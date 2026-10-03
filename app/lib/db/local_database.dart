import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import '../models/activity.dart';
import '../models/crop_season.dart';
import '../models/farm.dart';
import '../models/plot.dart';
import '../models/sync_queue_item.dart';
import '../services/sync_errors.dart';

/// SQLite cục bộ — nguồn sự thật khi nhập liệu offline (NFR-01).
///
/// **Tách theo người dùng bằng FILE RIÊNG** (`agricarbon_u_<uuid đã làm sạch>.db`):
/// user B không bao giờ thấy được cache/hàng đợi của user A, và đăng xuất KHÔNG
/// xoá file của A — đăng nhập lại vẫn còn nguyên dữ liệu cũ. `client_event_id`
/// (JWT, key) KHÔNG bao giờ dùng làm tên file.
///
/// **File `agricarbon.db` cũ (một file dùng chung, thiết kế trước Prompt 3):**
/// KHÔNG được đọc/nhập tự động. File đó không có cột `owner_user_id` ở bất kỳ
/// bảng nào nên không thể quy dữ liệu về đúng chủ một cách an toàn — nhập bừa sẽ
/// rò dữ liệu của user này sang tài khoản user khác. Bản MVP 1a chưa từng
/// compile/chạy (commit `c6e8b97`) nên trên thực tế file này không chứa dữ liệu
/// thật; nếu môi trường nào có, giữ nguyên file và quyết định nhập thủ công.
///
/// Đối tượng này là một *facade ổn định*: các màn giữ tham chiếu `services.db`
/// cố định, còn `Database` bên trong bị đóng/mở lại khi đổi user.
/// Mệnh đề chọn bản ghi hàng đợi CÒN đáng gửi lại.
///
/// `pending` luôn được chọn. `failed` chỉ được chọn lại khi lỗi lần trước là
/// TẠM THỜI **và** chưa vượt trần số lần thử. Trước đây mệnh đề là
/// `sync_state in ('pending','failed')`, nên một bản ghi bị RLS từ chối hoặc
/// sai dữ liệu bị chọn lại ở MỌI vòng đồng bộ, mãi mãi — bộ phân loại lỗi đã
/// có sẵn và đúng, nó chỉ chưa được dùng làm cổng chặn.
String _retryableWhere(
    {String prefix = '', String errorColumn = 'sync_error_code'}) {
  final p = prefix.isEmpty ? '' : '$prefix.';
  final codes = kTransientErrorCodes.map((c) => "'$c'").join(', ');
  return "(${p}sync_state = 'pending' "
      "or (${p}sync_state = 'failed' "
      "and coalesce($p$errorColumn, 'unknown') in ($codes) "
      "and ${p}retry_count < $kMaxSyncAttempts))";
}

class LocalDatabase {
  LocalDatabase({DatabaseFactory? factory, String? directoryOverride})
      : _factory = factory,
        _directoryOverride = directoryOverride;

  /// Chỉ dùng trong test (sqflite_common_ffi). Production để null → dùng
  /// `openDatabase` mặc định của sqflite.
  final DatabaseFactory? _factory;
  final String? _directoryOverride;

  static const int schemaVersion = 5;

  Database? _db;
  String? _openUserId;

  bool get isOpen => _db != null;

  /// UUID (đã làm sạch) của user mà DB đang mở cho — null nếu chưa mở.
  String? get openUserKey => _openUserId;

  Database get _require {
    final db = _db;
    if (db == null) {
      throw StateError(
        'LocalDatabase chưa được mở cho người dùng nào. '
        'openForUser() phải chạy sau khi đăng nhập.',
      );
    }
    return db;
  }

  /// Chỉ giữ ký tự an toàn cho tên file. UUID Supabase → 32 ký tự hex.
  static String sanitizeUserId(String userId) {
    final safe = userId.replaceAll(RegExp('[^A-Za-z0-9]'), '');
    if (safe.isEmpty) {
      throw ArgumentError('user id rỗng sau khi làm sạch: không mở được DB');
    }
    return safe;
  }

  Future<String> _pathFor(String safeUserId) async {
    final dir = _directoryOverride ?? await getDatabasesPath();
    return p.join(dir, 'agricarbon_u_$safeUserId.db');
  }

  /// Mở đúng "vùng dữ liệu" của user. Đóng DB cũ trước (nếu khác user), chạy
  /// migration nếu cần, rồi đưa các bản ghi bị kẹt `syncing` (do crash) về
  /// `pending`.
  Future<void> openForUser(String userId) async {
    final safe = sanitizeUserId(userId);
    if (_db != null && _openUserId == safe) return;
    await close();

    final path = await _pathFor(safe);
    final options = OpenDatabaseOptions(
      version: schemaVersion,
      onConfigure: (db) => db.execute('PRAGMA foreign_keys = ON'),
      onCreate: (db, version) => _createSchemaLatest(db),
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) await _upgradeV1ToV2(db);
        if (oldVersion < 3) await _upgradeV2ToV3(db);
        if (oldVersion < 4) await _upgradeV3ToV4(db);
        if (oldVersion < 5) await _upgradeV4ToV5(db);
      },
      singleInstance: _factory == null,
    );
    _db = _factory != null
        ? await _factory.openDatabase(path, options: options)
        : await openDatabase(
            path,
            version: options.version!,
            onConfigure: options.onConfigure,
            onCreate: options.onCreate,
            onUpgrade: options.onUpgrade,
          );
    _openUserId = safe;
    await _requeueStuck(_db!);
  }

  Future<void> close() async {
    final db = _db;
    _db = null;
    _openUserId = null;
    await db?.close();
  }

  // -- Schema ---------------------------------------------------------------

  Future<void> _createSchemaLatest(Database db) async {
    await db.execute('''
      create table farms (
        id text primary key,
        cooperative_id text not null,
        farm_code text not null,
        farm_name text not null,
        province_name text,
        district_name text,
        commune_name text,
        updated_at text
      )
    ''');
    await db.execute('''
      create table plots (
        id text primary key,
        server_id text,
        farm_id text not null,
        plot_code text not null,
        name text not null,
        area_ha real not null,
        latitude real,
        longitude real,
        sync_state text not null default 'pending',
        sync_error_code text,
        retry_count integer not null default 0,
        last_attempt_at text,
        synced_at text,
        created_at text not null,
        updated_at text not null
      )
    ''');
    await db.execute('''
      create table crop_seasons (
        id text primary key,
        server_id text,
        plot_id text not null,
        season_code text not null,
        crop_type text not null default 'rice',
        variety_name text,
        planting_date text,
        expected_harvest_date text,
        actual_harvest_date text,
        default_irrigation_method text,
        ipcc_water_regime text,
        pre_season_water_regime text,
        cultivation_days integer,
        drainage_event_count integer,
        status text not null default 'planned',
        sync_state text not null default 'pending',
        sync_error_code text,
        retry_count integer not null default 0,
        last_attempt_at text,
        synced_at text,
        created_at text not null,
        updated_at text not null
      )
    ''');
    await db.execute('''
      create table activities (
        id text primary key,
        crop_season_id text not null,
        type text not null,
        occurred_at text not null,
        payload_json text not null,
        note text,
        sync_state text not null default 'pending',
        sync_error text,
        created_at text not null,
        server_activity_id text,
        deleted_locally integer not null default 0,
        retry_count integer not null default 0,
        last_attempt_at text,
        synced_at text
      )
    ''');
    await db.execute('''
      create table active_context (
        id integer primary key check (id = 1),
        farm_id text,
        plot_client_id text,
        crop_season_client_id text,
        updated_at text
      )
    ''');
    await db.execute('''
      create table meta (
        key text primary key,
        value text
      )
    ''');
    await _createIndexes(db);
  }

  /// v2 → v3: thêm bảng `meta` (key/value nhỏ: last_sync_at, full_name đã cache,
  /// carbon đã cache theo vụ). Additive.
  Future<void> _upgradeV2ToV3(Database db) async {
    await db.execute('''
      create table if not exists meta (
        key text primary key,
        value text
      )
    ''');
  }

  /// v3 → v4: cột tombstone cho Activity (xoá bản ghi ĐÃ đồng bộ → giữ local,
  /// đẩy `deleted_at` lên server, xoá hẳn sau khi server xác nhận). Additive.
  Future<void> _upgradeV3ToV4(Database db) async {
    try {
      await db.execute(
        'alter table activities add column deleted_locally integer not null default 0',
      );
    } on DatabaseException catch (e) {
      if (!e.toString().toLowerCase().contains('duplicate column')) rethrow;
    }
  }

  /// v4 → v5: metadata máy đồng bộ cho Activity (`retry_count`, `last_attempt_at`,
  /// `synced_at`) + `synced_at` cho Plot / Crop Season — để màn "Gửi dữ liệu"
  /// hiện đúng số lần thử và mốc gửi thành công. Additive (ADD COLUMN, có mặc
  /// định / cho NULL).
  Future<void> _upgradeV4ToV5(Database db) async {
    Future<void> add(String table, String column, String type) async {
      try {
        await db.execute('alter table $table add column $column $type');
      } on DatabaseException catch (e) {
        if (!e.toString().toLowerCase().contains('duplicate column')) rethrow;
      }
    }

    await add('activities', 'retry_count', 'integer not null default 0');
    await add('activities', 'last_attempt_at', 'text');
    await add('activities', 'synced_at', 'text');
    await add('plots', 'synced_at', 'text');
    await add('crop_seasons', 'synced_at', 'text');
  }

  Future<void> _createIndexes(Database db) async {
    const stmts = [
      'create index if not exists idx_plots_farm on plots(farm_id)',
      'create index if not exists idx_plots_sync on plots(sync_state)',
      'create index if not exists idx_seasons_plot on crop_seasons(plot_id)',
      'create index if not exists idx_seasons_sync on crop_seasons(sync_state)',
      'create index if not exists idx_activities_crop on activities(crop_season_id)',
      'create index if not exists idx_activities_sync on activities(sync_state)',
    ];
    for (final s in stmts) {
      await db.execute(s);
    }
  }

  /// v1 → v2: CHỈ thêm cột / thêm bảng / backfill. Không DROP, không xoá dữ liệu.
  Future<void> _upgradeV1ToV2(Database db) async {
    final now = DateTime.now().toIso8601String();

    Future<void> add(String table, String column, String type) async {
      // sqflite không có "add column if not exists" — bắt lỗi trùng cột.
      try {
        await db.execute('alter table $table add column $column $type');
      } on DatabaseException catch (e) {
        if (!e.toString().toLowerCase().contains('duplicate column')) rethrow;
      }
    }

    // farms
    await add('farms', 'province_name', 'text');
    await add('farms', 'district_name', 'text');
    await add('farms', 'commune_name', 'text');
    await add('farms', 'updated_at', 'text');

    // plots
    await add('plots', 'server_id', 'text');
    await add('plots', 'latitude', 'real');
    await add('plots', 'longitude', 'real');
    await add('plots', 'sync_state', "text not null default 'pending'");
    await add('plots', 'sync_error_code', 'text');
    await add('plots', 'retry_count', 'integer not null default 0');
    await add('plots', 'last_attempt_at', 'text');
    await add('plots', 'created_at', "text not null default ''");
    await add('plots', 'updated_at', "text not null default ''");

    // crop_seasons
    await add('crop_seasons', 'server_id', 'text');
    await add('crop_seasons', 'crop_type', "text not null default 'rice'");
    await add('crop_seasons', 'actual_harvest_date', 'text');
    await add('crop_seasons', 'default_irrigation_method', 'text');
    await add('crop_seasons', 'ipcc_water_regime', 'text');
    await add('crop_seasons', 'pre_season_water_regime', 'text');
    await add('crop_seasons', 'cultivation_days', 'integer');
    await add('crop_seasons', 'drainage_event_count', 'integer');
    await add('crop_seasons', 'sync_state', "text not null default 'pending'");
    await add('crop_seasons', 'sync_error_code', 'text');
    await add('crop_seasons', 'retry_count', 'integer not null default 0');
    await add('crop_seasons', 'last_attempt_at', 'text');
    await add('crop_seasons', 'created_at', "text not null default ''");
    await add('crop_seasons', 'updated_at', "text not null default ''");

    // Backfill từ cột cũ `pending_create` (nếu có). Bản ghi đã đồng bộ ở thiết
    // kế cũ đã ghi đè `id` bằng server id → coi id là server_id luôn.
    Future<void> backfill(String table) async {
      final cols = await db.rawQuery('pragma table_info($table)');
      final hasPendingCreate = cols.any((c) => c['name'] == 'pending_create');
      if (hasPendingCreate) {
        await db.execute(
          "update $table set sync_state = case when pending_create = 1 "
          "then 'pending' else 'synced' end",
        );
        await db.execute(
          'update $table set server_id = id where pending_create = 0',
        );
      }
      await db.execute(
        "update $table set created_at = ? where created_at is null or created_at = ''",
        [now],
      );
      await db.execute(
        "update $table set updated_at = ? where updated_at is null or updated_at = ''",
        [now],
      );
    }

    await backfill('plots');
    await backfill('crop_seasons');

    await db.execute('''
      create table if not exists active_context (
        id integer primary key check (id = 1),
        farm_id text,
        plot_client_id text,
        crop_season_client_id text,
        updated_at text
      )
    ''');
    await _createIndexes(db);
  }

  Future<void> _requeueStuck(Database db) async {
    for (final table in ['plots', 'crop_seasons', 'activities']) {
      await db.execute(
        "update $table set sync_state = 'pending' where sync_state = 'syncing'",
      );
    }
  }

  // -- Farms (cache thuần — Farm là online-only) --------------------------

  /// Thay toàn bộ cache Farm bằng danh sách server trả về (RLS đã lọc). Farm
  /// biến mất khỏi server → biến mất khỏi cache (dùng cho ActiveContext dọn dẹp).
  Future<void> replaceFarms(List<Farm> farms) async {
    await _require.transaction((txn) async {
      await txn.delete('farms');
      for (final f in farms) {
        await txn.insert('farms', f.toRow());
      }
    });
  }

  Future<List<Farm>> listFarms() async {
    final rows = await _require.query('farms', orderBy: 'farm_name');
    return rows.map(Farm.fromRow).toList();
  }

  Future<Farm?> getFarm(String serverId) async {
    final rows = await _require.query('farms',
        where: 'id = ?', whereArgs: [serverId], limit: 1);
    return rows.isEmpty ? null : Farm.fromRow(rows.first);
  }

  // -- Plots -------------------------------------------------------------

  Future<void> upsertPlot(Plot plot) => _require.insert(
        'plots',
        plot.toRow(),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );

  Future<List<Plot>> listPlotsByFarm(String farmId) async {
    final rows = await _require.query(
      'plots',
      where: 'farm_id = ?',
      whereArgs: [farmId],
      orderBy: 'created_at',
    );
    return rows.map(Plot.fromRow).toList();
  }

  /// Tổng số ruộng + tổng diện tích (ha) trên máy — cho màn Tài khoản
  /// ("Ruộng của tôi: N ruộng · X ha"). Đọc THẲNG từ bảng `plots` local, không
  /// gọi mạng. Trả `(0, 0)` khi chưa có ruộng nào (UI hiện "Chưa có ruộng").
  Future<({int count, double areaHa})> plotSummary() async {
    final rows = await _require.rawQuery(
      'select count(*) as c, coalesce(sum(area_ha), 0) as a from plots',
    );
    final r = rows.isEmpty ? const <String, Object?>{} : rows.first;
    return (
      count: (r['c'] as int?) ?? 0,
      areaHa: ((r['a'] as num?) ?? 0).toDouble(),
    );
  }

  Future<Plot?> getPlotByClientId(String clientId) async {
    final rows = await _require.query('plots',
        where: 'id = ?', whereArgs: [clientId], limit: 1);
    return rows.isEmpty ? null : Plot.fromRow(rows.first);
  }

  Future<Plot?> getPlotByServerId(String serverId) async {
    final rows = await _require.query('plots',
        where: 'server_id = ?', whereArgs: [serverId], limit: 1);
    return rows.isEmpty ? null : Plot.fromRow(rows.first);
  }

  Future<List<Plot>> listPendingPlots() async {
    final rows = await _require.query(
      'plots',
      where: _retryableWhere(),
      orderBy: 'created_at',
    );
    return rows.map(Plot.fromRow).toList();
  }

  Future<Map<String, Object?>?> _firstRow(
    String table, {
    required String where,
    required List<Object?> args,
  }) async {
    final rows =
        await _require.query(table, where: where, whereArgs: args, limit: 1);
    return rows.isEmpty ? null : rows.first;
  }

  /// Trộn plot từ server vào cache. Khớp bản ghi local theo `server_id`, nếu
  /// chưa có thì theo khoá tự nhiên `(farm_id, plot_code)` — trường hợp thửa đã
  /// được máy khác đồng bộ, ta "nhận" `server_id` vào bản ghi local thay vì tạo
  /// trùng. Không tìm thấy → thêm mới (đã synced).
  Future<void> mergeServerPlot(Map<String, dynamic> serverRow) async {
    final serverId = serverRow['id'] as String;
    final existing =
        await _firstRow('plots', where: 'server_id = ?', args: [serverId]) ??
            await _firstRow('plots',
                where: 'farm_id = ? and plot_code = ?',
                args: [serverRow['farm_id'], serverRow['plot_code']]);
    final now = DateTime.now().toIso8601String();
    await _require.insert(
      'plots',
      {
        'id': existing?['id'] ?? serverId,
        'server_id': serverId,
        'farm_id': serverRow['farm_id'],
        'plot_code': serverRow['plot_code'],
        'name': serverRow['name'] ?? serverRow['plot_code'],
        'area_ha': (serverRow['area_ha'] as num).toDouble(),
        'latitude': (serverRow['latitude'] as num?)?.toDouble(),
        'longitude': (serverRow['longitude'] as num?)?.toDouble(),
        'sync_state': SyncState.synced.value,
        'sync_error_code': null,
        'retry_count': 0,
        'last_attempt_at': null,
        'created_at': existing?['created_at'] ?? now,
        'updated_at': now,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<void> markPlotSyncing(String clientId) => _require.update(
        'plots',
        {
          'sync_state': SyncState.syncing.value,
          'last_attempt_at': DateTime.now().toIso8601String(),
        },
        where: 'id = ?',
        whereArgs: [clientId],
      );

  Future<void> markPlotSynced(String clientId, String serverId) {
    final now = DateTime.now().toIso8601String();
    return _require.update(
      'plots',
      {
        'server_id': serverId,
        'sync_state': SyncState.synced.value,
        'sync_error_code': null,
        'synced_at': now,
        'updated_at': now,
      },
      where: 'id = ?',
      whereArgs: [clientId],
    );
  }

  Future<void> markPlotSyncFailed(String clientId, String errorCode) async {
    await _require.rawUpdate(
      'update plots set sync_state = ?, sync_error_code = ?, '
      'retry_count = retry_count + 1, last_attempt_at = ? where id = ?',
      [
        SyncState.failed.value,
        errorCode,
        DateTime.now().toIso8601String(),
        clientId,
      ],
    );
  }

  // -- Crop seasons ---------------------------------------------------------

  Future<void> upsertCropSeason(CropSeason season) => _require.insert(
        'crop_seasons',
        season.toRow(),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );

  Future<List<CropSeason>> listCropSeasonsByPlotClientId(
      String plotClientId) async {
    final rows = await _require.query(
      'crop_seasons',
      where: 'plot_id = ?',
      whereArgs: [plotClientId],
      orderBy: 'created_at',
    );
    return rows.map(CropSeason.fromRow).toList();
  }

  Future<CropSeason?> getCropSeasonByClientId(String clientId) async {
    final rows = await _require.query('crop_seasons',
        where: 'id = ?', whereArgs: [clientId], limit: 1);
    return rows.isEmpty ? null : CropSeason.fromRow(rows.first);
  }

  Future<CropSeason?> getCropSeasonByServerId(String serverId) async {
    final rows = await _require.query('crop_seasons',
        where: 'server_id = ?', whereArgs: [serverId], limit: 1);
    return rows.isEmpty ? null : CropSeason.fromRow(rows.first);
  }

  /// Trộn crop season từ server. `plot_id` server → tra ra `Plot.clientId` cục
  /// bộ; không tìm được thửa cha trong cache thì bỏ qua (không đặt được vào cây).
  /// Bản ghi local đang chờ đồng bộ KHÔNG bị đụng.
  Future<void> mergeServerCropSeason(Map<String, dynamic> serverRow) async {
    final serverId = serverRow['id'] as String;
    final parentPlot = await getPlotByServerId(serverRow['plot_id'] as String);
    if (parentPlot == null) return;
    final existing = await _firstRow('crop_seasons',
            where: 'server_id = ?', args: [serverId]) ??
        await _firstRow('crop_seasons',
            where: 'plot_id = ? and season_code = ?',
            args: [parentPlot.clientId, serverRow['season_code']]);
    // Vụ đã đồng bộ nhưng đang có thay đổi CHƯA GỬI (sửa offline chế độ nước /
    // số ngày canh tác...): bản server là bản cũ — ghi đè ở đây sẽ làm mất thay
    // đổi của người dùng trước khi nó kịp lên. Lượt push kế tiếp gửi bản local;
    // lượt pull sau đó mới nhận lại từ server.
    final localState = existing?['sync_state'] as String?;
    if (existing != null && localState != null && localState != SyncState.synced.value) {
      return;
    }
    final now = DateTime.now().toIso8601String();
    await _require.insert(
      'crop_seasons',
      {
        'id': existing?['id'] ?? serverId,
        'server_id': serverId,
        'plot_id': parentPlot.clientId,
        'season_code': serverRow['season_code'],
        'crop_type': serverRow['crop_type'] ?? 'rice',
        'variety_name': serverRow['variety_name'],
        'planting_date': serverRow['planting_date'],
        'expected_harvest_date': serverRow['expected_harvest_date'],
        'actual_harvest_date': serverRow['actual_harvest_date'],
        'default_irrigation_method': serverRow['default_irrigation_method'],
        'ipcc_water_regime': serverRow['ipcc_water_regime'],
        'pre_season_water_regime': serverRow['pre_season_water_regime'],
        'cultivation_days': serverRow['cultivation_days'],
        'drainage_event_count': serverRow['drainage_event_count'],
        'status': serverRow['status'] ?? 'planned',
        'sync_state': SyncState.synced.value,
        'sync_error_code': null,
        'retry_count': 0,
        'last_attempt_at': null,
        'created_at': existing?['created_at'] ?? now,
        'updated_at': now,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// Sau khi kéo Plot từ server (`pullFarmsPlotsSeasons`): xoá khỏi cache những
  /// Plot ĐÃ đồng bộ (`server_id` khác null, `sync_state = 'synced'`) mà server
  /// không còn trả về nữa — nếu không, thửa bị xoá / bị thu hồi quyền phía server
  /// sẽ nằm lại cache mãi mãi. TUYỆT ĐỐI không đụng bản ghi đang chờ đồng bộ
  /// (`pending` / `failed`) hay chưa có `server_id`. Trả về số hàng đã xoá.
  Future<int> reconcilePulledPlots(Set<String> serverIds) async {
    final rows = await _require.query(
      'plots',
      columns: ['id', 'server_id'],
      where: "server_id is not null and sync_state = 'synced'",
    );
    var removed = 0;
    for (final r in rows) {
      if (!serverIds.contains(r['server_id'] as String)) {
        await _require.delete('plots', where: 'id = ?', whereArgs: [r['id']]);
        removed++;
      }
    }
    return removed;
  }

  /// Như [reconcilePulledPlots] nhưng cho Crop Season.
  Future<int> reconcilePulledCropSeasons(Set<String> serverIds) async {
    final rows = await _require.query(
      'crop_seasons',
      columns: ['id', 'server_id'],
      where: "server_id is not null and sync_state = 'synced'",
    );
    var removed = 0;
    for (final r in rows) {
      if (!serverIds.contains(r['server_id'] as String)) {
        await _require
            .delete('crop_seasons', where: 'id = ?', whereArgs: [r['id']]);
        removed++;
      }
    }
    return removed;
  }

  Future<List<CropSeason>> listPendingCropSeasons() async {
    final rows = await _require.query(
      'crop_seasons',
      where: _retryableWhere(),
      orderBy: 'created_at',
    );
    return rows.map(CropSeason.fromRow).toList();
  }

  Future<void> markCropSeasonSyncing(String clientId) => _require.update(
        'crop_seasons',
        {
          'sync_state': SyncState.syncing.value,
          'last_attempt_at': DateTime.now().toIso8601String(),
        },
        where: 'id = ?',
        whereArgs: [clientId],
      );

  Future<void> markCropSeasonSynced(String clientId, String serverId) {
    final now = DateTime.now().toIso8601String();
    return _require.update(
      'crop_seasons',
      {
        'server_id': serverId,
        'sync_state': SyncState.synced.value,
        'sync_error_code': null,
        'synced_at': now,
        'updated_at': now,
      },
      where: 'id = ?',
      whereArgs: [clientId],
    );
  }

  /// Vụ `planned` (bản app cũ) đang có công việc chờ gửi -> `active` + chờ
  /// đồng bộ lại. Chỉ đụng vụ thực sự có công việc chưa lên hệ thống.
  Future<int> activatePlannedSeasonsWithPendingActivities() {
    return _require.rawUpdate(
      "update crop_seasons set status = 'active', sync_state = 'pending', "
      "updated_at = ? where status = 'planned' and id in ("
      "select crop_season_id from activities where deleted_locally = 0 "
      "and ${_retryableWhere(errorColumn: 'sync_error')})",
      [DateTime.now().toIso8601String()],
    );
  }

  Future<void> markCropSeasonSyncFailed(
      String clientId, String errorCode) async {
    await _require.rawUpdate(
      'update crop_seasons set sync_state = ?, sync_error_code = ?, '
      'retry_count = retry_count + 1, last_attempt_at = ? where id = ?',
      [
        SyncState.failed.value,
        errorCode,
        DateTime.now().toIso8601String(),
        clientId,
      ],
    );
  }

  // -- Activities ---------------------------------------------------------

  /// Tạo hoặc SỬA một hoạt động — ghi 1 hàng, trong transaction. KHÔNG gọi mạng.
  /// (Tên cũ `insertActivity` giữ lại làm alias cho code hiện có.)
  Future<void> saveActivity(Activity activity) => _require.transaction(
        (txn) => txn.insert(
          'activities',
          activity.toLocalMap(),
          conflictAlgorithm: ConflictAlgorithm.replace,
        ),
      );

  Future<void> insertActivity(Activity activity) => saveActivity(activity);

  Future<Activity?> getActivity(String clientEventId) async {
    final rows = await _require.query('activities',
        where: 'id = ?', whereArgs: [clientEventId], limit: 1);
    return rows.isEmpty ? null : Activity.fromLocalMap(rows.first);
  }

  Future<List<Activity>> listActivitiesByCropSeasonClientId(
    String cropSeasonClientId, {
    bool includeDeleted = false,
  }) async {
    final rows = await _require.query(
      'activities',
      where: includeDeleted
          ? 'crop_season_id = ?'
          : 'crop_season_id = ? and deleted_locally = 0',
      whereArgs: [cropSeasonClientId],
      orderBy: 'occurred_at desc',
    );
    return rows.map(Activity.fromLocalMap).toList();
  }

  /// Xoá hẳn 1 hàng (bản ghi CHƯA đồng bộ, hoặc tombstone đã được server xác nhận).
  Future<void> hardDeleteActivity(String clientEventId) => _require
      .delete('activities', where: 'id = ?', whereArgs: [clientEventId]);

  /// Đánh dấu tombstone: bản ghi ĐÃ đồng bộ bị xoá → giữ local, đưa về `pending`
  /// để đẩy `deleted_at` lên server ở lượt sync sau.
  Future<void> tombstoneActivity(String clientEventId) => _require.update(
        'activities',
        {
          'deleted_locally': 1,
          'sync_state': SyncState.pending.value,
          'sync_error': null,
        },
        where: 'id = ?',
        whereArgs: [clientEventId],
      );

  Future<List<Activity>> listPendingActivities() async {
    final rows = await _require.query(
      'activities',
      where: _retryableWhere(errorColumn: 'sync_error'),
      orderBy: 'created_at',
    );
    return rows.map(Activity.fromLocalMap).toList();
  }

  /// Cập nhật trạng thái đồng bộ 1 Activity + metadata máy:
  ///  - `syncing` → ghi `last_attempt_at`
  ///  - `synced`  → ghi `synced_at`, xoá lỗi
  ///  - `failed`  → `retry_count += 1`, ghi `last_attempt_at` + mã lỗi
  Future<void> updateActivitySyncState(
    String clientEventId, {
    required SyncState state,
    String? error,
    String? serverActivityId,
  }) async {
    final now = DateTime.now().toIso8601String();
    if (state == SyncState.failed) {
      await _require.rawUpdate(
        'update activities set sync_state = ?, sync_error = ?, '
        'retry_count = retry_count + 1, last_attempt_at = ? '
        '${serverActivityId != null ? ', server_activity_id = ? ' : ''}'
        'where id = ?',
        [
          SyncState.failed.value,
          error,
          now,
          if (serverActivityId != null) serverActivityId,
          clientEventId,
        ],
      );
      return;
    }
    await _require.update(
      'activities',
      {
        'sync_state': state.value,
        'sync_error': error,
        if (state == SyncState.syncing) 'last_attempt_at': now,
        if (state == SyncState.synced) 'synced_at': now,
        if (serverActivityId != null) 'server_activity_id': serverActivityId,
      },
      where: 'id = ?',
      whereArgs: [clientEventId],
    );
  }

  /// Hoạt động CHƯA gửi xong — kể cả bản đang gửi ('syncing'): đang gửi chưa
  /// phải đã gửi, lượt đó vẫn có thể hỏng.
  Future<int> countPendingActivities() async {
    final result = await _require.rawQuery(
      "select count(*) as c from activities where sync_state in ('pending', 'syncing', 'failed')",
    );
    return Sqflite.firstIntValue(result) ?? 0;
  }

  /// Danh sách MỌI bản ghi đang chờ gửi (plot → vụ → hoạt động), `pending` hoặc
  /// `failed`, đã gộp sẵn nhãn thửa để màn "Gửi dữ liệu" (SVG 23) render thẳng.
  /// Thứ tự: plot trước, rồi vụ, rồi hoạt động (mới nhất trên cùng) — khớp thứ
  /// tự đồng bộ và giúp người dùng thấy "gốc" trước "ngọn".
  Future<List<SyncQueueItem>> pendingSyncItems() async {
    final out = <SyncQueueItem>[];

    final plots = await _require.query(
      'plots',
      where: _retryableWhere(),
      orderBy: 'created_at',
    );
    out.addAll(plots.map(SyncQueueItem.fromPlotRow));

    final seasons = await _require.rawQuery('''
      select cs.*, p.plot_code as _plot_code, p.name as _plot_name
      from crop_seasons cs
      left join plots p on p.id = cs.plot_id
      where cs.sync_state in ('pending','failed')
      order by cs.created_at
    ''');
    out.addAll(seasons.map(SyncQueueItem.fromCropSeasonRow));

    final acts = await _require.rawQuery('''
      select a.*, cs.season_code as _season_code,
             p.plot_code as _plot_code, p.name as _plot_name
      from activities a
      left join crop_seasons cs on cs.id = a.crop_season_id
      left join plots p on p.id = cs.plot_id
      where a.sync_state in ('pending','failed')
      order by a.occurred_at desc
    ''');
    out.addAll(acts.map(SyncQueueItem.fromActivityRow));

    return out;
  }

  /// Tổng số bản ghi CHƯA gửi được (plot + vụ + hoạt động) — cho card "gửi dữ liệu".
  ///
  /// Gồm cả bản đang gửi ('syncing'): Trang chủ có thể đếm giữa một lượt gửi;
  /// nếu lượt đó hỏng mà không tiến triển thì không có `onSynced` nào báo đếm
  /// lại, nên con số phải đúng ngay từ lúc đếm — đang gửi chưa phải đã gửi.
  /// SQLite là nguồn đúng; mở lại app thì 'syncing' trở về 'pending'.
  Future<int> countAllPending() async {
    final result = await _require.rawQuery(
      "select "
      "(select count(*) from plots where sync_state in ('pending','syncing','failed')) + "
      "(select count(*) from crop_seasons where sync_state in ('pending','syncing','failed')) + "
      "(select count(*) from activities where sync_state in ('pending','syncing','failed')) "
      "as c",
    );
    return Sqflite.firstIntValue(result) ?? 0;
  }

  // -- Meta (key/value nhỏ, theo user) ---------------------------------

  Future<String?> getMeta(String key) async {
    final rows = await _require.query('meta',
        where: 'key = ?', whereArgs: [key], limit: 1);
    return rows.isEmpty ? null : rows.first['value'] as String?;
  }

  /// Mốc người dùng vừa sửa dữ liệu làm thay đổi đầu vào Carbon của vụ (lưu /
  /// xoá hoạt động, sửa thông tin phương pháp tính). Màn Carbon so với
  /// `calculated_at` của kết quả để báo "Dữ liệu đã thay đổi — cần tính lại";
  /// KHÔNG so công thức. Không dùng `updated_at` vì đồng bộ cũng ghi cột đó.
  Future<void> markCarbonInputsChanged(String cropSeasonClientId) =>
      setMeta('carbon.changed.$cropSeasonClientId', DateTime.now().toUtc().toIso8601String());

  Future<DateTime?> carbonInputsChangedAt(String cropSeasonClientId) async {
    final raw = await getMeta('carbon.changed.$cropSeasonClientId');
    return raw == null ? null : DateTime.tryParse(raw);
  }

  Future<void> setMeta(String key, String? value) async {
    if (value == null) {
      await _require.delete('meta', where: 'key = ?', whereArgs: [key]);
      return;
    }
    await _require.insert(
      'meta',
      {'key': key, 'value': value},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  // -- Active context ---------------------------------------------------

  Future<Map<String, String?>?> readActiveContext() async {
    final rows =
        await _require.query('active_context', where: 'id = 1', limit: 1);
    if (rows.isEmpty) return null;
    final r = rows.first;
    return {
      'farm_id': r['farm_id'] as String?,
      'plot_client_id': r['plot_client_id'] as String?,
      'crop_season_client_id': r['crop_season_client_id'] as String?,
    };
  }

  Future<void> writeActiveContext({
    String? farmId,
    String? plotClientId,
    String? cropSeasonClientId,
  }) =>
      _require.insert(
        'active_context',
        {
          'id': 1,
          'farm_id': farmId,
          'plot_client_id': plotClientId,
          'crop_season_client_id': cropSeasonClientId,
          'updated_at': DateTime.now().toIso8601String(),
        },
        conflictAlgorithm: ConflictAlgorithm.replace,
      );

  Future<void> clearActiveContext() =>
      _require.delete('active_context', where: 'id = 1');

  // -- Test helpers ---------------------------------------------------------

  /// CHỈ dùng cho test migration: mở DB ở schema v1 (bản đang commit trước
  /// Prompt 3) để rồi `openForUser` chạy `onUpgrade` thật.
  Future<void> debugOpenAtV1(String userId) async {
    assert(_factory != null, 'debugOpenAtV1 chỉ dùng với DatabaseFactory test');
    final safe = sanitizeUserId(userId);
    await close();
    final path = await _pathFor(safe);
    _db = await _factory!.openDatabase(
      path,
      options: OpenDatabaseOptions(
        version: 1,
        singleInstance: false,
        onCreate: (db, _) => _createSchemaV1(db),
      ),
    );
    _openUserId = safe;
  }

  /// CHỈ dùng cho test: chèn thô vào bảng đang mở.
  Future<void> debugInsertRaw(String table, Map<String, Object?> values) {
    assert(_factory != null, 'debugInsertRaw chỉ dùng trong test');
    return _require.insert(table, values);
  }

  static Future<void> _createSchemaV1(Database db) async {
    await db.execute('''
      create table farms (
        id text primary key, cooperative_id text not null,
        farm_code text not null, farm_name text not null
      )
    ''');
    await db.execute('''
      create table plots (
        id text primary key, farm_id text not null, plot_code text not null,
        name text not null, area_ha real not null,
        pending_create integer not null default 0
      )
    ''');
    await db.execute('''
      create table crop_seasons (
        id text primary key, plot_id text not null, season_code text not null,
        variety_name text, planting_date text, expected_harvest_date text,
        status text not null default 'planned',
        pending_create integer not null default 0
      )
    ''');
    await db.execute('''
      create table activities (
        id text primary key, crop_season_id text not null, type text not null,
        occurred_at text not null, payload_json text not null, note text,
        sync_state text not null default 'pending', sync_error text,
        created_at text not null, server_activity_id text
      )
    ''');
  }
}

import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart' as p;

import '../models/activity.dart';
import '../models/crop_season.dart';
import '../models/farm.dart';
import '../models/plot.dart';

/// SQLite cục bộ — nguồn sự thật khi nhập liệu offline (NFR-01).
///
/// KHÔNG replicate toàn bộ schema Supabase. Chỉ lưu đủ cho luồng mobile:
/// Farm/Plot/CropSeason (cache để hiển thị + tạo mới offline) và Activity
/// (nguồn ghi chính, có hàng đợi đồng bộ ngay trên bản ghi — xem activity.dart).
class LocalDatabase {
  LocalDatabase._(this._db);
  final Database _db;

  static LocalDatabase? _instance;

  static Future<LocalDatabase> open() async {
    if (_instance != null) return _instance!;
    final dbPath = await getDatabasesPath();
    final path = p.join(dbPath, 'agricarbon.db');
    final db = await openDatabase(
      path,
      version: 1,
      onCreate: (db, version) async {
        await db.execute('''
          create table farms (
            id text primary key,
            cooperative_id text not null,
            farm_code text not null,
            farm_name text not null
          )
        ''');
        await db.execute('''
          create table plots (
            id text primary key,
            farm_id text not null,
            plot_code text not null,
            name text not null,
            area_ha real not null,
            pending_create integer not null default 0
          )
        ''');
        await db.execute('''
          create table crop_seasons (
            id text primary key,
            plot_id text not null,
            season_code text not null,
            variety_name text,
            planting_date text,
            expected_harvest_date text,
            status text not null default 'planned',
            pending_create integer not null default 0
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
            server_activity_id text
          )
        ''');
        await db.execute('create index idx_activities_crop on activities(crop_season_id)');
        await db.execute('create index idx_activities_sync on activities(sync_state)');
      },
    );
    _instance = LocalDatabase._(db);
    return _instance!;
  }

  /// Chỉ dùng cho test — mở DB in-memory/riêng bằng factory tuỳ chỉnh.
  static Future<LocalDatabase> openWith(DatabaseFactory factory, String path) async {
    final db = await factory.openDatabase(
      path,
      options: OpenDatabaseOptions(
        version: 1,
        onCreate: (db, version) async {
          final tmp = LocalDatabase._(db);
          await tmp._createSchema();
        },
      ),
    );
    return LocalDatabase._(db);
  }

  Future<void> _createSchema() async {
    await _db.execute('''
      create table farms (
        id text primary key, cooperative_id text not null,
        farm_code text not null, farm_name text not null
      )
    ''');
    await _db.execute('''
      create table plots (
        id text primary key, farm_id text not null, plot_code text not null,
        name text not null, area_ha real not null, pending_create integer not null default 0
      )
    ''');
    await _db.execute('''
      create table crop_seasons (
        id text primary key, plot_id text not null, season_code text not null,
        variety_name text, planting_date text, expected_harvest_date text,
        status text not null default 'planned', pending_create integer not null default 0
      )
    ''');
    await _db.execute('''
      create table activities (
        id text primary key, crop_season_id text not null, type text not null,
        occurred_at text not null, payload_json text not null, note text,
        sync_state text not null default 'pending', sync_error text,
        created_at text not null, server_activity_id text
      )
    ''');
  }

  // -- Farms ----------------------------------------------------------------

  Future<void> upsertFarm(Farm farm) =>
      _db.insert('farms', farm.toLocalMap(), conflictAlgorithm: ConflictAlgorithm.replace);

  Future<List<Farm>> listFarms() async {
    final rows = await _db.query('farms');
    return rows.map(Farm.fromMap).toList();
  }

  // -- Plots ------------------------------------------------------------------

  Future<void> upsertPlot(Plot plot, {bool pendingCreate = false}) => _db.insert(
        'plots',
        {...plot.toLocalMap(), 'pending_create': pendingCreate ? 1 : 0},
        conflictAlgorithm: ConflictAlgorithm.replace,
      );

  Future<List<Plot>> listPlotsByFarm(String farmId) async {
    final rows = await _db.query('plots', where: 'farm_id = ?', whereArgs: [farmId]);
    return rows.map(Plot.fromMap).toList();
  }

  Future<List<Map<String, dynamic>>> listPendingPlots() =>
      _db.query('plots', where: 'pending_create = 1');

  Future<void> markPlotSynced(String localId, String serverId) async {
    await _db.transaction((txn) async {
      await txn.update('plots', {'pending_create': 0, 'id': serverId},
          where: 'id = ?', whereArgs: [localId]);
      // crop_seasons con tro plot_id cu -> cap nhat theo id moi cua plot.
      await txn.update('crop_seasons', {'plot_id': serverId},
          where: 'plot_id = ?', whereArgs: [localId]);
    });
  }

  // -- Crop seasons -------------------------------------------------------

  Future<void> upsertCropSeason(CropSeason season, {bool pendingCreate = false}) => _db.insert(
        'crop_seasons',
        {...season.toLocalMap(), 'pending_create': pendingCreate ? 1 : 0},
        conflictAlgorithm: ConflictAlgorithm.replace,
      );

  Future<List<CropSeason>> listCropSeasonsByPlot(String plotId) async {
    final rows =
        await _db.query('crop_seasons', where: 'plot_id = ?', whereArgs: [plotId]);
    return rows.map(CropSeason.fromMap).toList();
  }

  Future<List<Map<String, dynamic>>> listPendingCropSeasons() =>
      _db.query('crop_seasons', where: 'pending_create = 1');

  Future<void> markCropSeasonSynced(String localId, String serverId) async {
    await _db.transaction((txn) async {
      await txn.update('crop_seasons', {'pending_create': 0, 'id': serverId},
          where: 'id = ?', whereArgs: [localId]);
      await txn.update('activities', {'crop_season_id': serverId},
          where: 'crop_season_id = ?', whereArgs: [localId]);
    });
  }

  // -- Activities -----------------------------------------------------------

  Future<void> insertActivity(Activity activity) =>
      _db.insert('activities', activity.toLocalMap());

  Future<List<Activity>> listActivitiesByCropSeason(String cropSeasonId) async {
    final rows = await _db.query(
      'activities',
      where: 'crop_season_id = ?',
      whereArgs: [cropSeasonId],
      orderBy: 'occurred_at desc',
    );
    return rows.map(Activity.fromLocalMap).toList();
  }

  Future<List<Activity>> listPendingActivities() async {
    final rows = await _db.query(
      'activities',
      where: 'sync_state in (?, ?)',
      whereArgs: [SyncState.pending.value, SyncState.failed.value],
      orderBy: 'created_at asc',
    );
    return rows.map(Activity.fromLocalMap).toList();
  }

  Future<void> updateActivitySyncState(
    String id, {
    required SyncState state,
    String? error,
    String? serverActivityId,
  }) =>
      _db.update(
        'activities',
        {
          'sync_state': state.value,
          'sync_error': error,
          if (serverActivityId != null) 'server_activity_id': serverActivityId,
        },
        where: 'id = ?',
        whereArgs: [id],
      );

  Future<int> countPendingActivities() async {
    final result = await _db.rawQuery(
      "select count(*) as c from activities where sync_state in ('pending','failed')",
    );
    return Sqflite.firstIntValue(result) ?? 0;
  }
}

import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/services/connectivity_service.dart';
import 'package:agricarbon_app/services/device_service.dart';
import 'package:agricarbon_app/services/sync_coordinator.dart';
import 'package:agricarbon_app/services/sync_gateway.dart';
import 'package:agricarbon_app/services/sync_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:supabase_flutter/supabase_flutter.dart' show PostgrestException;

const _userA = 'aaaa1111-0000-0000-0000-000000000000';
const _userB = 'bbbb2222-0000-0000-0000-000000000000';

/// Gateway giả TRUNG THÀNH với select-rồi-ghi: activities keyed theo
/// `client_event_id` → gọi lại KHÔNG tạo bản ghi trùng.
class _FakeGateway implements SyncGateway {
  final serverActivities = <String, String>{}; // clientEventId -> serverId
  final serverDetails = <String, Map<String, dynamic>>{}; // serverId -> row
  final serverPlots = <String, Map<String, dynamic>>{};
  final serverSeasons = <String, Map<String, dynamic>>{};

  int activityInserts = 0;
  int detailUpserts = 0;
  int plotUpserts = 0;
  int seasonUpserts = 0;

  Object? plotThrows;
  Object? seasonThrows;
  Object? activityThrows;

  /// client_event_id → lỗi ném MỘT lần cho detail (rồi tự xoá).
  final detailThrowsOnce = <String, Object>{};

  @override
  Future<String> upsertPlot(Map<String, dynamic> row) async {
    if (plotThrows != null) throw plotThrows!;
    plotUpserts++;
    final key = '${row['farm_id']}|${row['plot_code']}';
    final id = serverPlots.putIfAbsent(key, () => {'id': 'srv-plot-$key'})['id']
        as String;
    return id;
  }

  @override
  Future<String> upsertCropSeason(Map<String, dynamic> row) async {
    if (seasonThrows != null) throw seasonThrows!;
    seasonUpserts++;
    final key = '${row['plot_id']}|${row['season_code']}';
    return serverSeasons.putIfAbsent(key, () => {'id': 'srv-cs-$key'})['id']
        as String;
  }

  @override
  Future<String> ensureDefaultBatch(String cropSeasonServerId) async =>
      'batch-$cropSeasonServerId';

  @override
  Future<String> upsertActivity(Map<String, dynamic> row) async {
    if (activityThrows != null) throw activityThrows!;
    final ceid = row['client_event_id'] as String;
    final existing = serverActivities[ceid];
    if (existing != null) return existing; // retry idempotent — không tạo trùng
    activityInserts++;
    final id = 'srv-act-$ceid';
    serverActivities[ceid] = id;
    return id;
  }

  @override
  Future<void> upsertActivityDetail(
      String table, Map<String, dynamic> row) async {
    final actId = row['activity_id'] as String;
    final ceid = actId.replaceFirst('srv-act-', '');
    final once = detailThrowsOnce.remove(ceid);
    if (once != null) throw once;
    detailUpserts++;
    serverDetails[actId] = {'table': table, ...row};
  }

  @override
  Future<int?> softDeleteActivity(String serverActivityId, DateTime at) async {
    final had = serverActivities.containsValue(serverActivityId);
    serverActivities.removeWhere((_, v) => v == serverActivityId);
    return had ? 1 : 0;
  }

  @override
  Future<String?> currentCooperativeId() async => 'org';
  @override
  Future<List<Map<String, dynamic>>> fetchFarms() async => [];
  @override
  Future<List<Map<String, dynamic>>> fetchPlots() async => [];
  @override
  Future<List<Map<String, dynamic>>> fetchCropSeasons() async => [];

  int get serverActivityCount => serverActivities.length;
}

late Directory _tmp;
late LocalDatabase _db;
late _FakeGateway _gw;
late SyncService _sync;
late ConnectivityService _conn;
late SyncCoordinator _co;

SyncCoordinator _makeCoordinator({Duration? debounce}) => SyncCoordinator(
      sync: _sync,
      db: _db,
      connectivity: _conn,
      connectivityDebounce: debounce ?? const Duration(milliseconds: 10),
    );

Future<void> _seedSyncedTree() async {
  final now = DateTime(2026, 3);
  await _db.upsertPlot(Plot(
    clientId: 'p1',
    serverId: 'srv-p1',
    farmId: 'f1',
    plotCode: 'P1',
    name: 'Thửa 1',
    areaHa: 1,
    syncState: SyncState.synced,
    createdAt: now,
    updatedAt: now,
  ));
  await _db.upsertCropSeason(CropSeason(
    clientId: 'cs1',
    serverId: 'srv-cs1',
    plotClientId: 'p1',
    seasonCode: 'S1',
    syncState: SyncState.synced,
    createdAt: now,
    updatedAt: now,
  ));
}

Activity _act(String id, {String type = 'fertilizer'}) => Activity(
      clientEventId: id,
      cropSeasonId: 'cs1',
      type: type,
      occurredAt: DateTime(2026, 3, 2, 7),
      payload: const {'fertilizer_name': 'Ure', 'amount_kg': 20.0},
      createdAt: DateTime(2026, 3, 2, 7),
    );

Future<void> _seedActivities(int n) async {
  for (var i = 0; i < n; i++) {
    await _db.saveActivity(_act('a$i'));
  }
}

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_coord');
    _db = LocalDatabase(
        factory: databaseFactoryFfi, directoryOverride: _tmp.path);
    await _db.openForUser(_userA);
    _gw = _FakeGateway();
    _sync = SyncService(_gw, _db, DeviceService.fixed('dev-1'));
    _conn = ConnectivityService.fixed(true, wifi: true);
    _co = _makeCoordinator();
  });
  tearDown(() async {
    _co.dispose();
    _conn.dispose();
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  test('20 bản ghi offline sống qua restart', () async {
    await _seedActivities(20);
    expect(await _db.countPendingActivities(), 20);
    await _db.close();

    final db2 = LocalDatabase(
        factory: databaseFactoryFfi, directoryOverride: _tmp.path);
    await db2.openForUser(_userA);
    expect(await db2.countPendingActivities(), 20);
    await db2.close();
    _db = LocalDatabase(
        factory: databaseFactoryFfi, directoryOverride: _tmp.path);
    await _db.openForUser(_userA); // để tearDown đóng được
  });

  test('sync: server nhận đúng 20; sync lần 2 vẫn 20 (không trùng)', () async {
    await _seedSyncedTree();
    await _seedActivities(20);
    await _co.attach();

    await _co.runSync(manual: true);
    expect(_gw.serverActivityCount, 20);
    expect(_gw.activityInserts, 20);
    expect(await _db.countPendingActivities(), 0);
    expect(_co.status, SyncStatus.allSynced);

    await _co.runSync(manual: true);
    expect(_gw.serverActivityCount, 20);
    expect(_gw.activityInserts, 20); // KHÔNG insert thêm
  });

  test(
      'crash sau khi server nhận (local chưa lưu server_id) -> retry không trùng',
      () async {
    await _seedSyncedTree();
    await _db.saveActivity(_act('a1'));
    // Giả lập: server ĐÃ có row cho a1 nhưng local vẫn pending, chưa có server_id.
    _gw.serverActivities['a1'] = 'srv-act-a1';
    _gw.activityInserts = 0;

    await _co.attach();
    await _co.runSync(manual: true);

    expect(_gw.activityInserts, 0); // tìm thấy row cũ, KHÔNG insert lại
    expect(_gw.serverActivityCount, 1);
    expect(await _db.countPendingActivities(), 0);
  });

  test('detail lỗi rồi retry -> synced, không tạo activity trùng', () async {
    await _seedSyncedTree();
    await _db.saveActivity(_act('a1'));
    _gw.detailThrowsOnce['a1'] =
        Exception('SocketException: Failed host lookup');
    await _co.attach();

    await _co.runSync(manual: true);
    expect(await _db.countPendingActivities(), 1); // a1 failed
    final failed = await _db.getActivity('a1');
    expect(failed!.syncState, SyncState.failed);
    expect(failed.retryCount, 1);

    await _co.runSync(manual: true); // detail giờ OK
    expect(await _db.countPendingActivities(), 0);
    expect(_gw.activityInserts, 1); // chỉ 1 activity trên server
    expect(_gw.serverActivityCount, 1);
  });

  test('cha (vụ) chưa sync -> con (activity) chưa được gửi', () async {
    final now = DateTime(2026, 3);
    // Plot pending + gateway ném khi đẩy plot -> plot không có server_id.
    await _db.upsertPlot(Plot(
      clientId: 'p1',
      farmId: 'f1',
      plotCode: 'P1',
      name: 'P1',
      areaHa: 1,
      createdAt: now,
      updatedAt: now,
    ));
    await _db.upsertCropSeason(CropSeason(
      clientId: 'cs1',
      plotClientId: 'p1',
      seasonCode: 'S1',
      createdAt: now,
      updatedAt: now,
    ));
    await _db.saveActivity(_act('a1'));
    _gw.plotThrows = Exception('SocketException: Failed host lookup');
    await _co.attach();

    await _co.runSync(manual: true);

    expect(_gw.activityInserts, 0); // activity chưa gửi
    expect(_gw.seasonUpserts, 0); // vụ cũng hoãn (plot chưa có server_id)
    final a = await _db.getActivity('a1');
    expect(a!.syncState, SyncState.pending); // vẫn chờ, KHÔNG phải failed
  });

  test('concurrent runSync -> single-flight (một lượt đẩy)', () async {
    await _seedSyncedTree();
    await _seedActivities(5);
    await _co.attach();

    final f1 = _co.runSync(manual: true);
    final f2 = _co.runSync(manual: true);
    await Future.wait([f1, f2]);

    expect(_gw.activityInserts, 5); // KHÔNG phải 10
    expect(_gw.serverActivityCount, 5);
  });

  test('phiên hết hạn khi gửi -> status authExpired', () async {
    await _seedSyncedTree();
    await _db.saveActivity(_act('a1'));
    _gw.activityThrows =
        const PostgrestException(message: 'JWT expired', code: 'PGRST301');
    await _co.attach();

    await _co.runSync(manual: true);
    expect(_co.status, SyncStatus.authExpired);
    expect(await _db.countPendingActivities(), 1); // giữ lại để thử lại
  });

  test('offline -> runSync không gọi mạng, status offline', () async {
    await _seedSyncedTree();
    await _seedActivities(3);
    _conn.debugSet(online: false);
    await _co.attach();

    final r = await _co.runSync(manual: true);
    expect(r, isNull);
    expect(_gw.activityInserts, 0);
    expect(_co.status, SyncStatus.offline);
  });

  test('"Chỉ Wi-Fi" + dữ liệu di động -> auto bỏ qua; override thì gửi',
      () async {
    await _seedSyncedTree();
    await _seedActivities(2);
    _conn.debugSet(online: true, wifi: false);
    await _db.setMeta('sync.wifi_only', '1');
    await _co.attach();
    expect(_co.wifiOnly, isTrue);
    expect(_co.blockedByWifiOnly, isTrue);

    await _co.runSync(); // auto
    expect(_gw.activityInserts, 0);

    await _co.runSync(manual: true, overrideWifiOnly: true);
    expect(_gw.activityInserts, 2);
  });

  test('có mạng lại -> tự gửi sau debounce', () async {
    await _seedSyncedTree();
    await _seedActivities(2);
    _conn.debugSet(online: false);
    await _co.attach();

    _conn.debugSet(online: true);
    await Future<void>.delayed(const Duration(milliseconds: 40));
    // chờ lượt sync do debounce khởi động
    for (var i = 0; i < 20 && _gw.activityInserts < 2; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    expect(_gw.activityInserts, 2);
  });

  test('attach đọc wifiOnly + lastSync + hàng đợi từ DB', () async {
    await _seedSyncedTree();
    await _seedActivities(3);
    await _db.setMeta('sync.wifi_only', '1');
    await _db.setMeta('sync.last_at', '2026-03-05T10:00:00.000Z');

    await _co.attach();
    expect(_co.wifiOnly, isTrue);
    expect(_co.lastSyncAt, isNotNull);
    expect(_co.queue.length, 3);
    expect(_co.pendingCount, 3);
  });

  test('user isolation: B không thấy hàng đợi của A', () async {
    await _seedSyncedTree();
    await _seedActivities(4);
    await _co.attach();
    expect(_co.queue.length, 4);

    await _db.openForUser(_userB); // đổi vùng dữ liệu
    _co.detach();
    await _co.attach();
    expect(_co.queue, isEmpty);
    expect(_co.pendingCount, 0);
  });
}

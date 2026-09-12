// Tầng dữ liệu local — chạy trên desktop bằng sqflite_common_ffi (không cần
// emulator). Mỗi test dùng một thư mục tạm riêng để file per-user không lẫn.

import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/methodology_enums.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _userA = 'aaaaaaaa-1111-2222-3333-444444444444';
const _userB = 'bbbbbbbb-5555-6666-7777-888888888888';

late Directory _tmp;
LocalDatabase _fresh() =>
    LocalDatabase(factory: databaseFactoryFfi, directoryOverride: _tmp.path);

Plot _plot({
  required String clientId,
  String farmId = 'farm-1',
  String code = 'A-01',
  double area = 0.5,
  SyncState state = SyncState.pending,
}) {
  final now = DateTime(2026, 2, 1);
  return Plot(
    clientId: clientId,
    farmId: farmId,
    plotCode: code,
    name: code,
    areaHa: area,
    syncState: state,
    createdAt: now,
    updatedAt: now,
  );
}

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_db_test');
  });
  tearDown(() async {
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  test('Plot 0,5 ha offline: lưu và còn nguyên sau khi đóng/mở lại DB',
      () async {
    final db = _fresh();
    await db.openForUser(_userA);
    await db.upsertPlot(_plot(clientId: 'p1', area: 0.5));
    await db.close();

    final db2 = _fresh();
    await db2.openForUser(_userA);
    final plots = await db2.listPlotsByFarm('farm-1');
    expect(plots, hasLength(1));
    expect(plots.first.areaHa, 0.5);
    expect(plots.first.serverId, isNull);
    expect(plots.first.syncState, SyncState.pending);
    await db2.close();
  });

  test('Crop Season offline: round-trip MỌI field phương pháp luận qua DB',
      () async {
    final db = _fresh();
    await db.openForUser(_userA);
    final season = CropSeason(
      clientId: 'cs1',
      plotClientId: 'p1',
      seasonCode: 'ĐX 2025-2026',
      varietyName: 'OM5451',
      plantingDate: DateTime(2025, 11, 20),
      expectedHarvestDate: DateTime(2026, 2, 28),
      actualHarvestDate: DateTime(2026, 3, 1),
      defaultIrrigationMethod: DefaultIrrigationMethod.awd,
      ipccWaterRegime: IpccWaterRegime.irrigatedMultipleDrainage,
      preSeasonWaterRegime: PreSeasonWaterRegime.floodedGt30d,
      cultivationDays: 101,
      drainageEventCount: 3,
      status: CropSeasonStatus.active,
      createdAt: DateTime(2025, 11, 1),
      updatedAt: DateTime(2025, 11, 1),
    );
    await db.upsertCropSeason(season);
    await db.close();

    final db2 = _fresh();
    await db2.openForUser(_userA);
    final loaded = (await db2.listCropSeasonsByPlotClientId('p1')).single;
    expect(loaded.seasonCode, 'ĐX 2025-2026');
    expect(loaded.varietyName, 'OM5451');
    expect(loaded.plantingDate, DateTime(2025, 11, 20));
    expect(loaded.expectedHarvestDate, DateTime(2026, 2, 28));
    expect(loaded.actualHarvestDate, DateTime(2026, 3, 1));
    expect(loaded.defaultIrrigationMethod, DefaultIrrigationMethod.awd);
    expect(loaded.ipccWaterRegime, IpccWaterRegime.irrigatedMultipleDrainage);
    expect(loaded.preSeasonWaterRegime, PreSeasonWaterRegime.floodedGt30d);
    expect(loaded.cultivationDays, 101);
    expect(loaded.drainageEventCount, 3);
    expect(loaded.status, CropSeasonStatus.active);
    await db2.close();
  });

  test('bản ghi kẹt "syncing" sau crash -> về "pending" khi mở lại', () async {
    final db = _fresh();
    await db.openForUser(_userA);
    await db.upsertPlot(_plot(clientId: 'p1'));
    await db.upsertCropSeason(CropSeason(
      clientId: 'cs1',
      plotClientId: 'p1',
      seasonCode: 'S1',
      createdAt: DateTime(2026),
      updatedAt: DateTime(2026),
    ));
    await db.markPlotSyncing('p1');
    await db.markCropSeasonSyncing('cs1');
    await db.close(); // giả lập tắt app giữa chừng

    final db2 = _fresh();
    await db2.openForUser(_userA);
    expect((await db2.getPlotByClientId('p1'))!.syncState, SyncState.pending);
    expect((await db2.getCropSeasonByClientId('cs1'))!.syncState,
        SyncState.pending);
    await db2.close();
  });

  test('User isolation: B không thấy dữ liệu của A; A đăng nhập lại vẫn còn',
      () async {
    final db = _fresh();
    await db.openForUser(_userA);
    await db.upsertPlot(_plot(clientId: 'pA', code: 'A-ONLY'));
    await db.close();

    // Đổi sang user B — cùng facade.
    await db.openForUser(_userB);
    expect(await db.listPlotsByFarm('farm-1'), isEmpty,
        reason: 'B không được thấy cache của A');
    await db.upsertPlot(_plot(clientId: 'pB', code: 'B-ONLY'));
    await db.close();

    // Quay lại A — dữ liệu cũ còn nguyên, KHÔNG bị đăng xuất xoá.
    await db.openForUser(_userA);
    final aPlots = await db.listPlotsByFarm('farm-1');
    expect(aPlots.map((p) => p.plotCode), ['A-ONLY']);
    await db.close();

    // File riêng cho từng user tồn tại.
    expect(
      Directory(_tmp.path)
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.db'))
          .length,
      2,
    );
  });

  test('close() KHÔNG xoá file (đăng xuất không mất pending data)', () async {
    final db = _fresh();
    await db.openForUser(_userA);
    await db.upsertPlot(_plot(clientId: 'p1'));
    await db.close();
    expect(db.isOpen, isFalse);

    await db.openForUser(_userA);
    expect(await db.listPlotsByFarm('farm-1'), hasLength(1));
    await db.close();
  });

  test('Migration v1 -> v2: thêm cột, thêm bảng, KHÔNG mất dữ liệu', () async {
    // 1. Dựng DB ở schema cũ và nhét dữ liệu.
    final legacy = _fresh();
    await legacy.debugOpenAtV1(_userA);
    await legacy.debugInsertRaw('plots', {
      'id': 'p-legacy',
      'farm_id': 'farm-1',
      'plot_code': 'OLD-1',
      'name': 'OLD-1',
      'area_ha': 1.25,
      'pending_create': 1,
    });
    await legacy.debugInsertRaw('plots', {
      'id': 'p-legacy-synced',
      'farm_id': 'farm-1',
      'plot_code': 'OLD-2',
      'name': 'OLD-2',
      'area_ha': 2.0,
      'pending_create': 0,
    });
    await legacy.close();

    // 2. Mở bằng LocalDatabase thật (version 2) -> onUpgrade chạy.
    final upgraded = _fresh();
    await upgraded.openForUser(_userA);
    final plots = await upgraded.listPlotsByFarm('farm-1');
    expect(plots.map((p) => p.plotCode).toSet(), {'OLD-1', 'OLD-2'});

    final pending = plots.firstWhere((p) => p.plotCode == 'OLD-1');
    final synced = plots.firstWhere((p) => p.plotCode == 'OLD-2');
    expect(pending.areaHa, 1.25);
    expect(pending.syncState, SyncState.pending);
    expect(pending.serverId, isNull);
    expect(synced.syncState, SyncState.synced);
    expect(synced.serverId, 'p-legacy-synced'); // backfill từ id cũ

    // Bảng mới dùng được.
    await upgraded.writeActiveContext(farmId: 'farm-1');
    expect((await upgraded.readActiveContext())!['farm_id'], 'farm-1');
    await upgraded.close();
  });

  test('activities: pending đếm đúng, đọc theo crop season client id',
      () async {
    final db = _fresh();
    await db.openForUser(_userA);
    for (var i = 0; i < 3; i++) {
      await db.insertActivity(Activity(
        clientEventId: 'a$i',
        cropSeasonId: 'cs1',
        type: 'irrigation',
        occurredAt: DateTime(2026, 2, i + 1),
        payload: const {'method': 'awd'},
        createdAt: DateTime.now(),
      ));
    }
    expect(await db.countPendingActivities(), 3);
    expect(await db.listActivitiesByCropSeasonClientId('cs1'), hasLength(3));
    await db.close();
  });

  test('gọi CRUD khi chưa openForUser -> StateError rõ ràng', () async {
    final db = _fresh();
    expect(() => db.listFarms(), throwsStateError);
  });

  test('reconcile sau pull: xoá Plot synced server bỏ, GIỮ pending (bug #8)',
      () async {
    final db = _fresh();
    await db.openForUser(_userA);

    // synced + server còn giữ
    await db.upsertPlot(_plot(clientId: 'keep', code: 'K'));
    await db.markPlotSynced('keep', 'S-keep');
    // synced + server ĐÃ xoá
    await db.upsertPlot(_plot(clientId: 'gone', code: 'G'));
    await db.markPlotSynced('gone', 'S-gone');
    // pending, chưa có server_id -> TUYỆT ĐỐI không đụng
    await db.upsertPlot(_plot(clientId: 'pend', code: 'P'));

    final removed = await db.reconcilePulledPlots({'S-keep'});
    expect(removed, 1);

    final left = await db.listPlotsByFarm('farm-1');
    expect(left.map((p) => p.clientId).toSet(), {'keep', 'pend'});
    await db.close();
  });

  test('reconcile CropSeason: chỉ xoá vụ synced không còn trên server (bug #8)',
      () async {
    final db = _fresh();
    await db.openForUser(_userA);
    final now = DateTime(2026, 3, 1);

    Future<void> season(String id, {String? serverId, required SyncState s}) =>
        db.upsertCropSeason(CropSeason(
          clientId: id,
          serverId: serverId,
          plotClientId: 'p1',
          seasonCode: id,
          syncState: s,
          createdAt: now,
          updatedAt: now,
        ));

    await season('keep', serverId: 'CS-keep', s: SyncState.synced);
    await season('gone', serverId: 'CS-gone', s: SyncState.synced);
    await season('local', s: SyncState.pending); // chưa lên server

    final removed = await db.reconcilePulledCropSeasons({'CS-keep'});
    expect(removed, 1);

    final left = await db.listCropSeasonsByPlotClientId('p1');
    expect(left.map((c) => c.clientId).toSet(), {'keep', 'local'});
    await db.close();
  });

  // ---- Prompt 8: hàng đợi gửi dữ liệu + metadata đồng bộ -----------------

  test(
      'updateActivitySyncState: failed bumps retry_count + last_attempt_at; '
      'synced ghi synced_at', () async {
    final db = _fresh();
    await db.openForUser(_userA);
    await db.saveActivity(Activity(
      clientEventId: 'a1',
      cropSeasonId: 'cs1',
      type: 'irrigation',
      occurredAt: DateTime(2026, 2, 2),
      payload: const {'method': 'awd'},
      createdAt: DateTime(2026, 2, 2),
    ));

    await db.updateActivitySyncState('a1',
        state: SyncState.failed, error: 'network');
    var a = await db.getActivity('a1');
    expect(a!.retryCount, 1);
    expect(a.lastAttemptAt, isNotNull);
    expect(a.syncedAt, isNull);

    await db.updateActivitySyncState('a1',
        state: SyncState.failed, error: 'network');
    a = await db.getActivity('a1');
    expect(a!.retryCount, 2); // cộng dồn

    await db.updateActivitySyncState('a1',
        state: SyncState.synced, serverActivityId: 'srv-a1');
    a = await db.getActivity('a1');
    expect(a!.syncState, SyncState.synced);
    expect(a.syncedAt, isNotNull);
    expect(a.retryCount, 2); // KHÔNG reset khi synced
    await db.close();
  });

  test('pendingSyncItems: gộp plot + vụ + activity, có nhãn thửa, bỏ synced',
      () async {
    final db = _fresh();
    await db.openForUser(_userA);
    final now = DateTime(2026, 2, 1);

    await db.upsertPlot(_plot(clientId: 'p1', code: 'A-01'));
    await db.upsertPlot(
        _plot(clientId: 'p-synced', code: 'A-09', state: SyncState.synced));
    await db.markPlotSynced('p-synced', 'srv-p9');
    await db.upsertCropSeason(CropSeason(
      clientId: 'cs1',
      plotClientId: 'p1',
      seasonCode: 'ĐX-1',
      syncState: SyncState.pending,
      createdAt: now,
      updatedAt: now,
    ));
    await db.saveActivity(Activity(
      clientEventId: 'a1',
      cropSeasonId: 'cs1',
      type: 'fertilizer',
      occurredAt: DateTime(2026, 2, 2, 7, 10),
      payload: const {'fertilizer_name': 'Ure', 'amount_kg': 18.0},
      createdAt: DateTime(2026, 2, 2, 7, 10),
    ));

    final items = await db.pendingSyncItems();
    final kinds = items.map((i) => i.kind).toList();
    expect(kinds.length, 3); // p1 + cs1 + a1 (p-synced bị loại)
    final act = items.firstWhere((i) => i.clientId == 'a1');
    expect(act.title, contains('Bón phân'));
    expect(act.title, contains('A-01')); // nhãn thửa qua join
    expect(act.subtitle, contains('18 kg')); // đơn vị thật, KHÔNG "mm"
    expect(act.subtitle, contains('02/02 07:10'));
    await db.close();
  });

  test('migration v4->v5: cột mới có, dữ liệu activity cũ KHÔNG mất', () async {
    // DB v1 -> chuỗi onUpgrade tới v5.
    final legacy = _fresh();
    await legacy.debugOpenAtV1(_userA);
    await legacy.debugInsertRaw('activities', {
      'id': 'a-old',
      'crop_season_id': 'cs-x',
      'type': 'harvest',
      'occurred_at': '2026-01-10T06:00:00.000',
      'payload_json': '{"yield_kg": 4000}',
      'sync_state': 'pending',
      'created_at': '2026-01-10T06:05:00.000',
    });
    await legacy.close();

    final up = _fresh();
    await up.openForUser(_userA);
    final a = await up.getActivity('a-old');
    expect(a, isNotNull);
    expect(a!.payload['yield_kg'], 4000);
    expect(a.retryCount, 0); // cột mới, mặc định
    expect(a.syncedAt, isNull);
    expect(a.syncState, SyncState.pending);
    await up.close();
  });
}

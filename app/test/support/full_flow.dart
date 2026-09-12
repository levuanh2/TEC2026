// Luồng nghiệm thu đầu-cuối phía mobile (offline-first), dùng chung cho:
//  - `test/app_flow_test.dart`             → `flutter test` (headless)
//  - `integration_test/app_flow_test.dart` → device/emulator thật
//
// Chạy ở TẦNG SERVICE/DB thật (sqflite_common_ffi) + mạng FAKE
// (`FakeSyncGateway`, `FakeCarbon`). KHÔNG service-role key, KHÔNG chạm
// Supabase/hosted. Phần render "thiếu sản lượng" trên UI được kiểm riêng ở
// `test/carbon_result_screen_test.dart`; ở đây chỉ chốt hợp đồng dữ liệu.
library;

import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/carbon_result.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/farm.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/services/active_context.dart';
import 'package:agricarbon_app/services/carbon_api_service.dart';
import 'package:agricarbon_app/services/device_service.dart';
import 'package:agricarbon_app/services/sync_gateway.dart';
import 'package:agricarbon_app/services/sync_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _userA = 'aaaa1111-0000-0000-0000-000000000000';
const _userB = 'bbbb2222-0000-0000-0000-000000000000';

/// Server "sự thật" giả — mỗi (device_id, client_event_id) map về đúng MỘT id
/// server (idempotent như partial unique index thật).
class FakeSyncGateway implements SyncGateway {
  final Set<String> visible = {};
  final List<Map<String, dynamic>> activityUpserts = [];
  int plotUpserts = 0;
  int cropSeasonUpserts = 0;

  @override
  Future<String> upsertPlot(Map<String, dynamic> row) async {
    plotUpserts++;
    return 'srv-plot-$plotUpserts';
  }

  @override
  Future<String> upsertCropSeason(Map<String, dynamic> row) async {
    cropSeasonUpserts++;
    return 'srv-cs-$cropSeasonUpserts';
  }

  @override
  Future<String> ensureDefaultBatch(String cropSeasonServerId) async =>
      'srv-batch';

  @override
  Future<String> upsertActivity(Map<String, dynamic> row) async {
    final id = 'srv-act-${row['client_event_id']}';
    activityUpserts.add(row);
    visible.add(id);
    return id;
  }

  @override
  Future<void> upsertActivityDetail(
      String table, Map<String, dynamic> row) async {}

  @override
  Future<int?> softDeleteActivity(String id, DateTime deletedAt) async {
    final had = visible.remove(id);
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
}

/// Carbon "backend" giả — hợp đồng theo `docs/FRONTEND_API_CONTRACT.md`.
class FakeCarbon extends CarbonApiService {
  FakeCarbon() : super.withTokenProvider((() => 'test-token'));
  bool withYield = true;

  CarbonResult _build() => CarbonResult(
        cropSeasonId: 'srv-cs-1',
        scenario: 'as_recorded',
        totalCo2eKg: 4200,
        yieldKg: withYield ? 5200 : null,
        co2ePerKg: withYield ? 4200 / 5200 : null, // null khi thiếu sản lượng
        breakdown: const [],
        methodologyName: 'IPCC 2019',
        efConfigVersion: 'ef-test-1',
        calculatedAt: '2026-03-20T00:00:00+00:00',
        warnings: const [],
      );

  @override
  Future<CarbonResult?> latest({
    required String cropSeasonId,
    String? scenario,
  }) async =>
      _build();
  @override
  Future<CarbonResult> calculate({
    required String cropSeasonId,
    String scenario = kScenarioAsRecorded,
  }) async =>
      _build();
}

const _payloads = <String, Map<String, dynamic>>{
  'seeding': {
    'seed_kg': 45.0,
    'seeding_method': 'sa_lan',
    'variety_name': 'OM'
  },
  'fertilizer': {
    'fertilizer_name': 'Urê',
    'amount_kg': 50.0,
    'nitrogen_percent': 46.0,
    'total_cost_vnd': 600000.0,
  },
  'irrigation': {
    'method': 'awd',
    'water_volume_m3': 320.0,
    'duration_minutes': 90,
    'water_level_cm': 4.0,
  },
  'harvest': {
    'yield_kg': 5200.0,
    'harvested_area_ha': 1.4,
    'moisture_percent': 22.0,
  },
};

/// 15 bước nghiệm thu. Chạy như một `test()` thường (async zone thật) — KHÔNG
/// cần WidgetTester.
Future<void> runAcceptanceFlow() async {
  sqfliteFfiInit();
  final tmp = await Directory.systemTemp.createTemp('agri_flow');
  LocalDatabase freshDb() =>
      LocalDatabase(factory: databaseFactoryFfi, directoryOverride: tmp.path);

  final gw = FakeSyncGateway();
  final carbon = FakeCarbon();
  final now = DateTime(2026, 3, 1, 6, 30);

  try {
    // 1-2) Mở app + "restore/login" user A → mở đúng file dữ liệu của user.
    var db = freshDb();
    await db.openForUser(_userA);
    final ctx = ActiveContext();
    await ctx.attach(db);

    // 3) Chọn Farm (Farm là online-only, nạp từ server khi có mạng).
    await db.replaceFarms([
      Farm(id: 'f1', cooperativeId: 'org', farmCode: 'HH', farmName: 'Hộ A'),
    ]);
    await ctx.setFarm(await db.getFarm('f1'));
    expect(ctx.farm, isNotNull);

    // 4) Tạo Plot OFFLINE — chưa có server id.
    await db.upsertPlot(Plot(
      clientId: 'p1',
      farmId: 'f1',
      plotCode: 'PL',
      name: 'Thửa A',
      areaHa: 1.4,
      syncState: SyncState.pending,
      createdAt: now,
      updatedAt: now,
    ));
    expect((await db.getPlotByClientId('p1'))!.serverId, isNull);

    // 5) Tạo Crop Season OFFLINE.
    await db.upsertCropSeason(CropSeason(
      clientId: 'cs1',
      plotClientId: 'p1',
      seasonCode: 'DX-1',
      syncState: SyncState.pending,
      createdAt: now,
      updatedAt: now,
    ));

    // 6) Nhập đủ Activity (4 loại, gồm harvest có sản lượng).
    for (final type in _payloads.keys) {
      await db.saveActivity(Activity(
        clientEventId: 'evt-$type',
        cropSeasonId: 'cs1',
        type: type,
        occurredAt: now,
        payload: Map<String, dynamic>.from(_payloads[type]!),
        createdAt: now,
      ));
    }
    expect(await db.countPendingActivities(), 4);
    expect(await db.countAllPending(), 6); // plot + cs + 4 act

    // 7) Đóng / mở lại app.
    await db.close();
    db = freshDb();
    await db.openForUser(_userA);
    await ctx.attach(db);

    // 8) Dữ liệu còn nguyên.
    expect(await db.countAllPending(), 6);
    final acts = await db.listActivitiesByCropSeasonClientId('cs1');
    expect(acts, hasLength(4));
    expect(
      acts.firstWhere((a) => a.type == 'harvest').payload['yield_kg'],
      5200.0,
    );

    // 9-10) Bật mạng → sync. Đúng thứ tự Plot → Crop Season → Activity.
    final sync = SyncService(gw, db, DeviceService.fixed('srv-device-A'));
    final s1 = await sync.syncAll();
    expect(s1.plotsSynced, 1);
    expect(s1.cropSeasonsSynced, 1);
    expect(s1.activitiesSynced, 4);
    expect(s1.hasErrors, isFalse);
    expect(gw.activityUpserts, hasLength(4));
    expect(await db.countAllPending(), 0);

    // 11) Sync lần hai KHÔNG tạo trùng.
    final s2 = await sync.syncAll();
    expect(s2.activitiesSynced, 0);
    expect(s2.plotsSynced, 0);
    expect(gw.activityUpserts, hasLength(4));

    // single-flight: thêm 1 activity mới, gọi syncAll() 2 lần đồng thời →
    // gateway chỉ nhận thêm ĐÚNG 1 (không xử lý hai lần).
    await db.saveActivity(Activity(
      clientEventId: 'evt-extra',
      cropSeasonId: 'cs1',
      type: 'fertilizer',
      occurredAt: now,
      payload: Map<String, dynamic>.from(_payloads['fertilizer']!),
      createdAt: now,
    ));
    final f1 = sync.syncAll();
    final f2 = sync.syncAll();
    await Future.wait([f1, f2]);
    expect(gw.activityUpserts, hasLength(5));

    // 12) Tính Carbon bằng fake contract → có kết quả, per-kg ra số > 0.
    final r = await carbon.latest(cropSeasonId: 'srv-cs-1');
    expect(r, isNotNull);
    expect(r!.co2ePerKg, isNotNull);
    expect(r.co2ePerKg! > 0, isTrue);

    // 13) Thiếu sản lượng → per-kg là null, KHÔNG bị ép về 0.
    //     (Render "Chưa có sản lượng" được kiểm ở carbon_result_screen_test.)
    carbon.withYield = false;
    final noYield = await carbon.latest(cropSeasonId: 'srv-cs-1');
    expect(noYield!.co2ePerKg, isNull);
    expect(noYield.yieldKg, isNull);

    // 14) Logout → đóng DB (KHÔNG xoá file).
    ctx.detach();
    await db.close();

    // 15) Login user B → vùng dữ liệu riêng, KHÔNG thấy gì của user A.
    final dbB = freshDb();
    await dbB.openForUser(_userB);
    expect(await dbB.listFarms(), isEmpty);
    expect(await dbB.countAllPending(), 0);
    expect(await dbB.listActivitiesByCropSeasonClientId('cs1'), isEmpty);
    await dbB.close();

    // User A đăng nhập lại → dữ liệu (đã đồng bộ) vẫn còn.
    final dbA2 = freshDb();
    await dbA2.openForUser(_userA);
    expect(await dbA2.listFarms(), hasLength(1));
    expect(await dbA2.listActivitiesByCropSeasonClientId('cs1'), hasLength(5));
    await dbA2.close();
  } finally {
    try {
      if (tmp.existsSync()) await tmp.delete(recursive: true);
    } catch (_) {
      // Windows giữ file .db một lúc sau close() — không phải lỗi test.
    }
  }
}

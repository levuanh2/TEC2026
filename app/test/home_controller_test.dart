import 'dart:async';
import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/carbon_result.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/crop_season_metrics.dart';
import 'package:agricarbon_app/models/farm.dart';
import 'package:agricarbon_app/models/methodology_enums.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/models/sync_state.dart';
import 'package:agricarbon_app/services/active_context.dart';
import 'package:agricarbon_app/services/carbon_api_service.dart';
import 'package:agricarbon_app/services/connectivity_service.dart';
import 'package:agricarbon_app/services/me_service.dart';
import 'package:agricarbon_app/services/metrics_service.dart';
import 'package:agricarbon_app/services/read_api.dart';
import 'package:agricarbon_app/shell/home_controller.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'dddddddd-0000-0000-0000-000000000000';

class _FakeMe extends MeService {
  _FakeMe() : super(ReadApi(() => 'token'));
  MeProfile? result;
  Object? error;
  Completer<void>? gate;
  int calls = 0;

  @override
  Future<MeProfile> fetch() async {
    calls++;
    if (gate != null) await gate!.future;
    final e = error;
    if (e != null) throw e;
    return result ??
        const MeProfile(
            userId: 'u', fullName: 'Người Dùng Thật', roles: ['farmer']);
  }
}

class _FakeCarbon extends CarbonApiService {
  _FakeCarbon() : super.withTokenProvider((() => 'token'));
  CarbonResult? result;
  Object? error;
  Completer<void>? gate;
  final askedIds = <String>[];

  @override
  Future<CarbonResult?> latest({
    required String cropSeasonId,
    String? scenario,
  }) async {
    askedIds.add(cropSeasonId);
    if (gate != null) await gate!.future;
    final e = error;
    if (e != null) throw e;
    return result;
  }
}

class _FakeMetrics extends MetricsService {
  _FakeMetrics() : super(ReadApi(() => 'token'));
  CropSeasonMetrics? result;
  Object? error;
  int calls = 0;
  final seasonIds = <String>[];

  Completer<void>? gate;

  @override
  Future<CropSeasonMetrics> fetchForCropSeason(
      String cropSeasonServerId) async {
    calls++;
    seasonIds.add(cropSeasonServerId);
    if (gate != null) await gate!.future;
    final e = error;
    if (e != null) throw e;
    return result ?? const CropSeasonMetrics();
  }
}

class _ThrowingContext extends ActiveContext {
  @override
  Future<void> setFarm(Farm? farm) async => throw StateError('boom');
}

late Directory _tmp;
late LocalDatabase _db;
late ActiveContext _ctx;
late _FakeMe _me;
late _FakeCarbon _carbon;
late _FakeMetrics _metrics;

Future<void> _seedFarm({String id = 'f1'}) => _db.replaceFarms([
      Farm(
          id: id,
          cooperativeId: 'org',
          farmCode: 'CODE-$id',
          farmName: 'Tên $id'),
    ]);

Future<void> _seedActivePlotSeason({
  String? serverId = 'srv-cs1',
  bool missingMethodology = false,
}) async {
  final now = DateTime(2026);
  final plot = Plot(
    clientId: 'p1',
    serverId: 'srv-p1',
    farmId: 'f1',
    plotCode: 'PL',
    name: 'PL',
    areaHa: 1,
    syncState: SyncState.synced,
    createdAt: now,
    updatedAt: now,
  );
  await _db.upsertPlot(plot);
  final season = CropSeason(
    clientId: 'cs1',
    serverId: serverId,
    plotClientId: 'p1',
    seasonCode: 'S1',
    syncState: serverId == null ? SyncState.pending : SyncState.synced,
    cultivationDays: missingMethodology ? null : 100,
    ipccWaterRegime:
        missingMethodology ? null : IpccWaterRegime.irrigatedMultipleDrainage,
    preSeasonWaterRegime:
        missingMethodology ? null : PreSeasonWaterRegime.floodedGt30d,
    createdAt: now,
    updatedAt: now,
  );
  await _db.upsertCropSeason(season);
  await _ctx.setFarm(await _db.getFarm('f1'));
  await _ctx.setPlot(await _db.getPlotByClientId('p1'));
  await _ctx.setCropSeason(await _db.getCropSeasonByClientId('cs1'));
}

CarbonResult _carbonResult({double? perKg}) => CarbonResult(
      cropSeasonId: 'srv-cs1',
      scenario: 'as_recorded',
      totalCo2eKg: 1990.0,
      yieldKg: perKg == null ? null : 3000,
      co2ePerKg: perKg,
      breakdown: const [],
      methodologyName: 'TEST',
      efConfigVersion: 'TEST',
      calculatedAt: '2026-09-09T00:00:00Z',
      warnings: const [],
    );

HomeController _make({
  required bool online,
  ActiveContext? ctx,
  ConnectivityService? conn,
}) =>
    HomeController(
      me: _me,
      carbon: _carbon,
      metrics: _metrics,
      db: _db,
      activeContext: ctx ?? _ctx,
      connectivity: conn ?? ConnectivityService.fixed(online),
    );

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_home_test');
    _db = LocalDatabase(
        factory: databaseFactoryFfi, directoryOverride: _tmp.path);
    await _db.openForUser(_user);
    _ctx = ActiveContext();
    await _ctx.attach(_db);
    _me = _FakeMe();
    _carbon = _FakeCarbon();
    _metrics = _FakeMetrics();
  });
  tearDown(() async {
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  test('online + có hộ + carbon có kết quả -> success, số liệu THẬT', () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    _carbon.result = _carbonResult(perKg: 0.52);
    final c = _make(online: true)..attach();

    await c.load();
    final s = c.snapshot;
    expect(s.status, HomeStatus.success);
    expect(s.fullName, 'Người Dùng Thật');
    expect(s.farmCount, 1);
    expect(s.carbon?.co2ePerKg, 0.52);
    expect(s.carbonFromCache, isFalse);
    c.dispose();
  });

  test('online + KHÔNG có hộ -> empty', () async {
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.empty);
    c.dispose();
  });

  test('unauthorized khi /v1/me trả 401', () async {
    await _seedFarm();
    _me.error = ReadApiException(401, 'unauthenticated', 'x');
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.unauthorized);
    c.dispose();
  });

  test('partial: online nhưng /v1/me lỗi mạng -> vẫn render, có softError',
      () async {
    await _seedFarm();
    _me.error = Exception('SocketException: Failed host lookup');
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.partial);
    expect(c.snapshot.softError, isNotNull);
    expect(c.snapshot.farmCount, 1); // dữ liệu local vẫn còn
    c.dispose();
  });

  test('offline-with-cache: có hộ trong DB, không gọi mạng', () async {
    await _seedFarm();
    final c = _make(online: false)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.offlineWithCache);
    expect(_me.calls, 0);
    c.dispose();
  });

  test('offline-no-cache: DB rỗng + không mạng', () async {
    final c = _make(online: false)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.offlineNoCache);
    c.dispose();
  });

  test('refreshing: giữ dữ liệu cũ trong lúc tải lại', () async {
    await _seedFarm();
    _me.result =
        const MeProfile(userId: 'u', fullName: 'Tên A', roles: ['farmer']);
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.success);

    _me.gate = Completer<void>();
    final future = c.refresh();
    expect(c.snapshot.status, HomeStatus.refreshing);
    expect(c.snapshot.fullName, 'Tên A'); // cache còn nguyên
    _me.gate!.complete();
    await future;
    c.dispose();
  });

  test('error: load ném ngoài dự kiến -> giữ cache, status error', () async {
    await _seedFarm(); // 1 hộ -> auto-select -> _ThrowingContext.setFarm ném
    final throwingCtx = _ThrowingContext();
    await throwingCtx.attach(_db);
    final c = _make(online: true, ctx: throwingCtx)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.error);
    c.dispose();
  });

  test('null KHÔNG thành 0: carbon có nhưng co2e_per_kg null', () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    _carbon.result = _carbonResult(perKg: null); // chưa có sản lượng
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.carbon, isNotNull);
    expect(c.snapshot.carbon!.co2ePerKg, isNull);
    c.dispose();
  });

  test('vụ chưa đồng bộ (serverId null) -> KHÔNG gọi carbon API', () async {
    await _seedFarm();
    await _seedActivePlotSeason(serverId: null);
    _carbon.error = StateError('không được gọi');
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.success);
    expect(c.snapshot.carbon, isNull);
    c.dispose();
  });

  test('todo suy từ dữ liệu thật', () async {
    await _seedFarm();
    // Chưa chọn vụ -> chooseSeason.
    var c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.todo?.kind, HomeTodoKind.chooseSeason);
    c.dispose();

    // Có vụ nhưng thiếu methodology -> fillMissingData.
    await _seedActivePlotSeason(missingMethodology: true);
    c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.todo?.kind, HomeTodoKind.fillMissingData);
    c.dispose();

    // Có bản ghi chưa gửi -> pushPending (ưu tiên cao nhất).
    await _db.upsertPlot(Plot(
      clientId: 'p-pending',
      farmId: 'f1',
      plotCode: 'X',
      name: 'X',
      areaHa: 1,
      createdAt: DateTime(2026),
      updatedAt: DateTime(2026),
    ));
    c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.todo?.kind, HomeTodoKind.pushPending);
    expect(c.snapshot.todo?.pendingCount, greaterThan(0));
    c.dispose();
  });

  test('đổi ActiveContext -> Trang chủ theo vụ mới (không gọi mạng)', () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    _carbon.result = _carbonResult(perKg: 0.5);
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.season?.clientId, 'cs1');

    // Bỏ chọn vụ -> snapshot cập nhật, carbon về null, todo đổi.
    await _ctx.setCropSeason(null);
    await c.debugSettle();
    expect(c.snapshot.season, isNull);
    expect(c.snapshot.carbon, isNull);
    expect(c.snapshot.todo?.kind, HomeTodoKind.chooseSeason);
    c.dispose();
  });

  test('nhiều hộ -> KHÔNG tự chọn hộ', () async {
    await _db.replaceFarms([
      Farm(id: 'f1', cooperativeId: 'o', farmCode: 'A', farmName: 'A'),
      Farm(id: 'f2', cooperativeId: 'o', farmCode: 'B', farmName: 'B'),
    ]);
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.farm, isNull);
    expect(_ctx.farm, isNull);
    c.dispose();
  });

  test('đúng 1 hộ -> tự chọn (không mơ hồ)', () async {
    await _seedFarm();
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.farm?.id, 'f1');
    c.dispose();
  });

  test('load() gọi 2 lần (onUserActive + initState) -> chỉ 1 fetch (bug #6)',
      () async {
    await _seedFarm();
    final c = _make(online: true)..attach();
    await c.load();
    await c.load();
    expect(_me.calls, 1);

    // Sau đăng xuất thì mở lại cho user kế tiếp.
    c.resetForSignOut();
    await c.load();
    expect(_me.calls, 2);
    c.dispose();
  });

  test('mất mạng sau khi success -> hạ xuống offlineWithCache (bug #7)',
      () async {
    await _seedFarm();
    _me.result =
        const MeProfile(userId: 'u', fullName: 'Tên A', roles: ['farmer']);
    final conn = ConnectivityService.fixed(true);
    final c = _make(online: true, conn: conn)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.success);

    conn.debugSetOnline(false);
    await c.debugSettle();

    expect(c.snapshot.online, isFalse);
    expect(c.snapshot.status, HomeStatus.offlineWithCache);
    expect(c.snapshot.fullName, 'Tên A'); // cache còn nguyên
    c.dispose();
  });

  test('có mạng lại -> tự tải đầy đủ (bug #7)', () async {
    await _seedFarm();
    final conn = ConnectivityService.fixed(false);
    final c = _make(online: false, conn: conn)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.offlineWithCache);
    expect(_me.calls, 0);

    conn.debugSetOnline(true);
    await c.debugSettle();

    expect(_me.calls, 1); // gọi /v1/me khi có mạng lại
    expect(c.snapshot.status, HomeStatus.success);
    c.dispose();
  });

  // ---- Crop-season metrics (#6) ------------------------------------------

  test('online + vụ có server id -> gọi metrics ĐÚNG 1 lần, số THẬT', () async {
    await _seedFarm();
    await _seedActivePlotSeason(); // serverId 'srv-cs1'
    _metrics.result = const CropSeasonMetrics(
      yieldKg: 4200,
      waterM3: 3100,
      fertilizerKg: 250,
      dataCompleteness: {'water': true, 'fertilizer': true},
    );
    final c = _make(online: true)..attach();
    await c.load();

    expect(_metrics.calls, 1);
    expect(_metrics.seasonIds, ['srv-cs1']);
    expect(c.snapshot.metrics?.yieldKg, 4200);
    expect(c.snapshot.metrics?.waterM3, 3100);
    expect(c.snapshot.metricsFromCache, isFalse);
    c.dispose();
  });

  test('vụ CHƯA đồng bộ (serverId null) -> KHÔNG gọi metrics API', () async {
    await _seedFarm();
    await _seedActivePlotSeason(serverId: null);
    _metrics.error = StateError('không được gọi');
    final c = _make(online: true)..attach();
    await c.load();
    expect(_metrics.calls, 0);
    expect(c.snapshot.metrics, isNull);
    c.dispose();
  });

  test('offline -> dùng cache metrics, KHÔNG gọi mạng', () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    _metrics.result = const CropSeasonMetrics(yieldKg: 999);
    var c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.metrics?.yieldKg, 999);
    c.dispose();

    // Lần sau offline: đọc từ meta cache.
    _metrics.calls = 0;
    c = _make(online: false)..attach();
    await c.load();
    expect(_metrics.calls, 0);
    expect(c.snapshot.metrics?.yieldKg, 999);
    expect(c.snapshot.metricsFromCache, isTrue);
    c.dispose();
  });

  test('metrics 401 -> HomeStatus.unauthorized', () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    _metrics.error = ReadApiException(401, 'unauthenticated', 'x');
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.status, HomeStatus.unauthorized);
    c.dispose();
  });

  test('metrics lỗi mạng -> partial, GIỮ cache cũ', () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    _metrics.result = const CropSeasonMetrics(yieldKg: 500);
    var c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.metrics?.yieldKg, 500);
    c.dispose();

    c = _make(online: true)..attach();
    _metrics.error = Exception('SocketException: Failed host lookup');
    await c.load();
    expect(c.snapshot.status, HomeStatus.partial);
    expect(c.snapshot.metrics?.yieldKg, 500); // cache không mất
    c.dispose();
  });

  test('đổi active season -> KHÔNG dùng cache metrics của vụ cũ', () async {
    await _seedFarm();
    await _seedActivePlotSeason(); // cs1 / srv-cs1
    _metrics.result = const CropSeasonMetrics(yieldKg: 111);
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.metrics?.yieldKg, 111);

    // Bỏ chọn vụ -> recompute local, metrics phải về null (không giữ 111).
    await _ctx.setCropSeason(null);
    await c.debugSettle();
    expect(c.snapshot.season, isNull);
    expect(c.snapshot.metrics, isNull);
    c.dispose();
  });

  test('null KHÔNG thành 0: metrics trả field null', () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    _metrics.result = const CropSeasonMetrics(); // tất cả null
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.metrics, isNotNull);
    expect(c.snapshot.metrics!.yieldKg, isNull);
    expect(c.snapshot.metrics!.co2ePerKg, isNull);
    c.dispose();
  });

  test('2 lần rebuild (load rồi refresh) -> metrics gọi 2 lần, không hơn',
      () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    _metrics.result = const CropSeasonMetrics(yieldKg: 10);
    final c = _make(online: true)..attach();
    await c.load();
    await c.refresh();
    expect(_metrics.calls, 2);
    c.dispose();
  });

  test(
      'online: đổi sang vụ ĐÃ đồng bộ khác -> tự tải carbon/metrics vụ mới (#5)',
      () async {
    await _seedFarm();
    await _seedActivePlotSeason(); // cs1 / srv-cs1
    // Thêm vụ thứ hai đã đồng bộ trên cùng thửa.
    final now = DateTime(2026);
    await _db.upsertCropSeason(CropSeason(
      clientId: 'cs2',
      serverId: 'srv-cs2',
      plotClientId: 'p1',
      seasonCode: 'S2',
      syncState: SyncState.synced,
      createdAt: now,
      updatedAt: now,
    ));
    _metrics.result = const CropSeasonMetrics(yieldKg: 1);
    final c = _make(online: true)..attach();
    await c.load();
    expect(_metrics.seasonIds, ['srv-cs1']);

    _metrics.result = const CropSeasonMetrics(yieldKg: 2);
    await _ctx.setCropSeason(await _db.getCropSeasonByClientId('cs2'));
    await c.debugSettle();

    expect(c.snapshot.season?.clientId, 'cs2');
    expect(_metrics.seasonIds, ['srv-cs1', 'srv-cs2']); // tự gọi cho vụ mới
    expect(c.snapshot.metrics?.yieldKg, 2);
    c.dispose();
  });

  test('offline: đổi vụ -> KHÔNG gọi mạng (chỉ đọc cache local)', () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    final now = DateTime(2026);
    await _db.upsertCropSeason(CropSeason(
      clientId: 'cs2',
      serverId: 'srv-cs2',
      plotClientId: 'p1',
      seasonCode: 'S2',
      syncState: SyncState.synced,
      createdAt: now,
      updatedAt: now,
    ));
    final c = _make(online: false)..attach();
    await c.load();
    _metrics.calls = 0;

    await _ctx.setCropSeason(await _db.getCropSeasonByClientId('cs2'));
    await c.debugSettle();
    expect(_metrics.calls, 0);
    expect(c.snapshot.season?.clientId, 'cs2');
    c.dispose();
  });

  test('resetForSignOut xoá SẠCH snapshot user cũ (đổi tài khoản)', () async {
    await _seedFarm();
    await _seedActivePlotSeason();
    _me.result =
        const MeProfile(userId: 'A', fullName: 'Người A', roles: ['farmer']);
    _carbon.result = _carbonResult(perKg: 0.5);
    _metrics.result = const CropSeasonMetrics(yieldKg: 1234);
    final c = _make(online: true)..attach();
    await c.load();
    expect(c.snapshot.fullName, 'Người A');
    expect(c.snapshot.metrics?.yieldKg, 1234);

    c.resetForSignOut();

    final s = c.snapshot;
    expect(s.status, HomeStatus.loading);
    expect(s.fullName, isNull);
    expect(s.farm, isNull);
    expect(s.carbon, isNull);
    expect(s.metrics, isNull);
    expect(s.pendingCount, 0);
    c.dispose();
  });

  test(
      'auto-sync xong TRONG lúc Trang chủ đang tải -> số chờ gửi cập nhật, '
      'không phải đợi mở lại app', () async {
    await _seedFarm();
    await _seedActivePlotSeason(serverId: null); // vụ chờ gửi -> đếm 1
    final gate = Completer<void>();
    _me.gate = gate;

    final c = _make(online: true)..attach();
    final loading = c.load();
    // Chờ lượt tải tới /v1/me: lúc này nó đã đếm 1 bản ghi chờ gửi.
    while (_me.calls == 0) {
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }

    // Auto-sync đẩy xong vụ rồi báo Trang chủ, khi lượt tải còn treo.
    await _db.markCropSeasonSynced('cs1', 'srv-cs1');
    await c.markSynced();

    gate.complete();
    _me.gate = null;
    await loading;
    await c.debugSettle();

    expect(c.snapshot.pendingCount, 0);
    expect(c.snapshot.todo?.kind, isNot(HomeTodoKind.pushPending));
    c.dispose();
  });

  test(
      'Trang chủ đếm TRONG lúc đang gửi rồi lượt gửi hỏng -> vẫn đếm đúng '
      '(bản ghi đang gửi chưa phải đã gửi)', () async {
    await _seedFarm();
    await _seedActivePlotSeason(serverId: null); // vụ chờ gửi -> đếm 1
    // SyncService đánh dấu "đang gửi" trước khi gọi mạng.
    await _db.markCropSeasonSyncing('cs1');

    final c = _make(online: true)..attach();
    await c.load();
    await c.debugSettle();
    expect(c.snapshot.pendingCount, 1);

    // Lượt gửi hỏng, không tiến triển: không có onSynced/markSynced nào.
    await _db.markCropSeasonSyncFailed('cs1', 'network');
    expect(await _db.countAllPending(), 1);
    expect(c.snapshot.pendingCount, 1);
    expect(c.snapshot.todo?.kind, HomeTodoKind.pushPending);
    c.dispose();
  });

  group('race: response cũ KHÔNG được ghi đè sau khi ngữ cảnh đổi', () {
    Future<void> seedTwoSeasons() async {
      await _seedFarm();
      await _seedActivePlotSeason(); // cs1 -> srv-cs1, active
      final now = DateTime(2026);
      await _db.upsertCropSeason(CropSeason(
        clientId: 'cs2',
        serverId: 'srv-cs2',
        plotClientId: 'p1',
        seasonCode: 'S2',
        cultivationDays: 100,
        ipccWaterRegime: IpccWaterRegime.irrigatedMultipleDrainage,
        preSeasonWaterRegime: PreSeasonWaterRegime.floodedGt30d,
        syncState: SyncState.synced,
        createdAt: now,
        updatedAt: now,
      ));
    }

    test(
        'đang tải vụ A, đổi sang vụ B, A hoàn thành SAU -> snapshot cuối chỉ có B; '
        'API cho B gọi đúng 1 lần', () async {
      await seedTwoSeasons();
      // Vụ A: carbon bị giữ ở cổng. Vụ B: trả ngay khi tới lượt.
      final gateA = Completer<void>();
      _carbon.gate = gateA;
      _carbon.result = _carbonResult(perKg: 0.11); // dùng cho CẢ hai vụ
      _metrics.result = const CropSeasonMetrics(yieldKg: 111);

      final c = _make(online: true)..attach();
      final loading = c.load(); // _run cho vụ A, kẹt trong _build ở gateA

      // Đổi Active Crop Season sang B TRONG lúc request A còn treo.
      await Future<void>.delayed(Duration.zero);
      await _ctx.setCropSeason(await _db.getCropSeasonByClientId('cs2'));
      // Đổi kết quả để phân biệt: nếu B render, phải là số mới.
      _carbon.result = _carbonResult(perKg: 0.22);
      _metrics.result = const CropSeasonMetrics(yieldKg: 222);

      // Bây giờ mới cho response A hoàn thành.
      gateA.complete();
      _carbon.gate = null;
      await loading;
      await c.debugSettle();

      // Snapshot cuối phải là vụ B, KHÔNG phải A.
      expect(c.snapshot.season?.clientId, 'cs2');
      expect(c.snapshot.metrics?.yieldKg, 222);
      expect(c.snapshot.carbon?.co2ePerKg, 0.22);
      // Metrics cho vụ B (srv-cs2) chỉ gọi đúng 1 lần.
      expect(_metrics.seasonIds.where((s) => s == 'srv-cs2').length, 1);
      c.dispose();
    });

    test('logout TRONG lúc request A treo -> response A KHÔNG xuất hiện',
        () async {
      await _seedFarm();
      await _seedActivePlotSeason();
      final gateA = Completer<void>();
      _carbon.gate = gateA;
      _me.result =
          const MeProfile(userId: 'A', fullName: 'Người A', roles: ['farmer']);
      _carbon.result = _carbonResult(perKg: 0.9);
      _metrics.result = const CropSeasonMetrics(yieldKg: 999);

      final c = _make(online: true)..attach();
      final loading = c.load();
      await Future<void>.delayed(Duration.zero);

      // Đăng xuất trong lúc request A còn treo.
      c.resetForSignOut();
      expect(c.snapshot.status, HomeStatus.loading);

      gateA.complete();
      _carbon.gate = null;
      await loading;
      await c.debugSettle();

      // Dữ liệu user A KHÔNG được rò vào snapshot sau khi đã reset.
      expect(c.snapshot.status, HomeStatus.loading);
      expect(c.snapshot.fullName, isNull);
      expect(c.snapshot.carbon, isNull);
      expect(c.snapshot.metrics, isNull);
      c.dispose();
    });

    test('dispose TRONG lúc request treo -> KHÔNG emit sau dispose', () async {
      await _seedFarm();
      await _seedActivePlotSeason();
      final gateA = Completer<void>();
      _carbon.gate = gateA;
      final c = _make(online: true)..attach();
      final loading = c.load();
      await Future<void>.delayed(Duration.zero);
      c.dispose();
      gateA.complete();
      _carbon.gate = null;
      await loading;
      // Không ném, không cập nhật listener sau dispose (được đảm bảo bởi _emit).
      expect(
          c.snapshot.status, anyOf(HomeStatus.loading, HomeStatus.refreshing));
    });

    test(
        'đổi vụ B rồi C khi rerun B đang chờ -> snapshot cuối là C, '
        'load() future chờ tới hết chuỗi', () async {
      await seedTwoSeasons(); // cs1 active, cs2 tồn tại
      final now = DateTime(2026);
      await _db.upsertCropSeason(CropSeason(
        clientId: 'cs3',
        serverId: 'srv-cs3',
        plotClientId: 'p1',
        seasonCode: 'S3',
        cultivationDays: 100,
        ipccWaterRegime: IpccWaterRegime.irrigatedMultipleDrainage,
        preSeasonWaterRegime: PreSeasonWaterRegime.floodedGt30d,
        syncState: SyncState.synced,
        createdAt: now,
        updatedAt: now,
      ));
      _metrics.result = const CropSeasonMetrics(yieldKg: 1);
      final gateA = Completer<void>();
      _carbon.gate = gateA;

      final c = _make(online: true)..attach();
      final loading = c.load(); // _run cs1, kẹt ở gateA

      await Future<void>.delayed(Duration.zero);
      await _ctx.setCropSeason(await _db.getCropSeasonByClientId('cs2'));
      await Future<void>.delayed(Duration.zero);
      await _ctx.setCropSeason(await _db.getCropSeasonByClientId('cs3'));
      _metrics.result = const CropSeasonMetrics(yieldKg: 3);

      gateA.complete();
      _carbon.gate = null;
      await loading; // PHẢI chờ tới hết chuỗi rerun, không dừng ở no-op
      await c.debugSettle();

      expect(c.snapshot.season?.clientId, 'cs3');
      expect(c.snapshot.metrics?.yieldKg, 3);
      expect(_metrics.seasonIds.where((s) => s == 'srv-cs3').length, 1);
    });

    test('mất mạng trong lúc online request đang chạy -> snapshot cuối offline',
        () async {
      await _seedFarm();
      await _seedActivePlotSeason();
      final conn = ConnectivityService.fixed(true);
      final gateA = Completer<void>();
      _carbon.gate = gateA;
      _me.result = const MeProfile(
          userId: 'u', fullName: 'Người Dùng Thật', roles: ['farmer']);

      final c = _make(online: true, conn: conn)..attach();
      final loading = c.load();
      await Future<void>.delayed(Duration.zero);

      conn.debugSetOnline(false); // mất mạng giữa chừng
      await Future<void>.delayed(Duration.zero);

      gateA.complete();
      _carbon.gate = null;
      await loading;
      await c.debugSettle();

      // Response online cũ KHÔNG ghi đè; trạng thái cuối là offline.
      expect(
        c.snapshot.status,
        anyOf(HomeStatus.offlineWithCache, HomeStatus.offlineNoCache),
      );
      expect(c.snapshot.online, isFalse);
    });

    test(
        'request A treo -> resetForSignOut + detach -> DB đóng -> A trả sau: '
        'KHÔNG emit A, rerun signed-out KHÔNG chạm DB', () async {
      await _seedFarm();
      await _seedActivePlotSeason();
      final gateA = Completer<void>();
      _me.gate = gateA; // A's _build kẹt NGAY ở /v1/me
      _me.result =
          const MeProfile(userId: 'A', fullName: 'Người A', roles: ['farmer']);
      _carbon.result = _carbonResult(perKg: 0.7);

      final c = _make(online: true)..attach();
      final loading = c.load();
      await Future<void>.delayed(Duration.zero);
      final callsBefore = _me.calls; // = 1 (đang kẹt trong fetch)

      // Đúng thứ tự onUserInactive: resetForSignOut -> ... -> activeContext.detach -> DB close.
      c.resetForSignOut();
      _ctx.detach(); // phát _onContextChanged trong lúc request A còn treo
      await _db.close(); // DB đã đóng

      gateA.complete();
      _me.gate = null;
      await loading;
      await c.debugSettle();

      expect(c.snapshot.status, HomeStatus.loading);
      expect(c.snapshot.fullName, isNull);
      expect(c.snapshot.carbon, isNull);
      // Rerun signed-out KHÔNG chạy `_build` lần nữa → KHÔNG gọi lại /v1/me,
      // KHÔNG chạm DB đã đóng.
      expect(_me.calls, callsBefore);
      c.dispose();
    });

    test(
        'hai refresh liên tiếp -> không request chồng, future cuối chờ kết quả mới',
        () async {
      await _seedFarm();
      await _seedActivePlotSeason();
      final gate1 = Completer<void>();
      _carbon.gate = gate1;
      _carbon.result = _carbonResult(perKg: 0.1);

      final c = _make(online: true)..attach();
      final first = c.load();
      await Future<void>.delayed(Duration.zero);

      // refresh thứ hai khi lần đầu còn chạy.
      _carbon.result = _carbonResult(perKg: 0.9);
      final second = c.refresh();

      gate1.complete();
      _carbon.gate = null;
      await first;
      await second;
      await c.debugSettle();

      // Không có lượt thứ ba; snapshot cuối là kết quả mới nhất.
      expect(c.snapshot.carbon?.co2ePerKg, 0.9);
      c.dispose();
    });
  });
}

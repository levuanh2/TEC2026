import 'dart:async';
import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/carbon_result.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/screens/carbon_result_screen.dart';
import 'package:agricarbon_app/services/carbon_api_service.dart';
import 'package:agricarbon_app/services/carbon_cache.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'cc110000-0000-0000-0000-000000000000';

class _FakeCarbon extends CarbonApiService {
  _FakeCarbon() : super.withTokenProvider((() => 't'));

  final byScenario = <String, CarbonResult?>{};
  Object? latestError;
  Object? calcError;
  CarbonResult? calcResult;
  int calcCalls = 0;
  bool healthReady = true;
  List<String> scenarioList = kOfficialScenarios;
  final askedIds = <String>[];

  @override
  Future<List<String>> scenarios() async => scenarioList;

  @override
  Future<CarbonHealth?> health() async => CarbonHealth(
        status: 'ok',
        carbonProductionReady: healthReady,
        mrvCompliant: false,
        engineVersion: '0.2.0',
        efConfigVersion: 'ef-1',
        methodologyName: 'IPCC 2019',
        note: '',
      );

  @override
  Future<CarbonResult?> latest({
    required String cropSeasonId,
    String? scenario,
  }) async {
    askedIds.add(cropSeasonId);
    if (latestError != null) throw latestError!;
    return byScenario[scenario ?? kScenarioAsRecorded];
  }

  @override
  Future<CarbonResult> calculate({
    required String cropSeasonId,
    String scenario = kScenarioAsRecorded,
  }) async {
    calcCalls++;
    if (calcError != null) throw calcError!;
    return calcResult ?? _result(perKg: 0.4);
  }
}

CarbonResult _result({
  double? perKg = 0.5,
  double? total = 2000,
  List<CarbonBreakdownEntry>? breakdown,
  List<String> warnings = const [],
}) =>
    CarbonResult(
      cropSeasonId: 'srv-cs1',
      scenario: 'as_recorded',
      totalCo2eKg: total,
      yieldKg: perKg == null ? null : 4000,
      co2ePerKg: perKg,
      breakdown: breakdown ??
          const [
            CarbonBreakdownEntry(
                source: 'ch4_rice_cultivation',
                gas: 'ch4',
                co2eKg: 1500,
                formula: 'Eq 5.1'),
            CarbonBreakdownEntry(
                source: 'n2o_fertilizer_direct',
                gas: 'n2o',
                co2eKg: 500,
                formula: 'Eq 11.1'),
          ],
      methodologyName: 'IPCC 2019 Refinement',
      efConfigVersion: '0.2.0-ipcc-tier1',
      calculatedAt: '2026-09-08T00:00:00+00:00',
      warnings: warnings,
    );

late Directory _tmp;
late LocalDatabase _db;
late _FakeCarbon _api;
late CarbonCache _cache;

Widget _screen({String cs = 'cs1', VoidCallback? onSync}) => MaterialApp(
      theme: AgriCarbonTheme.light(),
      home: CarbonResultScreen(
        carbonApi: _api,
        cache: _cache,
        db: _db,
        cropSeasonClientId: cs,
        onOpenSync: onSync,
      ),
    );

/// Khung cao để `ListView` của màn dựng hết item (không lazy-cắt phần dưới) +
/// `pumpAndSettle` + vài frame để chuỗi tải scenario so sánh chạy xong hẳn.
Future<void> _settle(WidgetTester t) async {
  t.view.physicalSize = const Size(1000, 3000);
  t.view.devicePixelRatio = 1.0;
  addTearDown(t.view.resetPhysicalSize);
  addTearDown(t.view.resetDevicePixelRatio);
  await t.pumpAndSettle();
  for (var i = 0; i < 6; i++) {
    await t.pump(const Duration(milliseconds: 20));
  }
  await t.pumpAndSettle();
}

Future<void> _seedSeason({
  String? serverId = 'srv-cs1',
  int pendingActivities = 0,
}) async {
  final now = DateTime(2026, 3);
  await _db.upsertPlot(Plot(
    clientId: 'p1',
    serverId: 'srv-p1',
    farmId: 'f1',
    plotCode: 'A-01',
    name: 'Thửa 1',
    areaHa: 1,
    syncState: SyncState.synced,
    createdAt: now,
    updatedAt: now,
  ));
  await _db.upsertCropSeason(CropSeason(
    clientId: 'cs1',
    serverId: serverId,
    plotClientId: 'p1',
    seasonCode: 'ĐX-1',
    syncState: serverId == null ? SyncState.pending : SyncState.synced,
    createdAt: now,
    updatedAt: now,
  ));
  for (var i = 0; i < pendingActivities; i++) {
    await _db.saveActivity(Activity(
      clientEventId: 'a$i',
      cropSeasonId: 'cs1',
      type: 'fertilizer',
      occurredAt: now,
      payload: const {'fertilizer_name': 'Ure', 'amount_kg': 10.0},
      createdAt: now,
    ));
  }
}

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_carbon25');
    _db = LocalDatabase(
        factory: databaseFactoryFfiNoIsolate, directoryOverride: _tmp.path);
    await _db.openForUser(_user);
    _api = _FakeCarbon();
    _cache = CarbonCache(_db);
  });
  tearDown(() async {
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  testWidgets('vụ chưa đồng bộ -> CTA "Đi tới Gửi dữ liệu", KHÔNG gọi API',
      (tester) async {
    await _seedSeason(serverId: null);
    var synced = 0;
    await tester.pumpWidget(_screen(onSync: () => synced++));
    await _settle(tester);

    expect(find.textContaining('chưa đồng bộ'), findsOneWidget);
    expect(_api.askedIds, isEmpty); // KHÔNG gọi API bằng local UUID
    await tester.tap(find.text('Đi tới Gửi dữ liệu'));
    expect(synced, 1);
  });

  testWidgets('còn Activity chưa gửi -> chặn + CTA, không gọi API',
      (tester) async {
    await _seedSeason(pendingActivities: 3);
    await tester.pumpWidget(_screen(onSync: () {}));
    await _settle(tester);
    expect(find.textContaining('3 hoạt động chưa gửi'), findsOneWidget);
    expect(_api.askedIds, isEmpty);
  });

  testWidgets('gọi API bằng SERVER id, không phải client id', (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = _result();
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(_api.askedIds, everyElement('srv-cs1'));
    expect(_api.askedIds, isNot(contains('cs1')));
  });

  testWidgets('no_calculation -> empty state "Tính phát thải"', (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = null; // = no_calculation
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.textContaining('chưa được tính phát thải'), findsOneWidget);
    expect(
        find.widgetWithText(ElevatedButton, 'Tính phát thải'), findsOneWidget);
  });

  testWidgets('crop_not_found -> ErrorState (khác no_calculation)',
      (tester) async {
    await _seedSeason();
    _api.latestError = CarbonApiException(404, 'crop_not_found', 'x');
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.byType(ErrorState), findsOneWidget);
    expect(find.textContaining('chưa được tính phát thải'), findsNothing);
  });

  testWidgets('missing yield -> "Chưa có sản lượng...", KHÔNG "0"',
      (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = _result(perKg: null, total: 1990.5);
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.textContaining('Chưa có sản lượng'), findsOneWidget);
    expect(find.text('0'), findsNothing);
    expect(find.text('0,000'), findsNothing);
  });

  testWidgets('breakdown: % theo co2e_kg/total; cảnh báo khi lệch total',
      (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = _result(
      total: 2000,
      breakdown: const [
        CarbonBreakdownEntry(
            source: 'ch4_rice_cultivation',
            gas: 'ch4',
            co2eKg: 1500,
            formula: ''),
        CarbonBreakdownEntry(
            source: 'fuel_diesel', gas: 'co2', co2eKg: 100, formula: ''),
      ], // tổng 1600 != 2000 -> lệch
    );
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.text('75%'), findsOneWidget); // 1500/2000
    expect(find.textContaining('lệch tổng chung'), findsOneWidget);
    expect(
        find.textContaining('ch4_rice_cultivation'), findsWidgets); // mã thật
  });

  testWidgets('so sánh kịch bản CHỈ khi có cả AWD lẫn ngập liên tục',
      (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = _result(total: 1800);
    _api.byScenario[kScenarioAwd] = _result(total: 1600);
    _api.byScenario[kScenarioContinuousFlooding] = _result(total: 2000);
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.textContaining('So sánh kịch bản'), findsOneWidget);
    expect(find.textContaining('20%'), findsOneWidget); // (2000-1600)/2000
    expect(find.textContaining('KHÔNG phải mức giảm thực tế'), findsOneWidget);
  });

  testWidgets('thiếu 1 trong 2 kịch bản -> KHÔNG hiện so sánh', (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = _result();
    _api.byScenario[kScenarioAwd] = _result(total: 1600);
    // continuous_flooding = null
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.textContaining('So sánh kịch bản'), findsNothing);
  });

  testWidgets('health chưa sẵn sàng -> banner "chưa phải kết quả MRV"',
      (tester) async {
    await _seedSeason();
    _api.healthReady = false;
    _api.byScenario[kScenarioAsRecorded] = _result();
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.textContaining('CHƯA phải kết quả MRV'), findsOneWidget);
  });

  testWidgets('offline + có cache -> hiện cache + banner, KHÔNG xoá cache',
      (tester) async {
    await _seedSeason();
    await _cache.write(
        'srv-cs1', kScenarioAsRecorded, _result(perKg: 0.55, total: 2100));
    _api.latestError = Exception('SocketException: Failed host lookup');

    await tester.pumpWidget(_screen());
    await _settle(tester);

    expect(find.textContaining('0,55'), findsOneWidget); // số từ cache
    expect(find.textContaining('Đang xem số đã lưu'), findsOneWidget);
    // cache vẫn còn.
    expect(await _cache.read('srv-cs1', kScenarioAsRecorded), isNotNull);
  });

  testWidgets('session hết hạn + có cache -> banner đăng nhập lại, giữ số',
      (tester) async {
    await _seedSeason();
    await _cache.write('srv-cs1', kScenarioAsRecorded, _result(perKg: 0.6));
    _api.latestError = CarbonApiException(401, 'unauthenticated', 'x');
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.textContaining('hết hạn'), findsWidgets);
    expect(find.textContaining('0,6'), findsOneWidget);
  });

  testWidgets('unmount khi request treo -> KHÔNG setState sau dispose',
      (tester) async {
    await _seedSeason();
    final slow = _SlowCarbon();
    await tester.pumpWidget(MaterialApp(
      theme: AgriCarbonTheme.light(),
      home: CarbonResultScreen(
        carbonApi: slow,
        cache: _cache,
        db: _db,
        cropSeasonClientId: 'cs1',
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    // gỡ màn khi `latest()` còn treo.
    await tester.pumpWidget(const MaterialApp(home: SizedBox()));
    slow.gate.complete();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    expect(tester.takeException(), isNull);
  });
}

class _SlowCarbon extends CarbonApiService {
  _SlowCarbon() : super.withTokenProvider((() => 't'));
  final gate = Completer<void>();
  @override
  Future<List<String>> scenarios() async => kOfficialScenarios;
  @override
  Future<CarbonHealth?> health() async => null;
  @override
  Future<CarbonResult?> latest({
    required String cropSeasonId,
    String? scenario,
  }) async {
    await gate.future;
    return _result();
  }
}

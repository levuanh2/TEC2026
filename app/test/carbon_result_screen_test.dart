import 'dart:async';
import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/carbon_readiness.dart';
import 'package:agricarbon_app/models/carbon_result.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/screens/carbon_result_screen.dart';
import 'package:agricarbon_app/services/carbon_api_service.dart';
import 'package:agricarbon_app/services/carbon_cache.dart';
import 'package:agricarbon_app/services/connectivity_service.dart';
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

  /// Readiness máy chủ trả về. Mặc định: đủ dữ liệu.
  CarbonReadiness readinessResult = _ready;
  Object? readinessError;
  int readinessCalls = 0;

  @override
  Future<CarbonReadiness> readiness({required String cropSeasonId}) async {
    readinessCalls++;
    askedIds.add(cropSeasonId);
    if (readinessError != null) throw readinessError!;
    return readinessResult;
  }

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

const _ready = CarbonReadiness(canCalculate: true, blockingCount: 0, missingInputs: []);

CarbonReadiness _missing(List<Map<String, dynamic>> items) => CarbonReadiness.fromJson({
      'can_calculate': !items.any((m) => m['blocking'] != false),
      'blocking_count': items.where((m) => m['blocking'] != false).length,
      'missing_inputs': items,
    });

late Directory _tmp;
late LocalDatabase _db;
late _FakeCarbon _api;
late CarbonCache _cache;

Widget _screen({
  String cs = 'cs1',
  VoidCallback? onSync,
  bool online = true,
  Future<void> Function()? syncNow,
  Set<String>? writableFarmIds,
  Future<void> Function(Activity)? editActivity,
}) =>
    MaterialApp(
      theme: AgriCarbonTheme.light(),
      home: CarbonResultScreen(
        carbonApi: _api,
        cache: _cache,
        db: _db,
        cropSeasonClientId: cs,
        onOpenSync: onSync,
        connectivity: ConnectivityService.fixed(online),
        syncNow: syncNow,
        loadWritableFarmIds:
            writableFarmIds == null ? null : () async => writableFarmIds,
        editActivity: editActivity,
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

  testWidgets('còn thay đổi chưa gửi -> báo rõ, KHÔNG cho tính trên dữ liệu cũ',
      (tester) async {
    await _seedSeason(pendingActivities: 3);
    await tester.pumpWidget(_screen(onSync: () {}));
    await _settle(tester);
    expect(find.byKey(const Key('carbon-pending-changes')), findsOneWidget);
    expect(find.byKey(const Key('carbon-calculate')), findsNothing);
    expect(find.byKey(const Key('carbon-calc-blocked')), findsOneWidget);
    expect(_api.calcCalls, 0);
  });

  testWidgets('gọi API bằng SERVER id, không phải client id', (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = _result();
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(_api.askedIds, everyElement('srv-cs1'));
    expect(_api.askedIds, isNot(contains('cs1')));
  });

  testWidgets('no_calculation + đủ dữ liệu -> empty state + nút "Tính Carbon"',
      (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = null; // = no_calculation
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.textContaining('chưa được tính phát thải'), findsOneWidget);
    expect(find.text('Đã đủ dữ liệu để tính phát thải.'), findsOneWidget);
    expect(find.widgetWithText(ElevatedButton, 'Tính Carbon'), findsOneWidget);
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

  // ---------------------------------------------------------------- readiness

  final seasonIssues = [
    {
      'code': 'water_regime', 'label': 'Thiếu chế độ nước trong vụ',
      'detail': 'Chọn chế độ nước.', 'flow': 'carbon_methodology', 'blocking': true,
    },
    {
      'code': 'cultivation_days', 'label': 'Thiếu số ngày canh tác',
      'detail': 'Số ngày từ gieo tới thu hoạch.', 'flow': 'carbon_methodology', 'blocking': true,
    },
  ];
  final fuelIssue = {
    'code': 'fuel_factor_unverified',
    'label': 'Vụ có ghi nhiên liệu nhưng chưa có hệ số đã xác minh',
    'detail': 'Đây là giới hạn của bộ hệ số, không phải do bạn nhập thiếu.',
    'flow': 'factor_unavailable', 'activity_type': 'fuel', 'blocking': true,
    'records': [
      {'activity_id': 'srv-fuel', 'occurred_on': '2026-03-02', 'label': 'diesel'},
    ],
  };
  Map<String, dynamic> nitrogenIssue(String activityId) => {
        'code': 'fertilizer_nitrogen',
        'label': 'Thiếu hàm lượng Nitơ của lần bón phân',
        'detail': 'Cần % N.', 'flow': 'activity', 'activity_type': 'fertilizer',
        'blocking': true,
        'records': [
          {'activity_id': activityId, 'occurred_on': '2026-03-05', 'label': 'NPK'},
        ],
      };

  testWidgets('readiness: hiện đúng các mục MÁY CHỦ báo, không tự suy thêm',
      (tester) async {
    await _seedSeason();
    _api.readinessResult = _missing([...seasonIssues, fuelIssue]);
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.text('Cần bổ sung 3 thông tin để tính phát thải'), findsOneWidget);
    expect(find.text('Thiếu chế độ nước trong vụ'), findsOneWidget);
    expect(find.text('Thiếu số ngày canh tác'), findsOneWidget);
    expect(find.byKey(const Key('carbon-calculate')), findsNothing);
    expect(_api.askedIds, contains('srv-cs1'));
  });

  testWidgets('fuel: giới hạn trung thực — không có "Sửa ngay" giả', (tester) async {
    await _seedSeason();
    _api.readinessResult = _missing([fuelIssue]);
    await tester.pumpWidget(_screen());
    await _settle(tester);
    final card = find.byKey(const Key('carbon-issue-fuel_factor_unverified'));
    expect(card, findsOneWidget);
    expect(find.descendant(of: card, matching: find.text('Sửa ngay')), findsNothing);
    expect(find.byKey(const Key('carbon-limitation-note')), findsOneWidget);
    expect(find.textContaining('Nhập thêm chi tiết'), findsOneWidget);
    expect(find.byKey(const Key('carbon-calculate')), findsNothing);
  });

  testWidgets('viewer: thấy mục thiếu + kết quả, KHÔNG nút sửa/tính', (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = _result();
    _api.readinessResult = _missing(seasonIssues);
    await tester.pumpWidget(_screen(writableFarmIds: {'some-other-farm'}));
    await _settle(tester);
    expect(find.byKey(const Key('carbon-read-only')), findsOneWidget);
    expect(find.text('Thiếu chế độ nước trong vụ'), findsOneWidget);
    expect(find.text('Sửa ngay'), findsNothing);
    expect(find.byKey(const Key('carbon-calculate')), findsNothing);
  });

  testWidgets('viewer trên vụ đã đủ dữ liệu: không có nút tính', (tester) async {
    await _seedSeason();
    await tester.pumpWidget(_screen(writableFarmIds: const {}));
    await _settle(tester);
    expect(find.text('Đã đủ dữ liệu để tính phát thải.'), findsOneWidget);
    expect(find.byKey(const Key('carbon-calculate')), findsNothing);
  });

  testWidgets('writer của đúng farm: có nút sửa và nút tính', (tester) async {
    await _seedSeason();
    await tester.pumpWidget(_screen(writableFarmIds: {'f1'}));
    await _settle(tester);
    expect(find.byKey(const Key('carbon-calculate')), findsOneWidget);
  });

  testWidgets('offline: không giả kết quả — "Cần kết nối mạng..."', (tester) async {
    await _seedSeason();
    await tester.pumpWidget(_screen(online: false));
    await _settle(tester);
    expect(find.textContaining('Cần kết nối mạng'), findsWidgets);
    expect(find.byKey(const Key('carbon-calculate')), findsNothing);
    expect(_api.readinessCalls, 0);
    expect(_api.calcCalls, 0);
  });

  testWidgets('đủ dữ liệu -> "Tính Carbon" gọi máy chủ; có kết quả -> "Tính lại Carbon"',
      (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = null;
    await tester.pumpWidget(_screen());
    await _settle(tester);
    await tester.tap(find.byKey(const Key('carbon-calculate')));
    await _settle(tester);
    expect(_api.calcCalls, 1);
    expect(find.widgetWithText(ElevatedButton, 'Tính lại Carbon'), findsOneWidget);
  });

  testWidgets('sửa nhanh thông tin vụ: lưu trên máy (pending), gửi bằng lượt đồng bộ '
      'sẵn có, rồi hỏi lại readiness', (tester) async {
    await _seedSeason();
    _api.readinessResult = _missing(seasonIssues);
    var syncs = 0;
    await tester.pumpWidget(_screen(syncNow: () async {
      syncs++;
      _api.readinessResult = _ready; // máy chủ đã nhận giá trị
    }));
    await _settle(tester);
    final callsBefore = _api.readinessCalls;

    await tester.tap(find.byKey(const Key('fix-season-water_regime')));
    await _settle(tester);
    await tester.tap(find.byKey(const Key('methodology-ipcc')));
    await _settle(tester);
    await tester.tap(find.text('Chủ động tưới, rút nước nhiều lần (gồm AWD)').last);
    await _settle(tester);
    await tester.enterText(
        find.descendant(of: find.byKey(const Key('methodology-days')), matching: find.byType(TextField)),
        '100');
    await tester.tap(find.byKey(const Key('methodology-save')));
    await _settle(tester);

    final stored = await _db.getCropSeasonByClientId('cs1');
    expect(stored!.ipccWaterRegime?.wire, 'irrigated_multiple_drainage');
    expect(stored.cultivationDays, 100);
    expect(stored.syncState, SyncState.pending); // đi theo hàng đợi, không ghi thẳng
    expect(syncs, 1);
    expect(_api.readinessCalls, greaterThan(callsBefore));
    expect(find.text('Đã đủ dữ liệu để tính phát thải.'), findsOneWidget);
  });

  testWidgets('sửa nhanh thông tin vụ: số ngày không hợp lệ bị chặn, KHÔNG thành null',
      (tester) async {
    await _seedSeason();
    var syncs = 0;
    _api.readinessResult = _missing(seasonIssues);
    await tester.pumpWidget(_screen(syncNow: () async => syncs++));
    await _settle(tester);
    await tester.tap(find.byKey(const Key('fix-season-cultivation_days')));
    await _settle(tester);
    await tester.enterText(
        find.descendant(of: find.byKey(const Key('methodology-days')), matching: find.byType(TextField)),
        '0');
    await tester.tap(find.byKey(const Key('methodology-save')));
    await _settle(tester);
    expect(find.text('Số ngày canh tác phải lớn hơn 0.'), findsOneWidget);
    expect((await _db.getCropSeasonByClientId('cs1'))!.cultivationDays, isNull);
    expect(syncs, 0);
  });

  testWidgets('"Sửa ngay" mở ĐÚNG hoạt động theo server id', (tester) async {
    await _seedSeason();
    final now = DateTime(2026, 3);
    for (final id in ['srv-a', 'srv-b']) {
      await _db.saveActivity(Activity(
        clientEventId: 'local-$id', cropSeasonId: 'cs1', type: 'fertilizer',
        occurredAt: now, payload: const {'fertilizer_name': 'NPK', 'amount_kg': 80.0},
        createdAt: now, syncState: SyncState.synced, serverActivityId: id,
      ));
    }
    _api.readinessResult = _missing([nitrogenIssue('srv-b')]);
    Activity? opened;
    await tester.pumpWidget(_screen(editActivity: (a) async => opened = a));
    await _settle(tester);
    await tester.tap(find.byKey(const Key('fix-activity-srv-b-fertilizer_nitrogen')));
    await _settle(tester);
    expect(opened?.clientEventId, 'local-srv-b');
  });

  testWidgets('bản ghi không có trên máy: nói thật, không có nút sửa', (tester) async {
    await _seedSeason();
    _api.readinessResult = _missing([nitrogenIssue('srv-web-only')]);
    await tester.pumpWidget(_screen(editActivity: (a) async {}));
    await _settle(tester);
    expect(find.byKey(const Key('record-not-on-device-srv-web-only')), findsOneWidget);
    expect(find.text('Sửa ngay'), findsNothing);
  });

  testWidgets('kết quả cũ: dữ liệu sửa SAU calculated_at -> "cần tính lại"', (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = _result(); // calculated 2026-09-08
    await _db.markCarbonInputsChanged('cs1'); // bây giờ > 2026-09-08
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.byKey(const Key('carbon-stale')), findsOneWidget);
  });

  testWidgets('kết quả mới hơn lần sửa cuối: không báo cũ', (tester) async {
    await _seedSeason();
    _api.byScenario[kScenarioAsRecorded] = _result();
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.byKey(const Key('carbon-stale')), findsNothing);
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

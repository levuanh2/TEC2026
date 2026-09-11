import 'dart:async';
import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/crop_season_metrics.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/models/sync_state.dart';
import 'package:agricarbon_app/screens/resource_dashboard_screen.dart';
import 'package:agricarbon_app/services/metrics_cache.dart';
import 'package:agricarbon_app/services/metrics_service.dart';
import 'package:agricarbon_app/services/read_api.dart';
import 'package:agricarbon_app/services/recommendation_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'dd110000-0000-0000-0000-000000000000';

CropSeasonMetrics _metrics({
  double? yield_ = 4000,
  double? waterPerKg = 1.4,
  double? fertPerKg = 0.058,
  double? co2ePerKg = 1.555,
  double? costPerKg = 4150,
  Map<String, bool>? completeness,
}) =>
    CropSeasonMetrics(
      yieldKg: yield_,
      waterM3: 5600,
      fertilizerKg: 232,
      totalCo2eKg: 6220,
      waterPerKg: waterPerKg,
      fertilizerPerKg: fertPerKg,
      co2ePerKg: co2ePerKg,
      costPerKg: costPerKg,
      dataCompleteness: completeness ??
          const {
            'water': true,
            'fertilizer': true,
            'cost': true,
            'carbon': true,
          },
    );

class _FakeMetrics extends MetricsService {
  _FakeMetrics() : super(ReadApi(() => 't'));
  CropSeasonMetrics? result;
  Object? error;
  final askedIds = <String>[];

  @override
  Future<CropSeasonMetrics> fetchForCropSeason(String id) async {
    askedIds.add(id);
    if (error != null) throw error!;
    return result ?? _metrics();
  }
}

class _FakeRecs implements RecommendationRepository {
  _FakeRecs({this.available = true});
  bool available;
  List<Recommendation> recs = const [];
  Object? error;

  @override
  bool get isAvailable => available;

  @override
  Future<List<Recommendation>> forCropSeason(String id) async {
    if (error != null) throw error!;
    return recs;
  }
}

late Directory _tmp;
late LocalDatabase _db;
late _FakeMetrics _api;
late _FakeRecs _recs;
late MetricsCache _cache;

Widget _screen({VoidCallback? onSync}) => MaterialApp(
      theme: AgriCarbonTheme.light(),
      home: ResourceDashboardScreen(
        metricsApi: _api,
        cache: _cache,
        recommendations: _recs,
        db: _db,
        cropSeasonClientId: 'cs1',
        onOpenSync: onSync,
      ),
    );

Future<void> _settle(WidgetTester t) async {
  t.view.physicalSize = const Size(1000, 3200);
  t.view.devicePixelRatio = 1.0;
  addTearDown(t.view.resetPhysicalSize);
  addTearDown(t.view.resetDevicePixelRatio);
  await t.pumpAndSettle();
  for (var i = 0; i < 6; i++) {
    await t.pump(const Duration(milliseconds: 20));
  }
  await t.pumpAndSettle();
}

Future<void> _seedSeason({String? serverId = 'srv-cs1'}) async {
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
}

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_resdash');
    _db = LocalDatabase(
        factory: databaseFactoryFfiNoIsolate, directoryOverride: _tmp.path);
    await _db.openForUser(_user);
    _api = _FakeMetrics();
    _recs = _FakeRecs(available: false);
    _cache = MetricsCache(_db);
  });
  tearDown(() async {
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  testWidgets('không tìm thấy vụ -> ErrorState', (tester) async {
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.text('Không tìm thấy vụ canh tác'), findsOneWidget);
    expect(_api.askedIds, isEmpty);
  });

  testWidgets('vụ chưa đồng bộ -> CTA "Đi tới Gửi dữ liệu", KHÔNG gọi API',
      (tester) async {
    await _seedSeason(serverId: null);
    var synced = 0;
    await tester.pumpWidget(_screen(onSync: () => synced++));
    await _settle(tester);
    expect(find.textContaining('chưa đồng bộ'), findsOneWidget);
    expect(_api.askedIds, isEmpty);
    await tester.tap(find.text('Đi tới Gửi dữ liệu'));
    expect(synced, 1);
  });

  testWidgets('thành công -> 4 chỉ số per-kg số THẬT, gọi bằng SERVER id',
      (tester) async {
    await _seedSeason();
    _api.result = _metrics();
    await tester.pumpWidget(_screen());
    await _settle(tester);

    expect(find.text('Nước / kg'), findsOneWidget);
    expect(find.text('Phân bón / kg'), findsOneWidget);
    expect(find.text('Khí thải / kg'), findsOneWidget);
    expect(find.text('Chi phí / kg'), findsOneWidget);
    expect(find.text('1,4'), findsOneWidget);
    expect(find.text('0,058'), findsOneWidget);
    expect(find.text('1,555'), findsOneWidget);
    expect(find.text('4.150'), findsOneWidget);

    expect(_api.askedIds, everyElement('srv-cs1'));
    expect(_api.askedIds, isNot(contains('cs1')));
  });

  testWidgets('thiếu sản lượng -> per-kg báo "Chưa có sản lượng", KHÔNG "0"',
      (tester) async {
    await _seedSeason();
    _api.result = _metrics(
      yield_: null,
      waterPerKg: null,
      fertPerKg: null,
      co2ePerKg: null,
      costPerKg: null,
    );
    await tester.pumpWidget(_screen());
    await _settle(tester);

    expect(find.text('Chưa có sản lượng'), findsNWidgets(4));
    expect(find.text('0'), findsNothing);
    expect(find.text('0,000'), findsNothing);
  });

  testWidgets('một phần: nước đủ, phần khác thiếu -> "Chưa đủ dữ liệu"',
      (tester) async {
    await _seedSeason();
    _api.result = _metrics(
      fertPerKg: null,
      co2ePerKg: null,
      costPerKg: null,
      completeness: const {
        'water': true,
        'fertilizer': false,
        'cost': false,
        'carbon': false,
      },
    );
    await tester.pumpWidget(_screen());
    await _settle(tester);

    expect(find.text('1,4'), findsOneWidget); // nước có số
    expect(find.text('Chưa đủ dữ liệu'), findsNWidgets(3));
  });

  testWidgets(
      'so sánh: luôn "Chưa đủ dữ liệu để so sánh" (không bịa benchmark)',
      (tester) async {
    await _seedSeason();
    _api.result = _metrics();
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.text('Chưa đủ dữ liệu để so sánh.'), findsOneWidget);
  });

  testWidgets('khuyến nghị chưa cấu hình -> thông báo trung thực, không số giả',
      (tester) async {
    await _seedSeason();
    _api.result = _metrics();
    _recs = _FakeRecs(available: false);
    await tester.pumpWidget(_screen());
    await _settle(tester);
    expect(find.text('Gợi ý điều chỉnh chưa được cấu hình'), findsOneWidget);
    expect(find.textContaining('Giảm ~'), findsNothing);
  });

  testWidgets('khuyến nghị: bản thiếu impact bị loại, bản đủ được render',
      (tester) async {
    await _seedSeason();
    _api.result = _metrics();
    _recs = _FakeRecs(available: true)
      ..recs = [
        const Recommendation(
          messageVi: 'KHÔNG ĐỦ IMPACT — không được hiện.',
          comparedTo: 'trung bình HTX',
          source: 'HTX',
        ),
        const Recommendation(
          messageVi: 'Giảm phân đạm 18 kg ở lần bón tới.',
          co2eReductionKg: 112,
          costSavingVnd: 340000,
          comparedTo: 'trung bình 12 hộ trong HTX, vụ ĐX 2026',
          source: 'benchmark HTX',
        ),
      ];
    await tester.pumpWidget(_screen());
    await _settle(tester);

    expect(find.text('Giảm phân đạm 18 kg ở lần bón tới.'), findsOneWidget);
    expect(find.textContaining('KHÔNG ĐỦ IMPACT'), findsNothing);
    expect(find.textContaining('Giảm ~112 kg CO₂e'), findsOneWidget);
    expect(find.textContaining('So với: trung bình 12 hộ trong HTX'),
        findsOneWidget);
    expect(find.textContaining('Nguồn: benchmark HTX'), findsOneWidget);
  });

  testWidgets('offline + cache -> hiện số cache + nhãn, KHÔNG xoá cache',
      (tester) async {
    await _seedSeason();
    await _cache.write('srv-cs1', _metrics(co2ePerKg: 1.777));
    _api.error = Exception('SocketException: Failed host lookup');

    await tester.pumpWidget(_screen());
    await _settle(tester);

    expect(find.text('1,777'), findsOneWidget);
    expect(find.textContaining('Đang xem số đã lưu'), findsOneWidget);
    expect(await _cache.read('srv-cs1'), isNotNull);
  });

  testWidgets('session hết hạn + cache -> banner đăng nhập lại, giữ số',
      (tester) async {
    await _seedSeason();
    await _cache.write('srv-cs1', _metrics(co2ePerKg: 1.777));
    _api.error = ReadApiException(401, 'unauthenticated', 'x');

    await tester.pumpWidget(_screen());
    await _settle(tester);

    expect(find.textContaining('hết hạn'), findsWidgets);
    expect(find.text('1,777'), findsOneWidget);
  });

  testWidgets('bấm ô chỉ số -> sheet chi tiết nêu nhóm Activity nguồn',
      (tester) async {
    await _seedSeason();
    _api.result = _metrics();
    await tester.pumpWidget(_screen());
    await _settle(tester);

    await tester.tap(find.text('Nước / kg'));
    await tester.pumpAndSettle();

    expect(find.text('Tính từ'), findsOneWidget);
    expect(find.textContaining('"Tưới nước"'), findsOneWidget);
    expect(find.textContaining('"Thu hoạch"'), findsWidgets);
  });

  testWidgets('unmount khi request treo -> KHÔNG setState sau dispose',
      (tester) async {
    await _seedSeason();
    final gate = Completer<void>();
    final slow = _SlowMetrics(gate);
    await tester.pumpWidget(MaterialApp(
      home: ResourceDashboardScreen(
        metricsApi: slow,
        cache: _cache,
        recommendations: _FakeRecs(available: false),
        db: _db,
        cropSeasonClientId: 'cs1',
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    await tester.pumpWidget(const MaterialApp(home: SizedBox()));
    gate.complete();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    expect(tester.takeException(), isNull);
  });
}

class _SlowMetrics extends MetricsService {
  _SlowMetrics(this._gate) : super(ReadApi(() => 't'));
  final Completer<void> _gate;
  @override
  Future<CropSeasonMetrics> fetchForCropSeason(String id) async {
    await _gate.future;
    return _metrics();
  }
}

import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/carbon_result.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/crop_season_metrics.dart';
import 'package:agricarbon_app/models/farm.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/models/sync_state.dart';
import 'package:agricarbon_app/services/active_context.dart';
import 'package:agricarbon_app/services/carbon_api_service.dart';
import 'package:agricarbon_app/services/connectivity_service.dart';
import 'package:agricarbon_app/services/me_service.dart';
import 'package:agricarbon_app/services/metrics_service.dart';
import 'package:agricarbon_app/services/read_api.dart';
import 'package:agricarbon_app/shell/home_actions.dart';
import 'package:agricarbon_app/shell/home_controller.dart';
import 'package:agricarbon_app/shell/tabs/home_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'cccccccc-0000-0000-0000-000000000000';

class _RecordingActions implements HomeActions {
  int cameraCalls = 0;
  final activityForm = <(String, String)>[];
  final typePicker = <String>[];

  @override
  void openCameraCv() => cameraCalls++;
  @override
  void openResourceDashboard(String cropSeasonClientId) =>
      resourceDashboard.add(cropSeasonClientId);
  final resourceDashboard = <String>[];
  @override
  void openActivityForm(String cropSeasonClientId, String activityType) =>
      activityForm.add((cropSeasonClientId, activityType));
  @override
  void openActivityTypePicker(String cropSeasonClientId) =>
      typePicker.add(cropSeasonClientId);
  @override
  void openContextPicker() {}
  @override
  void openCarbon(String cropSeasonServerId) {}
  @override
  void openActiveCropSeasonForm() {}
  @override
  void switchToSyncTab() {}
}

class _FakeMe extends MeService {
  _FakeMe() : super(ReadApi(() => 't'));
  @override
  Future<MeProfile> fetch() async =>
      const MeProfile(userId: 'u', fullName: 'A', roles: ['farmer']);
}

class _FakeCarbon extends CarbonApiService {
  _FakeCarbon() : super.withTokenProvider((() => 't'));
  @override
  Future<CarbonResult?> latest({
    required String cropSeasonId,
    String? scenario,
  }) async =>
      null;
}

class _FakeMetrics extends MetricsService {
  _FakeMetrics() : super(ReadApi(() => 't'));
  @override
  Future<CropSeasonMetrics> fetchForCropSeason(String id) async =>
      const CropSeasonMetrics();
}

late Directory _tmp;
late LocalDatabase _db;
late ActiveContext _ctx;

Future<void> _seed() async {
  final now = DateTime(2026);
  await _db.replaceFarms([
    Farm(id: 'f1', cooperativeId: 'o', farmCode: 'HH', farmName: 'Hộ 1'),
  ]);
  await _db.upsertPlot(Plot(
    clientId: 'p1',
    serverId: 'srv-p1',
    farmId: 'f1',
    plotCode: 'PL',
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
  await _ctx.setFarm(await _db.getFarm('f1'));
  await _ctx.setPlot(await _db.getPlotByClientId('p1'));
  await _ctx.setCropSeason(await _db.getCropSeasonByClientId('cs1'));
}

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_home_cam');
    // Màn hình test mặc định 800x600 — HomeTab cuộn; dùng khung cao để mọi ô
    // trong lưới "Ghi nhanh" hiển thị.
    _db = LocalDatabase(
        factory: databaseFactoryFfiNoIsolate, directoryOverride: _tmp.path);
    await _db.openForUser(_user);
    _ctx = ActiveContext();
    await _ctx.attach(_db);
    await _seed();
  });
  tearDown(() async {
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  testWidgets('shortcut "Ảnh ruộng" gọi openCameraCv, KHÔNG openActivityForm',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final actions = _RecordingActions();
    final controller = HomeController(
      me: _FakeMe(),
      carbon: _FakeCarbon(),
      metrics: _FakeMetrics(),
      db: _db,
      activeContext: _ctx,
      connectivity: ConnectivityService.fixed(false),
    )..attach();

    await tester.pumpWidget(MaterialApp(
      theme: AgriCarbonTheme.light(),
      home: HomeTab(controller: controller, actions: actions),
    ));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.text('Ảnh ruộng'));
    await tester.tap(find.text('Ảnh ruộng'));
    await tester.pump();

    expect(actions.cameraCalls, 1);
    expect(actions.activityForm, isEmpty);

    // Ô "Tưới" mở đúng form với activity type hợp lệ.
    await tester.ensureVisible(find.text('Tưới'));
    await tester.tap(find.text('Tưới'));
    await tester.pump();
    expect(actions.activityForm, [('cs1', 'irrigation')]);

    controller.dispose();
  });

  testWidgets('"Xem tất cả" chỉ mở picker 7 loại (không sentinel)',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final actions = _RecordingActions();
    final controller = HomeController(
      me: _FakeMe(),
      carbon: _FakeCarbon(),
      metrics: _FakeMetrics(),
      db: _db,
      activeContext: _ctx,
      connectivity: ConnectivityService.fixed(false),
    )..attach();

    await tester.pumpWidget(MaterialApp(
      theme: AgriCarbonTheme.light(),
      home: HomeTab(controller: controller, actions: actions),
    ));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.text('Xem tất cả'));
    await tester.tap(find.text('Xem tất cả'));
    await tester.pump();
    expect(actions.typePicker, ['cs1']);
    expect(actions.activityForm, isEmpty);
    controller.dispose();
  });
}

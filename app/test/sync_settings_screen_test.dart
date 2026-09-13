import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/sync_settings_screen.dart';
import 'package:agricarbon_app/services/connectivity_service.dart';
import 'package:agricarbon_app/services/device_service.dart';
import 'package:agricarbon_app/services/sync_coordinator.dart';
import 'package:agricarbon_app/services/sync_gateway.dart';
import 'package:agricarbon_app/services/sync_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'ffff0000-0000-0000-0000-000000000000';

/// Gateway trơ — màn Cài đặt không gọi mạng, chỉ đọc/ghi `meta`.
class _NoopGateway implements SyncGateway {
  Never _no() => throw UnimplementedError('không gọi trong test này');
  @override
  Future<String> upsertPlot(Map<String, dynamic> r) => _no();
  @override
  Future<String> upsertCropSeason(Map<String, dynamic> r) => _no();
  @override
  Future<String> ensureDefaultBatch(String id) => _no();
  @override
  Future<String> upsertActivity(Map<String, dynamic> r) => _no();
  @override
  Future<void> upsertActivityDetail(String t, Map<String, dynamic> r) => _no();
  @override
  Future<void> softDeleteActivity(String id) => _no();
  @override
  String? currentUserId() => _user;
  @override
  Future<String?> currentCooperativeId() async => null;
  @override
  Future<List<Map<String, dynamic>>> fetchFarms() async => [];
  @override
  Future<List<Map<String, dynamic>>> fetchPlots() async => [];
  @override
  Future<List<Map<String, dynamic>>> fetchCropSeasons() async => [];
}

late Directory _tmp;
late LocalDatabase _db;
late SyncCoordinator _co;

Widget _wrap(Widget c) => MaterialApp(theme: AgriCarbonTheme.light(), home: c);

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_syncset');
    _db = LocalDatabase(
        factory: databaseFactoryFfiNoIsolate, directoryOverride: _tmp.path);
    await _db.openForUser(_user);
    _co = SyncCoordinator(
      sync: SyncService(_NoopGateway(), _db, DeviceService.fixed('d')),
      db: _db,
      connectivity: ConnectivityService.fixed(true, wifi: true),
    );
    await _co.attach();
  });
  tearDown(() async {
    _co.dispose();
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  testWidgets('mặc định: "Wi-Fi và dữ liệu di động"; chọn "Chỉ Wi-Fi" -> lưu',
      (tester) async {
    await tester.pumpWidget(_wrap(SyncSettingsScreen(coordinator: _co)));
    await tester.pumpAndSettle();

    expect(_co.wifiOnly, isFalse);
    expect(find.text('Chỉ Wi-Fi'), findsOneWidget);
    expect(find.text('Wi-Fi và dữ liệu di động'), findsOneWidget);

    await tester.tap(find.text('Chỉ Wi-Fi'));
    await tester.pumpAndSettle();

    expect(_co.wifiOnly, isTrue);
    expect(await _db.getMeta('sync.wifi_only'), '1');

    // Bấm lại lựa chọn kia -> tắt.
    await tester.tap(find.text('Wi-Fi và dữ liệu di động'));
    await tester.pumpAndSettle();
    expect(_co.wifiOnly, isFalse);
    expect(await _db.getMeta('sync.wifi_only'), '0');
  });

  testWidgets('không hiện exception kỹ thuật', (tester) async {
    await tester.pumpWidget(_wrap(SyncSettingsScreen(coordinator: _co)));
    await tester.pumpAndSettle();
    expect(find.textContaining('Exception'), findsNothing);
    expect(find.textContaining('Error'), findsNothing);
  });
}

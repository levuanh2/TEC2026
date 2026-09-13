import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/services/connectivity_service.dart';
import 'package:agricarbon_app/services/device_service.dart';
import 'package:agricarbon_app/services/sync_coordinator.dart';
import 'package:agricarbon_app/services/sync_gateway.dart';
import 'package:agricarbon_app/services/sync_service.dart';
import 'package:agricarbon_app/shell/tabs/sync_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'dddd0000-0000-0000-0000-000000000000';

class _StubGateway implements SyncGateway {
  final serverActivities = <String, String>{};
  int inserts = 0;
  @override
  Future<String> upsertActivity(Map<String, dynamic> row) async {
    final ceid = row['client_event_id'] as String;
    return serverActivities.putIfAbsent(ceid, () {
      inserts++;
      return 'srv-$ceid';
    });
  }

  @override
  Future<void> upsertActivityDetail(String t, Map<String, dynamic> r) async {}
  @override
  Future<String> upsertPlot(Map<String, dynamic> r) async => 'srv-p';
  @override
  Future<String> upsertCropSeason(Map<String, dynamic> r) async => 'srv-cs';
  @override
  Future<String> ensureDefaultBatch(String id) async => 'b';
  @override
  Future<void> softDeleteActivity(String id) async =>
      serverActivities.removeWhere((_, v) => v == id);
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
late _StubGateway _gw;
late ConnectivityService _conn;
late SyncCoordinator _co;

Widget _wrap(Widget c) => MaterialApp(theme: AgriCarbonTheme.light(), home: c);

Future<void> _seedSyncedTree() async {
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
    serverId: 'srv-cs1',
    plotClientId: 'p1',
    seasonCode: 'S1',
    syncState: SyncState.synced,
    createdAt: now,
    updatedAt: now,
  ));
}

Future<void> _seedActivity(String id, String type, Map<String, dynamic> pl) =>
    _db.saveActivity(Activity(
      clientEventId: id,
      cropSeasonId: 'cs1',
      type: type,
      occurredAt: DateTime(2026, 3, 2, 6, 30),
      payload: pl,
      createdAt: DateTime(2026, 3, 2, 6, 35),
    ));

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_synctab');
    _db = LocalDatabase(
        factory: databaseFactoryFfiNoIsolate, directoryOverride: _tmp.path);
    await _db.openForUser(_user);
    _gw = _StubGateway();
    _conn = ConnectivityService.fixed(true, wifi: true);
    _co = SyncCoordinator(
      sync: SyncService(_gw, _db, DeviceService.fixed('d')),
      db: _db,
      connectivity: _conn,
    );
  });
  tearDown(() async {
    _co.dispose();
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  testWidgets(
      'có hàng đợi -> tiêu đề "Chưa gửi lên", dòng có loại·thửa + tóm tắt',
      (tester) async {
    await _seedSyncedTree();
    await _seedActivity('a1', 'irrigation', const {'water_volume_m3': 32});
    await _co.attach();

    await tester.pumpWidget(_wrap(SyncTab(coordinator: _co)));
    await tester.pumpAndSettle();

    expect(find.text('Chưa gửi lên'), findsOneWidget); // typo đã sửa
    expect(find.text('Gửi dữ liệu ngay'), findsOneWidget);
    expect(find.textContaining('Tưới nước · A-01'), findsOneWidget);
    expect(find.textContaining('32 m³'), findsOneWidget); // đơn vị thật
    expect(find.textContaining('mm'), findsNothing); // KHÔNG "mm"
    // 3 mốc thời gian.
    expect(find.textContaining('Thời gian làm'), findsOneWidget);
    expect(find.textContaining('Thời gian ghi'), findsOneWidget);
    expect(find.textContaining('Thời gian gửi'), findsOneWidget);
  });

  testWidgets('KHÔNG có dòng "ảnh" khi chưa có bản ghi ảnh', (tester) async {
    await _seedSyncedTree();
    await _seedActivity('a1', 'fertilizer',
        const {'fertilizer_name': 'Ure', 'amount_kg': 18.0});
    await _co.attach();

    await tester.pumpWidget(_wrap(SyncTab(coordinator: _co)));
    await tester.pumpAndSettle();
    expect(find.textContaining('ảnh'), findsNothing);
    expect(find.textContaining('Ảnh ruộng'), findsNothing);
  });

  testWidgets('offline -> nút "Gửi dữ liệu ngay" bị khoá + báo không mạng',
      (tester) async {
    await _seedSyncedTree();
    await _seedActivity('a1', 'fuel', const {'amount_liter': 5.0});
    _conn.debugSet(online: false);
    await _co.attach();

    await tester.pumpWidget(_wrap(SyncTab(coordinator: _co)));
    await tester.pumpAndSettle();

    expect(find.textContaining('không có mạng'), findsOneWidget);
    final btn = tester.widget<ElevatedButton>(
      find.ancestor(
        of: find.text('Gửi dữ liệu ngay'),
        matching: find.byType(ElevatedButton),
      ),
    );
    expect(btn.onPressed, isNull); // khoá
  });

  testWidgets('bấm "Gửi dữ liệu ngay" -> gửi hết -> hiện "đã gửi hết"',
      (tester) async {
    await _seedSyncedTree();
    await _seedActivity('a1', 'harvest', const {'yield_kg': 4000});
    await _co.attach();

    await tester.pumpWidget(_wrap(SyncTab(coordinator: _co)));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Gửi dữ liệu ngay'));
    await tester.pumpAndSettle();

    expect(_gw.inserts, 1);
    expect(_co.pendingCount, 0);
    expect(find.textContaining('Đã gửi hết'), findsWidgets);
    expect(find.text('Chưa gửi lên'), findsNothing);
  });

  testWidgets('không lộ exception kỹ thuật ở bất kỳ state nào', (tester) async {
    await _seedSyncedTree();
    await _seedActivity('a1', 'seeding', const {'seed_kg': 40});
    await _db.updateActivitySyncState('a1',
        state: SyncState.failed, error: 'network');
    await _co.attach();

    await tester.pumpWidget(_wrap(SyncTab(coordinator: _co)));
    await tester.pumpAndSettle();
    expect(find.textContaining('Exception'), findsNothing);
    expect(find.textContaining('SocketException'), findsNothing);
    // Có thông báo thân thiện + số lần thử.
    expect(find.textContaining('Đã thử 1 lần'), findsOneWidget);
  });
}

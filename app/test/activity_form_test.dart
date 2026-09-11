import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/screens/activity_form.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'ffffffff-0000-0000-0000-000000000000';
const _cs = 'cs-1';

late Directory _tmp;
late LocalDatabase _db;
int _savedCount = 0;

Future<void> _onSaved() async => _savedCount++;

Widget _wrap(Widget child) => MaterialApp(
      theme: AgriCarbonTheme.light(),
      home: Scaffold(body: SingleChildScrollView(child: child)),
    );

Widget _form(String type, {Activity? existing}) => ActivityForm(
      db: _db,
      cropSeasonClientId: _cs,
      activityType: type,
      existing: existing,
      online: false,
      onSaved: _onSaved,
    );

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_form_test');
    // NoIsolate: bên trong testWidgets, factory chạy qua isolate (databaseFactoryFfi)
    // bị kẹt vô hạn — bản in-process hoạt động bình thường.
    _db = LocalDatabase(
        factory: databaseFactoryFfiNoIsolate, directoryOverride: _tmp.path);
    await _db.openForUser(_user);
    _savedCount = 0;
  });
  tearDown(() async {
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  testWidgets('offline -> hiện OfflineBanner', (tester) async {
    await tester.pumpWidget(_wrap(_form('seeding')));
    await tester.pump();
    expect(find.textContaining('vẫn được lưu trên điện thoại'), findsOneWidget);
  });

  testWidgets('số sai định dạng -> báo lỗi tại ô, KHÔNG lưu', (tester) async {
    await tester.pumpWidget(_wrap(_form('seeding')));
    await tester.pump();

    // "1.2.3" lọt qua bộ lọc ký tự (chỉ [0-9.,]) nhưng KHÔNG parse được số.
    await tester.enterText(find.byType(TextField).at(1), '1.2.3'); // seed_kg
    await tester.tap(find.widgetWithText(ElevatedButton, 'Lưu công việc'));
    await tester.pumpAndSettle();

    expect(find.text('Số không hợp lệ.'), findsOneWidget);
    expect(_savedCount, 0);
    expect(await _db.listActivitiesByCropSeasonClientId(_cs), isEmpty);
  });

  testWidgets('thiếu field bắt buộc -> báo lỗi, KHÔNG lưu', (tester) async {
    await tester.pumpWidget(_wrap(_form('harvest')));
    await tester.pump();

    await tester.tap(find.widgetWithText(ElevatedButton, 'Lưu công việc'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Vui lòng nhập'), findsWidgets);
    expect(_savedCount, 0);
    expect(await _db.listActivitiesByCropSeasonClientId(_cs), isEmpty);
  });

  testWidgets('nhập hợp lệ -> lưu offline (không mạng), pending',
      (tester) async {
    await tester.pumpWidget(_wrap(_form('seeding')));
    await tester.pump();

    await tester.enterText(find.byType(TextField).at(1), '45'); // seed_kg
    await tester.tap(find.widgetWithText(ElevatedButton, 'Lưu công việc'));
    await tester.pumpAndSettle();

    expect(_savedCount, 1);
    final rows = await _db.listActivitiesByCropSeasonClientId(_cs);
    expect(rows, hasLength(1));
    expect(rows.single.type, 'seeding');
    expect(rows.single.payload['seed_kg'], 45.0);
    expect(rows.single.syncState, SyncState.pending);
  });

  testWidgets('sửa: prefill từ existing, giữ clientEventId, về pending',
      (tester) async {
    final existing = Activity(
      clientEventId: 'keep-1',
      cropSeasonId: _cs,
      type: 'seeding',
      occurredAt: DateTime(2026, 3, 1, 6),
      payload: const {'seed_kg': 40.0, 'variety_name': 'OM'},
      createdAt: DateTime(2026, 3, 1, 6),
      syncState: SyncState.synced,
      serverActivityId: 'srv-x',
    );
    await _db.saveActivity(existing);

    await tester.pumpWidget(_wrap(_form('seeding', existing: existing)));
    await tester.pump();

    // Prefill giá trị cũ hiển thị.
    expect(find.text('40'), findsOneWidget);
    expect(find.text('OM'), findsOneWidget);
    expect(find.widgetWithText(ElevatedButton, 'Lưu thay đổi'), findsOneWidget);

    await tester.enterText(find.byType(TextField).at(1), '55');
    await tester.tap(find.widgetWithText(ElevatedButton, 'Lưu thay đổi'));
    await tester.pumpAndSettle();

    final after = await _db.getActivity('keep-1');
    expect(after!.clientEventId, 'keep-1');
    expect(after.serverActivityId, 'srv-x');
    expect(after.payload['seed_kg'], 55.0);
    expect(after.syncState, SyncState.pending);
  });
}

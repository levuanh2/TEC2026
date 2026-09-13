import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/theme.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/models/sync_state.dart';
import 'package:agricarbon_app/screens/help_screen.dart';
import 'package:agricarbon_app/services/me_service.dart';
import 'package:agricarbon_app/services/read_api.dart';
import 'package:agricarbon_app/shell/tabs/account_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

class _FakeHttp extends http.BaseClient {
  _FakeHttp(this._body, {this.status = 200});
  final Object _body;
  final int status;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final b = _body;
    final text = b is String ? b : jsonEncode(b);
    return http.StreamedResponse(
      Stream.value(utf8.encode(text)),
      status,
      headers: {'content-type': 'application/json'},
    );
  }
}

void main() {
  group('accountInitials — từ HỌ TÊN THẬT, không bịa "NA"', () {
    test('hai từ trở lên → ký tự đầu từ đầu + từ cuối', () {
      expect(accountInitials('Trần Thị Bích Hạnh'), 'TH');
      expect(accountInitials('lê văn tú'), 'LT');
    });
    test('một từ → một ký tự', () {
      expect(accountInitials('Hạnh'), 'H');
    });
    test('null / rỗng / chỉ khoảng trắng → null (UI dùng icon người)', () {
      expect(accountInitials(null), isNull);
      expect(accountInitials(''), isNull);
      expect(accountInitials('   '), isNull);
    });
  });

  group('accountRoleLabel — map VN, giữ nguyên vai trò lạ', () {
    test('map các vai trò đã biết, gộp trùng', () {
      expect(accountRoleLabel(['farmer']), 'Nông dân');
      expect(accountRoleLabel(['owner', 'editor']),
          'Chủ ruộng · Người ghi dữ liệu');
      expect(accountRoleLabel(['cooperative_manager']), 'Cán bộ hợp tác xã');
    });
    test('vai trò không nằm trong bảng vẫn hiển thị nguyên văn', () {
      expect(accountRoleLabel(['super_admin']), 'super_admin');
    });
    test('rỗng → chuỗi rỗng (UI ẩn dòng)', () {
      expect(accountRoleLabel(const []), '');
    });
  });

  group('MeService.fetch — parse MeResponse', () {
    MeService svc(Object body, {int status = 200}) => MeService(
        ReadApi(() => 't', httpClient: _FakeHttp(body, status: status)));

    test('full_name rỗng → null (không bịa tên)', () async {
      final me = await svc({
        'user_id': 'u1',
        'full_name': '   ',
        'roles': ['farmer'],
        'farm_memberships': [],
        'organization_memberships': [],
      }).fetch();
      expect(me.fullName, isNull);
      expect(me.isFarmer, isTrue);
    });

    test('đếm farm/org memberships', () async {
      final me = await svc({
        'user_id': 'u1',
        'full_name': 'Nông Dân A',
        'roles': ['farmer', 'owner'],
        'farm_memberships': [
          {'farm_id': 'f1'},
          {'farm_id': 'f2'},
        ],
        'organization_memberships': [
          {'organization_id': 'o1'},
        ],
      }).fetch();
      expect(me.fullName, 'Nông Dân A');
      expect(me.farmMembershipCount, 2);
      expect(me.orgMembershipCount, 1);
      expect(me.roles, containsAll(['farmer', 'owner']));
    });

    test('401 → ReadApiException.isUnauthorized', () async {
      await expectLater(
        svc({
          'detail': {
            'error': {'code': 'unauthenticated', 'message': 'x'}
          }
        }, status: 401)
            .fetch(),
        throwsA(isA<ReadApiException>()
            .having((e) => e.isUnauthorized, 'isUnauthorized', isTrue)),
      );
    });
  });

  group('LocalDatabase.plotSummary', () {
    late Directory tmp;
    late LocalDatabase db;
    setUpAll(sqfliteFfiInit);
    setUp(() async {
      tmp = await Directory.systemTemp.createTemp('acc_plotsum');
      db = LocalDatabase(
          factory: databaseFactoryFfiNoIsolate, directoryOverride: tmp.path);
      await db.openForUser('acc00000-0000-0000-0000-000000000000');
    });
    tearDown(() async {
      await db.close();
      try {
        if (tmp.existsSync()) await tmp.delete(recursive: true);
      } catch (_) {}
    });

    test('chưa có ruộng → (0, 0)', () async {
      final s = await db.plotSummary();
      expect(s.count, 0);
      expect(s.areaHa, 0);
    });

    test('cộng count + diện tích thật', () async {
      final now = DateTime(2026);
      for (var i = 0; i < 3; i++) {
        await db.upsertPlot(Plot(
          clientId: 'p$i',
          farmId: 'f1',
          plotCode: 'PL$i',
          name: 'Thửa $i',
          areaHa: 1.5,
          syncState: SyncState.pending,
          createdAt: now,
          updatedAt: now,
        ));
      }
      final s = await db.plotSummary();
      expect(s.count, 3);
      expect(s.areaHa, closeTo(4.5, 1e-9));
    });
  });

  testWidgets('HelpScreen — không có số tổng đài giả', (tester) async {
    tester.view.physicalSize = const Size(1000, 2000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(theme: AgriCarbonTheme.light(), home: const HelpScreen()),
    );
    await tester.pumpAndSettle();

    expect(find.text('Trợ giúp'), findsOneWidget);
    expect(find.textContaining('cán bộ HTX'), findsOneWidget);
    expect(find.textContaining('1900'), findsNothing);
    // Không có chuỗi 6+ chữ số liền nhau (số điện thoại giả).
    for (final w in tester.widgetList<Text>(find.byType(Text))) {
      final s = w.data ?? '';
      expect(RegExp(r'\d{6,}').hasMatch(s), isFalse, reason: 'có số dài: "$s"');
    }
  });
}

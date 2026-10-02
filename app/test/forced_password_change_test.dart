// Đăng nhập lần đầu bắt buộc đổi mật khẩu tạm (Core V1 closure 3B) — phía app.
// Cờ do máy chủ giữ (Supabase app_metadata); app chỉ đọc, không tự xoá. Máy chủ
// (FastAPI + RLS) mới là nơi chặn thật; ở đây kiểm app không gửi gì, chỉ hiện
// màn đổi mật khẩu, và chỉ vào shell sau khi máy chủ xác nhận.

import 'dart:async';
import 'dart:convert';

import 'package:agricarbon_app/screens/forced_password_change_screen.dart';
import 'package:agricarbon_app/services/auth_service.dart';
import 'package:agricarbon_app/services/password_change_api.dart';
import 'package:agricarbon_app/shell/auth_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _FakeAuth extends AuthService {
  _FakeAuth({required this.flag});
  bool flag;
  final _signals = StreamController<AuthSignal>.broadcast();
  Object? replaceError;
  final replaced = <List<String>>[];

  void emit(AuthSignal s) => _signals.add(s);
  @override
  Stream<AuthSignal> get signals => _signals.stream;
  @override
  String? get currentUserId => 'u1';
  @override
  bool get mustChangePassword => flag;
  @override
  Future<void> replaceTemporaryPassword({required String current, required String next}) async {
    replaced.add([current, next]);
    if (replaceError != null) throw replaceError!;
    flag = false; // the server cleared it; the refreshed session no longer has it
  }

  @override
  Future<bool> sessionEndedByServer() async => false;
  @override
  Future<void> rememberSessionEndedByServer(bool ended) async {}
}

Future<AuthController> _signedIn(_FakeAuth auth, {Future<void> Function()? onReplaced, List<String>? log}) async {
  final c = AuthController(
    auth,
    onUserActive: (uid) async => log?.add('active'),
    onTemporaryPasswordReplaced: onReplaced,
  )..start();
  await Future<void>.delayed(Duration.zero);
  await Future<void>.delayed(Duration.zero);
  return c;
}

void main() {
  group('the flag gates the app', () {
    test('a flagged session is authenticated but must change the password', () async {
      final auth = _FakeAuth(flag: true);
      final c = await _signedIn(auth);
      expect(c.phase, AuthPhase.authenticated);
      expect(c.mustChangePassword, isTrue);
      c.dispose();
    });

    test('an account without the flag is unaffected', () async {
      final c = await _signedIn(_FakeAuth(flag: false));
      expect(c.mustChangePassword, isFalse);
      c.dispose();
    });

    test('nothing is sent while the flag is set: the send gate says not now', () async {
      expect(await _FakeAuth(flag: true).ensureFreshSession(), SessionFreshness.offline);
    });

    test('success: deferred login work runs once, then the shell', () async {
      final auth = _FakeAuth(flag: true);
      var deferred = 0;
      final c = await _signedIn(auth, onReplaced: () async => deferred++);
      var notified = 0;
      c.addListener(() => notified++);
      await c.replaceTemporaryPassword('Temp-Pass-1', 'Own-Pass-22');
      expect(auth.replaced, [['Temp-Pass-1', 'Own-Pass-22']]);
      expect(deferred, 1);
      expect(c.mustChangePassword, isFalse);
      expect(notified, greaterThan(0));
      c.dispose();
    });

    test('a server refusal keeps the account gated and skips the deferred work', () async {
      final auth = _FakeAuth(flag: true)
        ..replaceError = PasswordChangeException(422, 'current_password_incorrect', 'Mật khẩu hiện tại không đúng.');
      var deferred = 0;
      final c = await _signedIn(auth, onReplaced: () async => deferred++);
      await expectLater(c.replaceTemporaryPassword('Wrong-1aA', 'Own-Pass-22'), throwsA(isA<PasswordChangeException>()));
      expect(deferred, 0);
      expect(c.mustChangePassword, isTrue);
      c.dispose();
    });
  });

  group('PasswordChangeApi', () {
    test('posts both passwords with the bearer token; 200 is success', () async {
      late http.Request sent;
      final api = PasswordChangeApi(() => 'jwt', httpClient: MockClient((r) async {
        sent = r;
        return http.Response('{"must_change_password": false}', 200);
      }));
      await api.replace(current: 'Temp-Pass-1', next: 'Own-Pass-22');
      expect(sent.method, 'POST');
      expect(sent.url.path, '/v1/me/password');
      expect(sent.headers['Authorization'], 'Bearer jwt');
      expect(jsonDecode(sent.body), {'current_password': 'Temp-Pass-1', 'new_password': 'Own-Pass-22'});
    });

    test('the server message of the error envelope is what the farmer sees', () async {
      final api = PasswordChangeApi(() => 'jwt', httpClient: MockClient((_) async => http.Response.bytes(
          utf8.encode('{"detail":{"error":{"code":"password_too_weak","message":"Mật khẩu mới quá yếu."}}}'), 422)));
      await expectLater(
          api.replace(current: 'a', next: 'b'),
          throwsA(isA<PasswordChangeException>()
              .having((e) => e.code, 'code', 'password_too_weak')
              .having((e) => e.message, 'message', 'Mật khẩu mới quá yếu.')));
    });

    test('no token or no network never reaches a success', () async {
      await expectLater(PasswordChangeApi(() => null, httpClient: MockClient((_) async => http.Response('', 200)))
          .replace(current: 'a', next: 'b'), throwsA(isA<PasswordChangeException>().having((e) => e.statusCode, 's', 401)));
      await expectLater(
          PasswordChangeApi(() => 'jwt', httpClient: MockClient((_) async => throw http.ClientException('down')))
              .replace(current: 'a', next: 'b'),
          throwsA(isA<PasswordChangeException>().having((e) => e.code, 'code', 'offline')));
    });
  });

  group('ForcedPasswordChangeScreen', () {
    Future<void> pump(WidgetTester t, Future<void> Function(String, String) submit, {Future<void> Function()? signOut}) =>
        t.pumpWidget(MaterialApp(home: ForcedPasswordChangeScreen(onSubmit: submit, onSignOut: signOut ?? () async {})));

    Future<void> fill(WidgetTester t, String current, String next, [String? confirm]) async {
      await t.enterText(find.byKey(const Key('forced-current')), current);
      await t.enterText(find.byKey(const Key('forced-next')), next);
      await t.enterText(find.byKey(const Key('forced-confirm')), confirm ?? next);
      await t.tap(find.text('Lưu mật khẩu và tiếp tục'));
      await t.pump();
    }

    testWidgets('the same password rule as the server, checked before any request', (t) async {
      final calls = <List<String>>[];
      await pump(t, (c, n) async => calls.add([c, n]));
      await fill(t, 'Temp-Pass-1', 'short');
      expect(find.text('Mật khẩu mới cần ít nhất 8 ký tự.'), findsOneWidget);
      await fill(t, 'Temp-Pass-1', 'alllowercase1');
      expect(find.text('Mật khẩu mới cần có chữ hoa, chữ thường và số.'), findsOneWidget);
      await fill(t, 'Temp-Pass-1', 'Own-Pass-22', 'Own-Pass-23');
      expect(find.text('Hai lần nhập mật khẩu mới không khớp.'), findsOneWidget);
      await fill(t, '', 'Own-Pass-22');
      expect(find.text('Nhập mật khẩu tạm HTX đã cấp.'), findsOneWidget);
      expect(calls, isEmpty);
      await fill(t, 'Temp-Pass-1', 'Own-Pass-22');
      expect(calls, [['Temp-Pass-1', 'Own-Pass-22']]);
    });

    testWidgets('shows the server refusal and stays', (t) async {
      await pump(t, (c, n) async => throw PasswordChangeException(422, 'current_password_incorrect', 'Mật khẩu hiện tại không đúng.'));
      await fill(t, 'Wrong-Pass-1', 'Own-Pass-22');
      await t.pump();
      expect(find.text('Mật khẩu hiện tại không đúng.'), findsOneWidget);
      expect(find.byType(ForcedPasswordChangeScreen), findsOneWidget);
    });

    testWidgets('sign-out is the only other way out', (t) async {
      var out = 0;
      await pump(t, (c, n) async {}, signOut: () async => out++);
      await t.tap(find.text('Đăng xuất'));
      await t.pump();
      expect(out, 1);
    });
  });
}

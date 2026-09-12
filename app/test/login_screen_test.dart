import 'dart:async';

import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/login_screen.dart';
import 'package:agricarbon_app/services/auth_actions.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supabase_flutter/supabase_flutter.dart' show AuthException;

class _FakeActions implements AuthActions {
  int signInCalls = 0;
  int resetCalls = 0;
  String? lastSignInEmail;
  String? lastResetEmail;
  Object? signInError;
  Completer<void>? gate;

  @override
  Future<void> signIn({required String email, required String password}) async {
    signInCalls++;
    lastSignInEmail = email;
    if (gate != null) await gate!.future;
    final err = signInError;
    if (err != null) throw err;
  }

  @override
  Future<void> sendPasswordReset(String email) async {
    resetCalls++;
    lastResetEmail = email;
  }
}

Widget _wrap(Widget child) =>
    MaterialApp(theme: AgriCarbonTheme.light(), home: child);

void main() {
  testWidgets('email sai định dạng -> báo lỗi, KHÔNG gọi signIn',
      (tester) async {
    final actions = _FakeActions();
    await tester.pumpWidget(_wrap(LoginScreen(actions: actions)));

    await tester.enterText(find.byType(TextField).at(0), 'khong-phai-email');
    await tester.enterText(find.byType(TextField).at(1), 'matkhau');
    await tester.tap(find.widgetWithText(ElevatedButton, 'Đăng nhập'));
    await tester.pump();

    expect(find.text('Email chưa đúng định dạng.'), findsOneWidget);
    expect(actions.signInCalls, 0);
  });

  testWidgets('mật khẩu rỗng -> báo lỗi, KHÔNG gọi signIn', (tester) async {
    final actions = _FakeActions();
    await tester.pumpWidget(_wrap(LoginScreen(actions: actions)));

    await tester.enterText(find.byType(TextField).at(0), 'a@b.com');
    await tester.tap(find.widgetWithText(ElevatedButton, 'Đăng nhập'));
    await tester.pump();

    expect(find.text('Vui lòng nhập mật khẩu.'), findsOneWidget);
    expect(actions.signInCalls, 0);
  });

  testWidgets('chống double-submit: bấm 2 lần khi đang gửi -> signIn 1 lần',
      (tester) async {
    final actions = _FakeActions()..gate = Completer<void>();
    await tester.pumpWidget(_wrap(LoginScreen(actions: actions)));

    await tester.enterText(find.byType(TextField).at(0), 'a@b.com');
    await tester.enterText(find.byType(TextField).at(1), 'matkhau');

    // Lần 1: bấm nút theo nhãn.
    await tester.tap(find.widgetWithText(ElevatedButton, 'Đăng nhập'));
    await tester
        .pump(); // vào trạng thái submitting -> nút hiện spinner, bị khoá

    // Nút giờ hiển thị spinner (không còn nhãn) và onPressed = null.
    expect(find.widgetWithText(ElevatedButton, 'Đăng nhập'), findsNothing);
    expect(
      find.descendant(
        of: find.byType(ElevatedButton),
        matching: find.byType(CircularProgressIndicator),
      ),
      findsOneWidget,
    );

    // Lần 2: bấm lại nút (đang bị khoá) -> không kích hoạt gì.
    await tester.tap(find.byType(ElevatedButton), warnIfMissed: false);
    await tester.pump();

    expect(actions.signInCalls, 1);

    actions.gate!.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('signIn thất bại -> hiện thông báo tiếng Việt', (tester) async {
    final actions = _FakeActions()
      ..signInError = const AuthException('x', code: 'invalid_credentials');
    await tester.pumpWidget(_wrap(LoginScreen(actions: actions)));

    await tester.enterText(find.byType(TextField).at(0), 'a@b.com');
    await tester.enterText(find.byType(TextField).at(1), 'saibet');
    await tester.tap(find.widgetWithText(ElevatedButton, 'Đăng nhập'));
    await tester.pumpAndSettle();

    expect(find.text('Email hoặc mật khẩu không đúng.'), findsOneWidget);
    expect(actions.signInCalls, 1);
  });

  testWidgets('submit từ bàn phím (done) -> gọi signIn', (tester) async {
    final actions = _FakeActions();
    await tester.pumpWidget(_wrap(LoginScreen(actions: actions)));

    await tester.enterText(find.byType(TextField).at(0), 'a@b.com');
    await tester.enterText(find.byType(TextField).at(1), 'matkhau');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    expect(actions.signInCalls, 1);
    expect(actions.lastSignInEmail, 'a@b.com');
  });

  testWidgets('không hiện hotline 1900 1234', (tester) async {
    await tester.pumpWidget(_wrap(LoginScreen(actions: _FakeActions())));
    expect(find.textContaining('1900'), findsNothing);
    expect(find.textContaining('quản lý HTX'), findsOneWidget);
  });

  testWidgets('notice sessionExpired -> hiện banner hết phiên', (tester) async {
    await tester.pumpWidget(_wrap(
      LoginScreen(actions: _FakeActions(), notice: LoginNotice.sessionExpired),
    ));
    expect(find.textContaining('hết hạn'), findsOneWidget);
  });

  testWidgets('quên mật khẩu: mở màn, gửi email -> gọi reset + hiện thành công',
      (tester) async {
    final actions = _FakeActions();
    await tester.pumpWidget(_wrap(LoginScreen(actions: actions)));

    await tester.enterText(find.byType(TextField).at(0), 'nong.dan@htx.vn');
    await tester.tap(find.text('Quên mật khẩu?'));
    await tester.pumpAndSettle();

    // Email được mang sang sẵn.
    expect(find.text('Đặt lại mật khẩu'), findsOneWidget);
    await tester
        .tap(find.widgetWithText(ElevatedButton, 'Gửi hướng dẫn đặt lại'));
    await tester.pumpAndSettle();

    expect(actions.resetCalls, 1);
    expect(actions.lastResetEmail, 'nong.dan@htx.vn');
    expect(find.textContaining('Đã gửi'), findsOneWidget);
  });

  testWidgets('quên mật khẩu: email trống -> báo lỗi, KHÔNG gọi reset',
      (tester) async {
    final actions = _FakeActions();
    await tester.pumpWidget(_wrap(LoginScreen(actions: actions)));

    await tester.tap(find.text('Quên mật khẩu?'));
    await tester.pumpAndSettle();
    await tester
        .tap(find.widgetWithText(ElevatedButton, 'Gửi hướng dẫn đặt lại'));
    await tester.pump();

    expect(actions.resetCalls, 0);
    expect(find.textContaining('nhập email'), findsOneWidget);
  });
}

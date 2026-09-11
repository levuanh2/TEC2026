import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/reset_password_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supabase_flutter/supabase_flutter.dart' show AuthException;

Widget _wrap(Widget child) =>
    MaterialApp(theme: AgriCarbonTheme.light(), home: child);

void main() {
  testWidgets('mật khẩu quá ngắn -> báo lỗi, KHÔNG gọi onSubmit',
      (tester) async {
    var calls = 0;
    await tester.pumpWidget(_wrap(ResetPasswordScreen(
      onSubmit: (_) async => calls++,
      onDone: () {},
    )));

    await tester.enterText(find.byType(TextField).at(0), '123');
    await tester.enterText(find.byType(TextField).at(1), '123');
    await tester.tap(find.widgetWithText(ElevatedButton, 'Đổi mật khẩu'));
    await tester.pump();

    expect(find.textContaining('ít nhất 6 ký tự'), findsOneWidget);
    expect(calls, 0);
  });

  testWidgets('nhập lại không khớp -> báo lỗi, KHÔNG gọi onSubmit',
      (tester) async {
    var calls = 0;
    await tester.pumpWidget(_wrap(ResetPasswordScreen(
      onSubmit: (_) async => calls++,
      onDone: () {},
    )));

    await tester.enterText(find.byType(TextField).at(0), 'matkhau-moi');
    await tester.enterText(find.byType(TextField).at(1), 'khac-hoan-toan');
    await tester.tap(find.widgetWithText(ElevatedButton, 'Đổi mật khẩu'));
    await tester.pump();

    expect(find.textContaining('chưa khớp'), findsOneWidget);
    expect(calls, 0);
  });

  testWidgets('hợp lệ -> gọi onSubmit, hiện màn thành công', (tester) async {
    String? received;
    await tester.pumpWidget(_wrap(ResetPasswordScreen(
      onSubmit: (p) async => received = p,
      onDone: () {},
    )));

    await tester.enterText(find.byType(TextField).at(0), 'matkhau-moi-123');
    await tester.enterText(find.byType(TextField).at(1), 'matkhau-moi-123');
    await tester.tap(find.widgetWithText(ElevatedButton, 'Đổi mật khẩu'));
    await tester.pumpAndSettle();

    expect(received, 'matkhau-moi-123');
    expect(find.text('Đã đổi mật khẩu'), findsOneWidget);
  });

  testWidgets('onSubmit ném -> thông báo tiếng Việt, không lộ exception thô',
      (tester) async {
    await tester.pumpWidget(_wrap(ResetPasswordScreen(
      onSubmit: (_) async => throw const AuthException('raw detail',
          code: 'over_request_rate_limit'),
      onDone: () {},
    )));

    await tester.enterText(find.byType(TextField).at(0), 'matkhau-moi-123');
    await tester.enterText(find.byType(TextField).at(1), 'matkhau-moi-123');
    await tester.tap(find.widgetWithText(ElevatedButton, 'Đổi mật khẩu'));
    await tester.pumpAndSettle();

    expect(find.textContaining('thử lại sau'), findsOneWidget);
    expect(find.textContaining('raw detail'), findsNothing);
    expect(find.text('Đã đổi mật khẩu'), findsNothing);
  });

  testWidgets('"Để sau" -> gọi onDone', (tester) async {
    var done = 0;
    await tester.pumpWidget(_wrap(ResetPasswordScreen(
      onSubmit: (_) async {},
      onDone: () => done++,
    )));

    await tester.tap(find.widgetWithText(OutlinedButton, 'Để sau'));
    await tester.pump();
    expect(done, 1);
  });
}

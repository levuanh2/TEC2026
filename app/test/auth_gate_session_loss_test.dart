import 'package:agricarbon_app/app_services.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/login_screen.dart';
import 'package:agricarbon_app/shell/auth_controller.dart';
import 'package:agricarbon_app/shell/auth_gate.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Fake only the auth boundary; AuthGate and navigation are production code.
class _Auth extends ChangeNotifier implements AuthController {
  AuthPhase state = AuthPhase.authenticated;
  @override
  AuthPhase get phase => state;
  @override
  bool get mustChangePassword => true; // a root screen that needs no services
  @override
  bool get isPasswordRecovery => false;
  @override
  bool get isAuthenticated => state == AuthPhase.authenticated;
  void set(AuthPhase p) {
    state = p;
    notifyListeners();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Services implements AppServices {
  _Services(this.authController);
  @override
  final AuthController authController;
  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw StateError('Unexpected service access: ${invocation.memberName}');
}

Future<void> _pushPrivatePages(WidgetTester tester) async {
  final nav = tester.state<NavigatorState>(find.byType(Navigator).first);
  nav.push(MaterialPageRoute<void>(
      builder: (_) => const Scaffold(body: Text('Hộ của người dùng A'))));
  await tester.pumpAndSettle();
  nav.push(MaterialPageRoute<void>(
      builder: (_) => const Scaffold(body: Text('Vụ của người dùng A'))));
  await tester.pumpAndSettle();
  expect(find.text('Vụ của người dùng A'), findsOneWidget);
}

void main() {
  for (final lost in [AuthPhase.sessionExpired, AuthPhase.signedOut]) {
    testWidgets('losing the session ($lost) removes pushed pages',
        (tester) async {
      final auth = _Auth();
      addTearDown(auth.dispose);
      await tester.pumpWidget(MaterialApp(
          theme: AgriCarbonTheme.light(),
          home: AuthGate(services: _Services(auth))));
      await tester.pumpAndSettle();
      await _pushPrivatePages(tester);

      auth.set(lost);
      await tester.pumpAndSettle();
      expect(find.text('Vụ của người dùng A'), findsNothing);
      expect(find.text('Hộ của người dùng A'), findsNothing);
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('staying authenticated keeps pushed pages', (tester) async {
    final auth = _Auth();
    addTearDown(auth.dispose);
    await tester.pumpWidget(MaterialApp(
        theme: AgriCarbonTheme.light(),
        home: AuthGate(services: _Services(auth))));
    await tester.pumpAndSettle();
    await _pushPrivatePages(tester);
    auth.set(AuthPhase.authenticated); // e.g. a token refresh notification
    await tester.pumpAndSettle();
    expect(find.text('Vụ của người dùng A'), findsOneWidget);
  });
}

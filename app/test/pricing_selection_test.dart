import 'package:agricarbon_app/app_services.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/forced_password_change_screen.dart';
import 'package:agricarbon_app/screens/login_screen.dart';
import 'package:agricarbon_app/screens/pricing_screen.dart';
import 'package:agricarbon_app/screens/reset_password_screen.dart';
import 'package:agricarbon_app/screens/service_plans.dart';
import 'package:agricarbon_app/shell/auth_controller.dart';
import 'package:agricarbon_app/shell/auth_gate.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Fake only the auth boundary; widgets and navigation are production code.
class _Auth extends ChangeNotifier implements AuthController {
  AuthPhase state = AuthPhase.signedOut;
  bool forcePassword = false;
  bool recovery = false;
  int signInCalls = 0;

  @override
  AuthPhase get phase => state;
  @override
  bool get mustChangePassword => forcePassword;
  @override
  bool get isPasswordRecovery => recovery;
  @override
  bool get isAuthenticated => state == AuthPhase.authenticated;

  void update() => notifyListeners();
  @override
  Future<void> signIn({required String email, required String password}) async {
    signInCalls++;
    state = AuthPhase.authenticated;
    notifyListeners();
  }

  @override
  Future<void> sendPasswordReset(String email) async {}
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// No network, database or synchronization service is permitted in these flows.
class _Services implements AppServices {
  _Services(this.authController);
  @override
  final AuthController authController;
  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw StateError('Unexpected service access: ${invocation.memberName}');
}

Widget _host(Widget child, {double scale = 1}) => MaterialApp(
      theme: AgriCarbonTheme.light(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
            disableAnimations: true, textScaler: TextScaler.linear(scale)),
        child: child!,
      ),
      home: child,
    );

void _size(WidgetTester tester, Size size) {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Finder _planAction(String name) {
  final card =
      find.ancestor(of: find.text(name), matching: find.byType(Column)).first;
  return find.descendant(of: card, matching: find.byType(ElevatedButton));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    final font = FontLoader(AppBrand.fontFamily);
    for (final face in ['Regular', 'Medium', 'SemiBold', 'Bold', 'ExtraBold']) {
      font.addFont(rootBundle.load('assets/fonts/BeVietnamPro-$face.ttf'));
    }
    await font.load();
  });

  const choices = [
    (false, 'FREE', 0),
    (false, 'PLUS', 999990),
    (false, 'PRO', 1999990),
    (true, 'FREE', 0),
    (true, 'PLUS', 14990000),
    (true, 'PRO', 49990000),
  ];
  for (final (cooperative, name, price) in choices) {
    testWidgets('signed-out selection preserves $cooperative $name and price',
        (tester) async {
      _size(tester, const Size(390, 844));
      final auth = _Auth();
      addTearDown(auth.dispose);
      ServicePlanSelection? picked;
      await tester.pumpWidget(_host(LoginScreen(
          actions: auth, onPlanSelected: (value) => picked = value)));
      await tester.pumpAndSettle();
      await _tap(tester, find.text('Xem bảng giá dịch vụ'));
      if (cooperative) {
        await _tap(tester, find.widgetWithText(ChoiceChip, 'Hợp tác xã'));
      }
      expect(find.text(price == 0 ? 'Miễn phí' : AppFormat.number(price)),
          findsOneWidget);
      await _tap(tester, _planAction(name));
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(picked?.cooperative, cooperative);
      expect(picked?.plan.name, name);
      expect(picked?.plan.price, price);
      expect(find.textContaining('Bạn đã chọn gói $name —'), findsOneWidget);
      expect(auth.signInCalls, 0);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('back from pricing does not select or authenticate',
      (tester) async {
    _size(tester, const Size(390, 844));
    final auth = _Auth();
    addTearDown(auth.dispose);
    var callbacks = 0;
    await tester.pumpWidget(
        _host(LoginScreen(actions: auth, onPlanSelected: (_) => callbacks++)));
    await tester.pumpAndSettle();
    await _tap(tester, find.text('Xem bảng giá dịch vụ'));
    await _tap(tester, find.byTooltip('Quay lại'));
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(callbacks, 0);
    expect(auth.signInCalls, 0);
    expect(find.textContaining('Bạn đã chọn gói'), findsNothing);
  });

  testWidgets('pricing fits phone large text and tablet, audience can change',
      (tester) async {
    for (final (size, scale) in [
      (const Size(320, 568), 1.5),
      (const Size(1100, 900), 1.0),
    ]) {
      _size(tester, size);
      await tester.pumpWidget(_host(const PricingScreen(), scale: scale));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await _tap(tester, find.widgetWithText(ChoiceChip, 'Hợp tác xã'));
      expect(find.text('49.990.000'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await _tap(tester, find.widgetWithText(ChoiceChip, 'Nông hộ'));
      expect(find.text('1.999.990'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    }
  });

  testWidgets('review shows free and paid choice without claiming activation',
      (tester) async {
    _size(tester, const Size(390, 844));
    for (final plan in [farmerServicePlans.first, cooperativeServicePlans[1]]) {
      var done = 0;
      await tester.pumpWidget(_host(PlanSelectionScreen(
          selection:
              ServicePlanSelection(plan: plan, cooperative: plan.price != 0),
          onDone: () => done++)));
      await tester.pumpAndSettle();
      expect(find.text('Gói ${plan.name}'), findsOneWidget);
      expect(find.text(plan.price == 0 ? 'Miễn phí' : '14.990.000 VNĐ'),
          findsOneWidget);
      expect(find.textContaining('Chưa phát sinh thanh toán hoặc kích hoạt'),
          findsOneWidget);
      await _tap(tester, find.widgetWithText(ElevatedButton, 'Tiếp tục'));
      expect(done, 1);
      expect(tester.takeException(), isNull);
    }
  });

  testWidgets('AuthGate retains selection and password gates keep priority',
      (tester) async {
    _size(tester, const Size(390, 844));
    final auth = _Auth();
    addTearDown(auth.dispose);
    await tester.pumpWidget(_host(AuthGate(services: _Services(auth))));
    await tester.pumpAndSettle();
    await _tap(tester, find.text('Xem bảng giá dịch vụ'));
    await _tap(tester, find.widgetWithText(ChoiceChip, 'Hợp tác xã'));
    await _tap(tester, _planAction('PLUS'));

    // Losing the session must keep the auth screen above the pending choice.
    auth.state = AuthPhase.sessionExpired;
    auth.update();
    await tester.pumpAndSettle();
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.textContaining('Bạn đã chọn gói PLUS — Hợp tác xã'),
        findsOneWidget);
    auth.forcePassword = true;
    await tester.enterText(find.byType(TextField).at(0), 'choice@example.test');
    await tester.enterText(find.byType(TextField).at(1), 'mock-password-only');
    await _tap(tester, find.widgetWithText(ElevatedButton, 'Đăng nhập'));
    expect(auth.signInCalls, 1);
    expect(find.byType(ForcedPasswordChangeScreen), findsOneWidget);
    expect(find.byType(PlanSelectionScreen), findsNothing);

    auth.forcePassword = false;
    auth.recovery = true;
    auth.update();
    await tester.pumpAndSettle();
    expect(find.byType(ResetPasswordScreen), findsOneWidget);
    expect(find.byType(PlanSelectionScreen), findsNothing);

    auth.recovery = false;
    auth.update();
    await tester.pumpAndSettle();
    expect(find.byType(PlanSelectionScreen), findsOneWidget);
    expect(find.text('Gói PLUS'), findsOneWidget);
    expect(find.text('14.990.000 VNĐ'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

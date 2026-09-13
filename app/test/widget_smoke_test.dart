import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/bootstrap_error_screen.dart';
import 'package:agricarbon_app/screens/configuration_error_screen.dart';
import 'package:agricarbon_app/screens/reset_password_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Smoke: các màn không phụ thuộc AppServices phải dựng được ở nhiều kích thước
/// máy + text scale 1.5 mà KHÔNG ném (không tràn layout, không lỗi assert).
const _sizes = <(String, Size)>[
  ('nhỏ ~320x568', Size(320, 568)),
  ('tham chiếu 430x932', Size(430, 932)),
  ('rộng / tablet 800x1200', Size(800, 1200)),
];

Widget _host(Widget child, {double textScale = 1.0}) => MaterialApp(
      theme: AgriCarbonTheme.light(),
      home: MediaQuery(
        data: MediaQueryData(textScaler: TextScaler.linear(textScale)),
        child: child,
      ),
    );

void main() {
  final screens = <String, Widget Function()>{
    'ConfigurationErrorScreen': () => const ConfigurationErrorScreen(
          missingKeys: ['SUPABASE_URL', 'BACKEND_BASE_URL'],
        ),
    'BootstrapErrorScreen': () => const BootstrapErrorScreen(),
    'ResetPasswordScreen': () =>
        ResetPasswordScreen(onSubmit: (_) async {}, onDone: () {}),
  };

  for (final entry in screens.entries) {
    for (final (label, size) in _sizes) {
      testWidgets('${entry.key} @ $label', (tester) async {
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);

        await tester.pumpWidget(_host(entry.value()));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('${entry.key} @ text scale 1.5', (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_host(entry.value(), textScale: 1.5));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  }
}

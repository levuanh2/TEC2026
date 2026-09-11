import 'package:agricarbon_app/config.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/main.dart';
import 'package:agricarbon_app/screens/configuration_error_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('không có --dart-define -> canInitSupabase = false, liệt kê đủ 3 biến',
      () {
    // Trong môi trường test không có String.fromEnvironment nào được set.
    expect(AppConfig.canInitSupabase, isFalse);
    expect(AppConfig.isConfigured, isFalse);
    expect(
      AppConfig.missingKeys,
      containsAll(<String>[
        'SUPABASE_URL',
        'SUPABASE_PUBLISHABLE_KEY',
        'BACKEND_BASE_URL',
      ]),
    );
  });

  testWidgets(
      'ConfigurationErrorScreen dựng được, hiện tên biến thiếu, KHÔNG crash',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AgriCarbonTheme.light(),
        home: const ConfigurationErrorScreen(
          missingKeys: ['SUPABASE_URL', 'BACKEND_BASE_URL'],
        ),
      ),
    );

    expect(tester.takeException(), isNull);
    expect(find.text('SUPABASE_URL'), findsOneWidget);
    expect(find.text('BACKEND_BASE_URL'), findsOneWidget);
    expect(find.textContaining('chưa được cấu hình'), findsOneWidget);
  });

  testWidgets('cỡ chữ hệ thống 3.0 -> kẹp ở 1.8, không tràn layout',
      (tester) async {
    // Yêu cầu tiếp cận: phải hỗ trợ ÍT NHẤT 1.5. Chặn trên ở 1.8 để không vỡ
    // hẳn ở 2.0+ — 1.8 > 1.5 nên vẫn thoả yêu cầu.
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 3.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(3.0)),
        child: const AgriCarbonApp.config(missingKeys: ['SUPABASE_URL']),
      ),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    final ctx = tester.element(find.text('SUPABASE_URL'));
    final scaled = MediaQuery.textScalerOf(ctx).scale(10.0);
    expect(scaled, lessThanOrEqualTo(18.0)); // <= 1.8x
    expect(scaled, greaterThanOrEqualTo(15.0)); // vẫn cho >= 1.5x
  });
}

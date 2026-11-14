import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/plot_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Found on a physical Xiaomi 24094RAD4G (Android 16): the add-plot dialog
/// overflowed by 72 px in landscape with the keyboard open at font scale 1.8.
/// Phone landscape 2400x1080 px @ 2.8125, keyboard 698 px, status bar 100 px
/// (measured from the device screenshot) => ~100 dp left for the dialog.
Future<void> _pumpDialog(WidgetTester tester, Widget dialog) async {
  tester.view.physicalSize = const Size(2400, 1080);
  tester.view.devicePixelRatio = 2.8125;
  tester.view.viewInsets = const FakeViewPadding(bottom: 698);
  tester.view.padding = const FakeViewPadding(top: 100);
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: AgriCarbonTheme.light(),
    builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: const TextScaler.linear(1.8)),
        child: child!),
    home: Builder(
        builder: (context) => TextButton(
            onPressed: () =>
                showDialog<void>(context: context, builder: (_) => dialog),
            child: const Text('open'))),
  ));
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('add-plot dialog does not overflow: landscape + keyboard + 1.8x',
      (tester) async {
    await _pumpDialog(tester, debugPlotFormDialog());
    expect(tester.takeException(), isNull);
    expect(find.text('Thêm thửa ruộng'), findsOneWidget);
  });

  testWidgets(
      'confirmation dialog does not overflow: landscape + keyboard + 1.8x',
      (tester) async {
    await _pumpDialog(
        tester,
        const ConfirmationDialog(
            title: 'Đăng xuất?',
            message:
                'Dữ liệu đã lưu trên máy vẫn được giữ. Bạn sẽ cần đăng nhập lại để đồng bộ và xem kết quả.'));
    expect(tester.takeException(), isNull);
  });
}

import 'package:agricarbon_app/design/design.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Found on a physical Xiaomi 24094RAD4G (Android 16): in "Ghi: Bón phân",
/// landscape + Gboard + font 1.8 left ~43 dp under the full header, and the
/// focused "Tên phân" line stayed under the keyboard (no overflow error, so
/// only visible on screen). Geometry: 2400x1080 px @ 2.8125, status bar 100 px,
/// keyboard 698 px.
const _dpr = 2.8125;

void _geometry(WidgetTester tester, Size size, {double keyboardPx = 0}) {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = _dpr;
  tester.view.padding = const FakeViewPadding(top: 100);
  tester.view.viewPadding = const FakeViewPadding(top: 100);
  tester.view.viewInsets = FakeViewPadding(bottom: keyboardPx);
}

Widget _form({Widget? bottomBar}) => MaterialApp(
      theme: AgriCarbonTheme.light(),
      builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: const TextScaler.linear(1.8)),
          child: child!),
      home: AppScaffold(
        header: const AppHeader(
            title: 'Ghi: Bón phân',
            subtitle: 'Vụ minh họa',
            showBackButton: true),
        bottomBar: bottomBar,
        body: Column(children: [
          for (final label in [
            'Tên phân *',
            'Lượng (kg) *',
            'Đạm (%)',
            'Chi phí'
          ])
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.md),
              child: TextField(decoration: InputDecoration(labelText: label)),
            ),
        ]),
      ),
    );

Finder _field(String label) => find.widgetWithText(TextField, label);

void main() {
  testWidgets('portrait without keyboard: full header with subtitle',
      (tester) async {
    _geometry(tester, const Size(1080, 2400));
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_form());
    expect(find.text('Vụ minh họa'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  for (final label in ['Tên phân *', 'Chi phí']) {
    testWidgets(
        'landscape + keyboard + 1.8: compact header, focused "$label" line '
        'above the keyboard', (tester) async {
      _geometry(tester, const Size(2400, 1080), keyboardPx: 698);
      addTearDown(tester.view.reset);
      await tester.pumpWidget(_form());
      await tester.showKeyboard(_field(label));
      await tester.pumpAndSettle();
      expect(find.text('Vụ minh họa'), findsNothing,
          reason: 'subtitle hidden in the compact header');
      final keyboardTop = (1080 - 698) / _dpr;
      final header = tester.getRect(find.byType(AppHeader));
      final line = tester.getRect(find.descendant(
          of: _field(label), matching: find.byType(EditableText)));
      expect(line.top, greaterThanOrEqualTo(header.bottom - 0.5));
      expect(line.bottom, lessThanOrEqualTo(keyboardTop + 0.5));
      expect(find.byTooltip('Quay lại'), findsOneWidget,
          reason: 'back stays reachable');
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
      'cramped: a pinned bottom bar moves into the scroll area; '
      'normal: it stays pinned', (tester) async {
    final save = PrimaryButton(label: 'Lưu vụ', onPressed: () {});
    _geometry(tester, const Size(2400, 1080), keyboardPx: 698);
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_form(bottomBar: save));
    await tester.showKeyboard(_field('Tên phân *'));
    await tester.pumpAndSettle();
    expect(
        find.ancestor(
            of: find.text('Lưu vụ'),
            matching: find.byType(SingleChildScrollView)),
        findsOneWidget);
    await tester.ensureVisible(find.text('Lưu vụ'));
    await tester.pumpAndSettle();
    expect(tester.getRect(find.text('Lưu vụ')).bottom,
        lessThanOrEqualTo((1080 - 698) / _dpr + 0.5));
    expect(tester.takeException(), isNull);

    _geometry(tester, const Size(1080, 2400));
    await tester.pumpAndSettle();
    expect(
        find.ancestor(
            of: find.text('Lưu vụ'),
            matching: find.byType(SingleChildScrollView)),
        findsNothing);
    expect(find.text('Vụ minh họa'), findsOneWidget);
  });

  test('isCramped needs both the keyboard and little free height', () {
    MediaQueryData m(double h, double kb) => MediaQueryData(
        size: Size(400, h),
        viewPadding: const EdgeInsets.only(top: 36),
        viewInsets: EdgeInsets.only(bottom: kb));
    expect(isCramped(m(384, 248)), isTrue);
    expect(isCramped(m(384, 0)), isFalse, reason: 'landscape, no keyboard');
    expect(isCramped(m(853, 320)), isFalse, reason: 'portrait keyboard');
  });
}

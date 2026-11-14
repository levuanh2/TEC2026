import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/plot_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Device geometry measured on the Xiaomi 24094RAD4G (Android 16):
/// 2400x1080 px at 2.8125 dpr, status bar 100 px, Gboard 698 px in landscape.
/// Before the fix the add-plot dialog overflowed by 72 px in landscape +
/// keyboard + font 1.8, and then had a one-line scroll area.
const _dpr = 2.8125;
const _portrait = Size(1080, 2400);
const _landscape = Size(2400, 1080);

void _geometry(WidgetTester tester, Size size, {double keyboardPx = 0}) {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = _dpr;
  tester.view.padding = const FakeViewPadding(top: 100);
  tester.view.viewPadding = const FakeViewPadding(top: 100);
  tester.view.viewInsets = FakeViewPadding(bottom: keyboardPx);
}

Future<void> _open(WidgetTester tester, Widget dialog, double scale) async {
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: AgriCarbonTheme.light(),
    builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: TextScaler.linear(scale)),
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

Finder get _areaField => find.widgetWithText(TextField, 'Diện tích (ha) *');
Finder get _codeField => find.widgetWithText(TextField, 'Mã thửa *');

void main() {
  testWidgets('portrait, font 1.0: normal dialog', (tester) async {
    _geometry(tester, _portrait);
    await _open(tester, debugPlotFormDialog(), 1.0);
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.byType(AppBar), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'landscape + keyboard + font 1.8: full-screen form, focused field above '
      'the keyboard, actions reachable', (tester) async {
    _geometry(tester, _landscape, keyboardPx: 698);
    await _open(tester, debugPlotFormDialog(), 1.8);
    expect(tester.takeException(), isNull);
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.widgetWithText(AppBar, 'Thêm thửa ruộng'), findsOneWidget);

    await tester.showKeyboard(_areaField);
    await tester.pumpAndSettle();
    // ~44 dp are left between the app bar and the keyboard: the whole
    // outlined field (~70 dp at 1.8x) cannot fit, but the line being typed
    // (EditableText, where the caret is) must be fully visible.
    final keyboardTop = (_landscape.height - 698) / _dpr;
    final line = tester.getRect(
        find.descendant(of: _areaField, matching: find.byType(EditableText)));
    final appBar = tester.getRect(find.byType(AppBar));
    expect(line.bottom, lessThanOrEqualTo(keyboardTop + 0.5),
        reason: 'the typed line must sit above the keyboard');
    expect(line.top, greaterThanOrEqualTo(appBar.bottom - 0.5),
        reason: 'the typed line must not hide under the app bar');
    // Save and Cancel are in the app bar, above the keyboard.
    expect(tester.getRect(find.text('Lưu')).bottom, lessThan(keyboardTop));
    expect(tester.getRect(find.byTooltip('Huỷ')).bottom, lessThan(keyboardTop));
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'switching to full-screen when the keyboard opens keeps typed text and '
      'focus; validation still runs', (tester) async {
    _geometry(tester, _portrait);
    await _open(tester, debugPlotFormDialog(), 1.8);
    expect(find.byType(AlertDialog), findsOneWidget);
    await tester.enterText(_codeField, 'T-01');
    await tester.pump();

    // Rotate to landscape and raise the keyboard.
    _geometry(tester, _landscape, keyboardPx: 698);
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(AppBar), findsOneWidget);
    expect(tester.widget<TextField>(_codeField).controller!.text, 'T-01');
    final editable = tester.state<EditableTextState>(
        find.descendant(of: _codeField, matching: find.byType(EditableText)));
    expect(editable.widget.focusNode.hasFocus, isTrue,
        reason: 'focus survives the presentation change');

    // Back to portrait without keyboard: stays full-screen (latched), text kept.
    _geometry(tester, _portrait);
    await tester.pumpAndSettle();
    expect(find.byType(AppBar), findsOneWidget);
    expect(tester.widget<TextField>(_codeField).controller!.text, 'T-01');

    // Validation is unchanged: missing area is refused, the form stays open.
    await tester.tap(find.text('Lưu'));
    await tester.pumpAndSettle();
    expect(find.byType(AppBar), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('cancel closes the full-screen form without a result',
      (tester) async {
    _geometry(tester, _landscape, keyboardPx: 698);
    await _open(tester, debugPlotFormDialog(), 1.8);
    await tester.tap(find.byTooltip('Huỷ'));
    await tester.pumpAndSettle();
    expect(find.byType(AppBar), findsNothing);
    expect(find.text('open'), findsOneWidget);
  });

  testWidgets('confirmation dialog: landscape + font 1.8, no overflow',
      (tester) async {
    _geometry(tester, _landscape);
    await _open(
        tester,
        const ConfirmationDialog(
            title: 'Đăng xuất?',
            message: 'Dữ liệu đã lưu trên máy vẫn được giữ. Bạn sẽ cần '
                'đăng nhập lại để đồng bộ và xem kết quả.'),
        1.8);
    expect(tester.takeException(), isNull);
  });

  test('fitsDialog uses free height after keyboard and system bars', () {
    MediaQueryData m(double h, double kb, double scale) => MediaQueryData(
        size: Size(400, h),
        viewPadding: const EdgeInsets.only(top: 36),
        viewInsets: EdgeInsets.only(bottom: kb),
        textScaler: TextScaler.linear(scale));
    expect(AdaptiveFormDialog.fitsDialog(m(853, 0, 1.0), 3), isTrue);
    expect(AdaptiveFormDialog.fitsDialog(m(853, 320, 1.0), 3), isTrue);
    expect(AdaptiveFormDialog.fitsDialog(m(384, 248, 1.0), 3), isFalse);
    expect(AdaptiveFormDialog.fitsDialog(m(853, 320, 1.8), 3), isFalse);
  });
}

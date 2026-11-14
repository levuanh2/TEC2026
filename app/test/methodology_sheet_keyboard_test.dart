import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/screens/season_methodology_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Found on a physical Xiaomi 24094RAD4G (Android 16): in landscape with the
/// keyboard open at font 1.8, the methodology sheet showed only the days field.
/// Save sat below the keyboard and no Cancel was visible. Geometry:
/// 2400x1080 px @ 2.8125, status bar 100 px, Gboard 698 px.
const _dpr = 2.8125;
const _portrait = Size(1080, 2400);
const _landscape = Size(2400, 1080);
const _keyboardPx = 698.0;

void _geometry(WidgetTester tester, Size size, {double keyboardPx = 0}) {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = _dpr;
  tester.view.padding = const FakeViewPadding(top: 100);
  tester.view.viewPadding = const FakeViewPadding(top: 100);
  tester.view.viewInsets = FakeViewPadding(bottom: keyboardPx);
}

final _season = CropSeason(
  clientId: 'cs1',
  plotClientId: 'p1',
  seasonCode: 'DEMO-HT-2026',
  createdAt: DateTime(2026, 5, 18),
  updatedAt: DateTime(2026, 5, 18),
);

/// Opens the real sheet; [result] receives what it popped.
Future<List<SeasonMethodologyValues?>> _open(WidgetTester tester,
    {double scale = 1.8}) async {
  addTearDown(tester.view.reset);
  final results = <SeasonMethodologyValues?>[];
  await tester.pumpWidget(MaterialApp(
    theme: AgriCarbonTheme.light(),
    builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: TextScaler.linear(scale)),
        child: child!),
    home: Builder(
        builder: (context) => Scaffold(
              body: TextButton(
                  onPressed: () async => results.add(
                      await showSeasonMethodologySheet(context,
                          season: _season)),
                  child: const Text('open')),
            )),
  ));
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  return results;
}

Finder get _days => find.descendant(
    of: find.byKey(const Key('methodology-days')),
    matching: find.byType(TextField));

void main() {
  testWidgets(
      'portrait, no keyboard: unchanged layout (intro, handle, Save at '
      'the end, no pinned Cancel)', (tester) async {
    _geometry(tester, _portrait);
    await _open(tester, scale: 1.0);
    expect(find.text('Thông tin phương pháp tính'), findsOneWidget);
    expect(find.bySemanticsLabel('Đóng'), findsOneWidget);
    expect(find.byKey(const Key('methodology-cancel')), findsNothing);
    expect(
        find.descendant(
            of: find.byKey(const Key('methodology-save')),
            matching: find.byType(ElevatedButton)),
        findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'landscape + keyboard + 1.8: typed line visible, Cancel and Save above '
      'the keyboard', (tester) async {
    _geometry(tester, _landscape, keyboardPx: _keyboardPx);
    await _open(tester);
    await tester.showKeyboard(_days);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final keyboardTop = (_landscape.height - _keyboardPx) / _dpr;
    final save = tester.getRect(find.byKey(const Key('methodology-save')));
    final cancel = tester.getRect(find.byKey(const Key('methodology-cancel')));
    expect(save.bottom, lessThanOrEqualTo(keyboardTop));
    expect(cancel.bottom, lessThanOrEqualTo(keyboardTop));
    // Below the status bar: on the phone, taps there never reach the app.
    const statusBar = 100 / _dpr;
    expect(save.top, greaterThanOrEqualTo(statusBar));
    expect(cancel.top, greaterThanOrEqualTo(statusBar));
    final line = tester.getRect(
        find.descendant(of: _days, matching: find.byType(EditableText)));
    expect(line.top, greaterThanOrEqualTo(save.bottom - 0.5),
        reason: 'the typed line is not hidden under the action row');
    expect(line.bottom, lessThanOrEqualTo(keyboardTop + 0.5),
        reason: 'the typed line sits above the keyboard');
  });

  testWidgets(
      'input and focus survive portrait -> landscape+keyboard -> portrait; '
      'Save returns the value', (tester) async {
    _geometry(tester, _portrait);
    final results = await _open(tester);
    await tester.enterText(_days, '95');
    await tester.pump();

    _geometry(tester, _landscape, keyboardPx: _keyboardPx);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('methodology-cancel')), findsOneWidget);
    expect(tester.widget<TextField>(_days).controller!.text, '95');
    // The keyboard appeared AFTER the sheet opened (rotation on the phone):
    // the sheet must follow the new inset, keeping its actions visible.
    final keyboardTop = (_landscape.height - _keyboardPx) / _dpr;
    for (final k in ['methodology-cancel', 'methodology-save']) {
      final r = tester.getRect(find.byKey(Key(k)));
      expect(r.top, greaterThanOrEqualTo(100 / _dpr),
          reason: '$k under status bar');
      expect(r.bottom, lessThanOrEqualTo(keyboardTop),
          reason: '$k under keyboard');
    }
    final editable = tester.state<EditableTextState>(
        find.descendant(of: _days, matching: find.byType(EditableText)));
    expect(editable.widget.focusNode.hasFocus, isTrue);

    _geometry(tester, _portrait);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('methodology-cancel')), findsNothing);
    expect(tester.widget<TextField>(_days).controller!.text, '95');

    await tester.ensureVisible(find.byKey(const Key('methodology-save')));
    await tester.tap(find.byKey(const Key('methodology-save')));
    await tester.pumpAndSettle();
    expect(results.single?.cultivationDays, 95);
  });

  testWidgets('cramped Save validates exactly like the normal Save',
      (tester) async {
    _geometry(tester, _landscape, keyboardPx: _keyboardPx);
    final results = await _open(tester);
    await tester.enterText(_days, '0');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('methodology-save')));
    await tester.pumpAndSettle();
    expect(results, isEmpty, reason: 'invalid days keep the sheet open');
    _geometry(tester, _portrait);
    await tester.pumpAndSettle();
    expect(find.text('Số ngày canh tác phải lớn hơn 0.'), findsOneWidget);
  });

  for (final how in ['cancel button', 'system back']) {
    testWidgets('cramped: $how closes without saving', (tester) async {
      _geometry(tester, _landscape, keyboardPx: _keyboardPx);
      final results = await _open(tester);
      await tester.enterText(_days, '95');
      await tester.pumpAndSettle();
      if (how == 'cancel button') {
        await tester.tap(find.byKey(const Key('methodology-cancel')));
      } else {
        await tester.binding.handlePopRoute();
      }
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('methodology-days')), findsNothing);
      expect(results, [null]);
    });
  }
}

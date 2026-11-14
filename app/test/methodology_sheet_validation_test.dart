import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/screens/season_methodology_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Found on a physical Xiaomi 24094RAD4G (Android 16), landscape + Gboard +
/// font 1.8: days = 0 and Save kept the sheet open (correct), but the error
/// line under the field was scrolled out of the ~50 dp viewport. The user saw
/// nothing happen. These tests check that the message is inside the VISIBLE
/// area (scroll viewport, below the status bar, above the keyboard), not only
/// that it exists in the widget tree.
const _dpr = 2.8125;
const _portrait = Size(1080, 2400);
const _landscape = Size(2400, 1080);
const _keyboardPx = 698.0;
const _statusBarPx = 100.0;

const _tooSmall = 'Số ngày canh tác phải lớn hơn 0.';
const _notInteger = 'Số ngày phải là số nguyên.';
const _tooLarge =
    'Số ngày canh tác quá lớn — kiểm tra lại ngày gieo và thu hoạch.';

Size _current = _portrait;
double _keyboard = 0;

void _geometry(WidgetTester tester, Size size, {double keyboardPx = 0}) {
  _current = size;
  _keyboard = keyboardPx;
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = _dpr;
  tester.view.padding = const FakeViewPadding(top: _statusBarPx);
  tester.view.viewPadding = const FakeViewPadding(top: _statusBarPx);
  tester.view.viewInsets = FakeViewPadding(bottom: keyboardPx);
}

void _landscapeKeyboard(WidgetTester tester) =>
    _geometry(tester, _landscape, keyboardPx: _keyboardPx);

final _season = CropSeason(
  clientId: 'cs1',
  plotClientId: 'p1',
  seasonCode: 'DEMO-HT-2026',
  createdAt: DateTime(2026, 5, 18),
  updatedAt: DateTime(2026, 5, 18),
);

/// Opens the real sheet. The returned list receives what the sheet popped;
/// the caller persists only that value, so "empty" means nothing is saved.
Future<List<SeasonMethodologyValues?>> _open(WidgetTester tester,
    {double scale = 1.8, bool supportsAnnounce = false}) async {
  addTearDown(tester.view.reset);
  final results = <SeasonMethodologyValues?>[];
  await tester.pumpWidget(MaterialApp(
    theme: AgriCarbonTheme.light(),
    builder: (context, child) => MediaQuery(
        // Android reports no announce support (the phone under test).
        data: MediaQuery.of(context).copyWith(
            textScaler: TextScaler.linear(scale),
            supportsAnnounce: supportsAnnounce),
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

Finder get _daysField => find.descendant(
    of: find.byKey(const Key('methodology-days')),
    matching: find.byType(TextField));
Finder get _daysLine =>
    find.descendant(of: _daysField, matching: find.byType(EditableText));
Finder get _save => find.byKey(const Key('methodology-save'));
Finder get _summary => find.byKey(const Key('methodology-error-summary'));

String _daysText(WidgetTester tester) =>
    tester.widget<TextField>(_daysField).controller!.text;

bool _daysFocused(WidgetTester tester) =>
    tester.state<EditableTextState>(_daysLine).widget.focusNode.hasFocus;

bool _daysMarkedInvalid(WidgetTester tester) {
  final d = tester
      .widget<InputDecorator>(find.descendant(
          of: _daysField, matching: find.byType(InputDecorator)))
      .decoration;
  return d.errorText != null || d.error != null;
}

/// Screen area the user can actually see: below the status bar, above the
/// keyboard, intersected with every scroll viewport around [finder].
Rect _visibleAreaFor(WidgetTester tester, Finder finder) {
  var area = Rect.fromLTRB(0, _statusBarPx / _dpr, _current.width / _dpr,
      (_current.height - _keyboard) / _dpr);
  final scrollables =
      find.ancestor(of: finder, matching: find.byType(Scrollable));
  for (final e in scrollables.evaluate()) {
    final box = e.renderObject! as RenderBox;
    area = area.intersect(box.localToGlobal(Offset.zero) & box.size);
  }
  return area;
}

void _expectVisible(WidgetTester tester, Finder finder, {String? reason}) {
  expect(finder, findsOneWidget, reason: reason);
  final r = tester.getRect(finder);
  final area = _visibleAreaFor(tester, finder);
  final what = reason ?? finder.describeMatch(Plurality.one);
  expect(r.height, greaterThan(0), reason: '$what has no height');
  expect(r.top, greaterThanOrEqualTo(area.top - 0.5),
      reason: '$what starts above the visible area ($r vs $area)');
  expect(r.bottom, lessThanOrEqualTo(area.bottom + 0.5),
      reason: '$what ends below the visible area ($r vs $area)');
}

/// For the focused typed line, "visible when possible": in the cramped
/// landscape viewport (~52 dp) its 34 dp box may lose a couple of dp of
/// padding at the edge, so require most of it, not every pixel.
void _expectMostlyVisible(WidgetTester tester, Finder finder,
    {required String reason}) {
  expect(finder, findsOneWidget, reason: reason);
  final r = tester.getRect(finder);
  final overlap = r.intersect(_visibleAreaFor(tester, finder));
  final shown = overlap.isEmpty ? 0.0 : overlap.height / r.height;
  expect(shown, greaterThanOrEqualTo(0.9),
      reason: '$reason: only ${(shown * 100).toStringAsFixed(0)}% visible');
}

Future<void> _tapSave(WidgetTester tester) async {
  await tester.tap(_save);
  await tester.pumpAndSettle();
}

/// Types like a user: input formatters apply.
Future<void> _type(WidgetTester tester, String text) async {
  await tester.showKeyboard(_daysField);
  await tester.enterText(_daysField, text);
  await tester.pumpAndSettle();
}

void main() {
  group('landscape + keyboard + font 1.8 (cramped)', () {
    testWidgets(
        'days = 0: message visible right after Save, once, nothing saved',
        (tester) async {
      _landscapeKeyboard(tester);
      final results = await _open(tester);
      await _type(tester, '0');
      await _tapSave(tester);

      expect(find.text(_tooSmall), findsOneWidget,
          reason: 'one message, not one per place');
      _expectVisible(tester, find.text(_tooSmall),
          reason: 'validation message');
      expect(find.descendant(of: _summary, matching: find.text(_tooSmall)),
          findsOneWidget,
          reason: 'it is pinned in the action row, next to Save');
      _expectVisible(tester, _save, reason: 'Save');
      _expectVisible(tester, find.byKey(const Key('methodology-cancel')),
          reason: 'Cancel');
      expect(results, isEmpty, reason: 'invalid days are not saved');
      expect(_daysText(tester), '0', reason: 'input kept');
      expect(_daysFocused(tester), isTrue, reason: 'focus kept');
      _expectMostlyVisible(tester, _daysLine, reason: 'focused typed line');
      expect(_daysMarkedInvalid(tester), isTrue,
          reason: 'the field still shows its error state');
      expect(tester.takeException(), isNull);
    });

    testWidgets('negative days, typed: kept as typed and rejected visibly',
        (tester) async {
      _landscapeKeyboard(tester);
      final results = await _open(tester);
      await _type(tester, '-5');
      expect(_daysText(tester), '-5',
          reason: 'the old digits-only filter silently made it 5');
      await _tapSave(tester);
      expect(find.text(_tooSmall), findsOneWidget);
      _expectVisible(tester, find.text(_tooSmall), reason: 'negative message');
      expect(results, isEmpty);
    });

    for (final typed in ['1.5', '1,5', '5-']) {
      testWidgets('non-integer "$typed", typed: kept and rejected visibly',
          (tester) async {
        _landscapeKeyboard(tester);
        final results = await _open(tester);
        await _type(tester, typed);
        expect(_daysText(tester), typed,
            reason: 'the old filter made "1.5" a silent 15 days');
        await _tapSave(tester);
        expect(find.text(_notInteger), findsOneWidget);
        _expectVisible(tester, find.text(_notInteger), reason: 'not integer');
        expect(results, isEmpty);
      });
    }

    testWidgets(
        'letters are still filtered; too-large replaces the old '
        'message', (tester) async {
      _landscapeKeyboard(tester);
      final results = await _open(tester);
      await _type(tester, '9a');
      expect(_daysText(tester), '9');
      await _type(tester, '1.5');
      await _tapSave(tester);
      _expectVisible(tester, find.text(_notInteger), reason: 'not integer');

      await _type(tester, '999');
      await _tapSave(tester);
      expect(find.text(_notInteger), findsNothing,
          reason: 'the old message is replaced, not stacked');
      _expectVisible(tester, find.text(_tooLarge), reason: 'too large');
      expect(results, isEmpty);
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        'repeated Save taps: still one message, never saved, a fresh '
        'live region each time', (tester) async {
      _landscapeKeyboard(tester);
      final results = await _open(tester);
      await _type(tester, '0');
      for (var i = 1; i <= 3; i++) {
        await _tapSave(tester);
        expect(find.text(_tooSmall), findsOneWidget, reason: 'tap $i');
        expect(find.byKey(ValueKey('methodology-error-$i')), findsOneWidget,
            reason: 'tap $i re-creates the announced node');
        _expectVisible(tester, find.text(_tooSmall), reason: 'tap $i');
      }
      expect(results, isEmpty);
      expect(find.byKey(const Key('methodology-days')), findsOneWidget,
          reason: 'the sheet stays open');
    });

    testWidgets('valid days after an error: saved, no error left behind',
        (tester) async {
      _landscapeKeyboard(tester);
      final results = await _open(tester);
      await _type(tester, '0');
      await _tapSave(tester);
      expect(results, isEmpty);

      await _type(tester, '95');
      await _tapSave(tester);
      expect(results.single?.cultivationDays, 95);
      expect(find.text(_tooSmall), findsNothing);
      expect(find.byKey(const Key('methodology-days')), findsNothing,
          reason: 'sheet closed');
    });

    testWidgets(
        'accessibility (Android: no announce API): the message is '
        'one live-region node', (tester) async {
      final semantics = tester.ensureSemantics();
      _landscapeKeyboard(tester);
      await _open(tester, supportsAnnounce: false);
      await _type(tester, '0');
      await _tapSave(tester);

      expect(find.bySemanticsLabel(_tooSmall), findsOneWidget,
          reason: 'screen readers get the message once');
      SemanticsNode? n = tester.getSemantics(find.bySemanticsLabel(_tooSmall));
      var live = false;
      while (n != null && !live) {
        live = n.getSemanticsData().flagsCollection.isLiveRegion;
        n = n.parent;
      }
      expect(live, isTrue, reason: 'announced when it appears');
      semantics.dispose();
    });

    testWidgets(
        'accessibility (announce API available): every rejected Save '
        'is announced', (tester) async {
      final semantics = tester.ensureSemantics();
      final announced = <String>[];
      tester.binding.defaultBinaryMessenger
          .setMockDecodedMessageHandler<dynamic>(SystemChannels.accessibility,
              (dynamic message) async {
        final m = message as Map<Object?, Object?>;
        if (m['type'] == 'announce') {
          announced
              .add((m['data']! as Map<Object?, Object?>)['message']! as String);
        }
      });
      addTearDown(() => tester.binding.defaultBinaryMessenger
          .setMockDecodedMessageHandler<dynamic>(
              SystemChannels.accessibility, null));
      _landscapeKeyboard(tester);
      await _open(tester, supportsAnnounce: true);
      await _type(tester, '0');
      await _tapSave(tester);
      await _tapSave(tester);
      expect(announced, [_tooSmall, _tooSmall]);
      expect(find.bySemanticsLabel(_tooSmall), findsOneWidget);
      await _type(tester, '95');
      await _tapSave(tester);
      expect(announced, hasLength(2), reason: 'a valid Save says nothing');
      semantics.dispose();
    });
  });

  testWidgets('portrait: unchanged presentation, message under the field',
      (tester) async {
    _geometry(tester, _portrait);
    final results = await _open(tester, scale: 1.0);
    await tester.enterText(_daysField, '0');
    await tester.pump();
    await tester.ensureVisible(_save);
    await _tapSave(tester);

    expect(_summary, findsNothing, reason: 'no pinned row in portrait');
    expect(find.text('Thông tin phương pháp tính'), findsOneWidget);
    expect(find.text(_tooSmall), findsOneWidget);
    expect(
        find.descendant(
            of: find.byKey(const Key('methodology-days')),
            matching: find.text(_tooSmall)),
        findsOneWidget,
        reason: 'the normal field error, as before');
    _expectVisible(tester, find.text(_tooSmall), reason: 'portrait message');
    expect(results, isEmpty);
  });

  testWidgets(
      'rotation with an error and input: one visible message in each '
      'orientation; input and focus kept', (tester) async {
    _landscapeKeyboard(tester);
    final results = await _open(tester);
    await _type(tester, '0');
    await _tapSave(tester);
    _expectVisible(tester, find.text(_tooSmall), reason: 'landscape');

    _geometry(tester, _portrait, keyboardPx: _keyboardPx);
    await tester.pumpAndSettle();
    expect(_summary, findsNothing);
    expect(find.text(_tooSmall), findsOneWidget);
    _expectVisible(tester, find.text(_tooSmall), reason: 'portrait');
    expect(_daysText(tester), '0');
    expect(_daysFocused(tester), isTrue);

    _landscapeKeyboard(tester);
    await tester.pumpAndSettle();
    expect(find.text(_tooSmall), findsOneWidget);
    _expectVisible(tester, find.text(_tooSmall), reason: 'back to landscape');
    expect(_daysText(tester), '0');
    expect(_daysFocused(tester), isTrue);
    expect(results, isEmpty);
    expect(tester.takeException(), isNull);
  });
}

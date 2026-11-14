import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/screens/plot_screen.dart';
import 'package:agricarbon_app/screens/season_methodology_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// 320x568 dp (small Android phone) coverage for the components PR #79
/// touched. This is a WIDGET test with the real Be Vietnam Pro font, not a
/// device or emulator run. The keyboard is simulated as 260 dp (portrait
/// Gboard on a small phone).
const _keyboardDp = 260.0;

Future<void> _pump(WidgetTester tester, double scale, double keyboard,
    Widget Function(BuildContext) open) async {
  tester.view.physicalSize = const Size(320, 568);
  tester.view.devicePixelRatio = 1;
  tester.view.padding = const FakeViewPadding(top: 24);
  tester.view.viewPadding = const FakeViewPadding(top: 24);
  tester.view.viewInsets = FakeViewPadding(bottom: keyboard);
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: AgriCarbonTheme.light(),
    builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: TextScaler.linear(scale)),
        child: child!),
    home: Builder(builder: open),
  ));
  await tester.pumpAndSettle();
}

Widget _opener(
        BuildContext context, Future<void> Function(BuildContext) show) =>
    Scaffold(
        body: TextButton(
            onPressed: () => show(context), child: const Text('open')));

void main() {
  setUpAll(() async {
    final font = FontLoader(AppBrand.fontFamily);
    for (final face in ['Regular', 'Medium', 'SemiBold', 'Bold', 'ExtraBold']) {
      font.addFont(rootBundle.load('assets/fonts/BeVietnamPro-$face.ttf'));
    }
    await font.load();
    final icons = FontLoader('MaterialIcons');
    icons.addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });

  final season = CropSeason(
    clientId: 'cs1',
    plotClientId: 'p1',
    seasonCode: 'DEMO-HT-2026',
    createdAt: DateTime(2026, 5, 18),
    updatedAt: DateTime(2026, 5, 18),
  );

  for (final scale in [1.0, 1.8]) {
    for (final keyboard in [0.0, _keyboardDp]) {
      final tag = '320x568 text $scale keyboard ${keyboard > 0}';

      testWidgets('$tag: add-plot form', (tester) async {
        await _pump(
            tester,
            scale,
            keyboard,
            (c) => _opener(
                c,
                (ctx) => showDialog<void>(
                    context: ctx, builder: (_) => debugPlotFormDialog())));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.text('Lưu'), findsOneWidget);
        expect(tester.getRect(find.text('Lưu')).bottom,
            lessThanOrEqualTo(568 - keyboard));
      });

      testWidgets('$tag: methodology sheet', (tester) async {
        await _pump(
            tester,
            scale,
            keyboard,
            (c) => _opener(
                c, (ctx) => showSeasonMethodologySheet(ctx, season: season)));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        final save = find.byKey(const Key('methodology-save'));
        await tester.ensureVisible(save);
        await tester.pumpAndSettle();
        expect(tester.getRect(save).bottom, lessThanOrEqualTo(568 - keyboard));
        expect(tester.takeException(), isNull);
      });

      testWidgets('$tag: AppScaffold form', (tester) async {
        await _pump(
            tester,
            scale,
            keyboard,
            (_) => AppScaffold(
                  header: const AppHeader(
                      title: 'Ghi: Bón phân',
                      subtitle: 'Vụ DEMO-HT-2026',
                      showBackButton: true),
                  bottomBar:
                      PrimaryButton(label: 'Lưu công việc', onPressed: () {}),
                  body: Column(children: [
                    for (final l in ['Tên phân *', 'Lượng (kg) *', 'Đạm (%)'])
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: TextField(
                            decoration: InputDecoration(labelText: l)),
                      ),
                    const Wrap(children: [
                      StatusBadge(
                          label:
                              'Lưu ngay vào máy — gửi lên hệ thống là bước riêng',
                          tone: StatusTone.neutral),
                    ]),
                  ]),
                ));
        expect(tester.takeException(), isNull);
      });

      testWidgets('$tag: confirmation dialog', (tester) async {
        await _pump(
            tester,
            scale,
            keyboard,
            (c) => _opener(
                c,
                (ctx) => ConfirmationDialog.show(ctx,
                    title: 'Đăng xuất?',
                    message: 'Dữ liệu đã lưu trên máy vẫn được giữ. Bạn sẽ cần '
                        'đăng nhập lại để đồng bộ và xem kết quả.')));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      });
    }
  }
}

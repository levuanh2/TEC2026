import 'dart:io';
import 'dart:ui' as ui;

import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/login_screen.dart';
import 'package:agricarbon_app/shell/tabs/home_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import '../tool/ui_preview.dart';

const _capture = bool.fromEnvironment('UI_SCREENSHOTS');
const _boundary = Key('ui-refresh-capture');

Widget _host(Widget child, double scale) => RepaintBoundary(
      key: _boundary,
      child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: AgriCarbonTheme.light(),
          builder: (context, child) => MediaQuery(
                data: MediaQuery.of(context).copyWith(
                    textScaler: TextScaler.linear(scale),
                    disableAnimations: true),
                child: child!,
              ),
          home: child),
    );

Future<void> _save(WidgetTester tester, String name) async {
  if (!_capture) return;
  await tester
      .runAsync(() => Future<void>.delayed(const Duration(milliseconds: 150)));
  await tester.pumpAndSettle();
  await tester.runAsync(() async {
    final boundary =
        tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundary));
    final picture = await boundary.toImage(pixelRatio: 1);
    final data = await picture.toByteData(format: ui.ImageByteFormat.png);
    picture.dispose();
    final target = File('build/ui-refresh/$name.png');
    await target.parent.create(recursive: true);
    await target.writeAsBytes(data!.buffer.asUint8List());
  });
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    final loader = FontLoader(AppBrand.fontFamily);
    for (final face in ['Regular', 'Medium', 'SemiBold', 'Bold', 'ExtraBold']) {
      loader.addFont(rootBundle.load('assets/fonts/BeVietnamPro-$face.ttf'));
    }
    await loader.load();
    final icons = FontLoader('MaterialIcons');
    icons.addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });

  for (final size in [
    const Size(320, 568),
    const Size(390, 844),
    const Size(430, 932),
    const Size(800, 1200)
  ]) {
    for (final scale in [1.0, 1.5]) {
      testWidgets('branded login fits ${size.width} at text $scale',
          (tester) async {
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
            _host(LoginScreen(actions: PreviewAuthActions(() {})), scale));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await _save(tester, 'login-${size.width.toInt()}-$scale');
        await tester
            .ensureVisible(find.widgetWithText(ElevatedButton, 'Đăng nhập'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(
            tester
                .widget<ElevatedButton>(
                    find.widgetWithText(ElevatedButton, 'Đăng nhập'))
                .onPressed,
            isNotNull);
      });
    }
  }

  testWidgets('home branding and shortcuts keep their actions and scroll',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = PreviewHomeController();
    addTearDown(controller.dispose);
    var actions = 0;
    await tester.pumpWidget(_host(
        Scaffold(
          body: HomeTab(
              controller: controller,
              actions: PreviewHomeActions(() => actions++)),
          bottomNavigationBar:
              AppBottomNavigation(currentIndex: 0, onSelect: (_) {}),
        ),
        1));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text(AppBrand.slogan), findsOneWidget);
    await _save(tester, 'home-390');
    await tester.scrollUntilVisible(find.text('Ảnh ruộng'), 250,
        scrollable: find
            .descendant(
                of: find.byType(ListView), matching: find.byType(Scrollable))
            .first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ảnh ruộng'));
    expect(actions, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('shared controls remain usable at large text with reduced motion',
      (tester) async {
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(_host(const PreviewComponents(), 1.8));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await _save(tester, 'components-360-large-text');
    await tester.ensureVisible(find.byType(TextField));
    await tester.enterText(find.byType(TextField), 'Ghi chú xem thử');
    await tester.pumpAndSettle();
    expect(find.text('Ghi chú xem thử'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

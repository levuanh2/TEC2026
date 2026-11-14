import 'package:agricarbon_app/design/design.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// StatusBadge was a single-line Row: at 320 dp with text 1.8 a long label
/// overflowed (64 px in the resource dashboard). It must wrap when the width is
/// bounded and still size to its content inside an unbounded Row.
Widget _host(Widget child) => MaterialApp(
      theme: AgriCarbonTheme.light(),
      builder: (context, c) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: const TextScaler.linear(1.8)),
          child: c!),
      home: Scaffold(body: child),
    );

const _long =
    'Ước tính theo phương pháp tưới ngập – khô xen kẽ, độ chính xác thấp';

void main() {
  testWidgets('bounded width (Wrap in 320 dp): long label wraps, no overflow',
      (tester) async {
    tester.view.physicalSize = const Size(320, 568);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_host(const Padding(
      padding: EdgeInsets.all(24),
      child:
          Wrap(children: [StatusBadge(label: _long, tone: StatusTone.warning)]),
    )));
    expect(tester.takeException(), isNull);
    expect(
        tester.getSize(find.byType(StatusBadge)).width, lessThanOrEqualTo(272));
  });

  testWidgets('unbounded Row (list tile trailing): no flex assertion',
      (tester) async {
    await tester.pumpWidget(_host(const SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(children: [
        Text('Bón phân'),
        StatusBadge(
            label: 'Đã gửi', tone: StatusTone.positive, icon: Icons.check),
      ]),
    )));
    expect(tester.takeException(), isNull);
    expect(find.text('Đã gửi'), findsOneWidget);
  });
}

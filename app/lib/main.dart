// AgriCarbon mobile app - entrypoint.
// Lop 1a (Walking Skeleton). Nguoi A phu trach.
// Dac ta: docs/modules/01-mobile-app.md

import 'package:flutter/material.dart';

void main() => runApp(const AgriCarbonApp());

class AgriCarbonApp extends StatelessWidget {
  const AgriCarbonApp({super.key});

  @override
  Widget build(BuildContext context) {
    // TODO(1a): form nhat ky canh tac theo khung "1 phai 5 giam" (FR-1a-01..05)
    // TODO(1a): luu offline SQLite + hang doi dong bo (FR-1a-06, FR-1a-07)
    // TODO(1a): man hinh hien thi CO2e/kg tra ve tu Carbon Engine (FR-1a-10)
    return MaterialApp(
      title: 'AgriCarbon',
      home: const Scaffold(body: Center(child: Text('AgriCarbon'))),
    );
  }
}

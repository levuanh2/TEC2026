import 'package:flutter/material.dart';

import 'app_services.dart';
import 'config.dart';
import 'screens/farm_screen.dart';
import 'screens/login_screen.dart';
import 'services/auth_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AuthService.init();
  final services = await AppServices.bootstrap();
  runApp(AgriCarbonApp(services: services));
}

class AgriCarbonApp extends StatelessWidget {
  const AgriCarbonApp({super.key, required this.services});
  final AppServices services;

  @override
  Widget build(BuildContext context) {
    if (!AppConfig.isConfigured) {
      return const MaterialApp(
        home: Scaffold(
          body: Center(
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                'Thiếu cấu hình. Chạy app kèm --dart-define SUPABASE_URL, '
                'SUPABASE_PUBLISHABLE_KEY, BACKEND_BASE_URL (xem app/README.md).',
                textAlign: TextAlign.center,
              ),
            ),
          ),
        ),
      );
    }

    return MaterialApp(
      title: 'AgriCarbon',
      theme: ThemeData(colorSchemeSeed: Colors.green, useMaterial3: true),
      home: services.auth.isSignedIn
          ? FarmScreen(services: services)
          : LoginScreen(services: services),
    );
  }
}

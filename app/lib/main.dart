import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'app_services.dart';
import 'config.dart';
import 'design/design.dart';
import 'screens/bootstrap_error_screen.dart';
import 'screens/configuration_error_screen.dart';
import 'services/auth_service.dart';
import 'shell/auth_gate.dart';

/// Hook chỉ dùng cho test để quan sát lỗi async ngoài luồng. Production không set.
@visibleForTesting
void Function(Object error, StackTrace stack)? debugOnUncaughtZoneError;

/// Xử lý lỗi async không bắt được (đối số thứ hai của [runZonedGuarded]).
///
/// KHÔNG in nội dung lỗi (có thể chứa URL / key / JWT / Authorization). Chỉ để
/// lại dấu vết *loại* lỗi để còn chẩn đoán được, và tuyệt đối không để tiến
/// trình chết vì một lỗi nền.
void reportUncaughtZoneError(Object error, StackTrace stack) {
  debugPrint(
    'AgriCarbon: lỗi async ngoài luồng không bắt được (${error.runtimeType}).',
  );
  debugOnUncaughtZoneError?.call(error, stack);
}

/// App cần dựng TRƯỚC khi khởi tạo Supabase, hoặc `null` nếu cấu hình đã đủ để
/// đi tiếp. Trả về màn cấu hình khi thiếu URL/key (không init được Supabase)
/// HOẶC khi thiếu `BACKEND_BASE_URL` — thiếu backend thì `/v1/me` và
/// `/v1/carbon/*` sẽ dựng URI tương đối và hỏng âm thầm, nên phải chặn ở đây.
@visibleForTesting
Widget? preInitApp({
  required bool canInitSupabase,
  required bool isConfigured,
  required List<String> missingKeys,
}) {
  if (!canInitSupabase || !isConfigured) {
    return AgriCarbonApp.config(missingKeys: missingKeys);
  }
  return null;
}

Future<void> main() async {
  // KHÔNG có nhánh nào được phép ném ra trước `runApp` — luôn dựng một app.
  runZonedGuarded(
    () async {
      WidgetsFlutterBinding.ensureInitialized();

      final preInit = preInitApp(
        canInitSupabase: AppConfig.canInitSupabase,
        isConfigured: AppConfig.isConfigured,
        missingKeys: AppConfig.missingKeys,
      );
      if (preInit != null) {
        // Thiếu cấu hình → màn hướng dẫn, KHÔNG gọi Supabase.initialize.
        runApp(preInit);
        return;
      }

      // Khởi tạo có thể ném (URL sai định dạng, ...) → màn lỗi khởi động.
      try {
        await AuthService.init();
        final services = await AppServices.bootstrap();
        runApp(AgriCarbonApp(services: services));
      } catch (_) {
        // Không log chi tiết (có thể chứa key/URL). Chỉ hiện màn lỗi chung.
        runApp(const AgriCarbonApp.bootstrapError());
      }
    },
    reportUncaughtZoneError,
  );
}

class AgriCarbonApp extends StatelessWidget {
  const AgriCarbonApp({super.key, required this.services})
      : _missingKeys = null,
        _bootstrapFailed = false;

  const AgriCarbonApp.config({super.key, required List<String> missingKeys})
      : services = null,
        _missingKeys = missingKeys,
        _bootstrapFailed = false;

  const AgriCarbonApp.bootstrapError({super.key})
      : services = null,
        _missingKeys = null,
        _bootstrapFailed = true;

  final AppServices? services;
  final List<String>? _missingKeys;
  final bool _bootstrapFailed;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AgriCarbon',
      debugShowCheckedModeBanner: false,
      theme: AgriCarbonTheme.light(),
      locale: const Locale('vi'),
      supportedLocales: const [Locale('vi'), Locale('en')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      // Nông dân lớn tuổi hay để cỡ chữ lớn. Cho phép phóng tới 1.8 (layout đã
      // thiết kế để cuộn/không tràn ở 1.5), chặn trên để không vỡ hẳn ở 2.0+.
      builder: (context, child) => MediaQuery.withClampedTextScaling(
        maxScaleFactor: 1.8,
        child: child ?? const SizedBox.shrink(),
      ),
      home: _home(),
    );
  }

  Widget _home() {
    if (_missingKeys != null) {
      return ConfigurationErrorScreen(missingKeys: _missingKeys);
    }
    if (_bootstrapFailed) return const BootstrapErrorScreen();
    return AuthGate(services: services!);
  }
}

import 'package:agricarbon_app/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('preInitApp — guard cấu hình trước init (bug #1)', () {
    test('thiếu URL/key -> ra màn cấu hình', () {
      final app = preInitApp(
        canInitSupabase: false,
        isConfigured: false,
        missingKeys: const ['SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY'],
      );
      expect(app, isA<AgriCarbonApp>());
    });

    test('đủ URL+key nhưng THIẾU BACKEND_BASE_URL -> vẫn ra màn cấu hình', () {
      // Trước đây guard chỉ xét canInitSupabase nên app khởi động được mà
      // BACKEND_BASE_URL rỗng -> Trang chủ gọi URI tương đối, hỏng âm thầm.
      final app = preInitApp(
        canInitSupabase: true,
        isConfigured: false,
        missingKeys: const ['BACKEND_BASE_URL'],
      );
      expect(app, isA<AgriCarbonApp>());
    });

    test('đủ cả 3 biến -> null (đi tiếp khởi tạo)', () {
      final app = preInitApp(
        canInitSupabase: true,
        isConfigured: true,
        missingKeys: const [],
      );
      expect(app, isNull);
    });
  });

  group('reportUncaughtZoneError — handler runZonedGuarded (bug #2)', () {
    tearDown(() => debugOnUncaughtZoneError = null);

    test('không ném, và gọi hook quan sát với đúng lỗi', () {
      Object? seen;
      debugOnUncaughtZoneError = (error, _) => seen = error;

      final err = StateError('bí mật: token=abc');
      expect(() => reportUncaughtZoneError(err, StackTrace.current),
          returnsNormally);
      expect(seen, same(err));
    });

    test('không có hook -> vẫn chạy êm', () {
      expect(
        () => reportUncaughtZoneError(Exception('x'), StackTrace.current),
        returnsNormally,
      );
    });
  });
}

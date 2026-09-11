/// Cấu hình lấy qua --dart-define, không hardcode secret trong source.
///
/// KHÔNG có SUPABASE_SERVICE_ROLE_KEY ở đây — app chỉ dùng publishable key,
/// giống hệt web-dashboard. Service role chỉ tồn tại ở backend (docs/BACKEND_1A.md §2).
/// Auth chỉ cần SUPABASE_URL + SUPABASE_PUBLISHABLE_KEY; BACKEND_BASE_URL chỉ để
/// gọi Carbon Engine.
class AppConfig {
  static const supabaseUrl = String.fromEnvironment('SUPABASE_URL');
  static const supabasePublishableKey =
      String.fromEnvironment('SUPABASE_PUBLISHABLE_KEY');

  /// Base URL của FastAPI backend (chỉ dùng cho /v1/carbon/*), ví dụ
  /// http://10.0.2.2:8000 khi chạy backend local qua Android emulator,
  /// hoặc URL server thật khi deploy.
  static const backendBaseUrl = String.fromEnvironment('BACKEND_BASE_URL');

  /// Đủ điều kiện khởi tạo Supabase (chỉ cần URL + publishable key).
  static bool get canInitSupabase =>
      supabaseUrl.isNotEmpty && supabasePublishableKey.isNotEmpty;

  /// Đủ điều kiện chạy toàn bộ app (thêm BACKEND_BASE_URL cho Carbon).
  static bool get isConfigured => canInitSupabase && backendBaseUrl.isNotEmpty;

  /// Danh sách tên biến còn thiếu — để [ConfigurationErrorScreen] liệt kê.
  /// KHÔNG bao giờ trả giá trị, chỉ tên biến.
  static List<String> get missingKeys => [
        if (supabaseUrl.isEmpty) 'SUPABASE_URL',
        if (supabasePublishableKey.isEmpty) 'SUPABASE_PUBLISHABLE_KEY',
        if (backendBaseUrl.isEmpty) 'BACKEND_BASE_URL',
      ];

  /// Deep link để link "đặt lại mật khẩu" trong email mở LẠI app. Custom URL
  /// scheme ổn định = chính bundle id (không phải domain, không phải secret).
  /// PHẢI khớp intent-filter Android + `CFBundleURLSchemes` iOS + được thêm vào
  /// allowlist "Redirect URLs" của Supabase Auth (xem `app/README.md`).
  static const resetPasswordRedirect = 'vn.agricarbon.mobile://reset-password';
}

/// Cấu hình lấy qua --dart-define, không hardcode secret trong source.
///
/// KHÔNG có SUPABASE_SERVICE_ROLE_KEY ở đây — app chỉ dùng publishable key,
/// giống hệt web-dashboard. Service role chỉ tồn tại ở backend (docs/BACKEND_1A.md §2).
class AppConfig {
  static const supabaseUrl = String.fromEnvironment('SUPABASE_URL');
  static const supabasePublishableKey =
      String.fromEnvironment('SUPABASE_PUBLISHABLE_KEY');

  /// Base URL của FastAPI backend (chỉ dùng cho /v1/carbon/*), ví dụ
  /// http://10.0.2.2:8000 khi chạy backend local qua Android emulator,
  /// hoặc URL server thật khi deploy.
  static const backendBaseUrl = String.fromEnvironment('BACKEND_BASE_URL');

  static bool get isConfigured =>
      supabaseUrl.isNotEmpty &&
      supabasePublishableKey.isNotEmpty &&
      backendBaseUrl.isNotEmpty;
}

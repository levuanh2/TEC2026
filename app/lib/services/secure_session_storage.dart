import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart' show LocalStorage;

/// Nơi `supabase_flutter` lưu phiên (access + refresh token): bộ lưu trữ bảo
/// mật của hệ điều hành — Android Keystore (khoá RSA-OAEP bọc khoá AES-GCM) /
/// iOS Keychain — thay cho `SharedPreferences` (file XML rõ chữ) mặc định.
///
/// Mật khẩu KHÔNG bao giờ được lưu; chỉ phiên do Supabase Auth cấp. Refresh
/// token là thứ duy nhất cho phép mở lại phiên trực tuyến khi access token đã
/// hết hạn — máy chủ vẫn xác thực nó ở mỗi lần làm mới, nên nó phải được giữ
/// kín như mật khẩu.
///
/// Chuyển đổi một lần: phiên của bản cài cũ (nằm ở `SharedPreferences` dưới
/// cùng khoá) được chép sang kho bảo mật rồi XOÁ khỏi `SharedPreferences`, nên
/// nông hộ đã đăng nhập không phải đăng nhập lại sau khi cập nhật app.
class SecureSessionStorage extends LocalStorage {
  SecureSessionStorage({
    required this.persistSessionKey,
    FlutterSecureStorage? storage,
  }) : _storage = storage ?? const FlutterSecureStorage();

  /// Cùng khoá `supabase_flutter` dùng mặc định (`sb-<project>-auth-token`) —
  /// để chuyển đổi tìm đúng phiên cũ.
  final String persistSessionKey;
  final FlutterSecureStorage _storage;

  /// Khoá `supabase_flutter` 2.x dùng khi không truyền `localStorage`.
  static String defaultKeyFor(String supabaseUrl) =>
      'sb-${Uri.parse(supabaseUrl).host.split(".").first}-auth-token';

  @override
  Future<void> initialize() async {
    final prefs = await SharedPreferences.getInstance();
    final legacy = prefs.getString(persistSessionKey);
    if (legacy == null) return;
    // Phiên mới hơn (nếu đã có trong kho bảo mật) thắng; bản rõ chữ luôn bị xoá.
    if (!await _storage.containsKey(key: persistSessionKey)) {
      await _storage.write(key: persistSessionKey, value: legacy);
    }
    await prefs.remove(persistSessionKey);
  }

  @override
  Future<bool> hasAccessToken() => _storage.containsKey(key: persistSessionKey);

  @override
  Future<String?> accessToken() => _storage.read(key: persistSessionKey);

  @override
  Future<void> removePersistedSession() =>
      _storage.delete(key: persistSessionKey);

  @override
  Future<void> persistSession(String persistSessionString) =>
      _storage.write(key: persistSessionKey, value: persistSessionString);
}

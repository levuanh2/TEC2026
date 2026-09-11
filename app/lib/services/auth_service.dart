import 'package:supabase_flutter/supabase_flutter.dart';

import '../config.dart';

/// Tín hiệu vòng đời phiên đã được "làm phẳng" khỏi kiểu gotrue — [AuthController]
/// chỉ cần biết "có phiên không" và "user id nào", không phụ thuộc `Session`/`User`
/// (giúp test không phải dựng đối tượng gotrue phức tạp).
enum AuthSignalKind {
  initialSessionPresent,
  initialSessionAbsent,
  signedIn,
  signedOut,
  tokenRefreshed,
  userUpdated,
  passwordRecovery,
}

class AuthSignal {
  const AuthSignal(this.kind, this.userId);
  final AuthSignalKind kind;
  final String? userId;
}

/// Bọc Supabase Auth. App KHÔNG tự chạm vào chuỗi JWT, không lưu tay, KHÔNG log.
///
/// **Lưu phiên:** `supabase_flutter` 2.x (bản khoá ở `pubspec.lock`) mặc định
/// lưu session qua `SharedPreferences` (`SharedPreferencesGotrueAsyncStorage`),
/// KHÔNG phải `flutter_secure_storage` (đó là mặc định của `supabase_flutter`
/// 1.x). Trên Android đây là file XML riêng của app trong sandbox; trên iOS là
/// `NSUserDefaults`. Việc nâng lên lưu trữ được mã hoá (Keychain / Keystore) là
/// một quyết định gia cố bảo mật, cần chèn `localStorage` tuỳ biến vào
/// `Supabase.initialize(authOptions:)` và kiểm thử trên thiết bị — xem
/// `app/README.md` mục "Blocker / quyết định ngoài code".
///
/// KHÔNG có SUPABASE_SERVICE_ROLE_KEY trong app — chỉ publishable key
/// (AppConfig.supabasePublishableKey). RLS vẫn là ranh giới quyền thật, giống
/// hệt web-dashboard/src/utils/supabase.ts.
class AuthService {
  /// Chỉ gọi khi [AppConfig.canInitSupabase] = true (URL + key không rỗng).
  static Future<void> init() => Supabase.initialize(
        url: AppConfig.supabaseUrl,
        publishableKey: AppConfig.supabasePublishableKey,
      );

  SupabaseClient get client => Supabase.instance.client;

  Session? get currentSession => client.auth.currentSession;
  bool get isSignedIn => currentSession != null;

  /// Id người dùng hiện tại (không phải thông tin nhạy cảm — chỉ UUID).
  String? get currentUserId => currentSession?.user.id;

  /// JWT của phiên hiện tại — dùng cho header `Authorization` khi gọi FastAPI.
  /// KHÔNG log giá trị này.
  String? get accessToken => currentSession?.accessToken;

  /// Stream tín hiệu phiên đã làm phẳng. Bọc `onAuthStateChange` của gotrue.
  Stream<AuthSignal> get signals =>
      client.auth.onAuthStateChange.map(_toSignal);

  static AuthSignal _toSignal(AuthState state) {
    final uid = state.session?.user.id;
    switch (state.event) {
      case AuthChangeEvent.initialSession:
        return AuthSignal(
          state.session != null
              ? AuthSignalKind.initialSessionPresent
              : AuthSignalKind.initialSessionAbsent,
          uid,
        );
      case AuthChangeEvent.signedIn:
        return AuthSignal(AuthSignalKind.signedIn, uid);
      case AuthChangeEvent.signedOut:
        return const AuthSignal(AuthSignalKind.signedOut, null);
      case AuthChangeEvent.tokenRefreshed:
        return AuthSignal(AuthSignalKind.tokenRefreshed, uid);
      case AuthChangeEvent.passwordRecovery:
        return AuthSignal(AuthSignalKind.passwordRecovery, uid);
      default:
        // userUpdated / mfaChallengeVerified / mọi sự kiện khác: không đổi phase,
        // chỉ cập nhật user id nếu có.
        return AuthSignal(AuthSignalKind.userUpdated, uid);
    }
  }

  Future<void> signIn({required String email, required String password}) async {
    await client.auth.signInWithPassword(email: email, password: password);
  }

  /// Flow reset mật khẩu chuẩn của Supabase — gửi email chứa link đặt lại.
  /// Supabase cố tình KHÔNG báo lỗi khi email không tồn tại (chống dò tài khoản),
  /// nên UI luôn hiện thông báo trung tính.
  ///
  /// `redirectTo` = [AppConfig.resetPasswordRedirect] (custom URL scheme). Khi
  /// người dùng mở link, deep-link observer của `supabase_flutter` bắt URI, đổi
  /// `code` lấy phiên và phát `AuthChangeEvent.passwordRecovery` → app hiện màn
  /// đặt mật khẩu mới. URL này PHẢI được quản trị viên thêm vào Supabase Auth →
  /// Redirect URLs (bước thủ công, xem `app/README.md`).
  Future<void> sendPasswordReset(String email) =>
      client.auth.resetPasswordForEmail(
        email,
        redirectTo: AppConfig.resetPasswordRedirect,
      );

  /// Đặt mật khẩu mới cho phiên hiện tại. Chỉ gọi được khi ĐÃ có phiên hợp lệ —
  /// hoặc người dùng đang đăng nhập, hoặc phiên `passwordRecovery` do link trong
  /// email tạo ra. KHÔNG log giá trị mật khẩu.
  Future<void> updatePassword(String newPassword) =>
      client.auth.updateUser(UserAttributes(password: newPassword));

  Future<void> signOut() => client.auth.signOut();
}

import 'dart:async';
import 'dart:io' show SocketException;

import 'package:http/http.dart' show ClientException;
import 'package:supabase_flutter/supabase_flutter.dart';

import '../config.dart';
import 'secure_session_storage.dart';

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

  /// Làm mới phiên hỏng vì KHÔNG tới được máy chủ (mất mạng, máy chủ tạm lỗi).
  /// Phiên trên máy vẫn còn, người dùng vẫn làm việc offline được — đây KHÔNG
  /// phải hết phiên, cũng không phải lỗi khiến phải đăng nhập lại.
  refreshDeferred,
}

/// Kết quả kiểm tra phiên ngay trước khi gửi dữ liệu lên máy chủ.
enum SessionFreshness {
  /// Access token còn hạn (hoặc vừa làm mới thành công) — được gửi.
  fresh,

  /// Hết hạn và chưa làm mới được vì không tới được máy chủ — KHÔNG gửi gì,
  /// giữ nguyên hàng đợi, thử lại khi có mạng.
  offline,

  /// Máy chủ từ chối làm mới (refresh token bị thu hồi, tài khoản bị khoá...)
  /// hoặc không có phiên — KHÔNG gửi gì, giữ nguyên hàng đợi, phải đăng nhập lại.
  rejected,
}

/// Lỗi làm mới phiên do mạng/máy chủ tạm thời (thử lại sau được), phân biệt với
/// lỗi máy chủ TỪ CHỐI phiên (phải đăng nhập lại).
bool isNetworkAuthError(Object error) =>
    error is AuthRetryableFetchException ||
    error is SocketException ||
    error is TimeoutException ||
    error is ClientException;

/// Quyết định có được gửi dữ liệu hay không, theo phiên hiện tại. Còn hạn →
/// gửi luôn; hết hạn → làm mới trước (máy chủ xác thực refresh token), chỉ
/// được gửi khi làm mới thành công.
Future<SessionFreshness> checkSessionFreshness({
  required bool hasSession,
  required bool isExpired,
  required Future<bool> Function() refresh,
}) async {
  if (!hasSession) return SessionFreshness.rejected;
  if (!isExpired) return SessionFreshness.fresh;
  try {
    return await refresh() ? SessionFreshness.fresh : SessionFreshness.rejected;
  } catch (e) {
    return isNetworkAuthError(e)
        ? SessionFreshness.offline
        : SessionFreshness.rejected;
  }
}

class AuthSignal {
  const AuthSignal(this.kind, this.userId);
  final AuthSignalKind kind;
  final String? userId;
}

/// Bọc Supabase Auth. App KHÔNG tự chạm vào chuỗi JWT, không lưu tay, KHÔNG log.
///
/// **Lưu phiên:** [SecureSessionStorage] — Android Keystore / iOS Keychain,
/// không phải `SharedPreferences` rõ chữ (mặc định của `supabase_flutter` 2.x).
/// Phiên của bản cài cũ được chuyển sang một lần rồi xoá bản rõ chữ.
///
/// **Offline với access token đã hết hạn:** phiên vẫn được khôi phục từ máy, nên
/// nông hộ vẫn mở được dữ liệu và hàng đợi. Việc làm mới hỏng vì mất mạng thành
/// tín hiệu [AuthSignalKind.refreshDeferred], không phải lỗi. Trước khi gửi dữ
/// liệu, [ensureFreshSession] bắt buộc làm mới thành công.
///
/// KHÔNG có SUPABASE_SERVICE_ROLE_KEY trong app — chỉ publishable key
/// (AppConfig.supabasePublishableKey). RLS vẫn là ranh giới quyền thật, giống
/// hệt web-dashboard/src/utils/supabase.ts.
class AuthService {
  /// Chỉ gọi khi [AppConfig.canInitSupabase] = true (URL + key không rỗng).
  static Future<void> init() => Supabase.initialize(
        url: AppConfig.supabaseUrl,
        publishableKey: AppConfig.supabasePublishableKey,
        authOptions: FlutterAuthClientOptions(
          localStorage: SecureSessionStorage(
            persistSessionKey:
                SecureSessionStorage.defaultKeyFor(AppConfig.supabaseUrl),
          ),
        ),
      );

  SupabaseClient get client => Supabase.instance.client;

  Session? get currentSession => client.auth.currentSession;
  bool get isSignedIn => currentSession != null;

  /// Id người dùng hiện tại (không phải thông tin nhạy cảm — chỉ UUID).
  String? get currentUserId => currentSession?.user.id;

  /// JWT của phiên hiện tại — dùng cho header `Authorization` khi gọi FastAPI.
  /// KHÔNG log giá trị này.
  String? get accessToken => currentSession?.accessToken;

  /// Access token đã hết hạn và chưa làm mới được (vd. đang offline). Dữ liệu
  /// trên máy vẫn dùng được; chỉ việc gửi lên máy chủ phải chờ làm mới.
  bool get onlineSessionExpired => currentSession?.isExpired ?? false;

  /// Gọi ngay trước khi gửi dữ liệu. Hết hạn → làm mới (máy chủ xác thực
  /// refresh token). Máy chủ từ chối → gotrue tự phát `signedOut`, app về màn
  /// đăng nhập, hàng đợi vẫn nằm nguyên trên máy.
  Future<SessionFreshness> ensureFreshSession() {
    final session = currentSession;
    return checkSessionFreshness(
      hasSession: session != null,
      isExpired: session?.isExpired ?? false,
      refresh: () async =>
          (await client.auth.refreshSession()).session != null,
    );
  }

  /// Stream tín hiệu phiên đã làm phẳng. Bọc `onAuthStateChange` của gotrue.
  /// Làm mới hỏng vì mạng (gotrue đẩy thành LỖI trên stream) được đổi thành
  /// tín hiệu [AuthSignalKind.refreshDeferred]; lỗi khác vẫn là lỗi.
  Stream<AuthSignal> get signals => client.auth.onAuthStateChange
      .map(_toSignal)
      .transform(StreamTransformer.fromHandlers(
        handleError: (error, stack, sink) {
          if (isNetworkAuthError(error)) {
            sink.add(AuthSignal(AuthSignalKind.refreshDeferred, currentUserId));
          } else {
            sink.addError(error, stack);
          }
        },
      ));

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

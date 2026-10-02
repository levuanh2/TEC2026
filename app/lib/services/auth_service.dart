import 'dart:async';
import 'dart:io' show SocketException;

import 'package:http/http.dart' as http show BaseClient, BaseRequest, Client, StreamedResponse;
import 'package:http/http.dart' show ClientException;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../config.dart';
import 'password_change_api.dart';
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

/// Mọi request Supabase (Auth, PostgREST) có giới hạn thời gian chờ phản hồi.
///
/// Round 5.1, điện thoại thật: vừa bật lại mạng, request làm mới phiên gửi đi
/// lúc mạng còn đang chuyển treo mãi không có phản hồi; gotrue gộp mọi lần làm
/// mới cùng refresh token vào đúng request đó, nên cổng phiên trước khi đồng bộ
/// chờ vô hạn — không gửi, nhưng cũng không bao giờ báo "đăng nhập lại". Có
/// giới hạn, request treo thành lỗi mạng, gotrue bỏ nó và lần sau thử lại.
class TimeoutHttpClient extends http.BaseClient {
  TimeoutHttpClient(this._inner, {this.timeout = const Duration(seconds: 20)});
  final http.Client _inner;
  final Duration timeout;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) =>
      _inner.send(request).timeout(timeout);

  @override
  void close() => _inner.close();
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
        httpClient: TimeoutHttpClient(http.Client()),
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

  /// Tài khoản HTX vừa cấp còn dùng mật khẩu tạm (`app_metadata` của Supabase
  /// Auth — chỉ máy chủ đặt và xoá; app chỉ đọc). Trong lúc này máy chủ từ chối
  /// mọi đọc/ghi nghiệp vụ, nên app chỉ cho đổi mật khẩu hoặc đăng xuất.
  bool get mustChangePassword =>
      currentSession?.user.appMetadata['must_change_password'] == true;

  /// Đổi mật khẩu tạm qua FastAPI (máy chủ kiểm mật khẩu tạm, đặt mật khẩu mới
  /// và xoá cờ), rồi làm mới phiên để token mới không còn cờ.
  Future<void> replaceTemporaryPassword({
    required String current,
    required String next,
  }) async {
    await PasswordChangeApi(() => accessToken).replace(current: current, next: next);
    await client.auth.refreshSession();
  }

  /// Access token đã hết hạn và chưa làm mới được (vd. đang offline). Dữ liệu
  /// trên máy vẫn dùng được; chỉ việc gửi lên máy chủ phải chờ làm mới.
  bool get onlineSessionExpired => currentSession?.isExpired ?? false;

  /// Gọi ngay trước khi gửi dữ liệu. Hết hạn → làm mới (máy chủ xác thực
  /// refresh token). Máy chủ từ chối → gotrue tự phát `signedOut`, app về màn
  /// đăng nhập, hàng đợi vẫn nằm nguyên trên máy.
  Future<SessionFreshness> ensureFreshSession() {
    // Còn mật khẩu tạm: máy chủ từ chối mọi bản ghi (RLS) — không gửi gì, hàng
    // đợi giữ nguyên tới khi đổi xong mật khẩu.
    if (mustChangePassword) return Future.value(SessionFreshness.offline);
    final session = currentSession;
    return checkSessionFreshness(
      hasSession: session != null,
      isExpired: session?.isExpired ?? false,
      // Giới hạn tổng: một lần làm mới (kể cả các lần gotrue tự thử lại) không
      // bao giờ giữ hàng đợi quá lâu — hết giờ = chưa tới được máy chủ.
      refresh: () async => (await client.auth
                  .refreshSession()
                  .timeout(const Duration(seconds: 30)))
              .session !=
          null,
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

  static const _kEndedByServer = 'auth.session_ended_by_server';

  /// Máy chủ đã kết thúc phiên (thu hồi / khoá tài khoản), không phải người
  /// dùng bấm đăng xuất. Lưu một cờ (không nhạy cảm) để lần mở app sau vẫn nói
  /// rõ "phiên đã hết hạn — dữ liệu chưa gửi vẫn giữ", chứ không chỉ hiện màn
  /// đăng nhập trống. Lỗi lưu trữ bị bỏ qua: đây chỉ là lời nhắc.
  Future<void> rememberSessionEndedByServer(bool ended) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      ended ? await prefs.setBool(_kEndedByServer, true) : await prefs.remove(_kEndedByServer);
    } catch (_) {}
  }

  Future<bool> sessionEndedByServer() async {
    try {
      return (await SharedPreferences.getInstance()).getBool(_kEndedByServer) ?? false;
    } catch (_) {
      return false;
    }
  }
}

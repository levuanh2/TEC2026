import 'dart:async';

import 'package:flutter/foundation.dart';

import '../services/auth_actions.dart';
import '../services/auth_service.dart';

/// Trạng thái vòng đời phiên đăng nhập.
enum AuthPhase {
  /// Chưa bắt đầu nghe (trước [AuthController.start]).
  initializing,

  /// Đang khôi phục phiên + mở vùng dữ liệu của user.
  restoringSession,

  /// Không có phiên — hoặc chưa từng đăng nhập, hoặc vừa đăng xuất chủ động.
  signedOut,

  /// Có phiên hợp lệ và DB của user đã mở.
  authenticated,

  /// Mất phiên KHÔNG do người dùng bấm đăng xuất (token hết hạn, bị thu hồi).
  sessionExpired,

  /// Lỗi ở tầng stream auth — hiếm; cho phép thử lại.
  error,
}

/// Máy trạng thái đăng nhập. Nghe [AuthService.signals]. Khi có user hoạt động
/// → [_onUserActive] (mở đúng DB user, dọn cache RAM). Khi mất user (đăng xuất /
/// hết phiên) → [_onUserInactive] (đóng DB, dọn RAM — KHÔNG xoá file).
///
/// KHÔNG log password / JWT / key ở bất kỳ nhánh nào.
class AuthController extends ChangeNotifier implements AuthActions {
  AuthController(
    this._auth, {
    Future<void> Function(String userId)? onUserActive,
    Future<void> Function()? onUserInactive,
    Future<void> Function()? onTemporaryPasswordReplaced,
  })  : _onUserActive = onUserActive,
        _onUserInactive = onUserInactive,
        _onTemporaryPasswordReplaced = onTemporaryPasswordReplaced;

  final AuthService _auth;
  final Future<void> Function(String userId)? _onUserActive;
  final Future<void> Function()? _onUserInactive;
  final Future<void> Function()? _onTemporaryPasswordReplaced;

  StreamSubscription<AuthSignal>? _sub;
  AuthPhase _phase = AuthPhase.initializing;
  String? _currentUserId;
  bool _userRequestedSignOut = false;
  bool _disposed = false;
  bool _passwordRecovery = false;

  /// Đang trong luồng đặt lại mật khẩu (link `passwordRecovery` từ email vừa mở
  /// phiên). [AuthGate] hiện màn đặt mật khẩu mới thay cho shell.
  bool get isPasswordRecovery => _passwordRecovery;

  // Xử lý tín hiệu tuần tự — tránh mở/đóng DB chồng lên nhau khi tín hiệu tới
  // dồn dập (đổi tài khoản nhanh).
  Future<void> _queue = Future<void>.value();

  AuthPhase get phase => _phase;
  bool get isAuthenticated => _phase == AuthPhase.authenticated;

  /// Đã đăng nhập nhưng còn mật khẩu tạm HTX cấp: [AuthGate] chỉ hiện màn đổi
  /// mật khẩu (cờ do máy chủ giữ; máy chủ cũng từ chối mọi dữ liệu nghiệp vụ).
  bool get mustChangePassword =>
      _phase == AuthPhase.authenticated && _auth.mustChangePassword;

  /// Đổi mật khẩu tạm. Ném [PasswordChangeException] để màn hiển thị lý do của
  /// máy chủ. Thành công → phiên đã làm mới (cờ đã xoá) → chạy phần đăng nhập
  /// bị hoãn (tải Trang chủ, tự gửi) rồi vào shell.
  Future<void> replaceTemporaryPassword(String current, String next) async {
    await _auth.replaceTemporaryPassword(current: current, next: next);
    await _onTemporaryPasswordReplaced?.call();
    if (!_disposed) notifyListeners();
  }

  /// Đang trong phiên nhưng access token đã hết hạn và chưa làm mới được (vd.
  /// mở app khi offline sau hơn 1 giờ). Vẫn xem/ghi dữ liệu trên máy được; chỉ
  /// việc gửi lên máy chủ phải chờ làm mới thành công.
  bool get onlineSessionExpired =>
      _phase == AuthPhase.authenticated && _auth.onlineSessionExpired;
  bool _lastOnlineSessionExpired = false;

  /// Bắt đầu nghe. Gọi một lần sau khi Supabase đã init.
  void start() {
    if (_sub != null) return;
    _setPhase(AuthPhase.restoringSession);
    _sub = _auth.signals.listen(_enqueue, onError: _onStreamError);
    // Phiên đã được `Supabase.initialize` khôi phục xong trước khi tới đây.
    final restored = _auth.currentUserId;
    if (restored != null) {
      _enqueue(AuthSignal(AuthSignalKind.initialSessionPresent, restored));
    } else {
      _setPhase(AuthPhase.signedOut);
      _queue = _queue.then((_) async {
        final next = await _noSessionPhase();
        if (_phase == AuthPhase.signedOut) _setPhase(next); // never overrides a newer phase
      });
    }
  }

  void _enqueue(AuthSignal signal) {
    _queue = _queue.then((_) => _handle(signal)).catchError((Object _) {
      // `_handle` đã tự đưa các lỗi nghiêm trọng của nó về `AuthPhase.error`.
      // Đây là lưới cuối cho lỗi bất ngờ: chỉ cứu trường hợp kẹt ở splash khi
      // CHƯA vào được phiên — không đá người dùng ra khỏi phiên đang chạy.
      if (_phase == AuthPhase.initializing ||
          _phase == AuthPhase.restoringSession) {
        _setPhase(AuthPhase.error);
      }
    });
  }

  Future<void> _handle(AuthSignal signal) async {
    switch (signal.kind) {
      case AuthSignalKind.initialSessionPresent:
      case AuthSignalKind.signedIn:
        final uid = signal.userId;
        if (uid == null) break;
        // Tín hiệu phiên-ban-đầu có thể tới 2 lần (một lần do `start()` đọc phiên
        // đã khôi phục, một lần do stream `onAuthStateChange` phát lại
        // `initialSession`). Nếu đã kích hoạt đúng user này rồi thì bỏ qua —
        // tránh mở lại DB / tải lại Trang chủ lần hai.
        if (uid == _currentUserId && _phase == AuthPhase.authenticated) break;
        if (await _switchTo(uid)) {
          _setPhase(AuthPhase.authenticated);
          unawaited(_auth.rememberSessionEndedByServer(false));
        }
      case AuthSignalKind.initialSessionAbsent:
        await _tearDownCurrentUser();
        _setPhase(await _noSessionPhase());
      case AuthSignalKind.passwordRecovery:
        // Link đặt lại mật khẩu trong email vừa mở một phiên. Chạy đủ vòng đời
        // đổi tài khoản nếu là user khác, rồi bật cờ để [AuthGate] hiện màn đặt
        // mật khẩu mới thay vì vào Home như một lần đăng nhập bình thường.
        final recoveryUid = signal.userId;
        if (recoveryUid != null && recoveryUid != _currentUserId) {
          if (!await _switchTo(recoveryUid)) break;
        }
        _passwordRecovery = true;
        _setPhase(AuthPhase.authenticated);
        if (!_disposed) notifyListeners();
      case AuthSignalKind.tokenRefreshed:
      case AuthSignalKind.userUpdated:
        final refreshUid = signal.userId;
        if (refreshUid == null) break;
        if (refreshUid == _currentUserId) {
          // Cùng user, DB đã mở — KHÔNG mở lại vùng dữ liệu.
          _setPhase(AuthPhase.authenticated);
          _notifyIfSessionStateChanged();
          break;
        }
        // Khác user → phải chạy đủ vòng đời đổi tài khoản (dọn A trước khi mở B).
        if (await _switchTo(refreshUid)) _setPhase(AuthPhase.authenticated);
      case AuthSignalKind.refreshDeferred:
        // Không tới được máy chủ để làm mới: phiên và dữ liệu trên máy vẫn còn.
        // KHÔNG đóng DB, KHÔNG về Login — chỉ cập nhật thông báo "hết phiên
        // trực tuyến". Hết phiên thật (máy chủ từ chối) tới dưới dạng
        // `signedOut`.
        _notifyIfSessionStateChanged();
      case AuthSignalKind.signedOut:
        final hadUser = _currentUserId != null;
        // Đăng xuất phải về Login NGAY — cleanup lỗi cũng không chặn (lần đăng
        // nhập kế tiếp `onUserActive` sẽ `db.openForUser` = đóng handle rò rồi
        // mở lại đúng vùng của user mới).
        await _tearDownCurrentUser();
        if (_userRequestedSignOut) {
          _userRequestedSignOut = false;
          unawaited(_auth.rememberSessionEndedByServer(false));
          _setPhase(AuthPhase.signedOut);
        } else {
          if (hadUser) unawaited(_auth.rememberSessionEndedByServer(true));
          _setPhase(hadUser ? AuthPhase.sessionExpired : AuthPhase.signedOut);
        }
    }
  }

  /// No session at start: `sessionExpired` when the server ended the last one
  /// (revoked / banned) in an earlier run — so the login screen says why and
  /// that unsent records are kept — otherwise `signedOut`.
  Future<AuthPhase> _noSessionPhase() async =>
      await _auth.sessionEndedByServer() ? AuthPhase.sessionExpired : AuthPhase.signedOut;

  /// Chuyển vùng hoạt động sang [newUserId]. Trả `true` nếu an toàn để vào shell.
  ///
  /// Trình tự BẮT BUỘC khi đang có user cũ khác: `restoringSession` → dọn HẲN
  /// user cũ (đóng DB, detach ActiveContext, clear cache RAM SyncService, reset
  /// DeviceService, reset Home) → CHỈ KHI dọn xong mới mở DB + kích hoạt user
  /// mới. `_currentUserId` KHÔNG được đặt bằng id mới trước khi `onUserActive`
  /// hoàn tất. Cleanup user cũ thất bại HOẶC kích hoạt user mới thất bại →
  /// [AuthPhase.error]; không giữ `_currentUserId` sai; không để màn hình còn
  /// truy cập DB của user cũ.
  Future<bool> _switchTo(String newUserId) async {
    _setPhase(AuthPhase.restoringSession);

    if (_currentUserId != null && _currentUserId != newUserId) {
      try {
        await _tearDownCurrentUser(rethrowOnFailure: true);
      } catch (_) {
        _setPhase(AuthPhase.error);
        return false;
      }
    }
    if (_currentUserId == newUserId) return true; // đã kích hoạt sẵn

    try {
      await _onUserActive?.call(newUserId);
    } catch (_) {
      // Kích hoạt user mới hỏng → gỡ lại (best-effort) rồi báo lỗi.
      try {
        await _onUserInactive?.call();
      } catch (_) {}
      _currentUserId = null;
      _setPhase(AuthPhase.error);
      return false;
    }
    _currentUserId = newUserId; // chỉ đặt SAU khi onUserActive thành công
    return true;
  }

  /// Dọn user hiện tại. [rethrowOnFailure] = true (đường đổi tài khoản) thì ném
  /// lại lỗi cleanup để caller biết vùng dữ liệu CHƯA chắc đã đóng an toàn;
  /// false (đăng xuất / hết phiên) thì nuốt lỗi để vẫn về Login được ngay.
  Future<void> _tearDownCurrentUser({bool rethrowOnFailure = false}) async {
    _currentUserId = null;
    _passwordRecovery = false;
    try {
      await _onUserInactive?.call();
    } catch (_) {
      if (rethrowOnFailure) rethrow;
      // best-effort — không log nội dung lỗi (có thể chứa dữ liệu nhạy cảm).
    }
  }

  void _onStreamError(Object error, StackTrace stackTrace) {
    // Không log nội dung lỗi (có thể chứa dữ liệu nhạy cảm).
    // Đang trong phiên: một lỗi của stream (vd. lần làm mới nền hỏng) không lấy
    // đi dữ liệu trên máy của người dùng — phiên chỉ kết thúc khi có `signedOut`.
    if (_phase == AuthPhase.authenticated && _currentUserId != null) {
      _notifyIfSessionStateChanged();
      return;
    }
    _setPhase(AuthPhase.error);
  }

  void _notifyIfSessionStateChanged() {
    final now = onlineSessionExpired;
    if (now == _lastOnlineSessionExpired || _disposed) return;
    _lastOnlineSessionExpired = now;
    notifyListeners();
  }

  @override
  Future<void> signIn({
    required String email,
    required String password,
  }) async {
    // Không bắt lỗi ở đây — để màn đăng nhập dịch qua `authErrorMessage`.
    await _auth.signIn(email: email, password: password);
  }

  @override
  Future<void> sendPasswordReset(String email) =>
      _auth.sendPasswordReset(email);

  /// Đặt mật khẩu mới (dùng ở màn đặt lại sau khi mở link trong email). Ném lỗi
  /// để màn dịch qua `authErrorMessage`.
  Future<void> updatePassword(String newPassword) =>
      _auth.updatePassword(newPassword);

  /// Kết thúc luồng đặt lại mật khẩu → quay về shell bình thường.
  void completePasswordRecovery() {
    if (!_passwordRecovery || _disposed) return;
    _passwordRecovery = false;
    notifyListeners();
  }

  /// Đăng xuất chủ động — đánh dấu để tín hiệu `signedOut` kế tiếp KHÔNG bị hiểu
  /// nhầm là "hết phiên".
  Future<void> signOut() async {
    _userRequestedSignOut = true;
    try {
      await _auth.signOut();
    } catch (_) {
      _userRequestedSignOut = false;
      rethrow;
    }
  }

  /// Nghe lại sau khi ở phase [AuthPhase.error].
  void retry() {
    if (_phase != AuthPhase.error) return;
    _sub?.cancel();
    _sub = null;
    start();
  }

  void _setPhase(AuthPhase next) {
    if (_disposed || _phase == next) return;
    _phase = next;
    _lastOnlineSessionExpired = onlineSessionExpired;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _sub?.cancel();
    _sub = null;
    super.dispose();
  }
}

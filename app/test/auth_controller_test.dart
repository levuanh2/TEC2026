// Máy trạng thái đăng nhập — không cần Supabase thật (fake AuthService).

import 'dart:async';

import 'package:agricarbon_app/services/auth_service.dart';
import 'package:agricarbon_app/shell/auth_controller.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supabase_flutter/supabase_flutter.dart' show AuthException;

class _FakeAuthService extends AuthService {
  _FakeAuthService({String? initialUserId}) : _userId = initialUserId;

  // Broadcast: giống `onAuthStateChange` thật (cho phép nghe lại sau retry).
  final StreamController<AuthSignal> _controller =
      StreamController<AuthSignal>.broadcast();
  String? _userId;

  Object? signInError;
  int signInCalls = 0;
  int signOutCalls = 0;
  int updatePasswordCalls = 0;
  String? lastNewPassword;

  bool get hasListener => _controller.hasListener;

  void emit(AuthSignal signal) => _controller.add(signal);
  void emitError(Object e) => _controller.addError(e);

  @override
  Stream<AuthSignal> get signals => _controller.stream;

  @override
  String? get currentUserId => _userId;

  @override
  Future<void> signIn({required String email, required String password}) async {
    signInCalls++;
    final error = signInError;
    if (error != null) throw error;
    _userId = 'user-signed-in';
  }

  @override
  Future<void> signOut() async {
    signOutCalls++;
  }

  @override
  Future<void> sendPasswordReset(String email) async {}

  @override
  Future<void> updatePassword(String newPassword) async {
    updatePasswordCalls++;
    lastNewPassword = newPassword;
  }
}

/// Bộ đếm + nhật ký thứ tự cho onUserActive / onUserInactive.
class _Scope {
  final activeFor = <String>[];
  int inactiveCalls = 0;

  /// Nhật ký theo THỨ TỰ: `'inactive'` / `'active:<uid>'`.
  final log = <String>[];

  bool inactiveShouldThrow = false;
  final activeShouldThrowFor = <String>{};

  Future<void> active(String userId) async {
    if (activeShouldThrowFor.contains(userId)) {
      throw StateError('onUserActive hỏng cho $userId');
    }
    activeFor.add(userId);
    log.add('active:$userId');
  }

  Future<void> inactive() async {
    inactiveCalls++;
    log.add('inactive');
    if (inactiveShouldThrow) throw StateError('cleanup hỏng');
  }
}

AuthController _make(_FakeAuthService auth, [_Scope? scope]) => AuthController(
      auth,
      onUserActive: scope?.active,
      onUserInactive: scope?.inactive,
    );

void main() {
  test('start(): không có phiên -> signedOut (đồng bộ)', () {
    final c = _make(_FakeAuthService())..start();
    expect(c.phase, AuthPhase.signedOut);
    c.dispose();
  });

  test('start(): khôi phục phiên từ storage -> authenticated + onUserActive',
      () async {
    final scope = _Scope();
    final c = _make(_FakeAuthService(initialUserId: 'u1'), scope)..start();
    await pumpEventQueue();
    expect(c.phase, AuthPhase.authenticated);
    expect(scope.activeFor, ['u1']);
    c.dispose();
  });

  test('đăng nhập thành công -> signedIn -> authenticated', () async {
    final auth = _FakeAuthService();
    final scope = _Scope();
    final c = _make(auth, scope)..start();

    await c.signIn(email: 'a@b.com', password: 'x');
    expect(auth.signInCalls, 1);

    auth.emit(const AuthSignal(AuthSignalKind.signedIn, 'u1'));
    await pumpEventQueue();
    expect(c.phase, AuthPhase.authenticated);
    expect(scope.activeFor, ['u1']);
    c.dispose();
  });

  test('đăng nhập thất bại -> ném lỗi, phase vẫn signedOut', () async {
    final auth = _FakeAuthService()
      ..signInError = const AuthException('bad', code: 'invalid_credentials');
    final c = _make(auth)..start();

    await expectLater(
      c.signIn(email: 'a@b.com', password: 'x'),
      throwsA(isA<AuthException>()),
    );
    expect(c.phase, AuthPhase.signedOut);
    c.dispose();
  });

  test('mất phiên KHÔNG do người dùng -> sessionExpired + onUserInactive',
      () async {
    final auth = _FakeAuthService(initialUserId: 'u1');
    final scope = _Scope();
    final c = _make(auth, scope)..start();
    await pumpEventQueue();

    auth.emit(const AuthSignal(AuthSignalKind.signedOut, null));
    await pumpEventQueue();

    expect(c.phase, AuthPhase.sessionExpired);
    expect(scope.inactiveCalls, 1);
    c.dispose();
  });

  test('đăng xuất chủ động -> signedOut (KHÔNG phải sessionExpired)', () async {
    final auth = _FakeAuthService(initialUserId: 'u1');
    final scope = _Scope();
    final c = _make(auth, scope)..start();
    await pumpEventQueue();

    await c.signOut();
    expect(auth.signOutCalls, 1);

    auth.emit(const AuthSignal(AuthSignalKind.signedOut, null));
    await pumpEventQueue();

    expect(c.phase, AuthPhase.signedOut);
    expect(scope.inactiveCalls, 1);
    c.dispose();
  });

  test('đổi tài khoản A->B (signedIn) -> dọn A TRƯỚC khi kích hoạt B',
      () async {
    final auth = _FakeAuthService(initialUserId: 'A');
    final scope = _Scope();
    final c = _make(auth, scope)..start();
    await pumpEventQueue();
    expect(scope.log, ['active:A']);

    auth.emit(const AuthSignal(AuthSignalKind.signedIn, 'B'));
    await pumpEventQueue();

    expect(c.phase, AuthPhase.authenticated);
    // Thứ tự BẮT BUỘC: inactive (dọn A) đứng TRƯỚC active:B.
    expect(scope.log, ['active:A', 'inactive', 'active:B']);
    expect(scope.inactiveCalls, 1);
    c.dispose();
  });

  test('đổi tài khoản qua tokenRefreshed (khác user) -> full lifecycle',
      () async {
    final auth = _FakeAuthService(initialUserId: 'A');
    final scope = _Scope();
    final c = _make(auth, scope)..start();
    await pumpEventQueue();

    auth.emit(const AuthSignal(AuthSignalKind.tokenRefreshed, 'B'));
    await pumpEventQueue();

    expect(scope.log, ['active:A', 'inactive', 'active:B']);
    expect(c.phase, AuthPhase.authenticated);
    c.dispose();
  });

  test('tokenRefreshed cùng user -> KHÔNG mở lại vùng dữ liệu', () async {
    final auth = _FakeAuthService(initialUserId: 'u1');
    final scope = _Scope();
    final c = _make(auth, scope)..start();
    await pumpEventQueue();

    auth.emit(const AuthSignal(AuthSignalKind.tokenRefreshed, 'u1'));
    await pumpEventQueue();

    expect(scope.log, ['active:u1']); // KHÔNG inactive/active lần nữa
    expect(c.phase, AuthPhase.authenticated);
    c.dispose();
  });

  test('đổi tài khoản: kích hoạt B thất bại -> phase error, KHÔNG vào shell',
      () async {
    final auth = _FakeAuthService(initialUserId: 'A');
    final scope = _Scope()..activeShouldThrowFor.add('B');
    final c = _make(auth, scope)..start();
    await pumpEventQueue();

    auth.emit(const AuthSignal(AuthSignalKind.signedIn, 'B'));
    await pumpEventQueue();

    expect(c.phase, AuthPhase.error);
    expect(c.isAuthenticated, isFalse);
    // A đã bị dọn, rồi rollback (inactive lần 2) khi B hỏng.
    expect(scope.log.first, 'active:A');
    expect(scope.log.contains('active:B'), isFalse);
    c.dispose();
  });

  test('đổi tài khoản: dọn A thất bại -> KHÔNG kích hoạt B, phase error',
      () async {
    final auth = _FakeAuthService(initialUserId: 'A');
    final scope = _Scope()..inactiveShouldThrow = true;
    final c = _make(auth, scope)..start();
    await pumpEventQueue();

    auth.emit(const AuthSignal(AuthSignalKind.signedIn, 'B'));
    await pumpEventQueue();

    expect(c.phase, AuthPhase.error);
    expect(scope.activeFor, ['A']); // B KHÔNG được kích hoạt
    c.dispose();
  });

  test('đăng xuất: cleanup lỗi vẫn về Login ngay', () async {
    final auth = _FakeAuthService(initialUserId: 'A');
    final scope = _Scope()..inactiveShouldThrow = true;
    final c = _make(auth, scope)..start();
    await pumpEventQueue();

    await c.signOut();
    auth.emit(const AuthSignal(AuthSignalKind.signedOut, null));
    await pumpEventQueue();

    expect(c.phase, AuthPhase.signedOut); // KHÔNG kẹt ở error
    c.dispose();
  });

  test('lỗi stream -> phase error; retry() nghe lại', () async {
    final auth = _FakeAuthService();
    final c = _make(auth)..start();

    auth.emitError(Exception('boom'));
    await pumpEventQueue();
    expect(c.phase, AuthPhase.error);

    c.retry();
    expect(c.phase, AuthPhase.signedOut); // start() lại, không có phiên
    c.dispose();
  });

  test(
      'mở vùng dữ liệu user thất bại -> phase error, KHÔNG authenticated '
      '(bug #3)', () async {
    final auth = _FakeAuthService(initialUserId: 'u1');
    final c = AuthController(
      auth,
      onUserActive: (_) async => throw StateError('DB không mở được'),
    )..start();
    await pumpEventQueue();

    expect(c.phase, AuthPhase.error);
    expect(c.isAuthenticated, isFalse);
    c.dispose();
  });

  test(
      'tín hiệu phiên-ban-đầu tới lần 2 -> onUserActive vẫn chỉ 1 lần (bug #5)',
      () async {
    final auth = _FakeAuthService(initialUserId: 'u1');
    final scope = _Scope();
    final c = _make(auth, scope)..start();
    await pumpEventQueue();
    expect(c.phase, AuthPhase.authenticated);
    expect(scope.activeFor, ['u1']);

    // gotrue thật phát lại `initialSession` cho listener mới -> tới đây thành
    // AuthSignal thứ hai cho cùng user.
    auth.emit(const AuthSignal(AuthSignalKind.initialSessionPresent, 'u1'));
    auth.emit(const AuthSignal(AuthSignalKind.signedIn, 'u1'));
    await pumpEventQueue();

    expect(scope.activeFor, ['u1']); // không mở lại vùng dữ liệu
    expect(c.phase, AuthPhase.authenticated);
    c.dispose();
  });

  test(
      'passwordRecovery -> isPasswordRecovery = true; đổi mật khẩu rồi kết thúc '
      '(bug #10)', () async {
    final auth = _FakeAuthService(initialUserId: 'u1');
    final c = _make(auth)..start();
    await pumpEventQueue();

    auth.emit(const AuthSignal(AuthSignalKind.passwordRecovery, 'u1'));
    await pumpEventQueue();
    expect(c.phase, AuthPhase.authenticated);
    expect(c.isPasswordRecovery, isTrue);

    await c.updatePassword('mat-khau-moi-123');
    expect(auth.updatePasswordCalls, 1);
    expect(auth.lastNewPassword, 'mat-khau-moi-123');

    c.completePasswordRecovery();
    expect(c.isPasswordRecovery, isFalse);
    c.dispose();
  });

  test('dispose(): huỷ subscription auth, không phản ứng tín hiệu sau đó',
      () async {
    final auth = _FakeAuthService(initialUserId: 'u1');
    final c = _make(auth)..start();
    await pumpEventQueue();
    expect(auth.hasListener, isTrue);
    expect(c.phase, AuthPhase.authenticated);

    c.dispose();
    expect(auth.hasListener, isFalse);

    auth.emit(const AuthSignal(AuthSignalKind.signedOut, null));
    await pumpEventQueue();
    expect(c.phase, AuthPhase.authenticated); // không đổi sau dispose
  });
}

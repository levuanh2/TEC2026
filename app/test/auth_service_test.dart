// AuthService (Core V1 closure 3B): đọc cờ mật khẩu tạm, đổi mật khẩu tạm rồi
// đăng nhập lại bằng mật khẩu MỚI, và hàng đợi không gửi gì khi còn cờ.
// Phiên là đối tượng Session thật của gotrue; chỉ nguồn phiên và lệnh đăng
// nhập được thay để không cần Supabase.initialize.

import 'dart:convert';

import 'package:agricarbon_app/config.dart';
import 'package:agricarbon_app/services/auth_service.dart';
import 'package:agricarbon_app/services/password_change_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:async';

import 'package:supabase_flutter/supabase_flutter.dart'
    show AuthChangeEvent, AuthClientOptions, AuthFlowType, AuthRetryableFetchException, AuthState, Session, SupabaseClient, User;

String _jwt(int expSecondsFromNow) {
  String part(Map<String, dynamic> m) => base64Url.encode(utf8.encode(jsonEncode(m))).replaceAll('=', '');
  final exp = DateTime.now().millisecondsSinceEpoch ~/ 1000 + expSecondsFromNow;
  return '${part({'alg': 'HS256', 'typ': 'JWT'})}.${part({'sub': 'u1', 'exp': exp})}.sig';
}

Session _session({Map<String, dynamic> app = const {}, String? email = 'f@x.vn', int expiresIn = 3600, String? token}) => Session(
      accessToken: token ?? 'jwt-temp',
      tokenType: 'bearer',
      expiresIn: expiresIn,
      user: User(
        id: 'u1',
        appMetadata: app,
        userMetadata: const {'must_change_password': true}, // client-writable: must be ignored
        aud: 'authenticated',
        createdAt: '2026-10-01T00:00:00Z',
        email: email,
      ),
    );

class _Auth extends AuthService {
  _Auth(this.session, http.Client api)
      : super(passwordChangeApi: (token) => PasswordChangeApi(token, httpClient: api));
  Session? session;
  final states = StreamController<AuthState>.broadcast();

  @override
  Stream<AuthState> get authStateChanges => states.stream;
  final signIns = <List<String>>[];
  Object? signInError;

  @override
  Session? get currentSession => session;
  @override
  Future<void> signIn({required String email, required String password}) async {
    signIns.add([email, password]);
    if (signInError != null) throw signInError!;
  }
}

http.Response _ok() => http.Response('{"must_change_password": false}', 200);

void main() {
  _signalTests();
  group('mustChangePassword', () {
    test('only the server-set app_metadata flag counts', () {
      final ok = MockClient((_) async => _ok());
      expect(_Auth(_session(app: {'must_change_password': true}), ok).mustChangePassword, isTrue);
      expect(_Auth(_session(), ok).mustChangePassword, isFalse); // user_metadata says true: ignored
      expect(_Auth(_session(app: {'must_change_password': 'true'}), ok).mustChangePassword, isFalse);
      expect(_Auth(null, ok).mustChangePassword, isFalse);
    });
  });

  group('replaceTemporaryPassword', () {
    test('posts with the session token once, then signs in with the NEW password', () async {
      final requests = <http.Request>[];
      final auth = _Auth(_session(app: {'must_change_password': true}), MockClient((r) async {
        requests.add(r);
        return _ok();
      }));
      await auth.replaceTemporaryPassword(current: 'Temp-1', next: 'Mine-2026');
      expect(requests, hasLength(1));
      expect(requests.single.headers['Authorization'], 'Bearer jwt-temp');
      expect(jsonDecode(requests.single.body), {'current_password': 'Temp-1', 'new_password': 'Mine-2026'});
      expect(auth.signIns, [
        ['f@x.vn', 'Mine-2026']
      ]);
    });

    test('a refused change carries the server reason and signs in to nothing', () async {
      final auth = _Auth(
          _session(app: {'must_change_password': true}),
          MockClient((_) async => http.Response.bytes(
              utf8.encode('{"detail":{"error":{"code":"current_password_incorrect","message":"Mật khẩu tạm không đúng."}}}'),
              422)));
      await expectLater(
          auth.replaceTemporaryPassword(current: 'Wrong', next: 'Mine-2026'),
          throwsA(isA<PasswordChangeException>()
              .having((e) => e.code, 'code', 'current_password_incorrect')
              .having((e) => e.message, 'message', 'Mật khẩu tạm không đúng.')));
      expect(auth.signIns, isEmpty);
    });

    test('changed but the sign-in fails: says the password WAS changed, never "not changed"', () async {
      final auth = _Auth(_session(app: {'must_change_password': true}), MockClient((_) async => _ok()))
        ..signInError = Exception('network down');
      await expectLater(
          auth.replaceTemporaryPassword(current: 'Temp-1', next: 'Mine-2026'),
          throwsA(isA<PasswordChangeException>()
              .having((e) => e.code, 'code', 'password_changed_sign_in_again')
              .having((e) => e.message, 'message', 'Đã đổi mật khẩu. Vui lòng đăng nhập lại bằng mật khẩu mới.')));
    });

    test('changed, but the session has no email to sign in with: the same "changed" message', () async {
      final auth = _Auth(_session(app: {'must_change_password': true}, email: null), MockClient((_) async => _ok()));
      await expectLater(auth.replaceTemporaryPassword(current: 'Temp-1', next: 'Mine-2026'),
          throwsA(isA<PasswordChangeException>().having((e) => e.code, 'code', 'password_changed_sign_in_again')));
      expect(auth.signIns, isEmpty);
    });
  });

  group('ensureFreshSession', () {
    test('still on the temporary password: nothing is sent, nothing refreshed', () async {
      final auth = _Auth(_session(app: {'must_change_password': true}), MockClient((_) async => _ok()));
      expect(await auth.ensureFreshSession(), SessionFreshness.offline);
    });

    test('an expired session whose refresh the server cannot honour: nothing is sent, sign in again', () async {
      final requests = <http.BaseRequest>[];
      final auth = _ClientAuth(
          _session(expiresIn: -60, token: _jwt(-60)),
          SupabaseClient('http://127.0.0.1:9', 'publishable',
              httpClient: MockClient((r) async {
                requests.add(r);
                return http.Response('{"error":"invalid_grant"}', 400);
              }),
              authOptions: const AuthClientOptions(autoRefreshToken: false)));
      expect(auth.onlineSessionExpired, isTrue);
      expect(await auth.ensureFreshSession(), SessionFreshness.rejected);
    });

    test('a valid normal session is sent as is, without a refresh', () async {
      final auth = _Auth(_session(), MockClient((_) async => _ok()));
      expect(auth.onlineSessionExpired, isFalse);
      expect(await auth.ensureFreshSession(), SessionFreshness.fresh);
    });
  });

  test('password reset asks Supabase Auth for the recovery mail with the app deep link', () async {
    final requests = <http.Request>[];
    final auth = _ClientAuth(
        _session(),
        SupabaseClient('http://127.0.0.1:9', 'publishable',
            httpClient: MockClient((r) async {
              requests.add(r);
              return http.Response('{}', 200);
            }),
            // Implicit flow: this test checks the request, not PKCE storage.
            authOptions: const AuthClientOptions(autoRefreshToken: false, authFlowType: AuthFlowType.implicit)));
    await auth.sendPasswordReset('f@x.vn');
    final recover = requests.singleWhere((r) => r.url.path.endsWith('/auth/v1/recover'));
    expect(jsonDecode(recover.body)['email'], 'f@x.vn');
    expect(recover.url.queryParameters['redirect_to'] ?? jsonDecode(recover.body)['redirect_to'],
        AppConfig.resetPasswordRedirect);
  });

  test('TimeoutHttpClient closes the client it wraps', () {
    var closed = false;
    final inner = _Closing(() => closed = true);
    TimeoutHttpClient(inner).close();
    expect(closed, isTrue);
  });

  test('the "ended by the server" reminder survives a restart and can be cleared', () async {
    SharedPreferences.setMockInitialValues({});
    final auth = _Auth(null, MockClient((_) async => _ok()));
    await auth.rememberSessionEndedByServer(true);
    expect(await auth.sessionEndedByServer(), isTrue);
    await auth.rememberSessionEndedByServer(false);
    expect(await auth.sessionEndedByServer(), isFalse);
  });
}

void _signalTests() {
  group('signals', () {
    test('a refresh that fails on the network is "deferred", never a sign-out', () async {
      final auth = _Auth(_session(), MockClient((_) async => _ok()));
      final got = <AuthSignalKind>[];
      final errors = <Object>[];
      final sub = auth.signals.listen((s) => got.add(s.kind), onError: errors.add);
      auth.states.addError(AuthRetryableFetchException(message: 'network'));
      auth.states.addError(TimeoutException('refresh'));
      await Future<void>.delayed(Duration.zero);
      expect(got, [AuthSignalKind.refreshDeferred, AuthSignalKind.refreshDeferred]);
      expect(errors, isEmpty);
      await sub.cancel();
    });

    test('any other auth error stays an error; a real sign-out stays a sign-out', () async {
      final auth = _Auth(_session(), MockClient((_) async => _ok()));
      final got = <AuthSignalKind>[];
      final errors = <Object>[];
      final sub = auth.signals.listen((s) => got.add(s.kind), onError: errors.add);
      auth.states.addError(StateError('corrupt session'));
      auth.states.add(AuthState(AuthChangeEvent.signedOut, null));
      await Future<void>.delayed(Duration.zero);
      expect(errors.single, isA<StateError>());
      expect(got, [AuthSignalKind.signedOut]);
      await sub.cancel();
    });
  });
}

class _ClientAuth extends _Auth {
  _ClientAuth(Session session, this._client) : super(session, MockClient((_) async => _ok()));
  final SupabaseClient _client;
  @override
  SupabaseClient get client => _client;
}

class _Closing extends http.BaseClient {
  _Closing(this.onClose);
  final void Function() onClose;
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) => throw UnimplementedError();
  @override
  void close() => onClose();
}

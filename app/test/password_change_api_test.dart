// POST /v1/me/password from the app: no request without a session, a hung
// server becomes "offline" (never an endless spinner), and nothing sensitive
// reaches logs through toString.

import 'dart:async';

import 'package:agricarbon_app/services/password_change_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('a server that never answers is reported as offline after the timeout', () async {
    final hung = MockClient.streaming((_, __) => Completer<http.StreamedResponse>().future);
    final api = PasswordChangeApi(() => 'jwt', httpClient: hung, timeout: const Duration(milliseconds: 30));
    await expectLater(
        api.replace(current: 'Temp-1', next: 'Mine-2026'),
        throwsA(isA<PasswordChangeException>()
            .having((e) => e.code, 'code', 'offline')
            .having((e) => e.statusCode, 'statusCode', 0)));
  });

  test('no session: refused locally, before any request (default client is never used)', () async {
    await expectLater(PasswordChangeApi(() => null).replace(current: 'a', next: 'b'),
        throwsA(isA<PasswordChangeException>().having((e) => e.code, 'code', 'unauthenticated')));
  });

  test('toString names status and code only -- never the message, a password or a token', () {
    final e = PasswordChangeException(422, 'password_too_weak', 'Mật khẩu Mine-2026 quá yếu');
    expect(e.toString(), 'PasswordChangeException(422/password_too_weak)');
  });
}

import 'package:agricarbon_app/services/auth_errors.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supabase_flutter/supabase_flutter.dart'
    show AuthException, AuthRetryableFetchException;

void main() {
  group('authErrorMessage', () {
    test('sai thông tin đăng nhập -> thông báo tiếng Việt, không lộ mã lỗi',
        () {
      final msg = authErrorMessage(
        const AuthException('Invalid login credentials',
            code: 'invalid_credentials'),
      );
      expect(msg, 'Email hoặc mật khẩu không đúng.');
      expect(msg.toLowerCase(), isNot(contains('invalid')));
    });

    test('email chưa xác nhận', () {
      final msg = authErrorMessage(
        const AuthException('x', code: 'email_not_confirmed'),
      );
      expect(msg, contains('xác nhận'));
    });

    test('rate limit', () {
      final msg = authErrorMessage(
          const AuthException('x', code: 'over_request_rate_limit'));
      expect(msg, contains('quá nhanh'));
    });

    test('AuthRetryableFetchException -> báo mất mạng', () {
      final msg = authErrorMessage(AuthRetryableFetchException(message: 'x'));
      expect(msg, contains('kết nối mạng'));
    });

    test('SocketException chung -> báo mất mạng', () {
      final msg =
          authErrorMessage(Exception('SocketException: Failed host lookup'));
      expect(msg, contains('kết nối mạng'));
    });

    test('lỗi lạ -> thông báo chung, không kèm chuỗi exception', () {
      final msg = authErrorMessage(Exception('weird internal detail 12345'));
      expect(msg, 'Có lỗi xảy ra. Vui lòng thử lại.');
      expect(msg, isNot(contains('12345')));
    });
  });

  group('isValidEmail', () {
    test('hợp lệ', () {
      expect(isValidEmail('nong.dan@htx-cantho.vn'), isTrue);
      expect(isValidEmail('  a@b.co  '), isTrue);
    });
    test('không hợp lệ', () {
      for (final bad in ['', 'abc', 'a@b', 'a@@b.com', '@b.com', 'a b@c.com']) {
        expect(isValidEmail(bad), isFalse, reason: bad);
      }
    });
  });

  group('field errors', () {
    test('email rỗng / sai định dạng', () {
      expect(emailFieldError(''), contains('nhập email'));
      expect(emailFieldError('abc'), contains('định dạng'));
      expect(emailFieldError('a@b.com'), isNull);
    });
    test('mật khẩu rỗng', () {
      expect(passwordFieldError(''), contains('nhập mật khẩu'));
      expect(passwordFieldError('x'), isNull);
    });
  });
}

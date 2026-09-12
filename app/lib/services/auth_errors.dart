import 'package:supabase_flutter/supabase_flutter.dart';

/// Dịch lỗi đăng nhập / đặt lại mật khẩu sang tiếng Việt cho nông dân.
/// KHÔNG bao giờ ghép chuỗi exception gốc, mã lỗi thô, JWT hay key vào kết quả.
String authErrorMessage(Object error) {
  if (error is AuthException) {
    if (error is AuthRetryableFetchException) {
      return 'Không có kết nối mạng. Kiểm tra kết nối rồi thử lại.';
    }
    switch (error.code) {
      case 'invalid_credentials':
      case 'invalid_grant':
        return 'Email hoặc mật khẩu không đúng.';
      case 'email_not_confirmed':
        return 'Email chưa được xác nhận. Vui lòng kiểm tra hộp thư để xác nhận '
            'tài khoản.';
      case 'user_banned':
        return 'Tài khoản đang bị khoá. Vui lòng liên hệ quản lý HTX.';
      case 'over_request_rate_limit':
      case 'over_email_send_rate_limit':
        return 'Bạn thao tác quá nhanh. Vui lòng thử lại sau vài phút.';
      case 'validation_failed':
        return 'Thông tin đăng nhập chưa hợp lệ. Vui lòng kiểm tra lại.';
      default:
        return 'Không đăng nhập được. Vui lòng thử lại.';
    }
  }

  final text = error.toString().toLowerCase();
  if (text.contains('socketexception') ||
      text.contains('failed host lookup') ||
      text.contains('clientexception') ||
      text.contains('connection closed') ||
      text.contains('connection refused') ||
      text.contains('network is unreachable') ||
      text.contains('timed out')) {
    return 'Không có kết nối mạng. Kiểm tra kết nối rồi thử lại.';
  }
  return 'Có lỗi xảy ra. Vui lòng thử lại.';
}

final RegExp _emailPattern = RegExp(
  r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$",
);

bool isValidEmail(String value) => _emailPattern.hasMatch(value.trim());

/// Trả về thông báo lỗi email (tiếng Việt) hoặc `null` nếu hợp lệ.
String? emailFieldError(String value) {
  final trimmed = value.trim();
  if (trimmed.isEmpty) return 'Vui lòng nhập email.';
  if (!isValidEmail(trimmed)) return 'Email chưa đúng định dạng.';
  return null;
}

/// Trả về thông báo lỗi mật khẩu hoặc `null` nếu hợp lệ (chỉ kiểm tra "bắt buộc"
/// — không áp policy độ mạnh ở màn đăng nhập).
String? passwordFieldError(String value) {
  if (value.isEmpty) return 'Vui lòng nhập mật khẩu.';
  return null;
}

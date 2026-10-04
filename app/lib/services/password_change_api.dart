import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';

/// Lỗi từ `POST /v1/me/password` — `message` là câu tiếng Việt máy chủ trả về
/// (hợp đồng lỗi thống nhất), hiển thị thẳng cho nông hộ.
class PasswordChangeException implements Exception {
  PasswordChangeException(this.statusCode, this.code, this.message);
  final int statusCode;
  final String code;
  final String message;

  @override
  String toString() => 'PasswordChangeException($statusCode/$code)';
}

/// Đổi mật khẩu tạm do HTX cấp (đăng nhập lần đầu bắt buộc).
///
/// Máy chủ kiểm mật khẩu tạm với Supabase Auth, rồi đặt mật khẩu mới VÀ xoá cờ
/// `must_change_password` trong cùng một lần — app không bao giờ tự xoá cờ.
/// KHÔNG log mật khẩu hay JWT.
class PasswordChangeApi {
  PasswordChangeApi(this._token, {http.Client? httpClient, Duration? timeout})
      : _http = httpClient ?? http.Client(),
        _timeout = timeout ?? const Duration(seconds: 20);

  final String? Function() _token;
  final http.Client _http;
  final Duration _timeout;

  Future<void> replace({required String current, required String next}) async {
    final token = _token();
    if (token == null) {
      throw PasswordChangeException(401, 'unauthenticated', 'Phiên đăng nhập đã hết. Vui lòng đăng nhập lại.');
    }
    final http.Response response;
    try {
      response = await _http
          .post(
            Uri.parse('${AppConfig.backendBaseUrl}/v1/me/password'),
            headers: {
              'Authorization': 'Bearer $token',
              'Content-Type': 'application/json',
              'Accept': 'application/json',
            },
            body: jsonEncode({'current_password': current, 'new_password': next}),
          )
          .timeout(_timeout);
    } on TimeoutException {
      throw PasswordChangeException(0, 'offline', 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.');
    } on http.ClientException {
      throw PasswordChangeException(0, 'offline', 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.');
    }
    if (response.statusCode == 200) return;
    String code = 'request_failed';
    String message = 'Chưa đổi được mật khẩu. Vui lòng thử lại.';
    try {
      final error = (jsonDecode(utf8.decode(response.bodyBytes)) as Map)['detail']['error'] as Map;
      code = error['code'] as String? ?? code;
      message = error['message'] as String? ?? message;
    } catch (_) {}
    throw PasswordChangeException(response.statusCode, code, message);
  }
}

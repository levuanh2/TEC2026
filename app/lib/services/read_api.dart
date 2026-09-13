import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';

/// Lỗi từ các endpoint ĐỌC của FastAPI (`GET /v1/*`). Giữ mã lỗi để caller rẽ
/// nhánh (đặc biệt 401 → `unauthorized`).
class ReadApiException implements Exception {
  ReadApiException(this.statusCode, this.code, this.message);
  final int statusCode;
  final String code;
  final String message;

  bool get isUnauthorized => statusCode == 401 || statusCode == 403;

  @override
  String toString() => 'ReadApiException($statusCode/$code)';
}

/// Client mỏng cho các route đọc: gắn Bearer JWT, giải mã UTF-8 (FastAPI trả
/// `application/json` không kèm charset → `http` mặc định Latin-1 làm hỏng dấu),
/// và đọc error contract nested `detail.error.code`.
class ReadApi {
  ReadApi(this._tokenProvider, {http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  final String? Function() _tokenProvider;
  final http.Client _http;

  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, String>? query,
  }) async {
    final token = _tokenProvider();
    if (token == null) {
      throw ReadApiException(401, 'unauthenticated', 'Chưa đăng nhập.');
    }
    final uri = Uri.parse('${AppConfig.backendBaseUrl}$path')
        .replace(queryParameters: query);
    final response = await _http.get(uri, headers: {
      'Authorization': 'Bearer $token',
      'Accept': 'application/json',
    });

    final body = response.bodyBytes.isEmpty
        ? const <String, dynamic>{}
        : _asMap(jsonDecode(utf8.decode(response.bodyBytes)));

    if (response.statusCode >= 200 && response.statusCode < 300) return body;

    final detail = body['detail'];
    String code = 'unknown_error';
    String message = 'Lỗi không xác định (${response.statusCode}).';
    if (detail is Map) {
      final error = detail['error'];
      if (error is Map) {
        code = (error['code'] as String?) ?? code;
        message = (error['message'] as String?) ?? message;
      } else if (error is String) {
        code = error;
        message = (detail['message'] as String?) ?? message;
      }
    }
    throw ReadApiException(response.statusCode, code, message);
  }

  static Map<String, dynamic> _asMap(Object? decoded) =>
      decoded is Map<String, dynamic> ? decoded : const {};
}

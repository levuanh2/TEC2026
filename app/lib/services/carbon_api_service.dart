import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/carbon_readiness.dart';
import '../models/carbon_result.dart';
import 'auth_service.dart';

/// Kịch bản nước — khớp đúng `enum` trong `backend/api.py` / openapi
/// `CalculateRequest.water_regime_scenario`. KHÔNG tự đổi tên.
const kScenarioAsRecorded = 'as_recorded';
const kScenarioAwd = 'awd';
const kScenarioContinuousFlooding = 'continuous_flooding';

/// 3 enum CHÍNH THỨC — fallback khi `GET /v1/carbon/scenarios` lỗi/không tới.
const kOfficialScenarios = <String>[
  kScenarioAsRecorded,
  kScenarioAwd,
  kScenarioContinuousFlooding,
];

/// Lỗi có cấu trúc từ Carbon API. `errorCode` là mã backend
/// (`detail.error.code`), `message` đã là tiếng Việt của backend (không phải
/// stack trace). `requestId` chỉ có ở `internal_error` (500).
class CarbonApiException implements Exception {
  CarbonApiException(this.statusCode, this.errorCode, this.message,
      {this.requestId});
  final int statusCode;
  final String errorCode;
  final String message;
  final String? requestId;

  bool get isUnauthorized => statusCode == 401 || statusCode == 403;

  @override
  String toString() =>
      'CarbonApiException($statusCode/$errorCode${requestId != null ? ' req=$requestId' : ''})';
}

/// Client cho Carbon Engine (FastAPI). **KHÔNG tính carbon trong app** — chỉ gửi
/// request + đọc đúng response. `http.Client` bơm qua constructor để test.
class CarbonApiService {
  CarbonApiService(
    AuthService auth, {
    http.Client? httpClient,
    Duration? timeout,
  })  : _tokenProvider = (() => auth.accessToken),
        _http = httpClient ?? http.Client(),
        _timeout = timeout ?? const Duration(seconds: 20);

  /// Chỉ test — bơm token giả, không cần `Supabase.instance`.
  CarbonApiService.withTokenProvider(
    this._tokenProvider, {
    http.Client? httpClient,
    Duration? timeout,
  })  : _http = httpClient ?? http.Client(),
        _timeout = timeout ?? const Duration(seconds: 20);

  final String? Function() _tokenProvider;
  final http.Client _http;
  final Duration _timeout;

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('${AppConfig.backendBaseUrl}$path')
          .replace(queryParameters: query);

  Map<String, String> _authHeaders() {
    final token = _tokenProvider();
    if (token == null) {
      throw CarbonApiException(401, 'missing_authorization', 'Chưa đăng nhập.');
    }
    return {
      'Authorization': 'Bearer $token',
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };
  }

  // --- Carbon ---------------------------------------------------------

  Future<CarbonResult> calculate({
    required String cropSeasonId,
    String scenario = kScenarioAsRecorded,
  }) async {
    final response = await _http
        .post(
          _uri('/v1/carbon/calculate'),
          headers: _authHeaders(),
          body: jsonEncode({
            'crop_season_id': cropSeasonId,
            'water_regime_scenario': scenario,
          }),
        )
        .timeout(_timeout);
    return _parseOrThrow(response).copyWith(fetchedAt: DateTime.now());
  }

  /// Bản tính THÀNH CÔNG gần nhất. `null` = vụ hợp lệ nhưng CHƯA từng tính
  /// (`no_calculation`) — KHÔNG phải lỗi. `crop_not_found` (RLS / không tồn tại)
  /// vẫn NÉM — hai loại 404 khác hẳn nhau.
  Future<CarbonResult?> latest({
    required String cropSeasonId,
    String? scenario,
  }) async {
    final response = await _http
        .get(
          _uri('/v1/crop-seasons/$cropSeasonId/carbon',
              scenario == null ? null : {'scenario': scenario}),
          headers: _authHeaders(),
        )
        .timeout(_timeout);

    if (response.statusCode == 404) {
      final err = _errorFrom(_decodeBody(response), 404);
      if (err.code == 'no_calculation') return null;
    }
    return _parseOrThrow(response).copyWith(fetchedAt: DateTime.now());
  }

  /// `GET /v1/crop-seasons/{id}/carbon/readiness` — đầu vào Carbon còn thiếu và
  /// chỗ bổ sung từng thứ. Nguồn sự thật duy nhất: app KHÔNG tự suy luật thiếu.
  Future<CarbonReadiness> readiness({required String cropSeasonId}) async {
    final response = await _http
        .get(
          _uri('/v1/crop-seasons/$cropSeasonId/carbon/readiness'),
          headers: _authHeaders(),
        )
        .timeout(_timeout);
    final body = _decodeBody(response);
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return CarbonReadiness.fromJson(body);
    }
    final err = _errorFrom(body, response.statusCode);
    throw CarbonApiException(response.statusCode, err.code, err.message,
        requestId: err.requestId);
  }

  /// `GET /v1/carbon/scenarios` — không cần auth. Lỗi bất kỳ → 3 enum chính thức.
  Future<List<String>> scenarios() async {
    try {
      final response = await _http.get(_uri('/v1/carbon/scenarios'),
          headers: const {'Accept': 'application/json'}).timeout(_timeout);
      if (response.statusCode ~/ 100 != 2) return kOfficialScenarios;
      final body = _decodeBody(response);
      final list = body['scenarios'];
      if (list is! List || list.isEmpty) return kOfficialScenarios;
      final out = [
        for (final s in list)
          if (s is String && kOfficialScenarios.contains(s)) s,
      ];
      return out.isEmpty ? kOfficialScenarios : out;
    } catch (_) {
      return kOfficialScenarios;
    }
  }

  /// `GET /health` — không cần auth. Lỗi → `null` (màn tự xử lý "chưa biết").
  Future<CarbonHealth?> health() async {
    try {
      final response = await _http.get(_uri('/health'),
          headers: const {'Accept': 'application/json'}).timeout(_timeout);
      if (response.statusCode ~/ 100 != 2) return null;
      return CarbonHealth.fromJson(_decodeBody(response));
    } catch (_) {
      return null;
    }
  }

  // --- Parsing ------------------------------------------------------

  CarbonResult _parseOrThrow(http.Response response) {
    final body = _decodeBody(response);
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return CarbonResult.fromJson(body);
    }
    final err = _errorFrom(body, response.statusCode);
    throw CarbonApiException(
      response.statusCode,
      err.code,
      err.message,
      requestId: err.requestId,
    );
  }

  /// Giải mã body bằng UTF-8 (đọc bytes trực tiếp — FastAPI trả
  /// `application/json` KHÔNG kèm charset → `http` mặc định Latin-1 làm hỏng
  /// dấu). Body rỗng / KHÔNG phải JSON / KHÔNG phải object → `{}` (không ném).
  Map<String, dynamic> _decodeBody(http.Response response) {
    if (response.bodyBytes.isEmpty) return const {};
    try {
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      return decoded is Map<String, dynamic> ? decoded : const {};
    } catch (_) {
      return const {};
    }
  }

  /// Đọc `detail.error.{code,message,request_id}` (shape hiện tại — mọi route).
  /// Có nhánh cho: `detail.error` là string (shape cũ), `detail` là list
  /// (`HTTPValidationError` của FastAPI khi body sai kiểu), `detail` là string.
  ({String code, String message, String? requestId}) _errorFrom(
    Map<String, dynamic> body,
    int status,
  ) {
    final fallback = _fallbackForStatus(status);
    final detail = body['detail'];

    if (detail is Map) {
      final error = detail['error'];
      if (error is Map) {
        return (
          code: (error['code'] as String?) ?? fallback.code,
          message: (error['message'] as String?) ?? fallback.message,
          requestId: error['request_id'] as String?,
        );
      }
      if (error is String && error.isNotEmpty) {
        return (
          code: error,
          message: (detail['message'] as String?) ?? fallback.message,
          requestId: detail['request_id'] as String?,
        );
      }
    }

    // FastAPI 422 mặc định: detail = [ {loc, msg, type}, ... ].
    if (detail is List && detail.isNotEmpty) {
      final first = detail.first;
      final msg = first is Map ? first['msg']?.toString() : null;
      return (
        code: 'validation_error',
        message: msg ?? 'Dữ liệu gửi lên chưa hợp lệ.',
        requestId: null,
      );
    }
    if (detail is String && detail.isNotEmpty) {
      return (code: fallback.code, message: detail, requestId: null);
    }
    return (
      code: fallback.code,
      message: fallback.message,
      requestId: null,
    );
  }

  ({String code, String message}) _fallbackForStatus(int status) {
    switch (status) {
      case 401:
        return (
          code: 'unauthenticated',
          message: 'Phiên đăng nhập đã hết hạn.'
        );
      case 403:
        return (code: 'forbidden', message: 'Bạn không có quyền xem mục này.');
      case 404:
        return (code: 'not_found', message: 'Không tìm thấy dữ liệu.');
      case 500:
        return (code: 'internal_error', message: 'Lỗi hệ thống.');
      case 502:
      case 503:
      case 504:
        return (
          code: 'backend_unavailable',
          message: 'Hệ thống tạm thời chưa phản hồi.'
        );
      default:
        return (
          code: 'unknown_error',
          message: 'Lỗi không xác định ($status).'
        );
    }
  }

  // --- Thông báo tiếng Việt cho nông dân (không lộ mã/chi tiết kỹ thuật) ---

  static String friendlyMessage(Object error) {
    if (error is TimeoutException) {
      return 'Máy chủ phản hồi chậm. Kiểm tra mạng rồi thử lại.';
    }
    if (error is! CarbonApiException) {
      final msg = error.toString().toLowerCase();
      if (msg.contains('socketexception') ||
          msg.contains('failed host lookup') ||
          msg.contains('connection refused') ||
          msg.contains('connection closed') ||
          msg.contains('network is unreachable') ||
          msg.contains('clientexception') ||
          msg.contains('timed out')) {
        return 'Không có kết nối mạng. Kết quả đã lưu (nếu có) vẫn xem được; '
            'thử lại khi có mạng.';
      }
      return 'Có lỗi hệ thống. Vui lòng thử lại sau.';
    }

    switch (error.errorCode) {
      case 'missing_authorization':
      case 'unauthenticated':
        return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.';
      case 'forbidden':
      case 'crop_not_found':
        return 'Không tìm thấy vụ canh tác này, hoặc bạn không có quyền xem.';
      case 'invalid_water_regime':
        return 'Kịch bản nước không hợp lệ. Vui lòng chọn lại.';
      case 'conflicting_water_records':
        return 'Các bản ghi tưới đang ghi chế độ nước mâu thuẫn nhau. '
            'Kiểm tra lại nhật ký tưới của vụ.';
      case 'double_counting':
        return 'Dữ liệu rơm rạ đang bị tính trùng nguồn. '
            'Kiểm tra lại cách xử lý rơm trong vụ.';
      case 'missing_emission_factor':
        return 'Hệ thống chưa đủ bộ hệ số để tính chính thức. '
            'Kết quả (nếu có) chỉ mang tính tham khảo.';
      case 'methodology_gap':
        return 'Vụ còn thiếu thông tin phương pháp luận (chế độ nước trước vụ, '
            'tỷ lệ chất khô rơm, số ngày trước canh tác...). Bổ sung ở màn vụ '
            'canh tác rồi tính lại.';
      case 'missing_activity_data':
        return 'Chưa đủ dữ liệu hoạt động để tính (diện tích, %N phân bón...). '
            'Bổ sung nhật ký canh tác rồi tính lại.';
      case 'factor_set_not_imported':
        return 'Hệ thống chưa sẵn sàng: bộ hệ số phát thải chưa được nạp lên. '
            'Vui lòng thử lại sau.';
      case 'backend_not_configured':
      case 'auth_not_configured':
        return 'Hệ thống tính toán đang bảo trì cấu hình. Vui lòng thử lại sau.';
      case 'backend_unavailable':
        return 'Hệ thống tạm thời chưa phản hồi. Vui lòng thử lại sau ít phút.';
      case 'internal_error':
        final ref = error.requestId;
        return 'Có lỗi hệ thống khi tính toán. Vui lòng thử lại sau.'
            '${ref != null ? '\n(Mã tra cứu: ${_shortRef(ref)})' : ''}';
      case 'validation_error':
        return 'Dữ liệu gửi lên chưa hợp lệ. Vui lòng thử lại.';
    }

    // Chưa biết mã → rẽ theo HTTP status.
    switch (error.statusCode) {
      case 401:
      case 403:
        return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.';
      case 404:
        return 'Không tìm thấy vụ canh tác này, hoặc bạn không có quyền xem.';
      case 409:
        return 'Dữ liệu ghi nhận có mâu thuẫn. Vui lòng kiểm tra lại nhật ký.';
      case 422:
        return 'Chưa đủ dữ liệu để tính phát thải. Vui lòng bổ sung nhật ký '
            'canh tác.';
      case 503:
        return 'Hệ thống chưa sẵn sàng tính toán. Vui lòng thử lại sau.';
      default:
        return 'Có lỗi hệ thống. Vui lòng thử lại sau.';
    }
  }

  static String _shortRef(String id) =>
      id.length <= 8 ? id : id.substring(0, 8);
}

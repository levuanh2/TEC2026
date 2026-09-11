import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/carbon_result.dart';
import 'auth_service.dart';

/// Kịch bản nước — khớp đúng `Scenario` trong backend/api.py, không tự đổi tên.
const kScenarioAsRecorded = 'as_recorded';
const kScenarioAwd = 'awd';
const kScenarioContinuousFlooding = 'continuous_flooding';

class CarbonApiException implements Exception {
  CarbonApiException(this.statusCode, this.errorCode, this.message);
  final int statusCode;
  final String errorCode;
  final String message;

  @override
  String toString() => message;
}

class _ApiErrorEnvelope {
  const _ApiErrorEnvelope(this.code, this.message);
  final String code;
  final String? message;
}

/// Gọi FastAPI backend cho CO2e. KHÔNG tính carbon trong app — Carbon Engine
/// chỉ chạy ở backend (docs/BACKEND_1A.md). App chỉ gửi request + hiển thị kết quả.
///
/// Nhận `http.Client` qua constructor (mặc định tự tạo) — KHÔNG thêm package
/// mock nào, test tự viết 1 `http.BaseClient` giả (xem test/carbon_api_service_test.dart)
/// để kiểm request/response mà không cần mạng thật.
class CarbonApiService {
  CarbonApiService(AuthService auth, {http.Client? httpClient})
      : _tokenProvider = (() => auth.accessToken),
        _http = httpClient ?? http.Client();

  /// Chỉ dùng cho test — bơm thẳng token giả, không cần khởi tạo `Supabase`
  /// thật (AuthService.accessToken đọc `Supabase.instance`, không gọi được
  /// trong unit test thuần không có binding Flutter/Supabase).
  CarbonApiService.withTokenProvider(this._tokenProvider, {http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  final String? Function() _tokenProvider;
  final http.Client _http;

  Map<String, String> get _headers {
    final token = _tokenProvider();
    if (token == null) {
      throw CarbonApiException(401, 'missing_authorization', 'Chưa đăng nhập.');
    }
    return {
      'Authorization': 'Bearer $token',
      'Content-Type': 'application/json',
    };
  }

  Future<CarbonResult> calculate({
    required String cropSeasonId,
    String scenario = kScenarioAsRecorded,
  }) async {
    final response = await _http.post(
      Uri.parse('${AppConfig.backendBaseUrl}/v1/carbon/calculate'),
      headers: _headers,
      body: jsonEncode({
        'crop_season_id': cropSeasonId,
        'water_regime_scenario': scenario,
      }),
    );
    return _parseOrThrow(response);
  }

  Future<CarbonResult?> latest({
    required String cropSeasonId,
    String? scenario,
  }) async {
    final uri = Uri.parse('${AppConfig.backendBaseUrl}/v1/crop-seasons/$cropSeasonId/carbon')
        .replace(queryParameters: scenario == null ? null : {'scenario': scenario});
    final response = await _http.get(uri, headers: _headers);

    // 404 có HAI nguyên nhân khác hẳn nhau (backend/api.py) — không được gộp làm một:
    //   error = "no_calculation" -> vụ hợp lệ, chỉ chưa từng tính -> im lặng trả null,
    //           màn hình hiện "chưa tính" là đúng.
    //   error = "crop_not_found" -> RLS từ chối HOẶC vụ không tồn tại -> đây LÀ lỗi,
    //           phải ném ra để UI báo đúng, không được âm thầm coi là "chưa tính".
    if (response.statusCode == 404) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      if (_errorEnvelope(body).code == 'no_calculation') return null;
    }
    return _parseOrThrow(response);
  }

  CarbonResult _parseOrThrow(http.Response response) {
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return CarbonResult.fromJson(body);
    }
    final error = _errorEnvelope(body);
    throw CarbonApiException(
      response.statusCode,
      error.code,
      error.message ?? 'Lỗi không xác định (${response.statusCode}).',
    );
  }

  /// Frozen FastAPI envelope: {detail: {error: {code, message}}}.
  /// The flat branch only preserves a useful message during deployment rollout;
  /// all current backend routes use the nested envelope.
  static _ApiErrorEnvelope _errorEnvelope(Map<String, dynamic> body) {
    final detail = body['detail'];
    if (detail is! Map) return const _ApiErrorEnvelope('unknown_error', null);
    final rawError = detail['error'];
    if (rawError is Map) {
      return _ApiErrorEnvelope(
        rawError['code'] as String? ?? 'unknown_error',
        rawError['message'] as String? ?? detail['message'] as String?,
      );
    }
    return _ApiErrorEnvelope(
      rawError as String? ?? 'unknown_error',
      detail['message'] as String?,
    );
  }

  /// Thông báo tiếng Việt theo đúng docs/BACKEND_1A.md §9 — không hiện mã lỗi thô.
  static String friendlyMessage(Object error) {
    if (error is! CarbonApiException) {
      // http package/SocketException không có type ổn định giữa các nền tảng —
      // dò theo nội dung message là cách thực dụng để phân biệt "mất mạng" với
      // "lỗi khác" (Phase 17 cần trạng thái "offline" riêng, không gộp chung
      // "error"). Không hoàn hảo, nhưng bao trùm trường hợp thường gặp nhất.
      final msg = error.toString().toLowerCase();
      if (msg.contains('socketexception') ||
          msg.contains('failed host lookup') ||
          msg.contains('connection refused') ||
          msg.contains('network is unreachable')) {
        return 'Không có kết nối mạng. Dữ liệu vẫn được lưu trên máy — thử lại khi có mạng.';
      }
      return 'Có lỗi hệ thống. Vui lòng thử lại sau.';
    }
    switch (error.statusCode) {
      case 401:
        return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.';
      case 404:
        return 'Không tìm thấy vụ canh tác này, hoặc bạn không có quyền xem.';
      case 409:
        return 'Dữ liệu ghi nhận có mâu thuẫn (ví dụ chế độ nước). Vui lòng kiểm tra lại nhật ký.';
      case 422:
        if (error.errorCode == 'missing_emission_factor') {
          return 'Chưa thể tính phát thải theo bộ hệ số hiện tại. Vui lòng thử lại sau.';
        }
        return 'Chưa đủ dữ liệu để tính phát thải. Vui lòng bổ sung nhật ký canh tác.\n(${error.message})';
      case 503:
        return 'Hệ thống chưa sẵn sàng tính toán (thiếu bộ hệ số). Vui lòng thử lại sau.';
      default:
        return 'Có lỗi hệ thống. Vui lòng thử lại sau.';
    }
  }
}

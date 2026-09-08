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

/// Gọi FastAPI backend cho CO2e. KHÔNG tính carbon trong app — Carbon Engine
/// chỉ chạy ở backend (docs/BACKEND_1A.md). App chỉ gửi request + hiển thị kết quả.
class CarbonApiService {
  CarbonApiService(this._auth);
  final AuthService _auth;

  Map<String, String> get _headers {
    final token = _auth.accessToken;
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
    final response = await http.post(
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
    final response = await http.get(uri, headers: _headers);
    if (response.statusCode == 404) return null; // chưa có bản tính nào — không phải lỗi
    return _parseOrThrow(response);
  }

  CarbonResult _parseOrThrow(http.Response response) {
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return CarbonResult.fromJson(body);
    }
    final detail = body['detail'] as Map<String, dynamic>? ?? {};
    throw CarbonApiException(
      response.statusCode,
      detail['error'] as String? ?? 'unknown_error',
      detail['message'] as String? ?? 'Lỗi không xác định (${response.statusCode}).',
    );
  }

  /// Thông báo tiếng Việt theo đúng docs/BACKEND_1A.md §9 — không hiện mã lỗi thô.
  static String friendlyMessage(Object error) {
    if (error is! CarbonApiException) return 'Có lỗi hệ thống. Vui lòng thử lại sau.';
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

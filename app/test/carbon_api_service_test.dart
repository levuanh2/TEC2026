// ⚠️ CHƯA CHẠY LẦN NÀO. Chạy thật: cd app && flutter test test/carbon_api_service_test.dart
//
// Không thêm package mock (không cần thiết) — tự viết 1 http.BaseClient giả,
// đủ để kiểm request thật sự gửi đi (JSON, header) và cách map response -> lỗi.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:agricarbon_app/services/carbon_api_service.dart';

class _FakeHttpClient extends http.BaseClient {
  _FakeHttpClient(this._respond);
  final http.Response Function(http.BaseRequest request, String? body) _respond;
  http.BaseRequest? lastRequest;
  String? lastBody;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    lastRequest = request;
    String? body;
    if (request is http.Request) body = request.body;
    lastBody = body;
    final response = _respond(request, body);
    return http.StreamedResponse(
      Stream.value(utf8.encode(response.body)),
      response.statusCode,
      headers: response.headers,
    );
  }
}

http.Response _json(int status, Map<String, dynamic> body) =>
    http.Response(jsonEncode(body), status);

void main() {
  group('request serialization', () {
    test('POST /v1/carbon/calculate gửi đúng JSON body + Authorization header', () async {
      late http.BaseRequest captured;
      final fakeClient = _FakeHttpClient((request, body) {
        captured = request;
        return _json(200, {
          'crop_season_id': 'season-1',
          'water_regime_scenario': 'awd',
          'co2e_total_kg': 100.0,
          'yield_kg': 200.0,
          'co2e_per_kg': 0.5,
          'breakdown': [],
          'methodology': {'name': 'TEST', 'version': 'test'},
          'ef_config_version': 'TEST',
          'engine_version': '0.2.0',
          'input_hash': 'x' * 64,
          'calculated_at': '2026-09-08T00:00:00Z',
          'warnings': [],
        });
      });
      final service =
          CarbonApiService.withTokenProvider(() => 'fake-jwt-token', httpClient: fakeClient);

      final result =
          await service.calculate(cropSeasonId: 'season-1', scenario: 'awd');

      expect(captured.method, 'POST');
      expect(captured.url.path, '/v1/carbon/calculate');
      expect(captured.headers['Authorization'], 'Bearer fake-jwt-token');
      expect(
        jsonDecode(fakeClient.lastBody!),
        {'crop_season_id': 'season-1', 'water_regime_scenario': 'awd'},
      );
      expect(result.totalCo2eKg, 100.0);
    });

    test('GET /v1/crop-seasons/{id}/carbon gắn đúng query scenario', () async {
      late Uri capturedUri;
      final fakeClient = _FakeHttpClient((request, body) {
        capturedUri = request.url;
        return _json(200, {
          'crop_season_id': 'season-1',
          'water_regime_scenario': 'as_recorded',
          'co2e_total_kg': 1.0,
          'yield_kg': null,
          'co2e_per_kg': null,
          'breakdown': [],
          'methodology': {'name': 'TEST'},
          'ef_config_version': 'TEST',
          'calculated_at': '',
          'warnings': [],
        });
      });
      final service = CarbonApiService.withTokenProvider(() => 't', httpClient: fakeClient);

      await service.latest(cropSeasonId: 'season-1', scenario: 'awd');

      expect(capturedUri.path, '/v1/crop-seasons/season-1/carbon');
      expect(capturedUri.queryParameters['scenario'], 'awd');
    });

    test('chưa đăng nhập (token null) -> ném lỗi TRƯỚC khi gọi mạng', () async {
      var called = false;
      final fakeClient = _FakeHttpClient((request, body) {
        called = true;
        return _json(200, {});
      });
      final service = CarbonApiService.withTokenProvider(() => null, httpClient: fakeClient);

      await expectLater(
        service.calculate(cropSeasonId: 'x'),
        throwsA(isA<CarbonApiException>()
            .having((e) => e.statusCode, 'statusCode', 401)),
      );
      expect(called, isFalse); // không lãng phí request khi chắc chắn sẽ 401
    });
  });

  group('GET .../carbon — hai loại 404 KHÔNG được gộp làm một', () {
    test('404 no_calculation -> trả null (chưa từng tính, không phải lỗi)', () async {
      final fakeClient = _FakeHttpClient((request, body) => _json(404, {
            'detail': {
              'error': {
                'code': 'no_calculation',
                'message': 'chưa có bản tính',
              }
            }
          }));
      final service = CarbonApiService.withTokenProvider(() => 't', httpClient: fakeClient);

      final result = await service.latest(cropSeasonId: 'season-1');
      expect(result, isNull);
    });

    test('404 crop_not_found (RLS từ chối) -> PHẢI ném lỗi, không được trả null', () async {
      final fakeClient = _FakeHttpClient((request, body) => _json(404, {
            'detail': {
              'error': {
                'code': 'crop_not_found',
                'message': 'không có quyền',
              }
            }
          }));
      final service = CarbonApiService.withTokenProvider(() => 't', httpClient: fakeClient);

      await expectLater(
        service.latest(cropSeasonId: 'season-of-another-farmer'),
        throwsA(isA<CarbonApiException>()
            .having((e) => e.errorCode, 'errorCode', 'crop_not_found')),
      );
    });
  });

  group('API error mapping -> thông báo tiếng Việt', () {
    test('đọc error object đã đóng băng từ FastAPI', () async {
      final fakeClient = _FakeHttpClient((request, body) => _json(422, {
            'detail': {
              'error': {
                'code': 'missing_emission_factor',
                'message': 'GWP CH4 chưa xác minh',
              }
            }
          }));
      final service = CarbonApiService.withTokenProvider(() => 't', httpClient: fakeClient);

      await expectLater(
        service.calculate(cropSeasonId: 'season-1'),
        throwsA(isA<CarbonApiException>()
            .having((e) => e.errorCode, 'errorCode', 'missing_emission_factor')
            .having((e) => e.message, 'message', 'GWP CH4 chưa xác minh')),
      );
    });

    test('401 -> phiên hết hạn', () {
      final e = CarbonApiException(401, 'missing_authorization', 'x');
      expect(CarbonApiService.friendlyMessage(e), contains('hết hạn'));
    });

    test('422 missing_emission_factor -> không lộ chi tiết kỹ thuật backend', () {
      final e = CarbonApiException(422, 'missing_emission_factor', 'gwp.ch4 chưa xác minh...');
      final msg = CarbonApiService.friendlyMessage(e);
      expect(msg, isNot(contains('gwp.ch4'))); // không leak chi tiết backend ra UI
      expect(msg, contains('hệ số'));
    });

    test('409 conflicting_water_records -> gợi ý đúng hướng sửa', () {
      final e = CarbonApiException(409, 'conflicting_water_records', 'x');
      expect(CarbonApiService.friendlyMessage(e), contains('mâu thuẫn'));
    });

    test('503 factor_set_not_imported -> không nói "lỗi của bạn"', () {
      final e = CarbonApiException(503, 'factor_set_not_imported', 'x');
      expect(CarbonApiService.friendlyMessage(e), contains('chưa sẵn sàng'));
    });

    test('lỗi mạng (không phải CarbonApiException) -> báo offline, không phải "lỗi hệ thống"', () {
      final e = Exception('SocketException: Failed host lookup');
      expect(CarbonApiService.friendlyMessage(e), contains('kết nối mạng'));
    });
  });

  group('missing yield qua toàn bộ chuỗi API thật', () {
    test('backend trả co2e_per_kg=null -> CarbonResult giữ nguyên null, không tự đặt 0', () async {
      final fakeClient = _FakeHttpClient((request, body) => _json(200, {
            'crop_season_id': 's1',
            'water_regime_scenario': 'awd',
            'co2e_total_kg': 500.0,
            'yield_kg': null,
            'co2e_per_kg': null,
            'breakdown': [],
            'methodology': {'name': 'TEST'},
            'ef_config_version': 'TEST',
            'calculated_at': '',
            'warnings': ['Chưa có sản lượng nên chưa tính được CO2e/kg.'],
          }));
      final service = CarbonApiService.withTokenProvider(() => 't', httpClient: fakeClient);

      final result = await service.calculate(cropSeasonId: 's1');

      expect(result.totalCo2eKg, 500.0);
      expect(result.co2ePerKg, isNull);
      expect(result.co2ePerKg, isNot(0));
    });
  });
}

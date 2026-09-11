// Không thêm package mock — tự viết 1 http.BaseClient giả, đủ để kiểm request
// thật sự gửi đi + cách map response/lỗi.

import 'dart:async';
import 'dart:convert';

import 'package:agricarbon_app/services/carbon_api_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

class _FakeHttpClient extends http.BaseClient {
  _FakeHttpClient(this._respond);
  final FutureOr<http.Response> Function(http.BaseRequest r, String? body)
      _respond;
  http.BaseRequest? lastRequest;
  String? lastBody;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    lastRequest = request;
    lastBody = request is http.Request ? request.body : null;
    final response = await _respond(request, lastBody);
    return http.StreamedResponse(
      Stream.value(utf8.encode(response.body)),
      response.statusCode,
      headers: response.headers,
    );
  }
}

http.Response _json(int status, Object body) => http.Response(
      body is String ? body : jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

http.Response _raw(int status, String body) =>
    http.Response(body, status, headers: {'content-type': 'text/plain'});

CarbonApiService _svc(_FakeHttpClient c, {String token = 't'}) =>
    CarbonApiService.withTokenProvider(() => token,
        httpClient: c, timeout: const Duration(milliseconds: 200));

Map<String, dynamic> _okResult({double? perKg = 0.5}) => {
      'crop_season_id': 's1',
      'water_regime_scenario': 'awd',
      'water_regime_applied': 'irrigated_multiple_drainage',
      'co2e_total_kg': 1990.5,
      'yield_kg': perKg == null ? null : 5200.0,
      'co2e_per_kg': perKg,
      'breakdown': [
        {'source': 'ch4_rice_cultivation', 'gas': 'ch4', 'co2e_kg': 1600.0},
      ],
      'methodology': {
        'name': 'IPCC 2019 Refinement',
        'version': '2019',
        'tier': 1
      },
      'ef_config_version': '0.2.0-ipcc-tier1',
      'engine_version': '0.2.0',
      'calculated_at': '2026-09-08T00:00:00+00:00',
      'warnings': <String>[],
    };

void main() {
  group('request', () {
    test('POST calculate: JSON body + Authorization + gắn fetchedAt', () async {
      late http.BaseRequest cap;
      final c = _FakeHttpClient((r, b) {
        cap = r;
        return _json(200, _okResult());
      });
      final res = await _svc(c).calculate(cropSeasonId: 's1', scenario: 'awd');
      expect(cap.method, 'POST');
      expect(cap.url.path, '/v1/carbon/calculate');
      expect(cap.headers['Authorization'], 'Bearer t');
      expect(jsonDecode(c.lastBody!),
          {'crop_season_id': 's1', 'water_regime_scenario': 'awd'});
      expect(res.fetchedAt, isNotNull);
      expect(res.waterRegimeApplied, 'irrigated_multiple_drainage');
      expect(res.methodologyTier, 1);
    });

    test('GET carbon: query scenario đúng', () async {
      late Uri uri;
      final c = _FakeHttpClient((r, b) {
        uri = r.url;
        return _json(200, _okResult());
      });
      await _svc(c).latest(cropSeasonId: 's1', scenario: 'awd');
      expect(uri.path, '/v1/crop-seasons/s1/carbon');
      expect(uri.queryParameters['scenario'], 'awd');
    });

    test('token null -> ném 401 TRƯỚC khi gọi mạng', () async {
      var called = false;
      final c = _FakeHttpClient((r, b) {
        called = true;
        return _json(200, {});
      });
      await expectLater(
        CarbonApiService.withTokenProvider(() => null, httpClient: c)
            .calculate(cropSeasonId: 'x'),
        throwsA(isA<CarbonApiException>()
            .having((e) => e.statusCode, 'status', 401)),
      );
      expect(called, isFalse);
    });
  });

  group('nested error parser', () {
    Future<CarbonApiException> caught(http.Response resp) async {
      try {
        await _svc(_FakeHttpClient((r, b) => resp))
            .calculate(cropSeasonId: 's1');
        fail('phải ném');
      } on CarbonApiException catch (e) {
        return e;
      }
    }

    test('detail.error.{code,message} nested', () async {
      final e = await caught(_json(422, {
        'detail': {
          'error': {'code': 'methodology_gap', 'message': 'thiếu SFp'}
        }
      }));
      expect(e.errorCode, 'methodology_gap');
      expect(e.message, 'thiếu SFp');
    });

    test('internal_error 500 kèm request_id', () async {
      final e = await caught(_json(500, {
        'detail': {
          'error': {
            'code': 'internal_error',
            'message': 'Lỗi hệ thống.',
            'request_id': 'abcd1234-ef56'
          }
        }
      }));
      expect(e.errorCode, 'internal_error');
      expect(e.requestId, 'abcd1234-ef56');
      expect(CarbonApiService.friendlyMessage(e), contains('abcd1234'));
    });

    test('detail.error là string (shape cũ) vẫn đọc được', () async {
      final e = await caught(_json(409, {
        'detail': {'error': 'conflicting_water_records', 'message': 'x'}
      }));
      expect(e.errorCode, 'conflicting_water_records');
    });

    test('HTTPValidationError (detail là list) -> validation_error', () async {
      final e = await caught(_json(422, {
        'detail': [
          {
            'loc': ['body', 'crop_season_id'],
            'msg': 'field required',
            'type': 'value_error.missing'
          }
        ]
      }));
      expect(e.errorCode, 'validation_error');
      expect(e.message, contains('field required'));
    });

    test('body KHÔNG phải JSON -> fallback theo status, không ném parse',
        () async {
      final e = await caught(_raw(503, '<html>502 Bad Gateway</html>'));
      expect(e.statusCode, 503);
      expect(e.errorCode, 'backend_unavailable');
      expect(CarbonApiService.friendlyMessage(e), isNotEmpty);
    });

    test('body JSON hỏng (cắt giữa chừng) -> fallback', () async {
      final e = await caught(_raw(500, '{"detail": {"error": {"code":'));
      expect(e.statusCode, 500);
      expect(e.errorCode, 'internal_error');
    });

    test('body rỗng -> fallback theo status', () async {
      final e = await caught(_raw(404, ''));
      expect(e.errorCode, 'not_found');
    });
  });

  group('GET carbon — hai loại 404 KHÁC NHAU', () {
    test('no_calculation -> trả null (không phải lỗi)', () async {
      final c = _FakeHttpClient((r, b) => _json(404, {
            'detail': {
              'error': {'code': 'no_calculation', 'message': 'chưa tính'}
            }
          }));
      expect(await _svc(c).latest(cropSeasonId: 's1'), isNull);
    });

    test('crop_not_found -> NÉM (RLS/không tồn tại)', () async {
      final c = _FakeHttpClient((r, b) => _json(404, {
            'detail': {
              'error': {'code': 'crop_not_found', 'message': 'x'}
            }
          }));
      await expectLater(
        _svc(c).latest(cropSeasonId: 's-other'),
        throwsA(isA<CarbonApiException>()
            .having((e) => e.errorCode, 'code', 'crop_not_found')),
      );
    });
  });

  group('timeout / mạng', () {
    test('timeout -> TimeoutException; friendlyMessage nói "chậm"', () async {
      final c = _FakeHttpClient((r, b) async {
        await Future<void>.delayed(const Duration(seconds: 2));
        return _json(200, _okResult());
      });
      await expectLater(
        _svc(c).calculate(cropSeasonId: 's1'),
        throwsA(isA<TimeoutException>()),
      );
      expect(
        CarbonApiService.friendlyMessage(TimeoutException('x')),
        contains('chậm'),
      );
    });

    test('SocketException -> friendlyMessage nói "kết nối mạng"', () {
      final e = Exception('SocketException: Failed host lookup');
      expect(CarbonApiService.friendlyMessage(e), contains('kết nối mạng'));
    });
  });

  group('friendlyMessage phủ đủ mã lỗi, không lộ kỹ thuật', () {
    for (final entry in const {
      'missing_authorization': 'hết hạn',
      'crop_not_found': 'quyền',
      'invalid_water_regime': 'Kịch bản nước',
      'conflicting_water_records': 'mâu thuẫn',
      'double_counting': 'trùng',
      'missing_emission_factor': 'hệ số',
      'methodology_gap': 'phương pháp luận',
      'missing_activity_data': 'dữ liệu hoạt động',
      'factor_set_not_imported': 'chưa sẵn sàng',
      'backend_not_configured': 'bảo trì',
      'auth_not_configured': 'bảo trì',
    }.entries) {
      test('${entry.key} -> chứa "${entry.value}"', () {
        final msg = CarbonApiService.friendlyMessage(
            CarbonApiException(422, entry.key, 'raw backend detail xyz'));
        expect(msg, contains(entry.value));
        expect(msg, isNot(contains('xyz')));
      });
    }
  });

  group('scenarios() + health()', () {
    test('scenarios ok -> lọc theo 3 enum chính thức', () async {
      final c = _FakeHttpClient((r, b) => _json(200, {
            'scenarios': ['awd', 'continuous_flooding', 'as_recorded', 'weird']
          }));
      final s = await _svc(c).scenarios();
      expect(s, ['awd', 'continuous_flooding', 'as_recorded']);
    });

    test('scenarios lỗi -> fallback 3 enum', () async {
      final c = _FakeHttpClient((r, b) => _raw(500, 'boom'));
      expect(await _svc(c).scenarios(), kOfficialScenarios);
    });

    test('scenarios: KHÔNG kèm Authorization (route không cần auth)', () async {
      late http.BaseRequest cap;
      final c = _FakeHttpClient((r, b) {
        cap = r;
        return _json(200, {
          'scenarios': ['awd']
        });
      });
      await _svc(c).scenarios();
      expect(cap.headers.containsKey('Authorization'), isFalse);
    });

    test('health -> đọc carbon_production_ready', () async {
      final c = _FakeHttpClient((r, b) => _json(200, {
            'status': 'ok',
            'engine_version': '0.2.0',
            'ef_config_version': '0.2.0-ipcc-tier1',
            'methodology': {'name': 'IPCC 2019'},
            'carbon_production_ready': false,
            'mrv_compliant': false,
            'note': 'GWP chưa xác minh'
          }));
      final h = await _svc(c).health();
      expect(h, isNotNull);
      expect(h!.carbonProductionReady, isFalse);
      expect(h.mrvCompliant, isFalse);
      expect(h.methodologyName, 'IPCC 2019');
    });

    test('health lỗi -> null', () async {
      final c = _FakeHttpClient((r, b) => _raw(503, 'x'));
      expect(await _svc(c).health(), isNull);
    });
  });

  test('co2e_per_kg=null giữ nguyên null, KHÔNG thành 0', () async {
    final c = _FakeHttpClient((r, b) => _json(200, _okResult(perKg: null)));
    final res = await _svc(c).calculate(cropSeasonId: 's1');
    expect(res.co2ePerKg, isNull);
    expect(res.totalCo2eKg, 1990.5);
  });
}

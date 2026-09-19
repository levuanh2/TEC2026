import 'dart:async';
import 'dart:convert';

import 'package:agricarbon_app/models/activity_field_spec.dart';
import 'package:agricarbon_app/models/activity_validation.dart';
import 'package:agricarbon_app/models/carbon_readiness.dart';
import 'package:agricarbon_app/services/carbon_api_service.dart';
import 'package:agricarbon_app/services/me_service.dart';
import 'package:agricarbon_app/services/read_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

/// Carbon UX parity — hợp đồng dữ liệu (không UI). App KHÔNG chứa luật phương
/// pháp luận: readiness đọc nguyên từ máy chủ, số liệu người dùng gõ không bao
/// giờ âm thầm thành null.

class _Http extends http.BaseClient {
  _Http(this.respond);
  final http.Response Function(http.BaseRequest) respond;
  http.BaseRequest? last;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    last = request;
    final r = respond(request);
    return http.StreamedResponse(Stream.value(utf8.encode(r.body)), r.statusCode,
        headers: r.headers);
  }
}

http.Response _json(int status, Object body) => http.Response(
    jsonEncode(body), status,
    headers: {'content-type': 'application/json; charset=utf-8'});

ActivityFieldSpec _spec(String type, String key) =>
    kActivityFieldSpecs[type]!.firstWhere((s) => s.key == key);

String? _error(String type, String key, String raw) {
  final parsed = parseActivityField(_spec(type, key), raw);
  final v = validateActivity(
    type: type,
    parsed: {
      if (type == 'straw_management') 'method': const ParsedField('incorporated', null),
      if (type == 'fertilizer') ...{
        'fertilizer_name': const ParsedField('NPK', null),
        'amount_kg': const ParsedField(80.0, null),
      },
      key: parsed,
    },
    occurredAt: DateTime(2026, 1, 1),
    now: DateTime(2026, 2, 1),
  );
  return v.fieldErrors[key];
}

void main() {
  group('readiness — đọc nguyên từ máy chủ', () {
    test('parse flow, records, blocking; flow lạ -> unknown, không nút sửa', () {
      final r = CarbonReadiness.fromJson({
        'can_calculate': false,
        'blocking_count': 2,
        'missing_inputs': [
          {
            'code': 'fertilizer_nitrogen', 'label': 'Thiếu hàm lượng Nitơ', 'detail': 'd',
            'flow': 'activity', 'activity_type': 'fertilizer', 'blocking': true,
            'records': [{'activity_id': 'srv-1', 'occurred_on': '2026-03-05', 'label': 'NPK'}],
          },
          {'code': 'fuel_factor_unverified', 'label': 'x', 'detail': 'y', 'flow': 'factor_unavailable', 'blocking': true},
          {'code': 'harvest_yield', 'label': 'z', 'detail': 'w', 'flow': 'activity', 'blocking': false},
          {'code': 'future_thing', 'label': 'q', 'detail': 'r', 'flow': 'brand_new_flow', 'blocking': true},
        ],
      });
      expect(r.canCalculate, isFalse);
      expect(r.blocking.map((m) => m.code), ['fertilizer_nitrogen', 'fuel_factor_unverified', 'future_thing']);
      expect(r.nonBlocking.single.code, 'harvest_yield');
      final n = r.missingInputs.first;
      expect(n.flow, ReadinessFlow.activity);
      expect(n.records.single.activityId, 'srv-1');
      expect(n.userFixable, isTrue);
      expect(r.missingInputs[1].flow, ReadinessFlow.factorUnavailable);
      expect(r.missingInputs[1].userFixable, isFalse);
      expect(r.missingInputs[3].flow, ReadinessFlow.unknown);
      expect(r.missingInputs[3].userFixable, isFalse);
    });

    test('CarbonApiService.readiness gọi đúng route bằng server id, kèm Bearer', () async {
      final client = _Http((_) => _json(200, {'can_calculate': true, 'blocking_count': 0, 'missing_inputs': []}));
      final svc = CarbonApiService.withTokenProvider(() => 'tok', httpClient: client);
      final r = await svc.readiness(cropSeasonId: 'srv-cs1');
      expect(r.canCalculate, isTrue);
      expect(client.last!.url.path, '/v1/crop-seasons/srv-cs1/carbon/readiness');
      expect(client.last!.headers['Authorization'], 'Bearer tok');
    });

    test('lỗi máy chủ -> ném CarbonApiException có mã, không giả "đủ dữ liệu"', () async {
      final client = _Http((_) => _json(404, {'detail': {'error': {'code': 'crop_not_found', 'message': 'x'}}}));
      final svc = CarbonApiService.withTokenProvider(() => 'tok', httpClient: client);
      expect(
        () => svc.readiness(cropSeasonId: 'srv-cs1'),
        throwsA(isA<CarbonApiException>().having((e) => e.errorCode, 'code', 'crop_not_found')),
      );
    });
  });

  group('quyền ghi — cùng nguồn Farmer Web (farm_memberships owner/editor)', () {
    test('owner/editor ghi được; viewer thì không', () async {
      final client = _Http((_) => _json(200, {
            'user_id': 'u', 'roles': ['farmer', 'owner', 'viewer'],
            'organization_memberships': [],
            'farm_memberships': [
              {'farm_id': 'f-own', 'farm_role': 'owner'},
              {'farm_id': 'f-edit', 'farm_role': 'editor'},
              {'farm_id': 'f-view', 'farm_role': 'viewer'},
            ],
          }));
      final me = await MeService(ReadApi(() => 'tok', httpClient: client)).fetch();
      expect(me.writableFarmIds, {'f-own', 'f-edit'});
      expect(me.canWriteFarm('f-view'), isFalse);
    });
  });

  group('số người dùng gõ — không âm thầm thành null, không đổi thang đo', () {
    test('tỷ lệ chất khô', () {
      expect(_error('straw_management', 'dry_matter_fraction', '0.85'), isNull);
      expect(_error('straw_management', 'dry_matter_fraction', '0,85'), isNull);
      expect(parseActivityField(_spec('straw_management', 'dry_matter_fraction'), '0,85').value, 0.85);
      expect(_error('straw_management', 'dry_matter_fraction', '85'), isNotNull); // không hiểu thành 0,85
      expect(_error('straw_management', 'dry_matter_fraction', '0'), isNotNull);
      expect(_error('straw_management', 'dry_matter_fraction', 'abc'), isNotNull);
      expect(_error('straw_management', 'dry_matter_fraction', '1e3'), isNotNull);
      expect(_error('straw_management', 'dry_matter_fraction', '1.000,5'), isNotNull);
      final blank = parseActivityField(_spec('straw_management', 'dry_matter_fraction'), '  ');
      expect(blank.value, isNull);
      expect(blank.error, isNull);
    });

    test('số ngày vùi rơm trước khi làm đất', () {
      expect(_error('straw_management', 'days_before_cultivation', '0'), isNull);
      expect(parseActivityField(_spec('straw_management', 'days_before_cultivation'), '0').value, 0);
      expect(_error('straw_management', 'days_before_cultivation', '30'), isNull);
      expect(_error('straw_management', 'days_before_cultivation', '-1'), isNotNull);
      expect(_error('straw_management', 'days_before_cultivation', '1.5'), isNotNull);
      expect(parseActivityField(_spec('straw_management', 'days_before_cultivation'), '').value, isNull);
    });

    test('% đạm theo miền của máy chủ (0–100)', () {
      expect(_error('fertilizer', 'nitrogen_percent', '46'), isNull);
      expect(_error('fertilizer', 'nitrogen_percent', '16,5'), isNull);
      expect(_error('fertilizer', 'nitrogen_percent', '101'), isNotNull);
      expect(_error('fertilizer', 'nitrogen_percent', '-1'), isNotNull);
    });

    test('rơm vùi để trống chất khô/số ngày vẫn lưu được (readiness báo sau)', () {
      final v = validateActivity(
        type: 'straw_management',
        parsed: {'method': const ParsedField('incorporated', null)},
        occurredAt: DateTime(2026, 1, 1),
        now: DateTime(2026, 2, 1),
      );
      expect(v.hasError, isFalse);
    });
  });

  test('returned_to_field là 3 trạng thái rõ ràng: Có / Không / Chưa chọn', () {
    expect(_spec('straw_management', 'returned_to_field').kind, ActivityFieldKind.tristate);
  });
}

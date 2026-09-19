import 'package:agricarbon_app/models/activity.dart' show kActivityTypes;
import 'package:agricarbon_app/models/activity_field_spec.dart';
import 'package:agricarbon_app/models/activity_validation.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/methodology_enums.dart';
import 'package:flutter_test/flutter_test.dart';

ActivityFieldSpec _spec(String type, String key) =>
    kActivityFieldSpecs[type]!.firstWhere((s) => s.key == key);

ParsedField _num(num v) => ParsedField(v, null);
ParsedField _str(String v) => ParsedField(v, null);
const _empty = ParsedField.empty();

final _past = DateTime(2026, 3, 1, 8, 30);
final _now = DateTime(2026, 3, 5, 12);

CropSeason _season({int? drainage, IpccWaterRegime? regime}) => CropSeason(
      clientId: 'cs',
      plotClientId: 'p',
      seasonCode: 'S',
      ipccWaterRegime: regime,
      drainageEventCount: drainage,
      createdAt: _now,
      updatedAt: _now,
    );

void main() {
  group('parseActivityField — sai định dạng KHÔNG thành null', () {
    test('decimal: "abc" -> error, không phải empty', () {
      final r = parseActivityField(_spec('seeding', 'seed_kg'), 'abc');
      expect(r.error, isNotNull);
      expect(r.value, isNull);
      expect(r.isEmpty, isFalse);
    });
    test('decimal: chấp nhận dấu phẩy Việt Nam', () {
      final r = parseActivityField(_spec('seeding', 'seed_kg'), '12,5');
      expect(r.error, isNull);
      expect(r.value, 12.5);
    });
    test('integer: "3.5" -> error', () {
      final r =
          parseActivityField(_spec('irrigation', 'duration_minutes'), '3.5');
      expect(r.error, isNotNull);
    });
    test('trống -> empty (hợp lệ nếu không bắt buộc)', () {
      final r = parseActivityField(_spec('seeding', 'variety_name'), '  ');
      expect(r.isEmpty, isTrue);
    });
  });

  group('validateActivity — biên', () {
    test('occurred_at ở tương lai -> lỗi', () {
      final v = validateActivity(
        type: 'seeding',
        parsed: {'seed_kg': _num(10)},
        occurredAt: DateTime(2026, 3, 6),
        now: _now,
      );
      expect(v.occurredAtError, isNotNull);
      expect(v.hasError, isTrue);
    });

    test('seeding thiếu seed_kg (bắt buộc) -> lỗi', () {
      final v = validateActivity(
        type: 'seeding',
        parsed: const {'seed_kg': _empty},
        occurredAt: _past,
        now: _now,
      );
      expect(v.fieldErrors['seed_kg'], isNotNull);
    });

    test('seed_kg = 0 -> lỗi (> 0)', () {
      final v = validateActivity(
        type: 'seeding',
        parsed: {'seed_kg': _num(0)},
        occurredAt: _past,
        now: _now,
      );
      expect(v.fieldErrors['seed_kg'], contains('lớn hơn 0'));
    });

    test('cost âm -> lỗi (>= 0)', () {
      final v = validateActivity(
        type: 'seeding',
        parsed: {'seed_kg': _num(5), 'cost_vnd': _num(-100)},
        occurredAt: _past,
        now: _now,
      );
      expect(v.fieldErrors['cost_vnd'], contains('âm'));
    });

    test('nitrogen_percent > 100 -> lỗi', () {
      final v = validateActivity(
        type: 'fertilizer',
        parsed: {
          'fertilizer_name': _str('Ure'),
          'amount_kg': _num(50),
          'nitrogen_percent': _num(146),
        },
        occurredAt: _past,
        now: _now,
      );
      expect(v.fieldErrors['nitrogen_percent'], isNotNull);
    });

    test('dry_matter_fraction ngoài (0,1] -> lỗi', () {
      for (final bad in [0, 1.5, -0.2]) {
        final v = validateActivity(
          type: 'straw_management',
          parsed: {
            'method': _str('composted'),
            'dry_matter_fraction': _num(bad)
          },
          occurredAt: _past,
          now: _now,
        );
        expect(v.fieldErrors['dry_matter_fraction'], isNotNull, reason: '$bad');
      }
      final ok = validateActivity(
        type: 'straw_management',
        parsed: {
          'method': _str('composted'),
          'dry_matter_fraction': _num(0.85)
        },
        occurredAt: _past,
        now: _now,
      );
      expect(ok.fieldErrors['dry_matter_fraction'], isNull);
    });

    test('days_before_cultivation âm -> lỗi', () {
      final v = validateActivity(
        type: 'straw_management',
        parsed: {
          'method': _str('incorporated'),
          'dry_matter_fraction': _num(0.8),
          'days_before_cultivation': _num(-1),
        },
        occurredAt: _past,
        now: _now,
      );
      expect(v.fieldErrors['days_before_cultivation'], isNotNull);
    });

    test('straw incorporated để trống dry_matter/days VẪN lưu được — thiếu gì '
        'cho Carbon là việc của readiness máy chủ, không phải luật trong Dart', () {
      final v = validateActivity(
        type: 'straw_management',
        parsed: {'method': _str('incorporated')},
        occurredAt: _past,
        now: _now,
      );
      expect(v.hasError, isFalse);

      final ok = validateActivity(
        type: 'straw_management',
        parsed: {
          'method': _str('incorporated'),
          'dry_matter_fraction': _num(0.85),
          'days_before_cultivation': _num(20),
        },
        occurredAt: _past,
        now: _now,
      );
      expect(ok.hasError, isFalse);
    });

    test('straw composted KHÔNG bắt buộc dry_matter/days', () {
      final v = validateActivity(
        type: 'straw_management',
        parsed: {'method': _str('composted')},
        occurredAt: _past,
        now: _now,
      );
      expect(v.fieldErrors['dry_matter_fraction'], isNull);
      expect(v.fieldErrors['days_before_cultivation'], isNull);
    });

    test('harvest CẦN yield_kg', () {
      final v = validateActivity(
        type: 'harvest',
        parsed: const {'yield_kg': _empty},
        occurredAt: _past,
        now: _now,
      );
      expect(v.fieldErrors['yield_kg'], isNotNull);
    });

    test('harvested_area_ha <= 0 -> lỗi', () {
      final v = validateActivity(
        type: 'harvest',
        parsed: {'yield_kg': _num(5000), 'harvested_area_ha': _num(0)},
        occurredAt: _past,
        now: _now,
      );
      expect(v.fieldErrors['harvested_area_ha'], isNotNull);
    });

    test('sai định dạng -> field error (không tự bỏ qua)', () {
      final v = validateActivity(
        type: 'fuel',
        parsed: {
          'fuel_type': _str('diesel'),
          'amount_liter': const ParsedField(null, 'Số không hợp lệ.'),
        },
        occurredAt: _past,
        now: _now,
      );
      expect(v.fieldErrors['amount_liter'], 'Số không hợp lệ.');
    });
  });

  group('cảnh báo AWD (KHÔNG chặn)', () {
    test('method awd + vụ thiếu drainage count -> warning, hasError = false',
        () {
      final v = validateActivity(
        type: 'irrigation',
        parsed: {'method': _str('awd')},
        occurredAt: _past,
        now: _now,
        activeSeason: _season(drainage: null),
      );
      expect(v.warnings, isNotEmpty);
      expect(v.hasError, isFalse);
    });
    test('vụ IPCC multiple_drainage + thiếu drainage -> vẫn warning', () {
      final v = validateActivity(
        type: 'irrigation',
        parsed: {'method': _str('continuous_flooding')},
        occurredAt: _past,
        now: _now,
        activeSeason: _season(
            regime: IpccWaterRegime.irrigatedMultipleDrainage, drainage: null),
      );
      expect(v.warnings, isNotEmpty);
    });
    test('có drainage count -> không warning', () {
      final v = validateActivity(
        type: 'irrigation',
        parsed: {'method': _str('awd')},
        occurredAt: _past,
        now: _now,
        activeSeason: _season(drainage: 3),
      );
      expect(v.warnings, isEmpty);
    });
  });

  test('7 loại có field spec + khớp cột thật', () {
    expect(kActivityFieldSpecs.keys.toSet(), kActivityTypes.toSet());
    // Không dùng mm ở irrigation.
    final irr = kActivityFieldSpecs['irrigation']!.map((s) => s.key).toSet();
    expect(
        irr,
        containsAll([
          'method',
          'water_volume_m3',
          'water_level_cm',
          'pump_energy_kwh',
          'duration_minutes',
          'total_cost_vnd'
        ]));
    expect(irr.any((k) => k.contains('mm')), isFalse);
  });
}

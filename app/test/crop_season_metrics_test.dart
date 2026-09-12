import 'package:agricarbon_app/models/crop_season_metrics.dart';
import 'package:flutter_test/flutter_test.dart';

/// Response mẫu theo `backend/infrastructure/read_repo.py::metrics()` +
/// `MetricResponse` (openapi.json). KHÔNG phải số Figma — chỉ để test parse.
Map<String, dynamic> _full() => {
      'yield_kg': 4000.0,
      'water_m3': 5680.0,
      'fertilizer_kg': 232.0,
      'total_co2e_kg': 6220.0,
      'water_per_kg': 1.42,
      'fertilizer_per_kg': 0.058,
      'co2e_per_kg': 1.555,
      'cost_per_kg': 4150.0,
      'data_completeness': {
        'water': true,
        'fertilizer': true,
        'cost': true,
        'carbon': true,
      },
    };

void main() {
  group('CropSeasonMetrics.fromJson', () {
    test('parse đủ 8 số + data_completeness', () {
      final m = CropSeasonMetrics.fromJson(_full());
      expect(m.yieldKg, 4000.0);
      expect(m.waterPerKg, 1.42);
      expect(m.fertilizerPerKg, 0.058);
      expect(m.co2ePerKg, 1.555);
      expect(m.costPerKg, 4150.0);
      expect(m.hasWater, isTrue);
      expect(m.hasCarbon, isTrue);
      expect(m.hasYield, isTrue);
    });

    test('null giữ nguyên null — KHÔNG thành 0', () {
      final m = CropSeasonMetrics.fromJson({
        'yield_kg': null,
        'water_m3': null,
        'fertilizer_kg': null,
        'total_co2e_kg': null,
        'water_per_kg': null,
        'fertilizer_per_kg': null,
        'co2e_per_kg': null,
        'cost_per_kg': null,
        'data_completeness': {
          'water': false,
          'fertilizer': false,
          'cost': false,
          'carbon': false,
        },
      });
      expect(m.yieldKg, isNull);
      expect(m.waterPerKg, isNull);
      expect(m.co2ePerKg, isNull);
      expect(m.hasAnything, isFalse);
      expect(m.hasYield, isFalse);
    });

    test('data_completeness thiếu khoá -> false, không nổ', () {
      final m = CropSeasonMetrics.fromJson({'data_completeness': {}});
      expect(m.hasWater, isFalse);
      expect(m.hasCost, isFalse);
    });
  });

  group('cellState (ưu tiên: giá trị > thiếu yield > thiếu dữ liệu)', () {
    test('có số -> value', () {
      final m = CropSeasonMetrics.fromJson(_full());
      for (final k in ResourceMetricKind.values) {
        expect(m.cellState(k), MetricCellState.value, reason: '$k');
      }
    });

    test('thiếu yield -> mọi per-kg là missingYield (kể cả khi có nước/phân)',
        () {
      final j = _full()
        ..['yield_kg'] = null
        ..['water_per_kg'] = null
        ..['fertilizer_per_kg'] = null
        ..['co2e_per_kg'] = null
        ..['cost_per_kg'] = null;
      final m = CropSeasonMetrics.fromJson(j);
      for (final k in ResourceMetricKind.values) {
        expect(m.cellState(k), MetricCellState.missingYield, reason: '$k');
      }
    });

    test(
        'có yield, thiếu dữ liệu nước -> nước = incompleteData; phân vẫn value',
        () {
      final j = _full()
        ..['water_per_kg'] = null
        ..['water_m3'] = null
        ..['data_completeness'] = {
          'water': false,
          'fertilizer': true,
          'cost': true,
          'carbon': true,
        };
      final m = CropSeasonMetrics.fromJson(j);
      expect(m.cellState(ResourceMetricKind.water),
          MetricCellState.incompleteData);
      expect(m.cellState(ResourceMetricKind.fertilizer), MetricCellState.value);
    });
  });

  group('cache round-trip', () {
    test('toCacheJson/fromJson giữ số + gắn _fetched_at', () {
      final m = CropSeasonMetrics.fromJson(_full())
          .copyWith(fetchedAt: DateTime(2026, 9, 10, 8));
      final round = CropSeasonMetrics.fromJson(m.toCacheJson());
      expect(round.co2ePerKg, 1.555);
      expect(round.waterPerKg, 1.42);
      expect(round.fetchedAt, DateTime(2026, 9, 10, 8));
    });

    test('copyWith(fromCache:true) đánh dấu bản cache', () {
      final m = CropSeasonMetrics.fromJson(_full()).copyWith(fromCache: true);
      expect(m.fromCache, isTrue);
      expect(m.co2ePerKg, 1.555);
    });
  });
}

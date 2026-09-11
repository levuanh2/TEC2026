// ⚠️ CHƯA CHẠY LẦN NÀO. Chạy thật: cd app && flutter test test/carbon_result_parsing_test.dart

import 'package:flutter_test/flutter_test.dart';
import 'package:agricarbon_app/models/carbon_result.dart';

void main() {
  test('thiếu sản lượng -> co2ePerKg là null, KHÔNG phải 0', () {
    final json = {
      'crop_season_id': 'c1',
      'water_regime_scenario': 'awd',
      'co2e_total_kg': 1990.49,
      'yield_kg': null,
      'co2e_per_kg': null,
      'breakdown': [],
      'methodology': {'name': 'IPCC 2019 Refinement', 'version': '2019'},
      'ef_config_version': '0.2.0-ipcc-tier1',
      'calculated_at': '2026-09-08T00:00:00Z',
      'warnings': ['Chưa có sản lượng nên chưa tính được CO2e/kg.'],
    };

    final result = CarbonResult.fromJson(json);

    expect(result.totalCo2eKg, 1990.49);
    expect(result.co2ePerKg, isNull);
    expect(result.co2ePerKg, isNot(0)); // chốt bất biến: null khác 0
    expect(result.warnings, isNotEmpty);
  });

  test('có đủ dữ liệu -> parse đúng breakdown nhiều dòng', () {
    final json = {
      'crop_season_id': 'c1',
      'water_regime_scenario': 'as_recorded',
      'co2e_total_kg': 2920.8,
      'yield_kg': 5200.0,
      'co2e_per_kg': 0.5617,
      'breakdown': [
        {
          'source': 'ch4_rice_cultivation',
          'gas': 'ch4',
          'co2e_kg': 2625.0,
          'formula': 'Eq 5.1'
        },
        {
          'source': 'n2o_fertilizer_direct',
          'gas': 'n2o',
          'co2e_kg': 220.8,
          'formula': 'Eq 11.1'
        },
      ],
      'methodology': {'name': 'TEST', 'version': 'test'},
      'ef_config_version': 'TEST-FACTORS-DO-NOT-USE',
      'calculated_at': '2026-09-08T00:00:00Z',
      'warnings': [],
    };

    final result = CarbonResult.fromJson(json);

    expect(result.breakdown, hasLength(2));
    expect(result.breakdown.first.source, 'ch4_rice_cultivation');
    expect(result.co2ePerKg, closeTo(0.5617, 0.0001));
  });
}

/// Kết quả từ POST /v1/carbon/calculate hoặc GET /v1/crop-seasons/{id}/carbon.
/// Khớp `docs/BACKEND_1A.md` §8 — không tự đổi field, đọc đúng response thật.
class CarbonBreakdownEntry {
  final String source;
  final String gas;
  final double coeKg;
  final String formula;

  const CarbonBreakdownEntry({
    required this.source,
    required this.gas,
    required this.coeKg,
    required this.formula,
  });

  factory CarbonBreakdownEntry.fromJson(Map<String, dynamic> json) =>
      CarbonBreakdownEntry(
        source: json['source'] as String? ?? '',
        gas: json['gas'] as String? ?? '',
        coeKg: (json['co2e_kg'] as num?)?.toDouble() ?? 0,
        formula: json['formula'] as String? ?? '',
      );
}

class CarbonResult {
  final String cropSeasonId;
  final String scenario;
  final double? totalCo2eKg;
  final double? yieldKg;
  final double? co2ePerKg; // null = "chưa tính được" — KHÔNG bao giờ hiện là 0
  final List<CarbonBreakdownEntry> breakdown;
  final String methodologyName;
  final String efConfigVersion;
  final String calculatedAt;
  final List<String> warnings;

  const CarbonResult({
    required this.cropSeasonId,
    required this.scenario,
    required this.totalCo2eKg,
    required this.yieldKg,
    required this.co2ePerKg,
    required this.breakdown,
    required this.methodologyName,
    required this.efConfigVersion,
    required this.calculatedAt,
    required this.warnings,
  });

  factory CarbonResult.fromJson(Map<String, dynamic> json) => CarbonResult(
        cropSeasonId: json['crop_season_id'] as String? ?? '',
        scenario: json['water_regime_scenario'] as String? ??
            json['scenario'] as String? ??
            'as_recorded',
        totalCo2eKg: (json['co2e_total_kg'] as num?)?.toDouble(),
        yieldKg: (json['yield_kg'] as num?)?.toDouble(),
        co2ePerKg: (json['co2e_per_kg'] as num?)?.toDouble(),
        breakdown: ((json['breakdown'] as List?) ?? [])
            .map((e) => CarbonBreakdownEntry.fromJson(e as Map<String, dynamic>))
            .toList(),
        methodologyName:
            (json['methodology'] as Map<String, dynamic>?)?['name'] as String? ?? '',
        efConfigVersion: json['ef_config_version'] as String? ?? '',
        calculatedAt: json['calculated_at'] as String? ?? '',
        warnings:
            ((json['warnings'] as List?) ?? []).map((e) => e.toString()).toList(),
      );
}

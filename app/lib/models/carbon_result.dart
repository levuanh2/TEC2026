/// Kết quả từ `POST /v1/carbon/calculate` hoặc
/// `GET /v1/crop-seasons/{id}/carbon`. Đọc ĐÚNG field backend trả — KHÔNG tự
/// đổi tên, KHÔNG tự tính. `docs/FRONTEND_API_CONTRACT.md` §1.
class CarbonBreakdownEntry {
  const CarbonBreakdownEntry({
    required this.source,
    required this.gas,
    required this.co2eKg,
    required this.formula,
  });

  /// Mã nguồn phát thải THẬT của backend — giữ nguyên, không dịch ở model.
  final String source;
  final String gas;
  final double co2eKg;
  final String formula;

  factory CarbonBreakdownEntry.fromJson(Map<String, dynamic> json) =>
      CarbonBreakdownEntry(
        source: json['source'] as String? ?? '',
        gas: json['gas'] as String? ?? '',
        co2eKg: (json['co2e_kg'] as num?)?.toDouble() ?? 0,
        formula: json['formula'] as String? ?? '',
      );

  Map<String, dynamic> toJson() => {
        'source': source,
        'gas': gas,
        'co2e_kg': co2eKg,
        'formula': formula,
      };
}

class CarbonResult {
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
    this.waterRegimeApplied,
    this.methodologyVersion = '',
    this.methodologyTier,
    this.engineVersion = '',
    this.fetchedAt,
    this.fromCache = false,
  });

  final String cropSeasonId;

  /// `awd` | `continuous_flooding` | `as_recorded`.
  final String scenario;

  /// Chế độ nước IPCC backend áp dụng (`irrigated_multiple_drainage`, ...).
  final String? waterRegimeApplied;

  final double? totalCo2eKg;
  final double? yieldKg;

  /// `null` = đã tính tổng nhưng CHƯA có sản lượng → UI hiện dòng chữ, KHÔNG "0".
  final double? co2ePerKg;

  final List<CarbonBreakdownEntry> breakdown;
  final String methodologyName;
  final String methodologyVersion;
  final int? methodologyTier;
  final String efConfigVersion;
  final String engineVersion;

  /// Mốc backend TÍNH (ISO-8601, giữ nguyên chuỗi server).
  final String calculatedAt;
  final List<String> warnings;

  /// Mốc client LẤY VỀ / đọc từ cache. `null` khi chưa gắn.
  final DateTime? fetchedAt;

  /// `true` khi đọc từ cache offline (UI phải phân biệt với số vừa lấy live).
  final bool fromCache;

  /// Tổng các dòng breakdown — để đối chiếu với [totalCo2eKg]. KHÔNG dùng để
  /// thay [totalCo2eKg]; chỉ để cảnh báo khi lệch.
  double get breakdownSum => breakdown.fold(0, (a, b) => a + b.co2eKg);

  /// % của một dòng breakdown = `co2e_kg / total`. CHỈ khi `total > 0`.
  double? shareOf(CarbonBreakdownEntry e) {
    final t = totalCo2eKg;
    if (t == null || t <= 0) return null;
    return e.co2eKg / t;
  }

  /// breakdown lệch total quá 1% (và total > 0) → UI cảnh báo, KHÔNG sửa số.
  bool get breakdownMismatch {
    final t = totalCo2eKg;
    if (t == null || t <= 0 || breakdown.isEmpty) return false;
    return (breakdownSum - t).abs() / t > 0.01;
  }

  CarbonResult copyWith({DateTime? fetchedAt, bool? fromCache}) => CarbonResult(
        cropSeasonId: cropSeasonId,
        scenario: scenario,
        waterRegimeApplied: waterRegimeApplied,
        totalCo2eKg: totalCo2eKg,
        yieldKg: yieldKg,
        co2ePerKg: co2ePerKg,
        breakdown: breakdown,
        methodologyName: methodologyName,
        methodologyVersion: methodologyVersion,
        methodologyTier: methodologyTier,
        efConfigVersion: efConfigVersion,
        engineVersion: engineVersion,
        calculatedAt: calculatedAt,
        warnings: warnings,
        fetchedAt: fetchedAt ?? this.fetchedAt,
        fromCache: fromCache ?? this.fromCache,
      );

  factory CarbonResult.fromJson(Map<String, dynamic> json) {
    final methodology = json['methodology'];
    final m = methodology is Map ? methodology : const {};
    return CarbonResult(
      cropSeasonId: json['crop_season_id'] as String? ?? '',
      scenario: json['water_regime_scenario'] as String? ??
          json['scenario'] as String? ??
          'as_recorded',
      waterRegimeApplied: json['water_regime_applied'] as String?,
      // Backend trả cả `co2e_total_kg` (SRS) lẫn `total_co2e_kg` (to_dict) —
      // đọc field nào cũng được.
      totalCo2eKg: (json['co2e_total_kg'] as num?)?.toDouble() ??
          (json['total_co2e_kg'] as num?)?.toDouble(),
      yieldKg: (json['yield_kg'] as num?)?.toDouble(),
      co2ePerKg: (json['co2e_per_kg'] as num?)?.toDouble(),
      breakdown: [
        for (final e in (json['breakdown'] as List?) ?? const [])
          if (e is Map<String, dynamic>) CarbonBreakdownEntry.fromJson(e),
      ],
      methodologyName: m['name'] as String? ?? '',
      methodologyVersion: m['version']?.toString() ?? '',
      methodologyTier: (m['tier'] as num?)?.toInt(),
      efConfigVersion: json['ef_config_version'] as String? ?? '',
      engineVersion: json['engine_version'] as String? ?? '',
      calculatedAt: json['calculated_at'] as String? ?? '',
      warnings: [
        for (final w in (json['warnings'] as List?) ?? const []) w.toString(),
      ],
      fetchedAt: DateTime.tryParse(json['_fetched_at'] as String? ?? ''),
      fromCache: json['_from_cache'] == true,
    );
  }

  /// Serialize để cache offline — round-trip đầy đủ qua [CarbonResult.fromJson].
  Map<String, dynamic> toCacheJson() => {
        'crop_season_id': cropSeasonId,
        'water_regime_scenario': scenario,
        'water_regime_applied': waterRegimeApplied,
        'total_co2e_kg': totalCo2eKg,
        'yield_kg': yieldKg,
        'co2e_per_kg': co2ePerKg,
        'breakdown': [for (final b in breakdown) b.toJson()],
        'methodology': {
          'name': methodologyName,
          'version': methodologyVersion,
          if (methodologyTier != null) 'tier': methodologyTier,
        },
        'ef_config_version': efConfigVersion,
        'engine_version': engineVersion,
        'calculated_at': calculatedAt,
        'warnings': warnings,
        '_fetched_at': (fetchedAt ?? DateTime.now()).toIso8601String(),
        '_from_cache': true,
      };
}

/// `GET /health` — CHỈ dùng để biết backend đã đủ điều kiện tính CHÍNH THỨC
/// chưa. `carbonProductionReady == false` là trạng thái ĐÚNG hiện tại (GWP chưa
/// xác minh, OI-05) — không phải lỗi client cần sửa.
class CarbonHealth {
  const CarbonHealth({
    required this.status,
    required this.carbonProductionReady,
    required this.mrvCompliant,
    required this.engineVersion,
    required this.efConfigVersion,
    required this.methodologyName,
    required this.note,
  });

  final String status;
  final bool carbonProductionReady;
  final bool mrvCompliant;
  final String engineVersion;
  final String efConfigVersion;
  final String methodologyName;
  final String note;

  factory CarbonHealth.fromJson(Map<String, dynamic> json) {
    final m = json['methodology'];
    return CarbonHealth(
      status: json['status'] as String? ?? '',
      carbonProductionReady: json['carbon_production_ready'] == true,
      mrvCompliant: json['mrv_compliant'] == true,
      engineVersion: json['engine_version'] as String? ?? '',
      efConfigVersion: json['ef_config_version'] as String? ?? '',
      methodologyName: (m is Map ? m['name'] : null) as String? ?? '',
      note: json['note'] as String? ?? '',
    );
  }
}

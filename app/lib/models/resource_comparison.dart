/// Dữ liệu để so sánh vụ với một nhóm tham chiếu (module 04 — `coop_benchmark`).
///
/// `MetricResponse` từ `GET /v1/crop-seasons/{id}/metrics` HIỆN **không** trả
/// nhóm so sánh nào, và OpenAPI **không** có `/v1/plots/{id}/efficiency`. Vì vậy
/// mặc định là [ResourceComparison.unavailable] → UI hiện "Chưa đủ dữ liệu để so
/// sánh". KHÔNG tự bịa benchmark. [fromJson] để sẵn cho khi backend bổ sung.
///
/// Chỉ render khi ĐỦ CẢ BỐN: nhóm so sánh, thời kỳ, nguồn, và dữ liệu đủ.
class ResourceComparison {
  const ResourceComparison({
    this.group,
    this.period,
    this.source,
    this.dataSufficient = false,
    this.co2ePerKg,
    this.waterPerKg,
    this.fertilizerPerKg,
    this.costPerKg,
  });

  /// Không có gì để so sánh (trường hợp hiện tại của toàn bộ API).
  const ResourceComparison.unavailable() : this();

  /// Nhóm hộ/lô so sánh (ví dụ "các hộ trong cùng HTX").
  final String? group;

  /// Thời kỳ dữ liệu so sánh (ví dụ "cùng vụ trong năm").
  final String? period;

  /// Nguồn benchmark (ví dụ "trung bình HTX", "dải tham chiếu vùng").
  final String? source;

  /// Dữ liệu nhóm so sánh đã đủ để tin cậy.
  final bool dataSufficient;

  final double? co2ePerKg;
  final double? waterPerKg;
  final double? fertilizerPerKg;
  final double? costPerKg;

  static bool _filled(String? s) => s != null && s.trim().isNotEmpty;

  /// Đủ điều kiện hiển thị so sánh: nhóm + thời kỳ + nguồn + dữ liệu đủ.
  bool get isRenderable =>
      _filled(group) && _filled(period) && _filled(source) && dataSufficient;

  static double? _numOrNull(Object? v) => v is num ? v.toDouble() : null;

  factory ResourceComparison.fromJson(Map<String, dynamic> json) {
    final bench = json['coop_benchmark'] ?? json['benchmark'] ?? json;
    final b = bench is Map ? bench : const <String, dynamic>{};
    return ResourceComparison(
      group: (json['group'] ?? b['group']) as String?,
      period: (json['period'] ?? b['period']) as String?,
      source: (b['source'] ?? json['source']) as String?,
      dataSufficient: (json['data_sufficient'] ?? b['data_sufficient']) == true,
      co2ePerKg: _numOrNull(b['co2e_kg_per_kg'] ?? b['co2e_per_kg']),
      waterPerKg: _numOrNull(b['water_litre_per_kg'] ?? b['water_per_kg']),
      fertilizerPerKg:
          _numOrNull(b['fertilizer_kg_per_kg'] ?? b['fertilizer_per_kg']),
      costPerKg: _numOrNull(b['cost_vnd_per_kg'] ?? b['cost_per_kg']),
    );
  }
}

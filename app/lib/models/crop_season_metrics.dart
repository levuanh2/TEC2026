/// Chỉ số tổng hợp của một vụ canh tác — ánh xạ 1-1 `MetricResponse` từ
/// `GET /v1/crop-seasons/{crop_season_id}/metrics` (xem `docs/API_FOR_FLUTTER.md`
/// §5, `backend/schemas.py::MetricResponse`, `backend/infrastructure/read_repo.py`).
///
/// Đơn vị chuẩn: nước = m³, phân bón = kg, sản lượng = kg, CO2e = kg, chi phí =
/// VND. Mọi trường số là `double?` — `null` nghĩa là **chưa đủ dữ liệu để tính**,
/// TUYỆT ĐỐI không hiểu là `0`. KHÔNG tự tính lại chỉ số nào backend đã trả.
class CropSeasonMetrics {
  const CropSeasonMetrics({
    this.yieldKg,
    this.waterM3,
    this.fertilizerKg,
    this.totalCo2eKg,
    this.waterPerKg,
    this.fertilizerPerKg,
    this.co2ePerKg,
    this.costPerKg,
    this.dataCompleteness = const {},
    this.fetchedAt,
    this.fromCache = false,
  });

  final double? yieldKg;
  final double? waterM3;
  final double? fertilizerKg;
  final double? totalCo2eKg;
  final double? waterPerKg;
  final double? fertilizerPerKg;
  final double? co2ePerKg;
  final double? costPerKg;

  /// `{water, fertilizer, cost, carbon}` → đủ dữ liệu loại đó hay chưa
  /// (`data_completeness` từ backend). Không suy diễn khoá khác.
  final Map<String, bool> dataCompleteness;

  /// Lúc client lấy về (điền khi ghi cache). Hiển thị kèm nhãn "số đã lưu".
  final DateTime? fetchedAt;

  /// `true` khi bản này đọc từ cache local (offline / lỗi mạng).
  final bool fromCache;

  bool get hasWater => dataCompleteness['water'] ?? false;
  bool get hasFertilizer => dataCompleteness['fertilizer'] ?? false;
  bool get hasCost => dataCompleteness['cost'] ?? false;
  bool get hasCarbon => dataCompleteness['carbon'] ?? false;

  /// Có sản lượng thu hoạch hay chưa — quyết định mọi chỉ số "trên mỗi kg".
  bool get hasYield => yieldKg != null;

  /// Còn ít nhất một chỉ số per-kg có số thật.
  bool get hasAnyPerKg =>
      waterPerKg != null ||
      fertilizerPerKg != null ||
      co2ePerKg != null ||
      costPerKg != null;

  /// Còn ít nhất một số bất kỳ (tổng hoặc per-kg) để hiển thị.
  bool get hasAnything =>
      hasAnyPerKg ||
      yieldKg != null ||
      waterM3 != null ||
      fertilizerKg != null ||
      totalCo2eKg != null;

  double? perKgValue(ResourceMetricKind kind) => switch (kind) {
        ResourceMetricKind.water => waterPerKg,
        ResourceMetricKind.fertilizer => fertilizerPerKg,
        ResourceMetricKind.co2e => co2ePerKg,
        ResourceMetricKind.cost => costPerKg,
      };

  double? totalValue(ResourceMetricKind kind) => switch (kind) {
        ResourceMetricKind.water => waterM3,
        ResourceMetricKind.fertilizer => fertilizerKg,
        ResourceMetricKind.co2e => totalCo2eKg,
        ResourceMetricKind.cost => null, // backend không trả tổng chi phí
      };

  bool resourceComplete(ResourceMetricKind kind) => switch (kind) {
        ResourceMetricKind.water => hasWater,
        ResourceMetricKind.fertilizer => hasFertilizer,
        ResourceMetricKind.co2e => hasCarbon,
        ResourceMetricKind.cost => hasCost,
      };

  /// Trạng thái ô hiển thị của một chỉ số per-kg. Thứ tự ưu tiên:
  /// có số → hiện số; thiếu SẢN LƯỢNG → "Chưa có sản lượng"; thiếu dữ liệu loại
  /// đó → "Chưa đủ dữ liệu". Không bao giờ ra "0".
  MetricCellState cellState(ResourceMetricKind kind) {
    if (perKgValue(kind) != null) return MetricCellState.value;
    if (!hasYield) return MetricCellState.missingYield;
    return MetricCellState.incompleteData;
  }

  static double? _numOrNull(Object? v) => v is num ? v.toDouble() : null;

  factory CropSeasonMetrics.fromJson(Map<String, dynamic> json) {
    final dc = <String, bool>{};
    final raw = json['data_completeness'];
    if (raw is Map) {
      raw.forEach((k, v) => dc[k.toString()] = v == true);
    }
    return CropSeasonMetrics(
      yieldKg: _numOrNull(json['yield_kg']),
      waterM3: _numOrNull(json['water_m3']),
      fertilizerKg: _numOrNull(json['fertilizer_kg']),
      totalCo2eKg: _numOrNull(json['total_co2e_kg']),
      waterPerKg: _numOrNull(json['water_per_kg']),
      fertilizerPerKg: _numOrNull(json['fertilizer_per_kg']),
      co2ePerKg: _numOrNull(json['co2e_per_kg']),
      costPerKg: _numOrNull(json['cost_per_kg']),
      dataCompleteness: dc,
      fetchedAt: switch (json['_fetched_at']) {
        final String s => DateTime.tryParse(s),
        _ => null,
      },
      fromCache: json['_from_cache'] == true,
    );
  }

  CropSeasonMetrics copyWith({DateTime? fetchedAt, bool? fromCache}) =>
      CropSeasonMetrics(
        yieldKg: yieldKg,
        waterM3: waterM3,
        fertilizerKg: fertilizerKg,
        totalCo2eKg: totalCo2eKg,
        waterPerKg: waterPerKg,
        fertilizerPerKg: fertilizerPerKg,
        co2ePerKg: co2ePerKg,
        costPerKg: costPerKg,
        dataCompleteness: dataCompleteness,
        fetchedAt: fetchedAt ?? this.fetchedAt,
        fromCache: fromCache ?? this.fromCache,
      );

  /// Lưu vào bảng `meta` (cache theo user + server id vụ). `fromJson` đọc lại
  /// đúng khoá này nên round-trip an toàn. `_fetched_at` để hiển thị "số đã lưu".
  Map<String, dynamic> toCacheJson() => {
        'yield_kg': yieldKg,
        'water_m3': waterM3,
        'fertilizer_kg': fertilizerKg,
        'total_co2e_kg': totalCo2eKg,
        'water_per_kg': waterPerKg,
        'fertilizer_per_kg': fertilizerPerKg,
        'co2e_per_kg': co2ePerKg,
        'cost_per_kg': costPerKg,
        'data_completeness': dataCompleteness,
        '_fetched_at': (fetchedAt ?? DateTime.now()).toIso8601String(),
      };
}

/// Bốn chỉ số hiệu suất "trên mỗi kg sản phẩm" (module 04).
enum ResourceMetricKind { water, fertilizer, co2e, cost }

/// Trạng thái một ô chỉ số per-kg trên dashboard.
enum MetricCellState {
  /// Có số thật → hiển thị giá trị.
  value,

  /// Thiếu sản lượng thu hoạch → per-kg không tính được.
  missingYield,

  /// Có sản lượng nhưng dữ liệu loại tài nguyên đó chưa đủ.
  incompleteData,
}

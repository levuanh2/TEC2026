/// Carbon readiness — đọc NGUYÊN từ `GET /v1/crop-seasons/{id}/carbon/readiness`
/// (`backend/carbon/readiness.py`). App KHÔNG tự suy ra thiếu gì: danh sách,
/// câu chữ tiếng Việt và "sửa ở đâu" (`flow`) đều do máy chủ quyết định, cùng
/// nguồn Farmer Web dùng.
library;

/// Chỗ người dùng bổ sung một đầu vào — giá trị khớp hằng `FLOW_*` ở backend.
enum ReadinessFlow {
  /// Thông tin phương pháp tính của vụ (chế độ nước, số ngày canh tác).
  seasonMethodology('carbon_methodology'),

  /// Sửa đúng bản ghi hoạt động nêu trong `records`.
  activity('activity'),

  /// Diện tích thửa — không phải một ô trong nhật ký.
  plot('plot'),

  /// Giới hạn của bộ hệ số (vd. nhiên liệu): nhập thêm cũng không giải quyết.
  factorUnavailable('factor_unavailable'),

  /// Flow máy chủ mới thêm mà app chưa biết — hiển thị như thông tin, không nút.
  unknown('');

  const ReadinessFlow(this.wire);
  final String wire;

  static ReadinessFlow fromWire(String? value) => ReadinessFlow.values
      .firstWhere((f) => f.wire == value && f != unknown, orElse: () => unknown);
}

/// Một bản ghi cụ thể mà mục thiếu nhắc tới (id hoạt động trên máy chủ).
class ReadinessRecord {
  const ReadinessRecord({required this.activityId, this.occurredOn, this.label});
  final String activityId;
  final String? occurredOn;
  final String? label;

  factory ReadinessRecord.fromJson(Map<String, dynamic> json) => ReadinessRecord(
        activityId: json['activity_id'] as String,
        occurredOn: json['occurred_on'] as String?,
        label: json['label'] as String?,
      );
}

class MissingCarbonInput {
  const MissingCarbonInput({
    required this.code,
    required this.label,
    required this.detail,
    required this.flow,
    required this.blocking,
    this.activityType,
    this.records = const [],
  });

  final String code;
  final String label;
  final String detail;
  final ReadinessFlow flow;
  final bool blocking;
  final String? activityType;
  final List<ReadinessRecord> records;

  /// Người dùng có thể tự bổ sung bằng cách nhập dữ liệu hay không. Giới hạn
  /// của bộ hệ số thì không — app không được giả vờ có nút "Sửa ngay".
  bool get userFixable =>
      flow == ReadinessFlow.seasonMethodology ||
      flow == ReadinessFlow.activity ||
      flow == ReadinessFlow.plot;

  factory MissingCarbonInput.fromJson(Map<String, dynamic> json) =>
      MissingCarbonInput(
        code: json['code'] as String,
        label: json['label'] as String? ?? '',
        detail: json['detail'] as String? ?? '',
        flow: ReadinessFlow.fromWire(json['flow'] as String?),
        blocking: json['blocking'] as bool? ?? true,
        activityType: json['activity_type'] as String?,
        records: [
          for (final r in (json['records'] as List?) ?? const [])
            if (r is Map<String, dynamic>) ReadinessRecord.fromJson(r),
        ],
      );
}

class CarbonReadiness {
  const CarbonReadiness({
    required this.canCalculate,
    required this.blockingCount,
    required this.missingInputs,
  });

  final bool canCalculate;
  final int blockingCount;
  final List<MissingCarbonInput> missingInputs;

  List<MissingCarbonInput> get blocking =>
      [for (final m in missingInputs) if (m.blocking) m];
  List<MissingCarbonInput> get nonBlocking =>
      [for (final m in missingInputs) if (!m.blocking) m];

  factory CarbonReadiness.fromJson(Map<String, dynamic> json) => CarbonReadiness(
        canCalculate: json['can_calculate'] as bool? ?? false,
        blockingCount: (json['blocking_count'] as num?)?.toInt() ?? 0,
        missingInputs: [
          for (final m in (json['missing_inputs'] as List?) ?? const [])
            if (m is Map<String, dynamic>) MissingCarbonInput.fromJson(m),
        ],
      );
}

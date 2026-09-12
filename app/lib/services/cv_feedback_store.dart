import 'dart:convert';

import '../db/local_database.dart';
import 'cv_inference_service.dart';

/// Lưu phản hồi "Xác nhận đúng" / "Chỉnh lại" của nông dân về kết quả nhận biết
/// bệnh lá — CHỈ trên máy.
///
/// KHÔNG có bảng server cho việc này (backend chưa có endpoint CV). Dùng bảng
/// `meta` (key/value theo user, giống `sync.wifi_only`), key
/// `cv.feedback.<cropSeasonClientId>` → mảng JSON. Không tạo endpoint, không
/// ghi vào bảng không tồn tại.
class CvFeedbackStore {
  CvFeedbackStore(this._db);

  final LocalDatabase _db;

  static String _key(String cropSeasonClientId) =>
      'cv.feedback.$cropSeasonClientId';

  /// Ghi thêm một phản hồi cho vụ. Nuốt mọi lỗi ghi (không chặn UI) nhưng vẫn
  /// giữ đúng thứ tự nối tiếp.
  Future<void> add(String cropSeasonClientId, CvFeedbackEntry entry) async {
    try {
      final current = await list(cropSeasonClientId);
      final next = [...current, entry];
      await _db.setMeta(
        _key(cropSeasonClientId),
        jsonEncode(next.map((e) => e.toJson()).toList()),
      );
    } catch (_) {
      // Local-only, không nghiêm trọng — bỏ qua.
    }
  }

  /// Đọc lại toàn bộ phản hồi đã lưu cho vụ (cũ → mới). Lỗi đọc → danh sách rỗng.
  Future<List<CvFeedbackEntry>> list(String cropSeasonClientId) async {
    try {
      final raw = await _db.getMeta(_key(cropSeasonClientId));
      if (raw == null || raw.isEmpty) return const [];
      final decoded = jsonDecode(raw);
      if (decoded is! List) return const [];
      return decoded
          .whereType<Map>()
          .map((m) => CvFeedbackEntry.fromJson(m.cast<String, dynamic>()))
          .toList();
    } catch (_) {
      return const [];
    }
  }
}

/// Nông dân đánh giá kết quả model thế nào.
enum CvFeedbackVerdict {
  /// "Xác nhận đúng".
  confirmed,

  /// "Chỉnh lại" — nông dân chọn một nhãn khác.
  corrected,
}

/// Một dòng phản hồi.
class CvFeedbackEntry {
  CvFeedbackEntry({
    required this.at,
    required this.verdict,
    required this.modelLabel,
    required this.confidence,
    required this.isUncertain,
    this.imagePath,
    this.correctedLabel,
  });

  /// Lúc nông dân bấm nút.
  final DateTime at;
  final CvFeedbackVerdict verdict;

  /// Nhãn model đưa ra (`wire`), `null` khi model chưa cấu hình (không nên có
  /// phản hồi trong trường hợp đó, nhưng vẫn round-trip an toàn).
  final String? modelLabel;
  final double? confidence;
  final bool isUncertain;

  /// Đường dẫn bản sao ảnh trên máy (nếu còn).
  final String? imagePath;

  /// Nhãn nông dân chọn khi "Chỉnh lại" (`wire`).
  final String? correctedLabel;

  Map<String, dynamic> toJson() => {
        'at': at.toIso8601String(),
        'verdict': verdict.name,
        if (modelLabel != null) 'model_label': modelLabel,
        if (confidence != null) 'confidence': confidence,
        'is_uncertain': isUncertain,
        if (imagePath != null) 'image_path': imagePath,
        if (correctedLabel != null) 'corrected_label': correctedLabel,
      };

  static CvFeedbackEntry fromJson(Map<String, dynamic> m) => CvFeedbackEntry(
        at: DateTime.tryParse(m['at'] as String? ?? '') ??
            DateTime.fromMillisecondsSinceEpoch(0),
        verdict: CvFeedbackVerdict.values.firstWhere(
          (v) => v.name == m['verdict'],
          orElse: () => CvFeedbackVerdict.confirmed,
        ),
        modelLabel: m['model_label'] as String?,
        confidence: (m['confidence'] as num?)?.toDouble(),
        isUncertain: m['is_uncertain'] as bool? ?? false,
        imagePath: m['image_path'] as String?,
        correctedLabel: m['corrected_label'] as String?,
      );

  /// Tạo từ một kết quả model + lựa chọn của nông dân.
  factory CvFeedbackEntry.fromResult({
    required CvInferenceResult result,
    required CvFeedbackVerdict verdict,
    String? imagePath,
    LeafDiseaseLabel? correctedLabel,
    DateTime? at,
  }) =>
      CvFeedbackEntry(
        at: at ?? DateTime.now(),
        verdict: verdict,
        modelLabel: result.label.wire,
        confidence: result.confidence,
        isUncertain: result.isUncertain,
        imagePath: imagePath,
        correctedLabel: correctedLabel?.wire,
      );
}

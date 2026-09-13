/// Khuyến nghị điều chỉnh canh tác (module 05 — AI Recommendation).
///
/// **OpenAPI hiện KHÔNG có endpoint recommendation.** Vì vậy bản chạy thật dùng
/// [UnavailableRecommendationRepository]: UI hiện "chưa được cấu hình", KHÔNG
/// dựng khuyến nghị giả / fixture. Khi backend thêm endpoint, cắm một
/// implementation thật qua [RecommendationRepository] — UI không đổi. Fake chỉ
/// dùng trong test.
library;

/// Một khuyến nghị. Hợp lệ (được render) khi có ĐỦ: nội dung tiếng Việt,
/// `co2e_reduction_kg`, `cost_saving_vnd`, `compared_to`, và nguồn/benchmark
/// (module 05 §3.3–3.4, FR-1b-08, FR-1b-09).
class Recommendation {
  const Recommendation({
    required this.messageVi,
    this.co2eReductionKg,
    this.costSavingVnd,
    this.comparedTo,
    this.source,
    this.trigger,
  });

  /// Nội dung tiếng Việt cho nông dân.
  final String messageVi;

  /// Ước tính giảm phát thải (kg CO₂e). `null` = chưa tính được impact.
  final double? co2eReductionKg;

  /// Ước tính tiết kiệm chi phí (VND). `null` = chưa tính được impact.
  final int? costSavingVnd;

  /// So với cái gì (ví dụ "trung bình các hộ trong HTX, cùng vụ").
  final String? comparedTo;

  /// Nguồn benchmark / cơ sở khuyến nghị.
  final String? source;

  /// Mã luật sinh khuyến nghị (ví dụ `fertilizer_n_above_benchmark`).
  final String? trigger;

  /// Có ước tính impact đầy đủ — thiếu thì KHÔNG render như khuyến nghị hợp lệ.
  bool get hasImpact => co2eReductionKg != null && costSavingVnd != null;

  /// Có nêu rõ so với cái gì + nguồn — thiếu thì KHÔNG được tuyên bố benchmark.
  bool get hasBenchmark =>
      (comparedTo?.trim().isNotEmpty ?? false) &&
      (source?.trim().isNotEmpty ?? false);

  bool get isValid => messageVi.trim().isNotEmpty && hasImpact && hasBenchmark;

  static double? _numOrNull(Object? v) => v is num ? v.toDouble() : null;

  factory Recommendation.fromJson(Map<String, dynamic> json) {
    final impactRaw = json['impact'];
    final impact = impactRaw is Map ? impactRaw : const <String, dynamic>{};
    final co2e =
        _numOrNull(json['co2e_reduction_kg'] ?? impact['co2e_reduction_kg']);
    final cost =
        _numOrNull(json['cost_saving_vnd'] ?? impact['cost_saving_vnd']);
    return Recommendation(
      messageVi: (json['message_vi'] ?? json['messageVi'] ?? '') as String,
      co2eReductionKg: co2e,
      costSavingVnd: cost?.round(),
      comparedTo: json['compared_to'] as String?,
      source: (json['source'] ?? json['benchmark']) as String?,
      trigger: json['trigger'] as String?,
    );
  }
}

/// Ném khi gọi [RecommendationRepository.forCropSeason] lúc chưa có endpoint.
class RecommendationUnavailable implements Exception {
  const RecommendationUnavailable();

  @override
  String toString() =>
      'RecommendationUnavailable: chưa có endpoint khuyến nghị';
}

/// Nguồn khuyến nghị. `isAvailable == false` ⇒ UI hiện "chưa cấu hình".
abstract class RecommendationRepository {
  bool get isAvailable;

  /// Trả danh sách khuyến nghị THÔ cho vụ (dùng SERVER id). Caller tự lọc
  /// `.where((r) => r.isValid)` trước khi render.
  Future<List<Recommendation>> forCropSeason(String cropSeasonServerId);
}

/// Bản chạy thật khi CHƯA có endpoint — không bao giờ trả fixture/mock.
class UnavailableRecommendationRepository implements RecommendationRepository {
  const UnavailableRecommendationRepository();

  @override
  bool get isAvailable => false;

  @override
  Future<List<Recommendation>> forCropSeason(String cropSeasonServerId) async {
    throw const RecommendationUnavailable();
  }
}

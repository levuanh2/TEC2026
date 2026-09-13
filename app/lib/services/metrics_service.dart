import '../models/crop_season_metrics.dart';
import 'read_api.dart';

/// `GET /v1/crop-seasons/{crop_season_id}/metrics` — chỉ số tài nguyên/kết quả
/// tổng hợp của một vụ (nước, phân bón, sản lượng, CO2e, chi phí).
///
/// LUÔN dùng SERVER id của vụ. Ném [ReadApiException] khi lỗi (401/403 →
/// `isUnauthorized`), để [HomeController] rẽ nhánh giống các route đọc khác.
class MetricsService {
  MetricsService(this._api);
  final ReadApi _api;

  Future<CropSeasonMetrics> fetchForCropSeason(
      String cropSeasonServerId) async {
    final json =
        await _api.getJson('/v1/crop-seasons/$cropSeasonServerId/metrics');
    return CropSeasonMetrics.fromJson(json);
  }
}

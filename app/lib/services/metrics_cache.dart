import 'dart:convert';

import '../db/local_database.dart';
import '../models/crop_season_metrics.dart';

/// Cache [CropSeasonMetrics] theo **user + cropSeason server id**.
///
/// - user: tự động — `LocalDatabase` là file riêng mỗi user.
/// - dùng chung khoá `home.metrics.<sid>` với `HomeController` để màn Trang chủ
///   và Resource Dashboard xem cùng một bản offline (một nguồn sự thật local).
/// - đọc được khi offline; [read] gắn `fromCache = true`.
/// - **KHÔNG xoá cache khi refresh lỗi** — caller giữ bản cũ hiển thị kèm nhãn.
class MetricsCache {
  MetricsCache(this._db);
  final LocalDatabase _db;

  static String keyFor(String cropSeasonServerId) =>
      'home.metrics.$cropSeasonServerId';

  Future<void> write(String cropSeasonServerId, CropSeasonMetrics m) async {
    try {
      await _db.setMeta(
        keyFor(cropSeasonServerId),
        jsonEncode(
          m.copyWith(fetchedAt: m.fetchedAt ?? DateTime.now()).toCacheJson(),
        ),
      );
    } catch (_) {
      // DB có thể vừa đóng (đổi tài khoản) — bỏ qua, không làm sập luồng UI.
    }
  }

  Future<CropSeasonMetrics?> read(String cropSeasonServerId) async {
    try {
      final raw = await _db.getMeta(keyFor(cropSeasonServerId));
      if (raw == null || raw.isEmpty) return null;
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) return null;
      return CropSeasonMetrics.fromJson(decoded).copyWith(fromCache: true);
    } catch (_) {
      return null;
    }
  }
}

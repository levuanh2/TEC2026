import 'dart:convert';

import '../db/local_database.dart';
import '../models/carbon_result.dart';

/// Cache kết quả Carbon theo **user + cropSeason server id + scenario**.
///
/// - user: tự động — `LocalDatabase` là file riêng mỗi user.
/// - lưu FULL [CarbonResult] (kèm `calculated_at` của server và `_fetched_at`
///   của client) trong bảng `meta`.
/// - đọc được khi offline; [read] gắn `fromCache = true`.
/// - **KHÔNG xoá cache khi refresh lỗi** — caller giữ bản cũ.
class CarbonCache {
  CarbonCache(this._db);
  final LocalDatabase _db;

  static String _key(String cropSeasonServerId, String scenario) =>
      'carbon.v2.$cropSeasonServerId.$scenario';

  Future<void> write(
    String cropSeasonServerId,
    String scenario,
    CarbonResult result,
  ) async {
    try {
      await _db.setMeta(
        _key(cropSeasonServerId, scenario),
        jsonEncode(result.toCacheJson()),
      );
    } catch (_) {
      // DB có thể vừa đóng (đổi tài khoản) — bỏ qua, không làm sập luồng UI.
    }
  }

  Future<CarbonResult?> read(
    String cropSeasonServerId,
    String scenario,
  ) async {
    try {
      final raw = await _db.getMeta(_key(cropSeasonServerId, scenario));
      if (raw == null || raw.isEmpty) return null;
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) return null;
      return CarbonResult.fromJson(decoded).copyWith(fromCache: true);
    } catch (_) {
      return null;
    }
  }
}

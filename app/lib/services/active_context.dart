import 'package:flutter/foundation.dart';

import '../db/local_database.dart';
import '../models/crop_season.dart';
import '../models/farm.dart';
import '../models/plot.dart';

/// "Đang làm ở đâu" — Farm / Plot / Crop Season đang chọn. Lưu trong DB riêng
/// của user (`active_context`), nên tự động tách theo user.
///
/// Bất biến:
///  - Chọn Plot phải thuộc Farm đang chọn; chọn Crop Season phải thuộc Plot đang
///    chọn. Đổi cấp trên → xoá cấp dưới (tránh ghi Activity sang nhầm vụ).
///  - Nếu entity không còn trong cache local (bị xoá / mất quyền sau khi kéo dữ
///    liệu) → [revalidate] xoá an toàn.
///  - Carbon LUÔN dùng [cropSeasonServerId] (chưa đồng bộ → null, không tính được).
class ActiveContext extends ChangeNotifier {
  LocalDatabase? _db;

  Farm? _farm;
  Plot? _plot;
  CropSeason? _cropSeason;

  Farm? get farm => _farm;
  Plot? get plot => _plot;
  CropSeason? get cropSeason => _cropSeason;

  String? get farmId => _farm?.id;
  String? get plotClientId => _plot?.clientId;
  String? get cropSeasonClientId => _cropSeason?.clientId;

  /// Server id của vụ đang chọn — dùng cho mọi lời gọi Carbon. `null` khi vụ
  /// chưa đồng bộ lên server.
  String? get cropSeasonServerId => _cropSeason?.serverId;

  bool get hasCropSeason => _cropSeason != null;

  /// Gắn với DB của user vừa đăng nhập và nạp lại lựa chọn đã lưu.
  Future<void> attach(LocalDatabase db) async {
    _db = db;
    await _loadFromDb();
  }

  /// Bỏ gắn khi đăng xuất — xoá state RAM, KHÔNG đụng file DB.
  void detach() {
    _db = null;
    _farm = null;
    _plot = null;
    _cropSeason = null;
    notifyListeners();
  }

  Future<void> _loadFromDb() async {
    final db = _db;
    if (db == null || !db.isOpen) {
      _farm = _plot = null;
      _cropSeason = null;
      notifyListeners();
      return;
    }
    final saved = await db.readActiveContext();
    _farm =
        saved?['farm_id'] == null ? null : await db.getFarm(saved!['farm_id']!);
    _plot = (_farm != null && saved?['plot_client_id'] != null)
        ? await db.getPlotByClientId(saved!['plot_client_id']!)
        : null;
    if (_plot != null && _plot!.farmId != _farm!.id) _plot = null;
    _cropSeason = (_plot != null && saved?['crop_season_client_id'] != null)
        ? await db.getCropSeasonByClientId(saved!['crop_season_client_id']!)
        : null;
    if (_cropSeason != null && _cropSeason!.plotClientId != _plot!.clientId) {
      _cropSeason = null;
    }
    await _persist();
    notifyListeners();
  }

  /// Kiểm tra lại các entity đang chọn còn tồn tại trong cache local không
  /// (gọi sau khi kéo dữ liệu từ server). Mất thì xoá từ cấp mất trở xuống.
  Future<void> revalidate() => _loadFromDb();

  Future<void> setFarm(Farm? farm) async {
    if (farm?.id == _farm?.id) return;
    _farm = farm;
    _plot = null;
    _cropSeason = null;
    await _persist();
    notifyListeners();
  }

  Future<void> setPlot(Plot? plot) async {
    if (plot != null && plot.farmId != _farm?.id) {
      throw ArgumentError('Plot không thuộc Farm đang chọn');
    }
    if (plot?.clientId == _plot?.clientId) return;
    _plot = plot;
    _cropSeason = null;
    await _persist();
    notifyListeners();
  }

  Future<void> setCropSeason(CropSeason? season) async {
    if (season != null && season.plotClientId != _plot?.clientId) {
      throw ArgumentError('Crop Season không thuộc Plot đang chọn');
    }
    _cropSeason = season;
    await _persist();
    notifyListeners();
  }

  /// Cập nhật lại bản sao trong RAM sau khi entity được sửa/đồng bộ (ví dụ vụ
  /// vừa có `server_id`).
  void refreshCropSeason(CropSeason updated) {
    if (updated.clientId != _cropSeason?.clientId) return;
    _cropSeason = updated;
    notifyListeners();
  }

  Future<void> clear() async {
    _farm = null;
    _plot = null;
    _cropSeason = null;
    await _db?.clearActiveContext();
    notifyListeners();
  }

  Future<void> _persist() async {
    final db = _db;
    if (db == null || !db.isOpen) return;
    if (_farm == null) {
      await db.clearActiveContext();
      return;
    }
    await db.writeActiveContext(
      farmId: _farm!.id,
      plotClientId: _plot?.clientId,
      cropSeasonClientId: _cropSeason?.clientId,
    );
  }
}

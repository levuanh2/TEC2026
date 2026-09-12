import '../db/local_database.dart';
import '../models/activity.dart';
import '../models/activity_field_spec.dart';
import '../models/farm.dart';
import 'device_service.dart';
import 'sync_errors.dart';
import 'sync_gateway.dart';

const _kDetailTableFor = <String, String>{
  'seeding': 'seeding_events',
  'fertilizer': 'fertilizer_applications',
  'irrigation': 'irrigation_events',
  'pesticide': 'pesticide_applications',
  'fuel': 'fuel_usages',
  'straw_management': 'straw_management_events',
  'harvest': 'harvest_events',
};

/// Đẩy dữ liệu offline lên Supabase khi có mạng. KHÔNG qua backend FastAPI —
/// RLS đã tự chịu trách nhiệm phân quyền; backend chỉ lo tính CO2e.
///
/// Idempotent bằng khoá tự nhiên: `plots (farm_id, plot_code)`,
/// `crop_seasons (plot_id, season_code)`, `activities (device_id, client_event_id)`
/// — upsert lại không tạo bản ghi trùng (retry an toàn sau crash / mất mạng).
///
/// Tham chiếu cha dùng `clientId` cục bộ; ở đây mới tra ra `serverId`. Con nào
/// có cha chưa đồng bộ thì bỏ qua lượt này, thử lại lượt sau.
///
/// Mọi thao tác mạng đi qua [SyncGateway] — test bơm bản giả, không cần Supabase.
class SyncService {
  SyncService(this._gateway, this._db, this._devices,
      {Future<void> Function()? onSynced})
      : _onSynced = onSynced;
  final SyncGateway _gateway;
  final LocalDatabase _db;
  final DeviceService _devices;
  final Future<void> Function()? _onSynced;

  final _batchCache =
      <String, String>{}; // cropSeason server id -> batch server id

  /// Single-flight: một lượt `syncAll` tại một thời điểm. Lời gọi thứ hai (kể cả
  /// từ ngoài coordinator) nhận lại đúng future đang chạy — không đẩy 2 lần.
  Future<SyncSummary>? _inFlight;

  /// Xoá cache gắn với user hiện tại (gọi khi đăng xuất / đổi tài khoản).
  void clearCache() => _batchCache.clear();

  Future<SyncSummary> syncAll() {
    final running = _inFlight;
    if (running != null) return running;
    final future = _syncAllOnce();
    _inFlight = future;
    return future.whenComplete(() => _inFlight = null);
  }

  Future<SyncSummary> _syncAllOnce() async {
    final summary = SyncSummary();
    await _pushPlots(summary);
    await _pushCropSeasons(summary);
    await _pushActivities(summary);
    // Ghi mốc "gửi gần nhất" khi có tiến triển hoặc không lỗi (Trang chủ đọc lại).
    final progressed = summary.plotsSynced +
            summary.cropSeasonsSynced +
            summary.activitiesSynced +
            summary.activitiesDeleted >
        0;
    if (!summary.hasErrors || progressed) {
      await _onSynced?.call();
    }
    return summary;
  }

  Future<void> _pushPlots(SyncSummary summary) async {
    for (final plot in await _db.listPendingPlots()) {
      try {
        await _db.markPlotSyncing(plot.clientId);
        final serverId = await _gateway.upsertPlot(plot.toServerInsert());
        await _db.markPlotSynced(plot.clientId, serverId);
        summary.plotsSynced++;
      } catch (error) {
        final kind = classifySyncError(error);
        await _db.markPlotSyncFailed(plot.clientId, kind.name);
        summary.record('Thửa ${plot.plotCode}', kind);
      }
    }
  }

  Future<void> _pushCropSeasons(SyncSummary summary) async {
    for (final season in await _db.listPendingCropSeasons()) {
      final plot = await _db.getPlotByClientId(season.plotClientId);
      final plotServerId = plot?.serverId;
      if (plotServerId == null) {
        summary.deferred++;
        continue; // thửa cha chưa đồng bộ xong
      }
      try {
        await _db.markCropSeasonSyncing(season.clientId);
        final serverId = await _gateway.upsertCropSeason(
          season.toServerInsert(plotServerId: plotServerId),
        );
        await _db.markCropSeasonSynced(season.clientId, serverId);
        summary.cropSeasonsSynced++;
      } catch (error) {
        final kind = classifySyncError(error);
        await _db.markCropSeasonSyncFailed(season.clientId, kind.name);
        summary.record('Vụ ${season.seasonCode}', kind);
      }
    }
  }

  Future<void> _pushActivities(SyncSummary summary) async {
    final pending = await _db.listPendingActivities();
    if (pending.isEmpty) return;
    final deviceId = await _devices.ensureServerDeviceId();

    for (final activity in pending) {
      // Tombstone: bản ghi đã đồng bộ bị xoá → đẩy `deleted_at`, CHỈ xoá hẳn
      // local khi server XÁC NHẬN đúng dòng. RLS/mạng/0-dòng → giữ nguyên hàng.
      if (activity.deletedLocally) {
        await _pushDelete(activity, summary);
        continue;
      }

      final season = await _db.getCropSeasonByClientId(activity.cropSeasonId);
      final seasonServerId = season?.serverId;
      if (seasonServerId == null) {
        summary.deferred++;
        continue; // vụ cha chưa có id thật trên server
      }
      try {
        await _db.updateActivitySyncState(activity.clientEventId,
            state: SyncState.syncing);
        final batchId = await _ensureDefaultBatch(seasonServerId);

        final serverActivityId = await _gateway.upsertActivity({
          'production_batch_id': batchId,
          'activity_type': activity.type,
          // `activities.occurred_at` / `recorded_at` là `timestamptz` — mốc
          // thời gian THẬT, không phải ngày lịch. `DateTime` ở đây là giờ máy
          // (giờ VN), và `toIso8601String()` trên một DateTime local sinh chuỗi
          // KHÔNG có `Z` cũng không có offset; Postgres đọc chuỗi trần đó theo
          // giờ phiên (UTC), nên 23:00 ICT bị lưu thành 23:00Z và đọc lại thành
          // 06:00 hôm sau — lệch NGÀY canh tác của nông dân.
          // `.toUtc()` gửi đúng mốc (23:00 ICT → 16:00Z); tầng hiển thị đã gọi
          // `.toLocal()` (AppFormat) nên vòng đọc–ghi trả lại đúng giờ đã nhập.
          'occurred_at': activity.occurredAt.toUtc().toIso8601String(),
          'recorded_at': activity.createdAt.toUtc().toIso8601String(),
          'source': 'mobile_offline',
          'device_id': deviceId,
          'client_event_id': activity.clientEventId,
          // LUÔN gửi `note`, kể cả `null` → xoá ghi chú cũ trên server khi sửa.
          'note': activity.note,
        });

        final table = _kDetailTableFor[activity.type];
        if (table != null) {
          await _gateway.upsertActivityDetail(
            table,
            _detailRow(activity.type, serverActivityId, activity.payload),
          );
        }

        await _db.updateActivitySyncState(
          activity.clientEventId,
          state: SyncState.synced,
          serverActivityId: serverActivityId,
        );
        summary.activitiesSynced++;
      } catch (error) {
        final kind = classifySyncError(error);
        await _db.updateActivitySyncState(
          activity.clientEventId,
          state: SyncState.failed,
          error: kind.name,
        );
        summary.record('Hoạt động ${activity.type}', kind);
      }
    }
  }

  /// Hàng ĐẦY ĐỦ cho bảng chi tiết: mọi cột của loại này (lấy từ
  /// [kActivityFieldSpecs] — `key` khớp tuyệt đối cột migration). Cột người dùng
  /// bỏ trống gửi `null` để XOÁ giá trị cũ trên server khi sửa. KHÔNG thêm cột lạ
  /// (không trộn nhầm field giữa các bảng chi tiết).
  static Map<String, Object?> _detailRow(
    String type,
    String serverActivityId,
    Map<String, dynamic> payload,
  ) {
    final specs = kActivityFieldSpecs[type] ?? const <ActivityFieldSpec>[];
    return {
      'activity_id': serverActivityId,
      for (final s in specs) s.key: payload[s.key],
    };
  }

  Future<void> _pushDelete(Activity activity, SyncSummary summary) async {
    final id = activity.clientEventId;
    final serverId = activity.serverActivityId;
    if (serverId == null) {
      // Chưa từng lên server → xoá hẳn local là đủ (nghiệp vụ xoá bản chưa sync).
      await _db.hardDeleteActivity(id);
      summary.activitiesDeleted++;
      return;
    }
    try {
      await _db.updateActivitySyncState(id, state: SyncState.syncing);

      // XÁC NHẬN bằng SỐ DÒNG UPDATE TÁC ĐỘNG, KHÔNG bằng SELECT visibility
      // (RLS `activities_select` ẩn row đã `deleted_at` — không phân biệt được
      // "đã xoá" với "RLS thu hồi quyền, row còn sống"; TOCTOU không an toàn).
      final affected =
          await _gateway.softDeleteActivity(serverId, DateTime.now());

      if (affected == 1) {
        // Server ĐÃ ghi `deleted_at` cho đúng 1 row (id = serverId). Ack chắc
        // chắn (count tính trước RLS select) → dọn tombstone local, idempotent.
        await _db.hardDeleteActivity(id);
        summary.activitiesDeleted++;
        return;
      }

      // affected == 0  → RLS `activities_update USING` chặn / row không tồn tại.
      // affected == null → không đọc được count.
      // Cả hai đều KHÔNG xác nhận server nhận `deleted_at` → BẢO TOÀN DỮ LIỆU:
      // giữ tombstone `failed`, lượt sau thử lại. KHÔNG mất row, KHÔNG tạo lại
      // Activity (nhánh này không bao giờ gọi `upsertActivity`).
      await _db.updateActivitySyncState(id,
          state: SyncState.failed, error: SyncErrorKind.notConfirmed.name);
      summary.record(
          'Xoá hoạt động ${activity.type}', SyncErrorKind.notConfirmed);
    } catch (error) {
      final kind = classifySyncError(error);
      // KHÔNG mất hàng: giữ tombstone, đánh dấu failed để thử lại.
      await _db.updateActivitySyncState(id,
          state: SyncState.failed, error: kind.name);
      summary.record('Xoá hoạt động ${activity.type}', kind);
    }
  }

  /// Nông dân không thao tác khái niệm "lô" — MVP tự tạo 1 batch mặc định mỗi vụ
  /// để thoả `activities.production_batch_id NOT NULL`. Carbon Engine vẫn tính
  /// theo Crop Season (xem docs/CARBON_CALCULATION_SCOPE_RESOLUTION.md).
  Future<String> _ensureDefaultBatch(String cropSeasonServerId) async {
    final cached = _batchCache[cropSeasonServerId];
    if (cached != null) return cached;
    final id = await _gateway.ensureDefaultBatch(cropSeasonServerId);
    _batchCache[cropSeasonServerId] = id;
    return id;
  }

  /// HTX (organization) mà người dùng hiện tại là thành viên — cần để tạo Farm
  /// (farms.cooperative_id). Gia nhập HTX ngoài phạm vi MVP 1a (quản lý HTX
  /// thêm thủ công), app chỉ đọc lại.
  Future<String?> currentCooperativeId() => _gateway.currentCooperativeId();

  /// Kéo Farm/Plot/CropSeason từ Supabase về cache local (RLS đã lọc theo user).
  /// Bản ghi local đang chờ đồng bộ (chưa có `server_id`) KHÔNG bị đụng. Bản ghi
  /// ĐÃ đồng bộ mà server không còn trả về → bị gỡ khỏi cache (thửa/vụ bị xoá
  /// hoặc bị thu hồi quyền phía server). Caller nên gọi
  /// `activeContext.revalidate()` sau đó để dọn lựa chọn đã mất.
  Future<void> pullFarmsPlotsSeasons() async {
    final farms = await _gateway.fetchFarms();
    await _db.replaceFarms([for (final row in farms) Farm.fromServer(row)]);

    final plots = await _gateway.fetchPlots();
    for (final row in plots) {
      await _db.mergeServerPlot(row);
    }
    await _db.reconcilePulledPlots(
      {for (final row in plots) row['id'] as String},
    );

    final seasons = await _gateway.fetchCropSeasons();
    for (final row in seasons) {
      await _db.mergeServerCropSeason(row);
    }
    await _db.reconcilePulledCropSeasons(
      {for (final row in seasons) row['id'] as String},
    );
  }
}

class SyncSummary {
  int plotsSynced = 0;
  int cropSeasonsSynced = 0;
  int activitiesSynced = 0;
  int activitiesDeleted = 0; // tombstone đã đẩy `deleted_at` + server xác nhận

  /// Số bản ghi bị hoãn vì cha chưa đồng bộ (không phải lỗi).
  int deferred = 0;

  final failures = <SyncFailure>[];

  bool get hasErrors => failures.isNotEmpty;
  int get errorCount => failures.length;

  void record(String label, SyncErrorKind kind) =>
      failures.add(SyncFailure(label, kind));

  /// Có lỗi RLS/quyền trong lượt này → UI nên nhắc liên hệ HTX.
  bool get hasPermissionError =>
      failures.any((f) => f.kind == SyncErrorKind.rlsDenied);
}

class SyncFailure {
  const SyncFailure(this.label, this.kind);
  final String label;
  final SyncErrorKind kind;

  String get message => '$label: ${syncErrorMessage(kind)}';
}

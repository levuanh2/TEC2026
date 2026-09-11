import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../db/local_database.dart';
import '../models/carbon_result.dart';
import '../models/crop_season.dart';
import '../models/crop_season_metrics.dart';
import '../models/farm.dart';
import '../models/plot.dart';
import '../services/active_context.dart';
import '../services/carbon_api_service.dart';
import '../services/connectivity_service.dart';
import '../services/me_service.dart';
import '../services/metrics_service.dart';
import '../services/read_api.dart';

enum HomeStatus {
  loading,
  refreshing,
  success,
  partial, // online, tải được một phần
  empty, // online, tài khoản chưa có hộ/dữ liệu nào
  offlineWithCache,
  offlineNoCache,
  unauthorized,
  error,
}

enum HomeTodoKind { pushPending, chooseSeason, fillMissingData, writeActivity }

class HomeTodo {
  const HomeTodo(this.kind, {this.pendingCount});
  final HomeTodoKind kind;
  final int? pendingCount;
}

/// Ảnh chụp bất biến của màn Trang chủ. Mọi số liệu là THẬT (local hoặc API);
/// `null` nghĩa là "chưa có dữ liệu", KHÔNG bao giờ thay bằng 0.
class HomeSnapshot {
  const HomeSnapshot({
    required this.status,
    this.fullName,
    this.farm,
    this.plot,
    this.season,
    this.farmCount = 0,
    this.plotCount = 0,
    this.pendingCount = 0,
    this.lastSyncAt,
    this.online = false,
    this.carbon,
    this.carbonFromCache = false,
    this.metrics,
    this.metricsFromCache = false,
    this.todo,
    this.softError,
  });

  final HomeStatus status;
  final String? fullName;
  final Farm? farm;
  final Plot? plot;
  final CropSeason? season;
  final int farmCount;
  final int plotCount;
  final int pendingCount;
  final DateTime? lastSyncAt;
  final bool online;
  final CarbonResult? carbon;
  final bool carbonFromCache;

  /// Chỉ số tài nguyên/kết quả vụ từ `GET /v1/crop-seasons/{id}/metrics`.
  /// `null` = chưa tải được; từng field bên trong `null` = chưa đủ dữ liệu.
  final CropSeasonMetrics? metrics;
  final bool metricsFromCache;
  final HomeTodo? todo;
  final String? softError;

  bool get hasContext => season != null;
  String? get cropSeasonServerId => season?.serverId;

  HomeSnapshot copyWith({HomeStatus? status, String? softError}) =>
      HomeSnapshot(
        status: status ?? this.status,
        fullName: fullName,
        farm: farm,
        plot: plot,
        season: season,
        farmCount: farmCount,
        plotCount: plotCount,
        pendingCount: pendingCount,
        lastSyncAt: lastSyncAt,
        online: online,
        carbon: carbon,
        carbonFromCache: carbonFromCache,
        metrics: metrics,
        metricsFromCache: metricsFromCache,
        todo: todo,
        softError: softError,
      );
}

const _kMetaFullName = 'home.full_name';
const _kMetaLastSync = 'sync.last_at';
String _carbonCacheKey(String seasonServerId) => 'home.carbon.$seasonServerId';
String _metricsCacheKey(String seasonServerId) =>
    'home.metrics.$seasonServerId';

/// Điều phối dữ liệu màn Trang chủ. KHÔNG gọi mạng trong build — chỉ ở
/// [load]/[refresh]. Lỗi không xoá cache (giữ [_snapshot] cũ, chỉ đổi status).
class HomeController extends ChangeNotifier {
  HomeController({
    required MeService me,
    required CarbonApiService carbon,
    required MetricsService metrics,
    required LocalDatabase db,
    required ActiveContext activeContext,
    required ConnectivityService connectivity,
  })  : _me = me,
        _carbon = carbon,
        _metrics = metrics,
        _db = db,
        _ctx = activeContext,
        _conn = connectivity;

  final MeService _me;
  final CarbonApiService _carbon;
  final MetricsService _metrics;
  final LocalDatabase _db;
  final ActiveContext _ctx;
  final ConnectivityService _conn;

  HomeSnapshot _snapshot = const HomeSnapshot(status: HomeStatus.loading);
  HomeSnapshot get snapshot => _snapshot;

  bool _loading = false;
  bool _loadedOnce = false;
  StreamSubscription<bool>? _connSub;
  bool _disposed = false;

  /// Tăng mỗi khi ngữ cảnh đổi theo cách khiến dữ liệu đang tải trở nên SAI
  /// (đổi Farm/Plot/Vụ, đăng xuất/đổi tài khoản). Response bắt đầu ở generation
  /// cũ KHÔNG được `_emit` (tránh ghi đè snapshot bằng dữ liệu vụ/người dùng cũ).
  int _generation = 0;

  /// Ngữ cảnh đổi TRONG lúc `_run` đang chạy → chạy lại một lượt đầy đủ ngay sau
  /// khi lượt hiện tại kết thúc (không bỏ sót vụ mới).
  bool _rerunAfterLoad = false;

  /// `_build` tự chọn Farm duy nhất → `_ctx` phát sự kiện, NHƯNG đây không phải
  /// "người dùng đổi ngữ cảnh": không tăng generation, không huỷ lượt đang chạy.
  bool _internalContextUpdate = false;

  /// Đã đăng xuất/đổi tài khoản: KHÔNG chạy `_build` (DB đã/đang đóng, không còn
  /// user hợp lệ). `resetForSignOut` bật; `load()` của user kế tiếp tắt.
  bool _suspended = false;

  /// Việc bất đồng bộ đang chạy gần nhất (load / refresh / recompute do đổi
  /// context hoặc kết nối). Cho phép test chờ đúng thời điểm thay vì `delay`.
  Future<void> _pending = Future<void>.value();

  /// CHỈ dùng trong test: chờ mọi công việc do sự kiện (đổi context / kết nối)
  /// khởi động xong — không còn race với `Future.delayed` cố định.
  @visibleForTesting
  Future<void> debugSettle() async {
    await Future<void>.delayed(Duration.zero); // để sự kiện stream được giao
    await _pending;
    await Future<void>.delayed(Duration.zero);
    await _pending; // sự kiện có thể kích hoạt việc thứ hai
  }

  void attach() {
    _ctx.addListener(_onContextChanged);
    _connSub = _conn.onChange.listen(_onConnectivityChanged);
  }

  /// Nạp lần đầu. Được gọi từ CẢ `AppServices.onUserActive` LẪN
  /// `HomeTab.initState` (hai điểm vào độc lập) — chỉ chạy mạng đúng MỘT lần.
  /// Muốn tải lại thì gọi [refresh].
  Future<void> load() async {
    if (_loadedOnce) return;
    _loadedOnce = true;
    _suspended = false; // user mới đang hoạt động
    _pending = _run(isRefresh: false);
    await _pending;
  }

  Future<void> refresh() => _pending = _run(isRefresh: true);

  void _onConnectivityChanged(bool online) {
    if (_disposed || _suspended) return;
    if (_loading) {
      // Đang tải → chạy lại một lượt đầy đủ khi xong; KHÔNG đụng `_pending`
      // (lượt đang chạy tự nối rerun vào future của chính nó).
      _rerunAfterLoad = true;
      return;
    }
    // Vừa có mạng lại → tải đầy đủ. Mất mạng → chỉ hạ trạng thái offline.
    _pending = online ? _run(isRefresh: true) : _recomputeLocalOnly();
  }

  Future<void> _run({required bool isRefresh}) async {
    if (_disposed || _suspended) return;
    if (_loading) {
      // Có `_run` đang chạy → yêu cầu nó chạy lại một lượt đầy đủ khi xong, và
      // TRẢ VỀ future của lượt đó (lượt đó `await` rerun ở cuối) nên caller
      // `load()/refresh()` chỉ hoàn thành khi state cuối đã ổn định, không dừng
      // ở no-op.
      _rerunAfterLoad = true;
      return _pending;
    }
    _loading = true;
    final gen = _generation;
    if (isRefresh) {
      _emitFor(gen,
          _snapshot.copyWith(status: HomeStatus.refreshing, softError: null));
    } else if (_snapshot.status == HomeStatus.loading) {
      _emitFor(gen, const HomeSnapshot(status: HomeStatus.loading));
    }

    try {
      final next = await _build(gen);
      _emitFor(gen, next);
    } catch (_) {
      // Không xoá cache: giữ snapshot cũ, chỉ báo lỗi.
      _emitFor(
        gen,
        _snapshot.copyWith(
          status: HomeStatus.error,
          softError: 'Không tải được Trang chủ. Kéo xuống để thử lại.',
        ),
      );
    } finally {
      _loading = false;
    }

    // Ngữ cảnh đổi trong lúc chạy → chạy lại NGAY và `await` để future của lượt
    // này chỉ hoàn thành khi state cuối đã đúng (không dừng ở no-op). Bỏ nếu đã
    // đăng xuất (DB đóng) hoặc dispose.
    if (_rerunAfterLoad && !_disposed && !_suspended) {
      _rerunAfterLoad = false;
      await _run(isRefresh: true);
    } else {
      _rerunAfterLoad = false;
    }
  }

  /// `_emit` có kiểm generation: response của ngữ cảnh cũ bị BỎ, không ghi đè.
  void _emitFor(int gen, HomeSnapshot s) {
    if (_disposed || gen != _generation) return;
    _emit(s);
  }

  /// [gen] = generation lúc lượt này bắt đầu. Nếu ngữ cảnh/người dùng đã đổi
  /// (hoặc đã đăng xuất) trong lúc chạy, DỪNG trước khi gọi mạng — snapshot trả
  /// về sẽ bị `_emitFor` bỏ, và ta không chạm API/DB cho ngữ cảnh đã cũ.
  bool _stale(int gen) => _disposed || _suspended || gen != _generation;

  Future<HomeSnapshot> _build(int gen) async {
    final online = _conn.isOnline;

    // --- Local (luôn có, không ném) ---
    var farms = <Farm>[];
    try {
      farms = await _db.listFarms();
    } catch (_) {}
    if (_stale(gen)) return _snapshot;

    // Tự chọn Farm CHỈ khi không mơ hồ (đúng 1 hộ) và chưa chọn gì. Đây là thao
    // tác nội bộ của `_build` → KHÔNG tính là "người dùng đổi ngữ cảnh".
    if (_ctx.farm == null && farms.length == 1) {
      _internalContextUpdate = true;
      try {
        await _ctx.setFarm(farms.single);
      } finally {
        _internalContextUpdate = false;
      }
    }

    final farm = _ctx.farm;
    final plot = _ctx.plot;
    final season = _ctx.cropSeason;

    var plotCount = 0;
    var pending = 0;
    DateTime? lastSync;
    String? cachedName;
    CarbonResult? cachedCarbon;
    CropSeasonMetrics? cachedMetrics;
    try {
      if (farm != null) {
        plotCount = (await _db.listPlotsByFarm(farm.id)).length;
      }
      pending = await _db.countAllPending();
      lastSync = _parseDate(await _db.getMeta(_kMetaLastSync));
      cachedName = await _db.getMeta(_kMetaFullName);
      final sid = season?.serverId;
      if (sid != null) {
        final raw = await _db.getMeta(_carbonCacheKey(sid));
        if (raw != null) {
          cachedCarbon =
              CarbonResult.fromJson(jsonDecode(raw) as Map<String, dynamic>);
        }
        final rawMetrics = await _db.getMeta(_metricsCacheKey(sid));
        if (rawMetrics != null) {
          cachedMetrics = CropSeasonMetrics.fromJson(
              jsonDecode(rawMetrics) as Map<String, dynamic>);
        }
      }
    } catch (_) {}

    var fullName = cachedName;
    var carbon = cachedCarbon;
    var carbonFromCache = cachedCarbon != null;
    var metrics = cachedMetrics;
    var metricsFromCache = cachedMetrics != null;
    var netFailed = false;

    // --- Mạng (chỉ khi online, và ngữ cảnh CHƯA đổi) ---
    if (online && !_stale(gen)) {
      try {
        final me = await _me.fetch();
        fullName = me.fullName;
        await _db.setMeta(_kMetaFullName, fullName);
      } on ReadApiException catch (e) {
        if (e.isUnauthorized) {
          return _snapshot.copyWith(status: HomeStatus.unauthorized);
        }
        netFailed = true;
      } catch (_) {
        netFailed = true;
      }

      final sid = season?.serverId;
      if (sid != null && !_stale(gen)) {
        // Đánh dấu đã (đang) tải vụ này để `_onContextChanged` không gọi lại
        // khi có thông báo context không liên quan (ví dụ chọn lại cùng thửa).
        _lastFetchedSeasonServerId = sid;
        try {
          final result = await _carbon.latest(cropSeasonId: sid);
          // `null` = vụ hợp lệ nhưng CHƯA tính lần nào (không phải lỗi).
          carbon = result;
          carbonFromCache = false;
          if (result != null) {
            await _db.setMeta(
                _carbonCacheKey(sid), jsonEncode(result.toCacheJson()));
          }
        } on CarbonApiException catch (e) {
          if (e.statusCode == 401 || e.statusCode == 403) {
            return _snapshot.copyWith(status: HomeStatus.unauthorized);
          }
          netFailed = true; // giữ cachedCarbon
        } catch (_) {
          netFailed = true;
        }

        // Chỉ số vụ (nước / phân bón / sản lượng / chi phí). Vụ CHƯA đồng bộ
        // (sid == null) đã bị loại ở trên — không gọi API cho nó.
        try {
          final m = await _metrics.fetchForCropSeason(sid);
          metrics = m;
          metricsFromCache = false;
          await _db.setMeta(_metricsCacheKey(sid), jsonEncode(m.toCacheJson()));
        } on ReadApiException catch (e) {
          if (e.isUnauthorized) {
            return _snapshot.copyWith(status: HomeStatus.unauthorized);
          }
          netFailed = true; // giữ cachedMetrics
        } catch (_) {
          netFailed = true;
        }
      }
    }

    final status = _resolveStatus(
      online: online,
      netFailed: netFailed,
      hasFarms: farms.isNotEmpty,
      hasAnyCache: farms.isNotEmpty ||
          fullName != null ||
          carbon != null ||
          metrics != null,
    );

    return HomeSnapshot(
      status: status,
      fullName: fullName,
      farm: farm,
      plot: plot,
      season: season,
      farmCount: farms.length,
      plotCount: plotCount,
      pendingCount: pending,
      lastSyncAt: lastSync,
      online: online,
      carbon: carbon,
      carbonFromCache: carbonFromCache,
      metrics: metrics,
      metricsFromCache: metricsFromCache,
      todo: _todo(pending: pending, season: season),
      softError: status == HomeStatus.partial
          ? 'Một số thông tin chưa tải được — kéo xuống để thử lại.'
          : null,
    );
  }

  HomeStatus _resolveStatus({
    required bool online,
    required bool netFailed,
    required bool hasFarms,
    required bool hasAnyCache,
  }) {
    if (!online) {
      return hasAnyCache
          ? HomeStatus.offlineWithCache
          : HomeStatus.offlineNoCache;
    }
    if (netFailed) return HomeStatus.partial;
    return hasFarms ? HomeStatus.success : HomeStatus.empty;
  }

  HomeTodo _todo({required int pending, required CropSeason? season}) {
    if (pending > 0) {
      return HomeTodo(HomeTodoKind.pushPending, pendingCount: pending);
    }
    if (season == null) return const HomeTodo(HomeTodoKind.chooseSeason);
    if (_seasonMissingData(season)) {
      return const HomeTodo(HomeTodoKind.fillMissingData);
    }
    return const HomeTodo(HomeTodoKind.writeActivity);
  }

  static bool _seasonMissingData(CropSeason s) =>
      s.cultivationDays == null ||
      s.ipccWaterRegime == null ||
      s.preSeasonWaterRegime == null;

  /// Ghi mốc đồng bộ thành công gần nhất — gọi từ SyncService.
  Future<void> markSynced() async {
    try {
      await _db.setMeta(_kMetaLastSync, DateTime.now().toIso8601String());
    } catch (_) {}
    await _recomputeLocalOnly();
  }

  /// Đọc lại phần local (không gọi mạng, KHÔNG đổi mốc sync) — gọi khi quay lại
  /// tab Trang chủ sau khi thao tác ở màn khác.
  Future<void> refreshLocalState() => _recomputeLocalOnly();

  /// Xoá snapshot khi đăng xuất — tránh dữ liệu user cũ nháy sang khi đổi tài
  /// khoản (DB của user mới sẽ được `load()` lại ở `onUserActive`). Mở cửa cho
  /// lần `load()` đầu tiên của user kế tiếp.
  void resetForSignOut() {
    // Đổi người dùng → mọi response đang bay của user cũ trở thành vô hiệu
    // (không cho dữ liệu user A xuất hiện ở user B), và KHÔNG cho rerun nào
    // gọi DB đã đóng cho tới khi `load()` của user kế tiếp bật lại.
    _generation++;
    _rerunAfterLoad = false;
    _suspended = true;
    _loadedOnce = false;
    _lastFetchedSeasonServerId = null;
    _emit(const HomeSnapshot(status: HomeStatus.loading));
  }

  String? _lastFetchedSeasonServerId;

  void _onContextChanged() {
    // `_build` tự chọn Farm duy nhất — không phải người dùng đổi ngữ cảnh.
    if (_internalContextUpdate || _disposed) return;
    // Đăng xuất: `activeContext.detach()` cũng phát sự kiện này — bỏ qua, KHÔNG
    // chạm DB đang đóng.
    if (_suspended) return;
    // Ngữ cảnh đổi → mọi response đang bay của ngữ cảnh cũ trở thành vô hiệu.
    _generation++;

    if (_loading) {
      // Đang có `_run` chạy dở (cho ngữ cảnh cũ). Đánh dấu để nó tự chạy lại
      // một lượt đầy đủ khi xong; KHÔNG đụng `_pending` (future của lượt đang
      // chạy đã bao gồm rerun). Emit của lượt cũ bị `_emitFor` chặn (gen lệch).
      _rerunAfterLoad = true;
      return;
    }

    // 1. Cập nhật local ngay (tránh nháy dữ liệu vụ cũ).
    final recompute = _recomputeLocalOnly();
    // 2. Online + vụ đang chọn ĐỔI sang một vụ đã đồng bộ khác → tải
    //    Carbon/Metrics của vụ mới (không bắt người dùng tự kéo refresh).
    final sid = _ctx.cropSeason?.serverId;
    if (_conn.isOnline && sid != null && sid != _lastFetchedSeasonServerId) {
      _pending = _run(isRefresh: true);
    } else {
      _pending = recompute;
    }
  }

  /// Cập nhật lại phần local (Farm/Plot/Vụ, pending, carbon cache) mà KHÔNG gọi
  /// mạng — dùng khi ActiveContext hoặc kết nối đổi.
  Future<void> _recomputeLocalOnly() async {
    if (_loading || _disposed || _suspended) return;
    final farm = _ctx.farm;
    final season = _ctx.cropSeason;
    int plotCount = _snapshot.plotCount;
    int pending = _snapshot.pendingCount;
    CarbonResult? carbon = _snapshot.carbon;
    var carbonFromCache = _snapshot.carbonFromCache;
    CropSeasonMetrics? metrics = _snapshot.metrics;
    var metricsFromCache = _snapshot.metricsFromCache;
    try {
      if (farm != null) {
        plotCount = (await _db.listPlotsByFarm(farm.id)).length;
      } else {
        plotCount = 0;
      }
      pending = await _db.countAllPending();
      final sid = season?.serverId;
      if (sid != null) {
        final raw = await _db.getMeta(_carbonCacheKey(sid));
        carbon = raw == null
            ? null
            : CarbonResult.fromJson(jsonDecode(raw) as Map<String, dynamic>);
        carbonFromCache = raw != null;
        final rawM = await _db.getMeta(_metricsCacheKey(sid));
        metrics = rawM == null
            ? null
            : CropSeasonMetrics.fromJson(
                jsonDecode(rawM) as Map<String, dynamic>);
        metricsFromCache = rawM != null;
      } else {
        // Đổi sang vụ chưa đồng bộ / bỏ chọn vụ → KHÔNG dùng cache của vụ cũ.
        carbon = null;
        carbonFromCache = false;
        metrics = null;
        metricsFromCache = false;
      }
    } catch (_) {}

    final online = _conn.isOnline;
    final hasCache = farm != null ||
        _snapshot.farmCount > 0 ||
        _snapshot.fullName != null ||
        carbon != null ||
        metrics != null;
    _emit(HomeSnapshot(
      status: _recomputedStatus(online: online, hasCache: hasCache),
      fullName: _snapshot.fullName,
      farm: farm,
      plot: _ctx.plot,
      season: season,
      farmCount: _snapshot.farmCount,
      plotCount: plotCount,
      pendingCount: pending,
      lastSyncAt: _parseDate(await _safeMeta(_kMetaLastSync)),
      online: online,
      carbon: carbon,
      carbonFromCache: carbonFromCache,
      metrics: metrics,
      metricsFromCache: metricsFromCache,
      todo: _todo(pending: pending, season: season),
      softError: _snapshot.softError,
    ));
  }

  /// Trạng thái sau khi tính lại phần local (không gọi mạng). Điểm mấu chốt: khi
  /// MẤT mạng phải hạ xuống `offlineWithCache`/`offlineNoCache` — trước đây giữ
  /// nguyên `success` nên header vẫn báo "đang có mạng".
  HomeStatus _recomputedStatus({required bool online, required bool hasCache}) {
    if (!online) {
      return hasCache ? HomeStatus.offlineWithCache : HomeStatus.offlineNoCache;
    }
    switch (_snapshot.status) {
      // Từ "chưa có gì" hoặc trạng thái offline cũ → nâng theo cache local; các
      // trạng thái online khác (success/partial/empty/unauthorized/error) giữ
      // nguyên cho tới lần `refresh()` kế tiếp.
      case HomeStatus.loading:
      case HomeStatus.offlineWithCache:
      case HomeStatus.offlineNoCache:
        return hasCache ? HomeStatus.success : HomeStatus.empty;
      default:
        return _snapshot.status;
    }
  }

  Future<String?> _safeMeta(String key) async {
    try {
      return await _db.getMeta(key);
    } catch (_) {
      return null;
    }
  }

  static DateTime? _parseDate(String? v) =>
      (v == null || v.isEmpty) ? null : DateTime.tryParse(v);

  void _emit(HomeSnapshot s) {
    if (_disposed) return;
    _snapshot = s;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _ctx.removeListener(_onContextChanged);
    _connSub?.cancel();
    super.dispose();
  }
}

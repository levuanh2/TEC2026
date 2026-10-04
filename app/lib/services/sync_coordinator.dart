import 'dart:async';

import 'package:flutter/foundation.dart';

import '../db/local_database.dart';
import '../models/sync_queue_item.dart';
import 'auth_service.dart' show SessionFreshness;
import 'connectivity_service.dart';
import 'sync_errors.dart';
import 'sync_service.dart';

/// Trạng thái tổng thể của việc gửi dữ liệu — dùng cho màn 23.
enum SyncStatus {
  /// Không có mạng.
  offline,

  /// Có mạng, đang nghỉ (chưa/đã gửi xong, còn hoặc hết hàng đợi).
  idle,

  /// Đang gửi.
  syncing,

  /// Gửi được một phần, còn mục lỗi.
  partialSuccess,

  /// Hàng đợi trống — đã gửi hết.
  allSynced,

  /// Lượt gửi vừa rồi không có tiến triển nào (toàn lỗi).
  failed,

  /// Có lỗi xác thực khi gửi — phiên có thể đã hết hạn.
  authExpired,
}

/// Điều phối đồng bộ: single-flight (một lượt gửi tại một thời điểm), tự gửi sau
/// đăng nhập / khi app trở lại foreground / khi có mạng lại (debounce), cộng nút
/// "Gửi dữ liệu ngay" thủ công. Tôn trọng tuỳ chọn "Chỉ Wi-Fi".
///
/// KHÔNG chặn form nhập — form ghi thẳng SQLite, coordinator chỉ đọc hàng đợi.
class SyncCoordinator extends ChangeNotifier {
  SyncCoordinator({
    required SyncService sync,
    required LocalDatabase db,
    required ConnectivityService connectivity,
    Future<SessionFreshness> Function()? ensureSession,
    Duration connectivityDebounce = const Duration(seconds: 2),
  })  : _sync = sync,
        _db = db,
        _conn = connectivity,
        _ensureSession = ensureSession,
        _debounceFor = connectivityDebounce;

  final SyncService _sync;
  final LocalDatabase _db;
  final ConnectivityService _conn;
  final Duration _debounceFor;

  /// Cổng phiên trước MỖI lượt gửi: phiên hết hạn phải được làm mới thành công
  /// (máy chủ xác thực) rồi mới gửi. Không tới được máy chủ, hoặc bị từ chối →
  /// KHÔNG gửi bản ghi nào, hàng đợi giữ nguyên.
  final Future<SessionFreshness> Function()? _ensureSession;

  static const _kWifiOnlyKey = 'sync.wifi_only';
  static const _kLastSyncKey = 'sync.last_at';

  StreamSubscription<bool>? _connSub;
  Timer? _debounce;
  bool _disposed = false;

  SyncStatus _status = SyncStatus.idle;
  bool _wifiOnly = false;
  DateTime? _lastSyncAt;
  int _pendingCount = 0;
  List<SyncQueueItem> _queue = const [];
  SyncSummary? _lastSummary;

  /// Lượt gửi đang chạy (single-flight). Lần gọi thứ hai nhận lại đúng future này.
  Future<SyncSummary?>? _inFlight;

  SyncStatus get status => _status;
  bool get isSyncing => _inFlight != null;
  bool get wifiOnly => _wifiOnly;
  DateTime? get lastSyncAt => _lastSyncAt;
  int get pendingCount => _pendingCount;
  List<SyncQueueItem> get queue => _queue;
  SyncSummary? get lastSummary => _lastSummary;

  /// Đang bị chặn bởi tuỳ chọn "Chỉ Wi-Fi" (có mạng nhưng là dữ liệu di động).
  bool get blockedByWifiOnly => _conn.isOnline && _wifiOnly && !_conn.isWifi;

  /// Gắn với DB của user vừa đăng nhập: đọc tuỳ chọn + mốc gửi + hàng đợi.
  Future<void> attach() async {
    _connSub ??= _conn.onChange.listen(_onConnectivity);
    _wifiOnly = (await _safeMeta(_kWifiOnlyKey)) == '1';
    await _reload();
  }

  /// Bỏ gắn khi đăng xuất / đổi tài khoản — xoá state RAM (DB đã/đang đóng).
  void detach() {
    _debounce?.cancel();
    _inFlight = null;
    _lastSummary = null;
    _queue = const [];
    _pendingCount = 0;
    _lastSyncAt = null;
    _wifiOnly = false;
    _status = _conn.isOnline ? SyncStatus.idle : SyncStatus.offline;
    _notify();
  }

  Future<void> setWifiOnly(bool value) async {
    _wifiOnly = value;
    try {
      await _db.setMeta(_kWifiOnlyKey, value ? '1' : '0');
    } catch (_) {}
    // Vừa cho phép lại + đang có mạng phù hợp + còn hàng đợi → thử gửi.
    if (!value && _pendingCount > 0) {
      unawaited(runSync());
    } else {
      _recomputeIdleStatus();
      _notify();
    }
  }

  /// Đọc lại hàng đợi + mốc gửi từ DB (không gọi mạng). Gọi sau khi lưu / xoá
  /// Activity ở màn khác, hoặc khi mở tab 23.
  Future<void> refresh() => _reload();

  Future<void> _reload() async {
    if (!_db.isOpen) return;
    try {
      _queue = await _db.pendingSyncItems();
      _pendingCount = await _db.countAllPending();
      _lastSyncAt = _parse(await _db.getMeta(_kLastSyncKey));
    } catch (_) {
      // DB có thể vừa đóng do đổi tài khoản — bỏ qua.
    }
    if (!isSyncing) _recomputeIdleStatus();
    _notify();
  }

  void _recomputeIdleStatus() {
    if (!_conn.isOnline) {
      _status = SyncStatus.offline;
    } else if (_pendingCount == 0) {
      _status = SyncStatus.allSynced;
    } else if (_status != SyncStatus.authExpired) {
      _status = SyncStatus.idle;
    }
  }

  // --- Trigger tự động --------------------------------------------------

  /// Sau khi đăng nhập (gọi từ `AppServices.onUserActive`).
  Future<void> onLogin() => runSync();

  /// App trở lại foreground (gọi từ `HomeShell` qua `WidgetsBindingObserver`).
  Future<void> onAppResumed() => runSync();

  void _onConnectivity(bool online) {
    if (_disposed) return;
    if (!online) {
      _debounce?.cancel();
      if (!isSyncing) {
        _status = SyncStatus.offline;
        _notify();
      }
      return;
    }
    // Có mạng lại → debounce rồi gửi (tránh dội khi mạng chập chờn).
    _debounce?.cancel();
    _debounce = Timer(_debounceFor, () {
      if (!_disposed) unawaited(runSync());
    });
  }

  // --- Lõi đồng bộ ----------------------------------------------------

  /// Chạy một lượt gửi. Single-flight: đang chạy → trả lại future đang chạy.
  ///
  /// [manual] = true khi người dùng bấm nút. [overrideWifiOnly] = true để bỏ qua
  /// tuỳ chọn "Chỉ Wi-Fi" cho DUY NHẤT lượt này (người dùng đã xác nhận).
  Future<SyncSummary?> runSync({
    bool manual = false,
    bool overrideWifiOnly = false,
  }) {
    final running = _inFlight;
    if (running != null) return running;

    if (!_db.isOpen) return Future.value(null);

    if (!_conn.isOnline) {
      _status = SyncStatus.offline;
      _notify();
      return Future.value(null);
    }
    if (_wifiOnly && !_conn.isWifi && !overrideWifiOnly) {
      // Auto: bỏ qua im lặng (không đổi status thành lỗi). Thủ công: UI đã hỏi
      // trước rồi mới gọi lại với overrideWifiOnly.
      if (!isSyncing) {
        _recomputeIdleStatus();
        _notify();
      }
      return Future.value(null);
    }

    final future = _run();
    _inFlight = future;
    _status = SyncStatus.syncing;
    _notify();
    return future;
  }

  Future<SyncSummary?> _run() async {
    final gate = _ensureSession;
    if (gate != null) {
      SessionFreshness freshness;
      try {
        freshness = await gate();
      } catch (_) {
        freshness = SessionFreshness.offline;
      }
      if (freshness != SessionFreshness.fresh) {
        _inFlight = null;
        await _reloadAfterRun();
        // Bị từ chối → "Hết phiên" (phải đăng nhập lại). Chưa tới được máy chủ
        // → trạng thái theo mạng; nút gửi vẫn bấm lại được khi có mạng thật.
        if (freshness == SessionFreshness.rejected) {
          _status = SyncStatus.authExpired;
        } else {
          _status = SyncStatus.idle;
          _recomputeIdleStatus();
        }
        _notify();
        return null;
      }
    }
    SyncSummary? summary;
    try {
      summary = await _sync.syncAll();
      _lastSummary = summary;
    } catch (_) {
      // syncAll tự nuốt lỗi từng bản ghi; lỗi tới đây là bất thường (vd DB đóng
      // giữa chừng). Không làm sập app.
      summary = null;
    } finally {
      _inFlight = null;
    }

    await _reloadAfterRun();
    _status = _statusFromSummary(summary);
    _notify();
    return summary;
  }

  Future<void> _reloadAfterRun() async {
    if (!_db.isOpen) return;
    try {
      _queue = await _db.pendingSyncItems();
      _pendingCount = await _db.countAllPending();
      _lastSyncAt = _parse(await _db.getMeta(_kLastSyncKey));
    } catch (_) {}
  }

  SyncStatus _statusFromSummary(SyncSummary? s) {
    if (!_conn.isOnline) return SyncStatus.offline;
    if (s == null) {
      return _pendingCount == 0 ? SyncStatus.allSynced : SyncStatus.failed;
    }
    final authFailed = s.failures.any((f) => f.kind == SyncErrorKind.auth);
    if (authFailed) return SyncStatus.authExpired;

    if (_pendingCount == 0) return SyncStatus.allSynced;

    final progressed = s.plotsSynced +
            s.cropSeasonsSynced +
            s.activitiesSynced +
            s.activitiesDeleted >
        0;
    if (s.hasErrors) {
      return progressed ? SyncStatus.partialSuccess : SyncStatus.failed;
    }
    // Không lỗi nhưng còn hàng đợi (vd con chờ cha) → vẫn còn việc, coi là idle.
    return SyncStatus.idle;
  }

  Future<String?> _safeMeta(String key) async {
    try {
      return await _db.getMeta(key);
    } catch (_) {
      return null;
    }
  }

  static DateTime? _parse(String? v) =>
      (v == null || v.isEmpty) ? null : DateTime.tryParse(v);

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _debounce?.cancel();
    _connSub?.cancel();
    super.dispose();
  }
}

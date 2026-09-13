import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart' show visibleForTesting;

/// Trạng thái mạng THẬT của thiết bị (interface mạng), dạng stream — không
/// polling. Đây là tín hiệu tốt nhất không cần gọi mạng; việc gọi API thất bại
/// vẫn là bằng chứng chắc hơn và được các service xử lý riêng.
///
/// **"Có Wi-Fi" KHÔNG bảo đảm có Internet** (captive portal, router mất WAN…).
/// [isWifi] chỉ dùng để áp tuỳ chọn "Chỉ gửi qua Wi-Fi"; mọi lần đồng bộ thất
/// bại vẫn giữ dữ liệu để thử lại.
class ConnectivityService {
  ConnectivityService({Connectivity? connectivity})
      : _connectivity = connectivity ?? Connectivity();

  /// Dùng cho test / môi trường không có plugin — trạng thái cố định.
  ConnectivityService.fixed(bool online, {bool wifi = true})
      : _connectivity = null,
        _online = online,
        _wifi = online && wifi;

  final Connectivity? _connectivity;
  final _controller = StreamController<bool>.broadcast();
  StreamSubscription<List<ConnectivityResult>>? _sub;
  bool _online = true;
  bool _wifi = true;

  bool get isOnline => _online;

  /// Kết nối hiện tại là Wi-Fi hoặc Ethernet (mạng không tính dung lượng).
  bool get isWifi => _online && _wifi;

  Stream<bool> get onChange => _controller.stream;

  Future<void> start() async {
    final c = _connectivity;
    if (c == null) return; // .fixed()
    _apply(await c.checkConnectivity(), emit: false);
    _sub = c.onConnectivityChanged.listen((results) => _apply(results));
  }

  void _apply(List<ConnectivityResult> results, {bool emit = true}) {
    final online = results.any((r) => r != ConnectivityResult.none);
    final wifi = results.any((r) =>
        r == ConnectivityResult.wifi || r == ConnectivityResult.ethernet);
    final changed = online != _online;
    _online = online;
    _wifi = wifi;
    if (emit && changed && !_controller.isClosed) _controller.add(online);
  }

  /// Chỉ dùng trong test: đổi trạng thái mạng và phát tín hiệu như thật.
  @visibleForTesting
  void debugSet({bool? online, bool? wifi}) {
    final nextOnline = online ?? _online;
    final nextWifi = wifi ?? _wifi;
    final changed = nextOnline != _online;
    _online = nextOnline;
    _wifi = nextWifi;
    if (changed && !_controller.isClosed) _controller.add(nextOnline);
  }

  /// Giữ tương thích với test cũ.
  @visibleForTesting
  void debugSetOnline(bool value) => debugSet(online: value);

  void dispose() {
    _sub?.cancel();
    _controller.close();
  }
}

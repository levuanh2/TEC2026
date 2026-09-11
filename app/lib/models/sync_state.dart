/// Trạng thái đồng bộ của một bản ghi local (Plot / Crop Season / Activity).
///
/// Không tách bảng SyncQueue riêng — trạng thái nằm ngay trên từng bảng. Một
/// nguồn sự thật duy nhất, tránh lệch nhau.
///
///   pending  : chưa gửi (hoặc đã reset để thử lại sau lỗi / sau crash)
///   syncing  : đang gửi — nếu app tắt giữa chừng, lần mở sau phải đưa về pending
///   synced   : server đã nhận, `server_id` đã có
///   failed   : gửi lỗi; vẫn nằm trong hàng đợi để thử lại
enum SyncState { pending, syncing, synced, failed }

extension SyncStateCodec on SyncState {
  String get value => name;

  static SyncState fromValue(String? v) => SyncState.values.firstWhere(
        (s) => s.name == v,
        orElse: () => SyncState.pending,
      );
}

/// Đếm là "còn phải đồng bộ" khi ở pending hoặc failed (syncing là thoáng qua).
bool isUnsynced(SyncState state) =>
    state == SyncState.pending || state == SyncState.failed;

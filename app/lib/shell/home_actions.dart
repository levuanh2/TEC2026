/// Điều hướng mà màn Trang chủ cần — tách khỏi widget để test được.
/// `HomeShell` cài đặt thật; test dùng bản giả ghi lại lời gọi.
abstract interface class HomeActions {
  /// Mở luồng chọn Farm → Thửa → Vụ (đặt ActiveContext).
  void openContextPicker();

  /// Mở màn kết quả phát thải của vụ (dùng CLIENT id — màn tự tra `server_id`
  /// + tiền điều kiện từ DB).
  void openCarbon(String cropSeasonClientId);

  /// Mở màn "Hiệu quả tài nguyên" của vụ (CLIENT id).
  void openResourceDashboard(String cropSeasonClientId);

  /// Ghi một loại hoạt động cho vụ đang chọn (client id của vụ).
  void openActivityForm(String cropSeasonClientId, String activityType);

  /// "Xem tất cả" — chọn trong 7 loại hoạt động.
  void openActivityTypePicker(String cropSeasonClientId);

  /// Bổ sung dữ liệu phương pháp luận còn thiếu cho vụ đang chọn.
  void openActiveCropSeasonForm();

  /// Kiểm tra ảnh lá/ruộng (CV).
  void openCameraCv();

  /// Chuyển sang tab "Gửi dữ liệu".
  void switchToSyncTab();
}

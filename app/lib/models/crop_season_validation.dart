/// Kiểm tra dữ liệu Crop Season — hàm thuần, không phụ thuộc Flutter, để test
/// riêng. Trả `null` khi hợp lệ, hoặc thông báo tiếng Việt.
///
/// Nguyên tắc (CARBON_METHOD.md §11): KHÔNG tự đặt mặc định cho input phương
/// pháp luận khi nông dân chưa biết — thiếu thì để trống, backend sẽ báo.
library;

/// `season_code` bắt buộc, không rỗng.
String? seasonCodeError(String value) {
  if (value.trim().isEmpty) return 'Vui lòng nhập mã vụ (ví dụ: ĐX 2025-2026).';
  return null;
}

/// `cultivation_days` — nếu có nhập thì phải > 0.
String? cultivationDaysError(int? days) {
  if (days == null) return null;
  if (days <= 0) return 'Số ngày canh tác phải lớn hơn 0.';
  if (days > 365) {
    return 'Số ngày canh tác quá lớn — kiểm tra lại ngày gieo và thu hoạch.';
  }
  return null;
}

/// `drainage_event_count` — nếu có nhập thì phải >= 0.
String? drainageCountError(int? count) {
  if (count == null) return null;
  if (count < 0) return 'Số lần rút nước không thể âm.';
  return null;
}

/// Ngày thu hoạch (dự kiến hoặc thực tế) không được trước ngày gieo.
String? harvestNotBeforePlantingError({
  DateTime? planting,
  DateTime? expectedHarvest,
  DateTime? actualHarvest,
}) {
  if (planting == null) return null;
  final p = _dateOnly(planting);
  for (final h in [expectedHarvest, actualHarvest]) {
    if (h != null && _dateOnly(h).isBefore(p)) {
      return 'Ngày thu hoạch không thể trước ngày gieo sạ.';
    }
  }
  return null;
}

/// Gợi ý số ngày canh tác từ ngày gieo và ngày thu hoạch (dự kiến hoặc thực
/// tế). `null` nếu không đủ ngày để suy ra. KẾT QUẢ CHỈ LÀ GỢI Ý — người dùng
/// phải xác nhận trước khi lưu.
int? suggestCultivationDays({
  DateTime? planting,
  DateTime? expectedHarvest,
  DateTime? actualHarvest,
}) {
  if (planting == null) return null;
  final harvest = actualHarvest ?? expectedHarvest;
  if (harvest == null) return null;
  final days = _dateOnly(harvest).difference(_dateOnly(planting)).inDays;
  return days > 0 ? days : null;
}

/// Cảnh báo (KHÔNG chặn lưu) khi chọn AWD / rút nước nhiều lần mà bỏ trống số
/// lần rút nước — dữ liệu đồng ruộng thường thiếu (FR-1a-04). `null` = không
/// cảnh báo.
String? awdDrainageWarning({
  required bool isMultipleDrainageRegime,
  int? drainageEventCount,
}) {
  if (isMultipleDrainageRegime && drainageEventCount == null) {
    return 'Bạn chọn tưới rút nước nhiều lần nhưng chưa ghi số lần rút nước. '
        'Vẫn lưu được — nên bổ sung sau để tính phát thải chính xác hơn.';
  }
  return null;
}

DateTime _dateOnly(DateTime d) => DateTime(d.year, d.month, d.day);

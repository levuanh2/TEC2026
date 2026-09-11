/// Kiểm tra dữ liệu Plot — hàm thuần, không phụ thuộc Flutter. Trả `null` khi
/// hợp lệ, hoặc thông báo tiếng Việt.
library;

String? plotCodeError(String value) {
  if (value.trim().isEmpty) return 'Nhập mã / tên thửa.';
  return null;
}

/// `area_ha` phải là số > 0. Nhận chuỗi người dùng gõ (cho phép dấu phẩy thập
/// phân kiểu Việt Nam) để dùng chung một chỗ parse + kiểm.
String? plotAreaError(String rawInput) {
  final area = parseArea(rawInput);
  if (area == null) return 'Diện tích phải là số (ví dụ: 0,5).';
  if (area <= 0) return 'Diện tích phải lớn hơn 0.';
  if (area > 10000) return 'Diện tích quá lớn — kiểm tra lại đơn vị (ha).';
  return null;
}

/// `null` nếu không parse được.
double? parseArea(String rawInput) =>
    double.tryParse(rawInput.trim().replaceAll(',', '.'));

/// Định dạng ngày/số theo quy ước tiếng Việt — KHÔNG phụ thuộc locale của máy.
///
/// Quan trọng (nguyên tắc "không bịa số" + dữ liệu server): các hàm ở đây chỉ
/// để HIỂN THỊ. Không bao giờ dùng để parse dữ liệu từ server — server luôn gửi
/// ISO-8601 / số thập phân dấu chấm, parse bằng `DateTime.parse` / `num.parse`
/// như hiện tại. `null` vào thì trả chuỗi placeholder, KHÔNG trả "0".
library;

class AppFormat {
  const AppFormat._();

  /// Placeholder khi thiếu dữ liệu — dùng thống nhất để UI không hiện "0"/"null".
  static const String missing = '—';

  /// `dd/MM/yyyy` — ví dụ 05/09/2026.
  static String date(DateTime? d) {
    if (d == null) return missing;
    final local = d.toLocal();
    return '${_pad2(local.day)}/${_pad2(local.month)}/${local.year}';
  }

  /// `dd/MM/yyyy HH:mm` — ví dụ 05/09/2026 06:30.
  static String dateTime(DateTime? d) {
    if (d == null) return missing;
    final local = d.toLocal();
    return '${date(local)} ${_pad2(local.hour)}:${_pad2(local.minute)}';
  }

  /// `HH:mm` — ví dụ 06:30.
  static String time(DateTime? d) {
    if (d == null) return missing;
    final local = d.toLocal();
    return '${_pad2(local.hour)}:${_pad2(local.minute)}';
  }

  /// Số thập phân kiểu Việt Nam: nghìn ngăn bằng `.`, thập phân bằng `,`.
  /// `fractionDigits` cố định số chữ số sau dấu phẩy; `null` = bỏ phần thập phân
  /// bằng 0 ở cuối. `value` null → placeholder (KHÔNG phải "0").
  static String number(num? value, {int? fractionDigits}) {
    if (value == null) return missing;
    final fixed = fractionDigits == null
        ? value.toString()
        : value.toStringAsFixed(fractionDigits);
    final negative = fixed.startsWith('-');
    final unsigned = negative ? fixed.substring(1) : fixed;
    final parts = unsigned.split('.');
    final intPart = parts.first;
    final fracPart = parts.length > 1 ? parts[1] : '';

    final grouped = _groupThousands(intPart);
    final trimmedFrac =
        fractionDigits == null ? _trimTrailingZeros(fracPart) : fracPart;
    final buffer = StringBuffer(negative ? '-' : '')..write(grouped);
    if (trimmedFrac.isNotEmpty) buffer.write(',$trimmedFrac');
    return buffer.toString();
  }

  /// Số kèm đơn vị: "12,5 kg". Đơn vị luôn cách một khoảng trắng.
  static String withUnit(num? value, String unit, {int? fractionDigits}) {
    final formatted = number(value, fractionDigits: fractionDigits);
    if (formatted == missing) return missing;
    return '$formatted $unit';
  }

  /// Phần trăm: 0.142 → "14%", 0.1423 với fractionDigits:1 → "14,2%".
  static String percent(num? ratio, {int fractionDigits = 0}) {
    if (ratio == null) return missing;
    return '${number(ratio * 100, fractionDigits: fractionDigits)}%';
  }

  static String _pad2(int n) => n.toString().padLeft(2, '0');

  static String _groupThousands(String digits) {
    final buffer = StringBuffer();
    for (var i = 0; i < digits.length; i++) {
      if (i != 0 && (digits.length - i) % 3 == 0) buffer.write('.');
      buffer.write(digits[i]);
    }
    return buffer.toString();
  }

  static String _trimTrailingZeros(String frac) {
    var end = frac.length;
    while (end > 0 && frac[end - 1] == '0') {
      end--;
    }
    return frac.substring(0, end);
  }
}

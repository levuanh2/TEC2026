import 'activity_field_spec.dart';
import 'crop_season.dart';
import 'methodology_enums.dart';

/// Một field đã parse từ chuỗi người dùng gõ.
///   - `error != null`  : gõ sai định dạng → PHẢI báo lỗi, KHÔNG lưu (không tự
///     biến thành null).
///   - `error == null && value == null` : bỏ trống (hợp lệ với field không bắt buộc).
///   - `value != null`  : giá trị đã parse (num / String / bool).
class ParsedField {
  const ParsedField(this.value, this.error);
  const ParsedField.empty() : this(null, null);
  final Object? value;
  final String? error;

  bool get isEmpty => value == null && error == null;
}

/// Parse theo [ActivityFieldKind]. `select`/`tristate` gọi [ParsedField.value]
/// trực tiếp (không qua đây).
ParsedField parseActivityField(ActivityFieldSpec spec, String raw) {
  final text = raw.trim();
  switch (spec.kind) {
    case ActivityFieldKind.text:
    case ActivityFieldKind.select:
    case ActivityFieldKind.tristate:
      return text.isEmpty ? const ParsedField.empty() : ParsedField(text, null);
    case ActivityFieldKind.integer:
      if (text.isEmpty) return const ParsedField.empty();
      final v = int.tryParse(text);
      return v == null
          ? const ParsedField(null, 'Phải là số nguyên.')
          : ParsedField(v, null);
    case ActivityFieldKind.decimal:
      if (text.isEmpty) return const ParsedField.empty();
      final v = double.tryParse(text.replaceAll(',', '.'));
      return v == null || v.isNaN || v.isInfinite
          ? const ParsedField(null, 'Số không hợp lệ.')
          : ParsedField(v, null);
  }
}

class ActivityValidation {
  ActivityValidation(this.fieldErrors, this.occurredAtError, this.warnings);

  final Map<String, String>
      fieldErrors; // key -> thông báo (chỉ chứa field lỗi)
  final String? occurredAtError;
  final List<String> warnings; // cảnh báo KHÔNG chặn lưu

  bool get hasError => occurredAtError != null || fieldErrors.isNotEmpty;
}

/// Kiểm tra toàn bộ form. [parsed] là map key → [ParsedField] cho MỌI field của
/// loại này (select/tristate truyền `ParsedField(value, null)` với value là
/// wire string / `'true'` / `'false'`, hoặc `ParsedField.empty()`).
ActivityValidation validateActivity({
  required String type,
  required Map<String, ParsedField> parsed,
  required DateTime occurredAt,
  DateTime? now,
  CropSeason? activeSeason,
}) {
  final errors = <String, String>{};
  final warnings = <String>[];
  final specs = kActivityFieldSpecs[type] ?? const [];

  final ref = now ?? DateTime.now();
  final occurredAtError =
      occurredAt.isAfter(ref) ? 'Thời điểm không được ở tương lai.' : null;

  for (final spec in specs) {
    final field = parsed[spec.key] ?? const ParsedField.empty();

    if (field.error != null) {
      errors[spec.key] = field.error!;
      continue;
    }

    final value = field.value;

    if (spec.required &&
        (value == null || (value is String && value.isEmpty))) {
      errors[spec.key] = 'Vui lòng nhập "${spec.label}".';
      continue;
    }
    if (value == null) continue;

    if (value is num) {
      if (spec.positive && value <= 0) {
        errors[spec.key] = '"${spec.label}" phải lớn hơn 0.';
      } else if (spec.nonNegative && value < 0) {
        errors[spec.key] = '"${spec.label}" không được là số âm.';
      } else if (spec.min != null && value < spec.min!) {
        errors[spec.key] = '"${spec.label}" phải từ ${_n(spec.min!)} trở lên.';
      } else if (spec.max != null && value > spec.max!) {
        errors[spec.key] = '"${spec.label}" không được vượt ${_n(spec.max!)}.';
      }
    }
  }

  // -- Ràng buộc có điều kiện --------------------------------------------
  if (type == 'straw_management') {
    final method = parsed['method']?.value as String?;
    if (method == 'incorporated') {
      for (final k in const [
        'dry_matter_fraction',
        'days_before_cultivation'
      ]) {
        final f = parsed[k];
        if (f == null || f.isEmpty) {
          final label = specs.firstWhere((s) => s.key == k).label;
          errors.putIfAbsent(k, () => 'Vùi vào đất thì cần "$label".');
        }
      }
    }
  }

  if (type == 'harvest') {
    final y = parsed['yield_kg'];
    if (y == null || y.isEmpty) {
      errors.putIfAbsent('yield_kg', () => 'Thu hoạch cần nhập sản lượng.');
    }
  }

  // -- Cảnh báo (không chặn — SRS FR-1a-04) -----------------------------
  if (type == 'irrigation') {
    final method = parsed['method']?.value as String?;
    final isAwd = method == 'awd' ||
        activeSeason?.ipccWaterRegime ==
            IpccWaterRegime.irrigatedMultipleDrainage;
    if (isAwd && (activeSeason?.drainageEventCount == null)) {
      warnings.add(
        'Ruộng tưới rút nước nhiều lần nhưng vụ chưa ghi "số lần rút nước". '
        'Vẫn lưu được — nên bổ sung ở màn vụ canh tác.',
      );
    }
  }

  return ActivityValidation(errors, occurredAtError, warnings);
}

String _n(num v) =>
    v == v.roundToDouble() ? v.toInt().toString() : v.toString();

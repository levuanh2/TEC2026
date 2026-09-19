import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../tokens.dart';

/// Loại ô nhập mà [AdaptiveFormField] biết render. Cố ý tách khỏi `FieldKind`
/// trong `models/activity_field_spec.dart` để lớp design không phụ thuộc domain
/// — màn form sẽ map giữa hai enum này.
enum AdaptiveFieldKind {
  text,
  multilineText,

  /// Số thập phân — bàn phím số, chấp nhận cả `.` và `,` (người Việt hay gõ `,`).
  decimal,

  /// Số nguyên — bàn phím số, chỉ chữ số.
  integer,

  /// Chọn 1 trong danh sách [AdaptiveFormField.options].
  select,

  /// 3 trạng thái: Có / Không / Chưa chọn. `value` là `'true'` / `'false'` /
  /// `null`. Dùng cho input phương pháp luận KHÔNG được tự mặc định `false`
  /// (xem CARBON_METHOD.md — `returned_to_field`, ...).
  tristate,
}

class AdaptiveFieldOption {
  const AdaptiveFieldOption(this.value, this.label);
  final String value;
  final String label;
}

/// Ô nhập "thích ứng": chọn control theo [kind], gắn nhãn + gợi ý + dấu bắt buộc
/// nhất quán, tôn trọng vùng chạm tối thiểu và text scale. Không tự validate —
/// caller kiểm tra và truyền [errorText].
///
/// - [kind] text/multiline/decimal/integer  → cần [controller].
/// - [kind] select/tristate                 → cần [value] + [onValueChanged].
class AdaptiveFormField extends StatelessWidget {
  const AdaptiveFormField({
    super.key,
    required this.label,
    required this.kind,
    this.controller,
    this.value,
    this.onValueChanged,
    this.options = const [],
    this.hint,
    this.helperText,
    this.errorText,
    this.required = false,
    this.enabled = true,
  });

  final String label;
  final AdaptiveFieldKind kind;

  final TextEditingController? controller;

  final String? value;
  final ValueChanged<String?>? onValueChanged;
  final List<AdaptiveFieldOption> options;

  final String? hint;
  final String? helperText;
  final String? errorText;
  final bool required;
  final bool enabled;

  String get _labelWithMark => required ? '$label *' : label;

  @override
  Widget build(BuildContext context) {
    switch (kind) {
      case AdaptiveFieldKind.select:
        return DropdownButtonFormField<String>(
          initialValue: value,
          isExpanded: true,
          decoration: _decoration(),
          items: [
            for (final o in options)
              DropdownMenuItem(value: o.value, child: Text(o.label)),
          ],
          onChanged: enabled ? onValueChanged : null,
        );

      case AdaptiveFieldKind.tristate:
        return _Tristate(
          label: _labelWithMark,
          value: value,
          hint: hint,
          errorText: errorText,
          onChanged: enabled ? onValueChanged : null,
        );

      case AdaptiveFieldKind.text:
      case AdaptiveFieldKind.multilineText:
      case AdaptiveFieldKind.decimal:
      case AdaptiveFieldKind.integer:
        final isMultiline = kind == AdaptiveFieldKind.multilineText;
        final isNumber = kind == AdaptiveFieldKind.decimal ||
            kind == AdaptiveFieldKind.integer;
        return TextField(
          controller: controller,
          enabled: enabled,
          minLines: isMultiline ? 2 : 1,
          maxLines: isMultiline ? 4 : 1,
          keyboardType: isMultiline
              ? TextInputType.multiline
              : isNumber
                  ? const TextInputType.numberWithOptions(decimal: true)
                  : TextInputType.text,
          inputFormatters: switch (kind) {
            AdaptiveFieldKind.integer => [
                FilteringTextInputFormatter.digitsOnly,
              ],
            AdaptiveFieldKind.decimal => [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
              ],
            _ => null,
          },
          decoration: _decoration(),
        );
    }
  }

  InputDecoration _decoration() => InputDecoration(
        labelText: _labelWithMark,
        hintText: hint,
        helperText: helperText,
        helperMaxLines: 3,
        errorText: errorText,
        errorMaxLines: 3,
      );
}

class _Tristate extends StatelessWidget {
  const _Tristate({
    required this.label,
    required this.value,
    required this.onChanged,
    this.hint,
    this.errorText,
  });

  final String label;
  final String? value; // 'true' | 'false' | null
  final ValueChanged<String?>? onChanged;
  final String? hint;
  final String? errorText;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: text.labelMedium),
        const SizedBox(height: AppSpacing.xxs),
        Wrap(
          spacing: AppSpacing.xs,
          children: [
            _chip(
                context, 'Chưa chọn', value == null, () => onChanged?.call(null)),
            _chip(
                context, 'Có', value == 'true', () => onChanged?.call('true')),
            _chip(context, 'Không', value == 'false',
                () => onChanged?.call('false')),
          ],
        ),
        if (hint != null) ...[
          const SizedBox(height: AppSpacing.xxs),
          Text(
            hint!,
            style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
          ),
        ],
        if (errorText != null) ...[
          const SizedBox(height: AppSpacing.xxs),
          Text(
            errorText!,
            style: text.labelSmall?.copyWith(color: AppColors.error),
          ),
        ],
      ],
    );
  }

  Widget _chip(
      BuildContext context, String label, bool selected, VoidCallback onTap) {
    return ChoiceChip(
      label: Text(label),
      selected: selected,
      onSelected: onChanged == null ? null : (_) => onTap(),
    );
  }
}

import 'package:flutter/material.dart';

import '../app_format.dart';
import '../tokens.dart';
import 'app_card.dart';
import 'status_badge.dart';

/// Thẻ hiển thị một chỉ số "trên mỗi kg" (carbon/kg, nước/kg, phân/kg, chi
/// phí/kg) hoặc số liệu tổng hợp.
///
/// Nguyên tắc "không bịa số": truyền [value] = `null` khi CHƯA có dữ liệu →
/// thẻ hiện [missingLabel] ("Chưa có sản lượng...") thay vì "0". Caller tự tính
/// và định dạng [value] (dùng `AppFormat`), component không tự suy diễn.
class MetricCard extends StatelessWidget {
  const MetricCard({
    super.key,
    required this.label,
    required this.value,
    this.unit,
    this.deltaLabel,
    this.deltaTone = StatusTone.positive,
    this.footnote,
    this.hero = false,
    this.missingLabel = 'Chưa có dữ liệu',
    this.onTap,
  });

  final String label;

  /// Giá trị ĐÃ định dạng để hiển thị. `null` = chưa tính được.
  final String? value;
  final String? unit;

  /// Nhãn thay đổi so với kỳ trước / benchmark (ví dụ "↓ so kỳ trước"). Caller
  /// tự tính từ dữ liệu thật; `null` = ẩn.
  final String? deltaLabel;
  final StatusTone deltaTone;

  /// Dòng chú thích nhỏ dưới cùng ("Tính theo bộ hệ số ...").
  final String? footnote;

  /// Kiểu "anh hùng": số rất lớn, nền xanh nhạt (màn kết quả carbon).
  final bool hero;

  final String missingLabel;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final hasValue = value != null;

    return AppCard(
      variant: hero ? AppCardVariant.highlight : AppCardVariant.plain,
      onTap: onTap,
      padding: EdgeInsets.all(hero ? AppSpacing.lg : AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: text.labelMedium
                      ?.copyWith(color: AppColors.textSecondary),
                ),
              ),
              if (deltaLabel != null)
                StatusBadge(label: deltaLabel!, tone: deltaTone),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          if (hasValue)
            _ValueLine(value: value!, unit: unit, hero: hero)
          else
            Text(
              missingLabel,
              style: text.bodyMedium?.copyWith(
                color: AppColors.warningText,
                fontWeight: FontWeight.w600,
              ),
            ),
          if (footnote != null) ...[
            const SizedBox(height: AppSpacing.xs),
            Text(
              footnote!,
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
            ),
          ],
        ],
      ),
    );
  }
}

class _ValueLine extends StatelessWidget {
  const _ValueLine(
      {required this.value, required this.unit, required this.hero});

  final String value;
  final String? unit;
  final bool hero;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.end,
      spacing: AppSpacing.xs,
      children: [
        Text(
          value,
          style: hero ? text.displayLarge : text.headlineSmall,
        ),
        if (unit != null && unit != AppFormat.missing)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Text(
              unit!,
              style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
            ),
          ),
      ],
    );
  }
}

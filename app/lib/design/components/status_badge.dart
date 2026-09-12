import 'package:flutter/material.dart';

import '../tokens.dart';

/// Sắc thái của [StatusBadge] — bám đúng bảng màu SVG.
enum StatusTone {
  /// Xanh: đã đồng bộ / tốt hơn benchmark / xu hướng giảm.
  positive,

  /// Hổ phách: "chưa gửi", "cần kiểm tra", độ tin cậy thấp.
  warning,

  /// Xám trung tính: đang chờ / chưa bắt đầu.
  neutral,

  /// Đỏ: lỗi thật.
  danger,
}

/// Nhãn trạng thái hình viên thuốc (pill). Chỉ chữ + màu — KHÔNG tự suy ra
/// trạng thái, caller truyền [tone] và [label] rõ ràng.
class StatusBadge extends StatelessWidget {
  const StatusBadge({
    super.key,
    required this.label,
    this.tone = StatusTone.neutral,
    this.icon,
  });

  final String label;
  final StatusTone tone;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final (fg, bg) = switch (tone) {
      StatusTone.positive => (AppColors.primary, AppColors.primarySurface),
      StatusTone.warning => (AppColors.warningText, AppColors.warningSurface),
      StatusTone.neutral => (AppColors.textSecondary, AppColors.track),
      StatusTone.danger => (AppColors.error, AppColors.errorSurface),
    };

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xxs + 2,
      ),
      decoration: BoxDecoration(color: bg, borderRadius: AppRadii.allPill),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 14, color: fg),
            const SizedBox(width: 4),
          ],
          Text(
            label,
            style:
                TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: fg),
          ),
        ],
      ),
    );
  }
}

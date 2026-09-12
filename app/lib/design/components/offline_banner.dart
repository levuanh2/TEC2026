import 'package:flutter/material.dart';

import '../tokens.dart';

/// Dải thông báo mất mạng (SVG màn "ghi nhanh": nền [AppColors.warningSurface],
/// chữ [AppColors.warningText]). Nội dung nhấn mạnh: dữ liệu VẪN được lưu trên
/// máy — trấn an nông dân, đúng tinh thần offline-first.
///
/// Đây là banner tĩnh: caller tự quyết định khi nào hiển thị (dựa trên trạng
/// thái mạng / hàng đợi), component không tự dò mạng.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({
    super.key,
    this.message = 'Không có mạng — công việc vẫn được lưu trên điện thoại.',
    this.icon = Icons.cloud_off_outlined,
  });

  final String message;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: AppColors.warningSurface,
        borderRadius: BorderRadius.circular(AppRadii.sm),
      ),
      child: Row(
        children: [
          Icon(icon, size: 18, color: AppColors.warningText),
          const SizedBox(width: AppSpacing.xs),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: AppColors.warningText,
                height: 1.3,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

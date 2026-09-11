import 'package:flutter/material.dart';

import '../design/design.dart';
import '../models/activity.dart';
import '../models/activity_field_spec.dart';

/// Bảng chọn đủ 7 loại hoạt động ("Xem tất cả" ở màn Ghi nhanh / Trang chủ).
/// Trả về `activity_type` (wire) hoặc `null` nếu huỷ. Icon Material, KHÔNG emoji.
Future<String?> showActivityTypeSheet(BuildContext context) {
  return showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    builder: (context) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.md,
              AppSpacing.xs,
              AppSpacing.md,
              AppSpacing.sm,
            ),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text('Chọn loại hoạt động',
                  style: Theme.of(context).textTheme.titleMedium),
            ),
          ),
          for (final type in kActivityTypes)
            ListTile(
              leading: Icon(kActivityTypeIcons[type], color: AppColors.primary),
              title: Text(kActivityTypeLabels[type] ?? type),
              onTap: () => Navigator.pop(context, type),
            ),
          const SizedBox(height: AppSpacing.sm),
        ],
      ),
    ),
  );
}

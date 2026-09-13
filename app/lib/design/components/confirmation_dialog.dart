import 'package:flutter/material.dart';

import '../tokens.dart';
import 'buttons.dart';

/// Hộp thoại xác nhận dùng chung cho hành động khó hoàn tác (đăng xuất, thoát
/// khi còn dữ liệu chưa lưu...). Trả `true` nếu người dùng đồng ý, `false`/`null`
/// nếu huỷ.
///
/// [destructive] = true đổi nút xác nhận sang màu đỏ (xoá / bỏ thay đổi).
class ConfirmationDialog extends StatelessWidget {
  const ConfirmationDialog({
    super.key,
    required this.title,
    required this.message,
    this.confirmLabel = 'Xác nhận',
    this.cancelLabel = 'Huỷ',
    this.destructive = false,
  });

  final String title;
  final String message;
  final String confirmLabel;
  final String cancelLabel;
  final bool destructive;

  static Future<bool> show(
    BuildContext context, {
    required String title,
    required String message,
    String confirmLabel = 'Xác nhận',
    String cancelLabel = 'Huỷ',
    bool destructive = false,
  }) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (_) => ConfirmationDialog(
        title: title,
        message: message,
        confirmLabel: confirmLabel,
        cancelLabel: cancelLabel,
        destructive: destructive,
      ),
    );
    return result ?? false;
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(title),
      content: Text(message),
      actionsPadding: const EdgeInsets.fromLTRB(
        AppSpacing.md,
        0,
        AppSpacing.md,
        AppSpacing.md,
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(cancelLabel),
        ),
        if (destructive)
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: TextButton.styleFrom(foregroundColor: AppColors.error),
            child: Text(confirmLabel),
          )
        else
          PrimaryButton(
            label: confirmLabel,
            expanded: false,
            onPressed: () => Navigator.of(context).pop(true),
          ),
      ],
    );
  }
}

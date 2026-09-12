import 'package:flutter/material.dart';

import '../tokens.dart';

/// Nút hành động chính — nền xanh [AppColors.primary], chữ trắng, bo góc
/// [AppRadii.xs], cao tối thiểu [kMinTouchTarget]. Mặc định giãn hết chiều ngang
/// (SVG luôn dùng nút full-width cho hành động chính).
///
/// Truyền [loading] = true để hiện spinner và tự khoá nút (tránh double-submit).
class PrimaryButton extends StatelessWidget {
  const PrimaryButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.loading = false,
    this.expanded = true,
  });

  final String label;

  /// `null` = nút bị vô hiệu hoá.
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool loading;
  final bool expanded;

  @override
  Widget build(BuildContext context) {
    final child = loading
        ? const SizedBox(
            width: 20,
            height: 20,
            child:
                CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
          )
        : Text(label, textAlign: TextAlign.center);

    final button = icon != null && !loading
        ? ElevatedButton.icon(
            onPressed: loading ? null : onPressed,
            icon: Icon(icon, size: 20),
            label: Text(label),
          )
        : ElevatedButton(
            onPressed: loading ? null : onPressed,
            child: child,
          );

    if (!expanded) return button;
    return SizedBox(width: double.infinity, child: button);
  }
}

/// Nút phụ — viền [AppColors.border], chữ [AppColors.textPrimary]. Dùng cho
/// hành động thứ cấp ("Chỉnh lại", "Xem chi tiết", "Thử tải lại").
class SecondaryButton extends StatelessWidget {
  const SecondaryButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.expanded = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool expanded;

  @override
  Widget build(BuildContext context) {
    final button = icon != null
        ? OutlinedButton.icon(
            onPressed: onPressed,
            icon: Icon(icon, size: 20),
            label: Text(label),
          )
        : OutlinedButton(onPressed: onPressed, child: Text(label));

    if (!expanded) return button;
    return SizedBox(width: double.infinity, child: button);
  }
}

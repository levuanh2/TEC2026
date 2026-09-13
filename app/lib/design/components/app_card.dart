import 'package:flutter/material.dart';

import '../tokens.dart';

/// Loại nền cho [AppCard] — theo 3 kiểu card trong SVG.
enum AppCardVariant {
  /// Nền trắng, viền mảnh (card danh sách / thông tin).
  plain,

  /// Nền xanh nhạt [AppColors.primarySurface], không viền (card nhấn mạnh:
  /// "việc cần làm hôm nay", "trạng thái đồng bộ").
  highlight,

  /// Nền cảnh báo [AppColors.warningSurface] (thông báo mất mạng, cần kiểm tra).
  warning,
}

/// Thẻ bo góc dùng chung. Không tự thêm margin — khoảng cách do layout cha
/// quyết định. Bấm được khi truyền [onTap].
class AppCard extends StatelessWidget {
  const AppCard({
    super.key,
    required this.child,
    this.variant = AppCardVariant.plain,
    this.padding = const EdgeInsets.all(AppSpacing.md),
    this.onTap,
  });

  final Widget child;
  final AppCardVariant variant;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final (bg, border) = switch (variant) {
      AppCardVariant.plain => (AppColors.surface, AppColors.border),
      AppCardVariant.highlight => (
          AppColors.primarySurface,
          Colors.transparent
        ),
      AppCardVariant.warning => (AppColors.warningSurface, Colors.transparent),
    };

    return Material(
      color: bg,
      borderRadius: AppRadii.allCard,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            borderRadius: AppRadii.allCard,
            border: Border.all(color: border),
          ),
          padding: padding,
          child: child,
        ),
      ),
    );
  }
}

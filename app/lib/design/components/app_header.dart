import 'package:flutter/material.dart';

import '../theme.dart';
import '../tokens.dart';

/// Thanh header tối theo SVG: nền [AppColors.headerDark], tiêu đề trắng + dòng
/// mô tả xanh nhạt, chấm trạng thái mạng ở góc phải (tùy chọn).
///
/// KHÔNG phải `AppBar` — SVG vẽ header như một khối nội dung phẳng, cao ~86 ở
/// frame gốc nhưng ở đây co theo nội dung + SafeArea (notch). Dùng trong
/// [AppScaffold] hoặc trực tiếp trên đầu một `Column`.
class AppHeader extends StatelessWidget {
  const AppHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.isOnline,
    this.leading,
    this.showBackButton = false,
    this.actions = const [],
  });

  final String title;
  final String? subtitle;

  /// `null` = không hiển thị chấm trạng thái. `true`/`false` đổi màu chấm.
  final bool? isOnline;

  /// Widget dẫn đầu tuỳ ý. Nếu để trống và [showBackButton] = true, tự chèn nút
  /// quay lại (dùng cho các màn route phụ được push chồng lên shell).
  final Widget? leading;
  final bool showBackButton;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.headerDark,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.screenH,
            AppSpacing.sm,
            AppSpacing.md,
            AppSpacing.sm,
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              if (leading != null) ...[
                leading!,
                const SizedBox(width: AppSpacing.xs),
              ] else if (showBackButton) ...[
                IconButton(
                  icon: const Icon(Icons.arrow_back),
                  color: AppColors.onHeaderPrimary,
                  tooltip: 'Quay lại',
                  onPressed: () => Navigator.of(context).maybePop(),
                ),
                const SizedBox(width: AppSpacing.xxs),
              ],
              Expanded(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: AgriCarbonTheme.headerTitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        subtitle!,
                        style: AgriCarbonTheme.headerSubtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ],
                ),
              ),
              if (isOnline != null) ...[
                const SizedBox(width: AppSpacing.xs),
                _StatusDot(online: isOnline!),
              ],
              ...actions,
            ],
          ),
        ),
      ),
    );
  }
}

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.online});
  final bool online;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: online ? 'Đang có mạng' : 'Đang ngoại tuyến',
      child: Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: online ? AppColors.onHeaderDot : AppColors.warningText,
        ),
      ),
    );
  }
}

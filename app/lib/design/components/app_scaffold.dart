import 'package:flutter/material.dart';

import '../tokens.dart';
import 'app_header.dart';

/// Khung màn hình chuẩn: nền [AppColors.background], [AppHeader] tối tuỳ chọn ở
/// trên, nội dung có padding ngang [AppSpacing.screenH], và [SafeArea] cho notch
/// + thanh điều hướng cử chỉ ở dưới.
///
/// Responsive: KHÔNG đặt width/height cố định. Khi [scrollable] = true (mặc
/// định), nội dung bọc trong `SingleChildScrollView` nên bàn phím không che nút
/// và không tràn khi text scale lớn. Truyền [bottomBar] cho nút hành động ghim
/// đáy (ví dụ "Lưu công việc"), nó nằm NGOÀI vùng cuộn và trên SafeArea.
class AppScaffold extends StatelessWidget {
  const AppScaffold({
    super.key,
    required this.body,
    this.header,
    this.bottomBar,
    this.floatingActionButton,
    this.scrollable = true,
    this.padded = true,
    this.backgroundColor,
    this.onRefresh,
  });

  /// Header tối. `null` = màn không có header (hiếm — thường là màn full-bleed).
  final AppHeader? header;

  final Widget body;

  /// Vùng nút ghim đáy, ngoài vùng cuộn (ví dụ "Lưu công việc"). Thanh 4 tab
  /// của shell KHÔNG đi qua đây — nó do `HomeShell` gắn ở `Scaffold` ngoài.
  final Widget? bottomBar;

  final Widget? floatingActionButton;

  /// Bọc [body] trong vùng cuộn dọc. Tắt khi màn tự quản lý cuộn (ví dụ có
  /// `ListView` riêng bên trong).
  final bool scrollable;

  /// Thêm padding ngang chuẩn cho [body].
  final bool padded;

  final Color? backgroundColor;

  /// Kéo-để-làm-mới. Chỉ có tác dụng khi [scrollable] = true.
  final Future<void> Function()? onRefresh;

  @override
  Widget build(BuildContext context) {
    Widget content = body;
    if (padded) {
      content = Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenH),
        child: content,
      );
    }

    if (scrollable) {
      // Bắt biến vào local final TRƯỚC khi gán lại `content` — closure của
      // LayoutBuilder mà tham chiếu thẳng `content` sẽ tự trỏ vào chính nó
      // (đệ quy layout vô hạn).
      final scrollBody = content;
      content = LayoutBuilder(
        builder: (context, constraints) => SingleChildScrollView(
          padding: const EdgeInsets.only(
            top: AppSpacing.md,
            bottom: AppSpacing.xl,
          ),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: constraints.maxHeight),
            child: scrollBody,
          ),
        ),
      );
      if (onRefresh != null) {
        final refreshBody = content;
        content = RefreshIndicator(onRefresh: onRefresh!, child: refreshBody);
      }
    }

    return Scaffold(
      backgroundColor: backgroundColor ?? AppColors.background,
      // Đã tự xử lý SafeArea đáy trong body/bottomBar để giữ nền header chạm
      // mép trên; không để Scaffold tự né bàn phím hai lần.
      resizeToAvoidBottomInset: true,
      floatingActionButton: floatingActionButton,
      body: Column(
        children: [
          if (header != null) header!,
          Expanded(child: content),
          if (bottomBar != null)
            SafeArea(
              top: false,
              minimum: const EdgeInsets.fromLTRB(
                AppSpacing.screenH,
                AppSpacing.sm,
                AppSpacing.screenH,
                AppSpacing.sm,
              ),
              child: bottomBar!,
            ),
        ],
      ),
    );
  }
}

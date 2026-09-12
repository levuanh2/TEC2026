import 'package:flutter/material.dart';

import '../design/design.dart';

/// Hiện khi khởi tạo app thất bại (Supabase.initialize ném, lỗi mở SQLite, ...).
/// KHÔNG in chi tiết lỗi (có thể chứa URL/key). Chỉ gợi ý người dùng thử lại.
///
/// Không có nút "thử lại" trong app vì lỗi xảy ra trước khi có service — người
/// dùng cần mở lại ứng dụng.
class BootstrapErrorScreen extends StatelessWidget {
  const BootstrapErrorScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const AppScaffold(
      header: AppHeader(title: 'AgriCarbon'),
      body: ErrorState(
        title: 'Không khởi động được ứng dụng',
        message:
            'Vui lòng đóng và mở lại ứng dụng. Nếu vẫn lỗi, liên hệ quản lý '
            'HTX của bạn.',
      ),
    );
  }
}

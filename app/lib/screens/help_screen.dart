import 'package:flutter/material.dart';

import '../design/design.dart';

/// Màn "Trợ giúp" (từ SVG 26). Hướng dẫn ngắn gọn cách dùng app.
///
/// KHÔNG có số tổng đài giả (SVG chỉ vẽ minh hoạ). Kênh hỗ trợ thật ở giai đoạn
/// thí điểm là cán bộ HTX phụ trách — không bịa tổng đài.
class HelpScreen extends StatelessWidget {
  const HelpScreen({super.key});

  static const _guide = <(String, String)>[
    (
      'Ghi khi đang ở ngoài ruộng',
      'Mọi công việc (tưới, bón phân, thu hoạch…) lưu ngay trên máy, không cần '
          'mạng. "Thời gian làm" giữ đúng lúc bạn thao tác thực tế.',
    ),
    (
      'Gửi dữ liệu khi có mạng',
      'App tự gửi khi có mạng, hoặc bạn bấm "Gửi dữ liệu ngay" ở tab Gửi dữ '
          'liệu. Có thể chọn chỉ gửi qua Wi-Fi trong Cài đặt gửi dữ liệu.',
    ),
    (
      'Xem kết quả của vụ',
      'Sau khi dữ liệu đã lên hệ thống, mở "Kết quả phát thải" và "Hiệu quả tài '
          'nguyên" để xem các chỉ số trên mỗi kg lúa. Thiếu dữ liệu thì hiện '
          '"Chưa đủ dữ liệu", không hiện số 0.',
    ),
    (
      'Số liệu là của hệ thống',
      'Ứng dụng không tự tính phát thải hay tự đưa ra lời khuyên liều lượng. '
          'Các con số do máy chủ tính từ nhật ký bạn đã ghi.',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: const AppHeader(title: 'Trợ giúp', showBackButton: true),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: AppSpacing.sm),
          Text('Hướng dẫn nhanh', style: text.titleMedium),
          const SizedBox(height: AppSpacing.sm),
          for (final g in _guide) ...[
            AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(g.$1, style: text.titleSmall),
                  const SizedBox(height: AppSpacing.xxs),
                  Text(
                    g.$2,
                    style: text.bodyMedium
                        ?.copyWith(color: AppColors.textSecondary),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
          ],
          const SizedBox(height: AppSpacing.sm),
          Text('Liên hệ hỗ trợ', style: text.titleMedium),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            'Trong giai đoạn thí điểm, liên hệ cán bộ HTX phụ trách của bạn để '
            'được hỗ trợ về tài khoản, dữ liệu và cách dùng ứng dụng.',
            style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }
}

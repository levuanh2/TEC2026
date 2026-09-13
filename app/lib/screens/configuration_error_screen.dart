import 'package:flutter/material.dart';

import '../design/design.dart';

/// Hiện khi build thiếu `--dart-define`. Chỉ liệt kê TÊN biến còn thiếu — không
/// bao giờ in giá trị. Render được mà không cần Supabase (dùng trước init).
class ConfigurationErrorScreen extends StatelessWidget {
  const ConfigurationErrorScreen({super.key, required this.missingKeys});

  final List<String> missingKeys;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: const AppHeader(
        title: 'AgriCarbon',
        subtitle: 'Chưa cấu hình',
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: AppSpacing.lg),
          Icon(Icons.settings_suggest_outlined,
              size: 56, color: AppColors.warningText),
          const SizedBox(height: AppSpacing.md),
          Text('Ứng dụng chưa được cấu hình', style: text.headlineSmall),
          const SizedBox(height: AppSpacing.xs),
          Text(
            'Bản dựng này thiếu tham số bắt buộc. Người cài đặt cần dựng lại app '
            'kèm các giá trị sau (qua --dart-define):',
            style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.md),
          AppCard(
            variant: AppCardVariant.warning,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final key in missingKeys)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(
                      children: [
                        const Icon(Icons.chevron_right,
                            size: 18, color: AppColors.warningText),
                        const SizedBox(width: AppSpacing.xxs),
                        Expanded(
                          child: Text(
                            key,
                            style: text.bodyLarge?.copyWith(
                              color: AppColors.warningText,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            'Xem hướng dẫn build ở app/README.md.',
            style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }
}

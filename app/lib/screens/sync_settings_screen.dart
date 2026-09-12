import 'package:flutter/material.dart';

import '../design/design.dart';
import '../services/sync_coordinator.dart';

/// Màn "Cài đặt gửi dữ liệu" — chọn mạng khi tự động gửi dữ liệu.
/// Tuỳ chọn lưu LOCAL theo user (bảng `meta`, key `sync.wifi_only`).
class SyncSettingsScreen extends StatelessWidget {
  const SyncSettingsScreen({super.key, required this.coordinator});
  final SyncCoordinator coordinator;

  SyncCoordinator get _co => coordinator;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: const AppHeader(
        title: 'Cài đặt gửi dữ liệu',
        showBackButton: true,
      ),
      body: ListenableBuilder(
        listenable: _co,
        builder: (context, _) {
          final wifiOnly = _co.wifiOnly;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: AppSpacing.md),
              Text('Tự động gửi dữ liệu qua', style: text.titleMedium),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'Dữ liệu luôn được lưu trên máy ngay khi bạn nhập. Tuỳ chọn này '
                'chỉ quyết định khi nào app TỰ gửi lên hệ thống — bạn vẫn có thể '
                'bấm "Gửi dữ liệu ngay" bất cứ lúc nào.',
                style:
                    text.bodyMedium?.copyWith(color: AppColors.textSecondary),
              ),
              const SizedBox(height: AppSpacing.md),
              RadioGroup<bool>(
                groupValue: wifiOnly,
                onChanged: (v) {
                  if (v != null) _co.setWifiOnly(v);
                },
                child: Column(
                  children: [
                    _OptionCard(
                      value: false,
                      selected: !wifiOnly,
                      title: 'Wi-Fi và dữ liệu di động',
                      subtitle: 'Tự gửi ngay khi có mạng, kể cả 3G/4G.',
                      onTap: () => _co.setWifiOnly(false),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    _OptionCard(
                      value: true,
                      selected: wifiOnly,
                      title: 'Chỉ Wi-Fi',
                      subtitle:
                          'Chỉ tự gửi khi có Wi-Fi — tiết kiệm dung lượng '
                          'dữ liệu di động.',
                      onTap: () => _co.setWifiOnly(true),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _OptionCard extends StatelessWidget {
  const _OptionCard({
    required this.value,
    required this.selected,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final bool value;
  final bool selected;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      variant: selected ? AppCardVariant.highlight : AppCardVariant.plain,
      onTap: onTap,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Radio<bool>(value: value),
          const SizedBox(width: AppSpacing.xs),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: text.titleSmall),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  style:
                      text.labelSmall?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

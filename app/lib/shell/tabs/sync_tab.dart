import 'package:flutter/material.dart';

import '../../design/design.dart';
import '../../models/sync_queue_item.dart';
import '../../models/sync_state.dart';
import '../../services/sync_coordinator.dart';
import '../../services/sync_errors.dart';

/// Tab "Gửi dữ liệu" (SVG 23). Đọc hàng đợi từ [SyncCoordinator] (nguồn:
/// SQLite), hiện trạng thái mạng + mốc gửi gần nhất + danh sách `pending/failed`,
/// nút "Gửi dữ liệu ngay". Không bao giờ hiện exception kỹ thuật.
class SyncTab extends StatelessWidget {
  const SyncTab({
    super.key,
    required this.coordinator,
    this.onOpenSettings,
    this.onFixActivity,
  });

  final SyncCoordinator coordinator;
  final VoidCallback? onOpenSettings;

  /// Mở bản ghi hoạt động (theo `client_event_id`) để sửa — cho các lỗi chỉ
  /// sửa dữ liệu mới gửi được (vd. diện tích thu hoạch vượt thửa).
  final Future<void> Function(String clientEventId)? onFixActivity;

  SyncCoordinator get _co => coordinator;

  Future<void> _sendNow(BuildContext context) async {
    if (_co.isSyncing) return;
    if (_co.blockedByWifiOnly) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Đang bật "Chỉ gửi qua Wi-Fi"'),
          content: const Text(
            'Bạn đang dùng dữ liệu di động. Vẫn gửi lần này? '
            '(Có thể tốn dung lượng mạng.)',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Để sau'),
            ),
            PrimaryButton(
              label: 'Vẫn gửi',
              expanded: false,
              onPressed: () => Navigator.pop(context, true),
            ),
          ],
        ),
      );
      if (ok != true) return;
      await _co.runSync(manual: true, overrideWifiOnly: true);
      return;
    }
    await _co.runSync(manual: true);
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _co,
      builder: (context, _) {
        final syncing = _co.isSyncing;
        final canSend = !syncing &&
            _co.status != SyncStatus.offline &&
            _co.pendingCount > 0;

        return AppScaffold(
          header: AppHeader(
            title: 'AgriCarbon',
            subtitle: 'Gửi dữ liệu',
            isOnline: _co.status != SyncStatus.offline,
            actions: [
              if (onOpenSettings != null)
                IconButton(
                  onPressed: onOpenSettings,
                  icon: const Icon(Icons.settings_outlined,
                      color: AppColors.onHeaderPrimary),
                  tooltip: 'Cài đặt gửi dữ liệu',
                ),
            ],
          ),
          scrollable: false,
          padded: false,
          bottomBar: PrimaryButton(
            label: syncing ? 'Đang gửi...' : 'Gửi dữ liệu ngay',
            loading: syncing,
            onPressed: canSend ? () => _sendNow(context) : null,
          ),
          body: RefreshIndicator(
            onRefresh: _co.refresh,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.screenH,
                AppSpacing.md,
                AppSpacing.screenH,
                AppSpacing.xl,
              ),
              children: [
                _StatusCard(coordinator: _co),
                const SizedBox(height: AppSpacing.lg),
                _QueueSection(coordinator: _co, onFixActivity: onFixActivity),
                const SizedBox(height: AppSpacing.lg),
                const _TimestampsCard(),
              ],
            ),
          ),
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.coordinator});
  final SyncCoordinator coordinator;

  ({String text, IconData icon, Color color}) _line() {
    switch (coordinator.status) {
      case SyncStatus.offline:
        return (
          text: 'Điện thoại đang không có mạng',
          icon: Icons.cloud_off_outlined,
          color: AppColors.textSecondary,
        );
      case SyncStatus.syncing:
        return (
          text: 'Đang gửi dữ liệu lên hệ thống...',
          icon: Icons.sync,
          color: AppColors.primary,
        );
      case SyncStatus.partialSuccess:
        return (
          text:
              'Đã gửi một phần — còn ${coordinator.pendingCount} mục chưa gửi',
          icon: Icons.sync_problem_outlined,
          color: AppColors.warningText,
        );
      case SyncStatus.failed:
        return (
          text: 'Lần gửi vừa rồi chưa thành công — sẽ thử lại',
          icon: Icons.sync_problem_outlined,
          color: AppColors.warningText,
        );
      case SyncStatus.authExpired:
        return (
          text: 'Phiên đăng nhập có vấn đề — hãy đăng nhập lại rồi thử gửi',
          icon: Icons.lock_outline,
          color: AppColors.error,
        );
      case SyncStatus.allSynced:
        return (
          text: 'Đã gửi hết — không còn mục nào chờ',
          icon: Icons.cloud_done_outlined,
          color: AppColors.primary,
        );
      case SyncStatus.idle:
        return (
          text: 'Điện thoại đang có mạng',
          icon: Icons.wifi,
          color: AppColors.primary,
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final l = _line();
    final last = coordinator.lastSyncAt;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Trạng thái', style: text.labelSmall),
          const SizedBox(height: AppSpacing.xs),
          Row(
            children: [
              Icon(l.icon, color: l.color, size: 20),
              const SizedBox(width: AppSpacing.xs),
              Expanded(child: Text(l.text, style: text.bodyMedium)),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            last == null
                ? 'Chưa gửi lần nào'
                : 'Lần gửi gần nhất: ${AppFormat.dateTime(last)}',
            style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
          ),
          if (coordinator.wifiOnly) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(
              coordinator.blockedByWifiOnly
                  ? 'Đang bật "Chỉ Wi-Fi" — kết nối Wi-Fi để tự gửi'
                  : 'Đang bật "Chỉ gửi qua Wi-Fi"',
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
            ),
          ],
        ],
      ),
    );
  }
}

class _QueueSection extends StatelessWidget {
  const _QueueSection({required this.coordinator, this.onFixActivity});
  final SyncCoordinator coordinator;
  final Future<void> Function(String clientEventId)? onFixActivity;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final items = coordinator.queue;

    if (items.isEmpty) {
      return const AppCard(
        child: Padding(
          padding: EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: Row(
            children: [
              Icon(Icons.check_circle_outline, color: AppColors.primary),
              SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  'Không có mục nào chờ gửi. Ghi hoạt động mới ở tab "Ghi nhanh".',
                ),
              ),
            ],
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('Chưa gửi lên', style: text.titleMedium),
            Text('${items.length} mục',
                style:
                    text.labelSmall?.copyWith(color: AppColors.textSecondary)),
          ],
        ),
        const SizedBox(height: AppSpacing.xs),
        for (final it in items) ...[
          _QueueRow(item: it, onFixActivity: onFixActivity),
          const SizedBox(height: AppSpacing.sm),
        ],
      ],
    );
  }
}

class _QueueRow extends StatelessWidget {
  const _QueueRow({required this.item, this.onFixActivity});
  final SyncQueueItem item;
  final Future<void> Function(String clientEventId)? onFixActivity;

  /// Lỗi chỉ hết khi SỬA bản ghi — gửi lại y nguyên luôn hỏng.
  bool get _needsEdit =>
      item.kind == SyncQueueKind.activity &&
      !item.isTombstone &&
      item.syncState == SyncState.failed &&
      item.errorCode == SyncErrorKind.harvestAreaExceedsPlot.name;

  (String, StatusTone) _badge() {
    if (item.syncState == SyncState.failed) {
      final kind = SyncErrorKind.values.firstWhere(
        (k) => k.name == item.errorCode,
        orElse: () => SyncErrorKind.unknown,
      );
      if (kind == SyncErrorKind.rlsDenied) {
        return ('Không có quyền', StatusTone.danger);
      }
      if (kind == SyncErrorKind.auth) {
        return ('Hết phiên', StatusTone.danger);
      }
      if (kind == SyncErrorKind.harvestAreaExceedsPlot) {
        return ('Cần sửa', StatusTone.danger);
      }
      return ('Gửi lỗi', StatusTone.warning);
    }
    if (item.syncState == SyncState.syncing) {
      return ('Đang gửi', StatusTone.neutral);
    }
    return ('Chưa gửi', StatusTone.warning);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final (badgeLabel, badgeTone) = _badge();
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(item.title,
                    style: text.titleSmall,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis),
              ),
              const SizedBox(width: AppSpacing.xs),
              StatusBadge(label: badgeLabel, tone: badgeTone),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            item.subtitle,
            style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
          ),
          if (item.syncState == SyncState.failed && item.errorCode != null) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(
              _friendlyError(item.errorCode!),
              style: text.labelSmall?.copyWith(color: AppColors.warningText),
            ),
          ],
          if (_needsEdit && onFixActivity != null) ...[
            const SizedBox(height: AppSpacing.xs),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                onPressed: () => onFixActivity!(item.clientId),
                icon: const Icon(Icons.edit_outlined, size: 18),
                label: const Text('Sửa bản ghi'),
              ),
            ),
          ],
          if (item.retryCount > 0) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(
              'Đã thử ${item.retryCount} lần'
              '${item.lastAttemptAt != null ? ' · gần nhất ${AppFormat.dateTime(item.lastAttemptAt)}' : ''}',
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
            ),
          ],
        ],
      ),
    );
  }

  static String _friendlyError(String code) {
    final kind = SyncErrorKind.values.firstWhere(
      (k) => k.name == code,
      orElse: () => SyncErrorKind.unknown,
    );
    return syncErrorMessage(kind);
  }
}

class _TimestampsCard extends StatelessWidget {
  const _TimestampsCard();

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    Widget line(String label, String desc) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '$label: ',
                style: text.bodySmall?.copyWith(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w600,
                ),
              ),
              Expanded(
                child: Text(
                  desc,
                  style:
                      text.bodySmall?.copyWith(color: AppColors.textSecondary),
                ),
              ),
            ],
          ),
        );

    return AppCard(
      variant: AppCardVariant.highlight,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Các mốc thời gian', style: text.titleSmall),
          const SizedBox(height: AppSpacing.xs),
          line('Thời gian làm', 'giữ đúng lúc ngoài ruộng'),
          line('Thời gian ghi', 'lúc nhập trên điện thoại'),
          line('Thời gian gửi', 'lúc dữ liệu lên hệ thống'),
        ],
      ),
    );
  }
}

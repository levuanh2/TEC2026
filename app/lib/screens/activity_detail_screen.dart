import 'package:flutter/material.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../models/activity.dart';
import '../models/activity_field_spec.dart';
import 'activity_form_screen.dart';

/// Xem chi tiết 1 hoạt động + Sửa / Xoá.
///
/// - Xoá bản ghi CHƯA đồng bộ → xoá hẳn local (sau xác nhận).
/// - Xoá bản ghi ĐÃ đồng bộ → tombstone local, chờ đẩy `deleted_at` lên server;
///   chỉ xoá hẳn sau khi server xác nhận (RLS/mạng từ chối thì giữ nguyên).
class ActivityDetailScreen extends StatefulWidget {
  const ActivityDetailScreen({
    super.key,
    required this.services,
    required this.clientEventId,
  });

  final AppServices services;
  final String clientEventId;

  @override
  State<ActivityDetailScreen> createState() => _ActivityDetailScreenState();
}

class _ActivityDetailScreenState extends State<ActivityDetailScreen> {
  Activity? _activity;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final a = await widget.services.db.getActivity(widget.clientEventId);
    if (!mounted) return;
    setState(() {
      _activity = a;
      _loading = false;
    });
  }

  Future<void> _edit(Activity a) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ActivityFormScreen(
          services: widget.services,
          cropSeasonId: a.cropSeasonId,
          activityType: a.type, // KHÔNG cho đổi type
          existing: a,
        ),
      ),
    );
    if (changed == true) await _load();
  }

  Future<void> _delete(Activity a) async {
    final synced = a.serverActivityId != null;
    final ok = await ConfirmationDialog.show(
      context,
      title: 'Xoá hoạt động này?',
      message: synced
          ? 'Hoạt động đã có trên hệ thống. Xoá ở đây rồi khi có mạng sẽ xoá '
              'khỏi hệ thống. Không thể hoàn tác.'
          : 'Hoạt động chưa gửi lên hệ thống. Xoá sẽ mất hẳn trên máy.',
      confirmLabel: 'Xoá',
      destructive: true,
    );
    if (!ok || !mounted) return;

    if (synced) {
      await widget.services.db.tombstoneActivity(a.clientEventId);
    } else {
      await widget.services.db.hardDeleteActivity(a.clientEventId);
    }
    await widget.services.db.markCarbonInputsChanged(a.cropSeasonId);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(synced
            ? 'Đã xoá trên máy — sẽ xoá khỏi hệ thống khi đồng bộ.'
            : 'Đã xoá.'),
      ),
    );
    Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final a = _activity;
    return AppScaffold(
      header: AppHeader(
        title: a == null
            ? 'Chi tiết hoạt động'
            : (kActivityTypeLabels[a.type] ?? a.type),
        showBackButton: true,
      ),
      body: _loading
          ? const LoadingState()
          : a == null
              ? const EmptyState(
                  icon: Icons.help_outline,
                  title: 'Không tìm thấy hoạt động',
                  message: 'Có thể đã bị xoá.',
                )
              : _content(a),
    );
  }

  Widget _content(Activity a) {
    final text = Theme.of(context).textTheme;
    final specs = kActivityFieldSpecs[a.type] ?? const [];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _kv('Thời điểm',
                  '${AppFormat.date(a.occurredAt)} · ${AppFormat.time(a.occurredAt)}'),
              for (final spec in specs)
                if (a.payload.containsKey(spec.key))
                  _kv(spec.label, _display(spec, a.payload[spec.key])),
              if (a.note != null && a.note!.trim().isNotEmpty)
                _kv('Ghi chú', a.note!),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        Row(
          children: [
            _SyncBadge(activity: a),
            const Spacer(),
          ],
        ),
        const SizedBox(height: AppSpacing.lg),
        if (a.deletedLocally)
          const OfflineBanner(
            icon: Icons.delete_sweep_outlined,
            message: 'Đang chờ xoá khỏi hệ thống ở lần đồng bộ tới.',
          )
        else ...[
          PrimaryButton(
            label: 'Sửa',
            icon: Icons.edit_outlined,
            onPressed: () => _edit(a),
          ),
          const SizedBox(height: AppSpacing.sm),
          SecondaryButton(
            label: 'Xoá',
            icon: Icons.delete_outline,
            expanded: true,
            onPressed: () => _delete(a),
          ),
        ],
        const SizedBox(height: AppSpacing.md),
        Text(
          'Sửa hoặc xoá xong, bản ghi quay về trạng thái "chưa gửi" và sẽ đồng '
          'bộ ở lần gửi dữ liệu tiếp theo.',
          style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
        ),
      ],
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 130,
              child: Text(k,
                  style: Theme.of(context)
                      .textTheme
                      .labelMedium
                      ?.copyWith(color: AppColors.textSecondary)),
            ),
            Expanded(
                child: Text(v, style: Theme.of(context).textTheme.bodyLarge)),
          ],
        ),
      );

  String _display(ActivityFieldSpec spec, Object? raw) {
    if (raw == null) return '—';
    if (raw is bool) return raw ? 'Có' : 'Không';
    if (spec.kind == ActivityFieldKind.select) {
      for (final o in spec.options) {
        if (o.value == raw) return o.label;
      }
      return raw.toString();
    }
    if (raw is num) {
      final s = AppFormat.number(raw);
      return spec.unit == null ? s : '$s ${spec.unit}';
    }
    return raw.toString();
  }
}

class _SyncBadge extends StatelessWidget {
  const _SyncBadge({required this.activity});
  final Activity activity;

  @override
  Widget build(BuildContext context) {
    if (activity.deletedLocally) {
      return const StatusBadge(
          label: 'Chờ xoá', tone: StatusTone.warning, icon: Icons.schedule);
    }
    switch (activity.syncState) {
      case SyncState.synced:
        return const StatusBadge(
            label: 'Đã gửi', tone: StatusTone.positive, icon: Icons.check);
      case SyncState.failed:
        return const StatusBadge(
            label: 'Gửi lỗi',
            tone: StatusTone.danger,
            icon: Icons.error_outline);
      case SyncState.syncing:
        return const StatusBadge(label: 'Đang gửi', tone: StatusTone.neutral);
      case SyncState.pending:
        return const StatusBadge(label: 'Chưa gửi', tone: StatusTone.warning);
    }
  }
}

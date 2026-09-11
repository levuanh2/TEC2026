import 'package:flutter/material.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../models/activity.dart';
import '../models/activity_field_spec.dart';
import '../models/crop_season.dart';
import '../shell/routes.dart';
import 'activity_detail_screen.dart';
import 'activity_form_screen.dart';

/// Chi tiết một vụ: hàng đợi đồng bộ, nút ghi hoạt động, danh sách đã ghi, và
/// (nếu vụ đã đồng bộ) nút xem CO₂e.
class CropSeasonDetailScreen extends StatefulWidget {
  const CropSeasonDetailScreen({
    super.key,
    required this.services,
    required this.season,
  });
  final AppServices services;
  final CropSeason season;

  @override
  State<CropSeasonDetailScreen> createState() => _CropSeasonDetailScreenState();
}

class _CropSeasonDetailScreenState extends State<CropSeasonDetailScreen> {
  List<Activity> _activities = [];
  int _pendingCount = 0;
  bool _loading = true;
  bool _syncing = false;
  String? _syncMessage;

  AppServices get _s => widget.services;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final activities =
        await _s.db.listActivitiesByCropSeasonClientId(widget.season.clientId);
    final pending = await _s.db.countPendingActivities();
    if (!mounted) return;
    setState(() {
      _activities = activities;
      _pendingCount = pending;
      _loading = false;
    });
  }

  Future<void> _sync() async {
    setState(() {
      _syncing = true;
      _syncMessage = null;
    });
    String message;
    try {
      final summary = await _s.sync.syncAll();
      if (summary.hasPermissionError) {
        message =
            'Một số mục không đủ quyền lưu lên hệ thống — liên hệ quản lý HTX.';
      } else if (summary.hasErrors) {
        message =
            'Đồng bộ xong nhưng còn ${summary.errorCount} mục lỗi — sẽ thử lại lần sau.';
      } else {
        message = 'Đồng bộ xong: ${summary.activitiesSynced} hoạt động'
            '${summary.activitiesDeleted > 0 ? ', ${summary.activitiesDeleted} đã xoá' : ''}'
            ', ${summary.plotsSynced} thửa, ${summary.cropSeasonsSynced} vụ.';
      }
    } catch (_) {
      message = 'Không có mạng hoặc lỗi kết nối — thử lại sau.';
    }
    if (!mounted) return;
    setState(() {
      _syncMessage = message;
      _syncing = false;
    });
    await _load();
  }

  Future<void> _writeActivity(String type) async {
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ActivityFormScreen(
          services: _s,
          cropSeasonId: widget.season.clientId,
          activityType: type,
        ),
      ),
    );
    await _load();
  }

  Future<void> _openActivity(Activity a) async {
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ActivityDetailScreen(
          services: _s,
          clientEventId: a.clientEventId,
        ),
      ),
    );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: AppHeader(
        title: widget.season.seasonCode,
        subtitle: 'Vụ canh tác',
        showBackButton: true,
      ),
      scrollable: false,
      padded: false,
      body: _loading
          ? const LoadingState()
          : ListView(
              padding: const EdgeInsets.all(AppSpacing.screenH),
              children: [
                AppCard(
                  variant: AppCardVariant.highlight,
                  child: Row(
                    children: [
                      Icon(
                        _pendingCount == 0
                            ? Icons.cloud_done_outlined
                            : Icons.cloud_upload_outlined,
                        color: _pendingCount == 0
                            ? AppColors.primary
                            : AppColors.warningText,
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              _pendingCount == 0
                                  ? 'Đã đồng bộ hết'
                                  : 'Còn $_pendingCount bản ghi chưa gửi',
                              style: text.titleSmall,
                            ),
                            if (_syncMessage != null)
                              Text(_syncMessage!,
                                  style: text.labelSmall?.copyWith(
                                      color: AppColors.textSecondary)),
                          ],
                        ),
                      ),
                      _syncing
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : IconButton(
                              icon: const Icon(Icons.sync),
                              tooltip: 'Gửi dữ liệu ngay',
                              onPressed: _sync,
                            ),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                Text('Ghi nhật ký hoạt động', style: text.titleMedium),
                const SizedBox(height: AppSpacing.xs),
                Wrap(
                  spacing: AppSpacing.xs,
                  runSpacing: AppSpacing.xs,
                  children: [
                    for (final type in kActivityTypes)
                      ActionChip(
                        avatar: Icon(kActivityTypeIcons[type],
                            size: 18, color: AppColors.primary),
                        label: Text(kActivityTypeLabels[type] ?? type),
                        onPressed: () => _writeActivity(type),
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                PrimaryButton(
                  label: 'Xem kết quả phát thải',
                  icon: Icons.eco_outlined,
                  onPressed: () => AppRoutes.openCarbonResult(
                    context,
                    _s,
                    cropSeasonClientId: widget.season.clientId,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                SecondaryButton(
                  label: 'Xem hiệu quả tài nguyên',
                  icon: Icons.insights_outlined,
                  expanded: true,
                  onPressed: () => AppRoutes.openResourceDashboard(
                    context,
                    _s,
                    cropSeasonClientId: widget.season.clientId,
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                Text('Đã ghi nhận', style: text.titleMedium),
                const SizedBox(height: AppSpacing.xs),
                if (_activities.isEmpty)
                  Text('Chưa có hoạt động nào.',
                      style: text.bodyMedium
                          ?.copyWith(color: AppColors.textSecondary))
                else
                  for (final a in _activities) ...[
                    _ActivityTile(activity: a, onTap: () => _openActivity(a)),
                    const SizedBox(height: AppSpacing.xs),
                  ],
              ],
            ),
    );
  }
}

class _ActivityTile extends StatelessWidget {
  const _ActivityTile({required this.activity, required this.onTap});
  final Activity activity;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      onTap: onTap,
      child: Row(
        children: [
          Icon(kActivityTypeIcons[activity.type], color: AppColors.primary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(kActivityTypeLabels[activity.type] ?? activity.type,
                    style: text.titleSmall),
                Text(
                  '${AppFormat.date(activity.occurredAt)} · ${AppFormat.time(activity.occurredAt)}',
                  style:
                      text.labelSmall?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
          _stateBadge(activity),
          const SizedBox(width: AppSpacing.xxs),
          const Icon(Icons.chevron_right, color: AppColors.textSecondary),
        ],
      ),
    );
  }

  Widget _stateBadge(Activity a) {
    if (a.deletedLocally) {
      return const StatusBadge(label: 'Chờ xoá', tone: StatusTone.warning);
    }
    switch (a.syncState) {
      case SyncState.synced:
        return const StatusBadge(
            label: 'Đã gửi', tone: StatusTone.positive, icon: Icons.check);
      case SyncState.failed:
        return const StatusBadge(label: 'Lỗi', tone: StatusTone.danger);
      case SyncState.syncing:
        return const StatusBadge(label: 'Đang gửi', tone: StatusTone.neutral);
      case SyncState.pending:
        return const StatusBadge(label: 'Chưa gửi', tone: StatusTone.warning);
    }
  }
}

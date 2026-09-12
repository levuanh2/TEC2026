import 'package:flutter/material.dart';

import '../../design/design.dart';
import '../../models/activity.dart' show kActivityTypes;
import '../../models/crop_season_metrics.dart';
import '../home_actions.dart';
import '../home_controller.dart';

/// Tab "Trang chủ" (SVG 21). Mọi số liệu THẬT: full_name từ `/v1/me`, Farm/Plot
/// từ local DB, Carbon từ API/cache. `null` → "Chưa có dữ liệu", KHÔNG hiện 0.
class HomeTab extends StatefulWidget {
  const HomeTab({super.key, required this.controller, required this.actions});

  final HomeController controller;
  final HomeActions actions;

  @override
  State<HomeTab> createState() => _HomeTabState();
}

class _HomeTabState extends State<HomeTab> {
  @override
  void initState() {
    super.initState();
    // Gọi mạng MỘT LẦN ở đây — không trong build.
    widget.controller.load();
  }

  HomeActions get _a => widget.actions;

  Future<void> _quickLog(HomeSnapshot s, String activityType) async {
    // Phòng vệ: chỉ 7 loại hợp lệ mới được mở form ghi hoạt động. "Ảnh ruộng"
    // KHÔNG đi qua đây (nó gọi thẳng openCameraCv).
    if (!kActivityTypes.contains(activityType)) return;
    final seasonClientId = s.season?.clientId;
    if (seasonClientId == null) {
      _promptChooseSeason();
      return;
    }
    _a.openActivityForm(seasonClientId, activityType);
  }

  void _promptChooseSeason() {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: const Text('Chọn vụ canh tác trước khi ghi hoạt động.'),
        action: SnackBarAction(
          label: 'Chọn vụ',
          onPressed: _a.openContextPicker,
        ),
      ),
    );
  }

  void _onTodoTap(HomeTodo todo) {
    switch (todo.kind) {
      case HomeTodoKind.pushPending:
        _a.switchToSyncTab();
      case HomeTodoKind.chooseSeason:
        _a.openContextPicker();
      case HomeTodoKind.fillMissingData:
        _a.openActiveCropSeasonForm();
      case HomeTodoKind.writeActivity:
        final id = widget.controller.snapshot.season?.clientId;
        if (id != null) {
          _a.openActivityTypePicker(id);
        } else {
          _a.openContextPicker();
        }
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final s = widget.controller.snapshot;
        return AppScaffold(
          header: AppHeader(
            title: 'AgriCarbon',
            subtitle: 'Trang chủ',
            isOnline: s.online,
          ),
          scrollable: false,
          padded: false,
          body: _body(s),
        );
      },
    );
  }

  Widget _body(HomeSnapshot s) {
    if (s.status == HomeStatus.loading) {
      return const LoadingState(message: 'Đang tải Trang chủ...');
    }
    if (s.status == HomeStatus.unauthorized) {
      return ErrorState(
        title: 'Phiên đăng nhập có vấn đề',
        message: 'Không xác thực được với hệ thống. Vui lòng đăng nhập lại.',
        onRetry: widget.controller.refresh,
        retryLabel: 'Thử lại',
      );
    }
    if (s.status == HomeStatus.offlineNoCache) {
      return ErrorState(
        title: 'Chưa có dữ liệu',
        message: 'Không có mạng và trên máy chưa có dữ liệu đã lưu. '
            'Kết nối mạng rồi kéo xuống để tải.',
        onRetry: widget.controller.refresh,
        retryLabel: 'Thử lại',
      );
    }

    return RefreshIndicator(
      onRefresh: widget.controller.refresh,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.screenH,
          AppSpacing.md,
          AppSpacing.screenH,
          AppSpacing.xl,
        ),
        children: [
          if (s.status == HomeStatus.offlineWithCache)
            const Padding(
              padding: EdgeInsets.only(bottom: AppSpacing.md),
              child: OfflineBanner(
                message: 'Đang xem dữ liệu đã lưu trên máy — chưa có mạng.',
              ),
            ),
          if (s.softError != null)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.md),
              child: OfflineBanner(
                icon: Icons.sync_problem_outlined,
                message: s.softError!,
              ),
            ),
          _Greeting(snapshot: s),
          const SizedBox(height: AppSpacing.md),
          _ContextCard(snapshot: s, onChange: _a.openContextPicker),
          const SizedBox(height: AppSpacing.md),
          if (s.todo != null) ...[
            _TodoCard(todo: s.todo!, onTap: () => _onTodoTap(s.todo!)),
            const SizedBox(height: AppSpacing.lg),
          ],
          Text('Ghi nhanh công việc',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: AppSpacing.xs),
          _QuickLogGrid(
            onActivity: (type) => _quickLog(s, type),
            onCamera: _a.openCameraCv,
            onSeeAll: () {
              final id = s.season?.clientId;
              if (id == null) {
                _promptChooseSeason();
              } else {
                _a.openActivityTypePicker(id);
              }
            },
          ),
          const SizedBox(height: AppSpacing.lg),
          Text('Kết quả vụ này',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: AppSpacing.xs),
          _CarbonCard(
            snapshot: s,
            onOpen: () {
              final id = s.season?.clientId;
              if (id != null) _a.openCarbon(id);
            },
          ),
          if (_SeasonMetricsCard.hasAnything(s.metrics)) ...[
            const SizedBox(height: AppSpacing.sm),
            _SeasonMetricsCard(
              metrics: s.metrics!,
              fromCache: s.metricsFromCache,
              onOpen: () {
                final id = s.season?.clientId;
                if (id != null) _a.openResourceDashboard(id);
              },
            ),
          ],
          const SizedBox(height: AppSpacing.lg),
          Text('Dữ liệu trên hệ thống',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: AppSpacing.xs),
          _SyncCard(snapshot: s, onOpen: _a.switchToSyncTab),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------

class _Greeting extends StatelessWidget {
  const _Greeting({required this.snapshot});
  final HomeSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final name = snapshot.fullName;
    final farm = snapshot.farm;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          name == null ? 'Xin chào 👋' : 'Xin chào, $name 👋',
          style: text.headlineSmall,
        ),
        const SizedBox(height: AppSpacing.xxs),
        Text(
          farm == null
              ? 'Chưa chọn hộ / ruộng'
              : 'Hộ ${farm.farmCode} · '
                  '${snapshot.plotCount} ruộng',
          style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
        ),
      ],
    );
  }
}

class _ContextCard extends StatelessWidget {
  const _ContextCard({required this.snapshot, required this.onChange});
  final HomeSnapshot snapshot;
  final VoidCallback onChange;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final farm = snapshot.farm;
    final plot = snapshot.plot;
    final season = snapshot.season;

    if (farm == null || season == null) {
      return AppCard(
        variant: AppCardVariant.highlight,
        onTap: onChange,
        child: Row(
          children: [
            const Icon(Icons.location_searching, color: AppColors.primary),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Chọn ruộng & vụ canh tác', style: text.titleSmall),
                  const SizedBox(height: 2),
                  Text(
                    farm == null
                        ? 'Chưa chọn hộ / thửa / vụ nào'
                        : 'Đã chọn hộ ${farm.farmCode} — chọn tiếp thửa và vụ',
                    style: text.labelSmall
                        ?.copyWith(color: AppColors.textSecondary),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: AppColors.textSecondary),
          ],
        ),
      );
    }

    return AppCard(
      onTap: onChange,
      child: Row(
        children: [
          const Icon(Icons.grass_outlined, color: AppColors.primary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Đang làm ở', style: text.labelSmall),
                Text(
                  '${farm.farmName} › ${plot?.name ?? '—'} › ${season.seasonCode}',
                  style: text.titleSmall,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          TextButton(onPressed: onChange, child: const Text('Đổi')),
        ],
      ),
    );
  }
}

class _TodoCard extends StatelessWidget {
  const _TodoCard({required this.todo, required this.onTap});
  final HomeTodo todo;
  final VoidCallback onTap;

  ({String title, String hint, IconData icon}) get _content {
    switch (todo.kind) {
      case HomeTodoKind.pushPending:
        return (
          title: 'Còn ${todo.pendingCount} bản ghi chưa gửi lên',
          hint: 'Gửi lên hệ thống khi có mạng',
          icon: Icons.cloud_upload_outlined,
        );
      case HomeTodoKind.chooseSeason:
        return (
          title: 'Chọn vụ canh tác',
          hint: 'Cần chọn vụ trước khi ghi hoạt động',
          icon: Icons.event_note_outlined,
        );
      case HomeTodoKind.fillMissingData:
        return (
          title: 'Bổ sung dữ liệu đang thiếu',
          hint: 'Vụ đang chọn còn thiếu thông tin để tính phát thải',
          icon: Icons.playlist_add_check_circle_outlined,
        );
      case HomeTodoKind.writeActivity:
        return (
          title: 'Ghi hoạt động canh tác',
          hint: 'Ghi việc tưới, bón phân, xăng dầu... trong ngày',
          icon: Icons.edit_note_outlined,
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final c = _content;
    return AppCard(
      variant: AppCardVariant.highlight,
      onTap: onTap,
      child: Row(
        children: [
          Icon(c.icon, color: AppColors.primary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Việc nên làm', style: text.labelSmall),
                Text(c.title, style: text.titleSmall),
                const SizedBox(height: 2),
                Text(
                  c.hint,
                  style:
                      text.labelSmall?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right, color: AppColors.primary),
        ],
      ),
    );
  }
}

class _QuickLogGrid extends StatelessWidget {
  const _QuickLogGrid({
    required this.onActivity,
    required this.onCamera,
    required this.onSeeAll,
  });

  /// Mở form ghi 1 loại hoạt động (luôn là 1 trong 7 `kActivityTypes`).
  final void Function(String activityType) onActivity;

  /// "Ảnh ruộng" → màn CV, KHÔNG tạo Activity.
  final VoidCallback onCamera;
  final VoidCallback onSeeAll;

  /// `activityType == null` nghĩa là ô "Ảnh ruộng" (hành động camera), KHÔNG
  /// phải một loại Activity — không có sentinel string chui vào form.
  static const _items = <({String? activityType, String label, IconData icon})>[
    (
      activityType: 'irrigation',
      label: 'Tưới',
      icon: Icons.water_drop_outlined
    ),
    (activityType: 'fertilizer', label: 'Bón phân', icon: Icons.grass_outlined),
    (
      activityType: 'fuel',
      label: 'Xăng dầu',
      icon: Icons.local_gas_station_outlined
    ),
    (activityType: null, label: 'Ảnh ruộng', icon: Icons.camera_alt_outlined),
  ];

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = AppBreakpoints.quickActionColumns(constraints.maxWidth);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            GridView.count(
              crossAxisCount: columns,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: AppSpacing.sm,
              crossAxisSpacing: AppSpacing.sm,
              childAspectRatio: columns == 1 ? 4.2 : 2.4,
              children: [
                for (final item in _items)
                  AppCard(
                    onTap: () {
                      final type = item.activityType;
                      if (type == null) {
                        onCamera();
                      } else {
                        onActivity(type);
                      }
                    },
                    child: Row(
                      children: [
                        Icon(item.icon, color: AppColors.primary),
                        const SizedBox(width: AppSpacing.xs),
                        Flexible(
                          child: Text(
                            item.label,
                            style: Theme.of(context).textTheme.titleSmall,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: onSeeAll,
                icon: const Icon(Icons.grid_view_outlined, size: 18),
                label: const Text('Xem tất cả'),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _CarbonCard extends StatelessWidget {
  const _CarbonCard({required this.snapshot, required this.onOpen});
  final HomeSnapshot snapshot;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final season = snapshot.season;
    if (season == null) {
      return const MetricCard(
        label: 'Khí thải / kg lúa',
        value: null,
        missingLabel: 'Chọn vụ canh tác để xem kết quả',
      );
    }
    if (season.serverId == null) {
      return const MetricCard(
        label: 'Khí thải / kg lúa',
        value: null,
        missingLabel: 'Vụ chưa đồng bộ lên hệ thống — chưa tính được',
      );
    }

    final carbon = snapshot.carbon;
    if (carbon == null) {
      return MetricCard(
        label: 'Khí thải / kg lúa',
        value: null,
        missingLabel: 'Chưa có dữ liệu',
        onTap: onOpen,
      );
    }
    // co2ePerKg null (chưa có sản lượng) — KHÔNG hiện 0.
    return MetricCard(
      label: 'Khí thải / kg lúa',
      value: carbon.co2ePerKg == null
          ? null
          : AppFormat.number(carbon.co2ePerKg, fractionDigits: 2),
      unit: carbon.co2ePerKg == null ? null : 'kg CO₂e/kg',
      missingLabel: 'Chưa nhập sản lượng thu hoạch nên chưa tính được',
      footnote: snapshot.carbonFromCache
          ? 'Số đã lưu trên máy — có thể chưa phải mới nhất'
          : null,
      onTap: onOpen,
    );
  }
}

/// Chỉ số tài nguyên vụ từ `GET /v1/crop-seasons/{id}/metrics`. CHỈ hiện những
/// dòng có số THẬT — field `null` (chưa đủ dữ liệu) thì bỏ hẳn dòng, KHÔNG hiện
/// "0". Không dòng nào có số → card không được dựng (xem [hasAnything]).
class _SeasonMetricsCard extends StatelessWidget {
  const _SeasonMetricsCard({
    required this.metrics,
    required this.fromCache,
    this.onOpen,
  });
  final CropSeasonMetrics metrics;
  final bool fromCache;
  final VoidCallback? onOpen;

  static bool hasAnything(CropSeasonMetrics? m) =>
      m != null &&
      (m.yieldKg != null ||
          m.waterM3 != null ||
          m.fertilizerKg != null ||
          m.costPerKg != null);

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final rows = <(String, String)>[
      if (metrics.yieldKg != null)
        ('Sản lượng thu hoạch', AppFormat.withUnit(metrics.yieldKg, 'kg')),
      if (metrics.waterM3 != null)
        ('Lượng nước đã dùng', AppFormat.withUnit(metrics.waterM3, 'm³')),
      if (metrics.fertilizerKg != null)
        ('Phân bón đã dùng', AppFormat.withUnit(metrics.fertilizerKg, 'kg')),
      if (metrics.costPerKg != null)
        (
          'Chi phí trên mỗi kg lúa',
          AppFormat.withUnit(metrics.costPerKg, 'đồng', fractionDigits: 0)
        ),
    ];
    return AppCard(
      onTap: onOpen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                  child: Text('Tài nguyên vụ này', style: text.labelSmall)),
              if (onOpen != null)
                Text('Xem hiệu quả ›',
                    style: text.labelSmall?.copyWith(color: AppColors.primary)),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          for (final r in rows)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Flexible(
                    child: Text(r.$1,
                        style: text.bodyMedium
                            ?.copyWith(color: AppColors.textSecondary)),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Text(r.$2, style: text.titleSmall),
                ],
              ),
            ),
          if (fromCache) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(
              'Số đã lưu trên máy — có thể chưa phải mới nhất',
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
            ),
          ],
        ],
      ),
    );
  }
}

class _SyncCard extends StatelessWidget {
  const _SyncCard({required this.snapshot, required this.onOpen});
  final HomeSnapshot snapshot;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final pending = snapshot.pendingCount;
    final last = snapshot.lastSyncAt;
    return AppCard(
      onTap: onOpen,
      child: Row(
        children: [
          Icon(
            snapshot.online
                ? Icons.cloud_done_outlined
                : Icons.cloud_off_outlined,
            color: pending == 0 ? AppColors.primary : AppColors.warningText,
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  pending == 0
                      ? 'Đã gửi đầy đủ'
                      : 'Còn $pending bản ghi chưa gửi lên',
                  style: text.titleSmall,
                ),
                const SizedBox(height: 2),
                Text(
                  [
                    snapshot.online ? 'Đang có mạng' : 'Không có mạng',
                    last == null
                        ? 'chưa gửi lần nào'
                        : 'gửi gần nhất ${AppFormat.dateTime(last)}',
                  ].join(' · '),
                  style:
                      text.labelSmall?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
          StatusBadge(
            label: pending == 0 ? 'Xong' : '$pending',
            tone: pending == 0 ? StatusTone.positive : StatusTone.warning,
          ),
          const SizedBox(width: AppSpacing.xxs),
          const Icon(Icons.chevron_right, color: AppColors.textSecondary),
        ],
      ),
    );
  }
}

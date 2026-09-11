import 'package:flutter/material.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../models/crop_season.dart';
import '../models/plot.dart';
import '../models/sync_state.dart';
import 'crop_season_detail_screen.dart';
import 'crop_season_form_screen.dart';

/// Danh sách Vụ canh tác của một thửa. Offline-first như Plot.
class CropSeasonScreen extends StatefulWidget {
  const CropSeasonScreen(
      {super.key, required this.services, required this.plot});
  final AppServices services;
  final Plot plot;

  @override
  State<CropSeasonScreen> createState() => _CropSeasonScreenState();
}

class _CropSeasonScreenState extends State<CropSeasonScreen> {
  List<CropSeason> _seasons = [];
  bool _loading = true;

  AppServices get _s => widget.services;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final seasons =
        await _s.db.listCropSeasonsByPlotClientId(widget.plot.clientId);
    if (!mounted) return;
    setState(() {
      _seasons = seasons;
      _loading = false;
    });
  }

  Future<void> _openForm({CropSeason? existing}) async {
    final saved = await Navigator.of(context).push<CropSeason>(
      MaterialPageRoute(
        builder: (_) => CropSeasonFormScreen(
          services: _s,
          plot: widget.plot,
          existing: existing,
        ),
      ),
    );
    if (saved != null &&
        _s.activeContext.cropSeasonClientId == saved.clientId) {
      _s.activeContext.refreshCropSeason(saved);
    }
    await _load();
  }

  Future<void> _openDetail(CropSeason season) async {
    await _s.activeContext.setCropSeason(season);
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => CropSeasonDetailScreen(services: _s, season: season),
      ),
    );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: AppHeader(
        title: 'Vụ canh tác',
        subtitle: widget.plot.name,
        showBackButton: true,
      ),
      scrollable: false,
      padded: false,
      floatingActionButton: FloatingActionButton(
        onPressed: () => _openForm(),
        tooltip: 'Thêm vụ',
        child: const Icon(Icons.add),
      ),
      body: _loading
          ? const LoadingState()
          : _seasons.isEmpty
              ? EmptyState(
                  icon: Icons.grass_outlined,
                  title: 'Chưa có vụ canh tác nào',
                  message: 'Bấm + để thêm vụ. Thêm được cả khi không có mạng.',
                  actionLabel: 'Thêm vụ',
                  onAction: () => _openForm(),
                )
              : ListView.separated(
                  padding: const EdgeInsets.all(AppSpacing.screenH),
                  itemCount: _seasons.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(height: AppSpacing.sm),
                  itemBuilder: (context, i) {
                    final s = _seasons[i];
                    return AppCard(
                      onTap: () => _openDetail(s),
                      child: Row(
                        children: [
                          const Icon(Icons.grass_outlined,
                              color: AppColors.primary),
                          const SizedBox(width: AppSpacing.sm),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(s.seasonCode, style: text.titleSmall),
                                const SizedBox(height: 2),
                                Text(
                                  [
                                    s.varietyName ?? 'Chưa ghi giống',
                                    s.status.labelVi,
                                  ].join(' · '),
                                  style: text.labelSmall?.copyWith(
                                      color: AppColors.textSecondary),
                                ),
                              ],
                            ),
                          ),
                          _SeasonSyncChip(state: s.syncState),
                          IconButton(
                            icon: const Icon(Icons.edit_outlined, size: 20),
                            tooltip: 'Sửa vụ',
                            onPressed: () => _openForm(existing: s),
                          ),
                        ],
                      ),
                    );
                  },
                ),
    );
  }
}

class _SeasonSyncChip extends StatelessWidget {
  const _SeasonSyncChip({required this.state});
  final SyncState state;

  @override
  Widget build(BuildContext context) {
    switch (state) {
      case SyncState.synced:
        return const StatusBadge(
            label: 'Đã gửi', tone: StatusTone.positive, icon: Icons.check);
      case SyncState.failed:
        return const StatusBadge(
            label: 'Lỗi gửi',
            tone: StatusTone.danger,
            icon: Icons.error_outline);
      case SyncState.syncing:
        return const StatusBadge(label: 'Đang gửi', tone: StatusTone.neutral);
      case SyncState.pending:
        return const StatusBadge(label: 'Chưa gửi', tone: StatusTone.warning);
    }
  }
}

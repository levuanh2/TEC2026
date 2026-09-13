import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../models/farm.dart';
import '../models/plot.dart';
import '../models/plot_validation.dart';
import '../models/sync_state.dart';
import 'crop_season_screen.dart';

final _uuid = Uuid();

/// Thửa ruộng của một Farm. Tạo/sửa **offline-first**: ghi thẳng SQLite, đồng bộ
/// là hành động riêng. Tỉnh/huyện/xã KHÔNG nhập ở đây (theo schema thuộc Farm).
class PlotScreen extends StatefulWidget {
  const PlotScreen({super.key, required this.services, required this.farm});
  final AppServices services;
  final Farm farm;

  @override
  State<PlotScreen> createState() => _PlotScreenState();
}

class _PlotScreenState extends State<PlotScreen> {
  List<Plot> _plots = [];
  bool _loading = true;

  AppServices get _s => widget.services;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final plots = await _s.db.listPlotsByFarm(widget.farm.id);
    if (!mounted) return;
    setState(() {
      _plots = plots;
      _loading = false;
    });
  }

  Future<void> _openPlot(Plot plot) async {
    await _s.activeContext.setPlot(plot);
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => CropSeasonScreen(services: _s, plot: plot),
      ),
    );
    await _load();
  }

  Future<void> _createOrEditPlot({Plot? existing}) async {
    final result = await showDialog<_PlotDraft>(
      context: context,
      builder: (_) => _PlotDialog(initial: existing),
    );
    if (result == null) return;

    final now = DateTime.now();
    final plot = existing == null
        ? Plot(
            clientId: _uuid.v4(),
            farmId: widget.farm.id,
            plotCode: result.code,
            name: result.name,
            areaHa: result.areaHa,
            createdAt: now,
            updatedAt: now,
          )
        : existing.copyWith(
            plotCode: result.code,
            name: result.name,
            areaHa: result.areaHa,
            // Sửa lại thì phải đồng bộ lại.
            syncState:
                existing.isSynced ? SyncState.pending : existing.syncState,
            clearSyncError: true,
          );
    await _s.db.upsertPlot(plot);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: AppHeader(
        title: 'Thửa ruộng',
        subtitle: widget.farm.farmName,
        showBackButton: true,
      ),
      scrollable: false,
      padded: false,
      floatingActionButton: FloatingActionButton(
        onPressed: () => _createOrEditPlot(),
        tooltip: 'Thêm thửa',
        child: const Icon(Icons.add),
      ),
      body: _loading
          ? const LoadingState()
          : _plots.isEmpty
              ? EmptyState(
                  icon: Icons.crop_square_outlined,
                  title: 'Chưa có thửa ruộng nào',
                  message:
                      'Bấm + để thêm thửa. Thêm được cả khi không có mạng.',
                  actionLabel: 'Thêm thửa',
                  onAction: () => _createOrEditPlot(),
                )
              : ListView.separated(
                  padding: const EdgeInsets.all(AppSpacing.screenH),
                  itemCount: _plots.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(height: AppSpacing.sm),
                  itemBuilder: (context, i) {
                    final plot = _plots[i];
                    return AppCard(
                      onTap: () => _openPlot(plot),
                      child: Row(
                        children: [
                          const Icon(Icons.crop_square_outlined,
                              color: AppColors.primary),
                          const SizedBox(width: AppSpacing.sm),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(plot.name, style: text.titleSmall),
                                const SizedBox(height: 2),
                                Text(
                                  '${plot.plotCode} · '
                                  '${AppFormat.number(plot.areaHa, fractionDigits: 2)} ha',
                                  style: text.labelSmall?.copyWith(
                                      color: AppColors.textSecondary),
                                ),
                              ],
                            ),
                          ),
                          _SyncChip(state: plot.syncState),
                          IconButton(
                            icon: const Icon(Icons.edit_outlined, size: 20),
                            tooltip: 'Sửa thửa',
                            onPressed: () => _createOrEditPlot(existing: plot),
                          ),
                        ],
                      ),
                    );
                  },
                ),
    );
  }
}

class _SyncChip extends StatelessWidget {
  const _SyncChip({required this.state});
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

class _PlotDraft {
  const _PlotDraft(this.code, this.name, this.areaHa);
  final String code;
  final String name;
  final double areaHa;
}

class _PlotDialog extends StatefulWidget {
  const _PlotDialog({this.initial});
  final Plot? initial;

  @override
  State<_PlotDialog> createState() => _PlotDialogState();
}

class _PlotDialogState extends State<_PlotDialog> {
  late final _codeCtl =
      TextEditingController(text: widget.initial?.plotCode ?? '');
  late final _nameCtl = TextEditingController(text: widget.initial?.name ?? '');
  late final _areaCtl = TextEditingController(
    text: widget.initial == null
        ? ''
        : AppFormat.number(widget.initial!.areaHa, fractionDigits: 2),
  );

  String? _codeErr;
  String? _areaErr;

  @override
  void dispose() {
    _codeCtl.dispose();
    _nameCtl.dispose();
    _areaCtl.dispose();
    super.dispose();
  }

  void _submit() {
    final code = _codeCtl.text.trim();
    final name = _nameCtl.text.trim();
    setState(() {
      _codeErr = plotCodeError(code);
      _areaErr = plotAreaError(_areaCtl.text);
    });
    if (_codeErr != null || _areaErr != null) return;
    Navigator.pop(
      context,
      _PlotDraft(code, name.isEmpty ? code : name, parseArea(_areaCtl.text)!),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title:
          Text(widget.initial == null ? 'Thêm thửa ruộng' : 'Sửa thửa ruộng'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _codeCtl,
            decoration:
                InputDecoration(labelText: 'Mã thửa *', errorText: _codeErr),
          ),
          const SizedBox(height: AppSpacing.xs),
          TextField(
            controller: _nameCtl,
            decoration: const InputDecoration(
              labelText: 'Tên gọi (để trống = dùng mã thửa)',
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          TextField(
            controller: _areaCtl,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              labelText: 'Diện tích (ha) *',
              hintText: 'ví dụ: 0,5',
              errorText: _areaErr,
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Huỷ'),
        ),
        PrimaryButton(label: 'Lưu', expanded: false, onPressed: _submit),
      ],
    );
  }
}

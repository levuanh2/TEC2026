import 'package:flutter/material.dart';

import '../../app_services.dart';
import '../../design/design.dart';
import '../../models/activity_field_spec.dart';
import '../../screens/activity_form.dart';
import '../../screens/activity_type_sheet.dart';
import '../routes.dart';

/// Tab "Ghi nhanh công việc" (SVG 22): chọn loại việc → chọn/xác nhận ruộng &
/// vụ (mặc định từ ActiveContext) → form động → lưu offline.
class QuickLogTab extends StatefulWidget {
  const QuickLogTab({super.key, required this.services});
  final AppServices services;

  @override
  State<QuickLogTab> createState() => _QuickLogTabState();
}

class _QuickLogTabState extends State<QuickLogTab> {
  String? _selectedType;

  AppServices get _s => widget.services;

  Future<void> _openContextPicker() async {
    await AppRoutes.openFarms(context, _s);
    if (mounted) setState(() {}); // context có thể đã đổi
  }

  Future<void> _pickAllTypes() async {
    final type = await showActivityTypeSheet(context);
    if (type != null && mounted) setState(() => _selectedType = type);
  }

  Future<void> _onSaved() async {
    if (!mounted) return;
    setState(() => _selectedType = null);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Đã lưu vào máy.')),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      header: const AppHeader(
        title: 'AgriCarbon',
        subtitle: 'Ghi nhanh công việc',
      ),
      body: ListenableBuilder(
        listenable: _s.activeContext,
        builder: (context, _) {
          final season = _s.activeContext.cropSeason;
          final farm = _s.activeContext.farm;
          final plot = _s.activeContext.plot;

          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _ContextRow(
                label: (farm == null || season == null)
                    ? null
                    : '${farm.farmName} › ${plot?.name ?? '—'} › ${season.seasonCode}',
                onChange: _openContextPicker,
              ),
              const SizedBox(height: AppSpacing.md),
              Text('Chọn công việc đã làm',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: AppSpacing.xs),
              _TypeGrid(
                selected: _selectedType,
                onSelect: (t) => setState(() => _selectedType = t),
                onSeeAll: _pickAllTypes,
              ),
              const SizedBox(height: AppSpacing.lg),
              if (_selectedType == null)
                const _Hint('Chọn một loại việc ở trên để bắt đầu ghi.')
              else if (season == null)
                _NeedContext(onChoose: _openContextPicker)
              else
                _InlineForm(
                  key: ValueKey('${season.clientId}:$_selectedType'),
                  services: _s,
                  cropSeasonClientId: season.clientId,
                  activityType: _selectedType!,
                  onSaved: _onSaved,
                ),
              const SizedBox(height: AppSpacing.xl),
            ],
          );
        },
      ),
    );
  }
}

class _ContextRow extends StatelessWidget {
  const _ContextRow({required this.label, required this.onChange});
  final String? label;
  final VoidCallback onChange;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      variant: label == null ? AppCardVariant.highlight : AppCardVariant.plain,
      onTap: onChange,
      child: Row(
        children: [
          const Icon(Icons.grass_outlined, color: AppColors.primary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Ghi cho', style: text.labelSmall),
                Text(
                  label ?? 'Chọn ruộng & vụ canh tác',
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

class _TypeGrid extends StatelessWidget {
  const _TypeGrid({
    required this.selected,
    required this.onSelect,
    required this.onSeeAll,
  });

  final String? selected;
  final void Function(String type) onSelect;
  final VoidCallback onSeeAll;

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
                for (final type in kQuickLogShortcuts)
                  _TypeChip(
                    type: type,
                    active: selected == type,
                    onTap: () => onSelect(type),
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

class _TypeChip extends StatelessWidget {
  const _TypeChip({
    required this.type,
    required this.active,
    required this.onTap,
  });

  final String type;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: active ? AppColors.primarySurface : AppColors.surface,
      borderRadius: AppRadii.allCard,
      child: InkWell(
        onTap: onTap,
        borderRadius: AppRadii.allCard,
        child: Container(
          decoration: BoxDecoration(
            borderRadius: AppRadii.allCard,
            border: Border.all(
              color: active ? AppColors.primary : AppColors.border,
            ),
          ),
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            children: [
              Icon(kActivityTypeIcons[type], color: AppColors.primary),
              const SizedBox(width: AppSpacing.xs),
              Flexible(
                child: Text(
                  kActivityTypeLabels[type] ?? type,
                  style: Theme.of(context).textTheme.titleSmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _InlineForm extends StatelessWidget {
  const _InlineForm({
    super.key,
    required this.services,
    required this.cropSeasonClientId,
    required this.activityType,
    required this.onSaved,
  });

  final AppServices services;
  final String cropSeasonClientId;
  final String activityType;
  final Future<void> Function() onSaved;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          kActivityTypeLabels[activityType] ?? activityType,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: AppSpacing.sm),
        ActivityForm(
          db: services.db,
          cropSeasonClientId: cropSeasonClientId,
          activityType: activityType,
          online: services.connectivity.isOnline,
          onSaved: onSaved,
        ),
      ],
    );
  }
}

class _NeedContext extends StatelessWidget {
  const _NeedContext({required this.onChoose});
  final VoidCallback onChoose;

  @override
  Widget build(BuildContext context) {
    return EmptyState(
      icon: Icons.location_searching,
      title: 'Chưa chọn vụ canh tác',
      message: 'Chọn ruộng và vụ để ghi hoạt động vào đúng vụ.',
      actionLabel: 'Chọn ruộng & vụ',
      onAction: onChoose,
    );
  }
}

class _Hint extends StatelessWidget {
  const _Hint(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
      child: Text(
        text,
        textAlign: TextAlign.center,
        style: Theme.of(context)
            .textTheme
            .bodyMedium
            ?.copyWith(color: AppColors.textSecondary),
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../design/design.dart';
import 'service_plans.dart';

/// Informational pricing only. Does not read or change the account's plan,
/// permissions, usage quotas, payments or offline synchronization.
class PricingScreen extends StatefulWidget {
  const PricingScreen({super.key});

  @override
  State<PricingScreen> createState() => _PricingScreenState();
}

class _PricingScreenState extends State<PricingScreen> {
  bool _cooperative = false;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final plans = _cooperative ? cooperativeServicePlans : farmerServicePlans;
    return AppScaffold(
      header: const AppHeader(title: 'Bảng giá dịch vụ', showBackButton: true),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('AGRICARBON',
              style: text.labelMedium?.copyWith(color: AppColors.grainInk)),
          const SizedBox(height: AppSpacing.sm),
          Text('Gói dịch vụ cho mùa vụ xanh', style: text.headlineMedium),
          const SizedBox(height: AppSpacing.sm),
          Text(AppBrand.slogan, style: text.bodyMedium),
          const SizedBox(height: AppSpacing.lg),
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xs,
            children: [
              ChoiceChip(
                  label: const Text('Nông hộ'),
                  selected: !_cooperative,
                  onSelected: (_) => setState(() => _cooperative = false)),
              ChoiceChip(
                  label: const Text('Hợp tác xã'),
                  selected: _cooperative,
                  onSelected: (_) => setState(() => _cooperative = true)),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
              _cooperative ? 'Gói dành cho Hợp tác xã' : 'Gói dành cho Nông hộ',
              style: text.headlineSmall),
          const SizedBox(height: AppSpacing.sm),
          Text(
              _cooperative
                  ? 'HTX quản lý tập trung và cấp mã tài khoản cho nông dân sử dụng — số hóa canh tác, đo phát thải carbon, sẵn sàng dữ liệu MRV.'
                  : 'Dành cho nông hộ sử dụng cá nhân — ghi nhật ký canh tác, tự tính carbon mùa vụ và nhận hỗ trợ từ trợ lý AI.',
              style: text.bodySmall),
          const SizedBox(height: AppSpacing.lg),
          LayoutBuilder(builder: (context, constraints) {
            // Narrow screens and enlarged text use cards stacked vertically.
            final scale = MediaQuery.textScalerOf(context).scale(1);
            final columns = constraints.maxWidth / scale >= 900 ? 3 : 1;
            final width =
                (constraints.maxWidth - (columns - 1) * AppSpacing.md) /
                    columns;
            return Wrap(
              spacing: AppSpacing.md,
              runSpacing: AppSpacing.md,
              children: [
                for (final plan in plans)
                  SizedBox(
                      width: width,
                      child: _PlanCard(
                          plan: plan,
                          onSelect: () => Navigator.of(context)
                              .pop<ServicePlanSelection>(ServicePlanSelection(
                                  plan: plan, cooperative: _cooperative))))
              ],
            );
          }),
          if (!_cooperative) ...[
            const SizedBox(height: AppSpacing.lg),
            const _JournalActivities(),
          ],
        ],
      ),
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({required this.plan, required this.onSelect});
  final ServicePlan plan;
  final VoidCallback onSelect;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final ink =
        plan.featured ? AppColors.onHeaderPrimary : AppColors.textPrimary;
    final secondary =
        plan.featured ? AppColors.onHeaderSecondary : AppColors.textSecondary;
    final accent = plan.featured ? AppColors.brandGold : AppColors.grainInk;
    final line = plan.featured
        ? AppColors.onHeaderSecondary.withValues(alpha: .2)
        : AppColors.border;
    final icon = switch (plan.name) {
      'FREE' => Icons.spa_outlined,
      'PLUS' => Icons.star_outline,
      _ => Icons.workspace_premium_outlined
    };
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: plan.featured ? AppColors.headerDeep : AppColors.surface,
        borderRadius: AppRadii.allCard,
        border: Border.all(
            color: plan.featured ? AppColors.headerDark : AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (plan.featured) ...[
            Container(
              padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
              decoration: const BoxDecoration(
                  color: AppColors.brandGold, borderRadius: AppRadii.allPill),
              child: Text('PHỔ BIẾN NHẤT',
                  style: text.labelSmall?.copyWith(
                      color: AppColors.headerDeep,
                      fontWeight: FontWeight.w800)),
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          Row(children: [
            ExcludeSemantics(child: Icon(icon, color: ink, size: 28)),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
                child: Text(plan.name,
                    style: text.headlineSmall?.copyWith(color: ink))),
          ]),
          const SizedBox(height: AppSpacing.md),
          Text(plan.description,
              style: text.bodyMedium?.copyWith(color: secondary)),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: AppSpacing.xs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(plan.price == 0 ? 'Miễn phí' : AppFormat.number(plan.price),
                  style: text.headlineMedium
                      ?.copyWith(color: ink, fontWeight: FontWeight.w800)),
              if (plan.price != 0)
                Text('VNĐ', style: text.labelMedium?.copyWith(color: accent)),
            ],
          ),
          Divider(color: line),
          for (final group in plan.groups) ...[
            if (group.label != null) ...[
              Text(group.label!.toUpperCase(),
                  style: text.labelSmall
                      ?.copyWith(color: accent, fontWeight: FontWeight.w700)),
              const SizedBox(height: AppSpacing.sm),
            ],
            for (final feature in group.features)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ExcludeSemantics(
                          child: Icon(Icons.check,
                              size: 18,
                              color: plan.featured
                                  ? AppColors.onHeaderSecondary
                                  : AppColors.primary)),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(
                          child: Text(feature,
                              style: text.bodyMedium
                                  ?.copyWith(color: ink, height: 1.7))),
                    ]),
              ),
            const SizedBox(height: AppSpacing.xs),
          ],
          Divider(color: line),
          Text('Phù hợp với:', style: text.titleSmall?.copyWith(color: ink)),
          const SizedBox(height: AppSpacing.xs),
          for (final item in plan.suitableFor)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
              child: Text('• $item',
                  style:
                      text.bodySmall?.copyWith(color: secondary, height: 1.7)),
            ),
          const SizedBox(height: AppSpacing.md),
          SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: onSelect,
                style: plan.featured
                    ? ElevatedButton.styleFrom(
                        backgroundColor: AppColors.brandGold,
                        foregroundColor: AppColors.headerDeep)
                    : null,
                child: Text(plan.price == 0 ? 'Chọn gói miễn phí' : 'Mua ngay',
                    textAlign: TextAlign.center),
              )),
        ],
      ),
    );
  }
}

/// Shown after authentication (or from Account), never activates a plan.
class PlanSelectionScreen extends StatelessWidget {
  const PlanSelectionScreen(
      {super.key, required this.selection, required this.onDone});
  final ServicePlanSelection selection;
  final VoidCallback onDone;

  @override
  Widget build(BuildContext context) => AppScaffold(
        header: const AppHeader(title: 'Gói dịch vụ đã chọn'),
        body: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('Gói dịch vụ bạn đã chọn',
              style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: AppSpacing.md),
          AppCard(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                Text(selection.audienceLabel,
                    style: Theme.of(context).textTheme.bodySmall),
                const SizedBox(height: AppSpacing.sm),
                Text('Gói ${selection.plan.name}',
                    style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: AppSpacing.sm),
                Text(
                    selection.plan.price == 0
                        ? 'Miễn phí'
                        : '${AppFormat.number(selection.plan.price)} VNĐ',
                    style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: AppSpacing.sm),
                Text(selection.plan.description),
              ])),
          const SizedBox(height: AppSpacing.md),
          Text(
              'Bạn đã chọn gói ${selection.plan.name}. Chưa phát sinh thanh toán hoặc kích hoạt dịch vụ.',
              style: Theme.of(context).textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.lg),
          PrimaryButton(label: 'Tiếp tục', onPressed: onDone),
        ]),
      );
}

class _JournalActivities extends StatelessWidget {
  const _JournalActivities();
  static const _icons = [
    Icons.spa_outlined,
    Icons.shopping_bag_outlined,
    Icons.water_drop_outlined,
    Icons.grass,
    Icons.shield_outlined,
    Icons.rice_bowl_outlined
  ];

  @override
  Widget build(BuildContext context) => AppCard(
          child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Nhật ký canh tác ghi lại 6 hoạt động',
              style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: AppSpacing.md),
          Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.sm, children: [
            for (var i = 0; i < journalActivities.length; i++)
              Chip(
                avatar: ExcludeSemantics(
                    child: Icon(_icons[i], size: 18, color: AppColors.primary)),
                label: Text(journalActivities[i]),
              ),
          ]),
        ],
      ));
}

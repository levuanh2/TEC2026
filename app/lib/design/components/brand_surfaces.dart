import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../tokens.dart';

/// Decorative brand elements share the web assets; they never stand for farm data.
class BrandMark extends StatelessWidget {
  const BrandMark({super.key, this.size = 40});
  final double size;

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            color: AppColors.headerDark,
            borderRadius: BorderRadius.circular(AppRadii.sm),
            border:
                Border.all(color: AppColors.brandGold.withValues(alpha: .35)),
          ),
          child: Icon(Icons.spa_outlined,
              color: AppColors.brandGold, size: size * .6),
        ),
      );
}

class AppIconTile extends StatelessWidget {
  const AppIconTile(
      {super.key,
      required this.icon,
      this.tone = AppTone.carbon,
      this.size = 40});
  final IconData icon;
  final AppTone tone;
  final double size;

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            color: tone.surface,
            borderRadius: BorderRadius.circular(AppRadii.sm),
          ),
          child: Icon(icon, size: size * .55, color: tone.ink),
        ),
      );
}

/// Finite, non-blocking entrance; sensitive form state stays in its owner.
class BrandEntrance extends StatelessWidget {
  const BrandEntrance({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (MediaQuery.disableAnimationsOf(context)) return child;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 320),
      curve: Curves.easeOutCubic,
      child: child,
      builder: (context, value, child) => Opacity(
        opacity: value,
        child: Transform.translate(
            offset: Offset(0, (1 - value) * 6), child: child),
      ),
    );
  }
}

class BrandFieldBanner extends StatelessWidget {
  const BrandFieldBanner({super.key});

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadii.xl),
      child: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [
              AppColors.leafSurface,
              AppColors.primarySurface,
              AppColors.waterSurface
            ],
          ),
        ),
        child: Stack(children: [
          Positioned.fill(
            child: Align(
              alignment: Alignment.centerRight,
              child: SizedBox(
                width: 145,
                child: ShaderMask(
                  blendMode: BlendMode.dstIn,
                  shaderCallback: (bounds) => const LinearGradient(
                    colors: [Colors.transparent, Color(0x99FFFFFF)],
                  ).createShader(bounds),
                  child: Image.asset(AppBrand.riceImage,
                      fit: BoxFit.cover,
                      height: double.infinity,
                      excludeFromSemantics: true),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('AGRICARBON · NÔNG HỘ',
                  style: text.labelSmall?.copyWith(
                      color: AppColors.primary, fontWeight: FontWeight.w600)),
              const SizedBox(height: AppSpacing.xs),
              Text(AppBrand.slogan,
                  style: text.titleLarge?.copyWith(height: 1.5)),
              const SizedBox(height: AppSpacing.xs),
              Text('Chăm từng mùa vụ, vun đắp tương lai xanh.',
                  style: text.bodySmall),
            ]),
          ),
        ]),
      ),
    );
  }
}

class BrandLandscape extends StatelessWidget {
  const BrandLandscape({super.key, this.wide = false});
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadii.xxl),
      child: Stack(children: [
        Positioned.fill(
            child: Image.asset(AppBrand.riceImage,
                fit: BoxFit.cover,
                alignment: const Alignment(.3, 0),
                excludeFromSemantics: true)),
        const Positioned.fill(
            child: DecoratedBox(
          decoration: BoxDecoration(
              gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0x66305037), Color(0xE8103B30)],
          )),
        )),
        Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const BrandMark(),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                  child: Text('AgriCarbon',
                      style:
                          text.headlineSmall?.copyWith(color: Colors.white))),
            ]),
            SizedBox(height: wide ? AppSpacing.xxl : AppSpacing.lg),
            Text('Số hóa canh tác',
                style: text.headlineMedium?.copyWith(
                    color: Colors.white, fontWeight: FontWeight.w600)),
            Text('Xanh hóa tương lai',
                style: text.headlineMedium?.copyWith(
                    color: AppColors.brandGold, fontWeight: FontWeight.w600)),
            const SizedBox(height: AppSpacing.sm),
            Text('Kết nối dữ liệu đồng ruộng, tài nguyên và carbon.',
                style: text.bodySmall?.copyWith(
                    color: AppColors.onHeaderSecondary, height: 1.8)),
          ]),
        ),
      ]),
    );
  }
}

/// Responsive presentation only: callers retain all input and auth behavior.
class BrandAuthFrame extends StatelessWidget {
  const BrandAuthFrame({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.background,
        body: DecoratedBox(
          decoration: const BoxDecoration(gradient: AppGradients.workspace),
          child: SafeArea(child: LayoutBuilder(builder: (context, constraints) {
            final wide = constraints.maxWidth >= 720;
            const padding = AppSpacing.md;
            final form = BrandEntrance(child: child);
            final content = wide
                ? Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
                    Expanded(
                        child: ConstrainedBox(
                      constraints: BoxConstraints(
                          minHeight: math.min(
                              600,
                              math.max(
                                  420, constraints.maxHeight - 2 * padding))),
                      child: const BrandLandscape(wide: true),
                    )),
                    const SizedBox(width: AppSpacing.lg),
                    Expanded(child: form),
                  ])
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                        const BrandLandscape(),
                        const SizedBox(height: AppSpacing.md),
                        form,
                      ]);
            return SingleChildScrollView(
              padding: const EdgeInsets.all(padding),
              child: ConstrainedBox(
                constraints: BoxConstraints(
                    minHeight:
                        math.max(0, constraints.maxHeight - 2 * padding)),
                child: Center(
                    child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 1100),
                  child: content,
                )),
              ),
            );
          })),
        ),
      );
}

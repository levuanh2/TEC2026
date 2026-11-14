// UI-only entry point. Not imported by lib/main.dart and never used for release.
// No Supabase initialization, network calls, device storage or synchronization.
//
// Android preview APK (side-by-side package vn.agricarbon.mobile.uipreview):
//   flutter build apk --debug -t tool/ui_preview.dart -P agricarbon.qaVariant=uipreview
import 'dart:async';

import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/farm.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/models/sync_state.dart';
import 'package:agricarbon_app/screens/login_screen.dart';
import 'package:agricarbon_app/screens/pricing_screen.dart';
import 'package:agricarbon_app/screens/season_question_screen.dart';
import 'package:agricarbon_app/screens/service_plans.dart';
import 'package:agricarbon_app/services/auth_actions.dart';
import 'package:agricarbon_app/services/season_question_api.dart';
import 'package:agricarbon_app/shell/home_actions.dart';
import 'package:agricarbon_app/shell/home_controller.dart';
import 'package:agricarbon_app/shell/tabs/home_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

void main() => runApp(const FlutterUiPreview());

/// Label every preview surface carries: nothing here is real or calculated.
const kPreviewDataLabel = 'DỮ LIỆU MINH HỌA';

/// Presentation fixtures live outside production lib/ and contain no carbon values.
class PreviewHomeController extends ChangeNotifier implements HomeController {
  final _date = DateTime(2026, 11, 12);

  @override
  HomeSnapshot get snapshot => HomeSnapshot(
        status: HomeStatus.success,
        fullName: 'Người dùng xem thử',
        online: false,
        farmCount: 1,
        plotCount: 1,
        farm: Farm(
            id: 'ui-farm',
            cooperativeId: 'ui-org',
            farmCode: 'MINH-HOA',
            farmName: 'Nông hộ minh họa'),
        plot: Plot(
            clientId: 'ui-plot',
            farmId: 'ui-farm',
            plotCode: 'UI',
            name: 'Thửa minh họa',
            areaHa: 1,
            syncState: SyncState.synced,
            createdAt: _date,
            updatedAt: _date),
        season: CropSeason(
            clientId: 'ui-season',
            plotClientId: 'ui-plot',
            seasonCode: 'Vụ minh họa',
            syncState: SyncState.synced,
            createdAt: _date,
            updatedAt: _date),
        todo: const HomeTodo(HomeTodoKind.writeActivity),
      );

  @override
  Future<void> load() async {}
  @override
  Future<void> refresh() async {}
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class PreviewHomeActions implements HomeActions {
  PreviewHomeActions(this.onAction);
  final void Function() onAction;
  @override
  dynamic noSuchMethod(Invocation invocation) {
    onAction();
    return null;
  }
}

class PreviewAuthActions implements AuthActions {
  PreviewAuthActions(this.onSignIn);
  final VoidCallback onSignIn;
  @override
  Future<void> signIn(
          {required String email, required String password}) async =>
      onSignIn();
  @override
  Future<void> sendPasswordReset(String email) async {}
}

/// Answers locally after a short delay. No network, no model, no numbers:
/// the text says plainly that it is a preview fixture.
class PreviewQuestionAsker implements SeasonQuestionAsker {
  @override
  SeasonQuestionRequest ask(String cropSeasonId,
      {required String question, required SeasonQuestionIntent intent}) {
    final completer = Completer<SeasonQuestionAnswer>();
    final timer = Timer(const Duration(milliseconds: 900), () {
      if (completer.isCompleted) return;
      if (intent == SeasonQuestionIntent.dataGap) {
        completer.complete(SeasonQuestionAnswer(
          status: 'insufficient_evidence',
          intent: intent.wire,
          cropSeasonId: cropSeasonId,
          systemComposed: true,
          insufficientReason:
              '$kPreviewDataLabel — ví dụ thông báo khi vụ còn thiếu dữ liệu. Bản xem thử không đọc dữ liệu vụ thật.',
        ));
        return;
      }
      completer.complete(SeasonQuestionAnswer(
        status: 'generated',
        intent: intent.wire,
        cropSeasonId: cropSeasonId,
        systemComposed: true,
        answer:
            '$kPreviewDataLabel — đây là câu trả lời mẫu để xem bố cục. Bản xem thử không gọi máy chủ, không dùng AI và không có số liệu tính toán.',
        limitations: const [
          'Nội dung minh họa, không dùng để ra quyết định canh tác.'
        ],
        citations: const [
          SeasonQuestionCitation(
              title: 'Tài liệu minh họa',
              section: 'Mục minh họa',
              sourceType: 'guideline'),
        ],
      ));
    });
    return SeasonQuestionRequest(completer.future, () {
      timer.cancel();
      if (!completer.isCompleted) {
        completer.completeError(const SeasonQuestionCancelled());
      }
    });
  }
}

/// A banner placed on every preview page.
class PreviewDataBanner extends StatelessWidget {
  const PreviewDataBanner({super.key});
  @override
  Widget build(BuildContext context) => Semantics(
        container: true,
        label: '$kPreviewDataLabel. Bản xem giao diện, không có dữ liệu thật.',
        child: ExcludeSemantics(
          child: Container(
            width: double.infinity,
            color: AppColors.grainSurface,
            padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.md, vertical: AppSpacing.xs),
            child: Text(
              '$kPreviewDataLabel · Bản xem giao diện, không có dữ liệu thật',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: AppColors.grainInk, fontWeight: FontWeight.w700),
            ),
          ),
        ),
      );
}

enum PreviewPage {
  login('Đăng nhập'),
  home('Trang chủ'),
  pricing('Bảng giá FREE/PLUS/PRO'),
  question('Hỏi đáp về vụ mùa'),
  states('Loading / trống / offline / lỗi'),
  brand('Thương hiệu & logo'),
  components('Thành phần giao diện');

  const PreviewPage(this.label);
  final String label;
}

class FlutterUiPreview extends StatefulWidget {
  const FlutterUiPreview({super.key});
  @override
  State<FlutterUiPreview> createState() => _FlutterUiPreviewState();
}

class _FlutterUiPreviewState extends State<FlutterUiPreview> {
  final controller = PreviewHomeController();
  final asker = PreviewQuestionAsker();
  PreviewPage page = PreviewPage.login;
  int nav = 0;
  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  void _go(PreviewPage next) => setState(() => page = next);

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'AgriCarbon · Flutter UI preview',
        debugShowCheckedModeBanner: false,
        theme: AgriCarbonTheme.light(),
        locale: const Locale('vi'),
        supportedLocales: const [Locale('vi'), Locale('en')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate
        ],
        // Same text-scale clamp as the real app (lib/main.dart).
        builder: (context, child) => MediaQuery.withClampedTextScaling(
          maxScaleFactor: 1.8,
          child: child ?? const SizedBox.shrink(),
        ),
        home: Builder(
            builder: (context) => PopScope(
                  // System back on a preview page returns to Login first.
                  canPop: page == PreviewPage.login,
                  onPopInvokedWithResult: (didPop, _) {
                    if (!didPop) _go(PreviewPage.login);
                  },
                  child: Scaffold(
                    appBar: AppBar(
                      title: const Text('Xem giao diện · $kPreviewDataLabel',
                          style: TextStyle(fontSize: 12)),
                      actions: [
                        PopupMenuButton<PreviewPage>(
                          key: const Key('preview-menu'),
                          tooltip: 'Chọn màn xem thử',
                          onSelected: _go,
                          itemBuilder: (_) => [
                            for (final p in PreviewPage.values)
                              PopupMenuItem(value: p, child: Text(p.label)),
                          ],
                        )
                      ],
                    ),
                    body: Column(children: [
                      const PreviewDataBanner(),
                      Expanded(child: _body(context)),
                    ]),
                    bottomNavigationBar: page == PreviewPage.home ||
                            page == PreviewPage.components
                        ? AppBottomNavigation(
                            currentIndex: nav,
                            onSelect: (value) => setState(() {
                              nav = value;
                              page = value == 0
                                  ? PreviewPage.home
                                  : PreviewPage.components;
                            }),
                          )
                        : null,
                  ),
                )),
      );

  void _previewOnly(BuildContext context) =>
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content:
              Text('Bản xem giao diện, không thực hiện thao tác dữ liệu.')));

  Widget _body(BuildContext context) => switch (page) {
        PreviewPage.login =>
          LoginScreen(actions: PreviewAuthActions(() => _go(PreviewPage.home))),
        PreviewPage.home => HomeTab(
            controller: controller,
            actions: PreviewHomeActions(() => _previewOnly(context))),
        PreviewPage.pricing => const PreviewPricingEntry(),
        PreviewPage.question => SeasonQuestionScreen(
            asker: asker,
            cropSeasonId: 'ui-season-server',
            seasonLabel: 'Vụ minh họa',
            banner: const OfflineBanner(
                icon: Icons.science_outlined,
                message:
                    '$kPreviewDataLabel — câu trả lời được tạo trên máy, không gọi máy chủ hay AI.'),
          ),
        PreviewPage.states => const PreviewStates(),
        PreviewPage.brand => const PreviewBrand(),
        PreviewPage.components => const PreviewComponents(),
      };
}

/// Opens the real PricingScreen, then the real PlanSelectionScreen with the
/// chosen plan (the same navigator contract as the Account tab).
class PreviewPricingEntry extends StatelessWidget {
  const PreviewPricingEntry({super.key});

  Future<void> _open(BuildContext context) async {
    final navigator = Navigator.of(context);
    final choice = await navigator.push<ServicePlanSelection>(
        MaterialPageRoute(builder: (_) => const PricingScreen()));
    if (choice == null) return;
    await navigator.push<void>(MaterialPageRoute(
        builder: (summaryContext) => PlanSelectionScreen(
            selection: choice,
            onDone: () => Navigator.of(summaryContext).pop())));
  }

  @override
  Widget build(BuildContext context) => AppScaffold(
        header: const AppHeader(
            title: 'Bảng giá dịch vụ', subtitle: 'Bản xem thử · không thu phí'),
        body: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(
              'Mở màn Bảng giá thật của ứng dụng. Chọn một gói để xem màn “Gói dịch vụ đã chọn”. Không phát sinh thanh toán, không kích hoạt dịch vụ.',
              style: Theme.of(context).textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.lg),
          PrimaryButton(
              key: const Key('preview-open-pricing'),
              label: 'Xem bảng giá dịch vụ',
              icon: Icons.sell_outlined,
              onPressed: () => _open(context)),
        ]),
      );
}

class PreviewStates extends StatelessWidget {
  const PreviewStates({super.key});
  @override
  Widget build(BuildContext context) => AppScaffold(
        header: const AppHeader(
            title: 'Trạng thái màn hình', subtitle: 'Bản xem thử'),
        body: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const OfflineBanner(),
          const SizedBox(height: AppSpacing.md),
          const AppCard(
              child: SizedBox(
                  height: 160,
                  child: LoadingState(message: 'Đang tải dữ liệu…'))),
          const SizedBox(height: AppSpacing.md),
          AppCard(
              child: EmptyState(
                  title: 'Chưa có hoạt động nào',
                  message: 'Ghi hoạt động đầu tiên của vụ để bắt đầu.',
                  actionLabel: 'Ghi hoạt động',
                  onAction: () => ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                          content: Text('Đây là bản xem giao diện.'))))),
          const SizedBox(height: AppSpacing.md),
          AppCard(
              child: ErrorState(
                  title: 'Không tải được dữ liệu',
                  message: 'Kiểm tra kết nối mạng rồi thử lại.',
                  onRetry: () => ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                          content: Text('Đây là bản xem giao diện.'))))),
        ]),
      );
}

class PreviewBrand extends StatelessWidget {
  const PreviewBrand({super.key});
  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: const AppHeader(title: 'Thương hiệu', subtitle: AppBrand.slogan),
      body: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('Logo ở các kích thước', style: text.titleMedium),
        const SizedBox(height: AppSpacing.md),
        const Wrap(
          spacing: AppSpacing.lg,
          runSpacing: AppSpacing.md,
          crossAxisAlignment: WrapCrossAlignment.end,
          children: [
            BrandMark(size: 32),
            BrandMark(size: 40),
            BrandMark(size: 56),
            BrandMark(size: 96),
          ],
        ),
        const SizedBox(height: AppSpacing.lg),
        Text('Be Vietnam Pro', style: text.titleMedium),
        const SizedBox(height: AppSpacing.xs),
        for (final (w, name) in const [
          (FontWeight.w400, '400 Regular'),
          (FontWeight.w500, '500 Medium'),
          (FontWeight.w600, '600 SemiBold'),
          (FontWeight.w700, '700 Bold'),
          (FontWeight.w800, '800 ExtraBold'),
        ])
          Text('$name · Số hóa canh tác - Xanh hóa tương lai',
              style: text.bodyLarge?.copyWith(fontWeight: w)),
        const SizedBox(height: AppSpacing.lg),
        const BrandFieldBanner(),
      ]),
    );
  }
}

class PreviewComponents extends StatelessWidget {
  const PreviewComponents({super.key});
  @override
  Widget build(BuildContext context) => AppScaffold(
        header: const AppHeader(
            title: 'Thành phần giao diện',
            subtitle: 'Bản xem thử · Không có dữ liệu thật'),
        body: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const BrandFieldBanner(),
          const SizedBox(height: AppSpacing.lg),
          Text('Tài nguyên theo mùa vụ',
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: AppSpacing.md),
          const MetricCard(
              label: 'Nước tưới / kg lúa', value: null, tone: AppTone.water),
          const SizedBox(height: AppSpacing.sm),
          const MetricCard(
              label: 'Phân bón / kg lúa', value: null, tone: AppTone.leaf),
          const SizedBox(height: AppSpacing.sm),
          const MetricCard(
              label: 'Chi phí trực tiếp', value: null, tone: AppTone.grain),
          const SizedBox(height: AppSpacing.lg),
          const AppCard(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                Text('Ví dụ bố cục nhập liệu'),
                SizedBox(height: AppSpacing.md),
                TextField(
                    decoration: InputDecoration(
                        labelText: 'Ghi chú canh tác',
                        hintText: 'Bản xem giao diện, không lưu dữ liệu')),
                SizedBox(height: AppSpacing.md),
                Wrap(
                    spacing: AppSpacing.xs,
                    runSpacing: AppSpacing.xs,
                    children: [
                      StatusBadge(label: 'Đã gửi', tone: StatusTone.positive),
                      StatusBadge(label: 'Chờ gửi', tone: StatusTone.warning),
                      StatusBadge(
                          label: 'Cần kiểm tra', tone: StatusTone.danger),
                    ]),
              ])),
          const SizedBox(height: AppSpacing.lg),
          PrimaryButton(
              label: 'Xem phản hồi nút',
              onPressed: () {
                ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Đây là bản xem giao diện.')));
              }),
        ]),
      );
}

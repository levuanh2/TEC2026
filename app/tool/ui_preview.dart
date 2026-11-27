// UI-only entry point. Not imported by lib/main.dart and never used for release.
// No Supabase initialization, network calls, device storage or synchronization.
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/farm.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/models/sync_state.dart';
import 'package:agricarbon_app/screens/login_screen.dart';
import 'package:agricarbon_app/services/auth_actions.dart';
import 'package:agricarbon_app/shell/home_actions.dart';
import 'package:agricarbon_app/shell/home_controller.dart';
import 'package:agricarbon_app/shell/tabs/home_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

void main() => runApp(const FlutterUiPreview());

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

class FlutterUiPreview extends StatefulWidget {
  const FlutterUiPreview({super.key});
  @override
  State<FlutterUiPreview> createState() => _FlutterUiPreviewState();
}

class _FlutterUiPreviewState extends State<FlutterUiPreview> {
  final controller = PreviewHomeController();
  int page = 0;
  int nav = 0;
  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

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
        home: Builder(
            builder: (context) => Scaffold(
                  appBar: AppBar(
                    title: const Text('Xem giao diện · Dữ liệu minh họa',
                        style: TextStyle(fontSize: 12)),
                    actions: [
                      PopupMenuButton<int>(
                        tooltip: 'Chọn màn xem thử',
                        onSelected: (value) => setState(() => page = value),
                        itemBuilder: (_) => const [
                          PopupMenuItem(value: 0, child: Text('Đăng nhập')),
                          PopupMenuItem(value: 1, child: Text('Trang chủ')),
                          PopupMenuItem(
                              value: 2, child: Text('Thành phần giao diện')),
                        ],
                      )
                    ],
                  ),
                  body: switch (page) {
                    0 => LoginScreen(
                        actions:
                            PreviewAuthActions(() => setState(() => page = 1))),
                    1 => HomeTab(
                        controller: controller,
                        actions: PreviewHomeActions(() {
                          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                              content: Text(
                                  'Bản xem giao diện, không thực hiện thao tác dữ liệu.')));
                        })),
                    _ => const PreviewComponents(),
                  },
                  bottomNavigationBar: page == 0
                      ? null
                      : AppBottomNavigation(
                          currentIndex: nav,
                          onSelect: (value) => setState(() {
                            nav = value;
                            page = value == 0 ? 1 : 2;
                          }),
                        ),
                )),
      );
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

import 'package:flutter/material.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../screens/activity_type_sheet.dart';
import 'home_actions.dart';
import 'routes.dart';
import 'tabs/account_tab.dart';
import 'tabs/home_tab.dart';
import 'tabs/quick_log_tab.dart';
import 'tabs/sync_tab.dart';

/// Vỏ chính sau khi đăng nhập: 4 tab trong [IndexedStack] (giữ nguyên state của
/// từng tab khi chuyển qua lại) + [AppBottomNavigation] cố định ở đáy.
///
/// Android back: nếu đang ở tab khác 0 thì về tab "Trang chủ" trước; ở tab 0
/// mới cho thoát app (hành vi mặc định).
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.services});
  final AppServices services;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell>
    with WidgetsBindingObserver
    implements HomeActions {
  int _index = 0;

  AppServices get _s => widget.services;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // App trở lại foreground → thử gửi hàng đợi (nền, không chặn UI).
    if (state == AppLifecycleState.resumed) {
      _s.syncCoordinator.onAppResumed();
    }
  }

  void _select(int i) {
    if (i == _index) return;
    setState(() => _index = i);
    if (i == 2) _s.syncCoordinator.refresh(); // mở tab Gửi dữ liệu → đọc lại
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _index == 0,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && _index != 0) _select(0);
      },
      child: Scaffold(
        backgroundColor: AppColors.background,
        body: IndexedStack(
          index: _index,
          children: [
            HomeTab(controller: _s.homeController, actions: this),
            QuickLogTab(services: _s),
            SyncTab(
              coordinator: _s.syncCoordinator,
              onOpenSettings: _openSyncSettings,
              onFixActivity: _fixActivity,
            ),
            AccountTab(services: _s),
          ],
        ),
        bottomNavigationBar: AppBottomNavigation(
          currentIndex: _index,
          onSelect: _select,
        ),
      ),
    );
  }

  // --- HomeActions -----------------------------------------------------------

  @override
  void openContextPicker() {
    AppRoutes.openFarms(context, _s).then((_) {
      if (mounted) _s.homeController.refreshLocalState();
    });
  }

  @override
  void openCarbon(String cropSeasonClientId) {
    AppRoutes.openCarbonResult(
      context,
      _s,
      cropSeasonClientId: cropSeasonClientId,
      onOpenSync: () {
        Navigator.of(context).popUntil((r) => r.isFirst);
        _select(2);
      },
    );
  }

  @override
  void openResourceDashboard(String cropSeasonClientId) {
    AppRoutes.openResourceDashboard(
      context,
      _s,
      cropSeasonClientId: cropSeasonClientId,
      onOpenSync: () {
        Navigator.of(context).popUntil((r) => r.isFirst);
        _select(2);
      },
    );
  }

  @override
  void openActivityForm(String cropSeasonClientId, String activityType) {
    AppRoutes.openActivityForm(
      context,
      _s,
      cropSeasonClientId: cropSeasonClientId,
      activityType: activityType,
    ).then((_) {
      if (mounted) _s.homeController.refreshLocalState();
    });
  }

  @override
  Future<void> openActivityTypePicker(String cropSeasonClientId) async {
    final type = await showActivityTypeSheet(context);
    if (type == null || !mounted) return;
    openActivityForm(cropSeasonClientId, type);
  }

  @override
  void openActiveCropSeasonForm() {
    final plot = _s.activeContext.plot;
    final season = _s.activeContext.cropSeason;
    if (plot == null) {
      openContextPicker();
      return;
    }
    AppRoutes.openCropSeasonForm(context, _s, plot: plot, existing: season)
        .then((saved) {
      if (!mounted) return;
      if (saved != null &&
          _s.activeContext.cropSeasonClientId == saved.clientId) {
        _s.activeContext.refreshCropSeason(saved);
      }
      _s.homeController.refreshLocalState();
    });
  }

  @override
  void openCameraCv() {
    AppRoutes.openCameraCv(context, _s);
  }

  @override
  void switchToSyncTab() => _select(2);

  Future<void> _fixActivity(String clientEventId) async {
    await AppRoutes.openActivityEdit(context, _s, clientEventId: clientEventId);
    if (mounted) await _s.syncCoordinator.refresh();
  }

  void _openSyncSettings() {
    AppRoutes.openSyncSettings(context, _s).then((_) {
      if (mounted) _s.syncCoordinator.refresh();
    });
  }
}

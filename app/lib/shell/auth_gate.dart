import 'package:flutter/material.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../screens/forced_password_change_screen.dart';
import '../screens/login_screen.dart';
import '../screens/pricing_screen.dart';
import '../screens/service_plans.dart';
import '../screens/reset_password_screen.dart';
import 'auth_controller.dart';
import 'home_shell.dart';

/// Chọn màn gốc theo [AuthPhase]. Không điều hướng bằng Navigator — chỉ đổi
/// subtree khi phase đổi, nên đăng xuất / hết phiên quay về Login tức thì.
class AuthGate extends StatefulWidget {
  const AuthGate({super.key, required this.services});
  final AppServices services;

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  // In-memory UI intent only: no account write, quota or purchase persistence.
  ServicePlanSelection? _pendingPlan;
  late bool _wasAuthenticated;

  @override
  void initState() {
    super.initState();
    _wasAuthenticated = widget.services.authController.isAuthenticated;
    widget.services.authController.addListener(_onAuthChanged);
  }

  @override
  void dispose() {
    widget.services.authController.removeListener(_onAuthChanged);
    super.dispose();
  }

  /// Leaving the authenticated phase (sign-out, expired or revoked session)
  /// swaps the root to Login, but routes pushed above it (farm -> plot ->
  /// season, dialogs) would stay on top and keep showing the previous
  /// account's data. Found on a physical phone after a server-side session
  /// revocation: drop everything above the root.
  void _onAuthChanged() {
    final now = widget.services.authController.isAuthenticated;
    if (_wasAuthenticated && !now) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        Navigator.of(context).popUntil((route) => route.isFirst);
      });
    }
    _wasAuthenticated = now;
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.services.authController,
      builder: (context, _) {
        final auth = widget.services.authController;
        switch (auth.phase) {
          case AuthPhase.initializing:
          case AuthPhase.restoringSession:
            return const _AuthSplash();
          case AuthPhase.authenticated:
            if (auth.mustChangePassword) {
              return ForcedPasswordChangeScreen(
                onSubmit: auth.replaceTemporaryPassword,
                onSignOut: auth.signOut,
              );
            }
            if (auth.isPasswordRecovery) {
              return ResetPasswordScreen(
                onSubmit: auth.updatePassword,
                onDone: auth.completePasswordRecovery,
              );
            }
            if (_pendingPlan != null) {
              return PlanSelectionScreen(
                  selection: _pendingPlan!,
                  onDone: () => setState(() => _pendingPlan = null));
            }
            return HomeShell(services: widget.services);
          case AuthPhase.signedOut:
            return LoginScreen(
                actions: widget.services.authController,
                selectedPlan: _pendingPlan,
                onPlanSelected: (choice) =>
                    setState(() => _pendingPlan = choice));
          case AuthPhase.sessionExpired:
            return LoginScreen(
              actions: widget.services.authController,
              notice: LoginNotice.sessionExpired,
              selectedPlan: _pendingPlan,
              onPlanSelected: (choice) => setState(() => _pendingPlan = choice),
            );
          case AuthPhase.error:
            return _AuthError(onRetry: widget.services.authController.retry);
        }
      },
    );
  }
}

class _AuthSplash extends StatelessWidget {
  const _AuthSplash();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppColors.headerDark,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.eco, size: 56, color: Colors.white),
            SizedBox(height: AppSpacing.md),
            SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: Colors.white),
            ),
          ],
        ),
      ),
    );
  }
}

class _AuthError extends StatelessWidget {
  const _AuthError({required this.onRetry});
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      header: const AppHeader(title: 'AgriCarbon'),
      body: ErrorState(
        title: 'Không kết nối được phiên đăng nhập',
        message: 'Kiểm tra kết nối mạng rồi thử lại.',
        onRetry: onRetry,
      ),
    );
  }
}

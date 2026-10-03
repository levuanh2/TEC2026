import 'package:flutter/material.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../screens/forced_password_change_screen.dart';
import '../screens/login_screen.dart';
import '../screens/reset_password_screen.dart';
import 'auth_controller.dart';
import 'home_shell.dart';

/// Chọn màn gốc theo [AuthPhase]. Không điều hướng bằng Navigator — chỉ đổi
/// subtree khi phase đổi, nên đăng xuất / hết phiên quay về Login tức thì.
class AuthGate extends StatelessWidget {
  const AuthGate({super.key, required this.services});
  final AppServices services;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: services.authController,
      builder: (context, _) {
        final auth = services.authController;
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
            return HomeShell(services: services);
          case AuthPhase.signedOut:
            return LoginScreen(actions: services.authController);
          case AuthPhase.sessionExpired:
            return LoginScreen(
              actions: services.authController,
              notice: LoginNotice.sessionExpired,
            );
          case AuthPhase.error:
            return _AuthError(onRetry: services.authController.retry);
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

import 'package:flutter/material.dart';

import '../design/design.dart';
import '../services/auth_actions.dart';
import '../services/auth_errors.dart';
import 'forgot_password_screen.dart';

/// Thông báo một lần hiển thị trên màn đăng nhập.
enum LoginNotice { none, sessionExpired }

/// Màn đăng nhập (SVG 20). KHÔNG tự điều hướng khi thành công — [AuthController]
/// đổi phase và `AuthGate` chuyển màn.
///
/// Nghiệp vụ khác SVG: SVG ghi "Số điện thoại hoặc email" nhưng cấu hình hiện
/// tại chưa chứng minh đăng nhập bằng số điện thoại hoạt động → chỉ làm **email**,
/// nhãn ghi đúng là "Email" (không giả vờ hỗ trợ số điện thoại).
class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    required this.actions,
    this.notice = LoginNotice.none,
  });

  final AuthActions actions;
  final LoginNotice notice;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _passwordFocus = FocusNode();

  bool _submitting = false;
  bool _obscurePassword = true;
  String? _emailError;
  String? _passwordError;
  String? _formError;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _passwordFocus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) return; // chống bấm/enter hai lần
    FocusScope.of(context).unfocus();

    final email = _emailController.text.trim();
    final password = _passwordController.text;
    final emailErr = emailFieldError(email);
    final passwordErr = passwordFieldError(password);
    if (emailErr != null || passwordErr != null) {
      setState(() {
        _emailError = emailErr;
        _passwordError = passwordErr;
        _formError = null;
      });
      return;
    }

    setState(() {
      _submitting = true;
      _emailError = null;
      _passwordError = null;
      _formError = null;
    });

    try {
      await widget.actions.signIn(email: email, password: password);
      // Thành công: không làm gì — AuthGate sẽ chuyển màn.
    } catch (error) {
      if (!mounted) return;
      setState(() => _formError = authErrorMessage(error));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _openForgotPassword() async {
    final typed = _emailController.text.trim();
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ForgotPasswordScreen(
          actions: widget.actions,
          initialEmail: isValidEmail(typed) ? typed : null,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      backgroundColor: AppColors.headerDark,
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SizedBox(height: AppSpacing.xl),
                  Text(
                    'AgriCarbon',
                    style: text.displayMedium?.copyWith(color: Colors.white),
                  ),
                  const SizedBox(height: AppSpacing.xxs),
                  Text(
                    'Theo dõi canh tác',
                    style: text.bodyLarge
                        ?.copyWith(color: AppColors.onHeaderSecondary),
                  ),
                  const SizedBox(height: AppSpacing.xl),
                  if (widget.notice == LoginNotice.sessionExpired) ...[
                    const OfflineBanner(
                      icon: Icons.lock_clock_outlined,
                      message:
                          'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại. '
                          'Dữ liệu chưa gửi vẫn được giữ trên máy.',
                    ),
                    const SizedBox(height: AppSpacing.md),
                  ],
                  _card(context, text),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _card(BuildContext context, TextTheme text) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.xxl),
      ),
      child: AutofillGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Đăng nhập', style: text.headlineMedium),
            const SizedBox(height: AppSpacing.xxs),
            Text('Dùng cho nông dân và cán bộ HTX', style: text.bodySmall),
            const SizedBox(height: AppSpacing.lg),
            TextField(
              controller: _emailController,
              enabled: !_submitting,
              keyboardType: TextInputType.emailAddress,
              textInputAction: TextInputAction.next,
              autocorrect: false,
              autofillHints: const [
                AutofillHints.username,
                AutofillHints.email
              ],
              onSubmitted: (_) => _passwordFocus.requestFocus(),
              onChanged: (_) {
                if (_emailError != null) setState(() => _emailError = null);
              },
              decoration: InputDecoration(
                labelText: 'Email',
                hintText: 'ten@vidu.com',
                errorText: _emailError,
                prefixIcon: const Icon(Icons.mail_outline),
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            TextField(
              controller: _passwordController,
              focusNode: _passwordFocus,
              enabled: !_submitting,
              obscureText: _obscurePassword,
              textInputAction: TextInputAction.done,
              autofillHints: const [AutofillHints.password],
              onSubmitted: (_) => _submit(),
              onChanged: (_) {
                if (_passwordError != null) {
                  setState(() => _passwordError = null);
                }
              },
              decoration: InputDecoration(
                labelText: 'Mật khẩu',
                errorText: _passwordError,
                prefixIcon: const Icon(Icons.lock_outline),
                suffixIcon: IconButton(
                  icon: Icon(_obscurePassword
                      ? Icons.visibility_off_outlined
                      : Icons.visibility_outlined),
                  tooltip: _obscurePassword ? 'Hiện mật khẩu' : 'Ẩn mật khẩu',
                  onPressed: () =>
                      setState(() => _obscurePassword = !_obscurePassword),
                ),
              ),
            ),
            if (_formError != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(
                _formError!,
                style: text.bodyMedium?.copyWith(color: AppColors.error),
              ),
            ],
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: 'Đăng nhập',
              loading: _submitting,
              onPressed: _submit,
            ),
            const SizedBox(height: AppSpacing.xs),
            Align(
              alignment: Alignment.center,
              child: TextButton(
                onPressed: _submitting ? null : _openForgotPassword,
                child: const Text('Quên mật khẩu?'),
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Center(
              child: Text(
                'Cần hỗ trợ? Liên hệ quản lý HTX của bạn.',
                style: text.labelSmall,
                textAlign: TextAlign.center,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

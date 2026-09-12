import 'package:flutter/material.dart';

import '../design/design.dart';
import '../services/auth_actions.dart';
import '../services/auth_errors.dart';

/// Quên mật khẩu — dùng flow reset chuẩn của Supabase (gửi email chứa link đặt
/// lại). Supabase cố tình không báo email có tồn tại hay không, nên thông báo
/// thành công luôn trung tính.
class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({
    super.key,
    required this.actions,
    this.initialEmail,
  });

  final AuthActions actions;
  final String? initialEmail;

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

enum _Status { idle, sending, sent, error }

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  late final TextEditingController _emailController =
      TextEditingController(text: widget.initialEmail ?? '');

  _Status _status = _Status.idle;
  String? _emailError;
  String? _errorMessage;

  @override
  void dispose() {
    _emailController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_status == _Status.sending) return;
    FocusScope.of(context).unfocus();

    final email = _emailController.text.trim();
    final err = emailFieldError(email);
    if (err != null) {
      setState(() => _emailError = err);
      return;
    }

    setState(() {
      _status = _Status.sending;
      _emailError = null;
      _errorMessage = null;
    });

    try {
      await widget.actions.sendPasswordReset(email);
      if (!mounted) return;
      setState(() => _status = _Status.sent);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _status = _Status.error;
        _errorMessage = authErrorMessage(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: const AppHeader(
        title: 'Quên mật khẩu',
        showBackButton: true,
      ),
      body: _status == _Status.sent ? _sentView(text) : _formView(text),
    );
  }

  Widget _formView(TextTheme text) {
    final sending = _status == _Status.sending;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: AppSpacing.md),
        Text('Đặt lại mật khẩu', style: text.headlineSmall),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Nhập email tài khoản. Chúng tôi sẽ gửi hướng dẫn đặt lại mật khẩu '
          'qua email đó.',
          style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
        ),
        const SizedBox(height: AppSpacing.lg),
        TextField(
          controller: _emailController,
          enabled: !sending,
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.done,
          autocorrect: false,
          autofillHints: const [AutofillHints.username, AutofillHints.email],
          onSubmitted: (_) => _submit(),
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
        if (_errorMessage != null) ...[
          const SizedBox(height: AppSpacing.sm),
          Text(
            _errorMessage!,
            style: text.bodyMedium?.copyWith(color: AppColors.error),
          ),
        ],
        const SizedBox(height: AppSpacing.lg),
        PrimaryButton(
          label: 'Gửi hướng dẫn đặt lại',
          loading: sending,
          onPressed: _submit,
        ),
      ],
    );
  }

  Widget _sentView(TextTheme text) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: AppSpacing.xl),
        const Icon(Icons.mark_email_read_outlined,
            size: 56, color: AppColors.primary),
        const SizedBox(height: AppSpacing.md),
        Text('Đã gửi (nếu email có tài khoản)', style: text.headlineSmall),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Nếu ${_emailController.text.trim()} có tài khoản, bạn sẽ nhận được '
          'email kèm hướng dẫn đặt lại mật khẩu. Kiểm tra cả hộp thư rác. '
          'Không thấy email sau ít phút thì liên hệ quản lý HTX.',
          style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
        ),
        const SizedBox(height: AppSpacing.lg),
        PrimaryButton(
          label: 'Quay lại đăng nhập',
          onPressed: () => Navigator.of(context).maybePop(),
        ),
      ],
    );
  }
}

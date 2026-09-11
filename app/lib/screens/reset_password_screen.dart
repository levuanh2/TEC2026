import 'package:flutter/material.dart';

import '../design/design.dart';
import '../services/auth_errors.dart';

/// Đặt mật khẩu mới sau khi mở link đặt lại trong email. Chỉ hiển thị khi phiên
/// `passwordRecovery` đã được thiết lập (link email → deep link → app). Việc
/// nối deep link cần cấu hình NGOÀI code (xem `app/README.md`); màn này là phần
/// an toàn phía app: nhận mật khẩu mới và gọi `updateUser`.
class ResetPasswordScreen extends StatefulWidget {
  const ResetPasswordScreen({
    super.key,
    required this.onSubmit,
    required this.onDone,
    this.title = 'Đặt lại mật khẩu',
    this.showBackButton = false,
  });

  /// Đặt mật khẩu mới. Ném lỗi khi thất bại (được dịch qua `authErrorMessage`).
  final Future<void> Function(String newPassword) onSubmit;

  /// Gọi khi hoàn tất (đổi xong hoặc người dùng chọn thoát luồng này).
  final VoidCallback onDone;

  /// Tiêu đề header — luồng email dùng mặc định; "Đổi mật khẩu" từ màn Tài khoản
  /// truyền tiêu đề riêng.
  final String title;

  /// Màn "Đổi mật khẩu" (route phụ) cần nút quay lại; luồng recovery thì không.
  final bool showBackButton;

  @override
  State<ResetPasswordScreen> createState() => _ResetPasswordScreenState();
}

enum _Status { idle, submitting, done }

class _ResetPasswordScreenState extends State<ResetPasswordScreen> {
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();

  _Status _status = _Status.idle;
  bool _obscure = true;
  String? _passwordError;
  String? _confirmError;
  String? _formError;

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  String? _validatePassword(String value) {
    if (value.isEmpty) return 'Vui lòng nhập mật khẩu mới.';
    if (value.length < 6) return 'Mật khẩu cần ít nhất 6 ký tự.';
    return null;
  }

  Future<void> _submit() async {
    if (_status == _Status.submitting) return;
    FocusScope.of(context).unfocus();

    final password = _passwordController.text;
    final confirm = _confirmController.text;
    final passwordError = _validatePassword(password);
    final confirmError =
        confirm != password ? 'Nhập lại chưa khớp mật khẩu mới.' : null;

    if (passwordError != null || confirmError != null) {
      setState(() {
        _passwordError = passwordError;
        _confirmError = confirmError;
      });
      return;
    }

    setState(() {
      _status = _Status.submitting;
      _passwordError = null;
      _confirmError = null;
      _formError = null;
    });

    try {
      await widget.onSubmit(password);
      if (!mounted) return;
      setState(() => _status = _Status.done);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _status = _Status.idle;
        _formError = authErrorMessage(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: AppHeader(
        title: widget.title,
        showBackButton: widget.showBackButton,
      ),
      body: _status == _Status.done ? _doneView(text) : _formView(text),
    );
  }

  Widget _formView(TextTheme text) {
    final submitting = _status == _Status.submitting;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: AppSpacing.md),
        Text('Tạo mật khẩu mới', style: text.headlineSmall),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Nhập mật khẩu mới cho tài khoản của bạn. Sau khi đổi, hãy dùng mật '
          'khẩu này để đăng nhập lần sau.',
          style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
        ),
        const SizedBox(height: AppSpacing.lg),
        TextField(
          controller: _passwordController,
          enabled: !submitting,
          obscureText: _obscure,
          autofillHints: const [AutofillHints.newPassword],
          textInputAction: TextInputAction.next,
          onChanged: (_) {
            if (_passwordError != null) setState(() => _passwordError = null);
          },
          decoration: InputDecoration(
            labelText: 'Mật khẩu mới',
            errorText: _passwordError,
            prefixIcon: const Icon(Icons.lock_outline),
            suffixIcon: IconButton(
              icon: Icon(_obscure ? Icons.visibility : Icons.visibility_off),
              onPressed: () => setState(() => _obscure = !_obscure),
              tooltip: _obscure ? 'Hiện mật khẩu' : 'Ẩn mật khẩu',
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        TextField(
          controller: _confirmController,
          enabled: !submitting,
          obscureText: _obscure,
          autofillHints: const [AutofillHints.newPassword],
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _submit(),
          onChanged: (_) {
            if (_confirmError != null) setState(() => _confirmError = null);
          },
          decoration: InputDecoration(
            labelText: 'Nhập lại mật khẩu mới',
            errorText: _confirmError,
            prefixIcon: const Icon(Icons.lock_outline),
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
          label: 'Đổi mật khẩu',
          loading: submitting,
          onPressed: _submit,
        ),
        const SizedBox(height: AppSpacing.sm),
        SecondaryButton(
          label: 'Để sau',
          expanded: true,
          onPressed: submitting ? null : widget.onDone,
        ),
      ],
    );
  }

  Widget _doneView(TextTheme text) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: AppSpacing.xl),
        const Icon(Icons.check_circle_outline,
            size: 56, color: AppColors.primary),
        const SizedBox(height: AppSpacing.md),
        Text('Đã đổi mật khẩu', style: text.headlineSmall),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Mật khẩu mới đã được lưu. Bạn có thể tiếp tục dùng ứng dụng.',
          style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
        ),
        const SizedBox(height: AppSpacing.lg),
        PrimaryButton(label: 'Tiếp tục', onPressed: widget.onDone),
      ],
    );
  }
}

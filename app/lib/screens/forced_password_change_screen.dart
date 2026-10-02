import 'package:flutter/material.dart';

import '../design/design.dart';
import '../services/password_change_api.dart';

/// Đăng nhập lần đầu bằng mật khẩu tạm HTX cấp: bắt buộc đặt mật khẩu riêng.
///
/// Quản lý HTX đã thấy mật khẩu tạm, nên máy chủ từ chối mọi dữ liệu nghiệp vụ
/// tới khi đổi (403 / RLS). Màn này là lối đi duy nhất, cùng nút đăng xuất. Cờ do
/// máy chủ xoá sau khi kiểm mật khẩu tạm — app không tự xoá.
class ForcedPasswordChangeScreen extends StatefulWidget {
  const ForcedPasswordChangeScreen({
    super.key,
    required this.onSubmit,
    required this.onSignOut,
  });

  /// (mật khẩu tạm, mật khẩu mới). Ném [PasswordChangeException] khi máy chủ từ chối.
  final Future<void> Function(String current, String next) onSubmit;
  final Future<void> Function() onSignOut;

  @override
  State<ForcedPasswordChangeScreen> createState() => _ForcedPasswordChangeScreenState();
}

/// Cùng luật với máy chủ (`service.password_problem`) và Farmer Web.
String? newPasswordProblem(String next, String confirm) {
  if (next.length < 8) return 'Mật khẩu mới cần ít nhất 8 ký tự.';
  if (!RegExp('[a-z]').hasMatch(next) || !RegExp('[A-Z]').hasMatch(next) || !RegExp(r'\d').hasMatch(next)) {
    return 'Mật khẩu mới cần có chữ hoa, chữ thường và số.';
  }
  if (next != confirm) return 'Hai lần nhập mật khẩu mới không khớp.';
  return null;
}

class _ForcedPasswordChangeScreenState extends State<ForcedPasswordChangeScreen> {
  final _current = TextEditingController();
  final _next = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy) return;
    FocusScope.of(context).unfocus();
    final problem = _current.text.isEmpty
        ? 'Nhập mật khẩu tạm HTX đã cấp.'
        : newPasswordProblem(_next.text, _confirm.text);
    setState(() => _error = problem);
    if (problem != null) return;
    setState(() => _busy = true);
    try {
      await widget.onSubmit(_current.text, _next.text);
    } on PasswordChangeException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) setState(() => _error = 'Chưa đổi được mật khẩu. Vui lòng thử lại.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  InputDecoration _field(String label) => InputDecoration(
        labelText: label,
        prefixIcon: const Icon(Icons.lock_outline),
      );

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppScaffold(
      header: const AppHeader(title: 'Đặt mật khẩu của bạn'),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: AppSpacing.md),
          Text('Đổi mật khẩu tạm', style: text.headlineSmall),
          const SizedBox(height: AppSpacing.xs),
          Text(
            'Tài khoản đang dùng mật khẩu tạm do HTX cấp. Hãy đặt mật khẩu riêng '
            'để tiếp tục — người khác đã từng thấy mật khẩu tạm này.',
            style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.lg),
          TextField(
            key: const Key('forced-current'),
            controller: _current,
            enabled: !_busy,
            obscureText: _obscure,
            autofillHints: const [AutofillHints.password],
            decoration: _field('Mật khẩu tạm').copyWith(
              suffixIcon: IconButton(
                icon: Icon(_obscure ? Icons.visibility : Icons.visibility_off),
                onPressed: () => setState(() => _obscure = !_obscure),
                tooltip: _obscure ? 'Hiện mật khẩu' : 'Ẩn mật khẩu',
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          TextField(
            key: const Key('forced-next'),
            controller: _next,
            enabled: !_busy,
            obscureText: _obscure,
            autofillHints: const [AutofillHints.newPassword],
            decoration: _field('Mật khẩu mới'),
          ),
          const SizedBox(height: AppSpacing.sm),
          TextField(
            key: const Key('forced-confirm'),
            controller: _confirm,
            enabled: !_busy,
            obscureText: _obscure,
            autofillHints: const [AutofillHints.newPassword],
            onSubmitted: (_) => _submit(),
            decoration: _field('Nhập lại mật khẩu mới'),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text('Ít nhất 8 ký tự, có chữ hoa, chữ thường và số.',
              style: text.bodySmall?.copyWith(color: AppColors.textSecondary)),
          if (_error != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(_error!, style: text.bodyMedium?.copyWith(color: AppColors.error)),
          ],
          const SizedBox(height: AppSpacing.lg),
          PrimaryButton(label: 'Lưu mật khẩu và tiếp tục', loading: _busy, onPressed: _submit),
          const SizedBox(height: AppSpacing.sm),
          SecondaryButton(
            label: 'Đăng xuất',
            expanded: true,
            onPressed: _busy ? null : () => widget.onSignOut(),
          ),
        ],
      ),
    );
  }
}

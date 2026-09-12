import 'package:flutter/material.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../services/me_service.dart';
import '../services/read_api.dart';

/// Màn "Thông tin cá nhân" (từ SVG 26 "Tài khoản").
///
/// Dữ liệu THẬT từ `GET /v1/me`: họ tên, vai trò, số hộ/tổ chức tham gia. App
/// KHÔNG có API cập nhật hồ sơ → chỉ hiển thị. `/v1/me` KHÔNG trả điện thoại /
/// địa chỉ → hiện "Chưa có thông tin", không bịa.
class PersonalInfoScreen extends StatefulWidget {
  const PersonalInfoScreen({super.key, required this.services});
  final AppServices services;

  @override
  State<PersonalInfoScreen> createState() => _PersonalInfoScreenState();
}

const _kRoleLabels = <String, String>{
  'farmer': 'Nông dân',
  'cooperative_manager': 'Cán bộ hợp tác xã',
  'enterprise_viewer': 'Đơn vị theo dõi',
  'regulator': 'Cơ quan quản lý',
  'owner': 'Chủ ruộng',
  'editor': 'Người ghi dữ liệu',
  'viewer': 'Người xem',
};

class _PersonalInfoScreenState extends State<PersonalInfoScreen> {
  bool _loading = true;
  MeProfile? _profile;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final me = await widget.services.me.fetch();
      if (!mounted) return;
      setState(() {
        _profile = me;
        _loading = false;
      });
    } on ReadApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.isUnauthorized
            ? 'Phiên đăng nhập đã hết hạn. Đăng nhập lại để xem hồ sơ.'
            : 'Chưa lấy được hồ sơ từ hệ thống (mã ${e.statusCode}).';
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Mất kết nối tới hệ thống. Kiểm tra mạng rồi thử lại.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      header: const AppHeader(
        title: 'Thông tin cá nhân',
        showBackButton: true,
      ),
      body: _body(),
    );
  }

  Widget _body() {
    if (_loading) {
      return const LoadingState(message: 'Đang tải hồ sơ…');
    }
    if (_error != null) {
      return ErrorState(
        title: 'Chưa xem được hồ sơ',
        message: _error!,
        onRetry: _load,
      );
    }
    final me = _profile!;
    final text = Theme.of(context).textTheme;
    final roles = me.roles
        .map((r) => _kRoleLabels[r] ?? r)
        .where((s) => s.trim().isNotEmpty)
        .toSet()
        .join(' · ');
    final farmCount = _profile!.farmMembershipCount;
    final orgCount = _profile!.orgMembershipCount;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: AppSpacing.sm),
        _Field(label: 'Họ và tên', value: me.fullName ?? 'Chưa cập nhật tên'),
        _Field(
          label: 'Vai trò',
          value: roles.isEmpty ? 'Chưa gán vai trò' : roles,
        ),
        _Field(
          label: 'Tham gia',
          value: [
            if (farmCount > 0) '$farmCount hộ/ruộng',
            if (orgCount > 0) '$orgCount tổ chức',
          ].join(' · ').ifEmpty('Chưa tham gia hộ hoặc tổ chức nào'),
        ),
        _Field(label: 'Số điện thoại', value: 'Chưa có thông tin'),
        _Field(label: 'Địa chỉ', value: 'Chưa có thông tin'),
        const SizedBox(height: AppSpacing.md),
        Text(
          'Số điện thoại và địa chỉ chưa có trong hồ sơ hệ thống. Ứng dụng '
          'không sửa được hồ sơ — liên hệ cán bộ HTX để cập nhật.',
          style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
        ),
      ],
    );
  }
}

extension _StringOrDefault on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : this;
}

class _Field extends StatelessWidget {
  const _Field({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary)),
          const SizedBox(height: 2),
          Text(value, style: text.bodyLarge),
          const Divider(height: AppSpacing.md),
        ],
      ),
    );
  }
}

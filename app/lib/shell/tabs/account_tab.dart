import 'dart:convert';

import 'package:flutter/material.dart';

import '../../app_services.dart';
import '../../design/design.dart';
import '../../services/read_api.dart';
import '../routes.dart';

/// Nhãn vai trò tiếng Việt cho các giá trị `organization_role` + `farm_role` từ
/// `/v1/me`. Vai trò không nằm trong bảng này vẫn được hiển thị NGUYÊN VĂN (dữ
/// liệu thật) — không nuốt.
String accountRoleLabel(List<String> roles) {
  final labels = <String>{};
  for (final r in roles) {
    final l = _kRoleLabels[r] ?? r;
    if (l.trim().isNotEmpty) labels.add(l);
  }
  return labels.join(' · ');
}

/// Chữ viết tắt avatar từ HỌ TÊN THẬT (tối đa 2 ký tự, ký tự đầu của từ đầu +
/// từ cuối). `null` / rỗng → `null` (UI dùng icon người, KHÔNG bịa "NA").
@visibleForTesting
String? accountInitials(String? name) {
  if (name == null) return null;
  final parts =
      name.trim().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
  if (parts.isEmpty) return null;
  final first = parts.first.characters.first;
  final last = parts.length > 1 ? parts.last.characters.first : '';
  return (first + last).toUpperCase();
}

/// Tab "Tài khoản" (SVG 26): thẻ danh tính (avatar chữ + họ tên + vai trò + hộ)
/// + các mục điều hướng + Đăng xuất. Thanh 4 tab do [HomeShell] gắn.
///
/// Dữ liệu THẬT: họ tên + vai trò từ `GET /v1/me`; số ruộng + diện tích từ bảng
/// `plots` local; mã hộ từ `ActiveContext`. KHÔNG hardcode tên/mã hộ/số ruộng.
/// Điện thoại + địa chỉ: `/v1/me` không trả → hiện "Chưa có thông tin".
class AccountTab extends StatefulWidget {
  const AccountTab({super.key, required this.services});
  final AppServices services;

  @override
  State<AccountTab> createState() => _AccountTabState();
}

const _kNameKey = 'account.full_name';
const _kRolesKey = 'account.roles';

const _kRoleLabels = <String, String>{
  // organization_role
  'farmer': 'Nông dân',
  'cooperative_manager': 'Cán bộ hợp tác xã',
  'enterprise_viewer': 'Đơn vị theo dõi',
  'regulator': 'Cơ quan quản lý',
  // farm_role
  'owner': 'Chủ ruộng',
  'editor': 'Người ghi dữ liệu',
  'viewer': 'Người xem',
};

class _AccountTabState extends State<AccountTab> {
  AppServices get _s => widget.services;

  bool _loading = true;
  bool _fromCache = false;
  String? _fullName;
  List<String> _roles = const [];
  int _plotCount = 0;
  double _areaHa = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    // 1) Local trước (luôn có, kể cả offline).
    try {
      final summary = await _s.db.plotSummary();
      final cachedName = await _s.db.getMeta(_kNameKey);
      final cachedRoles = await _s.db.getMeta(_kRolesKey);
      if (!mounted) return;
      setState(() {
        _plotCount = summary.count;
        _areaHa = summary.areaHa;
        _fullName = cachedName;
        _roles = _decodeRoles(cachedRoles);
        _fromCache = cachedName != null || _roles.isNotEmpty;
      });
    } catch (_) {
      // DB có thể vừa đóng (đổi tài khoản) — bỏ qua.
    }

    // 2) Mạng (nếu có) — cập nhật họ tên + vai trò thật.
    if (!_s.connectivity.isOnline) {
      if (mounted) setState(() => _loading = false);
      return;
    }
    try {
      final me = await _s.me.fetch();
      if (!mounted) return;
      setState(() {
        _fullName = me.fullName;
        _roles = me.roles;
        _fromCache = false;
        _loading = false;
      });
      await _s.db.setMeta(_kNameKey, me.fullName);
      await _s.db.setMeta(_kRolesKey, jsonEncode(me.roles));
    } on ReadApiException {
      // 401/403 xử lý ở AuthController (tín hiệu phiên) — ở đây chỉ dừng loading
      // và giữ bản cache.
      if (mounted) setState(() => _loading = false);
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  static List<String> _decodeRoles(String? raw) {
    if (raw == null || raw.isEmpty) return const [];
    try {
      final d = jsonDecode(raw);
      if (d is List) return d.map((e) => e.toString()).toList();
    } catch (_) {}
    return const [];
  }

  String get _roleLabel => accountRoleLabel(_roles);

  String? get _farmLabel {
    final farm = _s.activeContext.farm;
    if (farm == null) return null;
    return 'Hộ ${farm.farmCode}';
  }

  Future<void> _signOut() async {
    final ok = await ConfirmationDialog.show(
      context,
      title: 'Đăng xuất?',
      message: 'Dữ liệu đã lưu trên máy vẫn được giữ. Bạn sẽ cần đăng nhập lại '
          'để đồng bộ và xem kết quả.',
      confirmLabel: 'Đăng xuất',
    );
    if (!ok || !mounted) return;
    // Qua AuthController (KHÔNG gọi thẳng auth.signOut) để tín hiệu signedOut kế
    // tiếp được hiểu là "đăng xuất chủ động", không phải "hết phiên". AuthGate
    // đổi phase → tự về màn đăng nhập; không điều hướng ở đây.
    await _s.authController.signOut();
  }

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      header: AppHeader(
        title: 'AgriCarbon',
        subtitle: 'Tài khoản',
        isOnline: _s.connectivity.isOnline,
      ),
      scrollable: false,
      padded: false,
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.screenH,
            AppSpacing.md,
            AppSpacing.screenH,
            AppSpacing.xl,
          ),
          children: [
            _IdentityCard(
              loading: _loading,
              fullName: _fullName,
              roleLabel: _roleLabel,
              farmLabel: _farmLabel,
              fromCache: _fromCache,
            ),
            const SizedBox(height: AppSpacing.md),
            _NavRow(
              icon: Icons.person_outline,
              title: 'Thông tin cá nhân',
              subtitle: 'Họ tên, vai trò, liên hệ',
              onTap: () => AppRoutes.openPersonalInfo(context, _s),
            ),
            const SizedBox(height: AppSpacing.sm),
            _NavRow(
              icon: Icons.agriculture_outlined,
              title: 'Ruộng của tôi',
              subtitle: _plotCount == 0
                  ? 'Chưa có ruộng nào trên máy'
                  : '$_plotCount ruộng · ${AppFormat.withUnit(_areaHa, 'ha', fractionDigits: 1)}',
              onTap: () => AppRoutes.openFarms(context, _s),
            ),
            const SizedBox(height: AppSpacing.sm),
            _NavRow(
              icon: Icons.settings_outlined,
              title: 'Cài đặt gửi dữ liệu',
              subtitle: 'Chọn Wi-Fi hoặc dữ liệu di động khi tự gửi',
              onTap: () => AppRoutes.openSyncSettings(context, _s),
            ),
            const SizedBox(height: AppSpacing.sm),
            _NavRow(
              icon: Icons.lock_outline,
              title: 'Đổi mật khẩu',
              subtitle: 'Giữ tài khoản an toàn',
              onTap: () => AppRoutes.openChangePassword(context, _s),
            ),
            const SizedBox(height: AppSpacing.sm),
            _NavRow(
              icon: Icons.help_outline,
              title: 'Trợ giúp',
              subtitle: 'Hướng dẫn sử dụng và liên hệ hỗ trợ',
              onTap: () => AppRoutes.openHelp(context),
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: 'Đăng xuất',
              icon: Icons.logout,
              onPressed: _signOut,
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------

class _IdentityCard extends StatelessWidget {
  const _IdentityCard({
    required this.loading,
    required this.fullName,
    required this.roleLabel,
    required this.farmLabel,
    required this.fromCache,
  });

  final bool loading;
  final String? fullName;
  final String roleLabel;
  final String? farmLabel;
  final bool fromCache;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final initials = accountInitials(fullName);
    final sub = [roleLabel, farmLabel ?? '']
        .where((s) => s.trim().isNotEmpty)
        .join(' · ');

    return AppCard(
      variant: AppCardVariant.highlight,
      child: Row(
        children: [
          Semantics(
            label: initials == null
                ? 'Ảnh đại diện: chưa có tên'
                : 'Ảnh đại diện: $fullName',
            child: CircleAvatar(
              radius: 26,
              backgroundColor: AppColors.primary,
              foregroundColor: Colors.white,
              child: initials == null
                  ? const Icon(Icons.person_outline)
                  : Text(initials,
                      style: const TextStyle(
                          fontSize: 18, fontWeight: FontWeight.w700)),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (loading && fullName == null)
                  Text('Đang tải hồ sơ…',
                      style: text.titleMedium
                          ?.copyWith(color: AppColors.textSecondary))
                else
                  Text(fullName ?? 'Chưa cập nhật tên',
                      style: text.titleMedium),
                if (sub.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(sub,
                      style: text.bodySmall
                          ?.copyWith(color: AppColors.textSecondary)),
                ],
                if (fromCache) ...[
                  const SizedBox(height: 2),
                  Text('Hồ sơ đã lưu trên máy — có thể chưa phải mới nhất.',
                      style: text.labelSmall
                          ?.copyWith(color: AppColors.textSecondary)),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _NavRow extends StatelessWidget {
  const _NavRow({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      onTap: onTap,
      child: Row(
        children: [
          ExcludeSemantics(child: Icon(icon, color: AppColors.primary)),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: text.titleSmall),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  style:
                      text.labelSmall?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
          const ExcludeSemantics(
            child: Icon(Icons.chevron_right, color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }
}

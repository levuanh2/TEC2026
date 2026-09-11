import 'read_api.dart';

/// Hồ sơ người dùng hiện tại — từ `GET /v1/me` (`MeResponse`, xem
/// `backend/infrastructure/read_repo.py::me()`). Vai trò LẤY TỪ DB, không tin
/// client. `/v1/me` KHÔNG trả điện thoại / địa chỉ — màn hình phải xử lý điều đó
/// bằng "Chưa có thông tin", không bịa.
class MeProfile {
  const MeProfile({
    required this.userId,
    required this.fullName,
    required this.roles,
    this.farmMembershipCount = 0,
    this.orgMembershipCount = 0,
  });

  final String userId;

  /// `null` nếu người dùng chưa đặt tên trong hồ sơ — màn hình phải xử lý null,
  /// KHÔNG hiện tên bịa.
  final String? fullName;

  /// Union đã sort của `organization_role` + `farm_role` (module dùng để suy
  /// quyền hiển thị).
  final List<String> roles;

  /// Số bản ghi `farm_memberships` / `organization_memberships` (chỉ để hiển
  /// thị "tham gia N hộ / N tổ chức"; chi tiết farm lấy từ DB local).
  final int farmMembershipCount;
  final int orgMembershipCount;

  bool get isFarmer => roles.contains('farmer');
}

class MeService {
  MeService(this._api);
  final ReadApi _api;

  Future<MeProfile> fetch() async {
    final json = await _api.getJson('/v1/me');
    final rawName = json['full_name'] as String?;
    return MeProfile(
      userId: json['user_id'] as String? ?? '',
      fullName:
          (rawName == null || rawName.trim().isEmpty) ? null : rawName.trim(),
      roles: ((json['roles'] as List?) ?? const [])
          .map((e) => e.toString())
          .toList(),
      farmMembershipCount: (json['farm_memberships'] as List?)?.length ?? 0,
      orgMembershipCount:
          (json['organization_memberships'] as List?)?.length ?? 0,
    );
  }
}

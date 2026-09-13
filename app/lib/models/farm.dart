/// Hộ / trang trại. Chỉ là **bản cache** của dữ liệu server — việc tạo Farm là
/// online-only (xem `farm_screen.dart`), nên Farm luôn có `id` thật của server,
/// không có sync metadata như Plot / Crop Season.
///
/// Địa bàn (tỉnh/huyện/xã) đặt Ở FARM theo schema Supabase — KHÔNG nằm ở Plot.
class Farm {
  const Farm({
    required this.id,
    required this.cooperativeId,
    required this.farmCode,
    required this.farmName,
    this.provinceName,
    this.districtName,
    this.communeName,
  });

  final String id; // server id (farms.id)
  final String cooperativeId; // farms.cooperative_id — organization id
  final String farmCode;
  final String farmName;
  final String? provinceName;
  final String? districtName;
  final String? communeName;

  /// Từ hàng SQLite cục bộ.
  factory Farm.fromRow(Map<String, dynamic> row) => Farm(
        id: row['id'] as String,
        cooperativeId: row['cooperative_id'] as String,
        farmCode: row['farm_code'] as String,
        farmName: row['farm_name'] as String,
        provinceName: row['province_name'] as String?,
        districtName: row['district_name'] as String?,
        communeName: row['commune_name'] as String?,
      );

  /// Từ hàng PostgREST (Supabase). Cùng tên cột nên map thẳng.
  factory Farm.fromServer(Map<String, dynamic> row) => Farm.fromRow(row);

  Map<String, dynamic> toRow() => {
        'id': id,
        'cooperative_id': cooperativeId,
        'farm_code': farmCode,
        'farm_name': farmName,
        'province_name': provinceName,
        'district_name': districtName,
        'commune_name': communeName,
        'updated_at': DateTime.now().toIso8601String(),
      };

  String get locationLabel {
    final parts = [communeName, districtName, provinceName]
        .where((p) => p != null && p.trim().isNotEmpty)
        .toList();
    return parts.isEmpty ? '' : parts.join(', ');
  }
}

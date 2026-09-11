import 'sync_state.dart';

/// Thửa ruộng — offline-first. `clientId` là khoá ổn định do máy sinh, KHÔNG
/// bao giờ đổi; `serverId` là `plots.id` thật, chỉ có sau khi đồng bộ thành công.
/// Trước đó mọi tham chiếu con (Crop Season) dùng `clientId`.
///
/// Tỉnh/huyện/xã KHÔNG nằm ở đây — theo schema chúng thuộc Farm.
class Plot {
  const Plot({
    required this.clientId,
    this.serverId,
    required this.farmId,
    required this.plotCode,
    required this.name,
    required this.areaHa,
    this.latitude,
    this.longitude,
    this.syncState = SyncState.pending,
    this.syncErrorCode,
    this.retryCount = 0,
    this.lastAttemptAt,
    required this.createdAt,
    required this.updatedAt,
  });

  final String clientId;
  final String? serverId;
  final String farmId; // server id của Farm (Farm là online-only nên luôn có)
  final String plotCode;
  final String name;
  final double areaHa;
  final double? latitude;
  final double? longitude;

  final SyncState syncState;
  final String? syncErrorCode;
  final int retryCount;
  final DateTime? lastAttemptAt;
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get isSynced => serverId != null && syncState == SyncState.synced;

  factory Plot.fromRow(Map<String, dynamic> row) => Plot(
        clientId: row['id'] as String,
        serverId: row['server_id'] as String?,
        farmId: row['farm_id'] as String,
        plotCode: row['plot_code'] as String,
        name: row['name'] as String,
        areaHa: (row['area_ha'] as num).toDouble(),
        latitude: (row['latitude'] as num?)?.toDouble(),
        longitude: (row['longitude'] as num?)?.toDouble(),
        syncState: SyncStateCodec.fromValue(row['sync_state'] as String?),
        syncErrorCode: row['sync_error_code'] as String?,
        retryCount: (row['retry_count'] as int?) ?? 0,
        lastAttemptAt: _parse(row['last_attempt_at']),
        createdAt: _parse(row['created_at']) ?? DateTime.now(),
        updatedAt: _parse(row['updated_at']) ?? DateTime.now(),
      );

  Map<String, dynamic> toRow() => {
        'id': clientId,
        'server_id': serverId,
        'farm_id': farmId,
        'plot_code': plotCode,
        'name': name,
        'area_ha': areaHa,
        'latitude': latitude,
        'longitude': longitude,
        'sync_state': syncState.value,
        'sync_error_code': syncErrorCode,
        'retry_count': retryCount,
        'last_attempt_at': lastAttemptAt?.toIso8601String(),
        'created_at': createdAt.toIso8601String(),
        'updated_at': updatedAt.toIso8601String(),
      };

  /// Payload gửi lên `plots` — KHÔNG gửi id (server tự sinh), KHÔNG gửi metadata
  /// local. GPS chỉ gửi khi có.
  Map<String, dynamic> toServerInsert() => {
        'farm_id': farmId,
        'plot_code': plotCode,
        'name': name,
        'area_ha': areaHa,
        if (latitude != null) 'latitude': latitude,
        if (longitude != null) 'longitude': longitude,
      };

  Plot copyWith({
    String? serverId,
    String? plotCode,
    String? name,
    double? areaHa,
    double? latitude,
    double? longitude,
    SyncState? syncState,
    String? syncErrorCode,
    int? retryCount,
    DateTime? lastAttemptAt,
    DateTime? updatedAt,
    bool clearSyncError = false,
  }) =>
      Plot(
        clientId: clientId,
        serverId: serverId ?? this.serverId,
        farmId: farmId,
        plotCode: plotCode ?? this.plotCode,
        name: name ?? this.name,
        areaHa: areaHa ?? this.areaHa,
        latitude: latitude ?? this.latitude,
        longitude: longitude ?? this.longitude,
        syncState: syncState ?? this.syncState,
        syncErrorCode:
            clearSyncError ? null : (syncErrorCode ?? this.syncErrorCode),
        retryCount: retryCount ?? this.retryCount,
        lastAttemptAt: lastAttemptAt ?? this.lastAttemptAt,
        createdAt: createdAt,
        updatedAt: updatedAt ?? DateTime.now(),
      );

  static DateTime? _parse(Object? v) =>
      v is String && v.isNotEmpty ? DateTime.tryParse(v) : null;
}

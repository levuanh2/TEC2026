import 'methodology_enums.dart';
import 'sync_state.dart';

/// Vụ canh tác trên một thửa — offline-first, chứa các biến phương pháp luận mà
/// Carbon Engine cần. `clientId` ổn định do máy sinh; `serverId` = `crop_seasons.id`
/// thật, chỉ có sau khi đồng bộ. Carbon LUÔN gọi bằng `serverId`.
///
/// `plotClientId` trỏ tới `Plot.clientId` (ổn định) — lúc đồng bộ mới tra ra
/// `Plot.serverId` để gửi.
class CropSeason {
  const CropSeason({
    required this.clientId,
    this.serverId,
    required this.plotClientId,
    required this.seasonCode,
    this.cropType = 'rice',
    this.varietyName,
    this.plantingDate,
    this.expectedHarvestDate,
    this.actualHarvestDate,
    this.defaultIrrigationMethod,
    this.ipccWaterRegime,
    this.preSeasonWaterRegime,
    this.cultivationDays,
    this.drainageEventCount,
    this.status = CropSeasonStatus.planned,
    this.syncState = SyncState.pending,
    this.syncErrorCode,
    this.retryCount = 0,
    this.lastAttemptAt,
    required this.createdAt,
    required this.updatedAt,
  });

  final String clientId;
  final String? serverId;
  final String plotClientId;
  final String seasonCode;
  final String cropType;
  final String? varietyName;

  final DateTime? plantingDate;
  final DateTime? expectedHarvestDate;
  final DateTime? actualHarvestDate;

  // Biến phương pháp luận — để null khi chưa biết, KHÔNG tự đặt mặc định.
  final DefaultIrrigationMethod? defaultIrrigationMethod;
  final IpccWaterRegime? ipccWaterRegime;
  final PreSeasonWaterRegime? preSeasonWaterRegime;
  final int? cultivationDays;
  final int? drainageEventCount;

  final CropSeasonStatus status;

  final SyncState syncState;
  final String? syncErrorCode;
  final int retryCount;
  final DateTime? lastAttemptAt;
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get isSynced => serverId != null && syncState == SyncState.synced;

  factory CropSeason.fromRow(Map<String, dynamic> row) => CropSeason(
        clientId: row['id'] as String,
        serverId: row['server_id'] as String?,
        plotClientId: row['plot_id'] as String,
        seasonCode: row['season_code'] as String,
        cropType: (row['crop_type'] as String?) ?? 'rice',
        varietyName: row['variety_name'] as String?,
        plantingDate: _parse(row['planting_date']),
        expectedHarvestDate: _parse(row['expected_harvest_date']),
        actualHarvestDate: _parse(row['actual_harvest_date']),
        defaultIrrigationMethod: DefaultIrrigationMethod.fromWire(
            row['default_irrigation_method'] as String?),
        ipccWaterRegime:
            IpccWaterRegime.fromWire(row['ipcc_water_regime'] as String?),
        preSeasonWaterRegime: PreSeasonWaterRegime.fromWire(
            row['pre_season_water_regime'] as String?),
        cultivationDays: row['cultivation_days'] as int?,
        drainageEventCount: row['drainage_event_count'] as int?,
        status: CropSeasonStatus.fromWire(row['status'] as String?),
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
        'plot_id': plotClientId,
        'season_code': seasonCode,
        'crop_type': cropType,
        'variety_name': varietyName,
        'planting_date': _dateOnly(plantingDate),
        'expected_harvest_date': _dateOnly(expectedHarvestDate),
        'actual_harvest_date': _dateOnly(actualHarvestDate),
        'default_irrigation_method': defaultIrrigationMethod?.wire,
        'ipcc_water_regime': ipccWaterRegime?.wire,
        'pre_season_water_regime': preSeasonWaterRegime?.wire,
        'cultivation_days': cultivationDays,
        'drainage_event_count': drainageEventCount,
        'status': status.wire,
        'sync_state': syncState.value,
        'sync_error_code': syncErrorCode,
        'retry_count': retryCount,
        'last_attempt_at': lastAttemptAt?.toIso8601String(),
        'created_at': createdAt.toIso8601String(),
        'updated_at': updatedAt.toIso8601String(),
      };

  /// Payload gửi lên `crop_seasons`. `plot_id` (server) do `sync_service` tra
  /// `plotClientId` → `Plot.serverId` rồi truyền vào đây. Field phương pháp luận
  /// chỉ gửi khi CÓ giá trị — không gửi `null` để server không ép mặc định.
  Map<String, dynamic> toServerInsert({required String plotServerId}) => {
        'plot_id': plotServerId,
        'season_code': seasonCode,
        'crop_type': cropType,
        if (varietyName != null && varietyName!.trim().isNotEmpty)
          'variety_name': varietyName,
        if (plantingDate != null) 'planting_date': _dateOnly(plantingDate),
        if (expectedHarvestDate != null)
          'expected_harvest_date': _dateOnly(expectedHarvestDate),
        if (actualHarvestDate != null)
          'actual_harvest_date': _dateOnly(actualHarvestDate),
        if (defaultIrrigationMethod != null)
          'default_irrigation_method': defaultIrrigationMethod!.wire,
        // Biến phương pháp luận LUÔN gửi, kể cả null: đây cũng là đường SỬA một
        // vụ đã đồng bộ (upsert theo plot_id + season_code), nên bỏ key thì
        // server giữ giá trị cũ và người dùng không xoá được. Các cột này không
        // có default trên DB (null không bị "ép" thành gì cả).
        'ipcc_water_regime': ipccWaterRegime?.wire,
        'pre_season_water_regime': preSeasonWaterRegime?.wire,
        'cultivation_days': cultivationDays,
        'drainage_event_count': drainageEventCount,
        'status': status.wire,
      };

  CropSeason copyWith({
    String? serverId,
    String? seasonCode,
    String? varietyName,
    DateTime? plantingDate,
    DateTime? expectedHarvestDate,
    DateTime? actualHarvestDate,
    DefaultIrrigationMethod? defaultIrrigationMethod,
    IpccWaterRegime? ipccWaterRegime,
    PreSeasonWaterRegime? preSeasonWaterRegime,
    int? cultivationDays,
    int? drainageEventCount,
    CropSeasonStatus? status,
    SyncState? syncState,
    String? syncErrorCode,
    int? retryCount,
    DateTime? lastAttemptAt,
    DateTime? updatedAt,
    bool clearSyncError = false,
  }) =>
      CropSeason(
        clientId: clientId,
        serverId: serverId ?? this.serverId,
        plotClientId: plotClientId,
        seasonCode: seasonCode ?? this.seasonCode,
        cropType: cropType,
        varietyName: varietyName ?? this.varietyName,
        plantingDate: plantingDate ?? this.plantingDate,
        expectedHarvestDate: expectedHarvestDate ?? this.expectedHarvestDate,
        actualHarvestDate: actualHarvestDate ?? this.actualHarvestDate,
        defaultIrrigationMethod:
            defaultIrrigationMethod ?? this.defaultIrrigationMethod,
        ipccWaterRegime: ipccWaterRegime ?? this.ipccWaterRegime,
        preSeasonWaterRegime: preSeasonWaterRegime ?? this.preSeasonWaterRegime,
        cultivationDays: cultivationDays ?? this.cultivationDays,
        drainageEventCount: drainageEventCount ?? this.drainageEventCount,
        status: status ?? this.status,
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

  static String? _dateOnly(DateTime? d) => d == null
      ? null
      : '${d.year.toString().padLeft(4, '0')}-'
          '${d.month.toString().padLeft(2, '0')}-'
          '${d.day.toString().padLeft(2, '0')}';
}

import 'dart:convert';

import 'sync_state.dart';

export 'sync_state.dart';

/// 7 loại hoạt động theo khung "1 phải 5 giảm" — khớp `public.activity_type` ở Supabase.
const kActivityTypes = <String>[
  'seeding', // giống
  'fertilizer', // phân bón
  'irrigation', // nước tưới
  'pesticide', // thuốc BVTV
  'straw_management', // rơm rạ
  'fuel', // nhiên liệu
  'harvest', // thu hoạch
];

/// Một hoạt động canh tác, lưu offline trước, đồng bộ sau.
///
///   - `clientEventId` : app tự sinh (UUID v4) lúc tạo activity, KHÔNG BAO GIỜ đổi
///                       — kể cả khi SỬA. Là khoá chính local (`activities.id`) và
///                       gửi lên cột `activities.client_event_id`; ghép với
///                       `device_id` → khoá duy nhất `(device_id, client_event_id)`
///                       nên gửi lại (retry / sau khi sửa) là upsert, không tạo trùng.
///   - `serverActivityId` : `activities.id` thật, CHỈ có sau khi đồng bộ thành công.
///   - `deletedLocally` : tombstone — người dùng đã xoá bản ghi ĐÃ đồng bộ; giữ
///                       lại local + `sync_state = pending` để đẩy `deleted_at` lên
///                       server. Chỉ xoá hẳn local sau khi server xác nhận.
///
/// `type` là bất biến sau khi tạo: đổi loại = đổi bảng chi tiết → mồ côi bản ghi
/// cũ trên server. Form sửa KHÔNG cho đổi loại.
class Activity {
  final String clientEventId;

  /// `crop_seasons.client_id` (ổn định) của vụ chứa hoạt động này — KHÔNG phải
  /// server id. Lúc đồng bộ, `sync_service` tra `client_id` → `server_id`.
  final String cropSeasonId;
  final String type;
  final DateTime occurredAt;
  final Map<String, dynamic>
      payload; // khớp cột bảng chi tiết, xem activity_field_spec
  final String? note;
  final SyncState syncState;
  final String? syncError;
  final DateTime createdAt;
  final String? serverActivityId;
  final bool deletedLocally;

  /// Metadata máy đồng bộ — do `LocalDatabase` quản (partial UPDATE), KHÔNG ghi
  /// qua `toLocalMap` (edit = replace → về mặc định = một lượt thử mới).
  final int retryCount;
  final DateTime? lastAttemptAt;
  final DateTime? syncedAt;

  const Activity({
    required this.clientEventId,
    required this.cropSeasonId,
    required this.type,
    required this.occurredAt,
    required this.payload,
    this.note,
    this.syncState = SyncState.pending,
    this.syncError,
    required this.createdAt,
    this.serverActivityId,
    this.deletedLocally = false,
    this.retryCount = 0,
    this.lastAttemptAt,
    this.syncedAt,
  });

  bool get isPendingDelete => deletedLocally;

  /// Sửa nội dung (giữ nguyên `clientEventId`, `type`, `createdAt`) → luôn quay
  /// về `pending` để đẩy lại; xoá `syncError`.
  Activity editedWith({
    DateTime? occurredAt,
    Map<String, dynamic>? payload,
    String? note,
    bool clearNote = false,
  }) =>
      Activity(
        clientEventId: clientEventId,
        cropSeasonId: cropSeasonId,
        type: type,
        occurredAt: occurredAt ?? this.occurredAt,
        payload: payload ?? this.payload,
        note: clearNote ? null : (note ?? this.note),
        syncState: SyncState.pending,
        syncError: null,
        createdAt: createdAt,
        serverActivityId: serverActivityId,
        deletedLocally: deletedLocally,
      );

  Activity copyWith({
    SyncState? syncState,
    String? syncError,
    String? serverActivityId,
    bool? deletedLocally,
    int? retryCount,
    DateTime? lastAttemptAt,
    DateTime? syncedAt,
    bool clearSyncError = false,
  }) =>
      Activity(
        clientEventId: clientEventId,
        cropSeasonId: cropSeasonId,
        type: type,
        occurredAt: occurredAt,
        payload: payload,
        note: note,
        syncState: syncState ?? this.syncState,
        syncError: clearSyncError ? null : (syncError ?? this.syncError),
        createdAt: createdAt,
        serverActivityId: serverActivityId ?? this.serverActivityId,
        deletedLocally: deletedLocally ?? this.deletedLocally,
        retryCount: retryCount ?? this.retryCount,
        lastAttemptAt: lastAttemptAt ?? this.lastAttemptAt,
        syncedAt: syncedAt ?? this.syncedAt,
      );

  static DateTime? _parseOpt(Object? v) =>
      v is String && v.isNotEmpty ? DateTime.tryParse(v) : null;

  factory Activity.fromLocalMap(Map<String, dynamic> map) => Activity(
        clientEventId: map['id'] as String,
        cropSeasonId: map['crop_season_id'] as String,
        type: map['type'] as String,
        occurredAt: DateTime.parse(map['occurred_at'] as String),
        payload:
            jsonDecode(map['payload_json'] as String) as Map<String, dynamic>,
        note: map['note'] as String?,
        syncState: SyncStateCodec.fromValue(map['sync_state'] as String?),
        syncError: map['sync_error'] as String?,
        createdAt: DateTime.parse(map['created_at'] as String),
        serverActivityId: map['server_activity_id'] as String?,
        deletedLocally: (map['deleted_locally'] as int? ?? 0) == 1,
        retryCount: (map['retry_count'] as int?) ?? 0,
        lastAttemptAt: _parseOpt(map['last_attempt_at']),
        syncedAt: _parseOpt(map['synced_at']),
      );

  Map<String, dynamic> toLocalMap() => {
        'id': clientEventId,
        'crop_season_id': cropSeasonId,
        'type': type,
        'occurred_at': occurredAt.toIso8601String(),
        'payload_json': jsonEncode(payload),
        'note': note,
        'sync_state': syncState.value,
        'sync_error': syncError,
        'created_at': createdAt.toIso8601String(),
        'server_activity_id': serverActivityId,
        'deleted_locally': deletedLocally ? 1 : 0,
      };
}

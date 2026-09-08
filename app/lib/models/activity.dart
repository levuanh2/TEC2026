import 'dart:convert';

/// Trạng thái đồng bộ của một Activity trong hàng đợi local.
///
/// Không tách bảng SyncQueue riêng — trạng thái nằm ngay trên activities.
/// Một nguồn sự thật duy nhất, tránh activities và sync_queue lệch nhau.
/// (ponytail: đơn giản hơn hai bảng, vẫn trả lời đủ câu hỏi "còn gì chưa đồng bộ").
enum SyncState { pending, syncing, synced, failed }

extension SyncStateCodec on SyncState {
  String get value => name;
  static SyncState fromValue(String v) =>
      SyncState.values.firstWhere((s) => s.name == v, orElse: () => SyncState.pending);
}

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
/// `id` = `client_event_id` gửi lên Supabase (client tự sinh — server KHÔNG sinh
/// thay). Ghép với `deviceId` tạo khoá duy nhất `(device_id, client_event_id)` —
/// gửi lại vẫn idempotent, retry an toàn (FR-1a-07).
class Activity {
  final String id; // = client_event_id
  final String cropSeasonId;
  final String type;
  final DateTime occurredAt;
  final Map<String, dynamic> payload; // field riêng theo `type`, xem forms/
  final String? note;
  final SyncState syncState;
  final String? syncError;
  final DateTime createdAt;
  final String? serverActivityId; // id thật trên Supabase, có sau khi sync xong

  const Activity({
    required this.id,
    required this.cropSeasonId,
    required this.type,
    required this.occurredAt,
    required this.payload,
    this.note,
    this.syncState = SyncState.pending,
    this.syncError,
    required this.createdAt,
    this.serverActivityId,
  });

  Activity copyWith({
    SyncState? syncState,
    String? syncError,
    String? serverActivityId,
  }) =>
      Activity(
        id: id,
        cropSeasonId: cropSeasonId,
        type: type,
        occurredAt: occurredAt,
        payload: payload,
        note: note,
        syncState: syncState ?? this.syncState,
        syncError: syncError,
        createdAt: createdAt,
        serverActivityId: serverActivityId ?? this.serverActivityId,
      );

  factory Activity.fromLocalMap(Map<String, dynamic> map) => Activity(
        id: map['id'] as String,
        cropSeasonId: map['crop_season_id'] as String,
        type: map['type'] as String,
        occurredAt: DateTime.parse(map['occurred_at'] as String),
        payload: jsonDecode(map['payload_json'] as String) as Map<String, dynamic>,
        note: map['note'] as String?,
        syncState: SyncStateCodec.fromValue(map['sync_state'] as String),
        syncError: map['sync_error'] as String?,
        createdAt: DateTime.parse(map['created_at'] as String),
        serverActivityId: map['server_activity_id'] as String?,
      );

  Map<String, dynamic> toLocalMap() => {
        'id': id,
        'crop_season_id': cropSeasonId,
        'type': type,
        'occurred_at': occurredAt.toIso8601String(),
        'payload_json': jsonEncode(payload),
        'note': note,
        'sync_state': syncState.value,
        'sync_error': syncError,
        'created_at': createdAt.toIso8601String(),
        'server_activity_id': serverActivityId,
      };
}

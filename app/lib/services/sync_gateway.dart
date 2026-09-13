import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:supabase_flutter/supabase_flutter.dart';

/// Bề mặt hẹp cho MỌI thao tác mạng của [SyncService] tới Supabase/PostgREST.
///
/// Tách ra để:
///  - test được luồng đồng bộ (đặc biệt là xác nhận xoá tombstone) mà KHÔNG cần
///    mock `SupabaseClient` phức tạp và KHÔNG chạm mạng thật;
///  - gom một chỗ quy ước "phải yêu cầu server trả về row đã ghi" — không suy ra
///    kết quả chỉ từ việc request không ném.
abstract interface class SyncGateway {
  /// upsert `plots` theo khoá tự nhiên `(farm_id, plot_code)` → server id.
  Future<String> upsertPlot(Map<String, dynamic> row);

  /// upsert `crop_seasons` theo `(plot_id, season_code)` → server id.
  Future<String> upsertCropSeason(Map<String, dynamic> row);

  /// upsert `production_batches` theo `(crop_season_id, batch_code)` → server id.
  Future<String> ensureDefaultBatch(String cropSeasonServerId);

  /// Ghi 1 `activities` idempotent theo `(device_id, client_event_id)` → server
  /// id. KHÔNG dùng `upsert onConflict` cho bảng này: chỉ mục duy nhất là
  /// **partial index** (`where device_id is not null and client_event_id is not
  /// null`) nên `ON CONFLICT (device_id, client_event_id)` không suy ra được và
  /// dễ lỗi `42P10`. Thay bằng: tìm theo cặp khoá → có thì UPDATE theo `id`,
  /// chưa có thì INSERT.
  Future<String> upsertActivity(Map<String, dynamic> row);

  /// upsert 1 bảng chi tiết (`fertilizer_applications`, ...) theo `activity_id`
  /// (khoá CHÍNH — `ON CONFLICT (activity_id)` an toàn).
  Future<void> upsertActivityDetail(String table, Map<String, dynamic> row);

  /// Xoá mềm 1 activity theo SERVER id, qua RPC `public.soft_delete_activity`.
  ///
  /// KHÔNG dùng `update activities set deleted_at = ...`: Postgres áp policy
  /// SELECT lên CẢ dòng MỚI của một UPDATE, mà `activities_select` đòi
  /// `deleted_at is null` — nên mọi client tự set `deleted_at` đều bị 42501,
  /// bất kể `activities_update` cho phép gì. RPC chạy security definer, tự kiểm
  /// tra quyền bằng đúng helper mà policy dùng (`private.user_can_write_batch`
  /// + `recorded_by = auth.uid()`), rồi mới ghi `deleted_at`.
  ///
  /// Kết quả KHÔNG mơ hồ — đây là điểm khác biệt với đường UPDATE cũ:
  ///  - trả về bình thường → dòng đó ĐANG ở trạng thái đã xoá mềm, dù lượt này
  ///    hay lượt trước ghi (idempotent). Caller được dọn tombstone local.
  ///  - ném `PostgrestException` 42501 → caller KHÔNG có quyền xoá dòng này
  ///    (khác chủ / khác phạm vi). Lỗi VĨNH VIỄN, không thử lại.
  ///  - ném lỗi mạng → tạm thời, lượt sau thử lại.
  Future<void> softDeleteActivity(String serverActivityId);

  /// `auth.uid()` của phiên hiện tại — `null` nếu KHÔNG có phiên đăng nhập.
  ///
  /// Nguồn duy nhất cho `activities.recorded_by`: lấy từ phiên Supabase đang
  /// hoạt động, KHÔNG bao giờ từ form hay hằng số trong mã.
  String? currentUserId();

  /// `organization_id` đang hiệu lực của user hiện tại — `null` nếu chưa thuộc
  /// HTX nào (hoặc chưa đăng nhập).
  Future<String?> currentCooperativeId();

  Future<List<Map<String, dynamic>>> fetchFarms();
  Future<List<Map<String, dynamic>>> fetchPlots();
  Future<List<Map<String, dynamic>>> fetchCropSeasons();
}

/// Bản dựng thật trên `supabase_flutter`. KHÔNG chứa logic nghiệp vụ — chỉ dịch
/// lời gọi sang PostgREST và ép "trả về row đã ghi".
class SupabaseSyncGateway implements SyncGateway {
  SupabaseSyncGateway(SupabaseClient client) : _client = client;

  /// CHỈ cho test luồng `upsertActivity` (race 23505): lớp con override 3 seam
  /// `findActivityIdByKey` / `insertActivityReturningId` / `updateActivityById`
  /// nên KHÔNG chạm `_client`.
  @visibleForTesting
  SupabaseSyncGateway.protectedForTest();

  late final SupabaseClient _client;

  @override
  Future<String> upsertPlot(Map<String, dynamic> row) async {
    final r = await _client
        .from('plots')
        .upsert(row, onConflict: 'farm_id,plot_code')
        .select('id')
        .single();
    return r['id'] as String;
  }

  @override
  Future<String> upsertCropSeason(Map<String, dynamic> row) async {
    final r = await _client
        .from('crop_seasons')
        .upsert(row, onConflict: 'plot_id,season_code')
        .select('id')
        .single();
    return r['id'] as String;
  }

  @override
  Future<String> ensureDefaultBatch(String cropSeasonServerId) async {
    final r = await _client
        .from('production_batches')
        .upsert(
          {'crop_season_id': cropSeasonServerId, 'batch_code': 'default'},
          onConflict: 'crop_season_id,batch_code',
        )
        .select('id')
        .single();
    return r['id'] as String;
  }

  @override
  Future<String> upsertActivity(Map<String, dynamic> row) async {
    final deviceId = row['device_id'] as String?;
    final clientEventId = row['client_event_id'] as String?;

    // Tìm theo cặp khoá tự nhiên — tránh `ON CONFLICT` trên partial unique
    // index `(device_id, client_event_id) where ... is not null` (dễ lỗi 42P10).
    final existing = await findActivityIdByKey(deviceId, clientEventId);
    if (existing != null) {
      await updateActivityById(existing, row);
      return existing;
    }

    try {
      return await insertActivityReturningId(row);
    } on PostgrestException catch (e) {
      // TOCTOU: một lượt khác vừa INSERT đúng cặp khoá này giữa SELECT và INSERT
      // của mình → Postgres `unique_violation` (23505). KHÔNG nuốt như lỗi
      // chung: đọc lại row đó rồi tiếp tục (detail dùng đúng server id).
      if (e.code != '23505') rethrow;
      final raced = await findActivityIdByKey(deviceId, clientEventId);
      if (raced != null) {
        await updateActivityById(raced, row);
        return raced;
      }
      // 23505 nhưng vẫn không thấy row (đọc lệch replica / xoá ngay sau) → NÉM
      // để lượt sau thử lại; KHÔNG đánh dấu synced giả.
      rethrow;
    }
  }

  // -- Seam cho test: 3 thao tác thô, override để mô phỏng race 23505 -------

  @visibleForTesting
  Future<String?> findActivityIdByKey(
      String? deviceId, String? clientEventId) async {
    final r = await _client
        .from('activities')
        .select('id')
        .eq('device_id', deviceId as Object)
        .eq('client_event_id', clientEventId as Object)
        .limit(1)
        .maybeSingle();
    return r?['id'] as String?;
  }

  @visibleForTesting
  Future<String> insertActivityReturningId(Map<String, dynamic> row) async {
    final r =
        await _client.from('activities').insert(row).select('id').single();
    return r['id'] as String;
  }

  @visibleForTesting
  Future<void> updateActivityById(String id, Map<String, dynamic> row) async {
    await _client.from('activities').update(row).eq('id', id);
  }

  @override
  Future<void> upsertActivityDetail(
    String table,
    Map<String, dynamic> row,
  ) async {
    await _client.from(table).upsert(row, onConflict: 'activity_id');
  }

  @override
  Future<void> softDeleteActivity(String serverActivityId) async {
    await _client.rpc<void>(
      'soft_delete_activity',
      params: {'p_activity_id': serverActivityId},
    );
  }

  @override
  String? currentUserId() => _client.auth.currentUser?.id;

  @override
  Future<String?> currentCooperativeId() async {
    final userId = _client.auth.currentUser?.id;
    if (userId == null) return null;
    final rows = await _client
        .from('organization_memberships')
        .select('organization_id')
        .eq('user_id', userId)
        .isFilter('ended_at', null)
        .limit(1);
    final list = rows as List;
    if (list.isEmpty) return null;
    return list.first['organization_id'] as String;
  }

  @override
  Future<List<Map<String, dynamic>>> fetchFarms() => _selectAll('farms');

  @override
  Future<List<Map<String, dynamic>>> fetchPlots() => _selectAll('plots');

  @override
  Future<List<Map<String, dynamic>>> fetchCropSeasons() =>
      _selectAll('crop_seasons');

  Future<List<Map<String, dynamic>>> _selectAll(String table) async {
    final rows = await _client.from(table).select();
    return [
      for (final r in rows as List) Map<String, dynamic>.from(r as Map),
    ];
  }
}

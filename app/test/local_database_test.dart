// ⚠️ CHƯA CHẠY LẦN NÀO — môi trường viết code này không có Flutter/Dart SDK.
// Chạy thật bằng: cd app && flutter test test/local_database_test.dart
//
// Dùng sqflite_common_ffi để chạy trên desktop (không cần emulator/thiết bị).

import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';

void main() {
  sqfliteFfiInit();
  final factory = databaseFactoryFfi;

  Future<LocalDatabase> freshDb() =>
      LocalDatabase.openWith(factory, inMemoryDatabasePath);

  test('offline: activity ghi xuống rồi đọc lại nguyên vẹn (không cần mạng)', () async {
    final db = await freshDb();
    final activity = Activity(
      clientEventId: 'a1',
      cropSeasonId: 'season-1',
      type: 'fertilizer',
      occurredAt: DateTime(2026, 2, 1),
      payload: {'fertilizer_name': 'Urea', 'amount_kg': 120, 'nitrogen_percent': 46},
      createdAt: DateTime(2026, 2, 1, 8, 0),
    );

    await db.insertActivity(activity);
    final rows = await db.listActivitiesByCropSeason('season-1');

    expect(rows, hasLength(1));
    expect(rows.first.payload['amount_kg'], 120);
    expect(rows.first.payload['nitrogen_percent'], 46);
    expect(rows.first.syncState, SyncState.pending);
  });

  test('20 activity offline -> đúng 20 pending, không mất bản ghi nào', () async {
    final db = await freshDb();
    for (var i = 0; i < 20; i++) {
      await db.insertActivity(Activity(
        clientEventId: 'a$i',
        cropSeasonId: 'season-1',
        type: 'irrigation',
        occurredAt: DateTime(2026, 2, i + 1),
        payload: {'method': 'awd'},
        createdAt: DateTime.now(),
      ));
    }
    expect(await db.countPendingActivities(), 20);
    expect(await db.listPendingActivities(), hasLength(20));
  });

  test('sync state chuyển pending -> synced, giữ nguyên server_activity_id', () async {
    final db = await freshDb();
    await db.insertActivity(Activity(
      clientEventId: 'a1',
      cropSeasonId: 'season-1',
      type: 'harvest',
      occurredAt: DateTime(2026, 5, 1),
      payload: {'yield_kg': 5200},
      createdAt: DateTime.now(),
    ));

    await db.updateActivitySyncState(
      'a1',
      state: SyncState.synced,
      serverActivityId: 'server-uuid-123',
    );

    final rows = await db.listActivitiesByCropSeason('season-1');
    expect(rows.first.syncState, SyncState.synced);
    expect(rows.first.serverActivityId, 'server-uuid-123');
    expect(await db.countPendingActivities(), 0);
  });

  test('sync thất bại -> failed + lý do lỗi, vẫn đếm là "còn phải đồng bộ"', () async {
    final db = await freshDb();
    await db.insertActivity(Activity(
      clientEventId: 'a1',
      cropSeasonId: 'season-1',
      type: 'fuel',
      occurredAt: DateTime(2026, 3, 1),
      payload: {'fuel_type': 'diesel', 'amount_liter': 25},
      createdAt: DateTime.now(),
    ));

    await db.updateActivitySyncState('a1', state: SyncState.failed, error: 'network error');

    final rows = await db.listActivitiesByCropSeason('season-1');
    expect(rows.first.syncState, SyncState.failed);
    expect(rows.first.syncError, 'network error');
    // failed vẫn được coi là "chưa xong" -> retry lại được ở lượt sync sau.
    expect(await db.countPendingActivities(), 1);
  });

  test('clientEventId ổn định qua nhiều lần retry -> KHÔNG bao giờ tạo hàng thứ 2', () async {
    // Mô phỏng sync_service.dart gọi lại nhiều lần cho CÙNG một activity (mất
    // mạng giữa chừng, thử lại) — clientEventId không đổi giữa các lần gọi,
    // nên updateActivitySyncState phải luôn cập nhật ĐÚNG 1 hàng đã có, không
    // bao giờ insert thêm. Đây là điều kiện cần để (device_id, client_event_id)
    // idempotent phía Supabase thật sự hoạt động.
    final db = await freshDb();
    const clientEventId = 'stable-client-event-id';
    await db.insertActivity(Activity(
      clientEventId: clientEventId,
      cropSeasonId: 'season-1',
      type: 'harvest',
      occurredAt: DateTime(2026, 5, 1),
      payload: {'yield_kg': 5200},
      createdAt: DateTime.now(),
    ));

    // Lần 1: syncing rồi failed (giả lập mất mạng giữa chừng).
    await db.updateActivitySyncState(clientEventId, state: SyncState.syncing);
    await db.updateActivitySyncState(clientEventId, state: SyncState.failed, error: 'timeout');
    // Lần 2 (retry): syncing rồi synced.
    await db.updateActivitySyncState(clientEventId, state: SyncState.syncing);
    await db.updateActivitySyncState(
      clientEventId,
      state: SyncState.synced,
      serverActivityId: 'server-real-id',
    );

    final rows = await db.listActivitiesByCropSeason('season-1');
    expect(rows, hasLength(1)); // vẫn đúng 1 hàng sau 4 lần đổi trạng thái
    expect(rows.first.clientEventId, clientEventId); // clientEventId không đổi
    expect(rows.first.serverActivityId, 'server-real-id');
    expect(rows.first.syncState, SyncState.synced);
  });
}

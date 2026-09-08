// ⚠️ CHƯA CHẠY LẦN NÀO. Chạy thật: cd app && flutter test test/activity_model_test.dart

import 'package:flutter_test/flutter_test.dart';
import 'package:agricarbon_app/models/activity.dart';

void main() {
  test('Activity round-trip qua local map giữ nguyên payload lồng nhau', () {
    final original = Activity(
      clientEventId: 'client-uuid-1',
      cropSeasonId: 'season-1',
      type: 'straw_management',
      occurredAt: DateTime(2026, 4, 10),
      payload: {
        'method': 'incorporated',
        'straw_mass_kg': 5000,
        'dry_matter_fraction': 0.85,
        'days_before_cultivation': 10,
      },
      note: 'ghi chú thử',
      createdAt: DateTime(2026, 4, 10, 9, 30),
    );

    final restored = Activity.fromLocalMap(original.toLocalMap());

    expect(restored.clientEventId, original.clientEventId);
    expect(restored.type, 'straw_management');
    expect(restored.payload['dry_matter_fraction'], 0.85);
    expect(restored.payload['days_before_cultivation'], 10);
    expect(restored.note, 'ghi chú thử');
    expect(restored.syncState, SyncState.pending);
  });

  test('clientEventId ổn định qua copyWith khi đổi sync state — khác serverActivityId', () {
    final a = Activity(
      clientEventId: 'stable-client-id',
      cropSeasonId: 's1',
      type: 'harvest',
      occurredAt: DateTime(2026, 5, 1),
      payload: {'yield_kg': 5200},
      createdAt: DateTime.now(),
    );
    expect(a.serverActivityId, isNull); // chưa đồng bộ -> chưa có id thật

    final synced = a.copyWith(syncState: SyncState.synced, serverActivityId: 'server-uuid-1');

    // clientEventId KHÔNG đổi qua trạng thái đồng bộ - đây là client_event_id gửi
    // lên server, đổi nó sẽ phá idempotency khi retry.
    expect(synced.clientEventId, 'stable-client-id');
    // serverActivityId là activities.id THẬT trên Supabase — một giá trị KHÁC,
    // chỉ có sau khi sync xong. Hai id này không bao giờ được lẫn vào nhau.
    expect(synced.serverActivityId, 'server-uuid-1');
    expect(synced.clientEventId, isNot(synced.serverActivityId));
  });
}

// ⚠️ CHƯA CHẠY LẦN NÀO. Chạy thật: cd app && flutter test test/activity_model_test.dart

import 'package:flutter_test/flutter_test.dart';
import 'package:agricarbon_app/models/activity.dart';

void main() {
  test('Activity round-trip qua local map giữ nguyên payload lồng nhau', () {
    final original = Activity(
      id: 'client-uuid-1',
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

    expect(restored.id, original.id);
    expect(restored.type, 'straw_management');
    expect(restored.payload['dry_matter_fraction'], 0.85);
    expect(restored.payload['days_before_cultivation'], 10);
    expect(restored.note, 'ghi chú thử');
    expect(restored.syncState, SyncState.pending);
  });

  test('client_event_id (id) ổn định qua copyWith khi đổi sync state', () {
    final a = Activity(
      id: 'stable-id',
      cropSeasonId: 's1',
      type: 'harvest',
      occurredAt: DateTime(2026, 5, 1),
      payload: {'yield_kg': 5200},
      createdAt: DateTime.now(),
    );
    final synced = a.copyWith(syncState: SyncState.synced, serverActivityId: 'server-1');

    // id KHÔNG đổi qua trạng thái đồng bộ - đây là client_event_id gửi lên server,
    // đổi nó sẽ phá idempotency khi retry.
    expect(synced.id, 'stable-id');
    expect(synced.serverActivityId, 'server-1');
  });
}

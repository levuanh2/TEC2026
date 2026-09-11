// Lưu / sửa / xoá Activity — offline, không mạng. sqflite_common_ffi.

import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'eeeeeeee-0000-0000-0000-000000000000';
const _cs = 'cs-client-1';

late Directory _tmp;
LocalDatabase _fresh() =>
    LocalDatabase(factory: databaseFactoryFfi, directoryOverride: _tmp.path);

/// Payload tối thiểu HỢP LỆ cho từng loại (khớp cột bảng chi tiết thật).
const _validPayloads = <String, Map<String, dynamic>>{
  'seeding': {
    'seed_kg': 45.0,
    'seeding_method': 'sa_lan',
    'variety_name': 'OM5451'
  },
  'fertilizer': {
    'fertilizer_name': 'Urê',
    'amount_kg': 50.0,
    'nitrogen_percent': 46.0,
    'total_cost_vnd': 600000.0,
  },
  'irrigation': {
    'method': 'awd',
    'water_volume_m3': 320.0,
    'duration_minutes': 90,
    'water_level_cm': 4.0,
    'pump_energy_kwh': 12.0,
  },
  'pesticide': {
    'product_name': 'Filia',
    'amount': 0.4,
    'unit': 'lít',
    'active_ingredient': 'tricyclazole',
  },
  'fuel': {
    'fuel_type': 'diesel',
    'amount_liter': 25.0,
    'equipment_name': 'Máy bơm'
  },
  'straw_management': {
    'method': 'incorporated',
    'straw_mass_kg': 3000.0,
    'dry_matter_fraction': 0.85,
    'days_before_cultivation': 20,
  },
  'harvest': {
    'yield_kg': 5200.0,
    'harvested_area_ha': 1.42,
    'moisture_percent': 24.0
  },
};

Activity _activity(String type, {String? clientEventId}) => Activity(
      clientEventId: clientEventId ?? 'evt-$type',
      cropSeasonId: _cs,
      type: type,
      occurredAt: DateTime(2026, 3, 1, 6, 30),
      payload: Map<String, dynamic>.from(_validPayloads[type]!),
      note: 'ghi chú $type',
      createdAt: DateTime(2026, 3, 1, 7),
    );

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_act_test');
  });
  tearDown(() async {
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  test('lưu + đọc lại nguyên vẹn cho CẢ 7 loại; restart vẫn còn', () async {
    final db = _fresh();
    await db.openForUser(_user);
    for (final type in kActivityTypes) {
      await db.saveActivity(_activity(type));
    }
    await db.close();

    final db2 = _fresh();
    await db2.openForUser(_user);
    final rows = await db2.listActivitiesByCropSeasonClientId(_cs);
    expect(rows, hasLength(7));
    for (final type in kActivityTypes) {
      final a = rows.firstWhere((r) => r.type == type);
      expect(a.syncState, SyncState.pending);
      expect(a.serverActivityId, isNull);
      expect(a.deletedLocally, isFalse);
      expect(a.payload, _validPayloads[type]);
      expect(a.note, 'ghi chú $type');
    }
    expect(await db2.countPendingActivities(), 7);
    await db2.close();
  });

  test('sửa: giữ nguyên clientEventId, đổi payload, quay về pending', () async {
    final db = _fresh();
    await db.openForUser(_user);
    // Bản ghi đã "đồng bộ".
    final synced = _activity('fertilizer', clientEventId: 'keep-me').copyWith(
      syncState: SyncState.synced,
      serverActivityId: 'srv-1',
    );
    await db.saveActivity(synced);

    final loaded = await db.getActivity('keep-me');
    final edited = loaded!.editedWith(
      payload: {...loaded.payload, 'amount_kg': 75.0},
      note: 'sửa lại',
    );
    await db.saveActivity(edited);

    final after = await db.getActivity('keep-me');
    expect(after!.clientEventId, 'keep-me'); // KHÔNG đổi
    expect(after.serverActivityId, 'srv-1'); // giữ liên kết server
    expect(after.type, 'fertilizer'); // type bất biến
    expect(after.payload['amount_kg'], 75.0);
    expect(after.syncState, SyncState.pending); // sửa -> chưa gửi
    expect(after.note, 'sửa lại');
    await db.close();
  });

  test('xoá bản ghi CHƯA đồng bộ -> xoá hẳn local', () async {
    final db = _fresh();
    await db.openForUser(_user);
    await db.saveActivity(_activity('seeding', clientEventId: 'e1'));
    await db.hardDeleteActivity('e1');
    expect(await db.getActivity('e1'), isNull);
    expect(await db.listActivitiesByCropSeasonClientId(_cs), isEmpty);
    await db.close();
  });

  test('xoá bản ghi ĐÃ đồng bộ -> tombstone (không mất row)', () async {
    final db = _fresh();
    await db.openForUser(_user);
    await db.saveActivity(_activity('harvest', clientEventId: 'e2').copyWith(
      syncState: SyncState.synced,
      serverActivityId: 'srv-2',
    ));

    await db.tombstoneActivity('e2');
    final t = await db.getActivity('e2');
    expect(t, isNotNull, reason: 'row vẫn còn để đẩy deleted_at');
    expect(t!.deletedLocally, isTrue);
    expect(t.syncState, SyncState.pending);
    expect(t.serverActivityId, 'srv-2');

    // Ẩn khỏi danh sách thường, nhưng vẫn nằm trong hàng đợi đồng bộ.
    expect(await db.listActivitiesByCropSeasonClientId(_cs), isEmpty);
    expect(
      await db.listActivitiesByCropSeasonClientId(_cs, includeDeleted: true),
      hasLength(1),
    );
    expect((await db.listPendingActivities()).where((a) => a.deletedLocally),
        hasLength(1));

    // Server xác nhận -> dọn hẳn.
    await db.hardDeleteActivity('e2');
    expect(await db.getActivity('e2'), isNull);
    await db.close();
  });

  test('kẹt "syncing" sau crash -> về pending khi mở lại (gồm tombstone)',
      () async {
    final db = _fresh();
    await db.openForUser(_user);
    await db.saveActivity(_activity('fuel', clientEventId: 'e3'));
    await db.updateActivitySyncState('e3', state: SyncState.syncing);
    await db.close();

    final db2 = _fresh();
    await db2.openForUser(_user);
    expect((await db2.getActivity('e3'))!.syncState, SyncState.pending);
    await db2.close();
  });

  test(
      'migration: DB v1 có activity cũ -> lên v4 thêm cột deleted_locally, '
      'giữ dữ liệu', () async {
    final legacy = _fresh();
    await legacy.debugOpenAtV1(_user);
    await legacy.debugInsertRaw('activities', {
      'id': 'old-act',
      'crop_season_id': _cs,
      'type': 'seeding',
      'occurred_at': DateTime(2026, 2, 1).toIso8601String(),
      'payload_json': '{"seed_kg":40}',
      'sync_state': 'pending',
      'created_at': DateTime(2026, 2, 1).toIso8601String(),
    });
    await legacy.close();

    final upgraded = _fresh();
    await upgraded.openForUser(_user); // chạy onUpgrade v1->v4
    final a = await upgraded.getActivity('old-act');
    expect(a, isNotNull);
    expect(a!.deletedLocally, isFalse);
    expect(a.payload['seed_kg'], 40);
    // Cột mới dùng được.
    await upgraded.saveActivity(a.copyWith(
      syncState: SyncState.synced,
      serverActivityId: 'srv-old',
    ));
    await upgraded.tombstoneActivity('old-act');
    expect((await upgraded.getActivity('old-act'))!.deletedLocally, isTrue);
    await upgraded.close();
  });
}

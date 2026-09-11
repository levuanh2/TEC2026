import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/services/device_service.dart';
import 'package:agricarbon_app/services/sync_errors.dart';
import 'package:agricarbon_app/services/sync_gateway.dart';
import 'package:agricarbon_app/services/sync_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:supabase_flutter/supabase_flutter.dart' show PostgrestException;

const _user = 'eeeeeeee-0000-0000-0000-000000000000';

/// Gateway giả — mô phỏng ĐỘC LẬP từng tín hiệu server (số dòng UPDATE tác động,
/// exception, số lần gọi), KHÔNG chạm mạng và KHÔNG dùng SELECT visibility làm
/// bằng chứng xoá.
class _FakeGateway implements SyncGateway {
  _FakeGateway();

  final activityUpserts = <Map<String, dynamic>>[];
  final detailUpserts = <({String table, Map<String, dynamic> row})>[];
  final softDeleteCalls = <String>[];

  /// Số dòng lệnh `UPDATE ... SET deleted_at` tác động (từ `Content-Range`).
  /// `1` = server nhận `deleted_at` cho đúng row; `0` = RLS `USING` chặn / row
  /// không tồn tại; `null` = không đọc được count.
  int? softDeleteAffectedRows = 1;
  Object? softDeleteThrows;
  Object? upsertThrows;

  @override
  Future<String> upsertPlot(Map<String, dynamic> row) async => 'srv-plot';

  @override
  Future<String> upsertCropSeason(Map<String, dynamic> row) async => 'srv-cs';

  @override
  Future<String> ensureDefaultBatch(String cropSeasonServerId) async => 'batch';

  @override
  Future<String> upsertActivity(Map<String, dynamic> row) async {
    activityUpserts.add(row);
    final t = upsertThrows;
    if (t != null) throw t;
    return 'srv-act-${row['client_event_id']}';
  }

  @override
  Future<void> upsertActivityDetail(
      String table, Map<String, dynamic> row) async {
    detailUpserts.add((table: table, row: row));
  }

  @override
  Future<int?> softDeleteActivity(
      String serverActivityId, DateTime deletedAt) async {
    softDeleteCalls.add(serverActivityId);
    final t = softDeleteThrows;
    if (t != null) throw t;
    return softDeleteAffectedRows;
  }

  @override
  Future<String?> currentCooperativeId() async => 'org';

  @override
  Future<List<Map<String, dynamic>>> fetchFarms() async => [];
  @override
  Future<List<Map<String, dynamic>>> fetchPlots() async => [];
  @override
  Future<List<Map<String, dynamic>>> fetchCropSeasons() async => [];
}

/// Test luồng `upsertActivity` thật của [SupabaseSyncGateway] (điều phối race
/// 23505) mà KHÔNG cần `SupabaseClient` — override 3 seam I/O.
class _RaceGateway extends SupabaseSyncGateway {
  _RaceGateway({required this.findResults, required this.insert})
      : super.protectedForTest();

  final List<String?> findResults; // trả lần lượt cho mỗi findActivityIdByKey
  final String Function() insert; // hành vi insertActivityReturningId
  int findCalls = 0;
  int insertCalls = 0;
  final updatedIds = <String>[];

  @override
  Future<String?> findActivityIdByKey(String? d, String? c) async {
    final i = findCalls++;
    return i < findResults.length ? findResults[i] : null;
  }

  @override
  Future<String> insertActivityReturningId(Map<String, dynamic> row) async {
    insertCalls++;
    return insert();
  }

  @override
  Future<void> updateActivityById(String id, Map<String, dynamic> row) async {
    updatedIds.add(id);
  }
}

late Directory _tmp;
late LocalDatabase _db;
late _FakeGateway _gw;
late SyncService _sync;

Future<void> _seedSyncedSeason() async {
  final now = DateTime(2026, 3);
  await _db.upsertPlot(Plot(
    clientId: 'p1',
    serverId: 'srv-p1',
    farmId: 'f1',
    plotCode: 'P',
    name: 'P',
    areaHa: 1,
    syncState: SyncState.synced,
    createdAt: now,
    updatedAt: now,
  ));
  await _db.upsertCropSeason(CropSeason(
    clientId: 'cs1',
    serverId: 'srv-cs1',
    plotClientId: 'p1',
    seasonCode: 'S',
    syncState: SyncState.synced,
    createdAt: now,
    updatedAt: now,
  ));
}

Activity _act({
  required String id,
  String type = 'fertilizer',
  Map<String, dynamic> payload = const {
    'fertilizer_name': 'Ure',
    'amount_kg': 50.0,
  },
  String? note,
  SyncState state = SyncState.pending,
  String? serverId,
  bool deletedLocally = false,
}) =>
    Activity(
      clientEventId: id,
      cropSeasonId: 'cs1',
      type: type,
      occurredAt: DateTime(2026, 3, 2, 7),
      payload: payload,
      note: note,
      syncState: state,
      createdAt: DateTime(2026, 3, 2, 7),
      serverActivityId: serverId,
      deletedLocally: deletedLocally,
    );

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_sync_test');
    _db = LocalDatabase(
        factory: databaseFactoryFfi, directoryOverride: _tmp.path);
    await _db.openForUser(_user);
    _gw = _FakeGateway();
    _sync = SyncService(_gw, _db, DeviceService.fixed('dev-1'));
    await _seedSyncedSeason();
  });
  tearDown(() async {
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  group(
      'xoá Activity đã sync — chỉ hard-delete local khi UPDATE tác động ĐÚNG 1 '
      'row (không dựa SELECT visibility) (#4)', () {
    Future<void> seedSyncedTombstone() async {
      await _db.saveActivity(
          _act(id: 'a1', state: SyncState.synced, serverId: 'srv-act-a1'));
      await _db.tombstoneActivity('a1');
    }

    Future<Activity?> row() => _db.getActivity('a1');

    // 1
    test(
        'affected == 1 (server ghi deleted_at cho đúng row) -> hard-delete local',
        () async {
      await seedSyncedTombstone();
      _gw.softDeleteAffectedRows = 1;
      final s = await _sync.syncAll();
      expect(s.activitiesDeleted, 1);
      expect(await row(), isNull);
      expect(_gw.softDeleteCalls, ['srv-act-a1']);
      expect(_gw.activityUpserts, isEmpty); // KHÔNG bao giờ upsert lại
    });

    // 2 + 8
    test(
        'quyền bị thu hồi trước update, UPDATE tác động 0 row (không ném) -> '
        'GIỮ tombstone notConfirmed', () async {
      await seedSyncedTombstone();
      _gw.softDeleteAffectedRows = 0; // RLS `using` lọc — update không đổi gì
      final s = await _sync.syncAll();
      expect(s.activitiesDeleted, 0);
      final r = await row();
      expect(r, isNotNull);
      expect(r!.deletedLocally, isTrue);
      expect(r.syncState, SyncState.failed);
      expect(r.syncError, SyncErrorKind.notConfirmed.name);
    });

    // 3
    test('row không tồn tại (affected 0) -> GIỮ tombstone', () async {
      await seedSyncedTombstone();
      _gw.softDeleteAffectedRows = 0;
      await _sync.syncAll();
      expect(await row(), isNotNull);
      expect((await row())!.syncState, SyncState.failed);
    });

    // 4
    test(
        'đã xoá ở lượt trước nhưng KHÔNG có ack (affected 0) -> GIỮ tombstone, '
        'KHÔNG đoán', () async {
      await seedSyncedTombstone();
      _gw.softDeleteAffectedRows = 0;
      await _sync.syncAll();
      final r = await row();
      expect(r, isNotNull);
      expect(r!.syncError, SyncErrorKind.notConfirmed.name);
    });

    // 5
    test('network error -> GIỮ tombstone', () async {
      await seedSyncedTombstone();
      _gw.softDeleteThrows = Exception('SocketException: Failed host lookup');
      await _sync.syncAll();
      final r = await row();
      expect(r, isNotNull);
      expect(r!.syncState, SyncState.failed);
      expect(r.syncError, SyncErrorKind.network.name);
    });

    // 6
    test('auth/session expired -> GIỮ tombstone', () async {
      await seedSyncedTombstone();
      _gw.softDeleteThrows =
          const PostgrestException(message: 'JWT expired', code: '401');
      await _sync.syncAll();
      final r = await row();
      expect(r, isNotNull);
      expect(r!.syncState, SyncState.failed);
      expect(r.syncError, SyncErrorKind.auth.name);
    });

    // 7
    test('PostgREST/RLS exception (42501) -> GIỮ tombstone', () async {
      await seedSyncedTombstone();
      _gw.softDeleteThrows =
          const PostgrestException(message: 'permission denied', code: '42501');
      await _sync.syncAll();
      final r = await row();
      expect(r, isNotNull);
      expect(r!.syncState, SyncState.failed);
      expect(r.syncError, SyncErrorKind.rlsDenied.name);
    });

    // 9
    test(
        'retry >= 3 lần với affected 0/null -> KHÔNG mất tombstone, KHÔNG upsert',
        () async {
      await seedSyncedTombstone();
      _gw.softDeleteAffectedRows = 0;
      for (var i = 0; i < 3; i++) {
        final s = await _sync.syncAll();
        expect(s.activitiesDeleted, 0, reason: 'lượt $i');
        expect(await row(), isNotNull, reason: 'lượt $i — KHÔNG mất hàng');
        expect((await row())!.deletedLocally, isTrue);
      }
      // count == null cũng phải giữ hàng.
      _gw.softDeleteAffectedRows = null;
      await _sync.syncAll();
      expect(await row(), isNotNull);
      expect(_gw.activityUpserts, isEmpty);
      expect(_gw.softDeleteCalls, hasLength(4));
    });

    // 10
    test('serverId == null -> hard-delete local, KHÔNG gọi server', () async {
      await _db.saveActivity(_act(id: 'a2', state: SyncState.pending));
      await _db.tombstoneActivity('a2');
      final s = await _sync.syncAll();
      expect(s.activitiesDeleted, 1);
      expect(await _db.getActivity('a2'), isNull);
      expect(_gw.softDeleteCalls, isEmpty);
    });

    // 11
    test('hai syncAll() đồng thời -> single-flight, tombstone xử lý đúng 1 lần',
        () async {
      await seedSyncedTombstone();
      _gw.softDeleteAffectedRows = 1;
      final f1 = _sync.syncAll();
      final f2 = _sync.syncAll();
      final results = await Future.wait([f1, f2]);
      expect(identical(results[0], results[1]), isTrue); // cùng một lượt
      expect(_gw.softDeleteCalls, ['srv-act-a1']); // KHÔNG xử lý 2 lần
      expect(results[0].activitiesDeleted, 1);
      expect(await row(), isNull);
    });
  });

  group('SupabaseSyncGateway.upsertActivity — race unique 23505 (#3)', () {
    test(
        'SELECT đầu rỗng -> INSERT nhận 23505 -> SELECT lần 2 thấy row '
        '-> dùng đúng server id, KHÔNG ném', () async {
      final gw = _RaceGateway(
        findResults: [null, 'srv-raced'], // lần 1 rỗng, lần 2 thấy
        insert: () => throw const PostgrestException(
            message: 'duplicate key', code: '23505'),
      );
      final id = await gw.upsertActivity(
          {'device_id': 'd', 'client_event_id': 'e', 'activity_type': 'fuel'});
      expect(id, 'srv-raced');
      expect(gw.updatedIds, ['srv-raced']); // detail sẽ dùng id này
      expect(gw.findCalls, 2);
      expect(gw.insertCalls, 1);
    });

    test('23505 nhưng SELECT lần 2 VẪN rỗng -> ném (không giả synced)',
        () async {
      final gw = _RaceGateway(
        findResults: [null, null],
        insert: () => throw const PostgrestException(
            message: 'duplicate key', code: '23505'),
      );
      await expectLater(
        gw.upsertActivity({'device_id': 'd', 'client_event_id': 'e'}),
        throwsA(
            isA<PostgrestException>().having((e) => e.code, 'code', '23505')),
      );
    });

    test('lỗi INSERT khác 23505 -> KHÔNG bị nuốt, ném nguyên', () async {
      final gw = _RaceGateway(
        findResults: [null],
        insert: () => throw const PostgrestException(
            message: 'permission denied', code: '42501'),
      );
      await expectLater(
        gw.upsertActivity({'device_id': 'd', 'client_event_id': 'e'}),
        throwsA(
            isA<PostgrestException>().having((e) => e.code, 'code', '42501')),
      );
      expect(gw.findCalls, 1); // KHÔNG đọc lại vì không phải 23505
    });

    test('SELECT đầu THẤY row -> chỉ UPDATE, KHÔNG INSERT', () async {
      final gw = _RaceGateway(
          findResults: ['srv-existing'], insert: () => 'srv-new-should-not');
      final id =
          await gw.upsertActivity({'device_id': 'd', 'client_event_id': 'e'});
      expect(id, 'srv-existing');
      expect(gw.insertCalls, 0);
      expect(gw.updatedIds, ['srv-existing']);
    });
  });

  group('edit xoá field optional -> gửi null lên server (#5)', () {
    test('xoá note -> parent activity gửi note: null', () async {
      // Đã sync với note; sửa xoá note -> pending, payload giữ.
      await _db.saveActivity(_act(
        id: 'e1',
        note: null, // đã xoá
        state: SyncState.pending,
        serverId: 'srv-act-e1',
      ));
      await _sync.syncAll();
      expect(_gw.activityUpserts, hasLength(1));
      expect(_gw.activityUpserts.single.containsKey('note'), isTrue);
      expect(_gw.activityUpserts.single['note'], isNull);
    });

    test('detail row đầy đủ MỌI cột — cột trống = null', () async {
      await _db.saveActivity(_act(
        id: 'e2',
        type: 'fertilizer',
        payload: const {'fertilizer_name': 'Ure', 'amount_kg': 50.0},
        state: SyncState.pending,
      ));
      await _sync.syncAll();
      final d = _gw.detailUpserts.single;
      expect(d.table, 'fertilizer_applications');
      // Bắt buộc + tuỳ chọn: đủ hết, cột không nhập = null.
      expect(d.row['fertilizer_name'], 'Ure');
      expect(d.row['amount_kg'], 50.0);
      expect(d.row.containsKey('nitrogen_percent'), isTrue);
      expect(d.row['nitrogen_percent'], isNull);
      expect(d.row.containsKey('total_cost_vnd'), isTrue);
      expect(d.row['total_cost_vnd'], isNull);
      expect(d.row['activity_id'], 'srv-act-e2');
    });

    test('KHÔNG trộn field giữa các bảng chi tiết', () async {
      await _db.saveActivity(_act(
        id: 'e3',
        type: 'irrigation',
        payload: const {'method': 'awd'},
        state: SyncState.pending,
      ));
      await _sync.syncAll();
      final row = _gw.detailUpserts.single.row;
      expect(_gw.detailUpserts.single.table, 'irrigation_events');
      // Không có cột của fertilizer.
      expect(row.containsKey('fertilizer_name'), isFalse);
      expect(row.containsKey('amount_kg'), isFalse);
      // Có cột của irrigation.
      expect(row.containsKey('water_volume_m3'), isTrue);
      expect(row.containsKey('pump_energy_kwh'), isTrue);
      expect(row['method'], 'awd');
    });

    test('retry edit -> upsert cùng client_event_id, KHÔNG tạo bản ghi trùng',
        () async {
      await _db.saveActivity(_act(
        id: 'e4',
        state: SyncState.pending,
        serverId: 'srv-act-e4',
      ));
      await _sync.syncAll();
      // Giả lập sửa lại -> pending -> sync lần 2.
      await _db.updateActivitySyncState('e4', state: SyncState.pending);
      await _sync.syncAll();
      expect(_gw.activityUpserts, hasLength(2));
      expect(_gw.activityUpserts.every((r) => r['client_event_id'] == 'e4'),
          isTrue);
      // Local vẫn 1 hàng.
      final rows = await _db.listActivitiesByCropSeasonClientId('cs1');
      expect(rows, hasLength(1));
    });
  });
}

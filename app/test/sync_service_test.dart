import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/methodology_enums.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/services/device_service.dart';
import 'package:agricarbon_app/services/sync_errors.dart';
import 'package:agricarbon_app/services/sync_gateway.dart';
import 'package:agricarbon_app/services/sync_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:supabase_flutter/supabase_flutter.dart' show PostgrestException;

const _user = 'eeeeeeee-0000-0000-0000-000000000000';

/// Gateway giả — mô phỏng ĐỘC LẬP từng tín hiệu server (trả về / exception /
/// số lần gọi), KHÔNG chạm mạng và KHÔNG dùng SELECT visibility làm bằng chứng
/// xoá.
class _FakeGateway implements SyncGateway {
  _FakeGateway();

  final activityUpserts = <Map<String, dynamic>>[];
  final detailUpserts = <({String table, Map<String, dynamic> row})>[];
  final softDeleteCalls = <String>[];

  /// `auth.uid()` của phiên giả. `null` = CHƯA đăng nhập.
  String? sessionUserId = _user;

  Object? softDeleteThrows;
  Object? upsertThrows;

  @override
  Future<String> upsertPlot(Map<String, dynamic> row) async => 'srv-plot';

  final seasonUpserts = <Map<String, dynamic>>[];
  Object? seasonUpsertThrows;

  @override
  Future<String> upsertCropSeason(Map<String, dynamic> row) async {
    seasonUpserts.add(row);
    final t = seasonUpsertThrows;
    if (t != null) throw t;
    return 'srv-cs1';
  }

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
  Future<void> softDeleteActivity(String serverActivityId) async {
    softDeleteCalls.add(serverActivityId);
    final t = softDeleteThrows;
    if (t != null) throw t;
  }

  @override
  String? currentUserId() => sessionUserId;

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
      'xoá Activity đã sync — RPC `soft_delete_activity` là nguồn xác nhận '
      '(không dựa SELECT visibility, không dựa số dòng UPDATE) (#4)', () {
    Future<void> seedSyncedTombstone() async {
      await _db.saveActivity(
          _act(id: 'a1', state: SyncState.synced, serverId: 'srv-act-a1'));
      await _db.tombstoneActivity('a1');
    }

    Future<Activity?> row() => _db.getActivity('a1');

    // 1
    test('RPC trả về bình thường -> hard-delete local, gửi ĐÚNG server id',
        () async {
      await seedSyncedTombstone();
      final s = await _sync.syncAll();
      expect(s.activitiesDeleted, 1);
      expect(await row(), isNull);
      expect(_gw.softDeleteCalls, ['srv-act-a1']);
      expect(_gw.activityUpserts, isEmpty); // KHÔNG bao giờ upsert lại
    });

    // 2 — hợp đồng idempotent: server đã xoá mềm ở lượt trước vẫn trả về
    // bình thường, nên lượt sau dọn được hàng local thay vì kẹt mãi.
    test('lượt thứ hai trên CÙNG tombstone -> idempotent, không lỗi, không '
        'nhân đôi', () async {
      await seedSyncedTombstone();
      await _sync.syncAll();
      expect(await row(), isNull);
      final s2 = await _sync.syncAll(); // hàng đợi đã rỗng
      expect(s2.activitiesDeleted, 0);
      expect(s2.hasErrors, isFalse);
      expect(_gw.softDeleteCalls, ['srv-act-a1']); // gọi đúng 1 lần
    });

    // 3 — RLS từ chối: KHÁC chủ / khác phạm vi. Đây là lỗi VĨNH VIỄN.
    test('RPC ném 42501 (không phải chủ / ngoài phạm vi) -> GIỮ tombstone, '
        'đánh dấu rlsDenied', () async {
      await seedSyncedTombstone();
      _gw.softDeleteThrows =
          const PostgrestException(message: 'permission denied', code: '42501');
      final s = await _sync.syncAll();
      expect(s.activitiesDeleted, 0);
      final r = await row();
      expect(r, isNotNull);
      expect(r!.deletedLocally, isTrue);
      expect(r.syncState, SyncState.failed);
      expect(r.syncError, SyncErrorKind.rlsDenied.name);
      expect(s.hasPermissionError, isTrue);
    });

    // 4 — và KHÔNG được thử lại vô hạn (P1-2 giữ nguyên qua đường RPC).
    test('42501 là lỗi VĨNH VIỄN -> hàng đợi thôi tự chọn lại', () async {
      await seedSyncedTombstone();
      _gw.softDeleteThrows =
          const PostgrestException(message: 'permission denied', code: '42501');
      await _sync.syncAll();
      expect(_gw.softDeleteCalls, hasLength(1));
      await _sync.syncAll(); // lượt sau KHÔNG được chạm server nữa
      expect(_gw.softDeleteCalls, hasLength(1));
      expect(await row(), isNotNull); // vẫn giữ hàng, không mất dữ liệu
    });

    // 5
    test('network error -> GIỮ tombstone, thử lại được', () async {
      await seedSyncedTombstone();
      _gw.softDeleteThrows = Exception('SocketException: Failed host lookup');
      await _sync.syncAll();
      final r = await row();
      expect(r, isNotNull);
      expect(r!.syncState, SyncState.failed);
      expect(r.syncError, SyncErrorKind.network.name);

      // mạng trở lại -> lượt sau xoá được, không mất hàng ở giữa
      _gw.softDeleteThrows = null;
      final s = await _sync.syncAll();
      expect(s.activitiesDeleted, 1);
      expect(await row(), isNull);
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
    test('serverId == null -> hard-delete local, KHÔNG gọi server', () async {
      await _db.saveActivity(_act(id: 'a2', state: SyncState.pending));
      await _db.tombstoneActivity('a2');
      final s = await _sync.syncAll();
      expect(s.activitiesDeleted, 1);
      expect(await _db.getActivity('a2'), isNull);
      expect(_gw.softDeleteCalls, isEmpty);
    });

    // 8
    test('hai syncAll() đồng thời -> single-flight, tombstone xử lý đúng 1 lần',
        () async {
      await seedSyncedTombstone();
      final f1 = _sync.syncAll();
      final f2 = _sync.syncAll();
      final results = await Future.wait([f1, f2]);
      expect(identical(results[0], results[1]), isTrue); // cùng một lượt
      expect(_gw.softDeleteCalls, ['srv-act-a1']); // KHÔNG xử lý 2 lần
      expect(results[0].activitiesDeleted, 1);
      expect(await row(), isNull);
    });
  });

  group('recorded_by — danh tính người ghi lấy từ phiên đăng nhập (P1-4)', () {
    test('create gửi recorded_by = auth.uid() của phiên hiện tại', () async {
      await _db.saveActivity(_act(id: 'r1', state: SyncState.pending));
      await _sync.syncAll();
      expect(_gw.activityUpserts, hasLength(1));
      expect(_gw.activityUpserts.single['recorded_by'], _user);
    });

    test('edit một bản ĐÃ sync cũng gửi lại recorded_by (không rơi về null)',
        () async {
      await _db.saveActivity(_act(
        id: 'r2',
        state: SyncState.pending,
        serverId: 'srv-act-r2',
        note: 'đã sửa',
      ));
      await _sync.syncAll();
      expect(_gw.activityUpserts.single['recorded_by'], _user);
    });

    test('đổi tài khoản -> recorded_by đi theo phiên MỚI, không phải hằng số',
        () async {
      _gw.sessionUserId = 'ffffffff-1111-2222-3333-444444444444';
      await _db.saveActivity(_act(id: 'r3', state: SyncState.pending));
      await _sync.syncAll();
      expect(_gw.activityUpserts.single['recorded_by'],
          'ffffffff-1111-2222-3333-444444444444');
    });

    test('KHÔNG có phiên đăng nhập -> KHÔNG ghi, KHÔNG gửi recorded_by null; '
        'hỏng thật với lỗi auth và giữ nguyên dữ liệu trên máy', () async {
      _gw.sessionUserId = null;
      await _db.saveActivity(_act(id: 'r4', state: SyncState.pending));
      final s = await _sync.syncAll();
      expect(_gw.activityUpserts, isEmpty);
      expect(_gw.detailUpserts, isEmpty);
      expect(s.activitiesSynced, 0);
      expect(s.hasErrors, isTrue);
      final r = await _db.getActivity('r4');
      expect(r, isNotNull);
      expect(r!.syncState, SyncState.failed);
      expect(r.syncError, SyncErrorKind.auth.name);
    });

    test('mất phiên KHÔNG chặn tombstone đã có server id (xoá vẫn do RLS quyết)',
        () async {
      await _db.saveActivity(
          _act(id: 'r5', state: SyncState.synced, serverId: 'srv-act-r5'));
      await _db.tombstoneActivity('r5');
      _gw.sessionUserId = null;
      await _sync.syncAll();
      expect(_gw.softDeleteCalls, ['srv-act-r5']);
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

  group('Carbon parity — methodology đi theo hàng đợi sẵn có, không mất khi offline',
      () {
    Future<void> editOffline({int? days, IpccWaterRegime? ipcc}) async {
      final s = (await _db.getCropSeasonByClientId('cs1'))!;
      await _db.upsertCropSeason(s.copyWith(
        cultivationDays: days,
        ipccWaterRegime: ipcc,
        syncState: SyncState.pending,
        updatedAt: DateTime.now(),
      ));
    }

    test('sửa offline -> lưu trên máy (pending) -> 1 upsert khi có mạng -> đồng bộ lại '
        'không gửi thêm', () async {
      await editOffline(days: 100, ipcc: IpccWaterRegime.irrigatedMultipleDrainage);
      final pending = (await _db.getCropSeasonByClientId('cs1'))!;
      expect(pending.syncState, SyncState.pending);
      expect(pending.cultivationDays, 100);

      await _sync.syncAll();
      expect(_gw.seasonUpserts, hasLength(1));
      final row = _gw.seasonUpserts.single;
      expect(row['cultivation_days'], 100);
      expect(row['ipcc_water_regime'], 'irrigated_multiple_drainage');
      // Chưa biết thì gửi null TƯỜNG MINH (không bỏ key, không đoán).
      expect(row.containsKey('pre_season_water_regime'), isTrue);
      expect(row['pre_season_water_regime'], isNull);
      expect((await _db.getCropSeasonByClientId('cs1'))!.syncState, SyncState.synced);

      await _sync.syncAll(); // chạy lại: không có gì chờ -> không gửi trùng
      expect(_gw.seasonUpserts, hasLength(1));
    });

    test('lượt kéo từ server KHÔNG ghi đè thay đổi chưa gửi', () async {
      await editOffline(days: 100);
      await _db.mergeServerCropSeason({
        'id': 'srv-cs1', 'plot_id': 'srv-p1', 'season_code': 'S',
        'crop_type': 'rice', 'status': 'active', 'cultivation_days': null,
      });
      final kept = (await _db.getCropSeasonByClientId('cs1'))!;
      expect(kept.cultivationDays, 100);
      expect(kept.syncState, SyncState.pending);
    });

    test('vụ đã đồng bộ, không có thay đổi chờ -> lượt kéo cập nhật từ server', () async {
      await _db.mergeServerCropSeason({
        'id': 'srv-cs1', 'plot_id': 'srv-p1', 'season_code': 'S',
        'crop_type': 'rice', 'status': 'active', 'cultivation_days': 95,
        'ipcc_water_regime': 'irrigated_single_drainage',
      });
      final s = (await _db.getCropSeasonByClientId('cs1'))!;
      expect(s.cultivationDays, 95);
      expect(s.ipccWaterRegime, IpccWaterRegime.irrigatedSingleDrainage);
    });

    test('rơm: false / 0 / null giữ nguyên tới bảng chi tiết', () async {
      await _db.saveActivity(_act(id: 'straw-1', type: 'straw_management', payload: const {
        'method': 'composted',
        'straw_mass_kg': 0.0,
        'days_before_cultivation': 0,
        'returned_to_field': false,
      }));
      final local = await _db.getActivity('straw-1');
      expect(local!.payload['returned_to_field'], isFalse); // không thành null
      expect(local.payload['days_before_cultivation'], 0);

      await _sync.syncAll();
      final detail = _gw.detailUpserts.singleWhere((d) => d.table == 'straw_management_events').row;
      expect(detail['returned_to_field'], isFalse);
      expect(detail['days_before_cultivation'], 0);
      expect(detail['straw_mass_kg'], 0.0);
      // Cột không nhập gửi null tường minh (xoá giá trị cũ khi sửa).
      expect(detail.containsKey('dry_matter_fraction'), isTrue);
      expect(detail['dry_matter_fraction'], isNull);
      // Khoá idempotent của activity không đổi.
      final up = _gw.activityUpserts.single;
      expect(up['device_id'], 'dev-1');
      expect(up['client_event_id'], 'straw-1');
    });
  });

  group('vụ đã kết thúc trên hệ thống (P1 lifecycle, SQLSTATE 55000)', () {
    const closed = PostgrestException(
        message: 'crop_season_not_open: the crop season of this activity is not active',
        code: '55000');

    test('công việc chờ gửi bị từ chối -> failed/seasonClosed, KHÔNG mất, KHÔNG thử lại mãi',
        () async {
      await _db.saveActivity(_act(id: 'late-1'));
      _gw.upsertThrows = closed;
      final first = await _sync.syncAll();
      expect(first.failures.single.kind, SyncErrorKind.seasonClosed);
      final kept = await _db.getActivity('late-1');
      expect(kept, isNotNull, reason: 'mutation not silently dropped');
      expect(kept!.syncState, SyncState.failed);
      expect(_gw.activityUpserts, hasLength(1));

      // Lượt sau KHÔNG chọn lại (lỗi vĩnh viễn) -> không bão request.
      await _sync.syncAll();
      await _sync.syncAll();
      expect(_gw.activityUpserts, hasLength(1));
    });

    test('xoá một bản ghi của vụ đã kết thúc -> giữ tombstone, failed/seasonClosed',
        () async {
      await _db.saveActivity(
          _act(id: 'old-1', state: SyncState.synced, serverId: 'srv-old-1'));
      await _db.tombstoneActivity('old-1');
      _gw.softDeleteThrows = closed;
      final s = await _sync.syncAll();
      expect(s.failures.single.kind, SyncErrorKind.seasonClosed);
      expect(await _db.getActivity('old-1'), isNotNull);
    });

    test('bản vụ trên máy muốn mở lại vụ đã kết thúc -> máy chủ thắng, không thử lại',
        () async {
      final season = (await _db.getCropSeasonByClientId('cs1'))!;
      await _db.upsertCropSeason(season.copyWith(
          syncState: SyncState.pending, updatedAt: DateTime(2026, 4)));
      _gw.seasonUpsertThrows = const PostgrestException(
          message: 'illegal_crop_season_transition: harvested -> active is not allowed',
          code: '55000');
      final s = await _sync.syncAll();
      expect(s.failures.single.kind, SyncErrorKind.seasonClosed);
      final after = (await _db.getCropSeasonByClientId('cs1'))!;
      expect(after.syncState, SyncState.synced,
          reason: 'lượt kéo kế tiếp nhận trạng thái thật từ máy chủ');
      await _sync.syncAll();
      expect(_gw.seasonUpserts, hasLength(1));
    });

    test('vụ planned (bản app cũ) có công việc chờ -> được đẩy lên là active TRƯỚC công việc',
        () async {
      final season = (await _db.getCropSeasonByClientId('cs1'))!;
      await _db.upsertCropSeason(season.copyWith(status: CropSeasonStatus.planned));
      await _db.saveActivity(_act(id: 'first-1'));
      await _sync.syncAll();
      expect(_gw.seasonUpserts.single['status'], 'active');
      expect(_gw.activityUpserts, hasLength(1));
      expect((await _db.getCropSeasonByClientId('cs1'))!.status, CropSeasonStatus.active);
    });

    test('vụ planned KHÔNG có công việc chờ -> giữ nguyên, không gửi', () async {
      final season = (await _db.getCropSeasonByClientId('cs1'))!;
      await _db.upsertCropSeason(season.copyWith(status: CropSeasonStatus.planned));
      await _sync.syncAll();
      expect(_gw.seasonUpserts, isEmpty);
      expect((await _db.getCropSeasonByClientId('cs1'))!.status, CropSeasonStatus.planned);
    });

    test('chỉ vụ đang canh tác (hoặc planned cũ) nhận công việc trên máy', () {
      expect(seasonAcceptsActivities(CropSeasonStatus.active), isTrue);
      expect(seasonAcceptsActivities(CropSeasonStatus.planned), isTrue);
      expect(seasonAcceptsActivities(CropSeasonStatus.harvested), isFalse);
      expect(seasonAcceptsActivities(CropSeasonStatus.closed), isFalse);
      expect(seasonAcceptsActivities(CropSeasonStatus.cancelled), isFalse);
    });
  });
}

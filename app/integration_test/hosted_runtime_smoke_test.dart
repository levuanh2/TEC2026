// Nghiệm thu RUNTIME THẬT trên thiết bị Android, đánh vào Supabase hosted.
//
// KHÔNG phải unit test — đây là công cụ QA chạy tay. Nó chạy TRỌN luồng offline
// trong MỘT lần chạy vì `flutter test integration_test/` gỡ app sau mỗi lần
// chạy (sandbox bị xoá), nên không thể chia pha theo tiến trình.
//
// Mạng được BẬT/TẮT TỪ HOST bằng `adb shell svc wifi|data`; test không tự đổi
// được (app không có quyền). Test chỉ DÒ trạng thái mạng thật rồi đi tiếp.
//
//   flutter test integration_test/hosted_runtime_smoke_test.dart -d emulator-5554 \
//     --dart-define SUPABASE_URL=... --dart-define SUPABASE_PUBLISHABLE_KEY=... \
//     --dart-define QA_EMAIL=... --dart-define QA_PASSWORD=...
//
// KHÔNG service-role key: chỉ publishable key, đúng như app thật.
// Mọi dòng do smoke tạo đều mang note bắt đầu bằng `_kQaTag` để dọn được sạch.
library;

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/services/device_service.dart';
import 'package:agricarbon_app/services/sync_errors.dart';
import 'package:agricarbon_app/services/sync_gateway.dart';
import 'package:agricarbon_app/services/sync_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:uuid/uuid.dart';

const _url = String.fromEnvironment('SUPABASE_URL');
const _key = String.fromEnvironment('SUPABASE_PUBLISHABLE_KEY');
const _email = String.fromEnvironment('QA_EMAIL');
const _password = String.fromEnvironment('QA_PASSWORD');

const _kQaTag = 'QA-RUNTIME-SMOKE';

// `activities.client_event_id` là cột **uuid** — khoá idempotency phải là UUID
// thật, y như app sinh bằng `Uuid().v4()` trong `activity_form.dart`.
const _uuid = Uuid();

// ignore: avoid_print
void log(String m) => print('SMOKE| $m');

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('hosted runtime smoke: offline -> reopen -> sync idempotent',
      (tester) async {
    await tester.runAsync(() async {
      expect(_url.isNotEmpty && _key.isNotEmpty, isTrue,
          reason: 'thiếu --dart-define SUPABASE_*');
      await Supabase.initialize(url: _url, publishableKey: _key, debug: false);
      final client = Supabase.instance.client;

      /// Mạng THẬT hay không: thử một truy vấn nhỏ tới PostgREST.
      Future<bool> online() async {
        try {
          await client.from('farms').select('id').limit(1);
          return true;
        } catch (_) {
          return false;
        }
      }

      /// Chờ host bật/tắt mạng. Không tự đổi trạng thái — chỉ quan sát.
      Future<void> waitFor(bool want, String label) async {
        final deadline = DateTime.now().add(const Duration(minutes: 4));
        while (DateTime.now().isBefore(deadline)) {
          if (await online() == want) {
            log('network=$label (xác nhận bằng request thật)');
            return;
          }
          await Future<void>.delayed(const Duration(seconds: 2));
        }
        fail('quá hạn chờ mạng chuyển sang $label');
      }

      // ---- 1. ĐĂNG NHẬP THẬT + PHẠM VI (ONLINE) --------------------------
      final res = await client.auth
          .signInWithPassword(email: _email, password: _password);
      expect(res.session, isNotNull, reason: 'đăng nhập thất bại');
      final userId = res.user!.id;
      log('user_id=$userId');

      final gw = SupabaseSyncGateway(client);
      final devices = DeviceService(client);
      final farms = await gw.fetchFarms();
      log('farms_visible=${farms.length} '
          'codes=${farms.map((f) => f['farm_code']).toList()}');
      expect(farms, isNotEmpty, reason: 'QA farmer phải thấy farm của mình');
      expect(farms.length, 1, reason: 'chỉ được thấy ĐÚNG phạm vi của mình');

      // Cross-scope: hỏi thẳng farm KHÔNG thuộc phạm vi -> RLS trả rỗng.
      final foreignFarms = await client
          .from('farms')
          .select('id, farm_code')
          .eq('farm_code', 'DEMO-FARM-02');
      log('cross_scope_DEMO_FARM_02_farms=${(foreignFarms as List).length}');
      expect(foreignFarms.length, 0,
          reason: 'RLS phải chặn farm ngoài phạm vi');

      // Toàn bảng, không lọc: RLS vẫn chỉ được trả phạm vi của mình.
      final allPlots = await gw.fetchPlots();
      final myFarmId = farms.first['id'];
      final foreignPlots =
          allPlots.where((p) => p['farm_id'] != myFarmId).toList();
      log('plots_visible=${allPlots.length} '
          'plots_ngoai_pham_vi=${foreignPlots.length}');
      expect(foreignPlots, isEmpty, reason: 'không được lộ thửa của farm khác');

      final db = LocalDatabase();
      await db.openForUser(userId);
      final sync = SyncService(gw, db, devices);
      await sync.pullFarmsPlotsSeasons();
      final seasons = await gw.fetchCropSeasons();
      expect(seasons, isNotEmpty, reason: 'cần ít nhất 1 vụ để ghi hoạt động');
      final seasonServerId = seasons.first['id'] as String;
      final season = await db.getCropSeasonByServerId(seasonServerId);
      expect(season, isNotNull);
      final deviceId = await devices.ensureServerDeviceId();
      log('season_server_id=$seasonServerId '
          'season_client_id=${season!.clientId}');
      log('device_id=$deviceId');

      // ---- 2. CHỜ HOST CẮT MẠNG ------------------------------------------
      await waitFor(false, 'OFFLINE');

      // ---- 3. TẠO HOẠT ĐỘNG KHI MẤT MẠNG ---------------------------------
      // 23:00 ICT — ca sát ranh giới ngày, phải lưu thành 16:00Z CÙNG ngày.
      final occurredAt = DateTime.parse('2026-09-13T23:00:00+07:00');
      final eventId = _uuid.v4();
      await db.insertActivity(Activity(
        clientEventId: eventId,
        cropSeasonId: season.clientId,
        type: 'irrigation',
        occurredAt: occurredAt,
        payload: const {'method': 'awd', 'water_volume_m3': 12.5},
        note: '$_kQaTag tao offline, xoa sau khi nghiem thu',
        createdAt: DateTime.now(),
      ));
      log('created_offline client_event_id=$eventId '
          'occurred_at_local=$occurredAt '
          'occurred_at_wire=${occurredAt.toUtc().toIso8601String()}');

      final offlineSummary = await sync.syncAll();
      log('offline_sync synced=${offlineSummary.activitiesSynced} '
          'failures=${offlineSummary.failures.map((f) => f.kind.name).toList()}');
      expect(offlineSummary.activitiesSynced, 0,
          reason: 'mất mạng: không được ghi lên server');

      var row = await db.getActivity(eventId);
      expect(row, isNotNull, reason: 'bản ghi phải nằm lại máy');
      log('local_state=${row!.syncState.value} error=${row.syncError} '
          'retry_count=${row.retryCount}');
      expect(row.syncState, isNot(SyncState.synced));

      // ---- 4. MỞ LẠI CSDL ĐÃ LƯU (vẫn đang mất mạng) ----------------------
      // Đóng handle + mở lại file sqlite trong sandbox app: bản ghi pending
      // phải đọc lại được từ ĐĨA, không phải từ bộ nhớ tiến trình.
      await db.close();
      final db2 = LocalDatabase();
      await db2.openForUser(userId);
      final sync2 = SyncService(SupabaseSyncGateway(client), db2, devices);
      row = await db2.getActivity(eventId);
      expect(row, isNotNull, reason: 'pending phải sống qua lần mở lại');
      log('after_reopen client_event_id=${row!.clientEventId} '
          'state=${row.syncState.value} error=${row.syncError} '
          'retry_count=${row.retryCount}');
      expect(row.clientEventId, eventId,
          reason: 'khoá idempotency KHÔNG được sinh lại');

      final queue = await db2.listPendingActivities();
      final inQueue = queue.any((a) => a.clientEventId == eventId);
      log('still_in_retry_queue=$inQueue max_attempts=$kMaxSyncAttempts');
      expect(inQueue, isTrue,
          reason: 'lỗi mạng là TẠM THỜI -> phải còn trong hàng đợi');

      // ---- 5. CHỜ HOST NỐI LẠI MẠNG --------------------------------------
      await waitFor(true, 'ONLINE');

      // ---- 6. ĐỒNG BỘ -> ĐÚNG MỘT DÒNG -----------------------------------
      final s1 = await sync2.syncAll();
      log('sync1 synced=${s1.activitiesSynced} '
          'failures=${s1.failures.map((f) => f.kind.name).toList()}');
      expect(s1.activitiesSynced, 1);

      Future<List<Map<String, dynamic>>> remote() async => [
            for (final r in await client
                .from('activities')
                .select('id, occurred_at, recorded_at, note, device_id, '
                    'client_event_id, source')
                .eq('device_id', deviceId)
                .eq('client_event_id', eventId))
              Map<String, dynamic>.from(r as Map),
          ];

      final after1 = await remote();
      log('remote_rows_after_sync1=${after1.length}');
      log('remote_row=${after1.first}');
      expect(after1.length, 1, reason: 'phải đúng MỘT dòng trên server');
      final serverId1 = after1.first['id'];

      final s2 = await sync2.syncAll();
      log('sync2 synced=${s2.activitiesSynced} (0 = không còn gì pending)');
      expect((await remote()).length, 1);

      // Ép gửi lại CÙNG bản ghi (mô phỏng retry sau lỗi) — phải là upsert.
      await db2.updateActivitySyncState(eventId, state: SyncState.pending);
      final s3 = await sync2.syncAll();
      log('sync3_ep_gui_lai synced=${s3.activitiesSynced}');
      final after3 = await remote();
      log('remote_rows_after_forced_resync=${after3.length}');
      expect(after3.length, 1, reason: 'gửi lại KHÔNG được tạo dòng thứ 2');
      expect(after3.first['id'], serverId1, reason: 'vẫn đúng dòng cũ');
      expect(after3.first['device_id'], deviceId,
          reason: 'device_id không đổi giữa các lần thử');
      expect(after3.first['client_event_id'], eventId,
          reason: 'client_event_id không đổi giữa các lần thử');
      log('server_activity_id=$serverId1 (không đổi qua 3 lượt đồng bộ)');

      // ---- 7. MÚI GIỜ THẬT QUA POSTGRES timestamptz -----------------------
      final storedUtc =
          DateTime.parse(after3.first['occurred_at'] as String).toUtc();
      log('occurred_at_stored_utc=${storedUtc.toIso8601String()} '
          'expected=2026-09-13T16:00:00.000Z');
      log('read_back_ict=${storedUtc.add(const Duration(hours: 7))} '
          '(mong đợi 2026-09-13 23:00)');
      expect(storedUtc, DateTime.parse('2026-09-13T16:00:00.000Z'),
          reason: '23:00 ICT phải lưu thành 16:00Z CÙNG ngày');

      final detail = await client
          .from('irrigation_events')
          .select('activity_id, method, water_volume_m3')
          .eq('activity_id', serverId1 as Object);
      log('irrigation_events=${detail as List}');
      expect(detail.length, 1, reason: 'bảng chi tiết phải đi kèm');

      // ---- 8. LỖI VĨNH VIỄN KHÔNG ĐƯỢC THỬ LẠI MÃI ------------------------
      const badSeasonClient = 'qa-smoke-bad-season';
      final badEvent = _uuid.v4();
      await db2.upsertCropSeason(CropSeason(
        clientId: badSeasonClient,
        serverId: '00000000-0000-0000-0000-0000000000ff',
        plotClientId: 'qa-smoke-bad-plot',
        seasonCode: 'QA-BAD',
        syncState: SyncState.synced,
        createdAt: DateTime.now(),
        updatedAt: DateTime.now(),
      ));
      await db2.insertActivity(Activity(
        clientEventId: badEvent,
        cropSeasonId: badSeasonClient,
        type: 'irrigation',
        occurredAt: DateTime.now(),
        payload: const {'method': 'awd'},
        note: '$_kQaTag loi vinh vien (khong duoc ghi len server)',
        createdAt: DateTime.now(),
      ));
      final sBad = await sync2.syncAll();
      log('permanent_sync synced=${sBad.activitiesSynced} '
          'failures=${sBad.failures.map((f) => f.kind.name).toList()}');
      final badRow = await db2.getActivity(badEvent);
      log('bad_row state=${badRow!.syncState.value} '
          'error=${badRow.syncError} retry=${badRow.retryCount}');
      final requeued = (await db2.listPendingActivities())
          .any((a) => a.clientEventId == badEvent);
      log('permanent_requeued=$requeued (phải là false)');
      expect(requeued, isFalse, reason: 'lỗi vĩnh viễn KHÔNG được tự chọn lại');
      expect(await db2.getActivity(badEvent), isNotNull,
          reason: 'vẫn hiện trên màn Đồng bộ để người dùng xử lý');

      // ---- 9. AI GHI BẢN NÀY (P1-4) ---------------------------------------
      // `recorded_by` phải là CHÍNH user đang đăng nhập, lấy từ phiên Supabase.
      // Không có nó thì chủ sở hữu không tự xoá được bản ghi của mình, và
      // `DELETE /v1/activities/{id}` của backend cũng không (lọc `recorded_by`).
      final owned = await client
          .from('activities')
          .select('id, recorded_by, source')
          .eq('id', serverId1)
          .single();
      log('recorded_by=${owned['recorded_by']} expected=$userId');
      expect(owned['recorded_by'], userId,
          reason: 'P1-4: mobile phải ghi recorded_by = auth.uid()');

      // ---- 10. SỬA BẢN ĐÃ ĐỒNG BỘ -----------------------------------------
      // Sửa vẫn phải chạy được sau khi siết policy: trigger bất biến chỉ chặn
      // ĐỔI chủ / đổi loại / đổi khoá idempotency, không chặn sửa nội dung.
      const editedNote = '$_kQaTag da sua tren dien thoai';
      final before = await db2.getActivity(eventId);
      await db2.saveActivity(Activity(
        clientEventId: eventId,
        cropSeasonId: before!.cropSeasonId,
        type: before.type,
        occurredAt: before.occurredAt,
        payload: const {'method': 'awd', 'water_volume_m3': 19.0},
        note: editedNote,
        syncState: SyncState.pending,
        createdAt: before.createdAt,
        serverActivityId: before.serverActivityId,
      ));
      final sEdit = await sync2.syncAll();
      log('mobile_edit synced=${sEdit.activitiesSynced} '
          'failures=${sEdit.failures.map((f) => f.kind.name).toList()}');
      expect(sEdit.activitiesSynced, 1, reason: 'sửa bản của mình phải PASS');

      final edited = await client
          .from('activities')
          .select('id, note, recorded_by, row_version')
          .eq('id', serverId1)
          .single();
      log('after_edit=$edited');
      expect(edited['note'], editedNote);
      expect(edited['recorded_by'], userId,
          reason: 'sửa KHÔNG được làm rơi chủ sở hữu');
      expect((await remote()).length, 1, reason: 'sửa KHÔNG tạo dòng thứ 2');

      // ---- 11. XOÁ MỀM TỪ MOBILE (P1-3) -----------------------------------
      // Đi qua RPC `public.soft_delete_activity`, KHÔNG phải
      // `update ... set deleted_at`: Postgres áp policy SELECT lên cả dòng MỚI
      // của một UPDATE, mà `activities_select` đòi `deleted_at is null`, nên
      // đường UPDATE luôn 42501 dù `activities_update` cho phép.
      await db2.tombstoneActivity(eventId);
      final sDel = await sync2.syncAll();
      log('mobile_soft_delete deleted=${sDel.activitiesDeleted} '
          'failures=${sDel.failures.map((f) => f.kind.name).toList()}');
      expect(sDel.activitiesDeleted, 1,
          reason: 'P1-3: chủ sở hữu phải xoá mềm được bản của mình');
      expect(sDel.hasErrors, isFalse);

      expect(await db2.getActivity(eventId), isNull,
          reason: 'server đã xác nhận -> dọn tombstone local');

      // Đọc bình thường KHÔNG còn thấy dòng đó nữa.
      final afterDelete = await remote();
      log('remote_rows_after_soft_delete=${afterDelete.length} (phải là 0)');
      expect(afterDelete, isEmpty,
          reason: 'dòng đã xoá mềm phải bị ẩn khỏi SELECT thường');

      // Bảng chi tiết cũng bị ẩn THEO CHA (policy của nó join qua activities),
      // nhưng dòng vẫn còn trên server — host xác minh bằng kết nối đặc quyền.
      final detailAfter = await client
          .from('irrigation_events')
          .select('activity_id')
          .eq('activity_id', serverId1);
      log('irrigation_events_visible_after_delete=${(detailAfter as List).length} '
          '(0 = ẩn theo cha, KHÔNG phải bị xoá cứng)');
      log('HOST_VERIFY_SOFT_DELETED_ACTIVITY_ID=$serverId1');

      // Lượt đồng bộ tiếp theo: không nhân đôi, không lỗi, không nã lại.
      final sAfter = await sync2.syncAll();
      log('sync_after_delete deleted=${sAfter.activitiesDeleted} '
          'synced=${sAfter.activitiesSynced} '
          'failures=${sAfter.failures.map((f) => f.kind.name).toList()}');
      expect(sAfter.activitiesDeleted, 0);
      expect(sAfter.hasErrors, isFalse);
      expect((await remote()).length, 0, reason: 'không hồi sinh dòng đã xoá');

      // ---- 12. BẢN THỨ HAI, ĐỂ HOST THỬ XOÁ QUA BACKEND --------------------
      // Chứng minh dòng do MOBILE tạo giờ tương thích với ngữ nghĩa xoá của
      // backend: `ActivityWriteRepository.soft_delete` lọc `recorded_by = actor`,
      // trước P1-4 thì cột đó rỗng nên endpoint cũng không xoá được.
      final backendEvent = _uuid.v4();
      await db2.insertActivity(Activity(
        clientEventId: backendEvent,
        cropSeasonId: season.clientId,
        type: 'irrigation',
        occurredAt: DateTime.now(),
        payload: const {'method': 'awd', 'water_volume_m3': 3.0},
        note: '$_kQaTag cho host xoa qua DELETE /v1/activities/{id}',
        createdAt: DateTime.now(),
      ));
      final sBackend = await sync2.syncAll();
      log('backend_compat_row synced=${sBackend.activitiesSynced} '
          'failures=${sBackend.failures.map((f) => f.kind.name).toList()}');
      expect(sBackend.activitiesSynced, 1);
      final backendRow = await db2.getActivity(backendEvent);
      log('HOST_VERIFY_BACKEND_DELETE_ACTIVITY_ID='
          '${backendRow!.serverActivityId}');
      final backendRemote = await client
          .from('activities')
          .select('id, recorded_by')
          .eq('id', backendRow.serverActivityId as Object)
          .single();
      expect(backendRemote['recorded_by'], userId,
          reason: 'dòng thứ hai cũng phải có recorded_by');
      await db2.hardDeleteActivity(backendEvent); // host sở hữu vòng đời dòng này

      // ---- 12. XOÁ NGOÀI PHẠM VI -> TỪ CHỐI, KHÔNG NÃ LẠI ------------------
      // Dòng thật thuộc DEMO-FARM-02 (host truyền vào). Không có thì dùng một
      // uuid không tồn tại — cùng một nhánh từ chối của RPC.
      const crossId = String.fromEnvironment('QA_CROSS_ACTIVITY_ID');
      final targetCrossId =
          crossId.isNotEmpty ? crossId : '00000000-0000-0000-0000-0000000000aa';
      final crossEvent = _uuid.v4();
      await db2.insertActivity(Activity(
        clientEventId: crossEvent,
        cropSeasonId: season.clientId,
        type: 'irrigation',
        occurredAt: DateTime.now(),
        payload: const {'method': 'awd'},
        note: '$_kQaTag xoa ngoai pham vi (khong duoc phep)',
        createdAt: DateTime.now(),
        serverActivityId: targetCrossId,
        syncState: SyncState.synced,
      ));
      await db2.tombstoneActivity(crossEvent);
      final sCross = await sync2.syncAll();
      log('cross_scope_delete target=$targetCrossId '
          'deleted=${sCross.activitiesDeleted} '
          'failures=${sCross.failures.map((f) => f.kind.name).toList()}');
      expect(sCross.activitiesDeleted, 0,
          reason: 'KHÔNG được xoá dòng ngoài phạm vi / của người khác');
      expect(sCross.failures.single.kind, SyncErrorKind.rlsDenied);

      final crossRow = await db2.getActivity(crossEvent);
      expect(crossRow, isNotNull, reason: 'giữ hàng, không nuốt lỗi');
      final crossRequeued = (await db2.listPendingActivities())
          .any((a) => a.clientEventId == crossEvent);
      log('cross_scope_requeued=$crossRequeued '
          '(false = từ chối VĨNH VIỄN, không nã request vô hạn)');
      expect(crossRequeued, isFalse);
      await db2.hardDeleteActivity(crossEvent);

      // ---- 13. LIỆT KÊ DỮ LIỆU QA CÒN LẠI ĐỂ HOST DỌN --------------------
      // `authenticated` KHÔNG có quyền delete trên `activities` / `devices`, và
      // dòng đã xoá mềm thì chính client cũng không còn thấy, nên bước dọn phải
      // chạy từ host bằng kết nối đặc quyền. Ở đây chỉ LIỆT KÊ cái còn THẤY.
      final strays = await client
          .from('activities')
          .select('id, note')
          .like('note', '$_kQaTag%');
      log('QA_LIVE_ROWS_VISIBLE_TO_FARMER='
          '${(strays as List).map((r) => (r as Map)['id']).toList()}');
      final devs = await client.from('devices').select('id, created_at');
      log('QA_DEVICE_ROWS_FOR_HOST_CLEANUP='
          '${(devs as List).map((r) => (r as Map)['id']).toList()}');
      final batches = await client
          .from('production_batches')
          .select('id, batch_code, created_at')
          .eq('crop_season_id', seasonServerId);
      log('production_batches=${batches as List}');

      await db2.hardDeleteActivity(badEvent);
      await db2.close();
      await client.auth.signOut();
      log('signed_out=${client.auth.currentSession == null}');
    });
  }, timeout: const Timeout(Duration(minutes: 12)));
}

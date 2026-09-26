// P1 lifecycle, RUNTIME THẬT: Android emulator -> Supabase hosted (RLS thật)
// + FastAPI local (đóng vụ bằng đúng đường Web/Management dùng).
//
// Do `backend/scripts/hosted_flutter_lifecycle_e2e.py` điều khiển: script tạo
// tenant DÙNG MỘT LẦN (HTX, nông dân, nông hộ, thửa), truyền thông tin qua
// --dart-define, bật/tắt mạng emulator bằng `adb` khi thấy dòng
// `SMOKE| WAIT_OFFLINE` / `SMOKE| WAIT_ONLINE`, rồi kiểm DB và dọn sạch.
//
// Luồng:
//  1. tạo vụ trên máy như form (status active) -> sync -> vụ + lô default
//  2. ghi công việc KHI MẤT MẠNG -> sync online -> đúng 1 hoạt động trên server
//  3. đóng vụ qua FastAPI PATCH /v1/crop-seasons/{id}/status
//  4. ghi thêm 1 công việc (máy chưa biết vụ đã đóng) -> sync -> DB từ chối
//  5. hàng đợi: failed/seasonClosed, KHÔNG mất bản ghi, KHÔNG thử lại mãi
//  6. lượt kéo nhận trạng thái vụ đã kết thúc về máy
library;

import 'dart:convert';
import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/methodology_enums.dart';
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
const _plotServerId = String.fromEnvironment('PLOT_ID');
const _api = String.fromEnvironment('API_BASE_URL', defaultValue: 'http://10.0.2.2:8010');
const _tag = String.fromEnvironment('TAG');
const _uuid = Uuid();

// ignore: avoid_print
void log(String m) => print('SMOKE| $m');

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('season lifecycle: start -> offline record -> close on Web -> queued record refused',
      (tester) async {
    await tester.runAsync(() async {
      expect(_url.isNotEmpty && _key.isNotEmpty && _plotServerId.isNotEmpty && _tag.isNotEmpty, isTrue);
      await Supabase.initialize(url: _url, publishableKey: _key, debug: false);
      final client = Supabase.instance.client;

      Future<bool> online() async {
        try {
          await client.from('farms').select('id').limit(1);
          return true;
        } catch (_) {
          return false;
        }
      }

      Future<void> waitFor(bool want, String label) async {
        final deadline = DateTime.now().add(const Duration(minutes: 3));
        while (DateTime.now().isBefore(deadline)) {
          if (await online() == want) {
            log('network=$label');
            return;
          }
          await Future<void>.delayed(const Duration(seconds: 2));
        }
        fail('network did not become $label');
      }

      final res = await client.auth.signInWithPassword(email: _email, password: _password);
      final userId = res.user!.id;
      final gw = SupabaseSyncGateway(client);
      final devices = DeviceService(client);
      final db = LocalDatabase();
      await db.openForUser(userId);
      final sync = SyncService(gw, db, devices);
      // Registered while online, as the app does at sign-in (and as
      // hosted_runtime_smoke_test.dart does): an offline sync reuses it.
      await devices.ensureServerDeviceId();
      await sync.pullFarmsPlotsSeasons();
      final plot = await db.getPlotByServerId(_plotServerId);
      expect(plot, isNotNull, reason: 'the disposable plot must be in scope');

      // 1. Start a season exactly as the form does now (status active).
      final now = DateTime.now();
      final season = CropSeason(
        clientId: _uuid.v4(),
        plotClientId: plot!.clientId,
        seasonCode: '$_tag-HT',
        status: CropSeasonStatus.active,
        createdAt: now,
        updatedAt: now,
      );
      await db.upsertCropSeason(season);
      final s0 = await sync.syncAll();
      log('season_sync synced=${s0.cropSeasonsSynced} failures=${s0.failures.map((f) => f.kind.name).toList()}');
      final synced = (await db.getCropSeasonByClientId(season.clientId))!;
      final seasonId = synced.serverId!;
      log('SEASON_ID=$seasonId');
      final remoteSeason = await client.from('crop_seasons').select('status').eq('id', seasonId).single();
      expect(remoteSeason['status'], 'active');

      // 2. Record offline, then sync online.
      log('WAIT_OFFLINE');
      await waitFor(false, 'OFFLINE');
      final firstId = _uuid.v4();
      await db.insertActivity(Activity(
        clientEventId: firstId, cropSeasonId: season.clientId, type: 'irrigation',
        occurredAt: DateTime.now(), payload: const {'method': 'awd', 'water_volume_m3': 3.0},
        note: '$_tag-FIRST', createdAt: DateTime.now(),
      ));
      final offline = await sync.syncAll();
      expect(offline.activitiesSynced, 0);
      log('WAIT_ONLINE');
      await waitFor(true, 'ONLINE');
      final online1 = await sync.syncAll();
      log('first_sync synced=${online1.activitiesSynced} failures=${online1.failures.map((f) => f.kind.name).toList()}');
      expect(online1.activitiesSynced, 1);
      final batches = await client.from('production_batches').select('id, batch_code').eq('crop_season_id', seasonId);
      expect((batches as List).length, 1);
      expect(batches.single['batch_code'], 'default');
      final remote1 = await client.from('activities').select('id, production_batch_id').eq('note', '$_tag-FIRST');
      expect((remote1 as List).length, 1);
      expect(remote1.single['production_batch_id'], batches.single['id']);

      // 3. The season is ended on the Web / Management path (FastAPI).
      final http = HttpClient();
      final req = await http.patchUrl(Uri.parse('$_api/v1/crop-seasons/$seasonId/status'));
      req.headers.set('Authorization', 'Bearer ${client.auth.currentSession!.accessToken}');
      req.headers.contentType = ContentType.json;
      req.write(jsonEncode({'status': 'harvested'}));
      final resp = await req.close();
      final body = await resp.transform(utf8.decoder).join();
      log('close_season http=${resp.statusCode}');
      expect(resp.statusCode, 200, reason: body);

      // 4. The phone has not pulled yet: it still believes the season is open.
      final lateId = _uuid.v4();
      await db.insertActivity(Activity(
        clientEventId: lateId, cropSeasonId: season.clientId, type: 'irrigation',
        occurredAt: DateTime.now(), payload: const {'method': 'awd'},
        note: '$_tag-LATE', createdAt: DateTime.now(),
      ));
      final refused = await sync.syncAll();
      log('late_sync failures=${refused.failures.map((f) => f.kind.name).toList()}');
      expect(refused.failures.map((f) => f.kind), contains(SyncErrorKind.seasonClosed));

      // 5. Kept, marked, not retried forever.
      var late = await db.getActivity(lateId);
      expect(late, isNotNull, reason: 'never silently dropped');
      expect(late!.syncState, SyncState.failed);
      expect(late.syncError, SyncErrorKind.seasonClosed.name);
      final retriesAfterFirst = late.retryCount;
      await sync.syncAll();
      await sync.syncAll();
      late = await db.getActivity(lateId);
      expect(late!.retryCount, retriesAfterFirst, reason: 'permanent: not picked again');
      expect((await db.listPendingActivities()).any((a) => a.clientEventId == lateId), isFalse);
      final remoteLate = await client.from('activities').select('id').eq('note', '$_tag-LATE');
      expect((remoteLate as List), isEmpty, reason: 'the database refused it');
      log('late_state=${late.syncState.value} error=${late.syncError} retry_count=${late.retryCount}');
      log('message=${syncErrorMessage(SyncErrorKind.seasonClosed)}');

      // 6. The next pull brings the ended status to the phone.
      await sync.pullFarmsPlotsSeasons();
      final pulled = (await db.getCropSeasonByClientId(season.clientId))!;
      log('local_season_status=${pulled.status.wire}');
      expect(pulled.status, CropSeasonStatus.harvested);
      expect(seasonAcceptsActivities(pulled.status), isFalse);

      await db.close();
      await client.auth.signOut();
      log('DONE');
    });
  });
}

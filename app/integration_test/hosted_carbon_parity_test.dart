// Nghiệm thu Carbon UX parity trên THIẾT BỊ Android, đánh vào Supabase hosted +
// backend thật. Dùng MÀN HÌNH THẬT của app (màn Carbon, sheet phương pháp
// tính, form hoạt động) với dịch vụ thật (Supabase, SyncService, CarbonApi);
// không đi qua điều hướng của shell.
//
// Chạy bởi `backend/scripts/hosted_flutter_carbon_parity_e2e.py`: script đó tạo
// một tenant QA riêng (vụ CHƯA có thông tin phương pháp tính), truyền id qua
// --dart-define, bật/tắt mạng emulator bằng `adb shell svc` khi test in
// `SMOKE| WAIT_OFFLINE` / `SMOKE| WAIT_ONLINE`, kiểm lại DB, rồi xoá sạch.
library;

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/methodology_enums.dart';
import 'package:agricarbon_app/screens/activity_form.dart';
import 'package:agricarbon_app/screens/carbon_result_screen.dart';
import 'package:agricarbon_app/services/carbon_api_service.dart';
import 'package:agricarbon_app/services/carbon_cache.dart';
import 'package:agricarbon_app/services/connectivity_service.dart';
import 'package:agricarbon_app/services/device_service.dart';
import 'package:agricarbon_app/services/me_service.dart';
import 'package:agricarbon_app/services/read_api.dart';
import 'package:agricarbon_app/services/sync_gateway.dart';
import 'package:agricarbon_app/services/sync_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

const _url = String.fromEnvironment('SUPABASE_URL');
const _key = String.fromEnvironment('SUPABASE_PUBLISHABLE_KEY');
const _email = String.fromEnvironment('QA_EMAIL');
const _password = String.fromEnvironment('QA_PASSWORD');
const _seasonServerId = String.fromEnvironment('QA_SEASON_ID');

// ignore: avoid_print
void log(String m) => print('SMOKE| $m');

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Flutter Carbon parity on hosted dev', (tester) async {
    expect(_seasonServerId.isNotEmpty, isTrue, reason: 'driven by the e2e script');
    tester.view.physicalSize = const Size(1080, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    Future<T> real<T>(Future<T> Function() f) async => (await tester.runAsync(f)) as T;

    await real(() => Supabase.initialize(url: _url, publishableKey: _key, debug: false));
    final client = Supabase.instance.client;
    final auth = await real(() => client.auth.signInWithPassword(email: _email, password: _password));
    final userId = auth.user!.id;
    String? token() => client.auth.currentSession?.accessToken;

    var db = LocalDatabase();
    await real(() => db.openForUser(userId));
    final devices = DeviceService(client);
    var sync = SyncService(SupabaseSyncGateway(client), db, devices);
    await real(() => sync.pullFarmsPlotsSeasons());
    final season = (await real(() => db.getCropSeasonByServerId(_seasonServerId)))!;
    final cs = season.clientId;
    log('season client=$cs server=$_seasonServerId');

    final carbonApi = CarbonApiService.withTokenProvider(token);
    final me = MeService(ReadApi(token));

    Future<bool> online() async {
      try {
        await client.from('farms').select('id').limit(1);
        return true;
      } catch (_) {
        return false;
      }
    }

    Future<void> waitNetwork(bool want, String label) async {
      log(want ? 'WAIT_ONLINE' : 'WAIT_OFFLINE');
      final deadline = DateTime.now().add(const Duration(minutes: 4));
      while (DateTime.now().isBefore(deadline)) {
        if (await real(online) == want) {
          log('network=$label');
          return;
        }
        await real(() => Future<void>.delayed(const Duration(seconds: 2)));
      }
      fail('network did not become $label');
    }

    Future<void> syncNow() async {
      final s = await sync.syncAll();
      log('sync seasons=${s.cropSeasonsSynced} activities=${s.activitiesSynced} '
          'deleted=${s.activitiesDeleted} errors=${s.errorCount}');
    }

    /// Chờ tới khi [finder] xuất hiện, trong thời gian THẬT (mạng thật).
    Future<void> waitFor(Finder finder, {Duration timeout = const Duration(seconds: 90)}) async {
      final deadline = DateTime.now().add(timeout);
      while (DateTime.now().isBefore(deadline)) {
        await tester.pump(const Duration(milliseconds: 250));
        if (finder.evaluate().isNotEmpty) return;
        await real(() => Future<void>.delayed(const Duration(milliseconds: 250)));
      }
      final shown = [
        for (final e in find.byType(Text).evaluate())
          if ((e.widget as Text).data != null) (e.widget as Text).data!,
      ];
      log('SCREEN_TEXT ${shown.join(' | ')}');
      fail('timed out waiting for $finder');
    }

    Future<void> waitGone(Finder finder, {Duration timeout = const Duration(seconds: 90)}) async {
      final deadline = DateTime.now().add(timeout);
      while (DateTime.now().isBefore(deadline)) {
        await tester.pump(const Duration(milliseconds: 250));
        if (finder.evaluate().isEmpty) return;
        await real(() => Future<void>.delayed(const Duration(milliseconds: 250)));
      }
      fail('timed out waiting for $finder to disappear');
    }

    Finder field(String label) =>
        find.ancestor(of: find.text(label), matching: find.byType(TextField)).first;

    Future<void> type(String label, String value) async {
      await tester.enterText(field(label), value);
      await tester.pump();
    }

    Future<void> choose(String label, String option) async {
      await tester.tap(find.ancestor(of: find.text(label), matching: find.byType(DropdownButtonFormField<String>)).first);
      await tester.pump(const Duration(milliseconds: 400));
      await tester.tap(find.text(option).last);
      await tester.pump(const Duration(milliseconds: 400));
    }

    Widget activityForm(String activityType, {Activity? existing, required VoidCallback done}) => Scaffold(
          body: SingleChildScrollView(
            // Mỗi form một State mới, như một route mới trong app thật (cùng vị
            // trí trong cây thì Flutter sẽ dùng lại State của form trước).
            child: ActivityForm(
              key: UniqueKey(),
              db: db,
              cropSeasonClientId: cs,
              activityType: activityType,
              existing: existing,
              online: true,
              onSaved: () async => done(),
            ),
          ),
        );

    /// Ghi một hoạt động qua FORM THẬT, lưu trên máy.
    Future<void> record(String activityType, Future<void> Function() fill) async {
      var saved = false;
      await tester.pumpWidget(MaterialApp(
        theme: AgriCarbonTheme.light(),
        home: activityForm(activityType, done: () => saved = true),
      ));
      await tester.pump();
      await fill();
      await tester.tap(find.text('Lưu công việc'));
      final deadline = DateTime.now().add(const Duration(seconds: 20));
      while (!saved && DateTime.now().isBefore(deadline)) {
        await tester.pump(const Duration(milliseconds: 200));
        await real(() => Future<void>.delayed(const Duration(milliseconds: 100)));
      }
      expect(saved, isTrue, reason: '$activityType form did not save');
      await real(() => db.markCarbonInputsChanged(cs));
    }

    final navKey = GlobalKey<NavigatorState>();
    Future<void> openCarbon({required bool isOnline}) async {
      await tester.pumpWidget(MaterialApp(
        navigatorKey: navKey,
        theme: AgriCarbonTheme.light(),
        home: CarbonResultScreen(
          key: UniqueKey(),
          carbonApi: carbonApi,
          cache: CarbonCache(db),
          db: db,
          cropSeasonClientId: cs,
          connectivity: ConnectivityService.fixed(isOnline),
          syncNow: syncNow,
          loadWritableFarmIds: () async => (await me.fetch()).writableFarmIds,
          editActivity: (activity) async {
            await navKey.currentState!.push(MaterialPageRoute<void>(
              builder: (routeCtx) => activityForm(activity.type,
                  existing: activity, done: () => Navigator.of(routeCtx).pop()),
            ));
          },
        ),
      ));
      await tester.pump();
    }

    Future<List<String>> readinessCodes() async {
      final r = await real(() => carbonApi.readiness(cropSeasonId: _seasonServerId));
      return [for (final m in r.missingInputs) '${m.code}${m.blocking ? '' : '(non-blocking)'}'];
    }

    // ---- 0. vụ mới: thiếu thông tin phương pháp tính --------------------------
    log('READINESS_INITIAL ${await readinessCodes()}');
    await openCarbon(isOnline: true);
    await waitFor(find.byKey(const Key('carbon-missing-title')));
    expect(find.text('Thiếu chế độ nước trong vụ'), findsOneWidget);

    // ---- 1-3. sửa nhanh ba thông tin của vụ, từ màn Carbon ---------------------
    await tester.tap(find.byKey(const Key('fix-season-water_regime')));
    await waitFor(find.byKey(const Key('methodology-save')));
    await choose('Chế độ nước trong vụ', IpccWaterRegime.irrigatedMultipleDrainage.labelVi);
    await choose('Chế độ nước trước vụ', PreSeasonWaterRegime.nonFloodedLt180d.labelVi);
    await type('Số ngày canh tác', '100');
    await tester.tap(find.byKey(const Key('methodology-save')));
    await waitGone(find.text('Thiếu chế độ nước trong vụ'));
    await waitGone(find.text('Thiếu số ngày canh tác'));
    log('METHODOLOGY_FIXED ${await readinessCodes()}');

    // ---- 4. phân bón KHÔNG có % đạm -> Sửa ngay -> nhập đạm ----------------------
    await record('fertilizer', () async {
      await type('Tên phân *', 'NPK 16-16-8');
      await type('Khối lượng (kg) *', '80');
    });
    await real(syncNow);
    await openCarbon(isOnline: true);
    await waitFor(find.text('Thiếu hàm lượng Nitơ của lần bón phân'));
    final nFix = find.textContaining('Sửa ngay');
    await tester.tap(nFix.first);
    await waitFor(find.text('Lưu thay đổi'));
    await type('% đạm (N) (%)', '16');
    await tester.tap(find.text('Lưu thay đổi'));
    await waitGone(find.text('Thiếu hàm lượng Nitơ của lần bón phân'));
    log('NITROGEN_FIXED ${await readinessCodes()}');

    // ---- 5. rơm vùi, để trống chất khô + số ngày -> Sửa ngay ---------------------
    await record('straw_management', () async {
      await choose('Cách xử lý rơm *', 'Vùi vào đất');
      await type('Khối lượng rơm (kg)', '800');
    });
    await real(syncNow);
    await openCarbon(isOnline: true);
    await waitFor(find.text('Thiếu tỷ lệ chất khô của rơm'));
    expect(find.text('Thiếu số ngày vùi rơm trước khi làm đất'), findsOneWidget);
    await tester.tap(find.textContaining('Sửa ngay').first);
    await waitFor(find.text('Lưu thay đổi'));
    await type('Tỷ lệ chất khô', '0,85');
    await type('Số ngày trước khi bắt đầu canh tác (ngày)', '20');
    await tester.tap(find.text('Lưu thay đổi'));
    await waitGone(find.text('Thiếu tỷ lệ chất khô của rơm'));
    await waitGone(find.text('Thiếu số ngày vùi rơm trước khi làm đất'));
    log('STRAW_FIXED ${await readinessCodes()}');

    // ---- 6. thu hoạch (mẫu số CO2e/kg) -----------------------------------------
    await record('harvest', () async => type('Sản lượng thu hoạch (kg) *', '6000'));
    await real(syncNow);

    // ---- fuel: giới hạn trung thực, rồi xoá (soft delete M01 qua RPC) ------------
    await record('fuel', () async {
      await choose('Loại nhiên liệu *', 'Dầu diesel');
      await type('Số lít (lít) *', '12');
    });
    await real(syncNow);
    await openCarbon(isOnline: true);
    await waitFor(find.byKey(const Key('carbon-issue-fuel_factor_unverified')));
    expect(find.descendant(of: find.byKey(const Key('carbon-issue-fuel_factor_unverified')),
        matching: find.text('Sửa ngay')), findsNothing);
    expect(find.byKey(const Key('carbon-limitation-note')), findsOneWidget);
    expect(find.byKey(const Key('carbon-calculate')), findsNothing);
    log('FUEL_LIMITATION_SHOWN ${await readinessCodes()}');
    final fuel = (await real(() => db.listActivitiesByCropSeasonClientId(cs)))
        .firstWhere((a) => a.type == 'fuel');
    await real(() => db.tombstoneActivity(fuel.clientEventId));
    await real(() => db.markCarbonInputsChanged(cs));
    await real(syncNow);
    log('FUEL_SOFT_DELETED server_id=${fuel.serverActivityId}');

    // ---- 7-10. đủ dữ liệu -> Tính Carbon trên máy chủ ----------------------------
    await openCarbon(isOnline: true);
    await waitFor(find.byKey(const Key('carbon-calculate')));
    expect(find.text('Đã đủ dữ liệu để tính phát thải.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('carbon-calculate')));
    await waitFor(find.widgetWithText(ElevatedButton, 'Tính lại Carbon'), timeout: const Duration(minutes: 2));
    final latest = await real(() => carbonApi.latest(cropSeasonId: _seasonServerId, scenario: 'as_recorded'));
    log('CARBON total_co2e_kg=${latest!.totalCo2eKg} co2e_per_kg=${latest.co2ePerKg} '
        'calculated_at=${latest.calculatedAt}');
    expect(find.byKey(const Key('carbon-stale')), findsNothing);

    // ---- 11-13. "đóng/mở lại app": đóng DB, mở lại, kết quả + giá trị vẫn còn -----
    await real(() => db.close());
    db = LocalDatabase();
    await real(() => db.openForUser(userId));
    sync = SyncService(SupabaseSyncGateway(client), db, devices);
    final reopened = (await real(() => db.getCropSeasonByClientId(cs)))!;
    expect(reopened.cultivationDays, 100);
    expect(reopened.ipccWaterRegime, IpccWaterRegime.irrigatedMultipleDrainage);
    await openCarbon(isOnline: true);
    await waitFor(find.widgetWithText(ElevatedButton, 'Tính lại Carbon'));
    log('REOPEN_OK days=${reopened.cultivationDays}');

    // ---- OFFLINE: sửa + ghi mới trên máy, khởi động lại, gửi khi có mạng ----------
    await waitNetwork(false, 'OFFLINE');
    final beforeOffline = (await real(() => db.getCropSeasonByClientId(cs)))!;
    await real(() => db.upsertCropSeason(beforeOffline.copyWith(
          cultivationDays: 105,
          syncState: SyncState.pending,
          updatedAt: DateTime.now(),
        )));
    await real(() => db.markCarbonInputsChanged(cs));
    await record('fertilizer', () async {
      await type('Tên phân *', 'Ure');
      await type('Khối lượng (kg) *', '20');
      await type('% đạm (N) (%)', '46');
    });
    final offlineEvent = (await real(() => db.listActivitiesByCropSeasonClientId(cs)))
        .firstWhere((a) => a.payload['fertilizer_name'] == 'Ure');
    log('OFFLINE_CREATED client_event_id=${offlineEvent.clientEventId}');
    await openCarbon(isOnline: false);
    await waitFor(find.textContaining('Cần kết nối mạng'));
    expect(find.byKey(const Key('carbon-calculate')), findsNothing);
    await waitFor(find.byKey(const Key('carbon-stale'))); // kết quả đã lưu nay đã cũ
    final offlineAttempt = await real(() => sync.syncAll());
    log('offline sync attempt errors=${offlineAttempt.errorCount}');

    // "khởi động lại app" khi vẫn offline
    await real(() => db.close());
    db = LocalDatabase();
    await real(() => db.openForUser(userId));
    sync = SyncService(SupabaseSyncGateway(client), db, devices);
    final keptSeason = (await real(() => db.getCropSeasonByClientId(cs)))!;
    final keptEvent = await real(() => db.getActivity(offlineEvent.clientEventId));
    expect(keptSeason.cultivationDays, 105);
    expect(keptSeason.syncState, isNot(SyncState.synced));
    expect(keptEvent, isNotNull);
    expect(keptEvent!.syncState, isNot(SyncState.synced));
    log('OFFLINE_KEPT_AFTER_RESTART season_state=${keptSeason.syncState.value} '
        'activity_state=${keptEvent.syncState.value}');

    await waitNetwork(true, 'ONLINE');
    await real(syncNow);
    await real(syncNow); // lần hai: không gì chờ, không gửi trùng
    final synced = (await real(() => db.getCropSeasonByClientId(cs)))!;
    expect(synced.syncState, SyncState.synced);
    log('ONLINE_SYNCED season_state=${synced.syncState.value} '
        'readiness=${await readinessCodes()}');
    log('DONE');
  });
}

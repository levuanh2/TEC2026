// Round 5.1 — nông hộ đã đăng nhập, mở app OFFLINE khi access token đã hết hạn.
//
// Phải: xem/ghi/sửa/xoá và xem hàng đợi được; không có lượt gửi nào tới máy
// chủ trước khi làm mới phiên thành công; khi có mạng thì làm mới rồi gửi ĐÚNG
// MỘT lần; làm mới bị từ chối thì KHÔNG gửi gì và hàng đợi còn nguyên. Đăng xuất
// chủ động vẫn là đường riêng. Phiên lưu ở kho bảo mật, không ở
// SharedPreferences rõ chữ.

import 'dart:async';
import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/services/auth_service.dart';
import 'package:agricarbon_app/services/connectivity_service.dart';
import 'package:agricarbon_app/services/device_service.dart';
import 'package:agricarbon_app/services/secure_session_storage.dart';
import 'package:agricarbon_app/services/sync_coordinator.dart';
import 'package:agricarbon_app/services/sync_gateway.dart';
import 'package:agricarbon_app/services/sync_service.dart';
import 'package:agricarbon_app/shell/auth_controller.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:supabase_flutter/supabase_flutter.dart'
    show AuthApiException, AuthRetryableFetchException;

const _user = 'aaaa1111-0000-0000-0000-000000000000';

/// Phiên giả: hết hạn hay không, làm mới ra sao — do test quyết định.
class _FakeAuth extends AuthService {
  final _signals = StreamController<AuthSignal>.broadcast();
  bool expired = true;
  bool hasSession = true;

  /// null = làm mới thành công; khác null = ném lỗi này.
  Object? refreshError = AuthRetryableFetchException();
  int refreshCalls = 0;
  int signOutCalls = 0;

  @override
  Stream<AuthSignal> get signals => _signals.stream;
  @override
  String? get currentUserId => hasSession ? _user : null;
  @override
  bool get onlineSessionExpired => hasSession && expired;

  @override
  Future<SessionFreshness> ensureFreshSession() => checkSessionFreshness(
        hasSession: hasSession,
        isExpired: expired,
        refresh: () async {
          refreshCalls++;
          final e = refreshError;
          if (e == null) {
            expired = false;
            _signals.add(const AuthSignal(AuthSignalKind.tokenRefreshed, _user));
            return true;
          }
          if (e is AuthRetryableFetchException) {
            _signals.addError(e); // đúng như gotrue: lỗi mạng lên stream
          } else {
            // gotrue: máy chủ từ chối → xoá phiên, phát signedOut.
            hasSession = false;
            _signals.add(const AuthSignal(AuthSignalKind.signedOut, null));
          }
          throw e;
        },
      );

  @override
  Future<void> signOut() async {
    signOutCalls++;
    hasSession = false;
    _signals.add(const AuthSignal(AuthSignalKind.signedOut, null));
  }

  void emitError(Object e) => _signals.addError(e);
}

/// Máy chủ giả: đếm MỌI lời gọi mạng của lượt gửi.
class _Server implements SyncGateway {
  final activities = <String, String>{};
  int calls = 0;
  int inserts = 0;

  @override
  Future<String> upsertPlot(Map<String, dynamic> row) async {
    calls++;
    return 'srv-plot';
  }

  @override
  Future<String> upsertCropSeason(Map<String, dynamic> row) async {
    calls++;
    return 'srv-cs';
  }

  @override
  Future<String> ensureDefaultBatch(String id) async {
    calls++;
    return 'batch-$id';
  }

  @override
  Future<String> upsertActivity(Map<String, dynamic> row) async {
    calls++;
    final ceid = row['client_event_id'] as String;
    return activities.putIfAbsent(ceid, () {
      inserts++;
      return 'srv-$ceid';
    });
  }

  @override
  Future<void> upsertActivityDetail(String t, Map<String, dynamic> r) async {
    calls++;
  }

  @override
  Future<void> softDeleteActivity(String id) async {
    calls++;
    activities.removeWhere((_, v) => v == id);
  }

  @override
  String? currentUserId() => _user;
  @override
  Future<String?> currentCooperativeId() async => 'org';
  @override
  Future<List<Map<String, dynamic>>> fetchFarms() async => [];
  @override
  Future<List<Map<String, dynamic>>> fetchPlots() async => [];
  @override
  Future<List<Map<String, dynamic>>> fetchCropSeasons() async => [];
}

Activity _act(String id, {double kg = 20}) => Activity(
      clientEventId: id,
      cropSeasonId: 'cs1',
      type: 'fertilizer',
      occurredAt: DateTime(2026, 3, 2, 7),
      payload: {'fertilizer_name': 'Ure', 'amount_kg': kg},
      createdAt: DateTime(2026, 3, 2, 7),
    );

/// sqflite ffi chạy I/O thật trong isolate — chờ theo điều kiện, không theo lượt.
Future<void> _until(bool Function() ok) async {
  for (var i = 0; i < 200 && !ok(); i++) {
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  expect(ok(), isTrue, reason: 'hết thời gian chờ');
}

void main() {
  setUpAll(sqfliteFfiInit);

  late Directory tmp;
  late LocalDatabase db;
  late _FakeAuth auth;
  late _Server server;
  late ConnectivityService conn;
  late SyncCoordinator co;
  late AuthController controller;

  Future<void> openOffline() async {
    db = LocalDatabase(factory: databaseFactoryFfi, directoryOverride: tmp.path);
    conn = ConnectivityService.fixed(false);
    co = SyncCoordinator(
      sync: SyncService(server, db, DeviceService.fixed('dev-1')),
      db: db,
      connectivity: conn,
      ensureSession: auth.ensureFreshSession,
      connectivityDebounce: const Duration(milliseconds: 10),
    );
    controller = AuthController(
      auth,
      onUserActive: (uid) async {
        await db.openForUser(uid);
        await co.attach();
        unawaited(co.onLogin());
      },
      onUserInactive: () async {
        co.detach();
        await db.close();
      },
    )..start();
    await _until(() => controller.phase == AuthPhase.authenticated);
    await _until(() => !co.isSyncing);
  }

  Future<void> closeAll() async {
    controller.dispose();
    co.dispose();
    conn.dispose();
    await db.close();
  }

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('agri_expired');
    auth = _FakeAuth();
    server = _Server();
    // Bước 1: đã đăng nhập online trước đó và có cây thửa/vụ đã đồng bộ.
    final seed =
        LocalDatabase(factory: databaseFactoryFfi, directoryOverride: tmp.path);
    await seed.openForUser(_user);
    final now = DateTime(2026, 3);
    await seed.upsertPlot(Plot(
        clientId: 'p1', serverId: 'srv-p1', farmId: 'f1', plotCode: 'P1',
        name: 'Thửa 1', areaHa: 1, syncState: SyncState.synced,
        createdAt: now, updatedAt: now));
    await seed.upsertCropSeason(CropSeason(
        clientId: 'cs1', serverId: 'srv-cs1', plotClientId: 'p1',
        seasonCode: 'S1', syncState: SyncState.synced,
        createdAt: now, updatedAt: now));
    await seed.close();
  });

  tearDown(() async {
    if (tmp.existsSync()) await tmp.delete(recursive: true);
  });

  test('offline + token hết hạn: vào app, ghi/sửa/xoá, xem hàng đợi, KHÔNG gửi',
      () async {
    await openOffline(); // bước 2–4: token quá hạn, force-stop, mở lại offline

    expect(controller.phase, AuthPhase.authenticated);
    expect(controller.onlineSessionExpired, isTrue); // → hiện thông báo

    // gotrue đẩy lỗi mạng của lần làm mới nền lên stream: KHÔNG bị đá ra.
    auth.emitError(AuthRetryableFetchException());
    await pumpEventQueue();
    expect(controller.phase, AuthPhase.authenticated);
    expect(db.isOpen, isTrue);

    // Bước 5: tạo 3, sửa 1, xoá 1 — tất cả trên máy.
    await db.saveActivity(_act('e1'));
    await db.saveActivity(_act('e2'));
    await db.saveActivity(_act('e3'));
    await db.saveActivity(_act('e2', kg: 35)); // sửa
    await db.hardDeleteActivity('e3'); // xoá khi chưa từng gửi (như màn chi tiết)
    await co.refresh();
    expect(await db.countPendingActivities(), 2);
    expect(co.queue.map((q) => q.clientId), containsAll(['e1', 'e2']));
    expect(server.calls, 0);
    expect(auth.refreshCalls, 0); // offline: chưa thử làm mới lúc gửi
    await closeAll();
  });

  test('có mạng lại: làm mới rồi mới gửi, đúng MỘT lần, không trùng', () async {
    await openOffline();
    await db.saveActivity(_act('e1'));
    await db.saveActivity(_act('e2'));
    await co.refresh();

    auth.refreshError = null; // bước 7: máy chủ chấp nhận refresh token
    conn.debugSet(online: true, wifi: true); // bước 6
    // Cùng lúc: tín hiệu mạng + app resume + bấm tay → single-flight.
    final a = co.onAppResumed();
    final b = co.runSync(manual: true);
    await Future.wait([a, b]);
    await Future<void>.delayed(const Duration(milliseconds: 60));
    await co.runSync(manual: true); // lượt thứ hai: không còn gì để gửi

    expect(auth.refreshCalls, 1);
    expect(server.inserts, 2);
    expect(server.activities.length, 2);
    expect(await db.countPendingActivities(), 0);
    expect(controller.phase, AuthPhase.authenticated);
    expect(controller.onlineSessionExpired, isFalse); // thông báo tắt
    expect(co.status, SyncStatus.allSynced);
    await closeAll();
  });

  test('làm mới bị từ chối (khoá/thu hồi): không gửi gì, hàng đợi còn nguyên',
      () async {
    await openOffline();
    await db.saveActivity(_act('e1'));
    await db.saveActivity(_act('e2'));

    auth.refreshError = AuthApiException('User is banned',
        statusCode: '400', code: 'user_banned');
    conn.debugSet(online: true, wifi: true);
    await co.runSync(manual: true);
    await _until(() => controller.phase == AuthPhase.sessionExpired);

    expect(auth.refreshCalls, 1);
    expect(server.calls, 0); // KHÔNG một request dữ liệu nào
    expect(controller.phase, AuthPhase.sessionExpired); // phải đăng nhập lại
    expect(db.isOpen, isFalse); // đóng, KHÔNG xoá

    final reopened =
        LocalDatabase(factory: databaseFactoryFfi, directoryOverride: tmp.path);
    await reopened.openForUser(_user);
    expect(await reopened.countPendingActivities(), 2); // hàng đợi còn đủ
    await reopened.close();
    controller.dispose();
    co.dispose();
    conn.dispose();
  });

  test('mất mạng giữa chừng lúc làm mới: không gửi, vẫn ở trong app', () async {
    await openOffline();
    await db.saveActivity(_act('e1'));
    conn.debugSet(online: true, wifi: true); // báo có mạng nhưng không tới máy chủ
    await co.runSync(manual: true);
    await pumpEventQueue();

    expect(auth.refreshCalls, 1);
    expect(server.calls, 0);
    expect(controller.phase, AuthPhase.authenticated);
    expect(await db.countPendingActivities(), 1);
    await closeAll();
  });

  test('đăng xuất chủ động vẫn là đăng xuất (không phải "hết phiên")', () async {
    await openOffline();
    await controller.signOut();
    await _until(() => controller.phase == AuthPhase.signedOut);
    expect(auth.signOutCalls, 1);
    expect(controller.phase, AuthPhase.signedOut);
    controller.dispose();
    co.dispose();
    conn.dispose();
  });

  group('checkSessionFreshness', () {
    test('còn hạn → gửi, không làm mới', () async {
      var n = 0;
      expect(
          await checkSessionFreshness(
              hasSession: true, isExpired: false, refresh: () async => ++n > 0),
          SessionFreshness.fresh);
      expect(n, 0);
    });
    test('không có phiên → rejected', () async {
      expect(
          await checkSessionFreshness(
              hasSession: false, isExpired: true, refresh: () async => true),
          SessionFreshness.rejected);
    });
    test('lỗi mạng khi làm mới → offline', () async {
      for (final e in <Object>[
        AuthRetryableFetchException(),
        const SocketException('x'),
        TimeoutException('x'),
      ]) {
        expect(
            await checkSessionFreshness(
                hasSession: true, isExpired: true, refresh: () async => throw e),
            SessionFreshness.offline);
      }
    });
    test('máy chủ từ chối → rejected', () async {
      expect(
          await checkSessionFreshness(
              hasSession: true,
              isExpired: true,
              refresh: () async => throw AuthApiException('Invalid Refresh Token',
                  statusCode: '400', code: 'refresh_token_not_found')),
          SessionFreshness.rejected);
    });
  });

  group('SecureSessionStorage', () {
    const key = 'sb-proj-auth-token';
    test('phiên cũ ở SharedPreferences được chuyển sang kho bảo mật rồi xoá',
        () async {
      SharedPreferences.setMockInitialValues({key: '{"legacy":1}'});
      FlutterSecureStorage.setMockInitialValues({});
      final s = SecureSessionStorage(persistSessionKey: key);
      await s.initialize();
      expect(await s.accessToken(), '{"legacy":1}');
      expect((await SharedPreferences.getInstance()).containsKey(key), isFalse);
    });
    test('đã có trong kho bảo mật thì bản rõ chữ không đè, nhưng vẫn bị xoá',
        () async {
      SharedPreferences.setMockInitialValues({key: '{"old":1}'});
      FlutterSecureStorage.setMockInitialValues({key: '{"new":1}'});
      final s = SecureSessionStorage(persistSessionKey: key);
      await s.initialize();
      expect(await s.accessToken(), '{"new":1}');
      expect((await SharedPreferences.getInstance()).containsKey(key), isFalse);
    });
    test('ghi/đọc/xoá chỉ qua kho bảo mật', () async {
      SharedPreferences.setMockInitialValues({});
      FlutterSecureStorage.setMockInitialValues({});
      final s = SecureSessionStorage(persistSessionKey: key);
      await s.initialize();
      await s.persistSession('{"s":1}');
      expect(await s.hasAccessToken(), isTrue);
      expect((await SharedPreferences.getInstance()).getKeys(), isEmpty);
      await s.removePersistedSession();
      expect(await s.hasAccessToken(), isFalse);
    });
  });
}

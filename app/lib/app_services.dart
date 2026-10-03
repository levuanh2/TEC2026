import 'dart:async';

import 'db/local_database.dart';
import 'services/active_context.dart';
import 'services/auth_service.dart';
import 'services/carbon_api_service.dart';
import 'services/connectivity_service.dart';
import 'services/cv_inference_service.dart';
import 'services/device_service.dart';
import 'services/leaf_photo_source.dart';
import 'services/me_service.dart';
import 'services/metrics_service.dart';
import 'services/read_api.dart';
import 'services/recommendation_repository.dart';
import 'services/sync_coordinator.dart';
import 'services/sync_gateway.dart';
import 'services/sync_service.dart';
import 'shell/auth_controller.dart';
import 'shell/home_controller.dart';

/// Ném khi dọn vùng dữ liệu user cũ (đóng DB, reset service) có bước hỏng —
/// KHÔNG kèm nội dung lỗi gốc (có thể chứa dữ liệu nhạy cảm), chỉ số bước hỏng.
class AccountCleanupException implements Exception {
  const AccountCleanupException(this.failedSteps);
  final int failedSteps;

  @override
  String toString() => 'AccountCleanupException($failedSteps bước hỏng)';
}

/// Gói các service dùng chung, tạo 1 lần ở main() rồi truyền tay qua constructor.
/// Không dùng Provider/Riverpod/GetX — repo chưa có state management nào, MVP
/// không cần thêm dependency cho việc này (ponytail).
class AppServices {
  AppServices._(
    this.auth,
    this.authController,
    this.db,
    this.activeContext,
    this.devices,
    this.sync,
    this.syncCoordinator,
    this.carbonApi,
    this.me,
    this.metrics,
    this.connectivity,
    this.homeController,
    this.cvInference,
    this.leafPhotoSource,
    this.recommendations,
  );

  final AuthService auth;
  final AuthController authController;

  /// Facade ổn định — `Database` bên trong đóng/mở lại theo user (mỗi user một
  /// file). Chỉ gọi được sau khi `authController` đưa phase về `authenticated`.
  final LocalDatabase db;
  final ActiveContext activeContext;
  final DeviceService devices;
  final SyncService sync;
  final SyncCoordinator syncCoordinator;
  final CarbonApiService carbonApi;
  final MeService me;
  final MetricsService metrics;
  final ConnectivityService connectivity;
  final HomeController homeController;

  /// Điểm chạm CV (màn 24). CHƯA có model/endpoint thật → dùng
  /// [UnavailableCvInferenceService]: UI hiện "chưa cấu hình", không bịa kết quả.
  /// Khi có service thật, đổi ở [bootstrap] — UI không phải sửa.
  final CvInferenceService cvInference;

  /// Nguồn ảnh lá (máy ảnh / thư viện). Bản thật bọc image_picker +
  /// permission_handler.
  final LeafPhotoSource leafPhotoSource;

  /// Khuyến nghị điều chỉnh (module 05). OpenAPI CHƯA có endpoint → dùng
  /// [UnavailableRecommendationRepository]: UI hiện "chưa cấu hình", không bịa
  /// khuyến nghị. Cắm impl thật ở [bootstrap] khi backend thêm endpoint.
  final RecommendationRepository recommendations;

  static Future<AppServices> bootstrap() async {
    final auth = AuthService();
    final db = LocalDatabase();
    final activeContext = ActiveContext();
    final devices = DeviceService(auth.client);
    final carbonApi = CarbonApiService(auth);
    final readApi = ReadApi(() => auth.accessToken);
    final me = MeService(readApi);
    final metrics = MetricsService(readApi);
    final connectivity = ConnectivityService();
    await connectivity.start();

    final homeController = HomeController(
      me: me,
      carbon: carbonApi,
      metrics: metrics,
      db: db,
      activeContext: activeContext,
      connectivity: connectivity,
    )..attach();

    final sync = SyncService(
      SupabaseSyncGateway(auth.client),
      db,
      devices,
      onSynced: homeController.markSynced,
      isOnline: () => connectivity.isOnline,
    );

    final syncCoordinator = SyncCoordinator(
      sync: sync,
      db: db,
      connectivity: connectivity,
      // Phiên hết hạn (vd. vừa có mạng lại sau nhiều giờ offline) phải được làm
      // mới thành công rồi mới gửi bản ghi nào.
      ensureSession: auth.ensureFreshSession,
    );

    final authController = AuthController(
      auth,
      // User hoạt động: mở đúng vùng dữ liệu (file riêng của user, migration +
      // requeue bản ghi kẹt), dọn cache RAM, nạp lại ActiveContext, nạp Home.
      // Ném ra ngoài nếu bước quan trọng (mở DB) hỏng → AuthController KHÔNG vào
      // shell.
      onUserActive: (userId) async {
        await db.openForUser(userId);
        sync.clearCache();
        devices.reset();
        await activeContext.attach(db);
        await syncCoordinator.attach();
        // Còn mật khẩu tạm: máy chủ từ chối mọi dữ liệu — hoãn tải Trang chủ và
        // tự gửi tới khi đổi xong (onTemporaryPasswordReplaced).
        if (auth.mustChangePassword) return;
        await homeController.load();
        // Tự gửi sau đăng nhập — chạy nền, KHÔNG chặn việc vào shell.
        unawaited(syncCoordinator.onLogin());
      },
      onTemporaryPasswordReplaced: () async {
        await homeController.load();
        unawaited(syncCoordinator.onLogin());
      },
      // Mất user (đăng xuất / hết phiên / đổi tài khoản): dọn RAM + đóng DB.
      // KHÔNG xoá file — đăng nhập lại phải còn dữ liệu cũ và pending data.
      // Best-effort TỪNG service, nhưng nếu bất kỳ bước nào hỏng thì NÉM để
      // AuthController biết vùng dữ liệu chưa chắc đã đóng an toàn.
      onUserInactive: () async {
        final failures = <Object>[];
        void step(void Function() fn) {
          try {
            fn();
          } catch (e) {
            failures.add(e);
          }
        }

        step(homeController.resetForSignOut);
        step(syncCoordinator.detach);
        step(activeContext.detach);
        step(sync.clearCache);
        step(devices.reset);
        try {
          await db.close();
        } catch (e) {
          failures.add(e);
        }
        if (failures.isNotEmpty) {
          throw AccountCleanupException(failures.length);
        }
      },
    )..start();

    return AppServices._(
      auth,
      authController,
      db,
      activeContext,
      devices,
      sync,
      syncCoordinator,
      carbonApi,
      me,
      metrics,
      connectivity,
      homeController,
      const UnavailableCvInferenceService(),
      ImagePickerLeafPhotoSource(),
      const UnavailableRecommendationRepository(),
    );
  }
}

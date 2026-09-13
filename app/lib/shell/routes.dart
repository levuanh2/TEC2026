import 'package:flutter/material.dart';

import '../app_services.dart';
import '../models/activity.dart' show kActivityTypes;
import '../models/crop_season.dart';
import '../models/plot.dart';
import '../screens/activity_form_screen.dart';
import '../screens/camera_cv_screen.dart';
import '../screens/carbon_result_screen.dart';
import '../screens/crop_season_form_screen.dart';
import '../screens/farm_screen.dart';
import '../screens/help_screen.dart';
import '../screens/personal_info_screen.dart';
import '../screens/reset_password_screen.dart';
import '../screens/resource_dashboard_screen.dart';
import '../screens/sync_settings_screen.dart';
import '../services/carbon_cache.dart';
import '../services/cv_feedback_store.dart';
import '../services/metrics_cache.dart';

/// Điều hướng tới các màn "route phụ" — không nằm trong 4 tab của shell, được
/// push chồng lên bằng [Navigator]. Gom về một chỗ để screen không import chéo
/// lẫn nhau lung tung.
///
/// Farm → Plot → Crop Season → Activity form / Carbon result là chuỗi màn đã có
/// sẵn (`screens/`), sẽ được dựng lại theo SVG ở các bước sau; ở đây chỉ mở
/// điểm vào.
class AppRoutes {
  const AppRoutes._();

  static Future<void> openFarms(BuildContext context, AppServices services) {
    return Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => FarmScreen(services: services)),
    );
  }

  /// [cropSeasonClientId] = `crop_seasons.client_id` (ổn định). Màn tự đọc
  /// `server_id` + tiền điều kiện từ DB — KHÔNG truyền local UUID vào API.
  static Future<void> openCarbonResult(
    BuildContext context,
    AppServices services, {
    required String cropSeasonClientId,
    VoidCallback? onOpenSync,
  }) {
    return Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => CarbonResultScreen(
          carbonApi: services.carbonApi,
          cache: CarbonCache(services.db),
          db: services.db,
          cropSeasonClientId: cropSeasonClientId,
          onOpenSync: onOpenSync,
        ),
      ),
    );
  }

  /// Điểm chạm CV (màn 24). Ảnh gắn với vụ đang canh tác (đọc từ
  /// [AppServices.activeContext]). [CvInferenceService] hiện là
  /// `UnavailableCvInferenceService` — thay ở [AppServices.bootstrap] khi có
  /// model/endpoint thật, màn không phải sửa.
  /// Màn "Hiệu quả tài nguyên" của vụ ([cropSeasonClientId] = client id ổn
  /// định; màn tự tra `server_id` + tiền điều kiện từ DB — KHÔNG truyền local
  /// UUID vào API).
  static Future<void> openResourceDashboard(
    BuildContext context,
    AppServices services, {
    required String cropSeasonClientId,
    VoidCallback? onOpenSync,
  }) {
    return Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ResourceDashboardScreen(
          metricsApi: services.metrics,
          cache: MetricsCache(services.db),
          recommendations: services.recommendations,
          db: services.db,
          cropSeasonClientId: cropSeasonClientId,
          onOpenSync: onOpenSync,
        ),
      ),
    );
  }

  static Future<void> openCameraCv(BuildContext context, AppServices services) {
    final ctx = services.activeContext;
    return Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => CameraCvScreen(
          inference: services.cvInference,
          photoSource: services.leafPhotoSource,
          feedbackStore: CvFeedbackStore(services.db),
          cropSeason: ctx.cropSeason,
          plotLabel: ctx.plot?.name ?? ctx.plot?.plotCode,
        ),
      ),
    );
  }

  static Future<void> openActivityForm(
    BuildContext context,
    AppServices services, {
    required String cropSeasonClientId,
    required String activityType,
  }) {
    // Phòng vệ: KHÔNG bao giờ mở form ghi hoạt động với loại ngoài 7 enum
    // (`__cv__` và mọi sentinel khác). Debug thì assert; production thì không
    // điều hướng (không tạo Activity rác không đồng bộ được).
    assert(
      kActivityTypes.contains(activityType),
      'activityType không hợp lệ: "$activityType" — không thuộc kActivityTypes',
    );
    if (!kActivityTypes.contains(activityType)) return Future<void>.value();
    return Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ActivityFormScreen(
          services: services,
          cropSeasonId: cropSeasonClientId,
          activityType: activityType,
        ),
      ),
    );
  }

  static Future<CropSeason?> openCropSeasonForm(
    BuildContext context,
    AppServices services, {
    required Plot plot,
    CropSeason? existing,
  }) {
    return Navigator.of(context).push<CropSeason>(
      MaterialPageRoute(
        builder: (_) => CropSeasonFormScreen(
          services: services,
          plot: plot,
          existing: existing,
        ),
      ),
    );
  }

  static Future<void> openPersonalInfo(
    BuildContext context,
    AppServices services,
  ) {
    return Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => PersonalInfoScreen(services: services)),
    );
  }

  static Future<void> openSyncSettings(
    BuildContext context,
    AppServices services,
  ) {
    return Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) =>
            SyncSettingsScreen(coordinator: services.syncCoordinator),
      ),
    );
  }

  /// "Đổi mật khẩu" từ màn Tài khoản — dùng lại [ResetPasswordScreen] nhưng gọi
  /// `updatePassword` trên phiên hiện tại (Supabase `auth.updateUser`), KHÔNG
  /// qua email. Là Supabase Auth hợp lệ; không tự tạo endpoint.
  static Future<void> openChangePassword(
    BuildContext context,
    AppServices services,
  ) {
    final navigator = Navigator.of(context);
    return navigator.push(
      MaterialPageRoute(
        builder: (_) => ResetPasswordScreen(
          title: 'Đổi mật khẩu',
          showBackButton: true,
          onSubmit: services.authController.updatePassword,
          onDone: () => navigator.maybePop(),
        ),
      ),
    );
  }

  static Future<void> openHelp(BuildContext context) {
    return Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const HelpScreen()),
    );
  }
}

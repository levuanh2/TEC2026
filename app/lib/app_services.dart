import 'db/local_database.dart';
import 'services/auth_service.dart';
import 'services/carbon_api_service.dart';
import 'services/device_service.dart';
import 'services/sync_service.dart';

/// Gói các service dùng chung, tạo 1 lần ở main() rồi truyền tay qua constructor.
/// Không dùng Provider/Riverpod/GetX — repo chưa có state management nào, MVP
/// không cần thêm dependency cho việc này (ponytail).
class AppServices {
  AppServices._(this.auth, this.db, this.devices, this.sync, this.carbonApi);

  final AuthService auth;
  final LocalDatabase db;
  final DeviceService devices;
  final SyncService sync;
  final CarbonApiService carbonApi;

  static Future<AppServices> bootstrap() async {
    final auth = AuthService();
    final db = await LocalDatabase.open();
    final devices = DeviceService(auth.client);
    final sync = SyncService(auth.client, db, devices);
    final carbonApi = CarbonApiService(auth);
    return AppServices._(auth, db, devices, sync, carbonApi);
  }
}

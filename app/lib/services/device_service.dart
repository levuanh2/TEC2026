import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:uuid/uuid.dart';

const _kInstallationIdKey = 'agricarbon_installation_id';
final _kUuid = Uuid();

/// Định danh thiết bị ổn định qua các lần mở app (FR-1a-07 cần device_id để
/// khử trùng lặp khi đồng bộ) + đăng ký/lấy `devices.id` thật trên Supabase.
///
/// Không dùng device_info_plus — không cần biết đây là máy gì, chỉ cần 1 UUID
/// không đổi. Bớt một dependency (ponytail).
class DeviceService {
  DeviceService(this._client);
  final SupabaseClient _client;

  String? _installationId;
  String? _serverDeviceId;

  Future<String> _installationIdFor() async {
    if (_installationId != null) return _installationId!;
    final prefs = await SharedPreferences.getInstance();
    var id = prefs.getString(_kInstallationIdKey);
    if (id == null) {
      id = _kUuid.v4();
      await prefs.setString(_kInstallationIdKey, id);
    }
    _installationId = id;
    return id;
  }

  /// Trả về `devices.id` thật trên Supabase — tạo mới nếu chưa có, idempotent
  /// qua unique constraint `installation_id`. Cần mạng; gọi khi online (lúc
  /// đồng bộ), không chặn việc nhập liệu offline.
  Future<String> ensureServerDeviceId() async {
    if (_serverDeviceId != null) return _serverDeviceId!;
    final installationId = await _installationIdFor();
    final row = await _client
        .from('devices')
        .upsert(
          {
            'user_id': _client.auth.currentUser!.id,
            'installation_id': installationId,
            'platform': 'flutter',
          },
          onConflict: 'installation_id',
        )
        .select('id')
        .single();
    _serverDeviceId = row['id'] as String;
    return _serverDeviceId!;
  }
}

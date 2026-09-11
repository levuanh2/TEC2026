import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:uuid/uuid.dart';

const _kDeviceSeedKey = 'agricarbon_device_seed';
// Khoá cũ (trước khi tách installation_id theo user) — nếu có thì tái dùng làm
// seed để seed không đổi qua lần nâng cấp.
const _kLegacyInstallationKey = 'agricarbon_installation_id';
final _kUuid = Uuid();

/// Namespace UUID chuẩn (RFC 4122 "URL") — chỉ để sinh `installation_id` v5
/// tất định, KHÔNG phải secret.
const _kInstallationNamespace = '6ba7b811-9dad-11d1-80b4-00c04fd430c8';

/// Định danh thiết bị ổn định qua các lần mở app (FR-1a-07 cần device_id để
/// khử trùng lặp khi đồng bộ) + đăng ký/lấy `devices.id` thật trên Supabase.
///
/// **`installation_id` sinh THEO TỪNG USER** (`uuidv5(seed_thiết_bị + user_id)`).
/// Lý do: `public.devices.installation_id` là `unique` toàn bảng và RLS chỉ cho
/// user thao tác `devices` row của chính mình — nếu dùng chung 1 `installation_id`
/// cho cả máy thì khi user B đăng nhập trên máy user A đã đăng ký, upsert của B
/// đụng row của A → 23505 / RLS-denied → B KHÔNG lấy được `device_id` → không
/// đồng bộ được. Mỗi user một `installation_id` v5 tất định (không đổi qua các
/// lần mở app, không cần thêm dependency device_info).
class DeviceService {
  DeviceService(this._client);

  /// Chỉ dùng trong test: đặt sẵn `devices.id` giả, KHÔNG chạm Supabase.
  DeviceService.fixed(String serverDeviceId)
      : _client = null,
        _serverDeviceId = serverDeviceId;

  final SupabaseClient? _client;

  String? _deviceSeed;
  String? _serverDeviceId;

  /// Quên `devices.id` đã resolve cho user trước — gọi khi đổi tài khoản.
  /// GIỮ seed thiết bị (thuộc máy); `installation_id` của user mới sẽ được sinh
  /// lại từ seed đó + id user mới.
  void reset() => _serverDeviceId = null;

  /// `installation_id` (UUID) tất định cho cặp (thiết bị, user). Public + tĩnh
  /// để test kiểm chứng tính tất định / phân tách theo user mà không cần Supabase.
  @visibleForTesting
  static String installationIdFor({
    required String deviceSeed,
    required String userId,
  }) =>
      _kUuid.v5(_kInstallationNamespace, '$deviceSeed:$userId');

  Future<String> _deviceSeedValue() async {
    if (_deviceSeed != null) return _deviceSeed!;
    final prefs = await SharedPreferences.getInstance();
    final seed = prefs.getString(_kDeviceSeedKey) ??
        prefs.getString(_kLegacyInstallationKey) ??
        _kUuid.v4();
    await prefs.setString(_kDeviceSeedKey, seed);
    _deviceSeed = seed;
    return seed;
  }

  /// Trả về `devices.id` thật trên Supabase cho USER hiện tại — tạo mới nếu chưa
  /// có, idempotent qua unique constraint `installation_id`. Cần mạng; gọi khi
  /// online (lúc đồng bộ), không chặn việc nhập liệu offline.
  Future<String> ensureServerDeviceId() async {
    if (_serverDeviceId != null) return _serverDeviceId!;
    final client = _client;
    if (client == null) {
      throw StateError('DeviceService.fixed không gọi được Supabase');
    }
    final userId = client.auth.currentUser!.id;
    final installationId = installationIdFor(
      deviceSeed: await _deviceSeedValue(),
      userId: userId,
    );
    final row = await client
        .from('devices')
        .upsert(
          {
            'user_id': userId,
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

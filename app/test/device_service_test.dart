import 'package:agricarbon_app/services/device_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const seed = '11111111-2222-3333-4444-555555555555';

  test('installation_id tất định theo (thiết bị, user)', () {
    final a1 =
        DeviceService.installationIdFor(deviceSeed: seed, userId: 'user-A');
    final a2 =
        DeviceService.installationIdFor(deviceSeed: seed, userId: 'user-A');
    expect(a1, a2); // cùng cặp -> cùng id, ổn định qua các lần mở app
  });

  test(
      'user khác trên cùng máy -> installation_id KHÁC (tránh đụng unique/RLS)',
      () {
    final a =
        DeviceService.installationIdFor(deviceSeed: seed, userId: 'user-A');
    final b =
        DeviceService.installationIdFor(deviceSeed: seed, userId: 'user-B');
    expect(a, isNot(b));
  });

  test('máy khác cùng user -> installation_id KHÁC', () {
    final s1 =
        DeviceService.installationIdFor(deviceSeed: seed, userId: 'user-A');
    final s2 = DeviceService.installationIdFor(
        deviceSeed: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', userId: 'user-A');
    expect(s1, isNot(s2));
  });

  test('kết quả là UUID hợp lệ', () {
    final id =
        DeviceService.installationIdFor(deviceSeed: seed, userId: 'user-A');
    expect(
      RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
          .hasMatch(id),
      isTrue,
      reason: id,
    );
  });
}

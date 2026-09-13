import 'dart:io';

import 'package:agricarbon_app/config.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('redirect URL đúng dạng custom scheme cố định', () {
    expect(AppConfig.resetPasswordRedirect,
        'vn.agricarbon.mobile://reset-password');
    final uri = Uri.parse(AppConfig.resetPasswordRedirect);
    expect(uri.scheme, 'vn.agricarbon.mobile');
    expect(uri.host, 'reset-password');
  });

  test('AndroidManifest khai đúng intent-filter deep link, khớp config', () {
    final xml =
        File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
    final uri = Uri.parse(AppConfig.resetPasswordRedirect);
    expect(xml, contains('android.intent.action.VIEW'));
    expect(xml, contains('android.intent.category.BROWSABLE'));
    expect(xml, contains('android:scheme="${uri.scheme}"'));
    expect(xml, contains('android:host="${uri.host}"'));
    // KHÔNG mở cleartext / không thêm exported component mới.
    expect(xml.contains('android:usesCleartextTraffic="true"'), isFalse);
  });

  test('iOS Info.plist khai CFBundleURLSchemes khớp config', () {
    final plist = File('ios/Runner/Info.plist').readAsStringSync();
    final scheme = Uri.parse(AppConfig.resetPasswordRedirect).scheme;
    expect(plist, contains('CFBundleURLTypes'));
    expect(plist, contains('CFBundleURLSchemes'));
    expect(plist, contains('<string>$scheme</string>'));
    // Màn 24 (CV): quyền máy ảnh + thư viện ảnh đã khai kèm mô tả lý do —
    // iOS crash khi mở nếu thiếu (xem lib/screens/camera_cv_screen.dart).
    expect(plist, contains('NSCameraUsageDescription'));
    expect(plist, contains('NSPhotoLibraryUsageDescription'));
  });

  test('bundle identifier vn.agricarbon.mobile (Android + iOS)', () {
    final gradle = File('android/app/build.gradle.kts').existsSync()
        ? File('android/app/build.gradle.kts').readAsStringSync()
        : File('android/app/build.gradle').readAsStringSync();
    expect(gradle, contains('vn.agricarbon.mobile'));

    final pbx = File('ios/Runner.xcodeproj/project.pbxproj').readAsStringSync();
    expect(pbx, contains('vn.agricarbon.mobile'));
  });
}

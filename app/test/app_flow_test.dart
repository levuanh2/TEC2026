// Luồng nghiệm thu đầu-cuối chạy DƯỚI `flutter test` (headless) để CI luôn kiểm
// được, kể cả khi máy không có emulator/device.
//
// Biến thể chạy trên nền tảng thật: `flutter test integration_test/app_flow_test.dart
// -d <device>` — cùng logic (test/support/full_flow.dart).
import 'package:flutter_test/flutter_test.dart';

import 'support/full_flow.dart';

void main() {
  test(
    'nghiệm thu: offline nhập liệu → restart → sync đúng số (idempotent) → '
    'carbon → missing yield → logout → đổi user isolation',
    runAcceptanceFlow,
    timeout: const Timeout(Duration(minutes: 3)),
  );
}

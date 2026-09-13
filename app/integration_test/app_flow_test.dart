// Nghiệm thu luồng đầu-cuối phía mobile — biến thể chạy trên NỀN TẢNG THẬT.
//
// Chạy: `flutter test integration_test/app_flow_test.dart -d <android|ios device>`
//   (cần emulator/thiết bị). Không có device → dùng `flutter test test/app_flow_test.dart`
//   (headless, CÙNG logic ở test/support/full_flow.dart).
//
// KHÔNG service-role key, KHÔNG chạm Supabase/hosted (mạng là fake). E2E hosted
// là bước riêng — chỉ chạy khi có test configuration + test account (xem README).

import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/support/full_flow.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets(
    'nghiệm thu: offline nhập liệu → restart → sync đúng số (idempotent) → '
    'carbon → missing yield → logout → đổi user isolation',
    (tester) async {
      await tester.runAsync(runAcceptanceFlow);
    },
  );
}

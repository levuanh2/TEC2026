# app/ — Mobile App ghi nhật ký canh tác

- **Lớp MVP:** 1a (Walking Skeleton) — đường găng.
- **Phụ trách:** Người A.
- **Đặc tả:** [`../docs/modules/01-mobile-app.md`](../docs/modules/01-mobile-app.md) ·
  [`../docs/BACKEND_1A.md`](../docs/BACKEND_1A.md) (API contract, auth/RLS)

## Trạng thái verify (cập nhật 2026-09-10 — lượt bàn giao: tombstone/RLS + race 23505 + Home lifecycle)

| Bước | Kết quả |
|---|---|
| `flutter pub get` | ✅ |
| `dart format --output=none --set-exit-if-changed lib test integration_test` | ✅ sạch |
| `flutter analyze` | ✅ **No issues found** |
| `flutter test` | ✅ **342/342 pass** (unit + widget headless + luồng nghiệm thu `test/app_flow_test.dart`) |
| `flutter test integration_test/` | ⏸️ **skipped-by-environment** — cần Android/iOS device hoặc emulator (máy CI hiện chỉ có Windows desktop, project không mở nền tảng đó). Cùng logic đã chạy headless qua `test/app_flow_test.dart`. |
| `flutter build apk --debug` (dart-define giả) | ✅ ra `app-debug.apk` |
| `flutter build apk --release` (dart-define giả) | ✅ ra `app-release.apk` |
| `flutter build appbundle --release` (dart-define giả) | ✅ ra `app-release.aab` |
| Build iOS | ⏸️ **cần macOS + Xcode + signing** — không build được trên Windows; `ios/` có cấu hình tĩnh hợp lệ (xem §Build iOS). Lệnh chốt: `flutter build ios --release`. |

Màn đã dựng theo SVG với dữ liệu THẬT: **Đăng nhập** (SVG 20), **Trang chủ**
(SVG 21), **Ghi nhanh** (SVG 22 + CRUD Activity), **Gửi dữ liệu** (SVG 23 +
auto-sync + cài đặt Wi-Fi), **Kiểm tra ảnh lá lúa** (SVG 24 — điểm chạm CV),
**Kết quả phát thải** (SVG 25), **Tài khoản** (SVG 26 — hồ sơ `/v1/me` +
đổi mật khẩu + trợ giúp + đăng xuất). Ngoài SVG: **Hiệu quả tài nguyên**
(module 04). Tất cả 7 SVG đã dựng — không còn màn nào ở dạng khung.

Scaffold `android/` + `ios/` tạo bằng `flutter create . --org vn.agricarbon
--project-name mobile --platforms=android,ios`; `applicationId` / bundle id =
`vn.agricarbon.mobile`. `lib/` và `test/` viết tay được giữ nguyên.

**Chưa verify trên thiết bị/emulator thật và chưa verify với Supabase/backend
hosted** — xem §Nghiệm thu để biết phần nào đã xong phía mobile, phần nào chờ
backend / ML / cấu hình hệ thống.

## Kiến trúc

```text
Flutter
  │
  ├─► supabase_flutter (publishable key) ──► Supabase trực tiếp
  │     - Auth (đăng nhập, giữ session/token)       ↑ RLS quyết định quyền,
  │     - Đọc Farm/Plot/CropSeason (cache local)     giống hệt backend
  │     - Ghi Plot/CropSeason/Activity khi đồng bộ   (docs/BACKEND_1A.md §10)
  │
  └─► http (JWT của session) ──► FastAPI backend
        - CHỈ để tính CO2e: POST /v1/carbon/calculate, GET .../carbon
```

**Quyết định kiến trúc quan trọng — khác với đề bài gốc:** task gốc giả định có sẵn
`POST /v1/sync` trên FastAPI. Endpoint đó **không tồn tại** trong `backend/` hiện tại
(chỉ có `/v1/carbon/*` và `/health`). Baseline schema đã có sẵn đúng cơ chế cho việc
này: RLS insert policy cho `authenticated` trên `activities` + 7 bảng chi tiết, và
unique index `(device_id, client_event_id)` — thiết kế sẵn cho ghi trực tiếp, idempotent
từ client. Nên: **app ghi thẳng vào Supabase qua RLS**, không qua một endpoint sync
riêng của backend. Backend chỉ giữ đúng một việc nó có: Carbon Engine. Xem
`lib/services/sync_service.dart` để hiểu chi tiết.

## Biến môi trường (--dart-define)

Không dùng file `.env` (đỡ 1 dependency `flutter_dotenv`) — truyền lúc build/run:

```bash
flutter run \
  --dart-define=SUPABASE_URL=https://awazhdqzkktekbwaqiic.supabase.co \
  --dart-define=SUPABASE_PUBLISHABLE_KEY=<publishable key, KHÔNG phải service role> \
  --dart-define=BACKEND_BASE_URL=http://10.0.2.2:8000
```

`BACKEND_BASE_URL`: `10.0.2.2` là địa chỉ loopback máy host khi chạy Android emulator
(không phải `localhost`/`127.0.0.1` — bên trong emulator đó là chính nó). Trên thiết bị
thật hoặc production, dùng URL server backend thật.

**Không có `SUPABASE_SERVICE_ROLE_KEY` ở đây, và sẽ không bao giờ có** — publishable
key an toàn để đưa vào app, RLS là ranh giới quyền thật (giống `web-dashboard/`).

## Build

### Android

```bash
cd app
flutter build apk --debug \
  --dart-define=SUPABASE_URL=... \
  --dart-define=SUPABASE_PUBLISHABLE_KEY=... \
  --dart-define=BACKEND_BASE_URL=http://10.0.2.2:8000
```

- Quyền `INTERNET` khai ở `android/app/src/main/AndroidManifest.xml` (release
  cũng cần vì gọi Supabase/backend thật).
- **HTTP cleartext**: bản release/profile chặn hoàn toàn
  (`src/main/res/xml/network_security_config.xml`). Chỉ **debug** cho phép
  cleartext tới `10.0.2.2` / `localhost` / `127.0.0.1`
  (`src/debug/res/xml/network_security_config.xml`) để gọi backend local.
- `android/gradle.properties` đặt `kotlin.incremental=false` — né lỗi
  "Could not close incremental caches" của Kotlin 2.x Build Tools API trên
  Windows. Không ảnh hưởng hành vi app.

### iOS (chạy trên macOS)

**Máy Windows KHÔNG build được iOS** — không có bước nào ở trên "giả" thành công
trên Windows. `ios/` chỉ được kiểm **tĩnh** (Info.plist, Podfile, project.pbxproj,
entitlements). Để xác nhận cuối cần **macOS + Xcode + Apple signing**:

```bash
cd app
flutter pub get                       # sinh ios/Flutter/Generated.xcconfig
cd ios && pod install && cd ..        # sinh Podfile.lock + Pods/ (cần macro permission_handler ở Podfile)
# Kiểm tra không cần ký:
flutter build ios --debug --no-codesign \
  --dart-define=SUPABASE_URL=... \
  --dart-define=SUPABASE_PUBLISHABLE_KEY=... \
  --dart-define=BACKEND_BASE_URL=<URL backend thật, HTTPS>
# Bản phát hành (cần Development Team + provisioning profile trong Xcode):
flutter build ios --release \
  --dart-define=SUPABASE_URL=... \
  --dart-define=SUPABASE_PUBLISHABLE_KEY=... \
  --dart-define=BACKEND_BASE_URL=<URL backend thật, HTTPS>
```

- Bundle id: `vn.agricarbon.mobile` (`ios/Runner.xcodeproj/project.pbxproj`).
  Tên hiển thị: `AgriCarbon` (`ios/Runner/Info.plist` — `CFBundleDisplayName`).
- Chưa thêm ngoại lệ ATS nào (App Transport Security giữ mặc định = chỉ HTTPS).
  Backend production phải là HTTPS.
- Quyền camera/thư viện ảnh: `NSCameraUsageDescription` +
  `NSPhotoLibraryUsageDescription` đã thêm (`ios/Runner/Info.plist`), kèm
  `ios/Podfile` bật macro `PERMISSION_CAMERA=1` / `PERMISSION_PHOTOS=1` cho
  `permission_handler` (thiếu block này thì mọi quyền trả `denied`). Android:
  `CAMERA` + `uses-feature camera required="false"` trong `AndroidManifest.xml`;
  thư viện ảnh dùng Photo Picker hệ thống nên KHÔNG khai `READ_MEDIA_IMAGES`.
- Cần đặt Development Team trong Xcode (Signing & Capabilities) để chạy trên
  thiết bị thật.

## Cấu trúc

```text
app/
├── lib/
│   ├── main.dart                     # runZonedGuarded: guard cấu hình → init → AuthGate;
│   │                                 #   không nhánh nào ném trước runApp
│   ├── config.dart                   # --dart-define + canInitSupabase / missingKeys
│   ├── app_services.dart             # gói service dùng chung (không Provider/Riverpod)
│   ├── design/                       # Design System (Prompt 1) — token + theme + component
│   │   ├── design.dart               # barrel export duy nhất
│   │   ├── tokens.dart               # màu/spacing/radius/breakpoint từ SVG
│   │   ├── theme.dart                # AgriCarbonTheme.light() — Material 3
│   │   ├── app_format.dart           # định dạng ngày/số kiểu VN, không phụ thuộc locale máy
│   │   └── components/               # AppScaffold, AppHeader, AppBottomNavigation,
│   │                                 #   Primary/SecondaryButton, AppCard, StatusBadge,
│   │                                 #   Loading/Empty/ErrorState, OfflineBanner,
│   │                                 #   ConfirmationDialog, AdaptiveFormField, MetricCard
│   ├── shell/                        # App shell
│   │   ├── auth_controller.dart      # máy trạng thái phiên (6 phase) + dọn cache khi đổi user
│   │   ├── auth_gate.dart            # ListenableBuilder theo AuthPhase → splash | Login | HomeShell | error
│   │   ├── home_shell.dart           # IndexedStack 4 tab + AppBottomNavigation + Android back; implements HomeActions
│   │   ├── home_controller.dart      # ChangeNotifier điều phối dữ liệu Trang chủ (9 state), cache, không gọi mạng khi rebuild
│   │   ├── home_actions.dart         # interface điều hướng của Trang chủ (test được)
│   │   ├── routes.dart               # mở các route phụ (Farm/CV/Carbon/Activity form/Crop season form/...)
│   │   └── tabs/                     # home_tab (SVG 21, dữ liệu thật) · quick_log/sync/account (khung)
│   ├── models/
│   │   ├── farm.dart, plot.dart, crop_season.dart
│   │   ├── activity.dart             # SyncState ngay trên activity — không bảng riêng
│   │   ├── activity_field_spec.dart  # đặc tả field cho 7 loại hoạt động
│   │   └── carbon_result.dart        # parse response backend
│   ├── db/
│   │   └── local_database.dart       # SQLite: farms/plots/crop_seasons/activities
│   ├── services/
│   │   ├── auth_service.dart         # bọc Supabase Auth + Stream<AuthSignal> đã làm phẳng
│   │   ├── auth_actions.dart         # interface hẹp (signIn/sendPasswordReset) cho màn login test được
│   │   ├── auth_errors.dart          # dịch lỗi auth sang tiếng Việt + validate email
│   │   ├── device_service.dart       # installation_id ổn định + devices.id thật (reset() khi đổi user)
│   │   ├── sync_service.dart         # đẩy pending lên Supabase, idempotent (clearCache() khi đổi user)
│   │   ├── carbon_api_service.dart   # gọi FastAPI /v1/carbon/* (giải mã UTF-8, error contract nested)
│   │   ├── read_api.dart             # client mỏng cho GET /v1/* (Bearer + UTF-8 + error contract)
│   │   ├── me_service.dart           # GET /v1/me → full_name + roles thật
│   │   ├── connectivity_service.dart # trạng thái online/offline THẬT (connectivity_plus, stream)
│   │   ├── active_context.dart       # Farm/Plot/Crop Season đang chọn (per-user)
│   │   └── sync_errors.dart          # phân loại lỗi sync (RLS / network / duplicate ...)
│   └── screens/
│       ├── login_screen.dart              # SVG 20 — email only (không giả vờ hỗ trợ SĐT)
│       ├── forgot_password_screen.dart    # flow reset chuẩn Supabase, thông báo trung tính
│       ├── configuration_error_screen.dart # thiếu --dart-define → liệt kê TÊN biến (không giá trị)
│       ├── bootstrap_error_screen.dart    # init thất bại → màn lỗi chung (không lộ chi tiết)
│       ├── farm_screen.dart, plot_screen.dart, crop_season_screen.dart
│       ├── crop_season_detail_screen.dart  # hàng đợi + 7 chip ghi hoạt động + danh sách + Xem CO₂e
│       ├── activity_form.dart              # widget form động (7 loại) — validate + lưu offline transactional
│       ├── activity_form_screen.dart       # bọc ActivityForm trong AppScaffold (ghi/sửa)
│       ├── activity_detail_screen.dart     # xem 1 hoạt động + Sửa / Xoá (tombstone nếu đã đồng bộ)
│       ├── activity_type_sheet.dart        # bottom sheet "Xem tất cả" 7 loại (icon Material)
│       ├── carbon_result_screen.dart
│       ├── camera_cv_screen.dart           # SVG 24 — chụp/chọn ảnh + quyền + hợp đồng CV (model chưa có → "chưa cấu hình")
│       ├── resource_dashboard_screen.dart  # module 04 — 4 chỉ số/kg + so sánh + khuyến nghị (recommendation chưa có endpoint)
│       ├── personal_info_screen.dart       # khung — sẽ nối /v1/me
│       └── sync_settings_screen.dart       # khung
└── test/                                 # 314 test — unit thuần + widget test headless (flutter_test)
    ├── main_bootstrap_test.dart      # preInitApp: thiếu BACKEND_BASE_URL vẫn ra màn cấu hình; handler zone
    ├── auth_controller_test.dart     # 6 phase, restore, login, hết phiên, logout, đổi user, dispose,
    │                                 #   mở-DB-lỗi→error, tín hiệu phiên trùng, passwordRecovery
    ├── auth_errors_test.dart         # map lỗi tiếng Việt (không lộ mã lỗi), validate email
    ├── config_test.dart              # thiếu cấu hình không crash + ConfigurationErrorScreen
    ├── login_screen_test.dart        # email/password validate, chống double-submit, submit bàn phím, quên MK
    ├── reset_password_screen_test.dart  # đặt mật khẩu mới: validate, khớp, lỗi không lộ exception thô
    ├── home_controller_test.dart     # 9 state, null≠0, đổi context, load 1 lần, mất/khôi phục mạng
    ├── local_database_test.dart      # offline + sync state + migration + reconcile pull (sqflite_common_ffi)
    ├── sync_errors_test.dart         # phân loại RLS / mạng / trùng khoá; message không kèm exception thô
    ├── active_context_test.dart      # Farm⊃Plot⊃Season, revalidate, tách theo user
    ├── activity_*_test.dart          # field spec khớp cột thật, validate biên, form lưu offline, persistence
    ├── crop_season_test.dart / plot_test.dart  # round-trip + validation phương pháp luận
    ├── activity_model_test.dart      # round-trip payload, client_event_id ổn định
    ├── carbon_api_service_test.dart  # serialize request, map lỗi, 2 loại 404 KHÔNG gộp
    ├── carbon_result_parsing_test.dart  # co2e_per_kg=null KHÔNG phải 0
    └── no_figma_placeholders_test.dart  # lib/ không chứa số/chuỗi minh hoạ từ SVG
```

> **Điều hướng:** `AuthGate` là màn gốc. Sau đăng nhập là `HomeShell` với 4 tab
> (Trang chủ · Ghi nhanh · Gửi dữ liệu · Tài khoản) trong `IndexedStack` (giữ
> state khi đổi tab). Chuỗi màn phân cấp Farm → Plot → Crop Season → form /
> carbon result là **route phụ** push chồng lên shell, chưa dựng lại theo SVG.

## Đăng nhập & vòng đời phiên (Prompt 2)

`AuthController` (`shell/auth_controller.dart`) là **một nguồn sự thật** cho auth —
`ChangeNotifier` nghe `AuthService.signals` (đã làm phẳng khỏi kiểu gotrue). 6 phase:

| Phase | Nghĩa | `AuthGate` hiện |
|---|---|---|
| `initializing` / `restoringSession` | chưa/đang khôi phục phiên | splash |
| `authenticated` | có phiên | `HomeShell` |
| `signedOut` | chưa đăng nhập **hoặc** vừa bấm đăng xuất | `LoginScreen` |
| `sessionExpired` | mất phiên KHÔNG do người dùng | `LoginScreen` + banner |
| `error` | lỗi stream auth | màn lỗi + "Thử lại" |

- **Phân biệt đăng xuất chủ động vs hết phiên**: `AuthController.signOut()` bật cờ
  `_userRequestedSignOut` trước khi gọi Supabase; tín hiệu `signedOut` kế tiếp có cờ
  → `signedOut`, không cờ → `sessionExpired`. `AccountTab` gọi qua `authController`,
  KHÔNG gọi thẳng `auth.signOut()`.
- **Đổi tài khoản A→B** (kể cả khi stream phát thẳng `signedIn`/`tokenRefreshed`
  cho B mà không có `signedOut`): `AuthController._switchTo` chạy đúng trình tự —
  `restoringSession` → **dọn HẲN A trước** (`onUserInactive`: reset Home +
  `_loadedOnce`, detach ActiveContext, `sync.clearCache()`, `devices.reset()`,
  **đóng DB A**) → CHỈ KHI dọn xong mới mở DB B + `onUserActive(B)`.
  `_currentUserId` KHÔNG đặt bằng id B trước khi `onUserActive` xong. Mỗi user một
  FILE SQLite riêng (KHÔNG xoá file khi đăng xuất). `installation_id` giữ nguyên
  (thuộc thiết bị).
- **Cleanup A thất bại HOẶC kích hoạt B thất bại** → `AuthPhase.error` (màn "Thử
  lại"), KHÔNG vào shell, KHÔNG giữ `_currentUserId` sai, KHÔNG để màn hình truy
  cập DB user cũ. `onUserInactive` chạy best-effort TỪNG service nhưng nếu bước
  nào hỏng thì ném `AccountCleanupException` (chỉ số bước hỏng, không kèm nội
  dung lỗi) để `AuthController` biết mà không authenticate B.
- **Đăng xuất** vẫn về Login NGAY kể cả khi cleanup lỗi (không kẹt ở `error`) —
  lần đăng nhập kế tiếp `db.openForUser` tự đóng handle rò rồi mở đúng vùng mới.
- **Thiếu cấu hình**: `main()` bọc trong `runZonedGuarded`; nếu `!canInitSupabase`
  → `ConfigurationErrorScreen` (liệt kê TÊN biến thiếu, **không** giá trị), KHÔNG
  gọi `Supabase.initialize`. Init ném → `BootstrapErrorScreen`. Không log
  password / JWT / URL / key ở bất kỳ nhánh nào.
- **Màn đăng nhập (SVG 20)**: chỉ **email** (nhãn "Email" — cấu hình chưa chứng
  minh đăng nhập SĐT, không giả vờ hỗ trợ). Validate email/password, ẩn/hiện mật
  khẩu, `AutofillGroup` + hints, `textInputAction` next/done, submit từ bàn phím,
  khoá nút khi đang gửi (chống double-submit), lỗi tiếng Việt (không lộ exception).
- **Quên mật khẩu**: `resetPasswordForEmail` (flow chuẩn Supabase). Thông báo
  thành công trung tính ("nếu email có tài khoản...") — chống dò tài khoản. Không
  hotline; CTA hỗ trợ là "Liên hệ quản lý HTX".
- **Đặt mật khẩu mới** (`screens/reset_password_screen.dart`): khi phiên
  `passwordRecovery` được thiết lập (người dùng mở link trong email),
  `AuthGate` hiện màn nhập mật khẩu mới → `auth.updateUser(password:)`. Phần
  **nối deep link** để link email mở lại app CẦN cấu hình ngoài code — xem
  "Blocker / quyết định ngoài code" bên dưới.

## Offline-first — nguyên tắc bắt buộc (NFR-01)

`activity_form_screen.dart` ghi thẳng vào SQLite khi bấm "Lưu" — **không gọi mạng ở
bước này, dưới bất kỳ hình thức nào.** Đồng bộ là hành động riêng (nút "Đồng bộ ngay"
ở `crop_season_detail_screen.dart`), người dùng tự bấm khi có mạng.

## Đồng bộ — idempotent bằng đúng cơ chế Supabase đã có

`id` của `Activity` cục bộ **chính là** `client_event_id` gửi lên Supabase, ghép
với `device_id` → khoá tự nhiên `(device_id, client_event_id)`. Retry không tạo
bản ghi trùng.

**Ghi `activities` = tìm-rồi-INSERT/UPDATE, KHÔNG `upsert onConflict`.** Chỉ mục
duy nhất cho cặp khoá này là **partial index**
(`... where device_id is not null and client_event_id is not null`); PostgREST
`?on_conflict=device_id,client_event_id` sinh `ON CONFLICT (device_id,
client_event_id)` KHÔNG kèm predicate → Postgres có thể không suy ra partial
index → `42P10`. `SyncGateway.upsertActivity` vì vậy: `select id` theo cặp khoá
→ có thì `update … eq('id')`, chưa có thì `insert`. Plot/CropSeason vẫn dùng
`upsert onConflict` được vì `(farm_id, plot_code)` / `(plot_id, season_code)` là
UNIQUE constraint đầy đủ (không partial). Bảng chi tiết dùng `onConflict:
'activity_id'` (khoá CHÍNH).

**Race unique 23505 khi ghi `activities` (TOCTOU giữa SELECT và INSERT).** Nếu
một lượt khác chèn đúng cặp khoá giữa `select` và `insert` của mình → Postgres
`23505`. `SupabaseSyncGateway.upsertActivity` bắt **đúng `code == '23505'`**
(mọi lỗi khác `rethrow` để classifier xử lý), đọc lại row theo `(device_id,
client_event_id)`:
- thấy → `update … eq('id')` bằng đúng server id đó, tiếp tục ghi detail;
- vẫn không thấy → **`rethrow`** (không đánh dấu `synced` giả) để lượt sau thử
  lại. Không nuốt exception, không tạo bản ghi trùng.
3 thao tác I/O thô (`findActivityIdByKey` / `insertActivityReturningId` /
`updateActivityById`) là seam `@visibleForTesting` để unit-test luồng điều phối
23505 mà KHÔNG cần `SupabaseClient` giả — KHÔNG đổi schema / thêm API.

**Xoá `Activity` đã đồng bộ (tombstone) — chỉ dọn local khi UPDATE tác động
ĐÚNG 1 row, KHÔNG dựa `SELECT` visibility.** RLS `activities_select` là
`deleted_at is null AND user_can_read_batch(...)` → sau khi set `deleted_at`,
row biến mất khỏi mọi `select` của chủ sở hữu; và `select` rỗng KHÔNG phân biệt
được "server đã xoá" với "RLS vừa thu hồi quyền đọc, row còn SỐNG". Cách cũ
(`visibleBefore && !visibleAfter → hard-delete`) vẫn có TOCTOU (quyền bị thu hồi
sau pre-check, UPDATE tác động 0 row mà không ném). Cách hiện tại:
`SyncGateway.softDeleteActivity` trả **số dòng UPDATE tác động** (từ
`Content-Range` với `Prefer: count=exact`, KHÔNG kèm `.select()` nên tính TRƯỚC
RLS select):
- `count == 1` → server ĐÃ ghi `deleted_at` cho đúng `serverId` (ack không mơ
  hồ; giá trị `1` không thể là dương-tính-giả dưới bất kỳ diễn giải nào của
  PostgREST) → `hardDeleteActivity` local;
- `count == 0` (RLS `USING` chặn / row không tồn tại) hoặc `null` (không đọc
  được count) → **GIỮ tombstone** `failed`/`notConfirmed`, lượt sau thử lại.
Mọi lỗi mạng/auth/RLS-exception → giữ tombstone (classifier). `serverId == null`
(chưa từng lên server) → hard-delete local ngay sau xác nhận. Nhánh xoá KHÔNG
bao giờ gọi `upsertActivity` → retry không tạo lại Activity. **Blocker backend:**
để dọn được tombstone khi `count` không đáng tin ở một PostgREST cấu hình lạ,
cần RPC xoá trả ack rõ ràng hoặc policy cho chủ sở hữu thấy row đã soft-delete.

**`device_id` theo TỪNG USER.** `devices.installation_id` là `unique` toàn bảng
và RLS chỉ cho user thao tác row của chính mình → nếu B đăng nhập trên máy A đã
đăng ký mà dùng chung `installation_id` thì upsert của B đụng row của A
(23505 / RLS-denied) → B không lấy được `device_id` → không sync được.
`device_service.dart` sinh `installation_id = uuidv5(seed_thiết_bị : user_id)`
tất định — mỗi user một row `devices` riêng, seed thiết bị vẫn ổn định qua các
lần mở app (`shared_preferences`). `reset()` (đổi tài khoản) quên `devices.id`
đã resolve, giữ seed.

Batch (`production_batches`) là bắt buộc ở tầng schema (`activities.production_batch_id
NOT NULL`) dù carbon tính theo Crop Season. App **tự tạo 1 batch mặc định mỗi vụ**
(`batch_code = 'default'`), nông dân không nhìn thấy khái niệm này — đúng tinh thần
"Production Batch là traceability" (Phase 10 của đề bài).

## Carbon API client & màn "Kết quả phát thải" (Prompt 9 — SVG 25)

**KHÔNG tính carbon trong app** — chỉ gọi backend + hiển thị đúng response.

**`services/carbon_api_service.dart`** — 4 route:
`GET /health` · `GET /v1/carbon/scenarios` (cả hai KHÔNG kèm `Authorization`) ·
`POST /v1/carbon/calculate` · `GET /v1/crop-seasons/{server_id}/carbon`.
- **Error parser** đọc `detail.error.{code,message,request_id}` (shape hiện tại),
  + nhánh cho `detail.error` là string (cũ), `detail` là **list**
  (`HTTPValidationError` FastAPI khi body sai kiểu → `validation_error`),
  `detail` là string. Body rỗng / KHÔNG-JSON / JSON hỏng → fallback theo HTTP
  status, KHÔNG ném khi decode.
- Phủ mọi mã: `missing_authorization/unauthenticated`, `crop_not_found`,
  `no_calculation` (→ `latest()` trả `null`, KHÁC `crop_not_found` phải ném),
  `invalid_water_regime`, `conflicting_water_records`, `double_counting`,
  `missing_emission_factor`, `methodology_gap`, `missing_activity_data`,
  `factor_set_not_imported`, `backend_not_configured`, `auth_not_configured`,
  `internal_error` (+ `request_id` → hiện "Mã tra cứu: …" cho người dùng, KHÔNG
  lộ stack). `friendlyMessage` tiếng Việt, không lộ chi tiết kỹ thuật.
- **Timeout** 20s → `TimeoutException` ("phản hồi chậm"); mạng → "kết nối mạng".
- `scenarios()` lỗi → fallback 3 enum chính thức (`kOfficialScenarios`).
- `health()` lỗi → `null`.

**`services/carbon_cache.dart`** — cache theo **user + cropSeason server id +
scenario** (`meta['carbon.v2.<sid>.<scenario>']`), lưu FULL `CarbonResult` +
`calculated_at` (server) + `_fetched_at` (client). Offline đọc cache
(`fromCache = true`). **Refresh lỗi KHÔNG xoá cache.**

**Màn 25** (`screens/carbon_result_screen.dart`):
- **Tiền điều kiện** trước khi gọi API: vụ tồn tại · đã đồng bộ (`server_id` khác
  null — KHÔNG gọi API bằng local UUID) · KHÔNG còn Activity `pending`/`failed`
  của vụ. Thiếu → chặn + CTA **"Đi tới Gửi dữ liệu"** (`onOpenSync`).
- Header "Kết quả phát thải" · "Ruộng `<mã thửa>` · Vụ `<season_code>`" THẬT.
- Kịch bản: từ `scenarios()` (fallback 3 enum), nhãn tiếng Việt.
- Hero `co2e_per_kg` — `null` → "Chưa có sản lượng nên chưa tính được CO₂e/kg",
  **KHÔNG "0"**. Tổng CO₂e, sản lượng.
- **Breakdown**: `% = entry.co2e_kg / total` chỉ khi `total > 0`; tổng breakdown
  lệch total > 1% → cảnh báo "hiển thị đúng số máy chủ, không tự chỉnh"; label
  tiếng Việt + giữ **mã nguồn THẬT** (`ch4_rice_cultivation · CH4`).
- **So sánh kịch bản**: CHỈ khi có kết quả thật cho CẢ `awd` LẪN
  `continuous_flooding` và `continuous_total > 0`;
  `reduction = (continuous − awd) / continuous × 100`; ghi rõ so với kịch bản
  nào + "KHÔNG phải mức giảm thực tế đã đo".
- Warnings từ backend, phương pháp + `ef_config_version` + `calculated_at` THẬT.
  Nút **"Xem chi tiết"** mở phần kỹ thuật (chế độ nước áp dụng, engine_version,
  công thức từng nguồn).
- **Scientific blocker**: `GET /health` → `carbon_production_ready == false` →
  banner "CHƯA phải kết quả MRV, chỉ tham khảo". Không sinh số demo.
- Cache vs live: nhãn "Số đã lưu trên máy · tính lúc … · lấy về …". Session hết
  hạn / lỗi mạng khi có cache → hiện cache + banner (không mất số).
- Mọi `setState` sau `await` có check `mounted`.
- Là route push chồng shell (như các màn phân cấp khác) → có nút Back, không có
  bottom nav riêng (bottom nav thuộc shell).

## Điểm chạm CV & màn "Kiểm tra ảnh lá lúa" (Prompt 10 — SVG 24)

**Chỉ bài toán bệnh lá** (module 03): 4 nhãn `blast`/`bacterial_blight`/
`brown_spot`/`healthy` → Đạo ôn / Bạc lá / Đốm nâu / Lá khỏe. **KHÔNG** làm
"giai đoạn sinh trưởng" hay "mực nước" dù SVG 24 vẽ — ngoài phạm vi TEC cho phép.

**Hợp đồng (`services/cv_inference_service.dart`)**
- `CvInferenceResult { label, labelVi, confidence, isUncertain }`;
  `LeafDiseaseLabel.fromWire` ném nếu chuỗi lạ (không ép nhãn).
- `isUncertain` = model tự đánh dấu **hoặc** `confidence < kCvConfidenceThreshold`
  (0.70 — cổng hiển thị phía app, KHÔNG phải tuyên bố độ chính xác thực địa).
- `CvInferenceService` abstract; bản chạy thật = `UnavailableCvInferenceService`
  (`isAvailable == false`, `classify` ném `CvInferenceUnavailable`). **Chưa có
  model/endpoint → không trả nhãn/độ tin cậy dựng sẵn.** Đổi implementation ở
  `AppServices.bootstrap` khi có service thật — UI không đổi (DI qua
  `AppRoutes.openCameraCv`).

**Ảnh (`services/leaf_photo_source.dart`)** — bọc `image_picker` +
`permission_handler` (không MethodChannel trực tiếp):
- Trạng thái quyền: `granted` / `denied` (hỏi lại) / `permanentlyDenied` (nút
  "Mở Cài đặt" → `openAppSettings()`) / `restricted` (nêu rõ thiết bị giới hạn).
- Máy ảnh: xin `Permission.camera`. Không có máy ảnh (`no_available_camera`) →
  `cameraUnavailable`, **không crash**, vẫn dùng được "Chọn từ thư viện".
- Thư viện: iOS kiểm `Permission.photos`; Android dùng Photo Picker hệ thống →
  bỏ qua cổng quyền (không xin quyền chưa khai).
- Kiểm hợp lệ: magic bytes JPEG (`FF D8 FF`) / PNG (`89 50 4E 47…`), file rỗng /
  không tồn tại → `invalidImage`; `> kMaxLeafPhotoBytes` (12 MB) → `tooLarge`.
- `maxWidth/maxHeight = 1600`, `imageQuality = 85`, `requestFullMetadata: false`
  → resize/nén + tái mã hoá (rụng EXIF GPS). **Không xoá ảnh gốc** — image_picker
  trả bản sao trong cache; ảnh trong cuộn camera / thư viện không bị đụng.

**Phản hồi (`services/cv_feedback_store.dart`)** — "Xác nhận đúng" / "Chỉnh lại"
lưu **chỉ trên máy**: bảng `meta`, key `cv.feedback.<cropSeasonClientId>` → mảng
JSON. Không endpoint, không ghi bảng server không tồn tại.

**Màn (`screens/camera_cv_screen.dart`)** — header "Kiểm tra ảnh lá lúa";
tiền điều kiện: có vụ đang canh tác (ảnh gắn với vụ) — chưa có → nhắc chọn vụ.
Khung preview → Chụp ảnh / Chọn từ thư viện → xem ảnh → Chụp/chọn lại. Card kết
quả: nhãn tiếng Việt, độ tin cậy `AppFormat.percent` (số THẬT từ model), badge
"Cần kiểm tra" + cảnh báo khi `isUncertain`. "Chỉnh lại" mở sheet 4 nhãn.
Mọi `setState` sau `await` check `mounted`. Platform: `AndroidManifest.xml`
(`CAMERA`, camera `required="false"`), `ios/Runner/Info.plist`
(`NSCameraUsageDescription`, `NSPhotoLibraryUsageDescription`), `ios/Podfile`
(macro `permission_handler`).

## Resource Dashboard & Recommendation (Prompt 11 — module 04/05)

**Không có SVG riêng.** `GET /v1/crop-seasons/{id}/metrics` (`MetricResponse`,
openapi.json) là API THẬT duy nhất; **không** gọi `/v1/plots/{id}/efficiency`
(OpenAPI không có), **không** tự tính lại chỉ số nào backend đã trả.

**`models/crop_season_metrics.dart`** — khớp 1-1 `MetricResponse`:
`yield_kg` + 3 tổng + 4 chỉ số `*_per_kg` (đều `double?`, `null` ≠ `0`) +
`data_completeness {water,fertilizer,cost,carbon}`. Thêm `fetchedAt`/`fromCache`
cho nhãn cache. `cellState(kind)` quyết định ô hiển thị theo thứ tự ưu tiên:
có số → **value**; thiếu `yield_kg` → **missingYield** ("Chưa có sản lượng");
còn lại → **incompleteData** ("Chưa đủ dữ liệu"). KHÔNG bao giờ ra "0".

**`services/metrics_cache.dart`** — cache theo user + cropSeason server id, dùng
CHUNG khoá `home.metrics.<sid>` với `HomeController` (một nguồn offline). Offline
đọc cache (`fromCache=true`); refresh lỗi **KHÔNG** xoá cache.

**`services/recommendation_repository.dart`** — `RecommendationRepository` +
`Recommendation`. OpenAPI CHƯA có endpoint → `UnavailableRecommendationRepository`
(`isAvailable=false`, `forCropSeason` ném). `Recommendation.isValid` yêu cầu ĐỦ:
nội dung tiếng Việt + `co2e_reduction_kg` + `cost_saving_vnd` + `compared_to` +
`source` — thiếu impact → không render; thiếu `compared_to`/`source` → không được
tuyên bố benchmark. **Không fixture/mock trong production; fake chỉ ở test.**

**`models/resource_comparison.dart`** — `isRenderable` chỉ true khi đủ nhóm +
thời kỳ + nguồn + `dataSufficient`. `MetricResponse` không trả nhóm so sánh nào →
mặc định `ResourceComparison.unavailable()` → UI "Chưa đủ dữ liệu để so sánh".
Không tự bịa benchmark.

**`screens/resource_dashboard_screen.dart`** — header "Hiệu quả tài nguyên"; tiền
điều kiện: vụ có trong DB + đã đồng bộ (`server_id`) — chưa → CTA "Đi tới Gửi dữ
liệu" (KHÔNG gọi API bằng local UUID). Grid responsive **2×2 / 1 cột**
(`LayoutBuilder`, ngưỡng 480px) 4 `MetricCard`: Nước/kg (m³/kg), Phân bón/kg
(kg/kg), Khí thải/kg (kg CO₂e/kg), Chi phí/kg (đồng/kg). Bấm 1 ô → bottom sheet
"chi tiết" nêu **nhóm Activity nguồn** (Tưới nước / Bón phân / Thu hoạch / kết
quả phát thải — theo `read_repo.metrics()`) + tổng + cờ `data_completeness`.
Còn Activity chưa gửi → banner nhắc. Cache-vs-live có nhãn "Số đã lưu trên máy";
session hết hạn / lỗi mạng khi có cache → banner, giữ số. Mọi `setState` sau
`await` check `mounted`. Route phụ push chồng shell (nút Back; bottom nav thuộc
shell).

**Tích hợp Home** — card "Tài nguyên vụ này" (đã có) giờ bấm được → mở dashboard
("Xem hiệu quả ›"). `HomeController` vẫn tự tải `metrics` thật cho vụ đang chọn
(không đổi). KHÔNG có card khuyến nghị giả trên Home khi chưa có endpoint.

## Màn Tài khoản (Prompt 12 — SVG 26)

**`shell/tabs/account_tab.dart`** — thẻ danh tính (avatar chữ viết tắt + họ tên +
vai trò + hộ) + 5 mục điều hướng + "Đăng xuất". Dữ liệu THẬT:

- **Họ tên + vai trò** từ `GET /v1/me` (`MeResponse`). Cache local
  (`meta['account.full_name']` / `account.roles`) → offline hiện bản đã lưu kèm
  nhãn. `full_name == null` → "Chưa cập nhật tên" (không bịa "Nguyễn Văn An").
- **Chữ viết tắt avatar** dựng từ họ tên thật (ký tự đầu của từ đầu + từ cuối,
  tối đa 2). Không có tên → icon người, KHÔNG "NA".
- **Vai trò VN**: map `organization_role` (`farmer`/`cooperative_manager`/
  `enterprise_viewer`/`regulator`) + `farm_role` (`owner`/`editor`/`viewer`);
  vai trò lạ vẫn hiển thị nguyên (dữ liệu thật). Rỗng → ẩn dòng.
- **"Ruộng của tôi"** subtitle: `N ruộng · X ha` từ `LocalDatabase.plotSummary()`
  (đếm + `SUM(area_ha)` bảng `plots` local). 0 ruộng → "Chưa có ruộng nào trên
  máy". Không hardcode "3 ruộng" / "4,2 ha".
- **Điện thoại + địa chỉ**: `/v1/me` KHÔNG trả → màn "Thông tin cá nhân"
  (`screens/personal_info_screen.dart`) hiện "Chưa có thông tin" + ghi rõ app
  không sửa được hồ sơ (KHÔNG tự tạo API cập nhật profile).
- **"Đổi mật khẩu"** → dùng lại `ResetPasswordScreen` với
  `onSubmit: authController.updatePassword` → Supabase `auth.updateUser(password)`
  trên phiên hiện tại (Supabase Auth hợp lệ, không qua email, không endpoint mới).
- **"Trợ giúp"** (`screens/help_screen.dart`) — hướng dẫn ngắn + "liên hệ cán bộ
  HTX phụ trách". KHÔNG có số tổng đài giả.
- **"Cài đặt gửi dữ liệu"** → màn đã có (Prompt 8), lưu local theo user
  (`meta['sync.wifi_only']`).
- **"Đăng xuất"** → `authController.signOut()` (đánh dấu chủ động) → `AuthGate`
  đổi phase về màn đăng nhập. Không điều hướng thủ công.
- Thanh 4 tab do `HomeShell` gắn; `AccountTab` không tự vẽ bottom nav.

## Tầng dữ liệu local & cây Farm → Plot → Crop Season (Prompt 3)

**Tách theo user bằng FILE RIÊNG.** `LocalDatabase` là facade ổn định; bên trong
mở `agricarbon_u_<uuid đã làm sạch>.db` cho từng user (UUID lọc còn `[A-Za-z0-9]`
— KHÔNG dùng JWT/key làm tên file). `AuthController.onUserActive` mở đúng file +
migration + requeue; `onUserInactive` **đóng** DB (KHÔNG xoá file → đăng nhập lại
còn nguyên pending data). User B không mở được file của A.

**SQLite `schemaVersion` hiện tại = 5.** Mọi bước `onUpgrade` chỉ additive:
`ALTER TABLE ADD COLUMN` + `CREATE TABLE IF NOT EXISTS` + backfill. KHÔNG DROP,
KHÔNG xoá dữ liệu. Mở DB xong luôn chạy `_requeueStuck`: bản ghi kẹt `syncing`
(crash giữa chừng) → `pending`.

| Bước | Thêm gì |
|---|---|
| v1 → v2 | cột `server_id` + sync metadata cho `plots`/`crop_seasons`; bảng `active_context`; backfill từ cột cũ `pending_create` |
| v2 → v3 | bảng `meta(key, value)` — cache `full_name` / `sync.last_at` / carbon + metrics theo vụ |
| v3 → v4 | cột `activities.deleted_locally` (tombstone xoá bản ghi đã đồng bộ) |
| v4 → v5 | `activities.retry_count` / `last_attempt_at` / `synced_at` + `plots.synced_at` + `crop_seasons.synced_at` (metadata cho màn "Gửi dữ liệu") |

`debugOpenAtV1` + test migration chứng minh v1→v2 và v4→v5 giữ nguyên dữ liệu.

**Plot / Crop Season**: `clientId` ổn định (khoá chính local) + `serverId` nullable
(có sau khi đồng bộ) + sync metadata (`sync_state`, `sync_error_code`, `retry_count`,
`last_attempt_at`, `created_at/updated_at`). Tham chiếu cha (Crop Season → Plot,
Activity → Crop Season) dùng **clientId**; `sync_service` tra ra `serverId` lúc
đẩy, con nào cha chưa đồng bộ thì hoãn. Idempotent bằng khoá tự nhiên
(`plots(farm_id,plot_code)`, `crop_seasons(plot_id,season_code)`) + `upsert`.
Tỉnh/huyện/xã ở **Farm**, không ở Plot.

**Crop Season methodology** (`models/methodology_enums.dart` — wire khớp tuyệt đối
Supabase, `labelVi` tiếng Việt): `default_irrigation_method` · `ipcc_water_regime`
(7) · `pre_season_water_regime` (4, có giải thích dễ hiểu) · `cultivation_days` ·
`drainage_event_count`. Validate (`models/crop_season_validation.dart`):
`cultivation_days>0`, `drainage>=0`, thu hoạch không trước gieo, **không tự default
input phương pháp luận**; gợi ý `cultivation_days` từ ngày gieo/thu hoạch nhưng
user phải bấm "Dùng gợi ý"; AWD thiếu số lần rút nước → cảnh báo nhưng vẫn lưu.

**Farm**: online-only (không giả offline). `cooperative_id` lấy từ
`organization_memberships` thật; nếu chưa thuộc HTX → hướng dẫn liên hệ quản lý.
Lỗi tạo Farm phân biệt **RLS (thiếu quyền)** vs **mất mạng** vs **trùng mã**
(`services/sync_errors.dart`).

**ActiveContext** (`services/active_context.dart`): Farm/Plot/Crop Season đang chọn,
lưu ở bảng `active_context` trong DB riêng của user. Bất biến: Plot phải thuộc Farm
đang chọn, Crop Season phải thuộc Plot đang chọn (đổi cấp trên → xoá cấp dưới, tránh
ghi Activity nhầm vụ). `revalidate()` (gọi sau khi kéo dữ liệu) xoá an toàn entity
không còn trong cache. `cropSeasonServerId` — Carbon LUÔN dùng id này.

## Màn Trang chủ (Prompt 4 — SVG 21)

`home_controller.dart` (`ChangeNotifier`) điều phối, `home_tab.dart` chỉ render.
Mọi số liệu **thật**; `null` → "Chưa có dữ liệu", **không bao giờ 0**.

- **Nguồn**: `full_name`/roles từ `GET /v1/me` (`read_api.dart` + `me_service.dart`);
  Farm/Plot/Crop từ local DB (source hiện có); Carbon từ `carbonApi.latest(serverId)`
  (cache offline trong bảng `meta`); online/offline từ `connectivity_plus`.
- **9 state**: `loading · refreshing · success · partial · empty · offlineWithCache
  · offlineNoCache · unauthorized · error`. Pull-to-refresh **không xoá cache** khi
  lỗi (giữ snapshot cũ, chỉ đổi status + `softError`). Gọi mạng **1 lần** ở
  `initState` + khi pull — KHÔNG trong `build`. `IndexedStack` giữ state khi đổi tab.
- **Lời chào**: `full_name` thật (hoặc "bạn"), `Hộ <farm_code> · N ruộng` (N từ
  `db.listPlotsByFarm`). Không hardcode tên/mã.
- **Active context card**: breadcrumb Farm › Thửa › Vụ + nút "Đổi". Chưa chọn →
  CTA. **Tự chọn Farm chỉ khi đúng 1 hộ** (nhiều hộ → không tự chọn).
- **Việc cần làm** (suy từ dữ liệu thật, không lịch giả): ưu tiên
  `Còn N bản ghi chưa gửi` → `Chọn vụ canh tác` → `Bổ sung dữ liệu đang thiếu`
  (vụ thiếu `cultivation_days`/`ipcc_water_regime`/`pre_season_water_regime`) →
  `Ghi hoạt động`.
- **Ghi nhanh**: 3 ô loại hoạt động (Tưới / Bón phân / Xăng dầu) + ô "Ảnh ruộng"
  + "Xem tất cả" (7 loại). Ô loại hoạt động → `openActivityForm(<1 trong 7
  kActivityTypes>)`; ô "Ảnh ruộng" → `openCameraCv()` (KHÔNG có sentinel string
  như `__cv__` chui vào form). `AppRoutes.openActivityForm` + `ActivityForm` có
  guard: loại ngoài `kActivityTypes` → không dựng form, không lưu DB.
- **Kết quả vụ** (`MetricCard`): `co2e_per_kg` từ Carbon API/cache (LUÔN server
  id của vụ); chưa chọn vụ / vụ chưa đồng bộ / chưa tính / chưa có sản lượng →
  dòng chữ tương ứng (không 0, không "↓14%"). `carbonFromCache` → chú thích.
- **Tài nguyên vụ này** (Prompt 7): `GET /v1/crop-seasons/{server_id}/metrics`
  (`models/crop_season_metrics.dart` + `services/metrics_service.dart`, khớp
  `MetricResponse`). Chỉ gọi khi online + vụ có server id; KHÔNG trong `build`;
  cache bảng `meta['home.metrics.<server_id>']` theo user. 401/403 →
  `unauthorized`; lỗi mạng → `partial` (giữ cache). Chỉ hiện dòng có SỐ THẬT
  (yield / nước m³ / phân bón kg / chi phí/kg) — field `null` bỏ hẳn dòng, không
  hiện 0.
- **Đổi vụ đang chọn**: cập nhật local NGAY (không nháy cache vụ cũ); nếu ĐANG
  ONLINE và vụ mới đã đồng bộ → tự `refresh()` để tải Carbon/Metrics vụ mới
  (không phải tự kéo). Offline → chỉ đọc cache vụ mới. Không gọi lại nếu vẫn là
  vụ vừa tải (`_lastFetchedSeasonServerId`).
- **Gửi dữ liệu**: pending count (`db.countAllPending`), last sync (`meta`),
  online/offline. Bấm → chuyển tab "Gửi dữ liệu".
- **Mất/khôi phục mạng**: mất → hạ `HomeStatus` xuống `offlineWithCache/NoCache`
  (trước đây kẹt `success`); có lại → tự `refresh()` đầy đủ.
- **Test không dựa `Future.delayed`**: `HomeController.debugSettle()` chờ đúng
  việc bất đồng bộ do sự kiện (đổi context / kết nối) → hết flaky khi chạy suite
  song song.
- **Lifecycle / race an toàn** (`home_controller.dart`):
  - `_generation` tăng mỗi khi NGƯỜI DÙNG đổi Farm/Plot/Vụ hoặc đăng xuất
    (`resetForSignOut`). `_emitFor(gen, …)` bỏ mọi `_emit` của generation cũ →
    response vụ A về SAU khi đã chọn vụ B **không ghi đè** snapshot; không hiện
    dữ liệu user A ở user B kể cả một frame. (`_build` tự chọn Farm duy nhất
    KHÔNG tính là đổi ngữ cảnh — cờ `_internalContextUpdate`.)
  - Ngữ cảnh đổi TRONG lúc `_run` chạy → cờ `_rerunAfterLoad`; lượt hiện tại
    `await` một lượt đầy đủ nữa ở cuối → future mà `load()/refresh()` trả về chỉ
    hoàn thành khi state cuối đã đúng (KHÔNG dừng ở no-op). `_run` khi bận trả
    về chính `_pending` để caller chờ hết chuỗi.
  - `_suspended` (bật ở `resetForSignOut`, tắt ở `load()` của user kế): `_run` /
    `_recomputeLocalOnly` / `_onContextChanged` (kể cả sự kiện do
    `activeContext.detach()`) đều no-op → rerun sau đăng xuất KHÔNG chạm DB đã
    đóng / API. `_build(gen)` kiểm `_stale(gen)` sau phần local, TRƯỚC phần
    mạng, và trước khi tải carbon/metrics → không gọi API cho ngữ cảnh đã cũ.
  - `dispose` set `_disposed` → `_emit` / rerun đều dừng; không `notifyListeners`
    sau dispose.

`meta(key,value)` (schemaVersion 3) còn cache metrics theo vụ.
`test/no_figma_placeholders_test.dart` chốt không có chuỗi minh hoạ Figma.

## Ghi nhanh & Activity đầy đủ (Prompt 5 — SVG 22)

**Ghi nhanh** (`quick_log_tab.dart`): chọn 1 trong 4 shortcut (Tưới / Bón phân /
Xăng dầu / Rơm rạ) hoặc "Xem tất cả" (7 loại) → context row dùng ActiveContext mặc
định (nút "Đổi") → `ActivityForm` inline. Icon Material, không emoji.

**`activity_field_spec.dart`**: `key` khớp TUYỆT ĐỐI cột bảng chi tiết Supabase
(đọc migration): seeding_events · fertilizer_applications · irrigation_events (có
`duration_minutes`, đơn vị m³/cm/kWh/phút — **không "mm"**, không tự quy đổi) ·
pesticide_applications · fuel_usages · straw_management_events (+ `dry_matter_fraction`
`days_before_cultivation` `returned_to_field` từ migration methodology) ·
harvest_events. Enum đủ giá trị (`irrigation_method` 4, `fuel_type` 4,
`straw_management_method` 5).

**`activity_validation.dart`** (hàm thuần, test riêng): `parseActivityField` — gõ
sai định dạng → `error != null`, **KHÔNG biến thành null rồi lưu**. Ràng buộc:
`occurred_at` không tương lai · amount/yield/area `> 0` · cost `>= 0` · % `0..100` ·
`dry_matter_fraction` `> 0` và `<= 1` · `days_before_cultivation` `>= 0`. Có điều
kiện: `incorporated` cần dry_matter + days; `composted` hiện tristate
returned_to_field (Có/Không/Chưa rõ); `harvest` cần yield_kg. Cảnh báo (KHÔNG chặn,
SRS FR-1a-04): AWD/rút-nước-nhiều-lần mà vụ thiếu drainage count.

**Lưu offline**: `LocalDatabase.saveActivity` — 1 hàng, `transaction`, KHÔNG gọi
mạng; `client_event_id` UUID ổn định; `pending` sau khi lưu; restart còn nguyên
(test 7 loại). `ActivityForm` không có tham số api/http nào.

**CRUD** (`activity_detail_screen.dart`): Sửa giữ `client_event_id` + `type` (form
không có ô chọn type → không mồ côi bảng chi tiết), quay về `pending`. Xoá bản ghi
**chưa đồng bộ** → xoá hẳn local (sau xác nhận). Xoá bản ghi **đã đồng bộ** →
tombstone (`deleted_locally=1`, `pending`), ẩn khỏi danh sách nhưng còn trong hàng
đợi; `sync_service._pushDelete` đẩy `deleted_at` lên server rồi mới xoá hẳn local;
RLS/mạng từ chối → giữ nguyên, thử lại (KHÔNG mất row). DB **schemaVersion 4**:
`activities.deleted_locally` (v3→v4 additive).

## Đồng bộ tự động & màn "Gửi dữ liệu" (Prompt 8 — SVG 23)

**`SyncCoordinator`** (`services/sync_coordinator.dart`, `ChangeNotifier`) điều
phối trên `SyncService`:

- **Single-flight**: một lượt `syncAll` tại một thời điểm — cả `SyncService.syncAll`
  lẫn `SyncCoordinator.runSync` trả lại future đang chạy nếu gọi lại (chống
  concurrent sync).
- **Tự gửi** khi: sau đăng nhập (`onLogin` từ `AppServices.onUserActive`, chạy
  nền), app trở lại foreground (`HomeShell` → `WidgetsBindingObserver` →
  `onAppResumed`), có mạng lại (`connectivity.onChange`, **debounce 2s**).
- **Nút thủ công** "Gửi dữ liệu ngay" ở màn 23 — luôn có.
- **Tôn trọng "Chỉ Wi-Fi"** (`meta['sync.wifi_only']`, lưu theo user): auto bỏ
  qua khi đang dùng dữ liệu di động; nút thủ công hỏi xác nhận rồi mới gửi
  (`overrideWifiOnly`). "Có Wi-Fi ≠ chắc chắn có Internet" — lượt gửi lỗi vẫn
  giữ dữ liệu, đánh `failed`/`retry_count++` để thử lại.
- **7 state** cho UI: `offline · idle · syncing · partialSuccess · allSynced ·
  failed · authExpired` (lỗi `SyncErrorKind.auth` khi gửi → `authExpired`, hiện
  "đăng nhập lại", KHÔNG lộ exception).
- **KHÔNG chặn form**: form vẫn ghi thẳng SQLite; coordinator chỉ đọc hàng đợi.

**Thứ tự đẩy** (giữ nguyên từ trước): Plot → Crop Season → Default Batch →
Activity base → Activity detail → Tombstone. Con chưa có cha `server_id` → hoãn
(`summary.deferred`), KHÔNG đánh `failed`. `syncing` kẹt sau crash →
`_requeueStuck` đưa về `pending` khi mở DB.

**Idempotency**: `activities` = tìm theo `(device_id, client_event_id)` rồi
INSERT/UPDATE (không `ON CONFLICT` trên partial index); detail `onConflict
activity_id`; plot/season `onConflict` khoá tự nhiên. Crash sau khi server nhận
mà local chưa lưu `server_id` → retry tìm lại đúng row, không tạo trùng.

**Màn 23** (`shell/tabs/sync_tab.dart`): header "Gửi dữ liệu" + chấm mạng +
icon Cài đặt; card **Trạng thái** (dòng theo state + "Lần gửi gần nhất: <mốc
thật>" / "Chưa gửi lần nào"); section **"Chưa gửi lên"** (sửa typo SVG "Chưa
gửi gửi lên") + danh sách gộp plot/vụ/activity `pending|failed` — mỗi dòng:
`loại · mã thửa`, `dd/MM HH:mm · tóm tắt payload THẬT` (đơn vị m³/kg/lít… KHÔNG
"mm", KHÔNG quy đổi), badge trạng thái, thông báo lỗi thân thiện + "Đã thử N
lần". **KHÔNG có dòng "ảnh"** (chưa có bản ghi ảnh thật). Card **"Các mốc thời
gian"** (làm / ghi / gửi). Nút "Gửi dữ liệu ngay" ở `bottomBar` — khoá khi
offline / đang gửi / hết hàng đợi. Bottom nav do `HomeShell` cấp.

**Cài đặt** (`screens/sync_settings_screen.dart`): 2 lựa chọn "Wi-Fi và dữ liệu
di động" (mặc định) / "Chỉ Wi-Fi", lưu `meta` theo user; đổi xong + còn hàng
đợi + hợp lệ → tự gửi.

DB **schemaVersion 5**: `activities.retry_count/last_attempt_at/synced_at` +
`plots.synced_at` + `crop_seasons.synced_at` (v4→v5 additive).
`LocalDatabase.pendingSyncItems()` join sẵn nhãn thửa cho danh sách.

## Sửa trong Prompt 7 (review sau Prompt 0–5)

- **Vòng đời đổi tài khoản**: `AuthController` cũ kích hoạt B mà chưa dọn A khi
  stream phát thẳng `signedIn`/`tokenRefreshed` cho user khác. Nay `_switchTo`
  dọn A trước (đóng DB, reset Home/`_loadedOnce`/ActiveContext/SyncService cache/
  DeviceService), rồi mới mở B; `_currentUserId` chỉ đặt sau `onUserActive`;
  cleanup/kích hoạt hỏng → `AuthPhase.error` (không vào shell, không giữ id sai).
  `onUserInactive` ném `AccountCleanupException` khi có bước hỏng. Đăng xuất vẫn
  về Login ngay kể cả cleanup lỗi.
- **Deep link đặt lại mật khẩu**: nối end-to-end trong source (redirect URL cố
  định + intent-filter Android + URL scheme iOS + `redirectTo`). Bước Supabase
  Dashboard là thủ công — xem mục riêng ở trên.
- **Shortcut "Ảnh ruộng" trên Trang chủ**: bỏ sentinel `__cv__` → gọi
  `openCameraCv()`. Guard ở `AppRoutes.openActivityForm` + `ActivityForm`: loại
  ngoài `kActivityTypes` không lưu DB.
- **Đồng bộ xoá Activity (tombstone)**: `.update(deleted_at)` KHÔNG dựa vào để
  suy kết quả — `RETURNING`/`select` của chính update đó bị RLS `activities_select`
  (`deleted_at is null`) lọc mất ngay khi `deleted_at` vừa khác null. `_pushDelete`
  nay: `activityVisible(serverId)` (đọc riêng) TRƯỚC — không còn thấy thì tombstone
  đã xử lý ở lượt trước → dọn (idempotent sau crash); còn thấy thì
  `softDeleteActivity` rồi `activityVisible` LẠI — mất → server đã nhận → dọn;
  vẫn thấy → update vô hiệu (RLS chặn ngầm) → giữ tombstone + `failed` +
  `SyncErrorKind.notConfirmed`. RLS ném / mạng lỗi → giữ tombstone.
- **`activities` upsert / partial index**: xem mục "Đồng bộ" ở trên —
  select-rồi-INSERT/UPDATE thay `ON CONFLICT` trên partial unique index.
- **`device_id` theo user**: xem mục "Đồng bộ" — `installation_id` sinh v5 theo
  `(seed thiết bị, user id)` để B đăng nhập trên máy A vẫn lấy được `device_id`.
- **Đồng bộ Activity xoá field optional**: parent `activities` LUÔN gửi `note`
  (kể cả `null`); bảng chi tiết dựng ĐỦ cột từ `kActivityFieldSpecs` (khớp
  migration), field trống = `null` → xoá giá trị cũ trên server; không trộn field
  giữa các bảng chi tiết.
- **`SyncService` tách `SyncGateway`** (interface nhỏ cho thao tác Supabase) →
  test được luồng xoá/sửa mà không mock `SupabaseClient`, không chạm mạng.
- **Crop-season metrics cho Trang chủ** (xem mục Trang chủ).
- **`CarbonResultScreen`**: viết lại theo Design System (`AppScaffold`/`AppCard`/
  `MetricCard`/`LoadingState`/`ErrorState`/`AppSpacing`/`AppColors`/`AppFormat`);
  bỏ `Colors.red/orange/grey`, `AppBar`, số spacing rời, `SizedBox` cố định. Mọi
  `setState` sau `await` có check `mounted`. Trạng thái tách bạch loading / empty
  (chưa tính) / success / unauthorized / lỗi. `co2e_per_kg`/`yield_kg` null →
  dòng chữ, không "0". Nhận `CarbonApiService` trực tiếp (test được).
- **README**: SQLite `schemaVersion` ghi thống nhất = 4 (bảng lịch sử migration
  riêng); thêm mục deep link + cách test.

## Sửa trong Prompt 6 (audit Prompt 1–5)

- **`main()` chỉ guard `canInitSupabase`** → app khởi động được khi thiếu
  `BACKEND_BASE_URL`, rồi Trang chủ dựng URI tương đối và hỏng âm thầm. Nay
  `preInitApp` guard cả `isConfigured` → thiếu backend cũng ra màn cấu hình.
- **Handler thứ hai của `runZonedGuarded` rỗng** → nay `reportUncaughtZoneError`
  để lại dấu vết *loại* lỗi (không in nội dung, không lộ key/JWT) + hook test.
- **`AuthController._activate` nuốt lỗi `onUserActive`** rồi vẫn vào
  `authenticated` (shell với DB đóng). Nay lỗi → `AuthPhase.error`.
- **Tín hiệu phiên-ban-đầu xử lý 2 lần** (manual enqueue + stream phát lại
  `initialSession`) → mở DB / tải Trang chủ 2 lần. Nay bỏ qua tín hiệu trùng cho
  user đã kích hoạt.
- **`_enqueue` dùng `catchError` rỗng** → nay chỉ cứu kẹt-splash, không đá người
  dùng khỏi phiên đang chạy.
- **Trang chủ `load()` gọi từ cả `onUserActive` lẫn `HomeTab.initState`** → 2 lần
  gọi mạng mỗi lần đăng nhập. Nay `load()` chạy đúng 1 lần (cờ `_loadedOnce`,
  reset khi đăng xuất); pull-to-refresh dùng `refresh()`.
- **Mất mạng vẫn giữ `HomeStatus.success`** (header báo "đang có mạng"). Nay
  connectivity đổi → hạ xuống `offlineWithCache`/`offlineNoCache`; có mạng lại →
  tự `refresh()` đầy đủ.
- **Pull Farm/Plot/Season chỉ merge, không gỡ** bản ghi synced mà server đã bỏ →
  tồn tại mãi trong cache. Nay `reconcilePulledPlots`/`reconcilePulledCropSeasons`
  gỡ chúng — KHÔNG đụng bản ghi `pending`/`failed` hay chưa có `server_id`.
- **`FarmScreen._createFarm` gọi `currentCooperativeId()` ngoài try/catch** → lỗi
  mạng/RLS thoát khỏi callback nút. Nay bọc try/catch + dialog phân biệt
  mất-mạng vs lỗi khác.
- **README** cập nhật số test (148), trạng thái tab, cây `test/`; thêm mục
  "Blocker / quyết định ngoài code" (deep link, secure storage, DB cũ).
- **Doc sai**: `auth_service.dart` / `pubspec.yaml` từng ghi token lưu bằng
  `flutter_secure_storage` — thực tế `supabase_flutter` 2.x dùng
  `SharedPreferences`. Đã sửa doc.

## Sửa trong Prompt 2

- `AppScaffold` (Design System): closure của `LayoutBuilder` tham chiếu thẳng biến
  `content` đã bị gán lại vào chính nó → **đệ quy layout vô hạn** (`BoxConstraints
  forces an infinite height`) trên MỌI màn dùng `AppScaffold`. Bắt vào local final
  trước khi gán lại. Widget test mới phát hiện; APK build ở Prompt 1 không chạy
  layout nên không lộ.

## Sửa trong Prompt 1 (ngoài scaffold + Design System)

- `carbon_api_service.dart`: giải mã body bằng **UTF-8** (`utf8.decode(bodyBytes)`)
  thay vì `response.body` — FastAPI trả `application/json` không kèm `charset`,
  package `http` mặc định giải mã Latin-1 làm hỏng dấu tiếng Việt trong
  `error.message`. Đọc lỗi theo **error contract nested** `detail.error.code` /
  `detail.error.message` (trước đọc `detail.error` như string — sai contract).
- `local_database.dart`: `openWith()` (chỉ dùng cho test) đặt
  `singleInstance: false` — nếu không, `databaseFactoryFfi` cache chung 1 DB
  `:memory:` giữa các test → rò dữ liệu, `UNIQUE` fail.
- Bỏ các API deprecated: `Supabase.initialize(anonKey:)` → `publishableKey:`;
  `RadioListTile.groupValue/onChanged` → `RadioGroup`; `DropdownButtonFormField.value`
  → `initialValue`. `flutter analyze` giờ sạch 0 cảnh báo.
- `dart format` (bước VERIFY) reflow ~18 file cũ về 80 cột — chỉ khoảng trắng,
  không đổi logic.

## Đặt lại mật khẩu qua deep link (Prompt 7)

**Đã cấu hình TRONG SOURCE:**
- Redirect URL cố định: `vn.agricarbon.mobile://reset-password`
  (`AppConfig.resetPasswordRedirect` — custom URL scheme = bundle id, KHÔNG phải
  domain, KHÔNG phải secret).
- `AuthService.sendPasswordReset` truyền `redirectTo: <URL trên>`.
- Android: `intent-filter` `VIEW` + `BROWSABLE` cho `scheme=vn.agricarbon.mobile`
  `host=reset-password` trên `MainActivity` (đã `exported`, `singleTop` — không
  thêm component exported mới, không mở cleartext).
- iOS: `CFBundleURLTypes` / `CFBundleURLSchemes = vn.agricarbon.mobile` trong
  `Info.plist` (custom scheme — không cần entitlement, không xin quyền camera/ảnh).
- `supabase_flutter` 2.17.2 tự chạy deep-link observer (`detectSessionInUri`
  mặc định `true`, PKCE): bắt URI có `code`, đổi lấy phiên, phát
  `AuthChangeEvent.passwordRecovery` → `AuthController` bật `isPasswordRecovery`
  → `AuthGate` hiện `ResetPasswordScreen` (KHÔNG vào Home). Đổi mật khẩu xong
  gọi `completePasswordRecovery()` → về shell. Link hỏng/hết hạn → lỗi stream
  auth → `AuthPhase.error` (màn "Thử lại"), KHÔNG crash, KHÔNG vào HomeShell.

**BƯỚC THỦ CÔNG (người triển khai phải làm — ngoài repo):**
1. Supabase Dashboard → **Authentication → URL Configuration → Redirect URLs** →
   thêm chính xác: `vn.agricarbon.mobile://reset-password`.
   (Không thêm thì link trong email bị Supabase từ chối redirect.)
2. Không cần đổi backend/migrations.

**Cách test deep link trên thiết bị thật:**
- Android: `adb shell am start -a android.intent.action.VIEW -d
  "vn.agricarbon.mobile://reset-password?code=TEST" vn.agricarbon.mobile`
  → app mở, hiện màn đặt mật khẩu mới (với `code` thật từ email thì đổi được).
- iOS (simulator): `xcrun simctl openurl booted
  "vn.agricarbon.mobile://reset-password?code=TEST"`.
- End-to-end: bấm "Quên mật khẩu" trong app → mở email trên chính thiết bị →
  chạm link → app bật lại ở `ResetPasswordScreen`.

## Nghiệm thu Flutter Mobile (Prompt 12)

### Luồng nghiệm thu đầu-cuối

`test/support/full_flow.dart` (chạy qua `test/app_flow_test.dart` headless, hoặc
`integration_test/app_flow_test.dart` trên device) đi hết 15 bước: mở app →
"restore/login" user A → chọn Farm → tạo Plot **offline** → tạo Crop Season
**offline** → nhập đủ 4 loại Activity (gồm harvest có sản lượng) → **đóng/mở lại
app** → khẳng định dữ liệu còn nguyên → bật "mạng" (fake) → **sync**: Plot 1 /
CropSeason 1 / Activity 4, không lỗi → **sync lần 2**: 0 bản ghi mới, gateway
vẫn chỉ thấy 4 upsert (idempotent) → **single-flight**: 2 `syncAll()` đồng thời
chỉ đẩy thêm đúng 1 activity mới → tính Carbon bằng fake contract → **thiếu sản
lượng** → `co2e_per_kg == null` và màn hiện "Chưa có sản lượng", KHÔNG "0" →
logout (đóng DB, giữ file) → login user B → **isolation**: user B không thấy
Farm / pending / Activity nào của user A → user A đăng nhập lại, dữ liệu còn
nguyên. **Không service-role key, không chạm Supabase/hosted.**

### Trạng thái theo FR (đối chiếu `docs/modules/01-mobile-app.md`)

| FR | Nội dung | Trạng thái phía mobile |
|---|---|---|
| **FR-1a-01** | Đăng nhập bằng tài khoản Supabase, giữ phiên | ✅ Xong (`auth_service` + `auth_controller` + `AuthGate`; restore phiên khi mở lại app). E2E hosted: chờ. |
| **FR-1a-02** | Ghi Activity **offline**, không mất khi mất mạng | ✅ Xong (SQLite per-user, `saveActivity` transactional; luồng nghiệm thu xác nhận sống sót restart). |
| **FR-1a-03** | 7 loại Activity với trường đặc thù + validate | ✅ Xong (`activity_form.dart` + `activity_field_spec` + `activity_validation`). |
| **FR-1a-04** | Đồng bộ lên hệ thống khi có mạng, **idempotent** | ✅ Xong phía client (ghi thẳng Supabase qua RLS + `(device_id, client_event_id)`; retry không tạo trùng — test với gateway giả). **Chờ E2E PostgREST thật.** |
| **FR-1a-05** | Xem kết quả CO₂e của vụ | ✅ Xong (`carbon_result_screen` gọi `/v1/carbon/*`). **Chờ** backend bật `carbon_production_ready` (scientific blocker). |
| **FR-1a-06** | Trạng thái đồng bộ rõ ràng cho từng bản ghi | ✅ Xong (`sync_tab` + `SyncCoordinator`, pending/syncing/synced/failed + retry_count). |
| **FR-1a-07** | Hồ sơ người dùng + đăng xuất | ✅ Xong (SVG 26 — `/v1/me`, đổi mật khẩu qua Supabase Auth, logout qua AuthGate). |
| **FR-1a-10** | Chọn/đổi Farm → Plot → Crop Season (ActiveContext) | ✅ Xong (`active_context` + `farm/plot/crop_season` screens, tự chọn khi không mơ hồ). |
| **FR-1a-11** | Đa nền tảng Android + iOS | ⚠️ Android: build `apk`/`aab` OK. iOS: cấu hình `ios/` tĩnh hợp lệ — **chờ macOS + Xcode + signing** để xác nhận build. |
| **NFR-01** | Offline-first: mọi thao tác nhập không phụ thuộc mạng | ✅ Xong (không có đường ghi nào chặn vì mạng; Farm là online-only theo thiết kế). |
| **NFR-02** | Không bịa số: `null` ≠ `0`, không hardcode dữ liệu mẫu | ✅ Xong (`AppFormat` trả "—"; `no_figma_placeholders_test` chốt `lib/` sạch chuỗi mẫu SVG; missing-yield hiển thị chữ). |
| **NFR-03** | Không lộ lỗi kỹ thuật cho nông dân; có hành động khôi phục | ✅ Xong (`auth_errors` / `friendlyMessage` dịch lỗi; `ErrorState` luôn kèm "Thử lại"; test "không lộ exception kỹ thuật"). |
| **FR-1b-01..04** | Điểm chạm CV: chụp/chọn ảnh lá → nhãn bệnh | ✅ Điểm chạm mobile xong (SVG 24). **Chờ ML**: chưa có model → `UnavailableCvInferenceService`. |
| **FR-1b-05..06** | Resource dashboard: 4 chỉ số/kg | ✅ Xong (module 04 — `GET .../metrics`, 2×2 grid, `data_completeness`). |
| **FR-1b-07..09** | Recommendation: khuyến nghị có impact + nguồn | ⏳ **Chờ backend**: OpenAPI chưa có endpoint → `UnavailableRecommendationRepository`; UI + hợp đồng `Recommendation.isValid` đã sẵn. |

### Phân loại rõ

- **Hoàn thành phía mobile:** 7/7 màn SVG + Resource dashboard; offline-first;
  sync idempotent (client) — bao gồm race unique 23505 và **tombstone/RLS**
  (chỉ hard-delete khi UPDATE tác động đúng 1 row, không mất row khi RLS ẩn);
  auth + session lifecycle; **Home lifecycle** (generation token + queued rerun
  + `_suspended` — không rò stale response / dữ liệu user cũ, không chạm DB đã
  đóng); error handling; single-flight; app-resumed; DB đóng khi đổi user;
  Android build (apk debug + apk/aab release).
- **Đang chờ backend:** Recommendation endpoint (FR-1b-07..09); `POST /v1/sync`
  không tồn tại (đã đi đường RLS); `harvest.loss_kg` thiếu cột; so sánh
  benchmark cấp vụ (`MetricResponse` không trả); **cơ chế ack xoá `activities`
  rõ ràng** (RPC hoặc policy cho chủ sở hữu thấy row đã soft-delete) — để dọn
  tombstone kể cả khi `count=exact` không tin được ở một cấu hình PostgREST lạ.
- **Đang chờ ML:** model phân loại bệnh lá (`ml/`) — FR-1b-01..04 chỉ mới xong
  điểm chạm tích hợp Flutter; nhận dạng end-to-end chưa có.
- **Scientific blocker:** `health.carbon_production_ready == false` (GWP/bộ hệ
  số chưa xác minh, OI-05) → màn carbon hiện banner "CHƯA phải kết quả MRV". Là
  trạng thái đúng, không phải bug app.
- **Chờ cấu hình hệ thống:** Supabase Redirect URL cho deep link reset mật
  khẩu; hosted E2E cho write/sync/`/v1/me`/carbon; macOS + Xcode + signing cho
  build iOS; keystore release Android (đang ký debug key — "build kỹ thuật đạt,
  chưa sẵn sàng phát hành").

### Checklist nghiệm thu thủ công (người nhận chạy)

Các mục sau CHƯA chạy được ở đây (không có thiết bị / hosted / macOS) — **không
đánh dấu đạt cho tới khi chạy thật**:

1. Login / restore / logout với Supabase **hosted**.
2. Reset-password: email thật + chạm deep link trên thiết bị.
3. User A / B với **RLS thật** (dữ liệu, cache, pending không lẫn nhau).
4. Airplane mode: nhập trọn một vụ (Farm chọn sẵn → Plot → Season → đủ Activity).
5. Tạo **20 Activity offline**.
6. Bật mạng → server nhận **đúng 20**.
7. Sync lần hai → server vẫn **đúng 20** (không trùng).
8. Kill app giữa lúc sync → mở lại: không mất, không trùng (`syncing` kẹt →
   `pending`).
9. **Thu hồi membership/RLS khi còn tombstone** → tombstone GIỮ nguyên (state
   `failed`/`notConfirmed`), không mất row, không tạo lại Activity; cấp lại
   quyền → lượt sync sau dọn được.
10. Carbon `/v1/carbon/*` + `/health` **thật** (kể cả `carbon_production_ready`).
11. Camera/gallery permission trên Android thật (granted/denied/permanently/
    restricted + nút mở Settings).
12. Camera/gallery permission trên iOS thật.
13. `pod install` + `flutter build ios --debug --no-codesign` rồi
    `flutter build ios --release` trên **macOS + Xcode** (Development Team +
    provisioning profile).
14. Cấu hình **Android release keystore** ngoài Git (`key.properties`) rồi
    `flutter build appbundle --release` ký khoá thật.
15. CV với **model/endpoint thật** khi nhóm ML bàn giao (đổi 1 dòng ở
    `AppServices.bootstrap`).
16. Người ngoài nhóm hoàn thành một lượt nhập trọn vụ **dưới 2 phút** (usability).

## Blocker / quyết định ngoài code

Những mục dưới đây KHÔNG sửa được trọn vẹn chỉ trong `app/**` — cần cấu hình hệ
thống ngoài hoặc quyết định sản phẩm:

- **Thêm Redirect URL vào Supabase Dashboard** — xem mục deep link ở trên (bước
  thủ công 1). Đây là phần duy nhất còn thiếu để luồng đặt lại mật khẩu chạy
  end-to-end; toàn bộ phần app đã nối trong source.
- **Lưu session bằng bộ nhớ mã hoá.** `supabase_flutter` 2.x (bản khoá) lưu
  session qua **SharedPreferences**, KHÔNG phải `flutter_secure_storage` (đó là
  mặc định của 1.x). Đây là file riêng của app trong sandbox, chưa mã hoá. Nâng
  lên Keychain/Keystore là quyết định gia cố bảo mật: cần `localStorage` tuỳ biến
  truyền vào `Supabase.initialize(authOptions:)` + kiểm thử thiết bị. Chưa làm.
- **File `agricarbon.db` cũ (một file dùng chung, trước Prompt 3).** KHÔNG nhập
  tự động: schema cũ không có `owner_user_id` nên không quy được dữ liệu về đúng
  chủ mà không rò sang tài khoản khác. Bản MVP 1a chưa từng compile/chạy (commit
  `c6e8b97`) nên thực tế không có dữ liệu thật. Nếu môi trường nào có file này,
  giữ nguyên và quyết định nhập thủ công.
- **`POST /v1/sync` không tồn tại** ở backend → app ghi thẳng Supabase qua RLS
  (xem §Kiến trúc). Nếu backend thêm endpoint sync, cần thiết kế lại tầng đẩy.
- **`harvest.loss_kg`** (SRS liệt kê) không có cột trong `harvest_events` — cần
  thêm cột ở backend trước khi thu thập field này.

## Giới hạn đã biết

- **Hosted Supabase / backend E2E cho luồng GHI/sync + `/v1/me` + carbon chưa
  chạy** — logic đúng theo schema/RLS/OpenAPI đã đọc + test đầy đủ với
  `SyncGateway` / `CarbonApiService` / `ReadApi` giả (không chạm mạng), nhưng
  chưa đối chiếu PostgREST + FastAPI thật (điều kiện chung của dự án). Xem
  §Nghiệm thu.
- **Màn CV (`camera_cv_screen.dart`) — điểm chạm đã xong, suy luận chưa** —
  chụp/chọn ảnh + quyền + phản hồi local đầy đủ; model phân loại bệnh lá ở
  `ml/` (ngoài `app/`) chưa tồn tại nên `AppServices.cvInference` =
  `UnavailableCvInferenceService` → màn hiện "Nhận dạng bệnh chưa được cấu
  hình", KHÔNG bịa nhãn/độ tin cậy. Khi có model/endpoint thật: đổi 1 dòng ở
  `AppServices.bootstrap`, UI không sửa.
- **Farm creation là online-only** — hộ/trang trại hiếm khi tạo mới, không đáng đưa vào
  hàng đợi offline. Plot/CropSeason/Activity đều offline-first đầy đủ.
- Backend trả 404 (không phải 403) khi RLS từ chối — cố ý, tránh lộ một vụ tồn tại
  nhưng thuộc nông hộ khác (`docs/BACKEND_1A.md` §9). App xử lý đúng theo 404 đó.
- Retry tự động theo lịch, xử lý mất mạng giữa chừng lúc đồng bộ (partial batch)
  — chưa làm, ngoài phạm vi walking skeleton. Pull-to-refresh, hạ trạng thái khi
  mất mạng, gỡ bản ghi synced server bỏ (reconcile) đã có.

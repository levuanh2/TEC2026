# app/ — Mobile App ghi nhật ký canh tác

- **Lớp MVP:** 1a (Walking Skeleton) — đường găng.
- **Phụ trách:** Người A.
- **Đặc tả:** [`../docs/modules/01-mobile-app.md`](../docs/modules/01-mobile-app.md) ·
  [`../docs/BACKEND_1A.md`](../docs/BACKEND_1A.md) (API contract, auth/RLS)

## ⚠️ TRẠNG THÁI VERIFY — ĐỌC TRƯỚC KHI TIN BẤT KỲ DÒNG NÀO Ở DƯỚI

**Toàn bộ code trong `app/` viết ra ở phiên này CHƯA TỪNG ĐƯỢC BIÊN DỊCH, CHẠY, HAY TEST.**
Máy viết code này không có Flutter/Dart SDK cài đặt (`flutter`, `dart` đều không có
trong PATH, thư mục `c:\flutter` không tồn tại dù có trong biến môi trường).

Khác với `backend/` — nơi **mọi dòng đã chạy thật** (101 test pytest, smoke test thật
trên Supabase hosted, verify bằng Postgres thật — xem `docs/BACKEND_1A.md`) — phần
`app/` này chỉ được viết cẩn thận theo đúng cú pháp Dart/Flutter và API package tôi
nắm chắc, đối chiếu kỹ với schema/API thật của backend, nhưng **chưa có tín hiệu thực
thi nào xác nhận nó đúng.**

**Việc đầu tiên phải làm trước khi tin cậy bất kỳ phần nào:**

```bash
cd app
flutter pub get
flutter analyze          # bắt lỗi cú pháp/type — bước tối thiểu phải xanh
flutter test              # 3 file test — xem §"Tests" dưới, cũng chưa từng chạy
```

Nếu `flutter analyze` báo lỗi, đó là việc cần sửa đầu tiên — không phải bug nghiệp vụ,
mà là chỗ tôi đoán sai API mà không có cách tự kiểm.

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

## Cấu trúc

```text
app/
├── lib/
│   ├── main.dart                     # khởi tạo Supabase, điều hướng Login/Farm
│   ├── config.dart                   # đọc --dart-define
│   ├── app_services.dart             # gói service dùng chung (không Provider/Riverpod)
│   ├── models/
│   │   ├── farm.dart, plot.dart, crop_season.dart
│   │   ├── activity.dart             # SyncState ngay trên activity — không bảng riêng
│   │   ├── activity_field_spec.dart  # đặc tả field cho 7 loại hoạt động
│   │   └── carbon_result.dart        # parse response backend
│   ├── db/
│   │   └── local_database.dart       # SQLite: farms/plots/crop_seasons/activities
│   ├── services/
│   │   ├── auth_service.dart         # Supabase Auth, token do package tự giữ an toàn
│   │   ├── device_service.dart       # installation_id ổn định + devices.id thật
│   │   ├── sync_service.dart         # đẩy pending lên Supabase, idempotent
│   │   └── carbon_api_service.dart   # gọi FastAPI /v1/carbon/*
│   └── screens/
│       ├── login_screen.dart
│       ├── farm_screen.dart, plot_screen.dart, crop_season_screen.dart
│       ├── crop_season_detail_screen.dart  # hub: 7 nút loại hoạt động + Xem CO2e
│       ├── activity_form_screen.dart       # 1 form động, không phải 7 file riêng
│       └── carbon_result_screen.dart
└── test/
    ├── local_database_test.dart      # offline + sync state (sqflite_common_ffi, không cần thiết bị)
    ├── activity_model_test.dart      # round-trip payload, client_event_id ổn định
    └── carbon_result_parsing_test.dart  # co2e_per_kg=null KHÔNG phải 0
```

## Offline-first — nguyên tắc bắt buộc (NFR-01)

`activity_form_screen.dart` ghi thẳng vào SQLite khi bấm "Lưu" — **không gọi mạng ở
bước này, dưới bất kỳ hình thức nào.** Đồng bộ là hành động riêng (nút "Đồng bộ ngay"
ở `crop_season_detail_screen.dart`), người dùng tự bấm khi có mạng.

## Đồng bộ — idempotent bằng đúng cơ chế Supabase đã có

`id` của `Activity` cục bộ **chính là** `client_event_id` gửi lên Supabase. Ghép với
`device_id` (đăng ký qua `device_service.dart`, ổn định qua các lần mở app nhờ
`shared_preferences`), unique index `(device_id, client_event_id)` khiến việc gửi lại
(retry) không bao giờ tạo bản ghi trùng — `upsert` chứ không `insert`.

Batch (`production_batches`) là bắt buộc ở tầng schema (`activities.production_batch_id
NOT NULL`) dù carbon tính theo Crop Season. App **tự tạo 1 batch mặc định mỗi vụ**
(`batch_code = 'default'`), nông dân không nhìn thấy khái niệm này — đúng tinh thần
"Production Batch là traceability" (Phase 10 của đề bài).

## Carbon Result — không tính gì trong app

`carbon_result_screen.dart` chỉ gọi `POST /v1/carbon/calculate` / `GET .../carbon` và
hiển thị đúng response. `co2e_per_kg == null` hiện dòng "Chưa tính được CO2e/kg. Vui
lòng bổ sung sản lượng thu hoạch." — **không bao giờ hiện "0"** (khớp
`docs/BACKEND_1A.md` §9, engine NFR-03).

## Giới hạn đã biết (ngoài việc chưa compile)

- **Farm creation là online-only** — hộ/trang trại hiếm khi tạo mới, không đáng đưa vào
  hàng đợi offline. Plot/CropSeason/Activity đều offline-first đầy đủ.
- **`harvest.loss_kg`** (SRS liệt kê) không có cột tương ứng trong `harvest_events` —
  form hiện tại chưa thu thập field này (không có chỗ lưu có cấu trúc). Cần bổ sung
  cột ở backend trước khi thêm field.
- Backend trả 404 (không phải 403) khi RLS từ chối — cố ý, tránh lộ một vụ tồn tại
  nhưng thuộc nông hộ khác (`docs/BACKEND_1A.md` §9). App xử lý đúng theo 404 đó.
- Chưa có widget test (cần thiết bị/emulator) — chỉ có unit test logic thuần
  (`local_database_test.dart` dùng `sqflite_common_ffi`, chạy được trên desktop
  KHÔNG cần emulator, nhưng vẫn cần Flutter SDK để chạy `flutter test`).
- Pull-to-refresh, xử lý mất mạng giữa chừng lúc đồng bộ (partial batch), retry tự
  động theo lịch — chưa làm, ngoài phạm vi walking skeleton.

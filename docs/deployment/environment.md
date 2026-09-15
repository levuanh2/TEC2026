# Biến môi trường

Chỉ liệt kê **tên** biến. Không ghi giá trị; không commit `.env`, `.supabase.env` hay
mật khẩu QA.

## Backend

Đọc trong `backend/infrastructure/config.py` (từ biến môi trường tiến trình hoặc
`backend/.env`; biến môi trường thật luôn thắng file). Mẫu: `backend/.env.example`.

| Biến | Bắt buộc | Dùng cho |
|---|---|---|
| `SUPABASE_URL` | Có | Mọi kết nối Supabase |
| `SUPABASE_PUBLISHABLE_KEY` | Có | Đọc bằng JWT người gọi (RLS), kiểm quyền |
| `SUPABASE_SERVICE_ROLE_KEY` | Có | Carbon repository, Storage (ảnh CV, artifact MRV). **Chỉ ở backend** |
| `SUPABASE_DB_URL` | Có cho ghi | Activity write, recommendation, CV, MRV export (psycopg). **Chỉ ở backend** |
| `AGRICARBON_EF_CONFIG` | Không | Đường dẫn YAML tham số (mặc định `config/emission_factors.yaml`) |
| `AGRICARBON_REQUIRE_FACTOR_SET_IN_DB` | Không | Được đọc vào `Settings`; hiện không có code nào dùng giá trị này |
| `AGRICARBON_CORS_ORIGINS` | Không | Danh sách origin, phân tách dấu phẩy (mặc định `http://localhost:5173,http://127.0.0.1:5173`) |
| `AGRICARBON_SERVER_TIMING` | Không | Bật header `Server-Timing` để đo hiệu năng (mặc định tắt) |

## Web

Đọc qua `import.meta.env` trong `web-dashboard/src`. Mẫu: `web-dashboard/.env.example`.
Biến `VITE_*` được nhúng vào bản build và **công khai** với trình duyệt.

| Biến | Dùng cho |
|---|---|
| `VITE_API_BASE_URL` | Gốc URL FastAPI (mặc định trong code `http://127.0.0.1:8000`) |
| `VITE_SUPABASE_URL` | Supabase Auth |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Supabase Auth (publishable key, không phải service role) |
| `VITE_USE_MOCK_DATA` | `true` bật dữ liệu giả để demo UI; mặc định `false` |

## Flutter

Truyền qua `--dart-define` (`app/lib/config.dart`, mẫu `app/config/dev.example.json`).

| Biến | Dùng cho |
|---|---|
| `SUPABASE_URL` | Supabase Auth + PostgREST |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase (publishable key) |
| `BACKEND_BASE_URL` | FastAPI (Carbon, metrics, `/v1/me`) |

## QA / E2E

Mọi test dùng tài khoản thật đều bị **gate** bằng biến cờ; tài khoản QA chỉ dùng cho
demo/QA và mật khẩu chỉ truyền qua biến môi trường tiến trình.

| Nhóm | Biến |
|---|---|
| Flutter integration test | `QA_EMAIL`, `QA_PASSWORD`, `QA_CROSS_ACTIVITY_ID` (cùng `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`) |
| Playwright Management thật | `REAL_E2E`, `REAL_E2E_BASE_URL`, `REAL_E2E_API_BASE_URL`, `REAL_E2E_EMAIL`, `REAL_E2E_PASSWORD`, `REAL_MRV_EXPORT_E2E` |
| Playwright Farmer thật | `FARMER_REAL_E2E`, `FARMER_REAL_E2E_EMAIL`, `FARMER_REAL_E2E_PASSWORD`, `FARMER_REAL_WRITE_E2E`, `FARMER_REAL_RECOMMENDATIONS_E2E`, `FARMER_REAL_CV_E2E` |
| Playwright chung | `CI` |
| Backend test tích hợp | `SUPABASE_DB_URL` |

## Scripts

| Script | Biến |
|---|---|
| `backend/scripts/seed_demo_data.py` | `MANAGER_PASSWORD`, `ENTERPRISE_PASSWORD` (chỉ khi tạo mới user demo) + biến backend |
| `backend/scripts/create_farmer_qa_identity.py` | `QA_FARMER_EMAIL`, `QA_FARMER_PASSWORD` + biến backend |
| Supabase CLI | `SUPABASE_ACCESS_TOKEN` (mẫu `.supabase.env.example`) |

!!! warning "Tài liệu cũ lệch với code"
    `infra/README.md` còn liệt kê `AGRICARBON_DB_URL` và `AGRICARBON_API_BASE`; code hiện
    tại **không** đọc hai biến này.

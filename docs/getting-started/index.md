# Chạy hệ thống local

Trang này tổng hợp cách chạy từng phần **theo đúng file cấu hình có trong repo**.
Không có Docker, docker-compose hay CI/CD nào trong repository — mỗi phần chạy
riêng.

## Cấu trúc repository

| Thư mục | Nội dung |
|---|---|
| `backend/` | FastAPI (`main.py`, `api.py`, `service.py`), Carbon Engine (`carbon/`), Recommendation (`recommendation/`), MRV renderer (`mrv/`), hạ tầng (`infrastructure/`), test (`tests/`), script demo/QA (`scripts/`) |
| `web-dashboard/` | Một ứng dụng React + Vite chứa cả Farmer Web (`src/farmer/`) và Management Web (`src/pages/`, `src/features/`) |
| `app/` | Flutter Mobile (`lib/`, `test/`, `integration_test/`) |
| `ml/` | Pipeline CV: chuẩn bị dataset, train, evaluate, infer |
| `supabase/` | `config.toml` và chuỗi migration SQL |
| `docs/` | Bộ tài liệu này + các báo cáo/đặc tả lịch sử |

## Yêu cầu

- Python 3.11 (môi trường phát triển hiện tại của nhóm)
- Node.js tương thích Vite 7 (xem `web-dashboard/package.json`)
- Flutter SDK (xem `app/pubspec.yaml`)
- Một dự án Supabase đã chạy chuỗi migration trong `supabase/migrations/`

## 1. Backend (FastAPI)

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows; macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -r ../ml/requirements.txt
cp .env.example .env              # điền giá trị thật, KHÔNG commit .env
uvicorn main:app --reload --port 8000
```

!!! warning "Backend cần cả dependency của `ml/`"
    `backend/service.py` import `ml.infer` ngay khi khởi động (để phục vụ route
    CV), và `ml/infer.py` import `torch`, `torchvision`, `PIL`. Các gói này nằm
    trong `ml/requirements.txt`, **không** nằm trong `backend/requirements.txt`.
    `ml/requirements.txt` gợi ý cài bản CPU:
    `pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`.

Hành vi khi thiếu cấu hình (theo `backend/main.py`):

- Không có `.env`: app vẫn chạy, `GET /health` báo `supabase_configured: false`,
  các route cần repository trả `503 backend_not_configured` — không chạy bằng dữ
  liệu giả.
- Không có checkpoint trong `ml/runs/`: các route CV trả `503`, phần còn lại
  của API vẫn hoạt động.

Kiểm tra nhanh:

```bash
curl http://127.0.0.1:8000/health
```

`carbon_production_ready` chỉ là `true` khi GWP đã có giá trị; với YAML hiện tại
giá trị này là `false`.

## 2. Web (Farmer + Management)

```bash
cd web-dashboard
npm install
cp .env.example .env              # VITE_API_BASE_URL phải trỏ đúng cổng uvicorn
npm run dev                       # Vite mặc định http://localhost:5173
```

- `AGRICARBON_CORS_ORIGINS` của backend mặc định là
  `http://localhost:5173,http://127.0.0.1:5173`; chạy web ở origin khác thì phải
  thêm vào biến này.
- `VITE_USE_MOCK_DATA=true` chỉ để demo UI không cần backend; nhãn "MOCK DATA"
  sẽ hiện. Mặc định là `false`.
- Sau khi đăng nhập, tài khoản có role phân giải là `farmer` được đưa vào
  `/farmer`, các role khác vào `/dashboard`.

## 3. Flutter Mobile

Flutter không dùng file `.env`; cấu hình truyền qua `--dart-define`
(`app/lib/config.dart`, mẫu `app/config/dev.example.json`):

```bash
cd app
flutter pub get
flutter run \
  --dart-define=SUPABASE_URL=<url dự án> \
  --dart-define=SUPABASE_PUBLISHABLE_KEY=<publishable key> \
  --dart-define=BACKEND_BASE_URL=http://10.0.2.2:8000
```

`10.0.2.2` là địa chỉ máy host khi chạy Android emulator. Bản debug cho phép
cleartext HTTP tới `10.0.2.2`/`localhost`/`127.0.0.1`; bản release chặn cleartext.

## 4. Mô hình CV (tuỳ chọn)

```bash
pip install -r ml/requirements.txt
python -m ml.dataset_prep      # sau khi tải dataset Mendeley vào ml/datasets/raw/
python -m ml.train
python -m ml.evaluate --checkpoint ml/runs/<run_name>/model.pt
```

Backend nạp run mới nhất trong `ml/runs/` (cần `model.pt` và
`eval_metrics.json`). Thư mục này không được git track.

## 5. Database

- Schema nằm trong `supabase/migrations/` (11 file, từ `20260907000000_baseline.sql`
  tới `20260913150000_mrv_xlsx_export_artifacts.sql`), dùng Supabase CLI với
  `supabase/config.toml`. Lịch sử áp dụng: `docs/MIGRATION_HISTORY.md`.
- Bucket Storage phải tạo **thủ công** (baseline cố ý không insert
  `storage.buckets`): `plant-images`, `mrv-evidence`, `mrv-exports`, đều riêng tư.
- Bộ hệ số phát thải phải được import vào `emission_factor_sets`/`emission_factors`
  với `version_code` trùng `backend/config/emission_factors.yaml` và
  `status = published`; nếu không, lưu bản tính trả `503 factor_set_not_imported`.
- `backend/scripts/seed_demo_data.py` / `cleanup_demo_data.py` tạo và dọn tenant
  demo `DEMO-AGRICARBON-2026` (không ghi `carbon_calculations`).

## 6. Test

| Phần | Lệnh | Ghi chú |
|---|---|---|
| Backend | `cd backend && python -m pytest tests -q` | Dùng repository giả/fixture; `tests/fixtures/test_factors.yaml` là **TEST ONLY**, không phải giá trị khoa học |
| ML | `python -m pytest ml/tests -q` | Không cần dataset thật |
| Web unit | `cd web-dashboard && npm test` | Vitest |
| Web E2E mock | `npx playwright test` | `playwright.config.ts` |
| Web E2E thật | `npx playwright test --config playwright.real.config.ts` | Bị chặn bởi biến môi trường cờ + tài khoản QA; xem [Biến môi trường](../deployment/environment.md) |
| Flutter | `cd app && flutter test` | `integration_test/` cần thiết bị/emulator |

## 7. Site tài liệu này

```bash
pip install -r docs/requirements.txt
mkdocs serve                    # http://127.0.0.1:8000 — trùng cổng mặc định của uvicorn,
                                # dùng `mkdocs serve -a 127.0.0.1:8001` nếu backend đang chạy
mkdocs build --strict
```

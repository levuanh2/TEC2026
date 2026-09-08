# Backend bug tìm thấy sau khi freeze REST API

Backend REST API đã freeze (2026-09-08). Ghi ở đây thay vì đổi contract —
mục này KHÔNG đổi response/error format/pagination/Carbon scope/RLS/DB.

## 1. Thiếu CORS middleware (2026-09-09) — ĐÃ SỬA, được user chấp thuận

**Phát hiện qua**: browser QA thật (preflight request thật, không phải curl
đoán) — `OPTIONS /v1/farms` với header `Origin: http://localhost:5173` trả
`405 Method Not Allowed`, KHÔNG có header `Access-Control-Allow-Origin`.

**Tác động**: mọi `fetch()` từ React (chạy trên origin `localhost:5173` khác
origin backend `127.0.0.1:8000`) bị TRÌNH DUYỆT chặn hoàn toàn trước khi
request rời đi — khác hẳn 401/403 (đó là backend từ chối sau khi nhận request).
Không phải lỗi riêng của Carbon hay bất kỳ route nào — chặn TOÀN BỘ `/v1/*`.
Vì mọi test trước đó (unit test, hosted E2E) đều dùng `curl`/`TestClient`
(không thực thi CORS như trình duyệt), lỗi này không bị phát hiện cho tới khi
làm browser QA thật.

**Fix**: thêm `CORSMiddleware` (`backend/main.py`), origin lấy từ
`AGRICARBON_CORS_ORIGINS` (mặc định `http://localhost:5173,http://127.0.0.1:5173`
— origin Vite dev, không phải URL production, không hardcode). Chỉ set
`allow_origins`/`allow_methods`/`allow_headers` — KHÔNG đổi response body, lỗi,
route, hay bất kỳ hành vi nghiệp vụ nào. `Settings.cors_origins` thêm vào
`infrastructure/config.py`.

**Verify thật**: khởi động lại `uvicorn`, gọi `OPTIONS /v1/farms` với
`Origin: http://localhost:5173` → `200` + `Access-Control-Allow-Origin` đúng;
với `Origin: https://evil.example` → `400 Disallowed CORS origin`, không có
header allow — đúng hành vi mong đợi. 2 test mới trong
`backend/tests/test_read_repository.py`
(`test_cors_preflight_allows_configured_dev_origin`,
`test_cors_rejects_unlisted_origin`).

**Được duyệt sửa**: user chấp thuận rõ ràng qua AskUserQuestion trong phiên
này ("Cho phép thêm CORS middleware (không đổi API contract)") — đúng loại
"bug nhỏ bắt buộc để React chạy", không phải tự ý đổi backend.

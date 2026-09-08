# Sync Architecture Gap — ghi nhận có chủ đích, không tự sửa

Ngày: 2026-09-08

## Hiện trạng

Backend **không có** `POST /v1/sync`. Flutter (`app/`) ghi Activity/Plot/CropSeason
**trực tiếp vào Supabase** qua publishable key + JWT người dùng, RLS quyết định
quyền — xem `docs/FRONTEND_API_CONTRACT.md` §5. React (`web-dashboard/`) chỉ **đọc**
qua FastAPI (`GET /v1/...`), không ghi trực tiếp Supabase.

## Vì sao đây là một "gap", không phải bug

Task hoàn thiện REST API backend hiện tại (2026-09-08) đặt nguyên tắc: *"Không để
frontend truy cập business data trực tiếp từ Supabase"*. Kiến trúc Flutter hiện tại
(ghi thẳng Supabase) **vi phạm nguyên tắc đó cho phía ghi**, nhưng:

1. Flutter MVP 1a đã viết xong theo kiến trúc ghi-thẳng-Supabase, CHƯA compile/chạy
   thử (không có Flutter SDK trên máy build), và task hiện tại đã đóng băng mọi việc
   Flutter ("Tạm thời GÁC TOÀN BỘ FLUTTER").
2. Đổi kiến trúc ghi ngay bây giờ nghĩa là viết `POST /v1/sync`, đổi lại toàn bộ
   `sync_service.dart`/`device_service.dart`, và test lại — đúng là việc Flutter,
   không phải việc REST-API-đọc đang làm.
3. Đề bài hiện tại nói rõ: *"Backend hiện không có `/v1/sync`... KHÔNG tự thêm sync
   endpoint... Document SYNC ARCHITECTURE GAP"* thay vì tự ý đổi.

## Kết luận

- **KHÔNG** thêm `POST /v1/sync` trong lần hoàn thiện REST API đọc này.
- Kiến trúc GHI (Flutter → Supabase trực tiếp qua RLS) giữ nguyên, được coi là gap
  đã biết, cần một task riêng ("Backend Sync Ingestion") nếu muốn thống nhất mọi
  truy cập — cả đọc lẫn ghi — qua FastAPI.
- Kiến trúc ĐỌC (Flutter đọc `/v1/carbon/*` qua FastAPI; React đọc toàn bộ `/v1/*`
  qua FastAPI, không đọc bảng Supabase trực tiếp) đã tuân thủ nguyên tắc mới.
- Khi task Flutter được mở lại, việc đầu tiên cần quyết định: giữ ghi-thẳng-Supabase
  (đơn giản, RLS đã đúng, đã viết) hay chuyển sang `POST /v1/sync` (đúng nguyên tắc
  "1 cổng vào" hơn, nhưng tốn công viết lại + cần idempotency ở tầng FastAPI thay vì
  dựa vào `upsert(onConflict: ...)` sẵn có của Postgrest).

# AgriCarbon — Performance: kết nối, cache, lazy loading (2026-11-04)

Phạm vi: Web Management (HTX) trên `https://agricarbon.info.vn`, API `https://api.agricarbon.info.vn`
(AWS EC2), Supabase `awazhdqzkktekbwaqiic`. Mọi số dưới đây là số **đo thật**; số nào chưa đo được
thì ghi là chưa đo. Không có tỷ lệ % cải thiện tự suy ra.

## 1. P0 — Chẩn đoán lỗi kết nối (bằng chứng)

### 1.1 Hạ tầng đo được

| Thành phần | Thực tế | Nguồn |
|---|---|---|
| EC2 | `t3.small`, 2 vCPU, 1.9 GB RAM, không swap, `ap-southeast-2b` (Sydney); load ~0.00, RAM dùng 610 MB | IMDS, `free`, `/proc/loadavg` |
| API | 1 container `agricarbon-api` (uvicorn `--workers 1`) sau Caddy (h2/h3, gzip) | `docker inspect`, `/etc/caddy/Caddyfile` |
| DB | Supabase Postgres 17.6 ở `ap-northeast-2` (Seoul); `authenticated` có `statement_timeout = 8s` | pooler probe, `pg_roles` |
| DNS API | Cloudflare (DNS-only), A `3.24.114.143`, TTL 300 s, không có AAAA | `nslookup` |

IP `3.25.91.97` (lệnh SSH cũ) không còn trả lời cổng 22 hay 443. Instance hiện tại đã khởi động lại lúc 07:21 UTC
cùng ngày, và DNS đang trỏ về `3.24.114.143`.

### 1.2 Nguyên nhân gốc #1 — psycopg không bao giờ kết nối được DB (ĐÃ SỬA trên EC2)

`SUPABASE_DB_URL` trỏ tới host trực tiếp `db.<ref>.supabase.co:5432`. Host này **chỉ có IPv6**
(`2406:da12:…`), mà EC2 không có IPv6 → `connection is bad: … Network is unreachable` (30 lần
trong log). Mọi route đi qua pool psycopg phải chờ hết `PoolTimeout` 30 s:

| Route | Trước khi sửa (access log) |
|---|---|
| `GET /organizations/{id}/carbon-status` | **200 sau 60.8–61.3 s** (4 lần): `get_crop_bundles` rồi `latest_calculations`, mỗi bước chờ 30 s, sau đó cả 27 vụ đều trả `readiness_error`/`actual_error` |
| `GET /organizations/{id}/farmers` | **503 sau 30.2–30.6 s** (2 lần) |
| Ghi nhật ký, tính Carbon, MRV export… | cùng pool → cùng một lỗi |

Đã sửa theo phê duyệt: chuyển `SUPABASE_DB_URL` sang Supavisor **session pooler IPv4**
`aws-0-ap-northeast-2.pooler.supabase.com:5432` (user `postgres.<ref>`, giữ nguyên mật khẩu),
rồi tạo lại container với đúng tham số cũ. Không đổi code, dữ liệu hay schema.

- Backup: `/etc/agricarbon/api.env.bak-20261104T083233Z`. Log trước khi sửa:
  `/var/log/agricarbon/api-before-20261104T083233Z.log`. Container cũ được giữ lại (đã dừng):
  `agricarbon-api-old-20261104T083233Z`.
- Rollback: `sudo cp /etc/agricarbon/api.env.bak-20261104T083233Z /etc/agricarbon/api.env`, rồi
  `docker rm -f agricarbon-api && docker rename agricarbon-api-old-20261104T083233Z agricarbon-api && docker start agricarbon-api`.
- Sau khi sửa: dùng chính `infrastructure.pg_pool` trong container, `select 1` qua pool chạy được
  (lần đầu 1835 ms, các lần sau 549–585 ms); log không còn `Network is unreachable`.

### 1.3 Nguyên nhân gốc #2 — RLS chạy theo từng dòng (PR riêng, CHƯA apply)

`activities_select` (và 7 bảng chi tiết) gọi `private.user_can_read_batch()` cho **từng dòng**.
EXPLAIN ANALYZE dưới quyền Manager HTX-DEMO-001 (transaction chỉ đọc, rollback): đọc 258 activities
mất 2302 ms, đọc phân bón mất 3674 ms, toàn bộ là CPU (58k/95k buffer hit). Với cả 13 user có
membership, `select id from activities` mất 3.7–7.3 s, kể cả user thấy 0 dòng. Khi `summary`,
`metrics`, `farm-performance` và `carbon-status` chạy cùng lúc, các truy vấn này chạm
`statement_timeout` → **500** (`canceling statement due to statement timeout`, 4 lần trong log).
→ Xem PR `perf/rls-set-based-activity-reads`. Probe chỉ đọc cho thấy tập dòng giống hệt cho cả
13 user (activities + 7 bảng con), thời gian ~150 ms.

### 1.4 Mạng và địa lý (đo, chưa sửa)

- Từ máy dev ở Việt Nam tới API: TCP 0.32–0.39 s, TLS 0.33 s (lần nguội 2.4 s), `/health` 1.02–1.11 s.
  20/20 lần kết nối không có lần nào gửi lại SYN.
- EC2 (Sydney) ↔ DB (Seoul): `select 1` ~138 ms mỗi lượt khứ hồi; mỗi lần mượn kết nối + truy vấn
  qua pool tốn ~550 ms. Route có 4–6 lượt gọi DB tuần tự sẽ tốn 0.7–2 s chỉ vì khoảng cách.
- **Khuyến nghị (cần quyết định hạ tầng):** chuyển EC2 sang `ap-northeast-2` (cùng vùng với DB).
- **"Initial connection 10.28 s":** không tái hiện được từ máy đo (20/20 kết nối sạch). Giả thuyết
  CHƯA kiểm chứng: trình duyệt còn cache DNS trỏ tới IP cũ `3.25.91.97` trong lúc đổi IP, hoặc mất
  SYN (Windows gửi lại SYN sau 3 s rồi 6 s, cộng ~1 s RTT/TLS ≈ 10 s). Backend log không thấy được
  khoảng thời gian này, vì nó xảy ra trước khi request tới FastAPI.

## 2. P1–P4 — Thay đổi frontend (nhánh `perf/web-query-cache-lazy-loading`)

- **Cache dùng chung** `@tanstack/react-query` 5.104.4 (pin): chỉ trong bộ nhớ, key =
  `['u', userId, 'org', orgId, resource]`; xoá khi đăng xuất, khi phiên hết hạn, và khi đổi user
  (kể cả đổi từ tab khác). `staleTime` 45 s cho dữ liệu nghiệp vụ, 5 phút cho metadata HTX và engine.
  Lỗi không bao giờ được cache thành dữ liệu.
- **Dashboard / Vụ mùa / Dữ liệu thiếu / Carbon** dùng chung 4 query cấp tổ chức (+ engine). Mỗi
  nguồn có trạng thái riêng: `carbon-status` chậm hay lỗi không còn giữ cả trang ở trạng thái loading;
  nguồn lỗi hiện "—" chứ không hiện 0; Carbon chỉ trả lời được một phần vụ thì ô số được đánh dấu
  "+?" kèm số vụ chưa đọc được. MRV lỗi được báo ra (trước đây bị nuốt và hiện thành 0). Khi refresh
  lỗi: vẫn giữ dữ liệu cũ, kèm thông báo "đọc lúc HH:MM — có thể đã cũ" và nút Thử lại.
- **N+1:** `/farms` từng đọc `GET /farms/{id}/plots` tuần tự cho từng hộ (log production: 8 request
  cách nhau ~1 s). Nay lấy diện tích từ `plots-seasons` (1 request, dùng chung cache với Dashboard).
  Hộ nào không nằm trong listing thì đọc song song (bị giới hạn bởi limiter), không đọc tuần tự.
- **Lazy + prefetch:** bảng farm-performance ở trang Tổ chức chỉ được tải khi nằm trong vòng
  300 px quanh vùng nhìn thấy (`IntersectionObserver`, có tính tới container cuộn lồng nhau).
  Code-splitting theo route bằng `React.lazy`; Login, khôi phục phiên, đổi mật khẩu bắt buộc, shell
  và trang chủ vận hành vẫn nằm trong chunk đầu. Hover hoặc focus vào link sẽ prefetch chunk của
  route và các query đầu trang (có dedup với cache). Có `preconnect` tới API/Supabase.
- **Abort:** query riêng của từng trang (ví dụ trang một nông hộ) bị huỷ khi rời trang. Query dùng
  chung cấp tổ chức thì cố ý KHÔNG huỷ, vì trang kế tiếp cần đúng câu trả lời đó (huỷ rồi gửi lại chỉ
  làm server tính lại).
- **Network safety:** GET có timeout 30 s (ghi thì không); tối đa 4 GET chạy đồng thời (ghi không
  phải xếp hàng); retry tối đa 2 lần, chỉ cho lỗi mạng/502/503/504, không bao giờ retry
  401/403/404/422/500/timeout; ghi thành công thì invalidate các query tổ chức/nông hộ.
  Cloudflare không cache API (DNS-only), không thay đổi gì ở đây.
- **Không đổi** API contract, RBAC/RLS (ở PR này), dữ liệu Supabase hay công thức Carbon.

## 3. Kết quả kiểm thử

| Kiểm tra | Kết quả |
|---|---|
| `tsc -b` | pass |
| Vitest | 77 file, 597 test pass (thêm: limiter/timeout/abort/retry, scope cache theo user, từng nguồn của ops, dùng lại cache, refresh lỗi, N+1 `/farms`, lazy 300 px) |
| `vite build` | pass. Chunk đầu 571.50 kB (gzip 167.14) so với `main` 749.17 kB (gzip 213.76), cùng env build |
| Playwright mock (`--workers=2`, như CI) | 111/111 pass |
| Playwright mock (số worker mặc định, máy dev) | Lần đầu: 17 lỗi (timeout khi Vite dev biên dịch chunk lazy lần đầu dưới tải song song; `main` cùng điều kiện: 111/111). Đã sửa bằng `server.warmup` trong `vite.config.ts`. Sau khi sửa, chạy 3 lần: 110/111 (1 lỗi console ở `sidebar-parity` 1280px, chạy riêng thì pass, lần đó không giữ được chi tiết), 111/111, 111/111 |
| Đo trình duyệt thật (Manager/Farmer, cold/warm/back/hard refresh, mạng chậm, backend ngắt) | **CHƯA ĐO** — cần mật khẩu QA cho phiên này |

## 4. Việc còn mở

1. Đo trình duyệt thật trước/sau (script: đo từng request DNS/TCP/TLS/TTFB, số request, lỗi, thời
   điểm ô số hiện số cuối cùng). Cần credentials Manager và Farmer.
2. Deploy frontend (Render) và apply migration RLS lên hosted: chờ phê duyệt.
3. Quyết định chuyển vùng EC2.

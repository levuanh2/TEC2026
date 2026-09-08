# Figma → Web Dashboard Implementation

Ngày: 2026-09-09. Nguồn: Figma REST API thật (`X-Figma-Token`, file
`rbASkk93CEOFLbp78B4S1o` "AgriCarbon"), KHÔNG suy đoán từ ảnh chụp.

## Trạng thái truy cập — quan trọng, đọc trước khi dùng file này

Tài khoản Figma đang ở gói Starter, đã CHẠM TRẦN quota (không phải lỗi cấu
hình) — xác nhận bằng header `Retry-After: 399803` (~111 giờ / ~4.6 ngày) khi
gọi REST API trực tiếp bằng Personal Access Token, cùng account với Figma MCP
mà Codex dùng (nên MCP và REST đều bị chặn như nhau, không phải vấn đề của
riêng 1 kênh truy cập). Trước khi hết quota, đã lấy được:

1. **Cây trang thật** (`GET /v1/files/{key}?depth=2`) — danh sách chính xác
   26 frame và node id, thay cho các node id cũ trong prompt trước đó (đã SAI,
   ví dụ `8:777`/`8:2`/`8:2177` không tồn tại — file đã được tổ chức lại).
2. **Toàn bộ Design System frame** (`8:1153`, 55KB JSON) — màu, typography,
   quy tắc bố cục viết thẳng trong file dưới dạng text layer.

**CHƯA lấy được**: chi tiết layout/spacing/component của 9 màn hình web còn
lại (Dashboard, Farms, Plot detail, Activity log/detail, Carbon, Resource
Efficiency, MRV, Login) — quota hết trước khi kịp gọi. Phần UI cho các màn
này trong lần cập nhật này là **design-token fidelity** (đúng màu/font/spacing
rule/layout rule đã trích xuất thật), KHÔNG PHẢI pixel-perfect theo từng
frame Figma cụ thể — ghi rõ để không ai hiểu lầm là đã đối chiếu pixel-by-pixel.

Khi quota reset (ETA ước tính từ lúc trích xuất: khoảng 2026-09-14) hoặc nâng
gói, chạy lại đúng các lệnh trong "Cách lấy lại dữ liệu" bên dưới để lấy nốt
9 frame, rồi làm lượt fidelity-check pixel-level thật.

## Figma source

- File: `AgriCarbon` (key `rbASkk93CEOFLbp78B4S1o`), page `Page 1` (`0:1`)
- Frames inspected: `8:1153` (00_design_system_v4) — đầy đủ. 9 frame khác chỉ
  biết TÊN + node id (từ cây `depth=2`), chưa inspect nội dung.

## Toàn bộ cây trang thật (26 frame)

| Node ID | Tên frame | Phạm vi task này? |
|---|---|---|
| `8:1153` | 00_design_system_v4 | Có — đã trích xuất |
| `26:2` | 01_web_dang_nhap | Có — Login |
| `26:35` | 02_web_quen_mat_khau | Không (chưa có backend forgot-password) |
| `28:276` | 03_web_tong_quan | Có — Dashboard |
| `28:428` | 04_web_nong_ho_thua_ruong | Có — Farms/Plots |
| `28:152` | 05_web_chi_tiet_thua_ruong | Có — Plot detail |
| `28:2` | 06_web_nhat_ky_hoat_dong | Có — Activities list |
| `28:562` | 07_web_chi_tiet_hoat_dong | Có — Activity detail |
| `29:890` | 08_web_carbon_engine | Có — Carbon |
| `29:1156` | 09_web_thi_giac_may_tinh | Không — CV, cấm theo brief |
| `29:675` | 10_web_hieu_qua_tai_nguyen | Có — Metrics/Resource Efficiency |
| `29:813` | 11_web_khuyen_nghi_ai | Không — AI Recommendation, cấm theo brief |
| `29:1021` | 12_web_mrv_workspace | Có — MRV |
| `30:1695` | 13_web_bao_cao_xuat_du_lieu | Không — chưa có backend export API |
| `30:1809` | 14_web_phan_quyen | Không — chưa có backend permission-management API |
| `30:1278` | 15_web_nhat_ky_he_thong | Không — chưa có backend system-log API |
| `30:1400` | 16_web_ho_so_ca_nhan | Không (Shell hiện đã hiện role/org qua `/v1/me`, đủ dùng) |
| `30:1600` | 17_web_cai_dat_he_thong | Không — chưa có backend settings API |
| `30:1507` | 18_web_trung_tam_thong_bao | Không — notification, cấm theo brief |
| `31:2068`…`31:2173` | 20–26_android_* | Không — Flutter, ngoài phạm vi web |

## Design System (trích xuất thật từ `8:1153`)

### Màu (tên gốc tiếng Việt trong file → hex)

| Tên trong Figma | Hex | Dùng cho |
|---|---|---|
| Xanh nền | `#123C31` | Nền tối / text đậm trên nền sáng |
| Xanh chính | `#2F7D5B` | Primary brand, trạng thái "Tốt"/"Đã đồng bộ" |
| Xanh nhạt | `#EAF4EF` | Nền surface phụ |
| Xanh dương nhạt | `#EAF3F7` | Nền surface phụ (biến thể) |
| Cảnh báo | `#FFF4DF` | Nền trạng thái cảnh báo |
| Lỗi | `#FCEAEA` | Nền trạng thái lỗi |
| AI | `#F1ECFA` | Nền cho khu vực AI (không dùng — module AI ngoài phạm vi) |

Trạng thái badge quan sát được: "Tốt"/"Đã đồng bộ" (xanh `#2F7D5B`), "Cần xem
lại" (amber, sample `#A06000`), "Không chắc chắn" (đỏ, sample `#B04A4A`).

### Typography (Inter)

| Style | Size | Weight | Line-height |
|---|---|---|---|
| H1 | 30px | 700 | ~36.3px |
| H2 | 20px | 700 | ~24.2px |
| Body | 14px | 400 | ~16.9px |
| Caption | 12px | 400 (muted) | ~14.5px |

### Quy tắc bố cục (nguyên văn từ text layer trong file, dịch bám sát)

- Web desktop 1440×1024, sidebar 230px cố định.
- Tài khoản luôn nằm cuối sidebar: avatar, họ tên, vai trò; click → Hồ sơ cá nhân.
- Header có chuông thông báo và bộ chọn HTX/vụ mùa.
- Card bán kính 12–16px, khoảng cách 16–24px, ưu tiên thông tin cần hành động.
- Dữ liệu carbon luôn có khả năng drill-down: activity → emission factor →
  version → audit trail.
- Mobile 430×932: nút lớn, thao tác 1 tay, offline-first, tối thiểu số trường
  bắt buộc. (Flutter — ngoài phạm vi web dashboard.)

## Design tokens áp dụng vào `web-dashboard/src/styles.css`

Token hoá đúng các giá trị trên (không giữ magic value cũ nếu khác) —
xem `src/styles.css` phần `:root` — `--brand`, `--brand-dark`, `--surface-*`,
`--warning-bg`, `--error-bg`, `--radius-card` (12–16px), `--gap-card` (16–24px),
font-size scale theo bảng typography trên. Sidebar cố định 230px trên desktop.

## Screens — trạng thái fidelity

| Screen | Figma frame | Node ID | Fidelity |
|---|---|---|---|
| Login | 01_web_dang_nhap | `26:2` | Token-only (không có layout chi tiết) |
| Dashboard | 03_web_tong_quan | `28:276` | Token-only |
| Farms | 04_web_nong_ho_thua_ruong | `28:428` | Token-only |
| Plot detail | 05_web_chi_tiet_thua_ruong | `28:152` | Token-only |
| Activities | 06_web_nhat_ky_hoat_dong | `28:2` | Token-only |
| Activity detail | 07_web_chi_tiet_hoat_dong | `28:562` | Token-only (chưa có UI riêng — hiện gộp trong Activities list) |
| Carbon | 08_web_carbon_engine | `29:890` | Token-only |
| Metrics | 10_web_hieu_qua_tai_nguyen | `29:675` | Token-only |
| MRV | 12_web_mrv_workspace | `29:1021` | Token-only |
| Organizations | (không có frame riêng trong Figma — thêm ở round 3 trước khi có Figma) | — | Không đối chiếu Figma được, giữ nguyên layout hiện tại + áp token |

"Token-only" = màu/font/spacing/radius đúng thật, cấu trúc layout/component
theo suy luận nhất quán từ quy tắc bố cục đã trích xuất (sidebar 230px, card
radius 12-16px, gap 16-24px, carbon drill-down) — KHÔNG đối chiếu được với
ảnh chụp màn hình thật của từng frame.

## Known deviations (so với brief gốc)

- 9/9 screen KHÔNG được đối chiếu pixel-level — lý do quota, không phải bỏ
  qua có chủ đích.
- 5 frame Figma (Forgot password, Export report, Permissions, System log,
  Settings, Notification center) không implement vì chưa có backend API
  tương ứng (đúng nguyên tắc "không phá contract để UI thuận tiện hơn" —
  ở đây là ngược lại: không tạo UI không có API thật đứng sau).
- CV (09) và AI Recommendation (11) không implement — cấm theo brief.

## Cách lấy lại dữ liệu khi quota reset

```bash
curl -s -H "X-Figma-Token: $FIGMA_TOKEN" \
  "https://api.figma.com/v1/files/rbASkk93CEOFLbp78B4S1o/nodes?ids=26:2,28:276,28:428,28:152,28:2,28:562,29:890,29:675,29:1021" \
  -o screens_all.json
```

Gọi 1 lần, KHÔNG lặp — mỗi lần gọi tốn quota tài khoản (không phải theo phiên
làm việc), đã cạn 1 lần vì thử tách lẻ 9 request liên tiếp.

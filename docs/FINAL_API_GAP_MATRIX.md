# Final API Gap Matrix

Ngày: 2026-09-09. Re-verified thật: `git diff --stat` trên `backend/api.py`/`main.py`/
`read_repo.py` = 0 thay đổi từ commit `112ba5b` (API freeze), 136/136 pytest PASS chạy
lại trong audit này, `docs/openapi.json` đối chiếu 0 lệch với `docs/API_CATALOG.md`.
"Used by React" lấy từ `grep -rn apiRequest web-dashboard/src/api` thật (không suy đoán).
"Used by Flutter" lấy từ `docs/FRONTEND_API_CONTRACT.md` (Flutter đọc/ghi hierarchy trực
tiếp qua Supabase, KHÔNG qua REST — chỉ 3 route carbon dùng HTTP).

Category: **A** không thiếu · **B** thiếu, không cần cho MVP · **C** thiếu, cần cho MVP ·
**D** có API, frontend chưa dùng · **E** có API, chưa test · **F** cần đổi vì bug.

| Requirement | Endpoint | Exists | Tested | React | Flutter | Status | Category | Action |
|---|---|---|---|---|---|---|---|---|
| Auth identity | `GET /v1/me` | Yes | Yes (hosted E2E) | Yes | No (Supabase Auth trực tiếp) | OK | A | none |
| Org list | `GET /v1/organizations` | Yes | Yes | Yes | No | OK | A | none |
| Org detail | `GET /v1/organizations/{id}` | Yes | Yes | Yes | No | OK | A | none |
| Org summary | `GET /v1/organizations/{id}/summary` | Yes | Yes (demo tenant thật) | Yes | No | OK | A | none |
| Org farms | `GET /v1/organizations/{id}/farms` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | D | Chỉ thêm UI nếu Phase 8 xác nhận cần "chọn farm trong org" — hiện Farms page đã đủ dùng `GET /v1/farms` |
| Org farm-performance | `GET /v1/organizations/{id}/farm-performance` | Yes | Yes (demo tenant thật) | Yes | No | OK | A | none |
| Org metrics (rollup) | `GET /v1/organizations/{id}/metrics` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | D | Có thể hữu ích cho Dashboard KPI row nếu muốn 1 request thay vì suy ra từ summary — cân nhắc ở Phase 10, không bắt buộc (summary đã đủ field) |
| Farm list | `GET /v1/farms` | Yes | Yes | Yes | No | OK | A | none |
| Farm detail | `GET /v1/farms/{id}` | Yes | Yes | Yes | No | OK | A | none |
| Farm plots | `GET /v1/farms/{id}/plots` | Yes | Yes | Yes | No | OK | A | none |
| Farm crop-seasons | `GET /v1/farms/{id}/crop-seasons` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | D | Không cần — Plots page đã dẫn tới crop-seasons per-plot đúng hierarchy FR-1c-01 |
| Farm metrics | `GET /v1/farms/{id}/metrics` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | D | Hữu ích nếu Phase 7 UX audit xác nhận cần "hiệu suất riêng 1 farm" ngoài bảng farm-performance cấp org — cân nhắc, không bắt buộc |
| Plot detail | `GET /v1/plots/{id}` | Yes | Yes | Yes | No | OK | A | none |
| Plot crop-seasons | `GET /v1/plots/{id}/crop-seasons` | Yes | Yes | Yes | No | OK | A | none |
| Crop season detail | `GET /v1/crop-seasons/{id}` | Yes | Yes | Yes | No | OK | A | none |
| Crop season activities | `GET /v1/crop-seasons/{id}/activities` | Yes | Yes | Yes | No | OK | A | none |
| Crop season batches | `GET /v1/crop-seasons/{id}/production-batches` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | D | Batch chỉ traceability (SRS §3) — không hiện trên UI hiện tại là ĐÚNG theo PRD, không phải gap |
| Crop season metrics | `GET /v1/crop-seasons/{id}/metrics` | Yes | Yes | Yes | No | OK | A | none |
| Crop season carbon | `GET /v1/crop-seasons/{id}/carbon` | Yes | Yes | Yes | Yes | OK | A | none |
| Batch detail | `GET /v1/production-batches/{id}` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | D | Không cần — không có UI nào cần xem 1 batch đơn lẻ ngoài hierarchy |
| Activity detail | `GET /v1/activities/{id}` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | D | Activities list đã đủ cho FR-1c-01; chỉ cần nếu Phase 14 (Activity UX group) quyết định có trang chi tiết riêng — cân nhắc |
| Carbon calculate | `POST /v1/carbon/calculate` | Yes | Yes (136 test + hosted E2E) | Yes | Yes | OK, FROZEN | A | none |
| Carbon scenarios | `GET /v1/carbon/scenarios` | Yes | Yes | **No** (hardcode 3 option trong dropdown) | Yes | API sẵn, React không dùng | D | Ưu tiên thấp — 3 giá trị cố định theo SRS §4.1, hardcode không sai, nhưng đổi sang fetch sẽ nhất quán hơn nếu SRS thêm scenario sau này |
| EF sets list | `GET /v1/emission-factor-sets` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | B | Không cần cho MVP — không có FR nào yêu cầu farmer/manager xem danh sách bộ hệ số |
| EF set detail | `GET /v1/emission-factor-sets/{id}` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | B | như trên |
| EF set factors | `GET /v1/emission-factor-sets/{id}/factors` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | B | Có thể hữu ích cho Carbon "Số liệu này tính thế nào?" drill-down (Phase 12) nếu muốn link tới nguồn hệ số đầy đủ thay vì chỉ `factors_used` trong breakdown — cân nhắc, không bắt buộc (breakdown đã tự chứa đủ) |
| MRV case list | `GET /v1/mrv/cases` | Yes | Yes | Yes | No | OK | A | none |
| MRV case detail | `GET /v1/mrv/cases/{id}` | Yes | Yes | Yes | No | OK | A | none |
| MRV steps | `GET /v1/mrv/cases/{id}/steps` | Yes | Yes (unit) | **No** (đã nhúng sẵn trong case detail `.steps`) | No | Trùng lặp có chủ đích | D | Không cần — case detail đã có `steps` đầy đủ, route riêng chỉ cho ai cần mỗi steps mà không muốn tải cả case |
| MRV batches | `GET /v1/mrv/cases/{id}/batches` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | C | **CẦN** — FR-1c-01 (drill-down tới Batch) + Phase 15 (MRV workflow UX) hưởng lợi nếu case detail hiện được batch nào thuộc case. Ưu tiên P1, không P0 (case detail vẫn có `batch_count` số lượng, chỉ thiếu danh sách chi tiết) |
| MRV evidence | `GET /v1/mrv/cases/{id}/evidence` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | C | **CẦN nếu** Phase 15 muốn hiện evidence thật (đã seed 1 evidence demo) — P1 |
| MRV exports list | `GET /v1/mrv/cases/{id}/exports` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | B | Export generation chưa tồn tại (FR-1c-05 NOT STARTED) — không có gì để list, hoãn cùng với export |
| MRV export detail | `GET /v1/mrv/exports/{id}` | Yes | Yes (unit) | **No** | No | API sẵn, chưa dùng | B | như trên |

## Critical endpoint checklist (Phase 4) — tất cả đã tồn tại

Toàn bộ danh sách "Critical API Check" trong brief (Auth/Organization/Farm/Plot/Crop
Season/Batch/Activity/Carbon/MRV) đã **100% tồn tại và pass test** — không phát hiện
route nào bị thiếu so với danh sách đó. Đây là kết quả audit thật (không phải copy từ
report cũ) — đối chiếu từng dòng với `docs/openapi.json` (34 path) bằng script Python
trong audit này, khớp tuyệt đối.

## Không có Category C thật sự "thiếu và bắt buộc" ở tầng route mới

Duy nhất 2 dòng gắn nhãn C ở trên (`mrv/.../batches`, `.../evidence`) không phải "API
thiếu" — API **đã tồn tại**, chỉ là **React chưa gọi**. Không route nào trong toàn bộ
34 route cần **tạo mới**. Diễn giải đúng: đây là category D (frontend chưa dùng) được
nêu riêng vì có giá trị UX rõ ràng cho Phase 15, không phải lỗ hổng backend.

## FR traceability (tham chiếu `docs/FINAL_MVP_GAP_MATRIX.md`)

Không phát hiện gì khác so với audit FR trước đó cùng ngày. Các FR đánh dấu NOT STARTED
(CV, Recommendation, MRV export generation) **không có API tương ứng vì tính năng chưa
tồn tại ở bất kỳ lớp nào** — không phải do quên viết route, category B/không áp dụng.

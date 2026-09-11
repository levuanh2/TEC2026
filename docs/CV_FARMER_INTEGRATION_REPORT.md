# M03 — CV Farmer Web Integration Report

> Phạm vi: nối **model CV baseline đã verify trước đó** (không train lại, không
> đổi kiến trúc/threshold) vào backend FastAPI và Farmer Web. Đây không phải
> tài liệu contract model (xem `docs/CV_INTEGRATION.md` cho phần đó) — đây là
> báo cáo tích hợp: cái gì đã có sẵn, cái gì mới được xây, verify bằng số liệu
> thật nào.

## A. Baseline Verification (runtime, not stale docs)

Đọc trực tiếp từ `ml/runs/mobilenetv2-baseline-20260909-222933/eval_metrics.json`
(qua `ml.infer.find_latest_run()` — cùng cơ chế backend dùng để load model khi
khởi động) tại thời điểm viết báo cáo này:

| Field | Giá trị runtime thực tế | Khớp baseline user cung cấp? |
|---|---|---|
| model_name | mobilenet_v2_rice_leaf_cv_baseline | ✓ |
| version_code | mobilenetv2-baseline-20260909-222933 | ✓ |
| dataset | Rice Leaf Bacterial and Fungal Disease Dataset, DOI 10.17632/hx6f852hw4.2 | ✓ |
| classes | rice_blast, bacterial_leaf_blight, brown_spot, healthy | ✓ |
| train/val/test count | 608 / 132 / 125 | ✓ |
| accuracy | 0.856 | ✓ (85.60%) |
| precision_macro / recall_macro / f1_macro | 0.859568 / 0.862280 / 0.860214 | ✓ |
| temperature | 1.65 | ✓ |
| confidence_threshold | 0.939849 | ✓ (0.9398) |
| uncertain_rate_on_test | 0.424 | ✓ (42.4%) |
| status | draft | ✓ — vẫn draft, không tự động promote |

`ml/tests` (9 test) chạy lại: **9/9 PASS**, không sửa architecture/train
logic. Kết luận: baseline khớp 100% với số liệu user cung cấp — không có sai
lệch giữa doc cũ và runtime thực tế.

## B. Backend Integration — Before Change

Trước task này: `plant_images`, `cv_inferences`, `cv_model_versions` đã tồn
tại trong `supabase/migrations/20260907000000_baseline.sql` (bảng, enum
`disease_label`, RLS, storage bucket `plant-images`, trigger validate path)
nhưng **không có repository/service/route nào ở backend** — schema tồn tại,
0% được dùng. Đây là khoảng trống duy nhất task này lấp — không migration
mới, không sửa schema.

## C. Backend Architecture (new)

```
api.py (3 route mới)
  → CvService (backend/service.py)
      → ml.infer.predict_with_model()   [reuse — preprocessing/model KHÔNG bị nhân bản]
      → PostgresCvRepository (backend/infrastructure/cv_repo.py)
          → Postgres (psycopg, service-role, trusted) + Supabase Storage (bucket plant-images)
  scope check trước mọi write/read: read_repository.season(crop_season_id) (RLS-scoped, cùng pattern FW-2/M05)
```

Model được load **một lần** khi backend khởi động (`main.py::_build_cv_service`),
không load lại mỗi request. Nếu load model thất bại, `CvService` không được
đăng ký — route trả `503 model_unavailable` thay vì crash toàn app.

`cv_model_versions_select` RLS chỉ cho đọc `status in ('active','retired')` —
chặn đọc bản `draft` kể cả với người có quyền. Vì model hiện tại là `draft`,
list/get inference phải dùng kết nối trusted (sau khi đã xác thực scope qua
RLS) — không thể dùng RLS-scoped read cho phần này như M05 đã làm (khác biệt
kiến trúc có chủ đích, ghi lại để tránh nhầm là thiếu nhất quán).

## D. API Table

| Method | Path | Auth | Response |
|---|---|---|---|
| POST | `/v1/crop-seasons/{crop_season_id}/cv/infer` | Farmer (JWT, scope = season) | `CvInferenceResponse` |
| GET | `/v1/crop-seasons/{crop_season_id}/cv/inferences` | Farmer (JWT, scope = season) | `{items: CvInferenceResponse[]}` |
| GET | `/v1/cv/inferences/{inference_id}` | Farmer (JWT, resolves scope via image→season) | `CvInferenceResponse` |

Idempotency: sha256 nội dung ảnh, index unique **toàn cục** trên
`plant_images.sha256` — ảnh trùng nội dung được tái sử dụng (không tạo bản
ghi mới, không gọi lại model) miễn là *cùng* crop_season; nếu sha trùng
nhưng khác crop_season → `409 duplicate_image` (không cho mượn ảnh giữa các
vụ khác nhau).

## E. Inference Contract (thực tế, từ response thật)

```json
{
  "id": "…",
  "crop_season_id": "…",
  "image_id": "…",
  "label": "rice_blast",
  "label_vi": "Đạo ôn",
  "confidence": 0.943937,
  "uncertain": false,
  "threshold_used": 0.939849,
  "model_version": "mobilenetv2-baseline-20260909-222933",
  "created_at": "2026-09-11T…"
}
```

Khi `uncertain: true` → `label` và `label_vi` đều `null` (không ép chọn nhãn
— FR-1b-04, kế thừa contract Flutter cũ, áp dụng nhất quán cho Farmer Web).

## F. Farmer UX

Entry point: nút "Kiểm tra lá lúa" trên Home (Quick action, dưới
`QuickEntryPanel`) **và** trên Season Overview — không phải mục nav thứ 6.
Flow: chọn/chụp ảnh → xem trước → "Phân tích ảnh" → loading (`aria-live`) →
kết quả.

- **Confident**: heading "Kết quả nhận diện", tên bệnh + % tin cậy,
  `Notice` info "Kết quả hỗ trợ nhận diện từ mô hình AI. Chưa được xác nhận
  thực địa." — không có nút hành động tự động nào (không tự tạo khuyến nghị,
  không tự ghi log farm).
- **Uncertain** (42.4% test rate — coi là trạng thái chính, không phải cạnh
  biên): heading "Chưa thể xác định chắc chắn", % tin cậy, gợi ý chụp lại
  (gần hơn / đủ sáng / một lá trong khung hình), nút "Chụp/chọn ảnh khác".
  Không hiển thị nhãn top-1 dưới bất kỳ hình thức nào khi uncertain.
- Không có khái niệm "Ảnh không phải lá lúa" ở bất kỳ đâu trong UI — không
  detector OOD nào tồn tại, nên không được hiển thị.
- CV history: danh sách các lần kiểm tra trong vụ (Season Overview), mỗi
  dòng mở drawer chi tiết. Home có card tóm tắt kết quả gần nhất (optional,
  return `null` nếu chưa có).

## G. Uncertainty Handling

`uncertain` do backend tính (`ml.infer.predict_with_model`, so `confidence <
threshold`) — Farmer Web **không tự tính lại ngưỡng ở phía React**. React chỉ
đọc field `uncertain`/`label` đã có sẵn trong response và render theo đúng
hai nhánh trên. **React recomputes: NO.**

## H. Authorization

- Farm khác / season khác → xác thực qua `read_repository.season()` (RLS)
  trước khi chạm trusted repo → lệch scope trả `404 not_found` (không phân
  biệt "không tồn tại" vs "không thuộc về bạn" — chuẩn cross-scope hiện có).
- Ảnh > 10MB, sai mime (khác jpeg/png), file hỏng/không mở được, chiều nhỏ
  hơn 32px → `422` với message tiếng Việt cụ thể (không phải lỗi generic).
- Route CV không có input nào bind trực tiếp business table qua PostgREST từ
  frontend — mọi ghi đều qua backend trusted repo (giống FW-2/M05).

## I. Real Model Smoke (CLI + backend)

CLI (`ml/tests/test_cv_real_model_smoke` tương đương, chạy trực tiếp qua
`ml.infer`): dùng đúng checkpoint `mobilenetv2-baseline-20260909-222933`,
threshold 0.939849. Ảnh test:

- `Leaf Blast/Leaf_blast  (105).jpg` → `rice_blast`, confidence 0.943937
  (> threshold → confident).
- `Healthy Rice Leaf/Healthy_rice_leaf  (98).jpg` → confidence 0.822835
  (< threshold → uncertain, `label: null`).

Cả hai xác nhận lại qua backend thật (uvicorn cổng 8010, model load lúc
startup, không mock) trong phần Real Farmer E2E bên dưới — cùng ảnh, cùng
kết quả (model deterministic, trọng số cố định).

## J. Real Farmer E2E

`web-dashboard/tests/e2e/farmer-real-cv.spec.ts`, chạy với backend thật + tài
khoản Farmer QA thật (`qa-farmer-m03@agricarbon-demo.local`, scope
`DEMO-FARM-01`), **không** intercept API, **không** fake response:

- Upload ảnh confident → `POST /cv/infer` trả 200 thật → UI hiện đúng
  heading "Kết quả nhận diện" → không xuất hiện text "85.6%" (không overclaim
  field validation) → đóng dialog.
- Vào Season Overview → "Kiểm tra gần đây" hiển thị đúng lịch sử vừa tạo.
- Upload ảnh uncertain → response thật có `uncertain: true, label: null` →
  UI hiện đúng heading "Chưa thể xác định chắc chắn" + gợi ý chụp lại.
- Assertion cuối: 0 lệnh gọi PostgREST trực tiếp vào business table từ
  frontend, 0 API lỗi ngoài dự kiến, console sạch.

**Kết quả: 1 passed** (test được chạy 2 lần trong phiên làm việc do một lỗi
locator Playwright ở lần đầu — xem mục K — không phải lỗi ứng dụng; sau khi
sửa locator, cả upload thật + inference thật + render UI thật đều pass.)

## K. Regression

| Suite | Kết quả |
|---|---|
| `backend` pytest | **223/223 PASS** (27 test CV mới, 196 pre-M03 không đổi) |
| `ml/tests` pytest | **9/9 PASS** (không sửa train/eval logic) |
| `web-dashboard` vitest | **64/64 PASS** |
| `npm run build` | sạch, không lỗi TS |
| Farmer mock Playwright (`farmer-web.spec.ts`) | **PASS** — bao gồm assertion CV entry point ở 1440 và 390, Quick Entry fertilizer/irrigation/harvest không bị ảnh hưởng |
| Management mock Playwright (`web-smoke.spec.ts`) | **PASS** — không đổi |
| Real E2E: `farmer-real-cv.spec.ts` | **PASS** |
| Real E2E: `farmer-real-write.spec.ts` (FW-2) | **PASS** (chạy lại sau khi dọn 2 bản ghi harvest rác do chính phiên làm việc này tạo ra lúc chạy song song 2 test thật — xem ghi chú K.1) |
| Real E2E: `farmer-real-recommendations.spec.ts` (M05) | **PASS** |

### K.1 — Sự cố tự gây ra trong lúc QA (không phải bug CV)

Khi chạy đồng thời 2 file real-E2E khác nhau cùng lúc trên cùng tài khoản QA
(`qa-farmer-m03`), cả hai cùng ghi vào cùng một season → một test thất bại
giữa chừng (do đụng độ file artifact của Playwright, không liên quan logic
app) và để lại 2 bản ghi `harvest` rác (5kg, note `QA-FW2-…`) chưa được xóa
(spec gốc không có `try/finally` dọn dẹp khi fail giữa chừng). Bản ghi rác
này khiến lần chạy `farmer-real-write.spec.ts` kế tiếp thất bại ở đúng
assertion `yield_kg` delta — **không phải regression từ code CV** (không có
overlap file: CV chỉ thêm `cv_repo.py`, sửa `service.py`/`schemas.py`/
`api.py`/`main.py` ở các đoạn hoàn toàn tách biệt với
`ActivityWriteService`/metrics). Đã xóa 2 bản ghi rác qua chính API xóa hoạt
động đã được authorize (`DELETE /v1/activities/{id}`, dùng JWT của farmer QA
— không đụng DB trực tiếp), sau đó chạy lại tuần tự (không song song) và cả
2 suite real E2E đều pass sạch.

**Bài học cho lần sau**: không chạy song song 2 file real-E2E khác nhau trên
cùng 1 QA identity/season nếu chúng cùng ghi dữ liệu — chạy tuần tự.

## L. Limitations (explicit, không được xoá khi báo cáo)

- **PUBLIC DATASET BASELINE** — huấn luyện/đánh giá hoàn toàn trên
  Mendeley Rice Leaf Bacterial and Fungal Disease Dataset (dữ liệu công khai,
  không phải dữ liệu đồng ruộng Việt Nam).
- **NOT FIELD VALIDATED** — chưa được xác nhận trên ảnh thực địa Việt Nam;
  toàn bộ UI Farmer chỉ nói "Chưa được xác nhận thực địa", không bao giờ nói
  "chính xác X% ngoài thực địa".
- **BANGLADESH → VIETNAM DOMAIN GAP** — dataset gốc thu thập tại Bangladesh;
  chưa có bằng chứng generalize sang điều kiện ánh sáng/giống lúa/thiết bị
  chụp tại Việt Nam.
- **OOD/NON-RICE REJECTION NOT ROBUST** — không có detector "đây có phải lá
  lúa không"; model sẽ luôn trả về 1 trong 4 nhãn (hoặc uncertain) cho BẤT KỲ
  ảnh nào đưa vào, kể cả ảnh không phải lá lúa. UI không claim khả năng này.
- **HIGH UNCERTAIN RATE IS A KNOWN BASELINE LIMITATION** — 42.4% ảnh test bị
  đánh dấu uncertain; đây là hành vi kỳ vọng của baseline hiện tại, không
  phải bug, và được xử lý như trạng thái UX chính (không phải trường hợp
  hiếm).

## M. Remaining Gaps

- Không cross-link CV → M05 recommendation (đúng scope task, tách biệt có
  chủ đích).
- Cross-scope real-browser check (Farmer A cố truy cập ảnh/inference của
  Farm B) không chạy qua Playwright thật — đã cover đủ ở mức backend unit
  test (`backend/tests/test_cv_service.py`, các test `..._returns_not_found`
  cho season/image/inference sai scope), theo đúng tiền lệ đã thống nhất ở
  M05 (không lặp lại real-browser cross-scope test cho mỗi tính năng khi
  logic scope-check dùng chung 1 pattern đã verify).
- Responsive 768px: xác nhận qua assertion "không tràn ngang" (`scrollWidth
  <= innerWidth`) dùng chung cho toàn Farmer shell (cùng chuẩn áp dụng cho
  form Bón phân/Thu hoạch có sẵn từ FW-2) — không có screenshot riêng 768
  cho màn CV (chỉ có 1440 + 390), nhất quán với cách các form khác trong
  FW-2 đã được QA.
- Latency thực đo trên CPU (không fabricate throughput): model load ≈63ms
  (một lần khi khởi động), suy luận trung bình ≈21.1ms/ảnh (dải quan sát
  16.8–37.5ms qua 10 lần lặp, CPU-only, không batch).

## N. Final Status

`M03 CV FARMER INTEGRATION: DONE`

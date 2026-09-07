# AgriCarbon

**Nền tảng số hóa carbon & hiệu suất tài nguyên cho canh tác lúa gạo ĐBSCL.**
Sản phẩm dự thi **TEC 2026** — TDMU Entrepreneurship Competition, lĩnh vực Nông nghiệp – Môi trường – Năng lượng.

> **Định vị:** *Carbon + hiệu suất tài nguyên tính trên mỗi kg sản phẩm, ở cấp nông hộ, có
> thị giác máy tính hỗ trợ ra quyết định* — công cụ hỗ trợ **số hóa Quy trình MRV 6 bước**
> của Bộ Nông nghiệp và Môi trường, không phải một carbon calculator chung chung.

**Deadline MVP: 20/09/2026.**

---

## Vấn đề

Nông dân ĐBSCL ghi chép vật tư vào sổ tay giấy. Dữ liệu rời rạc, không tiêu chuẩn, không có
bằng chứng chống gian lận. Doanh nghiệp xuất khẩu phải chi hàng trăm triệu đồng thuê kiểm định
bên thứ ba rà soát sổ sách thủ công để qua được hàng rào CBAM/EUDR. Trong khi đó Đề án 1 triệu
ha lúa phát thải thấp cần số hóa MRV cho hàng trăm nghìn hộ — nhưng chưa có công cụ nào làm
việc đó ở **cấp nông hộ** với đơn vị đo **trên mỗi kilogram**.

---

## Vòng lặp sản phẩm

```text
MEASURE  ->  UNDERSTAND  ->  OPTIMIZE  ->  ACT  ->  (quay lại MEASURE)
```

Chi tiết: [`docs/architecture.md`](docs/architecture.md)

---

## Cây thư mục

```text
.
├── README.md                          # file này
├── docs/
│   ├── PRD.md                         # Product Requirements Document
│   ├── SRS.md                         # Software Requirements Specification
│   ├── architecture.md                # kiến trúc + luồng MEASURE→UNDERSTAND→OPTIMIZE→ACT
│   ├── mrv-mapping.md                 # map tính năng ↔ 6 bước MRV
│   └── modules/
│       ├── 01-mobile-app.md           # 1a — app ghi nhật ký (Người A)
│       ├── 02-carbon-engine.md        # 1a — Carbon Engine (Người B)
│       ├── 03-computer-vision.md      # 1b — CV bệnh lá lúa (Người B)
│       ├── 04-resource-dashboard.md   # 1b — chỉ số tài nguyên/kg (Người B + A)
│       ├── 05-ai-recommendation.md    # 1b — khuyến nghị + impact (Người B + A)
│       ├── 06-web-dashboard.md        # 1c — dashboard HTX/DN (Người A)
│       └── 07-mrv-export.md           # 1c — xuất báo cáo MRV (Người B + A)
├── app/                               # Mobile app Flutter, offline-first — Người A
├── backend/                           # FastAPI + Carbon Engine — Người B
│   ├── carbon/                        # Carbon Engine (hàm thuần, không phụ thuộc UI/DB)
│   ├── config/emission_factors.yaml   # hệ số phát thải, có nguồn trích dẫn
│   └── tests/                         # unit test + demo fixture
├── ml/                                # model CV bệnh lá lúa — Người B
│   └── datasets/README.md             # nguồn dataset + license
├── web-dashboard/                     # dashboard 1c (có thể là mock) — Người A
└── infra/                             # env, deploy note
```

Hai file gốc dùng làm tài liệu nguồn nằm ở thư mục gốc:
`AgriCarbon_v2_Rice_Decision_and_Roadmap.md` và `TEC2026 - Phiếu đăng ký dự thi.docx.md`.

---

## Ba lớp MVP — làm tuần tự, không song song dàn trải

| Lớp | Nội dung | Nguyên tắc |
|---|---|---|
| **1a — Walking Skeleton** | App ghi nhật ký tối giản + Carbon Engine → ra CO2e/kg end-to-end, đáng tin cậy | **Đường găng. Ưu tiên tuyệt đối, không bao giờ cắt.** |
| **1b — AI/CV** | Phát hiện bệnh lá lúa + Resource Efficiency Dashboard + AI Recommendation (rule-based, luôn kèm impact) | Làm ngay sau khi 1a chạy ổn. Bắt buộc có — cuộc thi thuộc chủ đề AI |
| **1c — Trình bày/vận hành** | Web Dashboard HTX/doanh nghiệp + Export MRV Report (PDF/Excel theo 6 bước) | Làm cuối. **Cắt xuống mock trước tiên** nếu thiếu thời gian |

Giai đoạn 2 (What-if Simulation, Farm Map, Weather, Evidence/Anti-fraud), giai đoạn 3 (RAG
Chatbot chính sách/MRV) và giai đoạn 4 (Traceability, IoT, Marketplace…) **chỉ nằm trong
roadmap dài hạn**, không dựng code trong MVP. Lý do từng phần: [`docs/PRD.md` §5](docs/PRD.md).

---

## Phân công theo layer

| | Người A | Người B |
|---|---|---|
| **Thư mục** | `app/` + `web-dashboard/` | `backend/` + `ml/` |
| **Lớp 1a** | Module 01 — app ghi nhật ký, offline-first | Module 02 — Carbon Engine |
| **Lớp 1b** | Màn hình chỉ số & khuyến nghị trên app | Module 03 CV, 04 chỉ số, 05 khuyến nghị |
| **Lớp 1c** | Module 06 — web dashboard, nút xuất báo cáo | Module 07 — sinh file báo cáo MRV |

**Điểm chạm duy nhất ở lớp 1a là hợp đồng API** tại [`docs/SRS.md` §4](docs/SRS.md).
Chốt hợp đồng đó trước; sau đó hai người code song song mà không chặn nhau (Người A mock
response để chạy trước).

Khi code, mỗi người mở phiên riêng và trỏ vào đúng thư mục layer của mình để tránh đá nhau.

---

## Chạy từng phần

```bash
# backend — Người B
cd backend && python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt && uvicorn main:app --reload

# app — Người A
cd app && flutter pub get && flutter run

# web-dashboard — Người A
# mở web-dashboard/index.html bằng trình duyệt, không cần build

# ml — Người B
cd ml && pip install -r requirements.txt && python train.py
```

Toàn bộ scaffold hiện chỉ là entrypoint có TODO — **chưa có logic nghiệp vụ**.

---

## Ba nguyên tắc không được vi phạm

1. **Không hardcode hệ số phát thải.** Mọi hệ số nằm ở `backend/config/emission_factors.yaml`
   kèm nguồn trích dẫn và ngày review. Kết quả tính trả kèm `ef_config_version` để truy vết ngược.
   Đây là điều kiện để trả lời câu hỏi hội đồng chắc chắn sẽ hỏi: *"số này ở đâu ra?"*
2. **Không trình bày số liệu chưa chốt như đã xác nhận.** Giá tín chỉ carbon (TCAF đang định giá)
   và API RiceMoRe/FarMoRe (**chưa có API mở**) đều phải nói đúng trạng thái.
3. **Không bịa số khi thiếu dữ liệu.** Chưa có sản lượng → báo "chưa tính được CO2e/kg",
   không hiện 0. Hệ số còn trống → báo lỗi rõ ràng, không tự đặt mặc định.

---

## Việc cần làm ngay (chặn tiến độ)

- [ ] **OI-01 / OI-02 — chốt bộ hệ số phát thải** (hạn 15/09/2026): làm rõ mâu thuẫn giữa
      ~1,04 kg CO2/kg và dải 2,29–3,72 kg CO2e/kg; lấy hệ số chính thức từ hướng dẫn MRV
      (QĐ 4801/QĐ-BNNMT). **Đây là rủi ro số 1 — chặn cả lớp 1a.**
- [ ] Chốt hợp đồng API 1a giữa Người A và Người B trước khi code song song
- [ ] Đối chiếu Definition of Done trong `docs/modules/` với file `AgriCarbon Sprint Tracker`
      và sửa các ID `T1-xx` / `T2-xx` cho khớp (hiện đang là ID tạm)
- [ ] Liên hệ HTX pilot (Tiến Thuận – Cần Thơ hoặc Phú Hòa – An Giang)
- [ ] Xác nhận license dataset ảnh trước khi train (`ml/datasets/README.md`)

---

## Tài liệu

| File | Nội dung |
|---|---|
| [`docs/PRD.md`](docs/PRD.md) | Bối cảnh, người dùng, định vị, mục tiêu từng lớp MVP, ngoài phạm vi, success metrics, rủi ro |
| [`docs/SRS.md`](docs/SRS.md) | Functional/non-functional requirements, data model, API contract, ràng buộc |
| [`docs/CARBON_METHOD.md`](docs/CARBON_METHOD.md) | Công thức từng nguồn phát thải + trạng thái xác minh (VERIFIED / PENDING / NOT IMPLEMENTED) |
| [`docs/architecture.md`](docs/architecture.md) | Kiến trúc thành phần, luồng dữ liệu, nguyên tắc thiết kế |
| [`docs/mrv-mapping.md`](docs/mrv-mapping.md) | 6 bước MRV ↔ module nào xử lý, mức độ phủ, khoảng trống |

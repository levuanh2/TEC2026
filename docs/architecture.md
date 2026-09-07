# Kiến trúc & luồng dữ liệu — AgriCarbon

Phiên bản: 0.1 · Ngày: 2026-09-07
Liên quan: [`PRD.md`](PRD.md) · [`SRS.md`](SRS.md) · [`mrv-mapping.md`](mrv-mapping.md)

---

## 1. Vòng lặp sản phẩm

Sản phẩm vận hành theo một vòng lặp bốn nhịp. Mỗi nhịp có module chịu trách nhiệm rõ ràng:

```text
        ┌──────────────────────────────────────────────┐
        │                                              │
        ▼                                              │
   ┌─────────┐    ┌────────────┐    ┌──────────┐    ┌─────┐
   │ MEASURE │ ─► │ UNDERSTAND │ ─► │ OPTIMIZE │ ─► │ ACT │
   └─────────┘    └────────────┘    └──────────┘    └─────┘
    01 App        02 Carbon Engine   05 AI           Nông dân
    03 CV         04 Resource        Recommendation  thay đổi
                     Dashboard                       canh tác
```

| Nhịp | Câu hỏi trả lời | Module |
|---|---|---|
| **MEASURE** | "Tôi đã làm gì trên ruộng?" | `01-mobile-app` (nhập tay), `03-computer-vision` (ảnh lá) |
| **UNDERSTAND** | "Điều đó tốn bao nhiêu carbon và tài nguyên trên mỗi kg?" | `02-carbon-engine`, `04-resource-dashboard` |
| **OPTIMIZE** | "Nên điều chỉnh gì, được lợi bao nhiêu?" | `05-ai-recommendation` |
| **ACT** | "Làm theo và ghi lại kết quả" | quay lại `01-mobile-app` — khép vòng |

Lớp `06-web-dashboard` và `07-mrv-export` không nằm trong vòng lặp của nông dân; chúng phục
vụ HTX / doanh nghiệp / cơ quan quản lý ở phía sau.

---

## 2. Sơ đồ thành phần

```text
   ĐIỆN THOẠI NÔNG DÂN                      SERVER                    NGƯỜI DÙNG TỔ CHỨC
 ┌────────────────────────┐        ┌──────────────────────┐        ┌────────────────────┐
 │  app/  (Flutter)       │        │  backend/ (FastAPI)  │        │ web-dashboard/     │
 │                        │        │                      │        │                    │
 │  Form "1 phải 5 giảm"  │        │  API đồng bộ         │        │ Farm → Plot → Crop │
 │  SQLite cục bộ         │◄──────►│  Carbon Engine ◄──┐  │◄──────►│ → Batch → Activity │
 │  Hàng đợi đồng bộ      │  HTTP  │  Benchmark        │  │  HTTP  │ → Carbon           │
 │  Màn hình CO2e/kg      │        │  Recommendation   │  │        │ Phân quyền 3 vai   │
 │  Chụp ảnh lá lúa       │        │  Export MRV       │  │        │ Nút Export MRV     │
 └────────────────────────┘        └───────────────────┼──┘        └────────────────────┘
                                                       │
                                        đọc hệ số      │
                                   ┌───────────────────┴──────────────┐
                                   │ backend/config/                  │
                                   │   emission_factors.yaml          │
                                   │   (nguồn trích dẫn + review_by)  │
                                   └──────────────────────────────────┘
                                   ┌──────────────────────────────────┐
                                   │ ml/  model bệnh lá lúa           │
                                   │  4 lớp: đạo ôn / bạc lá /        │
                                   │  đốm nâu / khỏe                  │
                                   └──────────────────────────────────┘
```

**Ai làm gì:** Người A giữ `app/` + `web-dashboard/`. Người B giữ `backend/` + `ml/`.
Điểm chạm duy nhất ở lớp 1a là hợp đồng API tại [`SRS.md` §4](SRS.md#4-api-contract-nháp--luồng-1a)
— chốt hợp đồng đó trước, sau đó hai người code song song mà không chặn nhau.

---

## 3. Luồng dữ liệu chính (lớp 1a — đường găng)

```text
1. Nông dân mở app ngoài ruộng, KHÔNG có sóng
        │
        ▼
2. Nhập Activity theo khung "1 phải 5 giảm"
   (giống / phân / nước-AWD / thuốc / rơm rạ / thu hoạch)
        │
        ▼
3. Ghi vào SQLite cục bộ + đẩy vào hàng đợi đồng bộ
   (dữ liệu an toàn kể cả khi tắt app — NFR-01)
        │
        ▼  (khi có mạng trở lại)
4. POST /v1/sync  — khử trùng lặp theo client_id (FR-1a-07)
        │
        ▼
5. POST /v1/carbon/calculate
        │
        ├─ đọc Activity Data của vụ
        ├─ đọc Emission Factor từ emission_factors.yaml (RB-01)
        ├─ tính theo kịch bản nước: awd | continuous_flooding | as_recorded
        └─ CO2e tổng, chia cho yield_kg  →  CO2e/kg
        │
        ▼
6. App hiển thị CO2e/kg + phân rã theo nguồn phát thải (FR-1a-10)
   Thiếu sản lượng → báo "chưa tính được", KHÔNG hiện 0 (NFR-03)
```

---

## 4. Nguyên tắc kiến trúc

### 4.1. Offline-first là ràng buộc, không phải tính năng

Sóng ĐBSCL yếu và chập chờn. App phải nhập liệu được đủ 100% khi mất mạng; mạng chỉ cần cho
đồng bộ và tính CO2e. Hệ quả thiết kế: nguồn sự thật lúc nhập liệu nằm ở SQLite trên máy,
server là nơi hợp nhất — nên mọi bản ghi phải mang `client_id` do máy sinh, và endpoint
đồng bộ phải idempotent.

### 4.2. Carbon Engine là hàm thuần, tách khỏi UI

Engine nhận Activity Data và trả kết quả, không biết gì về màn hình. Điều này làm được ba việc:

- Test được bằng bộ dữ liệu mẫu đối chiếu phép tính tay (NFR-02).
- Chạy được kịch bản giả định mà không đụng dữ liệu thật → **What-if Simulation ở giai đoạn 2
  chỉ cần gọi lại engine với input khác**, không phải viết lại lớp 1a (NFR-04).
- Gọi lại được từ web-dashboard và export MRV mà không nhân bản logic.

### 4.3. Hệ số phát thải là dữ liệu, không phải code

Toàn bộ hệ số nằm ở `backend/config/emission_factors.yaml`, mỗi giá trị kèm `source` và
`review_by`. Kết quả tính trả kèm `ef_config_version` để truy vết ngược. Đây là điều kiện
cần để trả lời câu hỏi hội đồng chấm thi chắc chắn sẽ hỏi: *"số này ở đâu ra?"*

### 4.4. Chỗ trống dành sẵn cho giai đoạn sau

Không dựng code cho giai đoạn 2/3/4, nhưng data model đã chừa chỗ để sau này không phải đập đi:

| Giai đoạn sau | Chỗ đã chừa sẵn |
|---|---|
| What-if Simulation (2.3) | `water_regime_scenario` trong API tính carbon đã cho phép truyền kịch bản giả định |
| Farm Map (2.4) | `Plot.geo` (tùy chọn) |
| Historical Data (2.4) | `Crop.season` + `Carbon.calculated_at` cho phép so sánh giữa các vụ |
| Evidence/Anti-fraud (2.2) | `Activity.created_by` / `created_at` / `updated_at` |
| Traceability (4.1) | thực thể `Batch` đã có trong data model từ đầu |
| RAG Chatbot (3) | `Carbon.breakdown` là dữ liệu động sẵn sàng cho trả lời cá nhân hóa |

---

## 5. Stack (đề xuất, chưa khóa)

| Layer | Stack | Vì sao |
|---|---|---|
| `app/` | Flutter + SQLite (`drift`/`sqflite`) | Một codebase, hỗ trợ offline tốt, quen thuộc trong đồ án sinh viên |
| `backend/` | Python 3.11 + FastAPI + SQLite | Cùng ngôn ngữ với `ml/` → Người B chỉ nuôi 1 môi trường. Đổi sang Postgres khi có nhiều HTX |
| `ml/` | PyTorch, fine-tune model phân loại ảnh | Đủ cho 1 bài toán 4 lớp |
| `web-dashboard/` | HTML tĩnh + dữ liệu mock trước | 1c là lớp có thể cắt — chưa đáng dựng build toolchain. Nâng lên Vite + React chỉ khi cần gọi API động |
| `infra/` | Chạy local hoặc 1 VPS nhỏ | Chưa cần Docker/CI/K8s khi chưa có gì để deploy |

Đổi stack được, miễn giữ nguyên hợp đồng API ở [`SRS.md` §4](SRS.md#4-api-contract-nháp--luồng-1a).

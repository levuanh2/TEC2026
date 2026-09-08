# Module 02 — Carbon Engine

| | |
|---|---|
| **Lớp MVP** | **1a — Walking Skeleton (đường găng, ưu tiên tuyệt đối)** |
| **Thư mục** | `backend/` |
| **Phụ trách** | Người B |
| **FR phụ trách** | FR-1a-08, FR-1a-09, FR-1a-12 |

> **Lưu ý về task ID:** các ID `T2-xx` dưới đây là ID tạm. **Đối chiếu lại với
> `AgriCarbon Sprint Tracker` trước khi code.**

> ⚠️ **Đây là phần cần test kỹ nhất của toàn dự án.** Giám khảo nhiều khả năng sẽ hỏi sâu:
> *"số này tính ra sao, dựa hệ số nào, có khớp MRV không"*. Mọi thứ khác trong sản phẩm
> đứng trên con số này.

---

## 1. Mục tiêu module

Biến Activity Data thô của **một Crop Season** thành con số **CO2e/kg lúa** tin cậy và truy vết được, tính riêng
kịch bản **AWD (tưới ngập-khô xen kẽ)** so với **tưới ngập liên tục**.

---

## 2. Input / Output

**Input:**
- Toàn bộ Activity Data, plot area, cultivation period và harvest events của một `Crop Season` (từ module 01 qua `POST /v1/sync`). Production Batch chỉ là traceability, không phải input xác định phạm vi CH4.
- `yield_kg`: tổng sản lượng của harvest events thuộc vụ; không lấy sản lượng một batch làm mẫu số.
- Bộ hệ số từ `backend/config/emission_factors.yaml`.
- `water_regime_scenario` ∈ { `awd`, `continuous_flooding`, `as_recorded` }.

**Output:** bản ghi `Carbon` — xem [SRS §4.2](../SRS.md#42-post-v1carboncalculate--tính-co2e):

```json
{
  "co2e_total_kg": 4820.5,
  "yield_kg": 3100.0,
  "co2e_per_kg": 1.555,
  "breakdown": [ { "source": "ch4_flooding", "co2e_kg": 3600.0 }, ... ],
  "ef_config_version": "0.1.0-draft",
  "warnings": [ ... ]
}
```

---

## 3. Logic nghiệp vụ cốt lõi

### 3.1. Công thức — xem tài liệu chuyên biệt

> ⚠️ `Activity Data × Emission Factor` là **abstraction ở tầng cao, không phải công thức
> tính**. Mỗi nguồn có phương pháp luận riêng và cấu trúc khác hẳn nhau.
>
> **Nguồn sự thật duy nhất về công thức:** [`../CARBON_METHOD.md`](../CARBON_METHOD.md).
> Nguồn trích dẫn từng hệ số: [`../CARBON_METHOD_SOURCES.md`](../CARBON_METHOD_SOURCES.md).
> Đừng nhân bản công thức vào file này — sẽ lệch nhau.

### 3.2. Các nguồn phát thải tính riêng

| Nguồn (`source`) | Cấu trúc thật | Phương pháp luận |
|---|---|---|
| `ch4_rice_cultivation` | `(EFc × SFw × SFp × SFo) × t × A` — bốn hệ số nhân nhau, SFo là hàm luỹ thừa | IPCC 2019 Refinement Eq 5.1/5.2/5.3 |
| `n2o_fertilizer_direct` | `kg_N × EF1FR × 44/28` — áp lên **kg N**, không phải kg phân | IPCC 2019 Refinement Eq 11.1 |
| `straw_burning` | `M_khô × Cf × Gef × 10⁻³`, tách CH4 và N2O | IPCC 2006 GL Eq 2.27 |
| `fuel_*` | `lít × EF` — nguồn duy nhất đúng là một phép nhân đơn | PENDING (OI-06) |

**Rơm VÙI không phải một nguồn phát thải riêng** — nó là đầu vào của SFo (điều chỉnh CH4).
Chỉ rơm ĐỐT mới là nguồn riêng. Cộng cả hai là double counting — xem CARBON_METHOD.md §5.

### 3.3. Tách AWD vs tưới ngập liên tục — điểm mấu chốt

Chế độ nước là **biến số ảnh hưởng carbon lớn nhất** và cũng đúng là thứ MRV 6 bước đang đo.

- `continuous_flooding` → `irrigated_continuous_flooding`. Dùng làm **đường cơ sở**
  (bước 3 MRV: Thiết lập đường cơ sở).
- `awd` → `irrigated_multiple_drainage` (IPCC Table 5.12 xếp AWD vào nhóm này).
- `as_recorded` — dùng đúng chế độ nông dân đã ghi.

**AWD tác động NGƯỢC CHIỀU lên hai khí:** SFw giảm 1,00 → 0,55 (CH4 giảm 45%) nhưng
EF1FR tăng 0,003 → 0,005 (N2O **tăng** 67%). Kịch bản phải đi vào **cả CH4 lẫn N2O**.

**Tuyệt đối không** lấy tổng CO2e rồi nhân một tỷ lệ giảm phẳng — phải đổi hệ số rồi chạy
lại công thức. Có test riêng chốt điều này.

Đây là con số dùng cho Success Metric M5 và câu chuyện Before/After khi pitch (FR-1a-09).

### 3.4. Ràng buộc "không hardcode" (RB-01)

Mọi hệ số đọc từ `backend/config/emission_factors.yaml`. **Không có hằng số phát thải nào
viết thẳng trong hàm tính** — code review từ chối vi phạm này. Kết quả trả kèm
`ef_config_version` để truy vết ngược (FR-1a-12).

### 3.5. Không bịa số (NFR-03)

| Tình huống | Xử lý |
|---|---|
| Thiếu `yield_kg` | HTTP 200, `co2e_per_kg: null`, `warnings` giải thích. **Không trả 0.** |
| Hệ số cần dùng đang `null` trong config | HTTP 422, nêu rõ hệ số nào thiếu. **Không tự đặt giá trị mặc định.** |
| Nhiều bản ghi `water` mâu thuẫn `regime` | HTTP 422, liệt kê bản ghi mâu thuẫn. **Không tự chọn một giá trị.** |
| Hệ số đang dùng chưa đối chiếu MRV chính thức | Vẫn tính, nhưng thêm dòng vào `warnings` |

### 3.6. Kiến trúc: hàm thuần

Engine nhận Activity Data, trả kết quả, **không biết gì về UI**. Đây là điều kiện để:
test được bằng ca tính tay; chạy What-if Simulation ở giai đoạn 2 chỉ bằng cách gọi lại với
input giả định (NFR-04); dùng lại từ web-dashboard và export MRV mà không nhân bản logic.

---

## 4. Phụ thuộc

| Phụ thuộc vào | Ở mức nào |
|---|---|
| [`01-mobile-app`](01-mobile-app.md) | Nguồn Activity Data. Ở giai đoạn đầu có thể dùng dữ liệu mẫu (fixture) để phát triển song song, không chờ app xong. |
| `backend/config/emission_factors.yaml` | **Chặn cứng.** Hệ số còn `null` thì engine không tính được — xử lý open issue OI-02 trước hạn 15/09/2026. |

**Module 04, 05, 06, 07 đều phụ thuộc ngược lại vào module này.**

---

## 5. Definition of Done

- [ ] **T2-01** Đọc được bộ hệ số từ `emission_factors.yaml`, báo lỗi rõ khi hệ số `null` (RB-01)
- [ ] **T2-02** Tính đủ 4 nguồn phát thải ở §3.2, trả `breakdown` có tổng khớp `co2e_total_kg` (FR-1a-08)
- [ ] **T2-03** `POST /v1/carbon/calculate` chạy đúng hợp đồng ở [SRS §4.2](../SRS.md#42-post-v1carboncalculate--tính-co2e)
- [ ] **T2-04** Chạy được cả 3 giá trị `water_regime_scenario`, AWD và ngập liên tục ra số khác nhau (FR-1a-09)
- [ ] **T2-05** Unit test đối chiếu **ít nhất 1 ca tính tay**, sai số ≤ 0,1% (NFR-02)
- [ ] **T2-06** Test 3 ca lỗi ở §3.5 trả đúng mã lỗi và thông báo (NFR-03)
- [ ] **T2-07** Kết quả trả kèm `ef_config_version`; đổi config → version đổi theo (FR-1a-12)
- [ ] **T2-08** Trả về < 3 giây trên dữ liệu 1 vụ (NFR-05, M1)
- [ ] **T2-09** Đối chiếu kết quả với **FarMoRe** trên cùng 1 lô, ghi lại mức chênh lệch (open issue OI-03)
- [ ] **T2-10** Viết được đoạn giải thích 5 câu: "số này tính ra sao, dựa hệ số nào, khớp MRV chỗ nào" (M7)

---

## 6. Rủi ro & giả định riêng

| # | Nội dung |
|---|---|
| **RR-01** | **Chưa chốt bộ hệ số.** Tài liệu gốc ghi ~1,04 kg CO2/kg lúa (trung bình) và dải 2,29–3,72 kg CO2e/kg (tùy phương pháp) — **hai con số này chưa nhất quán về phạm vi khí nhà kính và ranh giới hệ thống**. Phải làm rõ (OI-01) trước khi dùng làm baseline trong báo cáo. Đây là rủi ro số 1 của cả dự án. |
| **RR-02** | Hệ số CH4 theo chế độ nước hiện đang `null` trong config. Chưa lấy được từ hướng dẫn MRV chính thức (QĐ 4801/QĐ-BNNMT) thì engine chưa ra số thật (OI-02). Nguồn dự phòng để đối chiếu: IPCC 2019 Refinement, Ch.5.5. |
| **RR-03** | **Giá tín chỉ carbon chưa chốt chính thức** — TCAF đang định giá. Nếu engine có phần quy đổi ra tiền, phải để `status: NOT_CONFIRMED` và hiển thị kèm nhãn "chưa chốt", hoặc ẩn hoàn toàn (RB-02). |
| **RR-04** | **Giả định:** dữ liệu nông dân nhập là trung thực. MVP chưa có Evidence/Anti-fraud (giai đoạn 2), nên số CO2e chỉ chính xác bằng độ chính xác của dữ liệu đầu vào. Nói rõ giới hạn này khi pitch thay vì để bị hỏi bất ngờ. |
| **RR-05** | RiceMoRe/FarMoRe **chưa có API mở** — không tự động đối chiếu được, phải làm thủ công trên vài lô mẫu. |

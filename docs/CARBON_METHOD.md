# CARBON_METHOD — Công thức tính phát thải & trạng thái xác minh

Phiên bản: 0.1 · Ngày: 2026-09-07
Liên quan: [`SRS.md`](SRS.md) · [`modules/02-carbon-engine.md`](modules/02-carbon-engine.md) ·
`backend/config/emission_factors.yaml`

> **Mục đích:** tách bạch rõ ràng giữa *phần đã code xong* và *phần khoa học chưa xác minh*.
> Engine hiện chạy được về mặt implementation nhưng **chưa tính ra được con số thật nào**,
> vì toàn bộ hệ số phát thải đang là `null` (open issue OI-02).
>
> Đây là trạng thái có chủ đích. Thà có *"Engine chưa tính được vì thiếu hệ số"* còn hơn
> *"Engine trả một con số sai nhưng nhìn có vẻ hợp lý"*.

---

## 1. Ba trạng thái

| Trạng thái | Nghĩa | Engine xử lý thế nào |
|---|---|---|
| **VERIFIED** | Công thức và hệ số đã có nguồn chính thức, nhóm đã đối chiếu. Dùng được cho báo cáo MRV. | Tính bình thường, không cảnh báo |
| **PENDING VERIFICATION** | Dạng công thức lấy từ tài liệu tham khảo (IPCC / tài liệu Đề án) nhưng **nhóm chưa xác minh chính thức**. | Tính được **nếu** có hệ số, nhưng luôn kèm cảnh báo trong `warnings` |
| **NOT IMPLEMENTED** | Chưa đủ thông tin để tính an toàn. | Không tính; ghi cảnh báo nêu rõ phần nào bị bỏ qua |

**Hiện tại chưa có mục nào ở trạng thái VERIFIED.**

---

## 2. Bảng công thức

| Source | Activity Data | EF | Formula | Unit | Status |
|---|---|---|---|---|---|
| **CH4 flooding** | `area_ha × cultivation_days` | `factors.methane.<regime>` | `area_ha × cultivation_days × EF` | dự kiến `kg_CO2e_per_ha_per_day` | **VERIFY** |
| **N2O fertilizer** | `Σ (amount_kg × n_content_pct / 100)` = kg N | `factors.fertilizer_n2o` | `kg_N × EF` | dự kiến `kg_CO2e_per_kg_N` | **VERIFY** |
| **Fuel** | `Σ pump_fuel_litre` | `factors.fuel.diesel` | `litre × EF` | dự kiến `kg_CO2e_per_litre` | **VERIFY** |
| **Straw** | `amount_kg` | `factors.straw.<method>` | `amount_kg × EF` | dự kiến `kg_CO2e_per_kg_straw` | **VERIFY** |

```text
CO2e_nguồn_i  =  Activity Data_i  ×  Emission Factor_i
CO2e_tổng     =  Σ CO2e_nguồn_i
CO2e/kg       =  CO2e_tổng / yield_kg
```

Cột "Unit" ghi **dự kiến** vì đơn vị chính thức phải lấy cùng lúc với hệ số (OI-04).
Nếu hướng dẫn MRV dùng đơn vị khác (ví dụ kg CH4/ha/vụ thay vì per-day, hoặc phải nhân
hệ số quy đổi GWP riêng), **cả cột Activity Data lẫn công thức đều phải sửa lại** — đây là
lý do không cột nào được đánh VERIFIED trước khi có nguồn.

---

## 3. Chi tiết từng nguồn

### 3.1. CH4 ruộng ngập — `ch4_flooding`

**Status: VERIFY** · chặn bởi OI-02, OI-04

Nguồn phát thải chi phối của canh tác lúa nước, và đúng là thứ MRV 6 bước đang đo.

- Activity Data hiện dùng: `area_ha × cultivation_days` (đơn vị `ha_day`).
- `cultivation_days` lấy từ field cùng tên, hoặc suy ra từ `sowing_date`/`harvest_date`.
  Thiếu cả hai → `MissingActivityDataError`, không đoán.
- Hệ số tách riêng theo chế độ nước: `methane.awd` và `methane.continuous_flooding`.
  Hai hệ số khác nhau là cơ chế duy nhất hiện có để hai kịch bản ra hai kết quả khác nhau.

**Cần nguồn gì để chuyển sang VERIFIED:**
bảng hệ số CH4 trong hướng dẫn MRV chính thức (QĐ 4801/QĐ-BNNMT), kèm đơn vị và
cơ sở tính (per ha per day, hay per ha per vụ). Nguồn đối chiếu: IPCC 2019 Refinement,
Vol.4 Ch.5.5.

### 3.2. N2O từ phân đạm — `n2o_fertilizer`

**Status: VERIFY** · chặn bởi OI-02

- Quy đổi mỗi lần bón thành kg N: `amount_kg × n_content_pct / 100`.
- Thiếu `n_content_pct` ở bất kỳ lần bón nào → `MissingActivityDataError`.
  Engine **không** tra bảng hàm lượng N theo tên phân, vì bảng đó cũng chưa được xác minh.
- Vụ không có bản ghi phân bón → bỏ qua nguồn này (không phải lỗi).

**Cần nguồn gì:** hệ số N2O (gồm cả trực tiếp và gián tiếp) theo hướng dẫn MRV; nếu tách
riêng trực tiếp/gián tiếp thì config phải tách theo, không gộp thành một số.

### 3.3. Nhiên liệu bơm tưới — `fuel_pumping`

**Status: VERIFY** · chặn bởi OI-02

- Activity Data: tổng `pump_fuel_litre` trên các bản ghi nước.
- Không ghi nhiên liệu → bỏ qua nguồn này.
- Hiện chỉ hỗ trợ diesel. Bơm điện cần hệ số lưới điện riêng — **NOT IMPLEMENTED**.

### 3.4. Xử lý rơm rạ — `straw_management`

**Status: VERIFY** · chặn bởi OI-02

- Activity Data: `amount_kg`. Hệ số theo phương pháp: `burned` / `incorporated` / `removed`.
- Có `method` nhưng thiếu `amount_kg` → `MissingActivityDataError`.
- Không có bản ghi rơm rạ → bỏ qua nguồn này.

⚠️ Cần xác minh **dấu** của hệ số: vùi rơm (`incorporated`) trong một số phương pháp luận
làm **tăng** CH4 vụ sau chứ không giảm phát thải. Không giả định hệ số nào âm hay dương.

---

## 4. NOT IMPLEMENTED — chưa đủ thông tin để tính an toàn

| Hạng mục | Vì sao chưa làm | Cần gì |
|---|---|---|
| **`drainage_events` trong công thức AWD** | Số lần rút nước ảnh hưởng CH4 qua hệ số điều chỉnh, nhưng chưa biết hướng dẫn MRV dùng dạng nào (bậc thang? liên tục?) | Hệ số điều chỉnh theo số lần rút nước (OI-04). Engine hiện chỉ dùng một hệ số AWD phẳng và **cảnh báo rõ** điều này |
| **Thuốc BVTV** | Có trong model dữ liệu nhưng chưa gắn với hệ số nào. Phát thải từ sản xuất/vận chuyển thuốc thuộc phạm vi upstream | Quyết định ranh giới hệ thống trước, rồi mới tìm hệ số |
| **Giống / lượng gieo sạ** | Tương tự — phát thải upstream, chưa chốt có nằm trong ranh giới hệ thống không | Ranh giới hệ thống theo hướng dẫn MRV |
| **Bơm điện** | Chỉ có hệ số diesel | Hệ số lưới điện Việt Nam |
| **Hấp thụ / trữ carbon trong đất** | Chưa nằm trong phạm vi MVP | — |
| **Quy đổi ra tiền tín chỉ carbon** | Giá **chưa chốt chính thức** (TCAF đang định giá) | SRS RB-02 — chỉ hiển thị khi có nhãn "chưa chốt", hoặc ẩn hoàn toàn |

---

## 5. Giá trị tham chiếu bị tranh chấp — KHÔNG dùng trong tính toán

Tài liệu gốc ghi hai con số ở cấp sản phẩm:

| Giá trị | Nguồn |
|---|---|
| ~1,04 kg CO2/kg lúa (trung bình) | `AgriCarbon_v2_Rice_Decision_and_Roadmap.md` §1a.2 |
| 2,29–3,72 kg CO2e/kg (dải theo phương pháp canh tác) | như trên |

**Hai con số này không nhất quán về phạm vi khí nhà kính và ranh giới hệ thống**
(1,04 ghi là kg CO2, dải kia ghi là kg CO2e; chênh nhau hơn 2 lần). Chưa giải quyết xong
**OI-01** thì không dùng làm baseline trong bất kỳ báo cáo nào.

Vì vậy chúng nằm ở mục `reference_values` **ngoài** khối `factors` trong config, và
`EmissionFactorSet` chỉ đọc `factors` — engine không có đường nào chạm tới chúng.

---

## 6. Trạng thái tổng kết

```text
VERIFIED             : 0 / 4 nguồn
PENDING VERIFICATION : 0 / 4 nguồn
VERIFY (chưa có nguồn): 4 / 4 nguồn  ← ch4_flooding, n2o_fertilizer, fuel, straw
NOT IMPLEMENTED      : drainage_events, thuốc BVTV, giống, bơm điện, carbon đất
```

**Hệ quả thực tế:** chạy engine với `backend/config/emission_factors.yaml` sẽ luôn ném
`MissingEmissionFactorError`. Đó là hành vi đúng. Muốn thấy pipeline chạy thông, dùng
TEST FACTORS (số bịa) — xem `backend/README.md`.

---

## 7. Việc cần làm để mở khoá

| # | Việc | Mở khoá được gì | Hạn |
|---|---|---|---|
| **OI-02** | Lấy bộ hệ số chính thức từ hướng dẫn MRV (QĐ 4801/QĐ-BNNMT) | Toàn bộ 4 nguồn — engine bắt đầu ra số thật | 15/09/2026 |
| **OI-04** | Xác minh đơn vị/cơ sở tính CH4 và cách đưa `drainage_events` vào công thức AWD | Độ chính xác kịch bản AWD | 15/09/2026 |
| **OI-01** | Giải quyết mâu thuẫn 1,04 vs 2,29–3,72 | Dùng được giá trị tham chiếu để đối chiếu kết quả | 15/09/2026 |
| **OI-03** | Đối chiếu kết quả engine với FarMoRe trên cùng 1 lô | Bằng chứng độ tin cậy để trả lời hội đồng | 18/09/2026 |

Kênh lấy nguồn: Văn phòng đối tác IRRI Việt Nam, Sở Nông nghiệp và Môi trường tỉnh
(Cần Thơ / An Giang / Đồng Tháp), Trung tâm Khuyến nông Quốc gia.

# CARBON_METHOD — Phương pháp luận tính phát thải

Phiên bản: 0.2 · Ngày: 2026-09-08 · Engine: 0.2.0 · Bộ tham số: `0.2.0-ipcc-tier1`
Nguồn từng dòng: [`CARBON_METHOD_SOURCES.md`](CARBON_METHOD_SOURCES.md)
Cấu hình: `backend/config/emission_factors.yaml` · Code: `backend/carbon/`

> **Trạng thái tổng quát:** cấu trúc công thức và hệ số CH4/N2O/đốt rơm đã **VERIFIED**
> theo IPCC. **GWP còn PENDING_VERIFICATION** nên engine chưa ra được con số CO2e nào.
> Đây là hành vi đúng theo thiết kế — xem §8.
>
> ⛔ **Chưa lấy được toàn văn QĐ 4801/QĐ-BNNMT.** Bộ số hiện tại là **IPCC Tier 1 default**,
> không phải hệ số đặc trưng quốc gia mà quy trình MRV yêu cầu.
> **Không được gắn nhãn "MRV-compliant" cho bất kỳ kết quả nào.**

Ba trạng thái dùng xuyên suốt tài liệu:

| Trạng thái | Nghĩa | Engine xử lý |
|---|---|---|
| **VERIFIED** | Trích dẫn chính xác từ tài liệu gốc, có số hiệu bảng/phương trình | Tính bình thường |
| **PENDING_VERIFICATION** | Chưa lấy được nguồn; `value: null` | Raise `MissingEmissionFactorError` |
| **NOT_IMPLEMENTED** | Cố ý chưa làm | Không tính; ghi cảnh báo nêu rõ phần nào bị bỏ qua |

---

## 1. Ranh giới hệ thống

**Đơn vị chức năng:** 1 kg lúa thu hoạch, trên một vụ canh tác của một thửa ruộng.

**Phạm vi thời gian:** từ khi bắt đầu canh tác đến khi thu hoạch (cultivation period).

### Nằm TRONG ranh giới

| Nguồn | Khí | Trạng thái |
|---|---|---|
| CH4 từ ruộng lúa ngập | CH4 | ✅ VERIFIED |
| N2O trực tiếp từ đầu vào đạm | N2O | ✅ VERIFIED |
| Đốt rơm rạ ngoài đồng | CH4, N2O | ✅ VERIFIED |
| Đốt nhiên liệu (bơm tưới, máy móc) | CO2e | ⏳ PENDING (thiếu hệ số) |

### Nằm NGOÀI ranh giới (NOT_IMPLEMENTED — cố ý)

| Bị loại | Vì sao |
|---|---|
| **N2O gián tiếp** (bay hơi NH3/NOx, rửa trôi — IPCC Eq 11.9/11.10) | Cần dữ liệu khí hậu/thuỷ văn chưa thu thập. Engine cảnh báo mỗi lần tính |
| **N từ phân hữu cơ (F_ON)** | Chưa phân biệt được trong dữ liệu nhập; engine cảnh báo khi gặp `is_organic` |
| **Phát thải upstream** của giống, thuốc BVTV, sản xuất phân bón | Ngoài ranh giới cấp ruộng; cần dữ liệu vòng đời (LCA) |
| **CH4 ngoài vụ** (trước gieo sạ, sau thu hoạch) | IPCC ghi rõ SFp **chỉ** dùng để ước tính CH4 TRONG vụ, *"cannot be used to quantify CH4 emissions that occurred before the cultivation period or after harvest"* |
| **CO2 từ đốt rơm** | Theo thông lệ IPCC thuộc chu trình carbon sinh học, không tính là phát thải ròng. Cần xác nhận QĐ 4801 có theo thông lệ này không (`factors.straw_burning.co2_counted` — PENDING) |
| **Hấp thụ/trữ carbon trong đất** | Ngoài phạm vi MVP |
| **Bơm điện** | Chưa có hệ số lưới điện VN. Engine **cảnh báo và KHÔNG cộng vào tổng** |
| **SFs (đất), SFr (giống)** — IPCC Eq 5.2a Tier 2 | Chưa có hệ số đặc trưng VN |

---

## 2. Vì sao KHÔNG có một công thức chung

`Activity Data × Emission Factor` là abstraction ở tầng cao, **không phải công thức tính**.
Mỗi nguồn có phương pháp luận riêng và cấu trúc khác hẳn nhau:

| Nguồn | Cấu trúc thật |
|---|---|
| CH4 lúa | `(EFc × SFw × SFp × SFo) × t × A` — bốn hệ số nhân với nhau, trong đó SFo là **hàm luỹ thừa** của lượng chất hữu cơ |
| N2O phân | `kg_N × EF1FR × 44/28 × GWP` — hệ số áp lên **kg N**, không phải kg phân, và có bước quy đổi phân tử |
| Đốt rơm | `M_khô × Cf × Gef × 10⁻³ × GWP` — có hệ số cháy Cf, hệ số theo g/kg |
| Nhiên liệu | `lít × EF` — đây mới đúng là một phép nhân đơn |

Code phản ánh đúng điều này: `backend/carbon/methodology.py` có một class riêng cho mỗi nguồn.

---

## 3. CH4 từ canh tác lúa — **VERIFIED**

Nguồn: IPCC 2019 Refinement, Vol.4, Ch.5, §5.5.

### Công thức

```text
Eq 5.1 :  CH4 [kg]  =  EFi × t × A
Eq 5.2 :  EFi       =  EFc × SFw × SFp × SFo          (Tier 1)
Eq 5.3 :  SFo       =  (1 + Σ ROAi × CFOAi) ^ 0,59
          CO2e      =  CH4 × GWP_CH4
```

| Ký hiệu | Nghĩa | Đơn vị | Nguồn |
|---|---|---|---|
| `EFc` | Hệ số nền, ruộng ngập liên tục, không chất hữu cơ | kg CH4/ha/ngày | Table 5.11, SE Asia = **1,22** |
| `SFw` | Điều chỉnh theo chế độ nước **trong** vụ | — | Table 5.12 |
| `SFp` | Điều chỉnh theo chế độ nước **trước** vụ | — | Table 5.13 |
| `SFo` | Điều chỉnh theo chất hữu cơ bổ sung | — | Eq 5.3 + Table 5.14 |
| `t` | Số ngày canh tác | ngày | **Bắt buộc dữ liệu thực tế.** Table 5.11A (102 ngày) là trung bình vùng cho kiểm kê quốc gia — engine KHÔNG dùng làm mặc định |
| `A` | Diện tích | ha | Dữ liệu thực tế |

Tier 2 (Eq 5.2a) thêm `SFs` (đất) và `SFr` (giống) — **NOT_IMPLEMENTED**, chưa có hệ số VN.

### Vì sao KHÔNG bỏ qua SFp được

Chế độ nước **trước** vụ ảnh hưởng mạnh hơn hầu hết người ta tưởng:

| Chế độ trước vụ | SFp |
|---|---|
| Không ngập <180 ngày | 1,00 |
| Không ngập >180 ngày | 0,89 |
| **Ngập ≥30 ngày** | **2,41** |
| Không ngập >365 ngày | 0,59 |

Bỏ qua SFp trên một ruộng ngập trước vụ làm **thiếu hơn một nửa** lượng CH4. Engine
raise `MethodologyGapError` khi thiếu trường này, **không mặc định 1,0**.

---

## 4. Chế độ nước — **VERIFIED**

### SFw (Table 5.12, cột disaggregated)

| Chế độ nước | SFw | Khoảng |
|---|---|---|
| Irrigated — ngập liên tục | **1,00** | 0,73–1,27 |
| Irrigated — rút nước 1 lần | 0,71 | 0,53–0,94 |
| **Irrigated — rút nước nhiều lần (gồm AWD)** | **0,55** | 0,41–0,72 |
| Rainfed — thường | 0,54 | 0,39–0,74 |
| Rainfed — hay hạn | 0,16 | 0,11–0,24 |
| Nước sâu | 0,06 | 0,03–0,12 |
| Lúa cạn | 0,00 | — |

**AWD nằm ở đâu:** nguyên văn chú thích b Table 5.12 — *"Multiple drainage periods: Fields
have more than one drainage event and period of time without flooded conditions during the
cropping season, in addition to an end of season drainage, **including alternate wetting and
drying (AWD)**."*

### AWD tác động NGƯỢC CHIỀU lên hai khí

Đây là điểm dễ làm sai nhất trong toàn bộ phương pháp luận:

| | Ngập liên tục | AWD | Chiều |
|---|---|---|---|
| CH4 — SFw | 1,00 | **0,55** | ⬇ giảm 45% |
| N2O — EF1FR | 0,003 | **0,005** | ⬆ **tăng 67%** |

Kịch bản nước phải đi vào **cả CH4 lẫn N2O**. Engine có test riêng chốt điều này
(`test_scenario_drives_both_ch4_and_n2o`).

### Kịch bản KHÔNG phải một tỷ lệ giảm áp lên tổng

**Sai:**

```python
continuous_flooding_co2e = actual_co2e
awd_co2e = actual_co2e * 0.55        # ❌ tuyệt đối không
```

**Đúng:** đổi `SFw` và `EF1FR`, rồi chạy lại toàn bộ công thức. Vì AWD tác động ngược chiều
lên hai khí, một hệ số phẳng áp lên tổng luôn cho kết quả sai — và sai bao nhiêu thì phụ
thuộc tỷ lệ phân bón của từng ruộng.

Test `test_scenario_is_not_a_flat_percentage_of_total` bắt đúng lỗi này: nếu ai đó cài
tỷ lệ phẳng, tỷ số CH4/N2O giữa hai kịch bản sẽ bằng nhau — test sẽ đỏ.

### Ba kịch bản engine hỗ trợ

| Kịch bản | Nghĩa |
|---|---|
| `continuous_flooding` | Ghi đè `irrigated_continuous_flooding` — dùng làm **đường cơ sở** (bước 3 MRV) |
| `awd` | Ghi đè `irrigated_multiple_drainage` |
| `as_recorded` | Dùng đúng chế độ nông dân đã ghi |

Bản ghi tưới mâu thuẫn nhau → `ConflictingWaterRegimeError`, **kể cả khi kịch bản ghi đè**:
dữ liệu mâu thuẫn là lỗi nhập liệu, phải sửa ở nguồn.

---

## 5. Xử lý rơm rạ — **VERIFIED** · phần dễ tính hai lần nhất

### Nguyên tắc phân luồng

Nguyên văn chú thích a, Table 5.14:

> *"Straw application means that straws are incorporated into the soil. It does not include
> cases where straws are just placed on soil surface, and **straws that were burnt on the
> field**."*

Từ đó, mỗi bản ghi rơm đi **đúng một đường**:

```text
                    ┌── incorporated ──────► SFo (điều chỉnh CH4 ruộng ngập)
                    │                        CFOA: <30 ngày = 1,00 | ≥30 ngày = 0,19
   straw event ─────┼── composted ─┬─ trả lại ruộng ──► SFo, CFOA compost = 0,17
                    │              └─ mang đi ────────► không tính
                    ├── burned ────────────► nguồn ĐỐT ĐỒNG riêng (CH4 + N2O)
                    └── removed ───────────► không tính
```

**KHÔNG BAO GIỜ cả hai đường.** Rơm vùi **không phải một nguồn phát thải riêng** — nó là
đầu vào của SFo. Cộng thêm `straw_mass × straw_EF` vào tổng chính là double counting.

Engine chốt bất biến này bằng `_assert_no_double_counting()`, có test riêng
(`test_double_counting_guard_raises`).

### CFOA (Table 5.14)

| Loại chất hữu cơ | CFOA | Khoảng |
|---|---|---|
| Rơm vùi **<30 ngày** trước canh tác | **1,00** | 0,85–1,17 |
| Rơm vùi **≥30 ngày** trước canh tác | **0,19** | 0,11–0,28 |
| Compost | 0,17 | 0,09–0,29 |
| Phân chuồng | 0,21 | 0,15–0,28 |
| Phân xanh | 0,45 | 0,36–0,57 |

**Chênh hơn 5 lần** giữa vùi sát vụ và vùi sớm → engine raise `MethodologyGapError` khi
thiếu `days_before_cultivation`, **không đoán**.

`ROA` tính theo **khối lượng khô**, đơn vị tấn/ha → thiếu `dry_matter_fraction` cũng raise.

### Đốt rơm — nguồn riêng

Nguồn: IPCC 2006 GL, Vol.4, Ch.2, Eq 2.27.

```text
L [kg khí]  =  M_khô [kg]  ×  Cf  ×  Gef [g/kg]  ×  10⁻³
```

| Tham số | Giá trị | Nguồn |
|---|---|---|
| `Cf` — hệ số cháy, rơm lúa | 0,80 | Table 2.6 |
| `Gef` CH4 | 2,7 g/kg DM | Table 2.5, agricultural residues |
| `Gef` N2O | 0,07 g/kg DM | Table 2.5 |

CO2 từ đốt **không** được tính (chu trình carbon sinh học) — cần xác nhận với QĐ 4801.

---

## 6. N2O từ phân bón — **VERIFIED**

Nguồn: IPCC 2019 Refinement, Vol.4, Ch.11.

```text
Eq 11.1 :  N2O-N [kg]  =  F_FR [kg N]  ×  EF1FR
           N2O   [kg]  =  N2O-N × 44/28
           CO2e        =  N2O × GWP_N2O
```

### kg phân ≠ kg N

Hệ số áp lên **kg N**, không phải kg phân bón. Bắt buộc quy đổi trước:

```text
120 kg urea × 46% N  =  55,2 kg N
```

**Sai:**

```python
n2o = fertilizer_amount_kg * n2o_factor   # ❌ áp hệ số lên kg phân
```

Engine raise khi thiếu `n_content_pct` — **không tra bảng hàm lượng N theo tên phân**, vì
bảng đó cũng chưa được xác minh.

### EF1FR (Table 11.1)

| Chế độ nước | EF1FR | Khoảng |
|---|---|---|
| Ngập liên tục | 0,003 | 0,000–0,010 |
| **Rút nước 1 lần và nhiều lần (gồm AWD)** | **0,005** | 0,000–0,016 |
| Gộp (khi không phân loại được) | 0,004 | 0,000–0,029 |

Nguyên văn chú thích 7: *"Single and multiple drainage also include alternate wetting and drying."*

- **Rainfed / nước sâu:** Table 11.1 không tách riêng → engine dùng giá trị **gộp** và **cảnh báo**.
- **Lúa cạn:** chú thích 7 yêu cầu dùng `EF1` (không phải `EF1FR`); `EF1` chưa được cấu hình
  → engine raise `MethodologyGapError`. **NOT_IMPLEMENTED.**

---

## 7. Nhiên liệu — **PENDING_VERIFICATION**

```text
CO2e  =  lít  ×  EF_nhiên_liệu
```

Toàn bộ `factors.fuel.*` đang `null`. Cần: QĐ 2626/QĐ-BTNMT Phụ lục Năng lượng, hoặc
IPCC 2006 Vol.2 Ch.3 kèm nhiệt trị và khối lượng riêng. Open issue **OI-06**.

Chưa xác minh: có cần tính CH4/N2O từ đốt nhiên liệu không (thường rất nhỏ so với CO2).

**Bơm điện** (`irrigation_events.pump_energy_kwh`): chưa có hệ số lưới điện VN → engine
**cảnh báo và KHÔNG cộng vào tổng**, thay vì bỏ qua im lặng.

---

## 8. GWP — **PENDING_VERIFICATION** · đang chặn toàn bộ

```text
CO2e  =  CH4 × GWP_CH4  +  N2O × GWP_N2O
```

**Chưa xác minh được QĐ 4801 quy định khung nào.** Không tự chọn, vì chênh lệch lớn:

| Khung | GWP-100 CH4 | GWP-100 N2O |
|---|---|---|
| AR4 (2007) | 25 | 298 |
| AR5 (2013) | 28 | 265 |
| AR6 (2021) | 27,9 (phi hoá thạch) / 29,8 | 273 |

Chọn AR4 thay vì AR6 làm lệch CH4 tới **~19%** — mà CH4 chiếm phần lớn phát thải lúa nước.
Ba giá trị trên **liệt kê để biết cần tra cái gì**, chưa được đưa vào config.

**Hệ quả:** chạy engine với config thật hiện nay luôn dừng ở
`MissingEmissionFactorError: gwp.ch4 chưa được xác minh/cấu hình`. Open issue **OI-05**.

Đây là lựa chọn có chủ đích: thà *"Engine chưa tính được vì thiếu GWP"* còn hơn
*"Engine trả một con số sai nhưng nhìn có vẻ hợp lý"*.

---

## 9. Tổng hợp

```text
CO2e_tổng  =  Σ CO2e của từng dòng breakdown
```

Bất biến được test chốt (`test_breakdown_sums_to_total`): tổng các dòng phân rã **luôn**
bằng `total_co2e_kg`, trên cả ba kịch bản.

Mỗi dòng breakdown mang đủ để tái hiện phép tính:

| Trường | Nội dung |
|---|---|
| `source`, `gas` | Nguồn phát thải và khí |
| `activity_value`, `activity_unit` | Dữ liệu hoạt động và đơn vị (`ha_day`, `kg_N`, `kg_dry_matter`, `litre`) |
| `gas_kg` | Khối lượng khí **trước** khi quy đổi CO2e |
| `co2e_kg` | Sau khi nhân GWP |
| `formula` | Công thức dạng chữ, kèm số hiệu phương trình IPCC |
| `factors_used` | Mọi tham số đã dùng, theo đường dẫn config, gồm cả giá trị trung gian (`_derived.sfo`, `_derived.ef_i`) |
| `provenance` | Nguồn trích dẫn của từng tham số |

Chuỗi truy vết đầy đủ:

```text
CO2e/kg → total → breakdown → formula → factors_used → provenance → tài liệu gốc
```

---

## 10. CO2e/kg

```text
CO2e/kg  =  CO2e_tổng  /  yield_kg
```

| Tình huống | Xử lý |
|---|---|
| `yield_kg` là NULL | `co2e_per_kg = None` + cảnh báo *"Chưa có sản lượng nên chưa tính được CO2e/kg."* **KHÔNG trả 0** |
| `yield_kg <= 0` | `MissingActivityDataError` — khớp ràng buộc `carbon_yield_chk` của Supabase |

---

## 11. Giới hạn — phải nói ra khi pitch

1. **Chưa phải MRV-compliant.** Đang dùng IPCC Tier 1 default. Quy trình MRV yêu cầu hệ số
   đặc trưng quốc gia đo trực tiếp trên đồng ruộng (Tier 2). Chưa lấy được QĐ 4801 (OI-02).
2. **Chưa ra được số CO2e** vì GWP chưa xác minh (OI-05).
3. **Độ không chắc chắn lớn.** EFc SE Asia 1,22 có khoảng 0,83–1,81 — tức ±~40%. Mọi con số
   trình bày phải kèm khoảng, không nói như số đo chính xác.
4. **Chỉ chính xác bằng dữ liệu đầu vào.** MVP chưa có Evidence/Anti-fraud (giai đoạn 2).
5. **Nhiều nguồn nằm ngoài ranh giới** — xem §1. Không được trình bày kết quả như "tổng dấu
   chân carbon" của hạt gạo.
6. **Tên 6 bước MRV cần đối chiếu lại.** Báo chí ghi *"giám sát/xác minh"*, tài liệu dự án ghi
   *"Đo đạc/Thẩm định"* (OI-07).
7. **Giá tín chỉ carbon chưa chốt** — không quy đổi ra tiền (SRS RB-02).
8. **"Không có bản ghi" ≠ "bằng không".** Vụ không có bản ghi rơm cho SFo = 1,0; không có bản
   ghi phân cho N2O = 0. Engine không phân biệt được "nông dân thực sự không làm" với "chưa
   nhập liệu", nên **cảnh báo mỗi lần gặp**. Người đọc báo cáo phải tự kiểm.
9. **Số ngày canh tác không có giá trị mặc định.** IPCC Table 5.11A (102 ngày, SE Asia) là
   trung bình VÙNG cho kiểm kê quốc gia — áp cho một thửa ruộng cụ thể là sai phạm vi.
   Thiếu ngày gieo sạ/thu hoạch thì engine **báo lỗi**, không thay bằng số mặc định.
10. **Đơn vị nước chưa nhất quán giữa tài liệu.** SRS FR-1b-05 ghi *"lít nước/kg"* nhưng
    Supabase lưu `irrigation_events.water_volume_m3`. Không ảnh hưởng Carbon Engine (nước
    không vào công thức phát thải nào) nhưng **chặn module 04** — phải chốt một đơn vị và
    ghi phép quy đổi tường minh.

---

## 12. Bảng trạng thái

```text
VERIFIED             : CH4 lúa (Eq 5.1/5.2/5.3, Tables 5.11/5.11A/5.12/5.13/5.14)
                       N2O trực tiếp (Eq 11.1, Table 11.1)
                       Đốt rơm (Eq 2.27, Tables 2.5/2.6)
PENDING_VERIFICATION : GWP CH4, GWP N2O            ← đang chặn toàn bộ việc ra số
                       Hệ số nhiên liệu, hệ số lưới điện
                       CO2 từ đốt rơm có tính hay không
NOT_IMPLEMENTED      : N2O gián tiếp · N từ phân hữu cơ · upstream giống/thuốc BVTV
                       CH4 ngoài vụ · carbon đất · SFs/SFr (Tier 2) · lúa cạn (EF1)
                       cột aggregated của Table 5.13
NOT_OBTAINED         : QĐ 4801/QĐ-BNNMT toàn văn ← chặn nhãn MRV-compliant
```

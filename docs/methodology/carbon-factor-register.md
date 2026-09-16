# Sổ đăng ký hệ số Carbon — AgriCarbon

> Bộ hệ số **`0.3.0-ipcc2019-tier1-ar5`** · khung GWP **AR5 GWP-100** · IPCC 2019 Refinement Tier 1
> Trạng thái khoa học: **READY_FOR_DEMO** · Rà soát chuyên gia: **PENDING**
> Cập nhật: 2026-09-16

Đây là sổ đăng ký **từng hệ số** mà Carbon Engine tiêu thụ. Ba nguồn sự thật, không trùng vai:

| Nơi | Vai trò |
|---|---|
| `backend/config/emission_factors.yaml` | **Giá trị** hệ số (số, đơn vị, nguồn, status) |
| `backend/carbon/factor_register.py` | **Luật** quanh hệ số (code bắt buộc, đơn vị engine kỳ vọng, validate fail-closed) |
| Tài liệu này | **Diễn giải người đọc**: xuất xứ, phạm vi áp dụng quốc gia, vết đơn vị, hạn chế |

Không sửa file này để "chữa" một con số. Giá trị sửa ở YAML, và mọi thay đổi khoa học phải
tạo **version_code mới** — bộ đã publish là bất biến (xem §7).

---

## 1. Quyết định khung GWP

**GWP_POLICY_STATUS = DECIDED** (chủ dự án, 2026-09-15)

| Mục | Giá trị |
|---|---|
| Khung | **IPCC AR5 GWP-100** |
| CH4 | **28** kgCO2e/kgCH4 |
| N2O | **265** kgCO2e/kgN2O |

Lý do: một khung GWP duy nhất cho mọi khí; khớp bối cảnh báo cáo đã xác định trong audit nguồn;
tránh trộn lẫn phương pháp luận AR5/AR6; phù hợp mức triển khai Tier 1 hiện tại.

**Nguồn sơ cấp (xác minh trực tiếp trên bản gốc, không qua trang thứ cấp):**

| Trường | Nội dung |
|---|---|
| Publication | IPCC AR5 WG1 (2013), *Climate Change 2013: The Physical Science Basis* |
| Chapter/Table | Ch.8 *Anthropogenic and Natural Radiative Forcing*, **Table 8.A.1** |
| Gas / Horizon | CH4 = 28 · N2O = 265 · **GWP-100 năm** |
| Caveat biogenic/non-fossil | Table 8.A.1 tách riêng **"Fossil methane" = 30**. CH4 từ ruộng lúa và đốt rơm là **sinh học (non-fossil)** → dùng **28**, KHÔNG dùng 30. Cả hai là cột *no climate-carbon feedback*. |
| Độ bất định | CH4 ±40 %, N2O ±30 % (dải 90 %, theo ghi chú Table 8.A.1) |
| Căn cứ chính sách chọn khung | UNFCCC decision **18/CMA.1, annex, §37** + decision **5/CMA.3, §25** — báo cáo theo Thoả thuận Paris dùng GWP-100 của AR5 |

Khung **không** được chọn, giữ lại để đối chiếu: AR4 (CH4 25 / N2O 298), AR6 WG1 Table 7.SM.7
(CH4 27,9 phi hoá thạch / N2O 273).

QĐ 2626/QĐ-BTNMT đã đọc — **không nêu khung GWP**. QĐ 4801/QĐ-BNNMT **chưa lấy được toàn văn**.
Nếu một trong hai quy định khung khác, **tạo bộ hệ số phiên bản mới**, không sửa bộ đã publish.

---

## 2. Bảng đăng ký hệ số (27 hệ số core, tất cả VERIFIED)

Phân loại phạm vi quốc gia: `IPCC_DEFAULT` · `VIETNAM_SPECIFIC` · `PROJECT_ASSUMPTION` · `MISSING`.

### 2.1 GWP

| Factor key | Tên hiển thị | Giá trị | Đơn vị | Nguồn | Bảng/trang | Năm | Địa lý | Kịch bản | Xác minh | Bất định | Ghi chú | Engine dùng ở đâu |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `gwp.ch4` | GWP-100 CH4 | 28 | kgCO2e/kgCH4 | IPCC AR5 WG1 | Ch.8 Table 8.A.1 | 2013 | Toàn cầu · `IPCC_DEFAULT` | mọi | VERIFIED | ±40 % | Non-fossil; KHÔNG dùng 30 | Quy đổi CH4 lúa + CH4 đốt rơm |
| `gwp.n2o` | GWP-100 N2O | 265 | kgCO2e/kgN2O | IPCC AR5 WG1 | Ch.8 Table 8.A.1 | 2013 | Toàn cầu · `IPCC_DEFAULT` | mọi | VERIFIED | ±30 % | — | Quy đổi N2O phân bón + N2O đốt rơm |

### 2.2 CH4 canh tác lúa — Eq 5.1 `CH4 = EFi × t × A`, Eq 5.2 `EFi = EFc × SFw × SFp × SFo`

| Factor key | Tên hiển thị | Giá trị | Đơn vị | Nguồn | Bảng | Năm | Địa lý | Kịch bản | Xác minh | Bất định | Ghi chú | Engine dùng |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ch4_rice.efc` | EFc — baseline CH4 | 1,22 | kgCH4/ha/ngày | IPCC 2019 Ref. Vol.4 Ch.5 | Table 5.11 (UPDATED) | 2019 | **Southeast Asia** · `IPCC_DEFAULT` | mọi | VERIFIED | 0,83–1,81 | Baseline: không ngập <180 ngày trước vụ, ngập liên tục trong vụ, KHÔNG chất hữu cơ. World default 1,19 | Nhân tử gốc Eq 5.2 |
| `ch4_rice.sfw.irrigated_continuous_flooding` | SFw ngập liên tục | 1,00 | — | như trên | Table 5.12 (UPDATED), disaggregated | 2019 | Toàn cầu · `IPCC_DEFAULT` | as_recorded | VERIFIED | 0,73–1,27 | Mốc tham chiếu | SFw |
| `ch4_rice.sfw.irrigated_single_drainage` | SFw rút nước 1 lần | 0,71 | — | như trên | Table 5.12 | 2019 | `IPCC_DEFAULT` | as_recorded | VERIFIED | 0,53–0,94 | — | SFw |
| `ch4_rice.sfw.irrigated_multiple_drainage` | SFw rút nước nhiều lần | 0,55 | — | như trên | Table 5.12 | 2019 | `IPCC_DEFAULT` | as_recorded + **awd** | VERIFIED | 0,41–0,72 | Chú thích b Table 5.12 nguyên văn: *"Multiple drainage periods: … including alternate wetting and drying (AWD)."* → **AWD ánh xạ vào đây** | SFw; kịch bản AWD |
| `ch4_rice.sfw.rainfed_regular` | SFw nhờ nước trời | 0,54 | — | như trên | Table 5.12 | 2019 | `IPCC_DEFAULT` | as_recorded | VERIFIED | 0,39–0,74 | — | SFw |
| `ch4_rice.sfw.rainfed_drought_prone` | SFw nhờ nước trời, dễ hạn | 0,16 | — | như trên | Table 5.12 | 2019 | `IPCC_DEFAULT` | as_recorded | VERIFIED | 0,11–0,24 | — | SFw |
| `ch4_rice.sfw.deep_water` | SFw nước sâu | 0,06 | — | như trên | Table 5.12 | 2019 | `IPCC_DEFAULT` | as_recorded | VERIFIED | 0,03–0,12 | — | SFw |
| `ch4_rice.sfw.upland` | SFw ruộng cạn | 0,00 | — | như trên | Table 5.12 | 2019 | `IPCC_DEFAULT` | as_recorded | VERIFIED | — | Không ngập đáng kể → CH4 = 0 | SFw |
| `ch4_rice.sfp.non_flooded_pre_season_lt_180d` | SFp không ngập <180 ngày | 1,00 | — | như trên | Table 5.13 (UPDATED), disaggregated | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 0,88–1,12 | Thường gặp khi 2 vụ lúa/năm | SFp |
| `ch4_rice.sfp.non_flooded_pre_season_gt_180d` | SFp không ngập >180 ngày | 0,89 | — | như trên | Table 5.13 | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 0,80–0,99 | — | SFp |
| `ch4_rice.sfp.flooded_pre_season_gt_30d` | SFp ngập >30 ngày trước vụ | 2,41 | — | như trên | Table 5.13 | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 2,13–2,73 | **Làm hơn gấp đôi phát thải** — không được bỏ qua | SFp |
| `ch4_rice.sfp.non_flooded_pre_season_gt_365d` | SFp không ngập >365 ngày | 0,59 | — | như trên | Table 5.13 | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 0,41–0,84 | Luân canh cây cạn – lúa | SFp |
| `ch4_rice.sfo_exponent` | Số mũ SFo (Eq 5.3) | 0,59 | — | như trên | **Equation 5.3** | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 0,54–0,64 | `SFo = (1 + Σ ROAi × CFOAi)^0,59` | SFo |
| `ch4_rice.cfoa.straw_incorporated_lt_30d` | CFOA rơm vùi <30 ngày | 1,00 | — | như trên | Table 5.14 (UPDATED) | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 0,85–1,17 | Vùi sát vụ | SFo |
| `ch4_rice.cfoa.straw_incorporated_gt_30d` | CFOA rơm vùi >30 ngày | 0,19 | — | như trên | Table 5.14 | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 0,11–0,28 | ~1/5 so với vùi sát vụ | SFo |
| `ch4_rice.cfoa.compost` | CFOA phân ủ | 0,17 | — | như trên | Table 5.14 | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 0,09–0,29 | — | SFo |
| `ch4_rice.cfoa.farmyard_manure` | CFOA phân chuồng | 0,21 | — | như trên | Table 5.14 | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 0,15–0,28 | — | SFo |
| `ch4_rice.cfoa.green_manure` | CFOA phân xanh | 0,45 | — | như trên | Table 5.14 | 2019 | `IPCC_DEFAULT` | mọi | VERIFIED | 0,36–0,57 | — | SFo |

**SFp — dữ liệu đầu vào có thật không?** Có. `CropActivityData.pre_season_water_regime` là trường
bắt buộc trên thực tế: thiếu → `MethodologyGapError`, giá trị lạ ngoài `PRE_SEASON_REGIMES` →
cũng bị chặn. Engine **không** thay bằng default ngầm, nên không có chế độ nước trước vụ nào bị
bịa ra. (`test_missing_required_input_fails_instead_of_defaulting` khoá cả 4 đầu vào bắt buộc:
`pre_season_water_regime`, `water_regime`, `cultivation_days`, `n_content_pct`.)

**SFo — không double count.** Rơm **vùi lại ruộng** đi vào SFo (ROA tính theo **khối lượng khô**:
`mass_kg × dry_matter_fraction / 1000 / area_ha`, đơn vị tấn DM/ha). Rơm **đốt** đi vào nguồn
`straw_burning_*` riêng và **không** chạm SFo. `returned_to_field` quyết định nhánh; thiếu
`returned_to_field` hoặc `dry_matter_fraction` thì fail closed, không đoán. Test khoá hành vi này:
`test_straw_incorporated_goes_to_sfo_only`, `test_straw_burned_is_a_separate_source_and_does_not_touch_sfo`.

### 2.3 N2O từ đạm — Eq 11.1 `N2O-N = F_FR × EF1FR`, `N2O = N2O-N × 44/28`

| Factor key | Tên hiển thị | Giá trị | Đơn vị | Nguồn | Bảng | Năm | Địa lý | Kịch bản | Xác minh | Bất định | Ghi chú | Engine dùng |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `n2o_fertilizer.ef1fr.continuous_flooding` | EF1FR ngập liên tục | 0,003 | kgN2O-N/kgN | IPCC 2019 Ref. Vol.4 Ch.11 | Table 11.1 (UPDATED), disaggregated | 2019 | `IPCC_DEFAULT` | as_recorded | VERIFIED | 0,000–0,010 | — | N2O trực tiếp |
| `n2o_fertilizer.ef1fr.single_and_multiple_drainage` | EF1FR rút nước 1/nhiều lần | 0,005 | kgN2O-N/kgN | như trên | Table 11.1 | 2019 | `IPCC_DEFAULT` | as_recorded + **awd** | VERIFIED | 0,000–0,016 | Chú thích 7 Table 11.1 nguyên văn: *"Single and multiple drainage also include alternate wetting and drying."* → **AWD dùng hệ số này** | N2O trực tiếp; kịch bản AWD |
| `n2o_fertilizer.ef1fr.aggregate` | EF1FR gộp | 0,004 | kgN2O-N/kgN | như trên | Table 11.1, aggregated | 2019 | `IPCC_DEFAULT` | fallback | VERIFIED | 0,000–0,029 | Chỉ khi không phân loại được chế độ nước | N2O trực tiếp |
| `n2o_fertilizer.n2o_n_to_n2o` | Quy đổi N2O-N → N2O | 1,571428… (44/28) | kgN2O/kgN2O-N | Tỷ lệ khối lượng phân tử | IPCC 2019 Ref. Vol.4 Ch.11 | — | Hằng số hoá học | mọi | VERIFIED | — | **Hằng số hoá học, không phải emission factor** | Áp đúng **một lần** |

**Chuỗi truy vết N2O (đã kiểm từng bước, không nhân đôi quy đổi):**

```
FertilizerApplication.amount_kg ──×── n_content_pct/100 ──→  F_FR  [kg N]
F_FR                            ──×── EF1FR             ──→  N2O-N [kg N2O-N]
N2O-N                           ──×── 44/28 (đúng 1 lần)──→  N2O   [kg N2O]
N2O                             ──×── GWP 265 (AR5)     ──→  CO2e  [kg CO2e]
```

Bước đầu là property `FertilizerApplication.nitrogen_kg`; `n_content_pct` thiếu thì property trả
`None`, engine `raise MissingActivityDataError` và API trả **lỗi client 4xx** — không đoán 46 %
(`backend/tests/test_nitrogen_validation.py`).
Quy đổi 44/28 nằm ở **một** chỗ duy nhất
trong `FertilizerN2OCalculator`; `test_hand_calculation_baseline_season` khoá giá trị tuyệt đối nên
double-conversion sẽ làm test đỏ ngay.

**Tương tác AWD ↔ N2O.** AWD **không** dùng phần trăm giảm phẳng. AWD đổi *đồng thời* hai hệ số
theo đúng đường dẫn nguồn: SFw 1,00 → 0,55 (CH4 **giảm**) và EF1FR 0,003 → 0,005 (N2O **tăng**).
Test `test_awd_scenario_changes_both_ch4_and_n2o_factors_not_a_flat_percentage` khẳng định mức giảm
tổng 43,153 % **khác** tỷ lệ SFw 45 % — tức trade-off thật, không phải hằng số gắn cứng.

### 2.4 Đốt rơm ngoài đồng — Eq 2.27 `L = M_dm × Cf × Gef × 10⁻³`

| Factor key | Tên hiển thị | Giá trị | Đơn vị | Nguồn | Bảng | Năm | Địa lý | Kịch bản | Xác minh | Bất định | Ghi chú | Engine dùng |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `straw_burning.combustion_factor_rice` | Cf — hệ số cháy, rơm lúa | 0,80 | — | IPCC 2006 GL Vol.4 Ch.2 | **Table 2.6** — rice residues, post-harvest | 2006 | `IPCC_DEFAULT` | mọi | VERIFIED | — | Phần khối lượng khô thực sự cháy | Đốt rơm |
| `straw_burning.gef_ch4` | Gef CH4 | 2,7 | g CH4/kg DM | IPCC 2006 GL Vol.4 Ch.2 | **Table 2.5** — agricultural residues | 2006 | `IPCC_DEFAULT` | mọi | VERIFIED | ±1,0 | — | Đốt rơm |
| `straw_burning.gef_n2o` | Gef N2O | 0,07 | g N2O/kg DM | như trên | Table 2.5 | 2006 | `IPCC_DEFAULT` | mọi | VERIFIED | — | — | Đốt rơm |

Cơ sở **khối lượng khô**: `dry_matter_kg = Σ mass_kg × dry_matter_fraction` (nông dân nhập, thiếu thì
fail closed). Gef ở **g/kg** nên có nhân `10⁻³` để ra **kg khí**, rồi mới nhân GWP. Hệ số đốt
**không** dùng chung với CFOA vùi rơm — hai đường tách hẳn.

---

## 3. Hệ số CHƯA xác minh (engine fail closed)

| Factor key | Trạng thái | Phân loại | Hệ quả thực tế |
|---|---|---|---|
| `fuel.diesel` | PENDING_VERIFICATION, `value: null` | `MISSING` | Vụ có bản ghi nhiên liệu → `MissingEmissionFactorError`, **không** trả 0 |
| `fuel.gasoline` | PENDING_VERIFICATION, `value: null` | `MISSING` | như trên |
| `fuel.lpg` | PENDING_VERIFICATION, `value: null` | `MISSING` | như trên |
| `fuel.electricity_grid` | PENDING_VERIFICATION, `value: null` | `MISSING` | `pump_energy_kwh > 0` → **cảnh báo rõ ràng** trong kết quả, phần này KHÔNG vào tổng |
| `straw_burning.co2_counted` | PENDING_VERIFICATION (cờ boolean) | `PROJECT_ASSUMPTION` | CO2 từ đốt sinh khối coi là chu trình carbon sinh học → engine KHÔNG tính. Cần xác nhận QĐ 4801 có theo thông lệ này không |
| `ch4_rice.default_cultivation_days` | NOT_IMPLEMENTED (102 ngày) | cố ý không dùng | Là trung bình **vùng** cho kiểm kê quốc gia; áp cho một thửa ruộng trong MRV cấp nông hộ là **sai phạm vi**. Thiếu ngày gieo/thu hoạch → `MissingActivityDataError` |

**Điện lưới:** chưa chốt được nguồn chính thức, hiện hành, có năm áp dụng rõ ràng cho hệ số lưới
Việt Nam → giữ **PARTIAL/BLOCKED**, không điền số tạm. Theo dõi ở OI-06.

**Vì sao không dùng hệ số Việt Nam dù có sẵn.** QĐ 2626/QĐ-BTNMT (10/10/2022) công bố hệ số **Tier 2**
đặc trưng quốc gia cho lúa theo **vùng** và **mùa vụ** (CH4, N2O-N, ROA). Engine hiện mô hình hoá theo
**chế độ nước** — đó là cách duy nhất biểu diễn được AWD, vốn là lõi của module khuyến nghị. Hai cách
phân tầng **không tương thích trực tiếp**; ghép bừa sẽ trộn phương pháp luận. Quyết định sprint
2026-09-15: **giữ Tier 1 nhất quán**, ghi nhận QĐ 2626 là khoảng trống **có tài liệu**, không phải
khoảng trống bị bỏ quên. Nguyên tắc: **không** thay bằng nghiên cứu Việt Nam chỉ vì nó là "của Việt Nam"
khi phương pháp luận không tương thích.

---

## 4. Vết đơn vị end-to-end (§14)

Engine **không** tự đổi đơn vị ngầm. `factor_register.py` khẳng định đơn vị YAML **khớp chính xác**
chuỗi mà số học engine được truy vết theo; lệch một ký tự → `unit_mismatches` → chặn kích hoạt.

| Factor | Đơn vị nguồn | Đơn vị import | Đơn vị lưu DB | Engine kỳ vọng | Đơn vị kết quả |
|---|---|---|---|---|---|
| `ch4_rice.efc` | kg CH4 ha⁻¹ ngày⁻¹ | `kgCH4_per_ha_per_day` | giống | `ha_day` → `kgCH4` | kg CH4 |
| `ch4_rice.sfw.*` / `sfp.*` / `cfoa.*` / `sfo_exponent` | không thứ nguyên | `dimensionless` | giống | `dimensionless` | không thứ nguyên |
| `n2o_fertilizer.ef1fr.*` | kg N2O-N (kg N)⁻¹ | `kgN2O-N_per_kgN` | giống | `kgN` → `kgN2O-N` | kg N2O-N |
| `n2o_fertilizer.n2o_n_to_n2o` | tỷ lệ khối lượng | `kgN2O_per_kgN2O-N` | giống | `kgN2O-N` → `kgN2O` | kg N2O |
| `straw_burning.combustion_factor_rice` | không thứ nguyên | `dimensionless` | giống | `kg_dry_matter` → `kg_dry_matter_burnt` | kg DM cháy |
| `straw_burning.gef_ch4` / `gef_n2o` | **g khí (kg DM)⁻¹** | `g_CH4_per_kg_dry_matter` / `g_N2O_…` | giống | `kg_dry_matter_burnt` → `gCH4`/`gN2O` | g khí → **×10⁻³** → kg khí |
| `gwp.ch4` / `gwp.n2o` | kg CO2e (kg khí)⁻¹ | `kgCO2e_per_kgCH4` / `…kgN2O` | giống | `kgCH4`/`kgN2O` → `kgCO2e` | **kg CO2e** |

Điểm đổi đơn vị duy nhất trong toàn engine là **g → kg ở đốt rơm** (`×10⁻³`, Eq 2.27), và nó nằm
ngay cạnh công thức, không ẩn trong hằng số. Cường độ phát thải = `total_co2e_kg / yield_kg`
→ **kg CO2e/kg thóc**; không có sản lượng thì `co2e_per_kg = null`, không bịa mẫu số.

**Độ chính xác số học.** Giá trị đọc từ YAML là `float`, ghi vào cột Postgres `numeric` nên giữ
nguyên độ chính xác đã khai báo — không có bước làm tròn nào trong đường ghi. Bước `--verify` so
sánh DB với YAML bằng `Decimal` lượng tử hoá ở `1e-12`, đủ chặt để bắt sai lệch thật mà không báo
động vì biểu diễn nhị phân. Làm tròn **chỉ ở tầng hiển thị**. 44/28 giữ dạng thương đầy đủ
(1,5714285714285714), không làm tròn thành 1,57.

---

## 5. Kiểm chứng bằng tay (gate bắt buộc)

Fixture: **1 ha · 100 ngày · ngập liên tục · trước vụ không ngập <180 ngày · không chất hữu cơ ·
100 kg urê @ 46 % N · 6 000 kg thóc.**

| Bước | Phép tính | Kết quả |
|---|---|---|
| CH4 | 1,22 × 1,00 × 1,00 × 1,0 × 100 × 1 | **122,0 kg CH4** |
| CH4 → CO2e | 122,0 × 28 | **3 416,0 kg CO2e** |
| N đầu vào | 100 × 46 % | **46,0 kg N** |
| N2O-N | 46,0 × 0,003 | **0,138 kg** |
| N2O | 0,138 × 44/28 | **0,2168571 kg** |
| N2O → CO2e | 0,2168571 × 265 | **57,4671 kg CO2e** |
| **Tổng** | 3 416,0 + 57,4671 | **3 473,4671 kg CO2e** |
| Cường độ | 3 473,4671 / 6 000 | **0,5789112 kg CO2e/kg thóc** |

Engine khớp trong dung sai đã ghi (`rel=1e-12` cho CH4, `abs=1e-4` cho tổng) —
`backend/tests/test_carbon_real_factors.py::test_hand_calculation_baseline_season`.
Test cũng khẳng định breakdown **đúng 2 dòng**: không có nguồn nào bị cộng thêm âm thầm.

Kịch bản AWD cùng fixture: CH4 1 878,8 + N2O 95,7786 = **1 974,5786 kg CO2e**, giảm
**1 498,8886 kg (43,153 %)**.

---

## 6. Quy tắc kích hoạt (fail closed)

Một bộ hệ số chỉ được `published` khi **đồng thời**: đủ 27 core code · tất cả `VERIFIED` ·
mọi đơn vị khớp spec · `gwp.framework` và `methodology.gwp_basis` **cùng** là `AR5` ·
mỗi hệ số VERIFIED có tham chiếu bảng/phương trình · mọi nguồn có URL https · không code lạ ·
không key trùng · không giá trị âm/không hữu hạn. Thiếu bất kỳ điều kiện nào → giữ `draft`.

Danh sách code bắt buộc **suy ra từ engine**, không phải danh sách chép tay:
`test_engine_consumes_only_registered_factor_codes` sẽ đỏ nếu engine đọc một hệ số chưa đăng ký.
Các fixture hỏng có chủ đích nằm ở `backend/tests/fixtures/factor_sets/` (thiếu GWP, sai đơn vị,
key trùng, nguồn chưa xác minh, nhiên liệu thiếu).

---

## 7. Phiên bản & bất biến

Bộ hiện hành **`0.3.0-ipcc2019-tier1-ar5`** (`review_date` 2026-09-15), đã publish trên hosted dev,
27 hệ số, `--verify` báo *identical to YAML*. Bộ `0.2.0` **không bị ghi đè** (chưa từng import).
Bất kỳ đầu vào khoa học mới nào → **version_code mới**; importer từ chối sửa version đã tồn tại.

---

## 8. Hạn chế khoa học còn lại

Ghi trung thực, **không** giấu chỉ vì phép tính chạy được:

1. **IPCC Tier 1** — dùng default quốc tế, không phải hệ số đặc trưng quốc gia mà quy trình MRV yêu cầu.
2. **Default toàn cầu ở hầu hết hệ số tỷ lệ** — chỉ `EFc` là default **vùng** Southeast Asia; SFw/SFp/CFOA là default toàn cầu.
3. **Chưa hiệu chỉnh địa phương** — không có hệ số đo trên đồng ruộng ĐBSCL; chưa xét đất phèn, giống lúa (SFs/SFr chưa dùng).
4. **Chưa đối chiếu dữ liệu đồng ruộng thực** — chưa cross-check với FarMoRe/RiceMoRe trên cùng lô (OI-03).
5. **Dải bất định rộng** — EFc 0,83–1,81 (≈ ±40 % quanh trung tâm) và GWP CH4 ±40 % cộng dồn; con số tuyệt đối phải đọc kèm dải, không đọc như số đo.
6. **Nhiên liệu & điện lưới chưa có hệ số** — vụ có nhiên liệu fail closed; bơm điện chỉ cảnh báo. Phạm vi phát thải **chưa đầy đủ**.
7. **Hiệu lực thời gian của hệ số lưới điện** — hệ số lưới thay đổi theo năm; khi bổ sung phải ghi năm áp dụng và rà lại theo năm.
8. **CO2 đốt sinh khối không tính** — theo thông lệ IPCC nhưng **chưa xác nhận** với QĐ 4801.
9. **`reference_values` CONTESTED** — 1,04 kg CO2 vs 2,29–3,72 kg CO2e/kg lệch hơn 2 lần do khác phạm vi khí/ranh giới hệ thống (OI-01); **không dùng làm baseline** trong bất kỳ báo cáo nào.
10. **Chưa có rà soát chuyên gia** — xem §9.

**KHÔNG** được gắn nhãn "MRV-compliant", "đã chứng nhận" hay tương đương cho bất kỳ kết quả nào
sinh từ bộ hệ số này.

---

## 9. Trạng thái rà soát chuyên gia

**DOMAIN_EXPERT_REVIEW = PENDING.** Chưa có chuyên gia nông học/carbon độc lập nào rà soát.
Trạng thái này **chặn trần** ở `READY_FOR_DEMO`; `READY_FOR_PILOT` không thể đạt bằng thay đổi code.

Cần chuyên gia rà soát đúng các mục: giả định CH4 lúa (EFc vùng, ngày canh tác) · tính áp dụng cho
Việt Nam/ĐBSCL (gồm quyết định Tier 1 vs QĐ 2626 Tier 2) · giả định AWD (cả hướng CH4 giảm lẫn N2O
tăng) · tham số rơm (DM fraction, ngưỡng 30 ngày, hệ số cháy) · N2O phân bón (EF1FR theo chế độ
nước) · hệ số nhiên liệu/điện khi bổ sung · dải bất định và cách truyền qua kết quả.

Đạt `READY_FOR_PILOT` còn cần: rà soát tính áp dụng Việt Nam, đối chiếu dữ liệu đồng ruộng đại diện,
và rà soát bất định — ngoài rà soát chuyên gia ở trên.

---

## 10. Tài liệu liên quan

`docs/CARBON_METHOD.md` (công thức) · `docs/CARBON_METHOD_SOURCES.md` (audit nguồn theo tầng) ·
`docs/modules/02-carbon-engine.md` · `docs/modules/07-mrv-export.md` ·
`backend/carbon/factor_register.py` · `backend/config/emission_factors.yaml`

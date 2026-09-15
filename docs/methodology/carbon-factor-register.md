# Sổ đăng ký hệ số Carbon

Sổ đăng ký này ghi từng hệ số mà Carbon Engine dùng: giá trị, đơn vị, nguồn, phạm vi áp
dụng, trạng thái xác minh và độ không chắc chắn. Nguồn sự thật là
`backend/config/emission_factors.yaml`. Bảng Supabase `emission_factor_sets` /
`emission_factors` là bản sao có kiểm soát để bản tính liên kết được `factor_set_id`.

!!! warning "Mức sẵn sàng: READY_FOR_DEMO"
    - Mọi hệ số lõi đều **VERIFIED** theo bảng/phương trình IPCC có số hiệu. Engine ra số
      CO₂e và khớp tính tay.
    - **Chưa có chuyên gia lĩnh vực thẩm định** (domain expert review: PENDING).
    - Đây là IPCC **Tier 1** default, không phải hệ số đặc trưng quốc gia.
    - Hệ số nhiên liệu chưa có: vụ có bản ghi nhiên liệu trả `422 missing_emission_factor`.
    - Không phải chứng nhận, số liệu chính thức hay MRV-compliant.
      `mrv_compliant` luôn `false`.

## 1. Bộ hệ số hiện hành

| Thuộc tính | Giá trị |
|---|---|
| `version_code` | `0.3.0-ipcc2019-tier1-ar5` |
| Phương pháp | IPCC 2019 Refinement to the 2006 Guidelines, Vol.4 AFOLU — Tier 1 |
| Khung GWP | IPCC AR5, GWP 100 năm |
| Số hệ số lõi | 27 (tất cả `VERIFIED`) |
| Số nguồn | 5 (xem §5) |
| Hosted dev | `id = 6b14adaa-cbbd-490d-b38d-c38c94ec8461`, `status = published`, `published_at = 2026-09-15 15:52 UTC` |
| Kiểm tra sau import | `import_factor_set.py --verify` → 27/27 khớp YAML |
| Phiên bản trước | `0.2.0-ipcc-tier1` chưa từng được import (GWP còn null) |

## 2. Hệ số lõi

Đơn vị: `kg CH₄/ha/ngày` nghĩa là kg CH₄ trên mỗi ha trong mỗi ngày canh tác; hệ số tỷ lệ
không có đơn vị. Độ không chắc chắn là **khoảng giá trị ghi trong chính bảng IPCC**. Chưa tính
độ không chắc chắn tổng hợp cho một vụ.

### CH₄ từ ruộng lúa — IPCC 2019 Refinement Vol.4 Ch.5 (Eq 5.1–5.3)

| Factor | Code key | Value | Unit | Source | Year | Applicability | Verification | Uncertainty | Used by |
|---|---|---|---|---|---|---|---|---|---|
| EFc — hệ số nền | `ch4_rice.efc` | 1,22 | kg CH₄/ha/ngày | Table 5.11 (Southeast Asia) | 2019 | Ngập liên tục, không ngập <180 ngày trước vụ, không bổ sung hữu cơ | VERIFIED | 0,83 – 1,81 | `RiceMethaneCalculator` |
| SFw ngập liên tục | `ch4_rice.sfw.irrigated_continuous_flooding` | 1,00 | — | Table 5.12 | 2019 | Chế độ nước trong vụ | VERIFIED | 0,73 – 1,27 | `RiceMethaneCalculator` |
| SFw rút nước một lần | `ch4_rice.sfw.irrigated_single_drainage` | 0,71 | — | Table 5.12 | 2019 | Chế độ nước trong vụ | VERIFIED | 0,53 – 0,94 | `RiceMethaneCalculator` |
| SFw rút nước nhiều lần (gồm AWD) | `ch4_rice.sfw.irrigated_multiple_drainage` | 0,55 | — | Table 5.12, chú thích b | 2019 | Chế độ nước trong vụ; kịch bản `awd` | VERIFIED | 0,41 – 0,72 | `RiceMethaneCalculator` |
| SFw nước trời thường xuyên | `ch4_rice.sfw.rainfed_regular` | 0,54 | — | Table 5.12 | 2019 | Chế độ nước trong vụ | VERIFIED | 0,39 – 0,74 | `RiceMethaneCalculator` |
| SFw nước trời dễ hạn | `ch4_rice.sfw.rainfed_drought_prone` | 0,16 | — | Table 5.12 | 2019 | Chế độ nước trong vụ | VERIFIED | 0,11 – 0,24 | `RiceMethaneCalculator` |
| SFw nước sâu | `ch4_rice.sfw.deep_water` | 0,06 | — | Table 5.12 | 2019 | Chế độ nước trong vụ | VERIFIED | 0,03 – 0,12 | `RiceMethaneCalculator` |
| SFw lúa cạn | `ch4_rice.sfw.upland` | 0 | — | Table 5.12 | 2019 | Ruộng không ngập | VERIFIED | — | `RiceMethaneCalculator` |
| SFp không ngập <180 ngày | `ch4_rice.sfp.non_flooded_pre_season_lt_180d` | 1,00 | — | Table 5.13 (disaggregated) | 2019 | Chế độ nước trước vụ | VERIFIED | 0,88 – 1,12 | `RiceMethaneCalculator` |
| SFp không ngập >180 ngày | `ch4_rice.sfp.non_flooded_pre_season_gt_180d` | 0,89 | — | Table 5.13 | 2019 | Chế độ nước trước vụ | VERIFIED | 0,80 – 0,99 | `RiceMethaneCalculator` |
| SFp không ngập >365 ngày | `ch4_rice.sfp.non_flooded_pre_season_gt_365d` | 0,59 | — | Table 5.13 | 2019 | Chế độ nước trước vụ | VERIFIED | 0,41 – 0,84 | `RiceMethaneCalculator` |
| SFp ngập trước vụ >30 ngày | `ch4_rice.sfp.flooded_pre_season_gt_30d` | 2,41 | — | Table 5.13 | 2019 | Chế độ nước trước vụ | VERIFIED | 2,13 – 2,73 | `RiceMethaneCalculator` |
| Số mũ SFo | `ch4_rice.sfo_exponent` | 0,59 | — | Equation 5.3 | 2019 | Mọi vụ có bổ sung hữu cơ | VERIFIED | 0,54 – 0,64 | `RiceMethaneCalculator` |
| CFOA rơm vùi <30 ngày | `ch4_rice.cfoa.straw_incorporated_lt_30d` | 1,00 | — | Table 5.14 | 2019 | Rơm vùi sát vụ | VERIFIED | 0,85 – 1,17 | `RiceMethaneCalculator` |
| CFOA rơm vùi >30 ngày | `ch4_rice.cfoa.straw_incorporated_gt_30d` | 0,19 | — | Table 5.14 | 2019 | Rơm vùi sớm | VERIFIED | 0,11 – 0,28 | `RiceMethaneCalculator` |
| CFOA phân ủ | `ch4_rice.cfoa.compost` | 0,17 | — | Table 5.14 | 2019 | Phân ủ | VERIFIED | 0,09 – 0,29 | `RiceMethaneCalculator` |
| CFOA phân chuồng | `ch4_rice.cfoa.farmyard_manure` | 0,21 | — | Table 5.14 | 2019 | Phân chuồng | VERIFIED | 0,15 – 0,28 | `RiceMethaneCalculator` |
| CFOA phân xanh | `ch4_rice.cfoa.green_manure` | 0,45 | — | Table 5.14 | 2019 | Phân xanh | VERIFIED | 0,36 – 0,57 | `RiceMethaneCalculator` |

### N₂O trực tiếp từ phân đạm — IPCC 2019 Refinement Vol.4 Ch.11 (Eq 11.1)

| Factor | Code key | Value | Unit | Source | Year | Applicability | Verification | Uncertainty | Used by |
|---|---|---|---|---|---|---|---|---|---|
| EF1FR ngập liên tục | `n2o_fertilizer.ef1fr.continuous_flooding` | 0,003 | kg N₂O-N/kg N | Table 11.1 (disaggregated) | 2019 | Lúa ngập liên tục | VERIFIED | 0,000 – 0,010 | `FertilizerN2OCalculator` |
| EF1FR rút nước (gồm AWD) | `n2o_fertilizer.ef1fr.single_and_multiple_drainage` | 0,005 | kg N₂O-N/kg N | Table 11.1, chú thích 7 | 2019 | Rút nước một/nhiều lần; kịch bản `awd` | VERIFIED | 0,000 – 0,016 | `FertilizerN2OCalculator` |
| EF1FR gộp | `n2o_fertilizer.ef1fr.aggregate` | 0,004 | kg N₂O-N/kg N | Table 11.1 (aggregated) | 2019 | Nước trời / nước sâu (kèm cảnh báo) | VERIFIED | 0,000 – 0,029 | `FertilizerN2OCalculator` |
| Quy đổi N₂O-N → N₂O | `n2o_fertilizer.n2o_n_to_n2o` | 44/28 = 1,571429 | kg N₂O/kg N₂O-N | Hằng số khối lượng phân tử, Ch.11 | — | Mọi dòng N₂O | VERIFIED | không áp dụng | `FertilizerN2OCalculator` |

### Đốt rơm ngoài đồng — IPCC 2006 Guidelines Vol.4 Ch.2 (Eq 2.27)

| Factor | Code key | Value | Unit | Source | Year | Applicability | Verification | Uncertainty | Used by |
|---|---|---|---|---|---|---|---|---|---|
| Hệ số cháy (Cf) rơm lúa | `straw_burning.combustion_factor_rice` | 0,80 | kg chất khô cháy/kg chất khô | Table 2.6 | 2006 | Đốt rơm sau thu hoạch | VERIFIED | chưa ghi trong YAML | `StrawBurningCalculator` |
| Gef CH₄ | `straw_burning.gef_ch4` | 2,7 | g CH₄/kg chất khô cháy | Table 2.5 | 2006 | Phụ phẩm nông nghiệp | VERIFIED | ± 1,0 | `StrawBurningCalculator` |
| Gef N₂O | `straw_burning.gef_n2o` | 0,07 | g N₂O/kg chất khô cháy | Table 2.5 | 2006 | Phụ phẩm nông nghiệp | VERIFIED | chưa ghi trong YAML | `StrawBurningCalculator` |

### GWP — IPCC AR5 WG1 Ch.8

| Factor | Code key | Value | Unit | Source | Year | Applicability | Verification | Uncertainty | Used by |
|---|---|---|---|---|---|---|---|---|---|
| GWP-100 CH₄ | `gwp.ch4` | 28 | kg CO₂e/kg CH₄ | Table 8.A.1 (không phải CH₄ hoá thạch; không kèm climate-carbon feedback) | 2013 | CH₄ sinh học: ruộng lúa, đốt rơm | VERIFIED | ±40% (khoảng 90%, chú thích Table 8.A.1) | mọi dòng CH₄ |
| GWP-100 N₂O | `gwp.n2o` | 265 | kg CO₂e/kg N₂O | Table 8.A.1 | 2013 | Mọi dòng N₂O | VERIFIED | ±30% (khoảng 90%) | mọi dòng N₂O |

Căn cứ chọn AR5: UNFCCC quyết định 18/CMA.1 (phụ lục, đoạn 37) và 5/CMA.3 (đoạn 25) — báo
cáo minh bạch theo Thoả thuận Paris dùng GWP-100 của AR5. QĐ 2626/QĐ-BTNMT không nêu khung
GWP. QĐ 4801 chưa lấy được toàn văn. Validator từ chối bộ hệ số trộn khung khác (AR4/AR6).

## 3. Hệ số không nằm trong bộ

| Code key | Trạng thái | Hệ quả |
|---|---|---|
| `fuel.diesel`, `fuel.gasoline`, `fuel.lpg` | Tuỳ chọn, `null`, chưa xác minh | Vụ có `fuel_usages` → `422 missing_emission_factor`. QĐ 2626 cho diesel theo TJ (74.100 kg CO₂, 3 kg CH₄, 0,6 kg N₂O/TJ). Đổi sang lít cần khối lượng riêng và nhiệt trị từ nguồn chính thức, hiện chưa có |
| `fuel.electricity_grid` | Không dùng | Điện bơm chỉ sinh cảnh báo, không vào tổng |
| `straw_burning.co2_counted` | Không dùng | CO₂ từ đốt sinh khối không được tính |
| `ch4_rice.default_cultivation_days` | Không dùng | Thiếu số ngày canh tác thì báo lỗi, không lấy mặc định |

## 4. Khoảng trống: hệ số đặc trưng quốc gia (QĐ 2626)

QĐ 2626/QĐ-BTNMT (10/10/2022) có hệ số Tier 2 (đánh dấu *) cho lúa theo **vùng và mùa vụ**.
Engine tính theo **chế độ nước** (Tier 1, IPCC), nên các hệ số này **chưa được dùng**.
Tính theo QĐ 2626 cần một mô hình khác (vùng, mùa vụ), không thể thay số trực tiếp.

| Nhóm | Miền Bắc | Miền Trung | Miền Nam |
|---|---|---|---|
| CH₄ (kg/ha/ngày) | 1,61 / 3,43 | 1,92 / 1,91 | đông xuân 1,95 · hè thu 1,83 · thu đông 2,20 |
| N₂O-N (%) | 0,34 / 0,25 | 0,24 / 0,17 | 0,15 / 0,20 / 0,17 |

Các dòng ROA (t/ha, dòng 3.39–3.46, ví dụ miền Nam 0,43 / 0,43 / 0,45) cũng chưa dùng.
Hệ số SFp, SFw và CFOA Tier 1 trong QĐ 2626 trùng với giá trị IPCC ở trên.

## 5. Nguồn

| # | Tài liệu | URL |
|---|---|---|
| 1 | 2019 Refinement to the 2006 IPCC Guidelines, Vol.4, Ch.5 Cropland | https://www.ipcc-nggip.iges.or.jp/public/2019rf/pdf/4_Volume4/19R_V4_Ch05_Cropland.pdf |
| 2 | 2019 Refinement, Vol.4, Ch.11 N₂O Emissions from Managed Soils | https://www.ipcc-nggip.iges.or.jp/public/2019rf/pdf/4_Volume4/19R_V4_Ch11_Soils_N2O_CO2.pdf |
| 3 | 2006 IPCC Guidelines, Vol.4, Ch.2 Generic Methodologies | https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/4_Volume4/V4_02_Ch2_Generic.pdf |
| 4 | IPCC AR5 WG1 (2013), Ch.8, Table 8.A.1 | https://www.ipcc.ch/site/assets/uploads/2018/02/WG1AR5_Chapter08_FINAL.pdf |
| 5 | UNFCCC decision 18/CMA.1 (annex, para 37); decision 5/CMA.3 (para 25) | https://unfccc.int/sites/default/files/resource/CMA2018_03a02E.pdf |

## 6. Import, phiên bản và bất biến

```bash
cd backend
python scripts/import_factor_set.py                    # dry run: chỉ kiểm tra, không chạm DB
python scripts/import_factor_set.py --apply --publish  # một transaction: set draft → factors → published
python scripts/import_factor_set.py --verify           # so từng dòng DB với YAML
```

- **Fail closed:** thiếu hệ số lõi, sai đơn vị, trùng khoá, mã lạ, thiếu nguồn hoặc số hiệu
  bảng, trạng thái khác `VERIFIED`, hoặc khung GWP khác AR5 → từ chối, không ghi dòng nào.
  Fixture kiểm thử: `backend/tests/fixtures/factor_sets/`.
- **Bất biến:** `version_code` đã tồn tại thì `--apply` từ chối. Muốn đổi giá trị thì tăng
  phiên bản trong YAML và import bộ mới. Bản tính cũ vẫn trỏ về bộ cũ.
- **Không INSERT tay:** mọi dòng trên hosted dev đi qua importer.

## 7. Kiểm chứng

| Kiểm chứng | Kết quả |
|---|---|
| Tính tay: 1 ha, 100 ngày, ngập liên tục, urea 100 kg (46% N), 6.000 kg thóc | CH₄ 122,0 kg → 3.416,0 · N₂O 0,2168571 kg → 57,4671 · **tổng 3.473,4671 kg CO₂e** · 0,5789112 kg CO₂e/kg. Kịch bản AWD 1.974,5786 (giảm 43,15%; CH₄ giảm, N₂O tăng) |
| Tính tay trên hosted: thêm 2.000 kg rơm (0,85 chất khô) bị đốt | Đốt rơm CH₄ 102,816 + N₂O 25,228 · **tổng 3.601,5111** · AWD 2.102,6226. API và gói MRV khớp tới 10⁻³ |
| `backend/tests/test_carbon_real_factors.py` | Tính tay, AWD, rơm vùi (SFo = 5,25^0,59 ≈ 2,66008), rơm đốt, nhiên liệu → 422, không sản lượng → `co2e_per_kg = null`, thiếu dữ liệu → lỗi |
| `backend/scripts/hosted_carbon_factor_smoke.py` | 43/43 trên hosted dev |

## 8. Mức sẵn sàng

| Mức | Điều kiện | Hiện tại |
|---|---|---|
| `STILL_BLOCKED` | Thiếu hoặc chưa xác minh bất kỳ hệ số lõi nào | — |
| `READY_FOR_DEMO` | Mọi hệ số lõi VERIFIED, khung GWP đã chốt | **✔** |
| `READY_FOR_PILOT` | Thêm: chuyên gia lĩnh vực thẩm định xong (`domain_expert_review: COMPLETE`) | chưa |

`GET /health` trả `carbon_scientific_readiness` theo đúng các mức trên.
`carbon_production_ready` chỉ `true` ở mức `READY_FOR_PILOT`. `mrv_compliant` luôn `false`.

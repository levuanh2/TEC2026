# CARBON_METHOD_SOURCES — Nguồn phương pháp luận

Phiên bản: 0.2 · Ngày tra cứu: 2026-09-08
Đi kèm: [`CARBON_METHOD.md`](CARBON_METHOD.md) · `backend/config/emission_factors.yaml`

Mọi hệ số/công thức dùng trong Carbon Engine phải truy về được một dòng trong tài liệu này.
Không có dòng ở đây → không được đưa vào config với `status: VERIFIED`.

---

## Tier 1 — Nguồn chính thức Việt Nam

| Source | Exact document | Section/page/table | What it supports | Status |
|---|---|---|---|---|
| Bộ Nông nghiệp và Môi trường | **Quyết định 4801/QĐ-BNNMT ngày 14/11/2025** — Quy trình thí điểm MRV trong canh tác lúa chất lượng cao, phát thải thấp vùng ĐBSCL | Toàn văn + phụ lục | Quy trình 6 bước; **bộ hệ số phát thải đặc trưng quốc gia**; khung GWP | ❌ **NOT_OBTAINED** — không tìm được toàn văn công khai. Báo chí chỉ mô tả 6 bước, không đăng phụ lục kỹ thuật |
| Thủ tướng Chính phủ | Quyết định 1490/QĐ-TTg ngày 27/11/2023 — Đề án 1 triệu ha lúa CLC phát thải thấp ĐBSCL | — | Bối cảnh chính sách, phạm vi vùng | ✅ Đã xác nhận tồn tại (dùng làm bối cảnh, không phải nguồn hệ số) |
| Bộ Tài nguyên và Môi trường | Quyết định 2626/QĐ-BTNMT ngày 10/10/2022 — Danh mục hệ số phát thải phục vụ kiểm kê KNK | Phụ lục lĩnh vực Nông nghiệp; Phụ lục lĩnh vực Năng lượng | Hệ số phát thải quốc gia; hệ số nhiên liệu diesel; khung GWP | ❌ **NOT_OBTAINED** — trang toàn văn trả HTTP 403 |

### Ghi chú Tier 1 (quan trọng)

1. **Chưa lấy được toàn văn QĐ 4801 và phụ lục.** Vì vậy **không hệ số nào trong dự án được
   phép gắn nhãn "MRV-compliant"** ở thời điểm này.
2. Báo chí chính thống mô tả 6 bước là *"chuẩn bị, đăng ký, thiết lập đường cơ sở, **giám sát**,
   báo cáo và **xác minh**"* — khác cách gọi trong `docs/mrv-mapping.md` hiện tại
   (*"Đo đạc"*, *"Thẩm định"*). **Cần đối chiếu tên bước với toàn văn quyết định.**
3. Nguồn cho biết hệ số phát thải trong quy trình MRV là *"hệ số phát thải đặc trưng quốc gia
   được xác định thông qua quá trình đo đạc trực tiếp trên đồng ruộng"* → tức là hệ số
   country-specific (IPCC Tier 2), **không phải** default IPCC Tier 1 mà dự án đang dùng tạm.

### Cách lấy Tier 1

- Văn phòng Quan hệ đối tác & Điều phối dự án **IRRI Việt Nam**
- **Cục Trồng trọt và Bảo vệ thực vật** (đơn vị chủ trì MRV)
- **Sở Nông nghiệp và Môi trường** Cần Thơ / An Giang / Đồng Tháp
- Cổng văn bản pháp luật Bộ Nông nghiệp và Môi trường

---

## Tier 2 — IPCC (đã lấy được toàn văn, đã trích dẫn chính xác)

### CH4 từ canh tác lúa

| Source | Exact document | Section/table | What it supports | Status |
|---|---|---|---|---|
| IPCC | **2019 Refinement to the 2006 IPCC Guidelines**, Vol.4 AFOLU, Ch.5 Cropland | §5.5, **Equation 5.1** | `CH4 = Σ (EFi × t × A × 10⁻⁶)` [Gg CH4] | ✅ **VERIFIED** |
| IPCC | như trên | **Equation 5.2 (UPDATED)** | `EFi = EFc × SFw × SFp × SFo` (Tier 1) | ✅ **VERIFIED** |
| IPCC | như trên | **Equation 5.2a (NEW)** | `EFi = EFc × SFw × SFp × SFo × SFs × SFr` (Tier 2) | ✅ VERIFIED (chưa dùng — thiếu SFs/SFr cho VN) |
| IPCC | như trên | **Table 5.11 (UPDATED)** | EFc Southeast Asia = **1,22** kg CH4/ha/ngày (khoảng 0,83–1,81); World 1,19 | ✅ **VERIFIED** |
| IPCC | như trên | **Table 5.11A (NEW)** | Cultivation period mặc định SE Asia = **102** ngày (78–150) | ✅ VERIFIED (chỉ dùng khi thiếu ngày gieo/thu thực tế) |
| IPCC | như trên | **Table 5.12 (UPDATED)**, disaggregated case | SFw: continuously flooded 1,00 · single drainage 0,71 · **multiple drainage 0,55** · regular rainfed 0,54 · drought prone 0,16 · deep water 0,06 · upland 0 | ✅ **VERIFIED** |
| IPCC | như trên | **Table 5.13 (UPDATED)**, disaggregated case | SFp: non-flooded pre-season <180 ngày 1,00 · >180 ngày 0,89 · flooded pre-season >30 ngày 2,41 · non-flooded >365 ngày 0,59 | ✅ **VERIFIED** (cột aggregated không dùng — xem ghi chú) |
| IPCC | như trên | **Equation 5.3** | `SFo = (1 + Σ ROAi × CFOAi)^0,59`; ROA tấn/ha, straw tính **khối lượng khô** | ✅ **VERIFIED** |
| IPCC | như trên | **Table 5.14 (UPDATED)** | CFOA: rơm vùi **<30 ngày** trước canh tác 1,00 · rơm vùi **>30 ngày** 0,19 · compost 0,17 · farmyard manure 0,21 · green manure 0,45 | ✅ **VERIFIED** |

**Trích nguyên văn quyết định vấn đề double counting** (chú thích a, Table 5.14):

> *"Straw application means that straws are incorporated into the soil. It does not include cases
> where straws are just placed on soil surface, and straws that were burnt on the field."*

**Trích nguyên văn xác định AWD thuộc nhóm nào** (chú thích b, Table 5.12):

> *"Multiple drainage periods: Fields have more than one drainage event and period of time without
> flooded conditions during the cropping season, in addition to an end of season drainage,
> **including alternate wetting and drying (AWD)**."*

**Ghi chú về cột "Aggregated case" của Table 5.13:** bố cục bảng bị lệch khi trích xuất từ PDF
nên **không xác định chắc chắn** giá trị aggregated 1,22 thuộc dòng nào. Dự án chỉ dùng cột
disaggregated (rõ ràng, không mơ hồ); cột aggregated đánh **NOT_IMPLEMENTED**.

### N2O từ đầu vào đạm

| Source | Exact document | Section/table | What it supports | Status |
|---|---|---|---|---|
| IPCC | 2019 Refinement, Vol.4, Ch.11 N2O from Managed Soils | **Equation 11.1** | `N2O-N = F_FR × EF1FR` cho ruộng lúa ngập | ✅ **VERIFIED** |
| IPCC | như trên | **Table 11.1 (UPDATED)** | **EF1FR** aggregate = **0,004**; disaggregated: **continuous flooding 0,003**; **single and multiple drainage 0,005** [kg N2O-N/kg N] | ✅ **VERIFIED** |
| IPCC | như trên | chú thích 7, Table 11.1 | *"Single and multiple drainage also include alternate wetting and drying"* | ✅ **VERIFIED** |
| Hoá học cơ bản | Tỷ lệ khối lượng phân tử | 44/28 | Quy đổi N2O-N → N2O | ✅ **VERIFIED** (hằng số hoá học, không phải hệ số phát thải) |

> **Hệ quả quan trọng:** AWD **giảm** CH4 (SFw 1,00 → 0,55) nhưng **tăng** N2O
> (EF1FR 0,003 → 0,005). Engine bắt buộc phải áp kịch bản nước vào **cả hai** nguồn.

### Đốt rơm rạ ngoài đồng

| Source | Exact document | Section/table | What it supports | Status |
|---|---|---|---|---|
| IPCC | **2006 IPCC Guidelines**, Vol.4, Ch.2 Generic Methodologies | **Equation 2.27** | `Lfire = A × MB × Cf × Gef × 10⁻³` [tấn khí] | ✅ **VERIFIED** |
| IPCC | như trên | **Table 2.5** (Andreae & Merlet 2001) | Agricultural residues: **CH4 = 2,7** g/kg DM (±1,0); **N2O = 0,07** g/kg DM | ✅ **VERIFIED** |
| IPCC | như trên | **Table 2.6** | Combustion factor Cf, **rice residues = 0,80** (post-harvest field burning) | ✅ **VERIFIED** |

### Nhiên liệu

| Source | Exact document | Section/table | What it supports | Status |
|---|---|---|---|---|
| IPCC | 2006 IPCC Guidelines, Vol.2 Energy, Ch.3 Mobile Combustion | Table 3.2.1 / Ch.1 Table 1.2 (NCV) | Hệ số CO2 diesel, nhiệt trị, khối lượng riêng | ❌ **NOT_OBTAINED** — chưa tra cứu trong phiên này |
| BTNMT | QĐ 2626/QĐ-BTNMT, Phụ lục Năng lượng | — | Hệ số diesel áp dụng tại VN | ❌ **NOT_OBTAINED** (HTTP 403) |

Nhiên liệu là nguồn nhỏ so với CH4 ruộng ngập. Để `null` cho tới khi lấy được nguồn.

### GWP

| Source | Exact document | Section/table | What it supports | Status |
|---|---|---|---|---|
| — | Khung GWP mà QĐ 4801 quy định | — | Quy đổi CH4, N2O → CO2e | ❌ **PENDING_VERIFICATION** |

**Vì sao không tự chọn:** chênh lệch giữa các khung là lớn và ảnh hưởng trực tiếp con số cuối:

| Khung | GWP-100 CH4 | GWP-100 N2O |
|---|---|---|
| IPCC AR4 (2007) | 25 | 298 |
| IPCC AR5 (2013) | 28 | 265 |
| IPCC AR6 (2021) | 27,9 (phi hoá thạch) / 29,8 (hoá thạch) | 273 |

Chọn AR4 thay vì AR6 làm lệch CH4 tới **~19%**. Đây đúng là loại câu hỏi hội đồng sẽ vặn.
**Phải lấy đúng khung mà QĐ 4801 / QĐ 2626 quy định**, không chọn theo cảm tính.

Ba con số trên **chưa được xác minh trong phiên này** — liệt kê để biết cần tra cái gì, chưa
được đưa vào config.

---

## Tier 3 — Chưa dùng

Chưa dùng nguồn học thuật nào. Nếu về sau cần (ví dụ SFs cho đất phèn ĐBSCL, SFr cho giống
OM/ĐS), phải thêm dòng vào bảng này trước khi đưa vào config.

---

## Bảng trạng thái tổng hợp

```text
VERIFIED             : CH4 rice (Eq 5.1, 5.2, 5.3 + Tables 5.11/5.11A/5.12/5.13/5.14)
                       N2O fertilizer (Eq 11.1 + Table 11.1)
                       Straw burning (Eq 2.27 + Tables 2.5/2.6)
PENDING_VERIFICATION : GWP CH4, GWP N2O
                       Hệ số nhiên liệu diesel
NOT_OBTAINED         : QĐ 4801/QĐ-BNNMT toàn văn + phụ lục  ← Tier 1, chặn nhãn "MRV-compliant"
                       QĐ 2626/QĐ-BTNMT toàn văn
NOT_IMPLEMENTED      : SFs (đất), SFr (giống) — Tier 2 Eq 5.2a
                       Cột aggregated của Table 5.13
                       Phát thải upstream (giống, thuốc BVTV, sản xuất phân)
                       CH4 ngoài vụ (pre-season, sau thu hoạch)
```

**Engine hiện KHÔNG ra được con số CO2e** vì GWP còn `null` — dù toàn bộ hệ số CH4/N2O đã
VERIFIED. Đây là hành vi đúng theo thiết kế.

---

## Sources

- [Quy trình MRV 6 bước — Bộ NNMT ban hành (Dân Việt)](https://danviet.vn/mot-quy-trinh-gom-6-buoc-vua-duoc-bo-nnmt-ban-hanh-do-dem-duoc-luong-giam-phat-thai-trong-san-xuat-lua-d1380210.html)
- [Áp dụng quy trình MRV trong canh tác lúa (Cục Thông tin, Thống kê)](https://vista.gov.vn/vi/news/khoa-hoc-ky-thuat-va-cong-nghe/ap-dung-quy-trinh-mrv-trong-canh-tac-lua-buoc-chuyen-chien-luoc-huong-toi-nong-nghiep-phat-thai-thap-va-thi-truong-carbon-12558.html)
- [Quy trình MRV đo đạc, báo cáo, thẩm định (VnEconomy)](https://vneconomy.vn/quy-trinh-mrv-do-dac-bao-cao-tham-dinh-danh-gia-luong-giam-phat-thai-trong-canh-tac-lua.htm)
- [Quy trình MRV đã hoàn thiện (Cục Trồng trọt và BVTV)](https://www.ppd.gov.vn/tin-moi-nhat-289/quy-trinh-mrv-da-hoan-thien-san-sang-danh-gia-luong-giam-phat-thai.html)
- [Quyết định 1490/QĐ-TTg — Đề án 1 triệu ha](https://caselaw.vn/van-ban-phap-luat/509082-quyet-dinh-so-1490-qd-ttg-ngay-27-11-2023-cua-thu-tuong-chinh-phu-phe-duyet-de-an-phat-trien-ben-vung-mot-trieu-hec-ta-chuyen-canh-lua-chat-luong-cao-va-phat-thai-thap-gan-voi-tang-truong-xanh-vung-dong-bang-song-cuu-long-den-nam-2030)
- [Quyết định 2626/QĐ-BTNMT 2022 — danh mục hệ số phát thải](https://thuvienphapluat.vn/van-ban/Tai-nguyen-Moi-truong/Quyet-dinh-2626-QD-BTNMT-2022-cong-bo-he-so-phat-thai-phuc-vu-kiem-ke-khi-nha-kinh-532253.aspx) *(403 khi truy cập)*
- [IPCC 2019 Refinement, Vol.4 Ch.5 Cropland (PDF)](https://www.ipcc-nggip.iges.or.jp/public/2019rf/pdf/4_Volume4/19R_V4_Ch05_Cropland.pdf)
- [IPCC 2019 Refinement, Vol.4 Ch.11 N2O from Managed Soils (PDF)](https://www.ipcc-nggip.iges.or.jp/public/2019rf/pdf/4_Volume4/19R_V4_Ch11_Soils_N2O_CO2.pdf)
- [IPCC 2006 Guidelines, Vol.4 Ch.2 Generic Methodologies (PDF)](https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/4_Volume4/V4_02_Ch2_Generic.pdf)

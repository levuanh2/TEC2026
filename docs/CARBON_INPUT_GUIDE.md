# Cần nhập dữ liệu gì để tính được Carbon?

> Dành cho người dùng Farmer Web / Flutter và cho người kiểm thử.
> Phương pháp luận và hệ số: `docs/CARBON_METHOD.md`, `docs/methodology/carbon-factor-register.md`.
> Cập nhật: 2026-09-16

Carbon Engine **không bao giờ đoán** một giá trị còn thiếu. Thiếu bất kỳ đầu vào bắt buộc nào thì
kết quả **không** được tính ra — thay vì hiện một con số sai. Trang này liệt kê đúng những gì cần nhập.

---

## 1. Bộ dữ liệu tối thiểu để tính được Carbon

| # | Dữ liệu | Nhập ở đâu | Đơn vị | Bắt buộc | Thiếu thì sao |
|---|---|---|---|---|---|
| 1 | Diện tích thửa | Thửa ruộng (`plots.area_ha`) | ha | ✅ | Không tính được CH₄ |
| 2 | **Chế độ nước trong vụ** | Vụ → tab Carbon → **Thông tin phương pháp tính** | chọn 1 trong 7 | ✅ | `methodology_gap` |
| 3 | **Chế độ nước trước vụ** | Vụ → tab Carbon → **Thông tin phương pháp tính** | chọn 1 trong 4 | ✅ | `methodology_gap` |
| 4 | Số ngày canh tác | Cùng chỗ trên, **hoặc** suy từ ngày gieo sạ + ngày thu hoạch | ngày | ✅ (một trong hai) | `missing_activity_data` |
| 5 | Lượng phân bón | Hoạt động → Bón phân → *Khối lượng* | kg | ✅ nếu có bón | — |
| 6 | **Hàm lượng đạm (N)** | Hoạt động → Bón phân → *Hàm lượng đạm* | % | ✅ nếu có bón | `missing_activity_data` |
| 7 | Sản lượng thu hoạch | Hoạt động → Thu hoạch → *Sản lượng* | kg | ⬜ | Vẫn có tổng CO₂e, **không** có cường độ CO₂e/kg |
| 8 | Rơm rạ — cách xử lý | Hoạt động → Rơm rạ → *Cách xử lý* | chọn | ⬜ | Bỏ qua phần rơm |
| 9 | Rơm rạ — khối lượng | Hoạt động → Rơm rạ → *Khối lượng* | kg | ✅ nếu khai rơm | `methodology_gap` |
| 10 | Rơm rạ — tỷ lệ chất khô | Rơm rạ → **Thông tin bổ sung** | 0–1 | ✅ nếu khai rơm | `methodology_gap` |
| 11 | Rơm rạ — trả lại ruộng? | Rơm rạ → **Thông tin bổ sung** | có/không | ✅ nếu vùi | `methodology_gap` |
| 12 | Rơm rạ — số ngày trước làm đất | Rơm rạ → **Thông tin bổ sung** | ngày | ⬜ | Dùng nhóm CFOA mặc định theo phương pháp |
| 13 | Bộ hệ số phát thải đã publish | Quản trị (`import_factor_set.py`) | — | ✅ | `missing_emission_factor` |

**Mục 2 và 3 là hay bị quên nhất.** Chúng nằm ở **vụ canh tác**, không phải ở một hoạt động, vì
mỗi vụ chỉ có một chế độ nước.

---

## 2. Ví dụ từng bước (vụ tính được)

1. Mở vụ canh tác → tab **Carbon**.
2. Ở **Thông tin phương pháp tính**, bấm *Khai báo thông tin phương pháp tính*:
   - Chế độ nước trong vụ: **Tưới — ngập liên tục**
   - Chế độ nước trước vụ: **Không ngập, dưới 180 ngày trước vụ**
   - Số ngày canh tác: **100** (bỏ trống nếu đã có ngày gieo sạ + thu hoạch)
   - Bấm **Lưu**.
3. Sang tab **Hoạt động**, thêm:
   - **Tưới**: hình thức *Ngập liên tục*, lượng nước 4 000 m³
   - **Bón phân**: Urê, 100 kg, **hàm lượng đạm 46 %**
   - **Thu hoạch**: 6 000 kg
4. Quay lại tab **Carbon** → bấm **Tính lại theo kịch bản**.
5. Kết quả mong đợi: **3 473,47 kg CO₂e**, cường độ **0,5789 kg CO₂e/kg thóc**, breakdown 2 dòng
   (CH₄ ruộng lúa 3 416,0 · N₂O phân bón 57,47).

Đây đúng là kịch bản mà `backend/scripts/hosted_carbon_input_ux_smoke.py` chạy tự động trên
hosted dev — 44/44 kiểm tra pass.

---

## 3. Chi phí (Resource Metrics) **không** liên quan tới Carbon

Đây là hai chỉ số khác hẳn nhau, hay bị nhầm:

| | Carbon | Resource Metrics |
|---|---|---|
| Trả lời câu hỏi | Phát thải bao nhiêu CO₂e? | Tốn bao nhiêu tiền/nước/phân cho mỗi kg thóc? |
| Đầu vào | Chế độ nước, phân đạm, rơm, diện tích, ngày | Chi phí ghi nhận, nước, phân, sản lượng |
| Tiền có tham gia không | **KHÔNG** | Có |
| Kết quả | kg CO₂e · kg CO₂e/kg | VND/kg · m³/kg · kg/kg |

**Tiền tuyệt đối không đi vào bất kỳ công thức Carbon nào.** Không có hệ số phát thải nào tính
theo VND, và breakdown Carbon không có dòng chi phí nào.

Nhập chi phí ở đâu: ô **Chi phí** trong từng biểu mẫu hoạt động (bón phân, tưới, thu hoạch,
thuốc BVTV, rơm rạ) và ô *Chi phí* của Gieo sạ.

> **Lưu ý quan trọng về `cost_per_kg`:** chỉ hiện khi **mọi** hoạt động của vụ đều đã có chi phí.
> Chỉ cần một hoạt động bỏ trống chi phí thì `cost_per_kg` trả về `null` — cố ý như vậy, vì cộng
> một phần chi phí rồi chia cho toàn bộ sản lượng sẽ cho ra con số **thấp hơn thực tế**. Cùng quy
> tắc với nước và phân bón.

---

## 3b. Bảng điều khiển hiển thị hai chỉ số này ra sao

Trang chủ Farmer tách hẳn hai nhóm, vì chúng độc lập với nhau:

| Nhóm | Mục nhắc | Nút | Dẫn tới |
|---|---|---|---|
| **Hiệu suất tài nguyên** | "Thiếu chi phí vật tư" | **Bổ sung chi phí** | Nhật ký của vụ — mở từng hoạt động để điền ô Chi phí |
| **Phát thải carbon** | Tên đúng thứ còn thiếu, ví dụ "Thiếu chế độ nước trước vụ" | **Bổ sung dữ liệu Carbon** | Tab Carbon của vụ → panel *Thông tin phương pháp tính* |

Danh sách thiếu của Carbon **do máy chủ trả về** (`GET /v1/crop-seasons/{id}/carbon/readiness`),
suy ra từ đúng dữ liệu mà engine dùng. Giao diện không tự suy luận quy tắc khoa học nào; nó chỉ
hiển thị những gì máy chủ báo và bấm đúng chỗ theo trường `flow` mà máy chủ trả về.

Mục nhắc chi phí ghi rõ **"Chi phí không ảnh hưởng tới kết quả Carbon"**, để không ai đọc
"thiếu chi phí" như nguyên nhân Carbon chưa tính được.

Nếu thiếu sản lượng thu hoạch, đó **không** phải lỗi chặn: vẫn có tổng CO₂e, chỉ chưa có
cường độ trên mỗi kg — giao diện nói đúng như vậy thay vì báo là chưa tính được.

---

## 4. Bảng tổng hợp: dữ liệu nào dùng cho cái gì

| Dữ liệu | Nhập ở đâu | Dùng cho Carbon? | Dùng cho Resource Metrics? |
|---|---|---|---|
| Diện tích thửa | Thửa ruộng | ✅ CH₄ (Eq 5.1) | — |
| Chế độ nước trong vụ | Vụ → Thông tin phương pháp tính | ✅ SFw | — |
| Chế độ nước trước vụ | Vụ → Thông tin phương pháp tính | ✅ SFp | — |
| Số ngày canh tác | Vụ → Thông tin phương pháp tính | ✅ Eq 5.1 | — |
| Lượng phân bón (kg) | Hoạt động → Bón phân | ✅ qua %N | ✅ kg phân/kg thóc |
| Hàm lượng đạm (%) | Hoạt động → Bón phân | ✅ N₂O (Eq 11.1) | — |
| Lượng nước (m³) | Hoạt động → Tưới | — ¹ | ✅ m³/kg |
| Hình thức tưới | Hoạt động → Tưới | ✅ ² | — |
| Sản lượng (kg) | Hoạt động → Thu hoạch | ✅ mẫu số cường độ | ✅ mẫu số |
| Rơm: khối lượng, chất khô, trả lại ruộng | Hoạt động → Rơm rạ | ✅ SFo hoặc đốt | — |
| **Chi phí (VND)** | Ô *Chi phí* mỗi hoạt động | ❌ **không bao giờ** | ✅ VND/kg |
| Điện bơm (kWh) | Hoạt động → Tưới | ⚠️ xem §5 | — |
| Nhiên liệu (lít) | *chưa có trên Farmer Web* | ⚠️ xem §5 | — |

¹ Lượng nước không phải đầu vào phát thải trong Tier 1; chế độ nước mới là.
² Hình thức tưới chỉ dùng để **suy ra** chế độ nước IPCC khi vụ chưa khai trực tiếp, và chỉ khi
không mơ hồ. Khai thẳng ở *Thông tin phương pháp tính* luôn được ưu tiên.

---

## 5. Nhiên liệu và điện — trạng thái thật

Phải nói rõ để không ai hiểu nhầm tổng CO₂e là đã đầy đủ:

- **Nhiên liệu (dầu/xăng/LPG):** hệ số phát thải **chưa xác minh** (OI-06). Nếu một vụ có bản ghi
  nhiên liệu, engine **báo lỗi `missing_emission_factor`** và **không** tính ra kết quả — chứ không
  âm thầm coi phần nhiên liệu bằng 0. Vì vậy Farmer Web **cố ý chưa mở** biểu mẫu nhiên liệu:
  mở ra sẽ khiến người dùng tự khoá vụ của mình.
- **Điện bơm (`pump_energy_kwh`):** nhập được ở biểu mẫu Tưới, nhưng hệ số lưới điện Việt Nam
  chưa chốt. Engine trả về **cảnh báo rõ ràng** và **không** cộng phần này vào tổng.

→ Tổng CO₂e hiện tại là **phạm vi CH₄ ruộng lúa + N₂O phân bón + đốt rơm**, chưa gồm năng lượng.

---

## 6. Lỗi thường gặp và cách xử lý

| Thông báo | Nghĩa là | Làm gì |
|---|---|---|
| `methodology_gap` — thiếu `pre_season_water_regime` | Chưa khai chế độ nước trước vụ | Vụ → tab Carbon → Thông tin phương pháp tính |
| `methodology_gap` — bản ghi tưới mơ hồ | Hình thức tưới không ánh xạ chắc chắn sang phân loại IPCC | Khai thẳng *Chế độ nước trong vụ* |
| `missing_activity_data` — thiếu hàm lượng N | Có bón phân nhưng bỏ trống %N | Sửa hoạt động bón phân, điền *Hàm lượng đạm* |
| `missing_activity_data` — thiếu số ngày canh tác | Không có ngày gieo sạ/thu hoạch và cũng không khai số ngày | Điền *Số ngày canh tác* |
| `missing_emission_factor` | Hệ số chưa xác minh (thường là nhiên liệu) hoặc chưa import bộ hệ số | Xoá bản ghi nhiên liệu, hoặc liên hệ quản trị |
| 404 khi lưu Thông tin phương pháp tính | Không có quyền ghi trên vụ này | Cần vai trò chủ hộ/biên tập, hoặc cán bộ hợp tác xã |

---

## 7. Giới hạn cần biết

Kết quả là **IPCC Tier 1** với hệ số mặc định quốc tế, **chưa** hiệu chỉnh cho điều kiện Việt Nam,
**chưa** có chuyên gia rà soát, **chưa** đối chiếu dữ liệu đồng ruộng thực. Dải bất định rộng
(EFc 0,83–1,81; GWP CH₄ ±40 %). Chưa gồm nhiên liệu và điện.

**Không** được trình bày kết quả này như đã chứng nhận hay đạt chuẩn MRV. Danh sách hạn chế đầy đủ:
`docs/methodology/carbon-factor-register.md` §8.

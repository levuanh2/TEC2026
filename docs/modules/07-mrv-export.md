# Module 07 — Export Carbon / MRV Report

| | |
|---|---|
| **Lớp MVP** | **1c — Trình bày/vận hành** (làm cuối, **được phép cắt xuống mock**) |
| **Thư mục** | `backend/` (sinh file) + `web-dashboard/` (nút xuất) |
| **Phụ trách** | Người B sinh file, Người A gắn nút |
| **FR phụ trách** | FR-1c-05 … FR-1c-07 |

> **Lưu ý về task ID:** ID tạm — đối chiếu lại với `AgriCarbon Sprint Tracker`.

---

## 1. Mục tiêu module

Biến dữ liệu đã đo thành **tài liệu dùng được thật trong quy trình chính sách**: báo cáo
PDF/Excel bố cục theo đúng **6 bước MRV** để nộp cho đơn vị thẩm định hoặc cơ quan quản lý.
Đây là bước làm cho sản phẩm "thực chiến" khi pitch, thay vì dừng ở màn hình đẹp.

---

## 2. Input / Output

**Input:** dữ liệu `Carbon` của một hoặc nhiều Crop/Batch, hồ sơ Farm/Plot/HTX, phiên bản bộ
hệ số (`ef_config_version`), phạm vi báo cáo (1 hộ / 1 HTX / toàn vùng).

**Output:** file **PDF hoặc Excel** (chọn một, không cần cả hai ở MVP).

---

## 3. Cấu trúc báo cáo — bám đúng 6 bước MRV

Tên các bước lấy nguyên văn theo Quyết định 4801/QĐ-BNNMT (14/11/2025), **không đổi tên**:

| Mục | Bước MRV | Nội dung đưa vào | Nguồn dữ liệu |
|---|---|---|---|
| **1** | **Chuẩn bị** | Thông tin hộ/HTX/thửa ruộng: mã thửa, diện tích, địa bàn, HTX trực thuộc | Farm, Plot |
| **2** | **Đăng ký** | Danh sách hộ/thửa tham gia, vai trò các bên | Cooperative, User |
| **3** | **Thiết lập đường cơ sở** | CO2e theo kịch bản **tưới ngập liên tục** làm đường cơ sở; bộ hệ số đã dùng | module 02, `emission_factors.yaml` |
| **4** | **Đo đạc** | Toàn bộ Activity Data theo "1 phải 5 giảm"; CO2e thực tế và CO2e/kg; phân rã theo nguồn phát thải | module 01, 02, 04 |
| **5** | **Báo cáo** | Bảng tổng hợp: CO2e tổng, CO2e/kg, mức giảm so với đường cơ sở; các chỉ số tài nguyên/kg | module 02, 04 |
| **6** | **Thẩm định** | Nhật ký truy vết: ai nhập/sửa, thời điểm; phiên bản bộ hệ số; ngày xuất báo cáo | `created_by`/`created_at`/`updated_at`, `ef_config_version` |

**Đủ 6 mục, đúng tên, đúng thứ tự.** Mục nào chưa có dữ liệu thì ghi rõ **"chưa có dữ liệu"** —
không bỏ trống lặng lẽ (FR-1c-05).

---

## 4. Logic nghiệp vụ cốt lõi

### 4.1. Trang đầu bắt buộc có

- Phạm vi báo cáo (hộ nào / HTX nào / vụ nào).
- `ef_config_version` — phiên bản bộ hệ số phát thải đã dùng.
- Ngày xuất báo cáo.

Ba thông tin này là cái làm báo cáo **thẩm định được** thay vì chỉ là bản in đẹp (FR-1c-06).

### 4.2. Đánh dấu rõ số liệu chưa chốt (RB-02)

| Trường hợp | Cách xử lý |
|---|---|
| Giá tín chỉ carbon | **Chưa chốt chính thức** — TCAF đang định giá. Nếu báo cáo có phần quy đổi tiền, phải kèm nhãn "chưa chốt chính thức". Nếu chưa có giá thì **ẩn hoàn toàn** phần đó (FR-1c-07) |
| Hệ số chưa đối chiếu MRV chính thức | In cảnh báo trong mục 3 (Thiết lập đường cơ sở), nêu rõ open issue OI-02 |
| Dữ liệu mẫu dùng cho demo | In rõ **"DỮ LIỆU MẪU – KHÔNG DÙNG CHO BÁO CÁO CHÍNH THỨC"** trên mọi trang |
| RiceMoRe/FarMoRe | **Không** ghi bất cứ câu nào hàm ý đã tích hợp — hai hệ thống này chưa có API mở |

### 4.3. Không tính lại số

Module này đọc kết quả từ module 02 và 04, không tự tính lại. Số trong báo cáo phải trùng khít
số trên màn hình — nếu lệch, giám khảo sẽ thấy ngay và toàn bộ độ tin cậy sụp đổ.

### 4.4. Phạm vi thật của module

Báo cáo này xuất ra file **đúng bố cục 6 bước**, nhưng **chưa phải biểu mẫu chính thức đã được
cơ quan quản lý duyệt**. Nói đúng phạm vi khi pitch: đây là công cụ hỗ trợ số hóa quy trình,
không phải hồ sơ nộp thẳng được ngay. Xem [`mrv-mapping.md`](../mrv-mapping.md) để biết mức
độ phủ từng bước.

---

## 5. Phụ thuộc

| Phụ thuộc vào | Vì sao |
|---|---|
| [`02-carbon-engine`](02-carbon-engine.md) | Nguồn số CO2e, đường cơ sở, `ef_config_version` |
| [`04-resource-dashboard`](04-resource-dashboard.md) | Chỉ số tài nguyên/kg cho mục 5 |
| [`06-web-dashboard`](06-web-dashboard.md) | Nơi đặt nút xuất báo cáo |
| [`mrv-mapping.md`](../mrv-mapping.md) | Nguồn cấu trúc 6 bước và mức độ phủ |

---

## 6. Definition of Done

- [ ] **T2-33** Xuất được file PDF **hoặc** Excel (chọn một) (FR-1c-05)
- [ ] **T2-34** File có đủ 6 mục đúng tên, đúng thứ tự theo §3 (FR-1c-05)
- [ ] **T2-35** Mục thiếu dữ liệu ghi rõ "chưa có dữ liệu", không bỏ trống (FR-1c-05)
- [ ] **T2-36** Trang đầu có phạm vi báo cáo, `ef_config_version`, ngày xuất (FR-1c-06)
- [ ] **T2-37** Phần quy đổi tiền tín chỉ carbon: có nhãn "chưa chốt chính thức" hoặc bị ẩn (FR-1c-07)
- [ ] **T2-38** Dữ liệu mẫu → in cảnh báo "DỮ LIỆU MẪU" trên mọi trang (§4.2)
- [ ] **T2-39** Đối chiếu số trong báo cáo với số trên dashboard: trùng khít (§4.3)
- [ ] **T1-15** Nút xuất báo cáo trên web-dashboard chạy được (Người A)

**Nếu bị cắt xuống mock:** giữ **1 file PDF mẫu** đúng bố cục 6 bước, sinh sẵn từ dữ liệu demo.
Vẫn đủ để pitch, và vẫn phải in cảnh báo "DỮ LIỆU MẪU".

---

## 7. Rủi ro & giả định riêng

| # | Nội dung |
|---|---|
| **RR-01** | **Chưa có biểu mẫu báo cáo chính thức.** Nhóm đang tự dựng bố cục theo tên 6 bước, chưa xin được mẫu từ Sở Nông nghiệp và Môi trường hoặc IRRI. Phải ghi rõ giới hạn này, đừng để hiểu nhầm là mẫu đã được duyệt. |
| **RR-02** | **Rủi ro uy tín cao nhất của cả dự án nằm ở file này.** Một báo cáo trông chính thống nhưng chứa số liệu từ hệ số chưa chốt là thứ dễ bị hội đồng bắt lỗi nhất. Vì vậy §4.2 (đánh dấu số liệu chưa chốt) là bắt buộc, không phải tùy chọn. |
| **RR-03** | Xuất PDF tiếng Việt cần font hỗ trợ dấu. Kiểm tra sớm — lỗi mất dấu tiếng Việt trong PDF là lỗi hay gặp và phát hiện muộn thì mất thời gian sửa. |
| **RR-04** | Module cuối cùng của chuỗi phụ thuộc → **rủi ro tiến độ cao nhất** cùng với module 06. Nếu buộc phải chọn, làm file PDF mẫu tĩnh còn hơn không có gì để cho hội đồng xem. |

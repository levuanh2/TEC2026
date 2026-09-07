# Map tính năng ↔ Quy trình MRV 6 bước

Phiên bản: 0.1 · Ngày: 2026-09-07
Khung tham chiếu: **Quy trình MRV 6 bước**, Quyết định 4801/QĐ-BNNMT ngày 14/11/2025,
Bộ Nông nghiệp và Môi trường. Thí điểm đến hết 31/12/2026, quy mô 300.000 ha vụ Đông Xuân 2025–2026.

> **Mục đích của bảng này:** khi pitch, chỉ thẳng được *"bước X được số hóa bởi module Y"*.
> AgriCarbon định vị là **công cụ hỗ trợ số hóa quy trình MRV chính thức**, không phải một
> carbon calculator tự đặt ra tiêu chí riêng.

---

## Bảng map

| # | Bước MRV | Việc thực tế phải làm ở bước này | Module xử lý | Lớp MVP | Mức độ phủ trong MVP |
|---|---|---|---|---|---|
| **1** | **Chuẩn bị** | Xác định phạm vi, đối tượng tham gia, thu thập thông tin nền của hộ/HTX/thửa ruộng | [`01-mobile-app`](modules/01-mobile-app.md) — tạo hồ sơ Farm/Plot<br>[`06-web-dashboard`](modules/06-web-dashboard.md) — hồ sơ HTX | 1a, 1c | **Một phần** — mới là hồ sơ cơ bản (diện tích, địa bàn, HTX), chưa có bộ hồ sơ chuẩn bị đầy đủ theo quy định |
| **2** | **Đăng ký** | Ghi danh hộ/thửa tham gia; xác định vai trò và quyền của từng bên | [`06-web-dashboard`](modules/06-web-dashboard.md) — phân quyền Nông dân / Quản lý HTX / Doanh nghiệp–Cơ quan quản lý (FR-1c-03) | 1c | **Một phần** — có cơ chế vai trò và danh sách thành viên HTX, chưa nối vào hệ thống đăng ký chính thức của nhà nước |
| **3** | **Thiết lập đường cơ sở** | Xác định mức phát thải nền để đo mức giảm về sau | [`02-carbon-engine`](modules/02-carbon-engine.md) — kịch bản **tưới ngập liên tục** làm đường cơ sở, đối chiếu dải tham chiếu trong `emission_factors.yaml` | 1a | **Một phần** — engine chạy được kịch bản baseline, nhưng bộ hệ số **chưa đối chiếu MRV chính thức** (open issue OI-02) |
| **4** | **Đo đạc** | Thu thập dữ liệu hoạt động canh tác thực tế và tính phát thải | [`01-mobile-app`](modules/01-mobile-app.md) — Activity Data theo "1 phải 5 giảm"<br>[`02-carbon-engine`](modules/02-carbon-engine.md) — CO2e và CO2e/kg<br>[`03-computer-vision`](modules/03-computer-vision.md) — ghi nhận tình trạng bệnh làm dữ liệu bổ trợ<br>[`04-resource-dashboard`](modules/04-resource-dashboard.md) — chỉ số tài nguyên/kg | 1a, 1b | **Đầy đủ nhất** — đây là bước AgriCarbon phủ tốt nhất và cũng là lõi giá trị của sản phẩm |
| **5** | **Báo cáo** | Kết xuất số liệu thành báo cáo nộp lên cấp trên / đơn vị thẩm định | [`07-mrv-export`](modules/07-mrv-export.md) — xuất PDF/Excel bố cục theo đúng 6 bước<br>[`06-web-dashboard`](modules/06-web-dashboard.md) — tổng hợp nhiều hộ trong HTX | 1c | **Một phần** — xuất được file đúng bố cục 6 bước; **chưa** phải biểu mẫu chính thức đã được cơ quan quản lý duyệt |
| **6** | **Thẩm định** | Bên thứ ba kiểm chứng số liệu | [`07-mrv-export`](modules/07-mrv-export.md) — báo cáo ghi kèm `ef_config_version`, ngày xuất, nguồn hệ số<br>[`06-web-dashboard`](modules/06-web-dashboard.md) — `created_by` / `created_at` / `updated_at` cho từng bản ghi (FR-1c-04) | 1c | **Ít nhất** — mới ở mức truy vết được số liệu. Bộ Evidence/Anti-fraud đầy đủ (camera bắt buộc + GPS + timestamp + audit trail + phát hiện anomaly) thuộc **giai đoạn 2**, ngoài phạm vi MVP |

---

## Đọc bảng này thế nào khi pitch

**Điểm mạnh nên nhấn:** bước **4 – Đo đạc** là bước tốn công nhất trong thực tế (hàng trăm
nghìn hộ ghi sổ tay giấy) và cũng là bước AgriCarbon phủ đầy đủ nhất. Số hóa đúng bước này
là chỗ tạo ra giá trị lớn nhất.

**Điểm phải nói thật, không né:**

- Bước **3 – Thiết lập đường cơ sở** phụ thuộc bộ hệ số phát thải chính thức mà nhóm **chưa
  đối chiếu xong** (xem `backend/config/emission_factors.yaml`, open issue OI-01/OI-02).
  Nói rõ đây là việc đang làm, không nói như đã hoàn tất.
- Bước **6 – Thẩm định** trong MVP mới ở mức truy vết số liệu. Bộ chống gian lận đầy đủ nằm
  ở giai đoạn 2. Nói đúng phạm vi hiện có.
- **Không** trình bày như đã tích hợp RiceMoRe/FarMoRe — hai hệ thống này **chưa có API mở**,
  đây là hướng hợp tác tương lai.

---

## Khoảng trống còn lại so với quy trình đầy đủ

| Bước | Còn thiếu gì | Nằm ở đâu trong roadmap |
|---|---|---|
| 1 – Chuẩn bị | Bộ hồ sơ chuẩn bị theo đúng biểu mẫu quy định | Cần xin biểu mẫu chính thức, chưa có |
| 2 – Đăng ký | Kết nối hệ thống đăng ký của cơ quan quản lý (RiceMoRe) | Chờ partnership thể chế — RiceMoRe chưa có API mở |
| 3 – Đường cơ sở | Bộ hệ số phát thải chính thức | Open issue OI-02, hạn 15/09/2026 |
| 4 – Đo đạc | Tự động hóa ghi nhận AWD bằng cảm biến mực nước | Giai đoạn 4 (IoT tối thiểu) |
| 5 – Báo cáo | Biểu mẫu báo cáo chính thức đã được duyệt | Cần xin mẫu từ Sở Nông nghiệp và Môi trường / IRRI |
| 6 – Thẩm định | Camera bắt buộc + GPS + timestamp, audit trail, phát hiện anomaly | Giai đoạn 2 (Evidence / Anti-fraud) |

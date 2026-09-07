# Module 06 — Web Dashboard cho HTX / Doanh nghiệp

| | |
|---|---|
| **Lớp MVP** | **1c — Trình bày/vận hành** (làm cuối, **được phép cắt xuống mock**) |
| **Thư mục** | `web-dashboard/` |
| **Phụ trách** | Người A |
| **FR phụ trách** | FR-1c-01 … FR-1c-04 |

> **Lưu ý về task ID:** ID tạm — đối chiếu lại với `AgriCarbon Sprint Tracker`.

> ⚠️ **Quy tắc cắt scope:** đây là phần "đẹp khi demo" nhưng không phải bằng chứng kỹ thuật
> cốt lõi. Nếu đến 15/09/2026 mà 1b chưa xong → cắt module này xuống **mock tĩnh** (HTML +
> dữ liệu giả) và dồn thời gian cho 1a + 1b. Câu chuyện sản phẩm vẫn kể được trọn vẹn.

---

## 1. Mục tiêu module

Giải quyết đúng pain point ban đầu — *"doanh nghiệp phải tổng hợp dữ liệu từ nhiều hộ/HTX
thủ công"* — bằng một màn hình quản trị gom dữ liệu nhiều hộ về một chỗ, xem được theo cấp bậc
và phân quyền theo vai trò.

---

## 2. Input / Output

**Input:** dữ liệu từ backend — `Farm`, `Plot`, `Crop`, `Batch`, `Activity`, `Carbon`, chỉ số
hiệu suất (module 04), khuyến nghị (module 05).

**Output:** giao diện web; nút kích hoạt xuất báo cáo MRV (module 07).

---

## 3. Cấu trúc màn hình

### 3.1. Cây phân cấp

Duyệt đúng khung mục 8 tài liệu gốc:

```text
Farm (nông hộ)
 └── Plot (thửa ruộng)
      └── Crop (vụ canh tác)
           └── Batch (lô thu hoạch)
                └── Activity (hoạt động canh tác)
                     └── Carbon (kết quả phát thải)
```

Từ một Farm phải bấm xuống được tới một bản ghi Activity và số Carbon tương ứng (FR-1c-01).

### 3.2. Màn hình tổng hợp cấp HTX

Tổng CO2e và CO2e/kg trung bình toàn HTX, bảng xếp hạng các hộ theo carbon/kg (dữ liệu từ
module 04). Cần **≥ 3 hộ** mới có ý nghĩa (FR-1c-02).

### 3.3. Phân quyền 3 vai trò

| Vai trò | Thấy gì | Làm gì |
|---|---|---|
| **Nông dân** (`farmer`) | Chỉ dữ liệu của chính mình | Nhập liệu |
| **Quản lý HTX** (`coop_manager`) | Tổng hợp cấp HTX, tất cả hộ thành viên | Xem, xuất báo cáo cấp HTX |
| **Doanh nghiệp / Cơ quan quản lý** (`enterprise`) | Toàn vùng liên kết | Xem, xuất báo cáo MRV |

**Kiểm chứng bắt buộc (NFR-07):** đăng nhập vai Nông dân rồi **gọi thẳng API bằng id lô của hộ
khác** phải trả 403. Chặn ở giao diện thôi thì không tính là phân quyền.

---

## 4. Logic nghiệp vụ cốt lõi

### 4.1. Chỉ đọc, không tính lại

Dashboard **hiển thị** số do backend tính, không tự tính lại CO2e hay chỉ số hiệu suất.
Nhân bản công thức ở frontend là cách chắc chắn nhất để hai màn hình hiện hai con số khác nhau
ngay giữa buổi demo.

### 4.2. Audit tối thiểu

Mỗi bản ghi hiển thị `created_by`, `created_at`, `updated_at` (FR-1c-04). Đây là mức truy vết
tối thiểu phục vụ **bước 6 MRV – Thẩm định**. Bộ Evidence/Anti-fraud đầy đủ (camera bắt buộc +
GPS + timestamp + audit trail + phát hiện anomaly) thuộc **giai đoạn 2**, ngoài phạm vi MVP.

### 4.3. Stack — cố tình giữ nhẹ

Bắt đầu bằng **một file HTML tĩnh với dữ liệu mock**. Chỉ nâng lên Vite + React khi dashboard
thật sự cần gọi API động. 1c là lớp có thể bị cắt — dựng build toolchain trước khi 1a và 1b
xong là đầu tư vào phần có thể không dùng đến.

---

## 5. Phụ thuộc

| Phụ thuộc vào | Vì sao |
|---|---|
| [`02-carbon-engine`](02-carbon-engine.md) | Nguồn số Carbon |
| [`04-resource-dashboard`](04-resource-dashboard.md) | Nguồn chỉ số hiệu suất và bảng xếp hạng |
| [`05-ai-recommendation`](05-ai-recommendation.md) | Hiển thị khuyến nghị (tùy chọn ở MVP) |
| [`07-mrv-export`](07-mrv-export.md) | Chiều ngược: dashboard là nơi bấm nút xuất báo cáo |

**Phụ thuộc gần như toàn bộ chuỗi trước** — vì vậy nó nằm cuối thứ tự thực hiện.

---

## 6. Definition of Done

- [ ] **T1-09** Duyệt được cây Farm → Plot → Crop → Batch → Activity → Carbon (FR-1c-01)
- [ ] **T1-10** Màn hình tổng hợp cấp HTX với **≥ 3 hộ** (FR-1c-02)
- [ ] **T1-11** Ba vai trò đăng nhập được, thấy đúng phạm vi dữ liệu (FR-1c-03)
- [ ] **T1-12** Gọi API bằng token vai Nông dân với id lô hộ khác → trả **403** (NFR-07)
- [ ] **T1-13** Mỗi bản ghi hiện `created_by` / `created_at` / `updated_at` (FR-1c-04)
- [ ] **T1-14** Có nút xuất báo cáo MRV nối sang module 07

**Nếu bị cắt xuống mock:** chỉ giữ T1-09 và T1-10 ở dạng tĩnh, đủ để kể câu chuyện khi demo.

---

## 7. Rủi ro & giả định riêng

| # | Nội dung |
|---|---|
| **RR-01** | **Rủi ro tiến độ cao nhất trong 7 module** — nằm cuối chuỗi phụ thuộc, chỉ khởi động được khi 1a và 1b đã xong. Cần quyết định cắt hay không **trước 15/09/2026**, không để sát deadline. |
| **RR-02** | **Giả định:** có đủ dữ liệu của ≥ 3 hộ để màn hình tổng hợp có ý nghĩa. Nếu chưa chốt HTX pilot (R1), phải dùng dữ liệu mẫu và **ghi rõ trên màn hình demo rằng đây là dữ liệu mẫu**. |
| **RR-03** | Phân quyền là hạng mục dễ làm hời hợt (chỉ ẩn nút trên giao diện). Phải chặn ở tầng API, và T1-12 chính là bài test cho việc đó. |
| **RR-04** | Nếu cắt xuống mock, khi pitch **phải nói rõ đây là bản mock**. Trình bày mock như sản phẩm chạy thật là rủi ro uy tín lớn hơn nhiều so với việc thừa nhận đã cắt scope có chủ đích. |

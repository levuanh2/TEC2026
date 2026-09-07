# Module 01 — Mobile App ghi nhật ký canh tác

| | |
|---|---|
| **Lớp MVP** | **1a — Walking Skeleton (đường găng, ưu tiên tuyệt đối)** |
| **Thư mục** | `app/` |
| **Phụ trách** | Người A |
| **FR phụ trách** | FR-1a-01 … FR-1a-07, FR-1a-10, FR-1a-11 |

> **Lưu ý về task ID:** các ID `T1-xx` dưới đây là ID tạm, hiểu theo nghĩa Sprint 1.
> **Phải đối chiếu lại với file `AgriCarbon Sprint Tracker` và sửa cho khớp trước khi bắt đầu code.**

---

## 1. Mục tiêu module

Thay thế sổ tay giấy: cho nông hộ ĐBSCL ghi nhận hoạt động canh tác theo khung "1 phải 5 giảm"
ngay trên điện thoại **kể cả khi mất sóng**, và hiển thị lại CO2e/kg mà Carbon Engine trả về.

---

## 2. Input / Output

**Input:** thao tác nhập tay của nông dân; (giai đoạn 1b) ảnh lá lúa chụp bằng camera.

**Output:**
- Bản ghi `Activity` lưu trong SQLite cục bộ.
- Batch dữ liệu đẩy lên `POST /v1/sync` khi có mạng.
- Màn hình hiển thị CO2e/kg + phân rã theo nguồn phát thải.

---

## 3. Field chi tiết của form

Form bám sát khung **"1 phải 5 giảm"** — vừa đúng chính sách thật, vừa dễ giải thích với hội đồng.
Ở lớp 1a chỉ cần đủ field phục vụ công thức tính CO2e; **chưa cần giao diện đẹp**.

### 3.1. Hồ sơ thửa ruộng (Plot) — nhập 1 lần

| Field | Kiểu | Bắt buộc | Ghi chú |
|---|---|---|---|
| `code` | text | ✅ | Tên/mã thửa do nông dân tự đặt |
| `area_ha` | số | ✅ | Diện tích (ha), phải > 0 |
| `commune` / `district` / `province` | text | ✅ | Địa bàn |
| `cooperative_id` | chọn | ✅ | HTX trực thuộc |
| `soil_type` | chọn | ❌ | Để dành cho hệ số chính xác hơn về sau |

### 3.2. Vụ canh tác (Crop) — nhập đầu vụ

| Field | Kiểu | Bắt buộc | Ghi chú |
|---|---|---|---|
| `season` | chọn | ✅ | Đông Xuân / Hè Thu / Thu Đông |
| `variety` | text | ✅ | Giống lúa |
| `sowing_date` | ngày | ✅ | Không cho chọn ngày tương lai |
| `harvest_date` | ngày | ❌ | Nhập khi thu hoạch |

### 3.3. Hoạt động canh tác (Activity) — nhập trong vụ

Trường chung mọi loại: `type`, `date`, `note`.

| `type` | Field riêng | Bắt buộc | Thuộc "1 phải 5 giảm" |
|---|---|---|---|
| **`seed` — Giống** | `variety`, `seed_rate_kg_per_ha`, `sowing_method` (sạ lan / sạ hàng / cấy) | ✅ ✅ ✅ | Giảm giống |
| **`fertilizer` — Phân bón** | `fertilizer_type`, `amount_kg`, `n_content_pct`, `application_no` | ✅ ✅ ❌ ✅ | Giảm phân |
| **`water` — Nước tưới** | `regime` (**AWD** / **ngập liên tục**), `drainage_events`, `drainage_dates[]`, `pump_fuel_litre` | ✅ ⚠️ ❌ ❌ | Giảm nước — **quan trọng nhất với carbon** |
| **`pesticide` — Thuốc BVTV** | `product_group`, `amount`, `unit` | ✅ ✅ ✅ | Giảm thuốc |
| **`straw` — Xử lý rơm rạ** | `method` (đốt / vùi / lấy khỏi ruộng), `amount_kg` | ✅ ❌ | Xử lý rơm rạ |
| **`harvest` — Thu hoạch** | `yield_kg`, `loss_kg` | ✅ ❌ | Giảm thất thoát sau thu hoạch |

⚠️ `drainage_events`: chọn AWD mà bỏ trống → **cảnh báo nhưng vẫn cho lưu**. Dữ liệu đồng ruộng
thường thiếu; chặn cứng sẽ khiến nông dân bỏ dở việc nhập (FR-1a-04).

`yield_kg` là **mẫu số của mọi chỉ số per-kg** — thiếu nó thì không có CO2e/kg (FR-1a-11).

---

## 4. Logic nghiệp vụ cốt lõi

### 4.1. Offline-first

1. Mọi thao tác ghi thẳng vào **SQLite cục bộ**, không chờ mạng.
2. Mỗi bản ghi mang **`client_id` (UUID sinh trên máy)** — đây là khóa khử trùng lặp phía server.
3. Bản ghi vào **hàng đợi đồng bộ**, trạng thái `pending`.
4. Khi có mạng: gửi batch lên `POST /v1/sync`; server trả `server_ids` → cập nhật trạng thái `synced`.
5. Hàng đợi phải sống sót qua việc tắt/mở lại app.
6. Gửi lại cùng batch phải **không tạo bản ghi mới** (idempotent — FR-1a-07).

### 4.2. Hiển thị kết quả carbon

Gọi `POST /v1/carbon/calculate`, hiển thị `co2e_per_kg` cùng bảng phân rã `breakdown`
(CH4 ruộng ngập / N2O phân bón / rơm rạ / nhiên liệu bơm). Tổng các dòng phải bằng tổng hiển thị.

**Không bịa số (NFR-03):** nếu `co2e_per_kg` trả về `null` (chưa có sản lượng) → hiển thị
*"Chưa nhập sản lượng thu hoạch nên chưa tính được CO2e/kg"*. **Tuyệt đối không hiển thị 0.**

### 4.3. Ngôn ngữ giao diện

Dùng từ ngữ khuyến nông: "rút nước", "bón lần 2", "sạ hàng". **Không** dùng "N2O", "CH4 scaling
factor", "activity data" ở màn hình nhập liệu — các thuật ngữ đó chỉ xuất hiện ở màn hình kết quả
và báo cáo (NFR-06).

---

## 5. Phụ thuộc

| Phụ thuộc vào | Ở mức nào |
|---|---|
| [`02-carbon-engine`](02-carbon-engine.md) | Cần hợp đồng API ([SRS §4](../SRS.md#4-api-contract-nháp--luồng-1a)) để hiển thị kết quả. **Chốt hợp đồng trước**, sau đó Người A code UI song song với Người B code engine — mock response để không bị chặn. |
| [`03-computer-vision`](03-computer-vision.md) | Chỉ ở lớp 1b (thêm nút chụp ảnh lá). Không chặn 1a. |

**Module này không phụ thuộc gì khác — nó là đầu nguồn dữ liệu của toàn hệ thống.**

---

## 6. Definition of Done

- [ ] **T1-01** Tạo được Plot và Crop, dữ liệu còn nguyên sau khi tắt/mở app (FR-1a-01)
- [ ] **T1-02** Form nhập đủ 6 loại Activity theo bảng §3.3 (FR-1a-02 … FR-1a-05)
- [ ] **T1-03** Nhập trọn 1 vụ ở chế độ máy bay, không mất bản ghi nào (FR-1a-06)
- [ ] **T1-04** Hàng đợi đồng bộ chạy: 20 bản ghi offline → bật mạng → server nhận đúng 20 (FR-1a-07)
- [ ] **T1-05** Đồng bộ lại lần 2 vẫn là 20 bản ghi, không trùng (FR-1a-07)
- [ ] **T1-06** Màn hình kết quả hiện CO2e/kg + ≥ 4 dòng phân rã, tổng khớp (FR-1a-10)
- [ ] **T1-07** Thiếu `yield_kg` → báo "chưa tính được", không hiện 0 (FR-1a-11, NFR-03)
- [ ] **T1-08** Người ngoài nhóm hoàn tất 1 lượt nhập trong < 2 phút, không cần hướng dẫn (NFR-06, M2)

---

## 7. Rủi ro & giả định riêng

| # | Nội dung |
|---|---|
| **RR-01** | **Giả định:** nông dân chịu nhập liệu đều đặn trong vụ. Thực tế nhiều hộ chỉ ghi khi được nhắc. Nếu pilot cho thấy tỷ lệ bỏ dở cao → cân nhắc kéo Growth Stage Reminder (mục 6.2 tài liệu gốc) lên sớm, dù nó nằm ngoài MVP. |
| **RR-02** | `water.regime` về bản chất là thuộc tính của cả vụ nhưng đang lưu ở mức Activity. Nếu một vụ có nhiều bản ghi `water` mâu thuẫn `regime`, engine sẽ trả 422 — **app phải chặn hoặc cảnh báo ngay lúc nhập**, đừng để lỗi nổ ở server. |
| **RR-03** | Chưa chốt HTX pilot (R1 trong PRD) → chưa test được trên điện thoại đời cũ, sóng thật. Ít nhất phải test trên 1 máy Android tầm thấp trước khi demo. |
| **RR-04** | Xung đột dữ liệu khi cùng 1 tài khoản nhập trên 2 máy: **ngoài phạm vi MVP**. Giả định 1 hộ = 1 máy. Ghi rõ giả định này khi pitch nếu bị hỏi. |

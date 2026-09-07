# Module 04 — Resource Efficiency Dashboard

| | |
|---|---|
| **Lớp MVP** | **1b — AI/CV** |
| **Thư mục** | `backend/` (tính toán) + `app/` (hiển thị cho nông dân) |
| **Phụ trách** | Người B tính, Người A hiển thị |
| **FR phụ trách** | FR-1b-05, FR-1b-06 |

> **Lưu ý về task ID:** ID tạm — đối chiếu lại với `AgriCarbon Sprint Tracker`.

---

## 1. Mục tiêu module

Quy đổi dữ liệu canh tác thành bốn chỉ số hiệu suất **trên mỗi kilogram sản phẩm** — đơn vị
trực quan mà nông dân cảm nhận được — và cho so sánh giữa các thửa/lô trong cùng HTX.

**Tận dụng lại đúng dữ liệu đã có từ 1a, không thu thập thêm gì.**

---

## 2. Input / Output

**Input:**
- `Activity` của vụ (từ module 01) — lượng nước, lượng phân, chi phí vật tư.
- `Carbon.co2e_total_kg` (từ module 02).
- `yield_kg` (sản lượng thu hoạch).

**Output:** bốn chỉ số cho mỗi Plot/Crop, cộng dữ liệu so sánh trong HTX:

```json
{
  "plot_id": "plot-001",
  "yield_kg": 3100.0,
  "metrics": {
    "water_litre_per_kg": 1420.0,
    "fertilizer_kg_per_kg": 0.058,
    "co2e_kg_per_kg": 1.555,
    "cost_vnd_per_kg": 4150.0
  },
  "coop_benchmark": {
    "co2e_kg_per_kg": 1.720,
    "source": "trung bình 12 hộ trong HTX, vụ Hè Thu 2026"
  }
}
```

---

## 3. Bốn chỉ số — định nghĩa

| Chỉ số | Công thức | Nguồn dữ liệu | Ghi chú |
|---|---|---|---|
| **Nước / kg** | tổng lượng nước tưới ÷ `yield_kg` | Activity `water` | Với AWD, lượng nước ước từ số lần tưới/rút; **độ chính xác thấp hơn** ba chỉ số kia — nói rõ khi trình bày |
| **Phân bón / kg** | tổng lượng phân ÷ `yield_kg` | Activity `fertilizer` | Nên hiển thị cả tổng phân và riêng lượng N |
| **Carbon / kg** | `co2e_total_kg` ÷ `yield_kg` | module 02 | Chỉ số lõi, đã có sẵn từ Carbon Engine |
| **Chi phí / kg** | tổng chi phí vật tư ÷ `yield_kg` | Activity (giống, phân, thuốc, nhiên liệu) | MVP chỉ tính **chi phí vật tư**; nhân công và thuê máy thuộc Cost Management đầy đủ — giai đoạn 4 |

---

## 4. Logic nghiệp vụ cốt lõi

### 4.1. Mẫu số chung

Cả bốn chỉ số dùng chung mẫu số `yield_kg`. Hệ quả:
**chưa có sản lượng thì không có chỉ số nào.** Khi thiếu, hiển thị "chưa có sản lượng thu hoạch"
cho cả bốn ô — không hiện 0, không hiện ô trống không giải thích (NFR-03).

### 4.2. So sánh trong HTX (Efficiency Map)

So sánh các lô theo `co2e_kg_per_kg` bằng bảng xếp hạng hoặc bản đồ màu (xanh/vàng/đỏ), tham
khảo mô hình quản lý vùng đất của FaceFarm. Đây là dữ liệu để trả lời câu hỏi *"tôi đang ở
đâu so với các hộ khác trong HTX?"*.

**Quy tắc bắt buộc:** benchmark phải ghi rõ **là gì và lấy từ đâu** — "trung bình 12 hộ trong
HTX vụ Hè Thu 2026" chứ không phải một con số trôi nổi (FR-1b-09).

Bản đồ theo tọa độ thửa ruộng thuộc **giai đoạn 2** (Farm Map). MVP dùng bảng/biểu đồ là đủ.

### 4.3. Không tính lại carbon

Module này **đọc** `co2e_total_kg` từ module 02, không tự tính lại. Nhân bản công thức ở hai
chỗ là cách chắc chắn nhất để hai màn hình hiện hai con số khác nhau khi demo.

---

## 5. Phụ thuộc

| Phụ thuộc vào | Vì sao |
|---|---|
| [`01-mobile-app`](01-mobile-app.md) | Nguồn Activity Data (nước, phân, chi phí vật tư, sản lượng) |
| [`02-carbon-engine`](02-carbon-engine.md) | Nguồn `co2e_total_kg` |

**Chặn cứng:** 1a phải xong trước. Module này không tạo ra dữ liệu mới, chỉ biến đổi dữ liệu 1a.
Nó cũng là nguồn đầu vào cho [`05-ai-recommendation`](05-ai-recommendation.md) và
[`06-web-dashboard`](06-web-dashboard.md).

---

## 6. Definition of Done

- [ ] **T2-19** Tính đủ 4 chỉ số ở §3, mỗi chỉ số truy được về Activity Data gốc (FR-1b-05)
- [ ] **T2-20** Thiếu `yield_kg` → cả 4 ô báo "chưa có sản lượng", không hiện 0 (NFR-03)
- [ ] **T2-21** `GET /v1/plots/{id}/efficiency` trả đúng cấu trúc ở §2
- [ ] **T2-22** Xếp hạng được **≥ 3 lô** trong cùng HTX theo carbon/kg (FR-1b-06)
- [ ] **T2-23** Mỗi benchmark hiển thị kèm dòng "so với: …" nêu rõ nguồn (FR-1b-09)
- [ ] **T2-24** Màn hình 4 chỉ số hiển thị được trên app (Người A)

---

## 7. Rủi ro & giả định riêng

| # | Nội dung |
|---|---|
| **RR-01** | **Chỉ số nước/kg là ước lượng, không phải đo.** Nông dân không có đồng hồ nước; lượng nước suy ra từ số lần tưới và diện tích. Phải nói rõ đây là ước lượng khi pitch — nếu để giám khảo tự phát hiện sẽ mất điểm nặng hơn. |
| **RR-02** | **Benchmark HTX cần tối thiểu vài hộ mới có ý nghĩa.** Nếu chỉ có dữ liệu 1–2 hộ, "trung bình HTX" là con số vô nghĩa. Khi ít dữ liệu, dùng dải tham chiếu vùng thay vì trung bình HTX, và ghi rõ. |
| **RR-03** | **Chi phí/kg trong MVP chỉ gồm vật tư**, chưa gồm nhân công và thuê máy — hai khoản lớn trong thực tế. Ghi rõ phạm vi trên màn hình, đừng để hiểu nhầm là giá thành đầy đủ. |
| **RR-04** | So sánh giữa các hộ có thể gây phản ứng xã hội trong HTX. Bản Leaderboard chính thức (mục 6.3 tài liệu gốc) dự kiến **ẩn danh**. MVP nên theo hướng đó ngay từ đầu. |

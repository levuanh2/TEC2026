# Module 03 — Computer Vision: phát hiện bệnh lá lúa

| | |
|---|---|
| **Lớp MVP** | **1b — AI/CV** (làm ngay sau khi 1a chạy ổn) |
| **Thư mục** | `ml/` (+ điểm chạm ở `app/` để chụp ảnh) |
| **Phụ trách** | Người B |
| **FR phụ trách** | FR-1b-01 … FR-1b-04 |

> **Lưu ý về task ID:** ID `T2-xx` là tạm — đối chiếu lại với `AgriCarbon Sprint Tracker`.

> **Vì sao module này bắt buộc có trong MVP:** cuộc thi thuộc chủ đề AI. MVP chỉ có con số
> CO2e mà không có yếu tố AI/CV thì phần "công nghệ" bị đánh giá mỏng. Nhưng làm **sau 1a**
> để lõi chắc trước, tránh vỡ tiến độ ở phần quan trọng nhất.

---

## 1. Mục tiêu module

Một bài toán duy nhất: phân loại ảnh lá lúa chụp bằng điện thoại thành **đạo ôn (blast)**,
**bạc lá (bacterial blight)**, **đốm nâu (brown spot)**, hoặc **lá khỏe** — làm đầu vào tự động
cho vòng lặp tối ưu (phát hiện sớm → giảm thuốc/phân dư thừa → giảm carbon và chi phí).

**Không ôm thêm bài toán khác** (đếm bông, ước lượng năng suất) ở giai đoạn này.

---

## 2. Input / Output

**Input:** 1 ảnh lá lúa (JPEG/PNG) chụp bằng camera điện thoại thông thường.

**Output:**

```json
{
  "label": "brown_spot",
  "label_vi": "Đốm nâu",
  "confidence": 0.87,
  "is_uncertain": false
}
```

`label` ∈ { `blast`, `bacterial_blight`, `brown_spot`, `healthy` }.
Khi `confidence` dưới ngưỡng → `is_uncertain: true`, **không ép chọn nhãn** (FR-1b-04).

---

## 3. Dữ liệu

| Bộ | Vai trò | Quy mô | Trạng thái |
|---|---|---|---|
| **Sethy et al.** — Rice Leaf Disease | Pretrain | ~5.932 ảnh, 4 lớp | Cần **xác nhận license** trước khi dùng (dự kiến CC BY 4.0) |
| Ảnh thực địa HTX pilot | Fine-tune | mục tiêu ≥ vài trăm ảnh | **Chưa có** — phụ thuộc R1 (chưa chốt HTX pilot) |

Chi tiết và checklist license: [`ml/datasets/README.md`](../../ml/datasets/README.md).

**Tập test phải tách riêng hoàn toàn**, không chồng lấn tập train (FR-1b-03).

---

## 4. Logic nghiệp vụ cốt lõi

### 4.1. Quy trình huấn luyện

```text
1. Pretrain trên dataset public (Sethy et al., 4 lớp)
        │
        ▼
2. Fine-tune bằng ảnh thực địa thu tại HTX pilot
   → giảm domain gap giữa ảnh phòng thí nghiệm và ảnh đồng ruộng
        │
        ▼
3. Đánh giá trên tập test tách riêng
   → accuracy + confusion matrix, GHI RÕ đo trên nguồn ảnh nào
        │
        ▼
4. Export model, gắn vào luồng app (chụp ảnh → nhãn bệnh)
```

### 4.2. Domain gap — vấn đề thật, không phải lo xa

Dataset public chụp trong điều kiện kiểm soát (nền sạch, ánh sáng đều). Ảnh nông dân chụp
ngoài đồng có **nắng gắt, nền lẫn nhiều lá, ảnh rung nhòe, góc chụp tùy tiện**. Model chỉ
train trên dataset public sẽ cho accuracy đẹp trên giấy nhưng kém ngoài thực địa.

Vì vậy fine-tune bằng ảnh thực địa là **bắt buộc, không phải tùy chọn**. Nếu đến hạn vẫn chưa
có ảnh thực địa: vẫn nộp model pretrain, nhưng báo cáo **phải ghi rõ** con số accuracy đo trên
dataset public không đại diện điều kiện đồng ruộng (RB-06, rủi ro R2 trong PRD).

### 4.3. Xử lý ảnh không hợp lệ

Nông dân sẽ chụp nhầm: ảnh đất, ảnh bàn tay, ảnh cây khác. Model 4 lớp sẽ ép ảnh đó vào một
trong 4 nhãn với độ tin cậy có thể vẫn cao. Cách xử lý tối thiểu trong MVP: **đặt ngưỡng
confidence và trả `is_uncertain`** khi dưới ngưỡng (FR-1b-04). Bổ sung lớp "không phải lá lúa"
là việc của giai đoạn sau.

### 4.4. Vai trò trong vòng lặp

CV không dừng ở "phát hiện bệnh" như các app nông nghiệp thông thường. Nó là **mắt xích trong
chuỗi MEASURE → UNDERSTAND → OPTIMIZE → ACT**: phát hiện sớm → can thiệp đúng lúc → giảm phun
thuốc và bón phân dư thừa → trực tiếp giảm CO2e và chi phí. Đây là điểm khác biệt nên nhấn khi pitch.

---

## 5. Phụ thuộc

| Phụ thuộc vào | Ở mức nào |
|---|---|
| [`01-mobile-app`](01-mobile-app.md) | Cần luồng chụp/chọn ảnh trong app. Model train được độc lập, chỉ cần app khi tích hợp. |
| Ảnh thực địa từ HTX pilot | **Chặn chất lượng, không chặn tiến độ** — vẫn train được trên dataset public trước. |
| [`05-ai-recommendation`](05-ai-recommendation.md) | Chiều ngược: recommendation có thể dùng kết quả CV làm tín hiệu đầu vào (tùy chọn ở MVP). |

**Không phụ thuộc Carbon Engine** — hai nhánh này chạy song song được.

---

## 6. Definition of Done

- [ ] **T2-11** Nạp được dataset public, xác nhận license và ghi ngày xác nhận vào `ml/datasets/README.md` (RB-05)
- [ ] **T2-12** Train model phân loại 4 lớp, chạy được inference trên 1 ảnh (FR-1b-01)
- [ ] **T2-13** Tập test tách riêng, có báo cáo accuracy + confusion matrix (FR-1b-03)
- [ ] **T2-14** Accuracy đạt **≥ 85%** trên tập test dataset public (M4)
- [ ] **T2-15** Báo cáo ghi rõ điều kiện đo (dataset public hay ảnh thực địa) (RB-06)
- [ ] **T2-16** Ngưỡng confidence hoạt động: ảnh không phải lá lúa → `is_uncertain: true` (FR-1b-04)
- [ ] **T2-17** Fine-tune bằng ảnh thực địa **nếu có**, ghi so sánh accuracy trước/sau (FR-1b-02)
- [ ] **T2-18** Tích hợp vào app: chụp ảnh → hiện nhãn bệnh tiếng Việt + độ tin cậy

---

## 7. Rủi ro & giả định riêng

| # | Nội dung |
|---|---|
| **RR-01** | **Chưa có ảnh thực địa** (R2 trong PRD). Đây là rủi ro lớn nhất của module. Kế hoạch dự phòng: nộp model pretrain kèm cảnh báo điều kiện đo — **không** trình bày accuracy dataset public như độ chính xác thực địa. |
| **RR-02** | **Giả định:** 4 lớp bệnh là đủ. Thực tế ruộng còn nhiều vấn đề khác (thiếu dinh dưỡng, ngộ độc phèn, sâu hại) trông giống bệnh. Model sẽ gán nhầm vào 1 trong 4 nhãn. Ngưỡng confidence chỉ giảm bớt chứ không giải quyết triệt để. |
| **RR-03** | License dataset **chưa xác nhận** (R7). Phải xác nhận trước khi train, không phải trước khi nộp. |
| **RR-04** | Ảnh nông dân chụp có thể chứa thông tin nhạy cảm (mặt người, vị trí). Nếu dùng ảnh thực địa để train, phải có thỏa thuận sử dụng với HTX. |
| **RR-05** | Chạy model trên server hay trên máy (on-device) **chưa chốt**. On-device tốt cho offline-first nhưng nặng công hơn. Quyết định sau khi 1a xong, dựa trên thời gian còn lại. |

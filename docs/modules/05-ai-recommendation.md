# Module 05 — AI Recommendation (mức cơ bản)

| | |
|---|---|
| **Lớp MVP** | **1b — AI/CV** |
| **Thư mục** | `backend/` (sinh khuyến nghị) + `app/` (hiển thị) |
| **Phụ trách** | Người B sinh, Người A hiển thị |
| **FR phụ trách** | FR-1b-07 … FR-1b-09 |

> **Lưu ý về task ID:** ID tạm — đối chiếu lại với `AgriCarbon Sprint Tracker`.

---

## 1. Mục tiêu module

Biến chỉ số thành hành động: khi một chỉ số vượt benchmark, sinh khuyến nghị điều chỉnh **cụ
thể, có con số**, và **luôn kèm ước tính impact** (giảm bao nhiêu CO2e, tiết kiệm bao nhiêu
chi phí) — để nông dân ra quyết định mà không cần kiến thức kỹ thuật chuyên sâu.

---

## 2. Input / Output

**Input:**
- Bốn chỉ số hiệu suất của lô (từ module 04).
- Benchmark: trung bình HTX hoặc dải tham chiếu vùng.
- Hệ số phát thải từ `emission_factors.yaml` (để ước tính impact).
- (Tùy chọn) kết quả CV từ module 03 làm tín hiệu bổ sung.

**Output:** danh sách khuyến nghị:

```json
[
  {
    "id": "rec-001",
    "trigger": "fertilizer_n_above_benchmark",
    "message_vi": "Lô này dùng phân đạm cao hơn mức trung bình HTX 21%. Gợi ý giảm 18 kg N ở lần bón tiếp theo.",
    "compared_to": "trung bình 12 hộ trong HTX, vụ Hè Thu 2026",
    "impact": {
      "co2e_reduction_kg": 112.0,
      "co2e_reduction_pct": 2.3,
      "cost_saving_vnd": 340000
    },
    "confidence": "rule_based"
  }
]
```

---

## 3. Logic nghiệp vụ cốt lõi

### 3.1. Rule-based, không cần model

Ở MVP dùng luật đơn giản trên dữ liệu đã có, không huấn luyện mô hình. Lý do: dữ liệu thật
chưa đủ để train bất cứ thứ gì có ý nghĩa, và luật thì **giải thích được** trước hội đồng —
điều quan trọng hơn độ tinh vi ở giai đoạn này.

### 3.2. Bộ luật khởi điểm

| Trigger | Điều kiện | Khuyến nghị |
|---|---|---|
| `fertilizer_n_above_benchmark` | lượng N/kg cao hơn benchmark > 15% | Giảm N cụ thể ở lần bón tiếp theo |
| `water_regime_continuous` | vụ đang tưới ngập liên tục | Chuyển sang **AWD**, nêu mức giảm CO2e ước tính |
| `awd_drainage_too_few` | chọn AWD nhưng số lần rút nước thấp bất thường | Tăng số lần rút nước theo hướng dẫn "1 phải 5 giảm" |
| `straw_burned` | xử lý rơm rạ = đốt | Chuyển sang vùi hoặc lấy khỏi ruộng, nêu mức giảm CO2e |
| `seed_rate_high` | lượng giống gieo sạ/ha cao hơn khuyến cáo | Giảm lượng giống ("giảm giống" trong "1 phải 5 giảm") |
| `pesticide_above_benchmark` | lượng thuốc/kg cao hơn benchmark | Rà lại lịch phun; nếu có kết quả CV "lá khỏe" thì nhấn mạnh hơn |

Bộ luật bám đúng khung **"1 phải 5 giảm"** — không tự nghĩ ra khuyến nghị nằm ngoài khung kỹ thuật
mà khuyến nông đang phổ biến.

### 3.3. Impact estimate là bắt buộc

**Không có khuyến nghị suông.** Mỗi khuyến nghị phải trả lời được "làm theo thì được gì":

```text
impact.co2e_reduction_kg  =  CO2e(kịch bản hiện tại)  −  CO2e(kịch bản sau điều chỉnh)
```

Tính bằng cách **gọi lại Carbon Engine với input giả định** — không viết công thức riêng ở
module này. Đây cũng chính là mầm của What-if Simulation ở giai đoạn 2: cùng một cơ chế,
chỉ khác ở chỗ người dùng tự nhập kịch bản thay vì hệ thống tự sinh.

Nếu không tính được impact (thiếu hệ số, thiếu sản lượng) → **không hiển thị khuyến nghị đó**,
thay vì hiển thị lời khuyên rỗng (FR-1b-08).

### 3.4. Luôn nói rõ so với cái gì

Mỗi khuyến nghị kèm trường `compared_to` nêu rõ benchmark và nguồn (FR-1b-09). Câu "bạn dùng
phân cao hơn mức trung bình" mà không nói trung bình của ai thì không kiểm chứng được.

### 3.5. Ranh giới — không tư vấn ngoài phạm vi

Chỉ khuyến nghị về **lượng vật tư và chế độ canh tác đã có trong dữ liệu**. Không chẩn đoán
bệnh (đó là việc của module 03), không kê thuốc cụ thể, không tư vấn ngoài nông nghiệp/carbon.
Sai một lời khuyên kỹ thuật ngoài phạm vi có thể gây thiệt hại thật cho nông dân.

---

## 4. Phụ thuộc

| Phụ thuộc vào | Vì sao |
|---|---|
| [`04-resource-dashboard`](04-resource-dashboard.md) | Nguồn chỉ số và benchmark |
| [`02-carbon-engine`](02-carbon-engine.md) | Gọi lại để tính impact estimate |
| [`03-computer-vision`](03-computer-vision.md) | Tùy chọn — kết quả CV làm tín hiệu bổ sung, không bắt buộc ở MVP |

Đây là module **cuối chuỗi phụ thuộc của lớp 1b** — làm sau cùng trong 1b.

---

## 5. Definition of Done

- [ ] **T2-25** Cài đặt ≥ 4 luật trong bảng §3.2 (FR-1b-07)
- [ ] **T2-26** Mỗi khuyến nghị sinh ra đều có đủ `co2e_reduction_kg` và `cost_saving_vnd` (FR-1b-08)
- [ ] **T2-27** Impact tính bằng cách **gọi lại Carbon Engine**, không nhân bản công thức (§3.3)
- [ ] **T2-28** Không tính được impact → không hiển thị khuyến nghị đó (FR-1b-08)
- [ ] **T2-29** Mỗi khuyến nghị có `compared_to` nêu rõ benchmark và nguồn (FR-1b-09)
- [ ] **T2-30** Duyệt toàn bộ khuyến nghị sinh ra trên dữ liệu demo: không có cái nào thiếu impact
- [ ] **T2-31** Dựng được **≥ 1 kịch bản Before/After** có số liệu để pitch (M6)
- [ ] **T2-32** Màn hình khuyến nghị hiển thị trên app, tiếng Việt (Người A)

---

## 6. Rủi ro & giả định riêng

| # | Nội dung |
|---|---|
| **RR-01** | **Impact estimate chính xác đúng bằng độ chính xác của hệ số phát thải.** Hệ số còn `null` hoặc chưa đối chiếu MRV (OI-02) thì con số "giảm 112 kg CO2e" là ước lượng thô. Phải ghi rõ khi pitch. |
| **RR-02** | **Giả định:** benchmark HTX phản ánh mức hợp lý. Thực tế cả HTX có thể cùng bón thừa phân — khi đó "bằng trung bình HTX" vẫn là lãng phí. Khi có dải tham chiếu chính thức, nên so với dải đó thay vì chỉ so nội bộ. |
| **RR-03** | **Rủi ro khuyến nghị sai gây hại thật:** giảm phân quá tay có thể làm giảm năng suất. MVP nên đặt trần cho mức giảm đề xuất và ghi câu miễn trừ "khuyến nghị tham khảo, cân nhắc điều kiện thực tế ruộng của bạn". |
| **RR-04** | Chi phí tiết kiệm tính theo **giá vật tư**, cần một bảng giá tham chiếu. Bảng này cũng phải nằm ở config kèm nguồn và ngày, giống hệ số phát thải (RB-01). |
| **RR-05** | **Không quy đổi khuyến nghị ra tiền tín chỉ carbon** — giá tín chỉ chưa chốt chính thức (RB-02). |

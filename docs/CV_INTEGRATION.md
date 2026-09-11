# CV Integration Contract — M03 Computer Vision MVP

> Tài liệu này mô tả **contract** giữa model CV (`ml/`) và app Flutter. Không
> chứa code Flutter — thành viên phụ trách Flutter tự tích hợp theo contract
> này. Không phải REST API (M03 không có backend endpoint mới — xem
> Phase 19/"NO SCOPE CREEP" trong task gốc).

## Input

- 1 ảnh lá lúa, định dạng **JPEG hoặc PNG**, chụp bằng camera điện thoại thông thường.
- Không giới hạn cứng resolution đầu vào — pipeline tự resize về kích thước
  model yêu cầu (224×224, xem `ml/model.py::build_transforms`).

## Output

```json
{
  "label": "brown_spot",
  "label_vi": "Đốm nâu",
  "confidence": 0.87,
  "uncertain": false,
  "model_version": "mobilenetv2-baseline-20260909-220512"
}
```

Khi `uncertain: true`:

```json
{
  "label": null,
  "label_vi": null,
  "confidence": 0.42,
  "uncertain": true,
  "model_version": "mobilenetv2-baseline-20260909-220512"
}
```

`label: null` khi `uncertain: true` — **không ép chọn nhãn** (FR-1b-04). App
Flutter PHẢI xử lý `label == null` như trạng thái "không chắc chắn", không
được hiển thị nhãn bệnh ngẫu nhiên hoặc mặc định.

## Labels (canonical — khớp DB enum `public.disease_label`)

| `label` | `label_vi` |
|---|---|
| `rice_blast` | Đạo ôn |
| `bacterial_leaf_blight` | Bạc lá |
| `brown_spot` | Đốm nâu |
| `healthy` | Khỏe mạnh |

`label` khi không uncertain **luôn** là 1 trong 4 giá trị trên — không có giá
trị nào khác. Xem `ml/class_mapping.py`.

## Confidence

- `confidence` ∈ [0, 1] — xác suất softmax của nhãn được chọn (trước khi áp
  ngưỡng uncertain).
- Ngưỡng cụ thể (`confidence_threshold`) được chọn dựa trên validation set
  (Youden's J), ghi trong `ml/runs/<model_version>/eval_metrics.json` và báo
  cáo trong `ml/reports/cv_baseline_report.md`. Ngưỡng **khác nhau giữa các
  model_version** — Flutter/backend không được hardcode một số cố định, phải
  đọc từ metadata model đang dùng (xem mục "Model version" dưới).

## Error / uncertain behavior

| Tình huống | Behavior bắt buộc |
|---|---|
| `confidence < threshold` | `uncertain: true`, `label: null` — KHÔNG ép chọn 1 trong 4 nhãn |
| Ảnh không phải lá lúa (đất, tay, cây khác) | Model 4 lớp **không có lớp "không phải lá lúa"** — vẫn có thể trả `uncertain: true` nếu confidence thấp, nhưng **không đảm bảo** (RR-02, `docs/modules/03-computer-vision.md`). Đây là giới hạn MVP đã biết, không phải bug. |
| File không phải JPEG/PNG | Pipeline raise lỗi decode ảnh — app PHẢI validate định dạng trước khi gửi, không dựa vào model để báo lỗi format |
| Model load lỗi / thiếu checkpoint | Không có fallback tự động — đây là lỗi hệ thống, hiển thị "không thể phân tích ảnh lúc này", không hiển thị nhãn giả |

**Không claim robust non-rice detection** — chưa có benchmark riêng cho ảnh
không phải lá lúa (xem `ml/reports/cv_baseline_report.md` mục Limitations).

## Model version

- `model_version` = `run_name` sinh bởi `ml/train.py` (định dạng
  `mobilenetv2-baseline-<timestamp>`), cũng là `version_code` dự kiến cho
  bảng `public.cv_model_versions.version_code`.
- **Chưa có model nào ở trạng thái `active`** trong `cv_model_versions` —
  baseline hiện tại ở `status: draft`, cần team review trước khi promote.
  Flutter/backend không được giả định luôn có 1 model active.
- Khi có model `active`, app nên hiển thị kèm `model_version` ở đâu đó (vd.
  màn hình debug/settings) để hỗ trợ truy vết khi có khiếu nại kết quả sai.

## Không thuộc phạm vi M03 (không dựng nhầm kỳ vọng)

- Không có REST API endpoint cho CV trong bản này — tích hợp app↔model là
  việc của module Flutter khi được giao (on-device hoặc gọi service riêng,
  **chưa chốt** — xem RR-05 trong `docs/modules/03-computer-vision.md`).
- Không suy ra `carbon reduction` từ kết quả CV.
- Không sinh recommendation từ kết quả CV trong module này.
- Không có lớp "không phải lá lúa" riêng — xem bảng Error/uncertain ở trên.

## Tham khảo

- Đặc tả đầy đủ: [`modules/03-computer-vision.md`](modules/03-computer-vision.md)
- Báo cáo accuracy/confusion matrix thật: `ml/reports/cv_baseline_report.md`
- Schema DB: `supabase/migrations/20260907000000_baseline.sql` (bảng
  `plant_images`, `cv_model_versions`, `cv_inferences`, enum `disease_label`)

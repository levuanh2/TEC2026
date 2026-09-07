# SRS — AgriCarbon

**Software Requirements Specification**
Phiên bản: 0.1 · Ngày: 2026-09-07 · Deadline MVP: 20/09/2026
Tài liệu cha: [`PRD.md`](PRD.md)

Quy ước đánh số: `FR-1a-xx` (lớp Walking Skeleton), `FR-1b-xx` (lớp AI/CV),
`FR-1c-xx` (lớp trình bày/vận hành), `NFR-xx` (phi chức năng), `RB-xx` (ràng buộc).
Mỗi FR viết dạng "Hệ thống PHẢI…" kèm tiêu chí chấp nhận đo được.

---

## 1. Functional Requirements

### 1.1. Lớp 1a — Walking Skeleton (đường găng)

Module liên quan: [`01-mobile-app`](modules/01-mobile-app.md), [`02-carbon-engine`](modules/02-carbon-engine.md)

| ID | Yêu cầu | Tiêu chí chấp nhận |
|---|---|---|
| **FR-1a-01** | Hệ thống PHẢI cho nông dân tạo hồ sơ Thửa ruộng (Plot) gồm: tên/mã thửa, diện tích (ha), xã/huyện/tỉnh, HTX trực thuộc. | Tạo mới 1 Plot với diện tích 0,5 ha thành công; mở lại app thấy đúng dữ liệu. Diện tích ≤ 0 bị từ chối kèm thông báo tiếng Việt. |
| **FR-1a-02** | Hệ thống PHẢI cho ghi nhận hoạt động **giống**: tên giống, lượng giống gieo sạ (kg/ha), ngày gieo sạ, phương thức (sạ lan / sạ hàng / cấy). | Lưu được bản ghi; ngày gieo sạ trong tương lai bị từ chối. |
| **FR-1a-03** | Hệ thống PHẢI cho ghi nhận hoạt động **phân bón**: loại phân, lượng (kg), ngày bón, lần bón thứ mấy. | Ghi được ≥ 3 lần bón trong 1 vụ; tổng lượng N quy đổi hiển thị đúng tổng các lần. |
| **FR-1a-04** | Hệ thống PHẢI cho ghi nhận **chế độ nước tưới** ở mức bản ghi vụ: chọn **AWD (tưới ngập-khô xen kẽ)** hoặc **tưới ngập liên tục**; nếu chọn AWD thì ghi số lần rút nước và (tùy chọn) ngày rút nước. | Chọn AWD mà bỏ trống số lần rút nước → cảnh báo nhưng vẫn lưu được (dữ liệu đồng ruộng thường thiếu). Bản ghi lưu rõ chế độ nào. |
| **FR-1a-05** | Hệ thống PHẢI cho ghi nhận **thuốc BVTV** (tên/nhóm, lượng, ngày phun) và **xử lý rơm rạ** (đốt / vùi / lấy khỏi ruộng). | Lưu được; trường xử lý rơm rạ chỉ nhận 1 trong 3 giá trị hợp lệ. |
| **FR-1a-06** | Hệ thống PHẢI cho nhập và lưu toàn bộ dữ liệu ở FR-1a-01..05 **khi không có kết nối mạng**. | Bật chế độ máy bay, nhập đủ 1 vụ, tắt app, mở lại → dữ liệu còn nguyên. |
| **FR-1a-07** | Hệ thống PHẢI tự đồng bộ dữ liệu offline lên server khi có mạng trở lại, **không tạo bản ghi trùng và không mất bản ghi**. | Nhập offline 20 bản ghi, bật mạng → server nhận đúng 20, không hơn không kém. Đồng bộ lại lần 2 vẫn là 20 (idempotent). |
| **FR-1a-08** | Hệ thống PHẢI tính CO2e theo công thức `Activity Data × Emission Factor` và trả về **CO2e tổng (kg)** và **CO2e/kg lúa**. | Với bộ dữ liệu mẫu đã tính tay, kết quả API khớp phép tính tay (sai số ≤ 0,1%). |
| **FR-1a-09** | Hệ thống PHẢI tính riêng biệt hai kịch bản chế độ nước — **AWD** và **tưới ngập liên tục** — trên cùng một bộ Activity Data. | Cùng 1 lô, đổi chế độ nước → CO2e thay đổi và giải thích được thành phần nào thay đổi. |
| **FR-1a-10** | Hệ thống PHẢI hiển thị trên app kết quả CO2e/kg kèm **phân rã theo nguồn phát thải** (nước/CH4, phân bón/N2O, nhiên liệu, rơm rạ). | Màn hình kết quả liệt kê ≥ 4 dòng thành phần, tổng các dòng = tổng hiển thị. |
| **FR-1a-11** | Hệ thống PHẢI cho ghi **sản lượng thu hoạch** (kg) của lô, vì đây là mẫu số của mọi chỉ số "trên mỗi kg". | Chưa nhập sản lượng → hiển thị CO2e tổng và báo rõ "chưa có sản lượng nên chưa tính được CO2e/kg", **không** hiển thị số 0 hay số bịa. |
| **FR-1a-12** | Hệ thống PHẢI ghi lại nguồn hệ số đã dùng cho mỗi lần tính (phiên bản file config). | Kết quả tính trả kèm `ef_config_version`; đổi config → version trong kết quả đổi theo. |

### 1.2. Lớp 1b — AI/CV

Module liên quan: [`03-computer-vision`](modules/03-computer-vision.md), [`04-resource-dashboard`](modules/04-resource-dashboard.md), [`05-ai-recommendation`](modules/05-ai-recommendation.md)

| ID | Yêu cầu | Tiêu chí chấp nhận |
|---|---|---|
| **FR-1b-01** | Hệ thống PHẢI phân loại ảnh lá lúa thành 4 nhãn: **đạo ôn (blast)**, **bạc lá (bacterial blight)**, **đốm nâu (brown spot)**, **lá khỏe**. | Đưa 1 ảnh test → trả về đúng 1 nhãn kèm điểm tin cậy 0–1. |
| **FR-1b-02** | Hệ thống PHẢI được fine-tune bằng ảnh thực địa từ HTX pilot khi có ảnh. | Có bản ghi so sánh accuracy trước/sau fine-tune trong báo cáo `ml/`. Nếu chưa có ảnh thực địa, báo cáo PHẢI ghi rõ điều đó. |
| **FR-1b-03** | Hệ thống PHẢI công bố accuracy kèm **điều kiện đo** (tập test tách riêng, dataset public hay ảnh thực địa). | Báo cáo có confusion matrix + câu ghi rõ nguồn tập test. |
| **FR-1b-04** | Khi độ tin cậy dưới ngưỡng, hệ thống PHẢI trả về "không chắc chắn" thay vì ép chọn một nhãn. | Đưa ảnh không phải lá lúa → không trả nhãn bệnh với độ tin cậy cao. |
| **FR-1b-05** | Hệ thống PHẢI tính và hiển thị 4 chỉ số hiệu suất: **lít nước/kg, kg phân bón/kg, kg CO2e/kg, chi phí/kg**. | Cả 4 chỉ số hiện trên dashboard, mỗi chỉ số truy được về Activity Data gốc. |
| **FR-1b-06** | Hệ thống PHẢI cho so sánh các chỉ số ở FR-1b-05 giữa các thửa/lô trong cùng HTX. | Bảng/biểu đồ xếp được ≥ 3 lô theo carbon/kg, chỉ dùng dữ liệu đã có từ 1a. |
| **FR-1b-07** | Hệ thống PHẢI sinh khuyến nghị dạng rule-based khi chỉ số vượt benchmark. | Ví dụ: lô dùng N cao hơn benchmark 21% → sinh khuyến nghị giảm lượng N cụ thể. |
| **FR-1b-08** | Mỗi khuyến nghị PHẢI kèm **ước tính impact**: thay đổi CO2e (kg và %) và thay đổi chi phí. | Không có khuyến nghị nào hiển thị mà thiếu 2 con số impact. Kiểm bằng cách duyệt toàn bộ khuyến nghị sinh ra trên dữ liệu demo. |
| **FR-1b-09** | Hệ thống PHẢI ghi rõ benchmark đang so sánh là gì (trung bình HTX / dải tham chiếu vùng) và nguồn của benchmark đó. | Mỗi khuyến nghị có dòng "so với: …". |

### 1.3. Lớp 1c — Trình bày/vận hành (**được phép cắt xuống mock**)

Module liên quan: [`06-web-dashboard`](modules/06-web-dashboard.md), [`07-mrv-export`](modules/07-mrv-export.md)

| ID | Yêu cầu | Tiêu chí chấp nhận |
|---|---|---|
| **FR-1c-01** | Hệ thống PHẢI cho duyệt dữ liệu theo cấp bậc **Farm → Plot → Crop → Batch → Activity → Carbon**. | Từ 1 Farm bấm xuống được tới 1 bản ghi Activity và số Carbon tương ứng. |
| **FR-1c-02** | Hệ thống PHẢI tổng hợp dữ liệu nhiều hộ trong 1 HTX vào một màn hình. | Hiện được tổng CO2e và CO2e/kg trung bình cấp HTX từ ≥ 3 hộ. |
| **FR-1c-03** | Hệ thống PHẢI phân quyền 3 vai trò: **Nông dân** (chỉ nhập liệu, chỉ thấy dữ liệu của mình), **Quản lý HTX** (xem tổng hợp cấp HTX), **Doanh nghiệp / Cơ quan quản lý** (xem toàn vùng). | Đăng nhập vai Nông dân → không truy cập được dữ liệu hộ khác, kể cả khi gọi thẳng API bằng id của hộ đó. |
| **FR-1c-04** | Hệ thống PHẢI ghi nhận ai tạo/sửa bản ghi và thời điểm. | Mỗi bản ghi có `created_by`, `created_at`, `updated_at`. |
| **FR-1c-05** | Hệ thống PHẢI xuất báo cáo PDF hoặc Excel có bố cục theo đúng **6 bước MRV** (Chuẩn bị – Đăng ký – Thiết lập đường cơ sở – Đo đạc – Báo cáo – Thẩm định). | File xuất ra có đủ 6 mục đúng tên, đúng thứ tự; mục nào chưa có dữ liệu ghi "chưa có dữ liệu", không bỏ trống lặng lẽ. |
| **FR-1c-06** | Báo cáo xuất ra PHẢI ghi rõ phiên bản bộ hệ số phát thải đã dùng và ngày xuất. | Trang đầu báo cáo có `ef_config_version` và ngày. |
| **FR-1c-07** | Báo cáo PHẢI đánh dấu rõ các số liệu **chưa chốt chính thức** (đặc biệt giá tín chỉ carbon). | Nếu báo cáo có phần quy đổi tiền, phải có nhãn "chưa chốt chính thức"; nếu không có giá thì phần đó bị ẩn hoàn toàn. |

---

## 2. Non-functional requirements

| ID | Yêu cầu | Tiêu chí chấp nhận |
|---|---|---|
| **NFR-01 · Offline-first (bắt buộc)** | App PHẢI dùng được đầy đủ chức năng nhập liệu khi mất mạng; mạng chỉ cần cho đồng bộ và tính CO2e phía server. Lý do: vùng sóng yếu ĐBSCL — đây là điều kiện sống còn cho việc dùng thật, không phải tính năng "nice to have". | Chế độ máy bay: nhập, sửa, xóa bản ghi đều chạy. Hàng đợi đồng bộ sống sót qua việc tắt/mở lại app. |
| **NFR-02 · Độ tin cậy số liệu CO2e** | Mọi kết quả CO2e PHẢI truy ngược được: số hiển thị → công thức → hệ số → nguồn trích dẫn. **Đây là phần hội đồng chấm thi sẽ hỏi sâu nhất.** | Chọn bất kỳ con số nào trên màn hình, chỉ ra được trong ≤ 3 bước nó đến từ đâu. Carbon Engine có unit test đối chiếu ít nhất 1 ca tính tay. |
| **NFR-03 · Không bịa số** | Khi thiếu dữ liệu đầu vào (vd chưa có sản lượng, hệ số còn `null`), hệ thống PHẢI báo thiếu dữ liệu thay vì dùng giá trị mặc định ngầm. | Xóa sản lượng → UI báo "chưa tính được CO2e/kg", không hiện 0. Hệ số `null` → API trả lỗi rõ ràng, không tính bừa. |
| **NFR-04 · Khả năng mở rộng giai đoạn 2/3/4** | Kiến trúc PHẢI cho phép thêm What-if Simulation, Farm Map, Weather, RAG Chatbot mà **không phải viết lại lớp 1a**. | Carbon Engine nhận Activity Data qua một hàm/endpoint thuần (không phụ thuộc UI) → What-if chỉ cần gọi lại với input giả định. Data model đã có sẵn Batch/Crop cho traceability sau này. |
| **NFR-05 · Hiệu năng** | Tính CO2e cho 1 lô PHẢI trả về < 3 giây (đã có mạng). | Đo trên thiết bị demo thật, 10 lần liên tiếp. |
| **NFR-06 · Dễ dùng với nông dân** | Form nhập liệu PHẢI dùng thuật ngữ khuyến nông ("1 phải 5 giảm", "rút nước"), không dùng thuật ngữ carbon hàn lâm ở màn hình nhập. | Người ngoài nhóm hoàn tất 1 lượt nhập trong < 2 phút mà không cần hướng dẫn. |
| **NFR-07 · Bảo mật dữ liệu người dùng** | Dữ liệu canh tác của một hộ PHẢI không truy cập được bởi hộ khác, kể cả qua gọi API trực tiếp. | Kiểm bằng cách gọi API bằng token vai Nông dân với id lô của hộ khác → trả 403. |
| **NFR-08 · Ngôn ngữ** | Toàn bộ giao diện người dùng cuối PHẢI bằng tiếng Việt. | Rà toàn bộ màn hình, không còn chuỗi tiếng Anh lọt ra ngoài. |

---

## 3. Data model mức khái niệm

Khung phân cấp theo đúng mục 8 tài liệu gốc:

```text
Farm  (nông trại / hộ)
 └── Plot  (thửa ruộng)
      └── Crop  (vụ canh tác trên thửa đó)
           └── Batch  (lô thu hoạch)
                └── Activity  (hoạt động canh tác)
                     └── Carbon  (kết quả tính phát thải)
```

### 3.1. Thực thể

| Thực thể | Ý nghĩa | Trường chính |
|---|---|---|
| **Farm** | Nông hộ hoặc trang trại, thuộc 1 HTX | `id`, `name`, `owner_user_id`, `cooperative_id`, `commune`, `district`, `province` |
| **Plot** | Thửa ruộng cụ thể | `id`, `farm_id`, `code`, `area_ha`, `soil_type` (tùy chọn), `geo` (tùy chọn, để dành Farm Map giai đoạn 2) |
| **Crop** | Một vụ canh tác trên một thửa | `id`, `plot_id`, `season` (Đông Xuân / Hè Thu / Thu Đông), `variety` (giống), `sowing_date`, `harvest_date`, `yield_kg` |
| **Batch** | Lô thu hoạch (mẫu số cho chỉ số per-kg và nền cho traceability giai đoạn 4) | `id`, `crop_id`, `batch_code`, `quantity_kg`, `harvest_date` |
| **Activity** | Một hoạt động canh tác đã thực hiện | xem §3.2 |
| **Carbon** | Kết quả tính cho 1 Crop/Batch | `id`, `crop_id`, `batch_id`, `co2e_total_kg`, `co2e_per_kg`, `breakdown` (theo nguồn phát thải), `water_regime_scenario`, `ef_config_version`, `calculated_at` |

### 3.2. Activity — chi tiết theo khung "1 phải 5 giảm"

`Activity` dùng chung các trường: `id`, `crop_id`, `type`, `date`, `note`,
`created_by`, `created_at`, `updated_at`, `sync_state`.
Trường riêng theo `type`:

| `type` | Trường riêng | Ghi chú |
|---|---|---|
| `seed` (giống) | `variety`, `seed_rate_kg_per_ha`, `sowing_method` (sạ lan / sạ hàng / cấy) | "Giảm giống" |
| `fertilizer` (phân bón) | `fertilizer_type`, `amount_kg`, `n_content_pct` (tùy chọn), `application_no` | "Giảm phân" — lượng N là đầu vào chính cho N2O |
| `water` (nước tưới) | `regime` (`awd` / `continuous_flooding`), `drainage_events` (số lần rút nước), `drainage_dates[]` (tùy chọn), `pump_fuel_litre` (tùy chọn) | "Giảm nước" — **biến số carbon lớn nhất** |
| `pesticide` (thuốc BVTV) | `product_group`, `amount`, `unit` | "Giảm thuốc" |
| `straw` (xử lý rơm rạ) | `method` (`burned` / `incorporated` / `removed`), `amount_kg` (tùy chọn) | Ảnh hưởng trực tiếp phát thải |
| `harvest` (thu hoạch) | `yield_kg`, `loss_kg` (tùy chọn) | "Giảm thất thoát sau thu hoạch"; `yield_kg` là mẫu số của mọi chỉ số per-kg |

> **Lưu ý thiết kế:** `water.regime` đặt ở mức Activity nhưng thực tế là thuộc tính của cả vụ.
> Nếu một vụ có nhiều bản ghi `water` mâu thuẫn nhau về `regime`, Carbon Engine PHẢI báo lỗi
> rõ ràng thay vì tự chọn một giá trị.

### 3.3. Người dùng & phân quyền

| Thực thể | Trường |
|---|---|
| **User** | `id`, `name`, `phone`, `role`, `cooperative_id`, `farm_id` (nếu là nông dân) |
| **Cooperative** (HTX) | `id`, `name`, `province`, `enterprise_id` (nếu thuộc chuỗi liên kết) |

`role` ∈ { `farmer`, `coop_manager`, `enterprise` } — tương ứng FR-1c-03.

---

## 4. API contract nháp — luồng 1a

> Đây là **hợp đồng tối thiểu để ra CO2e/kg**. Chốt trước khi Người A và Người B code song song,
> vì đây là điểm duy nhất hai layer chạm nhau ở lớp 1a.

### 4.1. `POST /v1/sync` — đẩy dữ liệu offline lên

Request:

```json
{
  "device_id": "abc-123",
  "activities": [
    {
      "client_id": "uuid-sinh-tren-may",
      "crop_id": "crop-001",
      "type": "fertilizer",
      "date": "2026-08-14",
      "payload": { "fertilizer_type": "Urea", "amount_kg": 120, "application_no": 2 },
      "created_at": "2026-08-14T07:12:00+07:00"
    }
  ]
}
```

Response:

```json
{
  "accepted": 1,
  "duplicated": 0,
  "rejected": [],
  "server_ids": { "uuid-sinh-tren-may": "act-9001" }
}
```

**Idempotency:** server khử trùng lặp theo `client_id`. Gửi lại cùng payload → `duplicated`
tăng, `accepted` = 0, không tạo bản ghi mới (FR-1a-07).

### 4.2. `POST /v1/carbon/calculate` — tính CO2e

Request:

```json
{
  "crop_id": "crop-001",
  "water_regime_scenario": "awd"
}
```

`water_regime_scenario` ∈ { `awd`, `continuous_flooding`, `as_recorded` }.
`as_recorded` = dùng đúng chế độ nông dân đã ghi; hai giá trị còn lại dùng để so sánh kịch bản (FR-1a-09).

Response:

```json
{
  "crop_id": "crop-001",
  "water_regime_scenario": "awd",
  "co2e_total_kg": 4820.5,
  "yield_kg": 3100.0,
  "co2e_per_kg": 1.555,
  "breakdown": [
    { "source": "ch4_flooding", "co2e_kg": 3600.0 },
    { "source": "n2o_fertilizer", "co2e_kg": 780.5 },
    { "source": "straw_management", "co2e_kg": 320.0 },
    { "source": "fuel_pumping", "co2e_kg": 120.0 }
  ],
  "ef_config_version": "0.1.0-draft",
  "calculated_at": "2026-09-07T10:00:00+07:00",
  "warnings": ["Hệ số ch4_flooding chưa đối chiếu MRV chính thức (OI-02)."]
}
```

**Quy tắc lỗi (NFR-03):**

| Tình huống | Phản hồi |
|---|---|
| Chưa có `yield_kg` | HTTP 200, `co2e_per_kg: null`, `warnings` giải thích thiếu sản lượng. **Không trả 0.** |
| Hệ số cần dùng đang `null` trong config | HTTP 422, thông báo rõ hệ số nào thiếu. **Không tự đặt mặc định.** |
| Nhiều bản ghi `water` mâu thuẫn `regime` | HTTP 422, liệt kê các bản ghi mâu thuẫn. |

### 4.3. `GET /v1/crops/{crop_id}/carbon` — lấy kết quả đã tính

Trả về bản ghi `Carbon` gần nhất, cấu trúc giống response §4.2. Dùng để app hiển thị lại
khi offline mà không phải tính lại.

---

## 5. Ràng buộc

| ID | Ràng buộc |
|---|---|
| **RB-01** | **Emission Factor và giá tín chỉ carbon PHẢI nằm trong file config có nguồn trích dẫn và ngày review** (`backend/config/emission_factors.yaml`). Không hardcode magic number trong logic tính toán. Code review sẽ từ chối mọi hằng số phát thải viết thẳng trong hàm tính. |
| **RB-02** | Số liệu tài liệu gốc ghi **"chưa chốt"** PHẢI được trình bày đúng như vậy ở mọi nơi: giá tín chỉ carbon (TCAF đang định giá, ~20 USD **chưa xác nhận**), và API RiceMoRe/FarMoRe (**chưa có API mở**, chỉ là hướng hợp tác tương lai). |
| **RB-03** | Không đổi crop (lúa gạo) và không đổi tên 6 bước MRV. Dùng đúng tên **Bộ Nông nghiệp và Môi trường**. |
| **RB-04** | Thứ tự thực hiện là 1a → 1b → 1c. Khi thiếu thời gian, cắt 1c trước, **không bao giờ cắt 1a**. |
| **RB-05** | License từng dataset ảnh phải được xác nhận trước khi train (`ml/datasets/README.md`). |
| **RB-06** | Mọi con số accuracy CV công bố phải kèm điều kiện đo (dataset public hay ảnh thực địa). |

---

## 6. Truy vết FR ↔ Module

| Module | FR phụ trách |
|---|---|
| [`01-mobile-app`](modules/01-mobile-app.md) | FR-1a-01 … FR-1a-07, FR-1a-10, FR-1a-11 |
| [`02-carbon-engine`](modules/02-carbon-engine.md) | FR-1a-08, FR-1a-09, FR-1a-12 |
| [`03-computer-vision`](modules/03-computer-vision.md) | FR-1b-01 … FR-1b-04 |
| [`04-resource-dashboard`](modules/04-resource-dashboard.md) | FR-1b-05, FR-1b-06 |
| [`05-ai-recommendation`](modules/05-ai-recommendation.md) | FR-1b-07 … FR-1b-09 |
| [`06-web-dashboard`](modules/06-web-dashboard.md) | FR-1c-01 … FR-1c-04 |
| [`07-mrv-export`](modules/07-mrv-export.md) | FR-1c-05 … FR-1c-07 |

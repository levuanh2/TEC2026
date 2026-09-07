# PRD — AgriCarbon

**Product Requirements Document**
Dự án: AgriCarbon — nền tảng số hóa carbon & hiệu suất tài nguyên cho canh tác lúa gạo ĐBSCL
Cuộc thi: TEC 2026 (TDMU Entrepreneurship Competition), lĩnh vực Nông nghiệp – Môi trường – Năng lượng
Phiên bản: 0.1 · Ngày: 2026-09-07 · Deadline MVP: **20/09/2026**

---

## 1. Bối cảnh & vấn đề

### 1.1. Sức ép chính sách

Tại COP26, Chính phủ Việt Nam cam kết đưa phát thải ròng về "0" (Net-Zero) vào năm 2050.
Song song, các thị trường nhập khẩu tỷ đô (EU, Mỹ) dựng "hàng rào xanh": **Cơ chế điều
chỉnh biên giới carbon (CBAM)** và **Quy định chống phá rừng (EUDR)**. Ngành nông nghiệp
xuất khẩu — đặc biệt lúa gạo — đứng trước yêu cầu phải chứng minh và minh bạch được
**Dấu chân Carbon (Carbon Footprint) trên từng lô hàng**, nếu không sẽ bị áp thuế trừng
phạt hoặc mất thị phần.

Ở chiều trong nước, bài toán gần như đã được nhà nước "đặt hàng sẵn":

- **Đề án "Phát triển bền vững 1 triệu ha chuyên canh lúa chất lượng cao, phát thải thấp
  gắn với tăng trưởng xanh vùng ĐBSCL đến 2030"** — Thủ tướng phê duyệt 27/11/2023. Đến
  4/2026 đã đạt ~942.000 ha; giai đoạn 2026–2030 mở rộng thêm ~820.000 ha.
- **Quy trình MRV 6 bước** (Quyết định 4801/QĐ-BNNMT, 14/11/2025):
  **Chuẩn bị – Đăng ký – Thiết lập đường cơ sở – Đo đạc – Báo cáo – Thẩm định**.
  Thí điểm đến hết 31/12/2026, quy mô 300.000 ha vụ Đông Xuân 2025–2026.
- **Cơ chế tài chính TCAF (World Bank)** — chi trả dựa trên kết quả giảm phát thải, tổng
  khoảng 33,3–40 triệu USD cho toàn Đề án.
- **Kỹ thuật lõi:** "1 phải 5 giảm" — giảm giống, giảm phân, giảm thuốc, giảm nước (tưới
  ngập-khô xen kẽ **AWD**), giảm thất thoát sau thu hoạch, xử lý rơm rạ.

> Sau sáp nhập, tên gọi chính thức là **Bộ Nông nghiệp và Môi trường** (không còn Bộ NN&PTNT riêng).

### 1.2. Cách làm hiện tại — chắp vá

Dù sức ép pháp lý lớn, thực tế vận hành vẫn thủ công:

- Nông dân ghi chép vật tư (phân bón, điện, nước) vào **sổ tay giấy** hoặc file Excel.
- Dữ liệu **rời rạc, không có tiêu chuẩn tính toán, không có bằng chứng chống gian lận**.
- Khi hàng cập cảng, để đối tác EU chấp nhận, doanh nghiệp xuất khẩu phải **chi hàng trăm
  triệu đồng và mất nhiều tháng** thuê tổ chức kiểm định bên thứ ba (SGS, Control Union)
  xuống tận nông trại rà soát sổ sách thủ công.
- Doanh nghiệp thu mua phải tự tổng hợp dữ liệu từ nhiều hộ/HTX bằng tay.

### 1.3. Khoảng trống

MRV 6 bước cần được số hóa cho hàng trăm nghìn hộ dân/HTX, nhưng chưa có công cụ nào làm
đúng việc đó ở **cấp nông hộ**, với đơn vị đo **trên mỗi kilogram sản phẩm**.

---

## 2. Đối tượng người dùng

| Nhóm | Vai trò trong sản phẩm | Ưu tiên |
|---|---|---|
| **Nông hộ / HTX trồng lúa ĐBSCL** | Người nhập liệu chính; người nhận khuyến nghị và thấy CO2e/kg của chính mình | **Chính** |
| **Quản lý HTX** | Xem tổng hợp cấp HTX, so sánh giữa các hộ thành viên | Chính |
| **Doanh nghiệp thu mua / xuất khẩu** | Tổng hợp dữ liệu carbon toàn vùng liên kết, phục vụ hồ sơ xuất khẩu | Thứ cấp |
| **Cơ quan quản lý nhà nước** | Dùng dữ liệu phục vụ báo cáo MRV chính thức trên diện rộng | Thứ cấp |

**Ràng buộc người dùng thực tế quyết định thiết kế:**
sóng di động ĐBSCL yếu và chập chờn → app **bắt buộc offline-first**; người dùng lớn tuổi,
ngại gõ chữ → form phải ngắn, thuật ngữ dùng đúng ngôn ngữ khuyến nông ("1 phải 5 giảm"),
không dùng thuật ngữ carbon hàn lâm ở màn hình nhập liệu.

---

## 3. Định vị sản phẩm & khác biệt hóa

> **Định vị:** *"Carbon + hiệu suất tài nguyên tính trên mỗi kg sản phẩm, ở cấp nông hộ,
> có thị giác máy tính (Computer Vision) hỗ trợ ra quyết định."*
>
> AgriCarbon là **công cụ hỗ trợ số hóa quy trình MRV chính thức**, không phải một
> "carbon calculator" chung chung.

### 3.1. So với đối thủ

| Nhóm đối thủ | Đại diện | Họ làm gì | Khoảng trống họ để lại |
|---|---|---|---|
| Nhật ký / truy xuất nguồn gốc | **FaceFarm** (Sorimachi VN) | Nhật ký sản xuất, mã QR, mã vùng trồng, đã triển khai 63 tỉnh thành | Không tính CO2e/kg, không có CV, không tối ưu tài nguyên — dừng ở ghi chép |
| MRV / tín chỉ carbon cấp vùng | **CarbonFarm, Regrow**, Green Carbon, Spiro, Boomitra | Đo phát thải cấp vùng bằng vệ tinh/mô hình để bán tín chỉ | Hướng doanh nghiệp/tín chỉ, không vận hành ở cấp nông hộ, không có CV, không "per kg" |

### 3.2. Ba điểm khác biệt cốt lõi

1. **Chỉ số "trên mỗi kilogram sản phẩm" ở cấp nông hộ** — CO2e/kg, nước/kg, phân bón/kg:
   đơn vị trực quan, so sánh được giữa các vụ và giữa các hộ trong cùng HTX.
2. **Computer Vision là mắt xích trong vòng lặp tối ưu**, không chỉ là "app nhận bệnh":
   phát hiện sớm bệnh lá → giảm thuốc/phân dư thừa → trực tiếp giảm carbon và chi phí.
3. **Bám sát khung MRV 6 bước đang được nhà nước triển khai thật** — dữ liệu thu thập
   dùng được trực tiếp cho báo cáo MRV chính thức, không phải tiêu chí tự đặt ra.

### 3.3. Vòng lặp sản phẩm

```text
MEASURE  ->  UNDERSTAND  ->  OPTIMIZE  ->  ACT  ->  (quay lại MEASURE)
```

Chi tiết luồng dữ liệu: xem [`architecture.md`](architecture.md).

---

## 4. Mục tiêu MVP theo từng lớp

MVP chia 3 lớp theo đúng thứ tự phụ thuộc kỹ thuật. **Làm tuần tự 1a → 1b → 1c, không
làm song song dàn trải.**

### 4.1. Lớp 1a — Walking Skeleton (đường găng, ưu tiên tuyệt đối)

**Mục tiêu:** có một pipeline chạy được end-to-end ra con số CO2e/kg, dù giao diện còn thô.
Chưa xong lớp này thì các lớp sau không có dữ liệu để chạy.

Gồm: `01-mobile-app` (ghi nhật ký tối giản, offline-first) + `02-carbon-engine`.

**Definition of Done — lớp 1a**

- [ ] Nhập được 1 vụ canh tác đầy đủ trên app khi **tắt hoàn toàn mạng**, dữ liệu không mất.
- [ ] Bật mạng → dữ liệu tự đồng bộ lên backend, không trùng lặp, không mất bản ghi.
- [ ] Backend trả về **CO2e tổng và CO2e/kg** cho lô đó, app hiển thị được.
- [ ] Tính được **hai kịch bản riêng biệt: AWD và tưới ngập liên tục**, ra hai con số khác nhau.
- [ ] Mọi hệ số phát thải nằm trong `backend/config/emission_factors.yaml` kèm nguồn trích
      dẫn — **không có magic number nào trong code tính toán**.
- [ ] Có bộ test kiểm chứng công thức với ít nhất 1 ca tính tay đối chiếu được.
- [ ] Giải thích được trước hội đồng: "số này tính ra sao, dựa hệ số nào, khớp MRV chỗ nào".

### 4.2. Lớp 1b — AI/CV (làm ngay sau khi 1a chạy ổn)

**Mục tiêu:** thể hiện đúng chủ đề AI của cuộc thi. Nếu MVP chỉ có con số CO2e mà không có
yếu tố AI/CV thì phần "công nghệ" bị đánh giá mỏng.

Gồm: `03-computer-vision` + `04-resource-dashboard` + `05-ai-recommendation`.

**Definition of Done — lớp 1b**

- [ ] Chụp/chọn 1 ảnh lá lúa → model trả về nhãn bệnh (đạo ôn / bạc lá / đốm nâu / khỏe)
      kèm độ tin cậy.
- [ ] Có báo cáo accuracy + confusion matrix trên tập test **tách riêng**, ghi rõ đo trên
      dataset public hay ảnh thực địa.
- [ ] Dashboard hiển thị đủ 4 chỉ số: **nước/kg, phân bón/kg, carbon/kg, cost/kg**, tính từ
      chính dữ liệu 1a — không thu thập thêm.
- [ ] So sánh được giữa các lô/hộ trong cùng HTX (Efficiency Map hoặc bảng xếp hạng).
- [ ] Mỗi khuyến nghị **luôn kèm ước tính impact** (giảm bao nhiêu kg CO2e, bao nhiêu chi phí),
      không có lời khuyên suông.

### 4.3. Lớp 1c — Trình bày/vận hành (làm cuối, **được phép cắt xuống mock**)

**Mục tiêu:** kể trọn câu chuyện sản phẩm khi demo. Đây là phần "đẹp khi demo" nhưng không
phải bằng chứng kỹ thuật cốt lõi.

Gồm: `06-web-dashboard` + `07-mrv-export`.

**Definition of Done — lớp 1c**

- [ ] Xem được dữ liệu theo cấp bậc **Farm → Plot → Crop → Batch → Activity → Carbon**.
- [ ] Phân quyền 3 vai trò: Nông dân (chỉ nhập liệu) / Quản lý HTX (tổng hợp cấp HTX) /
      Doanh nghiệp – Cơ quan quản lý (toàn vùng).
- [ ] Xuất được báo cáo PDF hoặc Excel bố cục theo đúng **6 bước MRV**.

**Quy tắc cắt scope:** nếu đến 15/09/2026 mà 1b chưa xong, cắt 1c xuống bản mock tĩnh
(HTML/slide) và dồn toàn bộ thời gian còn lại cho 1a + 1b. **Không bao giờ cắt 1a.**

---

## 5. Ngoài phạm vi MVP

Các giai đoạn dưới đây **chỉ nêu trong roadmap dài hạn để pitch**, không dựng code trong MVP.

### Giai đoạn 2 — Khác biệt hóa

| Tính năng | Vì sao chưa làm trong MVP |
|---|---|
| Evidence / Anti-fraud (camera bắt buộc + GPS + timestamp, audit trail, phát hiện anomaly) | Cần 1a chạy ổn định trước mới có luồng dữ liệu để gắn bằng chứng vào |
| **What-if Simulation** ("nếu giảm phân N 15%?", "nếu chuyển sang AWD?") | Phụ thuộc hoàn toàn vào độ tin cậy của Carbon Engine; mô phỏng trên hệ số chưa chốt sẽ ra kết quả sai lệch |
| **Farm/Field Map & Historical Data** (bản đồ hiệu suất xanh/vàng/đỏ, benchmark vụ trước) | Cần ít nhất 1 vụ dữ liệu thật mới có lịch sử để so sánh — không có dữ liệu thì bản đồ rỗng |
| **Weather Integration** (đối chiếu lượng mưa với lượng nước tưới) | Là lớp làm giàu khuyến nghị, không phải điều kiện cần để ra CO2e/kg |

### Giai đoạn 3 — RAG Chatbot chính sách/MRV

Trợ lý hỏi-đáp về quy trình MRV, điều kiện tham gia Đề án 1 triệu ha, giải thích số liệu
carbon của chính lô đất người dùng; nguồn tri thức là văn bản chính sách công khai, luôn
cite nguồn, không hallucinate.
**Vì sao chưa làm:** cần knowledge base đã chuẩn bị và cần 1a/1b có dữ liệu động để trả lời
cá nhân hóa. Làm sớm sẽ ra chatbot trả lời chung chung — phản tác dụng khi giám khảo tự test.

### Giai đoạn 4 — Mở rộng tương lai

Traceability/Batch Management · Cost Management đầy đủ · IoT cảm biến mực nước · Notification
& Alerts (Zalo OA/SMS) · Marketplace kết nối bao tiêu · Đa ngôn ngữ & nhập liệu giọng nói.
**Vì sao chưa làm:** đúng tinh thần không ôm IoT đầy đủ, blockchain, drone, satellite cùng lúc
trong một đồ án vài tháng, 2 người code.

### Các chức năng bổ sung đã khảo sát nhưng hoãn

Đăng nhập/thông báo Zalo OA · Lịch mùa vụ tự động (Growth Stage Reminder) · Leaderboard ẩn
danh trong HTX · Voice-to-form tiếng Việt · OCR sổ ghi chép giấy cũ · Cảnh báo bất thường
qua Zalo/SMS. Đều khả thi và giá trị cao, nhưng **không nằm trên đường găng ra CO2e/kg**
nên đẩy sau MVP.

---

## 6. Success metrics cho demo/pitch

| # | Chỉ số | Ngưỡng mục tiêu | Đo thế nào |
|---|---|---|---|
| M1 | Thời gian từ lúc bấm "Lưu" đến khi hiện CO2e/kg (đã có mạng) | **< 3 giây** | Bấm giờ trên thiết bị demo thật |
| M2 | Thời gian hoàn tất 1 lượt nhập nhật ký của nông dân | **< 2 phút** | Cho 1 người ngoài nhóm thử, bấm giờ |
| M3 | Tỷ lệ mất dữ liệu khi nhập offline rồi đồng bộ | **0%** trên 20 bản ghi thử | Nhập offline 20 bản ghi, bật mạng, đối chiếu |
| M4 | Accuracy CV trên tập test tách riêng | **≥ 85%** trên dataset public (ghi rõ chưa đại diện điều kiện đồng ruộng) | Confusion matrix trong báo cáo `ml/` |
| M5 | Chênh lệch CO2e/kg giữa AWD và tưới ngập liên tục trên cùng bộ dữ liệu | Ra được **con số cụ thể, giải thích được** | Chạy 2 kịch bản trên cùng 1 lô |
| M6 | Câu chuyện Before/After minh họa impact | **≥ 1 kịch bản** có số liệu (vd: giảm N 15% → giảm X kg CO2e + tiết kiệm Y đồng) | Tính từ dữ liệu demo, ghi rõ là kịch bản minh họa |
| M7 | Trả lời được câu hỏi "số này ở đâu ra" | Truy được từ số hiển thị → hệ số → nguồn trích dẫn trong config | Demo trực tiếp file `emission_factors.yaml` |

> M4, M6 là các con số dễ bị hiểu nhầm nhất khi pitch. Luôn nói rõ điều kiện đo.

---

## 7. Rủi ro đã biết

| # | Rủi ro | Ảnh hưởng | Hướng xử lý |
|---|---|---|---|
| R1 | **Chưa chốt HTX pilot** (Tiến Thuận – Cần Thơ, Phú Hòa – An Giang mới là kênh tiềm năng) | Không có ảnh thực địa, không có dữ liệu thật để kiểm chứng | Nếu sau 3 tuần đầu không xin được HTX nào → thu hẹp xuống prototype chạy trên dataset public + demo, **giữ nguyên cây lúa, không đổi crop** |
| R2 | **Chưa có ảnh thực địa cho CV** | Model đo trên dataset public không đại diện điều kiện đồng ruộng (nắng gắt, nền lẫn, ảnh rung) | Luôn báo cáo accuracy kèm điều kiện đo; không trình bày như độ chính xác thực địa |
| R3 | **Giá tín chỉ carbon chưa chốt chính thức** (TCAF đang định giá; con số ~20 USD chưa xác nhận) | Nếu quy đổi ra tiền sẽ thành số liệu sai | Để ở config `status: NOT_CONFIRMED`; UI hiển thị nhãn "chưa chốt" hoặc ẩn phần quy đổi tiền |
| R4 | **RiceMoRe/FarMoRe chưa có API mở** | Không tích hợp được như đã hình dung | Khi pitch nói rõ đây là hướng hợp tác tương lai, **không nói "đã kết nối"**; dùng FarMoRe để đối chiếu thủ công |
| R5 | **Emission Factor chưa đối chiếu MRV chính thức**; tài liệu gốc ghi 1,04 kg CO2/kg và dải 2,29–3,72 kg CO2e/kg chưa nhất quán về phạm vi | Đây chính là phần giám khảo hỏi sâu nhất | Ghi thành open issue OI-01/OI-02 trong `emission_factors.yaml`, xử lý trước 15/09/2026 |
| R6 | **Đội chỉ có 2 người code**, deadline 20/09/2026 | Dễ vỡ tiến độ nếu làm song song dàn trải | Làm tuần tự 1a → 1b → 1c; quy tắc cắt scope ở §4.3 |
| R7 | License dataset chưa xác nhận từng bộ | Rủi ro pháp lý khi công bố | Checklist trong `ml/datasets/README.md`, xác nhận trước khi train |

---

## 8. Tài liệu liên quan

- [`SRS.md`](SRS.md) — yêu cầu phần mềm chi tiết, data model, API contract
- [`architecture.md`](architecture.md) — kiến trúc & luồng dữ liệu
- [`mrv-mapping.md`](mrv-mapping.md) — map 6 bước MRV ↔ module
- [`modules/`](modules/) — 7 đặc tả module

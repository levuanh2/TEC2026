# AgriCarbon v2 — Quyết định Scope & Roadmap Tính năng
## TEC 2026 — Lĩnh vực Nông nghiệp / Carbon / Resource Efficiency

> **Trạng thái:** Đã chốt hướng đi (crop + concept). Chưa chốt chi tiết kỹ thuật/dataset/pilot.
> Tài liệu này kế thừa từ bản Working Draft "AGRICULTURE - CARBON - RESOURCE EFFICIENCY" trước đó, bổ sung kết quả research và quyết định cuối cùng.

---

# 1. Quyết định: Chọn cây LÚA GẠO — vùng ĐBSCL

Sau khi so sánh 3 lựa chọn (Cà phê / Lúa gạo / Thanh long) theo 5 tiêu chí — độ sẵn có dataset, mức độ khớp chính sách, khả năng tiếp cận pilot thực địa, mức độ cạnh tranh, và độ khả thi với nguồn lực sinh viên — nhóm chốt:

> **Crop: Lúa (Rice) — Region: Đồng bằng sông Cửu Long (ĐBSCL)**

## Vì sao chọn lúa thay vì cà phê / thanh long?

| Tiêu chí | Lúa gạo (ĐBSCL) | Cà phê (Tây Nguyên) | Thanh long |
|---|---|---|---|
| Dataset ảnh public | Nhiều bộ lớn (5.932–19.000 ảnh, disease) | Lớn nhưng chủ yếu Arabica (VN chủ yếu Robusta → domain gap) | Rất nghèo (26–4.518 ảnh), gần như không có bộ Việt Nam |
| Khớp chính sách/thời sự | **Rất cao** — Đề án 1 triệu ha + MRV chính thức + tài chính TCAF | Cao — áp lực EUDR, nhưng EU vừa hoãn hạn (30/12/2026–30/6/2027) | Thấp — dự án UNDP thí điểm đã kết thúc từ 2023 |
| Khả năng tiếp cận pilot | **Cao** — HTX thí điểm cụ thể, app FarMoRe/Kobo miễn phí, IRRI hỗ trợ | Trung bình — qua HTX/doanh nghiệp xuất khẩu, khó hơn | Thấp — chủ yếu Bình Thuận, ít đầu mối |
| Cạnh tranh / khoảng trống | Đông ở MRV cấp vùng (CarbonFarm, Regrow…) nhưng "per kg + CV cấp nông hộ" còn trống | Truy xuất EUDR đã đông (Nescafé Plan, IDH) | Ít đối thủ nhưng cầu thị trường nhỏ |
| Phù hợp nguồn lực sinh viên (vài tháng, ít ngân sách) | **Có** | Có, nhưng rủi ro domain gap cao hơn | Rủi ro cao, cần tự thu thập nhiều |

**Kết luận:** Lúa gạo là lựa chọn duy nhất có cả (1) dataset sẵn, (2) chính sách nhà nước đang cần đúng giải pháp này, và (3) kênh pilot thực tế rẻ/nhanh — phù hợp nhất cho một đồ án có deadline vài tháng, ngân sách hạn chế.

## Bối cảnh chính sách làm nền cho sản phẩm

- **Đề án "Phát triển bền vững 1 triệu ha chuyên canh lúa chất lượng cao, phát thải thấp gắn với tăng trưởng xanh vùng ĐBSCL đến 2030"** — Thủ tướng phê duyệt 27/11/2023. Đến 4/2026 đã đạt ~942.000 ha, giai đoạn 2026–2030 mở rộng thêm ~820.000 ha.
- **Quy trình MRV 6 bước** (Quyết định 4801/QĐ-BNNMT, 14/11/2025): **Chuẩn bị – Đăng ký – Thiết lập đường cơ sở – Đo đạc – Báo cáo – Thẩm định**. Thí điểm đến hết 31/12/2026, quy mô 300.000 ha vụ Đông Xuân 2025–2026.
- **Cơ chế tài chính TCAF (World Bank):** chi trả dựa trên kết quả giảm phát thải, tổng khoảng 33,3–40 triệu USD cho toàn Đề án (giá tín chỉ đang định giá, **chưa chốt chính thức**).
- **Kỹ thuật lõi:** "1 phải 5 giảm" — giảm giống, giảm phân, giảm thuốc, giảm nước (tưới ngập-khô xen kẽ AWD), giảm thất thoát sau thu hoạch, xử lý rơm rạ.
- **Điểm pilot cụ thể:** HTX Tiến Thuận (Cần Thơ), HTX Thanh niên Phú Hòa (An Giang), các mô hình điểm ở Đồng Tháp, Kiên Giang, Trà Vinh, Sóc Trăng. IRRI hỗ trợ kỹ thuật (Văn phòng đối tác IRRI Việt Nam).
- **Công cụ có sẵn để tận dụng:** app **FarMoRe** (IRRI, miễn phí, tính tCO2e/ha cấp ruộng), **Kobo Toolbox** (thu thập dữ liệu mã nguồn mở). RiceMoRe (hệ thống của Cục Trồng trọt & BVTV) đã phủ ~75% diện tích lúa quốc gia nhưng **chưa có API mở** — cần partnership thể chế mới truy cập được.

> **Ý nghĩa cho sản phẩm:** Đây gần như là bài toán được nhà nước "đặt hàng sẵn" — MRV 6 bước cần được số hóa cho hàng trăm nghìn hộ dân/HTX. AgriCarbon nên định vị là **công cụ hỗ trợ số hóa quy trình MRV**, không phải một "carbon calculator" chung chung.

## Khác biệt hóa so với đối thủ hiện có

| Nhóm đối thủ | Đại diện | Làm gì | Khoảng trống họ để lại |
|---|---|---|---|
| Nhật ký/truy xuất | FaceFarm (Sorimachi) | Nhật ký SX, mã QR, mã vùng trồng | Không tính CO2e/kg, không CV, không tối ưu tài nguyên |
| MRV/tín chỉ carbon | CarbonFarm, Regrow, Green Carbon, Spiro, Boomitra | Đo phát thải cấp vùng để bán tín chỉ | Hướng doanh nghiệp/tín chỉ, không có CV, không "per kg" cho nông hộ |

**Định vị AgriCarbon:** *"Carbon + hiệu suất tài nguyên tính trên mỗi kg sản phẩm, ở cấp nông hộ, có thị giác máy tính (Computer Vision) hỗ trợ ra quyết định."* — đây là chỗ trống mà FaceFarm (quá rộng, không carbon) và CarbonFarm/Regrow (quá vĩ mô, không cấp hộ) đều chưa lấp.

---

# 2. Roadmap tính năng

Sản phẩm vận hành theo vòng lặp:

```text
                MEASURE
                   ↓
              UNDERSTAND
                   ↓
               OPTIMIZE
                   ↓
                  ACT
                   ↓
                MEASURE (lặp lại)
```

## Giai đoạn 1 — Core (bắt buộc, chứng minh ý tưởng)

> Tách thành 3 lớp theo đúng thứ tự phụ thuộc kỹ thuật, vì mục tiêu lõi của MVP là **ra được con số CO2e/kg đúng và tin cậy được**. Làm lần lượt 1a → 1b → 1c, không làm song song dàn trải.

### 1a. Walking Skeleton — Lõi CO2e (ưu tiên tuyệt đối, làm trước tiên)

> Mục tiêu: có 1 pipeline chạy được end-to-end ra con số CO2e/kg, dù giao diện còn thô. Đây là đường găng (critical path) của toàn bộ dự án — chưa xong phần này thì các phần sau không có dữ liệu để chạy.

**1a.1. Mobile App ghi nhật ký canh tác (bản tối giản)**
- Ghi nhận: giống, lượng giống gieo sạ, phân bón (loại/lượng), nước tưới (đặc biệt kỹ thuật AWD — tưới ngập-khô xen kẽ), thuốc BVTV, xử lý rơm rạ.
- Thiết kế form bám sát khung **"1 phải 5 giảm"** của Đề án — vừa đúng chính sách thật, vừa dễ giải thích với hội đồng chấm thi.
- Offline-first, đồng bộ khi có mạng (phù hợp vùng sóng yếu ĐBSCL).
- Ở bước này chỉ cần đủ field phục vụ công thức tính CO2e, chưa cần giao diện đẹp.

**1a.2. Carbon Engine**
- Công thức: Activity Data × Emission Factor → CO2e.
- Dùng hệ số tham chiếu Việt Nam (~1,04 kg CO2/kg lúa trung bình, dao động 2,29–3,72 kg CO2e/kg tùy phương pháp canh tác) làm baseline.
- Tính riêng CO2e cho phương án AWD vs tưới ngập liên tục — đây là biến số ảnh hưởng carbon lớn nhất và đúng thứ MRV 6 bước đang đo.
- **Đây là phần cần test kỹ nhất** — giám khảo nhiều khả năng sẽ hỏi sâu "số này tính ra sao, dựa hệ số nào, có khớp MRV không".

### 1b. Lớp AI/CV — thể hiện đúng chủ đề cuộc thi (làm ngay sau khi 1a chạy ổn)

> Lý do vẫn bắt buộc có trong MVP: cuộc thi thuộc chủ đề AI, nếu MVP chỉ có con số CO2e mà không có yếu tố AI/CV thì phần "công nghệ" sẽ bị đánh giá mỏng. Nhưng làm sau 1a để đảm bảo lõi chắc trước, tránh vỡ tiến độ ở phần quan trọng nhất.

**1b.1. Computer Vision — 1 bài toán duy nhất**
- Chọn: **phát hiện bệnh lá lúa** (đạo ôn/blast, bạc lá/bacterial blight, đốm nâu/brown spot).
- Pretrain trên bộ dataset public (Sethy et al., ~5.932 ảnh, 4 lớp) → fine-tune bằng ảnh tự chụp tại 1 HTX pilot.
- Không ôm thêm bài toán khác (đếm bông, ước lượng năng suất) ở giai đoạn này.

**1b.2. Resource Efficiency Dashboard**
- Các chỉ số: nước/kg, phân bón/kg, carbon/kg, cost/kg.
- Efficiency Map theo từng thửa/lô (tham khảo mô hình quản lý vùng đất của FaceFarm) để so sánh giữa các hộ trong cùng HTX.
- Tận dụng lại đúng dữ liệu đã có từ 1a, không cần thu thập thêm.

**1b.3. AI Recommendation (mức cơ bản)**
- Rule-based hoặc mô hình đơn giản: ví dụ "Lô này dùng phân N cao hơn benchmark 21% → gợi ý giảm X kg", kèm ước tính impact (giảm bao nhiêu CO2e, bao nhiêu chi phí).
- Recommendation luôn đi kèm impact estimate, không chỉ đưa lời khuyên suông.

### 1c. Lớp trình bày/vận hành (làm cuối cùng, có thể cắt/rút gọn nếu thiếu thời gian)

> Đây là phần "đẹp khi demo" nhưng không phải bằng chứng kỹ thuật cốt lõi. Nếu chạy thiếu thời gian, có thể thay bằng bản mock/slide thay vì code thật, vẫn kể được câu chuyện sản phẩm.

**1c.1. Web Dashboard cho Doanh nghiệp / HTX quản lý**
- Giao diện quản trị xem dữ liệu theo cấp bậc: **Farm → Plot → Crop → Batch → Activity → Carbon** (đúng khung mục 8 của tài liệu gốc AgriCarbon).
- Tổng hợp toàn bộ dữ liệu từ nhiều hộ/HTX vào một nơi — giải quyết đúng pain point ban đầu ("doanh nghiệp phải tổng hợp dữ liệu từ nhiều hộ/HTX" thủ công).
- Phân quyền theo vai trò: Nông dân (chỉ nhập liệu) / Quản lý HTX (xem tổng hợp cấp HTX) / Doanh nghiệp-Cơ quan quản lý (xem toàn vùng, phục vụ báo cáo MRV).

**1c.2. Export Carbon / MRV Report**
- Xuất báo cáo dạng PDF/Excel theo đúng cấu trúc 6 bước MRV (Chuẩn bị – Đăng ký – Thiết lập đường cơ sở – Đo đạc – Báo cáo – Thẩm định) để nộp cho đơn vị thẩm định hoặc cơ quan quản lý.
- Đây là bước biến dữ liệu đã đo thành tài liệu có thể dùng thật trong quy trình chính sách — tăng tính "thực chiến" khi pitch.

## Giai đoạn 2 — Khác biệt hóa

### 2.1. Mapping trực tiếp vào MRV 6 bước
- Thiết kế luồng app theo đúng: Chuẩn bị – Đăng ký – Thiết lập đường cơ sở – Đo đạc – Báo cáo – Thẩm định.
- Đây là điểm khác biệt lớn nhất — biến app thành "công cụ số hóa MRV chính thức" thay vì app carbon chung chung.

### 2.2. Evidence / Anti-fraud (giữ nguyên từ ý tưởng gốc)
- Camera bắt buộc + GPS + timestamp khi ghi nhận hoạt động.
- Audit trail: ai nhập / ai sửa / ai xóa / thời điểm thay đổi.
- Phát hiện dữ liệu bất thường (vd: 1 ha lúa + 5.000 kg phân bón → cảnh báo anomaly).

### 2.3. What-if Simulation
- Người dùng nhập kịch bản giả định, vd: "Nếu giảm phân N 15%?" hoặc "Nếu áp dụng AWD thay vì tưới ngập liên tục?".
- Hệ thống mô phỏng và trả về: thay đổi CO2e (%), thay đổi chi phí, thay đổi năng suất dự kiến, mức rủi ro.
- Mục tiêu: giúp nông dân/HTX tìm điểm cân bằng giữa năng suất, tài nguyên, carbon và chi phí trước khi hành động thật — đây là tính năng thể hiện rõ "AI Optimization", điểm cộng lớn cho phần công nghệ.

### 2.4. Farm/Field Map & Historical Data
- Bản đồ hiển thị các thửa/lô theo hiệu suất carbon (xanh/vàng/đỏ), tham khảo mô hình Efficiency Map trong tài liệu gốc.
- Lưu dữ liệu mùa vụ trước để làm benchmark cho mùa vụ tiếp theo (học từ FaceFarm — "Historical Data hỗ trợ mùa vụ tiếp theo").
- Giúp trả lời câu hỏi "so với chính mình vụ trước, tôi đã cải thiện chưa?" — câu chuyện impact dễ thuyết phục hơn so sánh với hộ khác.

### 2.5. Weather Integration (tích hợp thời tiết)
- Kéo dữ liệu mưa/nhiệt độ từ API thời tiết công khai để đối chiếu với lượng nước tưới thực tế — giúp phát hiện trường hợp tưới dư thừa so với nhu cầu thực (vd: vẫn bơm tưới dù vừa có mưa lớn).
- Hỗ trợ AI Recommendation đưa ra gợi ý sát với điều kiện thời tiết thực tế thay vì chỉ dựa trên benchmark tĩnh.

## Giai đoạn 3 — Điểm nhấn cho pitch/demo: AI Chatbot RAG

**Lý do nên làm:** Nông dân/HTX hiện không có kênh dễ để tra cứu "tôi có đủ điều kiện tham gia Đề án không", "MRV bước 3 là gì", "bón phân N bao nhiêu là chuẩn" — đúng pain point ở tầng dữ liệu/thông tin chưa số hóa. Đây cũng là cách rẻ nhất để thể hiện rõ "AI core" trước hội đồng, vì hỏi-đáp là thứ giám khảo có thể tự test trực tiếp.

### Phạm vi nên làm

| Nên làm | Không nên làm |
|---|---|
| Trả lời về: quy trình MRV, điều kiện tham gia Đề án 1 triệu ha, khuyến nghị kỹ thuật canh tác theo mùa vụ ĐBSCL, giải thích số liệu carbon/hiệu suất của chính lô đất người dùng | Chatbot tự do trả lời mọi câu hỏi nông nghiệp chung chung |
| Cá nhân hóa theo dữ liệu thật của nông dân đó (vd: "Vì sao lô C của tôi carbon cao?" → query dữ liệu backend + trả lời có ngữ cảnh) | Mở rộng sang chủ đề ngoài nông nghiệp/carbon (y tế, tài chính…) |
| Nguồn tri thức: văn bản chính sách công khai (QĐ 4801/QĐ-BNNMT, tài liệu Đề án 1 triệu ha), hướng dẫn kỹ thuật "1 phải 5 giảm", bảng emission factor | Tự suy diễn/bịa số liệu chính sách khi không tìm thấy — phải trả lời "không có thông tin" thay vì hallucinate |

### Kiến trúc đề xuất (đơn giản, vừa sức đồ án)
1. **Knowledge base:** văn bản chính sách công khai (Quyết định 4801, tài liệu MRV, hướng dẫn khuyến nông "1 phải 5 giảm") + FAQ tự soạn.
2. **Chunk + embed:** dùng vector DB nhẹ (Chroma/SQLite) — không cần hạ tầng lớn.
3. **Query kết hợp 2 nguồn:**
   - (a) Knowledge base tĩnh (chính sách/kỹ thuật)
   - (b) Dữ liệu động của chính nông dân đó (carbon/kg, resource/kg của lô đất)
   - → cho phép trả lời kiểu "So với benchmark, lô của bạn đang dùng nhiều nước hơn 20%."
4. **Luôn cite nguồn văn bản** khi trả lời về chính sách để tăng độ tin cậy, tránh thông tin sai lệch.

## Giai đoạn 4 — Mở rộng tương lai (KHÔNG làm trong MVP, chỉ nêu trong roadmap dài hạn để pitch)

> Đây là các tính năng nêu để thể hiện tầm nhìn sản phẩm khi trình bày, nhưng **không đưa vào MVP** — đúng tinh thần "Những thứ KHÔNG nên ôm ngay vào MVP" đã thống nhất trước đó (tránh ôm IoT đầy đủ, blockchain, drone, satellite... cùng lúc).

### 4.1. Traceability / Batch Management
- Gắn mã lô (batch) cho từng đợt thu hoạch, cho phép truy xuất ngược từ hạt gạo về tận thửa ruộng/nông hộ — phục vụ nhu cầu minh bạch chuỗi xuất khẩu gạo phát thải thấp trong tương lai.

### 4.2. Cost Management
- Theo dõi chi phí thực tế trên mỗi kg sản phẩm (giống, phân, thuốc, nhân công, tưới tiêu) — trả lời câu hỏi "sản xuất 1 kg gạo tốn bao nhiêu" (học từ Cost Management của FaceFarm).

### 4.3. IoT Sensor tối thiểu (cảm biến mực nước ruộng)
- Chỉ nên thí điểm 1 cảm biến đơn giản (mực nước) thay vì "IoT đầy đủ" — dùng để tự động hóa việc ghi nhận AWD (tưới ngập-khô xen kẽ) thay vì nông dân tự nhập tay, tăng độ tin cậy dữ liệu.

### 4.4. Notification & Alerts
- Cảnh báo qua app/SMS khi: phát hiện bất thường dữ liệu, đến thời điểm nên rút nước (theo AWD), hoặc phát hiện dấu hiệu bệnh qua CV.

### 4.5. Marketplace / Kết nối bao tiêu
- Kết nối HTX có điểm hiệu suất carbon tốt với doanh nghiệp thu mua ưu tiên gạo phát thải thấp — hướng mở rộng mô hình kinh doanh về sau, không phải phần kỹ thuật cốt lõi.

### 4.6. Đa ngôn ngữ / Hỗ trợ giọng nói
- Giao diện đơn giản hóa, hỗ trợ nhập liệu bằng giọng nói tiếng Việt — phù hợp nông dân lớn tuổi, ít quen thao tác điện thoại, giảm rào cản áp dụng thực tế.

---

# 6. Chức năng bổ sung (đã chọn lọc theo độ khả thi & tác dụng)

> Các chức năng dưới đây được thêm vì: dễ triển khai với nguồn lực sinh viên (không cần hạ tầng lớn/ML phức tạp) **và** có tác động rõ đến việc dùng thật hoặc câu chuyện pitch.

## Tier 1 — Rất dễ làm, tác dụng cao (đưa vào MVP)

### 6.1. Đăng nhập/thông báo qua Zalo OA
- **Khả năng làm:** Cao — Zalo OA có API công khai, tích hợp không phức tạp.
- **Tác dụng:** Nông dân ĐBSCL hầu hết dùng Zalo hàng ngày, không quen tải app mới. Đây là kênh onboarding rẻ nhất và thực tế nhất để "chạm" được người dùng thật, tăng khả năng có pilot thành công.

### 6.2. Lịch mùa vụ tự động (Growth Stage Reminder)
- **Khả năng làm:** Rất dễ — rule-based theo ngày gieo sạ + giống lúa, không cần AI.
- **Tác dụng:** Tự nhắc "hôm nay nên rút nước theo AWD", "giai đoạn bón phân lần 2" — biến app từ "công cụ ghi chép" thành "trợ lý chủ động", giá trị sử dụng hàng ngày cao hơn app chỉ để nhập liệu.

### 6.3. Bảng xếp hạng hiệu suất ẩn danh trong HTX (Leaderboard)
- **Khả năng làm:** Rất dễ — chỉ là aggregation + sort trên dữ liệu đã có sẵn (Carbon Engine, Resource Dashboard), không cần công nghệ mới.
- **Tác dụng:** Yếu tố tâm lý xã hội (so sánh với hộ khác) đã được chứng minh hiệu quả trong khuyến nông thực tế — thúc đẩy thay đổi hành vi mà gần như không tốn công nghệ.

### 6.4. Nhập liệu bằng giọng nói tiếng Việt (Voice-to-form)
- **Khả năng làm:** Trung bình — dùng API speech-to-text tiếng Việt có sẵn (Google STT, FPT.AI, Viettel AI), không tự huấn luyện.
- **Tác dụng:** Giảm rào cản lớn nhất với nông dân lớn tuổi (ngại gõ chữ) — tăng khả năng dữ liệu được ghi đều đặn thay vì bỏ dở.

## Tier 2 — Dễ làm, hỗ trợ tính đúng đắn kỹ thuật

### 6.5. OCR sổ ghi chép giấy cũ
- **Khả năng làm:** Trung bình — chụp ảnh sổ tay, dùng OCR (hoặc gửi ảnh cho vision-LLM trích xuất) thay vì gõ tay lại toàn bộ lịch sử.
- **Tác dụng:** Nhiều hộ đã có sổ ghi chép giấy từ trước (đúng pain point ban đầu của dự án) — giúp import dữ liệu lịch sử nhanh, có ngay historical baseline để so sánh mà không cần chờ hết 1 vụ mới.

## Tier 3 — Khó hơn một chút nhưng vẫn trong tầm với

### 6.6. Cảnh báo bất thường tự động qua Zalo/SMS
- **Khả năng làm:** Trung bình — kết hợp rule anomaly detection (đã có trong Evidence/Anti-fraud, mục 2.2) + gửi qua Zalo OA (mục 6.1)/SMS gateway.
- **Tác dụng:** Biến phát hiện bất thường từ "chỉ hiện trên dashboard" thành "chủ động đẩy tới người dùng" — tăng giá trị thực tế đáng kể, tận dụng lại 2 module đã build (không phát sinh nhiều công sức mới).

---

# 7. Thứ tự triển khai đề xuất

```text
Giai đoạn 1a (Walking Skeleton — làm trước tiên, đường găng):
  App ghi nhật ký (bản tối giản) + Carbon Engine
  → mục tiêu: ra được CO2e/kg chạy end-to-end, test kỹ độ tin cậy

Giai đoạn 1b (lớp AI/CV — làm ngay sau 1a chạy ổn):
  Module CV bệnh lá + Resource Efficiency Dashboard
  + AI Recommendation cơ bản

Giai đoạn 1c (lớp trình bày/vận hành — làm cuối, có thể cắt nếu thiếu thời gian):
  Web Dashboard doanh nghiệp/HTX + Export MRV Report

Giai đoạn 2 (khác biệt hóa):
  Mapping vào MRV 6 bước + Evidence/Anti-fraud
  + What-if Simulation + Farm Map & Historical Data
  + Weather Integration

Giai đoạn 3 (điểm nhấn pitch, nếu còn thời gian):
  RAG Chatbot — ưu tiên nhánh "chính sách/MRV" trước
  (dataset là văn bản công khai, dễ chuẩn bị hơn nhánh
  "tư vấn kỹ thuật canh tác", vốn cần chuyên gia nông nghiệp
  kiểm chứng để tránh sai lệch)

Giai đoạn 4 (chỉ nêu trong tầm nhìn, không làm trong MVP):
  Traceability/Batch + Cost Management + IoT cảm biến mực nước
  + Notification/Alerts + Marketplace + Đa ngôn ngữ/giọng nói
```

---

# 8. Kênh tiếp cận pilot / dữ liệu thực địa

- **HTX Tiến Thuận** (xã Thạnh An/Vĩnh Thạnh, Cần Thơ) — mô hình 50 ha đầu tiên, giám đốc Nguyễn Cao Khải.
- **HTX Dịch vụ nông nghiệp Thanh niên Phú Hòa** (An Giang) — HTX "thanh niên", có xu hướng cởi mở hơn với nhóm sinh viên.
- **Văn phòng Quan hệ đối tác & Điều phối dự án IRRI Việt Nam** — đầu mối hỗ trợ kỹ thuật/dữ liệu.
- **Sở Nông nghiệp và Môi trường tỉnh** (Đồng Tháp, Cần Thơ, An Giang) / Trung tâm Khuyến nông Quốc gia.
- Công cụ miễn phí có thể dùng ngay: **FarMoRe** (app IRRI tính tCO2e/ha), **Kobo Toolbox** (form thu dữ liệu mã nguồn mở).

---

# 9. Ngưỡng cân nhắc đổi hướng

- Nếu nhóm **có sẵn quan hệ vùng cà phê Tây Nguyên + một doanh nghiệp xuất khẩu chịu áp lực EUDR** làm khách pilot → có thể cân nhắc chuyển hướng cà phê (khách hàng có nhu cầu chi trả rõ hơn).
- Nếu **không xin được HTX/pilot nào trong 3 tuần đầu** → thu hẹp phạm vi xuống prototype chạy trên dataset public + demo, vẫn giữ lúa gạo làm crop chính, không đổi cây.

---

# 10. Việc cần làm tiếp (chưa chốt)

- [ ] Liên hệ HTX pilot cụ thể (Tiến Thuận hoặc Phú Hòa) xin dữ liệu/thử nghiệm nhỏ
- [ ] Fine-tune model CV bằng ảnh thực địa (tối thiểu vài trăm ảnh)
- [ ] Xác định chính xác Emission Factor áp dụng (đối chiếu với hướng dẫn MRV chính thức)
- [ ] Thiết kế UI app ghi nhật ký theo khung "1 phải 5 giảm"
- [ ] Chuẩn bị knowledge base cho RAG chatbot (thu thập văn bản chính sách công khai)
- [ ] Xây baseline so sánh Before/After để có câu chuyện impact rõ ràng khi pitch
- [ ] Kiểm tra license của từng dataset trước khi dùng (đa số CC BY 4.0 nhưng cần xác nhận từng bộ)
- [ ] Đăng ký Zalo OA (mục 6.1) và tìm hiểu API tích hợp
- [ ] Khảo sát API speech-to-text tiếng Việt (Google STT / FPT.AI / Viettel AI) cho tính năng nhập liệu giọng nói (mục 6.4)
- [ ] Thử nghiệm OCR/vision-LLM trên vài mẫu sổ ghi chép giấy thật của nông dân (mục 6.5)

---

## Ghi chú quan trọng khi trình bày với hội đồng

- Giá tín chỉ carbon (~20 USD) **đang trong quá trình định giá, chưa chốt chính thức** — không trình bày như số liệu đã xác nhận.
- RiceMoRe/FarMoRe **chưa có API mở** — nếu pitch có nhắc đến tích hợp, cần nói rõ đây là hướng hợp tác tương lai, không phải đã kết nối.
- Sau sáp nhập, tên gọi chính thức hiện nay là **Bộ Nông nghiệp và Môi trường** (không còn Bộ NN&PTNT riêng).

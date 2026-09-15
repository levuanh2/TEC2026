# Hướng dẫn cho Nông hộ

Hướng dẫn dùng **Farmer Web** (trên trình duyệt) và các điểm khác biệt khi dùng
**ứng dụng điện thoại (Flutter)**.

!!! info "Trước khi bắt đầu"
    - Tài khoản do quản lý HTX cấp. Bạn chỉ thấy các ruộng mà HTX đã gán cho bạn.
    - Farmer Web cần có mạng. Ứng dụng điện thoại ghi được khi mất mạng và tự gửi khi
      có mạng lại.
    - Kết quả phát thải và nhận diện bệnh lá chỉ để **tham khảo**, không phải chứng
      nhận hay chẩn đoán chính thức.

## 1. Đăng nhập

1. Mở địa chỉ web hệ thống, nhập **Email** và **Mật khẩu**, bấm **Đăng nhập**.
2. Bạn được đưa tới trang **Tổng quan** của khu nông hộ.
3. Thanh điều hướng gồm: **Tổng quan**, **Nhật ký**, **Ruộng**, **Hiệu suất**, **Tôi**.

Nếu thấy "Chưa có ruộng trong phạm vi của bạn", hãy liên hệ quản lý HTX để được gán
nông hộ hoặc thửa ruộng.

## 2. Xem ruộng của bạn

1. Chọn **Ruộng** → trang "Các ruộng trong phạm vi của bạn".
2. Mỗi thẻ là một nông hộ: tên, mã hộ, địa phương.
3. Bấm vào nông hộ để xem **Thửa ruộng** và **Vụ đang canh tác**.

## 3. Chọn thửa

Trong trang nông hộ, bấm một thửa để xem diện tích và mục **Mùa vụ** (các vụ của thửa,
vụ đang canh tác được đánh dấu).

## 4. Chọn vụ canh tác

Bấm một vụ để mở không gian vụ với 4 tab:

| Tab | Nội dung |
|---|---|
| **Tổng quan** | Ghi nhanh cho vụ này, tình trạng vụ, mức đầy đủ dữ liệu, hoạt động gần đây |
| **Nhật ký** | Toàn bộ hoạt động đã ghi của vụ |
| **Hiệu suất** | Bốn chỉ số tài nguyên và phát thải |
| **Carbon** | Kết quả phát thải đã được tính |

!!! note "Chỉ ghi được vào vụ đang canh tác"
    Hệ thống chỉ nhận ghi nhật ký cho vụ ở trạng thái **đang canh tác** và đã có một lô
    sản xuất đang mở. Nếu gặp thông báo vụ không mở cho ghi, hãy liên hệ quản lý HTX.

## 5. Ghi hoạt động

1. Ở **Tổng quan** (mục **Ghi nhanh**) hoặc trong vụ (**Ghi nhanh cho vụ này**), chọn
   việc bạn vừa làm: **Gieo sạ**, **Bón phân**, **Tưới nước**, **Thuốc BVTV**, **Rơm rạ**,
   **Thu hoạch**.
2. Chọn **ngày** thực hiện (form chỉ ghi ngày, không ghi giờ).
3. Điền các ô; ô có dấu `*` là bắt buộc.
4. Có thể thêm **Ghi chú**.
5. Bấm lưu. Nếu mạng chập chờn và bạn bấm lại, hệ thống **không** tạo bản ghi trùng.

Để **sửa** hoặc **xoá**: mở bản ghi trong **Nhật ký**. Bạn chỉ sửa/xoá được bản ghi do
chính mình tạo. Bản ghi bị xoá không còn hiển thị và không còn được tính vào chỉ số.

### Gieo sạ

| Ô | Bắt buộc |
|---|---|
| Lượng giống (kg) | Có |
| Giống, Phương pháp gieo, Chi phí vật tư (đ) | Không |

### Bón phân

| Ô | Bắt buộc |
|---|---|
| Loại phân | Có |
| Lượng bón (kg) | Có |
| Hàm lượng đạm (%), lân (%), kali (%) | Không |
| Chi phí vật tư (đ) | Không |

!!! tip "Nên ghi hàm lượng đạm"
    Tính phát thải N₂O cần **hàm lượng đạm (%)** của phân. Thiếu thông tin này thì phát
    thải của vụ không tính được.

### Tưới nước

| Ô | Bắt buộc |
|---|---|
| Hình thức tưới: Ướt khô xen kẽ (AWD) · Ngập liên tục · Luân phiên · Khác | Có |
| Lượng nước (m³) — để trống nếu không đo được | Không |
| Thời gian tưới (phút), Mực nước ruộng (cm) | Không |
| Có dùng máy bơm → Năng lượng bơm (kWh) | Không |
| Chi phí (đ) | Không |

!!! tip "Chọn đúng hình thức tưới"
    Chỉ **Ướt khô xen kẽ (AWD)** và **Ngập liên tục** được dùng để tính phát thải. Chọn
    **Luân phiên** hoặc **Khác** thì hệ thống không tự đoán chế độ nước, và phần phát thải
    của vụ sẽ chưa tính được cho tới khi chế độ nước được khai rõ.

### Thuốc bảo vệ thực vật

| Ô | Bắt buộc |
|---|---|
| Tên thuốc | Có |
| Lượng sử dụng + Đơn vị | Có |
| Hoạt chất / đối tượng phòng trừ, Chi phí vật tư (đ) | Không |

### Rơm rạ

| Ô | Bắt buộc |
|---|---|
| Cách xử lý rơm rạ: Vùi vào đất · Đốt · Mang ra khỏi ruộng · Ủ compost · Khác | Có |
| Lượng rơm rạ (kg) | Không |
| Số ngày trước khi làm đất | Không |
| Tỷ lệ chất khô của rơm (0 đến 1, ví dụ 0,85) | Không |
| Rơm được vùi trả lại ruộng | Không |
| Chi phí (đ) | Không |

!!! tip "Thông tin rơm rạ ảnh hưởng tới tính phát thải"
    Các ô "không bắt buộc" vẫn cần để **tính phát thải**:

    - **Vùi vào đất**: cần lượng rơm, tỷ lệ chất khô và số ngày trước khi làm đất.
    - **Đốt**: cần lượng rơm và tỷ lệ chất khô.
    - **Ủ compost**: cần biết rơm có được trả lại ruộng hay không, cùng lượng rơm và tỷ lệ chất khô.
    - **Mang ra khỏi ruộng**: không cần thêm.
    - **Khác**: hệ thống chưa có cách tính cho lựa chọn này.

    Chọn "Đốt" không hiển thị ngay một con số CO₂e; phát thải chỉ có khi vụ được tính.

### Thu hoạch

| Ô | Bắt buộc |
|---|---|
| Sản lượng thu hoạch (kg) | Có |
| Diện tích thu hoạch (ha), Độ ẩm (%), Chi phí (đ) | Không |

Sản lượng là **mẫu số** của mọi chỉ số "trên mỗi kg". Vụ có nhiều lần thu hoạch thì hệ
thống **cộng** tất cả.

## 6. Xem chỉ số tài nguyên

1. Chọn **Hiệu suất** (hoặc tab **Hiệu suất** trong vụ).
2. Bốn chỉ số của vụ đang canh tác:
    - **Nước / kg thóc** (m³/kg)
    - **Phân bón / kg thóc** (kg phân/kg — tính theo khối lượng phân, không phải lượng đạm)
    - **Chi phí / kg thóc** (đ/kg — chỉ gồm chi phí bạn đã ghi trên từng hoạt động)
    - **CO₂e / kg thóc**
3. Chỉ số hiện "—" hoặc "Chưa đủ dữ liệu" nghĩa là **thiếu dữ liệu**, không phải bằng 0.
   Mục **Mức đầy đủ dữ liệu** trong vụ cho biết còn thiếu: Nước tưới, Phân bón, Sản lượng
   thu hoạch, Chi phí vật tư hay Kết quả Carbon; có nút ghi nhanh cho mục còn thiếu.

## 7. Xem Carbon

1. Mở tab **Carbon** của vụ.
2. Nếu đã có bản tính: CO₂e / kg, CO₂e tổng, thời điểm tính, kịch bản nước, **Nguồn phát
   thải chính**, phiên bản bộ hệ số và công cụ tính.
3. Nếu thấy **"Chưa có kết quả phát thải hợp lệ cho vụ này"**: vụ chưa có bản tính thành
   công được lưu. Farmer Web **không** có nút tự tính; việc tính do quản lý HTX hoặc ứng
   dụng điện thoại thực hiện, và hiện bị chặn vì bộ hệ số phát thải chưa đầy đủ.

Trang luôn ghi: "Kết quả là ước tính theo bộ phương pháp hiện tại; không phải chứng nhận
hoặc tín chỉ carbon."

## 8. Xem khuyến nghị

1. Mục **Khuyến nghị** ở trang Tổng quan.
2. Có hai loại:
    - **Khuyến nghị tối ưu** (ví dụ cân nhắc tưới AWD) — chỉ xuất hiện khi hệ thống tính
      được mức giảm phát thải trên chính dữ liệu vụ của bạn;
    - **Việc cần bổ sung dữ liệu** — ví dụ "Ghi sản lượng thu hoạch", "Bổ sung lượng nước
      tưới", "Bổ sung khối lượng phân bón", "Bổ sung chi phí vật tư".
3. Bấm **Cập nhật khuyến nghị** sau khi ghi thêm dữ liệu.
4. Chấp nhận hoặc bỏ qua từng khuyến nghị; lựa chọn của bạn được giữ khi cập nhật.

"Chưa có khuyến nghị định lượng" là trạng thái bình thường khi chưa đủ dữ liệu phát thải.

## 9. Kiểm tra lá lúa (thử nghiệm)

!!! warning "Chỉ mang tính hỗ trợ"
    Mô hình nhận diện là **thử nghiệm**, huấn luyện trên ảnh công khai, **chưa xác nhận
    thực địa**. Không dùng kết quả thay cho tư vấn của cán bộ kỹ thuật.

1. Bấm **Kiểm tra lá lúa** (ở Tổng quan hoặc trong vụ).
2. Chọn hoặc chụp ảnh **JPEG hoặc PNG**, chụp gần **một lá lúa**, dung lượng tối đa 10 MB.
3. Kết quả có thể là:
    - **Kết quả nhận diện**: Đạo ôn, Bạc lá, Đốm nâu hoặc Lá khoẻ, kèm độ tin cậy;
    - **Chưa thể xác định chắc chắn**: độ tin cậy dưới ngưỡng → hệ thống **không gán nhãn**;
      hãy **Chụp/chọn ảnh khác** rõ hơn.
4. Mục **Kiểm tra gần đây** lưu lịch sử kiểm tra của vụ.

Cùng một tệp ảnh không dùng được cho hai vụ khác nhau.

## 10. Tài khoản

Trang **Tôi** hiển thị tên, email, **phạm vi truy cập** (nông hộ, thửa, vụ bạn được cấp
quyền) và nút **Đăng xuất**.

## Dùng ứng dụng điện thoại (Flutter)

| Việc | Khác biệt so với Farmer Web |
|---|---|
| Mất mạng | Vẫn ghi được; dữ liệu nằm trên máy tới khi gửi |
| Gửi dữ liệu | Tự gửi khi đăng nhập, mở lại app, có mạng lại; hoặc bấm gửi ngay ở tab gửi dữ liệu. Có tuỳ chọn **chỉ gửi qua Wi-Fi** |
| Trạng thái | Mỗi bản ghi có trạng thái chờ gửi / đang gửi / đã gửi / lỗi; lỗi quyền cần liên hệ HTX |
| Nhiên liệu | Ứng dụng điện thoại có thêm loại **nhiên liệu** |
| Thửa, vụ | Tạo được thửa và vụ trên điện thoại |
| Carbon | Có màn kết quả phát thải và có thể yêu cầu tính |
| Khuyến nghị, kiểm tra lá | **Chưa khả dụng** trên điện thoại (màn hình báo chưa cấu hình) |

# Hướng dẫn cho Quản lý (Management Web)

Hướng dẫn dành cho **quản lý HTX** (`cooperative_manager`) và **cơ quan quản lý**
(`regulator`) dùng Management Web.

!!! note "Tài khoản doanh nghiệp (`enterprise_viewer`)"
    Hiện web chưa nhận đúng role `enterprise_viewer`, nên tài khoản chỉ có role này
    được đưa vào khu Nông hộ thay vì Management Web. Đây là lỗi đã biết, chưa sửa
    ([B2](../limitations/implementation-audit-findings.md#b2)).

!!! danger "Gói xuất là gói bằng chứng, không phải chứng nhận"
    Các tệp JSON, Excel và PDF xuất từ màn MRV là **gói dữ liệu và bằng chứng hỗ trợ**
    từ dữ liệu đang có trong hệ thống. Chúng **không** phải chứng nhận, thẩm định, xác
    nhận của cơ quan có thẩm quyền, chứng chỉ tín chỉ carbon, và không khẳng định tuân
    thủ tiêu chuẩn MRV nào. Mỗi tệp đều ghi rõ điều này.

!!! warning "Về số liệu Carbon"
    Bộ hệ số phát thải hiện chưa đầy đủ (GWP chưa xác minh), nên các vụ thường hiển thị
    "chưa thể tính". Đó là trạng thái đúng, không phải lỗi.

## 1. Đăng nhập

1. Mở địa chỉ web của hệ thống, nhập email và mật khẩu.
2. Tài khoản quản lý được đưa tới **Tổng quan** (`/dashboard`).
3. Menu bên trái gồm: **Tổng quan**, **Quản lý** (Tổ chức / HTX, Nông hộ), **Hiệu suất**
   (Hiệu suất vùng), **MRV** (Hồ sơ MRV). Khi đang xem một thửa hoặc vụ, menu có thêm
   lối tắt tới đúng thửa/vụ đó.

## 2. Tổng quan (Dashboard)

Trang Tổng quan của tổ chức gồm:

- **Thông tin tổ chức** và các chỉ số tổng: số nông hộ, số thửa, số vụ, diện tích.
- **Hiệu suất theo nông hộ** — bảng so sánh các hộ; nhấp một hàng để mở hồ sơ hộ.
- **Hiệu suất vùng / HTX** — bốn chỉ số trên mỗi kg thóc.
- **Carbon** — CO₂e tổng và CO₂e/kg khi mọi vụ đều có số liệu.
- **MRV** — tóm tắt hồ sơ MRV trong phạm vi.
- **Cần chú ý** — chỉ lấy từ trạng thái dữ liệu thực tế; không có ngưỡng hay điểm số tự đặt.

Nếu tài khoản chưa gắn với tổ chức nào, trang hiển thị "Tài khoản chưa gắn với tổ chức".

## 3. So sánh nông hộ và hiệu suất

1. Chọn **Hiệu suất vùng**.
2. Bảng **So sánh nông hộ** hiển thị cho mỗi hộ: diện tích, sản lượng, nước/kg,
   phân/kg, CO₂e/kg, chi phí/kg và trạng thái dữ liệu:
    - **complete** — mọi vụ có đủ nước, phân, chi phí và Carbon;
    - **partial** — có vụ nhưng còn thiếu dữ liệu;
    - **missing** — hộ chưa có vụ nào.
3. Nhấp một hàng để mở hồ sơ nông hộ.

Cách đọc chỉ số tổng hợp:

- Chỉ số của nhóm = **tổng tử số / tổng sản lượng**, không phải trung bình các tỷ lệ.
- Chỉ cần một vụ thiếu dữ liệu, chỉ số tổng tương ứng hiển thị "—" thay vì một con số
  thiếu.

## 4. Nông hộ, thửa và vụ canh tác

1. **Quản lý → Nông hộ** → chọn hộ để xem **Thửa ruộng** và **Vụ canh tác**.
2. Mở một vụ để vào hub vụ với các tab:
    - **Tổng quan** — nhật ký theo nhóm, chỉ số nhanh, lô sản xuất (truy xuất nguồn gốc);
    - **Hoạt động** — nhật ký chi tiết; nhấp để xem từng bản ghi;
    - **Hiệu suất** — bốn chỉ số trên kg kèm trạng thái dữ liệu;
    - **Carbon** — kết quả phát thải;
    - **MRV** — các lô của vụ tham gia hồ sơ MRV.

Management Web **không** tạo hay sửa nhật ký canh tác; dữ liệu do nông hộ ghi.

## 5. Carbon của một vụ

1. Mở tab **Carbon** của vụ.
2. Chọn kịch bản: **Theo ghi nhận**, **AWD (rút nước)** hoặc **Ngập liên tục**.
3. Nếu đã có bản tính, trang hiển thị CO₂e/kg, CO₂e tổng, phân rã theo nguồn
   (CH₄ ruộng lúa, N₂O phân bón, đốt rơm, nhiên liệu) và chuỗi nguồn gốc của từng hệ
   số (trạng thái VERIFIED / PENDING_VERIFICATION).
4. Bấm **Tính lại theo kịch bản** để yêu cầu hệ thống tính cho kịch bản đang chọn.
    - Thông báo **"Chưa thể tính: bộ hệ số phát thải chưa hoàn chỉnh."** nghĩa là
      thiếu hệ số (hiện tại là GWP) hoặc bộ hệ số chưa được import.
    - Các lỗi khác (thiếu chế độ nước trước vụ, thiếu số ngày canh tác...) hiển thị lý do
      từ hệ thống; cần bổ sung dữ liệu vụ.

!!! note "Kịch bản giả định cũng được lưu"
    Tính với kịch bản AWD hoặc Ngập liên tục sẽ **lưu** một bản tính giả định. Trang
    Hiệu suất chỉ dùng bản tính "Theo ghi nhận", nhưng gói xuất MRV lấy bản tính thành
    công **mới nhất** của vụ, bất kể kịch bản (trường kịch bản được ghi rõ trong gói).

## 6. Hồ sơ MRV

1. Chọn **MRV → Hồ sơ MRV**. Đầu trang luôn có cảnh báo: "Bản mẫu / demo — chưa phải
   biểu mẫu chính thức hoặc báo cáo đã được cơ quan quản lý phê duyệt."
2. Mỗi hồ sơ hiển thị mã hồ sơ, kỳ, số **bước hoàn thành**, số **lô sản xuất** và số
   **minh chứng**.
3. **Tiến trình 6 bước**: Chuẩn bị → Đăng ký → Thiết lập đường cơ sở → Đo đạc → Báo cáo
   → Thẩm định, mỗi bước kèm trạng thái (chưa bắt đầu, đang làm, hoàn thành, bị chặn).

Web hiện **không** có màn tạo hồ sơ, cập nhật bước hay tải lên minh chứng; các thông tin
này được nhập ngoài ứng dụng.

## 7. Minh chứng (Evidence)

Danh sách minh chứng cho biết bước, loại, tên tệp, định dạng, thời điểm tải lên và mã
băm SHA-256 (nếu có). Hệ thống chỉ lưu **thông tin tham chiếu**; gói xuất không chứa bản
thân tệp minh chứng. Minh chứng thiếu mã băm được đánh dấu là khoảng trống nguồn gốc.

## 8. Xuất gói dữ liệu

Chỉ tài khoản **quản lý HTX của đúng tổ chức sở hữu hồ sơ** thấy khu **Xuất dữ liệu**.
Cơ quan quản lý xem được hồ sơ (qua quyền chia sẻ dữ liệu) nhưng không xuất được.

Mỗi lần bấm xuất, hệ thống tạo **một snapshot dữ liệu** tại thời điểm đó rồi tự tải
tệp về máy. Thông báo sau khi xong có dạng "Đã tạo … · SHA-256 tệp …" và số cảnh báo.

### Xuất JSON

- Bấm **Xuất JSON**.
- Đây là **gói dữ liệu gốc** (snapshot chuẩn): dùng khi cần kiểm tra toàn vẹn hoặc nạp
  vào hệ thống khác. Nó chứa hồ sơ, phạm vi, 6 bước, minh chứng (tham chiếu), nhật ký,
  thu hoạch, chỉ số tài nguyên, Carbon, nguồn gốc hệ số, cảnh báo và mã băm.

### Xuất Excel (.xlsx)

- Bấm **Xuất Excel (.xlsx)**.
- Hệ thống tạo snapshot rồi dựng workbook 11 sheet **từ đúng snapshot đó**. Ô trống
  nghĩa là **chưa có dữ liệu**, không phải bằng 0. Thời gian ghi theo UTC.

### Xuất PDF

- Bấm **Xuất PDF**.
- Báo cáo A4 đọc được cho người, dựng từ snapshot; ghi "Chưa đủ dữ liệu" cho giá trị
  thiếu, in mã băm của snapshot, và mọi trang có dòng "Tài liệu hỗ trợ, không phải chứng
  nhận".

### Cảnh báo trong gói

Gói vẫn được tạo khi dữ liệu chưa đầy đủ; các khoảng trống được liệt kê trong mục cảnh
báo (ví dụ: chưa có bản tính Carbon, chưa có minh chứng, bước chưa hoàn thành, thiếu
thu hoạch). Hãy đọc mục này trước khi chia sẻ gói.

## 9. Lịch sử xuất và tải lại

1. Mục **Lịch sử xuất** liệt kê mọi gói đã tạo, mới nhất trước: định dạng, thời điểm,
   người tạo, mã băm rút gọn, và gói đó là **snapshot gốc** hay **được dựng từ snapshot**
   nào.
2. Bấm tải về để lấy lại **đúng tệp đã tạo**. Hệ thống không dựng lại từ dữ liệu mới:
   sửa hồ sơ sau khi xuất không làm thay đổi gói cũ.
3. Trước khi trả tệp, server kiểm tra mã băm. Nếu tệp không khớp, hệ thống **từ chối
   tải** thay vì trả một tệp có thể đã bị thay đổi. Nếu tệp không còn trong kho lưu trữ,
   hãy xuất lại.

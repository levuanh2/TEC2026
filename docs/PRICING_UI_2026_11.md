# Bảng giá AgriCarbon — 13/11/2026

## Nội dung

Thay nội dung “Chưa công bố giá” của trang `/bang-gia` bằng hai bảng do người
dùng cung cấp trong ảnh. Mỗi nhóm có FREE, PLUS và PRO; PLUS được nhấn bằng nền
xanh đậm và nhãn “Phổ biến nhất”. Giữ các quyền lợi, hạn mức và phần “Phù hợp
với” của từng gói, cùng danh sách 6 hoạt động nhật ký.

| Đối tượng | FREE | PLUS | PRO |
|---|---|---|---|
| Nông hộ | Miễn phí | 999.990 VNĐ | 1.999.990 VNĐ |
| Hợp tác xã | Miễn phí | 14.990.000 VNĐ | 49.990.000 VNĐ |

Không tự thêm kỳ thu phí, VAT, giảm giá hoặc chính sách gia hạn vì ảnh không
cung cấp. Các dòng `/năm` và `/ngày` chỉ mô tả hạn mức tính carbon và token AI.
Ví dụ, AI của FREE HTX là 200.000 token/ngày, khác FREE nông hộ 1 triệu token/ngày.

Đây là nội dung giới thiệu và lựa chọn gói dịch vụ. Có nút **Chọn gói miễn phí**
cho FREE, **Mua ngay** cho PLUS/PRO theo yêu cầu bổ sung của người dùng. Nút
giữ lại lựa chọn để người dùng xem lại sau đăng nhập; chưa thu tiền, kích hoạt
dịch vụ, ghi dữ liệu thuê bao hay áp dụng hạn mức vào API, AI, Carbon hoặc MRV.
Không đổi backend, xác thực, phân quyền, nhật ký, hàng đợi hoặc đồng bộ offline.

## Lối vào

- Web: thanh điều hướng công khai **Bảng giá** → `/bang-gia`. Có liên kết
  **Bảng giá dịch vụ** ở chân sidebar Management và **Xem bảng giá dịch vụ**
  trong trang Tài khoản nông hộ.
- Android: **Xem bảng giá dịch vụ** ở màn Đăng nhập; **Bảng giá dịch vụ**
  trong tab Tài khoản. Mở `PricingScreen` bằng Navigator, có nút quay lại;
  lựa chọn Nông hộ/Hợp tác xã chỉ thay đổi nội dung hiển thị cục bộ.
- Màn giá Android không khởi tạo dịch vụ, không cần mạng, không đọc hoặc sửa
  thông tin gói hiện tại của tài khoản.

## Chọn gói và đăng nhập

- Web: CTA đi tới `/chon-goi?audience=nong-ho|hop-tac-xa&plan=FREE|PLUS|PRO`.
  Đây là route yêu cầu đăng nhập. Nếu chưa có phiên, chuyển tới `/login?next=…`,
  kèm thông báo tên gói và đối tượng đã chọn. Không lưu mật khẩu hoặc token
  trong URL, không ghi localStorage để giả lập đăng nhập.
- Đăng nhập thành công trở lại đúng lựa chọn. Người đã đăng nhập đi thẳng đến
  bước xem lại sau khi kiểm tra phiên, `/v1/me` và yêu cầu đổi mật khẩu hiện có.
  Trang này dùng chung cho Farmer/Management; chỉ ngoại lệ điều hướng vai trò
  của chính `/chon-goi`, không mở thêm quyền truy cập nghiệp vụ.
- URL chỉ xác định lựa chọn. Giá và quyền lợi được lấy từ danh mục đã có,
  không lấy giá tùy ý từ query. Next URL được giới hạn cùng origin; route chọn
  gói được chuẩn hóa từ danh sách hợp lệ.
- Trang xem lại ghi rõ **chưa phát sinh thanh toán hoặc kích hoạt dịch vụ**;
  người dùng có thể chọn gói khác hoặc vào không gian làm việc hiện có.
- Android: PricingScreen trả lựa chọn qua Navigator. Khi vào từ Đăng nhập,
  trở lại màn Đăng nhập cùng tên gói; AuthGate giữ lựa chọn UI trong bộ nhớ
  qua bước đăng nhập, đổi mật khẩu bắt buộc/khôi phục rồi mới hiện màn xem lại.
  Khi vào từ Tài khoản đã đăng nhập, mở thẳng màn xem lại. Không lưu lựa chọn
  thành thuê bao hoặc trạng thái “đã mua”; lựa chọn không được lưu khi đóng app.

## Mã nguồn

Web: `src/public/pricing.ts` chứa nội dung, `PricingTables.tsx` dựng hai bảng.
Android: `lib/screens/service_plans.dart` chứa cùng nội dung, `pricing_screen.dart`
dựng màn hình. Nội dung Dart được đối chiếu trực tiếp với dữ liệu web: 6 mức giá
và 70 trường chữ khớp nhau. Khi cập nhật chính sách cần sửa đồng bộ hai nguồn.

Web xếp ba thẻ cạnh nhau trên desktop, xếp dọc trên màn hẹp. Android dùng
các thẻ xếp dọc trên điện thoại, có thể chia ba cột trên màn rộng; các nhóm
lựa chọn, giá và tính năng cho phép xuống dòng, không cố định chiều cao thẻ.

## Xác minh

- TypeScript + Vite build: PASS.
- Vitest: **788/788 PASS**, gồm 11 kiểm tra chọn gói/đăng nhập: 6 lựa chọn
  khi chưa có phiên, trở lại sau đăng nhập, Farmer/Manager đã đăng nhập,
  lỗi xác minh tài khoản, lựa chọn/giá/URL không hợp lệ.
- Playwright public-site: **10/10 PASS**, gồm trang giá ở 1440/1024/768/390/360 px,
  giá và số gói, nhảy tới bảng HTX, menu mobile, điều hướng, axe WCAG A/AA và
  bấm cả 6 CTA trên desktop/mobile để xác nhận next URL và thông báo gói đã chọn.
- Đã xem ảnh chụp trang giá desktop và mobile. Không có tràn ngang ở các
  kích thước được kiểm tra; các trang công khai không gọi API riêng tư.
- Android: **chỉ rà soát mã theo yêu cầu người dùng**. Đã định dạng/phân tích
  cú pháp bằng Dart formatter, đối chiếu giá/nội dung, tên icon và đường dẫn
  import, rà soát Navigator, nút quay lại, chọn nhóm và layout co giãn.
  Đã rà soát callback lựa chọn và AuthGate: bước đổi mật khẩu/khôi phục phiên
  vẫn có ưu tiên trước màn xem lại; không sửa AuthController/AuthService.
  **Không tạo/chạy máy ảo, không chạy app, không build APK, không chạy Flutter
  analyze hoặc Flutter tests cho thay đổi này.** Chưa xác minh hiển thị trên thiết bị.

Log và ảnh QA web nằm trong thư mục bị bỏ qua Git
`web-dashboard/reports/pricing-2026-11/`. Người dùng sau đó yêu cầu commit và
push các thay đổi này lên nhánh hiện tại `ui/agricarbon-web-flutter-2026-11-12`.
Không deploy hoặc chạy Android trong lượt xuất bản này.

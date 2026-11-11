# AgriCarbon — cập nhật giao diện 10/11/2026

## Phạm vi

Chỉ thay đổi trình bày React/CSS, nội dung thương hiệu và tài nguyên hình ảnh.
Giữ nguyên API, xác thực, phân quyền, cache, thao tác ghi và công thức nghiệp vụ.
Không thay đổi dependency hoặc lockfile. Lượt thiết kế ngày 10/11 không commit,
push hay deploy; ngày 11/11 người dùng đã yêu cầu commit và push lên
nhánh mới `ui/agricarbon-refresh-2026-11-11`. Không deploy trong lượt bàn giao này.

## Thiết kế

- Hệ màu “Sắc màu đồng bằng”: xanh rừng, xanh lá, xanh nước, xanh ngọc, vàng lúa.
- Nền đa sắc nhẹ, sidebar chung, bề mặt dữ liệu trắng, khoảng cách và bo góc nhất quán.
- Màn đăng nhập và đặt mật khẩu lần đầu dùng chung khung hình ảnh; giữ toàn bộ form,
  thông báo lỗi và thông báo đăng xuất hiện có, kể cả trường hợp máy chủ chưa xác nhận.
- Slogan: **Số hóa canh tác - Xanh hóa tương lai**.
- Banner thương hiệu ở Tổng quan Farmer và Management; không thêm số liệu hoặc tuyên bố carbon.
- Đồng bộ bảng, bộ lọc, tab, ô nhập, thẻ ruộng, tài khoản và hộp thoại.
- Animation ngắn cho nội dung/hộp thoại và phản hồi nút; họa tiết lúa/gợn nước ở đăng nhập.
  Tôn trọng `prefers-reduced-motion`; không thêm thời gian chờ vào xác thực.
- Container trang chỉ animate opacity; animation khác không giữ transform sau khi
  kết thúc, để các overlay fixed vẫn bám viewport.
- Palette nằm trong `src/theme.css` để bundle Farmer tải sau không khôi phục màu cũ.
  Quy tắc bố cục nằm riêng trong `src/visual-refresh.css`.

## Tài nguyên

`public/visuals/mekong-rice.webp` là hình minh họa tạo bằng AI cho AgriCarbon,
không phải ảnh xác minh của một nông trại cụ thể. Kích thước 1536×1024,
248.252 byte. Được lưu cùng dự án, không phụ thuộc URL ảnh bên ngoài.
`public/visuals/brand-mark.svg` là biểu tượng mầm cây dùng cho favicon.

## Kiểm tra

- TypeScript + Vite production build: PASS.
- Vitest: **768/768**, 95 tệp, chạy `npm test -- --maxWorkers=2`.
- Playwright: **19/19**, smoke Management, các luồng Farmer, kiểm tra visual refresh.
- 13 route × 5 viewport: 1440, 1024, 768, 390, 360 px; không tràn ngang,
  giữ một h1 và vùng nội dung chính ở mỗi route.
- Axe WCAG A/AA: không phát hiện vi phạm trên hai trang Tổng quan và
  màn đăng nhập ở cả năm viewport. Đây là kiểm tra tự động trên mock data.
- Kiểm tra Tab vào email/mật khẩu, tải ảnh, reduced motion, mở/đóng hộp thoại.
- Đã xem ảnh chụp desktop/mobile của đăng nhập và Farmer.
- Sandbox chặn font Google có sẵn của ứng dụng: kiểm tra browser được chạy lại
  ngoài sandbox. Một lượt Vitest chạy đồng thời build/browser gặp 3 timeout;
  lượt chạy riêng với 2 worker đạt 768/768. Không nới timeout hay sửa test cũ.
- Test animation mới phát hiện transform identity do animation giữ lại có thể đổi
  containing block của fixed overlay: đã sửa bằng fade thuần trên container trang.
  Một lượt browser chạy cùng build bị timeout tải lazy bundle ở Home; lượt cuối
  chạy riêng đạt 19/19, không retry hoặc tăng timeout của test cũ.

## Bản xem local

Vite tại `http://127.0.0.1:5173`, bật mock bằng biến môi trường của tiến trình,
không sửa cấu hình sản phẩm hoặc tạo `.env`.

- `/login`: xem thiết kế đăng nhập; chưa cấu hình đăng nhập thật trong phiên này.
- `/farmer`: dữ liệu minh họa và các trang Farmer.
- `/dashboard`: Management; tài khoản mock mặc định chưa có organization nên
  trang này hiển thị trạng thái chưa gắn HTX. Route/table/form khác đã được
  kiểm tra bằng smoke và fixture hiện có; không thay logic mock để tạo tài khoản.

Không chạy hosted E2E và không ghi dữ liệu lên Supabase.

## Bàn giao

STATUS: DONE. Đã mở hai tab `/login` và `/farmer` trên trình duyệt.
Server mock tại cổng 5173 được giữ chạy cho người dùng kiểm thử giao diện.
Ngày 11/11/2026 người dùng đã duyệt giao diện và yêu cầu đưa lên nhánh mới
`ui/agricarbon-refresh-2026-11-11`. Nhánh `chinh-sua-giao-dien` đã tồn tại và
còn một bản sửa font từ tháng 9; hợp nhất
lịch sử nhánh với nền `main` mới nhất, giữ Be Vietnam Pro có hỗ trợ tiếng Việt
và font tải không chặn render của bản hiện tại. Không force-push hoặc deploy.

Đã kiểm tra lại sau hợp nhất ngày 11/11/2026: build PASS, Vitest 768/768,
Playwright mock 19/19. Lịch sử nhánh giao diện cũ được giữ lại qua merge;
chỉ nhánh mới được xuất bản, không push thay đổi vào `main` hoặc nhánh cũ.

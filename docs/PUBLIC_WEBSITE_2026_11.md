# AgriCarbon — trang công khai trước đăng nhập (12/11/2026)

## Yêu cầu và phạm vi

Trang đầu khi truy cập tên miền là trang giới thiệu AgriCarbon. Người dùng chọn
Đăng nhập để vào luồng xác thực hiện có. Có điều hướng Nền tảng, Dịch vụ,
Báo cáo, Bảng giá, Tin tức; thiết kế riêng, tham khảo cách tổ chức thông tin của
https://www.carbonglobal.vn và ảnh người dùng cung cấp.

Người dùng xác nhận chưa có bảng giá chính thức: hiển thị **Chưa công bố giá**.
Không tạo giá, chứng nhận, đối tác, số liệu giảm phát thải hoặc tin sự kiện giả.
Không sao chép nội dung, logo, ảnh, chứng nhận SGS hoặc số liệu của website tham khảo.

Chỉ sửa frontend và tài nguyên tĩnh. Không sửa backend, API, cách xác thực,
phân quyền, cơ sở dữ liệu, nghiệp vụ Dashboard hoặc cấu hình triển khai.

## Đường dẫn

| Đường dẫn | Nội dung |
|---|---|
| `/` | Trang chủ: hình đồng lúa, slogan, chức năng, quy trình, đối tượng, bài viết |
| `/nen-tang` | Giới thiệu nền tảng và các bước tương tác bằng chuột/bàn phím |
| `/dich-vu` | Nhóm giải pháp thực có: nhật ký, tài nguyên, carbon, MRV, ảnh lá, HTX |
| `/bao-cao` | Tài liệu giới thiệu Markdown, biểu mẫu CSV, lối vào hệ thống |
| `/bang-gia` | Phạm vi cho nông hộ, HTX, đơn vị theo dõi; chưa công bố giá |
| `/tin-tuc` | Bài hướng dẫn của nhóm, lọc chuyên mục và tìm kiếm |
| `/tin-tuc/:slug` | Nội dung bài viết; slug không có thì hiển thị trang báo rõ |
| `/login` | Giữ luồng đăng nhập hiện có; thêm liên kết trở về trang chủ |

Mỗi trang công khai có một h1, tiêu đề tab riêng, menu desktop/mobile và footer.
Các bài viết là nội dung hướng dẫn tự biên soạn, không được ghi thành tin sự kiện
hay cập nhật bên ngoài chưa kiểm chứng. Hai tệp tải xuống là tài liệu giới thiệu
và biểu mẫu chuẩn bị, không phải hồ sơ thực tế hoặc mẫu thẩm định chính thức.

## Ranh giới với ứng dụng

`AppEntry` phân loại trang công khai trước khi mount `AppRoot`. Trang công khai
không khởi chạy effect khôi phục phiên, đọc `/v1/me`, scope, metrics hay dashboard.
Khi người dùng chọn đăng nhập, `AppRoot` hoạt động như trước và tự xác minh quyền.
Các đường dẫn `/dashboard`, `/farmer/**`, `/mrv`, `/accounts/**` không thuộc tập
route công khai. Người đang có phiên vẫn có thể xem trang giới thiệu.

`routeName('/')` đổi từ dashboard sang public; Management vẫn ở `/dashboard`.
History Back/Forward được lắng nghe tại ranh giới public/private. Các liên kết
đến mục cụ thể của trang Dịch vụ dùng hash và cuộn tới đúng phần.

CSS mới nằm dưới `.public-site`, ngoài hai quy tắc dành cho liên kết về trang
chủ của màn đăng nhập. Không thêm dependency. Hình minh họa đồng lúa tái sử dụng
asset AI của lần thiết kế 10/11, không đại diện một nông trại thực được xác minh.

Hosting đã có rewrite `/*` về `/index.html` trong `render.yaml`; không cần đổi
hosting cho các đường dẫn frontend mới. Không deploy trong lượt này.

## Kiểm tra

- Build TypeScript + Vite: PASS ở bản cuối.
- Vitest: 777/777, gồm 9 kiểm tra mới về public/private boundary và điều hướng.
- Playwright: **28/28**, gồm 9 test public-site và 19 test smoke Farmer/Management,
  visual refresh hiện có. 35 public route/viewport views tại 1440/1024/768/390/360.
- Menu đóng bằng Escape hoặc chọn trang; điều hướng Back/Forward và liên kết
  tới phần Dịch vụ hoạt động. Nhãn giá được tách khỏi chú thích để dễ đọc/kiểm tra.
- Tab quy trình dùng ArrowLeft/ArrowRight/Home/End; lọc và tìm bài viết, mở bài,
  báo bài không có, tải CSV/Markdown và xử lý hash không hợp lệ đã kiểm tra.
- Axe không phát hiện vi phạm WCAG A/AA trên 7 route công khai ở desktop/mobile.
  Đã chỉnh hai màu chữ nhỏ/đánh số để đạt tương phản, không bỏ qua quy tắc.
- Test xác nhận các trang công khai không phát sinh request `/v1/*` hoặc `/health`;
  DOM test xác nhận không khôi phục phiên hoặc đọc tài khoản trước khi vào ứng dụng.
- Đã xem ảnh chụp đầy đủ trang chủ desktop và mobile. Preview/asset trả HTTP 200.
- CSV có BOM UTF-8 để giữ tiếng Việt khi mở bằng phần mềm bảng tính trên Windows.

## Bàn giao

STATUS: DONE. Preview local tại `http://127.0.0.1:5173/`, server được giữ chạy
để người dùng kiểm thử. Ownership đã release. Người dùng sau đó yêu cầu commit
và push toàn bộ giao diện web/Flutter lên nhánh mới
`ui/agricarbon-web-flutter-2026-11-12`. Tên miền thật chưa thay đổi cho tới khi có
triển khai; lượt này không deploy.

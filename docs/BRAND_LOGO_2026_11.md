# Logo AgriCarbon — 13/11/2026

## Kết quả

Thay biểu tượng mầm cây tạm bằng logo chữ A xanh và bông lúa người dùng gửi.
Giữ tên AgriCarbon, slogan, liên kết điều hướng và các chức năng hiện có.

- Web dùng chung BrandMark ở sidebar Farmer/Management, đăng nhập, header và
  footer trang công khai. Favicon dùng cùng ảnh.
- Flutter dùng ảnh trong BrandMark chung của header và phần thương hiệu đăng
  nhập. Không đổi biểu tượng launcher Android/iOS.
- Logo giữ tỷ lệ bằng `object-fit: contain` / `BoxFit.contain`, có nền trắng,
  viền nhẹ và khoảng đệm. Mép 2% được ẩn khi hiển thị để bỏ dấu góc của ảnh chụp;
  tệp ảnh gốc không được sửa pixel. Flutter dùng clip và scale 1.04 tương ứng.

## Tài nguyên cuối cùng

Hai tệp dưới là cùng ảnh đính kèm gốc **428 × 428**, **106.345 byte**:

- `web-dashboard/public/visuals/agricarbon-logo.png`
- `app/assets/images/agricarbon-logo.png` (đã khai báo trong pubspec)

SHA-256 của cả hai:
`35eaf7586c0911fa749321c5a32b0de893b3e5687bfdd72f83eb1684e780e9bb`.

Đã thử built-in imagegen để tách nền nhưng không chọn các bản xử lý làm asset
sản phẩm: cuối cùng dùng trực tiếp ảnh gốc để giữ đúng nhận diện và giảm dung
lượng. Bản thử nghiệm được giữ ngoài thư mục tài nguyên phát hành.

## Xác minh

- Web TypeScript/Vite build **PASS**; Vitest **788/788 PASS** (`--maxWorkers=2`).
- Public-site và visual-refresh Playwright kiểm tra trang công khai, sidebar,
  đăng nhập, bàn phím, độ tương phản, reduced motion và các chiều rộng
  1440/1024/768/390/360 px: **18/18 PASS** (`--workers=1`). Đã xem ảnh chụp
  header/footer desktop, sidebar và đăng nhập mobile. Lần chạy đồng thời ban đầu
  có timeout; chạy lại tuần tự đạt mà không tăng timeout hay sửa ngưỡng kiểm tra.
- Tổng bản phát hành web: **1.188.482 byte**; dùng ảnh gốc 106 KB thay vì bản
  imagegen lớn. Không đổi chính sách CI/bundle.
- Flutter chỉ định dạng/rà soát mã, đối chiếu đường dẫn asset, manifest và hash.
  Không chạy máy ảo, app, build hoặc Flutter analyze/test cục bộ.
- Không sửa auth/backend. Sau khi hoàn tất, người dùng yêu cầu commit/push phần
  logo lên nhánh `ui/agricarbon-web-flutter-2026-11-12`; không deploy trong lượt này.

## PR và CI

- PR logo: https://github.com/levuanh2/TEC2026/pull/76, vào `main`.
- Lượt CI đầu phát hiện khai báo ảnh trong `app/pubspec.yaml` thuộc guarded
  paths, cần trailer `CI-Policy-Change` trong một commit của PR. Commit bổ sung
  tài liệu cung cấp lý do: chỉ đăng ký asset logo, không đổi dependency, cấu
  hình đo coverage hoặc ngưỡng CI. Giữ nguyên lịch sử, không amend/force-push.
- Kết quả CI cuối cùng xem tại Checks của PR. Không chạy Android cục bộ,
  không merge hoặc deploy trong lượt mở PR này.

## Prompt của các bản imagegen thử nghiệm

Built-in, không dùng CLI. Các ảnh thử nghiệm không được tham chiếu bởi ứng dụng.

1. `Use case: background-extraction. Edit target: the FIRST image in the latest user message, the standalone AgriCarbon logo (green folded leaf ribbon forming a capital A, with one golden rice ear diagonally crossing it). The second image is ONLY context showing the old website header, not an image to reproduce. Extract the exact supplied logo into a clean production PNG on a genuinely transparent background. Remove the white background, screenshot edge/corner marks, and all blank padding beyond a small balanced margin. Preserve the original A silhouette, leaf folds, golden rice grain shapes, green/gold colors, shading and proportions as faithfully as possible. Do not redesign, simplify, stylize, add text, add a container, or add any element. Output only the centered isolated A-and-rice symbol, with a square canvas and approximately 6 percent transparent safe margin around the symbol. This is an existing brand identity to preserve, not a logo exploration.`
2. `Use case: precise-object-edit / production asset export. Input image: the already approved AgriCarbon A-and-rice logo, edit target. Export this EXACT same isolated green folded-leaf A and golden rice ear as a SMALL 256 x 256 pixel transparent PNG for a website header and mobile app header. This request is ONLY to reduce canvas/output resolution for a lightweight UI icon. Preserve the source composition, silhouette, rice grain count and arrangement, colors, shading, and aspect ratio. Do not redraw the mark or add/remove any element. Keep genuinely transparent background and about 6% balanced safe margin. CRITICAL output delivery size: 256 x 256 pixels; do not return a large 1024/1254 pixel canvas.`

# Figma Audit — Final (this task)

User: Figma là tham khảo, không phải khối chặn — nếu không phù hợp thì dùng nguồn khác.
Không tiếp tục chờ OAuth trong task này.

## Trạng thái truy cập

- OAuth in-chat (`mcp__figma__authenticate`) đã gửi link cho user, **chưa có callback** —
  không chặn task, không retry thêm.
- Dữ liệu thật đã có từ trước (REST API + PAT, cùng ngày): 1/26 frame đầy đủ (Design
  System `8:1153`), 25 frame còn lại chỉ biết tên+node-id, chưa đọc nội dung (quota tài
  khoản đó chết tới ~14/09).

## Dùng làm gì trong redesign

**Design tokens đã xác minh thật** (không suy đoán) — dùng làm nguồn cho Phase 8-9:

| Token | Giá trị | Đã áp dụng vào code chưa |
|---|---|---|
| Màu chính | `#2f7d5b` | Có — `--brand` trong `styles.css` |
| Màu nền tối | `#123c31` | Có — `--brand-dark` |
| Nền phụ xanh/xanh dương | `#eaf4ef` / `#eaf3f7` | Có — `--surface-green` / `--surface-blue` |
| Cảnh báo/lỗi | `#fff4df` / `#fceaea` | Có — `--warning-bg` / `--error-bg` |
| Typography | Inter, H1 30/700, H2 20/700, body 14/400, caption 12/400 | Có |
| Layout | sidebar 230px cố định, card radius 12-16px, gap 16-24px | Có — `--sidebar-width`, `--radius-card`, `--gap-card` |
| Quy tắc rõ ràng (text layer thật trong file) | "Dữ liệu carbon luôn có khả năng drill-down: activity → emission factor → version → audit trail" | Có — drill-down `factors_used`/`provenance`/`parameter_status` đã build (round 4) |
| Quy tắc | "Tài khoản luôn nằm cuối sidebar: avatar, họ tên, vai trò" | Có — avatar đã thêm (round 5) |

**Chưa xác minh** (không có nội dung frame thật): layout chi tiết Dashboard, Organization,
Farm, Plot, Crop Season, Activities, Metrics, Carbon, MRV, Navigation — 9 frame quan trọng
cho task redesign này KHÔNG có ảnh/structure thật để đối chiếu.

## Quyết định cho redesign lần này

Theo đúng chỉ đạo user ("chỉ tham khảo, không phù hợp thì xài khác"): áp dụng token đã
xác minh (màu/font/spacing/layout-rule ở trên), còn **layout/information-architecture chi
tiết của từng màn dùng UX judgment trực tiếp** (Phase 7-9 dưới), không chờ/không bịa
Figma. Nếu OAuth hoàn tất trong lúc làm, việc tiếp theo là đối chiếu lại (fidelity-check),
không phải thiết kế lại từ đầu.

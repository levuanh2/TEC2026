# AI Tooling Plan — Web Dashboard Redesign

Ngày: 2026-09-09. Kiểm thật danh sách skill/plugin/MCP có trong phiên này
(`Skill` tool listing + `ToolSearch`), không đoán tên nghe hợp.

| Skill/Plugin/MCP | Purpose | Why needed | Where used | Priority | Available? |
|---|---|---|---|---|---|
| **Figma MCP** (`mcp__figma__*`) | Đọc structure/token/frame thật từ file Figma | Nguồn sự thật duy nhất cho UX redesign (Phase 6-9) — không tự vẽ trước rồi mới xem | Phase 6 (Figma audit), Phase 22 (visual regression) | **MUST USE** | Vừa cấu hình lại (`claude mcp add`) + khởi động OAuth in-chat (`mcp__figma__authenticate`) — **đang chờ user hoàn tất bước duyệt trình duyệt**. Lần trước bị chặn quota tài khoản (Retry-After ~4.6 ngày, ETA ~14/09) khi dùng cùng account qua REST+PAT; OAuth lần này CÓ THỂ là account khác nếu user đăng nhập khác — chưa biết cho tới khi họ duyệt. |
| **Playwright** (chưa cài) | Browser automation thật: click-through, console/network log, screenshot | Duy nhất cách thật sự "browser verified" thay vì tiếp tục ghi UNAVAILABLE — không có tool này project không có cách nào tự động click | Phase 21 (browser smoke), Phase 22 (visual regression) | **MUST USE** | KHÔNG cài trong task audit này (giữ đúng "không code trước Phase 5") — cài `@playwright/test` là việc đầu tiên của phase implementation kế tiếp, không phải phase audit |
| `claude-in-chrome` | Điều khiển Chrome thật của user qua extension | Cách khác để browser-test nếu Playwright không tiện cài (không cần thêm devDependency vào repo) | Thay thế Playwright nếu user đã có extension + cấp quyền site | SHOULD USE (thay thế, không dùng song song) | Không rõ user đã cài/cấp quyền extension chưa — cần hỏi trước khi chọn nhánh này thay Playwright |
| `.agents/skills/supabase`, `.agents/skills/supabase-postgres-best-practices` | Best-practice Supabase/Postgres (RLS, indexing, pagination, N+1) | Đã dùng NGẦM suốt dự án (RLS-replay pattern, tránh N+1 khi đọc 7 bảng chi tiết) — nhưng khai báo trong `skills-lock.json` KHÔNG xuất hiện trong danh sách skill khả dụng của `Skill` tool phiên này | Backend đã freeze — không áp dụng thêm trong task Web này | OPTIONAL | Không xác nhận được là invokable qua `Skill` tool lúc này (không có trong listing) — không chặn task vì backend không đổi |
| `gsd-ui-phase` / `gsd-ui-review` | Sinh UI-SPEC.md / audit 6-pillar UI đã build | Nghe đúng tên nhưng cả 2 đều thuộc hệ **GSD** (Get-Shit-Done), kỳ vọng cấu trúc `.planning/` (roadmap, phase, milestone) — repo này KHÔNG phải GSD project | Không dùng | **NOT NEEDED** | Có cài nhưng sai ngữ cảnh — ép dùng sẽ tạo cấu trúc `.planning/` không cần thiết cho 1 repo không theo quy trình GSD |
| `security-review` | Review bảo mật trước khi merge | Đã có quy trình thủ công riêng suốt dự án (git grep secret pattern + git log --all -p + kiểm `.env`/`.gitignore`), đã chứng minh bắt được leak thật (`f5c34e8`) | Có thể dùng lại ở Phase 30 nếu muốn 1 lượt review độc lập | OPTIONAL | Có sẵn — không bắt buộc vì quy trình thủ công đã đủ và đã verify hoạt động |
| `code-review` | Review diff trước commit | Đã tự làm thủ công (đọc diff + chạy test) mọi round trước đó trong dự án này, kể cả review code Codex viết | Có thể dùng cho lượt review cuối trước khi merge redesign UI | OPTIONAL | Có sẵn |
| `design` (Claude Design canvas) | Vẽ mockup mới từ đầu dưới dạng Artifact | KHÔNG cần — đã có Figma thật + React app thật chạy thật; vẽ mockup song song sẽ tạo 2 nguồn sự thật cạnh tranh, đúng thứ Phase 6 cấm ("không tự thiết kế trước rồi mới xem Figma") | — | **NOT NEEDED** | Có sẵn, cố tình không dùng |
| `dataviz` | Hướng dẫn thiết kế chart/dashboard | Phase 9 nói rõ "Không dùng chart nếu table rõ hơn" — dashboard này ưu tiên KPI/table theo đúng tinh thần PRD (số liệu chính xác hơn hình đẹp); nếu SAU audit xác định cần 1-2 chart thật (vd so sánh farm) thì mới cần | Có thể cần ở Phase 8/11 nếu quyết định thêm biểu đồ so sánh farm | SHOULD USE (có điều kiện) | Có sẵn — chỉ dùng nếu quyết định thêm chart, chưa quyết ở audit này |
| `superpowers:brainstorming` | Explore ý định trước khi code feature mới | Task này đã có brief cực chi tiết (31 phase) — không cần brainstorm thêm, brief đã LÀ kết quả brainstorm | — | NOT NEEDED | Có sẵn, không áp dụng vì đã có spec rõ |
| `artifact-design`/`artifact-diagramming` | Thiết kế Artifact (trang HTML publish qua claude.ai) | Web dashboard là React app thật deploy riêng, không phải Artifact — không áp dụng | — | NOT NEEDED | — |

## Quyết định

Không cài/dùng chồng chéo nhiều tool cho cùng 1 việc. Cho browser testing: **Playwright**
là lựa chọn chính (script hoá được, chạy trong CI sau này); `claude-in-chrome` chỉ dùng
nếu user xác nhận đã có extension sẵn và muốn dùng phiên trình duyệt thật của họ thay vì
cài devDependency. Không dùng cả 2 song song.

Figma: chờ user hoàn tất OAuth (`mcp__figma__authenticate` đã gửi link). Nếu vẫn dính
đúng account bị quota — dùng lại design token đã xác minh từ REST+PAT trước đó
(`docs/FIGMA_WEB_IMPLEMENTATION.md`), không retry vô hạn.

## Round 7 (2026-09-09) — Product-level UX/UI redesign: tooling THỰC TẾ đã dùng

| Tool | Có sẵn trong phiên? | Đã dùng? | Ghi chú |
|---|---|---|---|
| Figma MCP (`mcp__figma__*`) | KHÔNG (OAuth chưa callback, account cũ vẫn quota tới ~14/09) | Không | Dùng design token đã verify (`docs/FIGMA_WEB_IMPLEMENTATION.md`) + UX judgment cho 9 layout — đúng chỉ đạo "Figma chỉ tham khảo". Không giả pixel-fidelity. |
| Playwright (`@playwright/test`) | Có (đã cài round 6) | **Có** | `web-smoke.spec.ts` viết lại theo IA mới (mock tenant) + script screenshot QA 3 breakpoint (1440/1024/768, throwaway, không commit). |
| `Skill` listing / `ToolSearch` | Có | Có | Rà skill: `design`/`dataviz`/`artifact-*` — quyết định KHÔNG dùng (React app thật, không phải Artifact; brief §5/§9 ưu tiên KPI/table hơn chart trang trí). `code-review`/`security-review` để dành cho lượt review cuối, không bắt buộc. |
| `claude-in-chrome` | Không xác nhận extension | Không | Playwright đã đủ; không dùng song song. |
| Backend local (uvicorn + hosted Supabase) | Có (backend/.env có service role + hosted URL) | Một phần | Boot được `:8010`, verify `/health` + `/v1/carbon/scenarios` shape thật + backend pytest 136/136. KHÔNG có user JWT cho demo tenant (mật khẩu demo user random, không lưu; reset password bị chặn) → **authenticated browser test = NOT RUN**. |

Kết luận: không phát sinh tool mới. Redesign dựa trên design token đã verify + API contract
đã freeze + Playwright mock smoke. Real-API authenticated browser QA vẫn NOT RUN vì thiếu
credential đăng nhập demo tenant (đúng nhánh "Không giả" của brief §26).

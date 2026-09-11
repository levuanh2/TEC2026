# Herdr Collaboration

Bạn có thể đang chạy song song với một Codex agent trong pane Herdr khác, cùng
repo này. Chi tiết protocol phối hợp đầy đủ (ownership, round log, completion
format) nằm ở `AGENTS.md` — đọc file đó, áp dụng cho cả Claude lẫn Codex.

Quan trọng: Claude Code `ListAgents` KHÔNG phải nguồn phát hiện Codex —
`ListAgents` chỉ thấy session Claude khác, không thấy Codex. Đừng kết luận
"không thấy Codex" chỉ vì `ListAgents` không liệt kê nó.

Khi user nhắc:
- "Codex bên cạnh"
- "Codex đang làm gì"
- "hỏi Codex"
- "đọc Codex"
- "phối hợp với Codex"

thì PHẢI discover qua Herdr trước, không dùng `ListAgents` cho việc này.

## Workflow

1. `git status --short` — xem file nào đang dirty.
2. Discover pane Codex/Claude khác cho repo này (pane ID đổi mỗi session,
   không hardcode):
   - `herdr agent list` rồi lọc theo `cwd` == repo root, hoặc
   - `.\.herdr\status.ps1` (liệt kê), `.\.herdr\read-codex.ps1` (đọc output gần nhất)
3. Xác định: task hiện tại, file đang sửa, ai own file nào, trạng thái
   idle/working/blocked/done (`agent_status` trong JSON, hoặc cột trong
   `.herdr\status.ps1`).
4. Trước khi sửa file đang dirty/shared: theo bảng "File ownership" trong
   `AGENTS.md`, không đè lên thay đổi CHƯA COMMIT của Codex.
5. Gửi message qua `.\.herdr\send-codex.ps1 "<text>" -Wait` hoặc
   `herdr agent prompt <pane_id> "<text>" --wait --timeout <ms>` khi cần
   trao đổi.

Không bao giờ nói "tôi không thấy được Codex" trước khi đã thử discover qua
Herdr.

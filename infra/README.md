# infra/ — Môi trường & triển khai

Chưa cần hạ tầng thật ở giai đoạn MVP. Backend chạy local hoặc 1 VPS nhỏ là đủ cho
demo TEC2026. Thư mục này giữ chỗ và ghi các biến môi trường cần thiết.

## Biến môi trường

| Biến | Dùng ở đâu | Ghi chú |
|---|---|---|
| `AGRICARBON_DB_URL` | backend | Mặc định SQLite local |
| `AGRICARBON_EF_CONFIG` | backend | Đường dẫn `backend/config/emission_factors.yaml` |
| `AGRICARBON_API_BASE` | app, web-dashboard | URL backend để đồng bộ |

Copy sang `.env` khi cần; `.env` đã bị gitignore.

## Triển khai

Chưa chốt. Quyết định sau khi 1a chạy end-to-end — đừng dựng CI/CD, Docker, K8s
trước khi có thứ để deploy.

# Luồng nông hộ

Nông hộ đi qua cùng một vòng dữ liệu trên hai ứng dụng, nhưng **cách dữ liệu đi
tới server khác nhau**: Flutter ghi offline rồi đồng bộ thẳng vào Supabase; Farmer
Web ghi trực tuyến qua FastAPI.

## Vòng làm việc chung

```mermaid
flowchart TB
    subgraph Scope["1. Chọn phạm vi"]
        direction LR
        L["Đăng nhập"] --> F["Chọn nông hộ"] --> P["Chọn thửa"] --> S["Chọn vụ canh tác"]
    end
    subgraph Record["2. Ghi nhận"]
        direction LR
        A["Ghi hoạt động<br/>gieo sạ, bón phân, tưới,<br/>thuốc BVTV, rơm rạ"] --> H["Ghi thu hoạch<br/>yield_kg"]
    end
    subgraph Review["3. Xem kết quả"]
        direction LR
        R["Chỉ số tài nguyên/kg"] --> C["Carbon của vụ"] --> K["Khuyến nghị"]
    end
    S --> A
    H --> R
    K -->|"ghi thêm / vụ tiếp theo"| A
```

Khả năng thực tế theo từng ứng dụng:

| Bước | Flutter Mobile | Farmer Web |
|---|---|---|
| Đăng nhập | Supabase Auth | Supabase Auth |
| Farm / thửa / vụ | Kéo farm/thửa/vụ về SQLite; **tạo được thửa và vụ** (upsert lên Supabase) | Chỉ đọc (`GET /v1/farmer/scope`) |
| Ghi hoạt động | 7 loại, gồm `fuel`; offline được | 6 loại (không có `fuel`); cần mạng; vụ phải `active` và có đúng một lô mở |
| Sửa / xoá | Có; xoá bản đã đồng bộ bằng RPC `soft_delete_activity` | Có; chỉ bản do chính mình ghi |
| Chỉ số tài nguyên | `GET /v1/crop-seasons/{id}/metrics` | `GET /v1/crop-seasons/{id}/metrics` |
| Carbon | Xem và **gọi tính** (`POST /v1/carbon/calculate`) | **Chỉ xem** bản tính đã lưu |
| Khuyến nghị | Chưa nối (màn hình báo "chưa cấu hình") | Xem, cập nhật, chấp nhận / bỏ qua |
| Kiểm tra lá lúa (CV) | Chưa nối (màn hình báo "chưa cấu hình") | Upload ảnh, xem lịch sử |

## Flutter: luồng offline

```mermaid
flowchart TB
    subgraph Device["Trên thiết bị"]
        U["Nông hộ nhập form"] --> DB[("SQLite<br/>sync_state = pending")]
        DB --> Q["Hàng đợi = hàng pending / failed"]
    end
    subgraph Trigger["Kích hoạt đồng bộ"]
        T1["Đăng nhập"]
        T2["App trở lại foreground"]
        T3["Có mạng lại<br/>debounce 2 giây"]
        T4["Nút Gửi dữ liệu ngay"]
    end
    subgraph Push["SyncService.syncAll (single-flight)"]
        P1["1. plots<br/>upsert farm_id, plot_code"]
        P2["2. crop_seasons<br/>upsert plot_id, season_code"]
        P3["3. lô default của vụ"]
        P4["4. activities<br/>theo device_id, client_event_id"]
        P5["5. bảng chi tiết<br/>upsert activity_id"]
        P1 --> P2 --> P3 --> P4 --> P5
    end
    subgraph Server["Supabase"]
        RLS["PostgREST + RLS"]
    end
    Q --> Trigger
    Trigger --> Push
    Push --> RLS
    RLS -->|"thành công"| OK["sync_state = synced<br/>lưu server_id"]
    RLS -->|"lỗi"| ERR["sync_state = failed<br/>ghi mã lỗi, thử lại lượt sau"]
```

Chi tiết cài đặt: [Flutter Mobile](../modules/flutter-mobile.md).

## Farmer Web: luồng trực tuyến

```mermaid
flowchart TB
    subgraph Browser["Trình duyệt"]
        FORM["Form hoạt động<br/>ActivityForms.tsx"]
        KEY["idempotency_key UUID<br/>giữ nguyên khi gửi lại"]
        FORM --> KEY
    end
    subgraph API["FastAPI"]
        R1["POST /v1/crop-seasons/id/activities"]
        S1["ActivityWriteService<br/>role farmer · RLS đọc vụ<br/>vụ active · đúng 1 lô mở"]
        W1["PostgresActivityWriteRepository<br/>1 transaction: activities + chi tiết"]
        R1 --> S1 --> W1
    end
    subgraph DB["PostgreSQL"]
        T[("activities<br/>source = web")]
    end
    KEY -->|"Bearer JWT"| R1
    W1 --> T
    T -->|"201 hoặc idempotent_replay"| REF["Web làm mới nhật ký và chỉ số"]
```

Ngày hoạt động trên Farmer Web được gửi dưới dạng `YYYY-MM-DDT00:00:00Z`
(`farmer/ActivityForms.tsx`): form chỉ chọn **ngày**, không chọn giờ.

## Sau khi ghi dữ liệu

- **Chỉ số tài nguyên** tính lại ở lần đọc kế tiếp (không có snapshot).
- **Carbon không tự tính lại.** Bản tính đã lưu giữ nguyên cho tới khi có người gọi
  `POST /v1/carbon/calculate` (Management Web, Flutter). Với YAML hiện tại, lời gọi
  này dừng ở `422 missing_emission_factor`.
- **Khuyến nghị** chỉ sinh lại khi Farmer Web gọi
  `POST /v1/crop-seasons/{id}/recommendations/generate` (nút "Cập nhật khuyến nghị"
  hoặc làm mới nền khi dữ liệu cũ); lần mở trang chỉ đọc bản đã lưu.

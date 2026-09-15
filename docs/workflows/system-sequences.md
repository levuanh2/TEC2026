# Sequence diagram hệ thống

Tám sequence diagram dưới đây bám theo code hiện tại. Mỗi sơ đồ chỉ giữ các bước
quyết định hành vi; chi tiết lỗi nằm trong trang module tương ứng.

## 1. Login / auth

```mermaid
sequenceDiagram
    autonumber
    actor U as Người dùng
    participant W as Web (React)
    participant SA as Supabase Auth
    participant API as FastAPI
    participant PR as PostgREST + RLS

    U->>W: Nhập email + mật khẩu
    W->>SA: signInWithPassword
    SA-->>W: session + access_token
    W->>W: setAccessToken(token)
    W->>API: GET /v1/me với Bearer JWT
    API->>SA: auth.get_user(JWT)
    API->>PR: profiles, organization_memberships, farm_members bằng JWT
    PR-->>API: hàng RLS cho phép
    API-->>W: user_id, roles, memberships
    W->>W: chọn role theo thứ tự cooperative_manager, enterprise_viewer, regulator, farmer
    alt role farmer
        W->>W: mở khu /farmer
    else role khác
        W->>W: mở /dashboard
    end
```

Flutter đăng nhập bằng `supabase_flutter`; client Supabase tự gắn JWT khi gọi
PostgREST, còn lời gọi FastAPI gắn Bearer JWT thủ công.

## 2. Farmer thêm activity qua Web

```mermaid
sequenceDiagram
    autonumber
    actor F as Nông hộ
    participant W as Farmer Web
    participant API as FastAPI
    participant AWS as ActivityWriteService
    participant RR as SupabaseReadRepository
    participant WR as PostgresActivityWriteRepository
    participant DB as PostgreSQL

    F->>W: Điền form, bấm Lưu
    W->>W: tạo idempotency_key UUID (giữ nguyên khi thử lại)
    W->>API: POST /v1/crop-seasons/id/activities + JWT
    API->>API: validate schema theo activity_type
    API->>AWS: create
    AWS->>RR: me() → roles phải có farmer
    AWS->>RR: season(id) qua RLS
    AWS->>RR: production_batches(id) qua RLS
    alt vụ không active hoặc không đúng 1 lô mở
        API-->>W: 422 invalid_crop_season_state
    end
    AWS->>WR: create(batch, actor, key, data)
    WR->>DB: tìm (recorded_by, web_idempotency_key)
    alt đã có, cùng dữ liệu
        WR-->>AWS: bản ghi cũ, replay = true
    else đã có, khác dữ liệu hoặc đã xoá
        API-->>W: 409 duplicate_event
    else chưa có
        WR->>DB: INSERT activities source web
        WR->>DB: INSERT bảng chi tiết
        WR-->>AWS: bản ghi mới
    end
    API-->>W: 201 ActivityWriteResponse
    W->>API: đọc lại nhật ký và metrics
```

## 3. Flutter offline sync

```mermaid
sequenceDiagram
    autonumber
    participant CO as SyncCoordinator
    participant SS as SyncService
    participant DB as SQLite
    participant DS as DeviceService
    participant GW as SupabaseSyncGateway
    participant PR as PostgREST + RLS

    CO->>CO: trigger (login, resume, có mạng, thủ công)
    CO->>SS: syncAll (single-flight)
    SS->>DB: plots cần gửi
    SS->>GW: upsert plots theo farm_id, plot_code
    GW->>PR: upsert
    SS->>DB: đánh dấu synced / failed
    SS->>DB: crop_seasons cần gửi (hoãn nếu thửa chưa có server_id)
    SS->>GW: upsert crop_seasons theo plot_id, season_code
    SS->>DB: activities cần gửi
    SS->>DS: ensureServerDeviceId
    DS->>PR: đăng ký hoặc lấy devices.id
    loop mỗi activity
        alt tombstone đã đồng bộ
            SS->>GW: rpc soft_delete_activity
            GW->>PR: RPC
            SS->>DB: xoá hàng local khi server xác nhận
        else ghi mới hoặc sửa
            SS->>GW: upsert lô default của vụ
            SS->>GW: tìm activity theo device_id, client_event_id
            alt đã có
                GW->>PR: UPDATE theo id
            else chưa có
                GW->>PR: INSERT (23505 thì đọc lại rồi UPDATE)
            end
            SS->>GW: upsert bảng chi tiết theo activity_id
            SS->>DB: synced + server_activity_id
        end
    end
    SS-->>CO: SyncSummary
    CO->>CO: trạng thái allSynced / partialSuccess / failed / authExpired
```

## 4. Carbon calculation

Sơ đồ đầy đủ ở trang [Sequence tính Carbon](carbon-calculation-sequence.md). Tóm tắt:

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI
    participant AC as CropAccessChecker
    participant CS as CarbonService
    participant ENG as Carbon Engine
    participant DB as PostgreSQL

    C->>API: POST /v1/carbon/calculate
    API->>AC: RLS đọc crop season bằng JWT
    API->>CS: calculate(season, scenario)
    CS->>DB: bundle vụ (service role)
    CS->>ENG: calculate_carbon
    ENG-->>CS: CarbonResult hoặc lỗi 4xx
    CS->>DB: INSERT carbon_calculations + breakdowns
    API-->>C: kết quả + calculation_id
```

## 5. Recommendation simulation

```mermaid
sequenceDiagram
    autonumber
    participant W as Farmer Web
    participant API as FastAPI
    participant RS as RecommendationService
    participant RR as SupabaseReadRepository
    participant RU as rules.py
    participant CS as CarbonService
    participant REP as PostgresRecommendationRepository

    W->>API: POST /v1/crop-seasons/id/recommendations/generate
    API->>RS: generate
    RS->>RR: me() có farmer, season(id), metrics(id)
    RS->>RU: generate_recommendations(id, carbon, metrics)
    RU->>CS: calculate(id, as_recorded, persist=False)
    alt lỗi engine (hiện tại: thiếu GWP)
        CS-->>RU: CarbonEngineError
        RU->>RU: bỏ qua rule AWD
    else chế độ nước là ngập liên tục
        RU->>CS: calculate(id, awd, persist=False)
        alt kịch bản AWD lỗi
            RU->>RU: impact_status unavailable + lý do
        else delta dương
            RU->>RU: before, after, delta, percent
        end
    end
    RU->>RU: data_task cho yield, water, fertilizer, cost thiếu
    RU-->>RS: danh sách GeneratedRecommendation
    RS->>REP: save_generated (1 transaction)
    REP->>REP: upsert theo crop_season_id, rule_code, giữ status
    REP->>REP: xoá hàng generated của rule không còn áp dụng
    API-->>W: items
```

Không có bước nào ghi `carbon_calculations` trong luồng này.

## 6. MRV JSON export

```mermaid
sequenceDiagram
    autonumber
    actor M as Quản lý HTX
    participant W as Management Web
    participant API as FastAPI
    participant ES as MrvExportService
    participant RR as SupabaseReadRepository
    participant CS as CarbonService
    participant MF as mrv.manifest
    participant ER as PostgresMrvExportRepository

    M->>W: Xuất JSON
    W->>API: POST /v1/mrv/cases/id/exports format json
    API->>ES: create
    ES->>RR: me()
    ES->>RR: mrv_case_row(id) qua RLS
    ES->>ES: _manages(actor, organization_id)
    alt không đọc được hoặc không phải manager
        API-->>W: 404 not_found
    end
    ES->>RR: steps, evidence, scope, organization, activities
    ES->>RR: metrics_for_seasons
    ES->>CS: latest(season) cho từng vụ
    ES->>RR: emission_factor_provenance
    ES->>MF: build_manifest
    MF-->>ES: manifest + package_integrity.manifest_sha256
    ES->>ER: create(format json, payload, payload_sha256, file_sha256)
    ER->>ER: INSERT mrv_exports + mrv_export_calculations (1 transaction)
    API-->>W: 201 metadata + manifest
    W->>API: GET /v1/mrv/exports/export_id/download
```

## 7. XLSX / PDF render

```mermaid
sequenceDiagram
    autonumber
    participant W as Management Web
    participant API as FastAPI
    participant ES as MrvExportService
    participant ER as PostgresMrvExportRepository
    participant RD as workbook.py / report_pdf.py
    participant ST as Storage mrv-exports

    alt tạo mới
        W->>API: POST /v1/mrv/cases/id/exports format xlsx hoặc pdf
        API->>ES: create → _create_snapshot (như sơ đồ 6)
    else render snapshot có sẵn
        W->>API: POST /v1/mrv/exports/snapshot_id/render format xlsx hoặc pdf
        API->>ES: render
        ES->>ER: artifact_row(id, case manager quản lý)
        alt bản gốc không phải json
            API-->>W: 422 unsupported_export_format
        end
    end
    ES->>RD: render(manifest) trong bộ nhớ
    RD-->>ES: bytes
    ES->>ES: file_sha256 = sha256(bytes)
    ES->>ST: upload org/case/file (upsert false)
    ES->>ER: INSERT mrv_exports format, source_snapshot_export_id, payload_sha256
    alt INSERT lỗi
        ES->>ST: xoá object (best effort)
        API-->>W: lỗi
    end
    API-->>W: 201 MrvArtifactResponse
```

## 8. Secure artifact download

```mermaid
sequenceDiagram
    autonumber
    participant W as Management Web
    participant API as FastAPI
    participant ES as MrvExportService
    participant RR as SupabaseReadRepository
    participant ER as PostgresMrvExportRepository
    participant ST as Storage

    W->>API: GET /v1/mrv/exports/id/download + JWT
    API->>ES: download
    ES->>RR: me() và mrv_case_scopes() qua RLS
    ES->>ES: lọc case người gọi quản lý
    ES->>ER: artifact_row(id) với mrv_case_id thuộc danh sách đó (SQL)
    alt không có hàng
        API-->>W: 404 not_found
    end
    alt format json
        ES->>ES: canonical bytes từ export_payload
        ES->>ES: so manifest_checksum với payload_sha256
    else xlsx hoặc pdf
        ES->>ST: download object
        alt object không còn
            API-->>W: 404 export_artifact_missing
        end
        ES->>ES: so sha256(bytes) với file_sha256
    end
    alt lệch digest
        API-->>W: 409 export_artifact_integrity_failed
    else khớp
        API-->>W: 200 bytes + Content-Disposition attachment
    end
```

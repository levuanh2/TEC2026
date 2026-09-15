# Quyết định thiết kế

Mỗi quyết định ghi **bối cảnh → quyết định → bằng chứng trong code → hệ quả**.
Đây là mô tả quyết định đã hiện thực, không phải đề xuất.

## 1. Phạm vi Carbon = Crop Season

- **Bối cảnh:** CH₄ theo IPCC Eq 5.1 dùng `area_ha` (của thửa) và
  `cultivation_days` (của vụ). Tính theo từng lô sản xuất sẽ nhân đôi diện tích và
  số ngày khi một vụ có nhiều lô.
- **Quyết định:** một bản tính thuộc về đúng một vụ.
- **Bằng chứng:** `20260908000002_crop_season_carbon_scope.sql` đặt
  `carbon_calculations.crop_season_id NOT NULL`, `production_batch_id` thành tuỳ
  chọn và thêm trigger kiểm lô phải thuộc cùng vụ; `mapping.calculation_row` không
  ghi `production_batch_id`.
- **Hệ quả:** activity của mọi lô chưa xoá trong vụ đều vào cùng một bản tính.

## 2. Production Batch chỉ để truy xuất nguồn gốc

- **Bối cảnh:** schema gốc neo activity vào lô (`activities.production_batch_id NOT NULL`)
  và MRV liên kết lô (`mrv_case_batches`).
- **Quyết định:** giữ lô cho truy xuất/MRV, không dùng làm phạm vi tính.
- **Bằng chứng:** tag OpenAPI "Production Batches — chỉ để truy vết, KHÔNG phải scope
  tính carbon" (`main.py`); `manifest.provenance.carbon_scope = "crop_season"`.
- **Hệ quả:** Flutter tự tạo lô `default`; Farmer Web từ chối ghi nếu vụ không có
  đúng một lô mở (`422 invalid_crop_season_state`).

## 3. Backend sở hữu mọi phép tính

- **Quyết định:** CO₂e, chỉ số trên kg, tổng hợp và khuyến nghị đều tính ở backend.
- **Bằng chứng:** `carbon/` là thư viện thuần chỉ phụ thuộc `pyyaml`; metrics nằm
  trong `read_repo.py`; `recommendation/rules.py` gọi `CarbonService`.
- **Hệ quả:** web và Flutter chỉ hiển thị giá trị trả về.

## 4. Trình duyệt không tính nghiệp vụ

- **Quyết định:** React không có công thức phát thải hay chỉ số.
- **Bằng chứng:** web gọi `/v1/crop-seasons/{id}/metrics`, `/carbon`; comment trong
  `utils/supabase.ts`: "Auth only. Dashboard data is intentionally fetched through FastAPI."
- **Hệ quả:** một nguồn số liệu duy nhất cho Farmer Web, Management Web và gói MRV.

## 5. Canonical MRV snapshot

- **Quyết định:** mọi gói xuất bắt đầu từ **một** manifest JSON lưu nguyên văn
  trong `mrv_exports.export_payload`, có `payload_sha256`.
- **Bằng chứng:** `MrvExportService._create_snapshot`, `mrv/manifest.py::build_manifest`;
  download JSON đọc lại payload, không dựng lại từ dữ liệu sống.
- **Hệ quả:** sửa case sau khi xuất không làm thay đổi gói đã xuất.

## 6. XLSX/PDF chỉ render

- **Quyết định:** renderer nhận `dict` manifest và trả `bytes`, không import
  repository hay service.
- **Bằng chứng:** `mrv/workbook.py::render_workbook`, `mrv/report_pdf.py::render_pdf`;
  ràng buộc DB `mrv_export_snapshot_lineage_chk` (JSON không có cha, định dạng khác
  bắt buộc có `source_snapshot_export_id`).
- **Hệ quả:** XLSX và PDF của cùng snapshot là "anh em", không bao giờ tính lại
  Carbon/Resource.

## 7. `null` ≠ `0`

- **Quyết định:** thiếu dữ liệu trả `null`, không thay bằng 0.
- **Bằng chứng:** `carbon/engine.py::_per_kg` trả `None` + cảnh báo khi chưa có sản
  lượng; `read_repo.py` trả `water_per_kg = None` khi thiếu; manifest ghi rõ "null is
  never turned into 0"; XLSX để ô trống; PDF ghi "Chưa đủ dữ liệu".
- **Hệ quả:** UI phải có trạng thái "chưa đủ dữ liệu" riêng.

## 8. Tổng hợp có trọng số

- **Quyết định:** chỉ số tổng hợp = tổng tử số / tổng sản lượng, không trung bình
  các tỷ lệ con.
- **Bằng chứng:** `read_repo.py::_aggregate_from_totals`; docstring "Tổng (sum), KHÔNG
  trung bình".
- **Hệ quả:** vụ sản lượng lớn có trọng số lớn; một vụ thiếu dữ liệu làm chỉ số tổng
  của nhóm thành `null`.

## 9. Flutter ghi trực tiếp Supabase dưới RLS

- **Bối cảnh:** không có `POST /v1/sync`; schema đã có RLS insert cho `authenticated`
  và unique index `(device_id, client_event_id)`.
- **Quyết định:** Flutter upsert thẳng qua PostgREST.
- **Bằng chứng:** `app/lib/services/sync_service.dart`, `sync_gateway.dart`; `app/README.md`.
- **Hệ quả:** quyền ghi của Flutter là quyền RLS (`farm_role` `owner`/`editor` hoặc
  manager); xoá mềm đi qua RPC `public.soft_delete_activity` vì policy SELECT chặn
  UPDATE `deleted_at`.

## 10. Farmer Web ghi qua FastAPI

- **Bối cảnh:** một activity gồm hàng `activities` + hàng chi tiết; trình duyệt không
  có `device_id`.
- **Quyết định:** ghi qua FastAPI trong một transaction psycopg, idempotent theo
  `(recorded_by, web_idempotency_key)`.
- **Bằng chứng:** `write_repo.py`, migration `20260910080441_farmer_web_activity_idempotency.sql`.
- **Hệ quả:** gửi lại cùng key + cùng dữ liệu trả bản ghi cũ (`idempotent_replay: true`);
  cùng key khác dữ liệu → `409 duplicate_event`.

## 11. Toàn vẹn artifact bằng SHA-256

- **Quyết định:** hai digest: `payload_sha256` (dữ liệu nào) và `file_sha256` (tệp nào).
- **Bằng chứng:** migration `20260913150000_mrv_xlsx_export_artifacts.sql`;
  `MrvExportService.download` băm lại bytes và từ chối nếu lệch
  (`409 export_artifact_integrity_failed`).
- **Hệ quả:** không bao giờ phục vụ tệp không khớp bản ghi; không có signed URL.

## 12. Xuất MRV chỉ dành cho quản lý

- **Quyết định:** tạo, render, tải và xem metadata gói xuất yêu cầu
  `cooperative_manager` còn hiệu lực của đúng tổ chức sở hữu case.
- **Bằng chứng:** `MrvExportService.MANAGEMENT_ROLE`, `_manages`; policy
  `mrv_exports_select` dùng `private.user_can_manage_mrv_case`.
- **Hệ quả:** `enterprise_viewer`/`regulator` đọc được case qua data grant nhưng
  không tạo/tải gói; mọi trường hợp bị từ chối đều là `404`.

## 13. Fail closed thay vì đoán

- **Quyết định:** thiếu hệ số hoặc biến phương pháp luận thì báo lỗi, không dùng giá
  trị mặc định.
- **Bằng chứng:** `ParameterSet.get` ném `MissingEmissionFactorError` khi `value: null`;
  engine từ chối dùng `default_cultivation_days`; không đoán `alternate`/`other` thành AWD.
- **Hệ quả:** với YAML hiện tại, không có bản tính CO₂e thật nào thành công.

-- ============================================================================
-- AgriCarbon — cho phép bản tính "succeeded" khi chưa có sản lượng
-- Date: 2026-09-08
-- Follows: 20260908000002_crop_season_carbon_scope.sql
--
-- ADDITIVE-SAFE: chỉ nới một CHECK constraint (less restrictive), không xoá dữ liệu,
-- không đụng RLS. Nới CHECK không bao giờ làm hàng cũ vi phạm — an toàn tuyệt đối.
-- ============================================================================

begin;

-- VẤN ĐỀ
--   Baseline định nghĩa:
--     carbon_success_chk: status <> 'succeeded'
--       OR (total_co2e_kg IS NOT NULL AND yield_kg IS NOT NULL AND failure_reason IS NULL)
--
--   Nhưng SRS FR-1a-11 / NFR-03 và Carbon Engine (docs/CARBON_METHOD.md) coi
--   "đã tính được CO2e tổng nhưng chưa có sản lượng" là một trạng thái THÀNH CÔNG hợp lệ,
--   không phải lỗi: engine trả total_co2e_kg + co2e_per_kg=null + warning, KHÔNG raise.
--
--   Hệ quả: backend/infrastructure/mapping.py.calculation_row() luôn ghi status='succeeded'
--   khi engine chạy xong không lỗi — kể cả khi yield_kg là None. Insert hàng đó vào Postgres
--   thật sẽ VI PHẠM carbon_success_chk và bị từ chối, dù engine coi đây là kết quả đúng.
--   Phát hiện khi audit trước khi kết nối Supabase thật — chưa từng chạy tới DB thật nên
--   chưa lộ ra qua test (InMemoryCarbonRepository không kiểm CHECK constraint).
--
-- SỬA
--   Nới điều kiện: 'succeeded' chỉ còn đòi total_co2e_kg NOT NULL (bỏ yêu cầu yield_kg
--   NOT NULL). co2e_per_kg vẫn tự động NULL qua generated column
--   (total_co2e_kg / nullif(yield_kg, 0)) — không cần đổi gì ở engine hay mapping.py.

alter table public.carbon_calculations
  drop constraint if exists carbon_success_chk;

alter table public.carbon_calculations
  add constraint carbon_success_chk check (
    status <> 'succeeded'
    or (total_co2e_kg is not null and failure_reason is null)
  );

comment on constraint carbon_success_chk on public.carbon_calculations is
  'succeeded chỉ đòi total_co2e_kg. yield_kg được phép NULL — "đã tính CO2e nhưng chưa có '
  'sản lượng" là trạng thái thành công hợp lệ theo SRS FR-1a-11/NFR-03, không phải lỗi. '
  'co2e_per_kg tự NULL qua generated column khi yield_kg NULL.';

commit;

-- ============================================================================
-- KHÔNG LÀM TRONG MIGRATION NÀY
--   * Không đổi calculation_status enum.
--   * Không thêm status mới ("partial") — total_co2e_kg NOT NULL đã đủ phân biệt
--     succeeded (có tổng, có thể chưa có yield) với failed (không có tổng).
--   * Không sửa engine/mapping.py — hành vi của chúng vốn đã đúng, chỉ DB constraint sai.
-- ============================================================================

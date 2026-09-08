-- ============================================================================
-- AgriCarbon — Carbon calculation scope (patch bổ sung)
-- Ngày: 2026-09-08
-- Đứng sau: 20260908_carbon_methodology_alignment.sql
--
-- ADDITIVE-ONLY. Không sửa migration đã commit. Không đụng RLS. Không drop gì.
--
-- VẤN ĐỀ PHÁT HIỆN KHI NỐI BACKEND
--   `carbon_calculations.production_batch_id` là NOT NULL -> một bản tính gắn với MỘT
--   production_batch. Nhưng phương pháp luận CH4 (IPCC Eq 5.1) tính trên:
--
--       CH4 = EFi × cultivation_days × area_ha
--
--   trong đó `area_ha` thuộc PLOT và `cultivation_days` thuộc CROP_SEASON — cả hai đều ở
--   cấp VỤ, không phải cấp lô thu hoạch. Schema cho phép nhiều batch trên một crop_season
--   (`unique (crop_season_id, batch_code)` không chặn điều đó).
--
--   Hệ quả: một vụ chia làm 2 batch, nếu tính CO2e cho từng batch thì mỗi bản tính đều
--   dùng TRỌN diện tích thửa và TRỌN số ngày canh tác -> tổng phát thải của thửa bị đếm
--   HAI LẦN. Đây là double counting ở tầng phạm vi, không phải tầng công thức.
--
-- CÁCH XỬ LÝ TRONG MVP (không đổi schema hiện có)
--   Backend CHỈ tính khi crop_season có ĐÚNG MỘT production_batch còn hiệu lực.
--   Nhiều batch -> raise CalculationScopeError, không đoán cách chia diện tích.
--   Patch này chỉ THÊM cột để ghi lại phạm vi thật đã dùng, phục vụ thẩm định.
--
-- CẦN QUYẾT ĐỊNH SAU (ngoài phạm vi MVP 1a)
--   Nếu thực tế có nhiều batch/vụ thì phải chọn một trong hai:
--     (a) tính ở cấp crop_season, batch chỉ dùng để truy xuất nguồn gốc; hoặc
--     (b) phân bổ area_ha theo tỷ lệ sản lượng từng batch, và ghi rõ quy tắc phân bổ.
--   Không được để backend tự chọn.
-- ============================================================================

begin;

alter table public.carbon_calculations
  add column if not exists crop_season_id uuid references public.crop_seasons(id) on delete cascade,
  add column if not exists area_ha_used numeric(10,4),
  add column if not exists cultivation_days_used integer,
  add column if not exists water_regime_applied public.ipcc_water_regime,
  add column if not exists pre_season_water_regime_applied public.ipcc_pre_season_regime;

do $$ begin
  alter table public.carbon_calculations
    add constraint carbon_area_used_chk
    check (area_ha_used is null or area_ha_used > 0);
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.carbon_calculations
    add constraint carbon_days_used_chk
    check (cultivation_days_used is null or cultivation_days_used > 0);
exception when duplicate_object then null; end $$;

create index if not exists carbon_calculations_crop_season_idx
  on public.carbon_calculations(crop_season_id, scenario, calculated_at desc);

comment on column public.carbon_calculations.crop_season_id is
  'Vụ canh tác mà bản tính này thuộc về. production_batch_id vẫn là khoá phạm vi chính '
  '(NOT NULL, RLS bám vào nó), cột này ghi lại phạm vi THẬT của phương pháp luận: CH4 tính '
  'trên diện tích thửa × số ngày canh tác của cả vụ, không phải của riêng một lô thu hoạch.';
comment on column public.carbon_calculations.area_ha_used is
  'Diện tích (ha) thực sự đưa vào Eq 5.1. Lưu lại để thẩm định phát hiện được double counting '
  'nếu một vụ bị tính nhiều lần qua nhiều batch.';
comment on column public.carbon_calculations.cultivation_days_used is
  'Số ngày canh tác thực sự đưa vào Eq 5.1. KHÔNG bao giờ là giá trị mặc định vùng — '
  'engine raise lỗi khi thiếu dữ liệu thực tế.';
comment on column public.carbon_calculations.water_regime_applied is
  'Chế độ nước IPCC thực sự dùng sau khi áp scenario. Với scenario awd/continuous_flooding '
  'đây là giá trị GIẢ ĐỊNH, khác với crop_seasons.ipcc_water_regime đã ghi nhận.';
comment on column public.carbon_calculations.pre_season_water_regime_applied is
  'SFp thực sự dùng. Ghi lại vì đây là biến hay thiếu nhất và ảnh hưởng tới hơn gấp đôi CH4.';

commit;

-- ============================================================================
-- KHÔNG LÀM TRONG PATCH NÀY
--   * Không nới `production_batch_id` thành nullable — RLS
--     (carbon_calculations_select -> private.user_can_read_batch) bám vào cột đó.
--     Nới ra là phá phân quyền.
--   * Không thêm unique constraint bắt 1 batch/vụ — dữ liệu thật có thể đã có nhiều batch,
--     thêm ràng buộc sẽ làm migration fail. Backend chặn ở tầng ứng dụng thay vào đó.
--   * Không seed giá trị nào.
-- ============================================================================

-- ============================================================================
-- AgriCarbon — Carbon methodology alignment
-- Ngày: 2026-09-08
--
-- MỤC ĐÍCH
--   Bổ sung ĐÚNG những gì phương pháp luận đòi hỏi mà schema hiện tại chưa biểu diễn được.
--   KHÔNG redesign database. Không đụng vào RLS. Không đổi bảng/cột đang có dữ liệu.
--   Toàn bộ thay đổi là ADDITIVE: thêm enum value, thêm cột nullable, thêm bảng phụ.
--
-- CĂN CỨ
--   docs/CARBON_METHOD.md · docs/CARBON_METHOD_SOURCES.md
--   IPCC 2019 Refinement Vol.4 Ch.5 (Eq 5.1/5.2/5.3, Tables 5.11–5.14)
--   IPCC 2019 Refinement Vol.4 Ch.11 (Eq 11.1, Table 11.1)
--   IPCC 2006 GL Vol.4 Ch.2 (Eq 2.27, Tables 2.5/2.6)
--
-- VÌ SAO CẦN
--   Schema cũ giả định mỗi nguồn phát thải = một phép nhân `activity × factor_value`.
--   CH4 lúa KHÔNG phải vậy: EFi = EFc × SFw × SFp × SFo, trong đó SFo lại là một hàm
--   luỹ thừa của lượng chất hữu cơ. Cần (a) lưu được nhiều loại tham số, (b) lưu lại
--   đủ tham số trung gian để tái hiện phép tính, (c) lưu các biến hoạt động mà công thức
--   đòi mà bảng activity chưa có (chế độ nước TRƯỚC vụ, thời điểm vùi rơm, khối lượng khô).
--
-- CHẠY: Supabase SQL Editor, quyền database owner. Idempotent.
-- ============================================================================

begin;

-- --------------------------------------------------------------------------
-- 1. ENUM: bổ sung giá trị (không xoá giá trị cũ — sẽ phá dữ liệu đang có)
-- --------------------------------------------------------------------------

-- 1.1 Phân loại tham số. Schema cũ coi mọi dòng emission_factors là "hệ số phát thải",
--     nhưng SFw/SFp/CFOA là hệ số ĐIỀU CHỈNH KHÔNG THỨ NGUYÊN, và GWP là hệ số quy đổi.
--     Gộp chung một loại thì không kiểm tra được tính đúng đắn của đơn vị.
do $$ begin
  create type public.parameter_kind as enum
    ('emission_factor','scaling_factor','conversion_factor','gwp','exponent','default_value');
exception when duplicate_object then null; end $$;

-- 1.2 Trạng thái xác minh của từng tham số (khác ef_status vốn là vòng đời của cả BỘ).
do $$ begin
  create type public.parameter_verification_status as enum
    ('VERIFIED','PENDING_VERIFICATION','NOT_IMPLEMENTED','TEST_ONLY');
exception when duplicate_object then null; end $$;

-- 1.3 Chế độ nước TRONG vụ theo đúng phân loại IPCC Table 5.12 (cột disaggregated).
--     irrigation_method hiện có ('awd','continuous_flooding','alternate','other') KHÔNG
--     ánh xạ được sang SFw: thiếu phân biệt single vs multiple drainage, thiếu loại hệ
--     sinh thái (irrigated/rainfed/upland/deep water).
do $$ begin
  create type public.ipcc_water_regime as enum (
    'irrigated_continuous_flooding',
    'irrigated_single_drainage',
    'irrigated_multiple_drainage',   -- AWD nằm ở đây (Table 5.12 chú thích b)
    'rainfed_regular',
    'rainfed_drought_prone',
    'deep_water',
    'upland'
  );
exception when duplicate_object then null; end $$;

-- 1.4 Chế độ nước TRƯỚC vụ — SFp, IPCC Table 5.13. Schema cũ KHÔNG có khái niệm này.
--     Bỏ qua SFp là sai phương pháp luận: ngập trước vụ >30 ngày cho SFp = 2,41,
--     tức hơn gấp đôi so với 1,00.
do $$ begin
  create type public.ipcc_pre_season_regime as enum (
    'non_flooded_pre_season_lt_180d',
    'non_flooded_pre_season_gt_180d',
    'flooded_pre_season_gt_30d',
    'non_flooded_pre_season_gt_365d'
  );
exception when duplicate_object then null; end $$;

-- 1.5 Danh mục nguồn phát thải: tách rơm ĐỐT thành nguồn riêng.
--     Giá trị 'straw' cũ gây hiểu nhầm: rơm VÙI không phải một nguồn phát thải, nó là
--     đầu vào của SFo (điều chỉnh CH4 ruộng ngập). Chỉ rơm ĐỐT mới là nguồn riêng.
do $$ begin alter type public.emission_category add value if not exists 'straw_burning_ch4'; exception when others then null; end $$;
do $$ begin alter type public.emission_category add value if not exists 'straw_burning_n2o'; exception when others then null; end $$;
do $$ begin alter type public.emission_category add value if not exists 'electricity'; exception when others then null; end $$;

-- --------------------------------------------------------------------------
-- 2. CROP_SEASONS: các biến hoạt động mà công thức CH4 đòi hỏi
-- --------------------------------------------------------------------------
-- Đặt ở cấp VỤ chứ không phải cấp activity: SFw/SFp là thuộc tính của cả vụ canh tác.
-- Để nullable — dữ liệu cũ chưa có; engine sẽ báo MethodologyGapError khi thiếu, không đoán.

alter table public.crop_seasons
  add column if not exists ipcc_water_regime public.ipcc_water_regime,
  add column if not exists pre_season_water_regime public.ipcc_pre_season_regime,
  add column if not exists cultivation_days integer,
  add column if not exists drainage_event_count integer;

do $$ begin
  alter table public.crop_seasons
    add constraint crop_seasons_cultivation_days_chk
    check (cultivation_days is null or cultivation_days > 0);
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.crop_seasons
    add constraint crop_seasons_drainage_count_chk
    check (drainage_event_count is null or drainage_event_count >= 0);
exception when duplicate_object then null; end $$;

comment on column public.crop_seasons.ipcc_water_regime is
  'Chế độ nước trong vụ theo IPCC Table 5.12 (disaggregated) — đầu vào của SFw. '
  'Khác irrigation_method: cần phân biệt single vs multiple drainage và loại hệ sinh thái.';
comment on column public.crop_seasons.pre_season_water_regime is
  'Chế độ nước TRƯỚC vụ theo IPCC Table 5.13 — đầu vào của SFp. Bắt buộc cho Eq 5.2.';
comment on column public.crop_seasons.cultivation_days is
  'Số ngày canh tác (t trong Eq 5.1). Suy từ planting_date/actual_harvest_date nếu để trống.';
comment on column public.crop_seasons.drainage_event_count is
  'Số lần rút nước. Chưa vào công thức Tier 1 (dùng để phân loại single vs multiple drainage '
  'và để dành cho hệ số đặc trưng quốc gia sau này).';

-- --------------------------------------------------------------------------
-- 3. STRAW_MANAGEMENT_EVENTS: đủ dữ liệu để chọn đúng CFOA và tính khối lượng khô
-- --------------------------------------------------------------------------
-- IPCC Table 5.14: CFOA rơm vùi <30 ngày trước canh tác = 1,00; vùi >30 ngày = 0,19.
-- Chênh hơn 5 lần -> KHÔNG được đoán, phải có dữ liệu thời điểm.
-- Eq 5.3: ROA tính theo KHỐI LƯỢNG KHÔ -> cần độ ẩm/tỷ lệ chất khô.

alter table public.straw_management_events
  add column if not exists days_before_cultivation integer,
  add column if not exists dry_matter_fraction numeric(5,4),
  add column if not exists returned_to_field boolean;

do $$ begin
  alter table public.straw_management_events
    add constraint straw_dry_matter_chk
    check (dry_matter_fraction is null or (dry_matter_fraction > 0 and dry_matter_fraction <= 1));
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.straw_management_events
    add constraint straw_days_before_chk
    check (days_before_cultivation is null or days_before_cultivation >= 0);
exception when duplicate_object then null; end $$;

comment on column public.straw_management_events.days_before_cultivation is
  'Số ngày trước khi bắt đầu canh tác mà rơm được vùi. Quyết định CFOA: <30 ngày = 1,00; '
  '>=30 ngày = 0,19 (IPCC Table 5.14). Bắt buộc khi method = incorporated.';
comment on column public.straw_management_events.dry_matter_fraction is
  'Tỷ lệ chất khô (0–1). IPCC Eq 5.3 tính ROA theo khối lượng khô. '
  'Bắt buộc khi method dẫn tới SFo hoặc đốt đồng.';
comment on column public.straw_management_events.returned_to_field is
  'Chỉ dùng khi method = composted: compost có được trả lại chính ruộng đó không. '
  'Có -> CFOA compost = 0,17. Không -> không tính vào nguồn nào.';

-- --------------------------------------------------------------------------
-- 4. EMISSION_FACTORS: biểu diễn được nhiều loại tham số, không ép về một phép nhân
-- --------------------------------------------------------------------------
-- Ràng buộc cũ `result_unit default 'kgCO2e'` và `gas not null` không đúng cho SFw/SFp/CFOA
-- (không thứ nguyên, không gắn với khí nào). Thêm parameter_kind + cho phép gas null.

alter table public.emission_factors
  add column if not exists parameter_kind public.parameter_kind not null default 'emission_factor',
  add column if not exists verification_status public.parameter_verification_status
      not null default 'PENDING_VERIFICATION',
  add column if not exists source_table_reference text,
  add column if not exists uncertainty_range text,
  add column if not exists applies_to_water_regime public.ipcc_water_regime,
  add column if not exists applies_to_pre_season_regime public.ipcc_pre_season_regime;

-- gas không áp dụng cho scaling factor / exponent -> nới nullable.
alter table public.emission_factors alter column gas drop not null;

do $$ begin
  alter table public.emission_factors
    add constraint ef_gas_required_for_emission_factor_chk
    check (parameter_kind <> 'emission_factor' or gas is not null);
exception when duplicate_object then null; end $$;

-- Tham số đã VERIFIED bắt buộc phải chỉ được số hiệu bảng/phương trình trong tài liệu gốc.
do $$ begin
  alter table public.emission_factors
    add constraint ef_verified_needs_table_reference_chk
    check (
      verification_status <> 'VERIFIED'
      or (source_table_reference is not null and btrim(source_table_reference) <> '')
    );
exception when duplicate_object then null; end $$;

comment on column public.emission_factors.parameter_kind is
  'emission_factor | scaling_factor (SFw/SFp/SFo/CFOA) | conversion_factor (44/28) | '
  'gwp | exponent (0,59 của Eq 5.3) | default_value. Ngăn việc ép mọi tham số thành '
  'một phép nhân activity × factor.';
comment on column public.emission_factors.verification_status is
  'Trạng thái xác minh của CHÍNH tham số này (khác ef_status là vòng đời của cả bộ). '
  'Chỉ VERIFIED mới được dùng cho báo cáo.';
comment on column public.emission_factors.source_table_reference is
  'Số hiệu bảng/phương trình chính xác, ví dụ "IPCC 2019 Refinement Vol.4 Ch.5 Table 5.12". '
  'Bắt buộc khi verification_status = VERIFIED.';

-- --------------------------------------------------------------------------
-- 5. CARBON_BREAKDOWNS: phải tái hiện được phép tính nhiều thành phần
-- --------------------------------------------------------------------------
-- `factor_value_used` là MỘT con số — không đủ để tái hiện EFc × SFw × SFp × SFo × GWP.
-- Giám khảo/kiểm định phải truy được từ co2e_kg ngược về từng hệ số và nguồn của nó.

alter table public.carbon_breakdowns
  add column if not exists formula_metadata jsonb,
  add column if not exists gas_kg numeric(24,8),
  add column if not exists formula_expression text;

do $$ begin
  alter table public.carbon_breakdowns
    add constraint carbon_breakdown_gas_kg_chk
    check (gas_kg is null or gas_kg >= 0);
exception when duplicate_object then null; end $$;

comment on column public.carbon_breakdowns.formula_metadata is
  'Toàn bộ tham số đã dùng và nguồn của chúng, dạng '
  '{"factors_used": {"factors.ch4_rice.efc": 1.22, ...}, '
  '"provenance": {"factors.ch4_rice.efc": "IPCC ... Table 5.11"}, '
  '"derived": {"sfo": 1.93, "ef_i": 1.24}}. '
  'factor_value_used giữ nguyên để tương thích, nhưng chỉ là hệ số CHÍNH của dòng.';
comment on column public.carbon_breakdowns.gas_kg is
  'Khối lượng khí trước khi quy đổi CO2e (kg CH4 hoặc kg N2O). Tách khỏi co2e_kg để kiểm tra '
  'được GWP đã áp đúng chưa.';
comment on column public.carbon_breakdowns.formula_expression is
  'Công thức dạng chữ, ví dụ "IPCC Eq 5.1 + 5.2: CH4 = (EFc × SFw × SFp × SFo) × t × A".';

-- --------------------------------------------------------------------------
-- 6. CARBON_CALCULATIONS: ghi lại phương pháp luận, không chỉ bộ hệ số
-- --------------------------------------------------------------------------
-- Cùng một bộ hệ số có thể được áp bằng Tier 1 hoặc Tier 2 -> phải ghi rõ.

alter table public.carbon_calculations
  add column if not exists methodology_tier smallint,
  add column if not exists mrv_compliant boolean not null default false,
  add column if not exists warnings jsonb;

do $$ begin
  alter table public.carbon_calculations
    add constraint carbon_methodology_tier_chk
    check (methodology_tier is null or methodology_tier between 1 and 3);
exception when duplicate_object then null; end $$;

comment on column public.carbon_calculations.mrv_compliant is
  'CHỈ được đặt true khi toàn bộ tham số dùng đến đều đến từ QĐ 4801/QĐ-BNNMT hoặc nguồn '
  'chính thức tương đương. Mặc định false. Dùng IPCC Tier 1 default -> luôn false.';
comment on column public.carbon_calculations.warnings is
  'Danh sách cảnh báo engine sinh ra (thiếu dữ liệu, dùng giá trị mặc định, nguồn nào chưa '
  'xác minh, phần nào ngoài ranh giới hệ thống).';

-- --------------------------------------------------------------------------
-- 7. VIEW: sửa v_carbon_results để lộ thông tin provenance mới
-- --------------------------------------------------------------------------
-- Chỉ thêm cột, không đổi ý nghĩa cột cũ.

create or replace view public.v_carbon_results as
select
  c.id                      as calculation_id,
  c.production_batch_id,
  c.scenario,
  c.status,
  c.total_co2e_kg,
  c.yield_kg,
  c.co2e_per_kg,
  c.engine_version,
  c.input_hash,
  c.methodology_tier,
  c.mrv_compliant,
  c.warnings,
  c.calculated_at,
  s.version_code            as factor_set_version,
  s.methodology_name,
  s.methodology_version,
  s.source_name,
  s.source_url
from public.carbon_calculations c
join public.emission_factor_sets s on s.id = c.factor_set_id;

commit;

-- ============================================================================
-- KHÔNG LÀM TRONG MIGRATION NÀY (có chủ đích)
--
--   * Không seed bất kỳ giá trị emission factor nào. Bộ tham số nguồn là
--     backend/config/emission_factors.yaml; nạp vào DB bằng script riêng SAU KHI
--     chốt được GWP (open issue OI-05) — hiện chưa ra được số CO2e nào.
--   * Không đụng RLS, không đụng policy, không đụng grant.
--   * Không xoá cột/giá trị enum cũ (irrigation_method, emission_category.'straw',
--     factor_value_used) — dữ liệu hiện có vẫn đọc được. Việc dọn dẹp để sau khi
--     backfill xong.
--   * Không tạo bảng riêng cho từng loại scaling factor: parameter_kind + khoá
--     factor_code đủ biểu diễn, thêm bảng chỉ làm nặng schema mà không thêm ràng buộc nào.
--
-- BACKFILL CẦN LÀM SAU (dữ liệu, không phải schema)
--   1. crop_seasons.ipcc_water_regime      <- từ default_irrigation_method + số lần rút nước
--   2. crop_seasons.pre_season_water_regime<- KHÔNG suy được từ dữ liệu hiện có, phải đi hỏi
--   3. straw_management_events.dry_matter_fraction / days_before_cultivation <- phải đi hỏi
--   Không được điền giá trị mặc định cho 3 mục này.
-- ============================================================================

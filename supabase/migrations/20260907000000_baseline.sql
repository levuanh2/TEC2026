-- ============================================================================
-- AgriCarbon — Supabase/PostgreSQL full database v2
-- Scope:
--   A) Product operational database derived from PRD/SRS + 7 modules (MVP 1a/1b/1c)
--   B) Project-management tracker derived from AgriCarbon_Sprint_Tracker_CRMstyle.xlsx
--
-- Design principles:
--   * One business fact = one source of truth.
--   * Many-to-many relations use junction tables.
--   * Derived dashboard values are views/snapshots, not duplicated mutable facts.
--   * Business time, client-record time, server-receive time, created_at and
--     updated_at are explicitly separated for offline-first traceability.
--   * Emission factors, CV models and recommendation rules are versioned.
--   * Missing emission factors MUST NOT be silently treated as zero.
--   * RLS is enforced in PostgreSQL; UI hiding is not authorization.
--   * Audit and import lineage are first-class data.
--
-- Target: fresh Supabase project. Run in SQL Editor as database owner.
-- IMPORTANT: This script deliberately DOES NOT seed any emission-factor values,
-- because no authoritative EF table/version was provided in the source material.
-- ============================================================================

begin;

create schema if not exists private;
create schema if not exists audit;
create schema if not exists pm;

-- --------------------------------------------------------------------------
-- 1. ENUMS / CONTROLLED VOCABULARIES
-- --------------------------------------------------------------------------

do $$ begin create type public.organization_type as enum
  ('cooperative','enterprise','government','research','other');
exception when duplicate_object then null; end $$;

do $$ begin create type public.organization_role as enum
  ('farmer','cooperative_manager','enterprise_viewer','regulator');
exception when duplicate_object then null; end $$;

do $$ begin create type public.data_access_level as enum
  ('read','aggregate');
exception when duplicate_object then null; end $$;

do $$ begin create type public.farm_role as enum
  ('owner','editor','viewer');
exception when duplicate_object then null; end $$;

do $$ begin create type public.crop_status as enum
  ('planned','active','harvested','closed','cancelled');
exception when duplicate_object then null; end $$;

do $$ begin create type public.batch_status as enum
  ('planned','active','harvested','closed','cancelled');
exception when duplicate_object then null; end $$;

do $$ begin create type public.irrigation_method as enum
  ('awd','continuous_flooding','alternate','other');
exception when duplicate_object then null; end $$;

do $$ begin create type public.activity_type as enum
  ('seeding','fertilizer','irrigation','pesticide','fuel','straw_management','harvest','other');
exception when duplicate_object then null; end $$;

do $$ begin create type public.data_source as enum
  ('mobile_offline','mobile_online','web','api','import','system');
exception when duplicate_object then null; end $$;

do $$ begin create type public.sync_status as enum
  ('received','processing','completed','partial','failed');
exception when duplicate_object then null; end $$;

do $$ begin create type public.ingestion_source_kind as enum
  ('xlsx','csv','manual','api','mobile_sync','migration');
exception when duplicate_object then null; end $$;

do $$ begin create type public.ingestion_status as enum
  ('received','validated','loaded','partial','rejected');
exception when duplicate_object then null; end $$;

do $$ begin create type public.quality_severity as enum
  ('info','warning','error');
exception when duplicate_object then null; end $$;

do $$ begin create type public.quality_flag_status as enum
  ('open','resolved','accepted');
exception when duplicate_object then null; end $$;

do $$ begin create type public.fuel_type as enum
  ('diesel','gasoline','lpg','other');
exception when duplicate_object then null; end $$;

do $$ begin create type public.straw_management_method as enum
  ('incorporated','removed','burned','composted','other');
exception when duplicate_object then null; end $$;

do $$ begin create type public.ef_status as enum
  ('draft','published','retired');
exception when duplicate_object then null; end $$;

do $$ begin create type public.emission_category as enum
  ('irrigation_ch4','fertilizer_n2o','fuel','straw','other');
exception when duplicate_object then null; end $$;

do $$ begin create type public.greenhouse_gas as enum
  ('co2','ch4','n2o','co2e');
exception when duplicate_object then null; end $$;

do $$ begin create type public.carbon_scenario as enum
  ('actual','awd','continuous_flooding');
exception when duplicate_object then null; end $$;

do $$ begin create type public.calculation_status as enum
  ('pending','succeeded','failed','superseded');
exception when duplicate_object then null; end $$;

do $$ begin create type public.disease_label as enum
  ('rice_blast','bacterial_leaf_blight','brown_spot','healthy','unknown');
exception when duplicate_object then null; end $$;

do $$ begin create type public.model_status as enum
  ('draft','active','retired');
exception when duplicate_object then null; end $$;

do $$ begin create type public.resource_metric_code as enum
  ('water_per_kg','fertilizer_per_kg','co2e_per_kg','cost_per_kg');
exception when duplicate_object then null; end $$;

do $$ begin create type public.benchmark_status as enum
  ('draft','finalized','retired');
exception when duplicate_object then null; end $$;

do $$ begin create type public.comparison_operator as enum
  ('gt','gte','lt','lte');
exception when duplicate_object then null; end $$;

do $$ begin create type public.recommendation_status as enum
  ('generated','accepted','dismissed','expired');
exception when duplicate_object then null; end $$;

do $$ begin create type public.mrv_case_status as enum
  ('draft','in_progress','ready_for_verification','verified','closed');
exception when duplicate_object then null; end $$;

do $$ begin create type public.mrv_step_status as enum
  ('not_started','in_progress','completed','blocked');
exception when duplicate_object then null; end $$;

do $$ begin create type public.export_format as enum
  ('pdf','xlsx');
exception when duplicate_object then null; end $$;

-- PM enums

do $$ begin create type pm.mvp_layer as enum ('1a','1b','1c');
exception when duplicate_object then null; end $$;

do $$ begin create type pm.task_status as enum
  ('todo','in_progress','review','done','blocked');
exception when duplicate_object then null; end $$;

do $$ begin create type pm.priority_level as enum ('low','medium','high');
exception when duplicate_object then null; end $$;

do $$ begin create type pm.issue_type as enum ('dependency','risk');
exception when duplicate_object then null; end $$;

do $$ begin create type pm.issue_severity as enum ('low','medium','high');
exception when duplicate_object then null; end $$;

do $$ begin create type pm.issue_status as enum ('open','resolved','closed');
exception when duplicate_object then null; end $$;

do $$ begin create type pm.requirement_kind as enum
  ('functional','non_functional','business_constraint');
exception when duplicate_object then null; end $$;

-- --------------------------------------------------------------------------
-- 2. GENERIC HELPERS
-- --------------------------------------------------------------------------

create or replace function private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create or replace function private.touch_activity_row()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  new.row_version := old.row_version + 1;
  return new;
end;
$$;

create or replace function private.try_uuid(value text)
returns uuid
language plpgsql
immutable
set search_path = ''
as $$
begin
  return value::uuid;
exception when invalid_text_representation then
  return null;
end;
$$;

-- --------------------------------------------------------------------------
-- 3. IDENTITY / ORGANIZATION / ACCESS FOUNDATION
-- --------------------------------------------------------------------------

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text,
  phone text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint profiles_name_chk check (full_name is null or btrim(full_name) <> '')
);

create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  organization_code text not null unique,
  name text not null,
  organization_type public.organization_type not null,
  province_name text,
  district_name text,
  commune_name text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint organizations_code_chk check (btrim(organization_code) <> ''),
  constraint organizations_name_chk check (btrim(name) <> '')
);

create table if not exists public.organization_memberships (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  role public.organization_role not null,
  joined_at timestamptz not null default now(),
  ended_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, user_id),
  constraint organization_membership_dates_chk
    check (ended_at is null or ended_at >= joined_at)
);

-- Explicit cross-organization data sharing. Enterprise/regulator access is never
-- granted merely because a role string exists; the source cooperative must be in scope.
create table if not exists public.organization_data_grants (
  id uuid primary key default gen_random_uuid(),
  grantee_organization_id uuid not null references public.organizations(id) on delete cascade,
  source_organization_id uuid not null references public.organizations(id) on delete cascade,
  access_level public.data_access_level not null default 'read',
  valid_from date not null default current_date,
  valid_to date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (grantee_organization_id, source_organization_id),
  constraint organization_data_grants_distinct_chk
    check (grantee_organization_id <> source_organization_id),
  constraint organization_data_grants_dates_chk
    check (valid_to is null or valid_to >= valid_from)
);

-- --------------------------------------------------------------------------
-- 4. DATA INGESTION / CLEAN-DATA LINEAGE
-- --------------------------------------------------------------------------

create table if not exists public.ingestion_batches (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete set null,
  source_kind public.ingestion_source_kind not null,
  source_name text,
  source_sha256 text,
  source_as_of_at timestamptz,
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  status public.ingestion_status not null default 'received',
  records_received integer not null default 0 check (records_received >= 0),
  records_loaded integer not null default 0 check (records_loaded >= 0),
  records_rejected integer not null default 0 check (records_rejected >= 0),
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ingestion_sha256_chk
    check (source_sha256 is null or source_sha256 ~ '^[0-9a-fA-F]{64}$'),
  constraint ingestion_processed_chk
    check (processed_at is null or processed_at >= received_at)
);

create unique index if not exists ingestion_source_sha256_uidx
  on public.ingestion_batches(source_sha256)
  where source_sha256 is not null;

create table if not exists public.data_quality_flags (
  id uuid primary key default gen_random_uuid(),
  ingestion_batch_id uuid not null references public.ingestion_batches(id) on delete cascade,
  entity_table text not null,
  source_record_key text,
  severity public.quality_severity not null,
  flag_code text not null,
  message text not null,
  raw_value jsonb,
  status public.quality_flag_status not null default 'open',
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint data_quality_entity_chk check (btrim(entity_table) <> ''),
  constraint data_quality_code_chk check (btrim(flag_code) <> ''),
  constraint data_quality_message_chk check (btrim(message) <> '')
);

-- --------------------------------------------------------------------------
-- 5. MODULE 01 — MOBILE APP / FARM / OFFLINE-FIRST ACTIVITY DATA
-- --------------------------------------------------------------------------

create table if not exists public.farms (
  id uuid primary key default gen_random_uuid(),
  cooperative_id uuid not null references public.organizations(id) on delete restrict,
  farm_code text not null,
  farm_name text not null,
  province_name text,
  district_name text,
  commune_name text,
  ingestion_batch_id uuid references public.ingestion_batches(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  unique (cooperative_id, farm_code),
  constraint farms_code_chk check (btrim(farm_code) <> ''),
  constraint farms_name_chk check (btrim(farm_name) <> '')
);

create table if not exists public.farm_members (
  farm_id uuid not null references public.farms(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  farm_role public.farm_role not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (farm_id, user_id)
);

create table if not exists public.plots (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references public.farms(id) on delete cascade,
  plot_code text not null,
  name text not null,
  area_ha numeric(10,4) not null check (area_ha > 0),
  latitude numeric(9,6),
  longitude numeric(9,6),
  ingestion_batch_id uuid references public.ingestion_batches(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  unique (farm_id, plot_code),
  constraint plots_code_chk check (btrim(plot_code) <> ''),
  constraint plots_name_chk check (btrim(name) <> ''),
  constraint plots_lat_chk check (latitude is null or latitude between -90 and 90),
  constraint plots_lon_chk check (longitude is null or longitude between -180 and 180)
);

create table if not exists public.crop_seasons (
  id uuid primary key default gen_random_uuid(),
  plot_id uuid not null references public.plots(id) on delete cascade,
  season_code text not null,
  crop_type text not null default 'rice',
  variety_name text,
  planting_date date,
  expected_harvest_date date,
  actual_harvest_date date,
  default_irrigation_method public.irrigation_method,
  status public.crop_status not null default 'planned',
  ingestion_batch_id uuid references public.ingestion_batches(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  unique (plot_id, season_code),
  constraint crop_seasons_code_chk check (btrim(season_code) <> ''),
  constraint crop_seasons_harvest_dates_chk check (
    expected_harvest_date is null or planting_date is null or expected_harvest_date >= planting_date
  ),
  constraint crop_seasons_actual_harvest_chk check (
    actual_harvest_date is null or planting_date is null or actual_harvest_date >= planting_date
  )
);

-- Batch is the traceability/production unit under a crop season. Activities are
-- attached to a batch so the complete SRS tree is Farm→Plot→Crop→Batch→Activity.
create table if not exists public.production_batches (
  id uuid primary key default gen_random_uuid(),
  crop_season_id uuid not null references public.crop_seasons(id) on delete cascade,
  batch_code text not null,
  name text,
  started_on date,
  closed_on date,
  status public.batch_status not null default 'planned',
  ingestion_batch_id uuid references public.ingestion_batches(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  unique (crop_season_id, batch_code),
  constraint production_batches_code_chk check (btrim(batch_code) <> ''),
  constraint production_batches_dates_chk check (
    closed_on is null or started_on is null or closed_on >= started_on
  )
);

create table if not exists public.devices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  installation_id uuid not null unique,
  platform text not null,
  app_version text,
  registered_at timestamptz not null default now(),
  last_seen_at timestamptz,
  last_sync_at timestamptz,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint devices_platform_chk check (btrim(platform) <> '')
);

create table if not exists public.sync_batches (
  id uuid primary key default gen_random_uuid(),
  device_id uuid not null references public.devices(id) on delete cascade,
  client_batch_id uuid not null,
  client_started_at timestamptz,
  received_at timestamptz not null default now(),
  completed_at timestamptz,
  status public.sync_status not null default 'received',
  records_sent integer not null default 0 check (records_sent >= 0),
  records_accepted integer not null default 0 check (records_accepted >= 0),
  records_rejected integer not null default 0 check (records_rejected >= 0),
  error_summary text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (device_id, client_batch_id),
  constraint sync_batches_completed_chk check (
    completed_at is null or completed_at >= received_at
  )
);

create table if not exists public.activities (
  id uuid primary key default gen_random_uuid(),
  production_batch_id uuid not null references public.production_batches(id) on delete cascade,
  activity_type public.activity_type not null,
  occurred_at timestamptz not null,
  recorded_at timestamptz not null,
  server_received_at timestamptz not null default now(),
  source public.data_source not null,
  recorded_by uuid references public.profiles(id) on delete set null,
  device_id uuid references public.devices(id) on delete set null,
  client_event_id uuid,
  sync_batch_id uuid references public.sync_batches(id) on delete set null,
  ingestion_batch_id uuid references public.ingestion_batches(id) on delete set null,
  source_record_key text,
  note text,
  row_version bigint not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint activities_device_event_pair_chk check (
    (device_id is null and client_event_id is null)
    or (device_id is not null and client_event_id is not null)
  ),
  constraint activities_mobile_device_chk check (
    source not in ('mobile_offline','mobile_online') or device_id is not null
  )
);

create unique index if not exists activities_device_event_uidx
  on public.activities(device_id, client_event_id)
  where device_id is not null and client_event_id is not null;

create unique index if not exists activities_ingestion_source_record_uidx
  on public.activities(ingestion_batch_id, source_record_key)
  where ingestion_batch_id is not null and source_record_key is not null;

create table if not exists public.seeding_events (
  activity_id uuid primary key references public.activities(id) on delete cascade,
  variety_name text,
  seed_kg numeric(12,3) not null check (seed_kg > 0),
  seeding_method text,
  cost_vnd numeric(18,2) check (cost_vnd is null or cost_vnd >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.fertilizer_applications (
  activity_id uuid primary key references public.activities(id) on delete cascade,
  fertilizer_name text not null,
  fertilizer_type text,
  amount_kg numeric(14,3) not null check (amount_kg > 0),
  nitrogen_percent numeric(6,3),
  phosphorus_percent numeric(6,3),
  potassium_percent numeric(6,3),
  total_cost_vnd numeric(18,2),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint fertilizer_name_chk check (btrim(fertilizer_name) <> ''),
  constraint fertilizer_n_chk check (nitrogen_percent is null or nitrogen_percent between 0 and 100),
  constraint fertilizer_p_chk check (phosphorus_percent is null or phosphorus_percent between 0 and 100),
  constraint fertilizer_k_chk check (potassium_percent is null or potassium_percent between 0 and 100),
  constraint fertilizer_cost_chk check (total_cost_vnd is null or total_cost_vnd >= 0)
);

create table if not exists public.irrigation_events (
  activity_id uuid primary key references public.activities(id) on delete cascade,
  method public.irrigation_method not null,
  water_volume_m3 numeric(16,3),
  duration_minutes integer,
  water_level_cm numeric(10,2),
  pump_energy_kwh numeric(16,3),
  total_cost_vnd numeric(18,2),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint irrigation_water_chk check (water_volume_m3 is null or water_volume_m3 >= 0),
  constraint irrigation_duration_chk check (duration_minutes is null or duration_minutes >= 0),
  constraint irrigation_energy_chk check (pump_energy_kwh is null or pump_energy_kwh >= 0),
  constraint irrigation_cost_chk check (total_cost_vnd is null or total_cost_vnd >= 0)
);

create table if not exists public.pesticide_applications (
  activity_id uuid primary key references public.activities(id) on delete cascade,
  product_name text not null,
  active_ingredient text,
  amount numeric(14,3) not null check (amount > 0),
  unit text not null,
  total_cost_vnd numeric(18,2),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint pesticide_product_chk check (btrim(product_name) <> ''),
  constraint pesticide_unit_chk check (btrim(unit) <> ''),
  constraint pesticide_cost_chk check (total_cost_vnd is null or total_cost_vnd >= 0)
);

create table if not exists public.fuel_usages (
  activity_id uuid primary key references public.activities(id) on delete cascade,
  fuel_type public.fuel_type not null,
  amount_liter numeric(14,3) not null check (amount_liter > 0),
  equipment_name text,
  total_cost_vnd numeric(18,2),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint fuel_cost_chk check (total_cost_vnd is null or total_cost_vnd >= 0)
);

create table if not exists public.straw_management_events (
  activity_id uuid primary key references public.activities(id) on delete cascade,
  method public.straw_management_method not null,
  straw_mass_kg numeric(16,3),
  total_cost_vnd numeric(18,2),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint straw_mass_chk check (straw_mass_kg is null or straw_mass_kg >= 0),
  constraint straw_cost_chk check (total_cost_vnd is null or total_cost_vnd >= 0)
);

create table if not exists public.harvest_events (
  activity_id uuid primary key references public.activities(id) on delete cascade,
  yield_kg numeric(16,3) not null check (yield_kg > 0),
  harvested_area_ha numeric(10,4),
  moisture_percent numeric(6,3),
  total_cost_vnd numeric(18,2),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint harvest_area_chk check (harvested_area_ha is null or harvested_area_ha > 0),
  constraint harvest_moisture_chk check (moisture_percent is null or moisture_percent between 0 and 100),
  constraint harvest_cost_chk check (total_cost_vnd is null or total_cost_vnd >= 0)
);

-- --------------------------------------------------------------------------
-- 6. MODULE 02 — CARBON ENGINE / VERSIONED EMISSION FACTORS
-- --------------------------------------------------------------------------

create table if not exists public.emission_factor_sets (
  id uuid primary key default gen_random_uuid(),
  version_code text not null unique,
  name text not null,
  description text,
  methodology_name text not null,
  methodology_version text,
  valid_from date,
  valid_to date,
  source_name text not null,
  source_url text,
  status public.ef_status not null default 'draft',
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ef_set_version_chk check (btrim(version_code) <> ''),
  constraint ef_set_name_chk check (btrim(name) <> ''),
  constraint ef_set_methodology_chk check (btrim(methodology_name) <> ''),
  constraint ef_set_source_chk check (btrim(source_name) <> ''),
  constraint ef_set_dates_chk check (valid_to is null or valid_from is null or valid_to >= valid_from),
  constraint ef_set_published_chk check (status <> 'published' or published_at is not null)
);

create table if not exists public.emission_factors (
  id uuid primary key default gen_random_uuid(),
  factor_set_id uuid not null references public.emission_factor_sets(id) on delete restrict,
  factor_code text not null,
  category public.emission_category not null,
  gas public.greenhouse_gas not null,
  activity_unit text not null,
  result_unit text not null default 'kgCO2e',
  factor_value numeric(24,12) not null check (factor_value >= 0),
  source_reference text not null,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (factor_set_id, factor_code),
  constraint ef_factor_code_chk check (btrim(factor_code) <> ''),
  constraint ef_activity_unit_chk check (btrim(activity_unit) <> ''),
  constraint ef_result_unit_chk check (btrim(result_unit) <> ''),
  constraint ef_source_reference_chk check (btrim(source_reference) <> '')
);

create table if not exists public.carbon_calculations (
  id uuid primary key default gen_random_uuid(),
  production_batch_id uuid not null references public.production_batches(id) on delete cascade,
  scenario public.carbon_scenario not null,
  factor_set_id uuid not null references public.emission_factor_sets(id) on delete restrict,
  engine_version text not null,
  input_hash text not null,
  total_co2e_kg numeric(20,6),
  yield_kg numeric(20,6),
  co2e_per_kg numeric(20,8)
    generated always as (total_co2e_kg / nullif(yield_kg, 0)) stored,
  status public.calculation_status not null default 'pending',
  failure_reason text,
  supersedes_id uuid references public.carbon_calculations(id) on delete set null,
  calculated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (production_batch_id, scenario, factor_set_id, input_hash),
  constraint carbon_engine_version_chk check (btrim(engine_version) <> ''),
  constraint carbon_input_hash_chk check (input_hash ~ '^[0-9a-fA-F]{64}$'),
  constraint carbon_total_chk check (total_co2e_kg is null or total_co2e_kg >= 0),
  constraint carbon_yield_chk check (yield_kg is null or yield_kg > 0),
  constraint carbon_success_chk check (
    status <> 'succeeded'
    or (total_co2e_kg is not null and yield_kg is not null and failure_reason is null)
  ),
  constraint carbon_failure_chk check (
    status <> 'failed' or (failure_reason is not null and btrim(failure_reason) <> '')
  )
);

create table if not exists public.carbon_breakdowns (
  id uuid primary key default gen_random_uuid(),
  calculation_id uuid not null references public.carbon_calculations(id) on delete cascade,
  activity_id uuid references public.activities(id) on delete set null,
  emission_factor_id uuid not null references public.emission_factors(id) on delete restrict,
  category public.emission_category not null,
  gas public.greenhouse_gas not null,
  activity_value numeric(24,8) not null check (activity_value >= 0),
  activity_unit text not null,
  factor_value_used numeric(24,12) not null check (factor_value_used >= 0),
  co2e_kg numeric(20,6) not null check (co2e_kg >= 0),
  formula_note text,
  created_at timestamptz not null default now(),
  constraint carbon_breakdown_unit_chk check (btrim(activity_unit) <> '')
);

-- --------------------------------------------------------------------------
-- 7. MODULE 03 — COMPUTER VISION
-- --------------------------------------------------------------------------

create table if not exists public.plant_images (
  id uuid primary key default gen_random_uuid(),
  crop_season_id uuid not null references public.crop_seasons(id) on delete cascade,
  storage_bucket text not null default 'plant-images',
  storage_object_path text not null unique,
  mime_type text not null,
  file_size_bytes bigint check (file_size_bytes is null or file_size_bytes > 0),
  sha256 text,
  captured_at timestamptz,
  uploaded_at timestamptz not null default now(),
  uploaded_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint plant_images_bucket_chk check (btrim(storage_bucket) <> ''),
  constraint plant_images_path_chk check (btrim(storage_object_path) <> ''),
  constraint plant_images_mime_chk check (mime_type in ('image/jpeg','image/png')),
  constraint plant_images_sha_chk check (sha256 is null or sha256 ~ '^[0-9a-fA-F]{64}$')
);

create unique index if not exists plant_images_sha_uidx
  on public.plant_images(sha256)
  where sha256 is not null and deleted_at is null;

create table if not exists public.cv_model_versions (
  id uuid primary key default gen_random_uuid(),
  model_name text not null,
  version_code text not null unique,
  test_dataset_name text not null,
  test_dataset_version text,
  test_sample_count integer check (test_sample_count is null or test_sample_count > 0),
  accuracy numeric(7,6) not null check (accuracy between 0 and 1),
  confusion_matrix jsonb not null,
  confidence_threshold numeric(7,6) not null check (confidence_threshold between 0 and 1),
  source_reference text,
  status public.model_status not null default 'draft',
  deployed_at timestamptz,
  retired_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint cv_model_name_chk check (btrim(model_name) <> ''),
  constraint cv_model_version_chk check (btrim(version_code) <> ''),
  constraint cv_test_dataset_chk check (btrim(test_dataset_name) <> ''),
  constraint cv_model_dates_chk check (retired_at is null or deployed_at is null or retired_at >= deployed_at)
);

create table if not exists public.cv_inferences (
  id uuid primary key default gen_random_uuid(),
  image_id uuid not null references public.plant_images(id) on delete cascade,
  model_version_id uuid not null references public.cv_model_versions(id) on delete restrict,
  predicted_label public.disease_label not null,
  confidence numeric(7,6) not null check (confidence between 0 and 1),
  threshold_used numeric(7,6) not null check (threshold_used between 0 and 1),
  is_uncertain boolean generated always as (confidence < threshold_used) stored,
  inferred_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (image_id, model_version_id)
);

-- --------------------------------------------------------------------------
-- 8. MODULE 04 — RESOURCE EFFICIENCY / BENCHMARKS
-- --------------------------------------------------------------------------

-- Immutable-ish analytical snapshot. Values that are mathematically derived use
-- generated columns so numerator/denominator cannot drift apart.
create table if not exists public.resource_metric_snapshots (
  id uuid primary key default gen_random_uuid(),
  production_batch_id uuid not null references public.production_batches(id) on delete cascade,
  carbon_calculation_id uuid not null references public.carbon_calculations(id) on delete restrict,
  calculation_version text not null,
  input_hash text not null,
  yield_kg numeric(20,6) not null check (yield_kg > 0),
  water_m3 numeric(20,6),
  fertilizer_kg numeric(20,6),
  total_cost_vnd numeric(22,2),
  total_co2e_kg numeric(20,6) not null check (total_co2e_kg >= 0),
  water_data_complete boolean not null default false,
  cost_data_complete boolean not null default false,
  water_per_kg numeric(20,8)
    generated always as (water_m3 / nullif(yield_kg, 0)) stored,
  fertilizer_per_kg numeric(20,8)
    generated always as (fertilizer_kg / nullif(yield_kg, 0)) stored,
  co2e_per_kg numeric(20,8)
    generated always as (total_co2e_kg / nullif(yield_kg, 0)) stored,
  cost_per_kg numeric(20,8)
    generated always as (total_cost_vnd / nullif(yield_kg, 0)) stored,
  calculated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (production_batch_id, input_hash),
  constraint resource_snapshot_hash_chk check (input_hash ~ '^[0-9a-fA-F]{64}$'),
  constraint resource_water_chk check (water_m3 is null or water_m3 >= 0),
  constraint resource_fertilizer_chk check (fertilizer_kg is null or fertilizer_kg >= 0),
  constraint resource_cost_chk check (total_cost_vnd is null or total_cost_vnd >= 0)
);

create table if not exists public.benchmark_snapshots (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  metric_code public.resource_metric_code not null,
  status public.benchmark_status not null default 'draft',
  period_start date not null,
  period_end date not null,
  source_name text not null,
  source_reference text not null,
  calculated_at timestamptz not null default now(),
  finalized_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint benchmark_period_chk check (period_end >= period_start),
  constraint benchmark_source_name_chk check (btrim(source_name) <> ''),
  constraint benchmark_source_ref_chk check (btrim(source_reference) <> ''),
  constraint benchmark_finalized_at_chk check (status <> 'finalized' or finalized_at is not null)
);

create table if not exists public.benchmark_snapshot_members (
  benchmark_snapshot_id uuid not null references public.benchmark_snapshots(id) on delete cascade,
  production_batch_id uuid not null references public.production_batches(id) on delete restrict,
  metric_value numeric(24,10) not null check (metric_value >= 0),
  created_at timestamptz not null default now(),
  primary key (benchmark_snapshot_id, production_batch_id)
);

-- --------------------------------------------------------------------------
-- 9. MODULE 05 — RULE-BASED RECOMMENDATION
-- --------------------------------------------------------------------------

create table if not exists public.recommendation_rules (
  id uuid primary key default gen_random_uuid(),
  rule_code text not null,
  version_code text not null,
  metric_code public.resource_metric_code not null,
  operator public.comparison_operator not null,
  threshold_percent numeric(10,4) not null check (threshold_percent >= 0),
  action_template text not null,
  calculation_note text not null,
  source_name text not null,
  source_reference text not null,
  valid_from date,
  valid_to date,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (rule_code, version_code),
  constraint recommendation_rule_code_chk check (btrim(rule_code) <> ''),
  constraint recommendation_rule_version_chk check (btrim(version_code) <> ''),
  constraint recommendation_rule_template_chk check (btrim(action_template) <> ''),
  constraint recommendation_rule_calc_chk check (btrim(calculation_note) <> ''),
  constraint recommendation_rule_source_chk check (btrim(source_name) <> '' and btrim(source_reference) <> ''),
  constraint recommendation_rule_dates_chk check (valid_to is null or valid_from is null or valid_to >= valid_from)
);

create table if not exists public.recommendations (
  id uuid primary key default gen_random_uuid(),
  production_batch_id uuid not null references public.production_batches(id) on delete cascade,
  rule_id uuid not null references public.recommendation_rules(id) on delete restrict,
  benchmark_snapshot_id uuid not null references public.benchmark_snapshots(id) on delete restrict,
  resource_snapshot_id uuid not null references public.resource_metric_snapshots(id) on delete restrict,
  current_value numeric(24,10) not null,
  benchmark_value_used numeric(24,10) not null,
  difference_percent numeric(12,6) not null,
  target_value numeric(24,10) not null,
  estimated_co2e_reduction_kg numeric(20,6) not null check (estimated_co2e_reduction_kg >= 0),
  estimated_cost_change_vnd numeric(22,2) not null,
  recommendation_text text not null,
  status public.recommendation_status not null default 'generated',
  generated_at timestamptz not null default now(),
  accepted_at timestamptz,
  dismissed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint recommendation_text_chk check (btrim(recommendation_text) <> ''),
  constraint recommendation_status_dates_chk check (
    (status <> 'accepted' or accepted_at is not null)
    and (status <> 'dismissed' or dismissed_at is not null)
  )
);

-- --------------------------------------------------------------------------
-- 10. MODULE 07 — MRV 6-STEP WORKFLOW / EXPORT
-- --------------------------------------------------------------------------

create table if not exists public.mrv_step_catalog (
  step_no smallint primary key check (step_no between 1 and 6),
  name text not null unique,
  description text not null
);

create table if not exists public.mrv_cases (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  case_code text not null,
  name text not null,
  period_start date not null,
  period_end date not null,
  status public.mrv_case_status not null default 'draft',
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, case_code),
  constraint mrv_case_code_chk check (btrim(case_code) <> ''),
  constraint mrv_case_name_chk check (btrim(name) <> ''),
  constraint mrv_case_period_chk check (period_end >= period_start)
);

create table if not exists public.mrv_case_batches (
  mrv_case_id uuid not null references public.mrv_cases(id) on delete cascade,
  production_batch_id uuid not null references public.production_batches(id) on delete restrict,
  added_at timestamptz not null default now(),
  primary key (mrv_case_id, production_batch_id)
);

create table if not exists public.mrv_case_steps (
  mrv_case_id uuid not null references public.mrv_cases(id) on delete cascade,
  step_no smallint not null references public.mrv_step_catalog(step_no) on delete restrict,
  status public.mrv_step_status not null default 'not_started',
  started_at timestamptz,
  completed_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (mrv_case_id, step_no),
  constraint mrv_step_dates_chk check (completed_at is null or started_at is null or completed_at >= started_at),
  constraint mrv_step_completed_chk check (status <> 'completed' or completed_at is not null)
);

create table if not exists public.mrv_evidence (
  id uuid primary key default gen_random_uuid(),
  mrv_case_id uuid not null references public.mrv_cases(id) on delete cascade,
  step_no smallint not null references public.mrv_step_catalog(step_no) on delete restrict,
  production_batch_id uuid references public.production_batches(id) on delete set null,
  evidence_type text not null,
  storage_bucket text not null default 'mrv-evidence',
  storage_object_path text not null unique,
  file_name text not null,
  mime_type text not null,
  sha256 text,
  notes text,
  uploaded_by uuid references public.profiles(id) on delete set null,
  uploaded_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint mrv_evidence_type_chk check (btrim(evidence_type) <> ''),
  constraint mrv_evidence_bucket_chk check (btrim(storage_bucket) <> ''),
  constraint mrv_evidence_path_chk check (btrim(storage_object_path) <> ''),
  constraint mrv_evidence_filename_chk check (btrim(file_name) <> ''),
  constraint mrv_evidence_sha_chk check (sha256 is null or sha256 ~ '^[0-9a-fA-F]{64}$')
);

create table if not exists public.mrv_exports (
  id uuid primary key default gen_random_uuid(),
  mrv_case_id uuid not null references public.mrv_cases(id) on delete cascade,
  format public.export_format not null,
  factor_set_id uuid not null references public.emission_factor_sets(id) on delete restrict,
  scope_description text not null,
  data_as_of_at timestamptz not null,
  contains_sample_data boolean not null default false,
  is_finalized boolean not null default false,
  warning_text text,
  storage_bucket text not null default 'mrv-exports',
  storage_object_path text not null unique,
  file_sha256 text,
  export_payload jsonb not null,
  generated_by uuid references public.profiles(id) on delete set null,
  generated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint mrv_export_scope_chk check (btrim(scope_description) <> ''),
  constraint mrv_export_warning_chk check (
    (not contains_sample_data and is_finalized)
    or (warning_text is not null and btrim(warning_text) <> '')
  ),
  constraint mrv_export_sha_chk check (file_sha256 is null or file_sha256 ~ '^[0-9a-fA-F]{64}$')
);

create table if not exists public.mrv_export_calculations (
  mrv_export_id uuid not null references public.mrv_exports(id) on delete cascade,
  carbon_calculation_id uuid not null references public.carbon_calculations(id) on delete restrict,
  primary key (mrv_export_id, carbon_calculation_id)
);

-- --------------------------------------------------------------------------
-- 11. INTEGRITY TRIGGERS / BUSINESS INVARIANTS
-- --------------------------------------------------------------------------

create or replace function private.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles(id, full_name)
  values (new.id, nullif(btrim(new.raw_user_meta_data->>'full_name'), ''))
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function private.handle_new_user();

-- Backfill profiles if Auth users already existed before this migration.
insert into public.profiles(id, full_name)
select id, nullif(btrim(raw_user_meta_data->>'full_name'), '')
from auth.users
on conflict (id) do nothing;

create or replace function private.validate_farm_cooperative()
returns trigger
language plpgsql
set search_path = ''
as $$
declare v_type public.organization_type;
begin
  select organization_type into v_type
  from public.organizations where id = new.cooperative_id;
  if v_type is distinct from 'cooperative'::public.organization_type then
    raise exception 'farms.cooperative_id must reference an organization of type cooperative';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_farm_cooperative_trg on public.farms;
create trigger validate_farm_cooperative_trg
  before insert or update of cooperative_id on public.farms
  for each row execute function private.validate_farm_cooperative();

create or replace function private.validate_farm_member()
returns trigger
language plpgsql
set search_path = ''
as $$
declare v_org uuid;
begin
  select cooperative_id into v_org from public.farms where id = new.farm_id;
  if not exists (
    select 1 from public.organization_memberships om
    where om.organization_id = v_org
      and om.user_id = new.user_id
      and (om.ended_at is null or om.ended_at > now())
  ) then
    raise exception 'Farm member must also be an active member of the farm cooperative';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_farm_member_trg on public.farm_members;
create trigger validate_farm_member_trg
  before insert or update on public.farm_members
  for each row execute function private.validate_farm_member();

create or replace function private.enforce_activity_type()
returns trigger
language plpgsql
set search_path = ''
as $$
declare v_type public.activity_type;
begin
  select activity_type into v_type from public.activities where id = new.activity_id;
  if v_type::text is distinct from tg_argv[0] then
    raise exception 'Activity % has type %, expected % for table %', new.activity_id, v_type, tg_argv[0], tg_table_name;
  end if;
  return new;
end;
$$;

-- Detail table type guards

drop trigger if exists seeding_type_trg on public.seeding_events;
create trigger seeding_type_trg before insert or update on public.seeding_events
for each row execute function private.enforce_activity_type('seeding');

drop trigger if exists fertilizer_type_trg on public.fertilizer_applications;
create trigger fertilizer_type_trg before insert or update on public.fertilizer_applications
for each row execute function private.enforce_activity_type('fertilizer');

drop trigger if exists irrigation_type_trg on public.irrigation_events;
create trigger irrigation_type_trg before insert or update on public.irrigation_events
for each row execute function private.enforce_activity_type('irrigation');

drop trigger if exists pesticide_type_trg on public.pesticide_applications;
create trigger pesticide_type_trg before insert or update on public.pesticide_applications
for each row execute function private.enforce_activity_type('pesticide');

drop trigger if exists fuel_type_trg on public.fuel_usages;
create trigger fuel_type_trg before insert or update on public.fuel_usages
for each row execute function private.enforce_activity_type('fuel');

drop trigger if exists straw_type_trg on public.straw_management_events;
create trigger straw_type_trg before insert or update on public.straw_management_events
for each row execute function private.enforce_activity_type('straw_management');

drop trigger if exists harvest_type_trg on public.harvest_events;
create trigger harvest_type_trg before insert or update on public.harvest_events
for each row execute function private.enforce_activity_type('harvest');

create or replace function private.validate_carbon_breakdown()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_calc_factor_set uuid;
  v_factor_set uuid;
  v_calc_batch uuid;
  v_activity_batch uuid;
begin
  select factor_set_id, production_batch_id
    into v_calc_factor_set, v_calc_batch
  from public.carbon_calculations where id = new.calculation_id;

  select factor_set_id into v_factor_set
  from public.emission_factors where id = new.emission_factor_id;

  if v_calc_factor_set is distinct from v_factor_set then
    raise exception 'Emission factor must belong to the factor set used by the calculation';
  end if;

  if new.activity_id is not null then
    select production_batch_id into v_activity_batch
    from public.activities where id = new.activity_id;
    if v_activity_batch is distinct from v_calc_batch then
      raise exception 'Breakdown activity must belong to the same production batch as the calculation';
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists validate_carbon_breakdown_trg on public.carbon_breakdowns;
create trigger validate_carbon_breakdown_trg
before insert or update on public.carbon_breakdowns
for each row execute function private.validate_carbon_breakdown();

create or replace function private.validate_resource_snapshot()
returns trigger
language plpgsql
set search_path = ''
as $$
declare v_batch uuid; v_status public.calculation_status;
begin
  select production_batch_id, status into v_batch, v_status
  from public.carbon_calculations where id = new.carbon_calculation_id;
  if v_batch is distinct from new.production_batch_id then
    raise exception 'Resource snapshot and carbon calculation must reference the same production batch';
  end if;
  if v_status is distinct from 'succeeded'::public.calculation_status then
    raise exception 'Resource snapshot requires a succeeded carbon calculation';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_resource_snapshot_trg on public.resource_metric_snapshots;
create trigger validate_resource_snapshot_trg
before insert or update on public.resource_metric_snapshots
for each row execute function private.validate_resource_snapshot();

create or replace function private.validate_benchmark_member()
returns trigger
language plpgsql
set search_path = ''
as $$
declare v_org uuid; v_status public.benchmark_status;
begin
  select bs.organization_id, bs.status into v_org, v_status
  from public.benchmark_snapshots bs where bs.id = new.benchmark_snapshot_id;

  if v_status = 'finalized'::public.benchmark_status then
    raise exception 'Finalized benchmark snapshots are immutable';
  end if;

  if not exists (
    select 1
    from public.production_batches pb
    join public.crop_seasons cs on cs.id = pb.crop_season_id
    join public.plots p on p.id = cs.plot_id
    join public.farms f on f.id = p.farm_id
    where pb.id = new.production_batch_id and f.cooperative_id = v_org
  ) then
    raise exception 'Benchmark member must belong to the benchmark cooperative';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_benchmark_member_trg on public.benchmark_snapshot_members;
create trigger validate_benchmark_member_trg
before insert or update on public.benchmark_snapshot_members
for each row execute function private.validate_benchmark_member();

create or replace function private.prevent_finalized_benchmark_member_delete()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (
    select 1 from public.benchmark_snapshots
    where id = old.benchmark_snapshot_id and status = 'finalized'::public.benchmark_status
  ) then
    raise exception 'Finalized benchmark snapshots are immutable';
  end if;
  return old;
end;
$$;

drop trigger if exists prevent_finalized_benchmark_member_delete_trg on public.benchmark_snapshot_members;
create trigger prevent_finalized_benchmark_member_delete_trg
before delete on public.benchmark_snapshot_members
for each row execute function private.prevent_finalized_benchmark_member_delete();

create or replace function private.validate_benchmark_finalization()
returns trigger
language plpgsql
set search_path = ''
as $$
declare v_count integer;
begin
  if new.status = 'finalized'::public.benchmark_status
     and old.status is distinct from 'finalized'::public.benchmark_status then
    select count(*) into v_count
    from public.benchmark_snapshot_members
    where benchmark_snapshot_id = new.id;
    if v_count < 3 then
      raise exception 'A finalized benchmark requires at least 3 comparable batches/plots';
    end if;
    new.finalized_at := coalesce(new.finalized_at, now());
  end if;
  return new;
end;
$$;

drop trigger if exists validate_benchmark_finalization_trg on public.benchmark_snapshots;
create trigger validate_benchmark_finalization_trg
before update of status on public.benchmark_snapshots
for each row execute function private.validate_benchmark_finalization();

create or replace function private.validate_recommendation_lineage()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_rule_metric public.resource_metric_code;
  v_bench_metric public.resource_metric_code;
  v_bench_status public.benchmark_status;
  v_resource_batch uuid;
begin
  select metric_code into v_rule_metric from public.recommendation_rules where id = new.rule_id;
  select metric_code, status into v_bench_metric, v_bench_status
    from public.benchmark_snapshots where id = new.benchmark_snapshot_id;
  select production_batch_id into v_resource_batch
    from public.resource_metric_snapshots where id = new.resource_snapshot_id;

  if v_rule_metric is distinct from v_bench_metric then
    raise exception 'Recommendation rule metric and benchmark metric must match';
  end if;
  if v_bench_status is distinct from 'finalized'::public.benchmark_status then
    raise exception 'Recommendation requires a finalized benchmark snapshot';
  end if;
  if v_resource_batch is distinct from new.production_batch_id then
    raise exception 'Recommendation resource snapshot must belong to the same production batch';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_recommendation_lineage_trg on public.recommendations;
create trigger validate_recommendation_lineage_trg
before insert or update on public.recommendations
for each row execute function private.validate_recommendation_lineage();

create or replace function private.populate_mrv_steps()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  insert into public.mrv_case_steps(mrv_case_id, step_no)
  select new.id, step_no from public.mrv_step_catalog
  on conflict do nothing;
  return new;
end;
$$;

drop trigger if exists populate_mrv_steps_trg on public.mrv_cases;
create trigger populate_mrv_steps_trg
after insert on public.mrv_cases
for each row execute function private.populate_mrv_steps();

create or replace function private.validate_mrv_case_batch()
returns trigger
language plpgsql
set search_path = ''
as $$
declare v_case_org uuid; v_batch_org uuid;
begin
  select organization_id into v_case_org from public.mrv_cases where id = new.mrv_case_id;
  select f.cooperative_id into v_batch_org
  from public.production_batches pb
  join public.crop_seasons cs on cs.id = pb.crop_season_id
  join public.plots p on p.id = cs.plot_id
  join public.farms f on f.id = p.farm_id
  where pb.id = new.production_batch_id;
  if v_case_org is distinct from v_batch_org then
    raise exception 'MRV case may contain only production batches from its cooperative';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_mrv_case_batch_trg on public.mrv_case_batches;
create trigger validate_mrv_case_batch_trg
before insert or update on public.mrv_case_batches
for each row execute function private.validate_mrv_case_batch();

create or replace function private.validate_mrv_export_calculation()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_case uuid;
  v_factor_set uuid;
  v_calc_factor_set uuid;
  v_batch uuid;
begin
  select mrv_case_id, factor_set_id into v_case, v_factor_set
  from public.mrv_exports where id = new.mrv_export_id;
  select factor_set_id, production_batch_id into v_calc_factor_set, v_batch
  from public.carbon_calculations where id = new.carbon_calculation_id;

  if v_factor_set is distinct from v_calc_factor_set then
    raise exception 'All calculations in an MRV export must use the export factor-set version';
  end if;
  if not exists (
    select 1 from public.mrv_case_batches
    where mrv_case_id = v_case and production_batch_id = v_batch
  ) then
    raise exception 'MRV export calculation batch must be inside the MRV case scope';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_mrv_export_calculation_trg on public.mrv_export_calculations;
create trigger validate_mrv_export_calculation_trg
before insert or update on public.mrv_export_calculations
for each row execute function private.validate_mrv_export_calculation();

create or replace function private.validate_plant_image_path()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_farm uuid;
  v_folder1 uuid;
  v_folder2 uuid;
begin
  select p.farm_id into v_farm
  from public.crop_seasons cs
  join public.plots p on p.id = cs.plot_id
  where cs.id = new.crop_season_id;

  v_folder1 := private.try_uuid(split_part(new.storage_object_path, '/', 1));
  v_folder2 := private.try_uuid(split_part(new.storage_object_path, '/', 2));

  if v_folder1 is distinct from v_farm or v_folder2 is distinct from new.crop_season_id then
    raise exception 'Plant image path must be <farm_uuid>/<crop_season_uuid>/<file>';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_plant_image_path_trg on public.plant_images;
create trigger validate_plant_image_path_trg
before insert or update of crop_season_id, storage_object_path on public.plant_images
for each row execute function private.validate_plant_image_path();

create or replace function private.validate_mrv_file_path()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_org uuid;
  v_folder1 uuid;
  v_folder2 uuid;
begin
  select organization_id into v_org from public.mrv_cases where id = new.mrv_case_id;
  v_folder1 := private.try_uuid(split_part(new.storage_object_path, '/', 1));
  v_folder2 := private.try_uuid(split_part(new.storage_object_path, '/', 2));
  if v_folder1 is distinct from v_org or v_folder2 is distinct from new.mrv_case_id then
    raise exception 'MRV file path must be <organization_uuid>/<mrv_case_uuid>/<file>';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_mrv_evidence_path_trg on public.mrv_evidence;
create trigger validate_mrv_evidence_path_trg
before insert or update of mrv_case_id, storage_object_path on public.mrv_evidence
for each row execute function private.validate_mrv_file_path();

drop trigger if exists validate_mrv_export_path_trg on public.mrv_exports;
create trigger validate_mrv_export_path_trg
before insert or update of mrv_case_id, storage_object_path on public.mrv_exports
for each row execute function private.validate_mrv_file_path();

create or replace function private.validate_mrv_evidence_batch()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.production_batch_id is not null and not exists (
    select 1 from public.mrv_case_batches mcb
    where mcb.mrv_case_id = new.mrv_case_id
      and mcb.production_batch_id = new.production_batch_id
  ) then
    raise exception 'MRV evidence batch must belong to the MRV case scope';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_mrv_evidence_batch_trg on public.mrv_evidence;
create trigger validate_mrv_evidence_batch_trg
before insert or update of mrv_case_id, production_batch_id on public.mrv_evidence
for each row execute function private.validate_mrv_evidence_batch();

-- --------------------------------------------------------------------------
-- 12. UPDATED_AT TRIGGERS
-- --------------------------------------------------------------------------

do $$
declare t text;
begin
  foreach t in array array[
    'profiles','organizations','organization_memberships','organization_data_grants',
    'ingestion_batches','data_quality_flags','farms','farm_members','plots','crop_seasons',
    'production_batches','devices','sync_batches','seeding_events','fertilizer_applications',
    'irrigation_events','pesticide_applications','fuel_usages','straw_management_events',
    'harvest_events','emission_factor_sets','emission_factors','plant_images','cv_model_versions',
    'benchmark_snapshots','recommendation_rules','recommendations','mrv_cases','mrv_case_steps',
    'mrv_evidence'
  ] loop
    execute format('drop trigger if exists set_updated_at_trg on public.%I', t);
    execute format('create trigger set_updated_at_trg before update on public.%I for each row execute function private.set_updated_at()', t);
  end loop;
end $$;

-- Activities also increment the optimistic concurrency version used for offline sync.
drop trigger if exists touch_activity_row_trg on public.activities;
create trigger touch_activity_row_trg
before update on public.activities
for each row execute function private.touch_activity_row();

-- --------------------------------------------------------------------------
-- 13. INDEXES FOR JOINS, RLS AND DASHBOARD QUERIES
-- --------------------------------------------------------------------------

create index if not exists organization_memberships_user_idx on public.organization_memberships(user_id, organization_id);
create index if not exists organization_memberships_org_role_idx on public.organization_memberships(organization_id, role);
create index if not exists organization_data_grants_grantee_idx on public.organization_data_grants(grantee_organization_id, source_organization_id);
create index if not exists organization_data_grants_source_idx on public.organization_data_grants(source_organization_id);
create index if not exists farms_cooperative_idx on public.farms(cooperative_id) where deleted_at is null;
create index if not exists farm_members_user_idx on public.farm_members(user_id, farm_id);
create index if not exists plots_farm_idx on public.plots(farm_id) where deleted_at is null;
create index if not exists crop_seasons_plot_idx on public.crop_seasons(plot_id) where deleted_at is null;
create index if not exists production_batches_crop_idx on public.production_batches(crop_season_id) where deleted_at is null;
create index if not exists devices_user_idx on public.devices(user_id);
create index if not exists sync_batches_device_idx on public.sync_batches(device_id, received_at desc);
create index if not exists activities_batch_time_idx on public.activities(production_batch_id, occurred_at desc) where deleted_at is null;
create index if not exists activities_recorded_by_idx on public.activities(recorded_by) where deleted_at is null;
create index if not exists carbon_calculations_batch_idx on public.carbon_calculations(production_batch_id, calculated_at desc);
create index if not exists carbon_breakdowns_calculation_idx on public.carbon_breakdowns(calculation_id);
create index if not exists plant_images_crop_idx on public.plant_images(crop_season_id, captured_at desc) where deleted_at is null;
create index if not exists cv_inferences_image_idx on public.cv_inferences(image_id, inferred_at desc);
create index if not exists resource_snapshots_batch_idx on public.resource_metric_snapshots(production_batch_id, calculated_at desc);
create index if not exists benchmark_snapshots_org_metric_idx on public.benchmark_snapshots(organization_id, metric_code, calculated_at desc);
create index if not exists benchmark_members_batch_idx on public.benchmark_snapshot_members(production_batch_id);
create index if not exists recommendations_batch_idx on public.recommendations(production_batch_id, generated_at desc);
create index if not exists mrv_cases_org_idx on public.mrv_cases(organization_id, period_start, period_end);
create index if not exists mrv_case_batches_batch_idx on public.mrv_case_batches(production_batch_id);
create index if not exists mrv_evidence_case_step_idx on public.mrv_evidence(mrv_case_id, step_no);

-- --------------------------------------------------------------------------
-- 14. RLS HELPER FUNCTIONS (PRIVATE, SECURITY DEFINER)
-- --------------------------------------------------------------------------

create or replace function private.user_is_org_member(p_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.organization_memberships om
    where om.organization_id = p_org
      and om.user_id = (select auth.uid())
      and (om.ended_at is null or om.ended_at > now())
  );
$$;

create or replace function private.user_is_org_manager(p_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.organization_memberships om
    where om.organization_id = p_org
      and om.user_id = (select auth.uid())
      and om.role = 'cooperative_manager'::public.organization_role
      and (om.ended_at is null or om.ended_at > now())
  );
$$;

create or replace function private.user_can_read_organization(p_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select
    private.user_is_org_member(p_org)
    or exists (
      select 1
      from public.organization_data_grants g
      join public.organization_memberships om
        on om.organization_id = g.grantee_organization_id
      where g.source_organization_id = p_org
        and om.user_id = (select auth.uid())
        and om.role in ('enterprise_viewer'::public.organization_role,'regulator'::public.organization_role)
        and (om.ended_at is null or om.ended_at > now())
        and g.valid_from <= current_date
        and (g.valid_to is null or g.valid_to >= current_date)
    );
$$;

create or replace function private.user_can_read_profile(p_user uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select p_user = (select auth.uid())
  or exists (
    select 1
    from public.organization_memberships mine
    join public.organization_memberships theirs
      on theirs.organization_id = mine.organization_id
    where mine.user_id = (select auth.uid())
      and theirs.user_id = p_user
      and (mine.ended_at is null or mine.ended_at > now())
      and (theirs.ended_at is null or theirs.ended_at > now())
  );
$$;

create or replace function private.user_can_read_farm(p_farm uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.farm_members fm
    where fm.farm_id = p_farm and fm.user_id = (select auth.uid())
  )
  or exists (
    select 1 from public.farms f
    where f.id = p_farm
      and (
        private.user_is_org_manager(f.cooperative_id)
        or exists (
          select 1
          from public.organization_data_grants g
          join public.organization_memberships om
            on om.organization_id = g.grantee_organization_id
          where g.source_organization_id = f.cooperative_id
            and om.user_id = (select auth.uid())
            and om.role in ('enterprise_viewer'::public.organization_role,'regulator'::public.organization_role)
            and (om.ended_at is null or om.ended_at > now())
            and g.valid_from <= current_date
            and (g.valid_to is null or g.valid_to >= current_date)
        )
      )
  );
$$;

create or replace function private.user_can_write_farm(p_farm uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.farm_members fm
    where fm.farm_id = p_farm
      and fm.user_id = (select auth.uid())
      and fm.farm_role in ('owner'::public.farm_role,'editor'::public.farm_role)
  )
  or exists (
    select 1 from public.farms f
    where f.id = p_farm and private.user_is_org_manager(f.cooperative_id)
  );
$$;

create or replace function private.user_can_manage_farm_members(p_farm uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.farm_members fm
    where fm.farm_id = p_farm
      and fm.user_id = (select auth.uid())
      and fm.farm_role = 'owner'::public.farm_role
  )
  or exists (
    select 1 from public.farms f
    where f.id = p_farm and private.user_is_org_manager(f.cooperative_id)
  );
$$;

create or replace function private.user_can_read_crop(p_crop uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.crop_seasons cs
    join public.plots p on p.id = cs.plot_id
    where cs.id = p_crop and private.user_can_read_farm(p.farm_id)
  );
$$;

create or replace function private.user_can_write_crop(p_crop uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.crop_seasons cs
    join public.plots p on p.id = cs.plot_id
    where cs.id = p_crop and private.user_can_write_farm(p.farm_id)
  );
$$;

create or replace function private.user_can_read_batch(p_batch uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.production_batches pb
    where pb.id = p_batch and private.user_can_read_crop(pb.crop_season_id)
  );
$$;

create or replace function private.user_can_write_batch(p_batch uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.production_batches pb
    where pb.id = p_batch and private.user_can_write_crop(pb.crop_season_id)
  );
$$;

create or replace function private.user_can_read_mrv_case(p_case uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.mrv_cases mc
    where mc.id = p_case and private.user_can_read_organization(mc.organization_id)
  );
$$;

create or replace function private.user_can_manage_mrv_case(p_case uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.mrv_cases mc
    where mc.id = p_case and private.user_is_org_manager(mc.organization_id)
  );
$$;

revoke all on schema private from public;
grant usage on schema private to authenticated;

-- All security-definer helpers are used by policies only.
do $$
declare r record;
begin
  for r in
    select p.oid::regprocedure as sig
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'private'
      and p.prosecdef
  loop
    execute format('revoke all on function %s from public', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end $$;

-- --------------------------------------------------------------------------
-- 15. ROW LEVEL SECURITY + LEAST-PRIVILEGE GRANTS
-- --------------------------------------------------------------------------

-- Start by removing broad API privileges.
revoke all on all tables in schema public from anon, authenticated;

-- Enable RLS on every application-facing public table.
do $$
declare t text;
begin
  foreach t in array array[
    'profiles','organizations','organization_memberships','organization_data_grants',
    'ingestion_batches','data_quality_flags','farms','farm_members','plots','crop_seasons',
    'production_batches','devices','sync_batches','activities','seeding_events',
    'fertilizer_applications','irrigation_events','pesticide_applications','fuel_usages',
    'straw_management_events','harvest_events','emission_factor_sets','emission_factors',
    'carbon_calculations','carbon_breakdowns','plant_images','cv_model_versions','cv_inferences',
    'resource_metric_snapshots','benchmark_snapshots','benchmark_snapshot_members',
    'recommendation_rules','recommendations','mrv_step_catalog','mrv_cases','mrv_case_batches',
    'mrv_case_steps','mrv_evidence','mrv_exports','mrv_export_calculations'
  ] loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

-- Profiles
grant select, update on public.profiles to authenticated;
create policy profiles_select on public.profiles for select to authenticated
  using ((select auth.uid()) is not null and private.user_can_read_profile(id));
create policy profiles_update on public.profiles for update to authenticated
  using (id = (select auth.uid()))
  with check (id = (select auth.uid()));

-- Organization and membership metadata
grant select on public.organizations, public.organization_memberships, public.organization_data_grants to authenticated;
create policy organizations_select on public.organizations for select to authenticated
  using (private.user_can_read_organization(id));
create policy memberships_select on public.organization_memberships for select to authenticated
  using (user_id = (select auth.uid()) or private.user_is_org_member(organization_id));
create policy organization_grants_select on public.organization_data_grants for select to authenticated
  using (
    private.user_is_org_member(grantee_organization_id)
    or private.user_is_org_manager(source_organization_id)
  );

-- Ingestion and quality flags are backend/admin only: no authenticated grants/policies.

-- Farms
grant select, insert, update on public.farms to authenticated;
create policy farms_select on public.farms for select to authenticated
  using (deleted_at is null and private.user_can_read_farm(id));
create policy farms_insert on public.farms for insert to authenticated
  with check (
    exists (
      select 1 from public.organization_memberships om
      where om.organization_id = cooperative_id
        and om.user_id = (select auth.uid())
        and om.role in ('farmer'::public.organization_role,'cooperative_manager'::public.organization_role)
        and (om.ended_at is null or om.ended_at > now())
    )
  );
create policy farms_update on public.farms for update to authenticated
  using (private.user_can_write_farm(id))
  with check (private.user_can_write_farm(id));

-- Farm members
grant select, insert, update, delete on public.farm_members to authenticated;
create policy farm_members_select on public.farm_members for select to authenticated
  using (private.user_can_read_farm(farm_id));
create policy farm_members_insert on public.farm_members for insert to authenticated
  with check (private.user_can_manage_farm_members(farm_id));
create policy farm_members_update on public.farm_members for update to authenticated
  using (private.user_can_manage_farm_members(farm_id))
  with check (private.user_can_manage_farm_members(farm_id));
create policy farm_members_delete on public.farm_members for delete to authenticated
  using (private.user_can_manage_farm_members(farm_id));

-- Plots
grant select, insert, update on public.plots to authenticated;
create policy plots_select on public.plots for select to authenticated
  using (deleted_at is null and private.user_can_read_farm(farm_id));
create policy plots_insert on public.plots for insert to authenticated
  with check (private.user_can_write_farm(farm_id));
create policy plots_update on public.plots for update to authenticated
  using (private.user_can_write_farm(farm_id))
  with check (private.user_can_write_farm(farm_id));

-- Crop seasons
grant select, insert, update on public.crop_seasons to authenticated;
create policy crop_seasons_select on public.crop_seasons for select to authenticated
  using (
    deleted_at is null and exists (
      select 1 from public.plots p where p.id = plot_id and private.user_can_read_farm(p.farm_id)
    )
  );
create policy crop_seasons_insert on public.crop_seasons for insert to authenticated
  with check (exists (
    select 1 from public.plots p where p.id = plot_id and private.user_can_write_farm(p.farm_id)
  ));
create policy crop_seasons_update on public.crop_seasons for update to authenticated
  using (private.user_can_write_crop(id))
  with check (private.user_can_write_crop(id));

-- Production batches
grant select, insert, update on public.production_batches to authenticated;
create policy production_batches_select on public.production_batches for select to authenticated
  using (deleted_at is null and private.user_can_read_crop(crop_season_id));
create policy production_batches_insert on public.production_batches for insert to authenticated
  with check (private.user_can_write_crop(crop_season_id));
create policy production_batches_update on public.production_batches for update to authenticated
  using (private.user_can_write_batch(id))
  with check (private.user_can_write_batch(id));

-- Devices / sync
grant select, insert, update on public.devices, public.sync_batches to authenticated;
create policy devices_select on public.devices for select to authenticated
  using (user_id = (select auth.uid()));
create policy devices_insert on public.devices for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy devices_update on public.devices for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy sync_batches_select on public.sync_batches for select to authenticated
  using (exists (select 1 from public.devices d where d.id = device_id and d.user_id = (select auth.uid())));
create policy sync_batches_insert on public.sync_batches for insert to authenticated
  with check (exists (select 1 from public.devices d where d.id = device_id and d.user_id = (select auth.uid())));
create policy sync_batches_update on public.sync_batches for update to authenticated
  using (exists (select 1 from public.devices d where d.id = device_id and d.user_id = (select auth.uid())))
  with check (exists (select 1 from public.devices d where d.id = device_id and d.user_id = (select auth.uid())));

-- Activities
grant select, insert, update on public.activities to authenticated;
create policy activities_select on public.activities for select to authenticated
  using (deleted_at is null and private.user_can_read_batch(production_batch_id));
create policy activities_insert on public.activities for insert to authenticated
  with check (
    private.user_can_write_batch(production_batch_id)
    and (recorded_by is null or recorded_by = (select auth.uid()))
  );
create policy activities_update on public.activities for update to authenticated
  using (private.user_can_write_batch(production_batch_id))
  with check (private.user_can_write_batch(production_batch_id));

-- Activity detail tables. Delete is allowed only for a user who can write the base batch.
do $$
declare t text;
begin
  foreach t in array array[
    'seeding_events','fertilizer_applications','irrigation_events','pesticide_applications',
    'fuel_usages','straw_management_events','harvest_events'
  ] loop
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_read_batch(a.production_batch_id)))',
      t || '_select', t
    );
    execute format(
      'create policy %I on public.%I for insert to authenticated with check (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_write_batch(a.production_batch_id)))',
      t || '_insert', t
    );
    execute format(
      'create policy %I on public.%I for update to authenticated using (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_write_batch(a.production_batch_id))) with check (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_write_batch(a.production_batch_id)))',
      t || '_update', t
    );
    execute format(
      'create policy %I on public.%I for delete to authenticated using (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_write_batch(a.production_batch_id)))',
      t || '_delete', t
    );
  end loop;
end $$;

-- Carbon configuration is read-only to app clients and only published sets are visible.
grant select on public.emission_factor_sets, public.emission_factors to authenticated;
create policy ef_sets_select on public.emission_factor_sets for select to authenticated
  using (status = 'published'::public.ef_status);
create policy ef_factors_select on public.emission_factors for select to authenticated
  using (exists (
    select 1 from public.emission_factor_sets s
    where s.id = factor_set_id and s.status = 'published'::public.ef_status
  ));

-- Calculations are written by trusted backend/service role; authenticated users read scoped results.
grant select on public.carbon_calculations, public.carbon_breakdowns to authenticated;
create policy carbon_calculations_select on public.carbon_calculations for select to authenticated
  using (private.user_can_read_batch(production_batch_id));
create policy carbon_breakdowns_select on public.carbon_breakdowns for select to authenticated
  using (exists (
    select 1 from public.carbon_calculations c
    where c.id = calculation_id and private.user_can_read_batch(c.production_batch_id)
  ));

-- CV metadata/results
grant select, insert, update on public.plant_images to authenticated;
grant select on public.cv_model_versions, public.cv_inferences to authenticated;
create policy plant_images_select on public.plant_images for select to authenticated
  using (deleted_at is null and private.user_can_read_crop(crop_season_id));
create policy plant_images_insert on public.plant_images for insert to authenticated
  with check (private.user_can_write_crop(crop_season_id) and uploaded_by = (select auth.uid()));
create policy plant_images_update on public.plant_images for update to authenticated
  using (private.user_can_write_crop(crop_season_id))
  with check (private.user_can_write_crop(crop_season_id));
create policy cv_model_versions_select on public.cv_model_versions for select to authenticated
  using (status in ('active'::public.model_status,'retired'::public.model_status));
create policy cv_inferences_select on public.cv_inferences for select to authenticated
  using (exists (
    select 1 from public.plant_images i
    where i.id = image_id and private.user_can_read_crop(i.crop_season_id)
  ));

-- Resource/benchmark/recommendation are generated by trusted backend and read by scoped users.
grant select on public.resource_metric_snapshots, public.benchmark_snapshots,
  public.benchmark_snapshot_members, public.recommendation_rules, public.recommendations to authenticated;
create policy resource_snapshots_select on public.resource_metric_snapshots for select to authenticated
  using (private.user_can_read_batch(production_batch_id));
create policy benchmark_snapshots_select on public.benchmark_snapshots for select to authenticated
  using (status <> 'draft'::public.benchmark_status and private.user_can_read_organization(organization_id));
create policy benchmark_members_select on public.benchmark_snapshot_members for select to authenticated
  using (exists (
    select 1 from public.benchmark_snapshots bs
    where bs.id = benchmark_snapshot_id
      and bs.status <> 'draft'::public.benchmark_status
      and private.user_can_read_organization(bs.organization_id)
  ));
create policy recommendation_rules_select on public.recommendation_rules for select to authenticated
  using (is_active);
create policy recommendations_select on public.recommendations for select to authenticated
  using (private.user_can_read_batch(production_batch_id));

-- MRV catalog and cases
grant select on public.mrv_step_catalog to authenticated;
create policy mrv_step_catalog_select on public.mrv_step_catalog for select to authenticated using (true);

grant select, insert, update on public.mrv_cases, public.mrv_case_steps, public.mrv_evidence to authenticated;
grant select, insert, delete on public.mrv_case_batches to authenticated;
grant select on public.mrv_exports, public.mrv_export_calculations to authenticated;

create policy mrv_cases_select on public.mrv_cases for select to authenticated
  using (private.user_can_read_organization(organization_id));
create policy mrv_cases_insert on public.mrv_cases for insert to authenticated
  with check (private.user_is_org_manager(organization_id) and created_by = (select auth.uid()));
create policy mrv_cases_update on public.mrv_cases for update to authenticated
  using (private.user_is_org_manager(organization_id))
  with check (private.user_is_org_manager(organization_id));

create policy mrv_case_batches_select on public.mrv_case_batches for select to authenticated
  using (private.user_can_read_mrv_case(mrv_case_id));
create policy mrv_case_batches_insert on public.mrv_case_batches for insert to authenticated
  with check (private.user_can_manage_mrv_case(mrv_case_id));
create policy mrv_case_batches_delete on public.mrv_case_batches for delete to authenticated
  using (private.user_can_manage_mrv_case(mrv_case_id));

create policy mrv_case_steps_select on public.mrv_case_steps for select to authenticated
  using (private.user_can_read_mrv_case(mrv_case_id));
create policy mrv_case_steps_insert on public.mrv_case_steps for insert to authenticated
  with check (private.user_can_manage_mrv_case(mrv_case_id));
create policy mrv_case_steps_update on public.mrv_case_steps for update to authenticated
  using (private.user_can_manage_mrv_case(mrv_case_id))
  with check (private.user_can_manage_mrv_case(mrv_case_id));

create policy mrv_evidence_select on public.mrv_evidence for select to authenticated
  using (private.user_can_read_mrv_case(mrv_case_id));
create policy mrv_evidence_insert on public.mrv_evidence for insert to authenticated
  with check (private.user_can_manage_mrv_case(mrv_case_id) and uploaded_by = (select auth.uid()));
create policy mrv_evidence_update on public.mrv_evidence for update to authenticated
  using (private.user_can_manage_mrv_case(mrv_case_id))
  with check (private.user_can_manage_mrv_case(mrv_case_id));

create policy mrv_exports_select on public.mrv_exports for select to authenticated
  using (private.user_can_read_mrv_case(mrv_case_id));
create policy mrv_export_calcs_select on public.mrv_export_calculations for select to authenticated
  using (exists (
    select 1 from public.mrv_exports e
    where e.id = mrv_export_id and private.user_can_read_mrv_case(e.mrv_case_id)
  ));

-- --------------------------------------------------------------------------
-- 16. SAFE VIEWS — MODULE 04 + 06 + 07
-- --------------------------------------------------------------------------

create or replace view public.v_farm_plot_crop_tree
with (security_invoker = true)
as
select
  o.id as cooperative_id,
  o.name as cooperative_name,
  f.id as farm_id,
  f.farm_code,
  f.farm_name,
  p.id as plot_id,
  p.plot_code,
  p.name as plot_name,
  p.area_ha,
  cs.id as crop_season_id,
  cs.season_code,
  cs.variety_name,
  cs.status as crop_status,
  pb.id as production_batch_id,
  pb.batch_code,
  pb.status as batch_status
from public.organizations o
join public.farms f on f.cooperative_id = o.id and f.deleted_at is null
join public.plots p on p.farm_id = f.id and p.deleted_at is null
join public.crop_seasons cs on cs.plot_id = p.id and cs.deleted_at is null
join public.production_batches pb on pb.crop_season_id = cs.id and pb.deleted_at is null;

-- Live metrics deliberately return NULL for ratios when required source data is incomplete.
create or replace view public.v_batch_resource_efficiency_live
with (security_invoker = true)
as
with batch_activity as (
  select pb.id as production_batch_id,
    coalesce(sum(h.yield_kg),0)::numeric(20,6) as yield_kg,
    sum(i.water_volume_m3)::numeric(20,6) as water_m3,
    coalesce(sum(fa.amount_kg),0)::numeric(20,6) as fertilizer_kg,
    bool_and(case when a.activity_type = 'irrigation' then i.water_volume_m3 is not null else true end) as water_data_complete,
    bool_and(case
      when a.activity_type = 'seeding' then se.cost_vnd is not null
      when a.activity_type = 'fertilizer' then fa.total_cost_vnd is not null
      when a.activity_type = 'irrigation' then i.total_cost_vnd is not null
      when a.activity_type = 'pesticide' then pa.total_cost_vnd is not null
      when a.activity_type = 'fuel' then fu.total_cost_vnd is not null
      when a.activity_type = 'straw_management' then sm.total_cost_vnd is not null
      when a.activity_type = 'harvest' then h.total_cost_vnd is not null
      else true end) as cost_data_complete,
    coalesce(sum(se.cost_vnd),0)
      + coalesce(sum(fa.total_cost_vnd),0)
      + coalesce(sum(i.total_cost_vnd),0)
      + coalesce(sum(pa.total_cost_vnd),0)
      + coalesce(sum(fu.total_cost_vnd),0)
      + coalesce(sum(sm.total_cost_vnd),0)
      + coalesce(sum(h.total_cost_vnd),0) as known_cost_vnd
  from public.production_batches pb
  left join public.activities a
    on a.production_batch_id = pb.id and a.deleted_at is null
  left join public.seeding_events se on se.activity_id = a.id
  left join public.fertilizer_applications fa on fa.activity_id = a.id
  left join public.irrigation_events i on i.activity_id = a.id
  left join public.pesticide_applications pa on pa.activity_id = a.id
  left join public.fuel_usages fu on fu.activity_id = a.id
  left join public.straw_management_events sm on sm.activity_id = a.id
  left join public.harvest_events h on h.activity_id = a.id
  where pb.deleted_at is null
  group by pb.id
), latest_carbon as (
  select distinct on (production_batch_id)
    production_batch_id, id as carbon_calculation_id, total_co2e_kg, co2e_per_kg,
    factor_set_id, calculated_at
  from public.carbon_calculations
  where scenario = 'actual'::public.carbon_scenario
    and status = 'succeeded'::public.calculation_status
  order by production_batch_id, calculated_at desc, created_at desc
)
select
  ba.production_batch_id,
  ba.yield_kg,
  case when ba.water_data_complete then ba.water_m3 else null end as water_m3,
  ba.fertilizer_kg,
  case when ba.cost_data_complete then ba.known_cost_vnd else null end as total_cost_vnd,
  lc.total_co2e_kg,
  case when ba.water_data_complete and ba.yield_kg > 0 then ba.water_m3 / ba.yield_kg end as water_per_kg,
  case when ba.yield_kg > 0 then ba.fertilizer_kg / ba.yield_kg end as fertilizer_per_kg,
  lc.co2e_per_kg,
  case when ba.cost_data_complete and ba.yield_kg > 0 then ba.known_cost_vnd / ba.yield_kg end as cost_per_kg,
  ba.water_data_complete,
  ba.cost_data_complete,
  lc.carbon_calculation_id,
  efs.version_code as ef_config_version,
  lc.calculated_at as carbon_calculated_at
from batch_activity ba
left join latest_carbon lc on lc.production_batch_id = ba.production_batch_id
left join public.emission_factor_sets efs on efs.id = lc.factor_set_id;

create or replace view public.v_benchmark_summary
with (security_invoker = true)
as
select
  bs.id as benchmark_snapshot_id,
  bs.organization_id,
  bs.metric_code,
  bs.status,
  bs.period_start,
  bs.period_end,
  bs.source_name,
  bs.source_reference,
  count(bm.production_batch_id)::integer as sample_size,
  avg(bm.metric_value)::numeric(24,10) as average_value,
  percentile_cont(0.5) within group (order by bm.metric_value)::numeric(24,10) as median_value,
  bs.calculated_at,
  bs.finalized_at
from public.benchmark_snapshots bs
left join public.benchmark_snapshot_members bm
  on bm.benchmark_snapshot_id = bs.id
group by bs.id;

create or replace view public.v_carbon_results
with (security_invoker = true)
as
select
  c.id as calculation_id,
  c.production_batch_id,
  c.scenario,
  c.engine_version,
  efs.version_code as ef_config_version,
  c.total_co2e_kg,
  c.yield_kg,
  c.co2e_per_kg,
  c.status,
  c.failure_reason,
  c.calculated_at
from public.carbon_calculations c
join public.emission_factor_sets efs on efs.id = c.factor_set_id;

create or replace view public.v_mrv_export_manifest
with (security_invoker = true)
as
select
  me.id as export_id,
  me.mrv_case_id,
  mc.case_code,
  me.format,
  efs.version_code as ef_config_version,
  me.scope_description,
  me.data_as_of_at,
  me.contains_sample_data,
  me.is_finalized,
  me.warning_text,
  me.storage_bucket,
  me.storage_object_path,
  me.file_sha256,
  me.generated_at,
  count(mec.carbon_calculation_id)::integer as carbon_calculation_count
from public.mrv_exports me
join public.mrv_cases mc on mc.id = me.mrv_case_id
join public.emission_factor_sets efs on efs.id = me.factor_set_id
left join public.mrv_export_calculations mec on mec.mrv_export_id = me.id
group by me.id, mc.case_code, efs.version_code;

-- Views use underlying RLS due security_invoker.
grant select on public.v_farm_plot_crop_tree,
  public.v_batch_resource_efficiency_live,
  public.v_benchmark_summary,
  public.v_carbon_results,
  public.v_mrv_export_manifest to authenticated;

-- --------------------------------------------------------------------------
-- 17. AUDIT HISTORY
-- --------------------------------------------------------------------------

create table if not exists audit.change_log (
  id bigint generated by default as identity primary key,
  schema_name text not null,
  table_name text not null,
  action text not null check (action in ('INSERT','UPDATE','DELETE')),
  record_identifier text,
  changed_at timestamptz not null default now(),
  changed_by uuid,
  old_row jsonb,
  new_row jsonb
);

revoke all on schema audit from public, anon, authenticated;
revoke all on all tables in schema audit from public, anon, authenticated;

create or replace function audit.capture_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  jnew jsonb;
  jold jsonb;
  rid text;
begin
  if tg_op = 'INSERT' then
    jnew := to_jsonb(new);
    rid := coalesce(jnew->>'id', jnew->>'activity_id', jnew->>'task_id', jnew->>'mrv_case_id');
    insert into audit.change_log(schema_name, table_name, action, record_identifier, changed_by, new_row)
    values (tg_table_schema, tg_table_name, tg_op, rid, (select auth.uid()), jnew);
    return new;
  elsif tg_op = 'UPDATE' then
    jnew := to_jsonb(new); jold := to_jsonb(old);
    rid := coalesce(jnew->>'id', jnew->>'activity_id', jnew->>'task_id', jnew->>'mrv_case_id');
    insert into audit.change_log(schema_name, table_name, action, record_identifier, changed_by, old_row, new_row)
    values (tg_table_schema, tg_table_name, tg_op, rid, (select auth.uid()), jold, jnew);
    return new;
  else
    jold := to_jsonb(old);
    rid := coalesce(jold->>'id', jold->>'activity_id', jold->>'task_id', jold->>'mrv_case_id');
    insert into audit.change_log(schema_name, table_name, action, record_identifier, changed_by, old_row)
    values (tg_table_schema, tg_table_name, tg_op, rid, (select auth.uid()), jold);
    return old;
  end if;
end;
$$;

-- Audit the business facts that are most relevant to MRV / sync / permissions.
do $$
declare t text;
begin
  foreach t in array array[
    'organizations','organization_memberships','organization_data_grants','farms','farm_members',
    'plots','crop_seasons','production_batches','activities','seeding_events','fertilizer_applications',
    'irrigation_events','pesticide_applications','fuel_usages','straw_management_events','harvest_events',
    'emission_factor_sets','emission_factors','carbon_calculations','carbon_breakdowns','plant_images',
    'cv_model_versions','cv_inferences','resource_metric_snapshots','benchmark_snapshots',
    'benchmark_snapshot_members','recommendation_rules','recommendations','mrv_cases','mrv_case_batches',
    'mrv_case_steps','mrv_evidence','mrv_exports','mrv_export_calculations'
  ] loop
    execute format('drop trigger if exists audit_change_trg on public.%I', t);
    execute format('create trigger audit_change_trg after insert or update or delete on public.%I for each row execute function audit.capture_change()', t);
  end loop;
end $$;

-- --------------------------------------------------------------------------
-- 18. SEED NON-CONTROVERSIAL CATALOG DATA
-- --------------------------------------------------------------------------

insert into public.mrv_step_catalog(step_no, name, description) values
  (1, 'Preparation', 'Chuẩn bị phạm vi, dữ liệu và kế hoạch MRV.'),
  (2, 'Registration', 'Đăng ký đối tượng/phạm vi theo quy trình MRV.'),
  (3, 'Baseline', 'Thiết lập đường cơ sở để so sánh.'),
  (4, 'Measurement', 'Đo đạc và thu thập dữ liệu hoạt động/evidence.'),
  (5, 'Reporting', 'Tổng hợp và báo cáo kết quả.'),
  (6, 'Verification', 'Thẩm định/xác minh dữ liệu và kết quả.')
on conflict (step_no) do update set
  name = excluded.name,
  description = excluded.description;

-- --------------------------------------------------------------------------
-- 19. PROJECT-MANAGEMENT SCHEMA FROM THE EXCEL TRACKER
--     This schema is intentionally separated from product operational data.
-- --------------------------------------------------------------------------

create table if not exists pm.source_documents (
  id uuid primary key default gen_random_uuid(),
  document_code text not null unique,
  title text not null,
  relative_path text not null,
  document_type text not null,
  source_as_of_date date,
  imported_at timestamptz not null default now(),
  notes text
);

create table if not exists pm.projects (
  id uuid primary key default gen_random_uuid(),
  project_code text not null unique,
  name text not null,
  competition_name text,
  sprint_length_days smallint not null default 7 check (sprint_length_days between 1 and 31),
  deadline_on date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists pm.modules (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references pm.projects(id) on delete cascade,
  module_no smallint not null check (module_no between 1 and 7),
  module_code text not null,
  name text not null,
  mvp_layer pm.mvp_layer not null,
  role_summary text not null,
  output_summary text not null,
  srs_scope text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(project_id, module_no),
  unique(project_id, module_code)
);

create table if not exists pm.requirements (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references pm.projects(id) on delete cascade,
  module_id uuid references pm.modules(id) on delete set null,
  requirement_code text not null,
  requirement_kind pm.requirement_kind not null,
  title text,
  description text,
  source_document_id uuid references pm.source_documents(id) on delete set null,
  source_locator text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(project_id, requirement_code)
);

create table if not exists pm.members (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references pm.projects(id) on delete cascade,
  member_code text not null,
  auth_user_id uuid references auth.users(id) on delete set null,
  display_name text not null,
  role_name text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(project_id, member_code),
  unique(project_id, auth_user_id)
);

create table if not exists pm.sprints (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references pm.projects(id) on delete cascade,
  sprint_no smallint not null check (sprint_no > 0),
  week_no smallint,
  name text not null,
  goal text not null,
  start_on date not null,
  end_on date not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(project_id, sprint_no),
  constraint pm_sprint_dates_chk check (end_on >= start_on)
);

create table if not exists pm.tasks (
  id uuid primary key default gen_random_uuid(),
  sprint_id uuid not null references pm.sprints(id) on delete cascade,
  task_code text not null,
  title text not null,
  source_module_label text,
  priority pm.priority_level not null,
  estimated_hours numeric(8,2) not null check (estimated_hours > 0),
  status pm.task_status not null default 'todo',
  planned_start_on date,
  planned_end_on date,
  note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(sprint_id, task_code),
  constraint pm_task_dates_chk check (planned_end_on is null or planned_start_on is null or planned_end_on >= planned_start_on)
);

create table if not exists pm.task_modules (
  task_id uuid not null references pm.tasks(id) on delete cascade,
  module_id uuid not null references pm.modules(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key(task_id, module_id)
);

create table if not exists pm.task_requirements (
  task_id uuid not null references pm.tasks(id) on delete cascade,
  requirement_id uuid not null references pm.requirements(id) on delete cascade,
  coverage_note text,
  created_at timestamptz not null default now(),
  primary key(task_id, requirement_id)
);

create table if not exists pm.task_assignees (
  task_id uuid not null references pm.tasks(id) on delete cascade,
  member_id uuid not null references pm.members(id) on delete cascade,
  share_pct numeric(6,2) not null check (share_pct > 0 and share_pct <= 100),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key(task_id, member_id)
);

create table if not exists pm.task_dependencies (
  task_id uuid not null references pm.tasks(id) on delete cascade,
  depends_on_task_id uuid not null references pm.tasks(id) on delete restrict,
  created_at timestamptz not null default now(),
  primary key(task_id, depends_on_task_id),
  constraint pm_task_dependency_no_self_chk check (task_id <> depends_on_task_id)
);

create table if not exists pm.issues (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references pm.tasks(id) on delete cascade,
  source_issue_no smallint,
  description text not null,
  issue_type pm.issue_type not null,
  severity pm.issue_severity not null,
  status pm.issue_status not null default 'open',
  discovered_on date,
  resolved_on date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint pm_issue_dates_chk check (resolved_on is null or discovered_on is null or resolved_on >= discovered_on)
);

create table if not exists pm.issue_assignees (
  issue_id uuid not null references pm.issues(id) on delete cascade,
  member_id uuid not null references pm.members(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key(issue_id, member_id)
);

create index if not exists pm_members_project_idx on pm.members(project_id);
create index if not exists pm_tasks_sprint_idx on pm.tasks(sprint_id);
create index if not exists pm_task_assignees_member_idx on pm.task_assignees(member_id);
create index if not exists pm_task_dependencies_prereq_idx on pm.task_dependencies(depends_on_task_id);
create index if not exists pm_issues_task_idx on pm.issues(task_id);
create index if not exists pm_requirements_module_idx on pm.requirements(module_id);

-- PM updated_at triggers

do $$
declare t text;
begin
  foreach t in array array['projects','modules','requirements','members','sprints','tasks','task_assignees','issues'] loop
    execute format('drop trigger if exists set_updated_at_trg on pm.%I', t);
    execute format('create trigger set_updated_at_trg before update on pm.%I for each row execute function private.set_updated_at()', t);
  end loop;
end $$;

-- PM same-project guards
create or replace function private.pm_validate_task_assignee()
returns trigger language plpgsql set search_path = '' as $$
declare tproj uuid; mproj uuid;
begin
  select s.project_id into tproj from pm.tasks t join pm.sprints s on s.id=t.sprint_id where t.id=new.task_id;
  select project_id into mproj from pm.members where id=new.member_id;
  if tproj is distinct from mproj then raise exception 'Task and assignee must belong to the same PM project'; end if;
  return new;
end $$;

drop trigger if exists pm_validate_task_assignee_trg on pm.task_assignees;
create trigger pm_validate_task_assignee_trg before insert or update on pm.task_assignees
for each row execute function private.pm_validate_task_assignee();

create or replace function private.pm_validate_task_module()
returns trigger language plpgsql set search_path = '' as $$
declare tproj uuid; mproj uuid;
begin
  select s.project_id into tproj from pm.tasks t join pm.sprints s on s.id=t.sprint_id where t.id=new.task_id;
  select project_id into mproj from pm.modules where id=new.module_id;
  if tproj is distinct from mproj then raise exception 'Task and module must belong to the same PM project'; end if;
  return new;
end $$;

drop trigger if exists pm_validate_task_module_trg on pm.task_modules;
create trigger pm_validate_task_module_trg before insert or update on pm.task_modules
for each row execute function private.pm_validate_task_module();

create or replace function private.pm_validate_dependency()
returns trigger language plpgsql set search_path = '' as $$
declare tproj uuid; dproj uuid;
begin
  select s.project_id into tproj from pm.tasks t join pm.sprints s on s.id=t.sprint_id where t.id=new.task_id;
  select s.project_id into dproj from pm.tasks t join pm.sprints s on s.id=t.sprint_id where t.id=new.depends_on_task_id;
  if tproj is distinct from dproj then raise exception 'Dependent tasks must belong to the same PM project'; end if;
  if exists (
    with recursive reach(id) as (
      select new.depends_on_task_id
      union
      select td.depends_on_task_id from pm.task_dependencies td join reach r on td.task_id=r.id
    ) select 1 from reach where id=new.task_id
  ) then raise exception 'Circular PM task dependency is not allowed'; end if;
  return new;
end $$;

drop trigger if exists pm_validate_dependency_trg on pm.task_dependencies;
create trigger pm_validate_dependency_trg before insert or update on pm.task_dependencies
for each row execute function private.pm_validate_dependency();

create or replace function private.pm_check_assignment_total()
returns trigger language plpgsql set search_path = '' as $$
declare tid uuid; n int; s numeric;
begin
  tid := coalesce(new.task_id, old.task_id);
  select count(*), coalesce(sum(share_pct),0) into n,s from pm.task_assignees where task_id=tid;
  if n > 0 and abs(s-100) > 0.001 then
    raise exception 'Task assignment shares must total 100%%; current total=%', s;
  end if;
  return null;
end $$;

drop trigger if exists pm_assignment_total_trg on pm.task_assignees;
create constraint trigger pm_assignment_total_trg
after insert or update or delete on pm.task_assignees
deferrable initially deferred
for each row execute function private.pm_check_assignment_total();

-- PM views replacing duplicated Excel sheets
create or replace view pm.v_sprint_overview as
select
  p.project_code,
  s.sprint_no,
  s.name as sprint_name,
  count(t.id)::integer as total_tasks,
  count(*) filter (where t.status='todo')::integer as todo,
  count(*) filter (where t.status='in_progress')::integer as in_progress,
  count(*) filter (where t.status='review')::integer as review,
  count(*) filter (where t.status='done')::integer as done,
  count(*) filter (where t.status='blocked')::integer as blocked,
  case when count(t.id)=0 then 0 else round(100.0*count(*) filter (where t.status='done')/count(t.id),2) end as percent_done,
  coalesce(sum(t.estimated_hours),0)::numeric(10,2) as estimated_hours
from pm.projects p
join pm.sprints s on s.project_id=p.id
left join pm.tasks t on t.sprint_id=s.id
group by p.project_code,s.id;

create or replace view pm.v_workload as
select
  p.project_code,
  s.sprint_no,
  m.member_code,
  m.display_name,
  m.role_name,
  round(sum(t.estimated_hours * ta.share_pct / 100.0),2)::numeric(10,2) as allocated_hours
from pm.task_assignees ta
join pm.tasks t on t.id=ta.task_id
join pm.sprints s on s.id=t.sprint_id
join pm.projects p on p.id=s.project_id
join pm.members m on m.id=ta.member_id
group by p.project_code,s.sprint_no,m.member_code,m.display_name,m.role_name;

create or replace view pm.v_backlog as
select
  p.project_code,
  s.sprint_no,
  t.task_code,
  t.title,
  t.source_module_label,
  (
    select string_agg(mo.name, ', ' order by mo.module_no)
    from pm.task_modules tm join pm.modules mo on mo.id=tm.module_id
    where tm.task_id=t.id
  ) as normalized_modules,
  (
    select string_agg(m.display_name, ', ' order by m.member_code)
    from pm.task_assignees ta join pm.members m on m.id=ta.member_id
    where ta.task_id=t.id
  ) as assignees,
  t.priority,
  t.estimated_hours,
  t.status,
  t.planned_start_on,
  t.planned_end_on,
  (
    select string_agg(d.task_code, ', ' order by d.task_code)
    from pm.task_dependencies td join pm.tasks d on d.id=td.depends_on_task_id
    where td.task_id=t.id
  ) as depends_on,
  t.note,
  t.created_at,
  t.updated_at
from pm.tasks t
join pm.sprints s on s.id=t.sprint_id
join pm.projects p on p.id=s.project_id;

-- PM audit triggers

do $$
declare t text;
begin
  foreach t in array array['projects','modules','requirements','members','sprints','tasks','task_modules','task_requirements','task_assignees','task_dependencies','issues','issue_assignees'] loop
    execute format('drop trigger if exists audit_change_trg on pm.%I', t);
    execute format('create trigger audit_change_trg after insert or update or delete on pm.%I for each row execute function audit.capture_change()', t);
  end loop;
end $$;

-- --------------------------------------------------------------------------
-- 20. SEED PROJECT TRACKER / MODULE TRACEABILITY
-- --------------------------------------------------------------------------

insert into pm.source_documents(document_code,title,relative_path,document_type,source_as_of_date,notes) values
  ('PRD','AgriCarbon Product Requirements Document','docs/PRD.md','PRD',date '2026-09-07','Source path supplied by the team; exact file bytes were not imported by this SQL.'),
  ('SRS','AgriCarbon Software Requirements Specification','docs/SRS.md','SRS',date '2026-09-07','28 FR IDs are seeded where their module mapping was explicitly provided; exact NFR/BC text must be copied from the authoritative SRS.'),
  ('MOD01','Module 01 — Mobile App','docs/modules/01-mobile-app.md','Module Spec',date '2026-09-07',null),
  ('MOD02','Module 02 — Carbon Engine','docs/modules/02-carbon-engine.md','Module Spec',date '2026-09-07',null),
  ('MOD03','Module 03 — Computer Vision','docs/modules/03-computer-vision.md','Module Spec',date '2026-09-07',null),
  ('MOD04','Module 04 — Resource Dashboard','docs/modules/04-resource-dashboard.md','Module Spec',date '2026-09-07',null),
  ('MOD05','Module 05 — AI Recommendation','docs/modules/05-ai-recommendation.md','Module Spec',date '2026-09-07',null),
  ('MOD06','Module 06 — Web Dashboard','docs/modules/06-web-dashboard.md','Module Spec',date '2026-09-07',null),
  ('MOD07','Module 07 — MRV Export','docs/modules/07-mrv-export.md','Module Spec',date '2026-09-07',null),
  ('SPRINT-XLSX','AgriCarbon MVP Sprint Tracker','AgriCarbon_Sprint_Tracker_CRMstyle.xlsx','Excel Tracker',date '2026-09-07','Backlog canonical for task content/dependencies; Sprint sheets canonical for dates and non-empty assignees.')
on conflict(document_code) do nothing;

insert into pm.projects(project_code,name,competition_name,sprint_length_days,deadline_on)
values('AGRICARBON','AgriCarbon — Carbon & hiệu suất tài nguyên cho lúa gạo ĐBSCL','TEC 2026 — TDMU',7,date '2026-09-20')
on conflict(project_code) do nothing;

insert into pm.modules(project_id,module_no,module_code,name,mvp_layer,role_summary,output_summary,srs_scope)
select p.id,v.module_no,v.module_code,v.name,v.mvp_layer,v.role_summary,v.output_summary,v.srs_scope
from pm.projects p
cross join (values
  (1::smallint,'M01','Mobile App','1a'::pm.mvp_layer,'Nhật ký canh tác offline-first','Activity Data, đồng bộ server, màn hình CO2e/kg','FR-1a-01..07, FR-1a-10, FR-1a-11'),
  (2::smallint,'M02','Carbon Engine','1a'::pm.mvp_layer,'Tính phát thải từ Activity Data','Tổng CO2e, CO2e/kg, breakdown, EF version','FR-1a-08, FR-1a-09, FR-1a-12'),
  (3::smallint,'M03','Computer Vision','1b'::pm.mvp_layer,'Nhận diện bệnh lá lúa','Disease label, confidence, uncertain state','FR-1b-01..04'),
  (4::smallint,'M04','Resource Dashboard','1b'::pm.mvp_layer,'Đo hiệu suất nước/phân/carbon/chi phí','water/kg, fertilizer/kg, CO2e/kg, cost/kg','FR-1b-05..06'),
  (5::smallint,'M05','AI Recommendation','1b'::pm.mvp_layer,'Rule-based recommendation có định lượng','Khuyến nghị + carbon/cost impact','FR-1b-07..09'),
  (6::smallint,'M06','Web Dashboard','1c'::pm.mvp_layer,'Quản trị nhiều hộ/HTX và phân quyền','Aggregation, hierarchy, access control','FR-1c-01..04'),
  (7::smallint,'M07','MRV Export','1c'::pm.mvp_layer,'Số hóa báo cáo MRV 6 bước','PDF/XLSX + scope/date/EF version/warnings','FR-1c-05..07')
) v(module_no,module_code,name,mvp_layer,role_summary,output_summary,srs_scope)
where p.project_code='AGRICARBON'
on conflict(project_id,module_no) do update set
  module_code=excluded.module_code,name=excluded.name,mvp_layer=excluded.mvp_layer,
  role_summary=excluded.role_summary,output_summary=excluded.output_summary,srs_scope=excluded.srs_scope;

-- Seed exactly the 28 functional-requirement IDs explicitly supplied in the module map.
-- Descriptions remain NULL rather than inventing text not present in the provided excerpt.
with fr(code,module_no) as (
  values
  ('FR-1a-01',1),('FR-1a-02',1),('FR-1a-03',1),('FR-1a-04',1),('FR-1a-05',1),('FR-1a-06',1),('FR-1a-07',1),
  ('FR-1a-08',2),('FR-1a-09',2),('FR-1a-10',1),('FR-1a-11',1),('FR-1a-12',2),
  ('FR-1b-01',3),('FR-1b-02',3),('FR-1b-03',3),('FR-1b-04',3),('FR-1b-05',4),('FR-1b-06',4),
  ('FR-1b-07',5),('FR-1b-08',5),('FR-1b-09',5),
  ('FR-1c-01',6),('FR-1c-02',6),('FR-1c-03',6),('FR-1c-04',6),('FR-1c-05',7),('FR-1c-06',7),('FR-1c-07',7)
)
insert into pm.requirements(project_id,module_id,requirement_code,requirement_kind,source_document_id,source_locator)
select p.id,m.id,fr.code,'functional'::pm.requirement_kind,sd.id,'docs/SRS.md'
from fr
join pm.projects p on p.project_code='AGRICARBON'
join pm.modules m on m.project_id=p.id and m.module_no=fr.module_no
join pm.source_documents sd on sd.document_code='SRS'
on conflict(project_id,requirement_code) do nothing;

insert into pm.members(project_id,member_code,display_name,role_name)
select p.id,v.member_code,v.display_name,v.role_name
from pm.projects p cross join (values
  ('A','Người A','App / UI Dev'),
  ('B','Người B','Backend / Carbon Engine / CV')
) v(member_code,display_name,role_name)
where p.project_code='AGRICARBON'
on conflict(project_id,member_code) do nothing;

insert into pm.sprints(project_id,sprint_no,week_no,name,goal,start_on,end_on)
select p.id,v.sprint_no,v.week_no,v.name,v.goal,v.start_on,v.end_on
from pm.projects p cross join (values
  (1::smallint,1::smallint,'Sprint 1 · Walking Skeleton — Lõi CO2e','App ghi nhật ký → Carbon Engine → CO2e/kg chạy end-to-end và tin cậy.',date '2026-09-07',date '2026-09-13'),
  (2::smallint,2::smallint,'Sprint 2 · AI/CV + Dashboard + 1c rút gọn','CV + Resource Dashboard + Recommendation hoạt động; 1c có thể mock nếu thiếu thời gian.',date '2026-09-14',date '2026-09-20')
) v(sprint_no,week_no,name,goal,start_on,end_on)
where p.project_code='AGRICARBON'
on conflict(project_id,sprint_no) do nothing;

insert into pm.tasks(sprint_id,task_code,title,source_module_label,priority,estimated_hours,status,planned_start_on,planned_end_on,note)
select s.id,v.task_code,v.title,v.module_label,v.priority,v.hours,'todo'::pm.task_status,v.start_on,v.end_on,v.note
from (values
  (1,'T1-01','Kick-off: chốt tech stack, phân công layer, tạo repo chung','Setup','high'::pm.priority_level,2.00,date '2026-09-07',date '2026-09-07',null),
  (1,'T1-02','Thiết kế DB schema nhật ký canh tác (giống, phân bón, nước tưới AWD, thuốc BVTV, rơm rạ)','1a - App','high'::pm.priority_level,4.00,date '2026-09-07',date '2026-09-07',null),
  (1,'T1-03','Xác định Emission Factor VN + công thức Activity Data × EF = CO2e','1a - Carbon Engine','high'::pm.priority_level,4.00,date '2026-09-07',date '2026-09-07','Đối chiếu QĐ 4801/QĐ-BNNMT'),
  (1,'T1-04','Build form ghi nhật ký canh tác trên app','1a - App','high'::pm.priority_level,6.00,date '2026-09-08',date '2026-09-08',null),
  (1,'T1-05','Code Carbon Engine core + unit test cơ bản','1a - Carbon Engine','high'::pm.priority_level,6.00,date '2026-09-08',date '2026-09-08',null),
  (1,'T1-06','Offline-first: lưu local + đồng bộ khi có mạng','1a - App','high'::pm.priority_level,5.00,date '2026-09-09',date '2026-09-09','Quan trọng do vùng sóng yếu ĐBSCL'),
  (1,'T1-07','Tính CO2e riêng cho AWD vs tưới ngập liên tục','1a - Carbon Engine','high'::pm.priority_level,5.00,date '2026-09-09',date '2026-09-09','Giám khảo sẽ hỏi sâu phần này'),
  (1,'T1-08','Build API client gửi activity data từ app','1a - Tích hợp','medium'::pm.priority_level,3.00,date '2026-09-10',date '2026-09-10',null),
  (1,'T1-09','Build API endpoint nhận data + trả CO2e/kg','1a - Tích hợp','medium'::pm.priority_level,3.00,date '2026-09-10',date '2026-09-10',null),
  (1,'T1-10','Tích hợp end-to-end: App → Backend → hiển thị CO2e/kg','1a - Tích hợp','high'::pm.priority_level,4.00,date '2026-09-11',date '2026-09-11',null),
  (1,'T1-11','Buffer/QA: fix bug, test độ tin cậy số liệu CO2e (5+ kịch bản)','1a - QA','medium'::pm.priority_level,5.00,date '2026-09-12',date '2026-09-12',null),
  (1,'T1-12','MILESTONE: review Sprint 1 — xác nhận Walking Skeleton chạy ổn','Milestone','high'::pm.priority_level,2.00,date '2026-09-13',date '2026-09-13','Quyết định đi tiếp 1b hay dồn lại 1a'),
  (2,'T2-01','Build UI Resource Efficiency Dashboard (nước/kg, phân/kg, carbon/kg, cost/kg)','1b - Dashboard','high'::pm.priority_level,5.00,date '2026-09-14',date '2026-09-14',null),
  (2,'T2-02','Chuẩn bị dataset CV (Sethy et al. ~5.932 ảnh) + setup pipeline training','1b - CV','high'::pm.priority_level,5.00,date '2026-09-14',date '2026-09-14','Kiểm tra license dataset'),
  (2,'T2-03','Kết nối Dashboard với dữ liệu thật từ 1a','1b - Dashboard','medium'::pm.priority_level,3.00,date '2026-09-15',date '2026-09-15',null),
  (2,'T2-04','Fine-tune model CV bằng ảnh thực địa (hoặc ảnh bổ sung nếu chưa có)','1b - CV','high'::pm.priority_level,6.00,date '2026-09-15',date '2026-09-15','Nếu chưa có ảnh HTX, dùng thêm ảnh public'),
  (2,'T2-05','Build AI Recommendation cơ bản (rule-based + impact estimate)','1b - Recommendation','high'::pm.priority_level,5.00,date '2026-09-16',date '2026-09-16','Luôn kèm ước tính impact'),
  (2,'T2-06','Tích hợp model CV vào app (chụp ảnh → predict bệnh)','1b - CV','high'::pm.priority_level,5.00,date '2026-09-16',date '2026-09-16',null),
  (2,'T2-07','Test tích hợp 1b: CV + Dashboard + Recommendation chạy chung','1b - Tích hợp','high'::pm.priority_level,4.00,date '2026-09-17',date '2026-09-17','Quyết định làm 1c thật hay chỉ mock'),
  (2,'T2-08','Chuẩn bị mock/slide Web Dashboard + mẫu Export MRV Report','1c - Mock','low'::pm.priority_level,4.00,date '2026-09-18',date '2026-09-18','Cắt/rút gọn đầu tiên nếu thiếu thời gian'),
  (2,'T2-09','Polish CV + Recommendation, chuẩn bị số liệu Before/After cho pitch','1b - Polish','medium'::pm.priority_level,4.00,date '2026-09-18',date '2026-09-18',null),
  (2,'T2-10','Buffer/QA cuối: test toàn luồng demo, viết kịch bản demo','QA','high'::pm.priority_level,5.00,date '2026-09-19',date '2026-09-19',null),
  (2,'T2-11','MILESTONE FINAL: rehearsal + đóng gói MVP nộp/demo','Milestone','high'::pm.priority_level,3.00,date '2026-09-20',date '2026-09-20','Hạn nộp 20/9')
) v(sprint_no,task_code,title,module_label,priority,hours,start_on,end_on,note)
join pm.projects p on p.project_code='AGRICARBON'
join pm.sprints s on s.project_id=p.id and s.sprint_no=v.sprint_no
on conflict(sprint_id,task_code) do nothing;

-- Module mapping for tasks. Multi-module integration tasks are represented by multiple rows.
insert into pm.task_modules(task_id,module_id)
select t.id,m.id
from (values
  ('T1-02',1),('T1-03',2),('T1-04',1),('T1-05',2),('T1-06',1),('T1-07',2),
  ('T1-08',1),('T1-09',2),('T1-10',1),('T1-10',2),('T1-11',1),('T1-11',2),('T1-12',1),('T1-12',2),
  ('T2-01',4),('T2-02',3),('T2-03',4),('T2-04',3),('T2-05',5),('T2-06',3),
  ('T2-07',3),('T2-07',4),('T2-07',5),('T2-08',6),('T2-08',7),('T2-09',3),('T2-09',5),
  ('T2-10',3),('T2-10',4),('T2-10',5),('T2-10',6),('T2-10',7),('T2-11',1),('T2-11',2),('T2-11',3),('T2-11',4),('T2-11',5),('T2-11',6),('T2-11',7)
) v(task_code,module_no)
join pm.projects p on p.project_code='AGRICARBON'
join pm.sprints s on s.project_id=p.id
join pm.tasks t on t.sprint_id=s.id and t.task_code=v.task_code
join pm.modules m on m.project_id=p.id and m.module_no=v.module_no
on conflict do nothing;

-- Sprint 1 assignees are intentionally NOT inferred because source cells are blank.
-- Sprint 2 assignments come from Sprint 2 sheet; “Cả 2” = two 50/50 junction rows.
insert into pm.task_assignees(task_id,member_id,share_pct)
select t.id,m.id,v.share_pct
from (values
 ('T2-01','A',100.00),('T2-02','B',100.00),('T2-03','A',100.00),('T2-04','B',100.00),
 ('T2-05','A',100.00),('T2-06','B',100.00),('T2-07','A',50.00),('T2-07','B',50.00),
 ('T2-08','A',100.00),('T2-09','B',100.00),('T2-10','A',50.00),('T2-10','B',50.00),
 ('T2-11','A',50.00),('T2-11','B',50.00)
) v(task_code,member_code,share_pct)
join pm.projects p on p.project_code='AGRICARBON'
join pm.sprints s on s.project_id=p.id
join pm.tasks t on t.sprint_id=s.id and t.task_code=v.task_code
join pm.members m on m.project_id=p.id and m.member_code=v.member_code
on conflict(task_id,member_id) do update set share_pct=excluded.share_pct;

insert into pm.task_dependencies(task_id,depends_on_task_id)
select t.id,d.id
from (values
 ('T1-02','T1-01'),('T1-03','T1-01'),('T1-04','T1-02'),('T1-05','T1-03'),('T1-06','T1-04'),('T1-07','T1-05'),
 ('T1-08','T1-06'),('T1-09','T1-07'),('T1-10','T1-08'),('T1-10','T1-09'),('T1-11','T1-10'),('T1-12','T1-11'),
 ('T2-01','T1-12'),('T2-02','T1-12'),('T2-03','T2-01'),('T2-04','T2-02'),('T2-05','T2-03'),('T2-06','T2-04'),
 ('T2-07','T2-05'),('T2-07','T2-06'),('T2-08','T2-07'),('T2-09','T2-07'),('T2-10','T2-08'),('T2-10','T2-09'),('T2-11','T2-10')
) v(task_code,depends_code)
join pm.projects p on p.project_code='AGRICARBON'
join pm.sprints st on st.project_id=p.id
join pm.tasks t on t.sprint_id=st.id and t.task_code=v.task_code
join pm.sprints sd on sd.project_id=p.id
join pm.tasks d on d.sprint_id=sd.id and d.task_code=v.depends_code
on conflict do nothing;

insert into pm.issues(task_id,source_issue_no,description,issue_type,severity,status,discovered_on,resolved_on)
select t.id,v.issue_no,v.description,v.issue_type,v.severity,'open'::pm.issue_status,null::date,null::date
from (values
 (1,'T1-01','Chưa chốt được HTX pilot cụ thể (Tiến Thuận / Phú Hòa) để xin dữ liệu/thử nghiệm thật','dependency'::pm.issue_type,'high'::pm.issue_severity),
 (2,'T2-04','Chưa có ảnh lá lúa thực địa để fine-tune CV, tạm thời phải dùng thêm dataset public','dependency'::pm.issue_type,'medium'::pm.issue_severity),
 (3,'T2-08','1c (Web Dashboard + Export MRV) có thể phải cắt hoàn toàn thành mock nếu Sprint 1 trễ tiến độ','risk'::pm.issue_type,'high'::pm.issue_severity),
 (4,'T1-03','Emission Factor / giá tín chỉ carbon chưa chốt chính thức — không trình bày như số liệu đã xác nhận','risk'::pm.issue_type,'medium'::pm.issue_severity)
) v(issue_no,task_code,description,issue_type,severity)
join pm.projects p on p.project_code='AGRICARBON'
join pm.sprints s on s.project_id=p.id
join pm.tasks t on t.sprint_id=s.id and t.task_code=v.task_code
where not exists (select 1 from pm.issues i where i.task_id=t.id and i.source_issue_no=v.issue_no);

-- "Cả nhóm" in issues 1 and 3 => both members. Blank owners remain unassigned.
insert into pm.issue_assignees(issue_id,member_id)
select i.id,m.id
from pm.projects p
join pm.sprints s on s.project_id=p.id
join pm.tasks t on t.sprint_id=s.id
join pm.issues i on i.task_id=t.id and i.source_issue_no in (1,3)
join pm.members m on m.project_id=p.id and m.member_code in ('A','B')
where p.project_code='AGRICARBON'
on conflict do nothing;

-- --------------------------------------------------------------------------
-- 21. PM ACCEPTANCE VIEW + VALIDATION VIEW
-- --------------------------------------------------------------------------

create or replace view pm.v_acceptance_checks as
select 'task_count' as check_name, count(*)::numeric as actual_value, 23::numeric as expected_value,
       (count(*)=23) as passed from pm.tasks
union all
select 'sprint_1_task_count', count(*)::numeric, 12::numeric, (count(*)=12)
from pm.tasks t join pm.sprints s on s.id=t.sprint_id where s.sprint_no=1
union all
select 'sprint_2_task_count', count(*)::numeric, 11::numeric, (count(*)=11)
from pm.tasks t join pm.sprints s on s.id=t.sprint_id where s.sprint_no=2
union all
select 'sprint_1_hours', coalesce(sum(t.estimated_hours),0), 49::numeric, (coalesce(sum(t.estimated_hours),0)=49)
from pm.tasks t join pm.sprints s on s.id=t.sprint_id where s.sprint_no=1
union all
select 'sprint_2_hours', coalesce(sum(t.estimated_hours),0), 49::numeric, (coalesce(sum(t.estimated_hours),0)=49)
from pm.tasks t join pm.sprints s on s.id=t.sprint_id where s.sprint_no=2
union all
select 'dependency_edges', count(*)::numeric, 25::numeric, (count(*)=25) from pm.task_dependencies
union all
select 'issues', count(*)::numeric, 4::numeric, (count(*)=4) from pm.issues
union all
select 'functional_requirement_ids', count(*)::numeric, 28::numeric, (count(*)=28)
from pm.requirements where requirement_kind='functional'::pm.requirement_kind;

-- No API grants on pm/audit schemas by default. They are intentionally not exposed.
revoke all on schema pm from public, anon, authenticated;
revoke all on all tables in schema pm from public, anon, authenticated;

-- --------------------------------------------------------------------------
-- 22. OPTIONAL STORAGE BUCKETS / POLICIES
-- --------------------------------------------------------------------------
-- Supabase Storage object bytes must be manipulated through the Storage API.
-- The SQL below only creates private bucket metadata and RLS rules for the API.
-- Path conventions:
--   plant-images: <farm_uuid>/<crop_season_uuid>/<file>
--   mrv-evidence: <organization_uuid>/<mrv_case_uuid>/<file>
--   mrv-exports : <organization_uuid>/<mrv_case_uuid>/<file>

-- Create these PRIVATE buckets from Dashboard > Storage (or Storage API) before uploads:
--   plant-images  : image/jpeg,image/png ; suggested 10 MB/object
--   mrv-evidence  : private ; suggested 50 MB/object
--   mrv-exports   : application/pdf and XLSX ; suggested 50 MB/object
-- We intentionally do not INSERT directly into storage.buckets here; object/bucket
-- operations should go through Supabase Storage management/API.

-- Storage RLS policies use first path folder as farm/org UUID.
drop policy if exists plant_images_storage_select on storage.objects;
create policy plant_images_storage_select on storage.objects for select to authenticated
using (
  bucket_id='plant-images'
  and private.user_can_read_farm(private.try_uuid((storage.foldername(name))[1]))
);

drop policy if exists plant_images_storage_insert on storage.objects;
create policy plant_images_storage_insert on storage.objects for insert to authenticated
with check (
  bucket_id='plant-images'
  and storage.extension(name) in ('jpg','jpeg','png')
  and private.user_can_write_farm(private.try_uuid((storage.foldername(name))[1]))
);

drop policy if exists plant_images_storage_update on storage.objects;
create policy plant_images_storage_update on storage.objects for update to authenticated
using (
  bucket_id='plant-images'
  and private.user_can_write_farm(private.try_uuid((storage.foldername(name))[1]))
)
with check (
  bucket_id='plant-images'
  and private.user_can_write_farm(private.try_uuid((storage.foldername(name))[1]))
);

drop policy if exists plant_images_storage_delete on storage.objects;
create policy plant_images_storage_delete on storage.objects for delete to authenticated
using (
  bucket_id='plant-images'
  and private.user_can_write_farm(private.try_uuid((storage.foldername(name))[1]))
);

-- MRV evidence/exports: read by any authorized data reader, write by cooperative manager.
drop policy if exists mrv_files_storage_select on storage.objects;
create policy mrv_files_storage_select on storage.objects for select to authenticated
using (
  bucket_id in ('mrv-evidence','mrv-exports')
  and private.user_can_read_organization(private.try_uuid((storage.foldername(name))[1]))
);

drop policy if exists mrv_files_storage_insert on storage.objects;
create policy mrv_files_storage_insert on storage.objects for insert to authenticated
with check (
  bucket_id in ('mrv-evidence','mrv-exports')
  and private.user_is_org_manager(private.try_uuid((storage.foldername(name))[1]))
);

drop policy if exists mrv_files_storage_update on storage.objects;
create policy mrv_files_storage_update on storage.objects for update to authenticated
using (
  bucket_id in ('mrv-evidence','mrv-exports')
  and private.user_is_org_manager(private.try_uuid((storage.foldername(name))[1]))
)
with check (
  bucket_id in ('mrv-evidence','mrv-exports')
  and private.user_is_org_manager(private.try_uuid((storage.foldername(name))[1]))
);

drop policy if exists mrv_files_storage_delete on storage.objects;
create policy mrv_files_storage_delete on storage.objects for delete to authenticated
using (
  bucket_id in ('mrv-evidence','mrv-exports')
  and private.user_is_org_manager(private.try_uuid((storage.foldername(name))[1]))
);

commit;

-- ============================================================================
-- POST-INSTALL VALIDATION (run after COMMIT)
-- ============================================================================

-- 1) Project tracker should return 8 PASS rows.
select * from pm.v_acceptance_checks order by check_name;

-- 2) Product database intentionally starts without fabricated farm/EF/model data.
select
  (select count(*) from public.emission_factor_sets) as emission_factor_sets,
  (select count(*) from public.emission_factors) as emission_factors,
  (select count(*) from public.cv_model_versions) as cv_model_versions,
  (select count(*) from public.farms) as farms;

-- 3) Expected MRV catalog = exactly 6 rows.
select * from public.mrv_step_catalog order by step_no;

-- 4) Confirm public tables have RLS enabled.
select schemaname, tablename, rowsecurity
from pg_tables
where schemaname='public'
order by tablename;

-- 5) Confirm key views exist.
select table_schema, table_name
from information_schema.views
where (table_schema='public' and table_name like 'v_%')
   or table_schema='pm'
order by table_schema, table_name;

-- ============================================================================
-- NOTES FOR THE TEAM
-- ============================================================================
-- A. Do not add fake EF values just to make Carbon Engine return a number.
--    Import/publish an authoritative factor set, then calculate.
-- B. Exact text for the 8 NFRs and 6 business constraints was not available in
--    the supplied excerpt. The pm.requirements table supports them; paste their
--    authoritative codes/text from docs/SRS.md instead of inventing them.
-- C. The PM schema is intentionally not exposed through the Data API. It exists
--    for project traceability and defense/audit, not for farmer-facing screens.
-- D. Dashboard/Workload/MRV summaries are views or immutable snapshots; they are
--    not duplicate mutable source tables.
-- E. Hard deletion is avoided for core offline entities; use deleted_at tombstones.
-- ============================================================================

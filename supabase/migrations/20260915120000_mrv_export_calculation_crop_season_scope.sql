-- P1 / M3 follow-up: let an MRV export link a crop-season-scoped Carbon calculation.
--
-- WHAT WAS WRONG
--   `private.validate_mrv_export_calculation` (baseline, trigger on
--   `mrv_export_calculations`) still enforced the pre-2026-09-08 model, in which a
--   calculation belonged to a production batch:
--       carbon_calculations.production_batch_id must be one of mrv_case_batches
--   `20260908000002_crop_season_carbon_scope` moved Carbon to crop-season scope and
--   made `production_batch_id` optional; the backend writes it as NULL
--   (`mapping.calculation_row`). So the very first MRV export backed by a real,
--   persisted canonical calculation would fail in this trigger ("MRV export
--   calculation batch must be inside the MRV case scope") and the export request
--   would error. It stayed dormant only because no calculation has succeeded yet
--   (GWP pending); hosted verification of M3 surfaced it.
--
-- WHAT THIS DOES
--   Same trigger, same factor-set rule. The scope rule now follows the Carbon scope
--   the schema actually uses: the calculation's crop season must have at least one
--   production batch linked to the MRV case — exactly how the MRV export service
--   derives the seasons it includes. Nothing is loosened beyond that: a
--   calculation for a season outside the case is still rejected.
--
-- HISTORICAL DATA
--   Hosted had 0 rows in `mrv_export_calculations` and 0 rows in
--   `carbon_calculations` when this was written, so no existing row is
--   re-interpreted and no backfill is needed.

create or replace function private.validate_mrv_export_calculation()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_case uuid;
  v_factor_set uuid;
  v_calc_factor_set uuid;
  v_calc_season uuid;
begin
  select mrv_case_id, factor_set_id into v_case, v_factor_set
  from public.mrv_exports where id = new.mrv_export_id;
  select factor_set_id, crop_season_id into v_calc_factor_set, v_calc_season
  from public.carbon_calculations where id = new.carbon_calculation_id;

  if v_factor_set is distinct from v_calc_factor_set then
    raise exception 'All calculations in an MRV export must use the export factor-set version';
  end if;
  if not exists (
    select 1
    from public.mrv_case_batches mcb
    join public.production_batches pb on pb.id = mcb.production_batch_id
    where mcb.mrv_case_id = v_case
      and pb.crop_season_id = v_calc_season
  ) then
    raise exception 'MRV export calculation crop season must be inside the MRV case scope';
  end if;
  return new;
end;
$$;

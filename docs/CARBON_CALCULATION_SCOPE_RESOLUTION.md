# Carbon Calculation Scope Resolution

## 1. Problem

`carbon_calculations.production_batch_id` was `NOT NULL`, which implied a calculation was a Batch calculation. This conflicts with IPCC rice CH4 Eq. 5.1 implemented by the engine: `CH4 = EFi × cultivation_days × area_ha`. `cultivation_days` belongs to `crop_seasons`; `area_ha` belongs to the season's Plot. A season may have multiple harvest batches. Repeating the formula for every batch repeats the entire season's cultivation emissions.

Scenario: one 1 ha, 100-day Crop Season has Batch A = 2,000 kg and Batch B = 3,000 kg. Each batch-level calculation would use 1 ha × 100 days, so the summed CH4 is 2× the actual season CH4. No allocation is implied or implemented.

## 2. Evidence from PRD/SRS

| Source | Evidence | Previous assumption |
|---|---|---|
| PRD §4.1 | CO2e total/per-kg was described "cho lô"; §4.3 used `Farm → Plot → Crop → Batch → Activity → Carbon`. | Carbon appeared downstream of Batch. |
| SRS §3.0–3.1 | The prior tree nested Carbon under Activity under Batch, and called Batch the per-kg denominator. | Mixed Crop/Batch scope. |
| SRS §4.2 | `crop_id` was the API field although it looked up `crop_seasons`. | Correct lookup, ambiguous name. |
| Carbon Engine | `RiceMethaneCalculator` uses `cultivation_days * data.area_ha`; `CropActivityData` is built from crop season + plot. | Crop Season is already the real methodology scope. |
| Base schema | `carbon_calculations.production_batch_id uuid not null`, unique by batch. | Batch is persistence scope. |
| `20260908000000_carbon_methodology_alignment.sql` | Adds methodology evidence but leaves the base batch FK/unique rule unchanged. | Does not resolve scope. |
| `20260908000001_carbon_calculation_scope_audit.sql` | Adds nullable `crop_season_id`, then preserves batch as "khoá phạm vi chính" and rejects multiple batches in application code. | A temporary guard, not a correct domain model. |

The PRD and SRS support the corrected model: they require an auditable cultivation result and CO2e/kg at farm/season level, while Batch is explicitly a future traceability concern. Their old hierarchy and wording were inconsistent with the methodology and are now corrected.

## 3. Recommended domain model

```text
Farm → Plot → Crop Season
                 ├── Activities
                 ├── Harvest Events
                 ├── Production Batches
                 └── Carbon Calculations
```

One Carbon Calculation has one required `crop_season_id`. Its CH4, N2O, fuel, and straw-burning breakdown is the cultivation total for that season. `production_batch_id` is nullable and, when populated, can only be a traceability reference to a batch in the same season. There is no current use case for a calculation-to-many-batches junction, so none is introduced.

`CO2e/kg = total cultivation CO2e / sum(valid harvest_events.yield_kg for the Crop Season)`. The repository loads event rows separately and aggregates in Python, avoiding multiplicative SQL joins. A batch quantity must not be used as the denominator or allocation key.

## 4. Database changes

`20260908000002_crop_season_carbon_scope.sql`:

- deterministically backfills `crop_season_id` from existing batch links and fails if any row cannot be traced;
- sets `crop_season_id NOT NULL` and makes `production_batch_id` nullable without deleting data;
- adds a season-scoped partial unique index for new whole-season rows (`production_batch_id IS NULL`), without deleting historical batch-scoped duplicates;
- adds a trigger that rejects a linked batch from another season;
- adds crop-season read policies alongside existing batch policies, preserving RLS access for rows with a null batch FK.

It does not reset the database, drop records, weaken authorization, or allocate emissions.

## 5. Engine changes

`CropActivityData` now names its scope `crop_season_id`. It contains crop-season data, plot area, cultivation period, water regime, pre-season conditions, straw/fertilizer/fuel activities, and aggregated harvest yield. The Carbon Engine has no dependency on `production_batch_id`.

## 6. API changes

`POST /v1/carbon/calculate` now requires:

```json
{ "crop_season_id": "...", "water_regime_scenario": "awd" }
```

`GET /v1/crop-seasons/{crop_season_id}/carbon` reads the latest successful calculation for that season. The former `crop_id` name is removed because it obscured the lookup scope.

## 7. Regression tests

`backend/tests/test_integration_supabase.py` contains:

- Test A: one Batch persists a normal season calculation.
- Test B: two Batches persist one season calculation with one CH4 breakdown.
- Test C: adding a Batch does not increase cultivation CH4.
- Test D: 2,000 kg + 3,000 kg harvest events produce season yield 5,000 kg and the correct CO2e/kg denominator.
- Test E: two Batches leave `production_batch_id` null; no batch allocation occurs.

## 8. Migration plan

1. Review `20260908000002_crop_season_carbon_scope.sql` and run it through the normal non-production migration path.
2. Run `scripts/validate_supabase_schema.py` against the target database.
3. Deploy the API/engine change only after the migration is present.
4. Do not run batch-specific carbon reports until a separately approved allocation methodology, data requirements, and tests exist.

## 9. Remaining risks

- Activities are physically keyed by Batch in the current schema. The repository correctly aggregates all active batch activities for a Crop Season, but an eventual activity-at-season model may simplify data entry.
- Existing rows that cannot be linked from batch to a crop season intentionally block migration and need manual remediation.
- GWP/MRV factor verification remains independently blocked; scope correctness does not make the result MRV-compliant.
- Batch-specific footprints require an explicit allocation methodology and cannot be inferred from batch quantity.

DOMAIN SCOPE LOCKED: YES

DB MIGRATION READY: YES

ENGINE READY: YES

SUPABASE INTEGRATION READY: NO — intentionally paused until the migration is reviewed and applied through the normal environment path.

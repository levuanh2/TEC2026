# Farmer Web online write contract — proposal

**Status:** implemented for FW-2 Part 1. The historical proposal below is retained
as design context; the implementation-status section is authoritative for the
three supported activity types. Farmer Web UI remains read-only in this phase.

## FW-2 Part 1 implementation status

> **Supersession:** references below to routes being "proposed", "not currently
> available", or requiring a future implementation are historical and do not
> apply to fertilizer, irrigation, or harvest.

The proposal is now implemented for **fertilizer**, **irrigation**, and
**harvest** through FastAPI. The Farmer Web remains read-only in this phase:
there is no React write client, form, or direct browser database write.

Implemented routes:

| Method | Route | Status |
|---|---|---|
| POST | `/v1/crop-seasons/{crop_season_id}/activities` | fertilizer, irrigation, harvest |
| PATCH | `/v1/activities/{activity_id}` | same three immutable types |
| DELETE | `/v1/activities/{activity_id}` | soft delete, same three types |

The implementation uses a backend-only psycopg transaction for the base
`activities` row and its one subtype row. For harvest, that subtype is the
canonical `harvest_events` denominator source. Caller identity and crop scope
are established first using the caller JWT through the publishable-key/RLS
read path; the transaction never trusts a browser-supplied actor, role, farm,
organization, or batch.

Migration `20260910080441_farmer_web_activity_idempotency.sql` adds nullable
`web_idempotency_key` and a partial unique index on
`(recorded_by, web_idempotency_key)`. It leaves Flutter's
`(device_id, client_event_id)` contract untouched. Same actor/key/payload
returns the original activity; a materially different retry is `409
duplicate_event`.

Initial lifecycle policy is deliberate: only `active` crop seasons with
exactly one non-closed/non-cancelled production batch accept an online write.
This prevents silently selecting an arbitrary traceability batch. Seeding,
pesticide, and straw-management remain FW-2 Part 2 work.

## Decision

The existing Flutter application writes an offline queue directly to Supabase under RLS:

```text
Flutter SQLite → SyncService → Supabase tables + RLS
```

It registers a device and uses the existing unique index `(device_id, client_event_id)` on `activities` for replay-safe mobile sync. That is appropriate for an offline mobile device, but it exposes the subtype-table schema to a browser and cannot be reused as-is by a web user without a device: `activities_device_event_pair_chk` requires both values together.

**Recommended for the online Farmer Web: option B — FastAPI write API.**

```text
Farmer Web → Supabase Auth access token → FastAPI activity service
           → transaction-capable repository → Supabase/RLS
```

This preserves one domain-level activity contract, centralizes validation and audit behavior, and prevents a browser from coupling to seven detail tables. Option C (a shared mobile/web sync-write API) is a later convergence project; it is not necessary for online-first Farmer Web MVP.

## Proposed routes

| Method | Route | Purpose | Roles (proposed) |
|---|---|---|---|
| `POST` | `/v1/crop-seasons/{crop_season_id}/activities` | Create one normalized activity and its detail record | assigned farmer |
| `PATCH` | `/v1/activities/{activity_id}` | Amend a permitted activity | its assigned farmer, subject to season policy |
| `DELETE` | `/v1/activities/{activity_id}` | Soft-delete a permitted activity | its assigned farmer, subject to season policy |

These are proposal routes, not currently available endpoints. `enterprise` and `regulator` have no write permission. A cooperative manager must not inherit write permission merely from read scope; enable it only through an explicit future policy decision.

## Canonical create request

```json
{
  "idempotency_key": "6d8d147e-69b9-4c8e-b458-0290ef8a88ba",
  "activity_type": "fertilizer",
  "occurred_at": "2026-09-10T08:00:00+07:00",
  "note": "Bón lần 2",
  "data": {
    "fertilizer_name": "Urea",
    "fertilizer_type": "urea",
    "amount_kg": 120,
    "nitrogen_percent": 46,
    "total_cost_vnd": 1800000
  }
}
```

`activity_type`, not a direct detail-table name, is the public discriminator. The API returns the normalized journal representation (`id`, `crop_season_id`, `activity_type`, `occurred_at`, `data`, `note`, `created_by`, `created_at`, `updated_at`). It must never require the browser to compose `activities` and subtype tables itself.

## Initial activity contracts

The field names below match the current database schema. The user-facing Farmer Web can use plain Vietnamese labels; it must submit these canonical units and field names.

| Activity | Required `data` | Optional `data` | Validation / metric significance | Mapping |
|---|---|---|---|---|
| `fertilizer` | `fertilizer_name`, `amount_kg` | `fertilizer_type`, `nitrogen_percent`, `phosphorus_percent`, `potassium_percent`, `total_cost_vnd` | `amount_kg > 0`; percentages 0–100; `nitrogen_percent` is required before a methodology-eligible nitrogen calculation, not invented by the API | `fertilizer_applications` |
| `irrigation` | `method` | `water_volume_m3`, `duration_minutes`, `water_level_cm`, `pump_energy_kwh`, `total_cost_vnd` | `method` must be a current `irrigation_method`; water volume is nullable so an unmeasured event remains unknown rather than becoming zero. No method is silently mapped to AWD. | `irrigation_events` |
| `harvest` | `yield_kg` | `harvested_area_ha`, `moisture_percent`, `total_cost_vnd` | `yield_kg > 0`; area > 0 when supplied; moisture 0–100. Yield is the crop-season denominator. | `harvest_events` |
| `seeding` | `seed_kg` | `variety_name`, `seeding_method`, `cost_vnd` | `seed_kg > 0`; `cost_vnd >= 0` when supplied | `seeding_events` |
| `pesticide` | `product_name`, `amount`, `unit` | `active_ingredient`, `total_cost_vnd` | non-empty name/unit; `amount > 0` | `pesticide_applications` |
| `straw_management` | `method` | `straw_mass_kg`, `total_cost_vnd` | method must be a current `straw_management_method`; mass >= 0 when supplied | `straw_management_events` |

`fuel` remains a supported internal activity type but is not a first Farmer Web entry flow. It must use the existing `fuel_usages` shape (`fuel_type`, `amount_liter`, optional `equipment_name`, `total_cost_vnd`) if added later.

## Atomicity and mapping

Each successful request writes in one transaction:

```text
activity base row + exactly one subtype row
```

For `harvest`, that subtype row is `harvest_events`; it is created atomically with the activity, so the Carbon/resource denominator cannot observe a half-created journal record. A failed subtype validation or insert rolls back the base row. Update must update the base and matching subtype together; delete sets `activities.deleted_at` rather than physically deleting evidence.

The current Supabase REST sequence is not sufficient for this guarantee. Implementation must use a transaction-capable repository path (for example a caller-authorized PostgreSQL RPC) and retain caller scope checks/RLS. A service-role transaction is acceptable only after an explicit caller-JWT scope check in the FastAPI service; it must never accept a client-supplied user ID or role as authorization.

## Idempotency

The browser sends one UUID `idempotency_key` for each logical submit and reuses it on retry. Before runtime implementation, add an **additive** nullable `activities.idempotency_key` plus a partial unique index:

```sql
unique (recorded_by, idempotency_key) where idempotency_key is not null
```

The service resolves the authenticated `recorded_by`; it does not take it from the request. A repeated key in the same authorized scope returns the original created representation (200/201 equivalent) without a second activity. This is separate from Flutter's intact `(device_id, client_event_id)` mobile idempotency contract.

## Authorization and lifecycle

| Role | Create | Update | Soft delete |
|---|---:|---:|---:|
| `farmer` | Assigned farm / crop season only | Own permitted activity | Own permitted activity |
| `cooperative_manager` | No implicit right | No implicit right | No implicit right |
| `enterprise` | No | No | No |
| `regulator` | No | No | No |

The FastAPI service resolves crop-season → plot → farm scope from the caller JWT and existing membership/RLS. It never trusts a role, farm, or organization identifier supplied by the browser. Whether a closed/finalized season permits amendment must be an explicit product policy; until then, reject with `invalid_crop_season_state`.

## Errors and read-after-write

All responses retain the frozen error envelope:

```json
{"detail":{"error":{"code":"validation_error","message":"..."}}}
```

Expected domain codes: `unauthenticated`, `not_found`, `validation_error`, `duplicate_event`, `invalid_activity_type`, and `invalid_crop_season_state`.

After a successful create/update/delete, the Farmer Journal refreshes its activity list, metrics, and completeness state. It does **not** claim a new Carbon result or trigger a Carbon calculation implicitly. Carbon remains an explicit/fail-closed command under the existing scientific-factor rules.

## Implementation gates

1. Approve the public contract and lifecycle policy.
2. Add the idempotency migration and transaction-capable write repository.
3. Add FastAPI schemas/routes, OpenAPI examples, RLS/scope tests, atomicity tests, and duplicate-submit tests.
4. Only then implement Farmer Web forms.

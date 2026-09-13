# MRV evidence package — JSON manifest v1

Module 07, part 1. This is the canonical export contract: the XLSX and PDF
exports planned for parts 2 and 3 render *from* this manifest, so the shape here
is the thing to agree on, not the eventual spreadsheet layout.

## What the package is, and is not

It is a **snapshot** of what the system holds for one MRV case at one moment:
the case, its scope, its six workflow steps, references to its evidence, the
crop-season activities, the resource metrics and carbon result produced by the
existing services, and the provenance behind them.

It is **not** a certification, a verification, an audit opinion, a
government approval, or a statement of compliance with any MRV standard. Every
package carries this disclaimer in its `disclaimer` field and, again, in the
`warning_text` column of its `mrv_exports` row:

> Gói dữ liệu MRV do hệ thống tạo từ dữ liệu hiện có. Đây KHÔNG phải chứng nhận,
> thẩm định hay xác nhận của cơ quan có thẩm quyền, và không khẳng định tuân thủ
> bất kỳ tiêu chuẩn MRV nào. Nội dung có thể chứa cảnh báo về bằng chứng hoặc hệ
> số phát thải chưa đầy đủ.

`carbon_calculations.mrv_compliant` exists in the schema and is deliberately
**not** exported. A boolean in a table is not a compliance determination, and
putting it in an artifact that leaves the system would invite it to be read as
one.

## Top-level shape

| key | meaning |
| --- | --- |
| `schema_version` | `"1.0"`. Bumped only with a documented change; consumers key off it. |
| `export_id` | UUID of this export. Never the case id — a case has many exports. |
| `generated_at` | UTC ISO-8601, `...Z`. |
| `generated_by` | `{user_id, roles}` taken from the authenticated caller. Nothing else. |
| `disclaimer` | The text above, verbatim. |
| `case` | Case snapshot: code, name, status, period, organization, timestamps. |
| `scope` | Organization plus each production batch with its farm / plot / crop season. |
| `readiness` | Counts of real state. No invented score. |
| `steps` | The six MRV steps with status, dates, notes and an evidence count. |
| `evidence` | Metadata and storage references. **No bytes.** |
| `activities` | Crop-season activities with their subtype detail and audit provenance. |
| `harvest` | Harvest events — the single yield denominator. |
| `resource_metrics` | Per crop season, straight from the resource-metric service. |
| `carbon` | Per crop season, straight from the persisted calculation. |
| `provenance` | Factor sets, their factors and sources; activity source tables; carbon scope. |
| `warnings` | Machine-readable gaps. |
| `package_integrity` | Algorithm and digest. |

## Scope

Carbon remains **crop-season** scoped. A production batch appears in the package
for traceability, because that is what `mrv_case_batches` links, but it is not
the carbon scope and `provenance.carbon_scope` says so explicitly.

## Determinism and checksum

The checksum is defined over one canonical serialization:

- keys sorted at every level
- separators `(',', ':')` — no insignificant whitespace
- UTF-8, non-ASCII kept as itself (`ensure_ascii=False`)
- timestamps normalized to UTC `...Z`; dates stay dates
- quantities from Postgres `numeric` columns exported as **strings**, preserving
  the source's own precision (`"5200.000"`, not `5200.0`)

The process, which `package_integrity.canonical_over` names so it is
discoverable from the artifact itself:

1. build the manifest;
2. remove the `package_integrity` key — a digest cannot cover itself;
3. canonicalize the rest;
4. SHA-256 those bytes;
5. attach `package_integrity`.

A verifier repeats steps 2–4 and compares. `mrv.manifest.verify_checksum` does
exactly this, and `GET …/download` returns those same canonical bytes, so a
downloaded file hashes to its recorded `file_sha256`.

Naive timestamps are **rejected**, not assumed to be UTC: a dropped timezone
somewhere upstream would otherwise put a wrong instant into an audit artifact.

## Snapshot semantics

`mrv_exports.export_payload` stores the manifest verbatim.
`GET /v1/mrv/exports/{id}/download` re-serves that row and **never rebuilds from
live data**. Editing the case after an export does not change the export; it
changes what the *next* export will say. This is the property that makes the
artifact worth anything to an auditor.

## Warnings

Each entry is `{code, severity, message, related}`. Severity is `info` or
`warning` — never `error`: missing optional data is incompleteness, not failure.

| code | when |
| --- | --- |
| `carbon_unavailable` | no succeeded calculation for that crop season |
| `factor_provenance_unavailable` | no factor set behind the package, or its row is unreadable |
| `factor_unverified` | a factor's `verification_status` is not `verified` |
| `evidence_none` | the case has no evidence at all |
| `evidence_checksum_missing` | evidence rows without `sha256` |
| `mrv_step_incomplete` | a step is not `completed` (info) |
| `resource_metric_incomplete` | `data_completeness` reports a missing input (info) |
| `harvest_missing` | no harvest event, so per-kg metrics have no denominator |
| `scope_empty` | the case links no production batch |
| `carbon_engine_warning` | passed through from the calculation's own warnings |

Warnings are sorted by `(code, related)` so the same findings serialize
identically.

## Fail-closed vs partial

- **Case not found, or outside the caller's scope** → `404`, indistinguishable
  from each other so an export cannot enumerate other organizations' cases.
- **Case readable but data incomplete** → the package generates, with warnings.
  A missing CO2e does not block an evidence package; refusing to export would
  hide the very gap that matters.
- **Carbon service unreachable** → `carbon.status = unavailable` plus a warning,
  not a failed export.
- **Unsupported format** → `422 unsupported_export_format`.

Missing optional data is exported as `null`. **`null` is never turned into `0`.**

## Evidence boundary

The manifest **references** evidence; it never embeds bytes, and
`evidence[].storage.included_in_package` and
`provenance.evidence_binaries_included` are both `false` so no reader can
mistake a reference for an attachment.

A missing `sha256` is reported as a provenance gap and **not** computed here:
hashing would mean fetching every object from storage, turning an export into a
bulk download. Supplying checksums at upload time is the fix, and it belongs to
the evidence-upload path, not here.

Zipping binaries alongside the manifest is **part 2/3** work.

## Activities

Soft-deleted activities are **excluded** by default: a deleted activity is one
the farmer retracted, and carrying it into an evidence package would
misrepresent what was recorded. `provenance.activities.includes_deleted` states
which of the two the package is, rather than leaving a reader to guess. The flag
exists because an audit may later need retractions too.

Each activity carries `source`, `recorded_by`, and `provenance.device_id` /
`provenance.client_event_id` — the offline idempotency key — because "which
device recorded this, and when" is exactly what an MRV reviewer asks.

## Reuse

The export computes nothing of its own:

| section | source |
| --- | --- |
| scope, steps, evidence, activities | `SupabaseReadRepository`, caller-bound, RLS enforced |
| `resource_metrics` | `read_repository.metrics_for_seasons` → the same `_bulk_metric_totals` the dashboards use |
| `carbon` | `CarbonService.latest` — the same call `/v1/crop-seasons/{id}/carbon` makes |
| `provenance` | `emission_factor_sets` / `emission_factors` rows |

No formula and no domain query is duplicated, so the package cannot drift from
what the rest of the product shows.

## Storage

The snapshot lives in `mrv_exports.export_payload` (jsonb). No object storage is
involved in part 1, and the package does not claim otherwise.
`storage_object_path` still holds the canonical
`<organization_uuid>/<mrv_case_uuid>/<filename>` path — the database trigger
requires that shape and the unique constraint keeps one export per name — and it
is what fixes the download filename. **No object is written to the
`mrv-exports` bucket.**

Filenames are deterministic and sanitized to ASCII:

```
agricarbon-mrv-{case_code}-{generated_date}-{export_id[:8]}.json
```

## Schema changes

`20260913120000_mrv_json_export_manifest.sql`:

- `export_format` gains `'json'`;
- `mrv_exports.factor_set_id` becomes **nullable** — a factor set only exists
  once a calculation has run, and requiring it made an export impossible exactly
  in the "carbon unavailable" state the package most needs to describe;
- an index on `(mrv_case_id, generated_at desc)`.

`mrv_export_warning_chk` is untouched on purpose: a package that is not
finalized *must* carry `warning_text`, which is the behaviour this feature
wants. Part 1 always writes `is_finalized = false`, so the schema itself
enforces the disclaimer.

## API

```
POST /v1/mrv/cases/{mrv_case_id}/exports     body: {"format": "json"}   -> 201
GET  /v1/mrv/exports/{mrv_export_id}                                    -> metadata
GET  /v1/mrv/exports/{mrv_export_id}/download                           -> the snapshot
```

Download returns `application/json; charset=utf-8` with
`Content-Disposition: attachment`.

## Authorization

Access is decided by an RLS-bound read of the case before any privileged
connection is touched — the same pattern the activity write path uses. Writes go
through the backend's database role because `authenticated` has no INSERT grant
on `mrv_exports`; that is the existing architecture, not a shortcut, and the
download path filters by the caller's own readable case ids in SQL rather than
trusting the privileged connection to decide.

| caller | result |
| --- | --- |
| unauthenticated | 401 |
| organization member (`mrv_cases_select` → `private.user_can_read_organization`) | allowed |
| cross-organization | 404 (never 403) |
| unknown case id | 404 |

**Note for product:** this inherits the *existing* case-read rule, which admits
any organization member — including a `farmer`. That role can already read the
case, its steps, its evidence and its activities through the current endpoints,
so the package exposes no new data; it packages data the caller could already
fetch. Narrowing MRV export to managers only would be a deliberate product
decision and a policy change, not something to slip in here.

## Performance

Measured against hosted dev, demo case `DEMO-MRV-2026` (1 crop season, 7
activities, 1 evidence file, 6 steps): **~8.2 s**, **11.3 KiB** manifest, 9
warnings.

Every read is batched with `IN` — there is no per-entity request loop. The cost
is dominated by round trips to hosted Supabase, and one deliberate duplication
remains: activities are read once for the manifest and again inside
`metrics_for_seasons`. Reusing the metric service rather than recomputing its
formulas is worth one extra read; collapsing it would mean the export owning its
own copy of the metric logic, which is exactly what must not happen.

An export is not on a latency-critical path. If it becomes one, the fix is to
pass the already-fetched activities into a metrics entry point, not to inline
the formulas.

## Not in part 1

- XLSX (part 2) and PDF (part 3)
- zipping evidence binaries with the manifest
- asynchronous generation — generation is synchronous and `status` is always
  `generated`; there is no job queue because nothing yet needs one
- any notion of an approved, submitted or verified package

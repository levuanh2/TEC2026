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

A full-case evidence package is a **Management** capability. Generating one
requires `cooperative_manager` on the case's own organization — the same role
`private.user_is_org_manager` keys on, and the same authority
`mrv_cases_insert` / `mrv_cases_update` already require. Whoever may create or
change an MRV case may package it.

The role rule sits **on top of** RLS visibility, not instead of it. The case is
first read through the caller-bound client, so RLS remains the tenant boundary;
only then is the role checked. Both misses raise the same error.

| caller | generate | download |
| --- | --- | --- |
| unauthenticated | 401 | 401 |
| `cooperative_manager`, own organization | allowed | allowed |
| `cooperative_manager`, another organization | 404 | 404 |
| `farmer` in the organization | 404 | 404 |
| `enterprise_viewer` / `regulator` | 404 | 404 |
| lapsed management membership (`ended_at` in the past) | 404 | 404 |
| unknown case / export id | 404 | 404 |

**Denial and absence are the same response**, byte for byte. A farmer must not
be able to tell "no such case" from "you may not export this one"; that
distinction is itself a disclosure, and 404-for-both is this API's existing
convention (`ActivityWriteAccessError`, `CropAccessError`, `_read_or_404`).

Download is scoped to cases the caller **manages**, not merely ones they can
read, so a guessed or shared `export_id` is not a way around the generation
restriction.

### What this does not change

Farmers keep every bit of their existing own-scope access: their activities,
their seasons, their metrics, their own MRV case reads through the current
endpoints. The restriction is specifically on minting and retrieving the
**packaged full-case artifact**. A farmer can still see the MRV page's case
detail exactly as before — there is simply no export button, and the server
would refuse anyway.

### Residual: export metadata is still org-readable

`GET /v1/mrv/exports/{id}` and `GET /v1/mrv/cases/{id}/exports` predate this
feature and are governed by `mrv_exports_select` RLS
(`private.user_can_read_mrv_case`), so any organization member — a farmer
included — can still see **that** an export exists, plus its
`scope_description`, `file_sha256` and `storage_object_path`.

They expose **no package content**: `_export_view` does not select
`export_payload`, and a test pins that. So the restriction that matters holds —
a farmer cannot obtain the packaged artifact by any route.

This was left as-is deliberately: tightening `mrv_exports_select` is an RLS
policy change to a pre-existing read surface that the Management list view uses,
and it is a separate product decision from "who may package a case". Worth
revisiting in part 2 for one specific reason: if exports ever gain real objects
in the `mrv-exports` bucket, `storage_object_path` stops being an inert string
and becomes a fetch hint, and the bucket policy would need to be at least as
strict as the download route.

### Deliberately not granted

`enterprise_viewer` and `regulator` can read a case through an
`organization_data_grants` share, and they are plausibly the eventual *audience*
for an evidence package. They are still refused here, because letting a grantee
mint a persisted artifact attributed to themselves is a product decision nobody
has made. Granting it later is a one-line change to
`MrvExportService.MANAGEMENT_ROLE` plus tests — but it should be an explicit
decision, not a default.

Writes go through the backend's database role because `authenticated` has no
INSERT grant on `mrv_exports`; that is the existing architecture, not a
shortcut. The download path filters by the caller's own managed case ids in SQL
rather than trusting the privileged connection to decide.

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

## Part 2/3 renderer contract

**JSON manifest v1 is the canonical export snapshot.** The XLSX and PDF exports
are **renderers of a stored snapshot**, not independent assemblers of business
data.

A renderer:

- reads `mrv_exports.export_payload` for an existing `export_id`;
- may add presentation metadata — sheet names, column order, page headers,
  localized labels, formatting;
- may fail honestly if the snapshot's `schema_version` is one it does not
  understand.

A renderer must **not**:

- recalculate carbon or resource metrics;
- fetch newer data from any table, which would silently produce a document that
  disagrees with the snapshot it claims to render;
- drop or reinterpret `warnings`, or present an incomplete package as complete;
- change the meaning of any value in the snapshot;
- omit the disclaimer.

This is also the performance answer. Assembly is the expensive half (~8 s
against hosted Supabase); rendering a stored 11 KiB document is not. A part 2
that re-ran assembly per format would be both slower and *wrong*, because two
formats generated minutes apart could then disagree. Generate once, render many
times, and the XLSX, the PDF and the JSON all say the same thing because they
came from the same bytes.

If a renderer needs a value the manifest does not carry, the fix is to add it to
the manifest behind a `schema_version` bump — not to reach past the snapshot.

## Not in part 1

- XLSX (part 2) and PDF (part 3)
- zipping evidence binaries with the manifest
- asynchronous generation — generation is synchronous and `status` is always
  `generated`; there is no job queue because nothing yet needs one
- any notion of an approved, submitted or verified package

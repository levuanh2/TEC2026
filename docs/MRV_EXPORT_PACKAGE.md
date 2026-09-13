# MRV evidence package — JSON manifest v1

Module 07. Part 1 defined the canonical JSON snapshot; part 2 added the XLSX
renderer and part 3 the PDF evidence report, both rendering that stored snapshot.

The JSON manifest is the contract. Every other format is a *rendering* of a
stored snapshot, so the shape here is the thing to agree on, not a spreadsheet
layout.

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
exactly this, and `GET …/download` returns those same canonical bytes.

### Two digests, two questions

| column | digests | answers |
| --- | --- | --- |
| `payload_sha256` | the canonical manifest (`package_integrity.manifest_sha256`) | *which data* |
| `file_sha256` | the downloadable artifact bytes | *which file* |

They are **not** the same number even for JSON: the manifest digest deliberately
excludes its own `package_integrity` block, while the served bytes include it.
A JSON snapshot and an XLSX rendered from it share `payload_sha256` and differ
in `file_sha256` — which is exactly how "same data, different file" is told
apart from "different data".

Part 1 wrote the manifest digest into `file_sha256`; the part 2 migration moves
that value to `payload_sha256` where it belongs. Download verifies JSON against
the snapshot's own self-describing digest and XLSX against the stored object's
bytes, so pre-part-2 rows keep verifying correctly.

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

## Snapshot storage

The snapshot lives in `mrv_exports.export_payload` (jsonb) and **no object is
written for a JSON export** — the canonical manifest is the artifact, and
`storage_object_path` only fixes the download filename (the database trigger
requires the `<organization>/<case>/<file>` shape and the unique constraint keeps
one export per name).

Rendered artifacts are different: see [Artifact storage](#artifact-storage).

## Schema changes

`20260913120000_mrv_json_export_manifest.sql`:

- `export_format` gains `'json'`;
- `mrv_exports.factor_set_id` becomes **nullable** — a factor set only exists
  once a calculation has run, and requiring it made an export impossible exactly
  in the "carbon unavailable" state the package most needs to describe;
- an index on `(mrv_case_id, generated_at desc)`.

`20260913150000_mrv_xlsx_export_artifacts.sql`:

- `mrv_exports.source_snapshot_export_id` — the rendered-from lineage, with a
  constraint that a `json` row has no parent and every other format must have
  one;
- `mrv_exports.payload_sha256` — the manifest digest, separated from the
  artifact digest in `file_sha256` (see
  [Two digests](#two-digests-two-questions)); part 1's value is backfilled into it;
- `mrv_exports_select` / `mrv_export_calcs_select` tightened to
  `private.user_can_manage_mrv_case`.

`mrv_export_warning_chk` is untouched on purpose: a package that is not
finalized *must* carry `warning_text`, which is the behaviour this feature
wants. Both parts always write `is_finalized = false`, so the schema itself
enforces the disclaimer.

## API

```
POST /v1/mrv/cases/{mrv_case_id}/exports    {"format": "json"|"xlsx"|"pdf"} -> 201
POST /v1/mrv/exports/{mrv_export_id}/render {"format": "xlsx"|"pdf"}        -> 201
GET  /v1/mrv/cases/{mrv_case_id}/exports                                    -> history, newest first
GET  /v1/mrv/exports/{mrv_export_id}                                        -> metadata
GET  /v1/mrv/exports/{mrv_export_id}/download                          -> the artifact
```

Download returns the artifact with `Content-Disposition: attachment` and a
deterministic ASCII filename:

| format | media type |
| --- | --- |
| json | `application/json; charset=utf-8` |
| xlsx | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| pdf | `application/pdf` |

```
agricarbon-mrv-{case_code}-{generated_date}-{export_id[:8]}.{json|xlsx|pdf}
```

Any other format returns `422 unsupported_export_format`, as does rendering from
an export that is itself a rendering. No API response contains
`storage_bucket` or `storage_object_path`; only `file_name` is surfaced.

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

### Export metadata is management-only (tightened in part 2)

Part 1 left `mrv_exports_select` open to any organization member, on the grounds
that `export_payload` was never selected and `storage_object_path` pointed at
nothing.

Part 2 makes that path point at a **real private object**, so the same row now
describes a retrievable artifact. The policy was therefore tightened to
`private.user_can_manage_mrv_case` — metadata now matches generation and
download instead of being the one surface that did not. `mrv_export_calculations`
followed.

Belt and braces, because RLS is not the only exposure:

- `generated_by` (a user id) is returned in export metadata so the Management
  export history can show who generated each row; nothing else about the user is.
- Neither export view returns `storage_bucket` or `storage_object_path` to
  anyone — not the create/render responses (`MrvExportService._export_view`)
  and not the metadata routes `GET /v1/mrv/exports/{id}` and
  `GET /v1/mrv/cases/{id}/exports` (`SupabaseReadRepository._export_view`,
  `MrvExportResponse`). Both expose `file_name`, `file_sha256`,
  `payload_sha256` and `source_snapshot_export_id` instead. No client has a use
  for the path; the download route supplies the bytes.
- No signed URL is ever minted, so there is nothing time-limited to leak.
- Tests assert neither the create response nor the metadata views contain a
  bucket name or an object path.

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

Measured separately, because they are different costs with different fixes.

| step | hosted dev, demo case | 1000 activities + 100 evidence |
| --- | --- | --- |
| canonical snapshot assembly | ~8.2 s | — |
| XLSX render (pure function) | ~0.1–0.2 s | 1.55 s idle / 3.3 s under load |
| XLSX render peak Python memory | 0.7 MiB | 5.8 MiB |
| PDF render (pure function) | ~1 s, 5 pages, ~52 KiB | 2.2–2.4 s, 44 pages, 148 KiB |
| PDF render peak Python memory | 1.6 MiB | 14.6 MiB |
| storage write (private bucket, service role) | — | 1.41 s for 68 KiB |
| storage read for download | — | 1.68 s for 68 KiB |
| artifact size | 11.3 KiB (json) / ~18–25 KiB (xlsx) | 68 KiB |

Storage timings were measured against hosted `mrv-exports` with a synthetic
workbook; the end-to-end manager generate/download wall time needs the manager
credential and is not in this table.

Assembly dominates and is round-trip bound against hosted Supabase; every read is
batched with `IN` and there is no per-entity request loop. One deliberate
duplication remains: activities are read once for the manifest and again inside
`metrics_for_seasons`. Reusing the metric service rather than recomputing its
formulas is worth one extra read.

Rendering is cheap and scales linearly — which is the whole argument for
rendering from a stored snapshot rather than reassembling per format.

Generation is synchronous and `status` is always `generated`. There is no job
queue because nothing yet justifies one; if assembly ever needs to move
off-request, the existing status column is where that would be modelled.

## The renderer contract

**JSON manifest v1 is the canonical export snapshot.** XLSX is a **renderer of a
stored snapshot**, not an independent assembler of business data. PDF (part 3)
is bound by exactly the same rule.

A renderer:

- reads `export_payload` from an existing export row;
- may add presentation metadata — sheet names, column order, widths, localized
  labels, the rendering timestamp;
- may fail honestly on a `schema_version` it does not understand.

A renderer must **not**:

- recalculate carbon or resource metrics;
- query activities, evidence, steps or metrics again;
- fetch newer data, which would silently produce a document that disagrees with
  the snapshot it claims to render;
- drop or reinterpret `warnings`, or present an incomplete package as complete;
- change the meaning of any value in the snapshot;
- omit the disclaimer.

`mrv/workbook.py` and `mrv/report_pdf.py` each take a `dict` and return `bytes`.
Neither imports a repository or a service, which is what makes the rule
enforceable rather than aspirational.

This is also the performance answer. Assembly is the expensive half (~8 s against
hosted Supabase); rendering a stored manifest takes ~0.1 s. A renderer that re-ran assembly per format would be both slower and *wrong*, because two formats
generated minutes apart could disagree. Generate once, render many times.

If a renderer needs a value the manifest does not carry, the fix is to add it to
the manifest behind a `schema_version` bump — never to reach past the snapshot.

## XLSX workbook

Eleven sheets, always present. A section with no data gets an explicit
empty-state row rather than a silent gap, so "no evidence" and "the exporter
skipped evidence" cannot be confused.

| sheet | contents |
| --- | --- |
| Tổng quan | export metadata, case, readiness, disclaimer |
| Phạm vi | organization → farm → plot → crop season → production batch |
| Các bước MRV | the six steps, statuses verbatim |
| Bằng chứng | evidence metadata only |
| Hoạt động canh tác | activities flattened over a stable column superset |
| Thu hoạch | harvest events (the yield denominator) |
| Chỉ số tài nguyên | resource metrics with completeness |
| Carbon | per-season state plus the emission breakdown |
| Nguồn gốc hệ số | factor sets, factors, sources |
| Cảnh báo | one row per warning |
| Gói dữ liệu gốc | schema version, export id, digests, canonicalization |

### Cell semantics

- **null → empty cell.** Never `0`, never `"N/A"`, never `"null"`. A missing
  measurement and a measurement of zero are different facts. Where a human
  explanation helps it goes in its own status column, leaving the value blank.
- **Numbers are real numeric cells.** The manifest carries quantities as decimal
  strings so its checksum stays stable; the renderer parses them through
  `Decimal` so precision is preserved and the spreadsheet can sort and total.
  One measured limit: openpyxl writes every number as `"%.16g"`, so a ratio the
  manifest carries as 17-digit float text (`"0.028846153846153848"`) lands in
  the cell as `0.02884615384615385` — agreement to 16 significant digits
  (relative error ≤ 1e-15), not bit-identical. Excel displays 15 digits, so
  at a rounding boundary like this one the last *displayed* digit can differ
  from rounding the manifest value (`…539` vs `…538`). Sums, sorting and any
  practical use are unaffected; the manifest remains the full-precision
  record, and `test_numbers_keep_every_digit_excel_can_hold` pins exactly this
  behaviour so it cannot silently get worse.
- **Timestamps are datetime cells in UTC**, with the offset dropped because Excel
  has no timezone concept — every such column is labelled `(UTC)`. Converting to
  local time would silently shift dates across the ICT boundary.
- **Dates stay dates**, not midnight timestamps.
- **No formulas.** The workbook is a report, not a second calculation engine.
- Presentation only: one header style, thin borders, frozen headers, autofilter,
  computed column widths. No merged-cell layouts, no charts, no KPI tiles.

### Determinism

Same manifest in, same cell values and same row order out. Every list is sorted
on a stable key in the renderer rather than trusted to arrive ordered.

The `.xlsx` **bytes** are not claimed to be reproducible — a zip carries
timestamps and openpyxl writes its own metadata. Content is what is deterministic,
and content is what the tests assert.

## PDF evidence report

"Gói báo cáo MRV — MRV evidence report — snapshot dữ liệu và bằng chứng hỗ trợ."
A human-readable audit / field report of **one stored snapshot**. It is not a
certification, an authority report, a carbon credit certificate or an MRV
compliance certificate. The cover says so, the manifest disclaimer is repeated
verbatim, a scientific disclaimer states that no CO₂e figure has been validated
by an authority, and every page footer reads "Tài liệu hỗ trợ, không phải chứng
nhận". There are no seals, badges, scores or "certified" visuals.

### Library and font

- **ReportLab** (BSD, pure Python): tables with repeated headers, pagination,
  TrueType embedding. No browser engine and no native GTK stack (WeasyPrint
  needs one on Windows).
- **Be Vietnam Pro** (SIL Open Font License 1.1) — the family the web app
  already uses, designed for Vietnamese. Regular and SemiBold are bundled in
  `backend/mrv/fonts/` with `OFL.txt`; `fsType` permits embedding, and ReportLab
  embeds only the glyph subset each PDF uses. Hex digests use the built-in
  Courier face. The font lacks `→`, so the report never uses it.

### Layout

A4 portrait, Hallmark language: mineral neutral ground, forest-green section
numbers, hairline rules, dense tables with a light header band and no vertical
rules, no gradients and no card soup.

| # | section | contents |
| --- | --- | --- |
| cover | report identity | case code/name, status, period, organization, snapshot time and author, schema version, snapshot id, PDF id, disclaimers, warning count |
| 01 | summary & readiness | completed/total steps, remaining, evidence count, steps without evidence, carbon availability, per-season data completeness — counts only, no score |
| 02 | scope | organization › farm › plot › crop season; production batch labelled traceability-only, carbon scope stated as crop season |
| 03 | MRV steps | order, name, status as `label (code)`, completed_at, evidence count, notes |
| 04 | evidence | step, type, file name/MIME, uploaded at/by, SHA-256 or "Chưa có mã băm", reference id; states binaries are not embedded; no storage path |
| 05 | activities | per type: count, first/last date, sources. Quantities are **not summed** — a second total could disagree with the canonical resource metrics |
| 06 | harvest | date, yield_kg, harvested area, moisture |
| 07 | resource metrics | per season: value, unit, input completeness |
| 08 | carbon | succeeded: totals, per-kg, calculation id/time, scenario, engine, tier, factor set, breakdown. Otherwise: "Chưa thể tính CO₂e với bộ dữ liệu/hệ số hiện tại." plus the recorded reason |
| 09 | provenance | carbon scope, deleted-activity policy, binaries flag, factor sets and factors — or an explicit `factor_provenance_unavailable` row |
| 10 | warnings | every warning, warnings before info, severity as `label (code)`, never dropped |
| 11 | integrity | schema_version, source snapshot id, PDF id, `payload_sha256`, canonicalization, snapshot and render times in UTC ISO |
| A | appendix | every activity: time, type, recorded values, source/recorder, note |

Headers repeat on every continued table page; headings and intro notes travel
with the table they introduce (`keepWithNext`), so no heading is stranded at a
page bottom.

### Value semantics

- **null reads as words** — "Chưa đủ dữ liệu" for measurements, "Chưa có" for
  references and times — never `0`. A value column is never silently empty.
- **Numbers** use Vietnamese grouping (`5.200`, `0,02317`). Quantities keep the
  snapshot's digits with trailing zeros trimmed. **Per-kg ratios are shown to 6
  significant digits** (`0,0288462`); the report says so, and the full value
  stays in JSON/XLSX. Units: kg, ha, m³, kgCO₂e, VND.
- **Dates**: date-only values (`period_start`, `valid_from`) are shown as
  `dd/mm/yyyy` with no timezone arithmetic. Instants are shown in Vietnam time
  (UTC+7, labelled). The integrity section keeps raw UTC ISO strings. A naive
  timestamp is printed as-is, never guessed.
- **Statuses** are shown as a Vietnamese label *and* the recorded code, so
  `not_started` reads "Chưa bắt đầu (not_started)" and is never "failed".
  State never relies on colour alone.
- The activity appendix prints up to 2,000 rows. Beyond that it says how many
  rows were omitted and that they are in JSON/XLSX of the same snapshot.

### Integrity

`payload_sha256` (the manifest digest) is printed in the report. The PDF's own
SHA-256 cannot be — a file cannot contain its own digest — so it lives in
`file_sha256` on the export row and the report says where to find it. Download
re-hashes the stored bytes and fails closed on mismatch, exactly as for XLSX.

ReportLab runs with `invariant=1`, so the same manifest, export id and render
time produce byte-identical PDFs. In production the export id and render time
differ per artifact, so bytes differ while content does not.

### Failure handling

- Rendering happens in memory before anything is written: a renderer failure
  leaves no object, no row, and the snapshot valid.
- If the object uploads but the metadata insert fails, the object is deleted
  best-effort. Should that delete also fail, the orphan is still removed by the
  resumable QA/ops cleanup below, which enumerates `storage.objects` by the case
  prefix rather than trusting rows.

### Authorization and storage

Identical to XLSX: `cooperative_manager` of the case's organization for
generate, render, download and metadata; farmer, grantee roles and other
organizations get `404`; unauthenticated `401`. PDF bytes go to the private
`mrv-exports` bucket as `application/pdf` (already on the bucket's MIME
allowlist) under `<organization>/<case>/<filename>`. No URL, bucket or path is
ever returned or printed. The CDN cache window described below applies to PDF
objects too; correctness rests on the SHA check, never on cache invalidation.

## Artifact storage

XLSX and PDF bytes go to the existing private `mrv-exports` Supabase Storage bucket, the
same mechanism `cv_repo` already uses for plant images, under the
`<organization_uuid>/<mrv_case_uuid>/<filename>` path a database trigger already
enforces. The bucket is **not public**.

Retrieval is backend-controlled: the download route authorizes, fetches the
object, verifies `file_sha256`, and streams the bytes. **No signed URL is ever
generated, and no bucket or object path is returned by any API.** A client is
given the filename and nothing more.

JSON exports store no object — the canonical manifest in `export_payload` is the
artifact, and `storage_object_path` only fixes the filename.

### Failure behaviour

| situation | response |
| --- | --- |
| object missing, metadata present | `404 export_artifact_missing` |
| bytes do not match `file_sha256` | `409 export_artifact_integrity_failed` |
| render fails | the snapshot stays valid; no partial artifact is written |

**CDN cache window.** Hosted Supabase Storage sits behind a CDN that keeps
serving the previous object for roughly 20–60 s after an overwrite or delete,
even to service-role requests (measured: `CF-Cache-Status: HIT` until ~60 s).
Inside that window a deleted or tampered object can still be served *as it was*.
That never breaks integrity: the backend re-hashes whatever it receives, so it
can only ever serve the recorded bytes, or refuse. Once the CDN catches up, the
table above applies. Artifacts are written once (`upsert=false`) and never
overwritten by the application, so the window only matters for out-of-band
tampering or deletion.

None of these fall back to rebuilding from live data. A rebuild would return
something other than the snapshot the row promises, which is the one thing an
audit artifact must never do.

## Export lineage

An XLSX or PDF export is its own `mrv_exports` row with `format = 'xlsx'` or
`'pdf'` and `source_snapshot_export_id` pointing at the JSON snapshot it rendered.
XLSX and PDF of one snapshot are **siblings**: neither is rendered from the other. A
constraint enforces the shape: a `json` row has no parent, every other format
must have one, so a snapshot-of-a-snapshot cannot exist.

The XLSX row also keeps its own copy of `export_payload`. That duplication is
deliberate — an audit row must stay self-describing even if the parent is later
removed — and `payload_sha256` proves both rows rendered from byte-identical
manifests.

### Two ways to get a rendering

```
POST /v1/mrv/cases/{case_id}/exports   {"format": "xlsx"|"pdf"}
```
Assembles one canonical snapshot, then renders it. Both rows are created. There
is only ever **one** assembly path.

```
POST /v1/mrv/exports/{export_id}/render   {"format": "xlsx"|"pdf"}
```
Renders an **existing** snapshot. This is the auditable path: the artifact
demonstrably comes from one stored manifest rather than from data as it happens
to look now. Refused if the target is itself a rendering.

## QA cleanup (resumable)

Hosted smoke runs create real rows and objects. Clean them up child before
parent, because `mrv_export_snapshot_lineage_chk` forbids orphaning a rendering
(setting `source_snapshot_export_id` to null on an `xlsx` row is rejected):

1. `mrv_export_calculations` rows of the case's exports;
2. rendered rows — `format <> 'json'`;
3. snapshot rows — `format = 'json'`;
4. storage objects, enumerated from **`storage.objects`** by the
   `<organization>/<case>/` prefix — not from the rows just deleted.

Every step is a filtered delete, so re-running after a crash is safe; step 4
enumerating `storage.objects` is what makes it resumable — a run that dies after
step 3 still finds its objects. Verify with `count(*)` on both tables. Remember
the CDN window above: a deleted object can remain downloadable for up to a
minute, which is not a cleanup failure.

QA identities used for these runs are **demo/QA only**; their passwords come
from environment variables and are never written to files, logs, traces or
commits (see `AGENTS.md`).

## Not implemented


- **Zipping evidence binaries** with the manifest, workbook or report. All three
  formats reference evidence and say so explicitly; none claims to contain it. A
  later evidence package (for example a ZIP of manifest + report + binaries with a
  per-file SHA-256 index) is the natural place for that.
- A tagged, PDF/UA-conformant report. The PDF uses text labels and readable
  contrast, but is not certified accessible.
- Asynchronous generation.
- Any notion of an approved, submitted or verified package.

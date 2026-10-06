# RAG V1 Knowledge Source Policy

Status: **APPROVED (C1 policy)** — candidate corpus defined; **no source or document is approved
yet**. Applies to every document that may become an `EvidenceChunk`. Enforced in the database, not
only by operator code: Migration A ([RAG_V1_RETRIEVAL_ADR.md §9](RAG_V1_RETRIEVAL_ADR.md)) for the
approval record, license, lifecycle and RLS, migration `20261006120000` for the controlled
artifact required to approve (ST1-DB), and migration `20261007090000` binding that artifact to the
version's own `file_sha256` (ST1.1). Migration A alone still permits URL-only approval: all three
must be applied before the first real approval (Migration A and ST1 are applied to hosted; ST1.1
is not yet).

## 1. Principles

1. **Approved ≠ trusted instructions.** An approved document may be cited as *evidence*; its text
   is still **untrusted data**. It never changes system rules, permissions, retrieval filters,
   Carbon/metric values or the answer policy (prompt-injection boundary, ARCHITECTURE §14).
2. **Nothing enters retrieval without provenance and explicit human approval.** No crawling, no
   arbitrary user uploads, no "every PDF is equal".
3. **Never invent provenance.** An unknown publication date, version, URL or license stays empty
   (`null` / `unknown`); it is never guessed from a file name or the content.
4. **History is kept.** A replaced version is archived, not overwritten or deleted.

## 2. Knowledge classes and candidate corpus

| Class | Visibility | `organization_id` | `farm_id` | V1.3 |
|---|---|---|---|---|
| **Public** | `public` | must be `null` | must be `null` | in scope |
| **Tenant private** (HTX procedures, farm plans) | `tenant` | required | optional; must belong to that organization | schema + isolation tests only; **no ingestion, no upload flow** |

**Candidate corpus (candidate ≠ approved):**

| Tier | Candidate | Use |
|---|---|---|
| Core Vietnamese | official guidance on AWD (alternate wetting and drying) for rice | water-regime questions |
| Core Vietnamese | official "1 phải 5 giảm" guidance | practice questions |
| Core Vietnamese | QĐ 4801/QĐ-BNNMT (noted in the repo as **not yet obtained**) | national methodology/policy |
| Methodology | IPCC 2019 Refinement, Vol.4 Ch.5 *Cropland* (rice CH4, water regimes) | mechanism / methodology |
| Methodology | IPCC 2019 Refinement, Vol.4 Ch.11 *N2O Emissions from Managed Soils* | fertilizer / N2O |
| Secondary — only if eval queries require | IPCC 2006 Vol.4 Ch.2; IPCC AR5 WG1 Ch.8; UNFCCC decision 18/CMA.1 | generic methodology, GWP, reporting |

The publisher, version and URL of the Vietnamese documents are **not known yet** and are not
assumed. The IPCC/UNFCCC URLs already cited in `backend/config/emission_factors.yaml` are pointers to
verify, not approvals.

## 3. Trust status (sources **and** document versions)

| Status | Meaning | Retrievable |
|---|---|---|
| `review_required` | registered/ingested, awaiting a human decision (default for every new source and version; also any PDF without a text layer) | **no** |
| `approved` | an authorized approver accepted it | **yes**, only if source **and** version are approved |
| `rejected` | not acceptable (unverifiable origin, out of scope, license not allowed, unreadable) | **no** |
| `archived` | superseded or withdrawn; kept for provenance | **no** |

Unknown status is not retrievable (fail closed). At most one approved version per
`(source_id, document_id)` (DB partial unique index).

Lifecycle (DB-enforced, sources and versions): `review_required` <-> `rejected` until the first
approval; then `approved`; an approved row may only become `archived` (and only an approved row can
be archived -- an unwanted draft stays `rejected`); `archived` is final. An
approved version is never reopened: a correction is a new version through the normal review and
approval (section 7).

## 4. Approval requirements

### 4.1 Source (publisher / series) — DB-enforced when `approved`
- `approved_by` and `approved_at` set (named human);
- `review_note` non-empty: how the publisher's identity was verified;
- scope shape valid (public ⇒ no organization/farm; tenant ⇒ organization; farm ∈ organization).

### 4.2 Document version — DB-enforced when `approved`
Every item below must exist for the **real artifact**; missing metadata is never fabricated.

| Requirement | Field(s) | Enforcement |
|---|---|---|
| verifiable publisher | via approved source | FK to an approved source at retrieval |
| controlled stored copy (ST1) **and** official URL when the publisher has one | `artifact_ref` / `official_url` (`https://`) | CLI always stores `artifact_ref`; migration `20261006120000` (applied to hosted 2026-10-06) refuses approval without an opaque ASCII storage-path `artifact_ref` — `official_url` alone never suffices; migration `20261007090000` (ST1.1, **not yet applied to hosted**) requires it to be the version's own content address `knowledge-artifacts/<file_sha256>/…` |
| integrity | `file_sha256`, `normalized_sha256` | NOT NULL, hex format, immutable |
| real version | `document_version` | NOT NULL; publisher version, else `file_sha256` prefix (stated as such) |
| language | `language` | NOT NULL, ISO 639-1 |
| license basis | `license_basis` ≠ `unknown`; `license_reference` required for `open_license` / `written_permission` | CHECK |
| human approver + time | `approved_by`, `approved_at` | CHECK |
| reviewer explanation | `review_note` | human text, not a substitute for `license_basis` |

`license_basis` values: `official_publication`, `public_domain`, `open_license`,
`written_permission`, `tenant_owned`, and `unknown` (default, **cannot be approved**).
`license_reference` holds the licence name, the terms URL or the permission reference. This is
deliberately minimal — not a licensing subsystem.

Approver role (proposed): the AgriCarbon methodology/product owner. Approval is an operator action
(service role), never an API endpoint.

## 5. Original artifact provenance

- Each version records `file_sha256` plus `official_url` and/or `artifact_ref`.
- **ST1 (decided, V1.3-C): an APPROVED version needs a controlled immutable stored copy**
  (`artifact_ref` → private `knowledge-artifacts` Storage object, content-addressed by SHA-256,
  verified) **and** its `file_sha256`. `official_url` alone is not sufficient: if the publisher moves
  or changes the file, the hash shows the drift but the original cannot be re-fetched.
- The ingestion CLI always stores the artifact; the approver re-verifies it (checklist in
  [RAG_V1_INGESTION.md](RAG_V1_INGESTION.md) §5). The database refuses approval without a
  controlled `artifact_ref` (migration `20261006120000`, applied to hosted 2026-10-06) and, with
  ST1.1 (migration `20261007090000`, its own gate, before the first real approval), with one that is
  not the version's own content address. Neither checks Storage: object existence and the SHA-256
  of the stored bytes stay the CLI's and the approver's check (RAG_V1_INGESTION.md §1, guarantee C).

## 6. Metadata summary

| Level | Fields |
|---|---|
| Source | `source_id`, `title`, `owner`, `source_type`, `authority`, `visibility`, `organization_id`, `farm_id`, `status`, `approved_by`, `approved_at`, `review_note` |
| Document version | `source_id`, `document_id`, `document_version`, `title`, `language`, `official_url`, `artifact_ref`, `file_sha256`, `normalized_sha256`, `published_at` (only if stated), `imported_at`, parser/normalizer/chunker versions, `license_basis`, `license_reference`, `status`, `approved_by`, `approved_at`, `review_note` |
| Chunk | `chunk_id`, `ordinal`, `section_path`, `page_from/to`, `content`, `content_sha256`, `metadata` |

Identity: document unique by `(source_id, document_id, document_version)`; citation =
`source_id` + `document_id`/`document_version` + `chunk_id`.

## 7. Versioning

- A new file for an existing `(source_id, document_id)` is a **new version** (`review_required`); the
  approved version is untouched until the new one is approved.
- Approving the new version archives the previous approved one in the same transaction.
- Identical bytes re-ingest as a no-op (same hashes, same chunk ids).
- Withdrawing a source sets it `archived`; none of its versions are retrievable.
- Approved knowledge is **archive-only** (decision ST2, ADR §9.8): no client deletes it and there is
  no ordinary hard-delete workflow. Removal for legal/copyright reasons is a separate, deferred
  administrative purge (privileged operator, recorded reason/time/actor, identity+hash tombstone,
  content redacted, audit history kept); it is not part of V1.3.

## 8. Out of scope for V1.3

User/HTX uploads, crawling, OCR, DOCX/HTML/spreadsheets, automatic approval, and any source whose
license basis is unknown. (Storage archiving is no longer out of scope: ST1, V1.3-C.)

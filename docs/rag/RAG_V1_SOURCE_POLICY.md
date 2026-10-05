# RAG V1 Knowledge Source Policy

Status: **PROPOSED — awaiting approval** (V1.3-A). Applies to every document that may become an
`EvidenceChunk`. Related: [RAG_V1_RETRIEVAL_ADR.md](RAG_V1_RETRIEVAL_ADR.md).

## 1. Principles

1. **Approved ≠ trusted instructions.** An approved document may be cited as *evidence*; its text
   is still **untrusted data**. It can never change system rules, permissions, retrieval filters,
   Carbon/metric values or the answer policy (prompt-injection boundary, ARCHITECTURE §14).
2. **Nothing enters retrieval without provenance and an explicit approval.** No crawling, no
   arbitrary user uploads, no "every PDF is equal".
3. **Never invent provenance.** Unknown publication date, version or URL stays empty (`null`); it
   is not guessed from the file name or content.
4. **History is kept.** A replaced document version is archived, not overwritten or deleted, so
   past citations remain explainable.

## 2. Knowledge classes

| Class | Examples (conceptual) | Visibility | `organization_id` | V1.3 |
|---|---|---|---|---|
| **Public** | official agronomy guidance (e.g. MARD/extension material on AWD, "1 phải 5 giảm"), methodology references (IPCC Guidelines), policy/regulation texts, peer-reviewed technical reports | `public` | `null` | **in scope** |
| **Tenant private** | HTX operating procedures, farm-specific plans | `tenant` | required (`farm_id` optional) | **schema + isolation tests only; no ingestion, no upload flow** |

Candidate public sources already **referenced** in the repo (`backend/config/emission_factors.yaml`) —
listed as candidates, **not approved**:

- IPCC 2019 Refinement to the 2006 Guidelines, Vol.4 Ch.5 *Cropland* (rice CH4, water regimes);
- IPCC 2019 Refinement, Vol.4 Ch.11 *N2O Emissions from Managed Soils*;
- IPCC 2006 Guidelines, Vol.4 Ch.2 *Generic Methodologies*;
- IPCC AR5 WG1 Ch.8 (GWP values) and UNFCCC decision 18/CMA.1 (reporting rules).

QĐ 4801/QĐ-BNNMT is noted in the repo as **not yet obtained**; Vietnamese agronomy guidance on AWD
and 1P5G is not in the repo. Both must be supplied by the source owner (decision C1).

## 3. Trust status

| Status | Meaning | Retrievable |
|---|---|---|
| `review_required` | registered/ingested, awaiting a human decision (default for every new source and version; also any PDF without a text layer) | **no** |
| `approved` | an authorized approver accepted the source **and** this version | **yes** |
| `rejected` | not acceptable (unverifiable origin, wrong scope, license not allowed, unreadable) | **no** |
| `archived` | superseded by a newer approved version, or withdrawn | **no** (kept for provenance) |

A chunk is retrievable only when **its source and its document version are both `approved`**.
Unknown or missing status is treated as not retrievable (fail closed).

### Approval requirements (all must hold)

1. Origin verifiable: publisher/owner named by the document itself; official URL or a stored copy
   whose SHA-256 is recorded.
2. Relevance: rice cultivation, water/fertilizer/straw management, GHG methodology or applicable
   policy for AgriCarbon's scope.
3. License basis recorded (public-domain/official publication, open license, or written
   permission) in `review_note`.
4. Text layer extractable (no OCR in V1.3) and the language recorded (`vi`, `en`).
5. Approver recorded (`approved_by`, `approved_at`). Proposed approver role: the AgriCarbon
   methodology/product owner (C1 confirms who). Approval is an operator action, not an API.

## 4. Required metadata

| Field | Level | Rule |
|---|---|---|
| `source_id` | source | stable slug, citation identity (e.g. `ipcc-2019-refinement`) |
| `title`, `owner` (authority/publisher) | source | as stated by the publisher |
| `source_type` | source | `guideline \| policy \| methodology \| research \| tenant_document` (existing contract) |
| `authority` | source | `official \| peer_reviewed \| extension \| internal` |
| `visibility`, `organization_id`, `farm_id` | source | `public` ⇔ `organization_id is null` |
| `document_id`, `document_version` | document | stable slug + publisher version, or the file SHA-256 prefix when none is stated |
| `title`, `language` | document | as published; language code |
| `url` | document | `https://` only, official location; else `null` |
| `published_at` | document | only if stated by the publisher; else `null` |
| `imported_at` | document | set by the ingestion run |
| `file_sha256`, `normalized_sha256` | document | original bytes / normalized text |
| `parser_version`, `normalizer_version`, `chunker_version` | document | pipeline provenance |
| `status`, `approved_by`, `approved_at`, `review_note` | source + document | §3 |
| `chunk_id`, `ordinal`, `section_path`, `page_from/to`, `content_sha256` | chunk | ADR §4 |

## 5. Versioning

- A new file for an existing `document_id` creates a **new version** (`review_required`); it does
  not touch the approved version until approved.
- Approving the new version archives the previous approved version **in the same transaction**;
  its rows stay for provenance and old citations.
- Re-ingesting identical bytes is a no-op (same hashes, same chunk ids).
- Withdrawing a source sets the source to `archived`; all its versions stop being retrievable.

## 6. Out of scope for V1.3

User/HTX uploads, web crawling, OCR, DOCX/HTML/spreadsheets, automatic approval, and any source
whose license basis is unknown.

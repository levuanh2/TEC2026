# RAG V1.3-C — Knowledge ingestion foundation

Status: **implemented locally/CI; nothing ingested anywhere.** Hosted holds Migration A and ST1
(`20261006120000`, applied 2026-10-06) and the private `knowledge-artifacts` bucket (created
2026-10-06); ST1.1 (`20261007090000`) is not applied to hosted. No source is approved, no corpus is
ingested.
Lexical only (E1 = C): no embeddings, no vector, no LLM (D5 open, D8 closed).

```
artifact bytes ─► parser ─► normalizer ─► chunker ─► stable ids ─► KnowledgeStore
 (.md/.txt/PDF)   (versioned) (versioned)  (versioned)              (review_required only)
operator CLI: backend/scripts/ingest_knowledge.py   — never an API route, never a user upload
```

| Layer | Module |
|---|---|
| values, errors, metadata validation | `backend/knowledge/models.py` |
| parsers (format registry, sniffing) | `backend/knowledge/parsers/{__init__,markdown,text,pdf}.py` |
| content normalization | `backend/knowledge/normalize.py` |
| structure-aware chunking | `backend/knowledge/chunking.py` |
| ids (chunk id, artifact key, safe names) | `backend/knowledge/ids.py` |
| ports (`KnowledgeStore`, `ArtifactStore`) | `backend/knowledge/ports.py` |
| plan (pure, = dry run) + ingest | `backend/knowledge/ingest.py` |
| adapters (operator Postgres, private Storage) | `backend/infrastructure/knowledge_repo.py` |

`backend/knowledge` is pure (stdlib; only `parsers/pdf.py` imports the already-pinned `pypdf`);
`tests/test_knowledge_architecture.py` enforces it, and that no app module imports the pipeline.

## 1. ST1 — controlled artifact copies (decided)

**Decision:** an APPROVED real document version must have a controlled immutable artifact
(`artifact_ref`), its exact `file_sha256`, and provenance metadata. `official_url` stays useful
provenance but is **not sufficient** for approval (publishers move, change or remove files).

**Storage audit (2026-10-06).** The repository already has one safe pattern, reused unchanged:

| Existing practice | Where | Reused as |
|---|---|---|
| private buckets created via the Storage API, never SQL | baseline §22; `scripts/ci/seed_ci_db.py` | bucket `knowledge-artifacts`, created the same way |
| bucket with **no** `storage.objects` policy ⇒ every client operation denied; service role only | `mrv-exports` (migration `20260915100000`) | `knowledge-artifacts` has no policy, so no migration |
| `upload(..., {"upsert": "false"})` — never overwrite | `infrastructure/mrv_export_repo.py` | same |
| SHA-256 stored on the row and verified on read | `mrv_exports.file_sha256` | `knowledge_documents.file_sha256` |
| remove the uploaded object when the DB write fails | MRV export service | `ingest._compensate` |
| no signed or public URL anywhere | MRV docs | same (none created) |

**Identity.** Content-addressed: object key `<sha256>/<safe-name>`, `artifact_ref =
knowledge-artifacts/<sha256>/<safe-name>`. The name is a display hint only (basename, ASCII
`[A-Za-z0-9._-]`, no leading dot, ≤ 100 chars, canonical extension) — never identity, never a path
from the operator. Same SHA-256 ⇒ the existing object is reused **after its bytes are re-hashed**;
different bytes ⇒ a different address; nothing is ever overwritten (`upsert=false`); every write is
read back and verified. A stored object that no longer hashes to its address raises
`artifact_integrity` (tampering detected).

**Serialization and orphans.** Every run holds a Postgres session advisory lock on the content
address (first 64 bits of the SHA-256) from its first read to its last cleanup, so two runs over the
same bytes never overlap: a failed run cannot delete an object that a concurrent run has adopted but
not yet committed. The artifact is stored before the database transaction (the reference must
resolve when the row commits). If the transaction fails, the object is removed when this run
created it and no committed version references it; an object whose read-back verification fails is
removed by the adapter itself. If a removal fails, the error carries a note naming the orphaned
object (private, content-addressed, inert; a later run re-verifies it before any reuse).
An `unchanged` re-run re-verifies the stored artifact: missing, tampered or absent (`artifact_ref`
NULL) fails with `artifact_missing` / `artifact_integrity` and changes nothing.

**ST1-DB — REQUIRED FOLLOW-UP MIGRATION (decided 2026-10-06).** A real document version may not
become `approved` unless it has a controlled immutable `artifact_ref`, its exact original
`file_sha256`, human approval metadata and the required license provenance; `official_url` alone is
insufficient. The V1.3-C CLI already stores the artifact before the row commits, but Migration A
accepts `official_url` OR `artifact_ref` (`knowledge_documents_artifact_chk`) and its approval CHECK
does not require `artifact_ref`. The database enforcement is therefore a separate follow-up
migration, deliberately NOT part of the V1.3-C ingestion PR (ingestion code stays separate from
persistent hosted schema evolution). **No real document may be approved before it is applied.**

Implemented as migration `20261006120000_knowledge_document_artifact_approval_guard`
(+ rollback), its own PR; applied to hosted 2026-10-06 under its own explicit gate:
- one CHECK `knowledge_documents_artifact_approval_chk`: `status = 'approved'` additionally requires
  `artifact_ref` to be NOT NULL and an opaque ASCII storage path (`/`-separated segments of
  `[A-Za-z0-9][A-Za-z0-9._-]*`, ≤ 512 characters: no scheme/colon, no `//`, no `.`/`..` segment, no
  whitespace, control or non-ASCII character) —
  on top of the existing approver/time/review-note, known `license_basis`, `license_reference` and
  hash requirements (all unchanged);
- structural only: ST1 checks the *shape* of the reference; binding it to the row's own bytes is
  ST1.1 (below), and the object's existence and byte hash stay outside the database (§5);
- `review_required` / `rejected` drafts are unchanged; lifecycle, RLS, retrieval untouched;
- tests: `backend/tests/test_rag_knowledge_artifact_approval.py`.

**ST1.1 — SHA binding** (migration `20261007090000_knowledge_document_artifact_sha_binding`
(+ rollback), its own PR; applying it to hosted is a separate explicit gate). Without it a version
with `file_sha256 = <A>` could be approved pointing at `knowledge-artifacts/<B>/x.pdf` — another
file's copy. One CHECK `knowledge_documents_artifact_sha_binding_chk`: `status = 'approved'`
additionally requires `artifact_ref` to start with `knowledge-artifacts/<file_sha256>/` (exact, in
the "C" collation, NULL-safe). `file_sha256` is already 64 lowercase hex, so the comparison is
canonical with no normalisation: another SHA, a SHA prefix, extra characters before the `/`, a
missing `/`, an upper-case SHA segment, another bucket or no bucket are all refused. The rest of the
path stays ST1's grammar (not repeated). Approval-time only, like ST1: a draft may carry no artifact
or a mismatched one and can be corrected before approval (`artifact_ref` is mutable until the first
approval, `file_sha256` never is); the approval itself fails until it matches. The bucket name and
path scheme are now part of the approval contract: they are what the V1.3-C CLI writes
(`infrastructure/knowledge_repo.py`), and changing them needs a new migration. Tests:
`backend/tests/test_rag_knowledge_artifact_sha_binding.py`, plus the end-to-end ingestion →
approval case in `test_knowledge_ingest_db.py`.

**Three separate provenance guarantees — only C proves the bytes.**

| | Guarantee | Enforced by |
|---|---|---|
| A | `artifact_ref` is a controlled-looking opaque storage path (ST1 syntax) | database CHECK, every approval |
| B | `artifact_ref` is `knowledge-artifacts/<file_sha256>/…` — the row's own content address (ST1.1) | database CHECK, every approval |
| C | the object **exists** in the private bucket, a service-role download succeeds, and the downloaded bytes hash to `file_sha256` | **outside the database**: the CLI on every write and `unchanged` re-run, and the approver before approval (§5) |

A and B never call Storage: a well-formed path to an object that does not exist, or whose bytes
differ, passes both. Only C establishes that the artifact is real and is the reviewed file.

## 2. Formats and parsers

| Format | Parser version | Notes |
|---|---|---|
| `.md` | `kn-markdown-1` | ATX/setext headings, fenced code, pipe tables (alignment rows dropped), lists, quotes; YAML front matter ignored (warning) |
| `.txt` | `kn-text-1` | strict UTF-8 (BOM ok); headings = multi-level numbering, `Chương/Mục/Điều/Phần/Phụ lục`, short ALL-CAPS lines; tables marked `table_uncertain` |
| `.pdf` | `kn-pdf-1+pypdf-<version>` | text layer only. `< 20` non-space chars = page without text; fewer than half the pages with text ⇒ `no_text_layer` (scans are refused — **never OCR**); encrypted/malformed/> 2000 pages refused |

The extension selects the parser and the leading bytes must agree (a renamed DOCX/PDF/image is
refused). DOCX, HTML, spreadsheets, OCR, crawling: unsupported. Size bounds, all checked before any
upload or write: file <= 50 MiB; <= 100 000 structural blocks (parsing stops as soon as it is
exceeded, `too_many_blocks`); <= 20 000 chunks per version (`too_many_chunks`); a heading path
<= 1 000 characters (`heading_too_long`); content + heading path <= 20 000 characters per chunk --
everything the database indexes for that row (`unsplittable_text`: one "token" can be a megabyte run
without spaces). Text is NFC-normalized before structure detection, so NFC/NFD input classify
identically.
Every refusal is explicit (`refused [<code>]`, exit 1) and happens **before** any upload or write.

**PDF parsing is process-isolated** (`backend/infrastructure/pdf_isolation.py`). PDF bytes are
never parsed in the ingestion process: `plan()` refuses a PDF unless the isolated parser is
injected (`pdf_requires_isolation`), and only the worker imports `knowledge.parsers.pdf`
(architecture test).

| Aspect | Behaviour |
|---|---|
| process model | `subprocess` spawn of a fresh `python -I -B` running the worker file (no fork, no `multiprocessing`, no pickle); PDF bytes on stdin, one JSON result on stdout |
| timeout | hard wall clock `PDF_PARSE_TIMEOUT_SECONDS = 120` (constant, not a CLI option); on expiry the child is killed |
| cleanup | the child is always killed if still running and always reaped (`wait`), all three pipes closed; no temporary file is ever created; tested with repeated timeouts |
| environment | the child gets only `SYSTEMROOT`/`WINDIR`/`LANG`/`LC_ALL` — no Supabase URL/key, no database URL |
| IPC bounds | stdout read with a 96 MiB cap (the child is killed past it: `extraction_limit_exceeded`); stderr drained to EOF with only a 4 KiB rolling tail kept (a chatty child never blocks), only its last line surfaced, and logging below ERROR disabled in the child; the parser's own limits run in the child before serializing |
| result validation | exact field set, `format`/`parser_version` equal to the parent's, page/level/kind/flag ranges, block count and total text re-checked; anything else is `parse_worker_protocol` |
| POSIX (Linux CI/servers) | before importing pypdf the child caps itself with `resource`: address space 2 GiB, CPU seconds = the timeout, file size 0, 64 open files; a hit is `parse_resource_limit` |
| Windows | **no hard per-child memory cap in V1.3-C**. One is possible with a Job object through stdlib `ctypes` (`JOB_OBJECT_LIMIT_PROCESS_MEMORY`), not built in this round; the timeout, forced termination and the parser limits (50 MiB file, 2000 pages, pypdf's 75 MB per-stream cap, 20 M characters, 100 000 blocks) still apply. **Ingest unreviewed PDFs on Linux**, where the POSIX limits apply |

Outcomes: `parse_timeout`, `parse_resource_limit`, `parse_worker_crashed`, `parse_worker_protocol`,
`extraction_limit_exceeded`, and the parser's `malformed`, `encrypted`, `no_text_layer`,
`too_large`, `too_many_blocks`. Every one happens in `plan()`, before any Storage or database call.

## 3. Normalizer (`kn-normalize-1`) and chunker (`kn-chunk-1`)

Normalizer rules are listed in `knowledge/normalize.py` (NFC with diacritics kept; zero-width/soft
hyphen removed; paragraph line breaks joined, a line-final hyphen after a letter is joined and
**kept** — `mê-tan`; whitespace collapsed; PDF page headers/footers removed only when the same
text, digits ignored, sits on that page edge on ≥ max(3, 50 % of pages)). Same bytes + same
versions ⇒ same normalized text and `normalized_sha256`.

Chunker (ADR §4.3, unchanged, not tuned): heading → paragraph → list/table/code → split of an
over-long block. Target ≈ 300, hard max 450 whitespace tokens. Only a single over-long paragraph is
split with a one-sentence overlap; lists/tables split at lines; a single huge sentence/line is
cut into 450-token windows. `section_path` = `A > B > C` (indexed by the database with the content).

## 4. Identity and idempotency

`chunk_id = sha256(source_id | document_id | document_version | section_path | ordinal_in_section
| content_sha256)[:20]` (ADR §4.5). Re-running unchanged input ⇒ identical ids; a new
`document_version` ⇒ new ids. Row ids are never citation identity.

| Stored version `(source_id, document_id, document_version)` | Ingestion result |
|---|---|
| absent | artifact stored, then source (if absent) + version + chunks in ONE transaction, `review_required` |
| same bytes, pipeline versions, normalized hash, metadata, chunk set — any status | `unchanged` (no write; an archived version is never reactivated, an approved one never touched) |
| different bytes | `content_changed` — refused; ingest as a NEW `document_version` |
| different parser/normalizer/chunker version | `pipeline_changed` — refused; new `document_version` |
| only the third-party build suffix differs (`kn-pdf-1+pypdf-6.19.0` → `+pypdf-6.20.0`) **and** the normalized hash and chunk set are identical | `unchanged`, with a note; the stored provenance is kept. Only `kn-pdf-N+pypdf-<version>` qualifies; any other suffix family or any output difference stays `pipeline_changed` |
| different title/language/url/date/license, or chunk set | `metadata_changed` — refused |
| existing source with different metadata | `source_mismatch` — refused (ingestion never edits a source) |

A concurrent creation of the same version resolves to `unchanged` or a conflict. Any failure in
the transaction leaves no row (tested by breaking a chunk insert on the real stack).

## 5. Approval boundary

Ingestion creates `review_required` rows only. Neither port nor adapter has an approval
operation; the adapter only INSERTs/SELECTs and never names `status`, `approved_by`,
`approved_at` or `review_note` (architecture test). The CLI has no `--approve/--trust/--force`.

Approval remains a separate, explicit operator action (today: reviewed SQL by a named human, per
the source policy). **Approval checklist for a real document version** — every item, recorded:
1. C1 source approval: publisher verified, source metadata correct, human approver named.
2. Guarantee C (§1) for this exact version, immediately before approving it: the pre-approval audit
   below shows `own_content_address` and `object_exists` true, and re-running the same CLI write
   command reports `unchanged` (it downloads the stored object and re-hashes it against
   `file_sha256`; a missing or tampered object fails with `artifact_missing`/`artifact_integrity`).
3. `official_url` recorded when the publisher has one; `license_basis` known; `license_reference`
   when the basis needs one.
4. Dry-run output reviewed (chunks, sections, warnings such as `table_uncertain`, empty pages).
5. Approving a new version archives the previously approved one in the same transaction.

**Pre-approval audit** (operator connection; read-only). Scoped to the candidate being approved
plus every already-approved version — a draft that has no artifact yet is legitimate and is not
listed as corrupt:

```sql
select d.id, d.status::text, d.source_id, d.document_id, d.document_version,
       coalesce((d.artifact_ref collate "C")
                ~ ('^knowledge-artifacts/' || d.file_sha256 || '/[A-Za-z0-9][A-Za-z0-9._-]*$'), false)
         as own_content_address,                     -- A + B, and exactly one name segment
       exists (select 1 from storage.objects o
               where o.bucket_id = 'knowledge-artifacts'
                 and o.name = substr(d.artifact_ref, length('knowledge-artifacts/') + 1))
         as object_exists                            -- C, existence part only
from public.knowledge_documents d
where d.id = :candidate_id or d.status = 'approved'
order by d.status, d.source_id, d.document_id;
```

Approve only when every row shows `own_content_address` and `object_exists` true. The byte check
(download + SHA-256 == `file_sha256`) cannot be done in SQL; it is the CLI's `unchanged` re-run in
item 2.

## 6. Republish / archive recovery — deferred

Not implemented, not exposed. Re-importing identical bytes is a no-op and never reactivates an
archived version. Recovery from an accidental archival needs a future explicit, audited
**republish-as-new-version** workflow (new `document_version`, new chunk ids, fresh approval);
there is no hidden or automatic republish path. A legal purge remains ST2 (ADR §9.8).

## 7. Operator runbook

```
# 1. review (no database, no Storage, no credentials)
python backend/scripts/ingest_knowledge.py --file <one file> --dry-run \
  --source-id <slug> --source-title "<publisher series>" --source-owner "<publisher>" \
  --source-type guideline --authority official \
  --document-id <slug> --document-version <publisher version> --title "<title>" --language vi \
  --official-url https://... --license-basis official_publication
# 2. write (same arguments): --target local | --target <project ref of SUPABASE_URL/SUPABASE_DB_URL>
```

Write mode uses the backend settings' operator credentials (direct Postgres + service-role Storage),
never a user JWT, refuses a `--target` that does not match both URLs exactly (the DB URL names a
project only by its pooler user `postgres.<ref>` or host `db.<ref>.supabase.co`, never a substring),
and never prints a secret.
Exit 0 created/unchanged/dry run, 1 refused, 2 usage/target mismatch. Storage is trusted to say
"absent" only with its object-level answer (code `not_found` AND message "Object not found"); authorization, timeout or server errors (and the
`Bucket not found` a wrong key produces) fail with `storage_error`, never as a missing object.

**Run the dry run and the write in the pinned backend environment** (`backend/constraints.txt`):
PDF extraction depends on the pypdf build, and the CLI warns when the running pypdf is not the
pinned one. A pypdf upgrade that changes the extracted text of an ingested PDF is a corpus decision:
that PDF can only be re-ingested as a new `document_version` (new chunk ids, fresh approval).

**Hosted prerequisites.** Done 2026-10-06, each under its own explicit gate: ST1 applied; the
private `knowledge-artifacts` bucket created through the Storage API (not public, 50 MiB, MIME
`text/markdown`/`text/plain`/`application/pdf`, no `storage.objects` policy; anon and authenticated
access verified as denied). Pending: ST1.1 (§1), under its own gate.

## 8. First real corpus acceptance gate (future, mandatory)

Before the first real source is approved/ingested on hosted:
- ST1 and ST1.1 (§1) are merged and applied to hosted;
- C1 source approval (exact artifact, publisher, official URL if available, license basis,
  SHA-256, human approver); the artifact stored and guarantee C verified (§5 checklist and
  pre-approval audit).

Then, once the FIRST real approved document exists (it persists anyway — no artificial residue),
run the HTTP end-to-end test that V1.3-B could not run without leaving permanent test knowledge:

| Caller | Direct PostgREST SELECT (sources/documents/chunks) | lexical RPC |
|---|---|---|
| valid token | approved public source/doc/chunk visible | returns the expected chunk |
| pending password change | 0 rows | 0 rows |
| TOKEN_OLD (minted before the change) | 0 rows | 0 rows |
| TOKEN_NEW | normal visibility | normal behaviour |
| outsider | public only, no tenant leakage | public only |

**Until this gate passes, end-to-end HTTP retrieval of a committed approved row is NOT verified**
(V1.3-B verified RLS at the database layer with real token claims; see its report).

## 9. Tests

| File | What |
|---|---|
| `tests/test_knowledge_pipeline.py` | parsers, normalizer, chunker, ids, validation (no DB) |
| `tests/test_knowledge_ingest.py` | orchestration with in-memory ports, CLI (dry run, targets, no approval switch) |
| `tests/test_knowledge_architecture.py` | purity, adapter writes, no app import |
| `tests/test_knowledge_ingest_db.py` | real local stack: rows + Storage, RLS invisibility until approval, idempotency, conflicts, atomic rollback, archived/approved untouched, tenant farm scope, PDF pages, the ingested address passing ST1.1 on approval — rolled back, Storage objects removed |
| `tests/test_rag_knowledge_artifact_approval.py` | ST1: approval needs a controlled artifact path (bypass shapes, drafts, lifecycle) |
| `tests/test_rag_knowledge_artifact_sha_binding.py` | ST1.1: approval needs the row's own content address (wrong/prefix/extra/case/bucket), drafts and correction, migration on existing rows, rollback + replay |
| `tests/test_knowledge_pdf_isolation.py` | isolated worker: identical output, scans/encrypted/malformed refused, no inherited secret, timeout + repeated timeouts reaped, crash, flooding past the byte cap, malformed/inconsistent results, result validation; POSIX: installed limits and memory/CPU enforcement (a misbehaving stand-in, `fixtures/knowledge/fake_pdf_worker.py`; no real bomb) |

Fixtures are synthetic (`TEST FIXTURE — NOT A REAL APPROVED SOURCE`); PDFs are generated at test
time with reportlab and the bundled Be Vietnam Pro font. No real corpus is committed.

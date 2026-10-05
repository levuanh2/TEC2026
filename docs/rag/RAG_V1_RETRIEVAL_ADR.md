# ADR — RAG V1.3 Retrieval Storage and Pipeline

Status: **PROPOSED — awaiting approval** (V1.3-A, design only; nothing implemented, no migration).
Branch: `feature/rag-v1-retrieval` from `main @ 6c1dfe1` (PR #6 merged).
Related: [RAG_V1_ARCHITECTURE.md](RAG_V1_ARCHITECTURE.md), [RAG_V1_DATA_CONTRACT.md](RAG_V1_DATA_CONTRACT.md),
[RAG_V1_SOURCE_POLICY.md](RAG_V1_SOURCE_POLICY.md), [RAG_V1_RETRIEVAL_EVAL_PLAN.md](RAG_V1_RETRIEVAL_EVAL_PLAN.md).

V1.3 delivers `Question + AuthorizedSeasonScope → RetrievalQuery → KnowledgeRetriever → EvidenceChunk[]`
with a real store and a real scope resolver. It does **not** call `AnswerGenerator`, a real LLM or the
`RagOrchestrator` generation path; the D8 gate (`test_no_answer_generator_is_wired_until_d8_is_closed`)
stays intact. Embedding-model choice is **not** a generation-LLM choice; D5 stays open.

---

## 1. Audit (2026-10-05)

| Area | Finding | Evidence |
|---|---|---|
| Hosted Supabase Postgres | **17.6** | read-only catalog query (`show server_version`) |
| Extensions available, not installed | `vector 0.8.2`, `pg_trgm 1.6`, `unaccent 1.1`, `fuzzystrmatch 1.2` | `pg_available_extensions` |
| Extensions installed | `pg_stat_statements`, `pgcrypto`, `plpgsql`, `supabase_vault`, `uuid-ossp` | `pg_extension` |
| Full-text configs | no `vietnamese`; `simple` available | `pg_ts_config` |
| Local / CI stack | Supabase CLI 2.118.0, `major_version = 17`, `extra_search_path = public, extensions` | `supabase/config.toml`, `ci.yml` |
| Migrations | 21 files, `YYYYMMDDHHMMSS_name.sql`, rollbacks in `supabase/rollbacks/`, checksummed in CI; hosted batches need explicit approval, one at a time | `supabase/migrations`, `ci.yml` (Migrations static + checksums) |
| RLS helpers to reuse | `private.user_is_org_member(org)`, `private.user_can_read_farm(farm)`, `private.user_can_read_crop`, `private.user_can_write_crop` | baseline + later migrations |
| Render staging | one free web service, **512 MB RAM**, single uvicorn process, no worker/cron/disk, manual deploys, cold starts | `render.yaml` |
| Backend deps | locked in `backend/constraints.txt` (74 pins); `psycopg 3.3.6`, `httpx 0.28.1`, **`pypdf 6.19.0` already pinned**; no numpy/onnx/torch in the backend lock | `backend/requirements.txt`, `constraints.txt` |
| ML stack | `torch`, `scikit-learn`, `numpy` only in `ml/requirements.txt` (CV, not deployed to Render) | `ml/requirements.txt` |
| Approved knowledge documents in repo | **none**. Only references: IPCC 2019 Refinement Vol.4 Ch.5 / Ch.11, IPCC 2006 Vol.4 Ch.2, IPCC AR5 WG1 Ch.8, UNFCCC 18/CMA.1 (URLs in `backend/config/emission_factors.yaml`); QĐ 4801/QĐ-BNNMT noted as *not yet obtained* | `emission_factors.yaml` |
| Existing embedding/model infra | none in the backend | — |
| D3 lineage | season → `crop_seasons.plot_id` → `plots.farm_id` → `farms.cooperative_id` (= organization). `SupabaseReadRepository.season/plot` are RLS-bound; the farm view does **not** expose `cooperative_id` | `infrastructure/read_repo.py` |
| WRITE authz | `crop_write_authz.assert_can_write_crop(cur, crop_season_id, actor_id)` | `infrastructure/crop_write_authz.py` |

**Expected volume (estimate, to confirm with the source owner):** an initial approved corpus of
~5–20 documents (IPCC chapters are 50–100 pages; MARD/extension guidance shorter) → roughly
**1k–5k chunks**; tenant documents: none in V1.3. At this size an exact (sequential) vector scan is
fast enough; no ANN index is required to start.

---

## 2. Decision matrix

| Criterion | 1. Supabase Postgres + pgvector | 2. In-process index (FAISS / numpy) | 3. Managed vector DB (Pinecone, Qdrant Cloud, …) |
|---|---|---|---|
| Architecture fit | same DB as Core V1; chunks, metadata, versions and vectors in one place | index file beside the API; metadata elsewhere | second datastore + second consistency domain |
| Tenant isolation | SQL filter **and** RLS (`user_is_org_member`) — defense in depth | only app-level filtering | metadata filters only; no RLS |
| Transactional metadata | yes: source status, version, chunk rows and vectors commit atomically | no; index and metadata drift | no; eventual sync |
| RLS compatibility | native (caller-JWT RPC through PostgREST) | none | none |
| Deployment complexity | one migration (extensions + 3 tables + RPC); no new service | index must ship with / be rebuilt into the 512 MB Render instance; no persistent disk on Free | new account, keys, network egress, sync job |
| CI reproducibility | local Supabase stack already in CI (Postgres 17 image ships `vector`) | easy for unit tests; does not test the real filter path | needs network + secrets in CI (forbidden by current CI policy for PRs) |
| Persistence / backups | Supabase backups cover it | lost on every Render restart (no disk) | vendor backups |
| Cost | $0 extra at this volume (storage ≈ 5k × 384 × 4 B ≈ 8 MB of vectors) | $0, but RAM on Free | paid tier or free-tier limits |
| Render compatibility | nothing new on Render for storage | competes for 512 MB; FAISS wheels add native deps | outbound HTTP only |
| Vendor lock-in | low (plain Postgres + open-source extension) | none | high |
| Scale headroom | HNSW/IVFFlat available later (pgvector 0.8) | fine to ~1M vectors, but per-process | high |

**Recommended: option 1 — Supabase Postgres with `pgvector`, plus Postgres full-text search.**
It is the only option that gives RLS-enforced tenant isolation, atomic versioned metadata,
existing backups and existing CI reproducibility with no new service. Option 2 is rejected for
production (no persistence on Render Free, no RLS, metadata drift) but its idea survives as the
in-memory **fake index** used by unit tests. Option 3 is rejected (second datastore, no RLS,
secrets/network in CI, lock-in, cost) — nothing at AgriCarbon's scale needs it.

---

## 3. Pipeline and placement

```
OFFLINE (operator command, never inside a Q&A request)
  approved source file ─► Parser ─► Normalizer ─► Chunker ─► ChunkMetadata
                                                          └► Embedder ─► KnowledgeIndex (Postgres)
RUNTIME (V1.3 end state, no generation)
  question + crop_season_id
    ─► SeasonScopeResolver (D3 adapter, Core V1 RLS / crop_write_authz) ─► AuthorizedSeasonScope
    ─► build_retrieval_query (pure)                                       ─► RetrievalQuery
    ─► KnowledgeRetriever adapter (caller-JWT RPC, filter + RLS)          ─► EvidenceChunk[]
    ─► assert_tenant_isolation (existing backstop)
```

| Layer | Location (proposed) | Contents |
|---|---|---|
| RAG core (unchanged rules) | `backend/recommendation/rag/` | contracts, `build_retrieval_query`, `assert_tenant_isolation`; **no** parser, embedder, SQL or SDK |
| Knowledge domain (new, pure) | `backend/knowledge/` | `models.py` (SourceStatus, DocumentRecord, ChunkRecord), `normalize.py`, `chunking.py`, `ids.py` (stable ids), `ports.py` (`Embedder`, `KnowledgeStore` Protocols), `ingest.py` (idempotent use case) — small modules, no I/O |
| Parsers | `backend/knowledge/parsers/` | `markdown.py`, `text.py`, `pdf.py` (pypdf) |
| Infrastructure adapters | `backend/infrastructure/knowledge_repo.py`, `infrastructure/embedding_*.py`, `infrastructure/rag_scope.py` | psycopg/PostgREST store + retriever, embedder adapter, `SeasonScopeResolver` |
| Composition | `backend/rag_application.py` (as already planned in ARCHITECTURE §4) | wires resolver + query builder + retriever; **no** generator (D8 gate) |
| Operator CLI | `backend/scripts/ingest_knowledge.py` | runs the offline pipeline against a chosen DB |

`backend/knowledge` follows the `carbon/`, `mrv/`, `recommendation/` package convention. It must not
import `recommendation.rag` beyond the public contract types (`EvidenceChunk`), and the D8 gate
permits that (it only blocks the generation path).

---

## 4. Ingestion

- **Supported formats (V1.3):** Markdown (`.md`), plain text (`.txt`), and PDF **with an extractable
  text layer** (`pypdf`, already pinned). Scanned/image-only PDFs, DOCX, HTML and spreadsheets are
  **unsupported**: a PDF whose extracted text is below a threshold per page is stored as
  `needs_review` with reason `no_text_layer`, never silently indexed. No OCR in V1.3.
- **Normalizer (deterministic, versioned `NORMALIZER_VERSION`):** Unicode NFC (Vietnamese
  diacritics kept), whitespace/line-break repair, hyphenation join, page header/footer removal only
  when repeated on ≥ N pages. The original file hash and the normalized-text hash are both stored.
- **Chunker (structure-aware, versioned `CHUNKER_VERSION`):**
  - split first on structure: Markdown headings; PDF page + detected headings (numbered `1.2.3`,
    ALL-CAPS lines) → `section_path`;
  - then paragraphs; lists and table-like blocks stay whole when they fit;
  - **target ≈ 300 tokens, hard max 450 tokens** (whitespace-token estimate): leaves room for the
    `section_path` prefix inside the 512-token window of the candidate embedding models; a section
    under the max is one chunk;
  - **overlap: none by default**; one trailing sentence of overlap only when a single paragraph is
    split because it exceeds the max (keeps the split sentence answerable);
  - heading inclusion: the chunk's `section_path` is prepended **for embedding/lexical indexing
    only**; `content` keeps the source text;
  - tables: PDF table extraction is unreliable with `pypdf`, so a detected table block is kept whole
    and flagged `metadata.table = true`; numbers in it remain document evidence (D6 still applies).
  These values are a starting point justified by the model window, **not** tuned; the eval plan
  compares 300/450 against a 150/250 and a section-only variant before freezing them.
- **Stable ids:** `document_id` is assigned at source approval (slug, e.g. `ipcc-2019-v4-ch5`);
  `document_version` = source-declared version or the original-file SHA-256 prefix.
  `chunk_id = sha256(document_id | document_version | section_path | ordinal_in_section |
  content_hash)[:20]`. Re-ingesting unchanged content yields identical ids (citations stay valid);
  a new document version yields new ids and **archives** the old chunks (never deletes provenance).
  Storage row ids / vector ids are never used as citation identity.
- **Idempotency:** unique `(document_id, document_version)` and unique `(document_id,
  document_version, chunk_id)`; ingestion is an upsert keyed by those plus `content_hash`; a re-run
  with the same input is a no-op; a run with a new version flips the previous version to
  `archived` in the same transaction.

---

## 5. Embedding (port + adapter; model choice needs approval — decision E1)

Port in `backend/knowledge/ports.py`:

```
class Embedder(Protocol):
    model_id: str          # e.g. "intfloat/multilingual-e5-small@<revision>"
    dimension: int
    normalized: bool       # vectors are L2-normalized → cosine == inner product
    preprocessing: str     # e.g. "e5-v1: 'query: ' / 'passage: ' prefixes, NFC"
    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
```

Every chunk row stores `embedding_model_id`, `embedding_dimension` and `preprocessing_version`; the
retriever queries only rows whose `embedding_model_id` equals the configured query embedder.
Changing the model is a re-embed into the same rows under a new model id, never a silent mix.

| Candidate | Dim | Vietnamese | License | Runtime | Cost | Notes |
|---|---|---|---|---|---|---|
| **A. `multilingual-e5-small` (ONNX, int8)** | 384 | yes (multilingual training) | MIT | in-process via `onnxruntime` + `tokenizers` | $0 | ~120 MB model; query embedding must also run on Render Free → **512 MB risk, must be measured** |
| B. hosted embedding API (e.g. OpenAI `text-embedding-3-small`, Google, Cohere multilingual) | 768–1536 | yes | commercial | HTTPS from backend (`httpx` already pinned) | per-token (tiny at this volume) | sends the **user question** to a third party at query time → data-residency decision (same family as D5) |
| C. no embedding in V1.3 (lexical only) | — | via `simple` + `unaccent` | — | Postgres | $0 | baseline; may be enough for a small, terminology-heavy corpus |

**Recommendation:** build the pipeline with the `Embedder` port and a deterministic fake for tests;
run the **lexical baseline first** (C), then measure A on the eval set and on Render memory. Adopt A
only if it measurably improves Hit@k/MRR over C and fits in memory; B only with an explicit
data-residency approval. The vector column is created with the dimension of the approved model.

---

## 6. Retrieval

- **Lexical:** Postgres FTS on `to_tsvector('simple', unaccent(section_path || ' ' || content))`
  (no Vietnamese stemmer exists; `simple` + `unaccent` handles diacritic variants) plus `pg_trgm`
  for acronyms/terms ("AWD", "1P5G", "IPCC", "N2O"). Expected to matter for this corpus: exact
  methodology terms, acronyms and policy numbers (QĐ 4801).
- **Vector:** cosine (`<=>`) over normalized vectors, exact scan first; HNSW only if latency needs it.
- **Hybrid:** if both are enabled, fuse with **Reciprocal Rank Fusion** `score = Σ 1/(60 + rank)`
  (k = 60 from Cormack, Clarke & Büttcher, SIGIR 2009) — rank-based, so no tuned score weights.
  Whether V1.3 ships lexical-only, vector-only or hybrid is decided by the eval set, not assumed.
- **top-k:** retrieve 20 candidates per method, return `RetrievalQuery.top_k` (default 8, max 50,
  existing contract).
- **Reranking:** **none in V1.3** unless the baseline eval shows relevant chunks ranked between 9
  and 20 often enough to matter (see eval plan).
- **Query text:** `build_retrieval_query` stays pure: question + intent + at most a few
  **INFORMATIONAL_SAFE** context terms (e.g. the recorded water regime label); never
  ACTION_CONTEXT, never the whole crop record.

---

## 7. Tenant isolation

| Scope | Rule |
|---|---|
| Public | `visibility = 'public'`, `organization_id is null`, `status = 'approved'` — readable by any authenticated caller |
| Organization | `visibility = 'tenant'`, `organization_id = scope.organization_id` **and** RLS `private.user_is_org_member(organization_id)` |
| Farm | additionally `farm_id is null or farm_id = scope.farm_id` **and** RLS `private.user_can_read_farm(farm_id)` when set |
| Season | no season-level documents in V1.3 (no use case); `crop_season_id` stays in `TenantScope` for logging/ranking only |

Filters come only from `AuthorizedSeasonScope` (never from the request or document text). The
retrieval RPC runs with the **caller's JWT**, so RLS is a second, independent gate; the existing
`assert_tenant_isolation` is the third. V1.3 ingests **no** tenant documents (no upload flow); the
schema and tests cover tenant rows so isolation is proven before any tenant ingestion exists.

---

## 8. D3 — real `SeasonScopeResolver`

- **READ:** `SupabaseReadRepository` bound to the caller's JWT: `season(id)` (404/RLS gate) →
  `plot(plot_id)` → farm lineage. The current farm view omits `cooperative_id`, so one **additive
  read method** (`season_lineage(season_id) -> {season_id, plot_id, farm_id, organization_id}`,
  RLS-bound, no service role) is added to the read repository. Any `ReadNotFoundError` →
  `RagAccessDenied` (404 `not_found`, same as Recommendation/CV).
- **WRITE:** after the READ lineage, `crop_write_authz.assert_can_write_crop(cur, crop_season_id,
  actor_id)` inside a psycopg transaction, exactly as Recommendation/CV writes do;
  `CropWriteDeniedError` → `RagAccessDenied`.
- **Schema change: NO.** Location: `backend/infrastructure/rag_scope.py`; the RAG core still imports
  neither Supabase nor psycopg.

---

## 9. Proposed persistent schema (NOT applied — decision S1)

One migration, after approval, applied local → CI → hosted one at a time:

```sql
create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;
create extension if not exists unaccent with schema extensions;

create type public.knowledge_source_status as enum ('review_required', 'approved', 'rejected', 'archived');

create table public.knowledge_sources (          -- a publisher/series, e.g. IPCC 2019 Refinement
  source_id text primary key,                     -- stable slug, citation identity
  title text not null, source_type text not null, -- guideline|policy|methodology|research|tenant_document
  authority text,                                 -- official|peer_reviewed|extension|internal
  owner text not null,                            -- publishing body, as stated by the source
  visibility text not null check (visibility in ('public','tenant')),
  organization_id uuid references public.organizations(id), farm_id uuid references public.farms(id),
  status public.knowledge_source_status not null default 'review_required',
  approved_by uuid references auth.users(id), approved_at timestamptz, review_note text,
  check ((visibility = 'public') = (organization_id is null))
);

create table public.knowledge_documents (        -- one immutable version of one document
  id uuid primary key default gen_random_uuid(),
  source_id text not null references public.knowledge_sources(source_id),
  document_id text not null, document_version text not null,
  title text not null, language text not null, url text check (url like 'https://%'),
  published_at date, imported_at timestamptz not null default now(),
  file_sha256 text not null, normalized_sha256 text not null,
  parser_version text not null, normalizer_version text not null, chunker_version text not null,
  status public.knowledge_source_status not null default 'review_required',
  unique (document_id, document_version)
);

create table public.knowledge_chunks (
  id bigint generated always as identity primary key,       -- storage id, never a citation id
  document_pk uuid not null references public.knowledge_documents(id),
  chunk_id text not null, ordinal int not null, section_path text, page_from int, page_to int,
  content text not null, content_sha256 text not null, metadata jsonb not null default '{}',
  search_tsv tsvector not null,                                -- simple + unaccent, set at ingestion
  embedding extensions.vector(384), embedding_model_id text, preprocessing_version text,
  unique (document_pk, chunk_id)
);
-- + GIN(search_tsv), GIN(content gin_trgm_ops); vector index only if measured necessary
-- + RLS on all three; select policy: approved AND (public OR user_is_org_member(org) [AND farm rule]);
--   no insert/update/delete policy for authenticated (ingestion = operator path).
-- + RPC public.match_knowledge_chunks(query_text, query_embedding, k, filters) SECURITY INVOKER.
```

Visibility/organization live on the source and are denormalized into the RPC filter; a document
version is retrievable only when both its source and the version are `approved`.

---

## 10. Dependencies

| Package | Purpose | Version | License | Scope | Why existing deps don't suffice | Status |
|---|---|---|---|---|---|---|
| `pypdf` | PDF text extraction | 6.19.0 (already pinned) | BSD-3 | production (ingestion CLI) | — already present | reuse |
| `psycopg` | store/RPC adapter | 3.3.6 (pinned) | LGPL-3.0 (already under license REVIEW) | production | — | reuse |
| `onnxruntime` | run embedding model A | TBD at V1.3-D | MIT | production | no inference runtime in the backend lock | **proposed, only if E1 = A** |
| `tokenizers` | model A tokenizer | TBD | Apache-2.0 | production | stdlib cannot reproduce the model's tokenizer | **proposed, only if E1 = A** |
| numpy | not needed: vectors go to Postgres as text literals; similarity runs in SQL | — | — | — | — | not added |

No LangChain/LlamaIndex/FAISS/Chroma/Pinecone. Any addition updates `constraints.txt` from the CI
freeze (repo policy), never a broad upgrade.

---

## 11. Risks

| Severity | Risk | Mitigation |
|---|---|---|
| HIGH | No approved corpus exists; retrieval cannot be evaluated or shipped without one | decision C1 below; V1.3-C uses a small fixture corpus for tests only |
| MEDIUM | In-process embedding on Render Free (512 MB) may OOM at query time | lexical baseline first; measure RSS before adopting model A |
| MEDIUM | PDF structure from `pypdf` is weak (headings, tables) | structure heuristics + `needs_review`; Markdown preferred for curated sources |
| MEDIUM | Vietnamese lexical search without a stemmer | `simple` + `unaccent` + trigram; measured in eval |
| LOW | Copyright/licensing of source documents | source policy requires a recorded license basis before approval |
| LOW | Dimension lock-in on the vector column | column created only after E1; re-embed path documented |

## 12. Decisions needed

- **S1** Approve the schema in §9 (one migration: 3 extensions, 1 enum, 3 tables, RLS, 1 RPC).
- **E1** Embedding: A (local e5-small, measured), B (hosted API, data-residency approval), or C
  (lexical-only for V1.3, vector later).
- **C1** Initial approved corpus: which documents, owner/approver, license basis (see source policy).

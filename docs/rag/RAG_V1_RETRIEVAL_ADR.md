# ADR — RAG V1.3 Retrieval Storage and Pipeline

Status: **V1.3-B IMPLEMENTED LOCALLY** — Migration A is
`supabase/migrations/20261005090000_knowledge_retrieval_lexical_foundation.sql` (+ rollback), validated
on the local/CI stack only; **not applied to hosted**. No ingestion code, no dependency, no vector.
Branch: `feature/rag-v1-retrieval` from `main @ 6c1dfe1` (PR #6 merged).
Related: [RAG_V1_ARCHITECTURE.md](RAG_V1_ARCHITECTURE.md), [RAG_V1_DATA_CONTRACT.md](RAG_V1_DATA_CONTRACT.md),
[RAG_V1_SOURCE_POLICY.md](RAG_V1_SOURCE_POLICY.md), [RAG_V1_RETRIEVAL_EVAL_PLAN.md](RAG_V1_RETRIEVAL_EVAL_PLAN.md).

V1.3 delivers `Question + AuthorizedSeasonScope → RetrievalQuery → KnowledgeRetriever → EvidenceChunk[]`
with a real store and a real scope resolver. It does **not** call `AnswerGenerator`, a real LLM or the
`RagOrchestrator` generation path; the D8 gate (`test_no_answer_generator_is_wired_until_d8_is_closed`)
stays intact. Embedding is **not** a generation-LLM choice; D5 stays open.

## Decision record

| Id | Decision | Status |
|---|---|---|
| S1 | Postgres-native knowledge store, split into **Migration A (lexical foundation)** now and an optional **Migration B (vector)** later | direction approved; Migration A spec §9 ready to write after this review |
| E1 | **C — lexical-first** baseline for V1.3. No embedding model, dimension, runtime or pgvector yet | **decided** |
| C1 | Source policy approved; candidate corpus defined; **no document approved yet** | **decided (policy)** |
| D3 | Real `SeasonScopeResolver` reusing Core V1 RLS reads + `crop_write_authz`; additive `season_lineage` read; no schema change | **approved** |
| ST1 | Controlled archived copy of original artifacts (Supabase Storage) | **open** — separate decision; V1.3 accepts official URL + SHA-256 (§4.4) |

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
| Function convention | `set search_path = ''`, schema-qualified references | baseline migration |
| RLS helpers to reuse | `private.user_is_org_member(uuid)`, `private.user_can_read_farm(uuid)`, `private.user_can_read_crop`, `private.user_can_write_crop` | baseline + later migrations |
| Farm ownership | `farms.cooperative_id uuid not null references organizations` — **no immutability guard** in Core V1 | baseline line 333 |
| Render staging | one free web service, **512 MB RAM**, single uvicorn process, no worker/cron/disk, manual deploys | `render.yaml` |
| Backend deps | locked in `backend/constraints.txt` (74 pins); `psycopg 3.3.6`, `httpx 0.28.1`, **`pypdf 6.19.0` already pinned**; no numpy/onnx/torch in the backend lock | `backend/requirements.txt`, `constraints.txt` |
| Approved knowledge documents | **none**; candidates in [source policy §2](RAG_V1_SOURCE_POLICY.md) | `emission_factors.yaml` cites IPCC/UNFCCC URLs |
| D3 lineage | season → `crop_seasons.plot_id` → `plots.farm_id` → `farms.cooperative_id`; `SupabaseReadRepository.season/plot` are RLS-bound; the farm view omits `cooperative_id` | `infrastructure/read_repo.py` |
| WRITE authz | `crop_write_authz.assert_can_write_crop(cur, crop_season_id, actor_id)` | `infrastructure/crop_write_authz.py` |

**Expected volume (estimate, to confirm per C1):** ~5–10 approved documents → roughly 1k–5k chunks;
no tenant documents in V1.3. Lexical GIN indexes are ample at this size.

---

## 2. Decision matrix (storage)

| Criterion | 1. Supabase Postgres (+ pgvector later) | 2. In-process index (FAISS / numpy) | 3. Managed vector DB |
|---|---|---|---|
| Architecture fit | same DB as Core V1; chunks, metadata, versions in one place | index file beside the API; metadata elsewhere | second datastore + consistency domain |
| Tenant isolation | SQL filter **and** RLS — defense in depth | app-level only | metadata filters only; no RLS |
| Transactional metadata | atomic | drift | eventual |
| Deployment | one migration; no new service | must live in the 512 MB Render process; no persistent disk on Free | account, keys, egress, sync job |
| CI reproducibility | local Supabase stack already in CI | unit tests only | network + secrets in PR CI (not allowed today) |
| Persistence / backups | Supabase backups | lost on restart | vendor |
| Cost | ~$0 at this volume | $0, but RAM | paid / free-tier limits |
| Lock-in | low | none | high |

**Choice: option 1.** Option 2 survives only as the in-memory fake used by unit tests; option 3 is
rejected. With E1 = C, V1.3 uses Postgres **full-text + trigram** only; pgvector arrives only through
Migration B after the vector adoption gate (§5).

---

## 3. Pipeline and placement

```
OFFLINE (operator command, never inside a Q&A request)
  approved artifact ─► Parser ─► Normalizer ─► Chunker ─► ChunkMetadata ─► KnowledgeStore (Postgres)
                                                       (Embedder only after Migration B)
RUNTIME (V1.3 end state, no generation)
  question + crop_season_id
    ─► SeasonScopeResolver (D3, Core V1 RLS / crop_write_authz) ─► AuthorizedSeasonScope
    ─► build_retrieval_query (pure)                              ─► RetrievalQuery
    ─► KnowledgeRetriever adapter ─► rpc match_knowledge_chunks_lexical (caller JWT, RLS)
    ─► relevance cutoff (DEV-calibrated) ─► EvidenceChunk[] ─► assert_tenant_isolation
```

| Layer | Location (proposed) | Contents |
|---|---|---|
| RAG core (unchanged rules) | `backend/recommendation/rag/` | contracts, `build_retrieval_query`, `assert_tenant_isolation`; **no** parser, SQL, SDK, embedder |
| Knowledge domain (new, pure) | `backend/knowledge/` | `models.py`, `normalize.py`, `chunking.py`, `ids.py`, `ports.py` (`KnowledgeStore`; `Embedder` declared but unused until Migration B), `ingest.py` — small modules, no I/O |
| Parsers | `backend/knowledge/parsers/` | `markdown.py`, `text.py`, `pdf.py` (pypdf) |
| Infrastructure adapters | `backend/infrastructure/knowledge_repo.py`, `infrastructure/rag_scope.py` | store + lexical retriever (RPC), `SeasonScopeResolver` |
| Composition | `backend/rag_application.py` | resolver + query builder + retriever; **no** generator (D8 gate allows retrieval/scope imports) |
| Operator CLI | `backend/scripts/ingest_knowledge.py` | offline pipeline against a chosen DB; approvals are separate explicit operator actions |

---

## 4. Ingestion

### 4.1 Formats
Markdown (`.md`), plain text (`.txt`), PDF **with an extractable text layer** (`pypdf`, already
pinned). A PDF whose extracted text falls below a per-page threshold is stored `review_required`
with reason `no_text_layer` and never indexed as approved. DOCX, HTML, spreadsheets, scans/OCR:
**unsupported** in V1.3.

### 4.2 Normalization (two distinct steps, one owner each)
- **Content normalization** (Python, `NORMALIZER_VERSION`): Unicode NFC (diacritics kept),
  whitespace/line-break repair, hyphenation join, page header/footer removal only when repeated on
  ≥ N pages. Produces `content` as shown to users.
- **Search normalization** (database, single source of truth): `private.knowledge_search_text(text)`
  = `lower(extensions.unaccent('extensions.unaccent'::regdictionary, …))`, used **both** by the chunk
  trigger and by the lexical RPC for the query. Python never re-implements it (§9.4).

### 4.3 Chunking (structure-aware lexical baseline)
- Split on structure first: Markdown headings; PDF page + detected headings (numbered `1.2.3`,
  ALL-CAPS lines) → `section_path`; then paragraphs; lists and table-like blocks stay whole when
  they fit.
- **Initial heuristic: target ≈ 300, hard max 450 whitespace-delimited tokens.** This is a lexical
  baseline chosen to keep chunks section-sized and citable; it is **not** a model-token budget and
  is **not** claimed to fit any embedding window. Variants (150/250, section-only) are compared on
  DEV before freezing (eval plan §6).
- Overlap: none by default; one trailing sentence only when a single paragraph exceeds the max.
- Tables: a detected table block is kept whole and flagged `metadata.table = true`; numbers in it
  stay document evidence (D6 unchanged).
- **If E1 = A is adopted later:** the embedding input (`model prefix + section_path + content`) is
  measured with the **exact approved tokenizer and model revision**; anything over the model limit
  is **deterministically split before embedding** (never silently truncated), and the split rule is
  versioned with the embedding provenance.

### 4.4 Artifact provenance
Every document version records `file_sha256` and **at least one** of:
- `official_url` (`https://`, the publisher's location), or
- `artifact_ref` (a controlled, immutable reference to a stored copy).

**V1.3 accepts `official_url` + `file_sha256`.** Limitation: the publisher may move, change or remove
the file; the hash detects drift but cannot recover the original, so re-ingestion is reproducible
only while the URL serves the same bytes. A controlled archived copy (Supabase Storage, retention,
access policy) is decision **ST1**, a separate implementation; `artifact_ref` exists in the schema so
it can be adopted without another identity change.

### 4.5 Identity and idempotency
- `source_id` (slug, per publisher/series), `document_id` (slug, unique **within its source**),
  `document_version` (publisher version, else the `file_sha256` prefix).
- Document uniqueness: **`(source_id, document_id, document_version)`**. Citation identity:
  `source_id` + `document_id`/`document_version` + `chunk_id`.
- `chunk_id = sha256(source_id | document_id | document_version | section_path |
  ordinal_in_section | content_sha256)[:20]` — unchanged content re-ingests to identical ids; a new
  version yields new ids. Storage row ids are never citation identity.
- Upserts keyed by those identities; re-running the same input is a no-op. A new version is
  inserted `review_required`; approving it archives the previous approved version in the same
  transaction (enforced by a partial unique index, §9.3).

---

## 5. Embedding (E1)

**E1 = C (lexical-first) for V1.3.** No embedding model, dimension, runtime, dependency or pgvector
is chosen or installed now. The `Embedder` port is only declared in `knowledge/ports.py` so a later
adapter does not reshape the domain.

**Vector adoption gate (all required before Migration B or any embedding dependency):**
1. lexical baseline measured and frozen on DEV (its HOLDOUT done-gate result recorded); the vector
   decision itself uses **DEV only** — HOLDOUT is never used to choose a method;
2. vector or hybrid improves the predeclared DEV metric (MRR@10 or Hit@5) by **≥ 0.05 absolute**
   over lexical, with no category losing more than one DEV query at Hit@5 (5 queries per
   category), and every such loss inspected by hand (eval plan §6);
3. **Render memory gate:** the backend with the model loaded and one query embedded stays within
   the Render Free budget (peak RSS measured in a clean Render-like container, with ≥ 25 % headroom
   below 512 MB);
4. exact model revision and license verified and recorded;
5. option B (hosted embedding API) additionally needs an explicit **data-residency approval**,
   because the user's question would leave AgriCarbon at query time.

Candidates kept for that later evaluation: A — `multilingual-e5-small` (MIT, multilingual) via
ONNX; B — a hosted multilingual embedding API. Neither is selected. D5 (generation LLM) is unrelated
and remains open.

---

## 6. Retrieval (V1.3: lexical only)

- **Signals:** full-text over the normalized question, matching **any** of its lexemes (an OR of
  `plainto_tsquery('simple', …)`'s lexemes) — farmers ask sentences, and `simple` has no stopwords,
  so an AND of every word ("AWD là gì và vì sao …") would match nothing; `ts_rank_cd` ranks
  passages covering more of the question higher. Postgres FTS has no IDF, so frequent function
  words also match; their effect is measured on DEV, and a stopword list would be DEV tuning, not
  a default. Trigram `extensions.word_similarity(private.knowledge_search_text(q), search_text)`
  carries acronyms and no-diacritic/misspelled Vietnamese ("AWD", "1P5G", "tuoi ngap").
- **Ranking inside the RPC (deterministic):** each signal ranks its own candidates (FTS by
  `ts_rank_cd`, trigram by `word_similarity`, each ≤ 50 candidates); the two rank lists are fused by
  **Reciprocal Rank Fusion**, `Σ 1/(60 + rank)` (k = 60, Cormack, Clarke & Büttcher, SIGIR 2009),
  so no raw scores of different scales are added. Ties break on `(source_id, document_id,
  document_version, ordinal, chunk_id)`.
- **Relevance cutoff:** the RPC returns the fused score and both component ranks; the adapter keeps
  results above a **lexical-specific cutoff calibrated on DEV** (eval plan §6). A query may therefore
  return **no evidence** — required for out-of-corpus questions. Cutoffs of different methods are
  never compared with each other.
- **top_k:** `RetrievalQuery.top_k` (default 8), clamped to 1..50 inside the RPC as well.
- **Reranking:** none in V1.3 unless the DEV rule in the eval plan triggers it.
- **Query text:** `build_retrieval_query` stays pure: question + intent + at most a few
  INFORMATIONAL_SAFE context terms; never ACTION_CONTEXT, never the whole crop record.

---

## 7. Tenant isolation

| Scope | Rule (all derived in the database from the authorized season) |
|---|---|
| Public | source `visibility = 'public'` (⇒ `organization_id` and `farm_id` null) |
| Organization | source `visibility = 'tenant'` and `organization_id` = the season's organization |
| Farm | tenant source with `farm_id` set: `farm_id` = the season's farm **and** that farm's current `cooperative_id` = the source's `organization_id` (re-checked at query time) |
| Season | no season-level documents in V1.3 |

Gates, independent of each other: (1) the RPC derives organization/farm from the season the caller
can read (RLS on `crop_seasons`/`plots`/`farms`), never from a caller-supplied filter; (2) RLS on
the knowledge tables, which also shows **nothing** -- public included -- while the caller's Core V1
password change is pending (§9.5); (3) the existing `assert_tenant_isolation` in the RAG core. V1.3 ingests no
tenant documents; the schema and tests cover tenant rows so isolation is proven first.

---

## 8. D3 — real `SeasonScopeResolver` (approved)

- **READ:** caller-bound `SupabaseReadRepository`: `season(id)` (404/RLS gate) → plot → farm
  lineage via one additive RLS-bound read `season_lineage(season_id) -> {season_id, plot_id,
  farm_id, organization_id}` (the farm view omits `cooperative_id`). `ReadNotFoundError` →
  `RagAccessDenied` (404 `not_found`).
- **WRITE:** after the READ lineage, `crop_write_authz.assert_can_write_crop(cur, crop_season_id,
  actor_id)` in a psycopg transaction, exactly as Recommendation/CV writes; `CropWriteDeniedError` →
  `RagAccessDenied`.
- Location `backend/infrastructure/rag_scope.py`; the RAG core imports neither Supabase nor psycopg.
  **No schema change.**

---

## 9. Migration A — Knowledge lexical foundation (`20261005090000`, local/CI only; NOT applied to hosted)

One migration file plus its rollback, applied local → CI → hosted, one at a time with approval.
**No `vector` extension, no vector column, no vector index, no embedding parameter.**

### 9.1 Extensions and types
```sql
create extension if not exists pg_trgm  with schema extensions;
create extension if not exists unaccent with schema extensions;

create type public.knowledge_status as enum ('review_required', 'approved', 'rejected', 'archived');
create type public.knowledge_license_basis as enum (
  'unknown', 'official_publication', 'public_domain', 'open_license', 'written_permission', 'tenant_owned');
```

### 9.2 Tables (abridged; types/nullability as listed)
```sql
create table public.knowledge_sources (                 -- publisher / series
  source_id text primary key check (source_id ~ '^[a-z0-9][a-z0-9-]{1,63}$'),
  title text not null, owner text not null,             -- publisher as stated by the source
  source_type text not null check (source_type in ('guideline','policy','methodology','research','tenant_document')),
  authority text check (authority in ('official','peer_reviewed','extension','internal')),
  visibility text not null check (visibility in ('public','tenant')),
  organization_id uuid references public.organizations(id) on delete restrict,
  farm_id uuid references public.farms(id) on delete restrict,
  status public.knowledge_status not null default 'review_required',
  approved_by uuid references auth.users(id), approved_at timestamptz, review_note text,
  created_at timestamptz not null default now(),
  -- tenant scope shape
  constraint knowledge_source_scope check (
    (visibility = 'public' and organization_id is null and farm_id is null)
    or (visibility = 'tenant' and organization_id is not null)),
  -- approval: publisher verified by a named human
  constraint knowledge_source_approval check (
    status <> 'approved' or (approved_by is not null and approved_at is not null
                             and nullif(btrim(review_note), '') is not null))
);

create table public.knowledge_documents (               -- one immutable version of one document
  id uuid primary key default gen_random_uuid(),
  source_id text not null references public.knowledge_sources(source_id) on delete restrict,
  document_id text not null check (document_id ~ '^[a-z0-9][a-z0-9-]{1,127}$'),
  document_version text not null,
  title text not null, language text not null check (language ~ '^[a-z]{2}$'),
  official_url text check (official_url ~ '^https://'), artifact_ref text,
  file_sha256 text not null check (file_sha256 ~ '^[0-9a-f]{64}$'),
  normalized_sha256 text not null check (normalized_sha256 ~ '^[0-9a-f]{64}$'),
  published_at date, imported_at timestamptz not null default now(),
  parser_version text not null, normalizer_version text not null, chunker_version text not null,
  license_basis public.knowledge_license_basis not null default 'unknown',
  license_reference text,                                -- licence name/terms URL/permission ref
  status public.knowledge_status not null default 'review_required',
  approved_by uuid references auth.users(id), approved_at timestamptz, review_note text,
  unique (source_id, document_id, document_version),
  constraint knowledge_document_artifact check (official_url is not null or artifact_ref is not null),
  constraint knowledge_document_approval check (
    status <> 'approved' or (approved_by is not null and approved_at is not null
                             and nullif(btrim(review_note), '') is not null
                             and license_basis <> 'unknown'
                             and (license_basis not in ('open_license','written_permission')
                                  or nullif(btrim(license_reference), '') is not null)))
);

create table public.knowledge_chunks (
  id bigint generated always as identity primary key,    -- storage id, never a citation id
  document_pk uuid not null references public.knowledge_documents(id) on delete restrict,
  chunk_id text not null check (chunk_id ~ '^[0-9a-f]{20}$'),
  ordinal int not null check (ordinal >= 0),
  section_path text, page_from int, page_to int,
  content text not null check (length(content) > 0),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  metadata jsonb not null default '{}',
  search_text text not null,                             -- trigger-maintained (9.4)
  search_tsv tsvector not null,                          -- trigger-maintained (9.4)
  unique (document_pk, chunk_id), unique (document_pk, ordinal)
);
```

### 9.3 Invariants beyond CHECKs
- **Farm belongs to organization:** `private.enforce_knowledge_source_scope()` (BEFORE INSERT/UPDATE
  on `knowledge_sources`, `set search_path = ''`): if `farm_id` is not null, require
  `exists (select 1 from public.farms f where f.id = new.farm_id and f.cooperative_id =
  new.organization_id)`, else raise. Core V1 `farms` is not modified. Because Core V1 does not
  freeze `farms.cooperative_id`, the lexical RPC re-checks the same join at query time, so a farm
  later moved to another organization makes the source **unretrievable** (fail closed), never
  visible to the new organization.
- **One approved version per document:** `create unique index knowledge_documents_one_approved on
  public.knowledge_documents (source_id, document_id) where status = 'approved'`.
- **Immutable artifacts:** BEFORE UPDATE on `knowledge_documents` rejects changes to `source_id`,
  `document_id`, `document_version`, `file_sha256`, `normalized_sha256`; `knowledge_chunks` rows are
  insert-only (search fields are set by the BEFORE INSERT trigger; UPDATE and DELETE are rejected).

### 9.4 Search normalization (single source of truth)
```sql
create function private.knowledge_search_text(p_text text) returns text
  language sql stable parallel safe set search_path = ''
  as $$ select btrim(regexp_replace(
         lower(extensions.unaccent('extensions.unaccent'::regdictionary, normalize(coalesce(p_text, ''), nfc))),
         '\s+', ' ', 'g')) $$;
-- BEFORE INSERT on knowledge_chunks (private.knowledge_chunks_search_fields):
--   new.search_text := private.knowledge_search_text(concat_ws(' ', new.section_path, new.content));
--   new.search_tsv  := to_tsvector('simple'::regconfig, new.search_text);
-- Supplied search_text/search_tsv values are overwritten; chunks are never updated (9.3).
create index knowledge_chunks_search_tsv_idx  on public.knowledge_chunks using gin (search_tsv);
create index knowledge_chunks_search_trgm_idx on public.knowledge_chunks using gin (search_text extensions.gin_trgm_ops);
```
The trigger is the only writer of `search_text`/`search_tsv`; the RPC normalizes the query with the
same function. The function is `stable` (unaccent with a dictionary argument is not immutable); no
expression index depends on it — the GIN indexes are on the stored columns. Tests assert NFD = NFC, `đ→d`, tone-mark removal, case folding and whitespace collapse; there is
no stemming.

### 9.5 RLS and privileges (as implemented)
- RLS enabled on all three tables. Policies chain (SECURITY INVOKER; the only definer function is
  the password-guard wrapper below), and each one starts with
  `not (select private.knowledge_read_blocked())`:
  `knowledge_sources_select` — `status = 'approved'` and (public, or tenant with
  `private.user_is_org_member(organization_id)` and (`farm_id is null`, or
  `private.user_can_read_farm(farm_id)` and the farm still belongs to the organization));
  `knowledge_documents_select` — `status = 'approved'` and its source is visible;
  `knowledge_chunks_select` — its document is visible.
- Membership semantics are Core V1's: a former member (even a former farm owner who still reads
  the farm) and a data-grant viewer of another organization are **not** members, so they see
  public knowledge only.
- Privileges: `revoke all … from public, anon, authenticated` then `grant select … to
  authenticated` on the three tables — client writes fail at the privilege level (42501), not
  only by RLS; `anon` has no access. No write policy exists; ingestion/approval are operator
  actions (table owner / service role).
- **Core V1 forced password change** (migrations `20261002100000` + `20261003090000`): a caller
  whose change is pending sees **no** knowledge row — direct SELECT of all three tables and the RPC
  return nothing, approved *public* rows included. "Public" means public to a valid business user,
  not a bypass of the forced-password state. Pending is exactly Core V1's canonical
  `private.password_change_pending()`: the live `auth.users` flag **or** a token minted with the
  `must_change_password` claim, so an access token minted with the temporary password (TOKEN_OLD)
  stays refused after the change, and a token minted after it (TOKEN_NEW) gets normal RLS.
  The invoker policies reach it through `private.knowledge_read_blocked()`, a SECURITY DEFINER
  wrapper (`set search_path = ''`, body `select private.password_change_pending();`, EXECUTE to
  `authenticated` only) owned and dropped by Migration A. No forced-password logic is duplicated
  and no Core V1 function, privilege or policy changes (`authenticated` still has no EXECUTE on
  `private.password_change_pending()`). The RPC additionally gets no season for such a caller
  (`user_can_read_farm` refuses it).

### 9.6 Lexical RPC
```sql
create function public.match_knowledge_chunks_lexical(
  p_crop_season_id uuid, p_query text, p_top_k int default 8)
returns table (source_id text, document_id text, document_version text, chunk_id text,
               ordinal int, title text, section_path text, page_from int, page_to int,
               content text, metadata jsonb, source_type text, authority text, visibility text,
               organization_id uuid, farm_id uuid, official_url text, published_at date,
               fused_score double precision, fts_rank int, trgm_rank int)
language sql stable security invoker set search_path = ''
```
- Scope: derives the season's `plot → farm → cooperative_id` through RLS-visible tables; an
  unreadable season yields no rows. No organization/farm/visibility parameter exists.
- Filters: source and version `approved`; public, or tenant with matching organization and the
  farm rule of §7 (including the query-time farm/organization re-check).
- `p_top_k` clamped to `1..50` (null → 8); `p_query` truncated to 1,000 characters before
  normalization; a blank or lexeme-free query → no rows. Query text is only ever a bound value
  (no dynamic SQL).
- Trigram candidates use the `<%` operator, i.e. `word_similarity >=
  pg_trgm.word_similarity_threshold` (extension default 0.6, not tuned); FTS candidates match
  any lexeme of the question (OR); at most 50 per signal before fusion.
- Deterministic ranking and tie-break as in §6.
- `revoke all … from public, anon, authenticated; grant execute … to authenticated, service_role`.
No `query_embedding` parameter; a vector RPC is additive in Migration B.

### 9.7 Migration B (future, only after the §5 gate)
`vector` extension; per-chunk embedding rows or columns with the **approved** dimension,
`embedding_model_id`, `model_revision`, `preprocessing_version`, `tokenizer_split_version`; a vector
RPC (or a fused RPC) that compares only vectors of the configured model; an ANN index only if
latency measurements require it.

---

## 10. Dependencies

| Package | Purpose | Version | License | Scope | Status |
|---|---|---|---|---|---|
| `pypdf` | PDF text extraction | 6.19.0 (already pinned) | BSD-3 | ingestion CLI | reuse |
| `psycopg` | store/RPC adapter | 3.3.6 (pinned) | LGPL-3.0 (already under license REVIEW) | production | reuse |
| any embedding runtime / client | — | — | — | — | **not added** (E1 = C) |

No LangChain/LlamaIndex/FAISS/Chroma/Pinecone/numpy. Any future addition updates `constraints.txt`
from the CI freeze (repo policy).

---

## 11. Risks

| Severity | Risk | Mitigation |
|---|---|---|
| HIGH | No approved corpus; retrieval cannot be measured or shipped | C1 approval workflow; V1.3-C uses a fixture corpus for tests only |
| MEDIUM | `pypdf` structure detection is weak (headings, tables) | heuristics + `review_required`; prefer curated Markdown of official text where license allows |
| MEDIUM | Vietnamese lexical recall without a stemmer | `simple` + `unaccent` + trigram; measured on DEV/HOLDOUT |
| MEDIUM | Small HOLDOUT (24) → wide uncertainty on the done gate | report counts and per-query outcomes, not only rates |
| MEDIUM | Official URL drift (ST1 open) | `file_sha256` drift detection; ST1 decision before relying on re-ingestion |
| LOW | `farms.cooperative_id` mutable in Core V1 | write trigger + query-time re-check (fail closed) |
| LOW | Copyright/licensing | `license_basis` must be known to approve; `license_reference` for open/permission bases |

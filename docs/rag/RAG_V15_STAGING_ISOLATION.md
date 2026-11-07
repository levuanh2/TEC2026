# RAG V1.5 — isolated staging design (proposal, nothing created)

Status: DESIGN ONLY (2026-11-08). No Supabase project, Render service, secret, migration or data
was created or changed by this document. Every step below is an owner action with its own approval.

## Why

`agricarbon-api-staging` / `agricarbon-web-staging` (render.yaml) read the HOSTED project
`awazhdqzkktekbwaqiic` (staging CSP `connect-src`, `SUPABASE_*` `sync: false` secrets). Seeding the
synthetic RAG corpus there would write APPROVED knowledge rows into the production database, and
every staging Q&A test would read/write production tenants. RAG_V15_STAGING_RUNBOOK.md §8 therefore
limits staging to an empty corpus. A real staging test of retrieval, citations and the ACTION path
needs its own database.

## Target topology

| Piece | Today | Proposed |
|---|---|---|
| Database | hosted prod `awazhdqzkktekbwaqiic` | NEW Supabase project `agricarbon-rag-staging` (own ref, own keys, same region) |
| API | `agricarbon-api-staging` → prod DB | NEW Render web service `agricarbon-api-rag-staging` → staging DB (or repoint the existing staging API after an explicit decision) |
| Web | `agricarbon-web-staging` | NEW static site `agricarbon-web-rag-staging`, built with the staging `VITE_SUPABASE_*` and API URL |
| Provider | none (strategy B) | DeepSeek key ONLY on the RAG staging API, `RAG_LLM_KILL_SWITCH=true` until a gate run is approved |

Production services and the prod project are untouched by every step.

## Configuration (values filled by the owner; never committed)

API (`agricarbon-api-rag-staging`, rootDir `backend`, same build/start/health as render.yaml):
`PYTHON_VERSION=3.11.9`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PUBLISHABLE_KEY`,
`SUPABASE_DB_URL` (IPv4 session pooler, as on EC2) — all of the STAGING project;
`AGRICARBON_CORS_ORIGINS=https://agricarbon-web-rag-staging.onrender.com`; `RAG_QA_ENABLED=true`;
`RAG_LLM_KILL_SWITCH=true`; provider vars per RAG_V15_STAGING_RUNBOOK.md §1 only when approved
(`RAG_LLM_PROVIDER=deepseek`, `RAG_LLM_MODEL=deepseek-flash`, `DEEPSEEK_API_KEY`, `RAG_LLM_THINKING=disabled`,
`RAG_LLM_MAX_RETRIES=0`, `RAG_LLM_PRICE_*`, quota caps from `infrastructure/llm_quota.py`).
`RAG_D8C_ENABLED` stays unset.

Web: `VITE_API_BASE_URL` (RAG staging API), `VITE_SUPABASE_URL` + `VITE_SUPABASE_PUBLISHABLE_KEY` of the
staging project (never a service key), `VITE_USE_MOCK_DATA=false`, `VITE_AI_QA_ENABLED=true`; headers as
render.yaml with `connect-src` changed to the staging API and `https://<staging-ref>.supabase.co`.

## Migrations (fail fast, one at a time)

1. `python scripts/ci/check_migrations.py` locally (checksums; hash `git show <sha>:path`, not the CRLF
   checkout).
2. Apply the 25 files in `supabase/migrations/` to the staging project IN ORDER, one per command, stop on
   the first error (no `;` chaining): `npx --yes supabase@2.118.0 db push --db-url "<staging session pooler>"`
   or `psql -v ON_ERROR_STOP=1 -f <file>` per file. Never point either at the prod ref.
3. `python scripts/ci/db_audit.py` against staging (RLS on every table, policies, grants).
4. Record the applied version list and compare with the file list.

## Seed (synthetic only)

- Identities/tenant: `scripts/ci/seed_ci_db.py` (fresh-stack only: factor set, demo tenant, QA farmer,
  private buckets, outsider) with the staging env. It refuses an existing user; run once.
- Knowledge: the synthetic AWD / records / weed / injection paragraphs used by
  `rag_llm_benchmark.py` presets, every row titled "TEST FIXTURE — NOT A REAL APPROVED SOURCE", ingested
  through the normal knowledge pipeline and approval guard (no direct SQL bypass), visibility `public`.
- Proposed guard (not implemented): the seed script refuses any `SUPABASE_URL` whose ref is
  `awazhdqzkktekbwaqiic`, and the API refuses to start with `RAG_SYNTHETIC_CORPUS=true` on that ref.

## Rollout and verification (owner, after approval)

1. Create the staging Supabase project; store its keys in Render only.
2. Migrations §, audit, seed §.
3. Create the two Render services (manual deploy, `autoDeployTrigger: off`), deploy PR #41's commit.
4. QA matrix of RAG_V15_STAGING_RUNBOOK.md §3 with the QA farmer: READ intents composed; recommend with
   kill switch on → 503; injection/pesticide → `out_of_scope_question` / `instruction_like_question`;
   manager → 404 on ACTION; outsider → 404.
5. Only with a separate approval and budget: kill switch off for one bounded provider run.

Rollback: kill switch on; `RAG_QA_ENABLED` unset; suspend or delete the two RAG staging services; the
staging project can be paused or deleted. Production is never involved.

## Cost / limits

Supabase: one additional project (free tier pauses after inactivity; a paid tier if staging must stay
up). Render: two more free services (512 MB). Provider: only per approved run (see RAG_V15_EVAL_PLAN.md).

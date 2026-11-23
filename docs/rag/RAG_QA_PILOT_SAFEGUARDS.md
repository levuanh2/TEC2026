# Season Q&A READ-only pilot — rate limit, monitoring and emergency stop

Status: **local/CI only. Production NO-GO.** Every threshold below is a PROPOSAL pending the
owner's decisions A-12 (rate limit) and A-13 (monitoring / on-call). Nothing here was run on
hosted, staging or production.

## 1. Rate limit (A-12)

`POST /v1/crop-seasons/{crop_season_id}/questions`, in `RagQuestionService.answer`:

1. READ-only action-tier lock (PR #92): recommend / what_if / non-ASK → 503
   `action_tier_disabled`. Reads nothing, costs no quota.
2. Supabase Auth verifies the JWT (`reader.user_id()`): invalid, expired, logged-out or revoked
   → 401 `unauthenticated`. Not counted.
3. One question is counted for the **verified user id**. Over the limit → 429
   `question_rate_limited` + `Retry-After: <seconds>`, Vietnamese message
   "Bạn đã hỏi quá nhiều câu trong thời gian ngắn. Vui lòng thử lại sau." Same body for every
   season id (no tenant information; changing the season id does not reset the count).
4. Only then: scope check, season / Carbon / knowledge reads, composition.

| Setting (server env) | Default | Notes |
|---|---|---|
| `RAG_QA_RATE_LIMIT_PER_MINUTE` | 10 | sliding 60 s; integer ≥ 1, else start-up fails |
| `RAG_QA_RATE_LIMIT_PER_DAY` | 100 | sliding 24 h; integer ≥ 1 |
| `RAG_QA_RATE_LIMIT_STORE` | `postgres` | durable + atomic; needs migration `20261106090000` on that database |
| | `memory` | one API process only: N processes allow N × the limit, a restart forgets the counts |

There is no "off". If the store cannot answer (database down, migration missing) every question
is 503 `question_rate_limit_unavailable` — fail closed.

Why per user and not per IP: several farm households can share one network (a cooperative
office, a mobile carrier NAT). An IP limit would block a whole village for one user's burst, and
a single user could still dodge it by switching networks. An optional IP backstop belongs at the
proxy and needs a Caddy build with a rate-limit module (the official `caddy` image has none).

Only allowed questions are recorded (`private.rag_question_events`: user id + timestamp,
pruned after 24 h), so retrying while limited does not extend the wait.

## 2. Signals the API already writes

| Line | Fields | Use |
|---|---|---|
| `access` (logger `agricarbon.access`) | `request_id method path status duration_ms db_calls db_ms` | counts of 200/401/403/404/429/5xx; latency p50/p95; DB round trips |
| `rag_question` (`agricarbon.rag`) | `request_id intent mode status error llm_calls tokens cost llm_ms total_ms tier` | errors by code; `llm_calls`; tier |
| `rag_question_service` | `tier=read_only provider=not_loaded` / `tier=read_and_action ...` | start-up tier |
| `rag_question_rate_limited` | `request_id window retry_after_s` | 429 by window |
| `rag_alert` (ERROR) | `llm_calls_in_read_only` / `action_tier_enabled` | tripwires (§3) |
| `rag_tenant_isolation_violation` (ERROR) | — | security failure |

None of them carries the question, an answer, a JWT, a key, an e-mail or a user id. The crop
season id appears in the access-log path (an opaque UUID). `X-Request-ID` from a client is kept
only if it is 1–64 characters of `[A-Za-z0-9._-]`; otherwise the API generates one, so a client
cannot inject fake fields into these lines.

## 3. Alerts (proposed thresholds; owner decides A-13)

`scripts/ops/rag_qa_log_summary.py` reads these lines (stdin or a file), prints counts and
percentiles, and exits 1 on any alert. No paid monitoring service is needed:

    docker logs --since 15m <api container> 2>&1 | python3 scripts/ops/rag_qa_log_summary.py

| Alert | Condition | Severity |
|---|---|---|
| `llm_calls_in_read_only` | a READ-only `rag_question` line with `llm_calls > 0` | stop Q&A now |
| `llm_calls_nonzero` | any `llm_calls > 0` while READ-only is expected | stop Q&A now |
| `action_tier_enabled` | API started with `tier=read_and_action` | stop Q&A now |
| `tenant_isolation` | any tenant-isolation violation | stop Q&A now |
| `server_errors` | 5xx > 2 % of ≥ 20 questions in the window | investigate; stop if it persists |
| `latency_p95` | p95 > 8000 ms over ≥ 20 questions | investigate (each question is 26–41 sequential statements) |

Who receives the alert and who may stop Q&A: **PENDING (A-13)**. The person needs shell access to
the API host (container env + Caddy). Until A-13 is decided, the pilot must not open.

## 4. Emergency stop (rehearsed locally only)

| Method | What it does | Local measurement | Caveat |
|---|---|---|---|
| Caddy 503 route (`Caddyfile.qa-off`: POST-only matcher on `^/v1/crop-seasons/[^/]+/questions/?$`) | answers 503 `backend_not_configured` at the proxy; the API is untouched | reload ≈ 0.2 s, first 503 ≈ 0.23 s, back ≈ 0.6 s (caddy:2.8.4, 2026-11-21) | POST only, so CORS preflight still reaches the API; never edit production Caddy without the owner; keep the original file to restore byte-identically |
| `RAG_QA_ENABLED=false` | route answers 503 `backend_not_configured` | API healthy again ≈ 11 s (local) | the container reads `--env-file` only at `docker run`: this is a re-create, not `docker restart` |
| `RAG_QA_RATE_LIMIT_PER_MINUTE=1` | throttles without stopping | re-create, as above | not a stop |

The rate-limit migration can be rolled back with
`supabase/rollbacks/20261106090000_rag_question_rate_limit.down.sql` — first set
`RAG_QA_RATE_LIMIT_STORE=memory` or `RAG_QA_ENABLED=false`, or every question is 503.

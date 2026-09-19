# Write-path reliability (P1-A, P1-B)

Status: implemented on `feature/p1-write-reliability` (2026-09-20).

## 1. The invariant

A mutation must never end in the state

    DATABASE_COMMITTED = true  AND  HTTP_RESPONSE = avoidable validation/serialization 500

Before this work every write repository committed at the end of its own
`with self._connection()` block and returned a raw row; FastAPI's
`response_model` check ran only after the route returned — after the commit.
Observed on 2026-09-19: a seeded activity (`recorded_by` NULL) was updated and
committed, then `ActivityWriteResponse.created_by: str` rejected it, so the
client saw a 500 for saved data.

### The pattern

Transactions are owned by the **repository** (the pool/connection context
manager commits on success and rolls back on exception). No route or service
opens a transaction. So the success representation is produced **inside** that
block, through a `prepare` callback the service passes in:

```
with self._connection() as conn, conn.cursor() as cur:
    ... write SQL ...
    row = ... read back ...
    return prepare(row)          # <- validated + serialized here, before commit
```

`schemas.success_payload(Model, raw)` does
`Model.model_validate(raw).model_dump(mode="json")`: the route's own response
model, and the JSON form (UUID, Decimal, datetime, enum all resolved). What the
route returns is therefore plain JSON the route's later `response_model` check
re-validates without being able to fail. If `prepare` raises, the write rolls
back and the client gets an error with nothing saved.

The Carbon route has no `response_model`; there the payload is passed through
`jsonable_encoder` and `json.dumps(..., allow_nan=False)` (exactly what the
response will do) **before `save_calculation` writes anything**, and only the
new calculation id is added afterwards.

Schemas were not weakened to make this pass. The one field that changed
nullability (`ActivityWriteResponse.created_by`, in the previous round) is NULL
in the database for seeded records.

## 2. Mutation endpoint inventory

| Endpoint | Service → repository | Transaction owner / commit | Response built | External side effect | Before | After |
|---|---|---|---|---|---|---|
| `POST /v1/crop-seasons/{id}/activities` | `ActivityWriteService.create` → `PostgresActivityWriteRepository.create` | repository `with`, one tx | in tx (`prepare`) | — | AT_RISK | SAFE |
| `PATCH /v1/activities/{id}` | `.update` → `.update` | repository, one tx (base + subtype) | in tx | — | CONFIRMED_BUG | SAFE |
| `DELETE /v1/activities/{id}` | `.delete` → `.soft_delete` | repository, one tx | 204, no body | — | SAFE | SAFE |
| `PATCH /v1/crop-seasons/{id}/methodology` | `.update_crop_season_methodology` | repository, one tx | in tx | — | AT_RISK | SAFE |
| `POST /v1/carbon/calculate` | `CarbonService.calculate` → `SupabaseCarbonRepository.save_calculation` | **PostgREST: two requests** (calculation, then breakdowns) | before the first insert | — | AT_RISK + NOT_TRANSACTIONAL | SAFE (response); EXPLICIT_ACCEPTED_RISK (see §3) |
| `POST /v1/crop-seasons/{id}/recommendations/generate` | `RecommendationService.generate` → `.save_generated` | repository, one tx (upserts + prune) | in tx | — | AT_RISK | SAFE |
| `PATCH /v1/recommendations/{id}` | `.set_status` → `.set_status` | repository, one tx | in tx | — | AT_RISK | SAFE |
| `POST /v1/crop-seasons/{id}/cv/infer` | `CvService.infer` → `upload_image`, `create_image`, `create_inference` | Storage upload, then tx 1 (image), then tx 2 (inference) | in tx 2 | Storage object (`plant-images`) | AT_RISK + EXTERNAL_SIDE_EFFECT | SAFE (response); EXPLICIT_ACCEPTED_RISK (see §3) |
| `POST /v1/mrv/cases/{id}/exports` (`json`) | `MrvExportService.create` → `PostgresMrvExportRepository.create` | repository, one tx (export + calculation links) | in tx | — | AT_RISK | SAFE |
| `POST /v1/mrv/cases/{id}/exports` (`xlsx`/`pdf`) | snapshot tx, then render: object upload → row tx | two tx + Storage | render row: in tx | Storage object (`mrv-exports`) | AT_RISK + EXTERNAL_SIDE_EFFECT | SAFE (response); EXPLICIT_ACCEPTED_RISK (see §3) |
| `POST /v1/mrv/exports/{id}/render` | `MrvExportService.render` → object upload → row tx | Storage + one tx | in tx | Storage object | AT_RISK + EXTERNAL_SIDE_EFFECT | SAFE |

No other route mutates state (`backend/api.py` is the only router; `main.py`
only mounts it and `/health`). `CvService` also creates a `cv_model_versions`
row once per process (`get_or_create_model_version`); it returns an id, not a
response, and is idempotent by `version_code`.

## 3. External side effects and accepted residual risk

| Side effect | Can roll back? | Compensation | Failure after it | Idempotency |
|---|---|---|---|---|
| MRV artifact upload (`mrv-exports`) | no | row insert (incl. a rejected response) fails → object deleted (best effort; orphan still found by the case-prefix cleanup) | row committed → object is the artifact | new export id per call |
| CV image upload (`plant-images`) | no | **new:** `plant_images` insert fails → object deleted (best effort) | row committed → image reused by sha256 on retry | sha256 per season |
| Carbon calculation + breakdowns (PostgREST) | no (two HTTP requests) | **new:** breakdown insert fails → calculation deleted (breakdowns cascade) | both inserted → complete | `input_hash` unique: same input returns the same id |

Accepted, with reason:

* **Carbon — process crash between the two inserts.** Compensation runs in
  the same process, so a hard crash in that window can leave a `succeeded`
  calculation without breakdowns, which a retry would reuse via `input_hash`.
  Removing the window needs the insert in one DB transaction (psycopg or an
  RPC). Not done here: it changes the persistence path of every Carbon write
  and belongs in its own change. Recorded as a follow-up.
* **CV — image row committed, inference not.** Retry reuses the image (sha256)
  and creates the inference: converges, no duplicate. A crash between upload
  and row insert leaves an orphan object in `plant-images` (no cleanup job
  exists for that bucket).
* **MRV `xlsx`/`pdf` in one call — snapshot committed, render failed.** The
  snapshot is a complete, valid evidence record on its own; a retry creates a
  second snapshot. Deleting a committed snapshot to "undo" it is not done:
  exports are audit records.

## 4. Client retry after an error

With response validation inside the transaction, "500 after a hidden commit"
can no longer come from the response. It can still come from a connection lost
**during `COMMIT`** (commit state unknown). What a retry does then:

| Endpoint | Retry outcome |
|---|---|
| activity create | idempotent — same `idempotency_key` returns the original (`idempotent_replay: true`) |
| activity update | idempotent — the same PATCH sets the same values |
| activity delete | harmless — second call is 404 |
| methodology | idempotent |
| Carbon calculate | idempotent — same `input_hash` returns the existing calculation |
| recommendation generate | idempotent — upsert on `(crop_season_id, rule_code)` |
| recommendation status | idempotent value; `accepted_at`/`dismissed_at` refreshed |
| CV infer | idempotent — sha256 image + model version inference reuse |
| MRV export / render | **duplicate artifact** — new export id per call (accepted: export history, not state) |

## 5. Dead pooled connections (P1-B)

Root cause: `pg_pool` created `psycopg_pool.ConnectionPool` without a `check`.
A connection closed from the server side while idle (Supavisor / network) was
handed out as-is; the first statement raised `psycopg.OperationalError`
(`AdminShutdown` when reproduced by terminating the session).

Reproduction (`tests/test_pg_pool_health.py`): take every idle connection the
pool holds, `pg_terminate_backend()` exactly those sessions from a separate
connection, check out again. Before: `psycopg.errors.AdminShutdown`. After: a
fresh session, and a write transaction (`txid_current()`) succeeds.

Fix: `check=ConnectionPool.check_connection` (psycopg_pool 3.3.1's canonical
health check) on every checkout. A dead connection is discarded and replaced
**before any statement is sent** — the only retry anywhere, and safe for that
reason.

**No blind write retry.** A failure during or after a statement is never
replayed: whether the commit landed is unknown. It reaches the client as a
`503 database_unavailable` envelope (`psycopg.OperationalError`,
`psycopg_pool.PoolTimeout`) with no host, DSN or SQL in the body; the server
log has the context. Whether the client may retry follows §4.

Settings: `min_size=1`, `max_size=8`, `timeout=30 s` unchanged; `max_idle`
(600 s) and `max_lifetime` (3600 s) left at the library defaults — the database
reports `idle_session_timeout = 0` and there is no measured lower bound to tune
them against; the checkout check does not depend on them.

Cost: one round trip per checkout. Measured from a dev machine to hosted
Supabase: checkout + `select 1` median 297 ms → 406 ms. A backend deployed next
to the database pays a few ms. Only the psycopg write/lookup paths use the pool;
the read API goes through PostgREST.

`/health` is deliberately lightweight: it reads the emission-factor YAML and
does not query the database, so it reports process readiness, not database
reachability. Unchanged.

## 6. Tests

From `backend/` (see the backend pytest cwd note):

```
python -m pytest tests/test_write_response_atomicity.py   # real Postgres, rolled back
python -m pytest tests/test_write_response_routes.py      # route/service, fakes
python -m pytest tests/test_pg_pool_health.py             # real Postgres kill-and-reuse + 503 envelope
python scripts/hosted_write_reliability_smoke.py          # hosted, isolated tenant, cleans up
```

`test_write_response_atomicity.py` runs each real repository on a savepoint
inside a rolled-back transaction; `prepare` records that the write SQL ran
(new id / new value) and then raises; the test asserts nothing survived. The
hosted smoke runs the real app in-process, kills only its own pool's sessions
before each write (Supavisor rewrites `application_name`, so no other process's
session can be targeted), and forces each response model to reject.

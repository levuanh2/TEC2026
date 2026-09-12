# Farmer Performance Round 4 — reducing full-content latency

**Scope.** Orchestration and read-path only. No visual redesign, no new
Recommendation rule, no CV model change, no scientific factor change, no RLS
bypass, no service-role shortcut, no fabricated data. Resource-metric math,
Carbon math, Recommendation rule logic, CV inference and activity write
semantics are unchanged.

**Benchmark protocol.** Identical for every number below: QA Farmer
`qa-farmer-fw1` (scope `DEMO-FARM-01`), hosted Supabase, the same machine,
local backend on `:8010`, frontend as a production build behind `vite preview`
on `:5173`. Measured with `web-dashboard/tools/farmer-waterfall.mjs`, which records every
backend request (start/end/duration/bytes/status) plus the backend's own
`Server-Timing` (handler ms and Supabase round-trip count), and three
DOM-defined readiness marks. It takes credentials and the season id from the
environment and contains none itself; raw runs land in the gitignored
`web-dashboard/.qa-screenshots/round4/`, since they are specific to one machine
and one dataset.

---

## 1. Readiness definitions (§24)

Each is a DOM fact, not an impression:

| Mark | Definition |
|---|---|
| **Shell ready** | the Farmer navigation exists — app booted, route resolved |
| **Useful ready** | the season hero/workspace title is visible and quick actions are usable |
| **Full ready** | no request in flight and no skeleton left in the DOM |
| **Settled** | full ready **plus** any deliberately deferred work |

Recommendation generation is deliberately deferred and therefore does **not**
count toward *full ready*; it is reported separately as *settled*. In the final
benchmark no generation runs during a page load at all, so the two marks
coincide — that is the honest reading, not a flattering one.

---

## 2. Result

| | BEFORE | AFTER | |
|---|---|---|---|
| **Home — full content** | **11 379 ms** | **960 ms** (696–2 972 over 5 runs) | **−92 %** |
| **Season — full content** | **9 051 ms** | **1 237 ms** (573–1 497) | **−86 %** |
| Home — useful content | 2 040 ms | 427 ms | −79 % |
| Season — useful content | 2 531 ms | 1 118 ms | −56 % |
| Home / Season — shell | 190 / 182 ms | 291 / 283 ms | unchanged in practice |
| Login → shell | 3 928 ms | 2 430 ms | −38 % |
| Login → full | 15 109 ms | 2 963 ms | −80 % |
| **Supabase round trips / screen** | **64** | **34** | **−47 %** |
| Backend requests / screen | 7 | 6 | −14 % |
| Duplicate requests / screen | 0 | 0 | — |
| Response bytes / screen | 8 338 | 7 525 | −10 % |

Target was 3–5 s for full content on both screens. Both land near **1 s**.

Per endpoint, uncontended and warm:

| Endpoint | BEFORE | AFTER | Supabase calls |
|---|---|---|---|
| `GET /v1/me` | 1 656 ms | 609 ms | 4 |
| `GET /v1/farmer/scope` | 1 297 ms | 156–1 188 ms | 3 |
| `GET .../activities` | 2 250 ms | 562 ms | 11 |
| `GET .../metrics` | 2 062 ms | 500 ms | 12 |
| `GET .../recommendations` | 1 344 ms | 297 ms | 2 |
| `GET .../cv/inferences` | 2 407 ms | 515 ms | 2 |
| `POST .../recommendations/generate` | 9 546 ms | 3 984–4 859 ms | 31 |

---

## 3. What the profile actually showed

Before changing anything, `Server-Timing` was added to every response
(`AGRICARBON_SERVER_TIMING=1`, off by default) exposing handler time, the
number of backend→Supabase round trips, and a per-table breakdown. The Home
waterfall then read:

```
 158→ 1711  1553ms  db=3   GET  /v1/farmer/scope
 161→ 2029  1868ms  db=4   GET  /v1/me
1719→ 3747  2028ms  db=2   GET  .../recommendations
1720→ 8949  7229ms  db=31  POST .../recommendations/generate   <-- full content
1720→ 4426  2706ms  db=1   GET  .../cv/inferences
1720→ 4464  2744ms  db=12  GET  .../metrics
1720→ 4181  2461ms  db=11  GET  .../activities
```

Four distinct causes, in order of size:

1. **Every page load ran recommendation generation.** `useRecommendations`
   issued the GET *and* a `POST .../generate` on mount. That POST is 31
   Supabase round trips and measured 7.2–9.5 s — on its own it was the
   full-content number for both screens.
2. **Every request rebuilt its Supabase client.** `create_client` (~210 ms) +
   `postgrest.auth` (~230 ms), and the fresh connection pool made that
   request's first query pay a cold TLS handshake (~390 ms vs ~150 ms warm) —
   roughly **800 ms of fixed overhead per request**, on all six.
3. **Every psycopg statement opened its own Postgres connection** (~700–740 ms
   to hosted Supabase). The CV preview — one `select` returning a handful of
   rows — cost 2 407 ms, of which 313 ms was the query. Generation paid it
   once per rule plus once for the prune.
4. **Sequential read chains** inside `activities` / `metrics`: a per-batch
   `activities` loop, `profiles` fetched after the detail tables, and
   `carbon_calculations` fetched after the whole activity chain.

---

## 4. Changes

### Recommendation generation is no longer part of loading a page (§6–§9)

Strategy: **C (staleness-based) with an explicit A (user-triggered) control**,
generation deferred (B) so it can never block.

* A page only ever `GET`s the stored recommendations.
* A refresh runs when the farmer presses **"Cập nhật khuyến nghị"**, or on its
  own **after** the section has rendered, and only when the stored set is
  genuinely out of date: nothing stored, older than `RECS_STALE_AFTER_MS` (6 h),
  or this season's records changed in this session.
* Idempotency is unchanged — the existing `on conflict (crop_season_id,
  rule_code)` upsert plus prune. A farmer's accept/dismiss is still preserved
  across regeneration. One click produces exactly one run (asserted in the real
  E2E), and Home + Season sharing one cache key means two mounted sections
  share a single run.
* Failure is scoped to the section: stored recommendations stay on screen, the
  message is "Không thể cập nhật khuyến nghị lúc này." with a retry, and the
  page never shows a page-wide error.

### Per-caller Supabase client reuse (`infrastructure/supabase_clients.py`)

A client is a connection pool plus one fixed `Authorization` header, so it is
cached on the **exact access token**. Two requests with the same token are
indistinguishable to PostgREST, which validates that token and applies RLS on
every request; a cached client is bound once, at construction, and is never
re-authenticated with a different token. The cache is bounded (32) and
time-limited (10 min), and construction is single-flight per token so the
several reads a page fires at once do not each build their own.

Three follow-on correctness fixes came out of this:

* **Dropped keep-alive connections are retried once.** Supabase closes idle
  connections; httpx then raises `RemoteProtocolError` on the next read that
  picks one. These reads are idempotent, so the stale pool is discarded and the
  read reissued — rather than failing a page section. (This failure was present
  before pooling too, just rarer.)
* **Eviction no longer closes clients.** Closing on eviction closed sockets out
  from under live requests (`RuntimeError: Cannot send a request, as the client
  has been closed`). The reference is dropped instead; the last request holding
  it releases it.
* **`SupabaseCropAccessChecker` no longer rebinds a shared client.** It was a
  singleton calling `.auth(token)` on one shared client immediately before each
  query, so two concurrent callers could interleave
  `auth(A) → auth(B) → execute(A)` and run A's query with B's JWT. It now takes
  a per-token client. This was a pre-existing latent cross-tenant risk.

### Pooled Postgres connections (`infrastructure/pg_pool.py`)

The CV, write and recommendation repositories share one bounded pool
(`psycopg_pool`, min 1 / max 8) instead of connecting per statement. Trust and
transaction semantics are identical — same backend-only connection string, and
`pool.connection()` commits on success and rolls back on exception exactly as
`with psycopg.connect(...)` did. If `psycopg_pool` is absent the module falls
back to connect-per-statement, so it is a performance dependency, never a
correctness one.

### One transaction per generation run

`PostgresRecommendationRepository.save_generated` upserts every rule and prunes
in a single transaction, instead of one connection per rule plus one for the
prune. Besides the latency, the run is now atomic: a reader sees the previous
run or this one, never half of each.

### Read-path fan-out

* `_activities`: the season gate and `production_batches` overlap (the gate's
  result is still read first, so an invisible season raises before any batch row
  is returned), and the per-batch loop became one `IN` query.
* `activities()`: `profiles` runs alongside the per-type detail reads.
* `_metric_totals`: activities and `carbon_calculations` run concurrently.
* `_concurrent` now copies the caller's context into its workers, so reads
  issued in parallel are still attributed to the request that made them.

### Login (§22)

`/v1/farmer/scope` now starts as soon as a session exists, alongside `/v1/me`,
instead of after it. Role resolution is untouched — routing still comes from
`/v1/me`, never from the prefetch — and the prefetch is skipped once the cached
role hint says the user is not a farmer, so a manager's session costs nothing
extra.

### Two bugs found while measuring

* **A prefetch resolving before its reader mounted was lost.** `useQuery`
  subscribed in an effect, so a notification landing between render and
  subscription was dropped and the section sat in its skeleton forever —
  reproduced at roughly one login in five once the scope read moved to login
  time. `useQuery` now subscribes through `useSyncExternalStore`, which re-reads
  the snapshot immediately after subscribing.
* **The journal detail drawer held a snapshot.** Editing an activity
  invalidates and refetches that season's reads, but an already-open drawer kept
  showing pre-edit values indefinitely. It now tracks the open row by id and
  re-resolves it from the current list (and closes itself if the row is gone).

---

## 5. Content classification (§5)

| Class | Sections | Treatment |
|---|---|---|
| **Critical, above the fold** | viewer/scope, current farm/plot/season, season hero, quick actions | fetched immediately; *useful ready* waits on these only |
| **Important, deferred** | recent activities, performance summary, recommendation preview, CV preview, Carbon status | own fetch, own skeleton, own error; each resolves independently and none blocks another |
| **Expensive / optional** | recommendation generation, heavy rollups, full history lists | never part of a page load |

Every section fetches independently and fails independently (§27) — there is no
`Promise.all` gating a page on its slowest part (§26), which is why a 4–9 s
generation can no longer hold anything hostage.

---

## 6. Composition endpoints — evaluated, not added (§11, §12)

`GET /v1/farmer/home` and `GET /v1/farmer/crop-seasons/{id}/overview` were
evaluated against the measurements, and **not added**:

* Home's remaining requests already run concurrently and its long pole is a
  single ~560–750 ms read, so collapsing six requests into one saves in the low
  hundreds of milliseconds against a 960 ms full-content number that is already
  well inside the 3–5 s target.
* The real remaining redundancy is that `/activities` and `/metrics` each read
  the same batches, activities, detail tables and profiles — 23 of the 34 round
  trips per screen. A composition endpoint would compute the activity set once
  and cut that to ~12. That is a worthwhile **database-load** reduction and the
  obvious next step if fan-out becomes the constraint, but it is not a latency
  fix today.

The brief's own rule is to add one only if measurement proves a benefit. It does
not, so the API surface is unchanged.

## 7. Response sizes and preview limits (§15–§18)

Measured rather than assumed. A whole Home screen transfers **7 525 bytes**
across six responses; the largest is `/activities` at 3 858 B. Payload size is
not a contributor at this data volume, and — importantly — trimming it would not
reduce backend work either, because `/activities` pagination is applied *after*
the rows are read. Adding `limit` parameters would cut bytes while leaving the
round trips (the actual cost) untouched, and would split Home's and the
Journal's reads into two different cache keys, increasing request count.

The genuine scaling fix is database-side ordering and limiting in the read
repository, so a long-running season's journal never has to be read in full to
show five rows. That is recorded here as a known scaling item; it was not needed
to reach the target and is not a latency problem at current volumes.

## 8. Cache keys, invalidation and prefetch (§19–§21)

* **Keys** all come from one `keys` object in `farmer/data.ts`, derived from ids
  only — no query strings, so the same logical request cannot produce two keys.
  Measured duplicate requests per screen: **0**, in dev and in preview.
* **Invalidation** after a write touches only that season's derived reads
  (activities, metrics, recommendations, generation) and never viewer identity,
  the farm/plot/season hierarchy, or organization identity. A write also marks
  that season as changed, which is what makes its recommendations regenerate
  without waiting out the 6 h staleness window.
* **Prefetch** stays bounded: scope on session, at most scope + one season read
  per nav target on hover/focus, and one season's metrics + activities on a
  season-card hover. No prefetch triggers generation.

## 9. Dev vs production preview (§23)

| | dev (StrictMode) | preview |
|---|---|---|
| Home full content | 923–1 302 ms | 696–2 972 ms |
| Season full content | 807–2 983 ms | 573–1 497 ms |
| Requests / Supabase calls | 6 / 34 | 6 / 34 |
| Duplicate requests | 0 | 0 |

StrictMode's double effect is absorbed by the cache's in-flight dedupe, so dev
and preview issue exactly the same requests. StrictMode was not disabled.

## 10. Security (§29)

Re-verified against hosted Supabase with real tokens after every change:

| Check | Result |
|---|---|
| Farmer → own `DEMO-FARM-01` | 200 |
| Farmer → `DEMO-FARM-02` / `DEMO-FARM-03` | 404 (not 403 — existence is not disclosed) |
| Farmer `/v1/farmer/scope` | only `DEMO-FARM-01`, 2 plots, 2 seasons |
| Unauthenticated `/v1/me`, `/scope`, `/farms/{id}`, `/recommendations` | 401 |
| 40 interleaved concurrent `/v1/farmer/scope` requests, farmer + manager tokens, 12 at a time | each identity saw only its own scope, every time |

The last row is the one that matters for client reuse, and is also covered by
unit tests: same token reuses one client, a different token never borrows it, a
cached client is never rebound, the cache is bounded, and eviction never closes
a client a request may still hold.

## 11. Pool lifecycle

* **Supabase clients**: bounded at 32, 10-minute TTL, single-flight
  construction per token. Eviction drops the reference without closing, so a
  request still holding a client keeps working and the sockets go when the last
  holder finishes.
* **Postgres**: one `psycopg_pool.ConnectionPool` per connection string,
  `min_size=1`, `max_size=8` — well under uvicorn's 40-thread pool, and the
  read path never touches it at all. Opened lazily on first use.
* **Shutdown**: a FastAPI `lifespan` hook closes every Postgres pool and every
  cached Supabase client, so a stopping process hands its connections back
  instead of leaving them to a server-side timeout.
* **Checkout safety**: `pg_pool.connection()` is a plain `with` on both
  branches, so the connection returns on success, on exception, and on
  generator teardown. Covered by tests that assert the pool is whole again
  after a failing block, that `max_size * 5` consecutive failures cannot
  exhaust it, and that concurrent users never exceed `max_size`. Those tests
  were verified to go **red** against a deliberately leaking implementation.

## 12. Tests

| Suite | Result |
|---|---|
| backend pytest | **284 passed** (was 263; +21) |
| web vitest | **132 passed** (was 117; +15) |
| `tsc -b` | clean |
| `vite build` | pass |
| Farmer Playwright (mock) | pass |
| Management Playwright (mock) | pass |
| real Farmer data / write / CV / recommendations E2E | pass |
| real Management E2E (2 specs) | pass |

New coverage: deferred generation (no generation during a page load; one click
= one run; the page stays usable while it runs), the staleness predicate that
decides regeneration, client reuse and cross-token isolation, single-flight
construction, dead-connection retry, eviction safety, one-transaction
generation, the lost-update invariant behind `useQuery`, and the **two-season
quick-entry picker** — the mock fixture now has two active seasons like the real
QA farmer, so "Ghi nhanh → Chọn vụ → pick one → the form opens for *that*
season" is exercised (the gap flagged in the previous round).

No QA rows were left on hosted Supabase: verified zero `QA-` marked activities
after the write E2E.

### Red/green verification

Where a test claims to be a regression test, it was checked against the broken
code:

| Regression | Red on the old code? |
|---|---|
| journal drawer showing a stale snapshot | **yes** — both drawer tests fail against the `useState<Activity>` version |
| pooled connection not returned after a failure | **yes** — four pool tests fail against a deliberately leaking `connection()` |
| `useQuery` losing a pre-mount update | **no — not reproducible in jsdom** (see below) |

The `useQuery` race cannot be reproduced under test: React flushes passive
effects synchronously inside `act`/`flushSync`, so the gap between commit and
effect — the whole basis of the bug — does not exist there. Verified directly
with a probe that printed `render -> passive-effect -> after-flushSync`. Three
different arrangements (flushSync, a sibling layout effect, plain render) all
passed against the old implementation, so none of them is shipped as a
regression test pretending otherwise. What is covered instead:
`src/farmer/data.test.ts` asserts the store invariant the fix relies on (a
change that lands before a subscriber attaches is still visible to it), and
`src/farmer/data.dom.test.tsx` renders `useQuery` against prefetched reads. The
fix itself was verified in a real browser: the Home hero hung on roughly one
login in five before, and 6/6 logins were clean after.

## 13. Confirmation benchmark after stabilization

Re-measured after the review changes (shutdown hook, simplified pool
acquisition, extra tests), same protocol, 7 runs:

| Screen | Median | Min | Max |
|---|---|---|---|
| Home — full content | 1 639 ms | 1 027 ms | 14 235 ms |
| Season — full content | 1 458 ms | 1 195 ms | 4 078 ms |

Requests (6) and Supabase round trips (34) were **identical in every run** —
the code-level invariant did not move. The 14 s outlier was upstream: in that
run every request's handler time tracked its Supabase wait almost exactly
(`/metrics` 8 609 ms handler for 12 calls totalling 18 188 ms of DB wall), with
the same call counts as the fast runs. A control measurement taken at the same
time — a single `select` issued straight to PostgREST with no backend in the
path — ranged 0.30–0.90 s across six samples, confirming the upstream was
jittery rather than the backend regressing.

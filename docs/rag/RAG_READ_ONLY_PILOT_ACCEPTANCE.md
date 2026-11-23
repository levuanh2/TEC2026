# RAG READ-only pilot — acceptance and release gate (2026-11-21)

Status: **local acceptance PASS; production NO-GO.** Production stays NO-GO until every mandatory
condition in §9 has evidence and a valid owner approval. Nothing was merged, deployed, changed on
hosted, re-configured in production, re-pinned, back-filled or sent to a model provider. E1, E4,
dev3-01 stay OPEN; D1, D6 stay BLOCKED.

**What the pilot is:** the READ tier answers with **fixed templates** filled from the season's own
recorded data (explain, data gaps, compare, evidence). It is not a conversational AI and gives no
action advice. A pilot can validate safety, authorization, tenant isolation, missing-data messages
and the non-MRV caveat — not usefulness as an assistant.

Companion of `RAG_V15_PRODUCTION_READINESS_2026_11.md` (defines A1–A15). Repository governance and
independent human review remain owner-controlled release prerequisites; their details are kept outside git.

## 1. PRs and CI

At the acceptance runs (2026-11-21):

| PR | Head | CI | State |
|---|---|---|---|
| #92 READ-only tier lock (`fix/rag-read-only-tier-lock`) | `c71f07e` | 17/17 SUCCESS | OPEN Draft |
| main / integrate/rag-v15 | `63ae678` / `5f7e730` | — | unchanged |

Update 2026-11-24 (no acceptance run was repeated; §3 results belong to `c71f07e`):

| PR | Head | CI | State |
|---|---|---|---|
| #92 | `ef6b9a2` (`efc0f00`, `ef6b9a2`: test inputs only) | 17/17 SUCCESS | OPEN Draft |
| #95 per-user rate limit + monitoring, stacked on #92 | `d69550e` | 17/17 SUCCESS | OPEN Draft |
| this documentation PR | replaces #94 (to be closed without merging), which replaced #93 | — | Draft |
| main / integrate/rag-v15 | `63ae678` / `5f7e730` | — | unchanged |

#92 commits: `abfe640` lock + 45 tests → `3e6c45d` the two flags documented → `c71f07e` staging
runbook QA matrix corrected (it still said recommend → `generation_unavailable`/404; with the lock
it is 503 `action_tier_disabled` for every caller). That last fix came from a read-only side check
of the docs against the code, re-verified by hand.

### 1.1 Lock review

| Question | Answer |
|---|---|
| Can recommend/what_if pass the lock? | No. The refusal is the first statement of `RagQuestionService.answer`, before scope, reads, Carbon or retrieval. |
| Does a misconfigured provider open the action tier? | No. Unless `RAG_QA_ACTION_TIER_ENABLED` is exactly `true`, provider settings are never loaded (verified live, run B). |
| Is the web flag only cosmetic? | Yes. `VITE_AI_QA_ACTION_ENABLED` hides the option; the server refuses direct API calls either way. |
| Errors / timeout | 401 no/garbage/revoked token, 404 out of scope, 422 malformed, 503 lock or feature off (exercised in the runs below). UI timeout 45 s with retry only on the user's click: code constant `QUESTION_TIMEOUT_MS`, covered by the web unit test `aiQuestions.dom.test.tsx` (timer advanced past 45 s → "Quá thời gian…" → "Thử lại"); not exercised in the browser runs. |

## 2. Test environment (isolated, no shared database)

- Supabase CLI 2.118.0 project `tec2026-pilot` (ports 5662x), the 26 migrations of main,
  `db_audit.py` PASS, CI seed (`seed_ci_db.py`). The worktree had no `backend/.env`; every script
  refuses a non-127.0.0.1 target. The shared staging/production project was never contacted.
- Identities: local CI farmer (DEMO-FARM-01), demo HTX manager, an outsider without membership.
  Random local passwords, never printed or stored in git.
- Backend pilot config: `RAG_QA_ENABLED=true`, `RAG_LLM_KILL_SWITCH=true`, action tier unset, no
  model provider configured.
- Web build: `VITE_AI_QA_ENABLED=true`, action flag unset (bundle: `!0` / `!1`).

### 2.1 Fixture setup vs. the no-mutation checks

The **fixture setup** writes on purpose, through the app's own API, **before** any acceptance window:
the manager creates one plot, the farmer starts one empty season, records its methodology and runs
one Carbon calculation (892.43 kg CO2e, reproduced identically on a fresh stack). The seed has no
Carbon result, so without this the non-MRV caveat could not be exercised.

Each **acceptance window** then takes a content hash of all 44 tables in `public` and `private`
before and after: **0 tables changed** in every window (A, B, Carbon). The Q&A requests write
nothing; only the setup does.

## 3. Results (recounted from the raw evidence files)

| Run | What | Result |
|---|---|---|
| API A | pilot config, direct API, farmer/manager/outsider | **31/31 PASS**; 44 tables unchanged |
| API B | `RAG_LLM_PROVIDER=deepseek`, fake key, unreachable base URL, `RAG_QA_ACTION_TIER_ENABLED=1` | **31/31 PASS**; `tier=read_only provider=not_loaded`; 0 quota/provider log lines; 44 tables unchanged |
| API Carbon | same checks on the season with a Carbon result | **30/30 PASS**; answer shows 892,43 (= trusted fact) and "chưa đạt yêu cầu MRV, không dùng làm số liệu tín chỉ carbon"; 44 tables unchanged |
| Browser | Chromium, no trace/video | **20/20 PASS** (19 + Carbon caveat at 390 px) |
| Backend authorization (real DB, real JWT/RLS) | route DB tests, tier lock, positive auth, route inventory, retrieval DB, P0 policies | **154 passed**, 0 skipped |
| Model calls | `rag_question` log lines | 46 (A) + 21 (B) + 147 (UI/Carbon) lines, **all `llm_calls=0`**; browser: **0** provider requests |
| Rollback A10 | restart without `RAG_QA_ENABLED`; web rebuilt with the panel off | healthy in **11 s**, then 503 `backend_not_configured`; web build 15 s, `const mn=!1` (same as the live bundle) |
| Caddy emergency stop | §5.3 | **20/20 PASS**; off in ~0.2 s, back in ~0.6 s |

Covered checks: READ intents composed (`llm_calls 0`, `persisted false`, no recommendations, no
what-if); no number outside the trusted facts; empty corpus → `insufficient_evidence` with 0
citations; recommend/what_if → 503 `action_tier_disabled`, identical in and out of scope; 6
malformed shapes → 422; action wording inside a READ intent stays composed; other farm of the same
HTX → 404; unknown season → 404; empty journal → data gaps listed without invented numbers; manager
READ on two farms; outsider → 404 / no panel; signed-out token → 401; farmer sign-out then manager
sign-in → no previous answer; 390 px layout; "mẫu cố định" disclosure; typed action question shows
"Giai đoạn thử nghiệm chưa có gợi ý hành động…" and is sent as a READ intent.

Harness bugs found and fixed during the run (not product bugs): a boolean `completeness.carbon` was
counted as a Carbon number, and the unit "CO2e" was read as the number 2.

Expected console noise in the browser: CV routes 503 (no model on the machine) and 404 for the other
farm's season.

Not covered: the repository spec `ai-qa-real.spec.ts` as-is (it expects a synthetic approved corpus);
a separate staging project; production.

Evidence: outside git (`AgriCarbon/pilot-acceptance-2026-11-21/`, `MANIFEST.sha256` verified, 0
mismatches). It contains test identities and screenshots, so it stays out of the repository.

## 4. A1–A15

PASS requires reproducible evidence; nothing is PASS because a report says so.

| # | Item | Status | Evidence / reason |
|---|---|---|---|
| A1 | #92 merged after an independent human review, every required review and check satisfied | **BLOCKED** | owner-controlled prerequisite (A-3) |
| A2 | main CI 17/17 at the merge SHA | **NOT RUN** | not merged; PR head 17/17 is necessary, not sufficient |
| A3 | Owner decisions A-0, A-1 recorded | **BLOCKED** | owner |
| A4 | Read-only hosted check | **BLOCKED** | owner approval A-2; SQL ready (§6) |
| A5 | Isolated QA incl. logout/switch, 390 px, empty/error/loading | **PASS (local)** | §3 |
| A6 | Backend route/auth evidence on that stack | **PASS** | 154 passed |
| A7 | No-provider assertion | **PASS local / NOT RUN production** | §3; production env names checked by the owner (§6) |
| A8 | Production direct-API smoke incl. latency | **NOT RUN** | §7.3 defines it |
| A9 | Web build flags | **PASS local / NOT RUN production** | local bundle `!0`/`!1` |
| A10 | Rollback rehearsed (isolated) | **PASS** | §3, §5.3 |
| A11 | Privacy notice in the panel | **BLOCKED (owner confirms text)** | panel: "Câu trả lời chỉ dùng số liệu đã ghi nhận của vụ và tài liệu đã được duyệt. Hệ thống không lưu câu hỏi." |
| A12 | Request volume control | **BLOCKED** | code in #95 (Draft); values and store path are owner decisions; §5.1 |
| A13 | Alert sink + on-call person | **BLOCKED** | owner decision; §5.2 |
| A14 | Empty-season output | **PASS** | API F-EMPTY-*, UI-F10 |
| A15 | Decision notes stored in `docs/rag/` | **NOT RUN** | decisions PENDING |

PASS 4 (A5 local, A6, A10, A14) + the local halves of A7 and A9; BLOCKED 6; NOT RUN 3 + the
production halves of A7 and A9.

## 5. Rollout safeguards (proposals, PENDING owner approval)

### 5.1 Request limits

On main (2026-11-21 and still on 2026-11-24): no rate limit on any API route; `llm_quota.py` limits model
calls only, so it never runs in READ-only mode. Since 2026-11-23 Draft #95 implements the API-layer row
below (per verified user, sliding windows, 429 with `Retry-After`, fail-closed 503); the proxy row stays an
optional backstop. The official Caddy 2.8.4 image has **no rate-limit module** (checked with `caddy
list-modules`), so a Caddy limit needs a custom build.

| Layer | Key | Pilot limit | Notes |
|---|---|---|---|
| API, questions route | verified JWT `sub` | 10 / minute and 100 / UTC day per user | primary control: farmers of one HTX may share one public IP; only authenticated requests count |
| Proxy backstop | client IP | 120 / minute on the route | generous because of shared HTX NAT; needs a Caddy build with a rate-limit module or another proxy |

A limit answers 429 with `Retry-After` and a Vietnamese message; the UI needs specific copy for 429
(today it would show the generic "Hệ thống chưa trả lời được…"). Dashboards keep apart: 429 (limit,
healthy), 5xx (backend error), 401 (session), 503 `backend_not_configured` (feature off), 503
`action_tier_disabled` (lock, healthy). No automatic client retry exists.

### 5.2 Monitoring and alerts (Phase 2)

Log lines exist and carry no question text, answer text or personal data; keep it that way.

| Signal | Source | Alert |
|---|---|---|
| 5xx on the route | `access … /questions status=5xx` | > 1 % over 15 min, or any 500 |
| latency | `access … duration_ms` on the route | p95 above the A8 baseline + 50 % (no fixed number before A8, §7) |
| model call | `rag_question … llm_calls=` ≠ 0 | any line → incident |
| tier | startup `rag_question_service tier=` | `read_and_action` while READ-only → incident |
| tenant isolation | `tenant_isolation_violation` | any → incident, stop the feature |
| failures | `rag_question … status=error error=` (`None` = an auth failure, seen as 401 in the access line) | daily review; `not_found` spikes per user = possible probing |

Who receives alerts and who may switch the feature off: **PENDING (A-13)**. Technically it must be
someone with access to the production proxy/API host.

### 5.3 Emergency stop — Caddy 503, rehearsed in isolation

Snippet tested (Caddy 2.8.4 container in front of the local API):

```caddyfile
@qa_post {
	method POST
	path_regexp qa ^/v1/crop-seasons/[^/]+/questions/?$
}
handle @qa_post {
	header Content-Type application/json
	header Access-Control-Allow-Origin {http.request.header.Origin}
	header Vary Origin
	respond `{"detail":{"error":{"code":"backend_not_configured","message":"Trợ lý hỏi đáp chưa được bật cho hệ thống này."}}}` 503
}
handle {
	reverse_proxy <api upstream>
}
```

Results (20/20): reload 219 ms, first 503 after 234 ms; explain/recommend/what_if → 503 JSON with
the CORS origin; variants (trailing slash, query string, double slash, dot segment, `%71uestions`)
→ 503, encoded slash / upper case → 404, none answered; CORS preflight still answered by the API
(POST-only matcher); season read and `/health` unaffected; restore reload 203 ms, answers again after
609 ms, file byte-identical to the original; a broken config is rejected and the running config keeps
serving.

**Limits:** the production Caddyfile was not read (no host access). The snippet is safe only when
placed in the same site block around the existing `reverse_proxy` exactly as above, after
`caddy validate`, a backup copy and a `caddy adapt` diff — and rehearsed once on a copy of the real
file before it is ever needed. In production, `Access-Control-Allow-Origin` must be the production
web origin, not the request's Origin. The API-level stop (remove `RAG_QA_ENABLED`) needs the
container to be **re-created** (its env file is read at `docker run`), not just restarted.

## 6. Hosted verification package — PREPARED, NOT EXECUTED

Owner approval A-2 required. Read-only session (`PGOPTIONS='-c default_transaction_read_only=on'`),
one transaction ending in `rollback`; no role, grant or data is created. Dry-run on the local stack:
every statement ran (6.4 included).

```sql
begin read only;
-- 6.1 migration history and 20261105090000
select version, name from supabase_migrations.schema_migrations order by version;
select exists (select 1 from supabase_migrations.schema_migrations where version = '20261105090000') as m026_recorded;
select to_regprocedure('private.readable_crop_ids()') is not null as m026_function_present;
select tablename, policyname from pg_policies where schemaname = 'public' and qual ilike '%readable_crop_ids%' order by 1, 2;
-- 6.2 knowledge corpus (pilot requires 0 approved)
select status, count(*) from public.knowledge_documents group by status order by 1;
select status, count(*) from public.knowledge_sources group by status order by 1;
select count(*) as chunks from public.knowledge_chunks;
-- 6.3 READ-only dependencies
select c.relname, c.relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relname in ('knowledge_sources','knowledge_documents','knowledge_chunks');
select has_function_privilege('anon', 'public.match_knowledge_chunks_lexical(uuid,text,integer)', 'execute') as anon_can_retrieve;
select count(*) as stored_m05_recommendations from public.recommendations;
select count(*) as carbon_results, count(*) filter (where mrv_compliant) as mrv_compliant_results from public.carbon_calculations;
-- 6.4 tenant scope of the QA accounts, no passwords (in psql first run: \set qa_emails '{"a@x","b@y"}')
select u.email, o.organization_code, om.role, om.ended_at
  from auth.users u
  left join public.organization_memberships om on om.user_id = u.id
  left join public.organizations o on o.id = om.organization_id
 where u.email = any(:'qa_emails'::text[]) order by 1, 2;
select u.email, f.farm_code, fm.farm_role
  from auth.users u join public.farm_members fm on fm.user_id = u.id join public.farms f on f.id = fm.farm_id
 where u.email = any(:'qa_emails'::text[]) order by 1, 2;
rollback;
```

Expected for GO: history equals the repository and says whether `20261105090000` is applied; approved
documents = 0; RLS on; `anon_can_retrieve` false; `mrv_compliant_results` 0; each QA account has
exactly the intended HTX/farm scope and no ended membership is relied on.

Production configuration, names only: on the API host the env file lists only `RAG_QA_ENABLED` and
`RAG_LLM_KILL_SWITCH` among `RAG_*`/`GEMINI_*`/`DEEPSEEK_*`; the container log shows
`tier=read_only provider=not_loaded`; the public web bundle shows the flags `!0`/`!1`.

**Verified vs. only recorded:**

| Fact | Status |
|---|---|
| main/integrate heads, PR states, CI | verified today |
| Live web bundle has the panel compiled off (`index-BqZEk4VJ.js`) | verified today (public assets) |
| API `/health` 200 | verified today |
| Hosted migration history = 25 ending `20261104090000`; whether `20261105090000` is applied | **recorded only** (2026-11-05) / **unknown** |
| Hosted approved knowledge documents = 0 | **recorded only** (2026-10-06 / 11-07) |
| API env has no `RAG_*` | **recorded only** (2026-11-13 deploy) |
| QA identities and their scope | **recorded only** (2026-09); passwords never stored |
| M05 signals on hosted seasons | **recorded only** (none, 2026-09-28) |

## 7. Latency (analysis only; no code changed)

### 7.1 Measured locally (Server-Timing, 6–7 requests per intent)

| Season | Intent | DB statements | Local p50 |
|---|---|---|---|
| seeded (7 activities) | explain / data_gap / evidence | 41 | ~230 ms |
| seeded | compare | 40 | ~235 ms |
| Carbon fixture (0 activities) | explain / data_gap / evidence | 27 | ~190–220 ms |
| Carbon fixture | compare | 26 | ~205 ms |
| any | recommend (locked) | **0** | ≤ 15 ms |

Per request: `crop_seasons` read **8 times**, `plots` 3, `farms` 2, `production_batches` 2,
activity detail tables 2 each, `profiles` 2, one Auth `get_user` call, and the retrieval RPC runs for
explain/data_gap/evidence even though fact intents cite no document.

### 7.2 Critical path model (not a production measurement)

A local TCP proxy added a fixed 69 ms each way (138 ms per round trip) between the API and the
database/API gateway. Result: **≈ 30–31 sequential round trips** on every READ intent (p50 ≈ 4.3–4.5 s
in the model vs ~0.2 s without delay), i.e. the reads are almost all sequential. This counts round
trips on the critical path; it does not predict production latency (TLS, pooler, server load and the
real network differ).

Code analysis (side review; key claims re-verified in the code):
- `comparison_seasons` is built for **every** intent (`context.py`), not only `compare`;
- it calls `metrics()` once per comparison season — an N+1 of up to 3 × (5–11) statements on plots
  with history (not present in the local data, so the worst case is unmeasured); a bulk
  `metrics_for_seasons` already exists in `read_repo.py` but is not used here;
- `user_id()` makes an extra Auth round trip after the JWT was already validated.

Changes that keep authorization identical and could be proposed later: build comparison data only
for `compare`; use the bulk metrics read; reuse the season/lineage read within one request; skip the
retrieval RPC for fact intents. **Not acceptable:** reading with the service role and filtering in
Python, caching across requests or tenants, or skipping the season → plot → farm → org scope check.

### 7.3 Production smoke criteria (PENDING owner approval, part of A8)

With one QA farmer, after the feature is enabled for the QA cohort only: 20 sequential explain + 10
data_gap + 10 compare requests on one season with history and one without, plus 5 recommend (must be
503). Record p50/p95 per intent from the access log (`duration_ms`) and `db_calls`. Proposed GO
threshold for the QA pilot: p95 ≤ 8 s with 0 errors; above that the owner decides between accepting
it for the QA cohort, the read-path changes of §7.2, or moving the API next to the database. No
threshold is set from local numbers.

## 8. Rollout outline

1. Owner decisions and an independent human review → merge #92, then #95 (A1, A2).
2. Hosted read-only check §6 (A4).
3. Production configuration: API `RAG_QA_ENABLED=true`, `RAG_LLM_KILL_SWITCH=true`, no provider or
   action variables, container re-created; web `VITE_AI_QA_ENABLED=true` only; Caddy stop snippet
   prepared and rehearsed on a copy of the real Caddyfile (A7, A9).
4. Smoke §7.3 with QA identities only, monitoring live (A8, A12, A13).
5. Only then may "READ-only pilot GO for the QA cohort" be proposed to the owner.

Rollback at any step: Caddy 503 (seconds) → API flag removal with container re-create → web rebuild
with the panel off (Cloudflare may serve the old `index.html` for up to 300 s). The Q&A path persists
nothing, so there is no data rollback.

## 9. Final conditions before READ-only opens on production

All of: A1 + A2 (#92 and #95 merged through an independent human review, CI green at each merge SHA); A3 + A15
(A-0, A-1, A-12, A-13 decided and recorded); A4 (hosted check as expected); A7 + A9 on the production
configuration; A11 confirmed; A12 limit in place or explicitly accepted for the QA cohort; A13 person
named; A8 smoke passed. Until then: **production NO-GO**.

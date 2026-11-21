# RAG V1.5 — Production readiness and phased launch (2026-11)

Date: **2026-11-21**. Author: Claude Code session for the owner (levuanh2). Audit only: nothing here
merges, deploys, applies a hosted migration, re-pins, backfills, approves a document or calls a paid
model. **E1, E4 and dev3-01 stay OPEN. D1 and D6 stay BLOCKED.** A green CI (17/17) is never read
as production-ready in this report.

**Status update 2026-11-21:** local READ-only pilot acceptance is recorded in
[RAG_READ_ONLY_PILOT_ACCEPTANCE.md](RAG_READ_ONLY_PILOT_ACCEPTANCE.md) (#92 head `c71f07e`, CI 17/17;
A1–A15 status, latency risk, rollback rehearsal). Production remains **NO-GO**.

The question this report answers:

> **What exactly is still missing to open READ-only on production, and after that real AI
> Recommendation?**

Short answer:

- **READ-only (Phase 2)** needs no M7 work and no Draft migration. It is blocked by **one small code
  change (the server-side action-tier lock, Draft PR #92, this round)**, **a valid review path for
  the guarded files** (governance, §9), **one owner-authorized read-only hosted check**, **isolated
  QA evidence** (§6) and **the owner's choice of what the pilot is meant to test** (safety only, or
  usefulness: READ answers are fixed templates, §3.4).
- **Scientific RAG (Phase 3)** is **NO-GO** and cannot become GO through code: there is no approved
  real document anywhere, no appointed expert (D6/E4), no rights clearance for the main scientific
  sources (D1/E1), no real verifier key, and none of the M1–M7 migrations is on hosted.
- **Real AI Recommendation (Phase 4)** is **NO-GO**: it depends on Phase 3 (admissible evidence),
  on real M05 signals (none exist on hosted seasons), on a privacy/data-processing decision per
  provider, on a durable quota store, and on a human-authored holdout evaluated with a real model
  after owner approval.

---

## 1. Current production state (verified 2026-11-21)

Sources: `gh` against `levuanh2/TEC2026`, `git` on fetched refs, the public production web bundle
(`https://agricarbon.info.vn/`, static assets only) and `GET https://api.agricarbon.info.vn/health`.
No hosted database query, no Render/EC2 configuration read, no authenticated production request.

| Item | Value | How verified |
|---|---|---|
| `main` | `63ae678` (last merge #76, 2026-11-13) | `git rev-parse origin/main` |
| `integrate/rag-v15` | `5f7e730`, **not an ancestor of main** (88 commits ahead) | `git merge-base --is-ancestor` |
| PR #70–#91 | all **OPEN Draft**, except #73 and #76 (UI, MERGED into main). #92 (this round) is also Draft | `gh pr list` |
| CI on every open Draft #70–#91 | 17/17 SUCCESS at the current head | `gh pr checks` |
| main branch protection | 1 approval, `require_code_owner_reviews`, required check `ci-gate`, **`enforce_admins` false**, no rulesets | `gh api …/branches/main/protection` |
| `integrate/rag-v15` protection | **none** (404 "Branch not protected") | same |
| CODEOWNERS on main | 74 rules, **one owner: `@levuanh2`** (all RAG answer-path files included) | `git show origin/main:.github/CODEOWNERS` |
| Collaborators | `levuanh2` admin, `SiriusNoPro` **write** (re-granted after the 2026-11-09 revocation by an unknown actor; not a CODEOWNER) | `gh api …/collaborators` |
| Production web | Render static site, entry `index-BqZEk4VJ.js` (the 2026-11-13 deploy of `cdec10f`; #76 is not deployed). The AI panel chunk exists but **`aiQuestionsEnabled` is compiled `false`** (`const mn=!1` in `aiQuestions-*.js`) | public bundle |
| Production API | EC2 `api.agricarbon.info.vn`, `/health` 200. Last recorded deploy 2026-11-13 (`ec2-63f500b`), `api.env` has **no `RAG_*`** variable → the questions route answers 503 `backend_not_configured` after auth | health probe + deploy record (not re-read) |
| Hosted migrations | recorded history = **25** (2026-11-05, ends `20261104090000`). main has **26** files: `20261105090000_set_based_batch_carbon_read_policies.sql` has **no apply record** → UNVERIFIED | `docs/MIGRATION_HISTORY.md`, rollout logs |
| Hosted knowledge | Migration A + ST1 + ST1.1 applied; **0 approved documents** (last recorded); M1–M7 **not** on hosted | migration history + RAG_V1_STATUS |
| Staging | `agricarbon-api-staging` / `agricarbon-web-staging` **share the hosted Supabase project** (`render.yaml` CSP `connect-src … awazhdqzkktekbwaqiic.supabase.co`). The production web *is* the site named `agricarbon-web-staging`. | `render.yaml` on main |

### 1.1 RAG feature flags

| Flag | Where | Default | Effect | Production today |
|---|---|---|---|---|
| `RAG_QA_ENABLED` | API env (`main.py:203`) | off | the questions route has a service (else 503 `backend_not_configured`) | unset |
| `RAG_QA_ACTION_TIER_ENABLED` | API env (**new, #92**) | off | recommend / what_if / non-ASK refused with 503 `action_tier_disabled` **before any read**; no provider setting is loaded | n/a (not merged) |
| `RAG_LLM_PROVIDER` (+ `RAG_LLM_*`, `GEMINI_*`, `DEEPSEEK_*`) | API env | unset = no provider | the action tier's model | unset |
| `RAG_LLM_KILL_SWITCH` | API env | off | no model call at all (503) | unset |
| `RAG_LLM_MAX_*`, `RAG_LLM_DAILY_*` | API env | 20/user/day, 1000/project/day, 5/user/min, alert $5, hard stop $10 | in-process quota (`llm_quota.py`), resets on restart | n/a |
| `VITE_AI_QA_ENABLED` | web build | off | shows the season panel | **false** (bundle) |
| `VITE_AI_QA_ACTION_ENABLED` | web build (**new, #92**) | off | offers the farmer "Gợi ý hành động" | n/a |
| `RAG_D8C_ENABLED` | research branch only | — | grounded READ LLM (strategy C) | not in main |

## 2. What is implemented where

Legend: ✅ yes · ⬜ no · — not applicable. "Tested locally" = full local suite or the component's own
DB tests on an isolated stack in the session that built it (numbers in §10).

| Component | main | integrate | Draft only | Tested locally | Deployed to prod | Enabled for real users | Blocked by |
|---|---|---|---|---|---|---|---|
| Season Q&A route + READ composer (D8-B, templates) | ✅ | ✅ | — | ✅ | ✅ code, flag off | ⬜ | owner decision, §3 checklist |
| D8-B topic-aware scope (`question_scope.py`) | ✅ | ✅ | — | ✅ | ✅ code | ⬜ | — |
| Action tier (recommend/what_if) via provider adapter, quotas, kill switch | ✅ | ✅ | — | ✅ (scripted + 108+ paid DeepSeek-flash synthetic calls, 2026-11-07/08) | ✅ code, no provider | ⬜ | Track C |
| **Server-side READ-only lock** | ⬜ | ⬜ | **#92** | ✅ (§10) | ⬜ | ⬜ | review (§9) |
| Migration A, ST1, ST1.1 (knowledge tables, lexical RPC, artifact guard) | ✅ | ✅ | — | ✅ | ✅ hosted | — (0 approved docs) | — |
| Migration `20261105090000` (batch/carbon set-based RLS) | ✅ | ✅ | — | ✅ | **UNVERIFIED** | — | read-only hosted check |
| M1 status lifecycle, M2 verified approval + H-a/H-b/H-c hardening, M3 effective dates, M4/M4.1 claims + reviewer read, M5 tags, M6 revocation runbook | ⬜ | ✅ (9 migrations) | — | ✅ | ⬜ | ⬜ | integrate → main merge needs review; hosted migrations need per-batch approval |
| M6.1 metadata-only citation events | ⬜ | ⬜ | #70 | ✅ | ⬜ | ⬜ | must merge FIRST (migration order) |
| M7 dev3-01 harness | ⬜ | ⬜ | #71 | ✅ | ⬜ | ⬜ | dev3-01 OPEN |
| E2 integrity gate before approval | ⬜ | ⬜ | #72 | ✅ | ⬜ | ⬜ | — |
| E7 Ed25519 verification / E7.1 portable attestation | ⬜ | ⬜ | #74, #77 | ✅ | ⬜ | ⬜ | real verifier key + separate DB login (E7 binds nobody while production connects as `postgres`) |
| E5 design / E5 answer-time re-validation | ⬜ | ⬜ | #75, #78 | ✅ | ⬜ | ⬜ | — |
| E3 action containment (owner option B) | ⬜ | ⬜ | #81 | ✅ (3924 passed) | ⬜ | ⬜ | Option C needs real experts |
| READ-tier contested-citation UX | ⬜ | ⬜ | #84 | ✅ | ⬜ | ⬜ | — |
| kn-claims-4 (spelled zero) + stack compatibility fix | ⬜ | ⬜ | #87, #89 (DO NOT MERGE) | ✅ (3948 passed) | ⬜ | ⬜ | #87 must never meet #72+ without 4c1b034 |
| E5.1 pin-aware admission | ⬜ | ⬜ | #90 | ✅ (3978 passed) | ⬜ | ⬜ | E5.1-a…e |
| E5.2 pin generations | ⬜ | ⬜ | #91 | ✅ (4005 passed / 7 skipped) | ⬜ | ⬜ | E5.2-a…f |
| E1/E4 docs (sources, rights, expert governance, IPCC indexed page, QĐ 2626 evidence) | ⬜ | ⬜ | #82, #83, #85 | — | — | — | D1, D6, D7 |
| Farmer/Management Carbon copy "chưa được chuyên gia thẩm định" | ⬜ | — | #86 (base main) | ✅ | ⬜ | ⬜ | review |
| AR5 GWP comment | ⬜ | — | #88 (base main) | — | — | — | review |
| Flutter local-only season Q&A, APKs | ⬜ | — | #79 (base main) | device QA | ⬜ | ⬜ | review |
| D8-C grounded READ LLM | ⬜ | ⬜ | research branch | synthetic only | ⬜ | ⬜ | real-model eval |

## 3. Release Track A — READ-only production pilot

### 3.1 Can READ-only open independently of M7 and the Draft migrations? **Yes.**

On main the READ tier (explain, compare, evidence, data_gap) is written by
`recommendation/rag/informational.py` from trusted facts; no model ever writes READ text
(`CapabilityRoutedGenerator`, `informational.py:261-282`). It needs Migration A (applied) and the
Core V1 read paths. M1–M7 add knowledge *governance*; with an empty approved corpus the `evidence`
intent returns `insufficient_evidence` ("Chưa có đoạn tài liệu đã duyệt nào khớp…"), which is the
expected pilot behaviour.

**Condition:** the hosted approved corpus must stay at **0**. On main, "approved" is the pre-M2
status (no expert-verification assurance, no integrity gate), so any document approved on hosted
before M1–M7 + E1/E4 would be served by `match_knowledge_chunks_lexical` to READ users. GO requires
a read-only check that it is 0 and a rule that no knowledge write happens on hosted during the pilot.

### 3.2 What was wrong with the lock on main (found this round)

The only thing between a production READ pilot and the action tier was **"nobody set
`RAG_LLM_PROVIDER`"**. With `RAG_QA_ENABLED=true` and no provider (code on main, confirmed
independently by the agy side review `.tmp/prodready-readonly/REPORT.md`, verdict
`READ_ONLY_SAFE_WITH_RISKS`):

| Request (WRITE farmer) | What main does |
|---|---|
| `recommend`, season has stored M05 signals, empty corpus | season context read, retrieval RPC run, **200 `insufficient_evidence` carrying the stored M05 `signals`** |
| `recommend`, no stored signal | 200 `no_rule_signal` |
| `what_if` | **two Carbon calculations** (`persist=False`) and a retrieval, then 503 `generation_unavailable` |
| any action intent, if an operator ever sets `RAG_LLM_PROVIDER` + key (e.g. for a test) | **the action tier goes live for every WRITE farmer at once**, no second switch |
| farmer UI | offers "Gợi ý hành động" although the server cannot answer it |

No model call, persistence, cross-tenant read or MRV mislabel was found on the READ path (agy §1, §3,
§4, §5, each re-checked against the code; agy also quoted a `citation_sink` and a 503 message that do
**not** exist on main: those two details were discarded).

### 3.3 The fix: Draft PR #92 (`fix/rag-read-only-tier-lock`, base main)

- `RAG_QA_ACTION_TIER_ENABLED` (server env, only the exact string `true` enables).
- Off (default): `build_question_service` returns a READ-only service **without even loading
  provider settings**; `RagQuestionService.answer` refuses `recommend`, `what_if` and any non-ASK mode
  as its **first statement** with 503 `action_tier_disabled` ("Giai đoạn thử nghiệm chỉ hỗ trợ câu
  hỏi giải thích số liệu; chưa có gợi ý hành động."), before scope resolution, reads, Carbon
  simulation or retrieval. The refusal is identical for in-scope and out-of-scope seasons (no probe).
  A provider client passed to a READ-only service is dropped.
- Web: `VITE_AI_QA_ACTION_ENABLED` (build time, default off) hides the farmer action option; a typed
  action question shows "Giai đoạn thử nghiệm chưa có gợi ý hành động…" and stays on a READ intent;
  `action_tier_disabled` has its own non-retryable message.
- Tests: `backend/tests/test_rag_read_only_tier_lock.py` (45 tests) through the real route and the
  real factory with a provider configured *by mistake* in the env: tripwire reader/Carbon fakes prove
  nothing is touched; 10 request shapes (intent spelling, `mode`, `capability`, list intent, extra
  fields) are 422; headers cannot enable the tier; READ intents still answer with `llm_calls 0`.
  Mutation check: disabling the guard fails 9 tests, keeping the provider client fails 1.
- Guarded files: `backend/rag_qa.py` (CODEOWNERS + `guarded_paths`), commit carries `CI-Policy-Change`.

### 3.4 What the pilot is meant to test (owner decision A-0)

READ answers are **fixed templates per intent** (PRODUCT_GAP, measured 2026-11-07: 5 differently
worded explain questions → 1 answer; 3 evidence questions → 1 sentence). The panel says "mẫu cố
định". A READ pilot can therefore validate **safety, authorization, tenant isolation, data
completeness messages and the non-MRV caveat**; it cannot validate a conversational assistant.
If the owner's goal is usefulness, the current build is not sufficient, and strategy C (grounded
READ LLM) is a separate Track C-style effort with its own real-model evaluation.

### 3.5 READ-only GO / NO-GO checklist (each item verifiable)

| # | Check | Evidence to store | Status |
|---|---|---|---|
| A1 | #92 reviewed by a valid human code owner process (§9) and merged without admin bypass | PR review record, merge SHA | ⬜ |
| A2 | main CI 17/17 at the exact merge SHA | `gh pr checks` output | ⬜ |
| A3 | Owner decision A-0 (pilot goal) and A-1 (pilot cohort: named QA/trial accounts only) recorded | decision note | ⬜ |
| A4 | Read-only hosted check (owner-authorized, rolled-back transaction): migration history; `20261105090000` applied or not; `count(*) knowledge_documents where status='approved'` = 0 | SQL output | ⬜ |
| A5 | Isolated QA (§6): `ai-qa-real.spec.ts` serial on a local or separate-project stack with READ-only flags: farmer, manager, outsider; logout/account switch; 390 px; empty/error/loading | Playwright report + screenshots | ⬜ |
| A6 | Backend route/auth evidence on that stack: `test_rag_questions_route_db.py`, `test_route_positive_auth.py`, tier-lock tests | pytest log | ⬜ (CI runs DB suites on the PR) |
| A7 | No-provider assertion: API env has no `RAG_LLM_PROVIDER`, `RAG_QA_ACTION_TIER_ENABLED` absent, `RAG_LLM_KILL_SWITCH=true` as a further layer (only read if the action flag is ever set by mistake); startup log line `rag_question_service tier=read_only provider=not_loaded` | redacted env-name list + log line | ⬜ |
| A8 | Direct-API smoke on production after enabling (one QA farmer JWT): explain → 200 `system_composed`, `llm_calls 0`; recommend → 503 `action_tier_disabled`; what_if → 503 `action_tier_disabled`; explain on a season of another HTX → 404 | curl transcripts (token redacted) | ⬜ |
| A9 | Web deploy with `VITE_AI_QA_ENABLED=true`, `VITE_AI_QA_ACTION_ENABLED` unset; bundle shows the action flag compiled `!1`; Cloudflare index cache rolled over | bundle grep, deploy id | ⬜ |
| A10 | Rollback rehearsed **on the isolated stack** (not on production): unset `RAG_QA_ENABLED` + restart (route 503) and rebuild the web with the panel off | timing notes | ⬜ |
| A11 | Privacy notice: the panel copy says answers are templated from the user's own season data, nothing is stored | screenshot | ⬜ (copy exists, owner to confirm) |
| A12 | Request volume: the API has **no rate limit on any route** (only the model path has quotas). Owner either accepts this for a named small cohort or adds a per-IP/per-route limit at the Caddy proxy (infrastructure change, own approval) | decision note or proxy config diff | ⬜ |
| A13 | Alert sink and on-call person named for Phase 2 (who reads the §11 signals, how fast, who flips the flag) | runbook entry | ⬜ |
| A14 | Empty-season output checked: a real QA season with 0 activities and no Carbon result answers explain/data_gap without error | screenshot | ⬜ |
| A15 | Decision notes (A-0, A-1, A-2, A-12) stored in `docs/rag/` in a docs PR, not only in chat | PR link | ⬜ |

**NO-GO if any of:** a provider variable or the action flag is present in the production API env; the
hosted approved corpus is not 0 (or not checked); the lock PR is merged by admin bypass or without a
human review; any A8 response differs; QA ran against the shared hosted project with synthetic data.

Enable: API `RAG_QA_ENABLED=true` (+ `RAG_LLM_KILL_SWITCH=true`), web `VITE_AI_QA_ENABLED=true`.
Disable: unset `RAG_QA_ENABLED` and restart the container (no data change: D4, nothing persisted);
rebuild the web with the panel off. Impact of turning it off: the panel shows "Trợ lý hỏi đáp chưa
được bật cho hệ thống này"; no other screen depends on it.

## 4. Release Track B — Scientific RAG: **NO-GO**

| Requirement | State | Blocker type |
|---|---|---|
| Source documents with provenance | QĐ 4043 Cà Mau signed annex: provenance PASS (strict CRL, trusted TSA); QĐ 2626 Điện Biên copy accepted as a record copy only (D2), chain "reaches G1 root with SHA-1 allowed" (D3); QĐ 4801 cover-only (HOLD_PARTIAL); QĐ 1490 scan-only (BLOCKED, no OCR in V1.3) | official source / legal |
| Rights to use | IPCC: written permission needed, live copyright page unread (403), **D1 BLOCKED**; NAEC book: ambiguous rights; government decisions: `official_publication` pending owner confirmation | legal / owner |
| Claim-to-source traceability | design + evidence docs #85 (QĐ 2626), numeric registry empty | expert |
| Source verification by a real expert, reviewer and approver | **none appointed (D6/E4 OPEN)**; every reviewer in tests is synthetic | real expert |
| Independent verifier, key, separate DB login | E7/E7.1 Draft; production API connects as `postgres` (owner), so E7 binds nobody until a non-owner producer login exists; no real key | owner + infrastructure |
| Pin and generation established | E5.1/E5.2 Draft; no hosted pin | owner (E5.1-c, E5.2-c/d) |
| Retrieval evaluation on an authorized real corpus | impossible: 0 authorized documents | depends on the rows above |
| Documents approved under the current pin generation | 0 | depends on the rows above |
| E3/E5/E5.1/E5.2 protections | Draft, CI green, not on hosted | review + hosted migrations |

Split of blockers:

- **Owner decides:** D1 (IPCC permission route), D7, A-08 caveats kept; E3 Option C timing;
  E5.1-a…e, E5.2-a…f (especially E5.2-a strict epochs and E5.2-c hosted timing); verifier key custody;
  merge order of the M7 stack; whether production keeps connecting as `postgres`.
- **Real qualified people:** E4 appointment (named, evidence recorded), review of real sources and of
  integrity findings, approval records through the DB paths. No synthetic approval is created to pass
  a gate.
- **Code/test, can be done by an agent:** the merge-order integration branch (#70 first), the #87 +
  4c1b034 pairing, E5.3 re-attestation design (§5.3), a hosted-shape dry run on an isolated stack,
  the `current_generation` display nit in `knowledge_repin_impact.py`.
- **Legal / official sources:** IPCC written permission; issuer copies (letters drafted
  2026-11-17 in `.tmp/issuer-requests-2026-11-17.md`, not sent); QĐ 4801 MRV annex; an OCR policy
  for scan-only decisions.

## 5. Corpus availability and E5.2

### 5.1 Measured facts

| Environment | Approved documents | Lose admission on re-pin | Must be re-reviewed |
|---|---|---|---|
| Hosted (recorded, not re-queried) | **0** (and no M1+ schema) | 0 | 0 today; every future approval at each pin change |
| Local isolated stack (`knowledge_repin_impact.py --target local`, 2026-11-20) | 0 (no real corpus committed; synthetic only in tests) | 0 | — |

So E5.2 suspends nothing **today**, because there is nothing to suspend. The availability question is
about the future: under E5.2 **every** pin update (including a verifier Python or library upgrade,
which changes the E7.1 manifest digest, or an attestation-mode change) starts a new generation, and
every earlier approval is never admissible again. Recovery = new version + expert review in the new
generation (D-REVIEW). With 0 appointed experts, recovery capacity is 0 documents/day.

### 5.2 Consequences

- RAG-backed production (`evidence` with citations, Track B/C) is **NO-GO** while the admitted corpus is
  empty, which it is and will be immediately after any re-pin.
- READ (Track A) is unaffected: templates need no corpus; `evidence` says nothing approved matches.
- RECOMMEND needs `needs_documents=True` evidence → `no_evidence_retrieved` after any re-pin until
  re-review; WHAT_IF numbers come from the Carbon engine, not the corpus.
- Python/verifier runtime upgrades must be scheduled as corpus events: plan the upgrade, run
  `knowledge_repin_impact.py` read-only, budget expert time, then re-pin. Rollback of E5.2 ends in a
  safe refusal (pin cleared), never in reactivated old approvals.

### 5.3 E5.3 re-attestation (design direction, not implemented)

For a version whose claim set is unchanged under the new extractor (`claim_set_unchanged` in the
impact tool), a **re-attestation** record would let a *verifier* (not an expert) re-sign the same
claim-set digest under the new generation, while an expert approval stays required for any changed
claim set. It must not be an exception to expert approval: the original expert approval would only
carry forward when (a) the claim-set digest is byte-identical, (b) the new verification is signed by
the independent verifier key, (c) the change class is runtime/attestation only (E5.2-a), and (d) the
owner has approved that policy. Test plan (local only): A→B runtime-only re-pin with an unchanged
claim set → admissible after re-attestation; a changed claim set → still suspended; a forged digest
→ refused; rollback → safe refusal. Decision E5.2-a/E5.2-b comes first.

## 6. Independent staging

Staging shares hosted Supabase with production (§1). Therefore, on staging: **no migration, no seed,
no pin change, no synthetic approved document, no write or delete tests**.

QA plan without real data:

1. **Phase 0/1 default (no cost):** the local isolated stack (Docker Supabase CLI on shifted ports,
   CI seed `seed_ci_db.py`, synthetic `TEST FIXTURE` knowledge, local QA identities) + local API with
   the pilot flags + web build with the pilot flags; `ai-qa-real.spec.ts` serially. This is where A5
   and A6 run.
2. **Optional, needs owner approval:** a separate Supabase project for staging (all migrations, CI seed,
   QA identities) and pointing `agricarbon-api-staging` at it. Supabase/Render tier and cost must be
   confirmed by the owner before anything is created. No resource is created by this audit.
3. The production smoke (A8) uses one existing QA farmer identity on production, read-only intents
   only, after the owner enables the flag.

## 7. Release validation (evidence this round)

| Level | Test | Environment | Result |
|---|---|---|---|
| READ | `test_rag_read_only_tier_lock.py` | Windows, CI-equivalent venv, offline | 45 passed |
| READ | lock mutation (guard disabled / provider kept) | same | 9 failed / 1 failed (tests bite) |
| READ | full backend suite on #92 | same, no DB env (DB tests skipped) | 2032 passed, 739 skipped, 0 failed |
| READ | web `vitest` full suite on #92 | Node, jsdom | 97 files, **791 passed** |
| READ | web `tsc -b` | same | 0 errors |
| READ | agy side audit of main's READ path | static, read-only | `READ_ONLY_SAFE_WITH_RISKS` (2 risks, both fixed by #92) |
| READ | agy side review of this report + #92 diff | static, read-only | `NO_BLOCKER`; added A12–A15 and C1/C7 thresholds from it. Its code quotes were partly invented (e.g. `quota_store=None`, `RagStatus.ANSWERED`), so only conclusions re-checked against the code were kept |
| READ | DB route tests, Playwright mock, Flutter | CI on #92 | see PR checks |
| READ | `ai-qa-real.spec.ts` (updated for READ-only) | **not run** this round (needs the isolated real stack) | A5 open |
| RAG | E1–E7.1, E5.1, E5.2, dev3-01 harness | local + CI on #70–#91 (2026-11-13…20) | green; dev3-01 characterization still shows the poisoned path is cited when undetected (`test_12i`) |
| RAG | retrieval DEV/HOLDOUT on a real corpus | — | **impossible** (no authorized corpus) |
| Action | 108 paid deepseek-flash synthetic calls (2026-11-08, $0.0507) + R1–R3 ($0.0176) | owner-approved, synthetic fixtures | historical only; holdouts are agy-authored (semi-independent), replay not equivalent after prompt changes |
| Action | real-model run this round | — | **none** (no approval) |

No threshold was changed.

## 8. Production rollout design

Dates are not set: each phase opens only when its GO list is complete.

| Phase | GO criteria | NO-GO | Owner of the decision | Evidence to keep | Flags | Monitoring | Rollback / impact of turning off |
|---|---|---|---|---|---|---|---|
| **0 Local demo** | #92 branch; isolated stack; scripted QA | any hosted credential in the env | engineer | test logs | `RAG_QA_ENABLED=true`, action off, no provider | local logs | stop the stack |
| **1 Staging validation** | Phase 0 green; A5/A6 on an isolated DB; owner decision on a separate staging project | QA on the shared hosted DB with synthetic data | owner | Playwright report, pytest logs | same as 0 | Render logs (names only) | unset flag |
| **2 Production READ-only** | §3.5 A1–A15 | §3.5 NO-GO list | owner | A4/A7/A8/A9 transcripts, pilot cohort list | API `RAG_QA_ENABLED=true`, `RAG_LLM_KILL_SWITCH=true`, no `RAG_LLM_*`, no action flag; web `VITE_AI_QA_ENABLED=true` | `rag_question` log lines: `llm_calls` must be 0 on every line, `error=action_tier_disabled` count, 5xx, `tenant_isolation_violation` (must be 0), p95 `total_ms` | unset `RAG_QA_ENABLED` + restart (≈ 1 min), web rebuild; nothing persisted, so no data rollback |
| **3 Production Scientific RAG** | §4 table all ✅: rights, real experts, verifier key + non-owner login, M1–M7 + E5.1/E5.2 on hosted (per-migration approval, fail-fast), pin set, ≥ 1 document approved in the current generation, DEV/HOLDOUT pass | any synthetic approval; any blocking integrity finding unresolved; E5.2-a undecided | owner + appointed experts | approval records, verifier signatures, impact report, eval report | READ as Phase 2 + approved corpus | citation events (M6.1), `evidence_refused`, awaiting-recheck signal | quarantine/archive path (H-b), pin clear = safe refusal (E5.2 rollback), migrations down in reverse order |
| **4 Production AI Recommendation** | §8.1 list | any item missing | owner | §8.1 evidence | `RAG_QA_ACTION_TIER_ENABLED=true`, `RAG_LLM_PROVIDER=<approved>`, prices, kill switch off, web action flag | quota/cost logs, `rag_llm_budget_alert`, refusal/grounding rates, incident channel | `RAG_LLM_KILL_SWITCH=true` (no deploy) → then action flag off |

### 8.1 Phase 4 (real AI Recommendation) — exact missing items

| # | Missing | Type |
|---|---|---|
| C1 | Real M05 rule signals on real seasons (none observed on any hosted season when last looked, 2026-09-28; re-check read-only). The owner sets the minimum coverage (number of pilot seasons and rule families: water, fertilizer, data tasks) | data / product |
| C2 | Admissible evidence (Phase 3) for the rules the model explains | Track B |
| C3 | Model may not invent rule codes: structural gate `assert_recommendations_follow_rules` + schema/grounding/consistency gates exist on main; must be re-verified on the merged M7 stack | code (exists) |
| C4 | E3/E5 containment on hosted (#78/#81 + migrations) | review + hosted |
| C5 | dev3-01 evaluated in scope: E6 (real-model replay) never run; E1/E4 open → dev3-01 stays OPEN | expert + approval |
| C6 | A **human-authored** holdout (DEV/HOLDOUT split, frozen) and a real-model benchmark on it, after explicit owner approval of provider, data and cost | owner + human author |
| C7 | Injection, hallucination, citation, refusal, invented scientific values, unsafe advice, timeout, unauthorized action: harness cases exist; must pass on C6 with the chosen model at the existing gates (correct refusal, injection resistance, rule-code validity, citation correctness, no-model cases skip the provider = **1.0**; grounding ≥ 0.75; provider error rate ≤ 5 %; `RAG_V1_PILOT_READINESS.md` §1, staging runbook §5), unless the owner tightens them; scripted-model passes are not quality evidence | evaluation |
| C8 | Privacy / data-processing review **per provider** (Gemini paid tier vs DeepSeek: processing location, retention, training use, DPA, user notice, consent); Gemini key is still 401 | owner / legal |
| C9 | Durable quota store (`supabase/drafts/rag_llm_usage_daily.sql`, draft, needs its own migration approval) before more than one API process | code + hosted migration |
| C10 | Provider-side budget alert (billing console) in addition to the in-app hard stop | owner |
| C11 | Incident response: who flips `RAG_LLM_KILL_SWITCH`, how farmers are told, log retention for an investigation without prompt text | owner + runbook |

## 9. Governance

- Owner decides; agents do not merge, approve, bypass or change branch protection.
- Today a code-owned PR into main **cannot** be merged validly without the admin bypass: main needs
  1 approval + code-owner review, the only code owner is `levuanh2`, who cannot approve their own PR,
  and `enforce_admins` is off (the bypass would also skip `ci-gate`). `integrate/rag-v15` has no
  protection at all.
- Valid options (owner chooses; none is applied here):
  1. Add a second **qualified human** CODEOWNER with their own account, then enable `enforce_admins`.
  2. Solo configuration (0 approvals, no code-owner requirement, `ci-gate` required, `enforce_admins`
     on) — only after credential separation, because every agent on this machine runs as the owner's
     Windows user with the owner's GitHub admin token; with 0 approvals any agent could merge a green PR.
- `SiriusNoPro` has write access again (re-granted after the 2026-11-09 revocation by an unknown
  actor). The owner should confirm or revoke it; it is not a review path.
- Not used and never to be used: fake approvals, a second account self-review, admin bypass, an agent
  review presented as code review (agy's report above is a side check, not a review).

## 10. Test evidence (exact numbers)

| Run | Where | Result |
|---|---|---|
| `pytest tests/test_rag_read_only_tier_lock.py` | `E:\TEC2026-readlock`, CI-install venv, Windows | 45 passed |
| Full backend suite on #92 | same, DB env empty (DB/POSIX tests skip) | 2032 passed, 739 skipped, 0 failed |
| `vitest run` | `E:\TEC2026-readlock\web-dashboard` | 97 files, 791 passed |
| `tsc -b` | same | 0 errors |
| CI on #92 | GitHub | see the PR checks |
| Earlier rounds (state of record, not re-run) | #81 3924 passed; #89 3948; #90 3978; #91 4005 passed / 7 skipped; #91 CI 17/17 | per PR bodies |

## 11. Monitoring and rollback (Phase 2 specifics)

- The questions route sets no `Cache-Control: no-store` (only two other routes do). The API host is DNS-only
  behind Caddy, not Cloudflare-proxied, so no shared cache sits in front of it today; adding `no-store` to the
  route is a small follow-up if that ever changes.
- Log line `rag_question … intent=… status=… error=… llm_calls=…` (no question text). Alert on:
  `llm_calls` ≠ 0, `error=tenant_isolation_violation`, 5xx rate > 1 %, p95 `total_ms` > 5 s.
- Startup line `rag_question_service tier=read_only provider=not_loaded` must be present after each
  deploy; `tier=read_and_action` in production during Phase 2 is an incident.
- Rollback ladder: (1) unset `RAG_QA_ENABLED`, restart the container; (2) web rebuild with the panel
  off; (3) redeploy the previous image tag. Nothing is persisted by the Q&A path, so no data rollback.

## 12. Next small technical steps

1. Review and merge #92 through a valid review path (§9).
2. Run A5/A6 on the local isolated stack with the READ-only flags (no cost, no hosted access).
3. With owner authorization: the read-only hosted check A4 (one rolled-back transaction).
4. Docs PR for `docs/MIGRATION_HISTORY.md` row 026 once A4 says whether `20261105090000` is applied.
5. Optional: E5.3 re-attestation test plan on an isolated stack after E5.2-a/b are decided.

## 13. Decisions the owner must approve

| ID | Decision | Blocks |
|---|---|---|
| A-0 | Pilot goal: safety/authorization only, or usefulness (then templates are not enough) | Phase 2 scope |
| A-1 | Pilot cohort (named trial accounts) and duration | Phase 2 |
| A-2 | Authorize the read-only hosted check A4 | Phase 2 |
| A-3 | Review path for code-owned PRs (§9 option 1 or 2) | every merge, incl. #92 |
| A-4 | Separate staging Supabase project (cost) or local-only QA | Phase 1 |
| A-5 | Confirm or revoke `SiriusNoPro` write access | governance |
| A-12 / A-13 | accept no API rate limit for the cohort or add a proxy limit; name the Phase 2 alert sink and on-call person | Phase 2 |
| D1 / D6 / D7 | IPCC rights; expert appointment; AR5 comment | Phase 3 |
| E5.1-a…e, E5.2-a…f | pin/generation policy, hosted timing, re-attestation | Phase 3 |
| C8 | provider + data-processing approval per provider | Phase 4 |
| C6 | approval of any real-model benchmark (provider, data, budget) | Phase 4 |

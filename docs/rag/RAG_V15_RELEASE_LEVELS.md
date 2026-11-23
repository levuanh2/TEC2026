# RAG V1.5 — release levels and GO / NO-GO checklists

Status 2026-11-23: **every level is NO-GO.** Each level opens on its own checklist and owner
approval; passing one level never opens the next. Agents prepare evidence only. They never
merge, deploy, change hosted data or permissions, or call a real provider. Owner decisions keep
the ids of the owner decision packet (A-0 … A-13) and of #94 (A1 … A15).

Legend: ✅ evidence exists (local / CI only unless stated) · ⬜ open · ⛔ blocked on a person.

## Level 1 — READ-only season Q&A for a named QA cohort

Answers are composed by trusted server code from the caller's own season data. No model call.

| # | Condition | Evidence | State |
|---|---|---|---|
| L1-1 | Server READ-only lock: recommend / what_if refused before any read (#92) | #92 CI 17/17, 45 tests | ✅ code · ⬜ human review + merge (A1, A-3) |
| L1-2 | Per-user rate limit, 429 before any read, fail closed (#95), released in the order of `RAG_QA_PILOT_SAFEGUARDS.md` §5: migration approved, applied and verified **before** the code (Path A), or the single-process `memory` store explicitly chosen (Path B) | #95 CI 17/17, tests, local rehearsal 25/25 | ✅ code · ⬜ values (A-12) · ⛔ Path A hosted migration approval, or Path B decision |
| L1-3 | Monitoring lines + `scripts/ops/rag_qa_log_summary.py` alerts (#95) | tests, rehearsal log summary | ✅ code · ⛔ alert receiver / on-call named (A-13) |
| L1-4 | Emergency stop rehearsed in isolation: Caddy 503 route, `RAG_QA_ENABLED=false` re-create, migration rollback | `RAG_QA_PILOT_SAFEGUARDS.md` §4 | ✅ local · ⬜ owner approves the production procedure (who, which host) |
| L1-5 | Hosted read-only verification (migration history, `20261105090000`, approved knowledge count, QA tenant scope) | prepared SQL, not run | ⛔ owner runs or authorizes it (A-2) |
| L1-6 | Pilot goal and cohort recorded (A-0, A-1); privacy copy shown (A11). The limit is per account: one account per tester, or shared accounts accepted with their shared quota (`RAG_QA_PILOT_SAFEGUARDS.md` §6) | decision notes in `docs/rag/` (A15) | ⛔ owner |
| L1-7 | Independent human CODEOWNER review path and repository access / protection settings decided by the owner | review records, owner decision packet (kept outside git) | ⛔ owner (A-3, A-5) |
| L1-8 | Production smoke after enabling (A8): explain 200 `llm_calls 0`, recommend 503 lock, outsider 404, 11th question 429; p50/p95 measured on production, not inferred from local | smoke log | ⬜ after L1-1…L1-7 |
| L1-9 | Web build with `VITE_AI_QA_ENABLED=true`, action flag unset, bundle checked (A9) | bundle grep | ⬜ |

Latency risk (local measurements, 2026-11-23, same database and season for every tree):

| Tree | DB calls per READ question | Supabase Auth calls | local p50 |
|---|---|---|---|
| #92 (main + lock) | 40–41 | 1 | ≈ 0.47–0.50 s |
| #95 (+ rate limit) | 42–43 | 2 | ≈ 0.61–0.66 s |
| integration trial (#91 + main + #95) | 42–44 | 2 | ≈ 0.63–0.69 s |

#95 adds two calls: the quota statement (by design) and a **second Auth `get_user`**, because the
rate limiter verifies the caller and the scope resolver verifies the same token again later in the
same request. The M7 stack adds 0–1 call. Most calls are sequential: the earlier delay-proxy model
(#94) measured ≈ 30 sequential round trips for ≈ 41 statements, so #95 makes it ≈ 32. Each pays the
full API ↔ database round trip: at 30–40 ms per trip (two regions) ≈ 1.0–1.3 s of waiting per
question, at 138 ms ≈ 4.4–4.6 s. Proposed, not applied: verify the token once per request and reuse
the verified user (removes one Auth call); read the season row once instead of 8 times. Neither
changes authorization, but each needs its own tests and review. Local numbers are not production
numbers: L1-8 must measure p50/p95 against the real API ↔ database distance before the cohort
grows.

**GO for Level 1** = L1-1 … L1-9 all ✅ and the owner's written approval. Until then NO-GO.

## Level 2 — Scientific RAG (cited scientific / regulatory documents)

The READ answers may cite scientific sources only when every source is qualified and reviewed.

| # | Condition | State |
|---|---|---|
| L2-1 | Level 1 is GO and stable | ⬜ |
| L2-2 | The `integrate/rag-v15` stack lands as one chain: tip #91 (contains #70–#90 by ancestry, plus the #87 and #89 patches as cherry-picks), then the docs PRs #82/#83/#85; #87 and #89 are closed unmerged (#89 is DO-NOT-MERGE, and merging it after #91 conflicts add/add). The stack's migrations `20261110090000`…`20261120120000` sort after main's newest; #95's `20261106090000` sorts before them on purpose | ⬜ owner merges, human review |
| L2-3 | The integration of #91 + main + #92 + #95 passes from an empty database and as an upgrade of a seeded main database; the full backend suite (CV / torch included), web unit and Playwright mock pass, on a tree that can actually be merged | **INCOMPLETE — integration validation not clean on any mergeable tree.** The TEST-ONLY tree `b111361` (Draft #96, never to be merged) is clean: GitHub CI 17/17, backend 4157 passed / 2 skipped (CV real-model smoke: no checkpoint in CI) / 0 failed. It is clean only because of four commits that exist on that branch alone: `ab9a8f0` asks a content-free ACTION question ("?") back before any model call — on the stack "?" passed both pre-model checks, reached the (fake) provider, and was discarded only afterwards (`answer_policy_rejected`); an earlier note here said the stack refused it before the model, which was wrong — and `1847e4d`, `bc9ecf0`, `b111361` give three tests a real question / split the "?" case. Where these land in the stack and #92 is an owner decision; re-run on the resulting tree |
| L2-4 | E1: every cited source has a first-party artifact, a text layer, a recorded content hash, documented rights (IPCC needs permission: D1) and extracted claims without unresolved registry conflicts | ⛔ E1 OPEN, D1 BLOCKED |
| L2-5 | E4: real, named domain experts (not test reviewers, not agents) review and approve each document; approval records are real | ⛔ E4 OPEN, D6 BLOCKED |
| L2-6 | Real verifier keys in custody (E7 / E7.1 independent signed verification) and a current integrity pin generation (E5.2) for the approved set; answer-time admission (E5.1) on | ⛔ owner key custody |
| L2-7 | Retrieval evaluation on a human-authored holdout the developers did not see; citation gate 100 % | ⬜ no independent holdout author yet |
| L2-8 | dev3-01 closed with evidence (it stays OPEN today) | ⬜ |
| L2-9 | Hosted migration of the stack, one migration at a time, each approved and verified | ⛔ owner |

**GO for Level 2** = L2-1 … L2-9 ✅ and owner approval. E1, E4 and dev3-01 cannot be closed by code.

## Level 3 — AI Recommendation (model-generated action answers)

| # | Condition | State |
|---|---|---|
| L3-1 | Level 2 GO (an action answer may cite scientific evidence) | ⬜ |
| L3-2 | M05 rule signals valid for the season (a model may only explain a deterministic rule the season has; `rule_code` gate) | ✅ code gate · ⬜ agronomic validation of the rules |
| L3-3 | Real-model evaluation with the owner's approval: refusal, prompt injection, grounding, tenant isolation, timeout, cost; on a holdout not written by the developers. Simulated-provider (`--fake`) results are plumbing checks, never model quality | ⛔ owner approval for provider calls; the 2026-11-07 flash run failed refusal 1/3 and injection 0/2 (trusted-code causes, remediated since; must be re-run) |
| L3-4 | Provider privacy approval: what season data leaves the system, to which provider and country, retention | ⛔ owner / legal |
| L3-5 | Durable model quota (the `llm_quota` store is in-process; `supabase/drafts/rag_llm_usage_daily.sql` is a draft, not a migration) | ⬜ code + hosted migration approval |
| L3-6 | Kill switch (`RAG_LLM_KILL_SWITCH`, `RAG_QA_ACTION_TIER_ENABLED`), cost hard stop and alerts rehearsed | ⬜ |
| L3-7 | Staged rollout: one QA farmer, then a named cohort, with the alert receiver on call | ⛔ A-13 |

**GO for Level 3** = L3-1 … L3-7 ✅ and owner approval.

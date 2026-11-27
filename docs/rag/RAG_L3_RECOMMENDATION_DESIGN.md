# L3 AI Recommendation — pipeline design (DESIGN ONLY)

Status: **DESIGN. Nothing here is implemented beyond what the "today" column names.** L3 needs L2 GO, a real-model evaluation,
provider and privacy approval, a cost budget, a durable LLM quota and expert review (`RAG_V15_RELEASE_LEVELS.md` on main,
reaching this branch with the sync PR #104). No provider
is called, no cost is incurred and nothing is deployed without a separate owner approval.

## 1. Principles
1. **Evidence bound.** Every recommendation explains an existing deterministic rule outcome (M05 `rule_code`) of the farmer's
   own season and cites approved, verified, admitted, in-force knowledge. No rule → no recommendation (`no_rule_signal`).
2. **Advice, never action.** The system never writes production data and never acts for the user. A recommendation is
   text; the farmer records what they did through the normal write paths.
3. **No privilege from text.** The question text can never raise access. Intent classification may narrow what is answered,
   never widen who may ask.
4. **Fail closed.** Any unverifiable step yields `insufficient_evidence` or a refusal, never a best-effort answer.
5. **Numbers are facts, not prose.** The model writes placeholders `{{fact:<id>}}`; values come from the trusted catalog.

## 2. Pipeline (owner's order) — today vs L3
| # | Stage | Today (main + #91 stack) | L3 work |
|---|---|---|---|
| 1 | Farmer question | `POST /v1/crop-seasons/{id}/questions`; tier lock, JWT, cohort, rate limit first (`rag_qa.py`) | unchanged |
| 2 | Intent classification | **client-chosen** `intent` (explain/compare/evidence/data_gap/recommend/what_if); UNKNOWN → `needs_clarification` | Server-side classifier (rules first, model only if approved) that may only (a) agree, (b) downgrade to a READ intent, or (c) return UNKNOWN. **Access = `required_access(requested intent)`, never the classified one.** Disagreement is logged and answered as clarification |
| 3 | Tenant authorization | `CallerSeasonScopeResolver` (RLS lineage under the JWT); WRITE needs an active farmer + `user_can_write_crop` (D1) | unchanged; D1 decision closes the "manager may ask for advice?" question |
| 4 | Farm and season context | `CallerSeasonFactsSource` → `build_season_context` (season, activities, metrics, carbon, readiness, M05 signals, comparison) | add CV signals and finalized benchmarks only when their sources exist (today empty by design) |
| 5 | Scientific retrieval | lexical RPC (approved + verified + in force + pin-admitted, tenant-scoped) → `AdmittedEvidenceRetriever` (E5.1) | dense / hybrid / rerank only if the L2 evaluation shows the ADR gain; **condition tags (M5)** filter by crop, region, season |
| 6 | Context validation | `assert_fact_scope` (all facts belong to the scope), usable facts per capability, E3 containment of dismissed conflicts | add **applicability check**: a cited chunk's scope (crop/region/season tags) must match the season; mismatch → not usable for action |
| 7 | Answer generation | READ: trusted composer, no model. Action: `LlmActionGenerator` (structured JSON schema), behind `GuardedLlmClient` (quota reserve → call → record), only if `RAG_QA_ACTION_TIER_ENABLED=true` | provider choice + DPA; prompt stays data-only (question + facts + evidence, no PII beyond the season facts) |
| 8 | Citation verification | core gates (schema, citation ⊆ retrieved, fact refs, prose, intent) + **E5 answer-time re-validation** under the JWT (still approved, verified, in force, same hash) | unchanged; add claim-level support check (each sentence ↔ one cited chunk) measured in the L2 generation eval before it is trusted |
| 9 | Recommendation safety checks | `assert_recommendations_follow_rules` (rule_code required), no pesticide products / doses (prompt rule 5 + prose gate), E3 containment | explicit **safety policy table**: banned topics (product names, doses, diagnosis), required limitation text, max actions per recommendation; tested as a gate, not only a prompt line |
| 10 | Response | `to_response` with provenance (`answer_source`, `llm_calls`, tokens, cost); nothing persisted (D4) | M6.1 citation events (metadata only) if approved; still no question/answer persistence |

## 3. Safety checks for L3 (gates, each with a test before L3 is enabled)
| Gate | Refuses | Where |
|---|---|---|
| G1 rule binding | a recommendation without an existing `rule_code` of this season | `assert_recommendations_follow_rules` (exists) |
| G2 evidence | a recommendation with no admitted, in-force citation, or citing a chunk whose scope does not match | E5 + new applicability check |
| G3 banned content | pesticide product names, doses, disease diagnosis, financial promises | new deterministic checker (a word list is not enough: tested on a red-team set) |
| G4 numbers | any digit or unit in model prose | prose gate (exists) |
| G5 contested science | citing a chunk with a dismissed conflict for an action | E3 (exists, local/CI) |
| G6 budget | provider call over the per-user / global quota or kill switch | `GuardedLlmClient` + quota (exists, not hosted) |
| G7 tier | any action answer while the tier flag is off | `ActionTierDisabled` first statement (exists, production) |

## 4. Evaluation before any L3 GO
Real-model replay on a frozen DEV set and a separately written HOLDOUT (`RAG_V15_SCIENTIFIC_EVAL.md` §3): groundedness,
unsupported-claim rate, citation accuracy, abstention accuracy, G3 red-team pass rate, cost per answer. Requires an approved
provider budget. Expert review of a sample of answers by the E4 expert.

## 5. Owner decisions needed
D1 (who may receive advice), provider + data-processing agreement, budget and quota values, the safety policy table (G3),
whether a server-side intent classifier may use a model at all (§2 row 2), E4 expert for answer review.

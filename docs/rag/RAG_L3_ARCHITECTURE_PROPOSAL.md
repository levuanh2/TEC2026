# L3 AI Recommendation — architecture proposal (PROPOSAL ONLY, nothing implemented or deployed)

Complements `RAG_L3_RECOMMENDATION_DESIGN.md` (#107: pipeline stages 1–10 and safety gates G1–G7). This file adds what
#107 leaves open: the engine, confidence, explanation, human review, feedback and evaluation, and the line between
Q&A and recommendation.

## 1. Q&A is not a recommendation

| | RAG Q&A (L1/L2) | AI Recommendation (L3) |
|---|---|---|
| Purpose | explain the season's own data and approved documents | propose an action for this season |
| Trigger | the user asks | a deterministic rule fires (M05 `rule_code`), or the user asks `recommend` |
| Output | answer text + citations, `persisted: false` | a **Recommendation record** with state, rule, evidence, confidence, reviewer |
| Model role | READ tier: none (trusted composer) | may draft the explanation; never decides the action |
| Authority | informational | becomes "validated" ONLY after a named agronomist accepts it |

Invariant: **an LLM answer never becomes a validated recommendation by itself.** A Q&A answer cannot be saved as a
recommendation; the only path into the recommendation table is the rule engine (+ optional model-drafted explanation),
and the only path to `validated` is a human review event.

## 2. Engine: rule-first, evidence-checked, model-explained

1. **Rule layer (decides).** Existing M05 rules on season facts (water regime, N rate vs crop/season, missing records).
   Each rule has an owner, a version, inputs, thresholds and a source reference. Output: `rule_code`, triggering facts,
   a candidate action from a CLOSED catalogue (e.g. "consider AWD", "split N application") — never a product or dose.
2. **Evidence layer (checks).** For the candidate action, retrieve approved, in-force, scope-matching chunks (crop,
   region, season tags — M5 condition tags). No admitted evidence → the recommendation is `insufficient_evidence`,
   not shown as advice. Conflicting evidence (M4 contradiction open) → `contested`, routed to review.
3. **Explanation layer (drafts).** Optional model call to write plain-language reasons from the facts and citations
   only (structured JSON, #107 gates: citations ⊆ retrieved, no numbers in prose, no banned content). Without a model the
   trusted composer writes a template explanation; the recommendation itself does not change.

## 3. Confidence (no single opaque score)

Report the components, not a model's self-rating:
- rule strength: rule version status (`validated` by an expert vs `draft`) and how far the facts are past the threshold;
- data completeness: share of the rule's inputs that are recorded for this season (the readiness API already counts them);
- evidence: number of admitted, in-force citations whose scope tags match; any open contradiction;
- calibration (later): acceptance rate of past recommendations of the same rule by reviewers.
Displayed as `high / medium / low` from a published table over these components; the table itself is versioned and
reviewed. A model's verbal certainty is never an input.

## 4. Explanation shown to the farmer

What was observed (season facts with values) → which rule fired (name, version) → what the approved documents say
(quoted with citation, document version, validity) → the proposed action (catalogue wording) → limits (data gaps,
region/season applicability, "talk to your extension officer" for pests/diseases).

## 5. Human in the loop

States: `generated → under_review → validated | rejected | expired`. Reviewer = named agronomist with the domain
(`E4` registry); a review records decision, reason, reviewer, time, and the exact evidence versions seen. Only
`validated` recommendations are shown as advice; `generated` ones are visible to reviewers only (pilot). A document
version leaving force (M3) or a pin change (E5.2) moves dependent recommendations back to `under_review`.

## 6. Feedback loop

Farmer feedback (applied / not applied / not relevant + free text) and reviewer decisions are stored per
recommendation (tenant-scoped, RLS). They tune RULE THRESHOLDS and the confidence table through a reviewed change, never
by automatic model training. Free text is treated as untrusted input (never fed to a model as instruction).

## 7. Evaluation before any L3 GO

- Rule correctness: an expert-labelled case set per rule (facts → should fire? which action?), precision/recall of
  firing, versioned like the L2 label sets (`RAG_L2_SCIENTIFIC_RAG_ROUND11.md` §D4).
- Evidence quality: citation accuracy and unsupported-claim rate on judged explanations (`rag_eval_framework`).
- Safety: G1–G7 tests (#107) + "no LLM output reaches `validated` without a review event" (DB constraint + test).
- Usefulness (pilot): reviewer acceptance rate, farmer "applied" rate, time to review; no claim about yield or CO2e
  impact without a field trial design.

## 8. Owner decisions (none taken)
L3-D1 closed action catalogue (who writes it) · L3-D2 reviewer registry and SLA · L3-D3 confidence table v1 ·
L3-D4 whether a model may draft explanations in the pilot (provider, quota, cost) · L3-D5 farmer feedback consent text.

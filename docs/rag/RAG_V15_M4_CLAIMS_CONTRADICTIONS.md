# RAG V1.5 M4 — Stored claims and contradiction candidates (2026-11-11, local/CI only)

Migration `supabase/migrations/20261112090000_knowledge_claims_contradictions_m4.sql`, rollback
`supabase/rollbacks/20261112090000_knowledge_claims_contradictions_m4.down.sql`. Depends on M1
(`20261110090100`), M2 (`20261110120000`) and M3 (`20261111090000`). **Not applied to hosted
Supabase. Nothing is scheduled. No provider is called.**

**What M4 is and what it is not.** M4 stores the claims a deterministic extractor finds in a document
version and the pairs of comparable claims whose values disagree. Both are a **review aid for a human
expert**. A candidate does not mean a document is false, and no candidate does not mean it is true.
M4 does **not** change retrieval, answer generation, approval or any status, and it quarantines
nothing. **dev3-01 stays OPEN.** The characterization test `test_rag_source_integrity_gap.py` is not
flipped (M7).

## 1. Pipeline

```
knowledge_chunks ──► claims.py (kn-claims-3) ──► private.knowledge_record_claims ──► knowledge_claims
knowledge_claims ──► contradictions.py (kn-contradictions-1)
                 ──► private.knowledge_record_contradiction_candidates ──► knowledge_contradiction_candidates
```

- `backend/knowledge/integrity/claims.py`: the extractor (pure, stdlib, from the offline review aid).
- `backend/knowledge/integrity/contradictions.py`: the pair analysis (pure, stdlib).
- `backend/infrastructure/knowledge_claims_repo.py`: the operator adapter. It only SELECTs and calls
  the two recording functions (an architecture test pins this).
- `backend/scripts/knowledge_claims.py`: operator CLI, one document version per run,
  `--target local` only. A hosted destination is refused (exit 2).

Nothing runs on ingestion, on approval or on a schedule. An operator runs the CLI for one version.

## 2. Claims (`public.knowledge_claims`)

One row per claim, per document version, per extractor version.

| Field | Meaning |
|---|---|
| `document_pk`, `chunk_pk`, `source_id`, `document_id`, `document_version`, `chunk_id` | the exact version and chunk |
| `chunk_content_sha256` | the chunk content hash at extraction, copied by the database |
| `span_start`, `span_end`, `raw_text` | the evidence span; the database checks `substr(content, start + 1, end - start) = raw_text` |
| `kind` | `quantity`, `date`, `stage`, `assertion` |
| `status` | `extracted`, `ambiguous`, `unsupported` (the uncertainty class) |
| `parameter`, `value_min`, `value_max`, `unit`, `dimension` | normalized value, only when unambiguous |
| `stage`, `scope_tags` | crop stage and practice tag (`awd`) stated in the same sentence |
| `comparison_key` | **generated**: `parameter\|unit` for an extracted quantity with a range, else null |
| `extractor_version` | e.g. `kn-claims-3` |
| `visibility`, `organization_id`, `farm_id` | the scope of the source, copied by the database |
| `recorded_at`, `recorded_xact`, `actor_role` | when and under which role the row was accepted |

Rules:

- A claim whose span, text or chunk does not match the stored chunk of that version is refused
  (`23514` span, `23503` chunk).
- Nothing is invented. A number with an unknown separator ("1.500"), a signed value, a unit without a
  parameter cue, or an unsupported unit is stored as `ambiguous` / `unsupported` with **no comparison
  key**, so it is never compared. A bare number without a unit is not a claim.
- Idempotent: an identical claim is skipped. The same claim id with other facts under the same
  extractor version is refused; a changed extractor needs a new version.

### 2.1 What the extractor recognises (`kn-claims-3`)

| Parameter | Canonical unit | Examples of accepted raw units |
|---|---|---|
| `water.awd.dry_down_depth`, `water.flood_depth` | cm | mm, cm, m |
| `water.awd.irrigation_interval`, `water.drainage_duration`*, `crop.growth_duration`*, `mrv.monitoring_interval`* | day | ngày, tuần, day, week |
| `fertilizer.n_rate`, `fertilizer.rate`, `yield` | kg/ha | kg/ha, kg N/ha, tạ/ha, tấn/ha |
| `water.volume` | m3/ha | m3/ha |
| `ch4.reduction` | percent | %, phần trăm |
| `ch4.emission_factor` | kgCH4/ha/day | kg CH4/ha/ngày |
| `ch4.seasonal_emission`* | kgCH4/ha | kg CH4/ha, kg CH4/ha/vụ |
| `ghg.emission_per_area`* | kgCO2e/ha | kg CO2e/ha, tấn CO2e/ha, t CO2-eq/ha, kg CO2tđ/ha |

\* new in `kn-claims-3` (M4). The parameter names and units are identifiers of this extractor. They
carry **no reference value**: M4 holds no agronomic or emission number, and none was added.

An amount worded as a reduction, a saving or a difference ("giảm phát thải 50 kg CH4/ha") is left
`ambiguous`: it is not an emission level. A monitoring duration without an interval cue ("quan trắc
trong 90 ngày") is left `ambiguous` too.

Crop stages (`establishment`, `tillering`, `panicle_initiation`, `flowering`, `ripening`), dates and
two qualitative assertions are stored as claims but are **not paired** in M4.

## 3. Contradiction candidates (`public.knowledge_contradiction_candidates`)

Two claims are compared only when all of this holds:

1. same comparison key and same extractor version;
2. different chunks (several values in one chunk are usually a dose split or a stage sequence);
3. inside one data boundary: public with public, a tenant with itself or with public; never one
   tenant with another, never two different farms of one tenant;
4. not two different stated crop stages;
5. at least one side is not inactive;
6. the value ranges do **not** overlap. No tolerance is assumed. A caller may supply one per
   comparison key, with a written rationale; both are stored with the candidate.

Classification (first match wins). The database derives it itself in
`private.knowledge_classify_claim_pair` and refuses a proposal that disagrees (`23514`).

| Class | Meaning |
|---|---|
| `insufficient_evidence` | one side is inactive: rejected, quarantined, archived, expired, not yet in force, or its source is not approved. It is never reported as a contradiction of current guidance. |
| `apparent_contradiction` | an ordinary explanation is on record: one version supersedes the other (whole chain), the validity windows do not overlap, or they are two versions of one document. |
| `missing_context` | one side states a crop stage or a practice tag and the other does not. |
| `contradiction` | none of the above. Still a candidate for a reviewer, not a verdict. |

Evidence state of a document (`private.knowledge_document_evidence_state`): `active` = approved,
source approved, in force today (M3 predicate, policy date Asia/Ho_Chi_Minh); `candidate` =
`review_required` or `expert_review`; `inactive` = everything else. Each candidate row records the two
states and the policy date the database saw. `independence` is `same_document`, `same_source` or
`independent_source`.

A candidate involving a tenant claim carries the tenant scope (the more private of the two).

## 4. Privileges and evidence lifetime

- Both tables: RLS on, **no policy**, every privilege revoked from `public`, `anon`, `authenticated`
  and `service_role`; `service_role` may `SELECT`. Tenants and other clients read nothing.
- Rows are written only inside the two recording functions (`SECURITY DEFINER`, `search_path = ''`,
  static SQL, `EXECUTE` for `service_role` only), guarded by the M2 write marker.
- Append-only: no `UPDATE` and no `TRUNCATE` for any role, the owner included. A row is deleted only
  by the cascade of its chunk or document version, which M1 allows only for a version that was never
  approved and is not under expert review.
- Recording is idempotent and safe under concurrency (unique keys; a second writer waits and inserts
  nothing).

## 5. Rollback

Order: **M4, M3, M2, M1**. The M3 rollback refuses while M4 is installed. The M4 rollback drops only
what M4 added and needs `set local knowledge.m4_rollback_evidence_exported = 'yes'` (it deletes the
stored rows). It changes no status and no retrieval behaviour.

## 6. Measured behaviour (synthetic fixtures only)

`backend/tests/test_knowledge_contradictions.py::test_measured_behaviour_on_the_controlled_fixtures`:
20 hand-labelled synthetic pairs, 12 that must not be flagged and 8 that must. Result: 8 flagged, 8
correct, 0 false positives, 0 misses.

This measures the rules against their own specification. **It is not a scientific validation** and
says nothing about real guidance documents. No real corpus was measured.

## 7. Known limits

- **Reviewers cannot see the candidates yet.** Only `service_role` reads the tables. There is no
  read RPC and the M2 approval flow does not consult them, so a version with a stored contradiction
  can still be approved. Showing candidates to the expert reviewer is a separate change that needs an
  owner decision (it touches the review flow).
- The analysis runs only when an operator starts it, for one version, on a local stack.
- Context the extractor does not read is not compared: variety, region, soil, season, conditions
  ("nếu đất phèn ..."). Two statements about different varieties are reported as `contradiction`
  (two tests document this false positive).
- Only quantities are paired. Opposite qualitative assertions raise no candidate.
- Unitless values (scaling factors, ratios without `%`), `kg`, `lít`, `giờ`, `tháng`, `năm` are not
  normalized.
- The label is fixed when the row is written. A later status change does not rewrite it; a new run
  on another policy date adds a new row.
- Around midnight (Asia/Ho_Chi_Minh), or at an exact tolerance boundary, the analysis and the
  database can disagree. The database then refuses the whole proposal (`23514`); run it again.
- A person with `service_role` can record claims for any document. The rows are still bound to the
  real chunk text, and the classification is the database's.

## 8. Tests

- `backend/tests/test_knowledge_contradictions.py` (pure): extraction, ambiguity, equivalent units,
  contradictions, stages, context, versions, inactive evidence, boundaries, tolerance, determinism,
  the measurement above.
- `backend/tests/test_rag_knowledge_m4_claims.py` (database, real roles): RLS and privileges, span
  binding, invalid claims, idempotence, append-only, cascade, classification refusal, supersession
  chain, validity windows, expired/quarantined/archived/rejected material, tenant and farm isolation,
  no effect on retrieval or approval, concurrent extraction and analysis, CLI, rollback order.
- `test_knowledge_architecture.py`, `test_rag_knowledge_storage.py`, `test_rag_knowledge_status_events.py`,
  `test_rag_knowledge_m3_validity.py`: inventories and the rollback chain updated for M4.

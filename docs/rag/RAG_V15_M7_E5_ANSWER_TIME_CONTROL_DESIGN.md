# RAG V1.5 M7 E5: answer-time integrity control (DESIGN, not implemented)

Status: **design** (#75). **Implemented local/CI only in `RAG_V15_M7_E5_ANSWER_TIME_CONTROL.md`** (migration
20261114120000); no deployment. dev3-01 stays OPEN.

## 1. Gap

E2 and E7 protect the path to approval. Once a version IS approved (correctly, or by an attributable human error),
the answer path cites whatever retrieval returns (`test_rag_source_integrity_gap.py` pins this). E5 asks what the
answer path itself must re-check between retrieval and response emission. It cannot decide whether an approved
text is TRUE; it can only refuse evidence that is no longer admissible or not what retrieval returned.

## 2. What exists today (inspected)

- Retrieval: `public.match_knowledge_chunks_lexical` (H-a: verified assurance on version and source, in force, M3
  dates, tenant scope), SECURITY INVOKER under the caller's JWT.
- `rag_application.evidence_from_row`: refuses an unknown `approval_assurance`; labels demo rows.
- Orchestrator: `validate_citations` (a citation must name a chunk retrieved for this request), grounding, rule
  codes, the consistency gate (`answer_consistency.py`); trusted citation display fields come from chunk metadata.
- Nothing re-checks status between retrieval and emission; nothing re-checks chunk content hashes at answer time.

## 3. Proposed controls

| # | Control | Where | Note |
|---|---|---|---|
| C1 | Citations only to chunks returned by THIS request's authorized retrieval | exists (`validate_citations`) | keep; add a regression for a model that cites an id it saw in another request |
| C2 | Re-validate cited evidence just before emission: version still `approved`, source `approved`, assurance `verified`, in force today, not quarantined / archived / expired | new SECURITY INVOKER RPC `public.knowledge_cited_evidence_state(chunk_ids[])` called once per answer | closes the window between retrieval and response (status change mid-request) |
| C3 | Chunk identity: the cited `chunk_id` maps to the same `content_sha256` and `document_version` that retrieval returned | same RPC returns hashes; compare in the orchestrator | detects a swapped version under the same id |
| C4 | Unknown or non-verified assurance at emission: refuse the citation (fail closed), the answer degrades to `insufficient_evidence` for that part | orchestrator | never relabel silently |
| C5 | Unsupported claims are not turned into authoritative recommendations: a recommendation needs a stored rule code AND at least one C2-valid citation; integrity findings of the cited version that were resolved as `false_positive` are surfaced as a caveat, not hidden | orchestrator + E2 tables (read through a definer RPC that returns only finding types, never content) | caveat text is trusted copy |
| C6 | Status change between retrieval and emission: re-check (C2) is the last step before `to_response`; on any failure the whole model answer is discarded (as the consistency gate does) | `rag_qa.RagQuestionService.answer` | |
| C7 | Audit: the M6.1 citation event (local/CI) records C2 outcomes | #70 | not on hosted |

Not proposed: an LLM as approval authority or as a truth oracle; automatic quarantine from the answer path.

## 4. Tests to write with the implementation

Status flips to `quarantined` between retrieval and emission (two connections); expired between the two; a
cited id with a different content hash; a model citing an id from another request; demo / unrecorded assurance
at emission; a recommendation whose only citation fails C2; the frozen dev3-01 fixture approved through a
recorded false-positive: C5 caveat present, answer still bounded by the rule code. The characterization test can
flip only if the full system (approval gates + C2-C6) prevents the dev3-01 failure for the case it pins.

## 5. Cost and risk

One extra RPC per answered question (indexed lookups on chunk ids); a race where a just-approved version is not
yet visible degrades to `insufficient_evidence`, never to an unsafe answer.

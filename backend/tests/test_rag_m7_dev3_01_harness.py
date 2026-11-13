"""RAG V1.5 M7 evidence harness for dev3-01 (docs/rag/RAG_V15_M7_DEV3_01_HARNESS.md). DETERMINISTIC: no
LLM, no provider, no network. The frozen fixture is the benchmark's `poisoned_claim` chunk (the dev3-01
text) and the scripted model that cites it (tests/test_rag_source_integrity_gap.py).

It measures each control separately, on ACTUAL system behaviour (the real database retrieval feeds the
real answer service):
  A. detection  : the offline integrity review flags both poisoned assertions;
  B. human gate : how the expert-review gate responds to the unresolved evidence;
  C. quarantine : the emergency procedure removes the chunk from retrieval;
  D. answer side: what the answer service does with what retrieval actually returns, before and after;
  E. gaps       : what is missing for M7 (verified references, binding of the report to the review).

It does NOT flip tests/test_rag_source_integrity_gap.py and does NOT mark dev3-01 fixed: stage D shows
that while the poisoned version is approved and not quarantined the trusted path still cites it.
Every text and identity is a SYNTHETIC TEST FIXTURE. This file holds the offline stages (A, E); the
database stages (B, C, D) are in test_rag_knowledge_m7_dev3_01_replay.py.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.rag_llm_benchmark as bench  # noqa: E402
from knowledge.integrity.claims import ClaimSource  # noqa: E402
from knowledge.integrity.references import load_registry  # noqa: E402
from knowledge.integrity.review import review  # noqa: E402

from tests.test_rag_source_integrity_gap import CitesPoisonModel, _service  # noqa: E402

POISON = bench.CHUNK_PRESETS["poisoned_claim"]
CLEAN = bench.AWD_CHUNKS[0]
REGISTRY_FILE = Path(__file__).resolve().parent.parent / "knowledge" / "integrity" / "reference_registry.json"
POISON_PARAMETERS = {"ch4.rice.emission_eliminated", "records.water.not_required"}


def _registry():
    return load_registry(json.loads(REGISTRY_FILE.read_text(encoding="utf-8")))


# ================================================================== A. detection (offline)

def test_a_the_integrity_review_detects_both_poisoned_assertions_but_against_unverified_references():
    result = review([ClaimSource("fixture/poison@v1", POISON["chunk_id"], POISON["content"]),
                     ClaimSource("fixture/awd@v1", CLEAN["chunk_id"], CLEAN["content"])],
                    registry=_registry(), as_of=date(2026, 11, 13))
    conflicts = result.of_type("reference_conflict")
    flagged = {c.parameter for f in conflicts for c in result.claims if c.claim_id in f.claim_ids}
    assert flagged == POISON_PARAMETERS                                     # detected
    assert all(f.needs_expert_review for f in conflicts) and result.decision == "none"   # non-blocking
    # the references it is judged against are NOT human-verified primary sources (evidence gap E1)
    statuses = {e.verification_status for e in _registry().entries if e.parameter in POISON_PARAMETERS}
    assert statuses and "verified" not in statuses
    # the clean chunk is not flagged
    assert not [f for f in result.findings if f.needs_expert_review and "fixture/awd@v1" in f.document_refs]


# ================================================================== E. what M7 still lacks

def test_e_the_characterization_stays_unflipped():
    """The pinned gap still holds: with the poisoned chunk approved and retrieved, the trusted path cites
    it. Detection is non-blocking and quarantine needs a human; nothing at answer time judges content."""
    from tests.test_rag_source_integrity_gap import _case
    run = bench.run_case(_service(CitesPoisonModel()), _case())
    assert run["outcome"] == "generated" and run["source_integrity_failure"] is True


def test_e_no_verified_numeric_reference_exists_for_any_comparison():
    from knowledge.integrity import reference_numeric as rn
    from tests.test_knowledge_reference_numeric import NUMERIC_FILE
    assert rn.load_numeric_registry(json.loads(NUMERIC_FILE.read_text(encoding="utf-8"))).entries == ()

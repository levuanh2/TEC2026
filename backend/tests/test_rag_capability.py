"""Generation capability: access follows what a generator may PRODUCE, not an
intent's name. READ buys INFORMATIONAL answers (no recommendation slot);
ACTION_PRODUCING needs Core V1 WRITE. The capability comes from the trusted
intent policy — never from the caller or the model.

Free text of an INFORMATIONAL answer can still phrase advice. That is NOT
solved here (no keyword test pretends it is): it is decision D8, a required
gate before any real generator serves READ-tier requests
(test_rag_architecture.py::test_no_answer_generator_is_wired_until_d8_is_closed).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from recommendation.rag import (
    CAPABILITY_ACCESS,
    INTENT_POLICIES,
    AccessLevel,
    GenerationCapability,
    GenerationInput,
    InformationalAnswer,
    InvalidGeneratedSchema,
    RagAccessDenied,
    RagIntent,
    RagMode,
    RagQuestionRequest,
    required_access,
)
from tests.fixtures.rag_fakes import SEASON_ID
from tests.test_rag_orchestrator import FACT_ONLY, GROUNDED, READ_ONLY, WHAT_IF_ANSWER, Harness

INFORMATIONAL, ACTION = GenerationCapability.INFORMATIONAL, GenerationCapability.ACTION_PRODUCING
READ, WRITE = AccessLevel.READ, AccessLevel.WRITE


@pytest.mark.parametrize(("intent", "capability", "access"), [
    (RagIntent.EXPLAIN, INFORMATIONAL, READ),
    (RagIntent.COMPARE, INFORMATIONAL, READ),
    (RagIntent.EVIDENCE, INFORMATIONAL, READ),
    (RagIntent.DATA_GAP, INFORMATIONAL, READ),
    (RagIntent.RECOMMEND, ACTION, WRITE),
    (RagIntent.WHAT_IF, ACTION, WRITE),
])
def test_intent_maps_to_capability_and_capability_to_access(intent, capability, access):
    policy = INTENT_POLICIES[intent]
    assert policy.capability is capability
    assert policy.access is access is CAPABILITY_ACCESS[capability]
    assert required_access(intent, RagMode.ASK) is access
    assert policy.may_recommend is (capability is ACTION)


def test_every_intent_has_a_policy_and_access_is_derived_from_capability_only():
    assert set(INTENT_POLICIES) == set(RagIntent)
    assert CAPABILITY_ACCESS == {INFORMATIONAL: READ, ACTION: WRITE}


def test_preview_needs_write_whatever_the_capability():
    assert {required_access(intent, RagMode.PREVIEW) for intent in RagIntent} == {WRITE}


# -- UNKNOWN ---------------------------------------------------------------------------

def test_unknown_has_no_generation_capability_and_never_escalates():
    policy = INTENT_POLICIES[RagIntent.UNKNOWN]
    assert policy.capability is None and policy.access is READ and not policy.may_recommend
    h = Harness(granted=READ, output=GROUNDED)
    for intent in (None, "unknown"):
        assert h.ask(intent=intent).status == "needs_clarification"
    assert "generate" not in h.calls and h.carbon.calls == []
    assert set(h.resolver.levels) == {READ}


# -- capability is trusted, never requested ----------------------------------------------

@pytest.mark.parametrize("smuggled", [
    {"capability": "action_producing"},
    {"capability": "informational"},
    {"access": "write"},
])
def test_caller_cannot_request_a_capability_or_access(smuggled):
    with pytest.raises(ValidationError):
        RagQuestionRequest.model_validate({"question": "q", "crop_season_id": SEASON_ID, "intent": "explain",
                                           **smuggled})


@pytest.mark.parametrize(("intent", "capability"), [("explain", ACTION), ("recommend", INFORMATIONAL)])
def test_generation_input_capability_must_be_the_intent_policy(intent, capability):
    with pytest.raises(ValidationError, match="not the policy of intent"):
        GenerationInput(question="q", intent=intent, capability=capability, facts=(), evidence=())


@pytest.mark.parametrize(("intent", "expected"), [
    ("explain", INFORMATIONAL), ("compare", INFORMATIONAL), ("evidence", INFORMATIONAL),
    ("data_gap", INFORMATIONAL), ("recommend", ACTION), ("what_if", ACTION),
])
def test_generator_receives_the_capability_from_the_trusted_policy(intent, expected):
    if intent == "what_if":
        h = Harness(output=WHAT_IF_ANSWER)
        h.what_if()
    elif intent == "recommend":
        h = Harness()
        h.ask()
    else:
        setup, request = READ_ONLY[intent]
        h = Harness(**setup)
        h.ask(intent=intent, **request)
    assert h.generator.inputs[0].capability is expected


# -- INFORMATIONAL output has no action slot -------------------------------------------------

def test_informational_schema_has_no_recommendation_or_action_slot():
    assert not {"recommendations", "actions", "rule_code"} & set(InformationalAnswer.model_fields)


@pytest.mark.parametrize("intent", ["explain", "compare", "evidence", "data_gap"])
@pytest.mark.parametrize("recommendations", [GROUNDED["recommendations"], []])
def test_informational_generation_cannot_emit_recommendations(intent, recommendations):
    setup, request = READ_ONLY[intent]
    output = {**setup["output"], "recommendations": recommendations}
    h = Harness(**{**setup, "output": output})
    with pytest.raises(InvalidGeneratedSchema):
        h.ask(intent=intent, **request)


def test_informational_answer_is_returned_without_recommendations():
    result = Harness(granted=READ, output=FACT_ONLY).ask(intent="explain")
    assert result.status == "generated" and result.recommendations == ()


# -- ACTION_PRODUCING needs WRITE ------------------------------------------------------------

@pytest.mark.parametrize("run", [lambda h: h.ask(), lambda h: h.what_if()])
def test_action_producing_generation_never_runs_without_write(run):
    h = Harness(granted=READ, output=GROUNDED)
    with pytest.raises(RagAccessDenied):
        run(h)
    assert h.resolver.levels == [WRITE] and "generate" not in h.calls and h.carbon.calls == []


def test_action_producing_generation_may_return_structured_recommendations():
    result = Harness(granted=WRITE).ask()
    assert result.recommendations and result.recommendations[0].title

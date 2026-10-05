"""Fact usage: READ access to a Core V1 row is not permission for an
INFORMATIONAL answer to republish it as advice. Stored recommendation signals
and what-if impacts are ACTION_CONTEXT by their trusted SOURCE FIELD (never by
reading their text); actual Carbon, metrics, readiness, CV observations and
finalized benchmarks are INFORMATIONAL_SAFE. An INFORMATIONAL generation never
sees, references or renders ACTION_CONTEXT; an ACTION_PRODUCING one may.

Core V1 read behaviour is unchanged: a viewer/manager still reads the stored
recommendation through GET /crop-seasons/{id}/recommendations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from recommendation.rag import (
    CAPABILITY_FACT_USAGE,
    FACT_USAGE,
    AccessLevel,
    FactKind,
    FactReferenceMismatch,
    FactUsage,
    GeneratedAnswer,
    GenerationCapability,
    GenerationInput,
    GroundedFact,
    RagIntent,
    RagMode,
    build_fact_catalog,
    build_season_context,
    usable_facts,
    validate_grounding,
)
from recommendation.rag import orchestrator as orchestrator_module
from tests.fixtures.rag_fakes import AWD_RULE, FakeFactsSource, benchmark_row, public_chunk, scope, signal_row
from tests.test_rag_orchestrator import GROUNDED, Harness

SAFE, ACTION = FactUsage.INFORMATIONAL_SAFE, FactUsage.ACTION_CONTEXT
INFORMATIONAL, ACTION_PRODUCING = GenerationCapability.INFORMATIONAL, GenerationCapability.ACTION_PRODUCING
EVIDENCE = (public_chunk("c1"), public_chunk("c2"))
CARBON = {"calculation_id": "calc-1", "total_co2e_kg": 2900.0, "input_hash": "abc", "engine_version": "1",
          "ef_config_version": "factors-2026",
          "breakdown": [{"category": "rice_ch4", "gas": "CH4", "source": "rice_methane", "co2e_kg": 2500.0}]}
SIGNAL = f"current.signal.{AWD_RULE}"
ACTION_FACTS = [f"{SIGNAL}.title", f"{SIGNAL}.reason", f"{SIGNAL}.compared_to", f"{SIGNAL}.status",
                f"{SIGNAL}.impact_status", f"{SIGNAL}.co2e_total_kg_before", f"{SIGNAL}.co2e_total_kg_after",
                f"{SIGNAL}.co2e_total_kg_delta", f"{SIGNAL}.co2e_percent_delta"]


def _context(**source):
    return build_season_context(scope(), FakeFactsSource(calls=[], carbon=CARBON, **source), mode=RagMode.ASK)


def _catalog(**source) -> dict[str, GroundedFact]:
    return {fact.fact_id: fact for fact in build_fact_catalog(_context(**source))}


def _ground(fact_id: str, intent: RagIntent, **source):
    context = _context(**source)
    answer = GeneratedAnswer.model_validate({
        "status": "generated", "answer": "Giá trị {{fact:%s}}." % fact_id, "fact_refs": [{"fact_id": fact_id}],
        "evidence_refs": [{"source_id": "guide-awd", "chunk_id": "c1"}]})
    return validate_grounding(answer, intent=intent, evidence=EVIDENCE, facts=build_fact_catalog(context),
                              rule_codes=context.signal_rule_codes)


# -- classification ----------------------------------------------------------------------

def test_every_fact_kind_has_a_trusted_usage():
    assert set(FACT_USAGE) == set(FactKind)
    assert {kind for kind, usage in FACT_USAGE.items() if usage is ACTION} == {FactKind.RULE_SIGNAL, FactKind.WHAT_IF}


def test_stored_recommendation_fields_are_action_context_by_source_not_by_text():
    neutral = _catalog(signals=[signal_row(title="Thông tin", reason="Ghi nhận")])
    for fact_id in ACTION_FACTS:
        assert neutral[fact_id].usage is ACTION, fact_id


@pytest.mark.parametrize("fact_id", [
    "current.carbon.total_co2e_kg", "current.carbon.breakdown.0", "current.metrics.co2e_per_kg",
    "current.metrics.total_co2e_kg", "current.metrics.yield_kg", "current.season.ipcc_water_regime",
    "current.completeness.water",
])
def test_actual_measured_or_calculated_facts_are_informational_safe(fact_id):
    assert _catalog()[fact_id].usage is SAFE


def test_recommendation_impact_cannot_masquerade_as_the_actual_carbon_value():
    catalog = _catalog()
    actual, impact_before = catalog["current.carbon.total_co2e_kg"], catalog[f"{SIGNAL}.co2e_total_kg_before"]
    assert actual.value == impact_before.value == 2900.0          # same number, different meaning
    assert (actual.kind, actual.usage) == (FactKind.CARBON_TOTAL, SAFE)
    assert (impact_before.kind, impact_before.usage) == (FactKind.RULE_SIGNAL, ACTION)


def test_capabilities_allow_only_their_usages():
    assert CAPABILITY_FACT_USAGE == {INFORMATIONAL: frozenset({SAFE}), ACTION_PRODUCING: frozenset({SAFE, ACTION})}
    facts = build_fact_catalog(_context())
    assert {f.usage for f in usable_facts(facts, INFORMATIONAL)} == {SAFE}
    assert {f.usage for f in usable_facts(facts, ACTION_PRODUCING)} == {SAFE, ACTION}


# -- usage is trusted ----------------------------------------------------------------------

def test_fact_usage_cannot_be_supplied():
    with pytest.raises(ValidationError):
        GroundedFact(fact_id="x", kind=FactKind.RULE_SIGNAL, value="Cân nhắc tưới AWD", source="s",
                     usage="informational_safe")


def test_fact_usage_cannot_be_changed():
    fact = _catalog()[f"{SIGNAL}.title"]
    with pytest.raises((ValidationError, AttributeError, TypeError)):
        fact.usage = SAFE  # type: ignore[misc]
    assert fact.model_copy(update={"provenance": {}}).usage is ACTION


def test_generator_cannot_attach_a_usage_to_a_fact_reference():
    with pytest.raises(ValidationError):
        GeneratedAnswer.model_validate({"status": "generated", "answer": "x",
                                        "fact_refs": [{"fact_id": "current.metrics.co2e_per_kg",
                                                       "usage": "informational_safe"}]})


def test_unclassified_kind_fails_closed_to_action_context(monkeypatch):
    monkeypatch.delitem(FACT_USAGE, FactKind.CV_SIGNAL)
    fact = GroundedFact(fact_id="current.cv.0.label", kind=FactKind.CV_SIGNAL, value="blast", source="cv_service")
    assert fact.usage is ACTION


# -- grounding enforcement --------------------------------------------------------------------

@pytest.mark.parametrize("intent", [RagIntent.EXPLAIN, RagIntent.DATA_GAP])
@pytest.mark.parametrize("fact_id", ["current.carbon.total_co2e_kg", "current.metrics.co2e_per_kg",
                                     "current.carbon.breakdown.0"])
def test_informational_answer_may_use_actual_carbon_and_metric_facts(intent, fact_id):
    _ground(fact_id, intent)


def test_informational_compare_may_use_a_finalized_benchmark():
    _ground("benchmark.water-htx-2026", RagIntent.COMPARE, benchmark_rows=[benchmark_row()])


@pytest.mark.parametrize("intent", [RagIntent.EXPLAIN, RagIntent.COMPARE, RagIntent.EVIDENCE, RagIntent.DATA_GAP])
@pytest.mark.parametrize("fact_id", ACTION_FACTS)
def test_informational_answer_cannot_use_stored_recommendation_facts(intent, fact_id):
    with pytest.raises(FactReferenceMismatch, match="action_context"):
        _ground(fact_id, intent, benchmark_rows=[benchmark_row()])


@pytest.mark.parametrize("fact_id", ACTION_FACTS)
def test_action_producing_answer_may_use_action_context(fact_id):
    _ground(fact_id, RagIntent.RECOMMEND)


# -- orchestrator: see, reference, render, return ---------------------------------------------------

def test_informational_generation_never_sees_action_context():
    h = Harness(granted=AccessLevel.READ,
                output={"status": "generated", "answer": "Cường độ {{fact:current.metrics.co2e_per_kg}}.",
                        "fact_refs": [{"fact_id": "current.metrics.co2e_per_kg"}]})
    result = h.ask(intent="explain")
    sent = h.generator.inputs[0]
    assert sent.facts and {fact.usage for fact in sent.facts} == {SAFE}
    assert result.signals == () and result.basis is not None and result.basis.signal_rule_codes == ()


def test_action_producing_generation_sees_and_returns_stored_signals():
    h = Harness()
    result = h.ask()
    assert ACTION in {fact.usage for fact in h.generator.inputs[0].facts}
    assert result.signals and result.signals[0].rule_code == AWD_RULE
    assert result.basis is not None and result.basis.signal_rule_codes == (AWD_RULE,)


def test_generation_input_rejects_action_context_for_informational():
    facts = build_fact_catalog(_context())
    with pytest.raises(ValidationError, match="may not see"):
        GenerationInput(question="q", intent="explain", capability=INFORMATIONAL, facts=facts, evidence=())
    GenerationInput(question="q", intent="recommend", capability=ACTION_PRODUCING, facts=facts, evidence=())


def test_forbidden_reference_stops_at_grounding_and_never_reaches_the_renderer(monkeypatch):
    rendered: list[set[str]] = []
    real = orchestrator_module.render_answer
    monkeypatch.setattr(orchestrator_module, "render_answer",
                        lambda answer, facts: rendered.append(set(facts)) or real(answer, facts))
    title = f"{SIGNAL}.title"
    h = Harness(output={"status": "generated", "answer": "Khuyến nghị {{fact:%s}}." % title,
                        "fact_refs": [{"fact_id": title}]})
    with pytest.raises(FactReferenceMismatch, match="action_context"):
        h.ask(intent="explain")
    assert rendered == []
    Harness(output={"status": "generated", "answer": "Cường độ {{fact:current.metrics.co2e_per_kg}}.",
                    "fact_refs": [{"fact_id": "current.metrics.co2e_per_kg"}]}).ask(intent="explain")
    assert rendered and not any(fact_id.startswith("current.signal.") for fact_id in rendered[-1])


def test_informational_insufficient_result_carries_no_stored_signals():
    result = Harness(chunks=()).ask(intent="evidence")
    assert result.status == "insufficient_evidence" and result.signals == ()
    action = Harness(chunks=()).ask()
    assert action.status == "insufficient_evidence" and action.signals


def test_recommend_output_is_unchanged_by_the_usage_policy():
    result = Harness(output=GROUNDED).ask()
    assert result.status == "generated" and result.recommendations

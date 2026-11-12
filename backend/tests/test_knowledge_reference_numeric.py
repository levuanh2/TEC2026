"""M5 foundation (backend/knowledge/integrity/reference_numeric.py): the numeric reference entry
format, the closed unit / conversion model and the comparison.

Pure unit tests: no database, network or provider. EVERY NUMBER, URL, HASH AND NAME BELOW IS A
SYNTHETIC TEST FIXTURE. None is an agronomic, inventory or legal reference value, the artifact hash
is the hash of no real file, and "SYNTHETIC TEST FIXTURE" is not a person. Entries are marked
`synthetic: true`, which the production loader refuses.

dev3-01 stays OPEN: a finding is a review aid and changes nothing.
"""

from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from knowledge.integrity import reference_numeric as rn
from knowledge.integrity.claims import PARAMETERS, UNITS
from knowledge.integrity.references import RegistryError, load_registry

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
INTEGRITY = BACKEND / "knowledge" / "integrity"
NUMERIC_FILE = INTEGRITY / "reference_registry_numeric.json"
SHA_A = hashlib.sha256(b"synthetic artifact, not a real file").hexdigest()
SHA_E = hashlib.sha256(b"synthetic evidence note, not a real file").hexdigest()


def entry(**changes) -> dict:
    """A complete, human-verified SYNTHETIC entry: an emission rate with a printed range."""
    raw = {
        "reference_id": "ref-synthetic-rate",
        "kind": "numeric",
        "synthetic": True,
        "parameter": "ch4.emission_factor",
        "value": {"point": "2.50", "min": "2.00", "max": "3.00", "range_basis": "synthetic interval (as printed)"},
        "unit_as_printed": "kg CH4 ha-1 d-1",
        "unit": "kgCH4/ha/day",
        "quantity_semantics": {"kind": "emission_factor", "relative_to": None,
                               "numerator": "CH4 mass", "denominator": "area x time"},
        "conditions": ["synthetic condition one"],
        "scope": {"region": "Synthetic Region", "tier": "synthetic tier"},
        "source": {"title": "SYNTHETIC TEST FIXTURE guideline", "publisher": "SYNTHETIC TEST FIXTURE publisher",
                   "edition": "0000", "effective_date": "2000-01-01", "url": "https://example.invalid/synthetic.pdf",
                   "artifact_sha256": SHA_A, "artifact_bytes": 1234,
                   "locator": {"table": "Table S.1", "pdf_page": 7, "printed_page": "S.7", "row": "Synthetic row"}},
        "rights": {"status": "cleared", "basis": "synthetic fixture, written for this test",
                   "reference": "this test file", "restrictions": "none"},
        "comparison": {"claim_parameter": "ch4.emission_factor", "claim_unit": "kgCH4/ha/day",
                       "conversion": "identity", "required_claim_conditions": ["baseline"],
                       "tolerance": {"mode": "printed_range"}},
        "verification": {"machine_read": {"tool": "none (synthetic)", "date": "2026-11-12"},
                         "human": {"status": "verified", "verified_by": "SYNTHETIC TEST FIXTURE",
                                   "verified_at": "2026-11-12",
                                   "evidence_ref": "docs/rag/reference-evidence/ref-synthetic-rate.md",
                                   "evidence_sha256": SHA_E}},
        "limitations": ["synthetic"],
    }
    for path, value in changes.items():
        node, keys = raw, path.split("__")
        for key in keys[:-1]:
            node = node[key]
        if value is _DROP:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return raw


_DROP = object()


def doc(*entries) -> dict:
    return {"schema": rn.NUMERIC_REGISTRY_SCHEMA, "registry_version": "synthetic.1", "entries": list(entries)}


def load_one(raw: dict) -> rn.NumericReference:
    return rn.load_numeric_registry(doc(raw), allow_synthetic=True).entries[0]


def pending(**changes) -> dict:
    return entry(verification__human={"status": "pending", "verified_by": None, "verified_at": None,
                                      "evidence_ref": None, "evidence_sha256": None}, **changes)


def claim(low="2.2", high=None, *, parameter="ch4.emission_factor", unit="kgCH4/ha/day",
          conditions=("baseline",), region="Synthetic Region") -> rn.ClaimValue:
    return rn.ClaimValue(parameter, unit, Decimal(low), Decimal(high or low), frozenset(conditions), region)


# ================================================================== the committed registry

def test_the_committed_numeric_registry_holds_no_entry_and_the_schema_1_registry_no_numeric_value():
    """M5 foundation inserts NO canonical numeric entry. When a first entry is proposed, this test
    must be replaced by one that checks its evidence file exists and matches evidence_sha256."""
    data = json.loads(NUMERIC_FILE.read_text(encoding="utf-8"))
    registry = rn.load_numeric_registry(data)                       # production rules: no synthetic
    assert registry.entries == () and data["entries"] == []
    old = load_registry(json.loads((INTEGRITY / "reference_registry.json").read_text(encoding="utf-8")))
    assert all(e.kind == "qualitative" for e in old.entries)
    evidence_dir = REPO / rn.EVIDENCE_DIR
    assert not evidence_dir.exists() or not [p for p in evidence_dir.iterdir() if p.suffix == ".pdf"]


def test_no_source_pdf_is_stored_next_to_the_registry():
    assert not [p.name for p in INTEGRITY.iterdir() if p.suffix.lower() == ".pdf"]


# ================================================================== the closed model

def test_the_unit_and_rule_tables_are_closed_and_dimensionally_consistent():
    assert {u: d for u, d in rn.REFERENCE_UNITS.items() if u in UNITS} == UNITS      # M4 units keep their dimension
    assert set(rn.REFERENCE_UNITS) - set(UNITS) == {"kgN2O-N/kgN"}
    assert rn.REFERENCE_UNITS["kgN2O-N/kgN"] not in set(UNITS.values())               # its own dimension
    assert set(rn.CONVERSION_RULES) == {"identity", "percent_of_applied_n_to_fraction"}
    identity, percent = rn.CONVERSION_RULES["identity"], rn.CONVERSION_RULES["percent_of_applied_n_to_fraction"]
    assert (identity.claim_unit, identity.reference_unit, identity.factor, identity.preconditions) \
        == (None, None, Decimal(1), frozenset())
    assert (percent.claim_unit, percent.reference_unit, percent.factor) == ("percent", "kgN2O-N/kgN", Decimal("0.01"))
    assert percent.preconditions == {"base:applied_n", "quantity:n2o_n"}
    for rule in rn.CONVERSION_RULES.values():
        assert rule.rationale.strip() and rule.factor > 0
        assert rule.claim_unit is None or rule.claim_unit in UNITS
        assert rule.reference_unit is None or rule.reference_unit in rn.REFERENCE_UNITS


def test_a_complete_entry_loads_with_exact_decimals_and_every_evidence_field():
    e = load_one(entry())
    assert (e.point, e.range_min, e.range_max) == (Decimal("2.50"), Decimal("2.00"), Decimal("3.00"))
    assert str(e.point) == "2.50"                                    # as printed, not a float
    assert (e.unit_as_printed, e.unit, e.dimension) == ("kg CH4 ha-1 d-1", "kgCH4/ha/day", "emission_rate")
    assert (e.source.publisher, e.source.edition, e.source.effective_date) \
        == ("SYNTHETIC TEST FIXTURE publisher", "0000", "2000-01-01")
    assert e.source.url.startswith("https://") and e.source.artifact_sha256 == SHA_A
    assert e.source.locator == {"table": "Table S.1", "pdf_page": 7, "printed_page": "S.7", "row": "Synthetic row"}
    assert e.conditions == ("synthetic condition one",) and e.region == "Synthetic Region"
    assert (e.rights_basis, e.rights_restrictions) == ("synthetic fixture, written for this test", "none")
    assert (e.human_status, e.verified_by, e.evidence_sha256) == ("verified", "SYNTHETIC TEST FIXTURE", SHA_E)
    assert e.usable and e.synthetic


def test_the_digest_is_stable_and_changes_with_any_field():
    a = rn.load_numeric_registry(doc(entry()), allow_synthetic=True)
    assert rn.load_numeric_registry(copy.deepcopy(doc(entry())), allow_synthetic=True).digest == a.digest
    assert rn.load_numeric_registry(doc(entry(value__point="2.51")), allow_synthetic=True).digest != a.digest


# ================================================================== what the loader refuses

@pytest.mark.parametrize("changes, message", [
    ({"synthetic": False, "reference_id": "REF bad"}, "reference_id"),
    ({"kind": "quantity"}, "kind must be 'numeric'"),
    # values: decimal strings exactly as printed
    ({"value__point": 2.5}, "decimal string"),
    ({"value__point": "2,5"}, "decimal string"),
    ({"value__point": "1e3"}, "decimal string"),
    ({"value__point": "NaN"}, "decimal string"),
    ({"value__point": "3.50"}, "value.min <= value.point <= value.max"),
    ({"value__max": _DROP}, "decimal string"),
    ({"value__range_basis": _DROP}, "range_basis is required"),
    ({"unit_as_printed": ""}, "unit_as_printed is required"),
    # units and dimensions
    ({"unit": "kg"}, "unit must be one of"),
    ({"unit": None}, "unit must be one of"),
    ({"quantity_semantics__kind": "ratio"}, "quantity_semantics.kind"),
    ({"quantity_semantics__relative_to": "something"}, "relative_to is for scaling"),
    ({"quantity_semantics__numerator": ""}, "numerator is required"),
    ({"conditions": []}, "conditions must be a list"),
    # source evidence
    ({"source__url": "http://example.invalid/x.pdf"}, "https://"),
    ({"source__url": None}, "https://"),
    ({"source__publisher": ""}, "publisher is required"),
    ({"source__edition": _DROP}, "edition is required"),
    ({"source__artifact_sha256": "ABC"}, "64 lowercase hex"),
    ({"source__artifact_sha256": None}, "64 lowercase hex"),
    ({"source__artifact_bytes": 0}, "positive integer"),
    ({"source__effective_date": None}, "effective_date_note must say why"),
    ({"source__effective_date": "2019"}, "ISO date"),
    ({"source__locator__pdf_page": 0}, "pdf_page"),
    ({"source__locator__pdf_page": "7"}, "pdf_page"),
    ({"source__locator__table": _DROP}, "exact table or equation"),
    # rights
    ({"rights__status": "not_cleared"}, "rights are not cleared"),
    ({"rights__status": "fair_use"}, "rights.status"),
    ({"rights__basis": " "}, "basis is required"),
    ({"rights__restrictions": _DROP}, "restrictions is required"),
    # comparison
    ({"comparison__conversion": "ratio"}, "comparison.conversion must be"),
    ({"comparison__conversion": None}, "comparison.conversion must be"),
    ({"comparison__claim_parameter": "made.up"}, "claim_parameter"),
    ({"comparison__claim_unit": "percent"}, "does not fit"),
    ({"comparison__tolerance": {"mode": "absolute", "value": "0.5"}}, "cannot be entered"),
    ({"comparison__tolerance": {"mode": "exact", "value": "0.5"}}, "cannot be entered"),
    ({"comparison__required_claim_conditions": ["Has Spaces"]}, "condition tags"),
    # verification
    ({"verification__human__status": "approved"}, "human.status"),
    ({"verification__human__verified_by": ""}, "named person"),
    ({"verification__human__verified_at": "yesterday"}, "ISO date"),
    ({"verification__human__evidence_ref": "docs/other/file.md"}, "evidence_ref"),
    ({"verification__human__evidence_ref": "docs/rag/reference-evidence/../../x.md"}, "evidence_ref"),
    ({"verification__human__evidence_sha256": None}, "evidence_sha256"),
    ({"verification__human__evidence_sha256": SHA_A}, "separate record"),
    ({"verification__machine_read__date": "12/11/2026"}, "ISO date"),
])
def test_an_incomplete_or_overreaching_entry_is_refused(changes, message):
    with pytest.raises(RegistryError, match=message):
        load_one(entry(**changes))


def test_synthetic_entries_never_enter_a_production_registry():
    with pytest.raises(RegistryError, match="synthetic test fixtures are refused"):
        rn.load_numeric_registry(doc(entry()))
    with pytest.raises(RegistryError, match="unique"):
        rn.load_numeric_registry(doc(entry(), entry()), allow_synthetic=True)
    with pytest.raises(RegistryError, match="schema must be"):
        rn.load_numeric_registry({**doc(), "schema": "kn-reference-registry-1"})
    with pytest.raises(RegistryError, match="schema must be"):
        load_registry(doc())                                         # and the schema-1 loader refuses schema 2


def test_a_pending_entry_cannot_name_a_verifier_and_a_verified_one_must():
    assert not load_one(pending()).usable
    with pytest.raises(RegistryError, match="pending entry names no verifier"):
        load_one(entry(verification__human__status="pending"))


def test_a_dimensionless_factor_takes_no_unit_and_no_conversion():
    factor = dict(unit=None, unit_as_printed="(none; ratio)",
                  quantity_semantics={"kind": "scaling_factor", "relative_to": "synthetic reference condition",
                                      "numerator": "emission under the regime", "denominator": "emission under the reference"},
                  value={"point": "0.50"},
                  comparison={"claim_parameter": None, "claim_unit": None, "conversion": "none",
                              "required_claim_conditions": [], "tolerance": {"mode": "exact"}})
    e = load_one(entry(**factor))
    assert (e.unit, e.dimension, e.conversion, e.relative_to) == (None, None, "none", "synthetic reference condition")
    for unit in ("percent", "kgCH4/ha/day"):                         # no borrowed unit
        with pytest.raises(RegistryError, match="dimensionless"):
            load_one(entry(**{**factor, "unit": unit}))
    with pytest.raises(RegistryError, match="relative to"):
        load_one(entry(**{**factor, "quantity_semantics": {**factor["quantity_semantics"], "relative_to": None}}))
    for rule in rn.CONVERSION_RULES:                                 # and no rule reaches it from a claim
        with pytest.raises(RegistryError, match="no conversion from a claim"):
            load_one(entry(**{**factor, "comparison": {"claim_parameter": "ch4.reduction", "claim_unit": "percent",
                                                       "conversion": rule, "required_claim_conditions":
                                                           sorted(rn.CONVERSION_RULES[rule].preconditions),
                                                       "tolerance": {"mode": "exact"}}}))
    with pytest.raises(RegistryError, match="conversion 'none' takes no claim"):
        load_one(entry(**{**factor, "comparison": {**factor["comparison"], "claim_parameter": "ch4.reduction"}}))


def test_a_rule_is_bound_to_its_units_and_its_preconditions():
    with pytest.raises(RegistryError, match="identity needs the claim unit"):
        load_one(entry(unit="kgCH4/ha", comparison__claim_parameter=_first_parameter("areal_co2e"),
                       comparison__claim_unit="kgCO2e/ha"))
    percent_parameter = _first_parameter("ratio")
    n2o = dict(unit="kgN2O-N/kgN", unit_as_printed="kg N2O-N (kg N)-1",
               value={"point": "0.010", "min": "0.005", "max": "0.020", "range_basis": "synthetic"},
               quantity_semantics={"kind": "emission_factor", "relative_to": None, "numerator": "N2O-N mass",
                                   "denominator": "applied N mass"},
               comparison={"claim_parameter": percent_parameter, "claim_unit": "percent",
                           "conversion": "percent_of_applied_n_to_fraction",
                           "required_claim_conditions": ["base:applied_n", "quantity:n2o_n"],
                           "tolerance": {"mode": "printed_range"}})
    assert load_one(entry(**n2o)).dimension == "n2o_n_per_applied_n"
    with pytest.raises(RegistryError, match="requires the claim conditions"):
        load_one(entry(**{**n2o, "comparison": {**n2o["comparison"], "required_claim_conditions": ["base:applied_n"]}}))
    with pytest.raises(RegistryError, match="converts percent to kgN2O-N/kgN only"):
        load_one(entry(comparison__conversion="percent_of_applied_n_to_fraction",
                       comparison__required_claim_conditions=["base:applied_n", "quantity:n2o_n"]))
    with pytest.raises(RegistryError, match="identity needs the claim unit"):     # percent is not that fraction
        load_one(entry(**{**n2o, "comparison": {**n2o["comparison"], "conversion": "identity"}}))


def _first_parameter(dimension: str) -> str:
    return next(name for name, spec in sorted(PARAMETERS.items()) if spec[0] == dimension)


# ================================================================== comparison

def test_a_claim_inside_or_outside_the_printed_range():
    e = load_one(entry())
    inside, outside, straddling = rn.compare(claim("2.2", "2.8"), e), rn.compare(claim("3.5"), e), \
        rn.compare(claim("2.5", "3.5"), e)
    assert (inside.outcome, inside.is_mismatch) == ("within_printed_range", False)
    assert rn.compare(claim("2.00", "3.00"), e).outcome == "within_printed_range"     # the bounds are inside
    assert (outside.outcome, outside.is_mismatch) == ("outside_printed_range", True)
    assert straddling.outcome == "outside_printed_range"
    assert (outside.normalized_min, outside.normalized_max) == (Decimal("3.5"), Decimal("3.5"))


def test_every_mismatch_keeps_the_source_evidence_and_the_comparison_rationale():
    e = load_one(entry())
    f = rn.compare(claim("3.5"), e)
    assert f.is_mismatch and f.reference_id == "ref-synthetic-rate"
    assert (f.source_url, f.artifact_sha256) == (e.source.url, SHA_A)
    assert f.locator == {"table": "Table S.1", "pdf_page": 7, "printed_page": "S.7", "row": "Synthetic row"}
    assert (f.reference_point, f.reference_min, f.reference_max, f.reference_unit, f.unit_as_printed) \
        == (Decimal("2.50"), Decimal("2.00"), Decimal("3.00"), "kgCH4/ha/day", "kg CH4 ha-1 d-1")
    assert f.conversion == "identity" and "identity:" in f.rationale and "synthetic interval (as printed)" in f.rationale


def test_exact_mode_uses_no_tolerance_at_all():
    e = load_one(entry(value={"point": "2.50"}, comparison__tolerance={"mode": "exact"}))
    assert rn.compare(claim("2.5"), e).outcome == "equal_to_printed_value"            # 2.5 == 2.50 exactly
    for low, high in (("2.5000001", None), ("2.4", "2.6")):
        f = rn.compare(claim(low, high), e)
        assert f.outcome == "differs_from_printed_value" and f.is_mismatch and "prints no range" in f.rationale
    with pytest.raises(RegistryError, match="printed_range needs a printed range"):
        load_one(entry(value={"point": "2.50"}))


def test_an_unverified_reference_never_produces_a_mismatch():
    e = load_one(pending())
    for value in ("2.5", "999"):
        f = rn.compare(claim(value), e)
        assert (f.outcome, f.is_mismatch, f.normalized_min) == ("reference_unverified", False, None)


def test_different_quantities_units_scope_or_region_are_never_compared():
    e = load_one(entry())
    other_unit = rn.compare(claim("999", parameter=_first_parameter("areal_ch4"), unit="kgCH4/ha"), e)
    assert (other_unit.outcome, other_unit.normalized_min) == ("not_comparable", None)
    assert rn.compare(claim("999", conditions=()), e).outcome == "out_of_scope"       # does not state the baseline
    assert rn.compare(claim("999", region="Elsewhere"), e).outcome == "out_of_scope"
    assert rn.compare(claim("999", region=None), e).outcome == "out_of_scope"         # unknown is not a match
    worldwide = load_one(entry(scope__region=None))
    assert rn.compare(claim("999", region=None), worldwide).outcome == "outside_printed_range"
    factor = load_one(entry(unit=None, value={"point": "0.50"},
                            quantity_semantics={"kind": "scaling_factor", "relative_to": "reference",
                                                "numerator": "a", "denominator": "b"},
                            comparison={"claim_parameter": None, "claim_unit": None, "conversion": "none",
                                        "required_claim_conditions": [], "tolerance": {"mode": "exact"}}))
    percent = claim("50", parameter=_first_parameter("ratio"), unit="percent", conditions=())
    assert rn.compare(percent, factor).outcome == "not_comparable"                    # 50 percent is not SF 0.50


def test_the_percent_rule_converts_exactly_and_only_with_its_preconditions():
    parameter = _first_parameter("ratio")
    e = load_one(entry(unit="kgN2O-N/kgN", unit_as_printed="kg N2O-N (kg N)-1", scope__region=None,
                       value={"point": "0.010", "min": "0.005", "max": "0.020", "range_basis": "synthetic"},
                       quantity_semantics={"kind": "emission_factor", "relative_to": None, "numerator": "N2O-N mass",
                                           "denominator": "applied N mass"},
                       comparison={"claim_parameter": parameter, "claim_unit": "percent",
                                   "conversion": "percent_of_applied_n_to_fraction",
                                   "required_claim_conditions": ["base:applied_n", "quantity:n2o_n"],
                                   "tolerance": {"mode": "printed_range"}}))
    stated = ("base:applied_n", "quantity:n2o_n")
    ok = rn.compare(claim("0.7", parameter=parameter, unit="percent", conditions=stated, region=None), e)
    assert (ok.outcome, ok.normalized_min) == ("within_printed_range", Decimal("0.007"))
    high = rn.compare(claim("5", parameter=parameter, unit="percent", conditions=stated, region=None), e)
    assert (high.outcome, high.normalized_max) == ("outside_printed_range", Decimal("0.05"))
    # a bare percent, or a percent of N2O mass, is not that quantity
    for conditions in ((), ("base:applied_n",), ("base:applied_n", "quantity:n2o")):
        assert rn.compare(claim("5", parameter=parameter, unit="percent", conditions=conditions, region=None),
                          e).outcome == "out_of_scope"


def test_compare_is_deterministic_and_rejects_an_inverted_claim():
    e = load_one(entry())
    assert rn.compare(claim("2.2", "2.8"), e) == rn.compare(claim("2.2", "2.8"), e)
    with pytest.raises(ValueError):
        rn.compare(claim("3", "2"), e)

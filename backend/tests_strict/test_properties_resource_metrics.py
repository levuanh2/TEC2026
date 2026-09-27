"""Property-based tests for Resource Metrics aggregation (strict-ci.yml only).

Hypothesis is not a production dependency, so these live outside tests/ and run
in the strict workflow. They ADD to the example tests in
tests/test_metric_completeness_order.py; they replace none of them.

Properties, for any records in any order, on both the single-season and the
bulk (farm/organization/MRV) paths:
  * both paths agree;
  * one unknown quantity (None) -- or no record at all -- makes the metric unknown
    (None) and incomplete, never a partial sum and never 0;
  * otherwise the metric is the SUM of quantities and the ratio is sum / yield
    (never an average of per-record ratios);
  * the result does not depend on record order.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tests.test_metric_completeness_order import both_paths, repository  # noqa: E402

YIELD_KG = 1000.0  # the harvest in the shared fixture
quantity = st.one_of(st.none(), st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False))
records = st.lists(quantity, max_size=6)


def expected(values: list[float | None]) -> tuple[float | None, float | None, bool]:
    if not values or any(v is None for v in values):
        return None, None, False
    total = sum(values)
    return total, total / YIELD_KG, True


@settings(max_examples=300, deadline=None, derandomize=True)
@given(water=records, fertilizer=records, data=st.data())
def test_resource_metrics_properties(water, fertilizer, data):
    single, bulk = both_paths(repository(water, fertilizer))
    assert single == bulk

    for values, (amount_key, ratio_key, group) in ((water, ("water_m3", "water_per_kg", "water")),
                                                    (fertilizer, ("fertilizer_kg", "fertilizer_per_kg", "fertilizer"))):
        total, ratio, complete = expected(values)
        assert single["data_completeness"][group] is complete
        if total is None:
            assert single[amount_key] is None and single[ratio_key] is None
        else:
            assert single[amount_key] == pytest.approx(total)
            assert single[ratio_key] == pytest.approx(ratio)

    # Order independence. Plain float `sum()` is not associative: a different
    # record order can move the last binary digit (found by this test,
    # 1048578.0586978386 vs ...388). Values agree to 1e-12 relative; exact
    # equality would need math.fsum in the aggregation (finding F-METRICS-FSUM).
    shuffled_water = data.draw(st.permutations(water))
    shuffled_fert = data.draw(st.permutations(fertilizer))
    s2, b2 = both_paths(repository(list(shuffled_water), list(shuffled_fert)))
    for before, after in ((single, s2), (bulk, b2)):
        assert before["data_completeness"] == after["data_completeness"]
        for key, value in before.items():
            if isinstance(value, float):
                assert after[key] == pytest.approx(value, rel=1e-12), key
            else:
                assert after[key] == value, key

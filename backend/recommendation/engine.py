"""Recommendation Engine — orchestrates rules for one crop season.

Deliberately thin: it owns none of the domain logic itself (that lives in
`rules.py`), and it does not touch persistence (that's
`infrastructure/recommendation_repo.py` via `service.RecommendationService`).
Adding a rule means adding one function call here, not editing FastAPI route
handlers.
"""

from __future__ import annotations

from typing import Any

from .rules import (
    CarbonCalculator,
    GeneratedRecommendation,
    evaluate_awd_rule,
    evaluate_data_completeness,
)

ENGINE_VERSION = "1"


def generate_recommendations(
    crop_season_id: str, *, carbon: CarbonCalculator, metrics: dict[str, Any],
) -> list[GeneratedRecommendation]:
    out: list[GeneratedRecommendation] = []
    awd = evaluate_awd_rule(crop_season_id, carbon)
    if awd is not None:
        out.append(awd)
    out.extend(evaluate_data_completeness(crop_season_id, metrics))
    return out

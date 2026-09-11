"""M05 Recommendation Engine — deterministic, versioned rules only.

No LLM, no free-text advice without deterministic evidence (brief FW M05
§B3). Carbon-impact evidence always comes from re-invoking the existing
Carbon Engine (`carbon.calculate_carbon`) with an alternate scenario; this
package never duplicates CH4/N2O/GWP math.
"""

from .engine import ENGINE_VERSION, generate_recommendations
from .rules import (
    AWD_RULE_CODE,
    AWD_RULE_VERSION,
    DATA_TASK_RULE_CODE,
    DATA_TASK_RULE_VERSION,
    CarbonCalculator,
    GeneratedRecommendation,
    evaluate_awd_rule,
    evaluate_data_completeness,
)

__all__ = [
    "ENGINE_VERSION",
    "AWD_RULE_CODE",
    "AWD_RULE_VERSION",
    "DATA_TASK_RULE_CODE",
    "DATA_TASK_RULE_VERSION",
    "CarbonCalculator",
    "GeneratedRecommendation",
    "evaluate_awd_rule",
    "evaluate_data_completeness",
    "generate_recommendations",
]

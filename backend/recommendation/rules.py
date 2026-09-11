"""M05 deterministic recommendation rules.

Every rule is a pure function producing zero or one `GeneratedRecommendation`.
No rule implements CH4/N2O math itself — an `optimization` rule's evidence
always comes from re-invoking the existing Carbon Engine (via a
`CarbonCalculator`-shaped object, i.e. `service.CarbonService`) with an
alternate scenario on the same crop season; the impact is simply
`before.total_co2e_kg - after.total_co2e_kg`. A `data_task` rule never claims
a quantified carbon/resource impact — it is operational guidance, not an
optimization result (brief FW M05 §B4/R3).

Reproducibility: a rule's own version (`rule_version`) plus the Carbon
Engine's `input_hash`/`engine_version` for `optimization` rows (or a plain
digest of the triggering condition for `data_task` rows) are stored verbatim
so a recommendation can be explained/reproduced later without re-deriving it
from prose.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from carbon import CarbonEngineError

logger = logging.getLogger("agricarbon.recommendation")


class CarbonCalculator(Protocol):
    """Structural contract satisfied by `service.CarbonService`.

    Accepting only this shape (not the concrete class) keeps rule tests free
    to inject a fixture-backed stub without touching Supabase.
    """

    def calculate(self, crop_season_id: str, scenario: str = "as_recorded", *, persist: bool = True) -> Any: ...


@dataclass
class GeneratedRecommendation:
    rule_code: str
    rule_version: str
    type: str  # "optimization" | "data_task"
    title: str
    reason: str
    compared_to: str | None
    impact_status: str  # "available" | "unavailable"
    impact_unavailable_reason: str | None
    co2e_total_kg_before: float | None
    co2e_total_kg_after: float | None
    co2e_total_kg_delta: float | None
    co2e_percent_delta: float | None
    evidence: dict[str, Any] = field(default_factory=dict)
    input_hash: str = ""
    engine_version: str | None = None


# ===========================================================================
# R1 — AWD irrigation opportunity (docs/modules/05-ai-recommendation.md's
# `water_regime_continuous` rule)
# ===========================================================================

AWD_RULE_CODE = "water.awd_from_continuous_flooding"
AWD_RULE_VERSION = "1"
_CONTINUOUS_FLOODING_REGIME = "irrigated_continuous_flooding"
_AWD_TITLE = "Cân nhắc tưới AWD (ướt khô xen kẽ)"
_AWD_COMPARED_TO = "Kịch bản AWD tính bởi Carbon Engine trên cùng dữ liệu vụ này"


def evaluate_awd_rule(crop_season_id: str, carbon: CarbonCalculator) -> GeneratedRecommendation | None:
    """Recommend AWD only when all of the following hold:

    1. The season's `as_recorded` Carbon Engine calculation succeeds (real
       production is currently blocked on `gwp.ch4` — this legitimately
       returns None for every real season today; see docs/CARBON_METHOD.md
       OI-05). No baseline -> nothing to evaluate, not a fabricated maybe.
    2. The recorded regime is literally continuous flooding — the rule does
       not fire for AWD-already, rainfed, or any other regime.
    3. The `awd` scenario also calculates successfully (same engine, same
       season data, only the water regime input changes).
    4. The resulting CO2e delta is strictly positive — never recommend AWD
       "because it's generally better" (brief §B15).
    """
    try:
        baseline = carbon.calculate(crop_season_id, "as_recorded", persist=False)
    except CarbonEngineError:
        return None
    except Exception:
        # A transient infra failure (e.g. the Supabase connection dropping
        # mid-request) is not a methodology signal — it must not crash
        # generation for the whole season (data_task rules still need to
        # run). Log it distinctly from an expected CarbonEngineError so an
        # operator can tell the two apart; the farmer just sees this rule
        # skipped for now, exactly as if the baseline weren't calculable.
        logger.exception("recommendation_awd_baseline_failed crop_season_id=%s", crop_season_id)
        return None

    if baseline.result.water_regime_applied != _CONTINUOUS_FLOODING_REGIME:
        return None

    reason = (
        "Vụ đang ghi nhận chế độ tưới ngập liên tục. So sánh trực tiếp bằng "
        "Carbon Engine trên chính dữ liệu vụ này cho thấy chuyển sang AWD có "
        "thể giảm phát thải CH4."
    )

    try:
        proposed = carbon.calculate(crop_season_id, "awd", persist=False)
    except CarbonEngineError as exc:
        unavailable_reason = str(exc)
    except Exception:
        logger.exception("recommendation_awd_proposed_failed crop_season_id=%s", crop_season_id)
        unavailable_reason = "Tạm thời không thể ước tính kịch bản AWD — vui lòng thử lại sau."
    else:
        unavailable_reason = None

    if unavailable_reason is not None:
        return GeneratedRecommendation(
            rule_code=AWD_RULE_CODE, rule_version=AWD_RULE_VERSION, type="optimization",
            title=_AWD_TITLE, reason=reason, compared_to=_AWD_COMPARED_TO,
            impact_status="unavailable", impact_unavailable_reason=unavailable_reason,
            co2e_total_kg_before=None, co2e_total_kg_after=None,
            co2e_total_kg_delta=None, co2e_percent_delta=None,
            evidence={
                "baseline_input_hash": baseline.result.input_hash,
                "baseline_water_regime": baseline.result.water_regime_applied,
            },
            input_hash=baseline.result.input_hash,
            engine_version=baseline.result.engine_version,
        )

    delta = baseline.result.total_co2e_kg - proposed.result.total_co2e_kg
    if delta <= 0:
        return None

    percent = delta / baseline.result.total_co2e_kg if baseline.result.total_co2e_kg else None

    return GeneratedRecommendation(
        rule_code=AWD_RULE_CODE, rule_version=AWD_RULE_VERSION, type="optimization",
        title=_AWD_TITLE, reason=reason, compared_to=_AWD_COMPARED_TO,
        impact_status="available", impact_unavailable_reason=None,
        co2e_total_kg_before=baseline.result.total_co2e_kg,
        co2e_total_kg_after=proposed.result.total_co2e_kg,
        co2e_total_kg_delta=delta,
        co2e_percent_delta=percent,
        evidence={
            "baseline_input_hash": baseline.result.input_hash,
            "proposed_input_hash": proposed.result.input_hash,
            "baseline_water_regime": baseline.result.water_regime_applied,
            "proposed_water_regime": proposed.result.water_regime_applied,
            "ef_config_version": baseline.result.ef_config_version,
        },
        # Keyed on the baseline input: the same recorded activity data always
        # reproduces the same recommendation (brief §B12 idempotent generation).
        input_hash=baseline.result.input_hash,
        engine_version=baseline.result.engine_version,
    )


# ===========================================================================
# R3 — data completeness (brief §B4/R3: never a quantified optimization
# impact, a separate `data_task` type)
# ===========================================================================

DATA_TASK_RULE_CODE = "data.completeness"
DATA_TASK_RULE_VERSION = "1"
_NOT_A_QUANTIFIED_RESULT = "Đây là gợi ý bổ sung dữ liệu, không phải khuyến nghị tối ưu hoá có định lượng."

_DATA_TASKS: tuple[tuple[str, str, str], ...] = (
    # (metrics key checked, title, reason)
    ("yield", "Ghi sản lượng thu hoạch",
     "Vụ này chưa có sản lượng thu hoạch hợp lệ — mọi chỉ số trên mỗi kg "
     "(nước, phân bón, chi phí, carbon) đều cần sản lượng để tính."),
    ("water", "Bổ sung lượng nước tưới",
     "Một hoặc nhiều lần tưới của vụ này còn thiếu lượng nước — chỉ số Nước/kg lúa chưa tính được."),
    ("fertilizer", "Bổ sung khối lượng phân bón",
     "Một hoặc nhiều lần bón phân của vụ này còn thiếu khối lượng — chỉ số Phân bón/kg lúa chưa tính được."),
    ("cost", "Bổ sung chi phí vật tư",
     "Một hoặc nhiều hoạt động của vụ này còn thiếu chi phí — chỉ số Chi phí/kg lúa chưa tính được."),
)


def evaluate_data_completeness(crop_season_id: str, metrics: dict[str, Any]) -> list[GeneratedRecommendation]:
    completeness = metrics.get("data_completeness") or {}
    present = {
        "yield": metrics.get("yield_kg") is not None,
        "water": bool(completeness.get("water")),
        "fertilizer": bool(completeness.get("fertilizer")),
        "cost": bool(completeness.get("cost")),
    }
    out: list[GeneratedRecommendation] = []
    for key, title, reason in _DATA_TASKS:
        if present[key]:
            continue
        input_hash = hashlib.sha256(f"{crop_season_id}:{key}".encode("utf-8")).hexdigest()
        out.append(GeneratedRecommendation(
            rule_code=f"{DATA_TASK_RULE_CODE}.{key}", rule_version=DATA_TASK_RULE_VERSION, type="data_task",
            title=title, reason=reason, compared_to=None,
            impact_status="unavailable", impact_unavailable_reason=_NOT_A_QUANTIFIED_RESULT,
            co2e_total_kg_before=None, co2e_total_kg_after=None,
            co2e_total_kg_delta=None, co2e_percent_delta=None,
            evidence={"missing_metric": key}, input_hash=input_hash, engine_version=None,
        ))
    return out

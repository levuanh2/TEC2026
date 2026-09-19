"""Which Carbon inputs a season is still missing, and where the user fixes each.

This exists so a client can say "Thiếu chế độ nước trước vụ" instead of a generic
"chưa tính được", WITHOUT reimplementing any methodology in the client.

Scope discipline: every check here is a **field-presence** check on the same
`CropActivityData` the engine consumes — `x is None`. No threshold, no factor, no
formula lives here. The scientific rules stay in `methodology.py`; this module
only reports which of that module's required inputs are absent, and names the UI
flow that supplies each one.

Drift safety: `tests/test_carbon_readiness.py` asserts that an empty result means
the engine really does calculate, and that removing any single required input
makes this module name exactly that input. If `methodology.py` ever starts
requiring something new, that test fails rather than this list quietly going stale.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .models import CropActivityData

# Where the user goes to supply a missing input. The client maps these to routes;
# it does not decide which input needs which flow.
FLOW_METHODOLOGY = "carbon_methodology"   # season "Thông tin phương pháp tính" panel
FLOW_ACTIVITY = "activity"                # the journal form named by `activity_type`
FLOW_PLOT = "plot"                        # plot record (area), not a farmer journal form


@dataclass(frozen=True)
class MissingInput:
    code: str
    label: str
    detail: str
    flow: str
    activity_type: str | None = None
    #: False when the input only costs precision (intensity) rather than blocking
    #: the calculation outright.
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fertilizer(data: CropActivityData) -> list[MissingInput]:
    if any(a.n_content_pct is None for a in data.fertilizer):
        return [MissingInput(
            code="fertilizer_nitrogen",
            label="Thiếu hàm lượng Nitơ của lần bón phân",
            detail="Một hoặc nhiều lần bón phân chưa có hàm lượng đạm (%). Không có giá trị này thì "
                   "không tính được N₂O — engine không đoán 46 %.",
            flow=FLOW_ACTIVITY, activity_type="fertilizer",
        )]
    return []


def _straw(data: CropActivityData) -> list[MissingInput]:
    """Mirrors the branches in `methodology.classify_straw`, presence-only."""
    out: list[MissingInput] = []
    add = lambda code, label, detail: out.append(MissingInput(  # noqa: E731
        code=code, label=label, detail=detail, flow=FLOW_ACTIVITY, activity_type="straw_management"))
    for event in data.straw:
        if event.method == "removed":
            continue
        if event.method == "burned":
            if event.mass_kg is None:
                add("straw_mass", "Thiếu khối lượng rơm",
                    "Bản ghi đốt rơm chưa có khối lượng rơm.")
            if event.dry_matter_fraction is None:
                add("straw_dry_matter", "Thiếu tỷ lệ chất khô của rơm",
                    "Đốt rơm tính theo khối lượng khô, nên cần tỷ lệ chất khô (0–1).")
            continue
        if event.method in ("incorporated", "composted"):
            if event.method == "composted" and event.returned_to_field is None:
                add("straw_returned_to_field", "Thiếu thông tin rơm có trả lại ruộng hay không",
                    "Rơm ủ compost trả lại ruộng thì tính vào phát thải, mang đi nơi khác thì không.")
                continue
            if event.method == "composted" and not event.returned_to_field:
                continue
            if event.method == "incorporated" and event.days_before_cultivation is None:
                add("straw_days_before_cultivation", "Thiếu số ngày vùi rơm trước khi làm đất",
                    "Vùi sát vụ và vùi sớm cho kết quả chênh nhau nhiều lần.")
            if event.mass_kg is None:
                add("straw_mass", "Thiếu khối lượng rơm",
                    "Bản ghi xử lý rơm chưa có khối lượng rơm.")
            if event.dry_matter_fraction is None:
                add("straw_dry_matter", "Thiếu tỷ lệ chất khô của rơm",
                    "Lượng rơm trả lại ruộng tính theo khối lượng khô, nên cần tỷ lệ chất khô (0–1).")
    # One record missing a field and another missing the same field is one user task.
    seen: set[str] = set()
    return [m for m in out if not (m.code in seen or seen.add(m.code))]


def _area(detail: str = "Thửa ruộng của vụ này chưa có diện tích (ha).") -> MissingInput:
    return MissingInput(code="area", label="Thiếu diện tích thửa", detail=detail, flow=FLOW_PLOT)


def _water_regime(
    detail: str = "Cách giữ nước trong vụ quyết định lượng khí CH₄ phát thải.",
) -> MissingInput:
    return MissingInput(code="water_regime", label="Thiếu chế độ nước trong vụ",
                        detail=detail, flow=FLOW_METHODOLOGY)


def missing_inputs(data: CropActivityData) -> list[MissingInput]:
    """Every Carbon input the season still lacks, in the order a user would fix them."""
    out: list[MissingInput] = []

    if not data.area_ha:
        out.append(_area())
    if data.water_regime is None:
        out.append(_water_regime())
    if data.pre_season_water_regime is None:
        out.append(MissingInput(
            code="pre_season_water_regime", label="Thiếu chế độ nước trước vụ",
            detail="Tình trạng ngập nước trước khi vào vụ ảnh hưởng trực tiếp tới CH₄.",
            flow=FLOW_METHODOLOGY,
        ))
    if data.recorded_cultivation_days is None:
        out.append(MissingInput(
            code="cultivation_days", label="Thiếu số ngày canh tác",
            detail="Cần số ngày canh tác, hoặc đủ cả ngày gieo sạ và ngày thu hoạch.",
            flow=FLOW_METHODOLOGY,
        ))

    out.extend(_fertilizer(data))
    out.extend(_straw(data))

    if data.fuel:
        out.append(MissingInput(
            code="fuel_factor_unverified", label="Vụ có ghi nhiên liệu nhưng chưa có hệ số đã xác minh",
            detail="Hệ số phát thải nhiên liệu chưa được xác minh, nên vụ có bản ghi nhiên liệu "
                   "chưa tính được. Đây là giới hạn của bộ hệ số, không phải do bạn nhập thiếu.",
            flow=FLOW_ACTIVITY, activity_type="fuel",
        ))

    # Not blocking: the total is still produced, only the per-kg intensity is not.
    if data.yield_kg is None:
        out.append(MissingInput(
            code="harvest_yield", label="Chưa ghi sản lượng thu hoạch",
            detail="Vẫn tính được tổng CO₂e, nhưng chưa có cường độ phát thải trên mỗi kg lúa.",
            flow=FLOW_ACTIVITY, activity_type="harvest", blocking=False,
        ))
    return out


def _summary(missing: list[MissingInput]) -> dict[str, Any]:
    blocking = [m for m in missing if m.blocking]
    return {
        "can_calculate": not blocking,
        "missing_inputs": [m.to_dict() for m in missing],
        "blocking_count": len(blocking),
    }


def readiness(data: CropActivityData) -> dict[str, Any]:
    """Serializable readiness summary for the API."""
    return _summary(missing_inputs(data))


def mapping_refused(*, area_missing: bool, detail: str) -> dict[str, Any]:
    """Readiness when the row mapper refuses before a `CropActivityData` exists.

    The mapper refuses for exactly two user-fixable reasons: the plot has no
    area (fixed on the plot record), or irrigation records cannot be mapped to
    an IPCC class (fixed by declaring the water regime, which the mapper
    prefers over inference). Routing both to the water-regime panel would send
    a farmer with a missing area to a form that cannot fix it.
    """
    return _summary([_area(detail) if area_missing else _water_regime(detail)])


__all__ = ["MissingInput", "missing_inputs", "readiness", "mapping_refused",
           "FLOW_METHODOLOGY", "FLOW_ACTIVITY", "FLOW_PLOT"]

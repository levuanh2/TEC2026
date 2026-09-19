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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, asdict, replace
from typing import Any

from .models import CropActivityData

# Where the user goes to supply a missing input. The client maps these to routes;
# it does not decide which input needs which flow.
FLOW_METHODOLOGY = "carbon_methodology"   # season "Thông tin phương pháp tính" panel
FLOW_ACTIVITY = "activity"                # edit the exact records listed in `records`
FLOW_PLOT = "plot"                        # plot record (area), not a farmer journal form
#: Not fixable by entering data: the verified factor set lacks what the record
#: needs. Clients must show this as a limitation, never as a form to fill.
FLOW_FACTOR_UNAVAILABLE = "factor_unavailable"


@dataclass(frozen=True)
class RecordRef:
    """Which stored activity record an issue is about.

    Deliberately NOT a field on the engine's input model: `CropActivityData` is
    hashed for reproducibility and must not carry storage identity. The service
    passes these alongside, one list per activity type, in the same order the
    mapper emitted the engine's records.
    """
    activity_id: str
    occurred_on: str | None = None   # YYYY-MM-DD
    label: str | None = None         # what the farmer called it (fertilizer name, …)


#: activity_type -> refs, parallel to the matching `CropActivityData` list.
RecordRefs = Mapping[str, Sequence[RecordRef]]


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
    #: The records to open, for activity-level issues. Empty when the caller had
    #: no record identity (pure engine-model checks) — the issue is still named.
    records: tuple[RecordRef, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["records"] = [asdict(r) for r in self.records]
        return out


def _ref(refs: RecordRefs | None, activity_type: str, index: int, expected: int) -> tuple[RecordRef, ...]:
    """The ref for record `index`, or nothing when refs are absent or do not line
    up with the engine's list — a wrong record is worse than no record."""
    seq = (refs or {}).get(activity_type)
    if seq is None or len(seq) != expected:
        return ()
    return (seq[index],)


def _merge(entries: list[MissingInput]) -> list[MissingInput]:
    """Several records missing the same field are one user task listing them all."""
    merged: dict[str, MissingInput] = {}
    for m in entries:
        prior = merged.get(m.code)
        merged[m.code] = m if prior is None else replace(prior, records=prior.records + m.records)
    return list(merged.values())


def _fertilizer(data: CropActivityData, refs: RecordRefs | None) -> list[MissingInput]:
    n = len(data.fertilizer)
    return _merge([
        MissingInput(
            code="fertilizer_nitrogen",
            label="Thiếu hàm lượng Nitơ của lần bón phân",
            detail="Một hoặc nhiều lần bón phân chưa có hàm lượng đạm (%). Không có giá trị này thì "
                   "không tính được N₂O — engine không đoán 46 %.",
            flow=FLOW_ACTIVITY, activity_type="fertilizer",
            records=_ref(refs, "fertilizer", i, n),
        )
        for i, a in enumerate(data.fertilizer) if a.n_content_pct is None
    ])


def _straw(data: CropActivityData, refs: RecordRefs | None) -> list[MissingInput]:
    """Mirrors the branches in `methodology.classify_straw`, presence-only."""
    out: list[MissingInput] = []
    n = len(data.straw)
    for i, event in enumerate(data.straw):
        record = _ref(refs, "straw_management", i, n)
        add = lambda code, label, detail: out.append(MissingInput(  # noqa: E731
            code=code, label=label, detail=detail, flow=FLOW_ACTIVITY,
            activity_type="straw_management", records=record))
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
    return _merge(out)


def _area(detail: str = "Thửa ruộng của vụ này chưa có diện tích (ha).") -> MissingInput:
    return MissingInput(code="area", label="Thiếu diện tích thửa", detail=detail, flow=FLOW_PLOT)


def _water_regime(
    detail: str = "Cách giữ nước trong vụ quyết định lượng khí CH₄ phát thải.",
) -> MissingInput:
    return MissingInput(code="water_regime", label="Thiếu chế độ nước trong vụ",
                        detail=detail, flow=FLOW_METHODOLOGY)


def missing_inputs(data: CropActivityData, refs: RecordRefs | None = None) -> list[MissingInput]:
    """Every Carbon input the season still lacks, in the order a user would fix them.

    `refs` only adds record identity to activity-level issues; it never changes
    which issues are reported.
    """
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

    out.extend(_fertilizer(data, refs))
    out.extend(_straw(data, refs))

    if data.fuel:
        n = len(data.fuel)
        out.append(MissingInput(
            code="fuel_factor_unverified", label="Vụ có ghi nhiên liệu nhưng chưa có hệ số đã xác minh",
            detail="Hệ số phát thải nhiên liệu chưa được xác minh, nên vụ có bản ghi nhiên liệu "
                   "chưa tính được. Đây là giới hạn của bộ hệ số, không phải do bạn nhập thiếu.",
            flow=FLOW_FACTOR_UNAVAILABLE, activity_type="fuel",
            records=tuple(r for i in range(n) for r in _ref(refs, "fuel", i, n)),
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


def readiness(data: CropActivityData, refs: RecordRefs | None = None) -> dict[str, Any]:
    """Serializable readiness summary for the API."""
    return _summary(missing_inputs(data, refs))


def mapping_refused(*, area_missing: bool, detail: str) -> dict[str, Any]:
    """Readiness when the row mapper refuses before a `CropActivityData` exists.

    The mapper refuses for exactly two user-fixable reasons: the plot has no
    area (fixed on the plot record), or irrigation records cannot be mapped to
    an IPCC class (fixed by declaring the water regime, which the mapper
    prefers over inference). Routing both to the water-regime panel would send
    a farmer with a missing area to a form that cannot fix it.
    """
    return _summary([_area(detail) if area_missing else _water_regime(detail)])


__all__ = ["MissingInput", "RecordRef", "RecordRefs", "missing_inputs", "readiness", "mapping_refused",
           "FLOW_METHODOLOGY", "FLOW_ACTIVITY", "FLOW_PLOT", "FLOW_FACTOR_UNAVAILABLE"]

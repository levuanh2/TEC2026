"""Các bộ tính phát thải theo từng nguồn.

Mỗi nguồn có phương pháp luận RIÊNG — `Activity Data × Emission Factor` chỉ là abstraction
ở tầng cao, không phải công thức áp chung. Chi tiết và trích dẫn: docs/CARBON_METHOD.md
và docs/CARBON_METHOD_SOURCES.md.

Không có hằng số phát thải nào trong file này. Mọi con số đến từ ParameterSet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import (
    MethodologyGapError,
    MissingActivityDataError,
)
from .factors import Parameter, ParameterSet
from .models import (
    PRE_SEASON_REGIMES,
    WATER_REGIMES,
    CropActivityData,
    OrganicAmendment,
    StrawEvent,
)

# Chế độ nước trong vụ -> khoá EF1FR (IPCC Table 11.1, chú thích 7).
_N2O_REGIME_KEY = {
    "irrigated_continuous_flooding": "continuous_flooding",
    "irrigated_single_drainage": "single_and_multiple_drainage",
    "irrigated_multiple_drainage": "single_and_multiple_drainage",
}

# Bảng 11.1 không tách EF1FR cho rainfed/deep water -> dùng giá trị gộp, có cảnh báo.
_N2O_AGGREGATE_REGIMES = ("rainfed_regular", "rainfed_drought_prone", "deep_water")


@dataclass
class BreakdownEntry:
    """Một dòng phân rã — phải đủ để tái hiện lại phép tính từ nguồn trích dẫn."""

    source: str
    gas: str
    activity_value: float
    activity_unit: str
    gas_kg: float
    co2e_kg: float
    formula: str
    factors_used: dict[str, float] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    parameter_status: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "gas": self.gas,
            "activity_value": self.activity_value,
            "activity_unit": self.activity_unit,
            "gas_kg": self.gas_kg,
            "co2e_kg": self.co2e_kg,
            "formula": self.formula,
            "factors_used": self.factors_used,
            "provenance": self.provenance,
            "parameter_status": self.parameter_status,
        }


def _record(
    entry_factors: dict[str, Parameter]
) -> tuple[dict[str, float], dict[str, str], dict[str, str]]:
    """Trả (giá trị, nguồn, trạng thái xác minh) theo đường dẫn config của từng tham số."""
    used = {p.path: p.value for p in entry_factors.values()}
    provenance = {p.path: (p.source or "") for p in entry_factors.values()}
    statuses = {p.path: p.status for p in entry_factors.values()}
    return used, provenance, statuses


# ===========================================================================
# Rơm rạ: phân luồng để KHÔNG double counting
# ===========================================================================
# IPCC 2019 Refinement, Vol.4, Ch.5, Table 5.14, chú thích a (nguyên văn):
#   "Straw application means that straws are incorporated into the soil. It does not
#    include cases where straws are just placed on soil surface, and straws that were
#    burnt on the field."
# => rơm VÙI đi vào SFo (điều chỉnh CH4), rơm ĐỐT đi vào nguồn đốt đồng riêng,
#    rơm MANG KHỎI RUỘNG không đi đâu cả. Mỗi bản ghi đúng một đường.


def classify_straw(events: list[StrawEvent], crop_id: str, area_ha: float) -> tuple[
    list[OrganicAmendment], list[StrawEvent]
]:
    """Tách các bản ghi rơm thành (chất hữu cơ cho SFo, rơm bị đốt).

    Raise MethodologyGapError khi thiếu thông tin để chọn đường — không đoán.
    """
    amendments: list[OrganicAmendment] = []
    burned: list[StrawEvent] = []

    for event in events:
        if event.method == "removed":
            continue  # không đóng góp nguồn nào

        if event.method == "burned":
            burned.append(event)
            continue

        if event.method in ("incorporated", "composted"):
            if event.method == "composted":
                if event.returned_to_field is None:
                    raise MethodologyGapError(
                        f"Vụ '{crop_id}': rơm được ủ compost nhưng chưa biết có trả lại ruộng "
                        f"hay không ('returned_to_field'). Trả lại ruộng thì tính vào SFo "
                        f"(CFOA compost = 0,17); mang đi nơi khác thì không tính. Engine không đoán."
                    )
                if not event.returned_to_field:
                    continue
                cfoa_key = "compost"
            else:
                if event.days_before_cultivation is None:
                    raise MethodologyGapError(
                        f"Vụ '{crop_id}': rơm được vùi vào đất nhưng thiếu "
                        f"'days_before_cultivation'. CFOA chênh hơn 5 lần giữa vùi <30 ngày "
                        f"trước canh tác (1,00) và >30 ngày (0,19) — IPCC Table 5.14. "
                        f"Engine không đoán."
                    )
                cfoa_key = (
                    "straw_incorporated_lt_30d"
                    if event.days_before_cultivation < 30
                    else "straw_incorporated_gt_30d"
                )

            if event.mass_kg is None:
                raise MissingActivityDataError(
                    f"Vụ '{crop_id}': bản ghi rơm '{event.method}' thiếu 'mass_kg'."
                )
            if event.dry_matter_fraction is None:
                raise MethodologyGapError(
                    f"Vụ '{crop_id}': bản ghi rơm '{event.method}' thiếu "
                    f"'dry_matter_fraction'. IPCC Eq 5.3 yêu cầu ROA tính theo **khối lượng khô** "
                    f"cho rơm rạ. Engine không đoán độ ẩm."
                )

            amendments.append(
                OrganicAmendment(
                    cfoa_key=cfoa_key,
                    rate_t_per_ha=event.mass_kg * event.dry_matter_fraction / 1000.0 / area_ha,
                    origin=f"straw:{event.method}",
                )
            )
            continue

        raise MethodologyGapError(
            f"Vụ '{crop_id}': phương pháp xử lý rơm '{event.method}' chưa được ánh xạ vào "
            f"phương pháp luận nào. Xem docs/CARBON_METHOD.md."
        )

    return amendments, burned


# ===========================================================================
# CH4 canh tác lúa
# ===========================================================================


class RiceMethaneCalculator:
    """IPCC 2019 Refinement, Vol.4, Ch.5, §5.5.

    Eq 5.1 : CH4[kg] = EFi × t[ngày] × A[ha]
    Eq 5.2 : EFi = EFc × SFw × SFp × SFo
    Eq 5.3 : SFo = (1 + Σ ROAi × CFOAi) ^ exponent
    """

    def compute_sfo(
        self, amendments: list[OrganicAmendment], params: ParameterSet
    ) -> tuple[float, dict[str, Parameter], list[dict[str, Any]]]:
        """SFo theo Eq 5.3. Không có chất hữu cơ -> (1 + 0)^exp = 1,0."""
        exponent = params.factor("ch4_rice", "sfo_exponent")
        used: dict[str, Parameter] = {"sfo_exponent": exponent}
        terms: list[dict[str, Any]] = []

        accumulated = 0.0
        for amendment in amendments:
            cfoa = params.factor("ch4_rice", "cfoa", amendment.cfoa_key)
            used[f"cfoa.{amendment.cfoa_key}"] = cfoa
            accumulated += amendment.rate_t_per_ha * cfoa.value
            terms.append(
                {
                    "origin": amendment.origin,
                    "roa_t_per_ha": amendment.rate_t_per_ha,
                    "cfoa_key": amendment.cfoa_key,
                    "cfoa": cfoa.value,
                }
            )

        return (1.0 + accumulated) ** exponent.value, used, terms

    def calculate(
        self,
        data: CropActivityData,
        regime: str,
        amendments: list[OrganicAmendment],
        params: ParameterSet,
        cultivation_days: int,
    ) -> BreakdownEntry:
        if data.pre_season_water_regime is None:
            raise MethodologyGapError(
                f"Vụ '{data.crop_season_id}' thiếu 'pre_season_water_regime'. IPCC Eq 5.2 bắt buộc có "
                f"SFp; ngập trước vụ ≥30 ngày làm SFp = 2,41 (tăng hơn gấp đôi so với 1,00). "
                f"Bỏ qua SFp là sai phương pháp luận, engine không mặc định."
            )
        if data.pre_season_water_regime not in PRE_SEASON_REGIMES:
            raise MethodologyGapError(
                f"'pre_season_water_regime' = '{data.pre_season_water_regime}' không hợp lệ. "
                f"Chỉ nhận: {', '.join(PRE_SEASON_REGIMES)}."
            )

        efc = params.factor("ch4_rice", "efc")
        sfw = params.factor("ch4_rice", "sfw", regime)
        sfp = params.factor("ch4_rice", "sfp", data.pre_season_water_regime)
        sfo_value, sfo_used, sfo_terms = self.compute_sfo(amendments, params)

        ef_i = efc.value * sfw.value * sfp.value * sfo_value
        activity_value = cultivation_days * data.area_ha
        ch4_kg = ef_i * activity_value

        gwp = params.gwp("ch4")
        used, provenance, statuses = _record(
            {"efc": efc, "sfw": sfw, "sfp": sfp, "gwp_ch4": gwp, **sfo_used}
        )
        used["_derived.sfo"] = sfo_value
        used["_derived.ef_i_kgCH4_per_ha_day"] = ef_i

        return BreakdownEntry(
            source="ch4_rice_cultivation",
            gas="ch4",
            activity_value=activity_value,
            activity_unit="ha_day",
            gas_kg=ch4_kg,
            co2e_kg=ch4_kg * gwp.value,
            formula=(
                "IPCC 2019 Refinement Eq 5.1 + 5.2: "
                "CH4 = (EFc × SFw × SFp × SFo) × cultivation_days × area_ha; "
                "SFo = (1 + Σ ROAi × CFOAi)^sfo_exponent (Eq 5.3); CO2e = CH4 × GWP_CH4"
            ),
            factors_used={**used, "_sfo_terms": sfo_terms},  # type: ignore[dict-item]
            provenance=provenance,
            parameter_status=statuses,
        )


# ===========================================================================
# N2O từ đầu vào đạm
# ===========================================================================


class FertilizerN2OCalculator:
    """IPCC 2019 Refinement, Vol.4, Ch.11.

    Eq 11.1 : N2O-N = F_FR × EF1FR
    N2O = N2O-N × 44/28 ; CO2e = N2O × GWP_N2O

    Hệ số áp lên **kg N**, KHÔNG phải kg phân bón.
    """

    def resolve_ef_key(self, regime: str, crop_id: str) -> tuple[str, str | None]:
        """Trả (khoá EF1FR, cảnh báo nếu có)."""
        if regime in _N2O_REGIME_KEY:
            return _N2O_REGIME_KEY[regime], None
        if regime in _N2O_AGGREGATE_REGIMES:
            return "aggregate", (
                f"Vụ '{crop_id}': chế độ nước '{regime}' không có EF1FR tách riêng trong "
                f"IPCC Table 11.1 (chú thích 7) — dùng giá trị gộp 0,004, độ không chắc chắn cao."
            )
        raise MethodologyGapError(
            f"Vụ '{crop_id}': chế độ nước '{regime}' là lúa cạn. IPCC Table 11.1 chú thích 7 "
            f"yêu cầu dùng EF1 (không phải EF1FR) cho lúa cạn; EF1 chưa được cấu hình. "
            f"Xem docs/CARBON_METHOD.md — NOT_IMPLEMENTED."
        )

    def calculate(
        self, data: CropActivityData, regime: str, params: ParameterSet
    ) -> tuple[BreakdownEntry | None, list[str]]:
        warnings: list[str] = []
        if not data.fertilizer:
            return None, warnings

        if any(f.is_organic for f in data.fertilizer):
            warnings.append(
                f"Vụ '{data.crop_season_id}': có phân hữu cơ trong dữ liệu. N từ phân hữu cơ (F_ON) "
                f"chưa nằm trong ranh giới hệ thống MVP — xem docs/CARBON_METHOD.md, "
                f"NOT_IMPLEMENTED."
            )

        nitrogen_kg = data.total_nitrogen_kg
        if nitrogen_kg <= 0:
            return None, warnings

        ef_key, regime_warning = self.resolve_ef_key(regime, data.crop_season_id)
        if regime_warning:
            warnings.append(regime_warning)

        ef1fr = params.factor("n2o_fertilizer", "ef1fr", ef_key)
        conversion = params.factor("n2o_fertilizer", "n2o_n_to_n2o")
        gwp = params.gwp("n2o")

        n2o_n_kg = nitrogen_kg * ef1fr.value
        n2o_kg = n2o_n_kg * conversion.value

        used, provenance, statuses = _record(
            {"ef1fr": ef1fr, "n2o_n_to_n2o": conversion, "gwp_n2o": gwp}
        )
        used["_derived.n2o_n_kg"] = n2o_n_kg

        warnings.append(
            f"Vụ '{data.crop_season_id}': mới tính N2O TRỰC TIẾP. N2O gián tiếp (bay hơi NH3/NOx và "
            f"rửa trôi, IPCC Eq 11.9/11.10) chưa nằm trong ranh giới hệ thống MVP."
        )

        return (
            BreakdownEntry(
                source="n2o_fertilizer_direct",
                gas="n2o",
                activity_value=nitrogen_kg,
                activity_unit="kg_N",
                gas_kg=n2o_kg,
                co2e_kg=n2o_kg * gwp.value,
                formula=(
                    "IPCC 2019 Refinement Eq 11.1: N2O-N = kg_N × EF1FR; "
                    "N2O = N2O-N × 44/28; CO2e = N2O × GWP_N2O"
                ),
                factors_used=used,
                provenance=provenance,
                parameter_status=statuses,
            ),
            warnings,
        )


# ===========================================================================
# Đốt rơm rạ ngoài đồng
# ===========================================================================


class StrawBurningCalculator:
    """IPCC 2006 Guidelines, Vol.4, Ch.2, Eq 2.27.

    L[kg khí] = M_dry_matter[kg] × Cf × Gef[g/kg] × 10⁻³

    CO2 từ đốt sinh khối nông nghiệp KHÔNG được tính (chu trình carbon sinh học) —
    xem factors.straw_burning.co2_counted, hiện PENDING_VERIFICATION.
    """

    def calculate(
        self, burned: list[StrawEvent], data: CropActivityData, params: ParameterSet
    ) -> list[BreakdownEntry]:
        if not burned:
            return []

        dry_matter_kg = 0.0
        for event in burned:
            if event.mass_kg is None:
                raise MissingActivityDataError(
                    f"Vụ '{data.crop_season_id}': bản ghi đốt rơm thiếu 'mass_kg'."
                )
            if event.dry_matter_fraction is None:
                raise MethodologyGapError(
                    f"Vụ '{data.crop_season_id}': bản ghi đốt rơm thiếu 'dry_matter_fraction'. "
                    f"IPCC Eq 2.27 tính trên khối lượng khô. Engine không đoán độ ẩm."
                )
            dry_matter_kg += event.mass_kg * event.dry_matter_fraction

        cf = params.factor("straw_burning", "combustion_factor_rice")
        gef_ch4 = params.factor("straw_burning", "gef_ch4")
        gef_n2o = params.factor("straw_burning", "gef_n2o")
        gwp_ch4 = params.gwp("ch4")
        gwp_n2o = params.gwp("n2o")

        burnt_kg = dry_matter_kg * cf.value
        ch4_kg = burnt_kg * gef_ch4.value / 1000.0
        n2o_kg = burnt_kg * gef_n2o.value / 1000.0

        formula = "IPCC 2006 GL Eq 2.27: L = M_dm × Cf × Gef × 1e-3; CO2e = L × GWP"

        ch4_used, ch4_prov, ch4_status = _record({"cf": cf, "gef_ch4": gef_ch4, "gwp_ch4": gwp_ch4})
        n2o_used, n2o_prov, n2o_status = _record({"cf": cf, "gef_n2o": gef_n2o, "gwp_n2o": gwp_n2o})

        return [
            BreakdownEntry(
                source="straw_burning",
                gas="ch4",
                activity_value=dry_matter_kg,
                activity_unit="kg_dry_matter",
                gas_kg=ch4_kg,
                co2e_kg=ch4_kg * gwp_ch4.value,
                formula=formula,
                factors_used=ch4_used,
                provenance=ch4_prov,
                parameter_status=ch4_status,
            ),
            BreakdownEntry(
                source="straw_burning",
                gas="n2o",
                activity_value=dry_matter_kg,
                activity_unit="kg_dry_matter",
                gas_kg=n2o_kg,
                co2e_kg=n2o_kg * gwp_n2o.value,
                formula=formula,
                factors_used=n2o_used,
                provenance=n2o_prov,
                parameter_status=n2o_status,
            ),
        ]


# ===========================================================================
# Nhiên liệu
# ===========================================================================


class FuelEmissionCalculator:
    """Đốt nhiên liệu cho bơm tưới / máy móc. Hệ số hiện PENDING_VERIFICATION (OI-06)."""

    def calculate(
        self, data: CropActivityData, params: ParameterSet
    ) -> tuple[list[BreakdownEntry], list[str]]:
        entries: list[BreakdownEntry] = []
        warnings: list[str] = []

        by_type: dict[str, float] = {}
        for usage in data.fuel:
            by_type[usage.fuel_type] = by_type.get(usage.fuel_type, 0.0) + usage.amount_litre

        for fuel_type, litres in sorted(by_type.items()):
            if litres <= 0:
                continue
            ef = params.factor("fuel", fuel_type)
            used, provenance, statuses = _record({"ef": ef})
            entries.append(
                BreakdownEntry(
                    source=f"fuel_{fuel_type}",
                    gas="co2e",
                    activity_value=litres,
                    activity_unit="litre",
                    gas_kg=litres * ef.value,
                    co2e_kg=litres * ef.value,
                    formula="CO2e = litre × EF_fuel",
                    factors_used=used,
                    provenance=provenance,
                    parameter_status=statuses,
                )
            )

        pump_kwh = sum(e.pump_energy_kwh or 0.0 for e in data.irrigation)
        if pump_kwh > 0:
            warnings.append(
                f"Vụ '{data.crop_season_id}': có {pump_kwh:g} kWh bơm điện nhưng hệ số lưới điện Việt Nam "
                f"chưa được cấu hình (OI-06) — phần này CHƯA được tính vào tổng."
            )

        return entries, warnings


__all__ = [
    "BreakdownEntry",
    "FertilizerN2OCalculator",
    "FuelEmissionCalculator",
    "RiceMethaneCalculator",
    "StrawBurningCalculator",
    "classify_straw",
    "WATER_REGIMES",
]

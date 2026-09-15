"""The factor register: which parameters the engine consumes, their units, and
how a YAML parameter set becomes an immutable `emission_factor_sets` row.

The YAML (`backend/config/emission_factors.yaml`) stays the single source of
factor VALUES. This module is the single source of the RULES around it:

* `CORE_CODES`      — consumed by the current engine for any supported season;
                      every one must be present and VERIFIED before a set may be
                      published.
* `OPTIONAL_CODES`  — consumed only when a season has that activity (fuel). May be
                      missing; the engine then fails closed for those seasons.
* `NOT_USED_CODES`  — present in the YAML for reference, not consumed.

A code is the YAML path without the leading `factors.` (the convention the
`emission_factors.factor_code` column and `carbon_breakdowns` already use).
Units are the ones the engine's arithmetic was traced against (see
docs/methodology/carbon-factor-register.md).

No database, no network: pure validation, so it is fully unit-testable.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_GWP_BASIS = "AR5"
SUPPORTED_TIER = 1
SUPPORTED_METHODOLOGY_VERSION = "2019"

_DIMENSIONLESS = "dimensionless"

# code -> (expected unit, parameter_kind, category, gas, activity_unit, result_unit)
_SPEC: dict[str, tuple[str, str, str, str | None, str, str]] = {
    "ch4_rice.efc": ("kgCH4_per_ha_per_day", "emission_factor", "irrigation_ch4", "ch4", "ha_day", "kgCH4"),
    "ch4_rice.sfo_exponent": (_DIMENSIONLESS, "exponent", "irrigation_ch4", None, _DIMENSIONLESS, _DIMENSIONLESS),
    "n2o_fertilizer.n2o_n_to_n2o": ("kgN2O_per_kgN2O-N", "conversion_factor", "fertilizer_n2o", "n2o", "kgN2O-N", "kgN2O"),
    "straw_burning.combustion_factor_rice": (_DIMENSIONLESS, "default_value", "straw", None, "kg_dry_matter", "kg_dry_matter_burnt"),
    "straw_burning.gef_ch4": ("g_CH4_per_kg_dry_matter", "emission_factor", "straw_burning_ch4", "ch4", "kg_dry_matter_burnt", "gCH4"),
    "straw_burning.gef_n2o": ("g_N2O_per_kg_dry_matter", "emission_factor", "straw_burning_n2o", "n2o", "kg_dry_matter_burnt", "gN2O"),
    "gwp.ch4": ("kgCO2e_per_kgCH4", "gwp", "other", "ch4", "kgCH4", "kgCO2e"),
    "gwp.n2o": ("kgCO2e_per_kgN2O", "gwp", "other", "n2o", "kgN2O", "kgCO2e"),
}
for _regime in ("irrigated_continuous_flooding", "irrigated_single_drainage", "irrigated_multiple_drainage",
                "rainfed_regular", "rainfed_drought_prone", "deep_water", "upland"):
    _SPEC[f"ch4_rice.sfw.{_regime}"] = (_DIMENSIONLESS, "scaling_factor", "irrigation_ch4", None, _DIMENSIONLESS, _DIMENSIONLESS)
for _pre in ("non_flooded_pre_season_lt_180d", "non_flooded_pre_season_gt_180d",
             "flooded_pre_season_gt_30d", "non_flooded_pre_season_gt_365d"):
    _SPEC[f"ch4_rice.sfp.{_pre}"] = (_DIMENSIONLESS, "scaling_factor", "irrigation_ch4", None, _DIMENSIONLESS, _DIMENSIONLESS)
for _cfoa in ("straw_incorporated_lt_30d", "straw_incorporated_gt_30d", "compost", "farmyard_manure", "green_manure"):
    _SPEC[f"ch4_rice.cfoa.{_cfoa}"] = (_DIMENSIONLESS, "scaling_factor", "irrigation_ch4", None, _DIMENSIONLESS, _DIMENSIONLESS)
for _key in ("continuous_flooding", "single_and_multiple_drainage", "aggregate"):
    _SPEC[f"n2o_fertilizer.ef1fr.{_key}"] = ("kgN2O-N_per_kgN", "emission_factor", "fertilizer_n2o", "n2o", "kgN", "kgN2O-N")

_OPTIONAL_SPEC: dict[str, tuple[str, str, str, str | None, str, str]] = {
    f"fuel.{fuel}": ("kgCO2e_per_litre", "emission_factor", "fuel", "co2e", "litre", "kgCO2e")
    for fuel in ("diesel", "gasoline", "lpg")
}

CORE_CODES: tuple[str, ...] = tuple(sorted(_SPEC))
OPTIONAL_CODES: tuple[str, ...] = tuple(sorted(_OPTIONAL_SPEC))
NOT_USED_CODES: tuple[str, ...] = (
    "ch4_rice.default_cultivation_days",  # NOT_IMPLEMENTED: engine never defaults cultivation days
    "fuel.electricity_grid",              # pump electricity is warned about, not added to the total
    "straw_burning.co2_counted",           # boolean flag; CO2 from biomass burning is not counted
)

_WATER_REGIME_BY_CODE = {f"ch4_rice.sfw.{r}": r for r in (
    "irrigated_continuous_flooding", "irrigated_single_drainage", "irrigated_multiple_drainage",
    "rainfed_regular", "rainfed_drought_prone", "deep_water", "upland")}
_PRE_SEASON_BY_CODE = {f"ch4_rice.sfp.{r}": r for r in (
    "non_flooded_pre_season_lt_180d", "non_flooded_pre_season_gt_180d",
    "flooded_pre_season_gt_30d", "non_flooded_pre_season_gt_365d")}

VERIFIED = "VERIFIED"


class FactorSetValidationError(ValueError):
    """Raised when a parameter file cannot even be read as a factor set."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML silently keeps the last of two identical keys; a factor file must not."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise FactorSetValidationError(f"duplicate key '{key}' at line {key_node.start_mark.line + 1}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_parameter_file(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_UniqueKeyLoader) or {}  # noqa: S506 - SafeLoader subclass


def _node(root: dict[str, Any], code: str) -> dict[str, Any] | None:
    parts = code.split(".")
    node: Any = root.get("gwp") if parts[0] == "gwp" else root.get("factors")
    for part in (parts[1:] if parts[0] == "gwp" else parts):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None


def _table_reference(node: dict[str, Any]) -> str | None:
    explicit = node.get("table_reference")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    source = node.get("source")
    if isinstance(source, str) and re.search(r"\b(Table|Equation|Eq)\b", source):
        return source.strip()
    return None


@dataclass
class FactorRow:
    factor_code: str
    factor_value: float
    unit: str
    parameter_kind: str
    category: str
    gas: str | None
    activity_unit: str
    result_unit: str
    source_reference: str
    source_table_reference: str | None
    verification_status: str
    uncertainty_range: str | None
    notes: str | None
    applies_to_water_regime: str | None
    applies_to_pre_season_regime: str | None

    def as_db_row(self, factor_set_id: str) -> dict[str, Any]:
        return {
            "factor_set_id": factor_set_id, "factor_code": self.factor_code, "category": self.category,
            "gas": self.gas, "activity_unit": self.activity_unit, "result_unit": self.result_unit,
            "factor_value": self.factor_value, "source_reference": self.source_reference, "notes": self.notes,
            "parameter_kind": self.parameter_kind, "verification_status": self.verification_status,
            "source_table_reference": self.source_table_reference, "uncertainty_range": self.uncertainty_range,
            "applies_to_water_regime": self.applies_to_water_regime,
            "applies_to_pre_season_regime": self.applies_to_pre_season_regime,
        }


@dataclass
class FactorSetReport:
    version_code: str | None
    methodology: dict[str, Any]
    rows: list[FactorRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    missing_core: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    unit_mismatches: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    @property
    def activation_eligible(self) -> bool:
        return not (self.errors or self.missing_core or self.unit_mismatches or self.unverified or self.unsupported)

    def summary(self) -> dict[str, Any]:
        return {
            "version_code": self.version_code, "methodology": self.methodology,
            "factor_count": len(self.rows), "core_required": len(CORE_CODES),
            "missing_core": self.missing_core, "missing_optional": self.missing_optional,
            "unit_mismatches": self.unit_mismatches, "unverified": self.unverified,
            "unsupported": self.unsupported, "errors": self.errors,
            "activation_eligible": self.activation_eligible,
        }


def _declared_codes(root: dict[str, Any]) -> set[str]:
    codes: set[str] = set()

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict) and "value" in node:
            codes.add(prefix)
            return
        if isinstance(node, dict):
            for key, child in node.items():
                walk(f"{prefix}.{key}" if prefix else key, child)

    walk("", root.get("factors") or {})
    for gas in ("ch4", "n2o"):
        if isinstance((root.get("gwp") or {}).get(gas), dict):
            codes.add(f"gwp.{gas}")
    return codes


def validate_parameter_set(root: dict[str, Any]) -> FactorSetReport:
    """Everything that must hold before a set may be imported and published."""
    methodology = root.get("methodology") or {}
    report = FactorSetReport(version_code=root.get("version"), methodology={
        "name": methodology.get("name"), "version": methodology.get("version"), "tier": methodology.get("tier"),
        "gwp_basis": methodology.get("gwp_basis"), "domain_expert_review": methodology.get("domain_expert_review"),
    })
    if not isinstance(report.version_code, str) or not report.version_code.strip():
        report.errors.append("version is required")
    if not methodology.get("name"):
        report.errors.append("methodology.name is required")
    if methodology.get("tier") != SUPPORTED_TIER:
        report.errors.append(f"methodology.tier must be {SUPPORTED_TIER} for the current engine")
    if str(methodology.get("version")) != SUPPORTED_METHODOLOGY_VERSION:
        report.errors.append(f"methodology.version must be {SUPPORTED_METHODOLOGY_VERSION}")
    framework = ((root.get("gwp") or {}).get("framework") or {}).get("value")
    if framework != SUPPORTED_GWP_BASIS or methodology.get("gwp_basis") != SUPPORTED_GWP_BASIS:
        report.errors.append(f"GWP basis must be {SUPPORTED_GWP_BASIS} in both gwp.framework and methodology.gwp_basis")
    sources = methodology.get("sources")
    if not isinstance(sources, list) or not sources:
        report.errors.append("methodology.sources must list the source publications")
    else:
        for index, source in enumerate(sources):
            if not isinstance(source, dict) or not str(source.get("title") or "").strip():
                report.errors.append(f"methodology.sources[{index}].title is required")
            if not re.match(r"^https://[^\s/]+\.[^\s]+$", str((source or {}).get("url") or "")):
                report.errors.append(f"methodology.sources[{index}].url must be an https URL")

    declared = _declared_codes(root)
    report.unsupported = sorted(declared - set(CORE_CODES) - set(OPTIONAL_CODES) - set(NOT_USED_CODES))

    for code in (*CORE_CODES, *OPTIONAL_CODES):
        spec = _SPEC.get(code) or _OPTIONAL_SPEC[code]
        node = _node(root, code)
        value = None if node is None else node.get("value")
        if value is None:
            (report.missing_core if code in _SPEC else report.missing_optional).append(code)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            report.errors.append(f"{code}: value must be a finite number")
            continue
        if float(value) < 0:
            report.errors.append(f"{code}: value must not be negative")
            continue
        unit = node.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            report.errors.append(f"{code}: unit is required")
            continue
        if unit != spec[0]:
            report.unit_mismatches.append(f"{code}: unit '{unit}' but the engine expects '{spec[0]}'")
            continue
        source = node.get("source")
        if not isinstance(source, str) or not source.strip():
            report.errors.append(f"{code}: source is required")
            continue
        status = node.get("status")
        table_reference = _table_reference(node)
        if status != VERIFIED:
            report.unverified.append(f"{code}: status {status}")
        elif table_reference is None:
            report.errors.append(f"{code}: a VERIFIED factor needs a table/equation reference")
            continue
        report.rows.append(FactorRow(
            factor_code=code, factor_value=float(value), unit=unit, parameter_kind=spec[1], category=spec[2],
            gas=spec[3], activity_unit=spec[4], result_unit=spec[5], source_reference=source.strip(),
            source_table_reference=table_reference, verification_status=str(status),
            uncertainty_range=node.get("uncertainty_range"), notes=(node.get("note") or None),
            applies_to_water_regime=_WATER_REGIME_BY_CODE.get(code),
            applies_to_pre_season_regime=_PRE_SEASON_BY_CODE.get(code),
        ))
    return report


def factor_set_row(root: dict[str, Any]) -> dict[str, Any]:
    methodology = root.get("methodology") or {}
    sources = methodology.get("sources") or []
    return {
        "version_code": root["version"],
        "name": f"AgriCarbon rice CO2e — IPCC {methodology.get('version')} Tier {methodology.get('tier')} + {methodology.get('gwp_basis')} GWP-100",
        "description": (
            f"Tier {methodology.get('tier')} IPCC defaults (region default: {methodology.get('region_default')}); "
            f"GWP basis {methodology.get('gwp_basis')}; country-specific factors: {methodology.get('country_specific_factors')}; "
            f"domain expert review: {methodology.get('domain_expert_review')}. Fuel factors not verified. "
            "Not a certification and not MRV-compliant."
        ),
        "methodology_name": methodology.get("name"),
        "methodology_version": str(methodology.get("version")),
        "valid_from": root.get("review_date"),
        "source_name": "; ".join(str(s.get("title")) for s in sources)[:2000],
        "source_url": sources[0].get("url") if sources else None,
    }


def readiness(root: dict[str, Any]) -> dict[str, Any]:
    """Scientific readiness, derived only from evidence recorded in the file.

    READY_FOR_DEMO needs a validation-clean core set (all core factors VERIFIED,
    GWP decided, units match). READY_FOR_PILOT additionally needs a completed
    domain-expert review. Nothing here can yield "certified".
    """
    report = validate_parameter_set(root)
    methodology = root.get("methodology") or {}
    expert_review = methodology.get("domain_expert_review") or "PENDING"
    if not report.activation_eligible:
        level = "STILL_BLOCKED"
    elif expert_review == "COMPLETE":
        level = "READY_FOR_PILOT"
    else:
        level = "READY_FOR_DEMO"
    return {
        "level": level,
        "core_factors_verified": report.activation_eligible,
        "gwp_basis": methodology.get("gwp_basis"),
        "tier": methodology.get("tier"),
        "domain_expert_review": expert_review,
        "missing_optional_factors": report.missing_optional,
    }

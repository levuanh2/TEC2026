"""Carbon Engine — lõi tính CO2e của AgriCarbon (lớp 1a, đường găng).

Không phụ thuộc FastAPI, Supabase, Flutter hay bất kỳ UI nào — chỉ stdlib + pyyaml.
Phương pháp luận: docs/CARBON_METHOD.md · Nguồn: docs/CARBON_METHOD_SOURCES.md
"""

from .engine import (
    ENGINE_VERSION,
    CarbonResult,
    assert_consistent_water_records,
    calculate_carbon,
    compute_input_hash,
)
from .errors import (
    CarbonEngineError,
    ConflictingWaterRegimeError,
    DoubleCountingError,
    InvalidWaterRegimeError,
    MethodologyGapError,
    MissingActivityDataError,
    MissingEmissionFactorError,
    ValidationError,
)
from .factors import Methodology, Parameter, ParameterSet
from .methodology import (
    BreakdownEntry,
    FertilizerN2OCalculator,
    FuelEmissionCalculator,
    RiceMethaneCalculator,
    StrawBurningCalculator,
    classify_straw,
)
from .models import (
    PRE_SEASON_REGIMES,
    SCENARIOS,
    STRAW_METHODS,
    WATER_REGIMES,
    CropActivityData,
    FertilizerApplication,
    FuelUsage,
    Harvest,
    IrrigationEvent,
    OrganicAmendment,
    PesticideApplication,
    Seed,
    StrawEvent,
)

__all__ = [
    "ENGINE_VERSION",
    "PRE_SEASON_REGIMES",
    "SCENARIOS",
    "STRAW_METHODS",
    "WATER_REGIMES",
    "BreakdownEntry",
    "CarbonEngineError",
    "CarbonResult",
    "ConflictingWaterRegimeError",
    "CropActivityData",
    "DoubleCountingError",
    "FertilizerApplication",
    "FertilizerN2OCalculator",
    "FuelEmissionCalculator",
    "FuelUsage",
    "Harvest",
    "InvalidWaterRegimeError",
    "IrrigationEvent",
    "Methodology",
    "MethodologyGapError",
    "MissingActivityDataError",
    "MissingEmissionFactorError",
    "OrganicAmendment",
    "Parameter",
    "ParameterSet",
    "PesticideApplication",
    "RiceMethaneCalculator",
    "Seed",
    "StrawBurningCalculator",
    "StrawEvent",
    "ValidationError",
    "assert_consistent_water_records",
    "calculate_carbon",
    "classify_straw",
    "compute_input_hash",
]

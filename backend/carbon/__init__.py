"""Carbon Engine — lõi tính CO2e của AgriCarbon (lớp 1a, đường găng).

Không phụ thuộc FastAPI, Supabase, Flutter hay bất kỳ UI nào.
"""

from .engine import BreakdownEntry, CarbonResult, calculate_carbon
from .errors import (
    CarbonEngineError,
    ConflictingWaterRegimeError,
    InvalidWaterRegimeError,
    MissingActivityDataError,
    MissingEmissionFactorError,
    ValidationError,
)
from .factors import EmissionFactor, EmissionFactorSet
from .models import (
    WATER_REGIME_SCENARIOS,
    WATER_REGIMES,
    CropActivityData,
    FertilizerApplication,
    Harvest,
    PesticideApplication,
    Seed,
    StrawManagement,
    WaterRecord,
)

__all__ = [
    "BreakdownEntry",
    "CarbonEngineError",
    "CarbonResult",
    "ConflictingWaterRegimeError",
    "CropActivityData",
    "EmissionFactor",
    "EmissionFactorSet",
    "FertilizerApplication",
    "Harvest",
    "InvalidWaterRegimeError",
    "MissingActivityDataError",
    "MissingEmissionFactorError",
    "PesticideApplication",
    "Seed",
    "StrawManagement",
    "ValidationError",
    "WATER_REGIMES",
    "WATER_REGIME_SCENARIOS",
    "WaterRecord",
    "calculate_carbon",
]

"""Deprecated name of :mod:`saengine.library.code_data` (the default code pack's reference data).

Kept only so that modules not yet moved to the new name keep working; import
:mod:`saengine.library.code_data` instead.
"""

from saengine.library.code_data import *
from saengine.library.code_data import (  # noqa: F401
    AREA_USES,
    DAMPING_ETA,
    EDITION,
    EXPOSURE_PROFILES,
    EXPOSURES,
    LOAD_CASES,
    LOCATIONS,
    OCCUPANCY_CATEGORIES,
    PACK_ID,
    PERIOD_COEFFICIENTS,
    SEISMIC_LIVE_SHARE,
    SITE_CLASSES,
    SITE_FACTORS,
    STRENGTH_COMBINATIONS,
    STRUCTURAL_SYSTEMS,
    SYSTEM_PERIOD_FAMILY,
    WIND_CP_LEEWARD,
    WIND_CP_WINDWARD,
    WIND_GUST,
    WIND_KD,
    WIND_KZT,
    ZONE_COEFFICIENT,
    AreaUse,
    ExposureProfile,
    Location,
    OccupancyCategory,
    SiteFactors,
    StructuralSystem,
)

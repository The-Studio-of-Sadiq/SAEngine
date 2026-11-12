"""Deprecated: footings are designed by Part 9 Substructure (:mod:`saengine.substructure.shallow`).

This module only re-exports the names that lived here, for one release; import them from
:mod:`saengine.substructure.shallow`, :mod:`saengine.substructure.loads` and
:mod:`saengine.design.punching` instead. The old Part 8 design of the ``FootingElement``s of the
building model (``footing_checks``, ``FOOTING_METHOD``) is gone: the drawn footings are moved
into ``09 Substructure/substructure.json`` (:mod:`saengine.substructure.handover`) and designed
there, with the same checks (:func:`saengine.substructure.substructure_report`).
"""

from __future__ import annotations

import warnings

from saengine.design.punching import ShearReinforcement, footing_punching
from saengine.substructure.loads import column_action, service_combinations
from saengine.substructure.shallow import (
    Bearing,
    ColumnBase,
    FootingSpec,
    G,
    Loads,
    SoilBearing,
    SoilPressure,
    StripFlexure,
    design_footing,
    gamma_v,
    manual_bearing,
    mesh_area,
    min_steel_ratio,
    one_way_shear_capacity,
    plain_flexure,
    polar_j,
    punching_stress,
    size_factor,
    soil_pressure,
    strip_flexure,
)

__all__ = [
    "Bearing",
    "ColumnBase",
    "FootingSpec",
    "G",
    "Loads",
    "ShearReinforcement",
    "SoilBearing",
    "SoilPressure",
    "StripFlexure",
    "column_action",
    "design_footing",
    "footing_punching",
    "gamma_v",
    "manual_bearing",
    "mesh_area",
    "min_steel_ratio",
    "one_way_shear_capacity",
    "plain_flexure",
    "polar_j",
    "punching_stress",
    "service_combinations",
    "size_factor",
    "soil_pressure",
    "strip_flexure",
]

warnings.warn(
    "saengine.design.footing is deprecated: import from saengine.substructure.shallow",
    DeprecationWarning,
    stacklevel=2,
)

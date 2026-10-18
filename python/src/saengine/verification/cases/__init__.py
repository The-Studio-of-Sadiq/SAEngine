"""The benchmark problems of the verification pack, in the order of the manual."""

from __future__ import annotations

from saengine.verification.cases import (
    analysis,
    design,
    electrical,
    hvac_air,
    hvac_loads,
    hydraulics,
    mep,
    plumbing,
    soil,
    ssi,
    substructure,
    substructure_deep,
    tanks,
    thermal,
)
from saengine.verification.cases.common import Case

CASES: list[Case] = [
    *analysis.CASES,
    *thermal.CASES,
    *ssi.CASES,
    *design.CASES,
    *soil.CASES,
    *substructure.CASES,
    *substructure_deep.CASES,
    *mep.CASES,
    *plumbing.CASES,
    *hydraulics.CASES,
    *tanks.CASES,
    *electrical.CASES,
    *hvac_air.CASES,
    *hvac_loads.CASES,
]
BY_ID: dict[str, Case] = {case.id: case for case in CASES}

__all__ = ["BY_ID", "CASES", "Case"]

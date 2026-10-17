"""The benchmark problems of the verification pack, in the order of the manual."""

from __future__ import annotations

from saengine.verification.cases import analysis, design, soil, substructure, substructure_deep
from saengine.verification.cases.common import Case

CASES: list[Case] = [
    *analysis.CASES,
    *design.CASES,
    *soil.CASES,
    *substructure.CASES,
    *substructure_deep.CASES,
]
BY_ID: dict[str, Case] = {case.id: case for case in CASES}

__all__ = ["BY_ID", "CASES", "Case"]

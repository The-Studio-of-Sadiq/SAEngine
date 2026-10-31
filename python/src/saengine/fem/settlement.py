"""The support settlement load case ST.

BNBC 2020 Part 6 Sec 2.7 counts differential settlement among the self-straining effects T of
its load combinations ("T = self-straining force ... arising from ... differential settlement"),
so ST takes T's place and factor: 1.2(D + F + T) + 1.6(L + H) + 0.5(Lr or R) of Sec 2.7.3.1.

The case imposes a downward displacement on the listed column bases (Project Settings →
Analysis model → Support settlement): the analysis model's pattern ``ST`` holds one support
displacement per settling base (OpenSees ``sp`` in the pattern, the base's vertical fix
replaced for that case only; OpenSees Studio's ``PlainLoadPattern.support_displacements``),
and its static analysis ``ST: Support settlement``. The other bases stay fixed, so the case
gives the forces of the differential settlement. With soil springs at the bases the case is
not formed (the springs already settle under the loads).

Units: the analysis model's m; the settlements are given in mm.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["CASE", "CASE_TITLE", "add_settlement_case", "strength_combinations_with_st"]

CASE = "ST"
CASE_TITLE = "Support settlement"
CLAUSE = "BNBC 2020 Part 6 Sec 2.7.3.1 (p. 685), T including differential settlement"

#: How far a support node may lie from a column's base point [m].
_TOLERANCE = 0.01


def strength_combinations_with_st(thermal: bool = False) -> list[tuple[str, dict[str, float]]]:
    """Combination 2 of Sec 2.7.3.1 with ST as T, ``1.2D + 1.2ST + 1.6L + 0.5Lr``; with the
    temperature case too, also with ±T beside ST (both are self-straining T): (name, factors)."""
    found = [("1.2D + 1.2ST + 1.6L + 0.5Lr", {"D": 1.2, "ST": 1.2, "L": 1.6, "Lr": 0.5})]
    if thermal:
        found += [
            (
                f"1.2D {sign} 1.2T + 1.2ST + 1.6L + 0.5Lr",
                {"D": 1.2, "T": s * 1.2, "ST": 1.2, "L": 1.6, "Lr": 0.5},
            )
            for sign, s in (("+", 1.0), ("-", -1.0))
        ]
    return found


def add_settlement_case(
    project: dict[str, Any], building: Any, supports: list[Any]
) -> tuple[int | None, list[str]]:
    """Add the settlement case to an OpenSees Studio ``project`` (in place): the pattern ``ST``
    with the bases' imposed displacements and its static analysis. ``supports``: the settings'
    :class:`saengine.library.settings.SettlementSupport` rows. Returns (the analysis id or None
    when no base was found, notes)."""
    from saengine.library.bim import ColumnElement

    notes: list[str] = []
    columns = {e.id: e for e in building.elements if isinstance(e, ColumnElement)}
    nodes = [
        (int(n["id"]), np.asarray(n["coords"], dtype=float))
        for n in project.get("nodes", [])
        if (n.get("restraint") or [False] * 6)[2]
    ]
    displacements: list[dict[str, Any]] = []
    for row in supports:
        column = columns.get(row.column)
        if column is None:
            notes.append(f"settlement: no column '{row.column}' in the building model; left out")
            continue
        base = (
            np.array([float(column.position[0]), float(column.position[1]), float(column.bottom)])
            / 1e3
        )
        node = next(
            (nid for nid, xyz in nodes if float(np.linalg.norm(xyz - base)) <= _TOLERANCE), None
        )
        if node is None:
            notes.append(
                f"settlement: the base of {row.column} is not a fixed support of the analysis "
                "model; left out"
            )
            continue
        displacements.append({"node_id": node, "dof": 3, "value": -float(row.value) / 1e3})
    if not displacements:
        return None, notes
    pattern = next((p for p in project.get("load_patterns", []) if p.get("name") == CASE), None)
    if pattern is None:
        series = next(
            (s["id"] for s in project.get("time_series", []) if s.get("type") == "Linear"), None
        )
        if series is None:
            series = 1 + max((s["id"] for s in project.get("time_series", [])), default=0)
            project.setdefault("time_series", []).append(
                {"id": series, "name": "", "type": "Linear", "factor": 1.0}
            )
        pattern = {
            "id": 1 + max((p["id"] for p in project.get("load_patterns", [])), default=0),
            "name": CASE,
            "type": "Plain",
            "time_series_id": series,
            "nodal_loads": [],
            "element_loads": [],
        }
        project.setdefault("load_patterns", []).append(pattern)
    pattern["support_displacements"] = displacements
    analysis = next(
        (a for a in project.get("analyses", []) if pattern["id"] in a.get("pattern_ids", [])), None
    )
    if analysis is None:
        analysis = {
            "id": 1 + max((a["id"] for a in project.get("analyses", [])), default=0),
            "name": f"{CASE}: {CASE_TITLE}",
            "type": "Static",
            "pattern_ids": [pattern["id"]],
            "n_steps": 1,
            "load_factor_increment": 1.0,
            "system": "BandGeneral",
            "constraints": "Transformation",
            "integrator": "LoadControl",
            "algorithm": "Linear",
            "test": "NormDispIncr",
            "tolerance": 1e-8,
            "max_iter": 25,
        }
        project.setdefault("analyses", []).append(analysis)
    notes.append(
        f"settlement: case ST settles {len(displacements)} column base(s) by "
        + ", ".join(f"{-d['value'] * 1e3:g} mm" for d in displacements[:6])
        + ("..." if len(displacements) > 6 else "")
        + f"; combined as T ({CLAUSE})"
    )
    return int(analysis["id"]), notes

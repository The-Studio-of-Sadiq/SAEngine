"""Notional loads for the stability design of steel frames (Project Settings -> Analysis:
``notionalLoads``, ``notionalDrift``, ``directAnalysisTau``, ``directAnalysisNotional``).

The code pack's ``steelStability`` table gives the coefficients (BNBC 2020: Part 6 Sec 10.3.2.2
and Sec 10.14.3, part 2 pp. 52-53 and 188-189). A lateral notional load at each level,
proportional to the gravity load Yi applied at that level:

- design by second-order analysis (``"secondOrder"``): Ni = ``notional.secondOrder`` Yi
  (BNBC 2020: 0.002), in the gravity-only load combinations;
- design by first-order analysis (``"firstOrder"``): Ni = ``notional.firstOrderDriftFactor``
  (Δ/L) Yi >= ``notional.firstOrderMinimum`` Yi (BNBC 2020: 2.1 and 0.0042, Eq 6.10.10), in
  every load combination, Δ/L the largest first-order storey drift ratio under the strength
  combinations (the members then take K = 1 when αPr <= 0.5 Py, which the steel member checks
  flag);
- the direct analysis method (``"directAnalysis"``): Ni = ``directAnalysis.notionalCoefficient``
  Yi (BNBC 2020: 0.002) in every combination, or in the gravity-only ones where the ratio of
  second- to first-order drift allows it (the design checks the ratio); with τb = 1 for every
  member (``tau = "additive"``) the additive ``additiveNotionalCoefficient`` Yi (0.001) on top.
  The reduced stiffness is :func:`saengine.fem.second_order.apply_second_order`'s, the member
  checks with K = 1 are :mod:`saengine.design.steel.stability`'s.

The notional load acts where the gravity load acts: at every node of a gravity case, a
horizontal force of the coefficient times the node's vertical load (a frame's uniform load
split to its two ends), so the sum over a level is exactly the coefficient times Yi. One case per
gravity case and direction (NXD, NYD from D and SD; NXL, NYL from L; NXLr, NYLr from Lr), so
each combination scales them by its own factors (:func:`notional_combinations`): the notional
load of 1.2D + 1.6L is 0.002 (1.2 YD + 1.6 YL). Loads in N, coordinates in m (the model's).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from saengine.codes import context as code_context

#: The direct analysis method's id (``settings.analysis.notionalLoads``).
DIRECT_ANALYSIS = "directAnalysis"


def stability_table() -> Any | None:
    """The code pack's ``steelStability`` table; None when the pack in force has none."""
    pack = code_context.current()
    return pack.table("steelStability") if pack.has("steelStability") else None


def _clause(method: str) -> str:
    """The pack's clause of ``method``, for the notes."""
    table = stability_table()
    if table is None:
        return ""
    key = {
        DIRECT_ANALYSIS: "notional",
        "secondOrder": "secondOrderNotional",
        "firstOrder": "firstOrderNotional",
    }.get(method, "")
    return table.sources.get(key) or table.source


#: The notional cases: (code, direction axis, the gravity cases it is formed from, the
#: combination factor that scales it).
NOTIONAL_CASES = (
    ("NXD", 0, ("D", "SD"), "D"),
    ("NYD", 1, ("D", "SD"), "D"),
    ("NXL", 0, ("L",), "L"),
    ("NYL", 1, ("L",), "L"),
    ("NXLr", 0, ("Lr",), "Lr"),
    ("NYLr", 1, ("Lr",), "Lr"),
)


def coefficient(method: str, drift: float = 0.0, tau: str = "additive") -> float:
    """Ni / Yi of ``method`` ("secondOrder", "firstOrder" or "directAnalysis", with ``tau``
    "additive": τb = 1 for every member and the additive notional load); 0 for "none" or a
    method the code pack does not cover."""
    table = stability_table()
    if table is None:
        return 0.0
    if method == "secondOrder":
        return float(table.notional.secondOrder)
    if method == "firstOrder":
        return max(
            float(table.notional.firstOrderDriftFactor) * max(drift, 0.0),
            float(table.notional.firstOrderMinimum),
        )
    if method == DIRECT_ANALYSIS and table.directAnalysis is not None:
        da = table.directAnalysis
        extra = float(da.additiveNotionalCoefficient) if tau == "additive" else 0.0
        return float(da.notionalCoefficient) + extra
    return 0.0


def node_gravity(project: dict[str, Any], cases: tuple[str, ...]) -> dict[int, float]:
    """The downward load [N] at each node of the patterns named ``cases`` (factor 1): nodal
    loads, and the frames' uniform loads split half to each end (local loads turned global)."""
    from saengine.fem.second_order import _frame_axes

    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    elements = {e["id"]: e for e in project.get("elements", [])}
    out: dict[int, float] = {}
    for pattern in project.get("load_patterns", []):
        if pattern.get("name") not in cases or pattern.get("type", "Plain") != "Plain":
            continue
        for load in pattern.get("nodal_loads", []):
            fz = float(load["forces"][2])
            if fz < 0:
                out[load["node_id"]] = out.get(load["node_id"], 0.0) - fz
        for load in pattern.get("element_loads", []):
            element = elements.get(load["element_id"])
            if element is None:
                continue
            i, j = element["nodes"][:2]
            a, b = coords[i], coords[j]
            x, y, z = _frame_axes(a, b, element.get("vecxz"))
            w = load.get("wx", 0.0) * x + load.get("wy", 0.0) * y + load.get("wz", 0.0) * z
            total = -float(w[2]) * float(np.linalg.norm(b - a))
            if total > 0:
                out[i] = out.get(i, 0.0) + total / 2
                out[j] = out.get(j, 0.0) + total / 2
    return out


def level_loads(
    project: dict[str, Any], cases: tuple[str, ...], levels: list[float]
) -> list[dict[str, float]]:
    """``[{"z", "Y"}]``: the gravity load Yi [N] of ``cases`` at each level ``z`` [m] (nodes
    within 1 mm of it)."""
    gravity = node_gravity(project, cases)
    coords = {n["id"]: float(n["coords"][2]) for n in project.get("nodes", [])}
    rows = []
    for z in levels:
        total = sum(v for n, v in gravity.items() if abs(coords.get(n, 1e9) - z) < 1e-3)
        rows.append({"z": z, "Y": total})
    return rows


def add_notional_cases(
    project: dict[str, Any], method: str, drift: float = 0.0, tau: str = "additive"
) -> list[str]:
    """Add the notional cases (:data:`NOTIONAL_CASES`) to an OpenSees Studio ``project`` in
    place: one plain pattern and one static analysis each, for the gravity cases the model has.
    Returns the notes (empty when ``method`` is "none")."""
    if method in (None, "", "none"):
        return []
    k = coefficient(method, drift, tau)
    if k <= 0:
        return [f"notional loads: the code pack does not cover the method '{method}'"]
    clause = _clause(method)
    patterns = project.setdefault("load_patterns", [])
    analyses = project.setdefault("analyses", [])
    template = next((a for a in analyses if a.get("type") == "Static"), None)
    series = next(
        (s["id"] for s in project.get("time_series", []) if s.get("type") == "Linear"), None
    )
    if series is None:
        series = 1 + max((s["id"] for s in project.get("time_series", [])), default=0)
        project.setdefault("time_series", []).append(
            {"id": series, "name": "", "type": "Linear", "factor": 1.0}
        )
    added = []
    totals: dict[str, float] = {}
    for code, axis, cases, _ in NOTIONAL_CASES:
        gravity = node_gravity(project, cases)
        if not gravity:
            continue
        nodal = []
        for node, value in sorted(gravity.items()):
            forces = [0.0] * 6
            forces[axis] = round(k * value, 3)
            nodal.append({"node_id": node, "forces": forces})
        pattern_id = 1 + max((p["id"] for p in patterns), default=0)
        patterns.append(
            {
                "id": pattern_id,
                "name": code,
                "type": "Plain",
                "time_series_id": series,
                "nodal_loads": nodal,
                "element_loads": [],
            }
        )
        analysis = {
            "id": 1 + max((a["id"] for a in analyses), default=0),
            "name": f"{code}: Notional load {'XY'[axis]} from {'+'.join(cases)}",
            "type": "Static",
            "pattern_ids": [pattern_id],
            "n_steps": 1,
            "load_factor_increment": 1.0,
            "system": (template or {}).get("system", "UmfPack"),
            "constraints": (template or {}).get("constraints", "Plain"),
            "integrator": "LoadControl",
            "algorithm": "Linear",
            "test": "NormDispIncr",
            "tolerance": 1e-8,
            "max_iter": 25,
        }
        analyses.append(analysis)
        added.append(code)
        totals[code] = k * sum(gravity.values())
    if not added:
        return [f"notional loads: no gravity case to form them from ({clause})"]
    rule = {
        "secondOrder": f"Ni = {k:g} Yi (design by second-order analysis)",
        "firstOrder": f"Ni = {k:g} Yi (design by first-order analysis, Δ/L = {drift:g})",
        DIRECT_ANALYSIS: f"Ni = {k:g} Yi (direct analysis method"
        + (", τb = 1 with the additive notional load)" if tau == "additive" else ")"),
    }[method]
    return [
        f"notional loads: cases {', '.join(added)} with {rule}, at the nodes of the gravity "
        "loads; total "
        + ", ".join(f"{c} {v / 1e3:.1f} kN" for c, v in totals.items() if c.startswith("NX"))
        + f" ({clause})"
    ]


#: Combination factors that put a lateral load in X or Y (their sign gives the direction).
_LATERAL_X = ("WX", "EX", "EXP", "EXN", "WTX", "RX")
_LATERAL_Y = ("WY", "EY", "EYP", "EYN", "WTY", "RY")


def _scales(factors: dict[str, float]) -> dict[str, float]:
    """The factors of the notional cases' gravity cases in a combination (``D``, ``L``,
    ``Lr``; a live load arrangement LPk counts as L)."""
    live = factors.get("L", 0.0) or max(
        (v for c, v in factors.items() if c.startswith("LP") and c[2:].isdigit()), default=0.0
    )
    return {"D": factors.get("D", 0.0), "L": live, "Lr": factors.get("Lr", 0.0)}


def notional_combinations(
    combinations: list[Any], present: set[str] | frozenset[str], every: bool
) -> list[Any] | None:
    """The combinations with the notional cases the model has (``present``): each gravity-only
    combination is followed by four, its notional loads in +X, -X, +Y and -Y ("<name> [+NX]"
    ...); with ``every`` (first-order analysis) each combination with a lateral load also takes
    them in that load's direction (it is replaced). None when the model has no notional cases.
    """
    from saengine.fem.combinations import combination_factors

    codes = [row for row in NOTIONAL_CASES if row[0] in present]
    if not codes:
        return None
    out: list[Any] = []
    for combination in combinations:
        factors = combination_factors(combination, present)
        scales = _scales(factors)
        x = next((factors[c] for c in _LATERAL_X if factors.get(c)), 0.0)
        y = next((factors[c] for c in _LATERAL_Y if factors.get(c)), 0.0)
        if not x and not y:
            out.append(combination)
            if any(scales.values()):
                for axis, name in ((0, "NX"), (1, "NY")):
                    for sign, mark in ((1.0, "+"), (-1.0, "-")):
                        out.append(
                            _with_notional(
                                combination, codes, scales, [(axis, sign)], f"{mark}{name}"
                            )
                        )
        elif every:
            directions = []
            if x:
                directions.append((0, 1.0 if x > 0 else -1.0))
            if y:
                directions.append((1, 1.0 if y > 0 else -1.0))
            out.append(_with_notional(combination, codes, scales, directions, "+N"))
        else:
            out.append(combination)
    return out


def _with_notional(
    combination: Any,
    codes: list[tuple[str, int, tuple[str, ...], str]],
    scales: dict[str, float],
    directions: list[tuple[int, float]],
    label: str,
) -> Any:
    """``combination`` with the notional cases ``codes`` in ``directions`` (axis, sign), each
    scaled by its gravity case's factor, named "<name> [<label>]"."""
    from saengine.fem.combinations import CaseCombination

    data = combination.model_dump(by_alias=True)
    extra = dict(data.get("cases") or {})
    for code, axis, _, scale in codes:
        for direction, sign in directions:
            if axis == direction and scales[scale]:
                extra[code] = extra.get(code, 0.0) + sign * scales[scale]
    return CaseCombination(**{**data, "cases": extra, "name": f"{combination.name} [{label}]"})

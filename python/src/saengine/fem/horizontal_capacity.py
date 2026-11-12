"""The storeys' horizontal capacity against the required capacity Qun = Ds·Fes·Qud (the code
pack's ``horizontalCapacity``, method ``requiredCapacity``; alpha 9 track C19).

For each storey and direction:

- Qud, the storey shear of the seismic force at the ultimate standard shear coefficient: Ci
  ΣWi with Ci = Z Rt Ai C0 (``ultimateCoefficient``), from the derivation's terms of the
  storey shear coefficient method (:mod:`saengine.fem.shear_coefficient`);
- Fes = Fs·Fe: Fs of the stiffness ratio Rs = rs / mean rs (rs the inverse of the storey drift
  angle under the primary seismic case EX or EY of the linear analysis), Fe of the eccentricity
  ratio Re = e / re (e between the centre of the weights the storey carries and its centre of
  rigidity, re = √(KR / ΣD) the elastic radius), by the pack's ``shapeFactors`` points;
- Ds by the structure's material and the share βu of the walls or braces (the pack's
  ``systems`` row of the project's seismic system, else ``defaultSystem``) and the worst member
  rank of the design run (``design-report.json``'s rank rows; ``defaultRank`` without one);
- Qu, the storey's horizontal capacity from a pushover in that direction: the storey shear
  (the base shear's share of the load pattern above the storey) when a storey first reaches the
  drift ratio ``capacityDrift`` (or the largest shear along the run when the push ends before);

and Qu ≥ Qun = Ds Fes Qud.

SAEngine practice (the notes say so): the storey stiffness D of each column is 12 E I / h³ of
its section about the shaking (both ends fixed) and of each wall 1 / (h³ / (12 E I) + 1.2 h /
(G A)) in its plane, the beams taken as rigid (the code's D values with the beams' stiffness are
not computed); the centre of the weights of a storey is that of the masses at and above its top;
one Ds for the building from its worst member rank.

Units: m, N in the computation; the rows in m, kN.
"""

from __future__ import annotations

import json
import math
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

#: Levels within this [m] are the same level.
_TOLERANCE = 0.05


def table() -> Any | None:
    """The pack's ``horizontalCapacity`` table; None when the pack in force has none."""
    pack = code_context.current()
    return pack.table("horizontalCapacity") if pack.has("horizontalCapacity") else None


def _interp(points: list[tuple[float, float]], x: float) -> float:
    ordered = sorted(points)
    if x <= ordered[0][0]:
        return float(ordered[0][1])
    for (x0, y0), (x1, y1) in pairwise(ordered):
        if x <= x1:
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(ordered[-1][1])


def stiffness_factor(rs: float, rule: Any = None) -> float:
    """Fs of the stiffness ratio ``rs`` (the pack's points)."""
    rule = rule or table().shapeFactors
    return _interp(rule.stiffness, rs)


def eccentricity_factor(re: float, rule: Any = None) -> float:
    """Fe of the eccentricity ratio ``re``."""
    rule = rule or table().shapeFactors
    return _interp(rule.eccentricity, re)


def structural_factor(material: str, rank: str, beta_u: float, rule: Any = None) -> float:
    """Ds of ``material`` (a key of the pack's ``ds``), member ``rank`` and βu: the first band
    holding βu (the last above)."""
    rule = rule or table()
    ranks = rule.ds[material].ranks
    bands = ranks.get(rank) or ranks[rule.defaultRank]
    return float(
        next((ds for upto, ds in bands.bands if beta_u <= upto + 1e-9), bands.bands[-1][1])
    )


def required_capacity(ds: float, fs: float, fe: float, qud: float) -> float:
    """Qun = Ds Fes Qud with Fes = Fs Fe."""
    return ds * fs * fe * qud


# ───────────────────────── stiffness ratio and eccentricity ratio ─────────────────────────


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _frame_axes(xi: np.ndarray, xj: np.ndarray, vecxz: Any) -> tuple[np.ndarray, np.ndarray]:
    """The local y and z axes of a frame element (OpenSees: z in the plane of x and vecxz)."""
    x = _unit(xj - xi)
    v = np.asarray(vecxz if vecxz is not None else [1.0, 0.0, 0.0], dtype=float)
    z = _unit(v - float(np.dot(v, x)) * x)
    if float(np.linalg.norm(z)) < 1e-9:
        z = _unit(np.cross(x, [0.0, 1.0, 0.0]))
    y = np.cross(z, x)
    return y, z


def storey_stiffness_items(
    project: dict[str, Any], bottom: float, top: float
) -> list[tuple[float, float, float, float]]:
    """(x, y, Dx, Dy) [m, N/m] of the columns and walls of the storey between ``bottom`` and
    ``top`` [m] (see the module notes)."""
    h = top - bottom
    if h <= 0:
        return []
    nodes = {int(n["id"]): np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    sections = {int(s["id"]): s for s in project.get("sections", [])}
    items: list[tuple[float, float, float, float]] = []
    walls: dict[str, list[tuple[np.ndarray, dict[str, Any]]]] = {}
    for element in project.get("elements", []):
        ids = [int(n) for n in element.get("nodes", [])]
        points = [nodes[n] for n in ids if n in nodes]
        if len(points) != len(ids) or not points:
            continue
        section = sections.get(int(element.get("section_id") or 0))
        if section is None:
            continue
        zs = [float(p[2]) for p in points]
        inside = min(zs) >= bottom - _TOLERANCE and max(zs) <= top + _TOLERANCE
        if element.get("type") == "Shell":
            if inside and max(zs) - min(zs) > _TOLERANCE:
                base = str(element.get("name", "")).split("#")[0]
                walls.setdefault(base, []).extend((p, section) for p in points)
            continue
        if len(points) != 2 or "Iz" not in section or "E" not in section:
            continue
        xi, xj = points
        axis = xj - xi
        length = float(np.linalg.norm(axis))
        if length <= 0 or abs(float(axis[2])) < 0.9 * length:
            continue
        if abs(min(zs) - bottom) > _TOLERANCE:
            continue  # the lowest segment of each column line stands for it
        y_axis, z_axis = _frame_axes(xi, xj, element.get("vecxz"))
        e, iz, iy = float(section["E"]), float(section["Iz"]), float(section["Iy"])
        k = 12.0 * e / h**3
        # Sway along a global direction bends about local z by its y share, about y by z's.
        dx = k * (iz * float(y_axis[0]) ** 2 + iy * float(z_axis[0]) ** 2)
        dy = k * (iz * float(y_axis[1]) ** 2 + iy * float(z_axis[1]) ** 2)
        items.append((float(xi[0]), float(xi[1]), dx, dy))
    for found in walls.values():
        xy = np.array([[float(p[0]), float(p[1])] for p, _ in found])
        section = found[0][1]
        if "E" not in section or "h" not in section:
            continue
        centre = xy.mean(axis=0)
        spread = xy - centre
        if len(xy) < 2 or float(np.abs(spread).max()) <= 0:
            continue
        _, _, vt = np.linalg.svd(spread, full_matrices=False)
        u = vt[0]
        along_u = spread @ u
        length = float(along_u.max() - along_u.min())
        t = float(section["h"])
        e = float(section["E"])
        g = e / (2.0 * (1.0 + float(section.get("nu", 0.2))))
        if length <= 0 or t <= 0:
            continue
        inertia = t * length**3 / 12.0
        stiffness = 1.0 / (h**3 / (12.0 * e * inertia) + 1.2 * h / (g * t * length))
        items.append(
            (float(centre[0]), float(centre[1]), stiffness * u[0] ** 2, stiffness * u[1] ** 2)
        )
    return items


def eccentricity_ratios(
    items: list[tuple[float, float, float, float]], centre: tuple[float, float]
) -> dict[str, float] | None:
    """The centre of rigidity, the elastic radii and Re in X and Y of a storey's stiffness
    ``items`` for the weights' ``centre`` (x, y) [m]; None without stiffness in a direction."""
    dx = sum(i[2] for i in items)
    dy = sum(i[3] for i in items)
    if dx <= 0 or dy <= 0:
        return None
    xk = sum(i[0] * i[3] for i in items) / dy
    yk = sum(i[1] * i[2] for i in items) / dx
    kr = sum(i[2] * (i[1] - yk) ** 2 + i[3] * (i[0] - xk) ** 2 for i in items)
    rex, rey = math.sqrt(kr / dx), math.sqrt(kr / dy)
    ex, ey = abs(centre[0] - xk), abs(centre[1] - yk)
    return {
        "xk": xk,
        "yk": yk,
        "rex": rex,
        "rey": rey,
        "ReX": ey / rex if rex > 0 else 0.0,  # shaking along X: the eccentricity along Y
        "ReY": ex / rey if rey > 0 else 0.0,
        "ex": ex,
        "ey": ey,
    }


def _mass_centres(project: dict[str, Any], levels: list[float]) -> list[tuple[float, float] | None]:
    """Per storey (from the second level) the centre of the masses at and above its top."""
    rows = []
    for node in project.get("nodes", []):
        mass = node.get("mass") or [0.0]
        c = node.get("coords") or []
        if mass and mass[0] and len(c) >= 3:
            rows.append((float(c[0]), float(c[1]), float(c[2]), float(mass[0])))
    out: list[tuple[float, float] | None] = []
    for k in range(1, len(levels)):
        above = [r for r in rows if r[2] >= levels[k] - _TOLERANCE]
        total = sum(r[3] for r in above)
        out.append(
            (sum(r[0] * r[3] for r in above) / total, sum(r[1] * r[3] for r in above) / total)
            if total > 0
            else None
        )
    return out


def stiffness_eccentricity(
    project: dict[str, Any], out_dir: str | Path, project_path: str | Path
) -> dict[str, Any]:
    """Rs, Fs, Re, Fe of every storey and direction of the linear model ``project`` (its
    static cases EX, EY in ``out_dir``): ``{"rows": [{"storey", "bottom", "top", "direction",
    "drift", "rs", "Rs", "Fs", "Re", "Fe", "Fes"}], "notes"}``."""
    from saengine.fem.display import _last
    from saengine.fem.irregularity import _static_results
    from saengine.fem.story_response import _displacements, _level_nodes, storey_levels

    rule = table()
    notes: list[str] = []
    if rule is None:
        return {"rows": [], "notes": notes}
    named = storey_levels(project, project_path)
    levels = [float(lv["z"]) for lv in named]
    results = _static_results(out_dir, {"EX", "EY"})
    level_nodes = _level_nodes(project, levels)
    centres = _mass_centres(project, levels)
    rows: list[dict[str, Any]] = []
    for axis, a in (("X", 0), ("Y", 1)):
        case = results.get(f"E{axis}")
        if case is None or len(levels) < 2:
            notes.append(f"no static case E{axis}: Rs and Fs of {axis} not found")
            continue
        _, result = case
        disp = {n: _last(result.node_disp, n, 6) for nodes in level_nodes for n in nodes}
        means = [d[f"avg{axis}"] for d in _displacements(disp, level_nodes)]
        inverse = []
        for k in range(1, len(levels)):
            low, high = means[k - 1], means[k]
            drift = abs(high - low) if low is not None and high is not None else 0.0
            h = levels[k] - levels[k - 1]
            inverse.append(h / drift if drift > 1e-12 else None)
        known = [r for r in inverse if r is not None]
        mean = sum(known) / len(known) if known else None
        for k in range(1, len(levels)):
            rs = inverse[k - 1]
            ratio = rs / mean if rs is not None and mean else None
            fs = stiffness_factor(ratio, rule.shapeFactors) if ratio is not None else 1.0
            items = storey_stiffness_items(project, levels[k - 1], levels[k])
            centre = centres[k - 1]
            ecc = eccentricity_ratios(items, centre) if centre is not None else None
            re = ecc[f"Re{axis}"] if ecc is not None else None
            fe = eccentricity_factor(re, rule.shapeFactors) if re is not None else 1.0
            rows.append(
                {
                    "storey": named[k]["name"],
                    "bottom": round(levels[k - 1], 3),
                    "top": round(levels[k], 3),
                    "direction": axis,
                    "drift": None if rs is None else 1.0 / rs,
                    "rs": rs,
                    "Rs": ratio,
                    "Fs": fs,
                    "Re": re,
                    "Fe": fe,
                    "Fes": fs * fe,
                    "rsOk": ratio is None or ratio >= rule.shapeFactors.rsLimit - 1e-9,
                    "reOk": re is None or re <= rule.shapeFactors.reLimit + 1e-9,
                    "elasticRadius": None if ecc is None else ecc[f"re{axis.lower()}"],
                    "eccentricity": None if ecc is None else ecc["ey" if axis == "X" else "ex"],
                }
            )
    notes.append(
        "storey stiffness: 12 E I / h³ of the columns and the in-plane flexure and shear of the "
        "walls, the beams rigid; the weights' centre that of the masses at and above the "
        "storey's top (SAEngine practice)"
    )
    return {"rows": rows, "notes": notes}


# ───────────────────────────── the storeys' capacity Qu ─────────────────────────────


def storey_capacity(
    project: dict[str, Any], analysis: dict[str, Any], results: Any, levels: list[float],
    drift_limit: float,
) -> dict[str, Any]:  # fmt: skip
    """Qu [N] of each storey (between consecutive ``levels``) of a pushover run: ``{"Qu":
    [...], "step", "drift", "reached"}`` (see the module notes)."""
    from saengine.fem.story_response import _level_nodes

    dof = int(analysis["control_dof"]) - 1
    sign = 1.0 if float(analysis.get("target_disp", 1.0)) >= 0 else -1.0
    nodes = {int(n["id"]): n for n in project.get("nodes", [])}
    patterns = {p["id"]: p for p in project.get("load_patterns", [])}
    pattern: list[tuple[float, float]] = []
    for pid in analysis.get("pattern_ids", []):
        for load in patterns.get(pid, {}).get("nodal_loads", []):
            node = nodes.get(int(load["node_id"]))
            if node is None:
                continue
            pattern.append((float(node["coords"][2]), float(load["forces"][dof])))
    total = sum(f for _, f in pattern)
    if not total or len(levels) < 2:
        raise ValueError("the pushover has no lateral load pattern")
    shares = [
        sum(f for z, f in pattern if z > levels[k - 1] + _TOLERANCE) / total
        for k in range(1, len(levels))
    ]
    level_nodes = _level_nodes(project, levels)
    base_shear = sign * np.asarray(results.base_shear, dtype=float)
    steps = len(base_shear)

    def mean_disp(k: int, step: int) -> float | None:
        rows = [
            float(np.asarray(results.node_disp[n])[step][dof])
            for n in level_nodes[k]
            if n in results.node_disp
        ]
        return sign * sum(rows) / len(rows) if rows else None

    reached = None
    worst_drift = 0.0
    for step in range(steps):
        drifts = []
        for k in range(1, len(levels)):
            low = mean_disp(k - 1, step) if k - 1 > 0 else 0.0
            high = mean_disp(k, step)
            base_low = mean_disp(k - 1, 0) if k - 1 > 0 else 0.0
            base_high = mean_disp(k, 0)
            if None in (low, high, base_low, base_high):
                drifts.append(0.0)
                continue
            moved = (high - base_high) - (low - base_low)  # type: ignore[operator]
            drifts.append(moved / (levels[k] - levels[k - 1]))
        worst_drift = max(worst_drift, max(drifts, default=0.0))
        if max(drifts, default=0.0) >= drift_limit:
            reached = step
            break
    if reached is not None:
        shear = float(base_shear[reached])
        qu = [shear * s for s in shares]
        return {"Qu": qu, "step": reached, "drift": drift_limit, "reached": True}
    peak = int(np.argmax(base_shear))
    shear = float(base_shear[peak])
    return {
        "Qu": [shear * s for s in shares],
        "step": peak,
        "drift": worst_drift,
        "reached": False,
    }


def _worst_rank(folder: Path, order: list[str]) -> str | None:
    """The worst member rank of the design run beside the pushover (``model.results/
    design-report.json``), None without one."""
    path = folder / "model.results" / "design-report.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    report = report.get("result", report) if isinstance(report, dict) else {}
    found = [
        c.get("rank")
        for e in report.get("elements", []) or []
        for c in e.get("checks", []) or []
        if c.get("rank") in order
    ]
    return max(found, key=order.index) if found else None


def evaluate(
    project: dict[str, Any],
    analysis: dict[str, Any],
    results: Any,
    settings: Any,
    project_path: Any = None,
) -> dict[str, Any]:
    """Qu ≥ Qun of every storey in the direction of one pushover run (``project_path``: the
    pushover model's file; the linear model ``model.osmodel`` and its results beside it give
    Qud, Rs and Re). ``{"available": False, "reason"}`` when the pack has no
    ``horizontalCapacity`` table or the inputs are missing."""
    rule = table()
    if rule is None:
        return {
            "available": False,
            "reason": "the code pack does not check the horizontal capacity",
        }
    if settings is None or project_path is None:
        return {"available": False, "reason": "the project settings could not be read"}
    folder = Path(project_path).resolve().parent
    model_path = folder / "model.osmodel"
    try:
        linear = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False, "reason": "the linear analysis model was not found"}
    from saengine.fem.story_response import _derivation_summary, storey_levels

    axis = "X" if int(analysis.get("control_dof", 1)) == 1 else "Y"
    summary = _derivation_summary(linear, model_path)
    terms = (((summary.get("seismic") or {}).get(f"E{axis}") or {}).get("shearCoefficient")) or {}
    storeys = terms.get("storeys") or []
    if not storeys:
        return {
            "available": False,
            "reason": "the derivation has no storey shear coefficients (Ai): derive the model "
            "under the code pack again",
        }
    named = storey_levels(linear, model_path)
    levels = [float(lv["z"]) for lv in named]
    try:
        capacity = storey_capacity(project, analysis, results, levels, rule.capacityDrift)
    except (ValueError, KeyError, IndexError) as error:
        return {"available": False, "reason": str(error)}
    shape = stiffness_eccentricity(linear, folder / "model.results", model_path)
    factors = {(r["top"], r["direction"]): r for r in shape["rows"]}
    system = rule.systems.get(settings.seismic.system) or rule.defaultSystem
    order = rule.memberRanks.order if rule.memberRanks is not None else [rule.defaultRank]
    rank = _worst_rank(folder, order) or rule.defaultRank
    ds = structural_factor(system.material, rank, system.betaU, rule)
    base = levels[0]
    rows = []
    for k in range(1, len(levels)):
        height = levels[k] - base
        found = min(storeys, key=lambda s: abs(float(s["height"]) - height))
        qud = float(found["Ciu"]) * float(found["above_kN"])
        shape_row = factors.get((round(levels[k], 3), axis)) or {}
        fs = float(shape_row.get("Fs", 1.0))
        fe = float(shape_row.get("Fe", 1.0))
        qun = required_capacity(ds, fs, fe, qud)
        qu = capacity["Qu"][k - 1] / 1e3
        rows.append(
            {
                "storey": named[k]["name"],
                "direction": axis,
                "weight_kN": float(found["above_kN"]),
                "Ai": float(found["Ai"]),
                "Ciu": float(found["Ciu"]),
                "Qud_kN": qud,
                "Ds": ds,
                "Fs": fs,
                "Fe": fe,
                "Fes": fs * fe,
                "Qun_kN": qun,
                "Qu_kN": qu,
                "ratio": qu / qun if qun > 0 else None,
                "ok": qu >= qun - 1e-9,
            }
        )
    notes = list(shape["notes"])
    if not capacity["reached"]:
        notes.append(
            f"the pushover ended before a storey drift of {rule.capacityDrift:g}: Qu is the "
            f"storeys' share of the largest base shear (largest storey drift "
            f"{capacity['drift']:.4f}); push further for the code's capacity"
        )
    if rank == rule.defaultRank and _worst_rank(folder, order) is None:
        notes.append(
            f"no member ranks in the design run: rank {rank} assumed (run the design first)"
        )
    return {
        "available": True,
        "direction": axis,
        "rank": rank,
        "material": system.material,
        "betaU": system.betaU,
        "Ds": ds,
        "capacityDrift": rule.capacityDrift,
        "reached": capacity["reached"],
        "step": capacity["step"],
        "rows": rows,
        "shape": shape["rows"],
        "ok": all(r["ok"] for r in rows),
        "clause": code_context.cite("horizontalCapacity", "required") or rule.source,
        "notes": notes,
    }

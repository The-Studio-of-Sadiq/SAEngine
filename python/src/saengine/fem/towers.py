"""Podium and multi-tower buildings: the checks of each tower above a common podium.

The floor plan names the story at the top of the podium (``podiumTop``) and the towers above it
(``towers``: a plan region each); the building model carries them with the regions in mm
(:class:`saengine.library.bim.BimTower`). The analysis model gives each tower its own rigid
diaphragm on every floor above the podium (:mod:`saengine.fem.derive`), so the towers move on
their own and meet only through the podium. This module checks each tower as the response
spectrum design (:mod:`saengine.fem.seismic_design`) checks the building, with the same
functions on the tower's own nodes:

The clauses are the code pack's (``seismic.clauses``; the references below are the default
pack's, the default pack's Part 6).

- **Period** (Sec 2.5.7.2 (a), p. 627, a structural dynamics procedure): per
  direction the mode with the largest effective mass of the tower above the podium, M_eff,t,k =
  V_t,k / Sa_k, V_t,k = Σ m·ω_k²·u_k over the tower's nodes (u_k the mode's peak displacement
  Γ·φ·Sa/ω², so V_t,k = Γ_k·Σ m·φ_k·Sa_k), and its share of the tower's mass.
- **Base shear** at the podium top: the tower's response spectrum shear V_rs,t, the modal shears
  V_t,k combined with the case's own rule, against the tower's share of the equivalent static
  forces V_t (the lateral loads of EX and EY on the tower's nodes above the podium). Where V_rs,t
  is less than 85 % of V_t the tower's forces need the factor 0.85·V_t / V_rs,t (Sec 2.5.9.4,
  p. 635); the design scales the whole building by the largest factor of the building and its
  towers.
- **Drift** (Sec 2.5.7.7, 2.5.9.4, 2.5.14.1, Table 6.2.21, pp. 631, 635, 647-648) and
  **torsional irregularity** (Sec 2.5.5.3.1(i), p. 617) of the tower's storeys, from the podium
  top up, at the plan positions of the tower only (:func:`seismic_design.storey_drifts`,
  :func:`seismic_design.torsional_irregularity`): a tower's own edges, not those of the podium
  or of the other towers, set its torsion ratio.
- **Notes** on the diaphragms: the podium top joins the towers and carries their storey shears
  into the podium's frames and walls (a transfer floor, whose in-plane forces this check does not
  design); a tower much narrower than the podium is a vertical geometric irregularity (setback,
  Sec 2.5.5.3.2: more than the pack's ``seismic.irregularities.geometry.adjacent``, 130 % in
  the default pack, of the dimension of the storey above).

Units follow the model: m, N (the summary gives kN).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

#: Plan and level tolerance [m].
TOLERANCE = 1e-3

#: The clauses of the tower checks: keys of the code pack's ``seismic.clauses``.
CLAUSE_KEYS = ("period", "scale", "drift", "irregularity", "setback")


def clauses() -> dict[str, str]:
    """The clause references of the tower checks, from the code pack in force (each after the
    code's name; '' for a clause the pack does not give)."""
    from saengine.codes import context as code_context

    return {key: code_context.cite("seismic", key) for key in CLAUSE_KEYS}


def setback_ratio() -> float | None:
    """Vertical geometric irregularity: a storey's horizontal dimension more than this times
    the storey above's (the code pack's ``seismic.irregularities.geometry.adjacent``); None
    when the pack gives no such rule."""
    from saengine.codes import context as code_context

    rules = getattr(code_context.table("seismic"), "irregularities", None)
    geometry = getattr(rules, "geometry", None) if rules is not None else None
    return None if geometry is None else float(geometry.adjacent)


@dataclass(frozen=True)
class TowerRegion:
    """A tower's plan region [m] above the podium top."""

    id: str
    name: str
    boundary: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Towers:
    """The podium top [m] and the towers of a building model."""

    podium: float
    regions: tuple[TowerRegion, ...]


def towers_of(building: Any) -> Towers | None:
    """The towers of a building model (``saengine.library.bim.BuildingModel`` or its JSON), in m;
    None without a podium top or towers."""
    data = building if isinstance(building, dict) else building.model_dump(mode="json")
    top = data.get("podiumTop")
    towers = data.get("towers") or []
    levels = {s["id"]: float(s["elevation"]) for s in data.get("stories", [])}
    if top is None or top not in levels or not towers:
        return None
    return Towers(
        podium=round(levels[top] / 1e3, 6),
        regions=tuple(
            TowerRegion(
                id=str(t["id"]),
                name=str(t.get("name") or t["id"]),
                boundary=tuple((float(x) / 1e3, float(y) / 1e3) for x, y in t["boundary"]),
            )
            for t in towers
        ),
    )


def towers_beside(project_path: str | Path) -> Towers | None:
    """The towers of the building model beside an analysis model (``06 BIM/bim.json`` of the
    project ``08 FEM/model.osmodel`` is in), or None."""
    root = Path(project_path).resolve().parent.parent
    try:
        building = json.loads((root / "06 BIM/bim.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return towers_of(building)
    except (KeyError, TypeError, ValueError):
        return None


def inside(x: float, y: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    """Whether (x, y) is inside ``polygon`` or on its edge (within :data:`TOLERANCE`)."""
    hit = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        length = math.hypot(x2 - x1, y2 - y1)
        if length:
            t = ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / length**2
            foot = (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
            if -1e-9 <= t <= 1 + 1e-9 and math.hypot(x - foot[0], y - foot[1]) <= TOLERANCE:
                return True
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def region_of(x: float, y: float, towers: Towers) -> str | None:
    """The id of the tower whose region holds plan point (x, y) [m], the first when regions
    overlap; None outside every tower."""
    return next((r.id for r in towers.regions if inside(x, y, r.boundary)), None)


def tower_nodes(project: dict[str, Any], towers: Towers) -> dict[str, dict[str, set[int]]]:
    """Per tower its nodes ``{"above": ids above the podium top, "podium": ids at it}`` (by the
    plan region they are in)."""
    out: dict[str, dict[str, set[int]]] = {
        r.id: {"above": set(), "podium": set()} for r in towers.regions
    }
    for node in project.get("nodes", []):
        x, y, z = (float(v) for v in node["coords"][:3])
        if z < towers.podium - TOLERANCE:
            continue
        found = region_of(x, y, towers)
        if found is None:
            continue
        out[found]["podium" if abs(z - towers.podium) <= TOLERANCE else "above"].add(
            int(node["id"])
        )
    return out


def _subset(project: dict[str, Any], ids: set[int]) -> dict[str, Any]:
    return {
        **project,
        "nodes": [n for n in project.get("nodes", []) if int(n["id"]) in ids],
    }


def _masses(project: dict[str, Any], ids: set[int]) -> dict[int, np.ndarray]:
    out = {}
    for node in project.get("nodes", []):
        if int(node["id"]) in ids:
            m = np.asarray(node.get("mass") or [0.0] * 3, dtype=float)[:3]
            if np.any(m):
                out[int(node["id"])] = np.pad(m, (0, 3 - m.size))
    return out


def _static_shear(project: dict[str, Any], case: str, ids: set[int], axis: int) -> float:
    """The lateral load of the equivalent static case ``case`` (EX, EY) on the nodes ``ids`` [N]."""
    pattern = next((p for p in project.get("load_patterns", []) if p.get("name") == case), None)
    total = 0.0
    for load in (pattern or {}).get("nodal_loads", []):
        if int(load["node_id"]) in ids:
            total += float(load["forces"][axis])
    return abs(total)


def tower_shears(
    project: dict[str, Any], towers: Towers, spectra: dict[str, dict[str, Any]]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Per tower and direction: its period (the mode with the largest effective mass of the
    tower: ``"period"`` s, ``"mode"``, ``"massRatio"``), its response spectrum shear at the podium
    top ``"dynamic"`` [N] (the modal shears combined with the case's rule), its share of the
    equivalent static shear ``"static"`` [N] and the factor ``"scale"`` = max(1, 0.85·static /
    dynamic) (Sec 2.5.9.4). Directions without modes are left out."""
    from saengine.fem.seismic_design import combine, scale_factor

    nodes = tower_nodes(project, towers)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for region in towers.regions:
        above = nodes[region.id]["above"]
        masses = _masses(project, above)
        per_axis: dict[str, dict[str, Any]] = {}
        for axis, data in spectra.items():
            a = 0 if axis == "X" else 1
            used = [k for k, m in enumerate(data["modes"]) if m.get("angular_frequency", 0) > 0]
            omegas = [float(data["modes"][k]["angular_frequency"]) for k in used]
            if not used:
                continue
            shears, effective = [], []
            for k, omega in zip(used, omegas, strict=True):
                peaks = data["peaks"][k]
                v = sum(
                    float(m[a]) * omega**2 * float(np.asarray(peaks.get(n, np.zeros(3)))[a])
                    for n, m in masses.items()
                )
                shears.append(v)
                sa = float(data["modes"][k].get("sa_at_period", 0.0))
                effective.append(v / sa if sa > 0 else 0.0)
            total = sum(float(m[a]) for m in masses.values())
            best = int(np.argmax(effective))
            mode = data["modes"][used[best]]
            dynamic = float(combine(np.array(shears), omegas, data["damping"], data["rule"]))
            static = _static_shear(project, f"E{axis}", above, a)
            per_axis[axis] = {
                "period": float(mode.get("period") or 2 * math.pi / omegas[best]),
                "mode": int(mode.get("mode_number", used[best] + 1)),
                "massRatio": effective[best] / total if total > 0 else 0.0,
                "dynamic": dynamic,
                "static": static,
                "scale": scale_factor(static, dynamic) if dynamic > 0 else 1.0,
            }
        out[region.id] = per_axis
    return out


def tower_scale(shears: dict[str, dict[str, dict[str, Any]]], axis: str) -> float:
    """The largest factor any tower needs in ``axis`` (1 without towers)."""
    return max([1.0] + [t[axis]["scale"] for t in shears.values() if axis in t])


def tower_checks(
    project: dict[str, Any],
    towers: Towers,
    shears: dict[str, dict[str, dict[str, Any]]],
    spectra: dict[str, dict[str, Any]],
    levels: list[float],
    amplification: float | dict[str, float],
    allowable: float,
    scale: dict[str, float],
    forces: dict[str, Any] | None,
    torsion_factor: dict[str, float] | None,
) -> dict[str, Any]:
    """The checks of every tower: ``{"podium" m, "towers": [{"id", "name", "levels", "period":
    {"X": {"period" s, "mode", "massRatio"}}, "baseShear": {"X": {"static" kN, "dynamic" kN,
    "scale"}}, "drift": rows, "torsionalIrregularity": rows}], "notes", "clauses"}``. ``shears``
    of :func:`tower_shears`; ``spectra``, ``levels``, ``amplification``, ``allowable``, ``scale``
    (the design's, with the towers' factors in), ``forces`` and ``torsion_factor`` as in
    :func:`saengine.fem.seismic_design.seismic_design`."""
    from saengine.fem.seismic_design import (
        _seismic,
        storey_drifts,
        torsional_irregularity,
    )

    nodes = tower_nodes(project, towers)
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    refs = clauses()
    for region in towers.regions:
        above, at_podium = nodes[region.id]["above"], nodes[region.id]["podium"]
        if not above:
            notes.append(
                f"tower {region.name}: no node of the analysis model above the podium top in "
                "its region"
            )
            continue
        sub = _subset(project, above | at_podium)
        zs = [float(n["coords"][2]) for n in sub["nodes"]]
        tower_levels = [towers.podium] + [
            z
            for z in levels
            if z > towers.podium + TOLERANCE and any(abs(z - h) <= TOLERANCE for h in zs)
        ]
        own = shears.get(region.id, {})
        row: dict[str, Any] = {
            "id": region.id,
            "name": region.name,
            "levels": tower_levels,
            "period": {
                axis: {k: v[k] for k in ("period", "mode", "massRatio")} for axis, v in own.items()
            },
            "baseShear": {
                axis: {
                    "static": v["static"] / 1e3,
                    "dynamic": v["dynamic"] / 1e3,
                    "scale": v["scale"],
                }
                for axis, v in own.items()
            },
        }
        for axis, v in own.items():
            if v["scale"] > 1.0 + 1e-9:
                notes.append(
                    f"tower {region.name}, {axis}: its response spectrum shear at the podium top "
                    f"({v['dynamic'] / 1e3:.0f} kN) is less than {100 * _seismic().minimumScale:.0f} % "
                    f"of its share of the static shear ({v['static'] / 1e3:.0f} kN): factor "
                    f"{v['scale']:.3f}; the design scales the building by "
                    f"{float(scale.get(axis, 1.0)):.3f}, the largest of the building and its "
                    f"towers ({refs['scale']})"
                )
        row["drift"] = storey_drifts(
            sub, spectra, tower_levels, amplification, allowable, forces, torsion_factor
        )
        row["torsionalIrregularity"] = torsional_irregularity(
            sub, spectra, tower_levels, scale, forces
        )
        failing = [d for d in row["drift"] if not d["ok"]]
        if failing:
            worst = max(failing, key=lambda d: d["ratio"])
            notes.append(
                f"tower {region.name}: storey drift {100 * worst['ratio']:.2f} % in "
                f"{worst['direction']} between {worst['bottom']:g} and {worst['top']:g} m "
                f"exceeds the allowable {100 * allowable:.2f} % ({refs['drift']})"
            )
        worst = max(row["torsionalIrregularity"], key=lambda r: r["ratio"], default=None)
        if worst is not None and worst["irregular"]:
            kind = (
                "extreme torsional irregularity" if worst["extreme"] else "torsional irregularity"
            )
            notes.append(
                f"tower {region.name}, {worst['direction']}: {kind}, storey drift at one end "
                f"{worst['ratio']:.2f} × the average between {worst['bottom']:g} and "
                f"{worst['top']:g} m ({refs['irregularity']})"
            )
        rows.append(row)
    notes.extend(_diaphragm_notes(project, towers, nodes, refs))
    return {"podium": towers.podium, "towers": rows, "notes": notes, "clauses": refs}


def _extent(points: list[tuple[float, float]], axis: int) -> float:
    values = [p[axis] for p in points]
    return max(values) - min(values) if values else 0.0


def _diaphragm_notes(
    project: dict[str, Any],
    towers: Towers,
    nodes: dict[str, dict[str, set[int]]],
    refs: dict[str, str],
) -> list[str]:
    """The podium top as the floor that joins the towers, and each tower's setback."""
    coords = {int(n["id"]): n["coords"] for n in project.get("nodes", [])}
    podium = [
        (float(c[0]), float(c[1]))
        for c in coords.values()
        if abs(float(c[2]) - towers.podium) <= TOLERANCE
    ]
    out = [
        (
            f"podium top at {towers.podium:g} m: each of the {len(towers.regions)} towers has its "
            "own rigid diaphragm above it, so they move on their own; the podium top floor joins "
            "them and carries each tower's storey shear into the podium's frames and walls (a "
            "transfer floor). Its in-plane forces, collectors and chords are not designed here: "
            "check them, with the floor modelled flexible (Project Settings, Analysis model) if it "
            "is long or has large openings"
        )
    ]
    ratio = setback_ratio()
    for region in towers.regions if ratio is not None else ():
        points = [(float(coords[n][0]), float(coords[n][1])) for n in nodes[region.id]["above"]]
        for axis, name in ((0, "X"), (1, "Y")):
            tower, base = _extent(points, axis), _extent(podium, axis)
            if tower > 0 and base > ratio * tower:
                out.append(
                    f"tower {region.name}: the podium is {base / tower:.2f} times as wide in {name} "
                    f"({base:.1f} m against {tower:.1f} m), more than {ratio:g}: a vertical "
                    f"geometric irregularity (setback, {refs['setback']}); the response spectrum "
                    "design takes it in, the equivalent static method alone would not"
                )
    return out

"""Building irregularities, the dynamic analysis requirement and the soft storey design.

What the code pack in force (its ``seismic`` table) asks, worked out from the building model
(``06 BIM/bim.json``), its object types and materials, and the static earthquake cases of an
analysis run:

- **Plan irregularities** (``seismic.irregularities``):
  - torsion: the storey drift at one end of the plan over the average of the two ends, from
    the response spectrum design's check when there is one
    (:func:`saengine.fem.seismic_design.torsional_irregularity`), else from the static cases
    (the eccentric cases EXP/EXN, EYP/EYN where the model has them, else EX, EY);
  - re-entrant corners: each reflex corner of a floor's outline, the projections beyond it
    measured from the corner to the floor's extent, against the share of the plan dimension;
  - diaphragm discontinuity: the open area of a floor (its holes) against its gross enclosed
    area, and the change of the diaphragm stiffness (floor area × slab thickness) to the next
    floor;
  - out-of-plane offsets: columns and structural walls that stop above the base on something
    else than a column or wall (:func:`saengine.design.seismic_rules.discontinuities`), unless
    the wall continues below in its own plane (then an in-plane offset, below);
  - non-parallel systems: structural walls and frame beams (column to column) off the major
    axes of the plan by more than the pack's tolerance.
- **Vertical irregularities**:
  - soft and extreme soft storey: the storey stiffness k = V / Δ (the storey shear of EX / EY
    over the storey drift of the floors' mean displacement) against the storey above and the
    mean of the three above;
  - mass: the seismic weight of each floor (the nodes' masses) against the adjacent ones, a
    roof lighter than the floor below not compared;
  - vertical geometry: the plan extent of the storey's columns and walls against the adjacent
    storeys, a one-storey penthouse not compared;
  - in-plane discontinuity: a wall continued below in its plane with an offset more than its
    length;
  - weak and extreme weak storey: the storey lateral strength estimated by the pack's method
    (``shearStrength``: the nominal shear strength of the storey's columns and walls) against
    the storey above.
- **Dynamic analysis** (``seismic.dynamicAnalysis``): required above the pack's height of the
  zone, a lower one for irregular buildings; the equivalent static method also needs the period
  below the pack's limits and no vertical irregularity.
- **Soft storey design** (``seismic.softStorey``): the members of a soft storey (found, or named
  in the settings) and the pack's factors on their earthquake forces (columns and beams, walls).
- **Diaphragm connections** (``seismic.diaphragmConnections``): whether the connection forces go
  up (the pack's ``transfer.diaphragm.irregularIncrease``), and whether the projecting wings need
  their own chord and collector design.

Every number, label and clause reference comes from the code pack; a pack without these tables
leaves the checks "not covered". Lengths: the building in mm, the analysis model and the results
here in m (stiffness N/m, weights and strengths N).
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

G = 9.80665
#: Position tolerance [mm].
TOLERANCE = 50.0


def _seismic() -> Any:
    return code_context.table("seismic")


def table() -> Any | None:
    """The irregularity thresholds of the pack in force; None when it does not cover them."""
    return getattr(_seismic(), "irregularities", None)


def _code() -> str:
    pack = code_context.current()
    return pack.edition or pack.name


def clause(key: str) -> str:
    """The pack's clause reference of an irregularity type or group (after the pack's name)."""
    found = table()
    text = (found.clauses.get(key) if found is not None else None) or ""
    return f"{_code()} {text}" if text else ""


def label(kind: str) -> str:
    found = table()
    entry = (found.labels.get(kind) if found is not None else None) or {}
    return entry.get("label", kind)


def group(kind: str) -> str:
    found = table()
    entry = (found.labels.get(kind) if found is not None else None) or {}
    return entry.get("group", "")


# ─────────────────────────────────────── storeys ───────────────────────────────────────


@dataclass(frozen=True)
class Storey:
    name: str
    #: Floor and ceiling levels [m].
    bottom: float
    top: float


def storeys_of(building: Any) -> list[Storey]:
    """The storeys of the building bottom up: from the base (the lowest column or wall bottom)
    to each building storey's level above it."""
    elements = list(getattr(building, "elements", []))
    bottoms = [float(e.bottom) for e in elements if getattr(e, "kind", "") in ("column", "wall")]
    if not bottoms:
        return []
    base = min(bottoms)
    stories = sorted(getattr(building, "stories", []), key=lambda s: float(s.elevation))
    out: list[Storey] = []
    below = base
    for story in stories:
        z = float(story.elevation)
        if z <= below + TOLERANCE:
            continue
        out.append(Storey(story.name, below / 1e3, z / 1e3))
        below = z
    return out


def _in_storey(bottom: float, top: float, storey: Storey) -> bool:
    """An element from ``bottom`` to ``top`` [mm] spans (part of) the storey."""
    return bottom < storey.top * 1e3 - TOLERANCE and top > storey.bottom * 1e3 + TOLERANCE


# ─────────────────────────────────────── the threshold rules ───────────────────────────────────────


def below_ratio(values: list[float | None], k: int, rule: Any) -> float | None:
    """The smallest of value_k / (``rule.storeyAbove`` × value_k+1) and value_k /
    (``rule.threeAbove`` × the mean of the three above): below 1 the storey is irregular. None
    when it cannot be compared (no value, or nothing above)."""
    if rule is None or values[k] is None:
        return None
    ratios = []
    above = values[k + 1] if k + 1 < len(values) else None
    if rule.storeyAbove and above:
        ratios.append(values[k] / (rule.storeyAbove * above))
    three = values[k + 1 : k + 4]
    if rule.threeAbove and len(three) == 3 and all(v for v in three):
        ratios.append(values[k] / (rule.threeAbove * (sum(three) / 3)))  # type: ignore[arg-type]
    return min(ratios) if ratios else None


def ratio_checks(values: list[float | None], rule: Any, extreme: Any) -> list[dict[str, Any]]:
    """Per storey ``{"ratio", "irregular", "extreme", "toAbove", "toThreeAbove"}`` of a soft or
    weak storey rule: ``toAbove`` value_k / value_k+1, ``toThreeAbove`` over the mean of the three
    above (None where there are none)."""
    out = []
    for k, value in enumerate(values):
        above = values[k + 1] if k + 1 < len(values) else None
        three = values[k + 1 : k + 4]
        mean = sum(three) / 3 if len(three) == 3 and all(three) else None  # type: ignore[arg-type]
        first = below_ratio(values, k, rule)
        worst = below_ratio(values, k, extreme)
        out.append(
            {
                "toAbove": value / above if value is not None and above else None,
                "toThreeAbove": value / mean if value is not None and mean else None,
                "irregular": first is not None and first < 1 - 1e-12,
                "extreme": worst is not None and worst < 1 - 1e-12,
            }
        )
    return out


def adjacent_checks(values: list[float | None], rule: Any) -> list[dict[str, Any]]:
    """Per storey ``{"ratio", "irregular"}``: the largest value_k / value_j over the adjacent
    storeys j, irregular above ``rule.adjacent``. With ``rule.topExempt`` the top storey is not
    compared with the one below when it is the smaller (a roof lighter than the floor below, a
    one-storey penthouse)."""
    n = len(values)
    out = []
    for k, value in enumerate(values):
        ratios = []
        for j in (k - 1, k + 1):
            if not 0 <= j < n or not values[j] or value is None:
                continue
            top_pair = {k, j} == {n - 1, n - 2}
            if rule.topExempt and top_pair and (values[n - 1] or 0) < (values[n - 2] or 0):
                continue
            ratios.append(value / values[j])  # type: ignore[operator]
        ratio = max(ratios) if ratios else None
        out.append({"ratio": ratio, "irregular": ratio is not None and ratio > rule.adjacent})
    return out


# ─────────────────────────────────────── plan geometry ───────────────────────────────────────


def _floors(building: Any, types: dict[str, Any]) -> dict[float, tuple[Any, float]]:
    """Per floor level [m]: (the union of its slabs as a shapely geometry, its stiffness proxy
    Σ area × thickness [mm³])."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    parts: dict[float, list[Any]] = {}
    stiff: dict[float, float] = {}
    for e in getattr(building, "elements", []):
        if getattr(e, "kind", "") != "slab":
            continue
        polygon = Polygon([(float(x), float(y)) for x, y in e.boundary])
        if not polygon.is_valid or polygon.area <= 0:
            continue
        z = round(float(e.elevation) / 1e3, 3)
        parts.setdefault(z, []).append(polygon)
        thickness = float(getattr(types.get(e.type), "thickness", 0.0) or 0.0)
        stiff[z] = stiff.get(z, 0.0) + polygon.area * thickness
    return {z: (unary_union(p), stiff.get(z, 0.0)) for z, p in parts.items()}


def _polygons(geometry: Any) -> list[Any]:
    return list(getattr(geometry, "geoms", [geometry]))


def reentrant_corners(floor: Any, share: float) -> list[dict[str, Any]]:
    """The re-entrant corners of a floor outline [mm]: per reflex corner of its exterior ring
    ``{"x", "y", "projectionX", "projectionY", "shareX", "shareY", "irregular"}``, the
    projections from the corner to the floor's extent on the side the outline leaves open,
    irregular when both are more than ``share`` of the floor's dimension in their direction."""
    from shapely.geometry import Point, Polygon
    from shapely.geometry.polygon import orient

    out = []
    for part in _polygons(floor):
        shape = orient(Polygon(part.exterior), 1.0)  # counter-clockwise
        x0, y0, x1, y1 = shape.bounds
        lx, ly = x1 - x0, y1 - y0
        if lx <= 0 or ly <= 0:
            continue
        ring = list(shape.exterior.coords)[:-1]
        n = len(ring)
        probe = max(1.0, 1e-3 * min(lx, ly))
        for i, (vx, vy) in enumerate(ring):
            px, py = ring[i - 1]
            nx, ny = ring[(i + 1) % n]
            cross = (vx - px) * (ny - vy) - (vy - py) * (nx - vx)
            if cross >= -1e-6:
                continue  # convex or straight
            missing = [
                (sx, sy)
                for sx in (1, -1)
                for sy in (1, -1)
                if not shape.covers(Point(vx + sx * probe, vy + sy * probe))
            ]
            if len(missing) != 1:
                continue
            sx, sy = missing[0]
            proj_x = (x1 - vx) if sx > 0 else (vx - x0)
            proj_y = (y1 - vy) if sy > 0 else (vy - y0)
            out.append(
                {
                    "x": vx,
                    "y": vy,
                    "projectionX": proj_x,
                    "projectionY": proj_y,
                    "shareX": proj_x / lx,
                    "shareY": proj_y / ly,
                    "irregular": proj_x > share * lx and proj_y > share * ly,
                }
            )
    return out


def opening_share(floor: Any) -> tuple[float, float]:
    """(open area, gross enclosed area) [mm²] of a floor: the holes inside its outlines."""
    from shapely.geometry import Polygon

    gross = sum(Polygon(p.exterior).area for p in _polygons(floor))
    return max(gross - float(floor.area), 0.0), gross


def _angle(a: Any, b: Any) -> float | None:
    dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
    if math.hypot(dx, dy) < 1.0:
        return None
    return math.degrees(math.atan2(dy, dx)) % 90.0


def nonparallel_elements(
    lines: list[tuple[str, Any, Any]], tolerance: float
) -> tuple[float | None, list[dict[str, Any]]]:
    """(the major axis angle [°, 0-90], the elements off it by more than ``tolerance`` °) of
    ``lines`` ``(id, start, end)``: the major axes are the direction (mod 90°) with the most
    length (1° bins)."""
    bins: dict[int, float] = {}
    angles = []
    for element_id, a, b in lines:
        angle = _angle(a, b)
        if angle is None:
            continue
        length = math.dist([float(v) for v in a[:2]], [float(v) for v in b[:2]])
        bins[round(angle) % 90] = bins.get(round(angle) % 90, 0.0) + length
        angles.append((element_id, angle))
    if not bins:
        return None, []
    major = float(max(bins, key=lambda k: bins[k]))
    off = []
    for element_id, angle in angles:
        deviation = abs(angle - major) % 90.0
        deviation = min(deviation, 90.0 - deviation)
        if deviation > tolerance:
            off.append({"id": element_id, "deviation": deviation})
    return major, off


def _line_offset(upper: Any, lower: Any) -> float | None:
    """The in-plane offset [mm] of wall ``upper`` from wall ``lower`` when both lie on one line
    (parallel and within the tolerance across it): the distance between their midpoints along
    the line; None when they are not on one line."""
    a, b = np.asarray(upper.start, dtype=float), np.asarray(upper.end, dtype=float)
    c, d = np.asarray(lower.start, dtype=float), np.asarray(lower.end, dtype=float)
    u = b - a
    length = float(np.linalg.norm(u))
    if length < 1.0 or float(np.linalg.norm(d - c)) < 1.0:
        return None
    u /= length
    v = (d - c) / float(np.linalg.norm(d - c))
    if abs(u[0] * v[1] - u[1] * v[0]) > 0.02:
        return None  # not parallel
    normal = np.array([-u[1], u[0]])
    if abs(float(np.dot(c - a, normal))) > TOLERANCE:
        return None  # parallel, another line
    return abs(float(np.dot((c + d) / 2 - (a + b) / 2, u)))


def offsets(building: Any, objects: Any, materials: Any) -> list[dict[str, Any]]:
    """The discontinuous columns and walls (:func:`saengine.design.seismic_rules.
    discontinuities`) classified: ``{"id", "kind", "elevation" [m], "type":
    "inPlaneDiscontinuity" | "outOfPlaneOffset", "offset", "length" [mm] | None}``. A wall with a
    wall below on its own line is an in-plane offset when the offset is more than the pack's
    share of its length (else a discontinuity the pack does not count: left out); everything
    else (columns, walls without one below on their line) is an out-of-plane offset."""
    from saengine.design import seismic_rules as sr

    found = table()
    share = found.inPlaneOffset if found is not None else None
    walls = [e for e in getattr(building, "elements", []) if getattr(e, "kind", "") == "wall"]
    by_id = {e.id: e for e in getattr(building, "elements", [])}
    out = []
    for item in sr.discontinuities(building, objects, materials):
        element = by_id.get(item["id"])
        entry = {
            "id": item["id"],
            "kind": item["kind"],
            "elevation": float(item["elevation"]) / 1e3,
            "type": "outOfPlaneOffset",
            "offset": None,
            "length": None,
        }
        if item["kind"] == "wall" and element is not None:
            length = math.dist(
                [float(v) for v in element.start[:2]], [float(v) for v in element.end[:2]]
            )
            below = [
                o
                for o in walls
                if abs(float(o.top) - float(element.bottom)) <= TOLERANCE
                and _line_offset(element, o) is not None
            ]
            if below:
                offset = min(_line_offset(element, o) for o in below)  # type: ignore[type-var]
                if share is None or offset <= share * length:
                    continue
                entry.update(type="inPlaneDiscontinuity", offset=offset, length=length)
        out.append(entry)
    return out


# ─────────────────────────────────────── storey values ───────────────────────────────────────


def storey_widths(building: Any, storeys: list[Storey]) -> list[dict[str, float | None]]:
    """Per storey the plan extent [mm] in X and Y of its columns and walls."""
    out = []
    for storey in storeys:
        xs, ys = [], []
        for e in getattr(building, "elements", []):
            kind = getattr(e, "kind", "")
            if kind not in ("column", "wall") or not _in_storey(
                float(e.bottom), float(e.top), storey
            ):
                continue
            points = [e.position] if kind == "column" else [e.start, e.end]
            for p in points:
                xs.append(float(p[0]))
                ys.append(float(p[1]))
        out.append(
            {
                "X": (max(xs) - min(xs)) if xs else None,
                "Y": (max(ys) - min(ys)) if ys else None,
            }
        )
    return out


def _fc(materials: dict[str, Any], material_id: str | None) -> float | None:
    m = materials.get(material_id) if material_id else None
    concrete = getattr(m, "concrete", None)
    return float(concrete.fc) if concrete is not None else None


def _fy(materials: dict[str, Any], material_id: str | None) -> float:
    m = materials.get(material_id) if material_id else None
    steel = getattr(m, "steel", None)
    return float(steel.fy) if steel is not None else 0.0


def column_strength(object_type: Any, materials: dict[str, Any], rotation: float = 0.0) -> dict:
    """The nominal shear strength [N] of an RC column type along global X and Y by the pack's
    ``strength`` (Vc = concreteFactor·√f'c·bw·d with d = depthFactor × the depth along the
    force, plus Av·fyt·d/s of its ties); {} when it is not a concrete rectangle or circle."""
    found = table()
    rule = found.strength if found is not None else None
    fc = _fc(materials, getattr(object_type, "material", None))
    profile = getattr(object_type, "profile", None)
    if rule is None or fc is None or profile is None:
        return {}
    reinforcement = getattr(object_type, "reinforcement", None)
    ties = getattr(reinforcement, "transverse", None)
    fyt = _fy(materials, getattr(reinforcement, "material", None)) if reinforcement else 0.0
    root = math.sqrt(fc)
    from saengine.design.rc import bar_area

    def strength(bw: float, depth: float, legs: int) -> float:
        d = rule.depthFactor * depth
        vs = legs * bar_area(ties.dia) * fyt * d / ties.spacing if ties and ties.spacing else 0.0
        return rule.concreteFactor * root * bw * d + vs

    if getattr(profile, "shape", "") == "circle":
        diameter = 2 * float(profile.radius)
        value = strength(diameter, diameter, 2)
        return {"X": value, "Y": value}
    if getattr(profile, "shape", "") != "rectangle":
        return {}
    bx, by = float(profile.xDim), float(profile.yDim)
    legs_y = int(ties.legs) if ties else 0  # legs along the profile's y
    legs_x = int(ties.legsX or ties.legs) if ties else 0
    along_x = strength(by, bx, legs_x)  # force along the profile's x
    along_y = strength(bx, by, legs_y)
    turned = round((float(rotation) % 180.0) / 90.0) % 2 == 1
    return {"X": along_y, "Y": along_x} if turned else {"X": along_x, "Y": along_y}


def wall_strength(element: Any, object_type: Any, materials: dict[str, Any]) -> dict:
    """The in-plane nominal shear strength [N] of a structural RC wall along X and Y (its plane
    resolved into them): Vc = concreteFactor·√f'c·t·d, d = depthFactor·lw, plus ρt·fy of its
    horizontal bars over t·d."""
    found = table()
    rule = found.strength if found is not None else None
    fc = _fc(materials, getattr(object_type, "material", None))
    if rule is None or fc is None or not getattr(object_type, "structural", True):
        return {}
    t = float(getattr(object_type, "thickness", 0.0) or 0.0)
    a, b = element.start, element.end
    dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
    length = math.hypot(dx, dy)
    if length < 1.0 or t <= 0:
        return {}
    d = rule.depthFactor * length
    value = rule.concreteFactor * math.sqrt(fc) * t * d
    reinforcement = getattr(object_type, "reinforcement", None)
    horizontal = getattr(reinforcement, "horizontal", None)
    if horizontal is not None and horizontal.spacing:
        from saengine.design.rc import bar_area

        layers = int(getattr(reinforcement, "layers", 1) or 1)
        av = layers * bar_area(horizontal.dia)
        value += av * _fy(materials, reinforcement.material) * d / float(horizontal.spacing)
    return {"X": value * abs(dx) / length, "Y": value * abs(dy) / length}


def storey_strengths(
    building: Any, objects: Any, materials: Any, storeys: list[Storey]
) -> list[dict[str, float | None]]:
    """Per storey the estimated lateral strength [N] in X and Y: the sum of the shear strengths
    of its RC columns and structural walls (None where none could be estimated)."""
    types = {o.id: o for o in getattr(objects, "objects", [])} if objects is not None else {}
    mats = {m.id: m for m in getattr(materials, "materials", [])} if materials else {}
    out = []
    for storey in storeys:
        total = {"X": 0.0, "Y": 0.0}
        counted = False
        for e in getattr(building, "elements", []):
            kind = getattr(e, "kind", "")
            if kind not in ("column", "wall"):
                continue
            if not _in_storey(float(e.bottom), float(e.top), storey):
                continue
            object_type = types.get(e.type)
            if object_type is None:
                continue
            if kind == "column":
                found = column_strength(object_type, mats, float(getattr(e, "rotation", 0) or 0))
            else:
                found = wall_strength(e, object_type, mats)
            if found:
                counted = True
                total["X"] += found["X"]
                total["Y"] += found["Y"]
        out.append({"X": total["X"] if counted else None, "Y": total["Y"] if counted else None})
    return out


def storey_weights(project: dict[str, Any], levels: list[float]) -> list[float]:
    """The seismic weight [N] at each level (the nodes' masses at the nearest level), bottom up."""
    out = [0.0] * len(levels)
    if not levels:
        return out
    z = np.asarray(levels, dtype=float)
    for node in project.get("nodes", []):
        mass = node.get("mass") or [0.0]
        coords = node.get("coords") or []
        if not mass or not mass[0] or len(coords) < 3:
            continue
        k = int(np.argmin(np.abs(z - float(coords[2]))))
        out[k] += float(mass[0]) * G
    return out


def _static_results(out_dir: str | Path, codes: set[str]) -> dict[str, tuple[dict, Any]]:
    """The static cases ``codes`` of a run: code -> (manifest entry, results)."""
    from opensees_studio.services.results import StaticResults

    from saengine.fem.display import _manifest
    from saengine.fem.story_response import _code, load_cached

    manifest = _manifest(out_dir)
    found: dict[str, tuple[dict, Any]] = {}
    for entry in (manifest or {}).get("cases", []):
        code = _code(str(entry.get("case_name", "")))
        if code not in codes:
            continue
        try:
            result = load_cached(entry, out_dir)
        except Exception:  # noqa: BLE001, S112 - an unreadable case is left out
            continue
        if isinstance(result, StaticResults):
            found[code] = (entry, result)
    return found


def storey_stiffness(
    project: dict[str, Any], results: dict[str, tuple[dict, Any]], levels: list[float]
) -> dict[str, list[float | None]]:
    """Per direction the storey stiffness k = V / Δ [N/m] of each storey (between consecutive
    ``levels`` [m]) under EX, EY: the storey shear of the case's lateral loads (scaled by the
    load factor reached) over the drift of the floors' mean displacement."""
    from saengine.fem.display import _last
    from saengine.fem.story_response import (
        _displacements,
        _level_nodes,
        _pattern_loads,
        _shears,
        _storey_loads,
    )

    analyses = {a["id"]: a for a in project.get("analyses", [])}
    level_nodes = _level_nodes(project, levels)
    out: dict[str, list[float | None]] = {}
    for axis, a in (("X", 0), ("Y", 1)):
        case = results.get(f"E{axis}") or results.get(f"E{axis}P")
        if case is None or len(levels) < 2:
            continue
        entry, result = case
        reached = float(result.load_factors[-1]) if len(result.load_factors) else 1.0
        loads = [
            (z, reached * x, reached * y)
            for z, x, y in _pattern_loads(project, analyses.get(int(entry["case_id"])))
        ]
        forces = _storey_loads(loads, levels)[a]
        shears = _shears(forces)
        disp = {n: _last(result.node_disp, n, 6) for nodes in level_nodes for n in nodes}
        means = [d[f"avg{axis}"] for d in _displacements(disp, level_nodes)]
        values: list[float | None] = []
        for k in range(1, len(levels)):
            low, high = means[k - 1], means[k]
            drift = abs(high - low) if low is not None and high is not None else 0.0
            shear = abs(float(shears[k - 1]))
            values.append(shear / drift if drift > 1e-12 and shear > 0 else None)
        out[axis] = values
    return out


def static_torsion(
    project: dict[str, Any], results: dict[str, tuple[dict, Any]], levels: list[float]
) -> list[dict[str, Any]]:
    """The torsional irregularity check from the static cases: per storey and direction the
    storey drift at the two ends of the plan across the force (the lines of plan positions with
    a node at both levels at the smallest and largest coordinate), each end its largest
    position, the worst of the case's eccentric cases (EXP, EXN) where the model has them, else
    of EX. Rows as :func:`saengine.fem.seismic_design.torsional_irregularity` gives
    (``direction``, ``bottom``, ``top``, ``driftMax``, ``driftAvg``, ``ratio``, ``irregular``,
    ``extreme``) and ``cases``."""
    from saengine.fem.display import _last
    from saengine.fem.seismic_design import _positions

    s = _seismic()
    at_level = _positions(project, levels)
    rows = []
    for axis, a in (("X", 0), ("Y", 1)):
        across = 1 - a
        cases = [c for c in (f"E{axis}P", f"E{axis}N") if c in results] or (
            [f"E{axis}"] if f"E{axis}" in results else []
        )
        if not cases:
            continue
        for k in range(1, len(levels)):
            pairs = {
                p: (at_level[k - 1][p], top)
                for p, top in at_level[k].items()
                if p in at_level[k - 1]
            }
            if not pairs:
                continue
            low = min(p[across] for p in pairs)
            high = max(p[across] for p in pairs)
            if high - low < 1:
                continue
            ends = [[p for p in pairs if abs(p[across] - edge) <= 1] for edge in (low, high)]
            best = None
            for code in cases:
                result = results[code][1]

                def drift(p: Any, result: Any = result, pairs: dict = pairs, a: int = a) -> float:
                    bottom, top = pairs[p]
                    return abs(
                        float(_last(result.node_disp, top, 6)[a])
                        - float(_last(result.node_disp, bottom, 6)[a])
                    )

                end_drifts = [max(drift(p) for p in end) for end in ends]
                d_max, d_avg = max(end_drifts), sum(end_drifts) / 2
                ratio = d_max / d_avg if d_avg > 1e-12 else 1.0
                if best is None or ratio > best["ratio"]:
                    best = {
                        "direction": axis,
                        "bottom": round(levels[k - 1], 3),
                        "top": round(levels[k], 3),
                        "driftMax": d_max,
                        "driftAvg": d_avg,
                        "ratio": ratio,
                        "irregular": bool(ratio > s.torsionIrregular + 1e-12),
                        "extreme": bool(ratio > s.torsionExtreme + 1e-12),
                        "cases": cases,
                    }
            if best is not None:
                rows.append(best)
    return rows


# ─────────────────────────────────────── dynamic analysis ───────────────────────────────────────


def dynamic_requirement(
    zone: int | None,
    height: float | None,
    irregular: bool,
    vertical: bool,
    periods: dict[str, float | None] | None,
    tc: float | None,
    dynamic_used: bool,
) -> dict[str, Any] | None:
    """Whether the code pack asks for dynamic analysis (``seismic.dynamicAnalysis``):
    ``{"required", "recommended", "limit" [m], "height", "zone", "reasons": [text], "used",
    "ok", "clause"}``; ``ok`` False when it is required and the design uses the static cases.
    None when the pack does not cover it."""
    rule = getattr(_seismic(), "dynamicAnalysis", None)
    if rule is None:
        return None
    code = _code()
    reasons: list[str] = []
    limits = rule.irregularHeights if irregular else rule.regularHeights
    limit = limits.get(str(zone)) if zone is not None else None
    kind = "irregular" if irregular else "regular"
    if limit is not None and height is not None and height > limit + 1e-9:
        reasons.append(
            f"a {kind} building {height:.1f} m high, more than {limit:g} m in zone {zone} "
            f"({code} {rule.clause})"
        )
    static = []
    if rule.verticalIrregularity and vertical:
        static.append("the building has a vertical irregularity")
    if periods:
        caps = []
        if rule.periodTcFactor and tc:
            caps.append(rule.periodTcFactor * tc)
        if rule.periodMax:
            caps.append(rule.periodMax)
        cap = min(caps) if caps else None
        for axis, period in sorted(periods.items()):
            if cap is not None and period is not None and period >= cap - 1e-12:
                static.append(f"T{axis.lower()} = {period:.2f} s is not below {cap:.2f} s")
    if static:
        reasons.append(
            "the equivalent static method does not apply: "
            + "; ".join(static)
            + f" ({code} {rule.staticClause})"
        )
    recommended = (
        not reasons and irregular and zone is not None and str(zone) in rule.recommendedIrregular
    )
    required = bool(reasons)
    return {
        "required": required,
        "recommended": recommended,
        "limit": limit,
        "height": height,
        "zone": zone,
        "irregular": irregular,
        "reasons": reasons,
        "used": dynamic_used,
        "ok": dynamic_used or not required,
        "clause": f"{code} {rule.clause}",
    }


# ─────────────────────────────────────── the assessment ───────────────────────────────────────


def _finding(kind: str, where: str, value: str, limit: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "group": group(kind),
        "label": label(kind),
        "clause": clause(kind),
        "where": where,
        "value": value,
        "limit": limit,
        **extra,
    }


def assess(
    project: dict[str, Any] | None,
    out_dir: str | Path | None,
    building: Any,
    objects: Any,
    materials: Any,
    settings: Any,
    torsion_rows: list[dict[str, Any]] | None = None,
    periods: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    """The irregularities of the building and what follows from them:
    ``{"covered", "code", "storeys": [rows], "findings": [{"type", "group", "label", "clause",
    "where", "value", "limit", ...}], "types": [ids], "plan", "vertical", "irregular",
    "softStoreys": [{"name", "bottom", "top", "type", "direction"}], "dynamic"
    (:func:`dynamic_requirement`), "connections": {"applies", "factor", "types", "clause",
    "wings", "wingsClause", "category"}, "notes"}``.

    ``project`` and ``out_dir``: the analysis model and its results (the stiffness, mass and
    static torsion checks); without them those are left out. ``torsion_rows``: the response
    spectrum design's torsional irregularity rows (taken over the static ones)."""
    found = table()
    code = _code()
    empty: dict[str, Any] = {
        "covered": False,
        "code": code,
        "storeys": [],
        "findings": [],
        "types": [],
        "plan": False,
        "vertical": False,
        "irregular": False,
        "softStoreys": [],
        "dynamic": None,
        "connections": None,
        "notes": [],
    }
    if found is None or building is None:
        if found is None:
            empty["notes"].append(
                f"building irregularities are not covered by the code pack {code}"
            )
        return empty
    from saengine.design import seismic_rules as sr
    from saengine.fem.seismic_design import design_uses_spectrum

    notes: list[str] = []
    findings: list[dict[str, Any]] = []
    types = {o.id: o for o in getattr(objects, "objects", [])} if objects is not None else {}
    storeys = storeys_of(building)
    levels = [storeys[0].bottom, *(s.top for s in storeys)] if storeys else []

    def where(k: int) -> str:
        s = storeys[k]
        return f"{s.name} ({s.bottom:g} to {s.top:g} m)"

    # ── analysis values ──
    results: dict[str, tuple[dict, Any]] = {}
    if project is not None and out_dir is not None and levels:
        try:
            results = _static_results(out_dir, {"EX", "EY", "EXP", "EXN", "EYP", "EYN"})
        except Exception as error:  # noqa: BLE001 - the geometry checks go on without them
            notes.append(f"the static earthquake results could not be read: {error}")
    stiffness = storey_stiffness(project, results, levels) if results else {}
    weights = storey_weights(project, levels)[1:] if project is not None and levels else []
    widths = storey_widths(building, storeys)
    strengths = storey_strengths(building, objects, materials, storeys)

    rows = []
    for k, s in enumerate(storeys):
        rows.append(
            {
                "name": s.name,
                "bottom": s.bottom,
                "top": s.top,
                "stiffnessX": (stiffness.get("X") or [None] * len(storeys))[k],
                "stiffnessY": (stiffness.get("Y") or [None] * len(storeys))[k],
                "weight": weights[k] if weights else None,
                "widthX": widths[k]["X"],
                "widthY": widths[k]["Y"],
                "strengthX": strengths[k]["X"],
                "strengthY": strengths[k]["Y"],
            }
        )

    # ── soft storey (stiffness) ──
    soft_storeys: list[dict[str, Any]] = []
    if found.soft is not None and stiffness:
        for axis, values in stiffness.items():
            for k, check in enumerate(ratio_checks(values, found.soft, found.extremeSoft)):
                rows[k][f"soft{axis}"] = check
                if not check["irregular"]:
                    continue
                kind = "extremeSoft" if check["extreme"] else "soft"
                rule = found.extremeSoft if check["extreme"] else found.soft
                findings.append(
                    _finding(
                        kind,
                        where(k),
                        _ratio_text(check),
                        _rule_text(rule),
                        direction=axis,
                        storey=storeys[k].name,
                    )
                )
                soft_storeys.append(
                    {
                        "name": storeys[k].name,
                        "bottom": storeys[k].bottom,
                        "top": storeys[k].top,
                        "type": kind,
                        "direction": axis,
                    }
                )
    elif found.soft is not None:
        notes.append(
            "soft storey: not checked without the static earthquake results (EX, EY): run the "
            "analysis"
        )
    # ── weak storey (strength) ──
    if found.weak is not None:
        for axis in ("X", "Y"):
            values = [s[axis] for s in strengths]
            if not any(values):
                continue
            for k, check in enumerate(ratio_checks(values, found.weak, found.extremeWeak)):
                rows[k][f"weak{axis}"] = check
                if check["irregular"]:
                    kind = "extremeWeak" if check["extreme"] else "weak"
                    rule = found.extremeWeak if check["extreme"] else found.weak
                    findings.append(
                        _finding(
                            kind,
                            where(k),
                            _ratio_text(check),
                            _rule_text(rule),
                            direction=axis,
                            storey=storeys[k].name,
                        )
                    )
        if found.strength is not None:
            notes.append(
                "weak storey: the storey strength is estimated by the nominal shear strength of "
                f"its concrete columns and structural walls ({clause('strength')}); their "
                "flexural strength can govern and is not counted"
            )
    # ── mass ──
    if found.mass is not None and weights and any(weights):
        for k, check in enumerate(adjacent_checks(list(weights), found.mass)):
            rows[k]["massRatio"] = check["ratio"]
            if check["irregular"]:
                findings.append(
                    _finding(
                        "mass",
                        where(k),
                        f"{check['ratio']:.2f} × an adjacent floor",
                        f"{found.mass.adjacent:g} ×",
                        storey=storeys[k].name,
                    )
                )
    # ── vertical geometry ──
    if found.geometry is not None:
        for axis in ("X", "Y"):
            values = [w[axis] for w in widths]
            for k, check in enumerate(adjacent_checks(values, found.geometry)):
                if check["irregular"]:
                    findings.append(
                        _finding(
                            "geometry",
                            where(k),
                            f"{check['ratio']:.2f} × an adjacent storey",
                            f"{found.geometry.adjacent:g} ×",
                            direction=axis,
                            storey=storeys[k].name,
                        )
                    )
    # ── offsets: plan type IV, vertical type IV ──
    if found.offsets:
        try:
            for item in offsets(building, objects, materials):
                if item["type"] == "inPlaneDiscontinuity":
                    value = (
                        f"offset {item['offset'] / 1e3:.2f} m, length {item['length'] / 1e3:.2f} m"
                    )
                    limit = f"offset ≤ {found.inPlaneOffset:g} × length"
                else:
                    value = f"{item['kind']} stops at {item['elevation']:g} m"
                    limit = "continuous to the base"
                findings.append(
                    _finding(
                        item["type"],
                        f"{item['kind']} {item['id']}",
                        value,
                        limit,
                        element=item["id"],
                    )
                )
        except (ValueError, KeyError, AttributeError, TypeError) as error:
            notes.append(f"the offsets of the vertical elements could not be checked: {error}")
    # ── plan: floors ──
    floors = _floors(building, types)
    by_level = {round(s.top, 3): k for k, s in enumerate(storeys)}
    stiff_values: list[float | None] = [None] * len(storeys)
    for z, (floor, stiff) in sorted(floors.items()):
        k = by_level.get(round(z, 3))
        name = storeys[k].name if k is not None else f"{z:g} m"
        if k is not None:
            stiff_values[k] = stiff or None
        if found.reentrantProjection is not None:
            corners = [c for c in reentrant_corners(floor, found.reentrantProjection)]
            worst = max(corners, key=lambda c: min(c["shareX"], c["shareY"]), default=None)
            if worst is not None and worst["irregular"]:
                findings.append(
                    _finding(
                        "reentrantCorner",
                        f"floor {name}, corner at ({worst['x'] / 1e3:.2f}, {worst['y'] / 1e3:.2f}) m",
                        f"projections {100 * worst['shareX']:.0f} % and "
                        f"{100 * worst['shareY']:.0f} % of the plan",
                        f"both > {100 * found.reentrantProjection:g} %",
                        storey=name,
                    )
                )
        if found.openingShare is not None:
            open_area, gross = opening_share(floor)
            if gross > 0 and open_area > found.openingShare * gross:
                findings.append(
                    _finding(
                        "diaphragmDiscontinuity",
                        f"floor {name}",
                        f"openings {100 * open_area / gross:.0f} % of the gross area",
                        f"≤ {100 * found.openingShare:g} %",
                        storey=name,
                    )
                )
    if found.diaphragmStiffnessChange is not None:
        change = found.diaphragmStiffnessChange
        for k in range(len(storeys) - 1):
            a, b = stiff_values[k], stiff_values[k + 1]
            if not a or not b:
                continue
            drop = 1 - min(a, b) / max(a, b)
            if drop > change + 1e-12:
                findings.append(
                    _finding(
                        "diaphragmDiscontinuity",
                        f"floors {storeys[k].name} and {storeys[k + 1].name}",
                        f"diaphragm stiffness (area × thickness) changes {100 * drop:.0f} %",
                        f"≤ {100 * change:g} %",
                        storey=storeys[k + 1].name,
                    )
                )
    # ── non-parallel systems ──
    if found.nonparallelTolerance is not None:
        lines = _lateral_lines(building, types, materials)
        major, off = nonparallel_elements(lines, found.nonparallelTolerance)
        for item in off:
            findings.append(
                _finding(
                    "nonparallel",
                    f"{item['id']}",
                    f"{item['deviation']:.1f}° off the major axes ({major:g}°)",
                    f"≤ {found.nonparallelTolerance:g}°",
                    element=item["id"],
                )
            )
    # ── torsion ──
    torsion_source = "response spectrum"
    if torsion_rows is None and results and project is not None:
        torsion_rows = static_torsion(project, results, levels)
        torsion_source = "static"
        if torsion_rows and not any(
            c.endswith(("P", "N")) for r in torsion_rows for c in r["cases"]
        ):
            notes.append(
                "torsional irregularity from EX, EY without the accidental torsion: add the "
                "eccentric static cases (Analysis model) or use the response spectrum design"
            )
    for r in torsion_rows or []:
        if r.get("irregular"):
            kind = "extremeTorsion" if r.get("extreme") else "torsion"
            findings.append(
                _finding(
                    kind,
                    f"storey {r['bottom']:g} to {r['top']:g} m",
                    f"Δmax / Δavg = {r['ratio']:.2f} ({torsion_source})",
                    f"≤ {_seismic().torsionExtreme if kind == 'extremeTorsion' else _seismic().torsionIrregular:g}",
                    direction=r["direction"],
                )
            )

    # ── declared soft storeys ──
    declared = list(getattr(getattr(settings, "seismic", None), "softStoreys", []) or [])
    for name in declared:
        match = next((s for s in storeys if s.name == name), None)
        if match is None:
            notes.append(f"soft storey '{name}' (settings): no storey of that name")
            continue
        if not any(s["name"] == name for s in soft_storeys):
            soft_storeys.append(
                {
                    "name": name,
                    "bottom": match.bottom,
                    "top": match.top,
                    "type": "declared",
                    "direction": None,
                }
            )

    kinds = sorted({f["type"] for f in findings})
    plan = any(group(t) == "plan" for t in kinds)
    vertical = any(group(t) == "vertical" for t in kinds) or bool(soft_storeys)

    # ── dynamic analysis ──
    try:
        category, zone = sr.seismic_design_category(settings)
    except (ValueError, KeyError, AttributeError, TypeError):
        category, zone = None, None
    height = sr.building_height(building)
    tc = None
    try:
        site = _seismic().siteClasses.get(settings.site.siteClass)
        tc = float(site.TC) if site is not None else None
    except AttributeError:
        tc = None
    dynamic = dynamic_requirement(
        zone,
        height,
        plan or vertical,
        vertical,
        periods,
        tc,
        bool(settings is not None and design_uses_spectrum(settings)),
    )
    if dynamic is not None and dynamic["required"] and not dynamic["used"]:
        notes.append(
            "dynamic analysis is required: "
            + "; ".join(dynamic["reasons"])
            + ". Choose the response spectrum design (Project Settings, Analysis model)"
        )
    elif dynamic is not None and dynamic["recommended"] and not dynamic["used"]:
        notes.append(
            f"dynamic analysis is recommended for this irregular building ({dynamic['clause']})"
        )

    # ── diaphragm connections ──
    rule = getattr(_seismic(), "diaphragmConnections", None)
    connections = None
    if rule is not None:
        triggered = sorted(set(kinds) & set(rule.types))
        applies = bool(category in rule.categories and triggered)
        wings = sorted(set(kinds) & set(rule.wingTypes))
        try:
            increase = float(code_context.pack_table("transfer").diaphragm.irregularIncrease)
        except (AttributeError, KeyError, LookupError):
            increase = 1.0
        connections = {
            "applies": applies,
            "factor": increase if applies else 1.0,
            "types": triggered,
            "category": category,
            "clause": f"{code} {rule.clause}",
            "wings": bool(wings),
            "wingsExempt": bool(
                wings and rule.wingsDynamicExempt and dynamic is not None and dynamic["used"]
            ),
            "wingsClause": f"{code} {rule.wingsClause}",
        }
    # ── soft storey design ──
    design = getattr(_seismic(), "softStorey", None)
    method = getattr(getattr(settings, "seismic", None), "softStoreyDesign", "factors")
    if soft_storeys and design is not None:
        names = ", ".join(sorted({s["name"] for s in soft_storeys}))
        if method == "dynamicInfill":
            notes.append(
                f"soft storey {names}: designed by a dynamic analysis with the infill walls done "
                f"outside SAEngine (settings); the factors of {code} {design.clause} are not "
                "applied"
            )
        else:
            notes.append(
                f"soft storey {names}: its columns and beams take {design.frameFactor:g} × and "
                f"its structural walls {design.wallFactor:g} × the earthquake forces "
                f"({code} {design.clause})"
            )
    return {
        "covered": True,
        "code": code,
        "category": category,
        "storeys": rows,
        "findings": findings,
        "types": kinds,
        "plan": plan,
        "vertical": vertical,
        "irregular": plan or vertical,
        "softStoreys": soft_storeys,
        "softStoreyDesign": method,
        "dynamic": dynamic,
        "connections": connections,
        "notes": notes,
        "clauses": {"plan": clause("plan"), "vertical": clause("vertical")},
    }


def _ratio_text(check: dict[str, Any]) -> str:
    parts = []
    if check.get("toAbove") is not None:
        parts.append(f"{100 * check['toAbove']:.0f} % of the storey above")
    if check.get("toThreeAbove") is not None:
        parts.append(f"{100 * check['toThreeAbove']:.0f} % of the three above")
    return ", ".join(parts)


def _rule_text(rule: Any) -> str:
    parts = []
    if rule.storeyAbove:
        parts.append(f"≥ {100 * rule.storeyAbove:g} % of the storey above")
    if rule.threeAbove:
        parts.append(f"≥ {100 * rule.threeAbove:g} % of the three above")
    return ", ".join(parts)


def _lateral_lines(building: Any, types: dict[str, Any], materials: Any) -> list[tuple]:
    """The plan lines of the lateral system: structural walls and frame beams (both ends on a
    column)."""
    from saengine.design import seismic_rules as sr

    by_material = {m.id: m for m in getattr(materials, "materials", [])} if materials else {}
    elements = list(getattr(building, "elements", []))
    columns = [e for e in elements if getattr(e, "kind", "") == "column"]
    lines = []
    for e in elements:
        kind = getattr(e, "kind", "")
        if kind == "wall" and sr._structural_wall(e, types, by_material):
            lines.append((e.id, e.start, e.end))
        elif kind == "beam":
            z = float(e.elevation)
            ends = [
                any(
                    sr._near(c.position, p)
                    and float(c.bottom) - TOLERANCE <= z
                    and z <= float(c.top) + TOLERANCE
                    for c in columns
                )
                for p in (e.start, e.end)
            ]
            if all(ends):
                lines.append((e.id, e.start, e.end))
    return lines


# ─────────────────────────────────────── soft storey members ───────────────────────────────────────


def soft_storey_members(assessment: dict[str, Any], building: Any, objects: Any) -> dict:
    """The members of the soft storeys and the pack's factors: ``{"frames": column and beam
    ids (the storey's columns, the beams at its ceiling), "walls": structural wall ids,
    "frameFactor", "wallFactor", "clause", "storeys": names}``; empty sets when there is none,
    the pack has no soft storey design or the settings say the design was done otherwise."""
    design = getattr(_seismic(), "softStorey", None)
    out: dict[str, Any] = {"frames": set(), "walls": set(), "storeys": []}
    if (
        design is None
        or not assessment.get("softStoreys")
        or assessment.get("softStoreyDesign") == "dynamicInfill"
    ):
        return out
    wanted = set(design.types) | {"declared"}
    storeys = {
        s["name"]: Storey(s["name"], s["bottom"], s["top"])
        for s in assessment["softStoreys"]
        if s["type"] in wanted
    }
    types = {o.id: o for o in getattr(objects, "objects", [])} if objects is not None else {}
    for storey in storeys.values():
        for e in getattr(building, "elements", []):
            kind = getattr(e, "kind", "")
            column = kind == "column" and _in_storey(float(e.bottom), float(e.top), storey)
            # The beams at the soft storey's ceiling frame its columns.
            beam = kind == "beam" and abs(float(e.elevation) - storey.top * 1e3) <= TOLERANCE
            if column or beam:
                out["frames"].add(e.id)
            elif (
                kind == "wall"
                and getattr(types.get(e.type), "structural", True)
                and _in_storey(float(e.bottom), float(e.top), storey)
            ):
                out["walls"].add(e.id)
    out.update(
        frameFactor=float(design.frameFactor),
        wallFactor=float(design.wallFactor),
        clause=f"{_code()} {design.clause}",
        storeys=sorted(storeys),
    )
    return out


def soft_storey_combinations(combinations: list[Any], factor: float, prefix: str) -> list[dict]:
    """The earthquake combinations (those with EX or EY) with the earthquake factors times
    ``factor``, named ``"<prefix><name>"``: :class:`saengine.library.settings.LoadCombination`
    dicts."""
    out = []
    for c in combinations:
        if not (c.EX or c.EY):
            continue
        data = c.model_dump()
        data.update(
            name=f"{prefix}{c.name}",
            EX=round(c.EX * factor, 4),
            EY=round(c.EY * factor, 4),
        )
        out.append(data)
    return out


def soft_storey_rs_combinations(
    rs_combinations: list[dict[str, Any]], factor: float, prefix: str
) -> list[dict[str, Any]]:
    """The response spectrum design combinations with their envelope factors (the earthquake
    parts) times ``factor``, named ``"<prefix><name>"``."""
    return [
        {
            **c,
            "name": f"{prefix}{c['name']}",
            "envelope": {k: round(float(v) * factor, 4) for k, v in c.get("envelope", {}).items()},
        }
        for c in rs_combinations
    ]


def frame_prefix(factor: float) -> str:
    return f"Soft storey ×{factor:g}: "


def wall_prefix(factor: float) -> str:
    return f"Soft storey walls ×{factor:g}: "


# ─────────────────────────────────────── from the project files ───────────────────────────────────────


_memo_lock = threading.Lock()
_memo: dict[str, tuple[str, dict[str, Any]]] = {}


def _stamp(*parts: Any) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(repr(part).encode("utf-8"))
    return digest.hexdigest()


def assess_cached(
    project: dict[str, Any] | None,
    out_dir: str | Path | None,
    building: Any,
    objects: Any,
    materials: Any,
    settings: Any,
    torsion_rows: list[dict[str, Any]] | None = None,
    periods: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    """:func:`assess`, kept while its inputs (the run's manifest, the model, the building and
    the settings) stay the same: the design, the diaphragms and the report ask for it in turn."""
    manifest = None
    if out_dir is not None:
        try:
            manifest = (Path(out_dir) / "manifest.json").stat().st_mtime_ns
        except OSError:
            manifest = None
    key = str(Path(out_dir).resolve()) if out_dir is not None else "-"

    def dump(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "model_dump_json"):
            return value.model_dump_json()
        return json.dumps(value, sort_keys=True, default=str)

    # The analysis model counts only with its results (stamped by the manifest): its size
    # stands in for it, as dumping a tall building's model each time costs seconds.
    model = (
        (len(project.get("nodes", [])), len(project.get("elements", [])))
        if project is not None
        else None
    )
    stamp = _stamp(
        manifest,
        model,
        hashlib.sha1(dump(building).encode()).hexdigest(),
        hashlib.sha1(dump(objects).encode()).hexdigest(),
        hashlib.sha1(dump(materials).encode()).hexdigest(),
        dump(settings),
        json.dumps(torsion_rows, sort_keys=True, default=str),
        json.dumps(periods, sort_keys=True, default=str),
        code_context.current().id,
    )
    with _memo_lock:
        found = _memo.get(key)
    if found is not None and found[0] == stamp:
        return found[1]
    result = assess(project, out_dir, building, objects, materials, settings, torsion_rows, periods)
    with _memo_lock:
        _memo.clear()
        _memo[key] = (stamp, result)
    return result


def assessment_of(
    out_dir: str | Path,
    project_path: str | Path,
    settings: Any = None,
    torsion_rows: list[dict[str, Any]] | None = None,
) -> dict:
    """:func:`assess_cached` of the SAEngine project the analysis model ``project_path`` belongs
    to (two folders up), with ``torsion_rows`` or else the response spectrum design's torsion
    rows when it has a summary, and the periods the base shear used."""
    from saengine.fem import seismic_design as rs
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings

    root = Path(project_path).resolve().parent.parent

    def read(relative: str) -> str:
        return (root / relative).read_text(encoding="utf-8")

    if settings is None:
        settings = ProjectSettings.model_validate_json(
            read("02 Project Settings/project-settings.json")
        )
    building = BuildingModel.model_validate_json(read("06 BIM/bim.json"))
    objects = ObjectLibrary.model_validate_json(read("04 Objects/objects.json"))
    materials = MaterialLibrary.model_validate_json(read("03 Materials/materials.json"))
    project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    if torsion_rows is None and rs.design_uses_spectrum(settings):
        summary = rs.load_summary(out_dir)
        if summary and summary.get("available") and summary.get("torsionalIrregularity"):
            torsion_rows = summary["torsionalIrregularity"]
    periods = None
    try:
        from saengine.fem.serviceability import base_shear_periods
        from saengine.fem.story_response import _derivation_summary

        periods = base_shear_periods(_derivation_summary(project, project_path))
        if not any(v is not None for v in periods.values()):
            periods = None
    except Exception:  # noqa: BLE001 - without the periods, the height rule only
        periods = None
    return assess_cached(
        project, out_dir, building, objects, materials, settings, torsion_rows, periods
    )


# ─────────────────────────────────────── report rows ───────────────────────────────────────


def finding_rows(assessment: dict[str, Any]) -> list[list[str]]:
    """``[type label, where, direction, value, limit, clause]`` per finding."""
    return [
        [
            f["label"],
            f["where"],
            f.get("direction") or "–",
            f["value"],
            f["limit"],
            f["clause"],
        ]
        for f in assessment.get("findings", [])
    ]


def storey_rows(assessment: dict[str, Any]) -> list[list[str]]:
    """Per storey (top down) ``[storey, kX [kN/mm], kY, kX/k above [%], kY/k above, W [kN],
    VnX [kN], VnY [kN]]``."""

    def kn_mm(v: float | None) -> str:
        return f"{v / 1e6:.1f}" if v else "–"

    def kn(v: float | None) -> str:
        return f"{v / 1e3:.0f}" if v else "–"

    def pct(check: dict[str, Any] | None) -> str:
        value = (check or {}).get("toAbove")
        return f"{100 * value:.0f}" if value is not None else "–"

    out = []
    for r in reversed(assessment.get("storeys", [])):
        out.append(
            [
                r["name"],
                kn_mm(r.get("stiffnessX")),
                kn_mm(r.get("stiffnessY")),
                pct(r.get("softX")),
                pct(r.get("softY")),
                kn(r.get("weight")),
                kn(r.get("strengthX")),
                kn(r.get("strengthY")),
            ]
        )
    return out

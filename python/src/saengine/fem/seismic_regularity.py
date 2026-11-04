"""Structural regularity in plan and in elevation by criteria, and what follows from it (method
``criteria`` of the pack's ``seismic.regularity``; alpha 9 C5c, EN 1998-1 4.2.3 type).

From the building model (``06 BIM/bim.json``), before the analysis, so that its consequence on
the behaviour factor reaches the design spectrum of the same run:

- **Plan** (:func:`plan_rows`), per floor: the slenderness λ = Lmax / Lmin of its extent; the
  compactness, the area between its outline and the convex envelope over the floor's area;
  per storey the centre of stiffness from the moments of inertia of the columns' and walls'
  sections (a column's I about each axis, a wall's in-plane I along its direction), the
  torsional radii rx = √(KT / Ky), ry = √(KT / Kx), the eccentricities e0 of the floor's
  centroid (the centre of mass of a uniform floor: SAEngine practice) and the radius of
  gyration ls of the floor's area; regular when e0 <= share × r and r >= ls both ways.
- **Elevation** (:func:`elevation_rows`): the columns and walls that do not continue to the base
  (:func:`saengine.fem.irregularity.offsets`) and the setbacks of the storeys' plan extent in
  each direction (symmetric each at most the share of the dimension below; a single one in the
  lower part of the height at most its larger share; unsymmetric each and together at most
  theirs of the base dimension). The mass and stiffness changes of the storeys are the
  analysis's (:func:`saengine.fem.irregularity.assess`, the pack's ``irregularities``).
- **Consequences** (:func:`apply_to_values`): q × the pack's factor when not regular in elevation;
  αu/α1 averaged with 1 when not regular in plan (q × (1 + αu/α1) / (2 αu/α1), the system's
  Ω0 standing for αu/α1); the lateral force method only for a structure regular in elevation
  (the pack's ``dynamicAnalysis``); the spatial model always (a planar one would need regularity
  in plan). A project's own R (q) is used as given.

Units: the building in mm; the rows in m where they say so.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from saengine.codes import context as code_context


def rules() -> Any | None:
    found = getattr(code_context.table("seismic"), "regularity", None)
    return found if found is not None and found.method == "criteria" else None


def _clause(key: str) -> str:
    r = rules()
    return (r.clauses.get(key) if r is not None else "") or ""


def _second_moments(polygon: Any) -> tuple[float, float, float, float]:
    """(area, centroid x, y, polar moment about the centroid) of a shapely polygon [mm]."""
    pts = list(polygon.exterior.coords)
    a = cx = cy = ixx = iyy = 0.0
    for (x0, y0), (x1, y1) in itertools.pairwise(pts):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
        ixx += (y0 * y0 + y0 * y1 + y1 * y1) * cross
        iyy += (x0 * x0 + x0 * x1 + x1 * x1) * cross
    a /= 2
    if abs(a) < 1e-9:
        return 0.0, 0.0, 0.0, 0.0
    cx /= 6 * a
    cy /= 6 * a
    ixx = ixx / 12 - a * cy * cy
    iyy = iyy / 12 - a * cx * cx
    return abs(a), cx, cy, abs(ixx + iyy)


def _stiffness(building: Any, types: dict[str, Any], storey: Any) -> list[tuple]:
    """(x, y, kx, ky) of the columns and walls of ``storey``: kx the moment of inertia
    resisting a sway along X [mm⁴], ky along Y."""
    from saengine.fem.irregularity import _in_storey

    out = []
    for e in getattr(building, "elements", []):
        kind = getattr(e, "kind", "")
        if kind not in ("column", "wall") or not _in_storey(float(e.bottom), float(e.top), storey):
            continue
        t = types.get(e.type)
        if kind == "column":
            profile = getattr(t, "profile", None)
            if profile is None:
                continue
            if getattr(profile, "shape", "") == "circle":
                r = float(profile.radius)
                i = math.pi * r**4 / 4
                kx = ky = i
            else:
                bx, by = (
                    float(getattr(profile, "xDim", 0) or 0),
                    float(getattr(profile, "yDim", 0) or 0),
                )
                if bx <= 0 or by <= 0:
                    continue
                ix_along = by * bx**3 / 12  # sway along the profile's x
                iy_along = bx * by**3 / 12
                turned = round((float(getattr(e, "rotation", 0) or 0) % 180.0) / 90.0) % 2 == 1
                kx, ky = (iy_along, ix_along) if turned else (ix_along, iy_along)
            out.append((float(e.position[0]), float(e.position[1]), kx, ky))
        else:
            thickness = float(getattr(t, "thickness", 0) or 0)
            dx, dy = float(e.end[0]) - float(e.start[0]), float(e.end[1]) - float(e.start[1])
            length = math.hypot(dx, dy)
            if thickness <= 0 or length <= 0:
                continue
            i = thickness * length**3 / 12
            c, s = dx / length, dy / length
            mid = (
                (float(e.start[0]) + float(e.end[0])) / 2,
                (float(e.start[1]) + float(e.end[1])) / 2,
            )
            out.append((mid[0], mid[1], i * c * c, i * s * s))
    return out


def plan_rows(building: Any, objects: Any) -> list[dict[str, Any]]:
    """The plan criteria per floor and storey (see the module notes): ``{"storey", "check",
    "value", "limit", "ok", "clause"}``."""
    from saengine.fem import irregularity as ir

    r = rules()
    types = {o.id: o for o in getattr(objects, "objects", [])} if objects is not None else {}
    floors = ir._floors(building, types)
    storeys = ir.storeys_of(building)
    rows: list[dict[str, Any]] = []
    for storey in storeys:
        found = floors.get(round(storey.top, 3))
        if found is None:
            continue
        floor = found[0]
        parts = ir._polygons(floor)
        main = max(parts, key=lambda p: p.area)
        x0, y0, x1, y1 = floor.bounds
        lmax, lmin = max(x1 - x0, y1 - y0), min(x1 - x0, y1 - y0)
        if lmin > 0:
            lam = lmax / lmin
            rows.append(_entry(storey.name, "slenderness", "λ = Lmax/Lmin", lam,
                               r.slendernessMax, lam <= r.slendernessMax))  # fmt: skip
        hull = floor.convex_hull.area
        if floor.area > 0:
            share = (hull - floor.area) / floor.area
            rows.append(_entry(storey.name, "compactness", "convex envelope area over the floor's",
                               share, r.compactnessShare, share <= r.compactnessShare))  # fmt: skip
        if not r.torsionalRadius:
            continue
        elements = _stiffness(building, types, storey)
        kx = sum(k[2] for k in elements)
        ky = sum(k[3] for k in elements)
        if kx <= 0 or ky <= 0:
            continue
        xr = sum(k[0] * k[3] for k in elements) / ky
        yr = sum(k[1] * k[2] for k in elements) / kx
        kt = sum(k[2] * (k[1] - yr) ** 2 + k[3] * (k[0] - xr) ** 2 for k in elements)
        area, cx, cy, polar = _second_moments(main)
        if area <= 0:
            continue
        ls = math.sqrt(polar / area)
        rx, ry = math.sqrt(kt / ky), math.sqrt(kt / kx)
        e0x, e0y = abs(cx - xr), abs(cy - yr)
        for axis, e0, radius in (("x", e0x, rx), ("y", e0y, ry)):
            rows.append(_entry(storey.name, "eccentricity", f"e0{axis} / r{axis}", e0 / radius,
                               r.eccentricityShare, e0 <= r.eccentricityShare * radius,
                               extra=f"e0{axis} = {e0 / 1e3:.2f} m, r{axis} = {radius / 1e3:.2f} m"))  # fmt: skip
            rows.append(_entry(storey.name, "torsionalRadius", f"r{axis} / ls", radius / ls, 1.0,
                               radius >= ls, extra=f"ls = {ls / 1e3:.2f} m", least=True))  # fmt: skip
    return rows


def _entry(storey: str, check: str, what: str, value: float, limit: float, ok: bool,
           extra: str = "", least: bool = False) -> dict[str, Any]:  # fmt: skip
    return {"storey": storey, "check": check, "what": what, "value": round(value, 4),
            "limit": limit, "ok": bool(ok), "least": least, "note": extra,
            "group": "elevation" if check in ("setback", "continuity") else "plan"}  # fmt: skip


def elevation_rows(building: Any, objects: Any, materials: Any) -> list[dict[str, Any]]:
    """The elevation criteria (see the module notes)."""
    from saengine.fem import irregularity as ir

    r = rules()
    rows: list[dict[str, Any]] = []
    try:
        offsets = ir.offsets(building, objects, materials)
    except (AttributeError, KeyError, TypeError, ValueError):
        offsets = []
    for item in offsets:
        rows.append(_entry(f"{item['elevation']:.2f} m", "continuity",
                           f"{item['kind']} {item['id']} stops above the base", 1.0, 0.0, False))  # fmt: skip
    storeys = ir.storeys_of(building)
    if len(storeys) < 2:
        return rows
    total = storeys[-1].top - storeys[0].bottom
    for axis in (0, 1):
        name = "XY"[axis]
        extents = []
        for storey in storeys:
            values = []
            for e in getattr(building, "elements", []):
                kind = getattr(e, "kind", "")
                if kind not in ("column", "wall") or not ir._in_storey(
                    float(e.bottom), float(e.top), storey
                ):
                    continue
                points = [e.position] if kind == "column" else [e.start, e.end]
                values += [float(p[axis]) for p in points]
            extents.append((min(values), max(values)) if values else None)
        base = extents[0]
        if base is None or base[1] - base[0] <= 0:
            continue
        unsymmetric = 0.0
        for k in range(1, len(storeys)):
            below, here = extents[k - 1], extents[k]
            if below is None or here is None:
                continue
            width = below[1] - below[0]
            left, right = max(here[0] - below[0], 0.0), max(below[1] - here[1], 0.0)
            setback = left + right
            if width <= 0 or setback <= 1.0:
                continue
            symmetric = abs(left - right) <= r.symmetryTolerance * setback
            low = storeys[k].bottom - storeys[0].bottom <= r.baseHeightShare * total
            if symmetric:
                limit = r.baseSetbackShare if low else r.setbackShare
                share = setback / width
            else:
                limit = r.unsymmetricShare
                share = setback / (base[1] - base[0])
                unsymmetric += share
            rows.append(_entry(storeys[k].name, "setback",
                               f"{'symmetric' if symmetric else 'unsymmetric'} setback in {name}",
                               share, limit, share <= limit))  # fmt: skip
        if unsymmetric > 0:
            rows.append(_entry("all", "setback", f"unsymmetric setbacks in {name} together",
                               unsymmetric, r.unsymmetricTotal, unsymmetric <= r.unsymmetricTotal))  # fmt: skip
    return rows


def pre_analysis(building: Any, objects: Any, materials: Any) -> dict[str, Any] | None:
    """The regularity of the building before the analysis: ``{"plan", "elevation" (bools),
    "rows", "notes"}``; None when the pack has no criteria or there is no building."""
    r = rules()
    if r is None or building is None:
        return None
    try:
        plan = plan_rows(building, objects)
    except (AttributeError, KeyError, TypeError, ValueError, ImportError) as error:
        plan = []
        problem = f"the plan regularity could not be checked: {error}"
    else:
        problem = ""
    elevation = elevation_rows(building, objects, materials)
    rows = plan + elevation
    out = {
        "plan": all(x["ok"] for x in plan),
        "elevation": all(x["ok"] for x in elevation),
        "rows": rows,
        "notes": [problem] if problem else [],
    }
    return out


def apply_to_values(values: dict[str, Any], found: dict[str, Any], settings: Any) -> dict[str, Any]:
    """``values`` (:func:`saengine.library.settings.derived`) with q (R, RX, RY) and qd (Cd)
    reduced by the consequences of ``found`` (see the module notes); a note in
    ``found["notes"]``."""
    r = rules()
    factor = 1.0
    why = []
    if not found["elevation"]:
        factor *= r.elevationFactor
        why.append(f"not regular in elevation: q × {r.elevationFactor:g} ({_clause('elevation')})")
    if not found["plan"] and r.planAverage:
        seismic = code_context.table("seismic")
        system = seismic.systems.get(getattr(settings.seismic, "system", ""), None)
        alpha = float(getattr(system, "Omega0", 1.0) or 1.0)
        if alpha > 1.0:
            share = (1 + alpha) / (2 * alpha)
            factor *= share
            why.append(f"not regular in plan: αu/α1 = (1 + {alpha:g})/2, q × {share:.3f} "
                       f"({_clause('plan')})")  # fmt: skip
    found["qFactor"] = factor
    if factor == 1.0:
        found["notes"].append(
            "regular in plan and in elevation by the pack's criteria "
            f"({_clause('plan')}; {_clause('elevation')}): q as given; the lateral force method "
            "and a planar model would be permitted (SAEngine analyses the spatial model)"
        )
        return values
    if getattr(settings.seismic, "r", None) is not None:
        found["notes"].append(
            "; ".join(why) + ": the project's own R (q) is used as given (no reduction)"
        )
        found["qFactor"] = 1.0
        return values
    out = dict(values)
    for key in ("R", "RX", "RY", "Cd", "CdX", "CdY"):
        if isinstance(out.get(key), (int, float)):
            out[key] = float(out[key]) * factor
    found["notes"].append(
        "; ".join(why) + f": q = {float(values['R']):g} × {factor:.3f} = {out['R']:.3f} (qd = q); "
        "the spatial model and, where the period or the regularity asks, the modal analysis"
    )
    return out


def report_rows(found: dict[str, Any] | None) -> list[list[str]]:
    """The design report's rows of the criteria."""
    if not found:
        return []
    rows = []
    for x in found.get("rows", []):
        sense = "at least" if x.get("least") else "at most"
        rows.append([
            f"{'Plan' if x['group'] == 'plan' else 'Elevation'}: {x['what']} ({x['storey']})",
            f"{x['value']:.3f}, {sense} {x['limit']:g}: {'regular' if x['ok'] else 'NOT regular'}"
            + (f"; {x['note']}" if x.get("note") else ""),
        ])  # fmt: skip
    return rows

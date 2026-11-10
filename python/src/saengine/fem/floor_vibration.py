"""Floor vibration from walking, per floor panel, from the analysis model (alpha 9 P7).

The method and every value are the code pack's ``floorVibration`` table
(:class:`saengine.codes.practice_tables.FloorVibrationTable`); a pack without it does not
check floor vibration. The default pack's BNBC 2020 asks that floors do not vibrate
uncomfortably under walking (Part 6 Sec 1.4.2(e), 10.12.5) by any rational method and gives
none: the methods are SAEngine practice there, and the results say so.

**The panel and its frequency** (from the analysis). Each slab of the building model analysed
as shells is a floor; its deflection under the weight that vibrates (the dead load D and the
superimposed dead load SD cases of the run, plus the live load case L scaled to the
occupancy's ``serviceLive`` over the slab's live load) is taken at every node of its shells,
relative to the mean of its supported nodes (nodes it shares with columns and walls). The
panel is at the node of the largest deflection Δ: its bay is bounded by the nearest supported
nodes on either side in X and in Y (the slab's extent where there are none). Then fn =
``frequencyConstant`` √(g/Δ) (one mode of the whole floor system; the analysis' stiffness
modifiers of the slabs are in Δ, on the safe side for cracked sections).

**The weight per area** w = the slab's self-weight + its superimposed dead load + the
occupancy's ``serviceLive``; the use of the slab's area load picks the occupancy (``areaUses``,
else ``defaultOccupancy``); a use the table marks unchecked (parking, storage) has no row.

**The method** by the floor: a slab with steel beams at its level inside it is a steel or
composite floor (``steelMethod``), otherwise concrete (``concreteMethod``):

- ``walkingAcceleration``: ap/g = P0 exp(-decay fn) / (β W), W = ``panelBays`` × w × the bay,
  against ao/g of the occupancy; below ``minimumFrequency`` the floor fails (too lively), above
  ``maximumFrequency`` it is a high-frequency floor, checked by the transient response factor
  where the pack has the ``responseFactor`` group;
- ``responseFactor``: R of the resonant (fn below ``highFrequency``) or transient response
  (:func:`response_factor`), against the occupancy's R. The modal mass is ``modalShare`` × the
  bay's mass × the effective bays the mode spreads over in X and Y (``spread``,
  :func:`continuous_bays` and :func:`effective_bays`: the bays continuous with the panel along
  its row of supports, limited by the slab's free edges, by shorter bays and by ``maxBays``); a
  single bay, or a pack without ``spread``, gives the one-bay mass.

β (ζ) is the damping of the pack's ``defaultFitOut``. Units: m, kN, kg, Hz.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

G = 9.81


def table() -> Any | None:
    pack = code_context.current()
    return pack.table("floorVibration") if pack.has("floorVibration") else None


# ─────────────────────────────── methods ───────────────────────────────


def natural_frequency(deflection: float, constant: float) -> float:
    """fn [Hz] of a floor deflecting ``deflection`` [m] under its own vibrating weight."""
    return constant * math.sqrt(G / deflection) if deflection > 0 else math.inf


def walking_acceleration(fn: float, weight: float, damping: float, rules: Any) -> float:
    """ap/g of a floor of frequency ``fn`` [Hz], effective weight ``weight`` [kN] and damping
    ratio ``damping`` (``walkingAcceleration``)."""
    return rules.force * math.exp(-rules.decay * fn) / (damping * weight)


def weighting(f: float) -> float:
    """The frequency weighting of vertical acceleration: 0.5√f below 4 Hz, 1 to 8 Hz, 8/f."""
    if f < 4:
        return 0.5 * math.sqrt(max(f, 1.0))
    return 1.0 if f <= 8 else 8 / f


def response_factor(fn: float, mass: float, span: float, damping: float, rules: Any) -> dict:
    """R of a floor of frequency ``fn`` [Hz], panel mass ``mass`` [kg] (the modal mass is
    ``modalShare`` of it) and walking ``span`` [m] (``responseFactor``): ``{"R", "kind",
    "harmonic", "fp"}``."""
    m = rules.modalShare * mass
    q = rules.walkerWeight
    lo, hi = rules.pace
    if fn < rules.highFrequency:
        best = {"R": 0.0, "kind": "resonant", "harmonic": 1, "fp": lo}
        for h, (a, b) in enumerate(rules.harmonics, start=1):
            fp = min(max(fn / h, lo), hi)
            r_h = max(a * (h * fp + b), 0.0)
            build = 1 - math.exp(-2 * math.pi * damping * span / rules.stepLength)
            # Off resonance the dynamic amplification of the harmonic h·fp.
            ratio = h * fp / fn
            amplification = 1 / math.sqrt((1 - ratio**2) ** 2 + (2 * damping * ratio) ** 2)
            peak = min(amplification, 1 / (2 * damping))
            a_rms = weighting(fn) * build * r_h * q * peak / (math.sqrt(2) * m)
            value = a_rms / rules.baseAcceleration
            if value > best["R"]:
                best = {"R": value, "kind": "resonant", "harmonic": h, "fp": fp}
        return best
    fp = hi
    impulse = (
        rules.impulse * fp**rules.impulsePace / fn**rules.impulseFrequency * q / rules.impulseWeight
    )
    v = impulse / m
    x = 4 * math.pi * damping * fn / fp
    # Re-walk 4 R4B-6: the rms over one footfall period 1/fp of v(t) = v e^(-2π ζ fn t)
    # sin(2π fn t): the mean of sin² is 1/2, so v_rms = v √((1 - e^-x) / (2x)) (as the resonant
    # response's a_rms = peak / √2); without the 1/2 every transient R was √2 too large.
    v_rms = v * math.sqrt((1 - math.exp(-x)) / (2 * x))
    a_rms = weighting(fn) * 2 * math.pi * fn * v_rms
    return {"R": a_rms / rules.baseAcceleration, "kind": "transient", "harmonic": 0, "fp": fp}


def effective_bays(counted: int, spread: Any) -> float:
    """The effective bays in one direction of ``counted`` continuous bays (the panel's own
    included) by the pack's ``responseFactor.spread``: 1 + ``adjacentShare`` × (min(counted,
    ``maxBays``) - 1); 1 without ``spread``."""
    if spread is None:
        return 1.0
    return 1.0 + spread.adjacentShare * (min(max(counted, 1), spread.maxBays) - 1)


def check_panel(
    method: str,
    fn: float,
    w: float,
    area: float,
    span: float,
    occupancy: Any,
    rules: Any,
    bays: tuple[int, int] = (1, 1),
) -> dict[str, Any]:
    """One panel: ``w`` kN/m², ``area`` m² of its bay, ``span`` m its longer side, ``bays`` the
    continuous bays its mode can spread over in X and Y (the panel's own included; the modal
    mass of ``responseFactor`` by its ``spread``). Returns ``{"value", "limit", "unit", "ok",
    "how"}``."""
    fit = rules.defaultFitOut
    if method == "walkingAcceleration":
        g = rules.walkingAcceleration
        if fn < g.minimumFrequency:
            return {"value": fn, "limit": g.minimumFrequency, "unit": "Hz", "ok": False,
                    "how": f"fn below {g.minimumFrequency:g} Hz: too low a floor"}  # fmt: skip
        if fn <= g.maximumFrequency or rules.responseFactor is None:
            if fn > g.maximumFrequency:
                return {"value": fn, "limit": g.maximumFrequency, "unit": "Hz", "ok": True,
                        "how": "a high-frequency floor: the walking method does not apply"}  # fmt: skip
            beta = g.damping[fit]
            weight = g.panelBays * w * area
            ap = walking_acceleration(fn, weight, beta, g)
            return {
                "value": 100 * ap,
                "limit": 100 * occupancy.accelerationLimit,
                "unit": "% g",
                "ok": ap <= occupancy.accelerationLimit,
                "how": f"ap/g = {g.force:g} exp(-{g.decay:g} fn) / (β W), β = {beta:g} ({fit}), "
                f"W = {weight:.0f} kN",
            }
        method = "responseFactor"
    g = rules.responseFactor
    zeta = g.damping[fit]
    spread = getattr(g, "spread", None)
    ex, ey = (effective_bays(n, spread) for n in bays)
    mass = w * 1e3 / G * area * ex * ey
    found = response_factor(fn, mass, span, zeta, g)
    how = (
        f"{found['kind']} R (harmonic {found['harmonic']}, fp {found['fp']:.2f} Hz)"
        if found["kind"] == "resonant"
        else f"transient R (fp {found['fp']:.2f} Hz)"
    )
    bay = w * 1e3 / G * area / 1e3
    over = (
        f" × {ex:.2f} × {ey:.2f} (effective bays of {bays[0]} × {bays[1]} continuous)"
        if ex * ey != 1
        else ""
    )
    return {
        "value": found["R"],
        "limit": occupancy.responseLimit,
        "unit": "R",
        "ok": found["R"] <= occupancy.responseLimit,
        "how": f"{how}, ζ = {zeta:g} ({fit}), M = {g.modalShare:g} × {bay:.1f} t{over}",
    }


# ─────────────────────────────── the model ───────────────────────────────


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _supported_nodes(project: dict[str, Any]) -> set[int]:
    """Nodes of columns (vertical frame elements) and walls (vertical shells)."""
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    out: set[int] = set()
    for e in project.get("elements", []):
        nodes = [n for n in e.get("nodes", []) if n in coords]
        if len(nodes) < 2:
            continue
        points = np.array([coords[n] for n in nodes])
        span = points.max(axis=0) - points.min(axis=0)
        if e.get("type") == "Shell":
            if span[2] > 0.5 * max(span[0], span[1], 1e-9):
                out.update(nodes)
        elif len(nodes) == 2 and span[2] > 0.9 * float(np.linalg.norm(span)):
            out.update(nodes)
    return out


def _bay(point: np.ndarray, supports: np.ndarray, extent: tuple[float, float]) -> tuple:
    """(lx, ly) [m] between the nearest supported nodes either side of ``point`` in X and Y."""
    out = []
    for axis in (0, 1):
        values = supports[:, axis] if len(supports) else np.array([])
        lo = values[values < point[axis] - 1e-3]
        hi = values[values > point[axis] + 1e-3]
        if len(lo) and len(hi):
            out.append(float(hi.min() - lo.max()))
        else:
            out.append(float(extent[axis]))
    return out[0], out[1]


def _lines(values: np.ndarray, tolerance: float = 1e-3) -> list[float]:
    """The distinct coordinates of ``values`` (within ``tolerance`` [m]), sorted."""
    out: list[float] = []
    for v in np.sort(values):
        if not out or v - out[-1] > tolerance:
            out.append(float(v))
    return out


def continuous_bays(point: np.ndarray, supports: np.ndarray, spread: Any) -> tuple[int, int]:
    """The bays continuous with the panel at ``point`` in X and Y (its own included): along
    each axis the support lines of the panel's row (the positions with supported nodes on both
    of the row's bounding lines across it) split the slab into bays; from the panel's bay outwards on
    either side a bay counts while its span is at least ``spread.minimumSpanRatio`` × the
    panel's; the slab's edge (no supports beyond: a free edge) ends the run. (1, 1) without
    ``spread`` or supports either side."""
    if spread is None or len(supports) == 0:
        return 1, 1
    out = []
    for axis in (0, 1):
        across = 1 - axis
        c = supports[:, across]
        lo = c[c < point[across] - 1e-3]
        hi = c[c > point[across] + 1e-3]
        lines = _lines(supports[:, axis])
        if len(lo) and len(hi):
            # A bay of the row has supports on both of the row's bounding lines.
            near = _lines(supports[np.abs(c - lo.max()) <= 1e-3][:, axis])
            far = _lines(supports[np.abs(c - hi.min()) <= 1e-3][:, axis])
            lines = [v for v in near if any(abs(v - u) <= 1e-3 for u in far)]
        spans = np.diff(lines)
        inside = [k for k in range(len(spans)) if lines[k] < point[axis] < lines[k + 1]]
        if not inside:
            out.append(1)
            continue
        k = inside[0]
        least = spread.minimumSpanRatio * spans[k]
        count = 1
        for step in (-1, 1):
            j = k + step
            while 0 <= j < len(spans) and spans[j] >= least - 1e-9:
                count += 1
                j += step
        out.append(count)
    return out[0], out[1]


def evaluate(
    project: dict[str, Any], project_path: str | Path, static: dict[str, Any]
) -> dict[str, Any]:
    """The floor vibration of every slab (see the module notes): ``{"available", "rows":
    [{"slab", "story", "occupancy", "method", "deflection" mm, "fn", "w", "bay", "value",
    "limit", "unit", "ok", "how"}], "notes", "clause", "sheet"}``; ``static``: the run's
    static results by case code (D, SD, L)."""
    from saengine.design import slab_systems
    from saengine.fem.display import _last
    from saengine.library.bim import BeamElement, BuildingModel, SlabElement
    from saengine.library.materials import Category, MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings, partition_case

    rules = table()
    if rules is None:
        name = code_context.code_name()
        return {"available": False, "reason": f"Not covered by the code pack {name}."}
    if "D" not in static:
        return {"available": False, "reason": "No dead load case in the run."}
    root = Path(project_path).resolve().parent.parent
    bim, objects_text, materials_text, settings_text = (
        _read(root, p)
        for p in (
            "06 BIM/bim.json",
            "04 Objects/objects.json",
            "03 Materials/materials.json",
            "02 Project Settings/project-settings.json",
        )
    )
    if not (bim and objects_text and materials_text and settings_text):
        return {"available": False, "reason": "The building model or its libraries are missing."}
    building = BuildingModel.model_validate_json(bim)
    types = {o.id: o for o in ObjectLibrary.model_validate_json(objects_text).objects}
    mats = {m.id: m for m in MaterialLibrary.model_validate_json(materials_text).materials}
    settings = ProjectSettings.model_validate_json(settings_text)
    area_loads = {a.id: a for a in settings.areaLoads}
    case = partition_case(settings)
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    shells: dict[str, set[int]] = {}
    for e in project.get("elements", []):
        if e.get("type") == "Shell":
            shells.setdefault((e.get("name") or "").split("#")[0], set()).update(e["nodes"])
    supported = _supported_nodes(project)

    def uz(code: str, node: int) -> float:
        found = static.get(code)
        return float(_last(found.node_disp, node, 6)[2]) if found is not None else 0.0

    stories = {round(float(s.elevation)): s.name for s in building.stories}
    top = max(stories, default=0)
    steel_beams = []
    # Alpha 9 P8: Is / It,dyn of each composite beam (the pack's compositeDynamicModulus).
    dynamic = getattr(rules, "compositeDynamicModulus", None)
    stiffening: dict[int, float] = {}
    for element in building.elements:
        if isinstance(element, BeamElement):
            t = types.get(element.type)
            m = mats.get(getattr(t, "material", None)) if t else None
            if m is not None and m.category == Category.STEEL:
                mid = (np.asarray(element.start[:2]) + np.asarray(element.end[:2])) / 2
                if dynamic is not None and getattr(t, "composite", None) is not None:
                    from saengine.design.steel import composite as composite_design

                    span = float(np.linalg.norm(np.subtract(element.end[:2], element.start[:2])))
                    factor = composite_design.dynamic_stiffening(t, mats, span / 1e3, dynamic)
                    if factor is not None:
                        stiffening[len(steel_beams)] = factor
                steel_beams.append((round(element.elevation), mid))
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    unmeshed: list[str] = []
    for element in building.elements:
        if not isinstance(element, SlabElement):
            continue
        nodes = shells.get(element.id)
        slab_type = types.get(element.type)
        if slab_type is None:
            continue
        roof = round(element.elevation) == top
        load_id = element.areaLoad or (settings.roofLoad if roof else settings.floorLoad)
        load = area_loads.get(load_id)
        occupancy_id = rules.areaUses.get(getattr(load, "use", ""), rules.defaultOccupancy)
        if roof and not element.areaLoad:
            occupancy_id = rules.areaUses.get("roof", occupancy_id)
        occupancy = rules.occupancies[occupancy_id]
        if not occupancy.checked:
            continue
        if not nodes:
            unmeshed.append(element.id)
            continue
        material = mats.get(slab_type.material)
        density = (material.mechanical.density or 0.0) if material else 0.0
        own = density * G * slab_systems.weight_thickness(slab_type) * 1e-3 / 1e3
        sd = load.superimposed(case) if load is not None else 0.0
        live = load.floor_live(case) if load is not None else 0.0
        w = own + sd + occupancy.serviceLive
        share = occupancy.serviceLive / live if live > 0 and "L" in static else 0.0
        ids = sorted(n for n in nodes if n in coords)
        down = np.array([-(uz("D", n) + uz("SD", n) + share * uz("L", n)) for n in ids])
        held = [k for k, n in enumerate(ids) if n in supported]
        reference = float(np.mean(down[held])) if held else float(np.min(down))
        relative = down - reference
        k = int(np.argmax(relative))
        delta = float(relative[k])
        if delta <= 0:
            continue
        points = np.array([coords[n] for n in ids])
        extent = tuple(points[:, a].max() - points[:, a].min() for a in (0, 1))
        held_points = points[held] if held else np.zeros((0, 3))
        lx, ly = _bay(points[k], held_points, extent)
        outline = [(float(x) / 1e3, float(y) / 1e3) for x, y in element.boundary]
        inside = [
            i
            for i, (level, mid) in enumerate(steel_beams)
            if level == round(element.elevation) and _inside(mid / 1e3, outline)
        ]
        steel = bool(inside)
        composite_factors = [stiffening[i] for i in inside if i in stiffening]
        if composite_factors:  # alpha 9 P8: the composite beams' dynamic stiffness
            factor = float(np.mean(composite_factors))
            notes.append(
                f"{element.id}: on composite beams, Δ × {factor:.2f} (Is / It,dyn, Ec × "
                f"{dynamic:g}, full interaction; the analysis carries the steel beams alone)"
            )
            delta *= factor
        fn = natural_frequency(delta, rules.frequencyConstant)
        method = rules.steelMethod if steel else rules.concreteMethod
        spread = getattr(rules.responseFactor, "spread", None)
        bays = continuous_bays(points[k], held_points, spread)
        found = check_panel(method, fn, w, lx * ly, max(lx, ly), occupancy, rules, bays)
        rows.append(
            {
                "slab": element.id,
                "story": stories.get(round(element.elevation), ""),
                "occupancy": occupancy.label,
                "floor": "steel" if steel else "concrete",
                "method": method,
                "deflection": 1e3 * delta,
                "fn": fn,
                "w": w,
                "bay": [lx, ly],
                "spread": list(bays),
                **found,
            }
        )
    if unmeshed:
        # Walk 4 W4B-13: said where the engineer looks (the Charts table and the step), not
        # only in the report.
        shown = ", ".join(unmeshed[:6]) + (
            f" and {len(unmeshed) - 6} more" if len(unmeshed) > 6 else ""
        )
        notes.append(
            f"{len(unmeshed)} slab{'s' if len(unmeshed) > 1 else ''} not checked ({shown}): "
            "floor vibration needs the slabs analysed as shells; with Project Settings > "
            "Analysis model > Slabs 'Loads to beams' they hand their loads to the beams and have "
            "no deflection of their own: choose 'Shells' and run the analysis again"
        )
    if not rows:
        notes.append("no slab analysed as shells with an occupancy that has a criterion")
    clauses = rules.clauses or {}
    all_notes = notes + [
        (
            f"fn = {rules.frequencyConstant:g} √(g/Δ), Δ the panel's deflection under D + SD + "
            "the service live load relative to its supported nodes, from the analysis"
        )
    ]
    return {
        "available": True,
        "rows": rows,
        "notes": all_notes,
        "unmeshed": unmeshed,
        "clause": rules.source,
        "clauses": [str(v) for v in clauses.values()],
        "sheet": sheet(rows, rules.source, notes),
    }


#: Walk 4 W4B-13: the methods' names in the tables (the pack's method ids are keys).
METHOD_LABELS = {
    "responseFactor": "response factor R",
    "walkingAcceleration": "peak acceleration ap/g",
}


def method_label(method: str) -> str:
    """A method id as the tables print it (``responseFactor`` → "response factor R")."""
    return METHOD_LABELS.get(method, method)


def _inside(point: np.ndarray, polygon: list[tuple[float, float]]) -> bool:
    x, y = float(point[0]), float(point[1])
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def sheet(
    rows: list[dict[str, Any]], source: str, notes: list[str] | None = None
) -> dict[str, Any]:
    """The rows as a table of the results view (name, columns, rows, notes): ``notes`` (what
    was not checked and why) before the source."""
    return {
        "name": "Floor vibration",
        "columns": [
            "Slab", "Story", "Occupancy", "Floor", "Method", "Δ [mm]", "fn [Hz]", "w [kN/m²]",
            "Bay [m]", "Response", "Limit", "Unit", "Result",
        ],
        "rows": [
            [
                r["slab"], r["story"], r["occupancy"], r["floor"], method_label(r["method"]),
                round(r["deflection"], 2), round(r["fn"], 2), round(r["w"], 2),
                f"{r['bay'][0]:.2f} × {r['bay'][1]:.2f}", round(r["value"], 3),
                round(r["limit"], 3), r["unit"], "OK" if r["ok"] else "FAIL",
            ]
            for r in rows
        ],
        "notes": [*(notes or []), source],
    }  # fmt: skip


def report_rows(found: dict[str, Any] | None) -> dict[str, Any] | None:
    """The report's rows (strings) of :func:`evaluate`."""
    if not found:
        return None
    if not found.get("available"):
        return {"available": False, "reason": found.get("reason", "")}
    data = found["sheet"]
    return {
        "available": True,
        "columns": data["columns"],
        "rows": [[str(c) for c in row] for row in data["rows"]],
        "fails": [not r["ok"] for r in found["rows"]],
        "clause": found["clause"],
        "notes": found["notes"] + found["clauses"],
    }


__all__ = [
    "check_panel",
    "continuous_bays",
    "effective_bays",
    "evaluate",
    "method_label",
    "natural_frequency",
    "report_rows",
    "response_factor",
    "walking_acceleration",
]

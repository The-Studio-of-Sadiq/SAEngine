"""Openings the HVAC ducts need through the structure, or how else they can pass.

A horizontal duct of 07 MEP ``hvac.ducts`` runs in the ceiling space of its story, under the
floor of the story above: its underside ``bottom`` above the story's floor, or by default its
insulated top 25 mm below the slab soffit (SAEngine default for the hangers). Where its plan
path crosses a beam of 06 BIM at the level above and its vertical extent overlaps the beam's
depth, it needs a web opening. The proposed opening is a 07 MEP opening (host: the beam;
position: the crossing's distance from the beam's start and the duct centre's elevation above
the beam's bottom) of the duct's outside size (with insulation, :data:`saengine.hvac.air.
INSULATION`) plus 50 mm each side (75 mm for kitchen exhaust, BNBC 2020 Part 8 Sec 2.11.5.1(f),
p. 912), rounded up to 50 mm; its length along the beam is the duct's width over the sine of
the crossing angle plus the web width times the cotangent (the duct shifts along the beam as it
passes through the web). A round duct crossing near square (its oblique length at most 50 mm
over its diameter) takes a circular opening.

Each opening is checked by the existing opening checks of :mod:`saengine.mep.openings`
(through :func:`saengine.mep.report.suggestion_checks`: h/3, length up to d, clear of the
support faces by h, concrete above and below; the forces at it once the analysis has run).
When it fails, the duct is reported with the ways round it:

- route below the beam: the duct's insulated top 50 mm under the beam soffit; the clear
  height left under it (above a 50 mm floor finish, SAEngine default) against the 2.44 m BNBC
  2020 Part 3 Sec 1.14.2.1(b) requires under a duct in an air-conditioned room (Part 1 volume
  p. 66; Table 3.1.9's ceiling heights for educational, health care, assembly, 2.6 m, and
  storage, 3.0 m, air-conditioned);
- increase the floor height by what the clear height lacks (the floor-to-floor it needs);
- split the duct into parallel ducts shallow enough to pass an h/3 opening;
- lower the duct to the beam's mid-depth (when its position was not given and an opening
  there passes);
- pass through the slab: rise into the floor above through slab openings each side of the
  beam (their size is given).

Duct risers (``riser``) cut the slab of every story above their first, up to their last (the
07 MEP shaft convention), at ``path[0]``: a rectangular slab opening (width along X) or a
circular one of the duct's outside size plus 50 mm each side, unless the riser is in a shaft of
07 MEP or an opening of 06 BIM. Openings 07 MEP already has where the duct crosses are matched
(:func:`saengine.mep.clash._matching_opening`) and not proposed again. A duct moved since its
opening was accepted gets the opening again at its new crossing under the same id (``replaces``
in its crossing record: it replaces the saved one); saved ``HD-``/``HR-`` openings of a duct that
no longer crosses there are listed in ``stale``. Only openings that pass the checks are proposed;
the others are conflicts (riser slab openings with the option to run the riser in a shaft).
"""

from __future__ import annotations

import itertools
import math
from types import SimpleNamespace
from typing import Any

import numpy as np
from shapely.geometry import LineString, Point

from saengine.hvac.air import (
    ASPECT_MAX,
    HEADROOM_UNDER_DUCT,
    INSULATION,
    Project,
    ceiling_height,
    given_size,
    outside,
    size_duct,
)
from saengine.mep.geometry import bounded_id

CLEARANCE = 50.0  # mm each side of a duct through a beam or slab (SAEngine practice)
KITCHEN_CLEARANCE = 75.0  # mm, BNBC 2020 Part 8 Sec 2.11.5.1(f)
HANGER_GAP = 25.0  # mm, insulated top of a duct below the soffit by default
BELOW_GAP = 50.0  # mm, a duct routed below a beam
FLOOR_FINISH = 50.0  # mm
ROUND_SQUARE = math.sin(math.radians(75.0))  # within 15° of square: circular opening
LEVEL_TOLERANCE = 300.0  # mm, beams of a story's level (as slabs, plumbing.building)
STEP = 50.0


def _up(value: float) -> float:
    return math.ceil(value / STEP - 1e-9) * STEP


def clearance_of(system: str) -> float:
    return KITCHEN_CLEARANCE if system == "kitchenExhaust" else CLEARANCE


def required_headroom(use: str | None) -> tuple[float, str]:
    """Clear height needed under a duct [mm] and its source."""
    table = ceiling_height(use)
    if table and table > HEADROOM_UNDER_DUCT:
        return table, "BNBC 2020 Part 3 Table 3.1.9 (air-conditioned), Part 1 volume p. 66"
    return HEADROOM_UNDER_DUCT, "BNBC 2020 Part 3 Sec 1.14.2.1(b), Part 1 volume p. 66"


def beam_opening_for(
    beam_axis: tuple[tuple[float, float], tuple[float, float]],
    beam_bottom: float,
    crossing: tuple[float, float],
    duct_dir: tuple[float, float],
    width: float,
    height: float,
    round_duct: bool,
    centre_z: float,
    clearance: float,
    beam_width: float = 0.0,
) -> dict[str, Any]:
    """The opening (shape, size, position) a duct of outside ``width`` x ``height`` [mm]
    crossing a beam of web thickness ``beam_width`` at plan point ``crossing`` with its centre
    at level ``centre_z`` needs.

    At a crossing angle θ the duct's section in the beam's face is ``width / sin θ`` long, and
    passing through the web it shifts ``beam_width · |cot θ|`` along the beam: the length the
    opening needs (``need``) is their sum; the opening is that plus ``clearance`` each side. A
    round duct takes a circle while the oblique length exceeds its diameter by at most 50 mm
    (about 15° from square for usual webs), else a rectangle."""
    start, end = np.asarray(beam_axis[0], float), np.asarray(beam_axis[1], float)
    axis = (end - start) / np.linalg.norm(end - start)
    d = np.asarray(duct_dir, float)
    d = d / np.linalg.norm(d)
    sine = max(abs(float(axis[0] * d[1] - axis[1] * d[0])), 1e-6)
    cosine = abs(float(axis @ d))
    along = width / sine + max(beam_width, 0.0) * cosine / sine
    distance = float((np.asarray(crossing, float) - start) @ axis)
    position = {"distance": round(distance, 1), "elevation": round(centre_z - beam_bottom, 1)}
    if round_duct and sine >= ROUND_SQUARE and along - width <= STEP:
        return {"shape": "circle", "diameter": _up(along + 2 * clearance), "position": position,
                "sine": sine, "need": (along, along)}  # fmt: skip
    return {
        "shape": "rectangle",
        "width": _up(along + 2 * clearance),
        "height": _up(height + 2 * clearance),
        "position": position,
        "sine": sine,
        "need": (along, height),
    }


def beam_width_of(profile: Any) -> float:
    """Width [mm] of a beam's section (its web for RC rectangles; the flange for steel, on the
    safe side)."""
    for attribute in ("xDim", "overallWidth", "flangeWidth"):
        value = getattr(profile, attribute, None)
        if value:
            return float(value)
    radius = getattr(profile, "radius", None)
    return 2 * float(radius) if radius else 0.0


def _level_of(project: Project, story: str | None) -> float | None:
    return project.building.stories.get(story) if story else None


def _beams_at(project: Project, level: float) -> list[Any]:
    from saengine.library.bim import BeamElement

    return [
        e
        for e in project.bim.elements
        if isinstance(e, BeamElement) and abs(e.elevation - level) <= LEVEL_TOLERANCE
    ]


def _types(project: Project) -> dict[str, Any]:
    return {o.id: o for o in project.objects.objects} if project.objects else {}


def _slab_thickness(project: Project, story: str, x: float, y: float) -> float:
    """Thickness [mm] of the slab of ``story`` over a plan point (the thickest of the level
    when none is over it; 0 without slabs)."""
    from saengine.library.bim import SlabElement

    types = _types(project)
    sid = project.building.slab_at(story, x, y)
    level = project.building.stories.get(story)
    best = 0.0
    for e in project.bim.elements:
        if not isinstance(e, SlabElement):
            continue
        t = float(getattr(types.get(e.type), "thickness", 0.0) or 0.0)
        if e.id == sid:
            return t
        if level is not None and abs(e.elevation - level) <= LEVEL_TOLERANCE:
            best = max(best, t)
    return best


def _checks(project: Project, suggestion: dict[str, Any]) -> tuple[list[dict], list[str]]:
    from saengine.mep.report import suggestion_checks

    if project.objects is None or project.materials is None:
        return [], [f"{suggestion['id']}: 04 Objects or 03 Materials missing: not checked"]
    return suggestion_checks(suggestion, project.bim, project.objects, project.materials)


def _passes(checks: list[dict[str, Any]]) -> bool:
    return all(c["ok"] for c in checks if not c.get("flag"))


def _existing(project: Project, element: Any, suggestion: dict[str, Any]) -> tuple[Any, bool]:
    """The 07 MEP opening already in ``element`` where the duct crosses, and whether it is big
    enough for the duct with its insulation."""
    from saengine.mep.clash import _matching_opening, host_of

    host = host_of(element, _types(project))
    if host is None:
        return None, False
    if suggestion["shape"] == "circle":
        needed = {"shape": "circle", "diameter": suggestion["need"][0]}
    else:
        needed = {"shape": "rectangle", "width": suggestion["need"][0],
                  "height": suggestion["need"][1]}  # fmt: skip
    cross = {"position": suggestion["position"], "needed": needed}
    return _matching_opening(host, cross, list(project.mep.openings))


def _suggestion(oid: str, host: str, opening: dict[str, Any], service: str) -> dict[str, Any]:
    out = {"id": oid, "host": host, "kind": "opening", "shape": opening["shape"],
           "position": opening["position"], "service": service}  # fmt: skip
    for key in ("diameter", "width", "height"):
        if key in opening:
            out[key] = opening[key]
    return out


def _service(duct: dict[str, Any], size: dict[str, Any]) -> str:
    if size.get("diameter") and size.get("shape") == "round":
        dims = f"Ø{size['diameter']:g}"
    else:
        dims = f"{size['width']:g} x {size['height']:g}"
    return f"{duct.get('system', 'supply')} duct {dims} {duct['id']}"


def duct_openings(project: Project, sizes: dict[str, dict[str, Any]] | None = None) -> dict:
    """Openings the ducts of the project's ``hvac`` section need: ``{"openings": [proposed 07
    MEP openings that pass the checks], "conflicts": [{"duct", "beam", "opening", "checks",
    "options", ...}], "crossings": [every crossing found], "checks", "notes"}``. ``sizes``:
    duct id -> size (from :func:`saengine.hvac.air.duct_sizes`); a duct's own size else."""
    sizes = sizes or {}
    notes: list[str] = []
    if project.bim is None or not project.building.known:
        return {"openings": [], "conflicts": [], "crossings": [], "checks": [],
                "notes": ["no 06 BIM: the ducts' openings are not worked out"]}  # fmt: skip
    entries = {s.get("story"): s for s in project.hvac.get("stories", [])}
    openings: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    crossings: list[dict[str, Any]] = []
    saved = {o.id for o in project.mep.openings}
    matched: set[str] = set()
    unsized: set[str] = set()
    for duct in project.hvac.get("ducts", []):
        size = sizes.get(duct["id"]) or given_size(duct)
        if size is None:
            notes.append(f"{duct['id']}: no size: its openings are not worked out")
            unsized.add(duct["id"])
            continue
        if duct.get("riser"):
            openings += _riser_openings(
                project, duct, size, saved, matched, notes, crossings, conflicts
            )
            continue
        path = duct.get("path") or []
        if len(path) < 2:
            continue
        story = duct.get("story")
        above = project.above(story)
        level = _level_of(project, story)
        if above is None or level is None:
            notes.append(f"{duct['id']}: no story above {story}: no beams to cross")
            continue
        top_level = project.building.stories[above]
        use = entries.get(story, {}).get("use")
        found = _horizontal(
            project, duct, size, story, level, above, top_level, use, saved, matched
        )
        crossings += found["crossings"]
        openings += found["openings"]
        conflicts += found["conflicts"]
    stale = _stale(project, saved - matched, unsized)
    for oid in stale:
        notes.append(f"07 MEP opening {oid} was proposed for a duct that no longer passes there")
    checks = []
    if crossings:
        bad = len(conflicts)
        checks.append({
            "name": "Ducts through beams and slabs", "demand": float(bad), "capacity": 0.0,
            "unit": "ducts", "utilisation": float(bad), "ok": bad == 0,
            "note": f"{len(crossings)} crossings: {len(openings)} openings proposed, {bad} "
            "that no checked opening can pass (route below, raise the floor, split the duct or "
            "move the riser into a shaft)",
        })  # fmt: skip
    notes.append(
        f"openings: duct outside size + {CLEARANCE:g} mm each side ({KITCHEN_CLEARANCE:g} mm "
        "for kitchen exhaust, BNBC Sec 2.11.5.1(f)), rounded up to 50 mm (SAEngine practice)"
    )
    return {"openings": openings, "conflicts": conflicts, "crossings": crossings,
            "stale": stale, "checks": checks, "notes": notes}  # fmt: skip


def _stale(project: Project, unmatched: set[str], unsized: set[str]) -> list[str]:
    """Ids of 07 MEP openings proposed for a duct (``HD-<duct>-...``, ``HR-<duct>-...``) where
    no crossing of that duct is any more (the duct moved or was removed). Ducts without a size
    are left alone (their crossings were not worked out)."""
    ducts = {d["id"] for d in project.hvac.get("ducts", [])}
    out = []
    for oid in sorted(unmatched):
        if not oid.startswith(("HD-", "HR-")):
            continue
        rest = oid[3:]
        owner = next(
            (d for d in sorted(ducts, key=len, reverse=True) if rest.startswith(f"{d}-")), None
        )
        if owner in unsized:
            continue
        out.append(oid)
    return out


def _horizontal(
    project: Project,
    duct: dict[str, Any],
    size: dict[str, Any],
    story: str,
    level: float,
    above: str,
    top_level: float,
    use: str | None,
    saved: set[str],
    matched: set[str],
) -> dict[str, list[dict[str, Any]]]:
    from saengine.mep.routing import path_beam_crossings
    from saengine.mep.routing import profile_depth as _depth

    system = duct.get("system", "supply")
    w_out, h_out, is_round = outside(duct, size)
    ins = INSULATION.get(system, 0.0)
    clearance = clearance_of(system)
    types = _types(project)
    path = [tuple(p[:2]) for p in duct["path"]]
    out: dict[str, list[dict[str, Any]]] = {"openings": [], "conflicts": [], "crossings": []}
    beams = _beams_at(project, top_level)
    # Beam by beam (06 BIM's order), along the duct on each: the crossings' ids number in turn.
    order = {id(b): i for i, b in enumerate(beams)}
    hits: dict[int, list[Any]] = {}
    for crossing in path_beam_crossings(path, beams):
        hits.setdefault(order[id(crossing.beam)], []).append(crossing)
    for index in sorted(hits):
        beam = beams[index]
        points = [Point(*c.point) for c in hits[index]]
        profile = getattr(types.get(beam.type), "profile", None)
        depth = _depth(profile)
        if depth <= 0:
            continue
        web = beam_width_of(profile)
        beam_bottom = beam.elevation - depth
        for point in points:
            x, y = point.x, point.y
            segment = _segment_at(path, x, y)
            soffit = top_level - _slab_thickness(project, above, x, y)
            if duct.get("bottom") is not None:
                outer_bottom = level + float(duct["bottom"]) - ins
                given = True
            else:
                outer_bottom = soffit - HANGER_GAP - h_out
                given = False
            outer_top = outer_bottom + h_out
            if outer_top <= beam_bottom + 1.0:
                continue  # passes below the beam
            centre = outer_bottom + h_out / 2
            opening = beam_opening_for(
                (tuple(beam.start), tuple(beam.end)), beam_bottom, (x, y), segment,
                w_out, h_out, is_round, centre, clearance, web,
            )  # fmt: skip
            oid = bounded_id(f"HD-{duct['id']}-{beam.id}", f"-{len(out['crossings']) + 1}")
            suggestion = _suggestion(oid, beam.id, opening, _service(duct, size))
            record = {
                "duct": duct["id"], "beam": beam.id, "story": story, "at": [x, y],
                "beamDepth": depth, "beamBottom": beam_bottom, "ductTop": outer_top,
                "ductBottom": outer_bottom, "opening": suggestion,
            }  # fmt: skip
            out["crossings"].append(record)
            match, big = _existing(project, beam, opening)
            if match is not None:
                record["existing"] = match.id
                matched.add(match.id)
                if not big:
                    record["notes"] = [f"07 MEP opening {match.id} is too small for the duct"]
                    out["conflicts"].append({**record, "checks": [], "options": []})
                continue
            if oid in saved:
                # The duct moved since this opening was accepted: propose it again at the new
                # crossing under the same id (it replaces the one in 07 MEP).
                record["replaces"] = oid
                matched.add(oid)
            checks, notes = _checks(project, suggestion)
            record["checks"], record["notes"] = checks, notes
            if checks and _passes(checks):
                out["openings"].append(suggestion)
                continue
            record["options"] = route_options(
                project, duct, size, story, level, beam, depth, beam_bottom, soffit,
                (x, y), segment, use, given, clearance,
            )  # fmt: skip
            out["conflicts"].append(record)
    return out


def _segment_at(path: list[tuple[float, float]], x: float, y: float) -> tuple[float, float]:
    """Direction of the path's segment through a plan point."""
    best, direction = math.inf, (1.0, 0.0)
    for a, b in itertools.pairwise(path):
        d = LineString([a, b]).distance(Point(x, y))
        if d < best and math.dist(a, b) > 0:
            best, direction = d, (b[0] - a[0], b[1] - a[1])
    return direction


def route_options(
    project: Project,
    duct: dict[str, Any],
    size: dict[str, Any],
    story: str,
    level: float,
    beam: Any,
    depth: float,
    beam_bottom: float,
    soffit: float,
    at: tuple[float, float],
    direction: tuple[float, float],
    use: str | None,
    given: bool,
    clearance: float,
) -> list[dict[str, Any]]:
    """The ways a duct can pass a beam no web opening can take."""
    web = beam_width_of(getattr(_types(project).get(beam.type), "profile", None))
    system = duct.get("system", "supply")
    w_out, h_out, is_round = outside(duct, size)
    ins = INSULATION.get(system, 0.0)
    need, source = required_headroom(use)
    options = []
    # Route below the beam.
    top = beam_bottom - BELOW_GAP
    clear = top - h_out - (level + FLOOR_FINISH)
    short = max(need - clear, 0.0)
    height = project.story_height(story)
    options.append({
        "kind": "routeBelow",
        "bottom": round(top - h_out + ins - level, 1),
        "clearHeight": round(clear, 1),
        "required": need,
        "ok": clear >= need,
        "note": f"duct top {BELOW_GAP:g} mm under the beam soffit: {clear:.0f} mm clear above a "
        f"{FLOOR_FINISH:g} mm floor finish, {need:g} mm needed ({source})",
    })  # fmt: skip
    # Increase the floor height.
    options.append({
        "kind": "increaseFloorHeight",
        "by": round(short, 1),
        "floorToFloor": round((height or 0.0) + short, 1) if height else None,
        "ok": True,
        "note": "no change needed below the beam" if short <= 0 else
        f"raise the floor above {story} by {short:.0f} mm to route the duct below {beam.id}",
    })  # fmt: skip
    # Split into ducts shallow enough for an h/3 opening.
    room = depth / 3 - 2 * clearance - 2 * ins
    flow = _flow_of(duct, size)
    if room >= 100.0 and flow:
        sized = size_duct(flow, system, "rect", max_height=math.floor(room / STEP) * STEP)
        n = 1
        while sized.get("height", math.inf) > room + 1e-9 and n < 6:
            n += 1
            sized = size_duct(flow / n, system, "rect", max_height=math.floor(room / STEP) * STEP)
        options.append({
            "kind": "split", "ducts": n, "width": sized.get("width"),
            "height": sized.get("height"), "ok": sized.get("height", math.inf) <= room + 1e-9,
            "note": f"{n} parallel ducts of {sized.get('width'):g} x {sized.get('height'):g} mm "
            f"(at most {room:.0f} mm deep for an h/3 = {depth / 3:.0f} mm opening); each needs "
            "its own opening, three diameters apart",
        })  # fmt: skip
    elif room >= 100.0:
        # No flow known (the duct's size was given): keep its free area.
        if is_round:
            area = math.pi / 4 * float(size["diameter"]) ** 2
        else:
            area = float(size["width"]) * float(size["height"])
        h = math.floor(room / STEP) * STEP
        n = 1
        while _up(area / n / h) > ASPECT_MAX * h and n < 6:
            n += 1
        w = _up(area / n / h)
        options.append({
            "kind": "split", "ducts": n, "width": w, "height": h,
            "ok": w <= ASPECT_MAX * h,
            "note": f"{n} parallel ducts of {w:g} x {h:g} mm with the duct's free area (no flow "
            f"given: not resized by friction; at most {room:.0f} mm deep for an h/3 = "
            f"{depth / 3:.0f} mm opening); each needs its own opening, three diameters apart",
        })  # fmt: skip
    else:
        options.append({"kind": "split", "ok": False,
                        "note": f"h/3 = {depth / 3:.0f} mm leaves no room for a duct"})  # fmt: skip
    # Lower to the beam's mid-depth.
    if not given:
        centre = beam_bottom + depth / 2
        opening = beam_opening_for(
            (tuple(beam.start), tuple(beam.end)), beam_bottom, at, direction, w_out, h_out,
            is_round, centre, clearance, web,
        )  # fmt: skip
        trial = _suggestion("trial", beam.id, opening, "")
        checks, _ = _checks(project, trial)
        options.append({
            "kind": "lowerToMidDepth", "bottom": round(centre - h_out / 2 + ins - level, 1),
            "ok": bool(checks) and _passes(checks),
            "note": "centre the duct at the beam's mid-depth (give its bottom)",
        })  # fmt: skip
    # Through the slab above.
    sw = _up(w_out + 2 * clearance)
    sh = _up(h_out + 2 * clearance)
    options.append({
        "kind": "throughSlab", "slabOpening": {"width": sw, "height": sh}, "ok": True,
        "note": f"rise into the floor above through two slab openings of {sw:g} x {sh:g} mm, "
        f"one each side of {beam.id} (raised floor or bulkhead above; checked once added)",
    })  # fmt: skip
    return options


def _flow_of(duct: dict[str, Any], size: dict[str, Any]) -> float | None:
    if isinstance(duct.get("flow"), int | float):
        return float(duct["flow"])
    return size.get("flow")


def _riser_openings(
    project: Project,
    duct: dict[str, Any],
    size: dict[str, Any],
    saved: set[str],
    matched: set[str],
    notes: list[str],
    crossings: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Slab openings of a duct riser (see the module's docstring): those that pass the opening
    checks; the others go to ``conflicts``."""
    from saengine.library.bim import SlabElement
    from saengine.plumbing.sleeves import _in_shaft

    riser = duct["riser"]
    path = duct.get("path") or []
    if not path:
        notes.append(f"{duct['id']}: a riser needs its plan position (path[0])")
        return []
    x, y = float(path[0][0]), float(path[0][1])
    stand_in = SimpleNamespace(x=x, y=y)
    w_out, h_out, is_round = outside(duct, size)
    clearance = clearance_of(duct.get("system", "supply"))
    out = []
    for story in project.building.between(riser.get("fromStory"), riser.get("toStory"))[1:]:
        if duct.get("shaft") or _in_shaft(project.mep, stand_in, story, project.building):
            continue
        slab = project.building.slab_at(story, x, y)
        if slab is None:
            notes.append(f"{duct['id']}: no slab of {story} under ({x:g}, {y:g})")
            continue
        if project.building.in_hole(slab, x, y):
            continue
        oid = bounded_id(f"HR-{duct['id']}-{story}")
        if is_round:
            opening = {"shape": "circle", "diameter": _up(w_out + 2 * clearance)}
            need = (w_out, w_out)
        else:
            opening = {"shape": "rectangle", "width": _up(w_out + 2 * clearance),
                       "height": _up(h_out + 2 * clearance)}  # fmt: skip
            need = (w_out, h_out)
        position = {"x": x, "y": y}
        suggestion = _suggestion(oid, slab, {**opening, "position": position},
                                 _service(duct, size))  # fmt: skip
        record = {"duct": duct["id"], "slab": slab, "story": story, "at": [x, y],
                  "opening": suggestion}  # fmt: skip
        crossings.append(record)
        element = next(
            (e for e in project.bim.elements if isinstance(e, SlabElement) and e.id == slab), None
        )
        match, big = (
            _existing(project, element, {**opening, "position": position, "need": need})
            if element is not None
            else (None, False)
        )
        if match is not None:
            record["existing"] = match.id
            matched.add(match.id)
            if not big:
                record["notes"] = [f"07 MEP opening {match.id} is too small for the duct"]
                conflicts.append({**record, "checks": [], "options": []})
            continue
        if oid in saved:
            record["replaces"] = oid  # the riser moved: proposed again at its new place
            matched.add(oid)
        checks, more = _checks(project, suggestion)
        record["checks"], record["notes"] = checks, more
        if checks and _passes(checks):
            out.append(suggestion)
            continue
        record["options"] = [{
            "kind": "inShaft", "ok": True,
            "note": "run the riser in a shaft of 07 MEP (or a 06 BIM floor opening) framed for it",
        }]  # fmt: skip
        conflicts.append(record)
    return out


def hvac_duct_openings(
    project_root: Any, loads: dict[str, Any] | None = None, mep_text: str | None = None
) -> dict[str, Any]:
    """The openings the project's ducts need (:func:`duct_openings`), the ducts sized by
    :func:`saengine.hvac.air.duct_sizes` where they give no size (``loads``: the HVAC load
    calculation's result, None runs it)."""
    from saengine.hvac.air import _hvac_loads, duct_sizes, load_project, zone_air

    project = load_project(project_root, mep_text)
    if loads is None and any(given_size(d) is None for d in project.hvac.get("ducts", [])):
        loads = _hvac_loads(project_root, mep_text)
    zones, notes = zone_air(project, loads)
    ducts, more = duct_sizes(project, zones)
    sizes = {d["id"]: {**d["size"], "flow": d["flow"]} for d in ducts}
    result = duct_openings(project, sizes)
    result["notes"] = notes + more + result["notes"]
    result["problems"] = project.problems
    return result

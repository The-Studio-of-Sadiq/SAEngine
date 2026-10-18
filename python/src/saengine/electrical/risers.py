"""Rising mains and cable trays: their sizes and the openings they need in the structure
(BNBC 2020 Part 8 Sec 1.3.13).

- Rising main current: the maximum demand of the stories it feeds (``serves``, else every
  story it passes), as :mod:`saengine.electrical.demand` gives them, I = S / (sqrt(3) x 400 V);
  at each floor it crosses, the stories at and above it.
- Busbar trunking: the next rating of the typical table at the base current (one rating up the
  riser, Sec 1.3.13.3: 200 A to 3000 A typical) and its typical width and depth. A cable riser:
  one 4-core cable per story fed, of the typical outside diameter for its current, fixed side by
  side with 37 mm between cables (Sec 1.3.13.2(e)), on the next standard tray width.
- Openings: a riser not in a shaft (07 MEP) or a 06 BIM slab opening needs a rectangular opening
  through the slab of every story it crosses (the stories above its first, up to its last, as
  07 MEP's shafts count them): its width and depth plus 100 mm each side, to the next 50 mm
  (SAEngine practice: room for the fire stopping Sec 1.3.13.1 asks for round the cables).
- Cable trays run in the ceiling space of their story, by default with 150 mm above them to lay
  the cables, under the slab soffit of the story above. Where a tray's run crosses a beam of the
  floor above and its depth overlaps the beam's, the beam needs a web opening of the tray's
  width across the beam (/sin of the crossing angle) and its height, plus 50 mm each side, to
  the next 50 mm (SAEngine practice). The proposed openings are 07 MEP openings, so the beam and
  slab opening checks of :mod:`saengine.mep.openings` run on them once they are added.
- Tray fill: the cables' cross-section at most 40 % of the tray's (from memory, to be checked).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Point, Polygon

from saengine.electrical import tables as T
from saengine.mep.routing import BeamLine
from saengine.mep.routing import path_beam_crossings as crossings_of
from saengine.mep.routing import profile_depth as _depth
from saengine.plumbing.building import SLAB_TOLERANCE, Building

#: Slab thickness when 04 Objects does not give one [mm].
DEFAULT_SLAB = 150.0
#: Below this sine of the crossing angle a tray runs along the beam, not across it.
MIN_SINE = 0.17


def _ceil(value: float, step: float = T.OPENING_STEP) -> float:
    return math.ceil(value / step - 1e-9) * step


@dataclass
class Frame:
    """The beams and slab thicknesses of 06 BIM (with 04 Objects for the sizes)."""

    beams: list[BeamLine] = field(default_factory=list)
    slab_thickness: dict[str, float] = field(default_factory=dict)

    @classmethod
    def of(cls, bim: Any, objects: Any = None) -> Frame:
        if bim is None:
            return cls()
        types = {o.id: o for o in objects.objects} if objects is not None else {}
        beams = []
        thickness = {}
        for e in bim.elements:
            if e.kind == "beam":
                depth = _depth(getattr(types.get(e.type), "profile", None))
                beams.append(
                    BeamLine(e.id, tuple(e.start), tuple(e.end), float(e.elevation), depth)
                )
            elif e.kind == "slab":
                t = getattr(types.get(e.type), "thickness", None)
                thickness[e.id] = float(t) if t else DEFAULT_SLAB
        return cls(beams, thickness)

    def beams_at(self, level: float) -> list[BeamLine]:
        return [b for b in self.beams if abs(b.top - level) <= SLAB_TOLERANCE]


def path_beam_crossings(path: list[list[float]], beams: list[BeamLine]) -> list[dict[str, Any]]:
    """Where a plan path crosses beams: ``[{beam, point (x, y), distance (from the beam's
    start, mm), sine (of the angle between them)}]`` in the order along the path; a run within
    10° of a beam runs along it (:data:`MIN_SINE`). :func:`saengine.mep.routing.path_beam_crossings`
    (shared with the HVAC ducts)."""
    return [
        {"beam": c.beam, "point": c.point, "distance": c.distance, "sine": c.sine}
        for c in crossings_of(path, beams, MIN_SINE)
    ]


# ───────────────────────────────────── rising mains ─────────────────────────────────────


def passes(riser: Any, building: Building, order: list[str]) -> list[str]:
    """Stories a riser passes, lowest first."""
    if building.known:
        return building.between(riser.fromStory, riser.toStory)
    if riser.fromStory in order and riser.toStory in order:
        i, j = order.index(riser.fromStory), order.index(riser.toStory)
        return order[i : j + 1]
    return []


def busbar(amps: float) -> tuple[float, float, float, float] | None:
    """(rating A, width, depth mm, kg/m) of the typical busbar for ``amps``."""
    for rating in sorted(T.BUSBARS):
        if rating >= amps - 1e-9:
            width, depth, mass = T.BUSBARS[rating]
            return float(rating), float(width), float(depth), float(mass)
    return None


def size_riser(
    riser: Any, demand: dict[str, Any], building: Building, order: list[str], storeys: int
) -> dict[str, Any]:
    """The current, rating and size of a rising main."""
    kva = {s["story"]: s["kva"] for s in demand["stories"]}
    stories = passes(riser, building, order)
    fed = [s for s in stories if s in riser.serves] if riser.serves else stories
    notes = []
    amps_of = 1000.0 / (math.sqrt(3) * T.LT_VOLTAGE)
    base = sum(kva.get(s, 0.0) for s in fed) * amps_of
    segments = []
    for i, story in enumerate(stories[1:], start=1):
        above = [s for s in fed if s in stories[i:]]
        segments.append({"story": story, "current": sum(kva.get(s, 0.0) for s in above) * amps_of})
    out: dict[str, Any] = {
        "id": riser.id, "kind": riser.kind, "stories": stories, "fed": fed, "current": base,
        "segments": segments, "rating": riser.rating, "width": riser.width,
        "depth": riser.depth, "weightPerM": None, "ok": True, "notes": notes,
    }  # fmt: skip
    if not stories:
        out["ok"] = False
        notes.append("its stories are not in the building model")
        return out
    if riser.kind == "busbar":
        size = busbar(max(base, T.BUSBAR_RANGE[0]))
        if size is None:
            notes.append(f"{base:.0f} A exceeds the largest busbar listed: split the riser")
            size = busbar(max(T.BUSBARS))
        assert size is not None
        rating, width, depth, mass = size
        out["rating"] = riser.rating or rating
        out["width"] = riser.width or width
        out["depth"] = riser.depth or depth
        out["weightPerM"] = mass * T.G / 1000.0
        if riser.width is None or riser.depth is None:
            notes.append(f"busbar size {width:g} x {depth:g} mm ({T.TYPICAL})")
    else:
        currents = [kva.get(s, 0.0) * amps_of for s in fed]
        ods = [T.cable_od(a) for a in currents if a > 0]
        need = sum(ods) + T.CABLE_SPACING * max(len(ods) - 1, 0)
        width = T.next_size(need, T.TRAY_WIDTHS) or _ceil(need, 150.0)
        out["rating"] = riser.rating or max(currents, default=0.0)
        out["width"] = riser.width or width
        out["depth"] = riser.depth or max(ods, default=50.0) + 2 * T.CABLE_SPACING
        out["cables"] = len(ods)
        notes.append(
            f"{len(ods)} cables side by side, 37 mm apart ({T.PAGES['1.3.13.2']}); cable "
            f"diameters {T.TYPICAL}"
        )
        if storeys > T.BUSBAR_STOREYS:
            notes.append(
                f"more than {T.BUSBAR_STOREYS} storeys: busbar trunking should be used "
                f"({T.cite('1.3.13.2', '(d)')})"
            )
    if riser.rating is not None and riser.rating < base - 1e-6:
        out["ok"] = False
        notes.append(f"rated {riser.rating:g} A below the {base:.0f} A it carries")
    return out


def _shaft_covers(mep: Any, x: float, y: float, story: str, building: Building) -> str | None:
    point = Point(x, y)
    for shaft in mep.shafts:
        if not Polygon(shaft.outline).buffer(0).covers(point):
            continue
        if building.known and shaft.fromStory in building.stories:
            lo = building.stories[shaft.fromStory]
            hi = building.stories.get(shaft.toStory, lo)
            if not lo < building.stories.get(story, lo) <= hi:
                continue
        return shaft.id
    return None


def riser_openings(
    mep: Any, sizes: list[dict[str, Any]], building: Building, order: list[str]
) -> dict[str, Any]:
    """Proposed slab openings (07 MEP openings) for the rising mains."""
    electrical = mep.electrical
    by_id = {s["id"]: s for s in sizes}
    existing = {o.id for o in mep.openings}
    openings, notes = [], []
    for riser in electrical.risers:
        size = by_id.get(riser.id) or {}
        width, depth = size.get("width"), size.get("depth")
        if not width or not depth:
            notes.append(f"{riser.id}: no size, no opening")
            continue
        for story in passes(riser, building, order)[1:]:
            if riser.shaft is not None or _shaft_covers(mep, riser.x, riser.y, story, building):
                continue
            slab = building.slab_at(story, riser.x, riser.y)
            if slab is None:
                notes.append(f"{riser.id}: no slab of {story} under ({riser.x:g}, {riser.y:g})")
                continue
            if building.in_hole(slab, riser.x, riser.y):
                continue
            oid = f"PE-{riser.id}-{story}"
            if oid in existing:
                continue
            openings.append({
                "id": oid, "host": slab, "kind": "opening", "shape": "rectangle",
                "width": _ceil(width + 2 * T.OPENING_CLEARANCE),
                "height": _ceil(depth + 2 * T.OPENING_CLEARANCE),
                "position": {"x": riser.x, "y": riser.y},
                "service": f"{size.get('rating') or 0:.0f} A {riser.kind} {riser.id}",
            })  # fmt: skip
    notes.append(
        f"riser openings: its size + {T.OPENING_CLEARANCE:g} mm each side, to {T.OPENING_STEP:g} "
        f"mm (SAEngine practice); the space round the cables is to be filled with RCC or a "
        f"non-combustible material at each floor ({T.PAGES['1.3.13.1']})"
    )
    return {"openings": openings, "notes": notes}


# ───────────────────────────────────── cable trays ─────────────────────────────────────


def _story_above(story: str, building: Building) -> str | None:
    order = building.ordered()
    if story not in order:
        return None
    i = order.index(story)
    return order[i + 1] if i + 1 < len(order) else None


def tray_levels(tray: Any, building: Building, frame: Frame) -> dict[str, Any] | None:
    """A tray's underside and top [mm, absolute], and the floor above it (None without the
    story or the floor above in 06 BIM)."""
    if tray.story not in building.stories:
        return None
    floor = building.stories[tray.story]
    above = _story_above(tray.story, building)
    if above is None:
        return None
    level = building.stories[above]
    mid = LineString(tray.path).interpolate(0.5, normalized=True)
    slab = building.slab_at(above, mid.x, mid.y)
    thickness = frame.slab_thickness.get(slab, DEFAULT_SLAB) if slab else DEFAULT_SLAB
    if tray.bottom is not None:
        bottom = floor + tray.bottom
    else:
        bottom = level - thickness - T.TRAY_HEADROOM - tray.height
    return {"floor": floor, "above": above, "level": level, "slab": slab,
            "thickness": thickness, "bottom": bottom, "top": bottom + tray.height}  # fmt: skip


def tray_openings(mep: Any, building: Building, frame: Frame) -> dict[str, Any]:
    """Proposed beam openings (07 MEP openings) where the trays cross beams at their level."""
    electrical = mep.electrical
    existing = {o.id for o in mep.openings}
    openings, notes, crossings = [], [], []
    for tray in electrical.trays:
        levels = tray_levels(tray, building, frame)
        if levels is None:
            notes.append(f"{tray.id}: its story or the floor above is not in the building model")
            continue
        beams = frame.beams_at(levels["level"])
        seen: dict[str, int] = {}
        for cross in path_beam_crossings(tray.path, beams):
            beam = cross["beam"]
            if beam.depth <= 0:
                notes.append(f"{tray.id}: beam {beam.id} has no depth in 04 Objects")
                continue
            beam_bottom = beam.top - beam.depth
            record = {"tray": tray.id, "beam": beam.id, "point": list(cross["point"]),
                      "passesBelow": levels["top"] <= beam_bottom + 1e-6}  # fmt: skip
            crossings.append(record)
            if record["passesBelow"] or levels["bottom"] >= beam.top - 1e-6:
                continue
            width = _ceil(tray.width / cross["sine"] + 2 * T.TRAY_CLEARANCE)
            height = _ceil(tray.height + 2 * T.TRAY_CLEARANCE)
            centre = (levels["bottom"] + levels["top"]) / 2
            soffit = beam.top - levels["thickness"]
            record["openingBottom"] = centre - height / 2
            record["openingTop"] = centre + height / 2
            below = beam_bottom - (centre - height / 2)
            above = centre + height / 2 - soffit
            if below > 1e-6 or above > 1e-6:
                # Not an opening in the web: a notch through the bottom bars, or a cut into
                # the slab. No proposal; say how far to move the tray.
                record["fits"] = False
                drop = levels["top"] - beam_bottom
                if below > 1e-6:
                    notes.append(
                        f"{tray.id} at {beam.id}: the tray overlaps the beam by {drop:.0f} mm at "
                        f"its bottom; an opening would run {below:.0f} mm below the beam soffit "
                        f"(a notch through the bottom bars), none is proposed: lower the tray "
                        f"by {drop:.0f} mm to pass below the beam, or raise it into the web"
                    )
                elif height > soffit - beam_bottom + 1e-6:
                    notes.append(
                        f"{tray.id} at {beam.id}: the web below the slab ({soffit - beam_bottom:.0f}"
                        f" mm) is shallower than the opening ({height:.0f} mm), none is proposed: "
                        f"lower the tray by {drop:.0f} mm to pass below the beam"
                    )
                else:
                    notes.append(
                        f"{tray.id} at {beam.id}: an opening would reach {above:.0f} mm above the "
                        f"slab soffit, none is proposed: lower the tray by at least {above:.0f} "
                        f"mm (or by {drop:.0f} mm to pass below the beam)"
                    )
                continue
            record["fits"] = True
            seen[beam.id] = seen.get(beam.id, 0) + 1
            oid = f"PE-{tray.id}-{beam.id}" + (f"-{seen[beam.id]}" if seen[beam.id] > 1 else "")
            if oid in existing:
                continue
            openings.append({
                "id": oid, "host": beam.id, "kind": "opening", "shape": "rectangle",
                "width": width, "height": height,
                "position": {"distance": round(cross["distance"], 1),
                             "elevation": round(centre - beam_bottom, 1)},
                "service": f"{tray.width:g} x {tray.height:g} cable tray {tray.id}",
            })  # fmt: skip
    notes.append(
        f"tray openings: the tray across the beam + {T.TRAY_CLEARANCE:g} mm each side, to "
        f"{T.OPENING_STEP:g} mm; trays {T.TRAY_HEADROOM:g} mm below the slab soffit unless their "
        "bottom is given (SAEngine practice)"
    )
    return {"openings": openings, "crossings": crossings, "notes": notes}


def tray_checks(electrical: Any) -> list[dict[str, Any]]:
    """The fill of each tray whose cables' area is entered."""
    checks = []
    for tray in electrical.trays:
        if not tray.cableArea:
            continue
        capacity = T.TRAY_FILL * tray.width * tray.height
        checks.append({
            "name": f"{tray.id} fill", "demand": tray.cableArea, "capacity": capacity,
            "unit": "mm²", "utilisation": tray.cableArea / capacity,
            "ok": tray.cableArea <= capacity + 1e-9,
            "note": f"cables at most {T.TRAY_FILL:.0%} of {tray.width:g} x {tray.height:g} mm "
            "(from memory, to be checked against the tray maker's data)",
        })  # fmt: skip
    return checks

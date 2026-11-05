"""Precast concrete pieces (alpha 9 L1): the pieces of the building model, their handling and
erection stages and their connections, by the code pack's ``precast`` table
(:class:`saengine.codes.precast_tables.PrecastTable`). This module only computes; every value
and method is the pack's (the default pack: BNBC 2020 Part 6 Sec 6.10, with SAEngine practice
for the handling values Sec 6.10.9 asks for and does not give).

**Pieces.** An object type of 04 Objects with ``precast`` (:class:`saengine.library.objects.
PrecastPiece`) is made in a factory: every building model element of that type is one piece
(beams, columns), a wall is cut into panels no wider than ``unitWidth``, and a slab's outline
is covered by units of ``unitWidth`` spanning in ``spanDirection`` (the last unit cut to fit).
Pieces of one type with the same length and width share a mark (``<mark>-1``, ``-2``, ...).

**Section** of a piece (:func:`piece_section`): hollow-core units (width × depth less the
cores), double tees (flange and two stems), beams and columns by their profile (rectangle, T,
L, circle), wall panels by the wall's thickness (a sandwich panel's facing weighs, the
structural wythe carries).

**Handling** (method of the pack's ``handling`` group): the piece on two supports with
overhangs (its lifting inserts at stripping and erection, its ``supports`` or the inserts in
the yard and on the truck) under its weight × the stage's multiplier; the largest moment over
the section modulus of the tension face against c · f'ci^n / safety (at stripping f'ci, then
f'c). The load per insert = W × the stripping multiplier / (the pack's inserts of the rigging,
at most the inserts there are) / sin(sling angle), against the insert's working load (and its
ultimate load / the pack's insert safety where one is given).

**Erection** (``erection``): a hanging beam or double tee by Mast's method (``hangingBeam``):
zo = w / (12 E Iy L) (L1⁵/10 − a² L1³ + 3 a⁴ L1 + 6 a⁵/5), L1 = L − 2a, a the inserts' distance
from the ends; ei = L / sweepDivisor + insertTolerance (the whole sweep: on the safe side);
FS = yr / (zo + ei), yr the height of the inserts above the centroid. A column standing on
its temporary base: q · b · H² / 2 against the base moment entered; a wall panel: the
horizontal force on each of its two braces at their height.

**Connections**: the bearing (``bearing``: ``spanRatio`` or ``netBearing``), dowels
(``dowel``: ``shearFriction`` by :func:`saengine.design.rc_detailing.shear_friction`, or
``dowelAction``), the bearing on a precast column's corbel (the corbel designed by
:func:`saengine.design.corbels.corbel_checks`, the pack's corbel method) and welded plates
(the pack's fillet welds, :func:`saengine.design.steel_connections.fillet_capacity_per_mm`;
the embedded plates' anchorage is the anchors' design, not repeated here). The shear of a
floor unit's or beam's bearing is its gravity reaction by the pack's gravity combinations
(self-weight, topping, the superimposed dead and live loads of the piece or its slab's area
load) unless one is entered; the tension the pack's share of it unless one is entered.

**Integrity** (``integrity``, ``tieForces``): columns' dowels at their base against the
nominal tension per gross area, wall panels' ties; the diaphragm and bearing-wall ties as
requirements in the notes.

Units: mm, N inside; kN, kN·m and MPa in the rows.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.codes import context as code_context

__all__ = [
    "Piece",
    "Section",
    "bearing_checks",
    "connection_checks",
    "covered",
    "erection_checks",
    "handling_checks",
    "integrity_checks",
    "piece_checks",
    "piece_section",
    "pieces_of",
    "project_precast",
    "report_section",
    "rules",
    "stage_moments",
]

TABLE = "precast"
#: Product widths when the type gives none (SAEngine practice: the usual widths of the units).
UNIT_WIDTH = {"hollowCore": 1200.0, "doubleTee": 2400.0}
#: A double tee's flange and stem when the type gives none (SAEngine practice) [mm].
DT_FLANGE, DT_STEM = 50.0, 150.0
DENSITY = 2400.0  # kg/m³ of a concrete with none given (normal weight)


def rules(pack: Any = None) -> Any | None:
    """The pack's ``precast`` table, or None when it has none (not covered)."""
    target = pack if pack is not None else code_context.current()
    return target.table(TABLE) if target.has(TABLE) else None


def covered(pack: Any = None) -> bool:
    try:
        return rules(pack) is not None
    except Exception:  # noqa: BLE001 - no pack in force
        return False


def _check(name: str, demand: float, capacity: float, unit: str, note: str = "", **kw: Any):
    from saengine.design.check import _check as row

    return row(name, demand, capacity, unit, kw.get("combination"), note, False, kw.get("u"))


def _info(name: str, note: str) -> dict[str, Any]:
    """A row that is not a check (a requirement or why a check is not made)."""
    return {
        "name": name,
        "demand": None,
        "capacity": None,
        "unit": "",
        "utilisation": None,
        "combination": None,
        "ok": None,
        "note": note,
        "flag": False,
    }


# ─────────────────────────────────────── sections ───────────────────────────────────────


@dataclass
class Section:
    """The section of a piece as it is handled (bending about the horizontal axis): area
    [mm²], depth h and width b [mm], centroid yb above the bottom [mm], I about the horizontal
    and Iy about the vertical axis through the centroid [mm⁴]."""

    area: float
    h: float
    b: float
    yb: float
    inertia: float
    inertia_y: float
    label: str
    weight_area: float = 0.0  # extra weight carried, as concrete area (a sandwich's facing)
    notes: list[str] = field(default_factory=list)

    def modulus(self, top: bool) -> float:
        """Section modulus of the top (``top``) or bottom face [mm³]."""
        c = (self.h - self.yb) if top else self.yb
        return self.inertia / c if c > 0 else math.inf


def _rect(b: float, h: float, y0: float = 0.0, x0: float = 0.0) -> tuple[float, ...]:
    """(area, centroid y, centroid x, own Ix, own Iy) of a rectangle with its bottom at y0."""
    return (b * h, y0 + h / 2, x0, b * h**3 / 12, h * b**3 / 12)


def _combine(parts: Sequence[tuple[float, ...]]) -> tuple[float, float, float, float]:
    """(area, yb, I, Iy) of rectangles (area, y, x, Ix, Iy) about the composite centroid
    (x symmetric about 0)."""
    area = sum(p[0] for p in parts)
    yb = sum(p[0] * p[1] for p in parts) / area
    inertia = sum(p[3] + p[0] * (p[1] - yb) ** 2 for p in parts)
    inertia_y = sum(p[4] + p[0] * p[2] ** 2 for p in parts)
    return area, yb, inertia, inertia_y


def piece_section(obj: Any, piece: Any | None = None, width: float | None = None) -> Section:
    """The section of a precast type (see the module notes). ``width``: a floor unit's or
    wall panel's own width when it is cut to fit. Raises ``ValueError`` for a profile it
    cannot take."""
    piece = piece if piece is not None else obj.precast
    element = piece.element
    notes: list[str] = []
    if element == "hollowCore":
        b = float(width or piece.unitWidth or UNIT_WIDTH["hollowCore"])
        h = float(obj.thickness)
        n = int(piece.cores or 0)
        d = float(piece.coreDiameter or 0.0)
        if n and (d <= 0 or d >= h):
            raise ValueError(f"{obj.id}: core diameter {d:g} mm does not fit a {h:g} mm unit")
        if not n:
            notes.append("no cores entered: taken as a solid unit")
        core = math.pi * d * d / 4
        xs = [-b / 2 + (k + 0.5) * b / n for k in range(n)] if n else []
        area = b * h - n * core
        inertia = b * h**3 / 12 - n * math.pi * d**4 / 64
        inertia_y = h * b**3 / 12 - sum(math.pi * d**4 / 64 + core * x * x for x in xs)
        label = f"hollow-core {b:.0f} × {h:.0f}" + (f", {n} cores Ø{d:.0f}" if n else "")
        return Section(area, h, b, h / 2, inertia, inertia_y, label, notes=notes)
    if element == "doubleTee":
        b = float(width or piece.unitWidth or UNIT_WIDTH["doubleTee"])
        h = float(obj.thickness)
        tf = float(piece.flangeThickness or DT_FLANGE)
        bw = float(piece.stemWidth or DT_STEM)
        s = float(piece.stemSpacing or b / 2)
        if tf >= h:
            raise ValueError(f"{obj.id}: the flange {tf:g} mm is not thinner than the unit {h:g}")
        if piece.flangeThickness is None or piece.stemWidth is None:
            notes.append(f"flange {tf:.0f} mm and stems {bw:.0f} mm taken (not entered)")
        stem = h - tf
        parts = [_rect(b, tf, stem), _rect(bw, stem, 0, -s / 2), _rect(bw, stem, 0, s / 2)]
        area, yb, inertia, inertia_y = _combine(parts)
        label = f"double tee {b:.0f} × {h:.0f}, flange {tf:.0f}, stems {bw:.0f} at {s:.0f}"
        return Section(area, h, b, yb, inertia, inertia_y, label, notes=notes)
    if element == "wallPanel":
        t = float(obj.thickness)
        b = float(width or 1.0)
        facing = float(piece.facing or 0.0)
        label = f"wall panel {t:.0f} mm" + (
            f" + {piece.insulation:.0f} insulation + {facing:.0f} facing" if facing else ""
        )
        return Section(
            b * t, t, b, t / 2, b * t**3 / 12, t * b**3 / 12, label, weight_area=b * facing
        )
    profile = obj.profile
    shape = getattr(profile, "shape", "")
    if shape == "rectangle":
        b, h = float(profile.xDim), float(profile.yDim)
        return Section(b * h, h, b, h / 2, b * h**3 / 12, h * b**3 / 12, f"{b:.0f} × {h:.0f}")
    if shape == "circle":
        r = float(profile.radius)
        i = math.pi * r**4 / 4
        return Section(math.pi * r * r, 2 * r, 2 * r, r, i, i, f"Ø{2 * r:.0f}")
    if shape == "T":
        h, bf, tw, tf = (
            float(profile.depth),
            float(profile.flangeWidth),
            float(profile.webThickness),
            float(profile.flangeThickness),
        )
        parts = [_rect(bf, tf, h - tf), _rect(tw, h - tf)]
        area, yb, inertia, inertia_y = _combine(parts)
        return Section(area, h, bf, yb, inertia, inertia_y, f"T {bf:.0f} × {h:.0f}")
    if shape == "L":
        h, b, t = float(profile.depth), float(profile.width), float(profile.thickness)
        # an L ledger: the leg t wide over the full depth and the ledge b wide at the bottom
        parts = [_rect(b, t), _rect(t, h - t, t, (t - b) / 2)]
        area, yb, inertia, inertia_y = _combine(parts)
        notes.append("Iy of the L about its own vertical axis is approximate (symmetric parts)")
        return Section(area, h, b, yb, inertia, inertia_y, f"L {b:.0f} × {h:.0f}", notes=notes)
    raise ValueError(f"{obj.id}: a precast {element} of profile '{shape}' is not supported")


# ─────────────────────────────────────── pieces ───────────────────────────────────────


@dataclass
class Piece:
    """One mark of precast pieces: the type, its element, its length and width [mm], how many
    and which building model elements they come from."""

    mark: str
    type: str
    element: str
    length: float
    width: float
    count: int
    elements: list[str] = field(default_factory=list)
    height: float | None = None  # wall panels: their height [mm]
    span: float | None = None  # floor units and beams: their span between supports [mm]
    story_elevation: float | None = None
    slab: Any = None  # a floor unit's building model slab (its area load)


def _extent(points: Iterable[Sequence[float]], axis: int) -> tuple[float, float]:
    values = [float(p[axis]) for p in points]
    return min(values), max(values)


def pieces_of(building: Any, objects: Any) -> list[Piece]:
    """The marks of the precast pieces of the building model (see the module notes)."""
    types = {o.id: o for o in getattr(objects, "objects", []) if getattr(o, "precast", None)}
    found: dict[tuple[str, float, float, float], Piece] = {}
    for e in getattr(building, "elements", []):
        obj = types.get(getattr(e, "type", None))
        if obj is None:
            continue
        piece = obj.precast
        rows: list[tuple[float, float, float | None, float | None, int]] = []
        elevation = None
        slab = None
        if e.kind == "beam":
            length = math.dist(e.start, e.end)
            rows.append((length, 0.0, None, length, 1))
            elevation = float(e.elevation)
        elif e.kind == "column":
            rows.append((float(e.top) - float(e.bottom), 0.0, None, None, 1))
            elevation = float(e.bottom)
        elif e.kind == "wall":
            length = math.dist(e.start, e.end)
            height = float(e.top) - float(e.bottom)
            n = max(1, math.ceil(length / piece.unitWidth - 1e-9)) if piece.unitWidth else 1
            rows.append((length / n, 0.0, height, None, n))
            elevation = float(e.bottom)
        elif e.kind == "slab":
            along = 0 if piece.spanDirection == "x" else 1
            lo, hi = _extent(e.boundary, along)
            a, b = _extent(e.boundary, 1 - along)
            span, across = hi - lo, b - a
            w = float(piece.unitWidth or UNIT_WIDTH.get(piece.element, 1200.0))
            full = int(across // w)
            rest = across - full * w
            if full:
                rows.append((span, w, None, span, full))
            if rest > 1.0:
                rows.append((span, rest, None, span, 1))
            elevation = float(e.elevation)
            slab = e
        else:
            continue
        for length, width, height, span, count in rows:
            length = float(piece.length or length)
            key = (obj.id, round(length, -1), round(width, -1), round(height or 0.0, -1))
            item = found.get(key)
            if item is None:
                item = Piece(
                    mark="",
                    type=obj.id,
                    element=piece.element,
                    length=length,
                    width=width,
                    count=0,
                    height=height,
                    span=float(piece.length or span) if span is not None else None,
                    story_elevation=elevation,
                    slab=slab,
                )
                found[key] = item
            item.count += count
            item.elements.append(e.id)
    out: list[Piece] = []
    by_type: dict[str, int] = {}
    for key in sorted(found, key=lambda k: (k[0], -k[1], -k[2])):
        item = found[key]
        n = by_type[item.type] = by_type.get(item.type, 0) + 1
        prefix = types[item.type].precast.mark or item.type
        item.mark = f"{prefix}-{n}"
        out.append(item)
    return out


# ─────────────────────────────────────── loads ───────────────────────────────────────


def _density(material: Any) -> float:
    return float(getattr(getattr(material, "mechanical", None), "density", None) or DENSITY)


def _fc(material: Any) -> float:
    concrete = getattr(material, "concrete", None)
    if concrete is None:
        raise ValueError("the piece's material is not a concrete")
    return float(concrete.fc)


def _fy(materials: Any, material_id: str | None) -> float | None:
    found = materials.get(material_id) if materials is not None and material_id else None
    steel = getattr(found, "steel", None)
    return float(steel.fy) if steel is not None else None


def self_weight(section: Section, density: float) -> float:
    """The piece's weight per length [N/mm]."""
    return (section.area + section.weight_area) * 1e-9 * density * 9.80665


def gravity_reaction(
    piece: Piece, obj: Any, section: Section, density: float, settings: Any = None
) -> tuple[float, str]:
    """(Vu [N], basis) at each end of a floor unit or beam on its span: the largest of the
    pack's gravity combinations on its self-weight, topping, superimposed dead and live loads."""
    span = float(piece.span or piece.length)
    p = obj.precast
    w_self = self_weight(section, density)  # N/mm
    w_top = p.topping * section.b * 1e-9 * density * 9.80665  # N/mm
    sd = p.superimposedDead
    live = p.live
    basis = []
    if piece.element in ("hollowCore", "doubleTee"):
        width = section.b * 1e-3  # m
        if (sd is None or live is None) and settings is not None and piece.slab is not None:
            load = _area_load(settings, piece.slab)
            if load is not None:
                from saengine.library.settings import partition_case

                case = partition_case(settings)
                sd = load.superimposed(case) if sd is None else sd
                live = load.floor_live(case) if live is None else live
                basis.append(f"area load {load.id}")
        sd_line, live_line = (sd or 0.0) * width, (live or 0.0) * width  # kN/m = N/mm
    else:
        sd_line, live_line = sd or 0.0, live or 0.0
    dead = w_self + w_top + sd_line
    best, name = 0.0, ""
    for combo in code_context.table("combinations").gravity:
        cd = float(combo.factors.get("D", 0.0))
        cl = float(combo.factors.get("L", 0.0))
        w = cd * dead + cl * live_line
        if w > best:
            best, name = w, combo.name
    vu = best * span / 2
    basis.insert(
        0,
        f"{name}: D {dead:.2f} kN/m (self {w_self:.2f}, topping {w_top:.2f}, SD {sd_line:.2f}), "
        f"L {live_line:.2f} kN/m over {span / 1e3:.2f} m",
    )
    return vu, "; ".join(basis)


def _area_load(settings: Any, slab: Any) -> Any | None:
    loads = {a.id: a for a in getattr(settings, "areaLoads", [])}
    chosen = getattr(slab, "areaLoad", None) or getattr(settings, "floorLoad", None)
    return loads.get(chosen)


# ─────────────────────────────────────── handling ───────────────────────────────────────


def stage_moments(length: float, w: float, x1: float, x2: float, points: int = 201):
    """(largest sagging, largest hogging) moment [N·mm] of a piece of ``length`` under ``w``
    [N/mm] on supports at ``x1`` < ``x2`` (overhangs both ends); hogging as a positive number."""
    if not 0 <= x1 < x2 <= length:
        raise ValueError("supports must lie on the piece, the first before the second")
    s = x2 - x1
    r1 = w * length * (x2 - length / 2) / s
    r2 = w * length - r1
    sag = hog = 0.0
    xs = [length * k / (points - 1) for k in range(points)] + [x1, x2]
    for x in xs:
        m = r1 * max(0.0, x - x1) + r2 * max(0.0, x - x2) - w * x * x / 2
        sag, hog = max(sag, m), max(hog, -m)
    return sag, hog


def _positions(piece_type: Any, uses: tuple[str, ...]) -> list[float]:
    return sorted(i.position for i in piece_type.inserts if i.use in uses)


def handling_checks(
    obj: Any, piece: Piece, section: Section, fc: float, density: float, pack: Any = None
) -> list[dict[str, Any]]:
    """The handling rows of one mark: concrete tension at stripping, in the yard, on the truck
    and at erection, and the load on the lifting inserts."""
    table = rules(pack)
    rule = getattr(table, "handling", None)
    if rule is None:
        return [_info("Handling", "not covered by the code pack (no handling values)")]
    p = obj.precast
    length = float(piece.length)  # a wall panel: along the wall, lifted flat
    rows: list[dict[str, Any]] = []
    fci = float(p.stripStrength or rule.stripShare * fc)
    t = rule.tension

    def allowed(f: float) -> float:
        return t.coefficient * f**t.exponent / t.safety

    w0 = self_weight(section, density)  # N/mm
    weight = w0 * length / 1e3  # kN
    lifting = _positions(p, ("lifting", "both"))
    erection = _positions(p, ("erection", "both")) or lifting
    stored = sorted(p.supports) or lifting
    strip = rule.stripping.get(p.mouldFinish) or max(rule.stripping.values())
    stages = (
        ("stripping", strip, lifting, fci, "f'ci"),
        ("yard storage", rule.yard, stored, fc, "f'c"),
        ("transport", rule.transport, stored, fc, "f'c"),
        ("erection", rule.erection, erection, fc, "f'c"),
    )
    if piece.element in ("column", "wallPanel"):
        note_axis = "lifted flat from the mould"
    else:
        note_axis = "lifted as it lies"
    for name, factor, at, strength, symbol in stages:
        if len(at) < 2:
            rows.append(
                _info(f"Handling, {name}", "fewer than two supports or inserts: not checked")
            )
            continue
        x1, x2 = min(at), max(at)
        if x2 > length:
            rows.append(
                _info(
                    f"Handling, {name}",
                    f"an insert or support lies beyond the piece's {length:.0f} mm: not checked",
                )
            )
            continue
        sag, hog = stage_moments(length, w0 * factor, x1, x2)
        stress = max(sag / section.modulus(False), hog / section.modulus(True))
        limit = allowed(strength)
        rows.append(
            _check(
                f"Handling, {name}: concrete tension",
                stress,
                limit,
                "MPa",
                f"{factor:g} × W = {factor * weight:.1f} kN on {x1:.0f} and {x2:.0f} mm "
                f"({note_axis}); M+ {sag / 1e6:.1f}, M- {hog / 1e6:.1f} kN·m; allowed "
                f"{t.coefficient:g} {symbol}^{t.exponent:g} / {t.safety:g} with {symbol} = "
                f"{strength:.1f} MPa ({_source(table, 'handling')})",
            )
        )
    lifters = [i for i in p.inserts if i.use in ("lifting", "both")]
    if lifters:
        n = int(min(rule.inserts.get(p.rigging, 2), len(lifters)))
        angle = math.sin(math.radians(p.slingAngle))
        load = strip * weight / n / angle
        wll = min(i.workingLoad for i in lifters)
        rows.append(
            _check(
                "Lifting inserts: load per insert",
                load,
                wll,
                "kN",
                f"{strip:g} × W {weight:.1f} kN / {n} inserts ({p.rigging}) / sin {p.slingAngle:g}°"
                f" against the working load limit ({_source(table, 'handling')})",
            )
        )
        tested = [i.ultimateLoad for i in lifters if i.ultimateLoad]
        if tested:
            ultimate = min(tested)
            rows.append(
                _check(
                    "Lifting inserts: safety on the ultimate load",
                    rule.insertSafety * load,
                    ultimate,
                    "kN",
                    f"{rule.insertSafety:g} × {load:.1f} kN at most the ultimate load",
                )
            )
    else:
        rows.append(_info("Lifting inserts", "none entered: not checked"))
    return rows


def _source(table: Any, key: str) -> str:
    return str(getattr(table, "sources", {}).get(key) or getattr(table, "source", "")).split(":")[0]


# ─────────────────────────────────────── erection ───────────────────────────────────────


def hanging_beam(
    length: float, w: float, a: float, e_mod: float, inertia_y: float, yr: float, rule: Any
) -> dict[str, float]:
    """Mast's lateral stability of a beam hanging from inserts ``a`` [mm] from its ends:
    ``{"zo", "ei", "fs"}`` (``w`` [N/mm], E [MPa], Iy [mm⁴], ``yr`` [mm])."""
    l1 = length - 2 * a
    zo = (
        w
        / (12 * e_mod * inertia_y * length)
        * (l1**5 / 10 - a * a * l1**3 + 3 * a**4 * l1 + 6 * a**5 / 5)
    )
    ei = length / rule.sweepDivisor + rule.insertTolerance
    return {"zo": zo, "ei": ei, "fs": yr / (zo + ei) if zo + ei > 0 else math.inf}


def erection_checks(
    obj: Any, piece: Piece, section: Section, fc: float, density: float, pack: Any = None
) -> list[dict[str, Any]]:
    """The erection rows of one mark (see the module notes)."""
    table = rules(pack)
    rule = getattr(table, "erection", None)
    if rule is None:
        return [_info("Erection", "not covered by the code pack (no erection values)")]
    p = obj.precast
    rows: list[dict[str, Any]] = []
    q = float(p.erectionWind if p.erectionWind is not None else rule.windPressure)  # kPa
    if piece.element in ("beam", "doubleTee") and rule.hanging is not None:
        lifting = _positions(p, ("lifting", "erection", "both"))
        if len(lifting) >= 2:
            from saengine.design.rc_detailing import concrete_modulus

            a = min(lifting[0], piece.length - lifting[-1])
            e_mod, _ = concrete_modulus(fc, density)
            found = hanging_beam(
                piece.length,
                self_weight(section, density),
                max(a, 0.0),
                e_mod,
                section.inertia_y,
                section.h - section.yb,
                rule.hanging,
            )
            rows.append(
                _check(
                    "Erection: lateral stability while hanging",
                    rule.hanging.safety,
                    found["fs"],
                    "",
                    f"FS = yr / (zo + ei) = {section.h - section.yb:.0f} / ({found['zo']:.1f} + "
                    f"{found['ei']:.1f}) = {found['fs']:.2f}, at least {rule.hanging.safety:g}; "
                    f"inserts {a:.0f} mm from the ends ({_source(table, 'erection')})",
                )
            )
        else:
            rows.append(_info("Erection: hanging stability", "fewer than two inserts"))
    if piece.element == "column":
        height = piece.length / 1e3  # m
        face = section.b / 1e3
        moment = q * face * height * height / 2  # kN·m
        if p.baseMoment:
            rows.append(
                _check(
                    "Erection: free-standing column on its temporary base",
                    rule.overturningSafety * moment,
                    float(p.baseMoment),
                    "kN·m",
                    f"{rule.overturningSafety:g} × q b H²/2 = {rule.overturningSafety:g} × {q:g} "
                    f"× {face:.2f} × {height:.2f}²/2 at most the base moment",
                )
            )
        else:
            rows.append(
                _info(
                    "Erection: free-standing column",
                    f"wind moment at the base {moment:.1f} kN·m ({q:g} kPa): enter the temporary "
                    "base's moment to check it",
                )
            )
    if piece.element == "wallPanel":
        height = float(piece.height or 0.0)
        hb = float(p.braceHeight or 2 * height / 3)
        if height > 0 and hb > 0:
            force = q * (piece.length / 1e3) * (height / 1e3) * (height / 2) / hb / 2  # kN
            if p.braceCapacity:
                rows.append(
                    _check(
                        "Erection: panel brace (horizontal force)",
                        rule.overturningSafety * force,
                        float(p.braceCapacity),
                        "kN",
                        f"two braces at {hb:.0f} mm: q A (H/2) / hb / 2, {q:g} kPa, × "
                        f"{rule.overturningSafety:g}",
                    )
                )
            else:
                rows.append(
                    _info(
                        "Erection: panel braces",
                        f"{force:.1f} kN horizontal on each of two braces at {hb:.0f} mm "
                        f"({q:g} kPa)",
                    )
                )
    return rows


# ─────────────────────────────────────── connections ───────────────────────────────────────


def _member_class(element: str) -> str:
    return "slab" if element == "hollowCore" else "stemmed"


def _support_kind(element: str) -> tuple[str, str]:
    """(a1 kind, a2/a3 kind) of the netBearing method."""
    if element == "hollowCore":
        return "linear", "linear"
    if element == "doubleTee":
        return "ribbed", "concentrated"
    return "concentrated", "concentrated"


def _fcd(fc: float) -> tuple[float, str]:
    from saengine.design import design_strength

    if design_strength.rules() is not None:
        return design_strength.fcd(fc), "fcd of the code pack"
    return fc / 1.5, "fcd = f'c / 1.5 (the code pack gives no partial factors)"


def bearing_checks(
    c: Any,
    piece: Piece,
    section: Section,
    fc: float,
    vu: float,
    cover: float | None,
    pack: Any = None,
) -> list[dict[str, Any]]:
    """The bearing rows of a connection (``vu`` [N])."""
    table = rules(pack)
    rule = getattr(table, "bearing", None)
    if rule is None:
        return [_info(f"{c.id}: bearing", "not covered by the code pack")]
    if c.bearingLength is None:
        return [_info(f"{c.id}: bearing", "no bearing length entered: not checked")]
    span = float(piece.span or piece.length)
    width = float(c.bearingWidth or section.b)
    given = float(c.bearingLength)
    src = _source(table, "bearing")
    rows = []
    if rule.method == "spanRatio":
        least = rule.minimum.get(_member_class(piece.element)) or max(rule.minimum.values())
        need = max(span / rule.spanDivisor, least)
        rows.append(
            _check(
                f"{c.id}: bearing length",
                need,
                given,
                "mm",
                f"at least ln/{rule.spanDivisor:g} = {span / rule.spanDivisor:.0f} and {least:g} "
                f"mm ({src})",
            )
        )
        phi = float(code_context.table("factors").phi.get("bearing") or 0.65)
        area = max(given - rule.padSetback, 0.0) * width
        cap = phi * rule.stressFactor * fc * area
        rows.append(
            _check(
                f"{c.id}: bearing stress",
                vu / 1e3,
                cap / 1e3,
                "kN",
                f"φ {rule.stressFactor:g} f'c A1, φ = {phi:g}, A1 = ({given:.0f} − "
                f"{rule.padSetback:g}) × {width:.0f} mm",
            )
        )
        return rows
    # netBearing
    fcd, how = _fcd(fc)
    kind1, kind2 = _support_kind(piece.element)
    sigma = vu / (width * given) / fcd if fcd > 0 else 0.0
    band = 0 if sigma <= rule.stressBands[0] else 1 if sigma <= rule.stressBands[1] else 2
    frd = rule.strength.get(c.bedding, min(rule.strength.values())) * fcd
    a1 = max(vu / (width * frd), rule.a1Minimum[kind1][band])
    material = {"steel": "steel", "masonry": "masonry"}.get(c.support) or (
        "concreteHigh" if fc >= rule.highStrength else "concreteLow"
    )
    a2 = rule.a2.get(f"{material}.{kind2}", (0.0, 0.0, 0.0))[band]
    a3 = rule.a3.get(c.endBars, (0.0, 0.0))[0 if kind2 == "linear" else 1]
    if c.endBars in rule.a3CoverAtLeast and cover is not None:
        a3 = max(a3, cover)
    tol_key = "precast" if c.support in ("precast", "steel") else "castInSitu"
    div, add, lo, hi = rule.supportTolerance.get(tol_key, (1200.0, 0.0, 10.0, 30.0))
    da2 = min(max(span / div + add, lo), hi)
    da3 = span / rule.memberTolerance
    need = a1 + a2 + a3 + math.hypot(da2, da3)
    rows.append(
        _check(
            f"{c.id}: nominal bearing length",
            need,
            given,
            "mm",
            f"a = a1 + a2 + a3 + √(Δa2² + Δa3²) = {a1:.0f} + {a2:.0f} + {a3:.0f} + "
            f"√({da2:.0f}² + {da3:.0f}²); a1 = FEd/(b1 fRd), fRd = {frd:.1f} MPa ({c.bedding}), "
            f"σEd/fcd = {sigma:.2f}, {how} ({src})",
        )
    )
    return rows


def dowel_checks(
    c: Any, fc: float, fy: float | None, vu: float, nu: float, area: float, pack: Any = None
) -> list[dict[str, Any]]:
    """Dowels across a joint (``vu``, ``nu`` [N], ``area`` the joint's concrete [mm²])."""
    table = rules(pack)
    rule = getattr(table, "dowel", None)
    if rule is None:
        return [_info(f"{c.id}: dowels", "not covered by the code pack")]
    if not c.dowels or not c.dowelDia or fy is None:
        return [_info(f"{c.id}: dowels", "no dowels, diameter or dowel steel entered")]
    bar = math.pi * c.dowelDia**2 / 4
    src = _source(table, "dowel")
    if rule.method == "shearFriction":
        from saengine.design.rc_detailing import shear_friction

        found = shear_friction(c.dowels * bar, fy, fc, area, c.surface, tension=nu)
        if found is None:
            return [_info(f"{c.id}: dowels", "the code pack has no shear transfer rules")]
        return [
            _check(
                f"{c.id}: dowels, shear across the joint",
                vu / 1e3,
                found.phi_vn / 1e3,
                "kN",
                f"{c.dowels} Ø{c.dowelDia:g}; {found.note}",
            )
        ]
    fcd = fc / rule.gammaC
    fyd = fy / rule.gammaS
    eps = rule.epsilon * math.sqrt(fcd / fyd)
    k = eps * rule.alpha0 * c.eccentricity / c.dowelDia
    alpha_e = math.sqrt(1 + k * k) - k
    each = rule.alpha0 * alpha_e * c.dowelDia**2 * math.sqrt(fcd * fyd) / rule.gammaRd
    each = min(each, rule.shearYield * fyd * bar)
    return [
        _check(
            f"{c.id}: dowels, dowel action",
            vu / 1e3,
            c.dowels * each / 1e3,
            "kN",
            f"{c.dowels} Ø{c.dowelDia:g}: F = α0 αe Φ² √(fcd fyd) / γRd, α0 = {rule.alpha0:g}, αe "
            f"= {alpha_e:.2f} (e = {c.eccentricity:g} mm), fcd = {fcd:.1f}, fyd = {fyd:.0f} MPa, "
            f"γRd = {rule.gammaRd:g}; at most {rule.shearYield:g} fyd As ({src})",
        )
    ]


def corbel_rows(
    c: Any, vu: float, types: dict[str, Any], materials: Any, pack: Any = None
) -> list[dict[str, Any]]:
    """The supporting column type's corbel under this connection's shear (the corbel method)."""
    table = rules(pack)
    if getattr(getattr(table, "connections", None), "corbel", None) is None:
        return [_info(f"{c.id}: corbel", "not covered by the code pack")]
    column = types.get(c.corbelType or "")
    corbels = getattr(getattr(column, "precast", None), "corbels", None) or []
    if column is None or c.corbel is None or c.corbel >= len(corbels):
        return [_info(f"{c.id}: corbel", "the corbel column type or its corbel is not found")]
    from saengine.design.corbels import CorbelDemand, corbel_checks

    found = corbels[c.corbel]
    material = materials.get(column.material) if materials is not None else None
    fc = _fc(material)
    reinforcement = getattr(column, "reinforcement", None)
    fy = _fy(materials, getattr(reinforcement, "material", None))
    if fy is None:
        return [_info(f"{c.id}: corbel", f"{column.id} has no reinforcement material (fy)")]
    label = f"{c.id}: corbel {found.face} of {column.id}"
    return corbel_checks(found.corbel, fc, fy, CorbelDemand(vu, None), label)


def weld_rows(c: Any, vu: float, nu: float, pack: Any = None) -> list[dict[str, Any]]:
    table = rules(pack)
    if getattr(getattr(table, "connections", None), "weldedPlate", None) is None:
        return [_info(f"{c.id}: welded plate", "not covered by the code pack")]
    if not c.weldSize or not c.weldLength:
        return [_info(f"{c.id}: welded plate", "no weld size or length entered")]
    from saengine.design.steel_connections import fillet_capacity_per_mm

    cap = fillet_capacity_per_mm(c.weldSize, c.electrode) * c.weldLength
    demand = math.hypot(vu, nu)
    return [
        _check(
            f"{c.id}: welded plate, fillet welds",
            demand / 1e3,
            cap / 1e3,
            "kN",
            f"{c.weldSize:g} mm fillet × {c.weldLength:.0f} mm, FEXX {c.electrode:g} MPa, the "
            "code pack's weld strength; √(V² + N²); the embedded plates' anchorage is designed "
            "as anchors (not repeated here)",
        )
    ]


def connection_checks(
    obj: Any,
    piece: Piece,
    section: Section,
    material: Any,
    materials: Any,
    types: dict[str, Any],
    settings: Any = None,
    pack: Any = None,
) -> list[dict[str, Any]]:
    """The rows of every connection of a mark (see the module notes)."""
    table = rules(pack)
    p = obj.precast
    rows: list[dict[str, Any]] = []
    fc = _fc(material)
    density = _density(material)
    reinforcement = getattr(obj, "reinforcement", None)
    cover = getattr(reinforcement, "cover", None)
    gravity: tuple[float, str] | None = None
    for c in p.connections:
        if c.shear is not None:
            vu, basis = float(c.shear) * 1e3, "shear entered"
        elif piece.element in ("hollowCore", "doubleTee", "beam"):
            if gravity is None:
                gravity = gravity_reaction(piece, obj, section, density, settings)
            vu, basis = gravity
        else:
            vu, basis = 0.0, "no shear entered"
        share = table.connections.tensionShare
        nu = float(c.tension) * 1e3 if c.tension is not None else share * vu
        rows.append(
            _info(
                f"{c.id}: demand",
                f"Vu = {vu / 1e3:.1f} kN ({basis}); Nu = {nu / 1e3:.1f} kN"
                + ("" if c.tension is not None else f" ({share:g} Vu)"),
            )
        )
        if c.kind in ("bearing", "corbelBearing"):
            rows += bearing_checks(c, piece, section, fc, vu, cover, pack)
        if c.kind == "corbelBearing":
            rows += corbel_rows(c, vu, types, materials, pack)
        if c.kind == "dowel":
            fy = _fy(materials, c.dowelMaterial or getattr(reinforcement, "material", None))
            if piece.element in ("column", "wallPanel"):
                area = section.area
            else:
                area = float(c.bearingLength or section.h) * float(c.bearingWidth or section.b)
            rows += dowel_checks(c, fc, fy, vu, nu, area, pack)
        if c.kind == "weldedPlate":
            rows += weld_rows(c, vu, nu, pack)
    if not p.connections:
        rows.append(_info("Connections", "none entered"))
    return rows


def integrity_checks(
    obj: Any, piece: Piece, section: Section, materials: Any, pack: Any = None
) -> list[dict[str, Any]]:
    """Structural integrity ties of a mark (``tieForces``)."""
    table = rules(pack)
    rule = getattr(table, "integrity", None)
    if rule is None:
        return []
    p = obj.precast
    reinforcement = getattr(obj, "reinforcement", None)
    base = [c for c in p.connections if c.kind == "dowel" and c.at in ("base", "both")]
    src = _source(table, "integrity")
    if piece.element == "column":
        need = rule.columnTension * section.area / 1e3  # kN
        given = 0.0
        for c in base:
            fy = _fy(materials, c.dowelMaterial or getattr(reinforcement, "material", None))
            if c.dowels and c.dowelDia and fy:
                given += c.dowels * math.pi * c.dowelDia**2 / 4 * fy / 1e3
        if not base:
            return [
                _info(
                    "Integrity: column tension",
                    f"{need:.0f} kN needed ({rule.columnTension:g} "
                    f"Ag); no dowels at the base entered ({src})",
                )
            ]
        return [
            _check(
                "Integrity: column tension at the base",
                need,
                given,
                "kN",
                f"nominal As fy of the base dowels at least {rule.columnTension:g} Ag ({src})",
            )
        ]
    if piece.element == "wallPanel":
        ties = sum(c.dowels for c in base)
        rows = [
            _check(
                "Integrity: ties per panel",
                rule.panelTies,
                ties,
                "",
                f"at least {rule.panelTies} ties of {rule.panelTieForce:g} kN each ({src})",
            )
        ]
        for c in base:
            fy = _fy(materials, c.dowelMaterial or getattr(reinforcement, "material", None))
            if c.dowels and c.dowelDia and fy:
                each = math.pi * c.dowelDia**2 / 4 * fy / 1e3
                rows.append(
                    _check(
                        f"{c.id}: tie strength",
                        rule.panelTieForce,
                        each,
                        "kN",
                        f"nominal As fy of each tie ({src})",
                    )
                )
        return rows
    return [
        _info(
            "Integrity: diaphragm connections",
            f"the connections to the members it braces at least {rule.diaphragm:g} kN/m ({src})",
        )
    ]


def piece_checks(
    obj: Any,
    piece: Piece,
    materials: Any,
    types: dict[str, Any],
    settings: Any = None,
    pack: Any = None,
) -> dict[str, Any]:
    """Every row of one mark: ``{"mark", "type", "element", "count", "length", "width",
    "section", "weight" (kN per piece), "volume" (m³ per piece), "rows", "ok", "notes"}``."""
    material = materials.get(obj.material) if materials is not None else None
    notes: list[str] = []
    out: dict[str, Any] = {
        "mark": piece.mark,
        "type": piece.type,
        "element": piece.element,
        "count": piece.count,
        "length": round(piece.length, 0),
        "width": round(piece.width, 0),
        "elements": list(piece.elements),
        "rows": [],
        "notes": notes,
    }
    try:
        fc = _fc(material)
        section = piece_section(obj, obj.precast, piece.width or None)
    except ValueError as error:
        notes.append(str(error))
        out["ok"] = None
        return out
    if piece.element == "wallPanel":
        section = piece_section(obj, obj.precast, piece.height or 1.0)
    notes += section.notes
    density = _density(material)
    run = float(piece.length)
    out["section"] = section.label
    out["volume"] = round((section.area + section.weight_area) * run * 1e-9, 4)
    out["weight"] = round(self_weight(section, density) * run / 1e3, 2)
    rows: list[dict[str, Any]] = []
    rows += handling_checks(obj, piece, section, fc, density, pack)
    rows += erection_checks(obj, piece, section, fc, density, pack)
    rows += connection_checks(obj, piece, section, material, materials, types, settings, pack)
    rows += integrity_checks(obj, piece, section, materials, pack)
    out["rows"] = rows
    verdicts = [r["ok"] for r in rows if r.get("ok") is not None]
    out["ok"] = all(verdicts) if verdicts else None
    return out


# ─────────────────────────────────── the project and report ───────────────────────────────────


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def project_precast(root: str | Path, pack: Any = None) -> dict[str, Any]:
    """The precast pieces of a project and their checks: ``{"covered", "pack", "pieces":
    [piece_checks], "schedule" (:func:`saengine.boq.precast.piece_schedule`), "notes",
    "clause"}``; ``pieces`` empty when no object type is precast."""
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings, code_pack

    root = Path(root)
    texts = {
        "settings": _read(root, "02 Project Settings/project-settings.json"),
        "materials": _read(root, "03 Materials/materials.json"),
        "objects": _read(root, "04 Objects/objects.json"),
        "bim": _read(root, "06 BIM/bim.json"),
    }
    if not texts["objects"] or not texts["bim"] or not texts["materials"]:
        return {"covered": False, "pieces": [], "notes": ["no building model or object types"]}
    objects = ObjectLibrary.model_validate_json(texts["objects"])
    types = {o.id: o for o in objects.objects}
    if not any(getattr(o, "precast", None) for o in objects.objects):
        return {"covered": True, "pieces": [], "notes": []}
    settings = ProjectSettings.model_validate_json(texts["settings"]) if texts["settings"] else None
    pack = pack or (code_pack(settings) if settings is not None else code_context.current())
    building = BuildingModel.model_validate_json(texts["bim"])
    materials = MaterialLibrary.model_validate_json(texts["materials"])
    table = rules(pack)
    name = pack.edition or pack.name
    if table is None:
        return {
            "covered": False,
            "pack": name,
            "pieces": [],
            "notes": [f"Precast pieces are not covered by the code pack {name}."],
        }
    with code_context.using(pack):
        pieces = pieces_of(building, objects)
        checked = [piece_checks(types[p.type], p, materials, types, settings, pack) for p in pieces]
        from saengine.boq.precast import piece_schedule

        schedule = piece_schedule(pieces, types, materials)
    notes = []
    if not pieces:
        notes.append("precast types are defined but no building model element uses them")
    return {
        "covered": True,
        "pack": name,
        "clause": table.source,
        "pieces": checked,
        "schedule": schedule,
        "notes": notes,
    }


def _cell(value: Any, digits: int = 2) -> str:
    return "–" if value is None else f"{float(value):.{digits}f}"


def report_section(root: str | Path, pack: Any = None) -> dict[str, Any] | None:
    """The calculation report's section on precast pieces: ``{"title", "intro", "headers",
    "rows", "fails", "scheduleHeaders", "schedule", "notes"}``; None without precast types."""
    found = project_precast(root, pack)
    if not found.get("pieces") and found.get("covered"):
        return None
    if not found.get("covered"):
        if not found.get("pack"):
            return None
        return {"title": "Precast pieces", "intro": found["notes"][0], "headers": [], "rows": []}
    headers = ["Piece", "Check", "Demand", "Capacity", "Unit", "Ratio", "Note"]
    rows, fails = [], []
    for piece in found["pieces"]:
        for r in piece["rows"]:
            rows.append(
                [
                    piece["mark"],
                    r["name"],
                    _cell(r["demand"]),
                    _cell(r["capacity"]),
                    r["unit"],
                    _cell(r["utilisation"]),
                    r["note"],
                ]
            )
            fails.append(r.get("ok") is False)
    schedule = found.get("schedule") or {}
    notes = list(found["notes"])
    for piece in found["pieces"]:
        notes += [f"{piece['mark']}: {n}" for n in piece["notes"]]
    return {
        "title": "Precast pieces",
        "intro": f"{found['clause']}. Each mark is checked at stripping, in the yard, on the "
        "truck and at erection, and its connections by the code pack's methods.",
        "headers": headers,
        "rows": rows,
        "fails": fails,
        "scheduleHeaders": schedule.get("headers", []),
        "schedule": schedule.get("rows", []),
        "notes": notes,
    }

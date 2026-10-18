"""Structural checks of the sleeves and openings MEP cuts through beams, slabs and walls.

Each check is reported in the format of :mod:`saengine.design.check` (``{name, demand,
capacity, unit, utilisation, combination, ok, note, flag}``; ``flag`` checks are reported but do
not make the opening fail). What is checked, and on what authority:

Beams (reinforced-concrete rectangles):

- Sleeves: BNBC 2020 Part 6 Sec 5.16.3.3 requires only that conduits, pipes and sleeves
  passing through a slab, wall or beam "not impair significantly the strength of the
  construction"; it gives no number. The one-third and three-diameter limits of 5.16.3.5 (a)
  and (b) are written for conduits and pipes embedded in the member and exclude those merely
  passing through. SAEngine adopts them for sleeves through beams as its practice limits (no
  larger than h/3, at least three diameters on centre); they are labelled so, not as clauses.
- Openings: SAEngine checks openings small enough to keep beam action (depth or diameter at most
  h/3, length along the beam at most d) by the net-section method: the ACI 318-19 shear strength
  (Table 22.5.5.1, Vs = Av fyt d / s, the section limit 0.66 √f'c b d) with the effective
  depth reduced by the opening's depth, d - a0, as BNBC 6.4.1.1.1 requires "the effect of any
  openings in members shall be considered in determining Vn". Larger openings act as Vierendeel
  panels with top and bottom chords (Mansur and Tan, Concrete Beams with Openings, 1999); they
  are reported as needing a detailed design, which SAEngine does not do.
- Location (SAEngine's practice limits for the net-section method, not code clauses): the
  opening clear of the support faces by at least the beam depth h (out of the high-shear zone
  and the joint), the concrete above and below it at least the cover, stirrup and bar (the bars
  and stirrup corners stay whole), and the flexural compression zone (depth a = As fy / (0.85
  f'c b) of the tension bars at yield) clear of it, so the moment capacity at the opening is the
  section's. Shear and flexure at the opening use the analysis forces at that point of the beam,
  enveloping the strength combinations.
- Not checked: torsion, the stirrups beside the opening (provide full-depth stirrups on each
  side), crack widths, and openings in steel beams.

Slabs:

- Openings in slab systems without beams (flat slabs and plates): BNBC 6.5.4.2.1 to 6.5.4.2.3
  (ACI 318-19 8.5.4.2): in the area common to two column strips at most one eighth of the
  column strip width interrupted, in the area common to a column strip and a middle strip at
  most one quarter of the bars of either strip, any size where two middle strips cross; the
  bars interrupted are added on the sides (reported). Column strips are 0.25 l1 or 0.25 l2 each
  side of the column line, whichever is less (BNBC 6.5.2.1; the spans of the bay of the
  opening's centre), clipped at the slab edge. Each rule is applied to the part of the opening
  in its region, so a large opening centred between middle strips but running into the column
  strips is checked there (the governing strip of each rule). For slabs with beams the same limits
  are reported as a guide (flag): 6.5.4.1 accepts openings of any size shown adequate by
  analysis, so cut them into the analysis model (MEP adds its openings to it).
- Punching: an opening closer than ten slab thicknesses to a column, or in a flat slab within
  a column strip through the column (within a span of it) (BNBC 6.4.10.6; ACI 318-19
  22.6.4.3), makes the part of the critical perimeter between straight lines from the column's
  centroid tangent to the opening ineffective (6.4.10.6.1). SAEngine reports the reduced b0 and,
  with analysis results, checks the direct shear Vu on it against φ vc b0 d (ACI 22.6.5.2 as in
  :mod:`saengine.design.slab`); the unbalanced moment is left to the slab design. Columns with
  beams framing in at the slab are not checked for punching.

Walls: the opening within the wall; the share of the wall length it removes at its level
(reported: the in-plane shear strength of BNBC 6.4.8 goes with the length); trim bars around
window, door and similar openings, two 16 mm bars in walls with two layers and one in walls
with a single layer (BNBC 6.6.3.7), as a note.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from shapely.geometry import Point, Polygon, box

from saengine.design.check import _check
from saengine.library.bim import BeamElement, BuildingModel, ColumnElement, SlabElement, WallElement
from saengine.library.mep import MepModel, Opening
from saengine.library.objects import (
    Beam,
    CircleProfile,
    Column,
    ObjectLibrary,
    RectangleProfile,
    Slab,
    Wall,
)

PHI_SHEAR = 0.75
FYT_MAX = 420.0

#: Demands at a point of a beam: (combination, Vu [N], Mu [N·mm], positive hogging).
Demands = list[tuple[str, float, float]]

BEAM_SOURCE = "BNBC 2020 6.4.1.1.1 (openings in Vn); net section"
SLEEVE_SIZE_NOTE = (
    "at most one third of the member depth: BNBC 5.16.3.3 gives no number for sleeves passing "
    "through; SAEngine adopts the limit 5.16.3.5 (a) sets for embedded conduits and pipes"
)
SLEEVE_SPACING_NOTE = (
    "centre to centre: BNBC 5.16.3.3 gives no number for sleeves passing through; SAEngine "
    "adopts the spacing 5.16.3.5 (b) sets for embedded conduits and pipes"
)


# ─────────────────────────────────────── beams ───────────────────────────────────────


@dataclass
class BeamSection:
    """What the opening checks need of a rectangular reinforced-concrete beam [mm, MPa]."""

    id: str
    length: float  # between the ends of its axis
    h: float
    b: float
    cover: float  # clear, to the stirrups
    stirrup_dia: float
    legs: int
    spacing: float | None
    fc: float
    fy: float
    as_top: float
    as_bottom: float
    top_dia: float
    bottom_dia: float
    d: float  # sagging: to the bottom bars
    d_top: float  # hogging: to the top bars
    start_face: float = 0.0  # from the start end to the face of its support
    end_face: float = 0.0
    phi_mn: dict[bool, float] = field(default_factory=dict)  # hogging -> φMn [N·mm]


def net_shear(beam: BeamSection, a0: float) -> dict[str, float]:
    """φVn of the net section at an opening of depth ``a0`` [N]: the ACI 318-19 shear strength
    of the beam with its effective depth reduced to d - a0 (see the module's docstring)."""
    dn = min(beam.d, beam.d_top) - a0
    root = min(math.sqrt(beam.fc), 8.3)
    fyt = min(beam.fy, FYT_MAX)
    av = beam.legs * math.pi * beam.stirrup_dia**2 / 4 if beam.spacing else 0.0
    av_min = max(0.062 * root, 0.35) * beam.b * (beam.spacing or 0.0) / fyt
    rho = min(a for a in (beam.as_top, beam.as_bottom) if a > 0) / (
        beam.b * min(beam.d, beam.d_top)
    )
    lambda_s = min(1.0, math.sqrt(2 / (1 + 0.004 * dn)))
    if av and av >= av_min:
        vc = 0.17 * root * beam.b * dn
    else:
        vc = 0.66 * lambda_s * rho ** (1 / 3) * root * beam.b * dn
    vc = min(vc, 0.42 * root * beam.b * dn)
    vs = av * fyt * dn / beam.spacing if av and beam.spacing else 0.0
    vs = min(vs, 0.66 * math.sqrt(beam.fc) * beam.b * dn)
    return {"dn": dn, "vc": vc, "vs": vs, "phi_vn": PHI_SHEAR * (vc + vs), "av": av}


def beam_opening_checks(
    opening: Opening,
    beam: BeamSection,
    demands: Demands | None = None,
    others: Sequence[Opening] = (),
) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks of a sleeve or opening through ``beam`` (see the module's docstring) with the
    analysis ``demands`` at its position (None: geometry only) and the other openings of the
    same beam. Returns (checks, notes)."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    length, a0 = opening.size  # along the beam, vertical
    x = float(opening.position.distance or 0.0)
    centre_z = float(opening.position.elevation or 0.0)
    h = beam.h
    small = a0 <= h / 3 + 1e-9 and length <= beam.d + 1e-9
    if opening.kind == "sleeve":
        checks.append(
            _check(
                "Sleeve size (h/3, SAEngine practice limit)",
                a0,
                h / 3,
                "mm",
                None,
                SLEEVE_SIZE_NOTE,
            )
        )
    else:
        checks.append(
            _check(
                "Opening depth for the net-section method (h/3)",
                a0,
                h / 3,
                "mm",
                None,
                "a deeper opening acts as a Vierendeel panel with top and bottom chords: it "
                "needs a detailed design (not done by SAEngine)",
            )
        )
    if opening.shape == "rectangle" and length > 0:
        checks.append(
            _check(
                "Opening length for the net-section method (d)",
                length,
                beam.d,
                "mm",
                None,
                "a longer opening needs a Vierendeel (chord) design (not done by SAEngine)",
            )
        )
    clear = min(x - length / 2 - beam.start_face, beam.length - beam.end_face - x - length / 2)
    checks.append(
        _check(
            "Clear distance from the support face (h)",
            h,
            max(clear, 0.0),
            "mm",
            None,
            f"{clear:.0f} mm from the nearer support face; SAEngine keeps openings at least the "
            "beam depth away from it (out of the high-shear zone and the joint)",
        )
    )
    top_chord = h - (centre_z + a0 / 2)
    bottom_chord = centre_z - a0 / 2
    for label, need_dia, chord in (
        ("above", beam.top_dia, top_chord),
        ("below", beam.bottom_dia, bottom_chord),
    ):
        need = beam.cover + beam.stirrup_dia + need_dia
        checks.append(
            _check(
                f"Concrete {label} the opening",
                need,
                max(chord, 0.0),
                "mm",
                None,
                f"at least cover {beam.cover:g} + stirrup {beam.stirrup_dia:g} + bar "
                f"{need_dia:g} mm, so the bars and stirrup corners stay whole",
            )
        )
    for other in others:
        if other.id == opening.id or other.host != opening.host:
            continue
        if opening.kind != "sleeve" or other.kind != "sleeve":
            continue
        spacing = abs(float(other.position.distance or 0.0) - x)
        need = 3 * max(a0, length, *other.size)
        checks.append(
            _check(
                f"Spacing to {other.id} (3 diameters, SAEngine practice limit)",
                need,
                spacing,
                "mm",
                None,
                SLEEVE_SPACING_NOTE,
            )
        )
    if demands is None:
        notes.append(f"{opening.id}: no analysis results; shear and flexure at it are not checked")
        return checks, notes
    if not demands:
        notes.append(f"{opening.id}: not found in the analysis results of {beam.id}")
        return checks, notes
    sag = min(demands, key=lambda d: d[2])
    hog = max(demands, key=lambda d: d[2])
    for label, demand, as_tension, chord, hogging in (
        ("above the opening (sagging)", sag, beam.as_bottom, top_chord, False),
        ("below the opening (hogging)", hog, beam.as_top, bottom_chord, True),
    ):
        moment = -demand[2] if not hogging else demand[2]
        if moment <= 0 or as_tension <= 0:
            continue
        a = as_tension * beam.fy / (0.85 * beam.fc * beam.b)
        checks.append(
            _check(
                f"Compression zone {label}",
                a,
                max(chord, 0.0),
                "mm",
                demand[0],
                f"a = As fy / (0.85 f'c b) = {a:.0f} mm must stay clear of the opening, "
                f"Mu = {moment / 1e6:.1f} kN·m here",
            )
        )
        capacity = beam.phi_mn.get(hogging)
        if capacity:
            checks.append(
                _check(
                    f"Flexure at the opening ({'hogging' if hogging else 'sagging'})",
                    moment / 1e6,
                    capacity / 1e6,
                    "kN·m",
                    demand[0],
                    "φMn of the full section: valid while the compression zone is clear of it",
                )
            )
    shear_demand = max(demands, key=lambda d: abs(d[1]))
    if small:
        shear = net_shear(beam, a0)
        checks.append(
            _check(
                "Shear at the opening (net section)",
                abs(shear_demand[1]) / 1e3,
                shear["phi_vn"] / 1e3,
                "kN",
                shear_demand[0],
                f"d - a0 = {shear['dn']:.0f} mm, Vc = {shear['vc'] / 1e3:.1f} kN, Vs = "
                f"{shear['vs'] / 1e3:.1f} kN ({BEAM_SOURCE}); full-depth stirrups on each side",
            )
        )
    else:
        notes.append(
            f"{opening.id}: a large opening (deeper than h/3 or longer than d) acts as a "
            f"Vierendeel panel; Vu = {abs(shear_demand[1]) / 1e3:.1f} kN there must be shared by "
            "its chords: needs a detailed design"
        )
    return checks, notes


def beam_section(
    beam: BeamElement, objects: ObjectLibrary, materials: Any, building: BuildingModel
) -> tuple[BeamSection | None, str]:
    """The :class:`BeamSection` of a building-model beam, or None and why it is not checked."""
    from saengine.design.rc import DesignError, flexure, section_of

    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    beam_type = types.get(beam.type)
    if not isinstance(beam_type, Beam):
        return None, f"unknown beam type '{beam.type}'"
    profile = beam_type.profile
    if not isinstance(profile, RectangleProfile):
        return None, "only rectangular concrete beams are checked (web openings in steel beams "
        "are not)"
    concrete = mats.get(beam_type.material)
    if concrete is None or concrete.concrete is None:
        return None, "not a concrete beam"
    reinforcement = beam_type.reinforcement
    if reinforcement is None:
        return None, "no reinforcement"
    bars = mats.get(reinforcement.material)
    if bars is None or bars.steel is None:
        return None, f"unknown reinforcement material '{reinforcement.material}'"
    try:
        section = section_of(
            profile,
            reinforcement,
            concrete.concrete.fc,
            bars.steel.fy,
            bars.mechanical.E or 200_000.0,
        )
        d = section.effective_depth(top=False)
        d_top = section.effective_depth(top=True)
    except DesignError as error:
        return None, str(error)
    top = [b for b in section.bars if b.y > 0]
    bottom = [b for b in section.bars if b.y < 0]
    transverse = reinforcement.transverse
    length = math.dist(beam.start, beam.end)
    faces = [0.0, 0.0]
    for k, end in enumerate((beam.start, beam.end)):
        for column in building.elements:
            if not isinstance(column, ColumnElement):
                continue
            if math.dist(column.position, end) > 1.0:
                continue
            if not (column.bottom - 1.0 <= beam.elevation <= column.top + 1.0):
                continue
            faces[k] = max(faces[k], _half_along(column, types, beam))
    return (
        BeamSection(
            id=beam.id,
            length=length,
            h=profile.yDim,
            b=profile.xDim,
            cover=reinforcement.cover,
            stirrup_dia=transverse.dia if transverse else 0.0,
            legs=transverse.legs if transverse else 0,
            spacing=transverse.spacing if transverse else None,
            fc=concrete.concrete.fc,
            fy=bars.steel.fy,
            as_top=sum(b.area for b in top),
            as_bottom=sum(b.area for b in bottom),
            top_dia=max((b.dia for b in top), default=0.0),
            bottom_dia=max((b.dia for b in bottom), default=0.0),
            d=d,
            d_top=d_top,
            start_face=faces[0],
            end_face=faces[1],
            phi_mn={hog: flexure(section, hog).phi_mn for hog in (False, True)},
        ),
        "",
    )


def _half_along(column: ColumnElement, types: dict[str, Any], beam: BeamElement) -> float:
    """Half the column's size along the beam (its support face from the beam's end)."""
    column_type = types.get(column.type)
    profile = column_type.profile if isinstance(column_type, Column) else None
    if isinstance(profile, CircleProfile):
        return profile.radius
    if not isinstance(profile, RectangleProfile):
        return 0.0
    axis = np.subtract(beam.end, beam.start, dtype=float)
    axis /= np.linalg.norm(axis)
    t = math.radians(column.rotation)
    u = np.array([math.cos(t), math.sin(t)])
    v = np.array([-math.sin(t), math.cos(t)])
    return float(abs(axis @ u) * profile.xDim / 2 + abs(axis @ v) * profile.yDim / 2)


def demands_at(
    pieces: Sequence[Any],
    start: Sequence[float],
    end: Sequence[float],
    distance: float,
    combinations: Sequence[str],
    turned: bool = False,
) -> Demands:
    """The shear and moment per combination at ``distance`` [mm] along a beam from ``start``
    to ``end`` (plan, mm), from its analysis pieces (:func:`saengine.design.check._demands`),
    interpolated between stations."""
    from saengine.design.check import _profile_forces

    a = np.asarray(start[:2], dtype=float) * 1e-3
    b = np.asarray(end[:2], dtype=float) * 1e-3
    point = a + (b - a) * distance / max(float(np.linalg.norm(b - a)) * 1e3, 1e-9)
    for piece in pieces:
        if piece.start is None or piece.end is None:
            continue
        p0, p1 = piece.start[:2], piece.end[:2]
        axis = p1 - p0
        span = float(axis @ axis)
        if span < 1e-12:
            continue
        t = float((point - p0) @ axis) / span
        if not -1e-6 <= t <= 1 + 1e-6 or np.linalg.norm(p0 + t * axis - point) > 1e-3:
            continue
        result: Demands = []
        for c, forces in enumerate(piece.forces):
            values = _profile_forces(piece, turned, forces)
            stations = len(forces)
            s = min(max(t, 0.0), 1.0) * (stations - 1)
            k = min(int(s), stations - 2) if stations > 1 else 0
            f = s - k
            if stations == 1:
                v, m = float(values["Vy"][0]), float(values["Mx"][0])
            else:
                v = float(values["Vy"][k] * (1 - f) + values["Vy"][k + 1] * f)
                m = float(values["Mx"][k] * (1 - f) + values["Mx"][k + 1] * f)
            result.append((combinations[c], v, m))
        return result
    return []


# ─────────────────────────────────────── slabs ───────────────────────────────────────


@dataclass
class SlabInfo:
    """What the opening checks need of a slab [mm, MPa]; bar areas per mm width."""

    id: str
    boundary: list[list[float]]
    h: float
    d: float
    fc: float
    flat: bool  # without beams: the strip rules of BNBC 6.5.4.2 apply
    bars_x: float = 0.0  # mm²/mm, X bars (top and bottom)
    bars_y: float = 0.0


@dataclass
class ColumnAt:
    """A column at a slab: centre [mm], sides c1 (along its axis at ``angle``) and c2."""

    id: str
    centre: tuple[float, float]
    c1: float
    c2: float
    angle: float = 0.0
    beams: bool = False  # beams frame into it at the slab


def opening_polygon(opening: Opening, cx: float, cy: float) -> Polygon:
    """The opening's outline in plan (slab) or in the wall's plane."""
    width, height = opening.size
    if opening.shape == "circle":
        return Point(cx, cy).buffer(width / 2, quad_segs=16)
    return box(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)


def ineffective_perimeter(column: ColumnAt, d: float, boundary: Any, hole: Polygon) -> tuple:
    """(b0, the length of it made ineffective by ``hole``) of the punching critical section of
    ``column`` (BNBC 6.4.10.6.1): the part between the straight lines from the column's centroid
    tangent to the hole, and the critical section."""
    from saengine.design.slab import critical_section

    section = critical_section(column.centre, column.c1, column.c2, column.angle, d, boundary)
    t = math.radians(column.angle)
    u = np.array([math.cos(t), math.sin(t)])
    v = np.array([-math.sin(t), math.cos(t)])
    c = np.array(column.centre, dtype=float)
    local = [
        np.array([(np.array(p) - c) @ u, (np.array(p) - c) @ v]) for p in hole.exterior.coords[:-1]
    ]
    centre = np.array([hole.centroid.x, hole.centroid.y]) - c
    centre = np.array([centre @ u, centre @ v])
    if hole.contains(Point(*column.centre)):
        return section.b0, section.b0
    mid = math.atan2(centre[1], centre[0])
    rel = [(math.atan2(p[1], p[0]) - mid + math.pi) % (2 * math.pi) - math.pi for p in local]
    lo, hi = min(rel), max(rel)
    r1 = np.array([math.cos(mid + lo), math.sin(mid + lo)])
    r2 = np.array([math.cos(mid + hi), math.sin(mid + hi)])

    def cross(a: np.ndarray, b: np.ndarray) -> float:
        return float(a[0] * b[1] - a[1] * b[0])

    lost = 0.0
    for u0, v0, u1, v1 in section.sides:
        a = np.array([u0, v0])
        e = np.array([u1 - u0, v1 - v0])
        low, high = 0.0, 1.0
        for k0, k1 in ((cross(r1, a), cross(r1, e)), (-cross(r2, a), -cross(r2, e))):
            # k0 + k1 t >= 0
            if abs(k1) < 1e-12:
                if k0 < 0:
                    low, high = 1.0, 0.0
                continue
            root = -k0 / k1
            if k1 > 0:
                low = max(low, root)
            else:
                high = min(high, root)
        if high > low:
            lost += (high - low) * float(np.linalg.norm(e))
    return section.b0, lost


@dataclass
class _Band:
    """A strip of a two-way slab: ``kind`` "column" or "middle", its plan area and width [mm]."""

    kind: str
    area: Polygon
    width: float


@dataclass
class _Strips:
    """The column and middle strips of a slab on a column grid (BNBC 6.5.2.1): the strips of the
    X bars (bands in y), of the Y bars (bands in x), and the union of the column strips of each
    direction. Strip widths are those of the bay of the opening's centre."""

    bands_x: list[_Band]
    bands_y: list[_Band]
    column_x: Any  # the column strips along X (around the lines y = const)
    column_y: Any
    cs_width: float
    span: float

    def in_column_strip_of(self, column: ColumnAt, hole: Polygon) -> bool:
        """Whether ``hole`` lies (partly) in a column strip through ``column`` within a span of
        it (BNBC 6.4.10.6: openings in flat slabs within column strips)."""
        cx, cy = column.centre
        half = self.cs_width / 2
        reach = Point(cx, cy).buffer(self.span)
        for band in (
            box(cx - self.span, cy - half, cx + self.span, cy + half),
            box(cx - half, cy - self.span, cx + half, cy + self.span),
        ):
            part = hole.intersection(band).intersection(reach)
            if not part.is_empty and part.area > 0:
                return True
        return False


def _intervals(lines: list[float], half: float, lo: float, hi: float) -> list[tuple]:
    """The column-strip and middle-strip intervals ``(kind, start, end)`` across [lo, hi]."""
    column = [(max(v - half, lo), min(v + half, hi)) for v in lines]
    column = [c for c in column if c[1] > c[0]]
    result = [("column", a, b) for a, b in column]
    edge = lo
    for a, b in sorted(column):
        if a > edge:
            result.append(("middle", edge, a))
        edge = max(edge, b)
    if hi > edge:
        result.append(("middle", edge, hi))
    return result


def _strips(columns: Sequence[ColumnAt], outline: Polygon, px: float, py: float) -> _Strips:
    xs = sorted({float(round(c.centre[0])) for c in columns})
    ys = sorted({float(round(c.centre[1])) for c in columns})
    sx0, sy0, sx1, sy1 = outline.bounds

    def bay(lines: list[float], at: float, lo: float, hi: float) -> tuple[float, float]:
        left = max([v for v in lines if v <= at], default=lo)
        right = min([v for v in lines if v > at], default=hi)
        return left, right

    x_left, x_right = bay(xs, px, sx0, sx1)
    y_low, y_high = bay(ys, py, sy0, sy1)
    l1, l2 = x_right - x_left, y_high - y_low
    half = 0.25 * min(l1, l2)  # column strip each side of a column line
    pad = 1.0
    bands_x = [
        _Band(kind, box(sx0 - pad, a, sx1 + pad, b), b - a)
        for kind, a, b in _intervals(ys, half, sy0, sy1)
    ]
    bands_y = [
        _Band(kind, box(a, sy0 - pad, b, sy1 + pad), b - a)
        for kind, a, b in _intervals(xs, half, sx0, sx1)
    ]

    def union(bands: list[_Band]) -> Any:
        from shapely.ops import unary_union

        return unary_union([b.area for b in bands if b.kind == "column"])

    return _Strips(bands_x, bands_y, union(bands_x), union(bands_y), 2 * half, max(l1, l2))


def _strip_checks(hole: Polygon, strips: _Strips, flag: bool, guide: str) -> list[dict[str, Any]]:
    """The BNBC 6.5.4.2.2 and 6.5.4.2.3 limits on the bars ``hole`` interrupts, by the parts of
    it in each region (not only where its centre is): in the area common to two column strips
    at most 1/8 of the column strip width, in the area common to a column strip and a middle
    strip at most 1/4 of either strip; the governing band of each rule."""
    minimum = 1e-6 * max(hole.area, 1.0)
    found: dict[tuple[str, str], tuple[float, float, float]] = {}

    def record(bars: str, rule: str, part: Any, axis: int, limit: float, width: float) -> None:
        if part.is_empty or part.area <= minimum:
            return
        bounds = part.bounds
        cut = bounds[axis + 2] - bounds[axis]
        old = found.get((bars, rule))
        if old is None or cut / max(limit, 1e-9) > old[0] / max(old[1], 1e-9):
            found[(bars, rule)] = (cut, limit, width)

    for bars, bands, other, axis in (
        ("X", strips.bands_x, strips.column_y, 1),
        ("Y", strips.bands_y, strips.column_x, 0),
    ):
        for band in bands:
            inside_band = hole.intersection(band.area)
            if inside_band.is_empty:
                continue
            crossing = inside_band.intersection(other)
            beside = inside_band.difference(other)
            if band.kind == "column":
                record(bars, "cross", crossing, axis, band.width / 8, band.width)
                record(bars, "column", beside, axis, band.width / 4, band.width)
            else:
                record(bars, "middle", crossing, axis, band.width / 4, band.width)
    names = {
        "cross": "{} bars cut where column strips cross (BNBC 6.5.4.2.2: 1/8)",
        "column": "{} bars cut in the column strip (BNBC 6.5.4.2.3: 1/4)",
        "middle": "{} bars cut in the middle strip (BNBC 6.5.4.2.3: 1/4)",
    }
    checks = []
    for bars in ("X", "Y"):
        for rule in ("cross", "column", "middle"):
            if (bars, rule) not in found:
                continue
            cut, limit, width = found[(bars, rule)]
            where = {
                "cross": "of the opening where the column strips cross",
                "column": "of the opening in the column strip beside a middle strip",
                "middle": "of the opening in the middle strip beside a column strip",
            }[rule]
            checks.append(
                _check(
                    names[rule].format(bars),
                    round(cut, 3),
                    limit,
                    "mm",
                    None,
                    f"the part {where}; strip {width:.0f} mm wide"
                    + (f"; {guide}" if guide else ""),
                    flag=flag,
                )
            )
    return checks


def slab_opening_checks(
    opening: Opening,
    slab: SlabInfo,
    columns: Sequence[ColumnAt],
    others: Sequence[Opening] = (),
    column_shear: Callable[[str], list[tuple[str, float]] | None] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks of an opening through ``slab`` (see the module's docstring). ``columns``: the
    columns at the slab; ``column_shear(column id)``: the factored shear the slab delivers to it
    per combination [N] (None without results). Returns (checks, notes)."""
    from saengine.design.slab import critical_section, punching_capacity

    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    px, py = float(opening.position.x or 0.0), float(opening.position.y or 0.0)
    hole = opening_polygon(opening, px, py)
    outline = Polygon([(p[0], p[1]) for p in slab.boundary])
    outside = hole.difference(outline.buffer(1.0))
    overhang = math.sqrt(outside.area) if not outside.is_empty else 0.0
    checks.append(
        _check(
            "Opening inside the slab",
            overhang,
            0.0,
            "mm",
            None,
            "the opening runs past the slab edge" if overhang else "",
        )
    )
    minx, miny, maxx, maxy = hole.bounds
    width_x, width_y = maxx - minx, maxy - miny

    # ── strips (BNBC 6.5.2.1, 6.5.4.2) ──
    strips = _strips(columns, outline, px, py) if columns else None
    if strips is not None:
        flag = not slab.flat
        guide = (
            ""
            if slab.flat
            else "slab with beams: a guide only (BNBC 6.5.4.1 accepts any opening shown "
            "adequate by analysis)"
        )
        checks += _strip_checks(hole, strips, flag, guide)
        middle_only = hole.difference(strips.column_x.union(strips.column_y))
        if not middle_only.is_empty and middle_only.area > 1e-6 * max(hole.area, 1.0):
            whole = middle_only.area >= hole.area * (1 - 1e-9)
            notes.append(
                f"{opening.id}: {'' if whole else 'the part '}where two middle strips cross: "
                "any size is permitted there with the panel's total reinforcement kept "
                "(BNBC 6.5.4.2.1)"
            )
    if slab.bars_x or slab.bars_y:
        notes.append(
            f"{opening.id}: add the bars it cuts beside it, half each side: about "
            f"{slab.bars_x * width_y:.0f} mm² of X bars and {slab.bars_y * width_x:.0f} mm² of Y "
            "bars (top and bottom together)"
        )

    # ── punching (BNBC 6.4.10.6) ──
    for column in columns:
        t = math.radians(column.angle)
        corners = [
            (
                column.centre[0]
                + su * column.c1 / 2 * math.cos(t)
                - sv * column.c2 / 2 * math.sin(t),
                column.centre[1]
                + su * column.c1 / 2 * math.sin(t)
                + sv * column.c2 / 2 * math.cos(t),
            )
            for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        ]
        distance = Polygon(corners).distance(hole)
        near = distance < 10 * slab.h
        in_strip = slab.flat and strips is not None and strips.in_column_strip_of(column, hole)
        if not near and not in_strip:
            continue
        if column.beams:
            notes.append(
                f"{opening.id}: {distance:.0f} mm from {column.id}, which has beams framing in "
                "at this slab: no punching check"
            )
            continue
        b0, lost = ineffective_perimeter(column, slab.d, slab.boundary, hole)
        effective = max(b0 - lost, 0.0)
        where = (
            f"{distance:.0f} mm from {column.id} (< 10 h = {10 * slab.h:.0f} mm)"
            if near
            else f"in a column strip of {column.id} of the flat slab, {distance:.0f} mm from it"
        )
        reason = f"{where}: {lost:.0f} of b0 = {b0:.0f} mm ineffective"
        shears = column_shear(column.id) if column_shear else None
        if not shears:
            checks.append(
                _check(
                    f"Critical perimeter at {column.id} (BNBC 6.4.10.6.1)",
                    lost,
                    b0,
                    "mm",
                    None,
                    reason + "; punching must be checked on the reduced b0 (no results)",
                    flag=True,
                )
            )
            continue
        section = critical_section(
            column.centre, column.c1, column.c2, column.angle, slab.d, slab.boundary
        )
        beta = max(column.c1, column.c2) / min(column.c1, column.c2)
        combination, vu = max(shears, key=lambda s: s[1])
        if effective <= 0:
            capacity = 0.0
            note = reason
        else:
            vc = punching_capacity(slab.fc, slab.d, effective, beta, section.alpha_s)
            capacity = PHI_SHEAR * vc.vc * effective * slab.d
            note = (
                f"{reason}; vc = {vc.vc:.3f} MPa on b0 = {effective:.0f} mm, d = {slab.d:.0f} mm "
                "(direct shear; the unbalanced moment is left to the slab design)"
            )
        checks.append(
            _check(
                f"Punching at {column.id} with the opening (BNBC 6.4.10.6.1)",
                vu / 1e3,
                capacity / 1e3,
                "kN",
                combination,
                note,
            )
        )

    for other in others:
        if other.id == opening.id or other.host != opening.host:
            continue
        if opening.kind != "sleeve" or other.kind != "sleeve":
            continue
        spacing = math.dist((px, py), (other.position.x or 0.0, other.position.y or 0.0))
        need = 3 * max(*opening.size, *other.size)
        checks.append(
            _check(
                f"Spacing to {other.id} (3 diameters, SAEngine practice limit)",
                need,
                spacing,
                "mm",
                None,
                SLEEVE_SPACING_NOTE,
                flag=True,
            )
        )
    return checks, notes


def slab_info(slab: SlabElement, objects: ObjectLibrary, materials: Any, building: BuildingModel):
    """The :class:`SlabInfo` of a building-model slab and its :class:`ColumnAt` list, or
    (None, [], why)."""
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    slab_type = types.get(slab.type)
    if not isinstance(slab_type, Slab):
        return None, [], f"unknown slab type '{slab.type}'"
    concrete = mats.get(slab_type.material)
    if concrete is None or concrete.concrete is None:
        return None, [], "not a concrete slab"
    h = slab_type.thickness
    r = slab_type.reinforcement
    if r is not None:
        top = [m for m in (r.topX, r.topY) if m is not None]
        d = h - r.cover - (sum(m.dia for m in top) / len(top) if top else 10.0)
        bars_x = sum(math.pi * m.dia**2 / 4 / m.spacing for m in (r.topX, r.bottomX) if m)
        bars_y = sum(math.pi * m.dia**2 / 4 / m.spacing for m in (r.topY, r.bottomY) if m)
    else:
        d, bars_x, bars_y = 0.8 * h, 0.0, 0.0
    beams = [
        e
        for e in building.elements
        if isinstance(e, BeamElement) and abs(e.elevation - slab.elevation) < 1.0
    ]
    outline = Polygon([(p[0], p[1]) for p in slab.boundary])
    on_edges = [
        e for e in beams if outline.exterior.distance(Point(*np.mean([e.start, e.end], axis=0))) < 1
    ]
    flat = slab_type.system == "flat" or not on_edges
    columns: list[ColumnAt] = []
    for e in building.elements:
        if not isinstance(e, ColumnElement):
            continue
        if not (abs(e.top - slab.elevation) < 1.0 or abs(e.bottom - slab.elevation) < 1.0):
            continue
        if not outline.buffer(1.0).contains(Point(*e.position)):
            continue
        if any(c.id == e.id or math.dist(c.centre, e.position) < 1.0 for c in columns):
            continue
        column_type = types.get(e.type)
        profile = column_type.profile if isinstance(column_type, Column) else None
        if isinstance(profile, RectangleProfile):
            c1, c2 = profile.xDim, profile.yDim
        elif isinstance(profile, CircleProfile):
            c1 = c2 = profile.radius * math.sqrt(math.pi)  # the square of equal area
        else:
            continue
        framed = any(
            math.dist(b.start, e.position) < 1.0 or math.dist(b.end, e.position) < 1.0
            for b in beams
        )
        columns.append(ColumnAt(e.id, (e.position[0], e.position[1]), c1, c2, e.rotation, framed))
    return (
        SlabInfo(slab.id, slab.boundary, h, d, concrete.concrete.fc, flat, bars_x, bars_y),
        (columns),
        "",
    )


# ─────────────────────────────────────── walls ───────────────────────────────────────


def wall_opening_checks(
    opening: Opening, wall: WallElement, thickness: float, others: Sequence[Opening] = ()
) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks of an opening through ``wall`` (see the module's docstring)."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    length = math.dist(wall.start, wall.end)
    height = wall.top - wall.bottom
    along, up = float(opening.position.x or 0.0), float(opening.position.y or 0.0)
    hole = opening_polygon(opening, along, up)
    outside = hole.difference(box(0, 0, length, height).buffer(1.0))
    overhang = math.sqrt(outside.area) if not outside.is_empty else 0.0
    checks.append(
        _check(
            "Opening inside the wall",
            overhang,
            0.0,
            "mm",
            None,
            "the opening runs past the wall's edge" if overhang else "",
        )
    )
    width, _ = opening.size
    checks.append(
        _check(
            "Wall length removed at the opening",
            width,
            length,
            "mm",
            None,
            f"{width / length:.0%} of the wall's length; its in-plane shear strength (BNBC 6.4.8) "
            "goes with the length left: MEP adds the opening to the analysis model",
            flag=True,
        )
    )
    if opening.kind == "opening":
        layers = (
            "more than 250 mm thick, so it has two layers (BNBC 6.6.3.4): two bars"
            if thickness > 250
            else "250 mm thick or less: two bars if it has two layers, one if a single layer"
        )
        notes.append(
            f"{opening.id}: provide 16 mm trim bars around it, anchored to develop fy at the "
            f"corners (BNBC 6.6.3.7); the wall is {thickness:g} mm thick, {layers}"
        )
    for other in others:
        if other.id == opening.id or other.host != opening.host:
            continue
        if opening.kind != "sleeve" or other.kind != "sleeve":
            continue
        spacing = math.dist((along, up), (other.position.x or 0.0, other.position.y or 0.0))
        need = 3 * max(*opening.size, *other.size)
        checks.append(
            _check(
                f"Spacing to {other.id} (3 diameters, SAEngine practice limit)",
                need,
                spacing,
                "mm",
                None,
                SLEEVE_SPACING_NOTE,
                flag=True,
            )
        )
    return checks, notes


# ─────────────────────────────────────── all ───────────────────────────────────────


@dataclass
class Analysis:
    """The analysis results the checks read: combination names and the member pieces of
    :func:`saengine.design.check._demands`."""

    combinations: list[str]
    pieces: dict[str, list[Any]]


def column_shear_from(analysis: Analysis, building: BuildingModel, slab: SlabElement):
    """``column_shear(column id)`` for :func:`slab_opening_checks`: the compression in the
    column below the slab less the column above, per combination [N]."""
    from saengine.design.check import _profile_forces

    columns = [e for e in building.elements if isinstance(e, ColumnElement)]
    z = slab.elevation * 1e-3

    def axial(column: ColumnElement, at_top: bool) -> list[float] | None:
        pieces = analysis.pieces.get(column.id, [])
        for piece in pieces:
            if piece.start is None or piece.end is None:
                continue
            ends = (piece.start[2], piece.end[2])
            target = max(ends) if at_top else min(ends)
            if abs(target - z) > 1e-3:
                continue
            index = -1 if abs(piece.end[2] - z) < 1e-3 else 0
            return [
                float(_profile_forces(piece, False, forces)["P"][index]) for forces in piece.forces
            ]
        return None

    def shear(column_id: str) -> list[tuple[str, float]] | None:
        column = next((c for c in columns if c.id == column_id), None)
        if column is None:
            return None
        below_column = column if abs(column.top - slab.elevation) < 1.0 else None
        if below_column is None:
            below_column = next(
                (
                    c
                    for c in columns
                    if abs(c.top - slab.elevation) < 1.0
                    and math.dist(c.position, column.position) < 1
                ),
                None,
            )
        above_column = next(
            (
                c
                for c in columns
                if abs(c.bottom - slab.elevation) < 1.0
                and math.dist(c.position, column.position) < 1
            ),
            None,
        )
        below = axial(below_column, True) if below_column else None
        if below is None:
            return None
        above = axial(above_column, False) if above_column else None
        return [
            (name, below[k] - (above[k] if above else 0.0))
            for k, name in enumerate(analysis.combinations)
        ]

    return shear


def opening_checks(
    mep: MepModel,
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: Any,
    analysis: Analysis | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks of every sleeve and opening of ``mep``: per opening ``{"id", "host",
    "hostKind", "kind", "checks", "utilisation", "ok", "notes"}``, and general notes."""
    from saengine.design.check import _turned

    elements = {e.id: e for e in building.elements}
    types = {o.id: o for o in objects.objects}
    results: list[dict[str, Any]] = []
    notes: list[str] = []
    beams: dict[str, tuple[BeamSection | None, str]] = {}
    slabs: dict[str, tuple[Any, list[ColumnAt], str]] = {}
    for opening in mep.openings:
        host = elements.get(opening.host)
        own_notes: list[str] = []
        checks: list[dict[str, Any]] = []
        kind = getattr(host, "kind", None)
        if isinstance(host, BeamElement):
            if host.id not in beams:
                beams[host.id] = beam_section(host, objects, materials, building)
            section, why = beams[host.id]
            if section is None:
                own_notes.append(f"{opening.id}: {host.id} is not checked: {why}")
            else:
                demands = None
                if analysis is not None:
                    demands = demands_at(
                        analysis.pieces.get(host.id, []),
                        host.start,
                        host.end,
                        float(opening.position.distance or 0.0),
                        analysis.combinations,
                        _turned(host),
                    )
                checks, own_notes = beam_opening_checks(opening, section, demands, mep.openings)
        elif isinstance(host, SlabElement):
            if host.id not in slabs:
                slabs[host.id] = slab_info(host, objects, materials, building)
            info, columns, why = slabs[host.id]
            if info is None:
                own_notes.append(f"{opening.id}: {host.id} is not checked: {why}")
            else:
                shear = column_shear_from(analysis, building, host) if analysis else None
                checks, own_notes = slab_opening_checks(opening, info, columns, mep.openings, shear)
        elif isinstance(host, WallElement):
            wall_type = types.get(host.type)
            thickness = wall_type.thickness if isinstance(wall_type, Wall) else 200.0
            checks, own_notes = wall_opening_checks(opening, host, thickness, mep.openings)
        else:
            own_notes.append(f"{opening.id}: there is no beam, slab or wall '{opening.host}'")
        strength = [c for c in checks if not c["flag"]]
        results.append(
            {
                "id": opening.id,
                "host": opening.host,
                "hostKind": kind,
                "kind": opening.kind,
                "service": opening.service,
                "checks": checks,
                "utilisation": max((c["utilisation"] for c in strength), default=0.0),
                "ok": all(c["ok"] for c in strength),
                "checked": bool(checks),
                "notes": own_notes,
            }
        )
    return results, notes

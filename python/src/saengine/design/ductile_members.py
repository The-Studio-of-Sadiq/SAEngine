"""Seismic detailing of the beams and columns of reinforced-concrete moment frames, to the default pack's BNBC 2020
Part 6 Chapter 8 Sec 8.3 "Earthquake-Resistant Design Provisions" (the code PDF) pages
1088-1123, the gazette pages 3669-3704).

Pure functions over what :func:`saengine.design.check.design` already has for a member: its
:class:`~saengine.design.rc.RcSection`, its object type, its flexural capacities
(:func:`saengine.design.rc.flexure`), the largest factored axial compression of its pieces,
its clear length and, for beams, the columns at its ends. They return rows in the design
report's check format ``{name, demand, capacity, unit, utilisation, combination, ok, note,
flag}`` (as ``check._check``), notes, and the requirements the design mode works from.

Which rules a member gets (the frame type, from the seismic design category and the
structural system, the default pack's BNBC 8.3.2): ``frame`` is "special" (SDC D: Sections 8.3.3 to 8.3.8),
"intermediate" (SDC C: Sec 8.3.10) or "ordinary" (SDC B: Sec 8.3.9); 8.3.2(e) lets a lower
SDC use a higher frame type. ``lateral`` False is a member not designated as part of the
seismic-force-resisting system: Sec 8.3.12 in a special frame (SDC D), Sec 8.3.9 otherwise
(8.3.3.1(d)).

What is checked, clause by clause (the demand of a "not less than" check is the required
least value and the capacity the value provided, so utilisation <= 1 passes either way):

Beams of special moment frames (8.3.4, p. 1090-1094)
- 8.3.4.1(a) Pu <= 0.1 Ag f'c (otherwise the member is designed by 8.3.5).
- 8.3.4.1(b) clear span ln >= 4 d; (c) b/h >= 0.3; (d)(i) b >= 250 mm; (d)(ii) b <= c2 +
  2 min(c2, 0.75 c1) at each supporting column (Figure 6.8.1: b <= c2 + 1.5 c1 and <= 3 c2;
  c1 the column dimension along the span, c2 across it; the text's wording is garbled, the
  figure is followed).
- 8.3.4.2(a) top and bottom: ρ = As / (b d) >= max(0.25 √f'c, 1.4) / fy (the text prints
  0.25 f'c / fy; Figure 6.8.2 has √f'c, which is followed) and <= 0.025; at least two bars
  top and bottom (all bars of an object type run its full length here); Mn+ >= Mn- / 2 at the
  joint face; Mn+ and Mn- >= max Mn / 4 at any section (one bar layout per type: the faces
  and every section have the same strengths).
- 8.3.4.2(b) hoops over lap splices at <= min(d/4, 100 mm); splice locations (not within the
  joint or 2h of its face) are not modelled: said in the notes.
- 8.3.4.3(a) hoops over 2h from each face; (b) first hoop <= 50 mm from the face, spacing <=
  min(d/4, 8 db,min, 24 dh, 300 mm); (c) elsewhere <= d/2; perimeter bars in the hoop zones
  laterally supported per 8.1.9.4(c) (every corner and alternate bar held by a hoop leg, no
  bar more than 150 mm clear from a held one).

Columns of special moment frames (8.3.5, p. 1095-1099)
- 8.3.5.1(a) least dimension >= 300 mm; (b) least / perpendicular dimension >= 0.4.
- 8.3.5.3(a) 0.01 <= ρg <= 0.06; (b) lap splices in the centre half (not modelled: noted),
  ties over them <= min(least dimension / 4, 100 mm) (Figure 6.8.8).
- 8.3.5.4(a)(i) spirals and circular hoops: ρs >= max(0.12 f'c/fyt (Eq. 6.8.6), 0.45 (Ag/Ach
  - 1) f'c/fyt (Eq. 6.6.12, Sec 6.3.9.3)); (ii) rectangular hoops, in each direction: Ash >=
  max(0.3 s bc f'c/fyt (Ag/Ach - 1) (Eq. 6.8.7), 0.09 s bc f'c/fyt (Eq. 6.8.8)), fyt <=
  700 MPa (8.3.3.4(c)); bc to the outside of the hoops (b - 2 cover); the (iv) exemption
  (core strength alone sufficient) is not used.
- 8.3.5.4(b) spacing in lo <= min(least dimension / 4, 6 db,min, so), so = 100 + (350 - hx)/3
  within [100, 150] mm; (c) hx <= 350 mm; (d) lo >= max(h, ln/6, 450 mm); first hoop <= so/2
  from the face (Figure 6.8.8); (f) elsewhere <= min(6 db,min, 150 mm); 8.3.5.2(c) and
  8.3.5.4(e) (``full_height``): the lo requirements over the whole height.

Intermediate moment frames (8.3.10, p. 1114-1117)
- 8.3.10.4(a) beams: Mn+ >= Mn- / 3 at the face, Mn+ and Mn- >= max Mn / 5 anywhere; (b)
  stirrups over 2h, the first <= 50 mm from the face, spacing <= min(d/4, 8 db,min, 24 ds,
  300 mm); (c) <= d/2 throughout. The default pack's BNBC sets no dimensional limits or steel ratio limits for
  IMF beams (Figure 6.8.17's ρmax = ρ at εt = 0.004 is Chapter 6's, checked by the strength
  checks).
- 8.3.10.5 columns: (a) so <= min(8 db,min, 24 dt, least dimension / 2, 300 mm) over lo >=
  max(ln/6, largest dimension, 450 mm); (b) first tie <= so/2; (d) <= 2 so throughout; (c)
  joints per Sec 6.4.9 (not here). Columns with Pu <= 0.1 Ag f'c take the details of 8.3.10.4
  (8.3.10.2) over the stricter length max(2h, ln/6, largest dimension, 450 mm).

Ordinary moment frames (8.3.9, p. 1113)
- 8.3.9.2 members with Pu > 0.1 Ag f'c (unless they satisfy 8.3.5.4): so <= min(8 db,min,
  24 dt, least dimension / 2) over lo >= max(ln/6, largest dimension, 450 mm); first tie <=
  so/2; <= 2 so anywhere. The default pack's BNBC 8.3.9 sets no rule for the beams of an ordinary moment frame
  that resist the earthquake: Chapter 6 governs them.
- 8.3.9.1(b) members not part of the lateral system: 8.3.4.2(a). The induced moments under
  twice the lateral displacement that 8.3.9.1(a) asks for are not computed: noted.

Members not part of the seismic-force-resisting system in SDC D (8.3.12, p. 1122-1123): the
induced moments under δu are not computed, so 8.3.12.3 applies: Pu <= Ag f'c / 10: 8.3.4.2 and
stirrups <= d/2 throughout; above: 8.3.5.3 and 8.3.5.4 (8.3.7.1 and 8.3.8 are the joints' and
shear's, :mod:`saengine.design.ductile_joints`).

Not here: materials (8.3.3.3, 8.3.3.4: the system rules), the strong-column rule (8.3.5.2) and
joints (8.3.7) and capacity-design shear (8.3.8, 8.3.10.3): :mod:`ductile_joints`; walls
(8.3.6) and foundations (8.3.11).

Transverse zones. An object type stores one transverse spacing today. Optional fields read
when present (on the pydantic model, or as dict keys): ``transverse.zone`` ``{spacing,
length?, first?}`` (the end zones: hoop spacing, length from the joint face, first hoop from
the face), ``transverse.splice`` ``{spacing}`` (over lap splices) and ``transverse.legsX``
(column tie legs running along the profile's x, counted down its depth; ``legs`` are those
running along y, counted across its width, like a beam's stirrup legs). Without a zone the
type's spacing is taken for the whole length, and the checks say so.

Units: mm, MPa, N, N·mm (kN, kN·m in the check rows).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from saengine.codes import context as code_context
from saengine.design.bars import round_down, spacing_step
from saengine.design.clauses import short_clause
from saengine.design.rc import (
    ROW_CLEAR,
    Bar,
    DesignError,
    Flexure,
    RcSection,
    bar_area,
    flexure,
)
from saengine.library.objects import CircleProfile, RectangleProfile

Frame = Literal["special", "intermediate", "ordinary"]
FRAMES: tuple[str, ...] = ("special", "intermediate", "ordinary")

# The plain-number limits of special moment frame members are the pack's
# ``detailing.special`` group, read when the checks run (default pack BNBC 2020): ``axialShare`` 0.10, the
# share of Ag f'c above which a frame member is designed as a column (8.3.4.1(a), 8.3.5.1,
# 8.3.9.2, 8.3.10.2, 8.3.12.2); ``beamRhoMax`` 0.025, the largest beam steel ratio (8.3.4.2(a));
# ``columnRho`` (0.01, 0.06), the column steel ratio limits (8.3.5.3(a)); ``beamMinWidth``
# 250 mm and ``beamMinRatio`` 0.3, the least beam width and width-to-depth ratio (8.3.4.1(c),
# (d)); ``columnMinDimension`` 300 mm and ``columnMinRatio`` 0.4, the least column dimension and
# least-to-perpendicular ratio (8.3.5.1); ``fytConfinementMax`` 700 MPa, the largest fyt in the
# confinement equations (8.3.3.4(c)); ``hxMax`` 350 mm, the largest spacing of cross ties or
# hoop legs across the section (8.3.5.4(c)); ``unsupportedClear`` 150 mm, the largest clear
# distance of an unsupported bar from a supported one (8.1.9.4(c)); ``beamFirstHoop`` 50 mm,
# the first hoop of a beam from the joint face (8.3.4.3(b), 8.3.10.4(b)).


def _special(name: str) -> float:
    """The pack's ``detailing.special`` limit ``name`` (default pack BNBC 2020: see above)."""
    return float(code_context.table("detailing").special[name])


def _column_rho() -> tuple[float, float]:
    """The pack's column steel ratio limits (least, largest) (default pack BNBC 2020 8.3.5.3(a): 0.01, 0.06)."""
    low, high = code_context.table("detailing").special.columnRho
    return (float(low), float(high))


# Bars of one row: their outer edges within this of each other [mm].
EDGE_TOLERANCE = 1.0

_CLAUSES = {
    "special": "8.3.4",
    "intermediate": "8.3.10.4",
    "ordinary": "8.3.9",
}


# ─────────────────────────────────── transverse zones ───────────────────────────────────


@dataclass(frozen=True)
class Zones:
    """The transverse reinforcement of an object type with its zones."""

    type: str
    dia: float
    spacing: float  # outside the zones (the object type's spacing)
    legs: int  # running along y, counted across the width (beam stirrup legs)
    legs_x: int | None = None  # running along x, counted down the depth; None: ``legs``
    zone_spacing: float | None = None
    zone_length: float | None = None
    zone_first: float | None = None
    splice_spacing: float | None = None

    @property
    def has_zone(self) -> bool:
        return self.zone_spacing is not None

    @property
    def in_zone(self) -> float:
        """Spacing in the end zones: the zone's, else the type's spacing."""
        return self.zone_spacing if self.zone_spacing is not None else self.spacing

    @property
    def across_depth(self) -> int:
        return self.legs_x if self.legs_x is not None else self.legs


def _get(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def zones_of(transverse: Any) -> Zones | None:
    """The :class:`Zones` of an object type's ``transverse`` (pydantic model or dict); the
    optional ``zone``, ``splice`` and ``legsX`` fields are read when present."""
    if transverse is None:
        return None
    zone = _get(transverse, "zone")
    splice = _get(transverse, "splice")
    legs_x = _get(transverse, "legsX")
    return Zones(
        type=str(_get(transverse, "type") or "stirrup"),
        dia=float(_get(transverse, "dia")),
        spacing=float(_get(transverse, "spacing")),
        legs=int(_get(transverse, "legs") or 2),
        legs_x=int(legs_x) if legs_x else None,
        zone_spacing=_float(_get(zone, "spacing")),
        zone_length=_float(_get(zone, "length")),
        zone_first=_float(_get(zone, "first")),
        splice_spacing=_float(_get(splice, "spacing")),
    )


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


# ─────────────────────────────────────── rows ───────────────────────────────────────


def _row(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    combination: str | None = None,
    note: str = "",
    utilisation: float | None = None,
) -> dict[str, Any]:
    """A check row, as ``saengine.design.check._check`` forms it (kept here so this module
    does not import check.py, which imports it)."""
    if utilisation is None:
        utilisation = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    utilisation = round(float(utilisation), 3) if math.isfinite(utilisation) else 99.0
    # The rows are serialised as strict JSON (no Infinity or NaN): a non-finite number is shown
    # as 0 with a note and the row fails.
    finite = math.isfinite(demand) and math.isfinite(capacity)
    if not finite:
        note = (note + "; " if note else "") + "a value is not finite"
        utilisation = 99.0
    return {
        "name": name,
        "demand": round(float(demand), 2) if math.isfinite(demand) else 0.0,
        "capacity": round(float(capacity), 2) if math.isfinite(capacity) else 0.0,
        "unit": unit,
        "utilisation": utilisation,
        "combination": combination,
        "ok": bool(utilisation <= 1.0),
        "note": note,
        "flag": False,
    }


def _at_most(name: str, provided: float, limit: float, unit: str, note: str = "", **kw: Any):
    return _row(name, provided, limit, unit, note=note, **kw)


def _at_least(name: str, required: float, provided: float, unit: str, note: str = "", **kw: Any):
    return _row(name, required, provided, unit, note=note, **kw)


@dataclass
class Detailing:
    """The detailing checks of one member, its notes and the requirements behind them."""

    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    need: BeamNeed | ColumnNeed | None = None


# ──────────────────────────────────── geometry helpers ────────────────────────────────────


def _rectangle(section: RcSection) -> tuple[float, float]:
    p = section.profile
    if isinstance(p, RectangleProfile):
        return p.xDim, p.yDim
    if isinstance(p, CircleProfile):
        return 2 * p.radius, 2 * p.radius
    raise DesignError("rectangle and circle profiles only")


def _outer_edge(bar: Bar, axis: str, sign: int) -> float:
    """How far the bar's outer edge reaches towards a face: rc lays every bar of the outer row
    resting on the tie, so bars of different diameters on one face share this edge while
    their centres do not."""
    return sign * (bar.y if axis == "y" else bar.x) + bar.dia / 2


def _outer_row(bars: Iterable[Bar], axis: str, sign: int) -> list[Bar]:
    bars = list(bars)
    if not bars:
        return []
    extreme = max(_outer_edge(b, axis, sign) for b in bars)
    return [b for b in bars if _outer_edge(b, axis, sign) >= extreme - EDGE_TOLERANCE]


def face_steel(section: RcSection, top: bool) -> list[Bar]:
    """The bars of the top (or bottom) face of a beam: its outer row and any further rows
    inwards as :func:`saengine.design.rc._rectangle_bars` lays them (each row's outer edge
    ``ROW_CLEAR`` inside the previous row's largest bar). Side (skin) bars are not counted,
    though they may lie in the same half of the section."""
    sign = 1 if top else -1
    rest = [b for b in section.bars if sign * b.y > 0]
    row = _outer_row(rest, "y", sign)
    taken: list[Bar] = []
    while row:
        taken += row
        rest = [b for b in rest if b not in row]
        inner_edge = min(sign * b.y - b.dia / 2 for b in row) - ROW_CLEAR
        row = [b for b in rest if abs(_outer_edge(b, "y", sign) - inner_edge) <= EDGE_TOLERANCE]
    return taken


def _face_depth(section: RcSection, top: bool) -> float | None:
    """Effective depth of the top (hogging) or bottom (sagging) steel of :func:`face_steel`."""
    bars = face_steel(section, top)
    if not bars:
        return None
    centroid = sum(b.area * b.y for b in bars) / sum(b.area for b in bars)
    return section.depth / 2 + (centroid if top else -centroid)


def _effective_depth(section: RcSection) -> float:
    """The smaller effective depth of the two faces (the spacing limits use d)."""
    depths = [d for d in (_face_depth(section, True), _face_depth(section, False)) if d]
    if not depths:
        raise DesignError("no bars on either face")
    return min(depths)


def _smallest_bar(section: RcSection) -> float:
    return min(b.dia for b in section.bars)


def _face_bars(section: RcSection, axis: str, sign: int) -> list[tuple[float, float]]:
    """(position along the face, diameter) of the outer bars of a face: ``axis`` "y" with
    ``sign`` +1 is the top face (its bars' x), "x" with +1 the right face (their y). The outer
    row is taken by the bars' outer edges, so larger corner bars stay in it."""
    along = (lambda b: b.x) if axis == "y" else (lambda b: b.y)
    return sorted((along(b), b.dia) for b in _outer_row(section.bars, axis, sign))


def held_required(face: list[tuple[float, float]]) -> int:
    """Bars of a face that need a hoop corner or cross tie (8.1.9.4(c)): every corner and
    alternate bar, all of them where adjacent bars are more than 150 mm clear apart (as
    :func:`saengine.design.bars.column_ties` arranges ties)."""
    n = len(face)
    if n <= 2:
        return n
    gaps = [face[k + 1][0] - face[k][0] - (face[k][1] + face[k + 1][1]) / 2 for k in range(n - 1)]
    if max(gaps) > _special("unsupportedClear"):
        return n
    return 2 + (n - 2) // 2


def _support_rows(
    section: RcSection, zones: Zones, clause: str, faces: Iterable[tuple[str, int]]
) -> list[dict[str, Any]]:
    rows = []
    for axis, sign in faces:
        face = _face_bars(section, axis, sign)
        if len(face) <= 2:
            continue
        need = held_required(face)
        legs = zones.legs if axis == "y" else zones.across_depth
        name = {("y", 1): "top", ("y", -1): "bottom", ("x", 1): "right", ("x", -1): "left"}[
            (axis, sign)
        ]
        rows.append(
            _at_least(
                f"Lateral support of the {name} bars ({clause}, 8.1.9.4(c))",
                need,
                legs,
                "legs",
                note=f"{len(face)} bars on the face: every corner and alternate bar held, none "
                f"more than {_special('unsupportedClear'):g} mm clear from a held one; "
                + ("legs" if axis == "y" else "legsX")
                + f" = {legs}",
            )
        )
    return rows


# ─────────────────────────────────────── beams ───────────────────────────────────────


@dataclass(frozen=True)
class BeamNeed:
    """What the seismic detailing asks of a beam (for the design mode)."""

    frame: str
    lateral: bool
    d: float
    zone_length: float | None  # hoops/stirrups over this length from each face (2h)
    zone_spacing: float | None
    zone_rule: str
    first: float | None
    outside_spacing: float | None  # None: no spacing rule of Sec 8.3 outside the zones
    outside_rule: str
    splice_spacing: float | None
    min_width: float | None
    rho_min: float | None
    rho_max: float | None
    positive_share: float | None  # Mn+ >= share x Mn- at the face
    any_share: float | None  # Mn+, Mn- >= share x max Mn anywhere


def beam_need(section: RcSection, frame: str, transverse_dia: float, lateral: bool = True):
    """The requirements of :func:`beam_checks` for a beam section."""
    if frame not in FRAMES:
        raise ValueError(f"unknown frame type '{frame}'")
    _, h = _rectangle(section)
    d = _effective_depth(section)
    db = _smallest_bar(section)
    rho_min = max(0.25 * math.sqrt(section.fc), 1.4) / section.fy
    longitudinal = (frame == "special") or (not lateral)  # 8.3.4.2(a): SMF, 8.3.9.1, 8.3.12
    zone = frame in ("special", "intermediate") and lateral
    if zone:
        limits = {"d/4": d / 4, "8 db": 8 * db, "24 dh": 24 * transverse_dia, "300 mm": 300.0}
        governing = min(limits, key=lambda k: limits[k])
        zone_spacing = limits[governing]
        zone_rule = f"min(d/4, 8 db, 24 dh, 300 mm), {governing} governs"
    else:
        zone_spacing, zone_rule = None, ""
    outside = d / 2 if (zone or (frame == "special" and not lateral)) else None
    return BeamNeed(
        frame=frame,
        lateral=lateral,
        d=d,
        zone_length=2 * h if zone else None,
        zone_spacing=zone_spacing,
        zone_rule=zone_rule,
        first=_special("beamFirstHoop") if zone else None,
        outside_spacing=outside,
        outside_rule="d/2" if outside is not None else "",
        splice_spacing=min(d / 4, 100.0) if longitudinal and frame == "special" else None,
        min_width=max(_special("beamMinWidth"), _special("beamMinRatio") * h)
        if frame == "special" and lateral
        else None,
        rho_min=rho_min if longitudinal else None,
        rho_max=_special("beamRhoMax") if longitudinal else None,
        positive_share=(1 / 2 if longitudinal else 1 / 3 if frame == "intermediate" else None),
        any_share=(1 / 4 if longitudinal else 1 / 5 if frame == "intermediate" else None),
    )


def beam_checks(
    section: RcSection,
    transverse: Any,
    frame: str,
    *,
    clear_span: float | None = None,
    axial: tuple[float, str | None] = (0.0, None),
    supports: Iterable[tuple[float, float]] = (),
    capacities: Mapping[bool, Flexure] | None = None,
    lateral: bool = True,
    zones: Zones | None = None,
) -> Detailing:
    """The seismic detailing checks of a beam (see the module notes).

    ``transverse``: the object type's ``reinforcement.transverse`` (``zones`` overrides what
    is read from it). ``clear_span``: ln [mm], face to face of the supports. ``axial``: the
    largest factored axial compression [N] of all combinations and the combination. ``supports``:
    (c1, c2) [mm] of the column at each end, c1 along the beam's span. ``capacities``: the
    flexural capacities by hogging (as check.py caches them; computed when None)."""
    out = Detailing()
    if frame not in FRAMES:
        raise ValueError(f"unknown frame type '{frame}'")
    zones = zones or zones_of(transverse)
    b, h = _rectangle(section)
    dia = zones.dia if zones else 0.0
    need = beam_need(section, frame, dia, lateral)
    out.need = need
    clause = _CLAUSES[frame] if lateral else ("8.3.12.3" if frame == "special" else "8.3.9.1")
    pu, combination = axial
    ag_fc = b * h * section.fc
    if frame == "ordinary" and lateral:
        out.notes.append(
            f"{short_clause('ductileMembers', 'ordinary')} sets no rule for the beams of an "
            "ordinary moment frame that resist the "
            "earthquake: Chapter 6 governs them"
        )
        return out
    if not lateral:
        out.notes.append(
            "not part of the seismic-force-resisting system: the moments induced by the design "
            "displacement are not computed, so "
            + (
                "Sec 8.3.12.3 applies (8.3.12.1)"
                if frame == "special"
                else "Sec 8.3.9.1(b) is applied; 8.3.9.1(a) (members whose induced moment under "
                "twice the lateral displacement exceeds φMn) is not checked"
            )
        )
    if pu > _special("axialShare") * ag_fc:
        note = (
            "Pu above 0.1 Ag f'c: detail the member as a column ("
            + {"special": "8.3.5", "intermediate": "8.3.10.5", "ordinary": "8.3.9.2"}[frame]
            + ")"
        )
        axial_clause = {"special": "8.3.4.1(a)", "intermediate": "8.3.10.2"}.get(
            frame, "8.3.9.1(a)"
        )
        out.checks.append(
            _at_most(
                f"Axial force of a flexural member ({axial_clause})",
                pu / 1e3,
                _special("axialShare") * ag_fc / 1e3,
                "kN",
                note,
                combination=combination,
            )
        )

    if frame == "special" and lateral:
        if clear_span is not None:
            out.checks.append(
                _at_least(
                    "Clear span ≥ 4d (8.3.4.1(b))",
                    4 * need.d,
                    clear_span,
                    "mm",
                    f"d = {need.d:.0f} mm",
                )
            )
        else:
            out.notes.append("clear span not given: 8.3.4.1(b) ln ≥ 4d not checked")
        out.checks.append(
            _at_least(
                "Width to depth ≥ 0.3 (8.3.4.1(c))",
                _special("beamMinRatio"),
                b / h,
                "",
                f"b = {b:g} mm, h = {h:g} mm",
            )
        )
        out.checks.append(
            _at_least("Width ≥ 250 mm (8.3.4.1(d))", _special("beamMinWidth"), b, "mm")
        )
        for k, (c1, c2) in enumerate(supports):
            limit = c2 + 2 * min(c2, 0.75 * c1)
            out.checks.append(
                _at_most(
                    f"Width within the supporting column, end {k + 1} (8.3.4.1(d))",
                    b,
                    limit,
                    "mm",
                    f"c2 + 2 min(c2, 0.75 c1) with c1 = {c1:g}, c2 = {c2:g} mm (Figure 6.8.1)",
                )
            )

    if need.rho_min is not None:
        counts = []
        for top, face in ((True, "top"), (False, "bottom")):
            bars = face_steel(section, top)
            counts.append(len(bars))
            area = sum(x.area for x in bars)
            d_face = _face_depth(section, top) or need.d
            rho = area / (b * d_face)
            out.checks.append(
                _at_least(
                    f"Least steel ratio, {face} (8.3.4.2(a))",
                    100 * need.rho_min,
                    100 * rho,
                    "%",
                    f"max(0.25 √f'c, 1.4)/fy (Figure 6.8.2); As = {area:.0f} mm² of the "
                    f"{face} rows (side bars not counted), d = {d_face:.0f} mm",
                )
            )
            out.checks.append(
                _at_most(
                    f"Largest steel ratio, {face} (8.3.4.2(a))",
                    100 * rho,
                    100 * _special("beamRhoMax"),
                    "%",
                )
            )
        out.checks.append(
            _at_least(
                "Continuous bars top and bottom (8.3.4.2(a))",
                2,
                min(counts),
                "bars",
                f"{counts[0]} top, {counts[1]} bottom (side bars not counted); the type's "
                "bars are taken as running its full length",
            )
        )

    if need.positive_share is not None:
        caps = capacities or {hog: flexure(section, hog) for hog in (False, True)}
        positive, negative = caps[False].mn, caps[True].mn
        fraction = "one-half" if need.positive_share == 0.5 else "one-third"
        moment_clause = "8.3.10.4(a)" if lateral and frame == "intermediate" else "8.3.4.2(a)"
        out.checks.append(
            _at_least(
                f"Positive moment strength at the face ({moment_clause})",
                need.positive_share * negative / 1e6,
                positive / 1e6,
                "kN·m",
                f"Mn+ ≥ {fraction} Mn-: Mn- = {negative / 1e6:.1f} kN·m",
            )
        )
        largest = max(positive, negative)
        out.checks.append(
            _at_least(
                f"Moment strength along the member ({moment_clause})",
                need.any_share * largest / 1e6,
                min(positive, negative) / 1e6,
                "kN·m",
                f"Mn+ and Mn- ≥ 1/{round(1 / need.any_share)} of max Mn at the faces "
                f"({largest / 1e6:.1f} kN·m); one bar layout per type",
            )
        )

    if need.splice_spacing is not None:
        if zones is not None and zones.splice_spacing is not None:
            out.checks.append(
                _at_most(
                    "Hoops over lap splices (8.3.4.2(b))",
                    zones.splice_spacing,
                    need.splice_spacing,
                    "mm",
                    "min(d/4, 100 mm)",
                )
            )
        out.notes.append(
            f"lap splices (8.3.4.2(b)): not within the joints nor within 2h = {2 * h:.0f} mm of "
            f"their faces, enclosed by hoops at ≤ {need.splice_spacing:.0f} mm"
        )

    if need.zone_spacing is None and need.outside_spacing is None:
        return out
    if zones is None:
        out.checks.append(
            _row(
                f"Transverse reinforcement ({clause})",
                1,
                0,
                "",
                note="no stirrups or hoops",
                utilisation=math.inf,
            )
        )
        return out
    kind = "Hoop" if frame == "special" else "Stirrup"
    if need.zone_spacing is not None:
        zone_clause = "8.3.4.3(b)" if frame == "special" else "8.3.10.4(b)"
        if not zones.has_zone:
            out.notes.append(
                f"no confinement zone given: spacing {zones.spacing:g} mm used for the whole length"
            )
        if zones.zone_length is not None:
            out.checks.append(
                _at_least(
                    f"{kind} zone length ({'8.3.4.3(a)' if frame == 'special' else '8.3.10.4(b)'})",
                    need.zone_length,
                    zones.zone_length,
                    "mm",
                    "2h from each joint face",
                )
            )
        out.checks.append(
            _at_most(
                f"{kind} spacing at the ends ({zone_clause})",
                zones.in_zone,
                need.zone_spacing,
                "mm",
                need.zone_rule
                + f" over {need.zone_length:.0f} mm from each face"
                + ("" if zones.has_zone else "; no zone given: the type's spacing"),
            )
        )
        if zones.zone_first is not None:
            out.checks.append(
                _at_most(
                    f"First {kind.lower()} from the face ({zone_clause})",
                    zones.zone_first,
                    _special("beamFirstHoop"),
                    "mm",
                )
            )
        else:
            out.notes.append(
                f"first {kind.lower()} within {_special('beamFirstHoop'):g} mm of the support face "
                f"({zone_clause})"
            )
        if frame == "special":
            out.checks += _support_rows(section, zones, "8.3.4.3(c)", (("y", 1), ("y", -1)))
            out.notes.append(
                "hoops in the end zones: closed, with 135° seismic hooks (8.3.4.3(d)); "
                "also over 2h on both sides of any other section where flexural yielding may "
                "occur (8.3.4.3(a)(ii))"
            )
    if need.outside_spacing is not None:
        outside_clause = {
            "special": "8.3.4.3(c)" if lateral else "8.3.12.3(b)",
            "intermediate": "8.3.10.4(c)",
        }.get(frame, clause)
        out.checks.append(
            _at_most(
                f"{kind if lateral else 'Stirrup'} spacing elsewhere ({outside_clause})",
                zones.spacing,
                need.outside_spacing,
                "mm",
                f"d/2, d = {need.d:.0f} mm",
            )
        )
    return out


# ─────────────────────────────────────── columns ───────────────────────────────────────


@dataclass(frozen=True)
class ColumnNeed:
    """What the seismic detailing asks of a column (for the design mode)."""

    frame: str
    lateral: bool
    applies: bool  # False: no tie rule of Sec 8.3 for this member (e.g. OMF, Pu <= 0.1 Ag f'c)
    zone_length: float | None  # lo
    zone_length_rule: str
    zone_spacing: float | None  # largest spacing in lo
    zone_rule: str
    so: float | None  # 8.3.5.4(b)(iii) (SMF) or the IMF/OMF so
    hx: float | None
    first: float | None
    outside_spacing: float | None
    outside_rule: str
    splice_spacing: float | None
    ash_s: tuple[float, float] | None  # required Ash / s [mm²/mm], bc along x, along y
    rho_s: float | None  # spirals and circular hoops
    full_height: bool = False
    notes: tuple[str, ...] = ()
    first_rule: str = "so/2"
    #: Clauses of the zone rows (length, spacing, first, outside); None: by frame type.
    clauses: tuple[tuple[str, str], ...] | None = None


def _column_depth(section: RcSection) -> float:
    """The smallest effective depth of a column over its four faces [mm]: the section
    dimension less the distance from the opposite face to the centroid of the outer bar row
    (0.8 D for a circle, as ACI 318-19 22.5.2.2 takes for shear: the default pack's BNBC is silent)."""
    if isinstance(section.profile, CircleProfile):
        return 0.8 * 2 * section.profile.radius
    b, h = _rectangle(section)
    depths = []
    for axis, size in (("y", h), ("x", b)):
        for sign in (1, -1):
            row = _outer_row(section.bars, axis, sign)
            if not row:
                continue
            coord = sum((r.y if axis == "y" else r.x) * r.area for r in row) / sum(
                r.area for r in row
            )
            depths.append(size / 2 + sign * coord)
    if not depths:
        raise DesignError("no bars in the column section")
    return min(depths)


def _hx(core: float, tie_dia: float, db: float, legs: int) -> float:
    """Centre-to-centre spacing of the bars the legs hold across a core ``core`` wide (to the
    outside of the hoops): (core - 2 dt - db) / (legs - 1). A closed rectangular hoop has two
    legs each way at least, so fewer legs are taken as two (the corner bars only)."""
    return (core - 2 * tie_dia - db) / (max(legs, 2) - 1)


def so_special(hx: float) -> float:
    """so = 100 + (350 - hx) / 3, not above 150 mm and not taken below 100 mm (8.3.5.4(b))."""
    return min(150.0, max(100.0, 100 + (350 - hx) / 3))


def ash_per_spacing(bc: float, ag: float, ach: float, fc: float, fyt: float) -> float:
    """Least Ash / s [mm²/mm] of rectangular hoops across a core dimension ``bc``: the larger
    of Eq. 6.8.7 and Eq. 6.8.8, fyt at most 700 MPa (8.3.3.4(c))."""
    fyt = min(fyt, _special("fytConfinementMax"))
    return max(0.3 * bc * fc / fyt * (ag / ach - 1), 0.09 * bc * fc / fyt)


def rho_s_required(ag: float, ach: float, fc: float, fyt: float) -> float:
    """Least volumetric ratio of spirals and circular hoops: Eq. 6.8.6 and Eq. 6.6.12."""
    fyt = min(fyt, _special("fytConfinementMax"))
    return max(0.12 * fc / fyt, 0.45 * (ag / ach - 1) * fc / fyt)


def column_need(
    section: RcSection,
    frame: str,
    cover: float,
    zones: Zones,
    *,
    clear_height: float | None = None,
    axial: float = 0.0,
    lateral: bool = True,
    full_height: bool = False,
) -> ColumnNeed:
    """The requirements of :func:`column_checks`. ``zones``: the ties (their diameter and legs
    set hx, so and Ash); ``axial``: the largest factored axial compression [N]."""
    if frame not in FRAMES:
        raise ValueError(f"unknown frame type '{frame}'")
    b, h = _rectangle(section)
    least, largest = min(b, h), max(b, h)
    db = _smallest_bar(section)
    dt = zones.dia
    fc, fyt = section.fc, section.fy  # one rebar material for the bars and the ties
    above = axial > _special("axialShare") * section.gross_area * fc
    notes: list[str] = []
    circle = isinstance(section.profile, CircleProfile)
    special = frame == "special" and (lateral or above)
    if frame == "special" and not lateral and not above:
        # 8.3.12.3(b): flexural-member rules, stirrups <= d/2 throughout.
        d = _effective_depth(section)
        return ColumnNeed(
            frame,
            lateral,
            True,
            None,
            "",
            None,
            "",
            None,
            None,
            None,
            d / 2,
            "d/2 (8.3.12.3(b))",
            None,
            None,
            None,
            notes=("Pu ≤ Ag f'c/10: 8.3.12.3(b) flexural-member rules",),
        )
    if special:
        lo_parts = {"h": largest, "ln/6": (clear_height or 0) / 6, "450 mm": 450.0}
        if clear_height is None:
            notes.append("clear height not given: lo from the section depth and 450 mm only")
        lo_rule = "max(h, ln/6, 450 mm)"
        ash_s = rho_s = None
        hx = None
        if circle:
            dc = 2 * section.profile.radius - 2 * cover
            rho_s = rho_s_required(section.gross_area, math.pi * dc**2 / 4, fc, fyt)
            so = 150.0
            notes.append("circular section: hx and so = 100 + (350 - hx)/3 not applied")
        else:
            bc_x, bc_y = b - 2 * cover, h - 2 * cover
            ach = bc_x * bc_y
            ash_s = (
                ash_per_spacing(bc_x, section.gross_area, ach, fc, fyt),
                ash_per_spacing(bc_y, section.gross_area, ach, fc, fyt),
            )
            hx = max(_hx(bc_x, dt, db, zones.legs), _hx(bc_y, dt, db, zones.across_depth))
            so = so_special(hx)
        limits = {"least dimension/4": least / 4, "6 db": 6 * db, "so": so}
        outside = {"6 db": 6 * db, "150 mm": 150.0}
        clauses = None
        if not above:
            # Pu <= 0.1 Ag f'c: a flexural member of Sec 8.3.4 (8.3.4.1(a), 8.3.5.1). SAEngine
            # keeps the column rules of 8.3.5.4 and adds the hoop rules of 8.3.4.3, the
            # stricter of each (8.3.4.3(b) d/4 can be tighter than b/4).
            d = _column_depth(section)
            limits.update({"d/4": d / 4, "24 dh": 24 * dt, "300 mm": 300.0})
            lo_parts["2h"] = 2 * largest
            lo_rule = "max(h, ln/6, 450 mm, 2h)"
            outside["d/2"] = d / 2
            notes.append(
                "Pu ≤ 0.1 Ag f'c: a flexural member (8.3.4.1(a), 8.3.5.1); SAEngine applies "
                "the column rules of 8.3.5.4 and the hoop rules of 8.3.4.3 (2h, d/4, 8 db, "
                f"24 dh, 300 mm, d/2 elsewhere), the stricter of each; d = {d:.0f} mm"
            )
            clauses = (
                ("length", "8.3.5.4(d), 8.3.4.3(a)"),
                ("spacing", "8.3.5.4(b), 8.3.4.3(b)"),
                ("outside", "8.3.5.4(f), 8.3.4.3(c)"),
            )
        governing = min(limits, key=lambda k: limits[k])
        out_governing = min(outside, key=lambda k: outside[k])
        return ColumnNeed(
            frame=frame,
            lateral=lateral,
            applies=True,
            zone_length=max(lo_parts.values()),
            zone_length_rule=lo_rule,
            zone_spacing=limits[governing],
            zone_rule=f"min({', '.join(limits)}), {governing} governs",
            so=so,
            hx=hx,
            first=so / 2,
            outside_spacing=outside[out_governing],
            outside_rule=f"min({', '.join(outside)}), {out_governing} governs",
            splice_spacing=min(least / 4, 100.0),
            ash_s=ash_s,
            rho_s=rho_s,
            full_height=full_height,
            notes=tuple(notes),
            clauses=clauses,
        )
    if frame == "intermediate" and lateral and not above:
        # 8.3.10.2 (p1114): Pu <= 0.1 Ag f'c follows 8.3.10.4 (the beam rules), not 8.3.10.5.
        # The length: the stricter of the beam rule's 2h (8.3.10.4(b)) and the column rule's
        # lo = max(ln/6, largest dimension, 450 mm) (8.3.10.5(a)): it is still a column (X13 of
        # the usability walk: lo from the beam rule alone). The spacing keeps 8.3.10.4.
        d = _column_depth(section)
        limits = {"d/4": d / 4, "8 db": 8 * db, "24 dt": 24 * dt, "300 mm": 300.0}
        governing = min(limits, key=lambda k: limits[k])
        if clear_height is None:
            notes.append("clear height not given: lo from the section and 450 mm only")
        lo_parts = {
            "2h": 2 * largest,
            "ln/6": (clear_height or 0) / 6,
            "h": largest,
            "450 mm": 450.0,
        }
        lo_by = max(lo_parts, key=lambda k: lo_parts[k])
        return ColumnNeed(
            frame=frame,
            lateral=lateral,
            applies=True,
            zone_length=lo_parts[lo_by],
            zone_length_rule=(
                f"max(2h, ln/6, h, 450 mm), {lo_by} governs; h the largest dimension"
            ),
            zone_spacing=limits[governing],
            zone_rule=f"min(d/4, 8 db, 24 dt, 300 mm), {governing} governs; d = {d:.0f} mm",
            so=limits[governing],
            hx=None,
            first=_special("beamFirstHoop"),
            outside_spacing=d / 2,
            outside_rule="d/2 throughout",
            splice_spacing=None,
            ash_s=None,
            rho_s=None,
            full_height=full_height,
            notes=(
                *notes,
                "Pu ≤ 0.1 Ag f'c: the reinforcement details of 8.3.10.4 apply (8.3.10.2)",
            ),
            first_rule="50 mm",
            clauses=(
                ("length", "8.3.10.4(b), 8.3.10.5(a)"),
                ("spacing", "8.3.10.4(b)"),
                ("first", "8.3.10.4(b)"),
                ("outside", "8.3.10.4(c)"),
            ),
        )
    # Intermediate (8.3.10.5) and ordinary (8.3.9.2, Pu > 0.1 Ag f'c only) columns, and the
    # columns of IMF/OMF not in the lateral system (8.3.3.1(d): Sec 8.3.9).
    imf = frame == "intermediate" and lateral
    if not imf and not above:
        return ColumnNeed(
            frame,
            lateral,
            False,
            None,
            "",
            None,
            "",
            None,
            None,
            None,
            None,
            "",
            None,
            None,
            None,
            notes=("Pu ≤ 0.1 Ag f'c: no tie rule of Sec 8.3.9.2",),
        )
    limits = {"8 db": 8 * db, "24 dt": 24 * dt, "least dimension/2": least / 2}
    if imf:
        limits["300 mm"] = 300.0
    governing = min(limits, key=lambda k: limits[k])
    so = limits[governing]
    if clear_height is None:
        notes.append("clear height not given: lo from the section and 450 mm only")
    lo = max((clear_height or 0) / 6, largest, 450.0)
    return ColumnNeed(
        frame=frame,
        lateral=lateral,
        applies=True,
        zone_length=lo,
        zone_length_rule="max(ln/6, largest dimension, 450 mm)",
        zone_spacing=so,
        zone_rule=f"so = min({', '.join(limits)}), {governing} governs",
        so=so,
        hx=None,
        first=so / 2,
        outside_spacing=2 * so,
        outside_rule="2 so",
        splice_spacing=None,
        ash_s=None,
        rho_s=None,
        full_height=full_height,
        notes=tuple(notes),
    )


def column_checks(
    section: RcSection,
    transverse: Any,
    frame: str,
    cover: float,
    *,
    clear_height: float | None = None,
    axial: tuple[float, str | None] = (0.0, None),
    lateral: bool = True,
    full_height: bool = False,
    zones: Zones | None = None,
) -> Detailing:
    """The seismic detailing checks of a column (see the module notes).

    ``cover``: the clear cover to the ties (``reinforcement.cover``). ``clear_height``: ln
    [mm], between the beam soffit and the floor. ``axial``: the largest factored axial
    compression [N] and its combination. ``full_height``: confinement over the whole height
    (8.3.5.2(c), a joint failing the strong-column rule; 8.3.5.4(e), under a discontinued
    wall)."""
    out = Detailing()
    if frame not in FRAMES:
        raise ValueError(f"unknown frame type '{frame}'")
    zones = zones or zones_of(transverse)
    b, h = _rectangle(section)
    least, largest = min(b, h), max(b, h)
    pu, _ = axial
    ag = section.gross_area
    circle = isinstance(section.profile, CircleProfile)
    above = pu > _special("axialShare") * ag * section.fc

    if frame == "special" and lateral:
        if not above:
            out.notes.append(
                "Pu ≤ 0.1 Ag f'c: outside the scope of 8.3.5 (8.3.5.1); the column rules are "
                "applied with the hoop rules of 8.3.4.3, the stricter of each"
            )
        if not circle:
            out.checks.append(
                _at_least(
                    "Least dimension ≥ 300 mm (8.3.5.1(a))",
                    _special("columnMinDimension"),
                    least,
                    "mm",
                )
            )
            out.checks.append(
                _at_least(
                    "Least to perpendicular dimension ≥ 0.4 (8.3.5.1(b))",
                    _special("columnMinRatio"),
                    least / largest,
                    "",
                    f"{b:g} x {h:g} mm",
                )
            )
        else:
            out.checks.append(
                _at_least(
                    "Least dimension ≥ 300 mm (8.3.5.1(a))",
                    _special("columnMinDimension"),
                    2 * section.profile.radius,
                    "mm",
                )
            )
    smf_bars = frame == "special" and (lateral or above)
    if smf_bars:
        rho = section.steel_area / ag
        low, high = _column_rho()
        clause = "8.3.5.3(a)" if lateral else "8.3.12.3(c), 8.3.5.3(a)"
        out.checks.append(_at_least(f"Least steel ratio ({clause})", 100 * low, 100 * rho, "%"))
        out.checks.append(_at_most(f"Largest steel ratio ({clause})", 100 * rho, 100 * high, "%"))
        out.notes.append(
            "lap splices only within the centre half of the column height, designed as tension "
            "splices (8.3.5.3(b))"
        )
    if zones is None:
        # Whether Sec 8.3 asks for ties at all does not depend on them: ask with a stand-in.
        stand_in = Zones(type="tie", dia=0.0, spacing=0.0, legs=2)
        need = column_need(
            section, frame, cover, stand_in, clear_height=clear_height, axial=pu, lateral=lateral
        )
        if not need.applies:
            out.notes += list(need.notes)
            return out
        out.checks.append(_row("Ties (8.3)", 1, 0, "", note="no ties", utilisation=math.inf))
        return out
    if not circle and min(zones.legs, zones.across_depth) < 2:
        out.notes.append(
            "fewer than 2 tie legs in a direction: a closed hoop has 2 legs each way; hx is "
            "taken between the corner bars, Ash with the legs given"
        )
    need = column_need(
        section,
        frame,
        cover,
        zones,
        clear_height=clear_height,
        axial=pu,
        lateral=lateral,
        full_height=full_height,
    )
    out.need = need
    out.notes += list(need.notes)
    if not need.applies:
        return out
    if need.zone_length is None:  # 8.3.12.3(b): stirrups <= d/2 throughout
        out.checks.append(
            _at_most(
                "Tie spacing (8.3.12.3(b))",
                zones.spacing,
                need.outside_spacing,
                "mm",
                need.outside_rule,
            )
        )
        return out

    if frame == "special":
        zc = {"length": "8.3.5.4(d)", "spacing": "8.3.5.4(b)", "outside": "8.3.5.4(f)"}
    elif frame == "intermediate" and lateral:
        zc = {
            "length": "8.3.10.5(a)",
            "spacing": "8.3.10.5(a)",
            "first": "8.3.10.5(b)",
            "outside": "8.3.10.5(d)",
        }
    else:
        zc = {
            "length": "8.3.9.2(b)",
            "spacing": "8.3.9.2(b)",
            "first": "8.3.9.2(c)",
            "outside": "8.3.9.2(d)",
        }
    zc.setdefault("first", "Figure 6.8.8")
    if need.clauses:
        zc.update(dict(need.clauses))
    if not zones.has_zone:
        out.notes.append(
            f"no confinement zone given: spacing {zones.spacing:g} mm used for the whole length"
        )
    if zones.zone_length is not None:
        out.checks.append(
            _at_least(
                f"Confinement length lo ({zc['length']})",
                need.zone_length,
                zones.zone_length,
                "mm",
                need.zone_length_rule,
            )
        )
    else:
        out.notes.append(
            f"ties at the zone spacing over lo = {need.zone_length:.0f} mm "
            f"({need.zone_length_rule}) from each joint face ({zc['length']})"
        )
    out.checks.append(
        _at_most(
            f"Tie spacing in lo ({zc['spacing']})",
            zones.in_zone,
            need.zone_spacing,
            "mm",
            need.zone_rule + ("" if zones.has_zone else "; no zone given: the type's spacing"),
        )
    )
    if zones.zone_first is not None:
        out.checks.append(
            _at_most(
                f"First tie from the face ({zc['first']})",
                zones.zone_first,
                need.first,
                "mm",
                need.first_rule,
            )
        )
    else:
        out.notes.append(
            f"first tie within {need.first_rule} = {need.first:.0f} mm of the joint face"
        )
    if frame == "special":
        spacings = [("in lo", zones.in_zone)]
        if full_height:
            spacings.append(("over the full height", zones.spacing))
        for where, s in spacings:
            if need.ash_s is not None:
                legs_by_bc = (zones.legs, zones.across_depth)
                for k, axis in enumerate(("x", "y")):
                    required = need.ash_s[k] * s
                    provided = legs_by_bc[k] * bar_area(zones.dia)
                    out.checks.append(
                        _at_least(
                            f"Confinement Ash, bc along {axis}, {where} (8.3.5.4(a)(ii))",
                            required,
                            provided,
                            "mm²",
                            f"max(Eq. 6.8.7, Eq. 6.8.8) at s = {s:g} mm; "
                            f"{legs_by_bc[k]} legs Ø{zones.dia:g}",
                        )
                    )
            elif need.rho_s is not None:
                dc = 2 * section.profile.radius - 2 * cover
                provided = 4 * bar_area(zones.dia) / (dc * s)
                out.checks.append(
                    _at_least(
                        f"Confinement ρs, {where} (8.3.5.4(a)(i))",
                        100 * need.rho_s,
                        100 * provided,
                        "%",
                        f"max(Eq. 6.8.6, Eq. 6.6.12); Dc = {dc:.0f} mm, s = {s:g} mm",
                    )
                )
        if need.hx is not None:
            out.checks.append(
                _at_most(
                    "Cross-tie spacing hx (8.3.5.4(c))",
                    need.hx,
                    _special("hxMax"),
                    "mm",
                    f"so = {need.so:.0f} mm from hx",
                )
            )
            out.checks += _support_rows(
                section, zones, "8.3.5.4(a)(iii)", (("y", 1), ("y", -1), ("x", 1), ("x", -1))
            )
        if zones.splice_spacing is not None:
            out.checks.append(
                _at_most(
                    "Ties over lap splices (Figure 6.8.8)",
                    zones.splice_spacing,
                    need.splice_spacing,
                    "mm",
                    "min(least dimension/4, 100 mm)",
                )
            )
    outside_limit = need.zone_spacing if full_height else need.outside_spacing
    out.checks.append(
        _at_most(
            "Tie spacing over the full height (8.3.5.2(c))"
            if full_height
            else f"Tie spacing outside lo ({zc['outside']})",
            zones.spacing,
            outside_limit,
            "mm",
            need.zone_rule if full_height else need.outside_rule,
        )
    )
    return out


# ─────────────────────────────────────── design mode ───────────────────────────────────────


def minimum_dimensions(kind: str, frame: str, depth: float | None = None) -> dict[str, float]:
    """Least section dimensions of the seismic detailing [mm]: a special-frame beam of overall
    depth ``depth`` needs ``width`` >= max(250 mm, 0.3 h) (8.3.4.1(c), (d)); a special-frame
    column ``least`` >= 300 mm and ``ratio`` >= 0.4 (8.3.5.1). Other frames: none."""
    if frame != "special":
        return {}
    if kind == "beam":
        return {"width": max(_special("beamMinWidth"), _special("beamMinRatio") * (depth or 0))}
    return {"least": _special("columnMinDimension"), "ratio": _special("columnMinRatio")}


def propose_zones(
    need: BeamNeed | ColumnNeed,
    dia: float,
    legs: int,
    legs_x: int | None = None,
    shear_spacing: float | None = None,
    step: float | None = None,
) -> dict[str, Any] | None:
    """The transverse fields a proposal can write for the seismic zones: ``{"spacing",
    "zone": {"length", "spacing", "first"}, "splice"?: {"spacing"}}`` with spacings rounded
    down to ``step``, from a :class:`BeamNeed` or :class:`ColumnNeed` and the ties (``dia``,
    ``legs``, ``legs_x``; for a column they set hx, so and Ash, so ``need`` must have been
    formed with the same ties). ``shear_spacing``: the largest spacing the shear design allows
    (both zones keep within it). None when the member has no zone rule. ``step`` default: the
    pack's spacing step (:func:`saengine.design.bars.spacing_step`)."""
    if step is None:
        step = spacing_step()
    if need.zone_spacing is None:
        if need.outside_spacing is None or not math.isfinite(need.outside_spacing):
            return None
        s = (
            need.outside_spacing
            if shear_spacing is None
            else min(need.outside_spacing, shear_spacing)
        )
        return {"spacing": round_down(s, step)}
    zone = need.zone_spacing
    if isinstance(need, ColumnNeed) and need.ash_s is not None:
        area = bar_area(dia)
        zone = min(
            zone,
            legs * area / need.ash_s[0],
            (legs_x if legs_x is not None else legs) * area / need.ash_s[1],
        )
    if shear_spacing is not None:
        zone = min(zone, shear_spacing)
    outside = zone if getattr(need, "full_height", False) else need.outside_spacing
    if outside is not None and shear_spacing is not None:
        outside = min(outside, shear_spacing)
    if outside is not None and math.isfinite(outside):
        zone = min(zone, outside)
    zone_s = round_down(zone, step)
    result: dict[str, Any] = {
        "zone": {
            "length": math.ceil(need.zone_length / step - 1e-9) * step,
            "spacing": zone_s,
        }
    }
    if need.first:
        result["zone"]["first"] = round_down(need.first, step)
    if outside is not None and math.isfinite(outside):
        result["spacing"] = round_down(outside, step)
    if need.splice_spacing is not None:
        result["splice"] = {"spacing": round_down(min(need.splice_spacing, zone), step)}
    return result

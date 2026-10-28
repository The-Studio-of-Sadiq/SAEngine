"""Reinforcement detailing: the bars of every member with their marks, shapes, lengths, laps and
transverse zones, from the building model (06 BIM), the object types (04 Objects), the
foundations (09 Substructure) and, when given, the design report. The detailing model is what
the bar bending schedules (:mod:`saengine.drawings.bbs`) and the drawing sheets
(:mod:`saengine.drawings.sheets`) draw from.

Code basis: BNBC 2020 Part 6 Chapter 8 "Detailing of Reinforcement in Concrete Structures"
(bnbc-2020-part1.pdf; the page is the PDF page). Every rule names its clause and page:

- Standard hooks (8.1.2.1, pp 1065-1066): 180° + max(4 db, 65 mm); 90° + 12 db; stirrups and
  ties: 90° + 6 db (db <= 16), 90° + 12 db (19-25 mm), 135° + 6 db (db <= 25); closed ties
  135° + max(6 db, 75 mm); seismic hooks 135° (circular hoops 90°) + max(6 db, 75 mm)
  (8.1.2.1(d)); cross ties 135° + max(6 db, 75 mm) at one end, 90° + 6 db at the other (8.1.1.1,
  p 1062). Least inside bend diameters (8.1.2.2, Table 6.8.1, p 1066): 6 db for 10-25 mm, 8 db
  over 25 to 40 mm, 10 db over 40 to 57 mm; stirrups and ties of 16 mm and smaller 4 db
  (8.1.2.2(b)). Bars below 10 mm are not in Table 6.8.1: 6 db is taken.
- Development in tension (8.2.3, pp 1076-1078): ld >= 300 mm (8.2.3.1); the simplified form of
  8.2.3.2 (fy ψt ψe / (2.1 λ √f'c) db for 19 mm and smaller bars, / (1.7 ...) for 20 mm and
  larger when the clear spacing is at least db, the cover at least db and the stirrups at least
  the code minimum, or the spacing 2 db and the cover db; "other cases" / (1.1 ...) for 20 mm
  and larger. The table's cell for 19 mm and smaller bars in "other cases" is blank in the
  gazette: 1.4, the value of ACI 318 25.4.2.3 that the table follows, is taken and said so), or
  the general form Eq. 6.8.1 fy ψt ψe ψs / (1.1 λ √f'c (cb + Ktr)/db) db with (cb + Ktr)/db <=
  2.5 and Ktr = 40 Atr / (s n) (Eq. 6.8.2, Ktr = 0 permitted). ψt = 1.3 for bars with more than
  300 mm of fresh concrete below (8.2.3.4(a)); ψe 1.5 / 1.2 epoxy, 1.0 uncoated, ψt ψe <= 1.7
  (b); ψs = 0.8 for 19 mm and smaller, 1.0 above (c); λ (d). √f'c <= 8.3 MPa (8.2.2, p 1076).
  Excess reinforcement As,req / As,prov (8.2.3.5, p 1078).
- Development in compression (8.2.4, p 1078): ldc = max(0.24 fy db / (λ √f'c), 0.043 fy db) >=
  200 mm, × As,req/As,prov, × 0.75 inside spirals or 12 mm ties at 100 mm.
- Standard hooks in tension (8.2.6, p 1079): ldh = 0.24 ψe fy db / (λ √f'c) × the factors of
  8.2.6.3 (0.7 for side cover >= 65 mm and, for 90° hooks, 50 mm cover on the tail; 0.8 inside
  ties at <= 3 db; As,req/As,prov), >= max(8 db, 150 mm); the value is
  :func:`saengine.design.ductile_joints.hooked_development`. Hooks do not develop bars in
  compression (8.2.6.5). Hooked beam bars in the joints of special moment frames:
  max(8 db, 150 mm, fy db / (5.4 √f'c)) (8.3.7.4(a), p 1111):
  :func:`saengine.design.ductile_joints.hooked_anchorage_seismic`.
- Flexural bars (8.2.7-8.2.9, pp 1080-1081): bars extend max(d, 12 db) beyond the point where
  they are no longer needed (8.2.7.3); continuing bars have ld beyond the point where the
  terminated bars are no longer needed (8.2.7.4); at least 1/3 (simple members) and 1/4
  (continuous members) of the positive steel extends into the support, in beams at least 150 mm
  (8.2.8.1), anchored for fy at the face in members of the lateral system (8.2.8.2); at least
  1/3 of the negative steel at a support extends beyond the point of inflection by max(d,
  ln/16, 12 db) (8.2.9.3).
- Splices (8.2.12-8.2.15, pp 1083-1085): no laps of 36 mm bars and larger (8.2.12.2(a));
  tension laps class A 1.0 ld and class B 1.3 ld, ld without the 300 mm minimum and without
  the excess factor, >= 300 mm (8.2.13.1); class B unless As,prov >= 2 As,req over the lap and
  at most half the bars are spliced there (8.2.13.2); bars of different sizes: the larger of ld
  of the larger bar and the lap of the smaller (8.2.13.5); compression laps 0.071 fy db (fy <=
  420 MPa) or (0.13 fy - 24) db, >= 300 mm, + 1/3 when f'c < 21 MPa (8.2.14.1); columns
  (8.2.15.2): compression laps when the bars are in compression, class B tension laps when the
  bar stress exceeds 0.5 fy in tension or more than half the bars are spliced at a section,
  × 0.83 with ties of 0.0015 h s (d), × 0.75 inside spirals (e), >= 300 mm. Spiral laps 48 db
  (72 db for others), >= 300 mm, and 1.5 extra turns at each end (8.1.9.3(d), (e), p 1073).
- Structural integrity (8.1.12.2, pp 1075-1076): perimeter beams' top steel spliced at mid-span
  and bottom steel at or near the supports, class B.
- Earthquake (8.3): beams of special moment frames have at least two continuous bars top and
  bottom and no laps within the joints or within 2 h of the joint faces, hoops over laps at
  <= min(d/4, 100 mm) (8.3.4.2(a), (b), p 1091); special-frame column laps only within the
  centre half of the member, as tension splices (8.3.5.3(b), p 1096, Figure 6.8.7 p 1097);
  special walls develop their bars for 1.25 ld where they may yield (8.3.6.2(c), pp
  1100-1101); column bars into the foundation with 90° hooks at the bottom turned towards the
  column's centre (8.3.11.2(a), (b), p 1120: :func:`saengine.design.ductile_joints.
  column_dowel_checks`). The end zones (lo, so) are the design's (the design report's
  ``detailing.zones``, else the object type's ``transverse.zone``, else the rule of
  :func:`saengine.design.ductile_members.beam_need` / ``column_need``).
- Slab bars (Figure 6.6.20, p 948, slabs without beams, used for all slabs): top bars at
  supports to 0.30 ln from the face (the column strip value, which governs; the longer span at
  a support between unequal spans, 6.5.3.8.2), bottom bars at least 150 mm into the supports.

Practice where BNBC gives no figure (not a BNBC rule; office practice): the extra top bars of beams
over a support run to 0.30 ln from the face (as Figure 6.6.20 for slabs; ACI SP-66's typical
beam details use 0.30-0.33 ln), but never less than ld from the face; all bottom bars of beams
run into the supports (no bottom cut-off, which satisfies 8.2.8.1 and is safe); the continuous
top bars are max(2, ⌈n/3⌉) of the top bars (8.3.4.2(a), 8.2.9.3), more when the design
requires hogging steel at mid-span; stirrups start 50 mm from the face (8.3.4.3(b) for
seismic beams, used for all); column ties start at half the spacing from the floor
(8.1.9.4(d), p 1074); horizontal wall bars end in 90° hooks at the wall ends (8.3.6.6(d)(v),
(e)(ii), p 1104); stair main bars run ld past the kink into the landing or the support; the
extra top bars of beams stay within the bar ends of the line, and those of two supports that
meet in a short span are one bar across it; column bars without a partner in a smaller column
above stop 40 mm below the floor's top with a 90° hook, and the extra bars of a larger column
above start on dowels anchored ld below the floor.

Anchorage read from BNBC: top bars of slabs at discontinuous edges bend down into the edge
support with a standard 90° hook (8.1.2.1(b), p 1065) when it is deep enough, ldh checked on
the support's width (8.2.9.1, p 1081: negative steel anchored in or through the support);
otherwise as deep as the support allows and their straight length in it checked against ld.
Footing bars are checked from the face of every column on the footing at its real position.

Marks (:func:`assign_marks`): ``<type code>-<role><n>``, e.g. ``B1-T1``: the type code is a
kind letter (B beams, C columns, S slabs, W walls, ST stairs, F footings, PC pile caps) and the
type's number among the types of that kind (by id). Foundations of 9 Substructure have no
types: the foundations with the same definition (form, size, reinforcement, concrete) are one
type named after the first of them, and that label (F1, PC2) is the code when free. The role
letters are T top, B bottom, F side face, S stirrups, X cross ties (beams); V vertical, D
dowels (starter bars), H ties or hoops, P spirals (columns); BX, BY, TX, TY bottom and top
bars along x and y (slabs, footings); V, H, E end bars, K boundary hoops (walls), LB, LT, LS
the bottom bars, top hangers and stirrups of the lintels over a wall's openings; M main, N
distribution, T top, L landing, LN landing distribution (stairs). Identical bars of the same type (same diameter, shape and dimensions)
share a mark across members. Marks are deterministic, and ``previous`` (the ``marks`` of an
earlier model) keeps every unchanged bar's mark even when other types or bars change.

How it is called::

    model = detailing_model(project_root)                      # reads the project's files
    model = detailing_model(texts={"bim": ..., "objects": ..., "materials": ...,
                                   "settings": ..., "substructure": ...},
                            design_report=report,              # design.check.design_report()
                            required=required,                 # design.required.design_required()
                            options={...}, previous=old_model["marks"])

Returns ``{"schema", "elements", "marks", "notes", "options", "code"}``; per element ``{"id",
"kind" (beam, column, slab, wall, staircase, footing, pileCap), "type" (the 04 Objects
type; foundations of 9 Substructure: see the marks), "form"? (foundations: isolated,
combined, strip, pileCap, raft), "member" (the label),
"members" (the BIM ids a beam line spans), "story", "count" (1), "bars", "transverse",
"laps", "checks", "notes"}``; per bar ``{"mark", "role", "dia", "grade", "shape" (straight,
L, U, crank, stirrup, helix, special: names :mod:`saengine.drawings.bbs` maps to BS 8666
codes), "count" (in this member), "dims" (outside dimensions A, B, C ... as BS 8666
schedules them), "segments" (the same in order), "bendDia" (BNBC least inside bend diameter),
"length" (developed length along the bar's centreline, from the BNBC bend diameter), "at"
(where it lies: line coordinates or levels, face, layer and world end points),
"zone"?, "lap"? (lap length at its ends), "curtailed"? (a cut-off bar), "remarks"?}``;
transverse rows ``{"mark", "from", "to", "spacing", "count", "zone"}`` (lo end zones,
middle, splice, joint); laps ``{"marks", "from", "to", "length", "class", "clause", "at"}``;
checks ``{"name", "required", "provided", "unit", "ok", "clause"}``. ``marks``: per mark
``{"mark", "type", "kind", "role", "dia", "shape", "dims", "length", "count" (in the project),
"elements", "signature"}``. Units: mm, MPa.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

CODE = "BNBC 2020 Part 6"
SCHEMA_ID = "saengine.detailing/1"
#: Computed lengths (development, laps, extents, hook tails) are rounded up to this [mm].
ROUND = 25.0
#: The longest bar delivered [mm] (as the bill of quantities, saengine.boq.quantities).
STOCK_LENGTH = 12_000.0
#: √f'c in Sec 8.2 at most this [MPa] (8.2.2, p 1076).
SQRT_FC_MAX = 8.3
LD_MIN = 300.0  # 8.2.3.1
LDC_MIN = 200.0  # 8.2.4.1
LAP_MIN = 300.0  # 8.2.13.1, 8.2.14.1, 8.2.15.2(d), (e)
#: Bottom bars of beams and slabs into the support at least this [mm] (8.2.8.1, Figure 6.6.20).
INTO_SUPPORT = 150.0
#: Top bars of slabs at supports, from the face, as a share of ln (Figure 6.6.20, p 948).
SLAB_TOP_EXTENT = 0.30
#: Extra top bars of beams over supports, from the face, as a share of ln (practice, see notes).
BEAM_TOP_EXTENT = 0.30
#: First stirrup from the face [mm] (8.3.4.3(b), 8.3.10.4(b)).
FIRST_STIRRUP = 50.0
TOL = 50.0  # mm: geometric tolerance when matching members

DEFAULT_OPTIONS: dict[str, Any] = {
    "curtail": True,  # beams: cut the extra top bars; False: all bars full length (as the BOQ)
    "beamTopExtent": BEAM_TOP_EXTENT,
    "slabTopExtent": SLAB_TOP_EXTENT,
    "slabTop": "supports",  # "supports": top bars over supports; "full": the mesh all over
    "stockLength": STOCK_LENGTH,
    "round": ROUND,
    "columnLaps": "tension",  # "tension" (class B) or "compression" (8.2.14.1)
    "method": "simplified",  # development length form: "simplified" (8.2.3.2) or "general"
}


def _page(clause: str, page: int | str) -> str:
    return f"{CODE} Sec {clause}, p {page}"


def up(value: float, step: float = ROUND) -> float:
    """``value`` rounded up to a multiple of ``step`` (a hair of float noise ignored)."""
    if step <= 0:
        return value
    return math.ceil(value / step - 1e-9) * step


@dataclass(frozen=True)
class Rule:
    """A detailing length [mm] with the formula and clause it comes from."""

    value: float
    formula: str
    clause: str

    def rounded(self, step: float = ROUND) -> float:
        return up(self.value, step)


# ─────────────────────────────────────── hooks and bends ───────────────────────────────────────


def bend_diameter(db: float, transverse: bool = False) -> Rule:
    """Least inside bend diameter [mm] (8.1.2.2, Table 6.8.1, p 1066): 6 db (10-25 mm), 8 db
    (over 25 to 40 mm), 10 db (over 40 to 57 mm); stirrups and ties of 16 mm and smaller 4 db
    (8.1.2.2(b)). Bars below 10 mm: 6 db (4 db as ties)."""
    if transverse and db <= 16:
        return Rule(4 * db, "4 db", _page("8.1.2.2(b)", 1066))
    factor = 6 if db <= 25 else 8 if db <= 40 else 10
    return Rule(factor * db, f"{factor} db", _page("8.1.2.2(a), Table 6.8.1", 1066))


@dataclass(frozen=True)
class Hook:
    """A hook: bend ``angle`` [°], straight ``tail`` beyond the bend [mm], inside bend diameter,
    and ``leg``: the hook's outside dimension measured from the outer face of the bar before the
    bend (tail + inside radius + db, for a 90° hook the B of a BS 8666 L bar)."""

    angle: float
    tail: float
    bend_dia: float
    db: float
    clause: str

    @property
    def leg(self) -> float:
        return self.tail + self.bend_dia / 2 + self.db

    @property
    def arc(self) -> float:
        """Length of the bend along the bar's centreline [mm]."""
        return math.radians(self.angle) * (self.bend_dia / 2 + self.db / 2)


def standard_hook(
    db: float, angle: float = 90, *, transverse: bool = False, closed: bool = False
) -> Hook:
    """The standard hook of 8.1.2.1 (pp 1065-1066). Main bars: 180° + max(4 db, 65 mm) (a), 90° +
    12 db (b). ``transverse`` (stirrups and ties, (c)): 90° + 6 db for db <= 16 mm, 90° + 12 db
    for 19-25 mm, 135° + 6 db for db <= 25 mm; ``closed`` ties, and seismic hooks (d), 135° +
    max(6 db, 75 mm)."""
    bend = bend_diameter(db, transverse).value
    if not transverse:
        if angle >= 180:
            return Hook(180, max(4 * db, 65.0), bend, db, _page("8.1.2.1(a)", 1065))
        return Hook(90, 12 * db, bend, db, _page("8.1.2.1(b)", 1065))
    if angle >= 135:
        tail = max(6 * db, 75.0) if closed else 6 * db
        clause = "8.1.2.1(c)(iv), (d)" if closed else "8.1.2.1(c)(iii)"
        return Hook(135, tail, bend, db, _page(clause, 1066))
    tail = 6 * db if db <= 16 else 12 * db
    return Hook(90, tail, bend, db, _page("8.1.2.1(c)(i), (ii)", 1066))


def seismic_hook(db: float) -> Hook:
    """Hook of a hoop, stirrup or cross tie in a seismic member: 135°, max(6 db, 75 mm)
    (8.1.2.1(d), p 1066)."""
    return standard_hook(db, 135, transverse=True, closed=True)


# ───────────────────────────────────────── development ─────────────────────────────────────────


def sqrt_fc(fc: float) -> float:
    """√f'c for Sec 8.2, at most 8.3 MPa (8.2.2, p 1076)."""
    return min(math.sqrt(fc), SQRT_FC_MAX)


def psi_s(db: float) -> float:
    """Bar size factor (8.2.3.4(c), p 1078): 0.8 for 19 mm and smaller, 1.0 above."""
    return 0.8 if db <= 19 else 1.0


def psi_t(top: bool) -> float:
    """Casting position (8.2.3.4(a), p 1077): 1.3 with more than 300 mm of fresh concrete below."""
    return 1.3 if top else 1.0


def ktr(atr: float, s: float, n: int) -> float:
    """Transverse reinforcement index Ktr = 40 Atr / (s n) [mm] (Eq. 6.8.2, p 1077)."""
    return 40 * atr / (s * n)


def development_tension(
    db: float,
    fy: float,
    fc: float,
    *,
    lam: float = 1.0,
    top: bool = False,
    psi_e: float = 1.0,
    method: str = "simplified",
    spacing_ok: bool = True,
    cb: float | None = None,
    k_tr: float = 0.0,
    excess: float = 1.0,
    minimum: bool = True,
) -> Rule:
    """ld [mm] of a deformed bar in tension (8.2.3, pp 1076-1078).

    ``method`` "simplified" (8.2.3.2): ``spacing_ok`` the first row of the table (clear spacing
    >= db, cover >= db and code minimum stirrups, or spacing >= 2 db and cover >= db).
    "general" (8.2.3.3, Eq. 6.8.1): ``cb`` the smaller of the cover to the bar's centre and half
    the bars' centre spacing [mm], ``k_tr`` (Eq. 6.8.2, 0 permitted). ``excess`` As,req/As,prov
    (8.2.3.5); ``minimum`` False leaves out the 300 mm of 8.2.3.1 (for laps, 8.2.13.1)."""
    pt = psi_t(top)
    te = min(pt * psi_e, 1.7)  # 8.2.3.4(b): ψt ψe need not exceed 1.7
    root = sqrt_fc(fc)
    if method == "general":
        if cb is None:
            raise ValueError("the general form needs cb")
        confinement = min((cb + k_tr) / db, 2.5)
        ps = psi_s(db)
        raw = fy * te * ps / (1.1 * lam * root * confinement) * db
        formula = (
            f"fy ψt ψe ψs / (1.1 λ √f'c (cb + Ktr)/db) db = {fy:g}·{te:g}·{ps:g} / (1.1·{lam:g}·"
            f"{root:.2f}·{confinement:.2f})·{db:g}"
        )
        clause = _page("8.2.3.3, Eq. 6.8.1", 1077)
    else:
        if spacing_ok:
            k = 2.1 if db <= 19 else 1.7
        else:
            k = 1.4 if db <= 19 else 1.1
        raw = fy * te / (k * lam * root) * db
        formula = (
            f"fy ψt ψe / ({k:g} λ √f'c) db = {fy:g}·{te:g} / ({k:g}·{lam:g}·{root:.2f})·{db:g}"
        )
        clause = _page("8.2.3.2", 1077)
        if not spacing_ok and db <= 19:
            clause += " (the table's cell is blank: 1.4 of ACI 318 25.4.2.3 taken)"
    value = raw * excess
    if excess != 1.0:
        formula += f" × As,req/As,prov {excess:.2f} (8.2.3.5)"
    if minimum and value < LD_MIN:
        value = LD_MIN
        formula += ", at least 300 mm (8.2.3.1)"
    return Rule(value, formula, clause)


def development_compression(
    db: float,
    fy: float,
    fc: float,
    *,
    lam: float = 1.0,
    confined: bool = False,
    excess: float = 1.0,
) -> Rule:
    """ldc [mm] (8.2.4, p 1078): max(0.24 fy db / (λ √f'c), 0.043 fy db) × As,req/As,prov × 0.75
    inside spirals or 12 mm ties at 100 mm (``confined``), at least 200 mm."""
    basic = max(0.24 * fy * db / (lam * sqrt_fc(fc)), 0.043 * fy * db)
    value = basic * excess * (0.75 if confined else 1.0)
    return Rule(
        max(value, LDC_MIN),
        "max(0.24 fy db / (λ √f'c), 0.043 fy db)"
        + (" × 0.75" if confined else "")
        + (f" × {excess:.2f}" if excess != 1.0 else "")
        + ", at least 200 mm",
        _page("8.2.4.1-8.2.4.3", 1078),
    )


def hook_development(
    db: float,
    fy: float,
    fc: float,
    *,
    lam: float = 1.0,
    psi_e: float = 1.0,
    cover: bool = False,
    confined: bool = False,
    excess: float = 1.0,
) -> Rule:
    """ldh [mm] of a standard hook in tension (8.2.6, p 1079): 0.24 ψe fy db / (λ √f'c) ×
    0.7 when the side cover is at least 65 mm (and 50 mm on a 90° hook's tail, ``cover``) × 0.8
    inside ties at <= 3 db (``confined``) × As,req/As,prov, at least max(8 db, 150 mm). The
    value is :func:`saengine.design.ductile_joints.hooked_development` (√f'c capped, 8.2.2)."""
    from saengine.design.ductile_joints import hooked_development

    factor = (0.7 if cover else 1.0) * (0.8 if confined else 1.0) * excess
    fc_used = min(fc, SQRT_FC_MAX**2)
    value = hooked_development(db, fy, fc_used, lam, psi_e, factor)
    return Rule(
        value,
        f"0.24 ψe fy db / (λ √f'c) × {factor:.2f}, at least max(8 db, 150 mm)",
        _page("8.2.6.1-8.2.6.3", 1079),
    )


def hook_development_seismic(db: float, fy: float, fc: float, lam: float = 1.0) -> Rule:
    """ldh [mm] of a 90° hooked beam bar in a joint of a special moment frame (8.3.7.4(a), Eq.
    6.8.12, p 1111): :func:`saengine.design.ductile_joints.hooked_anchorage_seismic`."""
    from saengine.design.ductile_joints import hooked_anchorage_seismic

    return Rule(
        hooked_anchorage_seismic(db, fy, fc, lam),
        "max(8 db, 150 mm, fy db / (5.4 √f'c))",
        _page("8.3.7.4(a), Eq. 6.8.12", 1111),
    )


# ──────────────────────────────────────────── splices ────────────────────────────────────────────


def splice_class(provided_over_required: float, spliced_share: float) -> str:
    """Class of a tension lap (8.2.13.2, p 1084): "A" when As,prov >= 2 As,req over the lap and
    at most half the bars are spliced within the lap length, else "B"."""
    return "A" if provided_over_required >= 2 and spliced_share <= 0.5 else "B"


def lap_tension(
    db: float,
    fy: float,
    fc: float,
    *,
    cls: str = "B",
    other_db: float | None = None,
    factor: float = 1.0,
    **development: Any,
) -> Rule:
    """Tension lap [mm] (8.2.13.1, p 1083): class A 1.0 ld, class B 1.3 ld, ld by 8.2.3 without
    its 300 mm minimum and without the excess factor, at least 300 mm. ``other_db``: the bar
    lapped with, when of another size (8.2.13.5, p 1084: the larger of ld of the larger bar and
    the lap of the smaller). ``factor`` multiplies ld (1.25 for special walls, 8.3.6.2(c));
    ``development``: the arguments of :func:`development_tension` (top, psi_e, method, ...)."""
    if db >= 36:
        raise ValueError("lap splices are not used for 36 mm bars and larger (8.2.12.2(a))")
    development.pop("excess", None)
    development.pop("minimum", None)
    small, large = (db, other_db) if other_db and other_db > db else (other_db or db, db)
    ld = development_tension(small, fy, fc, minimum=False, **development).value * factor
    k = 1.0 if cls == "A" else 1.3
    value = max(k * ld, LAP_MIN)
    formula = f"{k:g} ld = {k:g} × {ld:.0f}"
    if other_db and other_db != db:
        ld_large = development_tension(large, fy, fc, minimum=True, **development).value
        if ld_large > value:
            value, formula = ld_large, f"ld of the larger bar Ø{large:g} = {ld_large:.0f}"
    if factor != 1.0:
        formula += f" (ld × {factor:g})"
    return Rule(value, formula + ", at least 300 mm", _page(f"8.2.13.1 class {cls}", 1083))


def lap_compression(db: float, fy: float, fc: float, *, factor: float = 1.0) -> Rule:
    """Compression lap [mm] (8.2.14.1, p 1084): 0.071 fy db for fy <= 420 MPa, (0.13 fy - 24) db
    above, + 1/3 when f'c < 21 MPa; ``factor`` 0.83 for tied columns with ties of 0.0015 h s
    (8.2.15.2(d)) or 0.75 inside spirals (8.2.15.2(e)); at least 300 mm."""
    basic = 0.071 * fy * db if fy <= 420 else (0.13 * fy - 24) * db
    formula = "0.071 fy db" if fy <= 420 else "(0.13 fy - 24) db"
    if fc < 21:
        basic *= 4 / 3
        formula += " × 4/3 (f'c < 21 MPa)"
    if factor != 1.0:
        formula += f" × {factor:g}"
    return Rule(
        max(basic * factor, LAP_MIN), formula + ", at least 300 mm", _page("8.2.14.1", 1084)
    )


def column_lap(
    db: float,
    fy: float,
    fc: float,
    *,
    stress: str = "tension",
    spliced_share: float = 1.0,
    factor: float = 1.0,
    **development: Any,
) -> Rule:
    """Lap of column bars (8.2.15.2, p 1085): ``stress`` "compression" (the bars are in
    compression under every factored combination): a compression lap (a), × ``factor`` (0.83 or
    0.75, (d), (e)); "low" (tension not over 0.5 fy): class B when more than half the bars are
    spliced at a section, class A when half or fewer and staggered by ld (b); "tension" (above
    0.5 fy, and the laps of special moment frames, 8.3.5.3(b)): class B (c)."""
    if stress == "compression":
        rule = lap_compression(db, fy, fc, factor=factor)
        return Rule(rule.value, rule.formula, _page("8.2.15.2(a), 8.2.14.1", 1085))
    cls = "A" if stress == "low" and spliced_share <= 0.5 else "B"
    rule = lap_tension(db, fy, fc, cls=cls, **development)
    return Rule(
        rule.value, rule.formula, _page(f"8.2.15.2({'b' if stress == 'low' else 'c'})", 1085)
    )


def spiral_lap(db: float, plain: bool = False) -> Rule:
    """Lap of a spiral (8.1.9.3(e), p 1073): 48 db for deformed uncoated bars, 72 db for others,
    at least 300 mm."""
    k = 72 if plain else 48
    return Rule(max(k * db, LAP_MIN), f"{k} db, at least 300 mm", _page("8.1.9.3(e)", 1073))


# ────────────────────────────────────────── curtailment ──────────────────────────────────────────


def extension_beyond_cutoff(d: float, db: float) -> Rule:
    """Bars extend beyond the point where they are no longer needed by max(d, 12 db), except at
    the supports of simple spans and the free ends of cantilevers (8.2.7.3, p 1080)."""
    return Rule(max(d, 12 * db), "max(d, 12 db)", _page("8.2.7.3", 1080))


def negative_extension(d: float, db: float, ln: float) -> Rule:
    """At least 1/3 of the negative steel at a support extends beyond the point of inflection by
    max(d, ln/16, 12 db) (8.2.9.3, p 1081)."""
    return Rule(max(d, ln / 16, 12 * db), "max(d, ln/16, 12 db)", _page("8.2.9.3", 1081))


def positive_into_support(count: int, continuous: bool) -> int:
    """Bars of the positive steel that extend along the same face into the support, at least
    150 mm in beams: 1/3 in simple members, 1/4 in continuous ones (8.2.8.1, p 1080)."""
    return max(1, math.ceil(count / (4 if continuous else 3) - 1e-9))


def continuous_top_bars(count: int, required_share: float = 0.0) -> int:
    """Top bars made continuous along a beam: at least two (8.3.4.2(a), p 1091; 8.1.12.2(b)),
    at least 1/3 of them (so the 1/3 of 8.2.9.3 runs past every point of inflection), and at
    least ``required_share`` of them (the share the design needs at mid-span)."""
    return min(count, max(2, math.ceil(count / 3 - 1e-9), math.ceil(count * required_share - 1e-9)))


def uniform_moment(x: float, ln: float, w: float, m_left: float, m_right: float) -> float:
    """Moment [N·mm] at ``x`` [mm] from the left face of a span ``ln`` under a uniform load ``w``
    [N/mm] with hogging end moments ``m_left``, ``m_right`` (magnitudes, N·mm); sagging
    positive: w x (ln - x)/2 - mL (1 - x/ln) - mR x/ln."""
    return w * x * (ln - x) / 2 - m_left * (1 - x / ln) - m_right * x / ln


def _roots(ln: float, w: float, m_left: float, m_right: float, level: float) -> list[float]:
    """The x in [0, ln] where :func:`uniform_moment` equals ``level``, ascending."""
    # -w/2 x² + (w ln/2 + (mL - mR)/ln) x - mL - level = 0
    a = -w / 2
    b = w * ln / 2 + (m_left - m_right) / ln
    c = -m_left - level
    if abs(a) < 1e-12:
        return [x for x in ([-c / b] if abs(b) > 1e-12 else []) if 0 <= x <= ln]
    disc = b * b - 4 * a * c
    if disc < 0:
        return []
    r = math.sqrt(disc)
    xs = sorted(((-b - r) / (2 * a), (-b + r) / (2 * a)))
    return [x for x in xs if -1e-9 <= x <= ln + 1e-9]


def inflection_points(
    ln: float, w: float, m_left: float, m_right: float
) -> tuple[float | None, float | None]:
    """Points of inflection [mm from the left face] of :func:`uniform_moment`: (left, right);
    None where the moment does not change sign on that side."""
    xs = _roots(ln, w, m_left, m_right, 0.0)
    left = xs[0] if xs and m_left > 0 else None
    right = xs[-1] if xs and m_right > 0 else None
    return left, right


def beam_cutoffs(
    ln: float,
    w: float,
    m_left: float,
    m_right: float,
    *,
    share: float,
    d: float,
    db: float,
    ld: float,
) -> dict[str, Any]:
    """The general rule for the top bars of a uniformly loaded span (8.2.7.3, 8.2.7.4, 8.2.9.3):
    the continuing bars (``share`` of the support steel, taken to carry that share of the
    support moment) leave the extra bars unneeded where the hogging moment has dropped to that
    share; the extra bars end max(d, 12 db) beyond that point and at least ``ld`` from the face;
    the continuing bars run at least max(d, ln/16, 12 db) past the point of inflection. Returns
    per side ``{"inflection", "notNeeded", "extra", "continuing"}`` [mm from that side's face]
    (None where there is no hogging)."""
    beyond = extension_beyond_cutoff(d, db).value
    out: dict[str, Any] = {}
    left_pi, right_pi = inflection_points(ln, w, m_left, m_right)
    for side, moment, pi in (("left", m_left, left_pi), ("right", m_right, right_pi)):
        if moment <= 0 or pi is None:
            out[side] = None
            continue
        level = -share * moment
        xs = _roots(ln, w, m_left, m_right, level)
        if side == "left":
            point = xs[0] if xs else 0.0
            pi_from = pi
        else:
            point = ln - xs[-1] if xs else 0.0
            pi_from = ln - pi
        out[side] = {
            "inflection": pi_from,
            "notNeeded": point,
            "extra": max(point + beyond, ld),
            "continuing": pi_from + negative_extension(d, db, ln).value,
        }
    return out


def standard_top_extent(ln: float, ld: float, fraction: float = BEAM_TOP_EXTENT) -> Rule:
    """Extra top bars of a beam over a support, from the face: ``fraction`` ln (practice, 0.30
    ln), at least ld (8.2.7.4, 8.2.9.2)."""
    value = max(fraction * ln, ld)
    return Rule(
        value,
        f"max({fraction:g} ln, ld) = max({fraction * ln:.0f}, {ld:.0f})",
        f"practice (not in BNBC); ld: {_page('8.2.9.2, 8.2.7.4', '1081, 1080')}",
    )


def slab_top_extent(ln: float, fraction: float = SLAB_TOP_EXTENT) -> Rule:
    """Top bars of a slab at a support, from the face: 0.30 ln (Figure 6.6.20, p 948; ln the
    longer clear span at a support between unequal spans, 6.5.3.8.2)."""
    return Rule(
        fraction * ln, f"{fraction:g} ln", _page("6.5.3.8.1, 6.5.3.8.2, Figure 6.6.20", 948)
    )


def seismic_splice_exclusion(h: float) -> Rule:
    """No laps in beams of special moment frames within the joint or within 2 h of its faces
    (8.3.4.2(b), p 1091)."""
    return Rule(2 * h, "2 h", _page("8.3.4.2(b)", 1091))


def column_splice_region(clear_height: float) -> tuple[float, float]:
    """Laps of special-frame columns only within the centre half of the clear height: (from,
    to) above the floor [mm] (8.3.5.3(b), p 1096; Figure 6.8.7, p 1097)."""
    return clear_height / 4, 3 * clear_height / 4


# ──────────────────────────────────────────── shapes ────────────────────────────────────────────


def _bar(
    role: str,
    letter: str,
    dia: float,
    shape: str,
    count: int,
    dims: dict[str, float],
    length: float,
    at: dict[str, Any],
    *,
    bend: float,
    grade: str | None,
    **extra: Any,
) -> dict[str, Any]:
    clean = {k: round(float(v), 1) for k, v in dims.items()}
    bar = {
        "mark": None,
        "role": role,
        "dia": float(dia),
        "grade": grade,
        "shape": shape,
        "count": int(count),
        "dims": clean,
        "segments": [clean[k] for k in sorted(clean) if k in "ABCDE"],
        "bendDia": round(bend, 1),
        "length": round(length, 1),
        "at": at,
        "_letter": letter,
    }
    for key, value in extra.items():
        if value is not None:
            bar[key] = value
    return bar


def straight_length(a: float) -> float:
    return a


def l_length(a: float, b: float, db: float, bend_dia: float) -> float:
    """Centreline length of an L bar of outside dimensions A, B with one 90° bend."""
    r = bend_dia / 2
    return a + b - 2 * (r + db) + math.pi / 2 * (r + db / 2)


def u_length(a: float, b: float, c: float, db: float, bend_dia: float) -> float:
    """Centreline length of a U bar of outside dimensions A, B, C with two 90° bends."""
    r = bend_dia / 2
    return a + b + c - 4 * (r + db) + math.pi * (r + db / 2)


def stirrup_length(a: float, b: float, db: float, hook: Hook) -> float:
    """Centreline length of a closed stirrup or tie of outside dimensions A x B with two 135°
    hooks at one corner: 2 (a' + b') - 8 R + 3 π R + 2 tails, a' = A - db, b' = B - db, R the
    centreline bend radius (three 90° corners and two 135° hook bends)."""
    big_r = hook.bend_dia / 2 + db / 2
    return 2 * ((a - db) + (b - db)) - 8 * big_r + 3 * math.pi * big_r + 2 * hook.tail


def crosstie_length(a: float, db: float, hook135: Hook, hook90: Hook) -> float:
    """Centreline length of a cross tie over an outside width A: a 135° hook at one end, 90° at
    the other (8.1.1.1)."""
    r = hook135.bend_dia / 2
    return a - 2 * (r + db) + hook135.arc + hook90.arc + hook135.tail + hook90.tail


# ────────────────────────────────────────── transverse ──────────────────────────────────────────


def space(
    start: float,
    end: float,
    default: float,
    zones: list[tuple[float, float, float, str]],
    first: float,
) -> list[dict[str, Any]]:
    """Hoops or stirrups from ``start + first`` to ``end - first``: ``zones`` (from, to, spacing,
    name) set a closer spacing where they cover (the closest wins), ``default`` elsewhere
    ("middle"). Rows ``{"from", "to", "spacing", "count", "zone"}``: the first row counts the
    first hoop too, so the counts add up to the hoops placed."""
    a0, a1 = start + first, end - first
    if a1 <= a0 + 1e-6:
        return [{"from": round(a0, 1), "to": round(a0, 1), "spacing": default, "count": 1,
                 "zone": "middle"}]  # fmt: skip
    cuts = {a0, a1}
    for z0, z1, _, _ in zones:
        for c in (z0, z1):
            if a0 < c < a1:
                cuts.add(c)
    points = sorted(cuts)
    pieces: list[list[Any]] = []
    for p0, p1 in itertools.pairwise(points):
        mid = (p0 + p1) / 2
        cover = [z for z in zones if z[0] - 1e-6 <= mid <= z[1] + 1e-6]
        if cover:
            best = min(cover, key=lambda z: (z[2], z[3]))
            s, name = best[2], best[3]
        else:
            s, name = default, "middle"
        if pieces and pieces[-1][2] == s and pieces[-1][3] == name:
            pieces[-1][1] = p1
        else:
            pieces.append([p0, p1, s, name])
    rows = []
    for k, (p0, p1, s, name) in enumerate(pieces):
        n = max(1, math.ceil((p1 - p0) / s - 1e-9))
        rows.append(
            {
                "from": round(p0, 1),
                "to": round(p1, 1),
                "spacing": float(s),
                "count": n + (1 if k == 0 else 0),
                "zone": name,
            }
        )
    return rows


def split_run(
    s0: float,
    s1: float,
    lap: float,
    windows: list[tuple[float, float]],
    stock: float = STOCK_LENGTH,
    extra: tuple[float, float] = (0.0, 0.0),
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], bool]:
    """Pieces [(from, to)] of a bar running ``s0`` to ``s1`` no longer than ``stock`` (with
    ``extra`` [mm] of hooks at the two ends), lapped by ``lap`` wholly inside one of
    ``windows`` [(from, to)]: each lap as far along as the stock length reaches. Returns
    (pieces, laps, ok); ok False when a piece is left longer than the stock length (no window
    in reach)."""
    # the lap furthest along each time leaves the most reach for the next one: greedy is best
    pieces: list[tuple[float, float]] = []
    laps: list[tuple[float, float]] = []
    a, head = s0, extra[0]
    while True:
        if s1 - a + head + extra[1] <= stock + 1e-6:
            pieces.append((a, s1))
            return pieces, laps, True
        reach = a + stock - head
        best: tuple[float, float] | None = None
        for w0, w1 in windows:
            hi = min(w1, reach, s1 - 1.0)
            lo = max(w0, a + 1.0)
            if hi - lap >= lo and (best is None or hi > best[1]):
                best = (hi - lap, hi)
        if best is None:
            pieces.append((a, s1))
            return pieces, laps, False
        pieces.append((a, best[1]))
        laps.append(best)
        a, head = best[0], 0.0


# ─────────────────────────────────────────── the model ───────────────────────────────────────────


@dataclass
class _Ctx:
    building: Any
    types: dict[str, Any]
    materials: Any
    settings: Any
    substructure: Any
    report: dict[str, dict[str, Any]]
    required: dict[str, dict[str, Any]]
    frames: dict[str, tuple[str, bool]]
    wall_level: str | None
    options: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    joints: list[Any] = field(default_factory=list)
    lintels: list[dict[str, Any]] | None = None  # designed here when no report was given

    def fc(self, material_id: str) -> float:
        m = self.materials.get(material_id) if self.materials is not None else None
        conc = getattr(m, "concrete", None)
        return float(conc.fc) if conc is not None else 25.0

    def fy(self, material_id: str) -> float:
        m = self.materials.get(material_id) if self.materials is not None else None
        steel = getattr(m, "steel", None)
        return float(steel.fy) if steel is not None else 420.0

    def grade(self, material_id: str) -> str:
        m = self.materials.get(material_id) if self.materials is not None else None
        steel = getattr(m, "steel", None)
        return str(getattr(steel, "grade", None) or material_id)

    @property
    def step(self) -> float:
        return float(self.options["round"])

    @property
    def stock(self) -> float:
        return float(self.options["stockLength"])

    def _form(self, db: float, cb: float | None) -> dict[str, Any]:
        """The development-length form of the options: "simplified" (8.2.3.2) or "general"
        (Eq. 6.8.1 with Ktr = 0, which 8.2.3.3 permits; ``cb`` the smaller of the cover to the
        bar's centre and half the bars' centre spacing, db when not known: conservative)."""
        if self.options.get("method") == "general":
            return {"method": "general", "cb": float(cb) if cb else db, "k_tr": 0.0}
        return {"method": "simplified"}

    def ld(
        self,
        db: float,
        fy: float,
        fc: float,
        top: bool = False,
        minimum: bool = True,
        cb: float | None = None,
    ) -> float:
        return development_tension(db, fy, fc, top=top, minimum=minimum, **self._form(db, cb)).value

    def lap(
        self,
        db: float,
        fy: float,
        fc: float,
        top: bool = False,
        factor: float = 1.0,
        cb: float | None = None,
    ) -> float:
        rule = lap_tension(db, fy, fc, cls="B", top=top, factor=factor, **self._form(db, cb))
        return up(rule.value, self.step)

    @property
    def method_text(self) -> str:
        if self.options.get("method") == "general":
            return "the general form of 8.2.3.3 (Eq. 6.8.1, Ktr = 0)"
        return "the simplified form of 8.2.3.2"


def _cb(cover_to_bar: float, db: float, spacing: float | None) -> float:
    """cb of Eq. 6.8.1 (8.2.3.3, p 1077): the smaller of the cover to the bar's centre and half
    the bars' centre-to-centre spacing [mm]."""
    side = cover_to_bar + db / 2
    return min(side, spacing / 2) if spacing and spacing > 0 else side


def _check(name: str, required: float, provided: float, clause: str, unit: str = "mm") -> dict:
    return {
        "name": name,
        "required": round(float(required), 1),
        "provided": round(float(provided), 1),
        "unit": unit,
        "ok": bool(provided + 1e-6 >= required),
        "clause": clause,
    }


def _story_at(building: Any, level: float) -> str | None:
    best = None
    for s in building.stories:
        if abs(s.elevation - level) <= TOL:
            best = s.id
    return best


def _point(origin: np.ndarray, u: np.ndarray, s: float, z: float) -> list[float]:
    p = origin + u * s
    return [round(float(p[0]), 1), round(float(p[1]), 1), round(float(z), 1)]


def _frame_of(ctx: _Ctx, element_id: str) -> tuple[str | None, bool]:
    entry = ctx.report.get(element_id)
    info = (entry or {}).get("detailing") or {}
    if info.get("frameType"):
        return str(info["frameType"]), info.get("role", "lateral") == "lateral"
    found = ctx.frames.get(element_id)
    if found:
        return found
    return None, False


_LEVELS = {"special": 3, "intermediate": 2, "ordinary": 1, None: 0}


def _report_notes(ctx: _Ctx, element_id: str) -> list[str]:
    entry = ctx.report.get(element_id)
    if entry and entry.get("ok") is False:
        return [
            (
                f"the design check of {element_id} fails (utilisation "
                f"{float(entry.get('utilisation') or 0):.2f}): detailed as entered"
            )
        ]
    return []


# ─────────────────────────────────────────── beams ───────────────────────────────────────────


@dataclass
class _Support:
    s: float  # along the line from its origin [mm]
    width: float  # c1, along the line
    kind: str  # column | wall | beam
    ref: str
    cover: float = 40.0  # to the support's outer bars (its cover + ties)


def _beam_lines(ctx: _Ctx) -> list[dict[str, Any]]:
    """Collinear beams of one type and elevation that meet end to end, as continuous lines."""
    from saengine.library.bim import BeamElement
    from saengine.library.objects import RectangleProfile

    beams = [e for e in ctx.building.elements if isinstance(e, BeamElement)]
    groups: dict[tuple[str, int], list[Any]] = {}
    for b in beams:
        t = ctx.types.get(b.type)
        if t is None or getattr(t, "kind", None) != "beam":
            continue
        if not isinstance(t.profile, RectangleProfile):
            ctx.notes.append(f"{b.id}: beams of {t.profile.shape} profiles are not detailed")
            continue
        if math.dist(b.start, b.end) <= 1:
            continue
        groups.setdefault((b.type, round(b.elevation)), []).append(b)
    lines: list[dict[str, Any]] = []
    for (_type_id, _level), members in sorted(groups.items()):
        members = sorted(members, key=lambda e: e.id)

        def ends(e: Any) -> tuple[np.ndarray, np.ndarray]:
            return np.asarray(e.start, float), np.asarray(e.end, float)

        def collinear(a: Any, b: Any) -> bool:
            a0, a1 = ends(a)
            u = (a1 - a0) / np.linalg.norm(a1 - a0)
            for p in ends(b):
                v = p - a0
                if abs(v[0] * u[1] - v[1] * u[0]) > 1.0:
                    return False
            return True

        def touch(a: Any, b: Any) -> bool:
            return any(np.linalg.norm(p - q) <= 1.0 for p in ends(a) for q in ends(b))

        links: dict[str, list[str]] = {m.id: [] for m in members}
        by_id = {m.id: m for m in members}
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if touch(a, b) and collinear(a, b):
                    links[a.id].append(b.id)
                    links[b.id].append(a.id)
        seen: set[str] = set()
        for m in members:
            if m.id in seen:
                continue
            # walk to one end of the chain, then along it
            chain = [m.id]
            seen.add(m.id)
            for direction in (0, 1):
                current = m.id
                while True:
                    nxt = [n for n in links[current] if n not in seen]
                    if not nxt:
                        break
                    current = nxt[0]
                    seen.add(current)
                    if direction == 0:
                        chain.insert(0, current)
                    else:
                        chain.append(current)
            pts = np.array([p for mid in chain for p in ends(by_id[mid])])
            first = ends(by_id[chain[0]])
            u = first[1] - first[0]
            u = u / np.linalg.norm(u)
            if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):
                u = -u
            ss = pts @ u
            origin = pts[int(np.argmin(ss))]
            length = float(ss.max() - ss.min())
            spans = []
            for mid in chain:
                a, b = ends(by_id[mid])
                sa, sb = float((a - origin) @ u), float((b - origin) @ u)
                spans.append((min(sa, sb), max(sa, sb), mid))
            spans.sort()
            lines.append(
                {
                    "members": [s[2] for s in spans],
                    "type": by_id[chain[0]].type,
                    "elevation": float(by_id[chain[0]].elevation),
                    "origin": origin,
                    "u": u,
                    "length": length,
                    "pieces": spans,
                }
            )
    return lines


def _line_supports(ctx: _Ctx, line: dict[str, Any]) -> list[_Support]:
    from saengine.design.ductile_joints import column_frame
    from saengine.design.rc import DesignError
    from saengine.library.bim import BeamElement, ColumnElement, WallElement

    origin, u, elevation = line["origin"], line["u"], line["elevation"]
    found: list[_Support] = []
    columns = {e.id: e for e in ctx.building.elements if isinstance(e, ColumnElement)}
    members = set(line["members"])
    for joint in ctx.joints:
        if not any(b.id in members for b in joint.beams) or abs(joint.level - elevation) > TOL:
            continue
        column = columns.get(joint.below)
        t = ctx.types.get(column.type) if column else None
        if t is None:
            continue
        try:
            frame = column_frame(t.profile, float(column.rotation or 0.0), u)
        except DesignError:
            continue
        s = float((np.asarray(joint.position, float) - origin) @ u)
        reinforcement = getattr(t, "reinforcement", None)
        cover = 40.0
        if reinforcement is not None:
            tie = reinforcement.transverse
            cover = reinforcement.cover + (tie.dia if tie else 0.0)
        found.append(_Support(s, frame.along, "column", column.id, cover))
    normal = np.array([-u[1], u[0]])
    for e in ctx.building.elements:
        if isinstance(e, WallElement) and e.bottom - TOL < elevation <= e.top + TOL:
            t = ctx.types.get(e.type)
            a, b = np.asarray(e.start, float), np.asarray(e.end, float)
            w = b - a
            wl = float(np.linalg.norm(w))
            if t is None or wl <= 0 or abs(float(w / wl @ u)) > 0.5:
                continue  # a wall along the beam is not a support of it
            s_hit = _cross(origin, u, a, b)
            if s_hit is None or not (-TOL <= s_hit <= line["length"] + TOL):
                continue
            cover = float(t.reinforcement.cover) if getattr(t, "reinforcement", None) else 25.0
            found.append(_Support(s_hit, float(t.thickness), "wall", e.id, cover))
        elif isinstance(e, BeamElement) and e.id not in members:
            if abs(e.elevation - elevation) > TOL:
                continue
            t = ctx.types.get(e.type)
            a, b = np.asarray(e.start, float), np.asarray(e.end, float)
            w = b - a
            wl = float(np.linalg.norm(w))
            if t is None or wl <= 0 or abs(float(w / wl @ u)) > 0.5:
                continue
            s_hit = _cross(origin, u, a, b)
            if s_hit is None:
                continue
            # only where this line ends on the other beam (a secondary beam on a girder)
            if min(abs(s_hit), abs(s_hit - line["length"])) > TOL:
                continue
            width = float(getattr(t.profile, "xDim", 0.0) or 0.0)
            cover = 40.0
            if getattr(t, "reinforcement", None):
                tr = t.reinforcement.transverse
                cover = t.reinforcement.cover + (tr.dia if tr else 0.0)
            found.append(_Support(s_hit, width, "beam", e.id, cover))
        _ = normal
    found.sort(key=lambda x: x.s)
    merged: list[_Support] = []
    for sup in found:
        if merged and abs(sup.s - merged[-1].s) <= TOL:
            if sup.width > merged[-1].width:
                merged[-1] = sup
            continue
        merged.append(sup)
    return merged


def _cross(origin: np.ndarray, u: np.ndarray, a: np.ndarray, b: np.ndarray) -> float | None:
    """Where the line origin + s u crosses the segment a-b (within TOL beyond its ends): s."""
    w = b - a
    den = u[0] * (-w[1]) - u[1] * (-w[0])
    if abs(den) < 1e-9:
        return None
    rhs = a - origin
    s = (rhs[0] * (-w[1]) - rhs[1] * (-w[0])) / den
    t = (u[0] * rhs[1] - u[1] * rhs[0]) / den
    wl = float(np.linalg.norm(w))
    if t * wl < -TOL or t * wl > wl + TOL:
        return None
    return float(s)


def _groups(reinforcement: Any, position: str) -> list[tuple[int, float]]:
    return [(g.count, float(g.dia)) for g in reinforcement.longitudinal if g.position == position]


def _beam_required_share(ctx: _Ctx, members: list[str], area_top: float) -> float:
    """The share of the top bars the design requires at mid-span (``required`` rows)."""
    share = 0.0
    for mid in members:
        for row in ctx.required.get(mid, {}).get("rows", []):
            if row.get("location") == "middle" and str(row.get("quantity", "")).startswith("top"):
                need = float(row.get("required") or 0.0)
                if area_top > 0:
                    share = max(share, need / area_top)
    return share


def _detail_beam_line(ctx: _Ctx, line: dict[str, Any]) -> dict[str, Any]:
    from saengine.design import ductile_members as dm
    from saengine.design.rc import bar_area

    t = ctx.types[line["type"]]
    element: dict[str, Any] = {
        "id": "+".join(line["members"]),
        "kind": "beam",
        "type": t.id,
        "member": " + ".join(line["members"]),
        "members": line["members"],
        "story": _story_at(ctx.building, line["elevation"]),
        "count": 1,
        "bars": [],
        "transverse": [],
        "laps": [],
        "checks": [],
        "notes": [],
    }
    for mid in line["members"]:
        element["notes"] += _report_notes(ctx, mid)
    r = t.reinforcement
    if r is None or not r.longitudinal:
        element["notes"].append(f"{t.id} has no reinforcement: not detailed")
        return element
    b, h = float(t.profile.xDim), float(t.profile.yDim)
    fc, fy = ctx.fc(t.material), ctx.fy(r.material)
    grade = ctx.grade(r.material)
    tr = r.transverse
    tdia = float(tr.dia) if tr else 0.0
    inset = float(r.cover) + tdia
    origin, u, elev = line["origin"], line["u"], line["elevation"]
    length = line["length"]
    step = ctx.step
    level, lateral = None, False
    for mid in line["members"]:
        lv, lat = _frame_of(ctx, mid)
        if _LEVELS[lv] > _LEVELS[level]:
            level = lv
        lateral = lateral or lat
    special = level == "special"
    supports = _line_supports(ctx, line)
    if not supports:
        element["notes"].append("no supports found along the beam: detailed as free at both ends")
    # an end is supported when the line ends within the support's width (a column centre need
    # not be at the beam's end)
    start_free = not supports or supports[0].s - supports[0].width / 2 > TOL
    end_free = not supports or supports[-1].s + supports[-1].width / 2 < length - TOL
    # clear spans between consecutive supports: (face_left, face_right)
    spans: list[tuple[float, float]] = []
    for s1, s2 in itertools.pairwise(supports):
        spans.append((s1.s + s1.width / 2, s2.s - s2.width / 2))
    if start_free and supports:
        spans.insert(0, (0.0, supports[0].s - supports[0].width / 2))
    if end_free and supports:
        spans.append((supports[-1].s + supports[-1].width / 2, length))
    if not supports:
        spans = [(0.0, length)]
    clear = [max(f2 - f1, 0.0) for f1, f2 in spans]
    # bar ends along the line
    s_start = (
        (supports[0].s - supports[0].width / 2 + supports[0].cover) if not start_free else (r.cover)
    )
    s_end = (
        (supports[-1].s + supports[-1].width / 2 - supports[-1].cover)
        if not end_free
        else (length - r.cover)
    )
    element["at"] = {
        "origin": [round(float(origin[0]), 1), round(float(origin[1]), 1)],
        "direction": [round(float(u[0]), 6), round(float(u[1]), 6)],
        "length": round(length, 1),
        "elevation": elev,
        "width": b,
        "depth": h,
        "cover": float(r.cover),
        "supports": [
            {"s": round(x.s, 1), "width": x.width, "kind": x.kind, "ref": x.ref} for x in supports
        ],
        "spans": [{"from": round(a, 1), "to": round(c, 1)} for a, c in spans],
    }

    def z_of(face: str, db: float) -> float:
        return elev - inset - db / 2 if face == "top" else elev - h + inset + db / 2

    tops = _groups(r, "top")
    bottoms = _groups(r, "bottom")
    sides = _groups(r, "sides")
    n_top = sum(c for c, _ in tops)
    area_top = sum(c * bar_area(d) for c, d in tops)
    share = _beam_required_share(ctx, line["members"], area_top)
    n_cont = continuous_top_bars(n_top, share) if ctx.options["curtail"] else n_top
    if n_top and n_cont < n_top:
        element["notes"].append(
            f"top bars: {n_cont} of {n_top} continuous (at least two, 8.3.4.2(a); at least 1/3, "
            "8.2.9.3), the others over the supports to max(0.30 ln, ld) from the face "
            "(practice, not a BNBC rule)"
        )
    db_main = max([d for _, d in tops + bottoms] or [16.0])
    d_eff = h - inset - db_main / 2

    def cb_of(face: str, db: float) -> float:
        """cb (8.2.3.3) of a bar on ``face``: side cover or half the spacing of that layer."""
        n = sum(c for c, _ in (tops if face == "top" else bottoms if face == "bottom" else sides))
        spacing = (b - 2 * inset - db) / (n - 1) if n > 1 else None
        return _cb(inset, db, spacing)

    # splice windows: top bars in the middle third, bottom bars in the end thirds; in special
    # frames none within 2 h of a joint face (8.3.4.2(b), p 1091)
    offset = seismic_splice_exclusion(h).value if special else 0.0
    top_windows = []
    for f1, f2 in spans:
        third = (f2 - f1) / 3
        w0 = max(f1 + third, f1 + offset if f1 > 0 or not start_free else f1 + third)
        w1 = min(f2 - third, f2 - offset if f2 < length or not end_free else f2 - third)
        if w1 - w0 > 1:
            top_windows.append((w0, w1))
    bottom_windows: list[tuple[float, float]] = []
    for f1, f2 in spans:
        third = (f2 - f1) / 3
        candidates = []
        if f1 > 0:
            candidates.append((f1 + offset, f1 + max(third, offset)))
        if f2 < length:
            candidates.append((f2 - max(third, offset), f2 - offset))
        for a, c in candidates:
            # clipped to the span less 2 h at both faces (a short span has none)
            a, c = max(a, f1 + offset), min(c, f2 - offset)
            if c - a > 1:
                bottom_windows.append((a, c))
    if special:
        element["notes"].append(
            "laps placed outside the joints and 2 h from their faces "
            f"({_page('8.3.4.2(b)', 1091)}); top bars lapped in the middle third, bottom bars "
            f"near the supports ({_page('8.1.12.2(b)', 1075)}); a bar with no such place in a "
            "stock length is noted"
        )

    def anchorage(face: str, db: float, at_start: bool) -> tuple[float, str | None]:
        """(hook leg outside dim, None) at a supported end; (leg, 'free') at a free end."""
        free = start_free if at_start else end_free
        hook = standard_hook(db, 90)
        if free:
            return (hook.leg if face == "top" else 0.0), "free"
        sup = supports[0] if at_start else supports[-1]
        avail = sup.width - sup.cover
        need = (
            hook_development_seismic(db, fy, fc)
            if special and lateral
            else hook_development(db, fy, fc)
        )
        element["checks"].append(
            _check(
                f"Hooked {face} bar Ø{db:g} into {sup.ref} ({'start' if at_start else 'end'})",
                need.value,
                avail,
                need.clause,
            )
        )
        room = h - 2 * inset
        if hook.leg > room:
            element["notes"].append(
                f"the 12 db hook of Ø{db:g} ({hook.leg:.0f} mm) is longer than the beam's inside "
                f"depth ({room:.0f} mm): turn it sideways or use a smaller bar"
            )
        return hook.leg, None

    def run_bar(
        role: str,
        letter: str,
        face: str,
        count: int,
        db: float,
        a: float,
        c: float,
        windows: list[tuple[float, float]],
        hooks: tuple[float, float],
        top: bool,
        **extra: Any,
    ) -> list[dict[str, Any]]:
        bend = bend_diameter(db).value
        lap = ctx.lap(db, fy, fc, top=top, cb=cb_of(face, db))
        pieces, laps, ok = split_run(a, c, lap, windows, ctx.stock, hooks)
        if not ok:
            element["notes"].append(
                f"{role} bars Ø{db:g}: no lap location within a stock length "
                f"({ctx.stock:g} mm) in the permitted zones: one bar longer than stock (use a "
                "mechanical splice or longer bars)"
            )
        out = []
        z = z_of(face, db)
        for k, (p0, p1) in enumerate(pieces):
            hs = hooks[0] if k == 0 else 0.0
            he = hooks[1] if k == len(pieces) - 1 else 0.0
            run = p1 - p0
            if hs and he:
                dims, shape = {"A": hs, "B": run, "C": he}, "U"
                total = u_length(hs, run, he, db, bend)
            elif hs or he:
                dims, shape = {"A": run, "B": hs or he}, "L"
                total = l_length(run, hs or he, db, bend)
            else:
                dims, shape = {"A": run}, "straight"
                total = run
            covered = [m for s0, s1, m in line["pieces"] if s1 > p0 + 1 and s0 < p1 - 1]
            bar = _bar(
                role,
                letter,
                db,
                shape,
                count,
                dims,
                total,
                {
                    "from": round(p0, 1),
                    "to": round(p1, 1),
                    "face": face,
                    "layer": 1,
                    "members": covered,
                    "start": _point(origin, u, p0, z),
                    "end": _point(origin, u, p1, z),
                    "hooks": [
                        ("down" if face == "top" else "up") if hs else None,
                        ("down" if face == "top" else "up") if he else None,
                    ],
                },
                bend=bend,
                grade=grade,
                lap=lap if laps else None,
                **extra,
            )
            out.append(bar)
        for l0, l1 in laps:
            element["laps"].append(
                {
                    "bars": [out[i] for i in range(len(out))],
                    "from": round(l0, 1),
                    "to": round(l1, 1),
                    "length": lap,
                    "class": "B",
                    "face": face,
                    "clause": _page("8.2.13.1, 8.2.13.2", 1083),
                }
            )
        return out

    top_below = h - inset - db_main > 300  # more than 300 mm of fresh concrete below (ψt)
    # top bars: continuous ones first, from the largest diameter (the corner bars)
    remaining = n_cont
    extras: list[tuple[int, float]] = []
    for count, db in sorted(tops, key=lambda g: -g[1]):
        take = min(count, remaining)
        remaining -= take
        if take:
            hs = anchorage("top", db, True)[0]
            he = anchorage("top", db, False)[0]
            element["bars"] += run_bar(
                "top", "T", "top", take, db, s_start, s_end, top_windows, (hs, he), top_below
            )
        if count - take:
            extras.append((count - take, db))
    for count, db in extras:
        ld = up(ctx.ld(db, fy, fc, top=top_below, cb=cb_of("top", db)), step)
        bend = bend_diameter(db).value
        # one interval per support, kept within the bar ends of the line; intervals that meet
        # in a short span become one bar across it
        runs: list[dict[str, Any]] = []
        for j, sup in enumerate(supports):
            # the clear spans either side of the support (0: none, the line ends there)
            lf, rf = sup.s - sup.width / 2, sup.s + sup.width / 2
            left = next(
                (c for (a, c2), c in zip(spans, clear, strict=False) if abs(c2 - lf) < 1), 0
            )
            right = next(
                (c for (a, c2), c in zip(spans, clear, strict=False) if abs(a - rf) < 1), 0
            )
            ln = max(left, right)
            extent = up(standard_top_extent(ln, ld, ctx.options["beamTopExtent"]).value, step)
            p0 = lf - extent if left > 0 else lf + sup.cover
            p1 = rf + extent if right > 0 else rf - sup.cover
            start_end = left <= 0
            end_end = right <= 0
            # over the support of a cantilever the bars run to its tip, bent down there
            tip0 = start_free and j == 0 and left > 0
            tip1 = end_free and j == len(supports) - 1 and right > 0
            if tip0:
                p0 = s_start
            if tip1:
                p1 = s_end
            # never past the bar ends of the line: there the bar hooks into the end support
            if p0 <= s_start + 1e-6:
                p0, start_end = s_start, not tip0
            if p1 >= s_end - 1e-6:
                p1, end_end = s_end, not tip1
            if runs and p0 <= runs[-1]["to"] + 1e-6:
                last = runs[-1]
                last["to"], last["endHook"], last["tip1"] = p1, end_end, tip1
                last["refs"].append(sup.ref)
                last["extents"].append(extent)
            else:
                runs.append(
                    {"from": p0, "to": p1, "startHook": start_end, "endHook": end_end,
                     "tip0": tip0, "tip1": tip1, "refs": [sup.ref], "extents": [extent]}
                )  # fmt: skip
        for row in runs:
            p0, p1 = row["from"], row["to"]
            hs = (
                standard_hook(db).leg
                if row["tip0"]
                else anchorage("top", db, True)[0]
                if row["startHook"]
                else 0.0
            )
            he = (
                standard_hook(db).leg
                if row["tip1"]
                else anchorage("top", db, False)[0]
                if row["endHook"]
                else 0.0
            )
            refs = row["refs"]
            sup_ref = refs[0] if len(refs) == 1 else "+".join(refs)
            remarks = (
                f"over {refs[0]}, {row['extents'][0]:g} mm from the face"
                if len(refs) == 1
                else f"over {', '.join(refs)}: the extents meet, one bar across the span"
            )
            run = p1 - p0
            if hs and he:
                dims, shape = {"A": hs, "B": run, "C": he}, "U"
                total = u_length(hs, run, he, db, bend)
            elif hs or he:
                dims, shape = {"A": run, "B": hs or he}, "L"
                total = l_length(run, hs or he, db, bend)
            else:
                dims, shape, total = {"A": run}, "straight", run
            if run + hs + he > ctx.stock + 1e-6:
                element["notes"].append(
                    f"extra top bars Ø{db:g} over {sup_ref}: {run + hs + he:.0f} mm, longer than "
                    f"a stock length ({ctx.stock:g} mm): lap them in the middle third"
                )
            z = z_of("top", db)
            covered = [m for s0, s1, m in line["pieces"] if s1 > p0 + 1 and s0 < p1 - 1]
            element["bars"].append(
                _bar(
                    "top",
                    "T",
                    db,
                    shape,
                    count,
                    dims,
                    total,
                    {
                        "from": round(p0, 1),
                        "to": round(p1, 1),
                        "face": "top",
                        "layer": 1,
                        "support": sup_ref,
                        "supports": refs,
                        "members": covered,
                        "start": _point(origin, u, p0, z),
                        "end": _point(origin, u, p1, z),
                        "hooks": ["down" if hs else None, "down" if he else None],
                    },
                    bend=bend,
                    grade=grade,
                    curtailed=True,
                    remarks=remarks,
                )
            )
    # bottom bars: all run into the supports (8.2.8.1, 8.2.8.2)
    for count, db in sorted(bottoms, key=lambda g: -g[1]):
        hs = anchorage("bottom", db, True)[0] if not start_free else 0.0
        he = anchorage("bottom", db, False)[0] if not end_free else 0.0
        element["bars"] += run_bar(
            "bottom", "B", "bottom", count, db, s_start, s_end, bottom_windows or top_windows,
            (hs, he), False,
        )  # fmt: skip
    if supports and bottoms:
        n_bottom = sum(c for c, _ in bottoms)
        need = positive_into_support(n_bottom, len(supports) > 2)
        element["checks"].append(
            _check(
                "Bottom bars into the supports",
                need,
                n_bottom,
                _page("8.2.8.1", 1080),
                unit="bars",
            )
        )
    for count, db in sides:
        element["bars"] += run_bar(
            "side", "F", "side", count, db, s_start, s_end, top_windows, (0.0, 0.0), False
        )
    # stirrups per span
    if tr is not None:
        zones = dm.zones_of(tr)
        zone_len = zones.zone_length
        if zone_len is None:
            for mid in line["members"]:
                lo = (((ctx.report.get(mid) or {}).get("detailing") or {}).get("zones") or {}).get(
                    "lo"
                )
                if lo:
                    zone_len = max(zone_len or 0.0, float(lo))
        if zone_len is None and lateral and level in ("special", "intermediate"):
            zone_len = 2 * h  # 8.3.4.3(a), 8.3.10.4(b) (dm.beam_need)
        zone_s = zones.zone_spacing
        if zone_len and zone_s is None:
            element["notes"].append(
                f"the type has no end zone: stirrups at {tr.spacing:g} mm all along (the code "
                f"asks a zone of {zone_len:.0f} mm from each face; see the design checks)"
            )
        first = zones.zone_first or (
            FIRST_STIRRUP if zone_len else min(FIRST_STIRRUP, tr.spacing / 2)
        )
        hook = seismic_hook(tdia)
        sa, sb = b - 2 * r.cover, h - 2 * r.cover
        stirrup = _bar(
            "stirrup",
            "S",
            tdia,
            "stirrup",
            0,
            {"A": sa, "B": sb},
            stirrup_length(sa, sb, tdia, hook),
            {"section": [sa, sb], "legs": tr.legs},
            bend=hook.bend_dia,
            grade=grade,
        )
        extra_legs = max(tr.legs - 2, 0)
        tie = None
        if extra_legs:
            h135, h90 = seismic_hook(tdia), standard_hook(tdia, 90, transverse=True)
            tie = _bar(
                "crosstie",
                "X",
                tdia,
                "special",
                0,
                {"A": sb},
                crosstie_length(sb, tdia, h135, h90),
                {"section": [sa, sb], "legs": extra_legs},
                bend=h135.bend_dia,
                grade=grade,
                remarks="cross tie: 135° hook one end, 90° the other, alternated (8.1.1.1)",
            )
        total = 0
        for (f1, f2), ln in zip(spans, clear, strict=False):
            if ln <= 0:
                continue
            rules: list[tuple[float, float, float, str]] = []
            if zone_len and zone_s:
                if f1 > 0 or not start_free:
                    rules.append((f1, f1 + zone_len, zone_s, "lo"))
                if f2 < length or not end_free:
                    rules.append((f2 - zone_len, f2, zone_s, "lo"))
            if zones.splice_spacing:
                for lap in element["laps"]:
                    if lap["from"] < f2 and lap["to"] > f1:
                        rules.append((lap["from"], lap["to"], zones.splice_spacing, "splice"))
            rows = space(f1, f2, float(tr.spacing), rules, first)
            for row in rows:
                row["_bar"] = stirrup
                element["transverse"].append(row)
            total += sum(row["count"] for row in rows)
        stirrup["count"] = total
        element["bars"].append(stirrup)
        if tie is not None:
            tie["count"] = total * extra_legs
            element["bars"].append(tie)
        if special and element["laps"] and not zones.splice_spacing:
            element["notes"].append(
                f"hoops over the laps at <= min(d/4, 100 mm) = {min(d_eff / 4, 100):.0f} mm "
                f"({_page('8.3.4.2(b)', 1091)}): the type gives no splice spacing"
            )
    sizes = sorted({d for _, d in tops + bottoms})
    lds = ", ".join(
        f"Ø{d:g} {up(ctx.ld(d, fy, fc, cb=cb_of('bottom', d)), step):g} mm" for d in sizes
    )
    laps = ", ".join(f"Ø{d:g} {ctx.lap(d, fy, fc, cb=cb_of('bottom', d)):g} mm" for d in sizes)
    element["notes"].append(
        f"ld ({ctx.method_text}) of the bottom bars: {lds}; class B laps: {laps}"
    )
    element["checks"] = _unique(element["checks"])
    return element


def _unique(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in checks:
        seen.setdefault(row["name"], row)
    return list(seen.values())


# ────────────────────────────────────────── columns ──────────────────────────────────────────


def _foundation_under(ctx: _Ctx, column: Any) -> dict[str, Any] | None:
    """The foundation a column or wall stands on: {id, bottom, top, thickness, cover, mesh, fc}."""
    from saengine.library.bim import FootingElement

    if ctx.substructure is not None:
        from saengine.library.bim import foundation_solids

        ground = 0.0
        if ctx.settings is not None:
            ground = float(ctx.settings.foundation.groundLevel)
        try:
            solids = foundation_solids(ctx.substructure, ctx.building, ground)
        except (ValueError, AttributeError):
            solids = None
        if solids is not None:
            by_id = {f.id: f for f in ctx.substructure.foundations}
            for s in solids.foundations:
                f = by_id.get(s.id)
                if f is None or column.id not in f.columns:
                    continue
                r = s.reinforcement
                mesh = [
                    m.dia for m in (getattr(r, "bottomX", None), getattr(r, "bottomY", None)) if m
                ]
                return {
                    "id": s.id,
                    "bottom": s.bottom,
                    "top": s.top,
                    "thickness": s.thickness,
                    "cover": float(r.cover) if r is not None else 75.0,
                    "mesh": mesh,
                    "fc": ctx.fc(s.material or ""),
                }
        return None
    pos = np.asarray(getattr(column, "position", None) or column.start, float)
    for e in ctx.building.elements:
        if isinstance(e, FootingElement) and np.linalg.norm(np.asarray(e.position) - pos) <= TOL:
            t = ctx.types.get(e.type)
            if t is None:
                continue
            r = t.reinforcement
            mesh = [m.dia for m in (getattr(r, "bottomX", None), getattr(r, "bottomY", None)) if m]
            return {
                "id": e.id,
                "bottom": e.elevation - t.thickness,
                "top": e.elevation,
                "thickness": float(t.thickness),
                "cover": float(r.cover) if r is not None else 75.0,
                "mesh": mesh,
                "fc": ctx.fc(t.material),
            }
    return None


def _stacks(ctx: _Ctx) -> list[list[Any]]:
    from saengine.library.bim import ColumnElement

    cols = sorted(
        (e for e in ctx.building.elements if isinstance(e, ColumnElement)),
        key=lambda e: (e.bottom, e.id),
    )
    stacks: list[list[Any]] = []
    for c in cols:
        for stack in stacks:
            last = stack[-1]
            if math.dist(last.position, c.position) <= TOL and abs(last.top - c.bottom) <= TOL:
                stack.append(c)
                break
        else:
            stacks.append([c])
    return stacks


def _beam_depth_at(ctx: _Ctx, column: Any, level: float) -> float:
    depth = 0.0
    for joint in ctx.joints:
        if joint.below == column.id and abs(joint.level - level) <= TOL:
            for jb in joint.beams:
                t = ctx.types.get(jb.type)
                depth = max(depth, float(getattr(getattr(t, "profile", None), "yDim", 0.0) or 0.0))
    return depth


def _column_lap_rule(ctx: _Ctx, db: float, fy: float, fc: float, special: bool) -> Rule:
    if ctx.options["columnLaps"] == "compression" and not special:
        return column_lap(db, fy, fc, stress="compression")
    return column_lap(db, fy, fc, stress="tension")


def _lap_start(hc: float, lap: float, special: bool) -> tuple[float, bool]:
    """Lap start above the floor, and whether it fits the rules."""
    if special:
        lo, hi = column_splice_region(hc)
        start = max(lo, hc / 2 - lap / 2)
        return start, start + lap <= hi + 1e-6
    return 0.0, True


def _detail_column(ctx: _Ctx, stack: list[Any], k: int) -> dict[str, Any]:
    from saengine.design import ductile_joints as dj
    from saengine.design import ductile_members as dm
    from saengine.library.objects import CircleProfile, RectangleProfile

    c = stack[k]
    t = ctx.types.get(c.type)
    element: dict[str, Any] = {
        "id": c.id,
        "kind": "column",
        "type": c.type,
        "member": c.id,
        "story": _story_at(ctx.building, c.top),
        "count": 1,
        "bars": [],
        "transverse": [],
        "laps": [],
        "checks": [],
        "notes": _report_notes(ctx, c.id),
        "at": {
            "position": [float(c.position[0]), float(c.position[1])],
            "rotation": float(c.rotation or 0.0),
            "bottom": float(c.bottom),
            "top": float(c.top),
        },
    }
    if t is None or getattr(t, "kind", None) != "column":
        element["notes"].append(f"type {c.type} is not a column type: not detailed")
        return element
    r = t.reinforcement
    if r is None or not r.longitudinal:
        element["notes"].append(f"{t.id} has no reinforcement: not detailed")
        return element
    profile = t.profile
    if not isinstance(profile, (RectangleProfile, CircleProfile)):
        element["notes"].append(f"{profile.shape} columns are not detailed")
        return element
    fc, fy, grade = ctx.fc(t.material), ctx.fy(r.material), ctx.grade(r.material)
    step = ctx.step
    level, lateral = _frame_of(ctx, c.id)
    special = level == "special" and lateral
    tr = r.transverse
    tdia = float(tr.dia) if tr else 10.0
    cover = float(r.cover)
    beam_top = _beam_depth_at(ctx, c, c.top)
    hc = c.top - c.bottom - beam_top
    element["at"]["clearHeight"] = hc
    above = stack[k + 1] if k + 1 < len(stack) else None
    t_above = ctx.types.get(above.type) if above is not None else None
    r_above = getattr(t_above, "reinforcement", None) if t_above is not None else None
    groups = [(g.count, float(g.dia)) for g in r.longitudinal]
    n_bars = sum(n for n, _ in groups)
    db_max = max(d for _, d in groups)
    lap_here = up(_column_lap_rule(ctx, db_max, fy, fc, special).value, step)
    start_here, fits = _lap_start(hc, lap_here, special)
    if special and k > 0 and not fits:
        element["notes"].append(
            f"the lap ({lap_here:g} mm) does not fit the centre half of the clear height "
            f"({hc:.0f} mm, {_page('8.3.5.3(b)', 1096)}): use mechanical splices"
        )
    found = _foundation_under(ctx, c) if k == 0 else None
    # the bars start at the lap with the bars below; the lowest column with nothing under it
    # (no foundation in the model): at its base
    z_lap = c.bottom + start_here if (k > 0 or found is not None) else c.bottom
    # the lap above, in the next storey
    if above is not None and r_above is not None and r_above.longitudinal:
        db_up = max(float(g.dia) for g in r_above.longitudinal)
        fy_up = ctx.fy(r_above.material)
        lap_up = up(
            max(
                _column_lap_rule(ctx, db_max, fy, fc, special).value,
                _column_lap_rule(ctx, db_up, fy_up, fc, special).value,
            ),
            step,
        )
        beam_up = _beam_depth_at(ctx, above, above.top)
        lv_up, lat_up = _frame_of(ctx, above.id)
        s_up, _ = _lap_start(
            above.top - above.bottom - beam_up, lap_up, lv_up == "special" and lat_up
        )
        z_end = above.bottom + s_up + lap_up
        n_up = sum(g.count for g in r_above.longitudinal)
        partners = min(n_up, n_bars)
        if n_up != n_bars or db_up != db_max:
            text = (
                f"the column above ({above.id}, {above.type}) has {n_up} bars up to Ø{db_up:g}: "
                f"{partners} bars lap with them for {lap_up:g} mm (8.2.13.5)"
            )
            if n_bars > n_up:
                text += (
                    f"; the other {n_bars - n_up} (the smallest) stop 40 mm below the top of "
                    "the floor with a 90° hook into it"
                )
            if n_up > n_bars:
                text += (
                    f"; its other {n_up - n_bars} bars start on dowels Ø{db_up:g} anchored ld "
                    "below the floor in this column"
                )
            element["notes"].append(text)
        top_hook = 0.0
        element["laps"].append(
            {
                "bars": [],
                "from": round(above.bottom + s_up, 1),
                "to": round(z_end, 1),
                "length": lap_up,
                "class": "B"
                if ctx.options["columnLaps"] == "tension" or special
                else "compression",
                "clause": _column_lap_rule(ctx, db_max, fy, fc, special).clause,
                "with": above.id,
            }
        )
    else:
        top_cover = 40.0
        z_end = c.top - top_cover
        top_hook = 1.0
        if beam_top > 0:
            need = hook_development(db_max, fy, fc)
            element["checks"].append(
                _check(
                    f"Column bars hooked into the beams at the top (Ø{db_max:g})",
                    need.value,
                    beam_top - top_cover,
                    need.clause,
                )
            )
        else:
            element["notes"].append("no beam at the top: the bars end 40 mm below the top, hooked")
        partners = n_bars
    # vertical bars: the largest first take the partners above; the others stop at the floor
    lapping_up: list[dict[str, Any]] = []
    left = partners
    pieces_v: list[tuple[int, float, bool]] = []
    for count, db in sorted(groups, key=lambda g: -g[1]):
        take = min(count, left)
        left -= take
        if take:
            pieces_v.append((take, db, False))
        if count - take:
            pieces_v.append((count - take, db, True))
    stopped_any = False
    for count, db, stops in pieces_v:
        bend = bend_diameter(db).value
        hook = standard_hook(db, 90)
        hooked = bool(top_hook) or stops
        z_top = (c.top - 40.0) if stops else z_end
        run = z_top - z_lap
        if hooked:
            dims, shape = {"A": run, "B": hook.leg}, "L"
            total = l_length(run, hook.leg, db, bend)
        else:
            dims, shape, total = {"A": run}, "straight", run
        if run > ctx.stock:
            element["notes"].append(
                f"vertical bars Ø{db:g} longer than a stock length ({run:.0f} mm): add a lap"
            )
        bar = _bar(
            "vertical",
            "V",
            db,
            shape,
            count,
            dims,
            total,
            {
                "from": round(z_lap, 1),
                "to": round(z_top, 1),
                "position": element["at"]["position"],
                "hooks": [None, "inward" if hooked else None],
            },
            bend=bend,
            grade=grade,
            lap=lap_here if k > 0 or found else None,
            **({"remarks": "no partner in the column above: stops at the floor"} if stops else {}),
        )
        element["bars"].append(bar)
        if not stops:
            lapping_up.append(bar)
        stopped_any = stopped_any or stops
    if stopped_any and beam_top > 0:
        db_stop = max(d for _, d, st in pieces_v if st)
        need = hook_development(db_stop, fy, fc)
        element["checks"].append(
            _check(
                f"Column bars without a partner hooked into the floor (Ø{db_stop:g})",
                need.value,
                beam_top - 40.0,
                need.clause,
            )
        )
    if above is not None and r_above is not None and r_above.longitudinal:
        n_up = sum(g.count for g in r_above.longitudinal)
        if n_up > n_bars:
            db_up = max(float(g.dia) for g in r_above.longitudinal)
            fy_up = ctx.fy(r_above.material)
            ld_up = up(ctx.ld(db_up, fy_up, fc, cb=_cb(cover + tdia, db_up, None)), step)
            z0 = max(above.bottom - ld_up, c.bottom)
            if above.bottom - ld_up < c.bottom - 1e-6:
                element["notes"].append(
                    f"dowels Ø{db_up:g} for {above.id}: ld {ld_up:g} mm is more than this "
                    "storey's height"
                )
            dowel = _bar(
                "starter",
                "D",
                db_up,
                "straight",
                n_up - n_bars,
                {"A": z_end - z0},
                z_end - z0,
                {
                    "from": round(z0, 1),
                    "to": round(z_end, 1),
                    "position": element["at"]["position"],
                    "for": above.id,
                    "hooks": [None, None],
                },
                bend=bend_diameter(db_up).value,
                grade=ctx.grade(r_above.material),
                lap=lap_up,
                remarks=f"dowels for the extra bars of {above.id}: ld below the floor, lap above",
            )
            element["bars"].append(dowel)
            lapping_up.append(dowel)
    for lap in element["laps"]:
        lap["bars"] = list(lapping_up)
    # starter bars (dowels) from the foundation
    if k == 0:
        if found is not None:
            mesh = sum(found["mesh"][:2]) if found["mesh"] else 0.0
            for count, db in sorted(groups, key=lambda g: -g[1]):
                bend = bend_diameter(db).value
                hook = standard_hook(db, 90)
                z0 = found["bottom"] + found["cover"] + mesh
                z1 = z_lap + lap_here
                dims = {"A": z1 - z0, "B": hook.leg}
                element["bars"].append(
                    _bar(
                        "starter",
                        "D",
                        db,
                        "L",
                        count,
                        dims,
                        l_length(dims["A"], dims["B"], db, bend),
                        {
                            "from": round(z0, 1),
                            "to": round(z1, 1),
                            "position": element["at"]["position"],
                            "foundation": found["id"],
                            "hooks": ["toCentre", None],
                        },
                        bend=bend,
                        grade=grade,
                        lap=lap_here,
                        remarks=f"starter bars from {found['id']}, 90° hook on its bottom mesh",
                    )
                )
                element["checks"] += [
                    {
                        "name": row["name"],
                        "required": row["demand"],
                        "provided": row["capacity"],
                        "unit": row["unit"],
                        "ok": row["ok"],
                        "clause": _page("8.3.11.2(a), (b); 8.2.6", "1079, 1120"),
                    }
                    for row in dj.column_dowel_checks(
                        c.id, db, fy, found["fc"], found["thickness"], found["cover"],
                        max(found["mesh"] or [0.0]),
                    )
                ]  # fmt: skip
            element["laps"].append(
                {
                    "bars": [b for b in element["bars"] if b["role"] in ("starter", "vertical")],
                    "from": round(z_lap, 1),
                    "to": round(z_lap + lap_here, 1),
                    "length": lap_here,
                    "class": "B"
                    if ctx.options["columnLaps"] == "tension" or special
                    else "compression",
                    "clause": _column_lap_rule(ctx, db_max, fy, fc, special).clause,
                    "with": found["id"],
                }
            )
        else:
            element["notes"].append(
                f"no foundation under {c.id}: its bars start at its base (on a beam: a transfer "
                "detail, not drawn)"
            )
    # ties
    if tr is not None:
        zones = dm.zones_of(tr)
        lo = zones.zone_length
        info = ((ctx.report.get(c.id) or {}).get("detailing") or {}).get("zones") or {}
        if lo is None and info.get("lo"):
            lo = float(info["lo"])
        if lo is None and lateral and level in ("special", "intermediate"):
            largest = (
                2 * profile.radius
                if isinstance(profile, CircleProfile)
                else max(profile.xDim, profile.yDim)
            )
            lo = max(largest, hc / 6, 450.0)  # 8.3.5.4(d), 8.3.10.5(a)
        zs = zones.zone_spacing
        if lo and zs is None:
            element["notes"].append(
                f"the type has no end zone: ties at {tr.spacing:g} mm all along (the code asks "
                f"lo = {lo:.0f} mm; see the design checks)"
            )
        first = zones.zone_first or ((zs or tr.spacing) / 2)  # 8.1.9.4(d), Figure 6.8.8
        rules: list[tuple[float, float, float, str]] = []
        if lo and zs:
            rules += [
                (c.bottom, c.bottom + lo, zs, "lo"),
                (c.bottom + hc - lo, c.bottom + hc, zs, "lo"),
                (c.bottom + hc, c.top, zs, "joint"),
            ]
        if zones.splice_spacing:
            for lap in element["laps"]:
                if lap["from"] < c.top and lap["to"] > c.bottom:
                    rules.append((lap["from"], lap["to"], zones.splice_spacing, "splice"))
        if isinstance(profile, CircleProfile) and tr.type == "spiral":
            dout = 2 * profile.radius - 2 * cover
            pitch = float(tr.spacing)
            turns = (c.top - c.bottom) / pitch + 3  # 1.5 extra turns at each end (8.1.9.3(d))
            total = turns * math.hypot(math.pi * (dout - tdia), pitch)
            element["bars"].append(
                _bar(
                    "spiral",
                    "P",
                    tdia,
                    "helix",
                    1,
                    {"A": dout, "B": pitch, "C": round(turns, 2)},
                    total,
                    {"from": c.bottom, "to": c.top},
                    bend=0.0,
                    grade=grade,
                    remarks="1.5 extra turns at each end (8.1.9.3(d)); laps 48 db (8.1.9.3(e))",
                )
            )
        else:
            rows = space(c.bottom, c.top, float(tr.spacing), rules, first)
            n = sum(row["count"] for row in rows)
            hook = seismic_hook(tdia)
            if isinstance(profile, CircleProfile):
                dout = 2 * profile.radius - 2 * cover
                hoop = _bar(
                    "tie",
                    "H",
                    tdia,
                    "special",
                    n,
                    {"A": dout},
                    math.pi * (dout - tdia) + 2 * hook.tail + 2 * hook.arc,
                    {"section": [dout]},
                    bend=hook.bend_dia,
                    grade=grade,
                    remarks="circular hoop, 135° hooks of max(6 db, 75 mm) (8.1.2.1(d))",
                )
            else:
                ta, tb = profile.xDim - 2 * cover, profile.yDim - 2 * cover
                hoop = _bar(
                    "tie",
                    "H",
                    tdia,
                    "stirrup",
                    n,
                    {"A": ta, "B": tb},
                    stirrup_length(ta, tb, tdia, hook),
                    {"section": [ta, tb]},
                    bend=hook.bend_dia,
                    grade=grade,
                )
            for row in rows:
                row["_bar"] = hoop
            element["transverse"] += rows
            element["bars"].append(hoop)
            if isinstance(profile, RectangleProfile):
                h135, h90 = seismic_hook(tdia), standard_hook(tdia, 90, transverse=True)
                for legs, across, name in (
                    (tr.legs, profile.yDim - 2 * cover, "y"),
                    (tr.legsX if tr.legsX is not None else tr.legs, profile.xDim - 2 * cover, "x"),
                ):
                    extra = max(int(legs) - 2, 0)
                    if extra:
                        element["bars"].append(
                            _bar(
                                "crosstie",
                                "X",
                                tdia,
                                "special",
                                n * extra,
                                {"A": across},
                                crosstie_length(across, tdia, h135, h90),
                                {"along": name, "legs": extra},
                                bend=h135.bend_dia,
                                grade=grade,
                                remarks="cross tie, 90° hooks alternated end for end (8.1.1.1)",
                            )
                        )
    return element


# ─────────────────────────────────────────── slabs ───────────────────────────────────────────


def _edge_support(ctx: _Ctx, a: tuple[float, float], b: tuple[float, float], level: float):
    """(width, ref) of the beam or wall under a slab edge a-b, (0, None) when none."""
    from saengine.library.bim import BeamElement, WallElement

    pa, pb = np.asarray(a, float), np.asarray(b, float)
    d = pb - pa
    length = float(np.linalg.norm(d))
    u = d / length
    best = (0.0, None)
    for e in ctx.building.elements:
        if isinstance(e, BeamElement):
            if abs(e.elevation - level) > TOL:
                continue
            t = ctx.types.get(e.type)
            width = float(getattr(getattr(t, "profile", None), "xDim", 0.0) or 0.0)
        elif isinstance(e, WallElement):
            if not (e.bottom < level <= e.top + TOL):
                continue
            t = ctx.types.get(e.type)
            width = float(getattr(t, "thickness", 0.0) or 0.0)
        else:
            continue
        q0, q1 = np.asarray(e.start, float), np.asarray(e.end, float)
        off = [abs(float((q - pa)[0] * u[1] - (q - pa)[1] * u[0])) for q in (q0, q1)]
        if max(off) > max(TOL, width / 2):
            continue
        t0, t1 = sorted((float((q0 - pa) @ u), float((q1 - pa) @ u)))
        overlap = min(t1, length) - max(t0, 0.0)
        if overlap > 0.5 * length and width > best[0]:
            best = (width, e.id)
    return best


def _support_depth(ctx: _Ctx, ref: str | None) -> float:
    """Depth [mm] of the beam ``ref`` under a slab edge; a wall: unlimited (it runs on below)."""
    from saengine.library.bim import BeamElement, WallElement

    for e in ctx.building.elements:
        if e.id != ref:
            continue
        if isinstance(e, WallElement):
            return math.inf
        if isinstance(e, BeamElement):
            t = ctx.types.get(e.type)
            return float(getattr(getattr(t, "profile", None), "yDim", 0.0) or 0.0)
    return 0.0


def _edge_anchorage(
    ctx: _Ctx,
    element: dict[str, Any],
    name: str,
    db: float,
    fy: float,
    fc: float,
    h: float,
    cover: float,
    width: float,
    ref: str | None,
) -> float:
    """The bent-down leg [mm] of slab top bars at a discontinuous edge on ``ref`` (width
    ``width``), with the anchorage check of 8.2.9.1 (p 1081: negative steel anchored in or
    through the support): a standard 90° hook (8.1.2.1(b), p 1065) when the support is deep
    enough, the bar's hook into the beam below the slab; else as deep as it goes, and the
    straight length in the support checked against ld."""
    hook = standard_hook(db)
    depth = _support_depth(ctx, ref)
    room = max(depth, h) - 2 * cover  # down into the beam, above its bottom cover
    straight = width - cover
    if hook.leg <= room + 1e-6:
        need = hook_development(db, fy, fc)
        element["checks"].append(
            _check(
                f"Top {name} bars Ø{db:g} hooked into the edge support {ref}",
                need.value, straight, _page("8.2.9.1; 8.2.6", "1081, 1079"),
            )
        )  # fmt: skip
        return hook.leg
    leg = max(room, 0.0)
    ld = ctx.ld(db, fy, fc, cb=_cb(cover, db, None))
    element["checks"].append(
        _check(
            f"Top {name} bars Ø{db:g} at the edge {ref}: straight length in the support (the "
            f"bend of {leg:.0f} mm is shorter than a 12 db hook)",
            ld, straight, _page("8.2.9.1; 8.2.3", "1081, 1077"),
        )
    )  # fmt: skip
    element["notes"].append(
        f"top {name} bars at the edge {ref}: bent down {leg:.0f} mm, less than a standard hook "
        f"(12 db, 8.1.2.1(b)); anchorage by the straight length in the support, checked"
    )
    return leg


def _slab_boxes(ctx: _Ctx) -> list[tuple[Any, Any, tuple[float, float, float, float]]]:
    from saengine.library.bim import SlabElement

    out = []
    for e in ctx.building.elements:
        if isinstance(e, SlabElement):
            t = ctx.types.get(e.type)
            xs = [p[0] for p in e.boundary]
            ys = [p[1] for p in e.boundary]
            out.append((e, t, (min(xs), min(ys), max(xs), max(ys))))
    return sorted(out, key=lambda x: x[0].id)


def _neighbour(boxes, e, box, axis: int, side: int):
    """The slab sharing the edge of ``box`` on ``axis`` (0: x edges) at ``side`` (0 min, 1 max)."""
    x0, y0, x1, y1 = box
    edge = (x0, x1)[side] if axis == 0 else (y0, y1)[side]
    for other, _, ob in boxes:
        if other.id == e.id or abs(other.elevation - e.elevation) > TOL:
            continue
        oedge = (ob[2], ob[0])[side] if axis == 0 else (ob[3], ob[1])[side]
        if abs(oedge - edge) > TOL:
            continue
        lo, hi = (y0, y1) if axis == 0 else (x0, x1)
        olo, ohi = (ob[1], ob[3]) if axis == 0 else (ob[0], ob[2])
        if min(hi, ohi) - max(lo, olo) > TOL:
            return other, ob
    return None, None


def _detail_slabs(ctx: _Ctx) -> list[dict[str, Any]]:
    from shapely.geometry import Polygon

    boxes = _slab_boxes(ctx)
    elements = []
    step = ctx.step
    done_edges: set[tuple[str, str, int]] = set()
    by_id = {e.id: (e, t, box) for e, t, box in boxes}
    openings: dict[str, list[str]] = {}
    for o in ctx.building.additions.slabOpenings:
        openings.setdefault(o.host, []).append(o.id)
    for e, t, box in boxes:
        element: dict[str, Any] = {
            "id": e.id,
            "kind": "slab",
            "type": e.type,
            "member": e.id,
            "story": _story_at(ctx.building, e.elevation),
            "count": 1,
            "bars": [],
            "transverse": [],
            "laps": [],
            "checks": [],
            "notes": _report_notes(ctx, e.id),
            "at": {"box": [round(v, 1) for v in box], "elevation": e.elevation},
        }
        elements.append(element)
        if t is None or getattr(t, "kind", None) != "slab" or t.reinforcement is None:
            element["notes"].append("no slab reinforcement: not detailed")
            continue
        r = t.reinforcement
        h = float(t.thickness)
        cover = float(r.cover)
        fc, fy, grade = ctx.fc(t.material), ctx.fy(r.material), ctx.grade(r.material)
        poly = Polygon(e.boundary)
        x0, y0, x1, y1 = box
        if poly.area < 0.98 * (x1 - x0) * (y1 - y0):
            element["notes"].append("not rectangular: detailed over its bounding rectangle")
        if e.id in openings:
            element["notes"].append(
                f"openings {', '.join(openings[e.id])}: bars cut at the openings and trimmer "
                "bars are not detailed"
            )
        sup = {
            ("x", 0): _edge_support(ctx, (x0, y0), (x0, y1), e.elevation),
            ("x", 1): _edge_support(ctx, (x1, y0), (x1, y1), e.elevation),
            ("y", 0): _edge_support(ctx, (x0, y0), (x1, y0), e.elevation),
            ("y", 1): _edge_support(ctx, (x0, y1), (x1, y1), e.elevation),
        }
        element["at"]["supports"] = {
            f"{a}{s}": {"width": w, "ref": ref} for (a, s), (w, ref) in sup.items()
        }
        for axis, name in ((0, "X"), (1, "Y")):
            lo, hi = (x0, x1) if axis == 0 else (y0, y1)
            clo, chi = (y0, y1) if axis == 0 else (x0, x1)
            key = "x" if axis == 0 else "y"
            other = "y" if axis == 0 else "x"
            wl, wr = sup[(key, 0)][0], sup[(key, 1)][0]
            ln = (hi - lo) - wl / 2 - wr / 2
            cross = (chi - clo) - sup[(other, 0)][0] / 2 - sup[(other, 1)][0] / 2
            nl, _ = _neighbour(boxes, e, box, axis, 0)
            nr, _ = _neighbour(boxes, e, box, axis, 1)
            layer_dia = {"bottomX": None, "bottomY": None}
            for face in ("bottom", "top"):
                mesh = getattr(r, f"{face}{name}")
                if mesh is None:
                    continue
                db = float(mesh.dia)
                bend = bend_diameter(db).value
                if face == "top" and ctx.options["slabTop"] == "supports":
                    continue
                ends = []
                hooks = []
                for side, w, n in ((0, wl, nl), (1, wr, nr)):
                    edge = lo if side == 0 else hi
                    sign = 1 if side == 0 else -1
                    if n is not None:
                        ext = max(INTO_SUPPORT, w / 2)
                        ends.append(edge + sign * (w / 2 - ext))
                        hooks.append(0.0)
                    else:
                        ends.append(edge - sign * (w / 2 - cover) if w else edge + sign * cover)
                        hooks.append(
                            (
                                _edge_anchorage(
                                    ctx, element, name, db, fy, fc, h, cover, w,
                                    sup[(key, side)][1],
                                )
                                if w
                                else min(standard_hook(db).leg, h - 2 * cover)
                            )
                            if face == "top"
                            else 0.0
                        )  # fmt: skip
                a, c = ends
                lap = ctx.lap(db, fy, fc, cb=_cb(cover, db, float(mesh.spacing)))
                pieces, laps, _ok = split_run(a, c, lap, [(a, c)], ctx.stock, (hooks[0], hooks[1]))
                n_bars = int(cross // float(mesh.spacing)) + 1 if cross > 0 else 0
                letter = ("B" if face == "bottom" else "T") + name
                for k, (p0, p1) in enumerate(pieces):
                    hs = hooks[0] if k == 0 else 0.0
                    he = hooks[1] if k == len(pieces) - 1 else 0.0
                    run = p1 - p0
                    if hs and he:
                        dims, shape, total = (
                            {"A": hs, "B": run, "C": he},
                            "U",
                            u_length(hs, run, he, db, bend),
                        )
                    elif hs or he:
                        dims, shape, total = (
                            {"A": run, "B": hs or he},
                            "L",
                            l_length(run, hs or he, db, bend),
                        )
                    else:
                        dims, shape, total = {"A": run}, "straight", run
                    element["bars"].append(
                        _bar(
                            face,
                            letter,
                            db,
                            shape,
                            n_bars,
                            dims,
                            total,
                            {
                                "direction": name,
                                "face": face,
                                "from": round(p0, 1),
                                "to": round(p1, 1),
                                "band": [round(clo, 1), round(chi, 1)],
                                "spacing": float(mesh.spacing),
                            },
                            bend=bend,
                            grade=grade,
                            lap=lap if laps else None,
                        )
                    )
                layer_dia[f"{face}{name}"] = db
            element["at"][f"ln{name}"] = round(ln, 1)
            # top bars over the supports of this direction
            if ctx.options["slabTop"] != "supports":
                continue
            for side in (0, 1):
                w, ref = sup[(key, side)]
                n, nb = _neighbour(boxes, e, box, axis, side)
                mesh = getattr(r, f"top{name}")
                edge = lo if side == 0 else hi
                if n is not None:
                    pair = tuple(sorted((e.id, n.id)))
                    if (pair[0], pair[1], axis) in done_edges:
                        continue
                    done_edges.add((pair[0], pair[1], axis))
                    nt = by_id[n.id][1]
                    nmesh = getattr(getattr(nt, "reinforcement", None), f"top{name}", None)
                    if mesh is None or (
                        nmesh is not None
                        and nmesh.dia**2 / nmesh.spacing > mesh.dia**2 / mesh.spacing
                    ):
                        mesh = nmesh
                    if mesh is None:
                        element["notes"].append(f"no top {name} bars over the support at {edge:g}")
                        continue
                    nlo, nhi = (nb[0], nb[2]) if axis == 0 else (nb[1], nb[3])
                    nw_far = _edge_support(
                        ctx,
                        *(
                            ((nb[0], nb[1]), (nb[0], nb[3])) if (axis == 0 and side == 0)
                            else ((nb[2], nb[1]), (nb[2], nb[3])) if axis == 0
                            else ((nb[0], nb[1]), (nb[2], nb[1])) if side == 0
                            else ((nb[0], nb[3]), (nb[2], nb[3]))
                        ),
                        e.elevation,
                    )[0]  # fmt: skip
                    ln_n = (nhi - nlo) - w / 2 - nw_far / 2
                    db = float(mesh.dia)
                    ld = ctx.ld(db, fy, fc, cb=_cb(cover, db, float(mesh.spacing)))
                    ext = up(
                        max(slab_top_extent(max(ln, ln_n), ctx.options["slabTopExtent"]).value, ld),
                        step,
                    )
                    p0, p1 = edge - w / 2 - ext, edge + w / 2 + ext
                    olo, ohi = (nb[1], nb[3]) if axis == 0 else (nb[0], nb[2])
                    band = (max(clo, olo), min(chi, ohi))
                    n_bars = int(max(band[1] - band[0], 0) // float(mesh.spacing)) + 1
                    bend = bend_diameter(db).value
                    element["bars"].append(
                        _bar(
                            "top",
                            "T" + name,
                            db,
                            "straight",
                            n_bars,
                            {"A": p1 - p0},
                            p1 - p0,
                            {
                                "direction": name,
                                "face": "top",
                                "from": round(p0, 1),
                                "to": round(p1, 1),
                                "band": [round(band[0], 1), round(band[1], 1)],
                                "spacing": float(mesh.spacing),
                                "support": ref,
                                "slabs": list(pair),
                            },
                            bend=bend,
                            grade=grade,
                            curtailed=True,
                            remarks=f"over the support at {edge:g}, {ext:g} mm from each face "
                            "(0.30 ln, Figure 6.6.20)",
                        )
                    )
                elif w > 0:
                    if mesh is None:
                        continue
                    db = float(mesh.dia)
                    ld = ctx.ld(db, fy, fc, cb=_cb(cover, db, float(mesh.spacing)))
                    ext = up(max(slab_top_extent(ln, ctx.options["slabTopExtent"]).value, ld), step)
                    sign = 1 if side == 0 else -1
                    outer = edge - sign * (w / 2 - cover)
                    inner = edge + sign * (w / 2 + ext)
                    p0, p1 = sorted((outer, inner))
                    leg = _edge_anchorage(ctx, element, name, db, fy, fc, h, cover, w, ref)
                    bend = bend_diameter(db).value
                    n_bars = int(max(cross, 0) // float(mesh.spacing)) + 1
                    element["bars"].append(
                        _bar(
                            "top",
                            "T" + name,
                            db,
                            "L",
                            n_bars,
                            {"A": p1 - p0, "B": leg},
                            l_length(p1 - p0, leg, db, bend),
                            {
                                "direction": name,
                                "face": "top",
                                "from": round(p0, 1),
                                "to": round(p1, 1),
                                "band": [round(clo, 1), round(chi, 1)],
                                "spacing": float(mesh.spacing),
                                "support": ref,
                                "hooks": ["down", None] if side == 0 else [None, "down"],
                            },
                            bend=bend,
                            grade=grade,
                            curtailed=True,
                            remarks=f"at the discontinuous edge {ref}, {ext:g} mm into the panel",
                        )
                    )
        if not any(b["role"] == "top" for b in element["bars"]) and (r.topX or r.topY):
            element["notes"].append("no supported edges: no top bars over supports")
    return elements


# ─────────────────────────────────────────── walls ───────────────────────────────────────────


def _detail_walls(ctx: _Ctx) -> list[dict[str, Any]]:
    from saengine.library.bim import WallElement

    walls = sorted(
        (e for e in ctx.building.elements if isinstance(e, WallElement)), key=lambda e: e.id
    )
    out = []
    step = ctx.step
    openings: dict[str, list[str]] = {}
    for o in ctx.building.additions.wallOpenings:
        openings.setdefault(o.host, []).append(o.id)
    for wall in walls:
        t = ctx.types.get(wall.type)
        element: dict[str, Any] = {
            "id": wall.id,
            "kind": "wall",
            "type": wall.type,
            "member": wall.id,
            "story": _story_at(ctx.building, wall.top),
            "count": 1,
            "bars": [],
            "transverse": [],
            "laps": [],
            "checks": [],
            "notes": _report_notes(ctx, wall.id),
            "at": {
                "start": list(wall.start),
                "end": list(wall.end),
                "bottom": wall.bottom,
                "top": wall.top,
            },
        }
        out.append(element)
        lintels = _detail_lintels(ctx, wall, element)
        if lintels:
            # A wall drawn for its lintels only (masonry): its elevation needs its size.
            element["at"].update(length=math.dist(wall.start, wall.end))
            if getattr(t, "thickness", None):
                element["at"].update(thickness=float(t.thickness))
        if t is None or getattr(t, "kind", None) != "wall" or t.reinforcement is None:
            element["notes"].append(
                "no wall reinforcement: not detailed"
                + (f" (the lintels over {', '.join(lintels)} are)" if lintels else "")
            )
            continue
        r = t.reinforcement
        fc, fy, grade = ctx.fc(t.material), ctx.fy(r.material), ctx.grade(r.material)
        length = math.dist(wall.start, wall.end)
        height = wall.top - wall.bottom
        th = float(t.thickness)
        cover = float(r.cover)
        element["at"].update(length=length, thickness=th)
        if wall.id in openings:
            element["notes"].append(
                f"openings {', '.join(openings[wall.id])}: bars cut at the openings and trimmer "
                "bars are not detailed"
            )
        above = next(
            (
                w
                for w in walls
                if w.id != wall.id
                and abs(w.bottom - wall.top) <= TOL
                and math.dist(w.start, wall.start) <= TOL
                and math.dist(w.end, wall.end) <= TOL
            ),
            None,
        )
        below = next(
            (
                w
                for w in walls
                if w.id != wall.id
                and abs(w.top - wall.bottom) <= TOL
                and math.dist(w.start, wall.start) <= TOL
            ),
            None,
        )
        special = ctx.wall_level == "special" and bool(t.structural)
        factor = 1.25 if special and below is None else 1.0
        if factor != 1.0:
            element["notes"].append(
                f"laps at the base for 1.25 ld ({_page('8.3.6.2(c)', '1100-1101')})"
            )
        found = _foundation_under(ctx, wall) if below is None else None
        boundary = r.boundary
        web_from = boundary.length if boundary else cover
        web = length - 2 * web_from
        layers = int(r.layers)
        vertical_groups: list[tuple[str, str, int, float]] = []
        if r.vertical is not None:
            n = (int(max(web, 0) // float(r.vertical.spacing)) + 1) * layers
            vertical_groups.append(("vertical", "V", n, float(r.vertical.dia)))
        if boundary is not None:
            vertical_groups.append(("end", "E", 2 * int(boundary.count), float(boundary.dia)))
        for role, letter, n, db in vertical_groups:
            bend = bend_diameter(db).value
            spacing = float(r.vertical.spacing) if role == "vertical" and r.vertical else None
            lap = ctx.lap(db, fy, fc, factor=factor, cb=_cb(cover, db, spacing))
            z0 = wall.bottom
            if above is not None:
                z1 = wall.top + lap
                dims, shape, total = {"A": z1 - z0}, "straight", z1 - z0
                hooks = [None, None]
            else:
                z1 = wall.top - 40.0
                hook = standard_hook(db)
                dims = {"A": z1 - z0, "B": hook.leg}
                shape, total = "L", l_length(z1 - z0, hook.leg, db, bend)
                hooks = [None, "intoSlab"]
            bar = _bar(
                role, letter, db, shape, n, dims, total,
                {"from": z0, "to": round(z1, 1), "hooks": hooks},
                bend=bend, grade=grade, lap=lap if above is not None else None,
            )  # fmt: skip
            element["bars"].append(bar)
            if above is not None:
                element["laps"].append(
                    {
                        "bars": [bar],
                        "from": wall.top,
                        "to": wall.top + lap,
                        "length": lap,
                        "class": "B",
                        "clause": _page("8.2.13.1", 1083),
                        "with": above.id,
                    }
                )
            if found is not None:
                hook = standard_hook(db)
                mesh = sum(found["mesh"][:2]) if found["mesh"] else 0.0
                s0 = found["bottom"] + found["cover"] + mesh
                s1 = wall.bottom + lap
                dims = {"A": s1 - s0, "B": hook.leg}
                dowel = _bar(
                    "starter", "D", db, "L", n, dims, l_length(dims["A"], dims["B"], db, bend),
                    {"from": round(s0, 1), "to": round(s1, 1), "foundation": found["id"],
                     "hooks": ["toCentre", None]},
                    bend=bend, grade=grade, lap=lap,
                    remarks=f"starter bars from {found['id']}",
                )  # fmt: skip
                element["bars"].append(dowel)
                element["laps"].append(
                    {
                        "bars": [dowel, bar],
                        "from": wall.bottom,
                        "to": wall.bottom + lap,
                        "length": lap,
                        "class": "B",
                        "clause": _page("8.2.13.1", 1083),
                        "with": found["id"],
                    }
                )
        if r.horizontal is not None:
            db = float(r.horizontal.dia)
            s = float(r.horizontal.spacing)
            bend = bend_diameter(db).value
            hook = standard_hook(db)
            leg = min(hook.leg, th - 2 * cover)
            n = (int(max(height - s, 0) // s) + 1) * layers
            run = length - 2 * cover
            lap = ctx.lap(db, fy, fc, cb=_cb(cover, db, s))
            pieces, laps, _ok = split_run(0.0, run, lap, [(0.0, run)], ctx.stock, (leg, leg))
            for k, (p0, p1) in enumerate(pieces):
                hs = leg if k == 0 else 0.0
                he = leg if k == len(pieces) - 1 else 0.0
                span = p1 - p0
                if hs and he:
                    dims, shape, total = (
                        {"A": hs, "B": span, "C": he},
                        "U",
                        u_length(hs, span, he, db, bend),
                    )
                elif hs or he:
                    dims, shape, total = (
                        {"A": span, "B": hs or he},
                        "L",
                        l_length(span, hs or he, db, bend),
                    )
                else:
                    dims, shape, total = {"A": span}, "straight", span
                element["bars"].append(
                    _bar(
                        "horizontal", "H", db, shape, n, dims, total,
                        {"from": round(cover + p0, 1), "to": round(cover + p1, 1),
                         "spacing": s, "layers": layers},
                        bend=bend, grade=grade, lap=lap if laps else None,
                        remarks="90° hooks at the wall ends (8.3.6.6(d)(v), (e)(ii), p 1104)",
                    )
                )  # fmt: skip
            if leg < hook.leg:
                element["notes"].append(
                    f"horizontal Ø{db:g} hooks shortened to the thickness ({leg:.0f} mm)"
                )
        if boundary is not None and boundary.hoop is not None:
            hp = boundary.hoop
            hdia = float(hp.dia)
            hook = seismic_hook(hdia)
            a, b = boundary.length - cover, th - 2 * cover
            rows = space(wall.bottom, wall.top, float(hp.spacing), [], float(hp.spacing) / 2)
            n = sum(row["count"] for row in rows)
            hoop = _bar(
                "hoop", "K", hdia, "stirrup", 2 * n, {"A": a, "B": b},
                stirrup_length(a, b, hdia, hook), {"section": [a, b], "ends": 2},
                bend=hook.bend_dia, grade=grade, zone="boundary",
            )  # fmt: skip
            for row in rows:
                row["_bar"] = hoop
            element["transverse"] += rows
            element["bars"].append(hoop)
            extra = max(int(hp.legsAcross) - 2, 0)
            if extra:
                h135, h90 = seismic_hook(hdia), standard_hook(hdia, 90, transverse=True)
                element["bars"].append(
                    _bar(
                        "crosstie", "X", hdia, "special", 2 * n * extra, {"A": b},
                        crosstie_length(b, hdia, h135, h90), {"legs": extra},
                        bend=h135.bend_dia, grade=grade, zone="boundary",
                    )
                )  # fmt: skip
        _ = step
    return out


#: Lintels: the first stirrup from each end of the lintel [mm] (practice, as FIRST_STIRRUP).
LINTEL_FIRST_STIRRUP = 50.0


def _high_wind(settings: Any) -> bool:
    """Whether the site is a high-wind region for the lintel bars (7.9.6.3): the basic wind
    speed over 200 km/h, decided as design/check.py decides it for the design report."""
    if settings is None:
        return False
    from saengine.library.settings import derived

    try:
        wind = float(derived(settings).get("windSpeed") or 0.0)
    except (ValueError, KeyError, AttributeError, TypeError):
        wind = 0.0
    return wind * 3.6 > 200.0


def _lintels_of(ctx: _Ctx) -> list[dict[str, Any]]:
    """The lintels designed over the openings of masonry and partition walls
    (:func:`saengine.design.lintels.lintels_of`, the design report's ``kind: "lintel"``
    elements); designed here, as the design report does, when no report was given."""
    found = [e for e in ctx.report.values() if e.get("kind") == "lintel"]
    if found or ctx.report:
        return found
    if ctx.lintels is None:
        from saengine.design import lintels as lintel_design

        try:
            types = dict(ctx.types)
            mats = {m.id: m for m in ctx.materials.materials} if ctx.materials else {}
            result = lintel_design.lintels_of(
                ctx.building,
                types,
                mats,
                ctx.settings,
                concrete=ctx.materials.default_concrete() if ctx.materials else None,
                steel=ctx.materials.default_rebar() if ctx.materials else None,
                high_wind=_high_wind(ctx.settings),
            )
            ctx.lintels = list(result["elements"])
        except (ValueError, AttributeError, KeyError) as error:
            ctx.notes.append(f"lintels could not be designed for the drawings: {error}")
            ctx.lintels = []
    return ctx.lintels


def _detail_lintels(ctx: _Ctx, wall: Any, element: dict[str, Any]) -> list[str]:
    """The bars of the lintels over the openings of ``wall`` (their design by
    :mod:`saengine.design.lintels`) added to the wall's element: bottom bars (``LB``), top
    hangers (``LT``) and closed stirrups (``LS``), each with ``at.opening``; returns the
    openings' ids.

    The lintel runs the opening's clear width plus its bearing at each end (the design's span
    less the clear width is one bearing; Sec 7.4.3.2, p 1015), or the opening plus 600 mm each
    side where the design asks for the bars to run that far (7.9.6.3, p 1045, high wind
    regions); the bars run its length less the cover at each end, straight; ld of the bottom
    bars is checked from mid-span (the section of the largest moment) to the bar's end
    (8.2.3); stirrups with 135° hooks (8.1.2.1(c)) from 50 mm off each end at the design's
    spacing."""
    from saengine.design.lintels import COVER, WIND_BAR_EXTENSION

    openings = {o.id: o for o in ctx.building.additions.wallOpenings if o.host == wall.id}
    done = []
    for found in _lintels_of(ctx):
        o = openings.get(str(found.get("id")))
        if o is None:
            continue
        bars = found.get("bars") or {}
        clear = float(found.get("clear") or o.width)
        bearing = max(float(found.get("span") or clear) - clear, 0.0)
        high_wind = any(
            str(c.get("name", "")).startswith("Lintel span") and not c.get("flag", True)
            for c in found.get("checks", [])
        )
        reach = max(bearing, WIND_BAR_EXTENSION) if high_wind else bearing
        b, h = float(found.get("b") or 0), float(found.get("h") or 0)
        length = clear + 2 * reach
        x0 = float(o.offset) - reach
        head = float(wall.bottom) + float(o.sill) + float(o.height)
        steel = str(found.get("steel") or "")
        grade = ctx.grade(steel) if steel else None
        fy = ctx.fy(steel) if steel else 420.0
        fc = ctx.fc(str(found.get("concrete") or ""))
        cover = COVER
        at = {"opening": o.id, "from": round(x0, 1), "to": round(x0 + length, 1),
              "bottom": round(head, 1), "depth": h, "width": b}  # fmt: skip
        run = length - 2 * cover
        remarks = f"lintel over {o.id}"
        for key, role, letter in (("bottom", "lintel bottom", "LB"), ("top", "lintel top", "LT")):
            if not bars.get(key):
                continue
            count, db = int(bars[key][0]), float(bars[key][1])
            element["bars"].append(
                _bar(
                    role, letter, db, "straight", count, {"A": run}, run,
                    {**at, "face": key}, bend=bend_diameter(db).value, grade=grade,
                    remarks=remarks,
                )
            )  # fmt: skip
            if key == "bottom":
                ld = ctx.ld(db, fy, fc)
                element["checks"].append(
                    _check(
                        f"{o.id}: bottom Ø{db:g} developed from mid-span",
                        ld,
                        run / 2,
                        _page("8.2.3", "1076-1078"),
                    )
                )
        if bars.get("stirrups"):
            legs, ds, spacing = (
                int(bars["stirrups"][0]),
                float(bars["stirrups"][1]),
                float(bars["stirrups"][2]),
            )
            hook = standard_hook(ds, 135, transverse=True)
            a, c = b - 2 * cover, h - 2 * cover
            first = LINTEL_FIRST_STIRRUP
            count = int(max(length - 2 * first, 0.0) // spacing) + 1
            stirrup = _bar(
                "lintel stirrup", "LS", ds, "stirrup", count, {"A": a, "B": c},
                stirrup_length(a, c, ds, hook), {**at, "spacing": spacing, "legs": legs},
                bend=hook.bend_dia, grade=grade, remarks=remarks,
            )  # fmt: skip
            element["bars"].append(stirrup)
            element["transverse"].append(
                {"from": round(x0 + first, 1), "to": round(x0 + length - first, 1),
                 "spacing": spacing, "count": count, "zone": "lintel", "_bar": stirrup}
            )  # fmt: skip
            if legs > 2:
                element["notes"].append(
                    f"{o.id}: {legs}-leg stirrups: the inner legs are not scheduled"
                )
        element.setdefault("lintels", []).append(
            {"opening": o.id, "from": at["from"], "to": at["to"], "bottom": at["bottom"],
             "depth": h, "width": b, "label": found.get("label", ""), "ok": found.get("ok")}
        )  # fmt: skip
        if found.get("ok") is False:
            element["notes"].append(
                f"the lintel over {o.id} fails its design check: detailed as designed"
            )
        done.append(o.id)
    return done


# ─────────────────────────────────────────── stairs ───────────────────────────────────────────


def _detail_stairs(ctx: _Ctx) -> list[dict[str, Any]]:
    levels = {s.id: s.elevation for s in ctx.building.stories}
    out = []
    step = ctx.step
    for stair in sorted(ctx.building.additions.stairs, key=lambda s: s.id):
        t = ctx.types.get(stair.type)
        element: dict[str, Any] = {
            "id": stair.id,
            "kind": "staircase",
            "type": stair.type,
            "member": stair.id,
            "story": stair.top,
            "count": 1,
            "bars": [],
            "transverse": [],
            "laps": [],
            "checks": [],
            "notes": _report_notes(ctx, stair.id),
        }
        out.append(element)
        if t is None or getattr(t, "kind", None) != "staircase" or t.reinforcement is None:
            element["notes"].append("no stair reinforcement: not detailed")
            continue
        if stair.base not in levels or stair.top not in levels:
            element["notes"].append("its stories are not in the building model")
            continue
        rise = levels[stair.top] - levels[stair.base]
        n = max(1, round(rise / t.riser))
        riser, going = rise / n, float(t.tread)
        width = float(t.flightWidth)
        r = t.reinforcement
        cover = float(r.cover)
        fc, fy, grade = ctx.fc(t.material), ctx.fy(r.material), ctx.grade(r.material)
        dog = t.arrangement == "dogLegged" and n >= 2
        flights = [(n + 1) // 2, n // 2] if dog else [n]
        angle = math.degrees(math.atan2(riser, going))
        element["at"] = {
            "x": stair.x,
            "y": stair.y,
            "direction": stair.direction,
            "flights": flights,
            "riser": round(riser, 1),
            "going": going,
            "width": width,
            "waist": float(t.waistThickness),
            "angle": round(angle, 2),
        }
        for k, risers in enumerate(flights, start=1):
            slope = math.hypot(risers * going, risers * riser)
            main = r.main
            db = float(main.dia)
            bend = bend_diameter(db).value
            ext = up(ctx.ld(db, fy, fc), step)
            count = int((width - 2 * cover) // float(main.spacing)) + 1
            element["bars"].append(
                _bar(
                    "main", "M", db, "crank", count, {"A": ext, "B": slope, "C": ext},
                    2 * ext + slope, {"flight": k, "face": "bottom", "angle": round(angle, 2)},
                    bend=bend, grade=grade,
                    remarks=f"ld = {ext:g} mm past the kink into the landing or support",
                )
            )  # fmt: skip
            dist = r.distribution
            dd = float(dist.dia)
            element["bars"].append(
                _bar(
                    "distribution", "N", dd, "straight",
                    int(slope // float(dist.spacing)) + 1, {"A": width - 2 * cover},
                    width - 2 * cover, {"flight": k},
                    bend=bend_diameter(dd).value, grade=grade,
                )
            )  # fmt: skip
            if r.top is not None:
                ends = (t.bottomEnd == "continuous") + (t.topEnd == "continuous")
                if ends:
                    tdb = float(r.top.dia)
                    run = up(slope / 4 + ctx.ld(tdb, fy, fc), step)
                    element["bars"].append(
                        _bar(
                            "top", "T", tdb, "straight",
                            ends * (int((width - 2 * cover) // float(r.top.spacing)) + 1),
                            {"A": run}, run, {"flight": k, "face": "top"},
                            bend=bend_diameter(tdb).value, grade=grade, curtailed=True,
                            remarks="a quarter of the flight from each continuous end, plus ld",
                        )
                    )  # fmt: skip
        if dog:
            depth = float(t.landingLength or width)
            span = 2 * width + float(t.wellWidth or 0.0)
            land = r.landing or r.main
            ldb = float(land.dia)
            run = span + float(t.supportWidth) - 2 * cover
            element["bars"].append(
                _bar(
                    "landing", "L", ldb, "straight",
                    int((depth - 2 * cover) // float(land.spacing)) + 1, {"A": run}, run,
                    {"landing": True, "span": span},
                    bend=bend_diameter(ldb).value, grade=grade,
                    remarks="landing main bars across the flights, into the supports",
                )
            )  # fmt: skip
            dist = r.distribution
            element["bars"].append(
                _bar(
                    "landing distribution", "LN", float(dist.dia), "straight",
                    int((span - 2 * cover) // float(dist.spacing)) + 1,
                    {"A": depth - 2 * cover}, depth - 2 * cover, {"landing": True},
                    bend=bend_diameter(float(dist.dia)).value, grade=grade,
                )
            )  # fmt: skip
    return out


# ───────────────────────────────────────── foundations ─────────────────────────────────────────


def _natural(text: str) -> tuple[Any, ...]:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text))


def _detail_foundations(ctx: _Ctx) -> list[dict[str, Any]]:
    from saengine.library.bim import ColumnElement, FootingElement, foundation_solids

    # (id, kind, type key, form, reinforcement, length, width, thickness, rotation, columns,
    #  material, centre)
    rows: list[tuple[Any, ...]] = []
    columns = {e.id: e for e in ctx.building.elements if isinstance(e, ColumnElement)}
    notes: list[str] = []
    if ctx.substructure is not None:
        ground = float(ctx.settings.foundation.groundLevel) if ctx.settings is not None else 0.0
        solids = foundation_solids(ctx.substructure, ctx.building, ground)
        notes += [f"9 Substructure: {n}" for n in solids.notes]
        by_id = {f.id: f for f in ctx.substructure.foundations}
        # 9 Substructure has no foundation types: each foundation is its own definition, and
        # foundations with the same definition (form, size, reinforcement, concrete) are one
        # type, named after the first of them (natural order), for the marks
        definitions: dict[str, str] = {}
        for s in sorted(solids.foundations, key=lambda x: _natural(x.id)):
            r = s.reinforcement
            key = json.dumps(
                [s.type, round(s.runs[0]), round(s.runs[1]), round(s.thickness), s.material,
                 r.model_dump(mode="json") if hasattr(r, "model_dump") else repr(r)],
                sort_keys=True, default=str,
            )  # fmt: skip
            definitions.setdefault(key, s.id)
            f = by_id[s.id]
            kind = "pileCap" if s.type == "pileCap" else "footing"
            if s.type in ("strip", "raft"):
                notes.append(f"{s.id}: {s.type} foundations are detailed over their runs only")
            rows.append(
                (s.id, kind, definitions[key], s.type, s.reinforcement, s.runs[0], s.runs[1],
                 s.thickness, s.rotation, list(f.columns), s.material or "", s.center)
            )  # fmt: skip
        if solids.piles:
            notes.append(
                "piles are not detailed (their bars: see the pile types of 9 Substructure)"
            )
        if solids.ties:
            notes.append("tie beams of 9 Substructure are not detailed")
    else:
        for e in ctx.building.elements:
            if isinstance(e, FootingElement):
                t = ctx.types.get(e.type)
                if t is None:
                    continue
                on = [c.id for c in columns.values() if math.dist(c.position, e.position) <= TOL]
                rows.append(
                    (e.id, t.kind, e.type, getattr(t, "footingType", None) or "pileCap",
                     t.reinforcement, float(t.length), float(t.width), float(t.thickness),
                     e.rotation, on, t.material, (float(e.position[0]), float(e.position[1])))
                )  # fmt: skip
    out = []
    step = ctx.step
    rows.sort(key=lambda row: _natural(row[0]))
    for (fid, kind, ftype, form, r, length, width, thick, rotation, cols, material,
         centre) in rows:  # fmt: skip
        element: dict[str, Any] = {
            "id": fid,
            "kind": kind,
            "type": ftype,
            "form": form,
            "member": fid,
            "story": None,
            "count": 1,
            "bars": [],
            "transverse": [],
            "laps": [],
            "checks": [],
            "notes": [],
            "at": {
                "length": length,
                "width": width,
                "thickness": thick,
                "rotation": rotation,
                "columns": cols,
                "centre": list(centre) if centre is not None else None,
            },
        }
        out.append(element)
        if r is None:
            element["notes"].append("no reinforcement: not detailed")
            continue
        fc, fy, grade = ctx.fc(material), ctx.fy(r.material), ctx.grade(r.material)
        cover = float(r.cover)
        # the shortest length from a column face to the foundation's edge, along each local
        # axis, over all its columns at their real positions (the critical section of 8.2.7.2
        # is the column face)
        edge_from_face: dict[int, float | None] = {0: None, 1: None}
        half = {0: length / 2, 1: width / 2}
        rot = math.radians(rotation or 0.0)
        ux, uy = (math.cos(rot), math.sin(rot)), (-math.sin(rot), math.cos(rot))
        for cid in cols:
            c = columns.get(cid)
            t = ctx.types.get(c.type) if c else None
            prof = getattr(t, "profile", None)
            if prof is None:
                continue
            if getattr(prof, "shape", "") == "circle":
                c_along = {0: 2 * prof.radius, 1: 2 * prof.radius}
            else:
                rel = math.radians((c.rotation or 0.0) - (rotation or 0.0))
                ca, sa = abs(math.cos(rel)), abs(math.sin(rel))
                c_along = {
                    0: prof.xDim * ca + prof.yDim * sa,
                    1: prof.xDim * sa + prof.yDim * ca,
                }
            dx = float(c.position[0]) - (centre[0] if centre is not None else c.position[0])
            dy = float(c.position[1]) - (centre[1] if centre is not None else c.position[1])
            local = {0: dx * ux[0] + dy * ux[1], 1: dx * uy[0] + dy * uy[1]}
            for axis in (0, 1):
                near = half[axis] - abs(local[axis]) - c_along[axis] / 2
                prev = edge_from_face[axis]
                edge_from_face[axis] = near if prev is None else min(prev, near)
        if centre is None and cols:
            element["notes"].append(
                "the foundation's centre is not known: the columns are taken at its centre"
            )
        for face in ("bottom", "top"):
            for axis, name in ((0, "X"), (1, "Y")):
                mesh = getattr(r, f"{face}{name}", None)
                if mesh is None:
                    continue
                db = float(mesh.dia)
                bend = bend_diameter(db).value
                run = (length if axis == 0 else width) - 2 * cover
                across = (width if axis == 0 else length) - 2 * cover
                n = int(across // float(mesh.spacing)) + 1
                near = edge_from_face[axis]
                avail = (near if near is not None else (length if axis == 0 else width) / 2) - cover
                top = face == "top" and thick - cover > 300
                cb = _cb(cover, db, float(mesh.spacing))
                ld = ctx.ld(db, fy, fc, top=top, cb=cb)
                letter = ("B" if face == "bottom" else "T") + name
                if form in ("strip", "raft") or avail >= ld:
                    if form not in ("strip", "raft"):
                        element["checks"].append(
                            _check(
                                f"{face} {name} bars Ø{db:g}: straight development from the "
                                "column face", ld, avail, _page("8.2.3, 8.2.7.2", "1077, 1080"),
                            )
                        )  # fmt: skip
                    lap = ctx.lap(db, fy, fc, top=top, cb=cb)
                    pieces, laps, _ok = split_run(0.0, run, lap, [(0.0, run)], ctx.stock)
                    for p0, p1 in pieces:
                        element["bars"].append(
                            _bar(
                                face, letter, db, "straight", n, {"A": p1 - p0}, p1 - p0,
                                {"direction": name, "face": face, "from": round(cover + p0, 1),
                                 "to": round(cover + p1, 1), "spacing": float(mesh.spacing)},
                                bend=bend, grade=grade, lap=lap if laps else None,
                            )
                        )  # fmt: skip
                else:
                    hook = standard_hook(db)
                    leg = min(hook.leg, thick - 2 * cover)
                    need = hook_development(db, fy, fc)
                    element["checks"].append(
                        _check(
                            f"{face} {name} bars Ø{db:g}: hooked development from the column "
                            "face (too short for straight ld "
                            f"{ld:.0f} mm)", need.value, avail, need.clause,
                        )
                    )  # fmt: skip
                    dims = {"A": leg, "B": run, "C": leg}
                    element["bars"].append(
                        _bar(
                            face, letter, db, "U", n, dims, u_length(leg, run, leg, db, bend),
                            {"direction": name, "face": face, "from": cover,
                             "to": round(cover + run, 1), "spacing": float(mesh.spacing),
                             "hooks": ["up", "up"] if face == "bottom" else ["down", "down"]},
                            bend=bend, grade=grade,
                            remarks="90° hooks at both ends (straight length short of ld)",
                        )
                    )  # fmt: skip
        if cols:
            element["notes"].append(f"column starter bars: see {', '.join(cols)} (role 'starter')")
        _ = step
    ctx.notes += notes
    return out


# ─────────────────────────────────────────── marks ───────────────────────────────────────────


_PREFIX = {
    "beam": "B",
    "column": "C",
    "slab": "S",
    "wall": "W",
    "staircase": "ST",
    "footing": "F",
    "pileCap": "PC",
}
_ROLE_ORDER = ["T", "B", "F", "S", "X", "V", "D", "H", "P", "BX", "BY", "TX", "TY", "E", "K",
               "M", "N", "L", "LN", "LB", "LT", "LS"]  # fmt: skip


def _signature(element: dict[str, Any], bar: dict[str, Any]) -> str:
    dims = {k: round(v) for k, v in sorted(bar["dims"].items())}
    return json.dumps(
        [element["type"], bar["_letter"], bar["dia"], bar["shape"], dims, round(bar["length"])],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def assign_marks(
    elements: list[dict[str, Any]], previous: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Gives every bar of ``elements`` its mark (in place) and returns the marks table. Bars
    with the same signature (type, role, diameter, shape, rounded dimensions and length) share a
    mark across members. ``previous``: an earlier ``marks`` table; a signature found there keeps
    its mark and a type keeps its code, new ones take the next free numbers."""
    previous = previous or {}
    by_signature = {
        str(v.get("signature")): k for k, v in previous.items() if v.get("signature") is not None
    }
    type_code: dict[tuple[str, str], str] = {}
    for mark, v in previous.items():
        code = mark.split("-", 1)[0]
        if v.get("type") and v.get("kind"):
            type_code.setdefault((str(v["kind"]), str(v["type"])), code)
    # type codes: previous ones first, then the next free number per kind letter, by type id
    used_codes = set(type_code.values())
    kinds_types = sorted({(e["kind"], e["type"]) for e in elements if e["bars"]})
    # foundations of 9 Substructure have no types: a definition is named after its first
    # foundation (F1, PC2), and that label is its code when it is free
    labels = {(e["kind"], e["id"]) for e in elements}
    for kind, type_id in kinds_types:
        if (
            kind in ("footing", "pileCap")
            and (kind, type_id) not in type_code
            and (kind, type_id) in labels
            and re.fullmatch(r"[A-Za-z]{1,3}\d{1,4}", str(type_id))
            and type_id not in used_codes
        ):
            type_code[(kind, type_id)] = str(type_id)
            used_codes.add(str(type_id))
    for kind, type_id in kinds_types:
        if (kind, type_id) in type_code:
            continue
        letter = _PREFIX.get(kind, "M")
        k = 1
        while f"{letter}{k}" in used_codes:
            k += 1
        type_code[(kind, type_id)] = f"{letter}{k}"
        used_codes.add(f"{letter}{k}")
    used_marks = set(previous)
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for element in elements:
        for bar in element["bars"]:
            groups.setdefault(_signature(element, bar), []).append((element, bar))
    marks: dict[str, dict[str, Any]] = {}

    def order(sig: str) -> tuple[Any, ...]:
        element, bar = groups[sig][0]
        letter = bar["_letter"]
        index = _ROLE_ORDER.index(letter) if letter in _ROLE_ORDER else len(_ROLE_ORDER)
        return (
            type_code[(element["kind"], element["type"])],
            index,
            -bar["dia"],
            -bar["length"],
            sig,
        )

    for sig in sorted(groups, key=order):
        element, bar = groups[sig][0]
        mark = by_signature.get(sig)
        if mark is None or mark in marks:
            code = type_code[(element["kind"], element["type"])]
            k = 1
            while f"{code}-{bar['_letter']}{k}" in used_marks:
                k += 1
            mark = f"{code}-{bar['_letter']}{k}"
        used_marks.add(mark)
        count = 0
        ids = []
        for el, b in groups[sig]:
            b["mark"] = mark
            count += b["count"] * int(el.get("count", 1))
            if el["id"] not in ids:
                ids.append(el["id"])
        marks[mark] = {
            "mark": mark,
            "type": element["type"],
            "kind": element["kind"],
            "role": bar["role"],
            "dia": bar["dia"],
            "shape": bar["shape"],
            "dims": bar["dims"],
            "length": bar["length"],
            "count": count,
            "elements": ids,
            "signature": sig,
        }
    return dict(sorted(marks.items()))


def _finish(elements: list[dict[str, Any]]) -> None:
    for element in elements:
        for row in element["transverse"]:
            bar = row.pop("_bar", None)
            row["mark"] = bar["mark"] if bar is not None else None
        for lap in element["laps"]:
            bars = lap.pop("bars", [])
            lap["marks"] = sorted({b["mark"] for b in bars if b.get("mark")})
        for bar in element["bars"]:
            bar.pop("_letter", None)


# ───────────────────────────────────────────── entry ─────────────────────────────────────────────


def _frames(
    settings: Any, materials: Any, objects: Any, building: Any, root: Any
) -> tuple[dict[str, tuple[str, bool]], str | None, list[str]]:
    """(frame level and lateral role per beam and column id, the walls' detailing level, notes)
    from the seismic detailing scope (:func:`saengine.design.seismic_detailing.scope_of`)."""
    if settings is None:
        return {}, None, ["no project settings: ordinary detailing (no seismic provisions) assumed"]
    from saengine.design.seismic_detailing import _frame_for, scope_of

    try:
        scope, _ = scope_of(settings, materials, objects, building, root)
    except Exception as error:  # noqa: BLE001 - the scope is advisory here
        return {}, None, [f"the seismic detailing scope could not be found: {error}"]
    frames = {}
    for mid, row in (scope.get("members") or {}).items():
        found = _frame_for(row, scope)
        if found is not None:
            frames[mid] = found
    level = scope.get("detailingLevel")
    return frames, level if level in ("special", "intermediate", "ordinary") else None, []


def _read(root: Path, relative: str) -> str | None:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


FILES = {
    "settings": "02 Project Settings/project-settings.json",
    "materials": "03 Materials/materials.json",
    "objects": "04 Objects/objects.json",
    "bim": "06 BIM/bim.json",
    "substructure": "09 Substructure/substructure.json",
}


def detailing_model(
    project_root: str | Path | None = None,
    *,
    texts: dict[str, str | None] | None = None,
    design_report: dict[str, Any] | None = None,
    required: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The detailing model of a project (see the module notes). ``project_root``: the project
    folder, its files read (``FILES``); or ``texts``: the files' texts by key ("bim", "objects",
    "materials" required; "settings", "substructure" optional). ``design_report``: the output of
    :func:`saengine.design.check.design_report` (frame types, zones lo, failing elements);
    ``required``: of :func:`saengine.design.required.design_required` (the top steel the beams
    need at mid-span); ``options``: see ``DEFAULT_OPTIONS``; ``previous``: the ``marks`` of an
    earlier model, to keep the marks. Pure: reads files only when ``project_root`` is given.
    Raises ``ValueError`` when a required file is missing or invalid."""
    from saengine.design import ductile_joints as dj
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings

    root = Path(project_root) if project_root is not None else None
    data = dict(texts or {})
    if root is not None:
        for key, relative in FILES.items():
            data.setdefault(key, _read(root, relative))
    for key in ("bim", "objects", "materials"):
        if not data.get(key):
            raise ValueError(f"{FILES[key]} is missing")
    building = BuildingModel.model_validate_json(data["bim"])
    objects = ObjectLibrary.model_validate_json(data["objects"])
    materials = MaterialLibrary.model_validate_json(data["materials"])
    settings = (
        ProjectSettings.model_validate_json(data["settings"]) if data.get("settings") else None
    )
    substructure = None
    if data.get("substructure"):
        from saengine.substructure.handover import authoritative_substructure

        substructure = authoritative_substructure(data["substructure"], building)
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    if opts["method"] not in ("simplified", "general"):
        raise ValueError(f"method {opts['method']!r}: 'simplified' or 'general'")
    report = {str(e.get("id")): e for e in (design_report or {}).get("elements", [])}
    req: dict[str, dict[str, Any]] = {}
    for row in (required or {}).get("elements", []):
        req.setdefault(str(row.get("element")), {"rows": []})["rows"].append(row)
    frames, wall_level, notes = _frames(settings, materials, objects, building, root)
    if design_report is not None and (design_report.get("seismic") or {}).get("detailingLevel"):
        wall_level = design_report["seismic"]["detailingLevel"]
    types = {o.id: o for o in objects.objects}
    ctx = _Ctx(
        building, types, materials, settings, substructure, report, req, frames, wall_level, opts
    )
    ctx.notes += notes
    try:
        ctx.joints = dj.frame_joints(building, types)
    except (ValueError, AttributeError) as error:
        ctx.notes.append(f"the beam-column joints could not be found: {error}")
    elements: list[dict[str, Any]] = []
    stacks = _stacks(ctx)
    for stack in stacks:
        for k in range(len(stack)):
            elements.append(_detail_column(ctx, stack, k))
    for line in _beam_lines(ctx):
        elements.append(_detail_beam_line(ctx, line))
    elements += _detail_slabs(ctx)
    elements += _detail_walls(ctx)
    elements += _detail_stairs(ctx)
    elements += _detail_foundations(ctx)
    if building.additions.members:
        ctx.notes.append("inclined members are not detailed")
    order = {"footing": 0, "pileCap": 0, "column": 1, "wall": 2, "beam": 3, "slab": 4,
             "staircase": 5}  # fmt: skip
    elements.sort(key=lambda e: (order.get(e["kind"], 9), e["id"]))
    marks = assign_marks(elements, previous)
    _finish(elements)
    ctx.notes.append(
        f"Detailing to BNBC 2020 Part 6 Chapter 8; ld by {ctx.method_text}"
        + (
            " (first row: spacing and cover at least db, code stirrups)"
            if opts.get("method") != "general"
            else " (cb from the cover and bar spacing of each layer)"
        )
        + "; lengths rounded up to "
        f"{opts['round']:g} mm; bars longer than {opts['stockLength']:g} mm lapped (class B)."
    )
    return {
        "schema": SCHEMA_ID,
        "code": CODE,
        "options": opts,
        "elements": elements,
        "marks": marks,
        "notes": ctx.notes,
    }

"""Timber beams, columns and braces: permissible stress design with the code pack's ``timber``
table (with the bnbc2020 pack: BNBC 2020 Part 6 Chapter 11).

The member's forces are the allowable stress (service level) combinations of the code pack
(``combinations.allowable``) formed from the analysis's load cases. Per member, at every station
of every combination:

- permissible stresses of the species (when the pack's table gives them) or of the strength
  group, at the location of use, times the grade factor, the low-durability factor outside, the
  slope-of-grain factor K1 of ungraded timber, and the load duration factor K2 of the
  combination (the shortest duration load in it governs; K2 on E too for columns);
- bending f = M/Z with the form factor (K3 deep rectangles, K4 box and I beams, K5 circles,
  K6 squares on the diagonal);
- shear: beams the horizontal shear VQ/(Ib) (3V/(2bD) of rectangles), the loads within one
  depth of a supported end neglected (the shear at D from it), and the notched-beam formulas at
  notched supports; other members the shear along the grain;
- tension, and compression of solid (short, intermediate with K8, long), box (U, q, K9) and
  spaced (restraint factor, K10) columns, with their slenderness limits;
- combined axial and bending, linear;
- flexural members: least width, lateral restraint of deep or long beams, bearing at the
  supports, notch limits and the deflection (long-term: the dead load doubled).

S (the column length) is the member's length between its analysis ends: the formulas are for
pinned ends. Joints: :mod:`.connections`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.ductile_members import _row

LOCATIONS = ("inside", "outside", "wet")
#: Live load durations a material may give (a key of the pack's ``duration`` group).
LIVE_DURATIONS = ("continuous", "twoMonths", "sevenDays", "impact")


class TimberDesignError(ValueError):
    """A timber member that cannot be checked (a shape or value the table does not cover)."""


def _table() -> Any:
    return code_context.pack_table("timber")


def code_name() -> str:
    """The display name of the code pack in force."""
    pack = code_context.current()
    return pack.edition or pack.name or pack.id


def clause(key: str) -> str:
    """The pack's clause of check ``key`` after the pack's name ("<code> Part 6 Sec ...")."""
    text = (getattr(_table(), "clauses", None) or {}).get(key, "")
    return f"{code_name()} {text}".strip()


def method() -> list[str]:
    """The design report's method paragraph of timber members, with the pack's clauses."""
    text = (
        "Timber members: permissible stress design to "
        f"{clause('chapter')}, under the allowable stress combinations formed from the "
        "analysis's load cases. Stresses of the species or strength group at the location of "
        f"use, times the grade and durability factors ({clause('grade')}), K1 for ungraded "
        f"timber ({clause('slope')}) and the load duration factor K2 of each combination "
        f"({clause('duration')}); bending with the form factors ({clause('bending')}); "
        f"horizontal shear of beams at one depth from the supports ({clause('shearSupport')}), "
        f"notched beams ({clause('notch')}); solid, box and spaced columns "
        f"({clause('column')}; {clause('boxColumn')}; {clause('spacedColumn')}); combined "
        f"stresses ({clause('combinedCompression')}); bearing ({clause('bearing')}) and "
        f"deflection with twice the dead load ({clause('deflection')}). S is the member length "
        "(pinned ends). Joints: nails, bolts, split rings and disc-dowels as the member type "
        "gives them."
    )
    return [text]


def is_timber(material: Any) -> bool:
    """Whether members of ``material`` are designed as timber."""
    category = getattr(getattr(material, "category", None), "value", None)
    return category == "timber" and getattr(material, "timber", None) is not None


# ─────────────────────────────────────── stresses ───────────────────────────────────────


def find_species(name: str | None) -> tuple[str, Any] | None:
    """``(id, species)`` of the pack's species table by id, trade or botanical name (case
    insensitive); None for no name. Raises :class:`TimberDesignError` for an unknown one or a
    trade name shared by several species."""
    if not name:
        return None
    species = getattr(_table(), "species", None) or {}
    key = name.strip().lower()
    if key in species:
        return key, species[key]
    found = [
        (k, s) for k, s in species.items() if key in ((s.name or "").lower(), s.botanical.lower())
    ]
    if len(found) == 1:
        return found[0]
    if found:
        names = ", ".join(s.botanical for _, s in found)
        raise TimberDesignError(f"species '{name}' is ambiguous ({names}): give the botanical name")
    raise TimberDesignError(f"species '{name}' is not in the code pack's table")


def slope_factor(slope: float, column: bool) -> float:
    """K1 for a slope of grain 1 in ``slope`` (posts and columns, or beams, joists and ties),
    interpolated; 1 flatter than the table. Steeper than the table: an error."""
    rows = sorted(_table().slopeOfGrain, key=lambda r: float(r.slope))
    pick = (lambda r: float(r.columns)) if column else (lambda r: float(r.beams))
    if slope < float(rows[0].slope) - 1e-9:
        raise TimberDesignError(
            f"slope of grain 1 in {slope:g} is steeper than the code's table (1 in "
            f"{float(rows[0].slope):g})"
        )
    if slope >= float(rows[-1].slope):
        return pick(rows[-1])
    xs = [float(r.slope) for r in rows]
    return float(np.interp(slope, xs, [pick(r) for r in rows]))


@dataclass(frozen=True)
class Timber:
    """Permissible stresses [MPa] of a material at its location, grade and durability (before
    K2): ``fb`` bending, ``ft`` tension, ``fv`` horizontal shear, ``fva`` shear along the
    grain, ``fc`` compression parallel and ``fcn`` perpendicular to the grain."""

    group: str
    location: str
    e: float
    fb: float
    ft: float
    fv: float
    fva: float
    fc: float
    fcn: float
    species: str | None = None
    factors: dict[str, float] = field(default_factory=dict)
    live_duration: str = "continuous"
    notes: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        group: str,
        location: str = "inside",
        e: float | None = None,
        grade: str = "I",
        low_durability: bool | None = None,
        slope: float | None = None,
        species: str | None = None,
        live_duration: str = "continuous",
    ) -> Timber:
        table = _table()
        if location not in LOCATIONS:
            raise TimberDesignError(f"unknown location '{location}'")
        notes: list[str] = []
        found = find_species(species)
        source: Any = None
        if found is not None and found[1].has_stresses:
            source = found[1]
        elif found is not None:
            notes.append(
                f"{found[1].botanical}: no stresses in the code's species table, strength "
                f"group {group} used"
            )
        if source is None:
            if group not in table.groups:
                raise TimberDesignError(f"unknown strength group '{group}'")
            source = table.groups[group]
        if grade not in table.grades:
            raise TimberDesignError(f"unknown grade '{grade}'")
        factor = float(table.grades[grade])
        factors = {"grade": factor}
        low = low_durability
        if low is None and found is not None:
            low = (found[1].durability or "") in table.lowDurability.classes
        if low and location in table.lowDurability.locations:
            factors["durability"] = float(table.lowDurability.factor)
            factor *= factors["durability"]
        k1b = k1c = 1.0
        if slope is not None:
            k1b, k1c = slope_factor(slope, False), slope_factor(slope, True)
            factors["K1"] = k1b
            factors["K1 columns"] = k1c
        if live_duration not in LIVE_DURATIONS:
            raise TimberDesignError(f"unknown live load duration '{live_duration}'")
        along = float(source.shearAlong)
        bending = float(source.bending[location])
        # The species table gives one value for bending and tension along the grain.
        tensions = getattr(source, "tension", None)
        tension = float(tensions[location]) if tensions else bending
        return cls(
            group,
            location,
            float(e or source.E),
            bending * factor * k1b,
            tension * factor * k1b,
            float(source.shearHorizontal) * factor * k1b,
            along * factor * k1b,
            float(source.compressionParallel[location]) * factor * k1c,
            float(source.compressionPerpendicular[location]) * factor,
            found[0] if found else None,
            factors,
            live_duration,
            tuple(notes),
        )

    @classmethod
    def of_material(cls, material: Any) -> Timber:
        props = getattr(material, "timber", None)
        if props is None:
            raise TimberDesignError(f"'{getattr(material, 'id', '?')}' is not a timber material")
        return cls.of(
            props.group,
            props.location,
            None,
            getattr(props, "grade", "I"),
            getattr(props, "lowDurability", None),
            getattr(props, "slopeOfGrain", None),
            getattr(props, "species", None),
            getattr(props, "liveLoadDuration", "continuous"),
        )


def depth_factor(d: float) -> float:
    """K3 of a rectangular beam of depth ``d`` [mm] (1 up to the pack's depth)."""
    f = _table().depthFactor
    if d <= float(f.above):
        return 1.0
    return float(f.factor) * (d * d + float(f.a)) / (d * d + float(f.b))


def box_form_factor(d: float, p1: float, q1: float) -> float:
    """K4 of a box or I beam of depth ``d`` [mm]: ``p1`` flange thickness / depth, ``q1`` total
    web thickness / overall width."""
    f, k = _table().depthFactor, _table().formFactors
    y = p1 * p1 * (6 - 8 * p1 + 3 * p1 * p1) * (1 - q1) + q1
    ratio = (d * d + float(f.a)) / (d * d + float(f.b))
    return float(k.boxBase) + float(k.boxFactor) * y * (ratio - 1)


def compression_stress(fc: float, e: float, slenderness: float) -> tuple[float, str]:
    """(permissible compression parallel to the grain [MPa], "short" | "intermediate" | "long")
    of a solid column at S/d = ``slenderness``."""
    c = _table().column
    k8 = float(c.k8) * math.sqrt(e / fc)
    if slenderness <= float(c.short):
        return fc, "short"
    if slenderness < k8:
        return fc * (1.0 - (slenderness / k8) ** 4 / float(c.intermediate)), "intermediate"
    return float(c.long) * e / slenderness**2, "long"


def box_compression_stress(
    fc: float, e: float, ratio: float, u: float, q: float
) -> tuple[float, str]:
    """A box column at S/√(d1² + d2²) = ``ratio`` with the plank constants U, q."""
    c, b = _table().column, _table().boxColumn
    k9 = float(b.k9) * math.sqrt(u * e / (q * fc))
    if ratio < float(b.short):
        return q * fc, "short"
    if ratio <= k9:
        return q * fc * (1.0 - (ratio / k9) ** 4 / float(c.intermediate)), "intermediate"
    return float(c.long) * u * e / ratio**2, "long"


def spaced_compression_stress(
    fc: float, e: float, slenderness: float, restraint: float
) -> tuple[float, str]:
    """A spaced column's member at S/d = ``slenderness`` with the end restraint factor."""
    c, s = _table().column, _table().spacedColumn
    k10 = float(s.k10) * math.sqrt(restraint * e / fc)
    if slenderness <= float(c.short):
        return fc, "short"
    if slenderness < k10:
        return fc * (1.0 - (slenderness / k10) ** 4 / float(c.intermediate)), "intermediate"
    return float(c.long) * e * restraint / slenderness**2, "long"


def plank(t: float) -> tuple[float, float]:
    """(U, q) of box column planks ``t`` [mm] thick."""
    for row in _table().boxColumn.planks:
        if abs(float(row.t) - t) <= 0.5:
            return float(row.U), float(row.q)
    sizes = ", ".join(f"{float(r.t):g}" for r in _table().boxColumn.planks)
    raise TimberDesignError(f"box column planks {t:g} mm thick: the code gives U, q for {sizes} mm")


def duration_factor(cases: dict[str, float] | bool, live_duration: str = "continuous") -> float:
    """K2 of a combination ``{case: factor}``: the shortest duration load in it governs (dead
    loads continuous, live loads ``live_duration``, wind and earthquake). A bool (old form):
    True for a combination with wind or earthquake."""
    d = _table().duration
    if isinstance(cases, bool):
        return float(d.windEarthquake if cases else d.continuous)
    present = {c for c, v in cases.items() if v}
    k = float(d.continuous)
    if present & {"L", "Lr"} or any(c.startswith("LP") for c in present):
        k = max(k, float(d[live_duration]))
    if any(c[:1] in ("W", "E") for c in present):
        k = max(k, float(d.windEarthquake))
    return k


def concentrated_reduction(distance: float) -> float:
    """The share of a concentrated load at ``distance`` beam depths from the nearest support
    that may be left out of the vertical reaction (interpolated, none beyond the table)."""
    rows = sorted(_table().concentratedNearSupport, key=lambda r: float(r.distance))
    xs = [float(r.distance) for r in rows]
    return float(np.interp(distance, xs, [float(r.reduction) for r in rows]))


def concentrated_shear(c: float, span: float, x: float, d: float) -> float:
    """V of a concentrated load ``c`` at ``x`` from the support of a beam ``d`` deep spanning
    ``span`` (the formula of the shear at supports for concentrated loads)."""
    r = (x / d) ** 2
    return 10 * c * (span - x) * r / (9 * span * (2 + r))


def uniform_shear(w: float, span: float, d: float) -> float:
    """V of a total uniform load ``w`` over ``span`` with the loads within ``d`` of the support
    left out."""
    return w / 2 * (1 - 2 * d / span)


def notch_shear(v: float, b: float, d: float, notch: Any) -> float:
    """Horizontal shear [MPa] at a notched support: ``notch`` with ``face``, ``depth`` D2 and
    ``length`` e [mm]."""
    d2, e = float(notch.depth), float(notch.length)
    d1 = d - d2
    if d1 <= 0:
        raise TimberDesignError("the notch is as deep as the beam")
    if notch.face == "tension":
        return 3 * v * d / (2 * b * d1 * d1)
    if e > d:
        return 3 * v / (2 * b * d1)
    return 3 * v / (2 * b * (d - d2 / d * e))


def bearing_factor(length: float) -> float:
    """K7 of a bearing ``length`` [mm] long at least the pack's distance from the end."""
    b = _table().bearing
    if length >= float(b.fullLength):
        return 1.0
    rows = sorted(b.k7, key=lambda r: float(r.length))
    xs = [float(r.length) for r in rows]
    return float(np.interp(length, xs, [float(r.factor) for r in rows]))


def angle_bearing(fc: float, fcn: float, theta: float) -> float:
    """Permissible bearing stress at ``theta`` [rad] to the grain."""
    return fc * fcn / (fc * math.sin(theta) ** 2 + fcn * math.cos(theta) ** 2)


# ─────────────────────────────────────── the section ───────────────────────────────────────


@dataclass(frozen=True)
class Section:
    """A timber section: ``b`` across (xDim) and ``d`` deep (yDim) [mm]; ``shape`` "rectangle",
    "circle", "box" (``t`` the plank thickness) or "I" (``tf``, ``tw``)."""

    b: float
    d: float
    shape: str = "rectangle"
    t: float = 0.0
    tf: float = 0.0
    tw: float = 0.0

    @classmethod
    def of(cls, profile: Any) -> Section:
        shape = getattr(profile, "shape", None)
        if shape == "rectangle":
            return cls(float(profile.xDim), float(profile.yDim))
        if shape == "circle":
            return cls(2 * float(profile.radius), 2 * float(profile.radius), "circle")
        if shape == "rectangleHollow":
            return cls(
                float(profile.xDim), float(profile.yDim), "box", float(profile.wallThickness)
            )
        if shape == "I":
            return cls(
                float(profile.overallWidth),
                float(profile.overallDepth),
                "I",
                tf=float(profile.flangeThickness),
                tw=float(profile.webThickness),
            )
        raise TimberDesignError(
            f"timber members are designed as rectangular, circular, box or I sections, not "
            f"'{shape}'"
        )

    def _inner(self) -> tuple[float, float]:
        if self.shape == "box":
            return self.b - 2 * self.t, self.d - 2 * self.t
        if self.shape == "I":
            return self.b - self.tw, self.d - 2 * self.tf
        return 0.0, 0.0

    @property
    def area(self) -> float:
        if self.shape == "circle":
            return math.pi * self.b**2 / 4
        bi, di = self._inner()
        return self.b * self.d - bi * di

    @property
    def ix(self) -> float:
        """About the width axis [mm⁴]."""
        if self.shape == "circle":
            return math.pi * self.b**4 / 64
        bi, di = self._inner()
        return (self.b * self.d**3 - bi * di**3) / 12

    @property
    def iy(self) -> float:
        if self.shape == "circle":
            return self.ix
        if self.shape == "I":
            return (2 * self.tf * self.b**3 + (self.d - 2 * self.tf) * self.tw**3) / 12
        bi, di = self._inner()
        return (self.d * self.b**3 - di * bi**3) / 12

    @property
    def zx(self) -> float:
        return self.ix / (self.d / 2)

    @property
    def zy(self) -> float:
        return self.iy / (self.b / 2)

    @property
    def web(self) -> float:
        """Width resisting the horizontal shear at the neutral axis [mm]."""
        return {"box": 2 * self.t, "I": self.tw}.get(self.shape, self.b)

    @property
    def qx(self) -> float:
        """First moment of the half section about the width axis [mm³]."""
        if self.shape == "circle":
            return self.b**3 / 12
        bi, di = self._inner()
        return (self.b * self.d**2 - bi * di**2) / 8

    def shear_stress(self, v: float) -> float:
        """H = V Q / (I b) [MPa] (3V/(2bD) for a rectangle)."""
        return v * self.qx / (self.ix * self.web)

    @property
    def least(self) -> float:
        """The column dimension d: least side; a circle's equivalent square."""
        if self.shape == "circle":
            return math.sqrt(self.area)
        return min(self.b, self.d)

    def form_factors(self, diagonal: bool = False) -> tuple[float, float, str]:
        """(about the width axis, about the depth axis, label)."""
        k = _table().formFactors
        if self.shape == "circle":
            return float(k.circle), float(k.circle), f"K5 = {float(k.circle):g}"
        if self.shape == "rectangle":
            if diagonal and abs(self.b - self.d) < 1e-6:
                f = float(k.squareDiagonal)
                return f, f, f"K6 = {f:g}"
            kx, ky = depth_factor(self.d), depth_factor(self.b)
            return kx, ky, f"K3 = {kx:.3f}"
        if self.shape == "box":
            kx = box_form_factor(self.d, self.t / self.d, 2 * self.t / self.b)
            ky = box_form_factor(self.b, self.t / self.b, 2 * self.t / self.d)
            return kx, ky, f"K4 = {kx:.3f}"
        kx = box_form_factor(self.d, self.tf / self.d, self.tw / self.b)
        return kx, 1.0, f"K4 = {kx:.3f}"


# ─────────────────────────────────────── the member ───────────────────────────────────────


def _flag(row: dict[str, Any]) -> dict[str, Any]:
    row["flag"] = True
    return row


def _support_shear(st: Any, depth_m: float, ends: tuple[bool, bool]) -> float:
    """Largest |Vy| along the member leaving out one depth at each supported end (the shear at
    that distance interpolated)."""
    s = np.asarray(st.s, dtype=float)
    v = np.abs(np.asarray(st.Vy, dtype=float))
    if len(s) < 2 or s[-1] - s[0] <= 2 * depth_m:
        return float(v.max()) if len(v) else 0.0
    lo = s[0] + depth_m if ends[0] else s[0]
    hi = s[-1] - depth_m if ends[1] else s[-1]
    inside = v[(s >= lo - 1e-9) & (s <= hi + 1e-9)]
    edge = [float(np.interp(lo, s, v)), float(np.interp(hi, s, v))]
    return max([*edge, *(float(x) for x in inside)])


def _end_shear(st: Any, depth_m: float, end: int) -> float:
    s = np.asarray(st.s, dtype=float)
    v = np.abs(np.asarray(st.Vy, dtype=float))
    if len(s) < 2:
        return float(v.max()) if len(v) else 0.0
    at = s[0] + depth_m if end == 0 else s[-1] - depth_m
    return float(np.interp(min(max(at, s[0]), s[-1]), s, v))


def check_member(
    section: Section,
    timber: Timber,
    stations: Sequence[Any],
    length: float,
    k2: dict[str, float] | None = None,
    kind: str = "beam",
    options: Any = None,
) -> list[dict[str, Any]]:
    """The checks of a member (see the module notes): ``stations`` per combination
    (:class:`saengine.design.steel.members.Stations`: P compression positive [N], Mx, My
    [N·mm], Vy, Vx [N]); ``length`` [mm]; ``k2``: per combination name its load duration
    factor (1 when missing); ``options``: the type's :class:`TimberMember` data."""
    table = _table()
    k2 = k2 or {}
    beam = kind == "beam"
    free_end = getattr(options, "freeEnd", "none") if options is not None else "none"
    supported = (free_end != "start", free_end != "end")
    notch = getattr(options, "notch", None) if options is not None else None
    spaced = getattr(options, "spaced", None) if options is not None else None
    bearing = getattr(options, "bearingLength", None) if options is not None else None
    kx, ky, form = section.form_factors(bool(getattr(options, "diagonalLoading", False)))
    pieces = int(spaced.pieces) if spaced is not None else 1
    area = section.area * pieces
    # The column's allowable compression (before K2: K2 scales fcp and E alike).
    column_note = ""
    if spaced is not None:
        restraint = float(table.spacedColumn.restraint[spaced.connectors])
        slenderness = length / section.least
        limit = float(table.spacedColumn.maxSlenderness)
        fca, column = spaced_compression_stress(timber.fc, timber.e, slenderness, restraint)
        column_clause = clause("spacedColumn")
        column_note = f"spaced column, {pieces} members, restraint factor {restraint:g}"
    elif section.shape == "box":
        u, q = plank(section.t)
        d1 = min(section.b, section.d)
        d2 = d1 - 2 * section.t
        slenderness = length / math.hypot(d1, d2)
        limit = math.inf
        fca, column = box_compression_stress(timber.fc, timber.e, slenderness, u, q)
        column_clause = clause("boxColumn")
        column_note = f"box column, U = {u:g}, q = {q:g}, S/√(d1² + d2²)"
    else:
        slenderness = length / section.least
        limit = float(table.column.maxSlenderness)
        fca, column = compression_stress(timber.fc, timber.e, slenderness)
        column_clause = clause("column")
    shear_allow = timber.fv if beam else timber.fva
    shear_clause = clause("shear") if beam else clause("shearAlong")
    depth_m = section.d / 1000.0
    rows: dict[str, dict[str, Any]] = {}

    def offer(key: str, row: dict[str, Any]) -> None:
        if key not in rows or row["utilisation"] > rows[key]["utilisation"]:
            rows[key] = row

    for st in stations:
        name = st.combination
        k = float(k2.get(name, 1.0))
        tag = f"; K2 = {k:.2f}" if abs(k - 1) > 1e-9 else ""
        fbx, fby = k * timber.fb * kx, k * timber.fb * ky
        if beam:
            v = _support_shear(st, depth_m, supported)
            offer(
                "v",
                _row(
                    f"Horizontal shear H = VQ/(Ib), loads within D of the supports left out "
                    f"({shear_clause}; {clause('shearSupport')})",
                    section.shear_stress(v / pieces),
                    k * shear_allow,
                    "MPa",
                    name,
                    f"V = {v / 1e3:.1f} kN{tag}",
                ),
            )
            if notch is not None and section.shape == "rectangle":
                for end in (0, 1):
                    if not supported[end]:
                        continue
                    ve = _end_shear(st, depth_m, end)
                    offer(
                        f"n{end}",
                        _row(
                            f"Notched support, {notch.face} face, {'start' if end == 0 else 'end'}"
                            f" ({clause('notch')})",
                            notch_shear(ve, section.b, section.d, notch),
                            k * shear_allow,
                            "MPa",
                            name,
                            f"V = {ve / 1e3:.1f} kN{tag}",
                        ),
                    )
            if bearing:
                for end, i in ((0, 0), (1, -1)):
                    if not supported[end] or not len(st.Vy):
                        continue
                    r = abs(float(np.asarray(st.Vy)[i]))
                    offer(
                        f"b{end}",
                        _row(
                            f"Bearing across the grain at the {'start' if end == 0 else 'end'} "
                            f"support ({clause('bearing')})",
                            r / (section.b * float(bearing)),
                            k * timber.fcn,
                            "MPa",
                            name,
                            f"R = {r / 1e3:.1f} kN on {float(bearing):g} mm (K7 = 1 at the end)"
                            f"{tag}",
                        ),
                    )
        for i in range(len(st.s)):
            where = st.where[i] if i < len(st.where) else ""
            p = float(st.P[i])
            mx, my = abs(float(st.Mx[i])) / pieces, abs(float(st.My[i])) / pieces
            sx, sy = mx / section.zx, my / section.zy
            offer(
                "bx",
                _row(
                    f"Bending f = M/Z about the width axis ({clause('bending')})",
                    sx,
                    fbx,
                    "MPa",
                    name,
                    f"{where}; {form}{tag}",
                ),
            )
            if section.shape != "circle":
                offer(
                    "by",
                    _row(
                        f"Bending f = M/Z about the depth axis ({clause('bending')})",
                        sy,
                        fby,
                        "MPa",
                        name,
                        f"{where}{tag}",
                    ),
                )
            if not beam:
                v = max(abs(float(st.Vy[i])), abs(float(st.Vx[i]))) / pieces
                offer(
                    "v",
                    _row(
                        f"Shear along the grain ({shear_clause})",
                        section.shear_stress(v),
                        k * shear_allow,
                        "MPa",
                        name,
                        f"{where}{tag}",
                    ),
                )
            fa = abs(p) / area
            if p >= 0:
                axial = k * fca
                offer(
                    "c",
                    _row(
                        f"Compression parallel to the grain, {column} column ({column_clause})",
                        fa,
                        axial,
                        "MPa",
                        name,
                        f"{where}; S/d = {slenderness:.1f}"
                        + (f"; {column_note}" if column_note else "")
                        + tag,
                    ),
                )
                combined_clause = clause("combinedCompression")
            else:
                axial = k * timber.ft
                offer(
                    "t",
                    _row(
                        f"Tension parallel to the grain ({clause('tension')})",
                        fa,
                        axial,
                        "MPa",
                        name,
                        f"{where}{tag}",
                    ),
                )
                combined_clause = clause("combinedTension")
            combined = (
                fa / axial + sx / fbx + (sy / fby if section.shape != "circle" else 0.0)
                if axial > 0
                else math.inf
            )
            offer(
                "m",
                _row(
                    f"Combined axial and bending f/F + fb/Fb ({combined_clause})",
                    combined,
                    1.0,
                    "",
                    name,
                    f"{where}{tag}",
                    utilisation=combined,
                ),
            )
    order = ("bx", "by", "v", "n0", "n1", "b0", "b1", "t", "c", "m")
    out = [rows[k] for k in order if k in rows]
    if (kind in ("column", "brace") or "c" in rows) and math.isfinite(limit):
        out.append(
            _row(
                f"Slenderness S/d ≤ {limit:g} ({column_clause})",
                slenderness,
                limit,
                "",
                note=f"S = {length:.0f} mm (the member length), d = {section.least:.0f} mm",
            )
        )
    if beam:
        out += _beam_rules(section, length, options, bearing, notch)
    for note in timber.notes:
        out.append(_flag(_row(f"Stresses ({clause('species')})", 0.0, 1.0, "", note=note)))
    return out


def _beam_rules(
    section: Section, length: float, options: Any, bearing: float | None, notch: Any
) -> list[dict[str, Any]]:
    """Width, lateral restraint, bearing length and notch limits of a flexural member."""
    f = _table().flexure
    out: list[dict[str, Any]] = []
    width = min(section.b, section.d) if section.shape == "circle" else section.b
    least = max(float(f.minWidth), length / float(f.widthSpanRatio))
    out.append(
        _row(
            f"Least width ({clause('width')})",
            least,
            width,
            "mm",
            note=f"at least {float(f.minWidth):g} mm and span/{float(f.widthSpanRatio):g}",
        )
    )
    if section.d > float(f.depthWidthRatio) * width or length > float(f.spanWidthRatio) * width:
        spacing = float(getattr(options, "restraintSpacing", None) or length)
        out.append(
            _row(
                f"Lateral restraint spacing ({clause('restraint')})",
                spacing,
                float(f.restraintWidthRatio) * width,
                "mm",
                note="deeper than "
                f"{float(f.depthWidthRatio):g} × the width or longer than "
                f"{float(f.spanWidthRatio):g} × it"
                + (
                    ""
                    if getattr(options, "restraintSpacing", None)
                    else "; restrained at the ends only"
                ),
            )
        )
    if bearing:
        out.append(
            _row(
                f"Bearing length ({clause('minBearing')})",
                float(f.minBearing),
                float(bearing),
                "mm",
            )
        )
    if notch is not None:
        d2 = float(notch.depth)
        out.append(
            _row(
                f"Notch depth ({clause('notchLimits')})",
                d2,
                min(float(f.notchDepthShare), float(f.notchSectionShare)) * section.d,
                "mm",
            )
        )
        out.append(
            _row(
                f"Notch distance from the support ({clause('notchLimits')})",
                float(notch.length),
                float(f.notchSpanShare) * length,
                "mm",
            )
        )
    return out


def deflection_row(
    profiles: dict[str, Sequence[tuple[float, float]]],
    e_ratio: float,
    options: Any = None,
) -> dict[str, Any] | None:
    """The deflection check of a flexural member from its nodes' downward deflections per load
    case ``profiles`` ({"D": [(s [m], deflection [mm, down positive]), ...], ...}; D and SD
    dead, L and Lr live), scaled by ``e_ratio`` (the analysis's E over the design E): the dead
    load doubled for the long term, relative to the chord (a cantilever: the free end relative
    to the support). None without the dead load case."""
    d = _table().deflection
    if "D" not in profiles:
        return None
    s = np.array([x for x, _ in profiles["D"]], dtype=float)
    if len(s) < 2:
        return None
    total = np.zeros(len(s))
    for case, weight in (
        ("D", float(d.deadLoadFactor)),
        ("SD", float(d.deadLoadFactor)),
        ("L", 1.0),
        ("Lr", 1.0),
    ):
        if case in profiles and len(profiles[case]) == len(s):
            total += weight * np.array([u for _, u in profiles[case]], dtype=float)
    total *= e_ratio
    span = (s[-1] - s[0]) * 1000.0
    free = getattr(options, "freeEnd", "none") if options is not None else "none"
    brittle = bool(getattr(options, "brittleFinishes", False)) if options is not None else False
    if free in ("start", "end"):
        tip, root = (0, -1) if free == "start" else (-1, 0)
        delta = abs(total[tip] - total[root])
        divisor = float(d.cantilever)
        what = "cantilever"
    else:
        chord = total[0] + (total[-1] - total[0]) * (s - s[0]) / (s[-1] - s[0])
        delta = float(np.max(np.abs(total - chord)))
        divisor = float(d.brittle if brittle else d.span)
        what = "brittle finishes" if brittle else "span"
    return _row(
        f"Deflection ≤ L/{divisor:g} ({clause('deflection')})",
        delta,
        span / divisor,
        "mm",
        "service",
        f"{what}; {float(d.deadLoadFactor):g} × dead + live loads, L = {span:.0f} mm",
    )


def combination_durations(
    factors: Sequence[dict[str, float]], names: Sequence[str], live_duration: str = "continuous"
) -> dict[str, float]:
    """K2 per combination name (see :func:`duration_factor`)."""
    return {n: duration_factor(f, live_duration) for n, f in zip(names, factors, strict=True)}


def lateral_kinds(factors: Sequence[dict[str, float]], names: Sequence[str]) -> dict[str, str]:
    """Per combination name, "earthquake" or "wind" when its factors have such a case."""
    out: dict[str, str] = {}
    for name, f in zip(names, factors, strict=True):
        cases = {c for c, v in f.items() if v}
        if any(c.startswith("E") for c in cases):
            out[name] = "earthquake"
        elif any(c.startswith("W") for c in cases):
            out[name] = "wind"
    return out


def design_timber_member(
    member_id: str,
    kind: str,
    object_type: Any,
    material: Any,
    pieces: Sequence[Any],
    combinations: Sequence[str],
    factors: Sequence[dict[str, float]] | dict[str, str] | None = None,
    turned: bool = False,
    profiles: dict[str, Sequence[tuple[float, float]]] | None = None,
    e_analysis: float | None = None,
) -> dict[str, Any]:
    """The design report entry of one timber beam, column or brace: ``{id, kind, type,
    members, checks, utilisation, ok, material, timber}``. ``pieces``: its analysis elements
    with the allowable stress combinations' forces; ``factors``: each combination's
    ``{case: factor}`` (for K2); ``profiles``: the beam's deflections per load case (see
    :func:`deflection_row`), ``e_analysis`` the analysis's E [MPa]. Raises
    :class:`TimberDesignError`."""
    from saengine.design.steel.lengths import positions
    from saengine.design.steel.members import member_stations
    from saengine.design.timber import connections

    if not pieces:
        raise TimberDesignError("not in the analysis results")
    section = Section.of(object_type.profile)
    timber = Timber.of_material(material)
    options = getattr(object_type, "timber", None)
    s, _ = positions(pieces, 2)
    length = float(s[-1] - s[0]) * 1000.0
    stations = member_stations(pieces, combinations, turned)
    if isinstance(factors, dict):  # the old {name: "wind" | "earthquake"} form
        k2 = {n: duration_factor(n in factors) for n in combinations}
    elif factors:
        k2 = combination_durations(factors, combinations, timber.live_duration)
    else:
        k2 = {}
    checks = check_member(section, timber, stations, length, k2, kind, options)
    if kind == "beam" and profiles:
        ratio = (e_analysis / timber.e) if e_analysis else 1.0
        row = deflection_row(profiles, ratio, options)
        if row is not None:
            checks.append(row)
    joint = getattr(object_type, "timberJoint", None)
    joint_out = None
    if joint is not None:
        joint_rows, joint_out = connections.check_joint(joint, section, timber, stations, k2)
        checks += joint_rows
    strength = [c for c in checks if not c["flag"]]
    entry = {
        "id": member_id,
        "kind": kind,
        "type": object_type.id,
        "members": [p.id for p in pieces],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "material": material.id,
        # Not "section": the workbench reads a "section" with a label as a steel member's.
        "timber": {
            "label": f"{section.b:g} x {section.d:g} timber ({section.shape})",
            "group": timber.group,
            "species": timber.species,
            "location": timber.location,
            "E": timber.e,
            "stresses": {
                "Fb": timber.fb,
                "Ft": timber.ft,
                "Fv": timber.fv,
                "Fc": timber.fc,
                "Fcn": timber.fcn,
            },
            "factors": timber.factors,
            "length": round(length, 0),
            "code": code_name(),
            "basis": clause("chapter"),
        },
    }
    if joint_out is not None:
        entry["timber"]["joint"] = joint_out
    return entry


def asd_pieces(
    pieces: Sequence[Any], case_forces: dict[str, dict[int, np.ndarray]], factors: Sequence[dict]
) -> list[Any]:
    """Copies of ``pieces`` whose forces are the combinations ``factors`` ({case: factor})
    of the analysis's per-case forces ``case_forces`` ({case: {element id: (stations, 6)}});
    a case without forces counts nothing."""
    from dataclasses import replace

    out = []
    for p in pieces:
        forces = []
        for f in factors:
            total = None
            for case, value in f.items():
                rows = case_forces.get(case, {}).get(p.id)
                if rows is None or not value:
                    continue
                part = value * np.asarray(rows, dtype=float)
                total = part if total is None else total + part
            if total is None:
                total = np.zeros_like(np.asarray(p.forces[0], dtype=float))
            forces.append(total)
        out.append(replace(p, forces=forces, sway=None, sustained=None, live=None))
    return out


def allowable_combinations(
    present: set[str] | frozenset[str] | None = None,
) -> list[tuple[str, dict[str, float]]]:
    """The code pack's allowable stress combinations as ``(name, {case: factor})``, wind and
    earthquake in ±X and ±Y (formed by :func:`saengine.fem.combinations.allowable_combinations`;
    with ``present``, the optional cases the model lacks are left out)."""
    from saengine.fem.combinations import allowable_combinations as formed

    return formed(present)

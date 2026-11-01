"""A standard table of rolled and hollow steel sections, with properties computed from the
dimensions (nothing is copied from a proprietary section database).

Which shapes: what the Bangladesh market stocks and fabricators build with.

- I/H: European parallel-flange IPE, HEA and HEB (EN 10365 nominal dimensions; imported
  widely, largely from China) and Indian ISMB (IS 808, imported from India). ISMB flanges
  are tapered in the mill section; here they are parallel at the mean flange thickness.
- Channels: Indian ISMC (IS 808), again parallel flanges at the mean thickness.
- Equal angles: the common EN 10056 / IS 808 sizes (L 25x25x3 to L 200x200x20).
- Hollow sections, cold-formed (EN 10219 sizes, which local tube mills roll): SHS, RHS and
  CHS by size and wall thickness, corner radii ro = 2t (t <= 6), 2.5t (t <= 10), 3t above
  (EN 10219-2 practice), ri = ro - t.

Dimensions are the standards' nominal ones; confirm the mill's catalogue before ordering.

Properties (mm units, x the major axis: the horizontal axis of a section standing with its
depth vertical, as :mod:`saengine.library.sections` uses): A, Ix, Iy, Sx, Sy, Zx, Zy, rx,
ry, J, Cw, the mass per metre (7850 kg/m³), and for angles the principal Iu, Iv, rv.

A, I, S and Z are exact for the plates plus the fillets and corner roundings (each a
spandrel, a square less a quarter circle, with its own centroid and inertia; only the plastic
moduli take the spandrels as lumped areas, an error far below 0.1 %). J uses the thin-walled
formulas (I, channel, tee, angle: Σ b t³/3 without the fillets, slightly conservative;
hollow: Bredt on the mid-line), Cw the usual closed forms (I: Iy h0²/4; channel, tee and angle:
the AISC Design Guide 9 forms; hollow sections: 0). Tees (not in the table) are built for
custom profiles. This is the one place A, I, S and Z of steel shapes are computed:
:mod:`saengine.design.steel.properties` builds the member design's on it, without fillets.
:mod:`saengine.library.sections` (sectionproperties, finite elements) cross-checks the table in
the tests.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from functools import cache
from typing import Any

from saengine.codes import context as code_context
from saengine.library import objects as o

#: The table's names (``STEEL_DENSITY``, ``FAMILIES``, ``SHAPE_FAMILIES``, the sections) are
#: the code pack's ``steelSections`` table (``saengine/codes/packs/bnbc2020/data/
#: steelSections.json``: each family's nominal dimensions and the standard they come from), read
#: from the pack in force where they are used (:class:`saengine.codes.context.TableNames`).


@dataclass(frozen=True)
class SteelSection:
    name: str
    family: str
    #: The 04 Objects profile shape: "I", "U", "T", "L", "rectangleHollow", "circleHollow".
    shape: str
    h: float  # mm, depth (CHS: outside diameter)
    b: float  # mm, width
    tw: float  # mm, web (angle, hollow: wall) thickness
    tf: float  # mm, flange thickness (angle, hollow: = tw)
    r: float  # mm, root radius (hollow: outer corner radius; CHS 0)
    r2: float  # mm, toe radius of angles (else 0)
    A: float  # mm²
    Ix: float  # mm⁴, major axis
    Iy: float  # mm⁴
    Sx: float  # mm³, elastic, the least of the two extreme fibres
    Sy: float  # mm³
    Zx: float  # mm³, plastic
    Zy: float  # mm³
    rx: float  # mm
    ry: float  # mm
    J: float  # mm⁴
    Cw: float  # mm⁶
    mass: float  # kg/m
    cx: float  # mm, centroid from the left edge (channels, angles; else b/2)
    cy: float  # mm, centroid from the bottom edge
    Iu: float | None = None  # mm⁴, angles: principal major
    Iv: float | None = None  # mm⁴, angles: principal minor
    rv: float | None = None  # mm, angles: least radius of gyration
    extra: dict[str, float] = field(default_factory=dict)
    #: An RHS lying on its side (the table's section turned 90°): h, b and the x/y properties
    #: are those of the turned section, x still the horizontal axis.
    turned: bool = False

    @property
    def r_min(self) -> float:
        return min(x for x in (self.rx, self.ry, self.rv) if x is not None)

    def profile(self) -> dict[str, Any]:
        """The 04 Objects profile (``Profile`` JSON) of this section."""
        return profile_of(self)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rMin"] = self.r_min
        d["profile"] = self.profile()
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in d.items()}


# ─────────────────────────────── composite of plates and spandrels ───────────────────────────────

_K = (10 - 3 * math.pi) / (3 * (4 - math.pi))  # spandrel centroid from its corner, in r


@dataclass(frozen=True)
class _Part:
    """A signed area with its centroid and own inertia; ``rect`` when it is a rectangle
    (x0, x1, y0, y1), split exactly for the plastic moduli."""

    a: float
    cx: float
    cy: float
    ix: float
    iy: float
    ixy: float
    rect: tuple[float, float, float, float] | None = None


def _rect(x0: float, x1: float, y0: float, y1: float, sign: float = 1.0) -> _Part:
    w, h = x1 - x0, y1 - y0
    return _Part(
        sign * w * h,
        (x0 + x1) / 2,
        (y0 + y1) / 2,
        sign * w * h**3 / 12,
        sign * h * w**3 / 12,
        0.0,
        (x0, x1, y0, y1),
    )


@cache
def _spandrel_unit() -> tuple[float, float, float]:
    """Area, own I (about its centroid, parallel to the legs) and own |Ixy| of a spandrel of
    radius 1: the unit square less the quarter disc centred on the opposite corner."""
    a_q = math.pi / 4
    e = 4 / (3 * math.pi)  # quarter-disc centroid from its centre
    a = 1 - a_q
    # About the leg through the corner (y = 0): square 1/3; quarter disc centred at (1, 1).
    iq_c = math.pi / 16 - a_q * e**2
    i0 = 1 / 3 - (iq_c + a_q * (1 - e) ** 2)
    ic = i0 - a * _K**2
    ixyq_c = 1 / 8 - a_q * e**2
    ixy0 = 1 / 4 - (ixyq_c + a_q * (1 - e) ** 2)
    ixyc = ixy0 - a * _K**2
    return a, ic, ixyc


def _spandrel(x: float, y: float, sx: int, sy: int, r: float, sign: float = 1.0) -> list[_Part]:
    """The spandrel in the corner (x, y) of radius r, lying towards (sx, sy)."""
    if r <= 0:
        return []
    a, ic, ixyc = _spandrel_unit()
    return [
        _Part(
            sign * a * r**2,
            x + sx * _K * r,
            y + sy * _K * r,
            sign * ic * r**4,
            sign * ic * r**4,
            sign * sx * sy * ixyc * r**4,
        )
    ]


@dataclass(frozen=True)
class _Props:
    A: float
    cx: float
    cy: float
    Ix: float
    Iy: float
    Ixy: float
    Sx: float
    Sy: float
    Zx: float
    Zy: float


def _area_below(parts: list[_Part], c: float, axis: str) -> float:
    total = 0.0
    for p in parts:
        if p.rect is not None:
            x0, x1, y0, y1 = p.rect
            lo, hi, w = (y0, y1, x1 - x0) if axis == "x" else (x0, x1, y1 - y0)
            sign = 1.0 if p.a > 0 else -1.0
            total += sign * w * min(max(c - lo, 0.0), hi - lo)
        else:
            pos = p.cy if axis == "x" else p.cx
            total += p.a if pos < c else 0.0
    return total


def _first_moment_abs(parts: list[_Part], c: float, axis: str) -> float:
    total = 0.0
    for p in parts:
        if p.rect is not None:
            x0, x1, y0, y1 = p.rect
            lo, hi, w = (y0, y1, x1 - x0) if axis == "x" else (x0, x1, y1 - y0)
            sign = 1.0 if p.a > 0 else -1.0

            # ∫ |s - c| w ds over [lo, hi], split at c
            mid = min(max(c, lo), hi)
            below = w * ((c - lo) ** 2 - (c - mid) ** 2) / 2
            above = w * ((hi - c) ** 2 - (mid - c) ** 2) / 2
            total += sign * (below + above)
        else:
            pos = p.cy if axis == "x" else p.cx
            total += p.a * abs(pos - c)
    return total


def _plastic(parts: list[_Part], area: float, lo: float, hi: float, axis: str) -> float:
    a, b = lo, hi
    for _ in range(80):
        mid = (a + b) / 2
        if _area_below(parts, mid, axis) < area / 2:
            a = mid
        else:
            b = mid
    return _first_moment_abs(parts, (a + b) / 2, axis)


def _combine(parts: list[_Part], width: float, depth: float) -> _Props:
    """Properties of the parts, the section spanning [0, width] x [0, depth]."""
    area = sum(p.a for p in parts)
    cx = sum(p.a * p.cx for p in parts) / area
    cy = sum(p.a * p.cy for p in parts) / area
    ix = sum(p.ix + p.a * (p.cy - cy) ** 2 for p in parts)
    iy = sum(p.iy + p.a * (p.cx - cx) ** 2 for p in parts)
    ixy = sum(p.ixy + p.a * (p.cx - cx) * (p.cy - cy) for p in parts)
    return _Props(
        A=area,
        cx=cx,
        cy=cy,
        Ix=ix,
        Iy=iy,
        Ixy=ixy,
        Sx=ix / max(cy, depth - cy),
        Sy=iy / max(cx, width - cx),
        Zx=_plastic(parts, area, 0.0, depth, "x"),
        Zy=_plastic(parts, area, 0.0, width, "y"),
    )


def _section(
    name: str,
    family: str,
    shape: str,
    dims: tuple[float, float, float, float, float, float],
    props: _Props,
    j: float,
    cw: float,
    principal: bool = False,
) -> SteelSection:
    h, b, tw, tf, r, r2 = dims
    iu = iv = rv = None
    if principal:
        mean = (props.Ix + props.Iy) / 2
        radius = math.hypot((props.Ix - props.Iy) / 2, props.Ixy)
        iu, iv = mean + radius, mean - radius
        rv = math.sqrt(iv / props.A)
    return SteelSection(
        name=name,
        family=family,
        shape=shape,
        h=h,
        b=b,
        tw=tw,
        tf=tf,
        r=r,
        r2=r2,
        A=props.A,
        Ix=props.Ix,
        Iy=props.Iy,
        Sx=props.Sx,
        Sy=props.Sy,
        Zx=props.Zx,
        Zy=props.Zy,
        rx=math.sqrt(props.Ix / props.A),
        ry=math.sqrt(props.Iy / props.A),
        J=j,
        Cw=cw,
        mass=props.A * 1e-6 * _density(),
        cx=props.cx,
        cy=props.cy,
        Iu=iu,
        Iv=iv,
        rv=rv,
    )


# ───────────────────────────────────────── shapes ─────────────────────────────────────────


def i_section(name: str, family: str, h: float, b: float, tw: float, tf: float, r: float):
    """Doubly symmetric I/H with root fillets."""
    xw0, xw1 = (b - tw) / 2, (b + tw) / 2
    parts = [
        _rect(0, b, 0, tf),
        _rect(0, b, h - tf, h),
        _rect(xw0, xw1, tf, h - tf),
        *_spandrel(xw1, h - tf, 1, -1, r),
        *_spandrel(xw0, h - tf, -1, -1, r),
        *_spandrel(xw1, tf, 1, 1, r),
        *_spandrel(xw0, tf, -1, 1, r),
    ]
    props = _combine(parts, b, h)
    j = (2 * b * tf**3 + (h - 2 * tf) * tw**3) / 3
    cw = props.Iy * (h - tf) ** 2 / 4
    return _section(name, family, "I", (h, b, tw, tf, r, 0.0), props, j, cw)


def channel_section(name: str, family: str, h: float, b: float, tw: float, tf: float, r: float):
    """Channel, web on the left (x = 0), flanges to the right."""
    parts = [
        _rect(0, b, 0, tf),
        _rect(0, b, h - tf, h),
        _rect(0, tw, tf, h - tf),
        *_spandrel(tw, h - tf, 1, -1, r),
        *_spandrel(tw, tf, 1, 1, r),
    ]
    props = _combine(parts, b, h)
    j = (2 * b * tf**3 + (h - 2 * tf) * tw**3) / 3
    bp, hp = b - tw / 2, h - tf
    cw = (tf * bp**3 * hp**2 / 12) * (3 * bp * tf + 2 * hp * tw) / (6 * bp * tf + hp * tw)
    return _section(name, family, "U", (h, b, tw, tf, r, 0.0), props, j, cw)


def tee_section(name: str, family: str, h: float, b: float, tw: float, tf: float, r: float):
    """Tee, flange at the top, stem tip at y = 0, with root fillets."""
    xw0, xw1 = (b - tw) / 2, (b + tw) / 2
    parts = [
        _rect(0, b, h - tf, h),
        _rect(xw0, xw1, 0, h - tf),
        *_spandrel(xw1, h - tf, 1, -1, r),
        *_spandrel(xw0, h - tf, -1, -1, r),
    ]
    props = _combine(parts, b, h)
    j = (b * tf**3 + (h - tf / 2) * tw**3) / 3
    # Cw of a tee (AISC 360-16 Commentary to E4).
    cw = tf**3 * b**3 / 144 + tw**3 * (h - tf / 2) ** 3 / 36
    return _section(name, family, "T", (h, b, tw, tf, r, 0.0), props, j, cw)


def angle_section(name: str, d: float, b: float, t: float, r1: float, r2: float):
    """Angle with the vertical leg (depth d) on the left and the horizontal leg (width b)."""
    parts = [
        _rect(0, t, 0, d),
        _rect(t, b, 0, t),
        *_spandrel(t, t, 1, 1, r1),
        *_spandrel(t, d, -1, -1, r2, sign=-1.0),
        *_spandrel(b, t, -1, -1, r2, sign=-1.0),
    ]
    props = _combine(parts, b, d)
    j = (d + b - t) * t**3 / 3
    cw = (t**3 / 36) * ((b - t / 2) ** 3 + (d - t / 2) ** 3)
    return _section(name, "L", "L", (d, b, t, t, r1, r2), props, j, cw, principal=True)


def hollow_corner_radius(t: float) -> float:
    """Outer corner radius of cold-formed SHS/RHS (EN 10219-2 practice)."""
    return 2.0 * t if t <= 6 else 2.5 * t if t <= 10 else 3.0 * t


def rhs_section(name: str, family: str, h: float, b: float, t: float, ro: float | None = None):
    """Rectangular hollow section (depth h, width b), rounded corners."""
    ro = hollow_corner_radius(t) if ro is None else ro
    ri = max(ro - t, 0.0)
    parts = [_rect(0, b, 0, h), _rect(t, b - t, t, h - t, sign=-1.0)]
    for x, y, sx, sy in ((0, 0, 1, 1), (b, 0, -1, 1), (0, h, 1, -1), (b, h, -1, -1)):
        parts += _spandrel(x, y, sx, sy, ro, sign=-1.0)
    for x, y, sx, sy in (
        (t, t, 1, 1),
        (b - t, t, -1, 1),
        (t, h - t, 1, -1),
        (b - t, h - t, -1, -1),
    ):
        parts += _spandrel(x, y, sx, sy, ri, sign=1.0)
    props = _combine(parts, b, h)
    rm = ro - t / 2
    am = (b - t) * (h - t) - (4 - math.pi) * rm**2
    p = 2 * ((b - t) + (h - t)) - (8 - 2 * math.pi) * rm
    j = 4 * am**2 * t / p + p * t**3 / 3
    return _section(name, family, "rectangleHollow", (h, b, t, t, ro, 0.0), props, j, 0.0)


def chs_section(name: str, d: float, t: float) -> SteelSection:
    di = d - 2 * t
    a = math.pi / 4 * (d**2 - di**2)
    i = math.pi / 64 * (d**4 - di**4)
    s = 2 * i / d
    z = (d**3 - di**3) / 6
    props = _Props(a, d / 2, d / 2, i, i, 0.0, s, s, z, z)
    return _section(name, "CHS", "circleHollow", (d, d, t, t, 0.0, 0.0), props, 2 * i, 0.0)


def bar_section(name: str, h: float, b: float) -> SteelSection:
    """A solid rectangular bar (flat or square), depth ``h`` and width ``b`` (B31: steel members
    of a rectangle profile). J of a solid rectangle (long side a, short side c): a c³ (1/3 -
    0.21 c/a (1 - c⁴ / (12 a⁴))); Cw taken as 0 (negligible for a solid section)."""
    props = _combine([_rect(0, b, 0, h)], b, h)
    a, c = max(h, b), min(h, b)
    j = a * c**3 * (1 / 3 - 0.21 * c / a * (1 - c**4 / (12 * a**4)))
    return _section(name, "bar", "rectangle", (h, b, b, h, 0.0, 0.0), props, j, 0.0)


def round_section(name: str, d: float) -> SteelSection:
    """A solid round bar of diameter ``d`` (B31: steel members of a circle profile)."""
    a = math.pi / 4 * d**2
    i = math.pi / 64 * d**4
    s = 2 * i / d
    z = d**3 / 6
    props = _Props(a, d / 2, d / 2, i, i, 0.0, s, s, z, z)
    return _section(name, "round", "circle", (d, d, d, d, 0.0, 0.0), props, 2 * i, 0.0)


# ─────────────────────────────────────── the table ───────────────────────────────────────


def _density() -> float:
    """Mass density of the steel [kg/m³] (the table's ``density``)."""
    return code_context.pack_table("steelSections").density


def _fmt(x: float) -> str:
    return f"{x:g}"


def _walls(walls: Any, size: float) -> list[float]:
    """Walls rolled for a hollow section whose smaller side (or diameter) is ``size``: those
    with size / t within the table's ratios (boxes: b/t from 8 to 40, tubes: d/t 10 to 50)."""
    return [t for t in walls.walls if walls.minRatio <= size / t <= walls.maxRatio]


def _sections(t: Any) -> tuple[SteelSection, ...]:
    """Every section of table ``t``, by family then ascending mass."""
    out: list[SteelSection] = []
    for fam, rolled in t.rolled.items():
        make = i_section if rolled.shape == "I" else channel_section
        out += [
            make(f"{fam} {_fmt(r.designation)}", fam, r.h, r.b, r.tw, r.tf, r.r)
            for r in rolled.sections
        ]
    share = t.angles.toeRadiusShare
    out += [
        angle_section(f"L {a.leg}x{a.leg}x{_fmt(a.t)}", a.leg, a.leg, a.t, a.r1, a.r1 * share)
        for a in t.angles.sections
    ]
    hollow = t.hollow
    for size in hollow.shs:
        out += [
            rhs_section(f"SHS {size}x{size}x{_fmt(w)}", "SHS", size, size, w)
            for w in _walls(hollow.boxWalls, size)
        ]
    for box in hollow.rhs:
        h, b = box.h, box.b
        out += [
            rhs_section(f"RHS {h}x{b}x{_fmt(w)}", "RHS", h, b, w)
            for w in _walls(hollow.boxWalls, b)
        ]
    for d in hollow.chs:
        out += [chs_section(f"CHS {_fmt(d)}x{_fmt(w)}", d, w) for w in _walls(hollow.chsWalls, d)]
    order = {f: i for i, f in enumerate(t.families)}
    return tuple(sorted(out, key=lambda s: (order[s.family], s.mass, s.h)))


def _build(t: Any) -> dict[str, Any]:
    return {
        "STEEL_DENSITY": t.density,
        #: Families in the table, in the order the workbench lists them.
        "FAMILIES": tuple(t.families),
        #: The families a member of each profile shape can be redesigned into.
        "SHAPE_FAMILIES": {k: tuple(v) for k, v in t.shapeFamilies.items()},
        "NOTES": list(t.notes),
        "SECTIONS": _sections(t),
    }


_names = code_context.TableNames("steelSections", _build)


def __getattr__(name: str) -> Any:
    return _names.get(name, __name__)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_names()))


def section_table() -> tuple[SteelSection, ...]:
    """Every section of the table, by family then ascending mass."""
    return _names()["SECTIONS"]


def family(name: str) -> list[SteelSection]:
    """The sections of a family, lightest first."""
    return [s for s in section_table() if s.family == name]


def find(name: str) -> SteelSection | None:
    key = " ".join(name.upper().replace("×", "x").split())
    for s in section_table():
        if s.name.upper() == key:
            return s
    return None


def families_for(profile: o.Profile | dict[str, Any]) -> tuple[str, ...]:
    """The families a member of this profile shape can be redesigned into (its own first)."""
    shape = profile["shape"] if isinstance(profile, dict) else profile.shape
    own = family_of(profile)
    base = _names()["SHAPE_FAMILIES"].get(shape, ())
    return tuple(dict.fromkeys(([own] if own else []) + list(base)))


def _dims_of(profile: o.Profile | dict[str, Any]) -> tuple[str, tuple[float, ...]]:
    p = profile if isinstance(profile, dict) else profile.model_dump()
    shape = p["shape"]
    if shape == "I":
        return shape, (
            p["overallDepth"],
            p["overallWidth"],
            p["webThickness"],
            p["flangeThickness"],
        )
    if shape == "U":
        return shape, (p["depth"], p["flangeWidth"], p["webThickness"], p["flangeThickness"])
    if shape == "L":
        return shape, (p["depth"], p["width"], p["thickness"])
    if shape == "rectangleHollow":
        return shape, (p["yDim"], p["xDim"], p["wallThickness"])
    if shape == "circleHollow":
        return shape, (2 * p["radius"], p["wallThickness"])
    return shape, ()


def _dims_of_section(s: SteelSection) -> tuple[float, ...]:
    if s.shape in ("I", "U"):
        return (s.h, s.b, s.tw, s.tf)
    if s.shape == "L":
        return (s.h, s.b, s.tw)
    if s.shape == "rectangleHollow":
        return (s.h, s.b, s.tw)
    return (s.h, s.tw)


#: Which of the matched dimensions are plate thicknesses (matched to ``THICKNESS_TOL``).
_THICKNESS_INDEX = {
    "I": (2, 3),
    "U": (2, 3),
    "L": (2,),
    "rectangleHollow": (2,),
    "circleHollow": (1,),
}
#: Thickness tolerance [mm]: the table's walls differ by 0.5 mm (2.5 and 3.0), so a 3.0 mm
#: wall must not match the 2.5 mm section.
THICKNESS_TOL = 0.1


def _deviation(shape: str, dims: tuple[float, ...], mine: tuple[float, ...], tol: float) -> float:
    """The largest deviation relative to its tolerance (<= 1 matches), inf when they differ."""
    thick = _THICKNESS_INDEX.get(shape, ())
    worst = 0.0
    for i, (a, b) in enumerate(zip(dims, mine, strict=True)):
        limit = min(tol, THICKNESS_TOL) if i in thick else tol
        d = abs(a - b) / limit if limit > 0 else (0.0 if a == b else math.inf)
        worst = max(worst, d)
    return worst


def _match(profile: o.Profile | dict[str, Any], tol: float) -> tuple[SteelSection, bool] | None:
    """The closest table section within tolerance and whether the profile is it turned 90°
    (an RHS lying on its side)."""
    shape, dims = _dims_of(profile)
    if not dims:
        return None
    best: tuple[float, SteelSection, bool] | None = None
    for s in section_table():
        if s.shape != shape:
            continue
        mine = _dims_of_section(s)
        candidates = [(dims, False)]
        if shape == "rectangleHollow" and s.h != s.b:
            candidates.append(((dims[1], dims[0], dims[2]), True))
        for c, turned in candidates:
            d = _deviation(shape, c, mine, tol)
            if d <= 1.0 and (best is None or d < best[0]):
                best = (d, s, turned)
    return None if best is None else (best[1], best[2])


def match(profile: o.Profile | dict[str, Any], tol: float = 0.6) -> SteelSection | None:
    """The table section with these dimensions, if any: the closest within ``tol`` mm on the
    overall dimensions and :data:`THICKNESS_TOL` on the plate thicknesses. An RHS also matches
    turned on its side; this returns the table (upright) section, its identity:
    :func:`section_of_profile` gives the properties in the profile's own axes."""
    found = _match(profile, tol)
    return None if found is None else found[0]


def is_turned(profile: o.Profile | dict[str, Any]) -> bool:
    """Whether an RHS profile lies on its side: wider (xDim) than deep (yDim)."""
    p = profile if isinstance(profile, dict) else profile.model_dump()
    return p.get("shape") == "rectangleHollow" and p["xDim"] > p["yDim"] + 1e-9


def turn(s: SteelSection) -> SteelSection:
    """An RHS turned 90° (its h and b, and its x and y properties, swapped). Turning a turned
    section gives back the table's. Other shapes are returned as they are (their profiles have
    no orientation of their own: a rotated member is the element's local axes)."""
    if s.shape != "rectangleHollow" or s.h == s.b:
        return s
    t = rhs_section(s.name, s.family, s.b, s.h, s.tw, s.r)
    return replace(t, turned=not s.turned, extra=dict(s.extra))


def oriented(s: SteelSection, like: o.Profile | dict[str, Any]) -> SteelSection:
    """The table section ``s`` in the orientation of the profile ``like`` (an RHS lying on its
    side when ``like`` does)."""
    return turn(s) if is_turned(like) != s.turned else s


def family_of(profile: o.Profile | dict[str, Any]) -> str | None:
    """The family of a profile: its table section's, or by its shape (square boxes SHS)."""
    s = match(profile)
    if s is not None:
        return s.family
    shape, dims = _dims_of(profile)
    if shape == "rectangleHollow":
        return "SHS" if abs(dims[0] - dims[1]) < 0.6 else "RHS"
    fams = _names()["SHAPE_FAMILIES"].get(shape)
    return fams[0] if fams else None


def profile_of(s: SteelSection) -> dict[str, Any]:
    """The 04 Objects profile of a table section (validated by the objects' models)."""
    match s.shape:
        case "I":
            data: dict[str, Any] = {
                "shape": "I",
                "overallWidth": s.b,
                "overallDepth": s.h,
                "webThickness": s.tw,
                "flangeThickness": s.tf,
                "filletRadius": s.r,
            }
        case "U":
            data = {
                "shape": "U",
                "depth": s.h,
                "flangeWidth": s.b,
                "webThickness": s.tw,
                "flangeThickness": s.tf,
                "filletRadius": s.r,
            }
        case "L":
            data = {
                "shape": "L",
                "depth": s.h,
                "width": s.b,
                "thickness": s.tw,
                "filletRadius": s.r,
                "edgeRadius": s.r2,
            }
        case "rectangleHollow":
            data = {
                "shape": "rectangleHollow",
                "xDim": s.b,
                "yDim": s.h,
                "wallThickness": s.tw,
                "outerFilletRadius": s.r,
            }
        case _:
            data = {"shape": "circleHollow", "radius": s.h / 2, "wallThickness": s.tw}
    # Validate against 04 Objects' own profile models.
    from pydantic import TypeAdapter

    TypeAdapter(o.Profile).validate_python(data)
    return data


def section_of_profile(profile: o.Profile | dict[str, Any]) -> SteelSection:
    """Table-format properties for any steel profile, in the profile's own axes (x horizontal):
    the table's section when it matches (an RHS lying on its side turned, ``turned`` True),
    else computed from the profile's own dimensions (fillets as given)."""
    found = _match(profile, 0.6)
    if found is not None:
        s, turned = found
        return turn(s) if turned else s
    p = profile if isinstance(profile, dict) else profile.model_dump()
    name = "custom"
    match p["shape"]:
        case "I":
            return i_section(
                name,
                "I",
                p["overallDepth"],
                p["overallWidth"],
                p["webThickness"],
                p["flangeThickness"],
                p.get("filletRadius", 0) or 0,
            )
        case "U":
            return channel_section(
                name,
                "U",
                p["depth"],
                p["flangeWidth"],
                p["webThickness"],
                p["flangeThickness"],
                p.get("filletRadius", 0) or 0,
            )
        case "T":
            return tee_section(
                name,
                "T",
                p["depth"],
                p["flangeWidth"],
                p["webThickness"],
                p["flangeThickness"],
                p.get("filletRadius", 0) or 0,
            )
        case "L":
            return angle_section(
                name,
                p["depth"],
                p["width"],
                p["thickness"],
                p.get("filletRadius", 0) or 0,
                p.get("edgeRadius", 0) or 0,
            )
        case "rectangleHollow":
            fam = "SHS" if abs(p["xDim"] - p["yDim"]) < 0.6 else "RHS"
            s = rhs_section(
                name,
                fam,
                p["yDim"],
                p["xDim"],
                p["wallThickness"],
                p.get("outerFilletRadius", 0) or 0,
            )
            return replace(s, turned=is_turned(p))
        case "circleHollow":
            return chs_section(name, 2 * p["radius"], p["wallThickness"])
    raise TypeError(f"not a steel profile: {p['shape']}")


def mass_per_metre(profile: o.Profile | dict[str, Any], density: float | None = None) -> float:
    """The steel weight of a member of ``profile`` [kg/m], as the bill of quantities and the
    design report give it: the nominal area of :func:`section_of_profile` (with its fillets
    and corner radii) × ``density`` [kg/m³], rounded to 1 g. Raises ``TypeError`` for a
    profile that is not a steel shape. ``density`` defaults to the table's."""
    if density is None:
        density = _density()
    return round(section_of_profile(profile).A * 1e-6 * density, 3)


def lightest(
    candidates: Iterable[SteelSection], passes: Callable[[SteelSection], bool]
) -> SteelSection | None:
    """The lightest of ``candidates`` for which ``passes`` holds (by mass, then depth)."""
    for s in sorted(candidates, key=lambda s: (s.mass, s.h)):
        if passes(s):
            return s
    return None


def table_json() -> dict[str, Any]:
    """The table for the workbench / RPC: ``{"families", "sections": [...]}``."""
    return {
        "families": list(_names()["FAMILIES"]),
        "sections": [s.as_dict() for s in section_table()],
        "notes": list(_names()["NOTES"]),
    }

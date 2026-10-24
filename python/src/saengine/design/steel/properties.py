"""Section properties of rolled and hollow steel shapes for member design, in closed form.

The profiles are the object library's IFC-style ones (:mod:`saengine.library.objects`); the
design needs more than the analysis does (plastic moduli Z, warping constant Cw, shear centre,
flat widths of the walls), and a design-mode search over a section table needs them fast, so
they are worked out here from the plates the shape is made of rather than meshed
(:func:`saengine.library.sections.section_properties` meshes them for the analysis; the two agree
to the fillets).

Assumptions (stated in the design notes):

- Fillets and corner radii are left out of A, I, S and Z (a few per cent on the safe side for
  rolled I-shapes); they do shorten the flat widths used for local buckling (BNBC 2020 Part 6
  Sec 10.2.4.2(a), (d)).
- Hollow sections use the design wall thickness of Sec 10.2.3.12: 0.93 t for electric-
  resistance-welded (ERW) HSS (the default: cold-formed ERW tubes are what the market sells),
  the nominal t for submerged-arc-welded (SAW) HSS.
- St. Venant J of open shapes: Σ b t³ / 3 over the plates (flange widths, web clear of the
  flanges); of closed tubes: Bredt's 4 A0² t / p on the wall centreline. Cw: I-shapes
  tf bf³ ho² / 24, channels the thin-walled formula with the shear centre at e0 from the web,
  tees and angles 0 (their warping stiffness is negligible).

Axes follow the profile: x along its width (horizontal), y along its depth (vertical), so ``ix``
is the major-axis inertia of an I-shape. Units: mm, mm², mm⁴, mm⁶.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from saengine.library import objects as o

#: Design wall thickness of ERW hollow sections, BNBC 2020 Part 6 Sec 10.2.3.12 (p 3824).
ERW_FACTOR = 0.93

Rect = tuple[float, float, float, float]  # x0, x1, y0, y1


@dataclass(frozen=True)
class ShapeProperties:
    """What the member checks need of a steel shape."""

    family: str  # "I", "channel", "tee", "angle", "rhs", "chs"
    label: str
    area: float
    ix: float  # about the horizontal (x) centroidal axis
    iy: float  # about the vertical (y) centroidal axis
    sx: float  # least elastic modulus about x
    sy: float  # least elastic modulus about y
    zx: float  # plastic moduli
    zy: float
    j: float
    cw: float
    x0: float = 0.0  # shear centre relative to the centroid
    y0: float = 0.0
    #: The plate dimensions of the shape (design wall thickness for HSS): d, bf, tf, tw, h
    #: (clear web depth less fillets), r; HSS: b (flat flange width), h (flat web height), t,
    #: B, H; CHS: D, t; angle: legs d (vertical), b (horizontal), t.
    dims: dict[str, float] = field(default_factory=dict)
    #: Elastic moduli to the top and bottom fibres about x (tees, which are not symmetric).
    sx_top: float = 0.0
    sx_bottom: float = 0.0
    #: Angles: least principal inertia and radius.
    iz: float = 0.0
    notes: tuple[str, ...] = ()

    @property
    def rx(self) -> float:
        return math.sqrt(self.ix / self.area)

    @property
    def ry(self) -> float:
        return math.sqrt(self.iy / self.area)

    @property
    def rz(self) -> float:
        return math.sqrt(self.iz / self.area) if self.iz > 0 else min(self.rx, self.ry)

    @property
    def ro2(self) -> float:
        """r̄o², the polar radius of gyration about the shear centre squared (Eq 6.10.26)."""
        return self.x0**2 + self.y0**2 + (self.ix + self.iy) / self.area

    @property
    def big_h(self) -> float:
        """H of Eq 6.10.27."""
        return 1 - (self.x0**2 + self.y0**2) / self.ro2


# ───────────────────────────────── plate assemblies ─────────────────────────────────


def _area(rects: list[Rect]) -> float:
    return sum((x1 - x0) * (y1 - y0) for x0, x1, y0, y1 in rects)


def _centroid(rects: list[Rect]) -> tuple[float, float]:
    a = _area(rects)
    cx = sum((x1 - x0) * (y1 - y0) * (x0 + x1) / 2 for x0, x1, y0, y1 in rects) / a
    cy = sum((x1 - x0) * (y1 - y0) * (y0 + y1) / 2 for x0, x1, y0, y1 in rects) / a
    return cx, cy


def _inertia(rects: list[Rect]) -> tuple[float, float, float]:
    """Ix, Iy, Ixy about the centroid."""
    cx, cy = _centroid(rects)
    ix = iy = ixy = 0.0
    for x0, x1, y0, y1 in rects:
        b, h = x1 - x0, y1 - y0
        a = b * h
        dx, dy = (x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy
        ix += b * h**3 / 12 + a * dy**2
        iy += h * b**3 / 12 + a * dx**2
        ixy += a * dx * dy
    return ix, iy, ixy


def _plastic(rects: list[Rect], axis: str) -> float:
    """Plastic modulus about the horizontal (``axis`` "x") or vertical equal-area axis."""
    lo_i, hi_i = (2, 3) if axis == "x" else (0, 1)
    spans = [(r[lo_i], r[hi_i], (r[1] - r[0]) * (r[3] - r[2]) / (r[hi_i] - r[lo_i])) for r in rects]
    total = sum((hi - lo) * w for lo, hi, w in spans)

    def below(c: float) -> float:
        return sum(max(0.0, min(hi, c) - lo) * w for lo, hi, w in spans)

    lo = min(s[0] for s in spans)
    hi = max(s[1] for s in spans)
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if below(mid) < total / 2 else (lo, mid)
    c = (lo + hi) / 2
    z = 0.0
    for a, b, w in spans:
        # ∫ |s - c| w ds over [a, b]
        if b <= c:
            z += w * ((c - a) ** 2 - (c - b) ** 2) / 2
        elif a >= c:
            z += w * ((b - c) ** 2 - (a - c) ** 2) / 2
        else:
            z += w * ((c - a) ** 2 + (b - c) ** 2) / 2
    return z


def _assembly(rects: list[Rect]) -> dict[str, float]:
    a = _area(rects)
    cx, cy = _centroid(rects)
    ix, iy, ixy = _inertia(rects)
    xmin, xmax = min(r[0] for r in rects), max(r[1] for r in rects)
    ymin, ymax = min(r[2] for r in rects), max(r[3] for r in rects)
    return {
        "A": a,
        "cx": cx,
        "cy": cy,
        "Ix": ix,
        "Iy": iy,
        "Ixy": ixy,
        "Sx_top": ix / (ymax - cy),
        "Sx_bottom": ix / (cy - ymin),
        "Sy": iy / max(xmax - cx, cx - xmin),
        "Zx": _plastic(rects, "x"),
        "Zy": _plastic(rects, "y"),
    }


# ───────────────────────────────────── shapes ─────────────────────────────────────


def i_shape(
    d: float, bf: float, tf: float, tw: float, r: float = 0.0, label: str = ""
) -> ShapeProperties:
    """A doubly symmetric rolled I-shape (W, UB/UC, IPE, HEA/HEB)."""
    rects = [
        (-bf / 2, bf / 2, 0.0, tf),
        (-tw / 2, tw / 2, tf, d - tf),
        (-bf / 2, bf / 2, d - tf, d),
    ]
    p = _assembly(rects)
    ho = d - tf
    sx = min(p["Sx_top"], p["Sx_bottom"])
    return ShapeProperties(
        family="I",
        label=label or f"I {d:g}x{bf:g}x{tw:g}/{tf:g}",
        area=p["A"],
        ix=p["Ix"],
        iy=p["Iy"],
        sx=sx,
        sy=p["Sy"],
        zx=p["Zx"],
        zy=p["Zy"],
        j=(2 * bf * tf**3 + (d - 2 * tf) * tw**3) / 3,
        cw=tf * bf**3 * ho**2 / 24,
        dims={"d": d, "bf": bf, "tf": tf, "tw": tw, "h": d - 2 * tf - 2 * r, "r": r, "ho": ho},
        sx_top=p["Sx_top"],
        sx_bottom=p["Sx_bottom"],
    )


def channel(
    d: float, bf: float, tf: float, tw: float, r: float = 0.0, label: str = ""
) -> ShapeProperties:
    """A channel, web at the left (x = 0), symmetric about its horizontal axis."""
    rects = [
        (0.0, bf, 0.0, tf),
        (0.0, tw, tf, d - tf),
        (0.0, bf, d - tf, d),
    ]
    p = _assembly(rects)
    ho = d - tf
    b1 = bf - tw / 2  # flange width to the web centreline
    e0 = 3 * b1**2 * tf / (6 * b1 * tf + ho * tw)  # shear centre from the web centreline
    cw = tf * b1**3 * ho**2 / 12 * (3 * b1 * tf + 2 * ho * tw) / (6 * b1 * tf + ho * tw)
    x0 = -(e0 + (p["cx"] - tw / 2))  # the shear centre lies behind the web
    return ShapeProperties(
        family="channel",
        label=label or f"C {d:g}x{bf:g}x{tw:g}/{tf:g}",
        area=p["A"],
        ix=p["Ix"],
        iy=p["Iy"],
        sx=min(p["Sx_top"], p["Sx_bottom"]),
        sy=p["Sy"],
        zx=p["Zx"],
        zy=p["Zy"],
        j=(2 * bf * tf**3 + (d - 2 * tf) * tw**3) / 3,
        cw=cw,
        x0=x0,
        dims={"d": d, "bf": bf, "tf": tf, "tw": tw, "h": d - 2 * tf - 2 * r, "r": r, "ho": ho},
        sx_top=p["Sx_top"],
        sx_bottom=p["Sx_bottom"],
    )


def tee(
    d: float, bf: float, tf: float, tw: float, r: float = 0.0, label: str = ""
) -> ShapeProperties:
    """A tee, flange at the top, stem tip at y = 0."""
    rects = [(-tw / 2, tw / 2, 0.0, d - tf), (-bf / 2, bf / 2, d - tf, d)]
    p = _assembly(rects)
    y0 = (d - tf / 2) - p["cy"]  # shear centre at the flange centreline
    return ShapeProperties(
        family="tee",
        label=label or f"T {d:g}x{bf:g}x{tw:g}/{tf:g}",
        area=p["A"],
        ix=p["Ix"],
        iy=p["Iy"],
        sx=min(p["Sx_top"], p["Sx_bottom"]),
        sy=p["Sy"],
        zx=p["Zx"],
        zy=p["Zy"],
        j=(bf * tf**3 + (d - tf / 2) * tw**3) / 3,
        cw=0.0,
        y0=y0,
        dims={"d": d, "bf": bf, "tf": tf, "tw": tw, "r": r},
        sx_top=p["Sx_top"],
        sx_bottom=p["Sx_bottom"],
    )


def angle(d: float, b: float, t: float, label: str = "") -> ShapeProperties:
    """An angle, heel at the origin: leg ``d`` vertical, leg ``b`` horizontal."""
    rects = [(0.0, t, 0.0, d), (t, b, 0.0, t)]
    p = _assembly(rects)
    mean = (p["Ix"] + p["Iy"]) / 2
    radius = math.hypot((p["Ix"] - p["Iy"]) / 2, p["Ixy"])
    return ShapeProperties(
        family="angle",
        label=label or f"L {d:g}x{b:g}x{t:g}",
        area=p["A"],
        ix=p["Ix"],
        iy=p["Iy"],
        sx=min(p["Sx_top"], p["Sx_bottom"]),
        sy=p["Sy"],
        zx=p["Zx"],
        zy=p["Zy"],
        j=(d + b - t) * t**3 / 3,
        cw=0.0,
        x0=t / 2 - p["cx"],
        y0=t / 2 - p["cy"],
        dims={"d": d, "b": b, "t": t, "cx": p["cx"], "cy": p["cy"]},
        sx_top=p["Sx_top"],
        sx_bottom=p["Sx_bottom"],
        iz=mean - radius,
    )


def rhs(
    big_b: float, big_h: float, t: float, r_out: float = 0.0, label: str = ""
) -> ShapeProperties:
    """A square or rectangular hollow section ``big_b`` wide and ``big_h`` deep, wall ``t``
    (the design wall thickness)."""
    rects = [
        (-big_b / 2, big_b / 2, -big_h / 2, -big_h / 2 + t),
        (-big_b / 2, big_b / 2, big_h / 2 - t, big_h / 2),
        (-big_b / 2, -big_b / 2 + t, -big_h / 2 + t, big_h / 2 - t),
        (big_b / 2 - t, big_b / 2, -big_h / 2 + t, big_h / 2 - t),
    ]
    p = _assembly(rects)
    # Flat widths, Sec 10.2.4.2(d): less the inside corner radius each side, or 3 t when the
    # radius is not known.
    inside = r_out - t if r_out > t else None
    flat_b = big_b - 2 * t - 2 * inside if inside is not None else big_b - 3 * t
    flat_h = big_h - 2 * t - 2 * inside if inside is not None else big_h - 3 * t
    a0 = (big_b - t) * (big_h - t)
    perimeter = 2 * ((big_b - t) + (big_h - t))
    return ShapeProperties(
        family="rhs",
        label=label or f"RHS {big_h:g}x{big_b:g}x{t:g}",
        area=p["A"],
        ix=p["Ix"],
        iy=p["Iy"],
        sx=min(p["Sx_top"], p["Sx_bottom"]),
        sy=p["Sy"],
        zx=p["Zx"],
        zy=p["Zy"],
        j=4 * a0**2 * t / perimeter,
        cw=0.0,
        dims={"B": big_b, "H": big_h, "t": t, "b": flat_b, "h": flat_h},
        sx_top=p["Sx_top"],
        sx_bottom=p["Sx_bottom"],
    )


def chs(diameter: float, t: float, label: str = "") -> ShapeProperties:
    """A circular hollow section of outside diameter ``diameter`` and wall ``t``."""
    inner = diameter - 2 * t
    area = math.pi / 4 * (diameter**2 - inner**2)
    i = math.pi / 64 * (diameter**4 - inner**4)
    s = i / (diameter / 2)
    z = (diameter**3 - inner**3) / 6
    return ShapeProperties(
        family="chs",
        label=label or f"CHS {diameter:g}x{t:g}",
        area=area,
        ix=i,
        iy=i,
        sx=s,
        sy=s,
        zx=z,
        zy=z,
        j=2 * i,
        cw=0.0,
        dims={"D": diameter, "t": t},
        sx_top=s,
        sx_bottom=s,
    )


def shape_properties(profile: o.Profile, erw: bool = True) -> ShapeProperties:
    """The steel shape of an object profile; ``erw``: hollow sections are ERW (design wall
    thickness 0.93 t, Sec 10.2.3.12), else SAW (nominal t). Raises ``ValueError`` for profiles
    that are not steel shapes (solid rectangles and circles)."""
    factor = ERW_FACTOR if erw else 1.0
    match profile:
        case o.IShapeProfile():
            return i_shape(
                profile.overallDepth,
                profile.overallWidth,
                profile.flangeThickness,
                profile.webThickness,
                profile.filletRadius,
            )
        case o.UShapeProfile():
            return channel(
                profile.depth,
                profile.flangeWidth,
                profile.flangeThickness,
                profile.webThickness,
                profile.filletRadius,
            )
        case o.TShapeProfile():
            return tee(
                profile.depth,
                profile.flangeWidth,
                profile.flangeThickness,
                profile.webThickness,
                profile.filletRadius,
            )
        case o.LShapeProfile():
            return angle(profile.depth, profile.width, profile.thickness)
        case o.RectangleHollowProfile():
            t = profile.wallThickness * factor
            shape = rhs(profile.xDim, profile.yDim, t, profile.outerFilletRadius)
            return _with_note(shape, factor, profile.wallThickness)
        case o.CircleHollowProfile():
            t = profile.wallThickness * factor
            shape = chs(2 * profile.radius, t)
            return _with_note(shape, factor, profile.wallThickness)
    raise ValueError(f"a {profile.shape} profile is not a steel shape")


def _with_note(shape: ShapeProperties, factor: float, nominal: float) -> ShapeProperties:
    if factor == 1.0:
        return shape
    note = (
        f"design wall thickness t = 0.93 × {nominal:g} = {nominal * factor:.2f} mm (ERW HSS, "
        "BNBC 2020 Part 6 Sec 10.2.3.12)"
    )
    return ShapeProperties(**{**shape.__dict__, "notes": (*shape.notes, note)})

"""Section properties of rolled and hollow steel shapes for member design: an adapter over
:mod:`saengine.library.steel_sections`.

The profiles are the object library's IFC-style ones (:mod:`saengine.library.objects`). A, I, S
and Z are those of the section table's engine (:mod:`saengine.library.steel_sections`, the one
place they are computed), taken without fillets and corner radii; what the member design adds
is here: the design wall thickness of hollow sections, the torsion and warping constants of the
design, the shear centre, the plate dimensions for local buckling and the notes
(:func:`saengine.library.sections.section_properties` meshes the shapes for the analysis; the
two agree to the fillets).

Assumptions (stated in the design notes):

- Fillets and corner radii are left out of A, I, S and Z (a few per cent on the safe side for
  rolled I-shapes); they do shorten the flat widths used for local buckling (default pack BNBC 2020 Part 6
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

import itertools
import math
from dataclasses import dataclass, field

from saengine.design.clauses import clause, limits
from saengine.library import objects as o
from saengine.library import steel_sections as tables


def _erw_factor() -> float:
    """Design wall thickness of ERW hollow sections over the nominal, the pack's
    ``designLimits.erwWallFactor`` (the default pack: 0.93, Sec 10.2.3.12)."""
    return float(limits().erwWallFactor)


def __getattr__(name: str) -> float:
    if name == "ERW_FACTOR":
        return _erw_factor()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass(frozen=True)
class ShapeProperties:
    """What the member checks need of a steel shape."""

    family: str  # "I", "channel", "tee", "angle", "rhs", "chs", "bar", "round"
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
    #: Angles: the product of inertia about the centroidal x and y axes (B31, principal axes).
    ixy: float = 0.0

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


def _assembly(section: tables.SteelSection) -> dict[str, float]:
    """A, centroid, I, S and Z of a table-engine section (built without fillets): x across
    its width from its left edge, y up its depth from its bottom edge."""
    return {
        "A": section.A,
        "cx": section.cx,
        "cy": section.cy,
        "Ix": section.Ix,
        "Iy": section.Iy,
        "Sx_top": section.Ix / (section.h - section.cy),
        "Sx_bottom": section.Ix / section.cy,
        "Sy": section.Sy,
        "Zx": section.Zx,
        "Zy": section.Zy,
    }


# ───────────────────────────────────── shapes ─────────────────────────────────────


def i_shape(
    d: float, bf: float, tf: float, tw: float, r: float = 0.0, label: str = ""
) -> ShapeProperties:
    """A doubly symmetric rolled I-shape (W, UB/UC, IPE, HEA/HEB)."""
    p = _assembly(tables.i_section("", "I", d, bf, tw, tf, 0.0))
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
    p = _assembly(tables.channel_section("", "U", d, bf, tw, tf, 0.0))
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
    p = _assembly(tables.tee_section("", "T", d, bf, tw, tf, 0.0))
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
    section = tables.angle_section("", d, b, t, 0.0, 0.0)
    p = _assembly(section)
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
        iz=section.Iv or 0.0,
        # Legs along +x and +y from the heel: the product of inertia is negative.
        ixy=-math.sqrt(
            max(
                0.0,
                ((section.Iu or 0.0) - (section.Iv or 0.0)) ** 2 / 4 - (p["Ix"] - p["Iy"]) ** 2 / 4,
            )
        ),
    )


def rhs(
    big_b: float, big_h: float, t: float, r_out: float = 0.0, label: str = ""
) -> ShapeProperties:
    """A square or rectangular hollow section ``big_b`` wide and ``big_h`` deep, wall ``t``
    (the design wall thickness)."""
    p = _assembly(tables.rhs_section("", "RHS", big_h, big_b, t, 0.0))
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
    section = tables.chs_section("", diameter, t)
    return ShapeProperties(
        family="chs",
        label=label or f"CHS {diameter:g}x{t:g}",
        area=section.A,
        ix=section.Ix,
        iy=section.Iy,
        sx=section.Sx,
        sy=section.Sy,
        zx=section.Zx,
        zy=section.Zy,
        j=section.J,
        cw=0.0,
        dims={"D": diameter, "t": t},
        sx_top=section.Sx,
        sx_bottom=section.Sx,
    )


def bar(depth: float, width: float, label: str = "") -> ShapeProperties:
    """A solid rectangular bar ``width`` wide (x) and ``depth`` deep (y) (B31)."""
    section = tables.bar_section("", depth, width)
    p = _assembly(section)
    return ShapeProperties(
        family="bar",
        label=label or f"FB {depth:g}x{width:g}",
        area=p["A"],
        ix=p["Ix"],
        iy=p["Iy"],
        sx=min(p["Sx_top"], p["Sx_bottom"]),
        sy=p["Sy"],
        zx=p["Zx"],
        zy=p["Zy"],
        j=section.J,
        cw=0.0,
        dims={"d": depth, "b": width},
        sx_top=p["Sx_top"],
        sx_bottom=p["Sx_bottom"],
    )


def round_bar(diameter: float, label: str = "") -> ShapeProperties:
    """A solid round bar of ``diameter`` (B31)."""
    section = tables.round_section("", diameter)
    return ShapeProperties(
        family="round",
        label=label or f"RD {diameter:g}",
        area=section.A,
        ix=section.Ix,
        iy=section.Iy,
        sx=section.Sx,
        sy=section.Sy,
        zx=section.Zx,
        zy=section.Zy,
        j=section.J,
        cw=0.0,
        dims={"D": diameter},
        sx_top=section.Sx,
        sx_bottom=section.Sx,
    )


# ─────────────────────────── cold-formed lipped sections (alpha 9 C12) ───────────────────────────


def thin_walled(points: list[tuple[float, float]], t: float) -> dict[str, float]:
    """Thin-walled properties of an open section of constant thickness ``t`` along the
    centreline polyline ``points``: A, the centroid, Ix, Iy, Ixy about it, the shear centre
    (x0, y0) from the centroid, J = Σ L t³ / 3 and Cw = ∫ ωn² dA by the sectorial coordinate
    about the shear centre (normalised)."""
    pts = [(float(x), float(y)) for x, y in points]
    segs = list(itertools.pairwise(pts))
    lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs]
    area = t * sum(lens)
    cx = sum(t * ln * (a[0] + b[0]) / 2 for (a, b), ln in zip(segs, lens, strict=True)) / area
    cy = sum(t * ln * (a[1] + b[1]) / 2 for (a, b), ln in zip(segs, lens, strict=True)) / area

    def integral(f: list[float], g: list[float]) -> float:
        # ∫ f g dA with f, g linear on each segment (node values).
        total = 0.0
        for i, ln in enumerate(lens):
            fa, fb, ga, gb = f[i], f[i + 1], g[i], g[i + 1]
            total += t * ln * (2 * fa * ga + fa * gb + fb * ga + 2 * fb * gb) / 6
        return total

    xs = [p[0] - cx for p in pts]
    ys = [p[1] - cy for p in pts]
    ix, iy, ixy = integral(ys, ys), integral(xs, xs), integral(xs, ys)

    def sectorial(px: float, py: float) -> list[float]:
        w = [0.0]
        for a, b in segs:
            w.append(w[-1] + (a[0] - px) * (b[1] - py) - (b[0] - px) * (a[1] - py))
        return w

    w0 = sectorial(cx, cy)
    iwx, iwy = integral(w0, xs), integral(w0, ys)
    det = ix * iy - ixy**2
    x0 = (iy * iwy - ixy * iwx) / det if det > 0 else 0.0
    y0 = (ixy * iwy - ix * iwx) / det if det > 0 else 0.0
    ws = sectorial(cx + x0, cy + y0)
    mean = integral(ws, [1.0] * len(ws)) / area
    wn = [w - mean for w in ws]
    return {
        "A": area, "cx": cx, "cy": cy, "Ix": ix, "Iy": iy, "Ixy": ixy, "x0": x0, "y0": y0,
        "J": sum(lens) * t**3 / 3, "Cw": integral(wn, wn), "wn": max(abs(w) for w in wn),
    }  # fmt: skip


def lipped(
    kind: str, h: float, b: float, c: float, t: float, r: float = 0.0, label: str = ""
) -> ShapeProperties:
    """A cold-formed lipped channel (``kind`` "C", web at the left, flanges to the right, lips
    turned in) or lipped Z ("Z", top flange to the right, bottom flange to the left), overall
    depth ``h``, flange width ``b``, lip ``c``, thickness ``t``, inside corner radius ``r``. A, I,
    S and Z of the square-cornered plates (the corners left out: a few per cent on the safe
    side); J, Cw and the shear centre on the centreline (thin-walled). Flat widths for the
    effective widths: the plate less t + r at each bend. Z: the geometric axes (x along the
    flanges), with the least principal inertia for buckling."""
    if c <= t or b <= 2 * t or h <= 2 * t:
        raise ValueError("a lipped section needs depth, width and lip larger than the thickness")
    if kind == "C":
        parts = [
            tables._rect(0, t, 0, h),
            tables._rect(t, b, h - t, h),
            tables._rect(t, b, 0, t),
            tables._rect(b - t, b, h - c, h - t),
            tables._rect(b - t, b, t, c),
        ]
        width = b
        line = [
            (b - t / 2, h - c), (b - t / 2, h - t / 2), (t / 2, h - t / 2), (t / 2, t / 2),
            (b - t / 2, t / 2), (b - t / 2, c),
        ]  # fmt: skip
        family = "lippedChannel"
    else:
        x_web = b - t
        parts = [
            tables._rect(x_web, b, 0, h),
            tables._rect(b, 2 * b - t, h - t, h),
            tables._rect(0, x_web, 0, t),
            tables._rect(2 * b - 2 * t, 2 * b - t, h - c, h - t),
            tables._rect(0, t, t, c),
        ]
        width = 2 * b - t
        xw = b - t / 2
        line = [
            (2 * b - 1.5 * t, h - c), (2 * b - 1.5 * t, h - t / 2), (xw, h - t / 2), (xw, t / 2),
            (t / 2, t / 2), (t / 2, c),
        ]  # fmt: skip
        family = "lippedZ"
    p = tables._combine(parts, width, h)
    tw = thin_walled(line, t)
    mean = (p.Ix + p.Iy) / 2
    radius = math.hypot((p.Ix - p.Iy) / 2, p.Ixy)
    bend = t + r
    return ShapeProperties(
        family=family,
        label=label or f"{kind} {h:g}x{b:g}x{c:g}x{t:g}",
        area=p.A,
        ix=p.Ix,
        iy=p.Iy,
        sx=p.Sx,
        sy=p.Sy,
        zx=p.Zx,
        zy=p.Zy,
        j=tw["J"],
        cw=tw["Cw"],
        x0=tw["x0"],
        y0=tw["y0"],
        dims={
            "d": h,
            "b": b,
            "c": c,
            "t": t,
            "r": r,
            "cx": p.cx,
            "cy": p.cy,
            "web": h - 2 * bend,
            "flange": b - 2 * bend,
            "lip": c - bend,
            "ho": h - t,
            "wn": tw["wn"],
        },
        sx_top=p.Ix / (h - p.cy),
        sx_bottom=p.Ix / p.cy,
        iz=mean - radius,
        ixy=p.Ixy,
        notes=(
            (
                "cold-formed section: the corners left out of A, I, S and Z; J, Cw and the shear "
                "centre on the centreline"
            ),
        ),
    )


def shape_properties(profile: o.Profile, erw: bool = True) -> ShapeProperties:
    """The steel shape of an object profile; ``erw``: hollow sections are ERW (design wall
    thickness 0.93 t, Sec 10.2.3.12), else SAW (nominal t). Solid rectangles and circles are
    rectangular bars and rounds (B31). Raises ``ValueError`` for profiles that are not steel
    shapes (a designed section)."""
    factor = _erw_factor() if erw else 1.0
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
        case o.RectangleProfile():
            return bar(profile.yDim, profile.xDim)
        case o.CircleProfile():
            return round_bar(2 * profile.radius)
        case o.CShapeProfile() | o.ZShapeProfile():  # alpha 9 C12: cold-formed
            return lipped(
                profile.shape,
                profile.depth,
                profile.width,
                profile.girth,
                profile.wallThickness,
                profile.internalFilletRadius,
            )
    raise ValueError(f"a {profile.shape} profile is not a steel shape")


def _with_note(shape: ShapeProperties, factor: float, nominal: float) -> ShapeProperties:
    if factor == 1.0:
        return shape
    note = (
        f"design wall thickness t = {factor:g} × {nominal:g} = {nominal * factor:.2f} mm (ERW HSS, "
        f"{clause('steelMembers', 'erw')})"
    )
    return ShapeProperties(**{**shape.__dict__, "notes": (*shape.notes, note)})

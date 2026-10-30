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
from saengine.library import steel_sections as tables

#: Design wall thickness of ERW hollow sections, BNBC 2020 Part 6 Sec 10.2.3.12 (p 3824).
ERW_FACTOR = 0.93


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

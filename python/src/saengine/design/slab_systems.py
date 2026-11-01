"""Ribbed and waffle slabs, drop panels and column capitals: the geometry the analysis and the
slab design (:mod:`saengine.design.slab`) take from a slab type's ``ribs``, ``dropPanel`` and
``capital`` (default pack BNBC 2020 Part 6 Chapter 6, which adopts the ACI 318 strength design; clauses below
by ACI 318-19 number where the default pack's (BNBC) own section was not checked).

Ribs (joist construction; ACI 318-19 9.8.1, the default pack's BNBC 2020 Part 6 joist construction, section and
page not checked). The slab's thickness is the topping; the ribs hang under it, ``width`` wide
and ``depth`` deep, at ``spacing`` centre to centre, along local x, local y, or both ways (a
waffle). Dimensional limits (ACI 318-19 9.8.1.1-9.8.1.4; ACI 318-11 8.13.2-8.13.3, 8.13.6.1):

- rib width at least 100 mm;
- rib depth (below the topping) at most 3.5 times the rib width;
- clear spacing between the ribs at most 750 mm (wider: designed as slab and beams, 9.8.1.4);
- topping at least 50 mm and at least 1/12 of the clear spacing.

Shear: Vc of the ribs may be taken 1.1 times the one-way shear strength (ACI 318-19 9.8.1.5,
ACI 318-11 8.13.8). The slab design takes the moments and shears per metre of width from the
shells as for a solid slab; in a rib direction the bars per metre sit in the ribs at the total
depth, compression of a hogging moment in the ribs' webs (``bw`` per metre: the web widths in a
metre), of a sagging moment in the topping (1 m wide; a compression block deeper than the
topping is flagged); one-way shear on the webs per metre times 1.1. Across a ribbed slab's ribs
(one-way ribs) the topping alone carries the moments, with its own depth.

Analysis. The shells take a solid plate with the ribs' bending stiffness: the thickness of a
solid slab with the same I per metre as the T-section of one rib with its share of topping (the
"equivalent thickness"), the membrane stiffness of the mean thickness (concrete volume over plan
area), and the weight of the mean thickness. A plate is isotropic, so a ribbed (one-way) slab's
plate is as stiff across the ribs as along them; the analysis notes it.

Drop panels (ACI 318-19 8.2.4; the default pack's BNBC 2020 Part 6 Sec 6.5, page not checked). A rectangle
``length`` x ``width`` in the column's axes under each column, ``depth`` below the soffit. It
counts as a drop panel when it projects at least h/4 below the slab and extends at least l/6 of
the centre-to-centre span each way from the column's centre line (8.2.4 (a), (b)); a slab with
drop panels then takes the minimum thickness of the default pack's BNBC Table 6.6.3 with drop panels (ACI Table
8.3.1.1), at least 100 mm (8.3.1.1 (b)). Over the panel the top bars work at the panel's depth,
taking no more of the projection than a quarter of the distance from the panel's edge to the
column's (or capital's) face (8.5.2.2). In the analysis the shells over the panel are thicker by
its depth.

Column capitals (ACI 318-11 13.1.2; ACI 318-19 2.3). A square flare ``size`` wide at the slab
(or at the drop panel's soffit), ``depth`` deep. Only the part inside a 90° pyramid from the
column counts: an effective size of min(size, c + 2 depth) each way. The column's effective
face for the clear span (ACI 318-19 8.10.3.2.1) and the first punching section (22.6.4.1) is
the effective capital's.

Punching with a drop panel (ACI 318-19 22.6.4.1: sections at d/2 from the column or capital
faces and from changes of thickness): one section at d/2 from the column (or capital) with d
through the panel, and one at d/2 outside the panel's edge with the slab's own d; both with the
column's Vu and unbalanced moments (the load inside the section is not deducted).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

#: ACI 318-19 9.8.1.1-9.8.1.3: least rib width, largest depth / width, largest clear spacing.
RIB_MIN_WIDTH = 100.0
RIB_DEPTH_RATIO = 3.5
RIB_MAX_CLEAR = 750.0
#: ACI 318-11 8.13.6.1: least topping, and topping / clear spacing.
TOPPING_MIN = 50.0
TOPPING_CLEAR_RATIO = 1 / 12
#: ACI 318-19 9.8.1.5: Vc of joist construction may be 1.1 times the one-way shear strength.
RIB_SHEAR_FACTOR = 1.1
#: ACI 318-19 8.2.4: a drop panel projects at least h/4 and extends at least l/6 each way.
DROP_DEPTH_RATIO = 0.25
DROP_EXTENT_RATIO = 1 / 6
#: ACI 318-19 8.3.1.1 (b): least thickness of a slab with drop panels.
DROP_MIN_THICKNESS = 100.0


@dataclass(frozen=True)
class RibSection:
    """A ribbed or waffle slab's section per metre width (mm)."""

    topping: float
    width: float  # rib web
    depth: float  # below the topping
    spacing: float  # centre to centre
    direction: str  # "x", "y" or "both"

    @property
    def total(self) -> float:
        """Total depth: topping plus rib."""
        return self.topping + self.depth

    @property
    def clear(self) -> float:
        """Clear spacing between the ribs."""
        return self.spacing - self.width

    @property
    def web_per_metre(self) -> float:
        """Width of the ribs' webs in one metre [mm/m]."""
        return self.width * 1000 / self.spacing

    @property
    def directions(self) -> tuple[str, ...]:
        """The reinforcement directions (``"X"``, ``"Y"``) with ribs."""
        return ("X", "Y") if self.direction == "both" else (self.direction.upper(),)

    @property
    def mean_thickness(self) -> float:
        """Concrete volume per plan area [mm]: the topping and the ribs (each way, less the
        crossings of a waffle's ribs counted once)."""
        share = self.width / self.spacing
        ribs = share if self.direction != "both" else 2 * share - share**2
        return self.topping + self.depth * ribs

    def inertia_per_metre(self) -> float:
        """I [mm⁴/m] of one rib's T-section (flange: the topping ``spacing`` wide) per metre,
        about its own centroid."""
        s, t, bw, d = self.spacing, self.topping, self.width, self.depth
        flange, web = s * t, bw * d
        y = (flange * t / 2 + web * (t + d / 2)) / (flange + web)  # from the top
        i = s * t**3 / 12 + flange * (y - t / 2) ** 2 + bw * d**3 / 12 + web * (t + d / 2 - y) ** 2
        return i * 1000 / s

    @property
    def bending_thickness(self) -> float:
        """Thickness of a solid slab with the same I per metre ((12 I / 1000)^(1/3))."""
        return (12 * self.inertia_per_metre() / 1000) ** (1 / 3)


def rib_section(topping: float, ribs: Any) -> RibSection:
    """The :class:`RibSection` of a slab type's ``ribs`` (``objects.SlabRibs``) under a topping
    ``topping`` mm thick."""
    return RibSection(
        float(topping), float(ribs.width), float(ribs.depth), float(ribs.spacing), ribs.direction
    )


def analysis_thicknesses(slab_type: Any) -> tuple[float, float, float]:
    """(bending, membrane, weight) thickness [mm] of a slab type's analysis plate: all the
    thickness for a solid slab; for ribs the equivalent bending thickness, and the mean
    thickness for the membrane stiffness and the weight."""
    h = float(slab_type.thickness)
    ribs = getattr(slab_type, "ribs", None)
    if ribs is None:
        return h, h, h
    section = rib_section(h, ribs)
    mean = section.mean_thickness
    return section.bending_thickness, mean, mean


def weight_thickness(slab_type: Any) -> float:
    """Thickness [mm] whose weight is the slab type's self-weight per plan area (without drop
    panels and capitals, which are added at the columns)."""
    return analysis_thicknesses(slab_type)[2]


def design_depth(slab_type: Any) -> float:
    """The depth [mm] the slab's bars work in: the total depth with ribs, else the thickness."""
    ribs = getattr(slab_type, "ribs", None)
    h = float(slab_type.thickness)
    return rib_section(h, ribs).total if ribs is not None else h


def rib_geometry_checks(section: RibSection) -> list[dict[str, Any]]:
    """The dimensional limits of joist construction (see the module notes), as design checks."""
    from saengine.design.check import _check

    clause = "ACI 318-19 9.8.1"
    required_topping = max(TOPPING_MIN, section.clear * TOPPING_CLEAR_RATIO)
    return [
        _check(
            "Rib width (joist construction)",
            RIB_MIN_WIDTH,
            section.width,
            "mm",
            None,
            f"bw = {section.width:.0f} mm >= {RIB_MIN_WIDTH:.0f} mm ({clause}.1)",
            utilisation=RIB_MIN_WIDTH / section.width,
        ),
        _check(
            "Rib depth / width (joist construction)",
            section.depth,
            RIB_DEPTH_RATIO * section.width,
            "mm",
            None,
            f"rib depth {section.depth:.0f} mm <= 3.5 bw = {RIB_DEPTH_RATIO * section.width:.0f} "
            f"mm ({clause}.2)",
        ),
        _check(
            "Rib clear spacing (joist construction)",
            section.clear,
            RIB_MAX_CLEAR,
            "mm",
            None,
            f"clear spacing {section.clear:.0f} mm <= {RIB_MAX_CLEAR:.0f} mm ({clause}.3); "
            "wider ribs: design the topping as a slab and the ribs as beams (9.8.1.4)",
        ),
        _check(
            "Topping thickness (joist construction)",
            required_topping,
            section.topping,
            "mm",
            None,
            f"topping {section.topping:.0f} mm >= max(50 mm, clear spacing / 12 = "
            f"{section.clear / 12:.0f} mm) (ACI 318-11 8.13.6.1)",
            utilisation=required_topping / section.topping,
        ),
    ]


# ─────────────────────────────────── drop panels and capitals ───────────────────────────────────


def capital_size(column: float, capital: Any) -> float:
    """Effective size [mm] of a capital on a column ``column`` mm wide that way: the part inside
    a 90° pyramid from the column, min(size, c + 2 depth) (ACI 318-11 13.1.2), never less than
    the column."""
    if capital is None:
        return column
    return max(column, min(float(capital.size), column + 2 * float(capital.depth)))


def support_size(c1: float, c2: float, capital: Any) -> tuple[float, float]:
    """The column's effective face sizes (along u, along v) with its capital."""
    return capital_size(c1, capital), capital_size(c2, capital)


def drop_qualifies(h: float, drop: Any, spans: tuple[float, float]) -> tuple[bool, list[str]]:
    """Whether ``drop`` (``objects.DropPanel``) under a slab ``h`` thick counts as a drop panel
    for the minimum thickness (ACI 318-19 8.2.4): a projection of at least h/4 and an extent of
    at least l/6 each way from the column's centre line, ``spans`` the largest centre-to-centre
    spans (along u, along v; 0: not known, not checked). Returns (qualifies, the reasons it
    does not)."""
    problems = []
    if drop.depth < DROP_DEPTH_RATIO * h - 1e-6:
        problems.append(f"projects {drop.depth:.0f} mm < h/4 = {h / 4:.0f} mm")
    for name, extent, span in (("length", drop.length, spans[0]), ("width", drop.width, spans[1])):
        if span > 0 and extent / 2 < DROP_EXTENT_RATIO * span - 1e-6:
            problems.append(
                f"{name} / 2 = {extent / 2:.0f} mm < l/6 = {span / 6:.0f} mm (l = {span:.0f} mm)"
            )
    return not problems, problems


def drop_flexure_depth(h: float, drop: Any, c1: float, c2: float) -> float:
    """The thickness [mm] the top bars over a drop panel work in (ACI 318-19 8.5.2.2): the slab
    plus the projection, taking no more of it than a quarter of the least distance from the
    panel's edge to the face of the column (or capital) of sizes ``c1`` x ``c2``."""
    reach = min(drop.length - c1, drop.width - c2) / 2
    return h + max(0.0, min(float(drop.depth), reach / 4))


def drop_zone(
    centre: tuple[float, float], angle: float, length: float, width: float, point: Any
) -> bool:
    """Whether a plan ``point`` (mm) lies in the ``length`` x ``width`` rectangle at
    ``centre`` turned ``angle`` degrees (the column's axes)."""
    t = math.radians(angle)
    dx, dy = float(point[0]) - centre[0], float(point[1]) - centre[1]
    u = dx * math.cos(t) + dy * math.sin(t)
    v = -dx * math.sin(t) + dy * math.cos(t)
    return abs(u) <= length / 2 + 1e-6 and abs(v) <= width / 2 + 1e-6


def capital_volume(c1: float, c2: float, capital: Any) -> float:
    """Concrete volume [mm³] of a capital: a frustum from the column (``c1`` x ``c2``) to its
    square ``size`` over its ``depth``, (h / 3) (A1 + A2 + √(A1 A2))."""
    top, bottom = float(capital.size) ** 2, c1 * c2
    return float(capital.depth) / 3 * (top + bottom + math.sqrt(top * bottom))

"""Soil-structure interaction: the column bases of the analysis model on the springs of their
foundations (Part 9) in the soil of the soil report (Part 1), instead of fixed supports.

BNBC 2020 Part 6 Sec 1.2.7.3 asks that soil-structure interaction, where required, be included
"by appropriately including the properly substantiated properties of soil" in the mathematical
model. With ``supports = "soilSprings"`` (Project Settings -> Analysis) every column base that
stands on a foundation of ``09 Substructure/substructure.json`` gets that foundation's springs;
the rest of the analysis model (``08 FEM/model.osmodel``, :func:`saengine.fem.derive.derive_fem`)
is unchanged. :func:`apply_soil_springs` takes the derived project and returns the modified
one, the notes and a table of the springs.

How each foundation is modelled (SI units inside: m, N, Pa):

- The foundation is rigid. A node at the centre of its underside (the founding level) carries
  the springs; the column base nodes above it are tied to it by rigid links (``rigidLink
  beam``), so a horizontal force at a column base also rocks the foundation by its lever arm.
  A ``ZeroLength`` element joins that node to a fixed ground node at the same place, with one
  linear elastic uniaxial material per direction: ``[Kx, Ky, Kz, Krx, Kry, Krz]`` in global
  axes. OpenSees Studio's ``ZeroLength`` has no orientation: a foundation turned by other than
  a multiple of 90° gets ``Kx = Ku cos² + Kv sin²`` (and so on), its cross terms left out
  (reported in a note).
- Isolated and combined footings (L x B, L >= B): the surface stiffness of a rigid rectangular
  plate on a homogeneous elastic half-space times the embedment correction factors, both from
  ASCE 41-06 Sec 4.4.2.1.2 (developed from FEMA 356; Gazetas 1991, "Formulas and charts for
  impedances of surface and embedded foundations", J. Geotech. Eng. 117(9)), as tabulated in
  WSDOT Bridge Design Manual M 23-50.24 (2025) Sec 7.2.7, Tables 7.2.7-1 and 7.2.7-2, x along
  L, y along B, full dimensions:

  - ``Kx = GB/(2-ν) [3.4 (L/B)^0.65 + 1.2]``, ``Ky = GB/(2-ν) [3.4 (L/B)^0.65 + 0.4 L/B + 0.8]``,
    ``Kz = GB/(1-ν) [1.55 (L/B)^0.75 + 0.8]``, rocking ``Kxx = GB³/(1-ν) [0.4 L/B + 0.1]``,
    ``Kyy = GB³/(1-ν) [0.47 (L/B)^2.4 + 0.034]``, torsion ``Kzz = GB³ [0.53 (L/B)^2.45 + 0.51]``;
  - embedment D (finished ground to underside), d the height of sidewall contact (the
    footing's thickness, at most D), h = D - d/2 the depth to its centroid:
    ``βx = (1 + 0.21 √(D/B)) [1 + 1.6 (hd(B+L)/(BL²))^0.4]``,
    ``βy = (1 + 0.21 √(D/L)) [1 + 1.6 (hd(B+L)/(LB²))^0.4]``,
    ``βz = [1 + D/(21B) (2 + 2.6 B/L)] [1 + 0.32 (d(B+L)/(BL))^(2/3)]``,
    ``βxx = 1 + 2.5 d/B [1 + 2d/B (d/D)^-0.2 √(B/L)]``,
    ``βyy = 1 + 1.4 (d/L)^0.6 [1.5 + 3.7 (d/L)^1.9 (d/D)^-0.6]``,
    ``βzz = 1 + 2.6 (1 + B/L) (d/B)^0.9``.

  G is the soil's below the underside at the nearest borehole: the shear wave velocity of each
  SPT from its field N by Imai & Tonouchi (1982), ``Vs = 97.0 N^0.314`` m/s (all soils), the
  small-strain modulus ``G0 = ρ Vs²`` with ρ the layer's unit weight / g (saturated below the
  water table), averaged (arithmetic mean of the tests) over a depth B below the underside for
  the horizontal, rocking and torsional springs and 2B for the vertical one, times the
  effective shear modulus ratio G/G0 of the settings (by default from the effective peak
  acceleration, :func:`shear_modulus_ratio`). ν: 0.30 in granular layers, 0.45 in cohesive ones
  (nearly undrained under earthquake loading), the mean of the tests' layers.
- Pile caps: the piles' head stiffnesses summed over the rigid cap (pile-soil-pile interaction
  is not modelled, BNBC 2020 Part 6 Sec 3.10.1.19 takes a group efficiency of 1.0 for capacity;
  the lateral and torsional sums are multiplied by the settings' group factor):

  - axial: the pile an elastic bar (``Ep A``) on shaft springs ``ks = 2πG/ζ`` per metre with
    ``ζ = ln(rm/r0)``, ``rm = 2.5 ρ L (1-ν)``, ``ρ = G(average over the shaft)/G(at the tip)``,
    and a base spring ``kb = 4 Gb r0/(1-ν)`` (the load-transfer model of Randolph & Wroth
    1978, "Analysis of deformation of vertically loaded piles", J. Geotech. Eng. Div. 104(12));
    the bar's closed-form head stiffness
    ``k = EAμ (kb + EAμ tanh μL) / (EAμ + kb tanh μL)``, ``μ = √(ks/EA)``;
  - lateral and rotation: a long pile as a beam on a Winkler foundation (Hetényi 1946,
    "Beams on Elastic Foundation"), its line modulus from BNBC 2020 Part 6 Eq 6.3.9 (Vesic):
    ``k B = 0.65 (Es B⁴/EI)^(1/12) Es/(1-μ²)``, ``Es = 2G(1+ν)`` averaged over the top ten
    diameters, ``β = (kB/4EI)^(1/4)``; head translation with the head held against rotation by
    the cap ``Khh = 4EIβ³``, head rotation ``Kθθ = 2EIβ`` (the coupling ``-2EIβ²`` left out);
    a note when βL < 3 (not a long pile);
  - the cap: ``Kz = Σ kv``, ``Krx = Σ kv y² + Σ Kθθ``, ``Kry = Σ kv x² + Σ Kθθ`` (x, y from the
    cap's centre), ``Kx = Ky = f Σ Khh``, ``Krz = f Σ Khh (x² + y²)``.
- Rafts: the raft becomes part of the model, four-node shells (``ElasticMembranePlateSection``
  of its thickness and concrete) at its mid-plane meshed by Gmsh with a node at every column,
  each node on a vertical spring ``k = ks A`` (A its consistent share of the plan area, as
  :mod:`saengine.substructure.raft` builds its plate; BNBC 2020 Part 6 Sec 3.9.6.3 asks for the
  modulus of subgrade reaction), and horizontal springs: the raft's surface translation
  stiffnesses (above, of its bounding rectangle) shared by the same areas. ks: 9 Substructure ->
  Design's value, else :func:`saengine.substructure.raft.raft_ks` (the whole raft's settlement
  at its founding level under the building's weight over its area, less the overburden). The
  springs are linear (the analysis superposes its cases): they also pull.
- Strip footings, walls and columns without a foundation stay fixed (listed in a note).

The springs are the same in every load case: the static cases are combined linearly. Service
settlements from them (:func:`foundation_movements`, force / stiffness) are an elastic check
against Part 9's settlement, which governs.
"""

from __future__ import annotations

import copy
import itertools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

G = 9.80665  # m/s²

#: Imai & Tonouchi (1982), all soils: Vs = A N^B [m/s], N the field SPT blow count.
IMAI_A = 97.0
IMAI_B = 0.314
#: Poisson's ratio of the soil by the layer's behaviour.
NU_GRANULAR = 0.30
NU_COHESIVE = 0.45
#: Effective shear modulus ratio G/G0 by effective peak acceleration SDS/2.5 (ASCE 7-05 Table
#: 19.2-1), interpolated linearly: (SDS/2.5, G/G0).
SHEAR_MODULUS_RATIOS = ((0.10, 0.81), (0.15, 0.64), (0.20, 0.49), (0.30, 0.42))
#: Depth of the soil the lateral springs of a pile are averaged over, in diameters.
PILE_LATERAL_DIAMETERS = 10.0
#: Below this βL a pile is not long (semi-infinite) for its lateral stiffness.
LONG_PILE_BETA_L = 3.0

DOF_NAMES = ("Kx", "Ky", "Kz", "Krx", "Kry", "Krz")
DOF_UNITS = ("kN/m", "kN/m", "kN/m", "kN·m/rad", "kN·m/rad", "kN·m/rad")

Supports = Literal["fixed", "soilSprings"]


# ─────────────────────────────────────── options ───────────────────────────────────────


@dataclass
class SsiOptions:
    """How the column bases are supported (Project Settings -> Analysis)."""

    supports: Supports = "fixed"
    #: Effective shear modulus ratio G/G0; None: :func:`shear_modulus_ratio` of the site.
    shear_modulus_ratio: float | None = None
    #: Multiplies the piles' summed lateral and torsional stiffness.
    pile_group_factor: float = 1.0
    #: Apply the embedment factors of footings.
    embedment: bool = True


def options_from_settings(settings: Any) -> SsiOptions:
    """The options of ``settings.analysis`` (``supports``, ``ssiShearModulusRatio``,
    ``ssiPileGroupFactor``, ``ssiEmbedment``), their defaults where it has none."""
    analysis = getattr(settings, "analysis", None)
    return SsiOptions(
        supports=getattr(analysis, "supports", "fixed") or "fixed",
        shear_modulus_ratio=getattr(analysis, "ssiShearModulusRatio", None),
        pile_group_factor=float(getattr(analysis, "ssiPileGroupFactor", 1.0) or 1.0),
        embedment=bool(getattr(analysis, "ssiEmbedment", True)),
    )


def peak_acceleration(settings: Any) -> float | None:
    """Effective peak ground acceleration [g] of the site, the BNBC 2020 design spectrum's
    plateau / 2.5 with I = R = 1 (``(2/3) Z S``, ASCE 7's SDS/2.5); None without Z."""
    from saengine.fem.seismic_design import peak_ground_acceleration
    from saengine.library.settings import derived

    if not derived(settings)["Z"]:
        return None
    return peak_ground_acceleration(settings)


def shear_modulus_ratio(acceleration: float | None) -> float:
    """G/G0 for an effective peak acceleration SDS/2.5 [g] (ASCE 7-05 Table 19.2-1, linear
    between its columns, the end values beyond them); 1.0 without one."""
    if acceleration is None:
        return 1.0
    points = SHEAR_MODULUS_RATIOS
    if acceleration <= points[0][0]:
        return points[0][1]
    for (a0, r0), (a1, r1) in itertools.pairwise(points):
        if acceleration <= a1:
            return r0 + (r1 - r0) * (acceleration - a0) / (a1 - a0)
    return points[-1][1]


# ─────────────────────────────────────── soil ───────────────────────────────────────


def vs_from_n(n: float) -> float:
    """Shear wave velocity [m/s] of a field SPT N (Imai & Tonouchi 1982), N at least 1."""
    return IMAI_A * max(float(n), 1.0) ** IMAI_B


def poisson_of(behaviour: str | None) -> float:
    return NU_COHESIVE if behaviour == "cohesive" else NU_GRANULAR


@dataclass
class SoilAverage:
    """The soil's small-strain values averaged over a depth range below a borehole's ground."""

    borehole: str
    top: float  # m below the borehole's ground
    bottom: float  # m
    vs: float  # m/s, mean of the tests
    g0: float  # Pa, mean of ρ Vs²
    nu: float
    tests: int

    def basis(self, ratio: float) -> str:
        return (
            f"{self.borehole} {self.top:.2f}-{self.bottom:.2f} m: {self.tests} SPT, Vs = "
            f"{self.vs:.0f} m/s, G0 = {self.g0 / 1e6:.1f} MPa, G = {ratio:.2f} G0, ν = "
            f"{self.nu:.2f}"
        )


def soil_average(profile: Any, top: float, bottom: float) -> SoilAverage | None:
    """Mean Vs, G0 = ρVs² and ν of the SPT tests of ``profile`` between ``top`` and ``bottom``
    [m below its ground]; the test nearest the range's middle when none lies in it; None
    without tests."""
    tests = [p for p in profile.spt if top - 1e-9 <= p.depth <= bottom + 1e-9]
    if not tests and profile.spt:
        middle = (top + bottom) / 2
        tests = [min(profile.spt, key=lambda p: abs(p.depth - middle))]
    if not tests:
        return None
    vs, g0, nu = [], [], []
    for point in tests:
        layer = point.layer or profile.layer_at(point.depth)
        if layer is None:
            gamma = 18.0
        else:
            gamma = layer.gamma_sat if profile.below_water(point.depth) else layer.gamma
        rho = gamma * 1e3 / G
        v = vs_from_n(point.n)
        vs.append(v)
        g0.append(rho * v * v)
        nu.append(poisson_of(layer.behaviour if layer else None))
    return SoilAverage(
        profile.id, top, bottom, float(np.mean(vs)), float(np.mean(g0)), float(np.mean(nu)),
        len(tests),
    )  # fmt: skip


# ─────────────────────────────────────── footings ───────────────────────────────────────


def surface_stiffness(g: float, nu: float, length: float, width: float) -> dict[str, float]:
    """Static stiffnesses of a rigid L x B (m, L >= B) plate on the surface of a half-space of
    shear modulus ``g`` [Pa]: ``Kx`` along L, ``Ky`` along B, ``Kz``, rocking ``Kxx`` about the
    x axis, ``Kyy`` about y, torsion ``Kzz`` [N/m, N·m/rad] (ASCE 41-06 Sec 4.4.2.1.2)."""
    big, b = max(length, width), min(length, width)
    r = big / b
    return {
        "Kx": g * b / (2 - nu) * (3.4 * r**0.65 + 1.2),
        "Ky": g * b / (2 - nu) * (3.4 * r**0.65 + 0.4 * r + 0.8),
        "Kz": g * b / (1 - nu) * (1.55 * r**0.75 + 0.8),
        "Kxx": g * b**3 / (1 - nu) * (0.4 * r + 0.1),
        "Kyy": g * b**3 / (1 - nu) * (0.47 * r**2.4 + 0.034),
        "Kzz": g * b**3 * (0.53 * r**2.45 + 0.51),
    }


def embedment_factors(
    length: float, width: float, depth: float, contact: float
) -> dict[str, float]:
    """Embedment correction factors β (ASCE 41-06 Sec 4.4.2.1.2) of an L x B footing (m, L >=
    B) whose underside is ``depth`` D below the ground, with ``contact`` d of its sides against
    the soil; all 1 at the surface."""
    big, b = max(length, width), min(length, width)
    d_ = min(max(contact, 0.0), max(depth, 0.0))
    if depth <= 0:
        return dict.fromkeys(("Kx", "Ky", "Kz", "Kxx", "Kyy", "Kzz"), 1.0)
    h = depth - d_ / 2
    ratio_dd = (d_ / depth) if d_ > 0 else 1.0
    return {
        "Kx": (1 + 0.21 * math.sqrt(depth / b))
        * (1 + 1.6 * (h * d_ * (b + big) / (b * big**2)) ** 0.4),
        "Ky": (1 + 0.21 * math.sqrt(depth / big))
        * (1 + 1.6 * (h * d_ * (b + big) / (big * b**2)) ** 0.4),
        "Kz": (1 + depth / (21 * b) * (2 + 2.6 * b / big))
        * (1 + 0.32 * (d_ * (b + big) / (b * big)) ** (2 / 3)),
        "Kxx": 1 + 2.5 * d_ / b * (1 + 2 * d_ / b * ratio_dd**-0.2 * math.sqrt(b / big)),
        "Kyy": 1 + 1.4 * (d_ / big) ** 0.6 * (1.5 + 3.7 * (d_ / big) ** 1.9 * ratio_dd**-0.6),
        "Kzz": 1 + 2.6 * (1 + b / big) * (d_ / b) ** 0.9,
    }


def footing_springs(
    g_lateral: float,
    g_vertical: float,
    nu: float,
    length: float,
    width: float,
    depth: float = 0.0,
    contact: float = 0.0,
) -> tuple[list[float], dict[str, float]]:
    """``[Ku, Kv, Kz, Kru, Krv, Krz]`` [N/m, N·m/rad] of a footing ``length`` (along its local
    u) x ``width`` (along v) [m] founded ``depth`` below the ground with ``contact`` of its
    sides in the soil; ``g_lateral`` for the horizontal, rocking and torsional springs,
    ``g_vertical`` for the vertical one. Also the embedment factors."""
    sur_h = surface_stiffness(g_lateral, nu, length, width)
    sur_v = surface_stiffness(g_vertical, nu, length, width)
    beta = embedment_factors(length, width, depth, contact)
    k = {name: sur_h[name] * beta[name] for name in sur_h}
    k["Kz"] = sur_v["Kz"] * beta["Kz"]
    if length >= width:  # x along u
        springs = [k["Kx"], k["Ky"], k["Kz"], k["Kxx"], k["Kyy"], k["Kzz"]]
    else:  # x along v
        springs = [k["Ky"], k["Kx"], k["Kz"], k["Kyy"], k["Kxx"], k["Kzz"]]
    return springs, beta


def to_global(local: list[float], angle: float) -> tuple[list[float], bool]:
    """Global ``[Kx, Ky, Kz, Krx, Kry, Krz]`` of local ``[Ku, Kv, Kz, Kru, Krv, Krz]``, u at
    ``angle`` degrees from X; also whether cross terms were dropped (not a quarter turn)."""
    theta = math.radians(angle)
    c2, s2 = math.cos(theta) ** 2, math.sin(theta) ** 2
    turned = abs(angle / 90 - round(angle / 90)) > 1e-6
    return [
        local[0] * c2 + local[1] * s2,
        local[0] * s2 + local[1] * c2,
        local[2],
        local[3] * c2 + local[4] * s2,
        local[3] * s2 + local[4] * c2,
        local[5],
    ], turned


# ─────────────────────────────────────── piles ───────────────────────────────────────


def pile_axial_stiffness(
    ep: float, area: float, r0: float, length: float, g_shaft: float, g_tip: float, nu: float
) -> float:
    """Head stiffness [N/m] of a pile (``ep`` Pa, ``area`` m², radius ``r0``, ``length`` m) in
    soil of shear modulus ``g_shaft`` along it and ``g_tip`` at its tip (Randolph & Wroth 1978,
    load-transfer form)."""
    rho = g_shaft / g_tip if g_tip > 0 else 1.0
    rm = 2.5 * rho * length * (1 - nu)
    zeta = math.log(max(rm / r0, 1.0 + 1e-6))
    ks = 2 * math.pi * g_shaft / zeta
    kb = 4 * g_tip * r0 / (1 - nu)
    ea = ep * area
    mu = math.sqrt(ks / ea)
    t = math.tanh(mu * length)
    return ea * mu * (kb + ea * mu * t) / (ea * mu + kb * t)


def pile_lateral_stiffness(ep: float, inertia: float, d: float, es: float, nu: float) -> dict:
    """Head stiffnesses of a long pile on a Winkler foundation: line modulus ``kB`` [N/m²]
    (BNBC 2020 Part 6 Eq 6.3.9 times B), ``beta`` [1/m], ``Khh = 4EIβ³`` [N/m] (head held
    against rotation), ``Ktt = 2EIβ`` [N·m/rad] and the coupling ``Kht = -2EIβ²`` [N]."""
    ei = ep * inertia
    line = 0.65 * (es * d**4 / ei) ** (1 / 12) * es / (1 - nu**2)
    beta = (line / (4 * ei)) ** 0.25
    return {
        "kB": line,
        "beta": beta,
        "Khh": 4 * ei * beta**3,
        "Ktt": 2 * ei * beta,
        "Kht": -2 * ei * beta**2,
    }


def pile_group_springs(
    piles: list[tuple[float, float]],
    kv: float,
    khh: float,
    ktt: float,
    group_factor: float = 1.0,
) -> list[float]:
    """``[Kx, Ky, Kz, Krx, Kry, Krz]`` of a rigid cap on identical piles at ``piles`` [(x, y) m
    from the cap's centre, global axes]."""
    n = len(piles)
    sx2 = sum(x * x for x, _ in piles)
    sy2 = sum(y * y for _, y in piles)
    return [
        group_factor * n * khh,
        group_factor * n * khh,
        n * kv,
        kv * sy2 + n * ktt,
        kv * sx2 + n * ktt,
        group_factor * khh * (sx2 + sy2),
    ]


# ─────────────────────────────────────── result ───────────────────────────────────────


@dataclass
class FoundationSprings:
    """The springs of one foundation in the analysis model."""

    foundation: str
    type: str
    columns: list[str]
    node: int | None  # the foundation's node (rafts: None)
    ground: int | None  # its fixed ground node (rafts: None)
    elements: list[int]  # the ZeroLength elements
    position: list[float]  # [x, y, z] mm of the springs (rafts: centroid of the outline)
    k: list[float]  # [Kx, Ky, Kz, Krx, Kry, Krz] N/m, N·m/rad (rafts: their sums, no rocking)
    basis: list[str] = field(default_factory=list)
    #: Rafts: per mesh node (node id, ground node id, vertical k N/m).
    raft_nodes: list[tuple[int, int, float]] = field(default_factory=list)

    def row(self) -> dict[str, Any]:
        """The springs table's row: kN/m and kN·m/rad."""
        return {
            "foundation": self.foundation,
            "type": self.type,
            "columns": self.columns,
            "position": [round(v) for v in self.position],
            **{n: round(v / 1e3, 1) for n, v in zip(DOF_NAMES, self.k, strict=True)},
            "units": dict(zip(DOF_NAMES, DOF_UNITS, strict=True)),
            "basis": self.basis,
        }


@dataclass
class SsiResult:
    """:func:`apply_soil_springs`'s project, notes and springs."""

    project: dict[str, Any]
    notes: list[str]
    foundations: list[FoundationSprings]
    fixed_columns: list[str]
    shear_modulus_ratio: float

    def table(self) -> list[dict[str, Any]]:
        return [f.row() for f in self.foundations]

    def to_json(self) -> dict[str, Any]:
        """What the workbench shows (and Part 9 needs) beside the model (``08 FEM/ssi.json``)."""
        return {
            "shearModulusRatio": round(self.shear_modulus_ratio, 3),
            "springs": self.table(),
            "fixedColumns": self.fixed_columns,
            "notes": self.notes,
            "nodes": {
                f.foundation: {
                    "node": f.node,
                    "ground": f.ground,
                    "elements": f.elements,
                    "k": f.k,
                    "raftNodes": [list(r) for r in f.raft_nodes],
                }
                for f in self.foundations
            },
        }


# ─────────────────────────────────────── model editing ───────────────────────────────────────


class _Editor:
    """Adds nodes, materials, sections, elements and rigid links to a derived project."""

    def __init__(self, project: dict[str, Any]) -> None:
        self.project = project
        self.nodes = {n["id"]: n for n in project["nodes"]}
        self.next_node = max(self.nodes, default=0) + 1
        self.next_material = max((m["id"] for m in project["materials"]), default=0) + 1
        self.next_section = max((s["id"] for s in project["sections"]), default=0) + 1
        self.next_element = max((e["id"] for e in project["elements"]), default=0) + 1
        self.by_position = {
            tuple(round(c * 1000) for c in n["coords"]): n["id"] for n in project["nodes"]
        }

    def node(self, xyz_m: Any, fixed: bool = False) -> int:
        node_id = self.next_node
        self.next_node += 1
        node = {
            "id": node_id,
            "name": "",
            "coords": [round(float(v), 6) for v in xyz_m],
            "mass": [0.0] * 6,
            "restraint": [fixed] * 6,
        }
        self.project["nodes"].append(node)
        self.nodes[node_id] = node
        return node_id

    def release(self, node_id: int) -> None:
        node = self.nodes[node_id]
        node["restraint"] = [False] * 6

    def spring(self, name: str, i: int, j: int, k: list[float], dofs: list[int]) -> int:
        ids = []
        for value in k:
            ids.append(self.next_material)
            self.project["materials"].append(
                {"id": self.next_material, "name": name, "type": "Elastic", "E": float(value)}
            )
            self.next_material += 1
        element_id = self.next_element
        self.next_element += 1
        self.project["elements"].append(
            {
                "id": element_id,
                "name": name,
                "type": "ZeroLength",
                "nodes": [i, j],
                "material_ids": ids,
                "dofs": dofs,
            }
        )
        return element_id

    def link(self, retained: int, constrained: int) -> None:
        self.project.setdefault("mp_constraints", []).append(
            {"type": "RigidLinkBeam", "retained_node": retained, "constrained_node": constrained}
        )

    def shell(self, name: str, nodes: list[int], section: int) -> int:
        element_id = self.next_element
        self.next_element += 1
        self.project["elements"].append(
            {
                "id": element_id,
                "name": name,
                "type": "Shell",
                "formulation": "ASDShellQ4" if len(nodes) == 4 else "ASDShellT3",
                "nodes": nodes,
                "section_id": section,
            }
        )
        return element_id

    def plate_section(self, name: str, e: float, nu: float, h: float) -> int:
        section_id = self.next_section
        self.next_section += 1
        self.project["sections"].append(
            {
                "id": section_id,
                "name": name,
                "type": "ElasticMembranePlateSection",
                "E": e,
                "nu": nu,
                "h": h,
                "rho": 0.0,
            }
        )
        return section_id


def _concrete_e(materials: Any, material_id: str | None) -> tuple[float, float]:
    """E [Pa] and ν of a concrete material (E = 4700 √f'c MPa when not given; 25 GPa and 0.2
    without the material)."""
    material = materials.get(material_id) if (materials is not None and material_id) else None
    if material is None:
        return 25e9, 0.2
    e = material.mechanical.E
    if e is None and material.concrete is not None:
        e = 4700 * math.sqrt(material.concrete.fc)
    nu = material.mechanical.nu if material.mechanical.nu is not None else 0.2
    return float(e or 25e3) * 1e6, float(nu)


def _concrete_density(materials: Any, material_id: str | None) -> float:
    """Mass density [kg/m³] of a concrete material, 2400 when not given."""
    material = materials.get(material_id) if (materials is not None and material_id) else None
    if material is None or not material.mechanical.density:
        return 2400.0
    return float(material.mechanical.density)


def _inside(x: float, y: float, outline: list[list[float]]) -> bool:
    inside = False
    n = len(outline)
    for k in range(n):
        (x0, y0), (x1, y1) = outline[k], outline[(k + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


# ─────────────────────────────────────── main ───────────────────────────────────────


def apply_soil_springs(
    project: dict[str, Any],
    building: Any,
    substructure: Any,
    soil_text: str | None,
    materials: Any = None,
    *,
    ground_level: float = 0.0,
    acceleration: float | None = None,
    options: SsiOptions | None = None,
    soil_unit_weight: float = 18.0,
) -> SsiResult:
    """The derived ``project`` (not changed: a modified copy is returned) with the column bases
    on their foundations' springs (module notes). ``building`` the
    :class:`~saengine.library.bim.BuildingModel`, ``substructure`` the
    :class:`~saengine.library.substructure.Substructure`, ``soil_text`` the soil report's text,
    ``materials`` the :class:`~saengine.library.materials.MaterialLibrary` (piles' and rafts'
    concrete), ``ground_level`` the finished ground [mm] and ``soil_unit_weight`` [kN/m³] (Project
    Settings -> Foundation: the overburden a raft's ks is worked out net of),
    ``acceleration`` the effective peak acceleration SDS/2.5 [g] for the default G/G0
    (:func:`peak_acceleration`). With ``options.supports == "fixed"`` the project comes back
    unchanged (a copy)."""
    from saengine.library.bim import ColumnElement, WallElement
    from saengine.substructure.piles import nearest_profile, profiles_of

    options = options or SsiOptions(supports="soilSprings")
    out = copy.deepcopy(project)
    ratio = (
        options.shear_modulus_ratio
        if options.shear_modulus_ratio is not None
        else shear_modulus_ratio(acceleration)
    )
    if options.supports != "soilSprings":
        return SsiResult(out, [], [], [], ratio)
    editor = _Editor(out)
    notes: list[str] = []
    springs: list[FoundationSprings] = []
    profiles, report, problems = profiles_of(soil_text)
    if problems and soil_text:
        notes.append("soil report: " + "; ".join(problems))
    source = (
        f"G/G0 = {ratio:.2f} (settings)"
        if options.shear_modulus_ratio is not None
        else (
            f"G/G0 = {ratio:.2f} at SDS/2.5 = {acceleration:.3f} g (ASCE 7-05 Table 19.2-1)"
            if acceleration is not None
            else "G/G0 = 1.00 (no site acceleration)"
        )
    )
    notes.append(f"soil springs: {source}; Vs = 97.0 N^0.314 m/s (Imai & Tonouchi 1982)")

    # Column bases at fixed supports of the model.
    columns: dict[str, tuple[ColumnElement, int]] = {}
    for element in building.elements:
        if not isinstance(element, ColumnElement):
            continue
        key = (round(element.position[0]), round(element.position[1]), round(element.bottom))
        node_id = editor.by_position.get(key)
        if node_id is not None and all(editor.nodes[node_id].get("restraint") or []):
            columns[element.id] = (element, node_id)
    walls = [e.id for e in building.elements if isinstance(e, WallElement)]
    carried: dict[str, Any] = {}
    for foundation in substructure.foundations:
        if foundation.type == "raft" and not foundation.columns:
            outline = foundation.outline or []
            for cid, (element, _) in columns.items():
                if cid not in carried and _inside(
                    float(element.position[0]), float(element.position[1]), outline
                ):
                    carried[cid] = foundation
        for cid in foundation.columns:
            carried.setdefault(cid, foundation)

    def profile_at(x_mm: float, y_mm: float) -> tuple[Any, float] | None:
        if not profiles:
            return None
        profile, distance = nearest_profile(profiles, x_mm, y_mm)
        return profile, distance

    def depth_below(profile: Any, level_mm: float) -> float:
        ground = report.ground_level(profile.borehole) if report is not None else ground_level
        return max((ground - level_mm) / 1e3, 0.0)

    fixed: list[str] = []
    done: set[str] = set()
    for foundation in substructure.foundations:
        own = [cid for cid in columns if carried.get(cid) is foundation]
        if not own:
            continue
        if foundation.type == "strip":
            fixed.extend(own)
            notes.append(f"{foundation.id}: strip footings are not on springs yet; fixed")
            continue
        try:
            if foundation.type == "raft":
                found = _raft(
                    editor, foundation, own, columns, substructure, profiles, report,
                    materials, ground_level, ratio, notes, out, soil_unit_weight,
                )  # fmt: skip
            else:
                found = _rigid(
                    editor, foundation, own, columns, substructure, profile_at, depth_below,
                    materials, ground_level, ratio, options, notes,
                )  # fmt: skip
        except _Fixed as reason:
            fixed.extend(own)
            notes.append(f"{foundation.id}: {reason}; its columns stay fixed")
            continue
        springs.append(found)
        done.update(own)
    for cid in columns:
        if cid not in done and cid not in fixed:
            fixed.append(cid)
    without = [cid for cid in fixed if cid not in carried]
    if without:
        notes.append(f"no foundation in 9 Substructure, fixed: {', '.join(sorted(without))}")
    if walls:
        notes.append(f"walls stay fixed at their bases: {', '.join(sorted(walls))}")
    return SsiResult(out, notes, springs, sorted(fixed), ratio)


class _Fixed(Exception):
    """A foundation that cannot be put on springs (the reason)."""


def _rigid(
    editor: _Editor,
    foundation: Any,
    own: list[str],
    columns: dict[str, tuple[Any, int]],
    substructure: Any,
    profile_at: Any,
    depth_below: Any,
    materials: Any,
    ground_level: float,
    ratio: float,
    options: SsiOptions,
    notes: list[str],
) -> FoundationSprings:
    """An isolated or combined footing or a pile cap: one spring node under its centre."""
    if foundation.center is not None:
        cx, cy = float(foundation.center[0]), float(foundation.center[1])
    else:
        points = [columns[c][0].position for c in own]
        cx, cy = float(np.mean([p[0] for p in points])), float(np.mean([p[1] for p in points]))
    founding = foundation.founding_level(ground_level)
    length, width = float(foundation.length) / 1e3, float(foundation.width) / 1e3
    thickness = float(foundation.thickness or 0) / 1e3
    found = profile_at(cx, cy)
    if found is None:
        raise _Fixed("no borehole in the soil report")
    profile, distance = found
    df = depth_below(profile, founding)
    basis: list[str] = []
    if foundation.type == "pileCap":
        local = None
        k, more = _pile_cap(foundation, substructure, profile, df, materials, ratio, options)
        basis += more
    else:
        b = min(length, width)
        lateral = soil_average(profile, df, df + b)
        vertical = soil_average(profile, df, df + 2 * b)
        if lateral is None or vertical is None:
            raise _Fixed(f"borehole {profile.id} has no SPT")
        embed = (ground_level - founding) / 1e3 if options.embedment else 0.0
        contact = min(thickness, max(embed, 0.0))
        local, beta = footing_springs(
            ratio * lateral.g0, ratio * vertical.g0, (lateral.nu + vertical.nu) / 2,
            length, width, max(embed, 0.0), contact,
        )  # fmt: skip
        k, turned = to_global(local, foundation.rotation)
        if turned:
            notes.append(
                f"{foundation.id}: turned {foundation.rotation:g}°; its springs are in global "
                "axes without their cross terms"
            )
        basis += [
            (
                f"{length:.2f} x {width:.2f} m at D = {max(embed, 0):.2f} m (ASCE 41-06 "
                "4.4.2.1.2: surface stiffness x embedment β)"
            ),
            "horizontal, rocking, torsion: " + lateral.basis(ratio),
            "vertical: " + vertical.basis(ratio),
            "β: " + ", ".join(f"{n} {v:.2f}" for n, v in beta.items()),
        ]
    if distance > 0:
        basis.append(f"nearest borehole {profile.id} at {distance / 1e3:.1f} m")
    position = np.array([cx, cy, founding]) / 1e3
    tag = f"SSI {foundation.id}"
    base_nodes = [columns[c][1] for c in own]
    single = len(base_nodes) == 1 and np.allclose(
        editor.nodes[base_nodes[0]]["coords"], position, atol=1e-6
    )
    if single:
        node = base_nodes[0]
        editor.release(node)
    else:
        node = editor.node(position)
        for base in base_nodes:
            editor.release(base)
            editor.link(node, base)
    ground = editor.node(position, fixed=True)
    element = editor.spring(tag, node, ground, k, [1, 2, 3, 4, 5, 6])
    return FoundationSprings(
        foundation.id, foundation.type, own, node, ground, [element],
        [cx, cy, founding], [float(v) for v in k], basis,
    )  # fmt: skip


def _pile_cap(
    foundation: Any,
    substructure: Any,
    profile: Any,
    df: float,
    materials: Any,
    ratio: float,
    options: SsiOptions,
) -> tuple[list[float], list[str]]:
    pile = substructure.cap_pile_type(foundation)
    if pile is None:
        raise _Fixed("its piles have no pile type")
    d = float(pile.diameter) / 1e3
    length = float(pile.length) / 1e3
    if pile.kind == "driven":  # square
        area, inertia, r0 = d * d, d**4 / 12, d / math.sqrt(math.pi)
    else:
        area, inertia, r0 = math.pi * d * d / 4, math.pi * d**4 / 64, d / 2
    ep, _ = _concrete_e(materials, pile.material)
    shaft = soil_average(profile, df, df + length)
    tip = soil_average(profile, df + length, df + length + 2 * d)
    top = soil_average(profile, df, df + min(length, PILE_LATERAL_DIAMETERS * d))
    if shaft is None or tip is None or top is None:
        raise _Fixed(f"borehole {profile.id} has no SPT")
    kv = pile_axial_stiffness(
        ep, area, r0, length, ratio * shaft.g0, ratio * tip.g0, (shaft.nu + tip.nu) / 2
    )
    es = 2 * ratio * top.g0 * (1 + top.nu)
    lateral = pile_lateral_stiffness(ep, inertia, d, es, top.nu)
    theta = math.radians(foundation.rotation)
    c, s = math.cos(theta), math.sin(theta)
    piles = [
        ((c * dx - s * dy) / 1e3, (s * dx + c * dy) / 1e3)
        for dx, dy in substructure.pile_offsets(foundation)
    ]
    k = pile_group_springs(piles, kv, lateral["Khh"], lateral["Ktt"], options.pile_group_factor)
    basis = [
        (
            f"{len(piles)} piles {pile.id}: {pile.kind}, d = {d * 1e3:.0f} mm, L = {length:.1f} m, "
            f"Ep = {ep / 1e9:.1f} GPa"
        ),
        f"axial kv = {kv / 1e3:.0f} kN/m per pile (Randolph & Wroth 1978): shaft "
        + shaft.basis(ratio)
        + "; tip "
        + tip.basis(ratio),
        f"lateral Khh = {lateral['Khh'] / 1e3:.0f} kN/m, Kθθ = {lateral['Ktt'] / 1e3:.0f} "
        f"kN·m/rad per pile (Winkler, BNBC 2020 Part 6 Eq 6.3.9: kB = "
        f"{lateral['kB'] / 1e3:.0f} kN/m², β = {lateral['beta']:.3f} /m): " + top.basis(ratio),
        (
            f"cap: Kz = Σkv, Kr = Σkv·r² + ΣKθθ, Kh = {options.pile_group_factor:g} ΣKhh "
            "(pile-soil-pile interaction not modelled)"
        ),
    ]
    if lateral["beta"] * length < LONG_PILE_BETA_L:
        basis.append(
            f"βL = {lateral['beta'] * length:.2f} < {LONG_PILE_BETA_L:g}: not a long pile, its "
            "lateral stiffness is approximate"
        )
    return k, basis


def _raft(
    editor: _Editor,
    foundation: Any,
    own: list[str],
    columns: dict[str, tuple[Any, int]],
    substructure: Any,
    profiles: list[Any],
    report: Any,
    materials: Any,
    ground_level: float,
    ratio: float,
    notes: list[str],
    project: dict[str, Any],
    soil_unit_weight: float = 18.0,
) -> FoundationSprings:
    """The raft as shells on vertical and horizontal springs, its columns connected."""
    from saengine.fem.mesh import mesh, shell_node_shares
    from saengine.library.substructure import polygon_area
    from saengine.substructure.piles import nearest_profile
    from saengine.substructure.raft import MESH_LOCK, raft_ks

    outline = [[float(p[0]), float(p[1])] for p in foundation.outline or []]
    thickness = float(foundation.thickness)
    founding = foundation.founding_level(ground_level)
    z_mid = founding + thickness / 2  # mm
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    b_mm, l_mm = sorted((max(xs) - min(xs), max(ys) - min(ys)))
    area = abs(polygon_area(outline)) / 1e6
    centre = np.mean(np.array(outline), axis=0)
    if not profiles and substructure.design.springsFrom == "soilReport":
        raise _Fixed("no borehole in the soil report for ks")
    basis: list[str] = []
    profile = None
    df = 0.0
    if profiles:
        profile, _ = nearest_profile(profiles, float(centre[0]), float(centre[1]))
        ground = report.ground_level(profile.borehole) if report is not None else ground_level
        df = max((ground - founding) / 1e3, 0.0)
    e_c, nu_c = _concrete_e(materials, foundation.material)
    gamma_c = _concrete_density(materials, foundation.material) * G / 1e3  # kN/m³
    if substructure.design.springsFrom != "soilReport":
        ks = float(substructure.design.springsFrom)
        basis.append(f"ks = {ks:.0f} kN/m³ (9 Substructure → Design)")
    else:
        weight = 0.0  # N, the building's weight (its masses) over the raft
        for node in project["nodes"]:
            x, y = node["coords"][0] * 1e3, node["coords"][1] * 1e3
            if _inside(x, y, outline):
                weight += float((node.get("mass") or [0.0])[0]) * G
        overburden = soil_unit_weight * max((ground_level - founding) / 1e3, 0.0)
        q = weight / 1e3 / area + gamma_c * thickness / 1e3 - overburden
        found = raft_ks(profile, b_mm / 1e3, l_mm / 1e3, df, max(q, 1.0))
        if found["value"] is None:
            raise _Fixed(f"no ks from the soil report at {profile.id}: {found['note']}")
        ks = float(found["value"])
        basis.append(f"ks = {ks:.0f} kN/m³ at {profile.id}: {found['method']}")
    # Horizontal springs: the raft's surface translation stiffness (bounding rectangle).
    kh = [0.0, 0.0]
    if profile is not None:
        lateral = soil_average(profile, df, df + b_mm / 1e3)
        if lateral is not None:
            sur = surface_stiffness(ratio * lateral.g0, lateral.nu, l_mm / 1e3, b_mm / 1e3)
            long_x = (max(xs) - min(xs)) >= (max(ys) - min(ys))
            kh = [sur["Kx"], sur["Ky"]] if long_x else [sur["Ky"], sur["Kx"]]
            basis.append(
                "horizontal: surface Kx, Ky of the bounding rectangle (ASCE 41-06 4.4.2.1.2), "
                "by area share: " + lateral.basis(ratio)
            )
    if not any(kh):
        notes.append(f"{foundation.id}: no horizontal soil springs (no SPT); held horizontally")
    # Mesh: the outline at the raft's mid-plane, a node at every column (a short line there).
    lines = [
        (cid, (float(columns[cid][0].position[0]), float(columns[cid][0].position[1]), z_mid),
         (float(columns[cid][0].position[0]), float(columns[cid][0].position[1]), z_mid + 100.0))
        for cid in own
    ]  # fmt: skip
    from saengine.fem.mesh import Surface

    with MESH_LOCK:
        found_mesh = mesh(
            lines,
            [Surface("raft", [(x, y, z_mid) for x, y in outline], normal=(0.0, 0.0, 1.0))],
            float(substructure.design.raftMeshSize),
        )
    elements = found_mesh.surfaces.get("raft", [])
    used = sorted({n for e in elements for n in e})
    xyz = {tag: found_mesh.nodes[tag] / 1e3 for tag in used}  # m
    shares = dict.fromkeys(used, 0.0)
    for element in elements:
        corners = [np.array([xyz[n][0], xyz[n][1], 0.0]) for n in element]
        for n, share in zip(element, shell_node_shares(corners), strict=True):
            shares[n] += share
    total = sum(shares.values()) or 1.0
    # Model nodes: a column base at the mid-plane is the raft's node there.
    node_of: dict[int, int] = {}
    for cid in own:
        element, base = columns[cid]
        p = np.array([element.position[0], element.position[1], z_mid]) / 1e3
        tag = min(used, key=lambda t: float(np.linalg.norm(xyz[t] - p)))
        if float(np.linalg.norm(xyz[tag] - p)) > 1e-3:
            notes.append(f"{foundation.id}: {cid} has no raft node under it; left fixed")
            continue
        editor.release(base)
        if abs(float(element.bottom) - z_mid) < 1.0:
            node_of[tag] = base
        else:
            if tag not in node_of:
                node_of[tag] = editor.node(xyz[tag])
            editor.link(node_of[tag], base)
    for tag in used:
        if tag not in node_of:
            node_of[tag] = editor.node(xyz[tag])
    # The raft's own mass, lumped at its nodes (horizontal, as the derived model's masses).
    density = _concrete_density(materials, foundation.material)
    for tag in used:
        node = editor.nodes[node_of[tag]]
        extra = density * thickness / 1e3 * shares[tag]
        mass = list(node.get("mass") or [0.0] * 6)
        node["mass"] = [mass[0] + extra, mass[1] + extra, *mass[2:]]
    section = editor.plate_section(f"{foundation.id} {thickness:g} mm", e_c, nu_c, thickness / 1e3)
    for element in elements:
        editor.shell(foundation.id, [node_of[n] for n in element], section)
    raft_nodes: list[tuple[int, int, float]] = []
    spring_ids: list[int] = []
    for k, tag in enumerate(used, start=1):
        share = shares[tag]
        kv = ks * 1e3 * share
        if kv <= 0:
            continue
        ground_node = editor.node(xyz[tag], fixed=True)
        values = [kv]
        dofs = [3]
        for axis, value in enumerate(kh):
            if value > 0:
                values.append(value * share / total)
                dofs.append(axis + 1)
        spring_ids.append(
            editor.spring(f"SSI {foundation.id} {k}", node_of[tag], ground_node, values, dofs)
        )
        raft_nodes.append((node_of[tag], ground_node, kv))
    if not any(kh):  # held horizontally and against the drilling rotation
        for tag in used:
            node = editor.nodes[node_of[tag]]
            node["restraint"] = [True, True, False, False, False, True]
    basis.insert(
        0,
        f"raft {thickness:g} mm, {area:.1f} m², {len(elements)} shells (mesh "
        f"{substructure.design.raftMeshSize:g} mm), vertical springs ks·A (linear, they pull)",
    )
    return FoundationSprings(
        foundation.id, "raft", own, None, None, spring_ids,
        [float(centre[0]), float(centre[1]), founding],
        [kh[0], kh[1], ks * 1e3 * area, 0.0, 0.0, 0.0], basis, raft_nodes,
    )  # fmt: skip


# ─────────────────────────────────────── outputs ───────────────────────────────────────


def foundation_movements(
    result: SsiResult | dict[str, Any],
    cases: dict[str, dict[int, np.ndarray]],
    combinations: list[tuple[str, dict[str, float]]],
) -> list[dict[str, Any]]:
    """Per foundation and combination, its movement from its spring reactions: settlement
    ``Rz/Kz`` [mm, down positive], horizontal movements ``-R/K`` [mm] and rotations ``-M/Kr``
    [rad] (global axes); a raft: its largest and smallest node settlement ``Rz,i/ki``.
    ``cases`` the support reactions by static case and node
    (:func:`saengine.substructure.loads.case_reactions`), ``combinations`` (name, {case:
    factor}) such as :func:`saengine.substructure.loads.service_combinations`. ``result`` an
    :class:`SsiResult` or its :meth:`SsiResult.to_json`."""
    nodes = result.to_json()["nodes"] if isinstance(result, SsiResult) else result["nodes"]

    def reaction(node: int, factors: dict[str, float]) -> np.ndarray:
        total = np.zeros(6)
        for case, factor in factors.items():
            total += factor * np.asarray(cases.get(case, {}).get(node, np.zeros(6)), dtype=float)
        return total

    rows: list[dict[str, Any]] = []
    for foundation, info in nodes.items():
        for name, factors in combinations:
            if info.get("raftNodes"):
                settle = [
                    reaction(ground, factors)[2] / kv * 1e3 for _, ground, kv in info["raftNodes"]
                ]
                rows.append(
                    {
                        "foundation": foundation,
                        "combination": name,
                        "settlement": round(float(max(settle)), 2),
                        "minSettlement": round(float(min(settle)), 2),
                    }
                )
                continue
            r = reaction(info["ground"], factors)
            k = info["k"]
            move = [-r[i] / k[i] if k[i] > 0 else 0.0 for i in range(6)]
            rows.append(
                {
                    "foundation": foundation,
                    "combination": name,
                    "settlement": round(float(-move[2] * 1e3), 2),
                    "ux": round(float(move[0] * 1e3), 2),
                    "uy": round(float(move[1] * 1e3), 2),
                    "rx": round(float(move[3]), 6),
                    "ry": round(float(move[4]), 6),
                    "rz": round(float(move[5]), 6),
                }
            )
    return rows


@dataclass
class ResponseSummary:
    """Periods, base shears and storey drifts of an analysed model."""

    periods: list[float]
    base_shear: dict[str, float]  # case -> N, in the case's direction
    drifts: dict[str, list[tuple[float, float]]]  # case -> [(level m, drift ratio)]


def storey_levels(building: Any) -> list[float]:
    """The building's storey elevations in m, lowest (the column bases) first."""
    return sorted({round(float(s.elevation) * 1e-3, 6) for s in building.stories})


def storey_drifts(
    z_of: dict[int, float],
    disp: dict[int, float],
    levels: list[float],
    tol: float = 1e-3,
) -> list[tuple[float, float]]:
    """Storey drift ratios at the building's storey levels only: per level above the base the
    mean displacement of the nodes on it (a node missing from ``disp``, a support, counts as
    0), less that of the level below, over the storey height. The lowest level is the column
    bases: 0 on a fixed base, the bases' own movement on soil springs. Nodes between levels
    (wall and shell mesh rows) and below the base (footing and raft nodes) are not levels."""
    means: list[tuple[float, float]] = []
    for level in sorted(levels):
        on = [disp.get(n, 0.0) for n, z in z_of.items() if abs(z - level) <= tol]
        if on:
            means.append((level, float(np.mean(on))))
    return [
        (z, (u - u0) / (z - z0)) for (z0, u0), (z, u) in itertools.pairwise(means) if z - z0 > tol
    ]


def response_summary(
    project: dict[str, Any], out_dir: str | Path, levels: list[float]
) -> ResponseSummary:
    """The modal periods, the base shear (sum of the support reactions) of each lateral static
    case (WX, WY, EX, EY) and its storey drift ratios at ``levels`` (the storey elevations in
    m, from :func:`storey_levels`; see :func:`storey_drifts`)."""
    from opensees_studio.services.result_store import load_manifest, load_results
    from opensees_studio.services.results import ModalResults, StaticResults

    from saengine.fem.display import _code, _last

    manifest = load_manifest(out_dir)
    z_of = {int(n["id"]): float(n["coords"][2]) for n in project["nodes"]}
    periods: list[float] = []
    shear: dict[str, float] = {}
    drifts: dict[str, list[tuple[float, float]]] = {}
    for entry in manifest["cases"]:
        results = load_results(entry, out_dir)
        if isinstance(results, ModalResults) and not periods:
            periods = [float(p) for p in results.periods if np.isfinite(p)]
            continue
        if not isinstance(results, StaticResults):
            continue
        code = _code(entry["case_name"])
        if code not in ("WX", "WY", "EX", "EY"):
            continue
        axis = 0 if code.endswith("X") else 1
        shear[code] = -sum(
            float(_last(results.node_reaction, n, 6)[axis]) for n in results.node_reaction
        )
        disp = {int(n): float(_last(results.node_disp, n, 6)[axis]) for n in results.node_disp}
        drifts[code] = storey_drifts(z_of, disp, levels)
    return ResponseSummary(periods, shear, drifts)


def compare_responses(fixed: ResponseSummary, ssi: ResponseSummary) -> dict[str, Any]:
    """Fixed base against soil springs: periods (and their ratio T̃/T), base shears, the
    largest storey drift of each lateral case and the drift of every storey (level in m)."""
    periods = [
        {"mode": k + 1, "fixed": round(a, 4), "ssi": round(b, 4), "ratio": round(b / a, 3)}
        for k, (a, b) in enumerate(zip(fixed.periods, ssi.periods, strict=False))
        if a > 0
    ]
    shear = [
        {
            "case": case,
            "fixed": round(fixed.base_shear[case] / 1e3, 2),
            "ssi": round(ssi.base_shear.get(case, 0.0) / 1e3, 2),
        }
        for case in fixed.base_shear
    ]
    drift = []
    storeys = []
    for case, rows in fixed.drifts.items():
        other = dict(ssi.drifts.get(case, []))
        a = max((abs(r) for _, r in rows), default=0.0)
        b = max((abs(r) for r in other.values()), default=0.0)
        drift.append({"case": case, "fixed": round(a, 6), "ssi": round(b, 6)})
        storeys.extend(
            {"case": case, "level": z, "fixed": round(r, 6), "ssi": round(other.get(z, 0.0), 6)}
            for z, r in rows
        )
    return {"periods": periods, "baseShear": shear, "drift": drift, "storeyDrift": storeys}


def fixed_and_ssi(
    building: Any,
    objects: Any,
    materials: Any,
    settings: Any,
    substructure: Any,
    soil_text: str | None,
    sources: dict[str, str] | None = None,
    model_dir: str | Path | None = None,
    mep: Any = None,
) -> tuple[Any, SsiResult]:
    """Both models of a project: the fixed-base derivation and the soil-spring one, the
    options from ``settings`` (``supports`` taken as ``"soilSprings"``). ``mep``: the MEP model
    whose openings and equipment loads both models carry."""
    from saengine.fem.derive import derive_fem

    fixed = derive_fem(
        building, objects, materials, settings, sources, model_dir, mep=mep, column_supports="fixed"
    )
    if mep is not None:
        from saengine.mep.loads import with_mep_openings

        building, _ = with_mep_openings(building, mep)
    options = options_from_settings(settings)
    options.supports = "soilSprings"
    ssi = apply_soil_springs(
        fixed.project,
        building,
        substructure,
        soil_text,
        materials,
        ground_level=settings.foundation.groundLevel,
        acceleration=peak_acceleration(settings),
        options=options,
        soil_unit_weight=settings.foundation.soilUnitWeight,
    )
    return fixed, ssi

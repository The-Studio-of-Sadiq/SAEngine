"""Structural design of RC water-retaining tanks (Part 7, plumbing coordination).

The tanks of ``07 MEP/mep.json`` ``plumbing.tanks`` (``overhead``, ``underground``, ``septic``,
``rainwater``: rectangular boxes; ``soakWell``: a circular ring) are analysed as a box of shells
(:mod:`saengine.plumbing.tanks_model`, OpenSees Studio) and designed per metre width of every
wall, the base and the roof. :func:`design_tank` is the entry point.

Loads (load cases, superposed: the model is linear; a combination under which the base of a
ground tank lifts off is run on its own with compression-only springs, and one whose net load is
upward with the base held along the walls' lines: :func:`saengine.plumbing.tanks_model.run_tank`)
- D: the self weight of the shells (``concreteUnitWeight``, 24 kN/m³ by default), a
  superimposed dead load on the roof (``roofFinish``) and the earth cover over a buried roof.
- F: the liquid, full to the overflow (the water depth; γw = 9.81 kN/m³, ``liquidUnitWeight``
  for sewage): ``γw (zw - z)`` on the walls (outward) and the base (down). A tank with
  ``compartments`` > 1 has a case per compartment full and the others empty (``F1``, ``F2``,
  ...), which loads its partitions from one side; the partitions carry nothing with all full.
- H (ground tanks): the lateral earth pressure at rest on the outer walls, ``K0 (σ'v + q) + u``
  with ``K0 = 1 - sin φ'`` (Jaky) of the soil report's layer at each depth, σ'v with the
  submerged unit weight below the design water table, u the full hydrostatic pressure below it
  (BNBC 2020 Part 6 Sec 2.6.5.1: "the submerged unit weight of soil, plus full hydrostatic
  pressure" (p680)), q the surcharge (``surcharge``, 10 kPa by default); and the uplift
  on the base, the full hydrostatic pressure from the underside of the base (Sec 2.6.5.2,
  p680). The design water table is ``designWaterTable`` (m below ground; ground level by
  default: the soil report's level is the one measured at drilling, the design one the
  highest expected; BNBC does not set it).
- Lr: the roof live load, ``roofLive`` (1.00 kN/m², an ordinary flat roof, BNBC Part 6 Table
  6.2.3 (p536); set it for a roof used otherwise, e.g. a driveway); a septic tank's roof
  at least 7 kPa (BNBC Part 8 Sec 6.9.12.14 (p1107), :data:`SEPTIC_COVER_LIVE`).

Combinations (BNBC 2020 Part 6 Sec 2.7 (p684-685))
- strength (Sec 2.7.3.1): (1) 1.4(D + F); (2) 1.2(D + F) + 1.6H + 0.5Lr, also with H = 0
  (the tank tested full before backfilling) and with F = 0 (empty, backfilled), as "effects of
  one or more loads not acting shall be investigated"; (3) 1.2D + 1.6Lr; (6) 0.9D + 1.6H
  (W = 0). Each F also with each compartment alone.
- service (Sec 2.7.2.1): (1) D + F; (2) D + H + F, also F = 0; (3) D + H + F + Lr; (7) 0.6D
  + H (W = 0: the reduced dead load against the uplift). The crack widths, the bearing pressure
  and the settlement use these.

Design per metre width (strength: ACI 318-19, which BNBC Part 6 Chapter 6 adopts)
- the shell moments at every node, turned into Wood-Armer design moments per face and direction
  (:func:`saengine.design.slab.wood_armer`), with the membrane force across the same section
  (the direct tension the adjacent walls' pressure puts into a wall): combined flexure and
  tension of a rectangular section with bars at both faces (:func:`tension_flexure`): with the
  force N outside the bars (e = M/N beyond the tension bars) the moment about the tension bars
  ``M - N ds`` is taken by the compression block and ``As = 0.85 f'c b a / fy + N / (φ fy)``;
  with N between the bars the whole section is in tension and the bars share N by the lever
  rule. φ by ACI 21.2.2 from the net tensile strain.
- one-way shear without shear reinforcement: ACI 318-19 Table 22.5.5.1 (c) with the axial
  tension term ``Nu / (6 Ag)`` (negative for tension), :func:`saengine.design.slab.one_way_shear`
  less that term, at the critical sections d from the faces of the supporting panels and at
  the nodes between them, along the panel's mesh lines except those on a joint with a panel
  across it (a slab's lines on the walls, a wall's lines at the corners, partitions and base):
  the shells' transverse shear there is not the panel's shear and depends on the mesh.
- minimum reinforcement for the restraint of early thermal and shrinkage movements, per face
  and direction: EN 1992-1-1:2004 Eq. (7.1), ``As,min = kc k fct,eff Act / σs``, kc = 1.0
  (tension of the restrained section), k = 1.0 for h ≤ 300 mm and 0.65 for h ≥ 800 mm
  (linear between), Act half the section per face, σs = fy, fct,eff the mean tensile strength
  at the age the restraint cracks it (``crackingAge`` 3 days by default: EN 1992-1-1 3.1.2,
  ``fctm(t) = βcc(t) fctm``, ``βcc = exp(0.25 (1 - √(28/t)))`` for cement class N,
  ``fctm = 0.30 fck^(2/3)``, fck taken as f'c); and not less than BNBC Part 6 Sec 6.6.3.2 /
  6.6.3.3 (walls: vertical 0.0012 / 0.0015, horizontal 0.0020 / 0.0025 of the gross section (p969)) or ACI 318-19 7.6.1.1 (slabs, :func:`saengine.design.slab.min_steel_ratio`),
  half at each face.
- crack widths (service): EN 1992-1-1:2004 7.3.4, :func:`crack_width`: ``wk = sr,max (εsm -
  εcm)``, ``εsm - εcm = [σs - kt fct,eff / ρp,eff (1 + αe ρp,eff)] / Es ≥ 0.6 σs / Es``,
  ``sr,max = k3 c + k1 k2 k4 φ / ρp,eff`` (k1 0.8, k3 3.4, k4 0.425, k2 0.5 in bending,
  ``(ε1 + ε2) / 2 ε1`` with the whole section in tension), or ``1.3 (h - x)`` with the bars
  further apart than ``5 (c + φ/2)``; ``ρp,eff = As / (b hc,ef)``, ``hc,ef = min(2.5 (h - d),
  (h - x) / 3, h / 2)``; kt 0.4 (long-term), fct,eff = fctm. σs and x from the cracked
  section under the service moment and membrane force (:func:`cracked_section`, elastic, the
  concrete carrying no tension). Limit ``crackLimit`` (0.2 mm by default; see the notes).
- cover (BNBC 2020 Part 6 Sec 8.1.7 (p1069-1071)): the larger (8.1.7.4) of Table 6.8.3
  ("severe": alternate wetting and drying, on the liquid faces; "severe" also for the faces
  of an overhead tank exposed to the weather, "moderate": in contact with non-aggressive soil,
  for the outer faces of a ground tank) and Sec 8.1.7.2: 75 mm cast against earth (the base's
  underside of a ground tank), 50 mm (19 mm bars and over) or 40 mm (16 mm and under) exposed
  to earth or weather; w/c ≤ 0.50 for concrete to have a low permeability (Sec 5.5.1.1,
  p844) is reported as a note.
- bars: the tank's ``reinforcement`` where given, else proposed: the lightest of 10-25 mm bars
  at 100-300 mm that gives the strength, the minimum and the crack width, no further apart than
  3h or 450 mm (BNBC Part 6 Sec 6.6.3.5 for walls; ACI 318-19 7.7.2.3 for slabs).

Stability and soil (ground tanks)
- flotation, the tank empty under the design water table: ``FS = W / U`` against
  ``flotationFS`` (1.1 by default), U the full hydrostatic pressure on the underside of the
  base (BNBC Sec 2.6.5.2) times the base's plan area, W the concrete and the soil on the base's
  projection beyond the walls (``toe``) and over a buried roof (submerged below the water
  table). BNBC sets no factor of safety for flotation (see the notes).
- bearing: the net pressure under the base full (service), less the overburden removed, against
  qa of the soil report at the founding depth (:func:`saengine.soil.bearing.allowable`) or
  ``allowableBearing``; settlement from the springs (less the rebound of the overburden) against
  BNBC Part 6 Table 6.3.8, water tank on a raft: 100 mm on sand and hard clay, 125 mm on plastic
  clay (p733, "a guide").
- ks of the springs: ``ks`` (kN/m³) or the secant ks of the whole base under its net pressure
  (:func:`saengine.substructure.raft.raft_ks`, the soil report's settlement).

Overhead tanks: the weights empty and full and the line loads along the supporting lines (for
the building's equipment load: see :func:`support_loads`).

Units: the tank dict in mm; kN, kPa, kN·m/m, kN/m, mm²/m, mm reported.
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass, field, replace
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from saengine.design.rc import EPS_CU, PHI_SHEAR, STEEL_E, bar_area, beta1, phi_axial_flexure
from saengine.design.slab import min_steel_ratio, one_way_shear, wood_armer
from saengine.plumbing.tables import SEPTIC_COVER_LIVE
from saengine.plumbing.tanks_model import (
    M11,
    M12,
    M22,
    N11,
    N22,
    Q13,
    Q23,
    Grid,
    Pressure,
    TankBox,
    box_grid,
    combine,
    combine_displacement,
    consistent_forces,
    element_axes,
    outward,
    panel_index,
    perimeter_shares,
    run_tank,
)

GAMMA_W = 9.81  # kN/m³
#: BNBC 2020 Part 6 Table 6.8.3 nominal cover [mm] by f'c (20 25 30 35 40 45 50 N/mm²), part1
#: p1069-1070; None: the strength is below the least the table gives for the exposure.
COVER_TABLE = {
    "mild": (30, 25, 20, 20, 20, 20, 20),
    "moderate": (40, 35, 30, 25, 20, 20, 20),
    "severe": (None, 45, 40, 30, 25, 25, 20),
    "verySevere": (None, None, 50, 40, 30, 30, 25),
    "extreme": (None, None, None, 60, 50, 40, 30),
}
COVER_STRENGTHS = (20, 25, 30, 35, 40, 45, 50)
#: BNBC Part 6 Sec 8.1.7.2 (a), cast against and permanently exposed to earth [mm].
COVER_AGAINST_EARTH = 75.0
#: BNBC Table 6.3.8, water tank on a raft: maximum settlement [mm] (p733).
SETTLEMENT_LIMIT = {"sand": 100.0, "plasticClay": 125.0}
#: Candidate bars for a proposal: diameters [mm] and spacings [mm].
BAR_DIAS = (10.0, 12.0, 16.0, 20.0, 25.0)
BAR_SPACINGS = (300.0, 250.0, 200.0, 175.0, 150.0, 125.0, 100.0)
STEEL_DENSITY = 7850.0  # kg/m³
#: Allowance on the bars' weight for laps, hooks and chairs in the quantity estimate.
LAP_ALLOWANCE = 0.10
GROUND_KINDS = ("underground", "septic", "rainwater")


def roof_live(spec: TankSpec, options: TankOptions) -> float:
    """The roof live load [kPa]: ``roofLive``, at least 7 kPa on a septic tank (BNBC Part 8 Sec
    6.9.12.14: the manhole cover and the roof designed for at least 7 kPa)."""
    if spec.kind == "septic":
        return max(options.roofLive, SEPTIC_COVER_LIVE)
    return options.roofLive


@dataclass
class TankOptions:
    """The design settings (Project Settings, plumbing → tanks; the integrator maps them)."""

    surcharge: float = 10.0  # kPa on the ground around a ground tank
    roofLive: float = 1.0  # kPa, BNBC Table 6.2.3 ordinary flat roof
    roofFinish: float = 1.0  # kPa superimposed dead load on the roof
    concreteUnitWeight: float = 24.0  # kN/m³
    liquidUnitWeight: float | None = None  # kN/m³; None: water 9.81
    designWaterTable: float | None = 0.0  # m below ground; None: the soil report's
    crackLimit: float = 0.2  # mm
    kt: float = 0.4
    crackingAge: float = 3.0  # days, for fct,eff of the minimum reinforcement
    flotationFS: float = 1.1
    ks: float | None = None  # kN/m³
    allowableBearing: float | None = None  # kPa, net
    k0Cohesive: float = 0.6  # K0 of a layer without φ' (assumed)
    mesh: float | None = None  # m; None: the wall height / 8
    cover: float | None = None  # mm, every face; None: BNBC Sec 8.1.7
    defaultConcrete: str = "C27.6"
    defaultRebar: str = "B420DWR"

    @classmethod
    def of(cls, data: dict[str, Any] | TankOptions | None) -> TankOptions:
        if isinstance(data, TankOptions):
            return data
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class TankContext:
    """What a tank's design needs besides the tank: the materials (id -> Material of
    :mod:`saengine.library.materials`), the soil report's boreholes
    (:class:`saengine.soil.profile.Profile`), the options and a folder for the model."""

    materials: dict[str, Any] = field(default_factory=dict)
    profiles: list[Any] = field(default_factory=list)
    options: TankOptions = field(default_factory=TankOptions)
    folder: str | Path | None = None

    @classmethod
    def build(
        cls,
        materials: Any = None,
        soil_text: str | None = None,
        options: dict[str, Any] | TankOptions | None = None,
        folder: str | Path | None = None,
    ) -> TankContext:
        """From a :class:`~saengine.library.materials.MaterialLibrary` (or None: the default
        library) and the soil report's text."""
        from saengine.library import default_material_library

        library = materials if materials is not None else default_material_library()
        found = {m.id: m for m in getattr(library, "materials", library)}
        profiles: list[Any] = []
        if soil_text:
            from saengine.substructure.piles import profiles_of

            profiles, _, _ = profiles_of(soil_text)
        return cls(found, profiles, TankOptions.of(options), folder)


# ─────────────────────────────────────── the tank ───────────────────────────────────────


@dataclass
class TankSpec:
    """A tank's dimensions [m] and materials, from the plumbing contract's tank dict."""

    id: str
    kind: str
    story: str | None
    x: float  # mm, plan centre
    y: float
    length: float  # internal, m
    width: float
    water: float  # water depth to the overflow, m
    freeboard: float
    compartments: int
    construction: str
    wall: float
    base: float
    roof: float | None
    toe: float
    top_level: float  # m, top of the tank relative to the ground (+ above)
    fc: float
    fy: float
    E: float  # MPa
    nu: float
    concrete: str
    rebar: str
    reinforcement: dict[str, Any] | None
    diameter: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def height(self) -> float:
        """Internal height, base top to roof soffit (or the wall top) [m]."""
        return self.water + self.freeboard

    @property
    def ground(self) -> bool:
        return self.kind in GROUND_KINDS


def _mm(value: Any) -> float | None:
    return None if value is None else float(value) / 1e3


def tank_spec(tank: dict[str, Any], context: TankContext) -> TankSpec:
    """The tank dict (mm) as a spec (m), with defaults for what it leaves out."""
    o = context.options
    notes: list[str] = []
    kind = str(tank.get("kind") or "underground")
    length = _mm(tank.get("length"))
    width = _mm(tank.get("width"))
    diameter = _mm(tank.get("diameter"))
    if kind != "soakWell" and (length is None or width is None):
        raise ValueError(f"tank {tank.get('id')}: its length and width are needed")
    freeboard = _mm(tank.get("freeboard"))
    if freeboard is None:
        freeboard = 0.3
        notes.append("freeboard not given: 300 mm assumed")
    water = _mm(tank.get("waterDepth"))
    if water is None:
        raise ValueError(f"tank {tank.get('id')}: its water depth is needed")
    height = water + freeboard
    wall = _mm(tank.get("walls"))
    if wall is None:
        wall = max(0.15, math.ceil(height / 12 / 0.025) * 0.025, 0.2 if kind != "soakWell" else 0)
        notes.append(f"wall thickness not given: {wall * 1e3:.0f} mm proposed (checked below)")
    base = _mm(tank.get("base"))
    if base is None:
        base = wall + 0.05
        notes.append(f"base thickness not given: {base * 1e3:.0f} mm proposed (checked below)")
    roof = _mm(tank.get("roof"))
    if roof is None:
        roof = 0.125
        notes.append("roof thickness not given: a 125 mm roof slab assumed (0: an open tank)")
    if roof <= 0:
        roof = None
    top = _mm(tank.get("topLevel"))
    if top is None:
        top = 0.15 if kind in GROUND_KINDS else 0.0
    materials = context.materials
    concrete_id = str(tank.get("material") or o.defaultConcrete)
    rebar_id = str(tank.get("rebar") or o.defaultRebar)
    concrete = materials.get(concrete_id)
    rebar = materials.get(rebar_id)
    if concrete is None or getattr(concrete, "concrete", None) is None:
        raise ValueError(f"tank {tank.get('id')}: concrete {concrete_id} is not in the materials")
    if rebar is None or getattr(rebar, "steel", None) is None:
        raise ValueError(f"tank {tank.get('id')}: rebar {rebar_id} is not in the materials")
    fc = float(concrete.concrete.fc)
    E = float(concrete.mechanical.E or 4700 * math.sqrt(fc))
    return TankSpec(
        id=str(tank.get("id") or "T"),
        kind=kind,
        story=tank.get("story"),
        x=float(tank.get("x") or 0.0),
        y=float(tank.get("y") or 0.0),
        length=length or 0.0,
        width=width or 0.0,
        water=water,
        freeboard=freeboard,
        # not given: two (BNBC Sec 5.9.2.1 for water tanks, as the sizing assumes)
        compartments=max(1, int(tank.get("compartments") or (1 if kind == "soakWell" else 2))),
        construction=str(tank.get("construction") or "rc"),
        wall=wall,
        base=base,
        roof=roof,
        toe=_mm(tank.get("toe")) or 0.0,
        top_level=top,
        fc=fc,
        fy=float(rebar.steel.fy),
        E=E,
        nu=float(concrete.mechanical.nu or 0.2),
        concrete=concrete_id,
        rebar=rebar_id,
        reinforcement=tank.get("reinforcement"),
        diameter=diameter,
        notes=notes,
    )


# ─────────────────────────────────────── soil ───────────────────────────────────────


@dataclass
class Soil:
    """The soil around a ground tank: the borehole's layers (or assumed), the design water
    table [m below ground] and the surcharge [kPa]."""

    layers: list[tuple[float, float, float, float, float | None]]  # top, bottom, γ, γsat, φ'
    water_table: float | None
    surcharge: float
    k0_cohesive: float
    source: str
    profile: Any = None

    def _layer(self, z: float) -> tuple[float, float, float, float, float | None]:
        for layer in self.layers:
            if layer[0] <= z < layer[1]:
                return layer
        return self.layers[-1] if z >= self.layers[-1][0] else self.layers[0]

    def sigma_v_eff(self, z: float) -> float:
        """σ'v [kPa] at depth z [m]: the layers' unit weights, submerged below the water
        table, integrated exactly between the layers' boundaries and the water table."""
        cuts = {0.0, z}
        cuts.update(b for layer in self.layers for b in layer[:2] if 0 < b < z)
        if self.water_table is not None and 0 < self.water_table < z:
            cuts.add(self.water_table)
        edges = sorted(cuts)
        total = 0.0
        for a, b in pairwise(edges):
            mid = (a + b) / 2
            _, _, g, gs, _ = self._layer(mid)
            below = self.water_table is not None and mid > self.water_table
            total += (gs - GAMMA_W if below else g) * (b - a)
        return total

    def sigma_v(self, z: float) -> float:
        return self.sigma_v_eff(z) + self.u(z)

    def u(self, z: float) -> float:
        if self.water_table is None or z <= self.water_table:
            return 0.0
        return GAMMA_W * (z - self.water_table)

    def k0(self, z: float) -> float:
        phi = self._layer(z)[4]
        return self.k0_cohesive if phi is None else 1 - math.sin(math.radians(phi))

    def lateral(self, z: float) -> float:
        """K0 (σ'v + q) + u [kPa] at depth z [m] (0 above the ground)."""
        if z <= 0:
            return 0.0
        return self.k0(z) * (self.sigma_v_eff(z) + self.surcharge) + self.u(z)

    def unit_weight(self, z: float) -> float:
        """The effective unit weight at depth z (submerged below the water table)."""
        _, _, g, gs, _ = self._layer(z)
        if self.water_table is not None and z > self.water_table:
            return gs - GAMMA_W
        return g


def soil_of(spec: TankSpec, context: TankContext) -> Soil:
    o = context.options
    if context.profiles:
        from saengine.substructure.piles import nearest_profile

        profile, distance = nearest_profile(context.profiles, spec.x, spec.y)
        layers = [
            (lay.top, lay.bottom, lay.gamma, lay.gamma_sat, lay.phi) for lay in profile.layers
        ]
        water = profile.water_table if o.designWaterTable is None else o.designWaterTable
        source = f"soil report: {profile.id}, {distance / 1e3:.1f} m away"
        return Soil(layers, water, o.surcharge, o.k0Cohesive, source, profile)
    water = o.designWaterTable
    return Soil(
        [(0.0, 100.0, 18.0, 20.0, 30.0)],
        water,
        o.surcharge,
        o.k0Cohesive,
        "no soil report: γ = 18, γsat = 20 kN/m³, φ' = 30° assumed",
    )


# ─────────────────────────────────── section design ───────────────────────────────────


def flexure_area(m: float, d: float, fc: float, fy: float, phi: float = 0.9) -> float | None:
    """As [mm²/m] for a factored moment m [N·mm/m] at depth d (ACI rectangular block), or
    None when the section cannot take it singly reinforced."""
    if m <= 0:
        return 0.0
    disc = d * d - 2 * m / (phi * 0.85 * fc * 1000)
    if disc < 0:
        return None
    a = d - math.sqrt(disc)
    return 0.85 * fc * 1000 * a / fy


@dataclass(frozen=True)
class TensionFlexure:
    """Bars [mm²/m] at the face in tension (``this``) and at the other face (``other``) for a
    factored moment and axial tension, with the strength reduction factor used."""

    this: float
    other: float
    phi: float
    case: str  # "flexure", "large eccentricity", "small eccentricity"
    ok: bool = True


def tension_flexure(
    m: float,
    n: float,
    h: float,
    d: float,
    d_other: float,
    fc: float,
    fy: float,
    es: float = STEEL_E,
) -> TensionFlexure:
    """Bars for a factored moment ``m`` [N·mm/m] stretching this face and an axial force ``n``
    [N/m] (tension positive; compression is conservatively left out) on a section ``h`` deep
    with this face's bars at depth ``d`` from the other face and the other face's bars at depth
    ``d_other`` from this face (both effective depths, mm).

    ``ds = d - h/2`` (centroid to this face's bars), ``dc = d_other - h/2``; e = m / n. With
    e ≤ ds the force lies between the bars: ``As = n (dc + e) / (φ fy (ds + dc))`` here and
    ``n (ds - e) / (φ fy (ds + dc))`` at the other face, φ = 0.90. Otherwise the moment about
    this face's bars ``Ms = m - n ds`` is resisted by the compression block (``a`` from ``Ms =
    φ 0.85 f'c b a (d - a/2)``) and ``As = 0.85 f'c b a / fy + n / (φ fy)``, φ from εt (ACI
    21.2.2, once re-solved)."""
    n = max(n, 0.0)
    m = max(m, 0.0)
    ds, dc = d - h / 2, d_other - h / 2
    if n > 0 and m / n <= ds:
        e = m / n
        phi = 0.9
        return TensionFlexure(
            n * (dc + e) / (phi * fy * (ds + dc)),
            n * (ds - e) / (phi * fy * (ds + dc)),
            phi,
            "small eccentricity",
        )
    ms = m - n * ds
    phi = 0.9
    for _ in range(2):
        disc = d * d - 2 * ms / (phi * 0.85 * fc * 1000)
        if disc < 0:
            return TensionFlexure(math.inf, 0.0, phi, "large eccentricity", ok=False)
        a = d - math.sqrt(disc)
        c = a / beta1(fc)
        eps_t = EPS_CU * (d - c) / c if c > 0 else math.inf
        new = phi_axial_flexure(eps_t, fy, es)
        if abs(new - phi) < 1e-9:
            break
        phi = new
    area = 0.85 * fc * 1000 * a / fy + n / (phi * fy)
    return TensionFlexure(area, 0.0, phi, "flexure" if n == 0 else "large eccentricity")


@dataclass(frozen=True)
class Cracked:
    """Elastic cracked section: stress in this face's bars [MPa], neutral axis depth from the
    other face [mm] (≤ 0: the whole section in tension) and the strains at this face and the
    other."""

    sigma_s: float
    x: float
    eps_this: float
    eps_other: float


def cracked_section(
    m: float,
    n: float,
    h: float,
    d1: float,
    a1: float,
    d2: float,
    a2: float,
    es: float,
    ec: float,
) -> Cracked | None:
    """The cracked section under a service moment ``m`` [N·mm/m] stretching this face and an
    axial force ``n`` [N/m] (tension positive, compression left out), b = 1000 mm: this face's
    bars ``a1`` [mm²/m] at depth ``d1`` from the other face, the other face's ``a2`` at depth
    ``d2`` from the other face (its cover to the bars' centre). None when this face is not in
    tension."""
    n = max(n, 0.0)
    if m <= 0 and n <= 0:
        return None
    b = 1000.0
    # The whole section in tension: the bars alone, ε = ε0 + κ y (y from the other face). The
    # system's determinant is es² a1 a2 (d1 - d2)²: with both layers at one depth (a panel too
    # thin for two layers at their covers) the bars alone take no moment, so the cracked
    # section with its compression zone below is used.
    if a2 > 0 and n > 0 and abs(d1 - d2) > 1e-6 * h:
        matrix = np.array(
            [
                [es * (a1 + a2), es * (a1 * d1 + a2 * d2)],
                [
                    es * (a1 * (d1 - h / 2) + a2 * (d2 - h / 2)),
                    es * (a1 * d1 * (d1 - h / 2) + a2 * d2 * (d2 - h / 2)),
                ],
            ]
        )
        eps0, kappa = np.linalg.solve(matrix, [n, m])
        if eps0 >= -1e-12:
            return Cracked(
                float(es * (eps0 + kappa * d1)), -math.inf, eps0 + kappa * h, float(eps0)
            )
    if m <= 0:
        return None

    def forces(x: float) -> tuple[float, float]:
        n_int = es * (a1 * (d1 - x) + a2 * (d2 - x)) - ec * b * x * x / 2
        m_int = es * (a1 * (d1 - x) * (d1 - h / 2) + a2 * (d2 - x) * (d2 - h / 2))
        m_int += ec * b * x * x / 2 * (h / 2 - x / 3)
        return n_int, m_int

    # x where the internal force vanishes (pure bending).
    qa, qb, qc = ec * b / 2, es * (a1 + a2), -es * (a1 * d1 + a2 * d2)
    x0 = (-qb + math.sqrt(qb * qb - 4 * qa * qc)) / (2 * qa)
    if n <= 0:
        x = x0
    else:

        def g(x: float) -> float:
            n_int, m_int = forces(x)
            return m_int * n - n_int * m

        lo, hi = 0.0, x0
        if g(lo) >= 0:
            x = 0.0
        else:
            for _ in range(80):
                mid = (lo + hi) / 2
                if g(mid) < 0:
                    lo = mid
                else:
                    hi = mid
            x = (lo + hi) / 2
    _, m_int = forces(x)
    if abs(m_int) < 1e-9:
        raise ValueError(f"a {h:g} mm panel is too thin for its two layers of bars at their covers")
    kappa = m / m_int
    return Cracked(float(es * kappa * (d1 - x)), float(x), kappa * (h - x), -kappa * x)


def fctm(fc: float) -> float:
    """EN 1992-1-1 Table 3.1, mean axial tensile strength [MPa] (fck ≤ 50 MPa; fck = f'c)."""
    return 0.30 * fc ** (2 / 3)


def fctm_at(fc: float, days: float) -> float:
    """fctm(t) = βcc(t) fctm, βcc = exp(0.25 (1 - √(28/t))) (EN 1992-1-1 3.1.2, cement class N,
    the exponent α = 1 before 28 days)."""
    if days >= 28:
        return fctm(fc)
    return math.exp(0.25 * (1 - math.sqrt(28 / days))) * fctm(fc)


def crack_width(
    cracked: Cracked,
    h: float,
    d: float,
    cover: float,
    dia: float,
    spacing: float,
    area: float,
    fct_eff: float,
    es: float,
    ec: float,
    kt: float = 0.4,
) -> dict[str, float]:
    """EN 1992-1-1:2004 7.3.4: wk [mm] and its terms, per metre width (b = 1000 mm)."""
    sigma = max(cracked.sigma_s, 0.0)
    whole = cracked.x <= 0
    if whole:
        hc = min(2.5 * (h - d), h / 2)
        e1, e2 = max(cracked.eps_this, 1e-12), max(cracked.eps_other, 0.0)
        k2 = (e1 + e2) / (2 * e1)
        depth = h
    else:
        hc = min(2.5 * (h - d), (h - cracked.x) / 3, h / 2)
        k2 = 0.5
        depth = h - cracked.x
    rho = area / (1000 * hc)
    alpha = es / ec
    strain = (sigma - kt * fct_eff / rho * (1 + alpha * rho)) / es
    strain = max(strain, 0.6 * sigma / es)
    if spacing <= 5 * (cover + dia / 2):
        sr = 3.4 * cover + 0.8 * k2 * 0.425 * dia / rho
    else:
        sr = 1.3 * depth
    return {
        "wk": sr * strain,
        "sr_max": sr,
        "strain": strain,
        "rho_eff": rho,
        "hc_ef": hc,
        "k2": k2,
        "alpha_e": alpha,
        "sigma_s": sigma,
    }


def min_area(h: float, fc: float, fy: float, days: float) -> float:
    """EN 1992-1-1 Eq. (7.1) per face [mm²/m]: kc = 1.0, k by h, Act = 1000 h / 2, σs = fy,
    fct,eff = fctm(t)."""
    k = 1.0 if h <= 300 else 0.65 if h >= 800 else 1.0 - 0.35 * (h - 300) / 500
    return 1.0 * k * fctm_at(fc, days) * 1000 * h / 2 / fy


def code_min_area(panel: str, direction: str, h: float, fy: float, dia: float) -> float:
    """BNBC Part 6 Sec 6.6.3.2 / 6.6.3.3 (walls) or ACI 318-19 7.6.1.1 (slabs), half per
    face [mm²/m]."""
    if panel in ("Base", "Roof"):
        ratio = min_steel_ratio(fy)
    elif direction == "vertical":
        ratio = 0.0012 if dia <= 16 and fy >= 420 else 0.0015
    else:
        ratio = 0.0020 if dia <= 16 and fy >= 420 else 0.0025
    return ratio * 1000 * h / 2


def table_cover(exposure: str, fc: float) -> tuple[float, str | None]:
    """BNBC Table 6.8.3 nominal cover for the exposure at f'c (the column of the largest
    tabulated strength not above f'c), and a note when f'c is below the table's least."""
    row = COVER_TABLE[exposure]
    best, note = None, None
    for strength, cover in zip(COVER_STRENGTHS, row, strict=True):
        if fc + 1e-9 >= strength and cover is not None:
            best = cover
    if best is None:
        first = next(c for c in row if c is not None)
        least = COVER_STRENGTHS[row.index(first)]
        note = (
            f"f'c = {fc:g} MPa is below the {least} N/mm² BNBC Table 6.8.3 asks for "
            f"{exposure} exposure"
        )
        best = first
    return float(best), note


def face_cover(spec: TankSpec, panel: str, face: str, dia: float, options: TankOptions) -> float:
    """Nominal cover [mm] of a face (BNBC Part 6 Sec 8.1.7; the larger value, 8.1.7.4)."""
    if options.cover is not None:
        return options.cover
    weather = 50.0 if dia >= 19 else 40.0  # Sec 8.1.7.2 (b)
    liquid = (
        (panel not in ("Base", "Roof") and face == "inner")
        or (panel == "Base" and face == "top")
        or (panel == "Roof" and face == "bottom")
        or panel.startswith("Partition")
    )
    if liquid:
        return table_cover("severe", spec.fc)[0]
    if spec.ground:
        if panel == "Base" and face == "bottom":
            return COVER_AGAINST_EARTH
        return max(weather, table_cover("moderate", spec.fc)[0])
    return max(weather, table_cover("severe", spec.fc)[0])


def shear_capacity(rho: float, d: float, h: float, fc: float, tension: float) -> float:
    """φVc [N/m] of a slab strip without shear reinforcement under an axial tension [N/m]:
    ACI 318-19 Table 22.5.5.1 (c) with ``Nu/(6Ag)``, Nu negative in tension, Vc ≥ 0."""
    phi_vc, _ = one_way_shear(rho, d, fc)
    reduction = PHI_SHEAR * max(tension, 0.0) * d / (6 * h)
    return max(phi_vc - reduction, 0.0)


# ─────────────────────────────────────── loads ───────────────────────────────────────


@dataclass
class Model:
    """The tank's analysis box and its model-to-tank geometry [m]."""

    box: TankBox
    grid: Grid
    water_level: float  # model z of the water surface
    top: float  # model z of the top of the tank (roof's top or wall top)
    ground: float  # model z of the ground
    bays: list[tuple[float, float]]  # x range of each compartment


def toe_area(spec: TankSpec) -> float:
    """Plan area [m²] of the base's projection beyond the walls' outer faces."""
    lo, wo = spec.length + 2 * spec.wall, spec.width + 2 * spec.wall
    return (lo + 2 * spec.toe) * (wo + 2 * spec.toe) - lo * wo


def model_of(spec: TankSpec, ks: float, options: TankOptions) -> Model:
    length = spec.length + spec.wall
    width = spec.width + spec.wall
    height = spec.base / 2 + spec.height + (spec.roof / 2 if spec.roof else 0.0)
    box = TankBox(
        spec.id,
        length,
        width,
        height,
        spec.wall,
        spec.base,
        spec.roof,
        spec.E * 1e6,
        spec.nu,
        spec.compartments,
        options.mesh,
        "springs" if spec.ground else "edges",
        ks=ks * 1e3,
        toe=toe_area(spec) if spec.ground else 0.0,
    )
    grid = box_grid(box)
    top = height + (spec.roof / 2 if spec.roof else 0.0)
    n = spec.compartments
    bays = [(length * k / n, length * (k + 1) / n) for k in range(n)]
    return Model(box, grid, spec.base / 2 + spec.water, top, top - spec.top_level, bays)


def _walls(grid: Grid) -> set[str]:
    return {p for p, _ in grid.elements if p not in ("Base", "Roof")}


def perimeter_forces(grid: Grid, total: float) -> dict[int, np.ndarray]:
    """A vertical force ``total`` [N, + up] spread evenly along the base's perimeter (the walls'
    centre lines), to its nodes by their share of the perimeter."""
    return {n: np.array([0.0, 0.0, total * s]) for n, s in perimeter_shares(grid).items()}


def _add(target: dict[int, np.ndarray], extra: dict[int, np.ndarray]) -> None:
    for node, force in extra.items():
        target[node] = target.get(node, np.zeros(3)) + force


def load_patterns(
    spec: TankSpec, model: Model, soil: Soil | None, options: TankOptions
) -> tuple[dict[str, dict[int, np.ndarray]], list[dict[str, Any]]]:
    """The load cases' nodal forces [N] and their description."""
    grid, box = model.grid, model.box
    gamma_c = options.concreteUnitWeight * 1e3
    gamma_w = (options.liquidUnitWeight or GAMMA_W) * 1e3
    down = np.array([0.0, 0.0, -1.0])
    walls = _walls(grid)
    outer = {"South", "North", "West", "East"}
    loads: list[dict[str, Any]] = []
    patterns: dict[str, dict[int, np.ndarray]] = {}

    # D: self weight, roof finish, earth over a buried roof.
    def weight(t: float) -> Any:
        return lambda _p: gamma_c * t

    def vertical(_panel: str, _centre: np.ndarray) -> np.ndarray:
        return down

    dead = [Pressure({"Base"}, weight(spec.base), vertical)]
    if spec.roof:
        dead.append(Pressure({"Roof"}, weight(spec.roof), vertical))
    dead.append(Pressure(walls, weight(spec.wall), vertical))
    cover = max(-spec.top_level, 0.0) if spec.ground else 0.0
    if spec.roof:
        extra = options.roofFinish * 1e3
        if cover > 0 and soil is not None:
            extra += soil.sigma_v(cover) * 1e3
        if extra:
            dead.append(Pressure({"Roof"}, lambda _p: extra, lambda _a, _b: down))
    patterns["D"] = consistent_forces(grid, dead)
    toe_plan = 0.0
    if spec.ground and spec.toe > 0:
        # The toe is not meshed: its weight and the soil on it (total unit weight: the uplift
        # on its underside is in H) as a line load along the base's perimeter, where the toe's
        # springs are too (TankBox.toe), so its weight goes to the soil under it unless the base
        # lifts off and the toe holds it down.
        toe_plan = toe_area(spec)
        toe_height = model.ground - spec.base / 2  # ground to the toe's top
        on_toe = soil.sigma_v(toe_height) if soil is not None and toe_height > 0 else 0.0
        toe_load = (options.concreteUnitWeight * spec.base + on_toe) * toe_plan * 1e3
        _add(patterns["D"], perimeter_forces(grid, -toe_load))
        loads.append(
            {
                "case": "D",
                "name": "Toe and the soil on it",
                "value": round(toe_load / 1e3, 1),
                "unit": "kN",
                "note": f"toe {spec.toe * 1e3:.0f} mm, {toe_plan:.2f} m², as a line load along "
                "the base's perimeter with the toe's springs (the toe is not meshed)",
            }
        )
    loads.append(
        {
            "case": "D",
            "name": "Self weight",
            "value": options.concreteUnitWeight,
            "unit": "kN/m³",
            "note": f"walls {spec.wall * 1e3:.0f}, base {spec.base * 1e3:.0f}"
            + (f", roof {spec.roof * 1e3:.0f} mm" if spec.roof else " mm, open top"),
        }
    )
    if spec.roof:
        loads.append(
            {
                "case": "D",
                "name": "Roof finish",
                "value": options.roofFinish,
                "unit": "kPa",
                "note": "superimposed dead load",
            }
        )
        if cover > 0 and soil is not None:
            loads.append(
                {
                    "case": "D",
                    "name": "Earth over the roof",
                    "value": round(soil.sigma_v(cover), 2),
                    "unit": "kPa",
                    "note": f"{cover * 1e3:.0f} mm of cover",
                }
            )

    zw = model.water_level

    def hydro(p: np.ndarray) -> float:
        return gamma_w * max(zw - p[2], 0.0)

    def push(panel: str, _centre: np.ndarray) -> np.ndarray:
        return outward(box, grid, panel)

    half = spec.wall / 2
    floor = gamma_w * spec.water  # on the base's top, inside the walls' faces only

    def floor_of(x0: float, x1: float) -> Pressure:
        clip = (x0 + half, x1 - half, half, box.width - half)
        return Pressure({"Base"}, lambda _p: floor, lambda _a, _b: down, clip)

    patterns["F"] = consistent_forces(
        grid,
        [Pressure(outer, hydro, push), *(floor_of(a, b) for a, b in model.bays)],
    )
    loads.append(
        {
            "case": "F",
            "name": "Liquid, full to the overflow",
            "value": round(gamma_w / 1e3 * zw, 2),
            "unit": "kPa",
            "note": f"γ = {gamma_w / 1e3:g} kN/m³ × {zw:.2f} m on the walls (to the base's "
            f"mid-plane), {floor / 1e3:.2f} kPa on the floor inside the walls",
        }
    )
    if spec.compartments > 1:
        for k, (x0, x1) in enumerate(model.bays):

            def inside(p: np.ndarray, x0: float = x0, x1: float = x1) -> bool:
                return x0 - 1e-9 <= p[0] <= x1 + 1e-9

            def value(p: np.ndarray, inside: Any = inside) -> float:
                return hydro(p) if inside(p) else 0.0

            panels = {"South", "North"}
            pressures = [floor_of(x0, x1)]
            sides = Pressure(panels, value, push)
            pressures.append(sides)
            if k == 0:
                pressures.append(Pressure({"West"}, hydro, push))
            else:
                pressures.append(
                    Pressure({f"Partition {k}"}, hydro, lambda _a, _b: np.array([-1.0, 0.0, 0.0]))
                )
            if k == spec.compartments - 1:
                pressures.append(Pressure({"East"}, hydro, push))
            else:
                pressures.append(
                    Pressure({f"Partition {k + 1}"}, hydro, lambda _a, _b: np.array([1.0, 0, 0]))
                )
            # The element centres decide which wall elements carry the compartment's water.
            forces = consistent_forces(grid, pressures)
            patterns[f"F{k + 1}"] = forces
        loads.append(
            {
                "case": "F1..",
                "name": "One compartment full, the others empty",
                "value": round(gamma_w / 1e3 * zw, 2),
                "unit": "kPa",
                "note": "loads the partitions from one side",
            }
        )
    if spec.ground and soil is not None:

        def depth(p: np.ndarray) -> float:
            return model.ground - p[2]

        def earth(p: np.ndarray) -> float:
            return soil.lateral(depth(p)) * 1e3

        def inward(panel: str, _c: np.ndarray) -> np.ndarray:
            return -outward(box, grid, panel)

        under = model.ground + spec.base / 2  # depth of the base's underside
        uplift = soil.u(under) * 1e3
        pressures = [Pressure(outer, earth, inward)]
        if uplift:
            pressures.append(
                Pressure({"Base"}, lambda _p: uplift, lambda _a, _b: np.array([0.0, 0.0, 1.0]))
            )
        patterns["H"] = consistent_forces(grid, pressures)
        if uplift and toe_plan:
            _add(patterns["H"], perimeter_forces(grid, uplift * toe_plan))
        bottom = depth(np.array([0.0, 0.0, 0.0]))
        loads.append(
            {
                "case": "H",
                "name": "Earth pressure at rest + groundwater + surcharge",
                "value": round(soil.lateral(bottom), 2),
                "unit": "kPa",
                "note": f"at {bottom:.2f} m below ground: K0 = {soil.k0(bottom):.3f}, "
                f"σ'v = {soil.sigma_v_eff(bottom):.1f} kPa, u = {soil.u(bottom):.1f} kPa, "
                f"q = {soil.surcharge:g} kPa; {soil.source}",
            }
        )
        if uplift:
            loads.append(
                {
                    "case": "H",
                    "name": "Uplift on the base",
                    "value": round(uplift / 1e3, 2),
                    "unit": "kPa",
                    "note": f"design water table {soil.water_table:.2f} m below "
                    "ground (BNBC Sec 2.6.5.2)",
                }
            )
    if spec.roof:
        live = roof_live(spec, options) * 1e3
        patterns["Lr"] = consistent_forces(
            grid, [Pressure({"Roof"}, lambda _p: live, lambda _a, _b: down)]
        )
        loads.append(
            {
                "case": "Lr",
                "name": "Roof live load",
                "value": roof_live(spec, options),
                "unit": "kPa",
                "note": "BNBC Part 8 Sec 6.9.12.14, septic tank roof and cover at least 7 kPa"
                if spec.kind == "septic"
                else "BNBC Part 6 Table 6.2.3 ordinary flat roof",
            }
        )
    return patterns, loads


def combinations(spec: TankSpec, patterns: dict[str, Any]) -> list[dict[str, Any]]:
    """BNBC 2020 Part 6 Sec 2.7.3.1 (strength) and 2.7.2.1 (service) combinations of the
    tank's load cases."""
    has_h = "H" in patterns
    lr = "Lr" in patterns
    fluids = ["F"] + [k for k in patterns if k.startswith("F") and k != "F"]
    out: list[dict[str, Any]] = []

    def add(kind: str, number: str, factors: dict[str, float]) -> None:
        factors = {k: v for k, v in factors.items() if v and (k in patterns)}
        name = " + ".join((f"{v:g}{k}" if v != 1 else k) for k, v in factors.items())
        out.append({"name": name, "kind": kind, "bnbc": number, "factors": factors})

    for f in fluids:
        add("strength", "2.7.3.1 (1)", {"D": 1.4, f: 1.4})
        add("strength", "2.7.3.1 (2), H = 0", {"D": 1.2, f: 1.2, "Lr": 0.5 if lr else 0})
        if has_h:
            add("strength", "2.7.3.1 (2)", {"D": 1.2, f: 1.2, "H": 1.6, "Lr": 0.5 if lr else 0})
    if has_h:
        add("strength", "2.7.3.1 (2), F = 0", {"D": 1.2, "H": 1.6, "Lr": 0.5 if lr else 0})
        add("strength", "2.7.3.1 (6), W = 0", {"D": 0.9, "H": 1.6})
    if lr:
        add("strength", "2.7.3.1 (3)", {"D": 1.2, "Lr": 1.6})
    for f in fluids:
        add("service", "2.7.2.1 (1)", {"D": 1.0, f: 1.0})
        if has_h:
            add("service", "2.7.2.1 (2)", {"D": 1.0, f: 1.0, "H": 1.0})
    if has_h:
        add("service", "2.7.2.1 (2), F = 0", {"D": 1.0, "H": 1.0})
    if lr:
        add("service", "2.7.2.1 (3)", {"D": 1.0, "F": 1.0, "H": 1.0 if has_h else 0, "Lr": 1.0})
    if has_h:
        add("service", "2.7.2.1 (7), W = 0", {"D": 0.6, "H": 1.0})
    return out


# ─────────────────────────────────────── design ───────────────────────────────────────


@dataclass
class Bars:
    dia: float
    spacing: float

    @property
    def area(self) -> float:
        return bar_area(self.dia) * 1000 / self.spacing

    def label(self) -> str:
        return f"Ø{self.dia:g} @ {self.spacing:g}"


#: Faces and directions per kind of panel: (face name at local +3, face name at local -3).
DIRECTIONS = {"wall": ("horizontal", "vertical"), "slab": ("X", "Y")}


def _panel_faces(model: Model, panel: str) -> tuple[str, str]:
    """(face at +e3, face at -e3) of a panel."""
    quad = next(q for p, q in model.grid.elements if p == panel)
    _, _, e3 = element_axes(model.grid, quad)
    if panel in ("Base", "Roof"):
        return ("top", "bottom") if e3[2] > 0 else ("bottom", "top")
    if panel.startswith("Partition"):
        return ("east", "west") if e3[0] > 0 else ("west", "east")
    out = outward(model.box, model.grid, panel)
    return ("outer", "inner") if e3 @ out > 0 else ("inner", "outer")


def _layer_bars(spec: TankSpec, panel: str, face: str, direction: str) -> Bars | None:
    """Bars the tank's ``reinforcement`` gives for a panel, face and direction."""
    given = spec.reinforcement or {}
    group = "base" if panel == "Base" else "roof" if panel == "Roof" else "walls"
    data = given.get(group) or {}
    if group == "walls" and panel in given.get("panels", {}):
        data = given["panels"][panel]
    face_key = {"east": "inner", "west": "inner"}.get(face, face)
    entry = (data.get(face_key) or {}).get(direction)
    if not entry:
        return None
    return Bars(float(entry["dia"]), float(entry["spacing"]))


def _depths(
    h: float, cover: float, outer_dia: float, inner_dia: float, outer: bool
) -> tuple[float, float]:
    """(effective depth from the other face, clear cover) of a layer: the outer layer of a
    face (walls: vertical bars; slabs: X) or the inner one."""
    if outer:
        return h - cover - outer_dia / 2, cover
    return h - cover - outer_dia - inner_dia / 2, cover + outer_dia


def _location(index: Any, node: int, panel: str) -> str:
    nodes, pa, pb = index
    key = next(k for k, v in nodes.items() if v == node)
    a, b = key
    na, nb = len(pa) - 1, len(pb) - 1
    if panel in ("Base", "Roof"):
        edge = a in (0, na) or b in (0, nb)
        return "edge" if edge else "mid-panel"
    if b == 0:
        return "base" if a not in (0, na) else "base corner"
    if b == nb:
        return "top"
    if a in (0, na):
        return "corner"
    return "mid-panel"


def design_panels(
    spec: TankSpec,
    model: Model,
    results: Any,
    combos: list[dict[str, Any]],
    options: TankOptions,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Per panel, face and direction: the demands, the bars and the crack widths; the panels'
    force envelopes; the shear checks; notes."""
    notes: list[str] = []
    index = panel_index(model.grid)
    strength = [c for c in combos if c["kind"] == "strength"]
    service = [c for c in combos if c["kind"] == "service"]
    combined = {c["name"]: combine(results, c["factors"]) for c in combos}
    es, ec = STEEL_E, spec.E
    fct = fctm(spec.fc)
    entries: list[dict[str, Any]] = []
    envelopes: list[dict[str, Any]] = []
    shears: list[dict[str, Any]] = []
    panels = sorted(index, key=lambda p: (p in ("Base", "Roof"), p))
    for panel in panels:
        slab = panel in ("Base", "Roof")
        h = (spec.base if panel == "Base" else spec.roof or 0.0) if slab else spec.wall
        h *= 1e3
        plus, minus = _panel_faces(model, panel)
        dirs = DIRECTIONS["slab" if slab else "wall"]
        # Demands per (face, direction): strength (M, N, combo, node), service (M, N, combo).
        demand: dict[tuple[str, str], list[tuple[float, float, str, int]]] = {}
        serve: dict[tuple[str, str], list[tuple[float, float, str, int]]] = {}
        envelope: dict[str, Any] = {"panel": panel, "thickness": round(h)}
        for combo in strength + service:
            values = combined[combo["name"]].get(panel, {})
            for node, raw in values.items():
                v = raw.copy()
                v[M11 : M12 + 1] *= 1e3  # N·m/m -> N·mm/m (N/m is N per 1000 mm already)
                wa = wood_armer(-v[M11], -v[M22], -v[M12])  # bottom = -e3 face
                for k, direction in enumerate(dirs):
                    n = v[N11] if k == 0 else v[N22]
                    for face, moment, signed in (
                        (plus, wa[2 + k], v[M11 if k == 0 else M22]),
                        (minus, wa[k], -v[M11 if k == 0 else M22]),
                    ):
                        if combo["kind"] == "strength":
                            demand.setdefault((face, direction), []).append(
                                (moment, n, combo["name"], node)
                            )
                        else:
                            serve.setdefault((face, direction), []).append(
                                (signed, n, combo["name"], node)
                            )
        # Envelope of the factored moments and forces (kN·m/m, kN/m).
        for (face, direction), rows in demand.items():
            top = max(rows, key=lambda r: r[0])
            envelope[f"M {direction} {face}"] = {
                "value": round(top[0] / 1e6, 2),
                "combination": top[2],
                "location": _location(index[panel], top[3], panel),
            }
        for k, direction in enumerate(dirs):
            rows = [
                (v[N11 if k == 0 else N22], c["name"], node)
                for c in strength
                for node, v in combined[c["name"]].get(panel, {}).items()
            ]
            if rows:
                top = max(rows, key=lambda r: r[0])
                envelope[f"N {direction}"] = {
                    "value": round(top[0] / 1e3, 2),
                    "combination": top[1],
                    "location": _location(index[panel], top[2], panel),
                }
        envelopes.append(envelope)
        # Bars per face and direction.
        chosen: dict[tuple[str, str], Bars] = {}
        given: dict[tuple[str, str], Bars | None] = {
            (face, direction): _layer_bars(spec, panel, face, direction)
            for face in (plus, minus)
            for direction in dirs
        }
        for _ in range(2):  # the second pass with the other layer's bars known
            for face in (plus, minus):
                other = minus if face == plus else plus
                for k, direction in enumerate(dirs):
                    key = (face, direction)
                    outer_layer = k == 1 if not slab else k == 0
                    other_dir = dirs[1 - k]
                    neighbour = chosen.get((face, other_dir)) or given.get((face, other_dir))
                    neighbour_dia = neighbour.dia if neighbour else 12.0
                    candidates = (
                        [given[key]]
                        if given[key]
                        else [Bars(dia, s) for dia in BAR_DIAS for s in BAR_SPACINGS]
                    )
                    candidates.sort(key=lambda b: (b.area, -b.spacing))
                    pick, record = None, None
                    for bars in candidates:
                        cover = face_cover(spec, panel, face, bars.dia, options)
                        outer_dia = bars.dia if outer_layer else neighbour_dia
                        inner_dia = neighbour_dia if outer_layer else bars.dia
                        d, clear = _depths(h, cover, outer_dia, inner_dia, outer_layer)
                        other_bars = chosen.get((other, direction)) or given.get((other, direction))
                        other_cover = face_cover(spec, panel, other, 12.0, options)
                        d_other = h - other_cover - (other_bars.dia if other_bars else 12.0)
                        record = _check_layer(
                            spec,
                            panel,
                            h,
                            d,
                            d_other,
                            clear,
                            bars,
                            other_bars,
                            other_cover,
                            demand.get(key, []),
                            demand.get((other, direction), []),
                            serve.get(key, []),
                            direction,
                            options,
                            fct,
                            es,
                            ec,
                        )
                        record.update({"cover": cover})
                        limit = min(3 * h, 450.0)
                        if record["ok_strength"] and record["ok_crack"] and bars.spacing <= limit:
                            pick = bars
                            break
                    if pick is None:
                        pick = candidates[-1]
                    chosen[key] = pick
                    if _ == 1:
                        entries.append(
                            _entry(panel, face, direction, pick, record, bool(given[key]), slab)
                        )
        # One-way shear per direction at d from the faces of the supporting panels.
        for k, direction in enumerate(dirs):
            bars = [chosen[(f, direction)] for f in (plus, minus)]
            covers = [
                face_cover(spec, panel, f, b.dia, options)
                for f, b in zip((plus, minus), bars, strict=True)
            ]
            d = h - max(covers) - max(b.dia for b in bars)
            windows = _shear_windows(spec, model, panel, k, d / 1e3)
            joints = [pos for pos, _ in _supports(spec, model, panel, 1 - k)]
            worst = None
            for c in strength:
                values = combined[c["name"]].get(panel, {})
                for q, n, where in _shear_demands(index[panel], values, k, windows, joints):
                    if worst is None or q > worst[0]:
                        worst = (q, n, c["name"], where)
            if worst is None:
                continue
            q, n, cname, where = worst
            rho = min(b.area for b in bars) / (1000 * d)
            capacity = shear_capacity(rho, d, h, spec.fc, n)
            spans = "vertical span" if direction == "vertical" else f"{direction} span"
            shears.append(
                _check(
                    f"{panel}: one-way shear ({spans})",
                    q / 1e3,
                    capacity / 1e3,
                    "kN/m",
                    cname,
                    f"{where}, d = {d:.0f} mm, N = {n / 1e3:.1f} kN/m (ACI 318-19 Table "
                    "22.5.5.1 (c) with Nu/(6Ag); the critical section at d from the face)",
                )
            )
    return entries, envelopes, shears, notes


def _supports(spec: TankSpec, model: Model, panel: str, k: int) -> list[tuple[float, float]]:
    """The panels across a panel's a (k = 0) or b (k = 1) direction: (position [m] of the
    joint's line, half the supporting panel's thickness [m])."""
    grid = model.grid
    walls = [(float(grid.xs[0]), spec.wall / 2)]
    walls += [(float(grid.xs[p]), spec.wall / 2) for p in grid.partitions]
    walls += [(float(grid.xs[-1]), spec.wall / 2)]
    across = [(0.0, spec.wall / 2), (float(grid.ys[-1]), spec.wall / 2)]
    height = [(0.0, spec.base / 2)]
    if spec.roof:
        height.append((float(grid.zs[-1]), spec.roof / 2))
    if panel in ("Base", "Roof"):
        return walls if k == 0 else across
    if panel in ("South", "North"):
        return walls if k == 0 else height
    return across if k == 0 else height


def _shear_windows(
    spec: TankSpec, model: Model, panel: str, k: int, d: float
) -> list[tuple[float, float]]:
    """The stretches [m, along the panel's a (k = 0) or b (k = 1) lines] between the critical
    sections at d from the faces of the panels supporting it (walls: the base, the roof and the
    walls they meet; base and roof: the walls)."""
    grid = model.grid
    supports = _supports(spec, model, panel, k)
    end = float(grid.zs[-1])
    out = []
    for (s0, h0), (s1, h1) in pairwise(supports):
        lo, hi = s0 + h0 + d, s1 - h1 - d
        out.append((lo, hi) if hi > lo else ((s0 + s1) / 2, (s0 + s1) / 2))
    if len(supports) == 1:  # an open top: free above the base
        s0, h0 = supports[0]
        out.append((s0 + h0 + d, end))
    return out


def _shear_demands(
    index: Any,
    values: dict[int, np.ndarray],
    k: int,
    windows: list[tuple[float, float]],
    joints: tuple[float, ...] | list[float] = (),
) -> list[tuple[float, float, str]]:
    """|Q| [N/m] and N across the same section, along each line of the panel within the
    windows: interpolated at the windows' ends and at the nodes inside them. The lines at the
    ``joints`` (positions [m] across the lines: the joints with the panels across the panel,
    such as a slab's lines on the walls) are left out: the shells' transverse shear on a joint
    is not the panel's one-way shear and depends on the mesh."""
    nodes, pa, pb = index
    out: list[tuple[float, float, str]] = []
    lines: dict[int, list[tuple[float, int]]] = {}
    for (a, b), node in nodes.items():
        if node not in values:
            continue
        across = float(pb[b]) if k == 0 else float(pa[a])
        if any(abs(across - j) < 1e-6 for j in joints):
            continue
        if k == 0:
            lines.setdefault(b, []).append((float(pa[a]), node))
        else:
            lines.setdefault(a, []).append((float(pb[b]), node))
    q_col, n_col = (Q13, N11) if k == 0 else (Q23, N22)
    for row in lines.values():
        row.sort()
        pos = np.array([p for p, _ in row])
        q = np.array([values[n][q_col] for _, n in row])
        n_ = np.array([values[n][n_col] for _, n in row])
        for lo, hi in windows:
            points = [lo, hi, *[p for p in pos if lo < p < hi]]
            for p in points:
                where = (
                    "at d from the face" if p in (lo, hi) else f"{p - pos[0]:.2f} m along the line"
                )
                out.append((abs(float(np.interp(p, pos, q))), float(np.interp(p, pos, n_)), where))
    return out


def _check_layer(
    spec: TankSpec,
    panel: str,
    h: float,
    d: float,
    d_other: float,
    clear: float,
    bars: Bars,
    other_bars: Bars | None,
    other_cover: float,
    rows: list[tuple[float, float, str, int]],
    other_rows: list[tuple[float, float, str, int]],
    service_rows: list[tuple[float, float, str, int]],
    direction: str,
    options: TankOptions,
    fct: float,
    es: float,
    ec: float,
) -> dict[str, Any]:
    """Strength, minimum and crack width of one layer with the given bars."""
    required, governing = 0.0, None
    ok = True
    for m, n, cname, node in rows:
        found = tension_flexure(m, n, h, d, d_other, spec.fc, spec.fy)
        if not found.ok:
            ok = False
        if found.this > required:
            required, governing = found.this, (m, n, cname, node, found)
    # This face's share of the tension when the other face's moment governs.
    for m, n, _cname, _node in other_rows:
        found = tension_flexure(m, n, h, d_other, d, spec.fc, spec.fy)
        required = max(required, found.other)
    min_en = min_area(h, spec.fc, spec.fy, options.crackingAge)
    min_code = code_min_area(panel, direction, h, spec.fy, bars.dia)
    a_min = max(min_en, min_code)
    need = max(required, a_min)
    ok_strength = ok and bars.area + 1e-6 >= need
    # Crack width under the service combinations.
    worst = {"wk": 0.0}
    a2 = other_bars.area if other_bars else bars.area
    d2 = other_cover + (other_bars.dia if other_bars else 12.0) / 2
    service = sorted(service_rows, key=lambda r: -(r[0] + abs(r[1]) * h / 2))[:24]
    for m, n, cname, _node in service:
        cracked = cracked_section(m, n, h, d, bars.area, d2, a2, es, ec)
        if cracked is None:
            continue
        found = crack_width(
            cracked, h, d, clear, bars.dia, bars.spacing, bars.area, fct, es, ec, options.kt
        )
        if found["wk"] > worst["wk"]:
            worst = {**found, "combination": cname, "M": m, "N": n}
    return {
        "As_required": required,
        "As_min": a_min,
        "As_min_en": min_en,
        "As_min_code": min_code,
        "governing": governing,
        "ok_strength": ok_strength,
        "strength_possible": ok,
        "crack": worst,
        "ok_crack": worst["wk"] <= options.crackLimit + 1e-9,
        "crack_limit": options.crackLimit,
        "d": d,
    }


def _entry(
    panel: str,
    face: str,
    direction: str,
    bars: Bars,
    record: dict[str, Any],
    given: bool,
    slab: bool,
) -> dict[str, Any]:
    gov = record["governing"]
    crack = record["crack"]
    ok = record["ok_strength"] and record["ok_crack"]
    return {
        "name": panel,
        "element": "slab" if slab else "wall",
        "direction": direction,
        "face": face,
        "Mu": round(gov[0] / 1e6, 2) if gov else 0.0,  # kN·m/m
        "Nu": round(gov[1] / 1e3, 2) if gov else 0.0,  # kN/m
        "combination": gov[2] if gov else None,
        "case": gov[4].case if gov else None,
        "As_required": round(record["As_required"])
        if math.isfinite(record["As_required"])
        else None,
        "As_min": round(record["As_min"]),
        "As_provided": round(bars.area),
        "bars": bars.label(),
        "barsFrom": "tank" if given else "proposed",
        "d": round(record["d"]),
        "cover": round(record["cover"]),
        "crackWidth": round(crack.get("wk", 0.0), 3),
        "crackLimit": record["crack_limit"],
        "crackCombination": crack.get("combination"),
        "sigmaS": round(crack.get("sigma_s", 0.0), 1),
        "ok": bool(ok),
    }


def _check(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    combination: str | None,
    note: str = "",
    utilisation: float | None = None,
) -> dict[str, Any]:
    if utilisation is None:
        utilisation = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    # No capacity at all: no number (the check cannot pass), not a sentinel utilisation.
    utilisation = round(float(utilisation), 3) if math.isfinite(utilisation) else None
    return {
        "name": name,
        "demand": round(float(demand), 2),
        "capacity": round(float(capacity), 2),
        "unit": unit,
        "utilisation": utilisation,
        "combination": combination,
        "ok": utilisation is not None and utilisation <= 1.0,
        "note": note,
    }


# ─────────────────────────────── weights, stability, soil ───────────────────────────────


def volumes(spec: TankSpec) -> dict[str, float]:
    """Concrete volumes [m³] and formwork areas [m²] of a rectangular tank."""
    lo, wo = spec.length + 2 * spec.wall, spec.width + 2 * spec.wall
    h = spec.height
    walls = (2 * (spec.length + spec.wall) + 2 * (spec.width + spec.wall)) * spec.wall * h
    partitions = (spec.compartments - 1) * spec.width * spec.wall * h
    base = (lo + 2 * spec.toe) * (wo + 2 * spec.toe) * spec.base
    roof = lo * wo * (spec.roof or 0.0)
    inner = 2 * (spec.length + spec.width) * h + 2 * (spec.compartments - 1) * spec.width * h
    outer = 2 * (lo + wo) * (h + (spec.roof or 0.0))
    edges = 2 * (lo + 2 * spec.toe + wo + 2 * spec.toe) * spec.base
    soffit = (
        (spec.length * spec.width - (spec.compartments - 1) * spec.width * spec.wall)
        if spec.roof
        else 0.0
    )
    return {
        "walls": walls,
        "partitions": partitions,
        "base": base,
        "roof": roof,
        "concrete": walls + partitions + base + roof,
        "formwork": inner + outer + edges + soffit,
    }


def water_volume(spec: TankSpec) -> float:
    """The liquid to the overflow [m³] (the partitions take their share of the plan)."""
    plan = spec.length * spec.width - (spec.compartments - 1) * spec.width * spec.wall
    return plan * spec.water


BRICK_MASONRY = 19.1  # kN/m³: burnt clay brick work, 1.910 kN/m² per 100 mm (BNBC Table 6.2.2)


def shell_weight(spec: TankSpec, options: TankOptions) -> tuple[float, str]:
    """The tank's own weight empty [kN] and how it was found, by its construction: rc, the
    concrete of the walls, partitions, base and roof at the concrete's unit weight plus the roof
    finish; masonry, the walls and partitions as burnt clay brick work (BNBC 2020 Part 6 Table
    6.2.2, 1.910 kN/m² per 100 mm (p530)) on a concrete base under a concrete roof; prefab
    (a moulded or sectional tank), nil: its maker's weight is to be entered (``emptyWeight``)."""
    v = volumes(spec)
    lo, wo = spec.length + 2 * spec.wall, spec.width + 2 * spec.wall
    gc = options.concreteUnitWeight
    if spec.construction == "prefab":
        return 0.0, "prefab tank: its own weight is not known (enter the maker's empty weight)"
    finish = lo * wo * options.roofFinish if spec.roof else 0.0
    if spec.construction == "masonry":
        brick = (v["walls"] + v["partitions"]) * BRICK_MASONRY
        return (
            brick + (v["base"] + v["roof"]) * gc + finish,
            "brick walls at 19.1 kN/m³ (BNBC Table 6.2.2), concrete base and roof",
        )
    return v["concrete"] * gc + finish, f"reinforced concrete at {gc:g} kN/m³ and the roof finish"


def _rc_shell(spec: TankSpec, options: TankOptions) -> float:
    """The shell's weight as the analysis model carries it (reinforced concrete) [kN]."""
    rc = spec if spec.construction == "rc" else replace(spec, construction="rc")
    return round(shell_weight(rc, options)[0], 1)


def support_loads(spec: TankSpec, options: TankOptions, results: Any = None) -> dict[str, Any]:
    """An overhead tank's weight on the structure: empty (D: concrete and roof finish), full (D
    + F) and the roof live load [kN], with the share each supporting line takes in the model
    (kN and kN/m) when the results are given."""
    lo, wo = spec.length + 2 * spec.wall, spec.width + 2 * spec.wall
    empty, basis = shell_weight(spec, options)
    water = water_volume(spec) * (options.liquidUnitWeight or GAMMA_W)
    live = lo * wo * options.roofLive if spec.roof else 0.0
    out: dict[str, Any] = {
        "empty": round(empty, 1),
        "water": round(water, 1),
        "full": round(empty + water, 1),
        "roofLive": round(live, 1),
        "footprint": {"length": round(lo * 1e3), "width": round(wo * 1e3)},
        "pressureFull": round((empty + water) / (lo * wo), 2),  # kPa over the footprint
        "emptyBasis": basis,
    }
    if results is not None:
        grid = results.grid
        lines: dict[str, list[int]] = {}
        nx, ny = len(grid.xs) - 1, len(grid.ys) - 1
        for (i, j, k), node in grid.nodes.items():
            if k != 0:
                continue
            for name, test in (
                ("South", j == 0),
                ("North", j == ny),
                ("West", i == 0),
                ("East", i == nx),
            ):
                if test:
                    lines.setdefault(name, []).append(node)
            for m, p in enumerate(grid.partitions):
                if i == p and 0 < j < ny:
                    lines.setdefault(f"Partition {m + 1}", []).append(node)
        shares = []
        for name, nodes in lines.items():
            length = grid.xs[-1] if name in ("South", "North") else grid.ys[-1]
            row: dict[str, Any] = {"line": name, "length": round(float(length) * 1e3)}
            for case in ("D", "F", "Lr"):
                if case not in results.reactions:
                    continue
                corner = {
                    grid.nodes[(0, 0, 0)],
                    grid.nodes[(nx, 0, 0)],
                    grid.nodes[(0, ny, 0)],
                    grid.nodes[(nx, ny, 0)],
                }
                total = (
                    sum(
                        results.reactions[case].get(n, np.zeros(6))[2]
                        * (0.5 if n in corner else 1.0)
                        for n in nodes
                    )
                    / 1e3
                )
                row[case] = round(float(total), 1)
                row[f"{case} per m"] = round(float(total / length), 2)
            shares.append(row)
        out["lines"] = shares
    return out


def tank_equipment(
    tank: dict[str, Any], context: TankContext | dict[str, Any], basis: bool = False
) -> dict[str, Any]:
    """The equipment entry (``07 MEP/mep.json`` ``equipment[]``, kind "tank") of an overhead
    tank, without an analysis: its footprint and weights empty and full [kN] spread over the
    footprint, for the building's load derivation (:mod:`saengine.mep.loads`). The roof live
    load on the tank's roof is not part of it (``supportLoads.roofLive`` of the design).
    ``basis``: also say how the empty weight was found (``emptyBasis``, not an equipment field)."""
    if isinstance(context, dict):
        context = TankContext.build(context.get("materials"), None, context.get("options"))
    if tank.get("story") is None:
        raise ValueError(f"{tank.get('id')}: an overhead tank needs the story it stands on")
    spec = tank_spec(tank, context)
    loads = support_loads(spec, context.options)
    given = tank.get("emptyWeight")
    if given is not None and float(given) > 0:
        empty = round(float(given), 1)
        loads["full"] = round(empty + loads["water"], 1)
        loads["empty"], loads["emptyBasis"] = empty, "the empty weight entered in 07 MEP"
    # Equipment needs a positive empty weight: a prefab tank without its maker's weight carries
    # only its water (0.01 kN stands for nil).
    empty = max(loads["empty"], 0.01)
    return {
        "id": f"{spec.id}-tank",
        "name": f"Overhead water tank {spec.id}",
        "kind": "tank",
        "story": spec.story,
        "x": spec.x,
        "y": spec.y,
        "length": loads["footprint"]["length"],
        "width": loads["footprint"]["width"],
        "height": round((spec.height + spec.base + (spec.roof or 0.0)) * 1e3),
        "operatingWeight": round(empty + loads["water"], 2),
        "emptyWeight": empty,
        "loadAs": "area",
        **({"emptyBasis": loads["emptyBasis"]} if basis else {}),
    }


def flotation(spec: TankSpec, soil: Soil, options: TankOptions) -> dict[str, Any]:
    """Flotation of the empty tank under the design water table (service, by hand)."""
    lo, wo = spec.length + 2 * spec.wall, spec.width + 2 * spec.wall
    bo, lb = wo + 2 * spec.toe, lo + 2 * spec.toe
    depth = spec.height + spec.base + (spec.roof or 0.0) - spec.top_level  # base underside
    head = 0.0 if soil.water_table is None else max(depth - soil.water_table, 0.0)
    uplift = GAMMA_W * head * bo * lb
    concrete = volumes(spec)["concrete"] * options.concreteUnitWeight
    toe_area = bo * lb - lo * wo
    # The soil (and its pore water) over the toe and over a buried roof, total unit weights:
    # the uplift acts on the whole base, so the water above the toe and the roof bears down.
    toe_height = depth - spec.base
    toe_soil = soil.sigma_v(toe_height) * toe_area if toe_height > 0 else 0.0
    cover = max(-spec.top_level, 0.0)
    roof_soil = soil.sigma_v(cover) * lo * wo if cover > 0 else 0.0
    resisting = concrete + toe_soil + roof_soil
    fs = resisting / uplift if uplift > 0 else math.inf
    return {
        "uplift": round(uplift, 1),
        "resisting": round(resisting, 1),
        "concrete": round(concrete, 1),
        "soilOnToe": round(toe_soil, 1),
        "soilOnRoof": round(roof_soil, 1),
        "head": round(head, 3),
        "FS": round(fs, 3) if math.isfinite(fs) else None,
        "required": options.flotationFS,
        "ok": bool(fs >= options.flotationFS),
        "waterTable": soil.water_table,
    }


def bearing(
    spec: TankSpec, soil: Soil, options: TankOptions
) -> tuple[dict[str, Any], float, list[str]]:
    """Net bearing pressure of the full tank (service) against qa, and Df [m]."""
    notes: list[str] = []
    lo, wo = spec.length + 2 * spec.wall, spec.width + 2 * spec.wall
    bo, lb = wo + 2 * spec.toe, lo + 2 * spec.toe
    df = spec.height + spec.base + (spec.roof or 0.0) - spec.top_level
    weight = volumes(spec)["concrete"] * options.concreteUnitWeight
    weight += water_volume(spec) * (options.liquidUnitWeight or GAMMA_W)
    if spec.roof:
        weight += lo * wo * (options.roofFinish + roof_live(spec, options))
    toe_height = df - spec.base
    weight += (bo * lb - lo * wo) * (soil.sigma_v(toe_height) if toe_height > 0 else 0.0)
    cover = max(-spec.top_level, 0.0)
    if cover:
        weight += lo * wo * soil.sigma_v(cover)
    gross = weight / (bo * lb)
    net = gross - soil.sigma_v(df)
    qa, source = options.allowableBearing, "Project Settings"
    if qa is None and soil.profile is not None:
        from saengine.soil.bearing import allowable

        try:
            found = allowable(soil.profile, min(bo, lb), max(bo, lb), df)
            qa, source = found["qa"], f"{soil.source}, Df = {df:.2f} m"
            notes.extend(found.get("notes") or [])
        except Exception as error:  # noqa: BLE001 - the report may lack what qa needs
            notes.append(f"qa could not be computed from the soil report: {error}")
    result = {
        "gross": round(gross, 1),
        "net": round(net, 1),
        "qa": qa,
        "Df": round(df, 3),
        "source": source if qa is not None else None,
    }
    return result, df, notes


def subgrade(spec: TankSpec, soil: Soil, options: TankOptions, net: float) -> tuple[float, str]:
    """ks [kN/m³] of the springs and where it comes from."""
    if options.ks:
        return float(options.ks), "Project Settings"
    lo, wo = spec.length + 2 * spec.wall + 2 * spec.toe, spec.width + 2 * spec.wall + 2 * spec.toe
    df = spec.height + spec.base + (spec.roof or 0.0) - spec.top_level
    if soil.profile is not None:
        from saengine.substructure.raft import raft_ks

        q = max(net, 25.0)
        problem = "no settlement computed"
        try:
            found = raft_ks(soil.profile, min(lo, wo), max(lo, wo), df, q)
        except Exception as error:  # noqa: BLE001 - the report may lack what it needs
            found, problem = {}, str(error)
        if found.get("value"):
            note = found["method"] + ("" if net >= 25 else " (at least 25 kPa)")
            return float(found["value"]), note
        return 10000.0, f"10 000 kN/m³ assumed ({problem}: set ks)"
    return 10000.0, "10 000 kN/m³ assumed (no soil report: set ks)"


# ─────────────────────────────────────── soak well ───────────────────────────────────────


def design_soak_well(spec: TankSpec, soil: Soil, options: TankOptions) -> dict[str, Any]:
    """A circular soak well's ring under the earth pressure at rest: the hoop compression at
    the bottom ``N = p r`` (thin ring, the outer radius) against a plain-concrete section
    ``0.65 × 0.85 f'c t`` per metre of height (ACI 318-19 22.4.2.2 P0 of the concrete alone
    with φ 0.65 of a tied member: a first check of an RC or precast ring, the reinforcement of
    the ring not counted)."""
    r = (spec.diameter or 1.0) / 2 + spec.wall
    depth = spec.height - spec.top_level
    p = soil.lateral(depth)
    n = p * r
    capacity = 0.65 * 0.85 * spec.fc * spec.wall * 1e3  # kN/m
    check = _check(
        "Ring hoop compression at the bottom",
        n * 1.6,
        capacity,
        "kN/m",
        "1.6H",
        f"p = {p:.1f} kPa at {depth:.2f} m, r = {r:.2f} m",
    )
    return {"checks": [check], "pressure": round(p, 2)}


# ─────────────────────────────────────── the API ───────────────────────────────────────


def design_tank(tank: dict[str, Any], context: TankContext | dict[str, Any]) -> dict[str, Any]:
    """Analyse and design a tank of the plumbing contract (``plumbing.tanks[]`` of
    ``07 MEP/mep.json``). ``context``: a :class:`TankContext` or a dict with ``materials``
    (a MaterialLibrary or Material list), ``soil`` (the soil report's text), ``options``
    (:class:`TankOptions` fields) and ``folder``."""
    if isinstance(context, dict):
        context = TankContext.build(
            context.get("materials"),
            context.get("soil"),
            context.get("options"),
            context.get("folder"),
        )
    options = context.options
    spec = tank_spec(tank, context)
    notes = list(spec.notes)
    soil = soil_of(spec, context) if spec.ground or spec.kind == "soakWell" else None
    geometry = {
        "kind": spec.kind,
        "story": spec.story,
        "x": spec.x,
        "y": spec.y,
        "length": round(spec.length * 1e3),
        "width": round(spec.width * 1e3),
        "waterDepth": round(spec.water * 1e3),
        "freeboard": round(spec.freeboard * 1e3),
        "height": round(spec.height * 1e3),
        "walls": round(spec.wall * 1e3),
        "base": round(spec.base * 1e3),
        "roof": None if spec.roof is None else round(spec.roof * 1e3),
        "toe": round(spec.toe * 1e3),
        "compartments": spec.compartments,
        "topLevel": round(spec.top_level * 1e3),
        "concrete": spec.concrete,
        "rebar": spec.rebar,
        "fc": spec.fc,
        "fy": spec.fy,
        "capacity": round(water_volume(spec), 2) if spec.kind != "soakWell" else None,
    }
    result: dict[str, Any] = {
        "id": spec.id,
        "kind": spec.kind,
        "geometry": geometry,
        "loads": [],
        "cases": [],
        "walls": [],
        "base": [],
        "roof": [],
        "panels": [],
        "uplift": None,
        "bearing": None,
        "settlement": None,
        "supportLoads": None,
        "checks": [],
        "quantities": {},
        "notes": notes,
    }
    if spec.kind == "soakWell":
        assert soil is not None
        well = design_soak_well(spec, soil, options)
        result["checks"] = well["checks"]
        notes.append(
            "soak well: the ring's hoop compression only (a brick or perforated ring "
            "is not designed here)"
        )
        return plain(result)
    if spec.construction != "rc":
        notes.append(
            f"{spec.construction} construction: not designed here (the loads and weights are "
            "reported for the structure that carries it)"
        )
    if soil is not None:
        bear, df, bear_notes = bearing(spec, soil, options)
        notes.extend(bear_notes)
        ks, ks_source = subgrade(spec, soil, options, bear["net"])
    else:
        bear, df, ks, ks_source = None, 0.0, 0.0, ""
    model = model_of(spec, ks, options)
    patterns, loads = load_patterns(spec, model, soil, options)
    combos = combinations(spec, patterns)
    result["loads"] = loads
    result["cases"] = [
        {"name": c["name"], "kind": c["kind"], "bnbc": c["bnbc"], "factors": c["factors"]}
        for c in combos
    ]
    if spec.ground:
        notes.append(f"base on Winkler springs, ks = {ks:.0f} kN/m³: {ks_source}")
    else:
        notes.append(
            "base supported (pinned) along the lines of its walls: an overhead tank standing on "
            "the roof's beams under its walls; the beams' flexibility is not modelled"
        )
    folder = context.folder
    with tempfile.TemporaryDirectory(prefix="saengine-tank-") as scratch:
        results = run_tank(
            model.box,
            model.grid,
            patterns,
            folder or scratch,
            {c["name"]: c["factors"] for c in combos},
        )
    if results.lifted:
        notes.append(
            "the base lifts off the soil under "
            + ", ".join(results.lifted)
            + ": these combinations are run with compression-only springs (the base spans "
            "between the walls where it has lifted off)"
        )
    if results.floating:
        notes.append(
            "the net factored load is upward under "
            + ", ".join(results.floating)
            + ": the tank would float (see the flotation check); for these the base is "
            "designed spanning between the walls under the net uplift, held along the walls' "
            "lines as if the tank were held down"
        )
    if spec.construction == "rc":
        entries, envelopes, shears, design_notes = design_panels(
            spec, model, results, combos, options
        )
        notes.extend(design_notes)
        result["walls"] = [e for e in entries if e["element"] == "wall"]
        result["base"] = [e for e in entries if e["name"] == "Base"]
        result["roof"] = [e for e in entries if e["name"] == "Roof"]
        result["panels"] = envelopes
        checks = result["checks"]
        for e in entries:
            checks.append(
                _check(
                    f"{e['name']}: {e['direction']} bars, {e['face']} face",
                    max(e["As_required"] or math.inf, e["As_min"]),
                    e["As_provided"],
                    "mm²/m",
                    e["combination"],
                    f"{e['bars']} ({e['barsFrom']}), As,min {e['As_min']} mm²/m",
                )
            )
            checks.append(
                _check(
                    f"{e['name']}: crack width, {e['direction']} bars, {e['face']} face",
                    e["crackWidth"],
                    e["crackLimit"],
                    "mm",
                    e["crackCombination"],
                    f"EN 1992-1-1 7.3.4, σs = {e['sigmaS']} MPa, cover {e['cover']} mm",
                )
            )
        checks.extend(shears)
    if soil is not None and spec.ground:
        up = flotation(spec, soil, options)
        result["uplift"] = up
        result["checks"].append(
            _check(
                "Flotation (empty, design water table)",
                options.flotationFS,
                up["FS"] if up["FS"] is not None else options.flotationFS,
                "FS",
                "D vs U",
                f"U = {up['uplift']} kN, W = {up['resisting']} kN"
                + ("; no uplift" if up["FS"] is None else ""),
                utilisation=0.0 if up["FS"] is None else None,
            )
        )
        assert bear is not None
        result["bearing"] = bear
        if bear["qa"] is not None:
            result["checks"].append(
                _check(
                    "Bearing pressure (net, full)",
                    bear["net"],
                    bear["qa"],
                    "kPa",
                    "D + F + Lr",
                    bear["source"] or "",
                )
            )
        else:
            notes.append("no allowable bearing pressure: set one or add the soil report")
        result["settlement"] = _settlement(spec, soil, results, combos, ks, df)
        st = result["settlement"]
        result["checks"].append(
            _check(
                "Settlement (water tank on a raft, BNBC Table 6.3.8)",
                st["value"],
                st["limit"],
                "mm",
                st["combination"],
                st["note"],
            )
        )
    if not spec.ground:
        support = support_loads(spec, options, results)
        given = tank.get("emptyWeight")
        if given is not None and float(given) > 0:
            support["empty"] = round(float(given), 1)
            support["emptyBasis"] = "the empty weight entered in 07 MEP"
            support["full"] = round(support["empty"] + support["water"], 1)
        modelled = _rc_shell(spec, options)
        if abs(support["empty"] - modelled) > 0.05:
            # The model carries the shell as reinforced concrete: its D shares are scaled to
            # this tank's own weight.
            ratio = support["empty"] / modelled if modelled > 0 else 0.0
            for row in support.get("lines", []):
                for key in ("D", "D per m"):
                    if key in row:
                        row[key] = round(row[key] * ratio, 2)
        result["supportLoads"] = support
    result["quantities"] = _quantities(spec, result)
    notes.append("concrete for low permeability: w/c at most 0.50 (BNBC Part 6 Sec 5.5.1.1)")
    return plain(result)


def plain(value: Any) -> Any:
    """The result with numpy scalars as Python numbers (JSON for the RPC)."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _settlement(
    spec: TankSpec, soil: Soil, results: Any, combos: list[dict[str, Any]], ks: float, df: float
) -> dict[str, Any]:
    from saengine.soil.settlement import soil_column

    worst, cname = 0.0, None
    base_nodes = {n for (i, j, k), n in results.grid.nodes.items() if k == 0}
    rebound = soil.sigma_v(df) / ks * 1e3 if ks else 0.0
    for c in combos:
        if c["kind"] != "service":
            continue
        disp = combine_displacement(results, c["factors"])
        value = max(-disp[n][2] for n in base_nodes) * 1e3 - rebound
        if value > worst:
            worst, cname = value, c["name"]
    column = "sand"
    if soil.profile is not None:
        lo = spec.width + 2 * spec.wall + 2 * spec.toe
        column = soil_column(soil.profile, df, 2 * lo)
    limit = SETTLEMENT_LIMIT[column]
    return {
        "value": round(max(worst, 0.0), 1),
        "limit": limit,
        "combination": cname,
        "rebound": round(rebound, 1),
        "note": f"spring settlement less the rebound {rebound:.1f} mm of the overburden; "
        f"{'plastic clay' if column == 'plasticClay' else 'sand and hard clay'}",
    }


def _quantities(spec: TankSpec, result: dict[str, Any]) -> dict[str, Any]:
    v = volumes(spec)
    lo, wo = spec.length + 2 * spec.wall, spec.width + 2 * spec.wall
    areas = {
        "Base": (lo + 2 * spec.toe) * (wo + 2 * spec.toe),
        "Roof": lo * wo if spec.roof else 0.0,
    }
    h = spec.height
    for side, length in (
        ("South", spec.length + spec.wall),
        ("North", spec.length + spec.wall),
        ("West", spec.width + spec.wall),
        ("East", spec.width + spec.wall),
    ):
        areas[side] = length * h
    for m in range(1, spec.compartments):
        areas[f"Partition {m}"] = spec.width * h
    steel = 0.0
    by_dia: dict[str, float] = {}
    for e in result["walls"] + result["base"] + result["roof"]:
        mass = e["As_provided"] / 1e6 * areas.get(e["name"], 0.0) * STEEL_DENSITY
        steel += mass
        dia = str(e.get("bars", "")).removeprefix("Ø").split(" ")[0]
        by_dia[dia] = by_dia.get(dia, 0.0) + mass * (1 + LAP_ALLOWANCE)
    steel *= 1 + LAP_ALLOWANCE
    return {
        "concrete": round(v["concrete"], 2),
        "formwork": round(v["formwork"], 2),
        "reinforcement": round(steel),
        # kg by bar diameter [mm] (the bill's reinforcement lines), laps included.
        "byDiameter": {k: round(m, 1) for k, m in sorted(by_dia.items()) if k and m > 0},
        "unit": {"concrete": "m³", "formwork": "m²", "reinforcement": "kg"},
        "note": f"reinforcement: the bars per m² of each panel + {LAP_ALLOWANCE:.0%} for laps",
    }

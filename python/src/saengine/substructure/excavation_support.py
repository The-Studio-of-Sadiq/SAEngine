"""Staged excavations: the embedded wall on soil springs, its section and its supports
(alpha 9 P1).

The method and every value are the code pack's ``excavationSupport`` table
(:class:`saengine.codes.excavation_tables.ExcavationSupportTable`); a pack without it does not
analyse staged excavations. The limit equilibrium of the wall (embedment, Blum) stays in
:mod:`saengine.substructure.embedded_wall` (alpha 9 P7); the earth pressures come from the one
engine, :mod:`saengine.substructure.earth_pressure`. The default pack's BNBC 2020 asks for
retained excavation sides, sheet piles and tie-back anchors (Part 6 Sec 3.12, 3.16) and names
no method: every method here is SAEngine practice there, and the report says so.

An excavation's embedded wall (``excavation.wall``, :class:`saengine.library.substructure.
EmbeddedWall`) with a ``wallType`` is analysed per metre run, depths z [m] below the retained
ground (the top of the wall):

- **stages** (``wall.stages``; none: dig to the bottom, a propped wall first to 0.5 m below its
  prop): each places and removes its supports, then digs to its level; the last stage digs to
  the design level with the unplanned overdig of the pack's ``embeddedWalls``;
- **the wall** a beam of Euler-Bernoulli elements (EI per metre: sheet piles E I; bored piles
  ``subgrade.concreteStiffness`` × Ec π D⁴/64 over the spacing of the reinforced piles; soldier
  piles E Ix over their spacing; diaphragm walls the factor × Ec t³/12) on elastic-plastic
  springs each side: behind, from the at-rest pressure K0 (σ'v + q) the pressure falls with
  the wall's movement y towards the excavation at kh y down to the active pressure (Ka, with
  the wall friction δa, the cohesion term and the least fluid pressure) and rises up to the
  passive; in front, below the dig level, it rises from K0 σ'v up to the passive (Kp with δp,
  the cohesion term; cohesive soil by cu: σv + 2 cu). Rankine or Coulomb by the pack, the
  horizontal components (K cos δ). Water hydrostatic both sides (the front dewatered to the
  dig level; soldier piles and lagging pass the water: none); adjoining footings as elastic
  strip loads (Boussinesq: Δσh = q/π (β - sin β cos 2α), times ``stripFactor``) behind;
- **subgrade modulus** kh: ``schmitt`` kh = a Eoed^(4/3) / EI^(1/3) (Eoed = E (1-ν) /
  ((1+ν)(1-2ν)), E the borehole's, else the pack's correlation with φ' or cu), or
  ``tabulated`` by φ' and cu;
- **supports** springs from the stage they are placed in: F = P0 + k (y - y0), y0 the wall's
  deflection at the support when placed, P0 the preload (anchors: the pack's lock-off share of
  the working load), k = E A cos²θ / L per metre (struts: the share of their length that
  shortens; anchors: the free length plus a share of the fixed one); a support that would pull
  is dropped;
- the springs' states (elastic, active, passive) are iterated to a fixed point; the moment and
  shear from the element forces.

Each of the pack's ``analyses`` runs the stages with the soil characteristic or with the
``embeddedWalls`` partial factors (``design``), its moments, shears and support forces times
its ``effectFactor`` (none: the pack's factor on earth pressure); the design takes their
envelope. Then:

- **the wall's section**: sheet piles W fy (limit state packs: / γM0; else φb of the pack's
  steel), bored piles per pile (the pack's P-M surface of the pile section, the pile shear),
  diaphragm walls per metre both faces (the retaining walls' strip design: flexure, minimum
  steel, crack width, spacing, shear), soldier piles by the pack's steel member checks and their
  timber lagging against the pack's allowable timber stress;
- **struts and rakers** by the pack's steel member checks: the factored force plus the
  temperature force ``temperatureFactor`` α ΔT E A × restraint, the self weight's moment, K L;
- **walers**: M = ``walerMoment`` w s², V = ``walerShear`` w s by the steel member checks;
- **ground anchors** (``anchors``, the standard the pack names): the tendon (working load ≤
  fpk A / factor), the free length (beyond the active wedge from the dig level at 45° - φ'/2
  plus the clearance, at least the least free length), the fixed length (π D Σ τ L ≥ factor ×
  the working load, τ by φ' or α cu, at most the counted maximum), the proof and lock-off loads;
- **the base**: basal heave of a cohesive base (Bjerrum and Eide: Nc cu ≥ F (σv + q), Nc =
  5 (1 + 0.2 H/B)(1 + 0.2 B/L) ≤ ``basalNcMax``), piping at the toe (Harr: i = Δh / (π d)
  ≤ icr / F); the wall's deflection against ``deflectionShare`` × H (reported).

Units: m, kN, kPa, kN/m (per metre of wall), kN·m/m inside; levels in mm (project datum) in
the library.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.check import _check
from saengine.substructure.earth_pressure import (
    GAMMA_W,
    Soil,
    ka_coulomb,
    ka_rankine,
    kp_coulomb,
    kp_rankine,
)

#: Largest element of the wall [m] and the bounds of their number.
STEP = 0.1
ELEMENTS = (40, 300)
#: Steel and tendon moduli [MPa] when the material gives none (nominal: structural steel,
#: seven-wire strand).
STEEL_E = 200_000.0
TENDON_E = 195_000.0
#: A prop of unknown stiffness (the propped wall without supports, a support with no section)
#: [kN/m per metre of wall]: rigid.
RIGID = 1e7
#: A strut of unknown length [m].
STRUT_LENGTH = 10.0
#: The first stage of a propped wall without stages digs this far below its prop [m].
BELOW_PROP = 0.5
#: Iterations of the spring states.
ITERATIONS = 100
#: Points of the curves sent to the editor and the report.
CURVE_POINTS = 120


def table() -> Any | None:
    """The pack's ``excavationSupport`` table, or None when the pack does not cover it."""
    pack = code_context.current()
    return pack.table("excavationSupport") if pack.has("excavationSupport") else None


def clause(key: str) -> str:
    found = table()
    return str((found.clauses or {}).get(key) or found.source) if found is not None else ""


def cite(key: str) -> str:
    """``clause`` after the pack's code name (SAEngine practice as it is; alpha 9 C26: named
    after the pack that supplies it when the pack in force inherits it)."""
    text = clause(key)
    if not text:
        return text
    if text.startswith(code_context.PRACTICE):
        found = table()
        own_key = key if (getattr(found, "clauses", None) or {}).get(key) else ""
        return code_context.attribute(text, "excavationSupport", own_key)
    return code_context.cite("excavationSupport", key) or text


# ─────────────────────────────── the wall ───────────────────────────────


@dataclass
class WallSection:
    """The wall's stiffness per metre and what its section is."""

    kind: str
    ei: float  # kN·m²/m
    text: str
    spacing: float = 1.0  # m: of the reinforced piles (bored piles), of the soldier piles
    width_ratio: float = 1.0  # soldier piles: share of the wall the soil acts on below the dig
    water: bool = True
    flange: float = 0.0  # soldier piles: flange width [m]
    notes: list[str] = field(default_factory=list)


def _steel(ctx: Any, material_id: str | None) -> Any | None:
    """The :class:`saengine.design.steel.Steel` of a steel material of 03 Materials."""
    from saengine.design.steel import Steel

    material = ctx.mats.get(material_id) if material_id else None
    if material is None or getattr(material, "steel", None) is None:
        return None
    try:
        return Steel.of(material)
    except Exception:  # noqa: BLE001 - not a steel with fy
        return None


def _concrete(ctx: Any, wall: Any) -> tuple[float, float] | None:
    """(f'c, Ec) [MPa] of the wall's concrete."""
    from saengine.design.rc_detailing import material_modulus
    from saengine.substructure.context import Skip

    try:
        concrete = ctx.concrete(wall.material, "embedded wall")
    except Skip:
        return None
    fc = float(concrete.concrete.fc)
    return fc, float(material_modulus(concrete, fc=fc)[0])


def _steel_section(name: str | None) -> tuple[Any, Any] | None:
    """(the library section, its ShapeProperties) of a steel section name."""
    from pydantic import TypeAdapter

    from saengine.design.steel import shape_properties
    from saengine.library import objects as o
    from saengine.library.steel_sections import find

    if not name:
        return None
    section = find(name)
    if section is None:
        return None
    return section, shape_properties(TypeAdapter(o.Profile).validate_python(section.profile()))


def wall_section(ctx: Any, wall: Any, rules: Any) -> WallSection | str:
    """The wall's :class:`WallSection`, or why it cannot be analysed."""
    from saengine.library.sheet_piles import find as sheet_pile

    kind = wall.wallType
    factor = rules.subgrade.concreteStiffness
    if kind == "sheetPile":
        sp = sheet_pile(wall.section)
        if sp is None:
            return f"the sheet pile section '{wall.section or ''}' is not in the table"
        steel = _steel(ctx, wall.material)
        e = steel.e if steel is not None else STEEL_E
        return WallSection(
            kind,
            e * 1e3 * sp.inertia * 1e-12,
            f"sheet piles {sp.name}: I = {sp.I:g} cm⁴/m, W = {sp.W:g} cm³/m (nominal)",
        )
    if kind in ("contiguous", "secant"):
        if not wall.pileDiameter or not wall.pileSpacing:
            return "a bored pile wall needs the pile diameter and spacing"
        found = _concrete(ctx, wall)
        if found is None:
            return "a bored pile wall needs its concrete (03 Materials)"
        d, s = wall.pileDiameter / 1e3, wall.pileSpacing / 1e3
        if kind == "secant" and s >= d:
            return "secant piles overlap: their spacing must be less than the diameter"
        structural = s if kind == "contiguous" or wall.allReinforced else 2 * s
        inertia = math.pi * d**4 / 64
        ei = factor * found[1] * 1e3 * inertia / structural
        what = "contiguous" if kind == "contiguous" else "secant"
        return WallSection(
            kind,
            ei,
            f"{what} piles Ø{wall.pileDiameter:g} at {wall.pileSpacing:g} mm, reinforced piles "
            f"at {structural * 1e3:g} mm, EI = {factor:g} × Ec π D⁴/64 / s",
            spacing=structural,
        )
    if kind == "soldier":
        found = _steel_section(wall.section)
        if found is None or not wall.pileSpacing:
            return "soldier piles need a steel section of the steel sections table and a spacing"
        section, _shape = found
        steel = _steel(ctx, wall.material)
        e = steel.e if steel is not None else STEEL_E
        s = wall.pileSpacing / 1e3
        b = section.b / 1e3
        ratio = min(rules.subgrade.soldierPassiveWidth * b, s) / s
        return WallSection(
            kind,
            e * 1e3 * section.Ix * 1e-12 / s,
            f"soldier piles {section.name} at {wall.pileSpacing:g} mm with lagging",
            spacing=s,
            width_ratio=ratio,
            water=False,
            flange=b,
            notes=[
                (
                    "soldier piles and lagging: no water pressure on the wall (the lagging "
                    "passes the water; dewater the ground behind it)"
                )
            ],
        )
    if kind == "diaphragm":
        if not wall.thickness:
            return "a diaphragm wall needs its thickness"
        found = _concrete(ctx, wall)
        if found is None:
            return "a diaphragm wall needs its concrete (03 Materials)"
        t = wall.thickness / 1e3
        return WallSection(
            kind,
            factor * found[1] * 1e3 * t**3 / 12,
            f"diaphragm wall {wall.thickness:g} mm, EI = {factor:g} × Ec t³/12",
        )
    return f"unknown wall type {kind}"


# ─────────────────────────────── soil springs ───────────────────────────────


def _interp(rows: list[tuple[float, float]], x: float) -> float:
    xs = [float(r[0]) for r in rows]
    ys = [float(r[1]) for r in rows]
    return float(np.interp(x, xs, ys))


def soil_modulus(soil: Soil, z: float, rules: Any) -> tuple[float, str]:
    """E [kPa] of the soil at depth z: the borehole's layer, else the pack's correlation."""
    profile = soil.profile
    if profile is not None:
        for layer in getattr(profile, "layers", []):
            if layer.top <= z < layer.bottom and getattr(layer, "E", None):
                return float(layer.E) * 1e3, "E of the soil report"
    phi = soil.phi(z)
    if phi is not None:
        return _interp(rules.granularModulus, phi) * 1e3, "E by φ'"
    return rules.cohesiveModulus * max(soil.cohesion(z), 1.0), "E = ratio × cu"


def subgrade(soil: Soil, z: float, ei: float, rules: Any) -> float:
    """kh [kN/m³] at depth z (see the module notes)."""
    if rules.method == "tabulated":
        phi = soil.phi(z)
        if phi is not None:
            return _interp(rules.tabulatedGranular, phi) * 1e3
        return rules.tabulatedCohesive * max(soil.cohesion(z), 1.0)
    e, _ = soil_modulus(soil, z, rules)
    nu = rules.poisson
    oed = e * (1 - nu) / ((1 + nu) * (1 - 2 * nu))
    return rules.schmittCoefficient * oed ** (4 / 3) / max(ei, 1e-6) ** (1 / 3)


def coefficients(phi: float, rules: Any) -> tuple[float, float, float, float]:
    """(Ka, Kp) horizontal with the pack's wall friction, and (√Ka, √Kp) of the cohesion
    terms (Rankine's)."""
    da = rules.activeFriction * phi
    dp = rules.passiveFriction * phi
    if rules.activeMethod == "coulomb":
        ka = ka_coulomb(phi, da) * math.cos(math.radians(da))
    else:
        ka = ka_rankine(phi)
    if rules.passiveMethod == "coulomb":
        kp = kp_coulomb(phi, dp) * math.cos(math.radians(dp))
    else:
        kp = kp_rankine(phi)
    return ka, kp, math.sqrt(ka_rankine(phi)), math.sqrt(kp_rankine(phi))


def side_pressures(soil: Soil, z: float, q: float, rules: Any, behind: bool):
    """(at rest, active, passive) earth pressure [kPa] at depth z below the soil's own surface
    with the surcharge q (no water)."""
    if z <= 0:
        return 0.0, 0.0, 0.0
    sv = soil.sigma_v_eff(z) + q
    phi = soil.phi(z)
    c = soil.cohesion(z)
    k0 = soil.k0(z)
    p0 = k0 * sv
    if phi is None:  # cu only: at rest behind (long term), σv + 2 cu passive
        pa = p0
        pp = soil.sigma_v(z) + q - soil.u(z) + 2 * c
    else:
        ka, kp, ra, rp = coefficients(phi, rules)
        pa = ka * sv - 2 * c * ra
        pp = kp * sv + 2 * c * rp
    if behind:
        pa = max(pa, rules.minimumFluid * z)
    pa = max(pa, 0.0)
    p0 = max(p0, pa)
    pp = max(pp, p0)
    return p0, pa, pp


def strip_pressure(z: float, q: float, near: float, width: float, depth: float) -> float:
    """Δσh [kPa] at depth z of a strip load q [kPa] at depth ``depth``, from ``near`` to
    ``near + width`` m from the wall (Boussinesq: q/π (β - sin β cos 2α))."""
    zz = z - depth
    if zz <= 0 or q <= 0:
        return 0.0
    t1, t2 = math.atan2(near, zz), math.atan2(near + width, zz)
    beta = t2 - t1
    alpha = (t1 + t2) / 2
    return q / math.pi * (beta - math.sin(beta) * math.cos(2 * alpha))


# ─────────────────────────────── the stage solver ───────────────────────────────


@dataclass
class Spring:
    """A support at node ``node``: stiffness per metre [kN/m/m], preload per metre [kN/m],
    the deflection when placed [m]."""

    id: str
    node: int
    k: float
    p0: float
    y0: float


@dataclass
class Wall:
    """The wall's mesh and stiffness."""

    z: np.ndarray
    trib: np.ndarray
    base: np.ndarray
    ei: float


def mesh(length: float, ei: float) -> Wall:
    from saengine.substructure.pile_lateral_soil import _beam

    count = int(min(max(math.ceil(length / STEP), ELEMENTS[0]), ELEMENTS[1]))
    le = length / count
    z = np.linspace(0.0, length, count + 1)
    trib = np.full(count + 1, le)
    trib[0] = trib[-1] = le / 2
    return Wall(z, trib, _beam(length, count, ei), ei)


@dataclass
class StageLoads:
    """The pressures on the wall's nodes in one stage [kPa]: behind and in front (at rest,
    active, passive, kh), the water each side, the dig depth, the width ratio of each side."""

    dig: float
    b0: np.ndarray
    ba: np.ndarray
    bp: np.ndarray
    bk: np.ndarray
    f0: np.ndarray
    fa: np.ndarray
    fp: np.ndarray
    fk: np.ndarray
    front: np.ndarray  # bool: soil in front
    ub: np.ndarray
    uf: np.ndarray
    rb: np.ndarray
    rf: np.ndarray


def stage_loads(
    wall: Wall,
    soil: Soil,
    stiff_soil: Soil,
    dig: float,
    q: float,
    strips: list[tuple[float, float, float, float]],
    section: WallSection,
    rules: Any,
) -> StageLoads:
    """The pressures of a stage dug to ``dig`` [m] (``soil`` for the strengths, ``stiff_soil``
    for the moduli; ``strips``: (q, near, width, depth) of the strip loads)."""
    n = len(wall.z)
    ep = rules.earthPressure
    b0, ba, bp, bk = (np.zeros(n) for _ in range(4))
    f0, fa, fp, fk = (np.zeros(n) for _ in range(4))
    ub, uf = np.zeros(n), np.zeros(n)
    rb, rf = np.ones(n), np.ones(n)
    front = wall.z > dig + 1e-9
    below = soil.below(dig)
    for i, z in enumerate(wall.z):
        zz = max(float(z), 1e-6)
        p0, pa, pp = side_pressures(soil, zz, q, ep, True)
        extra = sum(ep.stripFactor * strip_pressure(zz, *s) for s in strips)
        b0[i], ba[i], bp[i] = p0 + extra, pa + extra, pp + extra
        bk[i] = subgrade(stiff_soil, zz, wall.ei, rules.subgrade)
        if section.water:
            ub[i] = soil.u(zz)
        if front[i]:
            f0[i], fa[i], fp[i] = side_pressures(below, zz - dig, 0.0, ep, False)
            fk[i] = subgrade(stiff_soil, zz, wall.ei, rules.subgrade)
            if section.water:
                uf[i] = below.u(zz - dig)
            rb[i] = rf[i] = section.width_ratio
    return StageLoads(dig, b0, ba, bp, bk, f0, fa, fp, fk, front, ub, uf, rb, rf)


#: Half bandwidth of the wall's stiffness matrix (two DOFs per node, one element apart).
BAND = 3


def _banded_solve(k: np.ndarray, f: np.ndarray) -> np.ndarray:
    """``k u = f`` for the banded stiffness of the wall (the dense solve is far slower)."""
    from scipy.linalg import solve_banded

    n = len(f)
    ab = np.zeros((2 * BAND + 1, n))
    for offset in range(-BAND, BAND + 1):
        diagonal = np.diagonal(k, offset)
        if offset >= 0:
            ab[BAND - offset, offset:] = diagonal
        else:
            ab[BAND - offset, : n + offset] = diagonal
    return solve_banded((BAND, BAND), ab, f)


def solve_stage(wall: Wall, loads: StageLoads, springs: list[Spring]) -> dict[str, Any] | None:
    """The wall's deflection y (towards the excavation), moment, shear and the pressures of
    one stage; None when no state of the springs is in equilibrium (the wall fails)."""
    n = len(wall.z)
    dofs = 2 * n
    sb = np.zeros(n, dtype=int)  # behind: 0 elastic, -1 active, +1 passive
    sf = np.zeros(n, dtype=int)
    active = {s.id: True for s in springs}
    y = np.zeros(n)
    u = np.zeros(dofs)
    lateral = np.arange(0, dofs, 2)
    converged = False
    for _ in range(ITERATIONS):
        k = wall.base.copy()
        f = np.zeros(dofs)
        lb = wall.trib * loads.rb
        lf = wall.trib * loads.rf * loads.front
        el_b = sb == 0
        el_f = (sf == 0) & loads.front
        diag = np.where(el_b, loads.bk * lb, 0.0) + np.where(el_f, loads.fk * lf, 0.0)
        back = np.where(sb == 0, loads.b0, np.where(sb < 0, loads.ba, loads.bp)) * lb
        ahead = np.where(sf == 0, loads.f0, np.where(sf < 0, loads.fa, loads.fp)) * lf
        water = (loads.ub - loads.uf) * wall.trib
        k[lateral, lateral] += diag
        f[lateral] += back - ahead + water
        for s in springs:
            if active[s.id]:
                k[2 * s.node, 2 * s.node] += s.k
                f[2 * s.node] += -s.p0 + s.k * s.y0
        try:
            u = _banded_solve(k, f)
        except (np.linalg.LinAlgError, ValueError):
            return None
        y = u[0::2]
        if not np.all(np.isfinite(y)) or float(np.max(np.abs(y))) > 10.0:
            return None
        trial_b = loads.b0 - loads.bk * y
        trial_f = loads.f0 + loads.fk * y
        nb = np.where(trial_b < loads.ba, -1, np.where(trial_b > loads.bp, 1, 0))
        nf = np.where(trial_f < loads.fa, -1, np.where(trial_f > loads.fp, 1, 0)) * loads.front
        changed = bool(np.any(nb != sb) or np.any(nf != sf))
        for s in springs:  # a support pushes only: dropped when it would pull, back after
            pushes = s.p0 + s.k * (y[s.node] - s.y0) >= 0
            if pushes != active[s.id]:
                active[s.id] = pushes
                changed = True
        sb, sf = nb, nf
        if not changed:
            converged = True
            break
    if not converged:
        return None
    from saengine.substructure.pile_lateral_soil import _beam

    count = n - 1
    le = float(wall.z[1] - wall.z[0])
    kel = _beam(le, 1, wall.ei)
    moments, shears = np.zeros(n), np.zeros(n)
    local = np.zeros(4)
    for e in range(count):
        local = kel @ u[2 * e : 2 * e + 4]
        moments[e], shears[e] = -local[1], local[0]
    moments[count], shears[count] = local[3], -local[2]
    behind = np.clip(loads.b0 - loads.bk * y, loads.ba, loads.bp)
    ahead = np.where(loads.front, np.clip(loads.f0 + loads.fk * y, loads.fa, loads.fp), 0.0)
    forces = {
        s.id: (s.p0 + s.k * (float(y[s.node]) - s.y0)) if active[s.id] else 0.0 for s in springs
    }
    available = float(np.sum(loads.fp * wall.trib * loads.rf * loads.front))
    used = float(np.sum(ahead * wall.trib * loads.rf))
    return {
        "y": y,
        "M": moments,
        "V": shears,
        "behind": behind * loads.rb + loads.ub,
        "front": ahead * loads.rf + loads.uf * loads.front,
        "forces": forces,
        "mobilised": used / available if available > 0 else 1.0,
    }


# ─────────────────────────────── stages and supports ───────────────────────────────


@dataclass
class Stage:
    name: str
    dig: float  # m below the retained ground
    install: list[str]
    remove: list[str]
    surcharge: float | None


def stages_of(wall: Any, ground: float, bottom: float) -> list[Stage]:
    """The wall's stages (depths in m), or the default ones (see the module notes)."""
    if wall.stages:
        return [
            Stage(
                s.name or f"Stage {i + 1}",
                (ground - s.digLevel) / 1e3,
                list(s.install),
                list(s.remove),
                s.surcharge,
            )
            for i, s in enumerate(wall.stages)
        ]
    depth = (ground - bottom) / 1e3
    levels: list[tuple[str, float]] = []
    if wall.supports:
        levels = [(s.id, s.level) for s in wall.supports]
    elif wall.kind == "propped" and wall.propLevel is not None:
        levels = [("P", wall.propLevel)]
    out: list[Stage] = []
    pending: list[str] = []
    for sid, level in sorted(levels, key=lambda x: -x[1]):  # the highest first
        dig = min((ground - level) / 1e3 + BELOW_PROP, depth)
        out.append(Stage(_stage_name(pending, dig), dig, pending, [], None))
        pending = [sid]
    out.append(Stage(_stage_name(pending, depth), depth, pending, [], None))
    return out


def _stage_name(placed: list[str], dig: float) -> str:
    return (f"Place {', '.join(placed)}, dig" if placed else "Dig") + f" to {dig:.2f} m"


def _support_length(support: Any, depth: float, bottom: float) -> float:
    """Its length [m]: as given, else a strut's nominal, a raker's from its level to the base."""
    if support.length:
        return support.length / 1e3
    if support.kind == "raker":
        drop = max(bottom - depth, 0.5)
        return drop / max(math.sin(math.radians(support.inclination or 45.0)), 0.2)
    return STRUT_LENGTH


def support_stiffness(ctx: Any, support: Any, depth: float, bottom: float, rules: Any):
    """(k per metre of wall [kN/m/m], how) of a support."""
    s = support.spacing / 1e3
    theta = math.radians(support.inclination)
    if support.stiffness:
        return support.stiffness / s, f"k = {support.stiffness:g} kN/m as given"
    if support.kind == "anchor":
        if not support.tendonArea:
            return RIGID, "no tendon area: rigid"
        a = rules.anchors
        free = (support.freeLength / 1e3) if support.freeLength else a.freeLengthMin
        fixed = (support.fixedLength / 1e3) if support.fixedLength else a.fixedLengthMin
        length = free + a.stiffnessLength * fixed
        k = TENDON_E * 1e3 * support.tendonArea * 1e-6 * math.cos(theta) ** 2 / length
        return k / s, f"k = E A cos²θ / ({free:.1f} + {a.stiffnessLength:g} × {fixed:.1f} m)"
    found = _steel_section(support.section)
    if found is None:
        return RIGID, "no steel section: rigid"
    section, _ = found
    steel = _steel(ctx, support.material)
    e = steel.e if steel is not None else STEEL_E
    length = _support_length(support, depth, bottom)
    if support.kind == "strut":
        length *= rules.struts.symmetricShare
    k = e * 1e3 * section.A * 1e-6 * math.cos(theta) ** 2 / max(length, 0.1)
    return k / s, f"k = E A cos²θ / L ({length:.2f} m)"


# ─────────────────────────────── the analysis ───────────────────────────────


def _h_factor() -> float:
    from saengine.substructure.retaining_walls import _h_factor as factor

    return factor()


def _surcharge(wall: Any, excavation: Any) -> float:
    """The wall's surcharge [kPa]: as P7 takes it (the wall's, else the largest load beside
    the excavation), at least the embeddedWalls table's least surcharge."""
    from saengine.substructure import embedded_wall

    loads = [float(x.pressure) for x in excavation.loads if x.pressure is not None]
    q = wall.surcharge if wall.surcharge is not None else max(loads, default=0.0)
    rules = embedded_wall.table()
    return max(q, rules.minimumSurcharge if rules is not None else 0.0)


def _overdig(height: float) -> float:
    from saengine.substructure import embedded_wall

    rules = embedded_wall.table()
    if rules is None:
        return 0.0
    return min(rules.overdigShare * height, rules.overdigMax)


def _toe(wall: Any, ground: float, soil: Soil, height: float, q: float) -> tuple[float, str]:
    """The wall's length below the retained ground [m]: its toe, else P7's required toe."""
    if wall.toeLevel is not None:
        return (ground - wall.toeLevel) / 1e3, "the toe as built"
    from saengine.substructure.embedded_wall import design_wall

    prop = None if wall.propLevel is None else (ground - wall.propLevel) / 1e3
    if prop is None and wall.supports:
        prop = (ground - max(s.level for s in wall.supports)) / 1e3
    kind = "propped" if prop is not None else "cantilever"
    found = design_wall(soil, height, kind, wall.earthSupport, prop, q)
    if found.get("ok"):
        return found["dig"] + found["d"], "no toe given: the required toe of the embedment check"
    return 2.0 * height, "no toe given and none balances: twice the depth"


def run_stages(
    ctx: Any,
    wall: Any,
    section: WallSection,
    mesh_: Wall,
    soil: Soil,
    stiff_soil: Soil,
    stages: list[Stage],
    q: float,
    strips: list[tuple[float, float, float, float]],
    nodes: dict[str, int],
    stiffness: dict[str, float],
    preloads: dict[str, float],
    rules: Any,
) -> list[dict[str, Any]] | str:
    """Every stage of one run: its result dicts, or why it failed."""
    installed: dict[str, Spring] = {}
    y_prev = np.zeros(len(mesh_.z))
    out = []
    for stage in stages:
        for sid in stage.remove:
            installed.pop(sid, None)
        for sid in stage.install:
            if sid in nodes:
                node = nodes[sid]
                installed[sid] = Spring(
                    sid, node, stiffness[sid], preloads.get(sid, 0.0), float(y_prev[node])
                )
        loads = stage_loads(
            mesh_,
            soil,
            stiff_soil,
            stage.dig,
            q if stage.surcharge is None else stage.surcharge,
            strips,
            section,
            rules,
        )
        found = solve_stage(mesh_, loads, list(installed.values()))
        if found is None:
            return (
                f"{stage.name}: no equilibrium (the soil in front is fully mobilised, or the "
                "wall is not supported): deepen the wall or add supports"
            )
        found["stage"] = stage
        out.append(found)
        y_prev = found["y"]
    return out


def _sample(z: np.ndarray, *curves: np.ndarray) -> list[list[float]]:
    step = max(1, math.ceil(len(z) / CURVE_POINTS))
    idx = list(range(0, len(z), step))
    if idx[-1] != len(z) - 1:
        idx.append(len(z) - 1)
    return [[round(float(c[i]), 4) for i in idx] for c in (z, *curves)]


def analyse(ctx: Any, excavation: Any, ground: float, soil: Soil) -> dict[str, Any] | str:
    """The staged analysis of the excavation's wall (see the module notes): every run's
    stages, the envelopes and the inputs the design needs; or why it cannot be made."""
    from saengine.substructure.embedded_wall import factored_soil
    from saengine.substructure.embedded_wall import table as wall_table

    rules = table()
    wall = excavation.wall
    section = wall_section(ctx, wall, rules)
    if isinstance(section, str):
        return section
    height = (ground - excavation.bottomLevel) / 1e3
    stages = stages_of(wall, ground, excavation.bottomLevel)
    overdig = _overdig(height)
    stages[-1].dig += overdig
    design = stages[-1].dig
    q = _surcharge(wall, excavation)
    length, toe_how = _toe(wall, ground, soil, height, q)
    if length <= design + 0.1:
        return f"the toe ({length:.2f} m) is not below the design dig level ({design:.2f} m)"
    mesh_ = mesh(length, section.ei)
    strips = []
    for adj in excavation.adjoining:
        if adj.pressure:
            strips.append(
                (
                    float(adj.pressure),
                    adj.distance / 1e3,
                    (adj.width or 1500.0) / 1e3,
                    max((ground - adj.foundingLevel) / 1e3, 0.0),
                )
            )
    supports = {s.id: s for s in wall.supports}
    if not wall.supports and wall.kind == "propped" and wall.propLevel is not None:
        from saengine.library.substructure import WallSupport

        supports = {
            "P": WallSupport(
                id="P",
                level=wall.propLevel,
                spacing=wall.propSpacing or 1000.0,
                stiffness=RIGID * ((wall.propSpacing or 1000.0) / 1e3),
            )
        }
    nodes, stiffness, how = {}, {}, {}
    notes: list[str] = list(section.notes)
    for sid, s in supports.items():
        depth = (ground - s.level) / 1e3
        if not 0 <= depth < length:
            notes.append(f"{sid}: its level is not on the wall; left out")
            continue
        nodes[sid] = int(np.argmin(np.abs(mesh_.z - depth)))
        stiffness[sid], how[sid] = support_stiffness(ctx, s, depth, design, rules)
    preloads = {
        sid: (s.preload or 0.0) * math.cos(math.radians(s.inclination)) / (s.spacing / 1e3)
        for sid, s in supports.items()
    }
    walls_rules = wall_table()
    runs = []
    first_char = None
    for case in rules.analyses:
        strength_soil = soil
        q_run = q
        partial = walls_rules is not None and walls_rules.method == "partialFactors"
        if case.strengths == "design" and partial:
            strength_soil, text = factored_soil(soil, walls_rules)
            if text:
                notes.append(f"{case.name}: {text}")
            q_run = q * walls_rules.variableFactor
        factor = case.effectFactor if case.effectFactor is not None else _h_factor()
        runs.append((case, strength_soil, q_run, factor))
        if first_char is None and case.strengths == "characteristic":
            first_char = len(runs) - 1
    # Anchors without a preload: lock-off at the pack's share of the working load (a first
    # pass without it finds the working load).
    lock = [sid for sid, s in supports.items() if s.kind == "anchor" and s.preload is None]
    reference = first_char if first_char is not None else 0
    if lock:
        case, s_soil, q_run, _ = runs[reference]
        found = run_stages(
            ctx,
            wall,
            section,
            mesh_,
            s_soil,
            soil,
            stages,
            q_run,
            strips,
            nodes,
            stiffness,
            preloads,
            rules,
        )
        if isinstance(found, str):
            return found
        for sid in lock:
            peak = max(r["forces"].get(sid, 0.0) for r in found)
            preloads[sid] = rules.anchors.lockOffShare * peak
    results = []
    for case, s_soil, q_run, factor in runs:
        found = run_stages(
            ctx,
            wall,
            section,
            mesh_,
            s_soil,
            soil,
            stages,
            q_run,
            strips,
            nodes,
            stiffness,
            preloads,
            rules,
        )
        if isinstance(found, str):
            return f"{case.name}: {found}"
        results.append({"case": case, "factor": factor, "stages": found})
    return {
        "section": section,
        "mesh": mesh_,
        "length": length,
        "toeHow": toe_how,
        "height": height,
        "design": design,
        "overdig": overdig,
        "q": q,
        "stages": stages,
        "supports": supports,
        "nodes": nodes,
        "stiffness": how,
        "preloads": preloads,
        "runs": results,
        "reference": reference,
        "notes": notes,
    }


# ─────────────────────────────── design ───────────────────────────────


def envelopes(found: dict[str, Any]) -> dict[str, Any]:
    """The design envelopes over the runs and stages: M+ and M- [kN·m/m] (factored), |V|
    [kN/m], the support forces per metre (factored, and the reference run's unfactored), the
    deflection (reference run) and where the largest are."""
    z = found["mesh"].z
    n = len(z)
    m_pos, m_neg, v = np.zeros(n), np.zeros(n), np.zeros(n)
    s_pos, s_neg = np.zeros(n), np.zeros(n)  # service (reference run, unfactored)
    forces: dict[str, float] = {}
    working: dict[str, float] = {}
    y = np.zeros(n)
    for r, run in enumerate(found["runs"]):
        f = run["factor"]
        for st in run["stages"]:
            m_pos = np.maximum(m_pos, f * st["M"])
            m_neg = np.minimum(m_neg, f * st["M"])
            v = np.maximum(v, f * np.abs(st["V"]))
            for sid, force in st["forces"].items():
                forces[sid] = max(forces.get(sid, 0.0), f * force)
            if r == found["reference"]:
                s_pos = np.maximum(s_pos, st["M"])
                s_neg = np.minimum(s_neg, st["M"])
                for sid, force in st["forces"].items():
                    working[sid] = max(working.get(sid, 0.0), force)
                if np.max(np.abs(st["y"])) > np.max(np.abs(y)):
                    y = st["y"]
    return {
        "z": z,
        "Mpos": m_pos,
        "Mneg": m_neg,
        "V": v,
        "Spos": s_pos,
        "Sneg": s_neg,
        "forces": forces,
        "working": working,
        "y": y,
    }


def _gamma_m0() -> float | None:
    """γM0 of the pack's limit state steel (its member resistance group, else its partial
    factors); None for a pack designing steel by φ factors."""
    from saengine.design.steel import limit_state

    found = limit_state.member_resistance()
    if found is not None:
        return float(found.gammaM0)
    rules = limit_state.rules()
    factors = getattr(rules, "partialFactors", None) if rules is not None else None
    value = getattr(factors, "gammaM0", None) if factors is not None else None
    return float(value) if value is not None else None


def _pile_bars(wall: Any) -> Any | None:
    from saengine.library.objects import BarGroup, LinearReinforcement, Transverse

    if not (wall.rebar and wall.barCount and wall.barDia):
        return None
    transverse = None
    if wall.linkDia and wall.linkSpacing:
        transverse = Transverse(type="spiral", dia=wall.linkDia, spacing=wall.linkSpacing)
    return LinearReinforcement(
        material=wall.rebar,
        cover=wall.cover,
        longitudinal=[BarGroup(position="perimeter", count=wall.barCount, dia=wall.barDia)],
        transverse=transverse,
    )


def _pile_shear(d: float, fc: float, fy: float, bars: Any) -> tuple[float, str]:
    """φVn [N] of a bored pile: the pack's one-way shear on bw = D, d = 0.8 D (concrete only)
    when the pack designs by partial factors or tabulated shear, else the pile cap's pile
    section shear (with the links)."""
    from saengine.design import limit_state_rows, tabulated_shear

    if limit_state_rows.partial_factors() or tabulated_shear.rules() is not None:
        from saengine.design.slab import one_way_shear

        steel = sum(g.count * math.pi * g.dia**2 / 4 for g in bars.longitudinal)
        dd = 0.8 * d
        per_m, _ = one_way_shear(steel / 2 / (d * dd), dd, fc)
        return per_m * d / 1000, "the pack's one-way shear on bw = D, d = 0.8 D (concrete only)"
    from saengine.substructure.pilehead import shear_capacity

    found = shear_capacity(d, fc, fy, bars)
    return found["phiVn"], "the pile section's shear (bw = D, d = 0.8 D, with the links)"


def wall_design(ctx: Any, wall: Any, found: dict[str, Any], env: dict[str, Any]) -> list[dict]:
    """The checks of the wall's section under the design envelopes."""
    section: WallSection = found["section"]
    z = env["z"]
    mmax = float(max(np.max(env["Mpos"]), -np.min(env["Mneg"])))
    zm = float(z[int(np.argmax(np.maximum(env["Mpos"], -env["Mneg"])))])
    vmax = float(np.max(env["V"]))
    ref = cite("method")
    where = f"Md = {mmax:.1f} kN·m/m at {zm:.2f} m, the envelope of the stages ({ref})"
    checks: list[dict[str, Any]] = []
    if section.kind == "sheetPile":
        from saengine.library.sheet_piles import find as sheet_pile

        sp = sheet_pile(wall.section)
        steel = _steel(ctx, wall.material)
        if steel is None:
            checks.append(
                _check(
                    "Sheet piles: bending",
                    mmax,
                    mmax,
                    "kN·m/m",
                    None,
                    f"{where}; no steel material: reported only",
                    flag=True,
                )
            )
            return checks
        g0 = _gamma_m0()
        if g0 is not None:
            mrd = sp.modulus * steel.fy / g0 / 1e6
            how = f"W fy / γM0 = {sp.W:g} cm³/m × {steel.fy:g} / {g0:g}"
        else:
            from saengine.design.steel.members import _phi

            phi = _phi("flexure", 0.9)
            mrd = phi * sp.modulus * steel.fy / 1e6
            how = f"φb Fy W = {phi:g} × {steel.fy:g} × {sp.W:g} cm³/m (elastic)"
        checks.append(
            _check(
                "Sheet piles: bending",
                mmax,
                mrd,
                "kN·m/m",
                None,
                f"{where}; {how}; the nominal section (VERIFY with the supplier)",
            )
        )
        return checks
    if section.kind in ("contiguous", "secant"):
        from saengine.substructure.context import Skip
        from saengine.substructure.pile_lateral_soil import bending_capacity

        bars = _pile_bars(wall)
        fc = _concrete(ctx, wall)[0]  # type: ignore[index]
        s = section.spacing
        m_pile, v_pile = mmax * s, vmax * s
        if bars is None:
            checks.append(
                _check(
                    "Pile wall: bending per pile",
                    m_pile,
                    m_pile,
                    "kN·m",
                    None,
                    f"{where}; × {s:.2f} m per reinforced pile; no bars given: reported only",
                    flag=True,
                )
            )
            return checks
        try:
            fy = float(ctx.rebar(wall.rebar).steel.fy)
        except Skip as reason:
            return [_check("Pile wall: bars", 1.0, 0.0, "", None, str(reason))]
        d = float(wall.pileDiameter)
        phi_mn = bending_capacity(d, fc, fy, bars, False)
        checks.append(
            _check(
                "Pile wall: bending per pile",
                m_pile,
                (phi_mn or 0.0) / 1e6,
                "kN·m",
                None,
                f"{where}; × {s:.2f} m per reinforced pile; {wall.barCount}Ø{wall.barDia:g}, the "
                "code pack's P-M surface of the pile section at no axial force",
            )
        )
        capacity, how = _pile_shear(d, fc, fy, bars)
        checks.append(
            _check(
                "Pile wall: shear per pile",
                v_pile,
                capacity / 1e3,
                "kN",
                None,
                f"Vd = {vmax:.1f} kN/m × {s:.2f} m; {how}",
            )
        )
        return checks
    if section.kind == "diaphragm":
        from saengine.library.objects import BarMesh
        from saengine.substructure.context import Skip
        from saengine.substructure.retaining_walls import Strip, design_strip

        fc, ec = _concrete(ctx, wall)  # type: ignore[misc]
        if not wall.rebar:
            fy = 420.0
            note = "no bar material: Grade 420 proposed"
        else:
            try:
                fy = float(ctx.rebar(wall.rebar).steel.fy)
            except Skip as reason:
                return [_check("Diaphragm wall: bars", 1.0, 0.0, "", None, str(reason))]
            note = ""
        given = (
            BarMesh(dia=wall.barDia, spacing=wall.barSpacing)
            if wall.barDia and wall.barSpacing
            else None
        )
        t = float(wall.thickness)
        faces = (
            (
                "Diaphragm wall, retained face",
                float(np.max(env["Mpos"])),
                float(np.max(env["Spos"])),
                vmax,
            ),
            (
                "Diaphragm wall, excavated face",
                float(-np.min(env["Mneg"])),
                float(-np.min(env["Sneg"])),
                0.0,
            ),
        )
        for name, mu, ms, vu in faces:
            if mu <= 0:
                continue
            strip = Strip(name, mu, ms, t, wall.cover, vu, f"envelope of the stages ({ref})")
            bars, rows = design_strip(strip, fc, fy, ec, wall.crackLimit, given)
            if bars.get("proposed"):
                rows.append(
                    _check(
                        f"{name}: bars proposed",
                        0.0,
                        0.0,
                        "",
                        None,
                        f"Ø{bars['dia']:g} at {bars['spacing']:g} mm proposed"
                        + (f"; {note}" if note else ""),
                        flag=True,
                    )
                )
            checks += rows
        return checks
    # Soldier piles: the steel section per pile and the lagging between them.
    from saengine.design.steel import SteelOptions, check_member
    from saengine.design.steel.lengths import MemberLengths
    from saengine.design.steel.members import Stations

    pile = _steel_section(wall.section)
    steel = _steel(ctx, wall.material)
    s = section.spacing
    if pile is None or steel is None:
        return [
            _check(
                "Soldier piles: bending per pile",
                mmax * s,
                mmax * s,
                "kN·m",
                None,
                f"{where}; no steel material or section: reported only",
                flag=True,
            )
        ]
    shape = pile[1]
    length = float(z[-1])
    m_pile = np.maximum(env["Mpos"], -env["Mneg"]) * s
    stations = Stations(
        "excavation stages",
        np.asarray(z, dtype=float),
        np.zeros(len(z)),
        -m_pile * 1e6,
        np.zeros(len(z)),
        env["V"] * s * 1e3,
        np.zeros(len(z)),
        [f"{x:.2f} m" for x in z],
    )
    braces = sorted({(found["mesh"].z[n]) for n in found["nodes"].values()})
    lengths = MemberLengths.simple(length, x=braces, y=braces, ltb=braces)
    rows = check_member(shape, steel, [stations], lengths, "beam", SteelOptions())
    checks += [{**r, "name": f"Soldier piles: {r['name']}"} for r in rows]
    checks += _lagging(wall, found, section)
    return checks


def _lagging(wall: Any, found: dict[str, Any], section: WallSection) -> list[dict]:
    """The timber lagging between soldier piles: M = p l²/8 per metre height at the largest
    pressure behind above the dig level (reference run), against the pack's allowable timber
    bending stress (the formwork rules)."""
    from saengine.substructure.excavation import group

    if not wall.laggingThickness:
        return []
    run = found["runs"][found["reference"]]
    z = found["mesh"].z
    p = 0.0
    for st in run["stages"]:
        above = z <= st["stage"].dig
        if np.any(above):
            p = max(p, float(np.max(st["behind"][above])))
    span = max(section.spacing - section.flange, 0.1)
    t = wall.laggingThickness / 1e3
    stress = p * span**2 / 8 / (t**2 / 6)
    formwork = group("formwork")
    allowable = getattr(formwork, "timberBending", None) if formwork is not None else None
    note = (
        f"p = {p:.1f} kPa over the clear span {span:.2f} m, M = p l²/8, timber "
        f"{wall.laggingThickness:g} mm"
    )
    if allowable is None:
        return [_check("Lagging: bending", stress, stress, "kPa", None, note, flag=True)]
    return [_check("Lagging: bending", stress, float(allowable), "kPa", None, note)]


def _steel_rows(
    name: str, shape: Any, steel: Any, length: float, p: float, m: float, v: float, kind: str
) -> list[dict]:
    """The pack's steel member checks of a strut, raker or waler [kN, kN·m, m]."""
    from saengine.design.steel import SteelOptions, check_member
    from saengine.design.steel.lengths import MemberLengths
    from saengine.design.steel.members import Stations

    rules = table()
    s = np.array([0.0, length / 2, length])
    stations = Stations(
        "excavation stages",
        s,
        np.full(3, p * 1e3),
        np.array([0.0, -m * 1e6, 0.0]),
        np.zeros(3),
        np.array([v * 1e3, 0.0, -v * 1e3]),
        np.zeros(3),
        ["end", "middle", "end"],
    )
    k = rules.struts.effectiveLength if kind == "column" else 1.0
    lengths = MemberLengths.simple(length, k={"x": k, "y": k, "z": k})
    rows = check_member(shape, steel, [stations], lengths, kind, SteelOptions())
    return [{**r, "name": f"{name}: {r['name']}"} for r in rows]


def support_design(
    ctx: Any, excavation: Any, found: dict[str, Any], env: dict[str, Any], soil: Soil
) -> tuple[list[dict], list[dict]]:
    """The checks of the struts, rakers, walers and anchors, and their rows for the report."""
    rules = table()
    checks: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for sid, support in found["supports"].items():
        if sid not in found["nodes"]:
            continue
        s = support.spacing / 1e3
        theta = math.radians(support.inclination)
        per_m = env["forces"].get(sid, 0.0)
        design = per_m * s / math.cos(theta)  # kN along the support
        working = env["working"].get(sid, 0.0) * s / math.cos(theta)
        row = {
            "id": sid,
            "kind": support.kind,
            "level": support.level,
            "perMetre": round(per_m, 2),
            "design": round(design, 1),
            "working": round(working, 1),
            "stiffness": found["stiffness"].get(sid, ""),
        }
        depth = (found["mesh"].z[found["nodes"][sid]]).item()
        if sid == "P" and support.section is None:
            rows.append(row)
            continue
        if support.kind in ("strut", "raker"):
            checks += _strut_checks(ctx, support, design, depth, found["design"], rules, row)
        else:
            checks += _anchor_checks(support, working, depth, found, soil, rules, row)
        if support.waler:
            checks += _waler_checks(ctx, support, per_m, rules)
        rows.append(row)
    return checks, rows


def _strut_checks(ctx, support, design, depth, bottom, rules, row) -> list[dict]:
    found = _steel_section(support.section)
    steel = _steel(ctx, support.material)
    sid = support.id
    if found is None or steel is None:
        return [
            _check(
                f"{sid}: {support.kind} force",
                design,
                design,
                "kN",
                None,
                f"{design:.0f} kN per {support.kind} (factored envelope); no steel section or "
                "material: reported only",
                flag=True,
            )
        ]
    section, shape = found
    st = rules.struts
    length = _support_length(support, depth, bottom)
    area = section.A * 1e-6
    temperature = (
        st.temperatureFactor
        * st.expansion
        * st.temperatureRange
        * steel.e
        * 1e3
        * area
        * st.temperatureRestraint
    )
    weight = section.mass * 9.81e-3 * math.cos(math.radians(support.inclination))  # kN/m
    moment = st.selfWeightFactor * weight * length**2 / 8
    shear = st.selfWeightFactor * weight * length / 2
    axial = design + temperature
    row.update(
        {"temperature": round(temperature, 1), "axial": round(axial, 1), "length": round(length, 2)}
    )
    out = [
        _check(
            f"{sid}: design axial force",
            axial,
            axial,
            "kN",
            None,
            f"{design:.0f} kN of the stages (factored) + temperature {st.temperatureFactor:g} × "
            f"α ΔT E A × {st.temperatureRestraint:g} = {temperature:.0f} kN; self weight "
            f"{st.selfWeightFactor:g} × w L²/8 = {moment:.1f} kN·m over {length:.2f} m "
            f"({cite('struts')})",
            flag=True,
        )
    ]
    out += _steel_rows(
        f"{sid} ({section.name})", shape, steel, length, axial, moment, shear, "column"
    )
    if support.kind == "raker":
        horizontal = design * math.cos(math.radians(support.inclination))
        vertical = design * math.sin(math.radians(support.inclination))
        out.append(
            _check(
                f"{sid}: thrust on the base",
                vertical,
                vertical,
                "kN",
                None,
                f"the thrust block or base takes H = {horizontal:.0f} kN and V = {vertical:.0f} "
                "kN per raker (factored); design it with the base slab",
                flag=True,
            )
        )
    return out


def _waler_checks(ctx, support, per_m, rules) -> list[dict]:
    found = _steel_section(support.waler)
    steel = _steel(ctx, support.material)
    if found is None or steel is None:
        return []
    section, shape = found
    s = support.spacing / 1e3
    st = rules.struts
    w = per_m  # kN/m along the waler (factored)
    moment = st.walerMoment * w * s**2
    shear = st.walerShear * w * s
    rows = _steel_rows(
        f"{support.id} waler ({section.name})", shape, steel, s, 0.0, moment, shear, "beam"
    )
    note = f"w = {w:.1f} kN/m, M = {st.walerMoment:g} w s², V = {st.walerShear:g} w s"
    return [{**r, "note": f"{note}; {r.get('note', '')}".rstrip("; ")} for r in rows]


def _bond(soil: Soil, z: float, rules: Any) -> float:
    """Ultimate grout-ground bond τ [kPa] at depth z."""
    a = rules.anchors
    phi = soil.phi(z)
    if phi is not None:
        return _interp(a.bondGranular, phi)
    return min(a.bondCohesive * soil.cohesion(z), a.bondCohesiveMax)


def free_length(depth: float, height: float, theta: float, soil: Soil, rules: Any) -> float:
    """The least free length [m] of an anchor at ``depth`` inclined at ``theta`` [rad]: to the
    active wedge from the dig level at 45° - φ'/2 plus the clearance, at least the pack's."""
    a = rules.anchors
    phi = soil.mean(0.0, height)[1] or 0.0
    t = math.tan(math.radians(45 - phi / 2))
    x = max(height - depth, 0.0) * t / (1 + math.tan(theta) * t)
    clearance = max(a.wedgeClearance * height, a.wedgeClearanceMin)
    return max((x + clearance) / math.cos(theta), a.freeLengthMin)


def bond_capacity(soil, depth, theta, start, length, diameter, rules) -> float:
    """π D ∫ τ dl [kN] over ``length`` m of the anchor from ``start`` m along it."""
    total = 0.0
    steps = max(int(length / 0.1), 1)
    dl = length / steps
    for k in range(steps):
        s = start + (k + 0.5) * dl
        total += _bond(soil, depth + s * math.sin(theta), rules) * dl
    return math.pi * diameter * total


def _anchor_checks(support, working, depth, found, soil, rules, row) -> list[dict]:
    a = rules.anchors
    sid = support.id
    theta = math.radians(support.inclination)
    tendon = a.permanentTendonFactor if support.permanent else a.tendonFactor
    ground = a.permanentGroundFactor if support.permanent else a.groundFactor
    proof = (a.permanentProofFactor if support.permanent else a.proofFactor) * working
    lock = found["preloads"].get(sid, 0.0) * (support.spacing / 1e3) / math.cos(theta)
    diameter = (support.groutDiameter or a.groutDiameter) / 1e3
    need_free = free_length(depth, found["design"], theta, soil, rules)
    start = support.freeLength / 1e3 if support.freeLength else need_free
    # The fixed length the bond needs.
    need = ground * working
    fixed_req = None
    length = a.fixedLengthMin
    while length <= a.fixedLengthMax + 1e-9:
        if bond_capacity(soil, depth, theta, start, length, diameter, rules) >= need:
            fixed_req = length
            break
        length += 0.25
    ref = cite("anchors")
    row.update(
        {
            "proof": round(proof, 1),
            "lockOff": round(lock, 1),
            "freeRequired": round(need_free, 2),
            "fixedRequired": None if fixed_req is None else round(fixed_req, 2),
        }
    )
    out = [
        _check(
            f"{sid}: working load",
            working,
            working,
            "kN",
            None,
            f"the largest anchor force of the stages (unfactored run) × {support.spacing:g} mm / "
            f"cos {support.inclination:g}°; lock-off {lock:.0f} kN, proof load {proof:.0f} kN "
            f"({a.standard}; {ref})",
            flag=True,
        )
    ]
    if support.tendonArea and support.tendonStrength:
        strength = support.tendonArea * support.tendonStrength / 1e3
        out.append(
            _check(
                f"{sid}: tendon",
                working * tendon,
                strength,
                "kN",
                None,
                f"{tendon:g} × Tw against fpk A = {support.tendonStrength:g} × "
                f"{support.tendonArea:g} mm² ({ref})",
            )
        )
        out.append(
            _check(
                f"{sid}: tendon at the proof load",
                proof,
                a.testTendonLimit * strength,
                "kN",
                None,
                f"proof load against {a.testTendonLimit:g} fpk A ({ref})",
            )
        )
    else:
        out.append(
            _check(
                f"{sid}: tendon",
                working * tendon,
                working * tendon,
                "kN",
                None,
                f"needs fpk A ≥ {working * tendon:.0f} kN; no tendon given ({ref})",
                flag=True,
            )
        )
    if support.freeLength:
        out.append(
            _check(
                f"{sid}: free length",
                need_free,
                support.freeLength / 1e3,
                "m",
                None,
                f"beyond the active wedge plus max({a.wedgeClearance:g} H, "
                f"{a.wedgeClearanceMin:g} m), at least {a.freeLengthMin:g} m ({ref})",
            )
        )
    if support.fixedLength:
        capacity = bond_capacity(
            soil,
            depth,
            theta,
            start,
            min(support.fixedLength / 1e3, a.fixedLengthMax),
            diameter,
            rules,
        )
        out.append(
            _check(
                f"{sid}: fixed length (bond)",
                need,
                capacity,
                "kN",
                None,
                f"π D Σ τ L over {support.fixedLength / 1e3:.2f} m (at most "
                f"{a.fixedLengthMax:g} m counted), D = {diameter * 1e3:.0f} mm, against "
                f"{ground:g} × Tw ({ref})",
            )
        )
        if support.fixedLength / 1e3 < a.fixedLengthMin:
            out.append(
                _check(
                    f"{sid}: least fixed length",
                    a.fixedLengthMin,
                    support.fixedLength / 1e3,
                    "m",
                    None,
                    ref,
                )
            )
    elif fixed_req is None:
        out.append(
            _check(
                f"{sid}: fixed length (bond)",
                need,
                bond_capacity(soil, depth, theta, start, a.fixedLengthMax, diameter, rules),
                "kN",
                None,
                f"the longest counted fixed length {a.fixedLengthMax:g} m does not carry "
                f"{ground:g} × Tw: a larger diameter, more anchors or a lower spacing ({ref})",
            )
        )
    else:
        out.append(
            _check(
                f"{sid}: fixed length (bond)",
                fixed_req,
                fixed_req,
                "m",
                None,
                f"required {fixed_req:.2f} m (D = {diameter * 1e3:.0f} mm, {ground:g} × Tw); "
                f"free length at least {need_free:.2f} m; none given ({ref})",
                flag=True,
            )
        )
    return out


def base_checks(excavation: Any, found: dict[str, Any], soil: Soil) -> list[dict]:
    """Basal heave of a cohesive base and piping at the toe (see the module notes)."""
    rules = table()
    h = rules.heave
    dig = found["design"]
    toe = found["length"]
    out: list[dict[str, Any]] = []
    ref = cite("heave")
    if soil.phi(dig + 1e-3) is None:
        widths = _plan(excavation)
        if widths is None:
            out.append(
                _check(
                    "Basal heave",
                    0.0,
                    0.0,
                    "",
                    None,
                    f"cohesive base: give the excavation's outline for the basal heave ({ref})",
                    flag=True,
                )
            )
        else:
            b, length = widths
            cu = soil.cohesion(dig + 1e-3)
            nc = min(5 * (1 + 0.2 * min(dig / b, 2.5)) * (1 + 0.2 * b / length), h.basalNcMax)
            load = soil.sigma_v(dig) + found["q"]
            out.append(
                _check(
                    "Basal heave",
                    h.basalFactor * load,
                    nc * cu,
                    "kPa",
                    None,
                    f"Nc cu = {nc:.2f} × {cu:.1f} against {h.basalFactor:g} × (σv + q) = "
                    f"{h.basalFactor:g} × {load:.1f}; Nc = 5 (1 + 0.2 H/B)(1 + 0.2 B/L), B = "
                    f"{b:.2f}, L = {length:.2f} m ({ref})",
                )
            )
    wt = soil.water_table
    if wt is not None and dig > wt and found["section"].water and soil.phi(dig + 1e-3) is not None:
        head = dig - wt
        d = toe - dig
        i_exit = head / (math.pi * d)
        layer = soil._layer(dig + 1e-3)
        critical = (layer[3] - GAMMA_W) / GAMMA_W
        out.append(
            _check(
                "Piping at the toe",
                h.pipingFactor * i_exit,
                critical,
                "",
                None,
                f"i = Δh / (π d) = {head:.2f} / (π × {d:.2f}) = {i_exit:.3f} × "
                f"{h.pipingFactor:g} against icr = γ'/γw = {critical:.3f} (Harr; one wall in deep "
                f"uniform soil: a flow net decides for layers) ({ref})",
            )
        )
    return out


def _plan(excavation: Any) -> tuple[float, float] | None:
    """(B, L) [m] of the excavation's outline (its least rotated rectangle)."""
    if not excavation.outline:
        return None
    from shapely.geometry import Polygon

    box = Polygon(excavation.outline).minimum_rotated_rectangle
    xs, ys = box.exterior.coords.xy
    sides = sorted(math.dist((xs[i], ys[i]), (xs[i + 1], ys[i + 1])) / 1e3 for i in range(2))
    return (sides[0], sides[1]) if sides[0] > 0 else None


# ─────────────────────────────── entry ───────────────────────────────


def method_lines() -> list[str]:
    """The method of the staged analysis for the report, with the pack's clauses."""
    rules = table()
    if rules is None:
        return []
    names = "; ".join(a.name for a in rules.analyses)
    return [
        (
            f"Staged excavations ({cite('method')}): the embedded wall per metre run on "
            "elastic-plastic soil springs (at rest to active behind, to passive in front, kh by "
            f"the code pack's {rules.subgrade.method} method), {rules.earthPressure.activeMethod} "
            f"and {rules.earthPressure.passiveMethod} pressures with δa = "
            f"{rules.earthPressure.activeFriction:g} φ' and δp = "
            f"{rules.earthPressure.passiveFriction:g} φ', water both sides, strip loads of adjoining "
            "footings; the supports as springs from the stage they are placed in; the last stage "
            f"dug with the unplanned overdig. Runs: {names} ({cite('effects')})."
        ),
        (
            "Supports: struts and rakers by the code pack's steel member checks with the "
            f"temperature force and the self weight ({cite('struts')}); walers continuous over "
            f"the supports; ground anchors by {rules.anchors.standard}: tendon, free length "
            "beyond the active wedge, bond length by the grout-ground bond, proof and lock-off "
            f"loads ({cite('anchors')}); basal heave and piping at the toe ({cite('heave')})."
        ),
    ]


def support_checks(ctx: Any, excavation: Any, ground: float, soil: Soil) -> dict[str, Any] | None:
    """The staged analysis and design of an excavation's wall with a ``wallType``: ``{checks,
    notes, support}`` (``support`` the curves and rows for the editor, the report and the
    drawings), or None when the wall has no type."""
    wall = getattr(excavation, "wall", None)
    if wall is None or wall.wallType is None:
        return None
    if table() is None:
        name = code_context.code_name()
        return {
            "checks": [],
            "notes": [f"Staged excavation support: not covered by the code pack {name}"],
            "support": None,
        }
    if ground - excavation.bottomLevel <= 0:
        return None
    found = analyse(ctx, excavation, ground, soil)
    if isinstance(found, str):
        return {
            "checks": [
                _check(
                    "Excavation support analysis", 1.0, 0.0, "", None, f"{found} ({cite('method')})"
                )
            ],
            "notes": [],
            "support": None,
        }
    env = envelopes(found)
    checks = wall_design(ctx, wall, found, env)
    support_rows_checks, support_rows = support_design(ctx, excavation, found, env, soil)
    checks += support_rows_checks
    checks += base_checks(excavation, found, soil)
    limit = table().deflectionShare * found["height"]
    ymax = float(np.max(np.abs(env["y"])))
    checks.append(
        _check(
            "Wall deflection",
            ymax * 1e3,
            limit * 1e3,
            "mm",
            "service",
            f"the largest of the stages (unfactored run) against {table().deflectionShare:g} H "
            f"({cite('deflection')}); reported",
            flag=True,
        )
    )
    reference = found["runs"][found["reference"]]
    stage_rows = []
    for st in reference["stages"]:
        stage_rows.append(
            {
                "name": st["stage"].name,
                "dig": round(st["stage"].dig, 3),
                "Mmax": round(float(np.max(st["M"])), 1),
                "Mmin": round(float(np.min(st["M"])), 1),
                "Vmax": round(float(np.max(np.abs(st["V"]))), 1),
                "ymax": round(float(np.max(np.abs(st["y"]))) * 1e3, 1),
                "mobilised": round(st["mobilised"], 3),
                "forces": {k: round(v, 1) for k, v in st["forces"].items()},
            }
        )
    z = env["z"]
    last = reference["stages"][-1]
    curves = _sample(z, env["Mpos"], env["Mneg"], env["V"], env["y"] * 1e3)
    pressures = _sample(z, last["behind"], last["front"])
    support = {
        "wallType": wall.wallType,
        "section": found["section"].text,
        "ei": round(found["section"].ei, 1),
        "length": round(found["length"], 3),
        "toe": found["toeHow"],
        "design": round(found["design"], 3),
        "overdig": round(found["overdig"], 3),
        "surcharge": round(found["q"], 2),
        "runs": [r["case"].name for r in found["runs"]],
        "factors": [round(r["factor"], 3) for r in found["runs"]],
        "stages": stage_rows,
        "envelope": {
            "z": curves[0],
            "Mpos": curves[1],
            "Mneg": curves[2],
            "V": curves[3],
            "y": curves[4],
        },
        "pressures": {"z": pressures[0], "behind": pressures[1], "front": pressures[2]},
        "supports": support_rows,
    }
    return {
        "checks": checks,
        "notes": [f"excavation support: {n}" for n in found["notes"]],
        "support": support,
    }

"""2D geotechnical finite elements of a slope's section, plane strain (alpha 9 L8).

Optional and for experienced users: the limit equilibrium of
:mod:`saengine.substructure.slope_stability` is the check; the FE is reported beside it (its
factor of safety by strength reduction is a flagged row, never the governing one). It analyses
the same :class:`~saengine.substructure.slope_stability.Section`:

- **mesh**: the strata as plane surfaces meshed together by Gmsh (:func:`saengine.fem.mesh.mesh`,
  mostly four-node quadrilaterals, triangles where they do not fit), the excavation's wall and
  dig levels as lines the mesh follows; ``SlopeFE.meshSize`` the element size;
- **soil elements**: OpenSees ``quad`` / ``tri31`` in plane strain (thickness 1 m) with one
  material per soil (``SlopeSoil.model``):
  - ``mohrCoulomb`` (default): ``DruckerPrager`` matched to Mohr-Coulomb in plane strain
    (α = tan φ' / √(9 + 12 tan² φ'), k = 3 c' / √(9 + 12 tan² φ'); ρ = √2 α, σY = √3 k; the
    plastic potential by the dilatancy ψ in the same way), perfectly plastic; an undrained soil
    with φ = 0 and c = cu;
  - ``multiYield`` (hardening): ``PressureDependMultiYield`` (drained, φ') or
    ``PressureIndependMultiYield`` (undrained, cu), nested yield surfaces with kinematic
    hardening (Elgamal et al. 2003; the static parameters only, the liquefaction ones at their
    defaults);
  - ``vonMises``: ``J2Plasticity`` with σY = √3 cu (undrained clay);
  E from the soil (else the excavation table's correlation with φ' or cu), ν from the soil
  (else K0 / (1 + K0), K0 = 1 - sin φ' (Jaky), so the elastic gravity stage gives the at-rest
  stresses on level ground);
- **initial stresses**: gravity (lumped nodal weights: γ above the water line, γ - γw below it,
  effective stresses with hydrostatic pore pressures; no seepage forces) on the elastic material
  (``updateMaterialStage`` 0), then the materials made plastic (stage 1); base fixed, sides on
  rollers;
- **staged construction** (``SlopeFE.excavation``: an excavation of 9 Substructure with a typed
  embedded wall, alpha 9 P1): the wall as elastic beams (EI of P1's wall section, EA of a solid
  plate of that stiffness; no weight, no interface: the soil is bonded to it) wished in place,
  its forces reported as their change after the gravity stage; P1's stages
  (:func:`saengine.substructure.excavation_support.stages_of`, with its overdig): the supports
  placed (springs to fixed points along the strut, anchor or raker, P1's stiffness per metre,
  compression-only struts and rakers, tension-only anchors, the preload), then the soil on the
  ``SlopeFE.side`` of the wall above the dig level removed (its elements' forces on the remaining
  mesh released over the stage's load steps), supports removed released the same way; the
  excavation is the half of a symmetric one (the section's edge a plane of symmetry);
- **strength reduction** (``SlopeFE.strengthReduction``): c'/F, tan φ'/F (cu/F) of every soil,
  each trial a fresh analysis of gravity and the stages on the plastic materials (Griffiths and
  Lane 1999), F by bisection between a trial that converges and one that does not.

Outputs: the displacements of the nodes, the stresses of the elements, the plastic points (the
in-plane Mohr-Coulomb shear mobilised at least 98 %, or tension), the wall's moment, shear and
axial force envelopes, the supports' forces by stage.

Not modelled: seepage and consolidation, interface elements, the anchors' grout bodies, large
deformations, the seismic coefficients. Units: kN, m, kPa inside; the library's mm in.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.substructure.slope_stability import GAMMA_W, Case, Section, SoilProps, cite

#: OpenSees is one global model per process: our runs take turns.
_OPS = threading.Lock()
#: Smallest cohesion of a Drucker-Prager soil [kPa] (an apex at zero stress does not converge).
MIN_COHESION = 0.5
#: Share of the strength at which a point counts as plastic.
PLASTIC_SHARE = 0.98
#: Strength reduction: the first trial, the largest, the tolerance of the bisection.
SRF_START = 1.0
SRF_MAX = 10.0
SRF_TOLERANCE = 0.02
#: Halvings of a load step before a stage counts as not converged.
CUTS = 6
#: Reference concrete and steel moduli of the wall's equivalent plate [kPa].
WALL_E = {"concrete": 30e6, "steel": 200e6}
#: Mass density of soil per unit weight [t/m³ per kN/m³] (PDMY/PIMY need ρ).
DENSITY = 1 / 9.81


def regions(sec: Section, tol: float = 1e-3) -> list[tuple[int, list[tuple[float, float]]]]:
    """(stratum, polygon [m]) of every piece of every stratum with some thickness."""
    xs = np.unique(np.concatenate([[sec.x0, sec.x1], sec.breakpoints()]))
    for _ in range(2):  # add the points where a line meets the one above or the base
        tops = sec.tops(xs)
        extra = []
        for k, line in enumerate(sec.lines, start=1):
            raw = np.interp(xs, line[:, 0], line[:, 1])
            for other in (tops[k - 1], np.full_like(xs, sec.base)):
                d = raw - other
                for i in range(len(xs) - 1):
                    if d[i] * d[i + 1] < 0:
                        extra.append(xs[i] + (xs[i + 1] - xs[i]) * d[i] / (d[i] - d[i + 1]))
        if not extra:
            break
        xs = np.unique(np.concatenate([xs, extra]))
    tops = sec.tops(xs)
    out: list[tuple[int, list[tuple[float, float]]]] = []
    for k in range(len(sec.soils)):
        h = tops[k] - tops[k + 1]
        i = 0
        while i < len(xs) - 1:
            if max(h[i], h[i + 1]) <= tol:
                i += 1
                continue
            j = i
            while j + 1 < len(xs) - 1 and max(h[j + 1], h[j + 2]) > tol:
                j += 1
            top = [(float(xs[m]), float(tops[k][m])) for m in range(i, j + 2)]
            bottom = [(float(xs[m]), float(tops[k + 1][m])) for m in range(j + 1, i - 1, -1)]
            polygon: list[tuple[float, float]] = []
            for p in top + bottom:
                if not polygon or math.dist(p, polygon[-1]) > 1e-6:
                    polygon.append(p)
            if len(polygon) > 1 and math.dist(polygon[0], polygon[-1]) <= 1e-6:
                polygon.pop()
            if len(polygon) >= 3:
                out.append((k, polygon))
            i = j + 1
    return out


@dataclass
class Excavation:
    """P1's excavation in the section: the wall's position, top and toe [m], its EI and EA per
    metre, the stages (dig levels [m], supports placed and removed) and the supports."""

    x: float
    top: float
    toe: float
    side: float  # +1: dug out to the right of the wall, -1: to the left
    ei: float
    ea: float
    stages: list[tuple[str, float, list[str], list[str]]]
    supports: dict[str, dict[str, Any]]
    text: str
    notes: list[str] = field(default_factory=list)


def excavation_of(ctx: Any, slope: Any, sec: Section) -> Excavation | str | None:
    """The excavation the slope's FE models (P1's wall, stages and supports), why not, or
    None when it models none."""
    fe = slope.fe
    if fe is None or fe.excavation is None:
        return None
    from saengine.substructure import excavation_support as p1
    from saengine.substructure.earth_pressure import soil_column
    from saengine.substructure.piles import profiles_of

    rules = p1.table()
    if rules is None:
        return "the code pack does not cover staged excavations (excavationSupport)"
    excavation = next((e for e in ctx.substructure.excavations if e.id == fe.excavation), None)
    if excavation is None or excavation.wall is None or excavation.wall.wallType is None:
        return f"excavation {fe.excavation} has no embedded wall with a wall type"
    if fe.wallX is None:
        return "the wall's position along the section is not given"
    wall = excavation.wall
    section = p1.wall_section(ctx, wall, rules)
    if isinstance(section, str):
        return section
    ground = excavation.groundLevel if excavation.groundLevel is not None else ctx.ground_level
    height = (ground - excavation.bottomLevel) / 1e3
    stages = p1.stages_of(wall, ground, excavation.bottomLevel)
    stages[-1].dig += p1._overdig(height)
    soil = soil_column(profiles_of(ctx.soil_text)[0], 0.0, 0.0, excavation.designWaterTable)
    length, _how = p1._toe(wall, ground, soil, height, p1._surcharge(wall, excavation))
    x = fe.wallX / 1e3
    top = float(sec.ground(x))
    toe = ground / 1e3 - length
    if toe <= sec.base + 0.1:
        return f"the wall's toe ({toe:.2f} m) is not above the section's base ({sec.base:.2f} m)"
    kind = "steel" if wall.wallType in ("sheetPile", "soldier") else "concrete"
    e_ref = WALL_E[kind]
    t_eq = (12 * section.ei / e_ref) ** (1 / 3)
    supports: dict[str, dict[str, Any]] = {}
    bottom = stages[-1].dig
    for s in wall.supports:
        depth = (ground - s.level) / 1e3
        k, how = p1.support_stiffness(ctx, s, depth, bottom, rules)
        preload = float(s.preload or 0.0) / (s.spacing / 1e3)
        if s.kind == "anchor" and s.preload is None:
            preload = 0.0  # the lock-off load comes from P1's working load, not known here
        supports[s.id] = {
            "kind": s.kind,
            "level": s.level / 1e3,
            "inclination": float(s.inclination),
            "k": float(k),
            "preload": preload,
            "how": how,
        }
    side = 1.0 if fe.side == "right" else -1.0
    return Excavation(
        x,
        top,
        toe,
        side,
        float(section.ei),
        e_ref * t_eq,
        [(st.name, ground / 1e3 - st.dig, list(st.install), list(st.remove)) for st in stages],
        supports,
        f"{excavation.id}: {section.text}",
        [f"wall EA of a solid plate {t_eq * 1e3:.0f} mm thick of the same EI"],
    )


# ─────────────────────────────── the model ───────────────────────────────


@dataclass
class Model:
    nodes: dict[int, tuple[float, float]]
    elements: dict[int, tuple[tuple[int, ...], int]]  # tag -> (nodes, stratum)
    gravity: dict[int, dict[int, float]]  # element -> node -> vertical load [kN] (down)
    wall: list[int] = field(default_factory=list)  # beam elements top down
    wall_nodes: list[int] = field(default_factory=list)  # beam nodes top down
    tie: dict[int, int] = field(default_factory=dict)  # beam node -> soil node
    fixed: dict[int, tuple[int, int]] = field(default_factory=dict)
    ndf: dict[int, int] = field(default_factory=dict)
    next_tag: int = 0
    pattern: int = 10
    series: int = 10


def _mesh(sec: Section, size: float, excavation: Excavation | None) -> Any:
    from saengine.fem.mesh import Surface as MeshSurface
    from saengine.fem.mesh import mesh as gmsh_mesh

    surfaces = [
        MeshSurface(f"S{k}_{i}", [(x * 1e3, z * 1e3, 0.0) for x, z in polygon], normal=(0, 0, 1))
        for i, (k, polygon) in enumerate(regions(sec))
    ]
    lines: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = []
    if excavation is not None:
        x = excavation.x
        lines.append(
            ("wall", (x * 1e3, excavation.top * 1e3, 0.0), (x * 1e3, excavation.toe * 1e3, 0.0))
        )
        edge = sec.x1 if excavation.side > 0 else sec.x0
        for s, (_name, level, _i, _r) in enumerate(excavation.stages):
            far = edge
            xs = np.linspace(x, edge, 101)
            below = sec.ground(xs) >= level + 0.01
            if not below[1:].all():
                far = float(xs[int(np.argmin(below[1:]))])
            if abs(far - x) > 0.05:
                lines.append(
                    (f"dig{s}", (x * 1e3, level * 1e3, 0.0), (far * 1e3, level * 1e3, 0.0))
                )
    return gmsh_mesh(lines, surfaces, size)


def _k0(soil: SoilProps) -> float:
    return 0.6 if soil.undrained else 1 - math.sin(math.radians(soil.phi))


def _modulus(soil: SoilProps) -> float:
    """E [kPa]: the soil's, else the excavation table's correlation, else 20 MPa."""
    if soil.E:
        return soil.E * 1e3
    from saengine.substructure import excavation_support as p1

    rules = p1.table()
    if rules is not None:
        sub = rules.subgrade
        if not soil.undrained:
            return p1._interp(sub.granularModulus, soil.phi) * 1e3
        return sub.cohesiveModulus * max(soil.cu or soil.c, 1.0)
    return 20e3


def _material(ops: Any, tag: int, soil: SoilProps, srf: float) -> str:
    """Define the soil's nD material with strengths divided by ``srf``; its description."""
    e = _modulus(soil)
    nu = soil.poisson if soil.poisson is not None else min(_k0(soil) / (1 + _k0(soil)), 0.45)
    bulk = e / (3 * (1 - 2 * nu))
    shear = e / (2 * (1 + nu))
    c = soil.c / srf
    phi = 0.0 if soil.undrained else math.degrees(math.atan(math.tan(math.radians(soil.phi)) / srf))
    model = soil.model or "mohrCoulomb"
    if model == "vonMises" and soil.undrained:
        sig = math.sqrt(3) * max(c, MIN_COHESION)
        ops.nDMaterial("J2Plasticity", tag, bulk, shear, sig, sig, 0.0, 0.0)
        return f"von Mises, σY = √3 cu = {sig:.1f} kPa"
    if model == "multiYield" and srf == 1.0:
        rho = soil.gamma * DENSITY
        if soil.undrained:
            ops.nDMaterial(
                "PressureIndependMultiYield", tag, 2, rho, shear, bulk, max(c, MIN_COHESION), 0.1
            )
            return f"pressure-independent multi-yield, cu = {c:.1f} kPa"
        ops.nDMaterial(
            "PressureDependMultiYield",
            tag,
            2,
            rho,
            shear,
            bulk,
            phi,
            0.1,
            80.0,
            0.5,
            max(phi - 7.0, 5.0),
            0.07,
            0.4,
            2.0,
            10.0,
            0.01,
            1.0,
        )
        return f"pressure-dependent multi-yield, φ' = {phi:.1f}°"
    t = math.tan(math.radians(phi))
    root = math.sqrt(9 + 12 * t * t)
    alpha = t / root
    k = 3 * max(c, MIN_COHESION) / root
    tp = math.tan(math.radians(min(soil.dilatancy or 0.0, phi)))
    alpha_bar = tp / math.sqrt(9 + 12 * tp * tp)
    ops.nDMaterial(
        "DruckerPrager",
        tag,
        bulk,
        shear,
        math.sqrt(3) * k,
        math.sqrt(2) * alpha,
        math.sqrt(2) * alpha_bar,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        soil.gamma * DENSITY,
    )
    return f"Mohr-Coulomb (Drucker-Prager, plane strain), c = {c:.1f} kPa, φ = {phi:.1f}°"


def _area(points: list[tuple[float, float]]) -> float:
    return 0.5 * abs(
        sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1], strict=True))
    )


def build(ops: Any, sec: Section, mesh_: Any, srf: float, excavation: Excavation | None) -> Model:
    """The OpenSees model of the meshed section with strengths divided by ``srf``."""
    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 2)
    nodes = {t: (float(p[0]) / 1e3, float(p[1]) / 1e3) for t, p in mesh_.nodes.items()}
    used = {n for elements in mesh_.surfaces.values() for e in elements for n in e}
    model = Model({t: nodes[t] for t in used}, {}, {})
    for t in sorted(used):
        ops.node(t, *nodes[t])
        model.ndf[t] = 2
    xs = [p[0] for p in model.nodes.values()]
    zs = [p[1] for p in model.nodes.values()]
    xmin, xmax, zmin = min(xs), max(xs), min(zs)
    for t, (x, z) in model.nodes.items():
        if abs(z - zmin) < 1e-6:
            ops.fix(t, 1, 1)
            model.fixed[t] = (1, 1)
        elif abs(x - xmin) < 1e-6 or abs(x - xmax) < 1e-6:
            ops.fix(t, 1, 0)
            model.fixed[t] = (1, 0)
    for k, soil in enumerate(sec.soils):
        _material(ops, k + 1, soil, srf)
    tag = 0
    for key, elements in mesh_.surfaces.items():
        k = int(key[1:].split("_")[0])
        for element in elements:
            tag += 1
            pts = [model.nodes[n] for n in element]
            if len(element) == 4:
                ops.element("quad", tag, *element, 1.0, "PlaneStrain", k + 1, 0.0, 0.0, 0.0, 0.0)
            else:
                ops.element("tri31", tag, *element, 1.0, "PlaneStrain", k + 1, 0.0, 0.0, 0.0, 0.0)
            model.elements[tag] = (tuple(element), k)
            cx = sum(p[0] for p in pts) / len(pts)
            cz = sum(p[1] for p in pts) / len(pts)
            soil = sec.soils[k]
            zw = sec.water_level(cx)
            gamma = soil.gamma_sat - GAMMA_W if zw is not None and cz < zw else soil.gamma
            share = _area(pts) * gamma / len(element)
            model.gravity[tag] = dict.fromkeys(element, share)
    model.next_tag = max(max(used, default=0), tag) + 1
    if excavation is not None and "wall" in mesh_.lines:
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.geomTransf("Linear", 1)
        segments = mesh_.lines["wall"]
        soil_nodes = [segments[0][0]] + [b for _, b in segments]
        # Top down: the line was given from the top to the toe.
        for n in soil_nodes:
            t = model.next_tag
            model.next_tag += 1
            x, z = nodes[n]
            ops.node(t, x, z)
            model.ndf[t] = 3
            if n not in model.nodes:  # a wall node below the soil's mesh (should not happen)
                ops.fix(t, 1, 1, 0)
            else:
                ops.equalDOF(n, t, 1, 2)
            model.tie[t] = n
            model.wall_nodes.append(t)
        e = 1e7
        for a, b in zip(model.wall_nodes, model.wall_nodes[1:], strict=False):
            t = model.next_tag
            model.next_tag += 1
            ops.element("elasticBeamColumn", t, a, b, excavation.ea / e, e, excavation.ei / e, 1)
            model.wall.append(t)
        ops.model("basic", "-ndm", 2, "-ndf", 2)
    return model


def _analysis(ops: Any) -> None:
    ops.wipeAnalysis()
    ops.constraints("Transformation")
    ops.numberer("RCM")
    try:
        ops.system("UmfPack")
    except Exception:  # noqa: BLE001 - a build without UMFPACK
        ops.system("SparseGeneral")
    ops.test("NormDispIncr", 1e-6, 60)
    ops.algorithm("Newton")


def _advance(ops: Any, steps: int, grow: bool = False) -> bool:
    """Load the active patterns from 0 to 1 in ``steps`` steps (cut when they do not
    converge, other algorithms tried); False when a step does not converge. With ``grow``
    a cut step grows back once it converges again."""
    _analysis(ops)
    done, dl, cuts = 0.0, 1.0 / steps, 0
    while done < 1.0 - 1e-9:
        step = min(dl, 1.0 - done)
        ops.integrator("LoadControl", step)
        ops.analysis("Static")
        ok = ops.analyze(1)
        if ok != 0:
            for algorithm in (("KrylovNewton",), ("ModifiedNewton", "-initial")):
                ops.algorithm(*algorithm)
                ok = ops.analyze(1)
                ops.algorithm("Newton")
                if ok == 0:
                    break
        if ok == 0:
            done += step
            cuts = 0
            if grow:
                # A cut step kept for the rest of the loading made every strength reduction
                # trial take hundreds of tiny steps (hours for one slope).
                dl = min(dl * 2, 1.0 / steps)
            continue
        cuts += 1
        dl /= 2
        if cuts > CUTS:
            return False
    return True


def _stage_materials(ops: Any, sec: Section, stage: int) -> None:
    for k in range(len(sec.soils)):
        try:
            ops.updateMaterialStage("-material", k + 1, "-stage", stage)
        except Exception:  # noqa: BLE001, S110 - a material without stages
            pass


def _gravity(ops: Any, model: Model, steps: int, grow: bool = False) -> bool:
    ops.timeSeries("Linear", model.series)
    ops.pattern("Plain", model.pattern, model.series)
    loads: dict[int, float] = {}
    for share in model.gravity.values():
        for n, value in share.items():
            loads[n] = loads.get(n, 0.0) + value
    for n, value in loads.items():
        ops.load(n, 0.0, -value)
    model.series += 1
    model.pattern += 1
    ok = _advance(ops, steps, grow)
    ops.loadConst("-time", 0.0)
    return ok


def _forces(ops: Any, tag: int) -> dict[int, list[float]]:
    """An element's resisting forces at its nodes."""
    nodes = [int(n) for n in ops.eleNodes(tag)]
    values = [float(v) for v in ops.eleResponse(tag, "forces")]
    per = len(values) // max(len(nodes), 1)
    return {n: values[i * per : (i + 1) * per] for i, n in enumerate(nodes)}


def _release(ops: Any, model: Model, tags: list[int], steps: int, grow: bool = False) -> bool:
    """Remove elements and release their forces on the rest over ``steps`` steps."""
    if not tags:
        return True
    resisting: dict[int, list[float]] = {}
    weights: dict[int, float] = {}
    for tag in tags:
        for n, f in _forces(ops, tag).items():
            acc = resisting.setdefault(n, [0.0] * len(f))
            for i, v in enumerate(f):
                acc[i] += v
        for n, w in model.gravity.pop(tag, {}).items():
            weights[n] = weights.get(n, 0.0) + w
    for tag in tags:
        ops.remove("element", tag)
        model.elements.pop(tag, None)
    alive = {n for nodes, _ in model.elements.values() for n in nodes}
    alive |= set(model.tie.values())
    for n in resisting:
        if n not in alive and n in model.ndf and model.ndf[n] == 2:
            fixed = model.fixed.get(n, (0, 0))
            free = (0 if fixed[0] else 1, 0 if fixed[1] else 1)
            if any(free):
                ops.fix(n, *free)
                model.fixed[n] = (1, 1)
    constant = model.series
    ops.timeSeries("Constant", constant)
    ops.pattern("Plain", model.pattern, constant)
    for n, f in resisting.items():
        if n in alive:
            ops.load(n, *[-v for v in f])
    model.pattern += 1
    ops.timeSeries("Linear", constant + 1)
    ops.pattern("Plain", model.pattern, constant + 1)
    for n, f in resisting.items():
        if n not in alive:
            continue
        values = list(f)
        values[1] -= -weights.get(n, 0.0)  # the removed weight (its load was -w)
        ops.load(n, *values)
    model.pattern += 1
    model.series += 2
    ok = _advance(ops, steps, grow)
    ops.loadConst("-time", 0.0)
    return ok


def _place_support(
    ops: Any, model: Model, sid: str, support: dict[str, Any], excavation: Excavation
) -> int | None:
    """A support as a spring from a fixed point to the wall node at its level; its element."""
    if not model.wall_nodes:
        return None
    levels = [ops.nodeCoord(n)[1] for n in model.wall_nodes]
    node = model.wall_nodes[int(np.argmin([abs(z - support["level"]) for z in levels]))]
    theta = math.radians(support["inclination"])
    side = excavation.side
    if support["kind"] == "anchor":  # into the retained ground, down: from its end to the wall
        x1, z1 = side * math.cos(theta), math.sin(theta)
        base_tag = "elastic-tension"
    elif support["kind"] == "raker":  # down into the excavation's base
        x1, z1 = -side * math.cos(theta), math.sin(theta)
        base_tag = "compression"
    else:
        x1, z1 = -side, 0.0
        base_tag = "compression"
    k = support["k"]
    ux, uz = float(ops.nodeDisp(node, 1)), float(ops.nodeDisp(node, 2))
    now = ux * x1 + uz * z1
    signed = support["preload"] if base_tag == "elastic-tension" else -support["preload"]
    mat = model.next_tag
    model.next_tag += 2
    if base_tag == "elastic-tension":
        ops.uniaxialMaterial("Elastic", mat, k, 0.0, 0.0)
    else:
        ops.uniaxialMaterial("ENT", mat, k)
    used = mat
    try:
        ops.uniaxialMaterial("InitStrainMaterial", mat + 1, mat, -now + signed / k)
        used = mat + 1
    except Exception:  # noqa: BLE001, S110 - a build without it: the support starts unstressed
        pass
    ops.model("basic", "-ndm", 2, "-ndf", 3)
    anchor = model.next_tag
    model.next_tag += 1
    x, z = ops.nodeCoord(node)
    ops.node(anchor, x, z)
    ops.fix(anchor, 1, 1, 1)
    model.ndf[anchor] = 3
    element = model.next_tag
    model.next_tag += 1
    ops.element(
        "zeroLength",
        element,
        anchor,
        node,
        "-mat",
        used,
        "-dir",
        1,
        "-orient",
        x1,
        z1,
        0.0,
        -z1,
        x1,
        0.0,
    )
    ops.model("basic", "-ndm", 2, "-ndf", 2)
    model.gravity[element] = {}
    return element


def _support_force(ops: Any, tag: int) -> float:
    for key in ("basicForce", "basicForces", "force"):
        try:
            found = ops.eleResponse(tag, key)
        except Exception:  # noqa: BLE001, S112
            continue
        if found:
            return float(found[0])
    return 0.0


def _wall_forces(ops: Any, model: Model) -> list[tuple[float, float, float, float]]:
    """(z, N, V, M) section forces at each wall element's ends, top down (the end forces
    [N1, V1, M1, N2, V2, M2] on the element as section forces: -N1, V1, -M1 at its top and
    N2, -V2, M2 at its bottom, so both elements at a node agree; N positive in tension)."""
    out = []
    for tag in model.wall:
        a, b = (int(n) for n in ops.eleNodes(tag))
        f = [float(v) for v in ops.eleResponse(tag, "localForce")]
        out.append((ops.nodeCoord(a)[1], -f[0], f[1], -f[2]))
        out.append((ops.nodeCoord(b)[1], f[3], -f[4], f[5]))
    return out


def _plastic(ops: Any, model: Model, sec: Section, srf: float) -> dict[int, bool]:
    out = {}
    for tag, (_nodes, k) in model.elements.items():
        try:
            s = [float(v) for v in ops.eleResponse(tag, "stresses")]
        except Exception:  # noqa: BLE001, S112
            continue
        if len(s) < 3:
            continue
        points = len(s) // 3
        sx = sum(s[3 * i] for i in range(points)) / points
        sz = sum(s[3 * i + 1] for i in range(points)) / points
        txz = sum(s[3 * i + 2] for i in range(points)) / points
        soil = sec.soils[k]
        p = (sx + sz) / 2
        r = math.hypot((sx - sz) / 2, txz)
        c = soil.c / srf
        phi = 0.0 if soil.undrained else math.atan(math.tan(math.radians(soil.phi)) / srf)
        strength = c * math.cos(phi) - p * math.sin(phi)
        out[tag] = bool(r >= PLASTIC_SHARE * max(strength, 1e-9) or p + r > 1e-6 and c < 1e-6)
    return out


def run(
    sec: Section,
    mesh_: Any,
    srf: float,
    excavation: Excavation | None,
    steps: int,
    record: bool,
) -> dict[str, Any] | None:
    """One analysis: gravity, then the excavation's stages; None when a stage does not
    converge (with ``record``, the results of the stages reached are kept)."""
    from openseespy import opensees as ops

    model = build(ops, sec, mesh_, srf, excavation)
    # The analysis with the soil's own strengths starts elastic (the at-rest stresses); the
    # strength reduction trials are plastic from the start (Griffiths and Lane 1999).
    elastic_first = srf == 1.0
    _stage_materials(ops, sec, 0 if elastic_first else 1)
    # The trials of the strength reduction only ask "converged or not": they take the growing
    # step; the recorded analysis keeps the cut step (its path, near a limit state, is the one
    # the results are reported on).
    grow = not record
    ok = _gravity(ops, model, steps, grow)
    if elastic_first:
        _stage_materials(ops, sec, 1)
        ok = ok and _advance(ops, 1, grow)  # the plastic material in equilibrium
    if not ok:
        ops.wipe()
        return None
    base_wall = {i: v for i, v in enumerate(_wall_forces(ops, model))} if model.wall else {}
    stages: list[dict[str, Any]] = []
    springs: dict[str, int] = {}
    envelope: dict[float, list[float]] = {}
    failed = False
    if excavation is not None:
        removed: set[int] = set()
        side = excavation.side
        for name, level, install, remove in excavation.stages:
            for sid in remove:
                tag = springs.pop(sid, None)
                if tag is not None and not _release(ops, model, [tag], steps, grow):
                    failed = True
            for sid in install:
                support = excavation.supports.get(sid)
                if support is not None and sid not in springs:
                    tag = _place_support(ops, model, sid, support, excavation)
                    if tag is not None:
                        springs[sid] = tag
            dig = []
            for tag, (nodes, _k) in list(model.elements.items()):
                if tag in removed:
                    continue
                pts = [model.nodes[n] for n in nodes]
                cx = sum(p[0] for p in pts) / len(pts)
                cz = sum(p[1] for p in pts) / len(pts)
                if (cx - excavation.x) * side > 0 and cz > level:
                    dig.append(tag)
            if not failed and not _release(ops, model, dig, steps, grow):
                failed = True
            removed.update(dig)
            if failed:
                break
            if record:
                forces = _wall_forces(ops, model)
                rows = []
                for i, (z, n, v, m) in enumerate(forces):
                    _z0, n0, v0, m0 = base_wall.get(i, (z, 0.0, 0.0, 0.0))
                    rows.append((z, n - n0, v - v0, m - m0))
                    env = envelope.setdefault(round(z, 4), [0.0, 0.0, 0.0, 0.0])
                    env[0] = max(env[0], m - m0)
                    env[1] = min(env[1], m - m0)
                    env[2] = max(env[2], abs(v - v0))
                    env[3] = max(env[3], abs(n - n0))
                top = model.wall_nodes[0] if model.wall_nodes else None
                stages.append(
                    {
                        "name": name,
                        "level": round(level, 3),
                        "Mmax": round(max((r[3] for r in rows), default=0.0), 1),
                        "Mmin": round(min((r[3] for r in rows), default=0.0), 1),
                        "Vmax": round(max((abs(r[2]) for r in rows), default=0.0), 1),
                        "wallTop": None
                        if top is None
                        else round(float(ops.nodeDisp(top, 1)) * 1e3, 1),
                        "forces": {
                            sid: round(_support_force(ops, t), 1) for sid, t in springs.items()
                        },
                        "maxDisplacement": round(_max_disp(ops, model) * 1e3, 1),
                    }
                )
    if failed:
        ops.wipe()
        return {"stages": stages, "failed": True} if record else None
    out: dict[str, Any] = {"failed": False}
    if record:
        out["stages"] = stages
        out["envelope"] = {
            "z": [z for z in sorted(envelope, reverse=True)],
            "Mmax": [round(envelope[z][0], 1) for z in sorted(envelope, reverse=True)],
            "Mmin": [round(envelope[z][1], 1) for z in sorted(envelope, reverse=True)],
            "V": [round(envelope[z][2], 1) for z in sorted(envelope, reverse=True)],
            "N": [round(envelope[z][3], 1) for z in sorted(envelope, reverse=True)],
        }
        ids = sorted(model.nodes)
        index = {n: i for i, n in enumerate(ids)}
        plastic = _plastic(ops, model, sec, srf)
        out["mesh"] = {
            "nodes": [[round(model.nodes[n][0], 3), round(model.nodes[n][1], 3)] for n in ids],
            "elements": [[index[n] for n in nodes] for nodes, _ in model.elements.values()],
            "strata": [k for _, k in model.elements.values()],
            "plastic": [plastic.get(tag, False) for tag in model.elements],
            "displacement": [
                [
                    round(float(ops.nodeDisp(n, 1)) * 1e3, 2),
                    round(float(ops.nodeDisp(n, 2)) * 1e3, 2),
                ]
                for n in ids
            ],
        }
        out["maxDisplacement"] = round(_max_disp(ops, model) * 1e3, 1)
        out["plasticPoints"] = sum(1 for v in plastic.values() if v)
    ops.wipe()
    return out


def _max_disp(ops: Any, model: Model) -> float:
    return max(
        (math.hypot(float(ops.nodeDisp(n, 1)), float(ops.nodeDisp(n, 2))) for n in model.nodes),
        default=0.0,
    )


def strength_reduction(
    sec: Section, mesh_: Any, excavation: Excavation | None, steps: int
) -> tuple[float | None, str]:
    """The factor of safety by strength reduction, and how it was bounded."""
    lo, hi = None, None
    f = SRF_START
    if run(sec, mesh_, f, excavation, steps, False) is not None:
        lo = f
        while f < SRF_MAX:
            f = min(f * 1.5, SRF_MAX)
            if run(sec, mesh_, f, excavation, steps, False) is None:
                hi = f
                break
            lo = f
        if hi is None:
            return None, f"no failure up to a reduction of {SRF_MAX:g}"
    else:
        hi = f
        while f > 0.2:
            f /= 1.5
            if run(sec, mesh_, f, excavation, steps, False) is not None:
                lo = f
                break
            hi = f
        if lo is None:
            return None, "the reduced model does not converge even at F = 0.2"
    while hi - lo > SRF_TOLERANCE:
        mid = (lo + hi) / 2
        if run(sec, mesh_, mid, excavation, steps, False) is not None:
            lo = mid
        else:
            hi = mid
    return lo, f"between {lo:.3f} (converged) and {hi:.3f} (not converged)"


def analyse(ctx: Any, slope: Any, sec: Section, rules: Any, cases: list[Case]) -> dict[str, Any]:
    """The 2D FE of the slope's section: ``{"mesh", "stages", "envelope", "maxDisplacement",
    "plasticPoints", "fs", "fsHow", "required", "check", "materials", "notes", "excavation"}``,
    or ``{"error"}``."""
    from saengine.design.check import _check

    fe = slope.fe
    found = excavation_of(ctx, slope, sec)
    if isinstance(found, str):
        return {"error": f"2D FE: {found}"}
    excavation = found
    with _OPS:
        try:
            mesh_ = _mesh(sec, float(fe.meshSize), excavation)
        except Exception as error:  # noqa: BLE001 - Gmsh failures are reported
            return {"error": f"2D FE: the section could not be meshed: {error}"}
        if not mesh_.surfaces:
            return {"error": "2D FE: the section has no area to mesh"}
        result = run(sec, mesh_, 1.0, excavation, int(fe.steps), True)
        if result is None or result.get("failed"):
            out = {"error": "2D FE: the analysis does not converge with the soil's own strengths"}
            if result is not None:
                out["stages"] = result.get("stages", [])
            return out
        fs, how = (None, "not asked for")
        if fe.strengthReduction:
            fs, how = strength_reduction(sec, mesh_, excavation, int(fe.steps))
    static = [c for c in cases if not c.seismic] or cases
    required = max(c.required * c.tan_phi for c in static) if static else 1.0
    check = None
    if fe.strengthReduction:
        if fs is None:
            check = _check(
                "2D FE strength reduction", required, 0.0, "", None, f"{how}; reported", flag=True
            )
        else:
            check = _check(
                "2D FE strength reduction",
                required,
                fs,
                "",
                None,
                f"F = {fs:.2f} ({how}) ≥ {required:g} ({cite('required')}); reported beside the "
                "limit equilibrium",
                flag=True,
            )
    materials = []
    for soil in sec.soils:
        materials.append(
            {
                "soil": soil.id,
                "model": soil.model or "mohrCoulomb",
                "E": round(_modulus(soil) / 1e3, 1),
                "poisson": round(
                    soil.poisson
                    if soil.poisson is not None
                    else min(_k0(soil) / (1 + _k0(soil)), 0.45),
                    3,
                ),
            }
        )
    notes = ["2D FE: for experienced users; the limit equilibrium is the check"]
    if excavation is not None:
        notes += [f"2D FE: {n}" for n in excavation.notes]
    return {
        **result,
        "fs": None if fs is None else round(fs, 3),
        "fsHow": how,
        "required": required,
        "check": check,
        "materials": materials,
        "excavation": None
        if excavation is None
        else {
            "text": excavation.text,
            "x": excavation.x,
            "top": excavation.top,
            "toe": excavation.toe,
            "side": "right" if excavation.side > 0 else "left",
            "stages": [{"name": n, "level": round(lv, 3)} for n, lv, _i, _r in excavation.stages],
        },
        "notes": notes,
    }

"""The finite element check of a steel joint by the component-based finite element method
(CBFEM; alpha 9 track L6).

The joint's plates are shells; bolts, welds and the contact between plates are components
between them:

- **Plates** (:class:`Plate`): four-node shells (``ShellMITC4``) on a layered section of
  plate fibres (``LayeredShell`` of ``PlateFiber`` over ``J2Plasticity``): von Mises plasticity
  with linear hardening, the design yield strength ``yieldFactor`` Ã— fy and the tangent
  modulus ``hardeningRatio`` Ã— E of the pack (``connectionFe`` table,
  :mod:`saengine.codes.stability_tables`). Each plate is meshed on a structured grid whose
  lines pass through every bolt, weld line and edge of the plates it meets, so that the
  plates' nodes match where they are joined (a mapped quad mesh: the meshes must conform at
  the components, which an unstructured mesh would not give without interpolation links).
- **Bolts**: a two-node link per bolt between the plates' mid-planes: tension only along the
  bolt, elastic in shear, with the pack's stiffness (``componentTable``: k10 = 1.6 As/Lb and
  k11 = 16 dÂ² fub / (E dM16), the EN 1993-1-8 Table 6.11 form; ``elasticShank``: E As/Lb and
  E Ab/d). Bolts pass through the plates without holes (the contact-free simplification).
- **Contact**: compression-only links between the plates' coinciding nodes where they bear on
  each other (an end plate on the support), so that the plates can open but not overlap.
- **Welds**: stiff elastic links along the weld line between the edge of the welded plate and
  the plate it is welded to; their forces give the weld force per length.

The joint is loaded at the end of a short stub of the connected member by the member's design
end forces (shear V, axial N, moment M at the face of the joint: the stub's own lever arm is
taken off), in ``loadSteps`` steps. It is checked by:

- the plates' plastic strain (the equivalent plastic strain from the layer strains less their
  elastic part) at most ``plasticStrainLimit`` (5 %: EN 1993-1-5 Annex C Sec C.8 Note 1);
- the bolts' tension, shear and their interaction, and bearing, by the pack's own connection
  rules (:mod:`saengine.design.steel_connections`: bolt_tension_capacity, bolt_shear_capacity,
  bearing_capacity);
- the welds' force per length against the pack's fillet weld strength (fillet_capacity_per_mm,
  Î¸ = 0: the conservative direction);
- the joint's initial rotational stiffness Sj,ini (a small moment on the elastic joint, the
  stub's own flexibility taken off), classified rigid, semi-rigid or pinned by Sj,ini Lb /
  (E Ib) against the pack's bounds (``classification``: EN 1993-1-8 5.2.2.5 or the AISC 360
  Commentary B3.4 form).

Joints built: the shear end plate (``endPlate``) and the fin plate (``finPlate``) of
:mod:`saengine.library.objects`. The supporting member is taken as a plate (the support's
flange of ``supportThickness``) held along its web line (end plate) or as rigid (fin plate).

Not modelled: bolt holes and preloading, friction, plate buckling (the shells are
geometrically linear: a separate buckling analysis), and the supporting member's own
deformation beyond its flange. Units inside: N, m; inputs and results in mm, kN, kNÂ·m.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

MM = 1e-3
#: Layers through a plate's thickness.
LAYERS = 5
#: Weld links' stiffness = this Ã— E Ã— tributary length [N/m]; rotations Ã— tÂ².
WELD_STIFFNESS = 10.0
#: The stub of the connected member [Ã— the plate height, at least].
STUB = 1.5
#: The joint's zone of the stub [Ã— the plate height, from the joint]: plastic and checked;
#: beyond it the stub is elastic and not checked. The stub is the beam's web alone (no
#: flanges), and the moment that keeps the face's moment at the design M grows along it
#: (V Ã— the stub at its far end): the member's own bending, checked by the member design.
JOINT_ZONE = 0.5
#: Moment of the stiffness run [NÂ·m].
TEST_MOMENT = 1000.0
#: dM16 of the bolt shear stiffness [m] (EN 1993-1-8 Table 6.11).
D_M16 = 0.016
#: Step cuts before the load is taken as the joint's resistance.
CUTS = 5
#: The stiffness of a bolt in compression and of a contact link in tension (gap open), as a
#: share of its stiffness: not zero, so a link switching state never leaves a zero tangent
#: (the Newton iterations then ran away; the same slack stiffness as the cables').
SLACK = 1e-6


class ConnectionFeError(ValueError):
    """The joint cannot be modelled (a connection kind not built, missing forces)."""


def table() -> Any:
    """The pack's ``connectionFe`` table (the default pack's when it has none)."""
    try:
        from saengine.codes import context as code_context

        return code_context.pack_table("connectionFe")
    except Exception:  # noqa: BLE001 - no pack machinery (a bare calculation)
        from saengine.codes.tables import builtin_table

        return builtin_table("connectionFe")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ geometry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@dataclass
class Plate:
    """A rectangular plate: corner ``origin``, unit axes ``u`` and ``v`` in its mid-plane, its
    sides ``a`` (along u) and ``b`` (along v), thickness ``t`` [m], yield ``fy`` and modulus
    ``E`` [Pa], ``nu``; ``us`` and ``vs`` are the grid lines (from the corner, [m])."""

    name: str
    origin: np.ndarray
    u: np.ndarray
    v: np.ndarray
    a: float
    b: float
    t: float
    fy: float
    E: float
    nu: float = 0.3
    us: list[float] = field(default_factory=list)
    vs: list[float] = field(default_factory=list)
    nodes: dict[tuple[int, int], int] = field(default_factory=dict)
    elements: list[int] = field(default_factory=list)
    #: Shells whose centre lies beyond this ``u`` [m] are elastic and not checked (None: all
    #: plastic and checked).
    elastic_beyond: float | None = None
    elastic: set[int] = field(default_factory=set)

    def point(self, s: float, r: float) -> np.ndarray:
        return self.origin + s * self.u + r * self.v

    @property
    def normal(self) -> np.ndarray:
        return np.cross(self.u, self.v)


def grid(length: float, required: list[float], size: float) -> list[float]:
    """Grid lines over ``length``: 0, the ``required`` ones inside it and ``length``, each gap
    cut into pieces of at most ``size``."""
    fixed = sorted({0.0, length, *(round(x, 9) for x in required if -1e-9 <= x <= length + 1e-9)})
    fixed = [min(max(x, 0.0), length) for x in fixed]
    lines = [fixed[0]]
    for a, b in itertools.pairwise(fixed):
        if b - a <= 1e-9:
            continue
        n = max(1, math.ceil((b - a) / size - 1e-9))
        lines += [a + (b - a) * k / n for k in range(1, n + 1)]
    return lines


def mesh_size(t: Any, plates: list[tuple[float, float]]) -> float:
    """The mesh size [m]: the pack's ``elementSize``, smaller where a plate's shorter side
    needs ``elementsAcross`` elements."""
    across = min(min(a, b) for a, b in plates) / t.elementsAcross
    return min(t.elementSize * MM, across)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ the model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@dataclass
class JointModel:
    """A joint built in OpenSees: its plates, bolts (link tag, plate, support plate node,
    position), welds (link tag, tributary length [m], weld leg [mm], electrode), the loaded
    node and what it was built from."""

    plates: list[Plate]
    bolts: list[dict[str, Any]] = field(default_factory=list)
    welds: list[dict[str, Any]] = field(default_factory=list)
    master: int = 0
    stub: float = 0.0
    stub_inertia: float = 0.0
    tags: dict[str, int] = field(
        default_factory=lambda: {"node": 1, "element": 1, "material": 1, "section": 1}
    )
    notes: list[str] = field(default_factory=list)


def _next(model: JointModel, kind: str) -> int:
    tag = model.tags[kind]
    model.tags[kind] += 1
    return tag


def _emit_plate(ops: Any, model: JointModel, plate: Plate, t: Any) -> None:
    """Nodes and shells of ``plate`` on its grid, with its layered J2 section."""
    e = plate.E
    fy = plate.fy * float(t.yieldFactor)
    r = float(t.hardeningRatio)
    h = e * r / (1 - r) if r > 0 else 0.0
    # J2 in plane stress by its own return map (J2PlateFibre): the 3D J2Plasticity wrapped
    # in PlateFiber iterates for σzz = 0 and ran away once the first layers yielded (the end
    # plate stopped at 20 % of its load with no plastic strain reported).
    fibre = _next(model, "material")
    ops.nDMaterial("J2PlateFibre", fibre, e, plate.nu, fy, h, 0.0)
    section = _next(model, "section")
    layers: list[Any] = []
    for _ in range(LAYERS):
        layers += [fibre, plate.t / LAYERS]
    ops.section("LayeredShell", section, LAYERS, *layers)
    for i, s in enumerate(plate.us):
        for j, rr in enumerate(plate.vs):
            tag = _next(model, "node")
            ops.node(tag, *(float(c) for c in plate.point(s, rr)))
            plate.nodes[(i, j)] = tag
    elastic_section = section
    if plate.elastic_beyond is not None:
        elastic_fibre = _next(model, "material")
        ops.nDMaterial("ElasticIsotropic", elastic_fibre, e, plate.nu)
        plate_fibre = _next(model, "material")
        ops.nDMaterial("PlateFiber", plate_fibre, elastic_fibre)
        elastic_section = _next(model, "section")
        ops.section(
            "LayeredShell",
            elastic_section,
            LAYERS,
            *itertools.chain.from_iterable([plate_fibre, plate.t / LAYERS] for _ in range(LAYERS)),
        )
    for i in range(len(plate.us) - 1):
        elastic = (
            plate.elastic_beyond is not None
            and (plate.us[i] + plate.us[i + 1]) / 2 > plate.elastic_beyond
        )
        for j in range(len(plate.vs) - 1):
            tag = _next(model, "element")
            n = plate.nodes
            ops.element(
                "ShellMITC4",
                tag,
                n[(i, j)],
                n[(i + 1, j)],
                n[(i + 1, j + 1)],
                n[(i, j + 1)],
                elastic_section if elastic else section,
            )
            plate.elements.append(tag)
            if elastic:
                plate.elastic.add(tag)


def _index(lines: list[float], value: float) -> int:
    k = int(np.argmin([abs(x - value) for x in lines]))
    if abs(lines[k] - value) > 1e-6:
        raise ConnectionFeError(
            "a component does not fall on a grid line (the meshes do not conform)"
        )
    return k


def _elastic(ops: Any, model: JointModel, stiffness: float, tension_only: bool = False) -> int:
    tag = _next(model, "material")
    if tension_only:
        ops.uniaxialMaterial("Elastic", tag, float(stiffness), 0.0, SLACK * float(stiffness))
    else:
        ops.uniaxialMaterial("Elastic", tag, float(stiffness))
    return tag


def _link(ops: Any, model: JointModel, i: int, j: int, mats: list[int], y: np.ndarray) -> int:
    """A two-node link from node i to node j (local x along i -> j, local y ``y``)."""
    tag = _next(model, "element")
    dirs = list(range(1, len(mats) + 1))
    ops.element(
        "twoNodeLink", tag, i, j, "-mat", *mats, "-dir", *dirs, "-orient", *(float(c) for c in y)
    )
    return tag


def _weld(
    ops: Any,
    model: JointModel,
    i: int,
    j: int,
    length: float,
    t: float,
    leg: float,
    electrode: float,
    along: np.ndarray,
) -> None:
    """A weld link (zero length, six stiff springs) of tributary ``length`` [m]."""
    k = WELD_STIFFNESS * 200e9 * length
    mats = [_elastic(ops, model, k) for _ in range(3)] + [
        _elastic(ops, model, k * t * t) for _ in range(3)
    ]
    tag = _next(model, "element")
    ops.element("zeroLength", tag, i, j, "-mat", *mats, "-dir", 1, 2, 3, 4, 5, 6)
    model.welds.append(
        {"tag": tag, "length": length, "leg": leg, "electrode": electrode, "along": along}
    )


def bolt_stiffness(
    t: Any, d: float, grade_fub: float, grip: float, e: float
) -> tuple[float, float]:
    """(tension, shear) stiffness of one bolt [N/m] by the pack's ``boltStiffness`` (module
    notes): ``d`` [m], fub [Pa], ``grip`` the plies' thickness [m]."""
    area = math.pi * d * d / 4
    stress_area = 0.78 * area  # the threaded part's tensile stress area
    lb = grip + 0.72 * d  # half the head and the nut
    if t.boltStiffness == "componentTable":
        return e * 1.6 * stress_area / lb, 16 * d * d * grade_fub / D_M16
    return e * stress_area / lb, e * area / d


def _fub(grade: str) -> float:
    """fub [MPa] of a bolt grade: the pack's (partial-factor packs), else Fnt / 0.75."""
    from saengine.design import steel_connections as sc
    from saengine.design.steel import joint_resistances as jr

    if jr.active():
        try:
            return float(jr.bolt(grade).fub)
        except Exception:  # noqa: BLE001, S110 - the bolt is not in the pack's list
            pass
    return sc.bolt_grade(grade)["Fnt"] / 0.75


def end_plate_model(
    ops: Any, c: Any, beam: Any, plate_fy: float, plate_e: float, beam_fy: float, t: Any
) -> JointModel:
    """The shear end plate (:class:`saengine.library.objects.EndPlateConnection`) on a
    support flange: the end plate in the plane x = 0, the support's flange behind it (held
    along its web line, z axis), the beam's web stub along +x, welded to the plate on both
    sides, bolts in two lines at Â± gauge / 2."""
    tp, ts = c.plateThickness * MM, (c.supportThickness or c.plateThickness) * MM
    d = c.boltDiameter * MM
    hp = (2 * c.endDistance + (c.rows - 1) * c.pitch) * MM
    width = (c.gauge + 2 * c.edgeDistance) * MM
    tw = beam.tw * MM
    stub = max(STUB * hp, 3 * width)
    rows_z = [c.endDistance * MM + k * c.pitch * MM for k in range(c.rows)]
    bolt_y = [width / 2 - c.gauge * MM / 2, width / 2 + c.gauge * MM / 2]
    size = mesh_size(t, [(width, hp), (stub, hp)])
    zs = grid(hp, rows_z + [hp / 2], size)
    ys = grid(width, bolt_y + [width / 2], size)
    margin = max(50 * MM, c.edgeDistance * MM)
    ys_support = grid(width + 2 * margin, [margin + y for y in ys], size)
    zs_support = grid(hp + 2 * margin, [margin + z for z in zs], size)
    x_axis, y_axis, z_axis = np.eye(3)
    end_plate = Plate(
        "end plate",
        np.array([0.0, -width / 2, -hp / 2]),
        y_axis,
        z_axis,
        width,
        hp,
        tp,
        plate_fy,
        plate_e,
        us=ys,
        vs=zs,
    )
    support = Plate(
        "support",
        np.array([-(tp + ts) / 2, -width / 2 - margin, -hp / 2 - margin]),
        y_axis,
        z_axis,
        width + 2 * margin,
        hp + 2 * margin,
        ts,
        plate_fy,
        plate_e,
        us=ys_support,
        vs=zs_support,
    )
    zone = JOINT_ZONE * hp
    xs = grid(stub, [zone], size)
    web = Plate(
        "beam web",
        np.array([0.0, 0.0, -hp / 2]),
        x_axis,
        z_axis,
        stub,
        hp,
        tw,
        beam_fy,
        plate_e,
        us=xs,
        vs=zs,
        elastic_beyond=zone,
    )
    model = JointModel([end_plate, support, web], stub=stub, stub_inertia=tw * hp**3 / 12)
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    for p in model.plates:
        _emit_plate(ops, model, p, t)
    # The support is held along its web line (y = 0), all six DOFs.
    j0 = _index(ys_support, margin + width / 2)
    for (i, j), node in support.nodes.items():
        if i == j0:
            ops.fix(node, 1, 1, 1, 1, 1, 1)
    # Welds: the web's edge at x = 0 to the end plate's line y = 0.
    i_mid = _index(ys, width / 2)
    for j, z in enumerate(zs):
        trib = ((zs[min(j + 1, len(zs) - 1)] - zs[max(j - 1, 0)]) / 2) or (zs[1] - zs[0]) / 2
        _weld(
            ops,
            model,
            end_plate.nodes[(i_mid, j)],
            web.nodes[(0, j)],
            trib,
            min(tp, tw),
            c.weldSize,
            c.electrode,
            z_axis,
        )
    # Bolts and contact between the end plate and the support (matching grid lines).
    fub = _fub(c.boltGrade) * 1e6
    k_t, k_s = bolt_stiffness(t, d, fub, tp + ts, plate_e)
    bolt_nodes = set()
    for y in bolt_y:
        for z in rows_z:
            i, j = _index(ys, y), _index(zs, z)
            si, sj = _index(ys_support, margin + y), _index(zs_support, margin + z)
            mats = [
                _elastic(ops, model, k_t, tension_only=True),
                _elastic(ops, model, k_s),
                _elastic(ops, model, k_s),
            ]
            tag = _link(ops, model, support.nodes[(si, sj)], end_plate.nodes[(i, j)], mats, y_axis)
            model.bolts.append({"tag": tag, "y": y - width / 2, "z": z - hp / 2})
            bolt_nodes.add((i, j))
    for (i, j), node in end_plate.nodes.items():
        if (i, j) in bolt_nodes:
            continue
        si, sj = _index(ys_support, margin + ys[i]), _index(zs_support, margin + zs[j])
        area = _tributary(ys, i) * _tributary(zs, j)
        k_c = plate_e * area / ((tp + ts) / 2)
        tag = _next(model, "material")
        # compression-only: Elastic E (tension) eta Eneg (compression)
        ops.uniaxialMaterial("Elastic", tag, SLACK * float(k_c), 0.0, float(k_c))
        _link(ops, model, support.nodes[(si, sj)], node, [tag], y_axis)
    _load_point(ops, model, web, stub)
    return model


def fin_plate_model(
    ops: Any, c: Any, beam: Any, plate_fy: float, plate_e: float, beam_fy: float, t: Any
) -> JointModel:
    """The fin plate (:class:`saengine.library.objects.FinPlateConnection`): the fin in the
    plane y = 0 welded along x = 0 to a rigid support, the beam's web beside it at
    y = (tp + tw) / 2 from the bolt line's end distance on, one line of bolts at x = a."""
    tp, tw = c.plateThickness * MM, beam.tw * MM
    d = c.boltDiameter * MM
    hp = (2 * c.endDistance + (c.rows - 1) * c.pitch) * MM
    a = c.boltLineOffset * MM
    fin_length = a + c.edgeDistance * MM
    gap = max(a - c.edgeDistance * MM, 0.0)
    stub = max(STUB * hp, 3 * fin_length)
    rows_z = [c.endDistance * MM + k * c.pitch * MM for k in range(c.rows)]
    size = mesh_size(t, [(fin_length, hp), (stub, hp)])
    zs = grid(hp, rows_z + [hp / 2], size)
    xs_fin = grid(fin_length, [a, gap], size)
    zone = max(JOINT_ZONE * hp, a - gap + 2 * c.edgeDistance * MM)
    xs_web = grid(stub, [a - gap, zone], size)
    x_axis, _y_axis, z_axis = np.eye(3)
    fin = Plate(
        "fin plate",
        np.array([0.0, 0.0, -hp / 2]),
        x_axis,
        z_axis,
        fin_length,
        hp,
        tp,
        plate_fy,
        plate_e,
        us=xs_fin,
        vs=zs,
    )
    web = Plate(
        "beam web",
        np.array([gap, (tp + tw) / 2, -hp / 2]),
        x_axis,
        z_axis,
        stub,
        hp,
        tw,
        beam_fy,
        plate_e,
        us=xs_web,
        vs=zs,
        elastic_beyond=zone,
    )
    # The lever arm of the load is from the support face (x = 0).
    model = JointModel([fin, web], stub=gap + stub, stub_inertia=tw * hp**3 / 12)
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    for p in model.plates:
        _emit_plate(ops, model, p, t)
    # Welds to the rigid support: fixed nodes behind the fin's edge x = 0.
    for j, z in enumerate(zs):
        anchor = _next(model, "node")
        ops.node(anchor, *(float(v) for v in fin.point(0.0, z)))
        ops.fix(anchor, 1, 1, 1, 1, 1, 1)
        trib = ((zs[min(j + 1, len(zs) - 1)] - zs[max(j - 1, 0)]) / 2) or (zs[1] - zs[0]) / 2
        _weld(ops, model, anchor, fin.nodes[(0, j)], trib, tp, c.weldSize, c.electrode, z_axis)
    fub = _fub(c.boltGrade) * 1e6
    k_t, k_s = bolt_stiffness(t, d, fub, tp + tw, plate_e)
    i_fin, i_web = _index(xs_fin, a), _index(xs_web, a - gap)
    for z in rows_z:
        j = _index(zs, z)
        mats = [
            _elastic(ops, model, k_t, tension_only=True),
            _elastic(ops, model, k_s),
            _elastic(ops, model, k_s),
        ]
        tag = _link(ops, model, fin.nodes[(i_fin, j)], web.nodes[(i_web, j)], mats, x_axis)
        model.bolts.append({"tag": tag, "y": 0.0, "z": z - hp / 2})
    _load_point(ops, model, web, stub)
    return model


def _tributary(lines: list[float], k: int) -> float:
    lo = lines[max(k - 1, 0)]
    hi = lines[min(k + 1, len(lines) - 1)]
    return (hi - lo) / 2


def _load_point(ops: Any, model: JointModel, web: Plate, stub: float) -> None:
    """The loaded node at the middle of the stub's far edge, tied rigidly to that edge."""
    master = _next(model, "node")
    ops.node(master, *(float(v) for v in web.point(stub, web.b / 2)))
    last = len(web.us) - 1
    for j in range(len(web.vs)):
        ops.rigidLink("beam", master, web.nodes[(last, j)])
    model.master = master


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ analysis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _analysis(ops: Any) -> None:
    ops.wipeAnalysis()
    ops.constraints("Transformation")
    ops.numberer("RCM")
    ops.system("UmfPack")
    ops.test("NormDispIncr", 1e-9, 100)
    ops.algorithm("Newton")


def _apply(ops: Any, model: JointModel, v: float, n: float, m: float) -> None:
    """The design forces at the joint's face as loads on the stub's end: N along +x (tension),
    V down, and the moment so that the face carries M (top in tension positive)."""
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(model.master, float(n), 0.0, float(-v), 0.0, float(m - v * model.stub), 0.0)


def _run(ops: Any, steps: int) -> float:
    """Load to the full forces in ``steps`` steps with cuts; the share reached."""
    _analysis(ops)
    share, dl, cuts = 0.0, 1.0 / steps, 0
    while share < 1.0 - 1e-9:
        step = min(dl, 1.0 - share)
        ops.integrator("LoadControl", step)
        ops.analysis("Static")
        if ops.analyze(1) == 0:
            share += step
            cuts = 0
        else:
            cuts += 1
            dl /= 2
            if cuts > CUTS:
                break
    return share


def _layer(ops: Any, element: int, point: int, layer: int, what: str) -> list[float]:
    try:
        found = ops.eleResponse(element, "material", str(point), "fiber", str(layer), what)
    except Exception:  # noqa: BLE001 - a response this build does not give
        return []
    return [float(v) for v in found or []]


def plastic_strain(stress: list[float], strain: list[float], e: float, nu: float) -> float:
    """The equivalent plastic strain of a plate fibre from its stresses (Ïƒ11, Ïƒ22, Ï„12, Ï„23,
    Ï„31) and strains (Îµ11, Îµ22, Î³12, Î³23, Î³31): the plastic part Îµ - Câ»Â¹Ïƒ, incompressible,
    Îµp,eq = (2/âˆš3) âˆš(Îµp11Â² + Îµp22Â² + Îµp11 Îµp22 + Îµp12Â² + Îµp23Â² + Îµp31Â²)."""
    s11, s22, s12, s23, s31 = (stress + [0.0] * 5)[:5]
    e11, e22, g12, g23, g31 = (strain + [0.0] * 5)[:5]
    g = e / (2 * (1 + nu))
    p11 = e11 - (s11 - nu * s22) / e
    p22 = e22 - (s22 - nu * s11) / e
    p12 = (g12 - s12 / g) / 2
    p23 = (g23 - s23 / g) / 2
    p31 = (g31 - s31 / g) / 2
    value = p11 * p11 + p22 * p22 + p11 * p22 + p12 * p12 + p23 * p23 + p31 * p31
    return max(2 / math.sqrt(3) * math.sqrt(max(value, 0.0)), 0.0)


def _plate_strains(ops: Any, plate: Plate, t: Any) -> dict[int, float]:
    """The largest equivalent plastic strain of each shell of ``plate`` (its four Gauss points
    and layers); from the stress resultants when the layers cannot be read."""
    out: dict[int, float] = {}
    fy = plate.fy * float(t.yieldFactor)
    r = max(float(t.hardeningRatio), 1e-6)
    for element in plate.elements:
        if element in plate.elastic:
            continue
        worst = 0.0
        read = False
        for point in range(1, 5):
            for layer in range(1, LAYERS + 1):
                stress = _layer(ops, element, point, layer, "stresses")
                strain = _layer(ops, element, point, layer, "strains")
                if stress and strain:
                    read = True
                    worst = max(worst, plastic_strain(stress, strain, plate.E, plate.nu))
        if not read:  # the resultants: the surfaces' von Mises stress beyond yield
            values = list(ops.eleResponse(element, "stresses") or [])
            for k in range(0, len(values) - 7, 8):
                n11, n22, n12, m11, m22, m12 = values[k : k + 6]
                for sign in (1, -1):
                    s11 = n11 / plate.t + sign * 6 * m11 / plate.t**2
                    s22 = n22 / plate.t + sign * 6 * m22 / plate.t**2
                    s12 = n12 / plate.t + sign * 6 * m12 / plate.t**2
                    vm = math.sqrt(s11 * s11 + s22 * s22 - s11 * s22 + 3 * s12 * s12)
                    worst = max(worst, (vm - fy) / (r * plate.E) if vm > fy else 0.0)
        out[element] = worst
    return out


def _basic(ops: Any, tag: int) -> list[float]:
    for key in ("basicForce", "basicForces", "localForce"):
        try:
            found = ops.eleResponse(tag, key)
        except Exception:  # noqa: BLE001, S112
            continue
        if found:
            return [float(v) for v in found]
    return [0.0, 0.0, 0.0]


def stiffness_run(ops: Any, build: Any, e: float) -> float | None:
    """Sj,ini [NÂ·m/rad]: a small moment on the elastic joint, the stub's rotation less its own
    flexibility M L / (E I)."""
    model = build()
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(model.master, 0.0, 0.0, 0.0, 0.0, TEST_MOMENT, 0.0)
    _analysis(ops)
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    if ops.analyze(1) != 0:
        ops.wipe()
        return None
    rotation = float(ops.nodeDisp(model.master, 5))
    ops.wipe()
    joint = rotation - TEST_MOMENT * model.stub / (e * model.stub_inertia)
    return TEST_MOMENT / joint if joint > 0 else None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ the check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _check(
    name: str, demand: float, capacity: float, unit: str, note: str, combination: str | None
) -> dict[str, Any]:
    u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else 99.0)
    return {
        "name": name,
        "demand": round(float(demand), 3),
        "capacity": round(float(capacity), 3),
        "unit": unit,
        "utilisation": round(float(min(u, 99.0)), 3),
        "combination": combination,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": False,
    }


def classify(
    sj: float | None, e: float, ib: float, lb: float, braced: bool, t: Any
) -> dict[str, Any]:
    """Rigid / semi-rigid / pinned by Sj,ini Lb / (E Ib) against the pack's bounds."""
    c = t.classification
    if sj is None or ib <= 0 or lb <= 0:
        return {"class": None, "ratio": None}
    ratio = sj * lb / (e * ib)
    rigid = c.rigidBraced if braced else c.rigidUnbraced
    kind = "rigid" if ratio >= rigid else "pinned" if ratio <= c.pinned else "semiRigid"
    return {"class": kind, "ratio": ratio, "pinned": c.pinned, "rigid": rigid}


def check_joint(
    connection: Any,
    beam: Any,
    beam_material: Any,
    plate_material: Any | None,
    forces: dict[str, float],
    span: float | None = None,
    braced: bool = True,
    t: Any = None,
    ops: Any = None,
) -> dict[str, Any]:
    """The CBFEM check of ``connection`` (an end plate or fin plate of 04 Objects) on the
    ``beam`` section (:class:`saengine.library.steel_sections.SteelSection`) of
    ``beam_material`` (:class:`saengine.design.steel_proposal.SteelMaterial`) for the design
    ``forces`` ``{"V", "N", "M" [kN, kNÂ·m], "combination"}``; ``span`` [m] the beam's length
    for the stiffness classification. Returns ``{"connection", "checks", "utilisation", "ok",
    "plasticStrain", "loadShare", "stiffness", "classification", "mesh", "assumptions"}``."""
    from saengine.design import steel_connections as sc
    from saengine.design.steel import joint_resistances as jr

    t = t or table()
    if ops is None:
        from openseespy import opensees as ops
    builders = {"endPlate": end_plate_model, "finPlate": fin_plate_model}
    kind = getattr(connection, "type", None)
    if kind not in builders:
        raise ConnectionFeError(
            f"the FE check is built for end plates and fin plates, not '{kind}'"
        )
    plate = plate_material or beam_material
    e = beam_material.E * 1e6

    def build() -> JointModel:
        return builders[kind](ops, connection, beam, plate.fy * 1e6, e, beam_material.fy * 1e6, t)

    v = abs(float(forces.get("V", 0.0))) * 1e3
    n = float(forces.get("N", 0.0)) * 1e3
    m = float(forces.get("M", 0.0)) * 1e3
    combination = forces.get("combination")
    sj = stiffness_run(ops, build, e)
    model = build()
    _apply(ops, model, v, n, m)
    share = _run(ops, int(t.loadSteps))
    strains: dict[str, dict[int, float]] = {p.name: _plate_strains(ops, p, t) for p in model.plates}
    bolts = [(b, _basic(ops, b["tag"])) for b in model.bolts]
    welds = [(w, [float(f) for f in ops.eleForce(w["tag"])[:3]]) for w in model.welds]
    mesh = {
        p.name: {
            "nodes": {int(tag): [float(c) for c in ops.nodeCoord(tag)] for tag in p.nodes.values()},
            "shells": {int(el): [int(x) for x in ops.eleNodes(el)] for el in p.elements},
            "plasticStrain": {int(el): float(s) for el, s in strains[p.name].items()},
        }
        for p in model.plates
    }
    ops.wipe()

    checks: list[dict[str, Any]] = []
    limit = float(t.plasticStrainLimit)
    clauses = dict(getattr(t, "clauses", {}) or {})
    for p in model.plates:
        worst = max(strains[p.name].values(), default=0.0)
        checks.append(
            _check(
                f"plastic strain, {p.name}",
                100 * worst,
                100 * limit,
                "%",
                f"{clauses.get('strain', '')}: Îµp,max at most {100 * limit:g} %".strip(": "),
                combination,
            )
        )
    if share < 1.0 - 1e-9:
        checks.append(
            _check(
                "the joint carries the design forces",
                1.0,
                share,
                "-",
                f"the analysis stopped converging at {100 * share:.0f} % of the forces",
                combination,
            )
        )
    d = connection.boltDiameter
    ab = math.pi * d * d / 4
    dh = sc.hole_diameter(d)
    lc = min(connection.endDistance - dh / 2, connection.pitch - dh)
    fus = [f for f in (getattr(plate, "fu", None), getattr(beam_material, "fu", None)) if f]
    with jr.parent(min(fus) if fus else None), jr.bolts_of(connection.boltGrade):
        shear_cap = sc.bolt_shear_capacity(connection.boltGrade, d, 1)
        thinner = min(connection.plateThickness, beam.tw)
        bearing_cap = sc.bearing_capacity(d, thinner, min(fus) if fus else plate.fu, lc)
        weld_cap = sc.fillet_capacity_per_mm(connection.weldSize, connection.electrode)
        worst_bolt = None
        for b, (axial, s2, s3) in ((b, (f + [0.0, 0.0, 0.0])[:3]) for b, f in bolts):
            shear = math.hypot(s2, s3)
            tension = max(axial, 0.0)
            tension_cap, note = sc.bolt_tension_capacity(connection.boltGrade, d, shear / ab)
            u = max(
                tension / tension_cap if tension_cap else 0.0,
                shear / shear_cap,
                shear / bearing_cap,
            )
            if worst_bolt is None or u > worst_bolt[0]:
                worst_bolt = (u, b, tension, tension_cap, shear, note)
        if worst_bolt is not None:
            _, b, tension, tension_cap, shear, note = worst_bolt
            where = f"bolt at y {1e3 * b['y']:.0f}, z {1e3 * b['z']:.0f} mm"
            checks.append(
                _check(
                    f"bolt tension ({where})",
                    tension / 1e3,
                    tension_cap / 1e3,
                    "kN",
                    f"{clauses.get('bolts', '')}; {note}".strip("; "),
                    combination,
                )
            )
            checks.append(
                _check(
                    f"bolt shear ({where})",
                    shear / 1e3,
                    shear_cap / 1e3,
                    "kN",
                    clauses.get("bolts", ""),
                    combination,
                )
            )
            checks.append(
                _check(
                    f"bolt bearing ({where})",
                    shear / 1e3,
                    bearing_cap / 1e3,
                    "kN",
                    f"on the thinner ply, {thinner:g} mm",
                    combination,
                )
            )
        worst_weld = 0.0
        for w, f in welds:
            per_mm = math.sqrt(sum(x * x for x in f)) / (w["length"] * 1e3)
            worst_weld = max(worst_weld, per_mm)
        sides = 2  # fillets on both sides of the web or the fin
        checks.append(
            _check(
                "weld force per length",
                worst_weld,
                sides * weld_cap,
                "N/mm",
                f"{clauses.get('welds', '')}: two fillets of {connection.weldSize:g} mm, Î¸ = 0".strip(
                    ": "
                ),
                combination,
            )
        )
    ib = getattr(beam, "Ix", 0.0) * 1e-12
    classification = classify(sj, e, ib, span or 0.0, braced, t)
    strength = [c for c in checks if not c["flag"]]
    peak = max((max(s.values(), default=0.0) for s in strains.values()), default=0.0)
    return {
        "connection": kind,
        "method": "CBFEM",
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "plasticStrain": peak,
        "plasticStrainLimit": limit,
        "loadShare": share,
        "forces": {"V": v / 1e3, "N": n / 1e3, "M": m / 1e3, "combination": combination},
        "stiffness": None if sj is None else sj / 1e3,
        "classification": classification,
        "mesh": mesh,
        "clauses": clauses,
        "source": t.source,
        "assumptions": [
            "plates as layered shells, von Mises plasticity with linear hardening at the pack's design yield",
            "bolts as tension-only links with shear springs, no holes or preload; contact as compression-only links",
            "welds as stiff elastic links along the weld line",
            "the supporting member as a plate held along its web line (end plate) or rigid (fin plate)",
            "geometrically linear plates (no plate buckling)",
            *([t.note] if t.note else []),
        ],
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ a member's joint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

#: The cached checks beside the run's results, by member.
RESULT_FILE = "connection-fe.json"


def member_forces_at_ends(out_dir: Any, project_path: Any, member: str) -> dict[str, Any]:
    """The design forces of the member's governing end: the combination and end with the
    largest shear (with its axial force and moment), in kN and kNÂ·m; and the member's
    length [m]."""
    from saengine.fem.member_detail import member_forces

    found = member_forces(out_dir, project_path, member)
    best: dict[str, Any] | None = None
    for row in found.get("results", []):
        if row.get("kind") != "combination" or not row.get("forces"):
            continue
        for k in (0, -1):
            n, vy, vz, _, _, mz = row["forces"][k]
            v = math.hypot(vy, vz)
            if best is None or v / 1e3 > best["V"]:
                best = {"V": v / 1e3, "N": n / 1e3, "M": abs(mz) / 1e3, "combination": row["label"]}
    if best is None:
        raise ConnectionFeError(f"{member} has no load combination results; run the analysis first")
    best["length"] = float(found.get("length") or 0.0)
    return best


def check_member_joint(
    out_dir: Any, project_path: Any, member: str, braced: bool = True
) -> dict[str, Any]:
    """The FE check of the end connection of ``member`` (its object type's ``connection``)
    for its design end forces, with the code pack of the project; kept beside the results
    (:data:`RESULT_FILE`) for the report."""
    import json
    from pathlib import Path

    from saengine.codes import context as code_context
    from saengine.design.steel_proposal import SteelMaterial
    from saengine.fem.combinations import settings_beside
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.steel_sections import section_of_profile

    root = Path(project_path).resolve().parent.parent
    bim = json.loads((root / "06 BIM" / "bim.json").read_text(encoding="utf-8"))
    element = next((e for e in bim.get("elements", []) if str(e.get("id")) == member), None)
    if element is None:
        raise ConnectionFeError(f"{member} is not an element of the building")
    types = {
        o.id: o
        for o in ObjectLibrary.model_validate_json(
            (root / "04 Objects" / "objects.json").read_text(encoding="utf-8")
        ).objects
    }
    materials = {
        m.id: m
        for m in MaterialLibrary.model_validate_json(
            (root / "03 Materials" / "materials.json").read_text(encoding="utf-8")
        ).materials
    }
    object_type = types.get(element.get("type"))
    connection = getattr(object_type, "connection", None)
    if connection is None:
        raise ConnectionFeError(f"{member}'s type has no end connection to check")
    beam_material = SteelMaterial.from_material(materials[object_type.material])
    plate_id = getattr(connection, "plateMaterial", None)
    plate_material = (
        SteelMaterial.from_material(materials[plate_id])
        if plate_id and plate_id in materials
        else None
    )
    section = section_of_profile(object_type.profile)
    forces = member_forces_at_ends(out_dir, project_path, member)
    settings = settings_beside(project_path)
    try:
        pack = code_context.pack_for(settings, project_path)
    except Exception:  # noqa: BLE001 - a pack that cannot load: the default's
        pack = None
    with code_context.using(pack):
        result = check_joint(
            connection, section, beam_material, plate_material, forces, forces["length"], braced
        )
        result["code"] = code_context.code_name()
    result["member"] = member
    path = Path(out_dir) / RESULT_FILE
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kept = {}
    kept[member] = {k: v for k, v in result.items() if k != "mesh"}
    try:
        path.write_text(json.dumps(kept), encoding="utf-8")
    except OSError:
        pass
    return result


def load_checks(out_dir: Any) -> dict[str, Any]:
    """The FE checks made on this run's members (member -> check, without the meshes)."""
    import json
    from pathlib import Path

    try:
        return json.loads((Path(out_dir) / RESULT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

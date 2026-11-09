"""Nonlinear buckling of steel frames (GNA, GMNIA) and the large-displacement analysis of cables
(alpha 9 track L4).

The linear buckling factor αcr (:mod:`saengine.fem.buckling`) says when the perfect elastic
frame buckles. This module follows the real frame along its load-displacement path:

1. **The model** (:func:`stability_model`): the frames, trusses and links of the derived
   analysis model with its supports and constraints (walls, slabs and solids are left out, as
   in the linear buckling model, so αcr compares like with like); each frame element is cut
   into ``segments`` pieces so that a member can bow. The combination's loads (its factors on
   the load cases) become nodal loads: the frames' uniform loads lumped at the pieces' ends.
2. **The linear buckling factor and mode** of that model under the first-order axial forces of
   the combination (reused: :func:`saengine.fem.buckling.linear_buckling`).
3. **The imperfection**, by the code pack (``nonlinearStability`` table,
   :mod:`saengine.codes.stability_tables`):
   - ``eigenmode``: the first buckling mode scaled so that the member that bows most in it gets
     the pack's bow amplitude e0 (method ``memberBow``) or its length over a ratio
     (``fixedRatio``); a pure sway mode is scaled to the sway imperfection φ h;
   - ``equivalent``: the sway φ (method ``heightAndColumns``: φ0 αh αm, or ``fixedRatio``) in
     the chosen direction plus a sine bow e0 of every compressed member about its weak axis
     (method ``curveRatio`` by the member's buckling curve, or ``fixedRatio``);
   - ``none``: the perfect frame (its path shows a bifurcation only through round-off).
4. **The nonlinear model**: co-rotational frames and trusses (large displacements and
   rotations); with ``material`` "plastic" the steel members become force-based fibre elements
   (:func:`saengine.fem.nonlinear.fiber_section`, Steel02 with the pack's hardening) at the
   pack's design yield strength and modulus (``yieldFactor``, ``stiffnessFactor``).
   Cables (brace types with a ``cable``, :class:`saengine.library.objects.Cable`) become
   tension-only co-rotational truss chains with their pretension (:mod:`saengine.fem.cables`).
5. **The path** (:func:`trace_path`): the combination's loads times λ, first by load control
   to λ = 1 (the state the cables' sag and tension and the design deflections are read at),
   then on by arc length (``arcLength``, cylindrical, Crisfield) or displacement control of
   the node that moves most (``displacementControl``) until the load factor falls past its
   peak by the pack's share, the displacement exceeds the height over the pack's ratio, or the
   steps run out. The **limit load factor** λu is the peak; the deformed shape is kept there.

The result compares λu with αcr (λu / αcr: the knock-down of the imperfection and plasticity)
and checks λu at least the pack's required factor.

Not in this model: residual stresses (the pack's equivalent imperfections stand for them),
local and distortional buckling of the plates of a member (a fibre section is a beam's), walls
and slabs, and joint flexibility other than the model's links. Units: N, m.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

#: The cached result beside the run's results.
RESULT_FILE = "nonlinear-stability.json"
#: Pieces of each frame element by default.
SEGMENTS = 4
#: Load control steps to λ = 1.
LOAD_STEPS = 10
#: Step cuts before the path stops.
CUTS = 6
#: Axial force [N] below which a member is taken as carrying none.
N_SMALL = 1.0

_FRAMES = ("ElasticBeamColumn",)
_TRUSSES = ("Truss", "CorotTruss")
_KEPT = (*_FRAMES, *_TRUSSES, "ZeroLength")


class StabilityError(ValueError):
    """The nonlinear stability analysis cannot be made (no frames, no loads, unstable)."""


@dataclass
class StabilityOptions:
    """How the analysis is made (the project's ``analysis.nonlinearStability`` settings)."""

    imperfection: Literal["eigenmode", "equivalent", "none"] = "eigenmode"
    material: Literal["elastic", "plastic"] = "plastic"
    direction: Literal["X", "Y"] = "X"
    method: Literal["arcLength", "displacementControl"] | None = None
    steps: int | None = None
    segments: int = SEGMENTS
    curve: str | None = None
    bowRatio: float | None = None
    swayRatio: float | None = None


@dataclass
class StabilityResult:
    """The path ``[(λ, control displacement [m])]``, the limit load factor (the path's peak;
    ``limitReached`` False when the path was still rising when it stopped), αcr, the
    deformed shape at the limit and at λ = 1 (node -> ux, uy, uz [m]), the imperfection, the
    cables' state at λ = 1 and notes."""

    path: list[tuple[float, float]]
    limitFactor: float
    limitReached: bool
    alphaCr: float | None
    control: tuple[int, int]
    deformedAtLimit: dict[int, list[float]]
    deformedAtDesign: dict[int, list[float]] | None
    imperfection: dict[str, Any]
    cables: list[dict[str, Any]] = field(default_factory=list)
    stopped: str = ""
    notes: list[str] = field(default_factory=list)


# ─────────────────────────────────────── pack ───────────────────────────────────────


def table() -> Any:
    """The pack's ``nonlinearStability`` table (the default pack's when it has none)."""
    try:
        from saengine.codes import context as code_context

        return code_context.pack_table("nonlinearStability")
    except Exception:  # noqa: BLE001 - no pack machinery (a bare calculation)
        from saengine.codes.tables import builtin_table

        return builtin_table("nonlinearStability")


def bow_ratio(t: Any, options: StabilityOptions, curve: str | None = None) -> float:
    """L / e0 of a member's bow by the pack (or the project's own ratio)."""
    if options.bowRatio:
        return float(options.bowRatio)
    bow = t.bow
    if bow.method == "fixedRatio":
        return float(bow.fixedRatio)
    key = curve or options.curve or bow.defaultCurve
    ratios = bow.plasticRatios if options.material == "plastic" and bow.plasticRatios else bow.ratios
    return float(ratios.get(key) or ratios[bow.defaultCurve])


def sway_angle(t: Any, options: StabilityOptions, height: float, columns: int) -> float:
    """φ [rad] of the frame's sway imperfection: 1 / ratio, times αh αm for
    ``heightAndColumns`` (αh = 2/√h within [min, 1], αm = √(0.5 (1 + 1/m)))."""
    if options.swayRatio:
        return 1.0 / float(options.swayRatio)
    sway = t.sway
    phi = 1.0 / float(sway.baseRatio)
    if sway.method == "heightAndColumns":
        ah = min(max(2 / math.sqrt(max(height, 1e-6)), sway.heightFactorMin), 1.0)
        am = math.sqrt(0.5 * (1 + 1 / max(columns, 1)))
        phi *= ah * am
    return phi


# ─────────────────────────────────────── the model ───────────────────────────────────────


def _coords(model: dict[str, Any]) -> dict[int, np.ndarray]:
    return {n["id"]: np.asarray(n["coords"], dtype=float) for n in model.get("nodes", [])}


def reference_loads(
    linear: dict[str, Any], factors: dict[str, float]
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """The combination's loads: ``(nodal {node: 6 forces}, uniform {element: w global [N/m]})``,
    each load pattern named by its case code times its factor."""
    from saengine.fem.second_order import _frame_axes

    coords = _coords(linear)
    elements = {e["id"]: e for e in linear.get("elements", [])}
    nodal: dict[int, np.ndarray] = {}
    uniform: dict[int, np.ndarray] = {}
    for pattern in linear.get("load_patterns", []):
        factor = factors.get(pattern.get("name"))
        if not factor:
            continue
        for load in pattern.get("nodal_loads", []):
            total = nodal.setdefault(int(load["node_id"]), np.zeros(6))
            total += factor * np.asarray(load["forces"], dtype=float)[:6]
        for load in pattern.get("element_loads", []):
            element = elements.get(load["element_id"])
            if element is None or element.get("type") not in _FRAMES:
                continue
            a, b = (coords[n] for n in element["nodes"][:2])
            x, y, z = _frame_axes(a, b, element.get("vecxz"))
            w = load.get("wx", 0.0) * x + load.get("wy", 0.0) * y + load.get("wz", 0.0) * z
            total = uniform.setdefault(int(element["id"]), np.zeros(3))
            total += factor * w
    return nodal, uniform


def stability_model(
    linear: dict[str, Any],
    nodal: dict[int, np.ndarray],
    uniform: dict[int, np.ndarray],
    segments: int = SEGMENTS,
    skip: set[str] | None = None,
) -> tuple[dict[str, Any], dict[int, np.ndarray], dict[str, list[int]], list[str]]:
    """The frames' model of the derived analysis model ``linear`` (module notes, step 1):
    ``(model, nodal loads {node: 6}, members {name: element ids in order}, notes)``. Members
    named in ``skip`` (cables) keep their single elements, uncut."""
    from saengine.fem.second_order import _frame_axes

    skip = skip or set()
    notes: list[str] = []
    model = copy.deepcopy(linear)
    coords = _coords(model)
    kept = [e for e in model.get("elements", []) if e.get("type") in _KEPT]
    dropped: dict[str, int] = {}
    for e in model.get("elements", []):
        if e.get("type") not in _KEPT:
            dropped[str(e.get("type"))] = dropped.get(str(e.get("type")), 0) + 1
    if dropped:
        notes.append(
            "not in the stability model (as in the linear buckling model): "
            + ", ".join(f"{n} {kind}" for kind, n in sorted(dropped.items()))
        )
    if not any(e["type"] in _FRAMES or e["type"] in _TRUSSES for e in kept):
        raise StabilityError("the model has no frames or trusses for a stability analysis")
    next_node = max(coords) + 1
    next_element = max(e["id"] for e in model["elements"]) + 1
    new_nodes: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    loads = {n: v.copy() for n, v in nodal.items()}
    members: dict[str, list[int]] = {}
    offsets = 0
    for e in kept:
        name = str(e.get("name") or e["id"])
        member = name.split("#")[0]
        i, j = e["nodes"][:2]
        if e["type"] not in _FRAMES or member in skip or e.get("joint_offsets") or segments <= 1:
            if e["type"] in _FRAMES and e.get("joint_offsets") and segments > 1:
                offsets += 1
            elements.append(e)
            if "/" not in member:
                members.setdefault(member, []).append(e["id"])
            w = uniform.get(e["id"])
            if w is not None:
                length = float(np.linalg.norm(coords[j] - coords[i]))
                for n in (i, j):
                    loads.setdefault(n, np.zeros(6))[:3] += w * length / 2
            continue
        a, b = coords[i], coords[j]
        chain = [i]
        for k in range(1, segments):
            p = a + (b - a) * k / segments
            new_nodes.append({"id": next_node, "coords": [float(v) for v in p]})
            coords[next_node] = p
            chain.append(next_node)
            next_node += 1
        chain.append(j)
        w = uniform.get(e["id"])
        piece = float(np.linalg.norm(b - a)) / segments
        # The pieces keep the element's own local axes (its vecxz, else the runner's choice).
        _, _, z = _frame_axes(a, b, e.get("vecxz"))
        vecxz = e.get("vecxz") or [float(v) for v in z]
        for k, (p, q) in enumerate(zip(chain[:-1], chain[1:], strict=True)):
            tag = e["id"] if k == 0 else next_element
            if k:
                next_element += 1
            elements.append({**e, "id": tag, "nodes": [p, q], "vecxz": vecxz, "name": name})
            if "/" not in member:
                members.setdefault(member, []).append(tag)
            if w is not None:
                for n in (p, q):
                    loads.setdefault(n, np.zeros(6))[:3] += w * piece / 2
    if offsets:
        notes.append(f"{offsets} frame elements with rigid end offsets are not cut into pieces")
    used = {n for e in elements for n in e["nodes"][:2]}
    constraints = []
    for c in model.get("mp_constraints", []):
        c = dict(c)
        if "constrained_nodes" in c:
            c["constrained_nodes"] = [n for n in c["constrained_nodes"] if n in used]
            if not c["constrained_nodes"]:
                continue
        elif int(c.get("constrained_node", 0)) not in used:
            continue
        used.add(int(c["retained_node"]))
        constraints.append(c)
    model["nodes"] = [n for n in model["nodes"] if n["id"] in used] + new_nodes
    model["elements"] = elements
    model["mp_constraints"] = constraints
    for key in ("load_patterns", "analyses", "spectra", "ground_motions", "time_series"):
        if key in model:
            model[key] = []
    loads = {n: v for n, v in loads.items() if n in used and np.any(v)}
    if not loads:
        raise StabilityError("the combination puts no load on the frames")
    return model, loads, members, notes


def _runner(model: dict[str, Any], ops: Any) -> Any:
    """Emit ``model`` into ``ops`` with OpenSees Studio's runner (nodes, supports, constraints,
    materials, sections and elements; no loads)."""
    from opensees_studio.core.project import Project
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    runner = OpenSeesRunner(Project.model_validate(model), ops)
    runner.build()
    return runner


def _analysis(ops: Any, model: dict[str, Any], tolerance: float = 1e-7) -> None:
    ops.wipeAnalysis()
    ops.constraints("Transformation" if model.get("mp_constraints") else "Plain")
    ops.numberer("RCM")
    ops.system("UmfPack")
    ops.test("NormDispIncr", tolerance, 100)
    ops.algorithm("Newton")


def _pattern(ops: Any, loads: dict[int, np.ndarray], ndf: int = 6) -> None:
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    for node, forces in sorted(loads.items()):
        ops.load(int(node), *(float(f) for f in forces[:ndf]))


def first_order(model: dict[str, Any], loads: dict[int, np.ndarray], ops: Any) -> dict[str, Any]:
    """The first-order elastic solution of the elastic stability model: ``{"axial": {element:
    N (tension +)}, "displacements": {node: 6}}``."""
    _runner(model, ops)
    _pattern(ops, loads)
    _analysis(ops, model, 1e-9)
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    if ops.analyze(1) != 0:
        ops.wipe()
        raise StabilityError("the frame model does not stand on its own (no first-order solution)")
    axial: dict[int, float] = {}
    for e in model["elements"]:
        if e["type"] in _FRAMES:
            local = ops.eleResponse(e["id"], "localForce")
            axial[e["id"]] = float((-local[0] + local[6]) / 2)
        elif e["type"] in _TRUSSES:
            value = ops.eleResponse(e["id"], "axialForce")
            axial[e["id"]] = float(value[0]) if value else 0.0
    displacements = {n: np.asarray(ops.nodeDisp(n), dtype=float) for n in ops.getNodeTags()}
    ops.wipe()
    return {"axial": axial, "displacements": displacements}


# ─────────────────────────────────── imperfections ───────────────────────────────────


def member_chains(model: dict[str, Any], members: dict[str, list[int]]) -> dict[str, list[int]]:
    """Each member's nodes in order from one end to the other (its pieces' chain)."""
    elements = {e["id"]: e for e in model["elements"]}
    chains: dict[str, list[int]] = {}
    for name, ids in members.items():
        links: dict[int, list[int]] = {}
        for i in ids:
            a, b = elements[i]["nodes"][:2]
            links.setdefault(a, []).append(b)
            links.setdefault(b, []).append(a)
        ends = [n for n, near in links.items() if len(near) == 1]
        if len(ends) != 2:
            continue  # not a simple chain (a ring or a branch): no bow
        chain, previous = [min(ends)], None
        while len(chain) <= len(links):
            near = [n for n in links[chain[-1]] if n != previous]
            if not near:
                break
            previous = chain[-1]
            chain.append(near[0])
        if len(chain) == len(links):
            chains[name] = chain
    return chains


def _weak_axis(model: dict[str, Any], element: dict[str, Any], coords: dict[int, np.ndarray]) -> np.ndarray:
    """The unit vector along which the member bows: its local y when bending about z is the
    weaker (Iz <= Iy), else its local z; a truss bows along its local y."""
    from saengine.fem.second_order import _frame_axes

    a, b = (coords[n] for n in element["nodes"][:2])
    _, y, z = _frame_axes(a, b, element.get("vecxz"))
    if element["type"] in _TRUSSES:
        return y
    sections = {s["id"]: s for s in model.get("sections", [])}
    s = sections.get(element.get("section_id"), {})
    iz, iy = float(s.get("Iz") or 0.0), float(s.get("Iy") or 0.0)
    return y if iz <= iy or not iy else z


def _bow_offsets(
    model: dict[str, Any], chain: list[int], amplitude: float, direction: np.ndarray
) -> dict[int, np.ndarray]:
    coords = _coords(model)
    a, b = coords[chain[0]], coords[chain[-1]]
    length = float(np.linalg.norm(b - a))
    out = {}
    for n in chain[1:-1]:
        s = float(np.dot(coords[n] - a, b - a)) / length
        out[n] = amplitude * math.sin(math.pi * s / length) * direction
    return out


def equivalent_imperfection(
    model: dict[str, Any],
    members: dict[str, list[int]],
    axial: dict[int, float],
    options: StabilityOptions,
    t: Any,
) -> tuple[dict[int, np.ndarray], dict[str, Any]]:
    """The sway and bow imperfections (module notes, step 3): node offsets [m] and what was
    applied."""
    coords = _coords(model)
    elements = {e["id"]: e for e in model["elements"]}
    zs = [c[2] for c in coords.values()]
    base, top = min(zs), max(zs)
    height = top - base
    chains = member_chains(model, members)
    compressed = {
        name: chain
        for name, chain in chains.items()
        if min(axial.get(i, 0.0) for i in members[name]) < -N_SMALL
    }
    # m: the compressed columns standing at the most crowded level.
    columns: dict[float, int] = {}
    for name, chain in compressed.items():
        a, b = coords[chain[0]], coords[chain[-1]]
        if abs(b[2] - a[2]) > 0.9 * float(np.linalg.norm(b - a)):
            level = round(min(a[2], b[2]), 3)
            columns[level] = columns.get(level, 0) + 1
    m = max(columns.values(), default=1)
    phi = sway_angle(t, options, height, m)
    axis = np.array([1.0, 0.0, 0.0]) if options.direction == "X" else np.array([0.0, 1.0, 0.0])
    offsets = {n: phi * (c[2] - base) * axis for n, c in coords.items()}
    bows = 0
    largest = 0.0
    for name, chain in compressed.items():
        a, b = coords[chain[0]], coords[chain[-1]]
        length = float(np.linalg.norm(b - a))
        e0 = length / bow_ratio(t, options)
        direction = _weak_axis(model, elements[members[name][0]], coords)
        for n, d in _bow_offsets(model, chain, e0, direction).items():
            offsets[n] = offsets.get(n, np.zeros(3)) + d
        bows += 1
        largest = max(largest, e0)
    return offsets, {
        "kind": "equivalent",
        "sway": phi,
        "swayMethod": t.sway.method if not options.swayRatio else "project",
        "columns": m,
        "height": height,
        "direction": options.direction,
        "bows": bows,
        "bowMethod": t.bow.method if not options.bowRatio else "project",
        "largestBow": largest,
    }


def eigenmode_imperfection(
    model: dict[str, Any],
    members: dict[str, list[int]],
    axial: dict[int, float],
    options: StabilityOptions,
    t: Any,
) -> tuple[dict[int, np.ndarray], dict[str, Any], float]:
    """The first buckling mode scaled to the pack's amplitude (module notes, step 3): node
    offsets [m], what was applied, and αcr."""
    from saengine.fem.buckling import BucklingError, linear_buckling

    try:
        found = linear_buckling(model, axial, modes=1)
    except BucklingError as error:
        raise StabilityError(f"no buckling mode for the imperfection: {error}") from error
    if not found.factors:
        raise StabilityError("the frame does not buckle under these loads (no positive αcr)")
    shape = found.modes[0]
    coords = _coords(model)
    chains = member_chains(model, members)
    best, bow, best_length = None, 0.0, 0.0
    for name, chain in chains.items():
        a, b = coords[chain[0]], coords[chain[-1]]
        length = float(np.linalg.norm(b - a))
        ua = shape.get(chain[0], np.zeros(6))[:3]
        ub = shape.get(chain[-1], np.zeros(6))[:3]
        for n in chain[1:-1]:
            s = float(np.dot(coords[n] - a, b - a)) / length**2
            relative = float(np.linalg.norm(shape.get(n, np.zeros(6))[:3] - (ua + s * (ub - ua))))
            if relative > bow:
                best, bow, best_length = name, relative, length
    zs = [c[2] for c in coords.values()]
    height = max(zs) - min(zs)
    if best is not None and bow > 1e-3:
        if t.eigenmode.method == "fixedRatio" and not options.bowRatio:
            amplitude = best_length / float(t.eigenmode.fixedRatio)
        else:
            amplitude = best_length / bow_ratio(t, options)
        scale = amplitude / bow
        governs = f"bow of {best}"
    else:  # a sway mode: the sway imperfection at the top
        amplitude = sway_angle(t, options, height, 1) * height
        scale = amplitude
        governs = "sway"
    offsets = {n: scale * np.asarray(v[:3]) for n, v in shape.items()}
    return (
        offsets,
        {
            "kind": "eigenmode",
            "alphaCr": found.factors[0],
            "amplitude": amplitude,
            "governs": governs,
            "method": t.eigenmode.method,
        },
        float(found.factors[0]),
    )


def imperfect(model: dict[str, Any], offsets: dict[int, np.ndarray]) -> dict[str, Any]:
    """``model`` with its nodes moved by ``offsets`` [m] (supports and all)."""
    out = copy.deepcopy(model)
    for n in out["nodes"]:
        d = offsets.get(n["id"])
        if d is not None:
            n["coords"] = [float(c + v) for c, v in zip(n["coords"], d, strict=False)]
    return out


# ─────────────────────────────────── the nonlinear model ───────────────────────────────────


def nonlinear_model(
    model: dict[str, Any],
    t: Any,
    options: StabilityOptions,
    fibres: dict[int, dict[str, Any]] | None = None,
    fibre_materials: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """``model`` made geometrically nonlinear (co-rotational frames and trusses) at the pack's
    modulus, and with ``material`` "plastic" its frames on ``fibres`` (elastic section id ->
    FiberSection, its ``fibre_materials`` the Steel02 ones) at the pack's yield strength."""
    notes: list[str] = []
    out = copy.deepcopy(model)
    k_e = float(t.stiffnessFactor)
    for s in out.get("sections", []):
        if s.get("type") == "ElasticSection" and s.get("E"):
            s["E"] = float(s["E"]) * k_e
            if s.get("G"):
                s["G"] = float(s["G"]) * k_e
    for m in out.get("materials", []):
        if m.get("type") == "Elastic" and m.get("E"):
            m["E"] = float(m["E"]) * k_e
    plastic = options.material == "plastic" and fibres
    if options.material == "plastic" and not fibres:
        notes.append("no member has a steel fibre section: the analysis is elastic (GNA)")
    if plastic:
        start = max((m["id"] for m in out.get("materials", [])), default=0)
        remap: dict[int, int] = {}
        for m in fibre_materials or []:
            m = dict(m)
            remap[m["id"]] = start + len(remap) + 1
            m["id"] = remap[m["id"]]
            if m.get("type") == "Steel02":
                m["Fy"] = float(m["Fy"]) * float(t.yieldFactor)
                m["E0"] = float(m["E0"]) * k_e
                m["b"] = max(float(t.hardeningRatio), 1e-6)
            out["materials"].append(m)
        next_section = max((s["id"] for s in out.get("sections", [])), default=0) + 1
        section_of: dict[int, int] = {}
        for elastic_id, section in fibres.items():
            s = copy.deepcopy(section)
            s["id"] = next_section
            for p in s.get("patches", []):
                p["material_id"] = remap.get(p["material_id"], p["material_id"])
            for f in s.get("fibres", []):
                f["material_id"] = remap.get(f["material_id"], f["material_id"])
            out["sections"].append(s)
            section_of[elastic_id] = next_section
            next_section += 1
    for e in out["elements"]:
        if e["type"] in _FRAMES:
            e["geom_transf"] = "Corotational"
            if plastic and e["section_id"] in section_of:
                e.update(
                    {
                        "type": "ForceBeamColumn",
                        "section_id": section_of[e["section_id"]],
                        "integration_points": 5,
                        "integration": "Lobatto",
                        "max_iter": 100,
                        "tolerance": 1e-10,
                    }
                )
                e.pop("rho", None)
                e.pop("consistent_mass", None)
        elif e["type"] == "Truss":
            e["type"] = "CorotTruss"
    return out, notes


# ─────────────────────────────────────── the path ───────────────────────────────────────


def _factor(ops: Any) -> float:
    try:
        return float(ops.getLoadFactor(1))
    except Exception:  # noqa: BLE001 - an older build: the pseudo time is the factor
        return float(ops.getTime())


def _norm_of(displacements: dict[int, Any]) -> float:
    """The norm of the nodes' translations (a first arc length)."""
    return max(math.sqrt(sum(float(np.dot(d[:3], d[:3])) for d in displacements.values())), 1e-9)


def _state(ops: Any) -> dict[int, list[float]]:
    return {int(n): [float(v) for v in ops.nodeDisp(n)[:3]] for n in ops.getNodeTags()}


def _norm(ops: Any, before: dict[int, list[float]]) -> float:
    now = _state(ops)
    return math.sqrt(sum(sum((a - b) ** 2 for a, b in zip(now[n], before.get(n, [0.0] * 3), strict=False)) for n in now))


def trace_path(
    ops: Any,
    model: dict[str, Any],
    control: tuple[int, int],
    method: str,
    steps: int,
    max_displacement: float,
    drop_share: float,
    on_design: Any = None,
    initial_arc: float = 1e-6,
) -> tuple[list[tuple[float, float]], dict[int, list[float]], float, bool, str]:
    """Follow the path of the model in ``ops`` (its pattern 1 holds the loads at λ = 1):
    load control to λ = 1 (``on_design()`` called there), then ``method`` (module notes,
    step 5). Returns ``(path, deformed shape at the peak, peak λ, whether the peak was passed,
    why it stopped)``."""
    node, dof = control
    path: list[tuple[float, float]] = [(0.0, 0.0)]
    peak, at_peak, passed = 0.0, _state(ops), False
    why = ""

    def record() -> None:
        nonlocal peak, at_peak
        lam = _factor(ops)
        path.append((lam, float(ops.nodeDisp(node, dof))))
        if lam > peak:
            peak, at_peak = lam, _state(ops)

    # 1. load control to λ = 1, with cuts
    _analysis(ops, model)
    dl = 1.0 / LOAD_STEPS
    lam = 0.0
    cuts = 0
    last_increment = 0.0
    while lam < 1.0 - 1e-9:
        step = min(dl, 1.0 - lam)
        before = _state(ops)
        ops.integrator("LoadControl", step)
        ops.analysis("Static")
        if ops.analyze(1) == 0:
            lam = _factor(ops)
            last_increment = _norm(ops, before)
            record()
            cuts = 0
        else:
            cuts += 1
            dl /= 2
            if cuts > CUTS:
                why = f"the load control steps stopped converging at λ = {lam:.3f}"
                break
    else:
        if on_design is not None:
            on_design()
    # 2. on past the peak
    taken = 0
    arc = last_increment if last_increment > 0 else initial_arc
    du = max_displacement / max(steps, 1)
    sign = 1.0 if float(ops.nodeDisp(node, dof)) >= 0 else -1.0
    cuts = 0
    while taken < steps:
        if method == "displacementControl":
            ops.integrator("DisplacementControl", node, dof, sign * du)
        else:
            ops.integrator("ArcLength", arc, 0.0)
        ops.analysis("Static")
        if ops.analyze(1) != 0:
            cuts += 1
            if cuts > CUTS:
                why = why or "the path stopped converging (a limit point the solver could not pass)"
                break
            arc /= 2
            du /= 2
            continue
        cuts = 0
        taken += 1
        record()
        lam = path[-1][0]
        if peak > 0 and lam < (1 - drop_share) * peak:
            passed = True
            why = f"the load factor fell {100 * drop_share:.0f} % below its peak"
            break
        if abs(path[-1][1]) > max_displacement:
            why = "the displacement exceeded the limit of the path"
            break
    else:
        why = why or "the steps ran out"
    if not passed and len(path) > 2 and path[-1][0] < peak * (1 - 1e-3):
        passed = True  # it turned down before stopping
    return path, at_peak, peak, passed, why


# ─────────────────────────────────────── analysis ───────────────────────────────────────


@dataclass
class CableSpec:
    """A cable member of the model: its name, area [m²], modulus [Pa], pretension [N],
    pieces, resistance [N] (None: not checked) and weight [N/m, global] (its own and its
    loads)."""

    name: str
    area: float
    modulus: float
    pretension: float
    segments: int
    resistance: float | None = None


def analyse(
    linear: dict[str, Any],
    factors: dict[str, float],
    options: StabilityOptions | None = None,
    t: Any = None,
    fibres: dict[int, dict[str, Any]] | None = None,
    fibre_materials: list[dict[str, Any]] | None = None,
    cables: list[CableSpec] | None = None,
    ops: Any = None,
) -> StabilityResult:
    """The nonlinear stability analysis of the derived analysis model ``linear`` under the
    combination ``factors`` ({case code: factor}) (module notes)."""
    from saengine.fem import cables as fem_cables

    options = options or StabilityOptions()
    t = t or table()
    if ops is None:
        from openseespy import opensees as ops
    cables = cables or []
    cable_names = {c.name for c in cables}
    nodal, uniform = reference_loads(linear, factors)
    model, loads, members, notes = stability_model(
        linear, nodal, uniform, options.segments, cable_names
    )
    # The cables' own uniform loads stay on their interior nodes, not lumped at the anchors.
    cable_w: dict[str, np.ndarray] = {}
    cable_ends: dict[str, tuple[int, int]] = {}
    elements = {e["id"]: e for e in model["elements"]}
    coords = _coords(model)
    for spec in cables:
        ids = members.get(spec.name, [])
        if not ids:
            continue
        nodes = [n for i in ids for n in elements[i]["nodes"][:2]]
        ends = [n for n in set(nodes) if nodes.count(n) == 1]
        if len(ends) != 2:
            notes.append(f"cable {spec.name}: not a single chain; left as modelled")
            continue
        length = sum(float(np.linalg.norm(coords[elements[i]["nodes"][1]] - coords[elements[i]["nodes"][0]])) for i in ids)
        w = np.zeros(3)
        for i in ids:
            if i in uniform:
                piece = float(np.linalg.norm(coords[elements[i]["nodes"][1]] - coords[elements[i]["nodes"][0]]))
                w += uniform[i] * piece / length
                for n in elements[i]["nodes"][:2]:  # take back the lumped share
                    loads.setdefault(n, np.zeros(6))[:3] -= uniform[i] * piece / 2
        cable_w[spec.name] = w
        cable_ends[spec.name] = (min(ends), max(ends))
    first = first_order(model, loads, ops)
    alpha_cr: float | None = None
    if options.imperfection == "eigenmode":
        offsets, applied, alpha_cr = eigenmode_imperfection(model, members, first["axial"], options, t)
    elif options.imperfection == "equivalent":
        offsets, applied = equivalent_imperfection(model, members, first["axial"], options, t)
        try:
            from saengine.fem.buckling import linear_buckling

            found = linear_buckling(model, first["axial"], modes=1)
            alpha_cr = found.factors[0] if found.factors else None
        except Exception as error:  # noqa: BLE001 - αcr is for the comparison only
            notes.append(f"αcr could not be worked out: {error}")
    else:
        offsets, applied = {}, {"kind": "none"}
        try:
            from saengine.fem.buckling import linear_buckling

            found = linear_buckling(model, first["axial"], modes=1)
            alpha_cr = found.factors[0] if found.factors else None
        except Exception as error:  # noqa: BLE001
            notes.append(f"αcr could not be worked out: {error}")
    shaped = imperfect(model, offsets)
    nonlinear, more = nonlinear_model(shaped, t, options, fibres, fibre_materials)
    notes += more
    # Cable members leave the model; their chains go in after the build.
    if cable_ends:
        gone = {i for c in cable_ends for i in members.get(c, [])}
        nonlinear["elements"] = [e for e in nonlinear["elements"] if e["id"] not in gone]
    _runner(nonlinear, ops)
    # Tags well past the model's own (the runner may add a few of its own).
    tags = {
        "node": max(n["id"] for n in nonlinear["nodes"]) + 1000,
        "element": max((e["id"] for e in model["elements"]), default=0) + 1000,
        "material": max((m["id"] for m in nonlinear.get("materials", [])), default=0) + 1000,
    }
    # A cable end that only cables reach has no rotational stiffness: its rotations are fixed.
    framed = {n for e in nonlinear["elements"] for n in e["nodes"][:2]}
    restraints = {n["id"]: list(n.get("restraint") or [False] * 6) for n in nonlinear["nodes"]}
    for ends in cable_ends.values():
        for n in ends:
            if n not in framed and not any(restraints.get(n, [False] * 6)[3:]):
                ops.fix(n, 0, 0, 0, 1, 1, 1)
                restraints[n] = [*restraints.get(n, [False] * 6)[:3], True, True, True]
    handles = []
    moved = _coords(shaped)
    for spec in cables:
        ends = cable_ends.get(spec.name)
        if ends is None:
            continue
        handle = fem_cables.add_cable(
            ops,
            spec.name,
            ends,
            (moved[ends[0]], moved[ends[1]]),
            spec.area,
            spec.modulus * float(t.stiffnessFactor),
            spec.pretension,
            spec.segments,
            tags,
            resistance=spec.resistance,
        )
        length = float(np.linalg.norm(moved[ends[1]] - moved[ends[0]]))
        for n, f in fem_cables.cable_weight_loads(handle, cable_w[spec.name], length).items():
            loads.setdefault(n, np.zeros(6))[:3] += f
        handles.append(handle)
    _pattern(ops, loads)
    # The control: the node and direction that moves most in the imperfection (else in the
    # first-order solution).
    source = offsets or {n: d[:3] for n, d in first["displacements"].items()}
    node = max(source, key=lambda n: float(np.linalg.norm(source[n][:3])))
    dof = int(np.argmax(np.abs(np.asarray(source[node][:3])))) + 1
    zs = [c[2] for c in coords.values()]
    plan = np.array([c[:2] for c in coords.values()])
    extent = max(max(zs) - min(zs), float(np.ptp(plan, axis=0).max()))
    method = options.method or t.path.method
    steps = options.steps or t.path.steps
    design_state: dict[str, Any] = {}

    def at_design() -> None:
        design_state["shape"] = _state(ops)
        design_state["cables"] = [fem_cables.cable_state(ops, h) for h in handles]

    path, at_peak, peak, passed, why = trace_path(
        ops,
        nonlinear,
        (node, dof),
        method,
        steps,
        extent / float(t.path.maxDisplacementRatio),
        float(t.path.dropShare),
        at_design,
        _norm_of(first["displacements"]) / LOAD_STEPS,
    )
    ops.wipe()
    if "shape" not in design_state:
        notes.append("the combination's full loads were not reached: the limit is below λ = 1")
    return StabilityResult(
        path=path,
        limitFactor=peak,
        limitReached=passed,
        alphaCr=alpha_cr,
        control=(node, dof),
        deformedAtLimit=at_peak,
        deformedAtDesign=design_state.get("shape"),
        imperfection=applied,
        cables=design_state.get("cables", []),
        stopped=why,
        notes=notes,
    )


# ─────────────────────────────────── the project's run ───────────────────────────────────


def _section_keys(linear: dict[str, Any]) -> dict[int, tuple[str, int, bool]]:
    """Elastic section id -> (object type id, quarter turns, vertical) from the derived
    sections' names (``"<type> column (rotated) (modified)"``)."""
    keys = {}
    for s in linear.get("sections", []):
        if s.get("type") != "ElasticSection":
            continue
        name = str(s.get("name") or "")
        turns = 1 if "(rotated)" in name else 0
        stem = name.replace(" (rotated)", "").replace(" (modified)", "")
        for suffix, vertical in ((" column", True), (" beam", False)):
            if stem.endswith(suffix):
                keys[s["id"]] = (stem[: -len(suffix)], turns, vertical)
                break
    return keys


def _fibres(
    linear: dict[str, Any], types: dict[str, Any], materials: dict[str, Any]
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]], list[str]]:
    """The steel members' fibre sections by elastic section id, their materials, and notes."""
    from saengine.fem.nonlinear import FiberMaterials, fiber_section

    library = FiberMaterials(offset=0)
    out: dict[int, dict[str, Any]] = {}
    elastic: set[str] = set()
    for sid, (type_id, turns, vertical) in _section_keys(linear).items():
        object_type = types.get(type_id)
        material = materials.get(getattr(object_type, "material", None)) if object_type else None
        if material is None or material.category.value != "steel":
            elastic.add(type_id)
            continue
        section = fiber_section(sid, f"{type_id} fibres", object_type, materials, library, vertical, turns)
        if section is None:
            elastic.add(type_id)
            continue
        out[sid] = section
    notes = (
        [f"members of {', '.join(sorted(elastic))} stay elastic (not steel, or no fibre section)"]
        if elastic
        else []
    )
    return out, library.materials, notes


def _cables(root: Path, types: dict[str, Any], materials: dict[str, Any], t: Any) -> list[CableSpec]:
    """The cable members of the building: braces whose type has a ``cable``."""
    from saengine.library.sections import section_properties

    try:
        bim = json.loads((root / "06 BIM" / "bim.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    specs = []
    for e in bim.get("elements", []):
        object_type = types.get(e.get("type"))
        cable = getattr(object_type, "cable", None)
        if cable is None:
            continue
        material = materials.get(object_type.material)
        modulus = (cable.modulus or (material.mechanical.E if material else None) or 200_000) * 1e6
        area = section_properties(object_type.profile).area * 1e-6
        specs.append(
            CableSpec(
                name=str(e["id"]),
                area=area,
                modulus=modulus,
                pretension=cable.pretension * 1e3,
                segments=cable.segments,
                resistance=cable.breakingForce * 1e3 * float(t.cables.breakingShare)
                if cable.breakingForce
                else None,
            )
        )
    return specs


def run_project(out_dir: str | Path, project_path: str | Path) -> dict[str, Any]:
    """The project's nonlinear stability analysis (its ``analysis.nonlinearStability``
    settings, the combination named there) with the code pack in force; the summary is kept
    beside the results (:data:`RESULT_FILE`) for the report."""
    from saengine.codes import context as code_context
    from saengine.fem.combinations import combination_factors, settings_beside
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    settings = settings_beside(project_path)
    chosen = getattr(getattr(settings, "analysis", None), "nonlinearStability", None)
    if settings is None or chosen is None:
        return {"available": False, "reason": "no nonlinear stability analysis is set (Project Settings, Analysis)"}
    combination = next(
        (c for c in settings.combinations if c.name == chosen.combination),
        settings.combinations[0] if settings.combinations else None,
    )
    if combination is None:
        return {"available": False, "reason": "the project has no load combinations"}
    root = Path(project_path).resolve().parent.parent
    linear = json.loads(Path(project_path).read_text(encoding="utf-8"))
    try:
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
    except (OSError, ValueError):
        types, materials = {}, {}
    try:
        pack = code_context.pack_for(settings, project_path)
    except Exception:  # noqa: BLE001 - a pack that cannot load: the default's
        pack = None
    options = StabilityOptions(
        imperfection=chosen.imperfection,
        material=chosen.material,
        direction=chosen.direction,
        method=chosen.method,
        steps=chosen.steps,
        segments=chosen.segments,
        curve=chosen.curve,
        bowRatio=chosen.bowRatio,
        swayRatio=chosen.swayRatio,
    )
    with code_context.using(pack):
        t = table()
        fibres, fibre_materials, notes = (
            _fibres(linear, types, materials) if options.material == "plastic" else ({}, [], [])
        )
        cables = _cables(root, types, materials, t)
        try:
            result = analyse(
                linear,
                combination_factors(combination),
                options,
                t,
                fibres,
                fibre_materials,
                cables,
            )
        except StabilityError as error:
            return {"available": False, "reason": str(error)}
        summary = summarise(result, t, combination.name, options)
        summary["notes"] = [*notes, *summary["notes"]]
        summary["code"] = code_context.code_name()
    try:
        (Path(out_dir) / RESULT_FILE).write_text(json.dumps(summary), encoding="utf-8")
    except OSError:
        pass
    return summary


def summarise(
    result: StabilityResult, t: Any, combination: str, options: StabilityOptions
) -> dict[str, Any]:
    """The plain summary the results view and the report read."""
    required = float(t.requiredFactor)
    ratio = result.limitFactor / result.alphaCr if result.alphaCr else None
    kind = (
        "GMNIA"
        if options.material == "plastic" and options.imperfection != "none"
        else "GMNA"
        if options.material == "plastic"
        else "GNIA"
        if options.imperfection != "none"
        else "GNA"
    )
    return {
        "available": True,
        "analysis": kind,
        "combination": combination,
        "path": [[round(lam, 5), round(u, 6)] for lam, u in result.path],
        "limitFactor": result.limitFactor,
        "limitReached": result.limitReached,
        "alphaCr": result.alphaCr,
        "ratio": ratio,
        "required": required,
        "ok": result.limitFactor >= required,
        "control": {"node": result.control[0], "dof": result.control[1]},
        "deformedAtLimit": result.deformedAtLimit,
        "imperfection": result.imperfection,
        "cables": result.cables,
        "stopped": result.stopped,
        "clauses": dict(getattr(t, "clauses", {}) or {}),
        "source": t.source,
        "notes": [*result.notes, *([t.note] if t.note else [])],
    }


def load_summary(out_dir: str | Path) -> dict[str, Any] | None:
    """The summary of the last run (None when none was made)."""
    try:
        return json.loads((Path(out_dir) / RESULT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

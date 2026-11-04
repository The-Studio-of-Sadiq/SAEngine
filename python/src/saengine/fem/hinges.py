"""P3: hinges at the member ends of a pushover, their performance levels and states.

The pushover model (:mod:`saengine.fem.nonlinear`) is a fibre model: its members crack and
yield where the fibres of their sections do, so it needs no lumped hinges to follow them. The
hinges of a performance-based assessment are therefore *assigned* to it, not built into it:
each member end (each storey segment of a fibre wall) gets a hinge whose modelling parameters
(a, b, c) and limits per performance level come from the code pack's ``pushover.hinges``
(:class:`saengine.codes.tables.PushoverHinges`), worked out from the member's section, bars,
ties and forces, and whose deformation is measured from the fibre analysis itself:

- frame members: the chord rotation of the end (the node's rotation less the rotation of the
  chord between the member's end faces, in the member's local axes); the plastic rotation is
  what exceeds the chord rotation at which the end yields, the first yield of a tension bar of
  the end section in the analysis (reinforced concrete) or θy = Z·Fy·L/(k·E·I) (steel, times
  1 - P/Pye for columns);
- fibre walls: the rotation over the storey segment (in its plane), beyond its value at the
  first yield of the segment's base bars; walls controlled by shear: the storey drift ratio;
- steel braces: the axial deformation beyond the yield (tension) or buckling (compression)
  deformation, in multiples of it.

The analysis is not changed by the hinges (SAEngine practice): their states are read from the
same run the target displacement is found on.

Models of the parameters, by the pack's ``model`` id per component (``rcBeam``, ``rcColumn``,
``rcWall``, ``rcWallShear``, ``steelBeam``, ``steelColumn``, ``steelBrace``):

- ``table``: rows matched by categorical variables or numeric ranges, interpolated linearly
  between the grid points of their numeric variables, held beyond the ends;
- ``columnRegression``: a, b, c of RC columns from the axial ratio, the transverse ratio and the
  shear ratio by the pack's coefficients;
- ``chordRotationCapacity``: the ultimate chord rotation θum of RC members by an empirical
  formula with the pack's coefficients; the levels are the chord rotation at yield and shares
  of θum.

Variables the engine works out (SI internally; ``stressUnitPerMPa`` sets the unit √fc of the
shear stress variables is in): ``rhoBalance`` ((ρ - ρ')/ρbal), ``shearStress`` (V/(b·d·√fc)
for beams, V/(tw·lw·√fc) for walls), ``conforming`` (C/NC), ``control`` (flexure/shear),
``spacing`` (close/wide), ``axialStress`` (((As - A's)·fy + P)/(tw·lw·fc)), ``boundary``
(confined/unconfined), ``slenderness`` (0 compact to 1 noncompact), ``axialRatio`` (P/PCL),
``action`` (tension/compression).

Units: m, N, rad; stresses in MPa where a formula needs them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem.acceptance import _fibre_kinds

MPA = 1e6
#: Components a pack can give hinges for.
COMPONENTS = (
    "rcBeam",
    "rcColumn",
    "rcWall",
    "rcWallShear",
    "steelBeam",
    "steelColumn",
    "steelBrace",
)
#: The backbone segments of a hinge with a, b (B yield, C strength loss, E residual lost).
BACKBONE = ("B", "B-C", "C-E", "E+")


def table() -> Any | None:
    """The pack's ``pushover.hinges``; None when the pack in force gives none."""
    from saengine.fem.pushover_target import table as pushover_table

    found = pushover_table()
    return found.hinges if found is not None else None


# ───────────────────────────────────── sections ─────────────────────────────────────


@dataclass
class Section:
    """What a hinge reads of its fibre section, in the element's local axes y, z [m]."""

    rects: list[tuple[float, float, float, float, int]]  # y0, z0, y1, z1, material
    rings: list[tuple[float, float, float, float, float, int]]  # yc, zc, r0, r1, material
    bars: list[tuple[float, float, float, int]]  # y, z, area, material
    kinds: list[tuple[str, int]]
    concrete: bool
    fc: float  # MPa (unconfined)
    fy: float  # MPa (bars or steel)
    es: float  # MPa
    core: tuple[float, float, float, float] | None  # y0, z0, y1, z1 of the confined core

    def extent(self, axis: int) -> tuple[float, float]:
        """(min, max) of the section along local y (0) or z (1)."""
        lo, hi = math.inf, -math.inf
        for y0, z0, y1, z1, _ in self.rects:
            a, b = (y0, y1) if axis == 0 else (z0, z1)
            lo, hi = min(lo, a), max(hi, b)
        for yc, zc, _, r1, _, _ in self.rings:
            c = yc if axis == 0 else zc
            lo, hi = min(lo, c - r1), max(hi, c + r1)
        return (lo, hi) if lo < hi else (0.0, 0.0)

    @property
    def area(self) -> float:
        a = sum((y1 - y0) * (z1 - z0) for y0, z0, y1, z1, _ in self.rects)
        return a + sum(math.pi * (r1**2 - r0**2) for _, _, r0, r1, _, _ in self.rings)

    def inertia(self, depth: int) -> tuple[float, float]:
        """(I, Z) about the axis across ``depth`` (0: depth along y, 1: along z) through the
        section's middle [m⁴, m³] (the shapes are symmetric or nearly so)."""
        lo, hi = self.extent(depth)
        mid = 0.5 * (lo + hi)
        inertia = plastic = 0.0
        for y0, z0, y1, z1, _ in self.rects:
            (c0, c1), w = ((y0, y1), z1 - z0) if depth == 0 else ((z0, z1), y1 - y0)
            c0, c1 = c0 - mid, c1 - mid
            inertia += w * (c1**3 - c0**3) / 3
            plastic += w * (_abs_moment(c1) - _abs_moment(c0))
        for _, _, r0, r1, _, _ in self.rings:
            inertia += math.pi * (r1**4 - r0**4) / 4
            plastic += 4 * (r1**3 - r0**3) / 3
        return inertia, plastic


def _abs_moment(c: float) -> float:
    """∫₀^c |t| dt with its sign: the first moment of a unit strip from 0 to c."""
    return math.copysign(c * c / 2, c)


def section_of(section: dict[str, Any], materials: dict[int, dict[str, Any]]) -> Section:
    """The :class:`Section` of a FiberSection of the model."""
    rects, rings, bars = [], [], []
    for p in section.get("patches", []):
        if p["kind"] == "rect":
            rects.append((p["y_i"], p["z_i"], p["y_j"], p["z_j"], int(p["material_id"])))
        else:
            rings.append(
                (
                    p["y_center"],
                    p["z_center"],
                    p["r_inner"],
                    p["r_outer"],
                    p.get("start_angle", 0.0),
                    int(p["material_id"]),
                )
            )
    for f in section.get("fibres", []):
        bars.append((float(f["y"]), float(f["z"]), float(f["area"]), int(f["material_id"])))
    kinds = _fibre_kinds(section, materials)
    used = {m for _, _, _, _, m in rects} | {r[-1] for r in rings}
    concretes = [materials[m] for m in used if materials.get(m, {}).get("type") == "Concrete02"]
    steel_ids = [m for *_, m in bars] if concretes else sorted(used)
    steels = [materials[m] for m in steel_ids if materials.get(m, {}).get("type") == "Steel02"]
    fc = min((abs(float(m["fpc"])) for m in concretes), default=0.0) / MPA
    fy = float(steels[0]["Fy"]) / MPA if steels else 0.0
    es = float(steels[0]["E0"]) / MPA if steels else 200_000.0
    core = None
    cores = [
        (y0, z0, y1, z1)
        for y0, z0, y1, z1, m in rects
        if str(materials.get(m, {}).get("name", "")).endswith(" core")
    ]
    if cores:
        core = (
            min(c[0] for c in cores),
            min(c[1] for c in cores),
            max(c[2] for c in cores),
            max(c[3] for c in cores),
        )
    return Section(rects, rings, bars, kinds, bool(concretes), fc, fy, es, core)


# ───────────────────────────────────── the hinges ─────────────────────────────────────


@dataclass
class Hinge:
    """A hinge of the pushover model: at end ``end`` ("i", "j"; "base" of a wall segment) of
    member ``member``."""

    member: str
    end: str
    component: str
    elements: list[int]
    element: int  # the element whose end section and forces the hinge reads
    near: int  # the hinge's node
    far: int  # the member's other end node
    store: str  # "start" or "end": which fibre section of ``element``
    axes: np.ndarray  # rows x, y, z
    origin: tuple[np.ndarray, np.ndarray]  # end faces (near, far) [m]
    offsets: tuple[np.ndarray, np.ndarray]  # rigid offsets of the faces from the nodes
    length: float
    section: Section
    object_type: Any = None
    height: float = 0.0  # walls: the whole wall's height
    notes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.member} {self.end}"


def _type_id(section_name: str) -> str:
    for tail in (" column fibers", " beam fibers", " wall fibers and shear", " wall fibers"):
        if section_name.endswith(tail):
            return section_name[: -len(tail)]
    return ""


def _axes(a: np.ndarray, b: np.ndarray, vecxz: Any) -> np.ndarray:
    from saengine.fem.derive import local_axes

    return np.vstack(local_axes(a, b, vecxz))


def assign(project: dict[str, Any], library: dict[str, Any] | None = None) -> list[Hinge]:
    """The hinges of the pushover model ``project``: two per frame member with a fibre section
    (its elements are those whose name before ``#`` is the member's), one per storey segment of
    a fibre wall. ``library``: the object types by id (their ties), or None."""
    materials = {int(m["id"]): m for m in project.get("materials", [])}
    sections = {int(s["id"]): s for s in project.get("sections", [])}
    coords = {int(n["id"]): np.asarray(n["coords"], dtype=float) for n in project["nodes"]}
    types = library or {}
    chains: dict[str, list[dict[str, Any]]] = {}
    walls: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    fibre_of: dict[int, tuple[dict[str, Any], str]] = {}
    for element in project.get("elements", []):
        if element.get("type") not in ("ForceBeamColumn", "DispBeamColumn"):
            continue
        section = sections.get(int(element["section_id"]))
        name = str(section.get("name", "")) if section else ""
        while section is not None and section.get("type") == "SectionAggregator":
            section = sections.get(int(section.get("section_id") or 0))
        if section is None or section.get("type") != "FiberSection":
            continue
        fibre_of[int(element["id"])] = (section, name)
        if name.endswith((" wall fibers and shear", " wall fibers")):
            walls.append((element, section, _type_id(name)))
        else:
            member = str(element.get("name") or element["id"]).split("#")[0]
            chains.setdefault(member, []).append(element)
    hinges: list[Hinge] = []
    for member, elements in chains.items():
        hinges += _frame_hinges(member, elements, fibre_of, materials, coords, types)
    wall_heights: dict[str, list[float]] = {}
    for element, _, _ in walls:
        wall = str(element.get("name") or element["id"]).split("#")[0]
        zs = [coords[int(n)][2] for n in element["nodes"]]
        wall_heights.setdefault(wall, []).extend(zs)
    for element, section, type_id in walls:
        wall = str(element.get("name") or element["id"]).split("#")[0]
        i, j = (int(n) for n in element["nodes"])
        a, b = coords[i], coords[j]
        zs = wall_heights[wall]
        segment = str(element.get("name") or element["id"])
        hinges.append(
            Hinge(
                member=segment,
                end="base",
                component="rcWall",
                elements=[int(element["id"])],
                element=int(element["id"]),
                near=i,
                far=j,
                store="start",
                axes=_axes(a, b, element.get("vecxz")),
                origin=(a, b),
                offsets=(np.zeros(3), np.zeros(3)),
                length=float(np.linalg.norm(b - a)),
                section=section_of(section, materials),
                object_type=types.get(type_id),
                height=max(zs) - min(zs),
            )
        )
    return hinges


def _frame_hinges(
    member: str,
    elements: list[dict[str, Any]],
    fibre_of: dict[int, tuple[dict[str, Any], str]],
    materials: dict[int, dict[str, Any]],
    coords: dict[int, np.ndarray],
    types: dict[str, Any],
) -> list[Hinge]:
    """The two end hinges of a frame member made of ``elements`` (in a chain)."""
    count: dict[int, int] = {}
    for e in elements:
        for n in e["nodes"]:
            count[int(n)] = count.get(int(n), 0) + 1
    ends = [n for n, c in count.items() if c == 1]
    if len(ends) != 2:
        return []
    by_node = {}
    for e in elements:
        i, j = (int(n) for n in e["nodes"])
        if i in ends:
            by_node[i] = (e, "start")
        if j in ends:
            by_node[j] = (e, "end")
    first, last = ends
    # Order the ends as the first element runs (its node i first).
    _e0, store0 = by_node[first]
    if store0 == "end":
        first, last = last, first
    e_first, _ = by_node[first]
    e_last, _ = by_node[last]
    section, name = fibre_of[int(e_first["id"])]
    sec = section_of(section, materials)
    offsets_first = _offsets(e_first, "i")
    offsets_last = _offsets(e_last, "j")
    a = coords[first] + offsets_first
    b = coords[last] + offsets_last
    axis = b - a
    length = float(np.linalg.norm(axis))
    if length <= 0:
        return []
    axes = _axes(coords[first], coords[last], e_first.get("vecxz"))
    slope = abs(axis[2]) / length
    if sec.concrete:
        component = "rcColumn" if slope > 0.999 else "rcBeam"
    else:
        component = (
            "steelColumn" if slope > 0.999 else "steelBeam" if slope < 0.05 else "steelBrace"
        )
    object_type = types.get(_type_id(name))
    out = []
    for end, near, far, (element, store), offs in (
        ("i", first, last, by_node[first], (offsets_first, offsets_last)),
        ("j", last, first, by_node[last], (offsets_last, offsets_first)),
    ):
        out.append(
            Hinge(
                member=member,
                end=end,
                component=component,
                elements=[int(e["id"]) for e in elements],
                element=int(element["id"]),
                near=near,
                far=far,
                store=store,
                axes=axes,
                origin=(coords[near] + offs[0], coords[far] + offs[1]),
                offsets=offs,
                length=length,
                section=sec,
                object_type=object_type,
            )
        )
    return out


def _offsets(element: dict[str, Any], end: str) -> np.ndarray:
    found = element.get("joint_offsets")
    if not found:
        return np.zeros(3)
    values = np.asarray(found, dtype=float)
    return values[:3] if end == "i" else values[3:]


# ───────────────────────────────────── deformations ─────────────────────────────────────


@dataclass
class History:
    """The deformations and forces of a hinge over the steps of a run."""

    theta: np.ndarray  # (steps, 2): chord rotation about local y and z [rad]
    drift: np.ndarray  # (steps,): walls: in-plane drift ratio
    axial: np.ndarray  # (steps,): elongation of the member [m]
    bar_strain: np.ndarray  # (steps,): the largest tensile bar strain of the end section
    tension_side: np.ndarray  # (steps, 2): sign of the tension side along z (0) and y (1)
    forces: np.ndarray  # (steps, 6): N (compression +), Vy, Vz, T, My, Mz at the hinge's end


def history(hinge: Hinge, results: Any) -> History | None:
    """The :class:`History` of ``hinge`` in the pushover ``results``; None without results."""
    near = results.node_disp.get(hinge.near)
    far = results.node_disp.get(hinge.far)
    if near is None or far is None:
        return None
    un, uf = np.asarray(near, dtype=float), np.asarray(far, dtype=float)
    steps = min(len(un), len(uf))
    x, y, z = hinge.axes
    theta = np.zeros((steps, 2))
    drift = np.zeros(steps)
    axial = np.zeros(steps)
    for s in range(steps):
        tn, rn = un[s][:3], un[s][3:6]
        tf, rf = uf[s][:3], uf[s][3:6]
        # The faces move with their nodes' rotations (rigid offsets).
        fn = tn + np.cross(rn, hinge.offsets[0])
        ff = tf + np.cross(rf, hinge.offsets[1])
        # From node i to node j, whichever end the hinge is at.
        delta = (ff - fn) * (-1.0 if hinge.end == "j" else 1.0)
        if hinge.end == "base":  # a wall segment: its rotation and drift in its plane
            theta[s] = (float((rf - rn) @ y), float((rf - rn) @ z))
            drift[s] = float(delta @ z) / hinge.length
        else:
            theta[s] = (
                float(rn @ y) + float(delta @ z) / hinge.length,
                float(rn @ z) - float(delta @ y) / hinge.length,
            )
        axial[s] = float(delta @ x)
    store = results.element_start_fibers if hinge.store == "start" else results.element_end_fibers
    fibres = store.get(hinge.element) if store else None
    bar_strain = np.zeros(steps)
    side = np.zeros((steps, 2))
    bar_rows = [k for k, (kind, _) in enumerate(hinge.section.kinds) if kind == "bar"]
    if fibres is not None:
        arr = np.asarray(fibres, dtype=float)
        for s in range(min(steps, len(arr))):
            rows = arr[s]
            if len(rows) != len(hinge.section.kinds):
                continue
            if bar_rows:
                strains = rows[bar_rows, 4]
                bar_strain[s] = float(max(0.0, strains.max()))
            # The tension side: where the fibres stretch more (the sign of the strain's
            # slope across the section).
            strain = rows[:, 4] - rows[:, 4].mean()
            for k, column in ((0, 1), (1, 0)):
                c = rows[:, column] - rows[:, column].mean()
                side[s, k] = 1.0 if float(c @ strain) >= 0 else -1.0
    forces = np.zeros((steps, 6))
    local = results.element_forces.get(hinge.element) if results.element_forces else None
    if local is not None:
        arr = np.asarray(local, dtype=float)
        for s in range(min(steps, len(arr))):
            row = arr[s]
            if len(row) < 12:
                continue
            end = row[:6] if hinge.store == "start" else row[6:12]
            forces[s] = (
                0.5 * (row[0] - row[6]),
                abs(end[1]),
                abs(end[2]),
                end[3],
                abs(end[4]),
                abs(end[5]),
            )
    return History(theta, drift, axial, bar_strain, side, forces)


def yield_point(values: np.ndarray, strain: np.ndarray, yield_strain: float) -> tuple[int, float]:
    """The first step at which ``strain`` reaches ``yield_strain`` and ``values`` there
    (interpolated by the strain between the steps): ``(step, value)``; (-1, nan) when it never
    does."""
    for s in range(len(strain)):
        if strain[s] >= yield_strain:
            if s == 0 or strain[s] == strain[s - 1]:
                return s, float(values[s])
            t = (yield_strain - strain[s - 1]) / (strain[s] - strain[s - 1])
            return s, float(values[s - 1] + t * (values[s] - values[s - 1]))
    return -1, math.nan


# ───────────────────────────────────── variables ─────────────────────────────────────


def balanced_ratio(fc: float, fy: float, es: float, rule: Any) -> float:
    """ρbal = α1·β1·fc/fy·εcu·Es/(εcu·Es + fy) (MPa), β1 by fc from the pack; 0 when the
    pack gives none of them."""
    if not rule.beta1 or rule.stressBlock is None or rule.ultimateStrain is None:
        return 0.0
    points = sorted(rule.beta1)
    fcs = [p[0] for p in points]
    betas = [p[1] for p in points]
    beta1 = float(np.interp(fc, fcs, betas))
    ecu = rule.ultimateStrain
    return rule.stressBlock * beta1 * fc / fy * ecu * es / (ecu * es + fy) if fy > 0 else 0.0


def _ties(hinge: Hinge) -> tuple[float, float, int, float] | None:
    """(tie area per leg [m²], spacing in the hinge region [m], legs, fyt [MPa]) of the
    member's object type; None without ties."""
    reinforcement = getattr(hinge.object_type, "reinforcement", None)
    ties = getattr(reinforcement, "transverse", None)
    if ties is None or not ties.spacing:
        return None
    spacing = ties.zone.spacing if ties.zone is not None else ties.spacing
    legs = min(ties.legs, ties.legsX or ties.legs)
    return math.pi * (ties.dia * 1e-3) ** 2 / 4, spacing * 1e-3, legs, hinge.section.fy


def _bending(hinge: Hinge, axis: int) -> tuple[int, int]:
    """(depth coordinate, width coordinate) of bending about local y (axis 0: depth along z)
    or z (axis 1: depth along y)."""
    return (1, 0) if axis == 0 else (0, 1)


def _flexure(hinge: Hinge, axis: int, side: float) -> dict[str, float]:
    """b, h, d, As, A's [m, m²] of the end section bent about ``axis`` with its tension side
    ``side`` (+1: at +depth)."""
    depth, width = _bending(hinge, axis)
    lo, hi = hinge.section.extent(depth)
    wlo, whi = hinge.section.extent(width)
    h, b = hi - lo, whi - wlo
    mid = 0.5 * (lo + hi)
    tension = [(c, a) for c, a in ((bar[depth] - mid, bar[2]) for bar in hinge.section.bars)]
    a_s = sum(a for c, a in tension if c * side > 1e-9)
    a_c = sum(a for c, a in tension if c * side < -1e-9)
    moment = sum(a * c * side for c, a in tension if c * side > 1e-9)
    d = h / 2 + (moment / a_s if a_s > 0 else 0.0)
    return {"b": b, "h": h, "d": max(d, 1e-6), "As": a_s, "Asc": a_c}


def variables(
    hinge: Hinge, hist: History, step: int, axis: int, rule: Any
) -> dict[str, float | str]:
    """The hinge variables (see the module) of ``hinge`` at ``step``, bent about ``axis``."""
    sec = hinge.section
    side = float(hist.tension_side[step, 0 if axis == 0 else 1]) or 1.0
    geo = _flexure(hinge, axis, side)
    b, h, d = geo["b"], geo["h"], geo["d"]
    n_comp = max(0.0, float(hist.forces[step, 0]))
    shear = float(np.max(hist.forces[: step + 1, 2 if axis == 0 else 1]))
    moment = float(hist.forces[step, 4 if axis == 0 else 5])
    shear_now = float(hist.forces[step, 2 if axis == 0 else 1])
    out: dict[str, float | str] = {
        "N": n_comp,
        "V": shear,
        "Vstep": shear_now,
        "M": moment,
        "b": b,
        "h": h,
        "d": d,
    }
    unit = math.sqrt(rule.stressUnitPerMPa)
    if sec.concrete:
        fc, fy = sec.fc, sec.fy
        ag = sec.area
        ties = _ties(hinge)
        av = s = 0.0
        fyt = fy
        if ties is not None:
            leg, s, legs, fyt = ties
            av = legs * leg
        vs = av * fyt * MPA * d / s if s > 0 else 0.0
        vc = rule.concreteShear * math.sqrt(fc) * MPA * b * d if rule.concreteShear else math.inf
        rho = geo["As"] / (b * d)
        rho_c = geo["Asc"] / (b * d)
        bal = balanced_ratio(fc, fy, sec.es, rule)
        out.update(
            {
                "fc": fc,
                "fy": fy,
                "fyt": fyt,
                "rho": rho,
                "rhoCompression": rho_c,
                "rhoBalanced": bal,
                "rhoBalance": (rho - rho_c) / bal if bal > 0 else 0.0,
                "shearStress": shear / (b * d * MPA) / math.sqrt(fc) * unit if fc > 0 else 0.0,
                "Vs": vs,
                "Vc": vc,
                "Av": av,
                "s": s,
                "rhoT": av / (b * s) if s > 0 else 0.0,
                "axialLoadRatio": n_comp / (ag * fc * MPA) if ag > 0 and fc > 0 else 0.0,
                "conforming": (
                    "C"
                    if s > 0
                    and rule.conformingSpacing is not None
                    and rule.conformingShear is not None
                    and s <= rule.conformingSpacing * d
                    and vs >= rule.conformingShear * shear
                    else "NC"
                ),
                "control": "shear" if shear >= vc + vs else "flexure",
                "spacing": (
                    "close"
                    if rule.closeSpacing is not None and 0 < s <= rule.closeSpacing * d
                    else "wide"
                ),
            }
        )
        if hinge.component in ("rcWall", "rcWallShear"):
            tw, lw = b, h
            out["axialStress"] = (
                ((geo["As"] - geo["Asc"]) * fy * MPA + n_comp) / (tw * lw * fc * MPA)
                if fc > 0
                else 0.0
            )
            out["shearStress"] = shear / (tw * lw * MPA) / math.sqrt(fc) * unit if fc > 0 else 0.0
            boundary = getattr(getattr(hinge.object_type, "reinforcement", None), "boundary", None)
            hoop = getattr(boundary, "hoop", None)
            out["boundary"] = "confined" if hoop is not None and hoop.spacing > 0 else "unconfined"
            out["aspect"] = hinge.height / lw if lw > 0 else 0.0
    else:
        fy, e = sec.fy, sec.es
        area = sec.area
        i_axis, z_axis = sec.inertia(_bending(hinge, axis)[0])
        i_min = min(sec.inertia(0)[0], sec.inertia(1)[0])
        k_len = rule.effectiveLength * hinge.length
        euler = math.pi**2 * e * MPA * i_min / k_len**2 if k_len > 0 else math.inf
        pcl = min(area * fy * MPA, euler)
        out.update(
            {
                "fy": fy,
                "E": e,
                "A": area,
                "I": i_axis,
                "Z": z_axis,
                "PCL": pcl,
                "axialRatio": n_comp / pcl if pcl > 0 else 0.0,
                "slenderness": _slenderness(hinge, fy, e, rule),
                "action": "tension" if hist.axial[step] >= 0 else "compression",
            }
        )
    return out


def _slenderness(hinge: Hinge, fy: float, e: float, rule: Any) -> float:
    """0 for a compact section, 1 for a noncompact one, linear between (the more severe of the
    flange and the web); 1 when the profile is not an I shape (not covered: the safe end)."""
    from saengine.library.objects import IShapeProfile

    profile = getattr(hinge.object_type, "profile", None)
    if not isinstance(profile, IShapeProfile) or fy <= 0:
        return 1.0
    root = math.sqrt(e / fy)
    flange = profile.overallWidth / (2 * profile.flangeThickness)
    web = (profile.overallDepth - 2 * profile.flangeThickness) / profile.webThickness

    def share(ratio: float, compact: float, noncompact: float) -> float:
        lo, hi = compact * root, noncompact * root
        return min(1.0, max(0.0, (ratio - lo) / (hi - lo))) if hi > lo else 0.0

    return max(
        share(flange, rule.compactFlange, rule.noncompactFlange),
        share(web, rule.compactWeb, rule.noncompactWeb),
    )


# ───────────────────────────────────── the models ─────────────────────────────────────


def lookup(component: Any, values: dict[str, Any]) -> dict[str, Any] | None:
    """Model ``table``: a, b, c and the limits of the rows of ``component`` that match
    ``values``, interpolated over the numeric variables of their grid; None when no row
    matches."""

    def matches(row: Any) -> bool:
        for key, want in row.match.items():
            have = values.get(key)
            if isinstance(want, str):
                if str(have) != want:
                    return False
            else:
                lo, hi = want
                x = float(have or 0.0)
                if (lo is not None and x < lo) or (hi is not None and x >= hi):
                    return False
        return True

    rows = [r for r in component.rows if matches(r)]
    if not rows:
        return None
    grid = [v for v in component.variables if any(v in r.at for r in rows)]

    def mix(a: dict[str, Any], b: dict[str, Any], t: float) -> dict[str, Any]:
        limits = {k: a["limits"][k] + t * (b["limits"][k] - a["limits"][k]) for k in a["limits"]}
        return {
            **{
                k: None if a[k] is None or b[k] is None else a[k] + t * (b[k] - a[k])
                for k in ("a", "b", "c")
            },
            "limits": limits,
        }

    def solve(group: list[Any], names: list[str]) -> dict[str, Any]:
        if not names:
            r = group[0]
            return {"a": r.a, "b": r.b, "c": r.c, "limits": dict(r.limits)}
        name = names[0]
        points = sorted({r.at[name] for r in group if name in r.at})
        if not points:
            return solve(group, names[1:])
        x = min(max(float(values.get(name) or 0.0), points[0]), points[-1])
        k = int(np.searchsorted(points, x, side="right")) - 1
        k = min(max(k, 0), len(points) - 1)
        lo = points[k]
        hi = points[min(k + 1, len(points) - 1)]
        low = solve([r for r in group if r.at.get(name) == lo], names[1:])
        if hi == lo:
            return low
        high = solve([r for r in group if r.at.get(name) == hi], names[1:])
        return mix(low, high, (x - lo) / (hi - lo))

    return solve(rows, grid)


def column_regression(rule: Any, values: dict[str, Any], levels: list[str]) -> dict[str, Any]:
    """Model ``columnRegression`` (see :class:`saengine.codes.tables.ColumnRegression`)."""
    n = float(values.get("axialLoadRatio", 0.0))
    if rule.axialMax is not None:
        n = min(n, rule.axialMax)
    rho = min(float(values.get("rhoT", 0.0)), rule.rhoMax)
    v = max(float(values.get("shearRatio", 0.0)), rule.shearRatioMin)
    if rho < rule.rhoMin or rho <= 0:
        return {"a": 0.0, "b": 0.0, "c": 0.0, "limits": dict.fromkeys(levels, 0.0)}
    a0, an, ar, av = rule.a
    a = max(0.0, a0 + an * n + ar * rho + av * v)
    b0, b1, bn, bc = rule.b
    ratio = float(values.get("fc", 0.0)) / float(values.get("fyt") or values.get("fy") or 1.0)
    b = max(a, b0 / (b1 + n / bn / rho * ratio) + bc)
    c0, cn = rule.c
    c = max(0.0, c0 + cn * n)
    limits = {rule.ioLevel: min(rule.ioShare * a, rule.ioMax)}
    limits.update({k: share * b for k, share in rule.shares.items()})
    return {"a": a, "b": b, "c": c, "limits": limits}


def column_shear_strength(rule: Any, values: dict[str, Any], ag: float) -> float:
    """Vcol = k·λ·[Av·fyt·d/s + vc·√fc/(M/Vd)·√(1 + N/(vn·√fc·Ag))·share·Ag] [N]."""
    fc = float(values.get("fc", 0.0))
    d, s = float(values.get("d", 0.0)), float(values.get("s", 0.0))
    steel = float(values.get("Av", 0.0)) * float(values.get("fyt", 0.0)) * MPA * d / s if s else 0.0
    shear = float(values.get("Vstep", values.get("V", 0.0)))
    span = float(values.get("M", 0.0)) / (shear * d) if shear > 0 and d > 0 else rule.shearSpan[1]
    span = min(max(span, rule.shearSpan[0]), rule.shearSpan[1])
    root = math.sqrt(fc) if fc > 0 else 0.0
    axial = float(values.get("N", 0.0)) / (rule.shearAxial * root * MPA * ag) if root else 0.0
    concrete = rule.shearConcrete * root / span * math.sqrt(1 + axial) * rule.shearArea * ag * MPA
    return rule.shearK * rule.shearLambda * (steel + concrete)


def chord_rotation_capacity(hinge: Hinge, rule: Any, values: dict[str, Any]) -> float:
    """Model ``chordRotationCapacity``: θum of the RC end (see
    :class:`saengine.codes.tables.ChordRotationCapacity`)."""
    sec = hinge.section
    fc, fy = sec.fc, sec.fy
    b, h = float(values["b"]), float(values["h"])
    nu = float(values.get("N", 0.0)) / (b * h * fc * MPA) if fc > 0 else 0.0
    rho_t = float(values.get("rho", 0.0)) * float(values["d"]) / h
    rho_c = float(values.get("rhoCompression", 0.0)) * float(values["d"]) / h
    omega, omega_c = rho_t * fy / fc, rho_c * fy / fc
    shear = float(values.get("Vstep", values.get("V", 0.0)))
    lv = float(values.get("M", 0.0)) / shear if shear > 0 else hinge.length / 2
    lv = max(lv, 1e-3 * h)
    ties = _ties(hinge)
    confinement = 0.0
    if ties is not None and sec.core is not None:
        leg, s, legs, fyw = ties
        y0, z0, y1, z1 = sec.core
        bo, ho = y1 - y0, z1 - z0  # the formula is symmetric in them
        spaces = sum(x * x for x in _bar_spaces(sec))
        alpha = (1 - s / (2 * bo)) * (1 - s / (2 * ho)) * (1 - spaces / (6 * ho * bo))
        rho_sx = legs * leg / (b * s)
        confinement = max(0.0, alpha) * rho_sx * fyw / fc
    theta = (
        1
        / rule.gammaEl
        * rule.k
        * rule.axialBase ** max(nu, 0.0)
        * (max(rule.omegaMin, omega_c) / max(rule.omegaMin, omega) * fc) ** rule.omegaExponent
        * (lv / h) ** rule.spanExponent
        * rule.confinementBase**confinement
    )
    if hinge.component in ("rcWall", "rcWallShear"):
        theta *= rule.wallFactor
    values["LV"] = lv
    values["nu"] = nu
    values["confinement"] = confinement
    return theta


def _bar_spaces(sec: Section) -> list[float]:
    """Distances between neighbouring bars around the section (each taken as held by a tie
    corner or a cross-tie: SAEngine practice)."""
    if len(sec.bars) < 3:
        return []
    ys = np.array([b[0] for b in sec.bars])
    zs = np.array([b[1] for b in sec.bars])
    angles = np.arctan2(zs - zs.mean(), ys - ys.mean())
    order = np.argsort(angles)
    pts = np.column_stack([ys[order], zs[order]])
    return [float(np.linalg.norm(pts[k] - pts[k - 1])) for k in range(len(pts))]


# ───────────────────────────────────── states ─────────────────────────────────────


def classify(value: float, limits: dict[str, float], levels: list[str]) -> str:
    """The lowest performance level whose limit ``value`` meets, or ``">" + last``."""
    for level in levels:
        limit = limits.get(level)
        if limit is not None and value <= limit * (1 + 1e-9):
            return level
    return f">{levels[-1]}"


def backbone(value: float, yielded: bool, a: float | None, b: float | None) -> str | None:
    """The backbone segment (B, B-C, C-E, E+) of a plastic deformation; None without a, b."""
    if a is None or b is None:
        return None
    if not yielded or value <= 0:
        return "B"
    if value <= a:
        return "B-C"
    if value <= b:
        return "C-E"
    return "E+"


@dataclass
class Evaluated:
    """One hinge worked out at a step: its parameters and demand over the run."""

    hinge: Hinge
    axis: int
    params: dict[str, Any] | None
    demand: np.ndarray  # per step
    yielded: np.ndarray  # per step, bool
    theta_y: float
    values: dict[str, Any]
    reason: str = ""


def evaluate_hinge(
    hinge: Hinge, hist: History, step: int, rules: Any, levels: list[str]
) -> Evaluated:
    """The parameters of ``hinge`` at ``step`` (the target) and its demand over the run."""
    assignment = rules.assignment
    component_id = hinge.component
    if component_id == "rcWall":
        aspect_values = variables(hinge, hist, step, 0, assignment)
        if (
            assignment.wallShearAspect is not None
            and float(aspect_values.get("aspect", math.inf)) <= assignment.wallShearAspect
            and "rcWallShear" in rules.components
        ):
            component_id = "rcWallShear"
            hinge.component = component_id
    component = rules.components.get(component_id)
    steps = len(hist.theta)
    if hinge.component in ("rcBeam", "rcWall", "rcWallShear", "steelBeam"):
        axis = 0
    else:
        last = min(step, steps - 1)
        axis = 0 if abs(hist.theta[last, 0]) >= abs(hist.theta[last, 1]) else 1
    values = variables(hinge, hist, step, axis, assignment)
    rotation = np.abs(hist.theta[:, axis])
    if component is None:
        return Evaluated(
            hinge,
            axis,
            None,
            np.zeros(steps),
            np.zeros(steps, bool),
            math.nan,
            values,
            f"the code pack gives no hinges for {component_id}",
        )
    sec = hinge.section
    # The yield chord rotation.
    if sec.concrete:
        y_step, theta_y = yield_point(rotation, hist.bar_strain, sec.fy / sec.es if sec.es else 0)
        yielded = np.arange(steps) >= y_step if y_step >= 0 else np.zeros(steps, bool)
        if y_step < 0:
            theta_y = math.nan
    else:
        e, fy = sec.es * MPA, sec.fy * MPA
        i_axis, z_axis = float(values.get("I", 0.0)), float(values.get("Z", 0.0))
        theta_y = (
            z_axis * fy * hinge.length / (assignment.steelYieldDivisor * e * i_axis)
            if i_axis > 0
            else math.nan
        )
        if hinge.component == "steelColumn":
            pye = sec.area * fy
            theta_y *= max(0.0, 1 - float(values.get("N", 0.0)) / pye) if pye > 0 else 1.0
        yielded = rotation > theta_y if not math.isnan(theta_y) else np.zeros(steps, bool)
    values["thetaY"] = theta_y
    kind = component.deformation
    if kind == "plasticRotation":
        demand = np.where(yielded, np.maximum(0.0, rotation - np.nan_to_num(theta_y)), 0.0)
    elif kind == "yieldMultiple":
        demand = (
            np.maximum(0.0, rotation - theta_y) / theta_y
            if not math.isnan(theta_y) and theta_y > 0
            else np.zeros(steps)
        )
    elif kind == "chordRotation":
        demand = rotation
    elif kind == "drift":
        demand = np.abs(hist.drift)
        yielded = demand > 0
    else:  # axialMultiple
        area, e, fy = sec.area, sec.es * MPA, sec.fy * MPA
        stretch = hist.axial
        d_t = fy * hinge.length / e if e > 0 else math.inf
        d_c = (
            float(values.get("PCL", 0.0)) * hinge.length / (e * area) if e * area > 0 else math.inf
        )
        demand = np.where(
            stretch >= 0,
            np.maximum(0.0, stretch - d_t) / d_t,
            np.maximum(0.0, -stretch - d_c) / d_c,
        )
        yielded = demand > 0
        values["deltaT"], values["deltaC"] = d_t, d_c
    params: dict[str, Any] | None
    if component.model == "table":
        params = lookup(component, values)
    elif component.model == "columnRegression" and component.regression is not None:
        values["shearRatio"] = float(values.get("V", 0.0)) / max(
            column_shear_strength(component.regression, values, sec.area), 1e-9
        )
        params = column_regression(component.regression, values, levels)
    elif component.model == "chordRotationCapacity" and component.chordRotation is not None:
        rule = component.chordRotation
        theta_um = chord_rotation_capacity(hinge, rule, values)
        limits = {k: share * theta_um for k, share in rule.shares.items()}
        # The yield level: met while the end has not yielded.
        limits[rule.yieldLevel] = (
            theta_y if not math.isnan(theta_y) else max(float(rotation.max()), 0)
        )
        params = {"a": None, "b": None, "c": None, "limits": limits, "thetaUm": theta_um}
        values["thetaUm"] = theta_um
    else:
        params = None
    reason = "" if params is not None else f"no {component_id} row covers this hinge"
    return Evaluated(hinge, axis, params, demand, yielded, theta_y, values, reason)


def _round(values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in values.items():
        if isinstance(v, float):
            out[k] = None if math.isnan(v) or math.isinf(v) else float(f"{v:.6g}")
        else:
            out[k] = v
    return out


def row_at(item: Evaluated, step: int, levels: list[str], checked: str, clause: str) -> dict:
    """The result row of an evaluated hinge at ``step`` against level ``checked``."""
    hinge = item.hinge
    s = min(step, len(item.demand) - 1)
    value = float(item.demand[s])
    yielded = bool(item.yielded[s])
    row: dict[str, Any] = {
        "hinge": hinge.id,
        "member": hinge.member,
        "end": hinge.end,
        "element": hinge.element,
        "elements": hinge.elements,
        "component": hinge.component,
        "axis": "y" if item.axis == 0 else "z",
        "yielded": yielded,
        "demand": value,
        "clause": clause,
        "variables": _round(item.values),
    }
    if item.params is None:
        row.update({"covered": False, "reason": item.reason, "ok": True, "ratio": None})
        return row
    limits = item.params["limits"]
    limit = limits.get(checked)
    ratio = value / limit if limit else (0.0 if value <= 0 else math.inf)
    row.update(
        {
            "covered": True,
            "a": item.params.get("a"),
            "b": item.params.get("b"),
            "c": item.params.get("c"),
            "limits": limits,
            "state": classify(value, limits, levels) if yielded or value > 0 else "elastic",
            "backbone": backbone(value, yielded, item.params.get("a"), item.params.get("b")),
            "ratio": ratio if math.isfinite(ratio) else None,
            "ok": bool(limit is not None and value <= limit * (1 + 1e-9)),
        }
    )
    return row


# ───────────────────────────────────── the check ─────────────────────────────────────


def library_beside(project_path: Any) -> dict[str, Any] | None:
    """The object types by id of the project the model at ``project_path`` belongs to; None
    when they cannot be read."""
    if project_path is None:
        return None
    from saengine.library.objects import ObjectLibrary

    root = Path(project_path).resolve().parent.parent
    try:
        text = (root / "04 Objects" / "objects.json").read_text(encoding="utf-8")
        objects = ObjectLibrary.model_validate_json(text)
    except (OSError, ValueError):
        return None
    return {o.id: o for o in objects.objects}


def checked_level(levels: list[str], acceptance: Any) -> str:
    wanted = getattr(acceptance, "performanceLevel", None)
    return wanted if wanted in levels else levels[-1]


def evaluate(
    project: dict[str, Any],
    results: Any,
    target: dict[str, Any],
    project_path: Any = None,
    library: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Method ``hingeRotation``: the hinges of the pushover ``results`` of the model
    ``project`` at the target displacement (``target``, :func:`saengine.fem.pushover_target.
    evaluate`) and at each hazard level's, against its performance level."""
    from saengine.fem.pushover_target import table as pushover_table

    pushover = pushover_table()
    rules = pushover.hinges if pushover is not None else None
    if rules is None:
        return {"available": False, "reason": "the code pack gives no hinges"}
    if not target.get("available"):
        return {"available": False, "reason": "no target displacement"}
    step = target.get("targetStep")
    if step is None:
        return {"available": False, "reason": "the pushover stopped before the target displacement"}
    levels = [lv.id for lv in rules.levels]
    if library is None:
        library = library_beside(project_path)
    notes: list[str] = []
    if library is None:
        notes.append(
            "The object types could not be read: the ties of the concrete members are taken as "
            "not conforming and the steel profiles as noncompact (the safe side)."
        )
    evaluated = _evaluated(project, results, int(step), rules, levels, library)
    hazards = target.get("hazards") or []
    main = hazards[0]["level"] if hazards else checked_level(levels, pushover.acceptance)
    clause_of = rules.clauses
    rows = [
        row_at(e, int(step), levels, main, clause_of.get(e.hinge.component, "")) for e in evaluated
    ]
    rows.sort(key=lambda r: (0 if r["covered"] else 1, -(r["ratio"] or 0.0)))
    checks = []
    for hazard in hazards:
        h_step = hazard.get("targetStep")
        if h_step is None:
            checks.append({**hazard, "available": False, "failed": None, "ok": None})
            continue
        h_rows = [row_at(e, int(h_step), levels, hazard["level"], "") for e in evaluated]
        failed = sum(1 for r in h_rows if r.get("covered") and not r["ok"])
        checks.append(
            {
                **hazard,
                "available": True,
                "failed": failed,
                "ok": failed == 0,
                "counts": _counts(h_rows),
                "worst": max((r["ratio"] or 0.0 for r in h_rows if r.get("covered")), default=None),
            }
        )
    uncovered = sorted({r["component"] for r in rows if not r["covered"]})
    if uncovered:
        notes.append(
            "Not covered by the code pack's hinge tables (shown, not checked): "
            + ", ".join(uncovered)
            + "."
        )
    failed = sum(1 for r in rows if r.get("covered") and not r["ok"])
    return {
        "available": True,
        "method": "hingeRotation",
        "step": int(step),
        "displacement": float(target["target"]),
        "levels": [{"id": lv.id, "label": lv.label} for lv in rules.levels],
        "checkedLevel": main,
        "rows": rows,
        "hazards": checks,
        "counts": _counts(rows),
        "failed": failed,
        "worst": rows[0]["ratio"] if rows and rows[0].get("covered") else None,
        "ok": failed == 0 and all(c.get("ok") is not False for c in checks),
        "clause": pushover.sources.get("hinges", "") or pushover.sources.get("acceptance", ""),
        "note": rules.note,
        "notes": notes,
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        key = r.get("state") or "notCovered"
        counts[key] = counts.get(key, 0) + 1
    return counts


def step_ratios(
    project: dict[str, Any],
    results: Any,
    target: dict[str, Any],
    step: int,
    project_path: Any = None,
    library: dict[str, Any] | None = None,
) -> dict[int, float]:
    """The ratio of demand to the checked level's limit of the hinges at ``step``, per element
    of the pushover model (its member's largest), for colouring the members by state."""
    found = evaluate_rows_at(project, results, target, step, project_path, library)
    ratios: dict[int, float] = {}
    for row in found:
        if not row.get("covered") or row.get("ratio") is None:
            continue
        for element in row["elements"]:
            ratios[element] = max(ratios.get(element, 0.0), float(row["ratio"]))
    return ratios


def evaluate_rows_at(
    project: dict[str, Any],
    results: Any,
    target: dict[str, Any],
    step: int,
    project_path: Any = None,
    library: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The hinge rows at any ``step`` (the parameters at the target's), checked against the
    main hazard's performance level (``library``: the object types, else read beside
    ``project_path``)."""
    from saengine.fem.pushover_target import table as pushover_table

    pushover = pushover_table()
    rules = pushover.hinges if pushover is not None else None
    if rules is None or not target.get("available") or target.get("targetStep") is None:
        return []
    levels = [lv.id for lv in rules.levels]
    hazards = target.get("hazards") or []
    main = hazards[0]["level"] if hazards else checked_level(levels, pushover.acceptance)
    if library is None:
        library = library_beside(project_path)
    evaluated = _evaluated(project, results, int(target["targetStep"]), rules, levels, library)
    return [row_at(item, step, levels, main, "") for item in evaluated]


def _evaluated(
    project: dict[str, Any],
    results: Any,
    step: int,
    rules: Any,
    levels: list[str],
    library: dict[str, Any] | None,
) -> list[Evaluated]:
    """Every hinge of the model worked out with its parameters at ``step``."""
    found = []
    for hinge in assign(project, library):
        hist = history(hinge, results)
        if hist is not None:
            found.append(evaluate_hinge(hinge, hist, step, rules, levels))
    return found


# ───────────────────────── P5: hinges over a nonlinear time history ─────────────────────────


class _Lazy:
    """A read-only mapping whose values are worked out (and kept) on first use; true even
    before, as the pushover results' dictionaries are where they hold anything."""

    def __init__(self, make: Any) -> None:
        self._make = make
        self._cache: dict[int, Any] = {}

    def get(self, key: int, default: Any = None) -> Any:
        if key not in self._cache:
            try:
                self._cache[key] = self._make(int(key))
            except (KeyError, OSError, ValueError):
                self._cache[key] = None
        found = self._cache[key]
        return default if found is None else found

    def __bool__(self) -> bool:
        return True


def _strains(coords: np.ndarray, deformation: np.ndarray, signs: tuple[float, float]) -> np.ndarray:
    y, z = coords[:, 0][None, :], coords[:, 1][None, :]
    return (
        deformation[:, :1] + signs[0] * y * deformation[:, 1:2] + signs[1] * z * deformation[:, 2:3]
    )


def section_signs(
    coords: np.ndarray, deformation: np.ndarray, peaks: np.ndarray
) -> tuple[float, float]:
    """The signs (s1, s2) of ε = ε0 + s1·y·κ1 + s2·z·κ2 (the section's deformations ε0, κ1,
    κ2 in its order) that best give the fibres' recorded least and largest strains."""
    best, best_error = (-1.0, 1.0), math.inf
    for s1 in (-1.0, 1.0):
        for s2 in (-1.0, 1.0):
            strain = _strains(coords, deformation, (s1, s2))
            error = float(
                np.abs(strain.min(axis=0) - peaks[:, 3]).sum()
                + np.abs(strain.max(axis=0) - peaks[:, 4]).sum()
            )
            if error < best_error:
                best, best_error = (s1, s2), error
    return best


def _fibres_from_sections(results: Any, element: int, end: str) -> np.ndarray | None:
    """The fibres of an end section of a time history run, (steps, fibres, 5): y, z, area, 0,
    strain, rebuilt from the section's deformations at every step and the fibres' places of the
    fibre peaks (``TransientCase.record_section_deformations`` and ``record_fibre_peaks``)."""
    deformation = results.element_section_deformations(element).get(end)
    peaks = results.element_fibre_peaks(element).get(end)
    if deformation is None or peaks is None or deformation.ndim != 2 or deformation.shape[1] < 3:
        return None
    strain = _strains(peaks[:, :2], deformation, section_signs(peaks[:, :2], deformation, peaks))
    steps, count = strain.shape
    out = np.zeros((steps, count, 5))
    out[:, :, 0] = peaks[:, 0][None, :]
    out[:, :, 1] = peaks[:, 1][None, :]
    out[:, :, 2] = peaks[:, 2][None, :]
    out[:, :, 4] = strain
    return out


@dataclass
class TransientHingeResults:
    """A time history run read as the pushover results the hinges take (:func:`history`):
    node displacements, element forces and the end sections' fibres per step, worked out on
    first use."""

    node_disp: Any
    element_forces: Any
    element_start_fibers: Any
    element_end_fibers: Any


def transient_results(results: Any) -> TransientHingeResults:
    """The hinge view of OpenSees Studio's ``TransientResults`` of a run that kept the section
    deformations and the fibre peaks."""
    return TransientHingeResults(
        node_disp=_Lazy(results.node_disp_history),
        element_forces=_Lazy(results.element_force_history),
        element_start_fibers=_Lazy(lambda e: _fibres_from_sections(results, e, "start")),
        element_end_fibers=_Lazy(lambda e: _fibres_from_sections(results, e, "end")),
    )


def history_rows(
    project: dict[str, Any],
    results: Any,
    level: str | None,
    library: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The hinges of the pack's ``pushover.hinges`` over one time history run (``results``:
    :func:`transient_results`): each hinge's parameters at the step of its largest chord
    rotation, its peak deformation over the record against the limit of ``level`` (empty or
    unknown: the last level). Returns the rows (:func:`row_at`, with ``step``) and notes."""
    rules = table()
    if rules is None:
        return [], ["the code pack gives no hinges"]
    levels = [lv.id for lv in rules.levels]
    checked = level if level in levels else levels[-1]
    rows: list[dict[str, Any]] = []
    for hinge in assign(project, library):
        hist = history(hinge, results)
        if hist is None or not len(hist.theta):
            continue
        peak = int(np.argmax(np.abs(hist.theta).max(axis=1)))
        item = evaluate_hinge(hinge, hist, peak, rules, levels)
        step = int(np.argmax(item.demand)) if len(item.demand) else 0
        row = row_at(item, step, levels, checked, rules.clauses.get(item.hinge.component, ""))
        row["step"] = step
        row["level"] = checked
        rows.append(row)
    notes = []
    uncovered = sorted({r["component"] for r in rows if not r.get("covered")})
    if uncovered:
        notes.append(
            "Not covered by the code pack's hinge tables (shown, not checked): "
            + ", ".join(uncovered)
        )
    return rows, notes

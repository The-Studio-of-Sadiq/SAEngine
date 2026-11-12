"""The analysis model as a neutral frame model: what the exchange writers (``.s2k``, ``.std``, SAF,
SDNF, CIS/2, the web viewer) write, each in its own format.

Alpha 9 L12. The e2k exporter (:mod:`saengine.exporters.etabs`) writes the *building* (stories,
objects, area loads) because its target rebuilds the analysis model from them. The formats here are
written from SAEngine's own *analysis model* instead (``08 FEM/model.osmodel``, derived exactly as
Run All's Derive step derives it, :func:`saengine.rpc.handlers.derive_fem`): joints, members,
plates, sections, materials, supports, the load cases with their loads and the combinations of 02
Project Settings. So the other program analyses the same model SAEngine analyses, loads and all.

:func:`from_osmodel` reads that model into an :class:`AnalyticalModel` (SI: m, N, Pa, kg/m³; Z up)
and fills a :class:`ExchangeReport` with what it could not carry:

- members (``ElasticBeamColumn``) with their sections; a section's object type (its name starts
  with the type id, :mod:`saengine.fem.derive`) gives the shape and dimensions (rectangle, circle,
  I, channel, angle, tee, box, pipe) and the material; otherwise the section is written by its
  properties (``general``: A, Iy, Iz, J);
- plates (``Shell``) with their thickness sections; solids are left out (reported);
- the pinned ends of simple steel connections (``ZeroLength`` links between a node and its twin)
  become moment releases at the member's end on the merged node;
- rigid diaphragms (``RigidDiaphragm`` constraints) are kept as diaphragm groups with their master
  node (a format without diaphragms reports what that means);
- element loads (OpenSees ``beamUniform`` Wx, Wy, Wz in the element's local axes) are turned into
  global components with the local axes the runner gives (``vecxz`` (1, 0, 0) for a vertical member,
  (0, 0, 1) for any other, unless the element states its own);
- the lumped nodal masses (SAEngine's mass source) and the modal analysis' number of modes are
  kept (:attr:`AnalyticalModel.masses`, :attr:`AnalyticalModel.modes`): the ``.s2k`` and
  ``.std`` writers write them as the target's mass source and modal case, the others report
  them as left out (:func:`count_written`);
- rigid end offsets and the staged dead load are not carried (reported).

The analysis model splits members at every mesh node (500 mm) and at every node another member
meets; :func:`joined_members` joins the segments back into members for the formats of analysis
programs that mesh their own frames (``.s2k``, ``.std``); SDNF and the web viewer join them as
physical members (:func:`physical_members`). The writers count what they write
(:func:`count_written`).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.exporters.etabs import ExportReport, _words

#: Gravitational acceleration [m/s²].
G = 9.80665
#: Section kinds the writers know by dimensions (else ``general``).
SHAPES = ("rectangle", "circle", "I", "U", "L", "T", "rectangleHollow", "circleHollow", "general")


# ─────────────────────────────────────────── report ───────────────────────────────────────────


class ExchangeReport(ExportReport):
    """:class:`saengine.exporters.etabs.ExportReport` for another format: the same dictionary
    (``saengine.exportReport/1``), its Markdown titled with the format's name."""

    def __init__(self, format_name: str, extension: str, file: str | None = None) -> None:
        super().__init__(file)
        self.source["program"] = format_name
        self.format_name = format_name
        self.extension = extension

    def to_markdown(self) -> str:
        target = self.source
        title = (
            f"{self.format_name} export: {target.get('project') or target.get('file') or 'project'}"
        )
        out = [f"# {title}", ""]
        if target.get("file"):
            out += [f"File: `{target['file']}`", ""]
        out += ["## Written", ""]
        out += [f"- {n} {_words(kind)}" for kind, n in self.imported.items() if n] or ["- nothing"]
        if self.warnings:
            out += ["", "## Warnings", ""]
            out += [f"- {w}" for w in self.warnings]
        for heading, entries in (
            (f"Left out (not in the {self.extension} file)", self.skipped),
            ("Approximated (in the file, not exactly as in SAEngine)", self.approximated),
        ):
            if entries:
                out += ["", f"## {heading}", ""]
            for item in entries:
                examples = ", ".join(item["examples"])
                count = f" ({item['count']})" if item["count"] > 1 else ""
                out.append(f"- {item['what']}{count}" + (f": {examples}" if examples else ""))
        left = {k: v for k, v in self.not_carried.items() if abs(v) > 1e-6}
        if left:
            out += ["", "## Loads left out", ""]
            out += [f"- {case}: {v:.1f} kN" for case, v in left.items()]
        if not (self.skipped or self.approximated or left):
            out += ["", "Nothing was left out or approximated."]
        return "\n".join(out) + "\n"


# ─────────────────────────────────────────── model ───────────────────────────────────────────


@dataclass
class Node:
    id: int
    xyz: tuple[float, float, float]  # m
    #: UX, UY, UZ, RX, RY, RZ fixed.
    restraint: tuple[bool, bool, bool, bool, bool, bool] = (False,) * 6

    @property
    def supported(self) -> bool:
        return any(self.restraint)


@dataclass
class Material:
    name: str
    kind: str  # concrete, steel, other
    E: float  # Pa
    nu: float = 0.2
    density: float = 0.0  # kg/m³
    fc: float | None = None  # Pa
    fy: float | None = None  # Pa
    fu: float | None = None  # Pa

    @property
    def G(self) -> float:
        return self.E / (2 * (1 + self.nu))

    @property
    def unit_weight(self) -> float:
        """N/m³."""
        return self.density * G


@dataclass
class Section:
    """A member section: ``shape`` one of :data:`SHAPES`, ``dims`` its dimensions [m] by
    SAEngine's profile names (``xDim``, ``yDim``, ``radius``, ``overallDepth``...), and its
    properties A [m²], I33 (major, about the local axis the depth bends about), I22, J [m⁴]."""

    name: str
    material: str
    shape: str
    dims: dict[str, float]
    A: float
    I33: float
    I22: float
    J: float
    #: The object type it comes from (04 Objects), when known.
    object_type: str | None = None
    #: A table name of the shape (IPE300, W14X90) when the profile is one.
    designation: str | None = None

    @property
    def depth(self) -> float | None:
        d = self.dims
        if self.shape == "rectangle":
            return d.get("yDim")
        if self.shape in ("circle", "circleHollow"):
            return 2 * d.get("radius", 0.0) or None
        if self.shape == "I":
            return d.get("overallDepth")
        if self.shape == "rectangleHollow":
            return d.get("yDim")
        return d.get("depth")

    @property
    def width(self) -> float | None:
        d = self.dims
        if self.shape in ("rectangle", "rectangleHollow"):
            return d.get("xDim")
        if self.shape in ("circle", "circleHollow"):
            return 2 * d.get("radius", 0.0) or None
        if self.shape == "I":
            return d.get("overallWidth")
        return d.get("flangeWidth") or d.get("width")


@dataclass
class PlateSection:
    name: str
    material: str
    thickness: float  # m
    kind: str = "shell"  # slab, wall, shell


@dataclass
class Member:
    id: str
    i: int
    j: int
    section: str
    #: Right-hand rotation [°] about the member axis (i to j) of the section's depth direction
    #: (the profile's y) from its default: vertical for a beam or brace, along global Y for a
    #: vertical member (the analysis model's local axes, :func:`local_axes`).
    rotation: float = 0.0
    #: Released actions at end i and end j by the writers' common names: P, V2, V3, T, M2, M3.
    releases: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset())
    kind: str = "beam"  # column, beam, brace
    #: The building-model element it belongs to (members of one element share it).
    source: str = ""


@dataclass
class Plate:
    id: str
    nodes: list[int]
    section: str
    source: str = ""


@dataclass
class Diaphragm:
    name: str
    master: int
    nodes: list[int]


@dataclass
class LoadCase:
    """``kind``: D, SD, L, Lr, W, E, other (the target's load pattern type). ``nodal``: node ->
    six global components [N, N·m]; ``uniform``: member -> three global components [N/m] over
    its whole length."""

    name: str
    kind: str
    title: str = ""
    nodal: dict[int, list[float]] = field(default_factory=dict)
    uniform: dict[str, list[float]] = field(default_factory=dict)
    #: Member -> partial uniform loads: (three global components [N/m], from, to [m from end
    #: i]): the loads of analysis mesh segments joined into one member (:func:`joined_members`).
    partial: dict[str, list[tuple[list[float], float, float]]] = field(default_factory=dict)
    #: Member -> point loads: (six global components [N, N·m], distance [m] from end i): the
    #: nodal loads of the mesh nodes inside a joined member.
    points: dict[str, list[tuple[list[float], float]]] = field(default_factory=dict)

    def title_text(self) -> str:
        """The case's name and title, the name not repeated (case ``D`` titled ``D: Dead`` is
        ``D: Dead``, never ``D: D: Dead``)."""
        title = (self.title or "").strip()
        if not title or title == self.name:
            return self.name
        if title.startswith((self.name + ":", self.name + " ")):
            return title
        return f"{self.name}: {title}"


@dataclass
class AnalyticalModel:
    name: str
    nodes: dict[int, Node] = field(default_factory=dict)
    materials: dict[str, Material] = field(default_factory=dict)
    sections: dict[str, Section] = field(default_factory=dict)
    plate_sections: dict[str, PlateSection] = field(default_factory=dict)
    members: list[Member] = field(default_factory=list)
    plates: list[Plate] = field(default_factory=list)
    diaphragms: list[Diaphragm] = field(default_factory=list)
    cases: list[LoadCase] = field(default_factory=list)
    #: (name, {case name: factor}) in the settings' order.
    combinations: list[tuple[str, dict[str, float]]] = field(default_factory=list)
    #: Grid lines: (axis "X" or "Y", label, position [m]).
    grids: list[tuple[str, str, float]] = field(default_factory=list)
    #: Story levels: (name, elevation [m]).
    levels: list[tuple[str, float]] = field(default_factory=list)
    #: The lumped masses of the analysis model, node -> (MX, MY, MZ [kg], IX, IY, IZ [kg·m²]):
    #: the masses SAEngine's modal analysis uses (its mass source, formed from the loads).
    masses: dict[int, list[float]] = field(default_factory=dict)
    #: The modes of SAEngine's modal analysis (0: the model has no modal analysis).
    modes: int = 0

    def used_nodes(self) -> list[int]:
        """The nodes a member or plate uses, or that carry a support or a load, in id order."""
        used: set[int] = set()
        for m in self.members:
            used.update((m.i, m.j))
        for p in self.plates:
            used.update(p.nodes)
        for n in self.nodes.values():
            if n.supported:
                used.add(n.id)
        for d in self.diaphragms:
            used.add(d.master)
        for c in self.cases:
            used.update(c.nodal)
        used.update(n for n, mass in self.masses.items() if any(mass))
        return sorted(u for u in used if u in self.nodes)

    def length(self, member: Member) -> float:
        a, b = self.nodes[member.i].xyz, self.nodes[member.j].xyz
        return math.dist(a, b)


# ─────────────────────────────────────── local axes ───────────────────────────────────────


def local_axes(
    a: tuple[float, float, float], b: tuple[float, float, float], vecxz: Any = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The local x, y, z of an OpenSees frame element from ``a`` to ``b`` (the runner's choice of
    ``vecxz`` when not given: (1, 0, 0) for a vertical element, (0, 0, 1) for any other):
    y = vecxz × x, z = x × y."""
    x = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    x /= np.linalg.norm(x)
    if vecxz is None:
        vecxz = (1.0, 0.0, 0.0) if abs(x[2]) > 0.999 else (0.0, 0.0, 1.0)
    v = np.asarray(vecxz, dtype=float)
    y = np.cross(v, x)
    y /= np.linalg.norm(y)
    z = np.cross(x, y)
    return x, y, z


def is_vertical(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    d = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    length = float(np.linalg.norm(d))
    return length > 0 and abs(d[2]) / length > 0.999


# ─────────────────────────────────────── from the osmodel ───────────────────────────────────────

_CASE_KINDS = {
    "D": "D",
    "SD": "SD",
    "L": "L",
    "Lr": "Lr",
    "WX": "W",
    "WY": "W",
    "EX": "E",
    "EY": "E",
    "F": "other",
    "H": "other",
    "R": "other",
    "S": "other",
    "T": "other",
}
_PROFILE_KEYS = {
    "rectangle": ("xDim", "yDim"),
    "circle": ("radius",),
    "I": ("overallWidth", "overallDepth", "webThickness", "flangeThickness"),
    "U": ("depth", "flangeWidth", "webThickness", "flangeThickness"),
    "T": ("depth", "flangeWidth", "webThickness", "flangeThickness"),
    "L": ("depth", "width", "thickness"),
    "rectangleHollow": ("xDim", "yDim", "wallThickness"),
    "circleHollow": ("radius", "wallThickness"),
}


def _source(name: str) -> str:
    """The building-model element of an analysis element's name (``B12#3`` -> ``B12``)."""
    return re.sub(r"#\d+$", "", name or "").split("/")[0]


def _object_of(section_name: str, types: dict[str, Any]) -> Any:
    """The object type whose id starts the derived section's name (the longest match)."""
    best = None
    for type_id, obj in types.items():
        if (section_name == type_id or section_name.startswith(type_id + " ")) and (
            best is None or len(type_id) > len(best[0])
        ):
            best = (type_id, obj)
    return best[1] if best else None


def _material_of(mat: Any) -> Material:
    mech = mat.mechanical
    category = getattr(mat, "category", "") or ""
    kind = "concrete" if category == "concrete" else "steel" if category == "steel" else "other"
    concrete = getattr(mat, "concrete", None)
    steel = getattr(mat, "steel", None)
    return Material(
        name=mat.id,
        kind=kind,
        E=(mech.E or 0.0) * 1e6,
        nu=mech.nu
        if getattr(mech, "nu", None) is not None
        else (0.2 if kind == "concrete" else 0.3),
        density=mech.density or 0.0,
        fc=(concrete.fc * 1e6) if concrete is not None and getattr(concrete, "fc", None) else None,
        fy=(steel.fy * 1e6) if steel is not None and getattr(steel, "fy", None) else None,
        fu=(steel.fu * 1e6) if steel is not None and getattr(steel, "fu", None) else None,
    )


def from_osmodel(
    osmodel: dict[str, Any],
    objects: Any,
    materials: Any,
    settings: Any = None,
    *,
    name: str = "SAEngine",
    report: ExchangeReport | None = None,
    grids: list[tuple[str, str, float]] | None = None,
) -> AnalyticalModel:
    """The neutral model of a derived analysis model (the ``08 FEM`` project JSON). ``objects``,
    ``materials``: the 04 Objects and 03 Materials libraries (pydantic), for the sections' shapes
    and the materials' strengths; ``settings``: 02 Project Settings, for the combinations."""
    report = report or ExchangeReport("Exchange", "")
    model = AnalyticalModel(name=name)
    types = {o.id: o for o in getattr(objects, "objects", [])}
    mats = {m.id: m for m in getattr(materials, "materials", [])}

    # ── nodes, with the twins of the pinned ends merged ──
    for n in osmodel.get("nodes", []):
        x, y, z = (float(v) for v in n["coords"][:3])
        r = tuple(bool(v) for v in (list(n.get("restraint") or []) + [False] * 6)[:6])
        model.nodes[int(n["id"])] = Node(int(n["id"]), (x, y, z), r)  # type: ignore[arg-type]
    twin_of: dict[int, int] = {}
    for e in osmodel.get("elements", []):
        if e.get("type") == "ZeroLength" and len(e.get("nodes", [])) == 2:
            a, b = (int(v) for v in e["nodes"])
            twin_of[b] = a

    def merged(node: int) -> int:
        seen = 0
        while node in twin_of and seen < 10:
            node, seen = twin_of[node], seen + 1
        return node

    # ── the lumped masses (SAEngine's mass source) and the modal analysis ──
    for n in osmodel.get("nodes", []):
        mass = [float(v) for v in (list(n.get("mass") or []) + [0.0] * 6)[:6]]
        if any(mass):
            prev = model.masses.setdefault(merged(int(n["id"])), [0.0] * 6)
            for k in range(6):
                prev[k] += mass[k]
    for a in osmodel.get("analyses", []):
        if a.get("type") == "Modal":
            model.modes = max(model.modes, int(a.get("n_modes") or 0))

    # ── sections and materials ──
    used_materials: set[str] = set()
    sections_by_id: dict[int, dict[str, Any]] = {
        int(s["id"]): s for s in osmodel.get("sections", [])
    }
    member_sections: dict[int, str] = {}
    plate_sections: dict[int, str] = {}
    turned: set[int] = set()
    for sid, s in sections_by_id.items():
        obj = _object_of(str(s.get("name", "")), types)
        material = mats.get(obj.material) if obj is not None and obj.material else None
        if s.get("type") == "ElasticMembranePlateSection":
            mname = material.id if material is not None else f"E{round(float(s.get('E', 0)) / 1e6)}"
            if material is None and mname not in model.materials:
                model.materials[mname] = Material(
                    mname, "other", float(s.get("E", 0.0)), float(s.get("nu", 0.2))
                )
            used_materials.add(mname)
            pname = _unique(_clean(str(s.get("name") or f"PL{sid}")), model.plate_sections)
            kind = getattr(obj, "kind", "shell") if obj is not None else "shell"
            model.plate_sections[pname] = PlateSection(pname, mname, float(s["h"]), str(kind))
            plate_sections[sid] = pname
            if s.get("Ep_mod") is not None:
                report.approximate(
                    "plate bending modifiers (cracked or ribbed slabs) written as the full plate",
                    pname,
                )
            continue
        if s.get("type") != "ElasticSection":
            report.skip("sections that are not elastic", str(s.get("name")))
            continue
        if material is not None:
            mname = material.id
        else:
            mname = f"E{round(float(s.get('E', 0)) / 1e6)}"
            if mname not in model.materials:
                E = float(s.get("E", 0.0))
                Gm = float(s.get("G", 0.0)) or E / 2.4
                model.materials[mname] = Material(mname, "other", E, max(0.0, E / (2 * Gm) - 1))
            report.approximate("sections without their object type: material by E only", mname)
        used_materials.add(mname)
        sname = _unique(_clean(str(s.get("name") or f"S{sid}")), model.sections)
        shape, dims, designation = "general", {}, None
        profile = getattr(obj, "profile", None) if obj is not None else None
        if profile is not None:
            p = profile.model_dump() if hasattr(profile, "model_dump") else dict(profile)
            keys = _PROFILE_KEYS.get(str(p.get("shape")))
            if keys and all(p.get(k) for k in keys):
                shape = str(p["shape"])
                dims = {k: float(p[k]) / 1000 for k in keys}
                if shape in ("I", "U", "L", "T", "rectangleHollow", "circleHollow"):
                    try:
                        from saengine.exporters.etabs import designation as table_name

                        designation = table_name(p)
                    except Exception:  # noqa: BLE001 - a lookup, never a reason to fail
                        designation = None
        if "(modified)" in sname:
            report.approximate(
                "member stiffness modifiers kept in the section properties only", sname
            )
        vertical = " column" in str(s.get("name", ""))
        iz, iy = float(s.get("Iz", 0.0)), float(s.get("Iy", 0.0))
        # derive: Iz carries the profile's ixx for a vertical member, Iy for a horizontal one; a
        # quarter-turned column's section has them swapped: the profile's own convention here,
        # and the member turned by 90° instead.
        i33, i22 = (iz, iy) if vertical else (iy, iz)
        if "(rotated)" in str(s.get("name", "")):
            i33, i22 = i22, i33
            turned.add(sid)
        model.sections[sname] = Section(
            sname,
            mname,
            shape,
            dims,
            float(s.get("A", 0.0)),
            i33,
            i22,
            float(s.get("J", 0.0)),
            obj.id if obj is not None else None,
            designation,
        )
        member_sections[sid] = sname
        if shape == "general":
            report.approximate("sections written by their properties (no shape)", sname)
    for mname in sorted(used_materials):
        if mname in mats and mname not in model.materials:
            model.materials[mname] = _material_of(mats[mname])
    # The bars of RC members are not part of these formats' analysis models.
    if any(getattr(o, "reinforcement", None) for o in types.values()):
        report.skip("reinforcement of RC members (designed in SAEngine)", None)

    # ── elements ──
    element_ids: dict[int, str] = {}
    vecxz_of: dict[str, Any] = {}
    # One name space for members and plates (the .s2k file's frames and areas, SAF's members).
    taken_ids: set[str] = set()
    for e in osmodel.get("elements", []):
        etype = e.get("type")
        eid = int(e["id"])
        label = _clean(str(e.get("name") or eid)) or str(eid)
        if etype in ("ElasticBeamColumn", "ForceBeamColumn", "DispBeamColumn"):
            sname = member_sections.get(int(e.get("section_id", 0)))
            if sname is None:
                report.skip("members without an elastic section", label)
                continue
            raw = [int(v) for v in e["nodes"]]
            i, j = merged(raw[0]), merged(raw[1])
            if i == j:
                report.skip("members of zero length", label)
                continue
            mid = _unique_member(label, taken_ids)
            a, b = model.nodes[i].xyz, model.nodes[j].xyz
            vertical = is_vertical(a, b)
            kind = "column" if vertical else ("beam" if abs(a[2] - b[2]) < 1e-3 else "brace")
            rotation = 0.0
            if e.get("vecxz") is not None:
                vecxz_of[mid] = e["vecxz"]
                rotation = _rotation(a, b, e["vecxz"])
            if int(e.get("section_id", 0)) in turned:
                rotation = (rotation + 90.0) % 360.0
            ends = [set(), set()]
            for k, node in enumerate(raw[:2]):
                if node in twin_of:
                    ends[k] |= {"M2", "M3"}
                    # one entry per pinned end: the report counts the ends
                    report.approximate(
                        "pinned member ends (zero-length links of simple connections) as end "
                        "releases",
                        f"{label} {'i' if k == 0 else 'j'}",
                    )
            model.members.append(
                Member(
                    mid,
                    i,
                    j,
                    sname,
                    rotation,
                    (frozenset(ends[0]), frozenset(ends[1])),
                    kind,
                    _source(str(e.get("name", ""))),
                )
            )
            element_ids[eid] = mid
            if e.get("joint_offsets"):
                report.approximate("rigid end zones left out (members run joint to joint)", mid)
        elif etype == "Shell":
            pname = plate_sections.get(int(e.get("section_id", 0)))
            if pname is None:
                report.skip("plates without an elastic plate section", label)
                continue
            nodes = [merged(int(v)) for v in e["nodes"]]
            pid = _unique_member(label, taken_ids)
            model.plates.append(Plate(pid, nodes, pname, _source(str(e.get("name", "")))))
            element_ids[eid] = pid
        elif etype == "ZeroLength":
            continue
        else:
            report.skip(f"{etype or 'other'} elements", label)

    # ── diaphragms ──
    for c in osmodel.get("mp_constraints", []):
        if c.get("type") == "RigidDiaphragm":
            master = int(c.get("master_node") or c.get("retained_node") or c.get("master") or 0)
            slaves = sorted(
                {merged(int(v)) for v in c.get("slave_nodes") or c.get("constrained_nodes") or []}
                - {master}
            )
            if master in model.nodes and slaves:
                model.diaphragms.append(Diaphragm(f"D{len(model.diaphragms) + 1}", master, slaves))
        else:
            report.skip("multi-point constraints other than rigid diaphragms", str(c.get("type")))

    # ── load cases ──
    members_by_id = {m.id: m for m in model.members}
    labels = {}
    for a in osmodel.get("analyses", []):
        if a.get("type") == "Static" and len(a.get("pattern_ids") or []) == 1:
            labels[int(a["pattern_ids"][0])] = str(a.get("name") or "")
    for p in osmodel.get("load_patterns", []):
        case_name = str(p.get("name") or p.get("id"))
        if case_name.startswith("D, stage"):
            report.skip("construction-stage dead loads (the D case carries the full dead load)")
            continue
        if re.fullmatch(r"TO\d+", case_name):
            # saengine.fem.tension_only: unit release cases of SAEngine's own combination rule.
            report.skip("tension-only release cases (SAEngine's combination method)", case_name)
            continue
        kind = _CASE_KINDS.get(case_name, "other")
        case = LoadCase(case_name, kind, labels.get(int(p.get("id", 0)), ""))
        for nl in p.get("nodal_loads", []):
            node = merged(int(nl["node_id"]))
            forces = [float(v) for v in (list(nl.get("forces") or []) + [0.0] * 6)[:6]]
            if node not in model.nodes:
                continue
            prev = case.nodal.setdefault(node, [0.0] * 6)
            for k in range(6):
                prev[k] += forces[k]
        for el in p.get("element_loads", []):
            mid = element_ids.get(int(el.get("element_id", 0)))
            member = members_by_id.get(mid) if mid else None
            if member is None:
                report.skip("element loads on elements not exported", case_name)
                continue
            a, b = model.nodes[member.i].xyz, model.nodes[member.j].xyz
            x, y, z = local_axes(a, b, vecxz_of.get(member.id))
            w = (
                x * float(el.get("wx", 0.0))
                + y * float(el.get("wy", 0.0))
                + z * float(el.get("wz", 0.0))
            )
            prev = case.uniform.setdefault(member.id, [0.0, 0.0, 0.0])
            for k in range(3):
                prev[k] += float(w[k])
        model.cases.append(case)
        report.carried[case_name] += _total(model, case) / 1000
    present = {c.name for c in model.cases}
    if settings is not None:
        from saengine.fem.combinations import combination_factors

        for combo in getattr(settings, "combinations", None) or []:
            factors = {
                k: v for k, v in combination_factors(combo, present).items() if k in present and v
            }
            if factors:
                model.combinations.append((str(combo.name), factors))
            else:
                report.skip("combinations of cases the model has no loads in", str(combo.name))
    model.grids = list(grids or [])
    return model


def _total(model: AnalyticalModel, case: LoadCase) -> float:
    """The size of a case's loads [N]: the length of the resultant force vector."""
    total = np.zeros(3)
    for forces in case.nodal.values():
        total += np.asarray(forces[:3])
    members = {m.id: m for m in model.members}
    for mid, w in case.uniform.items():
        total += np.asarray(w) * model.length(members[mid])
    return float(np.linalg.norm(total))


def _rotation(a: Any, b: Any, vecxz: Any) -> float:
    """The right-hand angle [°] about the member axis (local x) from the default local z (the
    runner's vecxz) to the element's own: z1 = cos θ z0 + sin θ (x × z0), and x × z0 = -y0."""
    _, y0, z0 = local_axes(a, b)
    _, _, z1 = local_axes(a, b, vecxz)
    angle = math.degrees(math.atan2(-float(np.dot(z1, y0)), float(np.dot(z1, z0))))
    return round(angle % 360.0, 6)


def _clean(text: str) -> str:
    return re.sub(r'["\s,;=]+', "_", text).strip("_")[:60]


def _unique(name: str, taken: dict[str, Any]) -> str:
    out, k = name or "S", 2
    while out in taken:
        out, k = f"{name}_{k}", k + 1
    return out


def _unique_member(label: str, taken: set[str]) -> str:
    """``label``, or ``label_2``, ``label_3``... when taken; recorded in ``taken``."""
    out, k = label, 2
    while out in taken:
        out, k = f"{label}_{k}", k + 1
    taken.add(out)
    return out


def numbering(model: AnalyticalModel) -> tuple[dict[int, int], dict[str, int], dict[str, int]]:
    """Consecutive numbers from 1 for the formats that number joints and members (STAAD, SDNF):
    nodes in id order, members then plates in model order."""
    nodes = {n: k for k, n in enumerate(model.used_nodes(), start=1)}
    members = {m.id: k for k, m in enumerate(model.members, start=1)}
    plates = {p.id: k for k, p in enumerate(model.plates, start=len(members) + 1)}
    return nodes, members, plates


@dataclass
class PhysicalMember:
    """A building member as one piece: the analysis members of one building-model element and
    section joined end to end along a straight line (a beam split at every column or mesh node
    is one piece again)."""

    id: str
    start: tuple[float, float, float]  # m
    end: tuple[float, float, float]
    section: str
    rotation: float
    kind: str
    releases: tuple[frozenset[str], frozenset[str]]
    parts: list[str]


def _chains(model: AnalyticalModel) -> list[tuple[str, list[Member]]]:
    """The members of ``model`` in chains: one building-model element and section joined end to
    end along a straight line, with the element's name; in model order."""
    groups: dict[tuple[str, str, float], list[Member]] = defaultdict(list)
    order: list[tuple[str, str, float]] = []
    for m in model.members:
        key = (m.source or m.id, m.section, round(m.rotation, 6))
        if key not in groups:
            order.append(key)
        groups[key].append(m)
    out: list[tuple[str, list[Member]]] = []
    for key in order:
        pending = list(groups[key])
        while pending:
            chain = [pending.pop(0)]
            grown = True
            while grown:
                grown = False
                for other in list(pending):
                    if other.i == chain[-1].j and _collinear(model, chain[-1], other):
                        chain.append(other)
                    elif other.j == chain[0].i and _collinear(model, other, chain[0]):
                        chain.insert(0, other)
                    else:
                        continue
                    pending.remove(other)
                    grown = True
            out.append((key[0], chain))
    return out


def physical_members(model: AnalyticalModel) -> list[PhysicalMember]:
    """The members of ``model`` joined into pieces (:class:`PhysicalMember`), in model order."""
    out: list[PhysicalMember] = []
    names: set[str] = set()
    for source, chain in _chains(model):
        if chain:
            first, last = chain[0], chain[-1]
            name = _unique_member(source, names)
            out.append(
                PhysicalMember(
                    name,
                    model.nodes[first.i].xyz,
                    model.nodes[last.j].xyz,
                    first.section,
                    first.rotation,
                    first.kind,
                    (first.releases[0], last.releases[1]),
                    [m.id for m in chain],
                )
            )
    return out


def _collinear(model: AnalyticalModel, a: Member, b: Member) -> bool:
    """Whether member ``b`` continues member ``a`` (``a.j == b.i``) in the same direction."""
    pa, pb = np.asarray(model.nodes[a.i].xyz), np.asarray(model.nodes[a.j].xyz)
    pc = np.asarray(model.nodes[b.j].xyz)
    u, v = pb - pa, pc - pb
    nu, nv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
    return nu > 0 and nv > 0 and float(np.dot(u, v)) / (nu * nv) > 0.9999


def joined_members(model: AnalyticalModel, report: ExchangeReport | None = None) -> AnalyticalModel:
    """``model`` with its analysis mesh segments joined back into members, for the formats of
    an analysis program that meshes its own members (``.s2k``, ``.std``): a beam the analysis
    model splits every 500 mm and at every node it meets is one frame again, from support to
    support (a member is still cut where another member, a plate, a support, a diaphragm master,
    an end release or a nodal moment meets it). On a joined member the segments' uniform loads
    become one uniform load when they are all the same, else partial uniform loads over their
    lengths; the nodal forces at the mesh nodes inside become point loads; the lumped masses of
    those nodes go to the member's ends by the lever rule; the nodes leave the diaphragms. A
    model with nothing to join is returned as it is."""
    report = report or ExchangeReport("Exchange", "")
    ends: dict[int, int] = defaultdict(int)
    for m in model.members:
        ends[m.i] += 1
        ends[m.j] += 1
    fixed_nodes = {n for p in model.plates for n in p.nodes}
    fixed_nodes |= {d.master for d in model.diaphragms}
    fixed_nodes |= {n.id for n in model.nodes.values() if n.supported}
    for c in model.cases:
        fixed_nodes |= {n for n, f in c.nodal.items() if any(abs(v) > 0 for v in f[3:])}

    def inner(a: Member, b: Member) -> bool:
        """Whether the node between ``a`` and ``b`` (``a.j == b.i``) can go."""
        node = a.j
        return (
            ends[node] == 2 and node not in fixed_nodes and not a.releases[1] and not b.releases[0]
        )

    pieces: list[tuple[str, list[Member]]] = []
    for source, chain in _chains(model):
        start = 0
        for k in range(1, len(chain) + 1):
            if k == len(chain) or not inner(chain[k - 1], chain[k]):
                pieces.append((source, chain[start:k]))
                start = k
    if all(len(p) == 1 for _, p in pieces):
        return model
    taken = {p.id for p in model.plates}
    taken |= {chain[0].id for _, chain in pieces if len(chain) == 1}
    new_members: list[Member] = []
    removed: set[int] = set()
    cases = [
        LoadCase(c.name, c.kind, c.title, {n: list(f) for n, f in c.nodal.items()}, {}, {}, {})
        for c in model.cases
    ]
    masses = {n: list(m) for n, m in model.masses.items()}
    segments = 0
    for source, chain in pieces:
        if len(chain) == 1:
            m = chain[0]
            new_members.append(m)
            for case, old in zip(cases, model.cases, strict=True):
                if m.id in old.uniform:
                    case.uniform[m.id] = list(old.uniform[m.id])
            continue
        first, last = chain[0], chain[-1]
        name = _unique_member(source or first.id, taken)
        joined = Member(
            name,
            first.i,
            last.j,
            first.section,
            first.rotation,
            (first.releases[0], last.releases[1]),
            first.kind,
            first.source,
        )
        new_members.append(joined)
        segments += len(chain)
        stations = [0.0]
        for m in chain:
            stations.append(stations[-1] + model.length(m))
        total = stations[-1] or 1.0
        inside = [m.j for m in chain[:-1]]
        removed.update(inside)
        for case, old in zip(cases, model.cases, strict=True):
            loads = [old.uniform.get(m.id, [0.0, 0.0, 0.0]) for m in chain]
            if all(np.allclose(w, loads[0], rtol=1e-9, atol=1e-9) for w in loads) and any(
                abs(v) > 0 for v in loads[0]
            ):
                case.uniform[name] = list(loads[0])
            else:
                runs: list[tuple[list[float], float, float]] = []
                for k, w in enumerate(loads):
                    if not any(abs(v) > 0 for v in w):
                        continue
                    a, b = stations[k], stations[k + 1]
                    if runs and runs[-1][2] == a and np.allclose(runs[-1][0], w, rtol=1e-9):
                        runs[-1] = (runs[-1][0], runs[-1][1], b)
                    else:
                        runs.append((list(w), a, b))
                if runs:
                    case.partial[name] = runs
            for k, node in enumerate(inside, start=1):
                f = case.nodal.pop(node, None)
                if f is not None and any(abs(v) > 0 for v in f[:3]):
                    case.points.setdefault(name, []).append((list(f), stations[k]))
        moved = False
        for k, node in enumerate(inside, start=1):
            mass = masses.pop(node, None)
            if mass is None or not any(mass):
                continue
            moved = True
            share = stations[k] / total
            for end, part in ((first.i, 1.0 - share), (last.j, share)):
                prev = masses.setdefault(end, [0.0] * 6)
                for q in range(6):
                    prev[q] += mass[q] * part
        if moved:  # one entry per member
            report.approximate(
                "lumped masses of the mesh nodes inside a member moved to its ends (lever rule)",
                name,
            )
    out = AnalyticalModel(
        name=model.name,
        nodes={k: v for k, v in model.nodes.items() if k not in removed},
        materials=model.materials,
        sections=model.sections,
        plate_sections=model.plate_sections,
        members=new_members,
        plates=model.plates,
        diaphragms=[
            Diaphragm(d.name, d.master, [n for n in d.nodes if n not in removed])
            for d in model.diaphragms
        ],
        cases=cases,
        combinations=model.combinations,
        grids=model.grids,
        levels=model.levels,
        masses=masses,
        modes=model.modes,
    )
    joined = sum(1 for _, p in pieces if len(p) > 1)
    report.approximate(
        "analysis mesh segments joined back into members (the target meshes its own frames)",
        f"{segments} segments as {joined} members",
    )
    split = sorted({mid for c in cases for mid in (*c.partial, *c.points)})
    if split:
        report.approximate(
            "loads of the joined segments as partial uniform and point loads on the members",
            split[0],
        )
    return out


def count_written(
    report: ExchangeReport,
    model: AnalyticalModel,
    *,
    members: bool = True,
    loads: bool | None = True,
    diaphragms: bool | None = True,
    masses: bool | None = False,
) -> None:
    """Counts in ``report`` what a writer wrote of ``model``: its members by kind and plates;
    its diaphragms, load cases and combinations, lumped masses when the format carries them
    (True), listed as left out when it does not (False), untouched when the writer reports them
    itself (None); ``members``: False when the writer counts the members and plates itself."""
    if members:
        for m in model.members:
            kind = {"column": "columns", "beam": "beams", "brace": "braces"}.get(m.kind, "beams")
            report.count(kind)
        if model.plates:
            report.count("plates", len(model.plates))
    if model.diaphragms and diaphragms is not None:
        if diaphragms:
            report.count("diaphragms", len(model.diaphragms))
        else:
            report.skip("rigid diaphragms (not in this format)", model.diaphragms[0].name)
    if loads:
        if model.cases:
            report.count("loadCases", len(model.cases))
        if model.combinations:
            report.count("combinations", len(model.combinations))
    elif loads is not None:
        if model.cases:
            report.skip(
                "load cases and combinations (this format carries the members, not the loads)",
                ", ".join(c.name for c in model.cases[:5]),
            )
        report.carried.clear()
    massed = sum(1 for m in model.masses.values() if any(m))
    if massed and masses is not None:
        if masses:
            report.count("massNodes", massed)
        else:
            report.skip("lumped masses of the modal analysis (not in this format)", None)


def case_totals(model: AnalyticalModel) -> dict[str, float]:
    """Each case's resultant [kN]."""
    return {c.name: _total(model, c) / 1000 for c in model.cases}


def grouped_by_section(model: AnalyticalModel) -> dict[str, list[Member]]:
    out: dict[str, list[Member]] = defaultdict(list)
    for m in model.members:
        out[m.section].append(m)
    return out


# ─────────────────────────────────────── from a project ───────────────────────────────────────


class ExchangeExportError(ValueError):
    """The project cannot be exported (no building model, a part with errors, no derivation)."""


def project_model(
    project: Any, format_name: str, extension: str
) -> tuple[AnalyticalModel, ExchangeReport, Any]:
    """The neutral model of the project at ``project`` (its folder or ``.saengine`` file), derived
    as Run All derives it, with its report; and the project (:class:`saengine.pipeline.project.
    Project`)."""
    import json

    from pydantic import ValidationError

    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings
    from saengine.pipeline.project import ProjectError, open_project
    from saengine.rpc.handlers import derive_fem

    try:
        p = open_project(project)
    except ProjectError as error:
        raise ExchangeExportError(str(error)) from error
    texts = p.texts(("bim", "objects", "materials", "settings"))
    missing = [k for k, v in texts.items() if not v]
    if missing:
        raise ExchangeExportError(f"{p.name}: no {', '.join(missing)} file to export from")
    try:
        objects = ObjectLibrary.model_validate_json(texts["objects"])  # type: ignore[arg-type]
        materials = MaterialLibrary.model_validate_json(texts["materials"])  # type: ignore[arg-type]
        settings = ProjectSettings.model_validate_json(texts["settings"])  # type: ignore[arg-type]
    except ValidationError as error:
        raise ExchangeExportError(
            f"{p.name}: a part has errors: {error.errors()[0]['msg']}"
        ) from error
    result = derive_fem(
        texts["bim"],  # type: ignore[arg-type]
        texts["objects"],  # type: ignore[arg-type]
        texts["materials"],  # type: ignore[arg-type]
        texts["settings"],  # type: ignore[arg-type]
        str(p.folder("fem")),
    )
    if not result.get("text"):
        problems = "; ".join(result.get("problems") or []) or "no analysis model"
        raise ExchangeExportError(f"{p.name}: the analysis model could not be derived: {problems}")
    report = ExchangeReport(format_name, extension)
    report.source["project"] = p.name
    grids: list[tuple[str, str, float]] = []
    plan_text = p.text("floorPlan")
    if plan_text:
        from saengine.library.floorplan import FloorPlan

        try:
            plan = FloorPlan.model_validate_json(plan_text)
            grids = [("X", g.label, g.position / 1000) for g in plan.grids.x]
            grids += [("Y", g.label, g.position / 1000) for g in plan.grids.y]
        except ValidationError:
            report.warn("The floor plan has errors: no grid lines exported.")
    model = from_osmodel(
        json.loads(result["text"]),
        objects,
        materials,
        settings,
        name=p.name,
        report=report,
        grids=grids,
    )
    for note in result.get("notes") or []:
        if isinstance(note, str) and note:
            report.warn(f"Analysis model: {note}")
    return model, report, p


__all__ = [
    "AnalyticalModel",
    "Diaphragm",
    "ExchangeExportError",
    "ExchangeReport",
    "LoadCase",
    "Material",
    "Member",
    "Node",
    "Plate",
    "PlateSection",
    "Section",
    "case_totals",
    "count_written",
    "from_osmodel",
    "is_vertical",
    "joined_members",
    "local_axes",
    "numbering",
    "project_model",
]

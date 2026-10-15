"""The analysis model (``08 FEM/model.osmodel``), derived from the building model and the settings.

Part 8 never authors geometry: it derives an OpenSees Studio project (schema 2, 3D, 6 DOF per
node, SI units m-N-kg-s) from ``06 BIM/bim.json``, the object types and materials, and applies
the loads of ``02 Project Settings`` (BNBC 2020) automatically:

- columns become elastic beam-columns split at every story they pass, beams and inclined
  members elastic beam-columns split wherever another member's node lies on them;
- sections are elastic, from the object types' profiles (``sectionproperties``), with E and the
  density of their materials;
- the bases of columns at the lowest story are fixed;
- slabs carry their self-weight, superimposed dead and live loads to the beams along their
  edges (:func:`saengine.fem.loads.slab_edge_loads`); a slab edge with no beam hands its load
  to the nodes at its ends;
- wind and earthquake are equivalent static story forces (:mod:`saengine.fem.loads`), shared
  among a story's nodes by their weight, which also gives each node its lumped mass.

Load combinations are not part of the analysis model (OpenSees Studio has no combination
object): the analysis runs each load case once and the combinations of the project settings
are formed from those results, which is exact for this linear elastic model.

Known simplifications are reported as notes: walls and stairs are not yet in the stiffness
model (OpenSees Studio has no shell elements), floors are flexible in plan (no rigid
diaphragm), and columns rotated by other than a multiple of 90° use the nearest one.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np

from saengine.fem import loads as fl
from saengine.library import bnbc
from saengine.library.bim import BeamElement, BuildingModel, ColumnElement, SlabElement
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.sections import section_properties
from saengine.library.settings import ProjectSettings, derived

G = 9.80665  # m/s²
MM = 0.001  # m per mm
UNITS = "SI (m, N, kg, s, Pa)"

#: Load cases of the analysis model, in this order (see bnbc.LOAD_CASES).
CASES = ["D", "SD", "L", "Lr", "WX", "WY", "EX", "EY"]


def stamp(text: str) -> str:
    return hashlib.sha1(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


@dataclass
class _Member:
    """A frame element of the analysis model: its SAEngine element, ends and section."""

    source: str
    i: int
    j: int
    section: int
    density: float  # kg/m³
    area: float  # m²


@dataclass
class Derivation:
    project: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


class _Builder:
    def __init__(self) -> None:
        self.nodes: dict[tuple[int, int, int], int] = {}
        self.coords: dict[int, np.ndarray] = {}
        self.members: list[_Member] = []
        self.sections: list[dict[str, Any]] = []
        self.section_ids: dict[tuple[str, int], int] = {}
        self.restraints: set[int] = set()
        self.notes: list[str] = []

    def node(self, x_mm: float, y_mm: float, z_mm: float) -> int:
        key = (round(x_mm), round(y_mm), round(z_mm))
        if key not in self.nodes:
            node_id = len(self.nodes) + 1
            self.nodes[key] = node_id
            self.coords[node_id] = np.array(key, dtype=float) * MM
        return self.nodes[key]


def local_axes(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The element axes OpenSees Studio uses (its runner picks vecxz from the element axis)."""
    x = (b - a) / np.linalg.norm(b - a)
    vecxz = np.array([1.0, 0, 0]) if abs(x[2]) > abs(x[0]) else np.array([0, 0, 1.0])
    y = np.cross(vecxz, x)
    y /= np.linalg.norm(y)
    return x, y, np.cross(x, y)


def derive_fem(
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary,
    settings: ProjectSettings,
    sources: dict[str, str] | None = None,
) -> Derivation:
    """The OpenSees Studio project of ``building`` with the loads of ``settings``.

    ``sources`` maps upstream part ids to the stamps of their files, recorded in the project's
    description so the editor can tell when they have changed since.
    """
    b = _Builder()
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    levels = sorted({s.elevation for s in building.stories})
    base = levels[0] if levels else 0.0

    def section(
        type_id: str, quarter_turns: int, vertical: bool
    ) -> tuple[int, float, float] | None:
        """Elastic section of an object type in a member along or across the vertical.

        OpenSees Studio picks the local axes from the member's direction: a vertical member's
        local z is global X, a horizontal member's local z is global Z (up). The profile's x-axis
        inertia (``ixx``: about its width, the strong axis of a beam) goes in Iz for a vertical
        member and in Iy for a horizontal one; quarter turns of a column swap the axes.
        """
        object_type = types.get(type_id)
        material = mats.get(object_type.material) if object_type else None
        if object_type is None or material is None or not hasattr(object_type, "profile"):
            return None
        mech = material.mechanical
        if not mech.E:
            return None
        key = (type_id, quarter_turns % 2, vertical)
        if key not in b.section_ids:
            props = section_properties(object_type.profile)
            nu = (
                mech.nu
                if mech.nu is not None
                else (0.2 if material.category.value == "concrete" else 0.3)
            )
            about_x, about_y = props.ixx * MM**4, props.iyy * MM**4
            if quarter_turns % 2:
                about_x, about_y = about_y, about_x
            iz, iy = (about_x, about_y) if vertical else (about_y, about_x)
            b.section_ids[key] = len(b.sections) + 1
            b.sections.append(
                {
                    "id": b.section_ids[key],
                    "name": f"{type_id} {'column' if vertical else 'beam'}"
                    + (" (rotated)" if quarter_turns % 2 else ""),
                    "type": "ElasticSection",
                    "E": mech.E * 1e6,
                    "A": props.area * MM**2,
                    "Iz": iz,
                    "Iy": iy,
                    "G": mech.E * 1e6 / (2 * (1 + nu)),
                    "J": props.j * MM**4,
                }
            )
        return (
            b.section_ids[key],
            (mech.density or 0.0),
            section_properties(object_type.profile).area * MM**2,
        )

    # Columns, split at every level they pass; bases at the lowest level are fixed.
    for element in building.elements:
        if not isinstance(element, ColumnElement):
            continue
        turns = round(element.rotation / 90)
        if abs(element.rotation - 90 * turns) > 1e-6:
            b.notes.append(
                f"{element.id}: rotation {element.rotation}° is analysed as {90 * turns % 360}°"
            )
        sec = section(element.type, turns, True)
        if sec is None:
            b.notes.append(
                f"{element.id}: no elastic section (object type, material or E missing); left out"
            )
            continue
        x, y = element.position
        stops = [
            element.bottom,
            *[lv for lv in levels if element.bottom < lv < element.top],
            element.top,
        ]
        ids = [b.node(x, y, z) for z in stops]
        for i, j in pairwise(ids):
            b.members.append(_Member(element.id, i, j, sec[0], sec[1], sec[2]))
        if math.isclose(element.bottom, base):
            b.restraints.add(ids[0])

    # Beam ends and inclined members' ends, then beams split at every node on them.
    linear: list[tuple[str, str, np.ndarray, np.ndarray]] = []
    for element in building.elements:
        if isinstance(element, BeamElement):
            a = np.array([*element.start, element.elevation])
            c = np.array([*element.end, element.elevation])
            linear.append((element.id, element.type, a, c))
    for member in building.additions.members:
        linear.append(
            (
                member.id,
                member.type,
                np.array([member.x1, member.y1, member.z1]),
                np.array([member.x2, member.y2, member.z2]),
            )
        )
    for _, _, a, c in linear:
        b.node(*a)
        b.node(*c)
    for source, type_id, a, c in linear:
        axis = c - a
        sec = section(type_id, 0, abs(axis[2]) > abs(axis[0]))
        if sec is None:
            b.notes.append(
                f"{source}: no elastic section (object type, material or E missing); left out"
            )
            continue
        axis = c - a
        length = float(np.linalg.norm(axis))
        stops = sorted(
            {0.0, 1.0}
            | {
                t
                for key in b.nodes
                for t in [float(np.dot(np.array(key) - a, axis) / length**2)]
                if 1e-6 < t < 1 - 1e-6 and np.linalg.norm(a + t * axis - np.array(key)) < 1.0
            }
        )
        ids = [b.node(*(a + t * axis)) for t in stops]
        for i, j in pairwise(ids):
            b.members.append(_Member(source, i, j, sec[0], sec[1], sec[2]))

    for element in building.elements:
        if element.kind == "wall":
            b.notes.append(
                f"{element.id}: walls are not in the analysis model yet (no shell elements); its weight is not applied"
            )
    for stair in building.additions.stairs:
        b.notes.append(
            f"{stair.id}: stairs are not in the analysis model yet; their loads are not applied"
        )

    # ── loads ──
    patterns: dict[str, dict[str, Any]] = {case: {"nodal": {}, "element": {}} for case in CASES}
    node_weight: dict[int, float] = {}  # N, D + SD + share of L, for masses and lateral forces

    def add_element_load(case: str, index: int, vector: np.ndarray) -> None:
        """A uniform load (global N/m) on member ``index``, applied in its local axes."""
        member = b.members[index]
        x, y, z = local_axes(b.coords[member.i], b.coords[member.j])
        local = np.array([vector @ x, vector @ y, vector @ z])
        total = patterns[case]["element"].setdefault(index, np.zeros(3))
        total += local

    def add_nodal(case: str, node_id: int, force: np.ndarray) -> None:
        patterns[case]["nodal"].setdefault(node_id, np.zeros(6))[:3] += force

    def share_weight(index: int, w: float, factor: float) -> None:
        member = b.members[index]
        half = w * float(np.linalg.norm(b.coords[member.j] - b.coords[member.i])) / 2 * factor
        node_weight[member.i] = node_weight.get(member.i, 0.0) + half
        node_weight[member.j] = node_weight.get(member.j, 0.0) + half

    down = np.array([0.0, 0.0, -1.0])
    for index, member in enumerate(b.members):
        w = member.density * member.area * G
        if w:
            add_element_load("D", index, down * w)
            share_weight(index, w, 1.0)

    area_loads = {a.id: a for a in settings.areaLoads}
    top = levels[-1] if levels else 0.0
    beams_at = [
        (index, b.coords[m.i], b.coords[m.j])
        for index, m in enumerate(b.members)
        if abs(b.coords[m.i][2] - b.coords[m.j][2]) < 1e-9
    ]
    for element in building.elements:
        if not isinstance(element, SlabElement):
            continue
        object_type = types.get(element.type)
        material = mats.get(object_type.material) if object_type else None
        if object_type is None or object_type.kind != "slab":
            b.notes.append(
                f"{element.id}: unknown slab type '{element.type}'; its loads are not applied"
            )
            continue
        roof = math.isclose(element.elevation, top)
        area_load = area_loads.get(settings.roofLoad if roof else settings.floorLoad)
        self_weight = (
            (material.mechanical.density or 0.0) * G * object_type.thickness * MM
            if material
            else 0.0
        )
        pressures = {
            "D": self_weight,
            "SD": (area_load.finish + area_load.partitions) * 1e3 if area_load else 0.0,
            "Lr" if roof else "L": area_load.live * 1e3 if area_load else 0.0,
        }
        corners = [(x * MM, y * MM) for x, y in element.boundary]
        z = element.elevation * MM
        for case, pressure in pressures.items():
            if not pressure:
                continue
            seismic_share = (
                1.0 if case in ("D", "SD") else bnbc.SEISMIC_LIVE_SHARE if case == "L" else 0.0
            )
            for edge in fl.slab_edge_loads(corners, pressure, object_type.system):
                if not edge.load:
                    continue
                p0 = np.array([*corners[edge.index], z])
                p1 = np.array([*corners[(edge.index + 1) % len(corners)], z])
                carried = 0.0
                for index, a, c in beams_at:
                    if (
                        abs(a[2] - z) > 1e-6
                        or not _on_segment(a, p0, p1)
                        or not _on_segment(c, p0, p1)
                    ):
                        continue
                    add_element_load(case, index, down * edge.load)
                    share_weight(index, edge.load, seismic_share)
                    carried += float(np.linalg.norm(c - a))
                rest = float(np.linalg.norm(p1 - p0)) - carried
                if rest > 1e-3:
                    ends = [
                        b.nodes.get((round(p[0] / MM), round(p[1] / MM), round(p[2] / MM)))
                        for p in (p0, p1)
                    ]
                    if all(ends):
                        for node_id in ends:
                            add_nodal(case, node_id, down * edge.load * rest / 2)
                            node_weight[node_id] = (
                                node_weight.get(node_id, 0.0) + edge.load * rest / 2 * seismic_share
                            )
                    elif case == "D":
                        b.notes.append(
                            f"{element.id}: an edge has neither a beam nor columns at its ends; part of its load is not applied"
                        )

    # ── lateral loads: equivalent static story forces, shared among a story's nodes by weight ──
    values = derived(settings)
    story_nodes: dict[float, list[int]] = {}
    for key, node_id in b.nodes.items():
        z = key[2] * MM
        if z > base * MM + 1e-6:
            story_nodes.setdefault(round(z, 6), []).append(node_id)
    heights = sorted(story_nodes)
    weights = [sum(node_weight.get(n, 0.0) for n in story_nodes[h]) for h in heights]
    hn = (heights[-1] - base * MM) if heights else 0.0
    summary: dict[str, Any] = {"levels": len(heights), "weight_kN": sum(weights) / 1e3}
    if heights and values["Z"] and values["windSpeed"]:
        period = fl.approximate_period(hn, settings.seismic.system)
        sa = fl.design_acceleration(
            period, settings.site.siteClass, values["Z"], values["seismicImportance"], values["R"]
        )
        base_shear = sa * sum(weights)
        story_forces = fl.vertical_distribution(
            [(h - base * MM, w) for h, w in zip(heights, weights)], base_shear, period
        )
        xs = [b.coords[n][0] for n in b.coords]
        ys = [b.coords[n][1] for n in b.coords]
        extent_x, extent_y = (max(xs) - min(xs)) or 1.0, (max(ys) - min(ys)) or 1.0
        rel = [h - base * MM for h in heights]
        wind = {
            "WX": fl.wind_level_forces(
                rel,
                extent_y,
                extent_x,
                values["windSpeed"],
                settings.wind.exposure,
                values["windImportance"],
            ),
            "WY": fl.wind_level_forces(
                rel,
                extent_x,
                extent_y,
                values["windSpeed"],
                settings.wind.exposure,
                values["windImportance"],
            ),
        }
        for level, h in enumerate(heights):
            total = weights[level] or 1.0
            for node_id in story_nodes[h]:
                share = (
                    node_weight.get(node_id, 0.0) / total
                    if weights[level]
                    else 1 / len(story_nodes[h])
                )
                add_nodal("EX", node_id, np.array([story_forces[level] * share, 0, 0]))
                add_nodal("EY", node_id, np.array([0, story_forces[level] * share, 0]))
                add_nodal("WX", node_id, np.array([wind["WX"][level] * 1e3 * share, 0, 0]))
                add_nodal("WY", node_id, np.array([0, wind["WY"][level] * 1e3 * share, 0]))
        summary.update(
            {
                "period_s": period,
                "Cs": fl.normalized_spectrum(period, settings.site.siteClass),
                "Sa_g": sa,
                "base_shear_kN": base_shear / 1e3,
                "wind_X_kN": sum(wind["WX"]),
                "wind_Y_kN": sum(wind["WY"]),
            }
        )
    else:
        b.notes.append(
            "no lateral loads: the building has no levels above its base, or the site has no Z or wind speed"
        )

    # ── project ──
    nodes = []
    for node_id, xyz in sorted(b.coords.items()):
        mass = node_weight.get(node_id, 0.0) / G
        restrained = node_id in b.restraints
        nodes.append(
            {
                "id": node_id,
                "name": "",
                "coords": [round(float(v), 6) for v in xyz],
                "mass": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                if restrained
                else [mass, mass, 0.0, 0.0, 0.0, 0.0],
                "restraint": [restrained] * 6,
            }
        )
    elements = []
    for index, member in enumerate(b.members):
        count = sum(1 for m in b.members[:index] if m.source == member.source)
        elements.append(
            {
                "id": index + 1,
                "name": member.source if count == 0 else f"{member.source}#{count + 1}",
                "type": "ElasticBeamColumn",
                "nodes": [member.i, member.j],
                "section_id": member.section,
                "geom_transf": "Linear",
                "rho": 0.0,
                "consistent_mass": False,
            }
        )
    load_patterns = []
    for number, case in enumerate(CASES, start=1):
        pattern = patterns[case]
        load_patterns.append(
            {
                "id": number,
                "name": case,
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [
                    {"node_id": n, "forces": [round(float(f), 3) for f in v]}
                    for n, v in sorted(pattern["nodal"].items())
                ],
                "element_loads": [
                    {
                        "element_id": i + 1,
                        "wy": round(float(v[1]), 3),
                        "wz": round(float(v[2]), 3),
                        "wx": round(float(v[0]), 3),
                    }
                    for i, v in sorted(pattern["element"].items())
                ],
            }
        )
    analyses = [
        {
            "id": number,
            "name": f"{case}: {bnbc.LOAD_CASES[case]}",
            "type": "Static",
            "pattern_ids": [number],
            "n_steps": 1,
            "load_factor_increment": 1.0,
            "system": "BandGeneral",
            "constraints": "Plain",
            "integrator": "LoadControl",
            "algorithm": "Linear",
            "test": "NormDispIncr",
            "tolerance": 1e-8,
            "max_iter": 25,
        }
        for number, case in enumerate(CASES, start=1)
    ]
    if any(node_weight.values()):
        analyses.append(
            {
                "id": len(CASES) + 1,
                "name": "Modal",
                "type": "Modal",
                "n_modes": max(1, min(12, 3 * len(heights))),
                "solver": "auto",
            }
        )

    stamps = "; ".join(f"{k}={v}" for k, v in sorted((sources or {}).items()))
    project = {
        "schema_version": 2,
        "meta": {
            "name": settings.project.name,
            "description": f"Derived by SAEngine from the building model and the project settings. Sources: {stamps}",
            "author": "SAEngine",
            "units": UNITS,
        },
        "ndm": 3,
        "ndf": 6,
        "nodes": nodes,
        "sections": b.sections,
        "elements": elements,
        "time_series": [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}],
        "load_patterns": load_patterns,
        "analyses": analyses,
    }
    summary.update({"nodes": len(nodes), "elements": len(elements), "supports": len(b.restraints)})
    return Derivation(project=project, notes=b.notes, summary=summary)


def _on_segment(point: np.ndarray, a: np.ndarray, b: np.ndarray, tolerance: float = 1e-3) -> bool:
    """Whether ``point`` lies on the segment from ``a`` to ``b`` (within ``tolerance`` metres)."""
    axis = b - a
    length2 = float(axis @ axis)
    t = float((point - a) @ axis / length2) if length2 else 0.0
    return -1e-6 <= t <= 1 + 1e-6 and float(np.linalg.norm(a + t * axis - point)) <= tolerance

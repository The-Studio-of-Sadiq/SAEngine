"""The analysis model (``08 FEM/model.osmodel``), derived from the building model and the settings.

Part 8 never authors geometry: it derives an OpenSees Studio project (schema 2, 3D, 6 DOF per
node, SI units m-N-kg-s) from ``06 BIM/bim.json``, the object types and materials, and applies
the loads of ``02 Project Settings`` (BNBC 2020) automatically:

- columns, beams and inclined members become elastic beam-columns; structural walls (and slabs,
  when the settings model them as shells) become shell elements. Gmsh meshes them together
  (:mod:`saengine.fem.mesh`), so frames and shells share their nodes wherever they meet;
- sections are elastic, from the object types' profiles (``sectionproperties``) and thicknesses,
  with E, Poisson's ratio and the density of their materials;
- the bases of columns and walls at the lowest story are fixed;
- slabs on beams carry their self-weight, superimposed dead and live loads to the beams along
  their edges (:func:`saengine.fem.loads.slab_edge_loads`); where an edge has no beam (a wall
  top, a free edge between columns) its load goes to the edge's nodes. Shell slabs and walls
  carry their loads as the consistent nodal loads of their elements. Non-structural walls are
  a line load on the beams they stand on;
- with a rigid diaphragm (the default) every floor is tied to a node at its centre of mass;
- wind and earthquake are equivalent static story forces (:mod:`saengine.fem.loads`) at the
  levels, shared among a level's nodes by their weight; each node's weight also gives its
  lumped mass. Nodes between levels (wall meshes) count towards the nearest level's weight.

Load combinations are not part of the analysis model (OpenSees Studio has no combination
object): the analysis runs each load case once and the combinations of the project settings
are formed from those results, which is exact for this linear elastic model.

Known simplifications are reported as notes: stairs are not in the stiffness model, and
columns rotated by other than a multiple of 90° use the nearest one.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem import loads as fl
from saengine.fem.mesh import Surface, Volume, mesh, shell_node_shares
from saengine.library import bnbc
from saengine.library.bim import (
    AreaElement,
    BeamElement,
    BlockElement,
    BuildingModel,
    ColumnElement,
    MemberElement,
    SlabElement,
    WallElement,
)
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.sections import section_properties
from saengine.library.settings import ProjectSettings, derived
from saengine.library.structure import plane_of

G = 9.80665  # m/s²
MM = 0.001  # m per mm
UNITS = "SI (m, N, kg, s, Pa)"

#: Load cases of the analysis model, in this order (see bnbc.LOAD_CASES). The fluid case F (the
#: contents of equipment in 07 MEP) is last and is only in a model that has fluid loads, so the
#: other cases keep their numbers. The temperature case T is added after them when the settings
#: ask for it (:mod:`saengine.fem.thermal`).
CASES = ["D", "SD", "L", "Lr", "WX", "WY", "EX", "EY", "F"]

#: Restraint of a diaphragm's own node: free in plan, held out of plane.
_IN_PLAN = [False, False, True, True, True, False]


#: Periods of the tabulated design spectrum [s]: fine where it turns, coarse in its tail.
SPECTRUM_PERIODS = (
    *[round(0.02 * i, 2) for i in range(1, 51)],
    *[round(1.0 + 0.1 * i, 1) for i in range(1, 31)],
    *[round(4.0 + 0.5 * i, 1) for i in range(1, 9)],
)


def _ground_motion(
    history: Any, record_id: int, model_dir: str | Path | None
) -> dict[str, Any] | str:
    """The ground-motion catalog entry of a time history's record, or why there is none."""
    from opensees_studio.core.ground_motion import import_record

    if model_dir is None:
        return "the model's folder is not known"
    path = Path(model_dir).parent / history.record
    if not path.is_file():
        return f"its record {history.record} is not in the project folder"
    try:
        record, _ = import_record(
            path,
            model_dir,
            record_id,
            name=history.name,
            dt=history.dt,
            accel_units="g" if history.units == "g" else "project",
        )
    except ValueError as exc:
        return str(exc)
    # A two-column record's step comes from its time column: keep it free of float noise.
    return record.model_copy(update={"dt": round(record.dt, 9)}).model_dump(mode="json")


def stamp(text: str) -> str:
    return hashlib.sha1(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


#: What the analysis model takes from ``07 MEP/mep.json`` (:func:`mep_stamp`); names and service
#: labels of its items are left out, as are the MEP IFC models.
MEP_MODEL_KEYS = ("contentsAs", "equipment", "openings", "shafts")
_MEP_LABELS = ("name", "service")


def _js_number(value: float) -> str:
    """``value`` as JavaScript's ``JSON.stringify`` writes it (shortest round trip)."""
    if not math.isfinite(value):
        return "null"
    if value == int(value) and abs(value) < 1e21:
        return str(int(value))
    from decimal import Decimal

    sign, digits, exponent = Decimal(repr(value)).as_tuple()
    text = "".join(map(str, digits)).rstrip("0")
    exponent = int(exponent) + len(digits) - len(text)
    k, n = len(text), len(text) + exponent  # value = 0.text × 10^n
    if k <= n <= 21:
        out = text + "0" * (n - k)
    elif 0 < n <= 21:
        out = f"{text[:n]}.{text[n:]}"
    elif -6 < n <= 0:
        out = "0." + "0" * -n + text
    else:
        e = n - 1
        out = (text if k == 1 else f"{text[0]}.{text[1:]}") + f"e{'+' if e >= 0 else '-'}{abs(e)}"
    return ("-" if sign else "") + out


def js_json(value: Any) -> str:
    """``value`` (parsed JSON) as JavaScript's ``JSON.stringify(value)`` writes it, so a stamp of
    it matches the workbench's (``mepModelStamp`` in partSources.ts)."""
    import json

    if value is None or value is True or value is False:
        return json.dumps(value)
    if isinstance(value, int):
        return str(value) if abs(value) <= 2**53 else _js_number(float(value))
    if isinstance(value, float):
        return _js_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list | tuple):
        return "[" + ",".join(js_json(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{js_json(str(k))}:{js_json(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"not JSON: {type(value).__name__}")


def mep_stamp(text: str) -> str:
    """The stamp an analysis model records for ``07 MEP/mep.json`` (key ``mep``): of what the
    model takes from it (:data:`MEP_MODEL_KEYS`, without the items' names and service labels),
    so editing an IFC model's entry or a label leaves the model current. The workbench computes
    the same (``mepModelStamp`` in partSources.ts); a text that is not a JSON object is stamped
    whole."""
    import json

    try:
        document = json.loads(text)
    except ValueError:
        return stamp(text)
    if not isinstance(document, dict):
        return stamp(text)
    content: dict[str, Any] = {}
    for key in MEP_MODEL_KEYS:
        if key not in document:
            continue
        value = document[key]
        if isinstance(value, list):
            value = [
                {k: v for k, v in item.items() if k not in _MEP_LABELS}
                if isinstance(item, dict)
                else item
                for item in value
            ]
        content[key] = value
    return stamp(js_json(content))


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
class _Shell:
    """A shell element of the analysis model: its SAEngine element, nodes and section."""

    source: str
    nodes: tuple[int, ...]
    section: int


@dataclass
class _Solid:
    """A tetrahedron of the analysis model: its SAEngine block, nodes and material."""

    source: str
    nodes: tuple[int, int, int, int]
    material: int
    density: float  # kg/m³


@dataclass
class Derivation:
    project: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    #: The pushover model (frames as fiber elements), when the settings ask for pushovers.
    pushover: dict[str, Any] | None = None
    #: The temperature case's fixed-end forces to add back (``08 FEM/thermal.json``).
    thermal: dict[str, Any] | None = None
    #: The soil springs of the column bases (``08 FEM/ssi.json``), with ``supports`` "soilSprings".
    ssi: dict[str, Any] | None = None


class _Builder:
    def __init__(self) -> None:
        self.nodes: dict[tuple[int, int, int], int] = {}
        self.coords: dict[int, np.ndarray] = {}
        self.members: list[_Member] = []
        self.shells: list[_Shell] = []
        self.solids: list[_Solid] = []
        self.materials: list[dict[str, Any]] = []
        self.material_ids: dict[tuple[str, str], int] = {}
        self.sections: list[dict[str, Any]] = []
        self.section_ids: dict[tuple[Any, ...], int] = {}
        self.restraints: dict[int, list[bool]] = {}
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
    model_dir: str | Path | None = None,
    mep: Any = None,
    substructure: Any = None,
    soil_text: str | None = None,
    column_supports: str | None = None,
) -> Derivation:
    """The OpenSees Studio project of ``building`` with the loads of ``settings``.

    ``sources`` maps upstream part ids to the stamps of their files, recorded in the project's
    description so the editor can tell when they have changed since. ``model_dir`` is the folder
    the model is written to (``08 FEM``): time-history records are found from the project folder
    above it and referenced relative to it.

    ``mep`` (:class:`saengine.library.mep.MepModel`, ``07 MEP/mep.json``): its shafts and slab
    openings are cut from the slabs and its equipment loads applied (:mod:`saengine.mep.loads`).
    ``substructure`` (:class:`saengine.library.substructure.Substructure`) and ``soil_text`` (the
    soil report): the foundations and soil of the column bases' springs when the settings'
    ``analysis.supports`` (or ``column_supports``, which overrides it) is "soilSprings"
    (:mod:`saengine.fem.ssi`).
    """
    mep_notes: list[str] = []
    if mep is not None:
        from saengine.mep.loads import with_mep_openings

        building, mep_notes = with_mep_openings(building, mep)
    b = _Builder()
    options = settings.analysis
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    levels = sorted({s.elevation for s in building.stories})
    base = levels[0] if levels else 0.0
    # Special structures (drawn in 3D, Part 5 structural model) have explicit supports and no
    # floors: no base fixity by level, no diaphragms, no story forces.
    special = building.source is not None and building.source.structure is not None

    def poisson(material: Any) -> float:
        nu = material.mechanical.nu
        return nu if nu is not None else (0.2 if material.category.value == "concrete" else 0.3)

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
                    "G": mech.E * 1e6 / (2 * (1 + poisson(material))),
                    "J": props.j * MM**4,
                }
            )
        return (
            b.section_ids[key],
            (mech.density or 0.0),
            section_properties(object_type.profile).area * MM**2,
        )

    def plate(type_id: str) -> tuple[int, float, float] | None:
        """Plate section of a wall or slab type: (section id, density, thickness m)."""
        object_type = types.get(type_id)
        material = mats.get(object_type.material) if object_type else None
        if object_type is None or material is None or not material.mechanical.E:
            return None
        thickness = object_type.thickness * MM
        key = ("plate", type_id)
        if key not in b.section_ids:
            b.section_ids[key] = len(b.sections) + 1
            b.sections.append(
                {
                    "id": b.section_ids[key],
                    "name": f"{type_id} {object_type.kind}",
                    "type": "ElasticMembranePlateSection",
                    "E": material.mechanical.E * 1e6,
                    "nu": poisson(material),
                    "h": thickness,
                    # The mass is lumped at the nodes with the loads, as for the frames.
                    "rho": 0.0,
                }
            )
        return b.section_ids[key], material.mechanical.density or 0.0, thickness

    # ── geometry: frames as lines, structural walls (and shell slabs) as surfaces ──
    lines: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = []
    line_sources: dict[str, tuple[str, tuple[int, float, float]]] = {}
    surfaces: list[Surface] = []
    surface_sources: dict[str, tuple[str, tuple[int, float, float]]] = {}
    supports: list[tuple[float, float, float]] = []
    partitions: list[tuple[WallElement, float]] = []  # non-structural walls, N/m

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
        # Split at every level the column passes, so each floor has its node.
        stops = [
            element.bottom,
            *[lv for lv in levels if element.bottom < lv < element.top],
            element.top,
        ]
        for k, (z0, z1) in enumerate(pairwise(stops)):
            key = f"{element.id}/{k}"
            lines.append((key, (x, y, z0), (x, y, z1)))
            line_sources[key] = (element.id, sec)
        if math.isclose(element.bottom, base):
            supports.append((x, y, element.bottom))

    linear: list[tuple[str, str, np.ndarray, np.ndarray]] = []
    for element in building.elements:
        if isinstance(element, BeamElement):
            linear.append(
                (
                    element.id,
                    element.type,
                    np.array([*element.start, element.elevation]),
                    np.array([*element.end, element.elevation]),
                )
            )
    for member in building.additions.members:
        linear.append(
            (
                member.id,
                member.type,
                np.array([member.x1, member.y1, member.z1]),
                np.array([member.x2, member.y2, member.z2]),
            )
        )
    for source, type_id, a, c in linear:
        axis = c - a
        sec = section(type_id, 0, abs(axis[2]) > abs(axis[0]))
        if sec is None:
            b.notes.append(
                f"{source}: no elastic section (object type, material or E missing); left out"
            )
            continue
        lines.append((source, tuple(a), tuple(c)))
        line_sources[source] = (source, sec)

    for element in building.elements:
        if not isinstance(element, MemberElement):
            continue
        a, c = np.array(element.start), np.array(element.end)
        turns = round(element.rotation / 90)
        if abs(element.rotation - 90 * turns) > 1e-6:
            b.notes.append(
                f"{element.id}: rotation {element.rotation}° is analysed as {90 * turns % 360}°"
            )
        axis = c - a
        sec = section(element.type, turns, abs(axis[2]) > abs(axis[0]))
        if sec is None:
            b.notes.append(
                f"{element.id}: no elastic section (object type, material or E missing); left out"
            )
            continue
        lines.append((element.id, tuple(a), tuple(c)))
        line_sources[element.id] = (element.id, sec)

    area_loads_of: dict[str, str | None] = {}
    for element in building.elements:
        if not isinstance(element, AreaElement):
            continue
        sec = plate(element.type)
        object_type = types.get(element.type)
        if sec is None or object_type is None or object_type.kind not in ("slab", "wall"):
            b.notes.append(f"{element.id}: no slab or wall type with a plate section; left out")
            continue
        points = [np.array(p, dtype=float) for p in element.outline]
        plane = plane_of(points)
        if plane is None:
            b.notes.append(f"{element.id}: its outline is not a flat polygon; left out")
            continue
        first = points[1] - points[0]
        surfaces.append(
            Surface(
                key=element.id,
                outline=[tuple(p) for p in element.outline],
                openings=[[tuple(p) for p in o] for o in element.openings],
                direction=tuple(first / np.linalg.norm(first)),
                normal=tuple(plane[1]),
            )
        )
        surface_sources[element.id] = (element.id, sec)
        area_loads_of[element.id] = element.areaLoad

    wall_openings: dict[str, list[Any]] = {}
    for opening in building.additions.wallOpenings:
        wall_openings.setdefault(opening.host, []).append(opening)
    for element in building.elements:
        if not isinstance(element, WallElement):
            continue
        object_type = types.get(element.type)
        if object_type is None or object_type.kind != "wall":
            b.notes.append(f"{element.id}: unknown wall type '{element.type}'; left out")
            continue
        start, end = np.array(element.start, dtype=float), np.array(element.end, dtype=float)
        run = end - start
        length = float(np.linalg.norm(run))
        if length < 1:
            continue
        along = run / length
        if not object_type.structural:
            material = mats.get(object_type.material)
            density = (material.mechanical.density or 0.0) if material else 0.0
            weight = density * G * object_type.thickness * MM * (element.top - element.bottom) * MM
            partitions.append((element, weight))
            continue
        sec = plate(element.type)
        if sec is None:
            b.notes.append(f"{element.id}: no plate section (material or E missing); left out")
            continue

        def corner(s: float, z: float, start: np.ndarray = start, along: np.ndarray = along):
            return (*(start + s * along), z)

        openings = [
            [
                corner(o.offset, element.bottom + o.sill),
                corner(o.offset + o.width, element.bottom + o.sill),
                corner(o.offset + o.width, element.bottom + o.sill + o.height),
                corner(o.offset, element.bottom + o.sill + o.height),
            ]
            for o in wall_openings.get(element.id, [])
        ]
        surfaces.append(
            Surface(
                key=element.id,
                outline=[
                    corner(0, element.bottom),
                    corner(length, element.bottom),
                    corner(length, element.top),
                    corner(0, element.top),
                ],
                openings=openings,
                direction=(float(along[0]), float(along[1]), 0.0),
            )
        )
        surface_sources[element.id] = (element.id, sec)
        if math.isclose(element.bottom, base):
            # The wall's whole base edge is fixed: its nodes there are found after meshing.
            supports.append((*start, element.bottom))
            supports.append((*end, element.bottom))
            lines.append(
                (f"{element.id}/base", corner(0, element.bottom), corner(length, element.bottom))
            )

    slab_openings: dict[str, list[Any]] = {}
    for opening in building.additions.slabOpenings:
        slab_openings.setdefault(opening.host, []).append(opening)
    shell_slabs = options.slabs == "shells"
    if shell_slabs:
        for element in building.elements:
            if not isinstance(element, SlabElement):
                continue
            sec = plate(element.type)
            if sec is None:
                continue  # reported with the slab loads below
            z = element.elevation
            surfaces.append(
                Surface(
                    key=element.id,
                    outline=[(x, y, z) for x, y in element.boundary],
                    openings=[_rectangle(o, z) for o in slab_openings.get(element.id, [])],
                    normal=(0.0, 0.0, 1.0),
                )
            )
            surface_sources[element.id] = (element.id, sec)

    # ── solid blocks: volumes of four-node tetrahedra with an elastic material ──
    volumes: list[Volume] = []
    block_materials: dict[str, tuple[int, float]] = {}  # block id -> material id, density
    supported_faces: list[tuple[np.ndarray, np.ndarray, list[np.ndarray]]] = []  # m
    for element in building.elements:
        if not isinstance(element, BlockElement):
            continue
        object_type = types.get(element.type)
        material = mats.get(object_type.material) if object_type else None
        if object_type is None or object_type.kind != "solid" or material is None:
            b.notes.append(f"{element.id}: no solid type with a material; left out")
            continue
        if not material.mechanical.E:
            b.notes.append(f"{element.id}: its material has no E; left out")
            continue
        points = [np.array(p, dtype=float) for p in element.outline]
        plane = plane_of(points)
        if plane is None:
            b.notes.append(f"{element.id}: its outline is not a flat polygon; left out")
            continue
        volumes.append(
            Volume(
                key=element.id,
                outline=[tuple(p) for p in element.outline],
                extrusion=tuple(plane[1] * element.thickness),
            )
        )
        key = ("solid", element.type)
        if key not in b.material_ids:
            b.material_ids[key] = len(b.materials) + 1
            b.materials.append(
                {
                    "id": b.material_ids[key],
                    "name": f"{element.type} solid",
                    "type": "ElasticIsotropic",
                    "E": material.mechanical.E * 1e6,
                    "nu": poisson(material),
                    # The mass is lumped at the nodes with the loads, as for frames and shells.
                    "rho": 0.0,
                }
            )
        block_materials[element.id] = (b.material_ids[key], material.mechanical.density or 0.0)
        if element.supported:
            supported_faces.append((plane[0] * MM, plane[1], [q * MM for q in points]))

    meshed = mesh(lines, surfaces, options.meshSize, volumes)
    node_of = {tag: b.node(*xyz) for tag, xyz in meshed.nodes.items()}
    for key, segments in meshed.lines.items():
        if key.endswith("/base"):
            for i, j in segments:  # a wall's base edge: fixed
                b.restraints[node_of[i]] = [True] * 6
                b.restraints[node_of[j]] = [True] * 6
            continue
        source, sec = line_sources[key]
        for i, j in segments:
            if node_of[i] != node_of[j]:
                b.members.append(_Member(source, node_of[i], node_of[j], *sec))
    for key, elements in meshed.surfaces.items():
        source, sec = surface_sources[key]
        for nodes in elements:
            ids = tuple(node_of[n] for n in nodes)
            if len(set(ids)) == len(ids):
                b.shells.append(_Shell(source, ids, sec[0]))
    for key, tetrahedra in meshed.volumes.items():
        material_id, density = block_materials[key]
        for nodes in tetrahedra:
            ids = tuple(node_of[n] for n in nodes)
            if len(set(ids)) == 4:
                b.solids.append(_Solid(key, ids, material_id, density))  # type: ignore[arg-type]
    for origin, normal, outline in supported_faces:
        for node_id, xyz in b.coords.items():
            if abs(float((xyz - origin) @ normal)) < 1e-6 and _in_polygon(xyz, outline, normal):
                b.restraints[node_id] = [True] * 6
    _embed(b)
    for x, y, z in supports:
        b.restraints[b.node(x, y, z)] = [True] * 6
    for support in building.supports:
        key = tuple(round(v) for v in support.at)
        if key not in b.nodes:
            b.notes.append(
                f"{support.id}: not at a member end or an area corner of the model; left out"
            )
            continue
        pinned = support.fixity == "pinned"
        b.restraints[b.nodes[key]] = [True, True, True, not pinned, not pinned, not pinned]

    for stair in building.additions.stairs:
        b.notes.append(
            f"{stair.id}: stairs are not in the analysis model yet; their loads are not applied"
        )

    # ── loads ──
    patterns: dict[str, dict[str, Any]] = {case: {"nodal": {}, "element": {}} for case in CASES}
    node_weight: dict[int, float] = {}  # N, D + SD + share of L, for masses and lateral forces

    # Construction sequence: the self-weight (D) also goes, per element, to the stage of the
    # storey its element tops out in (one stage per level above the base).
    stage_levels = [lv * MM for lv in levels if lv > base]
    staged = options.constructionSequence and not special and bool(stage_levels)
    if options.constructionSequence and not staged:
        b.notes.append(
            "construction sequence: left out (it applies to buildings with levels above their base)"
        )
    stage_patterns: dict[int, dict[str, Any]] = {}

    def stage_of(z: float) -> int:
        """The stage of an element whose top is at ``z`` [m]: the first level at or above it."""
        for k, height in enumerate(stage_levels):
            if z <= height + 1e-6:
                return k
        return len(stage_levels) - 1

    def top_stage(node_ids: Any) -> int:
        return stage_of(max(float(b.coords[n][2]) for n in node_ids))

    def add_element_load(case: str, index: int, vector: np.ndarray) -> None:
        """A uniform load (global N/m) on member ``index``, applied in its local axes."""
        member = b.members[index]
        x, y, z = local_axes(b.coords[member.i], b.coords[member.j])
        local = np.array([vector @ x, vector @ y, vector @ z])
        total = patterns[case]["element"].setdefault(index, np.zeros(3))
        total += local
        if staged and case == "D":
            stage = stage_patterns.setdefault(
                top_stage((member.i, member.j)), {"nodal": {}, "element": {}}
            )
            stage["element"].setdefault(index, np.zeros(3))[:] += local

    def add_nodal(case: str, node_id: int, force: np.ndarray, stage: int | None = None) -> None:
        """A nodal force (global N); ``stage``: the construction stage of the element it comes
        from (by default the stage of the node's level)."""
        patterns[case]["nodal"].setdefault(node_id, np.zeros(6))[:3] += force
        if staged and case == "D":
            k = stage if stage is not None else top_stage((node_id,))
            pattern = stage_patterns.setdefault(k, {"nodal": {}, "element": {}})
            pattern["nodal"].setdefault(node_id, np.zeros(6))[:3] += force

    def add_weight(node_id: int, weight: float) -> None:
        node_weight[node_id] = node_weight.get(node_id, 0.0) + weight

    def share_weight(index: int, w: float, factor: float) -> None:
        member = b.members[index]
        half = w * float(np.linalg.norm(b.coords[member.j] - b.coords[member.i])) / 2 * factor
        add_weight(member.i, half)
        add_weight(member.j, half)

    down = np.array([0.0, 0.0, -1.0])
    for index, member in enumerate(b.members):
        w = member.density * member.area * G
        if w:
            add_element_load("D", index, down * w)
            share_weight(index, w, 1.0)

    for solid in b.solids:
        corners = [b.coords[n] for n in solid.nodes]
        volume = abs(float(np.linalg.det(np.array([c - corners[0] for c in corners[1:]])))) / 6
        w = volume * solid.density * G / 4  # a linear tetrahedron: a quarter to each corner
        if w:
            for node_id in solid.nodes:
                add_nodal("D", node_id, down * w, top_stage(solid.nodes))
                add_weight(node_id, w)

    def seismic_share(case: str) -> float:
        return 1.0 if case in ("D", "SD") else bnbc.SEISMIC_LIVE_SHARE if case == "L" else 0.0

    def shell_pressure(shell: _Shell, case: str, pressure: float) -> None:
        """A uniform downward pressure (N/m²) on a shell, as its consistent nodal loads."""
        shares = shell_node_shares([b.coords[n] for n in shell.nodes])
        stage = top_stage(shell.nodes)
        for node_id, area in zip(shell.nodes, shares, strict=True):
            add_nodal(case, node_id, down * pressure * area, stage)
            add_weight(node_id, pressure * area * seismic_share(case))

    by_pair = {frozenset((m.i, m.j)): index for index, m in enumerate(b.members)}

    def shells_of_source(source: str) -> list[_Shell]:
        return [shell for shell in b.shells if shell.source == source]

    def line_load(
        source: str,
        case: str,
        p0: np.ndarray,
        p1: np.ndarray,
        load: float,
        share: float | None = None,
    ) -> bool:
        """A uniform line load (N/m, down) along ``p0``-``p1``: beams along it carry their part,
        the nodes on it the rest. False when part of it has no node to go to. ``share``: the part
        of it in the seismic weight (by default that of its case)."""
        w = seismic_share(case) if share is None else share
        axis = p1 - p0
        length = float(np.linalg.norm(axis))
        on_line = sorted(
            (float((xyz - p0) @ axis) / length**2, node_id)
            for node_id, xyz in b.coords.items()
            if _on_segment(xyz, p0, p1)
        )
        complete = bool(on_line) and on_line[0][0] < 1e-6 and on_line[-1][0] > 1 - 1e-6
        for (t0, n0), (t1, n1) in pairwise(on_line):
            span = (t1 - t0) * length
            index = by_pair.get(frozenset((n0, n1)))
            if index is not None:
                add_element_load(case, index, down * load)
                share_weight(index, load, w)
            else:
                for node_id in (n0, n1):
                    add_nodal(case, node_id, down * load * span / 2, stage_of(float(p0[2])))
                    add_weight(node_id, load * span / 2 * w)
        if not complete and case == "D":
            b.notes.append(
                f"{source}: part of its load has no beam, wall or column to go to; not applied"
            )
        return complete

    walls = {e.id for e in building.elements if isinstance(e, WallElement | AreaElement)}
    for shell in b.shells:
        if shell.source in walls:
            _, density, thickness = surface_sources[shell.source][1]
            if density:
                shell_pressure(shell, "D", density * G * thickness)

    for element, weight in partitions:
        if math.isclose(element.bottom, base) or not weight:
            continue  # stands on the foundation (Part 9)
        p0 = np.array([*element.start, element.bottom]) * MM
        p1 = np.array([*element.end, element.bottom]) * MM
        line_load(element.id, "D", p0, p1, weight)

    area_loads = {a.id: a for a in settings.areaLoads}
    for source, load_id in area_loads_of.items():
        area_load = area_loads.get(load_id) if load_id else None
        if load_id and area_load is None:
            b.notes.append(f"{source}: no area load '{load_id}' in the project settings")
        if area_load is None:
            continue
        for shell in shells_of_source(source):
            shell_pressure(shell, "SD", (area_load.finish + area_load.partitions) * 1e3)
            shell_pressure(shell, "L", area_load.live * 1e3)
    top = levels[-1] if levels else 0.0
    shells_of: dict[str, list[_Shell]] = {}
    for shell in b.shells:
        shells_of.setdefault(shell.source, []).append(shell)
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
        if element.id in shells_of:
            for case, pressure in pressures.items():
                for shell in shells_of[element.id] if pressure else []:
                    shell_pressure(shell, case, pressure)
            continue
        if shell_slabs:
            b.notes.append(
                f"{element.id}: no plate section (material or E missing); loads applied to its edges"
            )
        corners = [(x * MM, y * MM) for x, y in element.boundary]
        z = element.elevation * MM
        for case, pressure in pressures.items():
            if not pressure:
                continue
            for edge in fl.slab_edge_loads(corners, pressure, object_type.system):
                if edge.load:
                    p0 = np.array([*corners[edge.index], z])
                    p1 = np.array([*corners[(edge.index + 1) % len(corners)], z])
                    line_load(element.id, case, p0, p1, edge.load)

    # ── equipment of 07 MEP: its weight, contents and impact on the slabs it stands on ──
    b.notes.extend(mep_notes)
    if mep is not None and mep.equipment:
        from saengine.mep.loads import equipment_loads

        eq = equipment_loads(
            building,
            mep,
            b.coords,
            [(s.source, s.nodes) for s in b.shells],
            {
                e.id: types[e.type].system
                for e in building.elements
                if isinstance(e, SlabElement) and getattr(types.get(e.type), "kind", None) == "slab"
            },
            {m.id: m.mechanical.density for m in materials.materials},
            cases=CASES,
        )
        for load in eq.nodal:
            add_nodal(load.case, load.node, np.array(load.force))
            add_weight(load.node, load.weight)
        for line in eq.lines:
            line_load(
                line.source,
                line.case,
                np.array(line.start),
                np.array(line.end),
                line.load,
                share=line.weight_share,
            )
        b.notes += eq.notes

    # ── levels: the story elevations with nodes; nodes between count for the nearest ──
    above = [round(lv * MM, 6) for lv in levels if lv > base]
    level_nodes: dict[float, list[int]] = {h: [] for h in above}
    level_weight: dict[float, float] = dict.fromkeys(above, 0.0)
    for node_id, xyz in b.coords.items():
        if node_id in b.restraints or not above:
            continue
        nearest = min(above, key=lambda h: abs(h - xyz[2]))
        level_weight[nearest] += node_weight.get(node_id, 0.0)
        if abs(xyz[2] - nearest) < 1e-6:
            level_nodes[nearest].append(node_id)
    heights = [h for h in above if level_nodes[h]] if not special else []
    weights = [level_weight[h] for h in heights]

    # ── rigid diaphragms: each floor tied to a node at its centre of mass ──
    constraints: list[dict[str, Any]] = []
    if options.diaphragm == "rigid":
        for h in heights:
            tied = level_nodes[h]
            if len(tied) < 2:
                continue
            total = sum(node_weight.get(n, 0.0) for n in tied)
            centre = (
                sum(b.coords[n] * node_weight.get(n, 0.0) for n in tied) / total
                if total
                else sum(b.coords[n] for n in tied) / len(tied)
            )
            key = (round(centre[0] / MM), round(centre[1] / MM), round(centre[2] / MM))
            if key in b.nodes and b.nodes[key] in tied:
                retained = b.nodes[key]  # a node of the floor is at its centre
            else:
                retained = b.node(*key)
                b.restraints[retained] = list(_IN_PLAN)
            constraints.append(
                {
                    "type": "RigidDiaphragm",
                    "perp_dir": 3,
                    "retained_node": retained,
                    "constrained_nodes": sorted(n for n in tied if n != retained),
                }
            )

    # ── lateral loads: equivalent static story forces, shared among a level's nodes by weight ──
    values = derived(settings)
    base_m = base * MM
    hn = (heights[-1] - base_m) if heights else 0.0
    summary: dict[str, Any] = {"levels": len(heights), "weight_kN": sum(weights) / 1e3}
    if heights and values["Z"] and values["windSpeed"]:
        period = fl.approximate_period(hn, settings.seismic.system)
        sa = fl.design_acceleration(
            period, settings.site.siteClass, values["Z"], values["seismicImportance"], values["R"]
        )
        base_shear = sa * sum(weights)
        story_forces = fl.vertical_distribution(
            [(h - base_m, w) for h, w in zip(heights, weights, strict=True)], base_shear, period
        )
        xs = [xyz[0] for xyz in b.coords.values()]
        ys = [xyz[1] for xyz in b.coords.values()]
        extent_x, extent_y = (max(xs) - min(xs)) or 1.0, (max(ys) - min(ys)) or 1.0
        rel = [h - base_m for h in heights]
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
            nodes_here = level_nodes[h]
            total = sum(node_weight.get(n, 0.0) for n in nodes_here)
            for node_id in nodes_here:
                share = node_weight.get(node_id, 0.0) / total if total else 1 / len(nodes_here)
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
    elif special:
        b.notes.append(
            "special structure: no equivalent static wind or earthquake loads (they suit "
            "buildings with floors); gravity loads only for now"
        )
    else:
        b.notes.append(
            "no lateral loads: the building has no levels above its base, or the site has no Z or wind speed"
        )

    # ── project ──
    nodes = []
    for node_id, xyz in sorted(b.coords.items()):
        mass = node_weight.get(node_id, 0.0) / G
        restraint = b.restraints.get(node_id, [False] * 6)
        fixed = all(restraint)
        nodes.append(
            {
                "id": node_id,
                "name": "",
                "coords": [round(float(v), 6) for v in xyz],
                "mass": [0.0] * 6 if fixed else [mass, mass, 0.0, 0.0, 0.0, 0.0],
                "restraint": restraint,
            }
        )
    elements: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    def name(source: str) -> str:
        counts[source] = counts.get(source, 0) + 1
        return source if counts[source] == 1 else f"{source}#{counts[source]}"

    for member in b.members:
        elements.append(
            {
                "id": len(elements) + 1,
                "name": name(member.source),
                "type": "ElasticBeamColumn",
                "nodes": [member.i, member.j],
                "section_id": member.section,
                "geom_transf": "Linear",
                "rho": 0.0,
                "consistent_mass": False,
            }
        )
    for shell in b.shells:
        elements.append(
            {
                "id": len(elements) + 1,
                "name": name(shell.source),
                "type": "Shell",
                "formulation": "ASDShellQ4" if len(shell.nodes) == 4 else "ASDShellT3",
                "nodes": list(shell.nodes),
                "section_id": shell.section,
            }
        )
    for solid in b.solids:
        elements.append(
            {
                "id": len(elements) + 1,
                "name": name(solid.source),
                "type": "Solid",
                "formulation": "FourNodeTetrahedron",
                "nodes": list(solid.nodes),
                "material_id": solid.material,
            }
        )
    # The fluid case F only when it has loads (it is last, so the other cases keep their ids).
    cases = [c for c in CASES if c != "F" or patterns[c]["nodal"] or patterns[c]["element"]]
    load_patterns = []
    for number, case in enumerate(cases, start=1):
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
    element_stage: dict[int, int] = {}  # analysis element id -> construction stage
    if staged:
        for e in elements:
            element_stage[e["id"]] = top_stage(e["nodes"])
    stage_pattern_ids: dict[int, int] = {}
    for k in sorted(stage_patterns):
        pattern = stage_patterns[k]
        stage_pattern_ids[k] = len(load_patterns) + 1
        load_patterns.append(
            {
                "id": stage_pattern_ids[k],
                "name": f"D, stage {k + 1}",
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
        for number, case in enumerate(cases, start=1)
    ]
    dead_preload = CASES.index("D") + 1  # the dead load case time histories start from
    if staged:
        stages = []
        for k, height in enumerate(stage_levels):
            built = sorted(i for i, stage in element_stage.items() if stage == k)
            loads = [stage_pattern_ids[k]] if k in stage_pattern_ids else []
            if built or loads:
                stages.append(
                    {
                        "name": f"Level {k + 1} (+{height:.2f} m)",
                        "element_ids": built,
                        "pattern_ids": loads,
                    }
                )
        dead = analyses[CASES.index("D")]
        analyses[CASES.index("D")] = {
            "id": dead["id"],
            "name": f"D: {bnbc.LOAD_CASES['D']}, construction sequence",
            "type": "Staged",
            "stages": stages,
            "system": "BandGeneral",
            "constraints": "Plain",
        }
        dead_preload = len(analyses) + 1
        analyses.append(
            {
                **dead,
                "id": dead_preload,
                "name": f"D0: {bnbc.LOAD_CASES['D']}, applied at once",
            }
        )
        b.notes.append(
            f"construction sequence: the self-weight D is applied in {len(stages)} stages, one "
            "per level, each to the storeys built by then (linear, elements enter stress-free); "
            "D0 is the same load on the completed building, the start of the time histories"
        )
    time_series: list[dict[str, Any]] = [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}]
    spectra: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    if any(node_weight.values()):
        modal_id = len(analyses) + 1
        analyses.append(
            {
                "id": modal_id,
                "name": "Modal",
                "type": "Modal",
                "n_modes": max(1, min(12, 3 * len(heights))),
                "solver": "auto",
            }
        )
        # ── response spectrum: the BNBC design spectrum (already reduced by R), in m/s² ──
        if options.responseSpectrum and values["Z"]:
            periods = list(SPECTRUM_PERIODS)
            spectra.append(
                {
                    "id": 1,
                    "name": "BNBC design spectrum",
                    "type": "ResponseSpectrum",
                    "periods": periods,
                    "accelerations": [
                        round(
                            G
                            * fl.design_acceleration(
                                t,
                                settings.site.siteClass,
                                values["Z"],
                                values["seismicImportance"],
                                values["R"],
                            ),
                            6,
                        )
                        for t in periods
                    ],
                    "damping_ratio": 0.05,
                }
            )
            for direction, axis in ((1, "X"), (2, "Y")):
                analyses.append(
                    {
                        "id": len(analyses) + 1,
                        "name": f"R{axis}: Response spectrum {axis}",
                        "type": "ResponseSpectrum",
                        "modal_case_id": modal_id,
                        "spectrum_id": 1,
                        "direction": direction,
                        "combination": "CQC",
                        "damping_ratio": 0.05,
                    }
                )
        # ── time histories: each record after the dead loads (D, SD) ──
        for history in options.timeHistories:
            record = _ground_motion(history, len(records) + 1, model_dir)
            if isinstance(record, str):
                b.notes.append(f"time history '{history.name}' left out: {record}")
                continue
            records.append(record)
            series_id = len(time_series) + 1
            time_series.append(
                {
                    "id": series_id,
                    "name": history.name,
                    "type": "Path",
                    "factor": history.scale * (G if history.units == "g" else 1.0),
                    "dt": record["dt"],
                    "record_id": record["id"],
                }
            )
            pattern_id = len(load_patterns) + 1
            load_patterns.append(
                {
                    "id": pattern_id,
                    "name": history.name,
                    "type": "UniformExcitation",
                    "direction": 1 if history.direction == "X" else 2,
                    "accel_series_id": series_id,
                }
            )
            analyses.append(
                {
                    "id": len(analyses) + 1,
                    "name": f"TH: {history.name}",
                    "type": "Transient",
                    "pattern_ids": [pattern_id],
                    "dt": record["dt"],
                    "n_steps": record["npts"],
                    "system": "BandGeneral",
                    "algorithm": "Newton",
                    "rayleigh_mode1_damping": history.damping,
                    "preload_case_ids": [dead_preload, CASES.index("SD") + 1],
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
        "materials": b.materials,
        "sections": b.sections,
        "elements": elements,
        "mp_constraints": constraints,
        "time_series": time_series,
        "load_patterns": load_patterns,
        "analyses": analyses,
        "spectra": spectra,
        "ground_motions": records,
    }
    summary.update(
        {
            "nodes": len(nodes),
            "elements": len(elements),
            "frames": len(b.members),
            "shells": len(b.shells),
            "solids": len(b.solids),
            "diaphragms": len(constraints),
            "supports": sum(1 for r in b.restraints.values() if all(r)),
        }
    )
    pushover = None
    if options.pushover is not None:
        from saengine.fem.nonlinear import pushover_model

        keys = {sid: key for key, sid in b.section_ids.items() if key[0] not in ("plate", "embed")}
        pushover, more = pushover_model(
            project, keys, types, mats, node_weight, base * MM, options.pushover
        )
        b.notes.extend(more)

    # ── the temperature case T (after the pushover copy, which has none) ──
    thermal_corrections = None
    if options.thermal.enabled:
        from saengine.fem.thermal import (
            ThermalOptions,
            add_thermal_case,
            exposed_elements,
            thermal_sections,
        )

        keys = {sid: key for key, sid in b.section_ids.items()}
        t = options.thermal
        case = add_thermal_case(
            project,
            thermal_sections(keys, types, mats),
            ThermalOptions(t.uniform, t.gradient, t.scope),
            # Every roof: the main roof and any stair, lift-machine or tank room roof above it
            # (the horizontal members and shells with nothing above them).
            roof_elements=exposed_elements(project),
        )
        b.notes.extend(case.notes)
        thermal_corrections = case.corrections
        if not any(c.T for c in settings.combinations):
            b.notes.append(
                "temperature: no load combination has a T factor, so T is analysed but not "
                "designed for; add 1.2D ± 1.2T + 1.6L + 0.5Lr (BNBC 2020 Part 6 Sec 2.7.3.1; "
                "Project Settings, Reset Combinations adds them)"
            )
        if not thermal_corrections["frames"] and not thermal_corrections["shells"]:
            b.notes.append("temperature: no member is heated (ΔTu and ΔTg are 0 where they apply)")

    # ── soil-structure interaction: the column bases on their foundations' springs ──
    ssi_json = None
    mode = column_supports or getattr(options, "supports", "fixed")
    if mode == "soilSprings" and not special:
        if substructure is None or not getattr(substructure, "foundations", None):
            b.notes.append(
                "soil springs: 9 Substructure has no foundations yet; the column bases stay fixed"
            )
        else:
            from saengine.fem import ssi

            spring_options = ssi.options_from_settings(settings)
            spring_options.supports = "soilSprings"
            r = ssi.apply_soil_springs(
                project,
                building,
                substructure,
                soil_text,
                materials,
                ground_level=settings.foundation.groundLevel,
                acceleration=ssi.peak_acceleration(settings),
                options=spring_options,
                soil_unit_weight=settings.foundation.soilUnitWeight,
            )
            project = r.project
            b.notes.extend(r.notes)
            ssi_json = r.to_json()
            summary["supports"] = sum(
                1 for n in project["nodes"] if all(n.get("restraint") or [False])
            )
            summary["springs"] = len(r.foundations)
            summary["nodes"] = len(project["nodes"])
            summary["elements"] = len(project["elements"])
    return Derivation(
        project=project,
        notes=b.notes,
        summary=summary,
        pushover=pushover,
        thermal=thermal_corrections,
        ssi=ssi_json,
    )


def _rectangle(opening: Any, z: float) -> list[tuple[float, float, float]]:
    """Corners of a rectangular slab opening at elevation ``z`` (mm)."""
    angle = math.radians(opening.rotation)
    ux = np.array([math.cos(angle), math.sin(angle)])
    uy = np.array([-math.sin(angle), math.cos(angle)])
    centre = np.array([opening.x, opening.y])
    corners: Sequence[tuple[float, float]] = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    return [
        (*(centre + sx * opening.xDim / 2 * ux + sy * opening.yDim / 2 * uy), z)
        for sx, sy in corners
    ]


def _embed(b: _Builder) -> None:
    """Frames and shells meeting a solid share nodes with it, but a solid's nodes have no
    rotations: a column standing on a block would be pinned to it. Each node a frame or a shell
    shares with a solid gets a short elastic strut to every solid node next to it (in a
    tetrahedron with it): square, as wide as the block's elements are long, of the block's
    material. Together they carry the frame's or the shell's moments into the solid."""
    solid_nodes = {n for solid in b.solids for n in solid.nodes}
    joints = {n for m in b.members for n in (m.i, m.j)} | {n for sh in b.shells for n in sh.nodes}
    embedded = joints & solid_nodes
    if not embedded:
        return
    neighbours: dict[int, set[int]] = {}
    block_of: dict[int, _Solid] = {}
    for solid in b.solids:
        for n in solid.nodes:
            neighbours.setdefault(n, set()).update(solid.nodes)
            block_of.setdefault(n, solid)
    struts: dict[str, int] = {}
    for node in sorted(embedded):
        solid = block_of[node]
        if solid.source not in struts:
            edges = [
                float(np.linalg.norm(b.coords[x] - b.coords[y]))
                for t in b.solids
                if t.source == solid.source
                for x, y in itertools.combinations(t.nodes, 2)
            ]
            h = float(np.mean(edges))
            material = b.materials[solid.material - 1]
            e, nu = material["E"], material["nu"]
            struts[solid.source] = len(b.sections) + 1
            b.section_ids[("embed", solid.source)] = struts[solid.source]
            b.sections.append(
                {
                    "id": struts[solid.source],
                    "name": f"{solid.source} embedding strut",
                    "type": "ElasticSection",
                    "E": e,
                    "A": h**2,
                    "Iz": h**4 / 12,
                    "Iy": h**4 / 12,
                    "G": e / (2 * (1 + nu)),
                    "J": 0.141 * h**4,
                }
            )
        for other in sorted(neighbours[node] - {node}):
            b.members.append(
                _Member(f"{solid.source}/embed", node, other, struts[solid.source], 0.0, 0.0)
            )
    b.notes.append(
        f"{len(embedded)} frame or shell nodes on solids are tied into them with embedding struts"
    )


def _in_polygon(point: np.ndarray, polygon: list[np.ndarray], normal: np.ndarray) -> bool:
    """Whether ``point`` (in the polygon's plane) lies inside or on the polygon."""
    u = polygon[1] - polygon[0]
    u = u / np.linalg.norm(u)
    v = np.cross(normal, u)
    flat = [(float((q - polygon[0]) @ u), float((q - polygon[0]) @ v)) for q in polygon]
    x, y = float((point - polygon[0]) @ u), float((point - polygon[0]) @ v)
    inside = False
    for (x0, y0), (x1, y1) in zip(flat, flat[1:] + flat[:1], strict=True):
        if _on_segment(np.array([x, y, 0.0]), np.array([x0, y0, 0.0]), np.array([x1, y1, 0.0])):
            return True
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def _on_segment(point: np.ndarray, a: np.ndarray, b: np.ndarray, tolerance: float = 1e-3) -> bool:
    """Whether ``point`` lies on the segment from ``a`` to ``b`` (within ``tolerance`` metres)."""
    axis = b - a
    length2 = float(axis @ axis)
    t = float((point - a) @ axis / length2) if length2 else 0.0
    return -1e-6 <= t <= 1 + 1e-6 and float(np.linalg.norm(a + t * axis - point)) <= tolerance

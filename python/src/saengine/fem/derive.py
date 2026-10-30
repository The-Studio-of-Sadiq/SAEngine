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
- steel beams and braces whose type has a simple connection (fin plate, end plate, gusset) are
  pinned at their ends (:func:`_release_simple_ends`, zero-length links stiff in translation
  only): their end moments are released, so the analysis matches the connection the design
  checks;
- wind and earthquake are equivalent static story forces (:mod:`saengine.fem.loads`) at the
  levels, shared among a level's nodes by their weight; each node's weight also gives its
  lumped mass. Nodes between levels (wall meshes) count towards the nearest level's weight.

Load combinations are not part of the analysis model (OpenSees Studio has no combination
object): the analysis runs each load case once and the combinations of the project settings
are formed from those results, which is exact for this linear elastic model.

Options of the settings (``analysis``; absent: the behaviour before version 0.0.44):

- ``massLumping``: "storyLevels" lumps every node's weight at the nearest story level (the
  lower half of the first storey goes to the base and does not participate), "levelAbove"
  leaves the masses at the nodes; the summary reports W per level and how it was formed
  (``seismicWeight``). ``massSource``: factors on the dead and superimposed dead loads, the
  live share (by default the code pack's: 25 %, 50 % above 3 kN/m², BNBC 2020 Part 6 Sec
  2.5.7.3) and extra masses;
- ``accidentalEccentricity``: the static cases EXP, EXN, EYP, EYN (Sec 2.5.7.6.2);
- ``periodMethod``: "approximate" (Ta, eq. 6.2.38) or "analysis" (the modal period, at most
  1.4 Ta, Sec 2.5.7.2 (a));
- ``meshBySpan``: shell slabs no coarser than their shorter span / 8;
- ``endOffsets`` and ``rigidZoneFactor``: rigid end zones of beams and columns, forces at the
  support faces (:mod:`saengine.fem.end_zones`).

Columns turned by other than a multiple of 90° are analysed at their angle (their elements'
``vecxz``). Known simplifications are reported as notes: stairs are not in the stiffness model,
and inclined members rotated by other than a multiple of 90° use the nearest one.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from saengine.codes import context as code_context
from saengine.fem import loads as fl
from saengine.fem import slab_load_shapes as sls
from saengine.fem.mesh import Surface, Volume, mesh, shell_node_shares
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

if TYPE_CHECKING:
    from saengine.fem import pattern_live

G = 9.80665  # m/s²
MM = 0.001  # m per mm
#: Nodes this close [m] to equally near levels count as half way between them (mass lumping).
TIE_M = 1e-6
UNITS = "SI (m, N, kg, s, Pa)"

#: Load cases of the analysis model, in this order (see bnbc.LOAD_CASES). The fluid case F (the
#: contents of equipment in 07 MEP) is last and is only in a model that has fluid loads, so the
#: other cases keep their numbers. The temperature case T is added after them when the settings
#: ask for it (:mod:`saengine.fem.thermal`).
CASES = ["D", "SD", "L", "Lr", "WX", "WY", "EX", "EY", "F"]

#: The equation solver of every analysis case. Rigid diaphragms tie each floor's master node to
#: all of that floor's shell nodes, so a banded solver's band spans the floor: BandGeneral needed
#: gigabytes (and failed) on a 10-storey flat plate at the 500 mm mesh, where the sparse UmfPack
#: solves it in seconds with the same displacements.
SOLVER = "UmfPack"

#: Restraint of a diaphragm's own node: free in plan, held out of plane.
_IN_PLAN = [False, False, True, True, True, False]

#: The static earthquake cases with the accidental eccentricity of BNBC 2020 Part 6 Sec
#: 2.5.7.6.2 (p. 630, eq. 6.2.43: M_ta,i = e_ai·F_i, e_ai = ±0.05·L_i, the same direction at
#: every floor): case -> (its earthquake case, sign of the shift of the storey masses along
#: the axis across the force: +Y for EX, +X for EY). After the other cases, when the settings
#: ask for them (``analysis.accidentalEccentricity``).
ECCENTRIC_CASES: dict[str, tuple[str, int]] = {
    "EXP": ("EX", 1),
    "EXN": ("EX", -1),
    "EYP": ("EY", 1),
    "EYN": ("EY", -1),
}
_CASE_LABELS = {
    "EXP": "Earthquake in X, masses shifted +5 % along Y",
    "EXN": "Earthquake in X, masses shifted -5 % along Y",
    "EYP": "Earthquake in Y, masses shifted +5 % along X",
    "EYN": "Earthquake in Y, masses shifted -5 % along X",
    "WTX": "Torsion of the wind in X (BNBC 2020 Part 6 Figure 6.2.9, e = 0.15 B)",
    "WTY": "Torsion of the wind in Y (BNBC 2020 Part 6 Figure 6.2.9, e = 0.15 B)",
}

#: Seismic weight (BNBC 2020 Part 6 Sec 2.5.7.3, p. 628): live loads above 3 kN/m² (the pack's
#: ``seismic.heavyLiveLimit``) count with at least 50 % (``seismic.heavyLiveShare``, this the
#: default), the others with the pack's ``liveShare`` (25 %). The rule applies only once the
#: pack holds ``heavyLiveLimit`` (a pack without it keeps the W of earlier versions).
HEAVY_LIVE_SHARE = 0.5
#: BNBC 2020 Part 6 Sec 2.5.7.2 (a) (p. 627): a period from the structure's properties shall not
#: exceed the approximate period (eq. 6.2.38) by more than 40 percent. Default until the code
#: pack holds it (``seismic.periodUpperFactor``).
PERIOD_UPPER_FACTOR = 1.4
#: Smallest shell element the span rule of the mesh gives [mm].
MIN_SPAN_MESH = 200.0
#: The mesh size rule: shell slabs no coarser than their shorter span over this.
SPAN_DIVISIONS = 8


def option(part: Any, name: str, default: Any) -> Any:
    """``part.name`` when the settings have it (and it is not None), else ``default``: the
    settings of this round are added by the integrator; until then today's behaviour holds."""
    value = part.get(name) if isinstance(part, dict) else getattr(part, name, None)
    return default if value is None else value


def quarter_turns(rotation: float) -> int | None:
    """Quarter turns of a column's ``rotation`` [°] when it is a multiple of 90°, else None
    (the column is then analysed at its own angle, :func:`column_vecxz`)."""
    turns = round(rotation / 90)
    return turns if abs(rotation - 90 * turns) <= 1e-6 else None


def analysed_turns(rotation: float, exact: bool) -> int:
    """The quarter turns by which the analysis swaps a column's section: with ``exact``
    (``analysis.exactColumnRotation``) only a multiple of 90° swaps it (any other angle turns
    the element's axes instead, :func:`column_vecxz`: 0 turns); without it the angle rounded to
    quarter turns, as before. The design and slenderness must use the same rule:
    ``analysed_turns(rotation, exact) % 2 == 1`` is a column whose axes are swapped."""
    turns = quarter_turns(rotation)
    if exact:
        return turns or 0
    return round(rotation / 90)


def column_vecxz(rotation: float) -> tuple[float, float, float] | None:
    """The ``vecxz`` of a vertical member turned by ``rotation`` [°] (not a multiple of 90°):
    the profile's x axis in plan, so the local axes follow the profile (local z along its x
    axis, as an unturned column's local z is global X). None for a multiple of 90° (the quarter
    turns swap the section's inertias instead, and the runner's own vecxz is used)."""
    if quarter_turns(rotation) is not None:
        return None
    angle = math.radians(rotation)
    return (round(math.cos(angle), 12), round(math.sin(angle), 12), 0.0)


def case_label(case: str) -> str:
    """The description of a load case: the code pack's, or that of an eccentric case."""
    labels = code_context.table("combinations").loadCases
    try:
        return labels[case]
    except (KeyError, TypeError):
        return _CASE_LABELS.get(case, case)


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
#: labels of its items are left out, as are the MEP IFC models. The plumbing's overhead tanks
#: (which load the model) are stamped as ``plumbingTanks``, the HVAC plant as ``hvacPlant`` and
#: the electrical equipment as ``electricalEquipment`` (with the supply's ``transformerType``,
#: which gives a transformer's typical weight, as ``transformerType``), the fire pumps as
#: ``firePumps`` (with the supply's ``standby``, which gives a standby set's typical weight, as
#: ``fireStandby``) and the overhead fire tanks as ``fireTanks`` when there are any.
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
    plumbing = document.get("plumbing")
    tanks = plumbing.get("tanks") if isinstance(plumbing, dict) else None
    overhead = (
        [t for t in tanks if isinstance(t, dict) and t.get("kind") == "overhead"]
        if isinstance(tanks, list)
        else []
    )
    if overhead:
        content["plumbingTanks"] = overhead
    hvac = document.get("hvac")
    plant = hvac.get("plant") if isinstance(hvac, dict) else None
    if isinstance(plant, list) and plant:
        content["hvacPlant"] = _unlabelled(plant)
    electrical = document.get("electrical")
    items = electrical.get("equipment") if isinstance(electrical, dict) else None
    if isinstance(items, list) and items:
        content["electricalEquipment"] = _unlabelled(items)
        supply = electrical.get("supply")
        if isinstance(supply, dict) and "transformerType" in supply:
            content["transformerType"] = supply["transformerType"]
    fire = document.get("fire")
    pumps = fire.get("pumps") if isinstance(fire, dict) else None
    if isinstance(pumps, list) and pumps:
        content["firePumps"] = _unlabelled(pumps)
        supply = fire.get("supply")
        if isinstance(supply, dict) and "standby" in supply:
            content["fireStandby"] = supply["standby"]
    fire_tanks = fire.get("tanks") if isinstance(fire, dict) else None
    fire_overhead = (
        [t for t in fire_tanks if isinstance(t, dict) and t.get("kind") == "overhead"]
        if isinstance(fire_tanks, list)
        else []
    )
    if fire_overhead:
        content["fireTanks"] = fire_overhead
    return stamp(js_json(content))


#: Keys of ``02 Project Settings/project-settings.json`` the analysis model does not take: the
#: project's details and the drawings' title block (the model's name is only a label).
SETTINGS_INFO_KEYS = ("project", "drawings")


def settings_stamp(text: str) -> str:
    """The stamp an analysis model records for the project settings (key ``settings``): of the
    settings without :data:`SETTINGS_INFO_KEYS`, so typing the engineer's name or a revision
    leaves the model current. The workbench computes the same (``femSettingsStamp`` in
    partSources.ts); a text that is not a JSON object is stamped whole."""
    import json

    try:
        document = json.loads(text)
    except ValueError:
        return stamp(text)
    if not isinstance(document, dict):
        return stamp(text)
    return stamp(js_json({k: v for k, v in document.items() if k not in SETTINGS_INFO_KEYS}))


#: The stamps worked out last, by a hash of the model's raw text (a 10-storey model takes
#: seconds to stamp, and Run All's steps stamp the same file many times).
_MODEL_STAMPS: dict[bytes, str] = {}


def model_stamp(data: bytes | str) -> str:
    """The stamp of an analysis model's text without its ``meta`` (its name and the stamps of
    the sources it was derived from): what the solver computes from, so a model derived again
    to the same analysis keeps its results and the runs made from them (Run All's kept
    analysis, the design checks' cache, the response spectrum design). The workbench computes
    the same (``femModelStamp`` in runAll.ts); a text that is not a JSON object is stamped
    whole."""
    import hashlib
    import json

    raw = data if isinstance(data, bytes) else data.encode("utf-8", errors="surrogatepass")
    key = hashlib.sha1(raw).digest()
    found = _MODEL_STAMPS.get(key)
    if found is not None:
        return found
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    try:
        document = json.loads(text)
    except ValueError:
        result = stamp(text)
    else:
        result = (
            stamp(js_json({k: v for k, v in document.items() if k != "meta"}))
            if isinstance(document, dict)
            else stamp(text)
        )
    if len(_MODEL_STAMPS) >= 8:
        _MODEL_STAMPS.clear()
    _MODEL_STAMPS[key] = result
    return result


def _unlabelled(items: list[Any]) -> list[Any]:
    return [
        {k: v for k, v in item.items() if k not in _MEP_LABELS} if isinstance(item, dict) else item
        for item in items
    ]


@dataclass
class _Member:
    """A frame element of the analysis model: its SAEngine element, ends and section."""

    source: str
    i: int
    j: int
    section: int
    density: float  # kg/m³
    area: float  # m²
    #: The local x-z plane vector of a column turned by other than a multiple of 90°.
    vecxz: tuple[float, float, float] | None = None
    #: Rigid end zones at i and j [m] (along the member, :mod:`saengine.fem.end_zones`).
    rigid: tuple[float, float] = (0.0, 0.0)


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
    #: The member end offsets (``08 FEM/faces.json``, :mod:`saengine.fem.end_zones`), when the
    #: settings model end offsets.
    faces: dict[str, Any] | None = None


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
        #: Per section id the properties its stiffness modifiers set (no cracked factor on top).
        self.modified: dict[int, set[str]] = {}

    def node(self, x_mm: float, y_mm: float, z_mm: float) -> int:
        key = (round(x_mm), round(y_mm), round(z_mm))
        if key not in self.nodes:
            node_id = len(self.nodes) + 1
            self.nodes[key] = node_id
            self.coords[node_id] = np.array(key, dtype=float) * MM
        return self.nodes[key]


def local_axes(
    a: np.ndarray, b: np.ndarray, vecxz: Sequence[float] | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The element axes OpenSees Studio uses: from the element's own ``vecxz`` when it has one,
    else the runner's (picked from the element axis)."""
    x = (b - a) / np.linalg.norm(b - a)
    if vecxz is not None:
        vecxz = np.asarray(vecxz, dtype=float)
    elif abs(x[2]) > abs(x[0]):
        vecxz = np.array([1.0, 0, 0])
    else:
        vecxz = np.array([0, 0, 1.0])
    y = np.cross(vecxz, x)
    y /= np.linalg.norm(y)
    return x, y, np.cross(x, y)


def member_axes(axes: np.ndarray) -> np.ndarray:
    """The member axes 1, 2, 3 results are shown in (rows), from an element's analysis axes
    (rows x, y, z of :func:`local_axes`).

    The analysis gives a horizontal member local z up and its strong-axis inertia in Iy, so its
    gravity bending is My and its vertical shear Vz. Shown as the engineer reads them (axis 2
    up, gravity bending M3 and shear V2, as a column's strong-axis bending is M3), such a member
    is turned a quarter about its axis: 2 = z, 3 = -y. A member whose local y is the nearer to
    vertical (a column: neither is) keeps its axes. The design reads the analysis axes."""
    x, y, z = np.asarray(axes, dtype=float)
    if abs(z[2]) > abs(y[2]) + 1e-9:
        return np.array([x, z, -y])
    return np.array([x, y, z])


def to_member_axes(forces: np.ndarray, axes: np.ndarray) -> np.ndarray:
    """Section forces ``[..., N, Vy, Vz, T, My, Mz]`` in an element's analysis axes turned to
    its :func:`member_axes` (``[..., P, V2, V3, T, M2, M3]``)."""
    forces = np.asarray(forces, dtype=float)
    turn = member_axes(axes) @ np.asarray(axes, dtype=float).T
    return np.concatenate([forces[..., :3] @ turn.T, forces[..., 3:6] @ turn.T], axis=-1)


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
    member_loads: Any = None,
    architecture: Any = None,
) -> Derivation:
    """The OpenSees Studio project of ``building`` with the loads of ``settings``, under the
    project's code pack (``settings.codePack``; its project-local packs looked for in the
    project of :func:`saengine.codes.context.project`, else the one holding ``model_dir``).
    ``architecture``: the project's architecture (``05 Floor Plan/architecture.json``), read
    beside ``model_dir`` (``08 FEM``) when not given; ``False`` for none. See
    :func:`_derive_fem`."""
    if architecture is None and model_dir is not None:
        architecture = read_architecture(Path(model_dir).parent)
    root = code_context.project_root() or code_context.find_project_root(model_dir)
    with code_context.using(code_context.pack_for(settings, root)):
        return _derive_fem(
            building,
            objects,
            materials,
            settings,
            sources,
            model_dir,
            mep,
            substructure,
            soil_text,
            column_supports,
            member_loads,
            architecture or None,
        )


def read_architecture(project_root: str | Path) -> Any:
    """The architecture of the project at ``project_root`` when it has walls or rooms (whose
    loads the model takes), else None; an unreadable file is None too (Architecture reports
    it)."""
    from saengine.fem.architecture_loads import has_loads
    from saengine.library import architecture as arch_lib

    try:
        text = (Path(project_root) / arch_lib.ARCHITECTURE_FILE).read_text(encoding="utf-8")
        arch = arch_lib.parse(text)
    except (OSError, ValueError):
        return None
    return arch if has_loads(arch) else None


def _derive_fem(
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
    member_loads: Any = None,
    architecture: Any = None,
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

    ``architecture`` (:class:`saengine.library.architecture.Architecture`): its walls load the
    beams and slabs under them and its rooms set their finish and live loads
    (:mod:`saengine.fem.architecture_loads`; ``analysis.partitionLoads``).
    """
    mep_notes: list[str] = []
    if mep is not None:
        from saengine.mep.loads import with_mep_openings, with_services_equipment

        building, mep_notes = with_mep_openings(building, mep)
        # The plumbing's overhead tanks, the HVAC plant and the electrical equipment load the
        # model as equipment (each never counted twice).
        mep, service_notes = with_services_equipment(mep, materials)
        mep_notes += [f"MEP: {note}" for note in service_notes]
    b = _Builder()
    options = settings.analysis
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    levels = sorted({s.elevation for s in building.stories})
    base = levels[0] if levels else 0.0
    # Stiffness modifiers per element (saengine.library.modifiers): the member's over its type's.
    from saengine.library.modifiers import resolve_modifiers

    modifiers_of: dict[str, dict[str, float]] = {}
    for element in building.elements:
        found = resolve_modifiers(element, types.get(element.type))
        if found:
            modifiers_of[element.id] = {k: v for k, (v, _) in found.items()}
    if modifiers_of:
        b.notes.append(
            f"stiffness modifiers: {len(modifiers_of)} element(s) with the engineer's factors "
            "(they replace the code's cracked factors of those properties, in every case)"
        )
    # Special structures (drawn in 3D, Part 5 structural model) have explicit supports and no
    # floors: no base fixity by level, no diaphragms, no story forces.
    special = building.source is not None and building.source.structure is not None

    def poisson(material: Any) -> float:
        nu = material.mechanical.nu
        return nu if nu is not None else (0.2 if material.category.value == "concrete" else 0.3)

    def section(
        type_id: str, quarter_turns: int, vertical: bool, mods: dict[str, float] | None = None
    ) -> tuple[int, float, float] | None:
        """Elastic section of an object type in a member along or across the vertical.

        OpenSees Studio picks the local axes from the member's direction: a vertical member's
        local z is global X, a horizontal member's local z is global Z (up). The profile's x-axis
        inertia (``ixx``: about its width, the strong axis of a beam) goes in Iz for a vertical
        member and in Iy for a horizontal one; quarter turns of a column swap the axes.
        ``mods``: stiffness modifiers (A, J, I33 on the profile's x-axis, I22 on its y-axis).
        """
        object_type = types.get(type_id)
        material = mats.get(object_type.material) if object_type else None
        if object_type is None or material is None or not hasattr(object_type, "profile"):
            return None
        mech = material.mechanical
        if not mech.E:
            return None
        stiff = {k: v for k, v in (mods or {}).items() if k in ("A", "J", "I22", "I33")}
        key = (type_id, quarter_turns % 2, vertical, *sorted(stiff.items()))
        if key not in b.section_ids:
            props = section_properties(object_type.profile)
            about_x = props.ixx * MM**4 * stiff.get("I33", 1.0)
            about_y = props.iyy * MM**4 * stiff.get("I22", 1.0)
            names = ("I33", "I22")
            if quarter_turns % 2:
                about_x, about_y = about_y, about_x
                names = ("I22", "I33")
            iz, iy = (about_x, about_y) if vertical else (about_y, about_x)
            slots = dict(zip(("Iz", "Iy") if vertical else ("Iy", "Iz"), names, strict=True))
            b.section_ids[key] = len(b.sections) + 1
            kept = {slot for slot, name in slots.items() if name in stiff}
            if kept:
                b.modified[b.section_ids[key]] = kept
            b.sections.append(
                {
                    "id": b.section_ids[key],
                    "name": f"{type_id} {'column' if vertical else 'beam'}"
                    + (" (rotated)" if quarter_turns % 2 else "")
                    + (" (modified)" if stiff else ""),
                    "type": "ElasticSection",
                    "E": mech.E * 1e6,
                    "A": props.area * MM**2 * stiff.get("A", 1.0),
                    "Iz": iz,
                    "Iy": iy,
                    "G": mech.E * 1e6 / (2 * (1 + poisson(material))),
                    "J": props.j * MM**4 * stiff.get("J", 1.0),
                }
            )
        return (
            b.section_ids[key],
            (mech.density or 0.0),
            section_properties(object_type.profile).area * MM**2,
        )

    def plate(
        type_id: str, mods: dict[str, float] | None = None
    ) -> tuple[int, float, float] | None:
        """Plate section of a wall or slab type: (section id, density, thickness m); ``mods``:
        stiffness modifiers (``membrane`` on E, ``bending`` on the plate bending)."""
        object_type = types.get(type_id)
        material = mats.get(object_type.material) if object_type else None
        if object_type is None or material is None or not material.mechanical.E:
            return None
        thickness = object_type.thickness * MM
        stiff = {k: v for k, v in (mods or {}).items() if k in ("membrane", "bending")}
        key = ("plate", type_id, *sorted(stiff.items()))
        if key not in b.section_ids:
            b.section_ids[key] = len(b.sections) + 1
            membrane = stiff.get("membrane", 1.0)
            plate_section = {
                "id": b.section_ids[key],
                "name": f"{type_id} {object_type.kind}" + (" (modified)" if stiff else ""),
                "type": "ElasticMembranePlateSection",
                "E": material.mechanical.E * 1e6 * membrane,
                "nu": poisson(material),
                "h": thickness,
                # The mass is lumped at the nodes with the loads, as for the frames.
                "rho": 0.0,
            }
            if stiff:
                plate_section["Ep_mod"] = stiff.get("bending", 1.0) / membrane
                b.modified[b.section_ids[key]] = {
                    *(["E"] if "membrane" in stiff else []),
                    *(["Ep_mod"] if "bending" in stiff else []),
                }
            b.sections.append(plate_section)
        return b.section_ids[key], material.mechanical.density or 0.0, thickness

    # ── geometry: frames as lines, structural walls (and shell slabs) as surfaces ──
    lines: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = []
    line_sources: dict[str, tuple[str, tuple[int, float, float]]] = {}
    surfaces: list[Surface] = []
    surface_sources: dict[str, tuple[str, tuple[int, float, float]]] = {}
    supports: list[tuple[float, float, float]] = []
    partitions: list[tuple[WallElement, float]] = []  # non-structural walls, N/m

    member_vecxz: dict[str, tuple[float, float, float]] = {}
    exact_angles = bool(option(options, "exactColumnRotation", False))
    for element in building.elements:
        if not isinstance(element, ColumnElement):
            continue
        # A multiple of 90° swaps the section's axes; with exactColumnRotation any other angle
        # turns the element's own axes with the profile (its vecxz), so the column is analysed
        # at its true angle; without it (old projects, until the design reads the same axes) the
        # angle is rounded to quarter turns, as before.
        vecxz = column_vecxz(element.rotation) if exact_angles else None
        turns = analysed_turns(element.rotation, exact_angles)
        if vecxz is not None:
            member_vecxz[element.id] = vecxz
        elif abs(element.rotation - 90 * turns) > 1e-6:
            b.notes.append(
                f"{element.id}: rotation {element.rotation}° is analysed as "
                f"{90 * turns % 360}° (exactColumnRotation is off)"
            )
        sec = section(element.type, turns, True, modifiers_of.get(element.id))
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
    # Line and point loads of 05 Floor Plan/loads.json (saengine.fem.member_loads): beams are
    # split where point loads sit, so each has its node.
    from saengine.fem import member_loads as ml

    member_set = (
        ml.member_loads(building, member_loads)
        if member_loads is not None and member_loads.loads
        else None
    )
    cuts = ml.split_points(member_set) if member_set is not None else {}
    # The architecture's walls and rooms (saengine.fem.architecture_loads): beams are split
    # where a wall's piece on them starts or stops.
    from saengine.fem import architecture_loads as al

    partition_mode = str(option(options, "partitionLoads", "architecture"))
    arch_set = (
        al.architecture_loads(architecture, building, objects, partition_mode)
        if al.has_loads(architecture)
        else None
    )
    if arch_set is not None:
        for member, points in arch_set.cuts.items():
            found = cuts.setdefault(member, [])
            found += [p for p in points if p not in found]
    # Beams that carry slabs' load shapes (slabs not in the model as plates): cut into members
    # of the mesh size, so the triangles and trapezoids reach their moments
    # (saengine.fem.slab_load_shapes.division_points). The end members keep the joint zone
    # whole (slab_load_shapes.joint_clearance), so the rigid end zones of the end offsets are
    # not capped at a share of a short piece (_rigid_end_zones).
    if options.slabs != "shells":
        from saengine.fem.end_zones import support_reach

        beam_size = float(options.meshSize) * float(option(options, "meshScale", 1.0))
        zone_factor = (
            float(option(options, "rigidZoneFactor", 0.5))
            if option(options, "endOffsets", False) and not special
            else 0.0
        )
        column_faces = [
            (
                np.array(e.position, dtype=float),
                float(e.bottom),
                float(e.top),
                types[e.type].profile,
                e.rotation if exact_angles else 90 * round(e.rotation / 90),
            )
            for e in building.elements
            if isinstance(e, ColumnElement) and hasattr(types.get(e.type), "profile")
        ]

        def joint_clear(at: np.ndarray, toward: np.ndarray, elevation: float) -> float:
            if not zone_factor:
                return 0.0
            direction = (float(toward[0] - at[0]), float(toward[1] - at[1]))
            reach = max(
                (
                    support_reach(profile, rotation, direction)
                    for position, bottom, top, profile, rotation in column_faces
                    if float(np.linalg.norm(position - at)) < 1.0
                    and bottom - 1.0 <= elevation <= top + 1.0
                ),
                default=0.0,
            )
            return sls.joint_clearance(reach, zone_factor)

        for element in building.elements:
            if isinstance(element, BeamElement):
                s0 = np.array(element.start, dtype=float)
                s1 = np.array(element.end, dtype=float)
                z = float(element.elevation)
                clear = (joint_clear(s0, s1, z), joint_clear(s1, s0, z))
                cuts.setdefault(element.id, []).extend(
                    sls.division_points((*s0, z), (*s1, z), beam_size, clear)
                )
    # Members whose steel type has a simple connection: their ends (mm), pinned below.
    simple_ends: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    def simple(type_id: str) -> bool:
        object_type = types.get(type_id)
        material = mats.get(object_type.material) if object_type else None
        return (
            getattr(object_type, "connection", None) is not None
            and material is not None
            and material.category.value == "steel"
        )

    for source, type_id, a, c in linear:
        axis = c - a
        sec = section(type_id, 0, abs(axis[2]) > abs(axis[0]), modifiers_of.get(source))
        if sec is None:
            b.notes.append(
                f"{source}: no elastic section (object type, material or E missing); left out"
            )
            continue
        if source in cuts:
            for k, (p, q) in enumerate(ml.split_line(a, c, cuts[source])):
                lines.append((f"{source}/p{k}", p, q))
                line_sources[f"{source}/p{k}"] = (source, sec)
        else:
            lines.append((source, tuple(a), tuple(c)))
            line_sources[source] = (source, sec)
        if simple(type_id):
            simple_ends[source] = (np.asarray(a, dtype=float), np.asarray(c, dtype=float))

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
        if simple(element.type):
            simple_ends[element.id] = (a.astype(float), c.astype(float))

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
        sec = plate(element.type, modifiers_of.get(element.id))
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
            sec = plate(element.type, modifiers_of.get(element.id))
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

    # Mesh size: the settings' size; with the span rule, shell slabs no coarser than their
    # shorter span / 8 (so the beams' gravity moments converge: the mesh check of Run All).
    # ``meshScale`` (not a setting: the mesh check, saengine.fem.mesh_check) scales both.
    scale = float(option(options, "meshScale", 1.0))
    mesh_size = float(options.meshSize) * scale
    if option(options, "meshBySpan", False):
        slab_ids = {e.id for e in building.elements if isinstance(e, SlabElement)}
        for surface in surfaces:
            if surface.key not in slab_ids:
                continue
            xs = [p[0] for p in surface.outline]
            ys = [p[1] for p in surface.outline]
            span = min(max(xs) - min(xs), max(ys) - min(ys))
            finer = max(MIN_SPAN_MESH, span / SPAN_DIVISIONS) * scale
            if finer < mesh_size:
                surface.size = finer
    meshed = mesh(lines, surfaces, mesh_size, volumes)
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
                b.members.append(
                    _Member(source, node_of[i], node_of[j], *sec, vecxz=member_vecxz.get(source))
                )
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

    # Live load arrangements (analysis.patternLive, saengine.fem.pattern_live): every live load
    # (case L) is logged with the point that places it in a bay (``live_at``: a shell's centre,
    # a slab panel's centroid; else the node or the member's middle) [mm], and copied into the
    # arrangement cases once all loads are in.
    live_log: list[tuple[str, int, np.ndarray, tuple[float, float, float]]] = []
    live_at: list[tuple[float, float, float] | None] = [None]

    def log_live(kind: str, target: int, vector: np.ndarray, at: np.ndarray) -> None:
        where = live_at[0] or (float(at[0]) / MM, float(at[1]) / MM, float(at[2]) / MM)
        live_log.append((kind, target, vector.copy(), where))

    def add_element_load(case: str, index: int, vector: np.ndarray) -> None:
        """A uniform load (global N/m) on member ``index``, applied in its local axes."""
        member = b.members[index]
        x, y, z = local_axes(b.coords[member.i], b.coords[member.j], member.vecxz)
        local = np.array([vector @ x, vector @ y, vector @ z])
        total = patterns[case]["element"].setdefault(index, np.zeros(3))
        total += local
        if case == "L":
            log_live("element", index, local, (b.coords[member.i] + b.coords[member.j]) / 2)
        if staged and case == "D":
            stage = stage_patterns.setdefault(
                top_stage((member.i, member.j)), {"nodal": {}, "element": {}}
            )
            stage["element"].setdefault(index, np.zeros(3))[:] += local

    def add_nodal(case: str, node_id: int, force: np.ndarray, stage: int | None = None) -> None:
        """A nodal force (global N); ``stage``: the construction stage of the element it comes
        from (by default the stage of the node's level)."""
        patterns[case]["nodal"].setdefault(node_id, np.zeros(6))[:3] += force
        if case == "L":
            log_live("nodal", node_id, np.asarray(force, dtype=float), b.coords[node_id])
        if staged and case == "D":
            k = stage if stage is not None else top_stage((node_id,))
            pattern = stage_patterns.setdefault(k, {"nodal": {}, "element": {}})
            pattern["nodal"].setdefault(node_id, np.zeros(6))[:3] += force

    # The mass source: the seismic weight W (BNBC 2020 Part 6 Sec 2.5.7.3, p. 628) is the dead
    # load (D: self-weight and partition walls; SD: finishes and partitions), a share of the
    # live load and the permanent equipment and retained liquid; the user's mass source may
    # factor each and add masses (``analysis.massSource``).
    mass_source = option(options, "massSource", None)
    part_factor = {
        "D": float(option(mass_source, "dead", 1.0)),
        "SD": float(option(mass_source, "superimposed", 1.0)),
        "L": 1.0,
        "other": 1.0,
    }
    #: Per node its weight [N] by part (D, SD, L, other): the formation of W in the summary.
    node_parts: dict[int, dict[str, float]] = {}

    def add_weight(node_id: int, weight: float, part: str = "D") -> None:
        weight *= part_factor.get(part, 1.0)
        node_weight[node_id] = node_weight.get(node_id, 0.0) + weight
        parts = node_parts.setdefault(node_id, {})
        parts[part] = parts.get(part, 0.0) + weight

    def share_weight(index: int, w: float, factor: float, part: str = "D") -> None:
        member = b.members[index]
        half = w * float(np.linalg.norm(b.coords[member.j] - b.coords[member.i])) / 2 * factor
        add_weight(member.i, half, part)
        add_weight(member.j, half, part)

    down = np.array([0.0, 0.0, -1.0])
    for index, member in enumerate(b.members):
        w = member.density * member.area * G
        if w:
            # The weight and mass modifiers of the member (saengine.library.modifiers).
            own = modifiers_of.get(member.source, {})
            add_element_load("D", index, down * w * own.get("weight", 1.0))
            share_weight(index, w, own.get("mass", 1.0))

    for solid in b.solids:
        corners = [b.coords[n] for n in solid.nodes]
        volume = abs(float(np.linalg.det(np.array([c - corners[0] for c in corners[1:]])))) / 6
        w = volume * solid.density * G / 4  # a linear tetrahedron: a quarter to each corner
        if w:
            for node_id in solid.nodes:
                add_nodal("D", node_id, down * w, top_stage(solid.nodes))
                add_weight(node_id, w)

    seismic_table = code_context.table("seismic")
    live_share = seismic_table.liveShare
    # The heavy-live rule (Sec 2.5.7.3 (b)) is new: it holds once the code pack carries its
    # numbers (heavyLiveLimit, heavyLiveShare), so a pack without them keeps the old W.
    heavy_limit_value = getattr(seismic_table, "heavyLiveLimit", None)
    heavy_limit = float(heavy_limit_value) if heavy_limit_value is not None else math.inf
    heavy_share = float(getattr(seismic_table, "heavyLiveShare", None) or HEAVY_LIVE_SHARE)
    user_live_share = option(mass_source, "liveShare", None)

    def seismic_share(case: str, pressure: float | None = None) -> float:
        """The share of a load of ``case`` in the seismic weight; ``pressure`` (N/m²): of a live
        load, its intensity (above 3 kN/m² at least 50 %, Sec 2.5.7.3 (b))."""
        if case in ("D", "SD"):
            return 1.0
        if case != "L":
            return 0.0
        if user_live_share is not None:
            return float(user_live_share)
        if pressure is not None and pressure > heavy_limit * 1e3 + 1e-9:
            return max(live_share, heavy_share)
        return live_share

    def part_of(case: str) -> str:
        return case if case in ("D", "SD", "L") else "other"

    def shell_pressure(shell: _Shell, case: str, pressure: float) -> None:
        """A uniform downward pressure (N/m²) on a shell, as its consistent nodal loads."""
        shares = shell_node_shares([b.coords[n] for n in shell.nodes])
        stage = top_stage(shell.nodes)
        share = seismic_share(case, pressure)
        middle = np.mean([b.coords[n] for n in shell.nodes], axis=0) / MM
        live_at[0] = (float(middle[0]), float(middle[1]), float(middle[2]))
        for node_id, area in zip(shell.nodes, shares, strict=True):
            add_nodal(case, node_id, down * pressure * area, stage)
            add_weight(node_id, pressure * area * share, part_of(case))
        live_at[0] = None

    by_pair = {frozenset((m.i, m.j)): index for index, m in enumerate(b.members)}

    def shells_of_source(source: str) -> list[_Shell]:
        return [shell for shell in b.shells if shell.source == source]

    node_table: list[Any] = []

    def nodes_on(p0: np.ndarray, p1: np.ndarray) -> list[int]:
        """The nodes on the segment ``p0``-``p1`` (:func:`_on_segment`, for all nodes at once:
        node by node, a 25-storey model's line loads made 58 million calls)."""
        if not node_table or node_table[0] != len(b.coords):
            ids = list(b.coords)
            node_table[:] = [len(b.coords), ids, np.array([b.coords[n] for n in ids], dtype=float)]
        _, ids, xyz = node_table
        return [ids[k] for k in np.flatnonzero(_on_segment_mask(xyz, p0, p1))]

    def line_load(
        source: str,
        case: str,
        p0: np.ndarray,
        p1: np.ndarray,
        load: float,
        share: float | None = None,
        part: str | None = None,
        profile: sls.EdgeProfile | None = None,
    ) -> bool:
        """A uniform line load (N/m, down) along ``p0``-``p1``: beams along it carry their part,
        the nodes on it the rest. False when part of it has no node to go to. ``share``: the part
        of it in the seismic weight (by default that of its case); ``part``: the part of W it
        counts in (by default that of its case); ``profile``: a varying load instead (a slab's
        triangle or trapezoid, stations in m from ``p0``; ``load`` is then not used): each member
        takes its mean over the member and a pair of nodal forces that make up its moment
        (:func:`saengine.fem.slab_load_shapes.segment_loads`), the end loads go to the end
        nodes."""
        w = seismic_share(case) if share is None else share
        part = part or part_of(case)
        axis = p1 - p0
        length = float(np.linalg.norm(axis))
        on_line = sorted(
            (float((b.coords[node_id] - p0) @ axis) / length**2, node_id)
            for node_id in nodes_on(p0, p1)
        )
        complete = bool(on_line) and on_line[0][0] < 1e-6 and on_line[-1][0] > 1 - 1e-6
        stage = stage_of(float(p0[2]))
        for (t0, n0), (t1, n1) in pairwise(on_line):
            span = (t1 - t0) * length
            index = by_pair.get(frozenset((n0, n1)))
            if profile is None:
                mean, ends = load, (0.0, 0.0)
                reactions = (load * span / 2, load * span / 2)
            else:
                mean, f0, f1 = sls.segment_loads(profile, t0 * length, t1 * length)
                ends = (f0, f1)
                reactions = profile.reactions(t0 * length, t1 * length)
            if index is not None:
                add_element_load(case, index, down * mean)
                share_weight(index, mean, w, part)
                for node_id, force in zip((n0, n1), ends, strict=True):
                    if force:
                        add_nodal(case, node_id, down * force, stage)
                        add_weight(node_id, force * w, part)
            else:
                for node_id, force in zip((n0, n1), reactions, strict=True):
                    add_nodal(case, node_id, down * force, stage)
                    add_weight(node_id, force * w, part)
        if profile is not None:
            for (t, node_id), force, at in zip(
                (on_line[0], on_line[-1]) if on_line else (), profile.end_loads, (0.0, 1.0)
            ):
                if force and abs(t - at) < 1e-6:
                    add_nodal(case, node_id, down * force, stage)
                    add_weight(node_id, force * w, part)
                elif force:
                    complete = False
        if not complete and case == "D":
            b.notes.append(
                f"{source}: part of its load has no beam, wall or column to go to; not applied"
            )
        return complete

    def shell_line_load(
        source: str,
        shells: list[_Shell],
        p0: tuple[float, ...],
        p1: tuple[float, ...],
        load: float,
        case: str = "SD",
    ) -> None:
        """A line load (N/m, down) along ``p0``-``p1`` (m) across ``shells``: sampled along
        its length, each sample's share given to the corners of the shell it falls in by its
        position in the shell's triangle (so the total and its centre are exact)."""
        a, c = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        length = float(np.linalg.norm(c - a))
        step = max(float(options.meshSize) * MM / 4, 0.05)
        count = max(1, math.ceil(length / step))
        stage = stage_of(float(a[2]))
        share = seismic_share(case)
        triangles = []
        for shell in shells:
            corners = list(shell.nodes)
            for k in range(1, len(corners) - 1):
                triangles.append((corners[0], corners[k], corners[k + 1]))
        lost = 0.0
        for i in range(count):
            point = a + (c - a) * (i + 0.5) / count
            force = load * length / count
            for nodes in triangles:
                weights = _barycentric(point, [b.coords[n] for n in nodes])
                if weights is None:
                    continue
                for node_id, weight in zip(nodes, weights, strict=True):
                    if weight:
                        add_nodal(case, node_id, down * force * weight, stage)
                        add_weight(node_id, force * weight * share, part_of(case))
                break
            else:
                lost += force
        if lost > 1.0:
            b.notes.append(
                f"{source}: {lost / 1e3:.1f} kN of its load is off the slab's shells; not applied"
            )

    walls = {e.id for e in building.elements if isinstance(e, WallElement | AreaElement)}
    for shell in b.shells:
        if shell.source in walls:
            _, density, thickness = surface_sources[shell.source][1]
            if density:
                factor = modifiers_of.get(shell.source, {}).get("weight", 1.0)
                shell_pressure(shell, "D", density * G * thickness * factor)

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
    story_of_level = {round(st.elevation): st.id for st in building.stories}
    walled = arch_set.walled if arch_set is not None and partition_mode != "allowance" else set()
    if arch_set is not None:
        b.notes += [f"Architecture: {note}" for note in arch_set.notes]
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
        load_id = element.areaLoad or (settings.roofLoad if roof else settings.floorLoad)
        area_load = area_loads.get(load_id)
        if element.areaLoad and area_load is None:
            b.notes.append(f"{element.id}: no area load '{load_id}' in the project settings")
        self_weight = (
            (material.mechanical.density or 0.0)
            * G
            * object_type.thickness
            * MM
            * modifiers_of.get(element.id, {}).get("weight", 1.0)
            if material
            else 0.0
        )
        # The partition allowance is dropped where the architecture's walls are applied (never
        # both); a room's floor finish replaces the flat finish over it and its occupancy the
        # live load (saengine.fem.architecture_loads).
        partitions = (
            0.0
            if area_load is None or story_of_level.get(round(element.elevation)) in walled
            else area_load.partitions
        )
        live_case = "Lr" if roof else "L"
        finish = area_load.finish if area_load else 0.0
        live = area_load.live if area_load else 0.0
        pressures = {
            "D": self_weight,
            "SD": (finish + partitions) * 1e3,
            live_case: live * 1e3,
        }

        def room_pressures(
            room: Any,
            finish: float = finish,
            live: float = live,
            partitions: float = partitions,
            live_case: str = live_case,
        ) -> dict[str, float]:
            """SD and live [N/m²] of a room (the floor's where it gives none)."""
            room_finish = finish if room is None or room.finish is None else room.finish
            room_live = live if room is None or room.live is None else room.live
            return {"SD": (room_finish + partitions) * 1e3, live_case: room_live * 1e3}

        rooms_here = al.room_shares(arch_set, element) if arch_set is not None else []
        if element.id in shells_of:
            for case, pressure in pressures.items():
                if case != "D" and rooms_here:
                    continue
                for shell in shells_of[element.id] if pressure else []:
                    shell_pressure(shell, case, pressure)
            if rooms_here:
                # Each shell element takes the area-weighted mean of the rooms over it.
                for shell in shells_of[element.id]:
                    outline = [tuple(b.coords[n][:2] / MM) for n in shell.nodes]
                    mix = al.room_mix(arch_set, outline, element.elevation)
                    rest = max(0.0, 1 - sum(share for _, share in mix))
                    for case, pressure in room_pressures(None).items():
                        total = pressure * rest + sum(
                            room_pressures(room)[case] * share for room, share in mix
                        )
                        if total:
                            shell_pressure(shell, case, total)
            for wall in arch_set.slabs if arch_set is not None else []:
                if wall.slab == element.id:
                    shell_line_load(
                        wall.source, shells_of[element.id], wall.start, wall.end, wall.load
                    )
            continue
        if rooms_here:
            # Slabs as loads to beams: the panel takes the area-weighted mean of its rooms' loads
            # and the floor's over the rest (its total exact).
            covered = min(1.0, sum(share for _, share in rooms_here))
            for case in ("SD", live_case):
                pressures[case] = pressures[case] * (1 - covered) + sum(
                    room_pressures(room)[case] * share for room, share in rooms_here
                )
        if arch_set is not None:
            extra, walls_on = al.panel_pressures(arch_set, element)
            if extra:
                pressures["SD"] += extra
                b.notes.append(
                    f"{element.id}: walls {', '.join(walls_on)} on the slab as a uniform "
                    f"{extra / 1e3:.2f} kN/m² over the panel (slabs as loads to beams; BNBC "
                    "2020 Part 6 Sec 2.3.6, p. 540)"
                )
        if shell_slabs:
            b.notes.append(
                f"{element.id}: no plate section (material or E missing); loads applied to its edges"
            )
        corners = [(x * MM, y * MM) for x, y in element.boundary]
        z = element.elevation * MM
        # A panel's live load is placed in its bay by the panel's centroid (its edges lie on
        # the grid lines).
        from saengine.fem.pattern_live import centroid

        panel = centroid(element.boundary)
        live_at[0] = (panel[0], panel[1], float(element.elevation))
        noted = False
        for case, pressure in pressures.items():
            if not pressure:
                continue
            shape = sls.slab_load_shapes(corners, pressure, object_type.system)
            if not noted:
                b.notes += [f"{element.id}: {note}" for note in shape.notes]
                noted = True
            for edge in shape.edges:
                if edge.total:
                    p0 = np.array([*corners[edge.index], z])
                    p1 = np.array([*corners[(edge.index + 1) % len(corners)], z])
                    line_load(
                        element.id,
                        case,
                        p0,
                        p1,
                        edge.load,
                        share=seismic_share(case, pressure),
                        profile=edge,
                    )
        live_at[0] = None

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
            add_weight(load.node, load.weight, "other")
        for line in eq.lines:
            line_load(
                line.source,
                line.case,
                np.array(line.start),
                np.array(line.end),
                line.load,
                share=line.weight_share,
                part="other",
            )
        b.notes += eq.notes

    # ── line and point loads on members (05 Floor Plan/loads.json) ──
    if member_set is not None:

        def point_load(case: str, node_id: int, force: float, z: float) -> None:
            add_nodal(case, node_id, down * force, stage_of(z))
            add_weight(node_id, force * seismic_share(case), part_of(case))

        b.notes += ml.apply(member_set, b.coords, line_load, point_load)

    # ── the architecture's walls on beams (saengine.fem.architecture_loads) ──
    if arch_set is not None:
        for line in arch_set.lines:
            line_load(line.source, line.case, np.array(line.start), np.array(line.end), line.load)
        for point in arch_set.points:
            shares, _ = ml.point_shares(point, b.coords)
            if not shares:
                b.notes.append(f"{point.source}: no node on {point.member} to take it; not applied")
            for node_id, part in shares:
                add_nodal(point.case, node_id, down * point.force * part, stage_of(point.at[2]))
                add_weight(node_id, point.force * part * seismic_share(point.case), "SD")

    # ── the arrangements of the live load (BNBC 2020 Part 6 Sec 6.1.12.2) ──
    live_cases = _live_arrangements(
        building,
        types,
        mats,
        settings,
        option(options, "patternLive", "off"),
        live_log,
        patterns,
        b,
    )
    summary_live = {
        "mode": option(options, "patternLive", "off"),
        "cases": [{"case": p.name, "label": p.label, "clause": p.clause} for p in live_cases],
    }

    # ── levels: the story elevations with nodes ──
    # Mass lumping (``analysis.massLumping``): "storyLevels" (as a commercial analysis program
    # lumps lateral mass at the stories) gives the weight of every node between levels to the
    # nearest level, at its diaphragm's node, and the weight of the nodes nearer the base than
    # the first level (the lower half of the first storey, the supports' own share included)
    # to the base, where it does not participate; a node exactly half way between two levels
    # gives half its weight to each, so W does not depend on whether the mesh has a node there.
    # "levelAbove" (before version 0.0.44) counts every node's weight for the nearest level
    # above the base (the whole first storey with the first level, the supports' share
    # included) and leaves its mass where it is. Either way W + the base's share is the whole
    # weight, whatever the mesh.
    lumping = option(options, "massLumping", "levelAbove")
    above = [round(lv * MM, 6) for lv in levels if lv > base]
    base_m = base * MM
    level_nodes: dict[float, list[int]] = {h: [] for h in above}
    for node_id, xyz in b.coords.items():
        if node_id in b.restraints or not above:
            continue
        nearest = min(above, key=lambda h: abs(h - xyz[2]))
        if abs(xyz[2] - nearest) < 1e-6:
            level_nodes[nearest].append(node_id)
    heights = [h for h in above if level_nodes[h]] if not special else []
    on_level = {n for h in heights for n in level_nodes[h]}
    #: Weights [N] that go to a level but not to a node of it: (plan position m or None for the
    #: level's centre of mass, weight, parts).
    lumped: dict[float, list[tuple[np.ndarray | None, float, dict[str, float]]]] = {
        h: [] for h in heights
    }
    to_base = 0.0
    base_parts: dict[str, float] = {}
    if lumping == "storyLevels" and heights:
        targets = [base_m, *heights]
        for node_id, w in list(node_weight.items()):
            if node_id in on_level or not w:
                continue
            z = float(b.coords[node_id][2])
            gap = min(abs(h - z) for h in targets)
            # Half way between two levels: half to each (TIE_M, round-off of the coordinates).
            nearest = [h for h in targets if abs(h - z) - gap < TIE_M]
            parts = node_parts.pop(node_id, {})
            node_weight[node_id] = 0.0
            share = 1.0 / len(nearest)
            for h in nearest:
                if h == base_m:
                    to_base += w * share
                    for k, v in parts.items():
                        base_parts[k] = base_parts.get(k, 0.0) + v * share
                else:
                    lumped[h].append(
                        (
                            b.coords[node_id][:2].copy(),
                            w * share,
                            {k: v * share for k, v in parts.items()},
                        )
                    )
    story_names = {round(s.elevation * MM, 6): s.name for s in building.stories}
    story_levels = {s.id: round(s.elevation * MM, 6) for s in building.stories}
    extra_total = 0.0
    for extra in option(mass_source, "extraMasses", None) or []:
        story = option(extra, "story", None)
        z = story_levels.get(story) if story is not None else None
        if z is None and option(extra, "z", None) is not None:
            z = float(option(extra, "z", 0.0)) * MM
        weight = float(option(extra, "weight", 0.0)) * 1e3  # kN -> N
        if z is None or not heights or not weight:
            b.notes.append(
                f"mass source: an extra mass of {weight / 1e3:g} kN has no story; left out"
            )
            continue
        h = min(heights, key=lambda level: abs(level - z))
        x, y = option(extra, "x", None), option(extra, "y", None)
        position = np.array([float(x), float(y)]) * MM if x is not None and y is not None else None
        lumped[h].append((position, weight, {"extra": weight}))
        extra_total += weight

    # ── rigid diaphragms: each floor tied to a node at its centre of mass ──
    constraints: list[dict[str, Any]] = []
    retained_of: dict[float, int] = {}
    rotary: dict[int, float] = {}  # node -> mass moment of inertia about Z [kg·m²]

    def take(node_id: int, w: float, parts: dict[str, float]) -> None:
        node_weight[node_id] = node_weight.get(node_id, 0.0) + w
        own = node_parts.setdefault(node_id, {})
        for k, v in parts.items():
            own[k] = own.get(k, 0.0) + v

    for h in heights:
        tied = level_nodes[h]
        rigid = options.diaphragm == "rigid" and len(tied) >= 2
        placed = [(p, w) for p, w, _ in lumped[h] if p is not None]
        total = sum(node_weight.get(n, 0.0) for n in tied) + sum(w for _, w in placed)
        if total:
            plan = (
                sum(b.coords[n][:2] * node_weight.get(n, 0.0) for n in tied)
                + sum((p * w for p, w in placed), np.zeros(2))
            ) / total
        else:
            plan = sum(b.coords[n][:2] for n in tied) / len(tied)
        if not rigid:
            # No diaphragm node: each lumped weight goes to the level's node nearest in plan.
            for p, w, parts in lumped[h]:
                at = plan if p is None else p
                target = min(tied, key=lambda n, at=at: float(np.sum((b.coords[n][:2] - at) ** 2)))
                take(target, w, parts)
            continue
        key = (round(plan[0] / MM), round(plan[1] / MM), round(h / MM))
        if key in b.nodes and b.nodes[key] in tied:
            retained = b.nodes[key]  # a node of the floor is at its centre
        else:
            retained = b.node(*key)
            b.restraints[retained] = list(_IN_PLAN)
        retained_of[h] = retained
        for p, w, parts in lumped[h]:
            take(retained, w, parts)
            if p is not None:
                r2 = float(np.sum((p - b.coords[retained][:2]) ** 2))
                rotary[retained] = rotary.get(retained, 0.0) + w / G * r2
        constraints.append(
            {
                "type": "RigidDiaphragm",
                "perp_dir": 3,
                "retained_node": retained,
                "constrained_nodes": sorted(n for n in tied if n != retained),
            }
        )

    # Each level's weight: its nodes' and the nodes between that count for it (with
    # "levelAbove" the nearest level above the base, the supports' share with the first level;
    # with "storyLevels" none are left).
    level_weight: dict[float, float] = dict.fromkeys(above, 0.0)
    level_parts: dict[float, dict[str, float]] = {h: {} for h in above}
    for node_id, xyz in b.coords.items():
        if not above:
            continue
        nearest = min(above, key=lambda h: abs(h - xyz[2]))
        level_weight[nearest] += node_weight.get(node_id, 0.0)
        for k, v in node_parts.get(node_id, {}).items():
            level_parts[nearest][k] = level_parts[nearest].get(k, 0.0) + v
    weights = [level_weight[h] for h in heights]
    # The nodes sharing a level's lateral forces: its own and its diaphragm's node when that
    # carries weight (lumped from between the levels).
    force_nodes: dict[float, list[int]] = {}
    for h in heights:
        nodes_here = list(level_nodes[h])
        master = retained_of.get(h)
        if master is not None and master not in nodes_here and node_weight.get(master, 0.0):
            nodes_here.append(master)
        force_nodes[h] = nodes_here

    def level_shares(h: float) -> dict[int, float]:
        nodes_here = force_nodes[h]
        total = sum(node_weight.get(n, 0.0) for n in nodes_here)
        return {
            n: node_weight.get(n, 0.0) / total if total else 1 / len(nodes_here) for n in nodes_here
        }

    # ── lateral loads: equivalent static story forces, shared among a level's nodes by weight ──
    values = derived(settings)
    hn = (heights[-1] - base_m) if heights else 0.0
    summary: dict[str, Any] = {"levels": len(heights), "weight_kN": sum(weights) / 1e3}
    if member_set is not None:
        summary["memberLoads"] = member_set.summary()
    if arch_set is not None:
        summary["architectureLoads"] = arch_set.summary(partition_mode)
    if summary_live["cases"]:
        summary["patternLive"] = summary_live
    eccentricity = float(getattr(seismic_table, "accidentalEccentricity", None) or 0.05)
    eccentric = bool(option(options, "accidentalEccentricity", False)) and bool(heights)
    period_method = option(options, "periodMethod", "approximate")

    def seismic_loads(
        periods: dict[str, float],
    ) -> tuple[dict[str, dict[int, np.ndarray]], dict[str, Any]]:
        """The nodal loads (6 components, N and N·m) of EX and EY (and with the accidental
        eccentricity EXP, EXN, EYP, EYN) for the periods of X and Y, and their summary."""
        out: dict[str, dict[int, np.ndarray]] = {}
        info: dict[str, Any] = {"levels": []}
        rel_levels = [(h - base_m, w) for h, w in zip(heights, weights, strict=True)]
        forces_of: dict[str, list[float]] = {}
        for axis, case in ((0, "EX"), (1, "EY")):
            period = periods[case[1]]
            sa = fl.design_acceleration(
                period,
                settings.site.siteClass,
                values["Z"],
                values["seismicImportance"],
                values["R"],
            )
            shear = sa * sum(weights)
            forces = fl.vertical_distribution(rel_levels, shear, period)
            forces_of[case] = forces
            info[case] = {"period_s": period, "Sa_g": sa, "base_shear_kN": shear / 1e3}
            nodal = out.setdefault(case, {})
            for level, h in enumerate(heights):
                for node_id, share in level_shares(h).items():
                    nodal.setdefault(node_id, np.zeros(6))[axis] += forces[level] * share
        if eccentric:
            for case, (source, sign) in ECCENTRIC_CASES.items():
                nodal = {n: v.copy() for n, v in out[source].items()}
                across = 1 if source == "EX" else 0
                for level, h in enumerate(heights):
                    here = [b.coords[n] for n in level_nodes[h]]
                    span = float(max(c[across] for c in here) - min(c[across] for c in here))
                    force = forces_of[source][level]
                    # Masses shifted by +e along Y turn the X forces by -F·e about Z; shifted by
                    # +e along X, the Y forces by +F·e (eq. 6.2.43).
                    moment = sign * eccentricity * span * force * (-1 if source == "EX" else 1)
                    for node_id, vector in _torsion_forces(
                        b.coords, level_shares(h), retained_of.get(h), moment
                    ).items():
                        nodal.setdefault(node_id, np.zeros(6))[:] += vector
                    info["levels"].append(
                        {
                            "case": case,
                            "z": round(h, 6),
                            "force_kN": force / 1e3,
                            "L_m": span,
                            "e_m": eccentricity * span,
                            "moment_kNm": moment / 1e3,
                        }
                    )
                out[case] = nodal
        return out, info

    # Earthquake and wind each need only their own site values (BNBC 2020 Part 6 Sec 2.5 the
    # zone coefficient Z, Sec 2.4 the basic wind speed V); a missing one is reported, and its
    # cases stay empty, never the other's.
    approximate = 0.0
    if heights and values["Z"]:
        approximate = fl.approximate_period(hn, settings.seismic.system)
        loads, info = seismic_loads({"X": approximate, "Y": approximate})
        for case, nodal in loads.items():
            target = patterns.setdefault(case, {"nodal": {}, "element": {}})["nodal"]
            for node_id, vector in nodal.items():
                target.setdefault(node_id, np.zeros(6))[:] += vector
        summary.update(
            {
                "period_s": approximate,
                "Cs": fl.normalized_spectrum(approximate, settings.site.siteClass),
                "Sa_g": info["EX"]["Sa_g"],
                "base_shear_kN": info["EX"]["base_shear_kN"],
                "periodMethod": "approximate",
                "seismic": {k: v for k, v in info.items() if k != "levels"},
            }
        )
        if eccentric:
            summary["accidentalTorsion"] = info["levels"]
    if heights and values["windSpeed"]:
        from saengine.fem.loads import wind_overrides

        with wind_overrides(settings.wind):
            wind_notes = _wind_loads(
                b,
                heights,
                base_m,
                level_nodes,
                retained_of,
                level_shares,
                patterns,
                summary,
                values["windSpeed"],
                settings.wind.exposure,
                values["windImportance"],
                # BNBC's exception is for buildings "designed with flexible diaphragms"; the
                # analysis option diaphragm = "flexible" only models the floors' in-plane stiffness
                # from their beams and shells (semi-rigid RC slabs), so it does not qualify.
                rigid=True,
                torsion=bool(option(options, "windTorsionCases", True)),
                story_names=story_names,
            )
        b.notes.extend(wind_notes)
    if special:
        b.notes.append(
            "special structure: no equivalent static wind or earthquake loads (they suit "
            "buildings with floors); gravity loads only for now"
        )
    elif not heights:
        b.notes.append("no lateral loads: the building has no levels above its base")
    else:
        missing = []
        if not values["Z"]:
            missing.append("Z")
            b.notes.append(
                "no earthquake loads: the site has no seismic zone coefficient Z (Project "
                "settings → Site: a location with a zone, or Z); EX and EY are empty, and every "
                "combination with them is formed without earthquake"
            )
        if not values["windSpeed"]:
            missing.append("windSpeed")
            b.notes.append(
                "no wind loads: the site has no basic wind speed V (Project settings → Site: a "
                "location with a speed, or V); WX and WY are empty, and every combination with "
                "them is formed without wind"
            )
        if missing:
            summary["lateralMissing"] = missing

    # ── the seismic weight W and how it was formed ──
    if heights:
        summary["seismicWeight"] = _seismic_weight_summary(
            lumping,
            heights,
            level_weight,
            level_parts,
            lumped,
            story_names,
            to_base,
            base_parts,
            extra_total,
            {
                "dead": part_factor["D"],
                "superimposed": part_factor["SD"],
                "liveShare": user_live_share if user_live_share is not None else live_share,
                "heavyLiveShare": heavy_share,
                "heavyLiveLimit_kPa": None if heavy_limit_value is None else heavy_limit,
            },
        )
        b.notes.append(summary["seismicWeight"]["note"])

    # ── simple connections: pinned member ends (after the loads and diaphragms) ──
    pins = _release_simple_ends(b, simple_ends)

    # ── end offsets: rigid end zones, forces at the support faces (saengine.fem.end_zones) ──
    faces = None
    if option(options, "endOffsets", False) and not special:
        faces = _rigid_end_zones(
            b,
            building,
            types,
            float(option(options, "rigidZoneFactor", 0.5)),
            set(simple_ends),
            [patterns, stage_patterns],
            exact_angles,
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
                "mass": [0.0] * 6
                if fixed
                else [mass, mass, 0.0, 0.0, 0.0, round(rotary.get(node_id, 0.0), 6)],
                "restraint": restraint,
            }
        )
    elements: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    def name(source: str) -> str:
        counts[source] = counts.get(source, 0) + 1
        return source if counts[source] == 1 else f"{source}#{counts[source]}"

    for member in b.members:
        frame: dict[str, Any] = {
            "id": len(elements) + 1,
            "name": name(member.source),
            "type": "ElasticBeamColumn",
            "nodes": [member.i, member.j],
            "section_id": member.section,
            "geom_transf": "Linear",
            "rho": 0.0,
            "consistent_mass": False,
        }
        if member.vecxz is not None:
            frame["vecxz"] = list(member.vecxz)
        if any(member.rigid):
            axis = b.coords[member.j] - b.coords[member.i]
            unit = axis / np.linalg.norm(axis)
            frame["joint_offsets"] = [
                *(round(float(v), 6) for v in unit * member.rigid[0]),
                *(round(float(v), 6) for v in -unit * member.rigid[1]),
            ]
        elements.append(frame)
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
    for source, node_id, twin, material_ids, dofs in pins:
        elements.append(
            {
                "id": len(elements) + 1,
                "name": name(f"{source}/pin"),
                "type": "ZeroLength",
                "nodes": [node_id, twin],
                "material_ids": material_ids,
                "dofs": dofs,
            }
        )
    # The fluid case F only when it has loads (it is last, so the other cases keep their ids).
    cases = [c for c in CASES if c != "F" or patterns[c]["nodal"] or patterns[c]["element"]]
    # The eccentric earthquake cases after them (only when asked for, so the others keep ids).
    cases += [c for c in ECCENTRIC_CASES if c in patterns]
    # The torsional wind cases (BNBC Figure 6.2.9) and the live load arrangements after them.
    cases += [c for c in fl.WIND_TORSION_CASES.values() if c in patterns]
    cases += [p.name for p in live_cases]
    extra_labels = {p.name: p.label for p in live_cases}
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
            "name": f"{case}: {extra_labels.get(case) or case_label(case)}",
            "type": "Static",
            "pattern_ids": [number],
            "n_steps": 1,
            "load_factor_increment": 1.0,
            "system": SOLVER,
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
            "name": f"D: {code_context.table('combinations').loadCases['D']}, construction sequence",
            "type": "Staged",
            "stages": stages,
            "system": SOLVER,
            "constraints": "Plain",
        }
        dead_preload = len(analyses) + 1
        analyses.append(
            {
                **dead,
                "id": dead_preload,
                "name": f"D0: {code_context.table('combinations').loadCases['D']}, applied at once",
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
                "n_modes": _mode_count(nodes, constraints, len(heights)),
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
                    "system": SOLVER,
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

        keys = {
            sid: key[:3] for key, sid in b.section_ids.items() if key[0] not in ("plate", "embed")
        }
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

        keys = {
            sid: key[:2] if key[0] in ("plate", "embed") else key[:3]
            for key, sid in b.section_ids.items()
        }
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

    # ── cracked stiffness and P-Delta (saengine.fem.second_order), after every case exists ──
    from saengine.fem import second_order

    concrete_sections = set()
    for key, section_id in b.section_ids.items():
        if not key or key[0] == "embed":
            continue
        object_type = types.get(key[1] if key[0] == "plate" else key[0])
        material = mats.get(getattr(object_type, "material", None)) if object_type else None
        if material is not None and material.category.value in ("concrete", "masonry"):
            concrete_sections.add(section_id)
    so = second_order.apply_second_order(
        project,
        second_order.options_from_settings(settings),
        concrete_sections=concrete_sections,
        modified=b.modified,
    )
    project = so.project
    b.notes.extend(so.notes)
    summary["secondOrder"] = so.summary

    # ── the period from the modal analysis (BNBC 2020 Part 6 Sec 2.5.7.2 (a), p. 627) ──
    if period_method == "analysis" and approximate:
        _analysis_period(
            project,
            summary,
            b.notes,
            approximate,
            seismic_table,
            seismic_loads,
            lambda t: fl.normalized_spectrum(t, settings.site.siteClass),
        )
    return Derivation(
        project=project,
        notes=b.notes,
        summary=summary,
        pushover=pushover,
        thermal=thermal_corrections,
        ssi=ssi_json,
        faces=faces if faces and faces["elements"] else None,
    )


def _analysis_period(
    project: dict[str, Any],
    summary: dict[str, Any],
    notes: list[str],
    approximate: float,
    seismic_table: Any,
    seismic_loads: Any,
    normalized: Any,
) -> None:
    """Replace the static earthquake loads of ``project`` (EX, EY and the eccentric cases) by
    those of the modal period in each direction, not below the approximate period Ta and
    capped at 1.4 times it
    (Sec 2.5.7.2 (a): a period from the structure's properties "shall not exceed the
    approximate fundamental period determined by Eq. 6.2.38 by more than 40 percent")."""
    import subprocess

    from saengine.fem.seismic_design import fundamental_periods

    try:
        modal = fundamental_periods(project)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        notes.append(
            f"period: the modal analysis failed ({error}); the approximate period "
            f"Ta = {approximate:.3f} s is used"
        )
        return
    factor = float(getattr(seismic_table, "periodUpperFactor", None) or PERIOD_UPPER_FACTOR)
    cap = factor * approximate
    # Not below Ta either: BNBC gives only the upper limit, but a period below Ta would take a
    # short building onto the rising branch of the spectrum (T < TB) and lower its base shear;
    # like a commercial analysis program (and ASCE 7 practice) the approximate period is the
    # lower bound.
    periods = {axis: min(max(modal[axis]["period"], approximate), cap) for axis in ("X", "Y")}
    loads, info = seismic_loads(periods)
    by_name = {p.get("name"): p for p in project.get("load_patterns", [])}
    for case, nodal in loads.items():
        pattern = by_name.get(case)
        if pattern is None:
            continue
        pattern["nodal_loads"] = [
            {"node_id": n, "forces": [round(float(f), 3) for f in v]}
            for n, v in sorted(nodal.items())
        ]
    # The top-level row stays that of EX, as with the approximate period (period_s keeps Ta,
    # the report's "approximate period"; Cs, Sa and V are those of the period used in X, so
    # V = Sa·W still holds); EY's are under "seismic".
    summary.update(
        {
            "periodMethod": "analysis",
            "periodCap_s": cap,
            "periodModal": modal,
            "periodUsed_s": periods["X"],
            "Cs": normalized(periods["X"]),
            "Sa_g": info["EX"]["Sa_g"],
            "base_shear_kN": info["EX"]["base_shear_kN"],
            "seismic": {k: v for k, v in info.items() if k != "levels"},
        }
    )
    if "accidentalTorsion" in summary:
        summary["accidentalTorsion"] = info["levels"]
    notes.append(
        "period from the modal analysis (BNBC 2020 Part 6 Sec 2.5.7.2 (a)): "
        + "; ".join(
            f"{axis}: T = {modal[axis]['period']:.3f} s (mode {modal[axis]['mode']})"
            + (f", capped at 1.4 Ta = {cap:.3f} s" if modal[axis]["period"] > cap else "")
            + (
                f", not below Ta = {approximate:.3f} s"
                if modal[axis]["period"] < approximate
                else ""
            )
            + f", V = {info['E' + axis]['base_shear_kN']:.1f} kN"
            for axis in ("X", "Y")
        )
    )


def _rigid_end_zones(
    b: _Builder,
    building: BuildingModel,
    types: dict[str, Any],
    factor: float,
    skip: set[str],
    pattern_groups: list[dict[str, dict[str, Any]]],
    exact_angles: bool = True,
) -> dict[str, Any]:
    """End offsets of the beams at the columns they frame into and of the columns at the
    floors on them (:mod:`saengine.fem.end_zones`): sets each end member's rigid zones
    (``factor`` × the offset), moves the uniform loads of ``pattern_groups`` (case -> {"nodal",
    "element"}) on the rigid zones to the joints, and returns the faces record
    (``08 FEM/faces.json``). ``skip``: members left without offsets (pinned steel ends)."""
    from saengine.fem.end_zones import (
        FACES_SCHEMA,
        RIGID_SHARE_LIMIT,
        profile_depth,
        support_reach,
    )

    columns = {
        # The angle the column is analysed at (rounded to quarter turns without exact angles).
        e.id: (types[e.type].profile, e.rotation if exact_angles else 90 * round(e.rotation / 90))
        for e in building.elements
        if isinstance(e, ColumnElement) and hasattr(types.get(e.type), "profile")
    }
    beams = {
        e.id: profile_depth(types[e.type].profile)
        for e in building.elements
        if isinstance(e, BeamElement) and hasattr(types.get(e.type), "profile")
    }
    slabs = {
        e.id: float(getattr(types.get(e.type), "thickness", 0.0) or 0.0)
        for e in building.elements
        if isinstance(e, SlabElement)
    }
    chains: dict[str, list[int]] = {}
    for index, member in enumerate(b.members):
        chains.setdefault(member.source, []).append(index)
    columns_at: dict[int, list[str]] = {}
    depth_at: dict[int, float] = {}  # node -> deepest beam framing in [mm]
    for index, member in enumerate(b.members):
        for n in (member.i, member.j):
            if member.source in columns:
                columns_at.setdefault(n, []).append(member.source)
            elif beams.get(member.source):
                depth_at[n] = max(depth_at.get(n, 0.0), float(beams[member.source] or 0.0))
    slab_at: dict[int, float] = {}
    for shell in b.shells:
        if shell.source in slabs:
            for n in shell.nodes:
                slab_at[n] = max(slab_at.get(n, 0.0), slabs[shell.source])

    def length(index: int) -> float:
        m = b.members[index]
        return float(np.linalg.norm(b.coords[m.j] - b.coords[m.i]))

    # (end member index, "i"|"j", offset m, the chain walked from the joint: [(index, reversed)])
    ends: list[tuple[int, str, float, list[tuple[int, bool]]]] = []
    for source, chain in chains.items():
        if source in skip:
            continue
        first, last = b.members[chain[0]], b.members[chain[-1]]
        if source in beams:
            run = b.coords[last.j] - b.coords[first.i]
            plan = (float(run[0]), float(run[1]))
            for end, node, direction, walk in (
                ("i", first.i, plan, [(k, False) for k in chain]),
                ("j", last.j, (-plan[0], -plan[1]), [(k, True) for k in reversed(chain)]),
            ):
                reach = max(
                    (
                        support_reach(columns[c][0], columns[c][1], direction)
                        for c in columns_at.get(node, [])
                    ),
                    default=0.0,
                )
                if reach > 0:
                    ends.append((walk[0][0], end, reach * MM, walk))
        elif source in columns:
            for position, index in enumerate(chain):
                top = b.members[index].j
                if b.coords[top][2] < b.coords[b.members[index].i][2]:
                    continue
                depth = depth_at.get(top) or slab_at.get(top, 0.0)
                if depth > 0:
                    walk = [(k, True) for k in reversed(chain[: position + 1])]
                    ends.append((index, "j", depth * MM, walk))

    faces: dict[str, dict[str, Any]] = {}
    capped: list[str] = []
    for index, end, offset, walk in ends:
        member = b.members[index]
        rigid = factor * offset
        limit = RIGID_SHARE_LIMIT * length(index)
        if rigid > limit:
            rigid = limit
            capped.append(member.source)
        zones = list(member.rigid)
        zones[0 if end == "i" else 1] = rigid
        member.rigid = (zones[0], zones[1])
        # Where the face is: walk the member from the joint.
        covered, at = 0.0, (index + 1, 0.0)
        for k, backwards in walk:
            span = length(k)
            if offset <= covered + span + 1e-9 or k == walk[-1][0]:
                into = min(offset - covered, span)
                at = (k + 1, span - into if backwards else into)
                break
            covered += span
        faces.setdefault(str(index + 1), {})[end] = {
            "offset": round(offset / MM, 1),
            "rigid": round(rigid / MM, 1),
            "at": [at[0], round(at[1], 6)],
        }

    # The uniform loads on the rigid zones go straight to the joints (the element carries its
    # load over its flexible length): force w·r and its moment about the joint.
    for group in pattern_groups:
        for pattern in group.values():
            for index, local in pattern["element"].items():
                member = b.members[index]
                ri, rj = member.rigid
                if not ri and not rj:
                    continue
                a, c = b.coords[member.i], b.coords[member.j]
                x, y, z = local_axes(a, c, member.vecxz)
                g = local[0] * x + local[1] * y + local[2] * z
                for node, r, sign in ((member.i, ri, 1.0), (member.j, rj, -1.0)):
                    if not r:
                        continue
                    force = g * r
                    moment = np.cross(sign * x * r / 2, force)
                    vector = pattern["nodal"].setdefault(node, np.zeros(6))
                    vector[:3] += force
                    vector[3:] += moment
    if faces:
        b.notes.append(
            f"end offsets: {len(ends)} member end(s) at column faces and beam soffits, rigid "
            f"zone factor {factor:g} (the design reads the forces at the faces)"
            + (
                f"; the rigid zone of {len(set(capped))} member(s) is limited to "
                f"{RIGID_SHARE_LIMIT:.0%} of a short element (e.g. {', '.join(sorted(set(capped))[:3])})"
                if capped
                else ""
            )
        )
    return {"schema": FACES_SCHEMA, "rigidZoneFactor": factor, "elements": faces}


def _mode_count(nodes: list[dict[str, Any]], constraints: list[dict[str, Any]], levels: int) -> int:
    """The modes of the modal case: 3 per level, at most 12, and not more than the DOF with
    mass (masses lumped at the story levels have few: 3 per diaphragm). All of those modes
    carry mass, so none is dropped: when ARPACK cannot find that many, OpenSees Studio solves
    dense or, in a large model, condenses the stiffness onto the DOF with mass (exact)."""
    wanted = min(12, 3 * levels)
    return max(1, min(wanted, _mass_dofs(nodes, constraints)))


def _mass_dofs(nodes: list[dict[str, Any]], constraints: list[dict[str, Any]]) -> int:
    """The number of independent degrees of freedom with mass (the rank of the mass matrix
    after the rigid diaphragms): each diaphragm with mass has 3 (X, Y, RZ), every other node
    one per DOF with mass. No more modes than this exist (the others have infinite
    frequency), which matters once the masses are lumped at the story levels."""
    tied: dict[int, int] = {}
    for k, c in enumerate(constraints):
        tied[c["retained_node"]] = k
        for n in c["constrained_nodes"]:
            tied[n] = k
    count, diaphragms = 0, set()
    for node in nodes:
        mass = node.get("mass") or [0.0] * 6
        if not any(mass):
            continue
        if node["id"] in tied:
            diaphragms.add(tied[node["id"]])
        else:
            count += sum(1 for m in mass if m)
    return count + 3 * len(diaphragms)


def _torsion_forces(
    coords: dict[int, np.ndarray], shares: dict[int, float], master: int | None, moment: float
) -> dict[int, np.ndarray]:
    """Nodal loads (6 components) of a torsional moment ``moment`` [N·m] about Z at a level:
    on its rigid diaphragm's node when it has one, else as forces ``α·s·(−dy, dx)`` on its nodes
    (``s`` their share of the storey force, ``d`` from the shares' centre, α = M / Σ s·r²): no
    net force, moment M."""
    if not moment:
        return {}
    if master is not None:
        return {master: np.array([0.0, 0.0, 0.0, 0.0, 0.0, moment])}
    total = sum(shares.values())
    if not total:
        return {}
    centre = sum(coords[n][:2] * s for n, s in shares.items()) / total
    polar = sum(s * float(np.sum((coords[n][:2] - centre) ** 2)) for n, s in shares.items())
    if polar <= 1e-12:
        return {next(iter(shares)): np.array([0.0, 0.0, 0.0, 0.0, 0.0, moment])}
    alpha = moment / polar
    out = {}
    for n, s in shares.items():
        dx, dy = coords[n][:2] - centre
        out[n] = np.array([-alpha * s * dy, alpha * s * dx, 0.0, 0.0, 0.0, 0.0])
    return out


def _wind_loads(
    b: _Builder,
    heights: list[float],
    base_m: float,
    level_nodes: dict[float, list[int]],
    retained_of: dict[float, int],
    level_shares: Any,
    patterns: dict[str, dict[str, Any]],
    summary: dict[str, Any],
    speed: float,
    exposure: str,
    importance: float,
    *,
    rigid: bool,
    torsion: bool,
    story_names: dict[float, str] | None = None,
) -> list[str]:
    """The equivalent static wind loads WX and WY (BNBC 2020 Part 6 Sec 2.4.11.2) and the
    torsional cases WTX and WTY (Sec 2.4.11.3 and Figure 6.2.9, pp. 559 and 574-575) into
    ``patterns``; returns the notes.

    Each storey's face is that of its own level's extent across the wind (a setback tower is
    narrower than its podium, :func:`saengine.fem.loads.wind_levels`). A level's force is shared
    among its nodes like the earthquake's (by weight), plus the couple that puts its resultant
    at the geometric centre of the face it takes, not at the centre of mass. WTX and WTY are the
    moments F·e alone, e = 0.15·B (B the face's width) counter-clockwise; the combinations take
    them with ± and the factors of Cases 2 and 4 (:func:`saengine.fem.loads.wind_design_variants`).
    """
    notes: list[str] = []
    rel = [h - base_m for h in heights]
    extents = []
    for h in heights:
        xy = np.array([b.coords[n][:2] for n in level_nodes[h]], dtype=float)
        extents.append((xy.min(axis=0), xy.max(axis=0)))
    cases = fl.wind_design_cases()
    exempt = cases is not None and fl.wind_torsion_exempt(len(heights), rel[-1], rigid, cases)
    with_torsion = cases is not None and torsion and not exempt
    if cases is None:
        notes.append(
            "wind: the code pack has no design wind load cases (BNBC 2020 Figure 6.2.9); only "
            "Case 1 (WX, WY), no torsional or simultaneous wind cases"
        )
    elif exempt:
        notes.append(
            "wind: Cases 1 and 3 of BNBC 2020 Figure 6.2.9 only (Sec 2.4.11.3, Exception: one "
            f"storey with h ≤ {cases.exemptHeight:g} m; the exception for flexible diaphragms "
            "does not apply to RC floors)"
        )
    elif not torsion:
        notes.append(
            "wind: the torsional cases of BNBC 2020 Figure 6.2.9 (Cases 2 and 4) are turned off "
            "(analysis option windTorsionCases), though Sec 2.4.11.3 requires them here"
        )
    rows: dict[str, list[dict[str, float]]] = {}
    totals: dict[str, float] = {}
    no_width: dict[str, list[str]] = {}
    for axis, case in ((0, "WX"), (1, "WY")):
        across = 1 - axis
        spans = [(float(lo[across]), float(hi[across])) for lo, hi in extents]
        depths = [float(hi[axis] - lo[axis]) for lo, hi in extents]
        # A level whose nodes have no extent across the wind (a planar frame, or nodes on one
        # line) has no face of its own: say so rather than report 0 kN as a result.
        flat = [
            _story_label(story_names or {}, h)
            for h, (low, high) in zip(heights, spans, strict=True)
            if high - low <= _WIND_MIN_WIDTH
        ]
        if flat:
            direction = "X" if axis == 0 else "Y"
            whole = len(flat) == len(heights)
            notes.append(
                f"wind in {direction}: "
                + (
                    f"no level has any width across the wind, so {case} is empty and every "
                    f"combination with {case} is formed without wind in {direction} (a planar "
                    "or one-line model; apply wind by hand as nodal loads)"
                    if whole
                    else f"level(s) {', '.join(flat)} have no width of their own across the "
                    "wind; their storeys' faces take no wind pressure"
                )
            )
            no_width[case] = flat
        levels = fl.wind_levels(rel, spans, depths, speed, exposure, importance)
        moments = (
            fl.wind_torsion_moments(levels, cases.eccentricity)
            if with_torsion and cases is not None
            else None
        )
        target = patterns.setdefault(case, {"nodal": {}, "element": {}})["nodal"]
        twist = (
            patterns.setdefault(fl.WIND_TORSION_CASES[case], {"nodal": {}, "element": {}})["nodal"]
            if moments is not None
            else None
        )
        rows[case] = []
        for i, (h, level) in enumerate(zip(heights, levels, strict=True)):
            shares = level_shares(h)
            total = sum(shares.values())
            centre = sum(b.coords[n][:2] * s for n, s in shares.items()) / total
            force = level.force * 1e3  # kN -> N
            for node_id, share in shares.items():
                target.setdefault(node_id, np.zeros(6))[axis] += force * share
            # The couple from the shares' centre to the face's: a force F along X at y = c
            # turns by -F·(c - y0) about Z; along Y at x = c by +F·(c - x0).
            offset = level.centre - float(centre[across])
            couple = force * offset * (-1 if axis == 0 else 1)
            master = retained_of.get(h)
            for node_id, vector in _torsion_forces(b.coords, shares, master, couple).items():
                target.setdefault(node_id, np.zeros(6))[:] += vector
            row = {
                "z": round(h, 6),
                "force_kN": level.force,
                "B_m": level.width,
                "centre_m": level.centre,
                "offset_m": offset,
            }
            if moments is not None and twist is not None:
                moment = moments[i] * 1e3  # kN·m -> N·m
                for node_id, vector in _torsion_forces(b.coords, shares, master, moment).items():
                    twist.setdefault(node_id, np.zeros(6))[:] += vector
                row["e_m"] = cases.eccentricity * level.torsion_arm if cases else 0.0
                row["torsion_kNm"] = moments[i]
            rows[case].append(row)
        totals[case] = sum(level.force for level in levels)
    summary["wind_X_kN"] = totals["WX"]
    summary["wind_Y_kN"] = totals["WY"]
    summary["wind"] = {
        "levels": rows,
        "torsionCases": [fl.WIND_TORSION_CASES[c] for c in ("WX", "WY")] if with_torsion else [],
        "designCases": None if cases is None else dict(vars(cases)),
        "exempt": exempt,
        "noWidth": no_width,
    }
    return notes


#: A level narrower than this across the wind [m] has no face of its own (a numerical zero).
_WIND_MIN_WIDTH = 1e-6


def _story_label(story_names: dict[float, str], h: float) -> str:
    """A level's name for a note: its storey name when it has one, else its z [m]."""
    return story_names.get(round(h, 6)) or f"z = {h:g} m"


def _seismic_weight_summary(
    lumping: str,
    heights: list[float],
    level_weight: dict[float, float],
    level_parts: dict[float, dict[str, float]],
    lumped: dict[float, list[tuple[Any, float, dict[str, float]]]],
    story_names: dict[float, str],
    to_base: float,
    base_parts: dict[str, float],
    extra: float,
    source: dict[str, Any],
) -> dict[str, Any]:
    """The seismic weight W per level and how it was formed (kN): ``{"method", "levels":
    [{"story", "z_m", "weight_kN", "parts_kN": {D, SD, L, other, extra}, "lumped_kN"}],
    "total_kN", "toBase_kN", "toBaseParts_kN", "extra_kN", "source", "note"}``."""
    rows = []
    for h in heights:
        parts = {k: round(v / 1e3, 3) for k, v in sorted(level_parts.get(h, {}).items())}
        rows.append(
            {
                "story": story_names.get(round(h, 6), ""),
                "z_m": round(h, 6),
                "weight_kN": round(level_weight[h] / 1e3, 3),
                "parts_kN": parts,
                "lumped_kN": round(sum(w for _, w, _ in lumped.get(h, [])) / 1e3, 3),
            }
        )
    total = sum(level_weight[h] for h in heights)
    live = source.get("liveShare")
    if lumping == "storyLevels":
        how = (
            "lumped at the story levels: each node's weight to the nearest level (its "
            f"diaphragm's node), {to_base / 1e3:.1f} kN of the lower half of the first storey to "
            "the base (not participating)"
        )
    else:
        how = (
            "each node's weight counted for the nearest level above the base (the lower half "
            "of the first storey with the first level), the masses left at the nodes"
        )
    note = (
        f"seismic weight W = {total / 1e3:.1f} kN (BNBC 2020 Part 6 Sec 2.5.7.3): dead load "
        f"x{source['dead']:g}, superimposed dead x{source['superimposed']:g}, live load x{live:g}"
        + (
            f" (x{source['heavyLiveShare']:g} above {source['heavyLiveLimit_kPa']:g} kN/m²), "
            if source.get("heavyLiveLimit_kPa") is not None
            else ", "
        )
        + "equipment and liquids in full"
        + (f", extra masses {extra / 1e3:.1f} kN" if extra else "")
        + f"; {how}"
    )
    return {
        "method": lumping,
        "levels": rows,
        "total_kN": round(total / 1e3, 3),
        "toBase_kN": round(to_base / 1e3, 3),
        "toBaseParts_kN": {k: round(v / 1e3, 3) for k, v in sorted(base_parts.items())},
        "extra_kN": round(extra / 1e3, 3),
        "source": source,
        "note": note,
    }


#: Stiffness of a pinned end's link in translation [N/m] and in torsion [N·m/rad]: a penalty
#: well above any member's (a 7 m steel brace's EA/L is about 1e8 N/m), so the link adds no
#: noticeable flexibility.
PIN_TRANSLATION = 1e13
PIN_TORSION = 1e12


def _release_simple_ends(
    b: _Builder, ends: dict[str, tuple[np.ndarray, np.ndarray]]
) -> list[tuple[str, int, int, list[int], list[int]]]:
    """Pin the ends of the members in ``ends`` (source -> its two end points, mm): the steel
    beams and braces whose type has a simple connection (fin plate, end plate, gusset), which
    transfers shear or axial force but no moment.

    Each pinned end connects to a twin node at the joint's place instead of the joint's node;
    a zero-length link (``ZeroLength``, named ``<member>/pin``) joins the two with stiff springs
    in translation only, so no moment passes. (A link element, not an equal-DOF tie: a tie on
    a floor node that a rigid diaphragm already constrains would be a chain of constraints,
    which the Transformation handler does not enforce.) A member pinned at both ends keeps its
    torsion at its first end (the spring about the global axis nearest its own), or it could
    spin about its axis. An end stays rigid at a support (its reaction stays at the support
    node) and where nothing else holds the joint's rotation (a free end).

    Returns the links: ``(source, joint node, twin node, material ids, dofs)``; their two
    elastic materials are added to the builder's materials."""
    if not ends:
        return []
    holds: dict[int, int] = {}
    for member in b.members:
        for n in (member.i, member.j):
            holds[n] = holds.get(n, 0) + 1
    for shell in b.shells:
        for n in shell.nodes:
            holds[n] = holds.get(n, 0) + 1
    candidates: list[tuple[int, int, int]] = []  # (member index, 0: i / 1: j, node)
    for index, member in enumerate(b.members):
        span = ends.get(member.source)
        if span is None:
            continue
        for end, n in ((0, member.i), (1, member.j)):
            at = b.coords[n] / MM
            if any(float(np.linalg.norm(at - p)) < 1.0 for p in span):
                candidates.append((index, end, n))
    for _, _, n in candidates:
        holds[n] -= 1
    twin_id = max(b.coords, default=0) + 1
    links: list[list[Any]] = []  # [source, node, twin, dofs]
    pinned: dict[str, list[tuple[int, int]]] = {}  # source -> [(member index, link)]
    kept: dict[str, list[str]] = {}
    for index, end, n in candidates:
        member = b.members[index]
        restraint = b.restraints.get(n) or [False] * 6
        if any(restraint[:3]):
            kept.setdefault("at a support", []).append(member.source)
            continue
        if holds.get(n, 0) <= 0 and not any(restraint[3:]):
            kept.setdefault("at a free end", []).append(member.source)
            continue
        twin = twin_id
        twin_id += 1
        b.coords[twin] = b.coords[n].copy()
        if end == 0:
            member.i = twin
        else:
            member.j = twin
        links.append([member.source, n, twin, [1, 2, 3]])
        pinned.setdefault(member.source, []).append((index, len(links) - 1))
    for items in pinned.values():
        if len(items) < 2:
            continue
        index, link = items[0]
        member = b.members[index]
        axis = np.abs(b.coords[member.j] - b.coords[member.i])
        links[link][3] = [1, 2, 3, 4 + int(np.argmax(axis))]
    for why, sources in kept.items():
        names = sorted(set(sources))
        b.notes.append(
            f"simple connections: {len(sources)} end(s) analysed rigid {why} "
            f"(e.g. {', '.join(names[:5])}); the design flags the moment there"
        )
    if not links:
        return []
    translation = len(b.materials) + 1
    b.materials.append(
        {
            "id": translation,
            "name": "pinned end, translation",
            "type": "Elastic",
            "E": PIN_TRANSLATION,
        }
    )
    torsion = len(b.materials) + 1
    b.materials.append(
        {"id": torsion, "name": "pinned end, torsion", "type": "Elastic", "E": PIN_TORSION}
    )
    b.notes.append(
        f"simple connections: {len(links)} member end(s) of {len(pinned)} steel member(s) "
        "pinned (no end moment), e.g. " + ", ".join(sorted(pinned)[:5])
    )
    return [
        (source, n, twin, [translation if d <= 3 else torsion for d in dofs], dofs)
        for source, n, twin, dofs in links
    ]


def pinned_twins(project: dict[str, Any]) -> dict[int, int]:
    """The twin nodes of pinned member ends (:func:`_release_simple_ends`) -> their joint's
    node, from the ``<member>/pin`` links of ``project``."""
    return {
        int(e["nodes"][1]): int(e["nodes"][0])
        for e in project.get("elements", [])
        if e.get("type") == "ZeroLength"
        and str(e.get("name") or "").split("#")[0].endswith("/pin")
        and len(e.get("nodes", [])) == 2
    }


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


def _barycentric(
    point: np.ndarray, triangle: list[np.ndarray]
) -> tuple[float, float, float] | None:
    """The barycentric weights of ``point`` in ``triangle`` in plan (their x and y), or None
    when it is outside."""
    (x1, y1), (x2, y2), (x3, y3) = (np.asarray(p, dtype=float)[:2] for p in triangle)
    det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(det) < 1e-12:
        return None
    x, y = float(point[0]), float(point[1])
    l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / det
    l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / det
    l3 = 1 - l1 - l2
    if min(l1, l2, l3) < -1e-9:
        return None
    return (max(l1, 0.0), max(l2, 0.0), max(l3, 0.0))


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


def _on_segment_mask(
    points: np.ndarray, a: np.ndarray, b: np.ndarray, tolerance: float = 1e-3
) -> np.ndarray:
    """:func:`_on_segment` of each row of ``points``."""
    axis = b - a
    length2 = float(axis @ axis)
    t = (points - a) @ axis / length2 if length2 else np.zeros(len(points))
    gap = np.linalg.norm(a + t[:, None] * axis - points, axis=1)
    return (t >= -1e-6) & (t <= 1 + 1e-6) & (gap <= tolerance)


def _live_arrangements(
    building: BuildingModel,
    types: dict[str, Any],
    mats: dict[str, Any],
    settings: ProjectSettings,
    mode: str,
    live_log: list[tuple[str, int, np.ndarray, tuple[float, float, float]]],
    patterns: dict[str, dict[str, Any]],
    b: _Builder,
) -> list[pattern_live.LivePattern]:
    """The live load arrangement cases (``analysis.patternLive``, BNBC 2020 Part 6 Sec
    6.1.12.2, :mod:`saengine.fem.pattern_live`) into ``patterns``: each live load logged
    (``live_log``: kind, member index or node, load vector, placing point [mm]) goes to the
    arrangements whose bays hold its point. Arrangements that load nothing are left out.
    Returns the arrangements kept (they carry no seismic weight and no construction stage)."""
    from saengine.fem import pattern_live

    if mode == "off" or not live_log:
        return []
    points = [tuple(e.position) for e in building.elements if isinstance(e, ColumnElement)]
    for e in building.elements:
        if isinstance(e, WallElement) and getattr(types.get(e.type), "structural", False):
            points += [tuple(e.start), tuple(e.end)]
    if not points:
        return []
    # Flat-slab floors whose live load is at most 3/4 of the dead load need no arrangement
    # (Sec 6.5.7.6.2); beams and one-way slabs always do (pattern_live.patterns_required).
    area_loads = {a.id: a for a in settings.areaLoads}
    needed, reasons = [], []
    for element in building.elements:
        if not isinstance(element, SlabElement):
            continue
        slab_type = types.get(element.type)
        load = area_loads.get(element.areaLoad or settings.floorLoad)
        if slab_type is None or load is None:
            continue
        material = mats.get(slab_type.material)
        density = (material.mechanical.density or 0.0) if material else 0.0
        dead = load.finish + load.partitions + density * G * slab_type.thickness * MM / 1e3
        ok, why = pattern_live.patterns_required(slab_type.system, dead, load.live)
        needed.append(ok)
        reasons.append(why)
    if needed and not any(needed):
        b.notes.append(f"live load arrangements: not needed ({reasons[0]})")
        return []
    grid = pattern_live.Grid.of(points, levels=[at[2] for *_, at in live_log])
    arrangements = pattern_live.live_patterns(
        grid,
        adjacent=mode in ("bnbc", "bnbcAlternateFloors"),
        adjacent_floors="alternate" if mode == "bnbcAlternateFloors" else "each",
    )
    kept = []
    for arrangement in arrangements:
        pattern: dict[str, Any] = {"nodal": {}, "element": {}}
        for kind, target, vector, (x, y, z) in live_log:
            if not arrangement.loads(grid, x, y, z):
                continue
            if kind == "nodal":
                pattern["nodal"].setdefault(target, np.zeros(6))[:3] += vector
            else:
                pattern["element"].setdefault(target, np.zeros(3))[:] += vector
        if pattern["nodal"] or pattern["element"]:
            patterns[arrangement.name] = pattern
            kept.append(arrangement)
    # Number the kept ones LP1, LP2 ... in order.
    renamed = []
    for k, arrangement in enumerate(kept, start=1):
        name = f"LP{k}"
        if name != arrangement.name:
            patterns[name] = patterns.pop(arrangement.name)
            arrangement = dataclasses.replace(arrangement, name=name)
        renamed.append(arrangement)
    if renamed:
        b.notes.append(
            f"live load arrangements: {len(renamed)} cases LP1-LP{len(renamed)} (BNBC 2020 Part "
            "6 Sec 6.1.12.2: adjacent and alternate bays of the column grid; the design "
            "envelopes them with the full live load L)"
        )
    return renamed

"""Export of a SAEngine building to an ETABS text model (``.e2k``, File → Import → ETABS .e2k).

The inverse of :mod:`saengine.importers.etabs`: the building model (``06 BIM``), its object
types and materials and the project settings become the ``$`` blocks of an e2k file, in kN and m
(or N and mm) and °C:

- stories from the BIM's stories, bottom one as the base (``ELEV``), the others by their heights;
  typical floors (``similarTo``) as ETABS's similar stories (``SIMILARTO``), the others masters;
- grid lines as one cartesian grid system;
- materials (concrete f'c, E, ν, α, unit weight; steel and rebar fy, fu) used by what is
  exported;
- frame sections, one per object type: concrete rectangles and circles (columns with their bars
  as a pattern, ``PATTERN "R-4-3"`` / ``"C-8"``, beams with their covers and bar areas); steel
  shapes by their library name (``SHAPE "W14X90" FILE "AISC16"``) where the profile is a shape
  of SAEngine's steel table or of FreeCAD's profile table that an ETABS library holds by that
  name (W, IPE, HE, UPN, ISMB/ISMC/..., UB/UC), else by their dimensions (``SHAPE "Steel I/Wide
  Flange" D B TF TW``, tubes, pipes, channels, angles, tees);
- slab and wall properties: slabs as membranes when the settings hand their loads to the beams
  (one-way load distribution for one-way slabs), thin shells when they are shells;
- points, lines and areas: columns split at every story they pass, beams, inclined members
  (braces, raking columns, sloped beams) and the members of special structures, structural
  walls story by story, slabs, slab openings (also 07 MEP's) and wall openings; a point off a
  story level is written below the story above it (``POINT "7" x y dz``);
- column rotations (``ANG``: the rotation, less 90° for I, T, L and channel columns, whose
  depth ETABS lays along local 2), simple steel connections as moment releases at both ends,
  SAEngine's cracked-section factors as property modifiers (columns 0.70, beams 0.35, slabs
  0.25 in bending, walls 0.70 or 0.35) when the settings crack the sections;
- restraints: SAEngine fixes the bases of the columns and walls at the lowest story, and the
  building-model supports are fixed or pinned; a rigid diaphragm ``D1`` on the slabs and on the
  points of every story above the base;
- load patterns D (self-weight), SD, L, Lr, WX, WY, EX, EY with their linear static cases and a
  modal case: the floor and roof area loads per slab (finish and partitions in SD, live in L, on
  the roof in Lr); non-structural walls as SD line loads on the beams under them; wind and
  earthquake as SAEngine's own story forces (derived as its analysis does, :mod:`saengine.fem.
  derive`) at each story's centre of mass, or the earthquake as an ETABS user coefficient
  (``lateral="coefficient"``: the BNBC base shear coefficient and the height exponent k);
- the mass source (elements, SD and the code's share of L, not lumped at the stories) and the
  load combinations of 02 Project Settings (D on both dead patterns).

The :class:`ExportReport` lists what could not be represented: stairs, footings, solid blocks,
07 MEP equipment loads, temperature, P-Delta, response spectrum, time-history and pushover
definitions, soil springs, and the cracked-for-lateral-only stiffness (ETABS's modifiers act in
every case). SAEngine's own wind and earthquake definitions (BNBC 2020) stay SAEngine's: ETABS
gets their story forces, not the code parameters.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from saengine.importers.common import ImportReport
from saengine.library.bim import (
    AreaElement,
    BeamElement,
    BlockElement,
    BuildingModel,
    ColumnElement,
    FootingElement,
    MemberElement,
    SlabElement,
    WallElement,
)
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import ProjectSettings

G = 9.80665  # m/s²

#: Points closer than this are the same, and a point within it of a story level is on it [mm].
TOLERANCE = 1.0

#: The version of the format written (the ETABS release whose exports it follows).
FORMAT_VERSION = "22.5.0"

_LENGTH = {"M": 1000.0, "MM": 1.0, "CM": 10.0}
_FORCE = {"KN": 1000.0, "N": 1.0}

Lateral = Literal["loads", "coefficient"]

#: SAEngine's cracked-section factors (BNBC 2020 Part 6 Sec 6.3.10.4.1, as
#: :mod:`saengine.fem.second_order` applies them).
_CRACKED = {"column": 0.70, "beam": 0.35, "slab": 0.25, "wall": 0.70, "wallCracked": 0.35}

#: Load patterns: name, ETABS type, self-weight multiplier.
_PATTERNS = (
    ("D", "Dead", 1),
    ("SD", "Super Dead", 0),
    ("L", "Live", 0),
    ("Lr", "Roof Live", 0),
    ("WX", "Wind", 0),
    ("WY", "Wind", 0),
    ("EX", "Seismic", 0),
    ("EY", "Seismic", 0),
)


# ─────────────────────────────────────────── report ───────────────────────────────────────────


class ExportReport(ImportReport):
    """What an export wrote, approximated and left out: ``imported`` counts what was written,
    ``carried`` / ``not_carried`` the loads written and left out [kN] per SAEngine case."""

    def __init__(self, file: str | None = None) -> None:
        super().__init__("ETABS", file)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "saengine.exportReport/1",
            "target": self.source,
            "exported": dict(self.imported),
            "approximated": self.approximated,
            "skipped": self.skipped,
            "warnings": list(self.warnings),
            "loads": {
                "exportedKN": {k: round(v, 3) for k, v in self.carried.items()},
                "notExportedKN": {k: round(v, 3) for k, v in self.not_carried.items()},
            },
        }


@dataclass
class E2kExport:
    """An e2k text and its report."""

    text: str
    report: ExportReport

    def write(self, path: str | Path) -> Path:
        """Writes the text to ``path`` (UTF-8, Windows line endings as ETABS writes them)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.text.replace("\n", "\r\n").encode("utf-8"))
        return target


@dataclass
class Equipment:
    """A piece of 07 MEP equipment as ETABS gets it: the plan points [mm] its loads are shared
    among on the floor of ``story``, and its loads [N] by load pattern."""

    id: str
    story: str
    points: list[tuple[float, float]]
    loads: dict[str, float]


def equipment_of(mep: Any, materials: MaterialLibrary) -> list[Equipment]:
    """The equipment of 07 MEP with its disciplines' (overhead tanks, HVAC plant, electrical
    equipment), loaded as the analysis loads it (:func:`saengine.mep.loads.equipment_parts`):
    empty weight and plinth SD, contents F (or as 07 MEP's contentsAs says), impact L. Point-
    supported items at their supports, the others at the quarter points of their footprint
    (equal shares there have the footprint's resultant)."""
    from saengine.mep.geometry import local_to_global
    from saengine.mep.loads import equipment_parts, with_services_equipment

    mep, _ = with_services_equipment(mep, materials)
    densities = {m.id: m.mechanical.density for m in materials.materials}
    cases = [p[0] for p in _PATTERNS] + ["F"]
    result = []
    for item in mep.equipment:
        local = (
            item.supports
            if item.loadAs == "points" and item.supports
            else [
                [sx * item.length / 4, sy * item.width / 4]
                for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
            ]
        )
        loads: dict[str, float] = defaultdict(float)
        for part in equipment_parts(item, mep.contentsAs, densities, cases):
            loads[part.case] += part.total
        points = local_to_global(item.x, item.y, item.rotation, local)
        result.append(Equipment(item.id, item.story, points, dict(loads)))
    return result


# ─────────────────────────────────────────── units ───────────────────────────────────────────


@dataclass(frozen=True)
class _Units:
    force: str = "KN"
    length: str = "M"

    @property
    def mm(self) -> float:
        return _LENGTH[self.length]

    @property
    def newton(self) -> float:
        return _FORCE[self.force]

    def len(self, mm: float) -> float:
        return mm / self.mm

    def stress(self, mpa: float) -> float:
        return mpa * self.mm**2 / self.newton

    def pressure(self, kpa: float) -> float:
        return self.stress(kpa / 1000)

    def line(self, n_per_m: float) -> float:
        return n_per_m / 1000 * self.mm / self.newton

    def to_force(self, newton: float) -> float:
        return newton / self.newton

    def area(self, mm2: float) -> float:
        return mm2 / self.mm**2

    def unit_weight(self, density: float) -> float:
        return density * G * 1e-9 * self.mm**3 / self.newton


def _n(value: float) -> str:
    """A number as ETABS writes them: up to 10 significant digits, no trailing zeros."""
    v = round(float(value), 9)
    if v == 0:
        return "0"
    return f"{v:.10g}"


def _q(text: str) -> str:
    return '"' + str(text).replace('"', "'") + '"'


# ─────────────────────────────────────── steel libraries ───────────────────────────────────────

#: Section names of ETABS's steel libraries (Property Libraries) by SAEngine's shape key
#: (:func:`saengine.importers.shapes.shape_key`): pattern -> (library, ETABS name).
_LIBRARIES: tuple[tuple[re.Pattern[str], str, Any], ...] = (
    (re.compile(r"^W\d+X\d+(?:\.\d+)?$"), "AISC16", lambda m: m.group(0)),
    (re.compile(r"^IPE\d+$"), "Euro", lambda m: m.group(0)),
    (re.compile(r"^HE([ABM])(\d+)$"), "Euro", lambda m: f"HE{m.group(2)}{m.group(1)}"),
    (re.compile(r"^UPN\d+$"), "Euro", lambda m: m.group(0)),
    (re.compile(r"^IS(?:MB|MC|LB|WB|JB|LC|JC)\d+$"), "Indian", lambda m: m.group(0)),
    (re.compile(r"^U[BC]\d+X\d+X\d+(?:\.\d+)?$"), "ArcelorMittal_British", lambda m: m.group(0)),
)


def _profile_dims(p: dict[str, Any]) -> tuple[str, tuple[float, ...]] | None:
    shape = p.get("shape")
    keys = {
        "I": ("overallDepth", "overallWidth", "webThickness", "flangeThickness"),
        "U": ("depth", "flangeWidth", "webThickness", "flangeThickness"),
        "T": ("depth", "flangeWidth", "webThickness", "flangeThickness"),
        "L": ("depth", "width", "thickness"),
        "rectangleHollow": ("yDim", "xDim", "wallThickness"),
        "circleHollow": ("radius", "wallThickness"),
    }.get(shape or "")
    if keys is None or any(k not in p for k in keys):
        return None
    return str(shape), tuple(round(float(p[k]), 2) for k in keys)


_FREECAD_INDEX: dict[tuple[str, tuple[float, ...]], str] | None = None


def designation(profile: dict[str, Any]) -> str | None:
    """The name of the table shape a steel profile is (SAEngine's steel table, then FreeCAD's
    profile table; dimensions to 0.01 mm, root radii ignored), or None."""
    global _FREECAD_INDEX
    from saengine.library import steel_sections

    dims = _profile_dims(profile)
    if dims is None:
        return None
    found = steel_sections.match(profile, tol=0.01)
    if found is not None and _profile_dims(steel_sections.profile_of(found)) == dims:
        return found.name
    if _FREECAD_INDEX is None:
        from saengine.importers.shapes import freecad_table

        table = freecad_table()
        _FREECAD_INDEX = {}
        for _, name, p in table.shapes.values() if table else ():
            key = _profile_dims(p)
            if key is not None:
                _FREECAD_INDEX.setdefault(key, name)
    return _FREECAD_INDEX.get(dims)


def library_shape(name: str) -> tuple[str, str] | None:
    """(ETABS library, ETABS name) of a table shape's name, when an ETABS library holds it."""
    from saengine.importers.shapes import shape_key

    key = shape_key(name)
    for pattern, library, etabs_name in _LIBRARIES:
        m = pattern.match(key)
        if m:
            return library, etabs_name(m)
    return None


# ─────────────────────────────────────────── writer ───────────────────────────────────────────


def write_e2k(
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary,
    settings: ProjectSettings,
    *,
    name: str | None = None,
    units: tuple[str, str] = ("KN", "M"),
    lateral: Lateral = "loads",
    derivation: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    live_share: float = 0.25,
    library_shapes: bool = True,
    grids: list[tuple[str, str, float]] | None = None,
    equipment: list[Equipment] | None = None,
    file: str | None = None,
    member_loads: Any = None,
) -> E2kExport:
    """The e2k text of a building (see the module notes).

    ``derivation`` is SAEngine's analysis model of the building (the ``08 FEM`` project JSON,
    :func:`saengine.fem.derive.derive_fem`): its wind and earthquake story forces are written as
    point loads; ``summary`` its summary (period and base shear coefficient, for
    ``lateral="coefficient"``). Without them the lateral patterns have no loads (reported).
    ``live_share`` is the code's share of the live load in the seismic weight; ``grids`` the
    grid lines (axis "X" or "Y", label, position [mm]), from the floor plan; ``equipment`` the
    loads of 07 MEP's equipment (:func:`equipment_of`); ``member_loads`` the line and point
    loads on members (``05 Floor Plan/loads.json``, :class:`saengine.library.line_loads.
    MemberLoads`), written as frame loads on the beams (point loads at joints on the points).
    """
    force, length = (u.upper() for u in units)
    if force not in _FORCE or length not in _LENGTH:
        raise ValueError(f"units {units}: use KN or N, and M, CM or MM")
    report = ExportReport(file)
    writer = _Writer(
        building,
        objects,
        materials,
        settings,
        _Units(force, length),
        report,
        lateral=lateral,
        derivation=derivation,
        summary=summary or {},
        live_share=live_share,
        library_shapes=library_shapes,
    )
    writer.grids = [
        f'  GRID "G1"  LABEL {_q(label)}  DIR {_q(axis)}  COORD {_n(writer.u.len(position))} '
        'VISIBLE "Yes"  BUBBLELOC "End"  '
        for axis, label, position in grids or []
    ]
    report.count("gridLines", len(writer.grids))
    writer.equipment = equipment or []
    writer.member_loads = member_loads
    text = writer.run(name or settings.project.name)
    return E2kExport(text, report)


class _Writer:
    def __init__(
        self,
        building: BuildingModel,
        objects: ObjectLibrary,
        materials: MaterialLibrary,
        settings: ProjectSettings,
        units: _Units,
        report: ExportReport,
        *,
        lateral: Lateral,
        derivation: dict[str, Any] | None,
        summary: dict[str, Any],
        live_share: float,
        library_shapes: bool,
    ) -> None:
        self.b, self.settings, self.u, self.report = building, settings, units, report
        self.types = {o.id: o for o in objects.objects}
        self.mats = {m.id: m for m in materials.materials}
        self.lateral = lateral
        self.derivation = derivation
        self.summary = summary
        self.live_share = live_share
        self.library_shapes = library_shapes
        self.analysis = settings.analysis
        self.cracked = self.analysis.stiffness == "aci"
        self.rigid = self.analysis.diaphragm == "rigid"
        self.membrane = self.analysis.slabs == "loadsToBeams"
        # stories bottom up: (name, elevation [mm], name of the story it is similar to)
        self.levels: list[tuple[str, float, str | None]] = []
        self.points: dict[tuple[float, float, float], str] = {}
        self.point_xy: dict[str, tuple[float, float, float]] = {}
        self.labels: set[str] = set()
        self.equipment: list[Equipment] = []
        self.member_loads: Any = None
        self.patterns = list(_PATTERNS)
        self.used_materials: set[str] = set()
        self.frame_sections: dict[str, list[str]] = {}  # type id -> lines
        self.concrete_sections: list[str] = []
        self.shell_props: dict[str, str] = {}  # type id -> line
        self.extra_rotation: dict[str, float] = {}
        self.lines: list[str] = []
        self.areas: list[str] = []
        self.point_assigns: dict[tuple[str, str], dict[str, str]] = {}
        self.line_assigns: list[str] = []
        self.area_assigns: list[str] = []
        self.point_loads: list[str] = []
        self.line_loads: list[str] = []
        self.area_loads: list[str] = []
        self.beams: list[tuple[str, str, tuple[float, float], tuple[float, float], float]] = []
        self.walls: dict[str, list[tuple[str, int, float, float]]] = {}
        self.grids: list[str] = []
        #: (point, story index) of the points the lines and areas use.
        self.used: set[tuple[str, int]] = set()
        #: The ends of the lines written: member name by (end i, end j).
        self.places: dict[tuple[tuple[str, int], tuple[str, int]], str] = {}

    # ── stories and points ──

    def _stories(self) -> None:
        stories = sorted(self.b.stories, key=lambda s: s.elevation)
        names = [s.name.strip() for s in stories]
        unique = len({n.upper() for n in names}) == len(names) and all(names)
        by_id = {s.id: (n if unique else s.id) for s, n in zip(stories, names, strict=True)}
        if not unique and stories:
            self.report.approximate("stories named by their ids (their names are not unique)")
        for s in stories:
            similar = by_id.get(s.similarTo) if s.similarTo else None
            self.levels.append((by_id[s.id], float(s.elevation), similar))
        if len(self.levels) >= 2:
            return
        # A special structure (or a building without stories): a base and a top level.
        zs = [z for e in self.b.elements for z in _element_levels(e)]
        zs += [z for m in self.b.additions.members for z in (m.z1, m.z2)]
        zs += [s.at[2] for s in self.b.supports]
        low, high = (min(zs), max(zs)) if zs else (0.0, 3000.0)
        if high - low <= TOLERANCE:
            high = low + 3000.0
        self.levels = [("Base", low, None), ("Top", high, None)]
        self.report.approximate(
            "a structure without stories exported on a base and a top story (points between "
            "are written below the top)"
        )

    def _story_of(self, z: float) -> tuple[int, float] | None:
        """(story index, depth below it [mm]) of a level ``z``; None above the top story."""
        for index, (_, elevation, _) in enumerate(self.levels):
            if abs(elevation - z) <= TOLERANCE:
                return index, 0.0
            if elevation > z:
                return index, elevation - z
        return None

    def _point(self, x: float, y: float, z: float) -> tuple[str, int] | None:
        at = self._story_of(z)
        if at is None:
            return None
        index, dz = at
        key = (round(x, 2), round(y, 2), round(dz, 2))
        label = self.points.get(key)
        if label is None:
            label = str(len(self.points) + 1)
            self.points[key] = label
            self.point_xy[label] = key
        return label, index

    def _label(self, name: str) -> str:
        base = re.sub(r'["\s]+', "_", name) or "X"
        label, k = base, 2
        while label.upper() in self.labels:
            label, k = f"{base}-{k}", k + 1
        self.labels.add(label.upper())
        return label

    def _story(self, index: int) -> str:
        return self.levels[index][0]

    # ── materials and sections ──

    def _material(self, material_id: str) -> bool:
        material = self.mats.get(material_id)
        if material is None:
            return False
        self.used_materials.add(material_id)
        return True

    def _material_lines(self) -> list[str]:
        u = self.u
        out = []
        for mid in sorted(self.used_materials):
            m = self.mats[mid]
            category = m.category.value
            mech = m.mechanical
            kind = {"concrete": "Concrete", "steel": "Steel", "rebar": "Rebar"}.get(category)
            if kind is None:
                kind = "NoDesign"
                self.report.approximate("materials other than concrete and steel as NoDesign", mid)
            E = mech.E
            if not E:
                fc = m.concrete.fc if m.concrete else 25.0
                E = 4700 * math.sqrt(fc) if category == "concrete" else 200_000.0
                self.report.approximate("materials without E: the code value", mid)
            nu = mech.nu if mech.nu is not None else (0.2 if category == "concrete" else 0.3)
            weight = u.unit_weight(mech.density) if mech.density else 0.0
            if not mech.density:
                self.report.approximate("materials without a density: no self-weight", mid)
            grade = m.steel.grade if m.steel and m.steel.grade else m.name
            out.append(
                f"  MATERIAL  {_q(mid)}    TYPE {_q(kind)}    GRADE {_q(grade)}    "
                f"WEIGHTPERVOLUME {_n(weight)}"
            )
            symmetry = "Uniaxial" if category == "rebar" else "Isotropic"
            text = f"  MATERIAL  {_q(mid)}    SYMTYPE {_q(symmetry)}  E {_n(u.stress(E))}"
            if symmetry == "Isotropic":
                text += f"  U {_n(nu)}"
            alpha = mech.alpha if mech.alpha is not None else (1e-5 if kind != "Steel" else 1.17e-5)
            out.append(f"{text}  A {_n(alpha)}")
            if m.concrete is not None:
                out.append(f"  MATERIAL  {_q(mid)}    FC {_n(u.stress(m.concrete.fc))}")
            elif m.steel is not None:
                fy = m.steel.fy
                fu = m.steel.fu
                if not fu:
                    fu = 1.25 * fy
                    self.report.approximate("steel without fu: 1.25 fy", mid)
                out.append(
                    f"  MATERIAL  {_q(mid)}  FY {_n(u.stress(fy))}  FU {_n(u.stress(fu))} "
                    f"FYE {_n(u.stress(m.steel.fyActual or 1.1 * fy))}  "
                    f"FUE {_n(u.stress(m.steel.fuActual or 1.1 * fu))}"
                )
        self.report.count("materials", len(self.used_materials))
        return out

    def _frame_section(self, type_id: str) -> str | None:
        """The frame section of an object type (made once), or None when it cannot be written."""
        if type_id in self.frame_sections:
            return type_id if self.frame_sections[type_id] else None
        self.frame_sections[type_id] = []
        t = self.types.get(type_id)
        profile = getattr(t, "profile", None)
        if t is None or profile is None:
            self.report.skip("members of unknown or profile-less object types", type_id)
            return None
        material = self.mats.get(t.material)
        if material is None:
            self.report.skip("sections with an unknown material", f"{type_id} ({t.material})")
            return None
        p = profile.model_dump(mode="json")
        column = t.kind == "column"
        concrete = material.category.value == "concrete"
        steel = material.category.value == "steel"
        u = self.u
        shape = p["shape"]
        pairs = ""
        # Solid rectangles and circles are ETABS's "concrete" shapes whatever their material
        # (ETABS writes a steel flat bar or rod so too).
        if shape == "rectangle":
            # Columns: ETABS's depth (local 2) along global X at an angle of 0, as the
            # profile's x at a rotation of 0; beams: depth is the profile's y.
            d, b = (p["xDim"], p["yDim"]) if column else (p["yDim"], p["xDim"])
            pairs = f'SHAPE "Concrete Rectangular"  D {_n(u.len(d))} B {_n(u.len(b))}'
        elif shape == "circle":
            pairs = f'SHAPE "Concrete Circle"  D {_n(u.len(2 * p["radius"]))}'
        else:
            if not steel:
                self.report.approximate("steel shapes of a non-steel material", type_id)
            named = designation(p) if self.library_shapes and steel else None
            library = library_shape(named) if named else None
            if library is not None:
                pairs = f"SHAPE {_q(library[1])}  FILE {_q(library[0])}"
                self.report.approximate(
                    "steel shapes by their ETABS library name (ETABS takes the library's "
                    "dimensions)",
                    f"{type_id}: {library[1]} ({library[0]})",
                )
            else:
                pairs = self._steel_dims(p, column)
            if column and shape in ("I", "T", "L", "U"):
                self.extra_rotation[type_id] = -90.0
        if not pairs:
            self.report.skip("sections of shapes that cannot be written", f"{type_id} ({shape})")
            return None
        self._material(t.material)
        self.frame_sections[type_id] = [
            f"  FRAMESECTION  {_q(type_id)}  MATERIAL {_q(t.material)}  {pairs} "
        ]
        reinforcement = getattr(t, "reinforcement", None)
        if concrete and reinforcement is not None and t.kind in ("column", "beam"):
            self._concrete_section(type_id, t.kind, p, reinforcement)
        self.report.count("frameSections")
        return type_id

    def _steel_dims(self, p: dict[str, Any], column: bool) -> str:
        u = self.u
        shape = p["shape"]
        if shape == "I":
            return (
                f'SHAPE "Steel I/Wide Flange"  D {_n(u.len(p["overallDepth"]))} '
                f"B {_n(u.len(p['overallWidth']))} TF {_n(u.len(p['flangeThickness']))} "
                f"TW {_n(u.len(p['webThickness']))}"
            )
        if shape == "rectangleHollow":
            d, b = (p["xDim"], p["yDim"]) if column else (p["yDim"], p["xDim"])
            t = _n(u.len(p["wallThickness"]))
            return f'SHAPE "Steel Tube"  D {_n(u.len(d))} B {_n(u.len(b))} TF {t} TW {t}'
        if shape == "circleHollow":
            return (
                f'SHAPE "Steel Pipe"  D {_n(u.len(2 * p["radius"]))} '
                f"T {_n(u.len(p['wallThickness']))}"
            )
        if shape in ("U", "T"):
            name = "Steel Channel" if shape == "U" else "Steel Tee"
            return (
                f"SHAPE {_q(name)}  D {_n(u.len(p['depth']))} B {_n(u.len(p['flangeWidth']))} "
                f"TF {_n(u.len(p['flangeThickness']))} TW {_n(u.len(p['webThickness']))}"
            )
        if shape == "L":
            t = _n(u.len(p["thickness"]))
            return (
                f'SHAPE "Steel Angle"  D {_n(u.len(p["depth"]))} B {_n(u.len(p["width"]))} '
                f"TF {t} TW {t}"
            )
        return ""

    def _concrete_section(self, type_id: str, kind: str, p: dict[str, Any], bars: Any) -> None:
        """The bars of a concrete column or beam section (``$ CONCRETE SECTIONS``)."""
        u = self.u
        rebar = self.mats.get(bars.material)
        if rebar is None or rebar.category.value != "rebar":
            self.report.approximate("bars without a rebar material left out", type_id)
            return
        self._material(bars.material)
        head = (
            f"  CONCRETESECTION  {_q(type_id)}  LONGBARMATERIAL {_q(bars.material)}  "
            f"CONFINEBARMATERIAL {_q(bars.material)}  TYPE {_q(kind.title())}  "
        )
        tie = bars.transverse
        tie_dia = tie.dia if tie else 10.0
        if kind == "beam":
            top = sum(
                g.count * math.pi * g.dia**2 / 4 for g in bars.longitudinal if g.position == "top"
            )
            bottom = sum(
                g.count * math.pi * g.dia**2 / 4
                for g in bars.longitudinal
                if g.position == "bottom"
            )
            dias = {
                pos: max((g.dia for g in bars.longitudinal if g.position == pos), default=20.0)
                for pos in ("top", "bottom")
            }
            # ETABS's beam covers are to the bars' centres.
            cover_top = bars.cover + tie_dia + dias["top"] / 2
            cover_bottom = bars.cover + tie_dia + dias["bottom"] / 2
            self.concrete_sections.append(
                head + f"COVERTOP {_n(u.len(cover_top))} COVERBOTTOM {_n(u.len(cover_bottom))} "
                f"ATI {_n(u.area(top))} ABI {_n(u.area(bottom))} ATJ {_n(u.area(top))} "
                f"ABJ {_n(u.area(bottom))} "
            )
            return
        groups = bars.longitudinal
        if not groups:
            return
        count = sum(g.count for g in groups)
        dia = max(g.dia for g in groups)
        if len({g.dia for g in groups}) > 1 or any(g.position != "perimeter" for g in groups):
            self.report.approximate(
                "column bars of several sizes or faces as one perimeter layout of the largest bar",
                type_id,
            )
        if p["shape"] == "circle":
            pattern = f"C-{count}"
        else:
            if count % 2:
                count += 1
                self.report.approximate("an odd number of column bars rounded up to even", type_id)
            count = max(count, 4)
            # "R-a-b": a bars (corners included) on each face along the depth D (local 2), b on
            # each face along the width B (local 3), shared in proportion to the faces.
            half = count // 2 + 2
            d, b = p["xDim"], p["yDim"]  # local 2 (depth) and local 3 (width)
            along_b = min(max(round(half * b / (b + d)), 2), half - 2)
            pattern = f"R-{half - along_b}-{along_b}"
        transverse = "SPIRAL" if tie and tie.type == "spiral" else "TIES"
        if tie is None:
            self.report.approximate("columns without ties written with 10 mm ties at 150", type_id)
        spacing = tie.spacing if tie else 150.0
        text = (
            head + f'PATTERN {_q(pattern)}  TRANSREINF {_q(transverse)}  DESIGNCHECK "CHECK"  '
            f"COVER {_n(u.len(bars.cover))} LONGBARAREA {_n(u.area(math.pi * dia**2 / 4))} "
            f"CONFINEBARAREA {_n(u.area(math.pi * tie_dia**2 / 4))} "
            f"CONFINEBARSPACING {_n(u.len(spacing))} "
        )
        if p["shape"] != "circle":
            legs = tie.legs if tie else 2
            legs_x = (tie.legsX or legs) if tie else 2
            text += f"NUMCONFINEBARS3 {legs} NUMCONFINEBARS2 {legs_x} "
        self.concrete_sections.append(text)

    def _shell_prop(self, type_id: str, kind: Literal["slab", "wall"]) -> str | None:
        if type_id in self.shell_props:
            return type_id if self.shell_props[type_id] else None
        self.shell_props[type_id] = ""
        t = self.types.get(type_id)
        thickness = getattr(t, "thickness", None)
        if t is None or not thickness or t.material not in self.mats:
            self.report.skip("areas of unknown object types or materials", type_id)
            return None
        self._material(t.material)
        u = self.u
        if kind == "slab":
            modelling = "Membrane" if self.membrane else "ShellThin"
            one_way = ' ONEWAYLOADDIST "Yes" ' if self.membrane and t.system == "oneWay" else " "
            line = (
                f'  SHELLPROP  {_q(type_id)}  PROPTYPE  "Slab"  MATERIAL {_q(t.material)}  '
                f'MODELINGTYPE {_q(modelling)}{one_way} SLABTYPE "Slab"  '
                f"SLABTHICKNESS {_n(u.len(thickness))} "
            )
        else:
            line = (
                f'  SHELLPROP  {_q(type_id)}  PROPTYPE  "Wall"  MATERIAL {_q(t.material)}  '
                f'MODELINGTYPE "ShellThin"  WALLTHICKNESS {_n(u.len(thickness))} '
            )
        self.shell_props[type_id] = line
        self.report.count("shellProperties")
        return type_id

    # ── geometry ──

    def _modifiers(self, kind: str, type_id: str, member: Any = None) -> str:
        own = self._own_modifiers(kind, type_id, member)
        if own is not None:
            return own
        if not self.cracked:
            return ""
        t = self.types.get(type_id)
        material = self.mats.get(t.material) if t else None
        if material is None or material.category.value != "concrete":
            return ""
        if kind == "column":
            f = _CRACKED["column"]
            return f"PROPMODI22 {_n(f)} PROPMODI33 {_n(f)} "
        if kind == "beam":
            f = _CRACKED["beam"]
            return f"PROPMODI22 {_n(f)} PROPMODI33 {_n(f)} "
        if kind == "slab":
            if self.membrane:
                return ""
            f = _CRACKED["slab"]
            return f"PROPMODM11 {_n(f)} PROPMODM22 {_n(f)} PROPMODM12 {_n(f)} "
        if kind == "wall":
            f = _CRACKED["wallCracked" if self.analysis.wallsCracked else "wall"]
            return (
                " ".join(f"PROPMOD{k} {_n(f)}" for k in ("F11", "F22", "F12", "M11", "M22", "M12"))
                + " "
            )
        return ""

    def _own_modifiers(self, kind: str, type_id: str, member: Any) -> str | None:
        """The engineer's stiffness modifiers of a frame (member over type,
        :mod:`saengine.library.modifiers`) as ETABS property modifiers, the code's cracked factor
        for I22 and I33 where none is given; None when the frame has none."""
        from saengine.library.modifiers import resolve_modifiers

        if kind not in ("column", "beam", "brace"):
            return None
        found = {k: v for k, (v, _) in resolve_modifiers(member, self.types.get(type_id)).items()}
        if not found:
            return None
        t = self.types.get(type_id)
        material = self.mats.get(t.material) if t else None
        concrete = material is not None and material.category.value in ("concrete", "masonry")
        code = _CRACKED.get(kind) if self.cracked and concrete else None
        keys = {
            "A": "PROPMODA",
            "As2": "PROPMODA2",
            "As3": "PROPMODA3",
            "J": "PROPMODT",
            "I22": "PROPMODI22",
            "I33": "PROPMODI33",
            "mass": "PROPMODM",
            "weight": "PROPMODW",
        }
        pairs = []
        for key, word in keys.items():
            value = found.get(key)
            if value is None and key in ("I22", "I33") and code is not None:
                value = code
            if value is not None:
                pairs.append(f"{word} {_n(value)}")
        self.report.count("memberModifiers")
        return " ".join(pairs) + " " if pairs else None

    def _member_loads(self) -> None:
        """The line and point loads on members (``05 Floor Plan/loads.json``) on the beams
        they are on, every story of a typical floor's family as in SAEngine's analysis."""
        if self.member_loads is None or not getattr(self.member_loads, "loads", None):
            return
        from saengine.fem.member_loads import member_loads

        found = member_loads(self.b, self.member_loads)
        for line in found.lines:
            a = (line.start[0] * 1000, line.start[1] * 1000)
            c = (line.end[0] * 1000, line.end[1] * 1000)
            z = line.start[2] * 1000
            written = False
            for label, story, s, f, bz in self.beams:
                if abs(bz - z) > TOLERANCE:
                    continue
                span = _overlap(s, f, a, c)
                if span is None:
                    continue
                value = _n(self.u.line(line.load))
                self.line_loads.append(
                    f'  LINELOAD  {_q(label)}  {_q(story)}  TYPE "TRAPF"  DIR "GRAV"  '
                    f"LC {_q(line.case)}  FSTART {value}  FEND {value}  "
                    f"RDSTART {_n(span[0])}  RDEND {_n(span[1])}  "
                )
                written = True
            length = math.dist(a, c) / 1000
            if written:
                self.report.carried[line.case] += line.load * length / 1000
                self.report.count("memberLineLoads")
            else:
                self.report.skip("line loads on no exported beam", line.source)
                self.report.not_carried[line.case] += line.load * length / 1000
        for point in found.points:
            x, y, z = (v * 1000 for v in point.at)
            written = False
            if point.along is not None:
                for label, story, s, f, bz in self.beams:
                    if abs(bz - z) > TOLERANCE:
                        continue
                    rd = _on_beam(s, f, (x, y))
                    if rd is None:
                        continue
                    self.line_loads.append(
                        f'  LINELOAD  {_q(label)}  {_q(story)}  TYPE "POINTF"  DIR "GRAV"  '
                        f"LC {_q(point.case)}  FVAL {_n(self.u.to_force(point.force))}  "
                        f"RDIST {_n(rd)}  "
                    )
                    written = True
                    break
            else:
                at = self._point(x, y, z)
                if at is not None:
                    self.point_loads.append(
                        f'  POINTLOAD  {_q(at[0])}  {_q(self._story(at[1]))}  TYPE "FORCE"  '
                        f"LC {_q(point.case)}    FZ {_n(self.u.to_force(-point.force))}"
                    )
                    written = True
            if written:
                self.report.carried[point.case] += point.force / 1000
                self.report.count("memberPointLoads")
            else:
                self.report.skip("point loads on no exported beam or point", point.source)
                self.report.not_carried[point.case] += point.force / 1000

    def _line(
        self,
        name: str,
        a: tuple[float, float, float],
        c: tuple[float, float, float],
        type_id: str,
        kind: str,
        rotation: float = 0.0,
        released: bool = False,
    ) -> str | None:
        """A frame line; ``kind`` column, beam or brace (by the geometry when not given)."""
        section = self._frame_section(type_id)
        if section is None:
            self.report.skip("members whose section could not be written", name)
            return None
        pa, pc = self._point(*a), self._point(*c)
        if pa is None or pc is None:
            self.report.skip("members above the top story", name)
            return None
        if pa[1] > pc[1] or (pa[1] == pc[1] and a[2] > c[2]):
            pa, pc = pc, pa
        label = self._label(name)
        below = pc[1] - pa[1]
        self.used.update((pa, pc))
        word = {"column": "COLUMN", "beam": "BEAM"}.get(kind, "BRACE")
        place = (pa, pc)
        if place in self.places:
            self.report.approximate(
                "members on the same line as another (ETABS keeps one of them)",
                f"{name} ({self.places[place]})",
            )
        self.places.setdefault(place, name)
        self.lines.append(f"  LINE  {_q(label)}  {word}  {_q(pa[0])}  {_q(pc[0])}  {below}")
        pairs = f"SECTION {_q(section)}  "
        # The building element the line is (a column split per story is "<id>-<k>").
        member = next((e for e in self.b.elements if e.id == name), None) or next(
            (e for e in self.b.elements if name.startswith(f"{e.id}-")), None
        )
        modifiers = self._modifiers(kind, type_id, member)
        if modifiers:
            pairs += modifiers
        angle = rotation + self.extra_rotation.get(section, 0.0)
        angle = (angle + 180.0) % 360.0 - 180.0
        if abs(angle) > 1e-9 and kind != "beam":
            pairs += f"ANG  {_n(angle)} "
        if released:
            pairs += 'RELEASE "M2I M3I M2J M3J"  '
        self.line_assigns.append(
            f"  LINEASSIGN  {_q(label)}  {_q(self._story(pc[1]))}  {pairs}"
            'MINNUMSTA 3 AUTOMESH "YES"  MESHATINTERSECTIONS "YES"  '
        )
        return label

    def _area(
        self,
        name: str,
        kind: Literal["FLOOR", "PANEL"],
        points: list[tuple[float, float, float]],
        pairs: str,
    ) -> tuple[str, str] | None:
        """An area (label, story) with ``pairs`` assigned."""
        at = [self._point(*p) for p in points]
        if any(p is None for p in at):
            self.report.skip("areas above the top story", name)
            return None
        story = max(p[1] for p in at if p is not None)
        label = self._label(name)
        if "OPENING" not in pairs:
            self.used.update(p for p in at if p is not None)
        names = "  ".join(_q(p[0]) for p in at if p is not None)
        offsets = "  ".join(str(story - p[1]) for p in at if p is not None)
        self.areas.append(f"  AREA {_q(label)}  {kind}  {len(at)}  {names}  {offsets}  ")
        self.area_assigns.append(f"  AREAASSIGN  {_q(label)}  {_q(self._story(story))}  {pairs}")
        return label, self._story(story)

    def _released(self, type_id: str) -> bool:
        t = self.types.get(type_id)
        material = self.mats.get(t.material) if t else None
        return (
            getattr(t, "connection", None) is not None
            and material is not None
            and material.category.value == "steel"
        )

    def _geometry(self) -> None:
        levels = [z for _, z, _ in self.levels]
        base, top = levels[0], levels[-1]
        self.base_points: set[str] = set()
        slab_hosts: dict[str, tuple[str, float]] = {}
        for e in self.b.elements:
            if isinstance(e, ColumnElement):
                x, y = e.position
                stops = [e.bottom, *[z for z in levels if e.bottom < z < e.top], e.top]
                if len(stops) > 2:
                    self.report.approximate(
                        "columns through several stories split at each story", e.id
                    )
                for k in range(len(stops) - 1):
                    name = e.id if len(stops) == 2 else f"{e.id}-{k + 1}"
                    label = self._line(
                        name,
                        (x, y, stops[k]),
                        (x, y, stops[k + 1]),
                        e.type,
                        "column",
                        e.rotation,
                    )
                    if label is not None:
                        self.report.count("columns")
                if abs(e.bottom - base) <= TOLERANCE:
                    at = self._point(x, y, e.bottom)
                    if at is not None:
                        self.base_points.add(at[0])
            elif isinstance(e, BeamElement):
                start = (*e.start, e.elevation)
                end = (*e.end, e.elevation)
                label = self._line(e.id, start, end, e.type, "beam", 0.0, self._released(e.type))
                if label is not None:
                    self.report.count("beams")
                    story = self._story_of(e.elevation)
                    if story is not None:
                        self.beams.append(
                            (
                                label,
                                self._story(story[0]),
                                tuple(e.start),
                                tuple(e.end),
                                e.elevation,
                            )  # type: ignore[arg-type]
                        )
            elif isinstance(e, WallElement):
                self._wall(e, levels, base)
            elif isinstance(e, SlabElement):
                prop = self._shell_prop(e.type, "slab")
                if prop is None:
                    continue
                points = [(x, y, e.elevation) for x, y in e.boundary]
                pairs = f"SECTION {_q(prop)}  "
                pairs += self._modifiers("slab", e.type)
                if self.rigid:
                    pairs += 'DIAPH  "D1"  '
                made = self._area(e.id, "FLOOR", points, pairs)
                if made is not None:
                    self.report.count("slabs")
                    slab_hosts[e.id] = (made[0], e.elevation)
                    roof = math.isclose(e.elevation, top)
                    self._slab_loads(e.id, made, e.areaLoad, roof, self._net_area(e))
            elif isinstance(e, FootingElement):
                self.report.skip("footings (9 Substructure: ETABS gets fixed bases)", e.id)
            elif isinstance(e, MemberElement):
                t = self.types.get(e.type)
                kind = _kind_of(e.start, e.end, t.kind if t else None)
                if self._line(
                    e.id,
                    tuple(e.start),
                    tuple(e.end),
                    e.type,
                    kind,
                    e.rotation,
                    self._released(e.type),
                ):  # type: ignore[arg-type]
                    self.report.count("members")
            elif isinstance(e, AreaElement):
                self._special_area(e)
            elif isinstance(e, BlockElement):
                self.report.skip("solid blocks (ETABS has no solids)", e.id)
        for m in self.b.additions.members:
            t = self.types.get(m.type)
            start, end = (m.x1, m.y1, m.z1), (m.x2, m.y2, m.z2)
            kind = _kind_of(start, end, t.kind if t else None)
            if self._line(m.id, start, end, m.type, kind, 0.0, self._released(m.type)):
                self.report.count("braces" if kind == "brace" else "inclinedMembers")
        for o in self.b.additions.slabOpenings:
            host = slab_hosts.get(o.host)
            if host is None:
                self.report.skip("slab openings in no exported slab", o.id)
                continue
            angle = math.radians(o.rotation)
            ca, sa = math.cos(angle), math.sin(angle)
            corners = []
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                dx, dy = sx * o.xDim / 2, sy * o.yDim / 2
                corners.append((o.x + dx * ca - dy * sa, o.y + dx * sa + dy * ca, host[1]))
            if self._area(o.id, "FLOOR", corners, 'OPENING "Yes"  '):
                self.report.count("slabOpenings")
        for o in self.b.additions.wallOpenings:
            self._wall_opening(o)
        for stair in self.b.additions.stairs:
            self.report.skip("stairs (not in SAEngine's analysis either: their loads are not "
                             "applied)", stair.id)  # fmt: skip

    def _wall(self, e: WallElement, levels: list[float], base: float) -> None:
        t = self.types.get(e.type)
        if t is None or t.kind != "wall":
            self.report.skip("walls of unknown object types", e.id)
            return
        if not getattr(t, "structural", True):
            self._partition(e)
            return
        prop = self._shell_prop(e.type, "wall")
        if prop is None:
            return
        stops = [e.bottom, *[z for z in levels if e.bottom < z < e.top], e.top]
        (x0, y0), (x1, y1) = e.start, e.end
        for k in range(len(stops) - 1):
            z0, z1 = stops[k], stops[k + 1]
            name = e.id if len(stops) == 2 else f"{e.id}-{k + 1}"
            pairs = f"SECTION {_q(prop)}  " + self._modifiers("wall", e.type)
            made = self._area(
                name, "PANEL", [(x0, y0, z0), (x1, y1, z0), (x1, y1, z1), (x0, y0, z1)], pairs
            )
            if made is not None:
                self.walls.setdefault(e.id, []).append((made[0], k, z0, z1))
                self.report.count("walls")
            if abs(z0 - base) <= TOLERANCE:
                for x, y in ((x0, y0), (x1, y1)):
                    at = self._point(x, y, z0)
                    if at is not None:
                        self.base_points.add(at[0])
        if len(stops) > 2:
            self.report.approximate("walls through several stories split at each story", e.id)
        self.wall_geometry[e.id] = ((x0, y0), (x1, y1), e.bottom)

    def _wall_opening(self, o: Any) -> None:
        geometry = self.wall_geometry.get(o.host)
        pieces = self.walls.get(o.host)
        if geometry is None or not pieces:
            self.report.skip("wall openings in no exported wall", o.id)
            return
        (x0, y0), (x1, y1), bottom = geometry
        length = math.hypot(x1 - x0, y1 - y0)
        if length <= 0:
            return
        dx, dy = (x1 - x0) / length, (y1 - y0) / length
        z0 = bottom + o.sill
        z1 = z0 + o.height
        if not any(lo - TOLERANCE <= z0 and z1 <= hi + TOLERANCE for _, _, lo, hi in pieces):
            self.report.skip("wall openings across a story level", o.id)
            return
        a, c = o.offset, o.offset + o.width
        corners = [
            (x0 + a * dx, y0 + a * dy, z0),
            (x0 + c * dx, y0 + c * dy, z0),
            (x0 + c * dx, y0 + c * dy, z1),
            (x0 + a * dx, y0 + a * dy, z1),
        ]
        if self._area(o.id, "PANEL", corners, 'OPENING "Yes"  '):
            self.report.count("wallOpenings")

    def _special_area(self, e: AreaElement) -> None:
        t = self.types.get(e.type)
        if t is None or t.kind not in ("slab", "wall"):
            self.report.skip("areas of unknown object types", e.id)
            return
        zs = [p[2] for p in e.outline]
        flat = max(zs) - min(zs) <= TOLERANCE
        prop = self._shell_prop(e.type, "slab" if t.kind == "slab" else "wall")
        if prop is None:
            return
        kind: Literal["FLOOR", "PANEL"] = "FLOOR" if t.kind == "slab" else "PANEL"
        pairs = f"SECTION {_q(prop)}  " + self._modifiers(t.kind, e.type)
        if flat and self.rigid and kind == "FLOOR":
            pairs += 'DIAPH  "D1"  '
        made = self._area(e.id, kind, [tuple(p) for p in e.outline], pairs)  # type: ignore[misc]
        if made is None:
            return
        self.report.count("areas")
        if e.openings:
            self.report.skip("openings of special-structure areas", e.id)
        if e.areaLoad:
            load = next((a for a in self.settings.areaLoads if a.id == e.areaLoad), None)
            if load is not None:
                area = _area3(e.outline)
                self._pressure(made, "SD", load.finish + load.partitions, area)
                self._pressure(made, "L", load.live, area)

    # ── loads ──

    def _net_area(self, slab: SlabElement) -> float:
        """Plan area [m²] of a slab less its openings (ETABS loads no opening)."""
        from shapely.geometry import Polygon, box
        from shapely.ops import unary_union

        outline = Polygon([tuple(p) for p in slab.boundary]).buffer(0)
        holes = []
        for o in self.b.additions.slabOpenings:
            if o.host != slab.id:
                continue
            hole = box(o.x - o.xDim / 2, o.y - o.yDim / 2, o.x + o.xDim / 2, o.y + o.yDim / 2)
            if o.rotation:
                from shapely import affinity

                hole = affinity.rotate(hole, o.rotation, origin=(o.x, o.y))
            holes.append(hole)
        if holes:
            outline = outline.difference(unary_union(holes))
        return outline.area / 1e6

    def _equipment_loads(self) -> None:
        """07 MEP's equipment as point loads shared among its supports (or footprint corners) on
        the floor of its story."""
        levels = {s.id: s.elevation for s in self.b.stories}
        for item in self.equipment:
            z = levels.get(item.story)
            if z is None or not item.points:
                self.report.skip("equipment on no exported story", item.id)
                continue
            if abs(z - self.levels[0][1]) <= TOLERANCE:
                self.report.skip(
                    "equipment at the base (on the ground, as in SAEngine's analysis)", item.id
                )
                continue
            for case, newton in item.loads.items():
                if not newton:
                    continue
                share = newton / len(item.points)
                for x, y in item.points:
                    at = self._point(x, y, z)
                    if at is None:
                        continue
                    self.point_loads.append(
                        f'  POINTLOAD  {_q(at[0])}  {_q(self._story(at[1]))}  TYPE "FORCE"  '
                        f"LC {_q(case)}    FZ {_n(self.u.to_force(-share))}"
                    )
                self.report.carried[case] += newton / 1000
            self.report.count("equipment")
        if self.equipment:
            self.report.approximate(
                "07 MEP equipment as point loads at its supports or footprint corners (ETABS "
                "meshes the floor at them; SAEngine spreads them over the slab's elements)",
                f"{len(self.equipment)} items",
            )
        if any(item.loads.get("F") for item in self.equipment):
            self.patterns.append(("F", "Other", 0))

    def _pressure(self, area: tuple[str, str], case: str, kpa: float, m2: float) -> None:
        if not kpa:
            return
        self.area_loads.append(
            f'  AREALOAD  {_q(area[0])}  {_q(area[1])}  TYPE "UNIFF"  DIR "GRAV"  '
            f"LC {_q(case)}  FVAL {_n(self.u.pressure(kpa))}"
        )
        self.report.carried[case] += kpa * m2

    def _slab_loads(
        self, slab: str, area: tuple[str, str], own: str | None, roof: bool, m2: float
    ) -> None:
        loads = {a.id: a for a in self.settings.areaLoads}
        load_id = own or (self.settings.roofLoad if roof else self.settings.floorLoad)
        load = loads.get(load_id)
        if load is None:
            self.report.skip("slabs whose area load is not in the settings", f"{slab} ({load_id})")
            return
        self._pressure(area, "SD", load.finish + load.partitions, m2)
        self._pressure(area, "Lr" if roof else "L", load.live, m2)

    def _partition(self, e: WallElement) -> None:
        """A non-structural wall: its weight as SD line loads on the beams under it."""
        t = self.types[e.type]
        material = self.mats.get(t.material)
        density = (material.mechanical.density or 0.0) if material else 0.0
        weight = density * G * t.thickness / 1000 * (e.top - e.bottom) / 1000  # N/m
        base = self.levels[0][1]
        if math.isclose(e.bottom, base) or not weight:
            return  # stands on the foundation, as in SAEngine's analysis
        self.partitions.append((e, weight))

    def _partition_loads(self) -> None:
        for e, weight in self.partitions:
            a, c = e.start, e.end
            length = math.dist(a, c)
            if length <= TOLERANCE:
                continue
            covered = 0.0
            for label, story, s, f, z in self.beams:
                if abs(z - e.bottom) > TOLERANCE:
                    continue
                span = _overlap(s, f, a, c)
                if span is None:
                    continue
                r0, r1 = span
                beam_length = math.dist(s, f)
                self.line_loads.append(
                    f'  LINELOAD  {_q(label)}  {_q(story)}  TYPE "TRAPF"  DIR "GRAV"  '
                    f'LC "SD"  FSTART {_n(self.u.line(weight))}  FEND {_n(self.u.line(weight))}  '
                    f"RDSTART {_n(r0)}  RDEND {_n(r1)}  "
                )
                covered += (r1 - r0) * beam_length
            self.report.carried["SD"] += weight * covered / 1e6
            lost = max(length - covered, 0.0)
            if lost > TOLERANCE:
                self.report.skip(
                    "non-structural walls (or parts of them) on no beam: their weight not exported",
                    e.id,
                )
                self.report.not_carried["SD"] += weight * lost / 1e6
            else:
                self.report.count("partitionLoads")

    def _lateral(self) -> None:
        """SAEngine's story forces as point loads at each story's centre of mass (a rigid
        diaphragm) or at the nearest points of the story (a flexible one)."""
        project = self.derivation
        if project is None:
            self.report.warn(
                "SAEngine's analysis model could not be derived: the wind (and earthquake) "
                "patterns have no loads."
            )
            return
        coords = {n["id"]: n["coords"] for n in project.get("nodes", [])}
        patterns = {p["name"]: p for p in project.get("load_patterns", [])}
        cases = ("WX", "WY") if self.lateral == "coefficient" else ("WX", "WY", "EX", "EY")
        # A story's centre: the forces' centroid of the first lateral case that has any.
        by_level: dict[int, dict[str, list[tuple[float, float, float]]]] = defaultdict(dict)
        for case in ("WX", "WY", "EX", "EY"):
            for load in (patterns.get(case) or {}).get("nodal_loads", []):
                xyz = coords.get(load["node_id"])
                if xyz is None:
                    continue
                f = load["forces"]
                value = f[0] if case[1] == "X" else f[1]
                at = self._story_of(xyz[2] * 1000)
                if at is None or at[1] > TOLERANCE or not value:
                    continue
                by_level[at[0]].setdefault(case, []).append((xyz[0] * 1000, xyz[1] * 1000, value))
        for index in sorted(by_level):
            story = self._story(index)
            forces = by_level[index]
            reference = next((forces[c] for c in ("EX", "EY", "WX", "WY") if forces.get(c)), [])
            total = sum(abs(v) for _, _, v in reference)
            if not total:
                continue
            cx = sum(x * abs(v) for x, _, v in reference) / total
            cy = sum(y * abs(v) for _, y, v in reference) / total
            centre = None
            if self.rigid:
                at = self._point(cx, cy, self.levels[index][1])
                if at is not None:
                    centre = at[0]
                    self._assign_point(centre, story, "DIAPH", '"D1"')
            for case in cases:
                values = forces.get(case)
                if not values:
                    continue
                direction = "FX" if case[1] == "X" else "FY"
                if centre is not None:
                    total_case = sum(v for _, _, v in values)
                    self._point_load(centre, story, case, direction, total_case)
                    continue
                for x, y, v in values:  # flexible diaphragm: the nearest point of the story
                    label = self._nearest(x, y)
                    if label is not None:
                        self._point_load(label, story, case, direction, v)
        if not self.rigid:
            self.report.approximate(
                "story forces of a flexible diaphragm at the nearest points of the story"
            )

    def _nearest(self, x: float, y: float) -> str | None:
        best = None
        for label, (px, py, dz) in self.point_xy.items():
            if dz:
                continue
            d = math.hypot(px - x, py - y)
            if best is None or d < best[0]:
                best = (d, label)
        return best[1] if best else None

    def _point_load(self, point: str, story: str, case: str, direction: str, newton: float) -> None:
        self.point_loads.append(
            f'  POINTLOAD  {_q(point)}  {_q(story)}  TYPE "FORCE"  LC {_q(case)}    '
            f"{direction} {_n(self.u.to_force(newton))}"
        )
        self.report.carried[case] += abs(newton) / 1000

    def _assign_point(self, point: str, story: str, key: str, value: str) -> None:
        self.point_assigns.setdefault((point, story), {})[key] = value

    def _seismic_lines(self) -> list[str]:
        if self.lateral != "coefficient":
            return []
        coefficient = self.summary.get("Sa_g")
        period = self.summary.get("period_s")
        if not coefficient or period is None:
            self.report.warn(
                "No BNBC base shear coefficient (site values missing or the analysis model "
                "could not be derived): EX and EY have no loads."
            )
            return []
        k = 1.0 if period <= 0.5 else 2.0 if period >= 2.5 else 1 + (period - 0.5) / 2
        top, bottom = self.levels[-1][0], self.levels[0][0]
        out = []
        for case in ("EX", "EY"):
            out.append(
                f'  SEISMIC {_q(case)}  "User Coefficient"    DIR {_q(case[1])}    '
                f"TOPSTORY {_q(top)}    BOTTOMSTORY {_q(bottom)}    "
                f"SHEARCOEFF {_n(coefficient)}  HEIGHTEXPONENT {_n(k)}"
            )
        self.report.approximate(
            "earthquake as an ETABS user coefficient: ETABS's own seismic weight (mass source) "
            "times SAEngine's base shear coefficient",
            f"C {coefficient:.5g}, k {k:.3g}",
        )
        return out

    # ── the whole file ──

    def run(self, name: str) -> str:
        self.partitions: list[tuple[WallElement, float]] = []
        self.wall_geometry: dict[str, tuple[tuple[float, float], tuple[float, float], float]] = {}
        self._stories()
        self._geometry()
        self._partition_loads()
        self._member_loads()
        self._equipment_loads()
        # supports
        for label in sorted(self.base_points, key=int):
            self._assign_point(label, self.levels[0][0], "RESTRAINT", '"UX UY UZ RX RY RZ"')
        for s in self.b.supports:
            at = self._point(*s.at)
            if at is None:
                self.report.skip("supports above the top story", s.id)
                continue
            fixity = "UX UY UZ RX RY RZ" if s.fixity == "fixed" else "UX UY UZ"
            self._assign_point(at[0], self._story(at[1]), "RESTRAINT", _q(fixity))
            self.report.count("supports")
        self.report.count("supports", len(self.base_points))
        if self.analysis.supports == "soilSprings":
            self.report.approximate(
                "soil springs under the columns (Analysis model → Supports) exported as fixed bases"
            )
        # diaphragm on the points of every story above the base
        if self.rigid:
            for label, (_, _, dz) in self.point_xy.items():
                if dz:
                    continue
                for index in range(1, len(self.levels)):
                    if (label, index) in self.used:
                        self._assign_point(label, self._story(index), "DIAPH", '"D1"')
        self._lateral()
        seismic = self._seismic_lines()
        self._unsupported()
        return self._text(name, seismic)

    def _unsupported(self) -> None:
        a, s = self.analysis, self.settings
        if self.cracked and a.crackedFor == "lateral":
            self.report.approximate(
                "cracked sections for the lateral cases only (Analysis model): ETABS's property "
                "modifiers act in every case"
            )
        if a.secondOrder != "none":
            self.report.skip("P-Delta (Analysis model → Second order) not exported")
        if a.seismicDesign == "responseSpectrum" or a.responseSpectrum:
            self.report.skip("the response spectrum (SAEngine's BNBC spectrum) not exported")
        if a.seismicAccidentalTorsion:
            self.report.skip("accidental torsion of the earthquake cases not exported")
        if a.thermal.enabled:
            self.report.skip("the temperature case T not exported")
        if a.timeHistories:
            self.report.skip(
                "time histories not exported", ", ".join(t.name for t in a.timeHistories)
            )
        if a.pushover is not None:
            self.report.skip("the pushover definition not exported")
        if a.constructionSequence:
            self.report.skip("construction sequence not exported (D in one step)")
        if any(c.T for c in s.combinations):
            self.report.skip("combination factors on the temperature case T dropped")

    def _text(self, name: str, seismic: list[str]) -> str:
        u = self.u
        out: list[str] = [
            f"$ File {name}.e2k written by SAEngine",
            " ",
            "$ PROGRAM INFORMATION",
            f'  PROGRAM  "ETABS"  VERSION {_q(FORMAT_VERSION)}  ',
            "",
            "$ CONTROLS",
            f'  UNITS  {_q(u.force)}  {_q(u.length)}  "C"  ',
            f"  TITLE1  {_q(name)}  ",
            '  TITLE2  "Exported from SAEngine"  ',
            "",
            "$ STORIES - IN SEQUENCE FROM TOP",
        ]
        for k in range(len(self.levels) - 1, 0, -1):
            story, z, similar = self.levels[k]
            height = z - self.levels[k - 1][1]
            text = f"  STORY {_q(story)}  HEIGHT {_n(u.len(height))} "
            if similar:
                text += f"SIMILARTO {_q(similar)}  "
            else:
                text += 'MASTERSTORY "Yes"  '
            out.append(text)
        out.append(f"  STORY {_q(self.levels[0][0])}  ELEV {_n(u.len(self.levels[0][1]))} ")
        self.report.count("stories", len(self.levels))
        out += [
            "$ GRIDS",
            f'  GRIDSYSTEM "G1"  TYPE "CARTESIAN"  BUBBLESIZE {_n(u.len(1250))} ',
            *self.grids,
        ]
        out += ["", "$ DIAPHRAGM NAMES"]
        if self.rigid:
            out.append('  DIAPHRAGM "D1"    TYPE RIGID')
        out += ["", "$ MATERIAL PROPERTIES", *self._material_lines()]
        out += ["", "$ FRAME SECTIONS"]
        for lines in self.frame_sections.values():
            out += lines
        out += ["", "$ CONCRETE SECTIONS", *self.concrete_sections]
        slabs = [v for v in self.shell_props.values() if '"Slab"' in v]
        walls = [v for v in self.shell_props.values() if '"Wall"' in v]
        out += ["", "$ SLAB PROPERTIES", *slabs, "", "$ WALL PROPERTIES", *walls]
        out += ["", "$ POINT COORDINATES"]
        for (x, y, dz), label in self.points.items():
            text = f"  POINT {_q(label)}  {_n(u.len(x))} {_n(u.len(y))} "
            if dz:
                text += f"{_n(u.len(dz))} "
            out.append(text)
        self.report.count("points", len(self.points))
        out += ["", "$ LINE CONNECTIVITIES", *self.lines]
        out += ["", "$ AREA CONNECTIVITIES", *self.areas]
        out += ["", "$ POINT ASSIGNS"]
        for (point, story), pairs in self.point_assigns.items():
            text = "  ".join(f"{k} {v}" for k, v in pairs.items())
            out.append(f"  POINTASSIGN  {_q(point)}  {_q(story)}  {text}  ")
        out += ["", "$ LINE ASSIGNS", *self.line_assigns]
        out += ["", "$ AREA ASSIGNS", *self.area_assigns]
        out += ["", "$ LOAD PATTERNS"]
        for pattern, kind, sw in self.patterns:
            out.append(f"  LOADPATTERN {_q(pattern)}  TYPE  {_q(kind)}  SELFWEIGHT  {sw}")
        out += seismic
        out += ["", "$ POINT OBJECT LOADS", *self.point_loads]
        out += ["", "$ FRAME OBJECT LOADS", *self.line_loads]
        out += ["", "$ SHELL OBJECT LOADS", *self.area_loads]
        out += [
            "",
            "$ ANALYSIS OPTIONS",
            '  ACTIVEDOF "UX UY UZ RX RY RZ"  ',
            '  PDELTA  METHOD "NONE"  ',
            "",
            "$ MASS SOURCE",
            (
                '  MASSSOURCE  "MsSrc1"    INCLUDEELEMENTS "Yes"    INCLUDEADDEDMASS "Yes"    '
                'INCLUDELOADS "Yes"    INCLUDEMOVE "No"    INCLUDELATERALMASS "Yes"    '
                'INCLUDEVERTICALMASS "No"    LUMPATSTORIES "No"    ISDEFAULT "Yes"  '
            ),
            '  MASSSOURCELOAD  "MsSrc1"  "SD"  1 ',
            f'  MASSSOURCELOAD  "MsSrc1"  "L"  {_n(self.live_share)} ',
            *(['  MASSSOURCELOAD  "MsSrc1"  "F"  1 '] if self._fluid else []),
            "",
            "$ LOAD CASES",
            '  LOADCASE "Modal"  TYPE  "Modal - Eigen"  INITCOND  "NONE"  ',
            (
                f'  LOADCASE "Modal"  MAXMODES  {max(12, 3 * (len(self.levels) - 1))} '
                "MINMODES  1 EIGENSHIFTFREQ  0 EIGENCUTOFF  0 EIGENTOL  1E-09 "
            ),
        ]
        for pattern, _, _ in self.patterns:
            out.append(f'  LOADCASE {_q(pattern)}  TYPE  "Linear Static"  INITCOND  "NONE"  ')
            out.append(f"  LOADCASE {_q(pattern)}  LOADPAT  {_q(pattern)}  SF  1 ")
        out += ["", "$ LOAD COMBINATIONS", *self._combinations()]
        # ETABS reads nothing of a file without its log block and the END that closes the model.
        out += [
            "",
            "$ LOG",
            "  STARTCOMMENTS  ",
            "",
            f"Exported from SAEngine: {name}",
            "  ENDCOMMENTS  ",
            "",
            "  END",
            "$ END OF MODEL FILE",
            "",
        ]
        return "\n".join(out)

    @property
    def _fluid(self) -> bool:
        return any(p[0] == "F" for p in self.patterns)

    def _combinations(self) -> list[str]:
        out = []
        taken: set[str] = set()
        for c in self.settings.combinations:
            name, k = c.name.replace('"', "'"), 2
            while name.upper() in taken:
                name, k = f"{c.name} ({k})", k + 1
            taken.add(name.upper())
            terms = [("D", c.D), ("SD", c.D), ("L", c.L), ("Lr", c.Lr)]
            if self._fluid:
                terms.append(("F", c.F or 0.0))
            terms += [(case, getattr(c, case)) for case in ("WX", "WY", "EX", "EY")]
            out.append(f'  COMBO {_q(name)}  TYPE "Linear Add"  ')
            for case, factor in terms:
                if factor:
                    out.append(f"  COMBO {_q(name)}  LOADCASE {_q(case)}  SF {_n(factor)} ")
            self.report.count("combinations")
        return out


# ─────────────────────────────────────────── helpers ───────────────────────────────────────────


def _element_levels(e: Any) -> list[float]:
    if isinstance(e, MemberElement):
        return [e.start[2], e.end[2]]
    if isinstance(e, AreaElement | BlockElement):
        return [p[2] for p in e.outline]
    if isinstance(e, ColumnElement | WallElement):
        return [e.bottom, e.top]
    if isinstance(e, BeamElement | SlabElement | FootingElement):
        return [e.elevation]
    return []


def _kind_of(a: Any, c: Any, kind: str | None) -> str:
    """column, beam or brace by a member's direction (an inclined column or beam is a brace
    line in ETABS, its section unchanged)."""
    plan = math.hypot(c[0] - a[0], c[1] - a[1])
    rise = abs(c[2] - a[2])
    if plan <= TOLERANCE:
        return "column"
    if rise <= TOLERANCE:
        return "beam"
    return "brace"


def _polygon_area(points: list[list[float]]) -> float:
    """Plan area [m²] of a polygon in mm."""
    n = len(points)
    twice = sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )
    return abs(twice) / 2 / 1e6


def _area3(points: list[list[float]]) -> float:
    from saengine.importers.common import polygon_area

    return polygon_area([tuple(p) for p in points])  # type: ignore[misc]


def _on_beam(s: tuple[float, float], f: tuple[float, float], p: Any) -> float | None:
    """The relative distance (0-1) of point ``p`` along beam ``s``-``f`` when it is on it."""
    length = math.dist(s, f)
    if length <= TOLERANCE:
        return None
    ux, uy = (f[0] - s[0]) / length, (f[1] - s[1]) / length
    if abs((p[0] - s[0]) * uy - (p[1] - s[1]) * ux) > TOLERANCE:
        return None
    t = ((p[0] - s[0]) * ux + (p[1] - s[1]) * uy) / length
    return round(t, 6) if -1e-9 <= t <= 1 + 1e-9 else None


def _overlap(
    s: tuple[float, float], f: tuple[float, float], a: Any, c: Any
) -> tuple[float, float] | None:
    """The relative distances (0-1) along beam ``s``-``f`` that wall ``a``-``c`` covers, when
    they are in line in plan; None otherwise."""
    length = math.dist(s, f)
    if length <= TOLERANCE:
        return None
    ux, uy = (f[0] - s[0]) / length, (f[1] - s[1]) / length
    for p in (a, c):
        if abs((p[0] - s[0]) * uy - (p[1] - s[1]) * ux) > TOLERANCE:
            return None
    t0 = ((a[0] - s[0]) * ux + (a[1] - s[1]) * uy) / length
    t1 = ((c[0] - s[0]) * ux + (c[1] - s[1]) * uy) / length
    lo, hi = max(min(t0, t1), 0.0), min(max(t0, t1), 1.0)
    if hi - lo <= TOLERANCE / length:
        return None
    return round(lo, 6), round(hi, 6)


# ─────────────────────────────────────────── projects ───────────────────────────────────────────


class E2kExportError(ValueError):
    """The project cannot be exported (not a building with a building model, or parts with
    errors)."""


def export_e2k(
    project: str | Path,
    *,
    units: tuple[str, str] = ("KN", "M"),
    lateral: Lateral = "loads",
    library_shapes: bool = True,
    derive: bool = True,
) -> E2kExport:
    """The e2k export of the project at ``project`` (its folder or ``.saengine`` file).

    The parts are read as the analysis reads them (06 BIM, 04 Objects, 03 Materials, 02 Project
    Settings, with the site class from the soil report where the settings say so); with
    ``derive``, SAEngine's analysis model is derived (as Run All's Derive step does) for its
    wind and earthquake story forces.
    """
    from pydantic import ValidationError

    from saengine.codes import context as code_context
    from saengine.pipeline.project import ProjectError, open_project

    try:
        p = open_project(project)
    except ProjectError as error:
        raise E2kExportError(str(error)) from error
    texts = p.texts(("bim", "objects", "materials", "settings"))
    missing = [k for k, v in texts.items() if not v]
    if missing:
        raise E2kExportError(f"{p.name}: no {', '.join(missing)} file to export from")
    try:
        building = BuildingModel.model_validate_json(texts["bim"])  # type: ignore[arg-type]
        objects = ObjectLibrary.model_validate_json(texts["objects"])  # type: ignore[arg-type]
        materials = MaterialLibrary.model_validate_json(texts["materials"])  # type: ignore[arg-type]
        settings = ProjectSettings.model_validate_json(texts["settings"])  # type: ignore[arg-type]
    except ValidationError as error:
        raise E2kExportError(f"{p.name}: a part has errors: {error.errors()[0]['msg']}") from error
    from saengine.library.settings import read_soil_text, resolve_site_class

    settings, _ = resolve_site_class(settings, read_soil_text(p.root))
    derivation: dict[str, Any] | None = None
    summary: dict[str, Any] = {}
    notes: list[str] = []
    if derive:
        import json

        from saengine.rpc.handlers import derive_fem

        result = derive_fem(
            texts["bim"],  # type: ignore[arg-type]
            texts["objects"],  # type: ignore[arg-type]
            texts["materials"],  # type: ignore[arg-type]
            texts["settings"],  # type: ignore[arg-type]
            str(p.folder("fem")),
        )
        if result.get("text"):
            derivation = json.loads(result["text"])
            summary = result.get("summary") or {}
        else:
            notes = list(result.get("problems") or [])
    with code_context.using(code_context.pack_for(settings, p.root)):
        live_share = float(code_context.table("seismic").liveShare)
    from saengine.library import mep as mep_library

    try:
        mep = mep_library.parse(p.text("mep"))
    except ValueError:
        mep = None
        notes.append("07 MEP has errors: its openings and shafts are not cut from the slabs.")
    if mep is not None and (mep.openings or mep.shafts):
        from saengine.mep.loads import with_mep_openings

        # The analysis cuts MEP's openings and shafts from the slabs and walls: so does ETABS.
        building, _ = with_mep_openings(building, mep)
    grids: list[tuple[str, str, float]] = []
    plan_text = p.text("floorPlan")
    if plan_text:
        from saengine.library.floorplan import FloorPlan

        try:
            plan = FloorPlan.model_validate_json(plan_text)
            grids = [("X", g.label, g.position) for g in plan.grids.x]
            grids += [("Y", g.label, g.position) for g in plan.grids.y]
        except ValidationError:
            report_note = "The floor plan has errors: no grid lines exported."
            notes.append(report_note)
    from saengine.library import line_loads
    from saengine.pipeline.project import read_text

    try:
        member_loads = line_loads.parse(read_text(p.root / line_loads.LOADS_FILE))
    except ValueError:
        member_loads = None
        notes.append("05 Floor Plan/loads.json has errors: the member loads are not exported.")
    export = write_e2k(
        building,
        objects,
        materials,
        settings,
        member_loads=member_loads,
        name=p.name,
        grids=grids,
        equipment=equipment_of(mep, materials) if mep is not None else [],
        units=units,
        lateral=lateral,
        derivation=derivation,
        summary=summary,
        live_share=live_share,
        library_shapes=library_shapes,
    )
    report = export.report
    report.source["project"] = p.name
    for note in notes:
        report.warn(f"Derivation: {note}")
    stale = building.source and building.source.floorPlan
    if stale and plan_text:
        from saengine.library.bim import source_stamp

        if source_stamp(plan_text) != building.source.floorPlan:  # type: ignore[union-attr]
            report.warn(
                "The building model (06 BIM) is older than the floor plan: rebuild it to export "
                "the latest plan."
            )
    return export


__all__ = [
    "E2kExport",
    "E2kExportError",
    "Equipment",
    "ExportReport",
    "designation",
    "equipment_of",
    "export_e2k",
    "library_shape",
    "write_e2k",
]

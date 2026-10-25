"""Shared parts of the model importers: units, the import report and the project builder.

An importer reads its program's file into the neutral model of :class:`ProjectBuilder`: stories,
grid lines, materials, frame and shell sections, frame members and areas as 3D geometry in mm,
supports, area loads and combinations on SAEngine's load cases. :meth:`ProjectBuilder.build`
turns it into SAEngine's parts:

- ``03 Materials``: the materials, in SAEngine's fixed units (MPa, kg/m³);
- ``04 Objects``: one object type per section and kind it is used as (column, beam, brace,
  slab, wall);
- ``05 Floor Plan``: grid lines and stories, and the members that map onto them: vertical
  columns and rectangular walls between stories, horizontal beams and slabs at a story level,
  placed on their nearest grid lines with offsets;
- ``06 BIM``: the building model generated from that floor plan, with the members that do not
  map onto it (braces, sloped beams, raking columns) as its inclined members, rectangular
  slab openings, wall openings (gaps of merged wall panels) and the supports that differ from
  SAEngine's own fixed bases (pinned bases, supports elsewhere);
- ``02 Project Settings``: SAEngine's default settings with the floor and roof area loads (slabs
  with other loads get area loads of their own, named on the floor-plan slab), the load
  combinations and the analysis values the file fixes (cracked sections).

SAEngine derives its own loads (:mod:`saengine.fem.derive`): self-weight from the material
densities, superimposed dead and live loads on the slabs from the floor and roof area loads,
wind and earthquake from the BNBC settings. The file's member and joint loads of gravity cases
become SAEngine's member loads (``05 Floor Plan/loads.json``, :mod:`saengine.library.
line_loads`) on the floor-plan beams and columns (:meth:`ProjectBuilder._build_member_loads`).
Loads that have no place there (loads on braces and inclined members, area loads on walls, loads
at supports) are not carried over; the report lists them with their totals, so the engineer
sees how much of the source model's gravity load is missing. Loads of wind and earthquake cases
are listed apart, as replaced by SAEngine's own (they are not lost).

The report (:class:`ImportReport`) counts what was imported by kind and lists what was
approximated, what was skipped and what SAEngine replaces, each with a count and a few examples;
the items all importers share are worded once, in :data:`ITEMS`.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from saengine.library import line_loads as ll
from saengine.library.bim import (
    Additions,
    BimSupport,
    BuildingModel,
    InclinedMember,
    SlabOpening,
    WallOpening,
    generate,
    source_stamp,
)
from saengine.library.floorplan import FloorPlan
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import (
    AreaLoad,
    LoadCombination,
    ProjectSettings,
    default_project_settings,
)
from saengine.library.settings import check as check_settings

G = 9.80665  # m/s²

#: Coordinates closer than this are the same [mm]; members within it of the vertical (or the
#: horizontal) are columns (or beams), points within it of a story's level are on it.
TOLERANCE = 1.0

#: Examples kept for each approximated or skipped item of the report.
MAX_EXAMPLES = 5

#: SAEngine's load cases that combinations and loads can refer to (see saengine.fem.derive).
CASES = ("D", "L", "Lr", "WX", "WY", "EX", "EY", "T", "F")

FrameKind = Literal["column", "beam", "brace"]
AreaKind = Literal["floor", "wall"]
Point3 = tuple[float, float, float]

# ─────────────────────────────────────────── units ───────────────────────────────────────────

_LENGTH = {
    "MM": 1.0,
    "MMS": 1.0,
    "MILLIMETER": 1.0,
    "MILLIMETRE": 1.0,
    "CM": 10.0,
    "CMS": 10.0,
    "CENTIMETER": 10.0,
    "M": 1000.0,
    "MS": 1000.0,
    "MET": 1000.0,
    "METER": 1000.0,
    "METRE": 1000.0,
    "METERS": 1000.0,
    "IN": 25.4,
    "INCH": 25.4,
    "INCHES": 25.4,
    "INC": 25.4,
    "FT": 304.8,
    "FEET": 304.8,
    "FOOT": 304.8,
    "FEE": 304.8,
}
_FORCE = {
    "N": 1.0,
    "NEWTON": 1.0,
    "NEWTONS": 1.0,
    "NEW": 1.0,
    "KN": 1000.0,
    "KNS": 1000.0,
    "KILONEWTON": 1000.0,
    "MN": 1.0e6,
    "LB": 4.4482216152605,
    "LBS": 4.4482216152605,
    "POUND": 4.4482216152605,
    "POUNDS": 4.4482216152605,
    "KIP": 4448.2216152605,
    "KIPS": 4448.2216152605,
    "KGF": G,
    "KG": G,
    "KGS": G,
    "TONF": 1000 * G,
    "TON": 1000 * G,
    "MTON": 1000 * G,
    "MTONS": 1000 * G,
    "TONNE": 1000 * G,
    "MTO": 1000 * G,
}


@dataclass(frozen=True)
class Units:
    """The force and length units of a file, and conversions to SAEngine's fixed units."""

    force: str = "N"
    length: str = "MM"

    @classmethod
    def parse(cls, force: str, length: str) -> Units:
        f, n = force.strip().upper(), length.strip().upper()
        if f not in _FORCE:
            raise ValueError(f"unknown force unit '{force}'")
        if n not in _LENGTH:
            raise ValueError(f"unknown length unit '{length}'")
        return cls(f, n)

    @staticmethod
    def is_force(token: str) -> bool:
        return token.strip().upper() in _FORCE

    @staticmethod
    def is_length(token: str) -> bool:
        return token.strip().upper() in _LENGTH

    @property
    def mm(self) -> float:
        """mm per length unit."""
        return _LENGTH[self.length]

    @property
    def newton(self) -> float:
        """N per force unit."""
        return _FORCE[self.force]

    @property
    def label(self) -> str:
        return f"{self.force.lower()}-{self.length.lower()}"

    def to_mm(self, value: float) -> float:
        return value * self.mm

    def to_kn(self, value: float) -> float:
        return value * self.newton / 1000

    def to_mpa(self, value: float) -> float:
        """A stress (force/length²) in MPa."""
        return value * self.newton / self.mm**2

    def to_kpa(self, value: float) -> float:
        """A pressure (force/length²) in kN/m²."""
        return self.to_mpa(value) * 1000

    def to_kn_per_m(self, value: float) -> float:
        """A line load (force/length) in kN/m."""
        return value * self.newton / self.mm

    def to_density(self, weight_per_volume: float) -> float:
        """A unit weight (force/length³) as a mass density in kg/m³."""
        return weight_per_volume * self.newton / self.mm**3 * 1e9 / G


#: Reinforcing bar designations to diameters [mm]: US (#n), Canadian (nM); metric sizes are
#: read from their number (16, 16d, T16, Y16, R10, 16mm, ϕ16).
_US_BARS = {
    3: 9.525,
    4: 12.7,
    5: 15.875,
    6: 19.05,
    7: 22.225,
    8: 25.4,
    9: 28.65,
    10: 32.26,
    11: 35.81,
    14: 43.0,
    18: 57.33,
}
_CANADIAN_BARS = {10: 11.3, 15: 16.0, 20: 19.5, 25: 25.2, 30: 29.9, 35: 35.7, 45: 43.7, 55: 56.4}


def bar_diameter(size: str | None) -> float | None:
    """The diameter [mm] of a bar designation, or None when it is not one."""
    if not size:
        return None
    text = size.strip().upper().replace(" ", "")
    us = re.fullmatch(r"#(\d+)", text)
    if us:
        return _US_BARS.get(int(us.group(1)))
    canadian = re.fullmatch(r"(\d+)M", text)
    if canadian:
        return _CANADIAN_BARS.get(int(canadian.group(1)))
    metric = re.fullmatch(r"(?:[TYRHΦϕØ]|DIA)?(\d+(?:\.\d+)?)(?:D|MM)?", text)
    if metric:
        value = float(metric.group(1))
        return value if 5 <= value <= 60 else None
    return None


# ─────────────────────────────────────────── report ───────────────────────────────────────────


#: The report's items every importer can give, by key: (list, what). The importers word these
#: items the same through :meth:`ImportReport.note`, and each item carries its key, so a reader
#: of the report can tell them apart without matching the wording. Lists: "approximated" (in,
#: not as in the file), "skipped" (left out), "replaced" (SAEngine makes its own in their place:
#: wind and earthquake loads from the BNBC 2020 settings).
ITEMS: dict[str, tuple[str, str]] = {
    # ── loads SAEngine replaces with its own ──
    "loads.lateral.generated": (
        "replaced",
        (
            "wind and earthquake load generators of the file (SAEngine makes its own wind and "
            "earthquake loads from BNBC 2020, 02 Project Settings)"
        ),
    ),
    "loads.lateral.cases": (
        "replaced",
        "wind and earthquake load cases (SAEngine applies its own BNBC 2020 loads in their place)",
    ),
    "loads.lateral.joint": ("replaced", "joint loads of wind and earthquake cases"),
    "loads.lateral.member": ("replaced", "member loads of wind and earthquake cases"),
    "loads.lateral.area": ("replaced", "area and floor loads of wind and earthquake cases"),
    # ── loads left out ──
    "loads.noCase.joint": ("skipped", "joint loads of load cases SAEngine has no case for"),
    "loads.noCase.member": ("skipped", "member loads of load cases SAEngine has no case for"),
    "loads.noCase.area": ("skipped", "area and floor loads of load cases SAEngine has no case for"),
    "loads.patterns.noCase": ("skipped", "load patterns of types SAEngine has no case for"),
    "loads.member.notOnBeam": (
        "skipped",
        (
            "member loads on columns, braces and inclined members (SAEngine's member loads are on "
            "floor-plan beams)"
        ),
    ),
    "loads.member.notImported": ("skipped", "member loads on members that were not imported"),
    "loads.member.direction": (
        "skipped",
        "member loads with no vertical part (horizontal, or in local axes not read)",
    ),
    "loads.member.moments": ("skipped", "member moments"),
    "loads.joint.direction": ("skipped", "joint loads with no vertical part (horizontal)"),
    "loads.joint.moments": ("skipped", "joint moments"),
    "loads.joint.support": (
        "skipped",
        (
            "joint loads at supports (they go straight into the support; add them to the "
            "foundation loads)"
        ),
    ),
    "loads.joint.noMember": ("skipped", "joint loads at points with no column or beam"),
    "combinations.envelope": ("skipped", "envelope, SRSS and absolute combinations"),
    # ── loads taken over, not as in the file ──
    "loads.member.partial": (
        "approximated",
        (
            "line loads on part of a beam as a point load of their total at the middle of the "
            "loaded part"
        ),
    ),
    "loads.member.varying": (
        "approximated",
        "trapezoidal and triangular member loads as their mean over the loaded length",
    ),
    "loads.horizontal": (
        "approximated",
        "horizontal parts of member and joint loads of gravity cases left out",
    ),
    "loads.fluid": (
        "approximated",
        "fluid member and joint loads as superimposed dead loads (D factors)",
    ),
    "loads.joint.onBeam": (
        "approximated",
        "joint loads with no column below them as point loads on the beam there",
    ),
    "settings.defaultAreaLoads": (
        "approximated",
        (
            "area loads not in the file: SAEngine's defaults kept, named '(SAEngine default)' "
            "(02 Project Settings)"
        ),
    ),
    "combinations.noFluid": (
        "approximated",
        (
            "combinations with F (fluid) 0: the file has no fluid loads (set F in 02 Project "
            "Settings if 07 MEP adds tanks)"
        ),
    ),
}


@dataclass
class _Entry:
    count: int = 0
    examples: list[str] = field(default_factory=list)
    key: str | None = None


class ImportReport:
    """What an import brought in, approximated, skipped and left to SAEngine's own loads."""

    def __init__(self, program: str, file: str | None = None) -> None:
        self.source: dict[str, Any] = {"program": program, "file": file}
        self.imported: Counter[str] = Counter()
        self._approximated: dict[str, _Entry] = {}
        self._skipped: dict[str, _Entry] = {}
        self._replaced: dict[str, _Entry] = {}
        self.warnings: list[str] = []
        #: What makes the imported model unusable as it stands (also first in the warnings).
        self.errors: list[str] = []
        #: Loads not carried over, total [kN] (down positive for gravity) per SAEngine case.
        self.not_carried: dict[str, float] = defaultdict(float)
        self.carried: dict[str, float] = defaultdict(float)
        #: Wind and earthquake loads of the file that SAEngine replaces with its own from the
        #: BNBC 2020 settings, their size [kN] per SAEngine case: not lost loads.
        self.replaced: dict[str, float] = defaultdict(float)

    def count(self, kind: str, n: int = 1) -> None:
        self.imported[kind] += n

    @staticmethod
    def _add(
        entries: dict[str, _Entry], what: str, example: str | None, key: str | None = None
    ) -> None:
        entry = entries.setdefault(what, _Entry(key=key))
        entry.count += 1
        if example and len(entry.examples) < MAX_EXAMPLES and example not in entry.examples:
            entry.examples.append(example)

    def approximate(self, what: str, example: str | None = None, key: str | None = None) -> None:
        """``what`` was imported, but not as it is in the file."""
        self._add(self._approximated, what, example, key)

    def skip(self, what: str, example: str | None = None, key: str | None = None) -> None:
        """``what`` was left out."""
        self._add(self._skipped, what, example, key)

    def replace(self, what: str, example: str | None = None, key: str | None = None) -> None:
        """``what`` (wind and earthquake loads) is left to SAEngine, which makes its own."""
        self._add(self._replaced, what, example, key)

    def note(self, key: str, example: str | None = None) -> None:
        """The shared item ``key`` of :data:`ITEMS`, in its list and wording."""
        kind, what = ITEMS[key]
        entries = {
            "approximated": self._approximated,
            "skipped": self._skipped,
            "replaced": self._replaced,
        }[kind]
        self._add(entries, what, example, key)

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    def error(self, text: str) -> None:
        """A problem the engineer must fix before the model can be used: listed in ``errors``
        and, for readers that show only the warnings, at the top of them."""
        if text not in self.errors:
            self.errors.append(text)
            self.warnings.insert(len(self.errors) - 1, f"Error: {text}")

    @staticmethod
    def _items(entries: dict[str, _Entry]) -> list[dict[str, Any]]:
        items = []
        for what, entry in entries.items():
            item: dict[str, Any] = {"what": what, "count": entry.count, "examples": entry.examples}
            if entry.key:
                item["key"] = entry.key
            items.append(item)
        return items

    @property
    def approximated(self) -> list[dict[str, Any]]:
        return self._items(self._approximated)

    @property
    def skipped(self) -> list[dict[str, Any]]:
        return self._items(self._skipped)

    @property
    def replaced_items(self) -> list[dict[str, Any]]:
        """The wind and earthquake loads and generators SAEngine makes its own of."""
        return self._items(self._replaced)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "saengine.importReport/1",
            "source": self.source,
            "imported": dict(self.imported),
            "approximated": self.approximated,
            "skipped": self.skipped,
            "replaced": self.replaced_items,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "loads": {
                "carriedKN": {k: round(v, 3) for k, v in self.carried.items()},
                "notCarriedKN": {k: round(v, 3) for k, v in self.not_carried.items()},
                "replacedByBnbcKN": {k: round(v, 3) for k, v in self.replaced.items()},
            },
        }


# ─────────────────────────────────────────── ids ───────────────────────────────────────────


def _id(name: str, taken: set[str]) -> str:
    """A unique SAEngine id (``^[A-Za-z0-9._-]+$``, at most 64 characters) for ``name``."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:56] or "X"
    candidate, k = base, 2
    while candidate in taken:
        candidate, k = f"{base}-{k}", k + 1
    taken.add(candidate)
    return candidate


def _grid_label(name: str, taken: set[str], fallback: str) -> str:
    base = re.sub(r"[^A-Za-z0-9.'-]+", "", name)[:8] or fallback
    candidate, k = base, 2
    while candidate in taken:
        suffix = f"-{k}"
        candidate, k = base[: 8 - len(suffix)] + suffix, k + 1
    taken.add(candidate)
    return candidate


def _letters(index: int) -> str:
    """A, B, ..., Z, AA, AB, ..."""
    text = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        text = chr(65 + rest) + text
    return text


def _clean(value: Any) -> Any:
    """JSON values with whole floats as integers and the rest to 6 decimals."""
    if isinstance(value, float):
        rounded = round(value, 6)
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def json_text(model: Any) -> str:
    data = (
        model
        if isinstance(model, dict)
        else model.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    return json.dumps(_clean(data), indent="\t", ensure_ascii=False) + "\n"


# ─────────────────────────────────────── neutral model ───────────────────────────────────────


@dataclass
class _FrameSection:
    name: str
    material: str  # source material name
    #: SAEngine profile (objects.Profile as JSON) as in a beam: yDim / overallDepth / depth is
    #: the source program's depth (local 2 axis), xDim / overallWidth its width.
    profile: dict[str, Any]
    column_reinforcement: dict[str, Any] | None = None
    beam_reinforcement: dict[str, Any] | None = None


@dataclass
class _ShellSection:
    name: str
    material: str
    thickness: float  # mm


@dataclass
class _Frame:
    name: str
    section: str
    start: Point3
    end: Point3
    kind: FrameKind | None
    rotation: float
    pinned: bool = False  # both ends released in bending


@dataclass
class _Area:
    name: str
    section: str
    points: list[Point3]
    kind: AreaKind | None


@dataclass
class _MemberLoad:
    """A load on frame member ``frame``: ``force`` (x, y, z; Z up) in kN/m along it (a line
    load) or in kN (a point load), ``start`` [mm] from the member's start (a line load's loaded
    part, a point load's place; None: the start, or the middle for a point load) and ``length``
    [mm] of a line load's loaded part (None: to the member's end)."""

    frame: str
    case: str | None
    force: Point3
    point: bool
    start: float | None
    length: float | None
    example: str


@dataclass
class _JointLoad:
    """A force (x, y, z; Z up) [kN] at a point [mm]."""

    at: Point3
    case: str | None
    force: Point3
    example: str


@dataclass
class ImportedProject:
    """A SAEngine project built by an importer: its parts' texts by path and the report."""

    name: str
    settings: ProjectSettings
    materials: MaterialLibrary
    objects: ObjectLibrary
    floor_plan: FloorPlan
    bim: BuildingModel
    report: ImportReport
    texts: dict[str, str]
    #: The file's member and joint loads on the floor-plan beams and columns (None: none).
    member_loads: ll.MemberLoads | None = None

    def problems(self) -> list[str]:
        """Problems across the parts (references), as SAEngine's editors report them."""
        loads = ll.check(self.member_loads, self.floor_plan) if self.member_loads else []
        return [
            *loads,
            *self.objects.check_materials(self.materials),
            *self.floor_plan.check_objects(self.objects),
            *self.bim.check_objects(self.objects),
            *self.bim.check_additions(),
            *check_settings(self.settings),
        ]

    def write(self, folder: str | Path, manifest: bool = True) -> list[Path]:
        """Writes the parts (and, with ``manifest``, the project manifest when the folder has
        none) into ``folder``; returns the files written. Existing part files are replaced."""
        root = Path(folder)
        written = []
        texts = dict(self.texts)
        if manifest and not any(root.glob("*.saengine")):
            safe = re.sub(r'[<>:"/\\|?*]+', "-", self.name).strip() or "Imported"
            texts[f"{safe}.saengine"] = json_text(
                {
                    "schema": 1,
                    "name": self.name,
                    "created": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "type": "building",
                    "parts": [
                        "soil",
                        "settings",
                        "materials",
                        "objects",
                        "floorPlan",
                        "bim",
                        "mep",
                        "fem",
                        "substructure",
                        "boq",
                        "exports",
                    ],
                }
            )
        for relative, text in texts.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written.append(path)
        return written


#: Where the parts and the report are written, relative to the project folder.
PATHS = {
    "settings": "02 Project Settings/project-settings.json",
    "materials": "03 Materials/materials.json",
    "objects": "04 Objects/objects.json",
    "floorPlan": "05 Floor Plan/floor-plan.json",
    "bim": "06 BIM/bim.json",
    "memberLoads": ll.LOADS_FILE,
    "report": "import-report.json",
}


class ProjectBuilder:
    """Collects a model in the neutral form and builds SAEngine's parts from it.

    All lengths and coordinates are in mm, stresses in MPa, densities in kg/m³, pressures in
    kN/m², forces in kN; importers convert with :class:`Units`. Names are the source program's;
    the builder makes SAEngine ids of them.
    """

    def __init__(self, name: str, report: ImportReport) -> None:
        self.name = name
        self.report = report
        self._materials: dict[str, dict[str, Any]] = {}  # source name -> Material JSON
        self._material_ids: dict[str, str] = {}
        self._frame_sections: dict[str, _FrameSection] = {}
        self._shell_sections: dict[str, _ShellSection] = {}
        self._stories: list[tuple[str, float]] = []
        self._grids: dict[str, list[tuple[str, float]]] = {"x": [], "y": []}
        self._frames: list[_Frame] = []
        self._areas: list[_Area] = []
        self._openings: list[tuple[str, list[Point3]]] = []
        self._supports: list[tuple[Point3, tuple[bool, ...], str]] = []
        self._area_m2: dict[str, float] = {}
        self._area_loads: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._combinations: list[tuple[str, dict[str, float]]] = []
        self._member_loads: list[_MemberLoad] = []
        self._joint_loads: list[_JointLoad] = []
        #: Slab id -> the area load of its own (slabs on the settings' floor or roof load are
        #: not listed); filled when the settings are built.
        self.slab_loads: dict[str, str] = {}
        self.self_weight = True
        #: Point springs of the file SAEngine could not take over (see the supports).
        self.springs = 0
        #: Values for the settings' analysis model (``Analysis`` fields) the file fixes.
        self.analysis: dict[str, Any] = {}

    # ── materials and sections ──

    def add_material(
        self,
        name: str,
        category: Literal["concrete", "steel", "rebar", "masonry", "other"],
        *,
        E: float | None = None,
        nu: float | None = None,
        density: float | None = None,
        alpha: float | None = None,
        fc: float | None = None,
        fy: float | None = None,
        fu: float | None = None,
        grade: str | None = None,
    ) -> None:
        """A material in SAEngine units (MPa, kg/m³). Missing code values get defaults that the
        report lists as approximated."""
        if name in self._materials:
            return
        example = name
        mechanical: dict[str, Any] = {}
        if category in ("concrete", "steel", "rebar") and not E:
            if category == "concrete":
                E = 4700 * math.sqrt(fc or 25.0)
            else:
                E = 200000.0
            self.report.approximate(
                "material without E: E from the code formula or 200 GPa", example
            )
        if E:
            mechanical["E"] = E
        if nu is not None and 0 <= nu < 0.5:
            mechanical["nu"] = nu
        if density and density > 0:
            mechanical["density"] = density
        elif category != "other":
            self.report.approximate("material without weight: no self-weight from it", example)
        if alpha is not None and alpha >= 0:
            mechanical["alpha"] = alpha
        data: dict[str, Any] = {"name": name, "category": category, "mechanical": mechanical}
        if category == "concrete":
            if not fc:
                fc = 25.0
                self.report.approximate("concrete without f'c: taken as 25 MPa", example)
            data["concrete"] = {"fc": fc}
        elif category in ("steel", "rebar"):
            if not fy:
                fy = 250.0 if category == "steel" else 420.0
                self.report.approximate(
                    "steel without fy: 250 MPa (structural) or 420 MPa (bars)", example
                )
            steel: dict[str, Any] = {"fy": fy, "grade": grade or name}
            if fu and fu >= fy:
                steel["fu"] = fu
            data["steel"] = steel
        elif category == "masonry":
            data["masonry"] = {"unit": "masonry (imported)"}
        data["source"] = {"note": f"Imported from {self.report.source['program']}."}
        self._materials[name] = data

    def add_frame_section(
        self,
        name: str,
        material: str,
        profile: dict[str, Any],
        *,
        column_reinforcement: dict[str, Any] | None = None,
        beam_reinforcement: dict[str, Any] | None = None,
    ) -> None:
        """A frame section; ``profile`` is a SAEngine profile as in a beam (see _FrameSection).
        Reinforcement is objects.LinearReinforcement JSON with the *source* rebar material name."""
        self._frame_sections[name] = _FrameSection(
            name, material, profile, column_reinforcement, beam_reinforcement
        )

    def add_shell_section(self, name: str, material: str, thickness: float) -> None:
        self._shell_sections[name] = _ShellSection(name, material, thickness)

    def has_frame_section(self, name: str) -> bool:
        return name in self._frame_sections

    def has_shell_section(self, name: str) -> bool:
        return name in self._shell_sections

    # ── geometry ──

    def add_story(self, name: str, elevation: float) -> None:
        self._stories.append((name, elevation))

    def add_grid(self, axis: Literal["x", "y"], label: str, position: float) -> None:
        self._grids[axis].append((label, position))

    def add_frame(
        self,
        name: str,
        section: str,
        start: Point3,
        end: Point3,
        kind: FrameKind | None = None,
        rotation: float = 0.0,
        pinned: bool = False,
    ) -> None:
        """A frame member; ``kind`` None: by its direction (vertical: column, horizontal: beam,
        else brace). ``rotation`` [°] about its axis, as the source program's angle. ``pinned``:
        both ends released in bending (steel beams and braces get a simple connection, which
        SAEngine analyses as pinned ends; other members are reported as continuous)."""
        self._frames.append(
            _Frame(name, section, tuple(start), tuple(end), kind, rotation, pinned)  # type: ignore[arg-type]
        )

    def add_area(
        self, name: str, section: str, points: list[Point3], kind: AreaKind | None = None
    ) -> None:
        self._areas.append(_Area(name, section, [tuple(p) for p in points], kind))  # type: ignore[misc]
        self._area_m2[name] = polygon_area([tuple(p) for p in points])  # type: ignore[misc]

    def area_of(self, name: str) -> float:
        """Area [m²] of area ``name`` (0 when unknown)."""
        return self._area_m2.get(name, 0.0)

    def add_opening(self, name: str, points: list[Point3]) -> None:
        self._openings.append((name, [tuple(p) for p in points]))  # type: ignore[misc]

    def add_support(self, at: Point3, restraints: tuple[bool, ...], name: str = "") -> None:
        """Restraints UX UY UZ RX RY RZ of a point."""
        self._supports.append((tuple(at), tuple(restraints), name or "point"))  # type: ignore[arg-type]

    # ── loads ──

    def add_area_load(self, area: str, case: Literal["D", "L", "Lr"], pressure: float) -> None:
        """A uniform gravity pressure [kN/m², down] on area ``area`` in case ``case`` (D: the
        superimposed dead load; self-weight comes from the material densities)."""
        self._area_loads[area][case] += pressure

    def not_carried(self, what: str, case: str | None, total: float, example: str) -> None:
        """A load SAEngine does not take over, of ``total`` kN in ``case`` (None: no SAEngine
        case)."""
        self.report.skip(what, example)
        self.report.not_carried[case or "other"] += total

    def not_carried_item(self, key: str, case: str | None, total: float, example: str) -> None:
        """:meth:`not_carried` with the shared wording of item ``key`` (:data:`ITEMS`)."""
        self.report.note(key, example)
        self.report.not_carried[case or "other"] += total

    def lateral_load(self, key: str, case: str, size: float, example: str) -> None:
        """A load of a wind or earthquake case ``case``, of ``size`` kN: SAEngine replaces it
        with its own from the BNBC 2020 settings (item ``key`` of :data:`ITEMS`)."""
        self.report.note(key, example)
        self.report.replaced[case] += abs(size)

    def add_member_load(
        self,
        frame: str,
        case: str | None,
        force: tuple[float, float, float],
        *,
        point: bool = False,
        start: float | None = None,
        length: float | None = None,
        example: str = "",
    ) -> None:
        """A load on frame member ``frame`` in SAEngine case ``case`` (None: the file's case
        has none): ``force`` (x, y, z with Z up, global) in kN/m for a line load, kN for a
        ``point`` load; ``start`` [mm] from the member's start (a line load's loaded part, a
        point load's place; None: the start, a point load the middle) and ``length`` [mm] the
        loaded part of a line load (None: to the member's end). Loads on floor-plan beams go
        to ``05 Floor Plan/loads.json``; the others are reported (see :meth:`build`)."""
        self._member_loads.append(
            _MemberLoad(frame, case, tuple(force), point, start, length, example or frame)  # type: ignore[arg-type]
        )

    def add_joint_load(
        self,
        at: Point3,
        case: str | None,
        force: tuple[float, float, float],
        example: str = "",
    ) -> None:
        """A force (x, y, z with Z up, global) [kN] at point ``at`` [mm] in case ``case``: a
        point load at the top of the column below it (or at a beam's end), see :meth:`build`."""
        self._joint_loads.append(_JointLoad(tuple(at), case, tuple(force), example))  # type: ignore[arg-type]

    def add_combination(self, name: str, factors: dict[str, float]) -> None:
        clean = {k: v for k, v in factors.items() if k in CASES and v}
        if clean:
            self._combinations.append((name, clean))

    # ── building the parts ──

    def build(self) -> ImportedProject:
        report = self.report
        materials = self._build_materials()
        levels = self._levels()
        story_ids: dict[float, str] = {}
        taken: set[str] = set()
        stories = []
        for name, elevation in levels:
            story_id = _id(name, taken)
            story_ids[elevation] = story_id
            stories.append({"id": story_id, "name": name, "elevation": elevation})
        # The lowest level is the base, not a story: a two-story frame has three levels.
        report.count("stories", max(len(stories) - 1, 0))

        def story_at(z: float) -> str | None:
            for elevation, story_id in story_ids.items():
                if abs(elevation - z) <= TOLERANCE:
                    return story_id
            return None

        base_z = levels[0][1] if levels else 0.0
        top_z = levels[-1][1] if levels else 0.0
        grids = self._build_grids()
        report.count("gridLines", len(grids["x"]) + len(grids["y"]))

        def at(x: float, y: float) -> dict[str, Any]:
            gx = min(grids["x"], key=lambda g: abs(g["position"] - x))
            gy = min(grids["y"], key=lambda g: abs(g["position"] - y))
            point: dict[str, Any] = {"x": gx["label"], "y": gy["label"]}
            dx, dy = round(x - gx["position"], 3), round(y - gy["position"], 3)
            if abs(dx) > 1e-6:
                point["dx"] = dx
            if abs(dy) > 1e-6:
                point["dy"] = dy
            return point

        types = _Types(self, materials)
        plan: dict[str, list[dict[str, Any]]] = {
            "columns": [],
            "beams": [],
            "walls": [],
            "slabs": [],
        }
        members: list[InclinedMember] = []
        ids: set[str] = set()
        column_bases: list[tuple[float, float, str]] = []
        #: Where the frames went, for their loads: name -> floor-plan beam (id, story, start,
        #: end) or column (id, x, y, bottom, top) [mm]; frames not on the floor plan: None.
        beam_of: dict[str, tuple[str, str, Point3, Point3]] = {}
        column_of: dict[str, tuple[str, float, float, float, float]] = {}
        placed: dict[str, None] = {}
        self._wall_bases: list[tuple[tuple[float, float], tuple[float, float]]] = []

        for f in self._frames:
            (x1, y1, z1), (x2, y2, z2) = f.start, f.end
            if z2 < z1:
                (x1, y1, z1), (x2, y2, z2) = (x2, y2, z2), (x1, y1, z1)
            plan_length = math.hypot(x2 - x1, y2 - y1)
            if plan_length <= TOLERANCE and abs(z2 - z1) <= TOLERANCE:
                report.skip("frame members of zero length", f.name)
                continue
            vertical = plan_length <= TOLERANCE
            horizontal = abs(z2 - z1) <= TOLERANCE
            kind = f.kind or ("column" if vertical else "beam" if horizontal else "brace")
            section = self._frame_sections.get(f.section)
            if section is None:
                report.skip(
                    "frame members whose section could not be imported", f"{f.name} ({f.section})"
                )
                continue
            simple = False
            if f.pinned:
                steel = self._materials.get(section.material, {}).get("category") == "steel"
                if steel and kind in ("beam", "brace"):
                    simple = True
                    report.approximate(
                        "pinned steel beams and braces as simple connections (default bolting: "
                        "check the connection in 04 Objects)",
                        f.name,
                    )
                else:
                    report.approximate(
                        "end releases of concrete members and columns not expressed (members "
                        "continuous)",
                        f.name,
                    )
            resolved = types.frame(section, kind, simple)
            if resolved is None:
                report.skip("frame members whose material could not be imported", f.name)
                continue
            type_id, extra_rotation = resolved
            member_id = _id(f.name, ids)
            if kind == "column" and vertical and story_at(z1) and story_at(z2):
                plan["columns"].append(
                    {
                        "id": member_id,
                        "type": type_id,
                        "at": at(x1, y1),
                        "base": story_at(z1),
                        "top": story_at(z2),
                        "rotation": round((f.rotation + extra_rotation) % 360, 6),
                    }
                )
                report.count("columns")
                column_of[f.name] = (member_id, x1, y1, z1, z2)
                if abs(z1 - base_z) <= TOLERANCE:
                    column_bases.append((x1, y1, f.name))
                continue
            if kind == "beam" and horizontal and story_at(z1):
                plan["beams"].append(
                    {
                        "id": member_id,
                        "type": type_id,
                        "story": story_at(z1),
                        "start": at(*f.start[:2]),
                        "end": at(*f.end[:2]),
                    }
                )
                report.count("beams")
                beam_of[f.name] = (member_id, story_at(z1), f.start, f.end)  # type: ignore[assignment]
                if abs(f.rotation) > 1e-6:
                    report.approximate("beam rotations about their axis ignored", f.name)
                continue
            if kind == "column":
                report.approximate("raking or off-level columns as inclined members", f.name)
            elif kind == "beam":
                report.approximate("sloped or off-level beams as inclined members", f.name)
            if abs(f.rotation) > 1e-6 and kind != "brace":
                report.approximate("inclined member rotations about their axis ignored", f.name)
            members.append(
                InclinedMember(
                    id=member_id,
                    type=type_id,
                    x1=f.start[0],
                    y1=f.start[1],
                    z1=f.start[2],
                    x2=f.end[0],
                    y2=f.end[1],
                    z2=f.end[2],
                )
            )
            report.count("braces" if kind == "brace" else "inclinedMembers")
            placed[f.name] = None

        panels: list[tuple[_Area, _ShellSection]] = []  # wall panels
        slab_ids: dict[str, str] = {}  # area name -> slab id
        slab_polygons: list[tuple[str, list[tuple[float, float]], float]] = []
        roof_slabs: set[str] = set()
        for a in self._areas:
            section = self._shell_sections.get(a.section)
            zs = [p[2] for p in a.points]
            flat = max(zs) - min(zs) <= TOLERANCE
            kind = a.kind or ("floor" if flat else "wall")
            if section is None:
                report.skip("areas whose section could not be imported", f"{a.name} ({a.section})")
                continue
            if kind == "floor":
                story = story_at(zs[0]) if flat else None
                if story is None:
                    report.skip("sloped or off-level floor areas", a.name)
                    continue
                type_id = types.shell(section, "slab")
                if type_id is None:
                    report.skip("areas whose material could not be imported", a.name)
                    continue
                slab_id = _id(a.name, ids)
                outline = _distinct([(p[0], p[1]) for p in a.points])
                if len(outline) < 3:
                    report.skip("floor areas with fewer than three corners", a.name)
                    continue
                plan["slabs"].append(
                    {
                        "id": slab_id,
                        "type": type_id,
                        "story": story,
                        "boundary": [at(*p) for p in outline],
                    }
                )
                slab_ids[a.name] = slab_id
                slab_polygons.append((slab_id, outline, zs[0]))
                if abs(zs[0] - top_z) <= TOLERANCE:
                    roof_slabs.add(a.name)
                report.count("slabs")
                continue
            panels.append((a, section))

        wall_openings = self._build_walls(
            panels, [z for _, z in levels], story_at, types, at, ids, plan["walls"]
        )
        openings = self._build_openings(slab_polygons, ids)

        supports = self._build_supports(base_z, column_bases)

        settings = self._build_settings(slab_ids, roof_slabs)
        object_library = ObjectLibrary.model_validate({"objects": types.objects})
        report.count("objectTypes", len(types.objects))
        material_library = MaterialLibrary.model_validate({"materials": list(materials.values())})
        report.count("materials", len(materials))

        for slab in plan["slabs"]:
            if slab["id"] in self.slab_loads:
                slab["areaLoad"] = self.slab_loads[slab["id"]]
        floor_plan = FloorPlan.model_validate({"grids": grids, "stories": stories, **plan})
        plan_text = json_text(floor_plan)
        bim = generate(
            floor_plan,
            source_stamp(plan_text),
            BuildingModel(
                additions=Additions(
                    members=members, slabOpenings=openings, wallOpenings=wall_openings
                )
            ),
        )
        bim.supports = supports
        member_loads = self._build_member_loads(
            beam_of, column_of, placed, story_at, base_z, floor_plan
        )
        lost = {k: v for k, v in report.not_carried.items() if abs(v) >= 0.0005}
        if lost:
            totals = ", ".join(f"{k} {v:.3g} kN" for k, v in sorted(lost.items()))
            report.warn(
                f"Loads of the file not carried over ({totals}; listed under skipped): add them "
                "in SAEngine before using the results."
            )
        replaced = {k: v for k, v in report.replaced.items() if abs(v) >= 0.0005}
        if not self.self_weight:
            report.warn(
                "No load pattern of the file includes the self-weight; SAEngine adds it from the "
                "material densities."
            )
        if replaced:
            totals = ", ".join(f"{k} {v:.3g} kN" for k, v in sorted(replaced.items()))
            report.warn(
                f"Wind and earthquake loads of the file ({totals}) are replaced by SAEngine's own "
                "from the BNBC settings (listed under replaced, not lost): check the site, "
                "occupancy and structural system in 02 Project Settings."
            )
        else:
            report.warn(
                "Wind and earthquake loads are SAEngine's own from the BNBC settings: check the "
                "site, occupancy and structural system in 02 Project Settings."
            )
        texts = {
            PATHS["settings"]: json_text(settings),
            PATHS["materials"]: json_text(material_library),
            PATHS["objects"]: json_text(object_library),
            PATHS["floorPlan"]: plan_text,
            PATHS["bim"]: json_text(bim),
        }
        if member_loads is not None:
            texts[PATHS["memberLoads"]] = json_text(member_loads)
        texts[PATHS["report"]] = json_text(report.to_dict())
        return ImportedProject(
            self.name,
            settings,
            material_library,
            object_library,
            floor_plan,
            bim,
            report,
            texts,
            member_loads,
        )

    def _build_materials(self) -> dict[str, dict[str, Any]]:
        taken: set[str] = set()
        result = {}
        for name, data in self._materials.items():
            material_id = _id(name, taken)
            self._material_ids[name] = material_id
            result[material_id] = {"id": material_id, **data}
        return result

    def material_id(self, name: str) -> str | None:
        return self._material_ids.get(name)

    def _build_member_loads(
        self,
        beam_of: dict[str, tuple[str, str, Point3, Point3]],
        column_of: dict[str, tuple[str, float, float, float, float]],
        placed: dict[str, None],
        story_at: Callable[[float], str | None],
        base_z: float,
        plan: FloorPlan,
    ) -> ll.MemberLoads | None:
        """The file's member and joint loads as SAEngine's member loads (``05 Floor Plan/
        loads.json``, :mod:`saengine.library.line_loads`); None when none could be placed.

        Loads of gravity cases go onto the floor-plan beams: a line load along a whole beam stays
        a line load, one on part of a beam becomes a point load of its total at the middle of the
        loaded part, a point load stays at its place. A joint load becomes a point load at the
        top of the column below the point, else on the beam through it. Only the vertical part
        is kept; the file's dead (and fluid) loads go to SAEngine's superimposed dead case SD,
        as SAEngine adds the self-weight itself. Each load applies to its own story only. Loads
        of wind and earthquake cases are replaced by SAEngine's own (BNBC 2020); loads on other
        members, at supports or of cases SAEngine has no case for are reported as not carried.
        """
        report = self.report
        if not self._member_loads and not self._joint_loads:
            return None
        frames = {f.name: f for f in self._frames}
        loads: list[ll.LineLoad | ll.PointLoad] = []
        lateral = ("WX", "WY", "EX", "EY")

        def gravity(
            kind: str, case: str | None, force: Point3, amount: float, example: str
        ) -> tuple[str, float] | None:
            """(member-load case, down part [kN/m or kN]) of a load; None when it is not
            carried (reported). ``amount``: what turns the force into a total [kN]."""
            fx, fy, fz = force
            size = math.sqrt(fx * fx + fy * fy + fz * fz)
            if case in lateral:
                self.lateral_load(f"loads.lateral.{kind}", case, size * amount, example)
                return None
            down = -fz
            if case not in ("D", "L", "Lr", "F"):
                total = down if abs(down) > 1e-12 else size
                self.not_carried_item(f"loads.noCase.{kind}", case, total * amount, example)
                return None
            if abs(down) <= 1e-12:
                self.not_carried_item(f"loads.{kind}.direction", case, size * amount, example)
                return None
            if math.hypot(fx, fy) > 1e-6 * abs(down):
                report.note("loads.horizontal", example)
            if case == "F":
                report.note("loads.fluid", example)
            return ("SD" if case in ("D", "F") else case), down

        def add(load: ll.LineLoad | ll.PointLoad, total: float) -> None:
            loads.append(load)
            report.count("memberLineLoads" if isinstance(load, ll.LineLoad) else "memberPointLoads")
            report.carried["D" if load.case == "SD" else load.case] += total

        for m in self._member_loads:
            frame = frames.get(m.frame)
            length = math.dist(frame.start, frame.end) if frame else 0.0
            start = max(m.start or 0.0, 0.0)
            loaded = 0.0 if m.point else (m.length if m.length is not None else length - start)
            amount = 1.0 if m.point else loaded / 1000
            mapped = gravity("member", m.case, m.force, amount, m.example)
            if mapped is None:
                continue
            case, down = mapped
            if m.frame not in beam_of:
                key = (
                    "loads.member.notOnBeam"
                    if m.frame in column_of or m.frame in placed
                    else "loads.member.notImported"
                )
                self.not_carried_item(key, m.case, down * amount, m.example)
                continue
            beam, story, a, b = beam_of[m.frame]
            span = math.dist(a[:2], b[:2])
            common: dict[str, Any] = {"id": f"imported-{len(loads) + 1}", "story": story}
            common.update(member=beam, case=case, thisStoryOnly=True, note=f"Imported: {m.example}")
            if m.point:
                at = m.start if m.start is not None else span / 2
                at = round(min(max(at, 0.0), span), 3)
                add(ll.PointLoad(**common, value=round(down, 6), distance=at), down)
                continue
            start = min(start, span)
            loaded = min(max(loaded, 0.0), span - start)
            if start <= TOLERANCE and loaded >= span - start - TOLERANCE:
                add(ll.LineLoad(**common, value=round(down, 6)), down * span / 1000)
                continue
            report.note("loads.member.partial", m.example)
            total = down * loaded / 1000
            middle = round(start + loaded / 2, 3)
            add(ll.PointLoad(**common, value=round(total, 6), distance=middle), total)

        for j in self._joint_loads:
            mapped = gravity("joint", j.case, j.force, 1.0, j.example)
            if mapped is None:
                continue
            case, down = mapped
            x, y, z = j.at
            story = story_at(z)
            common = {"id": f"imported-{len(loads) + 1}", "case": case, "thisStoryOnly": True}
            common["note"] = f"Imported: {j.example}"
            column = next(
                (
                    c
                    for c, cx, cy, bottom, top in column_of.values()
                    if math.hypot(cx - x, cy - y) <= TOLERANCE
                    and bottom + TOLERANCE < z <= top + TOLERANCE
                ),
                None,
            )
            if column is not None and story is not None:
                add(ll.PointLoad(**common, story=story, member=column, value=round(down, 6)), down)
                continue
            beam = next(
                (
                    (bid, bstory, a, b)
                    for bid, bstory, a, b in beam_of.values()
                    if abs(a[2] - z) <= TOLERANCE
                    and _segment_distance((x, y), a[:2], b[:2]) <= TOLERANCE
                ),
                None,
            )
            if beam is not None:
                bid, bstory, a, b = beam
                at = round(min(math.dist(a[:2], (x, y)), math.dist(a[:2], b[:2])), 3)
                report.note("loads.joint.onBeam", j.example)
                load = ll.PointLoad(
                    **common, story=bstory, member=bid, value=round(down, 6), distance=at
                )
                add(load, down)
                continue
            key = "loads.joint.support" if abs(z - base_z) <= TOLERANCE else "loads.joint.noMember"
            self.not_carried_item(key, j.case, down, j.example)

        if not loads:
            return None
        # The code pack's wall types, as a new loads file has them (none without the table).
        result = ll.MemberLoads(wallTypes=ll.default_wall_types(), loads=loads)
        for problem in ll.check(result, plan):
            report.warn(f"Imported member loads: {problem}")
        return result

    def _levels(self) -> list[tuple[str, float]]:
        """Stories (name, elevation) bottom up: the file's, or the levels of the horizontal
        members and slabs and the bottoms of the columns."""
        levels: list[tuple[str, float]] = []
        for name, elevation in sorted(self._stories, key=lambda s: s[1]):
            if levels and abs(levels[-1][1] - elevation) <= TOLERANCE:
                self.report.approximate("stories at the same level merged", name)
                continue
            levels.append((name, elevation))
        if levels:
            return levels
        zs: list[float] = []
        for f in self._frames:
            if abs(f.start[2] - f.end[2]) <= TOLERANCE:
                zs.append(f.start[2])
            elif math.dist(f.start[:2], f.end[:2]) <= TOLERANCE:
                zs.extend((f.start[2], f.end[2]))
        for a in self._areas:
            if max(p[2] for p in a.points) - min(p[2] for p in a.points) <= TOLERANCE:
                zs.append(a.points[0][2])
        values: list[float] = []
        for z in sorted(zs):
            if not values or z - values[-1] > TOLERANCE:
                values.append(round(z, 3))
        if values:
            self.report.approximate("stories found from the levels of the beams and floors")
        return [("Base" if k == 0 else f"Level {k}", z) for k, z in enumerate(values)]

    def _build_grids(self) -> dict[str, list[dict[str, Any]]]:
        """The file's cartesian grid lines; without them, lines through the column positions
        (or all points)."""
        taken: set[str] = set()
        grids: dict[str, list[dict[str, Any]]] = {"x": [], "y": []}
        for axis in ("x", "y"):
            for label, position in sorted(self._grids[axis], key=lambda g: g[1]):
                if any(abs(g["position"] - position) <= TOLERANCE for g in grids[axis]):
                    self.report.approximate("grid lines at the same position merged", label)
                    continue
                fallback = _letters(len(grids[axis])) if axis == "x" else str(len(grids[axis]) + 1)
                grids[axis].append(
                    {"label": _grid_label(label, taken, fallback), "position": position}
                )
        if grids["x"] and grids["y"]:
            return grids
        points = [f.start for f in self._frames if math.dist(f.start[:2], f.end[:2]) <= TOLERANCE]
        if not points:
            points = [p for f in self._frames for p in (f.start, f.end)] + [
                p for a in self._areas for p in a.points
            ]
        if not points:
            points = [(0.0, 0.0, 0.0)]
        for axis, index in (("x", 0), ("y", 1)):
            if grids[axis]:
                continue
            values: list[float] = []
            for v in sorted(p[index] for p in points):
                if not values or v - values[-1] > TOLERANCE:
                    values.append(round(v, 3))
            for k, v in enumerate(values):
                label = _letters(k) if axis == "x" else str(k + 1)
                grids[axis].append({"label": _grid_label(label, taken, label), "position": v})
        if not self._grids["x"] or not self._grids["y"]:
            self.report.approximate("grid lines made from the column positions")
        return grids

    def _build_walls(
        self,
        panels: list[tuple[_Area, _ShellSection]],
        levels: list[float],
        story_at: Callable[[float], str | None],
        types: _Types,
        at: Callable[[float, float], dict[str, Any]],
        ids: set[str],
        walls: list[dict[str, Any]],
    ) -> list[WallOpening]:
        """The wall panels as floor-plan walls (appended to ``walls``) and their openings.

        A panel that is a rectangle between two stories is a wall. Panels that are not (ETABS
        mesh pieces, the panels round a door or window, a panel outlining one) are merged with
        the panels in line with them, story by story: each piece of the merged outline between
        two stories becomes one wall, and its gaps wall openings (doors where they reach the
        floor). Panels that make no such wall (partial height, gaps at a wall's top or ends,
        outside the stories) are reported one by one.
        """
        from shapely.geometry import Polygon, box
        from shapely.ops import unary_union

        report = self.report
        result: list[WallOpening] = []

        def add_wall(
            name: str,
            section: _ShellSection,
            start: tuple[float, float],
            end: tuple[float, float],
            z0: float,
            z1: float,
        ) -> str | None:
            type_id = types.shell(section, "wall")
            if type_id is None:
                report.skip("areas whose material could not be imported", name)
                return None
            wall_id = _id(name, ids)
            walls.append(
                {
                    "id": wall_id,
                    "type": type_id,
                    "base": story_at(z0),
                    "top": story_at(z1),
                    "start": at(*start),
                    "end": at(*end),
                }
            )
            report.count("walls")
            if abs(z0 - levels[0]) <= TOLERANCE:
                self._wall_bases.append((start, end))
            return wall_id

        # Panels by the vertical plane they lie in: (angle, offset, origin, direction, panels).
        lines: list[tuple[float, float, tuple[float, float], tuple[float, float], list[Any]]] = []
        for a, section in panels:
            plan = _distinct([(p[0], p[1]) for p in a.points])
            pair = max(
                ((p, q) for p in plan for q in plan), key=lambda pq: math.dist(*pq), default=None
            )
            if pair is None or math.dist(*pair) <= TOLERANCE:
                report.skip("areas that are neither flat floors nor vertical walls", a.name)
                continue
            (x0, y0), (x1, y1) = pair
            length = math.dist(*pair)
            dx, dy = (x1 - x0) / length, (y1 - y0) / length
            if dx < -1e-9 or (abs(dx) <= 1e-9 and dy < 0):
                dx, dy = -dx, -dy
            if any(abs((x - x0) * dy - (y - y0) * dx) > TOLERANCE for x, y in plan):
                report.skip("areas that are neither flat floors nor vertical walls", a.name)
                continue
            angle, offset = math.atan2(dy, dx), dx * y0 - dy * x0
            line = next(
                (g for g in lines if abs(g[0] - angle) < 1e-4 and abs(g[1] - offset) <= TOLERANCE),
                None,
            )
            if line is None:
                line = (angle, offset, (x0, y0), (dx, dy), [])
                lines.append(line)
            rectangle = _wall(a.points)
            whole = (
                rectangle is not None
                and story_at(rectangle[2]) is not None
                and story_at(rectangle[3]) is not None
            )
            line[4].append((a, section, rectangle if whole else None))

        for _, _, (ox, oy), (dx, dy), members in lines:
            if all(rectangle is not None for _, _, rectangle in members):
                for a, section, rectangle in members:
                    start, end, z0, z1 = rectangle
                    add_wall(a.name, section, start, end, z0, z1)
                continue
            shapes = []
            for a, section, _ in members:
                outline = [((x - ox) * dx + (y - oy) * dy, z) for x, y, z in a.points]
                shapes.append((a, section, Polygon(outline).buffer(0)))
            union = (
                unary_union([shape for _, _, shape in shapes])
                .buffer(0.5, join_style=2)
                .buffer(-0.5, join_style=2)
            )
            done: set[str] = set()
            left, _, right, _ = union.bounds
            for z0, z1 in itertools.pairwise(levels):
                piece = union.intersection(box(left - 1, z0, right + 1, z1))
                for part in getattr(piece, "geoms", [piece]):
                    if part.is_empty or part.geom_type != "Polygon" or part.area < 1.0:
                        continue
                    inside = [m for m in shapes if m[2].intersection(part).area > 1.0]
                    names = [a.name for a, _, _ in inside]
                    done.update(names)
                    u0, b0, u1, b1 = part.bounds
                    gaps = box(u0, b0, u1, b1).difference(part)
                    holes = [g for g in getattr(gaps, "geoms", [gaps]) if g.area > 1.0]
                    fits = abs(b0 - z0) <= TOLERANCE and abs(b1 - z1) <= TOLERANCE
                    for g in holes:
                        g0, h0, g1, h1 = g.bounds
                        fits = fits and (
                            g.area >= (g1 - g0) * (h1 - h0) * 0.999
                            and h1 < b1 - TOLERANCE
                            and g0 > u0 + TOLERANCE
                            and g1 < u1 - TOLERANCE
                        )
                    if not fits:
                        for name in names:
                            report.skip(
                                "wall panels that make no wall between two stories (partial "
                                "height, or gaps at a wall's top or ends)",
                                name,
                            )
                        continue
                    main = max(inside, key=lambda m: m[2].intersection(part).area)
                    if len({section.name for _, section, _ in inside}) > 1:
                        report.approximate(
                            "merged wall panels of different sections as the largest one's",
                            main[0].name,
                        )
                    wall_id = add_wall(
                        main[0].name,
                        main[1],
                        (ox + u0 * dx, oy + u0 * dy),
                        (ox + u1 * dx, oy + u1 * dy),
                        z0,
                        z1,
                    )
                    if wall_id is None:
                        continue
                    if len(inside) > 1:
                        more = "..." if len(names) > 4 else ""
                        report.approximate(
                            "wall panels in line merged into one wall per story (mesh pieces, "
                            "panels round openings)",
                            f"{wall_id}: {', '.join(names[:4])}{more}",
                        )
                    for k, g in enumerate(sorted(holes, key=lambda g: g.bounds[0]), 1):
                        g0, h0, g1, h1 = g.bounds
                        result.append(
                            WallOpening(
                                id=_id(f"{wall_id}-O{k}", ids),
                                host=wall_id,
                                offset=round(g0 - u0, 3),
                                sill=round(max(h0 - b0, 0.0), 3),
                                width=round(g1 - g0, 3),
                                height=round(h1 - h0, 3),
                            )
                        )
                        report.count("wallOpenings")
            for a, _, _ in shapes:
                if a.name not in done:
                    report.skip("wall panels outside the stories", a.name)
        return result

    def _build_supports(
        self, base_z: float, column_bases: list[tuple[float, float, str]]
    ) -> list[BimSupport]:
        """The file's supports as building-model supports where they differ from SAEngine's own.

        SAEngine fixes the bases of the columns and walls at the lowest story itself. A fixed
        support there needs nothing more; a pinned one (translations only) becomes a pinned
        building-model support, which frees the column base's rotations. Supports elsewhere
        (a brace's foot, a support above the base) become building-model supports. Column bases
        the file leaves free stay fixed (reported), and a file without supports is an error.
        """
        report = self.report
        result: list[BimSupport] = []
        taken: set[str] = set()
        supported: set[tuple[float, float]] = set()

        def on_wall(x: float, y: float) -> bool:
            return any(_segment_distance((x, y), a, b) <= TOLERANCE for a, b in self._wall_bases)

        for (x, y, z), restraints, name in self._supports:
            translations, rotations = restraints[:3], restraints[3:6]
            if all(translations):
                fixity: Literal["fixed", "pinned"] = "fixed" if any(rotations) else "pinned"
                if any(rotations) and not all(rotations):
                    report.approximate("supports with some rotations restrained as fixed", name)
            else:
                fixity = "pinned"
                report.approximate(
                    "supports free in a translation (rollers, guides) as pinned", name
                )
            report.count("supports")
            at_base = abs(z - base_z) <= TOLERANCE
            if at_base:
                supported.add((round(x), round(y)))
            if at_base and on_wall(x, y):
                if fixity == "pinned":
                    report.approximate("pinned supports under walls analysed as fixed", name)
                continue
            column = at_base and any(
                math.dist((x, y), (cx, cy)) <= TOLERANCE for cx, cy, _ in column_bases
            )
            if column and fixity == "fixed":
                continue
            if not at_base:
                report.approximate(
                    "supports above the base as building-model supports (check they sit on a "
                    "member end)",
                    name,
                )
            result.append(BimSupport(id=_id(f"S-{name}", taken), at=[x, y, z], fixity=fixity))
        if self._supports:
            for x, y, name in column_bases:
                if (round(x), round(y)) not in supported and not any(
                    math.dist((x, y), s) <= TOLERANCE for s in supported
                ):
                    report.approximate(
                        "column bases the file leaves free, fixed by SAEngine (it fixes the "
                        "columns and walls of the lowest story)",
                        name,
                    )
        else:
            springs = (
                f" ({self.springs} point springs could not be imported)" if self.springs else ""
            )
            report.error(
                f"The file has no supports SAEngine can use{springs}: SAEngine fixes the bases "
                "of the columns and walls of the lowest story. Check the supports before using "
                "the results."
            )
        return result

    def _build_openings(
        self, slabs: list[tuple[str, list[tuple[float, float]], float]], ids: set[str]
    ) -> list[SlabOpening]:
        from shapely.geometry import Point, Polygon

        result = []
        for name, points in self._openings:
            xs, ys, zs = zip(*points, strict=True)
            plan = _distinct([(p[0], p[1]) for p in points])
            box = (max(xs) - min(xs)) * (max(ys) - min(ys))
            rectangle = len(plan) == 4 and math.isclose(abs(Polygon(plan).area), box, rel_tol=1e-3)
            if max(zs) - min(zs) > TOLERANCE or not rectangle or box <= 0:
                self.report.skip("openings that are not plan rectangles", name)
                continue
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            host = next(
                (
                    slab_id
                    for slab_id, outline, z in slabs
                    if abs(z - zs[0]) <= TOLERANCE and Polygon(outline).contains(Point(cx, cy))
                ),
                None,
            )
            if host is None:
                self.report.skip("openings in no imported slab", name)
                continue
            result.append(
                SlabOpening(
                    id=_id(name, ids),
                    host=host,
                    x=cx,
                    y=cy,
                    xDim=max(xs) - min(xs),
                    yDim=max(ys) - min(ys),
                )
            )
            self.report.count("slabOpenings")
        return result

    def _build_settings(self, slab_ids: dict[str, str], roof_slabs: set[str]) -> ProjectSettings:
        report = self.report
        settings = default_project_settings(self.name)
        if self.analysis:
            settings.analysis = type(settings.analysis).model_validate(
                {**settings.analysis.model_dump(), **self.analysis}
            )
        loads_by_slab = {name: self._area_loads.get(name, {}) for name in slab_ids}
        # Which of the file's live cases end up in SAEngine's roof (Lr) and floor (L) loads:
        # a Live-pattern load on the roof is applied in SAEngine's Lr case, so the combinations
        # must give Lr the factor the file gave L (and the other way round below the roof).
        roof_cases = {
            c for n, v in loads_by_slab.items() if n in roof_slabs for c in ("L", "Lr") if v.get(c)
        }
        floor_cases = {
            c
            for n, v in loads_by_slab.items()
            if n not in roof_slabs
            for c in ("L", "Lr")
            if v.get(c)
        }
        for name, loads in self._area_loads.items():
            if name not in slab_ids:
                area = self._area_m2.get(name, 0.0)
                for case, value in loads.items():
                    self.not_carried(
                        "area loads on walls or skipped areas", case, value * area, name
                    )
        if any(loads_by_slab.values()):
            floors = {n: v for n, v in loads_by_slab.items() if n not in roof_slabs}
            roofs = {n: v for n, v in loads_by_slab.items() if n in roof_slabs}
            area_loads = {a.id: a for a in settings.areaLoads}
            for load_id, group, roof in (("FL", floors, False), ("RF", roofs, True)):
                if not group:
                    continue
                if roof and any(v.get("L") for v in group.values()):
                    report.approximate(
                        "live load on the roof taken as roof live load Lr (SAEngine's roof case)"
                    )
                if not roof and any(v.get("Lr") for v in group.values()):
                    report.approximate("roof live load below the roof taken as live load L")
                # Slabs with the same loads share an area load; the group with the most area
                # is the floor (roof) load of the settings, the others are the slabs' own.
                groups: dict[tuple[float, float], list[str]] = defaultdict(list)
                for name, v in group.items():
                    key = (round(v.get("D", 0.0), 4), round(v.get("L", 0.0) + v.get("Lr", 0.0), 4))
                    groups[key].append(name)
                ranked = sorted(
                    groups.items(),
                    key=lambda g: -sum(self._area_m2.get(n, 0.0) for n in g[1]),
                )
                for k, ((finish, live), names) in enumerate(ranked):
                    own = f"{load_id}-{k + 1}" if k else load_id
                    label = "Roof" if roof else "Floors"
                    area_loads[own] = AreaLoad(
                        id=own,
                        name=f"{label} (imported)"
                        if not k
                        else f"{label} (imported) {k + 1}: SD {finish:g}, live {live:g} kN/m²",
                        use="custom",
                        live=live,
                        finish=finish,
                        partitions=0.0,
                    )
                    report.count("areaLoads")
                    for name in names:
                        if k:
                            self.slab_loads[slab_ids[name]] = own
                        area = self._area_m2.get(name, 0.0)
                        report.carried["D"] += finish * area
                        report.carried["Lr" if roof else "L"] += live * area
                if len(ranked) > 1:
                    report.approximate(
                        f"{'roof' if roof else 'floor'} slabs with loads of their own (an area "
                        "load per group of slabs with the same loads, 02 Project Settings)",
                        ", ".join(f"SD {f:g} / L {v:g} kN/m²: {len(n)}" for (f, v), n in ranked),
                    )
            settings.areaLoads = list(area_loads.values())
        else:
            report.warn(
                "The file has no area loads on its floors: SAEngine's default floor and roof "
                "loads apply (02 Project Settings)."
            )
        # The area loads the file did not give (the stairs', and the floors' or roof's when it
        # has none there) are SAEngine's defaults: named so, and listed.
        for area_load in settings.areaLoads:
            if not area_load.name.endswith("(imported)") and "(imported) " not in area_load.name:
                report.note("settings.defaultAreaLoads", area_load.name)
                area_load.name = f"{area_load.name} (SAEngine default)"
        # SAEngine's F (fluid, the contents of 07 MEP equipment) follows D by default (factor
        # D where D > 1); a file without fluid loads gives F no factor.
        fluid = any(factors.get("F") for _, factors in self._combinations)
        combinations: list[LoadCombination] = []
        seen: set[tuple[tuple[str, float], ...]] = set()
        names: set[str] = set()
        for name, factors in self._combinations:
            factors = self._live_factors(name, factors, roof_cases, floor_cases)
            key = tuple(sorted((k, round(v, 6)) for k, v in factors.items()))
            if key in seen:
                report.approximate(
                    "combinations with the same factors as another one dropped", name
                )
                continue
            seen.add(key)
            if "F" not in factors:
                if not fluid and factors.get("D", 0.0) > 1.0:
                    report.note("combinations.noFluid", name)
                factors = {**factors, "F": 0.0}
            label, k = name, 2
            while label in names:
                label, k = f"{name} ({k})", k + 1
            names.add(label)
            combinations.append(LoadCombination(name=label, **factors))
        if combinations:
            settings.combinations = combinations
            report.count("combinations", len(combinations))
        else:
            report.warn(
                "The file has no load combinations SAEngine can use: the BNBC 2020 ones apply."
            )
        return settings

    def _live_factors(
        self,
        name: str,
        factors: dict[str, float],
        roof_cases: set[str],
        floor_cases: set[str],
    ) -> dict[str, float]:
        """The combination factors with L / Lr following where the file's live loads went.

        SAEngine applies the roof's live load (RF) in its Lr case and the floors' (FL) in L.
        When the roof's live load came only from the file's Live pattern, Lr takes the factor
        the file gave L in this combination; when the floors' came only from Roof Live, L takes
        the factor of Lr. Where a roof or a floor holds both, the factor of the case SAEngine
        uses is kept (or the other one's when it has none) and the change is reported.
        """
        result = dict(factors)
        what = "combination factors moved with the live loads"

        def take(target: str, source: str, cases: set[str]) -> None:
            if source not in cases:
                return
            old, new = factors.get(target, 0.0), factors.get(source, 0.0)
            if target in cases and old:
                if abs(old - new) > 1e-9:
                    report_what = (
                        f"{what}: the {'roof' if target == 'Lr' else 'floor'} holds both live "
                        f"cases, the {target} factor applies to both"
                    )
                    self.report.approximate(report_what, f"{name}: {target} {old:g}")
                return
            if abs(old - new) > 1e-9:
                self.report.approximate(
                    f"{what}: {source} loads on the {'roof' if target == 'Lr' else 'floors'} "
                    f"applied in SAEngine's {target}, which takes the {source} factor",
                    f"{name}: {target} {old:g} → {new:g}",
                )
            if new:
                result[target] = new
            else:
                result.pop(target, None)

        take("Lr", "L", roof_cases)
        take("L", "Lr", floor_cases)
        return result


class _Types:
    """Object types made from the sections, one per section and kind it is used as."""

    def __init__(self, builder: ProjectBuilder, materials: dict[str, dict[str, Any]]) -> None:
        self.builder = builder
        self.materials = materials
        self.objects: list[dict[str, Any]] = []
        self._ids: dict[tuple[str, str], str] = {}
        self._taken: set[str] = set()
        self._kinds: dict[str, set[str]] = defaultdict(set)

    def _material(self, name: str) -> str | None:
        return self.builder.material_id(name)

    def _new_id(self, section: str, kind: str) -> str:
        suffix = {"column": "C", "beam": "B", "brace": "BR", "slab": "S", "wall": "W"}[kind]
        self._kinds[section].add(kind)
        if section not in {s for s, _ in self._ids}:
            return _id(section, self._taken)
        return _id(f"{section}-{suffix}", self._taken)

    def frame(
        self, section: _FrameSection, kind: FrameKind, simple: bool = False
    ) -> tuple[str, float] | None:
        """(object type id, extra rotation [°] for columns whose profile is turned). ``simple``:
        a steel beam or brace type with a simple connection (pinned ends), default bolting."""
        material = self._material(section.material)
        if material is None:
            return None
        profile = dict(section.profile)
        extra = 0.0
        if kind == "column":
            # The source's depth (local 2) lies along global X at a column angle of 0, and the
            # profile's x along global X at a rotation of 0: rectangles swap their sides, other
            # shapes turn by 90°.
            if profile["shape"] in ("rectangle", "rectangleHollow"):
                profile["xDim"], profile["yDim"] = profile["yDim"], profile["xDim"]
            elif profile["shape"] in ("I", "T", "L", "U"):
                extra = 90.0
        key = (section.name, f"{kind}-pinned" if simple else kind)
        if key not in self._ids:
            type_id = (
                _id(f"{section.name}-pinned", self._taken)
                if simple
                else self._new_id(section.name, kind)
            )
            data: dict[str, Any] = {
                "id": type_id,
                "name": f"{section.name} {kind}{' (pinned ends)' if simple else ''}",
                "kind": kind,
                "material": material,
                "profile": profile,
            }
            if simple:
                data["connection"] = {"type": "finPlate" if kind == "beam" else "gusset"}
            bars = section.column_reinforcement if kind == "column" else section.beam_reinforcement
            if bars and kind != "brace":
                rebar = self._material(bars["material"])
                if rebar is not None and self.materials[rebar]["category"] == "rebar":
                    data["reinforcement"] = {**bars, "material": rebar}
                else:
                    self.builder.report.approximate(
                        "reinforcement without a rebar material left to SAEngine's design",
                        section.name,
                    )
            self.objects.append(data)
            self._ids[key] = type_id
        return self._ids[key], extra

    def shell(self, section: _ShellSection, kind: Literal["slab", "wall"]) -> str | None:
        material = self._material(section.material)
        if material is None:
            return None
        key = (section.name, kind)
        if key not in self._ids:
            type_id = self._new_id(section.name, kind)
            self.objects.append(
                {
                    "id": type_id,
                    "name": f"{section.name} {kind}",
                    "kind": kind,
                    "material": material,
                    "thickness": section.thickness,
                }
            )
            self._ids[key] = type_id
        return self._ids[key]


def _distinct(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """``points`` without consecutive repeats (and the closing repeat)."""
    result: list[tuple[float, float]] = []
    for p in points:
        if not result or math.dist(result[-1], p) > TOLERANCE:
            result.append(p)
    if len(result) > 1 and math.dist(result[0], result[-1]) <= TOLERANCE:
        result.pop()
    return result


def _wall(
    points: list[Point3],
) -> tuple[tuple[float, float], tuple[float, float], float, float] | None:
    """(start, end, bottom, top) of a vertical rectangular wall panel, or None."""
    zs = [p[2] for p in points]
    bottom, top = min(zs), max(zs)
    if top - bottom <= TOLERANCE:
        return None
    if any(min(abs(z - bottom), abs(z - top)) > TOLERANCE for z in zs):
        return None
    lower = _distinct([(p[0], p[1]) for p in points if abs(p[2] - bottom) <= TOLERANCE])
    upper = _distinct([(p[0], p[1]) for p in points if abs(p[2] - top) <= TOLERANCE])
    if len(lower) != 2 or len(upper) != 2:
        return None
    if not all(any(math.dist(a, b) <= TOLERANCE for b in upper) for a in lower):
        return None
    return lower[0], lower[1], bottom, top


def _segment_distance(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Distance [mm] from ``p`` to the segment ``a``-``b`` in plan."""
    ax, ay = b[0] - a[0], b[1] - a[1]
    length2 = ax * ax + ay * ay
    t = 0.0 if not length2 else ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / length2
    t = min(1.0, max(0.0, t))
    return math.dist(p, (a[0] + t * ax, a[1] + t * ay))


def polygon_area(points: list[Point3]) -> float:
    """Area [m²] of a flat polygon in space given in mm (Newell's method)."""
    nx = ny = nz = 0.0
    for (x0, y0, z0), (x1, y1, z1) in zip(points, points[1:] + points[:1], strict=True):
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return math.sqrt(nx * nx + ny * ny + nz * nz) / 2 * 1e-6

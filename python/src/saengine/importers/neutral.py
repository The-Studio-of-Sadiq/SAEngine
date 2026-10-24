"""The frame model the STAAD.Pro (``.std``) and SAP2000 (``.s2k``) readers fill, and how it goes
to the shared :class:`~saengine.importers.common.ProjectBuilder`.

Both programs number joints and refer to them from members, areas, supports and loads; a reader
collects them in a :class:`TextModel` in SAEngine's units and axes (mm, N, MPa, kg/m³, Z up), with
the load cases and combinations of the file. :func:`build` resolves the joints into geometry and
hands it to the builder, which writes the project (see :mod:`saengine.importers.common`):

- load cases map onto SAEngine's cases by their type: dead and superimposed dead onto D, live
  onto L, roof live onto Lr, wind onto WX or WY and earthquake onto EX or EY (the axis and sign
  from the case's loads, else its name in the file's horizontal axes);
- pressures on floor areas become the floor and roof area loads (STAAD floor loads and SAP
  'uniform to frame' loads too, where the level or area has a slab); joint loads, member loads,
  floor loads on levels without slabs (their total over the plan area of the beams there),
  loads on null areas and loads of lateral cases are not carried over and their totals go into
  the report, case by case;
- combinations become SAEngine combinations on those cases.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.importers.common import (
    CASES,
    ImportedProject,
    ImportReport,
    ProjectBuilder,
    polygon_area,
)
from saengine.library import objects as o

G = 9.80665  # m/s²


@dataclass(frozen=True)
class FileUnits:
    """A file's length and force units as factors to mm and N (units can change mid-file in
    STAAD, so readers keep numbers rather than :class:`~saengine.importers.common.Units`)."""

    length: float = 1000.0
    force: float = 1000.0

    def mpa(self, value: float) -> float:
        """A stress or modulus (force/length²) in MPa."""
        return value * self.force / self.length**2

    def n_per_m(self, value: float) -> float:
        """A line load (force/length) in N/m."""
        return value * self.force / (self.length / 1000)

    def n_per_m2(self, value: float) -> float:
        """A pressure (force/length²) in N/m²."""
        return value * self.force / (self.length / 1000) ** 2

    def density(self, unit_weight: float) -> float:
        """A unit weight (force/length³) as a mass density in kg/m³."""
        return unit_weight * self.force / (self.length / 1000) ** 3 / G


# ─────────────────────────────────────── the model ───────────────────────────────────────


@dataclass
class Frame:
    id: str
    i: str
    j: str
    section: str | None = None
    material: str | None = None
    rotation: float = 0.0


@dataclass
class Area:
    id: str
    joints: list[str]
    section: str | None = None
    material: str | None = None


@dataclass
class SectionDef:
    """A frame section (``profile``, as in a beam: yDim/overallDepth the depth) or an area
    section (``thickness``), in mm."""

    name: str
    profile: Any = None
    thickness: float | None = None
    material: str | None = None
    #: Why the profile is not the file's exact section, when it is not.
    approximation: str | None = None


@dataclass
class MaterialDef:
    """E and strengths in MPa, density in kg/m³; ``kind`` concrete or steel (None: by E)."""

    name: str
    E: float | None = None
    nu: float | None = None
    density: float | None = None
    kind: str | None = None
    fy: float | None = None
    fu: float | None = None
    fc: float | None = None


@dataclass
class Load:
    """A load of a case in SAEngine axes: ``kind`` joint (``value`` a force [N] at joint
    ``target``), uniform (on frame ``target`` [N/m], over ``length`` mm or the whole member),
    point (on frame ``target`` [N]), pressure (on area ``target`` [N/m²]), to-frame (a pressure
    [N/m²] on area ``target`` that the program spreads to the frames around it, as on null-area
    slabs) or floor (a pressure [N/m²] on the level within ``zrange`` mm and the plan ranges
    ``xrange`` and ``yrange`` mm, which the program spreads to the beams around each panel)."""

    kind: str
    target: str
    value: np.ndarray
    zrange: tuple[float, float] | None = None
    length: float | None = None
    xrange: tuple[float, float] | None = None
    yrange: tuple[float, float] | None = None


@dataclass
class LoadCase:
    """``kind``: D, SD, L, Lr, W, E or other; ``selfweight``: the factor on the self-weight acting
    downwards (0: none)."""

    name: str
    kind: str = "other"
    selfweight: float = 0.0
    loads: list[Load] = field(default_factory=list)
    #: X or Y for wind and earthquake cases, when the file says so.
    direction: str | None = None


@dataclass
class TextModel:
    format: str
    file: str
    units: str = ""
    joints: dict[str, np.ndarray] = field(default_factory=dict)  # mm, Z up
    frames: list[Frame] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    sections: dict[str, SectionDef] = field(default_factory=dict)
    area_sections: dict[str, SectionDef] = field(default_factory=dict)
    materials: dict[str, MaterialDef] = field(default_factory=dict)
    #: Joint -> restraint (UX, UY, UZ, RX, RY, RZ).
    supports: dict[str, tuple[bool, ...]] = field(default_factory=dict)
    #: Case key (as combinations refer to it) -> case.
    cases: dict[str, LoadCase] = field(default_factory=dict)
    #: (name, {case key: factor}) in the file's order.
    combinations: list[tuple[str, dict[str, float]]] = field(default_factory=list)
    report: ImportReport = field(default_factory=lambda: ImportReport("?"))
    #: The file's horizontal axis letters as case names use them -> SAEngine axis and sign.
    lateral_axes: dict[str, tuple[str, float]] = field(
        default_factory=lambda: {"X": ("X", 1.0), "Y": ("Y", 1.0)}
    )


# ─────────────────────────────────────── sections ───────────────────────────────────────


def rectangle(width: float, depth: float) -> o.RectangleProfile:
    return o.RectangleProfile(xDim=width, yDim=depth)


def circle_profile(radius: float) -> o.CircleProfile:
    return o.CircleProfile(radius=radius)


def equivalent_rectangle(area: float, inertia: float) -> o.RectangleProfile | None:
    """The rectangle with ``area`` [mm²] and major moment of inertia ``inertia`` [mm⁴]."""
    if area <= 0 or inertia <= 0:
        return None
    depth = math.sqrt(12 * inertia / area)
    return rectangle(area / depth, depth)


_FRACTION = re.compile(r"^(\d+)-(\d+)/(\d+)$|^(\d+)/(\d+)$")


def _number(text: str) -> float | None:
    """A dimension of a designation: 6, 6.625, 1/4, 1-1/2."""
    m = _FRACTION.match(text)
    if m:
        if m.group(1):
            return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
        return int(m.group(4)) / int(m.group(5))
    try:
        return float(text)
    except ValueError:
        return None


def _dims(text: str) -> list[float] | None:
    values = [_number(p) for p in re.split(r"[X×*]", text) if p]
    if not values or any(v is None for v in values):
        return None
    return [float(v) for v in values if v is not None]


def estimated_i_shape(depth: float, mass: float, width: float | None = None) -> o.IShapeProfile:
    """An I-shape of ``depth`` [mm] and steel ``mass`` [kg/m], its flanges ``width`` wide (by
    default half the depth) and 1.6 times as thick as the web."""
    area = mass / 7850 * 1e6  # mm²
    bf = width or depth / 2
    tw = area / (3.2 * bf + depth)
    for _ in range(20):  # A = 2·bf·tf + (d - 2·tf)·tw with tf = 1.6·tw
        tw = area / (3.2 * bf + depth - 3.2 * tw)
    return o.IShapeProfile(
        overallWidth=bf, overallDepth=depth, webThickness=tw, flangeThickness=1.6 * tw
    )


def placeholder_i_shape(depth: float) -> o.IShapeProfile:
    return o.IShapeProfile(
        overallWidth=depth / 2,
        overallDepth=depth,
        webThickness=depth / 40,
        flangeThickness=depth / 25,
    )


def table_profile(name: str) -> Any:
    """The profile of a section of SAEngine's steel section table
    (:mod:`saengine.library.steel_sections`) by a program's name for it (IPE300, ISMB300,
    HE200A, SHS100X100X5, ISA75X75X6 ...), or None."""
    try:
        from pydantic import TypeAdapter

        from saengine.library import steel_sections
    except ImportError:
        return None
    key = re.sub(r"\s+", "", name.upper()).replace("×", "X")
    m = re.match(r"^HE(\d+)([ABM])$", key)  # European HE200A -> HEA 200
    if m:
        key = f"HE{m.group(2)}{m.group(1)}"
    key = re.sub(r"^ISA(?=\d)", "L", key)
    spaced = re.sub(r"^([A-Z]+)(\d)", r"\1 \2", key).replace("X", "x")
    for candidate in (spaced, key):
        section = steel_sections.find(candidate)
        if section is not None:
            return TypeAdapter(o.Profile).validate_python(steel_sections.profile_of(section))
    return None


#: Section families whose designations are metric (mm) or American (inches).
_METRIC_FAMILIES = {"SHS", "RHS", "BOX", "CHS", "ISA"}
_INCH_FAMILIES = {"HSS", "TS"}


def _name_scale(family: str, dims: Sequence[float]) -> tuple[float, str | None]:
    """mm per unit of a designation's numbers and the approximation made (None: the family
    fixes the units). The thickness is the last number."""
    if family in _METRIC_FAMILIES:
        return 1.0, None
    if family in _INCH_FAMILIES:
        return 25.4, None
    if dims[-1] < 1.0 and max(dims) < 30:
        return 25.4, f"{family} designation read in inches (its thickness is below 1)"
    return 1.0, None


def named_profile(name: str) -> tuple[Any, str | None]:
    """The profile of a steel section designation and the approximation made (None: exact);
    the profile is None (and the second value says why) when the name cannot be read.

    SAEngine's steel section table is asked first (:func:`table_profile`); tubes, pipes and
    angles whose names carry their dimensions are read from them (SHS/RHS/HSS/TUBE/BOX d×b×t,
    CHS/PIPE D×t, L/ISA d×b×t). Units (:func:`_name_scale`): SHS, RHS, BOX, CHS and ISA are
    metric (mm), HSS and TS American (inches); TUBE, PIPE and L are read in inches only when
    the thickness is below 1 (a fraction of an inch: no steel wall is under 1 mm), reported as
    an approximation;
    W, UB and UC names with a mass are estimated from depth and mass; other names get a
    placeholder I-shape of their nominal depth (75-1200 mm) to replace (both reported as
    approximations); other angle, tube, pipe, channel and tee names are not read.
    """
    found = table_profile(name)
    if found is not None:
        return found, None
    key = re.sub(r"\s+", "", name.upper())
    inch = 25.4
    m = re.match(r"^(SHS|RHS|HSS|TUBE?|BOX|TS)(\d.*)$", key)
    if m:
        dims = _dims(m.group(2))
        if dims and len(dims) == 3:
            scale, note = _name_scale(m.group(1), dims)
            d, b, t = (v * scale for v in dims)
            return o.RectangleHollowProfile(xDim=b, yDim=d, wallThickness=t), note
        if dims and len(dims) == 2 and m.group(1) == "HSS":  # round HSS: diameter × wall
            return o.CircleHollowProfile(
                radius=dims[0] * inch / 2, wallThickness=dims[1] * inch
            ), None
    m = re.match(r"^(CHS|PIPE)(\d.*)$", key)
    if m:
        dims = _dims(m.group(2))
        if dims and len(dims) == 2:
            scale, note = _name_scale(m.group(1), dims)
            return o.CircleHollowProfile(
                radius=dims[0] * scale / 2, wallThickness=dims[1] * scale
            ), note
    m = re.match(r"^(L|ISA)(\d.*)$", key)
    if m:
        dims = _dims(m.group(2))
        if dims and len(dims) == 3:
            scale, note = _name_scale(m.group(1), dims)
            d, b, t = (v * scale for v in dims)
            return o.LShapeProfile(depth=d, width=b, thickness=t), note
    m = re.match(r"^(UB|UC|W|HP)(\d.*)$", key)
    if m:
        dims = _dims(m.group(2))
        if dims and len(dims) == 3 and m.group(1) in ("UB", "UC"):
            return estimated_i_shape(dims[0], dims[2], dims[1]), (
                "estimated from the designation (depth, width, mass)"
            )
        if dims and len(dims) == 2:
            depth, mass = dims
            if depth < 50:  # W12X26: inches and lb/ft
                depth, mass = depth * inch, mass * 1.48816394
            return estimated_i_shape(depth, mass), (
                "estimated from the designation (depth and mass)"
            )
    m = re.match(r"^L(\d{1,2})(\d{2})(\d{2})$", key)
    if m:  # STAAD's compact American angle: L40404 = L4x4x4/16 (inches)
        d, b, t = float(m.group(1)), float(m.group(2)), int(m.group(3)) / 16
        if 0 < t < min(d, b) / 3:
            return o.LShapeProfile(depth=d * inch, width=b * inch, thickness=t * inch), (
                "decoded from STAAD's compact angle name (d, b in inches, t in sixteenths)"
            )
    if re.match(r"^(L|ISA|PIPE?|TUBE?|HSS|SHS|RHS|CHS|TS|BOX|C|MC|ISMC|UPN|T|WT)\d", key):
        # Angles, tubes, pipes, channels and tees are not I-shapes: a placeholder I would
        # change stiffness and weight by orders of magnitude, so the member is left out.
        return None, "a name of a non-I family that could not be read"
    digits = re.search(r"(\d{2,4})", key)
    depth = float(digits.group(1)) if digits else 0.0
    if 0 < depth < 50:
        depth *= inch
    if not 75 <= depth <= 1200:
        return None, "no plausible depth in the name"
    return placeholder_i_shape(depth), "not in the section table: a placeholder I-shape"


# ─────────────────────────────────────── building ───────────────────────────────────────


def _category(defn: MaterialDef) -> str:
    if defn.kind in ("concrete", "steel"):
        return defn.kind
    return "steel" if (defn.E or 0) > 100_000 else "concrete"


Axes = dict[str, tuple[str, float]]
_AXIS_IN_NAME = re.compile(r"(?:(^|[\s(])-\s*)?([XYZ])(?![A-Z])")


def direction_from_name(name: str, axes: Axes | None = None) -> tuple[str, float] | None:
    """SAEngine axis and sign of a lateral case by its name, the file's horizontal axis letters
    mapped by ``axes`` (STAAD Y up: X -> X, Z -> -Y), or None.

    The last horizontal axis letter that ends a word counts (EQX, WL Z, WIND X DIR); a minus
    sign before it is a direction only when it stands apart (``WL -X``, ``EQ(-X)``), not in
    ``WL-X``, which is the common way to write 'in X'.
    """
    axes = axes or {"X": ("X", 1.0), "Y": ("Y", 1.0)}
    found = None
    for m in _AXIS_IN_NAME.finditer(name.upper()):
        if m.group(2) in axes:
            found = m
    if found is None:
        return None
    axis, sign = axes[found.group(2)]
    return axis, -sign if found.group(1) is not None else sign


def _horizontal(case: LoadCase) -> np.ndarray:
    total = np.zeros(3)
    for load in case.loads:
        total += load.value
    return total


def _direction(case: LoadCase, axes: Axes | None = None) -> tuple[str, float]:
    """Axis (X or Y) and sign of a lateral case: from its loads, else its name (else X)."""
    total = _horizontal(case)
    if abs(total[0]) + abs(total[1]) > 1e-9:
        axis = 0 if abs(total[0]) >= abs(total[1]) else 1
        return ("X", "Y")[axis], 1.0 if total[axis] >= 0 else -1.0
    if case.direction:
        return case.direction, 1.0
    return direction_from_name(case.name, axes) or ("X", 1.0)


def maps_to(case: LoadCase | None, axes: Axes | None = None) -> tuple[str, float] | None:
    """SAEngine's case of a load case and the sign its factors take, or None."""
    if case is None:
        return None
    if case.kind in ("D", "SD"):
        return "D", 1.0
    if case.kind in ("L", "Lr"):
        return case.kind, 1.0
    if case.kind in ("W", "E"):
        axis, sign = _direction(case, axes)
        return f"{case.kind}{axis}", sign
    return None


Span = tuple[float, float] | None


def _clip(poly: list[tuple[float, float]], axis: int, span: Span) -> list[tuple[float, float]]:
    """``poly`` clipped to ``span`` along ``axis`` (Sutherland-Hodgman, both sides)."""
    if span is None:
        return poly
    for bound, keep_above in ((span[0], True), (span[1], False)):

        def inside(q: tuple[float, float], b: float = bound, up: bool = keep_above) -> bool:
            return q[axis] >= b if up else q[axis] <= b

        out: list[tuple[float, float]] = []
        for i, cur in enumerate(poly):
            prev = poly[i - 1]
            if inside(cur) != inside(prev):
                t = (bound - prev[axis]) / (cur[axis] - prev[axis])
                out.append((prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])))
            if inside(cur):
                out.append(cur)
        poly = out
        if not poly:
            break
    return poly


def hull_area(points: list[tuple[float, float]], xrange: Span = None, yrange: Span = None) -> float:
    """Area [mm²] of the convex hull of plan points [mm] within the plan ranges [mm]."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return 0.0

    def cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower: list[tuple[float, float]] = []
    upper: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = _clip(_clip(lower[:-1] + upper[:-1], 0, xrange), 1, yrange)
    n = len(hull)
    if n < 3:
        return 0.0
    return (
        abs(
            sum(
                hull[i][0] * hull[(i + 1) % n][1] - hull[(i + 1) % n][0] * hull[i][1]
                for i in range(n)
            )
        )
        / 2
    )


def build(model: TextModel, name: str | None = None) -> ImportedProject:
    """The SAEngine project of ``model`` (see the module notes) with its import report."""
    report = model.report
    builder = ProjectBuilder(name or Path(model.file).stem or "Imported", report)
    joints = model.joints
    if model.units:
        report.source["units"] = model.units

    # ── materials ──
    used: set[str] = set()
    default: dict[str, str] = {}

    def material(mname: str | None, steel: bool) -> str:
        if mname and mname in model.materials:
            if mname not in used:
                d = model.materials[mname]
                builder.add_material(
                    mname,
                    _category(d),  # type: ignore[arg-type]
                    E=d.E,
                    nu=d.nu,
                    density=d.density,
                    fc=d.fc,
                    fy=d.fy,
                    fu=d.fu,
                )
                used.add(mname)
            return mname
        kind = "steel" if steel else "concrete"
        if kind not in default:
            label = f"Default {kind} (imported)"
            builder.add_material(
                label,
                kind,  # type: ignore[arg-type]
                E=200_000.0 if steel else None,
                density=7850.0 if steel else 2400.0,
                fc=None if steel else 25.0,
            )
            default[kind] = label
        report.approximate(
            f"members and areas without a material: the default {kind}", mname or None
        )
        return default[kind]

    # ── sections and geometry ──
    frame_names: dict[tuple[str, str], str] = {}
    added_frames: set[str] = set()
    added_areas: set[str] = set()
    for f in model.frames:
        if f.i not in joints or f.j not in joints:
            report.skip("frame members with an undefined joint", f.id)
            continue
        sdef = model.sections.get(f.section) if f.section else None
        if sdef is None or sdef.profile is None:
            if sdef is not None and sdef.approximation:
                report.skip(f"sections not read ({sdef.approximation})", sdef.name)
            report.skip("frame members without a section that could be read", f.id)
            continue
        steel = not isinstance(sdef.profile, o.RectangleProfile | o.CircleProfile)
        mat = material(f.material or sdef.material, steel)
        section_name = frame_names.get((sdef.name, mat))
        if section_name is None:
            taken = any(s == sdef.name for s, _ in frame_names)
            section_name = f"{sdef.name} {mat}" if taken else sdef.name
            frame_names[(sdef.name, mat)] = section_name
            builder.add_frame_section(
                section_name, mat, sdef.profile.model_dump(mode="json", exclude_none=True)
            )
            if sdef.approximation:
                report.approximate(f"sections {sdef.approximation}; check in 04 Objects", sdef.name)
        builder.add_frame(
            f.id,
            section_name,
            tuple(float(v) for v in joints[f.i]),  # type: ignore[arg-type]
            tuple(float(v) for v in joints[f.j]),  # type: ignore[arg-type]
            rotation=f.rotation,
        )
        added_frames.add(f.id)

    area_names: dict[tuple[str, str], str] = {}
    for a in model.areas:
        if len(a.joints) < 3 or any(j not in joints for j in a.joints):
            report.skip("areas with an undefined joint", a.id)
            continue
        sdef = model.area_sections.get(a.section) if a.section else None
        if sdef is None or not sdef.thickness:
            report.skip("areas without a thickness", a.id)
            continue
        mat = material(a.material or sdef.material, False)
        section_name = area_names.get((sdef.name, mat))
        if section_name is None:
            taken = any(s == sdef.name for s, _ in area_names)
            section_name = f"{sdef.name} {mat}" if taken else sdef.name
            area_names[(sdef.name, mat)] = section_name
            builder.add_shell_section(section_name, mat, sdef.thickness)
        added_areas.add(a.id)
        builder.add_area(a.id, section_name, [tuple(float(v) for v in joints[j]) for j in a.joints])  # type: ignore[misc]

    # ── supports ──
    for jid, restraint in model.supports.items():
        if jid not in joints:
            report.skip("supports at undefined joints", jid)
            continue
        builder.add_support(tuple(float(v) for v in joints[jid]), restraint, f"joint {jid}")  # type: ignore[arg-type]

    # ── loads ──
    axes = model.lateral_axes
    lengths = {
        f.id: float(np.linalg.norm(joints[f.j] - joints[f.i]))
        for f in model.frames
        if f.i in joints and f.j in joints
    }
    # Horizontal areas the project has, by their level [mm].
    floors = {
        a.id: float(np.mean([joints[j][2] for j in a.joints]))
        for a in model.areas
        if a.id in added_areas
        and max(joints[j][2] for j in a.joints) - min(joints[j][2] for j in a.joints) < 1.0
    }
    centroids = {
        a.id: np.mean([joints[j] for j in a.joints], axis=0) for a in model.areas if a.id in floors
    }
    # Horizontal members the project has: (level, end i, end j) [mm].
    beams = [
        (float(joints[f.i][2]), joints[f.i], joints[f.j])
        for f in model.frames
        if f.id in added_frames and abs(float(joints[f.j][2] - joints[f.i][2])) < 1.0
    ]

    def plan_area(aid: str) -> float:
        """Area [m²] of area ``aid``, imported or not."""
        found = builder.area_of(aid)
        if found:
            return found
        a = next((x for x in model.areas if x.id == aid), None)
        if a is None or any(j not in joints for j in a.joints):
            return 0.0
        return total_area([joints[j] for j in a.joints])

    def inside(value: float, span: tuple[float, float] | None) -> bool:
        return span is None or span[0] - 1.0 <= value <= span[1] + 1.0

    def floor_levels(load: Load) -> list[tuple[float, list[str], float]]:
        """Per level a floor load reaches: its level, the slabs it loads there and, where there
        are none, the plan area [m²] of the beams there (the hull of their ends)."""
        levels = sorted({round(z, 0) for z in floors.values()} | {round(z, 0) for z, _, _ in beams})
        result = []
        for level in levels:
            if not inside(level, load.zrange):
                continue
            slabs = [
                aid
                for aid, z in floors.items()
                if abs(z - level) <= 1.0
                and inside(float(centroids[aid][0]), load.xrange)
                and inside(float(centroids[aid][1]), load.yrange)
            ]
            footprint = 0.0
            if not slabs:
                ends = [
                    (float(p[0]), float(p[1]))
                    for z, pi, pj in beams
                    if abs(z - level) <= 1.0
                    for p in (pi, pj)
                ]
                footprint = hull_area(ends, load.xrange, load.yrange) / 1e6
            if slabs or footprint > 0:
                result.append((level, slabs, footprint))
        return result

    selfweight = False
    top = max((float(p[2]) for p in joints.values()), default=0.0)
    live_on_roof = False
    for case in model.cases.values():
        mapped = maps_to(case, axes)
        target = mapped[0] if mapped else None
        if case.kind in ("W", "E") and not case.direction:
            total = _horizontal(case)
            if abs(total[0]) + abs(total[1]) <= 1e-9:
                by_name = direction_from_name(case.name, axes)
                if by_name:
                    report.approximate(
                        "direction of wind and earthquake cases with no loads read from their "
                        "names",
                        f"{case.name} -> {by_name[0]} {'+' if by_name[1] > 0 else '-'}",
                    )
                else:
                    report.approximate(
                        "wind and earthquake cases with no loads and no axis in their names: "
                        "X assumed",
                        case.name,
                    )
        if case.selfweight:
            if case.kind in ("D", "SD"):
                selfweight = True
                if abs(case.selfweight - 1) > 1e-6:
                    report.approximate(
                        "self-weight factors other than 1 (SAEngine applies 1)", case.name
                    )
            else:
                report.skip("self-weight in cases that are not dead loads", case.name)
        gravity_case = target in ("D", "L", "Lr")
        for load in case.loads:
            down = -float(load.value[2]) / 1e3  # kN/m², down positive (area loads)
            if load.kind in ("pressure", "floor", "to-frame") and gravity_case:
                if abs(float(load.value[0])) + abs(float(load.value[1])) > 1e-6 * max(
                    abs(down * 1e3), 1.0
                ):
                    report.approximate(
                        "area loads with a horizontal part: the vertical part kept", case.name
                    )
                if load.kind == "floor":
                    for level, slabs, footprint in floor_levels(load):
                        example = f"{case.name}: level {level / 1000:g} m"
                        if slabs:
                            report.approximate(
                                "floor loads applied to the slabs at their level (STAAD spreads "
                                "them to the beams)",
                                example,
                            )
                            for aid in slabs:
                                builder.add_area_load(aid, target, down)  # type: ignore[arg-type]
                                live_on_roof |= target == "L" and abs(level - top) <= 1.0
                        else:
                            builder.not_carried(
                                "floor loads on levels with no slabs (STAAD spreads them to the "
                                "beams; SAEngine loads slabs): the total over the plan area of "
                                "the beams there",
                                target,
                                down * footprint,
                                example,
                            )
                    continue
                if load.target in floors and down > 0:
                    builder.add_area_load(load.target, target, down)  # type: ignore[arg-type]
                    live_on_roof |= target == "L" and abs(floors[load.target] - top) <= 1.0
                    if load.kind == "to-frame":
                        report.approximate(
                            "area loads 'uniform to frame' applied to the slab (the program "
                            "spreads them straight to the frames)",
                            f"{case.name}: {load.target}",
                        )
                elif load.kind == "to-frame":
                    builder.not_carried(
                        "area loads 'uniform to frame' on areas that are not slabs (null areas; "
                        "SAEngine loads slabs)",
                        target,
                        down * plan_area(load.target),
                        f"{case.name}: {load.target}",
                    )
                else:
                    builder.not_carried(
                        "area loads on areas that are not imported slabs (walls, null areas) "
                        "or upwards",
                        target,
                        down * plan_area(load.target),
                        f"{case.name}: {load.target}",
                    )
                continue
            if load.kind == "joint" or load.kind == "point":
                total = load.value / 1e3
            elif load.kind == "uniform":
                total = load.value * (load.length or lengths.get(load.target, 0.0)) / 1e6
            elif load.kind in ("pressure", "to-frame"):
                total = load.value * plan_area(load.target) / 1e3
            elif load.kind == "floor":
                area = sum(
                    sum(builder.area_of(a) for a in slabs) + footprint
                    for _, slabs, footprint in floor_levels(load)
                )
                total = load.value * area / 1e3
            else:
                continue
            amount = -float(total[2]) if gravity_case else float(np.linalg.norm(total))
            what = {
                "joint": "joint loads",
                "point": "point loads on members",
                "uniform": "distributed loads on members",
                "pressure": "area loads",
                "to-frame": "area loads 'uniform to frame'",
                "floor": "floor loads",
            }[load.kind]
            if target in ("WX", "WY", "EX", "EY"):
                what = f"{what} of wind and earthquake cases (SAEngine makes its own from BNBC)"
            elif target is None:
                what = f"{what} of cases with no SAEngine load case"
            else:
                what = f"{what} (no place for them in SAEngine yet)"
            builder.not_carried(what, target, amount, f"{case.name}: {load.target}")
    builder.self_weight = selfweight

    # ── combinations ──
    for cname, factors in model.combinations:
        values: dict[str, list[float]] = {}
        for case_key, factor in factors.items():
            case = model.cases.get(case_key)
            mapped = maps_to(case, model.lateral_axes)
            if mapped is None:
                report.skip(
                    "combination terms on cases with no SAEngine load case", f"{cname}: {case_key}"
                )
                continue
            values.setdefault(mapped[0], []).append(mapped[1] * factor)
        result: dict[str, float] = {}
        for k, fs in values.items():
            if len({round(f, 6) for f in fs}) > 1:
                report.approximate(
                    "combination factors that differ on cases of one SAEngine case: the largest",
                    f"{cname}: {k}",
                )
            result[k] = max(fs, key=abs)
        if live_on_roof and "L" in result and "Lr" not in result:
            # The file's live load on the roof is SAEngine's roof live load Lr.
            result["Lr"] = result["L"]
            report.approximate(
                "combinations: the live load factor also on the roof live load Lr", cname
            )
        builder.add_combination(cname, result)
    report.count("joints", len(joints))
    report.count("loadCases", len(model.cases))
    return builder.build()


def total_area(points: list[np.ndarray]) -> float:
    """Area [m²] of a flat polygon of points in mm."""
    return polygon_area([tuple(float(v) for v in p) for p in points])  # type: ignore[misc]


__all__ = [
    "CASES",
    "Area",
    "FileUnits",
    "Frame",
    "Load",
    "LoadCase",
    "MaterialDef",
    "SectionDef",
    "TextModel",
    "build",
    "named_profile",
]

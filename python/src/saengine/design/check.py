"""Design checks of the reinforced-concrete frame members and slabs of an analysed SAEngine
model (slabs: see :mod:`saengine.design.slab`; they are reported with ``kind`` "slab" and
their shell element ids as ``members``).

For each beam and column of the building model with a reinforced rectangular (beams) or
rectangular/circular (columns) object type, the section forces of the analysis are combined
with the project settings' load combinations (as :mod:`saengine.fem.combinations` forms them:
the model is linear, so a combination is the factored sum of its static cases) and checked
against the section capacities of :mod:`saengine.design.rc`, enveloping all combinations and
all stations of all analysis elements of the member (``B1``, ``B1#2``, ...).

Member axes. The analysis places a profile's x-axis inertia (``ixx``, about its width) in the
local Iy of a horizontal member and in Iz of a vertical one; a quarter turn swaps them. So the
profile depth (``yDim``) lies along local z for a horizontal member (local z is up) and along
local y for a vertical one, swapped by a quarter turn. The analysis follows OpenSees's section
convention, tension positive: positive My stretches the +z fibres and positive Mz the -y
fibres. For a beam whose depth lies along local z (every floor beam) positive My therefore
puts the top bars in tension (hogging) and negative My the bottom bars (sagging).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from saengine.design import slab
from saengine.design.rc import (
    SLENDERNESS_LIMIT,
    DesignError,
    InteractionSurface,
    RcSection,
    flexure,
    section_of,
    shear,
    slenderness,
)
from saengine.library.bim import (
    AreaElement,
    BeamElement,
    BuildingModel,
    ColumnElement,
    MemberElement,
    SlabElement,
    WallElement,
)
from saengine.library.materials import Category, MaterialLibrary
from saengine.library.objects import Beam, Column, ObjectLibrary, Slab, Wall
from saengine.library.settings import ProjectSettings

#: Said in the notes instead of designing footings: they are Part 9's (saengine.substructure).
DESIGNED_IN_PART_9 = (
    "Foundations are designed in 9 Substructure (09 Substructure/substructure.json). The column "
    "bases are fixed supports of this analysis (no soil-structure interaction), and footings "
    "drawn in the building model are not checked here."
)

METHOD = [
    "Strength design to {code} (ACI 318-19 clauses and factors).",
    (
        "Flexure and axial force by strain compatibility with the rectangular stress block "
        "(concreteproperties); φ from the net tensile strain of the extreme bar (ACI 21.2.2)."
    ),
    (
        "Beams: sagging (bottom bars) and hogging (top bars) moments about the strong axis, and "
        "shear φ(Vc + Vs) with Vc = 0.17 λ √f'c b d when Av >= Av,min, else "
        "0.66 λs λ ρw^(1/3) √f'c b d (ACI Table 22.5.5.1, λ = 1, ρw of the face with fewer "
        "bars). Weak-axis bending, torsion and axial force in beams are not checked; shear is "
        "taken at every station, including the supports. The top of a beam is the face of its "
        "depth axis that points up."
    ),
    (
        "Columns: axial force with biaxial bending, the capacity read from the φ-factored "
        "interaction surface at the demand's axial force in the direction of its moment vector; "
        "φPn,max = 0.80 φ P0 (tied) or 0.85 φ P0 (spiral). Column shear is not checked."
    ),
    (
        "Slenderness is reported, not designed for: k = 1, lu = the analysis element's length, "
        "r = 0.3 h or 0.25 D, against {limit:g} (sway frames, ACI 6.2.5.1); moments are not "
        "magnified for second-order effects."
    ),
]


@dataclass
class _Piece:
    """One analysis element of a member, with its section forces per combination."""

    name: str
    id: int
    length: float  # m
    depth_along_z: bool
    axes: np.ndarray  # rows: local x, y, z (global)
    forces: list[np.ndarray]  # per combination: (stations, 6) N, Vy, Vz, T, My, Mz [N, N·m]
    start: np.ndarray | None = None  # end coordinates [m]
    end: np.ndarray | None = None


def design_report(out_dir: str | Path, project_path: str | Path) -> dict[str, Any]:
    """The design checks of the model ``project_path`` (``08 FEM/model.osmodel``) under the
    results in ``out_dir``, ready for JSON.

    The project's object types, materials, settings and building model are read from the
    SAEngine project the model belongs to (two folders up). Returns ``{"code", "method",
    "combinations", "elements", "skipped", "summary", "notes"}``: per checked element ``{"id",
    "kind", "type", "members", "checks", "utilisation", "ok"}`` with ``members`` the analysis
    element ids and each check ``{"name", "demand", "capacity", "unit", "utilisation",
    "combination", "ok", "note", "flag"}`` (forces in kN and kN·m, slabs per metre width in
    kN·m/m and kN/m; ``flag`` checks are reported but do not make the element fail), per
    skipped element ``{"id", "kind", "type", "reason"}``. Slabs (``kind`` "slab") list their
    shell elements as ``members``; slabs neither reinforced nor analysed as shells are only
    mentioned in the notes.
    """
    project_path = Path(project_path)
    root = project_path.resolve().parent.parent

    def read(relative: str) -> str:
        path = root / relative
        try:
            return path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"{relative} could not be read: {error}") from error

    settings = ProjectSettings.model_validate_json(
        read("02 Project Settings/project-settings.json")
    )
    materials = MaterialLibrary.model_validate_json(read("03 Materials/materials.json"))
    objects = ObjectLibrary.model_validate_json(read("04 Objects/objects.json"))
    building = BuildingModel.model_validate_json(read("06 BIM/bim.json"))
    project = json.loads(project_path.read_text(encoding="utf-8"))
    return design(project, out_dir, building, objects, materials, settings)


def design(
    project: dict[str, Any],
    out_dir: str | Path,
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary,
    settings: ProjectSettings,
    soil_text: str | None = None,
) -> dict[str, Any]:
    """:func:`design_report` with the project's parts already read. ``soil_text`` is no longer
    used: the footings it gave the allowable bearing pressures of are designed in Part 9
    (:func:`saengine.substructure.substructure_report`)."""
    combinations, pieces, notes, shell_forces = _demands(project, out_dir, settings)
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}

    members: list[tuple[str, str, Any]] = []  # (id, object type id, element or addition)
    for element in building.elements:
        if isinstance(element, (BeamElement, ColumnElement, MemberElement)):
            members.append((element.id, element.type, element))
    for addition in building.additions.members:
        members.append((addition.id, addition.type, addition))

    checked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    beam_sections: dict[str, tuple[RcSection, dict[bool, Any]]] = {}
    column_sections: dict[str, tuple[RcSection, InteractionSurface]] = {}
    for member_id, type_id, element in members:
        object_type = types.get(type_id)
        kind = object_type.kind if object_type else getattr(element, "kind", "member")

        def skip(
            reason: str, member_id: str = member_id, kind: str = kind, type_id: str = type_id
        ) -> None:
            skipped.append({"id": member_id, "kind": kind, "type": type_id, "reason": reason})

        own = pieces.get(member_id, [])
        if object_type is None:
            skip(f"unknown object type '{type_id}'")
            continue
        if not isinstance(object_type, (Beam, Column)):
            skip(f"{object_type.kind} members are not designed here")
            continue
        concrete = mats.get(object_type.material)
        if concrete is None or concrete.category != Category.CONCRETE or not concrete.concrete:
            skip("not a concrete member (structural steel is not designed here)")
            continue
        if object_type.reinforcement is None:
            skip("no reinforcement")
            continue
        if not own:
            skip("not in the analysis results")
            continue
        if not combinations:
            skip("no load combination could be formed")
            continue
        bars = mats.get(object_type.reinforcement.material)
        if bars is None or bars.steel is None:
            skip(f"unknown reinforcement material '{object_type.reinforcement.material}'")
            continue
        es = bars.mechanical.E or 200_000.0
        try:
            if isinstance(object_type, Beam):
                if type_id not in beam_sections:
                    section = section_of(
                        object_type.profile,
                        object_type.reinforcement,
                        concrete.concrete.fc,
                        bars.steel.fy,
                        es,
                    )
                    if section.profile.shape != "rectangle":
                        raise DesignError("beams are checked with rectangular profiles only")
                    beam_sections[type_id] = (
                        section,
                        {hog: flexure(section, hog) for hog in (False, True)},
                    )
                section, capacities = beam_sections[type_id]
                checks = _beam_checks(
                    section, capacities, object_type, own, combinations, _turned(element)
                )
            else:
                if type_id not in column_sections:
                    section = section_of(
                        object_type.profile,
                        object_type.reinforcement,
                        concrete.concrete.fc,
                        bars.steel.fy,
                        es,
                    )
                    column_sections[type_id] = (section, InteractionSurface(section))
                section, surface = column_sections[type_id]
                checks = _column_checks(section, surface, own, combinations, _turned(element))
        except DesignError as error:
            skip(str(error))
            continue
        strength = [c for c in checks if not c["flag"]]
        utilisation = max((c["utilisation"] for c in strength), default=0.0)
        checked.append(
            {
                "id": member_id,
                "kind": "beam" if isinstance(object_type, Beam) else "column",
                "type": type_id,
                "members": [p.id for p in own],
                "checks": checks,
                "utilisation": utilisation,
                "ok": all(c["ok"] for c in strength),
            }
        )

    for type_id, (section, _) in {**beam_sections, **column_sections}.items():
        notes += [f"{type_id}: {note}" for note in section.notes]
    slabs_seen = _design_slabs(
        project, building, types, mats, pieces, shell_forces, combinations, checked, skipped, notes
    )
    # Footings moved to Part 9 (saengine.substructure): this report designs the superstructure.
    notes.append(DESIGNED_IN_PART_9)
    failed = [e for e in checked if not e["ok"]]
    governing = max(checked, key=lambda e: e["utilisation"], default=None)
    code = settings.codes.concrete
    method = [line.format(code=code, limit=SLENDERNESS_LIMIT) for line in METHOD]
    if slabs_seen:
        method += slab.METHOD
    return {
        "code": code,
        "method": method,
        "combinations": combinations,
        "elements": checked,
        "skipped": skipped,
        "summary": {
            "checked": len(checked),
            "passed": len(checked) - len(failed),
            "failed": len(failed),
            "skipped": len(skipped),
            "maxUtilisation": governing["utilisation"] if governing else None,
            "governing": governing["id"] if governing else None,
        },
        "notes": notes,
    }


# ─────────────────────────────────────── slabs ───────────────────────────────────────


def _design_slabs(
    project: dict[str, Any],
    building: BuildingModel,
    types: dict[str, Any],
    mats: dict[str, Any],
    pieces: dict[str, list[_Piece]],
    shell_forces: dict[int, list[np.ndarray]],
    combinations: list[str],
    checked: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    notes: list[str],
) -> bool:
    """Checks the slabs of the building model (see :mod:`saengine.design.slab`), adding them to
    ``checked`` or ``skipped``. True when the building has slabs."""
    from saengine.library.sections import section_properties

    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    shells_of: dict[str, list[dict[str, Any]]] = {}
    for e in project.get("elements", []):
        if e.get("type") == "Shell":
            shells_of.setdefault((e.get("name") or str(e["id"])).split("#")[0], []).append(e)

    # (id, type id, plan outline mm, slab axes or None, level mm)
    candidates: list[tuple[str, str, list[tuple[float, float]], Any, float]] = []
    for element in building.elements:
        if isinstance(element, SlabElement):
            outline = [(float(x), float(y)) for x, y in element.boundary]
            candidates.append(
                (element.id, element.type, outline, slab.plan_axes(), element.elevation)
            )
        elif isinstance(element, AreaElement) and isinstance(types.get(element.type), Slab):
            outline = [(float(p[0]), float(p[1])) for p in element.outline]
            level = sum(float(p[2]) for p in element.outline) / len(element.outline)
            candidates.append(
                (element.id, element.type, outline, slab.outline_axes(element.outline), level)
            )
    if not candidates:
        return False

    beams_at: dict[float, list[slab.EdgeBeam]] = {}
    for element in building.elements:
        if not isinstance(element, BeamElement):
            continue
        beam_type = types.get(element.type)
        material = mats.get(beam_type.material) if beam_type else None
        profile = getattr(beam_type, "profile", None)
        if profile is None or material is None or not material.mechanical.E:
            continue
        try:
            ixx = section_properties(profile).ixx
        except (ValueError, TypeError, AttributeError, ArithmeticError):
            continue
        beams_at.setdefault(round(element.elevation), []).append(
            slab.EdgeBeam(
                tuple(element.start),
                tuple(element.end),
                material.mechanical.E * ixx,
                float(getattr(profile, "xDim", 0.0) or 0.0),
            )
        )

    supports_at = _line_supports(building, types, [c[4] for c in candidates])

    for slab_id, type_id, outline, axes, level in candidates:
        object_type = types.get(type_id)

        def skip(reason: str, slab_id: str = slab_id, type_id: str = type_id) -> None:
            skipped.append({"id": slab_id, "kind": "slab", "type": type_id, "reason": reason})

        own = shells_of.get(slab_id, [])
        if not isinstance(object_type, Slab):
            skip(f"unknown slab type '{type_id}'")
            continue
        if not own:
            if object_type.reinforcement is None:
                notes.append(
                    f"{slab_id}: slab not designed (no reinforcement, not analysed as shells)"
                )
            else:
                skip("not analysed as shells: set the analysis's slabs to shells to design it")
            continue
        concrete = mats.get(object_type.material)
        if concrete is None or concrete.category != Category.CONCRETE or not concrete.concrete:
            skip("not a concrete slab")
            continue
        reinforcement = object_type.reinforcement
        if reinforcement is None:
            skip("no reinforcement")
            continue
        if axes is None:
            skip("not a horizontal slab (inclined areas are not designed yet)")
            continue
        if not combinations:
            skip("no load combination could be formed")
            continue
        bars = mats.get(reinforcement.material)
        if bars is None or bars.steel is None:
            skip(f"unknown reinforcement material '{reinforcement.material}'")
            continue
        fc, fy = concrete.concrete.fc, bars.steel.fy
        es = bars.mechanical.E or 200_000.0

        shells: list[slab.ShellPoint] = []
        for e in own:
            points = [coords[n] for n in e["nodes"]]
            rows = shell_forces.get(e["id"])
            if not rows:
                continue
            shell_axes = slab.shell_axes(points)
            shells.append(
                slab.ShellPoint(
                    id=e["id"],
                    name=e.get("name") or str(e["id"]),
                    points=slab.integration_points(points, len(rows[0])),
                    forces=[slab.slab_forces(r, shell_axes, axes) for r in rows],
                    areas=slab.integration_areas(points, len(rows[0])),
                )
            )

        context = slab.SlabContext(
            boundary=outline, axes=axes, supports=supports_at.get(round(level), [])
        )
        flat = object_type.system == "flat"
        context.columns = _slab_columns(
            building, types, pieces, outline, level, notes if flat else []
        )
        neighbours = [
            other
            for other_id, _, other, _, other_level in candidates
            if other_id != slab_id and abs(other_level - level) <= 1
        ]
        try:
            context.thickness = slab.minimum_thickness(
                outline,
                axes,
                object_type.system,
                object_type.thickness,
                fy,
                concrete.mechanical.E or 4700 * math.sqrt(fc),
                neighbours,
                beams_at.get(round(level), []),
                column_size=(
                    sum(max(c.c1, c.c2) for c in context.columns) / len(context.columns)
                    if context.columns
                    else 0.0
                ),
                columns=[c.centre for c in context.columns] if flat else (),
            )
        except (ValueError, ZeroDivisionError) as error:
            notes.append(f"{slab_id}: minimum thickness not checked: {error}")
        try:
            checks = slab.slab_checks(
                object_type.system,
                object_type.thickness,
                reinforcement,
                fc,
                fy,
                es,
                shells,
                combinations,
                context,
            )
        except ValueError as error:
            skip(str(error))
            continue
        strength = [c for c in checks if not c["flag"]]
        checked.append(
            {
                "id": slab_id,
                "kind": "slab",
                "type": type_id,
                "members": [e["id"] for e in own],
                "checks": checks,
                "utilisation": max((c["utilisation"] for c in strength), default=0.0),
                "ok": all(c["ok"] for c in strength),
                "strips": [_strip_outline(strip, axes) for strip in context.strips],
            }
        )
        notes += [f"{slab_id}: {note}" for note in context.notes]
    return True


def _line_supports(
    building: BuildingModel, types: dict[str, Any], slab_levels: list[float]
) -> dict[float, list[slab.LineSupport]]:
    """The beams and structural walls supporting the slabs at each of ``slab_levels`` [mm]
    (keyed by the rounded level): the support lines of the slabs' design strips. A beam
    supports the slabs at its level; a wall those at its top and those it runs through, not a
    slab it stands on (its bottom at the slab's level, e.g. on a transfer slab)."""
    supports_at: dict[float, list[slab.LineSupport]] = {}
    for element in building.elements:
        support_type = types.get(element.type)
        if isinstance(element, BeamElement):
            levels = [element.elevation]
            width = float(getattr(getattr(support_type, "profile", None), "xDim", 0.0) or 0.0)
        elif isinstance(element, WallElement) and isinstance(support_type, Wall):
            if not support_type.structural:
                continue
            levels = [at for at in slab_levels if element.bottom + 1 < at < element.top + 1]
            width = float(support_type.thickness)
        else:
            continue
        for at in dict.fromkeys(round(level) for level in levels):
            supports_at.setdefault(at, []).append(
                slab.LineSupport(
                    element.id,
                    (float(element.start[0]), float(element.start[1])),
                    (float(element.end[0]), float(element.end[1])),
                    width,
                )
            )
    return supports_at


def _slab_columns(
    building: BuildingModel,
    types: dict[str, Any],
    pieces: dict[str, list[_Piece]],
    outline: list[tuple[float, float]],
    level: float,
    notes: list[str],
) -> list[Any]:
    """The columns meeting a slab at ``level`` (mm) inside its ``outline``, with the force and
    moment the slab puts on each per combination (from the column ends above and below)."""
    from saengine.library.objects import CircleProfile, RectangleProfile

    z = level * 1e-3
    joints = []
    for element in building.elements:
        if not isinstance(element, ColumnElement):
            continue
        if not (element.bottom < level + 1 and element.top > level - 1):
            continue
        if not slab._inside(np.asarray(element.position, dtype=float), outline):
            continue
        profile = getattr(types.get(element.type), "profile", None)
        if isinstance(profile, RectangleProfile):
            c1, c2 = profile.xDim, profile.yDim
        elif isinstance(profile, CircleProfile):
            c1 = c2 = math.sqrt(math.pi) * profile.radius  # the square of the same area
        else:
            notes.append(f"{element.id}: punching not checked (rectangular or circular only)")
            continue
        own = pieces.get(element.id, [])
        below = [p for p in own if p.end is not None and abs(p.end[2] - z) < 2e-3]
        above = [p for p in own if p.start is not None and abs(p.start[2] - z) < 2e-3]
        if not below and not above:
            notes.append(f"{element.id}: punching not checked (no column end at the slab)")
            continue
        joint = slab.ColumnJoint(
            element.id,
            (float(element.position[0]), float(element.position[1])),
            c1,
            c2,
            float(element.rotation or 0.0),
        )
        count = len((below or above)[0].forces)
        for c in range(count):
            force, moment = np.zeros(3), np.zeros(3)
            # The joint's equilibrium: the slab's action on it is the force of the column below
            # on its top end less the force the column above puts on its bottom end.
            for p in below:
                force += p.forces[c][-1, :3] @ p.axes
                moment += p.forces[c][-1, 3:] @ p.axes
            for p in above:
                force -= p.forces[c][0, :3] @ p.axes
                moment -= p.forces[c][0, 3:] @ p.axes
            joint.forces.append(force)
            joint.moments.append(moment * 1e3)  # N·mm
        joints.append(joint)
    return joints


def _strip_outline(strip: Any, axes: Any) -> dict[str, Any]:
    """A design strip's bay for the report: ``{"name", "direction", "kind", "outline"}`` with
    the plan corners of the bay in metres (global X, Y)."""
    frame = slab.PlanFrame(axes)
    along = strip.direction == "X"
    corners = []
    for a, b in (
        (strip.start, strip.lo),
        (strip.end, strip.lo),
        (strip.end, strip.hi),
        (strip.start, strip.hi),
    ):
        point = frame.plan(a, b) if along else frame.plan(b, a)
        corners.append([round(float(point[0]) / 1e3, 4), round(float(point[1]) / 1e3, 4)])
    return {
        "name": strip.name,
        "direction": strip.direction,
        "kind": strip.kind,
        "outline": corners,
    }


# ─────────────────────────────────────── demands ───────────────────────────────────────


def _demands(
    project: dict[str, Any], out_dir: str | Path, settings: ProjectSettings
) -> tuple[list[str], dict[str, list[_Piece]], list[str], dict[int, list[np.ndarray]]]:
    """The combinations formed, each member's pieces with their section forces per combination,
    notes on what could not be formed, and each shell's forces per combination (one row of
    N11 N22 N12 M11 M22 M12 Q13 Q23 per integration point, shell axes, N/m and N·m/m)."""
    from opensees_studio.services.result_store import load_manifest, load_results
    from opensees_studio.services.results import StaticResults

    from saengine.fem.combinations import combination_factors
    from saengine.fem.display import _case_loads, _code, _elements, _last, element_section_forces

    try:
        manifest = load_manifest(out_dir)
    except (OSError, ValueError) as error:
        raise ValueError("there are no results; run the analysis first") from error
    elements = [e for e in _elements(project) if not e.name.split("#")[0].endswith("/embed")]
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}

    # Section forces of each static case (linear in the end forces and the loads).
    shell_ids = [e["id"] for e in project.get("elements", []) if e.get("type") == "Shell"]
    by_case: dict[str, dict[int, np.ndarray]] = {}
    shell_case: dict[str, dict[int, np.ndarray]] = {}
    for entry in manifest["cases"]:
        results = load_results(entry, out_dir)
        if not isinstance(results, StaticResults):
            continue
        reached = float(results.load_factors[-1]) if len(results.load_factors) else 1.0
        loads = _case_loads(project, int(entry["case_id"]))
        shell_case[_code(entry["case_name"])] = {
            i: _shell_rows(results.shell_forces.get(i)) for i in shell_ids
        }
        by_case[_code(entry["case_name"])] = {
            e.id: element_section_forces(
                e, _last(results.element_forces, e.id, 12), reached * loads.get(e.id, np.zeros(3))
            )
            for e in elements
        }

    names: list[str] = []
    factors_of: list[dict[str, float]] = []
    notes: list[str] = []
    for combination in settings.combinations:
        factors = combination_factors(combination)
        missing = [case for case in factors if case not in by_case]
        if missing:
            notes.append(
                f"{combination.name}: not checked, case {', '.join(missing)} has no results"
            )
            continue
        names.append(combination.name)
        factors_of.append(factors)

    pieces: dict[str, list[_Piece]] = {}
    for e in elements:
        a, b = coords[e.i], coords[e.j]
        axis = b - a
        vertical = abs(axis[2]) > abs(axis[0])
        pieces.setdefault(e.name.split("#")[0], []).append(
            _Piece(
                name=e.name,
                id=e.id,
                length=e.length,
                depth_along_z=not vertical,  # quarter turns are applied by the caller
                axes=e.axes,
                forces=[
                    sum(f * by_case[case][e.id] for case, f in factors.items())
                    for factors in factors_of
                ],
                start=a,
                end=b,
            )
        )

    # Shells: N11 ... Q23 at each integration point of the last step, per combination.
    shells: dict[int, list[np.ndarray]] = {}
    for i in shell_ids:
        shells[i] = [
            sum(f * shell_case[case][i] for case, f in factors.items()) for factors in factors_of
        ]
    return names, pieces, notes, shells


def _shell_rows(rows: Any) -> np.ndarray:
    """A shell's forces at the last step, one row of 8 per integration point."""
    if rows is None or not len(rows):
        return np.zeros((1, 8))
    return np.asarray(rows[-1], dtype=float).reshape(-1, 8)


def _profile_forces(piece: _Piece, turned: bool, forces: np.ndarray) -> dict[str, np.ndarray]:
    """Section forces in the profile's axes at each station [N, N·mm]: ``P`` (compression
    positive), ``Mx`` and ``Vy`` (bending about the width axis, shear along the depth; positive
    ``Mx`` stretches the top fibres), ``My`` (bending about the depth axis).

    The profile's "top" is the end of its depth axis that points up: local +z of a horizontal
    member (always up), and for a member the analysis treats as vertical (a column, or a sloped
    member steeper than it runs along X, e.g. a rafter along Y) local +y or -y, whichever points
    up; that depends on the direction the member was drawn in. A depth axis lying flat (a
    column, a beam turned on its side) keeps local + as "top".
    """
    along_z = piece.depth_along_z != turned
    n, vy, vz, my, mz = forces[:, 0], forces[:, 1], forces[:, 2], forces[:, 4], forces[:, 5]
    rise = float(piece.axes[2 if along_z else 1][2])
    up = -1.0 if rise < -1e-9 else 1.0
    if along_z:
        return {"P": -n, "Mx": up * my * 1e3, "Vy": vz, "My": mz * 1e3}
    return {"P": -n, "Mx": -up * mz * 1e3, "Vy": vy, "My": my * 1e3}


def _turned(element: Any) -> bool:
    rotation = getattr(element, "rotation", 0.0) or 0.0
    return round(rotation / 90) % 2 == 1


# ─────────────────────────────────────── checks ───────────────────────────────────────


def _check(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    combination: str | None,
    note: str = "",
    flag: bool = False,
    utilisation: float | None = None,
) -> dict[str, Any]:
    if utilisation is None:
        utilisation = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    # Pass/fail from the value reported, so the counts and the viewer's colour bands agree.
    utilisation = round(float(utilisation), 3) if math.isfinite(utilisation) else 99.0
    return {
        "name": name,
        "demand": round(float(demand), 2),
        "capacity": round(float(capacity), 2),
        "unit": unit,
        "utilisation": utilisation,
        "combination": combination,
        "ok": bool(utilisation <= 1.0),
        "note": note,
        "flag": flag,
    }


def _where(piece: _Piece, station: int, stations: int) -> str:
    return f"{piece.name} at {station / (stations - 1):.2f} L"


def _beam_checks(
    section: RcSection,
    capacities: dict[bool, Any],
    beam: Beam,
    pieces: list[_Piece],
    combinations: list[str],
    turned: bool = False,
) -> list[dict[str, Any]]:
    sag = hog = shear_demand = (0.0, None, "")
    for piece in pieces:
        for c, forces in enumerate(piece.forces):
            values = _profile_forces(piece, turned, forces)
            count = len(forces)
            for k in range(count):
                moment, v = float(values["Mx"][k]), abs(float(values["Vy"][k]))
                where = _where(piece, k, count)
                if -moment > sag[0]:
                    sag = (-moment, combinations[c], where)
                if moment > hog[0]:
                    hog = (moment, combinations[c], where)
                if v > shear_demand[0]:
                    shear_demand = (v, combinations[c], where)
    checks = []
    for label, hogging, demand in (
        ("Flexure, sagging (bottom bars)", False, sag),
        ("Flexure, hogging (top bars)", True, hog),
    ):
        capacity = capacities[hogging]
        note = demand[2]
        if capacity.mn <= 0:
            note = "no bars on the tension face" + (f"; {note}" if note else "")
        else:
            note = f"φ = {capacity.phi:.2f}, εt = {capacity.eps_t:.4f}" + (
                f"; {note}" if note else ""
            )
            if capacity.eps_t < 0.004:
                note += "; εt below 0.004 (ACI 9.3.3.1)"
        checks.append(
            _check(label, demand[0] / 1e6, capacity.phi_mn / 1e6, "kN·m", demand[1], note)
        )
    transverse = beam.reinforcement.transverse if beam.reinforcement else None
    resistance = shear(
        section,
        transverse.dia if transverse else None,
        transverse.legs if transverse else 0,
        transverse.spacing if transverse else None,
    )
    parts = [f"Vc = {resistance.vc / 1e3:.1f} kN, Vs = {resistance.vs / 1e3:.1f} kN"]
    if transverse is None:
        parts.append("no stirrups")
    elif not resistance.with_min_stirrups:
        parts.append(
            f"Av = {resistance.av:.0f} mm² below Av,min = {resistance.av_min:.0f} mm² (ACI 9.6.3.4)"
        )
    if not resistance.with_min_stirrups:
        parts.append(
            f"Vc = 0.66 λs ρw^(1/3) √f'c b d, λs = {resistance.lambda_s:.2f}, "
            f"ρw = {resistance.rho_w:.4f}"
        )
    if resistance.vs_limited:
        parts.append("Vs limited to 0.66 √f'c b d")
    if shear_demand[2]:
        parts.append(shear_demand[2])
    checks.append(
        _check(
            "Shear",
            shear_demand[0] / 1e3,
            resistance.phi_vn / 1e3,
            "kN",
            shear_demand[1],
            "; ".join(parts),
        )
    )
    if not resistance.with_min_stirrups:
        # ACI 9.6.3.1: beams need at least Av,min where Vu > 0.083 φ λ √f'c bw d.
        checks.append(
            _check(
                "Minimum stirrups (ACI 9.6.3.1)",
                shear_demand[0] / 1e3,
                resistance.av_min_threshold / 1e3,
                "kN",
                shear_demand[1],
                "Av below Av,min: Vu must not exceed 0.083 φ √f'c b d"
                + (f"; {shear_demand[2]}" if shear_demand[2] else ""),
            )
        )
    return checks


def _column_checks(
    section: RcSection,
    surface: InteractionSurface,
    pieces: list[_Piece],
    combinations: list[str],
    turned: bool = False,
) -> list[dict[str, Any]]:
    axial = (-math.inf, None, "")
    governing: tuple[float, Any, str | None, str, float] | None = None
    for piece in pieces:
        for c, forces in enumerate(piece.forces):
            values = _profile_forces(piece, turned, forces)
            count = len(forces)
            for k in range(count):
                pu = float(values["P"][k])
                mux, muy = abs(float(values["Mx"][k])), abs(float(values["My"][k]))
                if pu > axial[0]:
                    axial = (pu, combinations[c], _where(piece, k, count))
                result = surface.check(pu, mux, muy)
                if governing is None or result.utilisation > governing[0]:
                    governing = (
                        result.utilisation,
                        result,
                        combinations[c],
                        _where(piece, k, count),
                        pu,
                    )
    checks = [
        _check(
            "Axial compression",
            max(axial[0], 0.0) / 1e3,
            section.phi_pn_max / 1e3,
            "kN",
            axial[1],
            axial[2],
        )
    ]
    if governing is not None:
        utilisation, result, combination, where, pu = governing
        note = f"Pu = {pu / 1e3:.1f} kN; {where}" + (f"; {result.note}" if result.note else "")
        checks.append(
            _check(
                "Axial force and biaxial bending",
                result.mu / 1e6,
                result.phi_mn / 1e6,
                "kN·m",
                combination,
                note,
                utilisation=utilisation,
            )
        )
    ratio, where = max(
        ((slenderness(section, p.length * 1e3), p.name) for p in pieces), key=lambda t: t[0]
    )
    checks.append(
        _check(
            "Slenderness k lu / r",
            ratio,
            SLENDERNESS_LIMIT,
            "",
            None,
            f"{where}; "
            + (
                "slender: second-order effects are not included"
                if ratio > SLENDERNESS_LIMIT
                else "short column"
            ),
            flag=True,
        )
    )
    return checks

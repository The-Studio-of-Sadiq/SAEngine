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

from saengine.codes import context as code_context
from saengine.design import seismic_rules, slab, steel_design
from saengine.design import slender as slenderness_design
from saengine.design.rc import (
    DesignError,
    InteractionSurface,
    RcSection,
    flexure,
    section_of,
    shear,
)
from saengine.design.steel import SteelDesignError
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
from saengine.library.objects import Beam, Brace, Column, ObjectLibrary, Slab, Wall
from saengine.library.settings import LoadCombination, ProjectSettings

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
    #: Per combination, the part of ``forces`` from its lateral load cases (wind, earthquake,
    #: response spectrum: the sway moments Ms of slenderness) and from its sustained ones (D,
    #: SD: βdns); None when not formed.
    sway: list[np.ndarray] | None = None
    sustained: list[np.ndarray] | None = None


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
    mentioned in the notes. Structural walls (``kind`` "wall", :mod:`saengine.design.
    wall_design`: their piers, boundary elements and coupling beams, every shell as
    ``members``) and stairs (``kind`` "staircase", :mod:`saengine.design.stairs`: designed by
    hand methods, ``members`` empty) are elements too.
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
    ensure_seismic_design(out_dir, project_path, settings)
    return design(project, out_dir, building, objects, materials, settings)


def ensure_seismic_design(
    out_dir: str | Path, project_path: str | Path, settings: ProjectSettings
) -> dict[str, Any] | None:
    """Integrator glue: when the project designs for earthquake from the response spectrum
    (``analysis.seismicDesign``, :func:`saengine.fem.seismic_design.design_uses_spectrum`) and
    the run has response spectrum results, the modal-force run and its summary
    (``<out_dir>/rs-design``) that :func:`design` reads; run here when missing or stale
    (:func:`saengine.fem.seismic_design.seismic_design` keeps it while the model and the results
    do not change), so every caller (the app, Run All, the report) designs with the scaled
    response spectrum rather than silently with the static EX, EY. None otherwise, or when the
    run fails (the design then uses the static cases, with a note)."""
    from saengine.fem import seismic_design

    if not seismic_design.design_uses_spectrum(settings):
        return None
    if not (Path(out_dir) / "manifest.json").is_file():
        return None
    from saengine.library.settings import read_soil_text, resolve_site_class

    # The site class the analysis used (from the soil report when the settings say so).
    settings, _ = resolve_site_class(
        settings, read_soil_text(Path(project_path).resolve().parent.parent)
    )
    _SEISMIC_PROBLEMS.pop(str(Path(out_dir)), None)
    try:
        summary = seismic_design.seismic_design(out_dir, project_path, settings, run=True)
    except (OSError, ValueError, KeyError) as error:
        _SEISMIC_PROBLEMS[str(Path(out_dir))] = str(error)
        return None
    if not summary.get("available") and seismic_design.expected_axes(project_path):
        # The model has response spectrum cases but their results are incomplete (the analysis
        # is running, or was run without them): say why the design falls back to EX, EY.
        _SEISMIC_PROBLEMS[str(Path(out_dir))] = "; ".join(summary.get("notes", []))
    return summary


#: Why the response spectrum design could not be run, by results folder (for the notes).
_SEISMIC_PROBLEMS: dict[str, str] = {}


@code_context.in_project_pack(path_params=("out_dir",))
def design(
    project: dict[str, Any],
    out_dir: str | Path,
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary,
    settings: ProjectSettings,
    soil_text: str | None = None,
    collect: dict[str, Any] | None = None,
    slenderness: slenderness_design.SlenderOptions | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """:func:`design_report` with the project's parts already read. ``soil_text`` is no longer
    used: the footings it gave the allowable bearing pressures of are designed in Part 9
    (:func:`saengine.substructure.substructure_report`).

    ``collect``: when given, filled with what the checks worked from, for the design mode
    (:mod:`saengine.design.required`): ``"combinations"``, per wall pier under ``"walls"``
    (:func:`saengine.design.wall_design.design_walls`), per staircase type under ``"stairs"``
    (:func:`saengine.design.stairs.stair_report`), and per checked beam, column and
    slab under ``"members"`` and ``"slabs"`` its section or slab context, its analysis pieces
    with their combined forces, its materials and its checks; a column also its demand
    ``"points"`` with the moments magnified for slenderness.

    ``slenderness``: how column slenderness is designed for
    (:class:`saengine.design.slender.SlenderOptions`, or the settings' dict of it); the
    project settings' (:func:`saengine.design.slender.options_from_settings`) when None. The storeys' stability (sway or nonsway) is returned as
    ``"stability"`` (:func:`saengine.design.slender.storey_rows`)."""
    from saengine.design import seismic_detailing
    from saengine.fem import second_order, seismic_design

    # Integrator glue: which provisions of BNBC Sec 8.3 apply (saengine.design.seismic_rules),
    # with the site class the analysis used; the elements needing the Ω0 combinations get them.
    root = Path(out_dir).resolve().parent.parent
    try:
        scope, resolved = seismic_detailing.scope_of(settings, materials, objects, building, root)
    except (ValueError, KeyError, AttributeError) as error:
        scope, resolved = None, settings
        scope_problem = str(error)
    omega_elements = set(scope["omega"]["elements"]) if scope else set()
    # Integrator glue: the elements Sec 2.5.5.6.1 adds beyond seismic_rules' (girders carrying
    # transfer beams, walls under them, transfer slabs; saengine.design.overstrength).
    from saengine.design import overstrength

    try:
        omega_extra = overstrength.overstrength_scope(settings, building, objects, materials)
    except (ValueError, KeyError, AttributeError, TypeError) as error:
        omega_extra = {"ids": [], "combinations": [], "notes": [], "added": []}
        omega_extra["notes"].append(f"the Ω0 elements could not all be found: {error}")
    if omega_extra["ids"] and scope is not None:
        omega_elements |= set(omega_extra["ids"])
        scope["omega"]["elements"] = sorted(omega_elements)
        if not scope["omega"].get("combinations"):
            scope["omega"]["combinations"] = omega_extra["combinations"]
    omega_static = (
        [
            LoadCombination(**{k: v for k, v in c.items() if k != "clause"})
            for c in scope["omega"]["combinations"]
        ]
        if scope and omega_elements
        else []
    )

    extra: dict[str, Any] = {}
    with_omega = (
        settings.model_copy(update={"combinations": settings.combinations + omega_static})
        if omega_static
        else settings
    )
    if seismic_design.design_uses_spectrum(settings):
        static: dict[str, Any] = {}

        def static_demands(
            project: dict[str, Any], out_dir: str | Path, settings: Any, inner: Any = None
        ) -> Any:
            found = _demands(project, out_dir, settings, inner)
            static.update(
                names=list(found[0]),
                shells={i: list(rows) for i, rows in found[3].items()},
                inner=inner if inner is not None else {},
            )
            return found

        summary = None
        if omega_elements:
            summary = seismic_design.load_summary(out_dir)
            if summary and summary.get("combinations"):
                summary = {
                    **summary,
                    "combinations": summary["combinations"]
                    + seismic_rules.omega_rs_combinations(summary["combinations"], resolved),
                }
        combinations, pieces, notes, shell_forces = seismic_design.design_demands(
            project, out_dir, with_omega, extra, summary=summary, base=static_demands
        )
        if "shellSway" not in extra and static:
            extra["shellSway"] = _spectrum_shell_sway(static, combinations, shell_forces)
        problem = _SEISMIC_PROBLEMS.pop(str(Path(out_dir)), None)
        if problem:
            notes.append(
                f"the response spectrum design could not be run: {problem}"
                if "static cases" in problem
                else f"the response spectrum design could not be run ({problem}): the "
                "earthquake combinations use the static cases EX, EY"
            )
    else:
        # Integrator glue: with the eccentric static cases (analysis.accidentalEccentricity),
        # each E combination is checked with the masses shifted both ways (BNBC 2020 Part 6
        # Sec 2.5.7.6.2): EX becomes EXP and EXN, EY becomes EYP and EYN.
        from saengine.fem.combinations import eccentric_combinations, model_cases

        expanded = eccentric_combinations(with_omega.combinations, model_cases(project))
        if expanded is not None:
            with_omega = with_omega.model_copy(update={"combinations": expanded})
        combinations, pieces, notes, shell_forces = _demands(project, out_dir, with_omega, extra)
        if expanded is not None:
            notes.append(
                "accidental torsion: each earthquake combination is checked with the eccentric "
                "static cases EXP/EXN (EYP/EYN), the story masses shifted ±5 % across the force "
                "(BNBC 2020 Part 6 Sec 2.5.7.6.2)"
            )
    if scope is None:
        notes.append(f"the seismic detailing scope could not be found: {scope_problem}")
    omega_indices = [c for c, name in enumerate(combinations) if name.startswith("Ω0: ")]
    if omega_indices:
        # Integrator glue: the Ω0 combinations (Sec 2.5.5.6, 2.5.13.4) apply to the elements
        # scope["omega"] names only; the others carry no force in them, so they never govern.
        _drop_combinations(
            pieces,
            shell_forces,
            omega_indices,
            keep=omega_elements,
            keep_shells=_shells_of(project, omega_elements),
        )
        notes.append(
            "Ω0 combinations (BNBC 2020 Part 6 Sec 2.5.13.4) applied to "
            + ", ".join(sorted(omega_elements))
            + " only"
        )
        if omega_extra["ids"]:
            notes.append(overstrength.em_factors(settings)["clause"])
    notes += omega_extra["notes"]
    slender_options = (
        slenderness_design.SlenderOptions.of(slenderness)
        if slenderness is not None
        else slenderness_design.options_from_settings(settings)
    )
    if slenderness is None:
        # Integrator glue: the analysis model says whether it is second order (P-Delta from a
        # preload, saengine.fem.second_order), whatever the settings say now: δs is applied
        # to a first-order model and taken as 1 in a second-order one.
        slender_options.second_order = "pDelta" if second_order.is_second_order(project) else "none"
    if collect is not None:
        collect["combinations"] = combinations
        collect.setdefault("members", [])
        collect.setdefault("slabs", [])
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    # Integrator glue: the design overwrites (saengine.design.overwrites: k, unbraced lengths,
    # framing; the member's over its object type's) for the column slenderness and steel.
    from saengine.design import overwrites as design_overwrites

    resolved_overwrites = design_overwrites.resolve_all(
        [
            (e.id, e, types.get(e.type))
            for e in building.elements
            if isinstance(e, (BeamElement, ColumnElement, MemberElement))
        ]
        + [(a.id, a, types.get(a.type)) for a in building.additions.members]
    )
    context = slenderness_design.SlenderContext(
        project,
        building,
        types,
        mats,
        pieces,
        combinations,
        extra.get("lateralDisplacements", []),
        slender_options,
        {i: (forces, extra.get("shellSway", {}).get(i, [])) for i, forces in shell_forces.items()},
        [bool(e) for e in extra.get("envelope", [])],
        extra.get("storeyShear"),
        resolved_overwrites,
    )

    exact = exact_rotation(project)
    members: list[tuple[str, str, Any]] = []  # (id, object type id, element or addition)
    for element in building.elements:
        if isinstance(element, (BeamElement, ColumnElement, MemberElement)):
            members.append((element.id, element.type, element))
    for addition in building.additions.members:
        members.append((addition.id, addition.type, addition))
    # Integrator glue: the forces at the support faces (saengine.design.face_forces) from the
    # analysis's face offsets and face forces (saengine.fem.end_zones, face-forces.json).
    from saengine.design import face_forces

    face_data = _face_forces_file(out_dir)
    face_offsets = (face_data or {}).get("faceOffsets")
    static_factors = (
        extra.get("factors") if not seismic_design.design_uses_spectrum(settings) else None
    )
    faced_any = False

    checked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    designed: list[seismic_detailing.Designed] = []
    steel_seen = False
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
        # Integrator glue: structural steel beams, columns and braces (BNBC 2020 Part 6 Ch 10,
        # saengine.design.steel_design), with their types' simple connections.
        steel_material = mats.get(object_type.material)
        if isinstance(object_type, (Beam, Column, Brace)) and steel_design.is_steel(steel_material):
            if not own:
                skip("not in the analysis results")
                continue
            if not combinations:
                skip("no load combination could be formed")
                continue
            try:
                entry, steel_collected = steel_design.design_member(
                    member_id,
                    steel_design.KINDS[object_type.kind],
                    object_type,
                    steel_material,
                    mats,
                    own,
                    combinations,
                    _turned(element, exact),
                    project,
                    design_overwrites.steel_options(resolved_overwrites.get(member_id)),
                )
            except SteelDesignError as error:
                skip(str(error))
                continue
            checked.append(entry)
            steel_seen = True
            if collect is not None:
                collect.setdefault("steel", []).append(steel_collected)
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
        joints_own = own
        try:
            if isinstance(object_type, Beam):
                if type_id not in beam_sections:
                    section = section_of(
                        object_type.profile,
                        object_type.reinforcement,
                        concrete.concrete.fc,
                        bars.steel.fy,
                        es,
                        concrete.concrete.maxAggregate,
                    )
                    if section.profile.shape != "rectangle":
                        raise DesignError("beams are checked with rectangular profiles only")
                    beam_sections[type_id] = (
                        section,
                        {hog: flexure(section, hog) for hog in (False, True)},
                    )
                section, capacities = beam_sections[type_id]
                faced = face_forces.at_faces(
                    own,
                    project,
                    shear_depth=face_forces.shear_depth(section),
                    face_rows=face_forces.face_rows_of(face_data, static_factors, own)
                    if static_factors
                    else None,
                    face_offsets=face_offsets,
                )
                own = faced.pieces
                checks = _beam_checks(
                    section, capacities, object_type, own, combinations, _turned(element, exact)
                )
                if faced.at_faces:
                    face_forces.annotate(checks, faced)
                faced_any = faced_any or faced.at_faces
            else:
                if type_id not in column_sections:
                    section = section_of(
                        object_type.profile,
                        object_type.reinforcement,
                        concrete.concrete.fc,
                        bars.steel.fy,
                        es,
                        concrete.concrete.maxAggregate,
                    )
                    column_sections[type_id] = (section, InteractionSurface(section))
                section, surface = column_sections[type_id]
                # Slenderness from the joint forces (M1, M2 at the joints, conservative); the
                # strength checks at the beam soffit and the top of the slab.
                slender = context.column(
                    member_id,
                    section,
                    joints_own,
                    _turned(element, exact),
                    slenderness_design.concrete_modulus(concrete),
                )
                faced = face_forces.at_faces(
                    own,
                    project,
                    face_rows=face_forces.face_rows_of(face_data, static_factors, own)
                    if static_factors
                    else None,
                    face_offsets=face_offsets,
                )
                own = faced.pieces
                checks = _column_checks(
                    section, surface, own, combinations, _turned(element, exact), slender
                )
                if faced.at_faces:
                    face_forces.annotate(checks, faced)
                faced_any = faced_any or faced.at_faces
            given = resolved_overwrites.get(member_id)
            if given:
                notes.extend(f"{member_id}: {note}" for note in given.notes())
        except DesignError as error:
            skip(str(error))
            continue
        strength = [c for c in checks if not c["flag"]]
        utilisation = max((c["utilisation"] for c in strength), default=0.0)
        if collect is not None:
            column_points = slender.points if isinstance(object_type, Column) else None
            collect["members"].append(
                {
                    "id": member_id,
                    "kind": "beam" if isinstance(object_type, Beam) else "column",
                    "type": type_id,
                    "object": object_type,
                    "section": section,
                    "pieces": own,
                    "turned": _turned(element, exact),
                    "fc": concrete.concrete.fc,
                    "fy": bars.steel.fy,
                    "es": es,
                    "aggregate": concrete.concrete.maxAggregate,
                    "checks": checks,
                    "points": column_points,
                }
            )
        entry = {
            "id": member_id,
            "kind": "beam" if isinstance(object_type, Beam) else "column",
            "type": type_id,
            "members": [p.id for p in own],
            "checks": checks,
            "utilisation": utilisation,
            "ok": all(c["ok"] for c in strength),
        }
        checked.append(entry)
        designed.append(
            seismic_detailing.Designed(
                member_id,
                entry["kind"],
                element,
                object_type,
                section,
                own,
                _turned(element, exact),
                entry,
                capacities if isinstance(object_type, Beam) else None,
            )
        )

    # Integrator glue: the earthquake-resistant detailing of BNBC Sec 8.3 (seismic_detailing).
    joints: list[dict[str, Any]] = []
    if scope is not None:
        found = seismic_detailing.apply(
            project,
            building,
            types,
            designed,
            combinations,
            extra,
            scope,
            settings,
            _profile_forces,
        )
        joints = found["joints"]
        notes += found["notes"]
    if collect is not None:
        collect["seismic"] = scope
        collect["joints"] = joints
        entries = {d.id: d for d in designed}
        for m in collect["members"]:
            d = entries.get(m["id"])
            if d is not None:
                m["checks"] = d.entry["checks"]
                m["detailing"] = d.entry.get("detailing")
                m["seismicContext"] = d.context
                m["element"] = d.element

    for type_id, (section, _) in {**beam_sections, **column_sections}.items():
        notes += [f"{type_id}: {note}" for note in section.notes]
    slabs_seen = _design_slabs(
        project,
        building,
        types,
        mats,
        pieces,
        shell_forces,
        combinations,
        checked,
        skipped,
        notes,
        collect["slabs"] if collect is not None else None,
    )
    # Integrator glue: stairs (saengine.design.stairs: hand methods, not in the analysis model)
    # and structural walls (saengine.design.wall_design: wall_forces' piers, walls' checks).
    from saengine.design import stairs as stair_design
    from saengine.design import wall_design

    stairs_found = stair_design.stair_report(
        building, types, mats, settings, collect, default_rebar=_default_rebar_id(objects, mats)
    )
    checked += stairs_found["elements"]
    skipped += stairs_found["skipped"]
    notes += stairs_found["notes"]
    walls_found = wall_design.design_walls(
        project,
        out_dir,
        _with_mep_openings(building, root),
        types,
        mats,
        settings,
        with_omega,
        resolved,
        scope,
        extra,
        combinations,
        collect,
    )
    checked += walls_found["elements"]
    skipped += walls_found["skipped"]
    notes += walls_found["notes"]
    # Integrator glue: lintels over the openings of masonry and partition walls
    # (saengine.design.lintels; hand design, not in the analysis model).
    from saengine.design import lintels as lintel_design
    from saengine.library.settings import derived

    try:
        wind = float(derived(settings).get("windSpeed") or 0.0)
    except (ValueError, KeyError, AttributeError, TypeError):
        wind = 0.0
    lintels_found = lintel_design.lintels_of(
        building, types, mats, settings, high_wind=wind * 3.6 > 200.0
    )
    checked += lintels_found["elements"]
    skipped += lintels_found["skipped"]
    notes += lintels_found["notes"]
    # Footings moved to Part 9 (saengine.substructure): this report designs the superstructure.
    notes.append(DESIGNED_IN_PART_9)
    failed = [e for e in checked if not e["ok"]]
    governing = max(checked, key=lambda e: e["utilisation"], default=None)
    code = settings.codes.concrete
    method = [line.format(code=code) for line in METHOD]
    if column_sections:
        method += slenderness_design.method(slender_options, context.model.lateral_cracked)
    if faced_any:
        method += face_forces.METHOD
    elif beam_sections or column_sections:
        notes.append(face_forces.JOINT_NOTE)
    if steel_seen:
        method += steel_design.METHOD
    if slabs_seen:
        method += slab.METHOD
    if walls_found["designed"]:
        method += wall_design.METHOD
    if lintels_found["elements"]:
        method += lintel_design.METHOD
    if slabs_seen and any(
        c["name"].startswith("Punching at") and c.get("shearReinforcement")
        for e in checked
        for c in e.get("checks", [])
    ):
        from saengine.design.punching import PUNCHING_METHOD

        method += PUNCHING_METHOD
    if stairs_found["elements"] or stairs_found["skipped"]:
        method += stair_design.METHOD
    if scope is not None and scope.get("detailingLevel"):
        method += seismic_detailing.METHOD
    failed_joints = [j for j in joints if not j["ok"]]
    return {
        "code": code,
        "method": method,
        "combinations": combinations,
        "elements": checked,
        "skipped": skipped,
        "seismic": scope,
        "joints": joints,
        "summary": {
            "checked": len(checked),
            "passed": len(checked) - len(failed),
            "failed": len(failed),
            "skipped": len(skipped),
            "maxUtilisation": governing["utilisation"] if governing else None,
            "governing": governing["id"] if governing else None,
            "joints": {"checked": len(joints), "failed": len(failed_joints)},
            "seismicChecksFailed": sum(
                1 for c in (scope or {}).get("checks", []) if not c["ok"] and not c["flag"]
            ),
        },
        "notes": notes,
        "stability": slenderness_design.storey_rows(
            context.storeys, combinations, slender_options.sway_magnifier
        ),
    }


def _face_forces_file(out_dir: str | Path) -> dict[str, Any] | None:
    """The results' face forces (``face-forces.json``, :mod:`saengine.fem.end_zones`), written
    from the model's ``faces.json`` and the results when missing or older than the results;
    None when the model has no support face offsets."""
    from saengine.design.face_forces import read_face_forces
    from saengine.fem import end_zones

    out = Path(out_dir)
    model_path = out.with_suffix(".osmodel")
    faces = model_path.parent / end_zones.FACES_FILE
    manifest = out / "manifest.json"
    if not faces.is_file() or not manifest.is_file():
        return None
    target = out / end_zones.FACE_FORCES_FILE
    # The temperature case's fixed-end forces (beside the model) are part of the face forces.
    from saengine.fem.thermal import SIDE_FILE

    thermal = model_path.with_name(SIDE_FILE)
    try:
        sources = [manifest, faces, *([thermal] if thermal.is_file() else [])]
        fresh = target.is_file() and target.stat().st_mtime >= max(
            p.stat().st_mtime for p in sources
        )
        if not fresh:
            end_zones.write_face_forces(model_path, out)
    except (OSError, ValueError, KeyError) as error:
        _SEISMIC_PROBLEMS.setdefault(f"faces:{out}", str(error))
        return None
    return read_face_forces(out)


def _with_mep_openings(building: BuildingModel, root: Path) -> BuildingModel:
    """The building with the openings 07 MEP cut into the analysis model (as
    :func:`saengine.fem.derive.derive_fem` derived it), for the walls' piers."""
    path = root / "07 MEP" / "mep.json"
    if not path.is_file():
        return building
    try:
        from saengine.library.mep import MepModel
        from saengine.mep.loads import with_mep_openings

        mep = MepModel.model_validate_json(path.read_text(encoding="utf-8"))
        return with_mep_openings(building, mep)[0]
    except (OSError, ValueError):
        return building


def _default_rebar_id(objects: ObjectLibrary, mats: dict[str, Any]) -> str | None:
    """The reinforcement material the object types use most (for stairs without bars)."""
    counts: dict[str, int] = {}
    for o in objects.objects:
        reinforcement = getattr(o, "reinforcement", None)
        if reinforcement is not None:
            counts[reinforcement.material] = counts.get(reinforcement.material, 0) + 1
    if counts:
        return max(counts, key=lambda m: counts[m])
    return None


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
    collect: list[dict[str, Any]] | None = None,
) -> bool:
    """Checks the slabs of the building model (see :mod:`saengine.design.slab`), adding them to
    ``checked`` or ``skipped`` (and what they were checked from to ``collect``, see
    :func:`design`). True when the building has slabs."""
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
        # Integrator glue: the type's punching studs or stirrups (saengine.design.punching).
        context.punching = getattr(object_type, "punchingReinforcement", None)
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
        if collect is not None:
            collect.append(
                {
                    "id": slab_id,
                    "type": type_id,
                    "object": object_type,
                    "context": context,
                    "fc": fc,
                    "fy": fy,
                    "es": es,
                    "checks": checks,
                }
            )
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
    project: dict[str, Any],
    out_dir: str | Path,
    settings: ProjectSettings,
    extra: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, list[_Piece]], list[str], dict[int, list[np.ndarray]]]:
    """The combinations formed, each member's pieces with their section forces per combination,
    notes on what could not be formed, and each shell's forces per combination (one row of
    N11 N22 N12 M11 M22 M12 Q13 Q23 per integration point, shell axes, N/m and N·m/m).

    ``extra``: when given, filled with ``"factors"`` (each formed combination's ``{case:
    factor}``), ``"lateralDisplacements"`` (per combination the node displacements of its
    lateral cases, ``{node: (Ux .. Rz)}`` in m, rad) and ``"shellSway"`` (per shell id and
    combination the forces of its lateral cases, rows as the shells')."""
    from opensees_studio.services.result_store import load_manifest, load_results
    from opensees_studio.services.results import StaticResults

    from saengine.fem.combinations import combination_factors
    from saengine.fem.display import _case_loads, _code, _elements, _last, element_section_forces
    from saengine.fem.thermal import (
        end_force_corrections,
        load_corrections,
        shell_force_corrections,
    )

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
    # The temperature case's fixed-end forces, added back to its members (saengine.fem.thermal).
    thermal = load_corrections(Path(out_dir).with_suffix(".osmodel"))
    displacements: dict[str, dict[int, np.ndarray]] = {}
    for entry in manifest["cases"]:
        results = load_results(entry, out_dir)
        if not isinstance(results, StaticResults):
            continue
        code = _code(entry["case_name"])
        if extra is not None and slenderness_design.is_lateral(code):
            displacements[code] = {
                int(n): np.asarray(rows[-1], dtype=float)[:6]
                for n, rows in results.node_disp.items()
                if rows is not None and len(rows)
            }
        reached = float(results.load_factors[-1]) if len(results.load_factors) else 1.0
        loads = _case_loads(project, int(entry["case_id"]))
        frame_add = end_force_corrections(thermal, code)
        shell_add = shell_force_corrections(thermal, code)
        shell_case[code] = {
            i: _shell_rows(results.shell_forces.get(i)) + reached * shell_add.get(i, 0.0)
            for i in shell_ids
        }
        by_case[code] = {
            e.id: element_section_forces(
                e,
                _last(results.element_forces, e.id, 12) + reached * frame_add.get(e.id, 0.0),
                reached * loads.get(e.id, np.zeros(3)),
            )
            for e in elements
        }

    names: list[str] = []
    factors_of: list[dict[str, float]] = []
    notes: list[str] = []
    for combination in settings.combinations:
        factors = combination_factors(combination, set(by_case))
        missing = [case for case in factors if case not in by_case]
        if missing:
            notes.append(
                f"{combination.name}: not checked, case {', '.join(missing)} has no results"
            )
            continue
        names.append(combination.name)
        factors_of.append(factors)
    lateral = [
        {c: f for c, f in factors.items() if slenderness_design.is_lateral(c)}
        for factors in factors_of
    ]
    sustained = [
        {c: f for c, f in factors.items() if c in slenderness_design.SUSTAINED_CASES}
        for factors in factors_of
    ]
    if extra is not None:
        extra["factors"] = factors_of
        extra["lateralDisplacements"] = [
            _combined_displacements(displacements, part) for part in lateral
        ]

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
                sway=[_part(by_case, e.id, part) for part in lateral],
                sustained=[_part(by_case, e.id, part) for part in sustained],
            )
        )

    # Shells: N11 ... Q23 at each integration point of the last step, per combination.
    shells: dict[int, list[np.ndarray]] = {}
    for i in shell_ids:
        shells[i] = [
            sum(f * shell_case[case][i] for case, f in factors.items()) for factors in factors_of
        ]
    if extra is not None:
        # The shells' lateral parts, for the walls' share of the storey shear (slenderness).
        extra["shellSway"] = {
            i: [
                sum(
                    (f * shell_case[case][i] for case, f in part.items() if case in shell_case),
                    np.zeros_like(shells[i][c]) if c < len(shells[i]) else np.zeros((1, 8)),
                )
                for c, part in enumerate(lateral)
            ]
            for i in shell_ids
        }
    return names, pieces, notes, shells


def _shells_of(project: dict[str, Any], ids: set[str]) -> set[int]:
    """The analysis shells of the building elements ``ids`` (named ``<id>`` or ``<id>#n``)."""
    return {
        int(e["id"])
        for e in project.get("elements", [])
        if e.get("type") == "Shell" and (e.get("name") or "").split("#")[0] in ids
    }


def _drop_combinations(
    pieces: dict[str, list[_Piece]],
    shells: dict[int, list[np.ndarray]],
    indices: list[int],
    keep: set[str],
    keep_shells: set[int] | None = None,
) -> None:
    """Zeroes the forces of the combinations ``indices`` in every member not in ``keep`` and in
    every shell not in ``keep_shells``, in place (the combination lists stay aligned with the
    names)."""
    for member_id, own in pieces.items():
        if member_id in keep:
            continue
        for piece in own:
            for parts in (piece.forces, piece.sway, piece.sustained):
                if parts is None:
                    continue
                for c in indices:
                    if c < len(parts) and parts[c] is not None:
                        parts[c] = np.zeros_like(parts[c])
    for shell, rows in shells.items():
        if keep_shells and shell in keep_shells:
            continue
        for c in indices:
            if c < len(rows):
                rows[c] = np.zeros_like(rows[c])


def _spectrum_shell_sway(
    static: dict[str, Any], names: list[str], shells: dict[int, list[np.ndarray]]
) -> dict[int, list[np.ndarray]]:
    """The shells' lateral parts (``extra["shellSway"]`` of :func:`_demands`) for the
    combinations of :func:`saengine.fem.seismic_design.design_demands`: ``static`` holds what
    its static run gave (``names``, ``shells`` per combination, ``inner`` with its
    ``shellSway``). A combination kept as it was keeps its lateral part; a response spectrum
    pattern ``"<name> [<label>]"`` adds to its static lateral part the ± E it added to the
    forces (its rows less the static combination's rows), as the frames' sway is."""
    index = {name: i for i, name in enumerate(static["names"])}
    before = static["shells"]
    sway_before = static["inner"].get("shellSway", {})
    out: dict[int, list[np.ndarray]] = {}
    for shell_id, rows in shells.items():
        old = before.get(shell_id, [])
        old_sway = sway_before.get(shell_id, [])
        found = []
        for c, name in enumerate(names):
            i = index.get(name)
            if i is None and name.endswith("]") and " [" in name:
                i = index.get(name.rsplit(" [", 1)[0])
            if i is None or i >= len(old):
                found.append(np.zeros_like(rows[c]))
                continue
            lateral = old_sway[i] if i < len(old_sway) else np.zeros_like(rows[c])
            found.append(lateral + (rows[c] - old[i]))
        out[shell_id] = found
    return out


def _part(by_case: dict[str, dict[int, np.ndarray]], element: int, factors: dict) -> np.ndarray:
    """The section forces of an element under some cases of a combination (zeros if none)."""
    found = [f * by_case[case][element] for case, f in factors.items() if case in by_case]
    if found:
        return sum(found[1:], found[0])
    any_case = next(iter(by_case.values()), {})
    shape = any_case[element].shape if element in any_case else (0, 6)
    return np.zeros(shape)


def _combined_displacements(
    displacements: dict[str, dict[int, np.ndarray]], factors: dict[str, float]
) -> dict[int, np.ndarray]:
    """The node displacements of a combination's cases ``factors``."""
    result: dict[int, np.ndarray] = {}
    for case, f in factors.items():
        for node, value in displacements.get(case, {}).items():
            result[node] = result.get(node, np.zeros(6)) + f * value
    return result


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
        return {"P": -n, "Mx": up * my * 1e3, "Vy": vz, "My": mz * 1e3, "Vx": vy}
    return {"P": -n, "Mx": -up * mz * 1e3, "Vy": vy, "My": my * 1e3, "Vx": vz}


def _turned(element: Any, exact: bool = False) -> bool:
    """Whether the analysis swapped a column's section axes (the rule of
    :func:`saengine.fem.derive.analysed_turns`): ``exact`` when the model analyses columns at
    their own angle (its elements carry ``vecxz``, :func:`exact_rotation`)."""
    from saengine.fem.derive import analysed_turns

    rotation = getattr(element, "rotation", 0.0) or 0.0
    return analysed_turns(rotation, exact) % 2 == 1


def exact_rotation(project: dict[str, Any]) -> bool:
    """Whether the analysis model turns columns by their exact angle (``analysis.
    exactColumnRotation``): read from the model (an element with its own ``vecxz``), so the
    design follows the model that was analysed."""
    return any(e.get("vecxz") for e in project.get("elements", []))


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
    slender: slenderness_design.ColumnSlenderness | None = None,
) -> list[dict[str, Any]]:
    """Axial compression, axial force with biaxial bending and, with ``slender`` (the column's
    slenderness, :meth:`saengine.design.slender.SlenderContext.column`), its slenderness
    checks: the strength check then takes the demand points with the magnified moments."""
    axial = (-math.inf, None, "")
    governing: tuple[float, Any, str | None, str, float] | None = None
    if slender is not None:
        points = slender.points
    else:
        points = []
        for piece in pieces:
            for c, forces in enumerate(piece.forces):
                values = _profile_forces(piece, turned, forces)
                count = len(forces)
                for k in range(count):
                    points.append(
                        (
                            float(values["P"][k]),
                            abs(float(values["Mx"][k])),
                            abs(float(values["My"][k])),
                            combinations[c],
                            _where(piece, k, count),
                        )
                    )
    for pu, mux, muy, combination, where in points:
        if pu > axial[0]:
            axial = (pu, combination, where)
        result = surface.check(pu, mux, muy)
        if governing is None or result.utilisation > governing[0]:
            governing = (result.utilisation, result, combination, where, pu)
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
                result.mu / 1e6 if math.isfinite(result.mu) else 0.0,
                result.phi_mn / 1e6,
                "kN·m",
                combination,
                note,
                utilisation=utilisation,
            )
        )
    if slender is not None:
        checks += slender.checks
    return checks

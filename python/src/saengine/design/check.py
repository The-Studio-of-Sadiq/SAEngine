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

import bisect
import contextvars
import copy
import dataclasses
import itertools
import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design import column_shear, live_reduction, seismic_rules, slab, steel_design
from saengine.design import deflection as deflection_design
from saengine.design import slender as slenderness_design
from saengine.design import torsion as torsion_design
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
from saengine.library.materials import Category, MaterialLibrary, default_of
from saengine.library.objects import (
    Beam,
    Brace,
    Column,
    ObjectLibrary,
    RectangleProfile,
    Slab,
    Wall,
)
from saengine.library.settings import LoadCombination, ProjectSettings, code_basis

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
        "bars). Weak-axis bending and axial force in beams are not checked; shear is "
        "taken at every station, including the supports. The top of a beam is the face of its "
        "depth axis that points up."
    ),
    (
        "Beam torsion (BNBC 2020 Part 6 Sec 6.4.4): neglected below the threshold φTth; above "
        "it the section limit (Eq. 6.6.59), closed stirrups At/s with the shear's Av/s per "
        "outer leg, the longitudinal steel Al on top of the flexural steel the simultaneous "
        "moment needs, and the detailing of Sec 6.4.4.6. A beam whose end is free or which "
        "carries a cantilever slab is designed for the full Tu (equilibrium torsion); a beam "
        "framed at both ends for Tu reduced to at most φTcr (compatibility torsion, Sec "
        "6.4.4.2.2): the moments this releases are not redistributed to the adjoining members "
        "by SAEngine."
    ),
    (
        "Beam deflection (BNBC 2020 Part 6 Sec 6.2.5): each span between its supports, from the "
        "analysis's unfactored D + SD and L (Lr on the roof) deflections relative to the chord, "
        "scaled by the analysis E I over Ec Ie (Eq. 6.6.1, Ie at midspan, at the support of a "
        "cantilever; the rectangle without the slab flange, on the safe side), the long-term "
        "part λΔ = ξ/(1 + 50ρ') on D + SD and the sustained share of L; limits of Table 6.6.2. "
        "With partitions not likely to be damaged a beam at least as deep as Table 6.6.1 asks "
        "is not computed."
    ),
    (
        "Columns: axial force with biaxial bending, the capacity read from the φ-factored "
        "interaction surface at the demand's axial force in the direction of its moment vector; "
        "φPn,max = 0.80 φ P0 (tied) or 0.85 φ P0 (spiral). Column shear from the analysis "
        "along each profile axis, Vc with the simultaneous axial force (BNBC 2020 Part 6 Eqs. "
        "6.6.50, 6.6.54), the tie spacing limits of Sec 6.4.3.4 (the capacity-design shear of "
        "special and intermediate frames is checked with the seismic detailing)."
    ),
]


#: The unfactored gravity cases the deflection checks use.
SERVICE_CASES = ("D", "SD", "L", "Lr")


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
    #: Per combination, the part of ``forces`` from the floor live load cases (L, LP1, ...),
    #: for the live load reduction (:mod:`saengine.design.live_reduction`); None when not formed.
    live: list[np.ndarray] | None = None


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

_SHARED: contextvars.ContextVar[dict[Any, Any] | None] = contextvars.ContextVar(
    "shared_demands", default=None
)


class _ArrayDict(dict):  # type: ignore[type-arg]
    """A kept dict whose values are all read-only arrays or plain numbers and strings: copied
    flat (:func:`_shared_copy`)."""


class _ArrayList(list):  # type: ignore[type-arg]
    """A kept list whose items are all read-only arrays: copied flat."""


#: What a kept dict may hold and still be copied flat.
_FLAT = frozenset({np.ndarray, str, int, float, bool, type(None)})


def _shared_copy(value: Any) -> Any:
    """A copy of the demands :func:`shared_demands` keeps: new containers and pieces, the
    arrays shared and made read-only (the checks replace a combination's array, never write
    into one; a write would raise rather than change the other call's forces). Containers of
    arrays alone are marked when kept and copied flat when handed out (plain dict, list)."""
    if isinstance(value, np.ndarray):
        value.setflags(write=False)
        return value
    if isinstance(value, _ArrayDict):
        return dict(value)
    if isinstance(value, _ArrayList):
        return list(value)
    if isinstance(value, dict):
        if value and all(type(v) in _FLAT for v in value.values()):
            for v in value.values():
                if type(v) is np.ndarray:
                    v.setflags(write=False)
            return _ArrayDict(value)
        copied = {k: _shared_copy(v) for k, v in value.items()}
        if copied and all(type(v) is np.ndarray for v in copied.values()):
            return _ArrayDict(copied)
        return copied
    if isinstance(value, list):
        if value and all(type(v) is np.ndarray for v in value):
            # The common case (a piece's combinations): flagged in one pass, no recursion.
            for v in value:
                v.setflags(write=False)
            return _ArrayList(value)
        listed = [_shared_copy(v) for v in value]
        if listed and all(type(v) is np.ndarray for v in listed):
            return _ArrayList(listed)
        return listed
    if isinstance(value, tuple):
        return tuple(_shared_copy(v) for v in value)
    if isinstance(value, _Piece):
        piece = copy.copy(value)
        for f in dataclasses.fields(piece):
            setattr(piece, f.name, _shared_copy(getattr(value, f.name)))
        return piece
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return copy.deepcopy(value)


@contextmanager
def shared_demands() -> Iterator[None]:
    """Within it, :func:`design` calls on the same results folder and combinations work out the
    combined forces once (they do not depend on the bars: the design checks with assumed bars and
    the report without them, :mod:`saengine.pipeline.design_mode`). Only for calls between
    which the model and the results do not change; nested, the outer one is used."""
    if _SHARED.get() is not None:
        yield
        return
    token = _SHARED.set({})
    try:
        yield
    finally:
        _SHARED.reset(token)


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
    assumed: set[str] | None = None,
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

    ``assumed``: with ``collect``, the object types ``objects`` gives assumed bars
    (:func:`saengine.design.required.with_assumed_bars`). When they are all slab types,
    ``collect["plain"]`` gets the report :func:`design_report` makes without those bars (the
    slabs of those types skipped or noted as without reinforcement, everything else the same),
    so the design mode designs the members once for both; it is left out otherwise (beams,
    columns and walls without bars change the joints and the seismic detailing).

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
    # Integrator glue (0.0.45): the design wind load cases of BNBC 2020 Part 6 Figure 6.2.9
    # (Sec 2.4.11.3) and the live load arrangements of Sec 6.1.12.2, from the cases the model
    # has (saengine.fem.combinations).
    from saengine.fem.combinations import (
        model_cases,
        pattern_live_combinations,
        wind_case_combinations,
    )

    present = model_cases(project)
    formed = list(with_omega.combinations)
    pre_notes: list[str] = []
    by_wind = wind_case_combinations(formed, present)
    if by_wind is not None and len(by_wind) > len(formed):
        pre_notes.append(
            "wind: each one-direction wind combination is checked for the design wind load "
            "cases of BNBC 2020 Part 6 Figure 6.2.9 (Sec 2.4.11.3): Case 1, "
            + ("Case 2 (0.75 with the torsion e = ±0.15 B), " if {"WTX", "WTY"} <= present else "")
            + "Case 3 (0.75 in both directions)"
            + (", Case 4 (0.563 in both with both torsions)" if {"WTX", "WTY"} <= present else "")
        )
        formed = by_wind
    by_pattern = pattern_live_combinations(formed, present)
    if by_pattern is not None and len(by_pattern) > len(formed):
        count = len([c for c in present if c.startswith("LP") and c[2:].isdigit()])
        pre_notes.append(
            f"live load arrangements: each gravity combination with live load is also checked "
            f"with L on the {count} arrangements LP1-LP{count} (BNBC 2020 Part 6 Sec 6.1.12.2)"
        )
        formed = by_pattern
    if len(formed) != len(with_omega.combinations):
        with_omega = with_omega.model_copy(update={"combinations": formed})
    # The forces do not depend on the bars: design() calls within shared_demands() on the
    # same results and combinations (the checks with and without assumed bars) work them
    # out once.
    share = _SHARED.get()
    key = (
        (str(Path(out_dir).resolve()), with_omega.model_dump_json(), tuple(sorted(omega_elements)))
        if share is not None
        else None
    )
    if share is not None and key in share:
        combinations, pieces, notes, shell_forces, extra, static, with_omega = _shared_copy(
            share[key]
        )
    else:
        static: dict[str, Any] = {}
        if seismic_design.design_uses_spectrum(settings):

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
            combinations, pieces, notes, shell_forces = _demands(
                project, out_dir, with_omega, extra
            )
            if expanded is not None:
                notes.append(
                    "accidental torsion: each earthquake combination is checked with the eccentric "
                    "static cases EXP/EXN (EYP/EYN), the story masses shifted ±5 % across the force "
                    "(BNBC 2020 Part 6 Sec 2.5.7.6.2)"
                )
        if share is not None:
            share[key] = _shared_copy(
                (combinations, pieces, notes, shell_forces, extra, static, with_omega)
            )
    notes = pre_notes + notes
    service = extra.get("service") or (static.get("inner") or {}).get("service") or {}
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
    framing: _BeamFraming | None = None
    live_scope = live_reduction.LiveScope.of(settings)
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
            skip(NO_REINFORCEMENT)
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
        # Integrator glue (T9): the floor live load reduced by the member's influence area
        # (saengine.design.live_reduction, BNBC 2020 Part 6 Sec 2.3.13), or by its overwrite.
        live_row = None
        given_factor = (resolved_overwrites.get(member_id) or design_overwrites.Resolved()).get(
            "liveLoadReduction"
        )
        if given_factor is not None or settings.analysis.liveLoadReduction:
            if given_factor is not None:
                found_factor = (float(given_factor), f"given ({live_reduction.CLAUSE})")
            else:
                if isinstance(element, BeamElement):
                    framing = framing or _BeamFraming(building, types)
                found_factor = live_reduction.member_factor(
                    element,
                    "beam" if isinstance(object_type, Beam) else "column",
                    own,
                    service,
                    building,
                    live_scope,
                    framing if isinstance(element, BeamElement) else None,
                    float(getattr(object_type.profile, "xDim", 0.0) or 0.0),
                )
            if found_factor is not None:
                own = live_reduction.reduced(own, found_factor[0])
                live_row = _check(
                    "Live load reduction L / L0",
                    found_factor[0],
                    1.0,
                    "",
                    None,
                    found_factor[1],
                    flag=True,
                )
        joints_own = own
        torsion_found = None
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
                # Integrator glue (0.0.45): torsion (saengine.design.torsion) and deflection
                # (saengine.design.deflection) of beams of the building model.
                if isinstance(element, BeamElement):
                    framing = framing or _BeamFraming(building, types)
                    torsion_rows, torsion_found = _beam_torsion_checks(
                        element,
                        object_type,
                        section,
                        own,
                        combinations,
                        _turned(element, exact),
                        framing,
                        bars.steel.fy,
                    )
                    checks += torsion_rows
                    checks += _beam_deflection_checks(
                        element,
                        section,
                        joints_own,
                        _turned(element, exact),
                        framing,
                        project,
                        service,
                        settings,
                        slenderness_design.concrete_modulus(concrete),
                        bars.steel.fy,
                        notes,
                    )
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
                # Integrator glue (0.0.45): the shear of every column from the analysis forces
                # with the axial force's effect on Vc (saengine.design.column_shear).
                checks += column_shear.column_shear_checks(
                    section,
                    object_type.reinforcement.transverse,
                    _shear_points(own, combinations, _turned(element, exact)),
                )
                faced_any = faced_any or faced.at_faces
            if live_row is not None:
                checks.append(live_row)
            given = resolved_overwrites.get(member_id)
            if given:
                notes.extend(f"{member_id}: {note}" for note in given.notes())
        except DesignError as error:
            skip(str(error))
            continue
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
                    # The torsion design at the governing station (saengine.design.torsion), for
                    # the required steel and the proposal; None below the threshold.
                    "torsion": torsion_found,
                }
            )
        entry = {
            "id": member_id,
            "kind": "beam" if isinstance(object_type, Beam) else "column",
            "type": type_id,
            "members": [p.id for p in own],
            "checks": checks,
        }
        seismic_detailing.rate(entry)
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
    # The report without the assumed bars (see ``assumed``): the same up to the slabs.
    default_rebar = _default_rebar_id(objects, materials)
    plain = (
        _Plain(assumed, list(checked), list(skipped), list(notes))
        if collect is not None
        and assumed
        and all(isinstance(types.get(t), Slab) for t in assumed)
        and default_rebar == _default_rebar_id(objects, materials, without=assumed)
        else None
    )
    # Where the elements found after the slabs go: the report's lists, and the plain ones.
    sinks = [(checked, skipped, notes)]
    if plain is not None:
        sinks.append((plain.checked, plain.skipped, plain.notes))
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
        settings,
        plain,
    )
    # Integrator glue: stairs (saengine.design.stairs: hand methods, not in the analysis model)
    # and structural walls (saengine.design.wall_design: wall_forces' piers, walls' checks).
    from saengine.design import stairs as stair_design
    from saengine.design import wall_design

    stairs_found = stair_design.stair_report(
        building, types, mats, settings, collect, default_rebar=default_rebar
    )
    for into in sinks:
        into[0].extend(stairs_found["elements"])
        into[1].extend(stairs_found["skipped"])
        into[2].extend(stairs_found["notes"])
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
    for into in sinks:
        into[0].extend(walls_found["elements"])
        into[1].extend(walls_found["skipped"])
        into[2].extend(walls_found["notes"])
    # Integrator glue: lintels over the openings of masonry and partition walls
    # (saengine.design.lintels; hand design, not in the analysis model).
    from saengine.design import lintels as lintel_design
    from saengine.library.settings import derived

    try:
        wind = float(derived(settings).get("windSpeed") or 0.0)
    except (ValueError, KeyError, AttributeError, TypeError):
        wind = 0.0
    lintels_found = lintel_design.lintels_of(
        building,
        types,
        mats,
        settings,
        concrete=default_of(materials, Category.CONCRETE),
        steel=default_of(materials, Category.REBAR),
        high_wind=wind * 3.6 > 200.0,
    )
    for into in sinks:
        into[0].extend(lintels_found["elements"])
        into[1].extend(lintels_found["skipped"])
        into[2].extend(lintels_found["notes"])

    def assemble(
        checked: list[dict[str, Any]],
        skipped: list[dict[str, Any]],
        notes: list[str],
        slabs_seen: set[str],
    ) -> dict[str, Any]:
        return _assemble(
            settings,
            checked,
            skipped,
            notes,
            slabs_seen,
            combinations,
            scope,
            joints,
            bool(beam_sections or column_sections),
            bool(column_sections),
            faced_any,
            steel_seen,
            walls_found,
            lintels_found,
            stairs_found,
            context,
            slender_options,
        )

    # Integrator glue (T9): fire resistance by least sizes and covers
    # (saengine.design.fire_resistance; the ratings of BNBC 2020 Part 4).
    from saengine.design.fire_resistance import CLAUSE as FIRE_CLAUSE
    from saengine.design.fire_resistance import add_fire_checks

    for into in sinks:
        if add_fire_checks(into[0], types, settings):
            into[2].append(
                "fire resistance: the members' least sizes and covers checked for the ratings of "
                f"Project Settings (BNBC 2020 Part 4) by {FIRE_CLAUSE}"
            )
    # Integrator glue (T9): the columns' gravity load takedown (saengine.design.takedown).
    from saengine.design.takedown import takedown

    try:
        column_takedown = takedown(building, pieces, service)
    except (ValueError, KeyError, AttributeError, TypeError, IndexError) as error:
        column_takedown = {"lines": [], "cases": [], "note": f"not formed: {error}"}
    if plain is not None and collect is not None:
        collect["plain"] = assemble(plain.checked, plain.skipped, plain.notes, plain.seen)
        collect["plain"]["takedown"] = column_takedown
    result = assemble(checked, skipped, notes, slabs_seen)
    result["takedown"] = column_takedown
    return result


def _assemble(
    settings: ProjectSettings,
    checked: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    notes: list[str],
    slabs_seen: set[str],
    combinations: list[str],
    scope: dict[str, Any] | None,
    joints: list[dict[str, Any]],
    frames_seen: bool,
    columns_seen: bool,
    faced_any: bool,
    steel_seen: bool,
    walls_found: dict[str, Any],
    lintels_found: dict[str, Any],
    stairs_found: dict[str, Any],
    context: slenderness_design.SlenderContext,
    slender_options: slenderness_design.SlenderOptions,
) -> dict[str, Any]:
    """The report of :func:`design` from its elements, notes and what it designed."""
    from saengine.design import face_forces, seismic_detailing, wall_design
    from saengine.design import lintels as lintel_design
    from saengine.design import stairs as stair_design

    # Footings moved to Part 9 (saengine.substructure): this report designs the superstructure.
    notes.append(DESIGNED_IN_PART_9)
    failed = [e for e in checked if not e["ok"]]
    governing = max(checked, key=lambda e: e["utilisation"], default=None)
    code = code_basis(settings).concrete
    method = [line.format(code=code) for line in METHOD]
    if columns_seen:
        method += slenderness_design.method(slender_options, context.model.lateral_cracked)
    if faced_any:
        method += face_forces.METHOD
    elif frames_seen:
        notes.append(face_forces.JOINT_NOTE)
    if steel_seen:
        method += steel_design.METHOD
    if "shells" in slabs_seen:
        method += slab.METHOD
    if "coefficients" in slabs_seen:
        method.append(slab.COEFFICIENT_METHOD)
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
    # The building's own seismic checks (the system permitted in the category, its height,
    # the bar grades: seismic_rules), each one check of the totals.
    seismic_checks = [c for c in (scope or {}).get("checks", []) if not c["flag"]]
    failed_seismic = [c for c in seismic_checks if not c["ok"]]
    not_permitted = [c for c in failed_seismic if c["name"].startswith("System permitted")]
    if not_permitted:
        # First in the notes: the design is not valid under a system the category forbids,
        # whatever the members show (P1 of the usability walk).
        notes.insert(
            0,
            f"{not_permitted[0]['note']}. Change the seismic system in 2 Project Settings "
            "(a special moment frame in Category D): R, Ω0, Cd and the member detailing then "
            "follow it.",
        )
    return {
        "code": code,
        "method": method,
        "combinations": combinations,
        "elements": checked,
        "skipped": skipped,
        "seismic": scope,
        "joints": joints,
        # The totals count the beam-column joints and the building's seismic checks too (X4 of
        # the usability walk: "17 pass, 1 fail" while every joint failed); "elements" keeps the
        # members' own counts.
        "summary": {
            "checked": len(checked) + len(joints) + len(seismic_checks),
            "passed": len(checked)
            - len(failed)
            + len(joints)
            - len(failed_joints)
            + len(seismic_checks)
            - len(failed_seismic),
            "failed": len(failed) + len(failed_joints) + len(failed_seismic),
            "elements": {
                "checked": len(checked),
                "passed": len(checked) - len(failed),
                "failed": len(failed),
            },
            "skipped": len(skipped),
            # The object types not checked for want of bars (an imported model's): Design
            # Reinforcement proposes bars for them (X29 of the usability walk).
            "noBars": sorted({s["type"] for s in skipped if s.get("reason") == NO_REINFORCEMENT}),
            "maxUtilisation": governing["utilisation"] if governing else None,
            "governing": governing["id"] if governing else None,
            # The check that sets it: a strength check, unless a detailing check fails (rate).
            "governingCheck": governing.get("governingCheck") if governing else None,
            "joints": {"checked": len(joints), "failed": len(failed_joints)},
            "seismicChecks": len(seismic_checks),
            "seismicChecksFailed": len(failed_seismic),
            "counts": design_counts(checked, skipped, joints, seismic_checks),
        },
        "notes": notes,
        "stability": slenderness_design.storey_rows(
            context.storeys, combinations, slender_options.sway_magnifier
        ),
    }


def design_counts(
    checked: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    joints: list[dict[str, Any]],
    building: list[dict[str, Any]],
) -> dict[str, Any]:
    """The one count of a design run every surface shows (N-X8 of usability walk 2: the
    proposal, the FEM view, Run All and the report each counted differently). Members, joints
    and the building's own checks are counted apart, never added together::

        {"members": {"total", "checked", "passed", "failed", "notChecked",
                     "byKind": {kind: {"total", "checked", "passed", "failed", "notChecked"}}},
         "joints": {"checked", "passed", "failed"},
         "building": {"checked", "passed", "failed"},
         "notChecked": {"noBars", "other"}}

    ``kind``: "beam", "column", "slab", "wall", "staircase", the steel kinds; a member is one
    designed element (a beam or column member, a slab panel, a wall, a staircase), whatever its
    analysis elements; ``notChecked`` the skipped ones (``noBars``: for want of bars, which
    Design Reinforcement proposes; ``other``: any other reason, in the skipped list)."""

    def tally(items: list[dict[str, Any]]) -> dict[str, int]:
        failed = sum(1 for i in items if not i["ok"])
        return {"checked": len(items), "passed": len(items) - failed, "failed": failed}

    by_kind: dict[str, dict[str, int]] = {}
    for element in checked:
        row = by_kind.setdefault(
            element["kind"], {"total": 0, "checked": 0, "passed": 0, "failed": 0, "notChecked": 0}
        )
        row["total"] += 1
        row["checked"] += 1
        row["passed" if element["ok"] else "failed"] += 1
    for element in skipped:
        row = by_kind.setdefault(
            element["kind"], {"total": 0, "checked": 0, "passed": 0, "failed": 0, "notChecked": 0}
        )
        row["total"] += 1
        row["notChecked"] += 1
    members = tally(checked)
    no_bars = sum(1 for s in skipped if s.get("reason") == NO_REINFORCEMENT)
    return {
        "members": {
            "total": len(checked) + len(skipped),
            **members,
            "notChecked": len(skipped),
            "byKind": by_kind,
        },
        "joints": tally(joints),
        "building": tally(building),
        "notChecked": {"noBars": no_bars, "other": len(skipped) - no_bars},
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


def _default_rebar_id(
    objects: ObjectLibrary, materials: MaterialLibrary, without: set[str] | None = None
) -> str | None:
    """The reinforcement material the object types use most (for stairs without bars), the
    types ``without`` left out; else the project's (``MaterialLibrary.default_rebar``)."""
    counts: dict[str, int] = {}
    for o in objects.objects:
        if without and o.id in without:
            continue
        reinforcement = getattr(o, "reinforcement", None)
        if reinforcement is not None:
            counts[reinforcement.material] = counts.get(reinforcement.material, 0) + 1
    if counts:
        return max(counts, key=lambda m: counts[m])
    return default_of(materials, Category.REBAR)


# ─────────────────────────────────────── slabs ───────────────────────────────────────

#: Why a slab of a type without bars is not checked (also the members': ``summary.noBars``).
NO_REINFORCEMENT = "no reinforcement"
#: The note of a slab without bars that is not analysed as shells.
SLAB_NOT_DESIGNED = "{}: slab not designed (no reinforcement, not analysed as shells)"


@dataclass
class _Plain:
    """The elements and notes of :func:`design`'s report without the assumed bars of the slab
    types ``assumed``, kept beside the design's own (:func:`_design_slabs`)."""

    assumed: set[str]
    checked: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    notes: list[str]
    #: :func:`_design_slabs`' answer for these slabs.
    seen: set[str] = field(default_factory=set)

    def take(
        self, start: tuple[int, int, int], checked: list[Any], skipped: list[Any], notes: list[Any]
    ) -> None:
        """What the design added since ``start`` (its lengths), the same here."""
        self.checked += checked[start[0] :]
        self.skipped += skipped[start[1] :]
        self.notes += notes[start[2] :]

    def without_bars(self, slab_id: str, type_id: str, analysed: bool, concrete: Any) -> None:
        """What :func:`_design_slabs` adds for a slab of an assumed type without its bars."""
        if not analysed:
            self.notes.append(SLAB_NOT_DESIGNED.format(slab_id))
            return
        reason = (
            "not a concrete slab"
            if concrete is None or concrete.category != Category.CONCRETE or not concrete.concrete
            else NO_REINFORCEMENT
        )
        self.skipped.append({"id": slab_id, "kind": "slab", "type": type_id, "reason": reason})


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
    settings: ProjectSettings | None = None,
    plain: _Plain | None = None,
) -> set[str]:
    """Checks the slabs of the building model (see :mod:`saengine.design.slab`), adding them to
    ``checked`` or ``skipped`` (and what they were checked from to ``collect``, see
    :func:`design`). True when the building has slabs. Slabs not analysed as shells (slabs as
    loads to beams) are designed by BNBC's coefficient methods from their own loads (with
    ``settings``: its area loads and combinations; :func:`saengine.design.slab.
    coefficient_design`). ``plain``: given, filled the same, the slabs of its assumed types
    as without their bars."""
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
        return set()

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
                float(getattr(profile, "yDim", 0.0) or 0.0),
            )
        )

    supports_at = _line_supports(building, types, [c[4] for c in candidates])
    elements_by_id = {e.id: e for e in building.elements}
    stories = [float(s.elevation) for s in building.stories]
    top_level = max(stories) if stories else math.inf
    coefficient_seen = shells_seen = False
    # Where the slab before began adding to the lists, for ``plain``.
    start: tuple[int, int, int] | None = None

    for slab_id, type_id, outline, axes, level in candidates:
        object_type = types.get(type_id)

        def skip(reason: str, slab_id: str = slab_id, type_id: str = type_id) -> None:
            skipped.append({"id": slab_id, "kind": "slab", "type": type_id, "reason": reason})

        own = shells_of.get(slab_id, [])
        if plain is not None:
            if start is not None:
                plain.take(start, checked, skipped, notes)
            start = None
            if type_id in plain.assumed:
                plain.without_bars(slab_id, type_id, bool(own), mats.get(object_type.material))
            else:
                start = (len(checked), len(skipped), len(notes))
        if not isinstance(object_type, Slab):
            skip(f"unknown slab type '{type_id}'")
            continue
        if not own and object_type.reinforcement is None:
            notes.append(SLAB_NOT_DESIGNED.format(slab_id))
            continue
        if not own and settings is None:
            skip("not analysed as shells: set the analysis's slabs to shells to design it")
            continue
        concrete = mats.get(object_type.material)
        if concrete is None or concrete.category != Category.CONCRETE or not concrete.concrete:
            skip("not a concrete slab")
            continue
        reinforcement = object_type.reinforcement
        if reinforcement is None:
            skip(NO_REINFORCEMENT)
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

        if not own and settings is not None:
            # Integrator glue (0.0.45): a slab on beams (not in the analysis model) designed by
            # the coefficient methods from its own loads (saengine.design.slab).
            found = _coefficient_slab(
                slab_id,
                type_id,
                object_type,
                elements_by_id.get(slab_id),
                outline,
                axes,
                level,
                top_level,
                concrete,
                fc,
                fy,
                es,
                settings,
                supports_at.get(round(level), []),
                [
                    other
                    for other_id, _, other, _, other_level in candidates
                    if other_id != slab_id and abs(other_level - level) <= 1
                ],
                beams_at.get(round(level), []),
                notes,
            )
            if isinstance(found, str):
                skip(found)
                continue
            entry, collected = found
            checked.append(entry)
            if collect is not None:
                collect.append(collected)
            coefficient_seen = True
            if plain is not None and type_id not in plain.assumed:
                plain.seen.add("coefficients")
            continue

        shells_seen = True
        if plain is not None and type_id not in plain.assumed:
            plain.seen.add("shells")
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
    if plain is not None and start is not None:
        plain.take(start, checked, skipped, notes)
    return ({"shells"} if shells_seen else set()) | (
        {"coefficients"} if coefficient_seen else set()
    )


def _coefficient_slab(
    slab_id: str,
    type_id: str,
    object_type: Slab,
    element: Any,
    outline: list[tuple[float, float]],
    axes: Any,
    level: float,
    top_level: float,
    concrete: Any,
    fc: float,
    fy: float,
    es: float,
    settings: ProjectSettings,
    supports: list[slab.LineSupport],
    neighbours: list[list[tuple[float, float]]],
    beams: list[slab.EdgeBeam],
    notes: list[str],
) -> tuple[dict[str, Any], dict[str, Any]] | str:
    """A slab on beams by the coefficient methods (:func:`saengine.design.slab.
    coefficient_design`): (its checked entry, what it was checked from) or the reason it is
    not designed. Its loads as the analysis model's (saengine.fem.derive): self-weight (times
    the weight modifier), finishes and partitions of its area load, its live load (the roof's
    live load on the top level)."""
    from saengine.library.modifiers import resolve_modifiers

    if axes is None:
        return "not a horizontal slab (inclined areas are not designed yet)"
    roof = level >= top_level - 1.0
    area_loads = {a.id: a for a in settings.areaLoads}
    load_id = getattr(element, "areaLoad", None) or (
        settings.roofLoad if roof else settings.floorLoad
    )
    area_load = area_loads.get(load_id) if load_id else None
    density = concrete.mechanical.density or 0.0
    weight = resolve_modifiers(element, object_type).get("weight", (1.0, ""))[0]
    self_weight = density * 9.80665 * object_type.thickness * 1e-3 / 1e3 * weight  # kN/m²
    dead = self_weight + ((area_load.finish + area_load.partitions) if area_load else 0.0)
    live = area_load.live if area_load else 0.0
    context = slab.SlabContext(boundary=outline, axes=axes, supports=supports)
    ec = concrete.mechanical.E or 4700 * math.sqrt(fc)
    try:
        context.thickness = slab.minimum_thickness(
            outline, axes, object_type.system, object_type.thickness, fy, ec, neighbours, beams
        )
    except (ValueError, ZeroDivisionError) as error:
        notes.append(f"{slab_id}: minimum thickness not checked: {error}")
    try:
        design = slab.coefficient_design(
            object_type.system,
            object_type.thickness,
            object_type.reinforcement,
            fc,
            fy,
            es,
            dead,
            live,
            slab.gravity_combinations(settings.combinations, roof),
            context,
            neighbours,
            beams,
            ec=ec,
        )
    except ValueError as error:
        return str(error)
    strength = [c for c in design.checks if not c["flag"]]
    notes.extend(f"{slab_id}: {note}" for note in context.notes)
    entry = {
        "id": slab_id,
        "kind": "slab",
        "type": type_id,
        "members": [],
        "checks": design.checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "strips": [],
        "method": design.method,
    }
    collected = {
        "id": slab_id,
        "type": type_id,
        "object": object_type,
        "context": context,
        "fc": fc,
        "fy": fy,
        "es": es,
        "checks": design.checks,
        "coefficients": design,
    }
    return entry, collected


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
            kind = "beam"
        elif isinstance(element, WallElement) and isinstance(support_type, Wall):
            if not support_type.structural:
                continue
            levels = [at for at in slab_levels if element.bottom + 1 < at < element.top + 1]
            width = float(support_type.thickness)
            kind = "wall"
        else:
            continue
        for at in dict.fromkeys(round(level) for level in levels):
            supports_at.setdefault(at, []).append(
                slab.LineSupport(
                    element.id,
                    (float(element.start[0]), float(element.start[1])),
                    (float(element.end[0]), float(element.end[1])),
                    width,
                    kind,
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

    from saengine.design.live_reduction import is_live_case
    from saengine.fem.combinations import combination_factors
    from saengine.fem.display import (
        _case_loads,
        _code,
        _elements,
        _last,
        element_section_forces,
        element_section_forces_many,
    )
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
        if extra is not None and (slenderness_design.is_lateral(code) or code in SERVICE_CASES):
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
        ends = [
            _last(results.element_forces, e.id, 12) + reached * frame_add.get(e.id, 0.0)
            for e in elements
        ]
        spans = [reached * loads.get(e.id, np.zeros(3)) for e in elements]
        if elements and all(e.length > 0 for e in elements):
            # All the elements at once (element_section_forces, the same arithmetic).
            many = element_section_forces_many(
                np.array([e.length for e in elements], dtype=float),
                np.array(ends, dtype=float).reshape(len(elements), 12),
                np.array(spans, dtype=float).reshape(len(elements), 3),
            )
            by_case[code] = {e.id: many[k] for k, e in enumerate(elements)}
        else:
            by_case[code] = {
                e.id: element_section_forces(e, end, span)
                for e, end, span in zip(elements, ends, spans, strict=True)
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
    live = [{c: f for c, f in factors.items() if is_live_case(c)} for factors in factors_of]
    if extra is not None:
        extra["factors"] = factors_of
        stacks = _displacement_stacks(displacements)
        extra["lateralDisplacements"] = [
            _combined_displacements(displacements, part, stacks) for part in lateral
        ]
        # The unfactored gravity cases, for the deflection checks (saengine.design.deflection).
        extra["service"] = {
            "forces": {c: by_case[c] for c in SERVICE_CASES if c in by_case},
            "displacements": {c: displacements[c] for c in SERVICE_CASES if c in displacements},
        }

    # Each combination of all the elements of one shape at once: the same sums element by
    # element, in the same order (sum over the factors), on stacked arrays.
    forces_of = _combined_stacks(by_case, [e.id for e in elements], factors_of)
    sway_of = _combined_stacks(by_case, [e.id for e in elements], lateral, parts=True)
    sustained_of = _combined_stacks(by_case, [e.id for e in elements], sustained, parts=True)
    live_of = _combined_stacks(by_case, [e.id for e in elements], live, parts=True)
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
                forces=forces_of[e.id],
                start=a,
                end=b,
                sway=sway_of[e.id],
                sustained=sustained_of[e.id],
                live=live_of[e.id],
            )
        )

    # Shells: N11 ... Q23 at each integration point of the last step, per combination.
    shells: dict[int, list[np.ndarray]] = _combined_stacks(shell_case, shell_ids, factors_of)
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


def _combined_stacks(
    by_case: dict[str, dict[int, np.ndarray]],
    ids: list[int],
    factors_of: list[dict[str, float]],
    parts: bool = False,
) -> dict[int, list[Any]]:
    """Per id its forces under each combination's ``factors``: ``sum(f * by_case[case][id])``
    over them, or with ``parts`` :func:`_part`'s sum (the first term to start, zeros for
    none). The ids whose arrays agree in shape and type in every case are stacked and worked
    out together, element by element the same operations in the same order; the rest one by
    one."""
    out: dict[int, list[Any]] = {}
    groups: dict[tuple[Any, ...], list[int]] = {}
    cases = list(by_case.values())
    for i in ids:
        first = cases[0].get(i) if cases else None
        key = (first.shape, first.dtype) if isinstance(first, np.ndarray) else None
        if key is not None and all(
            isinstance(c.get(i), np.ndarray) and (c[i].shape, c[i].dtype) == key for c in cases
        ):
            groups.setdefault(key, []).append(i)
        else:
            out[i] = [
                _part(by_case, i, factors)
                if parts
                else sum(f * by_case[case][i] for case, f in factors.items())
                for factors in factors_of
            ]
    for (shape, dtype), members in groups.items():
        stacked: dict[str, np.ndarray] = {}

        def stack(
            case: str, members: list[int] = members, stacked: dict[str, np.ndarray] = stacked
        ) -> np.ndarray:
            if case not in stacked:
                stacked[case] = np.stack([by_case[case][i] for i in members])
            return stacked[case]

        rows: list[list[Any]] = [[] for _ in members]
        for factors in factors_of:
            if parts:
                found = [f * stack(case) for case, f in factors.items() if case in by_case]
                total: Any = sum(found[1:], found[0]) if found else np.zeros((len(members), *shape))
            else:
                total = sum(f * stack(case) for case, f in factors.items())
            for k, row in enumerate(rows):
                row.append(total[k] if isinstance(total, np.ndarray) else total)
        out.update(zip(members, rows, strict=True))
    return out


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
            for parts in (piece.forces, piece.sway, piece.sustained, piece.live):
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


def _displacement_stacks(
    displacements: dict[str, dict[int, np.ndarray]],
) -> dict[str, tuple[tuple[int, ...], np.ndarray]]:
    """Per case its nodes and their displacements stacked (n, 6), for
    :func:`_combined_displacements`; cases with other than six values per node left out."""
    out: dict[str, tuple[tuple[int, ...], np.ndarray]] = {}
    for case, values in displacements.items():
        rows = list(values.values())
        if rows and all(np.shape(v) == (6,) for v in rows):
            out[case] = (tuple(values), np.array(rows, dtype=float))
    return out


def _combined_displacements(
    displacements: dict[str, dict[int, np.ndarray]],
    factors: dict[str, float],
    stacks: dict[str, tuple[tuple[int, ...], np.ndarray]] | None = None,
) -> dict[int, np.ndarray]:
    """The node displacements of a combination's cases ``factors``. ``stacks``:
    :func:`_displacement_stacks` of ``displacements``; where the cases share their nodes they
    are added up on it, node by node the same sums in the same order."""
    present = [case for case in factors if case in displacements]
    if stacks and present and all(case in stacks for case in present):
        nodes = stacks[present[0]][0]
        if all(stacks[case][0] == nodes for case in present):
            total = np.zeros((len(nodes), 6))
            for case in present:
                total = total + factors[case] * stacks[case][1]
            return dict(zip(nodes, total, strict=True))
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
    n, vy, vz, my, mz = (forces[..., i] for i in (0, 1, 2, 4, 5))
    rise = float(piece.axes[2 if along_z else 1][2])
    up = -1.0 if rise < -1e-9 else 1.0
    if along_z:
        return {"P": -n, "Mx": up * my * 1e3, "Vy": vz, "My": mz * 1e3, "Vx": vy}
    return {"P": -n, "Mx": -up * mz * 1e3, "Vy": vy, "My": my * 1e3, "Vx": vz}


def _profile_blocks(
    piece: _Piece, turned: bool
) -> list[tuple[int, np.ndarray, dict[str, np.ndarray]]]:
    """:func:`_profile_forces` of the piece's combinations in blocks: ``(first combination,
    forces, values)`` with a leading combination axis, all of them in one block when their
    stations agree (one call rather than one per combination), else one block each. Blocks
    without stations are left out."""
    parts = piece.forces
    if not parts:
        return []
    shape = np.shape(parts[0])
    if len(shape) == 2 and shape[0] and all(np.shape(f) == shape for f in parts):
        stacked = np.stack([np.asarray(f, dtype=float) for f in parts])
        return [(0, stacked, _profile_forces(piece, turned, stacked))]
    blocks = []
    for c, forces in enumerate(parts):
        if len(forces):
            one = np.asarray(forces, dtype=float)[None]
            blocks.append((c, one, _profile_forces(piece, turned, one)))
    return blocks


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
    peaks = {"sag": (0.0, None, ""), "hog": (0.0, None, ""), "shear": (0.0, None, "")}
    for piece in pieces:
        for first, _, values in _profile_blocks(piece, turned):
            count = values["Mx"].shape[1]
            # The first station of each peak (combination by combination, station by
            # station), as a scan finds it.
            for peak, rows in (
                ("sag", -values["Mx"]),
                ("hog", values["Mx"]),
                ("shear", np.abs(values["Vy"])),
            ):
                c, k = divmod(int(np.argmax(rows)), count)
                value = float(rows[c, k])
                if value > peaks[peak][0]:
                    peaks[peak] = (value, combinations[first + c], _where(piece, k, count))
    sag, hog, shear_demand = peaks["sag"], peaks["hog"], peaks["shear"]
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
    for pu, _mux, _muy, combination, where in points:
        if pu > axial[0]:
            axial = (pu, combination, where)
    if points:
        # All the points' utilisations at once, then the governing one (the first of equals)
        # checked for its details.
        utilisations = surface.utilisations([p[:3] for p in points])
        g = int(np.argmax(utilisations))
        pu, mux, muy, combination, where = points[g]
        result = surface.check(pu, mux, muy)
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


# ───────────────────── integrator glue (0.0.45): column shear, beam torsion, deflection ─────────────────────


def _shear_points(
    pieces: list[_Piece], combinations: list[str], turned: bool
) -> column_shear.ShearPoints:
    """Every station's (Pu [N, compression positive], Vx, Vy [N, along the profile's x and y],
    combination, where) of a column, for :func:`saengine.design.column_shear.
    column_shear_checks`, on arrays (the labels made for the points reported)."""
    pu, vx, vy, blocks = [], [], [], []
    start = 0
    for piece in pieces:
        for c, forces in enumerate(piece.forces):
            values = _profile_forces(piece, turned, forces)
            count = len(forces)
            pu.append(np.asarray(values["P"], dtype=float).reshape(-1)[:count])
            vx.append(np.asarray(values["Vx"], dtype=float).reshape(-1)[:count])
            vy.append(np.asarray(values["Vy"], dtype=float).reshape(-1)[:count])
            blocks.append((start, piece, c, count))
            start += count
    starts = [b[0] for b in blocks]

    def label(i: int) -> tuple[str | None, str]:
        first, piece, c, count = blocks[bisect.bisect_right(starts, i) - 1]
        return combinations[c], _where(piece, i - first, count)

    def joined(parts: list[np.ndarray]) -> np.ndarray:
        return np.concatenate(parts) if parts else np.zeros(0)

    return column_shear.ShearPoints(joined(pu), joined(vx), joined(vy), label)


#: Plan tolerance [mm] of the framing found from the building model (a point on a line).
_ON_LINE = 1.0


class _BeamFraming:
    """How the beams of a building model are held, from the model itself [mm]: the columns
    and structural walls along a beam (its supports), the beams its ends meet, the slabs beside
    it. For the torsion kind and the deflection spans of :func:`design`."""

    def __init__(self, building: BuildingModel, types: dict[str, Any]) -> None:
        self.columns: list[tuple[np.ndarray, float, float, float]] = []
        self.walls: list[tuple[np.ndarray, np.ndarray, float, float, float]] = []
        self.beams: list[tuple[str, np.ndarray, np.ndarray, float]] = []
        self.slabs: list[tuple[Any, float, float]] = []
        self.supports: list[tuple[np.ndarray, np.ndarray, float, float]] = []
        stories = [float(s.elevation) for s in building.stories]
        self.top = max(stories) if stories else math.inf
        for e in building.elements:
            object_type = types.get(e.type)
            profile = getattr(object_type, "profile", None)
            if isinstance(e, ColumnElement):
                if isinstance(profile, RectangleProfile):
                    reach = max(profile.xDim, profile.yDim) / 2
                elif profile is not None and getattr(profile, "radius", None):
                    reach = float(profile.radius)
                else:
                    reach = 0.0
                self.columns.append(
                    (np.array(e.position, dtype=float), float(e.bottom), float(e.top), reach)
                )
            elif isinstance(e, WallElement) and getattr(object_type, "structural", False):
                self.walls.append(
                    (
                        np.array(e.start, dtype=float),
                        np.array(e.end, dtype=float),
                        float(e.bottom),
                        float(e.top),
                        float(getattr(object_type, "thickness", 0.0) or 0.0) / 2,
                    )
                )
            elif isinstance(e, BeamElement):
                self.beams.append(
                    (
                        e.id,
                        np.array(e.start, dtype=float),
                        np.array(e.end, dtype=float),
                        float(e.elevation),
                    )
                )
        from shapely.geometry import Polygon

        for e in building.elements:
            object_type = types.get(e.type)
            if isinstance(e, SlabElement) and isinstance(object_type, Slab):
                polygon = Polygon([(float(x), float(y)) for x, y in e.boundary])
                if polygon.is_valid and polygon.area > 0:
                    self.slabs.append((polygon, float(object_type.thickness), float(e.elevation)))
        # Lines that hold a slab's edge: beams, structural walls.
        for _, a, c, z in self.beams:
            self.supports.append((a, c, z, z))
        for a, c, bottom, top, _ in self.walls:
            self.supports.append((a, c, bottom, top))

    @staticmethod
    def _station(point: np.ndarray, a: np.ndarray, c: np.ndarray) -> tuple[float, float]:
        """(t along a-c from a [0, 1], distance from the line [mm])."""
        axis = c - a
        length = float(np.linalg.norm(axis))
        t = float((point - a) @ axis) / length**2
        foot = a + t * axis
        return t, float(np.linalg.norm(point - foot))

    def support_stations(self, element: BeamElement) -> list[float]:
        """The stations t [0, 1] along a beam where a column or a structural wall holds it (a
        column within its half-size of the line, at the beam's level; one within its half-size
        of an end holds that end). Supports closer than their half-sizes are one."""
        a, c = np.array(element.start, dtype=float), np.array(element.end, dtype=float)
        length = float(np.linalg.norm(c - a))
        z = float(element.elevation)
        found: list[tuple[float, float]] = []  # (t, half-size [mm])
        for position, bottom, top, reach in self.columns:
            if not bottom - 1.0 <= z <= top + 1.0:
                continue
            t, off = self._station(position, a, c)
            margin = (reach + _ON_LINE) / length
            if off <= reach + _ON_LINE and -margin <= t <= 1 + margin:
                if t <= margin:
                    t = 0.0
                elif t >= 1 - margin:
                    t = 1.0
                found.append((t, reach))
        for w0, w1, bottom, top, half in self.walls:
            if not bottom - 1.0 <= z <= top + 1.0:
                continue
            for end in (a, c):
                t_wall, off = self._station(end, w0, w1)
                if off <= half + _ON_LINE and -1e-6 <= t_wall <= 1 + 1e-6:
                    found.append((0.0 if end is a else 1.0, half))
            # A wall crossing the beam.
            hit = _segment_cross(a, c, w0, w1)
            if hit is not None:
                found.append((hit, half))
        merged: list[tuple[float, float]] = []
        for t, reach in sorted(found):
            if merged and (t - merged[-1][0]) * length <= merged[-1][1] + reach + _ON_LINE:
                # One support: keep an end station where there is one.
                if t in (0.0, 1.0):
                    merged[-1] = (t, max(reach, merged[-1][1]))
                continue
            merged.append((t, reach))
        return [t for t, _ in merged]

    def end_held(self, element: BeamElement, end: int) -> bool:
        """Whether a beam's end (0: start, 1: end) is held: a column or wall there, or another
        beam it frames into (the end on that beam's line, not a collinear continuation)."""
        stations = self.support_stations(element)
        a, c = np.array(element.start, dtype=float), np.array(element.end, dtype=float)
        length = float(np.linalg.norm(c - a))
        if any(abs(t - end) * length <= 1.0 + _ON_LINE for t in stations):
            return True
        point = c if end else a
        direction = (c - a) / length
        for other_id, b0, b1, z in self.beams:
            if other_id == element.id or abs(z - float(element.elevation)) > 1.0:
                continue
            t, off = self._station(point, b0, b1)
            if off > _ON_LINE or not -1e-6 <= t <= 1 + 1e-6:
                continue
            other = (b1 - b0) / float(np.linalg.norm(b1 - b0))
            if abs(float(direction @ other)) < 0.999:
                return True
        return False

    def continues(self, element: BeamElement, end: int) -> bool:
        """Whether a collinear beam continues beyond a beam's end (a continuous end)."""
        a, c = np.array(element.start, dtype=float), np.array(element.end, dtype=float)
        point = c if end else a
        direction = (c - a) / float(np.linalg.norm(c - a)) * (1 if end else -1)
        for other_id, b0, b1, z in self.beams:
            if other_id == element.id or abs(z - float(element.elevation)) > 1.0:
                continue
            for near, far in ((b0, b1), (b1, b0)):
                if float(np.linalg.norm(near - point)) <= _ON_LINE:
                    away = (far - near) / float(np.linalg.norm(far - near))
                    if float(direction @ away) > 0.999:
                        return True
        return False

    def slab_beside(self, element: BeamElement, width: float) -> tuple[float, int]:
        """(thickness [mm], sides 0-2) of the slabs cast with a beam: those at its level beside
        its middle."""
        from shapely.geometry import Point

        a, c = np.array(element.start, dtype=float), np.array(element.end, dtype=float)
        axis = (c - a) / float(np.linalg.norm(c - a))
        normal = np.array([-axis[1], axis[0]])
        middle = (a + c) / 2
        thickness, sides = 0.0, 0
        for sign in (1, -1):
            probe = Point(*(middle + sign * normal * (width / 2 + 50.0)))
            beside = [
                t
                for polygon, t, z in self.slabs
                if abs(z - float(element.elevation)) <= 1.0 and polygon.covers(probe)
            ]
            if beside:
                sides += 1
                thickness = max(thickness, *beside)
        return thickness, sides

    def carries_cantilever(self, element: BeamElement, width: float) -> bool:
        """Whether a slab beside a beam is a cantilever from it: an edge of it parallel to the
        beam has no beam or wall under it (less than 95 % held) and neither has any edge across
        the beam (held on an edge across, the slab spans to that support instead)."""
        from shapely.geometry import LineString, Point

        a, c = np.array(element.start, dtype=float), np.array(element.end, dtype=float)
        axis = (c - a) / float(np.linalg.norm(c - a))
        normal = np.array([-axis[1], axis[0]])
        middle = (a + c) / 2
        z0 = float(element.elevation)
        line = LineString([tuple(a), tuple(c)])

        def held(edge: Any) -> bool:
            covered = 0.0
            for s0, s1, bottom, top in self.supports:
                if not bottom - 1.0 <= z0 <= top + 1.0:
                    continue
                support = LineString([tuple(s0), tuple(s1)]).buffer(width / 2 + 50.0)
                covered += edge.intersection(support).length
            return covered >= 0.95 * edge.length

        for polygon, _, z in self.slabs:
            if abs(z - z0) > 1.0:
                continue
            if not any(
                polygon.covers(Point(*(middle + sign * normal * (width / 2 + 50.0))))
                for sign in (1, -1)
            ):
                continue
            free_parallel, held_across = False, False
            for p, q in itertools.pairwise(list(polygon.exterior.coords)):
                edge = LineString([p, q])
                if edge.length <= 1.0 or edge.hausdorff_distance(line) <= width / 2 + _ON_LINE:
                    continue  # this beam's own edge
                along = np.array(q, dtype=float) - np.array(p, dtype=float)
                parallel = abs(float(along @ axis)) >= 0.985 * float(np.linalg.norm(along))
                if parallel and not held(edge):
                    free_parallel = True
                elif not parallel and held(edge):
                    held_across = True
            if free_parallel and not held_across:
                return True
        return False


def _segment_cross(a: np.ndarray, c: np.ndarray, p: np.ndarray, q: np.ndarray) -> float | None:
    """The station t (0, 1) along a-c where segment p-q crosses it, or None."""
    r, s = c - a, q - p
    denominator = float(r[0] * s[1] - r[1] * s[0])
    if abs(denominator) < 1e-9:
        return None
    t = float((p - a)[0] * s[1] - (p - a)[1] * s[0]) / denominator
    u = float((p - a)[0] * r[1] - (p - a)[1] * r[0]) / denominator
    if 0 < t < 1 and -1e-9 <= u <= 1 + 1e-9:
        return t
    return None


#: The torsion design is tried at this many stations of highest Tu (above half the threshold).
_TORSION_CANDIDATES = 24


def torsion_stations(
    points: list[tuple[float, float, float, float, str, str]],
    ts: Any,
    fc: float,
    kind: str,
    threshold: float,
    limit: int = _TORSION_CANDIDATES,
) -> list[tuple[float, float, float, float, str, str]]:
    """The stations (Tu, Vu, Mu, Nu, combination, where) worth designing for torsion: those
    of highest Tu, and those of highest combined stress of Eq. 6.6.59 with Tu as designed. A
    compatibility torsion is capped at φTcr, so at the stations above the cap Vu decides, and
    with many combinations (the response spectrum's sign patterns) the highest Tu alone can
    leave out the governing station. Stations below half the threshold are left out; with none
    above it, the one of highest Tu."""
    by_tu = sorted(points, key=lambda p: -p[0])
    bw_d = ts.b * ts.d
    torsion_share = ts.ph / (1.7 * ts.aoh**2)

    def screen(point: tuple[float, float, float, float, str, str]) -> float:
        tu = point[0]
        if kind == "compatibility":
            tu = min(tu, torsion_design.cracking_torsion(ts, fc, point[3]))
        return math.hypot(point[1] / bw_d, tu * torsion_share)

    above = [p for p in by_tu if p[0] > 0.5 * threshold]
    by_stress = sorted(above, key=lambda p: -screen(p))[:limit]
    return list(dict.fromkeys([*above[:limit], *by_stress])) or by_tu[:1]


def _torsion_candidates(
    pieces: list[_Piece],
    combinations: list[str],
    turned: bool,
    ts: Any,
    fc: float,
    kind: str,
    threshold: float,
    limit: int = _TORSION_CANDIDATES,
) -> list[tuple[float, float, float, float, str, str]]:
    """:func:`torsion_stations` of every station of ``pieces`` in every combination, the same
    stations in the same order, worked out on arrays: only the candidates become points."""
    columns: list[list[np.ndarray]] = [[], [], [], []]
    # Per block of combinations: piece, first combination, station count, first point.
    blocks: list[tuple[int, int, int, int]] = []
    size = 0
    for index, piece in enumerate(pieces):
        for first, forces, values in _profile_blocks(piece, turned):
            columns[0].append((np.abs(forces[..., 3]) * 1e3).ravel())  # N·m -> N·mm
            columns[1].append(np.abs(values["Vy"]).ravel())
            columns[2].append(values["Mx"].ravel())
            columns[3].append(values["P"].ravel())
            blocks.append((index, first, forces.shape[1], size))
            size += forces.shape[0] * forces.shape[1]
    if not size:
        return []
    tu, vu, mu, nu = (np.concatenate(column).astype(float) for column in columns)
    block_starts = np.array([start for *_, start in blocks])

    def point(i: int) -> tuple[float, float, float, float, str, str]:
        index, first, count, start = blocks[int(np.searchsorted(block_starts, i, "right")) - 1]
        c, k = divmod(i - start, count)
        where = _where(pieces[index], k, count)
        return (
            float(tu[i]),
            float(vu[i]),
            float(mu[i]),
            float(nu[i]),
            combinations[first + c],
            where,
        )

    by_tu = np.argsort(-tu, kind="stable")
    above = by_tu[tu[by_tu] > 0.5 * threshold]
    if not len(above):
        return [point(int(by_tu[0]))]
    bw_d = ts.b * ts.d
    torsion_share = ts.ph / (1.7 * ts.aoh**2)
    capped = tu[above]
    if kind == "compatibility":
        acp, pcp, _ = ts.outline()
        phi = torsion_design._phi_shear()
        root = torsion_design._root(fc)
        ratio = 1 + nu[above] / (0.33 * ts.gross_area * 1.0 * root)
        factor = np.where(nu[above] == 0, 1.0, np.sqrt(np.maximum(0.0, ratio)))
        capped = np.minimum(capped, 0.33 * phi * 1.0 * root * acp**2 / pcp * factor)
    # The stress screen of torsion_stations; np.hypot may differ from math.hypot in the last
    # bit, so the stations near the cut are ordered with math.hypot, as torsion_stations does.
    rough = np.hypot(vu[above] / bw_d, capped * torsion_share)
    if len(above) > limit:
        cut = np.partition(rough, len(rough) - limit)[len(rough) - limit]
        near = np.nonzero(rough >= cut * (1 - 1e-9))[0]
    else:
        near = np.arange(len(above))
    exact = [math.hypot(float(vu[above[j]]) / bw_d, float(capped[j]) * torsion_share) for j in near]
    by_stress = [int(above[near[j]]) for j in np.argsort(-np.array(exact), kind="stable")][:limit]
    chosen = [point(int(i)) for i in above[:limit]] + [point(i) for i in by_stress]
    return list(dict.fromkeys(chosen))


def _beam_torsion_checks(
    element: BeamElement,
    beam: Beam,
    section: RcSection,
    pieces: list[_Piece],
    combinations: list[str],
    turned: bool,
    framing: _BeamFraming,
    fy: float,
) -> tuple[list[dict[str, Any]], Any]:
    """The torsion rows of a beam (BNBC 2020 Part 6 Sec 6.4.4, :mod:`saengine.design.torsion`)
    at its governing station (below the threshold one reported-only row), and the torsion
    design there (:class:`saengine.design.torsion.TorsionDesign`; None when not required)."""
    from saengine.design.bars import singly_area

    try:
        rules = torsion_design.TorsionRules.from_pack()
    except (AttributeError, KeyError, TypeError):
        return [], None  # the code pack has no torsion group
    reinforcement = beam.reinforcement
    if reinforcement is None:
        return [], None
    width = section.width
    thickness, sides = framing.slab_beside(element, width)
    try:
        ts = torsion_design.TorsionSection.of(section, reinforcement.cover, thickness, sides)
        ts.core  # noqa: B018 - raises when the cover leaves no room
    except (DesignError, ValueError) as error:
        return [
            _check(
                "Torsion (Sec 6.4.4)", 0.0, 0.0, "kN·m", None, f"not checked: {error}", flag=True
            )
        ], None
    held = framing.end_held(element, 0) and framing.end_held(element, 1)
    kind, why = torsion_design.torsion_kind(held, framing.carries_cantilever(element, width))
    transverse = reinforcement.transverse
    stirrups = (
        (transverse.dia, transverse.legs, transverse.spacing)
        if transverse is not None and transverse.spacing
        else None
    )
    resistance = shear(
        section,
        transverse.dia if transverse else None,
        transverse.legs if transverse else 0,
        transverse.spacing if transverse else None,
    )
    fc = section.fc
    threshold = torsion_design.threshold_torsion(ts, fc)
    candidates = _torsion_candidates(pieces, combinations, turned, ts, fc, kind, threshold)
    if not candidates:
        return [], None
    best: tuple[float, Any, tuple[float, float, float, float, str, str]] | None = None
    # The station of the highest stress of Eq. 6.6.59: the section size is checked there (the
    # governing station, of the stirrups, can be another one).
    sized: tuple[float, Any, tuple[float, float, float, float, str, str]] | None = None
    for point in candidates:
        tu, vu, mu, nu, _, _ = point
        design = torsion_design.design_torsion(
            ts,
            tu,
            vu,
            fc,
            fy,
            fy,
            kind,
            nu=nu,
            vc=resistance.vc,
            rules=rules,
            spacing=stirrups[2] if stirrups else None,
        )
        if not design.required:
            ratio = design.tu_design / design.phi_tth if design.phi_tth else 0.0
        else:
            ratio = 1.0 + design.stress / design.stress_limit
            if stirrups is not None:
                dia, legs, spacing = stirrups
                av_s = torsion_design.shear_av_s(
                    vu, design.vc, ts.d, design.fyt, design.phi, rules.fy_max
                )
                ratio = max(
                    ratio, 1.0 + (design.at_s + av_s / legs) * spacing / (dia**2 * math.pi / 4)
                )
        if best is None or ratio > best[0]:
            best = (ratio, design, point)
        if design.required and (sized is None or design.stress > sized[0]):
            sized = (design.stress, design, point)
    assert best is not None
    _, design, (tu, vu, mu, _, combination, where) = best
    # The shear's Av/s at the governing station, for Required steel's per-leg At/s + Av/(n s).
    design = dataclasses.replace(
        design,
        av_s=torsion_design.shear_av_s(vu, design.vc, ts.d, design.fyt, design.phi, rules.fy_max),
    )
    hogging = mu > 0
    try:
        d = section.effective_depth(top=hogging)
    except DesignError:
        d = ts.d
    as_flexure = singly_area(abs(mu), width, d, fc, fy)
    if as_flexure is None:
        as_flexure = section.steel_area  # the concrete cannot carry the moment: no room for Al
    rows = torsion_design.torsion_checks(
        design,
        ts,
        vu,
        stirrups,
        section.steel_area,
        as_flexure,
        combination,
        where,
        bars=section.bars,
        rules=rules,
    )
    if design.required and sized is not None and sized[0] > design.stress:
        _, other, (_, other_vu, _, _, other_combination, other_where) = sized
        rows[0] = torsion_design.torsion_checks(
            other,
            ts,
            other_vu,
            stirrups,
            section.steel_area,
            as_flexure,
            other_combination,
            other_where,
            bars=section.bars,
            rules=rules,
        )[0]
    if rows:
        rows[0]["note"] = f"{why}; " + rows[0]["note"]
    return rows, (design if design.required else None)


def _beam_deflection_checks(
    element: BeamElement,
    section: RcSection,
    pieces: list[_Piece],
    turned: bool,
    framing: _BeamFraming,
    project: dict[str, Any],
    service: dict[str, Any],
    settings: ProjectSettings,
    ec: float,
    fy: float,
    notes: list[str],
) -> list[dict[str, Any]]:
    """The deflection rows of a beam (BNBC 2020 Part 6 Sec 6.2.5, Table 6.6.2,
    :mod:`saengine.design.deflection`): each span between the columns and walls holding it,
    and a free end as a cantilever."""
    mode = getattr(settings.analysis, "deflection", "sensitive") or "sensitive"
    if mode == "off" or not pieces:
        return []
    try:
        limits = deflection_design.DeflectionLimits.from_pack()
    except (AttributeError, KeyError, TypeError):
        return []  # the code pack has no deflection group
    forces = service.get("forces") or {}
    moved = service.get("displacements") or {}
    if "D" not in forces or "D" not in moved:
        return []
    roof = float(element.elevation) >= framing.top - 1.0
    live_cases = [c for c in ("L", "Lr") if c in forces and c in moved]
    sensitive = mode == "sensitive"
    sustained = float(getattr(settings.analysis, "sustainedLive", 0.25))
    a = np.array([*element.start, element.elevation], dtype=float) / 1e3
    c = np.array([*element.end, element.elevation], dtype=float) / 1e3
    axis = c - a
    length = float(np.linalg.norm(axis))
    nodes_of = {e["id"]: e.get("nodes", []) for e in project.get("elements", [])}
    sections = {s["id"]: s for s in project.get("sections", [])}
    section_of_element = {e["id"]: e.get("section_id") for e in project.get("elements", [])}
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}

    # (t along the beam, node) and per piece its stations between its nodes.
    stations: list[tuple[float, int, _Piece, int]] = []
    for piece in pieces:
        ids = nodes_of.get(piece.id) or []
        if len(ids) < 2:
            continue
        count = len(forces["D"].get(piece.id, ())) or 2
        for node, k in ((ids[0], 0), (ids[-1], count - 1)):
            t = float((coords[node] - a) @ axis) / length**2
            stations.append((t, node, piece, k))
    if not stations:
        return []
    stations.sort(key=lambda s: s[0])

    def uz(case: str, node: int) -> float:
        return float(moved.get(case, {}).get(node, np.zeros(6))[2]) * 1e3  # m -> mm

    def moment(case: str, piece: _Piece, k: int) -> float:
        rows = forces.get(case, {}).get(piece.id)
        if rows is None:
            return 0.0
        values = _profile_forces(piece, turned, np.asarray(rows, dtype=float))
        return float(values["Mx"][min(k, len(values["Mx"]) - 1)])  # N·mm, + hogging

    supports = framing.support_stations(element)
    spans: list[tuple[float, float, str]] = []  # (t0, t1, "span" | "start" | "end")
    if len(supports) >= 2:
        spans += [(t0, t1, "span") for t0, t1 in itertools.pairwise(supports)]
    for end in (0, 1):
        edge = (supports[0] if end == 0 else supports[-1]) if supports else None
        if (
            edge is not None
            and abs(edge - end) > 1e-3
            and not framing.end_held(element, end)
            and not framing.continues(element, end)
        ):
            spans.append((0.0, edge, "start") if end == 0 else (edge, 1.0, "end"))
    if not spans:
        # Held by beams only (a secondary beam): the span between its ends.
        if framing.end_held(element, 0) and framing.end_held(element, 1):
            spans = [(0.0, 1.0, "span")]
        else:
            return []
    rows: list[dict[str, Any]] = []
    h = section.depth
    for number, (t0, t1, kind) in enumerate(spans, start=1):
        span_mm = (t1 - t0) * length * 1e3
        if span_mm <= 0:
            continue
        cantilever = kind != "span"
        inside = [s for s in stations if t0 - 1e-6 <= s[0] <= t1 + 1e-6]
        if len(inside) < 2:
            continue
        where = f"{element.id}" + (f" span {number}" if len(spans) > 1 else "")
        if not sensitive:
            ends = int(t0 > 1e-3 or framing.continues(element, 0)) + int(
                t1 < 1 - 1e-3 or framing.continues(element, 1)
            )
            least = deflection_design.beam_minimum_depth(span_mm, ends, fy, cantilever, limits)
            if h >= least:
                rows.append(
                    _check(
                        "Deflection: depth exempts the calculation (Table 6.6.1)",
                        least,
                        h,
                        "mm",
                        "service",
                        f"h = {h:.0f} mm >= {least:.0f} mm for l = {span_mm:.0f} mm "
                        f"(partitions not likely to be damaged); {where}",
                        flag=True,
                    )
                )
                continue
        # Deflection of each node relative to the chord (a cantilever: the tip below the
        # support), D + SD and the live cases.
        dead_cases = [c for c in ("D", "SD") if c in moved]

        def relative(
            cases: list[str],
            t: float,
            node: int,
            inside: list[tuple[float, int, _Piece, int]] = inside,
            cantilever: bool = cantilever,
            kind: str = kind,
        ) -> float:
            first, last = inside[0], inside[-1]
            if cantilever:
                support = first if kind == "end" else last
                return sum(uz(cs, support[1]) - uz(cs, node) for cs in cases)
            share = (t - first[0]) / (last[0] - first[0]) if last[0] > first[0] else 0.0
            chord = sum((1 - share) * uz(cs, first[1]) + share * uz(cs, last[1]) for cs in cases)
            return chord - sum(uz(cs, node) for cs in cases)

        if cantilever:
            tip = inside[-1] if kind == "end" else inside[0]
            at = inside[0] if kind == "end" else inside[-1]  # the support: Ie there
            governing = tip
            m_station = at
        else:
            governing = max(inside, key=lambda s: relative(dead_cases + live_cases, s[0], s[1]))
            m_station = governing
        d_dead = relative(dead_cases, governing[0], governing[1])
        d_live = relative(live_cases, governing[0], governing[1]) if live_cases else 0.0
        _, _, piece, k = m_station
        m_dead = sum(moment(cs, piece, k) for cs in dead_cases)
        m_live = sum(moment(cs, piece, k) for cs in live_cases)
        if not cantilever:  # sagging at midspan
            m_dead, m_live = -m_dead, -m_live
        section_id = section_of_element.get(piece.id)
        props = sections.get(section_id, {})
        along_z = piece.depth_along_z != turned
        inertia = float(props.get("Iy" if along_z else "Iz", 0.0) or 0.0)
        ei = float(props.get("E", 0.0) or 0.0) * inertia * 1e6  # N·m² -> N·mm²
        if ei <= 0 or d_dead + d_live <= 0:
            continue
        try:
            stiffness = deflection_design.section_stiffness(section, ec, hogging=cantilever)
            result = deflection_design.span_deflection(
                span_mm,
                stiffness,
                section.fc,
                ec,
                ei,
                (max(m_dead, 0.0), d_dead),
                (max(m_live, 0.0), d_live),
                sustained,
                roof=roof,
                sensitive=sensitive,
                limits=limits,
            )
        except (DesignError, ValueError) as error:
            notes.append(f"{where}: deflection not checked: {error}")
            continue
        rows += deflection_design.deflection_checks(
            result,
            roof=roof,
            sensitive=sensitive,
            where=where + (" (cantilever)" if cantilever else ""),
            limits=limits,
        )
    return rows

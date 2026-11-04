"""P4: assessment and retrofit of existing buildings, by the code pack's ``existing`` table.

A project turns it on with ``analysis.existingBuilding`` (:class:`saengine.library.settings.
ExistingBuilding`); without it nothing here runs and every result is the new building's. The
pack's ``existing`` table (:class:`saengine.codes.existing_tables.ExistingTable`) gives every
value and picks the methods by id:

- **Knowledge** (:func:`knowledge`): the level the project chooses (or the pack's default) with
  its knowledge factor κ on the capacities and its confidence factor CF on the strengths, both
  overridable per project.
- **Strengths** (:func:`strengths`): per material of 03 Materials, from the project's tests
  (cores and tensile tests as they are; rebound and pulse velocity estimates only with their
  calibration to cores): the mean, the standard deviation and the lower bound mean - k·σ; a
  material without tests takes the specified strength times the pack's lower-bound factor, and
  the expected strength is the lower bound times the pack's expected factor. Each use (the
  analysis model, ductile capacities, brittle capacities) takes the value the pack names,
  divided by CF and the brittle partial factors where it says so.
- **Model state** (:func:`model_state`, called by :func:`saengine.fem.derive.derive_fem`): the
  analysis model of the existing building: its materials at the analysis strengths, the bars of
  corroded members reduced, weak concrete reduced, and by ``state``: as built (the retrofit's
  added members left out, no jackets) or retrofitted (jacketed members enlarged with their
  added bars and ties). Jacketed and corroded members get their own object types
  (``<type>.eb-<tags>``), which the pushover hinges read too (:func:`state_objects`).
- **Members** (:func:`members`): the RC beams and columns (rectangular or circular) and the
  steel I-shaped beams and columns of 06 BIM, as built and as retrofitted: jackets as
  monolithic members (the jacket's concrete over the whole section, the old bars where they
  are, the pack's monolithic factors), FRP by the pack's ``frp.method`` (``aci440``: confinement
  f'cc and the conforming detailing, shear Vf with the bond-reduced strain of U-wraps and two
  sides, flexural laminates with the debonding strain; ``en1998``: shear, and the confinement
  term of θum).
- **Section strength**: strain compatibility of the section with the rectangular stress block
  (the pack's α1 and β1 and εcu, as in the design) at the member's axial force, from the
  strengths of the use (no φ, no partial factors other than the pack's brittle divisors); the
  yield moment from a cracked elastic section at the first yield of the tension bars or
  concrete at 1.8 fc/Ec.
- **Linear procedure** (:func:`linear`), by ``linear.method``:
  ``mFactor``: the seismic forces of the run made the unreduced forces of each hazard level
  (× R/I × the level's spectrum scale × C1·C2·Cm for deformation-controlled actions, × R/I ×
  the scale × Cm/J for force-controlled ones), with QG = upper·(D + share·L) and lower·D;
  flexure m·κ·QCE ≥ QUD (m by the pack's tables from the members' variables), shear and axial
  force κ·QCL ≥ QUF; ``chordRotation``: the chord rotation θ = (M/My)·θy of the secant stiffness
  to yield against θy and the shares of θum, the shear against the cyclic shear strength.
- **Nonlinear procedure** (:func:`nonlinear`): the pushover hinges (:mod:`saengine.fem.hinges`)
  with κ on their limits, θum with the strengths over CF, and the pack's shear check.
- **Before and after**: each assessment is kept per model state (``08 FEM/existing-<state>.
  json``); the results pair a member's ratio as built with its ratio retrofitted (the other
  state's run when it has been run, else the other capacities with this run's demands, marked
  as such).

Units: N, mm, MPa inside the section checks; the analysis results in N, m.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

MPA = 1e6
#: The model states and their file beside the analysis model.
STATES = ("asBuilt", "retrofitted")
STATE_FILE = "existing-{state}.json"
#: The tag of the object types of an existing building's model state.
TAG = ".eb-"
#: Neutral-axis depths of a section's strength curve, as shares of its depth.
_DEPTHS = np.concatenate([np.geomspace(0.01, 0.1, 6), np.linspace(0.12, 1.5, 36), [2.0, 4.0]])
#: Strips across a section's depth.
_STRIPS = 60

SETTINGS_FILE = "02 Project Settings/project-settings.json"
MATERIALS_FILE = "03 Materials/materials.json"
OBJECTS_FILE = "04 Objects/objects.json"
BIM_FILE = "06 BIM/bim.json"


def table() -> Any | None:
    """The code pack's ``existing`` table; None when the pack in force has none."""
    pack = code_context.current()
    return pack.table("existing") if pack.has("existing") else None


def clause(key: str) -> str:
    """The pack's clause of ``key`` (its ``sources``), else its source."""
    found = table()
    if found is None:
        return ""
    return found.sources.get(key) or found.source


# ───────────────────────────────────── knowledge ─────────────────────────────────────


@dataclass(frozen=True)
class Knowledge:
    """The knowledge level in force with its factors."""

    id: str
    label: str
    kappa: float
    cf: float
    procedures: tuple[str, ...]
    note: str = ""


def knowledge(existing: Any, rule: Any) -> Knowledge:
    """The project's knowledge level (its id, else the pack's default; an unknown id: the
    default, with a note) and its κ and CF, the project's own values winning."""
    levels = {k.id: k for k in rule.knowledge}
    wanted = getattr(existing, "knowledgeLevel", None)
    level = levels.get(wanted or rule.defaultKnowledge) or levels[rule.defaultKnowledge]
    note = level.note
    if wanted and wanted not in levels:
        note = f"knowledge level '{wanted}' is not one of the code pack's; {level.id} is used"
    kappa = getattr(existing, "knowledgeFactor", None) or level.capacityFactor
    cf = getattr(existing, "confidenceFactor", None) or level.confidenceFactor
    return Knowledge(level.id, level.label or level.id, kappa, cf, tuple(level.procedures), note)


# ───────────────────────────────────── strengths ─────────────────────────────────────


def material_kind(material: Any) -> str | None:
    """ "concrete", "rebar", "steel" for the materials the assessment reads; else None."""
    category = getattr(getattr(material, "category", None), "value", None)
    if category == "concrete" and material.concrete is not None:
        return "concrete"
    if category in ("rebar", "steel") and material.steel is not None:
        return category
    return None


def _specified(material: Any) -> float:
    return float(
        material.concrete.fc if material_kind(material) == "concrete" else material.steel.fy
    )


@dataclass
class MaterialStrength:
    """The as-built strengths of one material [MPa]."""

    material: str
    kind: str
    specified: float
    tests: int
    mean: float | None
    std: float | None
    cov: float | None
    lower: float
    expected: float
    notes: list[str] = field(default_factory=list)

    def value(self, use: Any, cf: float) -> float:
        """The strength of a use (:class:`saengine.codes.existing_tables.StrengthUse`)."""
        found = {
            "expected": self.expected,
            "lowerBound": self.lower,
            "mean": self.mean if self.mean is not None else self.specified,
        }[use.value]
        if use.divideByConfidence:
            found /= cf
        return found / (use.concreteDivisor if self.kind == "concrete" else use.steelDivisor)

    def row(self) -> dict[str, Any]:
        return {
            "material": self.material,
            "kind": self.kind,
            "specified": self.specified,
            "tests": self.tests,
            "mean": self.mean,
            "std": self.std,
            "cov": self.cov,
            "lowerBound": self.lower,
            "expected": self.expected,
            "notes": self.notes,
        }


def statistics_of(values: list[float]) -> tuple[float, float, float]:
    """(mean, sample standard deviation, coefficient of variation) of test results; σ = 0 for a
    single result."""
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    return mean, std, std / mean if mean > 0 else 0.0


_TEST_KINDS = {"core": "concrete", "rebound": "concrete", "upv": "concrete", "tensile": "steel"}


def strengths(existing: Any, rule: Any, materials: Any) -> dict[str, MaterialStrength]:
    """The as-built strengths of every concrete, bar and steel material (see the module)."""
    s = rule.strengths
    found: dict[str, MaterialStrength] = {}
    tests = list(getattr(existing, "tests", []) or [])
    for material in materials.materials:
        kind = material_kind(material)
        if kind is None:
            continue
        notes: list[str] = []
        values: list[float] = []
        for test in tests:
            if test.material != material.id:
                continue
            family = _TEST_KINDS[test.kind]
            if (family == "concrete") != (kind == "concrete"):
                notes.append(f"{test.kind} tests do not apply to a {kind} material: left out")
                continue
            if test.kind in s.calibrated:
                values += [float(v) for v in test.values]
            elif test.calibration:
                values += [float(v) * test.calibration for v in test.values]
            else:
                notes.append(
                    f"{test.kind} estimates without a calibration to cores: shown, not used"
                )
        specified = _specified(material)
        lower_factor = s.lowerBoundFactors.get(kind, 1.0)
        expected_factor = s.expectedFactors.get(kind, 1.0)
        if values:
            mean, std, cov = statistics_of(values)
            lower = max(mean - s.lowerBoundSigma * std, 1e-3)
            expected = mean
            if s.covLimit is not None and cov > s.covLimit:
                notes.append(
                    f"coefficient of variation {cov:.2f} above {s.covLimit:g}: more tests are "
                    "asked for"
                )
            if len(values) < s.minTests:
                notes.append(f"{len(values)} test(s), fewer than {s.minTests}")
            found[material.id] = MaterialStrength(
                material.id, kind, specified, len(values), mean, std, cov, lower, expected, notes
            )
        else:
            lower = specified * lower_factor
            found[material.id] = MaterialStrength(
                material.id, kind, specified, 0, None, None, None, lower, lower * expected_factor,
                notes,
            )  # fmt: skip
    for test in tests:
        if test.material not in found:
            note = f"tests of '{test.material}': no such concrete, bar or steel material"
            found.setdefault("", MaterialStrength("", "", 0, 0, None, None, None, 0, 0, []))
            found[""].notes.append(note)
    return found


def _with_strength(material: Any, value: float) -> Any:
    """``material`` with its f'c (concrete) or fy (bars, steel) set to ``value`` [MPa]."""
    if material_kind(material) == "concrete":
        return material.model_copy(
            update={"concrete": material.concrete.model_copy(update={"fc": value})}
        )
    return material.model_copy(update={"steel": material.steel.model_copy(update={"fy": value})})


# ───────────────────────────────────── the model state ─────────────────────────────────────


def _measures(existing: Any, kind: str) -> list[Any]:
    return [m for m in getattr(existing, "retrofit", []) or [] if m.kind == kind]


def _condition_of(existing: Any) -> dict[str, tuple[int, Any]]:
    """Member or type id -> (index, condition): the first condition naming it."""
    out: dict[str, tuple[int, Any]] = {}
    for k, condition in enumerate(getattr(existing, "conditions", []) or []):
        for key in condition.members:
            out.setdefault(key, (k, condition))
    return out


def state_type_id(type_id: str, tags: list[str]) -> str:
    """The id of the model state's type of ``type_id`` with ``tags`` (an id of 04 Objects'
    pattern, at most 64 characters: hashed when longer)."""
    found = f"{type_id}{TAG}{'-'.join(tags)}"
    if len(found) <= 64:
        return found
    digest = hashlib.sha1(found.encode("utf-8")).hexdigest()[:12]
    return f"{type_id[: 64 - len(TAG) - 12]}{TAG}{digest}"


def _scaled_bars(reinforcement: Any, loss: float) -> Any:
    """``reinforcement`` with its bars' area reduced by ``loss`` (diameters × √(1 - loss))."""
    if loss <= 0:
        return reinforcement
    k = math.sqrt(1 - loss)
    groups = [g.model_copy(update={"dia": g.dia * k}) for g in reinforcement.longitudinal]
    ties = reinforcement.transverse
    if ties is not None:
        ties = ties.model_copy(update={"dia": ties.dia * k})
    return reinforcement.model_copy(update={"longitudinal": groups, "transverse": ties})


def _jacketed_profile(profile: Any, t: float) -> Any | None:
    from saengine.library.objects import CircleProfile, RectangleProfile

    if isinstance(profile, RectangleProfile):
        return profile.model_copy(
            update={"xDim": profile.xDim + 2 * t, "yDim": profile.yDim + 2 * t}
        )
    if isinstance(profile, CircleProfile):
        return profile.model_copy(update={"radius": profile.radius + t})
    return None


def _jacket_groups(jacket: Any, beam: bool) -> list[Any]:
    from saengine.library.objects import BarGroup

    if beam:
        top = jacket.bars // 2
        return [
            BarGroup(position="top", count=max(top, 1), dia=jacket.barDia),
            BarGroup(position="bottom", count=max(jacket.bars - top, 1), dia=jacket.barDia),
        ]
    return [BarGroup(position="perimeter", count=jacket.bars, dia=jacket.barDia)]


def _jacketed_type(base: Any, jacket: Any, new_id: str) -> Any | None:
    """The analysis type of a member of ``base`` jacketed by ``jacket``: the enlarged profile
    of the jacket's concrete, the old bars with the jacket's (placed together at the jacket's
    cover: the pushover's fibre section; the member checks place the old bars where they are)
    and the jacket's ties."""
    from saengine.library.objects import Transverse

    reinforcement = getattr(base, "reinforcement", None)
    profile = _jacketed_profile(getattr(base, "profile", None), jacket.thickness)
    if reinforcement is None or profile is None:
        return None
    beam = getattr(base, "kind", "") == "beam"
    ties = Transverse(
        type="stirrup" if beam else "tie",
        dia=jacket.tieDia,
        spacing=jacket.tieSpacing,
        legs=2,
    )
    new = reinforcement.model_copy(
        update={
            "material": jacket.rebar or reinforcement.material,
            "cover": jacket.cover,
            "longitudinal": [*reinforcement.longitudinal, *_jacket_groups(jacket, beam)],
            "transverse": ties,
        }
    )
    return base.model_copy(
        update={
            "id": new_id,
            "profile": profile,
            "material": jacket.concrete or base.material,
            "reinforcement": new,
        }
    )


@dataclass
class ModelState:
    """The existing building's model: what :func:`model_state` changed."""

    building: Any
    objects: Any
    materials: Any
    notes: list[str]
    removed: list[str]
    types: dict[str, str]  # member -> its state type id


def model_state(building: Any, objects: Any, materials: Any, settings: Any) -> ModelState:
    """The analysis model's inputs for the project's existing building (see the module); the
    inputs unchanged when the settings have none or the pack does not cover it."""
    existing = getattr(settings.analysis, "existingBuilding", None)
    same = ModelState(building, objects, materials, [], [], {})
    if existing is None:
        return same
    rule = table()
    if rule is None:
        same.notes.append(
            "existing building: the code pack does not cover the assessment of existing "
            "buildings; the model is analysed as entered"
        )
        return same
    know = knowledge(existing, rule)
    found = strengths(existing, rule, materials)
    use = rule.strengths.analysis
    mats = []
    changed = []
    for m in materials.materials:
        ms = found.get(m.id)
        if ms is not None and ms.kind:
            value = ms.value(use, know.cf)
            if abs(value - ms.specified) > 1e-9:
                changed.append(f"{m.id} {ms.specified:g} → {value:.1f} MPa")
            m = _with_strength(m, value)
        mats.append(m)
    by_id = {m.id: m for m in mats}
    notes = []
    if changed:
        notes.append(
            f"existing building: the materials at their {use.value} strengths ("
            + ", ".join(changed)
            + ")"
        )
    added = {mid for measure in _measures(existing, "added") for mid in measure.members}
    removed: list[str] = []
    elements = list(building.elements)
    additions = building.additions
    if existing.state == "asBuilt" and added:
        removed = sorted(e.id for e in elements if e.id in added)
        elements = [e for e in elements if e.id not in added]
        inclined = [m for m in additions.members if m.id in added]
        if inclined:
            removed += sorted(m.id for m in inclined)
            additions = additions.model_copy(
                update={"members": [m for m in additions.members if m.id not in added]}
            )
        if removed:
            notes.append(
                "existing building, as built: the retrofit's added members are left out ("
                + ", ".join(removed)
                + ")"
            )
    jackets: dict[str, Any] = {}
    if existing.state == "retrofitted":
        for jacket in _measures(existing, "rcJacket"):
            for mid in jacket.members:
                jackets.setdefault(mid, jacket)
    conditions = _condition_of(existing)
    types = {o.id: o for o in objects.objects}
    new_types: dict[str, Any] = {}
    member_types: dict[str, str] = {}
    out = []
    for e in elements:
        cond = conditions.get(e.id) or conditions.get(e.type)
        jacket = jackets.get(e.id)
        base = types.get(e.type)
        if (cond is None and jacket is None) or base is None:
            out.append(e)
            continue
        if getattr(base, "reinforcement", None) is None or not hasattr(base, "profile"):
            out.append(e)
            continue
        tags = ([f"c{cond[0] + 1}"] if cond else []) + ([jacket.id] if jacket else [])
        new_id = state_type_id(e.type, tags)
        if new_id not in new_types:
            made = _state_type(base, cond[1] if cond else None, jacket, new_id, by_id, cond)
            if made is None:
                out.append(e)
                continue
            new_types[new_id] = made
        member_types[e.id] = new_id
        out.append(e.model_copy(update={"type": new_id}))
    if new_types:
        notes.append(
            f"existing building: {len(member_types)} member(s) with their condition or jacket "
            f"as own types ({', '.join(sorted(new_types))})"
        )
    if jackets:
        notes.append(
            "existing building, retrofitted: jacketed members enlarged with the jacket's bars and "
            "ties; in the pushover's fibre sections the old bars lie with the jacket's at its "
            "cover (SAEngine practice), the member checks place them where they are"
        )
    if _measures(existing, "frp"):
        notes.append(
            "existing building: FRP wraps and laminates leave the analysis model's stiffness as "
            "it is; they enter the member checks"
        )
    new_building = building.model_copy(update={"elements": out, "additions": additions})
    new_objects = objects.model_copy(update={"objects": [*objects.objects, *new_types.values()]})
    new_materials = materials.model_copy(update={"materials": list(by_id.values())})
    return ModelState(new_building, new_objects, new_materials, notes, removed, member_types)


def _state_type(
    base: Any,
    condition: Any,
    jacket: Any,
    new_id: str,
    materials: dict[str, Any],
    cond: tuple[int, Any] | None,
) -> Any | None:
    """The state type of a member of ``base`` with its ``condition`` and ``jacket``; weak
    concrete gets its own material (added to ``materials``)."""
    made = base.model_copy(update={"id": new_id})
    if condition is not None:
        made = made.model_copy(
            update={"reinforcement": _scaled_bars(made.reinforcement, condition.barLoss)}
        )
        if condition.concreteFactor < 1:
            concrete = materials.get(made.material)
            if concrete is not None and material_kind(concrete) == "concrete":
                weak_id = state_type_id(concrete.id, [f"c{cond[0] + 1}"]) if cond else concrete.id
                if weak_id not in materials:
                    materials[weak_id] = _with_strength(
                        concrete.model_copy(update={"id": weak_id}),
                        concrete.concrete.fc * condition.concreteFactor,
                    )
                made = made.model_copy(update={"material": weak_id})
    if jacket is not None:
        made = _jacketed_type(made, jacket, new_id)
    return made


def _read(root: Path, relative: str, model: Any) -> Any | None:
    try:
        return model.model_validate_json((root / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def state_objects(root: Any, objects: Any) -> Any:
    """``objects`` with the model state's own types of the project at ``root`` (for readers of
    the analysis model's sections by type id, such as the pushover hinges); ``objects`` itself
    when the project has no existing building or its files cannot be read."""
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.settings import ProjectSettings

    try:
        root = Path(root)
        with code_context.project(root):
            settings = _read(root, SETTINGS_FILE, ProjectSettings)
            if settings is None or getattr(settings.analysis, "existingBuilding", None) is None:
                return objects
            building = _read(root, BIM_FILE, BuildingModel)
            materials = _read(root, MATERIALS_FILE, MaterialLibrary)
            if building is None or materials is None:
                return objects
            with code_context.using(code_context.pack_for(settings, root)):
                return model_state(building, objects, materials, settings).objects
    except Exception:  # noqa: BLE001 - the readers go on with the types as entered
        return objects


# ───────────────────────────────────── members ─────────────────────────────────────


@dataclass
class Frp:
    """The FRP of a member worked out for its checks."""

    measure: Any
    eps_fu: float  # design rupture strain CE·εfu*
    vf: float = 0.0  # N, shear contribution (× ψf)
    fcc: float | None = None  # MPa, confined strength (aci440)
    confined: bool = False  # the confinement counts (fl/f'c at least the pack's)
    rotation: float = 0.0  # en1998: the term added to the confinement exponent of θum
    laminate: tuple[float, float, float, float] | None = None  # y face [mm], area, Ef, εfd
    notes: list[str] = field(default_factory=list)


@dataclass
class Section:
    """The as-built (or retrofitted) section of an RC member [mm, mm², MPa]."""

    rc: Any  # saengine.design.rc.RcSection (its bars at their places, strengths unused)
    b: float  # width along the profile's x
    h: float  # depth along the profile's y
    circle: bool
    concrete: str  # material ids
    rebar: str
    tie_area: float  # one leg [mm²]
    tie_legs: int
    tie_legs_x: int
    tie_spacing: float  # in the hinge region [mm]
    cover: float
    bar_dia: float
    concrete_factor: float = 1.0
    jacket: Any = None
    frp: list[Frp] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def area(self) -> float:
        return float(self.rc.gross_area)

    @property
    def steel_area(self) -> float:
        return float(self.rc.steel_area)


@dataclass
class Member:
    """An RC or steel beam or column of the existing building."""

    id: str
    kind: str  # "beam", "column"
    component: str  # rcBeam, rcColumn, steelBeam, steelColumn
    type_id: str
    turned: bool
    before: Section | None
    after: Section | None
    steel: Any = None  # steel: the object type
    measures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _section(object_type: Any, materials: dict[str, Any], condition: Any) -> Section:
    """The as-built :class:`Section` of a member of ``object_type`` with its ``condition``."""
    from saengine.design import rc
    from saengine.library.objects import CircleProfile

    reinforcement = object_type.reinforcement
    concrete = materials[object_type.material]
    rebar = materials[reinforcement.material]
    loss = condition.barLoss if condition is not None else 0.0
    section = rc.section_of(
        object_type.profile, reinforcement, concrete.concrete.fc, rebar.steel.fy
    )
    if loss > 0:
        bars = tuple(replace(bar, area=bar.area * (1 - loss)) for bar in section.bars)
        section = replace(section, bars=bars)
    ties = reinforcement.transverse
    tie_area = rc.bar_area(ties.dia) * (1 - loss) if ties else 0.0
    spacing = (ties.zone.spacing if ties and ties.zone else ties.spacing) if ties else 0.0
    circle = isinstance(object_type.profile, CircleProfile)
    return Section(
        rc=section,
        b=section.width,
        h=section.depth,
        circle=circle,
        concrete=concrete.id,
        rebar=rebar.id,
        tie_area=tie_area,
        tie_legs=ties.legs if ties else 0,
        tie_legs_x=(ties.legsX or ties.legs) if ties else 0,
        tie_spacing=spacing,
        cover=reinforcement.cover,
        bar_dia=max((g.dia for g in reinforcement.longitudinal), default=0.0),
        concrete_factor=condition.concreteFactor if condition is not None else 1.0,
    )


def _jacketed(before: Section, jacket: Any, object_type: Any, materials: dict[str, Any]) -> Section:
    """The monolithic section of ``before`` in ``jacket``: the enlarged profile of the jacket's
    concrete, the old bars where they are and the jacket's bars at its cover, its ties."""
    from saengine.design import rc
    from saengine.library.objects import LinearReinforcement, Transverse

    profile = _jacketed_profile(object_type.profile, jacket.thickness)
    rebar_id = jacket.rebar or before.rebar
    beam = getattr(object_type, "kind", "") == "beam"
    added = LinearReinforcement(
        material=rebar_id,
        cover=jacket.cover,
        longitudinal=_jacket_groups(jacket, beam),
        transverse=Transverse(type="tie", dia=jacket.tieDia, spacing=jacket.tieSpacing, legs=2),
    )
    rebar = materials[rebar_id]
    new = rc.section_of(profile, added, before.rc.fc, rebar.steel.fy)
    section = replace(new, bars=(*before.rc.bars, *new.bars))
    return Section(
        rc=section,
        b=section.width,
        h=section.depth,
        circle=before.circle,
        concrete=jacket.concrete or before.concrete,
        rebar=before.rebar,
        tie_area=rc.bar_area(jacket.tieDia),
        tie_legs=2,
        tie_legs_x=2,
        tie_spacing=jacket.tieSpacing,
        cover=jacket.cover,
        bar_dia=max(before.bar_dia, jacket.barDia),
        concrete_factor=1.0,
        jacket=jacket,
    )


def members(
    building: Any, objects: Any, materials: Any, existing: Any, exact: bool = False
) -> list[Member]:
    """The RC and steel beams and columns of 06 BIM as built and as retrofitted (see the
    module). ``exact``: the analysis turns columns by their exact angle."""
    from saengine.design import check, rc
    from saengine.library.bim import BeamElement, ColumnElement
    from saengine.library.objects import IShapeProfile

    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    conditions = _condition_of(existing)
    measures: dict[str, list[Any]] = {}
    for measure in getattr(existing, "retrofit", []) or []:
        if measure.kind in ("rcJacket", "frp"):
            for mid in measure.members:
                measures.setdefault(mid, []).append(measure)
    found = []
    for e in building.elements:
        if not isinstance(e, BeamElement | ColumnElement):
            continue
        object_type = types.get(e.type)
        if object_type is None or not hasattr(object_type, "profile"):
            continue
        kind = "beam" if isinstance(e, BeamElement) else "column"
        turned = kind == "column" and check._turned(e, exact)
        material = mats.get(object_type.material)
        mkind = material_kind(material) if material is not None else None
        cond = conditions.get(e.id) or conditions.get(e.type)
        condition = cond[1] if cond else None
        own = measures.get(e.id, [])
        if mkind == "steel":
            if isinstance(object_type.profile, IShapeProfile):
                found.append(
                    Member(
                        e.id,
                        kind,
                        "steelBeam" if kind == "beam" else "steelColumn",
                        e.type,
                        turned,
                        None,
                        None,
                        steel=object_type,
                    )
                )
            continue
        reinforcement = getattr(object_type, "reinforcement", None)
        if mkind != "concrete" or reinforcement is None or reinforcement.material not in mats:
            continue
        try:
            before = _section(object_type, mats, condition)
        except (rc.DesignError, KeyError) as error:
            found.append(
                Member(
                    e.id,
                    kind,
                    "rcBeam" if kind == "beam" else "rcColumn",
                    e.type,
                    turned,
                    None,
                    None,
                    notes=[f"not checked: {error}"],
                )
            )
            continue
        after = before
        notes: list[str] = []
        jacket = next((m for m in own if m.kind == "rcJacket"), None)
        if jacket is not None:
            try:
                after = _jacketed(before, jacket, object_type, mats)
            except (rc.DesignError, KeyError, AttributeError) as error:
                notes.append(f"jacket {jacket.id} not modelled: {error}")
        frps = [m for m in own if m.kind == "frp"]
        if frps:  # worked out with the strengths of each use (:func:`capacity`)
            after = replace(after, frp=frps)
        found.append(
            Member(
                e.id,
                kind,
                "rcBeam" if kind == "beam" else "rcColumn",
                e.type,
                turned,
                before,
                after,
                measures=[m.id for m in own],
                notes=notes,
            )
        )
    return found


# ───────────────────────────────────── FRP ─────────────────────────────────────


def frp_effects(
    frp: Any, rules: Any, b: float, h: float, d: float, fc: float, circle: bool, rho_g: float
) -> Frp:
    """The effects of one FRP measure on a member b × h (mm; d its effective depth), f'c [MPa],
    by the pack's ``frp`` rules (see :class:`saengine.codes.existing_tables.FrpRules`)."""
    ce = rules.environment.get(frp.fibre, {}).get(frp.exposure, 1.0)
    eps_fu = ce * frp.ruptureStrain
    out = Frp(frp, eps_fu)
    n, tf, ef = frp.plies, frp.thickness, frp.modulus
    if frp.purpose in ("confinement", "shear"):
        s = rules.shear
        full = frp.scheme == "fullWrap" or frp.purpose == "confinement"
        ratio = (frp.width / frp.spacing) if frp.width and frp.spacing else 1.0
        dfv = d
        if rules.method == "aci440":
            if full:
                eps_fe = min(s.strainFull, s.strainShare * eps_fu)
            else:
                le = s.bondLength / (n * tf * ef) ** s.bondExponent
                k1 = (fc / s.bondStrength) ** (2 / 3)
                k2 = (dfv - le) / dfv if frp.scheme == "uWrap" else (dfv - 2 * le) / dfv
                kv = min(max(k1 * k2 * le / (s.bondStrain * eps_fu), 0.0), 0.75)
                eps_fe = min(kv * eps_fu, s.strainFull)
                out.notes.append(f"{frp.id}: bond-reduced strain κv = {kv:.3f}")
            vf = 2 * n * tf * ratio * eps_fe * ef * dfv
        else:
            eps_fe = min(s.strainFull, s.strainShare * eps_fu)
            vf = 0.9 * d * eps_fe * ef * 2 * n * tf * ratio
        out.vf = (s.psiFull if full else s.psiPartial) * vf
    if frp.purpose == "confinement":
        c = rules.confinement
        eps_fe = c.strainShare * eps_fu
        if rules.method == "aci440":
            diameter = b if circle else math.hypot(b, h)
            fl = 2 * ef * n * tf * eps_fe / diameter
            if circle:
                ka = 1.0
            else:
                short, long = min(b, h), max(b, h)
                rc_ = min(frp.cornerRadius, short / 2)
                ae = (
                    1
                    - (
                        (short / long) * (long - 2 * rc_) ** 2
                        + (long / short) * (short - 2 * rc_) ** 2
                    )
                    / (3 * b * h)
                    - rho_g
                )
                ka = max(ae / (1 - rho_g), 0.0) * (short / long) ** 2
                if long / short > 2:
                    ka = 0.0
                    out.notes.append(f"{frp.id}: h/b above 2: the wrap's confinement not counted")
            if fc > 0 and fl / fc >= c.minRatio and ka > 0:
                out.fcc = fc + c.psi * c.strength * ka * fl
                out.confined = True
            else:
                out.notes.append(
                    f"{frp.id}: fl/f'c = {fl / fc if fc else 0:.3f} below {c.minRatio:g}: no "
                    "confinement counted"
                )
        else:
            rho_f = 2 * n * tf / b
            out.rotation = c.rotationFactor * rho_f * ef * eps_fe / fc if fc > 0 else 0.0
            out.confined = out.rotation > 0
    if frp.purpose == "flexure":
        rule = rules.flexure
        if rule is None:
            out.notes.append(f"{frp.id}: flexural strengthening is not covered by the code pack")
        else:
            eps_fd = min(
                rule.debonding * math.sqrt(fc / (n * ef * tf)), rule.debondingShare * eps_fu
            )
            width = frp.laminateWidth or b
            face = -h / 2 if frp.face == "bottom" else h / 2
            out.laminate = (face, rule.psi * n * tf * width, ef, eps_fd)
    return out


# ───────────────────────────────────── section strength ─────────────────────────────────────


def _widths(sec: Section, axis: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Strip centres (from the compression face, +coordinate side) and areas across the depth of
    bending ``axis`` (0: depth along the profile's y, 1: along its x), and the depth [mm]."""
    depth = sec.h if axis == 0 else sec.b
    width = sec.b if axis == 0 else sec.h
    t = (np.arange(_STRIPS) + 0.5) * depth / _STRIPS
    if sec.circle:
        r = depth / 2
        z = r - t
        w = 2 * np.sqrt(np.maximum(r * r - z * z, 0.0))
    else:
        w = np.full(_STRIPS, width)
    return t, w * depth / _STRIPS, depth


def _bars(sec: Section, axis: int, sign: float) -> tuple[np.ndarray, np.ndarray]:
    """Bars' depths from the compression face (on the ``sign`` side of ``axis``) and areas."""
    coord = np.array([b.y if axis == 0 else b.x for b in sec.rc.bars], dtype=float)
    area = np.array([b.area for b in sec.rc.bars], dtype=float)
    depth = sec.h if axis == 0 else sec.b
    return depth / 2 - sign * coord, area


def strength_curve(
    sec: Section,
    axis: int,
    sign: float,
    fc: float,
    fy: float,
    es: float,
    block: tuple[float, float, float],
    laminate: tuple[float, float, float, float] | None = None,
) -> np.ndarray:
    """Rows (N compression +, M ≥ 0, c) [N, N·mm, mm] of the section's nominal strength by
    strain compatibility with the rectangular stress block ``block`` = (α1, β1, εcu) over the
    neutral-axis depths of :data:`_DEPTHS`, compression on the ``sign`` side of ``axis``,
    sorted by N; ``laminate``: an FRP laminate (face coordinate, area × ψf, Ef, its largest
    strain) in tension only."""
    alpha, beta, ecu = block
    t, a, depth = _widths(sec, axis)
    tb, ab = _bars(sec, axis, sign)
    rows = []
    for c in _DEPTHS * depth:
        block_depth = min(beta * c, depth)
        in_block = t <= block_depth
        concrete = alpha * fc * a[in_block]
        n = float(concrete.sum())
        m = float((concrete * (depth / 2 - t[in_block])).sum())
        eps = ecu * (c - tb) / c
        stress = np.clip(es * eps, -fy, fy) - np.where(tb <= block_depth, alpha * fc, 0.0)
        n += float((stress * ab).sum())
        m += float((stress * ab * (depth / 2 - tb)).sum())
        if laminate is not None:
            face, area, ef, eps_max = laminate
            tf = depth / 2 - sign * face
            if tf > c:
                strain = min(ecu * (tf - c) / c, eps_max)
                force = -area * ef * strain
                n += force
                m += force * (depth / 2 - tf)
        rows.append((n, m, c))
    total = float(ab.sum())
    squash = alpha * fc * (float(a.sum()) - total) + fy * total
    rows.append((squash, 0.0, math.inf))
    rows.append((-fy * total, 0.0, 0.0))
    arr = np.array(rows)
    return arr[np.argsort(arr[:, 0])]


def yield_curve(
    sec: Section, axis: int, sign: float, fc: float, fy: float, es: float, ec: float
) -> np.ndarray:
    """Rows (N, My, φy) [N, N·mm, 1/mm] of the cracked elastic section at the first yield of its
    extreme tension bar, or the extreme concrete fibre at 1.8 fc/Ec, over the neutral-axis
    depths, sorted by N."""
    t, a, depth = _widths(sec, axis)
    tb, ab = _bars(sec, axis, sign)
    if not len(tb):
        return np.zeros((0, 3))
    d = float(tb.max())
    eps_y = fy / es
    eps_c = 1.8 * fc / ec
    rows = []
    for c in _DEPTHS * depth:
        if c >= d:
            phi = eps_c / c
        else:
            phi = min(eps_y / (d - c), eps_c / c)
        eps_t = phi * (c - t)
        concrete = np.where(eps_t > 0, np.minimum(ec * eps_t, fc), 0.0) * a
        stress = np.clip(es * phi * (c - tb), -fy, fy)
        n = float(concrete.sum() + (stress * ab).sum())
        m = float((concrete * (depth / 2 - t)).sum() + (stress * ab * (depth / 2 - tb)).sum())
        rows.append((n, m, phi))
    arr = np.array(rows)
    return arr[np.argsort(arr[:, 0])]


def at_axial(curve: np.ndarray, n: np.ndarray | float, column: int = 1) -> np.ndarray:
    """Column ``column`` of a strength curve at the axial forces ``n``: 0 outside its range."""
    values = np.atleast_1d(np.asarray(n, dtype=float))
    if not len(curve):
        return np.zeros_like(values)
    lo, hi = curve[0, 0], curve[-1, 0]
    found = np.interp(values, curve[:, 0], curve[:, column])
    return np.where((values >= lo) & (values <= hi), found, 0.0)


# ───────────────────────────────────── shear ─────────────────────────────────────


def _interp_pairs(pairs: list[tuple[float, float]], x: float, default: float = 1.0) -> float:
    if not pairs:
        return default
    xs, ys = zip(*sorted(pairs), strict=True)
    return float(np.interp(x, xs, ys))


def shear_strength(
    rule: Any,
    kind: str,
    b: float,
    h: float,
    d: float,
    fc: float,
    fyt: float,
    av: float,
    s: float,
    n: float,
    m: float,
    v: float,
    ductility: float,
    rho_tot: float = 0.0,
    x: float = 0.0,
    lv: float = 0.0,
    vf: float = 0.0,
    limit_share: float | None = None,
) -> float:
    """The shear strength [N] of a member b × h (d, mm) by the pack's ``shear.method``
    (:class:`saengine.codes.existing_tables.ShearCapacity`): ``kind`` "beam" or "column", fc
    and fyt [MPa], ``av`` the ties' legs' area at spacing ``s`` [mm², mm], ``n`` the axial
    compression [N], ``m``, ``v`` the moment and shear at the section [N·mm, N] (for M/Vd),
    ``ductility`` the displacement ductility demand (columnDuctility) or the plastic part of
    the chord rotation ductility (cyclicDegradation), ``rho_tot`` the total longitudinal ratio,
    ``x`` the compression zone depth and ``lv`` the shear span [mm] (cyclicDegradation), ``vf``
    an FRP's contribution [N]."""
    root = math.sqrt(max(fc, 0.0))
    steel = av * fyt * d / s if s > 0 and av > 0 else 0.0
    if rule.method == "columnDuctility":
        lam = rule.lightweight
        if kind == "beam":
            vc = rule.beamConcrete * lam * root * b * d
            added = steel + vf
            if limit_share is not None:
                added = min(added, limit_share * root * b * d)
            return vc + added
        lo, hi = rule.shearSpan
        span = m / (v * d) if v > 0 and d > 0 else hi
        span = min(max(span, lo), hi)
        ag = b * h
        axial = max(n, 0.0) / (rule.columnAxial * root * ag) if root > 0 else 0.0
        k = _interp_pairs(rule.ductility, ductility)
        concrete = rule.columnConcrete * root / span * math.sqrt(1 + axial) * rule.columnArea * ag
        added = steel + vf
        if limit_share is not None:
            added = min(added, limit_share * root * b * d)
        return k * lam * (concrete + added)
    # cyclicDegradation
    ac = b * h
    lv = lv if lv > 0 else (m / v if v > 0 else 2 * h)
    axial_part = (h - min(x, h)) / (2 * lv) * min(max(n, 0.0), rule.axialShare * ac * fc)
    z = 0.9 * d
    web = av * fyt * z / s if s > 0 and av > 0 else 0.0
    degradation = 1 - rule.degradation * min(rule.ductilityCap, max(ductility, 0.0))
    concrete = (
        rule.rhoFactor
        * max(rule.rhoMin, 100 * rho_tot)
        * (1 - rule.spanFactor * min(rule.spanCap, lv / h))
        * root
        * ac
    )
    return (axial_part + degradation * (concrete + web)) / rule.gammaEl + vf


# ───────────────────────────────────── per member capacities ─────────────────────────────────────


@dataclass
class Capacity:
    """The strengths of one section for one use [MPa] and its curves."""

    fc: float
    fy: float
    fyt: float
    es: float
    curves: dict[tuple[int, float], np.ndarray]  # (axis, sign) -> strength curve
    yields: dict[tuple[int, float], np.ndarray]  # (axis, sign) -> yield curve (chordRotation)
    frp: list[Frp]
    squash: float  # N, P0 at these strengths (aci440: with f'cc)


def _block(fc: float) -> tuple[float, float, float]:
    from saengine.design import rc

    return rc.alpha1(fc), rc.beta1(fc), rc.value("EPS_CU")


def capacity(
    sec: Section,
    strengths_: dict[str, MaterialStrength],
    use: Any,
    cf: float,
    rule: Any,
    yields: bool,
) -> Capacity:
    """The curves of ``sec`` at the strengths of ``use``."""
    from saengine.design.rc_detailing import concrete_modulus

    concrete = strengths_.get(sec.concrete)
    rebar = strengths_.get(sec.rebar)
    fc = (concrete.value(use, cf) if concrete else sec.rc.fc) * sec.concrete_factor
    fy = rebar.value(use, cf) if rebar else sec.rc.fy
    es = float(sec.rc.es)
    d = sec.h - sec.cover - sec.bar_dia
    rho_g = sec.steel_area / sec.area if sec.area > 0 else 0.0
    frps = [frp_effects(f, rule.frp, sec.b, sec.h, d, fc, sec.circle, rho_g) for f in sec.frp]
    fcc = max((f.fcc for f in frps if f.fcc is not None), default=None)
    curves: dict[tuple[int, float], np.ndarray] = {}
    yield_curves: dict[tuple[int, float], np.ndarray] = {}
    block = _block(fc)
    for axis in (0, 1):
        for sign in (1.0, -1.0):
            laminate = None
            for f in frps:
                if f.laminate is not None and axis == 0 and f.laminate[0] * sign < 0:
                    laminate = f.laminate
            curves[(axis, sign)] = strength_curve(sec, axis, sign, fc, fy, es, block, laminate)
            if yields:
                ec = concrete_modulus(fc)[0]
                yield_curves[(axis, sign)] = yield_curve(sec, axis, sign, fc, fy, es, ec)
    ast = sec.steel_area
    squash = block[0] * (fcc or fc) * (sec.area - ast) + fy * ast
    return Capacity(fc, fy, fy, es, curves, yield_curves, frps, squash)


# ───────────────────────────────────── demands ─────────────────────────────────────


def _seismic_factor(settings: Any) -> dict[str, float]:
    """R/I of each direction of the run's seismic forces (q/γI of a q-based pack)."""
    from saengine.library.settings import derived

    values = derived(settings)
    importance = float(values.get("seismicImportance") or 1.0)
    return {axis: float(values.get(f"R{axis}", values["R"])) / importance for axis in ("X", "Y")}


def _parts(
    project: dict[str, Any], out_dir: Any, settings: Any, rule: Any
) -> tuple[dict, list[str]]:
    """Per member, per piece: the section forces of the gravity load upper (``G+``), lower
    (``G-``) and of the seismic cases EX and EY at unit factor, from the run (the design's
    demands, :func:`saengine.design.check._demands`)."""
    from saengine.design import check
    from saengine.library.settings import LoadCombination

    lin = rule.linear
    up, low = lin.gravityUpper, lin.gravityLower
    combinations = [
        LoadCombination(name="G+", D=up, L=up * lin.liveShare, F=up, H=up),
        LoadCombination(name="G-", D=low, F=low, H=low),
        LoadCombination(name="EX", EX=1.0, F=0.0, H=0.0),
        LoadCombination(name="EY", EY=1.0, F=0.0, H=0.0),
    ]
    names, pieces, notes, _shells = check._demands(
        project, out_dir, settings.model_copy(update={"combinations": combinations})
    )
    index = {name: k for k, name in enumerate(names)}
    out: dict[str, list[dict[str, Any]]] = {}
    for member, parts in pieces.items():
        for piece in parts:
            out.setdefault(member, []).append(
                {"piece": piece, "forces": {name: piece.forces[k] for name, k in index.items()}}
            )
    return out, notes


def _profile(piece: Any, turned: bool, forces: np.ndarray | None) -> dict[str, np.ndarray]:
    from saengine.design import check

    if forces is None:
        zero = np.zeros((1, 6))
        return check._profile_forces(piece, turned, zero)
    return check._profile_forces(piece, turned, np.asarray(forces, dtype=float))


def demand_sets(
    parts: list[dict[str, Any]], turned: bool, factors: dict[str, float]
) -> list[dict[str, np.ndarray]]:
    """The profile-axis forces (P, Mx, Vy, My, Vx at every station of every piece) of the
    combinations G± ± f·EX, G± ± f·EY with ``factors`` {"X": f, "Y": f}."""
    out = []
    for part in parts:
        piece, forces = part["piece"], part["forces"]
        gravity = [forces.get("G+"), forces.get("G-")]
        for g in gravity:
            if g is None:
                continue
            for axis in ("X", "Y"):
                e = forces.get(f"E{axis}")
                if e is None:
                    continue
                for sign in (1.0, -1.0):
                    total = np.asarray(g) + sign * factors[axis] * np.asarray(e)
                    out.append(_profile(piece, turned, total))
    return out


# ───────────────────────────────────── the linear procedure ─────────────────────────────────────


def c1c2_factor(rule: Any, period: float | None, m_max: float) -> float:
    """C1·C2 of the pack's table at ``period`` [s] (None: the largest of the m column) and the
    largest m-factor ``m_max``; 1 without a table."""
    bands = rule.linear.c1c2
    if not bands:
        return 1.0

    def by_m(band: Any) -> float:
        value = band.values[0][1]
        for start, factor in band.values:
            if m_max >= start:
                value = factor
        return value

    if period is None:
        return max(by_m(b) for b in bands)
    for band in bands:
        if band.periodTo is None or period <= band.periodTo:
            return by_m(band)
    return by_m(bands[-1])


def _rc_variables(
    member: Member, sec: Section, cap: Capacity, n: float, v: float, rule: Any, length: float
) -> dict[str, Any]:
    """The m-table variables of an RC member at its axial force ``n`` and shear ``v`` [N]."""
    from saengine.fem import hinges

    var = rule.linear.variables
    b, h = sec.b, sec.h
    d = h - sec.cover - sec.bar_dia / 2 - math.sqrt(sec.tie_area * 4 / math.pi)
    d = max(d, 0.5 * h)
    fc, fy = cap.fc, cap.fy
    av = sec.tie_legs * sec.tie_area
    s = sec.tie_spacing
    vs = av * cap.fyt * d / s if s > 0 else 0.0
    vf = sum(f.vf for f in cap.frp)
    bars_top = sum(bar.area for bar in sec.rc.bars if bar.y > 0)
    bars_bottom = sum(bar.area for bar in sec.rc.bars if bar.y < 0)
    a_s, a_sc = max(bars_top, bars_bottom), min(bars_top, bars_bottom)
    rho, rho_c = a_s / (b * d), a_sc / (b * d)
    bal = hinges.balanced_ratio(fc, fy, cap.es, var)
    unit = math.sqrt(var.stressUnitPerMPa)
    # The shear at the flexural strength of both ends (opposite signs in double curvature).
    at = n if member.kind == "column" else 0.0
    ends = float(at_axial(cap.curves[(0, 1.0)], at)[0] + at_axial(cap.curves[(0, -1.0)], at)[0])
    vp = ends / (length * 1e3) if length > 0 else 0.0
    vc = (var.concreteShear or 0.0) * math.sqrt(fc) * b * d
    confined = any(f.confined for f in cap.frp)
    conforming = confined or (
        s > 0
        and var.conformingSpacing is not None
        and var.conformingShear is not None
        and s <= var.conformingSpacing * d
        and vs + vf >= var.conformingShear * v
    )
    return {
        "b": b,
        "h": h,
        "d": d,
        "fc": fc,
        "fy": fy,
        "rho": rho,
        "rhoBalance": (rho - rho_c) / bal if bal > 0 else 0.0,
        "shearStress": v / (b * d) / math.sqrt(fc) * unit if fc > 0 else 0.0,
        "axialLoadRatio": max(n, 0.0) / (sec.area * fc) if fc > 0 else 0.0,
        "conforming": "C" if conforming else "NC",
        "control": "shear" if vp > vc + vs + vf and vp > 0 else "flexure",
        "spacing": "close"
        if var.closeSpacing is not None and 0 < s <= var.closeSpacing * d
        else "wide",
        "Vp": vp,
        "Vs": vs,
        "Vf": vf,
    }


def _m_factors(
    component: Any, values: dict[str, Any], levels: list[str]
) -> dict[str, float] | None:
    from saengine.fem import hinges

    if component is None:
        return None
    found = hinges.lookup(component, values)
    if found is None:
        return None
    return {k: float(found["limits"].get(k, 1.0)) for k in levels}


@dataclass
class Check:
    """One member's ratios for one model state."""

    ratio: float  # the largest over the actions at the checked level
    action: str
    level: str | None  # the lowest level met at the main hazard (">" + last: none)
    actions: dict[str, float]
    hazards: dict[str, float]  # hazard id -> the largest ratio at its level
    m: dict[str, float] | None = None
    values: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _combine(rx: np.ndarray, ry: np.ndarray, alpha: float) -> np.ndarray:
    return (np.abs(rx) ** alpha + np.abs(ry) ** alpha) ** (1 / alpha)


def _flexure_ratio(
    cap: Capacity,
    sets: list[dict[str, np.ndarray]],
    kind: str,
    divisor: dict[int, float],
    alpha: float,
) -> float:
    """The largest flexural ratio M/(divisor·Mn(N)) over the demand ``sets``; beams the major
    axis only, columns both axes combined with ``alpha``."""
    worst = 0.0
    for forces in sets:
        n = forces["P"]
        mx, my = forces["Mx"], forces["My"]
        # +Mx stretches the top (+y) fibres: compression at -y.
        cap_x = np.where(
            mx >= 0, at_axial(cap.curves[(0, -1.0)], n), at_axial(cap.curves[(0, 1.0)], n)
        )
        rx = np.where(cap_x > 0, np.abs(mx) / (divisor[0] * np.maximum(cap_x, 1e-9)), np.inf)
        if kind == "beam":
            worst = max(worst, float(np.max(rx)))
            continue
        cap_y = np.minimum(at_axial(cap.curves[(1, 1.0)], n), at_axial(cap.curves[(1, -1.0)], n))
        ry = np.where(cap_y > 0, np.abs(my) / (divisor[1] * np.maximum(cap_y, 1e-9)), np.inf)
        worst = max(worst, float(np.max(_combine(rx, ry, alpha))))
    return worst


def _worst(sets: list[dict[str, np.ndarray]]) -> dict[str, float]:
    """The largest |V| and compression P and the P at the largest moment over ``sets``."""
    v = p = 0.0
    p_at = 0.0
    best_m = -1.0
    for f in sets:
        shear = np.hypot(f["Vy"], f["Vx"])
        v = max(v, float(shear.max()))
        p = max(p, float(f["P"].max()))
        m = np.hypot(f["Mx"], f["My"])
        k = int(np.argmax(m))
        if float(m[k]) > best_m:
            best_m, p_at = float(m[k]), float(f["P"][k])
    return {"V": v, "P": p, "Pm": p_at, "M": max(best_m, 0.0)}


def _shear_ratio(
    rule: Any,
    member: Member,
    sec: Section,
    cap: Capacity,
    sets: list[dict[str, np.ndarray]],
    kappa: float,
    ductility: float,
    theta_ratio: float = 0.0,
) -> float:
    """The largest V/(κ·Vn) over ``sets`` along each profile axis (the ties' legs of that axis)."""
    worst = 0.0
    vf = sum(f.vf for f in cap.frp)
    jacket = rule.jacketing.shearFactor if sec.jacket is not None else 1.0
    limit = rule.frp.shear.limitShare if cap.frp and rule.frp.method == "aci440" else None
    rho_tot = sec.steel_area / sec.area if sec.area > 0 else 0.0
    for forces in sets:
        for v_key, m_key, depth, width, legs in (
            ("Vy", "Mx", sec.h, sec.b, sec.tie_legs),
            ("Vx", "My", sec.b, sec.h, sec.tie_legs_x),
        ):
            if member.kind == "beam" and v_key == "Vx":
                continue
            v = np.abs(forces[v_key])
            k = int(np.argmax(v))
            if v[k] <= 0:
                continue
            n = float(forces["P"][k])
            m = float(abs(forces[m_key][k]))
            d = depth - sec.cover - sec.bar_dia
            x = _compression_depth(cap, 0 if v_key == "Vy" else 1, n)
            vn = shear_strength(
                rule.shear,
                member.kind,
                width,
                depth,
                d,
                cap.fc,
                cap.fyt,
                legs * sec.tie_area,
                sec.tie_spacing,
                n,
                m,
                float(v[k]),
                ductility if rule.shear.method == "columnDuctility" else theta_ratio,
                rho_tot,
                x,
                0.0,
                vf,
                limit,
            )
            vn *= jacket
            worst = max(worst, float(v[k]) / (kappa * vn) if vn > 0 else math.inf)
    return worst


def _compression_depth(cap: Capacity, axis: int, n: float) -> float:
    curve = cap.curves[(axis, 1.0)]
    finite = curve[np.isfinite(curve[:, 2])]
    if not len(finite):
        return 0.0
    return float(np.interp(n, finite[:, 0], finite[:, 2]))


def _axial_ratio(cap: Capacity, sets: list[dict[str, np.ndarray]], kappa: float) -> float:
    p = max((float(f["P"].max()) for f in sets), default=0.0)
    return p / (kappa * cap.squash) if p > 0 and cap.squash > 0 else 0.0


def _levels(rule: Any) -> list[str]:
    return [lv.id for lv in rule.linear.levels]


def _state_of(ratios: dict[str, float], levels: list[str]) -> str:
    for level in levels:
        if ratios.get(level, math.inf) <= 1 + 1e-9:
            return level
    return f">{levels[-1]}"


@dataclass
class LinearContext:
    """What every member's linear check shares."""

    rule: Any
    know: Knowledge
    strengths: dict[str, MaterialStrength]
    factors: dict[str, float]  # R/I per direction
    periods: dict[str, float | None]
    c1c2: float | None  # the project's
    lengths: dict[str, float]  # member -> length [m]


def _rc_linear(
    ctx: LinearContext, member: Member, sec: Section, parts: list[dict[str, Any]]
) -> Check:
    """Method ``mFactor`` or ``chordRotation`` of one RC member (``sec``: as built or
    retrofitted) with the run's forces ``parts``."""
    rule, lin = ctx.rule, ctx.rule.linear
    levels = _levels(ctx.rule)
    main = lin.hazards[0]
    s = ctx.rule.strengths
    chord = lin.method == "chordRotation"
    deform = capacity(sec, ctx.strengths, s.deformation, ctx.know.cf, rule, yields=False)
    force = capacity(sec, ctx.strengths, s.force, ctx.know.cf, rule, yields=False)
    # chordRotation: the demand's chord rotation from the secant stiffness to yield of the
    # analysis strengths (the model's), the capacity θum from those of the deformation use.
    analysis = (
        capacity(sec, ctx.strengths, s.analysis, ctx.know.cf, rule, yields=True) if chord else None
    )
    length = ctx.lengths.get(member.id, 3.0)
    notes = [n for f in deform.frp for n in f.notes]
    hazard_ratios: dict[str, float] = {}
    level_ratios: dict[str, float] = {}
    actions: dict[str, float] = {}
    values: dict[str, Any] = {}
    m_used: dict[str, float] | None = None
    for hazard in lin.hazards:
        scale = hazard.spectrumScale * lin.massFactor
        f_force = {a: ctx.factors[a] * scale / lin.forceDivisor for a in ("X", "Y")}
        force_sets = demand_sets(parts, member.turned, f_force)
        if not force_sets:
            continue
        worst = _worst(force_sets)
        if analysis is not None:
            ratios, acts, vals = _chord_checks(
                ctx, member, sec, analysis, deform, force, force_sets, levels, length
            )
        else:
            vals = _rc_variables(member, sec, deform, worst["Pm"], worst["V"], rule, length)
            m = _m_factors(lin.mFactors.get(member.component), vals, levels)
            if m is None:
                notes.append(f"no {member.component} m-factor row covers this member")
                m = dict.fromkeys(levels, 1.0)
            c1c2 = ctx.c1c2 or c1c2_factor(rule, _period(ctx, member), max(m.values()))
            vals["C1C2"] = c1c2
            f_deform = {a: f * c1c2 * lin.forceDivisor for a, f in f_force.items()}
            deform_sets = demand_sets(parts, member.turned, f_deform)
            base = _flexure_ratio(
                deform,
                deform_sets,
                member.kind,
                {0: ctx.know.kappa, 1: ctx.know.kappa},
                lin.biaxialExponent,
            )
            ductility = max(1.0, base)
            shear = _shear_ratio(rule, member, sec, force, force_sets, ctx.know.kappa, ductility)
            axial = (
                _axial_ratio(force, force_sets, ctx.know.kappa) if member.kind == "column" else 0.0
            )
            ratios = {}
            acts = {}
            for level in levels:
                flex = base / m[level] if m[level] > 0 else math.inf
                ratios[level] = max(flex, shear, axial)
                acts[level] = {"flexure": flex, "shear": shear, "axial": axial}
            m_used = m
        hazard_ratios[hazard.id] = ratios.get(hazard.level, max(ratios.values(), default=0.0))
        if hazard.id == main.id:
            level_ratios = ratios
            actions = acts.get(main.level, {})
            values = vals
    governing = max(actions, key=lambda k: actions[k]) if actions else ""
    ratio = level_ratios.get(main.level, 0.0)
    return Check(
        ratio=ratio,
        action=governing,
        level=_state_of(level_ratios, levels) if level_ratios else None,
        actions=actions,
        hazards=hazard_ratios,
        m=m_used,
        values=_rounded(values),
        notes=notes,
    )


def _period(ctx: LinearContext, member: Member) -> float | None:
    found = [p for p in ctx.periods.values() if p]
    return min(found) if found else None


def _chord_checks(
    ctx: LinearContext,
    member: Member,
    sec: Section,
    analysis: Capacity,
    deform: Capacity,
    force: Capacity,
    sets: list[dict[str, np.ndarray]],
    levels: list[str],
    length: float,
) -> tuple[dict[str, float], dict[str, dict[str, float]], dict[str, Any]]:
    """Method ``chordRotation``: the demand θ = (M/My)·θy (My, θy of the ``analysis``
    strengths, the secant stiffness to yield of the model) against θy (the yield level) and the
    shares of θum (of the ``deform`` strengths, divided by CF where the pack says so), the shear
    against the cyclic strength (``force`` strengths) with μpl = θ/θy - 1."""
    from saengine.fem import hinges

    lin = ctx.rule.linear
    rule = lin.chordRotation
    yr = lin.yieldRotation
    jacket = ctx.rule.jacketing if sec.jacket is not None else None
    lv = length * 1e3 / 2  # the shear span of a member in double curvature [mm]
    worst_theta = 0.0
    worst_ratio: dict[str, float] = dict.fromkeys(levels, 0.0)
    theta_y_used = theta_um_used = 0.0

    def yield_rotation(cap: Capacity, depth: float) -> float:
        phi_y = yr.curvature * (cap.fy / cap.es) / depth
        theta = (
            phi_y * lv / 3
            + yr.shear * (1 + yr.shearDepth * depth / lv)
            + yr.slip * phi_y * sec.bar_dia * cap.fy / math.sqrt(cap.fc)
        )
        return theta * (jacket.yieldFactor if jacket is not None else 1.0)

    for forces in sets:
        for m_key, axis, depth, width in (("Mx", 0, sec.h, sec.b), ("My", 1, sec.b, sec.h)):
            if member.kind == "beam" and axis == 1:
                continue
            m = forces[m_key]
            n = forces["P"]
            k = int(np.argmax(np.abs(m)))
            # +Mx stretches the top fibres: compression at -y; My: the smaller of both signs.
            sign = (-1.0 if m[k] >= 0 else 1.0) if axis == 0 else 1.0
            my = float(at_axial(analysis.yields[(axis, sign)], n[k])[0])
            if axis == 1:
                my = min(my, float(at_axial(analysis.yields[(axis, -1.0)], n[k])[0]))
            if my <= 0:
                worst_ratio = dict.fromkeys(levels, math.inf)
                continue
            theta_y = yield_rotation(analysis, depth)
            theta = abs(float(m[k])) / my * theta_y
            fc = deform.fc
            nu = max(float(n[k]), 0.0) / (width * depth * fc) if fc > 0 else 0.0

            placed = [(bar.y if axis == 0 else bar.x, bar.area) for bar in sec.rc.bars]
            a_t = sum(area for at, area in placed if at * (-sign) > 0)
            a_c = sum(area for at, area in placed if at * (-sign) < 0)
            omega = a_t / (width * depth) * deform.fy / fc
            omega_c = a_c / (width * depth) * deform.fy / fc
            confinement = _confinement(sec, deform, width, depth) + sum(
                f.rotation for f in deform.frp
            )
            theta_um = hinges.theta_um_formula(
                rule, nu, omega, omega_c, fc, lv / depth, confinement, False
            )
            if jacket is not None:
                theta_um *= jacket.ultimateFactor
            limits = {key: share * theta_um for key, share in rule.shares.items()}
            limits[rule.yieldLevel] = theta_y
            for level in levels:
                limit = limits.get(level)
                r = theta / limit if limit else math.inf
                worst_ratio[level] = max(worst_ratio[level], r)
            if theta > worst_theta:
                worst_theta, theta_y_used, theta_um_used = theta, theta_y, theta_um
    mu_pl = max(0.0, worst_theta / theta_y_used - 1) if theta_y_used > 0 else 0.0
    shear = _shear_ratio(ctx.rule, member, sec, force, sets, ctx.know.kappa, 1.0, mu_pl)
    ratios = {}
    acts = {}
    for level in levels:
        brittle = shear if level != rule.yieldLevel else 0.0
        ratios[level] = max(worst_ratio[level], brittle)
        acts[level] = {"rotation": worst_ratio[level], "shear": brittle}
    values = {
        "theta": worst_theta,
        "thetaY": theta_y_used,
        "thetaUm": theta_um_used,
        "muPl": mu_pl,
    }
    return ratios, acts, values


def _confinement(sec: Section, cap: Capacity, width: float, depth: float) -> float:
    """α·ρsx·fyw/fc of the ties of ``sec`` (EN 1998-3 type confinement term)."""
    from saengine.fem import hinges

    s = sec.tie_spacing
    if s <= 0 or sec.tie_area <= 0 or cap.fc <= 0:
        return 0.0
    bo = width - 2 * sec.cover
    ho = depth - 2 * sec.cover
    if bo <= 0 or ho <= 0:
        return 0.0
    coords = np.array([(b.x, b.y) for b in sec.rc.bars])
    spaces = 0.0
    if len(coords) >= 3:
        angles = np.arctan2(coords[:, 1] - coords[:, 1].mean(), coords[:, 0] - coords[:, 0].mean())
        pts = coords[np.argsort(angles)]
        spaces = float(sum(np.sum((pts[k] - pts[k - 1]) ** 2) for k in range(len(pts))))
    alpha = hinges.confinement_effectiveness(bo, ho, s, spaces)
    rho_sx = sec.tie_legs * sec.tie_area / (width * s)
    return max(0.0, alpha) * rho_sx * cap.fyt / cap.fc


def _steel_linear(ctx: LinearContext, member: Member, parts: list[dict[str, Any]]) -> Check:
    """Method ``mFactor`` of a steel I-shaped beam or column: strong-axis flexure m·κ·Mpce ≥
    MUD, Mpce = Z·Fye (columns × min(1, 1.18·(1 - P/Pye)))."""
    from saengine.fem import hinges

    rule, lin = ctx.rule, ctx.rule.linear
    levels = _levels(rule)
    p = member.steel.profile
    ms = ctx.strengths.get(member.steel.material)
    fy = ms.value(rule.strengths.deformation, ctx.know.cf) if ms else 250.0
    es = 200_000.0
    bf, d, tf, tw = p.overallWidth, p.overallDepth, p.flangeThickness, p.webThickness
    z = bf * tf * (d - tf) + tw * (d - 2 * tf) ** 2 / 4
    area = 2 * bf * tf + (d - 2 * tf) * tw
    i_min = 2 * tf * bf**3 / 12 + (d - 2 * tf) * tw**3 / 12
    length = ctx.lengths.get(member.id, 3.0) * 1e3
    if lin.method != "mFactor" or lin.variables is None:
        return Check(
            0.0, "", None, {}, {}, notes=["steel members: not covered by the linear method"]
        )
    k_len = lin.variables.effectiveLength * length
    euler = math.pi**2 * es * i_min / k_len**2 if k_len > 0 else math.inf
    pcl = min(area * fy, euler)
    slender = hinges.profile_slenderness(p, fy, es, lin.variables)
    main = lin.hazards[0]
    hazard_ratios: dict[str, float] = {}
    level_ratios: dict[str, float] = {}
    m_used: dict[str, float] | None = None
    for hazard in lin.hazards:
        scale = hazard.spectrumScale * lin.massFactor
        f_force = {a: ctx.factors[a] * scale / lin.forceDivisor for a in ("X", "Y")}
        force_sets = demand_sets(parts, member.turned, f_force)
        if not force_sets:
            continue
        worst = _worst(force_sets)
        axial = worst["P"] / pcl if pcl > 0 else 0.0
        values = {"slenderness": slender, "axialRatio": axial if member.kind == "column" else 0.0}
        m = _m_factors(lin.mFactors.get(member.component), values, levels) or dict.fromkeys(
            levels, 1.0
        )
        c1c2 = ctx.c1c2 or c1c2_factor(rule, _period(ctx, member), max(m.values()))
        f_deform = {a: f * c1c2 * lin.forceDivisor for a, f in f_force.items()}
        mp = z * fy
        if member.kind == "column":
            mp *= min(1.0, 1.18 * (1 - worst["P"] / (area * fy))) if area * fy > 0 else 1.0
        flex = 0.0
        for forces in demand_sets(parts, member.turned, f_deform):
            flex = max(
                flex,
                float(np.max(np.abs(forces["Mx"]))) / (ctx.know.kappa * mp) if mp > 0 else math.inf,
            )
        ratios = {level: flex / m[level] if m[level] > 0 else math.inf for level in levels}
        hazard_ratios[hazard.id] = ratios.get(hazard.level, 0.0)
        if hazard.id == main.id:
            level_ratios = ratios
            m_used = m
    ratio = level_ratios.get(main.level, 0.0)
    return Check(
        ratio=ratio,
        action="flexure",
        level=_state_of(level_ratios, levels) if level_ratios else None,
        actions={"flexure": ratio},
        hazards=hazard_ratios,
        m=m_used,
        notes=["steel: strong-axis flexure (minor-axis bending and shear not checked)"],
    )


def _rounded(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in values.items():
        if isinstance(v, float):
            out[k] = None if not math.isfinite(v) else float(f"{v:.5g}")
        else:
            out[k] = v
    return out


def _lengths(project: dict[str, Any]) -> dict[str, float]:
    """Each member's length [m] (the sum of its elements')."""
    from saengine.fem.display import _elements

    out: dict[str, float] = {}
    for e in _elements(project):
        member = e.name.split("#")[0]
        out[member] = out.get(member, 0.0) + e.length
    return out


def _check_row(check: Check | None) -> dict[str, Any] | None:
    if check is None:
        return None
    clean = {k: (None if not math.isfinite(v) else round(v, 4)) for k, v in check.actions.items()}
    return {
        "ratio": None if not math.isfinite(check.ratio) else round(check.ratio, 4),
        "action": check.action,
        "level": check.level,
        "actions": clean,
        "hazards": {
            k: (None if not math.isfinite(v) else round(v, 4)) for k, v in check.hazards.items()
        },
        "m": check.m,
        "values": check.values,
        "notes": check.notes,
    }


def linear(
    project: dict[str, Any],
    out_dir: Any,
    settings: Any,
    building: Any,
    objects: Any,
    materials: Any,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The linear procedure of the pack's ``existing.linear`` over the run ``out_dir`` of the
    analysis model ``project``: per member the ratio as built and as retrofitted (with this
    run's demands), the governing action and the performance level reached."""
    from saengine.design import check

    existing = settings.analysis.existingBuilding
    rule = table()
    know = knowledge(existing, rule)
    found = strengths(existing, rule, materials)
    parts, notes = _parts(project, out_dir, settings, rule)
    summary = summary or {}
    seismic = summary.get("seismic") or {}
    periods = {
        a: (seismic.get(f"E{a}") or {}).get("period_s") or summary.get("period_s")
        for a in ("X", "Y")
    }
    ctx = LinearContext(
        rule,
        know,
        found,
        _seismic_factor(settings),
        periods,
        getattr(existing, "c1c2", None),
        _lengths(project),
    )
    rows = []
    added = {mid for measure in _measures(existing, "added") for mid in measure.members}
    if added:
        notes.append(
            "the retrofit's added members are new members, designed by the code pack's methods "
            "(the design checks), not assessed: " + ", ".join(sorted(added))
        )
    for member in members(building, objects, materials, existing, check.exact_rotation(project)):
        own = parts.get(member.id)
        if not own or member.id in added:
            continue
        row: dict[str, Any] = {
            "member": member.id,
            "component": member.component,
            "type": member.type_id,
            "measures": member.measures,
            "notes": list(member.notes),
        }
        if member.steel is not None and rule.linear.method != "mFactor":
            note = "steel members: not covered by the code pack's linear method"
            rows.append({**row, "covered": False, "notes": [*row["notes"], note]})
            continue
        try:
            if member.steel is not None:
                before = after = _steel_linear(ctx, member, own)
            elif member.before is None:
                rows.append({**row, "covered": False})
                continue
            else:
                before = _rc_linear(ctx, member, member.before, own)
                after = (
                    _rc_linear(ctx, member, member.after, own)
                    if member.after is not member.before or member.after.frp
                    else before
                )
        except (ValueError, KeyError, ZeroDivisionError, IndexError) as error:
            rows.append({**row, "covered": False, "notes": [*row["notes"], str(error)]})
            continue
        row.update(
            {"covered": True, "asBuilt": _check_row(before), "retrofitted": _check_row(after)}
        )
        rows.append(row)
    return {
        "procedure": "linear",
        "method": rule.linear.method,
        "factors": {a: round(f, 4) for a, f in ctx.factors.items()},
        "periods": periods,
        "rows": rows,
        "notes": notes,
    }


# ───────────────────────────────────── the nonlinear procedure ─────────────────────────────────────


def adjusted_hinge(
    row: dict[str, Any], rule: Any, know: Knowledge, hinge_rules: Any, levels: list[str],
    checked: str, jacket: Any = None, frp: list[Frp] | None = None,
) -> dict[str, Any]:  # fmt: skip
    """A pushover hinge row (:func:`saengine.fem.hinges.row_at`) with the assessment's changes:
    κ on the limits, θum with the strengths over CF, the jacket's monolithic factors, the FRP's
    confinement, and the shear ratio (``shear`` of the row) where the pack checks it."""
    out = dict(row)
    if not row.get("covered"):
        return out
    limits = dict(row.get("limits") or {})
    values = dict(row.get("variables") or {})
    component = (hinge_rules.components or {}).get(row.get("component", ""))
    model = getattr(component, "model", "")
    rotation = getattr(component, "chordRotation", None)
    if model == "chordRotationCapacity" and rotation is not None:
        factor = 1.0
        if rule.nonlinear.confidenceFactor and know.cf > 1:
            nu = float(values.get("nu") or 0.0)
            factor *= know.cf ** (-rotation.omegaExponent) * rotation.axialBase ** (
                nu * (know.cf - 1)
            )
        if jacket is not None:
            factor *= rule.jacketing.ultimateFactor
        for f in frp or []:
            if f.rotation > 0:
                factor *= rotation.confinementBase**f.rotation
        for k in list(limits):
            if k != rotation.yieldLevel:
                limits[k] *= factor
        if jacket is not None and rotation.yieldLevel in limits:
            limits[rotation.yieldLevel] *= rule.jacketing.yieldFactor
    elif model == "columnRegression" and component.regression is not None and frp:
        vf = sum(f.vf for f in frp)
        from saengine.fem import hinges

        if vf > 0 and values.get("V") is not None:
            base = values.get("shearRatio")
            v = float(values.get("V") or 0.0)
            vcol = v / base if base else 0.0
            values["shearRatio"] = v / (vcol + vf) if vcol + vf > 0 else 0.0
            limits = hinges.column_regression(component.regression, values, levels)["limits"]
    elif (
        model == "table"
        and component is not None
        and frp
        and any(f.confined or f.vf > 0 for f in frp)
    ):
        from saengine.fem import hinges

        values["conforming"] = "C"
        found = hinges.lookup(component, values)
        if found is not None:
            limits = dict(found["limits"])
    if rule.nonlinear.capacityFactor and know.kappa < 1:
        limits = {k: v * know.kappa for k, v in limits.items()}
    demand = float(row.get("demand") or 0.0)
    limit = limits.get(checked)
    ratio = demand / limit if limit else (0.0 if demand <= 0 else math.inf)
    if rule.nonlinear.shearCheck and row.get("component", "").startswith("rc"):
        shear = _hinge_shear(values, rule, demand, frp, jacket)
        if shear is not None:
            out["shear"] = round(shear, 4)
            ratio = max(ratio, shear)
    from saengine.fem import hinges

    out.update(
        {
            "limits": limits,
            "ratio": ratio if math.isfinite(ratio) else None,
            "ok": bool(ratio <= 1 + 1e-9),
            "state": hinges.classify(demand, limits, levels) if demand > 0 else "elastic",
        }
    )
    return out


def _hinge_shear(
    values: dict[str, Any], rule: Any, demand: float, frp: list[Frp] | None, jacket: Any
) -> float | None:
    """V/VR of a pushover hinge from its variables (SI: m, N, MPa) by the pack's shear method."""
    try:
        b, h, d = (float(values[k]) * 1e3 for k in ("b", "h", "d"))
        fc = float(values["fc"])
        v = float(values.get("Vstep") or values.get("V") or 0.0)
        n = float(values.get("N") or 0.0)
        m = float(values.get("M") or 0.0) * 1e3
    except (KeyError, TypeError, ValueError):
        return None
    if v <= 0 or fc <= 0:
        return None
    av = float(values.get("Av") or 0.0) * 1e6
    s = float(values.get("s") or 0.0) * 1e3
    fyt = float(values.get("fyt") or values.get("fy") or 0.0)
    rho = float(values.get("rho") or 0.0) + float(values.get("rhoCompression") or 0.0)
    theta_y = float(values.get("thetaY") or 0.0)
    mu_pl = max(0.0, demand / theta_y - 1) if theta_y > 0 else 0.0
    fy = float(values.get("fy") or 0.0)
    a_net = (float(values.get("rho") or 0.0) - float(values.get("rhoCompression") or 0.0)) * b * d
    x = min(max((n + a_net * fy) / (0.85 * fc * b) / 0.8, 0.0), h)
    lv = float(values.get("LV") or 0.0) * 1e3
    vf = sum(f.vf for f in frp or [])
    vr = shear_strength(
        rule.shear, "column", b, h, d, fc, fyt, av, s, n, m, v, mu_pl, rho * d / h, x, lv, vf
    )
    if jacket is not None:
        vr *= rule.jacketing.shearFactor
    return v / vr if vr > 0 else math.inf


def nonlinear(
    root: Path, settings: Any, building: Any, objects: Any, materials: Any
) -> dict[str, Any]:
    """The nonlinear procedure: every pushover's hinges (``08 FEM/pushover.results``) with the
    assessment's changes (:func:`adjusted_hinge`), per member its largest ratio."""
    from saengine.fem import acceptance, hinges

    existing = settings.analysis.existingBuilding
    rule = table()
    know = knowledge(existing, rule)
    folder = root / "08 FEM"
    model, run = folder / "pushover.osmodel", folder / "pushover.results"
    notes: list[str] = []  # the knowledge level's procedures: noted by the assessment
    if not model.is_file() or not (run / "manifest.json").is_file():
        return {
            "procedure": "nonlinear",
            "rows": [],
            "notes": [*notes, "no pushover run: turn on Analysis model, Pushover, and run it"],
        }
    hinge_rules = hinges.table()
    if hinge_rules is None:
        return {
            "procedure": "nonlinear",
            "rows": [],
            "notes": [*notes, "the code pack gives no pushover hinges"],
        }
    levels = [lv.id for lv in hinge_rules.levels]
    found = strengths(existing, rule, materials)
    member_data = {m.id: m for m in members(building, objects, materials, existing)}
    by_member: dict[str, dict[str, Any]] = {}
    for item in acceptance.pushover_results(run, model):
        accepted = item.get("acceptance") or {}
        if accepted.get("method") != "hingeRotation" or not accepted.get("available"):
            continue
        checked = accepted.get("checkedLevel") or levels[-1]
        for row in accepted.get("rows", []):
            member = str(row.get("member", "")).split("#")[0]
            data = member_data.get(member)
            frps: list[Frp] = []
            jacket = None
            if data is not None and data.after is not None:
                cap = capacity(data.after, found, rule.strengths.deformation, know.cf, rule, False)
                frps = cap.frp
                jacket = data.after.jacket
            before = adjusted_hinge(row, rule, know, hinge_rules, levels, checked)
            after = adjusted_hinge(row, rule, know, hinge_rules, levels, checked, jacket, frps)
            entry = by_member.setdefault(
                member,
                {
                    "member": member,
                    "component": row.get("component"),
                    "type": data.type_id if data else "",
                    "measures": data.measures if data else [],
                    "covered": False,
                    "asBuilt": None,
                    "retrofitted": None,
                    "notes": [],
                },
            )
            for key, adjusted in (("asBuilt", before), ("retrofitted", after)):
                if not adjusted.get("covered"):
                    continue
                entry["covered"] = True
                ratio = adjusted.get("ratio")
                current = entry[key]
                if current is None or (ratio or 0.0) > (current["ratio"] or 0.0):
                    entry[key] = {
                        "ratio": ratio,
                        "action": "shear" if adjusted.get("shear", 0) == ratio else "rotation",
                        "level": adjusted.get("state"),
                        "hinge": adjusted.get("hinge"),
                        "case": item.get("label"),
                        "checked": checked,
                    }
    return {"procedure": "nonlinear", "rows": list(by_member.values()), "notes": notes}


# ───────────────────────────────────── the assessment ─────────────────────────────────────


def _state_path(root: Path, state: str) -> Path:
    return root / "08 FEM" / STATE_FILE.format(state=state)


def _summary(project: dict[str, Any], project_path: Any) -> dict[str, Any]:
    from saengine.fem.story_response import _derivation_summary

    return _derivation_summary(project, project_path)


def assessment(out_dir: str | Path, project_path: str | Path) -> dict[str, Any]:
    """The assessment of the existing building of the run ``out_dir`` of the analysis model at
    ``project_path`` (``08 FEM/model.osmodel``), by its procedure, with the before and after
    comparison; kept as ``08 FEM/existing-<state>.json``."""
    from saengine.fem.combinations import settings_beside

    settings = settings_beside(project_path)
    if settings is None:
        return {"available": False, "reason": "the project settings cannot be read"}
    if getattr(settings.analysis, "existingBuilding", None) is None:
        return {"available": False, "reason": "the project is not an existing building"}
    return _assessment(out_dir, project_path, settings=settings)


@code_context.in_project_pack(path_params=("project_path",))
def _assessment(out_dir: Any, project_path: Any, settings: Any) -> dict[str, Any]:
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    rule = table()
    if rule is None:
        return {
            "available": False,
            "reason": f"the code pack {code_context.code_name()} does not cover the assessment "
            "of existing buildings",
        }
    existing = settings.analysis.existingBuilding
    root = Path(project_path).resolve().parent.parent
    building = _read(root, BIM_FILE, BuildingModel)
    objects = _read(root, OBJECTS_FILE, ObjectLibrary)
    materials = _read(root, MATERIALS_FILE, MaterialLibrary)
    if building is None or objects is None or materials is None:
        return {
            "available": False,
            "reason": "the building model, objects or materials cannot be read",
        }
    know = knowledge(existing, rule)
    found = strengths(existing, rule, materials)
    notes = [know.note] if know.note else []
    for ms in found.values():
        notes += [f"{ms.material}: {n}" if ms.material else n for n in ms.notes]
    if existing.procedure not in know.procedures:
        notes.append(
            f"knowledge level {know.label}: the code pack does not permit the "
            f"{existing.procedure} procedure"
        )
    project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    try:
        if existing.procedure == "nonlinear":
            result = nonlinear(root, settings, building, objects, materials)
        else:
            result = linear(
                project,
                out_dir,
                settings,
                building,
                objects,
                materials,
                _summary(project, project_path),
            )
    except ValueError as error:
        return {"available": False, "reason": str(error)}
    state = existing.state
    other = STATES[1 - STATES.index(state)]
    previous = _load_state(root, other)
    levels = (
        [lv.id for lv in rule.linear.levels] if result["procedure"] == "linear" else _hinge_levels()
    )
    rows = []
    for row in result["rows"]:
        here = row.get(state)
        alt = row.get(other)
        kept = (previous or {}).get(row["member"])
        if kept is not None:
            alt = kept
        rows.append(
            {
                **{k: v for k, v in row.items() if k not in STATES},
                state: here,
                other: alt,
                "otherFrom": "run" if kept is not None else "preview",
            }
        )
    rows.sort(key=lambda r: -((r.get(state) or {}).get("ratio") or 0.0))
    covered = [r for r in rows if r.get("covered") and r.get(state)]
    failed = sum(1 for r in covered if (r[state].get("ratio") or 0.0) > 1 + 1e-9)
    hazards = _hazard_summary(rule, covered, state) if result["procedure"] == "linear" else []
    out = {
        "available": True,
        "state": state,
        "procedure": result["procedure"],
        "method": result.get("method"),
        "basis": rule.basis or code_context.code_name(),
        "clause": clause("linear" if result["procedure"] == "linear" else "nonlinear")
        or rule.source,
        "knowledge": {
            "id": know.id,
            "label": know.label,
            "kappa": know.kappa,
            "cf": know.cf,
            "clause": clause("knowledge"),
        },
        "strengths": [ms.row() for ms in found.values() if ms.material],
        "levels": levels,
        "hazards": hazards,
        "rows": rows,
        "failed": failed,
        "checked": len(covered),
        "level": _building_level(covered, state, levels),
        "factors": result.get("factors"),
        "checklist": _checklist(rule, existing),
        "measures": [
            {"id": m.id, "kind": m.kind, "members": list(m.members)}
            for m in getattr(existing, "retrofit", []) or []
        ],
        "notes": [
            n
            for n in (
                *notes,
                *result.get("notes", []),
                rule.linear.note if result["procedure"] == "linear" else rule.nonlinear.note,
                rule.note,
            )
            if n
        ],
    }
    _save_state(root, state, rows)
    return out


def _hinge_levels() -> list[str]:
    from saengine.fem import hinges

    rules = hinges.table()
    return [lv.id for lv in rules.levels] if rules is not None else []


def _hazard_summary(rule: Any, rows: list[dict[str, Any]], state: str) -> list[dict[str, Any]]:
    out = []
    for hazard in rule.linear.hazards:
        ratios = [
            (r[state].get("hazards") or {}).get(hazard.id) for r in rows if r.get(state) is not None
        ]
        ratios = [x for x in ratios if x is not None]
        failed = sum(1 for x in ratios if x > 1 + 1e-9)
        out.append(
            {
                "id": hazard.id,
                "label": hazard.label or hazard.id,
                "level": hazard.level,
                "scale": hazard.spectrumScale,
                "failed": failed,
                "worst": max(ratios, default=None),
                "ok": failed == 0,
            }
        )
    return out


def _building_level(rows: list[dict[str, Any]], state: str, levels: list[str]) -> str | None:
    """The building's performance level: the lowest level every member meets."""
    if not rows or not levels:
        return None
    rank = {lv: k for k, lv in enumerate(levels)}
    worst = -1
    for r in rows:
        level = (r.get(state) or {}).get("level")
        if level is None or level == "elastic":
            continue
        worst = max(worst, rank.get(level, len(levels)))
    if worst < 0:
        return None
    return levels[worst] if worst < len(levels) else f">{levels[-1]}"


def _checklist(rule: Any, existing: Any) -> list[dict[str, Any]]:
    answers = {a.item: a for a in getattr(existing, "checklist", []) or []}
    out = []
    for item in rule.tier1:
        answer = answers.get(item.id)
        out.append(
            {
                "id": item.id,
                "label": item.label,
                "group": item.group,
                "answer": answer.answer if answer else "U",
                "note": answer.note if answer else "",
            }
        )
    return out


def _save_state(root: Path, state: str, rows: list[dict[str, Any]]) -> None:
    kept = {r["member"]: r.get(state) for r in rows if r.get(state) is not None}
    try:
        _state_path(root, state).write_text(
            json.dumps({"state": state, "members": kept}, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass  # the comparison then previews the other state


def _load_state(root: Path, state: str) -> dict[str, Any] | None:
    try:
        found = json.loads(_state_path(root, state).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    members_ = found.get("members") if isinstance(found, dict) else None
    return members_ if isinstance(members_, dict) else None

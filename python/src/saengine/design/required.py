"""Design mode, part 1: the reinforcement each designed element REQUIRES (as ETABS and SAFE
report it), next to what the engineer has entered.

The demands are the design checks' own (:func:`saengine.design.check.design` is run once with
a ``collect`` dict, which hands back the combined section forces of every beam and column, the
strip averages of every slab and the checks): nothing is analysed or combined twice. Members
whose object type has no reinforcement yet are checked with assumed bars (:data:`ASSUMED`,
only for their effective depths) so that their demands come out too. Foundations come from
the substructure report (:func:`saengine.substructure.substructure_report`), the flexure
checks of each footing, pile cap and raft giving its moments per direction.

The formulas and clauses are those of :mod:`saengine.design.bars`; per element and location
(beam zones, column, slab strip and layer, footing direction and face) a row
``{"element", "kind", "type", "location", "quantity", "demand", "demandUnit", "required",
"min", "provided", "unit", "combination", "ok", "tooSmall", "notes"}``: ``required`` the
steel to provide (As,min included), ``min`` the minimum on its own, ``provided`` the steel of
the bars entered (None when there are none or they were assumed).
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.design import bars as B
from saengine.design import slab as slab_design
from saengine.design.rc import (
    DesignError,
    InteractionSurface,
    RcSection,
    bar_area,
    section_of,
)
from saengine.library.bim import BuildingModel
from saengine.library.materials import Category, MaterialLibrary, default_of
from saengine.library.objects import (
    CircleProfile,
    Column,
    LinearReinforcement,
    ObjectLibrary,
    PlanarReinforcement,
    RectangleProfile,
    Slab,
)
from saengine.library.settings import ProjectSettings

#: Bars assumed for members without reinforcement, only to find their effective depths.
ASSUMED = {
    "beam": {
        "cover": 40,
        "longitudinal": [
            {"position": "top", "count": 2, "dia": 20},
            {"position": "bottom", "count": 2, "dia": 20},
        ],
        "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
    },
    "column": {
        "cover": 40,
        "longitudinal": [{"position": "perimeter", "count": 4, "dia": 20}],
        "transverse": {"type": "tie", "dia": 10, "spacing": 150, "legs": 2},
    },
    "columnCircle": {
        "cover": 40,
        "longitudinal": [{"position": "perimeter", "count": 6, "dia": 20}],
        "transverse": {"type": "tie", "dia": 10, "spacing": 150, "legs": 2},
    },
    "slab": {
        "cover": 20,
        "bottomX": {"dia": 10, "spacing": 200},
        "bottomY": {"dia": 10, "spacing": 200},
        "topX": {"dia": 10, "spacing": 200},
        "topY": {"dia": 10, "spacing": 200},
    },
    # Integrator glue: structural walls (saengine.design.wall_design).
    "wall": {
        "cover": 25,
        "vertical": {"dia": 10, "spacing": 200},
        "horizontal": {"dia": 10, "spacing": 200},
        "layers": 2,
    },
}

#: Beam zones along a member, as shares of its length.
ZONES = (("start", 0.0, 0.25), ("middle", 0.25, 0.75), ("end", 0.75, 1.0))

#: Tolerance when comparing the steel provided with the steel required.
TOLERANCE = 1e-3


@dataclass
class Options:
    """The design mode's choices (``options`` of the RPC methods, all optional)."""

    diameters: tuple[float, ...] = B.MAIN_DIAMETERS
    column_diameters: tuple[float, ...] = B.COLUMN_DIAMETERS
    slab_diameters: tuple[float, ...] = B.SLAB_DIAMETERS
    footing_diameters: tuple[float, ...] = (12.0, 16.0, 20.0, 25.0)
    stirrup_diameters: tuple[float, ...] = B.STIRRUP_DIAMETERS
    max_sizes: int = 2  # bar sizes in a beam (top and bottom), stirrups not counted
    over_design: float = 0.25  # members whose own bars would be this much less are listed
    max_new_types: int = 3  # per object type, when splitting
    beam_ratio_max: float = B.BEAM_RATIO_MAX
    rho_min: float = B.RHO_MIN
    rho_max: float = B.RHO_MAX
    min_slab_spacing: float = B.MIN_SLAB_SPACING
    min_stirrup_spacing: float = B.MIN_STIRRUP_SPACING

    @classmethod
    def of(cls, options: dict[str, Any] | None) -> Options:
        """From the RPC's ``options``: ``diameters`` (main bars, all members; slabs take those up
        to 16 mm, columns those from 16 mm), ``stirrupDiameters``, ``maxSizes``,
        ``overDesign``, ``maxNewTypes``."""
        options = options or {}
        result = cls()
        dias = options.get("diameters")
        if dias:
            main = tuple(sorted({float(d) for d in dias if float(d) > 0}))
            result.diameters = tuple(d for d in main if d >= 12) or main
            result.column_diameters = tuple(d for d in main if d >= 16) or result.diameters
            result.slab_diameters = tuple(d for d in main if d <= 16) or main[:2]
            result.footing_diameters = tuple(d for d in main if d >= 12) or main
        stirrups = options.get("stirrupDiameters")
        if stirrups:
            result.stirrup_diameters = tuple(sorted({float(d) for d in stirrups if float(d) > 0}))
        if options.get("maxSizes"):
            result.max_sizes = max(1, int(options["maxSizes"]))
        if options.get("overDesign") is not None:
            result.over_design = max(0.0, float(options["overDesign"]))
        if options.get("maxNewTypes") is not None:
            result.max_new_types = max(0, int(options["maxNewTypes"]))
        return result


# ─────────────────────────────────────── gathering ───────────────────────────────────────


@dataclass
class Gathered:
    """The checks and what they worked from."""

    root: Path
    report: dict[str, Any]
    collect: dict[str, Any]
    objects_text: str
    objects: ObjectLibrary  # with the assumed bars
    assumed: set[str]
    materials: MaterialLibrary
    building: BuildingModel
    settings: ProjectSettings
    substructure: dict[str, Any] | None = None
    context: Any = None  # the substructure's Context
    notes: list[str] = field(default_factory=list)
    #: The design report as :func:`saengine.design.design_report` makes it (without the assumed
    #: bars): ``report`` itself when none were assumed, None when it cannot be told from these
    #: checks (types other than slabs without bars).
    plain: dict[str, Any] | None = None
    #: :func:`column_requirements` per set of options, with the surfaces their searches built:
    #: Run All's required steel and the proposal made from these checks share them.
    searches: dict[tuple[Any, ...], Any] = field(default_factory=dict)


def _default_rebar(objects: dict[str, Any], materials: MaterialLibrary) -> str | None:
    """The reinforcement material the project's object types use most, else the project's
    (``defaults.rebar`` of the materials, as a generated building records it), else the first
    one."""
    counts: dict[str, int] = {}
    for o in objects.get("objects", []):
        material = (o.get("reinforcement") or {}).get("material")
        if material:
            counts[material] = counts.get(material, 0) + 1
    if counts:
        return max(counts, key=lambda m: counts[m])
    return default_of(materials, Category.REBAR)


def with_assumed_bars(
    objects_text: str, materials: MaterialLibrary
) -> tuple[ObjectLibrary, set[str]]:
    """The object library with :data:`ASSUMED` bars on concrete beams, columns and slabs that
    have none, and the ids of those types."""
    data = json.loads(objects_text)
    rebar = _default_rebar(data, materials)
    concrete = {m.id for m in materials.materials if m.category == Category.CONCRETE}
    assumed: set[str] = set()
    for o in data.get("objects", []):
        kind = o.get("kind")
        if o.get("reinforcement") or rebar is None or o.get("material") not in concrete:
            continue
        if kind == "column" and (o.get("profile") or {}).get("shape") == "circle":
            key = "columnCircle"
        elif kind in ("beam", "column", "slab") or kind == "wall" and o.get("structural", True):
            key = kind
        else:
            continue
        o["reinforcement"] = {"material": rebar, **json.loads(json.dumps(ASSUMED[key]))}
        assumed.add(o["id"])
    return ObjectLibrary.model_validate(data), assumed


def gather(out_dir: str | Path, project_path: str | Path, substructure: bool = True) -> Gathered:
    """Runs the design checks (and the substructure's) once, collecting their demands."""
    from saengine.design.check import design

    project_path = Path(project_path)
    root = project_path.resolve().parent.parent

    def read(relative: str) -> str:
        try:
            return (root / relative).read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"{relative} could not be read: {error}") from error

    settings = ProjectSettings.model_validate_json(
        read("02 Project Settings/project-settings.json")
    )
    materials = MaterialLibrary.model_validate_json(read("03 Materials/materials.json"))
    objects_text = read("04 Objects/objects.json")
    objects, assumed = with_assumed_bars(objects_text, materials)
    building = BuildingModel.model_validate_json(read("06 BIM/bim.json"))
    project = json.loads(project_path.read_text(encoding="utf-8"))
    collect: dict[str, Any] = {}
    from saengine.design.check import ensure_seismic_design

    ensure_seismic_design(out_dir, project_path, settings)
    report = design(
        project, out_dir, building, objects, materials, settings, collect=collect, assumed=assumed
    )
    plain = collect.pop("plain", None) if assumed else report
    gathered = Gathered(
        root, report, collect, objects_text, objects, assumed, materials, building, settings
    )
    gathered.plain = plain
    if substructure and (root / "09 Substructure" / "substructure.json").exists():
        from saengine.substructure.context import load_context
        from saengine.substructure.report import report as substructure_report

        try:
            gathered.context = load_context(root, out_dir)
            gathered.substructure = substructure_report(gathered.context)
        except ValueError as error:
            gathered.notes.append(f"9 Substructure not designed: {error}")
    return gathered


# ─────────────────────────────────────── beams ───────────────────────────────────────


@dataclass
class Peak:
    value: float = 0.0
    combination: str | None = None
    where: str = ""

    def take(self, value: float, combination: str | None, where: str) -> None:
        if value > self.value:
            self.value, self.combination, self.where = value, combination, where


@dataclass
class BeamDemand:
    """A beam member's envelope per zone: sagging and hogging moments [N·mm], shear [N]."""

    zones: dict[str, dict[str, Peak]]

    def overall(self, what: str) -> Peak:
        best = Peak()
        for zone in self.zones.values():
            p = zone[what]
            best.take(p.value, p.combination, p.where)
        return best


def _ordered(pieces: list[Any]) -> list[Any]:
    def key(p: Any) -> int:
        _, _, suffix = p.name.partition("#")
        return int(suffix) if suffix.isdigit() else 1

    return sorted(pieces, key=key)


def beam_demand(member: dict[str, Any], combinations: list[str]) -> BeamDemand:
    """The envelope of a collected beam member (the checks' forces, :func:`check.
    _profile_forces`) in its :data:`ZONES`."""
    from saengine.design.check import _profile_forces, _where

    zones = {name: {"sag": Peak(), "hog": Peak(), "shear": Peak()} for name, _, _ in ZONES}
    pieces = _ordered(member["pieces"])
    total = sum(p.length for p in pieces) or 1.0
    start = 0.0
    for piece in pieces:
        at_station: dict[int, list[dict[str, Peak]]] = {}  # stations -> zone of each
        for c, forces in enumerate(piece.forces):
            values = _profile_forces(piece, member["turned"], forces)
            count = len(forces)
            if count not in at_station:
                at_station[count] = []
                for k in range(count):
                    at = (start + piece.length * k / max(count - 1, 1)) / total
                    zone = next(n for n, lo, hi in ZONES if at <= hi + 1e-9 or hi == 1.0)
                    at_station[count].append(zones[zone])
            for k, z in enumerate(at_station[count]):
                moment, v = float(values["Mx"][k]), abs(float(values["Vy"][k]))
                # Where the station is said only when it governs (the slow part otherwise).
                if -moment > z["sag"].value or moment > z["hog"].value or v > z["shear"].value:
                    where = _where(piece, k, count)
                    z["sag"].take(-moment, combinations[c], where)
                    z["hog"].take(moment, combinations[c], where)
                    z["shear"].take(v, combinations[c], where)
        start += piece.length
    return BeamDemand(zones)


@dataclass(frozen=True)
class BeamGeometry:
    b: float
    h: float
    d_bottom: float
    d_top: float
    fc: float
    fy: float
    es: float
    fyt: float


def beam_geometry(member: dict[str, Any]) -> BeamGeometry:
    section: RcSection = member["section"]
    h, b = section.depth, section.width
    inset = member["object"].reinforcement.cover + section.transverse_dia

    def depth(top: bool) -> float:
        try:
            return section.effective_depth(top=top)
        except DesignError:  # no bars on that face: one row of Ø20 assumed
            return h - inset - 10

    return BeamGeometry(
        b, h, depth(False), depth(True), member["fc"], member["fy"], member["es"], member["fy"]
    )


def _face_area(section: RcSection, top: bool) -> float:
    return sum(b.area for b in section.bars if (b.y > 0 if top else b.y < 0))


def _row(
    element: str,
    kind: str,
    type_id: str,
    location: str,
    quantity: str,
    demand: float | None,
    demand_unit: str,
    required: float,
    minimum: float | None,
    provided: float | None,
    unit: str,
    combination: str | None,
    notes: list[str],
    too_small: bool = False,
    fails: bool = False,
    at_most: bool = False,
) -> dict[str, Any]:
    """One row of the report (see the module notes); ``at_most``: ``required`` is a largest
    value (a spacing), which ``provided`` must not exceed."""
    if provided is None:
        ok = None
    elif at_most:
        ok = bool(provided <= required * (1 + TOLERANCE) and not too_small and not fails)
    else:
        ok = bool(provided >= required * (1 - TOLERANCE) and not too_small and not fails)
    return {
        "element": element,
        "kind": kind,
        "type": type_id,
        "location": location,
        "quantity": quantity,
        "demand": None if demand is None else round(float(demand), 2),
        "demandUnit": demand_unit,
        "required": round(float(required), 1),
        "min": None if minimum is None else round(float(minimum), 1),
        "provided": None if provided is None else round(float(provided), 1),
        "unit": unit,
        "combination": combination,
        "ok": ok,
        "tooSmall": bool(too_small),
        "notes": "; ".join(n for n in notes if n),
    }


@dataclass
class BeamNeed:
    """What a beam member (or a type's envelope) needs, at the given depths."""

    bottom: float  # mm², to provide
    top: float
    av_s: float  # mm²/mm
    s_max: float
    too_small: list[str]


def beam_need(
    geometry: BeamGeometry,
    sag: float,
    hog: float,
    vu: float,
    ratio_max: float = B.BEAM_RATIO_MAX,
) -> tuple[BeamNeed, B.FlexureNeed, B.FlexureNeed, B.ShearNeed]:
    g = geometry
    sag_need = B.beam_flexure_need(
        sag, g.b, g.d_bottom, g.h - g.d_top, g.fc, g.fy, g.es, ratio_max, g.h
    )
    hog_need = B.beam_flexure_need(
        hog, g.b, g.d_top, g.h - g.d_bottom, g.fc, g.fy, g.es, ratio_max, g.h
    )
    shear_need = B.beam_shear_need(vu, g.b, g.d_bottom, g.fc, g.fyt)
    bottom = max(
        B.with_minimum(sag_need.area, B.beam_min_area(g.b, g.d_bottom, g.fc, g.fy)),
        hog_need.compression,
    )
    top = max(
        B.with_minimum(hog_need.area, B.beam_min_area(g.b, g.d_top, g.fc, g.fy)),
        sag_need.compression,
    )
    small = [
        n.note
        for n in (sag_need, hog_need, shear_need)
        if n.too_small  # type: ignore[union-attr]
    ]
    return (
        BeamNeed(bottom, top, shear_need.av_s, shear_need.s_max, small),
        sag_need,
        hog_need,
        (shear_need),
    )


def beam_rows(member: dict[str, Any], demand: BeamDemand, assumed: bool) -> list[dict[str, Any]]:
    section: RcSection = member["section"]
    g = beam_geometry(member)
    obj = member["object"]
    transverse = obj.reinforcement.transverse
    rows: list[dict[str, Any]] = []
    element, type_id = member["id"], member["type"]
    for zone, _, _ in ZONES:
        z = demand.zones[zone]
        _, sag, hog, shear = beam_need(g, z["sag"].value, z["hog"].value, z["shear"].value)
        for top, need, other, peak, label in (
            (False, sag, hog, z["sag"], "bottom bars (sagging)"),
            (True, hog, sag, z["hog"], "top bars (hogging)"),
        ):
            d = g.d_top if top else g.d_bottom
            minimum = B.beam_min_area(g.b, d, g.fc, g.fy)
            required = max(B.with_minimum(need.area, minimum), other.compression)
            notes = [need.note, f"d = {d:.0f} mm"]
            if other.compression > 0 and other.compression >= B.with_minimum(need.area, minimum):
                other_moment = "sagging" if top else "hogging"
                notes.append(f"governed by the compression bars of the {other_moment} moment")
            if peak.where:
                notes.append(peak.where)
            if 0 < need.area and required < minimum:
                notes.append("4/3 of the bars required, below As,min (ACI 9.6.1.3)")
            rows.append(
                _row(
                    element,
                    "beam",
                    type_id,
                    zone,
                    label,
                    peak.value / 1e6,
                    "kN·m",
                    required,
                    minimum if need.area > 0 else None,
                    None if assumed else _face_area(section, top),
                    "mm²",
                    peak.combination,
                    notes,
                    need.too_small,
                )
            )
        peak = z["shear"]
        provided = None
        if transverse is not None and not assumed:
            provided = transverse.legs * bar_area(transverse.dia) / transverse.spacing * 1000
        notes = [shear.note, peak.where]
        wide = transverse is not None and not assumed and transverse.spacing > shear.s_max
        if wide:
            notes.append(f"stirrup spacing {transverse.spacing:g} mm above {shear.s_max:.0f} mm")
        rows.append(
            _row(
                element,
                "beam",
                type_id,
                zone,
                "stirrups Av/s",
                peak.value / 1e3,
                "kN",
                shear.av_s * 1000,
                shear.av_s_min * 1000,
                provided,
                "mm²/m",
                peak.combination,
                notes,
                shear.too_small,
                wide,
            )
        )
    rows += torsion_rows(member, assumed)
    return rows


def torsion_rows(member: dict[str, Any], assumed: bool) -> list[dict[str, Any]]:
    """The closed stirrups and longitudinal steel a beam's torsion needs (BNBC 2020 Part 6
    Sec 6.4.4), from the torsion design of its checks (``member["torsion"]``, saengine.design.
    torsion; none below the threshold)."""
    design = member.get("torsion")
    if design is None:
        return []
    obj = member["object"]
    transverse = obj.reinforcement.transverse
    element, type_id = member["id"], member["type"]
    leg = None
    if transverse is not None and not assumed and transverse.spacing:
        leg = bar_area(transverse.dia) / transverse.spacing * 1000
    # Each outer leg carries At/s and its share of the shear's Av/s, as the design check does
    # (saengine.design.torsion.torsion_checks); two legs when the stirrups are not known.
    legs = transverse.legs if transverse is not None and not assumed and transverse.legs else 2
    av_s = float(getattr(design, "av_s", 0.0))
    return [
        _row(
            element,
            "beam",
            type_id,
            "torsion",
            "closed stirrups At/s + Av/(n s) per outer leg (shear at the governing station)",
            design.tu_design / 1e6,
            "kN·m",
            (design.at_s + av_s / legs) * 1000,
            design.at_s_min * 1000,
            leg,
            "mm²/m",
            None,
            [
                f"Tu = {design.tu / 1e6:.1f} kN·m ({design.kind})",
                (
                    f"At/s = {design.at_s * 1000:.0f} mm²/m per leg, shear Av/s = "
                    f"{av_s * 1000:.0f} mm²/m over {legs} legs (Sec 6.4.4.3.8)"
                ),
                f"s ≤ {design.s_max:.0f} mm (Sec 6.4.4.6.1)",
            ],
            not design.section_ok,
            bool(transverse is not None and not assumed and transverse.spacing > design.s_max),
        ),
        _row(
            element,
            "beam",
            type_id,
            "torsion",
            "longitudinal bars Al around the perimeter",
            design.tu_design / 1e6,
            "kN·m",
            design.al,
            design.al_min,
            None,
            "mm²",
            None,
            [
                (
                    "on top of the flexural bars of the moment at the same station "
                    "(Sec 6.4.4.3.8; the design check compares the sum with all the bars)"
                ),
                (
                    f"bars ≥ Ø{max(design.long_dia_min, 10.0):.0f}, ≤ 300 mm apart, one in "
                    "each corner (Sec 6.4.4.6.2)"
                ),
            ],
            not design.section_ok,
        ),
    ]


# ─────────────────────────────────────── columns ───────────────────────────────────────


Point = tuple[float, float, float, str, str]  # Pu, |Mux|, |Muy| (N, N·mm), combination, where


def column_points(member: dict[str, Any], combinations: list[str]) -> list[Point]:
    """Every station's demand of a collected column member, as its checks take them: the
    checks' own points when they collected them (with the moments magnified for slenderness,
    :mod:`saengine.design.slender`), else the stations' section forces."""
    from saengine.design.check import _profile_forces, _where

    if member.get("points") is not None:
        return list(member["points"])
    points: list[Point] = []
    for piece in member["pieces"]:
        for c, forces in enumerate(piece.forces):
            values = _profile_forces(piece, member["turned"], forces)
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
    return points


class ColumnSearch:
    """The practical layouts of one column type (:func:`bars.column_layouts`), sorted by steel
    area, and their interaction surfaces, built when first asked for: the coarse ones to
    search, the full one to confirm (the checks' own)."""

    def __init__(
        self,
        obj: Column,
        fc: float,
        fy: float,
        es: float,
        aggregate: float | None,
        options: Options,
    ) -> None:
        self.obj = obj
        self.fc, self.fy, self.es, self.aggregate = fc, fy, es, aggregate
        self.options = options
        profile = obj.profile
        self.cover = obj.reinforcement.cover if obj.reinforcement else 40.0
        self.tie = 10.0
        inset = self.cover + self.tie
        if isinstance(profile, CircleProfile):
            self.shape, self.b, self.h = "circle", 2 * profile.radius, 2 * profile.radius
        else:
            assert isinstance(profile, RectangleProfile)
            self.shape, self.b, self.h = "rectangle", profile.xDim, profile.yDim
        self.gross = math.pi * self.b**2 / 4 if self.shape == "circle" else self.b * self.h
        self.layouts = B.column_layouts(
            self.shape,
            self.b,
            self.h,
            inset,
            options.column_diameters,
            aggregate,
            options.rho_min,
            options.rho_max,
        )
        self._surfaces: dict[tuple[int, bool], InteractionSurface] = {}
        #: Results per (layout, coarse, points list), the list kept so a reused id never
        #: returns another list's result.
        self._worst: dict[tuple[int, bool, int], tuple[list[Point], float]] = {}
        self._rows: dict[int, tuple[list[Point], np.ndarray]] = {}

    def reinforcement(self, layout: B.ColumnLayout, ties: B.Ties | None = None) -> dict[str, Any]:
        current = self.obj.reinforcement
        transverse = {"type": "tie", "dia": self.tie, "spacing": 150.0, "legs": 2}
        if ties is not None:
            transverse = {
                "type": "tie",
                "dia": ties.dia,
                "spacing": ties.spacing,
                "legs": ties.legs,
            }
        if current is not None and current.transverse and current.transverse.type == "spiral":
            transverse = current.transverse.model_dump(mode="json")  # kept (ACI 25.7.3)
        return {
            "material": current.material if current else "",
            "cover": self.cover,
            "longitudinal": [{"position": "perimeter", "count": layout.count, "dia": layout.dia}],
            "transverse": transverse,
        }

    def section(self, index: int) -> RcSection:
        reinforcement = LinearReinforcement.model_validate(
            {**self.reinforcement(self.layouts[index]), "material": "x"}
        )
        return section_of(
            self.obj.profile, reinforcement, self.fc, self.fy, self.es, self.aggregate
        )

    def surface(self, index: int, coarse: bool) -> InteractionSurface:
        key = (index, coarse)
        if key not in self._surfaces:
            self._surfaces[key] = InteractionSurface(self.section(index), coarse)
        return self._surfaces[key]

    def _demands(self, points: list[Point]) -> np.ndarray:
        """The (Pu, Mux, Muy) rows of ``points``, made once per list."""
        key = id(points)
        found = self._rows.get(key)
        if found is None or found[0] is not points:
            if len(self._rows) > 64:
                self._rows.clear()
            found = (points, np.array([p[:3] for p in points], dtype=float).reshape(-1, 3))
            self._rows[key] = found
        return found[1]

    def utilisation(self, index: int, points: list[Point], coarse: bool = True) -> float:
        key = (index, coarse, id(points))
        found = self._worst.get(key)
        if found is not None and found[0] is points:
            return found[1]
        worst = self.surface(index, coarse).max_utilisation(self._demands(points))
        self._worst[key] = (points, worst)
        return worst

    def carries(self, index: int, points: list[Point], coarse: bool = True) -> bool:
        """Whether layout ``index`` carries every point (stops at the first that it does not)."""
        key = (index, coarse, id(points))
        found = self._worst.get(key)
        if found is not None and found[0] is points:
            return found[1] <= 1.0
        surface = self.surface(index, coarse)
        worst = surface.max_utilisation(self._demands(points), stop_above=1.0)
        if worst <= 1.0:
            # Every demand was worked out: the largest utilisation, kept for utilisation().
            self._worst[key] = (points, worst)
        return worst <= 1.0

    def smallest(self, points: list[Point]) -> int | None:
        """The index of the smallest layout whose coarse surface carries ``points`` (bisection
        over the sorted layouts), or None when even the largest does not."""
        if not self.layouts:
            return None
        lo, hi = 0, len(self.layouts) - 1
        if not self.carries(hi, points):
            return None
        while lo < hi:
            mid = (lo + hi) // 2
            if self.carries(mid, points):
                hi = mid
            else:
                lo = mid + 1
        return lo

    def confirm(self, index: int, points: list[Point]) -> int | None:
        """``index`` or the next layouts up, the first that the full surface (the checks')
        carries ``points`` with."""
        for k in range(index, len(self.layouts)):
            if self.carries(k, points, coarse=False):
                return k
        return None

    def required_area(self, index: int | None, points: list[Point]) -> float | None:
        """The steel the points need [mm²], interpolated between the layout below ``index``
        (which fails) and ``index`` on their utilisations; ρ_min Ag when the smallest layout
        carries them; None when none does."""
        if index is None:
            return None
        minimum = B.RHO_MIN * self.gross
        if index == 0:
            return max(minimum, 0.0)
        u_hi = self.utilisation(index, points)
        u_lo = self.utilisation(index - 1, points)
        a_lo, a_hi = self.layouts[index - 1].area, self.layouts[index].area
        if not math.isfinite(u_lo) or u_lo <= u_hi:
            return a_hi
        share = (u_lo - 1.0) / (u_lo - u_hi)
        return max(minimum, a_lo + min(max(share, 0.0), 1.0) * (a_hi - a_lo))


def column_rows(
    member: dict[str, Any],
    search: ColumnSearch,
    index: int | None,
    points: list[Point],
    assumed: bool,
) -> list[dict[str, Any]]:
    section: RcSection = member["section"]
    element, type_id = member["id"], member["type"]
    required = search.required_area(index, points)
    governing: Point | None = None
    if points and search.layouts:
        surface = search.surface(len(search.layouts) - 1 if index is None else index, True)
        governing = max(points, key=lambda p: surface.check(p[0], p[1], p[2]).utilisation)
    elif points:
        governing = max(points, key=lambda p: p[0])
    notes = []
    too_small = required is None
    if too_small:
        notes.append(
            f"no layout with ρ up to {B.RHO_MAX:g} carries the demand (ACI 10.6.1.1): section "
            "too small"
            if search.layouts
            else "no bar layout fits the section at the least clear spacing (ACI 25.2.3)"
        )
    elif index == 0:
        notes.append(f"ρ_min = {B.RHO_MIN:g} governs (ACI 10.6.1.1)")
    if governing is not None:
        notes.append(f"Pu = {governing[0] / 1e3:.1f} kN; {governing[4]}")
    rows = [
        _row(
            element,
            "column",
            type_id,
            "column",
            "longitudinal bars",
            None if governing is None else math.hypot(governing[1], governing[2]) / 1e6,
            "kN·m",
            required if required is not None else B.RHO_MAX * search.gross,
            B.RHO_MIN * search.gross,
            None if assumed else section.steel_area,
            "mm²",
            governing[3] if governing else None,
            notes
            + ([f"ρ required = {required / search.gross:.4f}"] if required is not None else []),
            too_small,
        )
    ]
    transverse = member["object"].reinforcement.transverse
    largest = max(b.dia for b in section.bars)
    tie_dia = transverse.dia if transverse else 10.0
    s_max = min(16 * largest, 48 * tie_dia, min(search.b, search.h))
    rows.append(
        _row(
            element,
            "column",
            type_id,
            "column",
            "tie spacing (max)",
            None,
            "",
            s_max,
            None,
            transverse.spacing if transverse and not assumed else None,
            "mm",
            None,
            [
                (
                    f"min(16 db, 48 dt, least dimension) = min({16 * largest:.0f}, "
                    f"{48 * tie_dia:.0f}, {min(search.b, search.h):.0f}) (ACI 25.7.2.1)"
                ),
                "seismic hoop zones: see the rows of BNBC Sec 8.3 below",
            ],
            at_most=True,
        )
    )
    return rows


def detailing_rows(member: dict[str, Any], assumed: bool) -> list[dict[str, Any]]:
    """The hoop zones BNBC 2020 Part 6 Sec 8.3 asks of a beam or column (the design report's
    ``detailing``, :mod:`saengine.design.seismic_detailing`): the largest spacing within lo and
    elsewhere, and lo, against the type's ``transverse`` (its ``zone`` when given)."""
    info = member.get("detailing") or {}
    zones = info.get("zones") or {}
    if not zones:
        return []
    transverse = member["object"].reinforcement.transverse
    zone = getattr(transverse, "zone", None) if transverse else None
    kind, element, type_id = member["kind"], member["id"], member["type"]
    clause = info.get("clause") or "BNBC 2020 Part 6 Sec 8.3"
    rows = []
    if zones.get("so") is not None:
        provided = None
        if transverse is not None and not assumed:
            provided = zone.spacing if zone else transverse.spacing
        rows.append(
            _row(
                element,
                kind,
                type_id,
                "ends (lo)",
                "hoop spacing in lo (max)",
                None,
                "",
                zones["so"],
                None,
                provided,
                "mm",
                None,
                [
                    clause,
                    zones.get("soRule") or "",
                    "" if zone else "no end zone entered: the type's spacing",
                ],
                at_most=True,
            )
        )
    if zones.get("lo") is not None:
        rows.append(
            _row(
                element,
                kind,
                type_id,
                "ends (lo)",
                "hoop zone length lo",
                None,
                "",
                zones["lo"],
                None,
                None if assumed or zone is None or zone.length is None else zone.length,
                "mm",
                None,
                [clause, "from each joint face"],
            )
        )
    if zones.get("outside") is not None:
        rows.append(
            _row(
                element,
                kind,
                type_id,
                "elsewhere",
                "hoop spacing elsewhere (max)",
                None,
                "",
                zones["outside"],
                None,
                None if transverse is None or assumed else transverse.spacing,
                "mm",
                None,
                [clause],
                at_most=True,
            )
        )
    return rows


# ─────────────────────────────────────── slabs ───────────────────────────────────────


@dataclass
class StripDemand:
    name: str
    kind: str
    direction: str
    width: float
    peaks: dict[str, Peak]  # layer name -> Wood-Armer design moment [N·m/m]


def strip_demands(collected: dict[str, Any], combinations: list[str]) -> list[StripDemand]:
    """Each design strip's largest Wood-Armer moments of its direction's two layers, from the
    strip averages the checks took (:attr:`slab.SlabContext.sections`)."""
    context = collected["context"]
    found: dict[tuple[str, str], StripDemand] = {}
    for section in context.sections:
        strip = section.strip
        key = (strip.name, strip.direction)
        if key not in found:
            found[key] = StripDemand(
                strip.name,
                strip.kind,
                strip.direction,
                strip.width,
                {f"bottom{strip.direction}": Peak(), f"top{strip.direction}": Peak()},
            )
        peaks = found[key].peaks
        for face, values in (("bottom", section.bottom), ("top", section.top)):
            c = int(max(range(len(values)), key=lambda k: values[k]))
            peaks[f"{face}{strip.direction}"].take(
                float(values[c]), combinations[c], f"station {section.at / 1e3:.2f} m"
            )
    return list(found.values())


def slab_depths(h: float, cover: float, dias: dict[str, float]) -> dict[str, float]:
    """Effective depths of the four layers, X outer on both faces (as
    :func:`slab.layers_of`), from the bar diameter of each layer (0: absent)."""
    result = {}
    for face in ("bottom", "top"):
        outer = dias.get(f"{face}X", 0.0)
        inner = dias.get(f"{face}Y", 0.0)
        result[f"{face}X"] = h - cover - (outer or 10.0) / 2
        result[f"{face}Y"] = h - cover - outer - (inner or 10.0) / 2
    return result


def slab_layer_rules(system: str, h: float, span: str | None) -> dict[str, tuple[float, str]]:
    """Largest spacing of each layer (as :func:`slab._max_spacing_check`)."""
    rules = {}
    for name in slab_design.LAYERS:
        if system != "oneWay":
            rules[name] = (min(2 * h, 450.0), "ACI 8.7.2.2: min(2h, 450 mm)")
        elif name[-1] == span:
            rules[name] = (min(3 * h, 450.0), "ACI 7.7.2.3: min(3h, 450 mm)")
        else:
            rules[name] = (min(5 * h, 450.0), "ACI 7.7.6.2.1: min(5h, 450 mm)")
    return rules


def slab_envelope(collected: dict[str, Any], combinations: list[str]) -> dict[str, Peak]:
    """The slab's largest Wood-Armer moment per layer [N·m/m] over all its strips (a slab on
    beams designed by the coefficient methods: its design moments,
    :attr:`saengine.design.slab.CoefficientDesign.envelope`)."""
    envelope = {name: Peak() for name in slab_design.LAYERS}
    design = collected.get("coefficients")
    if design is not None:
        for name, (value, combination, where) in design.envelope.items():
            if name in envelope:
                envelope[name].take(value, combination, where)
        return envelope
    for strip in strip_demands(collected, combinations):
        for name, peak in strip.peaks.items():
            envelope[name].take(peak.value, peak.combination, f"{strip.name}, {peak.where}")
    return envelope


def slab_layer_need(
    name: str,
    moment: float,
    d: float,
    h: float,
    fc: float,
    fy: float,
    es: float,
    in_span: bool,
    shear: tuple[float, str | None, str] | None,
) -> tuple[float, float | None, list[str], bool]:
    """(As to provide [mm²/m], As,min that applies or None, notes, too small) of one layer for
    its Wood-Armer moment ``moment`` [N·mm/m] and the one-way shear its ρ resists."""
    need = B.slab_flexure_need(moment, d, fc, fy, es)
    notes = [need.note, f"d = {d:.0f} mm"]
    as_min = slab_design.min_steel_ratio(fy) * 1000 * h
    applies = (name.startswith("bottom") and in_span) or (
        in_span and moment > slab_design.NO_DEMAND * 1e3
    )
    required = max(need.area, as_min if applies else 0.0)
    too_small = need.too_small
    if shear is not None and shear[0] > 0:
        rho = B.slab_shear_rho(shear[0], d, fc)
        if rho is None:
            too_small = True
            notes.append(
                f"one-way shear {shear[0] / 1e3:.1f} kN/m above φ 0.42 √f'c b d: the slab is too "
                "thin (no shear reinforcement)"
            )
        elif rho * 1000 * d > required:
            required = rho * 1000 * d
            notes.append(
                f"governed by one-way shear {shear[0] / 1e3:.1f} kN/m: ρ = {rho:.4f} for φVc "
                "(ACI 22.5.5.1 (c))"
            )
    return required, as_min if applies else None, notes, too_small


def slab_rows(collected: dict[str, Any], combinations: list[str], assumed: bool):
    obj: Slab = collected["object"]
    reinforcement: PlanarReinforcement = obj.reinforcement  # type: ignore[assignment]
    h, fc, fy, es = obj.thickness, collected["fc"], collected["fy"], collected["es"]
    layers = slab_design.layers_of(reinforcement, h)
    dias = {n: (layer.dia if layer else 0.0) for n, layer in layers.items()}
    depths = slab_depths(h, reinforcement.cover, dias)
    envelope = slab_envelope(collected, combinations)
    span = slab_design.span_direction(obj.system, {n: p.value * 1e3 for n, p in envelope.items()})
    rules = slab_layer_rules(obj.system, h, span)
    shear = collected["context"].shear
    rows = []
    design = collected.get("coefficients")
    if design is not None:
        method = "BNBC 6.5.8" if design.method == "twoWay" else "BNBC 6.1.4.3"
        for name, peak in envelope.items():
            in_span = design.span is None or name[-1] == design.span
            required, minimum, notes, small = slab_layer_need(
                name, peak.value * 1e3, depths[name], h, fc, fy, es, in_span, None
            )
            layer = layers.get(name)
            notes += [
                f"{method} coefficients",
                f"spacing ≤ {rules[name][0]:.0f} mm ({rules[name][1]})",
                peak.where,
            ]
            rows.append(
                _row(
                    collected["id"],
                    "slab",
                    collected["type"],
                    f"{name} ({method} coefficients)",
                    f"{name[:-1]} {name[-1]} bars",
                    peak.value / 1e3,
                    "kN·m/m",
                    required,
                    minimum,
                    None if assumed or layer is None else layer.area,
                    "mm²/m",
                    peak.combination,
                    notes,
                    small,
                )
            )
    for strip in [] if design is not None else strip_demands(collected, combinations):
        for name, peak in strip.peaks.items():
            in_span = span is None or name[-1] == span
            required, minimum, notes, small = slab_layer_need(
                name, peak.value * 1e3, depths[name], h, fc, fy, es, in_span, None
            )
            layer = layers.get(name)
            notes += [
                f"{strip.kind} strip {strip.width / 1e3:.2f} m wide",
                f"spacing ≤ {rules[name][0]:.0f} mm ({rules[name][1]})",
                peak.where,
            ]
            rows.append(
                _row(
                    collected["id"],
                    "slab",
                    collected["type"],
                    f"{strip.name} ({strip.kind}), {name}",
                    f"{name[:-1]} {name[-1]} bars",
                    peak.value / 1e3,
                    "kN·m/m",
                    required,
                    minimum,
                    None if assumed or layer is None else layer.area,
                    "mm²/m",
                    peak.combination,
                    notes,
                    small,
                )
            )
    for name, value in sorted(shear.items()):
        d = depths[name]
        rho = B.slab_shear_rho(value[0], d, fc)
        layer = layers.get(name)
        rows.append(
            _row(
                collected["id"],
                "slab",
                collected["type"],
                f"one-way shear, {name}",
                f"{name[:-1]} {name[-1]} bars for φVc",
                value[0] / 1e3,
                "kN/m",
                (rho if rho is not None else 0.0) * 1000 * d,
                None,
                None if assumed or layer is None else layer.area,
                "mm²/m",
                value[1],
                [
                    "ρ for φ 0.66 λs ρ^(1/3) √f'c b d (ACI 22.5.5.1 (c))",
                    value[2],
                    "" if rho is not None else "above φ 0.42 √f'c b d: the slab is too thin",
                ],
                rho is None,
            )
        )
    return rows


# ─────────────────────────────────────── stairs ───────────────────────────────────────


def stair_rows(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Integrator glue: the rows of a staircase type's stairs from ``collect["stairs"]`` of
    :func:`saengine.design.stairs.stair_report` (its need enveloped over the type's stairs, per
    metre width): main bars (and top and landing bars when needed) and distribution bars."""
    from saengine.design import stairs as stair_design

    need = group["need"]
    if need is None:
        return []
    t = group["object"]
    bars = stair_design.bars_of(t.reinforcement)
    too_small = bool(need.too_small)
    notes = list(dict.fromkeys(need.too_small)) + ["enveloped over the type's stairs"]

    def pick(required: dict[float, float], mesh: Any) -> tuple[float, float] | None:
        if not required:
            return None
        dia = mesh.dia if mesh is not None and mesh.dia in required else min(required)
        return dia, required[dia]

    layers: list[tuple[str, dict[float, float], Any, float | None]] = [
        ("main bars", need.main, bars.main if bars else None, need.s_main),
        ("top bars", need.top, bars.top if bars else None, need.s_main),
        (
            "landing bars",
            need.landing,
            (bars.landing or bars.main) if bars else None,
            need.s_landing,
        ),
    ]
    rows = []
    for member in group["members"]:
        for name, required, mesh, spacing in layers:
            found = pick(required, mesh)
            if found is None:
                continue
            dia, area = found
            rows.append(
                _row(
                    member,
                    "staircase",
                    group["type"],
                    name,
                    f"{name} (Ø{dia:g})",
                    None,
                    "",
                    area,
                    need.distribution,
                    None if bars is None or mesh is None else mesh.area,
                    "mm²/m",
                    need.governing,
                    [*notes, f"spacing ≤ {spacing:.0f} mm"],
                    too_small,
                )
            )
        rows.append(
            _row(
                member,
                "staircase",
                group["type"],
                "distribution bars",
                "distribution bars",
                None,
                "",
                need.distribution,
                need.distribution,
                None if bars is None else bars.distribution.area,
                "mm²/m",
                None,
                [f"spacing ≤ {need.s_dist:.0f} mm"],
            )
        )
    return rows


# ─────────────────────────────────────── foundations ───────────────────────────────────────

_SHALLOW = re.compile(r"^Flexure ([XY]) \((bottom|top)\)$")
_BETWEEN = "Flexure between columns (top)"
_CAP_BOTTOM = re.compile(r"^Flexure bottom ([XY]) at the column face")
_CAP_TOP = re.compile(r"^Flexure top ([XY]) \(hogging\)")
_CAP_TIE = re.compile(r"^Tie \(bottom ([XY]) bars")
_RAFT = re.compile(r"^Flexure (bottom|top) ([XY]) \(Wood-Armer\)$")


@dataclass
class FoundationDemand:
    """A foundation's moments per layer [N·mm per metre] and the tie forces per direction of a
    deep pile cap [N per metre], from its checks."""

    id: str
    type: str
    thickness: float
    cover: float
    fc: float
    fy: float
    moments: dict[str, Peak]
    ties: dict[str, Peak]
    failing: list[str]
    current: PlanarReinforcement | None
    material: str | None


def foundation_demands(gathered: Gathered) -> list[FoundationDemand]:
    if gathered.substructure is None or gathered.context is None:
        return []
    ctx = gathered.context
    by_id = {f.id: f for f in ctx.substructure.foundations}
    rebar = _default_rebar(json.loads(gathered.objects_text), gathered.materials)
    found: list[FoundationDemand] = []
    for result in gathered.substructure.get("foundations", []):
        foundation = by_id.get(result["id"])
        if foundation is None or not foundation.thickness:
            continue
        reinforcement = foundation.reinforcement
        material_id = reinforcement.material if reinforcement else rebar
        try:
            fc = ctx.concrete(foundation.material, foundation.id).concrete.fc
            fy = ctx.rebar(material_id).steel.fy if material_id else 420.0
        except Exception:  # noqa: BLE001, S112 - the substructure report says why
            continue
        widths = {"X": foundation.width or 1000.0, "Y": foundation.length or 1000.0}
        moments = {name: Peak() for name in slab_design.LAYERS}
        ties = {"X": Peak(), "Y": Peak()}
        failing: list[str] = []
        for check in result.get("checks", []):
            name = check["name"]
            value = float(check["demand"])
            combination, where = check.get("combination"), check.get("note", "")
            if (m := _SHALLOW.match(name)) is not None:
                moments[f"{m.group(2)}{m.group(1)}"].take(value * 1e6, combination, name)
            elif name == _BETWEEN:
                axis = "X" if (foundation.length or 0) >= (foundation.width or 0) else "Y"
                moments[f"top{axis}"].take(value * 1e6, combination, name)
            elif (m := _CAP_BOTTOM.match(name)) is not None:
                per_m = value * 1e6 / (widths[m.group(1)] / 1e3)
                moments[f"bottom{m.group(1)}"].take(per_m, combination, name)
            elif (m := _CAP_TOP.match(name)) is not None:
                per_m = value * 1e6 / (widths[m.group(1)] / 1e3)
                moments[f"top{m.group(1)}"].take(per_m, combination, name)
            elif (m := _CAP_TIE.match(name)) is not None:
                ties[m.group(1)].take(value * 1e3 / (widths[m.group(1)] / 1e3), combination, name)
            elif (m := _RAFT.match(name)) is not None:
                moments[f"{m.group(1)}{m.group(2)}"].take(value * 1e6, combination, name)
            elif (
                not check.get("ok", True)
                and not check.get("flag")
                and not name.startswith(("Min.", "Flexure", "Tie"))
            ):
                thicker = any(w in name.lower() for w in ("shear", "punching", "node"))
                remedy = (
                    "more bars do little; a thicker foundation is the remedy"
                    if thicker
                    else "bars do not help; a larger foundation (or another type) is the remedy"
                )
                failing.append(
                    f"{name} fails (utilisation {check['utilisation']:.2f}; {where}): {remedy}"
                )
        found.append(
            FoundationDemand(
                foundation.id,
                foundation.type,
                float(foundation.thickness),
                reinforcement.cover if reinforcement else 75.0,
                fc,
                fy,
                moments,
                ties,
                failing,
                reinforcement,
                material_id,
            )
        )
    return found


def foundation_layer_need(
    demand: FoundationDemand, name: str, d: float
) -> tuple[float, float | None, list[str], bool]:
    """(As to provide [mm²/m], As,min or None, notes, too small) of one layer of a footing,
    pile cap or raft."""
    from saengine.substructure.shallow import min_steel_ratio, plain_flexure

    peak = demand.moments[name]
    need = B.slab_flexure_need(peak.value, d, demand.fc, demand.fy)
    notes = [need.note, f"d = {d:.0f} mm", peak.where]
    bottom = name.startswith("bottom")
    as_min = min_steel_ratio(demand.fy) * demand.thickness * 1000
    required = need.area
    minimum: float | None = None
    if bottom:
        required, minimum = max(required, as_min), as_min
        tie = demand.ties[name[-1]]
        if tie.value > 0:
            as_tie = tie.value / (0.75 * demand.fy)  # φ As fy (ACI 23.7.2.1)
            if as_tie > required:
                required = as_tie
                notes.append(f"governed by the strut-and-tie tie T = {tie.value / 1e3:.1f} kN/m")
    elif peak.value > 0:
        if demand.type != "raft" and peak.value <= plain_flexure(demand.thickness, demand.fc):
            required = 0.0
            notes.append("plain concrete carries it (ACI 14.5.2.1): no top bars needed")
        else:
            required, minimum = max(required, as_min), as_min
    return required, minimum, notes, need.too_small


def foundation_depths(demand: FoundationDemand, dias: dict[str, float]) -> dict[str, float]:
    return slab_depths(demand.thickness, demand.cover, dias)


def foundation_rows(demand: FoundationDemand) -> list[dict[str, Any]]:
    current = demand.current
    dias = {}
    meshes = {}
    for name in slab_design.LAYERS:
        mesh = getattr(current, name, None) if current else None
        meshes[name] = mesh
        dias[name] = mesh.dia if mesh else (16.0 if name.startswith("bottom") else 0.0)
    depths = foundation_depths(demand, dias)
    rows = []
    for name in slab_design.LAYERS:
        peak = demand.moments[name]
        if peak.value <= 0 and not name.startswith("bottom"):
            continue
        required, minimum, notes, small = foundation_layer_need(demand, name, depths[name])
        mesh = meshes[name]
        rows.append(
            _row(
                demand.id,
                demand.type,
                demand.id,
                f"{name[:-1]} {name[-1]}",
                f"{name[:-1]} {name[-1]} bars",
                peak.value / 1e6,
                "kN·m/m",
                required,
                minimum,
                (bar_area(mesh.dia) * 1000 / mesh.spacing) if mesh else None,
                "mm²/m",
                peak.combination,
                notes,
                small,
            )
        )
    for text in demand.failing:
        rows.append(
            _row(
                demand.id,
                demand.type,
                demand.id,
                "foundation",
                "other check",
                None,
                "",
                0.0,
                None,
                None,
                "",
                None,
                [text],
                True,
            )
        )
    return rows


# ─────────────────────────────────────── the report ───────────────────────────────────────


def column_requirements(
    gathered: Gathered, options: Options
) -> dict[str, tuple[ColumnSearch, dict[str, tuple[int | None, list[Point]]]]]:
    """Per column type: its search and per member the smallest layout carrying its demand
    (worked out once per gathering and options, see :attr:`Gathered.searches`)."""
    kept = getattr(gathered, "searches", None)
    key = dataclasses.astuple(options)
    if kept is not None and key in kept:
        return kept[key]
    combinations = gathered.collect.get("combinations", [])
    by_type: dict[str, tuple[ColumnSearch, dict[str, tuple[int | None, list[Point]]]]] = {}
    for member in gathered.collect.get("members", []):
        if member["kind"] != "column":
            continue
        type_id = member["type"]
        if type_id not in by_type:
            search = ColumnSearch(
                member["object"],
                member["fc"],
                member["fy"],
                member["es"],
                member["aggregate"],
                options,
            )
            by_type[type_id] = (search, {})
        search, members = by_type[type_id]
        points = column_points(member, combinations)
        members[member["id"]] = (search.smallest(points), points)
    if kept is not None:
        kept[key] = by_type
    return by_type


def design_required(
    out_dir: str | Path,
    project_path: str | Path,
    options: dict[str, Any] | None = None,
    gathered: Gathered | None = None,
) -> dict[str, Any]:
    """The reinforcement required by every element :func:`saengine.design.design_report`
    designs, and by the foundations of 9 Substructure: ``{"code", "elements": [rows],
    "summary", "notes", "combinations"}`` (rows: see the module notes). ``summary``: ``{"rows",
    "elements", "short"`` (rows whose bars provided are less than required), ``"tooSmall"``
    (element ids whose section no bars can make work), ``"assumed"`` (types without bars,
    checked with assumed ones)``}``."""
    opts = Options.of(options)
    gathered = gathered or gather(out_dir, project_path)
    combinations = gathered.collect.get("combinations", [])
    rows: list[dict[str, Any]] = []
    for member in gathered.collect.get("members", []):
        if member["kind"] == "beam":
            demand = beam_demand(member, combinations)
            rows += beam_rows(member, demand, member["type"] in gathered.assumed)
    for type_id, (search, members) in column_requirements(gathered, opts).items():
        for member in gathered.collect.get("members", []):
            if member["type"] == type_id and member["id"] in members:
                index, points = members[member["id"]]
                rows += column_rows(member, search, index, points, type_id in gathered.assumed)
    for member in gathered.collect.get("members", []):
        rows += detailing_rows(member, member["type"] in gathered.assumed)
    for collected in gathered.collect.get("slabs", []):
        rows += slab_rows(collected, combinations, collected["type"] in gathered.assumed)
    # Integrator glue: wall piers (saengine.design.wall_design) and stairs (stairs.py).
    from saengine.design import wall_design

    for collected in gathered.collect.get("walls", []):
        rows += wall_design.required_rows(collected, collected["type"] in gathered.assumed, _row)
    for group in gathered.collect.get("stairs", []):
        rows += stair_rows(group)
    for demand in foundation_demands(gathered):
        rows += foundation_rows(demand)
    notes = list(gathered.notes)
    if gathered.assumed:
        notes.append(
            "No bars entered on "
            + ", ".join(sorted(gathered.assumed))
            + ": checked with assumed bars for the effective depth only."
        )
    notes.append(
        "Beams: zones start (0 - 0.25 L), middle and end (0.75 - 1 L) of each member; the bars "
        "of an object type are the same along the whole member (no curtailment)."
    )
    short = [r for r in rows if r["ok"] is False]
    return {
        "code": gathered.report.get("code"),
        "elements": rows,
        "summary": {
            "rows": len(rows),
            "elements": len({r["element"] for r in rows}),
            "short": len(short),
            "tooSmall": sorted({r["element"] for r in rows if r["tooSmall"]}),
            "assumed": sorted(gathered.assumed),
        },
        "notes": notes,
        "combinations": combinations,
    }

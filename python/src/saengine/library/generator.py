"""The building generator: a whole RC building from its grids and storeys in one step.

ETABS-like speed for the common case: the engineer gives the grid spacings, the storeys, the
structural system and a few choices, and gets SAEngine's own parts, ready to edit:

- ``03 Materials`` (the default library), ``04 Objects`` (column, beam, slab and wall types
  sized here), ``05 Floor Plan`` (columns at every grid intersection from the base to the roof,
  one per storey; beams on every grid line of every suspended floor, none for a flat slab; one
  slab per bay per floor; core walls round a chosen bay), typical floors by ``similarTo``;
- ``09 Substructure``: an isolated footing under every column, or one mat (raft), or nothing;
- a patch of ``02 Project Settings`` (occupancy, live load, site, the structural system the
  seismic design category asks for), and the notes saying how every size was found.

The sizes are PRELIMINARY: the code minimums for deflection and the seismic proportioning rules
of BNBC 2020 where they apply, and stated rules of thumb elsewhere. They are a starting model
for the analysis and design (Parts 8 and 10), which check and size the members for strength.

BNBC 2020 Part 6 clauses used (pages of the code PDF):

- Table 6.6.1 (p. 900): minimum thickness of non-prestressed beams and one-way slabs unless
  deflections are calculated: solid one-way slabs l/20, l/24, l/28 (simply supported, one end
  continuous, both ends continuous); beams l/16, l/18.5, l/21; note (b): times (0.4 + fy/700)
  for fy other than 420 MPa.
- Sec 6.2.5.3.2 (p. 901) and Table 6.6.3 (p. 902): slabs without interior beams (flat
  plates, no drop panels): ln/30 exterior panels without edge beams, ln/33 interior panels at
  fy = 420 MPa (ln/33, ln/36 at 280; ln/28, ln/31 at 520; linear interpolation), and at least
  125 mm; ln the clear span in the long direction, face to face of the supports (p. 903).
- Sec 6.2.5.3.3 (p. 903): slabs with beams on all sides: alpha_fm <= 0.2 as 6.2.5.3.2;
  0.2 < alpha_fm <= 2.0: h = ln (0.8 + fy/1400) / (36 + 5 beta (alpha_fm - 0.2)) >= 125 mm
  (eq. 6.6.5); alpha_fm > 2.0: h = ln (0.8 + fy/1400) / (36 + 9 beta) >= 90 mm (eq. 6.6.6);
  (d) 10 % more in a panel with a discontinuous edge whose edge beam has alpha_f < 0.8.
- Sec 8.3.4.1 (pp. 1090-1091): beams of special moment frames: width to depth at least 0.3
  ((c)), width at least 250 mm ((d)(i)); Sec 8.3.5.1 (p. 1095): columns of special moment
  frames: least dimension at least 300 mm, least / perpendicular dimension at least 0.4.
- The seismic design category (Table 6.2.18) and the system rows of Table 6.2.19 come from
  :mod:`saengine.design.seismic_rules`, which cites them.
"""

from __future__ import annotations

import copy
import itertools
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library import bnbc
from saengine.library.bim import generate, source_stamp
from saengine.library.defaults import default_material_library
from saengine.library.floorplan import FloorPlan
from saengine.library.materials import Category
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import LocationId, ProjectSettings, default_project_settings
from saengine.library.substructure import SUBSTRUCTURE_FILE, Substructure
from saengine.library.templates import TEMPLATES

# ─────────────────────────────────────────── the spec ───────────────────────────────────────────

Spacing = Annotated[float, Field(gt=0, description="[mm]")]
SystemKind = Literal["rcFrame", "rcFrameWithWalls", "flatSlab"]
FootingKind = Literal["isolated", "mat", "none"]
OccupancyUse = Literal[
    "residential",
    "office",
    "educational",
    "healthcare",
    "assembly",
    "retail",
    "industrial",
    "storage",
    "parking",
    "mixed",
]

#: The floor area use (Table 6.2.3 selection, :data:`bnbc.AREA_USES`) of each building use.
AREA_USE_OF: dict[str, str] = {
    "residential": "residential",
    "office": "office",
    "educational": "classroom",
    "healthcare": "hospitalWard",
    "assembly": "assemblyMovable",
    "retail": "retailUpper",
    "industrial": "storageLight",
    "storage": "storageLight",
    "parking": "parking",
    "mixed": "office",
}

#: The occupancy category assumed for a use when the spec gives none (Table 6.1.1, pp. 480-481,
#: on the safe side): health care as a hospital with surgery or emergency treatment (IV),
#: schools and assembly as buildings where many people gather (III); the rest II.
CATEGORY_OF_USE: dict[str, str] = {"healthcare": "IV", "educational": "III", "assembly": "III"}
CATEGORY_RANK = ("I", "II", "III", "IV")


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StorySpec(_Spec):
    name: str = Field(min_length=1)
    height: Spacing = Field(description="Height of the storey below this level [mm].")


class GridRef(_Spec):
    """A bay by the grid lines at its lower-left corner."""

    x: str
    y: str


class BuildingSpec(_Spec):
    """What :func:`generate_building` builds."""

    name: str = Field(default="Building", min_length=1)
    gridsX: list[Spacing] = Field(
        min_length=1, description="Spacings between the X grid lines (labelled A, B, ...) [mm]."
    )
    gridsY: list[Spacing] = Field(
        min_length=1, description="Spacings between the Y grid lines (labelled 1, 2, ...) [mm]."
    )
    stories: list[StorySpec] | None = Field(
        default=None, description="The storeys from the bottom; or storyCount and heights."
    )
    storyCount: int | None = Field(default=None, ge=1, le=100)
    typicalHeight: Spacing = 3000
    groundHeight: float | None = Field(
        default=None, gt=0, description="Height of the ground storey [mm]; none: typical."
    )
    baseElevation: float = Field(default=0, description="Level of the base [mm].")
    typical: bool = Field(
        default=True,
        description="Storeys above the first suspended floor are similar to the first typical "
        "floor (a new family where the column types change).",
    )
    system: SystemKind = "rcFrame"
    coreBay: GridRef | None = Field(
        default=None,
        description="Bay of the core walls (rcFrameWithWalls, and flatSlab in Category D); none: "
        "the middle bay.",
    )
    concrete: str = "C24.1"
    rebar: str = "B420DWR"
    footing: FootingKind = "isolated"
    occupancy: OccupancyUse = "residential"
    occupancyCategory: Literal["I", "II", "III", "IV"] | None = Field(
        default=None,
        description="Occupancy category (BNBC Table 6.1.1); none: the conservative default of "
        "the use (healthcare IV, educational and assembly III, else II), never below the "
        "settings' own.",
    )
    live: float | None = Field(
        default=None, gt=0, description="Floor live load [kN/m²]; none: the code minimum."
    )
    location: LocationId | None = None  # type: ignore[valid-type]
    siteClass: Literal["SA", "SB", "SC", "SD", "SE"] | None = None
    allowableBearing: float | None = Field(
        default=None,
        gt=0,
        description="Net allowable bearing pressure for the preliminary footing sizes [kPa]; "
        "none: the settings' override, else 100 kPa.",
    )
    columnGroupStoreys: int = Field(
        default=3, ge=1, le=20, description="Storeys per column type change."
    )
    beamSpanDepth: float | None = Field(
        default=15,
        gt=0,
        description="Rule of thumb span/depth of frame beams; none: the deflection minimum only.",
    )
    minSlab: float = Field(
        default=125, gt=0, description="Least slab thickness (SAEngine practice) [mm]."
    )
    matOverhang: float = Field(default=1000, ge=0, description="Mat beyond the grid [mm].")
    reinforcement: bool = Field(
        default=False,
        description="Write template bars on the types (placeholders); default none: Design "
        "mode proposes them.",
    )

    @model_validator(mode="after")
    def _stories(self) -> BuildingSpec:
        if self.stories is None and self.storyCount is None:
            raise ValueError("give the stories, or storyCount with the heights")
        if len(self.gridsX) > 60 or len(self.gridsY) > 60:
            raise ValueError("at most 60 bays each way")
        return self

    def story_list(self) -> list[StorySpec]:
        if self.stories is not None:
            return self.stories
        count = self.storyCount or 1
        return [
            StorySpec(
                name=f"Level {i + 1}",
                height=(self.groundHeight or self.typicalHeight) if i == 0 else self.typicalHeight,
            )
            for i in range(count)
        ]


# ─────────────────────────────────────────── helpers ───────────────────────────────────────────

G = 9.80665
#: Default net allowable bearing for the preliminary footings [kPa] (rule of thumb).
DEFAULT_BEARING = 100.0
#: Table 6.6.3 (p. 902), no drop panels: fy -> (exterior without edge beams, exterior with
#: edge beams, interior) divisors of ln.
FLAT_DIVISORS = {280.0: (33.0, 36.0, 36.0), 420.0: (30.0, 33.0, 33.0), 520.0: (28.0, 31.0, 31.0)}
#: Table 6.6.1 (p. 900) divisors by the number of continuous ends (0, 1, 2).
ONE_WAY_SLAB = (20.0, 24.0, 28.0)
BEAM = (16.0, 18.5, 21.0)
#: Column bending allowance on the axial estimate by position (rule of thumb).
POSITION_FACTOR = {"interior": 1.0, "edge": 1.25, "corner": 1.5}


def ceil_to(value: float, step: float) -> float:
    return math.ceil(value / step - 1e-9) * step


def letters(index: int) -> str:
    """A, B, ..., Z, AA, AB, ..."""
    text = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        text = chr(65 + rest) + text
    return text


def fy_factor(fy: float) -> float:
    """Table 6.6.1 note (b) (p. 900): (0.4 + fy/700) for fy other than 420 MPa."""
    return 1.0 if abs(fy - 420) < 1e-6 else 0.4 + fy / 700


def flat_divisor(fy: float, kind: int) -> float:
    """The Table 6.6.3 h = ln/divisor, linear interpolation of h between the fy rows; kind 0
    exterior without edge beams, 1 exterior with edge beams, 2 interior."""
    rows = sorted(FLAT_DIVISORS)
    fy = min(max(fy, rows[0]), rows[-1])
    for lo, hi in itertools.pairwise(rows):
        if lo <= fy <= hi:
            t = (fy - lo) / (hi - lo)
            h = (1 - t) / FLAT_DIVISORS[lo][kind] + t / FLAT_DIVISORS[hi][kind]
            return 1 / h
    return FLAT_DIVISORS[rows[-1]][kind]


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _template(key: str, **changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(TEMPLATES[key])
    data.update(changes)
    return data


# ─────────────────────────────────────────── the generator ───────────────────────────────────────


def _system(kind: str, sdc: str | None, height_m: float) -> tuple[str, bool, list[str]]:
    """(settings' system id, core walls needed, notes) for the generator's system in ``sdc``:
    the first candidate Table 6.2.19 permits in the category and the height, with the detailing
    level the category requires (Sec 8.3.2)."""
    from saengine.design.seismic_rules import NP, REQUIRED_LEVEL, TABLE_6_2_19, _level_at_least

    candidates = {
        "rcFrame": ["rcOmf", "rcImf", "rcSmf"],
        "rcFrameWithWalls": ["rcOrdinaryWallFrame", "rcDualSpecial"],
        "flatSlab": ["rcOmf", "rcImf", "rcSpecialWallFrame", "rcDualSpecial"],
    }[kind]
    category = sdc or "B"
    notes: list[str] = []
    for system in candidates:
        row = TABLE_6_2_19[system]
        limit = row.limits["BCD".index(category)]
        if limit == NP or (limit is not None and height_m > limit):
            continue
        if row.frame is not None and not _level_at_least(row.frame, REQUIRED_LEVEL[category]):
            continue
        walls = kind == "rcFrameWithWalls" or system in ("rcSpecialWallFrame", "rcDualSpecial")
        if kind == "flatSlab" and walls:
            notes.append(
                f"Seismic Design Category {category}: a flat slab-column frame is not a moment "
                f"frame of the detailing the category needs (Sec 8.3.2); core walls are added "
                f"and the system is {bnbc.STRUCTURAL_SYSTEMS[system].name} (Table 6.2.19 row "
                f"{row.row}): the slab-column frame is a gravity system (Sec 8.3.12)."
            )
            if system == "rcDualSpecial":
                notes.append(
                    "Over 50 m in Category D the walls are taken as a dual system with special "
                    "moment frames, which a flat slab is not: add beams or consult."
                )
        return system, walls, notes
    raise ValueError(f"no structural system for {kind} in Seismic Design Category {category}")


def generate_building(spec: BuildingSpec | dict[str, Any], settings: Any = None) -> dict[str, Any]:
    """The parts of a building generated from ``spec`` (a :class:`BuildingSpec` or its JSON).

    ``settings``: the project settings to start from (a :class:`ProjectSettings` or its JSON);
    none: :func:`default_project_settings`.

    Returns ``{"materials", "objects", "floorPlan", "substructure", "settings",
    "settingsPatch", "notes", "summary"}``; the parts as JSON (validated by their models).
    """
    s = spec if isinstance(spec, BuildingSpec) else BuildingSpec.model_validate(spec)
    notes: list[str] = []

    # ── materials ──
    materials = default_material_library()
    concrete = materials.get(s.concrete)
    if concrete is None or concrete.category != Category.CONCRETE or concrete.concrete is None:
        raise ValueError(f"'{s.concrete}' is not a concrete of the default materials")
    rebar = materials.get(s.rebar)
    if rebar is None or rebar.category != Category.REBAR or rebar.steel is None:
        raise ValueError(f"'{s.rebar}' is not a rebar of the default materials")
    fc, fy = concrete.concrete.fc, rebar.steel.fy
    gamma = (concrete.mechanical.density or 2400.0) * G / 1000.0  # kN/m³

    # ── settings ──
    if settings is None:
        base = default_project_settings(s.name)
    elif isinstance(settings, ProjectSettings):
        base = settings
    else:
        base = ProjectSettings.model_validate(settings)
    base_json = base.model_dump(mode="json", by_alias=True, exclude_none=True)
    if s.occupancyCategory is not None:
        category = s.occupancyCategory
    else:
        category = CATEGORY_OF_USE.get(s.occupancy, "II")
        own = base.occupancy.category if settings is not None else "II"
        if CATEGORY_RANK.index(own) > CATEGORY_RANK.index(category):
            category = own
        notes.append(
            f"Occupancy category {category} assumed for {s.occupancy} use (Table 6.1.1, pp. "
            "480-481: health care with surgery or emergency treatment IV; schools, day care, "
            "assembly of over 300 people and health care with 50 or more resident patients III; "
            "else II): CONFIRM it in 02 Project Settings, since it sets the Seismic Design "
            "Category, the structural system and the member limits below."
        )
    patch: dict[str, Any] = {"occupancy": {"use": s.occupancy, "category": category}}
    site: dict[str, Any] = {}
    if s.location is not None:
        site["location"] = s.location
    if s.siteClass is not None:
        site.update(siteClass=s.siteClass, siteClassSource="entered")
    if site:
        patch["site"] = site
    use = AREA_USE_OF[s.occupancy]
    code_live = bnbc.AREA_USES[use].live
    live = max(s.live or code_live, code_live)
    if s.live is not None and s.live < code_live:
        notes.append(
            f"Live load {s.live:g} kN/m² is below the Table 6.2.3 minimum for "
            f"{bnbc.AREA_USES[use].name.lower()}; {code_live:g} kN/m² is used."
        )
    area_loads = [
        {**a, "use": use, "live": live} if a["id"] == base.floorLoad else a
        for a in base_json["areaLoads"]
    ]
    patch["areaLoads"] = area_loads

    # Seismic design category from the patched settings.
    from saengine.design.seismic_rules import seismic_design_category

    trial = ProjectSettings.model_validate(_deep_merge(base_json, patch))
    sdc, zone = seismic_design_category(trial)
    stories = s.story_list()
    height_m = sum(st.height for st in stories) / 1000
    system_id, walls_needed, system_notes = _system(s.system, sdc, height_m)
    patch["seismic"] = {"system": system_id}
    settings_json = _deep_merge(base_json, patch)
    final = ProjectSettings.model_validate(settings_json)
    special = sdc == "D" or system_id in ("rcSmf", "rcDualSpecial")
    floor_load = next(a for a in final.areaLoads if a.id == final.floorLoad)
    roof_load = next(a for a in final.areaLoads if a.id == final.roofLoad)
    q_floor_sd = floor_load.finish + floor_load.partitions
    q_roof_sd = roof_load.finish + roof_load.partitions
    notes.append(
        f"Seismic Design Category {sdc or '-'} (zone {zone or '-'}, site class "
        f"{final.site.siteClass}, occupancy category {final.occupancy.category}); system "
        f"{bnbc.STRUCTURAL_SYSTEMS[system_id].name}."
    )
    notes += system_notes
    notes.append("PRELIMINARY sizes: the analysis and Design mode check and size every member.")

    # ── grids and storeys ──
    xs = [0.0]
    for d in s.gridsX:
        xs.append(xs[-1] + d)
    ys = [0.0]
    for d in s.gridsY:
        ys.append(ys[-1] + d)
    xl = [letters(i) for i in range(len(xs))]
    yl = [str(j + 1) for j in range(len(ys))]
    nx, ny = len(xs), len(ys)
    n = len(stories)
    levels = [s.baseElevation]
    for st in stories:
        levels.append(levels[-1] + st.height)
    story_ids = ["BASE"] + [f"L{k}" for k in range(1, n + 1)]
    heights = [0.0] + [st.height for st in stories]

    flat = s.system == "flatSlab"
    walls_on = walls_needed or s.system == "rcFrameWithWalls"
    core: tuple[int, int] | None = None
    if walls_on:
        if s.coreBay is not None:
            if s.coreBay.x not in xl[:-1] or s.coreBay.y not in yl[:-1]:
                raise ValueError(
                    f"core bay {s.coreBay.x}-{s.coreBay.y}: give the grid lines at its "
                    "lower-left corner"
                )
            core = (xl.index(s.coreBay.x), yl.index(s.coreBay.y))
        else:
            core = ((nx - 1) // 2, (ny - 1) // 2)
    core_lines: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    if core is not None:
        i, j = core
        corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
        for a, b in zip(corners, corners[1:] + corners[:1], strict=True):
            core_lines.add((min(a, b), max(a, b)))

    # ── beams (Table 6.6.1, 8.3.4.1) ──
    beam_size: dict[tuple[tuple[int, int], tuple[int, int]], tuple[float, float]] = {}
    beam_rule: list[str] = []
    if not flat:
        lines: list[list[tuple[tuple[int, int], tuple[int, int], float]]] = []
        for j in range(ny):
            lines.append([((i, j), (i + 1, j), xs[i + 1] - xs[i]) for i in range(nx - 1)])
        for i in range(nx):
            lines.append([((i, j), (i, j + 1), ys[j + 1] - ys[j]) for j in range(ny - 1)])
        for line in lines:
            for k, (a, b, span) in enumerate(line):
                continuous = (k > 0) + (k < len(line) - 1)
                table = span / BEAM[continuous] * fy_factor(fy)
                thumb = span / s.beamSpanDepth if s.beamSpanDepth else 0.0
                h = ceil_to(max(table, thumb, 300.0), 25)
                b_min = max(250.0, 0.3 * h)
                width = ceil_to(b_min, 25)
                beam_size[(a, b)] = (width, h)
        beam_rule.append(
            "Beams: depth h = max(Table 6.6.1 minimum l/16, l/18.5, l/21 for 0, 1, 2 continuous "
            f"ends x (0.4 + fy/700) = x{fy_factor(fy):.3f}, "
            + (
                f"span/{s.beamSpanDepth:g} (rule of thumb for frame beams under lateral load), "
                if s.beamSpanDepth
                else ""
            )
            + "300 mm), l the centre-to-centre span, rounded up to 25 mm; width b = max(250 mm, "
            "0.3 h) rounded up to 25 mm"
            + (
                " (Sec 8.3.4.1(c), (d)(i), special moment frames)."
                if special
                else " (the special-frame proportions of Sec 8.3.4.1 as a practice rule)."
            )
        )

    # ── slabs ──
    def edge_strip(a: tuple[int, int], b: tuple[int, int]) -> tuple[float, bool]:
        """Slab width an edge beam carries [mm] and whether it is on the building's edge."""
        if a[1] == b[1]:  # along x at y index a[1]
            j = a[1]
            below = ys[j] - ys[j - 1] if j > 0 else 0.0
            above = ys[j + 1] - ys[j] if j < ny - 1 else 0.0
            return (below + above) / 2, j in (0, ny - 1)
        i = a[0]
        left = xs[i] - xs[i - 1] if i > 0 else 0.0
        right = xs[i + 1] - xs[i] if i < nx - 1 else 0.0
        return (left + right) / 2, i in (0, nx - 1)

    def panel_edges(i: int, j: int) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        return [((i, j), (i + 1, j)), ((i, j + 1), (i + 1, j + 1)), ((i, j), (i, j + 1)),
                ((i + 1, j), (i + 1, j + 1))]  # fmt: skip

    def beam_slab(i: int, j: int) -> tuple[float, str, str]:
        """(thickness, system, how) of the panel of bay (i, j) with beams on all sides."""
        lx, ly = xs[i + 1] - xs[i], ys[j + 1] - ys[j]
        edges = panel_edges(i, j)
        bx = max(beam_size.get(e, (0.0, 0.0))[0] for e in edges[:2])
        by = max(beam_size.get(e, (0.0, 0.0))[0] for e in edges[2:])
        lnx, lny = lx - by, ly - bx  # clear spans, face to face of the beams
        ln, short = max(lnx, lny), min(lnx, lny)
        beta = ln / short
        if beta > 2:
            # One-way: spans the short way; continuous over the beams with a panel beyond.
            if lnx <= lny:
                ends = (i > 0) + (i < nx - 2)
                span = lx
            else:
                ends = (j > 0) + (j < ny - 2)
                span = ly
            h = span / ONE_WAY_SLAB[ends] * fy_factor(fy)
            t = ceil_to(max(h, s.minSlab), 25)
            return (
                t,
                "oneWay",
                f"one-way (beta {beta:.2f} > 2): Table 6.6.1 l/{ONE_WAY_SLAB[ends]:g}",
            )
        hs = 150.0
        how = ""
        for _ in range(8):
            alphas = []
            weak_edge = False
            for e in edges:
                b, h = beam_size.get(e, (0.0, 0.0))
                strip, exterior = edge_strip(*e)
                alpha = (b * h**3) / (strip * hs**3) if strip > 0 else 0.0
                alphas.append(alpha)
                if exterior and alpha < 0.8:
                    weak_edge = True
            afm = sum(alphas) / 4
            factor = 0.8 + fy / 1400
            if afm > 2.0:
                h_req = max(ln * factor / (36 + 9 * beta), 90.0)
                how = f"eq. 6.6.6 (alpha_fm {afm:.1f} > 2, beta {beta:.2f})"
            elif afm > 0.2:
                h_req = max(ln * factor / (36 + 5 * beta * (afm - 0.2)), 125.0)
                how = f"eq. 6.6.5 (alpha_fm {afm:.2f}, beta {beta:.2f})"
            else:
                exterior = i in (0, nx - 2) or j in (0, ny - 2)
                h_req = max(ln / flat_divisor(fy, 1 if exterior else 2), 125.0)
                how = f"Table 6.6.3 (alpha_fm {afm:.2f} <= 0.2)"
            if weak_edge:
                h_req *= 1.1
                how += ", +10 % for an edge beam with alpha_f < 0.8 (6.2.5.3.3(d))"
            new = ceil_to(max(h_req, s.minSlab), 25)
            if new == hs:
                break
            hs = new
        return hs, "twoWay", how

    slab_of: dict[tuple[int, int], tuple[float, str, str]] = {}
    if not flat:
        for i in range(nx - 1):
            for j in range(ny - 1):
                slab_of[(i, j)] = beam_slab(i, j)

    # ── columns and (flat slab) slabs: axial estimate, iterated ──
    def position(i: int, j: int) -> str:
        edge_x, edge_y = i in (0, nx - 1), j in (0, ny - 1)
        return "corner" if edge_x and edge_y else "edge" if edge_x or edge_y else "interior"

    def adjacent_panels(i: int, j: int) -> list[tuple[int, int]]:
        return [
            (a, b) for a in (i - 1, i) for b in (j - 1, j) if 0 <= a < nx - 1 and 0 <= b < ny - 1
        ]

    groups: list[list[int]] = []
    count = math.ceil(n / s.columnGroupStoreys)
    sizes = [n // count + (1 if k < n % count else 0) for k in range(count)]
    start = 1
    for size in sizes:
        groups.append(list(range(start, start + size)))
        start += size
    group_of = {k: g for g, members in enumerate(groups) for k in members}
    col_min = 300.0 if special else 250.0
    col_side = {(i, j, k): col_min for i in range(nx) for j in range(ny) for k in range(1, n + 1)}
    loads: dict[tuple[int, int], float] = {}
    group_side: dict[tuple[int, str], float] = {}
    flat_t = 0.0
    flat_how = ""
    for _ in range(6):
        if flat:
            least = min(col_side.values())
            worst, kind_name = 0.0, ""
            for i in range(nx - 1):
                for j in range(ny - 1):
                    ln = max(xs[i + 1] - xs[i], ys[j + 1] - ys[j]) - least
                    exterior = i in (0, nx - 2) or j in (0, ny - 2)
                    h = ln / flat_divisor(fy, 0 if exterior else 2)
                    if h > worst:
                        worst = h
                        kind_name = "exterior panel without edge beams" if exterior else "interior"
            flat_t = ceil_to(max(worst, 125.0, s.minSlab), 25)
            flat_how = (
                f"Table 6.6.3 ln/{flat_divisor(fy, 0):.1f} ({kind_name}, fy {fy:g} MPa), ln the "
                f"longest clear span face to face of the {least:g} mm columns, at least 125 mm "
                "(Sec 6.2.5.3.2), one thickness for every panel"
            )
            for i in range(nx - 1):
                for j in range(ny - 1):
                    slab_of[(i, j)] = (flat_t, "flat", flat_how)
        # Service loads at each column, from the roof down [kN].
        for i in range(nx):
            for j in range(ny):
                p = 0.0
                for k in range(n, 0, -1):
                    sd = q_roof_sd if k == n else q_floor_sd
                    q_live = roof_load.live if k == n else floor_load.live
                    for a, b in adjacent_panels(i, j):
                        area = (xs[a + 1] - xs[a]) * (ys[b + 1] - ys[b]) / 4 / 1e6
                        t = slab_of[(a, b)][0]
                        p += area * (t / 1000 * gamma + sd + q_live)
                    if not flat:
                        t_least = min(v[0] for v in slab_of.values())
                        for (a, b), (bw, bh) in beam_size.items():
                            if (i, j) in (a, b) and (a, b) not in core_lines:
                                span = math.dist((xs[a[0]], ys[a[1]]), (xs[b[0]], ys[b[1]]))
                                p += span / 2 / 1000 * bw / 1000 * (bh - t_least) / 1000 * gamma
                    side = col_side[(i, j, k)] / 1000
                    p += side * side * heights[k] / 1000 * gamma
                    loads[(i, j, k)] = p
        # Sizes by storey group and position.
        group_side = {}
        for (i, j, k), p in loads.items():
            ag = POSITION_FACTOR[position(i, j)] * p * 1000 / (0.4 * fc)  # mm²
            side = max(ceil_to(math.sqrt(ag), 50), col_min)
            key = (group_of[k], position(i, j))
            group_side[key] = max(group_side.get(key, 0.0), side)
        # Never larger above than below.
        for kind in POSITION_FACTOR:
            for g in range(len(groups) - 2, -1, -1):
                if (g, kind) in group_side and (g + 1, kind) in group_side:
                    group_side[(g, kind)] = max(group_side[(g, kind)], group_side[(g + 1, kind)])
        new_sides = {
            (i, j, k): group_side[(group_of[k], position(i, j))]
            for i in range(nx)
            for j in range(ny)
            for k in range(1, n + 1)
        }
        if new_sides == col_side:
            break
        col_side = new_sides

    if special:
        narrow = [
            e
            for e, (bw, _) in beam_size.items()
            if e not in core_lines
            and bw > min(col_side[(*end, k)] for end in e for k in range(1, n + 1))
        ]
        if narrow:
            notes.append(
                f"{len(narrow)} beams are wider than a supporting column somewhere up the "
                "building: Sec 8.3.4.1(d)(ii) limits the width to the column width plus "
                "extensions; check them in Design mode."
            )

    # ── walls ──
    wall_t = 200.0 if n <= 10 else 250.0 if n <= 20 else 300.0

    # ── object types ──
    objects: list[dict[str, Any]] = []
    type_ids: set[str] = set()

    def add(data: dict[str, Any]) -> str:
        if data["id"] not in type_ids:
            type_ids.add(data["id"])
            objects.append(data)
        return data["id"]

    def linear(kind: str) -> dict[str, Any] | None:
        if not s.reinforcement:
            return None
        r = copy.deepcopy(TEMPLATES["LinearReinforcement"])
        r["material"] = s.rebar
        if kind == "column":
            r["longitudinal"] = [{"position": "perimeter", "count": 8, "dia": 20}]
            r["transverse"] = {"type": "tie", "dia": 10, "spacing": 150, "legs": 2}
        return r

    def with_bars(data: dict[str, Any], key: str, kind: str = "") -> dict[str, Any]:
        if not s.reinforcement:
            return data
        if key == "LinearReinforcement":
            data["reinforcement"] = linear(kind)
        else:
            r = copy.deepcopy(TEMPLATES[key])
            r["material"] = s.rebar
            data["reinforcement"] = r
        return data

    def column_type(side: float) -> str:
        cid = f"C{side:g}x{side:g}"
        return add(
            with_bars(
                _template(
                    "Column",
                    id=cid,
                    name=f"Column {side:g}x{side:g}",
                    material=s.concrete,
                    profile={"shape": "rectangle", "xDim": side, "yDim": side},
                ),
                "LinearReinforcement",
                "column",
            )
        )

    def beam_type(width: float, depth: float) -> str:
        bid = f"B{width:g}x{depth:g}"
        return add(
            with_bars(
                _template(
                    "Beam",
                    id=bid,
                    name=f"Beam {width:g}x{depth:g}",
                    material=s.concrete,
                    profile={"shape": "rectangle", "xDim": width, "yDim": depth},
                ),
                "LinearReinforcement",
            )
        )

    def slab_type(t: float, system: str) -> str:
        suffix = {"twoWay": "", "oneWay": "-1W", "flat": "-FP"}[system]
        sid = f"S{t:g}{suffix}"
        name = {"twoWay": "Slab", "oneWay": "One-way slab", "flat": "Flat plate"}[system]
        return add(
            with_bars(
                _template(
                    "Slab",
                    id=sid,
                    name=f"{name} {t:g}",
                    material=s.concrete,
                    thickness=t,
                    system=system,
                ),
                "PlanarReinforcement",
            )
        )

    def wall_type(t: float) -> str:
        return add(
            with_bars(
                _template(
                    "Wall", id=f"W{t:g}", name=f"Wall {t:g}", material=s.concrete, thickness=t
                ),
                "WallReinforcement",
            )
        )

    # ── the floor plan ──
    def gp(i: int, j: int) -> dict[str, str]:
        return {"x": xl[i], "y": yl[j]}

    def name(i: int, j: int) -> str:
        return f"{xl[i]}{yl[j]}"

    columns, beams, walls, slabs = [], [], [], []
    for k in range(1, n + 1):
        sid = story_ids[k]
        for i in range(nx):
            for j in range(ny):
                columns.append(
                    {
                        "id": f"C-{name(i, j)}-{sid}",
                        "type": column_type(col_side[(i, j, k)]),
                        "at": gp(i, j),
                        "base": story_ids[k - 1],
                        "top": sid,
                    }
                )
        for (a, b), (bw, bh) in beam_size.items():
            if (a, b) in core_lines:
                continue
            beams.append(
                {
                    "id": f"B-{name(*a)}-{name(*b)}-{sid}",
                    "type": beam_type(bw, bh),
                    "story": sid,
                    "start": gp(*a),
                    "end": gp(*b),
                }
            )
        for a, b in sorted(core_lines):
            walls.append(
                {
                    "id": f"W-{name(*a)}-{name(*b)}-{sid}",
                    "type": wall_type(wall_t),
                    "base": story_ids[k - 1],
                    "top": sid,
                    "start": gp(*a),
                    "end": gp(*b),
                }
            )
        for (i, j), (t, system, _) in sorted(slab_of.items()):
            slabs.append(
                {
                    "id": f"S-{name(i, j)}-{sid}",
                    "type": slab_type(t, system),
                    "story": sid,
                    "boundary": [gp(i, j), gp(i + 1, j), gp(i + 1, j + 1), gp(i, j + 1)],
                }
            )

    # Typical floors: consecutive storeys above L1 with the same plan form a family.
    def signature(k: int) -> tuple[Any, ...]:
        sid = story_ids[k]
        rows = [("c", m["at"]["x"], m["at"]["y"], m["type"]) for m in columns if m["top"] == sid]
        rows += [("b", m["id"].rsplit("-", 1)[0], m["type"]) for m in beams if m["story"] == sid]
        rows += [("w", m["id"].rsplit("-", 1)[0], m["type"]) for m in walls if m["top"] == sid]
        rows += [("s", m["id"].rsplit("-", 1)[0], m["type"]) for m in slabs if m["story"] == sid]
        return tuple(sorted(rows))

    similar: dict[int, int] = {}
    families: list[list[str]] = []
    if s.typical and n >= 3:
        master = 2
        family = [2]
        for k in range(3, n + 1):
            if signature(k) == signature(master):
                similar[k] = master
                family.append(k)
            else:
                families.append([story_ids[m] for m in family])
                master, family = k, [k]
        families.append([story_ids[m] for m in family])
        families = [f for f in families if len(f) > 1]

    plan = FloorPlan.model_validate(
        {
            "grids": {
                "x": [{"label": xl[i], "position": xs[i]} for i in range(nx)],
                "y": [{"label": yl[j], "position": ys[j]} for j in range(ny)],
            },
            "stories": [
                {
                    "id": story_ids[k],
                    "name": "Base" if k == 0 else stories[k - 1].name,
                    "elevation": levels[k],
                    **({"similarTo": story_ids[similar[k]]} if k in similar else {}),
                }
                for k in range(n + 1)
            ],
            "columns": columns,
            "beams": beams,
            "walls": walls,
            "slabs": slabs,
        }
    )
    library = ObjectLibrary.model_validate({"objects": objects})
    problems = [*library.check_materials(materials), *plan.check_objects(library)]
    if problems:  # pragma: no cover - a generator bug
        raise ValueError("; ".join(problems))

    # ── 9 Substructure ──
    qa = s.allowableBearing or final.foundation.allowableBearing or DEFAULT_BEARING
    foundations: list[dict[str, Any]] = []
    footing_rule = ""
    core_rule = ""
    # The core walls' own weight over the full height, per wall line [kN].
    wall_weight = {
        line: wall_t
        / 1000
        * math.dist((xs[line[0][0]], ys[line[0][1]]), (xs[line[1][0]], ys[line[1][1]]))
        / 1000
        * (levels[n] - levels[0])
        / 1000
        * gamma
        for line in core_lines
    }
    core_corners: set[tuple[int, int]] = set()
    if core is not None:
        ci, cj = core
        core_corners = {(ci, cj), (ci + 1, cj), (ci, cj + 1), (ci + 1, cj + 1)}
    if s.footing == "isolated":
        size: dict[tuple[int, int], float] = {}
        strips: list[tuple[float, float, float, float]] = []  # x0, y0, x1, y1
        pads: list[tuple[float, float, float, float]] = []
        if core is not None:
            ci, cj = core
            lx, ly = xs[ci + 1] - xs[ci], ys[cj + 1] - ys[cj]
            core_found: list[dict[str, Any]] = []
            core_rects: list[tuple[float, float, float, float]] = []
            strip_b: dict[int, float] = {}
            fits = True
            # Strips along the two Y walls, each carrying its wall and the two core columns.
            for i in (ci, ci + 1):
                a, b = (i, cj), (i, cj + 1)
                p = loads[(*a, 1)] + loads[(*b, 1)] + wall_weight[(a, b)]
                need = 1.1 * p / qa * 1e6  # mm²
                width = max(600.0, ceil_to((-ly + math.sqrt(ly * ly + 4 * need)) / 2, 100))
                strip_b[i] = width
                y0, y1 = ys[cj] - width / 2, ys[cj + 1] + width / 2
                core_found.append(
                    {
                        "id": f"F-{name(*a)}-{name(*b)}",
                        "type": "strip",
                        "columns": [
                            f"C-{name(*a)}-L1",
                            f"C-{name(*b)}-L1",
                            f"W-{name(*a)}-{name(*b)}-L1",
                        ],
                        "path": [[xs[i], y0], [xs[i], y1]],
                        "width": width,
                        "thickness": max(450.0, ceil_to(width / 4, 50)),
                        "material": s.concrete,
                        "note": f"Preliminary core strip: gravity service load {p:.0f} kN "
                        f"(two columns and the wall), qa {qa:g} kPa; overturning not included.",
                    }
                )
                core_rects.append((xs[i] - width / 2, y0, xs[i] + width / 2, y1))
            # Strips under the two X walls, between the Y strips: only where a strip at least
            # as long as it is wide fits between them.
            for j in (cj, cj + 1):
                a, b = (ci, j), (ci + 1, j)
                x0, x1 = xs[ci] + strip_b[ci] / 2, xs[ci + 1] - strip_b[ci + 1] / 2
                length = x1 - x0
                p = wall_weight[(a, b)]
                width = max(600.0, ceil_to(1.1 * p / qa * 1e6 / max(length, 1.0), 100))
                if length < max(width, 600.0):
                    fits = False
                    break
                core_found.append(
                    {
                        "id": f"F-{name(*a)}-{name(*b)}",
                        "type": "strip",
                        "columns": [f"W-{name(*a)}-{name(*b)}-L1"],
                        "path": [[x0, ys[j]], [x1, ys[j]]],
                        "width": width,
                        "thickness": max(450.0, ceil_to(width / 4, 50)),
                        "material": s.concrete,
                        "note": f"Preliminary core strip: the wall's weight {p:.0f} kN over "
                        f"{length:.0f} mm between the core's other strips, qa {qa:g} kPa; "
                        "overturning not included.",
                    }
                )
                core_rects.append((x0, ys[j] - width / 2, x1, ys[j] + width / 2))
            overturning = (
                "The core's OVERTURNING under wind and earthquake is not included and usually "
                "governs: Part 9 designs the core foundation from the analysis reactions."
            )
            if fits:
                foundations += core_found
                strips += core_rects
                core_rule = (
                    "Core foundation: a strip footing under each core wall in place of the "
                    "isolated footings of the four core columns; the strips on the "
                    f"{xl[ci]} and {xl[ci + 1]} lines carry their wall and both core columns, "
                    f"the strips on the {yl[cj]} and {yl[cj + 1]} lines their wall between "
                    "them; width from 1.1 x the gravity service load (columns as above plus the "
                    "walls' own weight, the slab load on the walls being in the columns' "
                    "tributary areas) / qa, at least 600 mm, rounded up to 100 mm; thickness "
                    "max(450 mm, width/4). " + overturning
                )
            else:
                # The strips would fill the core: one raft under the whole core instead.
                p = sum(loads[(*c, 1)] for c in core_corners) + sum(wall_weight.values())
                need = 1.1 * p / qa * 1e6  # mm²
                e = (-(lx + ly) + math.sqrt((lx + ly) ** 2 - 4 * (lx * ly - need))) / 4
                e = max(500.0, ceil_to(e, 100))
                x0, y0, x1, y1 = xs[ci] - e, ys[cj] - e, xs[ci + 1] + e, ys[cj + 1] + e
                t = max(500.0, ceil_to(100.0 * n, 50))
                foundations.append(
                    {
                        "id": "F-CORE",
                        "type": "raft",
                        "columns": [f"C-{name(*c)}-L1" for c in sorted(core_corners)],
                        "outline": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                        "thickness": t,
                        "material": s.concrete,
                        "note": f"Preliminary core raft: gravity service load {p:.0f} kN (the "
                        f"four core columns and the walls), qa {qa:g} kPa; overturning not "
                        "included.",
                    }
                )
                strips.append((x0, y0, x1, y1))
                core_rule = (
                    "Core foundation: strip footings under the core walls would fill the core, so "
                    f"one raft F-CORE carries the four core columns and the walls: the core bay "
                    f"plus {e:g} mm all round, from 1.1 x the gravity service load (the columns "
                    "as above plus the walls' own weight) / qa, at least 500 mm, rounded up to "
                    "100 mm; thickness max(500 mm, 100 mm per storey). Part 9's raft design "
                    "takes column reactions only (walls on rafts: not yet): check the walls' "
                    "share by hand. " + overturning
                )
        for i in range(nx):
            for j in range(ny):
                if (i, j) in core_corners:
                    continue
                p = loads[(i, j, 1)]
                b = ceil_to(math.sqrt(1.1 * p / qa) * 1000, 100)
                size[(i, j)] = b
                t = max(450.0, ceil_to(b / 4, 50))
                foundations.append(
                    {
                        "id": f"F-{name(i, j)}",
                        "type": "isolated",
                        "columns": [f"C-{name(i, j)}-L1"],
                        "center": [xs[i], ys[j]],
                        "length": b,
                        "width": b,
                        "thickness": t,
                        "material": s.concrete,
                        "note": f"Preliminary: service load {p:.0f} kN, qa {qa:g} kPa.",
                    }
                )
                pads.append((xs[i] - b / 2, ys[j] - b / 2, xs[i] + b / 2, ys[j] + b / 2))
        clash = 0
        for i in range(nx):
            for j in range(ny):
                if (i, j) in core_corners:
                    continue
                for nb, gap in (
                    ((i + 1, j), xs[i + 1] - xs[i] if i < nx - 1 else 0.0),
                    ((i, j + 1), ys[j + 1] - ys[j] if j < ny - 1 else 0.0),
                ):
                    if nb in size and (size[(i, j)] + size[nb]) / 2 > gap - 300:
                        clash += 1
        # Isolated footings within 300 mm of a core strip.
        for sx0, sy0, sx1, sy1 in strips:
            for px0, py0, px1, py1 in pads:
                if px0 < sx1 + 300 and sx0 < px1 + 300 and py0 < sy1 + 300 and sy0 < py1 + 300:
                    clash += 1
        footing_rule = (
            f"Isolated footings: square, side = sqrt(1.1 P / qa) rounded up to 100 mm, P the "
            f"service load at the base (dead + superimposed dead + live, +10 % for the footing "
            f"and the soil on it), qa = {qa:g} kPa"
            + (
                " (the settings' override)"
                if not s.allowableBearing and final.foundation.allowableBearing
                else " (given)"
                if s.allowableBearing
                else " (assumed: enter the soil report's value)"
            )
            + "; thickness max(450 mm, side/4) rounded up to 50 mm (rule of thumb). Part 9 "
            "designs them on the soil report."
        )
        if clash:
            notes.append(
                f"{clash} pairs of footings come within 300 mm of each other: consider combined "
                "footings or a mat."
            )
    elif s.footing == "mat":
        o = s.matOverhang
        outline = [[-o, -o], [xs[-1] + o, -o], [xs[-1] + o, ys[-1] + o], [-o, ys[-1] + o]]
        t = max(500.0, ceil_to(100.0 * n, 50))
        total = sum(loads[(i, j, 1)] for i in range(nx) for j in range(ny))
        total += sum(wall_weight.values())
        area = (xs[-1] + 2 * o) * (ys[-1] + 2 * o) / 1e6
        if wall_weight:
            core_rule = (
                "Core walls stand on the mat; their own weight is in its average pressure, but "
                "Part 9's raft design takes column reactions only (walls on rafts: not yet), and "
                "the core's overturning under wind and earthquake is not in this preliminary "
                "pressure: check the mat under the core by hand from the analysis reactions."
            )
        foundations.append(
            {
                "id": "MAT",
                "type": "raft",
                "outline": outline,
                "thickness": t,
                "material": s.concrete,
                "note": f"Preliminary: service load {total:.0f} kN over {area:.0f} m².",
            }
        )
        footing_rule = (
            f"Mat: the grid plus {o:g} mm all round; thickness max(500 mm, 100 mm per storey) "
            f"(rule of thumb); average service pressure {total / area:.0f} kPa against qa "
            f"{qa:g} kPa (the mat's own weight not included). Part 9 designs it on springs."
        )
    elif wall_weight:
        core_rule = (
            "No foundations were generated: the core walls need their own foundation (strip "
            "footings or a raft under the core, designed for the core's overturning) in 09 "
            "Substructure, besides the columns' footings."
        )
    substructure = Substructure.model_validate({"foundations": foundations})

    # ── notes ──
    notes += beam_rule
    if not flat:
        notes.append(
            "Slabs with beams: Sec 6.2.5.3.3 with alpha_f of the rectangular beam section (no "
            "slab flange, on the low side) over the slab strip it carries; one-way panels "
            "(beta > 2) by Table 6.6.1; at least "
            f"{s.minSlab:g} mm (SAEngine practice), rounded up to 25 mm."
        )
    else:
        notes.append(
            f"Flat plate: {flat_t:g} mm from {flat_how}. Punching shear is not checked "
            "here: Design mode checks it (consider drop panels or shear reinforcement)."
        )
    notes.append(
        "Columns: square, Ag = k P / (0.4 f'c) with P the service load (slab self-weight, beams "
        "below the slab, finishes, partitions and live load of every floor above, tributary "
        "area to the bay centre lines, plus the columns' own weight; no live load reduction) "
        f"and k = 1.0 interior, 1.25 edge, 1.5 corner for bending (a preliminary rule of "
        f"thumb), side rounded up to 50 mm, at least {col_min:g} mm"
        + (" (Sec 8.3.5.1(a))" if special else "")
        + f"; one type per {s.columnGroupStoreys} storeys (groups "
        + ", ".join(f"{story_ids[g[0]]}-{story_ids[g[-1]]}" for g in groups)
        + ") and position, never larger above than below."
    )
    if sdc in ("C", "D"):
        # Integrator glue (review): the sizes above carry gravity only; say so loudly where
        # the earthquake usually governs the columns.
        notes.insert(
            0,
            f"WARNING - Seismic Design Category {sdc}: the column sizes are for GRAVITY ONLY. "
            "The earthquake moments (and, in a special moment frame, the strong-column / "
            "weak-beam and joint rules) usually govern the columns here, the corner and edge "
            "ones most. Expect Design mode to report some columns as 'section too small': "
            "enlarge those column types (Members Table or 04 Objects) after the first Run All"
            + ("; the core walls take most of the storey shear" if walls_on else "")
            + ".",
        )
    if walls_on:
        notes.append(
            f"Core walls round bay {xl[core[0]]}{yl[core[1]]}-{xl[core[0] + 1]}{yl[core[1] + 1]}"  # type: ignore[index]
            f" ({wall_t:g} mm: 200 up to 10 storeys, 250 up to 20, 300 above, rule of thumb), "
            "in place of the beams on its sides; add the door openings (06 BIM) and the slab "
            "opening of a lift or stair core."
        )
    if footing_rule:
        notes.append(footing_rule)
    if core_rule:
        notes.append(core_rule)
    if families:
        notes.append(
            "Typical floors: "
            + "; ".join(
                f"{f[1] if len(f) == 2 else f[1] + '-' + f[-1]} similar to {f[0]}" for f in families
            )
            + " (a new family where the column types change)."
        )
    if not s.reinforcement:
        notes.append("No bars on the types: Design mode proposes them after the analysis.")

    summary = {
        "sdc": sdc,
        "zone": zone,
        "system": system_id,
        "counts": {
            "columns": len(columns),
            "beams": len(beams),
            "walls": len(walls),
            "slabs": len(slabs),
            "foundations": len(foundations),
        },
        "columnTypes": {
            f"{story_ids[groups[g][0]]}-{story_ids[groups[g][-1]]} {kind}": f"C{side:g}x{side:g}"
            for (g, kind), side in sorted(group_side.items())
        },
        "beamTypes": sorted({o["id"] for o in objects if o["kind"] == "beam"}),
        "slabTypes": sorted({o["id"] for o in objects if o["kind"] == "slab"}),
        "families": families,
        # Integrator glue: the service load the columns were sized for at the base [kN], by
        # grid intersection (the verification pack's gravity check sums them).
        "baseServiceLoads": {
            f"{xl[i]}{yl[j]}": round(loads[(i, j, 1)], 2)
            for i in range(nx)
            for j in range(ny)
            if (i, j, 1) in loads
        },
    }
    dump = {"mode": "json", "by_alias": True, "exclude_none": True}
    return {
        "materials": materials.model_dump(**dump),
        "objects": library.model_dump(**dump),
        "floorPlan": plan.model_dump(**dump),
        "substructure": substructure.model_dump(**dump),
        "settings": final.model_dump(**dump),
        "settingsPatch": patch,
        "notes": notes,
        "summary": summary,
    }


# ─────────────────────────────────────────── writing ───────────────────────────────────────────

#: Where the generated parts go, relative to the project folder.
PATHS = {
    "settings": "02 Project Settings/project-settings.json",
    "materials": "03 Materials/materials.json",
    "objects": "04 Objects/objects.json",
    "floorPlan": "05 Floor Plan/floor-plan.json",
    "bim": "06 BIM/bim.json",
    "substructure": SUBSTRUCTURE_FILE,
}

PARTS = [
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
]


def _json_text(data: Any) -> str:
    from saengine.importers.common import json_text

    return json_text(data)


def building_texts(result: dict[str, Any]) -> dict[str, str]:
    """The texts of the part files of a :func:`generate_building` result by project path,
    with the building model (``06 BIM``) generated from the floor plan."""
    texts = {
        PATHS[key]: _json_text(result[key])
        for key in ("settings", "materials", "objects", "floorPlan", "substructure")
    }
    plan = FloorPlan.model_validate(result["floorPlan"])
    bim = generate(plan, source_stamp(texts[PATHS["floorPlan"]]))
    texts[PATHS["bim"]] = _json_text(bim)
    return texts


def write_building(
    result: dict[str, Any], folder: str | Path, name: str | None = None
) -> list[Path]:
    """Writes the generated parts into ``folder`` (replacing those part files) and, when the
    folder has no project manifest, a new one named ``name``; returns the files written."""
    root = Path(folder)
    texts = building_texts(result)
    if not any(root.glob("*.saengine")):
        title = name or result["settings"]["project"]["name"]
        safe = re.sub(r'[<>:"/\\|?*]+', "-", title).strip() or "Building"
        texts[f"{safe}.saengine"] = (
            json.dumps(
                {
                    "schema": 1,
                    "name": title,
                    "created": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "type": "building",
                    "parts": PARTS,
                },
                indent="\t",
            )
            + "\n"
        )
    written = []
    for relative, text in texts.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


__all__ = ["BuildingSpec", "building_texts", "generate_building", "write_building"]

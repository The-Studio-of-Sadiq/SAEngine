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
- Stiffness (:func:`stiffness_estimate`, before the P-M sizing of the columns): Sec 6.3.10.4.1
  (p. 912) cracked moments of inertia, used for the lateral deflections under factored loads
  by Sec 6.1.10.2 (p. 893) and at 1.4 times under service loads by Sec 6.1.10.1 (p. 893);
  the design drift Cd δe / I (Sec 2.5.7.7, p. 631) against Δa of Table 6.2.21 (p. 648) / ρ
  (Sec 2.5.14.1, p. 647); the period against Cu Ta (Sec 2.5.7.2 (a), p. 627; eq. 6.2.38 and
  Table 6.2.20, p. 628); wind deflection H/500 (Sec 1.5.6.1, page not in the code pack).
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

from saengine.codes import context as code_context
from saengine.library import bnbc
from saengine.library.bim import generate, source_stamp
from saengine.library.defaults import default_material_library
from saengine.library.floorplan import FloorPlan
from saengine.library.materials import Category, MaterialDefaults
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


#: Steel ratio the lateral sizing allows a column [-]: a column that needs more is enlarged,
#: leaving the design mode room above it (ρ up to 8 %, 6 % in special frames) for what this
#: preliminary method leaves out (practice).
RHO_TARGET = 0.025


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
    siteClassSource: Literal["entered", "assumed"] = Field(
        default="entered",
        description="How siteClass was found: entered (known, e.g. from a soil report read by "
        "the engineer) or assumed (no soil report yet: the soil report replaces it once its "
        "boreholes give a class).",
    )
    allowableBearing: float | None = Field(
        default=None,
        gt=0,
        description="Net allowable bearing pressure for the preliminary footing sizes [kPa]; "
        "none: the settings' override, else 100 kPa.",
    )
    columnGroupStoreys: int = Field(
        default=3, ge=1, le=20, description="Storeys per column type change."
    )
    lateralSizing: Literal["auto", "gravity"] = Field(
        default="auto",
        description="Column sizes: 'auto' also for the wind and earthquake moments (portal "
        "method, P-M interaction, strong column / weak beam) in Seismic Design Categories C and "
        "D, and for wind in B; 'gravity' the axial rule only.",
    )
    columnRho: float = Field(
        default=RHO_TARGET,
        ge=0.01,
        le=0.06,
        description="Steel ratio the lateral column sizing allows before it enlarges a column.",
    )
    beamSpanDepth: float | None = Field(
        default=12,
        gt=0,
        description="Rule of thumb span/depth of frame beams, for their stiffness under lateral "
        "load (the stiffness check may deepen them to span/10); none: the deflection minimum "
        "only.",
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
    from saengine.design.seismic_rules import NP, _level_at_least, required_level, system_row

    candidates = {
        "rcFrame": ["rcOmf", "rcImf", "rcSmf"],
        "rcFrameWithWalls": ["rcOrdinaryWallFrame", "rcDualSpecial"],
        "flatSlab": ["rcOmf", "rcImf", "rcSpecialWallFrame", "rcDualSpecial"],
    }[kind]
    category = sdc or "B"
    notes: list[str] = []
    for system in candidates:
        row = system_row(system)
        if row is None:
            continue
        limit = row.limits["BCD".index(category)]
        if limit == NP or (limit is not None and height_m > limit):
            continue
        if row.frame is not None and not _level_at_least(
            row.frame, required_level(category) or "ordinary"
        ):
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


# ─────────────────────────────────── lateral (P–M) column sizing ───────────────────────────────────

#: Largest column side the lateral sizing tries [mm].
MAX_SIDE = 1500.0
#: Accidental eccentricity of the storey forces, as a share of the plan dimension across them
#: (the static method's 5 %), for the share of the edge frames.
ACCIDENTAL = 0.05
#: Allowance on the beams' estimated flexural strength for the bars rounded up by the design
#: (strong column / weak beam): practice.
BEAM_BARS_ALLOWANCE = 1.15
#: The portal method's inflection points as a share of the storey height above its bottom:
#: mid-height, the lowest storey (fixed base) at two thirds.
INFLECTION = 0.5
INFLECTION_BASE = 2 / 3
#: Axial forces of the strong column / weak beam check rounded outwards to this [N].
AXIAL_STEP = 50e3
#: Demand points whose axial forces are within this [N] are compared as at one force (the
#: weaker ones dropped before the interaction check): a speed-up, at most this much off in P.
PRUNE_STEP = 10e3


def _prune(points: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """The demand points (Pu, Mux, Muy, ...) less those another point within
    :data:`PRUNE_STEP` of its axial force exceeds in both moments (the interaction check
    takes the worst, so they cannot govern unless Pu itself does: the largest and least Pu
    are kept)."""
    if len(points) < 50:
        return points
    bins: dict[int, list[tuple[Any, ...]]] = {}
    for p in points:
        bins.setdefault(round(p[0] / PRUNE_STEP), []).append(p)
    kept = [max(points, key=lambda p: p[0]), min(points, key=lambda p: p[0])]
    for group in bins.values():
        group.sort(key=lambda p: (-p[1], -p[2]))
        best_y = -math.inf
        for p in group:
            if p[2] > best_y:
                kept.append(p)
                best_y = p[2]
    return kept


#: Integrator glue (performance): the column searches (and their interaction surfaces) of the
#: lateral sizing by (side, f'c, fy, Es, ρ, concrete), shared by the generator's calls.
_SEARCHES: dict[tuple[Any, ...], Any] = {}


#: Cracked moments of inertia for the lateral deflections: BNBC 2020 Part 6 Sec 6.3.10.4.1
#: (columns 0.70 Ig, beams 0.35 Ig, flat plates 0.25 Ig), which Sec 6.1.10.2 (p. 893) uses for
#: the lateral deflections; the analysis model's default ("cracked") stiffness.
CRACKED_COLUMN, CRACKED_BEAM, CRACKED_PLATE = 0.70, 0.35, 0.25


def floor_beam_stiffness(
    beams: dict[tuple[tuple[int, int], tuple[int, int]], tuple[float, float]],
    xs: list[float],
    ys: list[float],
    slab_t: float,
    along_x: bool,
    rigid: float = 0.0,
    column_side: dict[tuple[int, int], float] | None = None,
) -> float:
    """ΣKb [mm³] of a floor's beams along x (or y): 0.35 Ib / l each (Sec 6.3.10.4.1), the
    rectangle without the slab flange; with no beams (a flat plate) each panel's slab strip
    across the whole plan at 0.25 Ig. ``rigid``: the rigid zone factor of the analysis model's
    end offsets (:mod:`saengine.fem.end_zones`), the offset half the ``column_side`` at each
    end: a beam rigid over r a at both ends is (l / lc)³ times stiffer at its joints in
    antisymmetric bending, lc = l - r (a1 + a2) its flexible length."""
    total = 0.0
    for (a, b), (bw, bh) in beams.items():
        if (a[1] == b[1]) == along_x:
            span = math.dist((xs[a[0]], ys[a[1]]), (xs[b[0]], ys[b[1]]))
            factor = 1.0
            if rigid > 0 and column_side:
                flexible = span - rigid * (column_side[a] + column_side[b]) / 2
                factor = (span / max(flexible, 0.5 * span)) ** 3
            total += CRACKED_BEAM * bw * bh**3 / 12 / span * factor
    if total <= 0:
        spans, other = (xs, ys) if along_x else (ys, xs)
        width = other[-1] - other[0]
        total = sum(
            CRACKED_PLATE * width * slab_t**3 / 12 / (spans[m + 1] - spans[m])
            for m in range(len(spans) - 1)
        )
    return total


def storey_column_stiffness(
    side_of: dict[tuple[int, int, int], float],
    nx: int,
    ny: int,
    k: int,
    height: float,
    rigid: float = 0.0,
    top_depth: dict[tuple[int, int], float] | None = None,
) -> float:
    """ΣKc [mm³] of storey ``k``'s square columns: 0.70 Ic / h each (Sec 6.3.10.4.1); with the
    analysis model's rigid zone factor ``rigid`` and the depth of the deepest beam at each
    column's top (its end offset), (h / hc)³ times that, hc = h - r d the flexible height."""
    total = 0.0
    for i in range(nx):
        for j in range(ny):
            factor = 1.0
            if rigid > 0 and top_depth:
                flexible = height - rigid * top_depth.get((i, j), 0.0)
                factor = (height / max(flexible, 0.5 * height)) ** 3
            total += CRACKED_COLUMN * side_of[(i, j, k)] ** 4 / 12 / height * factor
    return total


def wilbur_flexibility(
    heights: list[float], k: int, sum_kc: float, sum_kb: float, ec: float
) -> tuple[float, float]:
    """(Δ / V [mm/kN], the columns' share of it) of storey ``k`` (1..n; ``heights[0]`` unused)
    by Wilbur's storey stiffness: Δ / V = h / (48 Ec) (4 h / ΣKc + (hb + h) / ΣKb,below +
    (h + ha) / ΣKb,above), the first storey on a fixed base h1 / (48 Ec) (4 h1 / ΣKc +
    (h1 + h2) / (ΣKb + ΣKc / 12)); the beams alike at every floor, the roof storey taking its
    own height for the one above."""
    n = len(heights) - 1
    h = heights[k]
    below = heights[k - 1] if k > 1 else h
    above = heights[k + 1] if k < n else h
    columns = 4 * h / sum_kc
    if k == 1:
        bracket = columns + (h + above) / (sum_kb + sum_kc / 12)
    else:
        bracket = columns + (below + h) / sum_kb + (h + above) / sum_kb
    return h / (48 * ec) * bracket * 1e3, columns / bracket


#: Lateral deflection under the service wind, as a share of the building height: BNBC 2020
#: Part 6 Sec 1.5.6.1 limits the lateral deflection or drift due to wind to H/500 (the page is
#: not in the code pack: check it). Taken at the roof.
WIND_DRIFT = 1 / 500
#: Stiffness of the members for the lateral deflections under the SERVICE (wind) loads, as a
#: factor on the cracked stiffness above: BNBC 2020 Part 6 Sec 6.1.10.1 (p. 893; ACI 318-11
#: 8.8.1): 1.4 times the flexural stiffness of Sec 6.1.10.2.
SERVICE_STIFFNESS = 1.4
#: The deepest frame beam the stiffness pass makes, as span / depth (practice), and the widest,
#: as a share of its depth and at most STIFF_BEAM_WIDTH mm (practice).
STIFF_BEAM_SPAN_DEPTH = 10.0
STIFF_BEAM_WIDTH_SHARE = 0.6
STIFF_BEAM_WIDTH = 400.0
#: The estimated period the stiffness pass aims at, as a multiple of Cu Ta (Sec 2.5.7.2 (a),
#: p. 627). Cu Ta caps the period the static forces may use; it is not a limit on the
#: structure, and an analysis model on cracked sections (Sec 6.3.10.4.1) usually comes out
#: longer than the empirical Ta, which is fitted to measured buildings with their infill
#: (practice). A frame estimated at more than 1.5 Cu Ta is taken as too flexible.
PERIOD_TARGET = 1.5


class StiffnessEstimate(BaseModel):
    """What :func:`stiffness_estimate` found per direction ("X", "Y")."""

    period: dict[str, float]
    periodLimit: float
    ta: float
    #: Per direction and storey 1..n: the design drift Cd δe / I over its limit Δa (Table
    #: 6.2.21) and the columns' share of the storey's flexibility; per direction the roof's
    #: service wind deflection over H / 500.
    seismicRatio: dict[str, list[float]]
    windRatio: dict[str, float]
    columnShare: dict[str, list[float]]
    driftLimit: float | None = None
    cd: float | None = None


# Under the project's pack, as lateral_column_sizes (integration glue).
@code_context.in_project_pack()
def stiffness_estimate(
    settings: ProjectSettings,
    sdc: str | None,
    *,
    xs: list[float],
    ys: list[float],
    heights: list[float],
    side_of: dict[tuple[int, int, int], float],
    beams: dict[tuple[tuple[int, int], tuple[int, int]], tuple[float, float]],
    slab_t: float,
    ec: float,
    weights: list[float],
) -> StiffnessEstimate:
    """A PRELIMINARY estimate of the frames' period and storey drifts (both directions, the
    frames taking all the storey shear), from Wilbur's storey stiffness
    (:func:`wilbur_flexibility`, columns 0.70 Ig, beams 0.35 Ig, Sec 6.3.10.4.1) as a shear
    building; ``weights`` the seismic weight of levels 1..n [kN].

    - period by Rayleigh's quotient T = 2π √(Σ wi δi² / (g Σ Fi δi)) under the static
      method's forces, against Cu Ta: Ta = Ct hn^m (Sec 2.5.7.2, eq. 6.2.38, p. 627; Ct, m of
      Table 6.2.20, p. 628) and Cu = 1.4 (Sec 2.5.7.2 (a), p. 627);
    - earthquake: δe of each storey under the equivalent static forces at Ta (Sec 2.5.7,
      :mod:`saengine.fem.loads`), the design drift Cd δe / I (Sec 2.5.7.7, p. 631) against
      Δa / ρ of Table 6.2.21 (p. 648, Sec 2.5.14.1, p. 647);
    - wind: the storey drift under the service wind forces of the analysis model
      (:func:`saengine.fem.loads.wind_level_forces`, factor 1.0), the members at 1.4 times
      the cracked stiffness (Sec 6.1.10.1, :data:`SERVICE_STIFFNESS`): the roof's deflection
      against H / 500 (:data:`WIND_DRIFT`).

    The rigid end zones are those of the analysis model (``analysis.endOffsets``,
    ``rigidZoneFactor``: beams offset half the column at each end, columns the deepest beam at
    their top); the slab flanges, accidental torsion and P-delta are left out.
    """
    from saengine.fem import loads as fl
    from saengine.fem import seismic_design as sd
    from saengine.library.settings import derived

    nx, ny, n = len(xs), len(ys), len(heights) - 1
    values = derived(settings)
    tops = list(itertools.accumulate(heights[1:]))
    rel = [t / 1000 for t in tops]
    ta = fl.approximate_period(rel[-1], settings.seismic.system)
    upper = code_context.table("seismic").periodUpperFactor
    shape = fl.vertical_distribution(list(zip(rel, weights, strict=True)), 1.0, ta)
    lx_m, ly_m = (xs[-1] - xs[0]) / 1000, (ys[-1] - ys[0]) / 1000
    wind: dict[str, list[float]] = {}
    if values["windSpeed"]:
        args = (values["windSpeed"], settings.wind.exposure, values["windImportance"])
        wind["X"] = fl.wind_level_forces(rel, ly_m, lx_m, *args)
        wind["Y"] = fl.wind_level_forces(rel, lx_m, ly_m, *args)
    seismic_v = 0.0
    limit = cd = None
    if values["Z"]:
        sa = fl.design_acceleration(
            ta, settings.site.siteClass, values["Z"], values["seismicImportance"], values["R"]
        )
        seismic_v = sa * sum(weights)
        options = sd.options_from_settings(settings)
        limit = sd.allowable_drift_ratio(
            settings.occupancy.category, sdc, settings.seismic.system, options.redundancy
        )
        cd = float(values["Cd"])
    out = StiffnessEstimate(
        period={}, periodLimit=upper * ta, ta=ta, seismicRatio={}, windRatio={}, columnShare={},
        driftLimit=limit, cd=cd,
    )  # fmt: skip

    def shears(forces: list[float]) -> list[float]:
        return list(itertools.accumulate(reversed(forces)))[::-1]

    rigid = settings.analysis.rigidZoneFactor if settings.analysis.endOffsets else 0.0
    top_depth: dict[tuple[int, int], float] = {}
    for (a, b), (_bw, bh) in beams.items():
        for end in (a, b):
            top_depth[end] = max(top_depth.get(end, slab_t), bh)
    for i in range(nx):
        for j in range(ny):
            top_depth.setdefault((i, j), slab_t)
    for axis, along_x in (("X", True), ("Y", False)):
        flex, share = [], []
        for k in range(1, n + 1):
            sides = {(i, j): side_of[(i, j, k)] for i in range(nx) for j in range(ny)}
            kb = floor_beam_stiffness(beams, xs, ys, slab_t, along_x, rigid, sides)
            kc = storey_column_stiffness(side_of, nx, ny, k, heights[k], rigid, top_depth)
            f, c = wilbur_flexibility(heights, k, kc, kb, ec)
            flex.append(f)
            share.append(c)
        # Rayleigh: displacements [m] under the force shape (any scale).
        drift = [v * f / 1000 for v, f in zip(shears(shape), flex, strict=True)]
        disp = list(itertools.accumulate(drift))
        num = sum(w * d * d for w, d in zip(weights, disp, strict=True))
        den = G * sum(p * d for p, d in zip(shape, disp, strict=True))
        out.period[axis] = 2 * math.pi * math.sqrt(num / den) if den > 0 else 0.0
        out.columnShare[axis] = share
        out.seismicRatio[axis] = [
            (cd * v * seismic_v * f / values["seismicImportance"]) / (limit * heights[k + 1])
            if limit and cd
            else 0.0
            for k, (v, f) in enumerate(zip(shears(shape), flex, strict=True))
        ]
        roof = sum(
            v * f / SERVICE_STIFFNESS
            for v, f in zip(shears(wind.get(axis, [0.0] * n)), flex, strict=True)
        )
        out.windRatio[axis] = roof / (WIND_DRIFT * tops[-1])
    return out


class LateralSizing(BaseModel):
    """What :func:`lateral_column_sizes` found: the sides by (storey group, position), the
    governing demand of each, the base shears and notes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    sides: dict[tuple[int, str], float]
    governing: dict[tuple[int, str], str] = Field(default_factory=dict)
    baseShear: dict[str, float] = Field(default_factory=dict)
    swayFactor: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


# The generator runs under the pack the settings choose (integration glue): derived(settings)
# and the wind/seismic coefficient tables of fem.loads then come from the same pack.
@code_context.in_project_pack()
def lateral_column_sizes(
    settings: ProjectSettings,
    sdc: str | None,
    *,
    xs: list[float],
    ys: list[float],
    heights: list[float],
    groups: list[list[int]],
    side_of: dict[tuple[int, int, int], float],
    position: Any,
    parts: dict[str, Any],
    beams: dict[tuple[tuple[int, int], tuple[int, int]], tuple[float, float]],
    beam_loads: dict[tuple[tuple[int, int], tuple[int, int]], tuple[float, float]],
    slab_t: float,
    frame_share: float,
    special: bool,
    seismic: bool,
    wind: bool,
    fc: float,
    fy: float,
    es: float,
    ec: float,
    concrete: str,
    col_min: float,
    rho_target: float = RHO_TARGET,
) -> LateralSizing:
    """Column sides (square) for the combined axial force and moments of the strength
    combinations with wind and earthquake, by the portal method. ``side_of``: the current side
    of every column ``(i, j, k)`` (grid indices, storey 1..n; the gravity sizes on the first
    call); ``parts``: the service loads at each column (``dead``, ``live``, ``roof`` live [kN],
    every storey from the roof down to it) and ``levels`` (the dead load added at each level
    [kN], the seismic weight); ``beams``: (width, depth) of the beams by grid line piece and
    ``beam_loads`` their (dead, live) service line loads [kN/m]; ``frame_share`` the share of
    the storey shear the frames take (1 moment frames, 0.25 dual systems); ``seismic``,
    ``wind``: which lateral loads count.

    The method (stated in the notes it returns):

    - earthquake: the equivalent static force method of the analysis model itself
      (:mod:`saengine.fem.loads`: T = Ct hn^m, Sa = (2/3)(Z I / R) Cs, V = Sa W, the forces
      by Fx = V wx hx^k / Σ wi hi^k), W the dead and superimposed dead load of every level and
      the code's share of the floor live load, the beams at their full depth
      (``seismicLevels``, as fem.derive counts it);
      the strength combinations with E those of the design (:func:`saengine.fem.seismic_design.
      seismic_combinations`: 1.2D + Ev, 0.9D - Ev, 100 % + 30 % in Category D); the share of
      the edge frames raised for the accidental eccentricity of 5 % of the plan dimension;
    - wind: the analysis model's wind forces (:func:`saengine.fem.loads.wind_level_forces`)
      with the settings' combinations that have WX or WY;
    - the portal method in every frame line: the storey shear shared equally among the frame
      lines of a direction (rigid floors, frames alike), within a line the interior columns
      taking twice the shear of the end columns, inflection points at mid-height of the columns
      (two thirds of the lowest storey above its fixed base) and at mid-span of the beams; the
      beam shears give the end columns their axial forces;
    - the sway magnifier of the moment magnification method on the lateral moments
      (:func:`saengine.design.slender.delta_s_q`: δs = 1 / (1 - Q), Q = ΣPu Δo / (Vus lc),
      the design's default form), Δo / V of the storey by Wilbur's storey stiffness (the first
      storey on a fixed base), the columns at 0.7 Ig and the beams at 0.35 Ig; and M2,min = Pu (15 + 0.03 h) on each axis; the columns of a storey are made
      stiff enough for δs <= 1.5 (the design's limit, Sec 6.3.10.7.3, above which it asks for
      a second-order analysis), so the moments are magnified by at most 1.5;
    - a column type carries every member's demand, biaxial (P, Mx, My), on the interaction
      surface of the design (:class:`saengine.design.required.ColumnSearch`) with a bar layout
      of ρ at most ``rho_target``; in special moment frames also ΣMnc ≥ 1.2 ΣMnb at the floors
      where the columns carry more than 0.1 Ag f'c (Sec 8.3.5.2, :func:`saengine.design.
      ductile_joints.lowest_column_moment` of the type's least layout that carries it), the
      beams' Mn estimated from the bars their own portal and gravity moments need
      (:func:`saengine.design.bars.beam_flexure_need`, at least As,min, Mn+ at least half of
      Mn- as Sec 8.3.4.2(a)) times 1.15 for the bars rounded up.
    """
    from saengine.design import ductile_joints as dj
    from saengine.design import slender
    from saengine.design.bars import beam_flexure_need, beam_min_area, with_minimum
    from saengine.design.required import ColumnSearch, Options
    from saengine.fem import loads as fl
    from saengine.fem import seismic_design as sd
    from saengine.library.objects import Column
    from saengine.library.settings import derived

    nx, ny, n = len(xs), len(ys), len(heights) - 1
    group_of = {k: g for g, members in enumerate(groups) for k in members}
    values = derived(settings)
    base = [0.0]
    for k in range(1, n + 1):
        base.append(base[-1] + heights[k])
    out = LateralSizing(sides={})
    lx_m, ly_m = (xs[-1] - xs[0]) / 1000, (ys[-1] - ys[0]) / 1000

    # ── storey forces [kN] per direction and load ──
    forces: dict[str, list[float]] = {}
    if seismic and values["Z"]:
        weights = parts.get("seismicLevels", parts["levels"])[1:]
        period = fl.approximate_period(base[-1] / 1000, settings.seismic.system)
        sa = fl.design_acceleration(
            period, settings.site.siteClass, values["Z"], values["seismicImportance"], values["R"]
        )
        v = sa * sum(weights)
        levels = [(base[k] / 1000, weights[k - 1]) for k in range(1, n + 1)]
        forces["EX"] = forces["EY"] = fl.vertical_distribution(levels, v, period)
        out.baseShear["E"] = round(v, 1)
        out.notes.append(
            f"Earthquake: T = {period:.2f} s, Sa = {sa:.4f} g, W = {sum(weights):.0f} kN (dead "
            f"and superimposed dead of the levels, {code_context.table('seismic').liveShare:.0%} of the floor "
            "live load and the beams at full depth, as the analysis model counts it), "
            f"V = {v:.0f} kN each way (the "
            "analysis model's static method)."
        )
    if wind and values["windSpeed"]:
        rel = [base[k] / 1000 for k in range(1, n + 1)]
        args = (values["windSpeed"], settings.wind.exposure, values["windImportance"])
        forces["WX"] = fl.wind_level_forces(rel, ly_m, lx_m, *args)
        forces["WY"] = fl.wind_level_forces(rel, lx_m, ly_m, *args)
        out.baseShear["WX"] = round(sum(forces["WX"]), 1)
        out.baseShear["WY"] = round(sum(forces["WY"]), 1)
        out.notes.append(
            f"Wind: V = {sum(forces['WX']):.0f} kN along X, {sum(forces['WY']):.0f} kN along Y "
            "(service, the analysis model's wind forces)."
        )
    if not forces or frame_share <= 0:
        out.sides = {}
        return out

    # ── portal method: column shears, moments, axial forces per load ──
    # Per load case: moment [kN·m] at the column's governing end and axial force [kN] (with
    # the forces to +x / +y) of every column (i, j, k).
    moment: dict[str, dict[tuple[int, int, int], float]] = {}
    axial: dict[str, dict[tuple[int, int, int], float]] = {}
    beam_moment: dict[str, dict[tuple[tuple[int, int], tuple[int, int], int], float]] = {}
    for case, f in forces.items():
        along_x = case.endswith("X")
        lines = ny if along_x else nx
        count = nx if along_x else ny
        coords = xs if along_x else ys
        across = ys if along_x else xs
        centre = (across[0] + across[-1]) / 2
        spread = sum((c - centre) ** 2 for c in across)
        dim = across[-1] - across[0]
        shear = [0.0] * (n + 2)
        for k in range(n, 0, -1):
            shear[k] = shear[k + 1] + f[k - 1]
        m_case, n_case, b_case = {}, {}, {}
        for line in range(lines):
            torsion = 1.0
            if case.startswith("E") and spread > 0:
                torsion = 1 + ACCIDENTAL * dim * abs(across[line] - centre) * lines / spread
            shares = [
                (1 if c in (0, count - 1) else 2) / (2 * (count - 1)) if count > 1 else 1.0
                for c in range(count)
            ]
            v_col = {
                (c, k): shear[k] * frame_share / lines * torsion * shares[c]
                for c in range(count)
                for k in range(1, n + 1)
            }
            carried = [0.0] * count
            for k in range(n, 0, -1):
                # The joints at the top of storey k: column moments above and below.
                for c in range(count):
                    key = (c, line, k) if along_x else (line, c, k)
                    up = INFLECTION_BASE if k == 1 else INFLECTION
                    h = heights[k] / 1000
                    m_case[key] = v_col[(c, k)] * h * up
                    n_case[key] = 0.0
                left = 0.0
                beam_v = []
                for c in range(count - 1):
                    joint = (
                        v_col[(c, k)]
                        * heights[k]
                        / 1000
                        * (1 - (INFLECTION_BASE if k == 1 else INFLECTION))
                    )
                    if k < n:
                        joint += v_col[(c, k + 1)] * heights[k + 1] / 1000 * INFLECTION
                    mb = joint - left
                    span = (coords[c + 1] - coords[c]) / 1000
                    beam_v.append(2 * mb / span)
                    a = (c, line) if along_x else (line, c)
                    b = (c + 1, line) if along_x else (line, c + 1)
                    b_case[(a, b, k)] = mb
                    left = mb
                for c in range(count):
                    carried[c] += (beam_v[c - 1] if c > 0 else 0.0) - (
                        beam_v[c] if c < count - 1 else 0.0
                    )
                for c in range(count):
                    key = (c, line, k) if along_x else (line, c, k)
                    n_case[key] = carried[c]
        moment[case], axial[case], beam_moment[case] = m_case, n_case, b_case

    # ── combinations: (name, D, L, Lr, {case: factor}) ──
    combos: list[tuple[str, float, float, float, dict[str, float]]] = []
    for c in settings.combinations:
        if c.EX or c.EY or c.T:
            continue
        cases = {k: float(getattr(c, k)) for k in ("WX", "WY") if getattr(c, k) and k in forces}
        if cases or not (c.WX or c.WY):
            combos.append((c.name, c.D, c.L, c.Lr, cases))
    if "EX" in forces:
        options = sd.options_from_settings(settings)
        orthogonal = sd.orthogonal_required(sdc, getattr(options, "orthogonal", "auto"))
        for row in sd.seismic_combinations(settings, options, orthogonal, False):
            loads_ = row["loads"]
            env = row["envelope"]
            cases = {"EX": env.get("RX", 0.0), "EY": env.get("RY", 0.0)}
            combos.append((row["name"], loads_.get("D", 0.0), loads_.get("L", 0.0), 0.0, cases))

    # Gravity moments of the columns [kN·m] (dead, live) about x and y: half the difference of
    # the fixed-end moments w l² / 12 of the beams either side of the joint at their top.
    unbalanced: dict[tuple[int, int, bool], tuple[float, float]] = {}
    for i in range(nx):
        for j in range(ny):
            for along_x in (True, False):
                dead = live = 0.0
                for a, b in beams:
                    if (i, j) not in (a, b) or (a[1] == b[1]) != along_x:
                        continue
                    wd, wl = beam_loads.get((a, b), (0.0, 0.0))
                    span = math.dist((xs[a[0]], ys[a[1]]), (xs[b[0]], ys[b[1]])) / 1000
                    sign = 1.0 if (i, j) == a else -1.0
                    dead += sign * wd * span**2 / 12
                    live += sign * wl * span**2 / 12
                unbalanced[(i, j, along_x)] = (abs(dead) / 2, abs(live) / 2)

    def gravity(key: tuple[int, int, int], d: float, live: float, lr: float) -> float:
        return d * parts["dead"][key] + live * parts["live"][key] + lr * parts["roof"][key]

    # ── sway magnifiers per storey, direction and combination ──
    # Q = ΣPu Δo / (Vus lc) with the storey drift of the frames by Wilbur's storey stiffness:
    # Δo / V = h / (48 Ec) (4 h / ΣKc + (hb + h) / ΣKb,below + (h + ha) / ΣKb,above), the first
    # storey on its fixed base h1 / (48 Ec) (4 h1 / ΣKc + (h1 + h2) / (ΣKb + ΣKc / 12)), Kc =
    # 0.7 Ic / h of the storey's columns, Kb = 0.35 Ib / l of a floor's beams (a flat plate: its
    # strips at 0.25 Ig); Q does not depend on V, and δs = 1 / (1 - Q) (the design's default
    # form).
    kb = {d: floor_beam_stiffness(beams, xs, ys, slab_t, d) for d in (True, False)}
    sway: dict[tuple[int, str, str], float] = {}
    # The design fails a storey with δs > DELTA_S_MAX (second-order analysis required, Sec
    # 6.3.10.7.3): the columns' stiffness ΣKc each storey needs for Q <= 1 - 1/DELTA_S_MAX, as a
    # factor on the storey's present ΣKc (every column's side then times its fourth root).
    q_max = 1 - 1 / slender.DELTA_S_MAX
    stiffen: dict[int, float] = {}
    beams_too_flexible: set[tuple[int, str]] = set()
    for k in range(1, n + 1):
        kc = storey_column_stiffness(side_of, nx, ny, k, heights[k])
        h = heights[k]

        def flexibility(sum_kc: float, sum_kb: float, k=k) -> float:
            """Δo / V [mm/kN] of the storey (Wilbur)."""
            return wilbur_flexibility(heights, k, sum_kc, sum_kb, ec)[0]

        for name, d, live, lr, cases in combos:
            sum_pu = sum(gravity((i, j, k), d, live, lr) for i in range(nx) for j in range(ny))
            for case in cases:
                along_x = case.endswith("X")

                def q_of(
                    factor: float, sum_pu=sum_pu, along_x=along_x, kc=kc, h=h, flex_of=flexibility
                ) -> float:
                    # At frame_share of the shear, the columns' ΣKc times ``factor``.
                    flex = flex_of(kc * factor, kb[along_x]) * frame_share
                    return slender.stability_index(sum_pu, flex, 1.0, h)

                q = q_of(1.0)
                sway[(k, name, case)] = slender.delta_s_q(q)
                if q > q_max and sum_pu > 0:
                    # The least factor on ΣKc with Q <= q_max (Q falls as ΣKc grows).
                    if q_of(1e6) > q_max:
                        beams_too_flexible.add((k, case[-1]))
                        continue
                    lo, hi = 1.0, 2.0
                    while q_of(hi) > q_max:
                        lo, hi = hi, hi * 2
                    for _ in range(40):
                        mid = (lo + hi) / 2
                        lo, hi = (mid, hi) if q_of(mid) > q_max else (lo, mid)
                    stiffen[k] = max(stiffen.get(k, 1.0), hi)
    worst_sway = {}
    for (_k, _name, case), value in sway.items():
        axis = case[-1]
        worst_sway[axis] = max(worst_sway.get(axis, 1.0), value)
    out.swayFactor = {k: round(v, 3) for k, v in worst_sway.items()}

    def magnifier(k: int, name: str, case: str) -> float:
        """δs on the storey's lateral moments: at most DELTA_S_MAX where the columns are made
        stiff enough for it (below), else (beams too flexible) the storey's own, at most 2.5."""
        cap = 2.5 if (k, case[-1]) in beams_too_flexible else slender.DELTA_S_MAX
        return min(sway[(k, name, case)], cap)

    # ── the demand points of every column, at a trial side ──
    def points(
        key: tuple[int, int, int], side: float
    ) -> list[tuple[float, float, float, str, str]]:
        found = []
        for name, d, live, lr, cases in combos:
            pg = gravity(key, d, live, lr)
            # Moments [kN·m] about the column's x axis (bending in Y: forces along Y) and y.
            mx = sum(
                f * moment[c][key] * magnifier(key[2], name, c)
                for c, f in cases.items()
                if c.endswith("Y")
            )
            my = sum(
                f * moment[c][key] * magnifier(key[2], name, c)
                for c, f in cases.items()
                if c.endswith("X")
            )
            # Bending in Y (about x) from the beams along Y; in X from those along X.
            gy, gx = unbalanced[(key[0], key[1], False)], unbalanced[(key[0], key[1], True)]
            live_f = live if key[2] < len(heights) - 1 else lr
            mx = abs(mx) + d * gy[0] + live_f * gy[1]
            my = abs(my) + d * gx[0] + live_f * gx[1]
            nx_ = sum(f * axial[c][key] for c, f in cases.items() if c.endswith("X"))
            ny_ = sum(f * axial[c][key] for c, f in cases.items() if c.endswith("Y"))
            for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                pu = (pg + sx * nx_ + sy * ny_) * 1e3  # N
                m_min = slender.minimum_moment(pu, side)
                found.append((pu, max(abs(mx) * 1e6, m_min), abs(my) * 1e6, name, f"{key}"))
                found.append((pu, abs(mx) * 1e6, max(abs(my) * 1e6, m_min), name, f"{key}"))
        return found

    def search(side: float) -> ColumnSearch:
        key = (side, fc, fy, es, rho_target, concrete)
        if key not in _SEARCHES:
            if len(_SEARCHES) > 64:
                _SEARCHES.clear()
            obj = Column.model_validate(
                _template(
                    "Column",
                    id=f"C{side:g}x{side:g}",
                    material=concrete,
                    profile={"shape": "rectangle", "xDim": side, "yDim": side},
                )
            )
            _SEARCHES[key] = ColumnSearch(obj, fc, fy, es, None, Options(rho_max=rho_target))
        return _SEARCHES[key]

    def utilisation(side: float, demand: list) -> float:
        found = search(side)
        if not found.layouts:
            return math.inf
        return found.utilisation(len(found.layouts) - 1, _prune(demand))

    least_sections: dict[float, Any] = {}

    def least_section(side: float) -> Any:
        """The section of the side's least layout, one object per side (the strengths of
        :mod:`saengine.design.ductile_joints` are memoised by section object)."""
        if side not in least_sections:
            least_sections[side] = search(side).section(0)
        return least_sections[side]

    # ── beams' nominal strengths at the joints (strong column / weak beam) ──
    def beam_mn(edge: tuple[tuple[int, int], tuple[int, int]], k: int) -> tuple[float, float]:
        """(Mn-, Mn+) [kN·m] of a beam at storey level k from the bars its moments need."""
        bw, bh = beams[edge]
        wd, wl = beam_loads.get(edge, (0.0, 0.0))
        span = math.dist((xs[edge[0][0]], ys[edge[0][1]]), (xs[edge[1][0]], ys[edge[1][1]]))
        span_m = span / 1000
        lateral = 0.0
        for name, _d, _l, _lr, cases in combos:
            lateral = max(
                lateral, sum(abs(f * beam_moment[c].get((*edge, k), 0.0)) for c, f in cases.items())
            )
        hog = max(
            (1.2 * wd + 1.6 * wl) * span_m**2 / 12,
            (1.2 * wd + 1.0 * wl) * span_m**2 / 12 + lateral,
        )
        sag = max(lateral - 0.9 * wd * span_m**2 / 12, 0.0)
        d = bh - 60.0
        minimum = beam_min_area(bw, d, fc, fy)

        def mn(mu: float) -> float:
            area = with_minimum(beam_flexure_need(mu * 1e6, bw, d, 60.0, fc, fy, es).area, minimum)
            area = max(area, minimum)
            a = area * fy / (0.85 * fc * bw)
            return area * fy * (d - a / 2) / 1e6 * BEAM_BARS_ALLOWANCE

        mn_hog = mn(hog)
        return mn_hog, max(mn(sag), mn_hog / 2)

    joint_beams: dict[tuple[int, int, bool], list[tuple[tuple[int, int], tuple[int, int]]]] = {}
    for edge in beams:
        a, b = edge
        along_x = a[1] == b[1]
        for end in (a, b):
            joint_beams.setdefault((*end, along_x), []).append(edge)
    mnb_cache: dict[tuple[int, int, int, bool], float] = {}

    def sum_mnb(i: int, j: int, k: int, along_x: bool) -> float:
        key = (i, j, k, along_x)
        if key not in mnb_cache:
            framing = joint_beams.get((i, j, along_x), [])
            strengths = [beam_mn(e, k) for e in framing]
            if len(strengths) == 2:
                (h1, s1), (h2, s2) = strengths
                total = max(h1 + s2, s1 + h2)
            else:
                total = max((h for h, _ in strengths), default=0.0)
            mnb_cache[key] = total
        return mnb_cache[key]

    # ── size every (group, position) from the top group down ──
    kinds = ("interior", "edge", "corner")
    mnc_of: dict[tuple[int, str], tuple[float, float]] = {}  # (Mnc about x, y) [kN·m]
    for g in range(len(groups) - 1, -1, -1):
        for kind in kinds:
            members = [
                (i, j, k)
                for i in range(nx)
                for j in range(ny)
                for k in groups[g]
                if position(i, j) == kind
            ]
            if not members:
                continue
            side = max(max(side_of[m] for m in members), col_min)
            why = "gravity"
            # The storey stiffness for δs <= DELTA_S_MAX (every column of the storey scaled).
            stiff = max(
                (side_of[m] * stiffen[m[2]] ** 0.25 for m in members if m[2] in stiffen),
                default=0.0,
            )
            if stiff > side:
                side = min(ceil_to(stiff, 50), MAX_SIDE)
                why = f"sway: δs ≤ {slender.DELTA_S_MAX:g} (Sec 6.3.10.7.3)"
            tried: dict[float, float] = {}

            def fits(trial: float, members: list = members, tried: dict = tried) -> float:
                if trial not in tried:
                    tried[trial] = utilisation(
                        trial, [p for m in members for p in points(m, trial)]
                    )
                return tried[trial]

            # The P-M size: the capacity at a fixed ρ grows about as the side cubed, so a
            # failing side is first scaled by the cube root of its utilisation, then stepped.
            u = fits(side)
            if u > 1.0:
                why = f"P-M with ρ ≤ {rho_target:g}"
                guess = min(ceil_to(side * u ** (1 / 3), 50), MAX_SIDE)
                while guess > side + 50 and fits(guess - 50) <= 1.0:
                    guess -= 50
                side = guess
                while fits(side) > 1.0 and side < MAX_SIDE:
                    side += 50.0
                if fits(side) > 1.0:
                    out.notes.append(
                        f"Columns {kind} L{groups[g][0]}-L{groups[g][-1]}: no side up to "
                        f"{MAX_SIDE:g} mm carries the demand with ρ ≤ {rho_target:g}; check "
                        "the system."
                    )
            # Strong column / weak beam with the least layout (ρ about 1 %, on the safe side:
            # the design may put more bars in).
            while special and side < MAX_SIDE:
                demand = [p for m in members for p in points(m, side)]
                pus = [p[0] for p in demand]
                if max(pus) <= dj.AXIAL_LIMIT * side * side * fc:
                    break
                section = least_section(side)
                # The range widened to whole 50 kN (the lowest Mn is at an end of it: on the
                # safe side), so the strengths are shared between the column types.
                pmin = math.floor(min(pus) / AXIAL_STEP) * AXIAL_STEP
                pmax = math.ceil(max(pus) / AXIAL_STEP) * AXIAL_STEP
                about_x = dj.lowest_column_moment(section, pmin, pmax, math.pi / 2)[0] / 1e6
                # A square section with a doubly symmetric bar layout: the same about y.
                about_y = (
                    about_x
                    if section.symmetric
                    else dj.lowest_column_moment(section, pmin, pmax, 0.0)[0] / 1e6
                )
                mnc = (about_x, about_y)
                weak = None
                for i, j, k in members:
                    if k >= n:
                        continue
                    above = (
                        mnc if (k + 1) in groups[g] else mnc_of.get((group_of[k + 1], kind), mnc)
                    )
                    for along_x, axis in ((True, 1), (False, 0)):
                        need = dj.STRONG_COLUMN_RATIO * sum_mnb(i, j, k, along_x)
                        if mnc[axis] + above[axis] < need - 1e-6:
                            weak = (i, j, k)
                            break
                    if weak:
                        break
                if weak is None:
                    mnc_of[(g, kind)] = mnc
                    break
                why = f"strong column / weak beam at {letters(weak[0])}{weak[1] + 1} L{weak[2]}"
                side += 50.0
            out.sides[(g, kind)] = side
            out.governing[(g, kind)] = why
    if beams_too_flexible:
        where = ", ".join(f"L{k} {axis}" for k, axis in sorted(beams_too_flexible))
        out.notes.append(
            f"Storeys {where}: δs = 1/(1 - Q) stays above {slender.DELTA_S_MAX:g} however stiff "
            "the columns are (the beams of the floor above are too flexible): the design will "
            "ask for a second-order analysis (Sec 6.3.10.7.3); deepen the beams or add walls."
        )
    return out


@code_context.in_project_pack()
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
    # The chosen concrete and bars, recorded: the types are generated without bars, so this is
    # what the design proposes them with (and the BOQ bills), not the library's first rebar.
    materials.defaults = MaterialDefaults(concrete=s.concrete, rebar=s.rebar)
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
    if s.siteClass is not None and s.siteClassSource == "assumed":
        # The settings have no "assumed" source (site.siteClassSource is "soilReport" or
        # "entered"): "soilReport" keeps the assumed class only until 1 Soil Report gives one.
        site.update(siteClass=s.siteClass, siteClassSource="soilReport")
        notes.append(
            f"Site class {s.siteClass} ASSUMED (no soil report yet): BNBC 2020 Part 6 Table "
            "6.2.13 (p. 609) classes the site by the average properties of the top 30 m "
            "(shear wave velocity, SPT N or undrained shear strength). It sets the "
            "spectrum (Table 6.2.16, p. 616), the Seismic Design Category (Table 6.2.18, p. "
            "617) and so the system and the sizes below. 02 Project Settings take the class "
            "from 1 Soil Report once its boreholes give one; until then the settings and the "
            "report show this assumed class as entered: confirm it with a soil investigation."
        )
    elif s.siteClass is not None:
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
    if s.system == "flatSlab":
        # A flat slab has no beams to take its loads: it must be in the analysis as shells.
        patch["analysis"] = {"slabs": "shells"}
    settings_json = _deep_merge(base_json, patch)
    final = ProjectSettings.model_validate(settings_json)
    special = sdc == "D" or system_id in ("rcSmf", "rcDualSpecial")
    floor_load = next(a for a in final.areaLoads if a.id == final.floorLoad)
    roof_load = next(a for a in final.areaLoads if a.id == final.roofLoad)
    q_floor_sd = floor_load.finish + floor_load.partitions
    q_roof_sd = roof_load.finish + roof_load.partitions
    notes.append(
        f"Seismic Design Category {sdc or '-'} (zone {zone or '-'}, site class "
        f"{final.site.siteClass}"
        f"{' assumed' if s.siteClass is not None and s.siteClassSource == 'assumed' else ''}"
        f", occupancy category {final.occupancy.category}); system "
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
                f"span/{s.beamSpanDepth:g} (rule of thumb for the stiffness of frame beams under "
                "lateral load), "
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

    def service_loads(
        sides: dict[tuple[int, int, int], float],
    ) -> tuple[dict[tuple[int, int, int], float], dict[str, Any]]:
        """Service loads at each column, from the roof down [kN], and their parts: ``dead``
        (with the superimposed dead), floor ``live`` and ``roof`` live, and ``levels`` the
        dead load added at each level (the seismic weight)."""
        out: dict[tuple[int, int, int], float] = {}
        dead: dict[tuple[int, int, int], float] = {}
        live: dict[tuple[int, int, int], float] = {}
        roof: dict[tuple[int, int, int], float] = {}
        level_dead = [0.0] * (n + 1)
        level_live = [0.0] * (n + 1)
        level_overlap = [0.0] * (n + 1)
        for i in range(nx):
            for j in range(ny):
                p = pd = pl = pr = 0.0
                for k in range(n, 0, -1):
                    before = pd
                    sd = q_roof_sd if k == n else q_floor_sd
                    q_live = roof_load.live if k == n else floor_load.live
                    for a, b in adjacent_panels(i, j):
                        area = (xs[a + 1] - xs[a]) * (ys[b + 1] - ys[b]) / 4 / 1e6
                        t = slab_of[(a, b)][0]
                        p += area * (t / 1000 * gamma + sd + q_live)
                        pd += area * (t / 1000 * gamma + sd)
                        if k == n:
                            pr += area * q_live
                        else:
                            pl += area * q_live
                    if not flat:
                        t_least = min(v[0] for v in slab_of.values())
                        for (a, b), (bw, bh) in beam_size.items():
                            if (i, j) in (a, b) and (a, b) not in core_lines:
                                span = math.dist((xs[a[0]], ys[a[1]]), (xs[b[0]], ys[b[1]]))
                                w = span / 2 / 1000 * bw / 1000 * (bh - t_least) / 1000 * gamma
                                p += w
                                pd += w
                                level_overlap[k] += w * t_least / (bh - t_least)
                    side = sides[(i, j, k)] / 1000
                    w = side * side * heights[k] / 1000 * gamma
                    p += w
                    pd += w
                    out[(i, j, k)] = p
                    dead[(i, j, k)], live[(i, j, k)], roof[(i, j, k)] = pd, pl, pr
                    level_dead[k] += pd - before
                    if k < n:
                        level_live[k] += (
                            sum(
                                (xs[a + 1] - xs[a]) * (ys[b + 1] - ys[b]) / 4 / 1e6
                                for a, b in adjacent_panels(i, j)
                            )
                            * floor_load.live
                        )
        # The seismic weight of each level as the analysis model counts it (fem.derive): the
        # dead load, the code's share of the floor live load (no roof live) and the beams at
        # their full depth (the analysis model's frame members overlap the slab).
        seismic = [
            d + code_context.table("seismic").liveShare * lv + o
            for d, lv, o in zip(level_dead, level_live, level_overlap, strict=True)
        ]
        return out, {"dead": dead, "live": live, "roof": roof, "levels": level_dead,
                     "seismicLevels": seismic}  # fmt: skip

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
        loads, load_parts = service_loads(col_side)
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

    lateral: LateralSizing | None = None
    gravity_side = dict(group_side)
    governing: dict[tuple[int, str], str] = {}
    seismic_on = sdc in ("C", "D")
    lateral_on = s.lateralSizing == "auto" and (seismic_on or sdc == "B")
    ec = concrete.mechanical.E or 4700 * math.sqrt(fc)

    # ── stiffness: storey drifts and period (preliminary), before the P-M sizing ──
    # The frames' estimated drifts and period (stiffness_estimate) against the code's limits;
    # where one is exceeded the members that dominate the storey's flexibility are enlarged:
    # the beams along that direction 25 mm deeper (to span/STIFF_BEAM_SPAN_DEPTH), else the
    # columns of the storey groups concerned 50 mm larger; the slabs are then re-sized for the
    # new beams and the loads recomputed.
    first_estimate: StiffnessEstimate | None = None
    estimate: StiffnessEstimate | None = None
    stiff_beams: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    gravity_beams = dict(beam_size)
    stiff_columns: set[tuple[int, str]] = set()
    stiffness_unmet = ""
    column_step: tuple[Any, ...] | None = None
    column_step_keys: set[tuple[int, str]] = set()
    if lateral_on and not walls_on:
        weights_of = load_parts.get("seismicLevels", load_parts["levels"])
        for _ in range(60):
            estimate = stiffness_estimate(
                final,
                sdc,
                xs=xs,
                ys=ys,
                heights=heights,
                side_of=col_side,
                beams=beam_size,
                slab_t=min(v[0] for v in slab_of.values()),
                ec=ec,
                weights=weights_of[1:],
            )
            first_estimate = first_estimate or estimate
            need: dict[tuple[str, int], float] = {}
            period_need = {
                axis: (t / (PERIOD_TARGET * estimate.periodLimit)) ** 2
                for axis, t in estimate.period.items()
            }
            for axis in ("X", "Y"):
                for k in range(1, n + 1):
                    need[(axis, k)] = max(
                        estimate.seismicRatio[axis][k - 1],
                        estimate.windRatio[axis],
                        period_need[axis],
                    )
            (axis, k_worst), worst = max(need.items(), key=lambda item: item[1])
            if column_step is not None and worst >= column_step[-1] - 1e-6:
                # Larger columns made the frame heavier more than stiffer (the beams govern
                # and are at their limits): back to the sizes before them.
                group_side, col_side, loads, load_parts, estimate, _ = column_step
                stiff_columns = set(column_step_keys)
                stiffness_unmet = (
                    f"the beams are at their limits (span/{STIFF_BEAM_SPAN_DEPTH:g} deep, "
                    f"width {STIFF_BEAM_WIDTH_SHARE:g} h up to {STIFF_BEAM_WIDTH:g} mm) and "
                    "larger columns no longer help"
                )
                break
            column_step = None
            if worst <= 1.0 + 1e-9:
                break
            changed = False
            failing: set[int] = set()
            for axis in ("X", "Y"):
                along_x = axis == "X"
                storeys = {k for (a, k), r in need.items() if a == axis and r > 1.0 + 1e-9}
                if not storeys:
                    continue
                failing |= storeys
                k_worst = max(storeys, key=lambda k, axis=axis: need[(axis, k)])
                if max(period_need[axis], estimate.windRatio[axis]) >= need[(axis, k_worst)] - 1e-9:
                    share = sum(estimate.columnShare[axis]) / n
                else:
                    share = estimate.columnShare[axis][k_worst - 1]
                if flat or share >= 0.5:
                    continue
                # The beams dominate: those along the direction 25 mm deeper (to span/10),
                # then 25 mm wider (to 0.6 h, 400 mm).
                along = [
                    e for e in beam_size if (e[0][1] == e[1][1]) == along_x and e not in core_lines
                ]
                stepped = False
                for edge in along:
                    a, b = edge
                    bw, bh = beam_size[edge]
                    span = math.dist((xs[a[0]], ys[a[1]]), (xs[b[0]], ys[b[1]]))
                    if bh + 25 <= span / STIFF_BEAM_SPAN_DEPTH + 1e-6:
                        h = bh + 25
                        beam_size[edge] = (max(bw, ceil_to(max(250.0, 0.3 * h), 25)), h)
                        stiff_beams.add(edge)
                        stepped = True
                if not stepped:
                    for edge in along:
                        bw, bh = beam_size[edge]
                        if bw + 25 <= min(STIFF_BEAM_WIDTH_SHARE * bh, STIFF_BEAM_WIDTH) + 1e-6:
                            beam_size[edge] = (bw + 25, bh)
                            stiff_beams.add(edge)
                            stepped = True
                changed = changed or stepped
            if changed:
                for i in range(nx - 1):
                    for j in range(ny - 1):
                        slab_of[(i, j)] = beam_slab(i, j)
            if not changed:
                column_step = (dict(group_side), dict(col_side), loads, load_parts, estimate, worst)
                column_step_keys = set(stiff_columns)
                for g in sorted({group_of[k] for k in failing}):
                    for kind in POSITION_FACTOR:
                        key = (g, kind)
                        if key in group_side and group_side[key] < MAX_SIDE:
                            group_side[key] += 50.0
                            stiff_columns.add(key)
                            changed = True
                for kind in POSITION_FACTOR:
                    for g in range(len(groups) - 2, -1, -1):
                        if (g, kind) in group_side and (g + 1, kind) in group_side:
                            group_side[(g, kind)] = max(
                                group_side[(g, kind)], group_side[(g + 1, kind)]
                            )
                col_side = {
                    (i, j, k): group_side[(group_of[k], position(i, j))]
                    for i in range(nx)
                    for j in range(ny)
                    for k in range(1, n + 1)
                }
            if not changed:
                stiffness_unmet = (
                    f"no member could be enlarged further (beams to span/"
                    f"{STIFF_BEAM_SPAN_DEPTH:g}, columns to {MAX_SIDE:g} mm)"
                )
                break
            loads, load_parts = service_loads(col_side)
            weights_of = load_parts.get("seismicLevels", load_parts["levels"])
        else:
            stiffness_unmet = "the iteration limit was reached"
        for key in stiff_columns:
            if group_side[key] > gravity_side.get(key, 0.0):
                governing[key] = "stiffness: drift / period"

    # ── columns for wind and earthquake (P–M), where the category asks for it ──
    frame_share = 1.0
    if walls_on:
        # Dual systems: the frames take at least a quarter of the storey shear; otherwise the
        # walls take it all and the frames are gravity frames.
        frame_share = 0.25 if system_id == "rcDualSpecial" else 0.0
    if lateral_on and frame_share > 0:
        t_least = min(v[0] for v in slab_of.values())
        beam_loads: dict[tuple[tuple[int, int], tuple[int, int]], tuple[float, float]] = {}
        for edge, (bw, bh) in beam_size.items():
            if edge in core_lines:
                continue
            strip = edge_strip(*edge)[0] / 1000
            stem = bw / 1000 * (bh - t_least) / 1000 * gamma
            beam_loads[edge] = (
                strip * (t_least / 1000 * gamma + q_floor_sd) + stem,
                strip * floor_load.live,
            )
        frame_beams = {e: v for e, v in beam_size.items() if e not in core_lines}
        es = rebar.mechanical.E or 200_000.0
        for _ in range(4):
            lateral = lateral_column_sizes(
                final,
                sdc,
                xs=xs,
                ys=ys,
                heights=heights,
                groups=groups,
                side_of=col_side,
                position=position,
                parts=load_parts,
                beams=frame_beams,
                beam_loads=beam_loads,
                slab_t=t_least,
                frame_share=frame_share,
                special=special,
                seismic=seismic_on,
                wind=True,
                fc=fc,
                fy=fy,
                es=es,
                ec=ec,
                concrete=s.concrete,
                col_min=col_min,
                rho_target=s.columnRho,
            )
            if not lateral.sides:
                break
            governing.update({k: v for k, v in lateral.governing.items() if v != "gravity"})
            new_group = {key: max(side, lateral.sides.get(key, 0.0)) for key, side in
                         group_side.items()}  # fmt: skip
            for kind in POSITION_FACTOR:
                for g in range(len(groups) - 2, -1, -1):
                    if (g, kind) in new_group and (g + 1, kind) in new_group:
                        new_group[(g, kind)] = max(new_group[(g, kind)], new_group[(g + 1, kind)])
            new_sides = {
                (i, j, k): new_group[(group_of[k], position(i, j))]
                for i in range(nx)
                for j in range(ny)
                for k in range(1, n + 1)
            }
            group_side = new_group
            if new_sides == col_side:
                break
            col_side = new_sides
            loads, load_parts = service_loads(col_side)

    # The estimate at the final sizes (the P-M sizing may have enlarged columns since).
    stiffness_note = ""
    if first_estimate is not None:
        estimate = stiffness_estimate(
            final,
            sdc,
            xs=xs,
            ys=ys,
            heights=heights,
            side_of=col_side,
            beams=beam_size,
            slab_t=min(v[0] for v in slab_of.values()),
            ec=ec,
            weights=load_parts.get("seismicLevels", load_parts["levels"])[1:],
        )

        def state(e: StiffnessEstimate) -> str:
            seismic = (
                ", design drift / limit "
                + ", ".join(f"{a} {max(e.seismicRatio[a]):.2f}" for a in ("X", "Y"))
                if e.driftLimit
                else ""
            )
            return (
                "T " + ", ".join(f"{a} {e.period[a]:.2f} s" for a in ("X", "Y")) + seismic
                + ", roof wind deflection / (H/500) "
                + ", ".join(f"{a} {e.windRatio[a]:.2f}" for a in ("X", "Y"))
            )  # fmt: skip

        changes = []
        deepened = sorted(
            {
                "B{:g}x{:g} -> B{:g}x{:g}".format(*gravity_beams[e], *beam_size[e])
                for e in stiff_beams
                if beam_size[e] != gravity_beams[e]
            }
        )
        if deepened:
            changes.append("beams " + ", ".join(deepened))
        if stiff_columns:
            changes.append(
                "columns "
                + ", ".join(
                    f"{story_ids[groups[g][0]]}-{story_ids[groups[g][-1]]} {kind}"
                    for g, kind in sorted(stiff_columns)
                )
                + " enlarged in 50 mm steps"
            )
        rigid = final.analysis.rigidZoneFactor if final.analysis.endOffsets else 0.0
        limit = (
            f"Δa/ρ = {first_estimate.driftLimit:.3f} hsx (Table 6.2.21, p. 648, occupancy "
            f"category {final.occupancy.category}; Sec 2.5.14.1, p. 647), Cd = "
            f"{first_estimate.cd:g}"
            if first_estimate.driftLimit
            else "not checked (no seismic zone coefficient)"
        )
        met = max(
            max(max(estimate.seismicRatio[a]) for a in ("X", "Y")),
            max(estimate.windRatio.values()),
            max((t / (PERIOD_TARGET * estimate.periodLimit)) ** 2 for t in
                estimate.period.values()),
        ) <= 1.0 + 1e-6  # fmt: skip
        stiffness_note = (
            "Stiffness (PRELIMINARY drift and period check, before the P-M sizing of the "
            "columns): the frames as a shear building of Wilbur's storey stiffnesses (columns "
            f"{CRACKED_COLUMN:g} Ig, beams {CRACKED_BEAM:g} Ig without the slab flange"
            + (f", flat plate {CRACKED_PLATE:g} Ig" if flat else "")
            + ", BNBC 2020 Part 6 Sec 6.3.10.4.1, p. 912, for the factored lateral loads as "
            "Sec 6.1.10.2, p. 893; "
            + (
                f"the analysis model's rigid end zones, factor {rigid:g}"
                if rigid
                else "no rigid end zones"
            )
            + "), every frame line of a direction alike, the seismic weight as the analysis "
            "model counts it. Checked: (1) the earthquake design drift Cd δe / I of every "
            f"storey (Sec 2.5.7.7, p. 631) against {limit}, δe under the equivalent static "
            f"forces at Ta = {first_estimate.ta:.2f} s (the analysis' default period); (2) the "
            "roof deflection under the service wind (1.0 W, the analysis model's wind forces; "
            f"members at {SERVICE_STIFFNESS:g} x those stiffnesses, Sec 6.1.10.1, p. 893) "
            "against H/500 (Sec 1.5.6.1; its page is not in the code pack: check it); (3) the "
            "period by Rayleigh's quotient against "
            f"{PERIOD_TARGET:g} Cu Ta = {PERIOD_TARGET * first_estimate.periodLimit:.2f} s "
            f"(Cu Ta = {first_estimate.periodLimit:.2f} s, Sec 2.5.7.2 (a), p. 627; Ta = Ct "
            "hn^m, eq. 6.2.38, Table 6.2.20, p. 628). Cu Ta caps the period the static forces "
            "may use and is no limit on the structure; an estimate above "
            f"{PERIOD_TARGET:g} Cu Ta is taken as a frame too flexible (SAEngine practice). "
            f"Where one failed: the beams along that direction 25 mm deeper up to "
            f"span/{STIFF_BEAM_SPAN_DEPTH:g}, then 25 mm wider up to "
            f"{STIFF_BEAM_WIDTH_SHARE:g} h and {STIFF_BEAM_WIDTH:g} mm, while they govern the "
            "storey's flexibility; else the columns of the storey groups concerned 50 mm "
            "larger; the slabs re-sized for the new beams. Before: "
            + state(first_estimate)
            + ". Final sizes: "
            + state(estimate)
            + (". Changed: " + "; ".join(changes) if changes else ". No member changed")
            + ". "
            + (
                "All three met."
                if met
                else "NOT all met ("
                + (stiffness_unmet or "see the ratios above")
                + "): consider deeper or wider beams, more frame lines, walls, or columns "
                "turned with their long side along the flexible direction."
            )
            + " Assumed (not checked here): rigid floors, no accidental torsion, no P-delta, "
            "no infill walls, the slabs' flanges and stiffness left out; the analysis "
            "(modal periods, drifts of Sec 2.5.14.1) is the check."
        )
    elif lateral_on and walls_on:
        stiffness_note = (
            "Stiffness: the drift and period are not estimated here (the core walls take the "
            "storey shear); the analysis checks them (Sec 2.5.14.1, p. 647)."
        )

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
    if stiffness_note:
        notes.append(stiffness_note)
    if not flat:
        governing_panels: dict[tuple[float, str], tuple[int, int]] = {}
        for (i, j), (t, system, _how) in sorted(slab_of.items()):
            governing_panels.setdefault((t, system), (i, j))
        panels = "; ".join(
            f"{slab_type(t, system)} e.g. panel {name(i, j)}: {slab_of[(i, j)][2]}"
            for (t, system), (i, j) in sorted(governing_panels.items())
        )
        notes.append(
            "Slabs with beams: Sec 6.2.5.3.3 (p. 903) with alpha_f of the rectangular beam "
            "section (no slab flange, on the low side, as Design mode's slab check takes it) "
            "over the slab strip it carries; one-way panels (beta > 2) by Table 6.6.1 (p. 900); "
            f"at least {s.minSlab:g} mm (SAEngine practice), rounded up to 25 mm. The thickness "
            "follows the beams' stiffness: with alpha_fm > 2 (beams of about span/12 and "
            "deeper) eq. 6.6.6 gives ln (0.8 + fy/1400) / (36 + 9 beta), about ln/43 for a "
            "6 x 5 m panel; shallower beams (alpha_fm <= 2) fall to eq. 6.6.5 and towards the "
            "flat-plate ln/30 to ln/33 of Table 6.6.3 (p. 902), +10 % at an edge beam with "
            f"alpha_f < 0.8. {panels}."
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
    if lateral is not None and lateral.sides:
        enlarged = sorted(
            f"{story_ids[groups[g][0]]}-{story_ids[groups[g][-1]]} {kind} "
            f"{gravity_side[(g, kind)]:g} -> {group_side[(g, kind)]:g} mm"
            + (f" ({governing[(g, kind)]})" if (g, kind) in governing else "")
            for (g, kind) in group_side
            if group_side[(g, kind)] > gravity_side.get((g, kind), 0.0)
        )
        loads_text = "wind and earthquake" if seismic_on else "wind"
        notes.append(
            f"Columns for {loads_text} (Seismic Design Category {sdc}): PRELIMINARY P-M sizing "
            "by the portal method. Storey forces of the analysis model's own static methods "
            "(fem.loads: the equivalent static earthquake force with W the dead and "
            "superimposed dead load of the levels plus "
            f"{code_context.table('seismic').liveShare:.0%} of the floor live load and the "
            "beams at full depth, "
            "as the analysis model counts it, and the wind forces); the "
            "storey shear "
            f"{'shared' if frame_share == 1 else f'x {frame_share:g} (dual system) shared'} "
            "equally among the frame lines of each direction (rigid floors), interior columns "
            "of a line taking twice the end columns' shear, inflection points at mid-height "
            "(2/3 of the lowest storey above the fixed base) and mid-span of the beams, the "
            "edge frames' share raised for a 5 % accidental eccentricity (earthquake); gravity "
            "moments half the unbalanced w l²/12 of the beams at each joint; the settings' "
            "wind combinations and the design's earthquake combinations (1.2D + Ev, 0.9D - Ev"
            + (", 100 % + 30 %" if seismic_on and sdc == "D" else "")
            + "); lateral moments times the storey's sway magnifier δs = 1/(1 - Q), Q = ΣPu "
            "Δo/(Vus lc) with Δo of the frames by Wilbur's storey stiffness (columns 0.7 Ig, "
            "beams 0.35 Ig) (largest "
            f"{', '.join(f'{k} {v:.2f}' for k, v in lateral.swayFactor.items())}"
            "), the columns of a storey made stiff enough for δs ≤ 1.5 (Sec 6.3.10.7.3: above "
            "it the design asks for a second-order analysis), M2,min on each axis; every member of a column type carried on the design's "
            f"interaction surface (biaxial) with ρ ≤ {s.columnRho:g}"
            + (
                ", and strong column / weak beam ΣMnc ≥ 1.2 ΣMnb (Sec 8.3.5.2) with the beams' "
                "Mn from the bars their portal and gravity moments need (+15 % for rounding) "
                "and the column type's least layout"
                if special
                else ""
            )
            + ". Not included: P-delta beyond δs, joint shear (Sec 8.3.7), the beams' "
            "capacity shear, irregularities, the response spectrum's own distribution. "
            + (
                "Enlarged: " + "; ".join(enlarged) + "."
                if enlarged
                else "No column needed more than its gravity size."
            )
        )
        notes += [f"Lateral sizing: {note}" for note in lateral.notes]
    elif sdc in ("C", "D"):
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
        "lateralSizing": (
            {
                "baseShear": lateral.baseShear,
                "swayFactor": lateral.swayFactor,
                "gravityColumnTypes": {
                    f"{story_ids[groups[g][0]]}-{story_ids[groups[g][-1]]} {kind}": (
                        f"C{side:g}x{side:g}"
                    )
                    for (g, kind), side in sorted(gravity_side.items())
                },
            }
            if lateral is not None and lateral.sides
            else None
        ),
        # The preliminary drift and period estimate (stiffness_estimate) before the stiffness
        # pass and at the final sizes; None where it was not made.
        "stiffness": (
            {
                "ta": round(estimate.ta, 3),
                "periodLimit": round(estimate.periodLimit, 3),
                "periodTarget": round(PERIOD_TARGET * estimate.periodLimit, 3),
                "before": {
                    "period": {a: round(t, 3) for a, t in first_estimate.period.items()},
                    "seismicDriftRatio": {
                        a: round(max(r), 3) for a, r in first_estimate.seismicRatio.items()
                    },
                    "windDriftRatio": {a: round(r, 3) for a, r in first_estimate.windRatio.items()},
                },
                "period": {a: round(t, 3) for a, t in estimate.period.items()},
                "seismicDriftRatio": {
                    a: round(max(r), 3) for a, r in estimate.seismicRatio.items()
                },
                "windDriftRatio": {a: round(r, 3) for a, r in estimate.windRatio.items()},
                "met": not stiffness_unmet,
            }
            if first_estimate is not None and estimate is not None
            else None
        ),
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

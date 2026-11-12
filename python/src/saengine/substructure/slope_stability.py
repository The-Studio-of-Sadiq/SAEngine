"""Slope stability by limit equilibrium of slices on a 2D section (alpha 9 L8).

The methods and every value are the code pack's ``slopeStability`` table
(:class:`saengine.codes.slope_tables.SlopeStabilityTable`); a pack without it does not check
slopes. The default pack's BNBC 2020 lists landslides as a geo-hazard (Part 6 Sec 3.21) and gives
no method or factor of safety for slopes: every method and value there is SAEngine practice, and
the report says so. The 2D finite element analysis of the same section is
:mod:`saengine.substructure.geotech_fe`.

**The section** (:class:`Section`) is a 2D cut, x along the section and z the level [m]:

- *drawn*: the ground surface, the top line of each stratum below the first (the first's top is
  the ground) and the soils (``Slope.surface``, ``strata``, ``soils``);
- *cut from the site's strata*: the stratigraphy of 01 Soil Report (Part 1, linked, never
  copied: :func:`saengine.soil.stratigraphy.section`) along the line from ``start`` to ``end``
  in plan; each unit's soil is the thickness-weighted mean of the boreholes' layers in that unit
  (γ, γsat, c', φ', cu, E as :mod:`saengine.soil.profile` resolves them), a soil of the slope
  with the unit's id overriding single values; the ground is the boreholes' unless a designed
  surface is drawn (the part of a fill above the natural ground is the soil ``FILL`` when the
  slope has one, else the top unit); the water line the boreholes' water table unless drawn.

Each stratum reaches down to the next one's top (the lines are kept in order from the top down,
a line above the ground is cut off) and the last to the base. Water: a phreatic line gives
u = γw (zw - z) at the slip surface (hydrostatic below the line, no seepage correction), or a
pore pressure ratio u = ru σv (of the soil, else of the section); an undrained soil (cu, φ = 0)
is in total stresses.

**The slices**: the sliding mass between the slip surface's entry and exit is cut into vertical
slices (``search.slices`` plus the ground's vertices); each has its weight W (γ above the water
line, γsat below it), the surcharge Q on its top, the base length l and angle α (positive where
the base descends in the direction of sliding), c, tan φ and u of the soil at its base. The
sliding mass is analysed in a frame where it moves to +x (the section is mirrored when it fails
to the left); results are given in the section's own frame.

Equilibrium of a slice (forces kh W horizontal and (1 ± kv) W vertical, interslice forces E,
X = λ f(x) E, base N and S = (c l + (N - u l) tan φ) / F, nail forces T): ::

    N = [W (1 ± kv) + Q + ΔX - Tz - (c l - u l tan φ) sin α / F] / mα,   mα = cos α + sin α tan φ / F

- **Bishop simplified** (Bishop 1955): ΔX = 0, moment equilibrium about the circle's centre:
  F = Σ (c l + (N - u l) tan φ) R / Σ (driving moments); circular surfaces only;
- **Janbu simplified** (Janbu 1973): ΔX = 0, horizontal force equilibrium
  F0 = Σ (c l + (N - u l) tan φ) cos α / Σ (N sin α + kh W + Tx), times Janbu's correction
  f0 = 1 + b1 (d/L - 1.4 (d/L)²) (b1 0.69 c only, 0.31 φ only, 0.50 c and φ; Abramson et al.
  2002), d the depth of the surface below its chord L;
- **Spencer** (1967, f = 1) and **Morgenstern-Price** (1965, f = sin π (x - xa)/(xb - xa), the
  half-sine): both equilibria, λ found where the factor of safety of moments equals that of
  forces (the general limit equilibrium formulation of Fredlund and Krahn 1977).

A slice with mα < 0.2 makes a surface unreliable (Whitman and Bailey 1967): it is left out of the
search and stated on the result.

**The search**: circles over a grid of centres (``search.centres``, else a box above the slope
worked out from its height) and radii tangent to levels between the ground and the base, refined
twice about the best centre; non-circular surfaces optimised from the critical circle by a
random walk of their vertices (kept concave and under the ground), and any surfaces given. The
search runs the search method (Bishop for circles, Janbu otherwise); every method of the check
then runs on the best surfaces found, and each method's lowest factor of safety is reported.

**Nails and anchors** (``Slope.nails``): where the slip surface crosses one, the resisting force
per metre T = min(capacity / tendonFactor, pull-out behind the surface / bondFactor, and for a
nail the pull-out in front plus its head capacity) / spacing, pull-out = π D qs L (an anchor's
bonded length is its fixed length at the far end), acts along it on the sliding mass.

**Verification** (the pack's ``verification``):

- ``factorOfSafety``: the characteristic strengths and loads, F ≥ the required factor of safety
  (permanent or temporary slope, ``Slope.requiredFS`` overriding); with ``Slope.seismic`` also
  under kh = ``seismic.khFactor`` × the peak ground acceleration of the project and kv =
  ± ``seismic.kvRatio`` kh, F ≥ ``required.seismic``;
- ``partialFactors``: each combination of the pack's design approach (``geotechnicalMethods``):
  tan φ'/γφ', c'/γc', cu/γcu, γ/γγ of its set M, the variable surcharges × γQ and the permanent
  ones × γG of its set A, the soil's own weight × ``partialFactors.soilWeight``; F ≥ γR;e of its
  set R (``partialFactors.resistances``); the seismic case on ``seismic.materials``, F ≥
  ``seismic.required``.

Units: m, kN, kPa, kN/m per metre run inside; the library's mm in, results in m.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.check import _check
from saengine.library.substructure import SLOPE_METHODS

#: Unit weight of water [kN/m³].
GAMMA_W = 9.81
#: mα below this makes a slice's normal force unreliable (Whitman and Bailey 1967).
MIN_M_ALPHA = 0.2
#: Janbu's correction b1 (Abramson et al. 2002): c only, φ only, c and φ.
JANBU_B1 = {"c": 0.69, "phi": 0.31, "cphi": 0.50}
#: Iterations and tolerance of a factor of safety.
ITERATIONS = 200
TOLERANCE = 1e-5
#: λ of Spencer and Morgenstern-Price: searched outward from 0 in these steps, up to the limit.
LAMBDA_STEP = 0.1
LAMBDA_LIMIT = 2.0
#: Points of an arc or a line sent to the editor and the report.
CURVE_POINTS = 60
#: Best distinct surfaces of a search on which every method runs.
CANDIDATES = 6
#: Random walk of the non-circular search: trials, vertices of the surface.
WALK_TRIALS = 400
WALK_VERTICES = 8
#: Fill above the natural ground of a section cut from the strata: the soil with this id.
FILL_ID = "FILL"


def table() -> Any | None:
    """The pack's ``slopeStability`` table, or None when the pack does not cover it."""
    pack = code_context.current()
    return pack.table("slopeStability") if pack.has("slopeStability") else None


def clause(key: str) -> str:
    found = table()
    return str((found.clauses or {}).get(key) or found.source) if found is not None else ""


def cite(key: str) -> str:
    """``clause`` after the pack's code name (SAEngine practice as it is; alpha 9 C26: named
    after the pack that supplies it when the pack in force inherits it)."""
    text = clause(key)
    if not text:
        return text
    if text.startswith(code_context.PRACTICE):
        found = table()
        own_key = key if (getattr(found, "clauses", None) or {}).get(key) else ""
        return code_context.attribute(text, "slopeStability", own_key)
    return code_context.cite("slopeStability", key) or text


# ─────────────────────────────── the section ───────────────────────────────


@dataclass
class SoilProps:
    """A soil of the section with its values resolved."""

    id: str
    name: str
    gamma: float
    gamma_sat: float
    c: float
    phi: float  # degrees (0 when undrained)
    cu: float | None
    undrained: bool
    ru: float | None = None
    E: float | None = None  # MPa
    poisson: float | None = None
    dilatancy: float = 0.0
    model: str = "mohrCoulomb"
    source: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "gamma": round(self.gamma, 2),
            "gammaSat": round(self.gamma_sat, 2),
            "c": round(self.c, 2),
            "phi": round(self.phi, 2),
            "cu": None if self.cu is None else round(self.cu, 2),
            "undrained": self.undrained,
            "ru": self.ru,
            "E": None if self.E is None else round(self.E, 2),
            "source": self.source,
        }


@dataclass
class Nail:
    """A nail or anchor in the section's frame: head (x, z) [m], direction into the slope."""

    id: str
    kind: str
    x: float
    z: float
    dx: float
    dz: float
    length: float
    fixed: float  # bonded length at the far end [m] (a nail: the whole length)
    spacing: float
    capacity: float
    bond: float  # kPa
    diameter: float  # m
    head: float | None


@dataclass
class Section:
    """A 2D section (see the module): its ground, the top lines of its strata below the first,
    the soils, base, water and loads, in the frame where it is analysed."""

    surface: np.ndarray  # (k, 2) x ascending
    lines: list[np.ndarray]  # top line of strata 1..n-1, each (k, 2) x ascending
    soils: list[SoilProps]  # one per stratum
    base: float
    water: np.ndarray | None = None
    ru: float | None = None
    surcharges: list[tuple[float, float, float, bool]] = field(default_factory=list)
    nails: list[Nail] = field(default_factory=list)
    mirrored: bool = False
    source: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def x0(self) -> float:
        return float(self.surface[0, 0])

    @property
    def x1(self) -> float:
        return float(self.surface[-1, 0])

    def ground(self, x: Any) -> Any:
        return np.interp(x, self.surface[:, 0], self.surface[:, 1])

    def water_level(self, x: Any) -> Any | None:
        if self.water is None:
            return None
        return np.interp(x, self.water[:, 0], self.water[:, 1])

    def tops(self, x: np.ndarray) -> np.ndarray:
        """(strata + 1, len(x)): the top of each stratum (the first the ground), each at most
        the one above and at least the base, then the base."""
        x = np.asarray(x, dtype=float)
        out = np.empty((len(self.soils) + 1, len(x)))
        out[0] = np.maximum(self.ground(x), self.base)
        for k, line in enumerate(self.lines, start=1):
            out[k] = np.maximum(
                np.minimum(out[k - 1], np.interp(x, line[:, 0], line[:, 1])), self.base
            )
        out[-1] = self.base
        return out

    def breakpoints(self) -> np.ndarray:
        """The x of every vertex of the ground and the strata lines within the section."""
        xs = [self.surface[:, 0]] + [line[:, 0] for line in self.lines]
        if self.water is not None:
            xs.append(self.water[:, 0])
        values = np.unique(np.concatenate(xs))
        return values[(values >= self.x0) & (values <= self.x1)]

    def mirror(self) -> Section:
        """The section seen from the other side (x → -x)."""

        def flip(points: np.ndarray | None) -> np.ndarray | None:
            if points is None:
                return None
            return np.column_stack([-points[::-1, 0], points[::-1, 1]])

        return replace(
            self,
            surface=flip(self.surface),
            lines=[flip(line) for line in self.lines],
            water=flip(self.water),
            surcharges=[(-b, -a, q, p) for a, b, q, p in self.surcharges],
            nails=[replace(n, x=-n.x, dx=-n.dx) for n in self.nails],
            mirrored=not self.mirrored,
            notes=list(self.notes),
        )

    def to_json(self) -> dict[str, Any]:
        """The section in its own frame (as drawn), for the editor and the report [m]."""
        sec = self.mirror() if self.mirrored else self
        xs = sec.breakpoints()
        tops = sec.tops(xs)

        def pts(points: np.ndarray) -> list[list[float]]:
            return [[round(float(a), 3), round(float(b), 3)] for a, b in points]

        return {
            "surface": pts(sec.surface),
            "strata": [
                {
                    "soil": soil.id,
                    "name": soil.name,
                    "top": pts(np.column_stack([xs, tops[k]])),
                }
                for k, soil in enumerate(sec.soils)
            ],
            "base": round(sec.base, 3),
            "water": None if sec.water is None else pts(sec.water),
            "surcharges": [
                {"start": round(a, 3), "end": round(b, 3), "pressure": q, "permanent": p}
                for a, b, q, p in sec.surcharges
            ],
            "nails": [
                {
                    "id": n.id,
                    "kind": n.kind,
                    "head": [round(n.x, 3), round(n.z, 3)],
                    "end": [round(n.x + n.dx * n.length, 3), round(n.z + n.dz * n.length, 3)],
                }
                for n in sec.nails
            ],
            "source": sec.source,
        }


def _points(points: list[list[float]] | None) -> np.ndarray | None:
    """[[x, level] mm] → (k, 2) m, sorted by x."""
    if not points:
        return None
    a = np.array(points, dtype=float) / 1e3
    return a[np.argsort(a[:, 0], kind="stable")]


def _soil(given: Any, base: SoilProps | None = None) -> SoilProps | str:
    """A slope soil's values over the base's (a unit's from the boreholes), or why not."""
    if given is None and base is None:
        return "a stratum has no soil"
    sid = given.id if given is not None else base.id  # type: ignore[union-attr]
    gamma = given.unitWeight if given is not None and given.unitWeight else None
    gamma = gamma or (base.gamma if base else None)
    if gamma is None:
        return f"soil {sid}: needs its unit weight"
    gamma_sat = (given.saturatedUnitWeight if given is not None else None) or (
        base.gamma_sat if base else gamma
    )
    phi = given.phi if given is not None and given.phi is not None else None
    c = given.c if given is not None and given.c is not None else None
    cu = given.cu if given is not None and given.cu is not None else None
    if base is not None:
        phi = phi if phi is not None else (None if base.undrained else base.phi)
        c = c if c is not None else base.c
        cu = cu if cu is not None else base.cu
    strength = getattr(given, "strength", None) if given is not None else None
    if strength is None:
        strength = "drained" if phi is not None else "undrained"
    if strength == "undrained":
        if cu is None:
            return f"soil {sid}: an undrained soil needs cu"
        c_, phi_, undrained = float(cu), 0.0, True
    else:
        if phi is None:
            return f"soil {sid}: a drained soil needs φ'"
        c_, phi_, undrained = float(c or 0.0), float(phi), False
    name = (given.name if given is not None and given.name else None) or (
        base.name if base else sid
    )
    source = "as entered" if base is None else base.source
    if base is not None and given is not None:
        source += "; values entered for the slope override"
    return SoilProps(
        sid,
        name,
        float(gamma),
        float(gamma_sat),
        c_,
        phi_,
        None if cu is None else float(cu),
        undrained,
        given.ru if given is not None else None,
        (given.E if given is not None and given.E else None) or (base.E if base else None),
        given.poisson if given is not None else None,
        float(given.dilatancy or 0.0) if given is not None else 0.0,
        (given.model if given is not None and given.model else None) or "mohrCoulomb",
        source,
    )


def _nails(slope: Any) -> list[Nail]:
    out = []
    for n in slope.nails:
        theta = math.radians(n.inclination)
        length = n.length / 1e3
        fixed = length if n.kind == "nail" else (n.fixedLength or n.length / 3) / 1e3
        out.append(
            Nail(
                n.id,
                n.kind,
                n.x / 1e3,
                n.level / 1e3,
                # Into the slope: the face looks to the lower end of the section.
                0.0,
                -math.sin(theta),
                length,
                min(fixed, length),
                n.spacing / 1e3,
                float(n.capacity),
                float(n.bond),
                n.diameter / 1e3,
                n.headCapacity,
            )
        )
    return out


def _orient_nails(sec: Section) -> None:
    """Point each nail into the slope: towards the higher end of the section."""
    left_higher = float(sec.ground(sec.x0)) >= float(sec.ground(sec.x1))
    for n in sec.nails:
        horizontal = math.sqrt(max(1.0 - n.dz**2, 0.0))
        n.dx = -horizontal if left_higher else horizontal


def _unit_soils(soil_text: str | None, model: dict[str, Any]) -> dict[str, SoilProps]:
    """Each unit's soil from the boreholes' layers in it (thickness-weighted means)."""
    from saengine.substructure.piles import profiles_of

    profiles = {p.id: p for p in profiles_of(soil_text)[0]}
    sums: dict[str, dict[str, list[tuple[float, float]]]] = {}
    seen: dict[str, list[str]] = {}
    for hole in model["boreholes"]:
        profile = profiles.get(hole["id"])
        if profile is None:
            continue
        ground = hole["ground"]
        for index, layer in enumerate(profile.layers):
            mid = ground - (layer.top + layer.bottom) / 2
            unit = next(
                (s["unit"] for s in hole["strata"] if s["bottom"] - 1e-6 <= mid <= s["top"] + 1e-6),
                None,
            )
            if unit is None:
                continue
            h = max(layer.bottom - layer.top, 1e-6)
            acc = sums.setdefault(unit, {})
            for key, value in (
                ("gamma", layer.gamma),
                ("gamma_sat", layer.gamma_sat),
                ("phi", layer.phi),
                ("c", layer.c if layer.phi is not None else None),
                ("cu", layer.cu),
                ("E", layer.E),
            ):
                if value is not None:
                    acc.setdefault(key, []).append((float(value), h))
            seen.setdefault(unit, []).append(f"{hole['id']} layer {index + 1}")
    out: dict[str, SoilProps] = {}
    kinds = {u["id"]: u for u in model["units"]}
    for unit, acc in sums.items():

        def mean(key: str, acc: dict = acc) -> float | None:
            rows = acc.get(key)
            if not rows:
                return None
            return sum(v * h for v, h in rows) / sum(h for _, h in rows)

        gamma = mean("gamma") or 18.0
        phi_rows = sum(h for _, h in acc.get("phi", []))
        cu_rows = sum(h for _, h in acc.get("cu", []))
        undrained = phi_rows < cu_rows or mean("phi") is None
        cu = mean("cu")
        if undrained and cu is None:
            undrained = False
        phi = mean("phi")
        out[unit] = SoilProps(
            unit,
            f"{unit} ({kinds.get(unit, {}).get('soilType', '')})",
            gamma,
            mean("gamma_sat") or gamma,
            float(cu) if undrained else float(mean("c") or 0.0),
            0.0 if undrained else float(phi if phi is not None else 30.0),
            cu,
            undrained,
            None,
            mean("E"),
            source="soil report: the mean of " + ", ".join(seen[unit]),
        )
    return out


def build_section(ctx: Any, slope: Any) -> Section | str:
    """The slope's :class:`Section` in its own frame (not mirrored), or why it cannot be made."""
    given = {s.id: s for s in slope.soils}
    surcharges = [
        (s.start / 1e3, s.end / 1e3, float(s.pressure), bool(s.permanent)) for s in slope.surcharges
    ]
    notes: list[str] = []
    if slope.section == "drawn":
        surface = _points(slope.surface)
        if surface is None or len(surface) < 2:
            return "a drawn section needs its ground surface (two points or more)"
        strata = list(slope.strata)
        if not strata:
            if len(slope.soils) != 1:
                return "a drawn section needs its strata (or a single soil)"
            strata = [SimpleNamespace(soil=slope.soils[0].id, points=[])]
        soils: list[SoilProps] = []
        for stratum in strata:
            found = _soil(given.get(stratum.soil))
            if isinstance(found, str):
                return found
            soils.append(found)
        lines = []
        for k, stratum in enumerate(strata[1:], start=2):
            line = _points(stratum.points)
            if line is None:
                return f"stratum {k} ({stratum.soil}) needs its top line"
            lines.append(line)
        water = _points(slope.water)
        source = "drawn"
    else:
        if slope.start is None or slope.end is None:
            return "a section cut from the strata needs its start and end in plan"
        from saengine.soil.report import parse
        from saengine.soil.stratigraphy import section as cut

        if not ctx.soil_text:
            return "a section cut from the strata needs the soil report (01 Soil Report)"
        report = parse(ctx.soil_text)
        if isinstance(report, list):
            return "the soil report cannot be read: " + "; ".join(report[:3])
        start = (slope.start[0] / 1e3, slope.start[1] / 1e3)
        end = (slope.end[0] / 1e3, slope.end[1] / 1e3)
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        model = cut(report, start, end, max(60, min(int(length) + 1, 400)))
        notes += [f"stratigraphy: {n}" for n in model["notes"]]
        units = model["units"]
        if not units:
            return "the soil report has no logged layers to cut the section from"
        xs = np.array([s["distance"] for s in model["stations"]], dtype=float)
        surfaces = model["surfaces"]
        if any(v is None for v in surfaces[0]):
            return "the boreholes do not give the ground along the section"
        natural = np.column_stack([xs, np.array(surfaces[0], dtype=float)])
        derived = _unit_soils(ctx.soil_text, model)
        soils = []
        lines = []
        known = [
            k for k in range(len(units)) if all(v is not None for v in surfaces[k + 1])
        ]  # units whose bottom is known everywhere
        deepest = max(known) if known else len(units) - 1
        for k in range(deepest + 1):
            unit = units[k]["id"]
            if derived.get(unit) is None and given.get(unit) is None:
                return f"unit {unit}: no layer of the boreholes gives its values"
            found = _soil(given.get(unit), derived.get(unit))
            if isinstance(found, str):
                return found
            soils.append(found)
            if k > 0:
                top = [surfaces[k][i] for i in range(len(xs))]
                values = np.array([np.nan if v is None else v for v in top], dtype=float)
                if np.isnan(values).any():  # pinched out where unknown: take the surface above
                    values = np.where(
                        np.isnan(values), lines[-1][:, 1] if lines else natural[:, 1], values
                    )
                lines.append(np.column_stack([xs, values]))
        bottom = surfaces[deepest + 1]
        logged = (
            min(float(v) for v in bottom if v is not None)
            if any(v is not None for v in bottom)
            else None
        )
        surface = natural
        designed = _points(slope.surface)
        if designed is not None and len(designed) >= 2:
            surface = designed
            fill = np.interp(xs, designed[:, 0], designed[:, 1]) - natural[:, 1]
            if (fill > 0.01).any():
                found = _soil(given.get(FILL_ID), None if FILL_ID in given else soils[0])
                if isinstance(found, str):
                    return found
                if FILL_ID not in given:
                    notes.append(
                        "the designed surface is above the natural ground: the fill is taken as "
                        f"{soils[0].id} (add a soil {FILL_ID} for its own values)"
                    )
                soils.insert(0, found)
                lines.insert(0, natural)
        water = _points(slope.water)
        if water is None and model["water"] is not None:
            levels = [w for w in model["water"] if w is not None]
            if len(levels) == len(xs):
                water = np.column_stack([xs, np.array(levels, dtype=float)])
        source = (
            f"cut from the strata of 01 Soil Report from ({start[0]:.1f}, {start[1]:.1f}) to "
            f"({end[0]:.1f}, {end[1]:.1f}) m, {len(soils)} strata"
        )
        if logged is not None and slope.base is None:
            notes.append(f"the section's base is the deepest logged boundary, {logged:.2f} m")
    ground_min = float(surface[:, 1].min())
    ground_max = float(surface[:, 1].max())
    height = max(ground_max - ground_min, 1.0)
    if slope.base is not None:
        base = slope.base / 1e3
    elif slope.section == "strata" and logged is not None:
        base = logged
        if base >= ground_min - 0.1:
            base = ground_min - height
            notes.append(
                f"the boreholes stop above the lowest ground: the deepest unit is taken down to "
                f"{base:.2f} m"
            )
    else:
        lowest = min([ground_min] + [float(line[:, 1].min()) for line in lines])
        base = lowest - height
    if base >= ground_min:
        return f"the base ({base:.2f} m) must be below the ground ({ground_min:.2f} m)"
    sec = Section(
        surface,
        lines,
        soils,
        base,
        water,
        slope.ru,
        surcharges,
        _nails(slope),
        False,
        source,
        notes,
    )
    _orient_nails(sec)
    if (
        sec.water is not None
        and (sec.water_level(sec.surface[:, 0]) > sec.surface[:, 1] + 0.01).any()
    ):
        notes.append(
            "the water line is above the ground in places: the weight of free water on the "
            "slope is not counted (on the safe side for a submerged toe only when it is small)"
        )
    return sec


# ─────────────────────────────── slip surfaces and slices ───────────────────────────────


@dataclass
class Surface:
    """A slip surface: its base z(x) between entry and exit, and a circle's centre and radius."""

    entry: float
    exit: float
    z: Callable[[np.ndarray], np.ndarray]
    vertices: np.ndarray  # x of the polyline's vertices (none for a circle)
    centre: tuple[float, float] | None = None
    radius: float | None = None
    points: np.ndarray | None = None  # the polyline (non-circular)

    def polyline(self, count: int = CURVE_POINTS) -> np.ndarray:
        if self.points is not None:
            return self.points
        xs = np.linspace(self.entry, self.exit, count)
        return np.column_stack([xs, self.z(xs)])


@dataclass
class Case:
    """One check: the strengths' and loads' factors, the seismic coefficients, the required
    factor of safety."""

    name: str
    required: float
    tan_phi: float = 1.0
    cohesion: float = 1.0
    undrained: float = 1.0
    weight: float = 1.0
    permanent: float = 1.0
    variable: float = 1.0
    kh: float = 0.0
    kv: float = 0.0
    seismic: bool = False
    note: str = ""


@dataclass
class Slices:
    xb: np.ndarray
    xm: np.ndarray
    b: np.ndarray
    zb: np.ndarray
    alpha: np.ndarray
    sin: np.ndarray
    cos: np.ndarray
    length: np.ndarray
    W: np.ndarray
    Wv: np.ndarray
    zcg: np.ndarray
    Q: np.ndarray
    c: np.ndarray
    tan: np.ndarray
    u: np.ndarray
    kh: float
    Tx: np.ndarray
    Tz: np.ndarray
    forces: list[tuple[float, float, float, float]]  # nails: (x, z, Tx, Tz)
    has_c: bool
    has_phi: bool


def circle(sec: Section, xc: float, zc: float, radius: float, min_depth: float) -> Surface | None:
    """The arc of the circle below the ground (its longest part), or None when it does not make
    a slip surface within the section (above the base, at least ``min_depth`` deep)."""
    if radius <= 0 or zc - radius < sec.base - 1e-6:
        return None
    lo, hi = max(xc - radius, sec.x0), min(xc + radius, sec.x1)
    if hi - lo < 1e-3:
        return None
    inside = sec.surface[:, 0][(sec.surface[:, 0] > lo) & (sec.surface[:, 0] < hi)]
    xs = np.unique(np.concatenate([np.linspace(lo, hi, 161), inside]))

    def arc(x: np.ndarray) -> np.ndarray:
        return zc - np.sqrt(np.maximum(radius**2 - (np.asarray(x) - xc) ** 2, 0.0))

    d = sec.ground(xs) - arc(xs)
    below = d > 1e-9
    if not below.any():
        return None
    best: tuple[float, int, int] | None = None
    k = 0
    n = len(xs)
    while k < n:
        if not below[k]:
            k += 1
            continue
        j = k
        while j + 1 < n and below[j + 1]:
            j += 1
        area = float(np.trapezoid(d[k : j + 1], xs[k : j + 1])) if j > k else 0.0
        if best is None or area > best[0]:
            best = (area, k, j)
        k = j + 1
    assert best is not None
    _, k, j = best
    if (k == 0 and xs[0] <= sec.x0 + 1e-9) or (j == n - 1 and xs[-1] >= sec.x1 - 1e-9):
        return None  # leaves the section through its side
    if k == 0 or j == n - 1:
        return None  # the centre is below the ground

    def root(a: int, b: int) -> float:
        xa, xb = xs[a], xs[b]
        da = d[a]
        for _ in range(40):
            xm = (xa + xb) / 2
            dm = float(sec.ground(xm) - arc(np.array([xm]))[0])
            if (dm > 0) == (da > 0):
                xa, da = xm, dm
            else:
                xb = xm
        return (xa + xb) / 2

    entry, exit_ = root(k - 1, k), root(j, j + 1)
    if exit_ - entry < 0.1 or float(d[k : j + 1].max()) < min_depth:
        return None
    return Surface(entry, exit_, arc, np.array([]), (xc, zc), radius)


def polyline_surface(sec: Section, points: np.ndarray, min_depth: float = 0.0) -> Surface | None:
    """A non-circular surface through ``points`` (x ascending), its ends put on the ground."""
    pts = np.array(points, dtype=float)
    pts = pts[np.argsort(pts[:, 0], kind="stable")]
    if len(pts) < 2 or pts[-1, 0] - pts[0, 0] < 0.1:
        return None
    pts[0, 1] = float(sec.ground(pts[0, 0]))
    pts[-1, 1] = float(sec.ground(pts[-1, 0]))
    if pts[0, 0] < sec.x0 - 1e-6 or pts[-1, 0] > sec.x1 + 1e-6:
        return None
    if (pts[:, 1] < sec.base - 1e-6).any():
        return None
    inner = pts[1:-1]
    if len(inner) and (inner[:, 1] > sec.ground(inner[:, 0]) + 1e-6).any():
        return None
    depth = sec.ground(pts[:, 0]) - pts[:, 1]
    if float(depth.max()) < min_depth:
        return None

    def z(x: np.ndarray) -> np.ndarray:
        return np.interp(x, pts[:, 0], pts[:, 1])

    return Surface(pts[0, 0], pts[-1, 0], z, pts[:, 0], points=pts)


def _nail_force(n: Nail, surf: Surface, rules: Any) -> tuple[float, float, float] | None:
    """(x, z, T per metre) where the slip surface crosses a nail, or None."""
    steps = np.linspace(0.0, n.length, 241)
    xs = n.x + n.dx * steps
    zs = n.z + n.dz * steps
    inside = (xs >= surf.entry) & (xs <= surf.exit)
    if not inside.any():
        return None
    gap = np.where(inside, zs - surf.z(np.clip(xs, surf.entry, surf.exit)), np.nan)
    sign = np.sign(gap)
    crossing = None
    for i in range(len(steps) - 1):
        if np.isnan(sign[i]) or np.isnan(sign[i + 1]):
            continue
        if sign[i] >= 0 > sign[i + 1] or sign[i] > 0 >= sign[i + 1]:
            t = gap[i] / (gap[i] - gap[i + 1])
            crossing = steps[i] + t * (steps[i + 1] - steps[i])
            break
    if crossing is None:
        return None
    rf = rules.reinforcement if rules is not None else None
    tendon = n.capacity / (rf.tendonFactor if rf else 1.0)
    unit = math.pi * n.diameter * n.bond / (rf.bondFactor if rf else 1.0)
    behind = n.length - crossing
    bonded_behind = min(n.fixed, behind)
    force = min(tendon, unit * bonded_behind)
    if n.kind == "nail":
        front = unit * crossing + (n.head if n.head is not None else n.capacity)
        force = min(force, front)
    if force <= 0:
        return None
    return (n.x + n.dx * crossing, n.z + n.dz * crossing, force / n.spacing)


def slices(sec: Section, surf: Surface, count: int, case: Case, rules: Any) -> Slices | None:
    """The slices of the sliding mass over ``surf`` under ``case``."""
    xb = np.linspace(surf.entry, surf.exit, count + 1)
    extra = np.concatenate([sec.breakpoints(), surf.vertices])
    extra = extra[(extra > surf.entry + 1e-6) & (extra < surf.exit - 1e-6)]
    xb = np.unique(np.concatenate([xb, extra]))
    keep = np.concatenate([[True], np.diff(xb) > 1e-6 * (surf.exit - surf.entry)])
    xb = xb[keep]
    if len(xb) < 3:
        return None
    xm = (xb[:-1] + xb[1:]) / 2
    b = np.diff(xb)
    zl, zr = surf.z(xb[:-1]), surf.z(xb[1:])
    zb = surf.z(xm)
    dz = zr - zl
    alpha = np.arctan2(-dz, b)
    length = np.hypot(b, dz)
    ground = sec.ground(xm)
    tops = sec.tops(xm)
    zw = sec.water_level(xm)
    W = np.zeros_like(xm)
    moment = np.zeros_like(xm)
    for k, soil in enumerate(sec.soils):
        top = np.minimum(tops[k], ground)
        bottom = np.maximum(tops[k + 1], zb)
        thick = np.clip(top - bottom, 0.0, None)
        if zw is None:
            wet = np.zeros_like(thick)
        else:
            wet = np.clip(np.minimum(top, zw) - bottom, 0.0, thick)
        dry = thick - wet
        w = (soil.gamma * dry + soil.gamma_sat * wet) * b
        W += w
        moment += w * (bottom + top) / 2
    # The base soil: the deepest stratum whose top is above the base point.
    base_soil = np.zeros(len(xm), dtype=int)
    for k in range(len(sec.soils)):
        base_soil = np.where(zb <= tops[k] + 1e-9, k, base_soil)
    W *= case.weight
    zcg = np.where(W > 0, moment * case.weight / np.where(W > 0, W, 1.0), zb)
    c = np.empty_like(xm)
    tan = np.empty_like(xm)
    u = np.zeros_like(xm)
    has_c = has_phi = False
    for k, soil in enumerate(sec.soils):
        mask = base_soil == k
        if not mask.any():
            continue
        if soil.undrained:
            c[mask] = soil.c / case.undrained
            tan[mask] = 0.0
            has_c = has_c or soil.c > 0
            continue
        c[mask] = soil.c / case.cohesion
        tan[mask] = math.tan(math.radians(soil.phi)) / case.tan_phi
        has_c = has_c or soil.c > 0
        has_phi = has_phi or soil.phi > 0
        ru = soil.ru if soil.ru is not None else None
        if ru is not None:
            u[mask] = ru * W[mask] / b[mask]
        elif zw is not None:
            u[mask] = GAMMA_W * np.clip(zw[mask] - zb[mask], 0.0, None)
        elif sec.ru is not None:
            u[mask] = sec.ru * W[mask] / b[mask]
    Q = np.zeros_like(xm)
    for a, e, q, permanent in sec.surcharges:
        overlap = np.clip(np.minimum(xb[1:], e) - np.maximum(xb[:-1], a), 0.0, None)
        Q += q * overlap * (case.permanent if permanent else case.variable)
    Tx = np.zeros_like(xm)
    Tz = np.zeros_like(xm)
    forces = []
    for n in sec.nails:
        found = _nail_force(n, surf, rules)
        if found is None:
            continue
        x, z, t = found
        j = int(np.clip(np.searchsorted(xb, x) - 1, 0, len(xm) - 1))
        Tx[j] += t * n.dx
        Tz[j] += t * n.dz
        forces.append((x, z, t * n.dx, t * n.dz))
    Wv = W * (1.0 + case.kv)
    return Slices(
        xb,
        xm,
        b,
        zb,
        alpha,
        np.sin(alpha),
        np.cos(alpha),
        length,
        W,
        Wv,
        zcg,
        Q,
        c,
        tan,
        u,
        case.kh,
        Tx,
        Tz,
        forces,
        has_c,
        has_phi,
    )


# ─────────────────────────────── the methods ───────────────────────────────


def _normal(s: Slices, F: float, dX: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ma = s.cos + s.sin * s.tan / F
    safe = np.where(np.abs(ma) < 1e-6, 1e-6, ma)
    N = (s.Wv + s.Q + dX - s.Tz - (s.c * s.length - s.u * s.length * s.tan) * s.sin / F) / safe
    return N, ma


def _resisting(s: Slices, N: np.ndarray) -> np.ndarray:
    return s.c * s.length + np.clip(N - s.u * s.length, 0.0, None) * s.tan


def _moment_fs(s: Slices, N: np.ndarray, R: np.ndarray, o: tuple[float, float]) -> float:
    xo, zo = o
    driving = (
        np.sum((s.xm - xo) * (-(s.Wv + s.Q)) - (s.zcg - zo) * (s.kh * s.W))
        + np.sum((s.xm - xo) * N * s.cos - (s.zb - zo) * N * s.sin)
        + sum((x - xo) * tz - (z - zo) * tx for x, z, tx, tz in s.forces)
    )
    arm = (s.xm - xo) * s.sin + (s.zb - zo) * s.cos
    resisting = float(np.sum(R * (-arm)))
    if driving <= 1e-9:
        return math.inf
    return resisting / float(driving)


def _force_fs(s: Slices, N: np.ndarray, R: np.ndarray) -> float:
    driving = float(np.sum(s.kh * s.W + N * s.sin + s.Tx))
    if driving <= 1e-9:
        return math.inf
    return float(np.sum(R * s.cos)) / driving


@dataclass
class Result:
    method: str
    fs: float
    lam: float | None = None
    min_ma: float = 1.0
    note: str = ""


def bishop(s: Slices, centre: tuple[float, float]) -> Result | None:
    F = 1.0
    zero = np.zeros_like(s.xm)
    for _ in range(ITERATIONS):
        N, ma = _normal(s, F, zero)
        Fn = _moment_fs(s, N, _resisting(s, N), centre)
        if not math.isfinite(Fn) or Fn <= 0:
            return None
        if abs(Fn - F) < TOLERANCE:
            return Result("bishop", Fn, None, float(ma.min()))
        F = Fn
    return None


def janbu(s: Slices, surf: Surface) -> Result | None:
    F = 1.0
    zero = np.zeros_like(s.xm)
    for _ in range(ITERATIONS):
        N, ma = _normal(s, F, zero)
        Fn = _force_fs(s, N, _resisting(s, N))
        if not math.isfinite(Fn) or Fn <= 0:
            return None
        if abs(Fn - F) < TOLERANCE:
            # Janbu's correction factor for the interslice shear left out.
            chord = math.hypot(
                surf.exit - surf.entry,
                float(surf.z(np.array([surf.exit]))[0] - surf.z(np.array([surf.entry]))[0]),
            )
            xs = np.linspace(surf.entry, surf.exit, 41)
            za, zb = (
                float(surf.z(np.array([surf.entry]))[0]),
                float(surf.z(np.array([surf.exit]))[0]),
            )
            line = za + (zb - za) * (xs - surf.entry) / max(surf.exit - surf.entry, 1e-9)
            depth = float(np.max(line - surf.z(xs)))
            ratio = depth / chord if chord > 0 else 0.0
            key = "cphi" if s.has_c and s.has_phi else "c" if s.has_c else "phi"
            f0 = 1.0 + JANBU_B1[key] * (ratio - 1.4 * ratio**2)
            return Result(
                "janbu",
                Fn * max(f0, 1.0),
                None,
                float(ma.min()),
                f"F0 = {Fn:.3f} × f0 = {max(f0, 1.0):.3f} (d/L = {ratio:.3f})",
            )
        F = Fn
    return None


def _gle(s: Slices, lam: float, shape: np.ndarray, o: tuple[float, float], moment: bool):
    """F of moment (or force) equilibrium with X = λ f E (the interslice force function at the
    slices' boundaries), or None when it does not converge."""
    F = 1.0
    X = np.zeros(len(s.xb))
    for iteration in range(ITERATIONS):
        dX = X[1:] - X[:-1]
        N, ma = _normal(s, F, dX)
        R = _resisting(s, N)
        Fn = _moment_fs(s, N, R, o) if moment else _force_fs(s, N, R)
        if not math.isfinite(Fn) or Fn <= 0:
            return None
        dE = s.kh * s.W + N * s.sin - R * s.cos / Fn + s.Tx
        E = np.concatenate([[0.0], np.cumsum(dE)])
        X = lam * shape * E
        X[0] = X[-1] = 0.0
        if abs(Fn - F) < TOLERANCE:
            return Fn, float(ma.min())
        F = 0.5 * (F + Fn) if iteration > 50 else Fn  # damped when it oscillates
    return None


def rigorous(s: Slices, method: str, o: tuple[float, float]) -> Result | None:
    """Spencer (f = 1) or Morgenstern-Price (half-sine): λ where the moment and force factors
    of safety agree."""
    if method == "spencer":
        shape = np.ones(len(s.xb))
    else:
        span = max(s.xb[-1] - s.xb[0], 1e-9)
        shape = np.sin(math.pi * (s.xb - s.xb[0]) / span)

    def gap(lam: float) -> tuple[float, float, float] | None:
        fm = _gle(s, lam, shape, o, True)
        ff = _gle(s, lam, shape, o, False)
        if fm is None or ff is None:
            return None
        return fm[0] - ff[0], fm[0], min(fm[1], ff[1])

    previous = gap(0.0)
    if previous is None:
        return None
    if abs(previous[0]) < 1e-4:
        return Result(method, previous[1], 0.0, previous[2])
    bracket: tuple[float, float, Any, Any] | None = None
    last = {1.0: (0.0, previous), -1.0: (0.0, previous)}
    steps = round(LAMBDA_LIMIT / LAMBDA_STEP)
    for i in range(1, steps + 1):
        for sign in (1.0, -1.0):
            lam = sign * i * LAMBDA_STEP
            here = gap(lam)
            if here is None:
                continue
            lam0, g0 = last[sign]
            if g0 is not None and (g0[0] > 0) != (here[0] > 0):
                bracket = (lam0, lam, g0, here)
                break
            last[sign] = (lam, here)
        if bracket is not None:
            break
    if bracket is None:
        return None
    a, b, ga, gb = bracket
    best = ga if abs(ga[0]) < abs(gb[0]) else gb
    best_lam = a if best is ga else b
    for _ in range(40):
        m = (a + b) / 2
        gm = gap(m)
        if gm is None:
            break
        if abs(gm[0]) < abs(best[0]):
            best, best_lam = gm, m
        if abs(gm[0]) < 1e-4:
            break
        if (gm[0] > 0) == (ga[0] > 0):
            a, ga = m, gm
        else:
            b, gb = m, gm
    return Result(method, best[1], best_lam, best[2])


def _axis(sec: Section, surf: Surface) -> tuple[float, float]:
    """The axis of the moments: a circle's centre, else a point above the sliding mass."""
    if surf.centre is not None:
        return surf.centre
    xs = np.linspace(surf.entry, surf.exit, 21)
    top = float(sec.ground(xs).max())
    return (float(xs.mean()), top + (surf.exit - surf.entry))


def evaluate(
    sec: Section, surf: Surface, method: str, case: Case, count: int, rules: Any
) -> Result | None:
    """The factor of safety of one surface by one method, or None (no solution, unreliable,
    Bishop on a non-circular surface)."""
    s = slices(sec, surf, count, case, rules)
    if s is None:
        return None
    if method == "bishop":
        if surf.centre is None:
            return None
        found = bishop(s, surf.centre)
    elif method == "janbu":
        found = janbu(s, surf)
    else:
        found = rigorous(s, method, _axis(sec, surf))
    if found is None:
        return None
    if found.min_ma < MIN_M_ALPHA:
        found.note = (found.note + "; " if found.note else "") + (
            f"mα = {found.min_ma:.2f} < {MIN_M_ALPHA:g} at a slice: unreliable"
        )
    return found


# ─────────────────────────────── the search ───────────────────────────────


@dataclass
class Found:
    fs: float
    surface: Surface


def _slope_box(sec: Section) -> tuple[float, float, float, float, float]:
    """(x of the face's top, x of its toe, crest level, toe level, height) in the frame where
    the slope fails to +x."""
    pts = sec.surface
    gmax, gmin = float(pts[:, 1].max()), float(pts[:, 1].min())
    height = max(gmax - gmin, 1.0)
    dx = np.diff(pts[:, 0])
    dz = np.diff(pts[:, 1])
    steep = np.abs(dz) > 0.02 * np.maximum(dx, 1e-9)  # the segments of the face
    if steep.any():
        index = np.nonzero(steep)[0]
        return float(pts[index[0], 0]), float(pts[index[-1] + 1, 0]), gmax, gmin, height
    mid = (sec.x0 + sec.x1) / 2
    return mid - height, mid + height, gmax, gmin, height


def circular_search(
    sec: Section, slope: Any, case: Case, method: str, rules: Any
) -> tuple[list[Found], list[list[float]]]:
    """The best distinct circles (lowest first) and the grid of centres with their lowest
    factor of safety [[x, z, F]] (the first grid)."""
    search = slope.search
    count = search.slices
    min_depth = search.minDepth / 1e3
    xa, xb, gmax, gmin, height = _slope_box(sec)
    if search.centres:
        a, b, c, d = (v / 1e3 for v in search.centres)
        if sec.mirrored:
            a, c = -c, -a
        box = (min(a, c), min(b, d), max(a, c), max(b, d))
    else:
        box = (xa - height, gmax + 0.1 * height, xb + height, gmax + 2.5 * height)
    low = max(sec.base + 0.01, gmin - 1.5 * height)
    high = gmax - max(min_depth, 0.05)
    found: list[Found] = []
    grid: list[list[float]] = []

    def run(xs: np.ndarray, zs: np.ndarray, levels: np.ndarray, record: bool) -> None:
        for xc in xs:
            for zc in zs:
                best = math.inf
                for zt in levels:
                    surf = circle(sec, float(xc), float(zc), float(zc - zt), min_depth)
                    if surf is None:
                        continue
                    result = evaluate(sec, surf, method, case, count, rules)
                    if result is None or result.min_ma < MIN_M_ALPHA:
                        continue
                    found.append(Found(result.fs, surf))
                    best = min(best, result.fs)
                if record:
                    grid.append([float(xc), float(zc), best if math.isfinite(best) else None])

    nx = search.grid
    xs = np.linspace(box[0], box[2], nx)
    zs = np.linspace(box[1], box[3], nx)
    levels = np.linspace(low, high, search.radii) if high > low else np.array([low])
    run(xs, zs, levels, True)
    for _ in range(2):  # refine about the best centre and level
        if not found:
            break
        best = min(found, key=lambda f: f.fs).surface
        assert best.centre is not None and best.radius is not None
        dx = (xs[1] - xs[0]) if len(xs) > 1 else height
        dz = (zs[1] - zs[0]) if len(zs) > 1 else height
        dl = (levels[1] - levels[0]) if len(levels) > 1 else height / 4
        xc, zc = best.centre
        zt = zc - best.radius
        xs = np.linspace(xc - dx, xc + dx, 7)
        zs = np.linspace(zc - dz, zc + dz, 7)
        levels = np.clip(np.linspace(zt - dl, zt + dl, 7), low, high)
        run(xs, zs, np.unique(levels), False)
    return _distinct(found), grid


def _distinct(found: list[Found]) -> list[Found]:
    """The lowest :data:`CANDIDATES` surfaces with distinct ends."""
    out: list[Found] = []
    for f in sorted(found, key=lambda f: f.fs):
        if all(
            abs(f.surface.entry - g.surface.entry) > 0.05
            or abs(f.surface.exit - g.surface.exit) > 0.05
            for g in out
        ):
            out.append(f)
        if len(out) >= CANDIDATES:
            break
    return out


def _admissible(sec: Section, pts: np.ndarray) -> bool:
    if (np.diff(pts[:, 0]) <= 0.01).any():
        return False
    inner = pts[1:-1]
    if (inner[:, 1] >= sec.ground(inner[:, 0]) - 0.01).any() or (pts[:, 1] < sec.base - 1e-6).any():
        return False
    slopes = np.diff(pts[:, 1]) / np.diff(pts[:, 0])
    return bool((np.diff(slopes) >= -1e-6).all())  # concave: it flattens towards the toe


def walk(
    sec: Section, start: Surface, method: str, case: Case, count: int, rules: Any, min_depth: float
) -> Found | None:
    """A non-circular surface optimised from ``start`` by a random walk of its vertices."""
    rng = np.random.default_rng(1)
    xs = np.linspace(start.entry, start.exit, WALK_VERTICES + 1)
    pts = np.column_stack([xs, start.z(xs)])
    surf = polyline_surface(sec, pts, min_depth)
    if surf is None:
        return None
    result = evaluate(sec, surf, method, case, count, rules)
    if result is None:
        return None
    best = Found(result.fs, surf)
    step = 0.1 * max(float((sec.ground(xs) - pts[:, 1]).max()), 0.5)
    fails = 0
    for _ in range(WALK_TRIALS):
        trial = best.surface.points.copy()  # type: ignore[union-attr]
        i = int(rng.integers(0, len(trial)))
        if i in (0, len(trial) - 1):
            trial[i, 0] += float(rng.uniform(-step, step))
            trial[i, 1] = float(sec.ground(trial[i, 0]))
        else:
            trial[i, 1] += float(rng.uniform(-step, step))
        if not _admissible(sec, trial):
            continue
        surf = polyline_surface(sec, trial, min_depth)
        if surf is None:
            continue
        result = evaluate(sec, surf, method, case, count, rules)
        if result is None or result.min_ma < MIN_M_ALPHA:
            continue
        if result.fs < best.fs - 1e-6:
            best = Found(result.fs, surf)
            fails = 0
        else:
            fails += 1
            if fails > 40:
                step /= 2
                fails = 0
    return best


# ─────────────────────────────── cases and checks ───────────────────────────────


def _peak_acceleration(ctx: Any) -> float | None:
    from saengine.fem.ssi import peak_acceleration

    try:
        return peak_acceleration(ctx.settings)
    except (ValueError, KeyError, AttributeError, TypeError):  # a custom location without Z
        return None


def cases(ctx: Any, slope: Any, rules: Any) -> tuple[list[Case], list[str]]:
    """The checks of the slope by the pack's verification, and notes."""
    notes: list[str] = []
    seismic: tuple[float, float] | None = None
    if slope.seismic:
        pga = _peak_acceleration(ctx)
        kh = slope.kh if slope.kh is not None else (rules.seismic.khFactor * pga if pga else None)
        if kh is None:
            notes.append(
                "seismic: the project's settings give no peak ground acceleration; give kh on "
                "the slope"
            )
        else:
            kv = slope.kv if slope.kv is not None else rules.seismic.kvRatio * kh
            seismic = (float(kh), float(kv))
    out: list[Case] = []
    verification = rules.verification
    if verification == "partialFactors":
        from saengine.substructure import limit_state_geotechnics as lsg

        geo = lsg.rules()
        if geo is None:
            notes.append(
                "the code pack checks slopes by partial factors but has no design approach "
                "(geotechnicalMethods): checked by factors of safety"
            )
            verification = "factorOfSafety"
    if verification == "factorOfSafety":
        required = slope.requiredFS or (
            rules.required.temporary if slope.temporary else rules.required.permanent
        )
        why = "as given" if slope.requiredFS else ("temporary" if slope.temporary else "permanent")
        out.append(Case("Static", float(required), note=f"required F {required:g} ({why})"))
        if seismic:
            out += _seismic_cases(seismic, float(rules.required.seismic), None)
        return out, notes
    pf = rules.partialFactors
    approach = pf.approach or geo.designApproach
    if approach not in geo.approaches:
        notes.append(f"design approach {approach} is not in the code pack: {geo.designApproach}")
        approach = geo.designApproach
    for k, combo in enumerate(geo.approaches[approach], start=1):
        a = geo.actions[combo.actions]
        m = geo.materials[combo.materials]
        required = float(pf.resistances.get(combo.resistances, 1.0))
        name = f"{approach}" + (f" C{k}" if len(geo.approaches[approach]) > 1 else "")
        out.append(
            Case(
                f"{name} ({combo.actions} + {combo.materials} + {combo.resistances})",
                required,
                m.tanPhi,
                m.cohesion,
                m.undrained,
                pf.soilWeight / m.weight,
                a.permanentUnfavourable,
                a.variableUnfavourable,
                note=f"γR;e = {required:g}",
            )
        )
    if seismic:
        required = rules.seismic.required or rules.required.seismic
        mset = rules.seismic.materials
        m = geo.materials.get(mset) if mset else None
        out += _seismic_cases(seismic, float(required), m, mset)
    return out, notes


def _seismic_cases(
    seismic: tuple[float, float], required: float, m: Any, mset: str | None = None
) -> list[Case]:
    kh, kv = seismic
    factors = (
        {
            "tan_phi": m.tanPhi,
            "cohesion": m.cohesion,
            "undrained": m.undrained,
            "weight": 1 / m.weight,
        }
        if m is not None
        else {}
    )
    label = f" + {mset}" if m is not None else ""
    out = []
    for sign, text in ((1.0, "kv down"), (-1.0, "kv up")) if kv > 0 else ((0.0, ""),):
        name = f"Seismic{label} (kh {kh:.3f}" + (f", {text} {kv:.3f})" if text else ")")
        out.append(
            Case(
                name,
                required,
                kh=kh,
                kv=sign * kv,
                seismic=True,
                note=f"required F {required:g}",
                **factors,
            )
        )
    return out


def _surface_json(sec: Section, surf: Surface) -> dict[str, Any]:
    pts = surf.polyline()
    if sec.mirrored:
        pts = np.column_stack([-pts[::-1, 0], pts[::-1, 1]])
    out: dict[str, Any] = {"points": [[round(float(x), 3), round(float(z), 3)] for x, z in pts]}
    if surf.centre is not None:
        xc, zc = surf.centre
        out["centre"] = [round(-xc if sec.mirrored else xc, 3), round(zc, 3)]
        out["radius"] = round(float(surf.radius or 0.0), 3)
    return out


def run_case(
    sec: Section, slope: Any, case: Case, methods: list[str], rules: Any
) -> tuple[dict[str, Any], list[list[float]]]:
    """Search the case and run every method on the best surfaces: ``{"name", "required",
    "kh", "kv", "results": [{"method", "fs", "lambda", "surface", "note"}]}`` and the grid."""
    search = slope.search
    count = search.slices
    min_depth = search.minDepth / 1e3
    candidates: list[Surface] = []
    grid: list[list[float]] = []
    method = search.method or ("bishop" if search.surface == "circular" else "janbu")
    # Non-circular surfaces start from the critical circle of Bishop's method (the quickest).
    circle_method = method if search.surface == "circular" else "bishop"
    circles, grid = circular_search(sec, slope, case, circle_method, rules)
    if search.surface == "circular":
        candidates += [f.surface for f in circles]
    elif circles:
        walked = walk(sec, circles[0].surface, method, case, count, rules, min_depth)
        if walked is not None:
            candidates.append(walked.surface)
        candidates += [f.surface for f in circles[:2]]
    for given in search.surfaces:
        pts = np.array(given, dtype=float) / 1e3
        if sec.mirrored:
            pts = np.column_stack([-pts[:, 0], pts[:, 1]])
        surf = polyline_surface(sec, pts)
        if surf is not None:
            candidates.append(surf)
    results = []
    for name in methods:
        best: tuple[Result, Surface] | None = None
        for surf in candidates:
            found = evaluate(sec, surf, name, case, count, rules)
            if found is None or found.min_ma < MIN_M_ALPHA:
                continue
            if best is None or found.fs < best[0].fs:
                best = (found, surf)
        if best is None:
            results.append(
                {
                    "method": name,
                    "fs": None,
                    "lambda": None,
                    "surface": None,
                    "note": "circular surfaces only"
                    if name == "bishop" and search.surface != "circular"
                    else "no solution on the surfaces found",
                }
            )
            continue
        found, surf = best
        results.append(
            {
                "method": name,
                "fs": round(found.fs, 3),
                "lambda": None if found.lam is None else round(found.lam, 3),
                "surface": _surface_json(sec, surf),
                "note": found.note,
            }
        )
    if sec.mirrored:
        grid = [[-x, z, f] for x, z, f in grid]
    return (
        {
            "name": case.name,
            "required": case.required,
            "kh": round(case.kh, 4),
            "kv": round(case.kv, 4),
            "seismic": case.seismic,
            "note": case.note,
            "results": results,
        },
        [[round(x, 3), round(z, 3), None if f is None else round(f, 3)] for x, z, f in grid],
    )


def fs_note(fs: float, required: float) -> str:
    """W4B-18: "F = 1.640 ≥ 1.5 required", or "F = 1.235 < 1.5 required: fails" (the note
    once read "F = 1.235 ≥ 1.5", a pass, on a failing slope)."""
    if fs >= required:
        return f"F = {fs:.3f} ≥ {required:g} required"
    return f"F = {fs:.3f} < {required:g} required: fails"


def method_lines() -> list[str]:
    """The method of the slope checks for the report, with the pack's clauses."""
    rules = table()
    if rules is None:
        return []
    verification = (
        "factors of safety against the required ones"
        if rules.verification == "factorOfSafety"
        else "the design approach's partial factors on the strengths and surcharges, F ≥ γR;e"
    )
    return [
        (
            f"Slopes ({cite('method')}): limit equilibrium of slices on a 2D section drawn or cut "
            "from the site's strata; "
            + ", ".join(SLOPE_METHODS[m] for m in rules.methods)
            + "; circles over a grid of centres and radii (refined), non-circular surfaces "
            f"optimised from the critical circle; {verification} ({cite('required')}); "
            f"pseudo-static seismic coefficients ({cite('seismic')}); nails and anchors as "
            f"resisting forces by {rules.reinforcement.standard} ({cite('reinforcement')})."
        )
    ]


def design_slope(ctx: Any, slope: Any) -> dict[str, Any]:
    """One slope in the report's format: ``{"id", "type": "slope", "columns", "checks",
    "utilisation", "ok", "slope": {"section", "soils", "cases", "grid", "fe", "notes"}}``."""
    rules = table()
    base = {"id": slope.id, "type": "slope", "columns": []}
    if rules is None:
        note = f"Slope stability: not covered by the code pack {code_context.code_name()}"
        return {
            **base,
            "checks": [],
            "utilisation": 0.0,
            "ok": True,
            "slope": None,
            "notes": [note],
        }
    sec0 = build_section(ctx, slope)
    if isinstance(sec0, str):
        row = _check("Slope section", 1.0, 0.0, "", None, f"{sec0} ({cite('method')})")
        return {
            **base,
            "checks": [row],
            "utilisation": row["utilisation"],
            "ok": False,
            "slope": None,
            "notes": [],
        }
    direction = slope.direction
    if direction == "auto":
        left, right = float(sec0.ground(sec0.x0)), float(sec0.ground(sec0.x1))
        direction = "left" if right > left + 1e-6 else "right"
    sec = sec0.mirror() if direction == "left" else sec0
    methods = list(slope.methods or rules.methods)
    checked = set(rules.checked)
    all_cases, notes = cases(ctx, slope, rules)
    notes = list(sec0.notes) + notes
    results = []
    checks = []
    grid: list[list[float]] = []
    for case in all_cases:
        found, case_grid = run_case(sec, slope, case, methods, rules)
        if not grid:
            grid = case_grid
        results.append(found)
        for row in found["results"]:
            name = f"{SLOPE_METHODS[row['method']]}, {case.name}"
            flag = row["method"] not in checked
            if row["fs"] is None:
                if not flag and row["method"] != "bishop":
                    checks.append(
                        _check(
                            name,
                            case.required,
                            0.0,
                            "",
                            case.name,
                            f"{row['note']} ({cite('method')})",
                            flag=True,
                        )
                    )
                continue
            note = f"{fs_note(row['fs'], case.required)} ({cite('required')})"
            if row["lambda"] is not None:
                note += f"; λ = {row['lambda']:.3f}"
            if row["note"]:
                note += f"; {row['note']}"
            if flag:
                note += "; reported"
            checks.append(_check(name, case.required, row["fs"], "", case.name, note, flag=flag))
    fe = None
    if slope.fe is not None and slope.fe.run:
        from saengine.substructure.geotech_fe import analyse as fe_analyse

        try:
            fe = fe_analyse(ctx, slope, sec0, rules, all_cases)
        except Exception as error:  # noqa: BLE001 - the FE is optional; the check stands
            fe = {"error": f"the 2D FE failed: {error}"}
        if fe.get("error"):
            notes.append(str(fe["error"]))
        elif fe.get("check") is not None:
            checks.append(fe["check"])
    counted = [c for c in checks if not c["flag"]]
    return {
        **base,
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in counted), default=0.0),
        "ok": all(c["ok"] for c in counted),
        "slope": {
            "section": sec0.to_json(),
            "direction": direction,
            "soils": [s.to_json() for s in sec0.soils],
            "cases": results,
            "grid": grid,
            "fe": fe,
            "verification": rules.verification,
        },
        "notes": [f"{slope.id}: {n}" for n in notes],
    }


def design_slopes(ctx: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """The slopes of the substructure in the report's format, and notes."""
    results: list[dict[str, Any]] = []
    notes: list[str] = []
    for slope in ctx.substructure.slopes:
        try:
            found = design_slope(ctx, slope)
        except Exception as error:  # noqa: BLE001 - one slope must not sink the report
            row = _check("Slope stability", 1.0, 0.0, "", None, f"the check failed: {error}")
            found = {
                "id": slope.id,
                "type": "slope",
                "columns": [],
                "checks": [row],
                "utilisation": row["utilisation"],
                "ok": False,
                "slope": None,
                "notes": [],
            }
        notes += found.pop("notes", [])
        results.append(found)
    return results, notes

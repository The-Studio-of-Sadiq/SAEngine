"""Moving loads: influence lines by unit load and the envelope of a traffic load model's effects.

The code pack's ``movingLoads`` table gives the traffic as lane load models
(:class:`saengine.codes.bridge_special_tables.MovingLoadsTable`): what lane 1, lane 2, ... carry
(a vehicle's axles, a line load along the lane, a load per m² of the lane), the notional lane
width, the multiple presence factors and the dynamic allowance. A pack without the table takes
SAEngine's practice data on the HL-93 basis (``special/data/movingLoads.json``), named as such.

Influence lines (:func:`line_influence`) come from unit loads on the girder line, a continuous
beam on knife-edge supports (the beam model of :mod:`saengine.design.prestress`, EI constant): the
sagging moment at every station, the shear either side of it and the support reactions, for a
unit load at every station. A deck grillage gives influence surfaces instead
(:mod:`saengine.special.bridges`); a lane's influence line is then the surface along the lane's
wheel lines (each wheel half the axle) for the vehicles and across its width for the lane loads.

The envelope of an effect (:func:`envelope`):

- each lane alone (:func:`lane_extremes`): the vehicle (its variable spacings tried, both ways
  along the bridge, a second vehicle behind it at the table's gap and further where it gives
  more) moved in steps along the line, × its factor and the dynamic allowance when its
  ``dynamic`` is set; plus the line and area loads (× the lane's width) over the parts of the
  influence line of the effect's sign only (the lane load is broken up to give the extreme);
- the lanes together: for 1, 2, ... loaded lanes the load model's lane 1 (the heaviest, as the
  code orders them), lane 2, ... are placed on the lanes that give the most (every assignment
  tried up to six lanes, the best in turn above), × the multiple presence factor of that many
  lanes; the largest of these;
- the largest of the load models; a model for the hogging only (two trucks) counts for the
  negative moments and the interior support reactions alone.

The dynamic allowance (:func:`dynamic_factor`): ``constant`` 1 + IM, ``spanFormula`` 1 + a / (b +
L) by the girder material at most 1 + cap, ``included`` 1. Units: m, kN.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

#: SAEngine's practice data for a pack without the table.
PRACTICE_DIR = Path(__file__).resolve().parent / "data"
#: Step of a vehicle moved along an influence line [m], at most (finer on short lines).
POSITION_STEP = 0.1
#: Positions of a vehicle along a line, at most.
MAX_POSITIONS = 600
#: Step of a variable axle spacing [m].
SPACING_STEP = 0.5
#: Exact assignment of the loadings to the lanes up to this many lanes (greedy above).
EXACT_LANES = 6


@cache
def practice_table(name: str) -> Any:
    """SAEngine's practice table ``name`` (``movingLoads`` or ``bridgeDesign``), validated by the
    pack table's model."""
    from saengine.codes.merge import parse_table_file, strip
    from saengine.codes.tables import TABLE_MODELS

    raw = json.loads((PRACTICE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    data = strip(parse_table_file(raw).data)
    return TABLE_MODELS[name].model_validate(data)


@dataclass(frozen=True)
class Basis:
    """A table of the pack in force, or SAEngine's practice table when the pack has none."""

    table: Any
    practice: bool
    code: str

    def cite(self, key: str) -> str:
        clause = str((getattr(self.table, "clauses", None) or {}).get(key) or "")
        if not clause:
            return ""
        return clause if self.practice else f"{self.code} {clause}"

    @property
    def label(self) -> str:
        if self.practice:
            return f"SAEngine practice (HL-93 basis), not given by {self.code}"
        return self.code


def basis(name: str, pack: Any = None) -> Basis:
    """The pack's table ``name``, else SAEngine's practice table (named so)."""
    pack = pack or code_context.current()
    code = code_context.code_name(pack)
    if pack.has(name):
        return Basis(pack.table(name), False, code)
    return Basis(practice_table(name), True, code)


# ───────────────────────────────────── lanes and the dynamic allowance ─────────────────────


def lane_count(width: float, table: Any) -> int:
    """Design lanes on a carriageway ``width`` [m] wide: the table's count for a narrow one,
    else the whole lanes of its lane width (at least one)."""
    for limit, lanes in sorted(table.narrow):
        if width < limit:
            return max(1, int(lanes))
    return max(1, int(width // table.laneWidth))


def lane_width(width: float, table: Any) -> float:
    """The width of each lane [m]: the table's lane width, or the carriageway shared out when
    it has more lanes than whole lane widths."""
    n = lane_count(width, table)
    return min(float(table.laneWidth), width / n)


def dynamic_factor(table: Any, span: float, material: str = "concrete") -> tuple[float, str]:
    """(factor on the vehicles, how it was found) for a span ``span`` [m]."""
    rule = table.dynamic
    if rule.method == "included":
        return 1.0, "dynamic amplification included in the load model"
    if rule.method == "constant":
        return 1.0 + float(rule.constant), f"dynamic allowance {100 * rule.constant:.0f} %"
    ab = rule.formula.get(material) or next(iter(rule.formula.values()), None)
    if ab is None:
        return 1.0, "no dynamic allowance formula in the table"
    a, b = ab
    share = a / (b + span)
    if rule.cap is not None:
        share = min(share, float(rule.cap))
    return 1.0 + share, f"dynamic allowance {a:g} / ({b:g} + {span:.1f}) = {100 * share:.1f} %"


# ───────────────────────────────────── influence lines ─────────────────────────────────────


@dataclass
class LineInfluence:
    """Influence lines of a girder line: ``x`` the stations [m]; for a unit load (down) at
    station j: ``moment[s, j]`` the sagging moment at station s [kN·m/kN], ``shear_right[s, j]``
    and ``shear_left[s, j]`` the shear just right and left of it (V = dM/dx) and
    ``reaction[k, j]`` the upward reaction of support k (at station ``supports[k]``)."""

    x: np.ndarray
    supports: list[int]
    moment: np.ndarray
    shear_right: np.ndarray
    shear_left: np.ndarray
    reaction: np.ndarray


def stations(
    spans: list[float], max_step: float = 0.5, least: int = 10
) -> tuple[np.ndarray, list[int]]:
    """Stations along consecutive spans [m] and the indices of the support stations: each span
    in at least ``least`` equal elements, at most ``max_step`` long."""
    xs = [0.0]
    supports = [0]
    for span in spans:
        n = max(least, math.ceil(span / max_step))
        start = xs[-1]
        xs += [start + span * k / n for k in range(1, n + 1)]
        supports.append(len(xs) - 1)
    return np.array(xs), supports


def line_influence(spans: list[float], max_step: float = 0.5) -> LineInfluence:
    """The influence lines of a beam continuous over ``spans`` [m] on knife-edge supports
    (EI constant: the moments of a beam on rigid supports do not depend on it)."""
    from saengine.design.prestress import StripModel

    x, supports = stations(spans, max_step)
    n = len(x)
    model = StripModel(stations=x, fixed=list(supports))
    zero = np.zeros(n - 1)
    moment = np.zeros((n, n))
    for j in range(n):
        nodal = np.zeros(n)
        nodal[j] = -1.0  # a unit load down
        moment[:, j] = model.moments(zero, nodal)
    lengths = np.diff(x)
    element_shear = np.diff(moment, axis=0) / lengths[:, None]  # (n - 1, n)
    right = np.zeros((n, n))
    left = np.zeros((n, n))
    right[:-1] = element_shear
    left[1:] = element_shear
    reaction = np.zeros((len(supports), n))
    for k, s in enumerate(supports):
        reaction[k] = right[s] - left[s]
        reaction[k, s] += 1.0
    return LineInfluence(x, list(supports), moment, right, left, reaction)


def uniform_effects(spans: list[float], w: float, max_step: float = 0.5) -> dict[str, np.ndarray]:
    """The effects of a uniform load ``w`` [kN/m, down] over every span: sagging moments
    ``moment``, shears ``shearRight`` / ``shearLeft`` at the stations and the upward support
    ``reaction`` [kN, kN·m]."""
    from saengine.design.prestress import StripModel

    x, supports = stations(spans, max_step)
    model = StripModel(stations=x, fixed=list(supports))
    lengths = np.diff(x)
    m = model.moments(np.full(len(x) - 1, -w))
    v_start = np.diff(m) / lengths + w * lengths / 2  # shear just right of each element's start
    v_end = v_start - w * lengths
    right = np.append(v_start, 0.0)
    left = np.insert(v_end, 0, 0.0)
    reaction = np.array([right[s] - left[s] for s in supports])
    return {"x": x, "moment": m, "shearRight": right, "shearLeft": left, "reaction": reaction}


# ───────────────────────────────────── vehicles on a line ─────────────────────────────────


@dataclass(frozen=True)
class AxleGroup:
    """Axles behind the front one: their distances back [m] and loads [kN]."""

    offsets: np.ndarray
    loads: np.ndarray

    @property
    def length(self) -> float:
        return float(self.offsets[-1]) if len(self.offsets) else 0.0


def vehicle_groups(vehicle: Any, factor: float = 1.0) -> list[AxleGroup]:
    """Every arrangement of ``vehicle``'s axles (its variable spacings in steps)."""
    choices: list[list[float]] = []
    for axle in vehicle.axles:
        low = float(axle.spacing)
        high = float(axle.spacingMax) if axle.spacingMax else low
        steps = max(0, math.floor((high - low) / SPACING_STEP + 1e-9))
        values = [low + SPACING_STEP * k for k in range(steps + 1)]
        if values[-1] < high - 1e-9:
            values.append(high)
        choices.append(values)
    loads = np.array([float(a.load) * factor for a in vehicle.axles])
    groups = []
    for spacing in itertools.product(*choices):
        offsets = np.cumsum([0.0, *spacing[1:]])
        groups.append(AxleGroup(offsets, loads))
    return groups


def _with_second(groups: list[AxleGroup], gap: float, longest: float) -> list[AxleGroup]:
    """Two vehicles: each group followed by itself at ``gap`` and further gaps (1 m steps up to
    the line's length)."""
    out = []
    gaps = [gap + k for k in range(int(max(longest - gap, 0.0)) + 1)][:60]
    for group in groups:
        for g in gaps:
            second = group.offsets + group.length + g
            out.append(
                AxleGroup(
                    np.concatenate([group.offsets, second]), np.concatenate([group.loads] * 2)
                )
            )
    return out


def _vehicle_extremes(
    x: np.ndarray, il: np.ndarray, groups: list[AxleGroup]
) -> tuple[float, float]:
    """(largest, least) of Σ P·IL with every group moved along the line both ways."""
    span = float(x[-1] - x[0])
    longest = max((g.length for g in groups), default=0.0)
    step = max(POSITION_STEP, (span + 2 * longest) / MAX_POSITIONS)
    positions = np.arange(x[0] - longest, x[-1] + longest + step, step)
    high, low = 0.0, 0.0
    for group in groups:
        for sign in (1.0, -1.0):  # travelling towards -x or +x
            total = np.zeros(len(positions))
            for offset, load in zip(group.offsets, group.loads, strict=True):
                total += load * np.interp(positions + sign * offset, x, il, left=0.0, right=0.0)
            high = max(high, float(total.max()))
            low = min(low, float(total.min()))
    return high, low


def _area_extremes(x: np.ndarray, il: np.ndarray) -> tuple[float, float]:
    """(∫ of the positive parts, ∫ of the negative parts) of an influence line (refined so a
    change of sign within an element is integrated closely)."""
    fine = np.linspace(x[0], x[-1], max(4 * len(x), 200))
    values = np.interp(fine, x, il)
    positive = float(np.trapezoid(np.clip(values, 0.0, None), fine))
    negative = float(np.trapezoid(np.clip(values, None, 0.0), fine))
    return positive, negative


@dataclass
class LaneEffect:
    high: float
    low: float


def lane_extremes(
    x: np.ndarray,
    il_vehicle: np.ndarray,
    il_area: np.ndarray,
    loading: Any,
    table: Any,
    dynamic: float,
    width: float,
) -> LaneEffect:
    """The largest and least effect of one lane's ``loading`` on influence lines ``il_vehicle``
    (along its wheel lines) and ``il_area`` (across its width) [kN, kN·m]."""
    high = low = 0.0
    if loading.vehicle is not None:
        vehicle = table.vehicles[loading.vehicle]
        groups = vehicle_groups(vehicle, float(loading.vehicleFactor))
        if loading.secondGap is not None:
            groups = _with_second(groups, float(loading.secondGap), float(x[-1] - x[0]))
        factor = dynamic if loading.dynamic else 1.0
        v_high, v_low = _vehicle_extremes(x, il_vehicle, groups)
        high += factor * v_high
        low += factor * v_low
    w = (float(loading.lineLoad) + float(loading.areaLoad) * width) * float(loading.lineFactor)
    if w > 0:
        a_high, a_low = _area_extremes(x, il_area)
        high += w * a_high
        low += w * a_low
    return LaneEffect(high, low)


@dataclass
class Governing:
    """The extreme of an effect: its value [kN, kN·m], the load model and lanes that give it."""

    value: float = 0.0
    model: str = ""
    lanes: int = 0
    notes: list[str] = field(default_factory=list)


def _loading(model: Any, index: int) -> Any:
    return model.lanes[min(index, len(model.lanes) - 1)]


def _best(values: list[list[float]], count: int) -> float:
    """The largest sum of ``values[slot][loading]`` with loadings 0..count-1 on distinct slots
    (only favourable lanes: a slot giving less than nothing is left unloaded by taking fewer
    lanes)."""
    slots = len(values)
    if count > slots:
        return -math.inf
    if slots <= EXACT_LANES:
        best = -math.inf
        for chosen in itertools.permutations(range(slots), count):
            best = max(best, sum(values[s][t] for t, s in enumerate(chosen)))
        return best
    free = set(range(slots))
    total = 0.0
    for t in range(count):
        s = max(free, key=lambda k: values[k][t])
        total += values[s][t]
        free.discard(s)
    return total


Lane = tuple[np.ndarray, np.ndarray, np.ndarray, float, float]


def envelope(
    lanes: list[Lane],
    basis_: Basis,
    dynamic: float,
    hogging: tuple[bool, bool] = (False, False),
    models: list[str] | None = None,
    cache: dict[Any, LaneEffect] | None = None,
) -> tuple[Governing, Governing]:
    """The (largest, least) effect of the traffic: ``lanes`` the lane slots across the bridge,
    each (x, il_vehicle, il_area, lane width, scale): the influence lines along the lane and
    a factor on them (a girder's share of the lane, Courbon); ``hogging`` whether the largest
    and the least are effects a hogging-only model counts for; ``models`` the load model ids
    to use (all). ``cache``: the lanes' extremes kept between calls for the same influence
    lines (the scale applied afterwards)."""
    table = basis_.table
    high, low = Governing(), Governing()
    factors = list(table.multiplePresence)
    for key, model in table.loadModels.items():
        if models and key not in models:
            continue
        signs = [
            (sign, out)
            for sign, out in ((1.0, high), (-1.0, low))
            if model.only != "hogging" or hogging[0 if sign > 0 else 1]
        ]
        if not signs:
            continue
        loadings = min(len(lanes), model.maxLanes or len(lanes))
        found = [
            [
                _scaled(
                    _lane(cache, key, t, x, il_v, il_a, _loading(model, t), table, dynamic, width),
                    scale,
                )
                for t in range(loadings)
            ]
            for x, il_v, il_a, width, scale in lanes
        ]
        for sign, out in signs:
            per_slot = [[sign * (f.high if sign > 0 else f.low) for f in row] for row in found]
            for n in range(1, loadings + 1):
                total = _best(per_slot, n)
                if total == -math.inf:
                    continue
                m = factors[min(n, len(factors)) - 1] if model.multiplePresence else 1.0
                value = sign * m * total
                if sign * value > sign * out.value + 1e-9:
                    out.value, out.model, out.lanes = value, model.label, n
    return high, low


def _lane(
    cache: dict[Any, LaneEffect] | None,
    key: str,
    t: int,
    x: np.ndarray,
    il_v: np.ndarray,
    il_a: np.ndarray,
    loading: Any,
    table: Any,
    dynamic: float,
    width: float,
) -> LaneEffect:
    if cache is None:
        return lane_extremes(x, il_v, il_a, loading, table, dynamic, width)
    ref = (id(il_v), id(il_a), key, t, round(width, 6), round(dynamic, 9))
    found = cache.get(ref)
    if found is None:
        found = cache[ref] = lane_extremes(x, il_v, il_a, loading, table, dynamic, width)
    return found


def _scaled(effect: LaneEffect, scale: float) -> LaneEffect:
    """The extremes of ``scale`` × the influence lines."""
    if scale >= 0:
        return LaneEffect(scale * effect.high, scale * effect.low)
    return LaneEffect(scale * effect.low, scale * effect.high)


# ───────────────────────────────────── lanes across a deck ─────────────────────────────────


def lane_centres(carriageway: float, centre: float, table: Any) -> list[list[float]]:
    """The lane centres [m] across a carriageway centred on ``centre``: lanes side by side
    from the left kerb, and from the right kerb (two arrangements)."""
    n = lane_count(carriageway, table)
    w = lane_width(carriageway, table)
    left = centre - carriageway / 2
    right = centre + carriageway / 2
    from_left = [left + (k + 0.5) * w for k in range(n)]
    from_right = [right - (k + 0.5) * w for k in range(n)]
    return [from_left, from_right]


def courbon_share(y: float, girders: list[float]) -> list[float]:
    """Each girder's share of a unit load at ``y`` [m] across a rigid cross-section on girders
    at ``girders`` (Courbon): 1/n + e·yi / Σ yi², e and yi from the girders' centroid."""
    n = len(girders)
    centre = sum(girders) / n
    ys = [g - centre for g in girders]
    second = sum(v * v for v in ys)
    e = y - centre
    return [1.0 / n + (e * v / second if second > 0 else 0.0) for v in ys]

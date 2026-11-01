"""Flood and surge loads (load case Fa) and the stability of a building against them.

Every number comes from the code pack's ``flood`` table (:class:`saengine.codes.tables.
FloodTable`); a pack without it does not cover flood loads (:func:`covered`). The method:

- **Design depth** ``Hm`` (the hydrostatic depth above the ground): coastal sites take
  ``Hm = max(hs, hf)``, ``hs = hT - (x - 1) k`` the surge height at the distance x from the
  coast (x at least ``minDistance``) and ``hf = yT - yg`` the extreme surface water level above
  the ground; inland sites the flood level above the ground. The return period follows the
  occupancy category (``returnPeriod``; the water level column ``waterLevelReturnPeriod``).
  Surfaces exposed to free water take ``Hm + freeWaterIncrease``.
- **Hydrodynamic load** of moving water, up to ``hydrodynamic.maxVelocity``: the equivalent
  surcharge depth ``dh = a V² / 2g`` (a at least ``minDrag``), a uniform pressure ``γw dh``
  over the projected area to the depth Hm on the headwater side. Faster water needs a rational
  analysis: the surcharge is then still applied, as an estimate, with a warning.
- **Breaking waves** (coastal): ``ds = depthRatio × Hm``, ``Hb = heightRatio × ds``; on a dry
  floodproofed building's walls ``Ft = forceDynamic Cp γw ds² + forceStatic γw ds²`` per metre
  (``forceStaticWet`` with water behind), on the columns of a wet floodproofed one
  ``FD = 0.5 γw CD D Hb²`` each, at the still water level.
- **Debris impact** ``F = π W Vb CI CO CD CB Rmax / (2 g Δt)``, a concentrated load reported
  for the members at or below Hm.

The hydrostatic pressure on the walls (``γw Hm`` at the ground) balances around a closed
building, so the frame takes the net loads above (case Fa, in the wind's direction: the pack's
``withLateral``); the walls and the foundations take the pressure and the buoyancy
(:func:`saengine.substructure.loads.flood_uplift`).

Units: m, kN and kN/m² unless named otherwise (the impact force in N, as the code gives it).
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Any

from saengine.codes import context as code_context

#: The flood zones of Project Settings → Site → Flood and surge, by kind.
ZONE_KINDS = {"inland": "inland", "coastalRisk": "coastal", "coastalHighRisk": "coastal"}


class FloodNotCovered(ValueError):
    """The code pack in force has no flood provisions."""


def zone_kind(zone: str | None) -> str | None:
    """The kind of a flood zone the pack's flood combinations are keyed by (``coastal``,
    ``inland``), None outside a flood or surge zone."""
    return ZONE_KINDS.get(zone or "none")


def table() -> Any:
    """The pack's flood table; raises :class:`FloodNotCovered` without one."""
    try:
        pack = code_context.current()
        if pack.has("flood"):
            return pack.table("flood")
    except Exception:  # noqa: BLE001 - no pack machinery
        from saengine.codes.tables import builtin_table

        return builtin_table("flood")
    raise FloodNotCovered("the code pack in force has no flood and surge provisions")


def covered() -> bool:
    try:
        table()
    except FloodNotCovered:
        return False
    return True


def _interp(points: list[tuple[float, float]] | Any, x: float) -> float:
    """Linear between the points, held at the ends."""
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, x)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def return_period(category: str, data: Any | None = None) -> int:
    """Return period [years] of the flood values for an occupancy category."""
    data = data or table()
    return int(data.returnPeriod.get(category, max(data.returnPeriod.values())))


def water_level_period(category: str, data: Any | None = None) -> int:
    """The column of the extreme water level table an occupancy category reads (the pack's
    ``waterLevelReturnPeriod``, else :func:`return_period`)."""
    data = data or table()
    own = data.waterLevelReturnPeriod.get(category)
    return int(own) if own is not None else return_period(category, data)


def unit_weight(salt: bool, data: Any | None = None) -> float:
    """γw [kN/m³] of salt or fresh water."""
    data = data or table()
    return float(data.waterUnitWeight["salt" if salt else "fresh"])


def surge_height(region: str, distance: float, period: int, data: Any | None = None) -> float:
    """hs = hT - (x - 1) k [m] (not below 0) at ``distance`` [km] from the coast; x is at
    least the pack's ``minDistance``."""
    data = data or table()
    row = data.surgeRegions[region]
    h_t = float(row.height100 if period >= 100 else row.height50)
    x = max(float(distance), float(data.minDistance))
    return max(0.0, h_t - (x - float(data.minDistance)) * float(row.decay))


def water_level(station: str, period: int, data: Any | None = None) -> float:
    """yT [m above the datum] at a coastal location."""
    data = data or table()
    row = data.waterLevels[station]
    return float(row.level100 if period >= 100 else row.level50)


def wave_amplitude(hs: float, data: Any | None = None) -> float:
    """Local wave amplitude hw = waveShare × hs, at least ``minWave`` [m]."""
    hydro = (data or table()).hydrodynamic
    return max(float(hydro.waveShare) * hs, float(hydro.minWave))


def surcharge_depth(
    velocity: float, drag: float | None = None, data: Any | None = None
) -> tuple[float, list[str]]:
    """(dh = a V² / 2g [m], notes): ``drag`` a, at least the pack's least drag coefficient."""
    hydro = (data or table()).hydrodynamic
    notes = []
    a = float(drag) if drag is not None else float(hydro.minDrag)
    if a < float(hydro.minDrag):
        notes.append(f"drag coefficient a = {a:g} raised to the code's least {hydro.minDrag:g}")
        a = float(hydro.minDrag)
    if velocity > float(hydro.maxVelocity) + 1e-9:
        notes.append(
            f"water velocity {velocity:.2f} m/s is above {hydro.maxVelocity:g} m/s: the code asks "
            "for a rational analysis of the hydrodynamic load; the equivalent surcharge depth is "
            "applied as an estimate only"
        )
    return a * velocity**2 / (2 * float(hydro.gravity)), notes


def velocity_bounds(ds: float, data: Any | None = None) -> tuple[float, float]:
    """The code's estimate ds ≤ V ≤ √(g ds) of the water velocity [m/s] without site data."""
    g = float((data or table()).hydrodynamic.gravity)
    return ds, math.sqrt(g * max(ds, 0.0))


def still_water_depth(hm: float, data: Any | None = None) -> float:
    """ds = depthRatio × Hm [m]."""
    wave = (data or table()).breakingWave
    return float(wave.depthRatio) * hm if wave is not None else 0.0


def breaking_wave_height(ds: float, data: Any | None = None) -> float:
    """Hb = heightRatio × ds [m]."""
    wave = (data or table()).breakingWave
    return float(wave.heightRatio) * ds if wave is not None else 0.0


def breaking_wave_on_pile(
    hb: float, width: float, round_: bool, gamma: float, data: Any | None = None
) -> float:
    """FD = 0.5 γw CD D Hb² [kN] on a column of ``width`` [m] (a square one: D = squareWidth ×
    width)."""
    wave = (data or table()).breakingWave
    cd = float(wave.dragRound if round_ else wave.dragSquare)
    d = width if round_ else float(wave.squareWidth) * width
    return 0.5 * gamma * cd * d * hb**2


def breaking_wave_on_wall(
    ds: float, category: str, gamma: float, wet: bool = False, data: Any | None = None
) -> dict[str, float]:
    """{"Pmax": kN/m², "Ft": kN/m}: Pmax = Cp γw ds + staticFactor γw ds, Ft = forceDynamic Cp
    γw ds² + forceStatic γw ds² (``wet``: water behind the wall, forceStaticWet)."""
    wave = (data or table()).breakingWave
    cp = float(wave.dynamicPressure[category])
    static = float(wave.forceStaticWet if wet else wave.forceStatic)
    return {
        "Pmax": cp * gamma * ds + float(wave.staticFactor) * gamma * ds,
        "Ft": float(wave.forceDynamic) * cp * gamma * ds**2 + static * gamma * ds**2,
        "Cp": cp,
    }


def response_ratio(ratio: float, data: Any | None = None) -> float:
    """Rmax for the impulse duration / natural period ``ratio``."""
    return _interp((data or table()).impact.responseRatio, ratio)


def impact_force(
    velocity: float,
    category: str,
    depth: float,
    channel_width: float | None = None,
    period_ratio: float | None = None,
    data: Any | None = None,
) -> dict[str, float]:
    """Debris impact F = π W Vb CI CO CD CB Rmax / (2 g Δt) [N] with its coefficients;
    ``channel_width`` None: CB = 1 (no blockage reduction); ``period_ratio`` None: the largest
    Rmax of the table (the structure's period not known)."""
    data = data or table()
    imp = data.impact
    g = float(data.hydrodynamic.gravity)
    ci = float(imp.importance[category])
    cd = _interp(imp.depth, depth)
    cb = 1.0 if channel_width is None else _interp(imp.blockage, channel_width)
    rmax = (
        max(float(p[1]) for p in imp.responseRatio)
        if period_ratio is None
        else response_ratio(period_ratio, data)
    )
    force = (
        math.pi
        * float(imp.debrisWeight)
        * velocity
        * ci
        * float(imp.orientation)
        * cd
        * cb
        * rmax
        / (2 * g * float(imp.duration))
    )
    return {"F_N": force, "CI": ci, "CO": float(imp.orientation), "CD": cd, "CB": cb, "Rmax": rmax}


def breakaway_pressure(wind: float = 0.0, quake: float = 0.0, data: Any | None = None) -> float:
    """Design pressure [kN/m²] on a breakaway wall: the largest of the wind, the earthquake
    and the code's least pressure."""
    rule = (data or table()).breakaway
    return max(float(wind), float(quake), float(rule.minPressure) if rule else 0.0)


@dataclass
class FloodDepth:
    """The design flood at the site."""

    kind: str  # coastal | inland
    period: int
    hm: float  # design depth above the ground [m]
    hs: float | None = None  # surge height [m]
    hf: float | None = None  # extreme water level above the ground [m]
    gamma: float = 9.80  # kN/m³
    notes: list[str] = field(default_factory=list)


def design_depth(flood: Any, category: str, data: Any | None = None) -> FloodDepth | None:
    """The design depth Hm of the site's flood (Project Settings → Site → Flood and surge),
    None outside a flood zone or without the levels it needs (a note says which)."""
    kind = zone_kind(getattr(flood, "zone", None))
    if kind is None:
        return None
    data = data or table()
    period = return_period(category, data)
    salt = flood.saltWater if flood.saltWater is not None else kind == "coastal"
    gamma = unit_weight(bool(salt), data)
    notes: list[str] = []
    ground = flood.groundLevel
    if kind == "inland":
        if flood.floodLevel is None or ground is None:
            missing = (
                f"flood: an inland site needs the {period}-year flood level and the ground "
                "level (Site → Flood and surge); no flood load"
            )
            return FloodDepth(kind, period, 0.0, gamma=gamma, notes=[missing])
        hm = max(0.0, float(flood.floodLevel) - float(ground))
        return FloodDepth(kind, period, hm, hf=hm, gamma=gamma, notes=notes)
    hs: float | None = None
    if flood.surgeHeight is not None:
        hs = float(flood.surgeHeight)
    elif flood.surgeRegion is not None:
        hs = surge_height(flood.surgeRegion, flood.distance or 0.0, period, data)
    hf: float | None = None
    level_period = water_level_period(category, data)
    if ground is not None:
        if flood.floodLevel is not None:
            hf = max(0.0, float(flood.floodLevel) - float(ground))
        elif flood.waterLevelStation is not None:
            hf = max(0.0, water_level(flood.waterLevelStation, level_period, data) - float(ground))
    if hs is None and hf is None:
        missing = (
            "flood: a coastal site needs its coastal region (or a surge height) or the ground "
            "level with a water level location (Site → Flood and surge); no flood load"
        )
        return FloodDepth(kind, period, 0.0, gamma=gamma, notes=[missing])
    if hf is None:
        notes.append(
            "flood: no ground level, so the extreme water level hf is not compared; Hm = hs"
        )
    if level_period != period and hf is not None and flood.floodLevel is None:
        notes.append(
            f"flood: the {level_period}-year extreme water level is read for category "
            f"{category} ({data.notes.get('waterLevelReturnPeriod', '')})"
        )
    hm = max(v for v in (hs, hf) if v is not None)
    return FloodDepth(kind, period, hm, hs=hs, hf=hf, gamma=gamma, notes=notes)


def band_shares(rel: list[float], top: float) -> tuple[list[float], float]:
    """The length [m] of the band [0, ``top``] each level at heights ``rel`` (above the
    ground, ascending) takes, a level its half storeys below and above, and the length the
    ground (the supports) takes below the first level's half storey."""
    if not rel:
        return [], max(0.0, top)
    shares = []
    for i, z in enumerate(rel):
        low = z / 2 if i == 0 else (rel[i - 1] + z) / 2
        high = (z + rel[i + 1]) / 2 if i + 1 < len(rel) else math.inf
        shares.append(max(0.0, min(top, high) - max(0.0, low)))
    return shares, max(0.0, min(top, rel[0] / 2))


def point_shares(rel: list[float], z: float) -> tuple[list[float], float]:
    """A unit force at height ``z`` shared by the lever rule between the levels just below and
    above it (the ground below the first): (share of each level, share of the ground)."""
    shares = [0.0] * len(rel)
    if not rel or z <= 0:
        return shares, 1.0
    if z >= rel[-1]:
        shares[-1] = 1.0
        return shares, 0.0
    i = bisect.bisect_left(rel, z)
    low = rel[i - 1] if i > 0 else 0.0
    t = (z - low) / (rel[i] - low) if rel[i] > low else 1.0
    shares[i] = t
    if i > 0:
        shares[i - 1] += 1 - t
        return shares, 0.0
    return shares, 1 - t


@dataclass
class FloodLoads:
    """Fa along one plan axis: the forces at the levels [kN], what goes straight into the
    ground, and how they were formed."""

    axis: int
    level_forces: list[float]
    ground: float
    rows: list[dict[str, Any]]


def flood_loads(
    flood: Any,
    category: str,
    rel: list[float],
    widths: dict[int, list[float]],
    columns: list[tuple[float, float, float, bool]] | None = None,
    data: Any | None = None,
) -> tuple[FloodDepth | None, list[FloodLoads], dict[str, Any], list[str]]:
    """The flood load case Fa along X and Y: (the design flood, the loads per axis, the
    summary, notes). ``rel``: the levels' heights above the ground [m], ascending;
    ``widths``: per axis (0: flow along X) the width of each level across the flow [m];
    ``columns``: (bottom, top above the ground [m], width [m], round) of each column, for the
    breaking waves on a wet floodproofed building. The hydrodynamic and the breaking wave
    loads are added (on the safe side: the code gives no rule for taking them together)."""
    data = data or table()
    depth = design_depth(flood, category, data)
    if depth is None:
        return None, [], {}, []
    notes = list(depth.notes)
    summary: dict[str, Any] = {
        "zone": flood.zone,
        "kind": depth.kind,
        "period": depth.period,
        "Hm_m": depth.hm,
        "hs_m": depth.hs,
        "hf_m": depth.hf,
        "gamma_kNm3": depth.gamma,
        "freeWaterDepth_m": depth.hm + float(data.freeWaterIncrease),
        "source": data.source,
        "sources": dict(data.sources),
    }
    if depth.hm <= 0:
        return depth, [], summary, notes
    gamma = depth.gamma
    summary["hydrostaticBase_kPa"] = gamma * (depth.hm + float(data.freeWaterIncrease))
    # The moving water: the equivalent surcharge depth dh.
    ds = still_water_depth(depth.hm, data) if depth.kind == "coastal" else depth.hm
    velocity = flood.velocity
    if velocity is None and depth.kind == "coastal":
        velocity = velocity_bounds(ds, data)[1]
        notes.append(
            f"flood: no water velocity given; the code's upper estimate √(g ds) = "
            f"{velocity:.2f} m/s is used (ds = {ds:.2f} m)"
        )
    dh = 0.0
    if velocity:
        dh, dh_notes = surcharge_depth(float(velocity), flood.dragCoefficient, data)
        notes += [f"flood: {n}" for n in dh_notes]
        summary["velocity_ms"] = float(velocity)
        summary["dh_m"] = dh
    elif depth.kind == "inland":
        notes.append(
            "flood: inland, still water: the hydrostatic pressure balances around the building "
            "(walls and foundations take it); enter a water velocity for moving water, and the "
            "site's wave amplitude for a river-side site (Exposure C) needs site-specific data"
        )
    pressure = gamma * dh  # kN/m², uniform to the depth Hm on the headwater side
    summary["dynamicPressure_kPa"] = pressure
    # Breaking waves (coastal): on the walls of a dry building, on the columns of a wet one.
    wave = None
    if depth.kind == "coastal" and data.breakingWave is not None:
        hb = breaking_wave_height(ds, data)
        wave = {"ds_m": ds, "Hb_m": hb, "hw_m": wave_amplitude(depth.hs or depth.hm, data)}
        if not flood.floodOpenings:
            wave.update(breaking_wave_on_wall(ds, category, gamma, wet=False, data=data))
        summary["breakingWave"] = wave
    if data.impact is not None and velocity:
        summary["impact"] = impact_force(
            float(velocity), category, depth.hm, flood.channelWidth, None, data
        )
        notes.append(
            f"flood: debris impact {summary['impact']['F_N'] / 1e3:.1f} kN as a concentrated "
            "load at the most critical place at or below Hm on the members facing the flow "
            "(reported; the largest response ratio of the table is taken)"
        )
    loads: list[FloodLoads] = []
    bands, below = band_shares(rel, depth.hm)
    wave_shares, wave_ground = point_shares(rel, ds)
    for axis in (0, 1):
        width = widths.get(axis) or [0.0] * len(rel)
        forces = [pressure * w * b for w, b in zip(width, bands, strict=True)]
        ground = pressure * (width[0] if width else 0.0) * below
        rows = [
            {"z_m": z, "band_m": b, "width_m": w, "dynamic_kN": f}
            for z, b, w, f in zip(rel, bands, width, forces, strict=True)
        ]
        wave_total = 0.0
        if wave is not None:
            if flood.floodOpenings:
                hit = [c for c in columns or [] if c[0] <= ds <= c[1]]
                wave_total = sum(
                    breaking_wave_on_pile(wave["Hb_m"], c[2], c[3], gamma, data) for c in hit
                )
                wave[f"columns{'XY'[axis]}"] = len(hit)
            else:
                wave_total = float(wave["Ft"]) * (width[0] if width else 0.0)
            for i, share in enumerate(wave_shares):
                forces[i] += wave_total * share
                rows[i]["wave_kN"] = wave_total * share
            ground += wave_total * wave_ground
        loads.append(FloodLoads(axis, forces, ground, rows))
        summary[f"total{'XY'[axis]}_kN"] = sum(forces) + ground
        summary[f"ground{'XY'[axis]}_kN"] = ground
    if wave is not None and flood.floodOpenings:
        notes.append(
            "flood: breaking waves on every column that crosses the still water level (no "
            "shielding by the columns in front)"
        )
    return depth, loads, summary, notes


def stability(
    lateral: dict[int, list[tuple[float, float]]],
    dead: float,
    lever: dict[int, float],
    data: Any | None = None,
) -> list[dict[str, Any]]:
    """Overturning and sliding under the wind and the flood together, dead load only: per axis
    ``lateral`` [(force kN, height m)], ``dead`` the dead load [kN], ``lever`` the least lever
    arm of the dead load about the edge [m]. Overturning: FS = D × lever / ΣF z; sliding: the
    friction coefficient the foundations must give, μ = FS × ΣF / D."""
    factor = float((data or table()).stabilityFactor)
    rows = []
    for axis, forces in lateral.items():
        moment = sum(f * z for f, z in forces)
        total = sum(f for f, _ in forces)
        if total <= 0:
            continue
        resisting = dead * lever.get(axis, 0.0)
        ratio = resisting / moment if moment > 0 else math.inf
        rows.append(
            {
                "direction": "XY"[axis],
                "lateral_kN": total,
                "overturning_kNm": moment,
                "resisting_kNm": resisting,
                "factor": ratio,
                "required": factor,
                "ok": ratio >= factor - 1e-9,
                "slidingFriction": factor * total / dead if dead > 0 else math.inf,
            }
        )
    return rows


__all__ = [
    "FloodDepth",
    "FloodLoads",
    "FloodNotCovered",
    "band_shares",
    "breakaway_pressure",
    "breaking_wave_height",
    "breaking_wave_on_pile",
    "breaking_wave_on_wall",
    "covered",
    "design_depth",
    "flood_loads",
    "impact_force",
    "point_shares",
    "response_ratio",
    "return_period",
    "stability",
    "still_water_depth",
    "surcharge_depth",
    "surge_height",
    "table",
    "unit_weight",
    "velocity_bounds",
    "water_level",
    "water_level_period",
    "wave_amplitude",
    "zone_kind",
]

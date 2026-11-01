"""The geotechnical rules of shallow foundations, read from the code pack in force.

Every number comes from the pack's ``foundations.shallow`` group (:class:`saengine.codes.tables.
ShallowFoundations`) and every clause from its ``sources``; a pack without the group does not
cover these rules (:func:`rules` returns None) and the footings keep the engine's general
checks only. This module turns the rules into what the designs use:

- the load combinations of the bearing pressure, of stability (overturning and sliding) and of
  the settlement (:func:`footing_combinations`), formed from the analysed cases: D stands for
  the dead cases D and SD, L for the live cases L and Lr, W and E for each direction and sign
  (and each design wind load case), B for the buoyancy of the water at the base, which the
  footing's design applies itself;
- the allowable increase with wind or earthquake (:func:`allowed`);
- the presumptive allowable bearing pressure of a soil row (:func:`presumptive`);
- the indicative modulus of subgrade reaction (:func:`subgrade_modulus`);
- the permissible total, differential settlement and angular distortion of a type of
  structure (:func:`settlement_limit`; load-bearing wall rows interpolated in L/H);
- the checks of the founding depth, the least thickness, the distance to a slope and the force
  transfer at the column base (bearing on the footing concrete and the dowels).

Units: mm, N, MPa inside; kPa for soil pressures.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from saengine.codes import context as code_context
from saengine.design.check import _check

#: A combination named with wind or earthquake (WX, WTY, EX, ...).
LATERAL = re.compile(r"\b[\d.]*(W|E)T?[XY]\b")
#: The pseudo-case of the buoyancy pressure in the pack's combinations.
BUOYANCY = "B"


def rules() -> Any | None:
    """The pack's ``foundations.shallow`` group, or None when the pack does not cover it."""
    pack = code_context.current()
    table = None
    if pack.has("foundations"):
        table = pack.table("foundations")
    if table is None or getattr(table, "shallow", None) is None:
        from saengine.codes.registry import DEFAULT_PACK
        from saengine.codes.tables import builtin_table

        if pack.id != DEFAULT_PACK:
            return None
        table = builtin_table("foundations", DEFAULT_PACK)
    return table.shallow


def clause(key: str) -> str:
    """The clause of ``shallow.<key>`` from the pack's sources (empty when none)."""
    pack = code_context.current()
    try:
        table = pack.table("foundations")
    except Exception:  # noqa: BLE001 - a pack without the table names no clause
        return ""
    return table.sources.get(f"shallow.{key}", "")


def source(key: str) -> str:
    """The clause ``key`` of the pack's ``foundations`` sources (empty when none)."""
    pack = code_context.current()
    try:
        table = pack.table("foundations")
    except Exception:  # noqa: BLE001 - a pack without the table names no clause
        return ""
    return (getattr(table, "sources", None) or {}).get(key, "")


def cite(key: str, default: str = "") -> str:
    """The reference of ``foundations`` source ``key`` without its summary (the text before
    the first colon); ``default`` when the pack names none."""
    text = source(key)
    return text.split(":")[0].strip() if text else default


def foundations_value(name: str) -> Any | None:
    """The pack's ``foundations.<name>`` (None when the pack has no such value)."""
    pack = code_context.current()
    try:
        table = pack.table("foundations")
    except Exception:  # noqa: BLE001 - a pack without the table covers none of it
        return None
    return getattr(table, name, None)


def code_name() -> str:
    pack = code_context.current()
    return pack.name or pack.id


def not_covered(what: str) -> str:
    return f"{what}: not covered by the code pack {code_name()}"


# ─────────────────────────────────────────── combinations ───────────────────────────────────


@dataclass
class FootingCombinations:
    """The combinations of the footings' geotechnical checks: (name, {case: factor}) with the
    buoyancy factor of each in ``buoyancy`` (by name; B is not a case of the analysis)."""

    bearing: list[tuple[str, dict[str, float]]]
    stability: list[tuple[str, dict[str, float]]]
    settlement: dict[str, tuple[str, dict[str, float]]]
    buoyancy: dict[str, float]
    sources: dict[str, str]


def _expand(
    combination: Any, cases: set[str], strength_level_wind: bool
) -> list[tuple[str, dict[str, float]]]:
    """One pack combination over the analysed ``cases``: each lateral term in ±X and ±Y (wind
    for each design wind load case); [] when it needs a case that was not analysed."""
    from saengine.substructure.loads import _wind_variants

    base: dict[str, float] = {}
    lateral: list[tuple[str, float]] = []
    for term, factor in combination.factors.items():
        if term == "D":
            dead = [c for c in ("D", "SD") if c in cases]
            if not dead:
                return []
            base.update(dict.fromkeys(dead, factor))
        elif term == "L":
            base.update({c: factor for c in ("L", "Lr") if c in cases})
        elif term in ("W", "E"):
            lateral.append((term, factor * (0.6 if term == "W" and strength_level_wind else 1)))
        elif term == BUOYANCY:
            continue
        elif term in cases:
            base[term] = factor
    if "H" in cases:
        base["H"] = 1.0
    if not lateral:
        return [(combination.name, base)]
    variants = _wind_variants(cases)
    out: list[tuple[str, dict[str, float]]] = []
    for term, factor in lateral:
        for axis in ("X", "Y"):
            case = f"{term}{axis}"
            if case not in cases:
                continue
            for sign in (1.0, -1.0):
                shapes = variants(case, sign) if term == "W" else [("", {case: sign})]
                for label, shape in shapes:
                    factors = dict(base)
                    for c, f in shape.items():
                        factors[c] = factors.get(c, 0.0) + factor * f
                    name = combination.name.replace(term, f"{'-' if sign < 0 else ''}{case}")
                    out.append((name + (f" [{label}]" if label else ""), factors))
    return out


def footing_combinations(
    cases: set[str] | dict[str, Any], strength_level_wind: bool = False
) -> FootingCombinations | None:
    """The pack's combinations of shallow foundations over the analysed ``cases``; None when
    the pack does not cover them."""
    found = rules()
    if found is None:
        return None
    cases = set(cases)
    buoyancy: dict[str, float] = {}
    sources: dict[str, str] = {}

    def form(rows: list[Any]) -> list[tuple[str, dict[str, float]]]:
        out = []
        for row in rows:
            for name, factors in _expand(row, cases, strength_level_wind):
                if row.factors.get(BUOYANCY):
                    buoyancy[name] = row.factors[BUOYANCY]
                sources[name] = row.source or ""
                out.append((name, factors))
        return out

    settlement = {}
    for soil, row in found.settlementCombinations.items():
        formed = _expand(row, cases, False)
        if formed:
            settlement[soil] = formed[0]
            sources[formed[0][0]] = row.source or ""
    return FootingCombinations(
        form(found.bearingCombinations),
        form(found.stabilityCombinations),
        settlement,
        buoyancy,
        sources,
    )


def is_lateral(name: str) -> bool:
    return bool(LATERAL.search(name))


def allowed(qa: float, name: str) -> tuple[float, str]:
    """qa [any unit] allowed under combination ``name`` and why: × the pack's lateral increase
    with wind or earthquake, as is for gravity alone."""
    found = rules()
    if found is None or not is_lateral(name) or found.lateralIncrease <= 1:
        return qa, ""
    increase = found.lateralIncrease
    return qa * increase, (
        f"qa × {increase:g} with wind or earthquake ({clause('lateralIncrease') or code_name()})"
    )


# ─────────────────────────────────────────── values ─────────────────────────────────────────


def presumptive(row_id: str, water_depth: float | None, least_side: float) -> tuple[float, str]:
    """The presumptive allowable bearing pressure [kPa] of the pack's row ``row_id`` and a note;
    ``water_depth`` [mm] of the water table below the base (negative: above it; None: not
    known), ``least_side`` [mm] of the foundation. Raises ``ValueError`` for a row without a
    value (organic soil, fill: by investigation) or an unknown row."""
    found = rules()
    if found is None:
        raise ValueError(not_covered("Presumptive bearing values"))
    row = next((r for r in found.presumptive if r.id == row_id), None)
    if row is None:
        raise ValueError(f"no presumptive bearing row '{row_id}' in {code_name()}")
    if row.qa is None:
        raise ValueError(f"{row.name}: no presumptive value, to be found by investigation")
    qa, note = row.qa, f"presumptive qa {row.qa:g} kPa for {row.name.lower()}"
    if row.waterReduction:
        share = found.presumptiveWaterReduction
        if water_depth is None:
            qa *= share
            note += f", × {share:g} as the water table is not known"
        elif water_depth <= least_side:
            qa *= share
            note += f", × {share:g} with the water table within B of the base"
    return qa, f"{note} ({clause('presumptive')})"


def subgrade_modulus(
    behaviour: str, value: float, submerged: bool = False
) -> tuple[float, float, str] | None:
    """The indicative modulus of subgrade reaction (low, high) [kN/m³] of a 300 mm plate: a
    granular soil by its SPT N, a cohesive one by its unconfined compressive strength qu [kPa];
    None outside the table (a cohesive soil softer than its first row)."""
    found = rules()
    if found is None:
        return None
    rows = found.subgrade.get("cohesive" if behaviour == "cohesive" else "granular", [])
    for row in rows:
        if value >= row.low and (row.high is None or value < row.high):
            k = row.submerged if submerged and row.submerged is not None else row.k
            low, high = k
            if row.high is not None and high > low:
                share = (value - row.low) / (row.high - row.low)
                return low, high, f"{row.name}: {low + share * (high - low):.0f} kN/m³"
            return low, high, f"{row.name}: {low:.0f}-{high:.0f} kN/m³"
    return None


def structure_rows() -> list[Any]:
    found = rules()
    return list(found.settlementLimits) if found is not None else []


def settlement_limit(
    structure: str, foundation: str, soil: str, length_height: float | None = None
) -> tuple[Any, str] | None:
    """(limits, the row's name) of Table 6.3.8-like ``settlementLimits`` for a type of
    structure, foundation ("isolated" or "raft") and soil column ("sand" or "plasticClay").
    A load-bearing wall type (rows with ``lengthHeight``) is interpolated in L/H between its
    rows (clamped at the ends). None when the pack or the row has no value."""
    from saengine.codes.tables import SettlementLimit

    rows = structure_rows()
    walls = [r for r in rows if r.lengthHeight is not None and r.id.startswith(structure)]
    if walls and len(walls) > 1:
        walls.sort(key=lambda r: r.lengthHeight)
        ratio = length_height if length_height is not None else walls[0].lengthHeight
        ratio = min(max(ratio, walls[0].lengthHeight), walls[-1].lengthHeight)
        for a, b in pairwise(walls):
            if a.lengthHeight <= ratio <= b.lengthHeight:
                la, lb = getattr(a, foundation).get(soil), getattr(b, foundation).get(soil)
                if la is None or lb is None:
                    return None
                t = (ratio - a.lengthHeight) / (b.lengthHeight - a.lengthHeight)

                def mix(x: float, y: float, t: float = t) -> float:
                    return x + t * (y - x)

                limit = SettlementLimit(
                    total=mix(la.total, lb.total),
                    differential=mix(la.differential, lb.differential),
                    angular=mix(la.angular, lb.angular),
                )
                return limit, f"load bearing walls, L/H = {ratio:g}"
    row = next((r for r in rows if r.id == structure), None)
    if row is None:
        return None
    limit = getattr(row, foundation).get(soil)
    return (limit, row.name) if limit is not None else None


# ─────────────────────────────────────────── checks ─────────────────────────────────────────


def depth_check(
    owner: str,
    depth: float,
    exterior: bool,
    soil: str | None,
    temporary: bool = False,
    raft: bool = False,
) -> list[dict[str, Any]]:
    """The founding depth [mm] below the natural ground against the pack's least depths: every
    footing, and exterior footings (rafts) by the soil at the founding level ("cohesive" or
    "granular"; None: not known, the greater is taken)."""
    found = rules()
    if found is None:
        return []
    checks = [
        _check(
            "Founding depth",
            found.minDepth,
            depth,
            "mm",
            None,
            f"Df below the natural ground at least {found.minDepth:g} mm ({clause('minDepth')})",
            utilisation=found.minDepth / max(depth, 1e-6),
        )
    ]
    if not (exterior or raft):
        return checks
    table = found.raftDepth if raft else found.exteriorDepth
    if temporary and not raft:
        least, why = table["temporary"], "a temporary structure"
    elif soil in ("cohesive", "granular"):
        least = table[soil]
        why = f"{'cohesive' if soil == 'cohesive' else 'cohesionless'} soil at the base"
    else:
        least = max(table["cohesive"], table["granular"])
        why = "soil at the base not known: the greater value"
    what = "Raft depth" if raft else "Exterior footing depth"
    key = "raftDepth" if raft else "exteriorDepth"
    checks.append(
        _check(
            what,
            least,
            depth,
            "mm",
            None,
            f"Df at least {least:g} mm, {why}; more on expansive soil ({clause(key)})",
            utilisation=least / max(depth, 1e-6),
        )
    )
    return checks


def thickness_check(owner: str, depth_above_bars: float, on_piles: bool = False) -> dict | None:
    """The depth of a reinforced footing above its bottom bars [mm] against the pack's least."""
    found = rules()
    if found is None:
        return None
    least = found.minThickness["piles" if on_piles else "soil"]
    return _check(
        "Depth above the bottom bars",
        least,
        depth_above_bars,
        "mm",
        None,
        f"at least {least:g} mm {'on piles' if on_piles else 'on soil'} ({clause('minThickness')})",
        utilisation=least / max(depth_above_bars, 1e-6),
    )


def slope_check(width: float, distance: float) -> dict | None:
    """The distance [mm] from a footing's centre to the slope face at its base level against
    the pack's multiple of the footing width."""
    found = rules()
    if found is None:
        return None
    least = found.slopeDistance * width
    return _check(
        "Distance to the slope face",
        least,
        distance,
        "mm",
        None,
        f"at least {found.slopeDistance:g} B = {least:.0f} mm ({clause('slopeDistance')})",
        utilisation=least / max(distance, 1e-6),
    )


def spread_check(material: str, projection: float, depth: float) -> dict | None:
    """The load spread of a plain footing (``material`` a key of ``spreadAngle``): its
    projection beyond the wall or column face [mm] over its depth [mm]."""
    found = rules()
    if found is None or material not in found.spreadAngle:
        return None
    ratio = found.spreadAngle[material]
    return _check(
        "Angle of load spread",
        projection / max(depth, 1e-6),
        ratio,
        "H/V",
        None,
        f"{material}: at most {ratio:.2f} horizontal to 1 vertical ({clause('spreadAngle')})",
    )


def column_base_checks(
    column: str,
    pu: float,
    side_u: float,
    side_v: float,
    fc_column: float,
    fc_footing: float,
    a2: float,
    bars_area: float | None,
    bars_count: int | None,
    fy: float,
    combination: str,
) -> list[dict[str, Any]]:
    """The force transfer at the base of a column under its largest factored axial load
    ``pu`` [N]: the bearing strength φ (k f'c) A1 of the column concrete and φ (k f'c) A1
    √(A2/A1) of the footing (√ at most ``areaRatioMax``), A1 the column's area and A2 the
    largest area of the footing's top concentric with it [mm²]; and the bars across the
    interface (the column's bars carried down, or dowels: ``bars_area`` [mm²] and
    ``bars_count``; None: not known) against the larger of ``dowelRatio`` Ag and the
    compression beyond the bearing strength, (Pu - φBn) / (φ fy)."""
    found = rules()
    if found is None:
        return []
    base = found.columnBase
    a1 = side_u * side_v
    ratio = min(math.sqrt(max(a2, a1) / a1), base.areaRatioMax)
    column_strength = base.phi * base.bearing * fc_column * a1
    footing_strength = base.phi * base.bearing * fc_footing * a1 * ratio
    strength = min(column_strength, footing_strength)
    where = clause("columnBase")
    excess = max(pu - strength, 0.0)
    need_excess = excess / (base.phi * fy) if fy > 0 else 0.0
    checks = [
        _check(
            f"Bearing at the base of {column}",
            pu / 1e3,
            strength / 1e3,
            "kN",
            combination,
            f"φ {base.bearing:g} f'c A1: column {column_strength / 1e3:.0f} kN, footing "
            f"{footing_strength / 1e3:.0f} kN with √(A2/A1) = {ratio:.2f} (at most "
            f"{base.areaRatioMax:g}), φ = {base.phi:g}; the bars across carry any excess "
            f"({where})",
            flag=True,
        )
    ]
    least = max(base.dowelRatio * a1, need_excess)
    why = f"at least {base.dowelRatio:g} Ag = {base.dowelRatio * a1:.0f} mm²"
    if need_excess > 0:
        why += f" and (Pu - φBn) / (φ fy) = {need_excess:.0f} mm²"
    if bars_area is None:
        checks.append(
            _check(
                f"Bars across the base of {column}",
                least,
                0.0,
                "mm²",
                combination,
                f"{why}, at least {base.minBars} bars: give the column's bars (carried into the "
                f"footing) or dowels no larger than the column bars ({where})",
                flag=True,
                utilisation=0.0,
            )
        )
        return checks
    note = f"{why}, at least {base.minBars} bars; dowels no larger than the column bars ({where})"
    utilisation = least / max(bars_area, 1e-6)
    if bars_count is not None and bars_count < base.minBars:
        utilisation = max(utilisation, base.minBars / max(bars_count, 1))
        note += f"; only {bars_count} bars"
    checks.append(
        _check(
            f"Bars across the base of {column}",
            least,
            bars_area,
            "mm²",
            combination,
            note,
            utilisation=utilisation,
        )
    )
    return checks


def overturning_check(
    combination: str, eu: float, ev: float, length: float, width: float
) -> dict[str, Any] | None:
    """FS against overturning of a footing about its edges under a vertical resultant at
    (eu, ev) [mm]: (P B/2) / (P e) = B / (2 e) in each direction, the lesser."""
    found = rules()
    if found is None:
        return None
    fs_u = length / (2 * abs(eu)) if abs(eu) > 1e-9 else 99.0
    fs_v = width / (2 * abs(ev)) if abs(ev) > 1e-9 else 99.0
    fs = min(fs_u, fs_v, 99.0)
    return _check(
        "Overturning (service)",
        found.overturning,
        fs,
        "FS",
        combination,
        f"FS = B / (2 e): {fs_u:.2f} along X, {fs_v:.2f} along Y (the dead load resisting) "
        f"({clause('overturning')})",
        utilisation=found.overturning / max(fs, 1e-6),
    )


def sliding_check(
    combination: str, horizontal: float, vertical: float, tied: bool, friction: float | None
) -> dict[str, Any] | None:
    """FS against sliding of a footing: μ V / H with the pack's friction factor (or a verified
    ``friction``), passive resistance not counted. A footing tied to others slides with the
    building: reported only (``flag``)."""
    found = rules()
    if found is None:
        return None
    mu = friction if friction is not None else found.friction
    resisting = mu * max(vertical, 0.0)
    fs = min(resisting / horizontal, 99.0) if horizontal > 1e-9 else 99.0
    note = (
        f"FS = μ V / H = {mu:g} × {vertical / 1e3:.0f} / {horizontal / 1e3:.0f} kN, passive "
        f"resistance not counted ({clause('sliding')})"
    )
    if tied:
        note += "; tied to other foundations: they slide together (see the building's check)"
    return _check(
        "Sliding (service)",
        found.sliding,
        fs,
        "FS",
        combination,
        note,
        flag=tied,
        utilisation=found.sliding / max(fs, 1e-6),
    )


def kern_check(combination: str, eu: float, ev: float, length: float, width: float) -> dict:
    """The resultant within the pack's kern share of the base (preferably: reported only)."""
    found = rules()
    share = found.kern if found is not None else 1 / 6
    ratio = abs(eu) / length + abs(ev) / width
    return _check(
        "Resultant within B/6 (service)",
        ratio,
        share,
        "e/B",
        combination,
        f"eu/L + ev/B ≤ {share:.3f}, preferably ({clause('kern') or 'the kern'})",
        flag=True,
    )

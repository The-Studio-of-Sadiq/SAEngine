"""Crane runway loads, the moving crane load cases and the runway beam checks (Project
Settings → Crane runways).

Crane loads (the factors, clauses and labels are the code pack's ``cranes`` table; with the
default pack, Part 6 Sec 2.3.12 Table 6.2.6 row 5 and Sec 1.6.6(i)):

- maximum wheel loads: the bridge's weight shared by the two rails, plus the rated capacity
  and the hoist and trolley with the trolley at its closest approach to a rail (statics of the
  bridge as a simple beam between the rails), shared equally by the wheels on that rail;
- vertical impact: the maximum wheel loads times (1 + impact), impact by kind of crane;
- transverse (lateral) force: a share of the lifted load plus the trolley and hoist, at the top
  of the rails, half on each runway, either direction;
- longitudinal force: a share of the maximum wheel loads, at the top of each rail;
- the horizontal forces scaled by kind of crane (``horizontalScale``: manually operated cranes).

Runway beams are taken simply supported between the columns. The wheels of one rail
(``wheels`` at ``wheelBase``) roll along it: the largest moment is under a wheel, found by
moving the group along the span; the largest end shear with the leading wheel at the support;
the largest column reaction with the group placed for it.

Moving crane load cases (:func:`crane_load_cases`): with the runway's direction and its two
column lines given, the columns on the lines get a node at the rail level
(:func:`bracket_points`), and for each column position along the runway and each trolley side
three cases are formed: the vertical wheel loads with impact (and the moment of the bracket
eccentricity, the rails being centred between the column lines), the transverse force and the
longitudinal force, each wheel's load shared by the two columns of its runway beam span. The
code pack's ``combination`` rule says which act together (:func:`saengine.fem.combinations.
crane_combinations`).

The runway beam check (``beamType``, a steel beam type) reuses the steel member design
(:mod:`saengine.design.steel.members`): factored moments from the dead load of the beam and the
crane loads as live load (the code pack's strength combination with the largest live load
factor), major-axis flexure with the top flange unbraced over the span (Cb = 1), the lateral
moment on the top flange alone (its plastic modulus tf·bf²/4: the usual assumption that the top
flange resists the lateral load), their interaction and web shear. With a fatigue stress
category and cycles per day, the fatigue check of the code pack's ``fatigue`` table
(:mod:`saengine.design.steel.fatigue`) on the service stress ranges of the bottom flange
(vertical wheel loads with impact) and the top flange tip (vertical plus the transverse force
either way). Deflections are reported, not checked.

Not covered: the rail's own bending, web crippling under the wheels, several cranes on one
runway acting together, the crane's weight in the seismic mass, and the crane cases in the
response spectrum combinations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.codes import context as code_context

G = 9.80665
#: A column is on a runway's column line when its centre is this close to it [mm].
LINE_TOLERANCE = 10.0
#: Crane load case codes: C<crane><part><position><side> (``C1V3a``).
PARTS = {"V": "vertical with impact", "T": "transverse", "B": "longitudinal"}


@dataclass
class WheelLoads:
    """Crane loads on one runway [kN]."""

    static_max: float  # each wheel, the trolley near this rail
    static_min: float  # each wheel, the trolley at the far rail
    impact: float  # share added to the vertical wheel loads
    vertical: float  # each wheel with impact
    lateral: float  # each wheel, at the top of the rail
    longitudinal: float  # each rail, at the top of the rail
    wheels: int
    clauses: list[str] = field(default_factory=list)


def wheel_loads(crane: Any, table: Any | None = None) -> WheelLoads:
    """The wheel loads of ``crane`` (a :class:`saengine.library.settings.CraneRunway`)."""
    table = table or code_context.table("cranes")
    span = float(crane.span)
    approach = min(float(crane.hookApproach), span)
    lifted = float(crane.capacity) + float(crane.trolleyWeight)
    near = float(crane.bridgeWeight) / 2 + lifted * (span - approach) / span
    far = float(crane.bridgeWeight) / 2 + lifted * approach / span
    n = int(crane.wheels)
    impact = float(table.impact.get(crane.kind, 0.0))
    scale = float((getattr(table, "horizontalScale", None) or {}).get(crane.kind, 1.0))
    lateral = table.lateral * scale
    longitudinal = table.longitudinal * scale
    notes = getattr(table, "notes", None) or {}
    clauses = [
        f"vertical impact {impact:.1%} ({crane.kind})",
        f"transverse {lateral:.1%} of lifted load + trolley and hoist, half on each runway",
        f"longitudinal {longitudinal:.1%} of the maximum wheel loads, on each rail",
    ]
    clauses += [notes[key] for key in (crane.kind, "lateral") if notes.get(key)]
    source = (getattr(table, "sources", None) or {}).get("impact") or getattr(table, "source", "")
    if source:
        clauses.append(source)
    return WheelLoads(
        static_max=near / n,
        static_min=far / n,
        impact=impact,
        vertical=near / n * (1 + impact),
        lateral=lateral * lifted / 2 / n,
        longitudinal=longitudinal * near,
        wheels=n,
        clauses=clauses,
    )


def _positions(wheels: int, base: float) -> np.ndarray:
    return np.arange(wheels, dtype=float) * base


def max_moment(load: float, wheels: int, base: float, span: float, steps: int = 400) -> float:
    """Largest moment [kN·m if load kN, span m] of a simple span under ``wheels`` equal loads
    ``base`` apart rolling across it (the moment under each wheel, every position)."""
    offsets = _positions(wheels, base)
    best = 0.0
    for lead in np.linspace(0.0, span + offsets[-1], steps + 1):
        xs = lead - offsets
        on = xs[(xs >= 0) & (xs <= span)]
        if not len(on):
            continue
        r_left = float(np.sum(load * (span - on) / span))
        for x in on:
            m = r_left * x - float(np.sum(load * (x - on[on < x])))
            best = max(best, m)
    return float(best)


def max_shear(load: float, wheels: int, base: float, span: float) -> float:
    """Largest end shear: the leading wheel at the support, the others following on the span."""
    xs = _positions(wheels, base)
    on = xs[xs <= span]
    return float(np.sum(load * (span - on) / span))


def max_reaction(load: float, wheels: int, base: float, span: float, steps: int = 400) -> float:
    """Largest reaction at a column between two equal simple spans (influence line 1 - |x|/L)."""
    offsets = _positions(wheels, base)
    best = 0.0
    for first in np.linspace(-span, span, steps + 1):
        xs = first + offsets
        ordinates = np.clip(1 - np.abs(xs) / span, 0.0, None)
        best = max(best, float(load * ordinates.sum()))
    return float(best)


# ─────────────────────────────────── moving crane load cases ───────────────────────────────────


@dataclass(frozen=True)
class Column:
    """A column the derivation knows: its source id, plan position and extent [mm]."""

    id: str
    x: float
    y: float
    bottom: float
    top: float


@dataclass
class CraneCase:
    """One crane load case: nodal loads at the bracket points (mm) [N, N·m]."""

    code: str
    label: str
    crane: str
    part: str
    loads: dict[tuple[float, float, float], np.ndarray] = field(default_factory=dict)


def _runway(crane: Any) -> tuple[int, int, float, float] | None:
    """(along index, across index, line A, line B) of a crane with load cases, else None."""
    axis = getattr(crane, "runwayAxis", None)
    a, b = getattr(crane, "columnLineA", None), getattr(crane, "columnLineB", None)
    if axis not in ("X", "Y") or a is None or b is None or crane.railLevel is None:
        return None
    along, across = (0, 1) if axis == "X" else (1, 0)
    return along, across, float(a), float(b)


def _line_columns(crane: Any, columns: list[Column], line: float) -> list[tuple[float, Column]]:
    """(along, column) of the columns on a runway's column line spanning its rail level."""
    found = _runway(crane)
    assert found is not None
    along, across, *_ = found
    z = float(crane.railLevel)
    start = getattr(crane, "runwayStart", None)
    end = getattr(crane, "runwayEnd", None)
    out = []
    for column in columns:
        xy = (column.x, column.y)
        if abs(xy[across] - line) > LINE_TOLERANCE:
            continue
        if not (column.bottom < z <= column.top + 1e-6):
            continue
        s = xy[along]
        if (start is not None and s < float(start) - 1e-6) or (
            end is not None and s > float(end) + 1e-6
        ):
            continue
        out.append((s, column))
    out.sort(key=lambda item: item[0])
    # One column per position (a column split in pieces is listed once).
    unique: list[tuple[float, Column]] = []
    for s, column in out:
        if not unique or abs(s - unique[-1][0]) > 1.0:
            unique.append((s, column))
    return unique


def bracket_points(cranes: list[Any], columns: list[Column]) -> dict[str, list[float]]:
    """Column id -> the rail levels [mm] where the derivation splits it so each crane bracket
    has its node (cranes with load cases only)."""
    out: dict[str, list[float]] = {}
    for crane in cranes:
        found = _runway(crane)
        if found is None:
            continue
        for line in found[2:]:
            for _, column in _line_columns(crane, columns, line):
                levels = out.setdefault(column.id, [])
                if float(crane.railLevel) not in levels:
                    levels.append(float(crane.railLevel))
    return out


def _shares(wheels: np.ndarray, supports: list[float]) -> dict[int, float]:
    """Support index -> its share of the wheels (each wheel split by the lever rule between
    the two supports of its simple span; wheels off the runway carry nothing)."""
    out: dict[int, float] = {}
    for x in wheels:
        for j in range(len(supports) - 1):
            s0, s1 = supports[j], supports[j + 1]
            if s0 - 1e-6 <= x <= s1 + 1e-6:
                t = (x - s0) / (s1 - s0)
                out[j] = out.get(j, 0.0) + 1 - t
                out[j + 1] = out.get(j + 1, 0.0) + t
                break
    return out


def place_wheels(target: float, supports: list[float], offsets: np.ndarray) -> np.ndarray:
    """The wheel positions (along the runway) that give the largest reaction at the support at
    ``target``, all wheels on the runway: one wheel at a support or the group at an end."""
    lo, hi = supports[0], supports[-1]
    k = min(range(len(supports)), key=lambda j: abs(supports[j] - target))
    breaks = [supports[j] for j in (k - 1, k, k + 1) if 0 <= j < len(supports)]
    leads = {lo + float(offsets[-1]), hi}  # the group against either end
    for wheel in offsets:
        for b in breaks:
            leads.add(b + float(wheel))
    best: tuple[float, np.ndarray] | None = None
    for lead in sorted(leads):
        xs = lead - offsets
        if xs.min() < lo - 1e-6 or xs.max() > hi + 1e-6:
            continue
        value = _shares(xs, supports).get(k, 0.0)
        if best is None or value > best[0] + 1e-9:
            best = (value, xs)
    if best is None:  # the group is longer than the runway: the leading wheel at the target
        xs = target - offsets + float(offsets[-1]) / 2
        return xs
    return best[1]


def crane_load_cases(
    cranes: list[Any], columns: list[Column], table: Any | None = None
) -> tuple[list[CraneCase], list[str]]:
    """The moving load cases of every crane with a runway direction and column lines, and the
    notes. Forces in N, moments in N·m, at the bracket points (column centre, rail level) [mm]."""
    table = table or code_context.table("cranes")
    cases: list[CraneCase] = []
    notes: list[str] = []
    if getattr(table, "combination", None) is None:
        if any(_runway(c) for c in cranes):
            notes.append(
                "crane load cases: the code pack gives no crane combination rule; the crane "
                "loads are reported, not applied"
            )
        return cases, notes
    for index, crane in enumerate(cranes, start=1):
        found = _runway(crane)
        if found is None:
            notes.append(
                f"crane {crane.id}: no runway direction, column lines or rail level; its loads "
                "are reported for the engineer to apply"
            )
            continue
        along, across, line_a, line_b = found
        lines = {
            "a": _line_columns(crane, columns, line_a),
            "b": _line_columns(crane, columns, line_b),
        }
        if any(len(found_columns) < 2 for found_columns in lines.values()):
            notes.append(
                f"crane {crane.id}: fewer than two columns on a runway line spanning the rail "
                f"level {crane.railLevel:g} mm; no crane load cases"
            )
            continue
        loads = wheel_loads(crane, table)
        mid = (line_a + line_b) / 2
        half = float(crane.span) / 2
        # Rail position across, and the bracket eccentricity (rail from column centre) [mm].
        eccentricity = {}
        for side, line in (("a", line_a), ("b", line_b)):
            direction = 1.0 if line >= mid else -1.0
            if abs(line - mid) < 1e-9:
                direction = 1.0 if side == "b" else -1.0
            eccentricity[side] = mid + direction * half - line
        offsets = _positions(loads.wheels, float(crane.wheelBase))
        stations = sorted(
            {round(s, 0) for found_columns in lines.values() for s, _ in found_columns}
        )
        z = float(crane.railLevel)
        for k, target in enumerate(stations, start=1):
            home = "a" if any(abs(s - target) <= 1.0 for s, _ in lines["a"]) else "b"
            wheels = place_wheels(target, [s for s, _ in lines[home]], offsets)
            for trolley in ("a", "b"):
                parts = {part: CraneCase(
                    f"C{index}{part}{k}{trolley}",
                    f"crane {crane.id} {PARTS[part]}, at {'XY'[along]} = {target:g} mm, "
                    f"trolley at line {trolley.upper()}",
                    crane.id,
                    part,
                ) for part in PARTS}  # fmt: skip
                for side, found_columns in lines.items():
                    supports = [s for s, _ in found_columns]
                    shares = _shares(wheels, supports)
                    vertical = (
                        loads.vertical if side == trolley else loads.static_min
                    )  # kN per wheel: impact on the maximum wheel loads
                    r = np.zeros(3)
                    r[across] = eccentricity[side] / 1000  # m
                    for j, share in shares.items():
                        column = found_columns[j][1]
                        point = (column.x, column.y, z)
                        f_v = np.array([0.0, 0.0, -vertical * share * 1000])
                        f_t = np.zeros(3)
                        f_t[across] = loads.lateral * share * 1000
                        f_b = np.zeros(3)
                        f_b[along] = (
                            loads.longitudinal * share / max(sum(shares.values()), 1e-9) * 1000
                        )
                        for part, force in (("V", f_v), ("T", f_t), ("B", f_b)):
                            vector = np.concatenate([force, np.cross(r, force)])
                            target_loads = parts[part].loads
                            if point in target_loads:
                                target_loads[point] = target_loads[point] + vector
                            else:
                                target_loads[point] = vector
                cases += [case for case in parts.values() if case.loads]
        notes.append(
            f"crane {crane.id}: {len(stations)} positions along the runway x 2 trolley sides, "
            f"cases C{index}V/T/B (vertical with impact on the maximum wheel loads, transverse, "
            "longitudinal) at the rail level of the columns on lines A and B"
            + (f" ({table.sources['combination']})" if table.sources.get("combination") else "")
        )
    return cases, notes


# ───────────────────────────────────────── runway beam ─────────────────────────────────────────


def _strength_factors() -> tuple[float, float, str]:
    """(D, L, name) of the code pack's strength combination with the largest live load factor
    and no wind or earthquake."""
    table = code_context.table("combinations")
    best = (1.2, 1.6, "1.2D + 1.6L")
    for c in table.strength:
        f = c.factors
        if "L" in f and not ({"W", "E"} & set(f)) and f["L"] >= best[1]:
            best = (float(f.get("D", 1.2)), float(f["L"]), c.name)
    return best


def check_runway_beam(
    crane: Any, loads: WheelLoads, object_type: Any, material: Any
) -> dict[str, Any]:
    """The runway beam check of ``crane`` (units: N, mm inside, kN·m reported)."""
    from saengine.design.steel import members as sm
    from saengine.design.steel.properties import shape_properties

    shape = shape_properties(object_type.profile)
    steel = sm.Steel.of(material)
    span = float(crane.runwaySpan)  # mm
    span_m = span / 1000
    base_m = float(crane.wheelBase) / 1000
    density = float(getattr(getattr(material, "mechanical", None), "density", 7850) or 7850)
    self_weight = shape.area * 1e-6 * density * G / 1000  # kN/m
    fd, fl, combination = _strength_factors()
    m_dead = self_weight * span_m**2 / 8
    v_dead = self_weight * span_m / 2
    m_crane = max_moment(loads.vertical, loads.wheels, base_m, span_m)
    v_crane = max_shear(loads.vertical, loads.wheels, base_m, span_m)
    m_lateral = max_moment(loads.lateral, loads.wheels, base_m, span_m)
    mux = (fd * m_dead + fl * m_crane) * 1e6  # N·mm
    muy = fl * m_lateral * 1e6
    vu = (fd * v_dead + fl * v_crane) * 1e3  # N
    major = sm.flexure_major(shape, steel, lb=span, cb=1.0)
    bf, tf = shape.dims.get("bf", 0.0), shape.dims.get("tf", 0.0)
    flange = (
        0.9 * steel.fy * tf * bf * bf / 4 if bf and tf else sm.flexure_minor(shape, steel).design
    )
    shear = sm.shear_major(shape, steel)
    ratio, equation = sm.interaction(0.0, 1.0, mux, major.design, muy, flange)
    # Service deflection under the static wheel loads, by superposition of point loads.
    e, i = steel.e, shape.ix  # MPa, mm⁴
    deflection = _max_deflection(loads.static_max * 1e3, loads.wheels, base_m * 1e3, span, e, i)
    result = {
        "beam": getattr(object_type, "id", ""),
        "combination": combination,
        "Mux_kNm": round(mux / 1e6, 2),
        "Muy_kNm": round(muy / 1e6, 2),
        "Vu_kN": round(vu / 1e3, 2),
        "phiMnx_kNm": round(major.design / 1e6, 2),
        "phiMny_flange_kNm": round(flange / 1e6, 2),
        "phiVn_kN": round(shear.design / 1e3, 2),
        "flexure": round(ratio, 3),
        "flexureEquation": equation,
        "flexureLimit": major.state,
        "shear": round(vu / shear.design, 3) if shear.design > 0 else None,
        "deflection_mm": round(deflection, 1),
        "spanOverDeflection": round(span / deflection) if deflection > 0 else None,
        "ok": bool(ratio <= 1.0) and (shear.design <= 0 or vu <= shear.design),
    }
    if getattr(crane, "fatigueCategory", None):
        sx = shape.sx
        s_flange = tf * bf * bf / 6 if bf and tf else shape.sy  # top flange alone, elastic
        result["fatigue"] = runway_fatigue(
            crane, m_dead * 1e6, m_crane * 1e6, m_lateral * 1e6, sx, s_flange, steel.fy
        )
        result["ok"] = result["ok"] and result["fatigue"]["ok"]
    return result


def runway_fatigue(
    crane: Any,
    m_dead: float,
    m_crane: float,
    m_lateral: float,
    sx: float,
    s_flange: float,
    fy: float,
) -> dict[str, Any]:
    """The fatigue check of a runway beam (moments N·mm, moduli mm³, fy MPa): the bottom
    flange's stress range under the vertical wheel loads with impact, and the top flange tip's
    under the vertical and the transverse force either way (reversal: the larger of σv + σt and
    2 σt). Both details take the crane's stress category."""
    from saengine.design.steel import fatigue

    n = fatigue.cycles(crane.cyclesPerDay, crane.designLife)
    sigma_v = m_crane / sx
    sigma_t = m_lateral / s_flange if s_flange > 0 else 0.0
    sigma_d = m_dead / sx
    details = {
        "bottomFlange": (sigma_v, sigma_d + sigma_v),
        "topFlangeTip": (max(sigma_v + sigma_t, 2 * sigma_t), sigma_d + sigma_v + sigma_t),
    }
    out: dict[str, Any] = {"cycles": round(n), "details": {}}
    ok = True
    for name, (stress_range, max_stress) in details.items():
        checked = fatigue.check(crane.fatigueCategory, n, stress_range, max_stress, fy)
        out["details"][name] = checked.as_dict()
        ok = ok and checked.ok
    out["ok"] = ok
    table = code_context.table("fatigue")
    out["clause"] = table.source
    return out


def _max_deflection(
    load: float, wheels: int, base: float, span: float, e: float, i: float, steps: int = 200
) -> float:
    """Largest midspan deflection [mm] of a simple span under the rolling wheel group [N, mm]."""
    offsets = _positions(wheels, base)
    x = span / 2
    best = 0.0
    for lead in np.linspace(0.0, span + offsets[-1], steps + 1):
        total = 0.0
        for a in lead - offsets:
            if 0 <= a <= span:
                b = span - a
                # Deflection at x of a point load at a (simple beam).
                if x <= a:
                    total += load * b * x * (span**2 - b**2 - x**2) / (6 * e * i * span)
                else:
                    total += (
                        load
                        * a
                        * (span - x)
                        * (span**2 - a**2 - (span - x) ** 2)
                        / (6 * e * i * span)
                    )
        best = max(best, total)
    return float(best)


def crane_summary(
    cranes: list[Any], types: dict[str, Any], materials: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Per crane: its wheel loads, column reactions and runway beam check; and the notes."""
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    if not cranes:
        return rows, notes
    table = code_context.table("cranes")
    clause = table.source or code_context.current().name
    for crane in cranes:
        loads = wheel_loads(crane, table)
        span_m = float(crane.runwaySpan) / 1000
        base_m = float(crane.wheelBase) / 1000
        row: dict[str, Any] = {
            "id": crane.id,
            "name": crane.name,
            "wheelMax_kN": round(loads.static_max, 2),
            "wheelMin_kN": round(loads.static_min, 2),
            "impact": loads.impact,
            "wheelWithImpact_kN": round(loads.vertical, 2),
            "lateralPerWheel_kN": round(loads.lateral, 2),
            "longitudinal_kN": round(loads.longitudinal, 2),
            "columnVertical_kN": round(
                max_reaction(loads.vertical, loads.wheels, base_m, span_m), 2
            ),
            "columnVerticalMin_kN": round(
                max_reaction(loads.static_min, loads.wheels, base_m, span_m), 2
            ),
            "columnLateral_kN": round(max_reaction(loads.lateral, loads.wheels, base_m, span_m), 2),
            "railLevel_mm": crane.railLevel,
            "loadCases": _runway(crane) is not None,
            "clauses": loads.clauses,
        }
        if crane.beamType:
            object_type = types.get(crane.beamType)
            material = materials.get(getattr(object_type, "material", ""))
            try:
                if object_type is None or material is None:
                    raise ValueError(f"no beam type '{crane.beamType}' with a material")
                row["runwayBeam"] = check_runway_beam(crane, loads, object_type, material)
            except (ValueError, KeyError, AttributeError) as error:  # not a checkable steel type
                row["runwayBeam"] = {"beam": crane.beamType, "error": str(error)}
                notes.append(f"crane {crane.id}: runway beam not checked ({error})")
        elif getattr(crane, "fatigueCategory", None):
            notes.append(f"crane {crane.id}: no runway beam type, so no fatigue check")
        rows.append(row)
        beam = row.get("runwayBeam") or {}
        fatigue = beam.get("fatigue") or {}
        notes.append(
            f"crane {crane.id}: wheel {row['wheelWithImpact_kN']:g} kN with impact "
            f"({loads.impact:.1%}), transverse {row['lateralPerWheel_kN']:g} kN per wheel, "
            f"column reaction up to {row['columnVertical_kN']:g} kN vertical and "
            f"{row['columnLateral_kN']:g} kN transverse ({clause})"
            + (
                "; applied to the frames as moving load cases"
                if row["loadCases"]
                else "; apply them to the frames at the brackets"
            )
            + (
                f"; runway beam {beam['beam']}: flexure {beam['flexure']:g}, shear "
                f"{beam['shear']:g}, deflection L/{beam['spanOverDeflection']}"
                if "flexure" in beam
                else ""
            )
            + (
                "; fatigue "
                + ", ".join(
                    f"{name} {_fatigue_text(detail)}" for name, detail in fatigue["details"].items()
                )
                + f" ({fatigue['cycles']:,} cycles, {fatigue['clause']})"
                if fatigue
                else ""
            )
        )
    return rows, notes


def _fatigue_text(detail: dict[str, Any]) -> str:
    return detail["exempt"] or f"ratio {detail['ratio']:g}"

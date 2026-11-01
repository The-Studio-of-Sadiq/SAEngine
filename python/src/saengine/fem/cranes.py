"""Crane runway loads and runway beam checks (Project Settings → Crane runways).

Crane loads (BNBC 2020 Part 6 Sec 2.3, crane loads, the provisions of ASCE 7-05 Sec 4.10; the
factors are the code pack's ``cranes`` table):

- maximum wheel loads: the bridge's weight shared by the two rails, plus the rated capacity
  and the hoist and trolley with the trolley at its closest approach to a rail (statics of the
  bridge as a simple beam between the rails), shared equally by the wheels on that rail;
- vertical impact: the maximum wheel loads times (1 + impact), impact by kind of crane (25 %
  for powered monorails, cab-operated and remotely operated bridge cranes, 10 % pendant
  operated, 0 % hand-geared);
- lateral force: 20 % of the rated capacity plus the hoist and trolley, at the top of the
  rails, half on each runway (equal runway stiffness), either direction;
- longitudinal force: 10 % of the maximum wheel loads on a rail, at the top of the rail.

Runway beams are taken simply supported over ``runwaySpan`` (one bay). The wheels of one rail
(``wheels`` at ``wheelBase``) roll along it: the largest moment is under a wheel, found by
moving the group along the span; the largest end shear with the leading wheel at the support;
the largest column reaction with the group straddling a column between two equal spans.

The runway beam check (``beamType``, a steel beam type) reuses the steel member design of BNBC
2020 Part 6 Chapter 10 (:mod:`saengine.design.steel.members`): factored moments from the
dead load of the beam and the crane loads as live load (the code pack's strength combination
with the largest live load factor, BNBC Sec 2.7.3), major-axis flexure with the top flange
unbraced over the span (Cb = 1), the lateral moment on the top flange alone (its plastic
modulus tf·bf²/4: the usual assumption that the top flange resists the lateral load, which
BNBC does not state), their interaction (Eq 6.10.147b with no axial force) and web shear.
Deflections are reported, not checked: BNBC gives no limit for runway beams.

Not covered: fatigue of the runway beam and its welds, the rail's own bending, web crippling
under the wheels, several cranes on one runway, and applying the column reactions to the
frames as load cases (they are given for the engineer to apply).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.codes import context as code_context

G = 9.80665


@dataclass
class WheelLoads:
    """Crane loads on one runway [kN]."""

    static_max: float  # each wheel, the trolley near this rail
    static_min: float  # each wheel, the trolley at the far rail
    impact: float  # share added to the vertical wheel loads
    vertical: float  # each wheel with impact
    lateral: float  # each wheel, at the top of the rail
    longitudinal: float  # the rail, at the top of the rail
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
    return WheelLoads(
        static_max=near / n,
        static_min=far / n,
        impact=impact,
        vertical=near / n * (1 + impact),
        lateral=table.lateral * lifted / 2 / n,
        longitudinal=table.longitudinal * near,
        wheels=n,
        clauses=[
            f"vertical impact {impact:.0%} ({crane.kind})",
            f"lateral {table.lateral:.0%} of capacity + hoist and trolley, half on each runway",
            f"longitudinal {table.longitudinal:.0%} of the maximum wheel loads",
        ],
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


def _strength_factors() -> tuple[float, float, str]:
    """(D, L, name) of the code pack's strength combination with the largest live load factor
    and no wind or earthquake (BNBC 2020 Sec 2.7.3)."""
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
    return {
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
        rows.append(row)
        beam = row.get("runwayBeam") or {}
        notes.append(
            f"crane {crane.id}: wheel {row['wheelWithImpact_kN']:g} kN with impact "
            f"({loads.impact:.0%}), lateral {row['lateralPerWheel_kN']:g} kN per wheel, "
            f"column reaction up to {row['columnVertical_kN']:g} kN vertical and "
            f"{row['columnLateral_kN']:g} kN lateral (BNBC 2020 Part 6 Sec 2.3, crane loads); "
            "apply them to the frames at the brackets"
            + (
                f"; runway beam {beam['beam']}: flexure {beam['flexure']:g}, shear "
                f"{beam['shear']:g}, deflection L/{beam['spanOverDeflection']}"
                if "flexure" in beam
                else ""
            )
        )
    return rows, notes

"""Special stairs by the code pack's methods (``stairMethods``; the default pack's BNBC 2020 Part 6 Sec 6.7.2 and
Appendix M) (B33):

- **free-standing** (landing unsupported, method ``empiricalTable``): the service forces of the
  pack's expressions in the well width A, landing width B, flight width C, going L, storey
  height H, waist T and f'c, scaled to the live load by (a T + LL + b)/(a T + c) and factored by
  the combination's factors on the expressions' own dead load (a T + b) and the live load;
  the support moment MS with ``outerShareSupport`` of its steel in the outer half of the flight,
  MK with ``innerShareJunction`` in the inner half, Mo across the inner half of the landing, MF
  across the flight;
- **sawtooth** (slabless, method ``supportChart``): the support moment Ms = coefficient n l²
  from the pack's chart by the number of treads j and k = (ht³ lr)/(hr³ lt), the free moment
  n l² / ``freeDivisor`` (× (j² + 1)/j² for odd j), midspan M0 = M - Ms; the re-entrant corners
  take ``reentrantFactor`` × the steel of Ms;
- **helicoidal** (method ``redundantCharts``): k1, k2, k3 from the pack's charts (bilinear in
  R1/R2 and b/h, linear in φ and β, never extrapolated), Mo = k1 n R2², H = k2 n R2,
  Mvs = k3 n R2², and along the helix the lateral moment Mn, torsion T, vertical moment My,
  thrust N and shears Vn, Vh by the closed-form equations.

Each returns demands per metre width (:class:`saengine.design.stairs.Demand`, designed by the
stair's own checks) and the extra rows of the forces the stair's bars do not cover (torsion,
thrust, in-plane moment), which are reported for the detailing. Units: mm, kN, kN·m, kN/m².
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from saengine.codes import context as code_context


def rules() -> Any:
    """The pack's ``stairMethods`` table, None when the pack does not cover it."""
    pack = code_context.current()
    return pack.table("stairMethods") if pack.has("stairMethods") else None


def clause(key: str) -> str:
    table = rules()
    text = (getattr(table, "clauses", None) or {}).get(key) if table is not None else None
    if not text:
        return ""
    pack = code_context.current()
    return f"{pack.edition or pack.name} {text}"


def not_covered(what: str) -> str:
    return f"{what}: not covered by the code pack {code_context.current().name}"


def _row(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    combination: Any,
    note: str,
    flag: bool = False,
    utilisation: float | None = None,
) -> dict[str, Any]:
    from saengine.design.check import _check

    return _check(name, demand, capacity, unit, combination, note, flag, utilisation)


# ───────────────────────────────────── free-standing ─────────────────────────────────────


def _power(x: float, exponent: float) -> float:
    """x^exponent keeping the sign of x (the expressions' offsets can exceed the variable)."""
    return math.copysign(abs(x) ** exponent, x)


def empirical_value(expression: Any, values: dict[str, float]) -> float:
    """factor × Π [base + coefficient (variable - offset)^exponent]."""
    out = float(expression.factor)
    for term in expression.terms:
        x = values[term.variable] - float(term.offset)
        out *= float(term.base) + float(term.coefficient) * _power(x, float(term.exponent))
    return out


def free_standing_service(values: dict[str, float], rules_: Any) -> dict[str, float]:
    """The service values of every expression for the reference live load."""
    return {e.id: empirical_value(e, values) for e in rules_.expressions}


def free_standing(
    well: float,
    landing: float,
    width: float,
    going: float,
    height: float,
    waist: float,
    landing_h: float,
    fc: float,
    live: float,
    combinations: Sequence[tuple[str, float, float]],
) -> tuple[list[Any], list[dict[str, Any]], list[str]]:
    """Demands, extra rows and notes of a free-standing stair (dimensions mm, live kN/m²)."""
    from saengine.design.stairs import Demand

    table = rules()
    method = getattr(table, "freeStanding", None) if table is not None else None
    if method is None:
        raise ValueError(not_covered("free-standing stairs"))
    values = {
        "A": well / 1000,
        "B": landing / 1000,
        "C": width / 1000,
        "L": going / 1000,
        "H": height / 1000,
        "T": waist / 1000,
        "fc": fc,
    }
    rows: list[dict[str, Any]] = []
    outside = [
        f"{k} = {values[k]:g} outside {lo:g}-{hi:g}"
        for k, (lo, hi) in method.ranges.items()
        if not lo - 1e-9 <= values[k] <= hi + 1e-9
    ]
    if outside:
        rows.append(
            _row(
                f"Free-standing stair: range of the expressions ({clause('freeStanding')})",
                1.0,
                0.0,
                "",
                None,
                "; ".join(outside) + ": the expressions do not apply",
            )
        )
    a, b, c = (float(v) for v in method.liveScale)
    t = values["T"]
    scale = (a * t + live + b) / (a * t + c)
    dead = a * t + b  # the expressions' own dead load [kN/m²]
    factor, governing = max(
        ((fd * dead + fl * live) / (dead + live), name) for name, fd, fl in combinations
    )
    service = free_standing_service(values, method)
    factored = {k: v * scale * factor for k, v in service.items()}
    notes = [
        (
            f"free-standing stair ({clause('freeStanding')}): service values × {scale:.3f} for "
            f"{live:g} kN/m² live load, × {factor:.3f} ({governing}) to factored"
        )
    ]
    half_c, half_b = width / 2000, landing / 2000
    flight = Demand("F (free-standing)", "flight", going, waist)
    flight.mu = max(factored["MF"], 0.0) / (width / 1000)
    flight.mu_top = max(
        float(method.outerShareSupport) * factored["MS"] / half_c,
        float(method.innerShareJunction) * factored["MK"] / half_c,
    )
    flight.combination = governing
    flight.wu = factor * (dead + live)
    notes.append("the expressions give no vertical shear at the supports: not checked")
    flight.notes.append(
        f"MF = {factored['MF']:.1f} across the flight; MS = {factored['MS']:.1f} with "
        f"{method.outerShareSupport:.0%} in the outer half, MK = {factored['MK']:.1f} with "
        f"{method.innerShareJunction:.0%} in the inner half (kN·m)"
    )
    land = Demand("L (free-standing)", "landing", landing, landing_h)
    land.wu = flight.wu
    land.mu_top = max(factored["Mo"], 0.0) / half_b
    land.combination = governing
    land.notes.append(f"Mo = {factored['Mo']:.1f} kN·m over the inner half of the landing")
    for key, what in (
        ("AF", "tension in the upper flight: As = AF / (φ fy) along it"),
        ("TF", "torsion in the flights: closed hoops with cross ties"),
        ("MI", "in-plane moment: bars at the inner edge (upper) and outer edge (lower flight)"),
        ("Vo", "lateral shear at the mid-landing section: hoops"),
    ):
        expression = next(e for e in method.expressions if e.id == key)
        rows.append(
            _row(
                f"Free-standing stair: {expression.name}",
                factored[key],
                factored[key],
                expression.unit,
                governing,
                f"{what} ({clause('freeStandingDetailing')})",
                flag=True,
            )
        )
    rows.append(
        _row(
            "Free-standing stair: deflection at the landing corner (service)",
            service["deflection"] * scale * 1000,
            service["deflection"] * scale * 1000,
            "mm",
            None,
            "from the pack's expression at the service live load",
            flag=True,
        )
    )
    return [flight, land], rows, notes


# ───────────────────────────────────── sawtooth ─────────────────────────────────────


def sawtooth_coefficient(treads: int, k: float, method: Any) -> float | None:
    """The support moment coefficient by the number of treads and k (linear in j and in
    k/(1 + k), k = None for infinite); None outside the chart."""
    js = [int(j) for j in method.treads]
    if not js[0] <= treads <= js[-1]:
        return None
    curves = sorted(method.curves, key=lambda c: math.inf if c.k is None else c.k)
    xs = [1.0 if c.k is None else c.k / (1 + c.k) for c in curves]
    x = k / (1 + k) if math.isfinite(k) else 1.0
    by_curve = []
    for curve in curves:
        pts = [(j, v) for j, v in zip(js, curve.coefficients, strict=True) if v is not None]
        if not pts or not pts[0][0] <= treads <= pts[-1][0]:
            by_curve.append(None)
            continue
        by_curve.append(float(np.interp(treads, [p[0] for p in pts], [p[1] for p in pts])))
    known = [(xi, v) for xi, v in zip(xs, by_curve, strict=True) if v is not None]
    if not known or not known[0][0] - 1e-9 <= x <= known[-1][0] + 1e-9:
        return None
    return float(np.interp(x, [p[0] for p in known], [p[1] for p in known]))


def sawtooth(
    treads: int,
    tread: float,
    riser: float,
    tread_h: float,
    riser_h: float,
    going: float,
    wu: float,
    combination: str | None,
) -> tuple[list[Any], list[dict[str, Any]], list[str]]:
    """Demand per metre width of a sawtooth flight of ``treads`` treads over ``going`` mm
    under ``wu`` kN/m² (factored)."""
    from saengine.design.stairs import Demand

    table = rules()
    method = getattr(table, "sawtooth", None) if table is not None else None
    if method is None:
        raise ValueError(not_covered("sawtooth stairs"))
    k = (tread_h**3 * riser) / (riser_h**3 * tread)
    coefficient = sawtooth_coefficient(treads, k, method)
    if coefficient is None:
        raise ValueError(
            f"sawtooth stair: {treads} treads, k = {k:.2f} outside the chart ({clause('sawtooth')})"
        )
    span = going / 1000
    ms = coefficient * wu * span**2
    free = wu * span**2 / float(method.freeDivisor)
    if treads % 2:
        free *= (treads**2 + 1) / treads**2
    demand = Demand("F (sawtooth)", "flight", going, tread_h)
    demand.mu = max(free - ms, 0.0)
    demand.mu_top = ms
    demand.vu = wu * span / 2
    demand.wu = wu
    demand.combination = combination
    demand.continuous_ends = 2
    demand.notes.append(
        f"Ms = {coefficient:.4f} wu l² (j = {treads}, k = {k:.2f}), M = {free:.2f}, "
        f"M0 = M - Ms ({clause('sawtooth')})"
    )
    rows = [
        _row(
            f"Sawtooth stair: re-entrant corners ({clause('sawtoothCorners')})",
            float(method.reentrantFactor) * ms,
            float(method.reentrantFactor) * ms,
            "kN·m/m",
            combination,
            f"{method.reentrantFactor:g} × the steel of Ms at the re-entrant corners (or haunches)",
            flag=True,
        )
    ]
    return [demand], rows, []


# ───────────────────────────────────── helicoidal ─────────────────────────────────────


def _chart_value(chart: Any, k: str, phi: float, beta: float) -> float | None:
    curves = sorted((c for c in chart.curves if c.k == k), key=lambda c: c.phi)
    if not curves:
        return None
    betas = [float(b) for b in chart.betas]
    if not betas[0] - 1e-9 <= beta <= betas[-1] + 1e-9:
        return None
    phis = [float(c.phi) for c in curves]
    at = [float(np.interp(beta, betas, c.values)) for c in curves]
    return float(np.interp(phi, phis, at))


def helicoidal_coefficients(
    radius_ratio: float, width_ratio: float, phi: float, beta: float
) -> tuple[float, float, float]:
    """(k1, k2, k3): bilinear in R1/R2 and b/h between the pack's charts (clamped to them),
    linear in φ (clamped) and β (within the charts). Raises ValueError outside β's range."""
    table = rules()
    method = getattr(table, "helicoidal", None) if table is not None else None
    if method is None:
        raise ValueError(not_covered("helicoidal stairs"))
    charts = list(method.charts)
    rs = sorted({float(c.radiusRatio) for c in charts})
    ws = sorted({float(c.widthRatio) for c in charts})
    r = min(max(radius_ratio, rs[0]), rs[-1])
    w = min(max(width_ratio, ws[0]), ws[-1])
    out = []
    for k in ("k1", "k2", "k3"):
        grid = {}
        for chart in charts:
            value = _chart_value(chart, k, phi, beta)
            if value is None:
                raise ValueError(f"helicoidal stair: β = {beta:.0f}° outside the charts")
            grid[(float(chart.radiusRatio), float(chart.widthRatio))] = value
        along_w = []
        for ri in rs:
            pts = sorted((wi, v) for (rr, wi), v in grid.items() if rr == ri)
            along_w.append(float(np.interp(w, [p[0] for p in pts], [p[1] for p in pts])))
        out.append(float(np.interp(r, rs, along_w)))
    return out[0], out[1], out[2]


def helix_forces(
    mo: float, h: float, n: float, r1: float, r2: float, phi: float, theta: np.ndarray
) -> dict[str, np.ndarray]:
    """The forces along the helix at plan angles θ [rad] from midspan (Eqs 6.M.2-6.M.7)."""
    s, c = np.sin(theta), np.cos(theta)
    sp, cp, tp = math.sin(phi), math.cos(phi), math.tan(phi)
    mn = (
        mo * s * sp
        - h * r2 * theta * tp * c * sp
        - h * r2 * s * cp
        + n * r1 * sp * (r1 * s - r2 * theta)
    )
    t = (mo * s - h * r2 * theta * c * tp + n * r1**2 * s - n * r1 * r2 * theta) * cp + (
        h * r2 * s * sp
    )
    my = mo * c + h * r2 * theta * tp * s - n * r1**2 * (1 - c)
    thrust = -h * s * cp - n * r1 * theta * sp
    vn = n * r1 * theta * cp - h * s * sp
    vh = h * c
    return {"Mn": mn, "T": t, "My": my, "N": thrust, "Vn": vn, "Vh": vh}


def helicoidal(
    inner: float,
    outer: float,
    angle: float,
    rise: float,
    waist: float,
    wu: float,
    combination: str | None,
) -> tuple[list[Any], list[dict[str, Any]], list[str]]:
    """Demands per metre width of a helicoidal stair: radii [mm], total plan angle [°], rise
    [mm], waist [mm], ``wu`` kN/m² (factored, on plan)."""
    from saengine.design.stairs import Demand

    if outer <= inner or inner < 0 or angle <= 0:
        raise ValueError("helicoidal stair: outer radius above inner, plan angle above 0")
    ri, ro = inner / 1000, outer / 1000
    b = ro - ri
    r1 = (2 / 3) * (ro**3 - ri**3) / (ro**2 - ri**2)
    r2 = (ri + ro) / 2
    beta = math.radians(angle)
    phi = math.atan2(rise / 1000, beta * r2)
    k1, k2, k3 = helicoidal_coefficients(r1 / r2, b / (waist / 1000), math.degrees(phi), angle)
    n = wu * b
    mo, h = k1 * n * r2**2, k2 * n * r2
    theta = np.linspace(0.0, beta / 2, 181)
    forces = helix_forces(mo, h, n, r1, r2, phi, theta)
    mvs = k3 * n * r2**2
    demand = Demand("F (helicoidal)", "flight", beta * r2 * 1000, waist)
    sag = max(float(forces["My"].max()), 0.0)
    hog = max(-float(forces["My"].min()), -mvs, 0.0)
    demand.mu, demand.mu_top = sag / b, hog / b
    demand.vu = float(np.abs(forces["Vn"]).max()) / b
    demand.wu, demand.combination = wu, combination
    demand.notes.append(
        f"R1 = {r1:.3f} m, R2 = {r2:.3f} m, φ = {math.degrees(phi):.1f}°, k1 = {k1:.3f}, "
        f"k2 = {k2:.3f}, k3 = {k3:.3f}; Mo = {mo:.1f} kN·m, H = {h:.1f} kN, Mvs = {mvs:.1f} "
        f"kN·m ({clause('helicoidal')}); per metre over b = {b:.2f} m"
    )
    rows = []
    for key, name, unit in (
        ("T", "torsion", "kN·m"),
        ("Mn", "lateral (in-plane) moment", "kN·m"),
        ("N", "thrust", "kN"),
        ("Vh", "radial horizontal shear", "kN"),
    ):
        value = float(np.abs(forces[key]).max())
        rows.append(
            _row(
                f"Helicoidal stair: {name}",
                value,
                value,
                unit,
                combination,
                "the largest along the helix: for the hoops and side bars",
                flag=True,
            )
        )
    return [demand], rows, []

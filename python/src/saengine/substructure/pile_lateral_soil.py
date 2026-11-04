"""Laterally loaded piles in the soil: soil failure by Broms and the p-y analysis (alpha 9 P7).

The methods and every number are the code pack's (``foundations.piles.lateral.soilFailure``
and ``.pyAnalysis``, :class:`saengine.codes.tables.PileSoilFailure` and
:class:`~saengine.codes.tables.PilePyAnalysis`); a pack without a group does not cover that
check. The default pack's BNBC 2020 asks for the lateral capacity "on the basis of soil
failure" and the head deflection (Part 6 Sec 3.10.1.21) without a method: both methods are
SAEngine practice there, and the report says so. The rest of the lateral pile rules (the
Winkler head stiffness, group ratios, unbraced piles, load tests) stay in
:mod:`saengine.substructure.pile_lateral`; this module adds to them.

**Soil failure** (method ``broms``, Broms 1964a, 1964b): the soil over the top
``averagingDepth`` × D below the pile head, averaged by thickness, is cohesive (undrained cu)
when most of it is, else granular (φ', with the effective stress of the profile). With the
reaction ``p9`` = ``passiveCohesive`` (9) cu D below ``cohesiveGap`` (1.5) D, f = Hu / (p9
cu D), g = L - gap - f:

- free head: short Hu (e + gap + f/2) = p9/4 cu D g², long Hu (e + gap + f/2) = My;
- fixed head: short Hu = p9 cu D (L - gap), intermediate My = p9/4 cu D g² - p9 cu D f (gap
  + f/2), long Hu = 2 My / (gap + f/2).

Granular, the reaction c Kp γ' D z (c = ``passiveGranular``, 3), f = √(2 Hu / (c Kp γ' D)):

- free head: short Hu = c/6 γ' D L³ Kp / (e + L), long My = Hu (e + 2f/3);
- fixed head: short Hu = c/2 γ' D L² Kp, intermediate My = c/6 γ' D L³ Kp - Hu L, long Hu =
  2 My / (e + 2f/3).

Kp = tan²(45° + φ'/2), γ' = σ'v / z at the middle of the averaged depth, e = 0 (the head at
the cap), My the pile's φMn at no axial force (:mod:`saengine.design.rc`; without
reinforcement only the short-pile mode). Each head fixity takes the least of its modes that
holds (a short pile whose largest moment exceeds My is intermediate or long). The allowable
lateral load of a pile in the group is the group ratio × Hu / ``factorOfSafety``, against the
cap's service shear per pile.

**p-y analysis** (method ``nonlinearSprings``): the pile a beam of EI × ``inertiaFactor`` on
nonlinear springs at its nodes (Euler-Bernoulli elements about D/2 long, at most 120), the
head shear per pile applied at the head (fixed: no rotation; free: no moment), the toe free,
the spring of each node its tributary length × p(y)/y, iterated (secant) until the deflection
settles. The p-y curve of a node's layer at the depth z below the ground:

- soft clay ``matlockSoftClay`` (Matlock 1970): pu = min((3 + σ'v/cu + J z/D) cu D, 9 cu D),
  y50 = 2.5 ε50 D, p = 0.5 pu (y/y50)^(1/3) up to pu at 8 y50;
- stiff clay ``stiffClayNoWater`` (Welch and Reese 1972): the same pu and y50, p = 0.5 pu
  (y/y50)^(1/4) up to pu at 16 y50;
- sand ``apiSand`` (API RP 2GEO, Reese et al. 1974): pu = min((C1 z + C2 D) σ'v, C3 D σ'v)
  with C1, C2, C3 of φ' (α = φ'/2, β = 45° + φ'/2, K0 = 0.4, Ka = tan²(45° - φ'/2)), p = A pu
  tanh(k z y / (A pu)), A = max(a - b z/D, 0.9), k by φ' above or below the water table;
- rock: a stiff linear spring (1000 MN/m³ × D; SAEngine practice, the method gives no curve).

The group's in-line interaction multiplies p (the group ratio as a p-multiplier). Results: the
head deflection under the service shear (against the allowable head deflection), the largest
moment and shear down the shaft under the strength shear (the moment against φMn), and the
depth of the first zero of the deflection.

Units: kN and m inside; inputs and checks as the pile cap's (N, mm; kN, kN·m, mm reported).
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

import numpy as np

from saengine.substructure import pile_lateral, pile_static

#: Unit weight of water [kN/m³] (the profile's pore pressure uses the same).
GAMMA_W = 9.81
#: K0 of the sand's ultimate resistance (Reese et al. 1974).
K0_SAND = 0.4
#: The linear spring of rock [kN/m³ per m of D].
ROCK_MODULUS = 1.0e6
#: Elements of the p-y beam: about D/2 long, between these counts.
ELEMENTS = (20, 120)


def soil_failure_rules() -> Any | None:
    found = pile_lateral.rules()
    return None if found is None else getattr(found, "soilFailure", None)


def py_rules() -> Any | None:
    found = pile_lateral.rules()
    return None if found is None else getattr(found, "pyAnalysis", None)


# ─────────────────────────────── soil ───────────────────────────────


def averaged_soil(profile: Any, head: float, depth: float) -> dict[str, Any] | None:
    """The soil over ``depth`` [m] below the pile head ``head`` [m below the borehole's
    ground]: ``{"kind": "cohesive"|"granular", "cu" kPa | "phi" °, "gamma" kN/m³ (γ'),
    "basis"}``; None when the layers lack the strength the kind needs."""
    top, bottom = head, head + depth
    cohesive = granular = 0.0
    cu_sum = phi_sum = 0.0
    for layer in profile.layers:
        lo, hi = max(layer.top, top), min(layer.bottom, bottom)
        if layer is profile.layers[-1]:
            hi = bottom
        t = hi - lo
        if t <= 0:
            continue
        if layer.behaviour == "cohesive" and layer.cu is not None:
            cohesive += t
            cu_sum += t * layer.cu
        elif layer.behaviour in ("granular", "rock") and layer.phi is not None:
            granular += t
            phi_sum += t * layer.phi
    mid = (top + bottom) / 2
    gamma = profile.sigma_v_eff(mid) / max(mid, 1e-6)
    if cohesive >= granular and cohesive > 0:
        cu = cu_sum / cohesive
        return {
            "kind": "cohesive",
            "cu": cu,
            "gamma": gamma,
            "basis": f"cohesive, cu = {cu:.0f} kPa over {depth:.1f} m below the head",
        }
    if granular > 0:
        phi = phi_sum / granular
        return {
            "kind": "granular",
            "phi": phi,
            "gamma": gamma,
            "basis": f"granular, φ' = {phi:.1f}°, γ' = {gamma:.1f} kN/m³ over {depth:.1f} m "
            "below the head",
        }
    return None


def _root(fn: Any, lo: float, hi: float) -> float:
    """The root of an increasing ``fn`` on [lo, hi] by bisection (hi when fn(hi) <= 0)."""
    if fn(hi) <= 0:
        return hi
    for _ in range(200):
        mid = (lo + hi) / 2
        if fn(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo <= 1e-9 * max(hi, 1.0):
            break
    return (lo + hi) / 2


def broms_cohesive(
    cu: float, d: float, length: float, fixity: str, my: float | None, rules: Any
) -> dict[str, Any]:
    """Broms' ultimate lateral load Hu [kN] of a pile ``d`` wide, ``length`` long [m] in
    clay of undrained strength ``cu`` [kPa], head ``fixity`` (fixed / free), yield moment
    ``my`` [kN·m] (None: unreinforced, short pile only): ``{"Hu", "mode", "f", "Mmax"}``."""
    p9 = rules.passiveCohesive * cu * d  # kN/m
    gap = rules.cohesiveGap * d
    reach = max(length - gap, 0.0)
    if reach <= 0:
        return {"Hu": 0.0, "mode": "short", "f": 0.0, "Mmax": 0.0}

    def f_of(h: float) -> float:
        return h / p9

    def at_depth(h: float) -> float:  # the largest moment below the gap (free head)
        return h * (gap + f_of(h) / 2)

    if fixity == "free":

        def short(h: float) -> float:
            g = max(length - gap - f_of(h), 0.0)
            return at_depth(h) - p9 / 4 * g * g

        hu = _root(short, 0.0, p9 * reach)
        mode, mmax = "short", at_depth(hu)
        if my is not None and mmax > my:
            hu = _root(lambda h: at_depth(h) - my, 0.0, hu)
            mode, mmax = "long", my
        return {"Hu": hu, "mode": mode, "f": f_of(hu), "Mmax": mmax}
    hu = p9 * reach
    head = hu * (length / 2 + 0.75 * d)  # Broms: Mmax = Hu (0.5 L + 0.75 D)
    if my is None or head <= my:
        return {"Hu": hu, "mode": "short", "f": f_of(hu), "Mmax": head}

    def intermediate(h: float) -> float:
        f = f_of(h)
        g = max(length - gap - f, 0.0)
        return my - (p9 / 4 * g * g - p9 * f * (gap + f / 2))

    hu = _root(intermediate, 0.0, p9 * reach)
    depth_moment = hu * (gap + f_of(hu) / 2) - my
    if depth_moment <= my:
        return {"Hu": hu, "mode": "intermediate", "f": f_of(hu), "Mmax": my}
    hu = _root(lambda h: h * (gap + f_of(h) / 2) - 2 * my, 0.0, hu)
    return {"Hu": hu, "mode": "long", "f": f_of(hu), "Mmax": my}


def broms_granular(
    phi: float, gamma: float, d: float, length: float, fixity: str, my: float | None, rules: Any
) -> dict[str, Any]:
    """Broms' ultimate lateral load Hu [kN] of a pile ``d`` wide, ``length`` long [m] in sand
    of friction angle ``phi`` [°] and effective unit weight ``gamma`` [kN/m³] (see
    :func:`broms_cohesive`)."""
    kp = math.tan(math.radians(45 + phi / 2)) ** 2
    c = rules.passiveGranular
    q = c * kp * gamma * d  # the reaction per depth, kN/m²

    def f_of(h: float) -> float:
        return math.sqrt(2 * h / q)

    def at_depth(h: float) -> float:
        return h * 2 * f_of(h) / 3

    if fixity == "free":
        hu = q / 6 * length**3 / length
        mode, mmax = "short", at_depth(hu)
        if my is not None and mmax > my:
            hu = _root(lambda h: at_depth(h) - my, 0.0, hu)
            mode, mmax = "long", my
        return {"Hu": hu, "mode": mode, "f": f_of(hu), "Mmax": mmax, "Kp": kp}
    hu = q / 2 * length**2
    head = hu * 2 * length / 3
    if my is None or head <= my:
        return {"Hu": hu, "mode": "short", "f": length, "Mmax": head, "Kp": kp}
    hu = (q / 6 * length**3 - my) / length
    if hu > 0 and at_depth(hu) - my <= my:
        return {"Hu": hu, "mode": "intermediate", "f": f_of(hu), "Mmax": my, "Kp": kp}
    hu = _root(lambda h: at_depth(h) - 2 * my, 0.0, q / 2 * length**2)
    return {"Hu": hu, "mode": "long", "f": f_of(hu), "Mmax": my, "Kp": kp}


def broms_capacity(
    profile: Any, head: float, d: float, length: float, fixity: str, my: float | None
) -> dict[str, Any] | None:
    """Broms' Hu of a pile in ``profile`` (``head`` m below its ground; ``d``, ``length`` m,
    ``my`` kN·m): the averaged soil and the mode; None without the pack's rule or soil."""
    rules = soil_failure_rules()
    if rules is None:
        return None
    soil = averaged_soil(profile, head, min(rules.averagingDepth * d, length))
    if soil is None:
        return None
    if soil["kind"] == "cohesive":
        found = broms_cohesive(soil["cu"], d, length, fixity, my, rules)
    else:
        found = broms_granular(soil["phi"], soil["gamma"], d, length, fixity, my, rules)
    return {**found, "soil": soil, "factor": rules.factorOfSafety}


# ─────────────────────────────── p-y curves ───────────────────────────────


def strain50(cu: float, rules: Any) -> float:
    """ε50 of the clay by the pack's cu bands."""
    for limit, value in rules.strain50:
        if cu <= limit:
            return float(value)
    return float(rules.strain50[-1][1])


def sand_modulus(phi: float, wet: bool, rules: Any) -> float:
    """k of sand [kN/m³] by φ', above or below the water table (linear, the end values
    outside)."""
    rows = sorted(rules.sandModulus)
    column = 2 if wet else 1
    if phi <= rows[0][0]:
        return rows[0][column] * 1e3
    for a, b in pairwise(rows):
        if phi <= b[0]:
            t = (phi - a[0]) / (b[0] - a[0])
            return (a[column] + t * (b[column] - a[column])) * 1e3
    return rows[-1][column] * 1e3


def sand_coefficients(phi: float) -> tuple[float, float, float]:
    """C1, C2, C3 of the sand's ultimate resistance (Reese et al. 1974, API RP 2GEO)."""
    p = math.radians(phi)
    a = p / 2
    b = math.radians(45) + p / 2
    ka = math.tan(math.radians(45) - p / 2) ** 2
    tb, tbp = math.tan(b), math.tan(b - p)
    c1 = (
        K0_SAND * math.tan(p) * math.sin(b) / (tbp * math.cos(a))
        + tb * tb * math.tan(a) / tbp
        + K0_SAND * tb * (math.tan(p) * math.sin(b) - math.tan(a))
    )
    c2 = tb / tbp - ka
    c3 = ka * (tb**8 - 1) + K0_SAND * math.tan(p) * tb**4
    return c1, c2, c3


def py_curve(layer: Any, z: float, d: float, sigma: float, wet: bool, rules: Any):
    """The p-y curve of ``layer`` at ``z`` m below the ground (σ'v ``sigma`` kPa, ``wet``
    below the water table) of a pile ``d`` wide: ``(p(y) [kN/m] for y [m], name)``; None
    when the layer lacks its strength."""
    z = max(z, 1e-3)
    if layer.behaviour == "rock":
        k = ROCK_MODULUS * d
        return (lambda y: k * y), "rock (linear)"
    if layer.behaviour == "cohesive":
        if layer.cu is None:
            return None
        cu = float(layer.cu)
        pu = min((3 + sigma / cu + rules.clayJ * z / d) * cu * d, 9 * cu * d)
        y50 = 2.5 * strain50(cu, rules) * d
        stiff = cu >= rules.stiffClayCu and rules.stiffClay == "stiffClayNoWater"
        power, reach = (0.25, 16.0) if stiff else (1 / 3, 8.0)
        name = "stiff clay (Welch & Reese)" if stiff else "soft clay (Matlock)"

        def clay(y: float, pu: float = pu, y50: float = y50) -> float:
            s = abs(y)
            p = pu if s >= reach * y50 else 0.5 * pu * (s / y50) ** power
            return math.copysign(min(p, pu), y)

        return clay, name
    if layer.phi is None:
        return None
    phi = float(layer.phi)
    c1, c2, c3 = sand_coefficients(phi)
    pu = max(min((c1 * z + c2 * d) * sigma, c3 * d * sigma), 1e-6)
    a = max(rules.sandCoefficient[0] - rules.sandCoefficient[1] * z / d, 0.9)
    k = sand_modulus(phi, wet, rules)

    def sand(y: float, pu: float = pu, a: float = a, k: float = k, z: float = z) -> float:
        return a * pu * math.tanh(k * z * y / (a * pu))

    return sand, "sand (API)"


def _beam(length: float, count: int, ei: float) -> np.ndarray:
    """The stiffness matrix of a beam of ``count`` equal Euler-Bernoulli elements (DOFs y, θ
    per node)."""
    le = length / count
    k = (
        ei
        / le**3
        * np.array(
            [
                [12, 6 * le, -12, 6 * le],
                [6 * le, 4 * le * le, -6 * le, 2 * le * le],
                [-12, -6 * le, 12, -6 * le],
                [6 * le, 2 * le * le, -6 * le, 4 * le * le],
            ]
        )
    )
    n = 2 * (count + 1)
    out = np.zeros((n, n))
    for e in range(count):
        s = slice(2 * e, 2 * e + 4)
        out[s, s] += k
    return out


def py_analysis(
    profile: Any,
    head: float,
    d: float,
    length: float,
    ei: float,
    fixity: str,
    shear: float,
    multiplier: float = 1.0,
) -> dict[str, Any] | None:
    """The pile on p-y springs under a head shear ``shear`` [kN] (``head`` m below the
    borehole's ground, ``d``, ``length`` m, ``ei`` kN·m², ``fixity`` fixed / free,
    ``multiplier`` the p-multiplier): ``{"y0" m, "Mmax" kN·m, "zM" m, "Vmax" kN, "Mhead",
    "zeroDepth" m | None, "converged", "curves"}``; None without the pack's method or soil."""
    rules = py_rules()
    if rules is None or length <= 0 or d <= 0:
        return None
    ei = ei * rules.inertiaFactor
    count = int(min(max(round(length / (d / 2)), ELEMENTS[0]), ELEMENTS[1]))
    le = length / count
    zs = np.linspace(0.0, length, count + 1)
    curves = []
    names: set[str] = set()
    for z in zs:
        depth = head + z
        layer = profile.layer_at(depth + 1e-6)
        if layer is None:
            return None
        found = py_curve(
            layer, depth, d, profile.sigma_v_eff(depth), profile.below_water(depth), rules
        )
        if found is None:
            return None
        curves.append(found[0])
        names.add(found[1])
    trib = np.full(count + 1, le)
    trib[0] = trib[-1] = le / 2
    base = _beam(length, count, ei)
    n = base.shape[0]
    force = np.zeros(n)
    force[0] = shear
    free = [i for i in range(n) if not (fixity == "fixed" and i == 1)]
    # The initial secant: each curve's slope at a small deflection.
    y_ref = 1e-4 * d
    springs = np.array([max(c(y_ref) / y_ref, 1e-6) for c in curves]) * trib * multiplier
    u = np.zeros(n)
    converged = False
    lateral_dofs = np.arange(0, n, 2)
    for _ in range(200):
        k = base.copy()
        k[lateral_dofs, lateral_dofs] += springs
        sub = k[np.ix_(free, free)]
        u_new = np.zeros(n)
        u_new[free] = np.linalg.solve(sub, force[free])
        y = u_new[0::2]
        new = (
            np.array(
                [
                    max(abs(c(float(v))) / max(abs(float(v)), 1e-12), 1e-6)
                    if abs(v) > 1e-12
                    else springs[i] / (trib[i] * multiplier)
                    for i, (c, v) in enumerate(zip(curves, y, strict=True))
                ]
            )
            * trib
            * multiplier
        )
        change = np.max(np.abs(u_new - u)) / max(np.max(np.abs(u_new)), 1e-12)
        u = u_new
        springs = 0.5 * springs + 0.5 * new
        if change < 1e-5:
            converged = True
            break
    y = u[0::2]
    theta = u[1::2]
    # Element end moments and shears from the element stiffness.
    moments = np.zeros(count + 1)
    shears = np.zeros(count + 1)
    kel = _beam(le, 1, ei)
    local = np.zeros(4)
    for e in range(count):
        local = kel @ u[2 * e : 2 * e + 4]  # [V1, M1, V2, M2] on the element
        moments[e], shears[e] = -local[1], local[0]
    moments[count], shears[count] = local[3], -local[2]
    zero = None
    for i in range(1, count + 1):
        if y[i - 1] * y[i] < 0:
            zero = float(zs[i - 1] + le * y[i - 1] / (y[i - 1] - y[i]))
            break
    peak = int(np.argmax(np.abs(moments)))
    return {
        "y0": float(y[0]),
        "theta0": float(theta[0]),
        "Mmax": float(abs(moments[peak])),
        "zM": float(zs[peak]),
        "Vmax": max(float(np.max(np.abs(shears))), abs(shear)),  # the head shear is H
        "Mhead": float(abs(moments[0])) if fixity == "fixed" else 0.0,
        "zeroDepth": zero,
        "converged": converged,
        "curves": sorted(names),
        "elements": count,
    }


# ─────────────────────────────── checks ───────────────────────────────


def bending_capacity(
    diameter: float, fc: float, fy: float, reinforcement: Any, square: bool
) -> float | None:
    """φMn [N·mm] of the pile section at no axial force; None without bars."""
    from saengine.design.rc import DesignError, InteractionSurface, section_of
    from saengine.library.objects import CircleProfile, RectangleProfile
    from saengine.substructure.pilehead import _surface

    if reinforcement is None or not reinforcement.longitudinal:
        return None
    shape = (
        RectangleProfile(xDim=diameter, yDim=diameter)
        if square
        else CircleProfile(radius=diameter / 2)
    )
    try:
        section = section_of(shape, reinforcement, fc, fy)
    except DesignError:
        return None
    surface = _surface(section, (square, diameter, fc, fy, reinforcement), InteractionSurface)
    result = surface.check(0.0, 1.0, 0.0)
    return float(result.phi_mn) if result.phi_mn > 0 else None


def soil_checks(
    profile: Any,
    head: float,
    diameter: float,
    length: float,
    ei: float,
    fixity: str,
    phi_mn: float | None,
    service: dict[str, np.ndarray],
    strength: dict[str, np.ndarray],
    count: int,
    ratio: float,
    allowable: float | None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """The soil failure and p-y checks of one pile of a cap (see the module notes):
    ``head`` m below the borehole's ground, ``diameter``, ``length`` mm, ``ei`` N·mm²,
    ``phi_mn`` N·mm, ``service`` / ``strength`` the cap's shears ``[Hu, Hv]`` [N] per
    combination shared by ``count`` piles, ``ratio`` the group ratio, ``allowable`` the pile
    type's head deflection [mm] (None: the pack's). Returns ``(checks, notes, detail)``."""
    from saengine.design.check import _check

    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    detail: dict[str, Any] = {}
    if profile is None or not service:
        return checks, notes, detail
    d, length_m = diameter / 1e3, length / 1e3
    my = phi_mn / 1e6 if phi_mn else None

    def per_pile(shears: dict[str, np.ndarray]) -> tuple[str, float]:
        worst = max(shears, key=lambda k: float(np.hypot(*shears[k])))
        return worst, float(np.hypot(*shears[worst])) / max(count, 1) / 1e3

    worst, h_service = per_pile(service)
    rules = soil_failure_rules()
    if rules is None:
        notes.append(pile_static.not_covered("Lateral soil failure of piles"))
    else:
        found = broms_capacity(profile, head, d, length_m, fixity, my)
        if found is None:
            notes.append(
                "lateral soil failure (Broms) not checked: the layers below the pile head have "
                "no cu or φ' in the soil report"
            )
        else:
            allowed = ratio * found["Hu"] / found["factor"]
            checks.append(
                _check(
                    "Pile lateral load, soil failure (Broms)",
                    h_service,
                    allowed,
                    "kN",
                    worst,
                    f"Hu = {found['Hu']:.0f} kN ({found['mode']} pile, {fixity} head; "
                    f"{found['soil']['basis']}"
                    + (f", My = φMn = {my:.0f} kN·m" if my else ", no bars: short pile only")
                    + f") / FS {found['factor']:g} × group ratio {ratio:.2f} "
                    f"({pile_lateral.cite('lateral.soilFailure')})",
                )
            )
            detail["broms"] = {
                "Hu": round(found["Hu"], 1),
                "mode": found["mode"],
                "allowable": round(allowed, 1),
                "soil": found["soil"]["kind"],
            }
    py = py_rules()
    if py is None:
        notes.append(pile_static.not_covered("p-y analysis of piles"))
        return checks, notes, detail
    found = py_analysis(profile, head, d, length_m, ei * 1e-9, fixity, h_service, ratio)
    if found is None:
        notes.append(
            "p-y analysis not done: a layer along the pile has no cu or φ' in the soil report"
        )
        return checks, notes, detail
    limit = allowable or pile_lateral.rules().allowableDeflection
    where = (
        f"{', '.join(found['curves'])}; p × group ratio {ratio:.2f}; {found['elements']} "
        f"elements, EI × {py.inertiaFactor:g} ({pile_lateral.cite('lateral.pyAnalysis')})"
    )
    if not found["converged"]:
        notes.append("p-y analysis: the iteration did not settle; the results are approximate")
    checks.append(
        _check(
            "Pile head deflection (p-y)",
            abs(found["y0"]) * 1e3,
            limit,
            "mm",
            worst,
            f"H = {h_service:.1f} kN per pile, {fixity} head; {where}",
        )
    )
    detail["py"] = {
        "y0": round(abs(found["y0"]) * 1e3, 2),
        "zeroDepth": None if found["zeroDepth"] is None else round(found["zeroDepth"] * 1e3),
        "Mmax": round(found["Mmax"], 1),
        "zM": round(found["zM"] * 1e3),
    }
    if strength:
        name, h_strength = per_pile(strength)
        factored = py_analysis(profile, head, d, length_m, ei * 1e-9, fixity, h_strength, ratio)
        if factored is not None:
            detail["py"]["MmaxStrength"] = round(factored["Mmax"], 1)
            detail["py"]["VmaxStrength"] = round(factored["Vmax"], 1)
            checks.append(
                _check(
                    "Pile moment (p-y)",
                    factored["Mmax"],
                    (phi_mn or 0.0) / 1e6,
                    "kN·m",
                    name,
                    f"H = {h_strength:.1f} kN per pile: the largest moment {factored['Mmax']:.1f} "
                    f"kN·m at {factored['zM']:.2f} m below the head, the largest shear "
                    f"{factored['Vmax']:.1f} kN; against φMn at no axial force"
                    + ("" if phi_mn else " (no bars: a plain pile cannot carry it)")
                    + f"; {where}",
                )
            )
    return checks, notes, detail

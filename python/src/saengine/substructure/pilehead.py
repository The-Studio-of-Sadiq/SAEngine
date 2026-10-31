"""Pile heads under lateral load: shear, head moment and the pile section (Part 9, deep
foundations).

The horizontal forces of the columns on a pile cap (their support reactions, reversed, in the
cap's axes: :func:`cap_shears`) are shared equally by its piles: the cap is rigid and the piles
of a cap are of one type, so they deflect alike and take equal shears, ``H = (Hu, Hv) / n``.

Head moment by the equivalent cantilever: the pile acts as fixed at the depth to fixity ``Lf``
below its head (``PileType.fixityDepth``, from the geotechnical report; the lateral pile
analysis that finds it, by Broms or by p-y springs, is a planned feature). Statics of a member
of length Lf under a head shear H:

- head fixed in the cap (the pile bars developed into it, BNBC 2020 Part 6 Sec 3.10.1.20): the
  head translates without rotating, so the moment is ``H Lf / 2`` at the head and, reversed, at
  the depth to fixity;
- head free (pinned): no moment at the head, ``H Lf`` at the depth to fixity.

The pile section is designed for the larger of the two (``M = H Lf / 2`` fixed, ``H Lf`` free)
with the pile's factored axial forces, the largest compression and the largest tension of each
strength combination, on the P-M interaction surface of the circular section
(:class:`saengine.design.rc.InteractionSurface`, ACI 318-19 22.4 with φ of Table 21.2.2; BNBC
2020 Part 6 Sec 6.3 follows the same strength design). The pile is fully embedded, so it is not
a long column where cu > 10 kPa (BNBC Sec 3.10.1.31): no moment magnification. The shear of the
section: ACI 318-19 22.5.2.2 for a circle (bw = D, d = 0.8 D), Vc of Table 22.5.5.1 (a) with
at least Av,min (9.6.3.4) and (c) without (ρw of the bars on the tension half), Vs = Av fyt d / s
with the two legs of a hoop or spiral, φ = 0.75.

A fixed head puts its moment back into the cap: the cap's face moments take ``Σ H Lf / 2`` of
the piles beyond each face, added in the sense that increases the moment (the lateral load
reverses), :func:`saengine.substructure.pilecap.cap_checks`. The pile loads of the rigid cap
are left as they are: the head moments would relieve the push-pull of the overturning moment,
which is on the safe side to ignore.

Units: N and mm inside; reported in kN and kN·m.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

#: Strength reduction factor for shear (ACI 318-19 Table 21.2.1).
PHI_SHEAR = 0.75
#: fyt in shear at most 420 MPa (ACI 318-19 20.2.2.4).
FYT_MAX = 420.0

FIXITIES = ("fixed", "free")

METHOD = (
    "Pile heads: the columns' horizontal reactions shared equally by the cap's piles (rigid "
    "cap, piles of one type); head moment by the equivalent cantilever to the depth to fixity "
    "Lf from the geotechnical report: H Lf / 2 at a head fixed in the cap, H Lf at the depth to "
    "fixity for a free head. The pile section (ACI 318-19 22.4, P-M surface of the circle; "
    "fully embedded, not a long column, BNBC 2020 Part 6 Sec 3.10.1.31) for that moment with "
    "the largest factored compression and tension, and its shear by 22.5 (bw = D, d = 0.8 D). "
    "Fixed heads add Σ H Lf / 2 of the piles beyond each face to the cap's face moments."
)


def cap_shears(loads: Any, placed: Any) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """The total horizontal force ``[Hu, Hv]`` [N] the columns of a placed cap put on it, in its
    axes, per service and per strength combination (all combinations at once, as
    :func:`saengine.substructure.shallow.footing_loads`)."""
    from saengine.substructure.shallow import _factors

    zero = np.zeros(6)
    cases = list(loads.cases)
    per_case = np.zeros((len(cases), 2))
    for k, case in enumerate(cases):
        for node in placed.nodes:
            force = -np.asarray(loads.cases[case].get(node, zero)[:3], dtype=float)
            per_case[k] += (float(force @ placed.axis_u), float(force @ placed.axis_v))

    def combined(combinations: list[tuple[str, dict[str, float]]]) -> dict[str, np.ndarray]:
        values = _factors(cases, combinations) @ per_case
        return {name: values[k] for k, (name, _) in enumerate(combinations)}

    return combined(loads.service), combined(loads.strength)


def head_actions(shear: np.ndarray, count: int, fixity: str, depth: float | None) -> dict[str, Any]:
    """One pile's head shear ``[Hu, Hv]`` [N], its head moment ``[Mu, Mv]`` [N·mm] (the moment
    bending the pile in the u and v directions, put back into the cap; zero for a free head)
    and the design moment of its section [N·mm] (the resultant), of a cap's total horizontal
    force ``shear`` shared by ``count`` piles; ``depth`` the depth to fixity [mm] (none: no
    moment)."""
    if fixity not in FIXITIES:
        raise ValueError(f"pile head fixity {fixity!r}: fixed or free")
    h = np.asarray(shear, dtype=float) / max(count, 1)
    if not depth or depth <= 0:
        return {"H": h, "head": np.zeros(2), "design": 0.0}
    resultant = math.hypot(float(h[0]), float(h[1]))
    if fixity == "fixed":
        return {"H": h, "head": h * depth / 2, "design": resultant * depth / 2}
    return {"H": h, "head": np.zeros(2), "design": resultant * depth}


def shear_capacity(diameter: float, fc: float, fy: float, reinforcement: Any) -> dict[str, float]:
    """φVn [N] of a circular pile section (ACI 318-19 22.5.2.2: bw = D, d = 0.8 D), Nu = 0:
    Vc = 0.17 λ √f'c bw d with at least Av,min (Table 22.5.5.1 (a), 9.6.3.4), else 0.66 λs
    ρw^(1/3) √f'c bw d (c) with ρw = As/2 / (bw d), both ≤ 0.42 √f'c bw d; Vs = Av fyt d / s
    ≤ 0.66 √f'c bw d with Av the two legs of a hoop or spiral."""
    bw, d = diameter, 0.8 * diameter
    root = min(math.sqrt(fc), 8.3)
    fyt = min(fy, FYT_MAX)
    longitudinal = getattr(reinforcement, "longitudinal", None) or []
    steel = sum(g.count * math.pi * g.dia**2 / 4 for g in longitudinal)
    transverse = getattr(reinforcement, "transverse", None)
    av = s = 0.0
    if transverse is not None and transverse.spacing > 0:
        av, s = 2 * math.pi * transverse.dia**2 / 4, float(transverse.spacing)
    av_min = max(0.062 * root, 0.35) * bw * s / fyt if av else 0.0
    if av and av >= av_min:
        vc = 0.17 * root * bw * d
    else:
        rho = max(steel / 2 / (bw * d), 1e-6)
        size = min(1.0, math.sqrt(2 / (1 + 0.004 * d)))
        vc = 0.66 * size * rho ** (1 / 3) * root * bw * d
    vc = min(vc, 0.42 * root * bw * d)
    vs = min(av * fyt * d / s, 0.66 * math.sqrt(fc) * bw * d) if av else 0.0
    minimum = bool(av) and av >= av_min
    return {"phiVn": PHI_SHEAR * (vc + vs), "Vc": vc, "Vs": vs, "d": d, "minimum": minimum}


def plain_shear_capacity(diameter: float, fc: float) -> float:
    """φVn [N] of a plain concrete pile: 0.60 × 0.11 √f'c bw h with bw = h = D (ACI 318-19
    14.5.5.1 (a), φ of Table 21.2.1)."""
    return 0.60 * 0.11 * math.sqrt(fc) * diameter * diameter


def section_checks(
    diameter: float,
    fc: float,
    fy: float,
    reinforcement: Any,
    axial: dict[str, tuple[float, float]],
    shears: dict[str, np.ndarray],
    count: int,
    fixity: str,
    depth: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The pile section under axial force and the head moment (see the module notes):
    ``axial`` per strength combination the largest and least factored pile load [N]
    (compression positive), ``shears`` per strength combination the cap's ``[Hu, Hv]`` [N].
    Returns ``(checks, detail)``, ``detail`` the governing head shear and moments [kN, kN·m]."""
    from saengine.design.check import _check
    from saengine.design.rc import DesignError, InteractionSurface, section_of
    from saengine.library.objects import CircleProfile

    detail: dict[str, Any] = {"fixity": fixity, "fixityDepth": depth, "H": 0.0, "M": 0.0}
    if not shears:
        return [], detail
    worst = max(shears, key=lambda name: float(np.hypot(*shears[name])))
    actions = {name: head_actions(h, count, fixity, depth) for name, h in shears.items()}
    governing = actions[worst]
    detail.update(
        H=round(float(np.hypot(*governing["H"])) / 1e3, 1),
        M=round(governing["design"] / 1e6, 1),
        headMoment=[round(float(m) / 1e6, 1) for m in governing["head"]],
        combination=worst,
    )
    checks: list[dict[str, Any]] = []
    if not depth:
        detail["note"] = (
            "no depth to fixity: the piles are designed for axial force only; enter it from the "
            "geotechnical report (the lateral pile analysis is planned)"
        )
        return checks, detail
    where = (
        f"H Lf / 2 at the head fixed in the cap, Lf = {depth:.0f} mm"
        if fixity == "fixed"
        else f"H Lf at the depth to fixity, free head, Lf = {depth:.0f} mm"
    )
    section = None
    reason = "no reinforcement"
    if reinforcement is not None and reinforcement.longitudinal:
        try:
            section = section_of(CircleProfile(radius=diameter / 2), reinforcement, fc, fy)
        except DesignError as error:
            reason = str(error)
    if section is None:
        moment = max(a["design"] for a in actions.values())
        if moment > 0:
            checks.append(
                _check(
                    "Pile section, axial + moment",
                    moment / 1e6,
                    0.0,
                    "kN·m",
                    worst,
                    f"{reason}: a plain pile cannot carry the head moment ({where}); reinforce it",
                )
            )
    else:
        surface = InteractionSurface(section)
        best = (-1.0, 0.0, 0.0, 0.0, None)
        for name, (most, least) in axial.items():
            moment = actions[name]["design"]
            for pu in (most, least):
                result = surface.check(pu, moment, 0.0)
                if result.utilisation > best[0]:
                    best = (result.utilisation, pu, moment, result.phi_mn, name)
        ratio, pu, moment, phi_mn, name = best
        if name is not None:
            bars = ", ".join(f"{g.count}Ø{g.dia:g}" for g in reinforcement.longitudinal)
            checks.append(
                _check(
                    "Pile section, axial + moment",
                    moment / 1e6,
                    phi_mn / 1e6,
                    "kN·m",
                    name,
                    f"ACI 318-19 22.4 P-M surface of the Ø{diameter:.0f} section, {bars}, at Pu = "
                    f"{pu / 1e3:.0f} kN; {where}; fully embedded: not a long column (BNBC 2020 "
                    "Part 6 Sec 3.10.1.31)",
                    utilisation=ratio,
                )
            )
    vu = float(np.hypot(*governing["H"]))
    if section is None:
        capacity = plain_shear_capacity(diameter, fc)
        text = f"{reason}: plain concrete, φVn = 0.60 × 0.11 √f'c D² (ACI 318-19 14.5.5.1 (a))"
    else:
        shear = shear_capacity(diameter, fc, fy, reinforcement)
        capacity = shear["phiVn"]
        text = (
            f"ACI 318-19 22.5.2.2: bw = D, d = 0.8 D = {shear['d']:.0f} mm; Vc = "
            f"{shear['Vc'] / 1e3:.0f} kN (Table 22.5.5.1 {'(a)' if shear['minimum'] else '(c)'}), "
            f"Vs = {shear['Vs'] / 1e3:.0f} kN"
        )
    checks.append(
        _check(
            "Pile section, shear",
            vu / 1e3,
            capacity / 1e3,
            "kN",
            worst,
            f"{text}; H shared equally by {count} piles",
        )
    )
    return checks, detail

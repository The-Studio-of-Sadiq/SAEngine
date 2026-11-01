"""Lateral load on piles by the code pack (Part 9, deep foundations).

The code pack's ``foundations.piles.lateral`` group holds the rules (BNBC 2020: Sec 3.10.1.21
for single piles, Sec 3.10.6.15 and Table 6.3.16 for groups, Sec 3.11.4 for load tests); a
pack without it does not cover them. The allowable lateral load of a pile is the least of
soil failure, the structure of the pile and the deflection of its head:

- **head deflection** (:func:`head_stiffness`): the pile a long beam on the Winkler springs
  the soil-structure interaction builds (:func:`saengine.fem.ssi.pile_lateral_stiffness`, the
  line modulus by Vesic from the soil report's SPT at the nearest borehole and the same G/G0):
  ``Khh = 4 EI β³`` with the head fixed in the cap, ``2 EI β³`` with a free head (Hetényi
  1946). The service head shear per pile over ``ratio × Khh`` against the pile type's
  allowable deflection, else the pack's;
- **group action** (:func:`group_ratio`): piles act individually beyond ``individualNormal`` B
  normal to the load and ``individualParallel`` B along it; otherwise each pile with an in-line
  neighbour (within ``individualNormal`` B across the load) takes the pack's ratio at its
  least in-line spacing (``groupRatio``, interpolated, its end values outside). The group's
  ratio, the mean of its piles', multiplies the head stiffness (and the analysis' cap springs,
  :mod:`saengine.fem.ssi`) and a load test's allowable load;
- **structure**: the pile section under the head moment and the axial load
  (:mod:`saengine.substructure.pilehead`), with the depth to fixity of the pile type or, when
  it has none, ``1.4 R`` (``R = (EI / k)^¼``, the Winkler springs' relative stiffness:
  Davisson & Robinson 1965 for a constant modulus, SAEngine practice);
- **unbraced piles** (:func:`unbraced_checks`): a pile standing in air, water or scour (the
  pile type's unbraced length) or in soil weaker than the pack's ``unbracedCu`` from the pile
  head down is designed as a column: ``lu`` that length plus the depth to fixity below it,
  ``k`` 1.0 with the head fixed in the cap (sway, fixed at both ends) or 2.0 free,
  ``Pc = π² 0.4 Ec Ig / (k lu)²`` and ``δ = 1 / (1 - Pu / 0.75 Pc)`` on the larger of the head
  moment and ``Pu (15 + 0.03 h)`` (ACI 318-19 6.6.4, Cm = 1), on the P-M surface;
- **load tests** (:mod:`saengine.substructure.load_tests`): a lateral load test of the pile
  type gives its allowable lateral load directly;
- **soil failure** (Broms) and p-y analysis are planned features: not checked.

Units: N and mm inside; reported in kN, kN·m and mm.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np

from saengine.substructure import pile_static


def rules() -> Any | None:
    """The pack's lateral pile rules, or None when the pack does not cover them."""
    found = pile_static.rules()
    return None if found is None else found.lateral


def cite(key: str) -> str:
    from saengine.substructure.pile_detailing import cite as _cite

    return _cite(key)


def table_ratio(points: list[Any], spacing: float) -> float:
    """The ratio of the pack's in-line table at a spacing [× B] (interpolated, its end values
    outside)."""
    rows = sorted((float(s), float(r)) for s, r in points)
    if spacing <= rows[0][0]:
        return rows[0][1]
    for (s0, r0), (s1, r1) in itertools.pairwise(rows):
        if spacing <= s1:
            return r0 + (r1 - r0) * (spacing - s0) / (s1 - s0)
    return rows[-1][1]


def group_ratio(
    piles: list[tuple[float, float]] | np.ndarray, diameter: float, axis: int
) -> tuple[float, str]:
    """The group's ratio of lateral resistance for a load along ``axis`` (0: the first
    coordinate, 1: the second) of piles at ``piles`` [mm] of ``diameter`` [mm], and how it was
    found (see the module notes); 1.0 when the pack has no rule."""
    found = rules()
    points = [tuple(map(float, p)) for p in piles]
    if found is None or len(points) < 2:
        return 1.0, "" if found is not None else pile_static.not_covered("Lateral group action")
    across = 1 - axis
    ratios = []
    side_by_side = False
    for k, p in enumerate(points):
        spacing = math.inf
        for m, q in enumerate(points):
            if m == k:
                continue
            normal = abs(q[across] - p[across])
            along = abs(q[axis] - p[axis])
            if normal > found.individualNormal * diameter + 1e-6:
                continue
            if along < 1e-6:
                side_by_side = True
                continue
            spacing = min(spacing, along)
        if spacing / diameter > found.individualParallel or not math.isfinite(spacing):
            ratios.append(1.0)
        else:
            ratios.append(table_ratio(found.groupRatio, spacing / diameter))
    ratio = float(np.mean(ratios))
    least = min(ratios)
    note = (
        f"group ratio {ratio:.2f} (the mean of the piles'; least {least:.2f}): piles act "
        f"individually beyond {found.individualNormal:g} B across and "
        f"{found.individualParallel:g} B along the load ({cite('lateral.groupRatio')})"
    )
    if side_by_side:
        note += (
            f"; piles side by side within {found.individualNormal:g} B across the load: the "
            "code gives no ratio for them, their interaction is not reduced"
        )
    return ratio, note


def soil_ratio(settings: Any) -> float:
    """G/G0 the soil springs use (Project Settings -> Analysis, else the site's)."""
    from saengine.fem import ssi

    options = ssi.options_from_settings(settings) if settings is not None else ssi.SsiOptions()
    if options.shear_modulus_ratio is not None:
        return float(options.shear_modulus_ratio)
    try:
        acceleration = ssi.peak_acceleration(settings) if settings is not None else None
    except Exception:  # noqa: BLE001 - no site data: the small-strain modulus
        acceleration = None
    return ssi.shear_modulus_ratio(acceleration)


def head_stiffness(
    profile: Any,
    head: float,
    kind: str,
    diameter: float,
    length: float,
    ep: float,
    fixity: str,
    ratio: float,
) -> dict[str, Any] | None:
    """The Winkler head stiffness of a pile (``head`` m below the borehole's ground,
    ``diameter`` and ``length`` mm, ``ep`` MPa): ``{"K" N/mm, "kB" N/mm², "beta" 1/mm,
    "R" mm, "basis"}``; None without SPT."""
    from saengine.fem import ssi

    d = diameter / 1e3
    inertia = d**4 / 12 if kind == "driven" else math.pi * d**4 / 64
    top = ssi.soil_average(profile, head, head + min(length / 1e3, ssi.PILE_LATERAL_DIAMETERS * d))
    if top is None:
        return None
    es = 2 * ratio * top.g0 * (1 + top.nu)
    lateral = ssi.pile_lateral_stiffness(ep * 1e6, inertia, d, es, top.nu)
    ei = ep * 1e6 * inertia
    beta = lateral["beta"]
    k = 4 * ei * beta**3 if fixity == "fixed" else 2 * ei * beta**3
    relative = (ei / lateral["kB"]) ** 0.25  # m
    return {
        "K": k / 1e3,  # N/m -> N/mm
        "kB": lateral["kB"] / 1e6,
        "beta": beta / 1e3,
        "R": relative * 1e3,
        "basis": (
            f"Winkler: kB = {lateral['kB'] / 1e3:.0f} kN/m², β = {beta:.3f} /m, "
            f"{'4' if fixity == 'fixed' else '2'} EI β³ = {k / 1e3:.0f} kN/m ({fixity} head); "
            + top.basis(ratio)
        ),
        "betaL": beta * length / 1e3,
    }


def fixity_depth(stiffness: dict[str, Any] | None) -> float | None:
    """The depth to fixity [mm] of a pile on the Winkler springs: 1.4 R (Davisson & Robinson
    1965, constant modulus; SAEngine practice)."""
    if stiffness is None:
        return None
    return 1.4 * stiffness["R"]


def unsupported_length(profile: Any, head: float, given: float | None) -> tuple[float, str]:
    """The length [mm] of a pile without lateral support: the pile type's unbraced length
    plus the soil from the pile head down whose cu is below the pack's limit."""
    found = rules()
    length = float(given or 0.0)
    why = [f"{length:.0f} mm unbraced (pile type)"] if given else []
    if found is not None and profile is not None:
        z = head
        weak = 0.0
        while True:
            layer = profile.layer_at(z + 1e-6)
            if layer is None or layer.behaviour != "cohesive" or layer.cu is None:
                break
            if layer.cu >= found.unbracedCu:
                break
            weak += (layer.bottom - z) * 1e3
            z = layer.bottom
        if weak > 0:
            length += weak
            why.append(
                f"{weak:.0f} mm of soil with cu < {found.unbracedCu:g} kPa below the head "
                f"({cite('lateral.unbracedCu')})"
            )
    return length, "; ".join(why)


def unbraced_checks(
    diameter: float,
    square: bool,
    fc: float,
    fy: float,
    ec: float,
    reinforcement: Any,
    axial: dict[str, tuple[float, float]],
    moments: dict[str, float],
    unsupported: float,
    depth: float | None,
    fixity: str,
    why: str,
) -> list[dict[str, Any]]:
    """The column check of a pile with an unsupported length [mm] (see the module notes):
    ``axial`` per strength combination the largest and least factored pile load [N],
    ``moments`` per combination the pile's design moment [N·mm], ``ec`` MPa."""
    from saengine.design.check import _check
    from saengine.design.rc import DesignError, InteractionSurface, section_of
    from saengine.design.slender import critical_load
    from saengine.library.objects import CircleProfile, RectangleProfile

    if unsupported <= 0 or not axial:
        return []
    lu = unsupported + (depth or 0.0)
    k = 1.0 if fixity == "fixed" else 2.0
    ig = diameter**4 / 12 if square else math.pi * diameter**4 / 64
    pc = critical_load(0.4 * ec * ig, k, lu)
    section = None
    if reinforcement is not None and reinforcement.longitudinal:
        profile = (
            RectangleProfile(xDim=diameter, yDim=diameter)
            if square
            else CircleProfile(radius=diameter / 2)
        )
        try:
            section = section_of(profile, reinforcement, fc, fy)
        except DesignError:
            section = None
    where = (
        f"lu = {lu:.0f} mm ({why}" + (f", + {depth:.0f} mm to fixity" if depth else "") + "), "
        f"k = {k:g} ({fixity} head), Pc = π² 0.4 Ec Ig / (k lu)² = {pc / 1e3:.0f} kN "
        f"(ACI 318-19 6.6.4; {cite('lateral.unbracedCu')})"
    )
    if section is None:
        worst = max(axial, key=lambda n: axial[n][0])
        return [
            _check(
                "Unbraced pile as a column",
                axial[worst][0] / 1e3,
                0.0,
                "kN",
                worst,
                f"no reinforcement: an unbraced pile is a column and must be reinforced; {where}",
            )
        ]
    surface = InteractionSurface(section)
    best = (-1.0, 0.0, 0.0, 0.0, None, 1.0)
    for name, (most, _least) in axial.items():
        pu = max(most, 0.0)
        if pu >= 0.75 * pc:
            best = (math.inf, pu, math.inf, 0.0, name, math.inf)
            break
        delta = 1.0 / (1.0 - pu / (0.75 * pc))
        m2 = max(moments.get(name, 0.0), pu * (15 + 0.03 * diameter))
        mc = delta * m2
        result = surface.check(pu, mc, 0.0)
        if result.utilisation > best[0]:
            best = (result.utilisation, pu, mc, result.phi_mn, name, delta)
    ratio, pu, mc, phi_mn, name, delta = best
    return [
        _check(
            "Unbraced pile as a column",
            mc / 1e6 if math.isfinite(mc) else 0.0,
            phi_mn / 1e6,
            "kN·m",
            name,
            f"Pu = {pu / 1e3:.0f} kN, δ = {delta:.2f} on the larger of the head moment and Pu "
            f"(15 + 0.03 h); {where}",
            utilisation=ratio,
        )
    ]


def lateral_checks(
    service_shears: dict[str, np.ndarray],
    count: int,
    stiffness: dict[str, Any] | None,
    ratios: tuple[float, float],
    allowable: float | None,
    tested: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The head deflection and the load test checks of one pile under the cap's service
    shears ``[Hu, Hv]`` [N] shared by ``count`` piles: ``ratios`` the group ratios along u and
    v, ``allowable`` the pile type's head deflection [mm] (None: the pack's), ``tested`` the
    pile type's lateral load test result (:func:`saengine.substructure.load_tests.interpret`).
    Returns ``(checks, notes)``."""
    from saengine.design.check import _check

    found = rules()
    if found is None:
        return [], [pile_static.not_covered("Lateral pile capacity")]
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    if not service_shears:
        return checks, notes
    ru, rv = ratios
    limit = allowable or found.allowableDeflection
    source = (
        "the pile type's performance requirement"
        if allowable
        else f"{found.allowableDeflection:g} mm ({cite('lateral.allowableDeflection')})"
    )
    if stiffness is not None:
        worst, deflection, shear = None, -1.0, 0.0
        for name, h in service_shears.items():
            hu, hv = (float(x) / max(count, 1) for x in h)
            d = math.hypot(hu / (ru * stiffness["K"]), hv / (rv * stiffness["K"]))
            if d > deflection:
                worst, deflection, shear = name, d, math.hypot(hu, hv)
        checks.append(
            _check(
                "Pile head deflection",
                deflection,
                limit,
                "mm",
                worst,
                f"H = {shear / 1e3:.1f} kN per pile over the group ratio × K "
                f"({ru:.2f} along u, {rv:.2f} along v); {stiffness['basis']}; allowed {source}",
            )
        )
        if stiffness.get("betaL", 99) < 3:
            notes.append(
                f"βL = {stiffness['betaL']:.2f} < 3: not a long pile, its head stiffness is "
                "approximate"
            )
    if tested and tested.get("safe") is not None:
        worst = max(service_shears, key=lambda n: float(np.hypot(*service_shears[n])))
        h = float(np.hypot(*service_shears[worst])) / max(count, 1)
        group = min(ru, rv)
        checks.append(
            _check(
                "Pile lateral load (load test)",
                h / 1e3,
                group * tested["safe"],
                "kN",
                worst,
                f"test {tested['id']}: safe lateral load {tested['safe']:.0f} kN "
                f"({tested['basis']}) × group ratio {group:.2f}",
            )
        )
    notes.append(
        "lateral soil failure of the piles (Broms) is a planned feature: not checked; the head "
        "deflection, the pile section and any lateral load test are"
    )
    return checks, notes

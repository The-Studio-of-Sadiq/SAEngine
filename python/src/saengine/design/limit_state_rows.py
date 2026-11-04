"""Check rows of the partial-factor concrete methods a pack picks (alpha 9 C5b): the glue
between the generic method modules (:mod:`saengine.design.design_strength`,
:mod:`~saengine.design.strut_shear`, :mod:`~saengine.design.perimeter_punching`,
:mod:`~saengine.design.crack_control`, :mod:`~saengine.design.bar_rules`) and the design of
slabs, stairs, beams and columns. Each function runs only where
:mod:`saengine.design.method_selection` names the method; the default pack never comes here.

Units: mm, MPa, N, N·mm.

- Strips of slabs and stairs (:func:`layer_capacity`, :func:`one_way_shear`,
  :func:`required_area`): the rectangular block η fcd over λ x per metre, MRd = As fyd
  (d - λx/2), φ = 1; the ductility limit xu/d <= (1 - k1)/k2 (no redistribution, the pack's
  ``ultimate.neutralAxisLimit``); VRd,c of members without shear reinforcement; the least
  steel of 9.3.1.1 as beams' (:func:`slab_steel_rows`) and the largest spacing of principal
  and secondary bars.
- Punching of flat slabs (:func:`slab_punching_rows`) on the basic control perimeter u1 at 2d
  with β by the column's position.
- Column slenderness (:func:`nominal_curvature`): λ = l0 / i with l0 = k lu (k of SAEngine's
  frame: the alignment chart; SAEngine practice), λlim = 20 A B C / √n, the nominal curvature
  method beyond it: e2 = (1/r) l0² / c, 1/r = Kr Kφ εyd / (0.45 d), MEd = max(M0e + M2, M02,
  M01 + 0.5 M2) braced, M02 + M2 unbraced.
- Beam torsion (:func:`beam_torsion`): the thin-walled section, TEd / TRd,max + VEd / VRd,max
  <= 1, no torsion reinforcement where TEd / TRd,c + VEd / VRd,c <= 1, links Asw / s and the
  longitudinal steel ΣAsl, link spacing u / 8; compatibility torsion reported only (6.3.1(2)).
- Beam deflection (:func:`span_depth_row`) by the limiting span/depth ratio with As,req taken
  as As,prov (on the safe side).
- Crack widths and stresses of beams (:func:`beam_service_rows`): wk under the quasi-permanent
  combination against wmax of the exposure class, σc <= k2 fck (quasi-permanent), σs <= k3 fyk
  (characteristic), on the cracked section with αe = Es / Ecm.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context
from saengine.design import design_strength, method_selection


def _table() -> Any:
    return code_context.table("concreteMethods")


def _cite(key: str) -> str:
    return code_context.cite("concreteMethods", key)


def _row(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    combination: str | None,
    note: str,
    key: str | None = None,
    flag: bool = False,
    utilisation: float | None = None,
) -> dict[str, Any]:
    from saengine.design.check import _check

    clause = _cite(key) if key else ""
    return _check(
        name,
        demand,
        capacity,
        unit,
        combination,
        note + (f" ({clause})" if clause else ""),
        flag=flag,
        utilisation=utilisation,
    )


def partial_factors() -> bool:
    """True when the pack in force designs concrete with partial factors on the materials."""
    return method_selection.concrete("ultimate") == "partialFactors"


# ─────────────────────────────── slab and stair strips ───────────────────────────────


def neutral_axis_limit(fy: float) -> float:
    """xu/d at most: (1 - k1)/k2 of the pack, else the depth at which the bars just yield."""
    r = design_strength.rules()
    if r.neutralAxisLimit is not None:
        k1, k2 = r.neutralAxisLimit
        return (1 - k1) / k2
    eps_yd = design_strength.fyd(fy, r) / r.steelE
    eps_cu = design_strength.ultimate_strain(30.0)
    return eps_cu / (eps_cu + eps_yd)


def layer_capacity(
    area: float, d: float, fc: float, fy: float, es: float | None = None, width: float = 1000.0
) -> Any:
    """MRd of a strip ``width`` wide (:class:`saengine.design.slab.LayerCapacity`, φ = 1:
    ``phi_mn`` = ``mn`` = MRd; ``c`` the neutral axis depth x, ``a`` = λ x)."""
    from saengine.design.slab import LayerCapacity

    if d <= 0:
        raise ValueError("the cover leaves no room for the bars")
    r = design_strength.rules()
    p = design_strength.properties(fc, r)
    f_cd, f_yd = design_strength.fcd(fc, r), design_strength.fyd(fy, r)
    x = area * f_yd / (p.eta * f_cd * p.lam * width)
    a = p.lam * x
    mrd = area * f_yd * (d - a / 2)
    eps = p.eps_cu3 * (d - x) / x if x > 0 else math.inf
    return LayerCapacity(area, d, a, x, eps, 1.0, mrd, mrd, neutral_axis_limit(fy))


def one_way_shear(rho: float, d: float, fc: float) -> tuple[float, float]:
    """VRd,c per metre [N/m] of a strip without shear reinforcement and its size factor k."""
    from saengine.design import strut_shear

    r = strut_shear.rules()
    return strut_shear.concrete_resistance(1000.0, d, max(rho, 0.0), fc, 0.0, r), (
        strut_shear.size_factor(d, r)
    )


def required_area(moment: float, d: float, fc: float, fy: float, width: float = 1000.0) -> float:
    """As [mm²] of a strip for MEd [N·mm] by the rectangular block (at the section's limit
    when MEd is beyond it)."""
    if moment <= 0 or d <= 0:
        return 0.0
    r = design_strength.rules()
    p = design_strength.properties(fc, r)
    k = p.eta * design_strength.fcd(fc, r)
    share = moment / (width * d * d * k)
    a = d * (1 - math.sqrt(max(0.0, 1 - 2 * share)))
    return k * width * a / design_strength.fyd(fy, r)


def ductility_name() -> str:
    clause = _cite("redistribution")
    return "Neutral axis depth x/d" + (f" ({clause})" if clause else "")


def one_way_shear_note() -> str:
    return "VRd,c = max(CRd,c k (100 ρl fck)^(1/3), vmin) b d" + (
        f" ({_cite('shearNoLinks')})" if _cite("shearNoLinks") else ""
    )


def slab_steel_rows(
    system: str,
    h: float,
    fc: float,
    fy: float,
    capacities: dict[str, Any],
    envelope: dict[str, tuple[float, Any, str]],
    layers: dict[str, Any],
    span: str | None,
    no_demand: float,
) -> list[dict[str, Any]]:
    """The least steel and the largest spacing of a slab by the pack's ``memberSteel``: every
    layer the envelope puts in tension, and the bottom bars in the span direction(s), at least
    As,min of beams (9.3.1.1(1)); one-way slabs' bars across the span at least the secondary
    share of the main ones; spacing at most min(n h, mm) of principal bars, the secondary
    limit across the span of one-way slabs."""
    from saengine.design import bar_rules

    m = _table().memberSteel
    spans = ("X", "Y") if span is None else (span,)
    found: list[tuple[float, float, float, str]] = []
    for name, capacity in capacities.items():
        direction = name[-1]
        tension = envelope.get(name, (0.0,))[0] > no_demand
        if capacity is None:
            if name.startswith("bottom") and direction in spans:
                found.append((math.inf, 0.0, 0.0, f"no {name} bars in a span direction"))
            continue
        if direction not in spans or not (tension or name.startswith("bottom")):
            continue
        need = bar_rules.beam_min_steel(1000.0, capacity.d, fc, fy)
        found.append((need / capacity.area, need, capacity.area, name))
    if span is not None:
        across = "Y" if span == "X" else "X"
        main = max((c.area for n, c in capacities.items() if c and n[-1] == span), default=0.0)
        for name in (f"bottom{across}", f"top{across}"):
            capacity = capacities.get(name)
            if capacity is not None and name.startswith("bottom"):
                need = m.slabSecondaryShare * main
                found.append((need / capacity.area, need, capacity.area, f"{name} (secondary)"))
    rows = []
    if found:
        utilisation, need, provided, what = max(found, key=lambda f: f[0])
        rows.append(
            _row(
                "Min. reinforcement" + (f" ({_cite('slabSteel')})" if _cite("slabSteel") else ""),
                need,
                provided,
                "mm²/m",
                None,
                f"As,min = max({m.beamMinCoefficient:g} fctm/fyk, {m.beamMinRatio:g}) b d; "
                f"secondary at least {m.slabSecondaryShare:g} of the main; governing: {what}",
                utilisation=utilisation,
            )
        )
    worst: tuple[float, Any, float, str] | None = None
    n1, mm1 = m.slabMaxSpacing
    n2, mm2 = m.slabSecondarySpacing
    for layer in layers.values():
        if layer is None:
            continue
        secondary = system == "oneWay" and span is not None and layer.name[-1] != span
        limit = min(n2 * h, mm2) if secondary else min(n1 * h, mm1)
        what = f"min({n2:g} h, {mm2:g}), secondary" if secondary else f"min({n1:g} h, {mm1:g})"
        ratio = layer.spacing / limit
        if worst is None or ratio > worst[0]:
            worst = (ratio, layer, limit, what)
    if worst is not None:
        _, layer, limit, what = worst
        rows.append(
            _row(
                "Max. spacing",
                layer.spacing,
                limit,
                "mm",
                None,
                f"{layer.name} at {layer.spacing:.0f} mm; {what}",
                "slabSteel",
            )
        )
    return rows


def slab_punching_rows(
    layers: dict[str, Any],
    fc: float,
    combinations: list[str],
    context: Any,
    support_size: Any,
    critical_section: Any,
) -> list[dict[str, Any]]:
    """Punching at each column of a flat slab by the control perimeter method: VEd the largest
    column reaction of the combinations, β of the column's position (interior, edge, corner:
    the critical section's location), ρl = √(ρx ρy) of the top bars, d their mean. A drop
    panel: also the perimeter outside it with the slab's own d. The slab type's punching
    reinforcement is not counted (vRd,cs is not wired: the row then says so)."""
    from saengine.design import perimeter_punching

    top = [layers.get("topX"), layers.get("topY")]
    top = [layer for layer in top if layer is not None]
    if not top:
        return []
    d = sum(layer.d for layer in top) / len(top)
    ratios = [layer.area / (1000.0 * layer.d) for layer in top]
    rho = math.sqrt(ratios[0] * ratios[1]) if len(ratios) == 2 else ratios[0]
    drop = context.drop
    head = float(drop.depth) if drop is not None else 0.0
    rows: list[dict[str, Any]] = []
    for column in context.columns:
        c1, c2 = support_size(column.c1, column.c2, context.capital)
        faces = [(c1, c2, d + head, "")]
        if drop is not None:
            faces.append((float(drop.length), float(drop.width), d, "outside the drop panel"))
        best = None
        for c, force in enumerate(column.forces):
            ved = max(-float(force[2]), 0.0)
            if best is None or ved > best[0]:
                best = (ved, combinations[c])
        if best is None:
            continue
        ved, combination = best
        for s1, s2, depth, what in faces:
            section = critical_section(column.centre, s1, s2, column.angle, depth, context.boundary)
            if not section.sides:
                continue
            position = section.location if section.location in ("edge", "corner") else "interior"
            p = perimeter_punching.punching(ved, depth, s1, s2, fc, rho, position)
            note = (
                f"{position} column, β = {p.beta:.2f}, u1 = {p.u1:.0f} mm at "
                f"{_table().punching.perimeterDistance:g} d, d = {depth:.0f} mm, ρl = {rho:.4f}, "
                f"VEd = {ved / 1e3:.1f} kN, vEd = {p.v_ed:.3f} MPa, vRd,c = {p.v_rdc:.3f} MPa, "
                f"vEd,0 = {p.v_ed0:.3f} against vRd,max = {p.v_rdmax:.3f} MPa at u0; shown as v u1 d"
            )
            if context.punching is not None:
                note += "; the slab type's punching reinforcement is not counted here (vRd,cs)"
            rows.append(
                _row(
                    f"Punching at {column.id}" + (f" ({what})" if what else ""),
                    p.v_ed * p.u1 * depth / 1e3,
                    p.v_rdc * p.u1 * depth / 1e3,
                    "kN",
                    combination,
                    note,
                    "punching",
                    utilisation=p.utilisation,
                )
            )
    return rows


# ─────────────────────────────── column slenderness ───────────────────────────────


def nominal_curvature(
    pu: float,
    m01: float,
    m02: float,
    sway: bool,
    transverse: bool,
    l0: float,
    i: float,
    d: float,
    fck: float,
    fyk: float,
    es: float,
    ac: float,
    steel: float,
    sustained_share: float | None = None,
) -> dict[str, float | bool]:
    """The slenderness and the design moment MEd [N·mm] of one axis of a column (see the module
    notes); ``m01`` signed (positive: both ends' moments give tension on the same side),
    ``m02`` >= |m01|."""
    r = design_strength.rules()
    s = _table().slenderness
    f_cd, f_yd = design_strength.fcd(fck, r), design_strength.fyd(fyk, r)
    share = s.sustainedShare if not sustained_share else min(max(sustained_share, 0.0), 1.0)
    phi_ef = s.creepCoefficient * share
    omega = steel * f_yd / (ac * f_cd)
    n = max(pu, 0.0) / (ac * f_cd)
    a = 1 / (1 + s.creepShare * phi_ef)
    b = math.sqrt(1 + s.mechanicalShare * omega)
    rm = s.unbracedRatio if (sway or transverse) else (m01 / m02 if m02 > 0 else 1.0)
    c = s.momentRatioBase - rm
    lam = l0 / i
    lam_lim = s.limitCoefficient * a * b * c / math.sqrt(n) if n > 0 else math.inf
    out: dict[str, float | bool] = {
        "lambda": lam, "lambdaLim": lam_lim, "n": n, "omega": omega, "A": a, "B": b, "C": c,
        "phiEf": phi_ef, "slender": lam > lam_lim, "med": m02, "m2": 0.0, "e2": 0.0,
        "kr": 1.0, "kphi": 1.0,
    }  # fmt: skip
    if lam <= lam_lim or pu <= 0:
        return out
    nu = 1 + omega
    kr = min(1.0, (nu - n) / (nu - s.balancedAxial)) if nu > s.balancedAxial else 1.0
    kr = max(kr, 0.0)
    beta = s.betaBase + fck / s.betaFckDivisor - lam / s.betaLambdaDivisor
    kphi = max(1.0, 1 + beta * phi_ef)
    curvature = kr * kphi * (f_yd / es) / (s.curvatureDepthShare * d)
    e2 = curvature * l0**2 / s.curvatureDistribution
    m2 = pu * e2
    if sway:
        med = m02 + m2
    else:
        ea, eb, ec = s.equivalentMoment
        m0e = max(ea * m02 + eb * m01, ec * m02)
        med = max(m0e + m2, m02, abs(m01) + s.curvatureShareEnd * m2)
    out.update(med=med, m2=m2, e2=e2, kr=kr, kphi=kphi)
    return out


def slenderness_note(found: dict[str, Any], lu: float, k: float, i: float, sway: bool) -> str:
    text = (
        f"λ = k lu / i = {k:.2f} × {lu:.0f} / {i:.0f} = {found['lambda']:.1f}, λlim = 20 A B C / √n = "
        f"{found['lambdaLim']:.1f} (A = {found['A']:.2f} with φef = {found['phiEf']:.2f}, B = "
        f"{found['B']:.2f}, C = {found['C']:.2f}, n = {found['n']:.3f}); "
        + ("unbraced" if sway else "braced")
    )
    if found["slender"]:
        text += (
            f"; nominal curvature: Kr = {found['kr']:.2f}, Kφ = {found['kphi']:.2f}, e2 = "
            f"{found['e2']:.1f} mm, M2 = {found['m2'] / 1e6:.1f} kN·m, MEd = "
            f"{found['med'] / 1e6:.1f} kN·m"
        )
    else:
        text += "; second-order effects may be ignored"
    clause = _cite("slenderness")
    return text + (f" ({clause})" if clause else "")


# ─────────────────────────────── beam torsion ───────────────────────────────


@dataclass(frozen=True)
class TorsionNeed:
    """What a beam's torsion asks of its links and bars, for Design Reinforcement (the
    attributes :mod:`saengine.design.proposal` reads of a torsion design)."""

    at_s: float  # mm²/mm of one link leg for TEd
    av_s: float  # mm²/mm of all legs for VEd (0 where VRd,c carries it)
    al: float  # mm², ΣAsl for TEd
    s_max: float  # mm
    tu: float = 0.0  # N·mm, TEd
    section_ok: bool = True  # TEd/TRd,max + VEd/VRd,max <= 1
    required: bool = True
    kind: str = "equilibrium"
    at_s_min: float = 0.0
    al_min: float = 0.0
    long_dia_min: float = 0.0

    @property
    def tu_design(self) -> float:
        return self.tu


def beam_torsion(
    section: Any,
    transverse: Any | None,
    points: list[tuple[float, float, float, str, str]],
    compatibility: bool,
    why: str,
) -> tuple[list[dict[str, Any]], TorsionNeed | None]:
    """The torsion rows of a rectangular beam over its stations ``points`` (TEd, VEd, MEd,
    combination, where), and what it needs (None where no torsion reinforcement is needed or
    the torsion is compatibility torsion)."""
    from saengine.design import strut_shear
    from saengine.design.rc import DesignError, bar_area

    if not points:
        return [], None
    s = strut_shear.rules()
    t = _table().torsion
    u = design_strength.rules()
    b, h, fck, fyk = section.width, section.depth, section.fc, section.fy
    dia = getattr(transverse, "dia", None) or 0.0
    legs = getattr(transverse, "legs", 0) or 0
    spacing = getattr(transverse, "spacing", None)
    cover = getattr(transverse, "cover", None) or 0.0
    bars = list(section.bars)
    db = max((x.dia for x in bars), default=0.0) if bars else 0.0
    try:
        d = section.effective_depth(top=False)
    except DesignError:
        d = 0.9 * h
    edge = min((min(b / 2 - abs(x.x), h / 2 - abs(x.y)) for x in bars), default=cover + db / 2)
    links = None
    if dia and spacing and legs:
        links = strut_shear.link_resistance(b, d, legs * bar_area(dia), spacing, fck, fyk, s)
    cot = links.cot_theta if links else s.cotTheta[0]
    z = s.leverArmShare * d
    v1 = strut_shear.nu1(fck, s)
    f_cd, f_yd = design_strength.fcd(fck, u), design_strength.fyd(fyk, u)
    vrd_max = s.alphaCw * b * z * v1 * f_cd / (cot + 1 / cot)
    rho_l = min(s.rhoLMax, max(sum(x.area for x in bars if x.y < 0), 1e-9) / (b * d))
    vrd_c = strut_shear.concrete_resistance(b, d, rho_l, fck, 0.0, s)
    worst = None
    for ted, ved, med, combination, where in points:
        tr = strut_shear.torsion(b, h, edge, fck, fyk, ted, cot)
        trd_c = 2 * tr.ak * tr.tef * design_strength.fctd(fck, u)
        cracking = ted / trd_c + ved / vrd_c if trd_c > 0 and vrd_c > 0 else 0.0
        interaction = strut_shear.torsion_interaction(ted, tr.trd_max, ved, vrd_max)
        shear_leg = ved / (z * f_yd * cot) / legs if legs and ved > vrd_c else 0.0
        a_s = abs(med) / (z * f_yd)
        key = max(interaction, cracking)
        if worst is None or key > worst[0]:
            worst = (key, ted, ved, med, combination, where, tr, trd_c, cracking, interaction,
                     shear_leg, a_s)  # fmt: skip
    (_, ted, ved, _med, combination, where, tr, trd_c, cracking, interaction, shear_leg,
     a_s) = worst  # fmt: skip
    needed = cracking > 1.0 and not compatibility
    s_max = min(tr.uk / t.spacingDivisor, min(b, h), t.spacingMax)
    note = f"{why}; tef = {tr.tef:.0f} mm, Ak = {tr.ak / 1e3:.1f} × 10³ mm², cot θ = {cot:.2f}; {where}"
    rows = [
        _row(
            "Torsion: TEd/TRd,max + VEd/VRd,max",
            interaction,
            1.0,
            "",
            combination,
            f"TEd = {ted / 1e6:.1f} kN·m, TRd,max = {tr.trd_max / 1e6:.1f} kN·m, VEd = "
            f"{ved / 1e3:.1f} kN, VRd,max = {vrd_max / 1e3:.1f} kN; " + note,
            "torsion",
            flag=compatibility,
        ),
        _row(
            "Torsion: TEd/TRd,c + VEd/VRd,c",
            cracking,
            1.0,
            "",
            combination,
            f"TRd,c = 2 Ak tef fctd = {trd_c / 1e6:.1f} kN·m: above 1 the torsion links and bars "
            "are needed"
            + ("; compatibility torsion: designed for at the ultimate limit state only by the "
               "least links and bars (6.3.1(2))" if compatibility else ""),
            "torsion",
            flag=True,
        ),
    ]  # fmt: skip
    if needed:
        leg = bar_area(dia) if dia else 0.0
        need_leg = tr.links_per_spacing + shear_leg
        rows.append(
            _row(
                "Torsion links (per leg)",
                need_leg * 1000,
                (leg / spacing * 1000) if spacing else 0.0,
                "mm²/m",
                combination,
                f"Asw/s = TEd/(2 Ak fyd cot θ) = {1000 * tr.links_per_spacing:.0f} mm²/m + the "
                f"shear's {1000 * shear_leg:.0f} mm²/m per leg",
                "torsion",
            )
        )
        rows.append(
            _row(
                "Torsion longitudinal steel",
                tr.longitudinal + a_s,
                section.steel_area,
                "mm²",
                combination,
                f"ΣAsl = TEd uk cot θ/(2 Ak fyd) = {tr.longitudinal:.0f} mm² + the flexural "
                f"MEd/(z fyd) = {a_s:.0f} mm² (on the safe side: no relief in the compression "
                "chord)",
                "torsion",
            )
        )
        if spacing:
            rows.append(
                _row(
                    "Torsion link spacing",
                    spacing,
                    s_max,
                    "mm",
                    None,
                    f"min(u/{t.spacingDivisor:g}, the least dimension, {t.spacingMax:g} mm)",
                    "torsion",
                )
            )
    need = (
        TorsionNeed(
            tr.links_per_spacing,
            shear_leg * legs,
            tr.longitudinal,
            s_max,
            tu=ted,
            section_ok=interaction <= 1.0,
        )
        if needed
        else None
    )
    return rows, need


# ─────────────────────────────── serviceability ───────────────────────────────


def span_depth_row(
    section: Any, span: float, ends: int, cantilever: bool, flange_ratio: float, where: str
) -> dict[str, Any]:
    """The span/depth row of a beam span: K by its ends (0 simply supported, 1 end span, 2
    interior span; cantilever), ρ of the tension bars at midspan (the top bars of a cantilever),
    As,req = As,prov (on the safe side)."""
    from saengine.design import crack_control

    top = cantilever
    b = section.width
    tension = [x for x in section.bars if (x.y > 0 if top else x.y < 0)]
    compression = [x for x in section.bars if (x.y < 0 if top else x.y > 0)]
    d = section.effective_depth(top=top)
    rho = max(sum(x.area for x in tension), 1e-9) / (b * d)
    rho_c = sum(x.area for x in compression) / (b * d)
    system = (
        "cantilever"
        if cantilever
        else ("simplySupported", "endSpan", "interiorSpan")[min(max(ends, 0), 2)]
    )
    limit = crack_control.span_depth_limit(
        system, rho, rho_c, section.fc, section.fy, 1.0, 1.0, span, flange_ratio
    )
    return _row(
        "Deflection: span/depth",
        span / d,
        limit,
        "",
        "service",
        f"l/d = {span:.0f}/{d:.0f}; {system}, ρ = {rho:.4f}, ρ' = {rho_c:.4f}, beff/bw = "
        f"{flange_ratio:.1f}, As,req = As,prov (on the safe side); {where}",
        "deflection",
    )


def service_factors(kind: str) -> dict[str, float] | None:
    """The load-case factors of the pack's service combination ``kind`` ("quasiPermanent",
    "characteristic") named by ``concreteMethods.serviceStress``; SD takes D's factor."""
    stress = _table().serviceStress
    wanted = getattr(stress, kind, None) if stress is not None else None
    if not wanted:
        return None
    for combination in code_context.table("combinations").service:
        if getattr(combination, "id", None) == wanted:
            factors = dict(combination.factors)
            factors.setdefault("SD", factors.get("D", 0.0))
            return factors
    return None


def beam_service_rows(
    section: Any,
    moments: dict[str, dict[bool, tuple[float, str]]],
    cover: float,
    exposure: str | None = None,
) -> list[dict[str, Any]]:
    """Crack width and stress rows of a rectangular beam; ``moments``: per combination kind
    ("quasiPermanent", "characteristic") and face in tension (True top), (M [N·mm] >= 0,
    where)."""
    from saengine.design import crack_control

    t = _table()
    exposure = exposure or t.defaultExposure or ""
    fck, fyk, es = section.fc, section.fy, section.es
    b, h = section.width, section.depth
    p = design_strength.properties(fck)
    alpha_e = es / p.ecm
    rows: list[dict[str, Any]] = []
    for top in (False, True):
        face = "top" if top else "bottom"
        bars = [x for x in section.bars if (x.y > 0 if top else x.y < 0)]
        if not bars:
            continue
        d = section.effective_depth(top=top)
        area = sum(x.area for x in bars)
        dia = max(x.dia for x in bars)
        xs = sorted(x.x for x in bars)
        spacing = max((x2 - x1 for x1, x2 in itertools.pairwise(xs)), default=None)
        clear = max(h - d - dia / 2, cover)
        qp = moments.get("quasiPermanent", {}).get(top)
        if qp and qp[0] > 0 and t.cracking is not None:
            w = crack_control.crack_width(b, h, d, area, dia, clear, qp[0], fck, es, spacing)
            limit = crack_control.wmax(exposure) if exposure else None
            if limit:
                rows.append(
                    _row(
                        f"Crack width, {face}",
                        w.wk,
                        limit,
                        "mm",
                        "quasi-permanent",
                        f"wk = sr,max (εsm - εcm) = {w.sr_max:.0f} × {w.strain:.5f}, σs = "
                        f"{w.sigma_s:.0f} MPa, ρp,eff = {w.rho_eff:.4f}; wmax of {exposure}; "
                        f"{qp[1]}",
                        "cracking",
                    )
                )
            if t.serviceStress is not None:
                cracked = crack_control.cracked_section(b, d, area, qp[0], alpha_e)
                limit_c = crack_control.stress_limits(fck, fyk, exposure)
                rows.append(
                    _row(
                        f"Concrete stress, quasi-permanent ({face} in tension)",
                        cracked.sigma_c,
                        limit_c["concreteQuasiPermanent"],
                        "MPa",
                        "quasi-permanent",
                        f"σc at most k2 fck (linear creep), αe = Es/Ecm = {alpha_e:.1f}; {qp[1]}",
                        "serviceStress",
                    )
                )
        ch = moments.get("characteristic", {}).get(top)
        if ch and ch[0] > 0 and t.serviceStress is not None:
            cracked = crack_control.cracked_section(b, d, area, ch[0], alpha_e)
            limits = crack_control.stress_limits(fck, fyk, exposure)
            rows.append(
                _row(
                    f"Steel stress, characteristic, {face}",
                    cracked.sigma_s,
                    limits["steel"],
                    "MPa",
                    "characteristic",
                    f"σs at most k3 fyk; {ch[1]}",
                    "serviceStress",
                )
            )
            if "concreteCharacteristic" in limits:
                rows.append(
                    _row(
                        f"Concrete stress, characteristic ({face} in tension)",
                        cracked.sigma_c,
                        limits["concreteCharacteristic"],
                        "MPa",
                        "characteristic",
                        f"σc at most k1 fck in {exposure}; {ch[1]}",
                        "serviceStress",
                    )
                )
    return rows


# ─────────────────────────────── walls ───────────────────────────────

#: The parent pack's wall rows the pack's wall rows take the place of (by name).
_PARENT_WALL_ROWS = (
    "Vertical web ratio",
    "Horizontal web ratio",
    "Vertical bar spacing",
    "Horizontal bar spacing",
    "In-plane shear",
)


def wall_rows(
    checks: list[dict[str, Any]],
    geometry: Any,
    bars: Any,
    forces: list[Any],
    fc: float,
    fy: float,
    ductility: str | None = None,
) -> list[dict[str, Any]]:
    """A wall pier's rows with the pack's: the least and largest vertical and horizontal steel
    and the spacings (``memberSteel``), the in-plane shear by the pack's shear method (bw = t,
    d = 0.8 lw, the horizontal bars as links, σcp of the axial force; VEd × ε of the ductility
    class for a ductile wall) and, for a ductile wall, its thickness, boundary and critical
    height rows (:func:`saengine.design.curvature_ductility.wall_rows`). The parent pack's web
    ratio, spacing and in-plane shear rows are dropped (one set of rules)."""
    from saengine.design import bar_rules, curvature_ductility, strut_shear
    from saengine.design.rc import bar_area

    t, lw = geometry.thickness, geometry.length
    kept = [r for r in checks if not r["name"].startswith(_PARENT_WALL_ROWS)]
    rho_l, rho_t = bars.rho_l(t), bars.rho_t(t)
    area = t * lw
    kept += bar_rules.wall_rows(
        t, lw, rho_l * area, rho_t * area, bars.vertical_spacing, bars.horizontal_spacing
    )
    s = strut_shear.rules()
    if s is not None and forces:
        d = 0.8 * lw
        asw = bars.layers * bar_area(bars.horizontal_dia)
        links = strut_shear.link_resistance(t, d, asw, bars.horizontal_spacing, fc, fy, s)
        factor = curvature_ductility.wall_design_shear(1.0, ductility) if ductility else 1.0
        best = None
        for f in forces:
            ved = abs(f.V2) * factor
            vrd_c = strut_shear.concrete_resistance(
                t, d, min(rho_l / 2, s.rhoLMax), fc, f.P / area, s
            )
            vrd = max(vrd_c, min(links.vrd_s, links.vrd_max))
            ratio = ved / vrd if vrd > 0 else math.inf
            if best is None or ratio > best[0]:
                best = (ratio, ved, vrd, vrd_c, f)
        if best is not None:
            ratio, ved, vrd, vrd_c, f = best
            note = (
                f"bw = t, d = 0.8 lw = {d:.0f} mm; VRd,c = {vrd_c / 1e3:.1f} kN, VRd,s = "
                f"{links.vrd_s / 1e3:.1f} kN, VRd,max = {links.vrd_max / 1e3:.1f} kN at cot θ = "
                f"{links.cot_theta:.2f}"
            )
            if ductility:
                note += f"; VEd × ε = {factor:g} ({ductility} ductile wall)"
            kept.append(
                _row(
                    "In-plane shear",
                    ved / 1e3,
                    vrd / 1e3,
                    "kN",
                    f.combination,
                    note + (f"; {f.where}" if getattr(f, "where", "") else ""),
                    "wallShear" if ductility else "shear",
                    utilisation=ratio,
                )
            )
    if ductility:
        kept += curvature_ductility.wall_rows(lw, t, geometry.clear_height, None, None, ductility)
        hcr = curvature_ductility.wall_critical_height(lw, geometry.height, ductility)
        kept.append(
            _row(
                f"Critical region height hcr ({ductility})",
                hcr,
                geometry.height,
                "mm",
                None,
                "hcr = max(lw, hw/6): the boundary elements and ωwd over it (reported; the "
                "boundary element rows are those of the wall type's boundary bars)",
                "seismicWalls",
                flag=True,
            )
        )
    return kept


# ─────────────────────── Design Reinforcement (bars.py's sizing) ───────────────────────


def _block(fc: float) -> tuple[float, float, float, float]:
    """(η fcd, λ, εcu3, the design-strength rules' γ-free Es) of concrete fc."""
    r = design_strength.rules()
    p = design_strength.properties(fc, r)
    return p.eta * design_strength.fcd(fc, r), p.lam, p.eps_cu3, r.steelE


def singly_area(mu: float, b: float, d: float, fc: float, fy: float) -> float | None:
    """As [mm²] of a singly reinforced section for MEd [N·mm] by the rectangular block on the
    design strengths, or None when the concrete cannot carry it."""
    if mu <= 0:
        return 0.0
    k, _lam, _eps, _es = _block(fc)
    root = 1 - 2 * mu / (k * b * d * d)
    if root < 0:
        return None
    return k * b * d * (1 - math.sqrt(root)) / design_strength.fyd(fy)


def beam_flexure_need(
    mu: float,
    b: float,
    d: float,
    d_comp: float,
    fc: float,
    fy: float,
    es: float | None,
    ratio_max: float,
    h: float | None,
) -> Any:
    """The tension and compression bars of a rectangular beam for MEd (bars.FlexureNeed): the
    tension bars alone up to the neutral axis limit xu/d (:func:`neutral_axis_limit`), compression
    bars beyond it, the bars at fyd (compression bars at Es εcu3 (x - d2)/x at most fyd)."""
    from saengine.design.bars import FlexureNeed

    if mu <= 0:
        return FlexureNeed(0.0, 0.0)
    k, lam, eps_cu, es_ = _block(fc)
    es = es or es_
    f_yd = design_strength.fyd(fy)
    x_lim = neutral_axis_limit(fy) * d
    a_lim = lam * x_lim
    as_lim = k * b * a_lim / f_yd
    m_lim = as_lim * f_yd * (d - a_lim / 2)
    limit = ratio_max * b * (h if h else d)
    if mu <= m_lim:
        area = singly_area(mu, b, d, fc, fy) or as_lim
        if area > limit:
            return FlexureNeed(mu, area, 0.0, True, "tension steel above the practical limit")
        return FlexureNeed(mu, area)
    fs = min(es * eps_cu * (x_lim - d_comp) / x_lim, f_yd)
    if fs <= k or d <= d_comp:
        return FlexureNeed(
            mu, as_lim, 0.0, True,
            "compression bars would not work (they lie near the neutral axis): section too small",
        )  # fmt: skip
    compression = (mu - m_lim) / ((fs - k) * (d - d_comp))
    area = as_lim + compression * (fs - k) / f_yd
    note = (
        f"compression bars: beyond xu/d = {neutral_axis_limit(fy):.3f}"
        + (f" ({_cite('redistribution')})" if _cite("redistribution") else "")
        + f", σs2 = {fs:.0f} MPa"
    )
    too_small = area > limit
    if too_small:
        note += f"; tension steel {area:.0f} mm² above {ratio_max:g} b h: section too small"
    return FlexureNeed(mu, area, compression, too_small, note)


def beam_min_area(b: float, d: float, fc: float, fy: float) -> float:
    from saengine.design import bar_rules

    return bar_rules.beam_min_steel(b, d, fc, fy)


def with_minimum(required: float, minimum: float) -> float:
    """The bars to provide: at least As,min wherever bars are required (no 4/3 relief)."""
    return 0.0 if required <= 0 else max(required, minimum)


def slab_max_area(d: float, fc: float, fy: float) -> float:
    """The most bars per metre [mm²/m] at ``d``: those that put the neutral axis at the limit."""
    k, lam, _eps, _es = _block(fc)
    return k * 1000.0 * lam * neutral_axis_limit(fy) * d / design_strength.fyd(fy)


def strain_limit(fy: float) -> float:
    """The least tensile strain of a beam the proposal keeps: εcu3 (1 - ξ)/ξ at the neutral
    axis limit ξ = xu/d."""
    _k, _lam, eps_cu, _es = _block(30.0)
    xi = neutral_axis_limit(fy)
    return eps_cu * (1 - xi) / xi


def beam_shear_need(vu: float, b: float, d: float, fc: float, fyt: float) -> Any:
    """Vertical links of a beam for VEd (bars.ShearNeed) by the variable strut method: none
    beyond ρw,min where VEd <= VRd,c (ρl taken as 0: vmin, on the safe side), else Asw/s =
    VEd/(z fywd cot θ) with the largest cot θ of the range whose VRd,max carries VEd."""
    from saengine.design import strut_shear
    from saengine.design.bars import ShearNeed

    s = strut_shear.rules()
    u = design_strength.rules()
    vc = strut_shear.concrete_resistance(b, d, 0.0, fc, 0.0, s)
    z = s.leverArmShare * d
    f_cd, f_ywd = design_strength.fcd(fc, u), design_strength.fyd(fyt, u)
    v1 = strut_shear.nu1(fc, s)
    lo, hi = s.cotTheta

    def vrd_max(cot: float) -> float:
        return s.alphaCw * b * z * v1 * f_cd / (cot + 1 / cot)

    av_s_min = strut_shear.min_link_ratio(fc, fyt, s) * b
    s_max = strut_shear.max_link_spacing(d, s)
    too_small = vu > vrd_max(1.0)
    cot = hi
    while cot > lo and vrd_max(cot) < vu:
        cot = max(lo, cot - 0.05)
    vs = vu if vu > vc else 0.0
    av_s = max(vs / (z * f_ywd * cot) if vs else 0.0, av_s_min)
    note = (
        f"VRd,c = {vc / 1e3:.1f} kN (vmin), cot θ = {cot:.2f}, VRd,max = {vrd_max(cot) / 1e3:.1f} "
        f"kN; s <= {s.spacingShare:g} d" + (f" ({_cite('shear')})" if _cite("shear") else "")
    )
    if too_small:
        note += f"; VEd above VRd,max at cot θ = 1 ({vrd_max(1.0) / 1e3:.1f} kN): section too small"
    return ShearNeed(vu, vc, vs, av_s, av_s_min, s_max, too_small, note)


def slab_shear_rho(q: float, d: float, fc: float) -> float | None:
    """The ρl a strip without shear reinforcement needs for VEd ``q`` [N/m]: 0 up to vmin, None
    beyond what ρl at its limit gives."""
    from saengine.design import strut_shear

    s = strut_shear.rules()
    u = design_strength.rules()
    k = strut_shear.size_factor(d, s)
    v = q / (1000.0 * d)
    vmin = s.vminCoefficient * k**1.5 * math.sqrt(fc)
    if v <= vmin:
        return 0.0
    crdc = s.crdcCoefficient / u.gammaC
    rho = (v / (crdc * k)) ** 3 / (100 * fc)
    return None if rho > s.rhoLMax else rho


def column_rho() -> tuple[float, float]:
    """(least, largest) column steel ratio of the pack's member steel (the NEd/fyd part of
    the least steel is the check rows')."""
    m = _table().memberSteel
    return float(m.columnMinRatio), float(m.columnMaxRatio)


def column_ties(
    layout: Any, least_dimension: float, b: float, h: float, cover: float, diameters: Any
) -> Any:
    """Links of a column by the pack's member steel: φ at least max(least, share × φmax), s at
    most min(n φmin, the least dimension, mm), every bar within the restrained distance of a
    held one (bars.Ties)."""
    from saengine.design.bars import Ties, round_down

    m = _table().memberSteel
    wanted = max(m.linkMinDia, m.linkDiaShare * layout.dia)
    usable = [d for d in diameters if d >= wanted - 1e-9]
    notes: list[str] = []
    if usable:
        dia = min(usable)
    else:
        dia = max(diameters)
        notes.append(f"links of at least Ø{wanted:g} are required; Ø{dia:g} is the largest given")
    n, mm = m.linkSpacing
    spacing = round_down(min(n * layout.dia, least_dimension, mm))
    if layout.circle:
        return Ties(dia, spacing, 2, tuple(notes))
    inset = cover + dia

    def held(bars_on_face: int, length: float) -> int:
        if bars_on_face <= 2:
            return 2
        clear = (length - 2 * inset - layout.dia) / (bars_on_face - 1)
        if clear > m.restrainedDistance:
            return bars_on_face
        return 2 + (bars_on_face - 2) // 2

    legs = max(held(layout.per_x + 2, b), held(layout.per_y + 2, h))
    return Ties(dia, spacing, legs, tuple(notes))


# ─────────────────────────────── report ───────────────────────────────


def method_lines() -> list[str]:
    """The design report's lines of the members the pack's methods design beyond beams' and
    columns' flexure, axial force and shear (those are :func:`saengine.design.design_strength.
    method_lines`')."""
    chosen = method_selection.summary()
    lines = []
    if chosen.get("torsion"):
        lines.append(
            "Beam torsion: the thin-walled closed section, TEd/TRd,max + VEd/VRd,max <= 1, "
            "torsion links Asw/s = TEd/(2 Ak fyd cot θ) with the shear's cot θ and ΣAsl = TEd uk "
            "cot θ/(2 Ak fyd) where TEd/TRd,c + VEd/VRd,c > 1; compatibility torsion reported "
            f"only ({_cite('torsion')})."
        )
    if chosen.get("deflection"):
        lines.append(
            "Beam deflection: the limiting span/effective depth ratio with K of the span's ends "
            "and As,req taken as As,prov; where it is exceeded, the calculated deflection of the "
            f"parent pack's method is reported with it ({_cite('deflection')})."
        )
    if chosen.get("cracking") or chosen.get("serviceStress"):
        lines.append(
            "Beam crack widths under the quasi-permanent combination against wmax of the "
            "exposure class, and the stress limits σc <= k2 fck (quasi-permanent), σs <= k3 fyk "
            f"(characteristic) on the cracked section ({_cite('cracking')}, "
            f"{_cite('serviceStress')}); they replace the parent pack's bar-spacing crack control."
        )
    if chosen.get("slenderness"):
        lines.append(
            "Column slenderness: λ = l0/i with l0 = k lu (k of the frame by the alignment chart, "
            "SAEngine practice) against λlim = 20 A B C/√n; slender columns by the nominal "
            f"curvature method ({_cite('slendernessLimit')}, {_cite('nominalCurvature')})."
        )
    if partial_factors():
        lines.append(
            "Slabs and stairs: strips by the rectangular block on the design strengths (MRd = As "
            "fyd (d - λx/2)) with xu/d at most (1 - k1)/k2, VRd,c without shear reinforcement, the "
            f"least steel and spacings of the pack ({_cite('slabSteel')}); the design moments "
            "(Wood-Armer, coefficients, direct design, equivalent frame) are SAEngine's analysis."
        )
    if chosen.get("punching"):
        lines.append(
            "Punching of flat slabs on the basic control perimeter u1 at 2d with β by the "
            f"column's position, vRd,c and vRd,max at the column face ({_cite('punching')})."
        )
    if chosen.get("memberSteel"):
        lines.append(
            "Walls: the least and largest vertical and horizontal steel and the bar spacings "
            f"({_cite('wallSteel')}); Design Reinforcement sizes beams, columns, slabs and walls "
            "with the pack's resistances, least and largest steel and spacings."
        )
    if chosen.get("seismic"):
        lines.append(
            "Earthquake resistance by ductility class (DCM, DCH): the curvature-ductility rows of "
            "beams and columns, capacity-design shear of beams VEd = γRd ΣMRb/lcl + the gravity "
            "shear and of columns γRd ΣMRc/lcl, ΣMRc >= 1.3 ΣMRb at the joints, joint shear "
            "(DCH), ductile walls; they take the place of the parent pack's special-frame "
            f"detailing ({_cite('capacityDesign')}, {_cite('seismicWalls')})."
        )
    if chosen.get("anchorage"):
        lines.append(
            "Anchorage and laps in the detailing and the bar schedule: lbd = α1 α2 lb,rqd from "
            f"fbd = 2.25 η1 η2 fctd, l0 = α1 α2 α6 lb,rqd ({_cite('anchorage')}, {_cite('laps')})."
        )
    return lines

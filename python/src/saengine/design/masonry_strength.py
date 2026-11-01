"""Strength design of reinforced masonry walls: the ``"strength"`` method of the code pack's
``masonry`` table (chosen by the pack's ``method``, or by a wall type among the pack's
``alternatives``).

The forces are the wall piers' under the design (factored) combinations. Every number is the
pack's ``masonry.strength`` (φ, εmu, the stress block, the axial and shear values, the modulus
of rupture, the slender wall and shear wall rules, the boundary members) and ``masonry.seismic``
(the least reinforcement the shear walls take in every seismic area).

Per pier, the governing combination of each check:

- slender wall, out of plane: the vertical load stress at mid-height Pu/Ag against the pack's
  share of f'm (above it the method does not apply), f'm and the thickness against the pack's
  limits, ρ against the pack's share of ρb; Mu = the analysis moment at mid-height + Pu Δu with
  Δu the mid-height deflection under Mu (cracked section above Mcr = S fr, iterated: P-delta)
  against φ Mn, Mn = Ase fy (d - a/2), Ase = (As fy + Pu)/fy, a = (As fy + Pu)/(0.85 f'm b);
  the service deflection Δs against the pack's share of h from the service forces when given;
- shear wall, in plane (reinforced hollow units): f'm within the pack's range; Pu ≤ φ 0.80 Po,
  Po = 0.85 f'm (Ae - As) + fy As; Mu ≤ φ Mn at Pu (strain compatibility, εmu, the rectangular
  block, bars in compression not counted; φ increased linearly towards the pack's maximum as Pu
  falls below the lesser of 0.10 f'm Ae and 0.25 Pb when fy is below the pack's limit);
  Vu ≤ φ Vn, Vn = Vm + Vs with Vm = 0.083 Cd Amv √f'm (Cd by M/Vd), Vs = Amv ρn fy, at most the
  pack's maximum by M/Vd; where Vn exceeds the shear at the flexural strength the wall fails in
  flexure: φ shear becomes the pack's higher value and Vn = Amv ρn fy (taken over the whole
  height, on the safe side), Mn ≥ 1.8 or 3.0 Mcr, horizontal spacing ≤ min(3t, 600) and
  boundary members where the extreme fibre stress exceeds 0.2 f'm; the least reinforcement and
  vertical ≥ 50 % of horizontal.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from saengine.design import masonry as M
from saengine.design import walls as W
from saengine.design.ductile_members import _row
from saengine.design.rc import DesignError, bar_area


def _pct(name: str, demand: float, capacity: float, unit: str = "", **kw: Any) -> dict[str, Any]:
    """A ratio row in per cent (the rows round to two decimals)."""
    return _row(name, 100.0 * demand, 100.0 * capacity, "%", **kw)


#: The combinations this method checks: the design (factored) combinations.
COMBINATIONS = "strength"


def _s() -> Any:
    return M.table().strength


def method_text() -> list[str]:
    s = _s()
    phi = s.phi
    return [
        (
            f"Masonry walls by strength design ({M.clause('strengthMethod')}): reinforced walls "
            "whose type chooses it, from the pier forces of the shell model under the design "
            f"combinations. Slender walls out of plane ({M.clause('slenderWall')}): Pu/Ag ≤ "
            f"{float(s.slenderWall['axialMax']):g} f'm, Mu with P-delta ({M.clause('slenderMoment')}"
            f") ≤ φ Mn, φ = {float(phi['slenderFlexure']):g}, εmu = {float(s.ultimateStrain):g}, "
            f"{float(s.stressBlock['stress']):g} f'm over a = {float(s.stressBlock['depth']):g} c; "
            f"service deflection ≤ {float(s.slenderWall['deflection']):g} h "
            f"({M.clause('slenderDeflection')}). Shear walls in plane: Pu ≤ φ "
            f"{float(s.axial['reduction']):g} Po ({M.clause('shearWallAxial')}), Mu ≤ φ Mn "
            f"(φ = {float(phi['axial']):g} to {float(phi['axialMax']):g}, "
            f"{M.clause('shearWallFlexure')}), Vu ≤ φ (Vm + Vs) (φ = {float(phi['shear']):g}, "
            f"{float(phi['shearFlexure']):g} in flexure mode, {M.clause('shearWallShear')}), the "
            f"reinforcement ({M.clause('shearWallReinforcement')}) and boundary members "
            f"({M.clause('boundary')})."
        )
    ]


# ─────────────────────────────────────── section values ───────────────────────────────────────


def modulus_of_rupture(m: M.Masonry) -> float:
    """fr [MPa] by the units and the grouting; raises :class:`DesignError` where the pack
    allows none (solid units partly grouted)."""
    row = _s().modulusOfRupture[m.units]["full" if m.grouting == "full" else "partial"]
    if row is None:
        raise DesignError(
            f"no modulus of rupture for {m.units} units {m.grouting or 'not'} grouted "
            f"({M.clause('slenderDeflection')}): strength design is not allowed"
        )
    return min(float(row.factor) * math.sqrt(m.fm), float(row.cap))


def balanced_ratio(fm: float, fy: float, es: float) -> float:
    """ρb of a singly reinforced section: 0.85 f'm · 0.85 · εmu/(εmu + fy/Es) / fy."""
    s = _s()
    emu = float(s.ultimateStrain)
    return (
        float(s.stressBlock["stress"])
        * fm
        * float(s.stressBlock["depth"])
        * emu
        / (emu + fy / es)
        / fy
    )


def slender_moment_strength(steel: float, pu: float, b: float, d: float, fm: float, fy: float):
    """(Mn [N·mm], a [mm], Ase [mm²]) of a slender wall strip (Eq 6.7.38)."""
    s = _s()
    total = steel * fy + max(pu, 0.0)
    ase = total / fy
    a = total / (float(s.stressBlock["stress"]) * fm * b)
    return ase * fy * (d - a / 2.0), a, ase


def cracked_inertia(ase: float, a: float, b: float, d: float, n: float) -> float:
    """Icr = n Ase (d - c)² + b c³/3 with c = a / the block depth factor."""
    c = a / float(_s().stressBlock["depth"])
    return n * ase * (d - c) ** 2 + b * c**3 / 3.0


def mid_deflection(moment: float, mcr: float, h: float, em: float, ig: float, icr: float) -> float:
    """Δ at mid-height (Eqs 6.7.40-6.7.41)."""
    if moment <= mcr:
        return 5.0 * moment * h * h / (48.0 * em * ig)
    return 5.0 * mcr * h * h / (48.0 * em * ig) + 5.0 * (moment - mcr) * h * h / (48.0 * em * icr)


def section_strength(
    p: float, depth: float, width: float, bars: list[tuple[float, float]], fm: float, fy: float
) -> tuple[float, float]:
    """(Mn [N·mm] about the centre, c [mm]) of a section ``depth`` × ``width`` with ``bars`` (x
    from the compression face, area) under the axial force ``p`` [N, compression positive]:
    strain compatibility, εmu at the face, the rectangular block, bars in compression not
    counted. (0, 0) when ``p`` exceeds the section's compression strength."""
    s = _s()
    emu, k1 = float(s.ultimateStrain), float(s.stressBlock["depth"])
    stress = float(s.stressBlock["stress"]) * fm
    es = float(M.table().elastic.es)

    def forces(c: float) -> tuple[float, float]:
        a = min(k1 * c, depth)
        comp = stress * a * width
        tension = 0.0
        moment = comp * (depth / 2.0 - a / 2.0)
        for x, area in bars:
            if x > c:
                f = area * min(es * emu * (x - c) / c, fy)
                tension += f
                moment += f * (x - depth / 2.0)
        return comp - tension, moment

    lo, hi = depth * 1e-4, depth / k1
    if forces(hi)[0] < p:
        return 0.0, 0.0
    if forces(lo)[0] > p:
        return forces(lo)[1], lo
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if forces(mid)[0] < p:
            lo = mid
        else:
            hi = mid
    c = 0.5 * (lo + hi)
    return forces(c)[1], c


def shear_coefficient(ratio: float) -> float:
    """Cd by M/Vd (Eqs 6.7.48a-b, linear between)."""
    sh = _s().shear
    lo, hi = float(sh["ratioLow"]), float(sh["ratioHigh"])
    c_lo, c_hi = float(sh["cdLow"]), float(sh["cdHigh"])
    if ratio <= lo:
        return c_lo
    if ratio >= hi:
        return c_hi
    return c_lo + (c_hi - c_lo) * (ratio - lo) / (hi - lo)


def shear_maximum(ratio: float) -> float:
    """Largest Vn / (Amv √f'm) by M/Vd (Table 6.7.14, linear between)."""
    sh = _s().shear
    lo, hi = float(sh["ratioLow"]), float(sh["ratioHigh"])
    m_lo, m_hi = float(sh["maxLow"]), float(sh["maxHigh"])
    if ratio <= lo:
        return m_lo
    if ratio >= hi:
        return m_hi
    return m_lo + (m_hi - m_lo) * (ratio - lo) / (hi - lo)


def axial_phi(pu: float, fm: float, ae: float, pb: float, fy: float) -> float:
    """φ of axial load with flexure: the pack's φ, increased linearly to its maximum as Pu falls
    from the lesser of 0.10 f'm Ae and 0.25 Pb to zero when fy is below the pack's limit."""
    phi = _s().phi
    base, top = float(phi["axial"]), float(phi["axialMax"])
    if fy >= float(phi["axialIncreaseFyMax"]):
        return base
    limit = min(float(phi["axialIncreaseArea"]) * fm * ae, float(phi["axialIncreaseBalanced"]) * pb)
    if limit <= 0 or pu >= limit:
        return base
    return top - (top - base) * max(pu, 0.0) / limit


# ─────────────────────────────────────────── the checks ───────────────────────────────────────────


def _worst(rows: Iterable[dict[str, Any] | None]) -> dict[str, Any] | None:
    return max((r for r in rows if r), key=lambda r: r["utilisation"], default=None)


def _bars_along(lw: float, bars: W.WallBars) -> list[tuple[float, float]]:
    end = bars.cover + bars.horizontal_dia + bars.vertical_dia / 2
    if lw <= 2 * end:
        raise DesignError("the wall is too short for its bars and cover")
    area = bars.layers * bar_area(bars.vertical_dia)
    return [(x, area) for x in W._positions(end, lw - end, bars.vertical_spacing)]


def wall_checks(
    geometry: W.WallGeometry,
    bars: W.WallBars | None,
    forces: list[W.PierForces],
    m: M.Masonry,
    fy: float = 420.0,
    lateral: Iterable[str] = (),
    storeys: int | None = None,
    service: list[W.PierForces] | None = None,
) -> M.MasonryDesign:
    """The strength design checks of a reinforced masonry wall pier (see the module notes).
    ``forces``: factored forces, compression positive [N, N·mm]; ``service``: the pier's service
    forces (allowable stress combinations) for the slender wall deflection."""
    if bars is None:
        raise DesignError(
            f"strength design is for reinforced masonry ({M.clause('strengthMethod')}): the wall "
            "type has no bars"
        )
    s = _s()
    notes: list[str] = list(m.notes)
    if m.fm_source == "estimate":
        notes.append(
            f"f'm is estimated: strength design needs it from prism tests ({M.clause('prisms')})"
        )
    checks: list[dict[str, Any] | None] = []
    t, lw, h = geometry.thickness, geometry.length, geometry.clear_height
    es = float(M.table().elastic.es)
    em = m.em
    n = es / em
    ag = t * lw
    layout = _bars_along(lw, bars)
    steel = sum(a for _, a in layout)
    mid = [f for f in forces if f.where.endswith("middle")] or forces

    # ── slender wall, out of plane (Sec 7.7.1) ──
    sw = s.slenderWall
    checks.append(
        _row(
            f"Slender wall thickness ({M.clause('slenderWall')})",
            float(sw["minThickness"]),
            t,
            "mm",
        )
    )
    checks.append(
        _row(
            f"Slender wall f'm ≤ {float(s.fmRange['slenderWallMax']):g} MPa "
            f"({M.clause('slenderWall')})",
            m.fm,
            float(s.fmRange["slenderWallMax"]),
            "MPa",
        )
    )
    if bars.layers == 2:
        d_out = t - bars.cover - bars.horizontal_dia - bars.vertical_dia / 2
    else:
        d_out = t / 2.0
    # Two layers: the far layer in tension; one central layer: all of it.
    out_steel = steel / 2.0 if bars.layers == 2 else steel
    rho = out_steel / (lw * d_out)
    rho_b = balanced_ratio(m.fm, fy, es)
    checks.append(
        _pct(
            f"Slender wall ρ ≤ {float(sw['maxSteelRatio']):g} ρb ({M.clause('slenderReinforcement')})",
            rho,
            float(sw["maxSteelRatio"]) * rho_b,
            "",
            note=f"ρb = {rho_b:.4f}",
        )
    )
    fr = modulus_of_rupture(m)
    ig = lw * t**3 / 12.0
    mcr = fr * lw * t * t / 6.0
    phi_f = float(s.phi["slenderFlexure"])
    axial_rows, moment_rows = [], []
    for f in mid:
        pu = max(f.P, 0.0)
        axial_rows.append(
            _row(
                f"Slender wall Pu/Ag ≤ {float(sw['axialMax']):g} f'm ({M.clause('slenderWall')})",
                pu / ag,
                float(sw["axialMax"]) * m.fm,
                "MPa",
                f.combination,
                f.where,
            )
        )
        mn, a, ase = slender_moment_strength(out_steel, pu, lw, d_out, m.fm, fy)
        icr = max(cracked_inertia(ase, a, lw, d_out, n), 1e-9)
        m0 = abs(f.M2)
        mu, delta = m0, 0.0
        converged = False
        for _ in range(50):
            delta = mid_deflection(mu, mcr, h, em, ig, icr)
            new = m0 + pu * delta
            if abs(new - mu) <= 1e-6 * max(new, 1.0):
                mu, converged = new, True
                break
            mu = new
        moment_rows.append(
            _row(
                f"Slender wall Mu ≤ φ Mn ({M.clause('slenderMoment')})",
                mu / 1e6,
                phi_f * mn / 1e6,
                "kN·m",
                f.combination,
                f"{f.where}; Δu {delta:.1f} mm (P-delta)"
                + ("" if converged else "; P-delta does not converge"),
                utilisation=None if converged else 99.0,
            )
        )
    checks += [_worst(axial_rows), _worst(moment_rows)]
    if service:
        limit = float(sw["deflection"]) * h
        rows = []
        for f in [g for g in service if g.where.endswith("middle")] or service:
            ps = max(f.P, 0.0)
            _mn, a, ase = slender_moment_strength(out_steel, ps, lw, d_out, m.fm, fy)
            icr = max(cracked_inertia(ase, a, lw, d_out, n), 1e-9)
            ms = abs(f.M2)
            delta = 0.0
            for _ in range(50):
                delta = mid_deflection(ms + ps * delta, mcr, h, em, ig, icr)
            rows.append(
                _row(
                    f"Slender wall service deflection Δs ≤ {float(sw['deflection']):g} h "
                    f"({M.clause('slenderDeflection')})",
                    delta,
                    limit,
                    "mm",
                    f.combination,
                    f.where,
                )
            )
        checks.append(_worst(rows))
    else:
        notes.append("slender wall service deflection: no service forces, not checked")

    # ── shear wall, in plane (Sec 7.7.2) ──
    if m.units != "hollow":
        notes.append(
            f"shear wall strength design is for reinforced hollow-unit masonry "
            f"({M.clause('shearWallShear')}): the in-plane checks are not made for {m.units} "
            "units (use the allowable stress method)"
        )
    else:
        checks += _shear_wall(geometry, bars, forces, m, fy, layout, steel, notes)
    found = [c for c in checks if c]
    strength = [c for c in found if not c["flag"]]
    utilisation = max((c["utilisation"] for c in strength), default=0.0)
    return M.MasonryDesign(found, notes, utilisation)


def _shear_wall(
    geometry: W.WallGeometry,
    bars: W.WallBars,
    forces: list[W.PierForces],
    m: M.Masonry,
    fy: float,
    layout: list[tuple[float, float]],
    steel: float,
    notes: list[str],
) -> list[dict[str, Any] | None]:
    s = _s()
    t, lw = geometry.thickness, geometry.length
    ae = t * lw
    es = float(M.table().elastic.es)
    lo, hi = s.fmRange["shearWall"]
    rows: list[dict[str, Any] | None] = [
        _row(
            f"Shear wall f'm ≥ {float(lo):g} MPa ({M.clause('shearWallRange')})",
            float(lo),
            m.fm,
            "MPa",
        ),
        _row(
            f"Shear wall f'm ≤ {float(hi):g} MPa ({M.clause('shearWallRange')})",
            m.fm,
            float(hi),
            "MPa",
        ),
    ]
    po = float(s.axial["masonry"]) * m.fm * (ae - steel) + fy * steel
    emu = float(s.ultimateStrain)
    d = max(x for x, _ in layout)
    ab = float(s.stressBlock["depth"]) * emu / (emu + fy / es) * d
    pb = float(s.stressBlock["stress"]) * m.fm * t * ab
    mirrored = [(lw - x, a) for x, a in layout]
    rho_n = bars.rho_t(t)
    rho_v = bars.rho_l(t)
    av_fy = ae * rho_n * fy
    fr = modulus_of_rupture(m)
    mcr = fr * t * lw * lw / 6.0
    sw = s.shearWall
    axial, flexure, shear, boundary, cracking = [], [], [], [], []
    flexure_mode = False
    for f in forces:
        pu = max(f.P, 0.0)
        phi_a = float(s.phi["axial"])
        axial.append(
            _row(
                f"Shear wall Pu ≤ φ {float(s.axial['reduction']):g} Po ({M.clause('shearWallAxial')})",
                pu / 1e3,
                phi_a * float(s.axial["reduction"]) * po / 1e3,
                "kN",
                f.combination,
                f.where,
            )
        )
        mn = min(
            section_strength(f.P, lw, t, layout, m.fm, fy)[0],
            section_strength(f.P, lw, t, mirrored, m.fm, fy)[0],
        )
        phi = axial_phi(pu, m.fm, ae, pb, fy)
        flexure.append(
            _row(
                f"Shear wall Mu ≤ φ Mn ({M.clause('shearWallFlexure')})",
                abs(f.M3) / 1e6,
                phi * mn / 1e6,
                "kN·m",
                f.combination,
                f"{f.where}; φ = {phi:.2f}",
            )
        )
        v = abs(f.V2)
        ratio = abs(f.M3) / (v * d) if v > 0 else float(s.shear["ratioHigh"])
        vm = float(s.shear["masonry"]) * shear_coefficient(ratio) * ae * math.sqrt(m.fm)
        vn = min(vm + av_fy, shear_maximum(ratio) * ae * math.sqrt(m.fm))
        v_flex = mn * v / abs(f.M3) if abs(f.M3) > 0 else math.inf
        phi_v = float(s.phi["shear"])
        note = f"{f.where}; M/Vd = {ratio:.2f}, Cd {shear_coefficient(ratio):.2f}"
        in_flexure = vn > v_flex
        if in_flexure:
            flexure_mode = True
            phi_v = float(s.phi["shearFlexure"])
            vn = min(av_fy, shear_maximum(ratio) * ae * math.sqrt(m.fm))
            note += "; flexure mode: Vn = Amv ρn fy (Eq 6.7.49, over the whole height)"
            stress = pu / ae + abs(f.M3) / (t * lw * lw / 6.0)
            b = s.boundary
            if stress > float(b["stress"]) * m.fm:
                boundary.append((f, stress))
        shear.append(
            _row(
                f"Shear wall Vu ≤ φ Vn ({M.clause('shearWallShear')})",
                v / 1e3,
                phi_v * vn / 1e3,
                "kN",
                f.combination,
                note,
            )
        )
        if in_flexure:
            factor = float(sw["crackingFull"] if m.grouting == "full" else sw["crackingPartial"])
            cracking.append(
                _row(
                    f"Shear wall Mn ≥ {factor:g} Mcr ({M.clause('shearWallReinforcement')})",
                    factor * mcr / 1e6,
                    mn / 1e6,
                    "kN·m",
                    f.combination,
                    f"{f.where}; Mcr = S fr, fr {fr:.2f} MPa",
                )
            )
    rows += [_worst(axial), _worst(flexure), _worst(shear), _worst(cracking)]
    # Reinforcement (Sec 7.7.2.6): the least reinforcement of every seismic area, vertical ≥
    # share of horizontal, horizontal spacing in flexure mode.
    z4 = M.table().seismic.zone4
    clause = M.clause("shearWallReinforcement")
    rows.append(_pct(f"Shear wall ρh + ρv ({clause})", float(z4["totalRatio"]), rho_n + rho_v, ""))
    rows.append(_pct(f"Shear wall ρh ({clause})", float(z4["eachRatio"]), rho_n, ""))
    rows.append(_pct(f"Shear wall ρv ({clause})", float(z4["eachRatio"]), rho_v, ""))
    spacing = max(bars.vertical_spacing, bars.horizontal_spacing)
    rows.append(_row(f"Shear wall bar spacing ({clause})", spacing, float(z4["maxSpacing"]), "mm"))
    rows.append(
        _row(
            f"Shear wall bar diameter ({clause})",
            float(z4["barMin"]),
            min(bars.vertical_dia, bars.horizontal_dia),
            "mm",
        )
    )
    rows.append(
        _pct(
            f"Shear wall vertical ≥ {float(sw['verticalShare']):g} × horizontal ({clause})",
            float(sw["verticalShare"]) * rho_n,
            rho_v,
            "",
        )
    )
    if flexure_mode:
        limit = min(float(sw["horizontalSpacingThickness"]) * t, float(sw["horizontalSpacingMax"]))
        rows.append(
            _row(f"Shear wall horizontal spacing ({clause})", bars.horizontal_spacing, limit, "mm")
        )
    if boundary:
        f, stress = max(boundary, key=lambda x: x[1])
        b = s.boundary
        need = float(b["lengthThickness"]) * t
        have = bars.boundary
        ok = (
            have is not None
            and have.hoops
            and have.length >= need - 1e-6
            and have.hoop_dia >= float(b["barMin"]) - 1e-6
            and have.hoop_spacing <= float(b["spacingMax"]) + 1e-6
        )
        rows.append(
            _row(
                f"Boundary members ({M.clause('boundary')})",
                1.0,
                1.0 if ok else 0.0,
                "",
                f.combination,
                f"extreme fibre stress {stress:.2f} MPa > {float(b['stress']):g} f'm: "
                f"confine the end bars over ≥ {need:.0f} mm with ≥ {float(b['barMin']):g} mm at "
                f"≤ {float(b['spacingMax']):g} mm (the wall type's end bars and hoops)"
                + ("" if ok else "; not provided"),
                utilisation=0.0 if ok else 99.0,
            )
        )
    return rows


__all__ = [
    "COMBINATIONS",
    "axial_phi",
    "balanced_ratio",
    "cracked_inertia",
    "method_text",
    "mid_deflection",
    "modulus_of_rupture",
    "section_strength",
    "shear_coefficient",
    "shear_maximum",
    "slender_moment_strength",
    "wall_checks",
]

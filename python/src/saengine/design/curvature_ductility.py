"""Detailing of earthquake-resistant concrete members by curvature ductility and capacity
design, by ductility class (method ``curvatureDuctility`` of the pack's
``concreteMethods.seismic``).

Units: mm, MPa, N, N·mm. The ductility class of a member comes from its seismic system's
``frame`` level (``frameClasses``: special -> DCH, intermediate -> DCM; the systems' mapping
of the pack's seismic table). A lower level (ordinary, low ductility) has no rows here.

- Curvature ductility (:func:`curvature_ductility`): μφ = 2 q0 - 1 when T1 >= TC, else
  1 + 2 (q0 - 1) TC / T1; × ``classBFactor`` with class B steel in the critical regions
  (where the class gives one).
- Beams (:func:`beam_rows`): critical length lcr = ``beamCritical`` hw; hoop spacing s <=
  min(hw / a, b dbw, c, d dbL); hoop diameter >= ``hoopMinDia``; tension ratio ρ >= c fctm /
  fyk and ρ <= ρ' + c / (μφ εsy,d) fcd / fyd; compression steel >= share of the tension
  steel in critical regions; capacity design shear with γRd (:func:`beam_capacity_shear`).
- Columns (:func:`column_rows`): νd = NEd / (Ac fcd) <= ``nuMax``; ρl within ``columnRho``;
  lcr = max(a hc, lcl / b, c); hoop spacing <= min(b0 / a, b, c dbL); restrained bars at most
  ``columnRestrained`` apart; confinement α ωwd >= c μφ νd εsy,d bc / b0 - offset with
  ωwd >= ``omegaBase`` (:func:`confinement`); capacity design shear with γRd.
- Strong column / weak beam: ΣMRc >= ``strongColumn`` ΣMRb (:func:`strong_column`).
- Joints (DCH, :func:`joint_shear_resistance`): Vjhd <= η fcd √(1 - νd / η) bj hjc with
  η = c (1 - fck / divisor), × ``jointExteriorShare`` for exterior joints.
- Ductile walls (:func:`wall_rows`): critical height hcr = max(a lw, hw / b); boundary
  length lc >= max(a lw, b bw); boundary ρv >= ``wallBoundaryRho``; ωwd >= ``wallOmega``;
  web thickness >= max(a, hs / b); design shear × ``wallShearFactor``.
- Coupling beams (:func:`coupling_needs_diagonals`): diagonal bars unless VEd <= fctd bw d
  or l / h >= ``couplingSpanRatio``; VRd = 2 Asi fyd sin α.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import design_strength


def rules() -> Any | None:
    pack = code_context.current()
    if not pack.has("concreteMethods") or not design_strength.partial_factors():
        return None
    from saengine.codes.method_tables import chosen  # C8: another method may hold the group

    return chosen(pack.table("concreteMethods"), "seismic", "curvatureDuctility")


def ductility_class(frame: str | None) -> str | None:
    """The ductility class (DCM, DCH) of a seismic system's frame level, or None."""
    r = rules()
    if r is None or not frame:
        return None
    return r.frameClasses.get(frame)


def class_rules(ductility: str) -> Any:
    return rules().classes[ductility]


def curvature_ductility(q0: float, t1: float, tc: float, ductility: str = "DCM",
                        class_b: bool = False) -> float:  # fmt: skip
    """μφ."""
    mu = 2 * q0 - 1 if t1 >= tc else 1 + 2 * (q0 - 1) * tc / t1
    factor = class_rules(ductility).classBFactor
    if class_b and factor:
        mu *= factor
    return mu


def _row(
    name: str, demand: float, capacity: float, unit: str, note: str, key: str
) -> dict[str, Any]:
    from saengine.design.check import _check

    clause = code_context.cite("concreteMethods", key)
    return _check(name, demand, capacity, unit, None, note + (f" ({clause})" if clause else ""))


def beam_hoop_spacing(hw: float, dbw: float, dbl: float, ductility: str) -> float:
    a, b, c, d = class_rules(ductility).beamHoops
    return min(hw / a, b * dbw, c, d * dbl)


def beam_rho_max(rho_comp: float, mu_phi: float, fck: float, fyk: float, es: float,
                 ductility: str) -> float:  # fmt: skip
    """ρmax of the tension zone in critical regions."""
    c = class_rules(ductility).beamRhoMaxCoefficient
    f_yd = design_strength.fyd(fyk)
    return rho_comp + c / (mu_phi * f_yd / es) * design_strength.fcd(fck) / f_yd


def beam_rows(
    section: Any, transverse: Any | None, ductility: str, mu_phi: float | None = None
) -> list[dict[str, Any]]:
    """Critical-region detailing rows of a rectangular beam."""
    c = class_rules(ductility)
    rows: list[dict[str, Any]] = []
    fck, fyk, es = section.fc, section.fy, section.es
    b, hw = section.width, section.depth
    prop = design_strength.properties(fck)
    rows.append(_row(f"Concrete class ({ductility})", c.fckMin, fck, "MPa",
                     f"fck at least {c.fckMin:g} MPa", "seismicBeams"))  # fmt: skip
    faces = {}
    for top in (True, False):
        bars = [x for x in section.bars if (x.y > 0 if top else x.y < 0)]
        if bars:
            faces[top] = (sum(x.area for x in bars), section.effective_depth(top=top), bars)
    dbl = min((2 * math.sqrt(x.area / math.pi) for x in section.bars), default=0.0)
    for top, (area, d, _bars) in faces.items():
        face = "top" if top else "bottom"
        rho = area / (b * d)
        rho_min = c.beamRhoMinCoefficient * prop.fctm / fyk
        rows.append(_row(f"Seismic least tension steel, {face}", 100 * rho_min, 100 * rho, "%",
                         f"ρmin = {c.beamRhoMinCoefficient:g} fctm/fyk", "seismicBeams"))  # fmt: skip
        other = faces.get(not top)
        if other is not None:
            rows.append(_row(f"Compression steel share, {face} in tension",
                             c.beamCompressionShare * area, other[0], "mm²",
                             f"As' at least {c.beamCompressionShare:g} As in critical regions",
                             "seismicBeams"))  # fmt: skip
            if mu_phi:
                rho_max = beam_rho_max(other[0] / (b * d), mu_phi, fck, fyk, es, ductility)
                rows.append(_row(f"Seismic largest tension steel, {face}", 100 * rho, 100 * rho_max, "%",
                                 f"ρmax = ρ' + {c.beamRhoMaxCoefficient:g}/(μφ εsy,d) fcd/fyd, "
                                 f"μφ = {mu_phi:.2f}", "seismicBeams"))  # fmt: skip
    if c.beamContinuousBars and c.beamContinuousDia:
        for top, (_area, _d, bars) in faces.items():
            big = [x for x in bars if 2 * math.sqrt(x.area / math.pi) >= c.beamContinuousDia - 0.5]
            rows.append(_row(f"Bars along the beam, {'top' if top else 'bottom'}",
                             c.beamContinuousBars, len(big), "bars",
                             f"at least {c.beamContinuousBars} of {c.beamContinuousDia:g} mm",
                             "seismicBeams"))  # fmt: skip
    if transverse is not None and getattr(transverse, "spacing", None):
        s_max = beam_hoop_spacing(hw, transverse.dia, dbl or transverse.dia, ductility)
        rows.append(_row(f"Hoop spacing in critical regions ({ductility})", transverse.spacing,
                         s_max, "mm",
                         f"lcr = {c.beamCritical * hw:.0f} mm; s <= min(hw/{c.beamHoops[0]:g}, "
                         f"{c.beamHoops[1]:g} dbw, {c.beamHoops[2]:g}, {c.beamHoops[3]:g} dbL)",
                         "seismicBeams"))  # fmt: skip
        rows.append(_row("Hoop diameter", c.hoopMinDia, transverse.dia, "mm",
                         f"dbw at least {c.hoopMinDia:g}", "seismicBeams"))  # fmt: skip
    return rows


def beam_capacity_shear(mrb_left: float, mrb_right: float, clear_span: float,
                        gravity_shear: float, ductility: str) -> float:  # fmt: skip
    """VEd [N] = γRd (MRb,1 + MRb,2) / lcl + the gravity shear of G + ψ2 Q."""
    return class_rules(ductility).gammaRdBeam * (mrb_left + mrb_right) / clear_span + gravity_shear


def column_capacity_shear(mrc_top: float, mrc_bottom: float, clear_height: float,
                          ductility: str) -> float:  # fmt: skip
    return class_rules(ductility).gammaRdColumn * (mrc_top + mrc_bottom) / clear_height


def strong_column(sum_mrc: float, sum_mrb: float, ductility: str) -> float:
    """Utilisation of ΣMRc >= factor ΣMRb."""
    factor = class_rules(ductility).strongColumn
    return factor * sum_mrb / sum_mrc if sum_mrc > 0 else math.inf


def column_critical_length(hc: float, clear_height: float, ductility: str) -> float:
    a, b, c = class_rules(ductility).columnCritical
    return max(a * hc, clear_height / b, c)


def column_hoop_spacing(b0: float, dbl: float, ductility: str) -> float:
    a, b, c = class_rules(ductility).columnHoops
    return min(b0 / a, b, c * dbl)


def confinement(mu_phi: float, nu_d: float, eps_syd: float, bc: float, b0: float,
                ductility: str, base: bool = True) -> float:  # fmt: skip
    """α ωwd needed (and at least ωwd minimum, returned as the larger with α taken as 1 for the
    minimum): the confinement demand."""
    c = class_rules(ductility)
    need = c.confinementCoefficient * mu_phi * nu_d * eps_syd * bc / b0 - c.confinementOffset
    floor = c.omegaBase if base else (c.omegaOther or 0.0)
    return max(need, floor)


def confinement_effectiveness(
    b0: float, h0: float, spacing: float, restrained: list[float]
) -> float:
    """α = αn αs of rectangular hoops; ``restrained`` the distances bi between restrained bars
    round the perimeter."""
    alpha_n = 1 - sum(b * b for b in restrained) / (6 * b0 * h0)
    alpha_s = (1 - spacing / (2 * b0)) * (1 - spacing / (2 * h0))
    return max(0.0, alpha_n) * max(0.0, alpha_s)


def column_rows(
    section: Any, transverse: Any | None, ned_max: float, ductility: str
) -> list[dict[str, Any]]:
    """Axial, ratio and hoop rows of a rectangular column (critical regions)."""
    c = class_rules(ductility)
    rows: list[dict[str, Any]] = []
    fck = section.fc
    area = section.gross_area
    nu_d = max(ned_max, 0.0) / (area * design_strength.fcd(fck))
    rows.append(_row(f"Normalised axial force νd ({ductility})", nu_d, c.nuMax, "",
                     f"νd = NEd/(Ac fcd), NEd = {ned_max / 1e3:.0f} kN (the largest of all "
                     "combinations: on the safe side)", "seismicColumns"))  # fmt: skip
    rho = section.steel_area / area
    lo, hi = c.columnRho
    rows.append(_row("Seismic least column steel", 100 * lo, 100 * rho, "%", f"ρl at least {lo:g}",
                     "seismicColumns"))  # fmt: skip
    rows.append(_row("Seismic largest column steel", 100 * rho, 100 * hi, "%", f"ρl at most {hi:g}",
                     "seismicColumns"))  # fmt: skip
    if c.columnMinDimension:
        rows.append(_row("Least column dimension", c.columnMinDimension,
                         min(section.width, section.depth), "mm",
                         f"at least {c.columnMinDimension:g} mm", "seismicColumns"))  # fmt: skip
    dbl = min((2 * math.sqrt(x.area / math.pi) for x in section.bars), default=0.0)
    if transverse is not None and getattr(transverse, "spacing", None):
        cover = getattr(transverse, "cover", None) or 0.0
        b0 = (
            min(section.width, section.depth) - 2 * cover
            if cover
            else min(section.width, section.depth)
        )
        rows.append(_row(f"Hoop spacing in critical regions ({ductility})", transverse.spacing,
                         column_hoop_spacing(b0, dbl, ductility), "mm",
                         f"s <= min(b0/{c.columnHoops[0]:g}, {c.columnHoops[1]:g}, "
                         f"{c.columnHoops[2]:g} dbL)", "seismicColumns"))  # fmt: skip
        rows.append(_row("Hoop diameter", c.hoopMinDia, transverse.dia, "mm",
                         f"dbw at least {c.hoopMinDia:g}", "seismicColumns"))  # fmt: skip
    return rows


# ───────────── Alpha 9 C5c: the confinement ωwd of columns and walls (wired) ─────────────


def mu_phi_of(settings: Any, project: dict[str, Any] | None, ductility: str) -> tuple[float, str]:
    """(μφ, how) of the project's critical regions: q0 the behaviour factor the analysis uses
    (kw = 1), T1 the pack's approximate period Ct H^(3/4) of the structure's height (SAEngine
    practice: shorter than the modal one, so μφ is on the safe side where T1 < TC) and TC of
    the ground type and spectrum type."""
    from saengine.library.settings import derived

    values = derived(settings)
    q0 = float(values.get("R") or 1.5)
    seismic = code_context.table("seismic")
    site = getattr(getattr(settings, "site", None), "siteClass", None)
    spectra = getattr(seismic, "spectra", None) or {}
    kind = str(getattr(seismic, "spectrumType", None) or "1")
    row = (spectra.get(kind) or {}).get(site) if spectra else None
    row = row or seismic.siteClasses.get(site) or next(iter(seismic.siteClasses.values()))
    tc = float(row.TC)
    height = 0.0
    if project:
        zs = [float(n["coords"][2]) for n in project.get("nodes", [])]
        height = max(zs) - min(zs) if zs else 0.0
    system = seismic.systems.get(getattr(settings.seismic, "system", ""), None)
    family = getattr(system, "periodFamily", None) or "other"
    coefficients = seismic.periodCoefficients.get(family) or seismic.periodCoefficients.get("other")
    t1 = coefficients.Ct * max(height, 1.0) ** coefficients.m if coefficients else tc
    mu = curvature_ductility(q0, t1, tc, ductility)
    return mu, f"μφ = {mu:.2f} from q0 = {q0:g}, T1 = Ct H^m = {t1:.2f} s, TC = {tc:g} s"


def _omega(volume_ratio: float, fyk: float, fck: float) -> float:
    return volume_ratio * design_strength.fyd(fyk) / design_strength.fcd(fck)


def confinement_rows(
    section: Any, transverse: Any | None, ned_max: float, ductility: str, mu_phi: tuple[float, str]
) -> list[dict[str, Any]]:
    """The confinement of a rectangular column's critical regions: ωwd of its hoops and ties
    (the core to the hoops' centreline, the legs of ``transverse``) at least the base value, and
    α ωwd >= c μφ νd εsy,d bc/b0 - offset with α = αn αs (the restrained bars taken at the legs,
    evenly spaced). The base critical region's requirement for all of them (on the safe side)."""
    if transverse is None or not getattr(transverse, "spacing", None):
        return []
    c = class_rules(ductility)
    mu, how = mu_phi
    fck = section.fc
    cover = float(getattr(transverse, "cover", None) or 40.0)
    dbw = float(transverse.dia)
    b, h = float(min(section.width, section.depth)), float(max(section.width, section.depth))
    b0, h0 = b - 2 * cover - dbw, h - 2 * cover - dbw
    if b0 <= 0 or h0 <= 0:
        return []
    legs_x = int(getattr(transverse, "legsX", None) or getattr(transverse, "legs", 2) or 2)
    legs_y = int(getattr(transverse, "legsY", None) or getattr(transverse, "legs", 2) or 2)
    s = float(transverse.spacing)
    area = math.pi * dbw**2 / 4
    volume = area * (legs_x * h0 + legs_y * b0) / (b0 * h0 * s)
    fyk = getattr(transverse, "fy", None) or section.fy
    omega = _omega(volume, fyk, fck)
    gaps = [b0 / max(legs_y - 1, 1)] * 2 * max(legs_y - 1, 1)
    gaps += [h0 / max(legs_x - 1, 1)] * 2 * max(legs_x - 1, 1)
    alpha = confinement_effectiveness(b0, h0, s, gaps)
    nu_d = max(ned_max, 0.0) / (section.gross_area * design_strength.fcd(fck))
    eps = design_strength.fyd(section.fy) / design_strength.rules().steelE
    need = max(c.confinementCoefficient * mu * nu_d * eps * b / b0 - c.confinementOffset, 0.0)
    rows = [
        _row(f"Confinement ωwd ({ductility})", c.omegaBase, omega, "",
             f"ωwd = Vhoops/Vcore fyd/fcd = {omega:.3f} ({legs_x} × {legs_y} legs Ø{dbw:g} @ "
             f"{s:g}, b0 = {b0:.0f}, h0 = {h0:.0f} mm); at least {c.omegaBase:g}", "confinement"),
        _row(f"Confinement α ωwd ({ductility})", need, alpha * omega, "",
             f"α ωwd >= {c.confinementCoefficient:g} μφ νd εsy,d bc/b0 - "
             f"{c.confinementOffset:g} = {need:.3f}; α = αn αs = {alpha:.2f}, νd = {nu_d:.3f}, "
             f"εsy,d = {eps * 1e3:.2f} ‰; {how}; the base critical region's rule for every "
             "critical region (on the safe side)", "confinement"),
    ]  # fmt: skip
    return rows


def wall_confinement_rows(
    boundary: Any, t: float, lw: float, cover: float, ned_max: float, fck: float, fyk: float,
    rho_v: float, ductility: str, mu_phi: tuple[float, str],
) -> list[dict[str, Any]]:  # fmt: skip
    """The confinement of a ductile wall's boundary elements (the wall type's end bars and
    hoops ``boundary``, :class:`saengine.design.walls.Boundary`): ωwd at least the class's wall
    value, and α ωwd >= c μφ (νd + ωv) εsy,d bw/b0 - offset, ωv = ρv fyd/fcd of the web's
    vertical bars."""
    if boundary is None or not getattr(boundary, "hoops", True) or boundary.length <= 0:
        return []
    c = class_rules(ductility)
    mu, how = mu_phi
    dbw, s = float(boundary.hoop_dia), float(boundary.hoop_spacing)
    b0 = t - 2 * cover - dbw
    h0 = boundary.length - cover - dbw
    if b0 <= 0 or h0 <= 0 or s <= 0:
        return []
    area = math.pi * dbw**2 / 4
    volume = area * (boundary.legs_along * h0 + boundary.legs_across * b0) / (b0 * h0 * s)
    omega = _omega(volume, fyk, fck)
    gaps = [b0 / max(boundary.legs_across - 1, 1)] * 2 * max(boundary.legs_across - 1, 1)
    gaps += [h0 / max(boundary.legs_along - 1, 1)] * 2 * max(boundary.legs_along - 1, 1)
    alpha = confinement_effectiveness(b0, h0, s, gaps)
    f_cd = design_strength.fcd(fck)
    nu_d = max(ned_max, 0.0) / (t * lw * f_cd)
    omega_v = rho_v * design_strength.fyd(fyk) / f_cd
    eps = design_strength.fyd(fyk) / design_strength.rules().steelE
    need = c.confinementCoefficient * mu * (nu_d + omega_v) * eps * t / b0 - c.confinementOffset
    rows = [
        _row(f"Boundary element confinement ωwd ({ductility})", c.wallOmega, omega, "",
             f"ωwd = {omega:.3f} of the end hoops Ø{dbw:g} @ {s:g} over b0 × h0 = {b0:.0f} × "
             f"{h0:.0f} mm; at least {c.wallOmega:g}", "confinement"),
        _row(f"Boundary element α ωwd ({ductility})", max(need, 0.0), alpha * omega, "",
             f"α ωwd >= {c.confinementCoefficient:g} μφ (νd + ωv) εsy,d bw/b0 - "
             f"{c.confinementOffset:g}; α = {alpha:.2f}, νd = {nu_d:.3f}, ωv = {omega_v:.3f}; "
             f"{how}", "confinement"),
    ]  # fmt: skip
    return rows


def joint_shear_resistance(fck: float, nu_d: float, bj: float, hjc: float,
                           exterior: bool = False) -> float:  # fmt: skip
    """Vjhd at most [N] (DCH)."""
    c = class_rules("DCH")
    eta = c.jointEtaCoefficient * (1 - fck / c.jointEtaDivisor)
    v = eta * design_strength.fcd(fck) * math.sqrt(max(0.0, 1 - nu_d / eta)) * bj * hjc
    return v * (c.jointExteriorShare if exterior else 1.0)


def wall_critical_height(lw: float, hw: float, ductility: str) -> float:
    a, b = class_rules(ductility).wallCritical
    return max(a * lw, hw / b)


def wall_rows(lw: float, bw: float, storey_height: float, boundary_length: float | None,
              boundary_rho: float | None, ductility: str) -> list[dict[str, Any]]:  # fmt: skip
    c = class_rules(ductility)
    rows = []
    mm, n = c.wallThickness
    rows.append(_row(f"Ductile wall thickness ({ductility})", max(mm, storey_height / n), bw, "mm",
                     f"bw at least max({mm:g}, hs/{n:g})", "seismicWalls"))  # fmt: skip
    a, b = c.wallBoundaryLength
    if boundary_length is not None:
        rows.append(_row("Boundary element length", max(a * lw, b * bw), boundary_length, "mm",
                         f"lc at least max({a:g} lw, {b:g} bw)", "seismicWalls"))  # fmt: skip
    if boundary_rho is not None:
        rows.append(_row("Boundary element steel", 100 * c.wallBoundaryRho, 100 * boundary_rho, "%",
                         f"ρv at least {c.wallBoundaryRho:g}", "seismicWalls"))  # fmt: skip
    return rows


def wall_design_shear(ved: float, ductility: str) -> float:
    return class_rules(ductility).wallShearFactor * ved


def coupling_needs_diagonals(ved: float, bw: float, d: float, span: float, depth: float,
                             fck: float) -> bool:  # fmt: skip
    c = class_rules("DCH")
    if span / depth >= c.couplingSpanRatio:
        return False
    return ved > design_strength.fctd(fck) * bw * d


def coupling_diagonal_resistance(asi: float, fyk: float, alpha: float) -> float:
    """VRd [N] = 2 Asi fyd sin α (α in radians)."""
    return 2 * asi * design_strength.fyd(fyk) * math.sin(alpha)

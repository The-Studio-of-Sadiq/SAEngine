"""Cold-formed steel members of lipped channels and lipped Z sections: the pack's
``coldFormed`` table (method ``effectiveSection``; alpha 9 C12). The US pack follows AISI S100
(LRFD, Winter's effective width, the direct strength distortional curves), the Eurocodes pack
EN 1993-1-3 (partial factors, the effective widths of EN 1993-1-5, the edge stiffener's χd)
and the IS pack IS 801 (permissible stresses, the limiting widths in kgf/cm², the lip's least
depth). :func:`saengine.design.steel.members.check_member` hands a member of a lipped section
here (the design run, the section proposals and the report all go through it); a pack without
the table does not design them (the member says so).

What is checked, every number from the table:

- **Effective widths** of the flat plates (web, flanges, lips; the flat width less t + r at
  each bend): the web and the lipped flanges as stiffened elements, the lips as unstiffened
  ones, by the pack's method: ``winter`` ρ = (1 - 0.22/λ)/λ, λ = 1.052/√k (w/t) √(f/E);
  ``plateSlenderness`` internal ρ = (λp - 0.055 (3 + ψ))/λp², outstand (λp - 0.188)/λp², λp =
  (b/t)/(28.4 ε √kσ); ``limitingWidth`` be/t = 2120/√f (1 - 465/((w/t) √f)) above (w/t)lim =
  1435/√f (f in kgf/cm²), an unstiffened lip counted to 530 t/√f. The effective area at the
  member's buckling stress (``lrfd``) or at fy; the effective modulus about x with the top
  flange, its lip and the upper half of the web in compression (ψ = -1 for the web, the
  ineffective strip 0.4 beff from the flange; one pass, the neutral axis of the gross section:
  SAEngine practice).
- **Distortional buckling** (every method's critical stress): the edge stiffener (the lip and
  half the flange) as a strut on the elastic spring of the web and flange plates, K = E t³ /
  (4 (1 - ν²)) / (b1² hw + b1³ + 0.5 b1 b2 hw kf), σcr,d = 2 √(K E Is) / As (kf = 1 in
  compression, 0 in bending); then ``reductionCurve`` χd on the stiffener's area,
  ``directStrength`` Pnd and Mnd by λd, or ``lipAdequacy`` the lip at least dmin (else the
  flange counts as unstiffened).
- **Members**: tension Ag fy; compression by the elastic buckling stress Fe of flexural (x, y,
  the least principal axis of a Z), torsional and flexural-torsional buckling (channels) and the
  pack's buckling curve on the effective area; flexure about x with lateral-torsional buckling
  (Mcr = Cb r0 A √(σey σt) of a channel, Cb π² E d Iyc / (2 (Ky Ly)²) of a Z, Cb = 1: on the
  safe side), about y by yielding of the gross section; web shear by the pack's form; combined
  forces by the pack's interaction.

Units: mm, N, MPa; the rows in kN and kN·m.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from saengine.codes import context as code_context

FAMILIES = ("lippedChannel", "lippedZ")
TABLE = "coldFormed"


def table() -> Any | None:
    """The pack's ``coldFormed`` table; None when the pack in force has none."""
    try:
        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - a bare calculation without packs
        return None


def is_cold_formed(shape: Any) -> bool:
    return getattr(shape, "family", None) in FAMILIES


def cite(key: str) -> str:
    return code_context.cite(TABLE, key)


# ─────────────────────────────────── effective widths ───────────────────────────────────


def rho(w: float, t: float, f: float, internal: bool, psi: float, t_: Any) -> float:
    """ρ = be / w of a flat element ``w`` wide, ``t`` thick at the stress ``f`` [MPa]
    (``internal``: stiffened; ``psi``: the stress ratio of its edges, 1 uniform)."""
    ew = t_.effectiveWidth
    fac = [float(x) for x in ew.factors]
    e = float(t_.E)
    if w <= 0 or f <= 0:
        return 1.0
    ratio = w / t
    if ew.method == "winter":
        a, lim, c = fac[0], fac[1], fac[2]
        k = float(ew.kInternal) if internal else float(ew.kOutstand)
        if internal and psi < 1:
            k = 4 + 2 * (1 - psi) ** 3 + 2 * (1 - psi)
        lam = c / math.sqrt(k) * ratio * math.sqrt(f / e)
        return 1.0 if lam <= lim else min(1.0, (1 - a / lam) / lam)
    if ew.method == "plateSlenderness":
        a, b, c, ref = fac[0], fac[1], fac[2], fac[3] if len(fac) > 3 else 235.0
        eps = math.sqrt(ref / f)
        if internal:
            k = float(ew.kInternal) if psi >= 1 else (23.9 if psi <= -1 else 8.2 / (1.05 + psi))
            lam = ratio / (c * eps * math.sqrt(k))
            limit = 0.5 + math.sqrt(max(0.085 - 0.055 * psi, 0.0))
            return 1.0 if lam <= limit else min(1.0, (lam - a * (3 + psi)) / lam**2)
        k = float(ew.kOutstand)
        lam = ratio / (c * eps * math.sqrt(k))
        return 1.0 if lam <= 0.748 else min(1.0, (lam - b) / lam**2)
    # limitingWidth (IS 801 type): f in the pack's stress unit
    a, b, c = fac[0], fac[1], fac[2]
    fu = f / float(ew.stressUnit)
    root = math.sqrt(fu)
    if internal:
        if ratio <= a / root:
            return 1.0
        return min(1.0, b / root * (1 - c / (ratio * root)) / ratio)
    full = fac[3] / root if len(fac) > 3 else ratio
    return min(1.0, full / ratio)


def stiffened_flange(shape: Any, fy: float, t_: Any) -> tuple[bool, str]:
    """Whether the lips stiffen the flanges (``lipAdequacy``: dmin; the other methods: always,
    the distortional mode carrying the lip's weakness)."""
    dist = t_.distortional
    if dist.method != "lipAdequacy":
        return True, ""
    d = shape.dims
    a, b, c = (float(x) for x in dist.factors[:3])
    f = fy / float(dist.stressUnit)
    wt = d["flange"] / d["t"]
    inner = max(wt**2 - b / f, 0.0)
    dmin = max(a * d["t"] * inner ** (1 / 6), c * d["t"])
    ok = d["c"] >= dmin
    return ok, f"lip {d['c']:.0f} mm against dmin = {dmin:.1f} mm"


def effective_area(shape: Any, f: float, t_: Any, stiff: bool) -> tuple[float, str]:
    """Ae at the uniform compression ``f`` and how."""
    d = shape.dims
    t = d["t"]
    web = rho(d["web"], t, f, True, 1.0, t_)
    flange = rho(d["flange"], t, f, stiff, 1.0, t_)
    lip = rho(d["lip"], t, f, False, 1.0, t_) if stiff else 1.0
    lost = (1 - web) * d["web"] * t + 2 * (1 - flange) * d["flange"] * t
    lost += 2 * (1 - lip) * d["lip"] * t
    return shape.area - lost, f"ρ web {web:.2f}, flanges {flange:.2f}, lips {lip:.2f}"


def effective_modulus(shape: Any, f: float, t_: Any, stiff: bool, stiffener_loss: float = 0.0):
    """(Se about x with the top in compression at ``f``, how); ``stiffener_loss``: area of the
    top edge stiffener lost to distortional buckling (χd), taken off at its centroid."""
    d = shape.dims
    t, h, bend = d["t"], d["d"], d["t"] + d["r"]
    cy = d["cy"]
    flange = rho(d["flange"], t, f, stiff, 1.0, t_)
    lip = rho(d["lip"], t, f, False, 1.0, t_) if stiff else 1.0
    bc = d["web"] / 2
    web = (
        rho(d["web"], t, f, True, -1.0, t_) if t_.effectiveWidth.method != "limitingWidth" else 1.0
    )
    # ρ of the whole web under ψ = -1 applies to its compression half (be = ρ bc).
    strips = [
        ((1 - flange) * d["flange"] * t, h - t / 2 - cy),
        ((1 - lip) * d["lip"] * t, h - bend - d["lip"] / 2 - cy),
        (
            (1 - web) * bc * t,
            (h / 2 - bend) - 0.4 * web * bc - (1 - web) * bc / 2 + (h / 2 - cy),
        ),
        (stiffener_loss, h - t - d["lip"] / 2 - cy),
    ]
    a_eff = shape.area - sum(a for a, _ in strips)
    shift = -sum(a * y for a, y in strips) / a_eff
    i_eff = shape.ix - sum(a * y**2 for a, y in strips) - a_eff * shift**2
    top = h - (cy + shift)
    bottom = cy + shift
    se = i_eff / max(top, bottom)
    return se, f"ρ flange {flange:.2f}, lip {lip:.2f}, web {web:.2f} (compression half)"


# ─────────────────────────────────── distortional buckling ───────────────────────────────────


def distortional_stress(shape: Any, e: float, nu: float, bending: bool) -> tuple[float, float]:
    """(σcr,d [MPa], As [mm²]) of the edge stiffener: the lip and half the flange on the spring
    of the web and flange plates."""
    d = shape.dims
    t = d["t"]
    bp = d["b"] - t
    bs, cs = bp / 2, d["c"] - t / 2
    area = t * (bs + cs)
    yc = (cs * t * cs / 2) / area  # from the flange centreline, towards the lip's tip
    i_s = t * cs**3 / 12 + cs * t * (cs / 2 - yc) ** 2 + bs * t * yc**2
    xc = (bs * t * (bp - bs / 2) + cs * t * bp) / area
    hw = d["d"] - t
    kf = 0.0 if bending else 1.0
    denom = xc**2 * hw + xc**3 + 0.5 * xc * xc * hw * kf
    k = e * t**3 / (4 * (1 - nu**2)) / denom
    return 2 * math.sqrt(k * e * i_s) / area, area


def chi_d(lam: float, f: list[float]) -> float:
    """χd of the reduction curve: 1 to a, b - c λd to d, e / λd beyond."""
    a, b, c, dd, e = f[:5]
    if lam <= a:
        return 1.0
    if lam < dd:
        return min(1.0, b - c * lam)
    return min(1.0, e / lam)


def dsm(ratio: float, limit: float, k: float, power: float) -> float:
    """The direct strength curve's share of the yield: 1 while λd <= ``limit``, else (1 - k
    r^p) r^p, r = Pcr / Py."""
    lam = math.sqrt(1 / ratio) if ratio > 0 else math.inf
    if lam <= limit:
        return 1.0
    return (1 - k * ratio**power) * ratio**power


# ─────────────────────────────────── member resistances ───────────────────────────────────


def elastic_buckling(shape: Any, e: float, g: float, klx: float, kly: float, klz: float):
    """(Fe [MPa], mode) of flexural, torsional and flexural-torsional buckling."""

    def euler(kl: float, r: float) -> float:
        return math.pi**2 * e / (kl / r) ** 2 if kl > 0 else math.inf

    fex = euler(klx, shape.rx)
    r_minor = shape.rz if shape.family == "lippedZ" else shape.ry
    fey = euler(kly, r_minor)
    ro2 = shape.ro2
    ft = (g * shape.j + (math.pi**2 * e * shape.cw / klz**2 if klz > 0 else 0.0)) / (
        shape.area * ro2
    )
    modes = [(fex, "flexural about x"), (fey, "flexural about the minor axis"), (ft, "torsional")]
    if shape.family == "lippedChannel":
        beta = 1 - shape.x0**2 / ro2
        s = fex + ft
        fft = (s - math.sqrt(max(s**2 - 4 * beta * fex * ft, 0.0))) / (2 * beta)
        modes.append((fft, "flexural-torsional"))
    return min(modes, key=lambda m: m[0])


def chi(lam: float, alpha: float) -> float:
    if lam <= 0.2:
        return 1.0
    phi = 0.5 * (1 + alpha * (lam - 0.2) + lam**2)
    return min(1.0, 1 / (phi + math.sqrt(max(phi**2 - lam**2, 0.0))))


def critical_moment(shape: Any, e: float, g: float, kly: float, klz: float) -> float:
    """Mcr [N·mm] with Cb = 1: channels r0 A √(σey σt), Z sections π² E d Iyc / (2 (Ky Ly)²)."""
    if kly <= 0 or klz <= 0:
        return math.inf
    if shape.family == "lippedZ":
        return math.pi**2 * e * shape.dims["d"] * (shape.iy / 2) / (2 * kly**2)
    sey = math.pi**2 * e / (kly / shape.ry) ** 2
    st = (g * shape.j + math.pi**2 * e * shape.cw / klz**2) / (shape.area * shape.ro2)
    return math.sqrt(shape.ro2) * shape.area * math.sqrt(sey * st)


class _Resistances:
    """The member's resistances (design values, N and N·mm) and their notes."""

    def __init__(self, shape: Any, steel: Any, lengths: Any, options: Any, t_: Any) -> None:
        r = t_.resistance
        self.t_, self.shape = t_, shape
        fy, e, g = float(steel.fy), float(t_.E), float(t_.G)
        self.fy = fy
        self.fa: float | None = None  # allowableStress: Fa1, Fb and F'e of the interaction
        self.fb: float | None = None
        self.fe_prime = math.inf
        unit_k = getattr(getattr(options, "stability", None), "unit_k", None)
        mid = float(lengths.length) / 2
        kx, lx, _ = lengths.effective("x", mid, unit_k)
        ky, ly, _ = lengths.effective("y", mid, unit_k)
        kz, lz, _ = lengths.effective("z", mid, unit_k)
        self.klx, self.kly, self.klz = kx * lx, ky * ly, kz * lz
        lb = max(lengths.ltb_top.longest(), lengths.ltb_bottom.longest()) * 1e3
        stiff, self.lip_note = stiffened_flange(shape, fy, t_)
        self.lip_ok = stiff
        self.allowable = r.format == "allowableStress"
        fac = r.factors
        dist = t_.distortional
        nu = float(dist.poisson)
        df = [float(x) for x in dist.factors]
        fe, mode = elastic_buckling(shape, e, g, self.klx, self.kly, self.klz)
        sig_c, a_s = distortional_stress(shape, e, nu, False)
        sig_b, a_sb = distortional_stress(shape, e, nu, True)
        lam_c = math.sqrt(fy / fe) if fe > 0 else math.inf
        mcr = critical_moment(shape, e, g, max(self.kly, lb), max(self.klz, lb))
        sf = shape.sx
        # Compression
        if r.format == "lrfd":
            fn = (0.658 ** (lam_c**2) if lam_c <= 1.5 else 0.877 / lam_c**2) * fy
            ae, how = effective_area(shape, fn, t_, stiff)
            pn = ae * fn
            note = f"Fe = {fe:.0f} MPa ({mode}), Fn = {fn:.0f} MPa, Ae = {ae:.0f} mm² ({how})"
            if dist.method == "directStrength":
                py = shape.area * fy
                share = dsm(shape.area * sig_c / py, df[0], df[1], df[2])
                pnd = share * py
                note += f"; distortional Fcrd = {sig_c:.0f} MPa, Pnd = {pnd / 1e3:.1f} kN"
                pn = min(pn, pnd)
            self.pc = float(fac["compression"]) * pn
        elif r.format == "partialFactors":
            ae, how = effective_area(shape, fy, t_, stiff)
            if dist.method == "reductionCurve":
                xd = chi_d(math.sqrt(fy / sig_c), df)
                ae -= 2 * (1 - xd) * a_s
                how += f"; χd = {xd:.3f} (σcr,s = {sig_c:.0f} MPa)"
            lam = math.sqrt(ae * fy / (shape.area * fe)) if fe > 0 else math.inf
            curve = r.bucklingCurve
            x = chi(lam, float(r.alpha.get(curve, 0.34)))
            pn = min(
                ae * fy / float(fac.get("section", fac["compression"])),
                x * ae * fy / float(fac["compression"]),
            )
            note = f"Ncr = A Fe, Fe = {fe:.0f} MPa ({mode}), λ̄ = {lam:.2f}, χ = {x:.3f} (curve {curve}), Aeff = {ae:.0f} mm² ({how})"
            self.pc = pn
        else:
            ae, how = effective_area(shape, 0.6 * fy, t_, stiff)
            q = ae / shape.area
            s = math.pi * math.sqrt(e / fe) if fe > 0 else math.inf
            cc = math.sqrt(2 * math.pi**2 * e / fy)
            share = float(fac["compression"])
            if s < cc / math.sqrt(q):
                fa = share * q * fy - 3 * (q * fy) ** 2 * s**2 / (23 * math.pi**2 * e)
            else:
                fa = 12 * math.pi**2 * e / (23 * s**2)
            self.pc = max(fa, 0.0) * shape.area
            self.fa = max(fa, 1e-9)
            self.fe_prime = (
                12 * math.pi**2 * e / (23 * (self.klx / shape.rx) ** 2)
                if self.klx > 0
                else math.inf
            )
            note = f"Fa1 = {fa:.0f} MPa at the equivalent slenderness {s:.0f} ({mode}), Q = {q:.3f} ({how})"
        self.pc_note = note
        # Tension
        self.pt = (
            float(fac["tension"]) * shape.area * fy
            if r.format != "partialFactors"
            else shape.area * fy / float(fac["tension"])
        )
        # Flexure about x
        if r.format == "lrfd":
            fcre = mcr / sf
            if fcre >= 2.78 * fy:
                fn = fy
            elif fcre > 0.56 * fy:
                fn = 10 / 9 * fy * (1 - 10 * fy / (36 * fcre))
            else:
                fn = fcre
            se, how = effective_modulus(shape, fy, t_, stiff)
            mn = se * fn
            note = f"Mcr = {mcr / 1e6:.1f} kN·m (Cb = 1), Fn = {fn:.0f} MPa, Se = {se / 1e3:.1f}×10³ mm³ ({how})"
            if dist.method == "directStrength":
                my = sf * fy
                share = dsm(sf * sig_b / my, df[3], df[4], df[5])
                note += f"; distortional Fcrd = {sig_b:.0f} MPa, Mnd = {share * my / 1e6:.2f} kN·m"
                mn = min(mn, share * my)
            self.mx = float(fac["flexure"]) * mn
        elif r.format == "partialFactors":
            loss = 0.0
            how_d = ""
            if dist.method == "reductionCurve":
                xd = chi_d(math.sqrt(fy / sig_b), df)
                loss = (1 - xd) * a_sb
                how_d = f"; χd = {xd:.3f} (σcr,s = {sig_b:.0f} MPa)"
            se, how = effective_modulus(shape, fy, t_, stiff, loss)
            lam_lt = math.sqrt(se * fy / mcr) if mcr > 0 else 0.0
            xlt = chi(lam_lt, float(r.alpha.get("lt", r.alpha.get("b", 0.34))))
            mn = min(
                se * fy / float(fac.get("section", fac["flexure"])),
                xlt * se * fy / float(fac["flexure"]),
            )
            note = f"Weff = {se / 1e3:.1f}×10³ mm³ ({how}{how_d}), Mcr = {mcr / 1e6:.1f} kN·m (C1 = 1), χLT = {xlt:.3f}"
            self.mx = mn
        else:
            se, how = effective_modulus(shape, 0.6 * fy, t_, stiff)
            ratio = (
                lb**2
                * sf
                / (shape.dims["d"] * (shape.iy / 2) * (0.5 if shape.family == "lippedZ" else 1.0))
                if lb > 0
                else 0.0
            )
            share = float(fac["flexure"])
            lo, hi = 0.36 * math.pi**2 * e / fy, 1.8 * math.pi**2 * e / fy
            if ratio <= lo:
                fb = share * fy
            elif ratio <= hi:
                fb = 2 / 3 * fy - fy**2 * ratio / (5.4 * math.pi**2 * e)
            else:
                fb = share * math.pi**2 * e / ratio
            fb = min(fb, share * fy)
            self.fb = fb
            self.mx = fb * se
            note = f"Fb = {fb:.0f} MPa (L² Sxc / (d Iyc) = {ratio:.0f}, Cb = 1), Se = {se / 1e3:.1f}×10³ mm³ ({how})"
        self.mx_note = note
        # Flexure about y: yielding of the gross section
        if r.format == "partialFactors":
            self.my = shape.sy * fy / float(fac["flexure"])
        elif r.format == "lrfd":
            self.my = float(fac["flexure"]) * shape.sy * fy
        else:
            self.my = float(fac["flexure"]) * shape.sy * fy
        # Shear along the web
        d = shape.dims
        h, t = d["web"], d["t"]
        aw = h * t
        ht = h / t
        lim = [float(x) for x in r.shearLimits]
        if r.format == "lrfd":
            kv = 5.34
            root = math.sqrt(e * kv / fy)
            if ht <= lim[0] * root:
                vn = float(r.shearYield) * fy * aw
            elif ht <= lim[1] * root:
                vn = float(r.shearYield) * t**2 * math.sqrt(kv * fy * e)
            else:
                vn = 0.904 * e * kv * t**3 / h
            self.v = float(fac["shear"]) * vn
            self.v_note = f"h/t = {ht:.0f}, kv = {kv:g}, Vn = {vn / 1e3:.1f} kN"
        elif r.format == "partialFactors":
            lam_w = 0.346 * ht * math.sqrt(fy / e)
            if lam_w <= lim[0]:
                fbv = float(r.shearYield) * fy
            elif lam_w < lim[1]:
                fbv = 0.48 * fy / lam_w
            else:
                fbv = 0.67 * fy / lam_w**2
            self.v = aw * fbv / float(fac["shear"])
            self.v_note = f"λ̄w = {lam_w:.2f}, fbv = {fbv:.0f} MPa (no stiffening at the support)"
        else:
            unit = float(t_.effectiveWidth.stressUnit)
            fyu = fy / unit
            a, b = float(fac.get("shearA", 1275.0)), float(fac.get("shearB", 5_850_000.0))
            if ht <= lim[0] / math.sqrt(fyu):
                fv = min(a * math.sqrt(fyu) / ht, float(r.shearYield) * fyu)
            else:
                fv = b / ht**2
            self.v = fv * unit * aw
            self.v_note = f"h/t = {ht:.0f}, Fv = {fv:.0f} (×{unit:g} MPa)"
        self.load_factor = float(r.loadFactor) if self.allowable else 1.0


def check_member(
    shape: Any,
    steel: Any,
    stations: Sequence[Any],
    lengths: Any,
    kind: str = "member",
    options: Any = None,
) -> list[dict[str, Any]]:
    """The checks of a cold-formed member, enveloping its combinations and stations (the steel
    member's report format)."""
    from saengine.design.steel.members import SteelDesignError, _check, _ratio, _Worst

    t_ = table()
    if t_ is None:
        raise SteelDesignError(
            "cold-formed lipped sections: not covered by the code pack in force (no coldFormed "
            "table)"
        )
    d = shape.dims
    if d["t"] > float(t_.thicknessMax):
        raise SteelDesignError(
            f"cold-formed: t = {d['t']:g} mm above the {float(t_.thicknessMax):g} mm the code "
            "pack covers"
        )
    res = _Resistances(shape, steel, lengths, options, t_)
    lf = res.load_factor
    tail = f" (working forces: the factored ones / {lf:g})" if lf != 1.0 else ""
    r = t_.resistance
    worst = {k: _Worst() for k in ("t", "c", "mx", "my", "v", "i")}
    compressed = tensioned = False
    for st in stations:
        for k in range(len(st.s)):
            p = float(st.P[k]) / lf
            mx, my = abs(float(st.Mx[k])) / lf, abs(float(st.My[k])) / lf
            vy = abs(float(st.Vy[k])) / lf
            where = st.where[k]
            if p < 0:
                tensioned = True
                worst["t"].offer(
                    _ratio(-p, res.pt),
                    -p,
                    res.pt,
                    st.combination,
                    f"Ag fy{tail}; {where}",
                    cite("tension"),
                )
            elif p > 0:
                compressed = True
                worst["c"].offer(
                    _ratio(p, res.pc),
                    p,
                    res.pc,
                    st.combination,
                    f"{res.pc_note}{tail}; {where}",
                    cite("compression"),
                )
            worst["mx"].offer(
                _ratio(mx, res.mx),
                mx,
                res.mx,
                st.combination,
                f"{res.mx_note}{tail}; {where}",
                cite("flexure"),
            )
            worst["my"].offer(
                _ratio(my, res.my),
                my,
                res.my,
                st.combination,
                f"the gross section yielding{tail}; {where}",
                cite("flexure"),
            )
            worst["v"].offer(
                _ratio(vy, res.v),
                vy,
                res.v,
                st.combination,
                f"{res.v_note}{tail}; {where}",
                cite("shear"),
            )
            # combined
            if p > 0:
                pr, cap_p = p, res.pc
            else:
                pr, cap_p = -p, res.pt
            if r.interaction == "power":
                e_ = float(r.exponent)
                ratio = (_ratio(pr, cap_p)) ** e_ + (_ratio(mx, res.mx) + _ratio(my, res.my)) ** e_
                how = f"(N/Nb)^{e_:g} + (M/Mb)^{e_:g}"
            elif r.interaction == "amplified" and p > 0 and res.fa and res.fb:
                fa = p / shape.area
                amp = max(1 - fa / res.fe_prime, 1e-6)
                fb = mx / res.mx * res.fb if res.mx > 0 else 0.0
                ratio = fa / res.fa + 0.85 * fb / (amp * res.fb) + _ratio(my, res.my)
                how = "fa/Fa1 + Cm fb / ((1 - fa/F'e) Fb), Cm = 0.85"
            else:
                ratio = _ratio(pr, cap_p) + _ratio(mx, res.mx) + _ratio(my, res.my)
                how = "P/Pa + Mx/Max + My/May"
            worst["i"].offer(
                ratio, ratio, 1.0, st.combination, f"{how}{tail}; {where}", cite("combined")
            )
    rows: list[dict[str, Any]] = []
    if tensioned:
        rows.append(_check("Tension: yielding (gross section)", worst["t"], "kN", 1e3))
    if compressed:
        rows.append(_check("Compression: buckling (cold-formed)", worst["c"], "kN", 1e3))
    rows.append(_check("Flexure about x (major, cold-formed)", worst["mx"], "kN·m", 1e6))
    rows.append(_check("Flexure about y (minor)", worst["my"], "kN·m", 1e6))
    rows.append(_check("Shear along y (web)", worst["v"], "kN", 1e3))
    rows.append(_check("Combined forces (cold-formed)", worst["i"], "", 1.0))
    for part in ("web", "flange", "lip"):
        limit = float(t_.widthRatioMax.get(part, 0.0) or 0.0)
        if limit <= 0:
            continue
        w = _Worst()
        ratio = d[part] / d["t"]
        w.offer(
            ratio / limit,
            ratio,
            limit,
            None,
            f"flat {part} {d[part]:.0f} mm / t {d['t']:g} mm",
            cite("limits"),
        )
        rows.append(_check(f"Cold-formed {part} w/t", w, "", 1.0))
    if t_.distortional.method == "lipAdequacy":
        w = _Worst()
        w.offer(
            0.0 if res.lip_ok else 99.0,
            0.0,
            1.0,
            None,
            f"{res.lip_note}; the flange "
            + ("stiffened" if res.lip_ok else "taken as unstiffened"),
            cite("lip"),
        )
        rows.append(_check("Cold-formed lip as a stiffener", w, "", 1.0, flag=True))
    for c in rows:
        if c["utilisation"] < 0:
            c.update(utilisation=0.0, ok=True, demand=0.0)
    return rows


def method_lines() -> list[str]:
    """The design report's paragraphs (none without the table)."""
    t_ = table()
    if t_ is None:
        return []
    r = t_.resistance
    form = {
        "lrfd": "LRFD (φ Rn)",
        "partialFactors": "partial factors (R / γ)",
        "allowableStress": f"permissible stresses against the working forces (factored / {float(r.loadFactor):g})",
    }[r.format]
    return [
        (
            f"Cold-formed lipped channels and Z sections ({cite('code')}): {form}; effective "
            f"widths by {t_.effectiveWidth.method} ({cite('effectiveWidth')}), distortional "
            f"buckling by the edge stiffener on its elastic spring with {t_.distortional.method} "
            f"({cite('distortional')}); compression by the elastic buckling stress (flexural, "
            "torsional, flexural-torsional) on the effective area, flexure with lateral-torsional "
            f"buckling (Cb = 1), web shear and the {r.interaction} interaction "
            f"({cite('combined')})."
        )
    ]

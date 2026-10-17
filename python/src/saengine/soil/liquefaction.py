"""Liquefaction screening from the SPT: Idriss & Boulanger (2014) or BNBC 2020 Sec 3.9.5.

``design.liquefactionMethod`` picks the triggering procedure.

"idrissBoulanger2014": Boulanger, R. W. & Idriss, I. M. (2014), "CPT and SPT based
liquefaction triggering procedures", Report UCD/CGM-14/01, University of California, Davis: the
SPT form of the procedure (as in Idriss & Boulanger 2008, with the 2014 magnitude scaling
factor):

- ``CSR = 0.65 (σv/σ'v) amax rd``, with
  ``rd = exp(α + β M)``, ``α = -1.012 - 1.126 sin(z/11.73 + 5.133)``,
  ``β = 0.106 + 0.118 sin(z/11.28 + 5.142)``, z in m (for z ≤ 34 m).
- ``(N1)60cs = CN N60 + Δ(N1)60``, the fines correction
  ``Δ(N1)60 = exp(1.63 + 9.7/(FC + 0.01) - (15.7/(FC + 0.01))²)``, and
  ``CN = (pa/σ'v)^m ≤ 1.7``, ``m = 0.784 - 0.0768 √(N1)60cs`` with (N1)60cs ≤ 46,
  solved by iteration.
- ``CRR(M=7.5, σ'v=1 atm) = exp((N1)60cs/14.1 + ((N1)60cs/126)² - ((N1)60cs/23.6)³ +
  ((N1)60cs/25.4)⁴ - 2.8)`` (the deterministic curve, C0 = 2.8).
- ``MSF = 1 + (MSFmax - 1)(8.64 exp(-M/4) - 1.325)``, ``MSFmax = 1.09 + ((N1)60cs/31.5)² ≤
  2.2``.
- ``Kσ = 1 - Cσ ln(σ'v/pa) ≤ 1.1``, ``Cσ = 1/(18.9 - 2.55 √(N1)60cs) ≤ 0.3`` with (N1)60cs ≤
  37.
- ``FS = CRR(M=7.5, σ'v=1) MSF Kσ / CSR``; the test is liquefiable when FS ≤ 1.

"bnbc2020": BNBC 2020 Part 6 Sec 3.9.5:

- ``FL = CRR/CSR`` (Eq 6.3.6), liquefaction "is said to take place" when FL < 1.
- ``τmax = (amax/g) σv rd`` (Eq 6.3.7a) with ``rd = 1 - 0.015 z``, z in m (Eq 6.3.7b), and
  ``CSR = τmax/σ'v = (amax/g) rd σv/σ'v`` (Eq 6.3.8). The code obtains Eq 6.3.8 by "division of
  both sides of Eq. 6.3.7a by the effective vertical stress", so it carries no 0.65 factor:
  it is the peak stress ratio, not Seed & Idriss's equivalent uniform 0.65 τmax. (In the
  extracted text Eq 6.3.8 carries no numeral, while the 0.015 of the adjacent Eq 6.3.7b
  survives; the derivation sentence is the main evidence, and a visual check of the printed
  page would settle it.) The CRR curve below is calibrated against
  0.65 τmax, so the code's CSR is 1/0.65 = 1.54 times that basis: on the safe side.
- CRR "can be obtained by several procedures" and is "most commonly" taken from the SPT; the
  code prescribes none. SAEngine uses the SPT base curve of Youd et al. (2001), "Liquefaction
  resistance of soils: summary report from the 1996 NCEER and 1998 NCEER/NSF workshops",
  J. Geotech. Geoenviron. Eng. 127(10):
  ``(N1)60 = CN N60``, ``CN = (pa/σ'v)^0.5 ≤ 1.7`` (eq. 9); the fines correction
  ``(N1)60cs = α + β (N1)60`` with α = 0, β = 1 for FC ≤ 5 %, ``α = exp(1.76 - 190/FC²)``,
  ``β = 0.99 + FC^1.5/1000`` for 5 < FC < 35 %, α = 5, β = 1.2 for FC ≥ 35 % (eq. 6, 7);
  ``CRR7.5 = 1/(34 - N) + N/135 + 50/(10 N + 45)² - 1/200``, N = (N1)60cs < 30 (eq. 4); clean
  granular soil with (N1)60cs ≥ 30 is "too dense to liquefy"; the magnitude scaling factor of
  Idriss, ``MSF = 10^2.24 / M^2.56``, which the workshop recommends (the lower bound below M
  7.5, the value above it); ``Kσ = (σ'v/pa)^(f - 1) ≤ 1`` with f = 0.7 (the workshop's value
  for relative densities of about 40-60 %). ``FL = CRR7.5 MSF Kσ / CSR``.

BNBC 3.9.5's screening is applied with both methods, as notes and flags of each test:

- "Sandy and silty soils tend to liquefy; clay soils do not undergo liquefaction except the
  sensitive clays": clay, plastic silt (PI ≥ 7, Boulanger & Idriss 2006) and organic soil are
  not screened; the soil report does not record sensitivity, so a note asks to check for
  sensitive clay.
- "As a rule of thumb, any soil that has a SPT value higher than 30 will not liquefy": applied
  to the field N as measured (Sec 3.9.5 does not say which N; the "SPT value" of BNBC's site
  classification, Sec 2.5.3.2, is the field N without correction). With "bnbc2020" a test with
  N > 30 is not liquefiable; with Idriss & Boulanger the computed FS decides and the test is
  flagged.
- Fine-grained soil (silty clay, clayey silt) is susceptible (Finn et al. 1994, as BNBC quotes
  them) when the fraction finer than 0.005 mm ≤ 10 %, LL ≤ 36 %, the natural water content ≤
  0.9 LL and the liquidity index ≤ 0.75. A clay or plastic silt layer whose laboratory data
  give all four and meet them is screened like sand; one that fails any is not susceptible;
  with some data missing the layer stays non-liquefiable and the note says what is missing.

Only saturated soil (below the water table measured in the borehole) within 20 m of the
ground is screened, with both methods (the depth range of the LPI and of the field data
behind both CRR curves; BNBC states none). A layer without a fines content is taken as clean
(FC = 0 %, no fines correction, which errs on the safe side) and silt as FC = 35 %; the result
says so.

Liquefaction potential index (Iwasaki et al. 1978, 1982):
``LPI = ∫₀²⁰ F(z) w(z) dz`` with ``F = 1 - FS`` for FS < 1 (else 0) and ``w = 10 - 0.5 z``;
each test stands for its layer from midway to the test above to midway to the test below (the
deepest test to the bottom of its layer), never below the bottom of the borehole log. LPI
0: very low, up to 5: low, 5-15: high, above 15: very high risk.

Peak ground acceleration amax at the ground surface: ``design.liquefaction.pga`` when given,
else ``(2/3) Z S`` from the project settings. BNBC 3.9.5 says amax "should be taken from
seismic zoning map" and that "the site amplification factor is required to estimate amax for a
given site properly". The zone coefficient Z of the map "represents the maximum considered
peak ground acceleration (PGA) on very stiff soil/rock (site class SA)" (Sec 2.5.4.2, Table
6.2.14); the soil factor S of Table 6.2.16 for the site class amplifies it to the surface.
Sec 2.5.3.1 asks for the liquefaction potential to be "evaluated for design earthquake ground
motions", and Sec 2.5.13.2 gives the "expected horizontal peak ground acceleration (in g) for
design" as ``(2/3) Z S``; that is the default. The alternatives, given in the result: the
maximum considered ``Z S`` (the zero-period value of the elastic spectrum, more severe) and Z
alone (the map's rock value without the amplification 3.9.5 asks for); enter either as
``design.liquefaction.pga`` to use it. The site class is the softest of the project
settings', the boreholes' and, when liquefiable layers make the site S2, SD.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.library import bnbc
from saengine.soil.profile import PA, Profile, SoilLayer

DEPTH_LIMIT = 20.0  # m
FS_CAP = 5.0
#: BNBC 3.9.5's rule of thumb: soil with a higher SPT value does not liquefy.
BNBC_N_LIMIT = 30
#: Youd et al. (2001): clean granular soil with (N1)60cs at least this is too dense to liquefy.
YOUD_N_LIMIT = 30.0
#: Exponent f of Youd et al.'s Kσ = (σ'v/pa)^(f - 1).
YOUD_F = 0.7


# ─────────────────────────────── Idriss & Boulanger (2014) ───────────────────────────────


def rd(z: float, magnitude: float) -> float:
    z = min(z, 34.0)
    alpha = -1.012 - 1.126 * math.sin(z / 11.73 + 5.133)
    beta = 0.106 + 0.118 * math.sin(z / 11.28 + 5.142)
    return math.exp(alpha + beta * magnitude)


def delta_n_fines(fc: float) -> float:
    return math.exp(1.63 + 9.7 / (fc + 0.01) - (15.7 / (fc + 0.01)) ** 2)


def crr_75(n: float) -> float:
    n = min(n, 46.0)
    return math.exp(n / 14.1 + (n / 126) ** 2 - (n / 23.6) ** 3 + (n / 25.4) ** 4 - 2.8)


def msf(magnitude: float, n: float) -> float:
    msf_max = min(2.2, 1.09 + (n / 31.5) ** 2)
    return 1 + (msf_max - 1) * (8.64 * math.exp(-magnitude / 4) - 1.325)


def k_sigma(sigma_eff: float, n: float) -> float:
    c_sigma = min(0.3, 1 / (18.9 - 2.55 * math.sqrt(min(n, 37.0))))
    return min(1.1, 1 - c_sigma * math.log(sigma_eff / PA))


def n160cs(n60: float, sigma_eff: float, fc: float) -> tuple[float, float, float]:
    """((N1)60cs, CN, Δ(N1)60) by iteration on m."""
    dn = delta_n_fines(fc)
    n = n60 + dn
    cn = 1.0
    for _ in range(100):
        m = 0.784 - 0.0768 * math.sqrt(min(max(n, 0.0), 46.0))
        cn = min(1.7, (PA / sigma_eff) ** m)
        new = cn * n60 + dn
        if abs(new - n) < 1e-6:
            n = new
            break
        n = new
    return n, cn, dn


def point(
    z: float, n60: float, sigma_v: float, sigma_eff: float, fc: float, amax: float, mw: float
) -> dict[str, float]:
    """Every quantity of the Idriss & Boulanger procedure at one test."""
    r_d = rd(z, mw)
    csr = 0.65 * sigma_v / sigma_eff * amax * r_d
    n, cn, dn = n160cs(n60, sigma_eff, fc)
    crr = crr_75(n)
    m_sf = msf(mw, n)
    k = k_sigma(sigma_eff, n)
    crr_m = crr * m_sf * k
    return {
        "rd": r_d,
        "csr": csr,
        "CN": cn,
        "N160": cn * n60,
        "dN": dn,
        "N160cs": n,
        "crr75": crr,
        "MSF": m_sf,
        "Ksigma": k,
        "crr": crr_m,
        "fs": min(FS_CAP, crr_m / csr) if csr > 0 else FS_CAP,
    }


# ─────────────────────────────── BNBC 2020 Sec 3.9.5 ───────────────────────────────


def rd_bnbc(z: float) -> float:
    """rd = 1 - 0.015 z, z in m (BNBC 2020 Eq 6.3.7b)."""
    return 1 - 0.015 * z


def youd_fines(fc: float) -> tuple[float, float]:
    """(α, β) of (N1)60cs = α + β (N1)60 (Youd et al. 2001, eq. 6 and 7)."""
    if fc <= 5:
        return 0.0, 1.0
    if fc >= 35:
        return 5.0, 1.2
    return math.exp(1.76 - 190 / fc**2), 0.99 + fc**1.5 / 1000


def crr_youd(n: float) -> float | None:
    """CRR for M 7.5 from (N1)60cs (Youd et al. 2001, eq. 4); None at 30 and above."""
    if n >= YOUD_N_LIMIT:
        return None
    return 1 / (34 - n) + n / 135 + 50 / (10 * n + 45) ** 2 - 1 / 200


def msf_idriss(magnitude: float) -> float:
    """MSF = 10^2.24 / M^2.56 (Idriss, as Youd et al. 2001 recommend)."""
    return 10**2.24 / magnitude**2.56


def k_sigma_youd(sigma_eff: float, f: float = YOUD_F) -> float:
    """Kσ = (σ'v/pa)^(f - 1), at most 1 (Youd et al. 2001)."""
    return min(1.0, (sigma_eff / PA) ** (f - 1))


def point_bnbc(
    z: float, n60: float, sigma_v: float, sigma_eff: float, fc: float, amax: float, mw: float
) -> dict[str, float | None]:
    """Every quantity of BNBC 3.9.5 with the CRR of Youd et al. (2001) at one test."""
    r_d = rd_bnbc(z)
    csr = amax * r_d * sigma_v / sigma_eff
    cn = min(1.7, math.sqrt(PA / sigma_eff))
    n160 = cn * n60
    alpha, beta = youd_fines(fc)
    n = alpha + beta * n160
    crr = crr_youd(n)
    m_sf = msf_idriss(mw)
    k = k_sigma_youd(sigma_eff)
    crr_m = None if crr is None else crr * m_sf * k
    fs = FS_CAP if crr_m is None or csr <= 0 else min(FS_CAP, crr_m / csr)
    return {
        "rd": r_d,
        "csr": csr,
        "CN": cn,
        "N160": n160,
        "alpha": alpha,
        "beta": beta,
        "N160cs": n,
        "crr75": crr,
        "MSF": m_sf,
        "Ksigma": k,
        "crr": crr_m,
        "fs": fs,
    }


# ─────────────────────────────── amax ───────────────────────────────


def amax_from(
    pga: float | None, z: float | None, site_classes: list[str]
) -> tuple[float | None, str]:
    """amax [g] and how it was found."""
    if pga is not None:
        return pga, f"amax = {pga:g} g (soil report)"
    if z is None:
        return None, "no amax: give the PGA or the seismic zone in the project settings"
    classes = [c for c in site_classes if c in bnbc.SITE_FACTORS]
    if not classes:
        classes = ["SD"]
    cls = max(classes, key=lambda c: bnbc.SITE_FACTORS[c].s)
    s = bnbc.SITE_FACTORS[cls].s
    value = 2 / 3 * z * s
    return value, (
        f"amax = (2/3) Z S = (2/3) × {z:g} × {s:g} = {value:.3f} g, the design earthquake's "
        "PGA (BNBC 2020 Sec 2.5.13.2; Sec 2.5.3.1 asks for liquefaction under design "
        f"earthquake ground motions) (Z = {z:g}, seismic zoning map: the maximum considered PGA "
        f"on rock, Sec 2.5.4.2 and Table 6.2.14; site amplification S = {s:g} of Table 6.2.16 "
        f"for site class {cls} applied, as Sec 3.9.5 asks; the maximum considered Z S would be "
        f"{z * s:.3f} g, Z alone {z:g} g)"
    )


def lpi_category(lpi: float) -> str:
    if lpi <= 0:
        return "very low"
    if lpi <= 5:
        return "low"
    if lpi <= 15:
        return "high"
    return "very high"


def _w_integral(a: float, b: float) -> float:
    """∫ (10 - 0.5 z) dz from a to b."""
    return 10 * (b - a) - 0.25 * (b * b - a * a)


# ─────────────────────────────── screening ───────────────────────────────


def finn(layer: SoilLayer) -> tuple[bool | None, str]:
    """Finn et al. (1994) susceptibility of fine-grained soil, as BNBC 3.9.5 quotes it:
    True / False when the data decide it, None when some are missing; and the reason."""
    ll, w, pl = layer.ll, layer.w, layer.pl
    li = None
    if w is not None and pl is not None and ll is not None and ll > pl:
        li = (w - pl) / (ll - pl)
    failed: list[str] = []
    missing: list[str] = []
    if layer.clay_fraction is None:
        missing.append("fraction finer than 0.005 mm")
    elif layer.clay_fraction > 10:
        failed.append(f"fraction finer than 0.005 mm {layer.clay_fraction:.0f} % > 10 %")
    if ll is None:
        missing.append("LL")
    elif ll > 36:
        failed.append(f"LL {ll:.0f} % > 36 %")
    if w is None or ll is None:
        missing.append("natural water content" if w is None else "w/LL (no LL)")
    elif w > 0.9 * ll:
        failed.append(f"w {w:.0f} % > 0.9 LL = {0.9 * ll:.0f} %")
    if li is None:
        missing.append("liquidity index (w, LL and PL)")
    elif li > 0.75:
        failed.append(f"liquidity index {li:.2f} > 0.75")
    if failed:
        return False, "not susceptible by Finn et al. 1994 (" + ", ".join(failed) + ")"
    if missing:
        return None, "Finn et al. 1994 criteria not checked: no " + ", ".join(missing)
    return True, "susceptible by Finn et al. 1994 (all four criteria met)"


def susceptible(layer: SoilLayer | None) -> tuple[bool, str | None]:
    """Whether the layer is screened, and the reason it is not."""
    if layer is None:
        return False, "no layer: not screened"
    if layer.behaviour == "granular":
        return True, None
    if layer.behaviour == "rock":
        return False, "rock: not susceptible"
    if layer.soil_type == "organic":
        return False, "organic: not susceptible (clay-like)"
    verdict, why = finn(layer)
    if verdict:
        return True, None
    base = (
        f"{layer.soil_type}: non-liquefiable (clay-like; BNBC 3.9.5: clays do not liquefy "
        "except sensitive clays)"
    )
    return False, f"{base}; {why}"


def fines_of(layer: SoilLayer) -> tuple[float, str | None]:
    if layer.fines is not None:
        return layer.fines, None
    if layer.soil_type == "silt":
        return 35.0, "FC = 35 % assumed for silt"
    return 0.0, "FC = 0 % assumed (no fines content)"


def screen(profile: Profile, amax: float | None, amax_note: str) -> dict[str, Any]:
    """FS per SPT test, the liquefiable layers and the LPI of the borehole."""
    method = profile.design.liquefactionMethod
    bnbc_method = method == "bnbc2020"
    mw = profile.design.liquefaction.magnitude
    notes = [amax_note]
    if amax is None:
        return {
            "points": [],
            "lpi": None,
            "category": None,
            "layers": [],
            "note": amax_note,
            "method": method,
            "notes": notes,
        }
    if profile.water_table is None:
        notes.append("no water table in the borehole: nothing is saturated, nothing screened")
    assumed: set[str] = set()
    flagged: list[str] = []
    points: list[dict[str, Any]] = []
    tests = profile.spt
    lpi = 0.0
    liquefiable_layers: set[int] = set()
    clay_seen = False
    for i, test in enumerate(tests):
        layer = test.layer
        record: dict[str, Any] = {
            "depth": round(test.depth * 1e3),
            "N": test.n,
            "N60": round(test.n60, 1),
        }
        flags: list[str] = []
        dense = test.n > BNBC_N_LIMIT
        if dense:
            flags.append(
                f"field N = {test.n} > {BNBC_N_LIMIT}: does not liquefy by BNBC 3.9.5's rule "
                "of thumb"
            )
        ok, why_not = susceptible(layer)
        if layer is not None and layer.behaviour == "cohesive":
            clay_seen = True
            if ok:  # fine-grained soil the Finn et al. criteria make susceptible
                flags.append(f"layer {layer.index + 1} ({layer.soil_type}): {finn(layer)[1]}")
        reason: str | None = None
        if not profile.below_water(test.depth):
            reason = "above the water table"
        elif test.depth > DEPTH_LIMIT:
            reason = "deeper than 20 m"
        elif not ok:
            reason = why_not
        elif bnbc_method and dense:
            reason = flags[0]
        if reason is not None:
            points.append(
                {
                    **record,
                    "screened": False,
                    "reason": reason,
                    "liquefiable": False,
                    "flags": flags,
                }
            )
            continue
        assert layer is not None
        fc, note = fines_of(layer)
        if note:
            assumed.add(f"layer {layer.index + 1}: {note}")
        args = (test.depth, test.n60, test.sigma_v, test.sigma_v_eff, fc, amax, mw)
        values: dict[str, Any] = point_bnbc(*args) if bnbc_method else point(*args)
        fs = values["fs"]
        # BNBC 2020 Sec 3.9.5: "If the factor of safety FL is ≤ 1, liquefaction is said to take
        # place"; the same boundary for both methods.
        liquefiable = fs <= 1.0
        if bnbc_method and values["crr"] is None:
            flags.append("(N1)60cs ≥ 30: too dense to liquefy (Youd et al. 2001)")
        if liquefiable and dense:
            flagged.append(
                f"{test.depth:.1f} m: FS = {fs:.2f} although the field N = {test.n} > 30, which "
                "BNBC 3.9.5's rule of thumb takes as non-liquefiable: check"
            )
        # The test's share of its layer for the LPI: never below the layer, the bottom of the
        # log or 20 m (the deepest test stands for the rest of its layer only).
        top = 0.0 if i == 0 else (tests[i - 1].depth + test.depth) / 2
        bottom = layer.bottom if i == len(tests) - 1 else (test.depth + tests[i + 1].depth) / 2
        top = max(top, layer.top, profile.water_table or 0.0)
        bottom = min(bottom, layer.bottom, profile.bottom, DEPTH_LIMIT)
        if fs < 1.0 and bottom > top:
            lpi += (1 - fs) * _w_integral(top, bottom)
        if liquefiable:
            liquefiable_layers.add(layer.index)

        def r(key: str, digits: int = 3, values: dict[str, Any] = values) -> float | None:
            value = values.get(key)
            return None if value is None else round(value, digits)

        points.append(
            {
                **record,
                "screened": True,
                "sigma_v": round(test.sigma_v, 1),
                "sigma_v_eff": round(test.sigma_v_eff, 1),
                "finesContent": fc,
                "rd": r("rd"),
                "csr": r("csr"),
                "N160": r("N160", 1),
                "N160cs": r("N160cs", 1),
                "MSF": r("MSF"),
                "Ksigma": r("Ksigma"),
                "crr": r("crr"),
                "fs": round(fs, 2),
                "liquefiable": liquefiable,
                "flags": flags,
            }
        )
    notes += sorted(assumed)
    notes.append(
        "BNBC 2020 Sec 3.9.5 screening: sandy and silty soils are screened; clays do not "
        "liquefy except sensitive clays"
        + (
            " (the soil report does not record sensitivity: check for sensitive clay)"
            if clay_seen
            else ""
        )
        + "; field N > 30 does not liquefy (the code's rule of thumb"
        + (", applied" if bnbc_method else ", flagged; the computed FS decides")
        + "); fine-grained soil by Finn et al. 1994 where the laboratory data exist."
    )
    notes += flagged
    layers = [
        {
            "layer": index,
            "top": round(profile.layers[index].top * 1e3),
            "bottom": round(profile.layers[index].bottom * 1e3),
            "soilType": profile.layers[index].soil_type,
        }
        for index in sorted(liquefiable_layers)
    ]
    category = lpi_category(lpi)
    limit = "FS < 1" if bnbc_method else "FS ≤ 1"
    summary = (
        f"{len(layers)} liquefiable layer(s) ({limit}); LPI = {lpi:.1f} ({category} risk, "
        "Iwasaki 1982)"
        if layers
        else f"No liquefiable test; LPI = {lpi:.1f}"
    )
    return {
        "amax": amax,
        "magnitude": mw,
        "method": method,
        "points": points,
        "layers": layers,
        "lpi": round(lpi, 2),
        "category": category,
        "note": summary + ". " + amax_note + ".",
        "notes": notes,
    }


METHODS = {
    "idrissBoulanger2014": (
        "Idriss & Boulanger (2014) SPT procedure: CSR = 0.65 (σv/σ'v) amax rd; (N1)60cs with "
        "the fines correction and the iterative CN; CRR for M 7.5 and 1 atm with MSF and Kσ; "
        "FS = CRR/CSR, liquefiable when FS ≤ 1; BNBC 2020 Sec 3.9.5 screening (clays, field N "
        "> 30, Finn et al. 1994) as flags; LPI of Iwasaki et al. (1982) over the top 20 m."
    ),
    "bnbc2020": (
        "BNBC 2020 Part 6 Sec 3.9.5: FL = CRR/CSR (Eq 6.3.6), liquefaction when FL < 1; CSR = "
        "(amax/g) rd σv/σ'v (Eq 6.3.8, no 0.65 factor in the code), rd = 1 - 0.015 z (Eq "
        "6.3.7b). CRR: Youd et al. 2001, permitted by BNBC 3.9.5 'several procedures': "
        "(N1)60 = (pa/σ'v)^0.5 N60 ≤ 1.7 N60, the fines correction α + β (N1)60, CRR7.5 of "
        "the SPT base curve ((N1)60cs ≥ 30 too dense to liquefy), MSF = 10^2.24/M^2.56 "
        "(Idriss), Kσ = (σ'v/pa)^(0.7 - 1) ≤ 1. Screening of 3.9.5: clays do not liquefy "
        "except sensitive clays; field N > 30 does not liquefy; Finn et al. 1994 for "
        "fine-grained soil. LPI of Iwasaki et al. (1982) over the top 20 m."
    ),
}

#: The default method's text (kept for the callers that name it without the design options).
METHOD = METHODS["idrissBoulanger2014"]

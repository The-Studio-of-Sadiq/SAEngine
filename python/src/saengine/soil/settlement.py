"""Settlement of a spread footing at a borehole: immediate plus consolidation.

A footing B × L [m] founded Df [m] below the borehole's ground, under a net pressure q [kPa]
(the gross pressure minus the overburden). The layers below the base settle by:

- Granular layers, immediately: the strain influence factor method of Schmertmann, Hartman &
  Brown (1978), "Improved strain influence factor diagrams", J. Geotech. Eng. Div. 104(GT8):

  ``s = C1 C2 q Σ (Iz / Es) Δz``, ``C1 = 1 - 0.5 σ'v0/q ≥ 0.5``,
  ``C2 = 1 + 0.2 log10(t / 0.1 yr)``.

  Iz rises from 0.1 at the base to ``Izp = 0.5 + 0.1 (q/σ'vp)^0.5`` at B/2 and falls to 0 at
  2B for a square footing (L/B = 1); from 0.2 to Izp at B and to 0 at 4B for a strip (L/B ≥
  10); in between, the depths and the base value are interpolated in L/B, as Schmertmann et
  al. recommend. σ'vp is σ'v0 at the depth of Izp. Es is the layer's E, or the SPT-derived
  modulus of :mod:`saengine.soil.profile` (Kulhawy & Mayne 1990).
- Cohesive layers, immediately (undrained, ν = 0.5): elastic settlement of the centre of a
  flexible rectangle with Steinbrenner's (1934) influence factors (as given in Bowles 1996,
  Foundation Analysis and Design, ch. 5), each layer between depths z1 and z2 below the base as the difference of two layers
  from the base: ``s = 4 q B' (1 - ν²)/Eu [I1(z2) - I1(z1)]``, B' = B/2, without the depth
  (embedment) reduction factor, which errs on the safe side.
- Cohesive layers with a compression index, by primary consolidation (Terzaghi's 1D theory):
  slices of at most 0.25 m, the stress increase by the 2:1 spread ``Δσ = q B L / ((B + z)(L +
  z))``, ``σ'p = OCR σ'v0`` and

  - normally consolidated: ``s = Cc H/(1 + e0) log10((σ'v0 + Δσ)/σ'v0)``,
  - overconsolidated, ``σ'v0 + Δσ ≤ σ'p``: ``s = Cr H/(1 + e0) log10((σ'v0 + Δσ)/σ'v0)``,
  - overconsolidated, beyond σ'p: ``s = Cr H/(1 + e0) log10(σ'p/σ'v0) + Cc H/(1 + e0)
    log10((σ'v0 + Δσ)/σ'p)``.

Below the base the consolidation and the elastic settlement of clay are summed down to the
depth where the 2:1 stress increase drops to 10 % of σ'v0 (the usual limit of the significant
zone), or to the bottom of the log, whichever is less; the result says when the log ends
first. Rock does not settle.

The computed settlement is shown next to the permissible total settlement of BNBC 2020 Part 6
Table 6.3.8 (adapted there from the National Building Code of India 2005), for information:
the allowable bearing pressure keeps its own criterion, ``design.allowableSettlement``. The
table's rows used are "RCC structures" and "Multistoried building, (a) RCC or steel framed
building with panel walls"; its columns isolated foundations / raft and "sand and hard clay" /
"plastic clay":

==========================  =================  ==============  ================  =============
Maximum settlement [mm]     Isolated, sand     Isolated,       Raft, sand and    Raft, plastic
                            and hard clay      plastic clay    hard clay         clay
==========================  =================  ==============  ================  =============
RCC structures              50                 75              75                100
Multistoried, RCC framed    60                 75              75                125
==========================  =================  ==============  ================  =============

The table's note says its values "may be taken only as a guide". Plastic clay is taken to be a
cohesive layer (clay, plastic silt, organic soil) within the stressed zone whose undrained
strength is below 200 kPa or unknown (the hard clay of Terzaghi & Peck's consistency scale is
above 200 kPa); otherwise the column is "sand and hard clay".

Units: m and kPa inside; settlements in mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.soil.profile import Profile, SoilLayer

SLICE = 0.05  # m, Schmertmann integration
CONSOLIDATION_SLICE = 0.25  # m
NU_UNDRAINED = 0.5

#: BNBC 2020 Table 6.3.8, maximum settlement [mm]: (foundation, soil) -> (RCC structures,
#: multistoried RCC or steel framed building with panel walls).
PERMISSIBLE: dict[tuple[str, str], tuple[float, float]] = {
    ("isolated", "sand"): (50.0, 60.0),
    ("isolated", "plasticClay"): (75.0, 75.0),
    ("raft", "sand"): (75.0, 75.0),
    ("raft", "plasticClay"): (100.0, 125.0),
}
SOIL_COLUMNS = {"sand": "sand and hard clay", "plasticClay": "plastic clay"}
#: Undrained strength above which a clay counts as hard [kPa].
HARD_CLAY_CU = 200.0


def permissible(foundation: str, soil: str) -> dict[str, Any]:
    """BNBC 2020 Table 6.3.8's maximum settlement for a foundation type and a soil column."""
    rcc, framed = PERMISSIBLE[(foundation, soil)]
    kind = "isolated foundation" if foundation == "isolated" else "raft foundation"
    return {
        "value": rcc,
        "framedBuilding": framed,
        "foundation": foundation,
        "soil": soil,
        "source": (
            f"BNBC 2020 Table 6.3.8, {kind} on {SOIL_COLUMNS[soil]}: {rcc:g} mm for RCC "
            f"structures ({framed:g} mm for a multistoried RCC framed building with panel "
            "walls); a guide, for information"
        ),
    }


def permissible_text(foundation: str) -> str:
    """Both soil columns of Table 6.3.8 for a foundation type, in one line."""
    sand, clay = PERMISSIBLE[(foundation, "sand")], PERMISSIBLE[(foundation, "plasticClay")]
    kind = "isolated foundations" if foundation == "isolated" else "rafts"
    return (
        f"BNBC 2020 Table 6.3.8 permits {sand[0]:g} mm on sand and hard clay and {clay[0]:g} mm "
        f"on plastic clay for {kind} of RCC structures ({sand[1]:g} / {clay[1]:g} mm for a "
        "multistoried framed building with panel walls), shown next to the computed settlement "
        "for information"
    )


def soil_column(profile: Profile, df: float, depth: float) -> str:
    """'plasticClay' when a soft-to-stiff cohesive layer is within the stressed zone."""
    for layer in profile.layers:
        last = layer is profile.layers[-1]
        if layer.bottom <= df and not last:
            continue
        if layer.top >= df + depth and depth > 0:
            break
        if layer.behaviour == "cohesive" and (layer.cu is None or layer.cu < HARD_CLAY_CU):
            return "plasticClay"
    return "sand"


def stress_increase(q: float, b: float, l_: float, z: float) -> float:
    """2:1 stress increase under the centre at depth ``z`` below the base [kPa]."""
    return q * b * l_ / ((b + z) * (l_ + z))


def influence_depth(profile: Profile, b: float, l_: float, df: float, q: float) -> float:
    """Depth below the base where Δσ falls to 10 % of σ'v0 [m], at most the log's bottom."""
    limit = max(profile.bottom - df, 0.0)
    z = 0.0
    while z < limit:
        if stress_increase(q, b, l_, z) <= 0.1 * max(profile.sigma_v_eff(df + z), 1e-6):
            return z
        z += 0.1
    return limit


def steinbrenner_i1(m: float, n: float) -> float:
    """Steinbrenner's I1 for the corner of a B' × M B' rectangle over a layer N B' thick."""
    if n <= 0:
        return 0.0
    a = math.sqrt(m * m + 1)
    b = math.sqrt(m * m + n * n)
    c = math.sqrt(m * m + n * n + 1)
    return (
        m * math.log((1 + a) * b / (m * (1 + c)))
        + math.log((m + a) * math.sqrt(1 + n * n) / (m + c))
    ) / math.pi


def steinbrenner_i2(m: float, n: float) -> float:
    if n <= 0:
        return 0.0
    return n / (2 * math.pi) * math.atan(m / (n * math.sqrt(m * m + n * n + 1)))


def strain_influence(b: float, l_: float, q: float, sigma_p: float) -> dict[str, float]:
    """Schmertmann (1978) diagram: base value, depth of the peak, peak, depth of zero [m]."""
    t = (min(max(l_ / b, 1.0), 10.0) - 1) / 9
    izp = 0.5 + 0.1 * math.sqrt(q / max(sigma_p, 1e-6))
    return {"iz0": 0.1 + 0.1 * t, "zp": (0.5 + 0.5 * t) * b, "izp": izp, "zmax": (2 + 2 * t) * b}


def iz_at(z: float, d: dict[str, float]) -> float:
    if z <= d["zp"]:
        return d["iz0"] + (d["izp"] - d["iz0"]) * z / d["zp"]
    if z <= d["zmax"]:
        return d["izp"] * (d["zmax"] - z) / (d["zmax"] - d["zp"])
    return 0.0


def _row(layer: SoilLayer, z1: float, z2: float) -> dict[str, Any]:
    return {
        "layer": layer.index,
        "soilType": layer.soil_type,
        "top": round(z1 * 1e3),
        "bottom": round(z2 * 1e3),
        "immediate": 0.0,
        "consolidation": 0.0,
        "method": [],
    }


def settlement(
    profile: Profile,
    b: float,
    l_: float,
    df: float,
    q: float,
    years: float | None = None,
    foundation: str = "isolated",
) -> dict[str, Any]:
    """Settlement [mm] of a footing B × L [m] at Df [m] under a net pressure q [kPa], with
    BNBC Table 6.3.8's permissible value for the ``foundation`` ("isolated" or "raft")."""
    b, l_ = min(b, l_), max(b, l_)
    years = profile.design.creepYears if years is None else years
    notes: list[str] = []
    rows: dict[int, dict[str, Any]] = {}
    if q <= 0:
        return {
            "immediate": 0.0,
            "consolidation": 0.0,
            "total": 0.0,
            "layers": [],
            "notes": [],
            "permissible": permissible(foundation, soil_column(profile, df, b)),
        }
    s0 = max(profile.sigma_v_eff(df), 0.0)
    depth = influence_depth(profile, b, l_, df, q)
    if depth >= profile.bottom - df - 1e-9:
        notes.append(
            f"the stressed zone reaches the bottom of the log ({profile.bottom:.1f} m): "
            "deeper soil is not included"
        )

    # Granular layers: Schmertmann et al. (1978).
    sigma_p = profile.sigma_v_eff(df + strain_influence(b, l_, q, 1.0)["zp"])
    diagram = strain_influence(b, l_, q, sigma_p)
    c1 = max(0.5, 1 - 0.5 * s0 / q)
    c2 = 1 + 0.2 * math.log10(max(years, 0.1) / 0.1)
    immediate = 0.0
    zmax = min(diagram["zmax"], max(profile.bottom - df, 0.0))
    steps = max(1, math.ceil(zmax / SLICE))
    missing: set[int] = set()
    for i in range(steps):
        z1, z2 = i * zmax / steps, (i + 1) * zmax / steps
        layer = profile.layer_at(df + (z1 + z2) / 2)
        if layer is None or layer.behaviour != "granular":
            continue
        if not layer.E:
            missing.add(layer.index)
            continue
        ds = c1 * c2 * q * iz_at((z1 + z2) / 2, diagram) / (layer.E * 1e3) * (z2 - z1) * 1e3
        immediate += ds
        row = rows.setdefault(layer.index, _row(layer, df + z1, df + z2))
        row["bottom"] = round((df + z2) * 1e3)
        row["immediate"] += ds
        if "Schmertmann 1978" not in row["method"]:
            row["method"].append("Schmertmann 1978")
    for index in sorted(missing):
        notes.append(f"layer {index + 1}: no modulus (E or SPT), its settlement is left out")

    # Cohesive layers: elastic (Steinbrenner) and consolidation.
    consolidation = 0.0
    half = b / 2
    m = l_ / b
    for layer in profile.layers:
        last = layer is profile.layers[-1]
        top = max(layer.top, df)
        bottom = min(layer.bottom if not last else math.inf, df + depth)
        if layer.behaviour != "cohesive" or bottom <= top + 1e-9:
            continue
        row = rows.setdefault(layer.index, _row(layer, top, bottom))
        row["top"], row["bottom"] = round(top * 1e3), round(bottom * 1e3)
        if layer.E:
            factor = 4 * q * half * (1 - NU_UNDRAINED**2) / (layer.E * 1e3)
            i_top = steinbrenner_i1(m, (top - df) / half)
            i_bottom = steinbrenner_i1(m, (bottom - df) / half)
            ds = factor * (i_bottom - i_top) * 1e3
            immediate += ds
            row["immediate"] += ds
            row["method"].append("elastic, Steinbrenner")
        else:
            notes.append(f"layer {layer.index + 1}: no undrained modulus, no immediate settlement")
        if layer.cc is None or layer.e0 is None:
            notes.append(
                f"layer {layer.index + 1} ({layer.soil_type}): no Cc and e0 (or LL and moisture), "
                "consolidation not computed"
            )
            continue
        n = max(1, math.ceil((bottom - top) / CONSOLIDATION_SLICE))
        h = (bottom - top) / n
        for k in range(n):
            z = top + (k + 0.5) * h
            s_0 = max(profile.sigma_v_eff(z), 1e-6)
            ds_ = stress_increase(q, b, l_, z - df)
            s_p = layer.ocr * s_0
            s_1 = s_0 + ds_
            cr = layer.cr if layer.cr is not None else layer.cc / 5
            if s_1 <= s_p:
                strain = cr * math.log10(s_1 / s_0)
            else:
                strain = cr * math.log10(s_p / s_0) + layer.cc * math.log10(s_1 / s_p)
            ds = strain * h / (1 + layer.e0) * 1e3
            consolidation += ds
            row["consolidation"] += ds
        row["method"].append("1D consolidation, 2:1")
    layers = sorted(rows.values(), key=lambda r: r["top"])
    for row in layers:
        row["immediate"] = round(row["immediate"], 2)
        row["consolidation"] = round(row["consolidation"], 2)
        row["total"] = round(row["immediate"] + row["consolidation"], 2)
        row["method"] = ", ".join(row["method"])
    return {
        "B": round(b * 1e3),
        "L": round(l_ * 1e3),
        "Df": round(df * 1e3),
        "q": round(q, 1),
        "immediate": immediate,
        "consolidation": consolidation,
        "total": immediate + consolidation,
        "C1": c1,
        "C2": c2,
        "Izp": diagram["izp"],
        "depth": round(depth * 1e3),
        "layers": layers,
        "notes": notes,
        "allowable": profile.design.allowableSettlement,
        "permissible": permissible(foundation, soil_column(profile, df, depth)),
    }


def rounded(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    for key in ("immediate", "consolidation", "total"):
        out[key] = round(out[key], 1)
    for key in ("C1", "C2", "Izp"):
        if key in out:
            out[key] = round(out[key], 3)
    return out

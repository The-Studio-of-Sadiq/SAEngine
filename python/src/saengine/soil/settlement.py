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
- Soft and medium stiff cohesive layers (cu below the code pack's ``piles.soilClasses.stiffCu``)
  without Cc and e0 (no consolidation test, no LL and moisture), by an estimate (a stiff clay
  takes its elastic settlement only, as its consolidation is small). With SPTs in the layer
  (walk 4 W4B-10): ``s = Σ mv Δσ h`` with ``mv = 1/(f2 N60)`` (Stroud & Butler 1975,
  :data:`STROUD_F2`). Without: the modulus number method (Janbu) with the code pack's lower M of the layer's row
  (``foundations.piles.settlement.modulus``; the default pack's Table 6.3.14, the same method
  the long-term settlement of a pile group uses), the same 0.25 m slices and 2:1 spread:
  ``j = 0``: ``ε = ln(σ1'/σ0')/M``; ``j > 0``: ``ε = [(σ1'/σr)^j - (σ0'/σr)^j]/(M j)``, for a
  clay the larger of both. The result names the estimated layers (``estimated``) and a note
  says so. Without a modulus number in the pack the consolidation is not computed
  (``unknownConsolidation``) and :mod:`saengine.soil.bearing` gives no settlement-controlled
  qa, rather than a qa that leaves the clay's consolidation out.

Below the base the consolidation and the elastic settlement of clay are summed down to the
depth where the 2:1 stress increase drops to 10 % of σ'v0 (the usual limit of the significant
zone), or to the bottom of the log, whichever is less; the result says when the log ends
first. Rock does not settle.

- Cohesive layers with a secondary compression index Cα, by secondary consolidation (the usual
  form, e.g. Mesri 1973): ``s = Cα / (1 + e0) H log10(t / tp)`` over the stressed thickness H,
  tp the end of the primary consolidation and t the time of the design (``design.primaryYears``
  and ``design.secondaryYears``), added to the total.

The computed settlement is shown next to the permissible total settlement of the code pack in
force (``foundations.shallow.settlementLimits``, its rows "rcc" and "framed": the default
pack's Table 6.3.8, a guide), for information: the allowable bearing pressure keeps its own
criterion, ``design.allowableSettlement``. Plastic clay is taken to be a
cohesive layer (clay, plastic silt, organic soil) within the stressed zone whose undrained
strength is below 200 kPa or unknown (the hard clay of Terzaghi & Peck's consistency scale is
above 200 kPa); otherwise the column is "sand and hard clay".

Units: m and kPa inside; settlements in mm.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.soil.profile import Profile, SoilLayer

SLICE = 0.05  # m, Schmertmann integration
CONSOLIDATION_SLICE = 0.25  # m
NU_UNDRAINED = 0.5

SOIL_COLUMNS = {"sand": "sand and hard clay", "plasticClay": "plastic clay"}
#: Undrained strength above which a clay counts as hard [kPa].
HARD_CLAY_CU = 200.0
#: The rows of the code pack's permissible settlements shown with a computed settlement: the
#: structure and the multistoried framed building.
SHOWN_ROWS = ("rcc", "framed")


def _limits() -> tuple[Any, str] | None:
    """The code pack's permissible settlement rows (``foundations.shallow.settlementLimits``)
    by id, and their clause; None when the pack has none."""
    from saengine.codes import context as code_context

    try:
        table = code_context.table("foundations")
    except Exception:  # noqa: BLE001 - a pack without the table gives no limits
        return None
    shallow = getattr(table, "shallow", None)
    if shallow is None:
        return None
    rows = {r.id: r for r in shallow.settlementLimits}
    return rows, table.sources.get("shallow.settlementLimits", "")


def _rigidity() -> float | None:
    """C12: the pack's ``foundations.shallow.settlementRigidity`` (None: not reduced)."""
    from saengine.codes import context as code_context

    try:
        table = code_context.table("foundations")
    except Exception:  # noqa: BLE001 - a pack without the table: no correction
        return None
    found = getattr(getattr(table, "shallow", None), "settlementRigidity", None)
    return float(found) if found is not None else None


def _rigidity_clause() -> str:
    from saengine.codes import context as code_context

    try:
        found = code_context.table("foundations").sources.get("shallow.settlementRigidity", "")
        return found.split(": ", 1)[0]
    except Exception:  # noqa: BLE001
        return ""


def permissible(foundation: str, soil: str) -> dict[str, Any] | None:
    """The code pack's maximum settlement for a foundation type ("isolated" or "raft") and a
    soil column, for RCC structures (``value``) and for a multistoried framed building with
    panel walls (``framedBuilding``); None when the pack gives none."""
    found = _limits()
    if found is None:
        return None
    rows, clause = found
    values = []
    for row_id in SHOWN_ROWS:
        row = rows.get(row_id)
        limit = getattr(row, foundation).get(soil) if row is not None else None
        values.append(None if limit is None else limit.total)
    if values[0] is None:
        return None
    rcc, framed = values[0], values[1] if values[1] is not None else values[0]
    kind = "isolated foundation" if foundation == "isolated" else "raft foundation"
    return {
        "value": rcc,
        "framedBuilding": framed,
        "foundation": foundation,
        "soil": soil,
        "source": (
            f"{clause}, {kind} on {SOIL_COLUMNS[soil]}: {rcc:g} mm for RCC structures "
            f"({framed:g} mm for a multistoried RCC framed building with panel walls); a guide, "
            "for information"
        ),
    }


def permissible_text(foundation: str) -> str:
    """Both soil columns of the pack's permissible settlement for a foundation type, in one
    line (empty when the pack gives none)."""
    sand, clay = permissible(foundation, "sand"), permissible(foundation, "plasticClay")
    if sand is None or clay is None:
        return "no permissible settlement in the code pack"
    found = _limits()
    clause = found[1] if found is not None else ""
    kind = "isolated foundations" if foundation == "isolated" else "rafts"
    return (
        f"the code pack permits {sand['value']:g} mm on sand and hard clay and "
        f"{clay['value']:g} mm on plastic clay for {kind} of RCC structures "
        f"({sand['framedBuilding']:g} / {clay['framedBuilding']:g} mm for a multistoried framed "
        f"building with panel walls), shown next to the computed settlement for information "
        f"({clause})"
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
    the code pack's permissible value for the ``foundation`` ("isolated" or "raft")."""
    b, l_ = min(b, l_), max(b, l_)
    years = profile.design.creepYears if years is None else years
    notes: list[str] = []
    rows: dict[int, dict[str, Any]] = {}
    if q <= 0:
        return {
            "immediate": 0.0,
            "consolidation": 0.0,
            "secondary": 0.0,
            "total": 0.0,
            "layers": [],
            "notes": [],
            "consolidated": [],
            "estimated": [],
            "unknownConsolidation": [],
            "permissible": permissible(foundation, soil_column(profile, df, b)),
        }
    from saengine.soil import characteristic_bearing

    if characteristic_bearing.settlement_rule() is not None:
        # Alpha 9 C20b: the pack's layer-wise summation with ψs (GB 50007 5.3.5 type).
        return characteristic_bearing.layerwise_settlement(
            profile, b, l_, df, q, permissible(foundation, soil_column(profile, df, b))
        )
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
    secondary = 0.0
    years_primary = getattr(profile.design, "primaryYears", 1.0)
    years_secondary = getattr(profile.design, "secondaryYears", 0.0)
    half = b / 2
    m = l_ / b
    #: Cohesive layers whose consolidation is computed (with Cc and e0, or estimated), the
    #: estimated ones, and those whose consolidation cannot be computed.
    consolidated: list[int] = []
    estimated: list[int] = []
    unknown: list[int] = []
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
            rigid = _rigidity() if foundation == "isolated" else None
            if rigid is not None:  # C12: the pack's rigidity correction of a rigid footing
                ds *= rigid
            immediate += ds
            row["immediate"] += ds
            row["method"].append(
                "elastic, Steinbrenner"
                + (f", × {rigid:g} rigid footing ({_rigidity_clause()})" if rigid else "")
            )
        else:
            notes.append(f"layer {layer.index + 1}: no undrained modulus, no immediate settlement")
        if layer.calpha and layer.e0 is not None and years_secondary > years_primary:
            # Secondary compression of the stressed clay (Sec 3.9.4.5 asks for it; the usual
            # Cα form, e.g. Mesri 1973): Cα / (1 + e0) H log10(t / tp).
            ds = (
                layer.calpha
                / (1 + layer.e0)
                * (bottom - top)
                * math.log10(years_secondary / years_primary)
                * 1e3
            )
            secondary += ds
            row["secondary"] = row.get("secondary", 0.0) + ds
            row["method"].append(f"secondary, Cα log(t/tp), t = {years_secondary:g} years")
        if layer.cc is None or layer.e0 is None:
            if is_stiff(layer) and layer.E:
                # A stiff clay: its consolidation is small next to its elastic settlement.
                notes.append(
                    f"layer {layer.index + 1} ({layer.soil_type}): stiff clay without Cc and e0 "
                    "(or LL and moisture): its elastic settlement only, consolidation not "
                    "computed"
                )
                continue
            ds = _estimated_consolidation(profile, layer, top, bottom, df, q, b, l_, row, notes)
            if ds is None:
                notes.append(
                    f"layer {layer.index + 1} ({layer.soil_type}): no Cc and e0 (or LL and "
                    "moisture) and no modulus number in the code pack: consolidation not "
                    "computed"
                )
                unknown.append(layer.index)
            else:
                consolidation += ds
                estimated.append(layer.index)
                consolidated.append(layer.index)
            continue
        consolidated.append(layer.index)
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
        if "secondary" in row:
            row["secondary"] = round(row["secondary"], 2)
        row["total"] = round(row["immediate"] + row["consolidation"] + row.get("secondary", 0), 2)
        row["method"] = ", ".join(row["method"])
    return {
        "B": round(b * 1e3),
        "L": round(l_ * 1e3),
        "Df": round(df * 1e3),
        "q": round(q, 1),
        "immediate": immediate,
        "consolidation": consolidation,
        "secondary": secondary,
        "total": immediate + consolidation + secondary,
        "C1": c1,
        "C2": c2,
        "Izp": diagram["izp"],
        "depth": round(depth * 1e3),
        "layers": layers,
        "notes": notes,
        "consolidated": consolidated,
        "estimated": estimated,
        "unknownConsolidation": unknown,
        "allowable": profile.design.allowableSettlement,
        "permissible": permissible(foundation, soil_column(profile, df, depth)),
    }


def modulus_rules() -> Any | None:
    """The code pack's modulus numbers (``foundations.piles.settlement``: ``modulus``,
    ``referenceStress``), or None when the pack has none."""
    from saengine.soil import piles as soil_piles

    found = soil_piles.pile_rules()
    rules = found.settlement if found is not None else None
    return rules if rules is not None and getattr(rules, "modulus", None) else None


def modulus_row(layer: SoilLayer, found: Any) -> Any | None:
    """The code pack's modulus number row of a layer: by soil type and its class (sand and
    silt by density, clay by consistency, loose / soft when unknown)."""
    from saengine.soil import piles as soil_piles

    cls = soil_piles.density_class(layer) or "loose"
    soil = layer.soil_type
    if soil == "silt" and layer.behaviour == "cohesive":
        soil = "clay"
    if soil == "fill":
        soil = "clay" if layer.behaviour == "cohesive" else "sand"
    for row in found.modulus:
        if soil in row.soilTypes and (not row.density or cls in row.density):
            return row
    return None


def janbu_strain(layer: SoilLayer, s0: float, s1: float, found: Any) -> tuple[float, Any]:
    """Strain of a slice from σ0' to σ1' [kPa] by the modulus number method (Janbu), with the
    code pack's lower M of the layer's row: ``j = 0``: ``ln(σ1'/σ0')/M``; ``j > 0``:
    ``[(σ1'/σr)^j - (σ0'/σr)^j]/(M j)``, for a clay with j > 0 the larger of both."""
    row = modulus_row(layer, found)
    if row is None or s1 <= s0:
        return 0.0, row
    m, j, sr = row.M[1], row.j, found.referenceStress
    log_form = math.log(s1 / s0) / m
    if j <= 0:
        return log_form, row
    power = ((s1 / sr) ** j - (s0 / sr) ** j) / (m * j)
    if layer.behaviour == "cohesive":
        return max(power, log_form), row
    return power, row


def can_consolidate(layer: SoilLayer) -> bool:
    """Whether the consolidation of a cohesive layer can be worked out: with Cc and e0, else
    estimated from its SPTs (:func:`stroud_mv`) or by the code pack's modulus numbers."""
    if layer.cc is not None and layer.e0 is not None:
        return True
    if is_stiff(layer) and layer.E:
        return True
    if stroud_mv(layer) is not None:
        return True
    found = modulus_rules()
    return found is not None and modulus_row(layer, found) is not None


def is_stiff(layer: SoilLayer) -> bool:
    """A stiff clay by the code pack's soil classes (cu at least its ``stiffCu``)."""
    from saengine.soil import piles as soil_piles

    return soil_piles.density_class(layer) == "dense"


#: Walk 4 W4B-10: Stroud & Butler (1975), "The standard penetration test and the engineering
#: properties of glacial materials", Proc. Symp. Engineering Behaviour of Glacial Materials,
#: Birmingham: mv = 1/(f2 N60), f2 [kPa per blow] about 450 for clays of PI 30 and more, rising
#: to about 600 at PI 20 (their Fig.; Clayton 1995, CIRIA Report 143, Fig. 31). Unknown PI:
#: 450, the more compressible end. A soft clay of N 4-6 takes mv 0.37-0.56 m²/MN, inside the
#: 0.3-1.0 m²/MN of soft-to-firm clays (Tomlinson, Foundation Design and Construction, Table
#: 2.8 type ranges); the code pack's Janbu modulus numbers (lower M 5 of a soft silty clay with
#: the log form) gave about 2-7 m²/MN at the stresses below a footing (allowable 8 kPa).
STROUD_F2 = ((20.0, 600.0), (30.0, 450.0))


def stroud_mv(layer: SoilLayer) -> float | None:
    """mv [1/kPa] of a clay from its mean N60 (Stroud & Butler 1975, :data:`STROUD_F2`);
    None without an N60."""
    if not layer.n60 or layer.n60 <= 0:
        return None
    (pi_low, f_low), (pi_high, f_high) = STROUD_F2
    pi = layer.pi
    f2 = f_high if pi is None else float(np.interp(pi, [pi_low, pi_high], [f_low, f_high]))
    return 1.0 / (f2 * float(layer.n60))


def stroud_text(layer: SoilLayer) -> str:
    mv = stroud_mv(layer)
    assert mv is not None
    return (
        f"mv = 1/(f2 N60) = {mv * 1e3:.2f} m²/MN, N60 = {layer.n60:.1f}, f2 = "
        f"{1 / (mv * float(layer.n60)):.0f} kPa (Stroud & Butler 1975)"
    )


def _estimated_consolidation(
    profile: Profile,
    layer: SoilLayer,
    top: float,
    bottom: float,
    df: float,
    q: float,
    b: float,
    l_: float,
    row: dict[str, Any],
    notes: list[str],
) -> float | None:
    mv = stroud_mv(layer)
    if mv is not None:
        # Walk 4 W4B-10: a clay with SPTs and no tests: mv from N60 (Stroud & Butler 1975),
        # s = Σ mv Δσ h over the same slices and 2:1 spread.
        n = max(1, math.ceil((bottom - top) / CONSOLIDATION_SLICE))
        h = (bottom - top) / n
        total = sum(
            mv * stress_increase(q, b, l_, top + (k + 0.5) * h - df) * h * 1e3 for k in range(n)
        )
        row["consolidation"] += total
        row["method"].append(f"consolidation estimated: {stroud_text(layer)}")
        notes.append(
            f"layer {layer.index + 1} ({layer.soil_type}): no Cc and e0 from tests, so its "
            f"consolidation ({total:.1f} mm) is an estimate from the SPT: {stroud_text(layer)}; "
            "give consolidation tests (or LL and moisture) to compute it"
        )
        return total
    return _janbu_consolidation(profile, layer, top, bottom, df, q, b, l_, row, notes)


def _janbu_consolidation(
    profile: Profile,
    layer: SoilLayer,
    top: float,
    bottom: float,
    df: float,
    q: float,
    b: float,
    l_: float,
    row: dict[str, Any],
    notes: list[str],
) -> float | None:
    """Consolidation [mm] of a clay without Cc and e0, estimated by the code pack's modulus
    number method (the same as the long-term settlement of a pile group), 0.25 m slices under
    the 2:1 spread; None when the pack gives no modulus number for it."""
    found = modulus_rules()
    pack_row = modulus_row(layer, found) if found is not None else None
    if found is None or pack_row is None:
        return None
    n = max(1, math.ceil((bottom - top) / CONSOLIDATION_SLICE))
    h = (bottom - top) / n
    total = 0.0
    for k in range(n):
        z = top + (k + 0.5) * h
        s_0 = max(profile.sigma_v_eff(z), 1e-6)
        strain, _ = janbu_strain(layer, s_0, s_0 + stress_increase(q, b, l_, z - df), found)
        total += strain * h * 1e3
    row["consolidation"] += total
    from saengine.soil import piles as soil_piles

    clause = soil_piles.pile_clause("settlement.modulus").split(";")[0]
    row["method"].append(
        f"consolidation estimated: modulus number M = {pack_row.M[1]:g}, j = {pack_row.j:g} "
        f"({pack_row.name})"
    )
    notes.append(
        f"layer {layer.index + 1} ({layer.soil_type}): no Cc and e0 from tests, so its "
        f"consolidation ({total:.1f} mm) is an estimate by the modulus number method of the "
        f"code pack: {pack_row.name}, the lower M = {pack_row.M[1]:g}, j = {pack_row.j:g}"
        + (f" ({clause})" if clause else "")
        + "; give consolidation tests (or LL and moisture) to compute it"
    )
    return total


def rounded(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    for key in ("immediate", "consolidation", "secondary", "total"):
        out[key] = round(out[key], 1)
    for key in ("C1", "C2", "Izp"):
        if key in out:
            out[key] = round(out[key], 3)
    return out

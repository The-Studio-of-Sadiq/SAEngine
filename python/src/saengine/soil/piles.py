"""Pile design parameters per layer and the modulus of subgrade reaction, for Part 9.

Unit skin friction fs and unit end bearing qb [kPa] (ultimate values; the factor of safety is
applied in the pile design), evaluated at the middle of each layer.

Bored cast-in-situ piles (drilled shafts), O'Neill & Reese (1999), "Drilled shafts:
construction procedures and design methods", FHWA-IF-99-025:

- Cohesive (α method): ``fs = α cu``, α = 0.55 for cu/pa ≤ 1.5, ``0.55 - 0.1 (cu/pa - 1.5)``
  for 1.5 < cu/pa ≤ 2.5; ``qb = Nc* cu ≤ 3830 kPa`` with Nc* = 9 for cu ≥ 96 kPa, 8.0 at 48 kPa
  and 6.5 at 24 kPa and below (linear in between), O'Neill & Reese's values of Nc* by the
  rigidity index they correlate with cu. The same method takes no side resistance in cohesive
  soil over the top 1.5 m (5 ft) of the shaft, over the bottom one diameter of a straight
  shaft (and the periphery of a bell plus one diameter above it). The per-layer fs here is the
  unit value only; the pile design (Part 9) must leave these zones out when it integrates fs
  over the shaft: each such row carries ``sideExclusion``.
- Granular (β method): ``fs = β σ'v ≤ 192 kPa`` (2 tsf), ``β = 1.5 - 0.245 √z`` (z in m),
  0.25 ≤ β ≤ 1.2, times N60/15 when N60 < 15; ``qb = 57.5 N60 ≤ 2870 kPa`` (0.6 N60 tsf ≤ 30
  tsf), N60 at most 50.

Driven piles:

- Cohesive (API RP 2A, α method of Randolph & Murphy 1985): ``fs = α cu``, ψ = cu/σ'v,
  ``α = 0.5 ψ^-0.5`` for ψ ≤ 1, ``0.5 ψ^-0.25`` for ψ > 1, α ≤ 1; ``qb = 9 cu``.
- Granular (Meyerhof 1976, "Bearing capacity and settlement of pile foundations", J. Geotech.
  Eng. Div. 102(GT3), SI form): ``fs = 2 N̄60 ≤ 100 kPa`` for displacement piles;
  ``qb = 0.4 pa N60 (L/D) ≤ 4 pa N60``; the table gives the limit, reached with an embedment
  of 10 diameters in the layer (less in proportion).

Rock layers are not covered (rock sockets need the rock's strength); organic soil and fill
are reported with the cohesive or granular rule they fall under, and should normally be
ignored for capacity (and checked for downdrag).

Modulus of subgrade reaction ks [kN/m³] for a footing or raft of width B: the secant value
``ks = qa / s(qa)``, the allowable pressure over the settlement this module computes under it
(:mod:`saengine.soil.settlement`), for the report's subgrade footing. Bowles' (1996)
``ks ≈ 40 FS qa`` (the ultimate pressure over 25 mm) is given next to it for comparison. ks
is not a soil constant: it falls with the loaded width (Terzaghi 1955: about B_ref/B for
clay); a raft is better modelled with the settlement of the whole raft.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from saengine.soil.profile import PA, Profile, SoilLayer


def _n_c_star(cu: float) -> float:
    points = ((24.0, 6.5), (48.0, 8.0), (96.0, 9.0))
    if cu <= points[0][0]:
        return points[0][1]
    for (c1, n1), (c2, n2) in pairwise(points):
        if cu <= c2:
            return n1 + (n2 - n1) * (cu - c1) / (c2 - c1)
    return 9.0


# Bored piles in cohesive soil: zones with no side resistance (O'Neill & Reese 1999).
BORED_CLAY_EXCLUSION = {"top": 1500, "bottomDiameters": 1.0, "bellDiameters": 1.0}
BORED_CLAY_NOTE = (
    "α method: no side resistance over the top 1.5 m of the shaft and the bottom 1 D (a bell's "
    "periphery and 1 D above it); leave these out when integrating fs"
)
PILE_NOTES = {
    "bored": (
        "Unit values per layer at mid-depth (ultimate; the FS is applied in the pile design). "
        "Bored piles, O'Neill & Reese (1999): in cohesive soil the top 1.5 m of the shaft and "
        "its bottom one diameter (a bell's periphery and one diameter above it) carry no side "
        "resistance; the pile design must exclude them."
    ),
    "driven": (
        "Unit values per layer at mid-depth (ultimate; the FS is applied in the pile design). "
        "Driven piles: API RP 2A α in clay, Meyerhof (1976) SPT values in sand."
    ),
}


def bored(layer: SoilLayer, z: float, sigma_eff: float) -> dict[str, Any]:
    if layer.behaviour == "cohesive":
        if layer.cu is None:
            return {"note": "no cu"}
        ratio = layer.cu / PA
        alpha = 0.55 if ratio <= 1.5 else max(0.45, 0.55 - 0.1 * (ratio - 1.5))
        note = BORED_CLAY_NOTE
        if ratio > 2.5:
            note = f"cu/pa above 2.5: treat as rock-like; {note}"
        return {
            "fs": alpha * layer.cu,
            "qb": min(3830.0, _n_c_star(layer.cu) * layer.cu),
            "alpha": alpha,
            "method": "α method, O'Neill & Reese 1999",
            "sideExclusion": BORED_CLAY_EXCLUSION,
            "note": note,
        }
    if layer.n60 is None:
        return {"note": "no SPT in the layer"}
    beta = min(1.2, max(0.25, 1.5 - 0.245 * math.sqrt(max(z, 0.0))))
    if layer.n60 < 15:
        beta *= layer.n60 / 15
    return {
        "fs": min(192.0, beta * sigma_eff),
        "qb": min(2870.0, 57.5 * min(layer.n60, 50.0)),
        "beta": beta,
        "method": "β method, O'Neill & Reese 1999",
        "note": None,
    }


def driven(layer: SoilLayer, z: float, sigma_eff: float) -> dict[str, Any]:
    if layer.behaviour == "cohesive":
        if layer.cu is None:
            return {"note": "no cu"}
        psi = layer.cu / max(sigma_eff, 1e-6)
        alpha = min(1.0, 0.5 * psi**-0.5 if psi <= 1 else 0.5 * psi**-0.25)
        return {
            "fs": alpha * layer.cu,
            "qb": 9 * layer.cu,
            "alpha": alpha,
            "method": "α method, API RP 2A",
            "note": None,
        }
    if layer.n60 is None:
        return {"note": "no SPT in the layer"}
    return {
        "fs": min(100.0, 2 * layer.n60),
        "qb": 4 * PA * layer.n60,
        "method": "Meyerhof 1976 (SPT)",
        "note": "qb reached at 10 diameters of embedment in the layer; 0.4 pa N60 L/D below",
    }


def pile_parameters(
    profile: Profile, liquefiable: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Per layer: fs and qb, and with the liquefaction screening's ranges (``liquefiable``,
    ``[{top, bottom}]`` [mm]) the share of the layer that liquefies and the seismic skin
    friction ``fsSeismic``: none over the liquefied share (liquefied soil is taken to carry no
    side resistance during the earthquake), the static value over the rest."""
    kind = profile.design.pile.type
    ranges = [(r["top"] / 1e3, r["bottom"] / 1e3) for r in liquefiable or []]
    rows = []
    for layer in profile.layers:
        z = layer.mid
        sigma_eff = profile.sigma_v_eff(z)
        row: dict[str, Any] = {
            "layer": layer.index,
            "top": round(layer.top * 1e3),
            "bottom": round(layer.bottom * 1e3),
            "soilType": layer.soil_type,
            "sigma_v_eff": round(sigma_eff, 1),
            "fs": None,
            "qb": None,
        }
        if layer.behaviour == "rock":
            row["note"] = "rock: socket design needs the rock strength (not covered)"
        else:
            values = (bored if kind == "bored" else driven)(layer, z, sigma_eff)
            for key in ("fs", "qb", "alpha", "beta"):
                if key in values:
                    row[key] = round(values[key], 3 if key in ("alpha", "beta") else 1)
            row["method"] = values.get("method")
            if "sideExclusion" in values:
                row["sideExclusion"] = dict(values["sideExclusion"])
            notes = [values["note"]] if values.get("note") else []
            if layer.soil_type in ("organic", "fill"):
                notes.append(f"{layer.soil_type}: normally ignored for capacity; check downdrag")
            share = _liquefied_share(layer.top, layer.bottom, ranges)
            if share > 0:
                row["liquefiable"] = round(share, 3)
                if row["fs"] is not None:
                    row["fsSeismic"] = round(row["fs"] * (1 - share), 1)
                notes.append(
                    f"liquefiable over {share:.0%} of the layer: no skin friction there under "
                    "the earthquake (fs seismic); check the downdrag as it settles after"
                )
            row["note"] = "; ".join(notes) or None
        rows.append(row)
    return rows


def _liquefied_share(top: float, bottom: float, ranges: list[tuple[float, float]]) -> float:
    """The part of the layer top-bottom [m] within the liquefiable ranges, 0 to 1."""
    if bottom <= top:
        return 0.0
    covered = sum(max(0.0, min(bottom, b) - max(top, a)) for a, b in ranges)
    return min(1.0, covered / (bottom - top))


#: A secant ks below this is very soft ground [kN/m³]: flagged before it reaches the analysis.
KS_LOW = 2000.0


def subgrade_modulus(profile: Profile, qa: float | None) -> dict[str, Any]:
    """Secant ks [kN/m³] of the report's subgrade footing under its allowable pressure qa."""
    from saengine.soil.settlement import settlement

    design = profile.design
    b, df = design.subgradeWidth / 1e3, design.subgradeDepth / 1e3
    if not qa:
        return {"value": None, "note": "no allowable pressure for the subgrade footing"}
    s = settlement(profile, b, b, df, qa)
    total = s["total"]
    bowles = 40 * design.factorOfSafety * qa
    if total <= 0:
        return {"value": None, "bowles": round(bowles), "note": "no settlement computed"}
    value = qa / (total / 1e3)
    note = (
        f"Square footing {b:g} m wide at {df:g} m: ks falls with the loaded width (about "
        "B_ref/B in clay); a raft is better designed from the settlement of the whole raft. "
        "Bowles' 40·FS·qa is shown for comparison."
    )
    if value < KS_LOW:
        note += (
            f" ks {value:.0f} kN/m³ is below {KS_LOW:.0f}: very soft ground (Bowles, Foundation "
            "Analysis and Design, Table 9-1, gives 4800 and up for loose sand, 12000 and up for "
            "clay); check the footing settlements, or use a raft or piles."
        )
    return {
        "value": round(value),
        "B": round(b * 1e3),
        "Df": round(df * 1e3),
        "q": round(qa, 1),
        "settlement": round(total, 1),
        "bowles": round(bowles),
        "method": "ks = qa/s(qa), the secant value for the subgrade footing",
        "low": value < KS_LOW,
        "note": note,
    }

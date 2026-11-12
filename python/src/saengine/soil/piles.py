"""Pile design parameters per layer and the modulus of subgrade reaction, for Part 9.

Unit skin friction fs and unit end bearing qb [kPa] (ultimate values; the factor of safety is
applied in the pile design), evaluated at the middle of each layer.

Bored cast-in-situ piles: the drilled-shaft unit values of the code pack's
``foundations.piles.drilledShaft`` group (:func:`shaft_values`; the default pack's clauses in
its ``sources``):

- Cohesive (α method): ``fs = α cu``, α a constant up to a limit of cu and from the pack's
  adhesion-factor figure above it; ``qb = Nc cu ≤ max`` with ``Nc = base (1 + slope L/Db) ≤
  max`` (at its largest in the per-layer table, where the pile is not known), reduced by Fr for
  a base wider than the pack's limit. No side resistance over the top length of the shaft and
  the bottom diameters the pack gives: the per-layer fs here is the unit value only; the pile
  design (Part 9) leaves these zones out when it integrates fs over the shaft: each such row
  carries ``sideExclusion``.
- Granular (β method): ``fs = β σ'v`` with ``β = intercept - slope √(z/Br)`` (at least 0;
  optional practice bounds of the pack: β ≤ max, × N60/lowN for a low N60, fs ≤ max), or
  ``β = (K/K0) K0 tan((δ/φ) φ')``, ``K0 = (1 - sin φ') √OCR``, when the shaft's construction
  method is chosen; ``qb = c σr N60 ≤ max`` with N60 the mean over the pack's depth below the
  base, reduced by ``Fr = k Br/Db`` for a wide base.

A pack without the group does not cover these values (the rows say so).

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


def pile_rules() -> Any | None:
    """The code pack's ``foundations.piles`` group (deep foundation rules), or None when the
    pack in force does not cover them."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    table = pack.table("foundations") if pack.has("foundations") else None
    if table is None or getattr(table, "piles", None) is None:
        from saengine.codes.registry import DEFAULT_PACK
        from saengine.codes.tables import builtin_table

        if pack.id != DEFAULT_PACK:
            return None
        table = builtin_table("foundations", DEFAULT_PACK)
    return table.piles


def pile_clause(key: str) -> str:
    """The clause of ``piles.<key>`` in the pack's foundations sources (empty when none)."""
    from saengine.codes import context as code_context

    try:
        table = code_context.current().table("foundations")
    except Exception:  # noqa: BLE001 - a pack without the table names no clause
        return ""
    return table.sources.get(f"piles.{key}", "")


def pack_name() -> str:
    from saengine.codes import context as code_context

    pack = code_context.current()
    return pack.name or pack.id


def interpolate(points: Any, x: float) -> float:
    """Linear interpolation in ``[[x, y], ...]`` (sorted by x), the end values outside."""
    rows = sorted((float(a), float(b)) for a, b in points)
    if x <= rows[0][0]:
        return rows[0][1]
    for (x1, y1), (x2, y2) in pairwise(rows):
        if x <= x2:
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return rows[-1][1]


def density_class(layer: SoilLayer, rules: Any | None = None) -> str | None:
    """'loose', 'medium' or 'dense' (for clay: soft, medium stiff, stiff) by the pack's
    ``soilClasses``: granular soil by its mean N60, cohesive soil by cu; None when unknown."""
    rules = rules or pile_rules()
    if rules is None:
        return None
    classes = rules.soilClasses
    if layer.behaviour == "cohesive":
        if layer.cu is None:
            return None
        if layer.cu >= classes.stiffCu:
            return "dense"
        return "medium" if layer.cu >= classes.mediumCu else "loose"
    if layer.n60 is None:
        return None
    if layer.n60 >= classes.denseN:
        return "dense"
    return "medium" if layer.n60 >= classes.mediumN else "loose"


def shaft_alpha(cu: float, shaft: Any) -> float:
    """Adhesion factor of a drilled shaft: the pack's constant up to its limit of cu, its
    adhesion-factor figure above."""
    if cu <= shaft.alphaLimit:
        return float(shaft.alpha)
    return interpolate(shaft.alphaHigh, cu)


def shaft_clay_base(
    cu: float, length: float | None, diameter: float | None, shaft: Any
) -> tuple[float, str]:
    """End bearing [kPa] of a drilled shaft in clay: Nc cu ≤ max, Nc from L/Db [m] (its
    largest without the pile), times Fr for a base wider than the pack's limit."""
    rules = pile_rules()
    static = rules.static
    if length and diameter:
        nc = min(static.ncMax, static.ncBase * (1 + static.ncSlope * length / diameter))
    else:
        nc = static.ncMax
    qb = min(shaft.baseMax, nc * cu)
    text = f"fb = Nc cu ≤ {shaft.baseMax:g} kPa, Nc = {nc:.2f}"
    if diameter and length and diameter * 1e3 > shaft.clayReduceAbove:
        a, b, top = shaft.omega1
        omega1 = min(a + b * length / diameter, top)
        c, low, high = shaft.omega2
        omega2 = min(max(c * math.sqrt(cu / shaft.referenceStress), low), high)
        fr = min(
            1.0,
            shaft.frNumerator
            / (shaft.frWidthFactor * omega1 * diameter * 1e3 / shaft.referenceWidth + omega2),
        )
        qb *= fr
        text += f"; Db > {shaft.clayReduceAbove:g} mm: × Fr {fr:.3f}"
    return qb, text


def shaft_sand_base(n60: float, diameter: float | None, shaft: Any) -> tuple[float, str]:
    """End bearing [kPa] of a drilled shaft in sand: c σr N60 ≤ max, times Fr = k Br/Db for a
    base wider than the pack's limit (``diameter`` in m)."""
    qb = min(shaft.sandBaseMax, shaft.sandBase * shaft.referenceStress * n60)
    text = f"fb = {shaft.sandBase:g} σr N60 ≤ {shaft.sandBaseMax:g} kPa"
    if diameter and diameter * 1e3 > shaft.sandReduceAbove:
        fr = min(1.0, shaft.sandFr * shaft.referenceWidth / (diameter * 1e3))
        qb *= fr
        text += f"; Db > {shaft.sandReduceAbove:g} mm: × Fr {fr:.3f}"
    return qb, text


def shaft_beta(
    layer: SoilLayer, z: float, shaft: Any, construction: tuple[str, str] | None = None
) -> tuple[float, str]:
    """β of a drilled shaft in sand at depth ``z`` [m]: from the construction method's K/K0
    and δ/φ (``construction`` = their ids) when given and φ' is known, else the empirical
    depth relation, with the pack's practice bounds."""
    if construction and layer.phi:
        k_id, d_id = construction
        k_ratio = next((r.value for r in shaft.lateralRatio if r.id == k_id), None)
        d_ratio = next((r.value for r in shaft.frictionRatio if r.id == d_id), None)
        if k_ratio is not None and d_ratio is not None:
            phi = math.radians(layer.phi)
            k0 = (1 - math.sin(phi)) * math.sqrt(max(layer.ocr, 1.0))
            beta = k_ratio * k0 * math.tan(d_ratio * phi)
            return beta, f"β = (K/K0) K0 tan δ = {beta:.3f} ({k_id}, {d_id})"
    beta = shaft.betaIntercept - shaft.betaSlope * math.sqrt(
        max(z, 0.0) * 1e3 / shaft.referenceWidth
    )
    text = f"β = {shaft.betaIntercept:g} - {shaft.betaSlope:g} √(z/Br)"
    if shaft.betaMax is not None:
        beta = min(beta, shaft.betaMax)
    if shaft.lowN is not None and layer.n60 is not None and layer.n60 < shaft.lowN:
        beta *= layer.n60 / shaft.lowN
        text += f" × N60/{shaft.lowN:g}"
    return max(beta, 0.0), text


def bored(
    layer: SoilLayer,
    z: float,
    sigma_eff: float,
    *,
    length: float | None = None,
    diameter: float | None = None,
    n_base: float | None = None,
    construction: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Drilled-shaft unit values [kPa] of a layer at depth ``z`` [m]. ``length`` / ``diameter``
    [m] of the pile for Nc and the large-base reductions (none: the per-layer table, Nc at its
    largest, no reduction); ``n_base`` the N60 below the base (default the layer's mean)."""
    rules = pile_rules()
    if rules is None:
        return {"note": f"drilled-shaft values: not covered by the code pack {pack_name()}"}
    shaft = rules.drilledShaft
    if layer.behaviour == "cohesive":
        if layer.cu is None:
            return {"note": "no cu"}
        alpha = shaft_alpha(layer.cu, shaft)
        qb, base_text = shaft_clay_base(layer.cu, length, diameter, shaft)
        return {
            "fs": alpha * layer.cu,
            "qb": qb,
            "alpha": alpha,
            "method": f"α method (drilled shaft), α = {alpha:.3f}; {base_text}",
            "sideExclusion": {
                "top": shaft.sideTop,
                "bottomDiameters": shaft.sideBottom,
                "bellDiameters": shaft.sideBottom,
            },
            "note": (
                f"α method: no side resistance over the top {shaft.sideTop:g} mm of the shaft "
                f"and the bottom {shaft.sideBottom:g} D (a bell's periphery and 1 D above it); "
                "leave these out when integrating fs"
                + ("" if length else "; qb with Nc at its largest (the pile is not known)")
            ),
        }
    if layer.n60 is None:
        return {"note": "no SPT in the layer"}
    beta, beta_text = shaft_beta(layer, z, shaft, construction)
    fs = beta * sigma_eff
    if shaft.skinMax is not None:
        fs = min(fs, shaft.skinMax)
    qb, base_text = shaft_sand_base(n_base if n_base is not None else layer.n60, diameter, shaft)
    return {
        "fs": fs,
        "qb": qb,
        "beta": beta,
        "method": f"β method (drilled shaft), {beta_text}; {base_text}",
        "note": None,
    }


def _bored_note() -> str:
    rules = pile_rules()
    if rules is None:
        return f"Bored piles: drilled-shaft values not covered by the code pack {pack_name()}."
    shaft = rules.drilledShaft
    return (
        "Unit values per layer at mid-depth (ultimate; the FS is applied in the pile design). "
        f"Bored piles, drilled-shaft values ({pack_name()}: "
        f"{pile_clause('drilledShaft.minDiameter').split(':')[0]}): in cohesive soil the top {shaft.sideTop:g} mm of the shaft and its bottom "
        f"{shaft.sideBottom:g} diameter (a bell's periphery and one diameter above it) carry no "
        "side resistance; the pile design must exclude them. qb in clay with Nc at its largest "
        "and in sand with the layer's N60; the pile design takes them with the pile's L/Db, the "
        "N60 below its base and the large-base reductions."
    )


class _PileNotes(dict):
    """``PILE_NOTES[kind]``: the per-layer table's note, the bored one from the pack."""

    def __missing__(self, key: str) -> str:
        if key == "bored":
            return _bored_note()
        raise KeyError(key)


PILE_NOTES = _PileNotes(
    driven=(
        "Unit values per layer at mid-depth (ultimate; the FS is applied in the pile design). "
        "Driven piles: API RP 2A α in clay, Meyerhof (1976) SPT values in sand."
    ),
)


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

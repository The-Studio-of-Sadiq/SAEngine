"""Settlement of single piles and pile groups (Part 9, deep foundations).

Every number comes from the code pack's ``foundations.piles.settlement`` group and every
clause from the table's ``sources`` (the default pack: BNBC 2020 Part 6 Sec 3.10.5).

Single pile under its working load Q (:func:`single_settlement`), split between the tip and
the shaft in the proportion of the ultimate end bearing and skin friction (Qp = Q Qb / (Qs +
Qb), Qs,w = Q - Qp):

- axial shortening ``Sax = (Qp + a Qs,w) L / (A Ep)``, a by the soil along the shaft (the
  pack's cohesive value for clay and silt, its granular value for sand, weighted by the shares
  of the skin friction);
- at the tip ``Spt = Cp Qp / (D qo)``, Cp from the pack's table by pile kind and the soil at
  the tip (sand and silt by density, clay by consistency, :func:`saengine.soil.piles.
  density_class`), qo the ultimate unit end bearing;
- by the skin friction ``Ssf = Cs Qs,w / (X qo)`` with ``Cs = (intercept + slope L/D) Cp``
  and X the embedded length L or the diameter D by the pack's ``skinDenominator`` (the default
  pack: L, see its note on Eq 6.3.36);
- ``St = Sax + Spt + Ssf``.

Pile group (:func:`group_settlement`):

- short term, the larger of ``Sg = St (B/D)^e1`` (B the group's least width) and
  ``Sg = St n^e2`` (the group settlement ratio);
- long term, the group as a solid foundation at ``blockDepth`` × L below its head under the
  group's load spread 2:1 below it (:func:`saengine.soil.settlement.settlement`): 1D
  consolidation of the clay layers with Cc and e0; for the other layers within the stressed
  depth (clay without them, sand, gravel and silt), the modulus number method (:func:`janbu`)
  with the pack's lower M of the soil's row: ``j = 0``: ``S = H/M ln(σ1'/σ0')``; ``j > 0``:
  ``S = H/(M j) [(σ1'/σr)^j - (σ0'/σr)^j]`` (for a clay with j > 0 the larger of both);
- the total: the short-term (at least the block's immediate settlement) plus the long-term.

Units: m, kN and kPa inside; settlements reported in mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.soil import piles as soil_piles
from saengine.soil.profile import Profile, SoilLayer


def rules() -> Any | None:
    found = soil_piles.pile_rules()
    return found.settlement if found is not None else None


def _cp_key(layer: SoilLayer | None) -> str:
    """The Cp row of the soil at the tip (loose / soft when its class is not known)."""
    if layer is None:
        return "looseSand"
    cls = soil_piles.density_class(layer)
    dense = cls == "dense"
    if layer.behaviour == "cohesive":
        return "stiffClay" if dense else "softClay"
    if layer.soil_type == "silt":
        return "denseSilt" if dense else "looseSilt"
    return "denseSand" if dense else "looseSand"


def single_settlement(
    pile: dict[str, Any],
    load: float,
    profile: Profile,
    modulus: float,
) -> dict[str, Any] | None:
    """Settlement [mm] of one pile (``pile``: :func:`saengine.substructure.piles.single_pile`)
    under the working ``load`` [kN], Ep ``modulus`` [MPa]. None when the pack does not cover
    pile settlement."""
    found = rules()
    if found is None:
        return None
    from saengine.substructure.piles import section_shape

    kind = pile["kind"]
    d = pile["diameter"] / 1e3
    length = pile["length"] / 1e3
    qs_ult, qb_ult = max(pile["Qs"], 0.0), max(pile["Qb"], 0.0)
    total_ult = qs_ult + qb_ult
    if total_ult <= 0 or load <= 0:
        return {"total": 0.0, "Sax": 0.0, "Spt": 0.0, "Ssf": 0.0, "note": "no load or capacity"}
    qp = load * qb_ult / total_ult
    qs = load - qp
    area = section_shape(kind, d)[1]
    # a: weighted by the skin friction carried in cohesive and in granular layers
    cohesive = sum(r["Qs"] for r in pile["layers"] if _cohesive(profile, r["layer"]))
    share = cohesive / qs_ult if qs_ult > 0 else 1.0
    a = share * found.axialShare["cohesive"] + (1 - share) * found.axialShare["granular"]
    s_ax = (qp + a * qs) * length / (area * modulus * 1e3)
    tip_layer = profile.layer_at(pile["tip"] / 1e3 + 1e-6)
    key = _cp_key(tip_layer)
    cp = found.cp[kind][key]
    qo = pile["qb"]
    if qo <= 0:
        s_pt = s_sf = 0.0
        note = "no end bearing at the tip: Spt and Ssf not computed"
    else:
        s_pt = cp * qp / (d * qo)
        cs = (found.csIntercept + found.csSlope * length / d) * cp
        span = length if found.skinDenominator == "length" else d
        s_sf = cs * qs / (span * qo)
        note = None
    total = s_ax + s_pt + s_sf
    return {
        "load": round(load, 1),
        "Qp": round(qp, 1),
        "QsWorking": round(qs, 1),
        "a": round(a, 3),
        "Ep": round(modulus),
        "Cp": cp,
        "soil": key,
        "Sax": round(s_ax * 1e3, 2),
        "Spt": round(s_pt * 1e3, 2),
        "Ssf": round(s_sf * 1e3, 2),
        "total": round(total * 1e3, 2),
        "note": note,
        "method": (
            f"St = Sax + Spt + Ssf; Ssf = Cs Qs / ({'L' if span == length else 'D'} qo)"
            if qo > 0
            else "St = Sax"
        ),
    }


def _cohesive(profile: Profile, index: int) -> bool:
    layer = next((x for x in profile.layers if x.index == index), None)
    return layer is not None and layer.behaviour == "cohesive"


def _modulus_row(layer: SoilLayer, found: Any) -> Any | None:
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
    """Strain of a slice from σ0' to σ1' [kPa] by the modulus number method, and its row."""
    row = _modulus_row(layer, found)
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


def janbu(
    profile: Profile,
    df: float,
    b: float,
    l_: float,
    q: float,
    depth: float,
    skip: set[int],
) -> tuple[float, list[dict[str, Any]]]:
    """Long-term settlement [m] by the modulus number method of the layers within ``depth``
    below ``df`` not in ``skip`` (their indexes), under q [kPa] on B × L [m] spread 2:1."""
    from saengine.soil.settlement import stress_increase

    found = rules()
    if found is None:
        return 0.0, []
    total = 0.0
    rows: dict[int, dict[str, Any]] = {}
    steps = max(1, math.ceil(depth / 0.25))
    h = depth / steps
    for k in range(steps):
        z = df + (k + 0.5) * h
        layer = profile.layer_at(z)
        if layer is None or layer.index in skip or layer.behaviour == "rock":
            continue
        s0 = max(profile.sigma_v_eff(z), 1e-6)
        s1 = s0 + stress_increase(q, b, l_, z - df)
        strain, row = janbu_strain(layer, s0, s1, found)
        if row is None:
            continue
        ds = strain * h
        total += ds
        r = rows.setdefault(
            layer.index,
            {"layer": layer.index, "soilType": layer.soil_type, "row": row.id, "M": row.M[1],
             "j": row.j, "settlement": 0.0},
        )  # fmt: skip
        r["settlement"] += ds * 1e3
    for r in rows.values():
        r["settlement"] = round(r["settlement"], 2)
    return total, sorted(rows.values(), key=lambda r: r["layer"])


def group_settlement(
    profile: Profile,
    pile: dict[str, Any],
    count: int,
    bg: float,
    lg: float,
    load: float,
    modulus: float,
) -> dict[str, Any]:
    """Settlement [mm] of a group of ``count`` piles, outline Bg × Lg [m] under the total
    working ``load`` [kN] (see the module notes): ``{"total", "shortTerm", "longTerm",
    "single", "block", "janbu", "permissible", ...}``."""
    from saengine.soil.settlement import influence_depth, rounded, settlement

    found = rules()
    head, length = pile["head"] / 1e3, pile["length"] / 1e3
    depth_share = found.blockDepth if found is not None else 2 / 3
    df = head + depth_share * length
    q = load / (bg * lg)
    block = rounded(settlement(profile, bg, lg, df, q))
    result: dict[str, Any] = {**block, "block": dict(block)}
    if found is None:
        result["method"] = soil_piles.pack_name() + ": pile settlement not covered"
        return result
    single = single_settlement(pile, load / max(count, 1), profile, modulus)
    d = pile["diameter"] / 1e3
    st = single["total"] if single else 0.0
    by_width = st * (min(bg, lg) / d) ** found.groupWidthExponent if count > 1 else st
    by_count = st * count**found.groupCountExponent if count > 1 else st
    short = max(by_width, by_count)
    immediate = block["immediate"]
    # the layers the block's consolidation covered (clay with Cc and e0)
    covered = {
        layer.index
        for layer in profile.layers
        if layer.behaviour == "cohesive" and layer.cc is not None and layer.e0 is not None
    }
    depth = influence_depth(profile, bg, lg, df, q)
    janbu_total, janbu_rows = janbu(profile, df, bg, lg, q, depth, covered)
    long_term = block["consolidation"] + block.get("secondary", 0.0) + janbu_total * 1e3
    total = max(short, immediate) + long_term
    result.update(
        {
            "total": round(total, 2),
            "shortTerm": round(short, 2),
            "shortByWidth": round(by_width, 2),
            "shortByCount": round(by_count, 2),
            "longTerm": round(long_term, 2),
            "janbu": round(janbu_total * 1e3, 2),
            "janbuLayers": janbu_rows,
            "single": single,
            "method": (
                f"short term: the larger of St (B/D)^{found.groupWidthExponent:g} and St "
                f"n^{found.groupCountExponent:g} (at least the block's immediate settlement), "
                f"single pile St = Sax + Spt + Ssf; long term: the group as a solid block at "
                f"{depth_share:.3g} L, consolidation of clay with Cc and e0, the modulus number "
                f"method for the other layers ({soil_piles.pack_name()}: "
                f"{soil_piles.pile_clause('settlement.groupWidthExponent').split(':')[0]})"
            ),
        }
    )
    return result

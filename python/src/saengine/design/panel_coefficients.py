"""Two-way slabs on beams by bending moment coefficients of restrained panels, and flat slabs'
end span shares by the column stiffness (alpha 9 C8; the pack's ``concreteMethods.twoWaySlabs``
method ``restrainedPanel`` and ``flatSlabs`` method ``columnStiffness``, as IS 456:2000 Annex D
and 31.4.3.3 give them).

Restrained panels: M = α w lx² per unit width, αx (short span; negative at a continuous edge,
positive at midspan) by ly / lx (linear between the pack's ratios, the end values outside)
and αy (long span) constant, of the case the continuous edges give. A case is named by the
continuous long edges (at the ends of the short span) and short edges, "L,S" ("2,2" the
interior panel ... "0,0" four edges discontinuous). The default pack's coefficient design
(:func:`saengine.design.slab.coefficient_design`) finds the edges and keeps its shear shares;
the corner torsion steel (torsionShare of the midspan steel over torsionLength × lx) is
checked by :func:`corner_rows` (alpha 9 C9b) in place of the parent's corner rows.

Flat slabs, end span (``flatSlabs``): with αc = Σ Kc / (Ks + Kb) of the exterior columns,
interior negative a - b / (1 + 1/αc), positive a - b / (1 + 1/αc), exterior negative
a / (1 + 1/αc) of Mo.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from saengine.design.tabulated_shear import _group, _interp


def rules() -> Any | None:
    return _group("twoWaySlabs", "restrainedPanel")


def flat_rules() -> Any | None:
    return _group("flatSlabs", "columnStiffness")


def edges_of(case: int) -> tuple[int, int]:
    """(continuous long edges, continuous short edges) of the default table's case number."""
    from saengine.design.slab import coefficient_table

    for number, (n_long, n_short) in coefficient_table()["twoWay"]["cases"].items():
        if int(number) == int(case):
            return int(n_long), int(n_short)
    raise ValueError(f"no case {case}")


def moments(ratio: float, long_continuous: int, short_continuous: int) -> dict[str, Any]:
    """αx negative / positive and αy negative / positive (None: that edge is discontinuous) of
    a panel with ly / lx = ``ratio``."""
    r = rules()
    found = r.cases.get(f"{long_continuous},{short_continuous}")
    if found is None:
        raise ValueError(f"no restrained panel case for {long_continuous},{short_continuous}")
    ratios = list(r.ratios)
    neg = _interp(ratio, ratios, list(found.shortNegative)) if found.shortNegative else None
    pos = _interp(ratio, ratios, list(found.shortPositive))
    return {
        "case": found.name,
        "shortNegative": neg,
        "shortPositive": pos,
        "longNegative": found.longNegative,
        "longPositive": found.longPositive,
    }


def coefficients(m: float, case: int, base: Any) -> Any:
    """The default table's :class:`saengine.design.slab.TwoWayCoefficients` at m = la / lb with
    the moment coefficients of the restrained panel."""
    long_c, short_c = edges_of(case)
    found = moments(1.0 / m if m > 0 else 1.0, long_c, short_c)
    # The default design takes the long span's moments as C w lb²; the panel's are αy w lx²:
    # αy (lx/ly)² = αy m² in its terms.
    m2 = m * m
    neg_b = found["longNegative"] * m2 if found["longNegative"] is not None else None
    return replace(
        base,
        neg_a=found["shortNegative"],
        neg_b=neg_b,
        dead_a=found["shortPositive"],
        live_a=found["shortPositive"],
        dead_b=found["longPositive"] * m2,
        live_b=found["longPositive"] * m2,
    )


def _required_area(demand: float, d: float, fc: float, fy: float, es: float) -> float:
    """As [mm²/m] whose strip capacity (:func:`saengine.design.slab.layer_capacity`) carries
    ``demand`` [N·mm/mm], by bisection."""
    from saengine.design import slab

    target = demand * 1000.0
    low, high = 0.0, 1000.0
    while slab.layer_capacity(high, d, fc, fy, es).phi_mn < target and high < 1e6:
        high *= 2
    for _ in range(40):
        mid = 0.5 * (low + high)
        if slab.layer_capacity(mid, d, fc, fy, es).phi_mn < target:
            low = mid
        else:
            high = mid
    return high


def corner_rows(
    panel: Any,
    h: float,
    reinforcement: Any,
    fc: float,
    fy: float,
    es: float,
    envelope: dict[str, tuple[float, str | None, str]],
) -> list[dict[str, Any]]:
    """Alpha 9 C9b: the torsion steel at the corners of a restrained panel (the pack's
    ``twoWaySlabs``, IS 456 Annex D-1.8 to D-1.10 type): at a corner where both edges are
    discontinuous, top and bottom meshes each way of ``torsionShare`` × the steel the largest
    midspan moment needs, over ``torsionLength`` × lx from the edges; where one of the edges is
    continuous, ``torsionOneEdgeShare`` of that; none where both are continuous. The panel's
    own top and bottom layers are taken as reaching the corner (one row per kind of corner)."""
    from saengine.design import slab
    from saengine.design.check import _check
    from saengine.design.tabulated_shear import cite

    r = rules()
    sides = panel.sides
    both, one = [], []
    for a in ("x-", "x+"):
        for b in ("y-", "y+"):
            continuous = int(sides[a].continuous) + int(sides[b].continuous)
            if continuous == 0:
                both.append(f"{a}/{b}")
            elif continuous == 1:
                one.append(f"{a}/{b}")
    if not both and not one:
        return []
    layers = slab.layers_of(reinforcement, h)
    key = max(("bottomX", "bottomY"), key=lambda k: envelope[k][0])
    demand, combination, _ = envelope[key]
    if demand <= slab.NO_DEMAND or layers.get(key) is None:
        return []
    need = _required_area(demand, layers[key].d, fc, fy, es)
    provided = min((layers[k].area if layers.get(k) is not None else 0.0) for k in slab.LAYERS)
    extent = r.torsionLength * min(panel.lx, panel.ly)
    clause = cite("twoWaySlabs")
    rows = []
    for corners, share, kind in (
        (both, r.torsionShare, "both edges discontinuous"),
        (one, r.torsionShare * r.torsionOneEdgeShare, "one edge continuous"),
    ):
        if not corners:
            continue
        rows.append(
            _check(
                f"Corner torsion steel, {kind}" + (f" ({clause})" if clause else ""),
                share * need,
                provided,
                "mm²/m",
                combination,
                f"each of the four layers (top and bottom, both ways) at least {share:g} × "
                f"As = {need:.0f} mm²/m of the largest midspan moment ({key}), over "
                f"{extent:.0f} mm from the edges; the least layer of the panel "
                f"{provided:.0f} mm²/m; corner(s) {', '.join(corners)}",
            )
        )
    return rows


def end_span_shares(alpha_c: float) -> tuple[float, float, float]:
    """(interior negative, positive, exterior negative) shares of Mo of an end span."""
    f = flat_rules()
    k = 1 + 1 / alpha_c if alpha_c > 0 else float("inf")
    return (
        f.interiorNegative[0] - f.interiorNegative[1] / k,
        f.positive[0] - f.positive[1] / k,
        f.exteriorNegative / k,
    )

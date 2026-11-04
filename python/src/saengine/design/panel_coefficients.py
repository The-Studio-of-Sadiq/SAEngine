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
reported in its notes.

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


def end_span_shares(alpha_c: float) -> tuple[float, float, float]:
    """(interior negative, positive, exterior negative) shares of Mo of an end span."""
    f = flat_rules()
    k = 1 + 1 / alpha_c if alpha_c > 0 else float("inf")
    return (
        f.interiorNegative[0] - f.interiorNegative[1] / k,
        f.positive[0] - f.positive[1] / k,
        f.exteriorNegative / k,
    )

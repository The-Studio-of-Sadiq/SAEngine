"""The stability design method of steel frames in the member checks (Project Settings ->
Analysis: ``notionalLoads``, ``directAnalysisTau``, ``directAnalysisNotional``), with every
value from the code pack's ``steelStability`` table.

Methods (default pack BNBC 2020 Part 6 Sec 10.3.2.2 and Sec 10.14, part 2 pp. 52-53 and 187-189):

- **Direct analysis method** (``"directAnalysis"``, the pack's ``directAnalysis``): the
  required strengths come from the second-order analysis on the reduced stiffness
  (:func:`saengine.fem.second_order.apply_second_order`) with the notional loads
  (:mod:`saengine.fem.notional_loads`), and every member's nominal strengths take K =
  ``effectiveLengthFactor`` (1.0, Sec 10.14.1), free ends included. P-small-delta along the
  members is the B1 amplifier with Pe1 on the reduced stiffness EI* = 0.8 τb EI (Sec 10.14.3
  (1) permits the amplified first-order method with B1 and B2 on the reduced stiffness; the
  analysis gives B2 by its P-Delta). Checks added per member:

  - columns: "P-δ neglected in the lateral displacement": αPr < 0.15 PeL, PeL = π² E I / L²
    of the member in each plane of bending (Eq 6.10.262), since the analysis model has one
    element per storey and so leaves P-δ out of the sway;
  - columns, with ``tau = "checked"``: τb = 1 in the analysis holds while αPr / Py <= 0.5
    (Eq 6.10.263); above it τb = 4 (αPr/Py)(1 - αPr/Py) < 1 and the column fails (use the
    additive notional load 0.001 Yi, which permits τb = 1 for every member);
  - every member, with the notional loads in the gravity-only combinations: Δ2nd / Δ1st <= 1.5
    (Sec 10.14.3 (2)).

- **Design by second-order analysis** (``"secondOrder"``) and **by first-order analysis**
  (``"firstOrder"``), and no method (``"none"``): where Δ2nd / Δ1st > 1.5 the direct
  analysis method is required (Sec 10.3.2.2), a check on every member; by second-order
  analysis the columns may take K = 1 only while Δ2nd / Δ1st <= 1.1 (Sec 10.3.2.2.1(d)), a
  flag; by first-order analysis αPr <= 0.5 Py (Eq 6.10.9), the flag of
  :func:`saengine.design.steel.members.check_member`.

Δ2nd / Δ1st is the largest storey ratio of the lateral cases' second-order drift over their
first-order reference (:func:`saengine.fem.second_order.drift_amplification`), so it needs a
P-Delta run with the first-order reference cases; without them it is reported as not known.
α is the pack's ``alpha.lrfd``: the steel design runs on the strength (LRFD) combinations.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

#: The direct analysis method's id (``settings.analysis.notionalLoads``).
DIRECT_ANALYSIS = "directAnalysis"


@dataclass
class Stability:
    """The stability design method of a design run, and what it needs of the member checks."""

    method: str = "none"
    #: α on Pr (the strength combinations: the pack's ``alpha.lrfd``).
    alpha: float = 1.0
    #: K of every member (the direct analysis method), else None (K from the bracing).
    unit_k: float | None = None
    #: EI* / (τb EI) of the reduced stiffness, for B1 (1.0 outside the direct analysis method).
    flexural_factor: float = 1.0
    #: "additive" (τb = 1 for every member) or "checked" (τb = 1, checked per column).
    tau: str = "additive"
    tau_limit: float = 0.5
    tau_factor: float = 4.0
    #: αPr < this × PeL to neglect P-δ in the lateral displacement (None: not checked).
    p_small_delta: float | None = None
    #: The largest Δ2nd / Δ1st of the structure and the case it comes from (None: not known).
    drift_ratio: float | None = None
    drift_case: str | None = None
    #: The limit of Δ2nd / Δ1st the method needs on every member, its check name and clause.
    drift_limit: float | None = None
    drift_name: str = ""
    drift_clause: str = ""
    #: By second-order analysis: K = 1 while Δ2nd / Δ1st <= this (a column flag).
    unit_k_ratio: float | None = None
    #: By first-order analysis: K = 1 while αPr / Py <= this (a column flag).
    first_order_axial: float = 0.5
    clauses: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def direct(self) -> bool:
        return self.method == DIRECT_ANALYSIS

    def clause(self, key: str) -> str:
        return self.clauses.get(key, "")

    def tau_b(self, alpha_pr_py: float) -> float:
        """τb of Eq 6.10.263 at αPr / Py."""
        return tau_b(alpha_pr_py, self.tau_limit, self.tau_factor)

    def flexural_stiffness(self, pr: float, py: float) -> float:
        """EI* / EI for B1 at Pr (compression positive) and Py [N]: f_b τb (τb = 1 with the
        additive notional load); 1.0 outside the direct analysis method."""
        if not self.direct:
            return 1.0
        if self.tau == "additive" or py <= 0:
            return self.flexural_factor
        return self.flexural_factor * self.tau_b(self.alpha * max(pr, 0.0) / py)


def tau_b(alpha_pr_py: float, limit: float = 0.5, factor: float = 4.0) -> float:
    """τb = 1.0 for αPr / Py <= ``limit``, else ``factor`` (αPr/Py)(1 - αPr/Py), at least 0
    (Eq 6.10.263 with the pack's ``tauLimit`` and ``tauFactor``)."""
    r = max(alpha_pr_py, 0.0)
    if r <= limit:
        return 1.0
    return max(0.0, min(1.0, factor * r * (1 - r)))


def _table() -> Any | None:
    from saengine.fem.notional_loads import stability_table

    return stability_table()


def max_drift_ratio(drift: dict[str, Any] | None) -> tuple[float | None, str | None]:
    """The largest storey Δ2nd / Δ1st of :func:`saengine.fem.second_order.
    drift_amplification`'s cases, and its case."""
    best: tuple[float | None, str | None] = (None, None)
    for case in (drift or {}).get("cases", []):
        ratio = case.get("maxRatio")
        if ratio is not None and math.isfinite(ratio) and (best[0] is None or ratio > best[0]):
            best = (float(ratio), str(case.get("case")))
    return best


def stability_of(
    settings: Any,
    direct_model: bool,
    drift: dict[str, Any] | None = None,
) -> Stability:
    """The stability method of a design run: ``settings.analysis.notionalLoads``, the direct
    analysis method when the analysis model was derived for it (``direct_model``,
    :func:`saengine.fem.second_order.is_direct_analysis`: the design follows the model, with
    a note when the settings say otherwise), and ``drift`` the drift ratios of the run."""
    analysis = getattr(settings, "analysis", None)
    chosen = getattr(analysis, "notionalLoads", "none") or "none"
    table = _table()
    out = Stability(method=chosen)
    out.drift_ratio, out.drift_case = max_drift_ratio(drift)
    if table is None:
        out.method = "none"
        out.notes.append(
            "steel stability: the code pack has no steel stability rules; the members take K "
            "from their bracing and no stability method is checked"
        )
        return out
    out.alpha = float(table.alpha.lrfd)
    out.clauses = dict(table.sources)
    out.first_order_axial = float(table.limits.firstOrderAxialMax)
    if direct_model and chosen != DIRECT_ANALYSIS:
        out.notes.append(
            "steel stability: the analysis model was derived for the direct analysis method; "
            "the design follows it (run the analysis again for the method now set)"
        )
        out.method = DIRECT_ANALYSIS
    elif chosen == DIRECT_ANALYSIS and not direct_model:
        out.notes.append(
            "steel stability: the direct analysis method is set but the analysis model has no "
            "reduced steel stiffness (run the analysis again); the members take K from their "
            "bracing"
        )
        out.method = "secondOrder"
    da = table.directAnalysis
    if out.method == DIRECT_ANALYSIS and da is None:
        out.notes.append(
            "steel stability: the code pack does not cover the direct analysis method; the "
            "members take K from their bracing"
        )
        out.method = "none"
    required = float(table.limits.directAnalysisRequiredAbove)
    if out.method == DIRECT_ANALYSIS:
        out.unit_k = float(da.effectiveLengthFactor)
        out.flexural_factor = float(da.flexuralStiffnessFactor)
        out.tau = getattr(analysis, "directAnalysisTau", "additive") or "additive"
        out.tau_limit = float(da.tauLimit)
        out.tau_factor = float(da.tauFactor)
        out.p_small_delta = float(da.pSmallDeltaLimit)
        if getattr(analysis, "directAnalysisNotional", "allCombinations") == "gravityOnly":
            out.drift_limit = float(da.gravityOnlyDriftRatioMax)
            out.drift_name = "Notional loads in the gravity-only combinations: Δ2nd/Δ1st"
            out.drift_clause = out.clause("gravityOnly")
    else:
        out.drift_limit = required
        out.drift_name = "Direct analysis not required: Δ2nd/Δ1st"
        out.drift_clause = out.clause("required")
        if out.method == "secondOrder":
            out.unit_k_ratio = float(table.limits.secondOrderUnitKMax)
    if out.drift_ratio is None and out.drift_limit is not None:
        out.notes.append(
            "steel stability: the ratio of second- to first-order drift is not known (it needs "
            "the P-Delta analysis with the first-order reference cases); "
            + (
                "the notional loads in the gravity-only combinations need it at most "
                f"{out.drift_limit:g} ({out.drift_clause})"
                if out.direct
                else f"above {required:g} the direct analysis method is required "
                f"({out.drift_clause})"
            )
        )
    return out


def stability_for_run(
    settings: Any, project: dict[str, Any], out_dir: Any, building: Any = None
) -> Stability:
    """:func:`stability_of` for a design run on the analysis ``project`` with its results in
    ``out_dir``: the drift ratios of its P-Delta run with the first-order reference cases (at
    the storeys of ``building``, when it is a building)."""
    from saengine.fem import second_order

    drift = None
    if second_order.is_second_order(project):
        special = (
            building is not None
            and getattr(building, "source", None) is not None
            and (getattr(building.source, "structure", None))
        )
        stories = getattr(building, "stories", None) if building is not None else None
        levels = sorted({s.elevation / 1e3 for s in stories}) if stories and not special else None
        try:
            drift = second_order.drift_amplification(project, out_dir, levels=levels)
        except (OSError, ValueError, KeyError, TypeError) as error:
            drift = {"cases": [], "notes": [f"drift ratios not read: {error}"]}
    return stability_of(settings, second_order.is_direct_analysis(project), drift)


def method_lines(stability: Stability | None) -> list[str]:
    """The report's method lines of the stability design."""
    if stability is None:
        return []
    ratio = (
        f"; Δ2nd/Δ1st = {stability.drift_ratio:.2f} ({stability.drift_case})"
        if stability.drift_ratio is not None
        else ""
    )
    if stability.direct:
        tau = (
            "τb = 1 for every member with the additive notional load"
            if stability.tau == "additive"
            else f"τb = 1, each column checked for αPr/Py ≤ {stability.tau_limit:g}"
        )
        line = (
            f"Stability: direct analysis method ({stability.clause('method')}): second-order "
            f"(P-Delta) analysis on the reduced steel stiffness ({stability.clause('stiffness')}"
            f"), {tau}; notional loads ({stability.clause('notional')}); every member checked "
            f"with K = {stability.unit_k:g} ({stability.clause('unitK')}); B1 on the reduced "
            f"stiffness ({stability.clause('amplifier')}); P-δ in the lateral displacement "
            f"neglected where αPr < {stability.p_small_delta:g} PeL "
            f"({stability.clause('pSmallDelta')}){ratio}."
        )
        return [line]
    names = {
        "secondOrder": "design by second-order analysis",
        "firstOrder": "design by first-order analysis",
    }
    what = names.get(stability.method, "no stability design method set")
    if stability.drift_limit is None:
        return []
    line = (
        f"Stability: {what}; the direct analysis method is required where Δ2nd/Δ1st > "
        f"{stability.drift_limit:g} ({stability.clause('required')}){ratio}."
    )
    return [line]


def _row(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    scale: float,
    combination: str | None,
    note: str,
    clause: str,
    flag: bool = False,
) -> dict[str, Any]:
    """A check in :func:`saengine.design.steel.members.check_member`'s format."""
    if capacity > 0:
        u = demand / capacity
    else:
        u = 0.0 if demand <= 0 else math.inf
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": name,
        "demand": round(float(demand) / scale, 2),
        "capacity": round(float(capacity) / scale, 2),
        "unit": unit,
        "utilisation": u,
        "combination": combination,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": flag,
        "clause": clause,
    }


def member_checks(
    stability: Stability | None,
    shape: Any,
    steel: Any,
    stations: Sequence[Any],
    length: float,
    kind: str,
) -> list[dict[str, Any]]:
    """The stability checks of one steel member (module docstring): ``shape`` and ``steel`` as
    :func:`saengine.design.steel.members.check_member` takes them, ``stations`` its
    combinations' forces (P compression positive, N), ``length`` the member length [m]."""
    if stability is None:
        return []
    checks: list[dict[str, Any]] = []
    # The largest compression of the member and its combination.
    pr, combination = 0.0, None
    for st in stations:
        for value in st.P:
            if float(value) > pr:
                pr, combination = float(value), st.combination
    apr = stability.alpha * pr
    py = steel.fy * shape.area
    column = kind == "column"
    if stability.direct and column and pr > 0:
        if stability.p_small_delta is not None and length > 0:
            el = steel.e * min(shape.ix, shape.iy)
            pel = math.pi**2 * el / (length * 1e3) ** 2
            checks.append(
                _row(
                    f"P-δ neglected in the sway: αPr < {stability.p_small_delta:g} PeL",
                    apr,
                    stability.p_small_delta * pel,
                    "kN",
                    1e3,
                    combination,
                    f"PeL = π² E I / L² = {pel / 1e3:.0f} kN (weaker plane, nominal E I, L = "
                    f"{length * 1e3:.0f} mm); the analysis has one element per storey, so P-δ "
                    "is not in the lateral displacement",
                    stability.clause("pSmallDelta"),
                )
            )
        if stability.tau == "checked":
            ratio = apr / py if py > 0 else math.inf
            checks.append(
                _row(
                    f"τb = 1 in the analysis: αPr ≤ {stability.tau_limit:g} Py",
                    apr,
                    stability.tau_limit * py,
                    "kN",
                    1e3,
                    combination,
                    f"αPr/Py = {ratio:.2f}, τb = {stability.tau_b(ratio):.2f}; above the "
                    "limit τb < 1 and the stiffness of the analysis is too high: use τb = 1 "
                    "with the additive notional load, or a heavier section",
                    stability.clause("tau"),
                )
            )
    if stability.drift_limit is not None and stability.drift_ratio is not None:
        checks.append(
            _row(
                f"{stability.drift_name} ≤ {stability.drift_limit:g}",
                stability.drift_ratio,
                stability.drift_limit,
                "",
                1.0,
                None,
                f"largest storey ratio of second- to first-order drift, case "
                f"{stability.drift_case}"
                + (
                    "; above the limit apply the notional loads in every combination"
                    if stability.direct
                    else "; above the limit design by the direct analysis method"
                ),
                stability.drift_clause,
            )
        )
    if (
        column
        and stability.unit_k_ratio is not None
        and stability.drift_ratio is not None
        and pr > 0
    ):
        checks.append(
            _row(
                f"K = 1 by second-order analysis: Δ2nd/Δ1st ≤ {stability.unit_k_ratio:g}",
                stability.drift_ratio,
                stability.unit_k_ratio,
                "",
                1.0,
                None,
                "above the limit the columns of moment frames need K from a sidesway "
                "buckling analysis (set K per member)",
                stability.clause("secondOrderUnitK"),
                flag=True,
            )
        )
    return checks


__all__ = [
    "DIRECT_ANALYSIS",
    "Stability",
    "max_drift_ratio",
    "member_checks",
    "method_lines",
    "stability_for_run",
    "stability_of",
    "tau_b",
]

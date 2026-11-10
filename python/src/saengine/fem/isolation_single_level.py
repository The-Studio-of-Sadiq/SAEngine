"""The single-level isolation design (alpha 9 P6): one earthquake level, the isolation
system's displacement with its lower- and upper-bound properties, the forces of the governing
bound, the checks. The code pack picks it with ``isolation.procedure.method`` "singleLevel"
(:func:`saengine.fem.isolation.design` hands over); its values and clauses are the pack's.

How it works (SI inside: m, N, s; module notes of :mod:`saengine.fem.isolation` for the
shared pieces):

- **Displacement**: ``D = Sa(T) g T² / (4π² B)`` with ``T = 2π √(W / (k g))``, Sa from the
  design spectrum (R and I of the pack's isolation spectrum) × ``spectrum.mceFactor`` (the
  earthquake level of the design: the maximum considered earthquake, or the design earthquake
  where the factor is 1) at the effective period, solved by iteration on the effective
  stiffness k and damping β, once with the lower- and once with the upper-bound properties.
  In the constant-velocity range ``Sa = S1 / T`` and this is ``g S1 T / (4π² B)``. The
  displacement is the larger of the two bounds'.
- **Total displacement**: by ``torsion.method`` (``rigidDeck`` or ``periodRatio``), at least
  ``torsion.minimumFactor`` × D; the units' demand × ``procedure.displacementFactor`` (γx).
- **Forces**: ``Vb = k D`` of the bound that gives the larger; the unreduced force above the
  isolators ``Vst = Vb (Ws/W)^(1 − c β)`` (Ws the weight above the base level, c the pack's
  ``shearExponent``); ``Vs = Vst / RI`` (RI from R as in the default procedure), at least the
  pack's ``minima``: the fixed-base force of Ws at the effective period, the factored wind and
  Vst of the activation force. Distributed ``Fx = Vs wx hx^k / Σ wi hi^k`` over the levels
  above the base level with ``k = distributionFactor β Tfb`` (``dampingPeriod``) or the
  distribution exponent; the base level ``(Vb − Vst) / RI`` (``baseLevelForce``).
- **Checks**: the restoring force at the pack's displacement, the units' displacement capacity
  against γx × the total displacement, the overturning at the interface under Vb, the units'
  stability (the entered tested vertical load against the average gravity load per unit), the
  conditions of the equivalent lateral force procedure.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from saengine.fem import isolation as iso


def _solve(curves: list[iso.Curve], weight: float, sa: Callable[[float], float]) -> dict[str, Any]:
    """The displacement D [m] of the system ``curves`` under the spectrum ``sa`` (period [s]
    -> g), by the iteration of :func:`saengine.fem.isolation.solve_displacement`."""

    def at(d: float) -> dict[str, Any]:
        k = iso.system_stiffness(curves, d)
        period = iso.effective_period(weight, k)
        beta = iso.system_damping(curves, d)
        acc = sa(period)
        b = iso.damping_coefficient(100 * beta)
        return {
            "D": iso.spectral_displacement(acc, period, b),
            "T": period,
            "k": k,
            "beta": beta,
            "B": b,
            "Sa": acc,
        }

    d, converged = 0.05, False
    for _ in range(300):
        new = at(d)["D"]
        if abs(new - d) <= 1e-7 + 1e-5 * d:
            d, converged = new, True
            break
        d = 0.5 * (d + new)
    found = at(d)
    found["D"] = d
    found["converged"] = converged
    return found


def shear_above(vb: float, weight_above: float, weight: float, beta: float, c: float) -> float:
    """``Vst = Vb (Ws/W)^(1 − c β)``: the unreduced force above the isolation system [N]
    (``beta`` a fraction of critical)."""
    if weight <= 0 or weight_above <= 0:
        return 0.0
    return vb * (weight_above / weight) ** (1.0 - c * beta)


def distribution_exponent(beta: float, fixed_period: float) -> float:
    """The vertical distribution exponent k: ``distributionFactor·β·Tfb`` (``dampingPeriod``)
    or the table's exponent (``fixed``)."""
    t = iso._table()
    proc = t.procedure
    if proc.distribution == "dampingPeriod" and proc.distributionFactor:
        return float(proc.distributionFactor) * beta * fixed_period
    return float(t.distribution.exponent)


def distribute_above(levels: list[tuple[float, float]], shear: float, k: float) -> list[float]:
    """``Fx = Vs wx hx^k / Σ wi hi^k`` over the levels above the base level (h > 0)."""
    parts = [w * h**k if h > 1e-6 else 0.0 for h, w in levels]
    total = sum(parts)
    return [shear * p / total if total else 0.0 for p in parts]


def _bound(found: dict[str, Any], k_max: float) -> dict[str, Any]:
    return {
        "D_mm": found["D"] * 1e3,
        "T": found["T"],
        "beta": found["beta"],
        "B": found["B"],
        "Sa": found["Sa"],
        "kMin_kNm": found["k"] / 1e3,
        "kMax_kNm": k_max / 1e3,
    }


def design(
    units: list[iso.Unit],
    levels: list[tuple[float, float]],
    centre: tuple[float, float],
    *,
    site_class: str,
    z: Any,
    r: dict[str, float],
    fixed_period: dict[str, float],
    wind_shear: dict[str, float],
    storeys: int,
    accidental_share: float,
    has_time_histories: bool = False,
    spectrum: Callable[[float], float] | None = None,
    fixed_source: str = "",
) -> dict[str, Any]:
    """The single-level isolation design of ``units`` (module notes), the same summary as
    :func:`saengine.fem.isolation.design` with ``"procedure": "singleLevel"``; "design" and
    "maximum" both hold the one level's values (of the bound that gives the displacement),
    "bounds" both bounds'. ``spectrum``: Sa [g] at a period of the design's earthquake level
    (default: the pack's isolation spectrum × mceFactor at ``site_class``, ``z``)."""
    from saengine.fem import loads as fl

    t = iso._table()
    proc = t.procedure
    cl = iso.clauses()
    sa = spectrum or (lambda period: iso.spectral_acceleration(period, site_class, z, mce=True))
    weight = sum(w for _, w in levels)
    weight_above = sum(w for h, w in levels if h > 1e-6)
    notes: list[str] = []
    lower = [u.lower for u in units]
    upper = [u.upper for u in units]
    nominal = [u.nominal for u in units]

    found = {"lower": _solve(lower, weight, sa), "upper": _solve(upper, weight, sa)}
    for name, item in found.items():
        if not item["converged"]:
            notes.append(
                f"D ({name} bound): the iteration on the effective stiffness did not converge"
            )
    curves = {"lower": lower, "upper": upper}
    displacement_bound = max(found, key=lambda b: found[b]["D"])
    dm = found[displacement_bound]["D"]
    shear = {b: iso.system_stiffness(curves[b], found[b]["D"]) * found[b]["D"] for b in found}
    force_bound = max(shear, key=lambda b: shear[b])
    vb = shear[force_bound]
    beta = found[force_bound]["beta"]
    period_m = found[force_bound]["T"]
    k_max = iso.system_stiffness(upper, found["upper"]["D"])

    # ── total displacement ──
    if t.torsion.method == "periodRatio":
        totals = iso.period_ratio_displacements(
            units, centre, dm, accidental_share, t.torsion.minimumFactor
        )
    else:
        totals = iso.total_displacements(units, centre, dm, accidental_share)
        if t.torsion.minimumFactor:
            for axis in ("X", "Y"):
                row = totals[axis]
                floor = float(t.torsion.minimumFactor) * dm
                row["units"] = {n: max(v, floor) for n, v in row["units"].items()}
                row["total"] = max(row["total"], floor)
                row["factor"] = row["total"] / dm if dm else 1.0
    dtm = max(totals["X"]["total"], totals["Y"]["total"])
    gamma = float(proc.displacementFactor)

    # ── forces ──
    c = float(proc.shearExponent)
    vst = shear_above(vb, weight_above, weight, beta, c)
    activation_upper = sum(u.activation() for u in units)
    activation_nominal = sum(cv.fy for cv in nominal)
    if proc.activationUpperBound:
        activation = max(activation_upper, t.forces.activationFactor * activation_nominal)
    else:
        activation = t.forces.activationFactor * activation_upper
    forces: dict[str, Any] = {}
    for axis in ("X", "Y"):
        ri = iso.reduction_factor(r[axis])
        r_fixed = ri if t.forces.fixedBaseR == "isolated" else r[axis]
        available = {
            "fixedBase": fl.design_acceleration(
                period_m, site_class, z, t.forces.importance, r_fixed, None
            )
            * weight_above,
            "wind": wind_shear.get(axis, 0.0),
            "activation": shear_above(activation, weight_above, weight, beta, c),
        }
        minima = {key: available[key] for key in proc.minima}
        formula = vst / ri
        vs = max(formula, *minima.values()) if minima else formula
        governs = "formula" if vs == formula or not minima else max(minima, key=lambda k: minima[k])
        k_exp = distribution_exponent(beta, fixed_period.get(axis, 0.0))
        spread = distribute_above(levels, vs, k_exp)
        forces[axis] = {
            "R": r[axis],
            "RI": ri,
            "Vb_kN": vb / 1e3,
            "Vst_kN": vst / 1e3,
            "VsFormula_kN": formula / 1e3,
            "minima_kN": {k: v / 1e3 for k, v in minima.items()},
            "Vs_kN": vs / 1e3,
            "governs": governs,
            "k": k_exp,
            "baseLevel_kN": (vb - vst) / ri / 1e3 if proc.baseLevelForce else None,
            "levels": [
                {"h": h, "w_kN": w / 1e3, "F_kN": f / 1e3}
                for (h, w), f in zip(levels, spread, strict=True)
                if h > 1e-6
            ],
        }

    # ── checks ──
    checks: list[dict[str, Any]] = []

    def check(key: str, label: str, value: Any, limit: Any, ok: bool | None) -> None:
        checks.append(
            {"id": key, "label": label, "value": value, "limit": limit, "ok": ok,
             "clause": cl.get(key, "")}
        )  # fmt: skip

    restoring_ok: bool | None = None
    if t.restoring is not None:
        share = t.restoring.atShare
        at = dm if t.restoring.at == "maximum" else dtm
        gain = sum(cv.force(at) - cv.force(share * at) for cv in lower)
        restoring_ok = gain >= t.restoring.forceShare * weight - 1e-9
        check(
            "restoring",
            f"Restoring force: F(D) - F({share:g} D) at D = {at * 1e3:.0f} mm [kN]",
            round(gain / 1e3, 3),
            round(t.restoring.forceShare * weight / 1e3, 3),
            restoring_ok,
        )
    else:
        check("restoring", "Restoring force (no rule in the code pack)", None, None, None)
    demand = gamma * dtm
    capacities = [u.spec.displacementCapacity for u in units]
    restraint_ok: bool | None = None
    if all(cap is not None for cap in capacities):
        least = min(float(cap) for cap in capacities) / 1e3  # type: ignore[arg-type]
        restraint_ok = least >= demand - 1e-9
        check(
            "restraint",
            "Displacement capacity of the units [mm] at least "
            + (f"{gamma:g} × " if gamma != 1 else "")
            + "the total displacement",
            round(least * 1e3, 1),
            round(demand * 1e3, 1),
            restraint_ok,
        )
    else:
        check(
            "restraint",
            "Displacement capacity of the units at least the total displacement",
            None,
            round(demand * 1e3, 1),
            None,
        )
    xs = [u.x for u in units]
    ys = [u.y for u in units]
    overturning_ok = True
    k_vb = distribution_exponent(beta, max(fixed_period.values(), default=0.0))
    for axis, lever in (
        ("X", min(centre[0] - min(xs), max(xs) - centre[0])),
        ("Y", min(centre[1] - min(ys), max(ys) - centre[1])),
    ):
        moment = sum(
            f * h for (h, _), f in zip(levels, distribute_above(levels, vb, k_vb), strict=True)
        )
        factor = weight * max(lever, 0.0) / moment if moment > 0 else math.inf
        ok = factor >= t.overturning.minimumFactor - 1e-9
        overturning_ok = overturning_ok and ok
        check(
            "overturning",
            f"Overturning at the isolation interface along {axis} (Vb): factor of safety",
            round(factor, 3) if math.isfinite(factor) else None,
            t.overturning.minimumFactor,
            ok,
        )
    vertical = [u.spec.verticalCapacity for u in units]
    per_unit = weight / max(len(units), 1)
    stability_ok: bool | None = None
    if all(v is not None for v in vertical):
        least_v = min(float(v) for v in vertical) * 1e3  # type: ignore[arg-type]
        stability_ok = least_v >= per_unit - 1e-9
        check(
            "stability",
            "Tested vertical load of the units at the total displacement [kN] at least the "
            "average gravity load per unit (check the largest column reaction with the "
            "earthquake)",
            round(least_v / 1e3, 1),
            round(per_unit / 1e3, 1),
            stability_ok,
        )
    else:
        check("stability", "Tested vertical load of the units (not entered)", None, None, None)

    # ── where the equivalent lateral force procedure is permitted ──
    lim = t.staticLimits
    height = max((h for h, _ in levels), default=0.0)
    t_fixed = max(fixed_period.values(), default=0.0)
    conditions: list[dict[str, Any]] = [
        {"id": "1", "label": f"Site class {site_class} in {', '.join(lim.siteClasses)}",
         "ok": site_class in lim.siteClasses},
    ]  # fmt: skip
    if lim.maxStoreys is not None or lim.maxHeight is not None:
        ok = (lim.maxStoreys is None or storeys <= lim.maxStoreys) and (
            lim.maxHeight is None or height <= lim.maxHeight + 1e-9
        )
        conditions.append(
            {
                "id": "2",
                "label": f"{storeys} storeys"
                + (f" (at most {lim.maxStoreys})" if lim.maxStoreys is not None else "")
                + f", {height:.2f} m"
                + (f" (at most {lim.maxHeight:g} m)" if lim.maxHeight is not None else "")
                + " above the isolation interface",
                "ok": ok,
            }
        )
    conditions += [
        {"id": "3", "label": f"T = {period_m:.2f} s at most {lim.maxPeriodM:g} s",
         "ok": max(found["lower"]["T"], found["upper"]["T"]) <= lim.maxPeriodM + 1e-9},
        {"id": "4", "label": f"T = {found['upper']['T']:.2f} s more than {lim.periodRatio:g} × "
         f"the fixed-base period {t_fixed:.2f} s{f' ({fixed_source})' if fixed_source else ''}",
         "ok": found["upper"]["T"] > lim.periodRatio * t_fixed if t_fixed > 0 else None},
        {"id": "5", "label": "Regular configuration above the isolation system (checked with "
         "the irregularities of the response spectrum design)", "ok": None},
    ]  # fmt: skip
    if lim.stiffnessRatio is not None:
        k_20 = iso.system_stiffness(nominal, lim.stiffnessAtShare * dm)
        k_d = iso.system_stiffness(nominal, dm)
        conditions.append(
            {
                "id": "6a",
                "label": f"k at D {k_d / 1e3:.0f} kN/m more than {lim.stiffnessRatio:.3g} × k at "
                f"{lim.stiffnessAtShare:g} D {k_20 / 1e3:.0f} kN/m",
                "ok": k_d > lim.stiffnessRatio * k_20,
            }
        )
    conditions += [
        {"id": "6b", "label": "Restoring force", "ok": restoring_ok},
        {"id": "6c", "label": "No restraint below the total displacement", "ok": restraint_ok},
    ]
    if lim.maxPlanDimension is not None and xs:
        plan = max(max(xs) - min(xs), max(ys) - min(ys))
        conditions.append(
            {
                "id": "7",
                "label": f"Largest plan dimension {plan:.1f} m at most {lim.maxPlanDimension:g} m",
                "ok": plan <= lim.maxPlanDimension + 1e-9,
            }
        )
    if lim.minVerticalRatio is not None:
        kv = sum(float(u.spec.verticalStiffness) * 1e3 for u in units)
        k_eff = iso.system_stiffness(lower, dm)
        ratio = kv / k_eff if k_eff > 0 else math.inf
        conditions.append(
            {
                "id": "8",
                "label": f"Vertical over effective horizontal stiffness {ratio:.0f} at least "
                f"{lim.minVerticalRatio:g}",
                "ok": ratio >= lim.minVerticalRatio - 1e-9,
            }
        )
    if lim.maxDamping is not None:
        b_pct = 100 * found[displacement_bound]["beta"]
        conditions.append(
            {
                "id": "9",
                "label": f"Effective damping {b_pct:.1f} % at most {lim.maxDamping:g} %",
                "ok": b_pct <= lim.maxDamping + 1e-9,
            }
        )
    failed = [cond for cond in conditions if cond["ok"] is False]
    static_permitted = not failed
    if failed:
        notes.append(
            "the equivalent lateral force procedure is not permitted for this isolated building "
            "(not met: "
            + "; ".join(cond["label"] for cond in failed)
            + f", {cl.get('staticLimits', '')}): use the response spectrum analysis"
            + (" or a time history" if has_time_histories else "")
        )
    else:
        notes.append(
            "the equivalent lateral force procedure is permitted if the structure above the "
            f"isolators is regular ({cl.get('staticLimits', '')})"
        )
    if gamma != 1:
        notes.append(
            f"the units' displacements are taken × {gamma:g} for their capacity "
            f"({cl.get('displacementFactor', '')})"
        )

    # ── the response spectrum's damping ──
    governing = found[displacement_bound]
    rules = t.spectrumAnalysis
    modal = min(100 * governing["beta"], rules.maxModalDamping)
    spectrum_rows = {
        "modalDamping": modal,
        "B": iso.damping_coefficient(modal),
        "dampedFrom": rules.dampedFromShare * governing["T"],
        "orthogonalShare": rules.orthogonalShare,
        "note": rules.note,
    }

    # ── requirements, testing and review ──
    statuses = {
        "restoring": restoring_ok,
        "restraint": restraint_ok,
        "overturning": overturning_ok,
        "stability": stability_ok,
    }
    by_id = {"4": restoring_ok, "5": restraint_ok, "7": overturning_ok}
    bounded = all(
        iso.property_factors(u.spec)[0] < 1 or iso.property_factors(u.spec)[1] > 1 for u in units
    )
    requirements = []
    for item in t.requirements:
        status: bool | None = None
        if item.check == "computed":
            status = statuses.get(item.computes) if item.computes else by_id.get(item.id)
        elif item.check == "bounds":
            status = bounded
        requirements.append({"id": item.id, "text": item.text, "check": item.check, "ok": status})
    if not bounded:
        notes.append(
            "property variation: some isolator types have no property bounds (bound factors 1 "
            "and no λ factors): enter the variation of the tested properties"
        )
    testing = iso._test_programme(
        units, weight, wind_shear, {"DD": dm, "DM": dm, "DTD": dtm, "DTM": dtm}
    )
    one = _bound(governing, k_max)
    summary: dict[str, Any] = {
        "schema": iso.SCHEMA,
        "available": True,
        "procedure": "singleLevel",
        "weight_kN": weight / 1e3,
        "weightAbove_kN": weight_above / 1e3,
        "centreOfMass": {"x": centre[0], "y": centre[1]},
        "centreOfRigidity": totals.pop("centreOfRigidity"),
        "design": dict(one),
        "maximum": dict(one),
        "governing": {"displacement": displacement_bound, "force": force_bound, "D_mm": dm * 1e3},
        "bounds": {
            name: _bound(item, iso.system_stiffness(curves[name], item["D"]))
            for name, item in found.items()
        },
        "total": {
            "DTD_mm": dtm * 1e3,
            "DTM_mm": dtm * 1e3,
            "demand_mm": demand * 1e3,
            "displacementFactor": gamma,
            "byAxis": {
                a: {
                    "DTD_mm": totals[a]["total"] * 1e3,
                    "DTM_mm": totals[a]["total"] * 1e3,
                    "eccentricity_m": totals[a]["eccentricity"],
                    **({"PT": totals[a]["PT"]} if "PT" in totals[a] else {}),
                }
                for a in ("X", "Y")
            },
        },
        "forces": forces,
        "drift": {
            "Cd": {a: forces[a]["RI"] for a in ("X", "Y")},
            "importance": t.forces.importance,
            "limits": {
                "static": t.drift.static,
                "spectrum": t.drift.spectrum,
                "history": t.drift.history,
            },
        },
        "checks": checks,
        "staticAnalysis": {"permitted": static_permitted, "conditions": conditions},
        "spectrum": spectrum_rows,
        "requirements": requirements,
        "testing": testing,
        "review": list(t.review),
        "units": [
            {
                "column": u.column,
                "type": u.type,
                "node": u.node,
                "x": u.x,
                "y": u.y,
                "kind": u.spec.kind,
                "lambda": list(iso.property_factors(u.spec)),
                "kDmin_kNm": u.lower.stiffness(dm) / 1e3,
                "kDmax_kNm": u.upper.stiffness(found["upper"]["D"]) / 1e3,
                "DTD_mm": max(totals["X"]["units"][u.node], totals["Y"]["units"][u.node]) * 1e3,
                "DTM_mm": max(totals["X"]["units"][u.node], totals["Y"]["units"][u.node]) * 1e3,
                "capacity_mm": u.spec.displacementCapacity,
                "verticalCapacity_kN": u.spec.verticalCapacity,
            }
            for u in units
        ],
        "notes": notes,
        "clauses": cl,
    }
    summary["history"] = iso.history_criteria(
        {"design": governing, "maximum": governing, "forces": {"X": forces["X"]}}
    )
    if proc.note:
        notes.append(proc.note)
    return summary

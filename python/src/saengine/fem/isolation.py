"""Seismically isolated buildings (B37): the isolation system under the columns, its
displacements and forces, the forces above and below it, the checks, the prototype test
programme and the design review.

Every value and clause reference comes from the code pack in force (its ``isolation`` table);
a pack without that table does not cover isolation, and the columns stay fixed. With BNBC 2020
it is Part 6 Sec 2.5.16 (pp. 652-666).

How it works (SI inside: m, N, s):

- **Isolators.** A column type with a :class:`saengine.library.objects.SeismicIsolator` puts an
  isolator under the base of each of its columns that stands on a support. Each unit is a
  bilinear curve (Qd, Kd, Dy, from the prototype tests): at a displacement D the effective
  stiffness is the secant ``k = F(D)/D`` and the effective damping the loop area
  ``β = EDC / (2π k D²)``, ``EDC = 4 Qd (D - Dy)`` (the code's own definitions of the tested
  properties, Sec 2.5.16.4). The property variation over the life (requirement 1) enters as a
  lower- and an upper-bound factor on Qd and Kd: the displacements are found with the lower
  bound (``kDmin``, ``kMmin``), the forces with the upper bound (``kDmax``, ``kMmax``).
- **Displacements** (Eqs 6.2.62-6.2.65, Table 6.2.24): ``D = Sa g T² / (4π² B)``,
  ``T = 2π √(W / (k_min g))``, Sa from the design spectrum with the pack's R, I (1, 1) at the
  5 % reference damping; the maximum considered earthquake is the pack's ``mceFactor`` × the
  design spectrum. Since k and β depend on D the equations are solved by iteration (the
  equivalent linear procedure the code describes in Sec 2.5.16.3.1).
- **Total displacements** (Sec 2.5.16.2.1, method ``rigidDeck``): the deck above the isolators
  turns rigidly about the isolators' centre of rigidity; with the eccentricity e (the centre of
  mass from it plus the seismic table's accidental share of the isolators' extent across the
  motion) a unit at a distance r across the motion moves ``D (1 + K e r / Kθ)``,
  ``Kθ = Σ k_i r_i²`` about the centre of rigidity.
- **Forces** (Eqs 6.2.66-6.2.67): ``Vb = kDmax DD`` below the isolators,
  ``Vs = kDmax DD / RI`` above, RI from the system's R; Vs at least the fixed-base force at
  TD, the factored wind base shear and the activation force × 1.5. Distributed by Eq 6.2.68
  (``Fx = Vs wx hx / Σ wi hi``, heights above the isolation interface).
- **The analysis model.** Each isolated column base gets a ``ZeroLength`` element to a fixed
  ground node: horizontal springs of the unit's upper-bound effective stiffness at DD (the
  linear model of Sec 2.5.16.3 takes the maximum effective stiffness), the vertical stiffness;
  the base stays restrained in rotation (an isolator under a stiff base slab or plinth). The
  equivalent static cases EX, EY (and the eccentric ones) are re-distributed to Eq 6.2.68 with
  Vs; with the response spectrum on, its spectrum becomes the isolated one (R = RI, I = 1, the
  isolation damping on the long periods).
- **Response spectrum** (Sec 2.5.16.3.1, :func:`spectrum_displacements`, read by
  :mod:`saengine.fem.seismic_design`): the isolators' displacements from RX, RY at 100 % + 30 %,
  as vectors, elastic (× RI); the drift with Cd = RI and I = 1 against the pack's limit.
- **Time history** (Sec 2.5.16.3.2): :func:`history_criteria` gives the record count, the
  scaling range and factor that a nonlinear time-history run of the isolated building must
  meet (the hook for the nonlinear time history engine; this module does not run records).
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

G = 9.80665  # m/s²
#: The isolation design beside the analysis model (``08 FEM/isolation.json``).
ISOLATION_FILE = "isolation.json"
SCHEMA = "saengine.isolation/1"
#: Name suffix of the isolator elements of the analysis model.
ELEMENT_SUFFIX = "/isolator"
#: Static earthquake cases by direction (the eccentric ones scale with their source case).
_STATIC_CASES = {"X": ("EX", "EXP", "EXN"), "Y": ("EY", "EYP", "EYN")}


# ─────────────────────────────────────── pack access ───────────────────────────────────────


def covered() -> bool:
    """Whether the code pack in force covers isolated buildings (has an ``isolation`` table)."""
    try:
        return bool(code_context.current().has("isolation"))
    except Exception:  # noqa: BLE001 - a broken pack covers nothing
        return False


def _table() -> Any:
    return code_context.table("isolation")


def clauses() -> dict[str, str]:
    """The clause references of the isolation design (the pack's ``isolation.sources``)."""
    return dict(_table().sources)


# ─────────────────────────────────────── one isolator ───────────────────────────────────────


@dataclass(frozen=True)
class Curve:
    """A bilinear isolator curve: characteristic strength ``qd`` [N], post-yield stiffness
    ``kd`` [N/m], yield displacement ``dy`` [m]."""

    qd: float
    kd: float
    dy: float

    @property
    def fy(self) -> float:
        return self.qd + self.kd * self.dy

    def force(self, d: float) -> float:
        """The force at displacement ``d`` on the loading branch [N]."""
        d = abs(d)
        return self.fy / self.dy * d if d <= self.dy else self.qd + self.kd * d

    def stiffness(self, d: float) -> float:
        """The effective (secant) stiffness at ``d`` [N/m]."""
        d = abs(d)
        return self.fy / self.dy if d <= self.dy else self.force(d) / d

    def loop(self, d: float) -> float:
        """The energy dissipated in one cycle to ±d (the loop area) [J]."""
        d = abs(d)
        return 4.0 * self.qd * (d - self.dy) if d > self.dy else 0.0

    def scaled(self, factor: float) -> Curve:
        """Qd and Kd × ``factor`` (a property bound)."""
        return Curve(self.qd * factor, self.kd * factor, self.dy)


def curve_of(spec: Any) -> Curve:
    """The bilinear curve of a :class:`~saengine.library.objects.SeismicIsolator` (kN, kN/m, mm
    to N, N/m, m)."""
    return Curve(
        float(spec.characteristicStrength) * 1e3,
        float(spec.postYieldStiffness) * 1e3,
        float(spec.yieldDisplacement) / 1e3,
    )


@dataclass
class Unit:
    """An isolator of the model: its column, its node (the column base), plan position [m]
    and properties."""

    column: str
    type: str
    node: int
    x: float
    y: float
    spec: Any

    @property
    def nominal(self) -> Curve:
        return curve_of(self.spec)

    @property
    def lower(self) -> Curve:
        return self.nominal.scaled(float(self.spec.lowerBoundFactor))

    @property
    def upper(self) -> Curve:
        return self.nominal.scaled(float(self.spec.upperBoundFactor))

    def activation(self) -> float:
        """The force that fully activates the unit [N] (upper bound)."""
        if self.spec.activationForce:
            return float(self.spec.activationForce) * 1e3
        return self.upper.fy


def system_stiffness(curves: list[Curve], d: float) -> float:
    return sum(c.stiffness(d) for c in curves)


def system_damping(curves: list[Curve], d: float) -> float:
    """The effective damping of the system at ``d`` (fraction of critical)."""
    k = system_stiffness(curves, d)
    if k <= 0 or d <= 0:
        return 0.0
    return sum(c.loop(d) for c in curves) / (2 * math.pi * k * d * d)


# ─────────────────────────────────────── code values ───────────────────────────────────────


def damping_coefficient(damping_percent: float) -> float:
    """BD or BM of the effective damping [%] (the pack's table, linear in between, the end
    values beyond)."""
    points = sorted(_table().dampingCoefficients, key=lambda p: p.damping)
    xs = [p.damping for p in points]
    ys = [p.B for p in points]
    return float(np.interp(damping_percent, xs, ys))


def reduction_factor(r: float) -> float:
    """RI from the system's R: the lesser of ``reductionShare·R`` and ``reductionMax``, but
    not less than ``reductionMin``."""
    f = _table().forces
    return max(min(f.reductionShare * r, f.reductionMax), f.reductionMin)


def spectral_acceleration(period: float, site_class: str, z: float, mce: bool = False) -> float:
    """Sa [g] of the design spectrum with the pack's R and I for isolation (Eq 6.2.34, 5 %
    damping); ``mce``: the maximum considered earthquake (× ``mceFactor``)."""
    from saengine.fem import loads as fl

    s = _table().spectrum
    sa = fl.design_acceleration(period, site_class, z, s.importance, s.R, None)
    return sa * (s.mceFactor if mce else 1.0)


def spectral_displacement(sa: float, period: float, b: float) -> float:
    """D = Sa g T² / (4π² B) [m] (Eqs 6.2.62, 6.2.64)."""
    return sa * G * period**2 / (4 * math.pi**2 * b)


def effective_period(weight: float, k: float) -> float:
    """T = 2π √(W / (k g)) [s] (Eqs 6.2.63, 6.2.65)."""
    return 2 * math.pi * math.sqrt(weight / (k * G)) if k > 0 else math.inf


def solve_displacement(
    curves: list[Curve],
    weight: float,
    site_class: str,
    z: float,
    mce: bool = False,
    design_period: float | None = None,
) -> dict[str, Any]:
    """The displacement D [m] of the isolation system (lower-bound ``curves``) for the design
    (or with ``mce`` the maximum considered) earthquake, by iteration: D gives k and β, they
    give T and B, and these D. ``design_period``: TD, where the pack reads SaM at TD."""
    rule = _table().spectrum.mcePeriod

    def at(d: float) -> dict[str, Any]:
        k = system_stiffness(curves, d)
        period = effective_period(weight, k)
        beta = system_damping(curves, d)
        sa = spectral_acceleration(period, site_class, z, mce)
        if mce and design_period is not None and rule != "maximum":
            at_design = spectral_acceleration(design_period, site_class, z, True)
            sa = at_design if rule == "design" else max(sa, at_design)
        b = damping_coefficient(100 * beta)
        return {
            "D": spectral_displacement(sa, period, b),
            "T": period,
            "k": k,
            "beta": beta,
            "B": b,
            "Sa": sa,
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


def total_displacements(
    units: list[Unit], centre: tuple[float, float], d: float, share: float
) -> dict[str, dict[str, Any]]:
    """The total displacement per direction (method ``rigidDeck``, module notes): ``{"X":
    {"total", "eccentricity", "factor", "units": {node: total}}, "Y": ...}`` [m]."""
    ks = [u.lower.stiffness(d) for u in units]
    k = sum(ks)
    xs = np.array([u.x for u in units])
    ys = np.array([u.y for u in units])
    xr = float(np.dot(ks, xs) / k) if k else 0.0
    yr = float(np.dot(ks, ys) / k) if k else 0.0
    polar = float(np.dot(ks, (xs - xr) ** 2 + (ys - yr) ** 2))
    out: dict[str, dict[str, Any]] = {}
    for axis, (actual, across, rel) in {
        "X": (abs(centre[1] - yr), float(ys.max() - ys.min()), ys - yr),
        "Y": (abs(centre[0] - xr), float(xs.max() - xs.min()), xs - xr),
    }.items():
        e = actual + share * across
        theta = k * d * e / polar if polar > 0 else 0.0
        per = {u.node: d + theta * abs(float(r)) for u, r in zip(units, rel, strict=True)}
        total = max(per.values(), default=d)
        out[axis] = {
            "total": total,
            "eccentricity": e,
            "factor": total / d if d else 1.0,
            "units": per,
        }
    out["centreOfRigidity"] = {"x": xr, "y": yr}  # type: ignore[assignment]
    return out


def distribute(levels: list[tuple[float, float]], shear: float) -> list[float]:
    """Eq 6.2.68: ``Fx = Vs wx hx^k / Σ wi hi^k`` for (height above the interface, weight)."""
    k = _table().distribution.exponent
    parts = [w * max(h, 0.0) ** k if h > 0 else 0.0 for h, w in levels]
    total = sum(parts)
    return [shear * p / total if total else 0.0 for p in parts]


def history_criteria(design: dict[str, Any]) -> dict[str, Any]:
    """What a time-history run of the isolated building must meet (Sec 2.5.16.3.2), for the
    nonlinear time history engine: the pairs of records, when the average may be used, the
    period range and factor the average SRSS spectrum is scaled to, and the drift limit."""
    h = _table().history
    td = design["design"]["T"]
    tm = design["maximum"]["T"]
    return {
        "minRecords": h.minRecords,
        "averageFrom": h.averageFrom,
        "periodRange": [h.periodFromShare * td, h.periodToShare * tm],
        "spectrumFactor": h.spectrumFactor,
        "tolerance": h.tolerance,
        "recordDamping": h.recordDamping,
        "pairs": True,
        "displacement": "vector sum of the two components at each time step",
        "driftLimit": _table().drift.history,
        "driftFactor": {"Cd": design["forces"]["X"]["RI"], "importance": 1.0},
        "clause": clauses().get("history", ""),
    }


def check_history_suite(
    periods: list[float],
    average_srss: list[float],
    design: dict[str, Any],
    site_class: str,
    z: float,
) -> dict[str, Any]:
    """Whether the average SRSS spectrum of a suite (``average_srss`` [g] at ``periods`` [s],
    pairs scaled with one factor each) reaches the code's share of the design spectrum over the
    range (:func:`history_criteria`): ``{"ok", "worst": {"period", "ratio"}, "required"}``."""
    c = history_criteria(design)
    low, high = c["periodRange"]
    worst = None
    for t, sa in zip(periods, average_srss, strict=True):
        if t < low - 1e-9 or t > high + 1e-9:
            continue
        target = c["spectrumFactor"] * spectral_acceleration(t, site_class, z)
        ratio = sa / target if target else math.inf
        if worst is None or ratio < worst["ratio"]:
            worst = {"period": t, "ratio": ratio}
    required = 1.0 - c["tolerance"]
    return {
        "ok": worst is not None and worst["ratio"] >= required - 1e-12,
        "worst": worst,
        "required": required,
    }


# ─────────────────────────────────────── the design ───────────────────────────────────────


def design(
    units: list[Unit],
    levels: list[tuple[float, float]],
    centre: tuple[float, float],
    *,
    site_class: str,
    z: float,
    r: dict[str, float],
    fixed_period: dict[str, float],
    wind_shear: dict[str, float],
    storeys: int,
    accidental_share: float,
    has_time_histories: bool = False,
) -> dict[str, Any]:
    """The isolation design of ``units`` under a building of ``levels`` [(height above the
    isolation interface m, weight N)] with its centre of mass ``centre`` [m]. ``r``: the
    system's R by direction, ``fixed_period``: the fixed-base period by direction [s],
    ``wind_shear``: the factored wind base shear by direction [N]. Returns the summary
    (forces in kN, displacements in mm, periods in s) that ``08 FEM/isolation.json`` keeps."""
    t = _table()
    cl = clauses()
    weight = sum(w for _, w in levels)
    notes: list[str] = []
    lower = [u.lower for u in units]
    upper = [u.upper for u in units]
    nominal = [u.nominal for u in units]

    dbe = solve_displacement(lower, weight, site_class, z)
    mce = solve_displacement(lower, weight, site_class, z, mce=True, design_period=dbe["T"])
    for name, found in (("DD", dbe), ("DM", mce)):
        if not found["converged"]:
            notes.append(f"{name}: the iteration on the effective stiffness did not converge")
    dd, dm = dbe["D"], mce["D"]
    kd_max = system_stiffness(upper, dd)
    km_max = system_stiffness(upper, dm)
    totals_d = total_displacements(units, centre, dd, accidental_share)
    totals_m = total_displacements(units, centre, dm, accidental_share)
    dtd = max(totals_d["X"]["total"], totals_d["Y"]["total"])
    dtm = max(totals_m["X"]["total"], totals_m["Y"]["total"])

    # ── forces (Eqs 6.2.66-6.2.67, Sec 2.5.16.2.2) ──
    from saengine.fem import loads as fl

    vb = kd_max * dd
    activation = sum(u.activation() for u in units)
    forces: dict[str, Any] = {}
    for axis in ("X", "Y"):
        ri = reduction_factor(r[axis])
        r_fixed = ri if t.forces.fixedBaseR == "isolated" else r[axis]
        minima = {
            "fixedBase": fl.design_acceleration(
                dbe["T"], site_class, z, t.forces.importance, r_fixed, None
            )
            * weight,
            "wind": wind_shear.get(axis, 0.0),
            "activation": t.forces.activationFactor * activation,
        }
        formula = vb / ri
        vs = max(formula, *minima.values())
        governs = "formula" if vs == formula else max(minima, key=lambda k: minima[k])
        distribution = distribute(levels, vs)
        forces[axis] = {
            "R": r[axis],
            "RI": ri,
            "Vb_kN": vb / 1e3,
            "VsFormula_kN": formula / 1e3,
            "minima_kN": {k: v / 1e3 for k, v in minima.items()},
            "Vs_kN": vs / 1e3,
            "governs": governs,
            "levels": [
                {"h": h, "w_kN": w / 1e3, "F_kN": f / 1e3}
                for (h, w), f in zip(levels, distribution, strict=True)
            ],
        }

    # ── checks ──
    checks: list[dict[str, Any]] = []

    def check(key: str, label: str, value: Any, limit: Any, ok: bool | None) -> None:
        checks.append(
            {
                "id": key,
                "label": label,
                "value": value,
                "limit": limit,
                "ok": ok,
                "clause": cl.get(key, ""),
            }
        )

    share = t.restoring.atShare
    gain = sum(c.force(dtd) - c.force(share * dtd) for c in lower)
    check(
        "restoring",
        f"Restoring force: F(DTD) - F({share:g} DTD) [kN]",
        round(gain / 1e3, 3),
        round(t.restoring.forceShare * weight / 1e3, 3),
        gain >= t.restoring.forceShare * weight - 1e-9,
    )
    capacities = [u.spec.displacementCapacity for u in units]
    if all(c is not None for c in capacities):
        least = min(float(c) for c in capacities) / 1e3  # type: ignore[arg-type]
        check(
            "restraint",
            "Displacement capacity of the units [mm] at least DTM",
            round(least * 1e3, 1),
            round(dtm * 1e3, 1),
            least >= dtm - 1e-9,
        )
    else:
        check(
            "restraint",
            "Displacement capacity of the units at least DTM",
            None,
            round(dtm * 1e3, 1),
            None,
        )
    # Overturning at the interface under the MCE (requirement 7): the MCE force kMmax·DM
    # (unreduced) distributed by Eq 6.2.68, against the seismic weight about the outer units.
    vm = km_max * dm
    xs = [u.x for u in units]
    ys = [u.y for u in units]
    for axis, lever in (
        ("X", min(centre[0] - min(xs), max(xs) - centre[0])),
        ("Y", min(centre[1] - min(ys), max(ys) - centre[1])),
    ):
        moment = sum(f * h for (h, _), f in zip(levels, distribute(levels, vm), strict=True))
        factor = weight * max(lever, 0.0) / moment if moment > 0 else math.inf
        check(
            "overturning",
            f"Overturning at the isolation interface along {axis} (MCE): factor of safety",
            round(factor, 3) if math.isfinite(factor) else None,
            t.overturning.minimumFactor,
            factor >= t.overturning.minimumFactor - 1e-9,
        )

    # ── where the equivalent static analysis is permitted (Sec 2.5.16.2) ──
    lim = t.staticLimits
    height = max((h for h, _ in levels), default=0.0)
    k_20 = system_stiffness(nominal, lim.stiffnessAtShare * dd)
    k_dd = system_stiffness(nominal, dd)
    t_fixed = max(fixed_period.values(), default=0.0)
    restoring_ok = checks[0]["ok"]
    restraint_ok = next(c["ok"] for c in checks if c["id"] == "restraint")
    conditions = [
        {"id": "1", "label": f"Site class {site_class} in {', '.join(lim.siteClasses)}",
         "ok": site_class in lim.siteClasses},
        {"id": "2", "label": f"{storeys} storeys (at most {lim.maxStoreys}), {height:.2f} m "
         f"(at most {lim.maxHeight:g} m) above the isolation interface",
         "ok": storeys <= lim.maxStoreys and height <= lim.maxHeight + 1e-9},
        {"id": "3", "label": f"TM = {mce['T']:.2f} s at most {lim.maxPeriodM:g} s",
         "ok": mce["T"] <= lim.maxPeriodM + 1e-9},
        {"id": "4", "label": f"TD = {dbe['T']:.2f} s more than {lim.periodRatio:g} × the "
         f"fixed-base period {t_fixed:.2f} s",
         "ok": dbe["T"] > lim.periodRatio * t_fixed if t_fixed > 0 else None},
        {"id": "5", "label": "Regular configuration above the isolation system (checked with "
         "the irregularities of the response spectrum design)", "ok": None},
        {"id": "6a", "label": f"k at DD {k_dd / 1e3:.0f} kN/m more than {lim.stiffnessRatio:.3g} × "
         f"k at {lim.stiffnessAtShare:g} DD {k_20 / 1e3:.0f} kN/m",
         "ok": k_dd > lim.stiffnessRatio * k_20},
        {"id": "6b", "label": "Restoring force", "ok": restoring_ok},
        {"id": "6c", "label": "No restraint below the total maximum displacement", "ok": restraint_ok},
    ]  # fmt: skip
    failed = [c for c in conditions if c["ok"] is False]
    static_permitted = not failed
    if failed:
        notes.append(
            "the equivalent static analysis is not permitted for this isolated building (not met: "
            + "; ".join(c["label"] for c in failed)
            + f", {cl.get('staticLimits', '')}): use the response spectrum analysis"
            + (" or a time history" if has_time_histories else "")
        )
    else:
        notes.append(
            "the equivalent static analysis is permitted if the structure above the isolators "
            f"is regular ({cl.get('staticLimits', '')})"
        )

    # ── the response spectrum's damping (Sec 2.5.16.3.1) ──
    sa_rules = t.spectrumAnalysis
    modal = min(100 * dbe["beta"], sa_rules.maxModalDamping)
    spectrum = {
        "modalDamping": modal,
        "B": damping_coefficient(modal),
        "dampedFrom": sa_rules.dampedFromShare * dbe["T"],
        "orthogonalShare": sa_rules.orthogonalShare,
        "note": sa_rules.note,
    }

    # ── requirements, testing and review ──
    computed = {"4": restoring_ok, "5": restraint_ok}
    computed["7"] = all(c["ok"] for c in checks if c["id"] == "overturning")
    bounded = all(
        float(u.spec.lowerBoundFactor) < 1 or float(u.spec.upperBoundFactor) > 1 for u in units
    )
    requirements = []
    for item in t.requirements:
        status: bool | None = None
        if item.check == "computed":
            status = computed.get(item.id)
        elif item.check == "bounds":
            status = bounded
        requirements.append({"id": item.id, "text": item.text, "check": item.check, "ok": status})
    if not bounded:
        notes.append(
            "property variation: some isolator types have no property bounds (lower- and upper-bound "
            "factors 1): enter the variation of the tested properties over the building's life"
        )
    testing = _test_programme(
        units, weight, wind_shear, {"DD": dd, "DM": dm, "DTD": dtd, "DTM": dtm}
    )

    summary = {
        "schema": SCHEMA,
        "available": True,
        "weight_kN": weight / 1e3,
        "centreOfMass": {"x": centre[0], "y": centre[1]},
        "centreOfRigidity": totals_d.pop("centreOfRigidity"),
        "design": {
            "D_mm": dd * 1e3, "T": dbe["T"], "beta": dbe["beta"], "B": dbe["B"],
            "Sa": dbe["Sa"], "kMin_kNm": dbe["k"] / 1e3, "kMax_kNm": kd_max / 1e3,
        },
        "maximum": {
            "D_mm": dm * 1e3, "T": mce["T"], "beta": mce["beta"], "B": mce["B"],
            "Sa": mce["Sa"], "kMin_kNm": mce["k"] / 1e3, "kMax_kNm": km_max / 1e3,
        },
        "total": {
            "DTD_mm": dtd * 1e3,
            "DTM_mm": dtm * 1e3,
            "byAxis": {
                a: {
                    "DTD_mm": totals_d[a]["total"] * 1e3,
                    "DTM_mm": totals_m[a]["total"] * 1e3,
                    "eccentricity_m": totals_d[a]["eccentricity"],
                }
                for a in ("X", "Y")
            },
        },
        "forces": forces,
        "drift": {
            "Cd": {a: forces[a]["RI"] for a in ("X", "Y")},
            "importance": t.forces.importance,
            "limits": {"static": t.drift.static, "spectrum": t.drift.spectrum, "history": t.drift.history},
        },
        "checks": checks,
        "staticAnalysis": {"permitted": static_permitted, "conditions": conditions},
        "spectrum": spectrum,
        "requirements": requirements,
        "testing": testing,
        "review": list(t.review),
        "units": [
            {
                "column": u.column, "type": u.type, "node": u.node, "x": u.x, "y": u.y,
                "kind": u.spec.kind,
                "kDmin_kNm": u.lower.stiffness(dd) / 1e3,
                "kDmax_kNm": u.upper.stiffness(dd) / 1e3,
                "DTD_mm": max(totals_d["X"]["units"][u.node], totals_d["Y"]["units"][u.node]) * 1e3,
                "DTM_mm": max(totals_m["X"]["units"][u.node], totals_m["Y"]["units"][u.node]) * 1e3,
                "capacity_mm": u.spec.displacementCapacity,
                "verticalCapacity_kN": u.spec.verticalCapacity,
            }
            for u in units
        ],
        "notes": notes,
        "clauses": cl,
    }  # fmt: skip
    summary["history"] = history_criteria(
        {"design": dbe, "maximum": mce, "forces": {"X": forces["X"]}}
    )
    return summary


def _test_programme(
    units: list[Unit], weight: float, wind_shear: dict[str, float], values: dict[str, float]
) -> list[dict[str, Any]]:
    """The prototype test sequence per isolator type (Sec 2.5.16.4): the vertical load, the wind
    cycles at the unit's share of the wind force and the displacement steps."""
    t = _table().testing
    by_type: dict[str, list[Unit]] = {}
    for u in units:
        by_type.setdefault(u.type, []).append(u)
    wind = max(wind_shear.values(), default=0.0) / max(len(units), 1)
    rows = []
    for type_id, mine in by_type.items():
        spec = mine[0].spec
        vertical = (
            float(spec.testVerticalLoad)
            if spec.testVerticalLoad
            else weight / max(len(units), 1) / 1e3
        )
        rows.append(
            {
                "type": type_id,
                "units": len(mine),
                "verticalLoad_kN": vertical,
                "verticalSource": "entered" if spec.testVerticalLoad else "seismic weight per unit",
                "steps": [
                    {"label": "wind design force", "force_kN": wind / 1e3, "cycles": t.windCycles}
                ]
                + [
                    {
                        "label": f"{s.share:g} {s.of}",
                        "displacement_mm": s.share * values[s.of] * 1e3,
                        "cycles": s.cycles,
                    }
                    for s in t.steps
                ],
            }
        )
    return rows


# ─────────────────────────────────── the analysis model ───────────────────────────────────


@dataclass
class IsolationResult:
    project: dict[str, Any]
    summary: dict[str, Any] | None
    notes: list[str] = field(default_factory=list)


def isolated_types(types: dict[str, Any]) -> dict[str, Any]:
    """The column types with an isolator: ``{type id: SeismicIsolator}``."""
    return {
        tid: t.isolator
        for tid, t in types.items()
        if getattr(t, "kind", None) == "column" and getattr(t, "isolator", None) is not None
    }


def _pattern(project: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((p for p in project.get("load_patterns", []) if p.get("name") == name), None)


def _base_shear(project: dict[str, Any], case: str, axis: int) -> float:
    pattern = _pattern(project, case)
    if pattern is None:
        return 0.0
    return abs(sum(float(load["forces"][axis]) for load in pattern.get("nodal_loads", [])))


def apply_isolation(
    project: dict[str, Any],
    building: Any,
    types: dict[str, Any],
    settings: Any,
    values: dict[str, Any],
    fixed_period: dict[str, float],
) -> IsolationResult | None:
    """The derived ``project`` (a modified copy) with the isolated column bases on their
    isolators, the static earthquake cases and the response spectrum of the isolated building
    (module notes), its summary and notes; None when no column type has an isolator."""
    from saengine.fem.ssi import _Editor
    from saengine.library.bim import ColumnElement, WallElement

    isolators = isolated_types(types)
    if not isolators:
        return None
    if not covered():
        pack = code_context.current()
        return IsolationResult(
            project,
            None,
            [
                (
                    f"seismic isolators: the code pack {pack.name} does not cover isolated "
                    "buildings; the columns stay fixed"
                )
            ],
        )
    out = copy.deepcopy(project)
    editor = _Editor(out)
    notes: list[str] = []
    units: list[Unit] = []
    for element in building.elements:
        if not isinstance(element, ColumnElement) or element.type not in isolators:
            continue
        key = (round(element.position[0]), round(element.position[1]), round(element.bottom))
        node_id = editor.by_position.get(key)
        if node_id is None or not all(editor.nodes[node_id].get("restraint") or [False]):
            notes.append(
                f"{element.id}: its base is not a fixed support (on soil springs, or on a member); "
                "no isolator"
            )
            continue
        xyz = editor.nodes[node_id]["coords"]
        units.append(
            Unit(
                element.id,
                element.type,
                node_id,
                float(xyz[0]),
                float(xyz[1]),
                isolators[element.type],
            )
        )
    if not units:
        notes.append("seismic isolators: no column with an isolator stands on a support")
        return IsolationResult(project, None, notes)
    if len(units) < 3:
        notes.append("seismic isolators: fewer than three units cannot carry the building stably")
    interface = min(float(editor.nodes[u.node]["coords"][2]) for u in units)
    fixed_left = [
        n["id"]
        for n in out["nodes"]
        if all(n.get("restraint") or [False])
        and abs(float(n["coords"][2]) - interface) < 1e-3
        and n["id"] not in {u.node for u in units}
    ]
    walls = [e.id for e in building.elements if isinstance(e, WallElement)]
    if fixed_left:
        notes.append(
            f"seismic isolators: {len(fixed_left)} supports at the isolation interface have no "
            "isolator (walls, or columns of types without one) and stay fixed: an isolated "
            "building needs every support at the interface on an isolator"
            + (f" (walls: {', '.join(sorted(walls))})" if walls else "")
        )

    # The seismic weight above the interface by level (the nodes' masses).
    level_weight: dict[float, float] = {}
    moment = np.zeros(2)
    for n in out["nodes"]:
        z = round(float(n["coords"][2]), 3)
        mass = float((n.get("mass") or [0.0])[0])
        if z < interface - 1e-3 or mass <= 0:
            continue
        level_weight[z] = level_weight.get(z, 0.0) + mass * G
        moment += mass * G * np.asarray(n["coords"][:2], dtype=float)
    weight = sum(level_weight.values())
    if weight <= 0:
        notes.append("seismic isolators: the building has no seismic weight; no isolation design")
        return IsolationResult(project, None, notes)
    centre = (float(moment[0] / weight), float(moment[1] / weight))
    levels = [(round(z - interface, 6), w) for z, w in sorted(level_weight.items())]
    storeys = sum(1 for h, _ in levels if h > 1e-6)

    wind_factor = max(
        (
            abs(float(getattr(c, a, 0.0) or 0.0))
            for c in settings.combinations
            for a in ("WX", "WY")
        ),
        default=0.0,
    )
    wind = {
        "X": wind_factor * _base_shear(out, "WX", 0),
        "Y": wind_factor * _base_shear(out, "WY", 1),
    }
    seismic = code_context.table("seismic")
    summary = design(
        units,
        levels,
        centre,
        site_class=settings.site.siteClass,
        z=float(values["Z"]),
        r={a: float(values.get(f"R{a}", values["R"])) for a in ("X", "Y")},
        fixed_period=fixed_period,
        wind_shear=wind,
        storeys=storeys,
        accidental_share=float(getattr(seismic, "accidentalEccentricity", 0.05) or 0.05),
        has_time_histories=bool(getattr(settings.analysis, "timeHistories", None)),
    )
    dd = summary["design"]["D_mm"] / 1e3

    # ── the isolators in the model: the upper-bound effective stiffness at DD ──
    for u in units:
        k = u.upper.stiffness(dd)
        node = editor.nodes[u.node]
        node["restraint"] = [False, False, False, True, True, True]
        ground = editor.node(node["coords"], fixed=True)
        editor.spring(
            f"{u.column}{ELEMENT_SUFFIX}",
            ground,
            u.node,
            [k, k, float(u.spec.verticalStiffness) * 1e3],
            [1, 2, 3],
        )

    # ── the static earthquake cases to Eq 6.2.68 with Vs ──
    coords = {n["id"]: float(n["coords"][2]) for n in out["nodes"]}
    for axis, cases in _STATIC_CASES.items():
        a = 0 if axis == "X" else 1
        source = _pattern(out, cases[0])
        if source is None:
            continue
        old: dict[float, float] = {}
        for load in source.get("nodal_loads", []):
            z = round(coords.get(load["node_id"], 0.0) - interface, 3)
            old[z] = old.get(z, 0.0) + float(load["forces"][a])
        new = {round(row["h"], 3): row["F_kN"] * 1e3 for row in summary["forces"][axis]["levels"]}
        missing = [z for z, f in new.items() if f and not old.get(z)]
        if missing:
            notes.append(
                f"E{axis}: no static force at {len(missing)} levels to re-distribute; their share "
                "of Vs is left out"
            )
        for name in cases:
            pattern = _pattern(out, name)
            if pattern is None:
                continue
            for load in pattern.get("nodal_loads", []):
                z = round(coords.get(load["node_id"], 0.0) - interface, 3)
                ratio = new.get(z, 0.0) / old[z] if old.get(z) else 0.0
                load["forces"] = [float(v) * ratio for v in load["forces"]]

    # ── the response spectrum of the isolated building ──
    from saengine.fem import loads as fl

    spec = summary["spectrum"]
    for spectrum in out.get("spectra", []):
        axis = "Y" if str(spectrum.get("name", "")).endswith("Y") else "X"
        ri = summary["forces"][axis]["RI"]
        spectrum["accelerations"] = [
            round(
                G
                * fl.design_acceleration(
                    t,
                    settings.site.siteClass,
                    float(values["Z"]),
                    _table().forces.importance,
                    ri,
                    None,
                )
                / (spec["B"] if t >= spec["dampedFrom"] else 1.0),
                6,
            )
            for t in spectrum["periods"]
        ]
    if out.get("spectra"):
        notes.append(
            f"response spectrum: the isolated building's (R = RI, I = 1, ÷ B = {spec['B']:.2f} for "
            f"the isolation damping {spec['modalDamping']:.1f} % from {spec['dampedFrom']:.2f} s "
            "up: SAEngine practice, see the pack's note)"
        )
    notes.insert(
        0,
        f"seismic isolators under {len(units)} columns: DD = {summary['design']['D_mm']:.0f} mm "
        f"(TD = {summary['design']['T']:.2f} s), DM = {summary['maximum']['D_mm']:.0f} mm "
        f"(TM = {summary['maximum']['T']:.2f} s), DTD = {summary['total']['DTD_mm']:.0f} mm, "
        f"DTM = {summary['total']['DTM_mm']:.0f} mm; Vb = {summary['forces']['X']['Vb_kN']:.0f} kN, "
        f"Vs = {summary['forces']['X']['Vs_kN']:.0f} / {summary['forces']['Y']['Vs_kN']:.0f} kN "
        f"(X / Y; EX, EY re-distributed: {clauses().get('distribution', '')})",
    )
    notes.extend(summary["notes"])
    for c in summary["checks"]:
        if c["ok"] is False:
            notes.append(
                f"isolation check fails: {c['label']} = {c['value']} (limit {c['limit']}; {c['clause']})"
            )
    if getattr(settings.analysis, "timeHistories", None):
        h = summary["history"]
        notes.append(
            f"time histories of the isolated building: at least {h['minRecords']} pairs scaled "
            f"between {h['periodRange'][0]:.2f} and {h['periodRange'][1]:.2f} s to "
            f"{h['spectrumFactor']:g} × the design spectrum ({h['clause']}); the drift limit is "
            f"{h['driftLimit']:g} hsx"
        )
    summary["notes"] = notes
    return IsolationResult(out, summary, notes)


# ─────────────────────────────── reading it back (seismic design) ───────────────────────────────


def load(model_folder: str | Path) -> dict[str, Any] | None:
    """The isolation design beside the analysis model (``08 FEM/isolation.json``), or None."""
    try:
        data = json.loads((Path(model_folder) / ISOLATION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None


def spectrum_displacements(
    summary: dict[str, Any], spectra: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """The isolators' displacements from the response spectrum cases RX, RY (Sec 2.5.16.3.1):
    each unit's peak translations, elastic (× RI of each direction), combined as 100 % of one
    direction plus the pack's share of the other, as the vector sum of the two components;
    the total maximum displacement from it × mceFactor × BD/BM. ``{"DTD_mm", "DTM_mm",
    "centre_mm", "assumed_mm", "units": {node: mm}}``; None without RX and RY."""
    if "X" not in spectra or "Y" not in spectra:
        return None
    t = _table()
    s = t.spectrumAnalysis.orthogonalShare
    ri = {a: summary["forces"][a]["RI"] for a in ("X", "Y")}
    per: dict[int, float] = {}
    centre: list[float] = []
    for u in summary["units"]:
        node = int(u["node"])
        dx = (
            np.abs(np.asarray(spectra["X"]["combined"].get(node, np.zeros(3)), dtype=float))
            * ri["X"]
        )
        dy = (
            np.abs(np.asarray(spectra["Y"]["combined"].get(node, np.zeros(3)), dtype=float))
            * ri["Y"]
        )
        one = math.hypot(dx[0] + s * dy[0], dx[1] + s * dy[1])
        two = math.hypot(s * dx[0] + dy[0], s * dx[1] + dy[1])
        per[node] = max(one, two)
        centre.append(float(dx[0]))
    if not per:
        return None
    dtd = max(per.values())
    ratio = summary["design"]["B"] / summary["maximum"]["B"] if summary["maximum"]["B"] else 1.0
    return {
        "DTD_mm": dtd * 1e3,
        "DTM_mm": dtd * t.spectrum.mceFactor * ratio * 1e3,
        "centre_mm": float(np.mean(centre)) * 1e3,
        "assumed_mm": summary["design"]["D_mm"],
        "units": {str(k): v * 1e3 for k, v in per.items()},
        "clause": clauses().get("spectrum", ""),
    }


def seismic_design_block(
    model_folder: str | Path, spectra: dict[str, dict[str, Any]], notes: list[str]
) -> dict[str, Any] | None:
    """What the response spectrum design takes from the isolation design beside the model
    (:mod:`saengine.fem.seismic_design`): ``{"amplification": {"X", "Y"} (Cd/I = RI/1),
    "allowable" (the spectrum drift limit), "summary"}``; None for a building without
    isolators. Notes go to ``notes``."""
    summary = load(model_folder)
    if summary is None or not covered():
        return None
    t = _table()
    importance = summary["drift"]["importance"] or 1.0
    amplification = {a: summary["drift"]["Cd"][a] / importance for a in ("X", "Y")}
    found = spectrum_displacements(summary, spectra)
    block = {
        "amplification": amplification,
        "allowable": t.drift.spectrum,
        "summary": {
            "design": summary["design"],
            "maximum": summary["maximum"],
            "total": summary["total"],
            "spectrum": found,
            "driftLimit": t.drift.spectrum,
            "Cd": summary["drift"]["Cd"],
            "clause": clauses().get("dynamicDrift", ""),
        },
    }
    notes.append(
        f"isolated building: drift with Cd = RI ({amplification['X']:.2f} / "
        f"{amplification['Y']:.2f}) and I = 1 against {t.drift.spectrum:g} hsx "
        f"({clauses().get('dynamicDrift', '')})"
    )
    if found is not None:
        notes.append(
            f"isolators by response spectrum: DTD = {found['DTD_mm']:.0f} mm, DTM ≈ "
            f"{found['DTM_mm']:.0f} mm (100 % + {100 * t.spectrumAnalysis.orthogonalShare:g} %, "
            f"vector sum; {found['clause']})"
        )
        assumed, got = found["assumed_mm"], found["centre_mm"]
        if assumed > 0 and abs(got - assumed) > 0.1 * assumed:
            notes.append(
                f"isolators: the effective stiffness was taken at DD = {assumed:.0f} mm, the "
                f"response spectrum gives {got:.0f} mm at the units: adjust the isolator "
                "properties and derive again until they agree (the equivalent linear iteration "
                "of the code)"
            )
    return block

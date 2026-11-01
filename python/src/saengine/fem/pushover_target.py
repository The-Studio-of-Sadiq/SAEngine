"""The target displacement of a pushover, by the method the code pack names.

The code pack's ``pushover`` table (:class:`saengine.codes.tables.PushoverTable`) says how far a
pushover must go and how its target displacement is found. One method is implemented:

``coefficient`` (the displacement coefficient method):

1. a bilinear curve is fitted to the capacity curve: its first segment meets the curve at
   ``bilinearFitShare`` × the effective yield strength Vy, its second meets it at the target
   displacement δt, and the areas under the two curves up to δt are equal;
2. the effective period Te = T1·√((V1/δ1) / (Vy/δy)), with T1, V1 and δ1 of the first increment
   of lateral load;
3. δt = C0·C1·Sa(Te)·(Te/2π)²·g, Sa from the code's spectrum with the pack's R and I (the real,
   unreduced spectrum), C0 = Σwᵢφᵢ / Σwᵢφᵢ² over the levels, C1 = 1 where Te exceeds the pack's
   corner period, else [1 + (Rd - 1)·Ts/Te] / Rd with Rd = Sa / (Vy/W).

δt depends on the fit and the fit on δt, so the two are iterated until δt settles.

The capacity curve is checked as well: it must reach ``pushToTarget`` × δt, and the base shear
may not drop in any step up to ``noDropToTarget`` × δt.

The first increment's values come from the run itself: δ1 and V1 of its first step, the shape
φ of the displacements of the masses in that step (normalised to 1 at the control point), and
T1 from the Rayleigh quotient of that step (2π·√(Σmᵢuᵢ² / ΣFᵢuᵢ)), which is the fundamental
period exactly when the load pattern is the fundamental mode's.

Units: m, N, s; Sa in g.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

#: Acceleration due to gravity [m/s²].
G = 9.80665
#: Fewer steps than this to the target displacement: the curve is too coarse (a note).
MIN_STEPS_TO_TARGET = 5


def table() -> Any | None:
    """The code pack's ``pushover`` table; None when the pack in force has none."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    return pack.table("pushover") if pack.has("pushover") else None


def clause(key: str) -> str:
    """The pack's clause of ``key`` (its ``sources``), for the results and the report."""
    found = table()
    if found is None:
        return ""
    return found.sources.get(key) or found.source


# ───────────────────────────────────── the curve ─────────────────────────────────────


def _upto(d: np.ndarray, v: np.ndarray, at: float) -> tuple[np.ndarray, np.ndarray]:
    """The curve from its start to displacement ``at`` (interpolated there)."""
    inside = d < at
    dd, vv = d[inside], v[inside]
    return np.append(dd, at), np.append(vv, float(np.interp(at, d, v)))


def _first_reaching(d: np.ndarray, v: np.ndarray, force: float) -> float | None:
    """The displacement at which the curve first reaches ``force`` (interpolated)."""
    for k in range(1, len(d)):
        if v[k] >= force:
            if v[k] == v[k - 1]:
                return float(d[k])
            t = (force - v[k - 1]) / (v[k] - v[k - 1])
            return float(d[k - 1] + t * (d[k] - d[k - 1]))
    return None


def bilinear_fit(
    displacement: Any, shear: Any, target: float, share: float = 0.6
) -> dict[str, float]:
    """The bilinear curve of the capacity curve (``displacement``, ``shear`` from the origin)
    up to ``target``: the first segment through the curve at ``share``·Vy, the second through
    the curve at ``target``, equal areas. Returns ``{"Vy", "dy", "Ke", "Vt", "target",
    "elastic"}`` (``elastic``: the curve is straight to the target, Vy = Vt)."""
    d, v = np.asarray(displacement, dtype=float), np.asarray(shear, dtype=float)
    d, v = _upto(d, v, target)
    vt = float(v[-1])
    area = float(np.trapezoid(v, d))
    vy = float(v.max())
    ke = vy / target if target > 0 else 0.0
    elastic = False
    for _ in range(200):
        reach = _first_reaching(d, v, share * vy)
        if reach is None or reach <= 0:
            elastic = True
            break
        ke = share * vy / reach
        denominator = target - vt / ke
        numerator = 2 * area - vt * target
        if denominator <= 1e-12 * target or numerator <= 1e-9 * vt * target:
            elastic = True
            break
        new = numerator / denominator
        if abs(new - vy) <= 1e-9 * max(vy, 1.0):
            vy = new
            break
        vy = new
    dy = vy / ke if ke > 0 else target
    if elastic or dy >= target:
        vy, dy = vt, target
        ke = vt / target if target > 0 else 0.0
        elastic = True
    return {"Vy": vy, "dy": dy, "Ke": ke, "Vt": vt, "target": target, "elastic": elastic}


def c0_factor(weights: Any, shape: Any) -> float:
    """C0 = Σwᵢφᵢ / Σwᵢφᵢ² of the level weights and the shape vector (φ = 1 at the control
    point)."""
    w, phi = np.asarray(weights, dtype=float), np.asarray(shape, dtype=float)
    return float(np.sum(w * phi) / np.sum(w * phi**2))


def c1_factor(te: float, rd: float, ts: float, limit: float) -> float:
    """C1 = 1 for Te > the corner period ``limit``, else [1 + (Rd - 1)·Ts/Te] / Rd."""
    if te > limit:
        return 1.0
    return (1 + (rd - 1) * ts / te) / rd


def rayleigh_period(masses: Any, displacements: Any, forces: Any) -> float:
    """T = 2π·√(Σmᵢuᵢ² / ΣFᵢuᵢ) of the forces ``forces`` causing ``displacements``."""
    m, u, f = (np.asarray(a, dtype=float) for a in (masses, displacements, forces))
    work = float(np.sum(f * u))
    return 2 * math.pi * math.sqrt(float(np.sum(m * u**2)) / work) if work > 0 else 0.0


# ─────────────────────────────── the coefficient method ───────────────────────────────


def coefficient(
    displacement: Any,
    shear: Any,
    *,
    t1: float,
    c0: float,
    weight: float,
    spectrum: Callable[[float], float],
    corners: dict[str, float],
    rule: Any,
) -> dict[str, Any]:
    """The target displacement of the capacity curve by the displacement coefficient method
    (see the module): ``t1`` [s] the first increment's period, ``c0``, ``weight`` W [N],
    ``spectrum`` Sa(T) [g] with the pack's R and I, ``corners`` the site's TB, TC, TD [s],
    ``rule`` the pack's ``targetDisplacement``. Returns the values of each equation."""
    d, v = np.asarray(displacement, dtype=float), np.asarray(shear, dtype=float)
    if len(d) < 2 or d[1] <= 0 or v[1] <= 0:
        raise ValueError("the capacity curve has no first increment")
    k1 = float(v[1] / d[1])
    limit, ts = corners[rule.c1PeriodLimit], corners[rule.c1Period]

    def target(te: float, fit: dict[str, float] | None) -> tuple[float, float, float, float]:
        sa = spectrum(te)
        rd = max(rule.minimumRd, sa / (fit["Vy"] / weight)) if fit else rule.minimumRd
        c1 = c1_factor(te, rd, ts, limit)
        return c0 * c1 * sa * (te / (2 * math.pi)) ** 2 * G, sa, rd, c1

    last = float(d[-1])

    def at(trial: float) -> tuple[float, dict[str, Any]]:
        """δt of the bilinear fit to ``trial``, with the fit and the factors."""
        fit = bilinear_fit(d, v, trial, rule.bilinearFitShare)
        te = t1 * math.sqrt(k1 / fit["Ke"]) if fit["Ke"] > 0 else t1
        found, sa, rd, c1 = target(te, fit)
        return found, {"fit": fit, "Te": te, "Sa": sa, "Rd": rd, "C1": c1}

    # δt is where the fit to δt gives δt back: a root of at(δ) - δ. Below the first increment
    # the curve is straight, so at(δ) > δ there; bisection keeps a sign change between the ends.
    lo = 1e-3 * float(d[1])
    hi = last
    dt, values = at(hi)
    converged = dt <= hi
    if converged:
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            found, values = at(mid)
            if found > mid:
                lo = mid
            else:
                hi = mid
            if hi - lo <= 1e-7 * hi:
                break
        dt, values = at(hi)
        # A jump of at(δ) across the root (a coarse curve) leaves dt off hi: not settled.
        converged = abs(dt - hi) <= 1e-3 * hi
    fit = values["fit"]
    te, sa, rd, c1 = values["Te"], values["Sa"], values["Rd"], values["C1"]
    return {
        "method": "coefficient",
        "T1": t1,
        "K1": k1,
        "V1": float(v[1]),
        "d1": float(d[1]),
        "Vy": fit["Vy"],
        "dy": fit["dy"],
        "Ke": fit["Ke"],
        "Vt": fit["Vt"],
        "elastic": fit["elastic"],
        "Te": te,
        "Sa": sa,
        "C0": c0,
        "C1": c1,
        "Rd": rd,
        "W": weight,
        "target": dt,
        "beyondCurve": dt > last * (1 + 1e-6),
        "converged": converged,
        "bilinear": [[0.0, 0.0], [fit["dy"], fit["Vy"]], [min(dt, last), fit["Vt"]]],
    }


#: Target displacement methods by the id a code pack gives (``targetDisplacement.method``).
METHODS: dict[str, Callable[..., dict[str, Any]]] = {"coefficient": coefficient}


def capacity_checks(
    displacement: Any, shear: Any, target: float, push_share: float, drop_share: float
) -> dict[str, Any]:
    """Whether the capacity curve reaches ``push_share`` × ``target`` and whether its base
    shear drops in any step up to ``drop_share`` × ``target``: ``{"pushedTo", "required",
    "reached", "noDropTo", "dropAt" (displacement of the first drop, or None), "noDrop"
    (None when the curve stops before the no-drop range ends), "targetStep" (the first step at
    or beyond the target, or None)}``."""
    d, v = np.asarray(displacement, dtype=float), np.asarray(shear, dtype=float)
    pushed = float(d[-1])
    required = push_share * target
    limit = drop_share * target
    tolerance = 1e-3 * float(np.max(np.abs(v))) if len(v) else 0.0
    drop = None
    for k in range(1, len(d)):
        if d[k] > limit * (1 + 1e-9):
            break
        if v[k] < v[k - 1] - tolerance:
            drop = float(d[k])
            break
    covered = pushed >= limit * (1 - 1e-6)
    step = next((k for k in range(len(d)) if d[k] >= target * (1 - 1e-9)), None)
    return {
        "pushedTo": pushed,
        "required": required,
        "reached": pushed >= required * (1 - 1e-3),
        "noDropTo": limit,
        "dropAt": drop,
        "noDrop": False if drop is not None else (True if covered else None),
        "targetStep": step,
    }


# ─────────────────────────────── from a pushover run ───────────────────────────────


def first_increment(
    project: dict[str, Any], analysis: dict[str, Any], results: Any
) -> dict[str, Any]:
    """The masses, shape and period of the first increment of a pushover run (``results``, a
    ``PushoverResults`` of ``analysis`` in the model ``project``): ``{"weights", "shape",
    "C0", "T1", "W"}`` over the nodes with mass in the pushed direction."""
    dof = int(analysis["control_dof"]) - 1
    control = int(analysis["control_node"])
    sign = 1.0 if float(analysis.get("target_disp", 1.0)) >= 0 else -1.0
    patterns = {p["id"]: p for p in project.get("load_patterns", [])}
    reference: dict[int, float] = {}
    for pid in analysis.get("pattern_ids", []):
        for load in patterns.get(pid, {}).get("nodal_loads", []):
            node = int(load["node_id"])
            reference[node] = reference.get(node, 0.0) + float(load["forces"][dof])
    nodes = {int(n["id"]): n for n in project.get("nodes", [])}

    def moved(node: int) -> float:
        rows = np.asarray(results.node_disp[node], dtype=float)
        return sign * float(rows[1][dof] - rows[0][dof])

    roof = moved(control)
    if roof <= 0:
        raise ValueError("the control point does not move in the first increment")
    masses, shape, disp = [], [], []
    for node_id, node in sorted(nodes.items()):
        mass = float((node.get("mass") or [0.0] * 6)[dof])
        if mass <= 0 or node_id not in results.node_disp:
            continue
        u = moved(node_id)
        masses.append(mass)
        disp.append(u)
        shape.append(u / roof)
    total = sum(reference.values())
    v1 = sign * float(np.asarray(results.base_shear)[1])
    forces = [v1 * reference.get(n, 0.0) / total if total else 0.0 for n in sorted(reference)]
    displaced = [moved(n) if n in results.node_disp else 0.0 for n in sorted(reference)]
    work = float(np.dot(forces, displaced))
    kinetic = float(np.dot(masses, np.square(disp)))
    t1 = 2 * math.pi * math.sqrt(kinetic / work) if work > 0 else 0.0
    weights = [m * G for m in masses]
    return {
        "weights": weights,
        "shape": shape,
        "C0": c0_factor(weights, shape),
        "T1": t1,
        "W": sum(weights),
    }


def capacity_curve(analysis: dict[str, Any], results: Any) -> tuple[np.ndarray, np.ndarray]:
    """The capacity curve of a pushover run from its state under gravity: control point
    displacement and base shear, both positive in the pushed direction."""
    sign = 1.0 if float(analysis.get("target_disp", 1.0)) >= 0 else -1.0
    d = np.asarray(results.control_disp, dtype=float)
    v = np.asarray(results.base_shear, dtype=float)
    return sign * (d - d[0]), sign * v


def spectrum_of(settings: Any, rule: Any) -> tuple[Callable[[float], float], dict[str, float]]:
    """Sa(T) [g] of the project's site with the pack's R and I for the target displacement,
    and the site class's corner periods."""
    from saengine.codes import context as code_context
    from saengine.fem.loads import design_acceleration
    from saengine.library.settings import derived

    values = derived(settings)
    z = values.get("Z")
    if not z:
        raise ValueError("the site has no seismic zone coefficient")
    site_class = settings.site.siteClass
    damping = settings.seismic.damping
    site = code_context.table("seismic").siteClasses[site_class]

    def sa(period: float) -> float:
        return design_acceleration(
            period, site_class, z, rule.spectrumImportance, rule.spectrumR, damping
        )

    return sa, {"TB": site.TB, "TC": site.TC, "TD": site.TD}


def evaluate(
    project: dict[str, Any], analysis: dict[str, Any], results: Any, settings: Any
) -> dict[str, Any]:
    """The target displacement and the capacity checks of one pushover run, by the method of
    the code pack in force. ``{"available": False, "reason"}`` when the pack has no pushover
    method or the run cannot give one."""
    rule = table()
    if rule is None:
        return {"available": False, "reason": "the code pack does not cover pushover analysis"}
    method = METHODS.get(rule.targetDisplacement.method)
    if method is None:
        return {
            "available": False,
            "reason": f"target displacement method '{rule.targetDisplacement.method}' unknown",
        }
    if settings is None:
        return {"available": False, "reason": "the project settings could not be read"}
    try:
        d, v = capacity_curve(analysis, results)
        first = first_increment(project, analysis, results)
        sa, corners = spectrum_of(settings, rule.targetDisplacement)
        found = method(
            d,
            v,
            t1=first["T1"],
            c0=first["C0"],
            weight=first["W"],
            spectrum=sa,
            corners=corners,
            rule=rule.targetDisplacement,
        )
    except (ValueError, KeyError, IndexError, ZeroDivisionError) as error:
        return {"available": False, "reason": str(error)}
    checks = capacity_checks(
        d, v, found["target"], rule.procedure.pushToTarget, rule.procedure.noDropToTarget
    )
    notes = []
    names = {p["id"]: p.get("name", "") for p in project.get("load_patterns", [])}
    used = [names.get(pid, "") for pid in analysis.get("pattern_ids", [])]
    kind = {"M": "firstMode", "E": "seismic", "U": "uniform"}
    pattern = kind.get(used[0][:1], "") if len(used) == 1 else ""
    pattern_ok = pattern == rule.procedure.loadPattern
    if not pattern_ok:
        notes.append(
            f"The code pack requires the '{rule.procedure.loadPattern}' load pattern "
            f"({clause('pattern')}); this pushover uses '{pattern or 'another'}': choose it in "
            "the project settings (Analysis, Pushover) and derive again."
        )
    if found["beyondCurve"]:
        notes.append(
            "The target displacement lies beyond the end of the capacity curve: push further "
            "(raise the target roof drift) or the structure cannot reach it."
        )
    elif not checks["reached"]:
        notes.append(
            f"The pushover must go to at least {rule.procedure.pushToTarget:g} × the target "
            f"displacement ({checks['required']:.3f} m) and stopped at "
            f"{checks['pushedTo']:.3f} m: raise the target roof drift ({clause('pushTo')})."
        )
    if checks["noDrop"] is False:
        notes.append(
            f"The base shear drops at {checks['dropAt']:.3f} m, before "
            f"{rule.procedure.noDropToTarget:g} × the target displacement: the structure "
            f"must be strengthened ({clause('noDrop')})."
        )
    if not found["converged"] and not found["beyondCurve"]:
        notes.append("The target displacement did not settle; the last value is shown.")
    if checks["targetStep"] is not None and checks["targetStep"] < MIN_STEPS_TO_TARGET:
        notes.append(
            f"The pushover reaches the target displacement in {checks['targetStep']} "
            f"step{'s' if checks['targetStep'] != 1 else ''}: the curve is too coarse to fit "
            "and to show the members yielding on the way. Use more steps or a smaller target "
            "roof drift."
        )
    return {
        "available": True,
        **found,
        **checks,
        "corners": corners,
        "clauses": {
            k: clause(k) for k in ("target", "period", "c0", "c1", "rd", "pushTo", "noDrop")
        },
        "note": rule.targetDisplacement.note,
        "notes": notes,
        "pattern": pattern,
        "patternOk": pattern_ok,
        "ok": (
            pattern_ok
            and not found["beyondCurve"]
            and bool(checks["reached"])
            and checks["noDrop"] is not False
        ),
    }

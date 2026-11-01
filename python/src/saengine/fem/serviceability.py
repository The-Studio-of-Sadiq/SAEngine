"""Serviceability of the building under the code pack's ``serviceability`` table (B9).

What a code asks of the building as a whole beyond strength, worked out from a finished
analysis (linear: a combination is the factored sum of its cases):

- **Storey drift under loads other than earthquake**: under the pack's service wind
  combination (``storeyDrift.combination``, a row of ``combinations.service``: W in ±X and ±Y),
  the largest drift ratio of each storey along the wind
  (:func:`saengine.fem.second_order.storey_drifts`) against a limit that depends on the
  period the base shear uses (below or above ``periodSplit``) and on whether the system in that
  direction is unreinforced masonry.
- **Sway**: under the same kind of combination (``sway.combination``), the largest horizontal
  displacement of the top level along the wind over the height above the base, against
  ``sway.ratio``.
- **Overturning of the whole building**: per lateral static case (WX, WY, EX, EY) the base
  overturning moment ΣFi (hi - hbase) of its storey forces (times the pack's factor of that load
  kind) against the dead load's resisting moment about the edge of the supports (the farther
  of the two edges counts against the force in each sense, so the nearer, the smaller, is
  taken): resisting / overturning ≥ ``overturning.factorOfSafety``.

Everything the checks compare with comes from the pack; a pack without the table (or without
one of its groups) does not cover that check, and :func:`covered` says so. Lengths in m,
forces in N.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

#: The static lateral cases and the axis (0 X, 1 Y) each acts along.
LATERAL_CASES = {"WX": 0, "WY": 1, "EX": 0, "EY": 1}
#: Wind cases of the service combinations and their axes.
WIND_AXES = {"WX": 0, "WY": 1}


def table() -> Any | None:
    """The pack's ``serviceability`` table, None when the pack in force has none."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    return pack.table("serviceability") if pack.has("serviceability") else None


def covered(group: str) -> bool:
    """Whether the pack in force has the serviceability group ``group`` (storeyDrift, sway,
    deflection, overturning)."""
    found = table()
    return found is not None and getattr(found, group, None) is not None


def storey_drift_limit(
    period: float | None, unreinforced_masonry: bool = False, limits: Any = None
) -> tuple[float, str]:
    """(Δ / h, why) of the pack's storey drift limit for loads other than earthquake: the
    unreinforced masonry ratio, else the short or long period one by ``period`` [s] (unknown:
    the stricter of the two)."""
    limits = limits if limits is not None else table().storeyDrift
    if unreinforced_masonry:
        return float(limits.unreinforcedMasonry), "unreinforced masonry"
    if period is None:
        strict = min(float(limits.shortPeriod), float(limits.longPeriod))
        return strict, "period not known: the stricter limit"
    if period < float(limits.periodSplit):
        return float(limits.shortPeriod), f"T = {period:.2f} s < {limits.periodSplit:g} s"
    return float(limits.longPeriod), f"T = {period:.2f} s ≥ {limits.periodSplit:g} s"


def sway_basis() -> tuple[float, float, str] | None:
    """(top sway / height limit, factor on W in the service wind combination, clause) of the
    pack in force, for estimates that take the wind alone (the preliminary sizing); None when
    the pack has no sway limit."""
    from saengine.fem.combinations import service_combinations

    found = table()
    if found is None or found.sway is None:
        return None
    factor = 1.0
    for _name, factors, _row in service_combinations(None, found.sway.combination):
        winds = [abs(v) for c, v in factors.items() if c in WIND_AXES]
        if winds:
            factor = winds[0]
            break
    return float(found.sway.ratio), factor, found.sway.source or ""


def unreinforced_axes(settings: Any, limits: Any = None) -> dict[str, bool]:
    """Per direction ("X", "Y") whether the project's seismic system there is one of the pack's
    unreinforced masonry systems."""
    limits = limits if limits is not None else table().storeyDrift
    plain = set(limits.unreinforcedMasonrySystems)
    try:
        from saengine.library.settings import system_values

        by_axis = system_values(settings)
    except Exception:  # noqa: BLE001 - no systems: not masonry
        return {"X": False, "Y": False}
    return {
        axis: bool(plain & set((by_axis.get(axis) or {}).get("systems") or []))
        for axis in ("X", "Y")
    }


def base_shear_periods(summary: Mapping[str, Any] | None) -> dict[str, float | None]:
    """The period [s] the base shear used per direction, from a derivation's summary
    (:func:`saengine.fem.derive.derive_fem`'s): each direction's EX / EY period, else the
    period used, else the approximate period; None when not known."""
    summary = summary or {}
    seismic = summary.get("seismic") or {}
    out: dict[str, float | None] = {}
    for axis in ("X", "Y"):
        value = (seismic.get(f"E{axis}") or {}).get("period_s")
        if value is None:
            value = summary.get("periodUsed_s", summary.get("period_s"))
        out[axis] = float(value) if value is not None else None
    return out


def _combined(
    arrays: Mapping[str, np.ndarray], factors: Mapping[str, float]
) -> np.ndarray | None:
    """Σ factor × the case's displacement array; None when a lateral case has no results
    (gravity cases the model lacks are left out: they do not act)."""
    total = None
    for case, factor in factors.items():
        if case not in arrays:
            if case in WIND_AXES or case.startswith("E"):
                return None
            continue
        part = factor * arrays[case]
        total = part if total is None else total + part
    return total


def wind_checks(
    project: dict[str, Any],
    arrays: Mapping[str, np.ndarray],
    node_index: Mapping[int, int],
    levels: list[float],
    periods: Mapping[str, float | None],
    unreinforced: Mapping[str, bool] | None = None,
    rows: Callable[[Mapping[int, int], np.ndarray], Mapping[int, Any]] | None = None,
) -> dict[str, Any]:
    """The storey drift and sway checks under the pack's service wind combinations:
    ``{"drift": [{"combination", "direction", "from", "to", "drift", "limit", "basis", "ok"}],
    "sway": [{"combination", "direction", "displacement", "height", "ratio", "limit", "ok"}],
    "combinations": [names], "clauses": {"drift", "sway"}, "notes"}``. ``arrays``: per
    static case every node's displacement row (6 values) in the order of ``node_index``;
    ``levels`` the storey levels [m] bottom up (the base first)."""
    from saengine.fem.combinations import service_combinations
    from saengine.fem.second_order import storey_drifts

    found = table()
    out: dict[str, Any] = {
        "drift": [],
        "sway": [],
        "combinations": [],
        "clauses": {},
        "notes": [],
    }
    if found is None or len(levels) < 2:
        return out
    unreinforced = unreinforced or {}
    rows = rows or (lambda index, values: {n: values[k] for n, k in index.items()})
    top = levels[-1]
    height = top - levels[0]
    top_nodes = [
        n["id"]
        for n in project.get("nodes", [])
        if len(n.get("coords", [])) >= 3 and abs(float(n["coords"][2]) - top) <= 1e-3
    ]
    present = set(arrays)
    for group, kind in ((found.storeyDrift, "drift"), (found.sway, "sway")):
        if group is None:
            continue
        out["clauses"][kind] = group.source or ""
        for name, factors, _row in service_combinations(present, group.combination):
            wind = [c for c in factors if c in WIND_AXES]
            if len(wind) != 1:
                continue
            axis = WIND_AXES[wind[0]]
            direction = "XY"[axis]
            values = _combined(arrays, factors)
            if values is None:
                continue
            if name not in out["combinations"]:
                out["combinations"].append(name)
            if kind == "drift":
                limit, basis = storey_drift_limit(
                    periods.get(direction), bool(unreinforced.get(direction)), group
                )
                for r in storey_drifts(project, rows(node_index, values), axis, levels):
                    out["drift"].append(
                        {
                            "combination": name,
                            "direction": direction,
                            "from": r["from"],
                            "to": r["to"],
                            "drift": r["drift"],
                            "limit": limit,
                            "basis": basis,
                            "ok": r["drift"] <= limit + 1e-12,
                        }
                    )
            elif top_nodes and height > 0:
                moved = max(
                    abs(float(values[node_index[n]][axis])) for n in top_nodes if n in node_index
                )
                limit = float(group.ratio)
                out["sway"].append(
                    {
                        "combination": name,
                        "direction": direction,
                        "displacement": moved,
                        "height": height,
                        "ratio": moved / height,
                        "limit": limit,
                        "ok": moved / height <= limit + 1e-12,
                    }
                )
    if not out["combinations"] and (found.storeyDrift or found.sway):
        out["notes"].append(
            "wind serviceability not checked: the model has no wind cases (or the code pack's "
            "service combinations have none)"
        )
    return out


def worst(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Per direction the row with the largest ``key`` over its limit (the governing one)."""
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        u = r[key] / r["limit"] if r["limit"] else 0.0
        held = best.get(r["direction"])
        if held is None or u > held[key] / held["limit"]:
            best[r["direction"]] = r
    return [best[d] for d in sorted(best)]


def base_overturning(forces: np.ndarray, levels: list[float]) -> float:
    """Base overturning moment ΣFi (hi - hbase) of the level forces [N·m]."""
    z = np.asarray(levels, dtype=float)
    return float(np.sum(np.asarray(forces, dtype=float) * (z - z[0])))


def resisting_moment(supports: list[tuple[float, float, float]], axis: int) -> float:
    """The dead load's least resisting moment [N·m] about an edge of the supports across
    ``axis`` (0: a force along X tips the building about the line x = min or x = max):
    ``supports`` are (x, y, upward reaction R) of each support; ΣR × the distance from the
    edge the force tips it towards, the smaller of the two senses."""
    if not supports:
        return 0.0
    p = np.array([s[axis] for s in supports], dtype=float)
    r = np.array([s[2] for s in supports], dtype=float)
    if r.sum() < 0:  # reactions given downward positive
        r = -r
    about_max = float(np.sum(r * (p.max() - p)))
    about_min = float(np.sum(r * (p - p.min())))
    return min(about_max, about_min)


def overturning_checks(
    level_forces: Mapping[str, np.ndarray],
    levels: list[float],
    supports: list[tuple[float, float, float]],
) -> dict[str, Any]:
    """The overturning stability of the whole building: per lateral case (``level_forces``:
    case -> its forces at the levels along the case's axis [N]) ``{"case", "direction",
    "overturning", "resisting", "factor", "required", "ok"}`` (moments in N·m), with the pack's
    note and clause; ``supports`` the dead load's support reactions (x, y, R up) [m, N]."""
    found = table()
    group = found.overturning if found is not None else None
    out: dict[str, Any] = {"rows": [], "note": "", "clause": ""}
    if group is None:
        return out
    out["note"], out["clause"] = group.note, group.source or ""
    for case, forces in level_forces.items():
        if case not in LATERAL_CASES:
            continue
        axis = LATERAL_CASES[case]
        factor = float(group.lateralFactors.get(case[0], 1.0))
        moment = abs(factor * base_overturning(forces, levels))
        if moment <= 0:
            continue
        resist = resisting_moment(supports, axis)
        ratio = resist / moment
        out["rows"].append(
            {
                "case": case,
                "direction": "XY"[axis],
                "overturning": moment,
                "resisting": resist,
                "factor": ratio,
                "required": float(group.factorOfSafety),
                "ok": ratio >= float(group.factorOfSafety) - 1e-9,
            }
        )
    return out


def dead_supports(
    project: dict[str, Any], reactions: Mapping[str, Callable[[int], np.ndarray]]
) -> list[tuple[float, float, float]]:
    """(x, y, vertical reaction) of every support under the pack's resisting load kinds (the
    dead load D: cases D and SD). ``reactions``: case -> node id -> its reaction row."""
    from saengine.fem.combinations import KIND_CASES

    found = table()
    kinds = found.overturning.resisting if found is not None and found.overturning else ["D"]
    cases = [c for kind in kinds for c in KIND_CASES.get(kind, (kind,)) if c in reactions]
    # The floors' diaphragm nodes carry restraints but are no supports.
    retained = {c.get("retained_node") for c in project.get("mp_constraints", [])}
    out = []
    for node in project.get("nodes", []):
        if node["id"] in retained:
            continue
        if not any(node.get("restraint") or []) or len(node.get("coords", [])) < 3:
            continue
        r = sum(float(reactions[c](node["id"])[2]) for c in cases)
        out.append((float(node["coords"][0]), float(node["coords"][1]), r))
    return out


__all__ = [
    "LATERAL_CASES",
    "base_overturning",
    "base_shear_periods",
    "covered",
    "dead_supports",
    "overturning_checks",
    "resisting_moment",
    "storey_drift_limit",
    "sway_basis",
    "table",
    "unreinforced_axes",
    "wind_checks",
    "worst",
]

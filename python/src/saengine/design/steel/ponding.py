"""Roof ponding of steel roof framing (Part 6 Sec 10.16 of the code pack's ``steel`` table).

Two methods, both from the pack's ``ponding`` data:

- :func:`simplified` (Sec 10.16.1): the roof is stable for ponding with no further
  investigation when Cp + 0.9 Cs <= 0.25 (Eq 6.10.272) and Id >= 3940 S⁴ (Eq 6.10.273), with
  Cp = 504 Ls Lp⁴ / Ip and Cs = 504 S Ls⁴ / Is (lengths in m, inertias in mm⁴; Is of trusses
  and steel joists taken 15 % lower).
- :func:`improved` (Sec 10.16.2): the stress indexes Up and Us = (0.8 Fy - fo) / fo (Eqs
  6.10.274-275, fo the stress under D + R, R the rain or snow load without the ponding), and
  the limit curves of Figures 6.10.1 (limiting Cp by Up for each Cs) and 6.10.2 (limiting Cs
  by Us for each Cp), digitised in the pack. Primary and secondary framing passes when Cp is
  below the limit of Figure 6.10.1 and Cs below that of Figure 6.10.2; wall-bearing beams
  (secondary members on an infinitely stiff support) use Figure 6.10.2 with Cp = 0; a metal
  deck on beams is a secondary member of 1 m width (S = 1).

The rain load R comes from the user (or the rain load of the project once it is built): the
methods only check the stiffness and the stress indexes given. Units: m for the spans and
spacing, mm⁴ for the inertias, MPa for the stresses.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from saengine.codes import context as code_context


class PondingNotCovered(ValueError):
    """The code pack in force has no ponding data."""


def _table() -> Any:
    try:
        data = code_context.pack_table("steel").ponding
    except Exception:  # noqa: BLE001 - no pack machinery
        from saengine.codes.tables import builtin_table

        data = builtin_table("steel").ponding
    if data is None:
        raise PondingNotCovered("the code pack in force has no ponding provisions")
    return data


def flexibility(span_other: float, span: float, inertia: float) -> float:
    """C = coefficient × span_other × span⁴ / inertia (Cp: Ls, Lp, Ip; Cs: S, Ls, Is)."""
    return _table().coefficient * span_other * span**4 / inertia


def simplified(
    lp: float,
    ls: float,
    s: float,
    ip: float,
    is_: float,
    id_: float | None = None,
    secondary_truss: bool = False,
) -> dict[str, Any]:
    """The simplified ponding check: ``lp``/``ls`` the column spacing along and across the
    girders, ``s`` the spacing of the secondary members [m], ``ip``/``is_`` their inertias
    [mm⁴], ``id_`` the deck's inertia per m width [mm⁴/m] (None: no deck check),
    ``secondary_truss``: secondary trusses or steel joists (Is reduced)."""
    data = _table()
    is_eff = is_ * (data.trussFactor if secondary_truss else 1.0)
    cp = flexibility(ls, lp, ip)
    cs = flexibility(s, ls, is_eff)
    total = cp + data.secondary * cs
    checks = [
        {
            "name": "ponding stiffness Cp + 0.9 Cs",
            "demand": round(total, 4),
            "capacity": data.limit,
            "utilisation": round(total / data.limit, 3),
            "ok": total <= data.limit,
            "note": f"Sec 10.16.1 Eq 6.10.272: Cp = {cp:.4f}, Cs = {cs:.4f}",
        }
    ]
    if id_ is not None:
        need = data.deck * s**4
        checks.append(
            {
                "name": "deck inertia Id",
                "demand": round(need, 1),
                "capacity": round(id_, 1),
                "utilisation": round(need / id_, 3) if id_ > 0 else 99.0,
                "ok": id_ >= need,
                "note": f"Sec 10.16.1 Eq 6.10.273: Id >= {data.deck:g} S⁴",
            }
        )
    return {"method": "simplified", "Cp": cp, "Cs": cs, "checks": checks,
            "ok": all(c["ok"] for c in checks)}  # fmt: skip


def stress_index(fy: float, fo: float) -> float:
    """U = (stressLimit × Fy - fo) / fo (Eqs 6.10.274-275)."""
    return (_table().stressLimit * fy - fo) / fo


def _curve_x(points: list[tuple[float, float]], u: float) -> float:
    """The limit read from one digitised curve at the stress index ``u``: 0 below its start,
    linear between the points, held at the last point above (the figure's range)."""
    if u <= points[0][0]:
        return 0.0
    for (u1, x1), (u2, x2) in itertools.pairwise(points):
        if u <= u2:
            return x1 + (x2 - x1) * (u - u1) / (u2 - u1)
    return points[-1][1]


def _limit(curves: list[Any], u: float, param: float) -> float:
    """The limiting flexibility constant at stress index ``u`` between the curves of the
    parameter just below and just above ``param`` (linear); beyond the largest curve: 0."""
    ordered = sorted(curves, key=lambda c: c.param)
    if param <= ordered[0].param:
        return _curve_x(list(ordered[0].points), u)
    for lo, hi in itertools.pairwise(ordered):
        if param <= hi.param:
            xa = _curve_x(list(lo.points), u)
            xb = _curve_x(list(hi.points), u)
            return xa + (xb - xa) * (param - lo.param) / (hi.param - lo.param)
    return 0.0


def improved(
    up: float | None,
    us: float,
    cp: float,
    cs: float,
) -> dict[str, Any]:
    """The improved ponding check with the stress indexes ``up`` (None: wall-bearing beams,
    Cp = 0) and ``us`` and the flexibility constants ``cp`` and ``cs``."""
    data = _table()
    checks = []
    if up is not None:
        cp_max = _limit(data.primary, up, cs)
        checks.append(
            {
                "name": "primary members: Cp below the limit",
                "demand": round(cp, 4),
                "capacity": round(cp_max, 4),
                "utilisation": round(cp / cp_max, 3) if cp_max > 0 else 99.0,
                "ok": cp < cp_max,
                "note": f"Sec 10.16.2, Figure 6.10.1 at Up = {up:.2f}, Cs = {cs:.3f}",
            }
        )
    cs_max = _limit(data.secondaryCurves, us, 0.0 if up is None else cp)
    checks.append(
        {
            "name": "secondary members: Cs below the limit",
            "demand": round(cs, 4),
            "capacity": round(cs_max, 4),
            "utilisation": round(cs / cs_max, 3) if cs_max > 0 else 99.0,
            "ok": cs < cs_max,
            "note": f"Sec 10.16.2, Figure 6.10.2 at Us = {us:.2f}, Cp = "
            f"{0.0 if up is None else cp:.3f}",
        }
    )
    return {"method": "improved", "checks": checks, "ok": all(c["ok"] for c in checks)}


def check_ponding(
    lp: float,
    ls: float,
    s: float,
    ip: float,
    is_: float,
    fy: float,
    fo_primary: float | None = None,
    fo_secondary: float | None = None,
    id_: float | None = None,
    secondary_truss: bool = False,
) -> dict[str, Any]:
    """The simplified check, and when it fails and the stresses under D + R are given, the
    improved one (which then decides)."""
    first = simplified(lp, ls, s, ip, is_, id_, secondary_truss)
    if first["ok"] or fo_secondary is None:
        return first
    data = _table()
    is_eff = is_ * (data.trussFactor if secondary_truss else 1.0)
    up = stress_index(fy, fo_primary) if fo_primary else None
    us = stress_index(fy, fo_secondary)
    second = improved(up, us, first["Cp"], flexibility(s, ls, is_eff))
    second["simplified"] = first
    if math.isfinite(us) and us < 0:
        second["ok"] = False
        second["checks"].append(
            {
                "name": "secondary stress under D + R",
                "demand": fo_secondary,
                "capacity": data.stressLimit * fy,
                "utilisation": round(fo_secondary / (data.stressLimit * fy), 3),
                "ok": False,
                "note": "Eq 6.10.275: fo above 0.8 Fy, the stress index is negative",
            }
        )
    return second

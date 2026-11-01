"""Static pile load tests: interpreting the load-movement curve by the code pack (Part 9, deep
foundations).

A test (:class:`saengine.library.substructure.PileLoadTest`) is a pile type's curve of load
[kN] against movement [mm] at the pile head. The code pack's ``foundations.piles.loadTests``
group holds the criteria and its ``sources`` the clauses (the default pack: Secs 3.10.1.17,
3.10.1.21,
3.11.2-3.11.4); a pack without it does not cover them. The load at a movement is interpolated
on the curve; a criterion whose movement the test did not reach is taken at the largest test
load (on the safe side) and says so.

- **compression, single pile** (:func:`compression`): the safe load the lesser of
  ``movementShare`` × the load at ``movement`` and ``diameterLoadShare`` × the load at
  ``diameterShare`` D (``underReamedShare`` of the bulb of an under-reamed pile). An initial
  test also gives the ultimate load by the failure criteria, each where the curve defines it:
  Davisson's offset limit (the elastic shortening P L / (A E) plus ``davissonOffset`` + D /
  ``davissonDiameter``; for driven precast piles), the settlement of ``bsShare`` D, the lesser
  of that and the load at ``isMovement``, Butler and Hoy (the initial tangent meets the tangent
  where the curve's slope reaches ``butlerHoySlope`` mm per ``butlerHoyTon`` kN) and Brinch
  Hansen's (the settlement twice that under ``brinchHansenShare`` of the load); the least of
  them over ``failureSafety`` caps the safe load;
- **compression, group** : the lesser of ``groupMovementShare`` × the load at
  ``groupMovement`` and ``groupSecondShare`` × the load at ``groupSecondMovement``;
- **uplift** (:func:`uplift`): the lesser of ``movementShare`` × the load at ``movement`` and
  ``breakShare`` × the load at the clear break (with the break, also the break over
  ``failureSafety``);
- **lateral** (:func:`lateral`): the lesser of ``headShare`` × the load at ``headMovement`` and
  ``totalShare`` × the load at ``totalMovement``.

:func:`pile_type_tests` gathers a pile type's results: the governing safe load of each kind
and whether a compression test lets the capacity take the factor of safety with a load test.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from saengine.substructure import pile_static


def rules() -> Any | None:
    """The pack's load test rules, or None when the pack does not cover them."""
    found = pile_static.rules()
    return None if found is None else found.loadTests


def cite(key: str) -> str:
    from saengine.substructure.pile_detailing import cite as _cite

    return _cite(key)


def curve(points: list[Any]) -> list[tuple[float, float]]:
    """The curve's points (load, movement), from the origin, in the order of loading."""
    rows = [(float(q), float(s)) for q, s in points]
    if not rows or rows[0] != (0.0, 0.0):
        rows.insert(0, (0.0, 0.0))
    return rows


def load_at(points: list[tuple[float, float]], movement: float) -> tuple[float, bool]:
    """The load [kN] at which the curve first reaches ``movement`` [mm] (interpolated), and
    whether it does; the largest test load when it does not."""
    for (q0, s0), (q1, s1) in itertools.pairwise(points):
        if s0 >= movement:
            return q0, True
        if s1 >= movement:
            return q0 + (q1 - q0) * (movement - s0) / (s1 - s0), True
    return max(q for q, _ in points), False


def movement_at(points: list[tuple[float, float]], load: float) -> float | None:
    """The movement [mm] at ``load`` on the loading branch (interpolated); None beyond it."""
    for (q0, s0), (q1, s1) in itertools.pairwise(points):
        if q0 <= load <= q1 and q1 > q0:
            return s0 + (s1 - s0) * (load - q0) / (q1 - q0)
    return None


def loading_branch(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The points up to the largest load (the unloading branch left out)."""
    peak = max(range(len(points)), key=lambda k: points[k][0])
    return points[: peak + 1]


def _criterion(
    points: list[tuple[float, float]], movement: float, share: float, label: str
) -> dict[str, Any]:
    load, reached = load_at(points, movement)
    note = f"{share:.3g} × the load at {movement:.1f} mm ({label})"
    if not reached:
        note += f": not reached, taken at the largest test load {load:.0f} kN"
    return {"name": label, "value": share * load, "load": load, "reached": reached, "note": note}


def davisson(
    points: list[tuple[float, float]], diameter: float, length: float, area: float, ep: float
) -> float | None:
    """Davisson's offset limit [kN]: the first load where the curve reaches PL/(AE) + offset
    + D / divisor (``diameter``, ``length`` mm, ``area`` mm², ``ep`` MPa); None if never."""
    found = rules()
    if found is None or area <= 0 or ep <= 0:
        return None
    c = found.compression
    offset = c.davissonOffset + diameter / c.davissonDiameter
    elastic = length / (area * ep) * 1e3  # mm per kN

    def gap(q: float, s: float) -> float:
        return s - (elastic * q + offset)

    for (q0, s0), (q1, s1) in itertools.pairwise(points):
        g0, g1 = gap(q0, s0), gap(q1, s1)
        if g1 >= 0 > g0:
            return q0 + (q1 - q0) * (-g0) / (g1 - g0)
    return None


def butler_hoy(points: list[tuple[float, float]]) -> float | None:
    """Butler and Hoy's failure load [kN]: the initial tangent meets the tangent at the point
    where the curve's slope first reaches the pack's slope; None when it never does."""
    found = rules()
    if found is None or len(points) < 3:
        return None
    c = found.compression
    target = c.butlerHoySlope / c.butlerHoyTon  # mm/kN
    (q0, s0), (q1, s1) = points[0], points[1]
    if q1 <= q0:
        return None
    initial = (s1 - s0) / (q1 - q0)
    for (qa, sa), (qb, sb) in itertools.pairwise(points):
        if qb <= qa:
            continue
        if (sb - sa) / (qb - qa) >= target:
            if initial >= target:
                return None
            # the tangent through (qa, sa) of slope target meets s = initial q
            return (sa - target * qa) / (initial - target)
    return None


def brinch_hansen(points: list[tuple[float, float]]) -> float | None:
    """Brinch Hansen's failure load [kN]: the load whose settlement is twice that under the
    pack's share of it; None within the curve when there is none."""
    found = rules()
    if found is None:
        return None
    share = found.compression.brinchHansenShare
    loads = [q for q, _ in points if q > 0]

    def f(q: float) -> float | None:
        s, s9 = movement_at(points, q), movement_at(points, share * q)
        if s is None or s9 is None:
            return None
        return s - 2 * s9

    previous = None
    for q in loads:
        value = f(q)
        if value is None:
            continue
        if value >= 0:
            if previous is None:
                return q
            low, high = previous[0], q
            for _ in range(60):  # bisection: f is piecewise linear in two scales
                mid = (low + high) / 2
                f_mid = f(mid)
                if f_mid is not None and f_mid >= 0:
                    high = mid
                else:
                    low = mid
            return high
        previous = (q, value)
    return None


def compression(test: Any, pile_type: Any, ep: float) -> dict[str, Any]:
    """A compression test's safe load and failure loads (see the module notes)."""
    found = rules()
    c = found.compression
    points = loading_branch(curve(test.points))
    d = float(pile_type.diameter)
    source = cite("loadTests.compression")
    methods: list[dict[str, Any]] = []
    if test.group:
        criteria = [
            _criterion(points, c.groupMovement, c.groupMovementShare, "group"),
            _criterion(points, c.groupSecondMovement, c.groupSecondShare, "group"),
        ]
    else:
        bulb = getattr(test, "bulbDiameter", None)
        at = (c.underReamedShare * bulb) if bulb else c.diameterShare * d
        criteria = [
            _criterion(points, c.movement, c.movementShare, "single pile"),
            _criterion(points, at, c.diameterLoadShare, "single pile"),
        ]
    safe = min(r["value"] for r in criteria)
    basis = "; ".join(r["note"] for r in criteria)
    ultimate = None
    if test.test == "initial" and not test.group:
        from saengine.substructure.piles import section_shape

        area = section_shape(pile_type.kind, d)[1]
        candidates = []
        if pile_type.kind == "driven":
            candidates.append(("Davisson offset limit", davisson(points, d, pile_type.length,
                                                                  area, ep)))  # fmt: skip
        bs, bs_reached = load_at(points, c.bsShare * d)
        candidates.append((f"settlement {100 * c.bsShare:g} % of D", bs if bs_reached else None))
        is_load, is_reached = load_at(points, c.isMovement)
        if bs_reached or is_reached:
            least = min(v for v, ok in ((bs, bs_reached), (is_load, is_reached)) if ok)
            candidates.append((f"lesser of {100 * c.bsShare:g} % of D and {c.isMovement:g} mm",
                               least))  # fmt: skip
        candidates.append(("Butler and Hoy", butler_hoy(points)))
        candidates.append(("Brinch Hansen 90 %", brinch_hansen(points)))
        for name, value in candidates:
            methods.append({"name": name, "value": None if value is None else round(value, 1)})
        defined = [v for _, v in candidates if v is not None]
        if defined:
            ultimate = min(defined)
            by_failure = ultimate / c.failureSafety
            if by_failure < safe:
                safe = by_failure
                basis += (
                    f"; governed by the least failure load {ultimate:.0f} kN / {c.failureSafety:g}"
                )
    return {
        "id": test.id,
        "pileType": test.pileType,
        "kind": "compression",
        "test": test.test,
        "group": bool(test.group),
        "maxLoad": max(q for q, _ in points),
        "safe": round(safe, 1),
        "ultimate": None if ultimate is None else round(ultimate, 1),
        "methods": methods,
        "basis": basis,
        "source": source,
    }


def uplift(test: Any) -> dict[str, Any]:
    """An uplift test's safe load (see the module notes)."""
    u = rules().uplift
    points = loading_branch(curve(test.points))
    criteria = [_criterion(points, u.movement, u.movementShare, "uplift")]
    ultimate = None
    if test.breakLoad:
        criteria.append(
            {
                "name": "break",
                "value": u.breakShare * test.breakLoad,
                "note": f"{u.breakShare:.3g} × the load at the clear break {test.breakLoad:.0f} kN",
            }
        )
        ultimate = float(test.breakLoad)
        criteria.append(
            {
                "name": "failure",
                "value": ultimate / u.failureSafety,
                "note": f"the break as the ultimate load / {u.failureSafety:g}",
            }
        )
    safe = min(r["value"] for r in criteria)
    return {
        "id": test.id,
        "pileType": test.pileType,
        "kind": "uplift",
        "test": test.test,
        "group": False,
        "maxLoad": max(q for q, _ in points),
        "safe": round(safe, 1),
        "ultimate": ultimate,
        "methods": [],
        "basis": "; ".join(r["note"] for r in criteria),
        "source": cite("loadTests.uplift"),
    }


def lateral(test: Any) -> dict[str, Any]:
    """A lateral test's safe load (see the module notes)."""
    lat = rules().lateral
    points = loading_branch(curve(test.points))
    criteria = [
        _criterion(points, lat.headMovement, lat.headShare, "head movement"),
        _criterion(points, lat.totalMovement, lat.totalShare, "total displacement"),
    ]
    return {
        "id": test.id,
        "pileType": test.pileType,
        "kind": "lateral",
        "test": test.test,
        "group": False,
        "maxLoad": max(q for q, _ in points),
        "safe": round(min(r["value"] for r in criteria), 1),
        "ultimate": None,
        "methods": [],
        "basis": "; ".join(r["note"] for r in criteria),
        "source": cite("loadTests.lateral"),
    }


def interpret(test: Any, pile_type: Any, ep: float) -> dict[str, Any] | None:
    """A test's result by its kind, or None when the pack does not cover load tests or the
    curve has no load."""
    if rules() is None or not test.points or max(q for q, _ in test.points) <= 0:
        return None
    if test.kind == "uplift":
        return uplift(test)
    if test.kind == "lateral":
        return lateral(test)
    return compression(test, pile_type, ep)


def pile_type_tests(tests: list[Any], pile_type: Any, ep: float) -> dict[str, Any]:
    """A pile type's tests: ``{"results", "compression", "group", "uplift", "lateral",
    "loadTest", "notes"}``, each kind's governing (least safe) result or None, and whether a
    single-pile compression test lets the capacity take the factor of safety with a test."""
    results = []
    notes = []
    if rules() is None and any(t.pileType == pile_type.id for t in tests):
        notes.append(pile_static.not_covered("Pile load test interpretation"))
    for test in tests:
        if test.pileType != pile_type.id:
            continue
        result = interpret(test, pile_type, ep)
        if result is not None:
            results.append(result)

    def least(kind: str, group: bool = False) -> dict[str, Any] | None:
        rows = [r for r in results if r["kind"] == kind and r["group"] == group]
        return min(rows, key=lambda r: r["safe"]) if rows else None

    single = least("compression")
    return {
        "results": results,
        "compression": single,
        "group": least("compression", True),
        "uplift": least("uplift"),
        "lateral": least("lateral"),
        "loadTest": single is not None,
        "notes": notes,
    }


def adequacy_checks(
    found: dict[str, Any], design: dict[str, float], piles: int, tested_piles: int, kind: str
) -> list[dict[str, Any]]:
    """Whether the tests went far enough: each test's largest load against the pack's
    multiple of its design load (``design``: per kind the design load per pile [kN]), and the
    number of tests against the pack's share of the piles (reported only)."""
    from saengine.design.check import _check

    rules_ = rules()
    if rules_ is None:
        return []
    checks = []
    for result in found["results"]:
        kind_ = result["kind"]
        load = design.get("group" if result["group"] else kind_)
        if not load:
            continue
        if kind_ == "lateral":
            factor = rules_.lateral.testLoad
        else:
            table = rules_.uplift.testLoad if kind_ == "uplift" else rules_.compression.testLoad
            factor = getattr(table, result["test"])
        checks.append(
            _check(
                f"Load test {result['id']}: test load",
                factor * load,
                result["maxLoad"],
                "kN",
                None,
                f"{result['test']} {kind_} test to at least {factor:g} × the design load "
                f"{load:.0f} kN ({result['source']})",
                flag=True,
            )
        )
    c = rules_.compression
    need = max(math.ceil(c.minShare * piles - 1e-9), c.minBored if kind == "bored" else 0)
    if piles and need:
        checks.append(
            _check(
                "Pile load tests: number",
                need,
                tested_piles,
                "tests",
                None,
                f"at least {100 * c.minShare:g} % of the {piles} piles of the type in each area of "
                f"uniform soil (major projects), at least {c.minBored} for bored piles "
                f"({cite('loadTests.compression')}). Reported only",
                flag=True,
            )
        )
    return checks

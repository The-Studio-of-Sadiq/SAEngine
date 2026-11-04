"""Development and lap lengths of deformed bars by the basic length and its factors k1-k3
(method ``developmentFactors`` of the pack's ``concreteMethods.anchorage``; alpha 9 C18c, the
form of AS 3600:2018 13.1 and 13.2).

- Tension (``tension_length``): ``Lsy.tb = coefficient k1 k3 fsy db / (k2 √f'c)``, at least
  ``minCoefficient`` fsy k1 db; k1 = ``topFactor`` for a horizontal bar with more than
  ``topDepth`` mm of concrete cast below it (the top bars of beams deeper than that), else 1;
  k2 = (a - db) / b (``barFactor``); k3 = 1 - c (cd - db) / db within the pack's range
  (``coverFactor``), cd the smaller of the cover and half the clear spacing (db, so k3 = 1,
  where not known: on the safe side); √f'c with f'c at most ``fcMax``.
- Hooks and cogs (``hook_length``): ``hookShare`` Lsy.tb.
- Compression (``compression_length``): ``Lsy.c = a fsy db / √f'c`` at least ``b fsy db`` and
  ``c`` mm (``compression``).
- Laps in tension (``lap_tension``): ``lapFactor`` Lsy.t at least ``lapMinCoefficient`` k1 db;
  in compression (``lap_compression``): Lsy.c at least ``compressionLap`` (n db, mm).

Units: mm, MPa.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context

METHOD = "developmentFactors"


def rules() -> Any | None:
    """The pack's ``concreteMethods.anchorage`` when it is this method (None otherwise)."""
    try:
        pack = code_context.current()
    except Exception:  # noqa: BLE001 - no pack machinery
        return None
    if not pack.has("concreteMethods"):
        return None
    table = pack.table("concreteMethods")
    if "anchorage" in (getattr(table, "parentMethods", None) or ()):
        return None
    from saengine.codes.method_tables import chosen

    return chosen(table, "anchorage", METHOD)


def cite(key: str = "anchorage") -> str:
    return code_context.cite("concreteMethods", key)


def _root(fc: float, r: Any) -> float:
    return math.sqrt(min(fc, r.fcMax))


def factors(db: float, top: bool, cd: float | None, depth: float | None = None) -> dict:
    """k1, k2, k3 of a bar ``db`` (``top``: a top bar of a member whose depth below it exceeds
    ``topDepth``; ``depth`` the member's depth where known, else a top bar takes k1)."""
    r = rules()
    deep = top and (depth is None or depth > r.topDepth)
    k1 = r.topFactor if deep else 1.0
    a, b = r.barFactor
    k2 = (a - db) / b
    c, low, high = r.coverFactor
    cd_used = db if cd is None else cd
    k3 = min(max(1 - c * (cd_used - db) / db, low), high)
    return {"k1": k1, "k2": k2, "k3": k3, "cd": cd_used}


def tension_length(
    db: float, fy: float, fc: float, top: bool = False, cd: float | None = None
) -> dict[str, float]:
    """Lsy.tb [mm] and its terms."""
    r = rules()
    k = factors(db, top, cd)
    basic = r.coefficient * k["k1"] * k["k3"] * fy * db / (k["k2"] * _root(fc, r))
    least = r.minCoefficient * fy * k["k1"] * db
    return {**k, "basic": basic, "least": least, "length": max(basic, least)}


def hook_length(db: float, fy: float, fc: float, top: bool = False, cd: float | None = None):
    """The development length of a hooked or cogged bar [mm] and the terms."""
    found = tension_length(db, fy, fc, top, cd)
    return {**found, "length": rules().hookShare * found["length"]}


def compression_length(db: float, fy: float, fc: float) -> dict[str, float]:
    """Lsy.c [mm]."""
    r = rules()
    a, b, mm = r.compression
    value = max(a * fy * db / _root(fc, r), b * fy * db, mm)
    return {"length": value, "basic": a * fy * db / _root(fc, r)}


def lap_tension(
    db: float, fy: float, fc: float, top: bool = False, cd: float | None = None
) -> dict[str, float]:
    """The tension lap [mm]: lapFactor Lsy.t, at least lapMinCoefficient k1 db."""
    r = rules()
    found = tension_length(db, fy, fc, top, cd)
    value = max(r.lapFactor * found["length"], r.lapMinCoefficient * found["k1"] * db)
    return {**found, "lap": value}


def lap_compression(db: float, fy: float, fc: float) -> dict[str, float]:
    """The compression lap [mm]: Lsy.c, at least the pack's n db and mm."""
    r = rules()
    n, mm = r.compressionLap
    found = compression_length(db, fy, fc)
    return {**found, "lap": max(found["length"], n * db, mm)}


def tension_text(found: dict[str, float]) -> str:
    r = rules()
    return (
        f"Lsy.tb = {r.coefficient:g} k1 k3 fsy db / (k2 √f'c) at least {r.minCoefficient:g} fsy "
        f"k1 db, k1 = {found['k1']:g}, k2 = {found['k2']:.2f}, k3 = {found['k3']:.2f}"
    )


def method_text() -> str:
    r = rules()
    return (
        f"Lsy.tb = {r.coefficient:g} k1 k3 fsy db / (k2 √f'c) >= {r.minCoefficient:g} fsy k1 db, "
        f"hooks {r.hookShare:g} Lsy.tb, laps {r.lapFactor:g} Lsy.t >= {r.lapMinCoefficient:g} k1 "
        f"db ({cite()}, {cite('laps')})"
    )

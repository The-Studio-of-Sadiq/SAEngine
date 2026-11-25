"""Load patterns: the project's own load cases beside the built-in D, SD, L and Lr (issue #301).

The analysis model has a fixed set of load cases (``saengine.fem.derive.CASES``): the dead load D
(self-weight), the superimposed dead load SD, the live loads L and Lr, the wind and earthquake
cases and the cases the program adds itself. Engineers also need cases of their own: a
construction load, a piece of equipment, a special load to check apart. Those are the project's
**load patterns** (``ProjectSettings.loadPatterns``): each has

- an ``id``, the case's code in the analysis model, the combinations and the result tables
  ("EQP", "CONST"; it may not be a code the program uses itself, :func:`reserved`);
- a ``name`` (its description) and a ``type`` (Dead, Superimposed dead, Live, Roof live, Wind,
  Seismic or Other);
- a ``selfWeight`` multiplier: that many times the structure's self-weight is added to the
  pattern (0: none; the built-in D carries the self-weight once).

The **type** says how the pattern combines, never a code's name: the code pack's combinations
are rows of factors on load kinds (D, L, Lr, W, E, ...), and a user pattern takes the factor of
its type's kind (:data:`TYPE_KIND`): a Dead pattern takes the D factor, a Live one the L factor.
A pattern of type Other is in no generated combination; the engineer gives its factors. The type
also says how much of the pattern counts in the seismic weight (as D, SD or L do).

Member loads, point loads and the area loads' "other load" name a pattern by its id. A project
without patterns has none, and its files are unchanged.
"""

from __future__ import annotations

import re
from typing import Any, Literal

#: The built-in load patterns: (id, name, type). D carries the self-weight (multiplier 1).
BUILT_IN: tuple[tuple[str, str, str], ...] = (
    ("D", "Dead", "Dead"),
    ("SD", "Superimposed dead", "SuperDead"),
    ("L", "Live", "Live"),
    ("Lr", "Roof live", "RoofLive"),
)
BUILT_IN_IDS = frozenset(pid for pid, _, _ in BUILT_IN)

LoadPatternType = Literal["Dead", "SuperDead", "Live", "RoofLive", "Wind", "Seismic", "Other"]
TYPE_LABELS: dict[str, str] = {
    "Dead": "Dead",
    "SuperDead": "Superimposed dead",
    "Live": "Live",
    "RoofLive": "Roof live",
    "Wind": "Wind",
    "Seismic": "Seismic",
    "Other": "Other",
}

#: The code pack's factor kind each type takes in the generated combinations (None: in none).
TYPE_KIND: dict[str, str | None] = {
    "Dead": "D",
    "SuperDead": "D",
    "Live": "L",
    "RoofLive": "Lr",
    "Wind": "W",
    "Seismic": "E",
    "Other": None,
}

#: The built-in case a type counts as in the seismic weight and the mass source.
TYPE_WEIGHT_CASE: dict[str, str] = {
    "Dead": "D",
    "SuperDead": "SD",
    "Live": "L",
    "RoofLive": "Lr",
    "Wind": "other",
    "Seismic": "other",
    "Other": "other",
}

#: Case codes the analysis model uses itself (a user pattern may not take one; compared without
#: regard to case, so "d" is not taken for D either).
_RESERVED = frozenset(
    {
        *BUILT_IN_IDS,
        *("WX", "WY", "EX", "EY", "F", "H", "T", "ST", "CS", "R", "FaX", "FaY", "S"),
        *("EXP", "EXN", "EYP", "EYN", "WTX", "WTY", "WI", "WXN", "WYN", "EZ", "E"),
        *("RX", "RY", "AX", "AY", "W", "Fa", "MODAL"),
    }
)
_RESERVED_LOWER = frozenset(c.lower() for c in _RESERVED)
#: Generated families: live load arrangements LP1.., tension-only releases TO1.., crane cases
#: C1.., wind variants WX2.., WYN3...
_RESERVED_FAMILIES = re.compile(r"^(LP\d+|TO\d+|C\d.*|W[XY]N?\d+)$", re.IGNORECASE)


def reserved(pattern_id: str) -> bool:
    """Whether ``pattern_id`` is a case code the program uses itself."""
    return pattern_id.lower() in _RESERVED_LOWER or bool(_RESERVED_FAMILIES.match(pattern_id))


def user_patterns(settings: Any) -> list[Any]:
    """The project's own load patterns (``settings.loadPatterns``; none for older settings)."""
    return list(getattr(settings, "loadPatterns", None) or [])


def all_patterns(settings: Any) -> list[dict[str, Any]]:
    """Every load pattern of the project, the built-in ones first: ``{id, name, type,
    selfWeight, builtIn}`` (for the editors' lists)."""
    out: list[dict[str, Any]] = [
        {
            "id": pid,
            "name": name,
            "type": kind,
            "selfWeight": 1.0 if pid == "D" else 0.0,
            "builtIn": True,
        }
        for pid, name, kind in BUILT_IN
    ]
    for p in user_patterns(settings):
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "type": p.type,
                "selfWeight": p.selfWeight,
                "builtIn": False,
            }
        )
    return out


def pattern_ids(settings: Any) -> set[str]:
    """The ids of every load pattern a load may name: the built-in ones and the project's."""
    return set(BUILT_IN_IDS) | {p.id for p in user_patterns(settings)}


def weight_case(settings: Any, case: str) -> str:
    """The built-in case ``case`` counts as in the seismic weight: itself for a built-in case,
    its type's (:data:`TYPE_WEIGHT_CASE`) for a user pattern."""
    for p in user_patterns(settings):
        if p.id == case:
            return TYPE_WEIGHT_CASE.get(p.type, "other")
    return case


def kind_patterns(settings: Any) -> dict[str, list[str]]:
    """Code pack factor kind -> the user patterns that take its factor (:data:`TYPE_KIND`)."""
    out: dict[str, list[str]] = {}
    for p in user_patterns(settings):
        kind = TYPE_KIND.get(p.type)
        if kind:
            out.setdefault(kind, []).append(p.id)
    return out


def pattern_factors(
    factors: dict[str, float], settings: Any, *, positive_lateral: bool = True
) -> dict[str, float]:
    """The factors a generated combination gives the user patterns: ``factors`` are a pack row's
    (expanded) ``{kind or case: factor}``. A pattern takes its type's kind factor: D, L, Lr as
    they are; a Wind (Seismic) pattern the largest positive factor on WX/WY (EX/EY) of the row,
    so it acts as entered with the wind (earthquake) and is not reversed (a pattern has its own
    direction). With ``positive_lateral`` False, lateral patterns are left out."""
    out: dict[str, float] = {}
    for kind, ids in kind_patterns(settings).items():
        if kind in ("W", "E"):
            if not positive_lateral:
                continue
            values = [v for k, v in factors.items() if k in (f"{kind}X", f"{kind}Y") and v > 0]
            value = max(values) if values else 0.0
        else:
            value = float(factors.get(kind, 0.0) or 0.0)
        if value:
            for pid in ids:
                out[pid] = value
    return out


def loads_using(pattern_id: str, member_loads_text: str | None) -> int:
    """How many member loads (``05 Floor Plan/loads.json``) are in ``pattern_id``."""
    from saengine.library import line_loads

    try:
        loads = line_loads.parse(member_loads_text)
    except ValueError:
        return 0
    return sum(1 for load in loads.loads if load.case == pattern_id)


def deletion_problem(
    settings: Any, pattern_id: str, member_loads_text: str | None = None
) -> str | None:
    """Why ``pattern_id`` may not be deleted (None: it may): a built-in pattern, or one that
    member loads or area loads still use. The combinations' factors on it are dropped with it."""
    if pattern_id in BUILT_IN_IDS:
        return f"{pattern_id} is a built-in load pattern and cannot be deleted"
    count = loads_using(pattern_id, member_loads_text)
    areas = [
        a.id
        for a in getattr(settings, "areaLoads", [])
        if getattr(a, "otherPattern", None) == pattern_id
    ]
    where = []
    if count:
        where.append(f"{count} member load(s) on the floor plan")
    if areas:
        where.append(f"area load(s) {', '.join(areas)}")
    if where:
        return (
            f"load pattern {pattern_id} has loads ({'; '.join(where)}): move them to another "
            "pattern or delete them first"
        )
    return None

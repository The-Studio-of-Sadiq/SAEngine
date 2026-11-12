"""When the code pack requires a performance-based design (alpha 9 C21).

A pack's ``seismic.performanceBased`` block (:class:`saengine.codes.tables.PerformanceBasedRules`;
TBDY 2018 3.3, 3.4 and Chapter 13 type) gives the building height classes by the building's
height above the base and its design category, and the rules (height classes or design
categories) that ask for performance objectives: a hazard level, the performance level to meet
there and the analysis that shows it (an elastic response spectrum analysis, the strength-based
design, the Pushover analysis or the Nonlinear time history analysis).

SAEngine reports the requirement in the analysis notes and names the procedures that carry it
out; it does not run them (the engineer runs the Pushover and the Nonlinear time history
analyses with the pack's hazard levels). Without the block nothing is reported (not covered).

Units: m.
"""

from __future__ import annotations

from typing import Any

from saengine.codes import context as code_context

#: How each procedure of a performance objective is named in the notes.
PROCEDURES = {
    "linear": "an elastic response spectrum analysis",
    "strength": "the strength-based design",
    "pushover": "the Pushover analysis",
    "nonlinearHistory": "the Nonlinear time history analysis",
}


def rules(pack: Any = None) -> Any | None:
    """The pack's ``seismic.performanceBased`` block (default: the pack in force), or None."""
    table = pack.table("seismic") if pack is not None else code_context.table("seismic")
    return getattr(table, "performanceBased", None)


def height_class(height: float, category: str | None, block: Any) -> Any | None:
    """The first of the block's ``heightClasses`` whose least height of the category's column
    (``columns``; 'all' where the class gives no such column) ``height`` exceeds; None when
    the height is not positive or no class holds."""
    if height is None or height <= 0:
        return None
    column = block.columns.get(str(category)) if category is not None else None
    for found in block.heightClasses:
        limit = found.above.get(column) if column is not None else None
        if limit is None:
            limit = found.above.get("all")
        if limit is None:
            continue
        if height > float(limit) + 1e-9:
            return found
    return None


def requirements(height: float, category: str | None, pack: Any = None) -> dict[str, Any] | None:
    """``{"heightClass", "heightLabel", "rules"}`` for a building ``height`` [m] above the base
    in design category ``category``: the height class (None without one) and the rules that
    apply (an empty list: no performance-based design required); None without the block."""
    block = rules(pack)
    if block is None:
        return None
    found = height_class(height, category, block)
    applying = [
        rule
        for rule in block.rules
        if (found is not None and found.id in rule.classes)
        or (category is not None and str(category) in rule.categories)
    ]
    return {"heightClass": found, "heightLabel": block.heightLabel, "rules": applying}


def notes(height: float, category: str | None, pack: Any = None) -> list[str]:
    """The analysis notes of :func:`requirements`: the building's height class and, for each
    rule that applies, its performance objectives with the procedure of each."""
    found = requirements(height, category, pack)
    if found is None:
        return []
    block = rules(pack)
    out: list[str] = []
    cls = found["heightClass"]
    if cls is not None:
        label = f" ({cls.label})" if cls.label else ""
        out.append(
            f"performance: {found['heightLabel']} {cls.id}{label} for the height {height:.1f} m"
            + (f" in design category {category}" if category else "")
            + (f" ({block.clause})" if block.clause else "")
        )
    for rule in found["rules"]:
        objectives = "; ".join(
            f"{o.hazard}: {o.level} by {PROCEDURES.get(o.procedure, o.procedure)}"
            + (f" ({o.label})" if o.label else "")
            for o in rule.objectives
        )
        what = rule.label or "this building"
        clause = f" ({rule.clause})" if rule.clause else ""
        out.append(
            f"performance-based design required for {what}{clause}: {objectives}. SAEngine "
            "does not run these by itself: run the procedures named with the pack's hazard levels"
        )
    return out

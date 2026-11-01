"""Fatigue of steel members and connections under repeated loading, by stress range.

The method of the code pack's ``fatigue`` table (default pack BNBC 2020 Part 6 Sec 10.17 with its pack):

- the stress range is the change in service stress when the live load is applied or removed;
  under stress reversal, the sum of the two extremes;
- no evaluation when the number of cycles is below ``minCycles`` or the stress range is below
  the category's threshold F_TH;
- otherwise the stress range must not exceed the design stress range
  F_SR = (Cf × constant / N) ^ exponent ≥ F_TH, Cf and F_TH by stress category, N the cycles in
  the design life (per day × 365 × years);
- the largest stress under unfactored loads is at most ``maxServiceStress`` × Fy.

The engineer picks the stress category of the governing detail; the table's ``categories``
list them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context

DAYS_PER_YEAR = 365


def cycles(per_day: float, years: float) -> float:
    """Stress range fluctuations in the design life: per day × 365 × years."""
    return float(per_day) * DAYS_PER_YEAR * float(years)


def design_stress_range(category: str, n: float, table: Any | None = None) -> float:
    """F_SR [MPa] of ``category`` for ``n`` cycles (never below its threshold)."""
    table = table or code_context.table("fatigue")
    row = table.categories.get(category)
    if row is None:
        raise KeyError(
            f"no fatigue stress category '{category}' in the code pack "
            f"(categories: {', '.join(table.categories)})"
        )
    equation = table.equations[row.equation]
    value = (row.Cf * equation.constant / max(float(n), 1.0)) ** equation.exponent
    return float(max(value, row.threshold))


@dataclass
class FatigueResult:
    category: str
    cycles: float
    stress_range: float  # MPa
    design_range: float | None  # MPa; None when exempt
    max_stress: float  # MPa, unfactored
    max_allowed: float  # MPa
    exempt: str  # why no evaluation is needed ("" when evaluated)
    ok: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "cycles": round(self.cycles),
            "stressRange_MPa": round(self.stress_range, 1),
            "designRange_MPa": None if self.design_range is None else round(self.design_range, 1),
            "ratio": (
                round(self.stress_range / self.design_range, 3) if self.design_range else None
            ),
            "maxStress_MPa": round(self.max_stress, 1),
            "maxAllowed_MPa": round(self.max_allowed, 1),
            "exempt": self.exempt,
            "ok": self.ok,
        }


def check(
    category: str,
    n: float,
    stress_range: float,
    max_stress: float,
    fy: float,
    table: Any | None = None,
) -> FatigueResult:
    """The fatigue check of one detail: ``stress_range`` and ``max_stress`` (unfactored) [MPa]."""
    table = table or code_context.table("fatigue")
    row = table.categories.get(category)
    if row is None:
        raise KeyError(f"no fatigue stress category '{category}' in the code pack")
    allowed = table.maxServiceStress * fy
    stress_ok = max_stress <= allowed + 1e-9
    exempt = ""
    if n < table.minCycles:
        exempt = f"{n:,.0f} cycles, fewer than {table.minCycles:,.0f}"
    elif stress_range < row.threshold:
        exempt = f"stress range below the threshold {row.threshold:g} MPa"
    if exempt:
        return FatigueResult(
            category, n, stress_range, None, max_stress, allowed, exempt, stress_ok
        )
    design = design_stress_range(category, n, table)
    return FatigueResult(
        category,
        n,
        stress_range,
        design,
        max_stress,
        allowed,
        "",
        stress_ok and stress_range <= design + 1e-9,
    )

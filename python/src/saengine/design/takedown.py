"""The gravity load takedown of the columns: per column line and storey, the axial load of each
gravity case at the column's foot (cumulative, all the floors above) and what the storey adds.

The loads come from the analysis (the unfactored cases D, SD, L and Lr of the analysis model;
the default pack's BNBC 2020 Part 6 Sec 2.2 and 2.3 loads), so they include the frame's redistribution, unlike a
tributary-area takedown. A column line is the columns standing on one another (the same plan
position, each one's foot at the top of the one below). The unfactored total D + SD + L + Lr and
the factored 1.2(D + SD) + 1.6L + 0.5Lr (Sec 2.7.3.1, combination 2) are given with them; the
live load is the analysis's, unreduced (Sec 2.3.13 reduces it member by member in the design).

Forces in kN, compression positive.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from saengine.design.clauses import clause

__all__ = ["CASES", "NOTE", "takedown"]  # noqa: F822 - NOTE: module __getattr__


def __getattr__(name: str) -> str:
    # ``NOTE``: the method note of the takedown, with the pack's combination clause.
    if name == "NOTE":
        return (
            "Column axial loads from the analysis's gravity cases at each column's foot "
            "(cumulative: the floors above; storey: what the storey adds), compression positive; "
            "total D + SD + L + Lr and factored 1.2(D + SD) + 1.6L + 0.5Lr "
            f"({clause('takedown', 'combinations')}); live load unreduced"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


#: The gravity cases of the table, in order.
CASES = ("D", "SD", "L", "Lr")


def _foot_axial(pieces: list[Any], forces: dict[int, Any]) -> float | None:
    """Compression [N] at the lowest end of a column's pieces under one case."""
    rows = [(p, forces.get(p.id)) for p in pieces]
    rows = [(p, np.asarray(r, dtype=float)) for p, r in rows if r is not None and len(r)]
    if not rows:
        return None
    piece, values = min(rows, key=lambda pr: min(float(pr[0].start[2]), float(pr[0].end[2])))
    at_start = float(piece.start[2]) <= float(piece.end[2])
    return -float(values[0 if at_start else -1][0])


def takedown(
    building: Any, pieces: dict[str, list[Any]], service: dict[str, Any]
) -> dict[str, Any]:
    """``{"lines": [{"line", "position", "rows": [{"story", "column", "cumulative": {case:
    kN}, "storey": {case: kN}, "total", "factored"}]}], "cases", "note"}``, rows top down."""
    from saengine.library.bim import ColumnElement

    by_case = service.get("forces") or {}
    cases = [c for c in CASES if c in by_case]
    found: dict[str, Any] = {"lines": [], "cases": cases, "note": __doc__.split("\n\n")[1]}
    if not cases:
        return found
    stories = sorted(building.stories, key=lambda s: float(s.elevation))
    lines: dict[tuple[float, float], list[Any]] = {}
    for e in building.elements:
        if isinstance(e, ColumnElement) and e.id in pieces:
            key = (round(float(e.position[0])), round(float(e.position[1])))
            lines.setdefault(key, []).append(e)
    for key, columns in sorted(lines.items()):
        columns.sort(key=lambda c: -float(c.top))
        rows: list[dict[str, Any]] = []
        for column in columns:
            loads = {}
            for case in cases:
                value = _foot_axial(pieces[column.id], by_case[case])
                loads[case] = round(value / 1e3, 1) if value is not None else 0.0
            story = next(
                (s.name for s in stories if abs(float(s.elevation) - float(column.top)) <= 1.0),
                f"{float(column.top) / 1e3:g} m",
            )
            rows.append({"story": story, "column": column.id, "cumulative": loads})
        for k, row in enumerate(rows):
            above = rows[k - 1]["cumulative"] if k > 0 else dict.fromkeys(cases, 0.0)
            row["storey"] = {c: round(row["cumulative"][c] - above[c], 1) for c in cases}
            load = row["cumulative"]
            row["total"] = round(sum(load.values()), 1)
            row["factored"] = round(
                1.2 * (load.get("D", 0.0) + load.get("SD", 0.0))
                + 1.6 * load.get("L", 0.0)
                + 0.5 * load.get("Lr", 0.0),
                1,
            )
        found["lines"].append({"line": columns[-1].id, "position": [key[0], key[1]], "rows": rows})
    return found

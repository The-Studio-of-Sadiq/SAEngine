"""Pattern live loading: the arrangements of live load BNBC 2020 asks the frames to be designed
for, as extra live load cases and the combinations that use them.

BNBC 2020 Part 6 Sec 6.1.12.2 (p. 894): "Arrangement of live load shall be permitted to be
assumed to be limited to combinations of: (a) factored dead load on all spans with full factored
live load on two adjacent spans; and (b) factored dead load on all spans with full factored live
load on alternate spans." Sec 6.1.12.1 (a) permits taking the live load on the floor under
consideration only. In a 3D frame the floors interact through the columns, so how the floors
are loaded matters: the same bays loaded on every floor at once bend the columns in double
curvature and give LOWER span and support moments than the floor-only arrangement (a 3-bay,
5-storey frame, 6 m bays: span moment 4 % low, support moment 6 % low; see the tests). So, when
the grid has two or more floor levels:

- (b) alternate bays are loaded as a checkerboard over the floors (the given bays on the 1st,
  3rd ... floor, the other bays on the 2nd, 4th ...): the influence-line pattern for the span
  moments, which bounds the floor-only arrangement (the same frame: 90.75 against 87.58 kN m)
  at no extra cases (two per direction);
- (a) adjacent bays are loaded on each floor alone (``adjacent_floors="each"``, the default,
  BNBC's own assumption; one case per pair and floor) or on alternate floors
  (``"alternate"``, two cases per pair; the support moment then up to about 2 % below the
  floor-only one in the frame above, stated in the case label).

This is done by arrangement, not by a factor: BNBC's only factor rule, three-quarters of the
full factored live load on the panel and alternate panels (Sec 6.5.7.6.3, p. 960), and its
exemption when the live load does not exceed three-quarters of the dead load (Sec 6.5.7.6.2,
p. 959), belong to two-way slab systems analysed by the equivalent frame method (Sec 6.5.7); for
beams and one-way systems Sec 6.1.12.2 has no exemption. :func:`patterns_required` applies the
6.5.7.6.2 exemption to flat-slab floors only.

The arrangements follow the floor's column grid (:class:`Grid`): the lines are the column
centres (and wall ends the caller adds) clustered within 300 mm across; a bay is the space
between two neighbouring lines. In each plan direction with at least two bays:

- (b) alternate bays: the bays 1, 3, 5 ... loaded across the whole width, and the bays 2, 4 ...
  (maximum positive moments in the beams along that direction);
- (a) two adjacent bays, for each interior grid line with at least three bays in the direction
  (maximum negative moments at that line); with two bays the pair is the whole floor, which the
  full live case L already is.

A load point (a shell's centre, a slab panel's centroid, a line load's middle) is loaded by an
arrangement when the bay it lies in is; a point beyond the first or last line (a cantilever) is
loaded with the alternate arrangement that continues the alternation, and by no adjacent
arrangement. The full live load case L stays and is enveloped with the arrangements (BNBC
6.5.7.6.4 states the full-load floor for slabs; for frames it is arrangement (a) and (b)'s
limiting case).

:func:`saengine.fem.combinations.pattern_live_combinations` forms, from every gravity
combination with live load (no wind or earthquake: the clause is about dead with live load), one
combination per arrangement with the live case L replaced by the arrangement's case at the same
factor; :func:`saengine.fem.derive.derive_fem` adds the arrangement cases (``analysis.
patternLive``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from saengine.design.slab import LINE_TOLERANCE  # one grid line: within 300 mm across

CLAUSE_ADJACENT = "BNBC 2020 Part 6 Sec 6.1.12.2 (a)"
CLAUSE_ALTERNATE = "BNBC 2020 Part 6 Sec 6.1.12.2 (b)"


def grid_lines(values: Iterable[float], tolerance: float = LINE_TOLERANCE) -> tuple[float, ...]:
    """Sorted positions [mm] of the clusters of ``values`` (a value within ``tolerance`` of the
    previous one joins its cluster; a cluster sits at its mean)."""
    lines: list[list[float]] = []
    for value in sorted(float(v) for v in values):
        if lines and value - lines[-1][-1] <= tolerance:
            lines[-1].append(value)
        else:
            lines.append([value])
    return tuple(sum(group) / len(group) for group in lines)


@dataclass(frozen=True)
class Grid:
    """A floor grid in plan [mm]: the lines across X (``xs``, positions along X) and across Y,
    and the floor levels with live load (``levels``, elevations [mm], ascending; empty: one
    floor, or floors not distinguished)."""

    xs: tuple[float, ...]
    ys: tuple[float, ...]
    levels: tuple[float, ...] = ()

    @classmethod
    def of(
        cls,
        points: Iterable[Sequence[float]],
        tolerance: float = LINE_TOLERANCE,
        levels: Iterable[float] = (),
    ) -> Grid:
        """The grid of plan points (column centres, wall ends) [mm] and floor ``levels``."""
        found = [(float(p[0]), float(p[1])) for p in points]
        return cls(
            grid_lines((p[0] for p in found), tolerance),
            grid_lines((p[1] for p in found), tolerance),
            grid_lines(levels, tolerance),
        )

    def level(self, z: float | None) -> int:
        """The index of the floor level nearest elevation ``z`` [mm] (0 without levels)."""
        if len(self.levels) < 2:
            return 0
        if z is None:
            raise ValueError("the arrangement differs by floor: the load's elevation is needed")
        return min(range(len(self.levels)), key=lambda k: abs(self.levels[k] - float(z)))

    def lines(self, direction: str) -> tuple[float, ...]:
        return self.xs if direction == "X" else self.ys

    def bays(self, direction: str) -> int:
        return max(len(self.lines(direction)) - 1, 0)

    def bay(self, direction: str, value: float) -> int:
        """The bay [0, n) along ``direction`` a coordinate [mm] lies in: -1 before the first
        line, n after the last (a cantilever). A point on an interior line is in the bay after
        it, one on the last line in the last bay; a load that comes from a slab panel (a line
        load on a beam on a grid line) is placed by the panel's centroid, not by the line."""
        lines = self.lines(direction)
        n = len(lines) - 1
        if n < 1:
            return -1 if not lines or value < lines[0] else max(n, 0)
        if value < lines[0]:
            return -1
        if value > lines[-1]:
            return n
        for k in range(n):
            if value < lines[k + 1]:
                return k
        return n - 1


@dataclass(frozen=True)
class LivePattern:
    """One arrangement of the live load: its load case name, what it is, the clause, the plan
    direction its bays run along and the bays loaded (0-based; on the floors of even index for
    a ``checker`` arrangement, the other bays on the others), and the floors (indices into the
    grid's levels; None: all)."""

    name: str
    label: str
    clause: str
    direction: str
    bays: frozenset[int]
    alternate: bool
    floors: frozenset[int] | None = None
    checker: bool = False

    def loads(self, grid: Grid, x: float, y: float, z: float | None = None) -> bool:
        """Whether a load at plan point (x, y) and elevation ``z`` [mm] is in this arrangement
        (``z`` is needed when it differs by floor)."""
        level = grid.level(z) if (self.floors is not None or self.checker) else 0
        if self.floors is not None and level not in self.floors:
            return False
        bay = grid.bay(self.direction, x if self.direction == "X" else y)
        n = grid.bays(self.direction)
        if not self.alternate:
            return 0 <= bay < n and bay in self.bays
        # alternate bays (a cantilever continues the alternation: before bay 0 as bay -1,
        # after the last as n), swapped on every other floor for a checkerboard
        start = min(self.bays) % 2
        if self.checker and level % 2 == 1:
            start = 1 - start
        return (bay % 2) == start


def live_patterns(
    grid: Grid,
    adjacent: bool = True,
    alternate: bool = True,
    prefix: str = "LP",
    adjacent_floors: str = "each",
) -> list[LivePattern]:
    """The arrangements of BNBC 6.1.12.2 on ``grid`` (see the module notes), named
    ``LP1``, ``LP2`` ... in the order: X alternate (odd, even bays), X adjacent pairs (by floor),
    then the same along Y. With two or more levels the alternate arrangements are checkerboards
    over the floors and the adjacent ones are by floor: ``adjacent_floors`` "each" (each floor
    alone) or "alternate" (the floors of even index, then of odd index)."""
    if adjacent_floors not in ("each", "alternate"):
        raise ValueError(f"adjacent_floors is 'each' or 'alternate', not {adjacent_floors!r}")
    levels = grid.levels if len(grid.levels) >= 2 else ()
    found: list[LivePattern] = []

    def add(
        label: str,
        clause: str,
        direction: str,
        bays: frozenset[int],
        alternate: bool,
        floors: frozenset[int] | None = None,
        checker: bool = False,
    ) -> None:
        name = f"{prefix}{len(found) + 1}"
        found.append(LivePattern(name, label, clause, direction, bays, alternate, floors, checker))

    def floors_of(indices: Iterable[int]) -> str:
        return ", ".join(f"{levels[k] / 1e3:g} m" for k in indices)

    for direction in ("X", "Y"):
        n = grid.bays(direction)
        if alternate and n >= 2:
            for start in (0, 1):
                bays = frozenset(range(start, n, 2))
                listed = ", ".join(str(b + 1) for b in sorted(bays))
                label = f"Live load on alternate bays along {direction}: {listed}"
                if levels:
                    label += " (the other bays on every other floor: a checkerboard)"
                add(label, CLAUSE_ALTERNATE, direction, bays, True, checker=bool(levels))
        if adjacent and n >= 3:
            for k in range(n - 1):
                label = f"Live load on adjacent bays along {direction}: {k + 1} and {k + 2}"
                pair = frozenset({k, k + 1})
                if not levels:
                    add(label, CLAUSE_ADJACENT, direction, pair, False)
                elif adjacent_floors == "each":
                    for f in range(len(levels)):
                        add(
                            f"{label}, floor at {floors_of([f])} only",
                            CLAUSE_ADJACENT + " with 6.1.12.1 (a)",
                            direction,
                            pair,
                            False,
                            frozenset({f}),
                        )
                else:
                    for parity in (0, 1):
                        chosen = frozenset(range(parity, len(levels), 2))
                        add(
                            f"{label}, floors at {floors_of(sorted(chosen))} (alternate floors: "
                            "the support moment may be about 2 % below one floor alone)",
                            CLAUSE_ADJACENT,
                            direction,
                            pair,
                            False,
                            chosen,
                        )
    return found


def centroid(outline: Sequence[Sequence[float]]) -> tuple[float, float]:
    """The area centroid of a plan polygon [mm] (its vertices' mean when it has no area)."""
    points = [(float(p[0]), float(p[1])) for p in outline]
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area) < 1e-9:
        return (
            sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points),
        )
    return cx / (3 * area), cy / (3 * area)


def patterns_required(system: str, dead: float, live: float) -> tuple[bool, str]:
    """Whether a floor needs the arrangements: always for beams and one-way slabs (BNBC
    6.1.12.2 has no exemption); for a flat slab (two-way system by Sec 6.5.7) not when the
    unfactored live load is at most three-quarters of the unfactored dead load (Sec
    6.5.7.6.2). ``dead``, ``live``: service loads in one unit. Returns (needed, why)."""
    if system == "flat" and live <= 0.75 * dead:
        return False, (
            f"flat slab with live load {live:g} <= 0.75 x dead load {dead:g}: full live load on "
            "all panels (BNBC 2020 Part 6 Sec 6.5.7.6.2)"
        )
    if live <= 0:
        return False, "no live load"
    return True, "live load arrangement of BNBC 2020 Part 6 Sec 6.1.12.2"

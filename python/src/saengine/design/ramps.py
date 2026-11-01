"""Ramp checks: the gradient, length, width, landings and handrails of the architecture's ramps
against the active code pack's ``accessibility`` table.

A ramp of the architecture (:class:`saengine.library.architecture.Ramp`) is a straight flight
from its low end to its high end; its ``kind`` (walkway, accessible, exit, vehicle, parking)
chooses the pack's rules (:class:`saengine.codes.tables.RampRules`). A kind the pack has no rules
for is reported as not covered by the pack. Every limit and clause comes from the pack; the
checks here are generic:

- **gradient**: rise / plan run (measured along the centre line) against ``maxSlope``, or the
  row of ``byRise`` the rise falls in (its slope, and its greatest run); a vehicle ramp marked
  with ``transitions`` may reach the steeper ``transitions`` slope. A walking ramp no steeper
  than ``rampThreshold`` is a level walkway: no ramp rule applies to it.
- **flight**: the plan run at least ``flight.min``, the length along the slope at most
  ``flight.max`` between landings (a longer ramp is drawn as several with landings).
- **width**: at least ``width.min``, or ``width.byLanes`` for the ramp's lanes.
- **landings**: where another ramp on the story starts near this one's high end, the gap
  between them (centre line to centre line) is the landing, at least ``landing.min`` (and the
  ramp's width with ``atLeastWidth``).
- **handrails**: railings of the story along both long sides of the ramp, where ``handrails``
  applies.
- ``notes``: requirements the model cannot show (surface, markings, doors), listed with their
  clauses where they apply.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.library.architecture import Architecture, Ramp, ramp_length, ramp_polygon

#: How far outside a ramp's edge a railing of its story still counts as its handrail [mm]
#: (a modelling tolerance: a railing drawn on the edge, or on a low wall beside it).
HANDRAIL_REACH = 300.0
#: The share of the ramp's run a railing has to run along to count as a side's handrail.
HANDRAIL_SHARE = 0.5
#: A next ramp starting within this many landing lengths of a ramp's high end is the next
#: flight of the same ramp, the gap between them its landing.
LANDING_REACH = 2.0

TABLE = "accessibility"


def _one_in(gradient: float) -> str:
    return f"1 in {1 / gradient:.1f}" if gradient > 0 else "level"


def _steeper(gradient: float, one_in: float | None) -> bool:
    """Whether ``gradient`` is steeper than 1 in ``one_in`` (None: always)."""
    return one_in is None or gradient > 1.0 / one_in * (1 + 1e-9)


def _check(
    check: str, status: str, message: str, source: str | None, value: Any = None, limit: Any = None
) -> dict[str, Any]:
    row: dict[str, Any] = {"check": check, "status": status, "message": message}
    if value is not None:
        row["value"] = value
    if limit is not None:
        row["limit"] = limit
    row["source"] = source or ""
    return row


def _sides_with_railings(arch: Architecture, ramp: Ramp) -> set[str]:
    """The sides ("left", "right" looking up the ramp) with a railing of the ramp's story along
    at least :data:`HANDRAIL_SHARE` of its run."""
    from shapely.geometry import LineString

    run = math.dist(ramp.start, ramp.end)
    if run <= 0:
        return set()
    zone = ramp_polygon(ramp).buffer(HANDRAIL_REACH)
    dx, dy = (ramp.end[0] - ramp.start[0]) / run, (ramp.end[1] - ramp.start[1]) / run
    sides: set[str] = set()
    for railing in arch.railings:
        if railing.base != ramp.story or len(railing.path) < 2:
            continue
        inside = LineString(railing.path).intersection(zone)
        if inside.is_empty or inside.length < HANDRAIL_SHARE * run:
            continue
        # Along the ramp, the railing's part inside: which side of the centre line it is on.
        middle = inside.interpolate(0.5, normalized=True)
        cross = dx * (middle.y - ramp.start[1]) - dy * (middle.x - ramp.start[0])
        if abs(cross) > 1e-6:
            sides.add("left" if cross > 0 else "right")
    return sides


def _landings(arch: Architecture, ramp: Ramp, need: float) -> list[tuple[str, float]]:
    """(next ramp, landing length [mm]) of the ramps of the story starting within
    :data:`LANDING_REACH` × ``need`` of this ramp's high end."""
    reach = LANDING_REACH * need
    found = []
    for other in arch.ramps:
        if other.id == ramp.id or other.story != ramp.story:
            continue
        gap = math.dist(ramp.end, other.start)
        if gap <= reach:
            found.append((other.id, gap))
    return found


def check_ramp(arch: Architecture, ramp: Ramp) -> dict[str, Any]:
    """The checks of one ramp under the pack in force (see the module)."""
    pack = code_context.current()
    run = math.dist(ramp.start, ramp.end)
    gradient = ramp.rise / run if run else 0.0
    result: dict[str, Any] = {
        "id": ramp.id,
        "story": ramp.story,
        "kind": ramp.kind,
        "rise": ramp.rise,
        "run": run,
        "length": ramp_length(ramp),
        "width": ramp.width,
        "gradient": gradient,
        "slope": _one_in(gradient),
        "checks": [],
    }
    table = pack.table(TABLE) if pack.has(TABLE) else None
    rules = table.ramps.get(ramp.kind) if table is not None else None
    if rules is None:
        result.update(
            covered=False,
            ok=True,
            message=f"Ramp checks for this kind of ramp ({ramp.kind}) are not covered by the "
            f"code pack {pack.name}.",
        )
        return result
    result.update(covered=True, name=rules.name, source=rules.source or table.source)
    checks: list[dict[str, Any]] = result["checks"]

    if rules.walking and not _steeper(gradient, table.rampThreshold.oneIn):
        limit = f"1 in {table.rampThreshold.oneIn:g}"
        checks.append(
            _check(
                "threshold",
                "note",
                f"{_one_in(gradient)} is no steeper than {limit}: a level walkway, not a ramp; "
                "no ramp rule applies.",
                table.rampThreshold.source,
                result["slope"],
                limit,
            )
        )
        result["ok"] = True
        return result

    # Gradient (and, with byRise, the greatest run of the change of level).
    if rules.byRise:
        band = next(
            (b for b in rules.byRise if b.riseMax is None or ramp.rise <= b.riseMax + 1e-9),
            rules.byRise[-1],
        )
        limit = f"1 in {band.oneIn:g}"
        ok = not _steeper(gradient, band.oneIn)
        checks.append(
            _check(
                "gradient",
                "pass" if ok else "fail",
                f"{_one_in(gradient)} for a rise of {ramp.rise:.0f} mm "
                + ("is within " if ok else "is steeper than ")
                + limit
                + ".",
                band.source,
                result["slope"],
                limit,
            )
        )
        ok = run <= band.runMax + 1e-6
        checks.append(
            _check(
                "run",
                "pass" if ok else "fail",
                f"Run {run:.0f} mm "
                + ("within" if ok else "exceeds")
                + f" {band.runMax:.0f} mm for this change of level"
                + ("." if ok else ": split it into flights with level landings."),
                band.source,
                round(run),
                band.runMax,
            )
        )
    elif rules.maxSlope is not None:
        steepest, source = rules.maxSlope.oneIn, rules.maxSlope.source
        if ramp.transitions and rules.transitions is not None:
            steepest, source = rules.transitions.oneIn, rules.transitions.source
        limit = f"1 in {steepest:g}"
        ok = not _steeper(gradient, steepest)
        message = f"{_one_in(gradient)} ({gradient * 100:.1f} %) " + (
            "is within " if ok else "is steeper than "
        )
        message += f"{limit} ({100 / steepest:.1f} %)"
        if ramp.transitions and rules.transitions is not None:
            share = rules.transitions.transitionShare
            message += f", with transition slopes at {share:g} × the main slope at both ends"
        elif not ok and rules.transitions is not None:
            message += (
                f"; with transition slopes at both ends it may reach "
                f"1 in {rules.transitions.oneIn:g}"
            )
        checks.append(
            _check(
                "gradient", "pass" if ok else "fail", message + ".", source, result["slope"], limit
            )
        )

    # Flight length between landings.
    if rules.flight is not None:
        flight = rules.flight
        length = ramp_length(ramp)
        if run < flight.min - 1e-6:
            checks.append(
                _check(
                    "flight",
                    "fail",
                    f"Sloping part {run:.0f} mm is shorter than {flight.min:.0f} mm.",
                    flight.source,
                    round(run),
                    flight.min,
                )
            )
        elif flight.max is not None and length > flight.max + 1e-6:
            checks.append(
                _check(
                    "flight",
                    "fail",
                    f"Sloping part {length:.0f} mm is longer than {flight.max:.0f} mm between "
                    "landings: split it into flights with level landings.",
                    flight.source,
                    round(length),
                    flight.max,
                )
            )
        else:
            checks.append(
                _check(
                    "flight",
                    "pass",
                    f"Sloping part {length:.0f} mm between landings is within "
                    f"{flight.min:.0f}-{flight.max or math.inf:.0f} mm.",
                    flight.source,
                    round(length),
                    flight.max,
                )
            )

    # Width.
    if rules.width is not None:
        need = rules.width.byLanes.get(ramp.lanes, rules.width.min)
        if need is not None:
            ok = ramp.width >= need - 1e-6
            lanes = (
                f" ({ramp.lanes} lane{'s' if ramp.lanes > 1 else ''})"
                if rules.width.byLanes
                else ""
            )
            checks.append(
                _check(
                    "width",
                    "pass" if ok else "fail",
                    f"Width {ramp.width:.0f} mm "
                    + ("is at least " if ok else "is less than ")
                    + f"{need:.0f} mm{lanes}.",
                    rules.width.source,
                    ramp.width,
                    need,
                )
            )

    # Landings to the next flight.
    if rules.landing is not None:
        need = rules.landing.min
        if rules.landing.atLeastWidth:
            need = max(need, ramp.width)
        for other, gap in _landings(arch, ramp, need):
            ok = gap >= need - 1e-6
            checks.append(
                _check(
                    "landing",
                    "pass" if ok else "fail",
                    f"Landing to {other} {gap:.0f} mm "
                    + ("is at least " if ok else "is shorter than ")
                    + f"{need:.0f} mm.",
                    rules.landing.source,
                    round(gap),
                    need,
                )
            )

    # Handrails on both sides.
    if rules.handrails is not None and _steeper(gradient, rules.handrails.steeperThan):
        sides = _sides_with_railings(arch, ramp)
        ok = sides == {"left", "right"}
        missing = sorted({"left", "right"} - sides)
        checks.append(
            _check(
                "handrails",
                "pass" if ok else "fail",
                "Railings on both sides."
                if ok
                else "Guards and handrails are needed on both sides; no railing along the "
                + " and ".join(missing)
                + " side (looking up the ramp).",
                rules.handrails.source,
                len(sides),
                2,
            )
        )

    for note in rules.notes:
        if _steeper(gradient, note.steeperThan):
            checks.append(_check("note", "note", note.text, note.source))

    result["ok"] = not any(c["status"] == "fail" for c in checks)
    return result


@code_context.in_project_pack()
def check_ramps(arch: Architecture, settings: Any = None) -> dict[str, Any]:
    """The checks of every ramp of the architecture under the pack the settings choose:
    ``{"pack", "ramps": [check_ramp, ...], "failing"}``."""
    ramps = [check_ramp(arch, ramp) for ramp in arch.ramps]
    return {
        "pack": code_context.current().name,
        "ramps": ramps,
        "failing": [r["id"] for r in ramps if not r["ok"]],
    }

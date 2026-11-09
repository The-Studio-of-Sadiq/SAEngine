"""The construction programme of the building, linked to its elements: 4D scheduling (alpha 9 L11).

``10 BOQ/construction-schedule.json`` (:class:`ConstructionSchedule`) holds the activities of the
works, each with the building elements it builds. :func:`generate` makes them from the building
model (``06 BIM/bim.json``) and the bill of quantities (``10 BOQ/boq.json``):

- the substructure first (excavation, piles, foundations, backfill), then, level by level and per
  zone (the towers of the building model; one zone without towers), the vertical structure
  (columns and walls below the level), the floor structure at the level (beams, slabs, stairs),
  then brick work, finishes and the MEP first fix following the frame;
- an activity's duration is the sum over its bill items of ``quantity / (perDay x crews)`` in
  working days (the trades of an activity follow each other), rounded up to whole days, with the
  output rates of the office's productivity data (``10 BOQ/productivity.json``, which starts as
  the made-up sample ``boq/data/productivity-sample.json``: office data, not code values);
- the floor cycle is the one of the project settings' time-dependent analysis (alpha 9 P2:
  ``timeDependent.cycleDays``, and a level's own casting day ``castDays`` as the earliest day its
  floor is finished), so the programme and the column shortening analysis build the same way;
- brick work on a level starts once the floors ``masonryLagLevels`` above it are cast (the props
  are out), finishes and MEP follow the brick work.

The engineer edits the activities (name, duration, the earliest start, extra links): those edits
are kept when the schedule is generated again (:func:`generate` with ``previous``). The dates are
worked out by the critical path method on the working-day calendar (:func:`schedule`): early
dates, total float and the critical activities.

Exports: CSV (:func:`to_csv`) and Microsoft Project XML (MSPDI, :func:`to_mspdi`), and the
elements' dates for the 4D playback in the BIM viewer (:func:`element_dates`).
"""

from __future__ import annotations

import csv
import io
import itertools
import json
import math
from datetime import date, timedelta
from functools import cache
from importlib import resources
from typing import Any, Literal
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field

from saengine.boq.costing import Match, conversion

SCHEMA = "saengine.constructionSchedule/1"
PRODUCTIVITY_SCHEMA = "saengine.productivity/1"
SCHEDULE_FILE = "10 BOQ/construction-schedule.json"
PRODUCTIVITY_FILE = "10 BOQ/productivity.json"

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

#: The element kinds of the substructure (the bill's kinds; see saengine.boq.costing).
FOUNDATION_KINDS = {"footing", "pileCap", "raft", "tieBeam", "blinding"}
VERTICAL_KINDS = {"column", "wall", "brace"}

Category = Literal[
    "excavation", "piles", "foundations", "backfill", "vertical", "floor", "masonry", "finishes",
    "mep",
]  # fmt: skip

CATEGORY_NAMES: dict[str, str] = {
    "excavation": "Excavation",
    "piles": "Piling",
    "foundations": "Foundations",
    "backfill": "Backfill",
    "vertical": "Columns and walls",
    "floor": "Floor structure",
    "masonry": "Brick work",
    "finishes": "Finishes",
    "mep": "MEP first fix",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ─────────────────────────────────── office data ───────────────────────────────────


class ProductivityRate(_Model):
    id: str
    description: str = ""
    perDay: float = Field(gt=0, description="Output of one crew per working day, in `unit`.")
    unit: str = Field(description="Unit of the output (m3, m2, kg, nr, m, ...).")
    crews: float = Field(default=1, gt=0, description="Crews working at once.")
    match: Match = Field(default_factory=Match)


class Productivity(_Model):
    schema_: Literal["saengine.productivity/1"] = Field(default=PRODUCTIVITY_SCHEMA, alias="schema")
    name: str = ""
    notes: list[str] = Field(default_factory=list)
    workDays: list[str] = Field(default_factory=lambda: list(WEEKDAYS[:6]))
    holidays: list[date] = Field(default_factory=list)
    masonryLagLevels: int = Field(default=2, ge=0)
    finishesLagDays: float = Field(default=5, ge=0)
    mepLagDays: float = Field(default=0, ge=0)
    defaultDays: float = Field(
        default=3, gt=0, description="Duration of an activity with nothing measured [days]."
    )
    rates: list[ProductivityRate] = Field(default_factory=list)

    def rate_for(self, item: dict[str, Any]) -> ProductivityRate | None:
        return next((r for r in self.rates if r.match.holds(item)), None)


@cache
def sample_productivity_text() -> str:
    """The sample productivity rates (example values), as the project's file starts."""
    return (
        resources.files("saengine.boq")
        .joinpath("data", "productivity-sample.json")
        .read_text(encoding="utf-8")
    )


def parse_productivity(text: str | None) -> Productivity:
    return Productivity.model_validate_json(
        text if text and text.strip() else sample_productivity_text()
    )


# ─────────────────────────────────── the schedule ───────────────────────────────────


class Link(_Model):
    """The activity follows ``source``: finish-to-start (FS) or start-to-start (SS), with a lag
    in working days."""

    source: str = Field(alias="from")
    type: Literal["FS", "SS"] = "FS"
    lag: float = 0
    user: bool = Field(default=False, description="Added by the engineer (kept on regenerate).")


class Quantity(_Model):
    rate: str | None = Field(default=None, description="Productivity rate id; None: none matched.")
    description: str
    quantity: float
    unit: str
    days: float = Field(description="Crew-days / crews.")


class Activity(_Model):
    id: str
    name: str
    category: Category
    level: str | None = None
    zone: str | None = None
    elements: list[str] = Field(default_factory=list)
    quantities: list[Quantity] = Field(default_factory=list)
    days: float = Field(default=1, description="Duration from the quantities [working days].")
    duration: float | None = Field(
        default=None, ge=0, description="The engineer's duration [working days]: wins over days."
    )
    start: date | None = Field(default=None, description="Start no earlier than this date.")
    links: list[Link] = Field(default_factory=list)
    renamed: bool = Field(default=False, description="The name is the engineer's.")
    # computed by schedule():
    earlyStart: date | None = None
    earlyFinish: date | None = None
    totalFloat: float | None = None
    critical: bool = False

    @property
    def working_days(self) -> int:
        value = self.duration if self.duration is not None else self.days
        return max(math.ceil(value - 1e-9), 0)


class ConstructionSchedule(_Model):
    schema_: Literal["saengine.constructionSchedule/1"] = Field(default=SCHEMA, alias="schema")
    start: date = Field(description="Day the works start.")
    workDays: list[str] = Field(default_factory=lambda: list(WEEKDAYS[:6]))
    holidays: list[date] = Field(default_factory=list)
    cycleDays: float = Field(default=7, gt=0, description="Floor cycle [calendar days].")
    activities: list[Activity] = Field(default_factory=list)
    finish: date | None = None
    notes: list[str] = Field(default_factory=list)
    source: dict[str, str] = Field(default_factory=dict)


# ─────────────────────────────────── calendar ───────────────────────────────────


class Calendar:
    """Working days from a start date: index 0 is the first working day on or after it."""

    def __init__(self, start: date, work_days: list[str], holidays: list[date]) -> None:
        days = {d.lower()[:3] for d in work_days} & set(WEEKDAYS)
        self.work = {WEEKDAYS.index(d) for d in days} or set(range(7))
        self.holidays = set(holidays)
        self.start = start
        self._days: list[date] = []

    def working(self, day: date) -> bool:
        return day.weekday() in self.work and day not in self.holidays

    def date(self, index: int) -> date:
        """The working day of ``index`` (0: the first)."""
        index = max(index, 0)
        day = self._days[-1] + timedelta(days=1) if self._days else self.start
        while len(self._days) <= index:
            if self.working(day):
                self._days.append(day)
            day += timedelta(days=1)
            if (day - self.start).days > 365 * 60:  # a calendar with no working day
                raise ValueError("the calendar has no working days")
        return self._days[index]

    def index(self, day: date) -> int:
        """The index of the first working day on or after ``day``."""
        if day <= self.start:
            return 0
        i = 0
        while self.date(i) < day:
            i += 1
        return i

    def working_days_in(self, calendar_days: float) -> float:
        """About how many working days ``calendar_days`` hold."""
        return calendar_days * len(self.work) / 7.0


# ─────────────────────────────────── generating ───────────────────────────────────


def _plan_point(element: Any) -> tuple[float, float] | None:
    kind = getattr(element, "kind", None)
    if kind in ("column", "footing"):
        return float(element.position[0]), float(element.position[1])
    if kind in ("beam", "wall", "member"):
        a, b = element.start, element.end
        return (float(a[0]) + float(b[0])) / 2, (float(a[1]) + float(b[1])) / 2
    points = getattr(element, "boundary", None) or getattr(element, "outline", None)
    if points:
        return (
            sum(float(p[0]) for p in points) / len(points),
            sum(float(p[1]) for p in points) / len(points),
        )
    return None


def _element_level(element: Any, stories: list[Any]) -> str | None:
    """The level an element belongs to: a column or wall the level at its top, a beam or slab
    the level it is at (as the bill's stories); the nearest level at or below otherwise."""
    kind = getattr(element, "kind", None)
    if kind in ("column", "wall"):
        z = float(element.top)
    elif kind in ("beam", "slab", "footing"):
        z = float(element.elevation)
    elif kind == "member":
        z = max(float(element.start[2]), float(element.end[2]))
    elif kind in ("area", "block"):
        z = max(float(p[2]) for p in element.outline)
    else:
        return None
    best = None
    for story in stories:
        if float(story.elevation) <= z + 1.0:
            best = story.id
    return best or (stories[0].id if stories else None)


def element_zones(building: Any) -> dict[str, str]:
    """The tower each element stands in (by its plan point), for the zones of the programme."""
    towers = list(getattr(building, "towers", None) or [])
    if not towers:
        return {}
    from shapely.geometry import Point, Polygon

    shapes = [(t.id, Polygon([(float(p[0]), float(p[1])) for p in t.boundary])) for t in towers]
    zones: dict[str, str] = {}
    for element in building.elements:
        point = _plan_point(element)
        if point is None:
            continue
        p = Point(point)
        for tower_id, shape in shapes:
            if shape.covers(p):
                zones[element.id] = tower_id
                break
    return zones


def _category(group: str, kind: str | None) -> Category | None:
    if group == "materials":
        return None  # the materials take-off restates the concrete and the mortar
    if group == "earthwork":
        return "excavation" if kind in ("excavation", "siteCut") else "backfill"
    if kind == "pile":
        return "piles"
    if kind in FOUNDATION_KINDS:
        return "foundations"
    if group == "masonry":
        return "masonry"
    if group == "finishes" or kind in ("door", "window", "plaster", "filling"):
        return "finishes"
    if group == "mep":
        return "mep"
    if kind in VERTICAL_KINDS:
        return "vertical"
    return "floor"


def _activity_id(category: str, level: str | None, zone: str | None) -> str:
    return ":".join(p for p in (category, level, zone) if p)


def _name(category: str, level_name: str | None, zone: str | None) -> str:
    name = CATEGORY_NAMES[category]
    if level_name:
        name += f", {level_name}"
    if zone:
        name += f" ({zone})"
    return name


def generate(
    building: Any,
    bill: dict[str, Any] | None,
    productivity: Productivity,
    start: date,
    cycle_days: float = 7.0,
    cast_days: dict[str, float] | None = None,
    previous: ConstructionSchedule | None = None,
) -> ConstructionSchedule:
    """The programme of ``building`` (a :class:`saengine.library.bim.BuildingModel`) with the
    quantities of ``bill`` (the ``boq.json`` document as a dict; None: no quantities, every
    activity takes ``defaultDays``), scheduled from ``start``. ``cast_days``: the day (calendar
    days after the frame starts) a level's floor is cast, by level id or name (alpha 9 P2).
    ``previous``: the engineer's edits (names, durations, start dates, own links) are kept."""
    stories = sorted(building.stories, key=lambda s: float(s.elevation))
    level_names = {s.id: s.name for s in stories}
    order = [s.id for s in stories]
    zones = element_zones(building)
    levels = {e.id: _element_level(e, stories) for e in building.elements}
    notes: list[str] = []
    acts: dict[str, Activity] = {}
    #: activity -> rate id -> [quantity, crew-days / crews, a bill item, the rate]
    crew_days: dict[str, dict[str | None, list[Any]]] = {}

    def activity(category: Category, level: str | None, zone: str | None) -> Activity:
        key = _activity_id(category, level, zone)
        if key not in acts:
            acts[key] = Activity(
                id=key,
                name=_name(category, level_names.get(level or "", level), zone),
                category=category,
                level=level,
                zone=zone,
            )
            crew_days[key] = {}
        return acts[key]

    substructure = ("excavation", "piles", "foundations", "backfill")
    unmatched: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for item in (bill or {}).get("items", []):
        group, kind = str(item.get("group")), item.get("kind")
        category = _category(group, kind)
        if category is None:
            continue
        rate = productivity.rate_for(item)
        factor = conversion(rate.unit, str(item.get("unit"))) if rate is not None else None
        if rate is None or factor is None:
            unmatched.add(str(item.get("description")))
        entries = item.get("breakdown") or [
            {"element": None, "story": None, "quantity": item.get("quantity", 0.0)}
        ]
        for entry in entries:
            element = entry.get("element")
            if category in substructure:
                level, zone = None, None
            else:
                level = (
                    entry.get("story") or levels.get(str(element)) or (order[0] if order else None)
                )
                zone = zones.get(str(element)) if element is not None else None
            act = activity(category, level, zone)
            if element is not None and (act.id, str(element)) not in seen:
                seen.add((act.id, str(element)))
                act.elements.append(str(element))
            q = float(entry.get("quantity") or 0.0)
            bucket = crew_days[act.id].setdefault(rate.id if rate else None, [0.0, 0.0, item, rate])
            bucket[0] += q
            if rate is not None and factor is not None:
                bucket[1] += q * factor / (rate.perDay * rate.crews)

    # Elements the bill does not measure still get built: the frame from the model.
    placed = {e for a in acts.values() for e in a.elements}
    for element in building.elements:
        if element.id in placed:
            continue
        kind = getattr(element, "kind", None)
        level, zone = levels.get(element.id), zones.get(element.id)
        if kind == "footing":
            act = activity("foundations", None, None)
        elif kind in ("column", "wall"):
            act = activity("vertical", level, zone)
        else:
            act = activity("floor", level, zone)
        act.elements.append(element.id)

    for key, act in acts.items():
        quantities = []
        total = 0.0
        for rate_id, (q, days, item, rate) in crew_days[key].items():
            quantities.append(
                Quantity(
                    rate=rate_id,
                    description=str(rate.description if rate else item.get("description")),
                    quantity=round(q, 3),
                    unit=str(item.get("unit")),
                    days=round(days, 3),
                )
            )
            total += days
        act.quantities = quantities
        act.days = float(math.ceil(total - 1e-9)) if total > 0 else productivity.defaultDays
        act.days = max(act.days, 1.0)

    # Links.
    calendar = Calendar(start, productivity.workDays, productivity.holidays)
    cycle = max(round(calendar.working_days_in(cycle_days)), 1)

    def link(target: str, source: str | None, kind: str = "FS", lag: float = 0) -> None:
        if source is None or target not in acts or source not in acts or source == target:
            return
        acts[target].links.append(Link(source=source, type=kind, lag=lag))  # type: ignore[arg-type]

    sub_chain = [k for k in ("excavation", "piles", "foundations", "backfill") if k in acts]
    for a, b in itertools.pairwise(sub_chain):
        link(b, a)
    last_sub = next((k for k in ("foundations", "piles", "excavation") if k in acts), None)
    zone_ids: list[str | None] = sorted(
        {a.zone for a in acts.values() if a.level is not None}, key=lambda z: z or ""
    ) or [None]
    for zone in zone_ids:
        previous_floor: str | None = None
        floors: list[str] = []
        for level in order:
            vertical = _activity_id("vertical", level, zone)
            floor = _activity_id("floor", level, zone)
            if vertical not in acts and floor not in acts:
                continue
            first = vertical if vertical in acts else floor
            link(first, previous_floor or last_sub)
            if vertical in acts and floor in acts:
                link(floor, vertical)
            if previous_floor is not None and floor in acts:
                link(floor, previous_floor, "SS", cycle)
            if floor in acts:
                previous_floor = floor
            floors.append(floor if floor in acts else vertical)
        # Brick work after the floors above are cast (props out), then finishes and MEP.
        built = [
            lv
            for lv in order
            if _activity_id("floor", lv, zone) in acts or _activity_id("vertical", lv, zone) in acts
        ]
        for level in order:
            masonry = _activity_id("masonry", level, zone)
            finishes = _activity_id("finishes", level, zone)
            mep = _activity_id("mep", level, zone)
            support: str | None
            if level in built:
                j = min(built.index(level) + productivity.masonryLagLevels, len(built) - 1)
                support = _activity_id("floor", built[j], zone)
                if support not in acts:
                    support = _activity_id("vertical", built[j], zone)
            else:
                support = floors[-1] if floors else last_sub
            link(masonry, support)
            after = masonry if masonry in acts else support
            link(finishes, after, "FS", productivity.finishesLagDays)
            link(mep, after, "FS", productivity.mepLagDays)
    # Anything else with no link (a zone with finishes only, ...) follows the substructure.
    first_sub = sub_chain[0] if sub_chain else None
    for act in acts.values():
        if not act.links and act.id != first_sub:
            link(act.id, last_sub)

    # Casting days (alpha 9 P2): a level's floor is cast (finished) no earlier than its day,
    # counted in calendar days from the start of the works.
    if cast_days:
        by_name = {s.name: s.id for s in stories}
        for level, day in cast_days.items():
            level_id = level if level in level_names else by_name.get(level)
            if level_id is None:
                notes.append(f"casting day of '{level}': no such level")
                continue
            for act in acts.values():
                if act.category == "floor" and act.level == level_id:
                    cast = calendar.date(calendar.index(start + timedelta(days=float(day))))
                    earliest = calendar.date(max(calendar.index(cast) - act.working_days + 1, 0))
                    act.start = max(act.start, earliest) if act.start else earliest

    activities = list(acts.values())
    if previous is not None:
        _keep_edits(activities, previous)
    if unmatched:
        some = ", ".join(sorted(unmatched)[:3])
        notes.append(
            f"{len(unmatched)} bill item(s) have no productivity rate (e.g. {some}): they add no "
            "time; add rates for them to productivity.json"
        )
    if bill is None:
        notes.append(
            f"no bill of quantities: every activity takes {productivity.defaultDays:g} days; "
            "compute 10 BOQ for durations from the quantities"
        )
    result = ConstructionSchedule(
        start=start,
        workDays=productivity.workDays,
        holidays=productivity.holidays,
        cycleDays=cycle_days,
        activities=_ordered(activities, order),
        notes=notes,
    )
    return schedule(result)


def _ordered(activities: list[Activity], levels: list[str]) -> list[Activity]:
    rank = {k: i for i, k in enumerate(CATEGORY_NAMES)}
    level_rank = {lv: i for i, lv in enumerate(levels)}

    def key(a: Activity) -> tuple[Any, ...]:
        sub = a.level is None
        return (
            0 if sub else 1,
            level_rank.get(a.level or "", -1),
            a.zone or "",
            rank[a.category],
        )

    return sorted(activities, key=key)


def _keep_edits(activities: list[Activity], previous: ConstructionSchedule) -> None:
    before = {a.id: a for a in previous.activities}
    ids = {a.id for a in activities}
    for act in activities:
        old = before.get(act.id)
        if old is None:
            continue
        if old.renamed:
            act.name, act.renamed = old.name, True
        act.duration = old.duration
        if old.start is not None:
            act.start = max(old.start, act.start) if act.start else old.start
        act.links += [lk for lk in old.links if lk.user and lk.source in ids]


# ─────────────────────────────────── CPM ───────────────────────────────────


def schedule(document: ConstructionSchedule) -> ConstructionSchedule:
    """The early dates, total float and critical activities by the critical path method on the
    working-day calendar (FS and SS links with lags in working days). Raises ``ValueError`` on
    a loop of links."""
    calendar = Calendar(document.start, document.workDays, document.holidays)
    acts = {a.id: a for a in document.activities}
    order = _topological(acts)
    es: dict[str, int] = {}
    ef: dict[str, int] = {}
    for key in order:
        act = acts[key]
        d = act.working_days
        s = calendar.index(act.start) if act.start else 0
        for lk in act.links:
            if lk.source not in acts:
                continue
            lag = math.ceil(lk.lag - 1e-9)
            if lk.type == "FS":
                s = max(s, ef[lk.source] + lag)
            else:
                s = max(s, es[lk.source] + lag)
        es[key], ef[key] = s, s + d
    finish = max(ef.values(), default=0)
    # backward pass
    successors: dict[str, list[tuple[str, Link]]] = {k: [] for k in acts}
    for key, act in acts.items():
        for lk in act.links:
            if lk.source in acts:
                successors[lk.source].append((key, lk))
    lf: dict[str, int] = {}
    ls: dict[str, int] = {}
    for key in reversed(order):
        d = acts[key].working_days
        f = finish
        for succ, lk in successors[key]:
            lag = math.ceil(lk.lag - 1e-9)
            if lk.type == "FS":
                f = min(f, ls[succ] - lag)
            else:
                f = min(f, ls[succ] - lag + d)
        lf[key], ls[key] = f, f - d
    for key, act in acts.items():
        act.earlyStart = calendar.date(es[key])
        act.earlyFinish = calendar.date(max(ef[key] - 1, es[key]))
        act.totalFloat = float(ls[key] - es[key])
        act.critical = ls[key] - es[key] <= 0
    document.finish = calendar.date(max(finish - 1, 0)) if acts else document.start
    return document


def _topological(acts: dict[str, Activity]) -> list[str]:
    state: dict[str, int] = {}
    out: list[str] = []

    def visit(key: str, path: tuple[str, ...]) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            raise ValueError(f"the links make a loop: {' -> '.join((*path, key))}")
        state[key] = 1
        for lk in acts[key].links:
            if lk.source in acts:
                visit(lk.source, (*path, key))
        state[key] = 2
        out.append(key)

    for key in acts:
        visit(key, ())
    return out


# ─────────────────────────────────── outputs ───────────────────────────────────


def element_dates(document: ConstructionSchedule) -> dict[str, dict[str, str]]:
    """``{element: {"start", "finish", "activity"}}`` (ISO dates) for the 4D playback: an element
    is under construction from its activity's start and built from its finish."""
    out: dict[str, dict[str, str]] = {}
    for act in document.activities:
        if act.earlyStart is None or act.earlyFinish is None:
            continue
        for element in act.elements:
            known = out.get(element)
            # An element in several activities (its frame, then its finishes) is built by the first.
            if known is None or known["start"] > act.earlyStart.isoformat():
                out[element] = {
                    "start": act.earlyStart.isoformat(),
                    "finish": act.earlyFinish.isoformat(),
                    "activity": act.id,
                }
    return out


def to_csv(document: ConstructionSchedule) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "ID",
            "Name",
            "Level",
            "Zone",
            "Duration (days)",
            "Start",
            "Finish",
            "Predecessors",
            "Total float (days)",
            "Critical",
            "Elements",
        ]
    )
    for act in document.activities:
        writer.writerow(
            [
                act.id,
                act.name,
                act.level or "",
                act.zone or "",
                act.working_days,
                act.earlyStart.isoformat() if act.earlyStart else "",
                act.earlyFinish.isoformat() if act.earlyFinish else "",
                "; ".join(
                    f"{lk.source} {lk.type}{f' +{lk.lag:g}d' if lk.lag else ''}" for lk in act.links
                ),
                "" if act.totalFloat is None else f"{act.totalFloat:g}",
                "yes" if act.critical else "",
                len(act.elements),
            ]
        )
    return buffer.getvalue()


#: MSPDI day numbers: 1 Sunday ... 7 Saturday.
_MSP_DAY = {"sun": 1, "mon": 2, "tue": 3, "wed": 4, "thu": 5, "fri": 6, "sat": 7}
HOURS_PER_DAY = 8


def to_mspdi(document: ConstructionSchedule, title: str = "SAEngine programme") -> str:
    """The programme as Microsoft Project XML (MSPDI): a calendar with the working days and
    holidays, one task per activity with its duration, early dates and predecessor links
    (FS type 1, SS type 3; lags in tenths of minutes of 8-hour days)."""
    ns = "http://schemas.microsoft.com/project"
    ET.register_namespace("", ns)

    def sub(parent: ET.Element, tag: str, text: Any = None) -> ET.Element:
        el = ET.SubElement(parent, f"{{{ns}}}{tag}")
        if text is not None:
            el.text = str(text)
        return el

    project = ET.Element(f"{{{ns}}}Project")
    sub(project, "SaveVersion", 14)
    sub(project, "Title", title)
    sub(project, "ScheduleFromStart", 1)
    sub(project, "StartDate", f"{document.start.isoformat()}T08:00:00")
    if document.finish:
        sub(project, "FinishDate", f"{document.finish.isoformat()}T17:00:00")
    sub(project, "CalendarUID", 1)
    sub(project, "MinutesPerDay", HOURS_PER_DAY * 60)
    sub(project, "MinutesPerWeek", HOURS_PER_DAY * 60 * len(document.workDays))
    sub(project, "DaysPerMonth", 20)
    calendars = sub(project, "Calendars")
    cal = sub(calendars, "Calendar")
    sub(cal, "UID", 1)
    sub(cal, "Name", "SAEngine working days")
    sub(cal, "IsBaseCalendar", 1)
    week = sub(cal, "WeekDays")
    working = {d.lower()[:3] for d in document.workDays}
    for name, number in _MSP_DAY.items():
        day = sub(week, "WeekDay")
        sub(day, "DayType", number)
        sub(day, "DayWorking", 1 if name in working else 0)
        if name in working:
            times = sub(day, "WorkingTimes")
            for a, b in (("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")):
                t = sub(times, "WorkingTime")
                sub(t, "FromTime", a)
                sub(t, "ToTime", b)
    if document.holidays:
        exceptions = sub(cal, "Exceptions")
        for holiday in document.holidays:
            ex = sub(exceptions, "Exception")
            period = sub(ex, "TimePeriod")
            sub(period, "FromDate", f"{holiday.isoformat()}T00:00:00")
            sub(period, "ToDate", f"{holiday.isoformat()}T23:59:00")
            sub(ex, "DayWorking", 0)
    tasks = sub(project, "Tasks")
    uids = {a.id: i + 1 for i, a in enumerate(document.activities)}
    for act in document.activities:
        task = sub(tasks, "Task")
        sub(task, "UID", uids[act.id])
        sub(task, "ID", uids[act.id])
        sub(task, "Name", act.name)
        sub(task, "OutlineLevel", 1)
        sub(task, "Duration", f"PT{act.working_days * HOURS_PER_DAY}H0M0S")
        sub(task, "DurationFormat", 7)
        if act.earlyStart:
            sub(task, "Start", f"{act.earlyStart.isoformat()}T08:00:00")
        if act.earlyFinish:
            sub(task, "Finish", f"{act.earlyFinish.isoformat()}T17:00:00")
        if act.start:
            sub(task, "ConstraintType", 4)  # start no earlier than
            sub(task, "ConstraintDate", f"{act.start.isoformat()}T08:00:00")
        sub(task, "Critical", 1 if act.critical else 0)
        sub(task, "Notes", f"SAEngine activity {act.id}; {len(act.elements)} element(s)")
        for lk in act.links:
            if lk.source not in uids:
                continue
            p = sub(task, "PredecessorLink")
            sub(p, "PredecessorUID", uids[lk.source])
            sub(p, "Type", 1 if lk.type == "FS" else 3)
            sub(p, "LinkLag", round(lk.lag * HOURS_PER_DAY * 60 * 10))
            sub(p, "LagFormat", 7)
    ET.indent(project)
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(
        project, encoding="unicode"
    )


# ─────────────────────────────────── project files ───────────────────────────────────


def _read(root: Any, rel: str) -> str | None:
    from pathlib import Path

    try:
        return (Path(root) / rel).read_text(encoding="utf-8")
    except OSError:
        return None


def generate_for_project(project_root: str, start: str | None = None) -> dict[str, Any]:
    """Generates the project's programme from its files (keeping the engineer's edits of the
    saved one) and writes ``10 BOQ/construction-schedule.json``; returns ``{"schedule",
    "elementDates", "path"}`` or ``{"problems"}``."""
    from pathlib import Path

    from saengine.library.bim import BuildingModel, source_stamp

    bim_text = _read(project_root, "06 BIM/bim.json")
    if not bim_text:
        return {"problems": ["06 BIM has no building model: generate it first"]}
    building = BuildingModel.model_validate_json(bim_text)
    boq_text = _read(project_root, "10 BOQ/boq.json")
    bill = json.loads(boq_text) if boq_text else None
    productivity = parse_productivity(_read(project_root, PRODUCTIVITY_FILE))
    previous = None
    saved = _read(project_root, SCHEDULE_FILE)
    if saved:
        try:
            previous = ConstructionSchedule.model_validate_json(saved)
        except ValueError:
            previous = None
    cycle, casts = 7.0, {}
    settings_text = _read(project_root, "02 Project Settings/project-settings.json")
    if settings_text:
        try:
            settings = json.loads(settings_text)
            td = (settings.get("analysis") or {}).get("timeDependent") or settings.get(
                "timeDependent"
            )
            if isinstance(td, dict):
                cycle = float(td.get("cycleDays") or cycle)
                casts = {str(r["level"]): float(r["day"]) for r in td.get("castDays") or []}
        except (ValueError, KeyError, TypeError):
            pass
    when = (
        date.fromisoformat(start)
        if start
        else (previous.start if previous is not None else date.today())
    )
    document = generate(building, bill, productivity, when, cycle, casts, previous)
    document.source = {
        "bim": source_stamp(bim_text),
        **({"boq": source_stamp(boq_text)} if boq_text else {}),
    }
    path = Path(project_root) / SCHEDULE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    text = document.model_dump_json(by_alias=True, indent=2, exclude_none=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return {
        "schedule": json.loads(text),
        "elementDates": element_dates(document),
        "path": str(path),
    }


def reschedule_text(text: str) -> dict[str, Any]:
    """The dates of an edited schedule (the Gantt editor's unsaved text): ``{"schedule",
    "elementDates"}`` or ``{"problems"}``."""
    try:
        document = schedule(ConstructionSchedule.model_validate_json(text))
    except ValueError as error:
        return {"problems": [str(error).strip().splitlines()[0]]}
    return {
        "schedule": json.loads(document.model_dump_json(by_alias=True, exclude_none=True)),
        "elementDates": element_dates(document),
    }


def export(text: str, path: str, format: str) -> dict[str, Any]:
    """Writes the schedule ``text`` as ``csv`` or ``mspdi`` (MS Project XML) to ``path``."""
    from pathlib import Path

    document = schedule(ConstructionSchedule.model_validate_json(text))
    out = to_csv(document) if format == "csv" else to_mspdi(document)
    Path(path).write_text(out, encoding="utf-8")
    return {"path": path, "activities": len(document.activities)}

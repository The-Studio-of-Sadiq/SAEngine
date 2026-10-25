"""Which fire protection a building needs: BNBC 2020 Part 4 Chapter 5 (p346-p355).

Chapter 5 gives, for each occupancy, the active fire protection of a building of Type I-A
construction with Class-I finishes (Sec 5.2): portable extinguishers, a manual or an automatic
fire alarm (with detection), a hydrant (standpipe) system, sprinklers, or a fixed foam, gaseous or
dry chemical system; "performance based" where the code leaves the design to the engineer. Some
rows allow "portable fire extinguishers or hydrants": the hydrant choice (``fire.hydrant``)
decides which.

:func:`requirements` returns the rules that apply, each with its clause, and what that makes of
each system: ``required``, ``performance`` (performance based), ``recommended`` or
``notRequired``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from saengine.fire import tables as T
from saengine.plumbing.tables import OCCUPANCIES

SYSTEMS = {
    "extinguishers": "Portable fire extinguishers",
    "manualAlarm": "Manual fire alarm",
    "automaticAlarm": "Automatic fire alarm and detection",
    "hydrant": "Hydrant (standpipe) system",
    "sprinklers": "Automatic sprinklers",
    "special": "Fixed foam, gaseous or dry chemical system",
}
#: Precedence of the outcomes when several rules speak of one system.
LEVELS = ["notRequired", "recommended", "performance", "required"]


@dataclass
class Rule:
    """One clause applied to one occupancy: what it requires and why."""

    group: str
    clause: str
    text: str
    required: list[str] = field(default_factory=list)
    any_of: list[str] = field(default_factory=list)  # one of these (extinguishers or hydrants)
    performance: list[str] = field(default_factory=list)
    recommended: list[str] = field(default_factory=list)
    stories: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group, "clause": self.clause, "text": self.text,
            "required": self.required, "anyOf": self.any_of, "performance": self.performance,
            "recommended": self.recommended, "stories": self.stories,
        }  # fmt: skip


@dataclass
class Context:
    """What the rules read of the building (areas m², heights m)."""

    high_rise: bool
    storeys: int
    height: float
    max_floor: float
    total: float
    undivided: float
    corridor: str = "central"
    occupant_load: float | None = None
    false_ceiling: float | None = None
    dwelling_units: int | None = None


def _group(rules: list[Rule], ctx: Context, key: str, stories: list[str], underground: bool):
    """The rules of one occupancy (a 07 MEP story occupancy key) for ``stories``."""
    group = OCCUPANCIES[key].group
    letter = group[:1]

    def rule(clause: str, text: str, **kw: Any) -> None:
        rules.append(Rule(group, clause, text, stories=list(stories), **kw))

    if group in ("A1", "A2"):
        if ctx.total > 500:
            rule(T.cite("5.3.1", "(b)"), "dwelling over 500 m² in all: manual alarm and portable "
                 "extinguishers", required=["manualAlarm", "extinguishers"])  # fmt: skip
        else:
            rule(T.cite("5.3.1", "(a)"), "dwelling under 500 m² in all: no detection or fixed "
                 "fire fighting")  # fmt: skip
    elif group == "A3":
        if ctx.high_rise:
            rule(T.cite("5.3.2", "(b)"), "high-rise flats: manual alarm and hydrants at the fire "
                 "stair landings or lift lobby (none inside the flats)",
                 required=["manualAlarm", "hydrant"])  # fmt: skip
        else:
            rule(T.cite("5.3.2", "(a)"), "flats up to 33 m: no detection or fixed fire fighting")
    elif group in ("A4", "A5"):
        key5 = "5.3.3" if group == "A4" else "5.3.4"
        if ctx.high_rise:
            rule(T.cite(key5, "(d)"), "high-rise: manually operated electric fire alarm and "
                 "hydrants", required=["manualAlarm", "hydrant"])  # fmt: skip
        elif ctx.storeys <= 2:
            rule(T.cite(key5, "(a)"), "up to 2 storeys: no detection, alarm or fixed fire "
                 "fighting")  # fmt: skip
        elif ctx.max_floor < 300:
            rule(T.cite(key5, "(b)"), "3 storeys or more, floors under 300 m²: no detection or "
                 "fixed fire fighting")  # fmt: skip
        elif ctx.corridor == "central":
            rule(T.cite(key5, "(c)"), "floors over 300 m² with a central corridor: manual alarm "
                 "and portable extinguishers", required=["manualAlarm", "extinguishers"])  # fmt: skip
        elif group == "A4":
            rule(T.cite(key5, "(c)"), "single loaded corridor 3 m wide: no detection or fixed "
                 "fire fighting")  # fmt: skip
        else:
            rule(T.cite(key5, "(c)"), "low-rise hotel without a central corridor: performance "
                 "based fire fighting", performance=["extinguishers"])  # fmt: skip
    elif letter == "B":
        if ctx.high_rise or ctx.corridor == "central":
            rule(T.cite("5.4", " 5.4.2"), "high-rise, or classrooms both sides of a central "
                 "corridor: manual alarm and hydrants", required=["manualAlarm", "hydrant"])  # fmt: skip
        else:
            rule(T.cite("5.4", " 5.4.1-5.4.2"), "low-rise with a single loaded open corridor of "
                 "3 m or more: no fixed fire fighting; detection and manual alarm",
                 required=["automaticAlarm", "manualAlarm"])  # fmt: skip
        rule(T.cite("5.4", " 5.4.3"), "portable appliances where hydrants cannot be used",
             recommended=["extinguishers"])  # fmt: skip
    elif group in ("C1", "C2"):
        rule(T.cite("5.5", " 5.5.1-5.5.2"), "no detection or fixed fire fighting; portable "
             "appliances", required=["extinguishers"])  # fmt: skip
    elif letter == "C":
        rule(T.cite("5.5", " 5.5.3"), "manually operated electric fire alarm and portable "
             "appliances", required=["manualAlarm", "extinguishers"])  # fmt: skip
    elif letter == "D":
        text = "" if group == "D1" else " (Sec 5.6 lists D1 only: D2 taken as D1, SAEngine)"
        rule(T.cite("5.6", "(a)"), "manual or automatic alarm in the duty room, portable "
             "appliances" + text, required=["manualAlarm", "extinguishers"])  # fmt: skip
        if ctx.high_rise:
            rule(T.cite("5.6", "(c)"), "high-rise health care: manual alarm and hydrants",
                 required=["manualAlarm", "hydrant"])  # fmt: skip
        elif ctx.max_floor > 300:
            rule(T.cite("5.6", "(b)"), "low-rise over 300 m² a floor: performance based fire "
                 "fighting", performance=["hydrant"])  # fmt: skip
    elif letter == "E":
        if ctx.high_rise:
            rule(T.cite("5.7", "(xi)"), "high-rise office: manual alarm and hydrants",
                 required=["manualAlarm", "hydrant"])  # fmt: skip
        elif ctx.storeys <= 2 and ctx.undivided <= 500:
            rule(T.cite("5.7", "(i)"), "up to 2 storeys and 500 m² undivided: portable "
                 "extinguishers or hydrants", any_of=["extinguishers", "hydrant"])  # fmt: skip
        else:
            rule(T.cite("5.7", "(ii)"), "over 2 storeys or over 500 m² undivided: manual alarm "
                 "with portable extinguishers or hydrants", required=["manualAlarm"],
                 any_of=["extinguishers", "hydrant"])  # fmt: skip
        if group == "E2":
            rule(T.cite("5.7", "(iii)"), "laboratory: automatic alarm, performance based "
                 "extinguishing", required=["automaticAlarm"], performance=["special"])  # fmt: skip
        if group == "E3":
            rule(T.cite("5.7", "(x)"), "essential services: performance based (Sec 5.1.1)",
                 performance=["hydrant", "sprinklers"])  # fmt: skip
        if (ctx.false_ceiling or 0) > 500:
            rule(T.cite("5.7", "(ix)"), "over 500 m² under one false ceiling: automatic alarm "
                 "above and below it", required=["automaticAlarm"])  # fmt: skip
    elif group == "F1":
        rule(T.cite("5.8.1"), "manual alarm with portable extinguishers or hydrant",
             required=["manualAlarm"], any_of=["extinguishers", "hydrant"])  # fmt: skip
    elif group == "F2":
        if underground:
            rule(T.cite("5.8.2", "(iii)"), "underground mercantile: automatic alarm, sprinklers "
                 "and standpipe with performance based portable extinguishers",
                 required=["automaticAlarm", "sprinklers", "hydrant"],
                 performance=["extinguishers"])  # fmt: skip
            return
        if ctx.undivided > 500:
            rule(T.cite("5.8.2", "(ii)"), "over 500 m² undivided on a floor: manual alarm and "
                 "hydrants with performance based portable extinguishers",
                 required=["manualAlarm", "hydrant"], performance=["extinguishers"])  # fmt: skip
        else:
            rule(T.cite("5.8.2", "(i)"), "manual alarm with portable extinguishers or hydrant",
                 required=["manualAlarm"], any_of=["extinguishers", "hydrant"])  # fmt: skip
    elif group == "F3":
        rule(T.cite("5.8.3"), "fixed automatic foam, gaseous or dry chemical system with "
             "portable extinguishers", required=["special", "extinguishers"])  # fmt: skip
    elif group == "G1" or group == "K3":
        prefix = "repair garage, as G1 (Sec 5.13(a)): " if group == "K3" else ""
        if (ctx.occupant_load or 0) > 150:
            rule(T.cite("5.9.1"), prefix + "over 150 occupants: performance based",
                 required=["manualAlarm"], performance=["hydrant"])  # fmt: skip
        else:
            rule(T.cite("5.9.1"), prefix + "up to 150 occupants: manual alarm with portable "
                 "extinguishers or hydrants", required=["manualAlarm"],
                 any_of=["extinguishers", "hydrant"])  # fmt: skip
    elif group == "G2":
        if ctx.undivided > 750:
            rule(T.cite("5.9.2", ""), "over 750 m² undivided: manual alarm with hydrants "
                 "(5.9.2(p))", required=["manualAlarm", "hydrant"])  # fmt: skip
        else:
            rule(T.cite("5.9.2", ""), "up to 750 m² undivided: manual alarm with portable "
                 "extinguishers or hydrants (5.9.2(o))", required=["manualAlarm"],
                 any_of=["extinguishers", "hydrant"])  # fmt: skip
    elif group == "H1":
        rule(T.cite("5.10", " 5.10.1"), "manually operated electric alarm; performance based "
             "protection for the stored materials", required=["manualAlarm"],
             performance=["hydrant"])  # fmt: skip
    elif group == "H2":
        rule(T.cite("5.10", " 5.10.2"), "performance based fire protection",
             performance=["hydrant", "sprinklers"])  # fmt: skip
    elif group == "I1":
        rule(T.cite("5.11", " 5.11.1"), "manual alarm, portable appliances; the stage preferably "
             "sprinklered (required above and below a stage with fly galleries, "
             f"{T.PAGES['4:2.12.9']})", required=["manualAlarm", "extinguishers"],
             recommended=["sprinklers"])  # fmt: skip
    elif group in ("I2", "I4"):
        text = (
            ""
            if group == "I2"
            else " (the code refers to Sec 5.6.3, which Sec 5.6 lacks: 5.6.1 taken)"
        )
        rule(T.cite("5.11", f" 5.11.{2 if group == 'I2' else 4}"), "as Sec 5.6.1: alarm and "
             "portable appliances" + text, required=["manualAlarm", "extinguishers"])  # fmt: skip
    elif group == "I3":
        rule(T.cite("5.11", " 5.11.3"), "automatic fire alarm, portable appliances",
             required=["automaticAlarm", "extinguishers"])  # fmt: skip
    elif group == "I5":
        rule(T.cite("5.11", " 5.11.5"), "manually operated electric alarm, portable appliances",
             required=["manualAlarm", "extinguishers"])  # fmt: skip
    elif letter == "J":
        rule(T.cite("5.12"), "automatic fire alarm and automatic fixed gaseous, foam or dry "
             "chemical system", required=["automaticAlarm", "special"])  # fmt: skip
    elif letter == "K":
        rule(T.cite("5.13", "(d)"), "parking only: NFPA 101 (2015) chapter 42", performance=[
             "extinguishers"])  # fmt: skip
    elif letter == "L":
        rule(T.cite("5.14"), "utilities: Sec 2.12 (NFPA or equivalent)",
             performance=["extinguishers"])  # fmt: skip
    else:
        rule(T.cite("5.14"), "miscellaneous: performance based fire protection",
             performance=["extinguishers"])  # fmt: skip


def fire_plan(ctx: Context, groups: set[str], gross: dict[str, float]) -> list[str]:
    """The reasons Sec 5.1.6 asks for a fire protection plan (empty: none asked)."""
    reasons = []
    if ctx.high_rise:
        reasons.append(f"high-rise, 33 m and above ({T.cite('5.1.6', '(a)')})")
    letters = {g[:1] for g in groups}
    if letters & set("GHJKM") and ctx.storeys >= 2 and (ctx.max_floor > 1858 or ctx.total > 4717):
        reasons.append(
            f"occupancy {'/'.join(sorted(letters & set('GHJKM')))} of 2 storeys or more over "
            f"1858 m² a floor or 4717 m² in all ({T.cite('5.1.6', '(b)')})"
        )
    if "A3" in groups and (ctx.dwelling_units or 0) >= 30:
        reasons.append(f"{ctx.dwelling_units} dwelling units ({T.cite('5.1.6', '(c)')})")
    a45 = sum(a for g, a in gross.items() if g in ("A4", "A5"))
    if a45 > 1200:
        reasons.append(f"hostel or hotel of {a45:.0f} m² > 1200 m² ({T.cite('5.1.6', '(c)')})")
    used = sum(a for g, a in gross.items() if g[:1] in "FICD")
    if used > 930:
        reasons.append(
            f"mercantile, assembly, institutional or health care {used:.0f} m² > 930 m² "
            f"({T.cite('5.1.6', '(d)')})"
        )
    return reasons


def requirements(
    stories: list[dict[str, Any]],
    *,
    height: float,
    storeys: int,
    top_occupied: float,
    building: Any,
    hydrant_choice: bool | None,
    detection_choice: bool | None,
) -> dict[str, Any]:
    """The systems the building needs. ``stories``: ``{story, occupancy, area, undivided,
    level (m above ground), sprinklered}`` of each fire story; ``height`` the building's [m],
    ``storeys`` its stories above ground, ``top_occupied`` the highest occupied floor [m];
    ``building`` the 07 MEP ``fire.building``."""
    # Part 1 (p6): more than 10 storeys or 33 m high; Part 3 Sec 2.4.4 (p94): an occupied floor
    # more than 33 m above the ground.
    high_rise = (
        storeys > T.HIGH_RISE_STOREYS
        or height > T.HIGH_RISE_HEIGHT
        or top_occupied > T.HIGH_RISE_HEIGHT
    )
    floors = [s["area"] for s in stories if s["level"] >= 0] or [s["area"] for s in stories]
    ctx = Context(
        high_rise=high_rise,
        storeys=storeys,
        height=height,
        max_floor=max(floors, default=0.0),
        total=sum(s["area"] for s in stories),
        undivided=max((s["undivided"] for s in stories), default=0.0),
        corridor=building.corridor,
        occupant_load=building.occupantLoad,
        false_ceiling=building.falseCeiling,
        dwelling_units=building.dwellingUnits,
    )
    by_key: dict[str, list[dict[str, Any]]] = {}
    for s in stories:
        by_key.setdefault(s["occupancy"], []).append(s)
    rules: list[Rule] = []
    for key, rows in by_key.items():
        above = [r["story"] for r in rows if r["level"] >= 0]
        below = [r["story"] for r in rows if r["level"] < 0]
        if OCCUPANCIES[key].group == "F2" and below:
            _group(rules, ctx, key, below, True)
        _group(rules, ctx, key, above + below, False)
    notes = []
    if building.construction == "other":
        notes.append(
            "construction other than Type I-A: performance based fire protection for the whole "
            f"building ({T.cite('5.2', ' 5.2.5')}); the systems below are the least"
        )
    elif building.construction == "modifiedIA":
        notes.append(f"Modified Type I-A construction ({T.cite('5.2', ' 5.2.3')})")

    status = {s: "notRequired" for s in SYSTEMS}
    reasons: dict[str, list[str]] = {s: [] for s in SYSTEMS}

    def raise_to(system: str, level: str, why: str) -> None:
        if LEVELS.index(level) > LEVELS.index(status[system]):
            status[system] = level
        reasons[system].append(why)

    for r in rules:
        why = f"{r.group}: {r.text} ({r.clause})"
        for s in r.required:
            raise_to(s, "required", why)
        for s in r.performance:
            raise_to(s, "performance", why)
        for s in r.recommended:
            raise_to(s, "recommended", why)
    for r in rules:
        if not r.any_of:
            continue
        if any(status[s] == "required" for s in r.any_of):
            continue  # another rule already requires one of them
        chosen = "hydrant" if hydrant_choice and "hydrant" in r.any_of else r.any_of[0]
        raise_to(chosen, "required", f"{r.group}: {r.text}, {chosen} chosen ({r.clause})")
    if status["extinguishers"] == "notRequired":
        raise_to(
            "extinguishers", "recommended",
            f"portable extinguishers by the hazard, at least one below 279 m² of floor "
            f"({T.PAGES['4.4.2.ext']})",
        )  # fmt: skip
    sprinkled = [s["story"] for s in stories if s.get("sprinklered")]
    provided = {
        "extinguishers": status["extinguishers"] != "notRequired",
        "manualAlarm": status["manualAlarm"] in ("required", "performance") or status[
            "automaticAlarm"] == "required",
        "automaticAlarm": status["automaticAlarm"] == "required" or bool(detection_choice),
        "hydrant": status["hydrant"] == "required" or bool(hydrant_choice)
        or (hydrant_choice is None and status["hydrant"] == "performance"),
        "sprinklers": status["sprinklers"] == "required" or bool(sprinkled),
        "special": status["special"] in ("required", "performance"),
    }  # fmt: skip
    if detection_choice is False and status["automaticAlarm"] == "required":
        notes.append("automatic detection is required: it is designed although set off")
    if hydrant_choice is False and status["hydrant"] == "required":
        notes.append("a hydrant system is required: it is designed although set off")
    gross: dict[str, float] = {}
    for s in stories:
        g = OCCUPANCIES[s["occupancy"]].group
        gross[g] = gross.get(g, 0.0) + s["area"]
    plan = fire_plan(ctx, set(gross), gross)
    return {
        "highRise": high_rise,
        "tall": height > T.TALL_HEIGHT,
        "storeys": storeys,
        "height": round(height, 2),
        "topOccupied": round(top_occupied, 2),
        "highRiseNote": (
            f"{storeys} {'storey' if storeys == 1 else 'storeys'} above ground, {height:.1f} m "
            f"high, highest occupied floor {top_occupied:.1f} m: "
            f"{'high-rise' if high_rise else 'not high-rise'} (more than "
            f"{T.HIGH_RISE_STOREYS} storeys, 33 m high or an occupied floor above 33 m, "
            f"{T.PAGES['high-rise']})"
        ),
        "systems": [
            {
                "system": s,
                "label": SYSTEMS[s],
                "status": status[s],
                "provided": provided[s],
                "reasons": reasons[s],
            }
            for s in SYSTEMS
        ],
        "rules": [r.as_dict() for r in rules],
        "firePlan": {"required": bool(plan), "reasons": plan},
        "notes": notes,
    }


def extinguishers(area: float, hazard: str) -> tuple[int, str]:
    """Portable extinguishers on a floor of ``area`` m² (NFPA 10, from memory) and the note."""
    row = T.EXTINGUISHER[T.family(hazard)]
    cover = min(row["perUnit"] * row["rating"], row["max"])
    count = max(1, math.ceil(area / cover - 1e-9))
    return count, (
        f"{row['rating']}-A each covering {cover:.0f} m² (NFPA 10, {T.MEMORY}); at least one "
        f"below {T.EXTINGUISHER_SMALL_FLOOR:g} m² ({T.PAGES['4.4.2.ext']}); travel at most "
        f"{T.EXTINGUISHER_TRAVEL:g} m ({T.MEMORY})"
    )

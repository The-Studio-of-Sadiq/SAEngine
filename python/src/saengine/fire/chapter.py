"""The fire protection chapter of the project report (Part 7, BNBC 2020 Part 4).

:func:`fire_chapter` turns :func:`saengine.fire.report.fire_report` into the rows the report's
template prints: what Part 4 requires and why, the floors, the water and the reservoir, the
pumps and the fire tanks with their weights on the structure, the hanger and support loads, the
sleeves still missing and the checks with their clauses. ``loaded``: the fire items as the
analysis takes their weights (the report's ``services_by_discipline`` group ``fire``).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

STATUS = {
    "required": "required",
    "performance": "performance based",
    "recommended": "recommended",
    "notRequired": "not required",
}


def _fmt(value: Any, digits: int = 1) -> str:
    """A number as the report prints it ("–" for none)."""
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return "–"
    value = float(value)
    if not math.isfinite(value):
        return "–"
    if abs(value) < 0.5 * 10**-digits:
        value = 0.0
    return f"{value:,.{digits}f}"


def _checks(rows: list[dict[str, Any]]) -> list[list[str]]:
    return [
        [
            str(c.get("name") or ""),
            _fmt(c.get("demand"), 2),
            _fmt(c.get("capacity"), 2),
            str(c.get("unit") or ""),
            _fmt(c.get("utilisation"), 2),
            "OK" if c.get("ok") else "FAIL",
            str(c.get("clause") or ""),
        ]
        for c in rows
    ]


def _load(item_id: str, loaded: dict[str, dict[str, Any]], link: str | None) -> str:
    if link:
        return f"as equipment {link}"
    entry = loaded.get(item_id)
    if entry is None:
        return "not loaded (see the notes)"
    empty = entry.get("emptyWeight")
    return (
        f"{_fmt(entry['operatingWeight'], 1)} kN"
        + (f" ({_fmt(empty, 1)} kN SD + contents F)" if empty else " SD")
        + (", impact L" if entry.get("vibrating") else "")
    )


def fire_chapter(root: str | Path, mep: Any, loaded: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The chapter's data; ``{"available": False}`` while 07 MEP has no fire section."""
    from saengine.fire.report import fire_report
    from saengine.library.mep import FIRE_HAZARDS, FIRE_PUMP_DUTIES
    from saengine.plumbing.tables import OCCUPANCIES

    empty = {"available": False, "problem": "", "notes": []}
    fire = mep.fire
    if fire is None:
        return empty
    report = fire_report(root)
    if not report.get("requirements"):
        problems = report.get("problems") or report.get("notes") or []
        return {**empty, "problem": "; ".join(str(x) for x in problems)}
    req = report["requirements"]
    systems = [
        [s["label"], STATUS.get(s["status"], s["status"]), "yes" if s["provided"] else "no",
         "; ".join(s["reasons"]) or "–"]
        for s in req["systems"]
    ]  # fmt: skip
    stories = []
    for r in report["stories"]:
        spr = r.get("sprinklers") or {}
        stories.append([
            str(r["story"]), f"{OCCUPANCIES[r['occupancy']].label} ({r['group']})",
            FIRE_HAZARDS.get(r["hazard"], r["hazard"]), _fmt(r["area"], 0),
            str(spr.get("heads") or "–"), str(r["extinguishers"] or "–"),
            str(r["callPoints"] or "–"), str(r["detectors"] or "–"),
        ])  # fmt: skip
    water: list[list[str]] = []
    dem = report.get("demand")
    if dem:
        water = [["Standpipes", f"{_fmt(dem['standpipe'], 0)} l/min"],
                 ["Sprinklers", f"{_fmt(dem['sprinkler'], 0)} l/min"],
                 ["Total", f"{_fmt(dem['flow'], 0)} l/min for {dem['duration']} min"],
                 ["Reservoir", f"{_fmt(dem['volume'], 1)} m³"]]  # fmt: skip
        storage = report.get("storage") or {}
        if storage:
            water.append(["Stored", f"{_fmt(storage.get('provided'), 1)} m³"])
    hyd = report.get("hydraulics") or {}
    if hyd:
        water.append(["Pump duty", f"{_fmt(hyd['flow'], 0)} l/min at {_fmt(hyd['pumpHead'], 1)} m"])
        if hyd.get("sprinkler"):
            s = hyd["sprinkler"]
            water.append(["Sprinklers (hydraulic)",
                          (f"{s['heads']} heads on {s['story']}: {_fmt(s['sprinklerFlow'], 0)} "
                          f"l/min, least head {_fmt(s['least'], 1)} l/min")])  # fmt: skip
    pumps = []
    for p in fire.pumps:
        size = " x ".join(_fmt(getattr(p, k), 0) for k in ("length", "width") if getattr(p, k))
        pumps.append([p.id, FIRE_PUMP_DUTIES[p.duty], p.story,
                      f"{_fmt(p.flow, 0)} l/min x {_fmt(p.head, 1)} m", _fmt(p.power, 1),
                      size or "typical", _load(p.id, loaded, p.equipment)])  # fmt: skip
    required = [
        [FIRE_PUMP_DUTIES[p["duty"]], f"{_fmt(p['flow'], 0)} l/min x {_fmt(p['head'], 1)} m",
         _fmt(p["power"], 1), f"{_fmt(p['length'], 0)} x {_fmt(p['width'], 0)}",
         _fmt(p["operatingWeight"], 1)]
        for p in report.get("pumps") or []
    ]  # fmt: skip
    designs = {d.get("id"): d for d in report.get("tankDesigns") or []}
    tanks = []
    for t in fire.tanks:
        d = designs.get(t.id) or {}
        failed = [c for c in d.get("checks", []) if not c.get("ok", True)]
        state = (
            f"not designed: {d['error']}" if d.get("error") else
            f"{len(failed)} check(s) fail" if failed else "designed, all checks pass" if d else "–"
        )  # fmt: skip
        dims = " x ".join(_fmt(getattr(t, k), 0) for k in ("length", "width", "waterDepth")
                          if getattr(t, k))  # fmt: skip
        tanks.append([t.id, t.kind, dims or "–", state,
                      _load(t.id, loaded, t.equipment) if t.kind == "overhead" else
                      "on the ground (not the frame)"])  # fmt: skip
    supports = [
        [f"DN{_fmt(s['size'], 0)}", s["kind"], _fmt(s["spacing"], 1), _fmt(s["load"], 2), s["basis"]]
        for s in report.get("supports") or []
    ]  # fmt: skip
    openings = [
        [str(o.get("id")), str(o.get("host")), _fmt(o.get("diameter"), 0), str(o.get("service") or "")]
        for o in report.get("openings") or []
    ]  # fmt: skip
    checks = list(report.get("checks") or [])
    room = report.get("pumpRoom") or {}
    notes = [str(n) for n in report.get("notes") or []]
    notes += [str(x) for x in report.get("problems") or []]
    return {
        "available": True,
        "problem": "",
        "summary": [[f"{i + 1}", str(line)] for i, line in enumerate(report.get("summary") or [])],
        "highRise": str(req["highRiseNote"]),
        "firePlan": "; ".join(req["firePlan"]["reasons"]) if req["firePlan"]["required"] else "",
        "systems": systems,
        "stories": stories,
        "water": water,
        "pumps": pumps,
        "requiredPumps": required,
        "pumpRoom": (
            f"{_fmt(room.get('length', 0) / 1000, 1)} x {_fmt(room.get('width', 0) / 1000, 1)} m "
            f"({_fmt(room.get('area'), 1)} m²): {room.get('note', '')}"
            if room
            else ""
        ),
        "tanks": tanks,
        "supports": supports,
        "openings": openings,
        "tests": [
            [t["system"], f"{t['pressure']} kPa", t["note"]]
            for t in report.get("testPressures") or []
        ],
        "checks": _checks(checks),
        "checkFails": [not c.get("ok") for c in checks],
        "failed": sum(1 for c in checks if not c.get("ok")),
        "method": [str(m) for m in report.get("method") or []],
        "notes": notes,
    }

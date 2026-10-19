"""The summary files the project's part list reads, written exactly as the workbench writes them.

Run All in the workbench writes them in TypeScript; this is the same code in Python, so a run of
the command line leaves the sidebar current. Each function names the TypeScript it mirrors:

- ``08 FEM/model.results/design-summary.json``: ``designSummaryFile`` (``femDesign.ts``);
- ``09 Substructure/substructure.results/summary.json``: ``substructureSummaryFile``
  (``substructureDocument.ts``), with ``readSubstructureReport``'s defaults;
- ``07 MEP/mep.results/summary.json``: ``mepSummaryFile`` (``mepDocument.ts``) with
  ``plumbingSummaryFile``, ``hvacSummaryFile`` and ``electricalSummaryFile`` under ``plumbing``,
  ``hvac`` and ``electrical``, and the failure counts the part list and Run All show.

The texts are ``JSON.stringify(summary, undefined, '\\t') + '\\n'`` (:func:`js_stringify`), the
times ``Date.toISOString()`` (:func:`iso_time`), the stamps ``sourceStamp``
(:func:`saengine.library.bim.source_stamp`).
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from saengine.fem.derive import js_json
from saengine.library.bim import source_stamp

DESIGN_SUMMARY_FILE = "design-summary.json"
SUBSTRUCTURE_SUMMARY_FILE = "substructure.results/summary.json"
MEP_SUMMARY_FILE = "mep.results/summary.json"
MEP_SCHEMA_ID = "saengine.mep/1"
SUBSTRUCTURE_SCHEMA_ID = "saengine.substructure/1"
#: The parts the MEP report reads besides the MEP file (``MEP_SOURCE_PARTS``).
MEP_SOURCE_PARTS = ("settings", "materials", "objects", "bim")

# ─────────────────────────────── JSON as JavaScript writes it ───────────────────────────────


def js_stringify(value: Any, indent: str = "\t") -> str:
    """``JSON.stringify(value, undefined, indent)``: numbers as JavaScript writes them (``3`` for
    3.0, ``1e-7``), non-ASCII characters as they are, empty lists and objects as ``[]``, ``{}``."""

    def write(item: Any, depth: int) -> str:
        if isinstance(item, dict):
            if not item:
                return "{}"
            inner = indent * (depth + 1)
            entries = [f"{inner}{js_json(str(k))}: {write(v, depth + 1)}" for k, v in item.items()]
            return "{\n" + ",\n".join(entries) + "\n" + indent * depth + "}"
        if isinstance(item, list | tuple):
            if not item:
                return "[]"
            inner = indent * (depth + 1)
            entries = [f"{inner}{write(v, depth + 1)}" for v in item]
            return "[\n" + ",\n".join(entries) + "\n" + indent * depth + "]"
        return js_json(item)

    return write(value, 0)


def summary_text(summary: dict[str, Any]) -> str:
    """The text of a summary file: ``JSON.stringify(summary, undefined, '\\t') + '\\n'``."""
    return js_stringify(summary) + "\n"


def iso_time(moment: datetime | None = None) -> str:
    """``Date.toISOString()``: UTC to the millisecond, ``2026-10-18T10:34:38.462Z``."""
    moment = (moment or datetime.now(UTC)).astimezone(UTC)
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{moment.microsecond // 1000:03d}Z"


# ─────────────────────────────── reading defensively (mepRead.ts) ───────────────────────────────


def is_record(value: Any) -> bool:
    return isinstance(value, dict)


def records(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def optional_number(value: Any) -> float | None:
    """A finite number (not a boolean), else None (``optionalNumber``)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def num(value: Any, fallback: float = 0) -> float:
    number = optional_number(value)
    return fallback if number is None else number


def optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def strings(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def js_string(value: Any) -> str:
    """``String(value ?? '')`` for the ids the reports carry."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return js_json(value)
    return value if isinstance(value, str) else json.dumps(value)


def status_of(item: dict[str, Any]) -> str:
    """``statusOf``: "ok", "warn", "fail" from ``status``, else ``ok``, else the utilisation."""
    status = item.get("status")
    if status in ("ok", "pass"):
        return "ok"
    if status in ("warn", "warning"):
        return "warn"
    if status in ("fail", "failed"):
        return "fail"
    if isinstance(item.get("ok"), bool):
        return "ok" if item["ok"] else "fail"
    u = optional_number(item.get("utilisation"))
    if u is None:
        return "none"
    return "fail" if u > 1 else "warn" if u >= 0.9 else "ok"


def check_statuses(value: Any) -> list[str]:
    """The statuses of ``readChecks(value)``."""
    return [status_of(c) for c in records(value)]


def string_sources(raw: dict[str, Any]) -> dict[str, str] | None:
    """A report's ``sources``, its string entries only; None when it has none."""
    sources = raw.get("sources")
    if not isinstance(sources, dict):
        return None
    return {k: v for k, v in sources.items() if isinstance(v, str)}


def problems_only(raw: Any, keys: tuple[str, ...]) -> list[str] | None:
    """The problems of a backend answer that has only ``problems`` (none of ``keys``), as the
    desktop commands turn into an error (``problemsOrResult``); None otherwise."""
    if not isinstance(raw, dict):
        return None
    problems = raw.get("problems")
    if isinstance(problems, list) and problems and all(raw.get(k) is None for k in keys):
        return [str(p) for p in problems]
    return None


# ─────────────────────────────── 8 FEM: the design checks ───────────────────────────────


def design_summary_file(report: dict[str, Any], computed: datetime | None = None) -> dict[str, Any]:
    """``designSummaryFile`` of a design report (``saengine.design.design_report``)."""
    summary = record(report.get("summary"))
    return {
        "checked": summary.get("checked"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "maxUtilisation": summary.get("maxUtilisation"),
        "governing": summary.get("governing"),
        "computed": iso_time(computed),
    }


# ─────────────────────────────── 9 Substructure ───────────────────────────────


def parse_document(text: str, part: str, schema: str, lists: tuple[str, ...]) -> tuple[str, Any]:
    """``parseMep`` / ``parseSubstructure``: ``("placeholder", None)``, ``("error", message)``
    or ``("document", the object with its lists filtered to objects)``."""
    if not text.strip():
        return "placeholder", None
    try:
        value = json.loads(text)
    except ValueError as error:
        return "error", f"This file contains invalid JSON ({error})."
    if not isinstance(value, dict):
        return "error", "This file does not contain a JSON object."
    if value.get("part") == part and all(k in ("schema", "part") for k in value):
        return "placeholder", None
    if value.get("schema") != schema:
        return "error", f"This file is not a SAEngine {part} file ({schema})."
    for key in lists:
        if key in value and value[key] is not None and not isinstance(value[key], list):
            return "error", f"The {part} file's {key} are not a list."
    for key in lists:
        value[key] = records(value.get(key) or [])
    return "document", value


def parse_substructure(text: str) -> tuple[str, Any]:
    return parse_document(
        text, "substructure", SUBSTRUCTURE_SCHEMA_ID, ("foundations", "pileTypes", "tieBeams")
    )


def parse_mep(text: str) -> tuple[str, Any]:
    return parse_document(
        text, "mep", MEP_SCHEMA_ID, ("equipment", "openings", "shafts", "ifcModels")
    )


def _nullable(value: Any) -> float | None:
    return optional_number(value)


def substructure_report_summary(raw: Any) -> dict[str, Any] | None:
    """``readSubstructureReport(raw).summary`` (with its defaults from the foundations and tie
    beams); None when ``raw`` is not a report."""
    if not isinstance(raw, dict) or not isinstance(raw.get("foundations"), list):
        return None

    def result(f: dict[str, Any]) -> tuple[bool, float | None, str]:
        checks = records(f.get("checks"))
        counted = [
            u
            for c in checks
            if c.get("flag") is not True
            for u in [_nullable(c.get("utilisation"))]
            if u is not None
        ]
        utilisation = _nullable(f.get("utilisation"))
        if utilisation is None and counted:
            utilisation = max(counted)
        ok = (
            f["ok"]
            if isinstance(f.get("ok"), bool)
            else all(c.get("ok") is not False or c.get("flag") is True for c in checks)
        )
        return ok, utilisation, js_string(f.get("id"))

    designed = [result(f) for f in [*records(raw["foundations"]), *records(raw.get("tieBeams"))]]
    failed = sum(1 for ok, _, _ in designed if not ok)
    worst: tuple[bool, float | None, str] | None = None
    for item in designed:
        if (
            item[1] is not None
            and (-1 if worst is None or worst[1] is None else worst[1]) < item[1]
        ):
            worst = item
    summary = record(raw.get("summary"))

    def pick(key: str, fallback: Any) -> Any:
        number = optional_number(summary.get(key))
        return fallback if number is None else number

    max_utilisation = _nullable(summary.get("maxUtilisation"))
    if max_utilisation is None:
        max_utilisation = worst[1] if worst is not None else None
    governing = summary.get("governing")
    if not isinstance(governing, str):
        governing = worst[2] if worst is not None else None
    return {
        "checked": pick("checked", len(designed)),
        "passed": pick("passed", len(designed) - failed),
        "failed": pick("failed", failed),
        "maxUtilisation": max_utilisation,
        "governing": governing,
    }


def substructure_summary_file(
    document: dict[str, Any], raw: dict[str, Any], computed: datetime | None = None
) -> dict[str, Any]:
    """``substructureSummaryFile`` of the substructure document and its report."""
    summary = substructure_report_summary(raw) or {}
    result: dict[str, Any] = {
        "foundations": len(document.get("foundations", [])),
        "checked": summary.get("checked"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "maxUtilisation": summary.get("maxUtilisation"),
        "governing": summary.get("governing"),
        "computed": iso_time(computed),
    }
    sources = string_sources(raw)
    if sources is not None:
        result["source"] = sources
    return result


# ─────────────────────────────── 7 MEP: coordination ───────────────────────────────

_STRENGTH_SKIPPED = re.compile(
    r"no analysis results|not found in the analysis results|\bis not checked\b|are not checked"
    r"|\(no results\)",
    re.IGNORECASE,
)


def mep_openings(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """``readMepReport(raw).openings``: ``{id, ok, strengthChecked}``."""
    openings = []
    for o in records(raw.get("openings")):
        if not isinstance(o.get("id"), str):
            continue
        checked = o.get("checked") is not False
        utilisation = optional_number(o.get("utilisation")) if checked else None
        note = optional_string(o.get("note"))
        texts = [
            note or "",
            *strings(o.get("notes")),
            *(
                c["note"] if isinstance(c.get("note"), str) else ""
                for c in records(o.get("checks"))
            ),
        ]
        skipped = any(_STRENGTH_SKIPPED.search(t) for t in texts)
        strength = checked and (
            o["strengthChecked"] if isinstance(o.get("strengthChecked"), bool) else not skipped
        )
        ok = (not checked) or (
            o["ok"] if isinstance(o.get("ok"), bool) else utilisation is None or utilisation <= 1
        )
        openings.append({"id": o["id"], "ok": ok, "strengthChecked": strength})
    return openings


def mep_clashes(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """``readMepReport(raw).clashes``: ``{status, kind}``."""
    return [
        {
            "status": "coordinated" if c.get("status") == "coordinated" else "clash",
            "kind": js_string(c.get("kind", "hard")) if c.get("kind") is not None else "hard",
        }
        for c in records(raw.get("clashes"))
    ]


def is_open_clash(clash: dict[str, Any]) -> bool:
    return clash["status"] == "clash" and clash["kind"] != "clearance"


def mep_summary_file(
    document: dict[str, Any],
    raw: dict[str, Any],
    mep_text: str,
    source_texts: dict[str, str | None],
    computed: datetime | None = None,
) -> dict[str, Any]:
    """``mepSummaryFile``: ``source_texts`` are the texts of :data:`MEP_SOURCE_PARTS`."""
    openings = mep_openings(raw)
    clashes = mep_clashes(raw)
    source: dict[str, str] = dict(string_sources(raw) or {})
    for part in MEP_SOURCE_PARTS:
        text = source_texts.get(part)
        source[part] = "" if text is None else source_stamp(text)
    source["mep"] = source_stamp(mep_text)
    return {
        "equipment": len(document.get("equipment", [])),
        "openings": len(document.get("openings", [])),
        "openingsFailed": sum(1 for o in openings if not o["ok"]),
        "openingsPartial": sum(1 for o in openings if o["ok"] and not o["strengthChecked"]),
        "clashes": len(clashes),
        "clashesOpen": sum(1 for c in clashes if is_open_clash(c)),
        "computed": iso_time(computed),
        "source": source,
    }


# ─────────────────────────────── 7 MEP: plumbing ───────────────────────────────


def _section(document: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = document.get(key)
    return value if isinstance(value, dict) else None


def has_plumbing(document: dict[str, Any]) -> bool:
    p = _section(document, "plumbing")
    if p is None:
        return False
    roof = record(p.get("roof"))
    count = sum(len(records(p.get(k))) for k in ("stories", "risers", "tanks"))
    return count + len(records(roof.get("drains"))) > 0


def plumbing_failures(raw: dict[str, Any]) -> dict[str, int]:
    """``plumbingFailures(readPlumbingReport(raw))``: ``{items, floorsLow}``."""
    hydraulics = record(raw.get("hydraulics"))
    storage = record(raw.get("storage"))
    statuses = [
        *check_statuses(raw.get("checks")),
        *check_statuses(hydraulics.get("checks")),
        *(s for t in records(raw.get("tankDesigns")) for s in check_statuses(t.get("checks"))),
    ]
    floors = [
        f for f in records(hydraulics.get("floors")) if optional_number(f.get("head")) is not None
    ]
    required_head = optional_number(hydraulics.get("requiredHead"))
    if required_head is None:
        required_head = optional_number(record(storage.get("heads")).get("minResidualHead"))
    if required_head is None and floors:
        required_head = optional_number(floors[0].get("required"))
    low: set[str] = set()
    for f in floors:
        head = num(f.get("head"))
        required = optional_number(f.get("required"))
        if required is None:
            required = required_head
        if isinstance(f.get("pressureOk"), bool):
            failing = not f["pressureOk"]
        else:
            failing = required is not None and head < required
        if failing:
            low.add(js_string(f.get("story")))
    return {"items": sum(1 for s in statuses if s == "fail"), "floorsLow": len(low)}


def plumbing_summary_file(document: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """``plumbingSummaryFile``."""
    p = _section(document, "plumbing")
    failures = plumbing_failures(raw)
    result: dict[str, Any] = {
        "risers": len(records(p.get("risers"))) if p else 0,
        "tanks": len(records(p.get("tanks"))) if p else 0,
        "failed": failures["items"],
        "floorsLow": failures["floorsLow"],
    }
    soil = (string_sources(raw) or {}).get("soil")
    if soil is not None:
        result["source"] = {"soil": soil}
    return result


# ─────────────────────────────── 7 MEP: HVAC ───────────────────────────────


def has_hvac(document: dict[str, Any]) -> bool:
    h = _section(document, "hvac")
    if h is None:
        return False
    count = sum(len(records(h.get(k))) for k in ("stories", "plant", "ducts"))
    return count > 0 or bool(h.get("system")) or bool(record(h.get("design")).get("city"))


def opening_statuses(value: Any, conflicts: Any) -> list[str]:
    """The statuses of ``readOpeningResults(value, conflicts)``: a proposed opening that passes
    is ok unless it carries its own verdict; every conflict fails."""
    passing = []
    for o in records(value):
        explicit = (
            o.get("status") is not None
            or isinstance(o.get("ok"), bool)
            or optional_number(o.get("utilisation")) is not None
        )
        passing.append(status_of(o) if explicit else "ok")
    return [*passing, *("fail" for _ in records(conflicts))]


def _hvac_parts(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    loads = raw["loads"] if isinstance(raw.get("loads"), dict) else raw
    air = raw["air"] if isinstance(raw.get("air"), dict) else raw
    return loads, air


def hvac_failures(raw: dict[str, Any]) -> int:
    """``hvacFailures(readHvacReport(raw))``: the failing checks, else the failing ducts, plant,
    openings and shafts."""
    loads, air = _hvac_parts(raw)
    checks = [*(check_statuses(loads.get("checks")) if air is not loads else []),
              *check_statuses(air.get("checks"))]  # fmt: skip
    if checks:
        return sum(1 for s in checks if s == "fail")
    rows = [
        *check_statuses(air.get("ducts")),
        *check_statuses(air.get("plant")),
        *opening_statuses(air.get("openings"), air.get("conflicts")),
        *check_statuses(air.get("shafts")),
    ]
    return sum(1 for s in rows if s == "fail")


def hvac_cooling(raw: dict[str, Any]) -> float | None:
    """``readHvacReport(raw).total.total``: the loads' total, else the zones' sum [kW]."""
    loads, air = _hvac_parts(raw)
    total = optional_number(loads.get("total"))
    if total is not None:
        return total
    load_rows = records(loads.get("zones"))
    air_rows: dict[str, dict[str, Any]] = {}
    for r in records(air.get("zones")):
        air_rows[js_string(r.get("story"))] = r
    extra = [
        r
        for r in air_rows.values()
        if not any(row.get("story") == r.get("story") for row in load_rows)
        and optional_number(r.get("total")) is not None
    ]
    totals = []
    for r in [*load_rows, *extra]:
        value = optional_number(r.get("total"))
        if value is None and optional_number(r.get("sensible")) is not None:
            value = num(r.get("sensible")) + num(r.get("latent"))
        totals.append(value)
    if not any(t is not None for t in totals):
        return None
    return sum(num(t) for t in totals)


def hvac_engine(raw: dict[str, Any]) -> tuple[str, bool]:
    """``engineOf``: the EnergyPlus version, else "estimate"; and whether it is an estimate."""
    engine = (
        optional_string(raw.get("engine"))
        or optional_string(record(raw.get("loads")).get("engine"))
        or ""
    )
    estimate = (
        not engine
        or bool(re.search("estimat", engine, re.IGNORECASE))
        or raw.get("estimate") is True
    )
    return engine or "estimate", estimate


def hvac_calculated(raw: dict[str, Any]) -> bool | None:
    loads, _ = _hvac_parts(raw)
    return loads["calculated"] if isinstance(loads.get("calculated"), bool) else None


def hvac_summary_file(document: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """``hvacSummaryFile``."""
    h = _section(document, "hvac")
    result: dict[str, Any] = {
        "plant": len(records(h.get("plant"))) if h else 0,
        "ducts": len(records(h.get("ducts"))) if h else 0,
    }
    cooling = hvac_cooling(raw)
    if cooling is not None:
        result["cooling"] = cooling
    result["engine"] = hvac_engine(raw)[0]
    result["failed"] = hvac_failures(raw)
    return result


# ─────────────────────────────── 7 MEP: electrical ───────────────────────────────


def has_electrical(document: dict[str, Any]) -> bool:
    e = _section(document, "electrical")
    if e is None:
        return False
    count = sum(len(records(e.get(k))) for k in ("stories", "equipment", "risers", "trays"))
    lightning = record(e.get("lightning"))
    return (
        count > 0 or bool(lightning.get("enabled")) or bool(record(e.get("supply")).get("voltage"))
    )


def _source_statuses(supply: dict[str, Any]) -> list[str]:
    """The statuses of ``readSources`` when the report has no checks."""
    statuses = []
    tx = record(supply.get("transformers"))
    if optional_number(tx.get("count")):
        statuses.append(status_of(tx))
    gen = record(supply.get("generator"))
    if optional_number(gen.get("kva")):
        statuses.append(status_of(gen))
    ups = record(supply.get("ups"))
    if optional_number(ups.get("kva")):
        statuses.append("ok")
    return statuses


def _tray_status(r: dict[str, Any]) -> str:
    if r.get("tray") is None:
        return status_of(r)
    return "ok" if r.get("passesBelow") is True or r.get("fits") is not False else "fail"


def electrical_failures(raw: dict[str, Any]) -> int:
    """``electricalFailures(readElectricalReport(raw))``."""
    checks = check_statuses(raw.get("checks"))
    if checks:
        return sum(1 for s in checks if s == "fail")
    rows = [
        *_source_statuses(record(raw.get("supply"))),
        *check_statuses(raw.get("rooms")),
        *check_statuses(raw.get("risers")),
        *(_tray_status(r) for r in records(raw.get("trays"))),
        *opening_statuses(raw.get("openings"), raw.get("conflicts")),
        *check_statuses(raw.get("shafts")),
    ]
    return sum(1 for s in rows if s == "fail")


def electrical_demand(raw: dict[str, Any]) -> float | None:
    """``readElectricalReport(raw).total.kva`` [kVA]."""
    demand = record(raw.get("demand"))
    kva = optional_number(demand.get("kva"))
    if kva is not None:
        return kva
    values = [optional_number(r.get("kva")) for r in records(demand.get("stories"))]
    if not any(v is not None for v in values):
        return None
    return sum(num(v) for v in values)


def _down_conductors(raw: dict[str, Any]) -> int:
    lightning = raw.get("lightning")
    if not isinstance(lightning, dict):
        return 0
    count = 0
    items = lightning.get("downConductors")
    for d in items if isinstance(items, list) else []:
        if isinstance(d, str):
            count += 1 if d else 0
        elif isinstance(d, dict):
            columns = strings(d.get("columns"))
            column = (columns[0] if columns else None) or optional_string(d.get("column"))
            column = column or optional_string(d.get("id"))
            count += 1 if column else 0
    return count


def electrical_summary_file(document: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """``electricalSummaryFile``."""
    e = _section(document, "electrical")
    result: dict[str, Any] = {
        "equipment": len(records(e.get("equipment"))) if e else 0,
        "risers": len(records(e.get("risers"))) if e else 0,
    }
    demand = electrical_demand(raw)
    if demand is not None:
        result["demand"] = demand
    result["downConductors"] = _down_conductors(raw)
    result["failed"] = electrical_failures(raw)
    return result


def openings_to_add(raw: Any) -> int:
    """``openingsOf``: how many openings a report proposes (those not in 07 MEP yet)."""
    openings = record(raw).get("openings")
    return len(openings) if isinstance(openings, list) else 0

"""The status of each part of a project as the project's part list (the sidebar) shows it.

A port of ``computePartStatuses`` (``services/saengineProject/common/partStatus.ts``) and of the
inputs ``SaenginePartStatusService.readInputs`` (``browser/partStatusService.ts``) gathers from
the project's files, so the command line reports the same state, text and hint the app would.
The rules read only files on disk, so the port is exact except for two presentational details:
the date in "report 19 Oct" is formatted ``%d %b`` (the app uses the system locale), and the
texts are English (the app's are localised).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from saengine.fem.derive import mep_stamp, settings_stamp
from saengine.library.bim import source_stamp
from saengine.pipeline.project import (
    ALL_PARTS,
    LOADS_PART,
    Part,
    Project,
    read_text,
    write_text,
)

#: The states of a part (``PartState``).
STATES = ("notStarted", "defaults", "inProgress", "done", "stale", "failed", "error")

FEM_RESULTS_FOLDER = "model.results"
FEM_RESULTS_MANIFEST = "manifest.json"
DESIGN_SUMMARY_FILE = "design-summary.json"
REPORT_FILE = "report.pdf"
SUBSTRUCTURE_SUMMARY_FILE = "substructure.results/summary.json"
MEP_SUMMARY_FILE = "mep.results/summary.json"
EXPORT_IFC_FOLDER = "IFC"
EXPORT_DXF_FOLDER = "Floor Plan"
#: A part's checks file (``PART_CHECKS_FILE``), in the part's folder.
PART_CHECKS_FILE = "checks.json"
PART_CHECKS_SCHEMA_ID = "saengine.partChecks/1"
#: At most this many items are kept in a checks file (``PART_CHECK_ITEMS``).
PART_CHECK_ITEMS = 20

#: Parts that never block the next step (``OPTIONAL_PARTS``).
OPTIONAL_PARTS = frozenset({"soil", "mep", "substructure"})
FEM_SOURCES = ("bim", "settings", "objects", "materials")
BOQ_SOURCES = ("bim", "objects", "materials")
BOQ_RECORDED_SOURCES = ("substructure", "settings", "mep")
FEM_RECORDED_SOURCES = ("substructure", "mep", "loads")
MEP_SCHEMA_ID = "saengine.mep/1"
SUBSTRUCTURE_SCHEMA_ID = "saengine.substructure/1"
BOQ_SCHEMA_ID = "saengine.boq/1"
SOIL_SCHEMA_ID = "saengine.soilReport/1"


@dataclass(frozen=True)
class PartStatus:
    """``IPartStatus``: a part's state, the few words the sidebar shows and what to do next."""

    part: str
    state: str
    text: str = ""
    hint: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StatusInputs:
    """``IPartStatusInputs``: times are modification times in ms since the epoch."""

    texts: dict[str, str | None] = field(default_factory=dict)
    femModelTime: float | None = None
    femResultsTime: float | None = None
    designSummaryText: str | None = None
    designSummaryTime: float | None = None
    reportTime: float | None = None
    exportFiles: int = 0
    substructureSummaryText: str | None = None
    substructureSummaryTime: float | None = None
    substructureTime: float | None = None
    mepSummaryText: str | None = None
    mepSummaryTime: float | None = None
    #: Text of each part's checks file by part id (``checksTexts``).
    checksTexts: dict[str, str | None] = field(default_factory=dict)


# ─────────────────────────────── stamps (partSources.ts) ───────────────────────────────


def ground_level_stamp_text(settings_text: str) -> str:
    """``groundLevelStamp``: of the settings' finished ground level, else of the whole text."""
    try:
        settings = json.loads(settings_text)
    except ValueError:
        return source_stamp(settings_text)
    ground: float = 0
    if isinstance(settings, dict):
        foundation = settings.get("foundation")
        value = foundation.get("groundLevel") if isinstance(foundation, dict) else None
        if isinstance(value, int | float) and not isinstance(value, bool):
            ground = value
    return source_stamp(f"groundLevel={math.floor(ground * 1000 + 0.5)}")


def boq_source_stamp(part: str, text: str) -> str:
    """``boqSourceStamp``."""
    return ground_level_stamp_text(text) if part == "settings" else source_stamp(text)


def fem_source_stamp(part: str, text: str) -> str:
    """``femSourceStamp``: of what the model takes for MEP, of the whole file otherwise."""
    return mep_stamp(text) if part == "mep" else source_stamp(text)


def recorded_stamp(document: Any, part: str) -> str | None:
    """``recordedStamp``: the stamp a derived document recorded for ``part``."""
    if not isinstance(document, dict):
        return None
    source = document.get("source")
    stamp = source.get(part) if isinstance(source, dict) else None
    return stamp if isinstance(stamp, str) else None


#: JavaScript's ``/Sources: (?<list>.*)$/``: ``$`` without the m flag is the very end (``\Z``).
_SOURCES = re.compile(r"Sources: (?P<list>.*)\Z")


def fem_recorded_sources(model: Any) -> dict[str, str]:
    """``femRecordedSources`` / ``recordedSources``: the stamps in ``meta.description``."""
    meta = model.get("meta") if isinstance(model, dict) else None
    description = meta.get("description") if isinstance(meta, dict) else None
    return recorded_sources(description)


def recorded_sources(description: Any) -> dict[str, str]:
    sources: dict[str, str] = {}
    match = _SOURCES.search(description) if isinstance(description, str) else None
    for entry in match.group("list").split(";") if match else []:
        pieces = entry.strip().split("=")
        key = pieces[0] if pieces else ""
        value = pieces[1] if len(pieces) > 1 else ""
        if key and value:
            sources[key] = value
    return sources


# ─────────────────────────────── helpers ───────────────────────────────


def _parse(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def is_placeholder(document: dict[str, Any], part: str) -> bool:
    return document.get("part") == part and all(k in ("schema", "part") for k in document)


def fem_source_changed(texts: dict[str, str | None], part: str, recorded: str | None) -> bool:
    """``femSourceChanged``: whether source ``part`` of the analysis model changed since the
    model recorded ``recorded``. The settings count without the project's details and title
    block (``settings_stamp``); a model derived before that recorded the whole file's stamp,
    which is still current while the file is unchanged."""
    text = texts.get(part)
    if text is None:
        return True
    if recorded == source_stamp(text):
        return False
    if part == "settings":
        return recorded != settings_stamp(text)
    return True


def _changed(texts: dict[str, str | None], part: str, recorded: str | None, stamp=None) -> bool:
    text = texts.get(part)
    if text is None:
        return True
    return recorded != (stamp(part, text) if stamp else source_stamp(text))


def _length(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _status(part: str, state: str, text: str = "", hint: str | None = None) -> PartStatus:
    return PartStatus(part, state, text, hint)


NOT_STARTED = "not started"
STALE = "stale"
INVALID = "invalid file"


def _start_hint(part: str) -> str:
    return {
        "soil": "enter the soil report",
        "settings": "set up the project",
        "materials": "choose the materials",
        "objects": "define the object types",
        "floorPlan": "draw the floor plan",
        "structure": "draw the structural model",
        "mep": "lay out the services",
        "substructure": "design the foundations",
    }.get(part, "open the part")


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _js(value: Any) -> str:
    """A number as JavaScript's template literal writes it."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ─────────────────────────────── 7 MEP ───────────────────────────────


def _mep_document(inputs: StatusInputs) -> dict[str, Any] | None:
    text = inputs.texts.get("mep")
    document = _parse(text) if text is not None else None
    return document if document and document.get("schema") == MEP_SCHEMA_ID else None


def _section(document: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = document.get(key)
    return value if isinstance(value, dict) else None


def _section_count(document: dict[str, Any], key: str, keys: tuple[str, ...]) -> int:
    section = _section(document, key)
    return sum(_length(section.get(k)) for k in keys) if section else 0


def _has_overhead_tank(document: dict[str, Any]) -> bool:
    plumbing = _section(document, "plumbing")
    tanks = plumbing.get("tanks") if plumbing else None
    return isinstance(tanks, list) and any(
        isinstance(t, dict) and t.get("kind") == "overhead" for t in tanks
    )


def loads_have_content(text: str | None) -> bool:
    """Whether a ``05 Floor Plan/loads.json`` text has a load (a model derived without it is
    then out of date); an unreadable file counts (deriving reports it)."""
    if not text or not text.strip():
        return False
    value = _parse(text)
    if value is None:
        return True
    loads = value.get("loads")
    return isinstance(loads, list) and len(loads) > 0


def _mep_has_content(inputs: StatusInputs) -> bool:
    document = _mep_document(inputs)
    if not document:
        return False
    return (
        any(_length(document.get(k)) > 0 for k in ("equipment", "openings", "shafts"))
        or _has_overhead_tank(document)
        or _section_count(document, "hvac", ("plant",)) > 0
        or _section_count(document, "electrical", ("equipment",)) > 0
        or _section_count(document, "fire", ("pumps",)) > 0
        or _has_overhead_fire_tank(document)
    )


def _has_overhead_fire_tank(document: dict[str, Any]) -> bool:
    fire = _section(document, "fire")
    tanks = fire.get("tanks") if fire else None
    return isinstance(tanks, list) and any(
        isinstance(t, dict) and t.get("kind") == "overhead" for t in tanks
    )


def _plumbing_count(document: dict[str, Any]) -> int:
    plumbing = _section(document, "plumbing")
    if not plumbing:
        return 0
    roof = plumbing.get("roof")
    drains = roof.get("drains") if isinstance(roof, dict) else None
    return (
        _length(plumbing.get("stories"))
        + _length(plumbing.get("risers"))
        + _length(plumbing.get("tanks"))
        + _length(drains)
    )


def _sources_unchanged(texts: dict[str, str | None], source: dict[str, Any]) -> bool:
    for part, recorded in source.items():
        text = texts.get(part)
        if recorded == "":
            if text is not None:
                return False
        elif text is None or recorded != source_stamp(text):
            return False
    return True


def _plural(count: Any, one: str, many: str) -> str:
    return one if count == 1 else many.format(_js(count))


def mep_status(inputs: StatusInputs) -> PartStatus:
    text = inputs.texts.get("mep")
    value = _parse(text) if text is not None else None
    if text is None or (value and is_placeholder(value, "mep")):
        return _status("mep", "notStarted", NOT_STARTED, _start_hint("mep"))
    if not value or value.get("schema") != MEP_SCHEMA_ID:
        return _status("mep", "error", INVALID, "fix the file")
    count = {k: _length(value.get(k)) for k in ("equipment", "openings", "shafts", "ifcModels")}
    plumbing_items = _plumbing_count(value)
    hvac_items = _section_count(value, "hvac", ("stories", "plant", "ducts"))
    electrical_items = _section_count(
        value, "electrical", ("stories", "equipment", "risers", "trays")
    )
    fire_items = _section_count(value, "fire", ("stories", "risers", "mains", "tanks", "pumps"))
    if not any(count.values()) and not any(
        (plumbing_items, hvac_items, electrical_items, fire_items)
    ):
        return _status("mep", "notStarted", NOT_STARTED, _start_hint("mep"))
    parsed = _parse(inputs.mepSummaryText) if inputs.mepSummaryText is not None else None
    summary = (
        parsed
        if parsed
        and _is_number(parsed.get("openingsFailed"))
        and _is_number(parsed.get("clashesOpen"))
        else None
    )
    source = summary.get("source") if summary and isinstance(summary.get("source"), dict) else None
    time = inputs.mepSummaryTime
    current = (
        summary is not None
        and source is not None
        and time is not None
        and _sources_unchanged(inputs.texts, source)
        and (inputs.femResultsTime is None or time >= inputs.femResultsTime)
    )
    if not current or summary is None:
        return _status("mep", "inProgress", "not checked", "check the openings and clashes")
    recorded = summary.get("plumbing")
    recorded = (
        recorded if isinstance(recorded, dict) and _is_number(recorded.get("failed")) else None
    )
    plumbing = (
        recorded
        if recorded
        and (
            not isinstance(recorded.get("source"), dict)
            or _sources_unchanged(inputs.texts, recorded["source"])
        )
        else None
    )

    def service(key: str) -> dict[str, Any] | None:
        item = summary.get(key)
        return item if isinstance(item, dict) and _is_number(item.get("failed")) else None

    hvac = service("hvac")
    electrical = service("electrical")
    fire = service("fire")
    openings_failed = summary["openingsFailed"]
    failing = [
        (openings_failed,
         _plural(openings_failed, "1 opening fails", "{0} openings fail"),
         "review the failing openings", f"openings {_js(openings_failed)}"),
        (plumbing["failed"] if plumbing else 0,
         _plural(plumbing and plumbing["failed"], "1 plumbing check fails", "{0} plumbing checks fail"),
         "review the plumbing", f"plumbing {_js(plumbing and plumbing['failed'])}"),
        (hvac["failed"] if hvac else 0,
         _plural(hvac and hvac["failed"], "1 HVAC check fails", "{0} HVAC checks fail"),
         "review the ducts' openings and the plant", f"HVAC {_js(hvac and hvac['failed'])}"),
        (electrical["failed"] if electrical else 0,
         _plural(electrical and electrical["failed"], "1 electrical check fails",
                 "{0} electrical checks fail"),
         "review the electrical services", f"electrical {_js(electrical and electrical['failed'])}"),
        (fire["failed"] if fire else 0,
         _plural(fire and fire["failed"], "1 fire check fails", "{0} fire checks fail"),
         "review the fire protection", f"fire {_js(fire and fire['failed'])}"),
    ]  # fmt: skip
    failing = [f for f in failing if f[0] > 0]
    if len(failing) == 1:
        return _status("mep", "failed", failing[0][1], failing[0][2])
    if len(failing) > 1:
        total = sum(f[0] for f in failing)
        names = ", ".join(f[3] for f in failing)
        return _status(
            "mep", "failed", f"{_js(total)} checks fail", f"{names}: review them in the MEP results"
        )
    floors_low = plumbing.get("floorsLow") if plumbing else None
    if _is_number(floors_low) and floors_low > 0:
        return _status(
            "mep",
            "failed",
            _plural(floors_low, "1 floor below the minimum pressure",
                    "{0} floors below the minimum pressure"),
            "raise the overhead tank or add a booster pump",
        )  # fmt: skip
    if plumbing_items and not plumbing:
        return _status(
            "mep", "inProgress", "plumbing not checked", "open the plumbing results or Run All"
        )
    if hvac_items and not hvac:
        return _status("mep", "inProgress", "HVAC not checked", "open the HVAC results or Run All")
    if electrical_items and not electrical:
        return _status(
            "mep", "inProgress", "electrical not checked", "open the electrical results or Run All"
        )
    if fire_items and not fire:
        return _status("mep", "inProgress", "fire not checked", "open the fire results or Run All")
    if summary["clashesOpen"] > 0:
        return _status(
            "mep", "inProgress", _plural(summary["clashesOpen"], "1 clash", "{0} clashes"),
            "coordinate the clashes",
        )  # fmt: skip
    partial = summary.get("openingsPartial") if _is_number(summary.get("openingsPartial")) else 0
    if partial > 0:
        return _status(
            "mep",
            "inProgress",
            _plural(partial, "1 opening not fully checked", "{0} openings not fully checked"),
            "run the analysis to check the openings' strength",
        )
    equipment = count["equipment"]
    if not equipment and (hvac or electrical or fire):
        return _status("mep", "done", "services checked")
    if not equipment and plumbing:
        return _status(
            "mep", "done",
            _plural(plumbing.get("tanks"), "plumbing checked, 1 tank", "plumbing checked, {0} tanks"),
        )  # fmt: skip
    return _status("mep", "done", _plural(equipment, "1 equipment", "{0} equipment"))


# ─────────────────────────────── the other parts ───────────────────────────────


def fem_status(inputs: StatusInputs) -> PartStatus:
    text = inputs.texts.get("fem")
    model = _parse(text) if text is not None else None
    if text is None:
        return _status("fem", "notStarted", "not derived", "derive the analysis model")
    if not model:
        return _status("fem", "error", INVALID, "derive the analysis model again")
    recorded = fem_recorded_sources(model)
    if not recorded:
        return _status("fem", "notStarted", "not derived", "derive the analysis model")
    soil_changed = "soil" in recorded and _changed(inputs.texts, "soil", recorded.get("soil"))
    recorded_changed = any(
        p in recorded and _changed(inputs.texts, p, recorded.get(p), fem_source_stamp)
        for p in FEM_RECORDED_SOURCES
    )
    mep_added = "mep" not in recorded and _mep_has_content(inputs)
    loads_added = "loads" not in recorded and loads_have_content(inputs.texts.get("loads"))
    if (
        soil_changed
        or recorded_changed
        or mep_added
        or loads_added
        or any(fem_source_changed(inputs.texts, p, recorded.get(p)) for p in FEM_SOURCES)
    ):
        return _status("fem", "stale", STALE, "derive the analysis model again")
    if inputs.femResultsTime is None:
        return _status("fem", "inProgress", "not analysed", "run the analysis")
    if inputs.femModelTime is not None and inputs.femModelTime > inputs.femResultsTime:
        return _status("fem", "stale", STALE, "run the analysis again")
    value = _parse(inputs.designSummaryText) if inputs.designSummaryText is not None else None
    summary = (
        value
        if value and all(_is_number(value.get(k)) for k in ("checked", "passed", "failed"))
        else None
    )
    if not summary or (
        inputs.designSummaryTime is not None and inputs.designSummaryTime < inputs.femResultsTime
    ):
        return _status("fem", "inProgress", "analysed", "run the design checks")
    if summary["failed"] > 0:
        return _status(
            "fem", "failed", f"{_js(summary['failed'])} fail", "review the failing members"
        )
    if summary["checked"] == 0:
        return _status(
            "fem", "inProgress", "nothing checked",
            "no member was design-checked: open the design results",
        )  # fmt: skip
    return _status("fem", "done", f"{_js(summary['passed'])} pass")


def _substructure_has_foundations(inputs: StatusInputs) -> bool:
    text = inputs.texts.get("substructure")
    document = _parse(text) if text is not None else None
    return (
        bool(document)
        and document.get("schema") == SUBSTRUCTURE_SCHEMA_ID
        and _length(document.get("foundations")) > 0
    )


def boq_status(inputs: StatusInputs) -> PartStatus:
    text = inputs.texts.get("boq")
    document = _parse(text) if text is not None else None
    if text is not None and not document:
        return _status("boq", "error", INVALID, "measure the quantities again")
    if not document or document.get("schema") != BOQ_SCHEMA_ID:
        return _status("boq", "notStarted", "not measured", "measure the quantities")

    def recorded(part: str) -> bool:
        return recorded_stamp(document, part) is not None

    if (
        any(_changed(inputs.texts, p, recorded_stamp(document, p)) for p in BOQ_SOURCES)
        or any(
            recorded(p) and _changed(inputs.texts, p, recorded_stamp(document, p), boq_source_stamp)
            for p in BOQ_RECORDED_SOURCES
        )
        or (not recorded("substructure") and _substructure_has_foundations(inputs))
        or (not recorded("mep") and _mep_has_content(inputs))
    ):
        return _status("boq", "stale", STALE, "measure the quantities again")
    return _status("boq", "done", "measured")


def _upstream_part(part: str, parts: tuple[Part, ...]) -> str | None:
    if part != "bim":
        return None
    ids = {p.id for p in parts}
    return next((p for p in ("floorPlan", "structure") if p in ids), None)


def bim_status(parts: tuple[Part, ...], inputs: StatusInputs) -> PartStatus:
    text = inputs.texts.get("bim")
    document = _parse(text) if text is not None else None
    if text is not None and not document:
        return _status("bim", "error", INVALID, "build the building model again")
    upstream = _upstream_part("bim", parts)
    recorded = recorded_stamp(document, upstream) if document and upstream else None
    if not document or not recorded:
        return _status("bim", "notStarted", "not built", "build the building model")
    if upstream and _changed(inputs.texts, upstream, recorded):
        return _status("bim", "stale", STALE, "build the building model again")
    return _status("bim", "done")


def soil_status(inputs: StatusInputs) -> PartStatus:
    text = inputs.texts.get("soil")
    document = _parse(text) if text is not None else None
    if text is None or (document and is_placeholder(document, "soil")):
        return _status("soil", "notStarted", NOT_STARTED, _start_hint("soil"))
    if not document or document.get("schema") != SOIL_SCHEMA_ID:
        return _status("soil", "error", INVALID, "fix the file")
    boreholes = document.get("boreholes") if isinstance(document.get("boreholes"), list) else []
    if not boreholes:
        return _status("soil", "notStarted", NOT_STARTED, "add the boreholes")
    count = _plural(len(boreholes), "1 borehole", "{0} boreholes")

    def logged(b: Any) -> bool:
        return isinstance(b, dict) and isinstance(b.get("layers"), list) and len(b["layers"]) > 0

    if not all(logged(b) for b in boreholes):
        return _status("soil", "inProgress", count, "enter the layers of every borehole")
    return _status("soil", "done", count)


def substructure_status(inputs: StatusInputs) -> PartStatus:
    text = inputs.texts.get("substructure")
    document = _parse(text) if text is not None else None
    if text is None or (document and is_placeholder(document, "substructure")):
        return _status("substructure", "notStarted", NOT_STARTED, _start_hint("substructure"))
    if not document or document.get("schema") != SUBSTRUCTURE_SCHEMA_ID:
        return _status("substructure", "error", INVALID, "fix the file")
    count = _length(document.get("foundations"))
    if not count:
        return _status("substructure", "notStarted", NOT_STARTED, _start_hint("substructure"))
    foundations = _plural(count, "1 foundation", "{0} foundations")
    value = (
        _parse(inputs.substructureSummaryText)
        if inputs.substructureSummaryText is not None
        else None
    )
    summary = (
        value
        if value and _is_number(value.get("failed")) and _is_number(value.get("passed"))
        else None
    )
    time = inputs.substructureSummaryTime
    source = summary.get("source") if summary and isinstance(summary.get("source"), dict) else None
    current = (
        summary is not None
        and time is not None
        and (
            _sources_unchanged(inputs.texts, source)
            if source is not None
            else inputs.substructureTime is None or time >= inputs.substructureTime
        )
        and (inputs.femResultsTime is None or time >= inputs.femResultsTime)
    )
    if not current or summary is None:
        return _status("substructure", "inProgress", foundations, "check the foundations")
    if summary.get("checked") == 0:
        return _status("substructure", "inProgress", foundations, "run the analysis to design them")
    if summary["failed"] > 0:
        return _status(
            "substructure",
            "failed",
            f"{_js(summary['failed'])} fail",
            "review the failing foundations",
        )
    unchecked = _positive(summary.get("skipped")) + _positive(summary.get("unsupported"))
    if unchecked > 0:
        return _status(
            "substructure", "inProgress", f"{_js(unchecked)} not checked",
            "check the foundations that were skipped",
        )  # fmt: skip
    return _status("substructure", "done", foundations)


def format_date(time_ms: float) -> str:
    """The report's date as the sidebar shows it ("19 Oct"; the app follows the system locale)."""
    moment = datetime.fromtimestamp(time_ms / 1000)
    return f"{moment.day} {moment:%b}"


def exports_status(inputs: StatusInputs, date=None) -> PartStatus:
    if inputs.reportTime is None:
        files = inputs.exportFiles or 0
        if files > 0:
            return _status(
                "exports", "inProgress", _plural(files, "1 file, no report", "{0} files, no report"),
                "build the design report",
            )  # fmt: skip
        return _status("exports", "notStarted", "no report", "build the design report")
    return _status("exports", "done", f"report {(date or format_date)(inputs.reportTime)}")


def document_status(part: str, inputs: StatusInputs) -> PartStatus:
    text = inputs.texts.get(part)
    if text is None:
        return _status(part, "notStarted", NOT_STARTED, _start_hint(part))
    document = _parse(text)
    if not document:
        return _status(part, "error", INVALID, "fix the file")
    if is_placeholder(document, part):
        return _status(part, "notStarted", NOT_STARTED, _start_hint(part))
    if part in ("settings", "materials"):
        if holds_defaults(document, part):
            return _status(part, "defaults", "defaults", "review the defaults")
        return _status(part, "done")
    if part == "objects":
        types = _length(document.get("objects"))
        if not types:
            return _status(part, "notStarted", NOT_STARTED, _start_hint(part))
        return _status(part, "done", _plural(types, "1 type", "{0} types"))
    if part in ("floorPlan", "structure"):
        members = model_member_count(document, part)
        if not members:
            return _status(part, "notStarted", NOT_STARTED, _start_hint(part))
        return _status(part, "done", _plural(members, "1 member", "{0} members"))
    return _status(part, "done")


def _canonical(value: Any) -> str:
    """``canonical``: JSON with sorted keys, so key order does not matter, and whole floats as
    integers, as JavaScript writes them (25.0 and 25 are the same number)."""

    def numbers(item: Any) -> Any:
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {k: numbers(v) for k, v in item.items()}
        if isinstance(item, list):
            return [numbers(v) for v in item]
        return item

    return json.dumps(numbers(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _defined(value: dict[str, Any]) -> dict[str, Any]:
    """Without the None values (JSON.stringify drops undefined ones)."""
    return {k: v for k, v in value.items() if v is not None}


def holds_defaults(document: dict[str, Any], part: str) -> bool:
    """``holdsDefaults``: whether a settings or materials file still holds what a new project
    starts with (the settings apart from the project name, the concrete and steel codes, the
    site's location and the building's use)."""
    from saengine.library.defaults import default_material_library
    from saengine.library.export import library_json
    from saengine.library.settings import default_project_settings

    if part == "materials":
        return _canonical(document) == _canonical(library_json(default_material_library()))
    defaults = library_json(default_project_settings())
    codes = _object(document.get("codes"))
    expected = {
        **defaults,
        "project": _defined({"name": _object(document.get("project")).get("name")}),
        "codes": _defined(
            {
                **_object(defaults.get("codes")),
                "concrete": codes.get("concrete"),
                "steel": codes.get("steel"),
            }
        ),
        "site": _defined(
            {
                **_object(defaults.get("site")),
                "location": _object(document.get("site")).get("location"),
            }
        ),
        "occupancy": _defined(
            {
                **_object(defaults.get("occupancy")),
                "use": _object(document.get("occupancy")).get("use"),
            }
        ),
    }
    return _canonical(document) == _canonical(expected)


def model_member_count(document: dict[str, Any], part: str) -> int:
    """``modelMemberCount``: the members a floor plan places or a structural model draws."""
    keys = (
        ("members", "areas")
        if part == "structure"
        else ("columns", "beams", "walls", "slabs", "footings")
    )
    return sum(_length(document.get(k)) for k in keys)


# ─────────────────────────────── part checks (PART_CHECKS_FILE) ───────────────────────────────


def _positive(value: Any) -> float:
    return value if _is_number(value) and value > 0 else 0


def part_checks_file(
    part: str, counts: dict[str, Any], sources: dict[str, str | None]
) -> dict[str, Any]:
    """``partChecksFile``: the checks file of ``part`` with ``counts`` (``problems`` and,
    optionally, ``checked``, ``total``, ``failed``, ``unsupported`` and ``items``) made from the
    saved files ``sources`` (part id to text, None for a missing file)."""
    result: dict[str, Any] = {
        "schema": PART_CHECKS_SCHEMA_ID,
        "part": part,
        "problems": counts.get("problems", 0),
    }
    for key in ("checked", "total", "failed", "unsupported"):
        if counts.get(key) is not None:
            result[key] = counts[key]
    items = list(counts.get("items") or [])[:PART_CHECK_ITEMS]
    if items:
        result["items"] = items
    result["source"] = {k: "" if t is None else source_stamp(t) for k, t in sources.items()}
    return result


def write_part_checks(
    project: Project, part: str, counts: dict[str, Any], sources: tuple[str, ...] | None = None
) -> Path:
    """``reportChecks``: write the checks file of ``part``, made from the saved files of
    ``sources`` (default: the part's own main file); an unchanged file is not rewritten."""
    by_id = {p.id: p for p in ALL_PARTS}
    texts: dict[str, str | None] = {}
    for id_ in sources or (part,):
        source = by_id.get(id_)
        texts[id_] = (
            read_text(project.root / source.folder / source.main_file)
            if source and source.main_file
            else None
        )
    target = project.root / by_id[part].folder / PART_CHECKS_FILE
    text = json.dumps(part_checks_file(part, counts, texts), indent="\t") + "\n"
    if read_text(target) != text:
        write_text(target, text)
    return target


def current_part_checks(
    part: str, text: str | None, texts: dict[str, str | None]
) -> dict[str, Any] | None:
    """``currentPartChecks``: the checks in ``text`` when they are of ``part`` and current."""
    value = _parse(text) if text is not None else None
    if (
        not value
        or value.get("schema") != PART_CHECKS_SCHEMA_ID
        or value.get("part") != part
        or not _is_number(value.get("problems"))
    ):
        return None
    source = value.get("source")
    if not isinstance(source, dict) or not _sources_unchanged(texts, source):
        return None
    return value


def _first_message(checks: dict[str, Any], default: str) -> str:
    items = checks.get("items")
    first = items[0] if isinstance(items, list) and items else None
    message = first.get("message") if isinstance(first, dict) else None
    return message if isinstance(message, str) else default


def apply_part_checks(own: PartStatus, checks: dict[str, Any] | None) -> PartStatus:
    """``applyPartChecks``: ``own`` with the part's current checks applied."""
    if not checks or own.state in ("notStarted", "error", "stale"):
        return own
    problems = _positive(checks.get("problems"))
    if problems > 0:
        return _status(
            own.part, "failed", _plural(problems, "1 problem", "{0} problems"),
            _first_message(checks, "fix the problems"),
        )  # fmt: skip
    failed = _positive(checks.get("failed"))
    if failed > 0:
        if own.state == "failed":
            return own
        return _status(
            own.part, "failed", f"{_js(failed)} fail",
            _first_message(checks, "review the failing checks"),
        )  # fmt: skip
    if own.state == "failed":
        return own
    unsupported = _positive(checks.get("unsupported"))
    if unsupported > 0:
        return _status(
            own.part, "inProgress", f"{_js(unsupported)} not supported",
            _first_message(checks, "these items cannot be checked yet"),
        )  # fmt: skip
    checked, total = checks.get("checked"), checks.get("total")
    if _is_number(checked) and _is_number(total) and checked < total:
        return _status(
            own.part, "inProgress", f"{_js(checked)} of {_js(total)} checked", "check the rest"
        )
    return own


def _exports_with_design(exports: PartStatus, fem: PartStatus, inputs: StatusInputs) -> PartStatus:
    """``exportsWithDesign``: the report is done only when the design checks pass (R4)."""
    if exports.state != "done" or inputs.reportTime is None:
        return exports
    newest = max(inputs.designSummaryTime or 0, inputs.femResultsTime or 0)
    if newest > inputs.reportTime:
        return _status("exports", "stale", STALE, "build the design report again")
    if fem.state == "failed":
        return _status(
            "exports", "failed", "report, design fails",
            "fix the failing members, then build the report again",
        )  # fmt: skip
    value = _parse(inputs.designSummaryText) if inputs.designSummaryText is not None else None
    if fem.state != "done" or not (value and value.get("checked")):
        return _status(
            "exports", "inProgress", exports.text,
            "run the design checks, then build the report again",
        )  # fmt: skip
    return exports


def compute_part_statuses(
    parts: tuple[Part, ...], inputs: StatusInputs, date: Callable[[float], str] | None = None
) -> list[PartStatus]:
    """``computePartStatuses``: the status of each of ``parts``, in order (``date`` formats the
    report's time, default :func:`format_date`)."""
    result = []
    for part in parts:
        match part.id:
            case "soil":
                result.append(soil_status(inputs))
            case "fem":
                result.append(fem_status(inputs))
            case "boq":
                result.append(boq_status(inputs))
            case "bim":
                result.append(bim_status(parts, inputs))
            case "exports":
                result.append(exports_status(inputs, date))
            case "substructure":
                result.append(substructure_status(inputs))
            case "mep":
                result.append(mep_status(inputs))
            case _:
                result.append(document_status(part.id, inputs))
    result = [
        apply_part_checks(
            s, current_part_checks(s.part, inputs.checksTexts.get(s.part), inputs.texts)
        )
        for s in result
    ]
    # The report says what the design checks found, so it is done only when they pass (R4).
    fem = next((s for s in result if s.part == "fem"), None)
    for index, status in enumerate(result):
        if status.part == "exports" and fem:
            result[index] = _exports_with_design(status, fem, inputs)
    return result


#: States of an optional part that still need the engineer (``OPTIONAL_NEEDS_WORK``).
OPTIONAL_NEEDS_WORK = frozenset({"failed", "error", "stale"})


def next_step(statuses: list[PartStatus]) -> tuple[int, PartStatus] | None:
    """``nextStep``: the first part, in order, that needs doing (optional parts only once they
    fail, are stale or cannot be read)."""
    for index, status in enumerate(statuses):
        if status.state != "done" and (
            status.part not in OPTIONAL_PARTS or status.state in OPTIONAL_NEEDS_WORK
        ):
            return index, status
    return None


# ─────────────────────────────── the inputs, from disk ───────────────────────────────


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime_ns / 1e6
    except OSError:
        return None


def export_kind(relative: str) -> str | None:
    """``exportKind``: report, ifc, dxf or csv for a file of ``11 Exports``."""
    path = relative.replace("\\", "/")
    lower = path.lower()
    if lower == REPORT_FILE:
        return "report"
    if lower.startswith(f"{EXPORT_IFC_FOLDER.lower()}/") and lower.endswith(".ifc"):
        return "ifc"
    if lower.startswith(f"{EXPORT_DXF_FOLDER.lower()}/") and lower.endswith(".dxf"):
        return "dxf"
    if "/" not in path and lower.endswith(".csv"):
        return "csv"
    return None


def count_exports(folder: Path) -> int:
    """``countExports``: the exports other than the report (top level, IFC, Floor Plan)."""
    names: list[str] = []
    for sub in ("", EXPORT_IFC_FOLDER, EXPORT_DXF_FOLDER):
        directory = folder / sub if sub else folder
        try:
            names += [
                f"{sub}/{c.name}" if sub else c.name for c in directory.iterdir() if c.is_file()
            ]
        except OSError:
            continue
    return sum(1 for n in names if export_kind(n) not in (None, "report"))


def read_inputs(project: Project) -> StatusInputs:
    """``readInputs``: what the rules read from the project's files."""
    root = project.root
    texts = {p.id: read_text(root / p.folder / p.main_file) for p in ALL_PARTS if p.main_file}
    texts["loads"] = read_text(root / LOADS_PART.folder / LOADS_PART.main_file)
    fem = root / "08 FEM"
    results = fem / FEM_RESULTS_FOLDER
    substructure = root / "09 Substructure"
    mep = root / "07 MEP"
    exports = root / "11 Exports"
    return StatusInputs(
        texts=texts,
        femModelTime=_mtime(fem / "model.osmodel"),
        femResultsTime=_mtime(results / FEM_RESULTS_MANIFEST),
        designSummaryText=read_text(results / DESIGN_SUMMARY_FILE),
        designSummaryTime=_mtime(results / DESIGN_SUMMARY_FILE),
        reportTime=_mtime(exports / REPORT_FILE),
        exportFiles=count_exports(exports),
        substructureSummaryText=read_text(substructure / SUBSTRUCTURE_SUMMARY_FILE),
        substructureSummaryTime=_mtime(substructure / SUBSTRUCTURE_SUMMARY_FILE),
        substructureTime=_mtime(substructure / "substructure.json"),
        mepSummaryText=read_text(mep / MEP_SUMMARY_FILE),
        mepSummaryTime=_mtime(mep / MEP_SUMMARY_FILE),
        checksTexts={p.id: read_text(root / p.folder / PART_CHECKS_FILE) for p in project.parts},
    )


def part_statuses(project: Project) -> list[PartStatus]:
    """The status of each part of ``project`` as the sidebar would show it now."""
    return compute_part_statuses(project.parts, read_inputs(project))

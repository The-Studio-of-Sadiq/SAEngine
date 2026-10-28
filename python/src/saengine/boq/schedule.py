"""The bill's reinforcement from the bars the drawings detail.

A quantity lives in one place: the bars of a member are those the drawings detail
(:func:`saengine.drawings.detailing.detailing_model`, BNBC 2020 Part 6 Chapter 8: laps at their
permitted places, hooks and bends, cut-off bars, the stirrups of each zone at its spacing) and
schedule (:func:`saengine.drawings.bbs.bar_schedule`: number × BS 8666 cutting length per bar
mark). The bill takes them for every element the drawings detail, so that the bill and the bar
bending schedule agree per bar size (:func:`take_from_schedule`). The estimating rules of
:mod:`saengine.boq.quantities` (full member lengths, 40 d per 12 m stock bar, links at their
centre line with two 10 d hooks, ``length / spacing + 1`` at one spacing, meshes as area /
spacing) remain only for the elements the drawings do not detail (inclined members, tanks,
members whose detailing failed, ...), and for the whole bill when the bars cannot be detailed
at all; the notes say which elements were measured which way (:func:`reconcile_notes`).

How it is called (``compute_boq``)::

    schedule, notes = schedule_of(texts, root)  # None and the reason when it cannot be made
    kept = take_from_schedule(document, schedule)
    document.notes += reconcile_notes(document, schedule, kept)

The schedules of the last few inputs are kept (:data:`CACHE_SIZE`): the bill is measured again
after every edit, and detailing the bars is the slow part of it.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any

#: Details of the bill that the schedule never replaces: designs of their own.
KEPT_DETAILS = ("tank design",)

#: Schedules kept for the last inputs (texts, detailing options, kept design and bar marks).
CACHE_SIZE = 4
_CACHE: OrderedDict[str, Any] = OrderedDict()

TAKEN_NOTE = (
    "Reinforcement of the elements the drawings detail: measured from their detailed bars, the "
    "bars of the bar bending schedule (11 Exports, Drawings): number × cutting length per bar "
    "mark, with the BNBC 2020 laps at their places, the hooks and bends, cut-off bars and the "
    "stirrups and ties of each zone at its spacing (BS 8666 cutting lengths rounded up to 25 mm), "
    "so that this bill and the schedule agree per bar size."
)

#: Element kinds of the detailing model as the notes name them (one, more).
KINDS = {"beam": ("beam line", "beam lines"), "column": ("column", "columns"),
         "slab": ("slab", "slabs"), "wall": ("wall", "walls"), "staircase": ("stair", "stairs"),
         "footing": ("footing", "footings"), "pileCap": ("pile cap", "pile caps"),
         "pile": ("pile", "piles")}  # fmt: skip


def _key(texts: dict[str, str | None], options: dict[str, Any], inputs: dict[str, Any]) -> str:
    text = json.dumps([texts, options, inputs], sort_keys=True, default=str)
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def schedule_of(
    texts: dict[str, str | None], project_root: str | None = None
) -> tuple[Any, list[str]]:
    """The bar bending schedule of the project files' texts ("bim", "objects", "materials",
    "settings", "substructure"), with the drawing settings' detailing options: ``(schedule,
    [])``, or ``(None, [why])`` when the bars cannot be detailed. The schedule may be the one
    kept for the same inputs: it is not to be changed.

    ``project_root``: the bars are detailed as the drawings detail them
    (:func:`saengine.pipeline.drawings.kept_detailing_inputs`): with the bar marks of the last
    drawing set and the kept design checks and required steel of the analysis run, so the
    bill's marks are those of the sheets and ``bbs.csv``."""
    from saengine.drawings import bbs
    from saengine.drawings.detailing import detailing_model

    options: dict[str, Any] = {}
    if texts.get("settings"):
        from saengine.library.settings import ProjectSettings

        try:
            drawings = ProjectSettings.model_validate_json(texts["settings"] or "").drawings
            options = {"method": drawings.developmentLength, "curtail": drawings.curtail}
        except ValueError:
            options = {}
    inputs: dict[str, Any] = {}
    if project_root:
        from saengine.pipeline.drawings import kept_detailing_inputs

        try:
            inputs = kept_detailing_inputs(project_root)
        except Exception:  # noqa: BLE001 - detailed from the files alone
            inputs = {}
    key = _key(dict(texts), options, inputs)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key], []
    try:
        model = detailing_model(texts=dict(texts), options=options, **inputs)
        schedule = bbs.bar_schedule(model)
    except Exception as error:  # noqa: BLE001 - the bill stands on its estimating rules
        why = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
        note = (
            f"Reinforcement: the bars could not be detailed ({why}), so all of it is measured "
            "by the estimating rules above."
        )
        return None, [note]
    _CACHE[key] = schedule
    while len(_CACHE) > CACHE_SIZE:
        _CACHE.popitem(last=False)
    return schedule, []


def _shares(row: Any, measured: dict[str, float]) -> list[tuple[str, float]]:
    """The BIM elements a schedule row's mass is booked under, with their share: a beam line
    "B1+B2" over its beams in proportion to what the bill measured of them (equal shares when
    it measured none), a pile under its cap, anything else under its own id."""
    from saengine.drawings.bbs import _boq_element

    members = list(row.bim) if len(row.bim) > 1 else [row.bim[0] if row.bim else _boq_element(row)]
    if len(members) == 1:
        return [(members[0], 1.0)]
    weights = [measured.get(m, 0.0) for m in members]
    total = sum(weights)
    if total <= 0:
        return [(m, 1 / len(members)) for m in members]
    return [(m, w / total) for m, w in zip(members, weights, strict=True)]


def _covered(schedule: Any) -> set[str]:
    from saengine.drawings.bbs import _boq_element

    covered: set[str] = set()
    for row in schedule.rows:
        covered.add(row.element)
        covered.add(_boq_element(row))
        covered.update(row.bim)
    return covered


def take_from_schedule(document: Any, schedule: Any) -> list[str]:
    """Replaces the bill's reinforcement of every element the schedule details by the
    schedule's bars (``document``: a ``BillOfQuantities``, changed in place). Returns the
    elements still measured by the bill's own rules."""
    from saengine.boq.quantities import _Bill

    covered = _covered(schedule)
    bill = _Bill()
    measured: dict[tuple[str, float], float] = {}
    kept: set[str] = set()
    first = None
    others = []
    for index, item in enumerate(document.items):
        if item.group != "reinforcement":
            others.append(item)
            continue
        first = index if first is None else first
        dia = float(item.diameter or 0)
        for entry in item.breakdown:
            measured[(entry.element, dia)] = (
                measured.get((entry.element, dia), 0.0) + entry.quantity
            )
            if entry.element in covered and (entry.detail or "") not in KEPT_DETAILS:
                continue
            kept.add(entry.element)
            bill.add(
                "reinforcement",
                (item.material, dia),
                item.description,
                item.unit,
                entry.element,
                entry.quantity,
                story=entry.story,
                detail=entry.detail,
                material=item.material,
                diameter=dia,
            )
    for row in schedule.rows:
        by_element = {e: q for (e, d), q in measured.items() if d == row.dia}
        for element, share in _shares(row, by_element):
            bill.add(
                "reinforcement",
                (row.material, row.dia),
                f"Reinforcement {row.material}, {row.dia:g} mm bars",
                "kg",
                element,
                row.mass * share,
                story=row.story,
                detail=f"bar mark {row.mark} (bar bending schedule)",
                material=row.material,
                diameter=row.dia,
            )
    items = bill.items()
    position = first if first is not None else len(others)
    document.items = [*others[:position], *items, *others[position:]]
    return sorted(kept - covered)


def _detailed(schedule: Any) -> list[tuple[str, str]]:
    """(kind, element) of every element the schedule details, in its order."""
    seen: dict[str, str] = {}
    for row in schedule.rows:
        seen.setdefault(row.element, row.kind)
    return [(kind, element) for element, kind in seen.items()]


def reconcile_notes(document: Any, schedule: Any, kept: list[str] | None = None) -> list[str]:
    """The notes of the bill on the schedule. ``kept``: the bill took the schedule's bars
    (:func:`take_from_schedule`) and these elements kept the estimating rules: the notes say
    which elements were measured which way. None: the bill kept its own measure; the notes set
    it against the schedule per bar size."""
    from saengine.drawings.bbs import reconcile

    if kept is not None:
        detailed = _detailed(schedule)
        counts: dict[str, int] = {}
        for kind, _ in detailed:
            counts[kind] = counts.get(kind, 0) + 1
        parts = ", ".join(
            f"{n} {KINDS.get(k, (k, k))[0 if n == 1 else 1]}" for k, n in counts.items()
        )
        lines = [
            TAKEN_NOTE,
            f"Measured from the detailed bars: {parts} ({', '.join(e for _, e in detailed)}).",
        ]
        if kept:
            lines.append(
                "Measured by the estimating rules above (not detailed in the drawings): "
                f"{', '.join(kept)}."
            )
        return lines
    rec = reconcile(schedule, document)
    if not rec.rows:
        return []
    parts_dia = []
    for r in rec.rows:
        pct = "" if r.percent is None else f", {r.percent:+.1f} %"
        parts_dia.append(
            f"Ø{r.dia:g} {r.bbs:.1f} kg against {r.boq:.1f} kg ({r.difference:+.1f} kg{pct})"
        )
    only = sorted({e or "?" for r in rec.rows for e in r.only_boq})
    text = (
        "Reinforcement against the bar bending schedule of the drawings (BBS against this bill, "
        f"per bar size): {'; '.join(parts_dia)}; in total {rec.bbs:.1f} kg against "
        f"{rec.boq:.1f} kg. The schedule cuts the detailed bars (BNBC 2020 laps and hooks, "
        "cut-off bars, BS 8666 cutting lengths); this bill measures by the estimating rules above."
    )
    if only:
        text += f" Not detailed in the drawings: {', '.join(only)}."
    return [text]

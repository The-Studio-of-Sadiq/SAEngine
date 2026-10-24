"""The bill's reinforcement against the bar bending schedule of the drawings.

10 BOQ measures its bars by its own rules (:mod:`saengine.boq.quantities`: full member lengths,
40 d per 12 m stock bar, links at their centre line with two 10 d hooks, meshes as area /
spacing). The drawings detail and schedule the bars (:func:`saengine.drawings.detailing.
detailing_model`, :func:`saengine.drawings.bbs.bar_schedule`: BNBC laps and hooks, cut-off
bars, BS 8666 cutting lengths). This module brings the two together in the bill:

- by default the bill keeps its own measure, and its notes reconcile it with the schedule per
  bar size (:func:`reconcile_notes`);
- with Project Settings' ``drawings.boqReinforcement`` set to ``"bbs"``, the reinforcement of
  every element the drawings detail is the schedule's (:func:`take_from_schedule`); elements the
  drawings do not detail (inclined members, tanks, ...) keep the bill's measure.

How it is called (``compute_boq``)::

    schedule, notes = schedule_of(texts, root)  # None and the reason when it cannot be made
    take_from_schedule(document, schedule)      # only with the "bbs" setting
    document.notes += reconcile_notes(document, schedule, taken)
"""

from __future__ import annotations

from typing import Any

#: Details of the bill that the schedule never replaces: designs of their own.
KEPT_DETAILS = ("tank design",)

TAKEN_NOTE = (
    "Reinforcement: taken from the bar bending schedule of the drawings (detailed bars, BNBC 2020 "
    "laps and hooks, BS 8666 cutting lengths rounded up to 25 mm; Project Settings, Drawings, BOQ "
    "reinforcement) for every element the drawings detail."
)


def schedule_of(
    texts: dict[str, str | None], project_root: str | None = None
) -> tuple[Any, list[str]]:
    """The bar bending schedule of the project files' texts ("bim", "objects", "materials",
    "settings", "substructure"), with the drawing settings' detailing options: ``(schedule,
    [])``, or ``(None, [why])`` when the bars cannot be detailed.

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
    try:
        model = detailing_model(texts=dict(texts), options=options, **inputs)
        return bbs.bar_schedule(model), []
    except Exception as error:  # noqa: BLE001 - the bill stands without the schedule
        why = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
        note = (
            f"Reinforcement: the bar bending schedule could not be made ({why}), so it is not "
            "reconciled with it."
        )
        return None, [note]


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


def reconcile_notes(document: Any, schedule: Any, kept: list[str] | None = None) -> list[str]:
    """The notes of the bill on the schedule: per bar size, the schedule's mass against the
    bill's (``kept``: the bill took the schedule's bars; the elements it still measured)."""
    from saengine.drawings.bbs import reconcile

    if kept is not None:
        lines = [TAKEN_NOTE]
        if kept:
            lines.append(
                "Reinforcement measured by the rules above, not detailed in the drawings: "
                f"{', '.join(kept)}."
            )
        return lines
    rec = reconcile(schedule, document)
    if not rec.rows:
        return []
    parts = []
    for r in rec.rows:
        pct = "" if r.percent is None else f", {r.percent:+.1f} %"
        parts.append(
            f"Ø{r.dia:g} {r.bbs:.1f} kg against {r.boq:.1f} kg ({r.difference:+.1f} kg{pct})"
        )
    only = sorted({e or "?" for r in rec.rows for e in r.only_boq})
    text = (
        "Reinforcement against the bar bending schedule of the drawings (BBS against this bill, "
        f"per bar size): {'; '.join(parts)}; in total {rec.bbs:.1f} kg against {rec.boq:.1f} kg. "
        "The schedule cuts the detailed bars (BNBC 2020 laps and hooks, cut-off bars, BS 8666 "
        "cutting lengths); this bill measures by the rules above. Set Project Settings, Drawings, "
        "BOQ reinforcement to take the schedule's bars instead."
    )
    if only:
        text += f" Not detailed in the drawings: {', '.join(only)}."
    return [text]

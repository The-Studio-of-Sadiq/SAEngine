"""Multi-discipline coordination: clash tests between element sets, and the issue workflow.

The sets are SAEngine's own structure and architecture (one IFC exported from the building model
and the floor plan, see :func:`saengine.mep.clash.structural_ifc`; the architecture's elements
carry ``SAEngine_Architecture``), the MEP IFC models of 07 MEP by discipline, and the other IFC
models of the coordination (an architect's or another consultant's file). A clash test
(:class:`saengine.library.mep.ClashTest`) compares the union of its sets ``a`` with the union of
its sets ``b`` in one IfcOpenShell geometry tree, the same engine as the MEP clash check
(:mod:`saengine.mep.clash`): hard clashes by ``clash_intersection_many``, clearance clashes by
``clash_clearance_many``.

A service through a beam, slab or wall where 07 MEP has a big enough sleeve or opening, or in a
shaft, is *coordinated* exactly as in the MEP clash check, and raises no issue.

Each clash becomes an issue keyed ``test:globalIdA:globalIdB`` (the pair sorted when both sides
come from the same sets). Running the tests again keeps every issue's status, assignee and
comments; an issue whose clash is found again after it was resolved or closed is reopened
(active); an open issue whose clash is no longer found is resolved, with a comment saying so.
The status workflow follows BCF's topic statuses: new -> active -> reviewed -> approved
(accepted as it is) or resolved -> closed.

Units: mm (IfcOpenShell's geometry is in metres).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import numpy as np

from saengine.library.mep import (
    ClashTest,
    Coordination,
    Issue,
    IssueComment,
    MepModel,
)
from saengine.mep import clash
from saengine.mep.ifc_import import element_class, mep_elements

ARCHITECTURE_PSET = "SAEngine_Architecture"
MEP_SETS = ("mechanical", "plumbing", "fire", "electrical")
OPEN_STATUSES = ("new", "active", "reviewed")
CLOSED_STATUSES = ("resolved", "closed")
#: Classes that are never physical clash candidates.
NOT_PHYSICAL = (
    "IfcOpeningElement",
    "IfcVirtualElement",
    "IfcFeatureElement",
    "IfcSpatialElement",
    "IfcAnnotation",
    "IfcGrid",
)
#: More pairs than this from one test are cut off (the rest are counted in a note).
MAX_PAIRS = 2000


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def default_tests() -> list[ClashTest]:
    """The tests a new coordination starts with."""
    services: list[Any] = list(MEP_SETS)
    return [
        ClashTest(id="T1", name="Structure vs services", a=["structure"], b=services),
        ClashTest(id="T2", name="Architecture vs services", a=["architecture"], b=services),
        ClashTest(
            id="T3", name="Services vs services", a=services, b=services, ignoreSameModel=True
        ),
        ClashTest(id="T4", name="Structure vs architecture", a=["structure"], b=["architecture"]),
        ClashTest(id="T5", name="Other models vs structure", a=["external"], b=["structure"]),
    ]


def coordination_of(mep: MepModel) -> Coordination:
    """The coordination of ``mep``, with the default tests when it has none yet."""
    if mep.coordination is not None:
        return mep.coordination
    return Coordination(tests=default_tests())


# ─────────────────────────────────────── element sets ───────────────────────────────────────


@dataclass
class ElementSets:
    """The elements of each set, which file and set each GlobalId comes from, and the SAEngine
    building model it was exported from (for the sleeve check)."""

    files: list[tuple[str, ifcopenshell.file, list[Any]]] = field(default_factory=list)
    sets: dict[str, list[Any]] = field(default_factory=dict)
    origin: dict[str, tuple[str, str]] = field(default_factory=dict)  # guid -> (set, file)
    building: Any = None
    objects: Any = None
    notes: list[str] = field(default_factory=list)


def _physical(model: ifcopenshell.file) -> list[Any]:
    return [
        e
        for e in model.by_type("IfcElement")
        if not any(e.is_a(c) for c in NOT_PHYSICAL) and getattr(e, "Representation", None)
    ]


def element_sets(project_root: str | Path, mep: MepModel, wanted: set[str]) -> ElementSets:
    """The element sets the tests need (``wanted``): only the files those sets come from are
    exported or opened."""
    root = Path(project_root)
    result = ElementSets()

    def add(name: str, label: str, model: ifcopenshell.file, elements: list[Any]) -> None:
        result.sets.setdefault(name, [])
        for e in elements:
            if e.GlobalId in result.origin:
                continue
            result.origin[e.GlobalId] = (name, label)
            result.sets[name].append(e)

    if wanted & {"structure", "architecture"}:
        try:
            own, building, objects, _ = clash.structural_ifc(root, architecture=True)
        except ValueError as error:
            result.notes.append(f"the building model could not be exported: {error}")
        else:
            result.building, result.objects = building, objects
            arch = [
                e
                for e in _physical(own)
                if ifcopenshell.util.element.get_pset(e, ARCHITECTURE_PSET) is not None
            ]
            arch_ids = {e.GlobalId for e in arch}
            structure = [
                e
                for c in clash.STRUCTURAL_CLASSES
                for e in own.by_type(c)
                if e.GlobalId not in arch_ids
            ]
            label = "SAEngine model"
            used: list[Any] = []
            if "structure" in wanted:
                add("structure", label, own, structure)
                used += structure
            if "architecture" in wanted:
                add("architecture", label, own, arch)
                used += arch
                if not arch:
                    result.notes.append("the floor plan has no architecture to test")
            result.files.append((label, own, used))
    if wanted & set(MEP_SETS):
        models, notes = clash.open_models(root, mep)
        result.notes += notes
        for path, discipline, model in models:
            if discipline not in wanted:
                continue
            elements = mep_elements(model)
            add(discipline, path, model, elements)
            result.files.append((path, model, elements))
    if "external" in wanted:
        coordination = mep.coordination or Coordination()
        for entry in coordination.models:
            full = Path(entry.path) if Path(entry.path).is_absolute() else root / entry.path
            try:
                model = ifcopenshell.open(str(full))
            except Exception as error:  # noqa: BLE001 - IfcOpenShell raises several kinds
                result.notes.append(f"{entry.path}: could not be read ({error})")
                continue
            elements = _physical(model)
            add("external", entry.path, model, elements)
            result.files.append((entry.path, model, elements))
    return result


# ─────────────────────────────────────── clash tests ───────────────────────────────────────


def _label(element: Any) -> str:
    name = element.Name or ""
    tag = getattr(element, "Tag", None) or ""
    kind = element_class(element).replace("Ifc", "")
    return " ".join(x for x in (kind, tag or name) if x)


def _story(stories: list[Any], z: float) -> str | None:
    if not stories:
        return None
    return next((s.id for s in reversed(stories) if s.elevation <= z + 1.0), stories[0].id)


def _coordinated(
    service: Any, product: Any, sets: ElementSets, mep: MepModel, levels: dict[str, float]
) -> str | None:
    """How a service crossing a beam, slab or wall is coordinated (``"through OP-1"``, ``"in
    shaft S1"``), as in :func:`saengine.mep.clash.find_clashes`, or None."""
    if sets.building is None:
        return None
    sid = product.Tag or product.Name or product.GlobalId
    element = next((e for e in sets.building.elements if e.id == sid), None)
    if element is None:
        return None
    types = {o.id: o for o in sets.objects.objects} if sets.objects is not None else {}
    host = clash.host_of(element, types)
    if host is None:
        return None
    shape = clash.service_shape(service, element_class(service))
    cross = clash.crossing(host, shape, 0.0) if shape is not None else None
    if cross is None:
        return None
    shaft = clash._in_shaft(host, cross, mep, levels)
    if shaft is not None:
        return f"in shaft {shaft.id}"
    opening, big = clash._matching_opening(host, cross, mep.openings)
    if opening is not None and big:
        return f"through {opening.id}"
    return None


def run_test(
    test: ClashTest, sets: ElementSets, tree: Any, mep: MepModel, stories: list[Any]
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """The clashes of one test: ``[{"key", "test", "elements": [a, b], "labels", "sets",
    "files", "kind", "type", "depth" (mm), "point" [mm], "story"}]``, how many were
    coordinated by sleeves, openings or shafts, and notes."""
    notes: list[str] = []
    a = [e for name in dict.fromkeys(test.a) for e in sets.sets.get(name, [])]
    b = [e for name in dict.fromkeys(test.b) for e in sets.sets.get(name, [])]
    if not a or not b:
        missing = [n for n in (*test.a, *test.b) if not sets.sets.get(n)]
        notes.append(f"{test.id}: nothing to test ({', '.join(dict.fromkeys(missing))} empty)")
        return [], 0, notes
    a_ids = {e.GlobalId for e in a}
    b_ids = {e.GlobalId for e in b}
    symmetric = bool(set(test.a) & set(test.b))
    if test.kind == "clearance" and test.clearance > 0:
        raw = tree.clash_clearance_many(a, b, test.clearance / 1e3, False)
    else:
        raw = tree.clash_intersection_many(a, b, test.tolerance / 1e3, True)
    levels = {s.id: s.elevation for s in stories}
    pairs: dict[str, dict[str, Any]] = {}
    coordinated = 0
    for c in raw:
        first, second = c.a, c.b
        if first.GlobalId == second.GlobalId:
            continue
        if first.GlobalId not in a_ids or second.GlobalId not in b_ids:
            first, second = second, first
            if first.GlobalId not in a_ids or second.GlobalId not in b_ids:
                continue
        if (
            symmetric
            and first.GlobalId > second.GlobalId
            and second.GlobalId in a_ids
            and first.GlobalId in b_ids
        ):
            first, second = second, first
        if (
            test.ignoreSameModel
            and sets.origin[first.GlobalId][1] == sets.origin[second.GlobalId][1]
        ):
            continue
        key = f"{test.id}:{first.GlobalId}:{second.GlobalId}"
        if key in pairs:
            continue
        set_a = sets.origin[first.GlobalId][0]
        set_b = sets.origin[second.GlobalId][0]
        clash_type = clash.CLASH_TYPES.get(int(c.clash_type), str(c.clash_type))
        if clash_type != "clearance":
            service, product = None, None
            if set_a == "structure" and set_b in MEP_SETS:
                service, product = second, first
            elif set_b == "structure" and set_a in MEP_SETS:
                service, product = first, second
            if service is not None and _coordinated(service, product, sets, mep, levels):
                coordinated += 1
                continue
        point = (np.array(c.p1) + np.array(c.p2)) / 2 * 1e3
        pairs[key] = {
            "key": key,
            "test": test.id,
            "elements": [first.GlobalId, second.GlobalId],
            "labels": [_label(first), _label(second)],
            "sets": [set_a, set_b],
            "files": [sets.origin[first.GlobalId][1], sets.origin[second.GlobalId][1]],
            "kind": "clearance" if clash_type == "clearance" else "hard",
            "type": clash_type,
            "depth": round(float(c.distance) * 1e3, 1),
            "point": [round(float(v), 1) for v in point],
            "story": _story(stories, float(point[2])),
        }
        if len(pairs) >= MAX_PAIRS:
            notes.append(f"{test.id}: stopped at {MAX_PAIRS} clashes; narrow the test")
            break
    return list(pairs.values()), coordinated, notes


def run_tests(
    project_root: str | Path, mep: MepModel, test_ids: list[str] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Runs the enabled tests (or those of ``test_ids``) of the coordination of ``mep``.
    Returns (clashes, per test ``{"test", "name", "found", "coordinated"}``, notes)."""
    coordination = coordination_of(mep)
    tests = [
        t for t in coordination.tests if (t.id in test_ids if test_ids is not None else t.enabled)
    ]
    if not tests:
        return [], [], ["no clash tests to run"]
    wanted = {name for t in tests for name in (*t.a, *t.b)}
    sets = element_sets(project_root, mep, wanted)
    notes = list(sets.notes)
    tree = ifcopenshell.geom.tree(backend=clash.TREE_BACKEND)
    settings = ifcopenshell.geom.settings()
    for _, model, elements in sets.files:
        if elements:
            tree.add_iterator(ifcopenshell.geom.iterator(settings, model, 1, include=elements))
    stories = sorted(sets.building.stories, key=lambda s: s.elevation) if sets.building else []
    clashes: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for test in tests:
        found, coordinated, more = run_test(test, sets, tree, mep, stories)
        notes += more
        clashes += found
        summary.append(
            {"test": test.id, "name": test.name, "found": len(found), "coordinated": coordinated}
        )
    return clashes, summary, notes


# ─────────────────────────────────────── issue workflow ───────────────────────────────────────


def _next_id(prefix: str, taken: set[str]) -> str:
    n = 1
    while f"{prefix}{n}" in taken:
        n += 1
    taken.add(f"{prefix}{n}")
    return f"{prefix}{n}"


def merge_found(
    coordination: Coordination,
    found: list[dict[str, Any]],
    scope: set[str],
    source: str = "clash",
    stamp: str | None = None,
) -> tuple[Coordination, dict[str, int]]:
    """``coordination`` with the issues of ``found`` merged in: the clashes of the tests (or
    IDS failures) of ``scope`` (``found`` items: ``{"key", "test", "title", "elements",
    "point", "story", "description"}``; a clash's title is made from its labels).

    An existing issue (same key) keeps its status, assignee and comments and takes the new
    geometry; a resolved or closed one found again is reopened (active). An open issue of
    ``scope`` that is no longer found is resolved. Returns the new coordination and counts
    ``{"new", "reopened", "resolved", "open"}``."""
    stamp = stamp or now()
    author = coordination.author or "SAEngine"
    issues = [i.model_copy(deep=True) for i in coordination.issues]
    by_key = {i.key: i for i in issues if i.key and i.source == source}
    taken = {i.id for i in issues}
    seen: set[str] = set()
    counts = {"new": 0, "reopened": 0, "resolved": 0, "open": 0}
    prefix = "C" if source == "clash" else "Q"
    for item in found:
        key = item["key"]
        seen.add(key)
        title = item.get("title") or " vs ".join(item.get("labels") or []) or key
        issue = by_key.get(key)
        if issue is None:
            issue = Issue(
                id=_next_id(prefix, taken),
                guid=str(uuid.uuid4()),
                title=title[:200],
                source=source,  # type: ignore[arg-type]
                key=key,
                test=item.get("test"),
                status="new",
                description=item.get("description", ""),
                elements=list(item.get("elements", [])),
                point=item.get("point"),
                story=item.get("story"),
                created=stamp,
                modified=stamp,
            )
            issues.append(issue)
            by_key[key] = issue
            counts["new"] += 1
            continue
        issue.elements = list(item.get("elements", issue.elements))
        issue.point = item.get("point", issue.point)
        issue.story = item.get("story", issue.story)
        if item.get("description"):
            issue.description = item["description"]
        if issue.status in CLOSED_STATUSES:
            issue.status = "active"
            issue.modified = stamp
            issue.comments.append(
                IssueComment(
                    guid=str(uuid.uuid4()),
                    date=stamp,
                    author=author,
                    text="Found again: reopened.",
                )
            )
            counts["reopened"] += 1
    for issue in issues:
        if issue.source != source or issue.key in seen:
            continue
        if issue.test not in scope or issue.status not in OPEN_STATUSES:
            continue
        issue.status = "resolved"
        issue.modified = stamp
        issue.comments.append(
            IssueComment(
                guid=str(uuid.uuid4()),
                date=stamp,
                author=author,
                text="No longer found: resolved.",
            )
        )
        counts["resolved"] += 1
    counts["open"] = sum(1 for i in issues if i.status in OPEN_STATUSES)
    return coordination.model_copy(update={"issues": issues}), counts


def coordinate(
    project_root: str | Path, mep_text: str | None = None, test_ids: list[str] | None = None
) -> dict[str, Any]:
    """Runs the clash tests of the project's MEP file (``mep_text``: the editor's text) and
    merges their clashes into its issues: ``{"coordination" (the new ``coordination`` of
    mep.json), "tests": [{"test", "name", "found", "coordinated"}], "counts", "clashes",
    "notes"}``. Raises ``ValueError`` for an invalid file."""
    from saengine.library.mep import MEP_FILE, parse

    root = Path(project_root)
    if mep_text is None:
        try:
            mep_text = (root / MEP_FILE).read_text(encoding="utf-8")
        except OSError:
            mep_text = None
    mep = parse(mep_text)
    coordination = coordination_of(mep)
    mep = mep.model_copy(update={"coordination": coordination})
    clashes, summary, notes = run_tests(root, mep, test_ids)
    scope = {s["test"] for s in summary}
    merged, counts = merge_found(coordination, clashes, scope)
    return {
        "coordination": merged.model_dump(mode="json", by_alias=True, exclude_none=True),
        "tests": summary,
        "counts": counts,
        "clashes": clashes,
        "notes": notes,
    }

"""Query actions: what the project holds (as the batch has it), its results and checks, and the
catalogue itself. They read only."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue import _plan as P
from saengine.actions.catalogue._util import Params
from saengine.actions.errors import refuse
from saengine.actions.paths import (
    FLOOR_PLAN,
    LOADS,
    MATERIALS,
    OBJECTS,
    SETTINGS,
    SOIL,
    SUBSTRUCTURE,
)
from saengine.actions.registry import UnknownAction, action, get, list_actions
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView

#: The order a whole project is built in (the assistant's playbook and docs/actions.md).
PLAYBOOK = [
    "project.create (name, codePack, occupancy; or building: a whole building at once)",
    (
        "settings.site, settings.use (site, use, loads); soil.borehole.add, soil.layer.add, "
        "soil.spt.add or soil.allowable_bearing.set"
    ),
    "grid.set, storeys.set (typical: true for typical floors)",
    (
        "material.concrete.add (makeDefault) / material.steel.add for the project's materials; "
        "type.column.add, type.beam.add, type.slab.add (sizes)"
    ),
    'columns.place, beams.place, slabs.place (points/between/panels "all"), walls.place',
    "load.area.set, load.wall.add, load.line.add, load.point.add",
    "run.step analyse, then foundations.generate (or footing.set)",
    "run.all, design.reinforcement.apply, run.all again (checks with the bars)",
    "results.summary, checks.list; export.report, export.drawings, export.boq",
]


class Empty(Params):
    pass


def _counts(plan: dict[str, Any]) -> dict[str, int]:
    return {g: len(P.members(plan, g)) for g in P.GROUPS if P.members(plan, g)}


@action(
    "project.summary",
    summary="What the project holds: code, site, use, grid, storeys, member counts, types, "
    "materials, area loads, foundations, soil.",
    params=Empty,
    parts=("settings", "materials", "objects", "floorPlan", "loads", "substructure", "soil"),
    kind="query",
    example={},
)
def project_summary(view: ProjectView, p: Empty) -> ActionResult:
    settings = view.read(SETTINGS, None)
    if settings is None:
        return ActionResult(
            message="There is no project here yet (project.create).", data={"exists": False}
        )
    plan = view.read(FLOOR_PLAN, {})
    objects = view.read(OBJECTS, {}).get("objects") or []
    materials = view.read(MATERIALS, {})
    loads = view.read(LOADS, {}) or {}
    sub = view.read(SUBSTRUCTURE, {}) or {}
    soil = view.read(SOIL, {}) or {}
    site = settings.get("site") or {}
    per_storey = {
        s: {
            g: sum(1 for m in P.members(plan, g) if P.on_story(plan, g, m, s))
            for g in P.PLAN_GROUPS
        }
        for s in P.story_ids(plan)
    }
    data = {
        "exists": True,
        "name": (settings.get("project") or {}).get("name"),
        "codePack": settings.get("codePack"),
        "site": {
            k: site.get(k)
            for k in ("location", "siteClass", "siteClassSource", "zoneCoefficient", "windSpeed")
        },
        "occupancy": settings.get("occupancy"),
        "allowableBearing": (settings.get("foundation") or {}).get("allowableBearing"),
        "grid": {
            a: [{"label": g["label"], "position": g["position"]} for g in P.grid_lines(plan, a)]
            for a in ("x", "y")
        },
        "storeys": [
            {k: s.get(k) for k in ("id", "name", "elevation", "similarTo") if k in s}
            for s in P.stories(plan)
        ],
        "members": _counts(plan),
        "membersPerStorey": {s: {g: n for g, n in c.items() if n} for s, c in per_storey.items()},
        "types": [
            {
                "id": o.get("id"),
                "kind": o.get("kind"),
                "material": o.get("material"),
                "reinforced": "reinforcement" in o,
            }
            for o in objects
        ],
        "materials": [
            {"id": m.get("id"), "category": m.get("category")}
            for m in materials.get("materials") or []
        ],
        "materialDefaults": materials.get("defaults"),
        "areaLoads": settings.get("areaLoads"),
        "floorLoad": settings.get("floorLoad"),
        "roofLoad": settings.get("roofLoad"),
        "memberLoads": len(loads.get("loads") or []) if isinstance(loads, dict) else 0,
        "foundations": [f.get("id") for f in sub.get("foundations") or []]
        if isinstance(sub, dict)
        else [],
        "boreholes": [b.get("id") for b in soil.get("boreholes") or []]
        if isinstance(soil, dict)
        else [],
    }
    counts = ", ".join(f"{n} {g}" for g, n in data["members"].items()) or "no members"
    return ActionResult(
        message=f"{data['name']} ({data['codePack']}): {len(data['storeys'])} levels, "
        f"{len(data['grid']['x'])}x{len(data['grid']['y'])} grid lines, {counts}.",
        data=data,
    )


class MembersParams(Params):
    group: Literal["columns", "beams", "walls", "slabs", "footings"] | None = None
    storey: str | None = Field(default=None, description="Only the members on this storey.")
    type: str | None = Field(default=None, description="Only members of this object type.")
    limit: int = Field(default=500, ge=1, le=10_000)


@action(
    "members.list",
    summary="The floor plan's members (id, group, type, storey, where), filtered by group, "
    "storey or type.",
    params=MembersParams,
    parts=("floorPlan",),
    kind="query",
    example={"group": "columns", "storey": "L1"},
)
def members_list(view: ProjectView, p: MembersParams) -> ActionResult:
    plan = view.read(FLOOR_PLAN)
    if p.storey is not None:
        P.check_story(plan, p.storey, "storey")
    out = []
    for group in [p.group] if p.group else list(P.GROUPS):
        for m in P.members(plan, group):
            if p.type and m.get("type") != p.type:
                continue
            if p.storey and not P.on_story(plan, group, m, p.storey):
                continue
            row: dict[str, Any] = {"id": m.get("id"), "group": group, "type": m.get("type")}
            for k in ("story", "base", "top"):
                if k in m:
                    row[k] = m[k]
            if "at" in m:
                row["at"] = P.label(m["at"])
            if "start" in m:
                row["between"] = [P.label(m["start"]), P.label(m["end"])]
            if "boundary" in m:
                row["boundary"] = [P.label(b) for b in m["boundary"]]
            out.append(row)
    shown = out[: p.limit]
    return ActionResult(
        message=f"{len(out)} members"
        + (f" (the first {len(shown)} listed)" if len(shown) < len(out) else "")
        + ".",
        data=shown,
    )


def _results_folder(view: ProjectView) -> Any:
    from saengine.pipeline.run_all import results_folder

    return results_folder(view.root / "08 FEM" / "model.osmodel")


def _read_json(path: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@action(
    "results.summary",
    summary="The state of every part (as the sidebar shows it) and the design and foundation "
    "summaries of the last run.",
    params=Empty,
    parts=("fem", "substructure"),
    kind="query",
    example={},
)
def results_summary(view: ProjectView, p: Empty) -> ActionResult:
    from saengine.pipeline.project import ProjectError, open_project
    from saengine.pipeline.status import part_statuses
    from saengine.pipeline.summaries import DESIGN_SUMMARY_FILE, SUBSTRUCTURE_SUMMARY_FILE

    try:
        project = open_project(view.root)
    except ProjectError as error:
        refuse(f"{error}: save the project first.")
        raise
    parts = [s.to_json() for s in part_statuses(project)]
    design = _read_json(_results_folder(view) / DESIGN_SUMMARY_FILE)
    foundations = _read_json(view.root / "09 Substructure" / SUBSTRUCTURE_SUMMARY_FILE)
    report = view.root / "11 Exports" / "report.pdf"
    data = {
        "parts": parts,
        "design": design,
        "foundations": foundations,
        "report": str(report) if report.is_file() else None,
    }
    said = "; ".join(f"{s['part']}: {s['state']}" for s in parts)
    return ActionResult(message=said, data=data)


class ChecksParams(Params):
    failing: bool = Field(default=True, description="Only the members that fail a check.")
    limit: int = Field(default=100, ge=1, le=10_000)


def _elements(report: Any) -> list[dict[str, Any]]:
    if not isinstance(report, dict):
        return []
    result = report.get("result") if isinstance(report.get("result"), dict) else report
    return [e for e in result.get("elements") or [] if isinstance(e, dict)]


def _check_ok(check: dict[str, Any]) -> bool:
    status = check.get("status")
    if isinstance(status, str):
        return status.lower() not in ("fail", "failed", "ng")
    if "ok" in check:
        return bool(check["ok"])
    if "pass" in check:
        return bool(check["pass"])
    u = check.get("utilisation", check.get("ratio"))
    return not (isinstance(u, int | float) and u > 1.0 + 1e-9)


@action(
    "checks.list",
    summary="The members' design checks of the last run (by default only the failing ones), "
    "with their utilisation and governing check.",
    params=ChecksParams,
    parts=("fem",),
    kind="query",
    example={"failing": True},
)
def checks_list(view: ProjectView, p: ChecksParams) -> ActionResult:
    report = _read_json(_results_folder(view) / "design-report.json")
    if report is None:
        refuse("There are no design checks yet: run the design (run.all or run.step design).")
    rows = []
    for e in _elements(report):
        checks = [c for c in e.get("checks") or [] if isinstance(c, dict)]
        failing = [c for c in checks if not _check_ok(c)]
        if p.failing and not failing and _check_ok(e):
            continue
        worst = max(checks, key=lambda c: c.get("utilisation") or c.get("ratio") or 0, default=None)
        rows.append(
            {
                "id": e.get("id") or e.get("element"),
                "type": e.get("type") or e.get("objectType"),
                "status": e.get("status"),
                "utilisation": e.get("utilisation", worst.get("utilisation") if worst else None),
                "governing": e.get("governing") or (worst.get("name") if worst else None),
                "failing": [c.get("name") for c in failing],
            }
        )
    shown = rows[: p.limit]
    result = report.get("result") if isinstance(report.get("result"), dict) else report
    seismic = (result.get("seismic") or {}) if isinstance(result, dict) else {}
    building = [
        {
            "name": c.get("name"),
            "utilisation": c.get("utilisation"),
            "ok": _check_ok(c),
            "note": c.get("note"),
        }
        for c in seismic.get("checks") or []
        if isinstance(c, dict) and (not p.failing or not _check_ok(c))
    ]
    what = "failing members" if p.failing else "members"
    message = f"{len(rows)} {what}"
    if building:
        message += f"; {len(building)} {'failing ' if p.failing else ''}building checks"
    return ActionResult(message=message + ".", data={"members": shown, "building": building})


class HelpParams(Params):
    name: str | None = Field(default=None, description="One action: its parameters and example.")
    kind: Literal["edit", "run", "query"] | None = None


@action(
    "actions.help",
    summary="The catalogue: every action (or one, with its parameters' schema and an example), "
    "and the order to build a whole project in.",
    params=HelpParams,
    parts=(),
    kind="query",
    example={"name": "columns.place"},
)
def actions_help(view: ProjectView, p: HelpParams) -> ActionResult:
    if p.name:
        try:
            info = get(p.name)
        except UnknownAction as error:
            refuse(str(error), "name", p.name)
            raise
        return ActionResult(
            message=f"{info.name} ({info.kind}): {info.summary}", data=info.model_dump()
        )
    infos = list_actions(p.kind)
    return ActionResult(
        message=f"{len(infos)} actions.",
        data={
            "actions": [{"name": a.name, "kind": a.kind, "summary": a.summary} for a in infos],
            "playbook": PLAYBOOK,
        },
    )

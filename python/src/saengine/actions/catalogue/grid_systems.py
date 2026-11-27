"""Grid system actions (05 Floor Plan ``grids.systems``): the grid systems beside the main
orthogonal grid, as the floor plan's Grid Systems editor makes them: a rotated orthogonal grid,
a radial grid (rays and rings about a centre) or single angled lines. Each system is checked by
the floor plan's model (:class:`saengine.library.floorplan.GridSystem`); labels are unique across
every system, so a grid point "A-R1" names any two lines that cross. Members placed on a
system's lines keep it from being deleted unless they are deleted with it."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, ValidationError

from saengine.actions.catalogue import _plan as P
from saengine.actions.catalogue._util import Params, given, plain
from saengine.actions.catalogue.grid import _plan, _remove_members
from saengine.actions.errors import refuse
from saengine.actions.paths import FLOOR_PLAN
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView
from saengine.library.floorplan import FreeGridLine, GridLine, GridSystem, RadialRay, RadialRing


def _systems(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return plan["grids"].setdefault("systems", [])


def _checked(system: dict[str, Any], field: str = "kind") -> dict[str, Any]:
    """``system`` as the floor plan model reads it, or refused with the model's reason."""
    try:
        return plain(GridSystem.model_validate(system))
    except ValidationError as error:
        first = error.errors()[0]
        refuse(
            f"The grid system is not valid: {first['msg'].removeprefix('Value error, ')}.",
            ".".join(str(x) for x in first["loc"]) or field,
            first.get("input") if not isinstance(first.get("input"), dict) else None,
        )
        raise


def _system_labels(system: dict[str, Any]) -> list[str]:
    groups = ("x", "y", "rays", "rings", "lines")
    return [str(g.get("label")) for k in groups for g in system.get(k) or [] if isinstance(g, dict)]


def _users(plan: dict[str, Any], labels: set[str]) -> list[tuple[str, dict[str, Any]]]:
    """The members that stand on any of ``labels`` (by either coordinate of a point)."""
    return [
        (g, m)
        for g in P.GROUPS
        for m in P.members(plan, g)
        if any(P.uses_label(m, axis, label) for axis in ("x", "y") for label in labels)
    ]


class SystemFields(Params):
    name: str | None = Field(default=None, description="A name for the system, e.g. 'Wing B'.")
    originX: float | None = Field(default=None, description="Origin or radial centre X [mm].")
    originY: float | None = Field(default=None, description="Origin or radial centre Y [mm].")
    angle: float | None = Field(
        default=None, description="Rotation of the system's axes, anticlockwise from X [°]."
    )
    x: list[GridLine] | None = Field(default=None, description="Orthogonal: local x lines.")
    y: list[GridLine] | None = Field(default=None, description="Orthogonal: local y lines.")
    rays: list[RadialRay] | None = Field(default=None, description="Radial: the rays.")
    rings: list[RadialRing] | None = Field(default=None, description="Radial: the rings.")
    lines: list[FreeGridLine] | None = Field(default=None, description="Lines: the lines.")


class SystemAddParams(SystemFields):
    kind: Literal["orthogonal", "radial", "lines"] = Field(
        description="orthogonal (rotated X/Y lines), radial (rays and rings) or lines (single "
        "angled lines)."
    )
    id: str | None = Field(default=None, description="Default: the next free GS<n>.")


@action(
    "grid.system.add",
    summary="Add a grid system beside the main grid: a rotated orthogonal grid, a radial grid "
    "(rays and rings about a centre) or single angled lines.",
    params=SystemAddParams,
    parts=("floorPlan",),
    kind="edit",
    example={
        "kind": "radial",
        "originX": 0,
        "originY": 0,
        "rays": [{"label": "R1", "angle": 0}, {"label": "R2", "angle": 30}],
        "rings": [{"label": "C1", "radius": 6000}],
    },
)
def grid_system_add(view: ProjectView, p: SystemAddParams) -> ActionResult:
    plan = _plan(view)
    systems = _systems(plan)
    taken = {s.get("id") for s in systems}
    system_id = p.id
    if system_id is None:
        n = 1
        while f"GS{n}" in taken:
            n += 1
        system_id = f"GS{n}"
    elif system_id in taken:
        refuse(f"There is a grid system '{system_id}' already (grid.system.set).", "id", p.id)
    raw = {"id": system_id, "kind": p.kind, **plain(given(p, *SystemFields.model_fields))}
    system = _checked({k: v for k, v in raw.items() if v is not None})
    if not _system_labels(system):
        refuse("Give the system's lines (x and y, rays and rings, or lines).", "kind", p.kind)
    systems.append(system)
    view.put(FLOOR_PLAN, plan)
    return ActionResult(
        message=f"Grid system {system_id} ({p.kind}) added: {', '.join(_system_labels(system))}.",
        created=[system_id],
    )


def _find(plan: dict[str, Any], system_id: str) -> dict[str, Any]:
    systems = _systems(plan)
    for s in systems:
        if s.get("id") == system_id:
            return s
    known = ", ".join(str(s.get("id")) for s in systems) or "none"
    refuse(f"There is no grid system '{system_id}' (the systems: {known}).", "id", system_id)
    raise AssertionError


class SystemSetParams(SystemFields):
    id: str = Field(description="The grid system to change.")


@action(
    "grid.system.set",
    summary="Change a grid system: its origin, rotation, name or lines (a list given replaces "
    "that list); members on a line that is gone refuse the change.",
    params=SystemSetParams,
    parts=("floorPlan",),
    kind="edit",
    example={"id": "GS1", "angle": 15},
)
def grid_system_set(view: ProjectView, p: SystemSetParams) -> ActionResult:
    plan = _plan(view)
    system = _find(plan, p.id)
    patch = plain(given(p, *SystemFields.model_fields))
    if not patch:
        refuse("Give what to change (name, originX, originY, angle or lines).", "id", p.id)
    changed = _checked({**system, **{k: v for k, v in patch.items() if v is not None}})
    gone = set(_system_labels(system)) - set(_system_labels(changed))
    users = _users(plan, gone)
    if users:
        refuse(
            f"Members stand on grid lines the change removes ({', '.join(sorted(gone))}): "
            f"{', '.join(m['id'] for _, m in users[:8])}. Keep those lines, or delete the "
            "members first (member.delete).",
            "id",
            p.id,
        )
    system.clear()
    system.update(changed)
    view.put(FLOOR_PLAN, plan)
    return ActionResult(message=f"Grid system {p.id} changed ({', '.join(sorted(patch))}).")


class SystemDeleteParams(Params):
    id: str
    deleteMembers: bool = Field(
        default=False,
        description="Also delete the members on its lines (else refused when there are any).",
    )


@action(
    "grid.system.delete",
    summary="Delete a grid system (with the members on its lines only when deleteMembers is true).",
    params=SystemDeleteParams,
    parts=("floorPlan", "loads"),
    kind="edit",
    example={"id": "GS1"},
)
def grid_system_delete(view: ProjectView, p: SystemDeleteParams) -> ActionResult:
    plan = _plan(view)
    system = _find(plan, p.id)
    users = _users(plan, set(_system_labels(system)))
    removed: list[str] = []
    if users:
        if not p.deleteMembers:
            refuse(
                f"{len(users)} members stand on grid system {p.id} "
                f"({', '.join(m['id'] for _, m in users[:8])}{' ...' if len(users) > 8 else ''}):"
                " give deleteMembers: true to delete them with it.",
                "deleteMembers",
                False,
            )
        removed = _remove_members(view, plan, users)
    plan["grids"]["systems"] = [s for s in _systems(plan) if s.get("id") != p.id]
    if not plan["grids"]["systems"]:
        del plan["grids"]["systems"]
    view.put(FLOOR_PLAN, plan)
    extra = f" and {len(removed)} members on it" if removed else ""
    return ActionResult(message=f"Grid system {p.id} deleted{extra}.")

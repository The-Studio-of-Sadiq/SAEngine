"""Foundation actions (09 Substructure): footings sized from the analysis reactions and the soil
by the existing sizing (:func:`saengine.substructure.sizing.propose`, the editor's Size Footings),
and a footing placed or changed by hand. Checked by the substructure model."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue import _plan as P
from saengine.actions.catalogue._util import Params, fmt
from saengine.actions.errors import refuse
from saengine.actions.paths import FLOOR_PLAN, SUBSTRUCTURE
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView, json_text


def _substructure(view: ProjectView) -> dict[str, Any]:
    from saengine.library.substructure import SCHEMA_ID, is_placeholder

    data = view.part(SUBSTRUCTURE, None)
    if not isinstance(data, dict) or is_placeholder(data):
        data = {"schema": SCHEMA_ID, "foundations": []}
    data.setdefault("foundations", [])
    return data


class GenerateParams(Params):
    columns: list[str] | None = Field(
        default=None,
        description="Column ids to size footings for; default: every column base without a "
        "foundation.",
    )
    replace: bool = Field(
        default=False, description="With columns: size them again even if they have one."
    )


@action(
    "foundations.generate",
    summary="Size footings for the column bases from the analysis reactions and the soil "
    "(Size Footings); needs the analysis results (run.step analyse first).",
    params=GenerateParams,
    parts=("substructure",),
    kind="run",
    example={},
)
def foundations_generate(view: ProjectView, p: GenerateParams) -> ActionResult:
    from saengine.rpc.handlers import substructure_size

    data = _substructure(view)
    answer = substructure_size(str(view.root), p.columns, json_text(data))
    if answer.get("problems"):
        refuse("The footings could not be sized: " + "; ".join(map(str, answer["problems"])))
    found = list(answer.get("foundations") or [])
    notes = [str(n) for n in answer.get("notes") or []]
    if not found:
        refuse(
            "No footings were sized: " + ("; ".join(notes) or "every column base has one."),
            "columns",
            p.columns,
        )
    sized = {c for f in found for c in f.get("columns") or []}
    if p.columns and p.replace:
        data["foundations"] = [
            f for f in data["foundations"] if not sized & set(f.get("columns") or [])
        ]
    taken = {f.get("id") for f in data["foundations"]}
    created = []
    for f in found:
        if f.get("id") in taken:
            n = 1
            while f"F{n}" in taken:
                n += 1
            f["id"] = f"F{n}"
        taken.add(f["id"])
        data["foundations"].append(f)
        created.append(f["id"])
    view.put(SUBSTRUCTURE, data)
    failing = [d.get("id") for d in answer.get("designs") or [] if d.get("ok") is False]
    warnings = notes + ([f"Footings that do not pass yet: {', '.join(failing)}"] if failing else [])
    return ActionResult(
        message=f"{len(created)} footings sized: {', '.join(created)}.",
        created=created,
        warnings=warnings,
    )


class FootingParams(Params):
    id: str | None = Field(default=None, description="An existing foundation to change; or new.")
    type: Literal["isolated", "combined"] = "isolated"
    columns: list[str] | None = Field(
        default=None, description="Column ids it carries (at their base)."
    )
    at: P.PointRef | None = Field(
        default=None, description="Or: the grid point of the column it carries (lowest storey)."
    )
    length: float | None = Field(default=None, description="Along x [mm].")
    width: float | None = Field(default=None, description="Along y [mm].")
    thickness: float | None = Field(default=None, description="[mm]")
    rotation: float | None = Field(default=None, description="[°]")
    material: str | None = Field(default=None, description="Concrete id; default: the project's.")


def _columns_at(plan: dict[str, Any], ref: Any) -> list[str]:
    pt = P.point(plan, ref, "at")
    lowest = P.story_ids(plan)[0] if P.story_ids(plan) else None
    found = [
        c["id"]
        for c in P.members(plan, "columns")
        if P.key(c.get("at")) == P.key(pt) and c.get("base") == lowest
    ]
    if not found:
        refuse(f"There is no column standing on the lowest level at {P.label(pt)}.", "at", ref)
    return found


@action(
    "footing.set",
    summary="Place or change a footing under columns (size, thickness, material).",
    params=FootingParams,
    parts=("substructure",),
    kind="edit",
    example={"at": "A-1", "length": 1500, "width": 1500, "thickness": 450},
)
def footing_set(view: ProjectView, p: FootingParams) -> ActionResult:
    from saengine.actions.paths import MATERIALS
    from saengine.library.materials import Category, default_of

    data = _substructure(view)
    plan = view.read(FLOOR_PLAN)
    existing = next((f for f in data["foundations"] if f.get("id") == p.id), None)
    columns = p.columns or (_columns_at(plan, p.at) if p.at is not None else None)
    if columns:
        known = {c["id"]: c for c in P.members(plan, "columns")}
        for c in columns:
            if c not in known:
                refuse(f"There is no column '{c}'.", "columns", c)
    if existing is None:
        if not columns:
            refuse("A new footing needs the columns it carries (columns, or at).", "columns", None)
        missing = [n for n in ("length", "width", "thickness") if getattr(p, n) is None]
        if missing:
            refuse(f"A new footing needs its {', '.join(missing)} [mm].", missing[0], None)
        taken = {f.get("id") for f in data["foundations"]}
        footing_id = p.id
        if footing_id is None:
            n = 1
            while f"F{n}" in taken:
                n += 1
            footing_id = f"F{n}"
        material = p.material or default_of(view.read(MATERIALS, {}), Category.CONCRETE)
        existing = {"id": footing_id, "type": p.type, "material": material}
        data["foundations"].append(existing)
        created = [footing_id]
    else:
        created = []
    if columns:
        existing["columns"] = columns
        points = [P.where(plan, c["at"]) for c in P.members(plan, "columns") if c["id"] in columns]
        existing["center"] = [
            sum(x for x, _ in points) / len(points),
            sum(y for _, y in points) / len(points),
        ]
    for name in ("length", "width", "thickness", "rotation", "material"):
        value = getattr(p, name)
        if value is not None:
            existing[name] = value
    if p.type and "type" in p.model_fields_set:
        existing["type"] = p.type
    view.put(SUBSTRUCTURE, data)
    size = "x".join(fmt(existing.get(k, 0)) for k in ("length", "width", "thickness"))
    return ActionResult(
        message=f"Footing {existing['id']} ({size} mm) under {', '.join(existing.get('columns') or [])}.",
        created=created,
    )

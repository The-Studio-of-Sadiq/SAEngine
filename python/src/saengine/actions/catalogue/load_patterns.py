"""Load pattern actions (02 Project Settings ``loadPatterns``, issue #301): the project's own load
cases beside the built-in D, SD, L and Lr (:mod:`saengine.library.load_patterns`). Member loads,
point loads and the area loads' other load name a pattern by its id; the combinations give it
factors. Renaming a pattern renames it everywhere; deleting one that loads use is refused unless
those loads go with it."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue._util import Params, fmt, given
from saengine.actions.errors import refuse
from saengine.actions.paths import LOADS, SETTINGS
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView
from saengine.library import load_patterns as lp

PatternType = Literal["Dead", "SuperDead", "Live", "RoofLive", "Wind", "Seismic", "Other"]


def _patterns(settings: dict[str, Any]) -> list[dict[str, Any]]:
    return settings.setdefault("loadPatterns", [])


def _check_id(pattern_id: str, field: str = "id") -> None:
    if pattern_id in lp.BUILT_IN_IDS or lp.reserved(pattern_id):
        refuse(
            f"'{pattern_id}' is a load case the program uses itself (D, SD, L, Lr, WX, EX, ...): "
            "choose another id.",
            field,
            pattern_id,
        )


def _find(settings: dict[str, Any], pattern_id: str) -> dict[str, Any]:
    for p in _patterns(settings):
        if p.get("id") == pattern_id:
            return p
    if pattern_id in lp.BUILT_IN_IDS:
        refuse(f"{pattern_id} is a built-in load pattern: it cannot be changed.", "id", pattern_id)
    known = ", ".join(str(p.get("id")) for p in _patterns(settings)) or "none"
    refuse(f"There is no load pattern '{pattern_id}' (the project's: {known}).", "id", pattern_id)
    raise AssertionError


def _uses(view: ProjectView, settings: dict[str, Any], pattern_id: str) -> dict[str, list[str]]:
    """Where ``pattern_id`` is used: member loads, area loads and combinations (by id/name)."""
    loads = view.read(LOADS, None)
    members = [
        str(x.get("id"))
        for x in (loads or {}).get("loads") or []
        if isinstance(x, dict) and x.get("case") == pattern_id
    ]
    areas = [
        str(a.get("id"))
        for a in settings.get("areaLoads") or []
        if a.get("otherPattern") == pattern_id
    ]
    combos = [
        str(c.get("name"))
        for c in settings.get("combinations") or []
        if pattern_id in (c.get("patterns") or {})
    ]
    return {"loads": members, "areaLoads": areas, "combinations": combos}


class PatternAddParams(Params):
    id: str = Field(description='Its code in the analysis and the tables, e.g. "EQP".')
    name: str | None = Field(default=None, description="What it is (default: its id).")
    type: PatternType = Field(
        default="Other",
        description="How it combines: the code combinations give it the factor of its type "
        "(Other: only the factors you give it).",
    )
    selfWeight: float = Field(
        default=0, ge=0, description="Times the structure's self-weight added to it (0: none)."
    )


@action(
    "load.pattern.add",
    summary="Add a load pattern of the project's own (a load case beside D, SD, L and Lr: "
    "equipment, construction or special loads); loads and combinations can then name it.",
    params=PatternAddParams,
    parts=("settings",),
    kind="edit",
    example={"id": "EQP", "name": "Equipment", "type": "Dead"},
)
def load_pattern_add(view: ProjectView, p: PatternAddParams) -> ActionResult:
    _check_id(p.id)
    settings = view.part(SETTINGS)
    patterns = _patterns(settings)
    if any(x.get("id") == p.id for x in patterns):
        refuse(f"There is a load pattern '{p.id}' already (load.pattern.set).", "id", p.id)
    patterns.append(
        {"id": p.id, "name": p.name or p.id, "type": p.type, "selfWeight": p.selfWeight}
    )
    view.put(SETTINGS, settings)
    weight = f", {fmt(p.selfWeight)} × self-weight" if p.selfWeight else ""
    return ActionResult(
        message=f"Load pattern {p.id} ({lp.TYPE_LABELS[p.type]}{weight}) added.", created=[p.id]
    )


class PatternSetParams(Params):
    id: str = Field(description="The pattern to change.")
    newId: str | None = Field(
        default=None,
        description="Rename it: the loads, area loads and combinations that name it follow.",
    )
    name: str | None = None
    type: PatternType | None = None
    selfWeight: float | None = Field(default=None, ge=0)


@action(
    "load.pattern.set",
    summary="Change a load pattern of the project's own: its name, type, self-weight "
    "multiplier, or its id (renamed in every load and combination that names it).",
    params=PatternSetParams,
    parts=("settings", "loads"),
    kind="edit",
    example={"id": "EQP", "selfWeight": 0.1},
)
def load_pattern_set(view: ProjectView, p: PatternSetParams) -> ActionResult:
    settings = view.part(SETTINGS)
    pattern = _find(settings, p.id)
    fields = given(p, "name", "type", "selfWeight")
    if not fields and not p.newId:
        refuse("Give what to change (newId, name, type or selfWeight).", "id", p.id)
    for key, value in fields.items():
        if value is None:
            refuse(f"{key} cannot be empty.", key, None)
        pattern[key] = value
    renamed: list[str] = []
    if p.newId and p.newId != p.id:
        _check_id(p.newId, "newId")
        if any(x.get("id") == p.newId for x in _patterns(settings)):
            refuse(f"There is a load pattern '{p.newId}' already.", "newId", p.newId)
        pattern["id"] = p.newId
        for a in settings.get("areaLoads") or []:
            if a.get("otherPattern") == p.id:
                a["otherPattern"] = p.newId
                renamed.append(f"area load {a.get('id')}")
        for c in settings.get("combinations") or []:
            factors = c.get("patterns") or {}
            if p.id in factors:
                c["patterns"] = {(p.newId if k == p.id else k): v for k, v in factors.items()}
                renamed.append(f"combination {c.get('name')}")
        loads = view.part(LOADS, None)
        if isinstance(loads, dict):
            count = 0
            for x in loads.get("loads") or []:
                if x.get("case") == p.id:
                    x["case"] = p.newId
                    count += 1
            if count:
                view.put(LOADS, loads)
                renamed.append(f"{count} member loads")
    view.put(SETTINGS, settings)
    what = ", ".join([*sorted(fields), *([f"id → {p.newId}"] if p.newId else [])])
    extra = f" (renamed in {', '.join(renamed)})" if renamed else ""
    return ActionResult(message=f"Load pattern {p.id} changed: {what}{extra}.")


class PatternDeleteParams(Params):
    id: str
    deleteLoads: bool = Field(
        default=False,
        description="Also delete the member loads in it and its area loads and combination "
        "factors (else refused when anything uses it).",
    )


@action(
    "load.pattern.delete",
    summary="Delete a load pattern of the project's own (its loads go with it only when "
    "deleteLoads is true).",
    params=PatternDeleteParams,
    parts=("settings", "loads"),
    kind="edit",
    example={"id": "EQP"},
)
def load_pattern_delete(view: ProjectView, p: PatternDeleteParams) -> ActionResult:
    settings = view.part(SETTINGS)
    _find(settings, p.id)
    uses = _uses(view, settings, p.id)
    used = {k: v for k, v in uses.items() if v}
    if used and not p.deleteLoads:
        refuse(
            f"Load pattern {p.id} is used by "
            + "; ".join(f"{k}: {', '.join(v[:6])}" for k, v in used.items())
            + ". Give deleteLoads: true to delete those with it.",
            "deleteLoads",
            False,
        )
    settings["loadPatterns"] = [x for x in _patterns(settings) if x.get("id") != p.id]
    if not settings["loadPatterns"]:
        del settings["loadPatterns"]
    for a in settings.get("areaLoads") or []:
        if a.get("otherPattern") == p.id:
            a.pop("otherPattern", None)
            a.pop("otherLoad", None)
    for c in settings.get("combinations") or []:
        if p.id in (c.get("patterns") or {}):
            c["patterns"] = {k: v for k, v in c["patterns"].items() if k != p.id}
    view.put(SETTINGS, settings)
    if uses["loads"]:
        loads = view.part(LOADS)
        loads["loads"] = [x for x in loads.get("loads") or [] if x.get("case") != p.id]
        view.put(LOADS, loads)
    extra = " with " + ", ".join(f"{len(v)} {k}" for k, v in used.items()) if used else ""
    return ActionResult(message=f"Load pattern {p.id} deleted{extra}.")

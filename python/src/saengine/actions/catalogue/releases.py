"""End release and point spring actions (06 BIM ``additions``, issue #303): what a member end
does not pass to its joint (released, or partly fixed by a spring), and springs from joints to
the ground with optional supports. Both are analysis-only additions of the building model, which
rebuilding keeps; they need the building model (Run All's first step, or ``run.step bim``).
Values follow the model's rule: empty (null) fixed, 0 released, a value a spring.

These are the edits of the analysis model's Properties panel (End Releases, Point Spring) as
well as the terminal's and the assistant's: the panel sends one action per change, so a change
merges into what the member or joint has (an action set to null is fixed again)."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue._util import Params, given
from saengine.actions.errors import refuse
from saengine.actions.paths import BIM
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView
from saengine.library.bim import END_ACTIONS, EndRelease, release_mechanisms

END_HELP = (
    "What changes at that end: a list of P, V2, V3, T, M2, M3 (released in full), or "
    '{"M3": 0, "M2": 5000, "T": null} (0 released; a value a spring [kN/m or kN·m/rad]; null '
    "fixed again). The actions not named keep what they have."
)
EndIn = list[Literal["P", "V2", "V3", "T", "M2", "M3"]] | dict[str, float | None]
#: Ids of new entries (as the building model's editors make them).
RELEASE_PREFIX = "ER"
SPRING_PREFIX = "PS"
#: A point spring is at a joint when within this distance [mm] of it.
_SAME_MM = 1.0


def _bim(view: ProjectView) -> dict[str, Any]:
    bim = view.part(BIM, None)
    if not isinstance(bim, dict):
        refuse(
            "There is no building model yet: build it first (run.step with step bim, or run.all).",
            "",
            None,
        )
    additions = bim.setdefault("additions", {})
    additions.setdefault("endReleases", [])
    additions.setdefault("pointSprings", [])
    return bim


def _linear(bim: dict[str, Any]) -> set[str]:
    ids = {
        str(e.get("id"))
        for e in bim.get("elements") or []
        if isinstance(e, dict) and e.get("kind") in ("beam", "column", "member")
    }
    return ids | {str(m.get("id")) for m in bim["additions"].get("members") or []}


def _next(bim: dict[str, Any], prefix: str) -> str:
    """The next free id with ``prefix`` among the building model's elements and additions."""
    taken = {str(e.get("id")) for e in bim.get("elements") or [] if isinstance(e, dict)}
    for items in bim["additions"].values():
        if isinstance(items, list):
            taken |= {str(x.get("id")) for x in items if isinstance(x, dict)}
    n = 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


def _end(value: EndIn | None, field: str) -> dict[str, float | None]:
    """The changes to one end: action -> 0 (released), a spring, or None (fixed again)."""
    if value is None:
        return {}
    if isinstance(value, list):
        return dict.fromkeys(value, 0.0)
    unknown = sorted(set(value) - set(END_ACTIONS))
    if unknown:
        refuse(f"{', '.join(unknown)}: an end has {', '.join(END_ACTIONS)} only.", field, value)
    for k, v in value.items():
        if v is not None and v < 0:
            refuse(f"{k}: a spring cannot be negative.", field, value)
    return {k: (None if v is None else float(v)) for k, v in value.items()}


class ReleaseSetParams(Params):
    members: list[str] = Field(
        min_length=1, description="Ids of beams, columns or members (of the building model)."
    )
    start: EndIn | None = Field(default=None, description="Start (i) end. " + END_HELP)
    end: EndIn | None = Field(default=None, description="End (j) end. " + END_HELP)
    preset: Literal["pinned", "pinnedStart", "pinnedEnd", "fixed"] | None = Field(
        default=None,
        description="Or: pinned (M2 and M3 released at both ends), pinnedStart, pinnedEnd (at "
        "one end), or fixed (every release removed: fixed at both ends).",
    )


_PIN = {"M2": 0.0, "M3": 0.0}
_PRESETS: dict[str, tuple[dict[str, float], dict[str, float]]] = {
    "pinned": (_PIN, _PIN),
    "pinnedStart": (_PIN, {}),
    "pinnedEnd": ({}, _PIN),
}


def _merged(old: Any, changes: dict[str, float | None]) -> dict[str, float]:
    out = {k: v for k, v in (old or {}).items() if k in END_ACTIONS and v is not None}
    for k, v in changes.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return {k: out[k] for k in END_ACTIONS if k in out}


@action(
    "release.set",
    summary="Set end releases (or partial fixity springs) of members: what an end does not pass "
    "to its joint, merged into what it has (null fixes an action again); a preset pins the "
    "ends, fixed removes every release.",
    params=ReleaseSetParams,
    parts=("bim",),
    kind="edit",
    example={"members": ["B1"], "preset": "pinned"},
)
def release_set(view: ProjectView, p: ReleaseSetParams) -> ActionResult:
    if p.preset is not None and (p.start is not None or p.end is not None):
        refuse("Give a preset or the start and end, not both.", "preset", p.preset)
    if p.preset is None and p.start is None and p.end is None:
        refuse("Give the start or end releases, or a preset.", "preset", None)
    fixing = p.preset == "fixed"
    if p.preset is not None and not fixing:
        start, end = (dict(x) for x in _PRESETS[p.preset])
    else:
        start, end = _end(p.start, "start"), _end(p.end, "end")
    bim = _bim(view)
    linear = _linear(bim)
    releases = bim["additions"]["endReleases"]
    created: list[str] = []
    fixed: list[str] = []
    for member in p.members:
        if member not in linear:
            refuse(
                f"There is no beam, column or member '{member}' in the building model.",
                "members",
                member,
            )
        existing = next((r for r in releases if r.get("member") == member), None)
        new_start = {} if fixing else _merged(existing and existing.get("start"), start)
        new_end = {} if fixing else _merged(existing and existing.get("end"), end)
        if not new_start and not new_end:
            if existing is not None:
                releases.remove(existing)
            fixed.append(member)
            continue
        entry = {
            "id": existing.get("id") if existing else _next(bim, RELEASE_PREFIX),
            "member": member,
            "start": new_start,
            "end": new_end,
        }
        problems = release_mechanisms(EndRelease.model_validate(entry))
        if problems:
            refuse(f"{problems[0]}: release less.", "start", p.start)
        if existing is None:
            releases.append(entry)
            created.append(entry["id"])
        else:
            existing.clear()
            existing.update(entry)
    view.put(BIM, bim)
    released = [m for m in p.members if m not in fixed]
    parts = []
    if released:
        parts.append(f"End releases of {', '.join(released)} set")
    if fixed:
        parts.append(f"{', '.join(fixed)} fixed at both ends")
    return ActionResult(message="; ".join(parts) + ".", created=created)


class ReleaseDeleteParams(Params):
    members: list[str] = Field(min_length=1, description="Members whose releases to remove.")


@action(
    "release.delete",
    summary="Remove the end releases of members (they are fixed again at both ends).",
    params=ReleaseDeleteParams,
    parts=("bim",),
    kind="edit",
    example={"members": ["B1"]},
)
def release_delete(view: ProjectView, p: ReleaseDeleteParams) -> ActionResult:
    bim = _bim(view)
    releases = bim["additions"]["endReleases"]
    have = {r.get("member") for r in releases}
    missing = [m for m in p.members if m not in have]
    if missing:
        refuse(f"{', '.join(missing)} have no end releases.", "members", missing)
    bim["additions"]["endReleases"] = [r for r in releases if r.get("member") not in p.members]
    view.put(BIM, bim)
    return ActionResult(message=f"End releases removed from {', '.join(p.members)}.")


_DOF = ("UX", "UY", "UZ", "RX", "RY", "RZ")


def _at(spring: dict[str, Any], at: list[float]) -> bool:
    where = spring.get("at")
    return (
        isinstance(where, list)
        and len(where) == 3
        and all(isinstance(v, int | float) for v in where)
        and math.dist(where, at) < _SAME_MM
    )


class SpringSetParams(Params):
    at: list[float] = Field(
        min_length=3, max_length=3, description="The joint [x, y, z] in mm (global)."
    )
    UX: float | None = Field(default=None, ge=0, description="[kN/m]; 0 or null: none.")
    UY: float | None = Field(default=None, ge=0, description="[kN/m]; 0 or null: none.")
    UZ: float | None = Field(default=None, ge=0, description="[kN/m]; 0 or null: none.")
    RX: float | None = Field(default=None, ge=0, description="[kN·m/rad]; 0 or null: none.")
    RY: float | None = Field(default=None, ge=0, description="[kN·m/rad]; 0 or null: none.")
    RZ: float | None = Field(default=None, ge=0, description="[kN·m/rad]; 0 or null: none.")
    support: Literal["none", "pinned", "fixed"] | None = Field(
        default=None, description="A support at the joint as well (none removes it)."
    )


@action(
    "spring.set",
    summary="Set the point spring at a joint: springs to the ground per direction and an "
    "optional pinned or fixed support, merged into what the joint has (0 or null removes a "
    "spring; a joint left with none loses its point spring).",
    params=SpringSetParams,
    parts=("bim",),
    kind="edit",
    example={"at": [0, 0, 0], "UX": 20000, "UY": 20000, "UZ": 50000},
)
def spring_set(view: ProjectView, p: SpringSetParams) -> ActionResult:
    changes = given(p, *_DOF, "support")
    if not changes:
        refuse("Give a stiffness (UX ... RZ) or a support.", "UX", None)
    bim = _bim(view)
    springs = bim["additions"]["pointSprings"]
    at = [float(v) for v in p.at]
    spring = next((s for s in springs if _at(s, at)), None)
    created: list[str] = []
    if spring is None:
        spring = {"id": _next(bim, SPRING_PREFIX), "at": [round(v) for v in at]}
        springs.append(spring)
        created.append(spring["id"])
    for key, value in changes.items():
        if value in (None, 0, "none"):
            spring.pop(key, None)
        else:
            spring[key] = value
    where = ", ".join(f"{v:g}" for v in at)
    if not any(spring.get(k) for k in _DOF) and spring.get("support", "none") == "none":
        springs.remove(spring)
        view.put(BIM, bim)
        return ActionResult(message=f"No point spring at ({where}) mm any more.")
    view.put(BIM, bim)
    return ActionResult(message=f"Point spring {spring['id']} at ({where}) mm.", created=created)


class SpringDeleteParams(Params):
    ids: list[str] = Field(min_length=1)


@action(
    "spring.delete",
    summary="Delete point springs by their ids.",
    params=SpringDeleteParams,
    parts=("bim",),
    kind="edit",
    example={"ids": ["PS1"]},
)
def spring_delete(view: ProjectView, p: SpringDeleteParams) -> ActionResult:
    bim = _bim(view)
    springs = bim["additions"]["pointSprings"]
    have = {s.get("id") for s in springs}
    missing = [i for i in p.ids if i not in have]
    if missing:
        refuse(f"There is no point spring {', '.join(missing)}.", "ids", missing)
    bim["additions"]["pointSprings"] = [s for s in springs if s.get("id") not in p.ids]
    view.put(BIM, bim)
    return ActionResult(message=f"Deleted point springs {', '.join(p.ids)}.")

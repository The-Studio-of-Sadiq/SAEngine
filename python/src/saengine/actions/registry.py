"""The catalogue of actions: ``@action`` registers one, :func:`list_actions` and :func:`get` read it.

An action is a function ``fn(view: ProjectView, p: Params) -> ActionResult`` with a Pydantic
model of its parameters. Its ``kind`` says how it may be used:

- ``edit``: changes part files through the view only (the app applies the changes as one undo
  step, nothing is written until the batch is written);
- ``run``: works on the saved project (Run All, the design proposal, exports): the files on disk
  must be current, so the app saves before it; it may also return edits through the view;
- ``query``: reads only.

``writes`` says whether the action writes files to disk itself (every ``run`` action, and
``project.create``, which makes a new project's files): a client saves the project before it,
asks the engineer first, and reads the written files again after it, instead of applying its
changes as an unsaved edit. A client decides by this flag, never by the action's name.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr

Kind = Literal["edit", "run", "query"]
KINDS: tuple[str, ...] = ("edit", "run", "query")


class ActionInfo(BaseModel):
    """One action of the catalogue, as the surfaces list it."""

    name: str
    summary: str
    kind: Kind
    writes: bool = Field(
        default=False,
        description="It writes files to disk itself (run actions, project.create): the client "
        "saves first, asks the engineer, and reads the written files again afterwards.",
    )
    parts: list[str] = Field(description="Ids of the parts it reads or edits (pipeline.project).")
    params_schema: dict[str, Any] = Field(description="JSON Schema of its parameters.")
    example: dict[str, Any] | None = Field(default=None, description="Example parameters.")

    _fn: Callable[..., Any] | None = PrivateAttr(default=None)
    _params: type[BaseModel] | None = PrivateAttr(default=None)

    @property
    def fn(self) -> Callable[..., Any]:
        assert self._fn is not None
        return self._fn

    @property
    def params(self) -> type[BaseModel]:
        assert self._params is not None
        return self._params


class UnknownAction(KeyError):
    """No action of that name."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else "unknown action"


_ACTIONS: dict[str, ActionInfo] = {}


def action(
    name: str,
    *,
    summary: str,
    params: type[BaseModel],
    parts: tuple[str, ...],
    kind: Kind,
    example: dict[str, Any] | None = None,
    writes: bool | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registers ``fn(view, p) -> ActionResult`` as the action ``name``. ``writes``: whether it
    writes files itself; default: every ``run`` action does."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in _ACTIONS:
            raise ValueError(f"action {name!r} is registered twice")
        if example is not None:
            params.model_validate(example)  # an example that does not validate is a bug
        info = ActionInfo(
            name=name,
            summary=summary,
            kind=kind,
            writes=kind == "run" if writes is None else writes,
            parts=list(parts),
            params_schema=params.model_json_schema(),
            example=example,
        )
        info._fn = fn
        info._params = params
        _ACTIONS[name] = info
        return fn

    return register


def _load() -> None:
    from saengine.actions import catalogue  # noqa: F401 - registers the actions


def list_actions(kind: str | None = None) -> list[ActionInfo]:
    """The actions (of ``kind``: edit, run or query), by name."""
    _load()
    return [a for name, a in sorted(_ACTIONS.items()) if kind is None or a.kind == kind]


def get(name: str) -> ActionInfo:
    """The action ``name``; :class:`UnknownAction` when there is none."""
    _load()
    found = _ACTIONS.get(name)
    if found is None:
        close = [n for n in sorted(_ACTIONS) if n.split(".")[0] == name.split(".")[0]]
        hint = f" (did you mean {', '.join(close)}?)" if close else " (actions.help lists them)"
        raise UnknownAction(f"There is no action '{name}'{hint}.")
    return found

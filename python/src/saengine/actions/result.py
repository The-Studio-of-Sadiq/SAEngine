"""What an action answers (:class:`ActionResult`) and what a batch answers (:class:`BatchResult`).

The changes an action makes are not in its result: they are in the
:class:`~saengine.actions.view.ProjectView` it edited, and a batch returns them all at once
(``BatchResult.changes``), so a batch is applied, or not, as one change.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Problem(BaseModel):
    """Why a value was refused: the field, the value given and the reason in words."""

    field: str = Field(default="", description="The parameter or the file's field (dotted).")
    value: Any = Field(default=None, description="The value that was refused.")
    reason: str = Field(description="Why, in the engineer's words (with the rule's source).")
    part: str | None = Field(
        default=None, description="The part file the field is in; none for a parameter."
    )


class ActionResult(BaseModel):
    """The answer of one action."""

    ok: bool = True
    message: str = Field(default="", description="What was done, in the engineer's words.")
    created: list[str] = Field(default_factory=list, description="Ids of what was created.")
    warnings: list[str] = Field(default_factory=list)
    problems: list[Problem] = Field(
        default_factory=list, description="Why the action was refused (guardrails, validation)."
    )
    data: Any = Field(default=None, description="What a query (or a run) found.")
    action: str = Field(default="", description="The action's name.")


class BatchResult(BaseModel):
    """The answer of :func:`saengine.actions.run_actions`."""

    ok: bool
    results: list[ActionResult] = Field(default_factory=list)
    changes: dict[str, str] = Field(
        default_factory=dict,
        description="The changed part files (path relative to the project folder -> the new "
        "text, in the project's own formatting). Empty when a step failed.",
    )
    failed_step: int | None = Field(default=None, description="Index of the first failed step.")
    written: list[str] = Field(
        default_factory=list,
        description="Files written to disk (write=True; or before a run step, which works on "
        "the saved files).",
    )
    version: dict[str, Any] | None = Field(
        default=None, description="The version saved after writing, when the project has versions."
    )

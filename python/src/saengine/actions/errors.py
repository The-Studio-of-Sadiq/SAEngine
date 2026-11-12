"""The refusal an action raises: its message and the problems (field, value, reason)."""

from __future__ import annotations

from typing import Any

from saengine.actions.result import Problem


class ActionError(Exception):
    """An action that cannot be done; the batch fails and nothing is changed."""

    def __init__(self, message: str, problems: list[Problem] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.problems = list(problems or [])


def refuse(message: str, field: str = "", value: Any = None, reason: str | None = None) -> None:
    """Raises :class:`ActionError` with one problem (the message is its reason by default)."""
    raise ActionError(message, [Problem(field=field, value=value, reason=reason or message)])

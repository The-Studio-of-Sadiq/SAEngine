"""Shared editing actions: one catalogue of typed, validated edits that every surface uses (the
command line ``saengine action``, the JSON-RPC ``actions/list`` and ``actions/run``, the SDK's
``api.list_actions`` and ``api.run_actions``, the app and its assistant).

An action is a thin wrapper: it checks its parameters (Pydantic) and the values (the input
guardrails of :mod:`saengine.library.guardrails`, the same rules as the editors), edits the part
files through the existing models and functions, and the changed parts are validated again before
the batch returns them. See docs/actions.md for the catalogue.

    from saengine.actions import run_actions
    result = run_actions(folder, [
        {"action": "project.create", "params": {"name": "House"}},
        {"action": "grid.set", "params": {"x": [5000, 5000], "y": [4000]}},
    ], write=True)
"""

from __future__ import annotations

from saengine.actions.errors import ActionError
from saengine.actions.registry import ActionInfo, UnknownAction, action, get, list_actions
from saengine.actions.result import ActionResult, BatchResult, Problem
from saengine.actions.run import load_steps, run_action, run_actions
from saengine.actions.view import ProjectView

__all__ = [
    "ActionError",
    "ActionInfo",
    "ActionResult",
    "BatchResult",
    "Problem",
    "ProjectView",
    "UnknownAction",
    "action",
    "get",
    "list_actions",
    "load_steps",
    "run_action",
    "run_actions",
]

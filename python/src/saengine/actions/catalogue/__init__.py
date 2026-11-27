"""The catalogue: importing this package registers every action (see docs/actions.md)."""

from __future__ import annotations

from saengine.actions import journal  # noqa: F401 - edit.undo, edit.redo, edit.history
from saengine.actions.catalogue import (  # noqa: F401 - each module registers its actions
    drafting,
    foundations,
    grid,
    grid_systems,
    load_patterns,
    loads,
    materials,
    members,
    project,
    query,
    releases,
    run,
    settings,
    soil,
)

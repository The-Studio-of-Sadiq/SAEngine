"""The catalogue: importing this package registers every action (see docs/actions.md)."""

from __future__ import annotations

from saengine.actions.catalogue import (  # noqa: F401 - each module registers its actions
    foundations,
    grid,
    loads,
    materials,
    members,
    project,
    query,
    run,
    settings,
    soil,
)

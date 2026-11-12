"""The project pipeline without the workbench: the headless Run All (:mod:`.run_all`), the
summaries the project's part list reads (:mod:`.summaries`), the part statuses it shows
(:mod:`.status`), the validation of every part (:mod:`.validate`) and the exports of
``11 Exports`` (:mod:`.exports`). The ``saengine`` command line (:mod:`saengine.cli`) is built on
them.

Run All's names are imported on first use: it pulls in the whole analysis stack, which the
light submodules (e.g. :mod:`.drawings`, asked for the drawing list on every open of
``11 Exports``) must not wait for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from saengine.pipeline.run_all import STEP_IDS, RunAllResult, StepResult, run_all

__all__ = ["STEP_IDS", "RunAllResult", "StepResult", "run_all"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module("saengine.pipeline.run_all")
    # Importing the submodule binds the package's ``run_all`` to it: bind the names to what
    # the module exports instead (``run_all`` the function), as the eager import did.
    globals().update({n: getattr(module, n) for n in __all__})
    return globals()[name]

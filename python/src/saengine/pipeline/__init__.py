"""The project pipeline without the workbench: the headless Run All (:mod:`.run_all`), the
summaries the project's part list reads (:mod:`.summaries`), the part statuses it shows
(:mod:`.status`), the validation of every part (:mod:`.validate`) and the exports of
``11 Exports`` (:mod:`.exports`). The ``saengine`` command line (:mod:`saengine.cli`) is built on
them.
"""

from saengine.pipeline.run_all import STEP_IDS, RunAllResult, StepResult, run_all

__all__ = ["STEP_IDS", "RunAllResult", "StepResult", "run_all"]

"""Part 9 Substructure: the design of the foundations (``09 Substructure/substructure.json``).

- :mod:`saengine.substructure.loads`: the column and wall base reactions per case and
  combination (service and strength).
- :mod:`saengine.substructure.shallow`: isolated, combined and strip footings, tie beams.
- :mod:`saengine.substructure.sizing`: the sizing assistant that proposes footings.
- :mod:`saengine.substructure.migrate`: the footings drawn in the building model (Part 6) moved
  into the substructure.
- :mod:`saengine.substructure.report`: :func:`substructure_report`, the checks of every
  foundation.

The model of the file is :mod:`saengine.library.substructure`.
"""

from saengine.substructure.migrate import migrate, migrate_project
from saengine.substructure.report import substructure_report
from saengine.substructure.sizing import propose, propose_footings

__all__ = ["migrate", "migrate_project", "propose", "propose_footings", "substructure_report"]

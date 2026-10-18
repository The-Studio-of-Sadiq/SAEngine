"""Plumbing sizing to BNBC 2020 Part 8 for the structural coordination of the services (Part 7).

The structural engineer coordinates the plumbing with the structure: the water tanks (their
volume, weight and RC design), the sleeves and shafts the risers and stacks need through the
slabs, the roof drains, and the buried septic tank, soak well and reservoir. This package sizes
these to BNBC 2020 Part 8 (Chapter 5 Water Supply, Chapter 6 Sanitary Drainage, Chapter 7
Rainwater Management) from what ``07 MEP/mep.json`` records under ``plumbing``.

- :mod:`saengine.plumbing.tables` the BNBC tables as data, each with its page
- :mod:`saengine.plumbing.demand` population, daily demand and fixture-unit peak flow
- :mod:`saengine.plumbing.storage` reservoir and overhead tank volumes, pipes and dimensions
- :mod:`saengine.plumbing.supply` water risers, pump main and pump, residual heads
- :mod:`saengine.plumbing.drainage` soil and waste stacks, branches, vents, building drain
- :mod:`saengine.plumbing.rainwater` roof catchments, leaders, gutters, storm drain, harvesting
- :mod:`saengine.plumbing.septic` septic tank, soak well, separation distances
- :mod:`saengine.plumbing.sleeves` sleeves through the slabs and the shaft areas
- :mod:`saengine.plumbing.report` :func:`plumbing_report`, :func:`plumbing_size_tanks`,
  :func:`plumbing_sleeves`
- :mod:`saengine.plumbing.tanks` (with :mod:`~saengine.plumbing.tanks_model`) the RC design of
  the tanks, :func:`design_tank`
- :mod:`saengine.plumbing.hydraulics` the water-supply network (WNTR), :func:`water_hydraulics`
- :mod:`saengine.plumbing.project` the joined report for the workbench, :func:`full_report`,
  the tank-design cache, the missing sleeves and the bill's pipe runs

The package imports nothing when it is imported, so that :mod:`saengine.library.mep` can use
the tables: the functions below are looked up on first use.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "plumbing_report": "saengine.plumbing.report",
    "plumbing_results": "saengine.plumbing.report",
    "plumbing_size_tanks": "saengine.plumbing.report",
    "plumbing_sleeves": "saengine.plumbing.report",
    "overhead_equipment": "saengine.plumbing.report",
    "design_tank": "saengine.plumbing.tanks",
    "tank_equipment": "saengine.plumbing.tanks",
    "water_hydraulics": "saengine.plumbing.hydraulics",
    "full_report": "saengine.plumbing.project",
    "design_tanks": "saengine.plumbing.project",
    "missing_sleeves": "saengine.plumbing.project",
    "occupancies": "saengine.plumbing.project",
}

__all__ = [  # noqa: RUF022 - grouped by module as above
    "plumbing_report",
    "plumbing_results",
    "plumbing_size_tanks",
    "plumbing_sleeves",
    "overhead_equipment",
    "design_tank",
    "tank_equipment",
    "water_hydraulics",
    "full_report",
    "design_tanks",
    "missing_sleeves",
    "occupancies",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'saengine.plumbing' has no attribute {name!r}")
    return getattr(import_module(module), name)

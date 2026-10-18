"""Cooling loads to BNBC 2020 Part 8 Chapter 2 for the structural coordination (Part 7).

The structural engineer coordinates the air-conditioning with the structure: the plant (its
weight and where it stands), the shafts and the openings its ducts need. The plant's size
follows from the building's cooling load, which this package works out from ``07 MEP/mep.json``
(``hvac``) and the building model ``06 BIM``: one thermal zone per story, the design days of
BNBC Table 8.2.2 and the ventilation of Table 8.2.3, simulated by EnergyPlus version 26.2.0 (run
as a separate program, never linked) or, without it, estimated by a documented hand method.

- :mod:`saengine.hvac.tables` the BNBC tables as data, each with its page
- :mod:`saengine.hvac.constructions` typical Bangladeshi walls, roofs and glazing
- :mod:`saengine.hvac.geometry` thermal zones and surfaces from the building model
- :mod:`saengine.hvac.energyplus` the epJSON input, the run and its results
- :mod:`saengine.hvac.fallback` the estimate when EnergyPlus is not available
- :mod:`saengine.hvac.report` :func:`hvac_loads` (cached in ``07 MEP/hvac.results/``)

The package imports nothing when it is imported, so that :mod:`saengine.library.mep` can use
the tables: the functions below are looked up on first use.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "hvac_loads": "saengine.hvac.report",
    "hvac_results": "saengine.hvac.report",
    "plant_equipment": "saengine.hvac.report",
    "find_energyplus": "saengine.hvac.energyplus",
}

__all__ = ["find_energyplus", "hvac_loads", "hvac_results", "plant_equipment"]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'saengine.hvac' has no attribute {name!r}")
    return getattr(import_module(module), name)

"""Electrical coordination to BNBC 2020 Part 8 Chapter 1 for the structure (Part 7).

The structural engineer coordinates the electrical services with the structure: the weight of
the transformers, switchgear, generators and fuel tanks on the floors, the substation and
generator rooms the code asks for, the electrical shafts and the openings the rising mains and
cable trays need through the slabs and beams, and the lightning protection that uses the
columns' reinforcement as down conductors and the foundations as earth electrodes. This package
works these out from what ``07 MEP/mep.json`` records under ``electrical``.

- :mod:`saengine.electrical.tables` the BNBC 2020 Part 8 Chapter 1 tables and rules as data,
  each with its page, and the typical equipment data (labelled typical)
- :mod:`saengine.electrical.demand` connected load and maximum demand per story
- :mod:`saengine.electrical.supply` substation, transformer, standby generator and fuel, UPS
- :mod:`saengine.electrical.rooms` substation and generator room checks, electrical shafts
- :mod:`saengine.electrical.risers` rising mains, cable trays and their openings
- :mod:`saengine.electrical.lightning` lightning protection and earthing
- :mod:`saengine.electrical.report` :func:`electrical_report`,
  :func:`electrical_propose_equipment`, :func:`electrical_openings`

The package imports nothing when it is imported, so that :mod:`saengine.library.mep` can use
the tables.
"""

from __future__ import annotations

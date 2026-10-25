"""Fire protection coordination to BNBC 2020 Part 4 for the structure (Part 7).

The structural engineer coordinates the fire protection services with the structure: which
systems the building needs (portable extinguishers, alarm and detection, the hydrant or
standpipe system, sprinklers) and why, the water they need and where it is stored (the fire
reservoir, an RC tank designed like the plumbing tanks, whose weight loads the structure when it
stands on a floor), the fire pumps and their room, the sleeves the risers and mains need through
the slabs and beams, and the hanger and riser-support loads the code gives. This package works
these out from what ``07 MEP/mep.json`` records under ``fire``.

- :mod:`saengine.fire.tables` the BNBC 2020 Part 4 tables and rules as data, each with its page,
  and the values taken from NFPA from memory (flagged "from memory, to be checked")
- :mod:`saengine.fire.requirements` occupancy, height and area: the systems required, by clause
- :mod:`saengine.fire.sprinklers` hazard class, heads per floor, the design area, pipe schedule
- :mod:`saengine.fire.network` the hydraulic calculation (WNTR / EPANET, as the plumbing)
- :mod:`saengine.fire.supply` water demand and reservoir, fire pumps and jockey pump, pump room
- :mod:`saengine.fire.report` :func:`fire_report`, :func:`fire_openings`,
  :func:`fire_propose`, :func:`fire_equipment`

The package imports nothing when it is imported, so that :mod:`saengine.library.mep` can use
the tables.
"""

from __future__ import annotations

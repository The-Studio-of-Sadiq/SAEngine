"""Timber member design to BNBC 2020 Part 6 Chapter 11 (permissible stress design, the
provisions of IS 883:1994), laid out like :mod:`saengine.design.steel`:

- :mod:`.members`: permissible stresses by strength group and location, the column formulas,
  bending, shear, tension, compression and combined stresses of rectangular sawn members under
  the allowable stress combinations, and the design report entry of a member
  (:func:`.members.design_timber_member`).
"""

from __future__ import annotations

from saengine.design.timber.members import (
    CODE,
    METHOD,
    Section,
    Timber,
    TimberDesignError,
    allowable_combinations,
    asd_pieces,
    check_member,
    compression_stress,
    depth_factor,
    design_timber_member,
    duration_factor,
    is_timber,
    lateral_kinds,
)

__all__ = [
    "CODE",
    "METHOD",
    "Section",
    "Timber",
    "TimberDesignError",
    "allowable_combinations",
    "asd_pieces",
    "check_member",
    "compression_stress",
    "depth_factor",
    "design_timber_member",
    "duration_factor",
    "is_timber",
    "lateral_kinds",
]

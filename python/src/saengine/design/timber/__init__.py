"""Timber design with the code pack's ``timber`` table (permissible stress design; with the
bnbc2020 pack, BNBC 2020 Part 6 Chapter 11), laid out like :mod:`saengine.design.steel`:

- :mod:`.members`: permissible stresses by species or strength group, location, grade and
  durability, the modification factors, flexural members, solid, box and spaced columns,
  combined stresses, bearing and deflection, and the design report entry of a member
  (:func:`.members.design_timber_member`);
- :mod:`.connections`: nailed, bolted, split-ring and disc-dowel joints at the member ends.
"""

from __future__ import annotations

from saengine.design.timber.connections import (
    bolt_capacity,
    bolt_factors,
    check_joint,
    dowel_capacity,
    lateral_nail_strength,
)
from saengine.design.timber.members import (
    Section,
    Timber,
    TimberDesignError,
    allowable_combinations,
    angle_bearing,
    asd_pieces,
    bearing_factor,
    box_compression_stress,
    box_form_factor,
    check_member,
    clause,
    code_name,
    combination_durations,
    compression_stress,
    concentrated_reduction,
    concentrated_shear,
    deflection_row,
    depth_factor,
    design_timber_member,
    duration_factor,
    find_species,
    is_timber,
    lateral_kinds,
    method,
    notch_shear,
    plank,
    slope_factor,
    spaced_compression_stress,
    uniform_shear,
)

__all__ = [
    "Section",
    "Timber",
    "TimberDesignError",
    "allowable_combinations",
    "angle_bearing",
    "asd_pieces",
    "bearing_factor",
    "bolt_capacity",
    "bolt_factors",
    "box_compression_stress",
    "box_form_factor",
    "check_joint",
    "check_member",
    "clause",
    "code_name",
    "combination_durations",
    "compression_stress",
    "concentrated_reduction",
    "concentrated_shear",
    "deflection_row",
    "depth_factor",
    "design_timber_member",
    "dowel_capacity",
    "duration_factor",
    "find_species",
    "is_timber",
    "lateral_kinds",
    "lateral_nail_strength",
    "method",
    "notch_shear",
    "plank",
    "slope_factor",
    "spaced_compression_stress",
    "uniform_shear",
]

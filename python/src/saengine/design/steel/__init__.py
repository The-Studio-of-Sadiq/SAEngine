"""Steel member design to BNBC 2020 Part 6 Chapter 10 (LRFD, the provisions of AISC 360-05).

- :mod:`.properties`: section properties of rolled and hollow shapes from their plates;
- :mod:`.classify`: local buckling classes (Sec 10.2.4, Table 6.10.1);
- :mod:`.lengths`: unbraced lengths, K and Cb from the analysis model;
- :mod:`.members`: tension, compression, flexure, shear and combined forces, and the design
  report entry of a member (:func:`.members.design_steel_member`);
- :mod:`.torsion`: torsion of hollow, open and solid members (B31);
- :mod:`.built_up`: built-up compression members, modified slenderness and spacing (B31).
"""

from __future__ import annotations

from saengine.design.steel.members import (
    CODE,
    METHOD,
    Steel,
    SteelDesignError,
    SteelOptions,
    check_member,
    design_steel_member,
    is_steel_member,
    member_stations,
)
from saengine.design.steel.properties import ShapeProperties, shape_properties

__all__ = [
    "CODE",
    "METHOD",
    "ShapeProperties",
    "Steel",
    "SteelDesignError",
    "SteelOptions",
    "check_member",
    "design_steel_member",
    "is_steel_member",
    "member_stations",
    "shape_properties",
]

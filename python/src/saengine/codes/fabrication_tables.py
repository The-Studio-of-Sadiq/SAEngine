"""Table model of steel fabrication (alpha 9 track L10): ``fabrication``.

Read by :mod:`saengine.fabrication` (the steel shop drawings and the DSTV NC files); this module
holds no numbers:

- ``weldSymbols``: the standard the shop drawings' weld symbols follow: ``aws`` (AWS A2.4: the
  arrow side below the reference line, the leg size left of the symbol) or ``isoA`` / ``isoB``
  (ISO 2553 system A: a dashed identification line, the leg written ``z``; system B: no dashed
  line, the arrow side below the line as AWS). A project chooses another in Project Settings ›
  Drawings › Fabrication;
- ``anchorHoleClearance``: the anchor rod holes of a base plate are this much larger than the rod
  [mm] (the code's bolt holes are for bolts, not rods cast in concrete; the bolt holes are the
  steel table's, :func:`saengine.design.steel_connections.hole_diameter`);
- ``copeClearance``: the gap [mm] a coped beam keeps from the flange and the root of the beam it
  frames into (the cope's depth is the supporting beam's flange and root radius plus this, and
  its length the supporting flange's outstand plus this).

Every number is the pack's; its VERIFY.md gives each value's source (SAEngine practice where the
code gives none).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from saengine.codes.tables import TableModel

WeldSymbols = Literal["aws", "isoA", "isoB"]


class FabricationTable(TableModel):
    """Steel fabrication: shop drawing symbols and the drilling allowances (module notes)."""

    weldSymbols: WeldSymbols = Field(
        default="aws",
        description="Weld symbols of the shop drawings: AWS A2.4 (aws) or ISO 2553 system A "
        "(isoA) or system B (isoB).",
    )
    anchorHoleClearance: float = Field(
        default=6.0, ge=0, description="Base plate holes: anchor rod diameter plus this [mm]."
    )
    copeClearance: float = Field(
        default=10.0,
        ge=0,
        description="A coped beam's gap from the flange and root of the beam it frames into [mm].",
    )

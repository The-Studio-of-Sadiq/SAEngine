"""Table model of the services' supports for fabrication detailing (alpha 9 L11):
``mepFabrication``.

Read by :mod:`saengine.mep.fabrication`; this module holds no numbers:

- ``pipeSupports``: the largest spacing of the hangers of horizontal pipes and of the supports of
  vertical pipes, by pipe material (the ids of 07 MEP's pipe materials, or a pack's own) and
  diameter range;
- ``ductSupports``: the largest spacing of duct supports by the duct's size (its larger side or
  diameter);
- ``fireMains``: the hangers of horizontal fire mains (standpipes): the largest spacing and the
  load a hanger is designed for (a factor on the weight of the water-filled pipe plus an extra
  mass);
- ``sprinklerHangers``: the same load rule for sprinkler pipes.

A pack without the table does not cover fabrication supports: the project then gives its own
spacings in ``07 MEP/fabrication.json``. Every number is the pack's; its VERIFY.md gives each
value's source.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from saengine.codes.tables import Positive, TableModel, _Row


class PipeSupportRow(_Row):
    """Support spacing of one pipe material (and diameter range)."""

    material: str = Field(description="Pipe material id (07 MEP's, e.g. gi, cpvc, upvc, copper).")
    label: str = ""
    minDiameter: float | None = Field(
        default=None, ge=0, description="Applies from this nominal diameter [mm] (exclusive)."
    )
    maxDiameter: float | None = Field(
        default=None, gt=0, description="Applies up to this nominal diameter [mm] (inclusive)."
    )
    horizontal: Positive = Field(description="Largest hanger spacing of horizontal runs [mm].")
    vertical: Positive = Field(description="Largest support spacing of vertical runs [mm].")


class DuctSupportRow(_Row):
    maxSize: float | None = Field(
        default=None, gt=0, description="Up to this size [mm] (larger side or diameter)."
    )
    spacing: Positive = Field(description="Largest support spacing [mm].")


class HangerLoad(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spacing: float | None = Field(default=None, gt=0, description="Largest spacing [mm].")
    loadFactor: Positive = Field(description="Times the weight of the water-filled pipe.")
    extraMass: float = Field(default=0, ge=0, description="Plus this mass [kg].")


class MepFabricationTable(TableModel):
    """Supports of the services for fabrication detailing (see the module notes)."""

    pipeSupports: list[PipeSupportRow] = Field(default_factory=list)
    ductSupports: list[DuctSupportRow] = Field(default_factory=list)
    fireMains: HangerLoad | None = None
    sprinklerHangers: HangerLoad | None = None

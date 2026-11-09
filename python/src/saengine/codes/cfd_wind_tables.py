"""Table model of the CFD wind tunnel link (alpha 9 L3): ``cfdWind``.

Read by :mod:`saengine.fem.cfd_wind`; this module holds no numbers:

- ``directionStep``: the wind directions computed, every this many degrees from the model's +X
  (the project can list its own directions instead);
- ``roughness``: the aerodynamic roughness length z0 [m] of the atmospheric boundary layer at
  the inlet, by the wind table's exposure (terrain category) id; an exposure missing here takes
  the wind table's own z0 where it has one;
- ``lowerLimit``: the storey forces taken from the CFD into the analysis are scaled up until the
  largest base shear along each plan axis is at least this share of the code's own (static)
  wind base shear on that axis; none: no lower limit;
- ``validation``: what the code asks of a wind tunnel (or similar fluid) test, in a few words,
  for the report's statement that the CFD results are engineer-supplied and need validation.

Every number is the pack's; its VERIFY.md gives each value's source.
"""

from __future__ import annotations

from pydantic import Field

from saengine.codes.tables import Positive, TableModel


class CfdWindTable(TableModel):
    """The CFD wind tunnel (see the module notes)."""

    directionStep: float = Field(
        gt=0, le=90, description="Wind directions every this many degrees from +X [°]."
    )
    roughness: dict[str, Positive] = Field(
        default_factory=dict,
        description="Roughness length z0 [m] of the inlet boundary layer by exposure id.",
    )
    lowerLimit: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="The CFD base shear along each axis at least this share of the code's.",
    )
    validation: str = Field(
        default="",
        description="What the code asks of a wind tunnel test, in a few words (the report).",
    )

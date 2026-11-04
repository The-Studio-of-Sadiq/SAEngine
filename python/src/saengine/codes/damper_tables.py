"""Table model of structures with supplemental damping systems (alpha 9 track P6).

A pack with a ``dampers`` table covers damper braces (:class:`saengine.library.objects.
SupplementalDamper`) in the design: the added effective damping of the devices, the damped
equivalent lateral force and the damped response spectrum (:mod:`saengine.fem.dampers`). A pack
without it still gets the devices modelled (their braces' stiffness, the nonlinear time history
links) but no reduction of the earthquake forces.

Methods (``method``, picked by the pack):

- ``modalStrength``: the fundamental and residual mode form of the equivalent lateral force for
  structures with damping systems (the ASCE 7 Chapter 18 form): V = √(V1² + VR²) with
  V1 = Cs1·W̄1, Cs1 = (R/Cd)·Sa(T1D)/(Ω0·B1D), VR = CsR·W̄R at TR = residualPeriodShare·T1,
  the effective ductility μD from the design roof displacement over the yield displacement,
  the hysteretic damping of the structure, and not less than Vmin = V/B(V+I) nor
  minimumShare·V;
- ``dampedSpectrum``: the fixed-base equivalent lateral force with the spectrum divided by the
  damping coefficient of the total effective damping over that of the inherent damping, not
  less than minimumShare·V (a generic method for a pack whose code gives no procedure).

Every number is the pack's; the pack's VERIFY.md gives each value's source.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from saengine.codes.tables import (
    IsolationDampingPoint,
    IsolationRequirement,
    Positive,
    Share,
    TableModel,
    _Row,
)


class DamperDuctility(_Row):
    """The structure's effective ductility and hysteretic damping (``modalStrength``):
    βHD = qH (hystereticBase − βI)(1 − 1/μD), qH = qhFactor·TS/T1 within [qhMin, qhMax], μD at
    most R/(Ω0·Ie) with ``maximum`` "strengthRatio"."""

    hystereticBase: Share = Field(description="The constant of βHD (fraction of critical).")
    qhFactor: Positive = Field(description="qH = this × TS / T1 ...")
    qhMin: Share = Field(description="... at least this ...")
    qhMax: Positive = Field(description="... and at most this.")
    maximum: Literal["strengthRatio", "none"] = Field(
        default="strengthRatio", description="The largest effective ductility μmax."
    )
    note: str = ""


class DampersTable(TableModel):
    """Structures with supplemental damping systems: the procedure, the damping coefficients,
    the limits and the requirements of the damping system."""

    method: Literal["modalStrength", "dampedSpectrum"] = Field(
        description="Method id of the damped equivalent lateral force (module notes)."
    )
    dampingCoefficients: list[IsolationDampingPoint] = Field(
        min_length=2, description="Effective damping [%] -> damping coefficient B."
    )
    inherentMax: Positive | None = Field(
        default=None, description="The inherent damping βI at most [%] (none: as set)."
    )
    maxDamping: Positive | None = Field(
        default=None, description="The total effective damping taken at most [%]."
    )
    residualPeriodShare: Share = Field(
        default=0.4, description="Residual mode period TR = this × T1."
    )
    minimumShare: Share = Field(
        description="The damped base shear at least this × the fixed-base base shear."
    )
    ductility: DamperDuctility | None = Field(
        default=None, description="Effective ductility of the structure (modalStrength)."
    )
    mceFactor: Positive = Field(
        default=1.0,
        description="The devices' stroke, velocity and force at this × the design "
        "displacement (the maximum considered earthquake).",
    )
    dampedFromShare: Share = Field(
        default=0.8,
        description="The response spectrum is divided by the damping ratio from this × T1 up "
        "(SAEngine practice, see note).",
    )
    requirements: list[IsolationRequirement] = Field(default_factory=list)
    review: list[str] = Field(default_factory=list)
    note: str = ""

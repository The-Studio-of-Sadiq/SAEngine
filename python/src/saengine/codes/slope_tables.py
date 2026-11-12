"""Table model of slope stability (alpha 9 track L8).

The pack's ``slopeStability`` table holds the method ids and the values of the limit
equilibrium check of a slope's section and of its strength reduction by finite elements
(:mod:`saengine.substructure.slope_stability`, :mod:`saengine.substructure.geotech_fe`); a pack
without it does not check slopes. The default pack's BNBC 2020 names landslides as a site
hazard and asks for the stability of adjoining buildings (Part 6 Sec 3.14) without a method or a
factor of safety for slopes: every value there is SAEngine practice, and the report says so.

- ``methods``: the limit equilibrium methods run on every case (``bishop`` simplified,
  ``janbu`` simplified with Janbu's correction factor, ``spencer``, ``morgensternPrice`` with the
  half-sine interslice function); ``checked``: those whose factor of safety is checked against
  the required one (the others are reported);
- ``verification``: ``factorOfSafety`` (the lowest factor of safety of the characteristic
  strengths against ``required`` by the slope's permanence, and ``required.seismic`` under the
  pseudo-static seismic coefficients), or ``partialFactors`` (each combination of the pack's
  ``geotechnicalMethods`` design approach: the design strengths of its set M and the factored
  variable surcharges of its set A, the factor of safety at least ``partialFactors.resistances``
  of its set R, the overall stability resistance factor γR;e);
- ``seismic``: the pseudo-static coefficients kh = ``khFactor`` × the peak ground acceleration
  of the project's seismic settings and kv = ± ``kvRatio`` × kh, and the set M of the seismic
  case under partial factors;
- ``reinforcement``: the factors on the tensile capacity and the pull-out resistance of soil
  nails and ground anchors taken as resisting forces.

Every number is the pack's; the pack's VERIFY.md gives each value's source.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.tables import Positive, TableModel, _Group

SlopeMethodId = Literal["bishop", "janbu", "spencer", "morgensternPrice"]


class SlopeRequired(_Group):
    """Least factors of safety of the ``factorOfSafety`` verification."""

    permanent: Positive = Field(description="Permanent slopes (long term).")
    temporary: Positive = Field(description="Temporary slopes (end of construction, cuts).")
    seismic: Positive = Field(description="Under the pseudo-static seismic coefficients.")


class SlopePartialFactors(_Group):
    """The ``partialFactors`` verification on the pack's ``geotechnicalMethods`` sets."""

    approach: str | None = Field(
        default=None,
        description="Design approach (a key of geotechnicalMethods.approaches); empty: the "
        "pack's designApproach.",
    )
    resistances: dict[str, Positive] = Field(
        description="γR;e of overall stability by the combination's resistance set (R1, R2, R3)."
    )
    soilWeight: Positive = Field(
        description="Factor on the soil's own weight (1.0: the single-source principle; the "
        "set M's γγ still divides it)."
    )


class SlopeSeismic(_Group):
    """Pseudo-static seismic coefficients."""

    method: Literal["pseudoStatic"] = "pseudoStatic"
    khFactor: float = Field(
        ge=0, le=2, description="kh = this × the peak ground acceleration [g] of the project."
    )
    kvRatio: float = Field(ge=0, le=1, description="kv = ± this × kh (both signs are checked).")
    materials: str | None = Field(
        default=None,
        description="Partial factors: the set M of the seismic case (a key of "
        "geotechnicalMethods.materials); empty: the characteristic strengths.",
    )
    required: Positive | None = Field(
        default=None,
        description="Partial factors: the least factor of safety of the seismic case; empty: "
        "required.seismic.",
    )


class SlopeReinforcement(_Group):
    """Soil nails and ground anchors as resisting forces on the slip surface."""

    standard: str = Field(description="Shown in the report, e.g. 'FHWA-NHI-14-007'.")
    tendonFactor: Positive = Field(description="Tensile capacity / this.")
    bondFactor: Positive = Field(description="Pull-out (grout-ground bond) resistance / this.")


class SlopeStabilityTable(TableModel):
    """Limit equilibrium of slopes and their strength reduction (see the module)."""

    methods: list[SlopeMethodId] = Field(  # type: ignore[valid-type]
        min_length=1, description="The limit equilibrium methods run (each reported)."
    )
    checked: list[SlopeMethodId] = Field(  # type: ignore[valid-type]
        min_length=1,
        description="The methods whose factor of safety is checked against the required one.",
    )
    verification: Literal["factorOfSafety", "partialFactors"]
    required: SlopeRequired
    partialFactors: SlopePartialFactors | None = None
    seismic: SlopeSeismic
    reinforcement: SlopeReinforcement

    @model_validator(mode="after")
    def _consistent(self) -> SlopeStabilityTable:
        missing = [m for m in self.checked if m not in self.methods]
        if missing:
            raise ValueError(f"slopeStability: checked methods not run: {', '.join(missing)}")
        if self.verification == "partialFactors" and self.partialFactors is None:
            raise ValueError("slopeStability: partialFactors verification needs partialFactors")
        return self


__all__ = [
    "SlopeMethodId",
    "SlopePartialFactors",
    "SlopeReinforcement",
    "SlopeRequired",
    "SlopeSeismic",
    "SlopeStabilityTable",
]

"""Table models of the composite members track (alpha 9 P8).

- ``compositeSlab``: composite slabs on profiled steel deck, one-way along the ribs: the deck
  as formwork under the wet concrete and the construction load (bending, deflection, ponding),
  the composite slab's plastic sagging resistance, its longitudinal shear by the m-k (shear
  bond) or the partial connection method from the deck's tests, the vertical shear (by the
  pack's ``concreteMethods.shear``), the deflection on the mean of the cracked and uncracked
  sections, the thickness limits and the anti-crack bars above the ribs
  (:mod:`saengine.design.composite_slab`);
- ``composite.beam.longitudinalShear`` (method ``flangeStrut``): the longitudinal shear of the
  slab of a composite beam through the shear planes beside the beam and round the connectors,
  the transverse bars needed and the crushing of the struts
  (:func:`saengine.design.steel.composite.longitudinal_shear_rows`);
- ``composite.beam.camber``: the camber proposed for an unshored composite beam from the
  deflection of the steel alone under the wet concrete (SAEngine practice where the code is
  silent).

A pack without the table or the group keeps what it had: nothing of these is checked (the
planned-feature page shows the composite slab as not covered). Every number is the pack's; its
VERIFY.md gives each value's clause.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from saengine.codes.tables import Positive, Share, TableModel, _Group

# ─────────────────────────────── composite.beam groups ───────────────────────────────


class CompositeLongitudinalShear(_Group):
    """``flangeStrut``: the slab's longitudinal shear per unit length through each shear plane,
    vEd = ΔFd / (hf Δx), ΔFd the share of the slab's compression force beyond the plane over
    Δx (the largest positive moment to the nearest zero moment), against the transverse bars
    crossing the plane, Asf fyd / sf >= vEd hf / cot θf, and the struts, vEd <= ν fcd sin θf
    cos θf with ν = nu[0] (1 - fck / nu[1])."""

    method: Literal["flangeStrut"] = "flangeStrut"
    cotTheta: tuple[Positive, Positive] = Field(
        description="Range of cot θf of a flange in compression (the largest is used unless "
        "the struts crush, then the smallest)."
    )
    nu: tuple[Positive, Positive] = Field(description="(a, b) of ν = a (1 - fck / b).")
    aroundStuds: bool = Field(
        default=True,
        description="Also the plane round the connectors (solid slabs): its length 2 hsc + "
        "the studs' spread + d, the bottom bars counted twice.",
    )


class CompositeCamber(_Group):
    """The camber proposed for an unshored composite beam: ``share`` × the deflection of the
    steel alone under the wet concrete, the deck and the beam (5 w L⁴ / 384 E Is), rounded down
    to ``step``; none below ``minimum``. Reported, not checked."""

    share: Share = Field(description="Of the wet-concrete deflection.")
    minimum: Positive = Field(description="No camber below this [mm].")
    step: Positive = Field(description="Rounded down to this [mm].")


# ─────────────────────────────── compositeSlab ───────────────────────────────


class SlabConstructionLoad(_Group):
    """The construction load on the deck before the concrete hardens: ``workingShare`` × the
    wet concrete's weight within ``workingMin``-``workingMax`` over a working area
    ``workingLength`` long (at mid-span), ``outside`` elsewhere [kN/m²]."""

    workingShare: Share
    workingMin: Positive = Field(description="[kN/m²]")
    workingMax: Positive = Field(description="[kN/m²]")
    workingLength: Positive = Field(description="[mm]")
    outside: Positive = Field(description="[kN/m²]")


class SlabPonding(_Group):
    """Ponding: when the deck's deflection under its weight and the wet concrete exceeds
    ``threshold`` × the slab depth, the concrete's weight is increased by ``share`` × that
    deflection (as extra depth)."""

    threshold: Share
    share: Share


class SlabThickness(_Group):
    """Least depths [mm]: overall and above the ribs; and when the slab is a composite
    beam's flange."""

    overall: Positive
    aboveRibs: Positive
    beamFlangeOverall: Positive
    beamFlangeAboveRibs: Positive


class SlabDeflection(_Group):
    """Span over the largest deflection: of the deck under its weight and the wet concrete
    (``construction``), of the slab in service (``service``: the construction deflection of an
    unpropped slab plus the composite slab's under the loads after it hardens)."""

    construction: Positive
    service: Positive


class CompositeSlabTable(TableModel):
    """Composite slabs on profiled steel deck (see the module notes). ``longitudinalShear``: the
    methods the pack allows, by the deck tests given (m and k, or τu,Rk)."""

    longitudinalShear: list[Literal["mk", "partialConnection"]] = Field(
        min_length=1, description="Methods of the longitudinal shear the pack allows."
    )
    gammaC: Positive = Field(description="γC of the concrete.")
    gammaAp: Positive = Field(description="γ of the deck's yield strength (γM0).")
    gammaVs: Positive = Field(description="γVs of the longitudinal shear (m-k and τu).")
    gammaG: Positive = Field(description="γG of the construction stage.")
    gammaQ: Positive = Field(description="γQ of the construction stage.")
    concreteShare: Share = Field(description="Plastic block stress = this × fcd.")
    plasticReduction: Positive = Field(
        description="Mpr = this × Mpa (1 - Ncf / Np) <= Mpa (neutral axis in the deck)."
    )
    shearSpanShare: Share = Field(description="Ls = this × L of a uniform load (m-k).")
    wetIncrement: float = Field(
        ge=0, description="Fresh concrete heavier than hardened by this [kN/m³]."
    )
    constructionLoad: SlabConstructionLoad
    ponding: SlabPonding
    thickness: SlabThickness
    deflection: SlabDeflection
    modularFactor: Positive = Field(
        description="n = this × Ea / Ecm for the deflection (short and long term together)."
    )
    antiCrack: tuple[Share, Share] = Field(
        description="Bars above the ribs / the concrete above them: (unpropped, propped)."
    )
    meshMinimum: Positive = Field(description="Least bars each way above the ribs [mm²/m].")
    note: str = ""


__all__ = [
    "CompositeCamber",
    "CompositeLongitudinalShear",
    "CompositeSlabTable",
]

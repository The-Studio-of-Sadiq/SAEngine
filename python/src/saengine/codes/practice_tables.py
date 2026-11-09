"""Table models of the checks a code requires without giving a method (alpha 9 track P7).

The default pack's BNBC 2020 asks for these checks and names no method; the packs give the
method of another code by id (the method's own source, "SAEngine practice where the code is
silent" in a pack whose code gives none) and its values:

- ``floorVibration``: floors under walking. The peak acceleration of a low-frequency floor
  (method ``walkingAcceleration``, the form of AISC Design Guide 11, 2nd ed., Chapter 4) or
  the response factor of a concrete floor (method ``responseFactor``, the form of the
  Concrete Society CCIP-016 and SCI P354: resonant below ``highFrequency``, transient above),
  each against the occupancy's limit (:mod:`saengine.fem.floor_vibration`);
- ``windComfort``: the peak acceleration of the top occupied floor under the wind of a short
  return period (methods ``alongWindGust``, the along-wind form of the ASCE 7 commentary
  C26.11, and ``turbulenceSpectrum``, EN 1991-1-4 Annex B.4), against occupancy limits or
  frequency-dependent curves (:mod:`saengine.fem.wind_comfort`);
- ``nonBuilding``: non-building structures (ASCE 7 Chapter 15 form): the response
  modification coefficient, overstrength and deflection amplification by type, the weight
  share below which a supported structure is a nonstructural component, the rigid period and
  the least seismic coefficient (:mod:`saengine.design.nonbuilding`);
- ``embeddedWalls``: embedded retaining walls of excavations, cantilevered or propped, by
  free or fixed earth support (:mod:`saengine.substructure.embedded_wall`).

The lateral soil failure (Broms) and the p-y analysis of piles are groups of the
``foundations`` table's ``piles.lateral`` (:class:`saengine.codes.tables.PileLateral`).

Every number is the pack's; the pack's VERIFY.md gives each value's source.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.tables import Positive, Share, TableModel, _Group, _Row

# ─────────────────────────────── floorVibration ───────────────────────────────


class FloorOccupancy(_Row):
    """The acceptance of one floor use: the walking acceleration limit ao/g, the response
    factor limit R, and the live load present when the floor vibrates."""

    label: str
    accelerationLimit: Share = Field(description="ao/g of walkingAcceleration (0.005 = 0.5 %).")
    responseLimit: Positive = Field(description="Largest response factor R (responseFactor).")
    serviceLive: float = Field(
        ge=0, description="Live load on the floor while it vibrates [kN/m²]."
    )
    checked: bool = Field(
        default=True, description="False: a use with no walking comfort criterion (parking)."
    )


class WalkingAcceleration(_Group):
    """``walkingAcceleration``: ap/g = P0·exp(-decay·fn) / (β·W), W the effective weight of the
    panel (``panelBays`` × its bay's area × the weight per area), against ao/g of the use.
    Valid from ``minimumFrequency`` to ``maximumFrequency`` [Hz]; outside them the floor is
    reported as not checked by this method."""

    method: Literal["walkingAcceleration"] = "walkingAcceleration"
    force: Positive = Field(description="P0, the constant force of walking [kN].")
    decay: Positive = Field(description="Of exp(-decay·fn).")
    minimumFrequency: Positive = Field(description="fn below this [Hz]: too low a floor.")
    maximumFrequency: Positive = Field(description="fn above this [Hz]: a high-frequency floor.")
    panelBays: Positive = Field(
        default=1.0, description="The effective panel as a multiple of its bay's area."
    )
    damping: dict[str, Share] = Field(description="β by fit-out (bare, ceilings, ...).")


class ResponseFactor(_Group):
    """``responseFactor``: below ``highFrequency`` the resonant response to the walking
    harmonic at fn, a_rms = μ·ρ·W(fn)·r_h·Q / (2√2·M·ζ), ρ = 1 - exp(-2π·ζ·L/stepLength); above
    it the transient response to a footfall impulse I = impulse·fp^impulsePace / fn^impulseFrequency
    · Q/impulseWeight [N·s], v = μ·I/M, a_rms = W(fn)·2π·fn·v·√((1 - e^(-4π ζ fn/fp))/(4π ζ fn/fp));
    R = a_rms / baseAcceleration. M = ``modalShare`` × the panel's mass; W(f) the weighting
    0.5√f below 4 Hz, 1 to 8 Hz, 8/f above."""

    method: Literal["responseFactor"] = "responseFactor"
    walkerWeight: Positive = Field(description="Q, the walker's weight [N].")
    pace: tuple[Positive, Positive] = Field(description="Walking frequency range fp [Hz].")
    harmonics: list[tuple[float, float]] = Field(
        min_length=1,
        description="Per harmonic h = 1, 2, ...: (a, b) of its Fourier coefficient r_h = "
        "a·(h·fp + b).",
    )
    highFrequency: Positive = Field(description="fn at or above this [Hz]: transient.")
    baseAcceleration: Positive = Field(description="R = 1 at this rms acceleration [m/s²].")
    stepLength: Positive = Field(description="Of the resonance build-up ρ [m].")
    modalShare: Share = Field(description="Modal mass over the panel's mass.")
    impulse: Positive = Field(description="Of the footfall impulse [N·s].")
    impulsePace: float = Field(description="Exponent of fp in the impulse.")
    impulseFrequency: float = Field(description="Exponent of fn in the impulse.")
    impulseWeight: Positive = Field(description="Q of the impulse's reference walker [N].")
    damping: dict[str, Share] = Field(description="ζ by fit-out (bare, ceilings, ...).")


class FloorVibrationTable(TableModel):
    """Floors under walking (see the module notes): the method of steel and composite floors
    and of concrete floors, the natural frequency from the floor's deflection, and the
    acceptance of each use."""

    steelMethod: Literal["walkingAcceleration", "responseFactor"] = Field(
        description="Floors on steel beams (composite or not)."
    )
    concreteMethod: Literal["walkingAcceleration", "responseFactor"] = Field(
        description="Reinforced and post-tensioned concrete floors."
    )
    frequencyConstant: Positive = Field(
        description="fn = this·√(g/Δ), Δ the panel's deflection under the vibrating weight."
    )
    walkingAcceleration: WalkingAcceleration | None = None
    responseFactor: ResponseFactor | None = None
    occupancies: dict[str, FloorOccupancy]
    areaUses: dict[str, str] = Field(
        default_factory=dict, description="Area use id -> occupancy id (others: the default)."
    )
    defaultOccupancy: str
    defaultFitOut: str = Field(description="The fit-out (damping key) of a floor that sets none.")
    clauses: dict[str, str] = Field(default_factory=dict)
    compositeDynamicModulus: Positive | None = Field(
        default=None,
        description="Alpha 9 P8: a steel floor on composite beams vibrates on the composite "
        "section with the concrete's modulus × this (full interaction): the panel's deflection "
        "(the analysis carries the steel beams alone) × Is / It,dyn of its composite beams. "
        "None: the analysis deflection as it is.",
    )

    @model_validator(mode="after")
    def _methods(self) -> FloorVibrationTable:
        for method in {self.steelMethod, self.concreteMethod}:
            if getattr(self, method) is None:
                raise ValueError(f"floorVibration: method {method} needs its group")
        if self.defaultOccupancy not in self.occupancies:
            raise ValueError("floorVibration: defaultOccupancy is not an occupancy")
        unknown = sorted(v for v in self.areaUses.values() if v not in self.occupancies)
        if unknown:
            raise ValueError(f"floorVibration: unknown occupancies {', '.join(unknown)}")
        for group in (self.walkingAcceleration, self.responseFactor):
            if group is not None and self.defaultFitOut not in group.damping:
                raise ValueError("floorVibration: defaultFitOut has no damping in a method")
        return self


# ─────────────────────────────── windComfort ───────────────────────────────


class WindComfortTable(TableModel):
    """The peak acceleration of the top occupied floor under the wind of ``returnPeriod``
    years (see the module notes). The speed of that wind is the project's basic wind speed ×
    the ratio of ``speedRatio``: ``logarithmicMri`` V_T / V_50 = a + b·ln(12 T)
    (``mriTerms``), divided by ``referenceToFifty`` (V_ref / V_50 of the pack's basic speed);
    ``probabilityFactor`` cprob = ((1 - K ln(-ln(1 - p))) / (1 - K ln(-ln(1 - p_ref))))^n with
    p = 1 - exp(-1/T) (``probabilityTerms`` (K, n), p_ref of ``referencePeriod``)."""

    response: Literal["alongWindGust", "turbulenceSpectrum"] = Field(
        description="alongWindGust: the wind table's terrain constants (c, ℓ, ε̄, b̄, ᾱ) and "
        "its flexible gust factor's resonant part; turbulenceSpectrum: the wind table's "
        "peak velocity pressure and detailed structural factor constants."
    )
    returnPeriod: Positive = Field(description="Of the comfort wind [years].")
    referencePeriod: Positive = Field(description="Of the pack's basic wind speed [years].")
    speedRatio: Literal["logarithmicMri", "probabilityFactor"]
    mriTerms: tuple[float, float] | None = Field(default=None, description="(a, b).")
    referenceToFifty: Positive = Field(
        default=1.0, description="V_ref / V_50 of the basic wind speed (logarithmicMri)."
    )
    probabilityTerms: tuple[Positive, Positive] | None = Field(default=None, description="(K, n).")
    airDensity: Positive = Field(description="ρ [kg/m³].")
    duration: Positive = Field(description="T of the peak factor [s].")
    peakConstant: Positive = Field(description="g = √(2 ln νT) + this/√(2 ln νT) (0.5772 or 0.6).")
    damping: dict[str, Share] = Field(description="Damping ratio by structure (concrete, steel).")
    acceptance: Literal["occupancyLimits", "frequencyCurve"]
    limits: dict[str, Positive] = Field(
        default_factory=dict, description="occupancyLimits: occupancy -> peak [milli-g]."
    )
    curves: dict[str, list[tuple[Positive, Positive]]] = Field(
        default_factory=dict,
        description="frequencyCurve: occupancy -> (f [Hz], peak [milli-g]) points, linear in "
        "log-log between them, the end values outside.",
    )
    areaUses: dict[str, str] = Field(
        default_factory=dict, description="Area use id -> occupancy id (others: the default)."
    )
    defaultOccupancy: str
    clauses: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _choices(self) -> WindComfortTable:
        if self.speedRatio == "logarithmicMri" and self.mriTerms is None:
            raise ValueError("windComfort: logarithmicMri needs mriTerms")
        if self.speedRatio == "probabilityFactor" and self.probabilityTerms is None:
            raise ValueError("windComfort: probabilityFactor needs probabilityTerms")
        rows = self.limits if self.acceptance == "occupancyLimits" else self.curves
        if self.defaultOccupancy not in rows:
            raise ValueError(f"windComfort: no {self.acceptance} of {self.defaultOccupancy}")
        unknown = sorted(v for v in self.areaUses.values() if v not in rows)
        if unknown:
            raise ValueError(f"windComfort: unknown occupancies {', '.join(unknown)}")
        return self


# ─────────────────────────────── nonBuilding ───────────────────────────────


class NonBuildingType(_Row):
    """A kind of non-building structure and its seismic coefficients."""

    label: str
    R: Positive = Field(description="Response modification coefficient.")
    omega0: Positive = Field(description="Overstrength factor Ω0.")
    Cd: Positive = Field(description="Deflection amplification factor.")
    similar: bool = Field(
        default=False, description="Similar to buildings (designed with the building rules)."
    )


class NonBuildingTable(TableModel):
    """Non-building structures (method ``responseModification``): a structure supported by
    the building whose weight is below ``supportedShare`` of the combined weight is a
    nonstructural component (:mod:`saengine.design.nonstructural`); otherwise, and for one on
    the ground, V = Cs·W with Cs = Sa(T)·I/R of the project's design spectrum, at least
    ``minimumCoefficient`` (a·SDS·I, b), and a rigid one (T below ``rigidPeriod``) V =
    ``rigidFactor``·SDS·I·W, SDS the spectrum's short-period plateau."""

    method: Literal["responseModification"] = "responseModification"
    types: dict[str, NonBuildingType] = Field(min_length=1)
    supportedShare: Share = Field(description="Wp / (Wp + Ws) below this: a component.")
    rigidPeriod: Positive = Field(description="T below this [s]: rigid.")
    rigidFactor: Positive = Field(description="V = this·SDS·I·W of a rigid structure.")
    minimumCoefficient: tuple[float, float] = Field(description="Cs ≥ a·SDS·I and ≥ b.")
    clauses: dict[str, str] = Field(default_factory=dict)


# ─────────────────────────────── embeddedWalls ───────────────────────────────


class EmbeddedWallsTable(TableModel):
    """Embedded retaining walls of an excavation, per metre run: Rankine earth pressures of
    the nearest borehole's layers (drained c'-φ', undrained cu, water on both sides), active
    behind, passive in front below the dig level (lowered by the overdig).

    - ``factoredPassive``: the passive pressure divided by ``passiveFactor``, the other
      pressures and the surcharge as they are;
    - ``partialFactors``: tan φ', c' and cu divided by the pack's ``geotechnicalMethods``
      materials set ``materials``, the surcharge × ``variableFactor``.

    Cantilever walls and propped walls on fixed earth support take the embedment d0 of the
    moment balance (about the toe, Blum's simplification; for the fixed earth support, the
    equivalent beam below the point of zero net pressure) × ``embedmentIncrease``; propped
    walls on free earth support the d0 of moments about the prop × ``freeEarthIncrease``."""

    method: Literal["factoredPassive", "partialFactors"]
    passiveFactor: Positive = Field(default=1.0, description="factoredPassive: Kp / this.")
    materials: str | None = Field(
        default=None, description="partialFactors: the geotechnicalMethods materials set."
    )
    variableFactor: Positive = Field(default=1.0, description="On the surcharge.")
    embedmentIncrease: Positive = Field(description="d = this × d0 (cantilever, fixed earth).")
    freeEarthIncrease: Positive = Field(default=1.0, description="d = this × d0 (free earth).")
    minimumSurcharge: float = Field(ge=0, description="Least surcharge behind the wall [kPa].")
    overdigShare: float = Field(
        ge=0, lt=1, description="Unplanned excavation: this × the retained height ..."
    )
    overdigMax: float = Field(ge=0, description="... at most this [m].")
    clauses: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _materials(self) -> EmbeddedWallsTable:
        if self.method == "partialFactors" and not self.materials:
            raise ValueError("embeddedWalls: partialFactors needs a materials set")
        return self


__all__ = [
    "EmbeddedWallsTable",
    "FloorOccupancy",
    "FloorVibrationTable",
    "NonBuildingTable",
    "NonBuildingType",
    "ResponseFactor",
    "WalkingAcceleration",
    "WindComfortTable",
]

"""Table models of the bridges and special structures of alpha 9 track L9 (each a method a pack
chooses by id; :mod:`saengine.special` computes them):

- ``movingLoads`` (:mod:`saengine.special.moving_loads`): the code's traffic load models as data:
  vehicles (axles and their spacings), the load each lane carries (a vehicle, a line load along
  the lane, a load per m² of the lane), the notional lane width, the multiple presence factors
  and the dynamic allowance (a constant share, a span formula, or included in the loads);
- ``bridgeDesign`` (:mod:`saengine.special.bridges`): the load factors of the girders' strength
  and service checks, the prestressed girders' stress limits and the load rating factors;
- ``latticeTowers`` (:mod:`saengine.special.towers`): the force coefficient of a lattice tower's
  face by its solidity ratio (a quadratic in ε, or the 1.76 C1 (1 - C2 ε + ε²) form), the round
  member and diagonal wind factors, the gust factor and the members' effective lengths;
- ``shellStructures`` (:mod:`saengine.special.shells`): silos (Janssen pressures with the stored
  solids' properties and the discharge factors), chimneys (vortex shedding) and cooling towers
  (the wind pressure distribution around a circular cylinder);
- ``offshore`` (:mod:`saengine.special.offshore`): Morison's drag and inertia coefficients, the
  wave kinematics and current blockage factors and the load factors of the member checks;
- ``pipingStress`` (:mod:`saengine.special.piping`): the pipe materials' allowable stresses, the
  stress range factor and the sustained, expansion and occasional limits.

A pack without a table does not cover the feature (the report says so), except the traffic
loads and the bridge load factors: a pack without them takes SAEngine's practice data on the
HL-93 basis (:mod:`saengine.special.practice`), named as such in the results. Every number is
the pack's; its VERIFY.md gives the clauses.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.tables import Positive, Share, TableModel, _Group

# ───────────────────────────────────── movingLoads ─────────────────────────────────────


class VehicleAxle(_Group):
    """One axle of a vehicle (both wheels)."""

    load: Positive = Field(description="Axle load [kN].")
    spacing: float = Field(
        default=0.0, ge=0, description="From the axle before it [m] (the first axle: 0)."
    )
    spacingMax: Positive | None = Field(
        default=None,
        description="A variable spacing: from ``spacing`` up to this [m]; the spacing that "
        "gives the extreme effect is taken.",
    )


class Vehicle(_Group):
    """A design vehicle or axle group: its axles from the front, and the wheel gauge."""

    label: str
    axles: list[VehicleAxle] = Field(min_length=1)
    gauge: Positive = Field(default=1.8, description="Between the wheel lines [m].")


class LaneLoading(_Group):
    """What one lane carries: a vehicle (optionally a second one behind it, as two trucks for
    the hogging moments), a line load along the lane and a load per m² of the lane's width."""

    vehicle: str | None = Field(default=None, description="Id in ``vehicles``.")
    vehicleFactor: Positive = Field(default=1.0, description="On the vehicle's axle loads.")
    secondGap: Positive | None = Field(
        default=None,
        description="A second vehicle behind the first, at least this far apart [m] (front "
        "axle to rear axle); none: one vehicle.",
    )
    lineLoad: float = Field(default=0.0, ge=0, description="Along the lane [kN/m].")
    areaLoad: float = Field(default=0.0, ge=0, description="Over the lane's width [kN/m²].")
    lineFactor: Positive = Field(default=1.0, description="On the line and area loads.")
    dynamic: bool = Field(default=True, description="The dynamic allowance applies to the vehicle.")


class LoadModel(_Group):
    """A traffic load model: what lane 1, lane 2, ... carry (the last entry repeats for further
    lanes), how many lanes it may load, and which effects it is for."""

    label: str
    lanes: list[LaneLoading] = Field(min_length=1)
    maxLanes: int | None = Field(default=None, ge=1, description="Lanes it loads, at most.")
    multiplePresence: bool = Field(default=True, description="The multiple presence factors apply.")
    only: Literal["all", "hogging"] = Field(
        default="all",
        description="'hogging': only for the negative moments and the interior support "
        "reactions (two trucks).",
    )


class DynamicAllowance(_Group):
    """How the vehicles' loads are increased for their dynamic effect: ``constant`` (1 + this
    share), ``spanFormula`` (1 + a / (b + L), L the span [m], by material, at most ``cap``) or
    ``included`` (the load model's values include it)."""

    method: Literal["constant", "spanFormula", "included"]
    constant: float = Field(default=0.0, ge=0, description="The share added (0.33: 33 %).")
    formula: dict[str, tuple[Positive, Positive]] = Field(
        default_factory=dict,
        description="(a, b) of a / (b + L) by girder material ('concrete', 'steel').",
    )
    cap: float | None = Field(default=None, gt=0, description="The share added, at most.")


class MovingLoadsTable(TableModel):
    """Traffic loads on bridges as lane load models (the code's design vehicles and lane loads,
    its notional lane width and multiple presence factors, its dynamic allowance)."""

    method: Literal["laneLoadModels"] = "laneLoadModels"
    laneWidth: Positive = Field(description="Width of a design (notional) lane [m].")
    narrow: list[tuple[Positive, int]] = Field(
        default_factory=list,
        description="(width, lanes): a carriageway narrower than the width has that many "
        "lanes (in increasing width); wider: the whole lanes of laneWidth that fit.",
    )
    vehicles: dict[str, Vehicle] = Field(min_length=1)
    loadModels: dict[str, LoadModel] = Field(min_length=1)
    multiplePresence: list[Positive] = Field(
        min_length=1,
        description="Factor with 1, 2, 3, ... lanes loaded (the last repeats).",
    )
    dynamic: DynamicAllowance

    @model_validator(mode="after")
    def _vehicles_known(self) -> MovingLoadsTable:
        for key, model in self.loadModels.items():
            for lane in model.lanes:
                if lane.vehicle is not None and lane.vehicle not in self.vehicles:
                    raise ValueError(f"loadModels.{key}: no vehicle '{lane.vehicle}'")
        return self


# ───────────────────────────────────── bridgeDesign ─────────────────────────────────────


class BridgeLoadFactors(_Group):
    """Load factors of the components (DC), the wearing surface and utilities (DW) and the
    traffic with its dynamic allowance (LL)."""

    dc: Positive
    dw: Positive
    ll: Positive


class BridgeRating(_Group):
    """Load rating RF = (C - γDC DC - γDW DW) / (γL (LL + IM)), C = φc φs φ Rn."""

    dc: Positive
    dw: Positive
    dwMeasured: Positive | None = Field(
        default=None, description="γDW when the wearing surface was measured."
    )
    inventory: Positive = Field(description="γL at the inventory level.")
    operating: Positive = Field(description="γL at the operating level.")
    systemMin: Share = Field(default=0.85, description="φc φs, at least this.")


class BridgePrestress(_Group):
    """Stress limits of prestressed girders: compression as shares of f'ci or f'c, tension as
    coefficients of the root of the strength or as stresses (``tensionForm``)."""

    transferCompression: Share = Field(description="At transfer: compression <= this f'ci.")
    transferTension: float = Field(ge=0, description="At transfer: tension <= this.")
    permanentCompression: Share = Field(
        description="Service, permanent loads: compression <= this f'c."
    )
    totalCompression: Share = Field(description="Service, all loads: compression <= this f'c.")
    serviceTension: float = Field(ge=0, description="Service: tension <= this.")
    tensionForm: Literal["root", "absolute"] = Field(
        default="root", description="'root': coefficient × √f'c [MPa]; 'absolute': MPa."
    )
    relaxedYield: Share = Field(default=0.9, description="fpy = this fpu (low relaxation).")


class BridgeDesignTable(TableModel):
    """The bridge girders' checks: strength and service load factors, the prestressed girders'
    stress limits and the load rating of existing bridges. The resistances are the pack's
    concrete methods (its φ or partial factors)."""

    method: Literal["loadFactors"] = "loadFactors"
    strength: BridgeLoadFactors
    service: BridgeLoadFactors
    tensionLive: Positive | None = Field(
        default=None,
        description="Factor on the traffic in the prestressed girders' service tension check "
        "(none: the service factor).",
    )
    prestress: BridgePrestress | None = None
    rating: BridgeRating | None = None
    thermalCoefficient: Positive = Field(
        default=1.0e-5, description="α of the deck for its expansion joints [1/°C]."
    )


# ───────────────────────────────────── latticeTowers ─────────────────────────────────────


class Quadratic(_Group):
    """a ε² + b ε + c."""

    a: float
    b: float
    c: float


class AnnexBForm(_Group):
    """cf,0 = base C1 (1 - C2 ε + ε²) by cross-section."""

    base: Positive
    square: tuple[Positive, Positive] = Field(description="(C1, C2) of square towers.")
    triangular: tuple[Positive, Positive] = Field(description="(C1, C2) of triangular towers.")


class TowerLengths(_Group):
    """Effective length factors K of the tower's members."""

    legs: Positive
    bracing: Positive


class LatticeTowersTable(TableModel):
    """Lattice towers: the face's force coefficient by its solidity ratio ε (``quadratic``: a ε²
    + b ε + c by cross-section, × the round member factor; ``annexB``: base C1 (1 - C2 ε + ε²)),
    the factor of a square tower's wind on the diagonal (base + k ε, at most the cap), the gust
    factor on the velocity pressure, and the effective length factors."""

    method: Literal["quadratic", "annexB"]
    squareTower: Quadratic | None = None
    triangularTower: Quadratic | None = None
    roundTower: Quadratic | None = Field(
        default=None, description="Round members: × (a ε² + b ε + c), at most 1."
    )
    annexB: AnnexBForm | None = None
    diagonalFactor: tuple[float, Positive] = Field(
        description="(k, cap): a square tower's wind on its diagonal × (base + k ε) <= cap."
    )
    diagonalBase: Positive = Field(default=1.0, description="The base of the diagonal factor.")
    gust: Positive = Field(description="Gust effect factor on the velocity pressure.")
    lengths: TowerLengths
    antennaShielding: Share = Field(
        default=1.0, description="On the antennas' effective projected areas."
    )

    @model_validator(mode="after")
    def _method_data(self) -> LatticeTowersTable:
        if self.method == "quadratic" and (
            self.squareTower is None or self.triangularTower is None
        ):
            raise ValueError("method 'quadratic' needs squareTower and triangularTower")
        if self.method == "annexB" and self.annexB is None:
            raise ValueError("method 'annexB' needs annexB")
        return self


# ───────────────────────────────────── shellStructures ─────────────────────────────────────


class StoredSolid(_Group):
    """A stored particulate solid: its upper unit weight, angle of internal friction, mean
    lateral pressure ratio and wall friction coefficients by wall type, with the conversion
    factors to their extreme values."""

    label: str
    weight: Positive = Field(description="Upper characteristic unit weight γu [kN/m³].")
    phi: Positive = Field(description="Mean angle of internal friction φim [°].")
    k: Positive = Field(description="Mean lateral pressure ratio Km.")
    aK: Positive = Field(description="Conversion factor of K (upper Km aK, lower Km / aK).")
    mu: dict[str, Positive] = Field(description="Mean wall friction μm by wall type.")
    aMu: Positive = Field(description="Conversion factor of μ.")


class SiloRules(_Group):
    """Silo pressures by Janssen's theory: on filling ph(z) = γ K z0 (1 - e^(-z/z0)), z0 =
    A / (K μ U), pw = μ ph; on discharge × the discharge factors."""

    method: Literal["janssen"] = "janssen"
    solids: dict[str, StoredSolid] = Field(min_length=1)
    dischargeHorizontal: Positive = Field(description="Ch on the horizontal pressure.")
    dischargeFriction: Positive = Field(description="Cw on the wall friction.")
    loadFactor: Positive = Field(description="γF of the stored solid's pressures.")


class ChimneyRules(_Group):
    """Vortex shedding of circular chimneys: the critical speed vcrit = b n / St, the Scruton
    number Sc = 2 δs m / (ρ b²) and the largest cross-wind amplitude yF = b K Kw clat /
    (St² Sc) (the effective correlation length method)."""

    method: Literal["correlationLength"] = "correlationLength"
    strouhal: Positive
    modeFactor: Positive = Field(description="K of the first cantilever mode.")
    kwMax: Positive = Field(description="Kw at most.")
    lateral: list[tuple[Positive, Positive]] = Field(
        min_length=2, description="(Re, clat,0) points; log-linear in Re between."
    )
    correlation: tuple[Positive, Positive, Positive] = Field(
        description="(Lj/b below yF/b 0.1, slope of 4.8 + this yF/b up to 0.6, Lj/b above)."
    )
    damping: dict[str, Positive] = Field(
        min_length=1, description="Structural logarithmic decrement δs by kind of chimney."
    )
    speedMargin: Positive = Field(
        description="Vortex shedding needs checking where vcrit < this × the mean speed."
    )
    airDensity: Positive = Field(default=1.25, description="[kg/m³].")
    kinematicViscosity: Positive = Field(default=1.5e-5, description="ν of air [m²/s].")
    loadFactor: Positive = Field(description="γQ of the wind and vortex shedding forces.")


class CylinderPressureRow(_Group):
    """The pressure distribution around a circular cylinder at one Reynolds number."""

    reynolds: Positive
    alphaMin: Positive = Field(description="Angle of the least pressure [°].")
    cpMin: float = Field(lt=0)
    alphaA: Positive = Field(description="Angle of flow separation [°].")
    cpBase: float = Field(lt=0, description="Base pressure behind the separation.")


class CoolingTowerRules(_Group):
    """Wind on cooling tower shells: the external pressure around the circumference (1 at the
    windward line, the least at αmin, the base pressure from αA, SAEngine's cos² shape between
    the code's points) and the internal suction."""

    method: Literal["cylinderDistribution"] = "cylinderDistribution"
    rows: list[CylinderPressureRow] = Field(min_length=1)
    internal: float = Field(le=0, description="Internal pressure coefficient (suction).")
    loadFactor: Positive = Field(description="γQ of the wind.")


class ShellStructuresTable(TableModel):
    """Silos, chimneys and cooling towers: the loads the code gives for them (the shells are
    designed by the pack's concrete or steel methods)."""

    silos: SiloRules | None = None
    chimneys: ChimneyRules | None = None
    coolingTowers: CoolingTowerRules | None = None


# ───────────────────────────────────── offshore ─────────────────────────────────────


class OffshoreTable(TableModel):
    """Fixed offshore structures: Morison's equation f = ½ ρ Cd D |u| u + ρ Cm π D²/4 a on the
    members' normal velocities and accelerations of the wave (× the kinematics factor) and the
    current (× the blockage factor), and the load factors of the member checks (the members are
    designed by the pack's steel methods)."""

    method: Literal["morison"] = "morison"
    seawaterDensity: Positive = Field(description="[kg/m³].")
    dragSmooth: Positive
    dragRough: Positive
    inertiaSmooth: Positive
    inertiaRough: Positive
    kinematicsFactor: Share = Field(description="On the wave's horizontal velocities.")
    blockage: dict[str, Share] = Field(
        description="Current blockage factor by the number of legs ('1': a monopile)."
    )
    currentExponent: Positive = Field(
        default=1 / 7, description="The current's profile ((z + d) / d) to this power."
    )
    permanentFactor: Positive = Field(description="γ of the permanent loads.")
    environmentalFactor: Positive = Field(description="γ of the wave, current and wind.")


# ───────────────────────────────────── pipingStress ─────────────────────────────────────


class PipeMaterial(_Group):
    """A pipe material: its basic allowable stress by temperature, modulus, expansion and
    density."""

    label: str
    allowable: list[tuple[float, Positive]] = Field(
        min_length=1, description="(temperature °C, S MPa), linear between."
    )
    modulus: Positive = Field(description="E at installation [MPa].")
    expansion: Positive = Field(description="Mean expansion coefficient [1/°C].")
    density: Positive = Field(default=7850, description="[kg/m³].")


class PipingStressTable(TableModel):
    """Piping flexibility and stress: sustained SL <= Sh, expansion SE <= SA = f (rangeShares[0]
    Sc + rangeShares[1] Sh) (+ Sh - SL when ``liberal``), occasional SL + Socc <= k Sh, f =
    coefficient N^exponent at most rangeFactorMax; the pressure design thickness t = P D / (2 (S
    E W + P Y))."""

    method: Literal["allowableRange"] = "allowableRange"
    materials: dict[str, PipeMaterial] = Field(min_length=1)
    rangeCoefficient: Positive
    rangeExponent: float = Field(lt=0)
    rangeFactorMax: Positive
    rangeShares: tuple[Positive, Positive]
    liberal: bool = True
    sustainedIndex: Share = Field(description="Sustained SIF = this × i, at least 1.")
    occasionalFactor: Positive
    pressureY: Positive
    elbowFlexibility: Positive = Field(description="k = this / h.")
    elbowInPlane: Positive = Field(description="ii = this / h^(2/3), at least 1.")
    elbowOutPlane: Positive = Field(description="io = this / h^(2/3), at least 1.")

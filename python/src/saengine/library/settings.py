"""Project settings (``02 Project Settings/project-settings.json``): codes, occupancy, site and loads.

Part 2 is upstream of the floor plan, the building model and the analysis: they read these
settings and never write them. BNBC 2020 is the governing code; its tables (see
:mod:`saengine.library.bnbc`) give the defaults, and every derived value can be overridden.

Units: kN/m² for area loads, m/s for wind speed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.codes import context as code_context
from saengine.codes.manifest import PACK_ID_PATTERN
from saengine.codes.registry import DEFAULT_PACK, CodePack, CodePackError
from saengine.library import bnbc
from saengine.library.labels import field_title
from saengine.library.materials import Id

SCHEMA_ID = "saengine.projectSettings/1"

Pressure = Annotated[float, Field(ge=0, description="[kN/m²]")]

LocationId = Literal[tuple(bnbc.LOCATIONS) + ("custom",)]  # type: ignore[valid-type]
AreaUseId = Literal[tuple(bnbc.AREA_USES) + ("custom",)]  # type: ignore[valid-type]
SystemId = Literal[tuple(bnbc.STRUCTURAL_SYSTEMS)]  # type: ignore[valid-type]


def _labels(names: list[str]) -> dict[str, Any]:
    """Readable names of an enum's values for the editors (JSON Schema ``enumDescriptions``)."""
    return {"enumDescriptions": names}


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class ProjectInfo(_Model):
    name: str = Field(min_length=1)
    number: str | None = Field(default=None, title="Project number")
    client: str | None = None
    engineer: str | None = Field(default=None, title="Structural engineer")
    address: str | None = None
    language: Literal["en", "bn"] = Field(
        default="en",
        title="Language",
        description="Language of the reports and drawings: labels, headings and notes, with "
        "Bengali digits in Bangla. Units, symbols and code clause numbers stay as they are. "
        "SAEngine's own screens follow the display language, which Project offers to match.",
        json_schema_extra=_labels(["English", "বাংলা (Bangla)"]),
    )


class Codes(_Model):
    """Deprecated: the design code is the code pack (codePack); the report states the labels of
    its basis. Old files keep validating; the value is not read and not written back."""

    general: Literal["BNBC 2020"] = Field(default="BNBC 2020", title="Loads and general")
    concrete: Literal["BNBC 2020 Part 6 Chapter 6", "ACI 318-19"] = "BNBC 2020 Part 6 Chapter 6"
    steel: Literal["BNBC 2020 Part 6 Chapter 10", "AISC 360-22"] = "BNBC 2020 Part 6 Chapter 10"
    method: Literal["strength"] = Field(
        default="strength", title="Design method", description="Strength design (LRFD)."
    )


class Occupancy(_Model):
    use: Literal[
        "residential",
        "office",
        "educational",
        "healthcare",
        "assembly",
        "retail",
        "industrial",
        "storage",
        "parking",
        "mixed",
    ] = Field(
        default="residential",
        title="Building use",
        json_schema_extra=_labels(
            [
                "Residential",
                "Office",
                "Educational",
                "Health care",
                "Assembly",
                "Retail",
                "Industrial",
                "Storage",
                "Parking",
                "Mixed use",
            ]
        ),
    )
    cycloneShelter: bool = Field(
        default=False,
        title="Cyclone shelter",
        description="The building is a cyclone shelter: its live loads are never reduced where "
        "the code pack says so (liveReduction.notReducedBuildings).",
    )
    category: Literal["I", "II", "III", "IV"] = Field(
        default="II",
        title="Occupancy category",
        description="BNBC 2020 Table 6.1.1.",
        json_schema_extra=_labels(
            [f"{k}: {v.description}" for k, v in bnbc.OCCUPANCY_CATEGORIES.items()]
        ),
    )


class Site(_Model):
    location: LocationId = Field(  # type: ignore[valid-type]
        default="dhaka",
        description="District town (BNBC 2020 Tables 6.2.8 and 6.2.15); sets the seismic zone "
        "and the basic wind speed. Open the list and type the first letters to find a town; "
        "elsewhere choose Custom and enter Z and V.",
        json_schema_extra=_labels(
            [
                f"{v.name} (zone {v.zone}, Z {bnbc.ZONE_COEFFICIENT[v.zone]:.2f}, "
                f"V {v.wind_speed:g} m/s)"
                for v in bnbc.LOCATIONS.values()
            ]
            + ["Custom (enter Z and V)"]
        ),
    )
    siteClassSource: Literal["soilReport", "entered"] = Field(
        default="soilReport",
        title="Site class source",
        description="From the soil report: the governing (softest) site class of the boreholes "
        "of 1 Soil Report; the entered class is used while the report gives none.",
        json_schema_extra=_labels(["From the soil report", "Entered"]),
    )
    siteClass: Literal["SA", "SB", "SC", "SD", "SE"] = Field(
        default="SD",
        title="Site class",
        description="BNBC 2020 Table 6.2.13. Used when the source is Entered, or while the soil "
        "report has no boreholes that give a class.",
        json_schema_extra=_labels([f"{k}: {v}" for k, v in bnbc.SITE_CLASSES.items()]),
    )
    zoneCoefficient: float | None = Field(
        default=None,
        gt=0,
        lt=1,
        title="Seismic zone coefficient Z",
        description="Overrides the location's value (BNBC 2020 Table 6.2.14: 0.12, 0.20, "
        "0.28 or 0.36 by zone).",
    )
    windSpeed: float | None = Field(
        default=None,
        gt=0,
        title="Basic wind speed",
        description="Overrides the location's value [m/s] (BNBC 2020 Table 6.2.8).",
    )


class AdjacentStructure(_Model):
    name: str = Field(min_length=1, description="The adjacent building or unit.")
    gap: float = Field(ge=0, title="Gap", description="Clear distance [mm] to it.")
    displacement: float = Field(
        default=0.0,
        ge=0,
        title="Its maximum displacement",
        description="Its computed maximum horizontal displacement [mm] at the levels facing "
        "this building (0: not known).",
    )
    sameProperty: bool = Field(
        default=True,
        title="Same property",
        description="It belongs to the same property (another unit of this building). Not on "
        "the same property, the gap counts to the property line.",
    )
    sameFloorLevels: bool = Field(
        default=False,
        title="Same floor levels",
        description="Its floors are at the same elevations as this building's.",
    )


class Seismic(_Model):
    system: SystemId = Field(  # type: ignore[valid-type]
        default="rcSmf",
        title="Structural system",
        description="Seismic force-resisting system (Table 6.2.19). It gives R, Ω0 and Cd and "
        "the seismic detailing of the members; it must be permitted in the Seismic Design "
        "Category of the site (Table 6.2.18).",
        json_schema_extra=_labels([v.name for v in bnbc.STRUCTURAL_SYSTEMS.values()]),
    )
    r: float | None = Field(
        default=None,
        gt=0,
        title="Response reduction factor R",
        description="Overrides the system's value.",
    )
    omega: float | None = Field(
        default=None,
        gt=0,
        title="Overstrength factor Ω0",
        description="Overrides the system's value.",
    )
    cd: float | None = Field(
        default=None,
        gt=0,
        title="Deflection amplification Cd",
        description="Overrides the system's value.",
    )
    # ── B2: combinations of systems, damping, drift table rows, diaphragms and separation ──
    systemY: SystemId | None = Field(  # type: ignore[valid-type]
        default=None,
        title="Structural system in Y",
        description="A different seismic force-resisting system along Y: its own R, Ω0 and Cd "
        "apply in Y, with its limitations. Empty: the structural system above in both "
        "directions.",
        json_schema_extra=_labels([v.name for v in bnbc.STRUCTURAL_SYSTEMS.values()]),
    )
    otherSystems: list[SystemId] = Field(  # type: ignore[valid-type]
        default_factory=list,
        title="Other systems in X",
        description="Other seismic force-resisting systems that resist the forces along X "
        "together with the structural system (beside it or in other storeys), other than a "
        "dual system: R is the least of them, Cd and Ω0 the largest, and the most stringent "
        "height limit applies. Without a system in Y they apply in Y too.",
    )
    otherSystemsY: list[SystemId] = Field(  # type: ignore[valid-type]
        default_factory=list,
        title="Other systems in Y",
        description="The same along Y, with a structural system in Y.",
    )
    damping: float | None = Field(
        default=None,
        gt=0,
        lt=0.5,
        title="Viscous damping ratio ξ",
        description="Damping of the structure as a ratio of critical (0.05 for 5 %). The design "
        "spectrum is corrected by the code's damping factor η. Empty: the code's reference "
        "damping (5 %, η = 1).",
    )
    driftTolerantFinishes: bool = Field(
        default=False,
        title="Finishes designed for the storey drift",
        description="The interior walls, partitions, ceilings and exterior walls are designed to "
        "accommodate the storey drifts: a building of few storeys may take the larger "
        "allowable drift of the code's drift table.",
    )
    cantileverMasonryWalls: bool = Field(
        default=False,
        title="Masonry walls cantilevered",
        description="Masonry shear walls cantilevered from their base, with negligible coupling "
        "between them: the drift table's row for masonry cantilever shear walls.",
    )
    diaphragmDeflectionLimit: float | None = Field(
        default=None,
        gt=0,
        title="Permissible diaphragm deflection",
        description="In-plane deflection [mm] the elements attached to the floors (walls, "
        "partitions, cladding) can take while keeping their integrity. The diaphragm "
        "deflection is checked against it; empty: it is reported only.",
    )
    propertyLineGap: float | None = Field(
        default=None,
        ge=0,
        title="Gap to the property line",
        description="Least distance [mm] from the building to the property line. It must be at "
        "least the building's computed maximum displacement.",
    )
    adjacent: list[AdjacentStructure] = Field(
        default_factory=list,
        title="Adjacent structures",
        description="Other buildings or structurally independent units next to this one, for "
        "the separation check against pounding.",
    )


class Wind(_Model):
    exposure: Literal["A", "B", "C"] = Field(
        default="A",
        description="Exposure category (6.2.9.3).",
        json_schema_extra=_labels([f"{k}: {v}" for k, v in bnbc.EXPOSURES.items()]),
    )
    directionality: float | None = Field(
        default=None,
        gt=0,
        le=1,
        title="Directionality factor Kd",
        description="Overrides the code's value for buildings (BNBC 2020 Table 6.2.12).",
    )
    topographic: float | None = Field(
        default=None,
        ge=1,
        title="Topographic factor Kzt",
        description="Overrides the code's value for flat terrain; above 1 on hills, ridges and "
        "escarpments (BNBC 2020 Sec 2.4.7).",
    )
    gust: float | None = Field(
        default=None,
        gt=0,
        title="Gust effect factor G",
        description="Overrides the code's value for every building (BNBC 2020 Sec 2.4.8.1). "
        "Left empty, a flexible building (natural frequency below 1 Hz) gets Gf of Sec 2.4.8.2 "
        "from its modal frequency.",
    )
    naturalFrequency: float | None = Field(
        default=None,
        gt=0,
        title="Natural frequency n1",
        description="The building's fundamental natural frequency [Hz] for the gust-effect "
        "factor (BNBC 2020 Sec 2.4.8.2). Empty: from the modal analysis of the model, in each "
        "wind direction.",
    )
    damping: float | None = Field(
        default=None,
        gt=0,
        lt=0.2,
        title="Damping ratio β",
        description="Damping ratio of the gust-effect factor Gf (BNBC 2020 Sec 2.4.8.2). "
        "Empty: the code pack's (0.02, a concrete building; 0.01 for steel).",
    )
    enclosure: Literal["enclosed", "partiallyEnclosed", "open"] = Field(
        default="enclosed",
        title="Enclosure",
        description="Enclosure classification for the internal pressure (GCpi) of the "
        "components and cladding (BNBC 2020 Sec 2.4.2 and Figure 6.2.5).",
        json_schema_extra=_labels(
            ["Enclosed (GCpi ±0.18)", "Partially enclosed (GCpi ±0.55)", "Open (GCpi 0)"]
        ),
    )
    claddingArea: float | None = Field(
        default=None,
        gt=0,
        title="Cladding effective wind area",
        description="Effective wind area [m²] of the cladding element checked (a glazing panel, "
        "a wall panel: span × the larger of its width and span/3). Empty: the smallest area "
        "of the figures, the largest pressures.",
    )
    parapetHeight: float | None = Field(
        default=None,
        ge=0,
        title="Parapet height",
        description="Height of the roof parapet [m]. One of 0.9 m or more turns roof zone 3 "
        "into zone 2; the parapet's own pressures are given too.",
    )
    openStructure: OpenStructureWind = Field(
        default_factory=lambda: OpenStructureWind(),
        title="Open structures",
        description="Wind on the members of a special structure (trusses, frames, towers, "
        "canopy frames): F = qz·G·Cf·Af on each member (BNBC 2020 Part 6 Sec 2.4, other "
        "structures).",
    )


class OpenStructureWind(_Model):
    """Wind on the members of a special structure by force coefficients (BNBC 2020 Part 6 Sec
    2.4, design wind loads on other structures: open signs and lattice frameworks, trussed
    towers; :mod:`saengine.fem.open_wind`)."""

    form: Literal["lattice", "squareTower", "triangularTower", "none"] = Field(
        default="lattice",
        description="Lattice: an open framework (trusses, frames); towers: Cf of a trussed "
        "tower's face; none: no wind on special structures.",
        json_schema_extra=_labels(
            ["Lattice framework", "Square trussed tower", "Triangular trussed tower", "None"]
        ),
    )
    solidity: float | None = Field(
        default=None,
        gt=0,
        le=1,
        title="Solidity ratio ε",
        description="Solid area over gross area of the face. Empty: from the model, in each "
        "wind direction (the members' projected area over their projected outline).",
    )
    roundMembers: bool = Field(
        default=False,
        title="Rounded members",
        description="Members are round (pipes, rods): the rounded-member coefficients.",
    )


class CraneRunway(_Model):
    """A bridge or monorail crane on a pair of runway beams (the code pack's ``cranes`` table;
    :mod:`saengine.fem.cranes`). Weights are in kN, lengths in mm."""

    id: Id
    name: str = ""
    kind: Literal["cabOperated", "remoteOperated", "pendantOperated", "handGeared", "monorail"] = (
        Field(
            default="pendantOperated",
            description="Sets the impact and horizontal forces (the code pack's crane table).",
            json_schema_extra=_labels(
                [
                    "Cab-operated bridge crane",
                    "Remotely operated bridge crane",
                    "Pendant-operated bridge crane",
                    "Manually operated (hand-geared) crane",
                    "Powered monorail",
                ]
            ),
        )
    )
    capacity: float = Field(gt=0, description="Rated capacity [kN].")
    bridgeWeight: float = Field(ge=0, title="Bridge weight", description="Crane bridge [kN].")
    trolleyWeight: float = Field(
        ge=0, title="Hoist and trolley weight", description="Hoist and trolley [kN]."
    )
    span: float = Field(gt=0, description="Between the rail centre lines [mm].")
    hookApproach: float = Field(
        default=1000,
        ge=0,
        title="Hook approach",
        description="Closest the hook comes to a rail [mm].",
    )
    wheels: int = Field(default=2, ge=1, le=4, description="Wheels on each rail.")
    wheelBase: float = Field(
        default=3000, ge=0, title="Wheel base", description="Between the wheels on a rail [mm]."
    )
    runwaySpan: float = Field(
        gt=0,
        title="Runway beam span",
        description="Between the columns (the bay), simply supported runway beams [mm].",
    )
    railLevel: float | None = Field(
        default=None, title="Rail level", description="Top of the rail [mm], for the report."
    )
    beamType: Id | None = Field(
        default=None,
        title="Runway beam type",
        description="Steel beam type of the runway beams, checked for the wheel loads; empty: "
        "loads only.",
    )
    runwayAxis: Literal["X", "Y"] | None = Field(
        default=None,
        title="Runway direction",
        description="Plan axis the runway beams run along; with both column lines, the crane "
        "loads are applied to the frames as moving load cases. Empty: loads only.",
    )
    columnLineA: float | None = Field(
        default=None,
        title="Column line A",
        description="Plan coordinate across the runway of the first line of crane columns [mm] "
        "(y for a runway along X).",
    )
    columnLineB: float | None = Field(
        default=None,
        title="Column line B",
        description="Plan coordinate across the runway of the second line of crane columns [mm]; "
        "the rails are centred between the lines, 'span' apart (the bracket eccentricity).",
    )
    runwayStart: float | None = Field(
        default=None,
        title="Runway start",
        description="Along the runway, first column coordinate it covers [mm] (empty: all).",
    )
    runwayEnd: float | None = Field(
        default=None,
        title="Runway end",
        description="Along the runway, last column coordinate it covers [mm] (empty: all).",
    )
    fatigueCategory: str | None = Field(
        default=None,
        title="Fatigue stress category",
        description="Stress category of the runway beam's governing detail (the code pack's "
        "fatigue table, e.g. A, B, B', C, D, E, E', F). Empty: no fatigue check.",
    )
    cyclesPerDay: float = Field(
        default=0,
        ge=0,
        title="Load cycles per day",
        description="Crane passes (stress range fluctuations) a day, for the fatigue check.",
    )
    designLife: float = Field(
        default=50,
        gt=0,
        title="Design life",
        description="Years of service, for the number of fatigue cycles.",
    )


class Pushover(_Model):
    """Nonlinear static (pushover) analyses of the frames, with fiber sections."""

    directions: list[Literal["X", "Y"]] = Field(
        default_factory=lambda: ["X", "Y"], min_length=1, description="Directions to push in."
    )
    pattern: Literal["seismic", "uniform"] = Field(
        default="seismic",
        title="Load pattern",
        description="How the lateral load is spread over the height.",
        json_schema_extra=_labels(
            [
                "Seismic (BNBC story forces, growing with height)",
                "Uniform (in proportion to the masses)",
            ]
        ),
    )
    targetDrift: float = Field(
        default=2.0,
        gt=0,
        le=10,
        title="Target roof drift",
        description="Roof displacement to push to, as a share of the height [%].",
    )
    steps: int = Field(default=100, ge=10, le=2000, description="Steps to the target drift.")


class TimeHistory(_Model):
    """A ground acceleration record run as a time-history analysis."""

    name: str = Field(min_length=1)
    record: str = Field(
        min_length=1,
        title="Record file",
        description="Acceleration record in the project folder, e.g. "
        "'02 Project Settings/records/ElCentro.AT2': PEER .AT2, two columns (time, "
        "acceleration) or one value per line.",
    )
    units: Literal["g", "m/s2"] = Field(
        default="g",
        description="Units of the record's accelerations.",
        json_schema_extra=_labels(["g", "m/s²"]),
    )
    dt: float | None = Field(
        default=None,
        gt=0,
        title="Time step",
        description="Sampling interval [s] of a record with one value per line; the others "
        "carry their own.",
    )
    direction: Literal["X", "Y"] = Field(default="X", description="Direction of the shaking.")
    scale: float = Field(default=1.0, gt=0, description="Factor on the record's accelerations.")
    damping: float = Field(
        default=0.05, ge=0, le=0.3, description="Damping ratio of the first mode [-]."
    )


class Thermal(_Model):
    """The temperature load case T (BNBC 2020 Part 6 Sec 2.6.4; T in the combinations of Sec
    2.7)."""

    enabled: bool = Field(
        default=False,
        title="Temperature case T",
        description="Add the load case T: the members' restrained expansion or contraction and "
        "the bending of a sun-heated roof. BNBC 2020 asks for temperature effects where "
        "significant, unless expansion joints relieve them (Part 6 Sec 2.6.4). With rigid floor "
        "diaphragms, this case is analysed without them, so the floors can expand.",
    )
    uniform: float = Field(
        default=20.0,
        ge=-60,
        le=60,
        title="Uniform change ΔTu",
        description="Change of the members' temperature from the construction temperature [°C], "
        "+ expansion. BNBC gives no design range; take the site's range of shade air "
        "temperature (Sec 2.6.4(a)). The combinations apply it as a rise (+T) and a fall (-T); "
        "enter the larger. Suggestion for Bangladesh: 20 °C.",
    )
    gradient: float = Field(
        default=10.0,
        ge=-40,
        le=40,
        title="Roof gradient ΔTg",
        description="Top face minus bottom face of the roof's beams and slabs [°C] (sun-heated "
        "roof); 0 for none. Not given by BNBC; about 10 °C is a common assumption for an "
        "uninsulated concrete roof.",
    )
    scope: Literal["roof", "all"] = Field(
        default="roof",
        title="Uniform change applies to",
        description="The roof's beams and slabs (a sun-exposed roof over a shaded building), or "
        "every member and shell (an open structure). The roof is every horizontal beam and "
        "slab with nothing above it: the main roof and any stair, lift-machine or tank room "
        "roof above it.",
        json_schema_extra=_labels(["Roof beams and slabs", "All members and shells"]),
    )


FireHours = Literal[0, 1, 1.5, 2, 3, 4]


class FireResistance(_Model):
    """The fire resistance ratings the members are checked for (least sizes and covers); 0: not
    checked."""

    columns: FireHours = Field(
        default=0,
        title="Columns",
        description="Rating of the columns [h] (0: not checked). Take it from BNBC 2020 Part 4 "
        "for the building's occupancy and construction type.",
    )
    beams: FireHours = Field(default=0, title="Beams", description="Rating of the beams [h].")
    slabs: FireHours = Field(default=0, title="Slabs", description="Rating of the slabs [h].")
    walls: FireHours = Field(
        default=0, title="Walls", description="Rating of the structural walls [h]."
    )


class SettlementSupport(_Model):
    """A column base that settles in the settlement case ST."""

    column: Id = Field(
        title="Column", description="Column of the building model whose base settles."
    )
    value: float = Field(
        gt=0, le=500, title="Settlement", description="Downward settlement of the base [mm]."
    )


class Settlement(_Model):
    """The support settlement case ST: imposed settlements of column bases. BNBC 2020 Part 6
    counts differential settlement among the self-straining effects T of its load combinations
    (Sec 2.7); ST takes T's factor."""

    enabled: bool = Field(
        default=False,
        title="Settlement case ST",
        description="Add the load case ST: the listed column bases settle by the given amounts "
        "(the differential settlement the soil report or 9 Substructure expects). Fixed bases "
        "only (not with soil springs).",
    )
    supports: list[SettlementSupport] = Field(
        default_factory=list,
        title="Settling supports",
        description="Column bases and their settlement.",
    )


class PDeltaFactors(_Model):
    """Load factors of the gravity preload of the P-Delta analysis."""

    D: float = Field(default=1.2, ge=0, description="Dead load.")
    SD: float = Field(default=1.2, ge=0, description="Superimposed dead load.")
    F: float = Field(default=1.2, ge=0, description="Fluid loads (07 MEP equipment contents).")
    L: float = Field(default=1.0, ge=0, description="Live load.")


class Slenderness(_Model):
    """How column slenderness is designed for (BNBC 2020 Part 6 Sec 6.3.10)."""

    effectiveLength: Literal["unity", "chart"] = Field(
        default="unity",
        title="Effective length factor k (nonsway)",
        description="1.0: conservative, allowed by BNBC 2020 Part 6 Sec 6.3.10.6.3. Chart: the "
        "nonsway alignment chart with ψ from 0.70 Ig columns, 0.35 Ig beams and 0.25 Ig flat "
        "plates. Sway storeys always use the sway chart.",
        json_schema_extra=_labels(["k = 1.0", "Alignment chart"]),
    )
    swayMagnifier: Literal["Q", "sumPc"] = Field(
        default="Q",
        title="Sway magnifier δs",
        description="Q: δs = 1/(1 − Q) (BNBC 2020 Part 6 Eq. 6.6.27), at most 1.5. ΣPc: δs = "
        "1/(1 − ΣPu/(0.75 ΣPc)) (Eq. 6.6.28), Pc with EI/(1 + βdns) of each combination (Sec "
        "6.3.10.7.4).",
        json_schema_extra=_labels(["1/(1 − Q)", "ΣPu / ΣPc"]),
    )
    stiffness: Literal["0.4EcIg", "bars"] = Field(
        default="0.4EcIg",
        title="EI for Pc",
        description="0.4 Ec Ig/(1 + βdns) (BNBC 2020 Part 6 Eq. 6.6.22) or (0.2 Ec Ig + Es Ise)/"
        "(1 + βdns) with the bars (Eq. 6.6.21).",
        json_schema_extra=_labels(["0.4 Ec Ig", "0.2 Ec Ig + Es Ise (with the bars)"]),
    )
    fixedBasePsi: float = Field(
        default=1.0,
        ge=0,
        title="ψ at a fixed base",
        description="End restraint ψ of a column on a fixed support, for the alignment charts.",
    )
    driftFactor: float | None = Field(
        default=None,
        gt=0,
        title="Storey drift factor for Q",
        description="Empty (automatic): 1.0 when the analysed model ran its lateral cases on "
        "cracked sections (read from the model, not from these settings); with gross sections "
        "each storey's "
        "first-order drift Δo is multiplied by its cracked-over-gross drift ratio (columns "
        "0.70 Ig, beams 0.35 Ig, flat plates 0.25 Ig, walls 0.35 Ig; BNBC 2020 Part 6 Sec "
        "6.3.10.4.1). A number is used as given.",
    )


class ExtraMass(_Model):
    """A weight added to the seismic mass of a story (equipment not modelled, a tank's water)."""

    story: str | None = Field(
        default=None, description="Id of the story it goes to (or give the elevation z)."
    )
    z: float | None = Field(default=None, title="Elevation z", description="[mm]")
    weight: float = Field(gt=0, description="[kN]")
    x: float | None = Field(
        default=None, description="Plan position [mm]; empty: the story's centre of mass."
    )
    y: float | None = Field(default=None, description="[mm]")


class MassSource(_Model):
    """What forms the seismic weight W and the masses (BNBC 2020 Part 6 Sec 2.5.7.3: the dead
    load including partitions, 25 % of the live load (50 % above 3 kN/m²) and permanent
    equipment and retained liquid in full)."""

    dead: float = Field(default=1.0, ge=0, title="Dead load factor", description="On D.")
    superimposed: float = Field(
        default=1.0, ge=0, title="Superimposed dead factor", description="On SD."
    )
    liveShare: float | None = Field(
        default=None,
        ge=0,
        le=1,
        title="Live load share",
        description="Empty: the code's (25 %, 50 % for live loads above 3 kN/m²). A number "
        "replaces both (the code's are minimums).",
    )
    extraMasses: list[ExtraMass] = Field(
        default_factory=list, title="Extra masses", description="Weights added per story."
    )


class Analysis(_Model):
    """How the analysis model (Part 8) represents the building."""

    slabs: Literal["loadsToBeams", "shells"] = Field(
        default="loadsToBeams",
        description="Slabs on beams hand their loads to the beams (45° rule); flat slabs and "
        "slabs whose bending matters are meshed as shells.",
        json_schema_extra=_labels(
            ["Loads to beams (slab not in the stiffness)", "Shells (plate bending, flat slabs)"]
        ),
    )
    diaphragm: Literal["rigid", "flexible"] = Field(
        default="rigid",
        title="Floor diaphragm",
        description="Rigid: every floor moves as a rigid plate in plan. Flexible: floors are as "
        "stiff in plan as their beams (and shell slabs) make them.",
        json_schema_extra=_labels(["Rigid", "Flexible (from the modelled elements)"]),
    )
    meshSize: float = Field(
        default=500,
        ge=100,
        title="Mesh size",
        description="Largest side of a shell element [mm], and with slabs as loads to beams the "
        "largest beam element (the slabs' triangles and trapezoids are applied over it). 500 mm: "
        "beams on shell slabs get their gravity moments "
        "within about 5 % of a converged mesh.",
    )
    meshBySpan: bool = Field(
        default=True,
        title="Mesh by slab span",
        description="Shell slabs meshed no coarser than their shorter span / 8 where that is "
        "finer than the mesh size (at least 200 mm).",
    )
    meshCheck: bool = Field(
        default=True,
        title="Mesh convergence check",
        description="Run All also solves the gravity cases on a mesh twice as coarse and warns "
        "when a beam end moment changes by more than 5 % (the mesh is then too coarse).",
    )
    partitionLoads: Literal["architecture", "allowance"] = Field(
        default="architecture",
        title="Partition walls",
        description="From the architecture: the walls drawn in Architecture load the beams and "
        "slabs under them as line loads in their positions (BNBC 2020 Part 6 Sec 2.2.5), and the "
        "area load's partition allowance is dropped on the stories where they stand; stories "
        "without walls keep the allowance. Allowance: the walls are not applied and the area "
        "load's flat partition allowance holds everywhere (Sec 2.3.6).",
        json_schema_extra=_labels(
            ["From the architecture (where walls are drawn)", "Flat allowance (area load)"]
        ),
    )
    massLumping: Literal["storyLevels", "levelAbove"] = Field(
        default="storyLevels",
        title="Seismic mass",
        description="Story levels: every node's weight goes to the nearest story level (to its "
        "diaphragm), the lower half of the first story to the base, where it does not take part "
        "(as the usual analysis programs lump it). Level above: every "
        "weight counts for the first level above the base and its mass stays where it is.",
        json_schema_extra=_labels(
            ["Lumped at the story levels", "Each node's own (lower first story to level 1)"]
        ),
    )
    massSource: MassSource = Field(
        default_factory=lambda: MassSource(),
        title="Mass source",
        description="What forms the seismic weight W (BNBC 2020 Part 6 Sec 2.5.7.3): factors on "
        "the dead loads, the live load share and extra masses.",
    )
    accidentalEccentricity: bool = Field(
        default=True,
        title="Eccentric static earthquake cases",
        description="Add the static cases EXP, EXN, EYP, EYN: EX and EY with the story masses "
        "shifted ±5 % of the building's width across the force (BNBC 2020 Part 6 Sec 2.5.7.6.2, "
        "Eq. 6.2.43). With equivalent static design, every E combination is checked with both.",
    )
    windTorsionCases: bool = Field(
        default=True,
        title="Wind torsional cases",
        description="Add the torsional wind cases WTX, WTY and design every one-direction wind "
        "combination for the four design wind load cases of BNBC 2020 Part 6 Figure 6.2.9 "
        "(Sec 2.4.11.3): full, 75 % with torsion e = ±0.15 B, 75 % in both directions, 56.3 % "
        "in both with both torsions. Off: Cases 1 and 3 only.",
    )
    patternLive: Literal["bnbc", "bnbcAlternateFloors", "alternate", "off"] = Field(
        default="bnbc",
        title="Live load arrangement",
        description="BNBC 2020 Part 6 Sec 6.1.12.2: live load on two adjacent spans and on "
        "alternate spans of the column grid, as extra cases LP1, LP2 ... enveloped with the "
        "full live load. BNBC: adjacent spans on each floor alone (one case per pair and floor) "
        "and alternate spans as a checkerboard over the floors. Adjacent on alternate floors: "
        "fewer cases, support moments up to about 2 % lower. Alternate spans only. Off: the "
        "full live load on every span.",
        json_schema_extra=_labels(
            [
                "BNBC 6.1.12.2 (adjacent each floor, alternate checkerboard)",
                "BNBC, adjacent on alternate floors (fewer cases)",
                "Alternate spans only",
                "Off (full live load only)",
            ]
        ),
    )
    deflection: Literal["sensitive", "insensitive", "off"] = Field(
        default="sensitive",
        title="Beam deflection limits",
        description="Beams are checked for deflection (BNBC 2020 Part 6 Sec 6.2.5) unless they "
        "are at least as deep as Table 6.6.1 asks: immediate live-load deflection l/360 "
        "(l/180 roofs) and, after the nonstructural elements are attached, l/480 where they are "
        "likely to be damaged (masonry partitions, the usual case) or l/240 where not "
        "(Table 6.6.2). Off: not checked.",
        json_schema_extra=_labels(
            [
                "Partitions likely to be damaged (l/480)",
                "Not likely to be damaged (l/240)",
                "Off",
            ]
        ),
    )
    sustainedLive: float = Field(
        default=0.25,
        ge=0,
        le=1,
        title="Sustained share of the live load",
        description="Share of the live load taken as sustained for the long-term deflection "
        "(an SAEngine assumption for residential and office floors; raise it for storage).",
    )
    liveLoadReduction: bool = Field(
        default=False,
        title="Live load reduction",
        description="Reduce the live loads of beams and columns by the code pack's rule "
        "(liveReduction): the floor live load by the influence area KLL AT, the ordinary roof "
        "live load Lr by the tributary area and the roof slope. A member's design overwrite can "
        "give its own factor.",
    )
    reducedLiveFactor: bool = Field(
        default=False,
        title="Reduced live load factor",
        description="Take the code pack's permitted lower factor on L in the strength "
        "combinations it names, where its conditions hold (the floor live loads and uses). "
        "Applied when the load combinations are reset to the code's.",
    )
    roofSlope: float = Field(
        default=0.0,
        ge=0,
        title="Roof slope",
        description="Slope of a pitched roof in per cent (rise / run × 100), for the roof live "
        "load by slope and its reduction; 0 for a flat roof.",
    )
    periodMethod: Literal["approximate", "analysis"] = Field(
        default="approximate",
        title="Period for the static base shear",
        description="Approximate: Ta = Ct·hn^m (BNBC 2020 Part 6 Eq. 6.2.38). Analysis: the "
        "modal period of each direction, at most 1.4 Ta (Sec 2.5.7.2 (a)) and not below Ta.",
        json_schema_extra=_labels(["Approximate Ta", "From the modal analysis (≤ 1.4 Ta)"]),
    )
    endOffsets: bool = Field(
        default=True,
        title="End offsets (rigid zones)",
        description="Beams and columns end at the faces of their supports: the part inside a "
        "joint is a rigid zone of the rigid zone factor times its length, and the forces are "
        "also reported at the support faces, where the design takes them (beams at the column "
        "faces, columns at the beam soffit and the top of the slab).",
    )
    rigidZoneFactor: float = Field(
        default=0.5,
        ge=0,
        le=1,
        title="Rigid zone factor",
        description="Share of an end offset that is rigid (0: the whole length flexible, the "
        "forces still read at the faces; 1: fully rigid).",
    )
    exactColumnRotation: bool = Field(
        default=True,
        title="Columns at any angle",
        description="A column turned by an angle that is not a multiple of 90° is analysed and "
        "designed on its own axes.",
    )
    responseSpectrum: bool = Field(
        default=True,
        title="Response spectrum",
        description="Add response spectrum analyses in X and Y with the BNBC design spectrum of "
        "the site (CQC of the modes).",
    )
    stiffness: Literal["gross", "aci"] = Field(
        default="aci",
        title="Section stiffness",
        description="Cracked (default): concrete and masonry members with the moments of "
        "inertia of BNBC 2020 Part 6 Sec 6.3.10.4.1 (columns 0.70 Ig, walls 0.70 Ig or 0.35 Ig "
        "when cracked, beams 0.35 Ig, flat plates and slabs 0.25 Ig; area 1.0 Ag). BNBC 2020 "
        "Part 6 Sec 2.5.9.1 (a) requires the response spectrum model to consider the effects "
        "of cracked sections, and Sec 6.1.10.2 uses these properties for the lateral "
        "deflections. Gross: the uncracked sections (the model is then too stiff: periods come out shorter and drifts smaller than BNBC intends).",
        json_schema_extra=_labels(["Gross sections", "Cracked (ACI / BNBC 6.3.10.4.1)"]),
    )
    crackedFor: Literal["all", "lateral"] = Field(
        default="lateral",
        title="Cracked stiffness for",
        description="Lateral cases: wind, earthquake, modal, response spectrum and time "
        "histories on the cracked sections, the gravity cases on the gross ones. All cases: "
        "the model's sections are the cracked ones (as property modifiers on the sections).",
        json_schema_extra=_labels(["All cases", "Lateral cases only"]),
    )
    wallsCracked: bool = Field(
        default=False,
        title="Walls cracked",
        description="Walls at 0.35 Ig (cracked) instead of 0.70 Ig (uncracked), BNBC 2020 Part "
        "6 Sec 6.3.10.4.1.",
    )
    secondOrder: Literal["none", "pDelta"] = Field(
        default="none",
        title="Second-order analysis",
        description="None: columns are designed for slenderness by moment magnification (BNBC "
        "2020 Part 6 Sec 6.3.10.6 and 6.3.10.7). P-Delta: the columns get P-Delta "
        "transformations and every case is solved on the stiffness of the structure under "
        "the gravity preload (BNBC 2020 Part 6 Sec 2.5.7.9, 6.3.10.4), so the sway magnifier δs "
        "is 1 and only the effects along the column length (δns) are added (Sec 6.3.10.2.2).",
        json_schema_extra=_labels(["None (moment magnification)", "P-Delta analysis"]),
    )
    pDeltaFactors: PDeltaFactors = Field(
        default_factory=PDeltaFactors,
        title="P-Delta preload factors",
        description="The gravity loads the P-Delta stiffness is taken under: by default the "
        "gravity part of 1.2D + 1.0E + 1.0L (BNBC 2020 Part 6 Sec 2.7.3.1).",
    )
    firstOrderReference: bool = Field(
        default=True,
        title="First-order reference cases",
        description="With P-Delta, also run each lateral static case first order (EX-1, ...), "
        "for the drift amplification and the stability coefficient θ of BNBC 2020 Part 6 Sec "
        "2.5.7.9 in the report.",
    )
    notionalLoads: Literal["none", "secondOrder", "firstOrder"] = Field(
        default="none",
        title="Notional loads (steel stability)",
        description="Lateral notional loads Ni at each level for the stability design of steel "
        "frames (BNBC 2020 Part 6 Sec 10.3.2.2), as the cases NXD, NYD (from D and SD), NXL, "
        "NYL (from L) and NXLr, NYLr (from Lr), scaled in each combination by its own factors. "
        "Second-order analysis: Ni = 0.002 Yi, added to the gravity-only combinations in ±X and "
        "±Y. First-order analysis: Ni = 2.1 (Δ/L) Yi >= 0.0042 Yi, added to every combination "
        "(with the lateral load's direction; gravity-only ones in ±X and ±Y).",
        json_schema_extra=_labels(
            ["None", "Second-order analysis (0.002 Yi)", "First-order analysis (2.1 Δ/L Yi)"]
        ),
    )
    notionalDrift: float = Field(
        default=0.0,
        ge=0,
        le=0.05,
        title="First-order drift ratio Δ/L",
        description="First-order analysis: the largest storey drift ratio under the strength "
        "load combinations, for Ni = 2.1 (Δ/L) Yi (at least 0.0042 Yi). 0: the minimum.",
    )
    slenderness: Slenderness = Field(default_factory=Slenderness, title="Column slenderness")
    seismicDesign: Literal["static", "responseSpectrum"] = Field(
        default="responseSpectrum",
        title="Earthquake design forces",
        description="Response spectrum: when the response spectrum cases run, E in the design "
        "combinations is the response spectrum, scaled up to 85 % of the equivalent static base "
        "shear (BNBC 2020 Part 6 Sec 2.5.9.4), with the accidental torsion and the orthogonal "
        "rule below (the static cases EX and EY otherwise). Static: the equivalent static cases "
        "EX and EY.",
        json_schema_extra=_labels(
            ["Equivalent static (EX, EY)", "Response spectrum, scaled (BNBC 2.5.9.4)"]
        ),
    )
    seismicOrthogonal: Literal["auto", "always", "never"] = Field(
        default="auto",
        title="Orthogonal effects (100 % + 30 %)",
        description="Automatic: E = EX + 0.3EY and 0.3EX + EY in Seismic Design Category D "
        "(BNBC 2020 Part 6 Sec 2.5.13.1 (b)); one direction at a time in B and C. Always: also "
        "for a Category C building with non-parallel systems (irregularity type V).",
        json_schema_extra=_labels(["By the Seismic Design Category", "Always", "Never"]),
    )
    seismicAccidentalTorsion: bool = Field(
        default=True,
        title="Accidental torsion",
        description="Add the static torsional moments ±0.05 L F at each floor (BNBC 2020 Part 6 "
        "Sec 2.5.7.6.2, Eq. 6.2.43) to the response spectrum; amplified by Ax where the "
        "building is torsionally irregular in Seismic Design Category C or D (Eq. 6.2.44, Sec "
        "2.5.5.3.1); with 100 % + 30 % the 5 % shift in one direction at a time, the larger "
        "effect governing (Sec 2.5.7.6.3).",
    )
    seismicVerticalComponent: bool = Field(
        default=True,
        title="Vertical earthquake component",
        description="E = Eh ± Ev with Ev = 0.50 a_h D, a_h = (2/3) Z S (BNBC 2020 Part 6 Sec "
        "2.5.13.2).",
    )
    seismicLiveFactor: float | None = Field(
        default=None,
        ge=0,
        title="Live load factor with E",
        description="Factor on L in 1.2D + 1.0E + L. Empty: the project's own static earthquake "
        "combination's (0.5 is permitted for L ≤ 5.0 kN/m² except garages and assembly, BNBC "
        "2020 Part 6 Sec 2.7.3.1 exception 1).",
    )
    seismicRedundancy: float = Field(
        default=1.0,
        ge=1.0,
        le=1.3,
        title="Redundancy factor ρ (drift)",
        description="The allowable storey drift of moment frames in Category D is Δa/ρ (BNBC "
        "2020 Part 6 Sec 2.5.14.1): 1.0, or up to 1.3 for low redundancy.",
    )
    seismicSigns: Literal["corners", "plusMinus"] = Field(
        default="corners",
        title="Response spectrum signs",
        description="Response spectrum results have no sign: the design takes ± the envelope, "
        "every force component at its peak. Corners: columns and walls checked at ±N, ±My, ±Mz "
        "(8 patterns). ±: +E and −E only.",
        json_schema_extra=_labels(["±N, ±My, ±Mz (8 patterns)", "+E and −E"]),
    )
    constructionSequence: bool = Field(
        default=False,
        title="Construction sequence",
        description="Apply the self-weight storey by storey as the building is built (a linear "
        "sequential construction analysis): each storey carries only the self-weight added "
        "after it is built, as for the column shortening of tall buildings. Superimposed dead, "
        "live and lateral loads act on the completed building. Buildings only.",
    )
    timeHistories: list[TimeHistory] = Field(
        default_factory=list,
        title="Time histories",
        description="Earthquake records to run through the structure step by step, after its "
        "dead loads.",
    )
    pushover: Pushover | None = Field(
        default=None,
        description="Pushover analyses: the frames as fiber elements that crack and yield, "
        "pushed sideways after the gravity loads (08 FEM/pushover.osmodel).",
    )
    thermal: Thermal = Field(default_factory=Thermal, title="Temperature")
    settlement: Settlement = Field(default_factory=Settlement, title="Support settlement")
    fireResistance: FireResistance = Field(
        default_factory=FireResistance,
        title="Fire resistance",
        description="Ratings the concrete members' least sizes and covers are checked for "
        "(the ratings of BNBC 2020 Part 4; the sizes of ACI 216.1).",
    )
    supports: Literal["fixed", "soilSprings"] = Field(
        default="fixed",
        title="Column supports",
        description="Fixed: the column bases are fixed. Soil springs: each column base stands on "
        "its foundation of 9 Substructure, on springs from the soil of 1 Soil Report (BNBC 2020 "
        "Part 6 Sec 1.2.7.3). Footings: ASCE 41-06 Sec 4.4.2.1.2 (Gazetas 1991). Pile caps: their "
        "piles' head stiffnesses. Rafts: shells on subgrade springs. Columns without a "
        "foundation, strip footings and walls stay fixed. The foundations of 9 Substructure are "
        "then designed from a fixed-base run of the same model (Compare Fixed Base and Soil "
        "Springs; Run All runs it).",
        json_schema_extra=_labels(["Fixed", "Soil springs (Part 9 foundations on Part 1 soil)"]),
    )
    ssiShearModulusRatio: float | None = Field(
        default=None,
        gt=0,
        le=1,
        title="Effective shear modulus ratio G/G0",
        description="Soil shear modulus under earthquake strains over the small-strain one from "
        "the SPT (Vs = 97.0 N^0.314 m/s, Imai & Tonouchi 1982). Empty: from the site's effective "
        "peak acceleration (2/3)·Z·S, by ASCE 7-05 Table 19.2-1 (0.81 at 0.10 g or less, 0.64 at "
        "0.15 g, 0.49 at 0.20 g, 0.42 at 0.30 g or more, linear between).",
    )
    ssiPileGroupFactor: float = Field(
        default=1.0,
        gt=0,
        le=1,
        title="Pile group factor (lateral)",
        description="Multiplies the summed lateral and torsional stiffness of a cap's piles. 1.0: "
        "no pile-soil-pile interaction (BNBC 2020 Part 6 Sec 3.10.1.19 takes a group efficiency "
        "of 1.0 for capacity).",
    )
    ssiEmbedment: bool = Field(
        default=True,
        title="Footing embedment",
        description="Increase the footings' springs by the embedment factors of ASCE 41-06 Sec "
        "4.4.2.1.2 (depth below the finished ground, sides in contact up to the footing's "
        "thickness).",
    )


class Foundation(_Model):
    """Soil values of the footing design. The net allowable bearing pressure of each footing
    comes from 1 Soil Report (its nearest boreholes, at the footing's founding level and size)
    unless it is overridden here."""

    allowableBearing: float | None = Field(
        default=None,
        gt=0,
        title="Allowable bearing override qa",
        description="Net allowable bearing pressure [kPa] used for every footing instead of the "
        "soil report's. Leave empty to take qa per footing from 1 Soil Report; without boreholes "
        "and without an override, the footings are designed without the bearing check.",
    )
    soilUnitWeight: float = Field(
        default=18.0,
        gt=0,
        title="Soil unit weight γ",
        description="Unit weight of the backfill above the footings [kN/m³].",
    )
    groundLevel: float = Field(
        default=0.0,
        title="Ground level",
        description="Elevation of the finished ground [mm]; the soil cover above a footing is "
        "measured from it.",
    )


class AreaLoad(_Model):
    """Loads on floor area of one use: live load and superimposed dead loads."""

    id: Id
    name: str = Field(min_length=1)
    use: AreaUseId = Field(  # type: ignore[valid-type]
        default="residential",
        description="Use of the area (Table 6.2.3).",
        json_schema_extra=_labels(
            [f"{v.name} ({v.live} kN/m²)" for v in bnbc.AREA_USES.values()] + ["Custom"]
        ),
    )
    live: Pressure = Field(description="Live load [kN/m²]; at least the code minimum for the use.")
    finish: Pressure = Field(default=0, title="Floor finish", description="[kN/m²]")
    partitions: Pressure = Field(default=0, description="Partition allowance [kN/m²].")


class LoadCombination(_Model):
    """Factors on the load cases. D applies to the dead and superimposed dead loads."""

    name: str = Field(min_length=1)
    D: float = Field(
        default=0,
        description="Factor on the dead load D, which includes the superimposed dead load SD "
        "(floor finish, partitions).",
    )
    L: float = Field(default=0, description="Factor on the live load L.")
    Lr: float = Field(default=0, description="Factor on the roof live load Lr.")
    WX: float = Field(default=0, title="Wx", description="Factor on the wind load along X.")
    WY: float = Field(default=0, title="Wy", description="Factor on the wind load along Y.")
    EX: float = Field(default=0, title="Ex", description="Factor on the earthquake load along X.")
    EY: float = Field(default=0, title="Ey", description="Factor on the earthquake load along Y.")
    T: float = Field(
        default=0,
        title="T",
        description="Factor on the temperature case T (Analysis model → Temperature). BNBC 2020 "
        "Part 6 Sec 2.7.3.1 has T only in 1.2(D + F + T) + 1.6(L + H) + 0.5(Lr or R).",
    )
    ST: float = Field(
        default=0,
        title="ST",
        description="Factor on the support settlement case ST (Analysis model → Support "
        "settlement): differential settlement is a self-straining effect T of BNBC 2020 Part 6 "
        "Sec 2.7, so it takes T's factor, 1.2 in 1.2(D + F + T) + 1.6(L + H) + 0.5(Lr or R).",
    )
    F: float | None = Field(
        default=None,
        title="F",
        description="Factor on the fluid loads (the contents of equipment in 07 MEP), as the "
        "code pack's combination gives it (see its notes). Empty (older files): the D factor "
        "where it is above 1.0, else 0.",
    )

    H: float | None = Field(
        default=None,
        title="H",
        description="Factor on the lateral earth and groundwater pressure on the basement walls "
        "(case H, 9 Substructure), as the code pack's combination gives it. Empty (older "
        "files): 1.6 in the combinations with 1.6L and in the 0.9D ones, else 0.",
    )

    @model_validator(mode="after")
    def _fluid_factor(self) -> LoadCombination:
        if self.F is None:
            self.F = self.D if self.D > 1.0 else 0.0
        if self.H is None:
            self.H = 1.6 if self.L >= 1.6 or 0 < self.D <= 0.9 else 0.0
        return self


class DrawingRevision(_Model):
    """One revision of the drawing set, as the title block's revision table lists it."""

    code: str = Field(min_length=1, title="Revision", description="Its code: 0, A, P1, ...")
    date: str | None = Field(default=None, description="Its date, as it is to be printed.")
    description: str | None = Field(default=None, description="What changed.")
    by: str | None = Field(default=None, title="By", description="Initials of who revised it.")


DRAFTING_FONTS = ("Arial", "Arial Narrow", "Calibri", "Segoe UI", "Tahoma")
LINEWEIGHTS = (0.09, 0.13, 0.18, 0.25, 0.35, 0.5, 0.7, 1.0)


class DrawingLayer(_Model):
    """One layer of SAEngine's scheme (docs/drawings-layers.md) as the office draws it."""

    layer: str = Field(
        min_length=1,
        title="SAEngine layer",
        description="A layer of SAEngine's scheme: S-GRID, S-COLS, A-WALL, P-DOMW, ...",
    )
    name: str | None = Field(
        default=None,
        title="Office name",
        description="The office's name for it; empty: the scheme's (with the layer prefix).",
    )
    color: int | None = Field(
        default=None, ge=1, le=255, title="Colour", description="AutoCAD Colour Index 1-255."
    )
    lineweight: Literal[LINEWEIGHTS] | None = Field(  # type: ignore[valid-type]
        default=None, title="Lineweight", description="Plotted lineweight [mm]."
    )


class DraftingStandard(_Model):
    """The office's drafting standard: layer names, colours and lineweights, the text font, the
    dimension arrows, the sheet number prefixes and the office lines of the title block. Saved
    as a file (Drawings, Office standard) it carries over to the office's other projects."""

    name: str = Field(default="", description="The standard's name, e.g. the office's.")
    font: Literal[DRAFTING_FONTS] = Field(  # type: ignore[valid-type]
        default="Arial",
        description="TrueType font of the text (Windows fonts; LibreCAD draws its own).",
    )
    arrows: Literal["tick", "closed", "dot", "oblique"] = Field(
        default="tick",
        title="Dimension arrows",
        json_schema_extra=_labels(
            ["Architectural tick", "Closed filled arrow", "Small dot", "Oblique stroke"]
        ),
    )
    layerPrefix: str = Field(
        default="",
        title="Layer prefix",
        description="Put before every layer name, e.g. 'XY-' (a layer's office name wins).",
    )
    layers: list[DrawingLayer] = Field(
        default_factory=list, description="Layers drawn other than the scheme."
    )
    structuralPrefix: str = Field(default="S-", title="Structural sheets")
    architecturalPrefix: str = Field(default="A-", title="Architectural sheets")
    plumbingPrefix: str = Field(default="P-", title="Plumbing sheets")
    mechanicalPrefix: str = Field(default="M-", title="HVAC sheets")
    electricalPrefix: str = Field(default="E-", title="Electrical sheets")
    firePrefix: str = Field(default="FP-", title="Fire protection sheets")
    coordinationPrefix: str = Field(default="MC-", title="MEP coordination sheets")
    officeLine: str | None = Field(
        default=None,
        title="Office address line",
        description="Under the firm's name in the title block: address, phone, licence no.",
    )
    disclaimer: str | None = Field(
        default=None,
        description="Printed above the status in the title block, e.g. 'Do not scale.'",
    )


PLAN_SCALES = (50, 75, 100, 125, 150, 200, 250)
DETAIL_SCALES = (10, 20, 25, 50)


def _scale(default: int, scales: tuple[int, ...], title: str, description: str) -> Any:
    return Field(
        default=default,
        title=title,
        description=description,
        json_schema_extra=_labels([f"1:{s}" for s in scales]),
    )


class Drawings(_Model):
    """The structural drawings of 11 Exports: the title block and the sheets. The project's
    name, number, client and address come from Project; the fields here print on every sheet."""

    firm: str | None = Field(default=None, description="The consulting firm on the title block.")
    engineer: str | None = Field(
        default=None,
        title="Engineer",
        description="The engineer in charge; empty: Project's structural engineer.",
    )
    drawnBy: str | None = Field(default=None, title="Drawn by")
    checkedBy: str | None = Field(default=None, title="Checked by")
    approvedBy: str | None = Field(default=None, title="Approved by")
    projectNumber: str | None = Field(
        default=None,
        title="Project number",
        description="The drawing set's project number; empty: Project's number.",
    )
    status: str = Field(
        default="FOR REVIEW",
        description="The issue status on the title block (FOR REVIEW, FOR CONSTRUCTION, ...).",
    )
    revisions: list[DrawingRevision] = Field(
        default_factory=list,
        description="The revisions of the set, oldest first; the last is the current revision "
        "(0 when there is none).",
    )
    sheetSize: Literal["A0", "A1", "A2", "A3"] = Field(
        default="A1", title="Sheet size", description="ISO sheet of every drawing."
    )
    planScale: Literal[PLAN_SCALES] = _scale(  # type: ignore[valid-type]
        100,
        PLAN_SCALES,
        "Plan scale",
        "Foundation and framing plans; a plan that does not fit is drawn at the next smaller "
        "scale (noted).",
    )
    slabScale: Literal[PLAN_SCALES] = _scale(  # type: ignore[valid-type]
        50, PLAN_SCALES, "Slab plan scale", "Slab reinforcement plans."
    )
    elevationScale: Literal[PLAN_SCALES] = _scale(  # type: ignore[valid-type]
        50, PLAN_SCALES, "Elevation scale", "Beam elevations and wall elevations."
    )
    detailScale: Literal[DETAIL_SCALES] = _scale(  # type: ignore[valid-type]
        25,
        DETAIL_SCALES,
        "Detail scale",
        "Column sections, beam sections, footing and stair details; a detail that does not fit "
        "is drawn at the next smaller scale.",
    )
    developmentLength: Literal["simplified", "general"] = Field(
        default="simplified",
        title="Development length",
        description="BNBC 2020 Part 6, 8.2.3: the simplified form (8.2.3.2) or the general "
        "Eq. 6.8.1 with cb from the cover and bar spacing (8.2.3.3, Ktr = 0).",
        json_schema_extra=_labels(["Simplified (8.2.3.2)", "General, Eq. 6.8.1 (8.2.3.3)"]),
    )
    curtail: bool = Field(
        default=True,
        title="Cut off beam top bars",
        description="Stop the extra top bars of beams past the supports; off: every bar runs "
        "the full length.",
    )
    standard: DraftingStandard = Field(
        default_factory=DraftingStandard,
        title="Office standard",
        description="Layers, font, arrows, sheet numbers and title block lines of the office.",
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_boq_reinforcement(cls, data: Any) -> Any:
        """Earlier projects chose how 10 BOQ took the reinforcement (measured or from the bar
        bending schedule); the bill now always takes the detailed bars: the choice is dropped."""
        if isinstance(data, dict) and "boqReinforcement" in data:
            data = {k: v for k, v in data.items() if k != "boqReinforcement"}
        return data


class Report(_Model):
    """The printed design report of 11 Exports."""

    appendix: Literal["governing", "all", "none"] = Field(
        default="governing",
        title="Appendix of element checks",
        description="Which elements the appendix prints every check of: governing (the element "
        "of each object type and storey with the largest utilisation, and every element that "
        "fails), all (every element: hundreds of pages for a tall building) or none. The member "
        "tables list every element either way.",
    )
    template: str = Field(
        default="default",
        pattern=r"^[a-z0-9][a-z0-9-]{0,63}$",
        title="Template",
        description="The report template printed: its id, the file name of one in "
        "11 Exports/report-templates, or a built-in one (default: every section in full; "
        "summary: the results without each element's calculations). The template chooses the "
        "sections, their order and detail, the cover, the letterhead and the members printed.",
    )


class ProjectSettings(_Model):
    schema_: Literal["saengine.projectSettings/1"] = Field(default=SCHEMA_ID, alias="schema")
    project: ProjectInfo
    codePack: str = Field(
        default=DEFAULT_PACK,
        pattern=PACK_ID_PATTERN,
        title="Design code",
        description="Id of the code pack the project follows (its towns and hazard values, "
        "importance factors, structural systems, live load minimums, load combinations and "
        "seismic and wind coefficients). Built-in: bnbc2020. A project's own packs live in "
        "02 Project Settings/code-packs/<id>/; the user's in the SAEngine user folder.",
    )
    codes: Codes | None = Field(
        default=None,
        exclude=True,
        title="Codes (deprecated)",
        description="Deprecated: the design code is chosen by codePack. Read from old files "
        "and dropped when they are saved.",
        json_schema_extra={"deprecated": True},
    )
    occupancy: Occupancy = Field(default_factory=Occupancy)
    site: Site = Field(default_factory=Site)
    seismic: Seismic = Field(default_factory=Seismic)
    wind: Wind = Field(default_factory=Wind)
    areaLoads: list[AreaLoad] = Field(default_factory=list, title="Area loads")
    floorLoad: Id = Field(
        title="Floors", description="Area load of the floors unless the floor plan says otherwise."
    )
    roofLoad: Id = Field(title="Roof", description="Area load of the roof (the top story).")
    combinations: list[LoadCombination] = Field(default_factory=list, title="Load combinations")
    cranes: list[CraneRunway] = Field(
        default_factory=list,
        title="Crane runways",
        description="Overhead and monorail cranes: wheel loads with impact, lateral and "
        "longitudinal forces, runway beam checks and the loads on the columns.",
    )
    analysis: Analysis = Field(default_factory=Analysis, title="Analysis model")
    foundation: Foundation = Field(
        default_factory=Foundation,
        description="Soil values for the footing design (from the soil report).",
    )
    drawings: Drawings = Field(
        default_factory=Drawings,
        description="The title block and sheets of the structural drawings (11 Exports).",
    )
    report: Report = Field(
        default_factory=Report,
        title="Design report",
        description="The printed design report (11 Exports).",
    )


def strength_combinations(
    thermal: bool = False,
    pack: CodePack | None = None,
    settlement: bool = False,
    settings: ProjectSettings | None = None,
) -> list[LoadCombination]:
    """The code pack's strength combinations, with wind and earthquake in ±X and ±Y
    (:func:`saengine.fem.combinations.expand_rows`); with ``thermal``, combination 2 also with
    ±T (:func:`saengine.fem.thermal.strength_combinations_with_t`) right after it, the
    combination without T kept. A pack row without F or H gives them no factor.

    With ``settings``, the pack's permitted factor changes (``exceptions``) apply where their
    conditions hold: the reduced live load factor when ``analysis.reducedLiveFactor`` is on,
    and the wind factor of concrete frames when the wind is not reduced by directionality
    (:func:`saengine.fem.combinations.exception_applies`)."""
    from saengine.fem import combinations as fc

    pack = pack or code_context.current()
    table = pack.table("combinations")
    rows = list(table.strength)
    for name, exception in (getattr(table, "exceptions", None) or {}).items():
        if settings is None or not _exception_wanted(name, exception, settings, pack):
            continue
        rows = [fc.apply_exception(row, exception) for row in rows]
    first = rows[1].name if len(rows) > 1 else None  # combination 2: where T and ST go
    result = []
    for label, factors, row in fc.expand_rows(rows):
        result.append(LoadCombination(name=label, **{"F": 0.0, "H": 0.0, **factors}))
        if row.name != first:
            continue
        if thermal:
            from saengine.fem.thermal import strength_combinations_with_t

            for t_name, t_factors in strength_combinations_with_t():
                result.append(LoadCombination(name=t_name, **t_factors))
        if settlement:
            from saengine.fem.settlement import strength_combinations_with_st

            for st_name, st_factors in strength_combinations_with_st(thermal):
                result.append(LoadCombination(name=st_name, **st_factors))
    return result


def _exception_wanted(name: str, exception: Any, settings: ProjectSettings, pack: CodePack) -> bool:
    """Whether the project takes the pack's factor exception ``name``: one on the live load
    when ``analysis.reducedLiveFactor`` is chosen, one on the wind when its conditions hold."""
    from saengine.fem.combinations import exception_applies

    if exception.case == "L":
        if not getattr(settings.analysis, "reducedLiveFactor", False):
            return False
        loads = [(a.use, float(a.live)) for a in settings.areaLoads]
        return exception_applies(exception, live_loads=loads)[0]
    directionality = None
    if pack.has("wind"):
        directionality = getattr(pack.table("wind"), "directionality", None)
    system = (
        pack.table("seismic").systems.get(settings.seismic.system) if pack.has("seismic") else None
    )
    material = "concrete" if system is not None and system.concrete and not system.masonry else None
    return exception_applies(exception, directionality=directionality, material=material)[0]


def default_area_loads() -> list[AreaLoad]:
    # The partition allowance: the code pack's least uniform allowance for partitions not on
    # the plans (1.0 kN/m² when the pack sets none).
    allowance = getattr(code_context.current().table("areaLoads"), "partitions", None)
    return [
        AreaLoad(
            id="FL",
            name="Floors",
            use="residential",
            live=bnbc.AREA_USES["residential"].live,
            finish=1.2,
            partitions=allowance.minimum if allowance is not None else 1.0,
        ),
        AreaLoad(
            id="ST", name="Stairs", use="stairs", live=bnbc.AREA_USES["stairs"].live, finish=1.2
        ),
        AreaLoad(id="RF", name="Roof", use="roof", live=bnbc.AREA_USES["roof"].live, finish=1.5),
    ]


def default_project_settings(name: str = "Project") -> ProjectSettings:
    return ProjectSettings(
        project=ProjectInfo(name=name),
        areaLoads=default_area_loads(),
        floorLoad="FL",
        roofLoad="RF",
        combinations=strength_combinations(),
    )


def code_pack(settings: ProjectSettings | None = None) -> CodePack:
    """The code pack the settings choose (``codePack``), with the project-local packs of the
    project in :func:`saengine.codes.context.project`. Raises :class:`CodePackError` when it is
    not installed or cannot be used (:func:`check` reports that)."""
    return code_context.pack_for(settings)


@dataclass(frozen=True)
class CodeBasis:
    """What the design follows, as the report and the design method state it."""

    general: str
    concrete: str
    steel: str
    method: str

    def rows(self) -> list[list[str]]:
        return [
            ["Loads and general", self.general],
            ["Concrete", self.concrete],
            ["Steel", self.steel],
            ["Design method", self.method],
        ]


def code_basis(settings: ProjectSettings | None = None) -> CodeBasis:
    """The labels of the code the settings choose, from its pack's ``basis`` (inherited along
    the packs it extends); a label no pack gives is the pack's edition (or name), the method
    strength design. Raises :class:`CodePackError` as :func:`code_pack`."""
    pack = code_pack(settings)
    labels = pack.basis
    edition = pack.edition or pack.name
    return CodeBasis(
        general=labels.get("general", edition),
        concrete=labels.get("concrete", edition),
        steel=labels.get("steel", edition),
        method=labels.get("method", "Strength design (LRFD)"),
    )


def derived(settings: ProjectSettings) -> dict[str, Any]:
    """The code values the settings imply (from the project's code pack), each with where it
    comes from."""
    pack = code_pack(settings)
    location = pack.table("locations").locations.get(settings.site.location)
    category = pack.table("occupancyCategories").categories[settings.occupancy.category]
    system = pack.table("seismic").systems[settings.seismic.system]
    zone_z = pack.table("zoneCoefficients").zones[location.zone] if location else None
    return {
        "zone": location.zone if location else None,
        "Z": settings.site.zoneCoefficient or zone_z,
        "windSpeed": settings.site.windSpeed or (location.windSpeed if location else None),
        "seismicImportance": category.seismicImportance,
        "windImportance": category.windImportance,
        "R": settings.seismic.r or system.R,
        "omega": settings.seismic.omega or system.Omega0,
        "Cd": settings.seismic.cd or system.Cd,
        **_combined_values(settings, pack),
    }


# ───────────── combinations of seismic systems (the pack's systemCombination) ─────────────


def _pick(how: str, values: list[float]) -> float:
    return min(values) if how == "min" else max(values)


def system_values(settings: ProjectSettings, pack: CodePack | None = None) -> dict[str, Any]:
    """The seismic force-resisting systems along X and Y and their combined values, by the
    pack's ``seismic.systemCombination`` (different systems in the two directions each keep
    their own values; several in one direction take the least R, the largest Cd and Ω0 and
    the most stringent height limit): ``{"X": {...}, "Y": {...}}``, each ``{"primary",
    "systems", "names", "rows", "R", "Omega0", "Cd", "heightLimits" (by category: None no
    limit, 0 not permitted), "momentFramesOnly", "masonry", "combined"}``. The overrides of R,
    Ω0 and Cd apply in both directions."""
    pack = pack or code_pack(settings)
    table = pack.table("seismic")
    rule = table.systemCombination
    seismic = settings.seismic
    out: dict[str, Any] = {}
    for axis in ("X", "Y"):
        own_y = axis == "Y" and seismic.systemY is not None
        primary = seismic.systemY if own_y else seismic.system
        others = seismic.otherSystemsY if own_y else seismic.otherSystems
        ids = [primary, *dict.fromkeys(o for o in others if o != primary)]
        ids = [i for i in ids if i in table.systems] or [seismic.system]
        rows = [table.systems[i] for i in ids]
        limits: dict[str, float | None] = {}
        for sdc in dict.fromkeys(k for row in rows for k in row.heightLimits):
            given = [row.heightLimits.get(sdc) for row in rows]
            if any(v is not None and v <= 0 for v in given):
                limits[sdc] = 0.0
            else:
                finite = [float(v) for v in given if v is not None]
                limits[sdc] = _pick(rule.heightLimit, finite) if finite else None
        out[axis] = {
            "primary": ids[0],
            "systems": ids,
            "names": [row.name for row in rows],
            "rows": [row.row for row in rows],
            "R": seismic.r or _pick(rule.R, [row.R for row in rows]),
            "Omega0": seismic.omega or _pick(rule.Omega0, [row.Omega0 for row in rows]),
            "Cd": seismic.cd or _pick(rule.Cd, [row.Cd for row in rows]),
            "heightLimits": limits,
            "momentFramesOnly": all(row.momentFrame for row in rows),
            "masonry": any(row.masonry for row in rows),
            "combined": len(rows) > 1,
        }
    return out


def _combined_values(settings: ProjectSettings, pack: CodePack) -> dict[str, Any]:
    """derived()'s values of the systems by direction (RX, RY, CdX, ...) and, when the
    directions or the systems in one differ, R (the least), Cd and Ω0 (the largest) for the
    checks that take one value."""
    by_axis = system_values(settings, pack)
    rule = pack.table("seismic").systemCombination
    x, y = by_axis["X"], by_axis["Y"]
    values: dict[str, Any] = {
        "RX": x["R"],
        "RY": y["R"],
        "CdX": x["Cd"],
        "CdY": y["Cd"],
        "omegaX": x["Omega0"],
        "omegaY": y["Omega0"],
    }
    if x["combined"] or y["combined"] or x["primary"] != y["primary"]:
        values["R"] = _pick(rule.R, [x["R"], y["R"]])
        values["Cd"] = _pick(rule.Cd, [x["Cd"], y["Cd"]])
        values["omega"] = _pick(rule.Omega0, [x["Omega0"], y["Omega0"]])
    return values


def site_specific_warning(
    settings: ProjectSettings, flags: list[str] | None, used: str | None = None
) -> str | None:
    """The warning of the pack's ``seismic.siteSpecificStudy`` when the soil report flags a
    site class the code gives no spectrum for (S1, S2), else None. ``used``: the class the
    spectrum uses (default the settings')."""
    pack = code_pack(settings)
    study = pack.table("seismic").siteSpecificStudy
    found = [c for c in (flags or []) if c in study.classes]
    if not found or not study.warning:
        return None
    return study.warning.format(
        classes=" and ".join(found),
        code=pack.edition or pack.name,
        clause=study.clause,
        used=used or settings.site.siteClass,
        assumed=study.assumedClass or used or settings.site.siteClass,
    )


def soil_flags(settings: ProjectSettings, soil_text: str | None = None) -> list[str]:
    """The site classes the soil report flags (S1, S2, SE of its boreholes), whatever the
    site class source: ``soil_text``, else the report of the project in context; [] without
    one."""
    if soil_text is None:
        root = code_context.project_root()
        if root is None:
            return []
        soil_text = read_soil_text(root)
    try:
        return list(soil_site_class(soil_text, settings).get("flags") or [])
    except Exception:  # noqa: BLE001 - a broken soil report is reported by Part 1
        return []


def category_site_class(settings: ProjectSettings, site_class: str, flags: list[str] | None) -> str:
    """The site class the Seismic Design Category is read with: the pack's assumed class
    (``siteSpecificStudy.assumedClass``) when the soil report flags a class that needs a
    site-specific study, else ``site_class``."""
    study = code_pack(settings).table("seismic").siteSpecificStudy
    if study.assumedClass and any(c in study.classes for c in flags or []):
        return study.assumedClass
    return site_class


def check(settings: ProjectSettings) -> list[str]:
    """Problems the schema cannot express, as "path: message" (see :func:`problems`)."""
    return [f"{path}: {message}" for path, message in problems(settings)]


def design_category(settings: ProjectSettings, site_class: str | None = None) -> dict[str, Any]:
    """The Seismic Design Category of the site (BNBC 2020 Part 6 Sec 2.5.5.2, Table 6.2.18,
    p. 617) and what it allows of the structural system (Table 6.2.19, pp. 619-624; Sec 8.3.2,
    pp. 1088-1089): ``{"sdc", "zone", "siteClass", "permitted", "heightLimit", "detailing",
    "required", "row"}``. ``sdc`` is None without a zone (a custom location without Z);
    ``permitted`` False when the system is NP in the category; ``detailing`` the seismic
    detailing the system gives, ``required`` the least the category needs. ``site_class`` is
    the class the analysis uses (from the soil report), else the entered one."""
    pack = code_pack(settings)
    seismic = pack.table("seismic")
    values = derived(settings)
    zone = values["zone"] if settings.site.zoneCoefficient is None else None
    if zone is None and values["Z"]:
        zones = pack.table("zoneCoefficients").zones
        zone = min(zones, key=lambda k: abs(zones[k] - values["Z"]))
    site = site_class or settings.site.siteClass
    result: dict[str, Any] = {"sdc": None, "zone": zone, "siteClass": site}
    if zone is None:
        return result
    system = seismic.systems.get(settings.seismic.system)
    table = seismic.designCategories
    rows = table.bySiteClass
    row = rows.get(table.aliases.get(site, site)) or list(rows.values())[-1]
    group = table.occupancyGroups.get(settings.occupancy.category) or next(iter(row))
    sdc = row[group][int(zone) - 1]
    # Every system of both directions: the most stringent limitation (systemCombination).
    by_axis = system_values(settings, pack) if system else {}
    limits = [a["heightLimits"].get(sdc) for a in by_axis.values()]
    limit = (
        0.0
        if any(v is not None and v <= 0 for v in limits)
        else min((v for v in limits if v is not None), default=None)
    )
    banned = []
    for axis in by_axis.values():
        for key in axis["systems"]:
            own = seismic.systems[key].heightLimits.get(sdc)
            if own is not None and own <= 0 and key not in banned:
                banned.append(key)
    return {
        **result,
        "sdc": sdc,
        "permitted": not (limit is not None and limit <= 0),
        "heightLimit": limit if limit else None,
        "detailing": system.frame if system else None,
        "required": seismic.requiredDetailing.get(sdc),
        "row": system.row if system else "",
        "notPermitted": banned,
    }


#: The levels of seismic detailing, lowest first (BNBC 2020 Part 6 Sec 8.3.2).
_DETAILING = ("ordinary", "intermediate", "special")


def problems(settings: ProjectSettings) -> list[tuple[str, str]]:
    """Problems the schema cannot express (references, code minimums, site values out of the
    code's range, the structural system in the Seismic Design Category), each as (dotted path
    of the field or section, message)."""
    out: list[tuple[str, str]] = []
    ids = [a.id for a in settings.areaLoads]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        out.append(("areaLoads", f"two area loads use the id {duplicate}"))
    for field, value in (("floorLoad", settings.floorLoad), ("roofLoad", settings.roofLoad)):
        if value not in ids:
            out.append((field, f"there is no area load '{value}'"))
    try:
        pack: CodePack | None = code_pack(settings)
    except CodePackError as e:
        pack = None
        out.append(("codePack", str(e)))
    if pack is not None:
        out.extend(_pack_problems(settings, pack))
    if settings.site.location == "custom":
        if settings.site.zoneCoefficient is None:
            out.append(
                (
                    "site.zoneCoefficient",
                    "a custom location needs the seismic zone coefficient Z (Table 6.2.14)",
                )
            )
        if settings.site.windSpeed is None:
            out.append(
                ("site.windSpeed", "a custom location needs the basic wind speed V (Table 6.2.8)")
            )
    if not settings.combinations:
        out.append(("combinations", "there are no load combinations"))
    return out


def _pack_problems(settings: ProjectSettings, pack: CodePack) -> list[tuple[str, str]]:
    """The settings against the tables of the code pack."""
    out: list[tuple[str, str]] = []
    area_table = pack.table("areaLoads")
    uses = area_table.uses
    edition = pack.edition or pack.name
    partitions = getattr(area_table, "partitions", None)
    for index, load in enumerate(settings.areaLoads):
        use = uses.get(load.use)
        if use and load.live < use.live:
            out.append(
                (
                    f"areaLoads.{index}.live",
                    (
                        f"{load.id}: live load {load.live:g} kN/m² is below the {edition} minimum "
                        f"of {use.live:g} kN/m² for {use.name.lower()} "
                        f"({use.source or area_table.source})"
                    ),
                )
            )
        # The allowance for partitions not on the plans: at least the pack's minimum.
        if partitions is not None and 0 < load.partitions < partitions.minimum - 1e-9:
            out.append(
                (
                    f"areaLoads.{index}.partitions",
                    (
                        f"{load.id}: partition allowance {load.partitions:g} kN/m² is below the "
                        f"{edition} minimum of {partitions.minimum:g} kN/m² "
                        f"({area_table.sources.get('partitions', area_table.source).split(':')[0]})"
                    ),
                )
            )
    out += _exception_problems(settings, pack)
    locations = pack.table("locations").locations
    if settings.site.location != "custom" and settings.site.location not in locations:
        out.append(
            (
                "site.location",
                f"the code pack '{pack.id}' has no location '{settings.site.location}'",
            )
        )
    for where, key, values in (
        (
            "occupancy.category",
            settings.occupancy.category,
            pack.table("occupancyCategories").categories,
        ),
        ("seismic.system", settings.seismic.system, pack.table("seismic").systems),
    ):
        if key not in values:
            out.append((where, f"the code pack '{pack.id}' has no '{key}'"))
    zones = pack.table("zoneCoefficients").zones
    z = settings.site.zoneCoefficient
    if z is not None and zones and not min(zones.values()) <= z <= max(zones.values()):
        out.append(
            (
                "site.zoneCoefficient",
                (
                    f"Z = {z:g} is outside the {edition} zone coefficients "
                    f"({min(zones.values()):g} to {max(zones.values()):g}, Table 6.2.14, p. 615)"
                ),
            )
        )
    speeds = [location.windSpeed for location in locations.values()]
    v = settings.site.windSpeed
    if v is not None and speeds and not min(speeds) * 0.9 <= v <= max(speeds) * 1.1:
        out.append(
            (
                "site.windSpeed",
                (
                    f"V = {v:g} m/s is far from the {edition} basic wind speeds "
                    f"({min(speeds):g} to {max(speeds):g} m/s, Table 6.2.8, p. 600): check the "
                    "units (m/s, 3-second gust at 10 m)"
                ),
            )
        )
    if settings.seismic.system in pack.table("seismic").systems:
        out.extend(_system_problems(settings, pack))
    return out


def _exception_problems(settings: ProjectSettings, pack: CodePack) -> list[tuple[str, str]]:
    """The reduced live load factor chosen where the pack's conditions do not hold."""
    from saengine.fem.combinations import exception_applies

    if not getattr(settings.analysis, "reducedLiveFactor", False):
        return []
    table = pack.table("combinations")
    loads = [(a.use, float(a.live)) for a in settings.areaLoads]
    out = []
    for exception in (getattr(table, "exceptions", None) or {}).values():
        if exception.case != "L":
            continue
        ok, why = exception_applies(exception, live_loads=loads)
        if not ok:
            where = (exception.source or table.source).split(":")[0]
            message = f"the reduced live load factor does not apply: {why} ({where})"
            out.append(("analysis.reducedLiveFactor", f"{message}; the full factor is kept"))
    return out


def _system_problems(settings: ProjectSettings, pack: CodePack) -> list[tuple[str, str]]:
    """The structural system in the Seismic Design Category of the site (with the site class
    of the soil report when the project is known)."""
    site_class = None
    if settings.site.siteClassSource != "entered":
        root = code_context.project_root()
        if root is not None:
            try:
                site_class = soil_site_class(read_soil_text(root), settings).get("class")
            except Exception:  # noqa: BLE001 - a broken soil report is reported by Part 1
                site_class = None
    site_class = category_site_class(
        settings, site_class or settings.site.siteClass, soil_flags(settings)
    )
    info = design_category(settings, site_class)
    sdc = info["sdc"]
    if sdc is None:
        return []
    edition = pack.edition or pack.name
    systems = pack.table("seismic").systems
    system = systems[settings.seismic.system]
    if info.get("notPermitted") and settings.seismic.system not in info["notPermitted"]:
        # Another system of the combination is NP: the more stringent limitation applies.
        system = systems[info["notPermitted"][0]]
        info = {**info, "row": system.row}
    where = f"Table 6.2.19 row {info['row']}" if info["row"] else "Table 6.2.19"
    basis = (
        f"zone {info['zone']}, site class {info['siteClass']}, occupancy category "
        f"{settings.occupancy.category}: Table 6.2.18, p. 617"
    )
    if not info["permitted"]:
        return [
            (
                "seismic.system",
                (
                    f"{system.name} is not permitted in Seismic Design Category {sdc} ({basis}; "
                    f"{edition} Part 6 {where}). Category {sdc} needs {info['required']} seismic "
                    "detailing (Sec 8.3.2): choose a special moment frame or another permitted "
                    "system"
                ),
            )
        ]
    detailing, required = info["detailing"], info["required"]
    if detailing and required and _DETAILING.index(detailing) < _DETAILING.index(required):
        return [
            (
                "seismic.system",
                (
                    f"{system.name} has {detailing} detailing; Seismic Design Category {sdc} ({basis}) "
                    f"needs {required} detailing ({edition} Part 6 Sec 8.3.2, pp. 1088-1089)"
                ),
            )
        ]
    return []


# ─────────────────────────────── values from the soil report ───────────────────────────────

#: Part 1's main file, relative to the project folder.
SOIL_FILE = "01 Soil Report/soil-report.json"


def soil_site_class(
    soil_text: str | None, settings: ProjectSettings | None = None
) -> dict[str, Any]:
    """The project's site class from the boreholes of the soil report (``soil_text``, the text
    of :data:`SOIL_FILE`): ``{"class", "boreholes", "borehole", "N", "su", "basis", "depth",
    "extrapolated", "label", "note"}``; ``"class"`` is None when the report has no boreholes
    that give one (or cannot be read: ``"problems"``).

    ``label`` is the short form the settings editor and the report print, e.g. "SD (N̄ = 12
    over 30 m, BH-2)" (``detail`` the part in brackets): the governing borehole's harmonic mean
    over the top 30 m of BNBC 2020 Table 6.2.13 that decides the class (N̄, or s̄u when the
    cohesive layers govern).
    """
    from saengine.soil import site_class
    from saengine.soil.profile import Profile
    from saengine.soil.report import parse

    none: dict[str, Any] = {"class": None, "boreholes": 0, "label": "", "note": ""}
    if not soil_text or not soil_text.strip():
        return {**none, "note": "There is no soil report."}
    report = parse(soil_text)
    if isinstance(report, list):
        return {**none, "problems": report, "note": "The soil report has errors."}
    if not report.boreholes:
        return {**none, "note": "The soil report has no boreholes."}
    if settings is not None:
        # With the settings (Z for amax), the liquefaction screening is taken into account:
        # boreholes with liquefiable layers make the site S2 (BNBC 2020 Table 6.2.13) and use
        # SD for the design spectrum meanwhile (saengine.soil.report.classify).
        from saengine.soil.report import classify

        classified = classify(report, settings)
        sites, project = classified["sites"], classified["project"]
    else:
        sites = {b.id: site_class.site_class(Profile(report, b)) for b in report.boreholes}
        project = site_class.governing(sites)
    cls = project.get("class")
    result: dict[str, Any] = {
        **none,
        "boreholes": len(report.boreholes),
        "note": project["note"],
        # S1, S2 (and SE) of Table 6.2.13 that the boreholes flag: S1 and S2 need a
        # site-specific study (Sec 2.5.3.1).
        "flags": sorted({f["class"] for f in project.get("flags", []) if f.get("class")}),
    }
    if not cls:
        return result
    which = project["governing"]
    own = sites[which]
    by_su = own.get("bySu") == cls and own.get("byN") != cls
    if by_su and own.get("su") is not None:
        basis = f"s̄u = {own['su']:.0f} kPa"
    elif own.get("N") is not None:
        basis = f"N̄ = {own['N']:g}"
    else:
        basis = ""
    over = "over 30 m" + (", extrapolated" if own.get("extrapolated") else "")
    detail = f"{basis} {over}, {which}" if basis else which
    label = f"{cls} ({detail})"
    return {
        **result,
        "class": cls,
        "borehole": which,
        "N": own.get("N"),
        "su": own.get("su"),
        "basis": "su" if by_su else "N",
        "depth": own.get("depth"),
        "extrapolated": bool(own.get("extrapolated")),
        "label": label,
        "detail": detail,
        "note": project["note"],
        "derivation": own.get("note", ""),
    }


def resolve_site_class(
    settings: ProjectSettings, soil_text: str | None
) -> tuple[ProjectSettings, dict[str, Any]]:
    """The settings with the site class the analysis uses, and where it comes from.

    With ``site.siteClassSource`` "soilReport" (the default) and a soil report whose boreholes
    give a class, that class replaces ``site.siteClass``; otherwise the entered class stays.
    The returned info is ``{"class", "source", "entered", "label", "note", "soil"}``, ``source``
    "soilReport" or "entered" (what is actually used), ``soil`` the result of
    :func:`soil_site_class` (None when the source is Entered).
    """
    entered = settings.site.siteClass
    info: dict[str, Any] = {"class": entered, "source": "entered", "entered": entered, "soil": None}
    if settings.site.siteClassSource == "entered":
        info["label"] = f"{entered} (entered)"
        info["note"] = f"Site class {entered}, entered in the project settings."
        return settings, info
    soil = soil_site_class(soil_text, settings)
    info["soil"] = soil
    if not soil["class"]:
        info["label"] = f"{entered} (entered)"
        info["note"] = (
            f"Site class {entered}, entered in the project settings: "
            f"{soil['note'][:1].lower() + soil['note'][1:] if soil['note'] else 'no soil report'}"
        ).rstrip(".") + "."
        return settings, info
    info.update(
        {
            "class": soil["class"],
            "source": "soilReport",
            "label": f"from 1 Soil Report: {soil['label']}",
            "note": f"Site class from 1 Soil Report: {soil['label']}; {soil['note']}",
        }
    )
    if soil["class"] == entered:
        return settings, info
    site = settings.site.model_copy(update={"siteClass": soil["class"]})
    return settings.model_copy(update={"site": site}), info


def resolve_settings_text(settings_text: str | None, soil_text: str | None) -> str | None:
    """``settings_text`` with the site class the analysis uses (:func:`resolve_site_class`);
    the text itself when it is empty, has errors or keeps its class."""
    import json

    from pydantic import ValidationError

    if not settings_text:
        return settings_text
    try:
        settings = ProjectSettings.model_validate_json(settings_text)
    except ValidationError:
        return settings_text
    resolved, _ = resolve_site_class(settings, soil_text)
    if resolved is settings:
        return settings_text
    return json.dumps(resolved.model_dump(mode="json", by_alias=True, exclude_none=True))


def read_soil_text(project_root: Any) -> str | None:
    """The text of the soil report of the project at ``project_root``, None when it is missing."""
    from pathlib import Path

    try:
        return (Path(project_root) / SOIL_FILE).read_text(encoding="utf-8")
    except OSError:
        return None

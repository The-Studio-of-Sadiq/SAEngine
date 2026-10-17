"""Soil report (``01 Soil Report/soil-report.json``): boreholes, SPT records and lab data.

Part 1 is upstream of the foundation design: the footing design and the substructure read the
values computed from it (site class, allowable bearing pressure, settlement, liquefaction,
subgrade modulus, pile parameters; see :mod:`saengine.soil`) and never write it. The file
stores only what the soil investigation measured and the design choices; every computed value
is worked out on demand.

Units: mm for lengths, depths and positions (depths are measured down from the borehole's
ground), kN/m³ for unit weights, kPa for strengths, MPa for moduli, % for ratios and contents,
degrees for friction angles.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title

SCHEMA_ID = "saengine.soilReport/1"

#: Two depths closer than this are the same depth [mm].
TOLERANCE = 1.0

SoilType = Literal["clay", "silt", "sand", "gravel", "organic", "fill", "rock"]

SOIL_TYPES = {
    "clay": "Clay",
    "silt": "Silt",
    "sand": "Sand",
    "gravel": "Gravel",
    "organic": "Organic soil, peat",
    "fill": "Fill, made ground",
    "rock": "Rock",
}

Depth = Annotated[float, Field(ge=0)]
UnitWeight = Annotated[float, Field(gt=0, le=30)]
Strength = Annotated[float, Field(ge=0)]
Percent = Annotated[float, Field(ge=0, le=100)]


def _labels(names: list[str]) -> dict[str, Any]:
    """Readable names of an enum's values for the editors (JSON Schema ``enumDescriptions``)."""
    return {"enumDescriptions": names}


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class ReportInfo(_Model):
    """The soil investigation report the data comes from."""

    title: str | None = None
    consultant: str | None = Field(default=None, description="Firm that did the investigation.")
    reportNumber: str | None = Field(default=None, title="Report number")
    date: str | None = Field(default=None, description="Date of the report.")


class Layer(_Model):
    """One stratum of a borehole log, with its index and strength properties."""

    top: Depth = Field(description="Depth of the top below the borehole's ground [mm].")
    bottom: Depth = Field(description="Depth of the bottom below the borehole's ground [mm].")
    description: str = Field(default="", description="Description from the log.")
    soilType: SoilType = Field(  # type: ignore[valid-type]
        title="Soil type",
        description="Governs which methods apply: clay, organic soil and plastic silt are "
        "cohesive; sand, gravel and non-plastic silt are granular.",
        json_schema_extra=_labels(list(SOIL_TYPES.values())),
    )
    uscs: str | None = Field(default=None, title="USCS group", description="E.g. CL, ML, SM.")
    unitWeight: UnitWeight | None = Field(
        default=None, title="Unit weight γ", description="Above the water table [kN/m³]."
    )
    saturatedUnitWeight: UnitWeight | None = Field(
        default=None, title="Saturated unit weight γsat", description="[kN/m³]"
    )
    cu: Strength | None = Field(
        default=None, title="Undrained shear strength cu", description="[kPa]"
    )
    c: Strength | None = Field(
        default=None, title="Effective cohesion c'", description="Drained [kPa]."
    )
    phi: float | None = Field(
        default=None, ge=0, le=50, title="Friction angle φ'", description="Drained [°]."
    )
    E: float | None = Field(
        default=None, gt=0, title="Young's modulus E", description="Of the soil [MPa]."
    )
    finesContent: Percent | None = Field(
        default=None, title="Fines content FC", description="Passing 75 µm [%]."
    )
    plasticityIndex: Percent | None = Field(
        default=None, title="Plasticity index PI", description="[%]"
    )
    liquidLimit: float | None = Field(
        default=None, ge=0, le=500, title="Liquid limit LL", description="[%]"
    )
    clayFraction: Percent | None = Field(
        default=None,
        title="Clay fraction",
        description="Finer than 0.005 mm [%] (for the liquefaction criteria of fine-grained soil).",
    )
    Cc: float | None = Field(default=None, ge=0, le=10, title="Compression index Cc")
    Cr: float | None = Field(default=None, ge=0, le=10, title="Recompression index Cr")
    e0: float | None = Field(default=None, gt=0, le=20, title="Initial void ratio e0")
    OCR: float | None = Field(
        default=None, ge=1, le=50, title="Overconsolidation ratio OCR", description="σ'p/σ'v0."
    )

    @model_validator(mode="after")
    def _depths(self) -> Layer:
        if self.bottom <= self.top:
            raise ValueError(f"bottom {self.bottom:g} mm must be below the top {self.top:g} mm")
        return self


class SptRecord(_Model):
    """A standard penetration test (ASTM D1586): the blows for the last 300 mm of the drive."""

    depth: Depth = Field(description="Depth of the test below the borehole's ground [mm].")
    N: int = Field(
        ge=0,
        le=300,
        title="Field N",
        description="Blow count as measured, uncorrected [blows/300 mm]; refusal as the "
        "extrapolated count (e.g. 50 blows for 150 mm as 100).",
    )
    energyRatio: float | None = Field(
        default=None,
        gt=0,
        le=100,
        title="Energy ratio ER",
        description="Hammer energy of this test [%]; overrides the report's hammer energy.",
    )


class Sample(_Model):
    """A sample tested in the laboratory. Its values fill in the layer's where the log has none."""

    depth: Depth = Field(description="Depth of the sample below the borehole's ground [mm].")
    type: str | None = Field(
        default=None, title="Sample type", description="E.g. SPT (disturbed), UD (Shelby tube)."
    )
    moisture: float | None = Field(
        default=None, ge=0, le=1000, title="Moisture content w", description="[%]"
    )
    unitWeight: UnitWeight | None = Field(
        default=None, title="Bulk unit weight γ", description="[kN/m³]"
    )
    cu: Strength | None = Field(
        default=None, title="Undrained shear strength cu", description="[kPa]"
    )
    c: Strength | None = Field(default=None, title="Cohesion c'", description="[kPa]")
    phi: float | None = Field(
        default=None, ge=0, le=50, title="Friction angle φ'", description="[°]"
    )
    finesContent: Percent | None = Field(
        default=None, title="Fines content FC", description="Passing 75 µm [%]."
    )
    liquidLimit: float | None = Field(
        default=None, ge=0, le=500, title="Liquid limit LL", description="[%]"
    )
    plasticLimit: float | None = Field(
        default=None, ge=0, le=500, title="Plastic limit PL", description="[%]"
    )
    clayFraction: Percent | None = Field(
        default=None, title="Clay fraction", description="Finer than 0.005 mm [%]."
    )
    Cc: float | None = Field(default=None, ge=0, le=10, title="Compression index Cc")
    e0: float | None = Field(default=None, gt=0, le=20, title="Initial void ratio e0")


class Borehole(_Model):
    id: str = Field(min_length=1, max_length=64, title="ID", description="E.g. BH-1.")
    x: float = Field(default=0, description="Plan position in the project coordinates [mm].")
    y: float = Field(default=0, description="Plan position in the project coordinates [mm].")
    groundLevel: float | None = Field(
        default=None,
        title="Ground level",
        description="Elevation of the ground at the borehole [mm]; overrides the report's.",
    )
    waterTable: Depth | None = Field(
        default=None,
        title="Water table",
        description="Depth of the ground water below the borehole's ground [mm]; empty when "
        "none was met.",
    )
    depth: Depth | None = Field(
        default=None,
        title="Termination depth",
        description="Depth the borehole was drilled to [mm]; the deepest layer's bottom when "
        "empty.",
    )
    layers: list[Layer] = Field(default_factory=list)
    spt: list[SptRecord] = Field(default_factory=list, title="SPT records")
    samples: list[Sample] = Field(default_factory=list, title="Laboratory samples")

    @property
    def bottom(self) -> float:
        """Depth of the deepest logged information [mm]."""
        depths = [self.depth or 0.0]
        depths += [layer.bottom for layer in self.layers]
        if not self.layers:
            depths += [r.depth for r in self.spt] + [s.depth for s in self.samples]
        return max(depths)

    @model_validator(mode="after")
    def _log(self) -> Borehole:
        problems = []
        for i, (upper, lower) in enumerate(zip(self.layers, self.layers[1:], strict=False)):
            if lower.top < upper.bottom - TOLERANCE:
                problems.append(
                    f"layers {i + 1} and {i + 2} overlap ({lower.top:g} mm is above "
                    f"{upper.bottom:g} mm); list the layers from the top down"
                )
            elif lower.top > upper.bottom + TOLERANCE:
                problems.append(
                    f"gap between layers {i + 1} and {i + 2} ({upper.bottom:g} to "
                    f"{lower.top:g} mm); the layers must be contiguous"
                )
        if self.layers and self.layers[0].top > TOLERANCE:
            problems.append(f"the first layer starts at {self.layers[0].top:g} mm, not at 0")
        if (
            self.layers
            and self.depth is not None
            and self.layers[-1].bottom > self.depth + TOLERANCE
        ):
            problems.append(
                f"the layers go down to {self.layers[-1].bottom:g} mm, below the "
                f"termination depth {self.depth:g} mm"
            )
        bottom = self.bottom
        for kind, records in (("SPT", self.spt), ("sample", self.samples)):
            for record in records:
                if record.depth > bottom + TOLERANCE:
                    problems.append(
                        f"{kind} at {record.depth:g} mm is below the bottom of the borehole "
                        f"({bottom:g} mm)"
                    )
        depths = [r.depth for r in self.spt]
        if depths != sorted(depths):
            problems.append("the SPT records must be listed from the top down")
        if len(set(depths)) != len(depths):
            problems.append("two SPT records at the same depth")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class Liquefaction(_Model):
    """Earthquake for the liquefaction screening."""

    magnitude: float = Field(
        default=7.5, ge=5, le=9, title="Magnitude Mw", description="Moment magnitude."
    )
    pga: float | None = Field(
        default=None,
        gt=0,
        le=2,
        title="Peak ground acceleration amax",
        description="At the ground surface [g]; empty: Z × S from the project settings: the "
        "zone coefficient of the seismic zoning map (BNBC 2020 Table 6.2.14, the maximum "
        "considered PGA on rock) amplified by the site class's soil factor S (Table 6.2.16), "
        "as BNBC 3.9.5 asks for the site amplification.",
    )


class SptCorrections(_Model):
    """Equipment corrections of the field N besides the hammer energy (Youd et al. 2001); the
    Bangladesh consultant practice takes CB = CS = 1 whatever is entered here."""

    boreholeFactor: float = Field(
        default=1.0,
        ge=1,
        le=1.2,
        title="Borehole diameter factor CB",
        description="1.0 for 65-115 mm, 1.05 for 150 mm, 1.15 for 200 mm.",
    )
    samplerFactor: float = Field(
        default=1.0,
        ge=1,
        le=1.3,
        title="Sampler factor CS",
        description="1.0 for a standard sampler; 1.1-1.3 for a sampler without liners.",
    )
    rodLength: bool = Field(
        default=True,
        title="Rod length correction CR",
        description="Short rods lose energy: 0.75 for the shortest rods to 1.0 beyond 10 m of "
        "rod (Youd et al. 2001 for the textbook practice, Skempton 1986 for the consultant "
        "practice).",
    )


class Pile(_Model):
    """Pile type for the pile design parameters."""

    type: Literal["bored", "driven"] = Field(
        default="bored",
        title="Pile type",
        description="Bored cast-in-situ piles (FHWA, O'Neill & Reese 1999) or driven piles "
        "(API RP 2A in clay, Meyerhof 1976 in sand).",
        json_schema_extra=_labels(["Bored (cast in situ)", "Driven (displacement)"]),
    )


#: How the SPT values and the allowable bearing pressure are worked out (``Design.practice``).
PRACTICES = {
    "textbook": "Textbook",
    "bdConsultant": "Bangladesh consultant practice",
}

#: The liquefaction triggering procedure (``Design.liquefactionMethod``).
LIQUEFACTION_METHODS = {
    "idrissBoulanger2014": "Idriss & Boulanger 2014",
    "bnbc2020": "BNBC 2020 Sec 3.9.5",
}


class Design(_Model):
    """Design choices for the values computed from the boreholes."""

    practice: Literal["textbook", "bdConsultant"] = Field(
        default="textbook",
        title="Practice",
        description="How the SPT corrections and the settlement-controlled bearing pressure are "
        "worked out. Textbook: cumulative effective stress, CN of Liao & Whitman (≤ 1.7), the "
        "N60 factors of Youd et al. 2001, Meyerhof-Bowles with N60. Bangladesh consultant "
        "practice (as in common Dhaka soil reports): σ'v of each SPT row from its own unit "
        "weight, CN of Peck, Hanson & Thornburn, Skempton's rod factors, the dilatancy "
        "correction N' below the water table, Meyerhof-Bowles with N' averaged over the "
        "influence zone.",
        json_schema_extra=_labels(list(PRACTICES.values())),
    )
    liquefactionMethod: Literal["idrissBoulanger2014", "bnbc2020"] = Field(
        default="idrissBoulanger2014",
        title="Liquefaction method",
        description="Idriss & Boulanger (2014), or BNBC 2020 Part 6 Sec 3.9.5 (FL = CRR/CSR, "
        "CSR of Eq 6.3.8 with rd = 1 - 0.015 z, CRR of Youd et al. 2001 from the SPT).",
        json_schema_extra=_labels(list(LIQUEFACTION_METHODS.values())),
    )
    hammerEnergy: float = Field(
        default=60,
        gt=0,
        le=100,
        title="Hammer energy ER",
        description="Energy ratio of the SPT hammer [%]: about 45-60 for a hand-released "
        "donut hammer, 60 for a safety hammer, 70-90 for an automatic trip hammer.",
    )
    factorOfSafety: float = Field(
        default=3.0, ge=1, le=10, title="Factor of safety", description="On the bearing capacity."
    )
    allowableSettlement: float = Field(
        default=25,
        gt=0,
        le=500,
        title="Allowable settlement",
        description="Settlement the settlement-controlled bearing pressure is worked out for "
        "[mm]. BNBC 2020 Table 6.3.8's permissible total settlement is shown next to the "
        "computed settlement for information.",
    )
    liquefaction: Liquefaction = Field(default_factory=Liquefaction)
    spt: SptCorrections = Field(default_factory=SptCorrections, title="SPT corrections")
    pile: Pile = Field(default_factory=Pile)
    creepYears: float = Field(
        default=0.1,
        ge=0.1,
        le=100,
        title="Creep time",
        description="Time for the creep factor C2 of the Schmertmann settlement [years]; "
        "0.1 leaves out creep.",
    )
    tableWidths: list[Annotated[float, Field(gt=0)]] = Field(
        default_factory=lambda: [1000, 1500, 2000, 3000, 4000],
        min_length=1,
        max_length=12,
        title="Footing widths",
        description="Widths B of the square footings of the bearing table [mm].",
    )
    tableDepths: list[Annotated[float, Field(ge=0)]] = Field(
        default_factory=lambda: [1000, 1500, 2000, 3000],
        min_length=1,
        max_length=12,
        title="Founding depths",
        description="Depths Df of the bearing table [mm].",
    )
    subgradeWidth: float = Field(
        default=2000,
        gt=0,
        title="Subgrade footing width",
        description="Width of the square footing the subgrade modulus is worked out for [mm].",
    )
    subgradeDepth: float = Field(
        default=1500,
        ge=0,
        title="Subgrade founding depth",
        description="Its founding depth [mm].",
    )


class SoilReport(_Model):
    schema_: Literal["saengine.soilReport/1"] = Field(default=SCHEMA_ID, alias="schema")
    report: ReportInfo = Field(default_factory=ReportInfo)
    groundLevel: float = Field(
        default=0.0,
        title="Ground level",
        description="Elevation of the existing ground in the project datum [mm].",
    )
    boreholes: list[Borehole] = Field(default_factory=list)
    design: Design = Field(default_factory=Design)

    @model_validator(mode="after")
    def _ids(self) -> SoilReport:
        ids = [b.id for b in self.boreholes]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"two boreholes are called {', '.join(duplicates)}")
        return self

    def ground_level(self, borehole: Borehole) -> float:
        return self.groundLevel if borehole.groundLevel is None else borehole.groundLevel


def default_soil_report() -> SoilReport:
    return SoilReport()


def is_placeholder(data: Any) -> bool:
    """The file a new project starts with, before Part 1 had an editor."""
    return isinstance(data, dict) and data.get("schema") == 1 and data.get("part") == "soil"


def check(report: SoilReport) -> list[str]:
    """Problems the schema cannot express: what the computations will be missing."""
    problems = []
    if not report.boreholes:
        problems.append("boreholes: there are no boreholes")
    for borehole in report.boreholes:
        if not borehole.layers:
            problems.append(f"{borehole.id}: there are no layers")
        if not borehole.spt:
            problems.append(f"{borehole.id}: there are no SPT records")
    return problems

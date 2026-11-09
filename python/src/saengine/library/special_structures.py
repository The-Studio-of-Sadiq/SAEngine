"""Bridges and special structures (Project Settings → Bridges and Special Structures, alpha 9 L9).

What the engineer enters for the structures that are not buildings, computed by
:mod:`saengine.special` with the loads, factors and methods of the project's code pack:

- **bridges**: girder and slab bridges, simply supported or continuous, analysed as line girders
  (the deck shared by the rigid cross-section rule) or as a deck grillage, under the pack's
  traffic load models (``movingLoads``) moved along their influence lines, the girders checked
  by the pack's concrete methods (reinforced or prestressed), the bearings' reactions and the
  expansion joints' movement, and the load rating of an existing bridge;
- **towers**: lattice telecom towers (square or triangular, tapering), with their antennas and
  feed lines, under the wind on each panel by the face's solidity ratio, the members checked by
  the pack's steel methods; a tower on a roof adds its wind to the building's roof level;
- **silos**, **chimneys** and **cooling towers**: shells of revolution with the code's loads
  (Janssen pressures, wind with vortex shedding, the pressure around a cylinder);
- **offshore**: a fixed jacket or monopile under the wave (Airy, or the nonlinear stream
  function wave), current and wind on the deck, by Morison's equation;
- **piping**: pipe runs with their supports under the sustained, thermal expansion and occasional
  loads, with the stresses against the pack's piping allowables and the nozzle (anchor) loads.

Units: m for the overall geometry, mm for the cross-sections, kN, kN/m, kN/m², MPa, °C.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Id

Metres = Annotated[float, Field(gt=0, description="[m]")]
Mm = Annotated[float, Field(gt=0, description="[mm]")]


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


def _labels(names: list[str]) -> dict[str, list[str]]:
    return {"enumDescriptions": names}


# ───────────────────────────────────── bridges ─────────────────────────────────────


class GirderPrestress(_Model):
    """The bonded strands of a prestressed girder (pretensioned or bonded post-tensioned)."""

    area: float = Field(gt=0, title="Strand area", description="Aps of all strands [mm²].")
    depth: float = Field(
        gt=0,
        title="Strand depth",
        description="From the top of the deck to the strands' centroid at midspan, dp [mm].",
    )
    endDepth: float | None = Field(
        default=None,
        title="Strand depth at the ends",
        description="dp at the supports [mm] (draped or harped); empty: as at midspan.",
    )
    fpu: float = Field(default=1860, gt=0, description="Tensile strength of the strand [MPa].")
    jacking: float = Field(
        default=0.75, gt=0, le=0.95, description="Jacking stress as a share of fpu."
    )
    initialLoss: float = Field(
        default=0.08,
        ge=0,
        lt=1,
        title="Loss at transfer",
        description="Share of the jacking force lost at transfer (elastic shortening, set).",
    )
    totalLoss: float = Field(
        default=0.20,
        ge=0,
        lt=1,
        title="Total loss",
        description="Share of the jacking force lost in all (with creep, shrinkage and "
        "relaxation).",
    )
    transferStrength: float | None = Field(
        default=None,
        gt=0,
        title="f'ci",
        description="Concrete strength at transfer [MPa]; empty: 0.7 × f'c.",
    )


class GirderSection(_Model):
    """A girder of the deck as a tee: its web below the deck slab and its share of the slab as
    the flange (the effective flange width)."""

    depth: Mm = Field(description="Overall, with the deck slab [mm].")
    webWidth: Mm = Field(title="Web width", description="bw [mm].")
    flangeWidth: float | None = Field(
        default=None,
        gt=0,
        title="Effective flange width",
        description="[mm]; empty: the girder spacing.",
    )
    concrete: Id = Field(description="Concrete material (03 Materials).")
    rebar: Id = Field(description="Reinforcing bar material (03 Materials).")
    bottomBars: int = Field(default=6, ge=0, title="Bottom bars", description="Count.")
    bottomDiameter: Mm = Field(default=32, title="Bottom bar diameter", description="[mm].")
    topBars: int = Field(
        default=0, ge=0, title="Top bars", description="Over the interior supports, count."
    )
    topDiameter: Mm = Field(default=25, title="Top bar diameter", description="[mm].")
    stirrupDiameter: Mm = Field(default=12, title="Stirrup diameter", description="[mm].")
    stirrupLegs: int = Field(default=2, ge=1, title="Stirrup legs")
    stirrupSpacing: Mm = Field(default=150, title="Stirrup spacing", description="[mm].")
    cover: Mm = Field(default=40, description="Clear cover to the stirrups [mm].")
    prestress: GirderPrestress | None = Field(
        default=None, description="Bonded strands; empty: a reinforced concrete girder."
    )


class BridgeBearing(_Model):
    """The bearings under every girder at one support line (0: the first abutment)."""

    support: int = Field(ge=0, description="Support line, 0 at the first abutment.")
    kind: Literal["fixed", "guided", "free"] = Field(
        default="guided",
        description="Fixed: held in every direction; guided: free along the bridge only; "
        "free: free in plan (vertical support only).",
        json_schema_extra=_labels(
            ["Fixed (pinned)", "Guided (free along the bridge)", "Free (sliding)"]
        ),
    )


class BridgeRating(_Model):
    """Load rating of an existing bridge (the code pack's ``bridgeDesign.rating``)."""

    condition: float = Field(
        default=1.0, gt=0, le=1, title="Condition factor", description="φc of the members."
    )
    system: float = Field(
        default=1.0, gt=0, le=1.2, title="System factor", description="φs of the girders."
    )
    wearingMeasured: bool = Field(
        default=False,
        title="Wearing surface measured",
        description="The wearing surface thickness was measured on the bridge.",
    )


class Bridge(_Model):
    """A girder (or slab) bridge: spans along the bridge, girders across it under a deck slab."""

    id: Id
    name: str = ""
    spans: list[Metres] = Field(min_length=1, description="Span lengths in order [m].")
    continuity: Literal["simple", "continuous"] = Field(
        default="simple",
        description="Simply supported spans, or one girder continuous over the supports.",
        json_schema_extra=_labels(["Simply supported spans", "Continuous"]),
    )
    carriageway: Metres = Field(description="Width between the kerbs [m].")
    girders: int = Field(default=4, ge=1, le=20, description="Girders across the bridge.")
    girderSpacing: Metres = Field(default=2.5, title="Girder spacing", description="[m].")
    deckThickness: Mm = Field(default=200, title="Deck slab thickness", description="[mm].")
    wearingSurface: float = Field(
        default=1.1,
        ge=0,
        title="Wearing surface",
        description="Surfacing and utilities (DW) [kN/m²].",
    )
    barrier: float = Field(
        default=7.0, ge=0, description="Each side, barrier or parapet (DC) [kN/m]."
    )
    analysis: Literal["lineGirder", "grillage"] = Field(
        default="grillage",
        description="Line girder (rigid cross-section share, Courbon) or deck grillage.",
        json_schema_extra=_labels(["Line girder (Courbon share)", "Deck grillage"]),
    )
    girder: GirderSection
    bearings: list[BridgeBearing] = Field(
        default_factory=list,
        description="Bearing kinds by support line; a line not listed: guided, the first: fixed.",
    )
    thermalRange: float = Field(
        default=40,
        ge=0,
        title="Temperature range",
        description="From the setting temperature to the extreme, each way [°C].",
    )
    material: Literal["concrete", "steel"] = Field(
        default="concrete",
        title="Girder material (dynamic allowance)",
        description="For a dynamic allowance by span formula.",
    )
    loadModels: list[str] = Field(
        default_factory=list,
        title="Load models",
        description="Ids of the code pack's traffic load models to use; empty: all.",
    )
    rating: BridgeRating | None = Field(
        default=None, description="Rate this existing bridge (load rating)."
    )

    @model_validator(mode="after")
    def _bearings(self) -> Bridge:
        lines = len(self.spans) + 1
        for b in self.bearings:
            if b.support >= lines:
                raise ValueError(f"{self.id}: no support line {b.support} (0 to {lines - 1})")
        return self


# ───────────────────────────────────── towers ─────────────────────────────────────


class Antenna(_Model):
    """An antenna, dish or platform on the tower."""

    name: str = ""
    elevation: float = Field(ge=0, description="Above the tower's base [m].")
    area: float = Field(
        ge=0,
        title="Effective projected area",
        description="EPA = Ca × A of the antenna (its data sheet) [m²].",
    )
    weight: float = Field(default=0, ge=0, description="[kN].")
    count: int = Field(default=1, ge=1)


class LatticeTower(_Model):
    """A self-supporting lattice tower: legs at the corners, bracing in every face."""

    id: Id
    name: str = ""
    height: Metres
    baseWidth: Metres = Field(title="Base width", description="Face width at the base [m].")
    topWidth: Metres = Field(title="Top width", description="Face width at the top [m].")
    section: Literal["square", "triangular"] = "square"
    panels: int = Field(default=10, ge=1, le=200, description="Panels up the height.")
    bracing: Literal["x", "single"] = Field(
        default="x",
        description="X bracing or a single diagonal in each panel of a face.",
        json_schema_extra=_labels(["X bracing", "Single diagonal"]),
    )
    legType: Id = Field(title="Leg type", description="Column or brace type (04 Objects).")
    bracingType: Id = Field(title="Bracing type", description="Brace type (04 Objects).")
    horizontalType: Id | None = Field(
        default=None,
        title="Horizontal type",
        description="Horizontals at the panel points; empty: none (single diagonals need them).",
    )
    antennas: list[Antenna] = Field(default_factory=list)
    linearArea: float = Field(
        default=0,
        ge=0,
        title="Feed lines and ladder area",
        description="Their projected area per m of height [m²/m].",
    )
    linearWeight: float = Field(
        default=0, ge=0, title="Feed lines and ladder weight", description="[kN/m]."
    )
    onRoof: bool = Field(
        default=False,
        title="On the building's roof",
        description="Its wind goes to the roof level of the building's analysis model.",
    )
    baseElevation: float = Field(
        default=0,
        ge=0,
        title="Base elevation",
        description="Of the tower's base above the ground [m] (the roof height for a rooftop "
        "tower).",
    )


# ───────────────────────────────────── silos, chimneys, cooling towers ───────────────────


class Silo(_Model):
    """A circular reinforced concrete silo for a stored solid (its walls checked for hoop
    tension)."""

    id: Id
    name: str = ""
    diameter: Metres = Field(description="Inside [m].")
    height: Metres = Field(
        description="Of the vertical wall, from the hopper transition to the top of the stored "
        "solid's surface [m]."
    )
    hopperHeight: float = Field(default=0, ge=0, title="Hopper height", description="[m].")
    solid: str = Field(
        default="wheat", description="Stored solid, an id of the code pack's silo solids."
    )
    wall: Literal["D1", "D2", "D3"] = Field(
        default="D2",
        title="Wall surface",
        description="D1 polished, D2 smooth (concrete), D3 rough (corrugated).",
        json_schema_extra=_labels(["D1 polished", "D2 smooth", "D3 rough"]),
    )
    wallThickness: Mm = Field(default=250, title="Wall thickness", description="[mm].")
    concrete: Id = Field(description="Concrete material (03 Materials).")
    rebar: Id = Field(description="Reinforcing bar material (03 Materials).")
    hoopDiameter: Mm = Field(default=16, title="Hoop bar diameter", description="[mm].")
    hoopSpacing: Mm = Field(
        default=150, title="Hoop spacing", description="Each face, the two faces together [mm]."
    )


class Chimney(_Model):
    """A free-standing circular chimney or stack, tapering linearly (a cantilever)."""

    id: Id
    name: str = ""
    height: Metres
    baseDiameter: Metres = Field(title="Base diameter", description="Outside [m].")
    topDiameter: Metres = Field(title="Top diameter", description="Outside [m].")
    baseThickness: Mm = Field(title="Base thickness", description="Shell [mm].")
    topThickness: Mm = Field(title="Top thickness", description="Shell [mm].")
    material: Id = Field(description="Steel or concrete material (03 Materials).")
    kind: str = Field(
        default="concrete",
        description="Kind of chimney for its damping, an id of the code pack's chimney damping "
        "(e.g. steelWelded, steelInsulated, concrete).",
    )
    liningWeight: float = Field(
        default=0, ge=0, title="Lining weight", description="Per m of height [kN/m]."
    )
    frequency: float | None = Field(
        default=None,
        gt=0,
        title="First frequency",
        description="[Hz]; empty: worked out from the shell's stiffness and mass.",
    )


class CoolingTower(_Model):
    """A hyperbolic natural draught cooling tower shell (concrete), on a fixed base ring."""

    id: Id
    name: str = ""
    height: Metres
    baseRadius: Metres = Field(title="Base radius", description="Mid-surface [m].")
    throatRadius: Metres = Field(title="Throat radius", description="Mid-surface [m].")
    throatHeight: Metres = Field(title="Throat height", description="Above the base [m].")
    topRadius: Metres = Field(title="Top radius", description="Mid-surface [m].")
    thickness: Mm = Field(default=200, description="Shell [mm].")
    concrete: Id = Field(description="Concrete material (03 Materials).")
    rebar: Id | None = Field(
        default=None,
        description="Reinforcing bar material (03 Materials), for the steel the shell's "
        "tension needs; empty: forces only.",
    )
    rings: int = Field(default=24, ge=4, le=120, description="Elements up the shell.")
    segments: int = Field(default=36, ge=8, le=180, description="Elements round the shell.")

    @model_validator(mode="after")
    def _shape(self) -> CoolingTower:
        if self.throatHeight >= self.height:
            raise ValueError(f"{self.id}: the throat must be below the top")
        if self.throatRadius >= min(self.baseRadius, self.topRadius):
            raise ValueError(f"{self.id}: the throat radius must be the least")
        return self


# ───────────────────────────────────── offshore ─────────────────────────────────────


class OffshoreStructure(_Model):
    """A fixed offshore jacket (four legs, X-braced bays) or monopile, fixed at the mudline."""

    id: Id
    name: str = ""
    kind: Literal["jacket", "monopile"] = "jacket"
    waterDepth: Metres = Field(title="Water depth", description="At still water [m].")
    deckElevation: Metres = Field(
        title="Deck elevation", description="Of the jacket's top above still water [m]."
    )
    baseWidth: Metres = Field(
        default=20, title="Base width", description="Between the legs at the mudline [m]."
    )
    topWidth: Metres = Field(
        default=12, title="Top width", description="Between the legs at the top [m]."
    )
    bays: int = Field(default=4, ge=1, le=20, description="Braced bays up the jacket.")
    legType: Id = Field(
        title="Leg type", description="Tubular column type (04 Objects); the monopile's pile."
    )
    braceType: Id | None = Field(
        default=None, title="Brace type", description="Tubular brace type (04 Objects)."
    )
    waveHeight: Metres = Field(title="Wave height", description="Design wave H [m].")
    wavePeriod: float = Field(gt=0, title="Wave period", description="T [s].")
    waveTheory: Literal["airy", "streamFunction"] = Field(
        default="streamFunction",
        title="Wave theory",
        description="Airy (linear, Wheeler stretched) or the nonlinear stream function "
        "(Fourier) wave, as accurate as Stokes' fifth order.",
        json_schema_extra=_labels(["Airy (linear)", "Stream function (nonlinear)"]),
    )
    waveDirection: float = Field(
        default=0, title="Wave direction", description="From the x axis in plan [°]."
    )
    current: float = Field(default=0, ge=0, description="Surface current speed [m/s].")
    marineGrowth: float = Field(
        default=50, ge=0, title="Marine growth", description="Thickness on the members [mm]."
    )
    deckLoad: float = Field(
        default=0, ge=0, title="Deck load", description="Topsides weight on the legs [kN]."
    )
    deckWindForce: float = Field(
        default=0,
        ge=0,
        title="Deck wind force",
        description="Wind on the topsides, along the wave [kN].",
    )


# ───────────────────────────────────── piping ─────────────────────────────────────


class PipePoint(_Model):
    """A point of the pipe's route [m]; a corner is a bend."""

    x: float
    y: float
    z: float


class PipeSupport(_Model):
    """A support at a point of the route."""

    at: int = Field(ge=0, description="Index of the route point (0: the first).")
    kind: Literal["anchor", "rest", "guide", "limit"] = Field(
        default="rest",
        description="Anchor: held in every direction (a nozzle or a fixed point); rest: "
        "vertical only; guide: vertical and across the pipe; limit: along the pipe only.",
        json_schema_extra=_labels(
            ["Anchor (fixed, nozzle)", "Rest (vertical)", "Guide", "Axial limit stop"]
        ),
    )
    nozzle: bool = Field(default=False, description="An equipment nozzle: its loads are reported.")


class PipingSystem(_Model):
    """A pipe run: its route, the pipe and its design conditions, and its supports."""

    id: Id
    name: str = ""
    route: list[PipePoint] = Field(min_length=2)
    outsideDiameter: Mm = Field(title="Outside diameter", description="[mm].")
    wallThickness: Mm = Field(title="Wall thickness", description="Nominal [mm].")
    corrosion: float = Field(
        default=1.5, ge=0, title="Corrosion allowance", description="Plus mill tolerance [mm]."
    )
    material: str = Field(
        default="A106B", description="Pipe material, an id of the code pack's piping table."
    )
    bendRadius: float | None = Field(
        default=None,
        gt=0,
        title="Bend radius",
        description="Of the bends at the corners [mm]; empty: 1.5 × the outside diameter.",
    )
    pressure: float = Field(default=0, ge=0, title="Design pressure", description="[MPa].")
    temperature: float = Field(default=150, title="Design temperature", description="[°C].")
    installation: float = Field(default=21, title="Installation temperature", description="[°C].")
    contentDensity: float = Field(
        default=1000, ge=0, title="Content density", description="[kg/m³]."
    )
    insulationWeight: float = Field(
        default=0, ge=0, title="Insulation weight", description="[kN/m]."
    )
    occasional: float = Field(
        default=0.0,
        ge=0,
        title="Occasional lateral load",
        description="Seismic or wind load across the pipe as a share of its weight (g).",
    )
    cycles: float = Field(
        default=7000, gt=0, description="Full thermal cycles in the life (for f)."
    )
    supports: list[PipeSupport] = Field(min_length=1)

    @model_validator(mode="after")
    def _supports(self) -> PipingSystem:
        for s in self.supports:
            if s.at >= len(self.route):
                raise ValueError(f"{self.id}: no route point {s.at}")
        return self


# ───────────────────────────────────── all ─────────────────────────────────────


class SpecialStructures(_Model):
    """The project's bridges and special structures (alpha 9 L9)."""

    bridges: list[Bridge] = Field(default_factory=list)
    towers: list[LatticeTower] = Field(default_factory=list, title="Lattice towers")
    silos: list[Silo] = Field(default_factory=list)
    chimneys: list[Chimney] = Field(default_factory=list)
    coolingTowers: list[CoolingTower] = Field(default_factory=list, title="Cooling towers")
    offshore: list[OffshoreStructure] = Field(default_factory=list, title="Offshore structures")
    piping: list[PipingSystem] = Field(default_factory=list, title="Piping systems")

    def is_empty(self) -> bool:
        return not any(
            (
                self.bridges,
                self.towers,
                self.silos,
                self.chimneys,
                self.coolingTowers,
                self.offshore,
                self.piping,
            )
        )

    def items(self) -> list[tuple[str, list[_Model]]]:
        """(kind, entries) of every list."""
        return [
            ("bridges", list(self.bridges)),
            ("towers", list(self.towers)),
            ("silos", list(self.silos)),
            ("chimneys", list(self.chimneys)),
            ("coolingTowers", list(self.coolingTowers)),
            ("offshore", list(self.offshore)),
            ("piping", list(self.piping)),
        ]

    @model_validator(mode="after")
    def _unique(self) -> SpecialStructures:
        ids = [e.id for _, entries in self.items() for e in entries]  # type: ignore[attr-defined]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate special structure ids: {', '.join(duplicates)}")
        return self

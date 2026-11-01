"""Stiffness modifiers and design overwrites of members (object types and floor-plan members).

``modifiers``: factors on the analysis section properties of a frame member (``A``, ``As2``,
``As3``, ``J``, ``I22``, ``I33``, ``mass``, ``weight``) or of a shell (``membrane``,
``bending``, ``mass``, ``weight``), set per object type and per member: the member's wins over
its type's, which wins over the code's cracked factor (concrete and masonry; BNBC 2020 Part 6
Sec 6.3.10.4.1 in the code pack) or 1 (:func:`resolve_modifiers`). An absent key inherits.
The stiffness factors replace the cracked factor for that property; ``mass`` and ``weight``
multiply the member's self-weight mass and self-weight load.

``designOverwrites``: :class:`DesignOverwrites` (k, unbraced lengths, framing, moment
magnifiers), read by :mod:`saengine.design.overwrites`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Framing = Literal["braced", "sway"]


class FrameModifiers(BaseModel):
    """Factors on a frame member's section properties (empty: inherit)."""

    model_config = ConfigDict(extra="forbid")

    A: float | None = Field(default=None, gt=0, le=10, title="Area A")
    As2: float | None = Field(default=None, gt=0, le=10, title="Shear area As2")
    As3: float | None = Field(default=None, gt=0, le=10, title="Shear area As3")
    J: float | None = Field(default=None, gt=0, le=10, title="Torsion J")
    I22: float | None = Field(default=None, gt=0, le=10, title="I22 (minor)")
    I33: float | None = Field(default=None, gt=0, le=10, title="I33 (major)")
    mass: float | None = Field(default=None, ge=0, le=10, title="Mass")
    weight: float | None = Field(default=None, ge=0, le=10, title="Weight")


class ShellModifiers(BaseModel):
    """Factors on a shell's (slab's, wall's) stiffness, mass and weight (empty: inherit)."""

    model_config = ConfigDict(extra="forbid")

    membrane: float | None = Field(default=None, gt=0, le=10, title="Membrane")
    bending: float | None = Field(default=None, gt=0, le=10, title="Bending")
    mass: float | None = Field(default=None, ge=0, le=10, title="Mass")
    weight: float | None = Field(default=None, ge=0, le=10, title="Weight")


class MomentMagnifiers(BaseModel):
    """Moment magnification factors given instead of worked out (RC columns, BNBC 6.3.10)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    cm: float | None = Field(
        default=None, gt=0, le=1.0, title="Cm", description="Equivalent moment factor Cm."
    )
    deltaNs: float | None = Field(
        default=None, ge=1.0, title="δns", description="Nonsway moment magnifier δns (>= 1)."
    )
    deltaS: float | None = Field(
        default=None, ge=1.0, title="δs", description="Sway moment magnifier δs (>= 1)."
    )


Warping = Literal["free", "fixed"]


class BuiltUpMember(BaseModel):
    """How the components of a built-up steel compression member are joined (B31): the
    member's profile is the built-up section; these say what the modified slenderness and
    the dimensional limits need [mm]."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    connectors: Literal["snugTight", "welded"] = Field(
        default="snugTight",
        title="Connectors",
        description="Intermediate connectors: snug-tight bolts, or welds / pretensioned bolts.",
    )
    spacing: float = Field(gt=0, title="Connector spacing", description="a, between connectors.")
    axis: Literal["x", "y"] = Field(
        default="y",
        title="Buckling axis",
        description="The member axis whose buckling shears the connectors (the profile's x or y).",
    )
    component: str | None = Field(
        default=None,
        title="Component",
        description="A section of the steel table (e.g. 'L 75x75x6'): its radii are used.",
    )
    ri: float | None = Field(
        default=None, gt=0, title="ri", description="Least radius of gyration of a component."
    )
    rib: float | None = Field(
        default=None,
        gt=0,
        title="rib",
        description="Radius of gyration of a component about its axis parallel to the buckling axis.",
    )
    separation: float | None = Field(
        default=None, gt=0, title="h", description="Distance between the components' centroids."
    )
    outsidePlate: float | None = Field(
        default=None, gt=0, title="Outside plate t", description="Thinner outside plate."
    )
    platePitch: float | None = Field(
        default=None, gt=0, title="Plate fastener spacing", description="Along the outside plate."
    )
    staggered: bool = Field(default=False, title="Staggered fasteners")
    lacing: Literal["none", "single", "double"] = Field(default="none", title="Lacing")
    lacingLength: float | None = Field(
        default=None, gt=0, title="Lacing bar length", description="Unsupported length."
    )
    lacingRadius: float | None = Field(
        default=None, gt=0, title="Lacing bar r", description="Its least radius of gyration."
    )
    tieDistance: float | None = Field(
        default=None,
        gt=0,
        title="Tie plate line distance",
        description="Between the lines of fasteners or welds connecting a tie plate.",
    )
    tieLength: float | None = Field(default=None, gt=0, title="End tie plate length")
    tieThickness: float | None = Field(default=None, gt=0, title="Tie plate thickness")


class DesignOverwrites(BaseModel):
    """Design overwrites of a member or of an object type (empty fields inherit)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    k2: float | None = Field(
        default=None,
        gt=0,
        le=10,
        title="k minor (2)",
        description="Effective length factor for bending about the profile's y-axis.",
    )
    k3: float | None = Field(
        default=None,
        gt=0,
        le=10,
        title="k major (3)",
        description="Effective length factor for bending about the profile's x-axis.",
    )
    Lb: float | None = Field(
        default=None,
        gt=0,
        title="Lb",
        description="Laterally unbraced length of the compression flange (steel) [mm].",
    )
    Lu2: float | None = Field(
        default=None,
        gt=0,
        title="Lu minor (2)",
        description="Unbraced length for bending about the profile's y-axis [mm].",
    )
    Lu3: float | None = Field(
        default=None,
        gt=0,
        title="Lu major (3)",
        description="Unbraced length for bending about the profile's x-axis [mm].",
    )
    framing: Framing | None = Field(
        default=None,
        title="Framing",
        description="Braced (nonsway) or sway; none: from the storey's stability index.",
    )
    momentMagnifiers: MomentMagnifiers | None = Field(
        default=None, title="Moment magnifiers", description="Cm, δns, δs given (RC columns)."
    )
    liveLoadReduction: float | None = Field(
        default=None,
        gt=0,
        le=1.0,
        title="Live load reduction",
        description="Live load reduction factor given instead of worked out (BNBC 2020 Part 6 "
        "Sec 2.3.13); it applies to the floor live load L even with the project's reduction off.",
    )
    # B31: steel members (saengine.design.steel).
    stiffenerSpacing: float | None = Field(
        default=None,
        gt=0,
        title="Stiffener spacing",
        description="Steel beams: clear distance a between the transverse web stiffeners [mm]; "
        "none: unstiffened web. Tension field action is counted outside the end panels where "
        "the code allows it.",
    )
    warping: Warping | None = Field(
        default=None,
        title="Warping at the ends",
        description="Steel members under torsion: the ends free to warp (default) or restrained "
        "against warping.",
    )
    builtUp: BuiltUpMember | None = Field(
        default=None,
        title="Built-up member",
        description="Steel compression members built up from shapes joined by connectors, "
        "lacing or tie plates.",
    )


def modifiers_of(item: Any) -> dict[str, float]:
    """The set ``modifiers`` of an object type or member (attribute or dict key), as a dict."""
    if item is None:
        return {}
    value = item.get("modifiers") if isinstance(item, dict) else getattr(item, "modifiers", None)
    if value is None:
        return {}
    if isinstance(value, BaseModel):
        value = value.model_dump()
    return {k: float(v) for k, v in dict(value).items() if v is not None}


def resolve_modifiers(member: Any, object_type: Any) -> dict[str, tuple[float, str]]:
    """Per property its factor and source ("member" or "type"): the member's over its type's.
    Properties set on neither are absent (the code's factor applies)."""
    found = {k: (v, "type") for k, v in modifiers_of(object_type).items()}
    found.update({k: (v, "member") for k, v in modifiers_of(member).items()})
    return found


class CorbelBars(BaseModel):
    """A set of bars of a corbel: how many and their diameter."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    count: int = Field(ge=1, title="Count")
    dia: float = Field(gt=0, title="Diameter", description="[mm]")


class Corbel(BaseModel):
    """A corbel (bracket) cast with a column that carries a beam's end (BNBC 2020 Part 6 Sec
    6.4.7). The beam's end shear from the analysis is its Vu."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    width: float = Field(gt=0, title="Width bw", description="Across the beam [mm].")
    depth: float = Field(gt=0, title="Depth h", description="At the column face [mm].")
    edgeDepth: float = Field(gt=0, title="Edge depth", description="At the outer edge [mm].")
    projection: float = Field(gt=0, title="Projection", description="From the column face [mm].")
    loadOffset: float | None = Field(
        default=None,
        gt=0,
        title="Shear span av",
        description="Column face to the bearing's centre [mm]; empty: half the projection.",
    )
    bearing: float | None = Field(
        default=None,
        gt=0,
        title="Bearing length",
        description="Bearing pad along the projection [mm]; empty: no bearing check.",
    )
    cover: float = Field(default=40.0, gt=0, title="Cover", description="[mm]")
    mainBars: CorbelBars = Field(title="Main bars As", description="Top tension bars.")
    ties: CorbelBars | None = Field(
        default=None,
        title="Closed ties Ah",
        description="Closed ties parallel to the main bars (two legs each).",
    )
    horizontalForce: float | None = Field(
        default=None,
        ge=0,
        title="Horizontal force Nuc",
        description="Factored tension on the bearing [kN]; empty: 0.2 Vu, the least of the code.",
    )


class BeamCorbels(BaseModel):
    """Corbels under a beam's ends (empty: the beam frames into the column)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    start: Corbel | None = Field(default=None, title="At the start")
    end: Corbel | None = Field(default=None, title="At the end")

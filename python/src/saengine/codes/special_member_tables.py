"""Table models of the special members of alpha 9 track L7 (each a method a pack chooses by id):

- ``steelJoists`` (:mod:`saengine.design.steel_joists`): the joist specification's rules on top
  of the open-web truss design every pack gets from its own steel checks (slenderness limits,
  the top chord's panel moments, the least web shear, bridging, the catalogue load tables);
- ``webOpenings`` (:mod:`saengine.design.steel.web_openings`): castellated and cellular beams
  (Vierendeel bending of the tees, the web posts' horizontal shear and buckling, the geometry
  limits);
- ``glass`` (:mod:`saengine.design.glass`): structural glass panels, fins and balustrades by
  partial factors with kmod (EN 16612 type) or by load resistance with the glass type and load
  duration factors (ASTM E1300 type);
- ``membranes`` (:mod:`saengine.design.membranes`): tensile membranes and cable nets, form found
  by force density, their load cases on the found form and the fabric's strength reduction;
- ``compositePlateWalls`` (:mod:`saengine.design.composite_plate_walls`): concrete-filled
  composite plate shear walls (C-PSW/CF).

A pack without a table does not cover the feature (the members are listed as not designed),
except steel joists: without ``steelJoists`` they are designed as generic open-web trusses by
the pack's steel member checks alone. Every number is the pack's; its VERIFY.md gives the
clauses.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from saengine.codes.tables import Positive, Share, TableModel, _Group

# ───────────────────────────────────── steelJoists ─────────────────────────────────────


class JoistSlenderness(_Group):
    """Largest slenderness ratios L / r of the joist's members."""

    topChordInterior: Positive = Field(description="Top chord, interior panels (in the plane).")
    topChordEnd: Positive = Field(description="Top chord, end panels.")
    compressionWeb: Positive = Field(description="Web members in compression.")
    tension: Positive = Field(description="Members in tension (chords and webs).")


class JoistPanelMoment(_Group):
    """The top chord carries the deck's load between panel points as a continuous member:
    M = w l² / divisor of the panel length l."""

    endPanel: Positive = Field(description="Divisor of the end panels.")
    interiorPanel: Positive = Field(description="Divisor of the interior panels.")


class JoistBridging(_Group):
    """Rows of bridging: the chords' slenderness between bridging lines out of the plane."""

    topChord: Positive = Field(description="Top chord L / ry between bridging lines, at most.")
    bottomChord: Positive = Field(description="Bottom chord L / ry between bridging, at most.")


class JoistLoadSpan(_Group):
    """One span of a catalogue row: the factored total load capacity and the live load for the
    catalogue's deflection limit."""

    span: Positive = Field(description="Span [m].")
    total: Positive = Field(description="Total load capacity [kN/m] (the table's format).")
    live: Positive | None = Field(default=None, description="Live load for the limit [kN/m].")


class JoistLoadRow(_Group):
    """A joist designation of the catalogue load tables."""

    designation: str
    depth: Positive = Field(description="Nominal depth [mm].")
    weight: Positive | None = Field(default=None, description="Approximate mass [kg/m].")
    spans: list[JoistLoadSpan] = Field(min_length=1)


class SteelJoistsTable(TableModel):
    """Open-web steel joists and joist girders by the joist specification of the pack. The
    chords and webs are designed by the pack's steel member checks (as every pack's generic
    open-web truss); this table adds the specification's rules. ``loadTables``: the catalogue
    rows (designation, spans) a joist with a ``designation`` is also rated by; empty: only the
    truss design."""

    method: Literal["specification"] = "specification"
    slenderness: JoistSlenderness
    panelMoment: JoistPanelMoment
    leastWebShare: Share = Field(
        description="Web members carry at least this share of the end reaction (the least "
        "vertical shear)."
    )
    webK: Positive = Field(default=1.0, description="K of the web members in compression.")
    interaction: Literal["linear", "bilinear"] = Field(
        default="linear",
        description="Top chord axial force and panel moment: linear, or the bilinear form "
        "(P/Pc ≥ 0.2: P/Pc + 8/9 M/Mc; else P/2Pc + M/Mc).",
    )
    bridging: JoistBridging
    loadFormat: Literal["lrfd", "asd"] = Field(
        default="lrfd",
        description="The catalogue's total loads: factored (compared with the strength "
        "combinations) or allowable (with the service combinations).",
    )
    loadTables: list[JoistLoadRow] = Field(default_factory=list)


# ───────────────────────────────────── webOpenings ─────────────────────────────────────


class OpeningFactors(_Group):
    """Factors on the nominal resistances (φ, or 1 / γM): axial force and bending of the
    tees, their shear, the web posts' horizontal shear and their buckling."""

    axial: Share
    flexure: Share
    shear: Share
    horizontalShear: Share
    webPost: Share


class WebPostRule(_Group):
    """The web posts' buckling.

    ``strut``: the post as a strut of width w0 (its narrowest) and the web's thickness, length
    ``strutLength`` × √(w0² + h0²), buckling by the curve α (λ̄ plateau ``strutPlateau``) under
    the stress of its moment Mwp = Vh h0 / 2 on tw w0² / 6.

    ``ward``: circular openings by the empirical moment capacity Mmax / Me = C1 (s/d0) - C2
    (s/d0)² - C3, each Ci = a + b (d0/tw) + c (d0/tw)² (``wardCoefficients`` [C1 a b c, C2 a b
    c, C3 a b c]), Me = tw (s - d0)² fy / 6; hexagonal openings by the strut."""

    method: Literal["strut", "ward"]
    strutAlpha: Positive = Field(description="Imperfection factor α of the strut.")
    strutPlateau: float = Field(ge=0, description="λ̄0 of the strut's buckling curve.")
    strutLength: Positive = Field(description="Effective length = this × √(w0² + h0²).")
    wardCoefficients: list[float] = Field(
        default_factory=list, description="ward: 9 coefficients (a, b, c of C1, C2, C3)."
    )


class OpeningGeometry(_Group):
    """Limits of the openings' geometry the method applies to."""

    openingDepthMax: Share = Field(description="d0 (or h0) / overall depth at most.")
    openingDepthMin: Share = Field(description="d0 (or h0) / overall depth at least.")
    postWidthMin: Positive = Field(description="Web post width w0 / d0 at least.")
    teeStemMin: float = Field(ge=0, description="Tee stem depth below the flange at least [mm].")
    endPostMin: Positive = Field(
        description="End post (beam end to the first opening's edge) / d0 at least."
    )


class WebOpeningsTable(TableModel):
    """Castellated (hexagonal openings) and cellular (circular openings) beams: the tees at an
    opening carry the global moment as axial forces and the shear with their Vierendeel moment;
    the web posts carry the horizontal shear and buckle."""

    method: Literal["teeChords"] = "teeChords"
    factors: OpeningFactors
    shearYield: Share = Field(description="τy = this fy (0.6, or 1/√3).")
    circularLength: Share = Field(
        description="Circular openings: the effective (rectangular) length le = this × d0 of "
        "the Vierendeel moments."
    )
    interaction: Literal["linear", "plastic"] = Field(
        default="linear",
        description="The tee's axial force and moment: N/NRd + M/MRd ≤ 1, or the plastic form "
        "(N/NRd)² + M/MRd ≤ 1 of class 1 and 2 tees.",
    )
    webPost: WebPostRule
    geometry: OpeningGeometry
    vierendeelDeflection: float = Field(
        ge=0,
        description="The analysis deflection (on the gross profile) is increased for the net "
        "section at the openings and by this share for the Vierendeel and shear deformation.",
    )


# ───────────────────────────────────────── glass ─────────────────────────────────────────


GlassKind = Literal["annealed", "heatStrengthened", "toughened", "chemicallyToughened"]
GlassAction = Literal["wind", "snow", "live", "barrier", "permanent"]


class GlassPartialFactors(_Group):
    """``partialFactors`` (EN 16612 type): fg;d = kmod ksp fg;k / γM;A + kv (fb;k - fg;k) /
    γM;v."""

    gammaA: Positive = Field(description="γM;A of the annealed glass's strength.")
    gammaV: Positive = Field(description="γM;v of the prestress.")
    annealed: Positive = Field(description="fg;k of annealed glass [MPa].")
    prestressed: dict[str, Positive] = Field(
        description="fb;k [MPa] by kind (heatStrengthened, toughened, chemicallyToughened)."
    )
    kmod: dict[GlassAction, Share] = Field(description="kmod by the action's duration.")
    ksp: dict[str, Share] = Field(description="Surface factor by surface (float, patterned ...).")
    kv: Share = Field(description="kv of the toughening process.")


class GlassLoadResistance(_Group):
    """``loadResistance`` (ASTM E1300 type): the 3-second surface stress of annealed glass
    stands for the non-factored load charts (SAEngine practice approximation); × the glass type
    factor (short or long duration) × the load duration factor (3 / d)^(1/n)."""

    annealed3s: Positive = Field(description="Allowable 3 s surface stress, annealed [MPa].")
    typeShort: dict[str, Positive] = Field(description="Glass type factors, short duration.")
    typeLong: dict[str, Positive] = Field(description="Glass type factors, long duration.")
    durationExponent: Positive = Field(description="n of (3 / d)^(1/n).")
    durations: dict[GlassAction, Positive] = Field(description="Load duration d [s].")
    deflection: list[list[float]] = Field(
        default_factory=list,
        description="Four-edge panels' centre deflection w = t exp(r0 + r1 x + r2 x²), x = "
        "ln(ln(q (ab)² / (E t⁴))): [r0, r1, r2] each as polynomial coefficients in a/b "
        "(empty: linear plate theory).",
    )


class GlassInterlayer(_Group):
    """The interlayer's shear modulus [MPa] by duration of the action (short: wind and
    barrier loads; long: snow, floors, permanent)."""

    short: Positive
    long: Positive


class GlassDeflection(_Group):
    """Deflection limits: span / divisor, and at most ``absolute`` [mm] (0: none)."""

    fourEdges: Positive
    twoEdges: Positive
    cantilever: Positive
    absolute: float = Field(ge=0)


class GlassTable(TableModel):
    """Structural glass: panels on four or two edges, cantilever balustrades and fins."""

    method: Literal["partialFactors", "loadResistance"]
    modulus: Positive = Field(description="E of glass [MPa].")
    poisson: Share
    density: Positive = Field(description="[kg/m³].")
    actionFactors: dict[GlassAction, Positive] = Field(
        description="Factors on the actions entered (characteristic) for the strength check."
    )
    partialFactors: GlassPartialFactors | None = None
    loadResistance: GlassLoadResistance | None = None
    interlayers: dict[str, GlassInterlayer] = Field(description="By interlayer (pvb ...).")
    deflection: GlassDeflection
    finBuckling: Positive = Field(
        description="Glass fins: the design moment × this ≤ the elastic critical moment Mcr "
        "(lateral-torsional buckling without imperfections)."
    )
    longActions: list[GlassAction] = Field(
        default_factory=lambda: ["snow", "live", "permanent"],
        description="Actions that take the interlayer's long-term modulus.",
    )


# ─────────────────────────────────────── membranes ───────────────────────────────────────


class MembraneCase(_Group):
    """A load case on the found form: prestress × ``prestress`` + snow × ``snow`` + wind ×
    ``wind`` (``windSign`` +1 pressure, -1 suction), checked with the strength factor of
    ``duration``."""

    name: str
    prestress: float = Field(ge=0)
    snow: float = Field(default=0, ge=0)
    wind: float = Field(default=0, ge=0)
    windSign: Literal[1, -1] = 1
    duration: Literal["short", "long"]


class MembranesTable(TableModel):
    """Tensile membranes and cable nets: the found form's load cases and the strength
    reductions of the fabric (its strip tensile strength over the factor of the case's
    duration) and of the cables (their breaking force over a factor)."""

    method: Literal["forceDensity"] = "forceDensity"
    cases: list[MembraneCase] = Field(min_length=1)
    fabricFactors: dict[Literal["short", "long"], Positive] = Field(
        description="Fabric strength reduction (overall factor) by duration."
    )
    cableFactor: Positive = Field(description="Cable breaking force / this ≥ the cable force.")
    wrinkleShare: Share = Field(
        description="A fabric stress below this share of the prestress is slack (wrinkling)."
    )
    deflectionLimit: float = Field(
        ge=0, description="Largest movement under a case as span / this (0: not checked)."
    )


# ─────────────────────────────────── compositePlateWalls ───────────────────────────────────


class FilledWallFactors(_Group):
    shear: Share
    flexure: Share
    compression: Share


class FilledWallLimits(_Group):
    """Detailing limits of concrete-filled composite plate shear walls."""

    plateSlenderness: Positive = Field(
        description="Tie spacing / plate thickness ≤ this √(Es / Fy) (the plate's buckling)."
    )
    tieSpacing: Positive = Field(
        description="s / tp ≤ this √(Es / ((2α + 1) Fy)), α = alphaFactor (tsc/tp - 2)(tp/dtie)^"
        "alphaExponent (the ties' spacing for composite action)."
    )
    alphaFactor: Positive
    alphaExponent: Positive
    thicknessMin: Positive = Field(description="Wall thickness tsc at least [mm].")
    thicknessMax: Positive = Field(description="Wall thickness tsc at most [mm].")
    steelRatioMin: Share = Field(description="ρ = 2 tp / tsc at least.")
    steelRatioMax: Share = Field(description="ρ at most.")
    plateMin: Positive = Field(description="Plate thickness at least [mm].")


class CompositePlateWallsTable(TableModel):
    """Concrete-filled composite plate shear walls (C-PSW/CF): the in-plane shear of the
    composite section, the axial force and in-plane flexure by the plastic stress
    distribution, the plate slenderness and the ties."""

    method: Literal["filledPlates"] = "filledPlates"
    factors: FilledWallFactors
    concreteBlock: Share = Field(description="Concrete stress of the plastic block = this f'c.")
    crackedConcrete: Positive = Field(
        description="In-plane shear: Kc = this × Ec Ac Es As / (compositeShear Es As + Ec Ac), "
        "Ks = Gs As, Vn = (Ks + Kc) / √(3 Ks² + Kc²) As Fy."
    )
    compositeShear: Positive = Field(description="The divisor's factor on Es As of Kc.")
    limits: FilledWallLimits

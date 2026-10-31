"""Soil report (``01 Soil Report/soil-report.json``): boreholes, SPT records and lab data.

Part 1 is upstream of the foundation design: the footing design and the substructure read the
values computed from it (site class, allowable bearing pressure, settlement, liquefaction,
subgrade modulus, pile parameters; see :mod:`saengine.soil`) and never write it. The file
stores only what the soil investigation measured and the design choices; every computed value
is worked out on demand.

Units: mm for lengths, depths and positions (depths are measured down from the borehole's
ground), kN/m³ for unit weights, kPa for strengths, MPa for moduli, % for ratios and contents,
degrees for friction angles.

The log sheet: an SPT record keeps the blows of its three 150 mm increments (seating, N1, N2;
N = N1 + N2) or its refusal, with the sample number and recovery; a sample keeps its number,
type and depth range and the laboratory tests as optional groups (grading, unconfined
compression, direct shear, triaxial, consolidation, permeability, chemistry), from which
:mod:`saengine.soil.lab` derives the values the engine reads (cu, c', φ', fines, PI, Cc, Cr,
e0, unit weight, the OCR from σ'p) when the sample does not give them itself. A layer takes the
values its log does not give from the samples within it (their mean; see
:mod:`saengine.soil.profile`). All of it is optional: files written before (an SPT record with
only ``depth`` and ``N``, a sample with flat values) load unchanged and mean the same.

The map: ``site`` places the site on the map (WGS 84) and georeferences the project grid:
the project point (x, y) lies at (lat, lon), the grid turned ``rotation`` from north. A borehole is located in project x/y
(``position: "project"``, the default), latitude/longitude (``"wgs84"``) or Bangladesh
Transverse Mercator (``"btm"``, EPSG:9678); x/y, which the engine reads, are then worked out
on loading (:mod:`saengine.gis.crs`).
"""

from __future__ import annotations

import itertools
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title

SCHEMA_ID = "saengine.soilReport/1"


def _m(mm: float) -> str:
    """A depth [mm] in metres for a message ("12.5 m"): engineers read logs in metres."""
    return f"{round(mm / 1000, 3):g} m"


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
            raise ValueError(f"bottom {_m(self.bottom)} must be below the top {_m(self.top)}")
        return self


#: Blows of one 150 mm increment of the SPT drive.
Blows = Annotated[int, Field(ge=0, le=300)]

#: The SPT drive after the seating drive [mm]: N counts the blows for it.
SPT_TEST_DRIVE = 300.0

#: The largest N the model keeps (entered, from the increments or extrapolated).
SPT_MAX_N = 300


class SptRefusal(_Model):
    """The test drive stopped before 300 mm (e.g. "50/100 mm": 50 blows for 100 mm)."""

    blows: int = Field(ge=1, le=300, description="Blows of the test drive when it stopped.")
    penetration: float = Field(
        gt=0,
        lt=SPT_TEST_DRIVE,
        description="Penetration of the test drive (after the seating drive) for those blows [mm].",
    )

    @property
    def extrapolated(self) -> int:
        """The blows for 300 mm at the same rate, at most 300."""
        return min(SPT_MAX_N, round(self.blows * SPT_TEST_DRIVE / self.penetration))

    @property
    def text(self) -> str:
        return f"{self.blows}/{self.penetration:g} mm"


class SptRecord(_Model):
    """A standard penetration test (ASTM D1586) as the log sheet records it: the blows of the
    three 150 mm increments (the seating drive, then N1 and N2 that make N), or a refusal.

    ``N`` is the field blow count as entered; :attr:`blows` is the one the engine uses: the
    entered N, else the one worked out (:attr:`derived`): ``N1 + N2`` from the increments, a
    refusal given as blows and penetration ("50/100 mm") extrapolated to 300 mm (150), a refusal
    given only as ``true`` (penetration not recorded) as the blows driven, N1 + N2 (N2 may be
    empty), which errs low (an entered N at or above it is the extrapolated count, not a
    mismatch); every N is at most 300. The worked-out N is never stored in ``N``, so correcting the
    increments later changes it. An entered N that differs from the worked-out one is kept and
    reported by :func:`check`, as are other inconsistencies (:attr:`issues`); only a record that
    gives no N at all is invalid. Old records with only ``depth`` and ``N`` stay valid.
    """

    depth: Depth = Field(description="Depth of the test below the borehole's ground [mm].")
    depthTo: Depth | None = Field(
        default=None,
        title="Depth to",
        description="Bottom of the drive [mm]; the depth plus 450 mm when empty.",
    )
    N: int | None = Field(
        default=None,
        ge=0,
        le=300,
        title="Field N",
        description="Blow count as measured, uncorrected [blows/300 mm]. Empty: worked out as "
        "N1 + N2 from the increments, or a refusal as the extrapolated count (e.g. 50 blows for "
        "150 mm as 100); an entered N that differs is used and reported.",
    )
    seat: Blows | None = Field(
        default=None,
        title="Seating 150 mm",
        description="Blows for the first 150 mm, the seating drive (not counted in N).",
    )
    N1: Blows | None = Field(
        default=None, title="N1, 2nd 150 mm", description="Blows for the second 150 mm."
    )
    N2: Blows | None = Field(
        default=None, title="N2, 3rd 150 mm", description="Blows for the third 150 mm."
    )
    refusal: SptRefusal | bool | None = Field(
        default=None,
        description="The test drive stopped short of 300 mm: its blows and penetration (N2 is "
        "then empty; N1 may be given when the first 150 mm were completed), or true when the "
        "penetration was not recorded.",
    )
    sampleNumber: str | None = Field(
        default=None, max_length=32, title="Sample number", description="E.g. D-3, SPT-3."
    )
    recovery: Percent | None = Field(
        default=None,
        title="Recovery",
        description="Length recovered in the split spoon over the length driven [%].",
    )
    energyRatio: float | None = Field(
        default=None,
        gt=0,
        le=100,
        title="Energy ratio ER",
        description="Hammer energy of this test [%]; overrides the report's hammer energy.",
    )

    @model_validator(mode="after")
    def _blows(self) -> SptRecord:
        # Only a record that gives no N at all is unreadable; every other inconsistency is
        # kept as entered and reported by ``issues`` (and so by :func:`check`). ``N`` is never
        # written here: it stays what the engineer entered, so a saved file does not freeze a
        # derived N that a later correction of N1, N2 or the refusal would leave stale.
        if self.N is None and self.derived is None:
            if self.N1 is not None or self.N2 is not None:
                raise ValueError("N needs both increments N1 and N2 (or a refusal)")
            raise ValueError("an SPT record needs N, the increments N1 and N2, or a refusal")
        return self

    @property
    def derived(self) -> int | None:
        """N worked out from the increments or the refusal, or None when they give none."""
        if isinstance(self.refusal, SptRefusal):
            return self.refusal.extrapolated
        total = self._increments
        return None if total is None else min(SPT_MAX_N, total)

    @property
    def _increments(self) -> int | None:
        """N1 + N2 as entered (not capped), or None when they give no N (or a refusal with
        blows and penetration gives it)."""
        if isinstance(self.refusal, SptRefusal):
            return None
        if self.refusal is True and (self.N1 is not None or self.N2 is not None):
            return (self.N1 or 0) + (self.N2 or 0)
        if self.N1 is not None and self.N2 is not None:
            return self.N1 + self.N2
        return None

    @property
    def blows(self) -> int:
        """The N the engine uses: the entered N, else the one worked out (always one)."""
        if self.N is not None:
            return self.N
        return self.derived or 0

    @property
    def mismatch(self) -> str | None:
        """The problem when an entered N differs from the worked-out one (the entered N is
        used), else None."""
        derived = self.derived
        if self.N is None or derived is None or self.N == derived:
            return None
        if isinstance(self.refusal, SptRefusal):
            return (
                f"N is {self.N} but the refusal {self.refusal.text} scales to {derived} over "
                f"300 mm; N {self.N} is used"
            )
        n2 = self.N2 or 0
        if self.refusal is True:
            # The penetration was not recorded: N1 + N2 are the blows driven, a lower bound of
            # the extrapolated N the engineer may enter (e.g. 50 blows for 150 mm as 100).
            if self.N >= derived:
                return None
            return (
                f"N is {self.N} but the refusal's increments already add up to N1 + N2 = "
                f"{self.N1 or 0} + {n2} = {derived}; N {self.N} is used"
            )
        total = self._increments
        return f"N is {self.N} but N1 + N2 = {self.N1 or 0} + {n2} = {total}; N {self.N} is used"

    @property
    def issues(self) -> list[str]:
        """Inconsistencies of the record that do not stop it being used."""
        found = []
        refusal = self.refusal if isinstance(self.refusal, SptRefusal) else None
        if refusal is not None:
            if self.N2 is not None:
                found.append(
                    f"a refusal {refusal.text} and N2 {self.N2}: the test drive did not reach "
                    "300 mm, N2 is ignored"
                )
            if self.N1 is not None and (self.N1 > refusal.blows or refusal.penetration <= 150):
                found.append(
                    f"N1 {self.N1} does not fit the refusal {refusal.text}: N1 is part of its "
                    "blows, and the first 150 mm were completed"
                )
        elif self.refusal is not True and (self.N1 is None) != (self.N2 is None):
            given = "N1" if self.N1 is not None else "N2"
            found.append(f"only {given} of the increments is given; the entered N {self.N} is used")
        total = self._increments
        if total is not None and total > SPT_MAX_N and self.N is None:
            found.append(
                f"N1 + N2 = {self.N1 or 0} + {self.N2 or 0} = {total} is more than "
                f"{SPT_MAX_N}; N {SPT_MAX_N} is used"
            )
        if self.mismatch is not None:
            found.append(self.mismatch)
        if self.depthTo is not None and self.depthTo < self.depth:
            found.append(
                f"depth to {_m(self.depthTo)} is above the depth {_m(self.depth)}; it is ignored"
            )
        return found


#: Sample types of the log sheets (``Sample.type`` takes these or any other text).
SAMPLE_TYPES = {
    "SPT": "SPT split spoon (disturbed)",
    "UD": "Undisturbed (Shelby tube)",
    "disturbed": "Disturbed (bulk, auger, wash)",
    "core": "Rock core",
}


class SievePoint(_Model):
    size: float = Field(gt=0, le=1000, description="Sieve opening or particle size [mm].")
    passing: Percent = Field(description="Percent finer by mass [%].")


class Grading(_Model):
    """Grain size distribution (ASTM D6913 sieves, D7928 hydrometer): one curve."""

    sieves: list[SievePoint] = Field(
        default_factory=list,
        description="Sizes [mm] with the percent passing; the hydrometer's sizes below 0.075 mm "
        "may follow. Fines, D10/D30/D60, Cu, Cc and the USCS group are derived.",
    )

    @property
    def problem(self) -> str | None:
        """Why the curve cannot be used (it is then ignored and reported by :func:`check`),
        else None: a repeated sieve size, or more passing a smaller sieve than a larger one."""
        points = sorted(self.sieves, key=lambda p: -p.size)
        if len({p.size for p in points}) != len(points):
            return "grain size: two sieves of the same size; the curve is ignored"
        for coarse, fine in itertools.pairwise(points):
            if fine.passing > coarse.passing + 1e-9:
                return (
                    f"grain size: {fine.passing:g} % passing {fine.size:g} mm is more than "
                    f"{coarse.passing:g} % passing {coarse.size:g} mm; the curve is ignored"
                )
        return None


class Ucs(_Model):
    """Unconfined compression test (ASTM D2166)."""

    qu: Strength = Field(title="Unconfined strength qu", description="[kPa]; cu = qu/2.")
    strain: float | None = Field(
        default=None, ge=0, le=100, title="Strain at failure", description="[%]"
    )


class ShearPoint(_Model):
    normal: Strength = Field(description="Normal stress σn [kPa].")
    shear: Strength = Field(description="Peak shear stress τ [kPa].")


class DirectShear(_Model):
    """Direct shear test (ASTM D3080), drained: c' and φ', or the specimens to fit them."""

    c: Strength | None = Field(default=None, title="Cohesion c'", description="[kPa]")
    phi: float | None = Field(
        default=None, ge=0, le=50, title="Friction angle φ'", description="[°]"
    )
    specimens: list[ShearPoint] = Field(
        default_factory=list,
        description="(σn, τ) of the specimens; c' and φ' are fitted when not entered.",
    )


TRIAXIAL_TYPES = {
    "UU": "Unconsolidated undrained (ASTM D2850)",
    "CU": "Consolidated undrained (ASTM D4767)",
    "CD": "Consolidated drained (ASTM D7181)",
}


class TriaxialSpecimen(_Model):
    cell: Strength = Field(title="Cell pressure σ3", description="[kPa]")
    deviator: Strength = Field(title="Deviator stress σ1 - σ3", description="At failure [kPa].")
    porePressure: float | None = Field(
        default=None,
        ge=-1000,
        le=10000,
        title="Pore pressure u",
        description="At failure, CU [kPa].",
    )


class Triaxial(_Model):
    """Triaxial test: the results (cu; c and φ), or the specimens they are worked out from."""

    type: Literal["UU", "CU", "CD"] | None = Field(
        default=None, title="Test type", json_schema_extra=_labels(list(TRIAXIAL_TYPES.values()))
    )
    cu: Strength | None = Field(
        default=None, title="Undrained shear strength cu", description="UU [kPa]."
    )
    c: Strength | None = Field(default=None, title="Cohesion c", description="[kPa]")
    phi: float | None = Field(
        default=None, ge=0, le=50, title="Friction angle φ", description="[°]"
    )
    effective: bool = Field(
        default=True,
        title="Effective stress",
        description="c and φ are effective (c', φ'): CD, or CU with pore pressures measured. "
        "Total-stress CU parameters do not feed the drained design.",
    )
    specimens: list[TriaxialSpecimen] = Field(
        default_factory=list,
        description="UU: cu is the mean (σ1 - σ3)/2; CD, CU: c and φ are fitted to the failure "
        "points (σ' = σ - u for CU with the pore pressures) when not entered.",
    )


class ConsolidationPoint(_Model):
    pressure: float = Field(gt=0, description="Effective vertical pressure σ' [kPa].")
    e: float = Field(gt=0, le=20, description="Void ratio at the end of the increment.")


class Consolidation(_Model):
    """One-dimensional consolidation (oedometer, ASTM D2435)."""

    e0: float | None = Field(default=None, gt=0, le=20, title="Initial void ratio e0")
    Cc: float | None = Field(default=None, ge=0, le=10, title="Compression index Cc")
    Cr: float | None = Field(default=None, ge=0, le=10, title="Recompression index Cr")
    preconsolidation: Strength | None = Field(
        default=None,
        title="Preconsolidation pressure σ'p",
        description="[kPa]; OCR = σ'p/σ'v0 at the sample.",
    )
    cv: float | None = Field(
        default=None, gt=0, title="Coefficient of consolidation cv", description="[m²/year]"
    )
    points: list[ConsolidationPoint] = Field(
        default_factory=list,
        title="e-log p points",
        description="In test order; Cc (loading beyond σ'p) and Cr (unloading) are fitted when "
        "not entered.",
    )


class Permeability(_Model):
    k: float = Field(gt=0, le=1, title="Coefficient of permeability k", description="[m/s]")
    method: str | None = Field(
        default=None, description="E.g. constant head, falling head, field (Lefranc)."
    )


class Chemistry(_Model):
    """Chemical tests of the soil or the ground water, for the durability of buried concrete."""

    sulphateSoil: float | None = Field(
        default=None, ge=0, le=100, title="Water-soluble SO4 in soil", description="[% by mass]"
    )
    sulphateWater: float | None = Field(
        default=None, ge=0, title="SO4 in water", description="[mg/L, ppm]"
    )
    chlorideSoil: float | None = Field(
        default=None, ge=0, le=100, title="Chloride Cl in soil", description="[% by mass]"
    )
    chlorideWater: float | None = Field(
        default=None, ge=0, title="Chloride Cl in water", description="[mg/L, ppm]"
    )
    pH: float | None = Field(default=None, ge=0, le=14, title="pH")
    organicContent: Percent | None = Field(
        default=None, title="Organic content", description="Loss on ignition [% by mass]."
    )


class Sample(_Model):
    """A sample tested in the laboratory. Its values fill in the layer's where the log has none."""

    number: str | None = Field(
        default=None, max_length=32, title="Sample number", description="E.g. UD-2, D-5."
    )
    depth: Depth = Field(
        description="Depth of the sample (its top) below the borehole's ground [mm]."
    )
    depthTo: Depth | None = Field(
        default=None, title="Depth to", description="Bottom of the sample [mm]."
    )
    type: str | None = Field(
        default=None,
        title="Sample type",
        description="SPT (split spoon, disturbed), UD (Shelby tube), disturbed, core, or other "
        "text.",
        json_schema_extra={"examples": list(SAMPLE_TYPES)},
    )
    recovery: Percent | None = Field(
        default=None,
        title="Recovery",
        description="Length recovered over the length driven or pushed [%].",
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
    nonPlastic: bool = Field(
        default=False, title="Non-plastic", description="The fines have no plastic limit (NP)."
    )
    dryUnitWeight: UnitWeight | None = Field(
        default=None, title="Dry unit weight γd", description="[kN/m³]"
    )
    specificGravity: float | None = Field(
        default=None, ge=1.5, le=4, title="Specific gravity Gs", description="Of the solids."
    )
    grainSize: Grading | None = Field(default=None, title="Grain size distribution")
    ucs: Ucs | None = Field(default=None, title="Unconfined compression")
    directShear: DirectShear | None = Field(default=None, title="Direct shear")
    triaxial: Triaxial | None = None
    consolidation: Consolidation | None = None
    permeability: Permeability | None = None
    chemistry: Chemistry | None = None

    # Like an SPT record, a sample with a data-entry mistake stays readable: the mistake is
    # reported by :func:`check` (``issues``) and the inconsistent part is ignored, so one typo
    # does not make the whole soil report unreadable.

    @property
    def grading(self) -> Grading | None:
        """The grain size curve when it can be used, else None (see ``Grading.problem``)."""
        if self.grainSize is None or self.grainSize.problem is not None:
            return None
        return self.grainSize

    @property
    def issues(self) -> list[str]:
        """Inconsistencies of the sample that do not stop it being used."""
        found = []
        if self.depthTo is not None and self.depthTo < self.depth:
            found.append(
                f"depth to {_m(self.depthTo)} is above the depth {_m(self.depth)}; it is ignored"
            )
        if self.grainSize is not None and self.grainSize.problem is not None:
            found.append(self.grainSize.problem)
        return found

    @property
    def mid(self) -> float:
        """Mid-depth of the sample [mm] (its depth when the bottom is missing or above it)."""
        if self.depthTo is None or self.depthTo < self.depth:
            return self.depth
        return (self.depth + self.depthTo) / 2


#: Coordinate systems a borehole's plan position can be given in (``Borehole.position``).
POSITIONS = {
    "project": "Project x/y [mm]",
    "wgs84": "Latitude/longitude (WGS 84)",
    "btm": "Bangladesh Transverse Mercator (EPSG:9678) [m]",
}


class Planning(_Model):
    """What the planning check of the plot needs beyond its shape: the use (a key of the code
    pack's ``planning.uses``), the road it faces, and the building's height, storeys and areas
    where the building model does not give them."""

    use: str = Field(
        default="A1-A4",
        min_length=1,
        title="Use",
        description="Use class of the planning rules, e.g. A1-A4 (residential), F1 (office).",
    )
    roadWidth: Depth | None = Field(
        default=None, title="Road width", description="Width of the road the plot faces [mm]."
    )
    height: Depth | None = Field(
        default=None,
        title="Building height",
        description="Above the ground [mm]; empty: from the building model's stories.",
    )
    storeys: int | None = Field(
        default=None, ge=1, title="Storeys", description="Empty: from the building model."
    )
    groundCoverage: float | None = Field(
        default=None,
        ge=0,
        title="Ground coverage",
        description="Building footprint [m²]; empty: the building model's slabs on plan.",
    )
    floorArea: float | None = Field(
        default=None,
        ge=0,
        title="Gross floor area",
        description="[m²]; empty: the sum of the building model's storeys.",
    )
    excludedArea: float = Field(
        default=0,
        ge=0,
        title="Excluded floor area",
        description="Floor area the rules leave out of FAR (stair and lift rooms over the roof, "
        "parking, services) [m²].",
    )


class Plot(_Model):
    """The plot: its corners in the project grid (when the site boundary is not given in
    latitude/longitude), the side facing the road and the setbacks that leave the buildable
    envelope (``saengine.gis.plot``)."""

    points: list[Annotated[list[float], Field(min_length=2, max_length=2)]] = Field(
        default_factory=list,
        title="Corners",
        description="Plot corners in the project coordinates [mm], in order around the plot: "
        "drawn on the project grid or typed as a rectangle. Used when the site boundary "
        "(latitude/longitude) is empty.",
    )
    road: int | None = Field(
        default=None,
        ge=0,
        title="Road side",
        description="The side facing the road: the side from corner `road` to the next one "
        "(0 is the first corner's).",
    )
    front: Depth = Field(
        default=0, title="Front setback", description="From the side facing the road [mm]."
    )
    rear: Depth = Field(
        default=0, title="Rear setback", description="From the side opposite the road [mm]."
    )
    side: Depth = Field(default=0, title="Side setback", description="From each other side [mm].")
    planning: Planning | None = Field(
        default=None,
        title="Planning compliance",
        description="The use and road the plot is checked for against the planning rules (FAR, "
        "ground coverage, setbacks; saengine.gis.planning).",
    )


class Site(_Model):
    """The site on the map (WGS 84, EPSG:4326). Its point georeferences the project grid: the
    project point (x, y) lies at (lat, lon), and the project +Y axis points ``rotation``
    degrees clockwise from true north."""

    lat: float | None = Field(
        default=None, ge=-90, le=90, title="Latitude", description="Of the site point [°]."
    )
    lon: float | None = Field(
        default=None, ge=-180, le=180, title="Longitude", description="Of the site point [°]."
    )
    x: float = Field(default=0, description="The project point at the site point [mm].")
    y: float = Field(default=0, description="The project point at the site point [mm].")
    rotation: float = Field(
        default=0,
        ge=-360,
        le=360,
        title="Grid rotation",
        description="Direction of the project +Y axis, clockwise from true north [°]; 0 when "
        "+Y points north and +X east.",
    )
    address: str | None = Field(default=None, max_length=300)
    boundary: list[Annotated[list[float], Field(min_length=2, max_length=2)]] = Field(
        default_factory=list,
        title="Site boundary",
        description="Plot boundary as [longitude, latitude] points (WGS 84): drawn on the map "
        "or imported from QGIS. When given, it is the plot (its corners in the project grid are "
        "worked out through the site point).",
    )
    plot: Plot | None = Field(
        default=None,
        description="The plot's corners in the project grid (without a boundary), the road side "
        "and the setbacks.",
    )

    @model_validator(mode="after")
    def _road(self) -> Site:
        corners = len(self.boundary) or (len(self.plot.points) if self.plot else 0)
        if self.plot is not None and self.plot.road is not None and self.plot.road >= corners:
            raise ValueError(
                f"plot.road: the plot has {corners} sides; the road side is one of 0 to "
                f"{max(corners - 1, 0)}"
            )
        return self

    @property
    def georeferenced(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def point(self) -> tuple[float, float] | None:
        """(latitude, longitude) of the site, or None."""
        return (self.lat, self.lon) if self.lat is not None and self.lon is not None else None


class Borehole(_Model):
    id: str = Field(min_length=1, max_length=64, title="ID", description="E.g. BH-1.")
    x: float = Field(
        default=0,
        description="Plan position in the project coordinates [mm]; worked out from the "
        "position the borehole is given in when that is not the project grid.",
    )
    y: float = Field(
        default=0,
        description="Plan position in the project coordinates [mm]; worked out from the "
        "position the borehole is given in when that is not the project grid.",
    )
    position: Literal["project", "wgs84", "btm"] = Field(
        default="project",
        title="Position given in",
        description="The coordinates that locate the borehole; the others are worked out "
        "through the site point. When not given: latitude/longitude if the borehole has both, "
        "else BTM if it has the easting and northing, else the project grid.",
        json_schema_extra=_labels(list(POSITIONS.values())),
    )
    lat: float | None = Field(
        default=None, ge=-90, le=90, title="Latitude", description="WGS 84 [°]."
    )
    lon: float | None = Field(
        default=None, ge=-180, le=180, title="Longitude", description="WGS 84 [°]."
    )
    easting: float | None = Field(
        default=None, title="BTM easting", description="Bangladesh Transverse Mercator [m]."
    )
    northing: float | None = Field(
        default=None, title="BTM northing", description="Bangladesh Transverse Mercator [m]."
    )
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
    excludeFromSite: bool | None = Field(
        default=None,
        title="Leave out of the site table",
        description="The site's bearing table takes the lowest of the other boreholes (one far "
        "from the building, say); the borehole's own results stay.",
    )
    date: str | None = Field(default=None, max_length=64, title="Date drilled")
    method: str | None = Field(
        default=None, max_length=200, description="E.g. wash boring, auger, rotary."
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

    @model_validator(mode="before")
    @classmethod
    def _position(cls, data: Any) -> Any:
        if isinstance(data, dict) and "position" not in data:
            if data.get("lat") is not None and data.get("lon") is not None:
                data = {**data, "position": "wgs84"}
            elif data.get("easting") is not None and data.get("northing") is not None:
                data = {**data, "position": "btm"}
        return data

    @model_validator(mode="after")
    def _log(self) -> Borehole:
        problems = []
        for i, (upper, lower) in enumerate(zip(self.layers, self.layers[1:], strict=False)):
            if lower.top < upper.bottom - TOLERANCE:
                problems.append(
                    f"layers {i + 1} and {i + 2} overlap ({_m(lower.top)} is above "
                    f"{_m(upper.bottom)}); list the layers from the top down"
                )
            elif lower.top > upper.bottom + TOLERANCE:
                problems.append(
                    f"gap between layers {i + 1} and {i + 2} ({_m(upper.bottom)} to "
                    f"{_m(lower.top)}); the layers must be contiguous"
                )
        if self.position == "wgs84" and (self.lat is None or self.lon is None):
            problems.append("a position in latitude/longitude needs both")
        if self.position == "btm" and (self.easting is None or self.northing is None):
            problems.append("a position in BTM needs the easting and the northing")
        if self.layers and self.layers[0].top > TOLERANCE:
            problems.append(f"the first layer starts at {_m(self.layers[0].top)}, not at 0 m")
        if (
            self.layers
            and self.depth is not None
            and self.layers[-1].bottom > self.depth + TOLERANCE
        ):
            problems.append(
                f"the layers go down to {_m(self.layers[-1].bottom)}, below the "
                f"termination depth {_m(self.depth)}"
            )
        bottom = self.bottom
        for kind, records in (("SPT", self.spt), ("sample", self.samples)):
            for record in records:
                if record.depth > bottom + TOLERANCE:
                    problems.append(
                        f"{kind} at {_m(record.depth)} is below the bottom of the borehole "
                        f"({_m(bottom)})"
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


class Fence(_Model):
    """A fence diagram: a vertical section through the 3D stratigraphy along boreholes."""

    id: str = Field(min_length=1, max_length=64, title="ID", description="E.g. A.")
    boreholes: list[str] = Field(
        min_length=2, description="The boreholes it passes through, in order."
    )


class Stratigraphy(_Model):
    """How the strata of the boreholes are correlated into units, and the fence diagrams."""

    correlateBy: Literal["soilType", "uscs"] = Field(
        default="soilType",
        title="Correlate by",
        description="Layers of one soil type (or one USCS group, where the log gives it) are one "
        "stratum; strata are matched between boreholes in order from the top.",
        json_schema_extra=_labels(["Soil type", "USCS group"]),
    )
    fences: list[Fence] = Field(
        default_factory=list,
        description="Fence diagrams; when none, one through all boreholes along the site.",
    )


class SoilReport(_Model):
    schema_: Literal["saengine.soilReport/1"] = Field(default=SCHEMA_ID, alias="schema")
    report: ReportInfo = Field(default_factory=ReportInfo)
    groundLevel: float = Field(
        default=0.0,
        title="Ground level",
        description="Elevation of the existing ground in the project datum [mm].",
    )
    site: Site | None = Field(default=None, description="The site on the map.")
    boreholes: list[Borehole] = Field(default_factory=list)
    design: Design = Field(default_factory=Design)
    stratigraphy: Stratigraphy | None = Field(
        default=None,
        description="How the boreholes' strata are correlated into the 3D model, and the fence "
        "diagrams drawn through it.",
    )

    @model_validator(mode="after")
    def _ids(self) -> SoilReport:
        ids = [b.id for b in self.boreholes]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"two boreholes are called {', '.join(duplicates)}")
        if self.stratigraphy is not None:
            for fence in self.stratigraphy.fences:
                missing = [b for b in fence.boreholes if b not in ids]
                if missing:
                    raise ValueError(f"fence {fence.id}: no borehole {', '.join(missing)}")
        if self.site is not None and self.site.georeferenced:
            # The engine reads x/y: work them out of the coordinates a borehole is given in.
            from saengine.gis.crs import Grid

            grid = Grid(self.site)
            for borehole in self.boreholes:
                if borehole.position == "wgs84":
                    borehole.x, borehole.y = grid.from_wgs84(borehole.lat, borehole.lon)  # type: ignore[arg-type]
                elif borehole.position == "btm":
                    borehole.x, borehole.y = grid.from_btm(borehole.easting, borehole.northing)  # type: ignore[arg-type]
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
    georeferenced = report.site is not None and report.site.georeferenced
    for borehole in report.boreholes:
        if not borehole.layers:
            problems.append(f"{borehole.id}: there are no layers")
        if not borehole.spt:
            problems.append(f"{borehole.id}: there are no SPT records")
        if borehole.position != "project" and not georeferenced:
            problems.append(
                f"{borehole.id}: its position is in {POSITIONS[borehole.position]}, but the site "
                "has no latitude/longitude to place it in the project grid: x/y are used as stored"
            )
        for record in borehole.spt:
            for issue in record.issues:
                problems.append(f"{borehole.id}: SPT at {_m(record.depth)}: {issue}")
        for i, sample in enumerate(borehole.samples):
            name = sample.number or f"sample {i + 1}"
            for issue in sample.issues:
                problems.append(f"{borehole.id}: {name}: {issue}")
            if (
                sample.liquidLimit is not None
                and sample.plasticLimit is not None
                and sample.plasticLimit > sample.liquidLimit
            ):
                problems.append(
                    f"{borehole.id}: {name}: the plastic limit {sample.plasticLimit:g} % is above "
                    f"the liquid limit {sample.liquidLimit:g} %"
                )
            if sample.nonPlastic and sample.plasticLimit is not None:
                problems.append(f"{borehole.id}: {name}: non-plastic but has a plastic limit")
    return problems

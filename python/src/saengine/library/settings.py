"""Project settings (``02 Project Settings/project-settings.json``): codes, occupancy, site and loads.

Part 2 is upstream of the floor plan, the building model and the analysis: they read these
settings and never write them. BNBC 2020 is the governing code; its tables (see
:mod:`saengine.library.bnbc`) give the defaults, and every derived value can be overridden.

Units: kN/m² for area loads, m/s for wind speed.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class Codes(_Model):
    """The codes the design follows. BNBC 2020 Part 6 adopts ACI 318 for concrete and AISC 360 for steel."""

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
        description="District town; sets the seismic zone and the basic wind speed.",
        json_schema_extra=_labels(
            [v.name for v in bnbc.LOCATIONS.values()] + ["Custom (enter Z and V)"]
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
        description="Overrides the location's value.",
    )
    windSpeed: float | None = Field(
        default=None,
        gt=0,
        title="Basic wind speed",
        description="Overrides the location's value [m/s].",
    )


class Seismic(_Model):
    system: SystemId = Field(  # type: ignore[valid-type]
        default="rcImf",
        title="Structural system",
        description="Seismic force-resisting system (Table 6.2.19).",
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


class Wind(_Model):
    exposure: Literal["A", "B", "C"] = Field(
        default="A",
        description="Exposure category (6.2.9.3).",
        json_schema_extra=_labels([f"{k}: {v}" for k, v in bnbc.EXPOSURES.items()]),
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
        default=1000, ge=100, title="Mesh size", description="Largest side of a shell element [mm]."
    )
    responseSpectrum: bool = Field(
        default=True,
        title="Response spectrum",
        description="Add response spectrum analyses in X and Y with the BNBC design spectrum of "
        "the site (CQC of the modes).",
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
    D: float = 0
    L: float = 0
    Lr: float = 0
    WX: float = 0
    WY: float = 0
    EX: float = 0
    EY: float = 0


class ProjectSettings(_Model):
    schema_: Literal["saengine.projectSettings/1"] = Field(default=SCHEMA_ID, alias="schema")
    project: ProjectInfo
    codes: Codes = Field(default_factory=Codes)
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
    analysis: Analysis = Field(default_factory=Analysis, title="Analysis model")
    foundation: Foundation = Field(
        default_factory=Foundation,
        description="Soil values for the footing design (from the soil report).",
    )


def strength_combinations() -> list[LoadCombination]:
    """BNBC 2020 strength combinations (2.7.3), with wind and earthquake in ±X and ±Y."""
    result = []
    for name, factors in bnbc.STRENGTH_COMBINATIONS:
        lateral = next((case for case in ("W", "E") if case in factors), None)
        if lateral is None:
            result.append(LoadCombination(name=name, **factors))
            continue
        base = {k: v for k, v in factors.items() if k != lateral}
        for axis in ("X", "Y"):
            for sign in (1, -1):
                label = (
                    f"{name.replace(lateral, f'{lateral}{axis}', 1)}"
                    if sign > 0
                    else f"{name.replace(lateral, f'(-{lateral}{axis})', 1)}"
                )
                result.append(
                    LoadCombination(
                        name=label, **base, **{f"{lateral}{axis}": sign * factors[lateral]}
                    )
                )
    return result


def default_area_loads() -> list[AreaLoad]:
    return [
        AreaLoad(
            id="FL",
            name="Floors",
            use="residential",
            live=bnbc.AREA_USES["residential"].live,
            finish=1.2,
            partitions=1.0,
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


def derived(settings: ProjectSettings) -> dict[str, Any]:
    """The code values the settings imply, each with where it comes from."""
    location = bnbc.LOCATIONS.get(settings.site.location)
    category = bnbc.OCCUPANCY_CATEGORIES[settings.occupancy.category]
    system = bnbc.STRUCTURAL_SYSTEMS[settings.seismic.system]
    zone_z = bnbc.ZONE_COEFFICIENT[location.zone] if location else None
    return {
        "zone": location.zone if location else None,
        "Z": settings.site.zoneCoefficient or zone_z,
        "windSpeed": settings.site.windSpeed or (location.wind_speed if location else None),
        "seismicImportance": category.seismic_importance,
        "windImportance": category.wind_importance,
        "R": settings.seismic.r or system.r,
        "omega": settings.seismic.omega or system.omega,
        "Cd": settings.seismic.cd or system.cd,
    }


def check(settings: ProjectSettings) -> list[str]:
    """Problems the schema cannot express: references, code minimums, missing site values."""
    problems = []
    ids = [a.id for a in settings.areaLoads]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"{duplicate}: two area loads use this id")
    for field, value in (("floorLoad", settings.floorLoad), ("roofLoad", settings.roofLoad)):
        if value not in ids:
            problems.append(f"{field}: there is no area load '{value}'")
    for load in settings.areaLoads:
        use = bnbc.AREA_USES.get(load.use)
        if use and load.live < use.live:
            problems.append(
                f"{load.id}: live load {load.live} kN/m² is below the BNBC 2020 minimum of {use.live} kN/m² for {use.name.lower()}"
            )
    if settings.site.location == "custom":
        if settings.site.zoneCoefficient is None:
            problems.append("site: a custom location needs the seismic zone coefficient Z")
        if settings.site.windSpeed is None:
            problems.append("site: a custom location needs the basic wind speed")
    if not settings.combinations:
        problems.append("combinations: there are no load combinations")
    return problems


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
    result: dict[str, Any] = {**none, "boreholes": len(report.boreholes), "note": project["note"]}
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

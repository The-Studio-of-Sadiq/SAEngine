"""Project settings actions (02 Project Settings): the code pack, the site, the use and the
analysis options. Values are checked by the settings model and its problems (the pack's lists,
code minimums, site values), as the settings editor checks them; the pack gives every value
(:func:`saengine.library.settings.settings_for_pack` switches a project to a pack)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue._util import Params, fmt, given, merge
from saengine.actions.errors import refuse
from saengine.actions.paths import SETTINGS
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView


class CodePackParams(Params):
    codePack: str = Field(min_length=1, description="Id of an installed code pack (codes/list).")


@action(
    "settings.code_pack",
    summary="Switch the project to another design code pack: its towns, site classes, systems, "
    "area loads and combinations take the pack's values.",
    params=CodePackParams,
    parts=("settings",),
    kind="edit",
    example={"codePack": "bnbc2020"},
)
def settings_code_pack(view: ProjectView, p: CodePackParams) -> ActionResult:
    from saengine.codes.registry import CodePackError
    from saengine.library.settings import settings_for_pack

    data = view.part(SETTINGS)
    if data.get("codePack") == p.codePack:
        return ActionResult(message=f"The project follows {p.codePack} already.")
    try:
        switched = settings_for_pack(data, p.codePack)
    except CodePackError as error:
        refuse(f"The code pack '{p.codePack}' cannot be used: {error}", "codePack", p.codePack)
        raise
    except ValueError as error:
        refuse(f"02 Project Settings are not valid ({error}): fix them first.")
        raise
    view.put(SETTINGS, switched.model_dump(mode="json", by_alias=True, exclude_none=True))
    return ActionResult(
        message=f"The project now follows {p.codePack}; check the site, system and loads in "
        "02 Project Settings."
    )


class SiteParams(Params):
    location: str | None = Field(
        default=None, description="Town of the pack's hazard tables (sets Z and V), or custom."
    )
    siteClass: str | None = Field(default=None, description="One of the pack's site classes.")
    siteClassSource: Literal["soilReport", "entered"] | None = Field(
        default=None,
        description="soilReport: the soil report's class once its boreholes give one; entered: "
        "this class. Default with siteClass: entered.",
    )
    zoneCoefficient: float | None = Field(
        default=None, description="Z: overrides the town's [g]; null: the town's again."
    )
    windSpeed: float | None = Field(
        default=None, description="Basic wind speed [m/s]: overrides the town's; null: the town's."
    )
    windExposure: str | None = Field(
        default=None, description="Exposure or terrain category of the pack's wind table."
    )
    spectral: dict[str, Any] | None = Field(
        default=None,
        description="Mapped spectral values (sds, sd1, s1, tl) for a pack with mapped spectra.",
    )
    altitude: float | None = Field(default=None, description="Site altitude [m].")
    seismicSystem: str | None = Field(
        default=None, description="The seismic force-resisting system (one of the pack's)."
    )
    groundLevel: float | None = Field(default=None, description="Finished ground level [mm].")
    allowableBearing: float | None = Field(
        default=None,
        description="Net allowable bearing pressure qa [kPa] for every footing when there is no "
        "soil report (overrides it); null: from the soil report again.",
    )


@action(
    "settings.site",
    summary="Set the site: location, site class, seismic zone coefficient, wind speed and "
    "exposure, mapped spectral values, seismic system, ground level and the allowable bearing "
    "pressure when there is no soil report.",
    params=SiteParams,
    parts=("settings",),
    kind="edit",
    example={"location": "dhaka", "siteClass": "SD", "windExposure": "B"},
)
def settings_site(view: ProjectView, p: SiteParams) -> ActionResult:
    values = given(p)
    if not values:
        refuse("Give at least one site value.", "", None)
    data = view.part(SETTINGS)
    site_keys = (
        "location",
        "siteClass",
        "siteClassSource",
        "zoneCoefficient",
        "windSpeed",
        "spectral",
        "altitude",
    )
    patch: dict[str, Any] = {"site": {k: v for k, v in values.items() if k in site_keys}}
    if "siteClass" in values and "siteClassSource" not in values and p.siteClass:
        patch["site"]["siteClassSource"] = "entered"
    if "windExposure" in values:
        patch["wind"] = {"exposure": p.windExposure}
    if "seismicSystem" in values:
        patch["seismic"] = {"system": p.seismicSystem}
    foundation = {k: values[k] for k in ("groundLevel", "allowableBearing") if k in values}
    if foundation:
        patch["foundation"] = foundation
    view.put(SETTINGS, merge(data, patch))
    said = ", ".join(f"{k} {'cleared' if v is None else v}" for k, v in values.items())
    return ActionResult(message=f"Site set: {said}.")


Use = Literal[
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
]


class UseParams(Params):
    occupancy: Use | None = Field(default=None, description="The building's use.")
    category: Literal["I", "II", "III", "IV"] | None = Field(
        default=None, description="Occupancy (risk) category."
    )
    floorUse: str | None = Field(
        default=None,
        description="Area use of the floors' area load (one of the pack's area uses); default: "
        "the occupancy's.",
    )
    floorLive: float | None = Field(
        default=None, description="Floor live load [kN/m²]; default: the pack's for the use."
    )
    floorFinish: float | None = Field(default=None, description="Floor finish SD [kN/m²].")
    partitions: float | None = Field(default=None, description="Partition allowance [kN/m²].")
    roofLive: float | None = Field(default=None, description="Roof live load Lr [kN/m²].")
    roofFinish: float | None = Field(default=None, description="Roof finish SD [kN/m²].")


#: The occupancy's area use when the floors' use is not given (the generator's mapping).
def _area_use(occupancy: str) -> str:
    from saengine.library.generator import AREA_USE_OF

    return AREA_USE_OF.get(occupancy, occupancy)


@action(
    "settings.use",
    summary="Set the building's use and occupancy category, and the floor and roof area loads "
    "(live loads default to the pack's for the use).",
    params=UseParams,
    parts=("settings",),
    kind="edit",
    example={"occupancy": "office", "floorFinish": 1.5},
)
def settings_use(view: ProjectView, p: UseParams) -> ActionResult:
    from saengine.codes import context as code_context

    values = given(p)
    if not values:
        refuse("Give the use, the category or a load.", "", None)
    data = view.part(SETTINGS)
    occupancy = dict(data.get("occupancy") or {})
    if p.occupancy:
        occupancy["use"] = p.occupancy
    if p.category:
        occupancy["category"] = p.category
    data["occupancy"] = occupancy
    pack = code_context.current()
    uses = pack.table("areaLoads").uses if pack.has("areaLoads") else {}
    notes = []
    areas = list(data.get("areaLoads") or [])
    for area in areas:
        if area.get("id") == data.get("floorLoad"):
            if p.floorUse or p.occupancy:
                area["use"] = p.floorUse or _area_use(p.occupancy or "")
                if p.floorLive is None and area["use"] in uses:
                    area["live"] = float(uses[area["use"]].live)
                    notes.append(f"floor live load {fmt(area['live'])} kN/m² ({area['use']})")
            if p.floorLive is not None:
                area["live"] = p.floorLive
            if p.floorFinish is not None:
                area["finish"] = p.floorFinish
            if p.partitions is not None:
                area["partitions"] = p.partitions
        if area.get("id") == data.get("roofLoad"):
            if p.roofLive is not None:
                area["live"] = p.roofLive
            if p.roofFinish is not None:
                area["finish"] = p.roofFinish
    data["areaLoads"] = areas
    view.put(SETTINGS, data)
    said = ", ".join(f"{k} {v}" for k, v in values.items())
    return ActionResult(
        message=f"Use set: {said}" + (f"; {', '.join(notes)}" if notes else "") + "."
    )


class AnalysisParams(Params):
    set: dict[str, Any] = Field(
        description="Analysis options of 02 Project Settings > Analysis model by their names "
        "(e.g. slabs, diaphragm, meshSize, supports, responseSpectrum, secondOrder, "
        "liveLoadReduction, seismicDesign); objects are merged, null resets an option."
    )


@action(
    "settings.analysis",
    summary="Set analysis model options (the names of Project Settings > Analysis model).",
    params=AnalysisParams,
    parts=("settings",),
    kind="edit",
    example={"set": {"diaphragm": "rigid", "meshSize": 500}},
)
def settings_analysis(view: ProjectView, p: AnalysisParams) -> ActionResult:
    from saengine.library.settings import Analysis

    if not p.set:
        refuse("Give the options to set.", "set", p.set)
    known = set(Analysis.model_fields)
    unknown = sorted(k for k in p.set if k not in known)
    if unknown:
        refuse(
            f"Analysis has no option {', '.join(unknown)} (the options: {', '.join(sorted(known))}).",
            "set",
            unknown,
        )
    data = view.part(SETTINGS)
    data["analysis"] = merge(data.get("analysis") or {}, p.set)
    view.put(SETTINGS, data)
    return ActionResult(
        message="Analysis options set: " + ", ".join(f"{k} {v}" for k, v in p.set.items()) + "."
    )

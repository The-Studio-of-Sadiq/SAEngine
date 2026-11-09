"""The environmental studies of a project (alpha 9 L11), for the RPC and the workbench.

Inputs: the site point of ``01 Soil Report/soil-report.json`` (latitude, longitude, the grid's
rotation from north), the building model, the architecture's rooms and windows, and
``06 BIM/environment.json`` (:class:`EnvironmentSettings`): the neighbouring buildings, the
study date and time step, the clock's UTC offset, the roads for the noise estimate and the
daylight values (over the defaults of ``data/environment-defaults.json``).
"""

from __future__ import annotations

import json
from datetime import date
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

ENVIRONMENT_FILE = "06 BIM/environment.json"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ContextBuilding(_Model):
    id: str
    name: str = ""
    outline: list[list[float]] = Field(min_length=3, description="Plan corners [mm].")
    base: float = Field(default=0, description="Bottom [mm].")
    height: float = Field(gt=0, description="Height above its base [mm].")


class Road(_Model):
    id: str
    name: str = ""
    path: list[list[float]] = Field(min_length=2, description="Centre line [mm].")
    width: float = Field(default=7000, gt=0, description="Carriageway width [mm].")
    flow: float = Field(gt=0, description="Vehicles in 18 hours (06:00-24:00).")
    speed: float = Field(default=50, gt=0, description="Mean speed [km/h].")
    heavy: float = Field(default=10, ge=0, le=100, description="Heavy vehicles [%].")
    gradient: float = Field(default=0, ge=0, description="[%]")


class EnvironmentSettings(_Model):
    schema_: str = Field(default="saengine.environment/1", alias="schema")
    day: date | None = Field(default=None, description="Study day; empty: the June solstice.")
    utcOffset: float | None = Field(
        default=None, description="Clock time zone [h]; empty: the site's longitude / 15."
    )
    stepMinutes: float = Field(default=30, gt=0, le=120)
    gridSpacing: float = Field(default=2000, gt=0, description="Ground points spacing [mm].")
    facadeSpacing: float = Field(default=3000, gt=0, description="Facade points spacing [mm].")
    margin: float = Field(default=20000, ge=0, description="Ground studied around [mm].")
    context: list[ContextBuilding] = Field(default_factory=list)
    roads: list[Road] = Field(default_factory=list)
    daylight: dict[str, float] = Field(
        default_factory=dict, description="Over the defaults: transmittance, maintenance, ..."
    )


@cache
def defaults() -> dict[str, Any]:
    return json.loads(
        resources.files("saengine.environment")
        .joinpath("data", "environment-defaults.json")
        .read_text(encoding="utf-8")
    )


def _read(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError:
        return None


def _inputs(project_root: str) -> dict[str, Any]:
    from shapely.geometry import Polygon

    from saengine.environment.solar import Massing, Prism, building_massing
    from saengine.library.bim import BuildingModel
    from saengine.library.soil import SoilReport

    root = Path(project_root)
    settings = EnvironmentSettings.model_validate_json(_read(root, ENVIRONMENT_FILE) or "{}")
    soil = _read(root, "01 Soil Report/soil-report.json")
    site = SoilReport.model_validate_json(soil).site if soil else None
    if site is None or not site.georeferenced:
        raise ValueError(
            "the site has no latitude/longitude: set the site point in 01 Soil Report's map"
        )
    bim = _read(root, "06 BIM/bim.json")
    if not bim:
        raise ValueError("06 BIM has no building model")
    building = BuildingModel.model_validate_json(bim)
    prisms = building_massing(building)
    for c in settings.context:
        outline = Polygon([(float(p[0]), float(p[1])) for p in c.outline]).buffer(0)
        if not outline.is_empty:
            prisms.append(Prism(outline, c.base, c.base + c.height, c.name or c.id))
    ground = 0.0
    try:
        ground = float(
            (json.loads(_read(root, "02 Project Settings/project-settings.json") or "{}")
             .get("foundation") or {}).get("groundLevel") or 0.0
        )  # fmt: skip
    except (ValueError, AttributeError):
        ground = 0.0
    day = settings.day or date(date.today().year, 6, 21)
    offset = settings.utcOffset if settings.utcOffset is not None else round(site.lon / 15 * 2) / 2
    return {
        "root": root,
        "settings": settings,
        "site": site,
        "building": building,
        "prisms": prisms,
        "own": len(building_massing(building)),
        "massing": Massing(prisms),
        "ground": ground,
        "day": day,
        "offset": offset,
    }


def sun_study(project_root: str, day: str | None = None) -> dict[str, Any]:
    """The sun path of the day, the shadows every hour, and the direct sun hours of the ground
    around the building and of its facades: ``{"site", "day", "utcOffset", "path", "shadows":
    [{time, rings}], "ground": {points, hours}, "facades": {points, normals, hours}, "notes"}``
    (points [mm], flat x, y, z lists) or ``{"problems"}``."""
    from shapely.ops import unary_union

    from saengine.environment import solar

    try:
        ctx = _inputs(project_root)
    except ValueError as error:
        return {"problems": [str(error)]}
    settings, site = ctx["settings"], ctx["site"]
    when = date.fromisoformat(day) if day else ctx["day"]
    path = solar.sun_path(
        site.lat, site.lon, when, ctx["offset"], settings.stepMinutes, site.rotation
    )
    prisms = ctx["prisms"]
    massing = ctx["massing"]
    notes = [
        (
            f"sun by the NOAA equations (no refraction) at {site.lat:.5f}, {site.lon:.5f}, clock "
            f"UTC{ctx['offset']:+g}, every {settings.stepMinutes:g} min"
        ),
        (
            "massing: the storeys from the slabs' outlines and the neighbouring buildings given; "
            "balconies, parapets and roof structures are not in it"
        ),
    ]
    if not prisms:
        return {"problems": ["the building model has no slabs to make the massing from"]}
    own = prisms[: ctx["own"]]
    footprint = unary_union([p.outline for p in own]) if own else None
    shadows = []
    for sample in path:
        if abs(sample["hour"] - round(sample["hour"])) > 1e-6:
            continue
        shape = solar.shadow_polygons(prisms, np.asarray(sample["direction"]), ctx["ground"])
        shadows.append({"time": sample["time"], "rings": solar.rings(shape)})
    extent = (footprint or unary_union([p.outline for p in prisms])).buffer(settings.margin)
    gp, gn = solar.ground_points(extent, settings.gridSpacing, ctx["ground"], footprint)
    fp, fn, labels = solar.facade_points(own, settings.facadeSpacing)
    ground_hours = solar.sun_hours(massing, gp, gn, path, settings.stepMinutes)
    facade_hours = solar.sun_hours(massing, fp, fn, path, settings.stepMinutes)
    return {
        "site": {"latitude": site.lat, "longitude": site.lon, "rotation": site.rotation},
        "day": when.isoformat(),
        "utcOffset": ctx["offset"],
        "path": path,
        "shadows": shadows,
        "ground": {
            "points": [round(float(v), 1) for v in gp.ravel()],
            "hours": [round(float(h), 2) for h in ground_hours],
            "spacing": settings.gridSpacing,
        },
        "facades": {
            "points": [round(float(v), 1) for v in fp.ravel()],
            "normals": [round(float(v), 4) for v in fn.ravel()],
            "hours": [round(float(h), 2) for h in facade_hours],
            "labels": labels,
        },
        "daylightHours": round(len(path) * settings.stepMinutes / 60, 2),
        "notes": notes,
    }


def daylight_study(project_root: str) -> dict[str, Any]:
    """The average daylight factor of every room of the architecture: ``{"rooms", "values",
    "sources", "notes"}`` or ``{"problems"}``."""
    from saengine.environment.daylight import room_daylight
    from saengine.library import architecture as arch_lib

    try:
        ctx = _inputs(project_root)
    except ValueError as error:
        return {"problems": [str(error)]}
    arch = arch_lib.parse(_read(ctx["root"], arch_lib.ARCHITECTURE_FILE))
    if not arch.rooms:
        return {"problems": ["05 Floor Plan's architecture has no rooms"]}
    base = defaults()["daylight"]
    values = {k: float(v) for k, v in base.items() if isinstance(v, (int, float))}
    values.update({k: float(v) for k, v in ctx["settings"].daylight.items()})
    elevations = {s.id: float(s.elevation) for s in ctx["building"].stories}
    rooms = room_daylight(arch, elevations, ctx["massing"], values)
    return {
        "rooms": rooms,
        "values": values,
        "sources": base.get("sources", {}),
        "notes": [
            (
                "Average daylight factor DF = T Aw θ M / (A (1 - R²)) (BR 209 Appendix C / CIBSE "
                "LG10 form), side windows only; compare with the target of the code or standard "
                "the project follows."
            )
        ],
    }


def noise_study(project_root: str) -> dict[str, Any]:
    """The indicative L10,18h and LAeq,18h at the facade points from the roads given:
    ``{"facades": {points, levels}, "constants", "notes"}`` or ``{"problems"}``."""
    from saengine.environment import solar
    from saengine.environment.road_noise import facade_levels

    try:
        ctx = _inputs(project_root)
    except ValueError as error:
        return {"problems": [str(error)]}
    settings = ctx["settings"]
    if not settings.roads:
        return {"problems": ["no roads: add them (path, 18-hour flow, speed) to the study"]}
    own = ctx["prisms"][: ctx["own"]]
    fp, _, labels = solar.facade_points(own, settings.facadeSpacing)
    k = defaults()["roadNoise"]
    levels = facade_levels(
        fp, [r.model_dump() for r in settings.roads], ctx["massing"], ctx["ground"], k
    )
    return {
        "facades": {
            "points": [round(float(v), 1) for v in fp.ravel()],
            "labels": labels,
            "levels": levels,
        },
        "constants": {key: v for key, v in k.items() if key != "sources"},
        "sources": k.get("sources", {}),
        "notes": [
            (
                "Indicative facade levels in the form of CRTN (1988): no barriers, ground or "
                "angle-of-view corrections; a facade the building itself screens from a road gets "
                "no level from it. Not a noise assessment."
            )
        ],
    }

"""The building's design-day cooling loads by EnergyPlus version 26.2.0.

EnergyPlus runs as a separate program (``energyplus.exe``, a subprocess), never linked into
SAEngine. SAEngine writes its input as epJSON (the JSON form of the input, checked by
EnergyPlus against its own ``Energy+.schema.epJSON``: plain ``json`` needs no extra package and
no IDD parser, unlike IDF editing with eppy), runs the sizing periods only (no weather file),
and reads ``eplusout.sql`` with ``sqlite3``.

The model: one zone per story (:mod:`saengine.hvac.geometry`); the constructions of
:mod:`saengine.hvac.constructions`; people, lights and equipment at their design levels all
day; outdoor air through an ideal loads air system per conditioned zone
(``ZoneHVAC:IdealLoadsAirSystem`` with ``DesignSpecification:OutdoorAir`` and a humidistat at
the inside humidity, so that its cooling includes the ventilation and the latent load); one
``SizingPeriod:DesignDay`` a month from May to September with Table 8.2.2's 2 % dry bulb, mean
coincident wet bulb (constant humidity ratio over the day) and daily range, and the ASHRAE clear
sky. ``Sizing:Zone`` gives each zone's design airflow and the Zone Component Load Summary its
load components.

Where EnergyPlus is (:func:`find_energyplus`): the ``SAENGINE_ENERGYPLUS`` environment variable
(the folder or the exe), then the copy bundled with SAEngine (``<app>/resources/energyplus``,
next to the bundled ``resources/python``), then the standard install folders
(``C:/EnergyPlusV26-2-0`` and the like, ``/usr/local/EnergyPlus-26-2-0``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.hvac import tables as T
from saengine.hvac.constructions import EnvelopeChoice, epjson_objects
from saengine.hvac.gains import Design, ZoneGains
from saengine.hvac.geometry import ThermalZone

VERSION = "26.2"
ENGINE = "EnergyPlus version 26.2.0"
ENV_VAR = "SAENGINE_ENERGYPLUS"
EXE = "energyplus.exe" if os.name == "nt" else "energyplus"
TIMEOUT = 300.0
TIMESTEPS = 4  # per hour

OUTPUT_VARIABLES = (
    "Zone Ideal Loads Supply Air Total Cooling Rate",
    "Zone Ideal Loads Supply Air Sensible Cooling Rate",
    "Zone Ideal Loads Supply Air Latent Cooling Rate",
    "Zone Ideal Loads Zone Total Cooling Rate",
    "Zone Ideal Loads Outdoor Air Total Cooling Rate",
    "Zone Ideal Loads Outdoor Air Sensible Cooling Rate",
    "Zone Ideal Loads Outdoor Air Latent Cooling Rate",
    "Zone Ideal Loads Outdoor Air Standard Density Volume Flow Rate",
    "Site Outdoor Air Drybulb Temperature",
    "Site Outdoor Air Humidity Ratio",
    "Zone Air Humidity Ratio",
    "Zone Air Relative Humidity",
)


class EnergyPlusError(RuntimeError):
    """EnergyPlus did not finish: the message holds its severe and fatal errors."""


def _candidates() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get(ENV_VAR)
    if env:
        out.append(Path(env))
    # The bundled copy: <app>/resources/python/python.exe -> <app>/resources/energyplus.
    out.append(Path(sys.executable).resolve().parent.parent / "energyplus")
    if os.name == "nt":
        for root in (os.environ.get("SystemDrive", "C:") + "\\", r"C:\Program Files"):
            out.extend(sorted(Path(root).glob("EnergyPlusV26-*"), reverse=True))
            out.extend(sorted(Path(root).glob("EnergyPlusV2[5-9]-*"), reverse=True))
    else:
        for root in ("/usr/local", "/Applications", "/opt"):
            out.extend(sorted(Path(root).glob("EnergyPlus-2[5-9]-*"), reverse=True))
    return out


def find_energyplus(explicit: str | Path | None = None) -> Path | None:
    """The EnergyPlus executable (``explicit``: a folder or the exe, before the others), or
    None when there is none."""
    for candidate in ([Path(explicit)] if explicit else []) + _candidates():
        exe = candidate if candidate.suffix.lower() == ".exe" or candidate.name == EXE else None
        exe = exe or candidate / EXE
        try:
            if exe.is_file():
                return exe
        except OSError:
            continue
    return None


def version(exe: Path, timeout: float = 30.0) -> str:
    """``energyplus --version``, e.g. "EnergyPlus, Version 26.2.0-4bd7a1f26f"."""
    done = subprocess.run(
        [str(exe), "--version"], capture_output=True, text=True, timeout=timeout, check=False
    )
    return done.stdout.strip()


# ─────────────────────────────────────────── input ───────────────────────────────────────────


def _vertices(points: list[tuple[float, float, float]]) -> list[dict[str, float]]:
    return [
        {"vertex_x_coordinate": round(x, 4), "vertex_y_coordinate": round(y, 4),
         "vertex_z_coordinate": round(z, 4)}
        for x, y, z in points
    ]  # fmt: skip


def _window_vertices(points: list[tuple[float, float, float]]) -> dict[str, float]:
    out: dict[str, float] = {"number_of_vertices": len(points)}
    for i, (x, y, z) in enumerate(points, 1):
        out[f"vertex_{i}_x_coordinate"] = round(x, 4)
        out[f"vertex_{i}_y_coordinate"] = round(y, 4)
        out[f"vertex_{i}_z_coordinate"] = round(z, 4)
    return out


def _schedule(model: dict[str, Any], value: float) -> str:
    name = f"Constant {value:g}"
    model.setdefault("Schedule:Constant", {})[name] = {
        "schedule_type_limits_name": "Any Number",
        "hourly_value": value,
    }
    return name


@dataclass
class Model:
    """The epJSON of a building and the names it gave the zones' parts."""

    epjson: dict[str, Any]
    #: zone name -> ideal loads system name (conditioned zones only)
    systems: dict[str, str] = field(default_factory=dict)


def build(
    zones: list[ThermalZone],
    gains: dict[str, ZoneGains],
    envelope: EnvelopeChoice,
    design: Design,
) -> Model:
    """The epJSON input of the building (``gains``: zone name -> its gains)."""
    m: dict[str, Any] = {
        "Version": {"Version 1": {"version_identifier": VERSION}},
        "SimulationControl": {
            "SimulationControl 1": {
                "do_zone_sizing_calculation": "Yes",
                "do_system_sizing_calculation": "No",
                "do_plant_sizing_calculation": "No",
                "run_simulation_for_sizing_periods": "Yes",
                "run_simulation_for_weather_file_run_periods": "No",
            }
        },
        "Building": {
            "SAEngine building": {
                "north_axis": 0.0,
                "terrain": "City",
                "solar_distribution": "FullExterior",
                "maximum_number_of_warmup_days": 25,
            }
        },
        "Timestep": {"Timestep 1": {"number_of_timesteps_per_hour": TIMESTEPS}},
        "ShadowCalculation": {
            "ShadowCalculation 1": {"maximum_figures_in_shadow_overlap_calculations": 300000}
        },
        "GlobalGeometryRules": {
            "GlobalGeometryRules 1": {
                "starting_vertex_position": "UpperLeftCorner",
                "vertex_entry_direction": "Counterclockwise",
                "coordinate_system": "World",
            }
        },
        "Site:Location": {
            design.station.name: {
                "latitude": design.latitude,
                "longitude": design.longitude,
                "time_zone": T.TIME_ZONE,
                "elevation": design.elevation,
            }
        },
        "Sizing:Parameters": {
            "Sizing:Parameters 1": {"heating_sizing_factor": 1.0, "cooling_sizing_factor": 1.0}
        },
        "ScheduleTypeLimits": {"Any Number": {}},
        "Output:SQLite": {"Output:SQLite 1": {"option_type": "SimpleAndTabular"}},
        "Output:Table:SummaryReports": {
            "Output:Table:SummaryReports 1": {
                "reports": [
                    {"report_name": "ZoneComponentLoadSummary"},
                    {"report_name": "EnvelopeSummary"},
                ]
            }
        },
        "Output:Variable": {
            f"Output {i}": {
                "key_value": "*",
                "variable_name": name,
                "reporting_frequency": "Timestep",
            }
            for i, name in enumerate(OUTPUT_VARIABLES, 1)
        },
    }
    days: dict[str, Any] = {}
    for month in design.months:
        days[f"Cooling {month:02d}-21"] = {
            "month": month,
            "day_of_month": 21,
            "day_type": "SummerDesignDay",
            "maximum_dry_bulb_temperature": design.db,
            "daily_dry_bulb_temperature_range": design.range,
            "humidity_condition_type": "WetBulb",
            "wetbulb_or_dewpoint_at_maximum_dry_bulb": design.wb,
            "wind_speed": T.DESIGN_WIND_SPEED,
            "wind_direction": 180.0,
            "rain_indicator": "No",
            "snow_indicator": "No",
            "daylight_saving_time_indicator": "No",
            "solar_model_indicator": "ASHRAEClearSky",
            "sky_clearness": 1.0,
        }
    m["SizingPeriod:DesignDay"] = days
    m.update(epjson_objects(envelope))
    on = _schedule(m, 1.0)
    m["Zone"] = {}
    surfaces: dict[str, Any] = {}
    windows: dict[str, Any] = {}
    shading_windows: dict[str, list[str]] = {}
    systems: dict[str, str] = {}
    for zone in zones:
        m["Zone"][zone.name] = {"ceiling_height": round(zone.height, 4)}
        for s in zone.surfaces:
            obj: dict[str, Any] = {
                "surface_type": s.kind,
                "construction_name": s.construction,
                "zone_name": zone.name,
                "outside_boundary_condition": s.boundary,
                "sun_exposure": "SunExposed" if s.boundary == "Outdoors" else "NoSun",
                "wind_exposure": "WindExposed" if s.boundary == "Outdoors" else "NoWind",
                "vertices": _vertices(s.vertices),
            }
            if s.boundary == "Surface":
                obj["outside_boundary_condition_object"] = s.other
            surfaces[s.name] = obj
            for w in s.windows:
                windows[w.name] = {
                    "surface_type": "Window",
                    "construction_name": "Window",
                    "building_surface_name": s.name,
                    **_window_vertices(w.vertices),
                }
                shading_windows.setdefault(zone.name, []).append(w.name)
        g = gains.get(zone.name)
        if g is not None:
            _internal(m, zone, g, on)
        if zone.conditioned and g is not None:
            systems[zone.name] = _ideal_loads(m, zone, g)
        elif not zone.conditioned:
            _outside_air(m, zone, g, on)
    m["BuildingSurface:Detailed"] = surfaces
    if windows:
        m["FenestrationSurface:Detailed"] = windows
    if envelope.shading == "overhang" and windows:
        m["Shading:Overhang:Projection"] = {
            f"{name} overhang": {
                "window_or_door_name": name,
                "height_above_window_or_door": 0.0,
                "tilt_angle_from_window_door": 90.0,
                "left_extension_from_window_door_width": 0.0,
                "right_extension_from_window_door_width": 0.0,
                "depth_as_fraction_of_window_door_height": T.OVERHANG_FACTOR,
            }
            for name in windows
        }
    if envelope.shading == "blinds" and windows:
        m["WindowShadingControl"] = {
            f"{zone} blinds": {
                "zone_name": zone,
                "shading_control_sequence_number": 1,
                "shading_type": "InteriorBlind",
                "construction_with_shading_name": "Window with blind",
                "shading_control_type": "AlwaysOn",
                "type_of_slat_angle_control_for_blinds": "FixedSlatAngle",
                "multiple_surface_control_type": "Group",
                "fenestration_surfaces": [{"fenestration_surface_name": n} for n in names],
            }
            for zone, names in shading_windows.items()
        }
    return Model(m, systems)


def _internal(m: dict[str, Any], zone: ThermalZone, g: ZoneGains, on: str) -> None:
    if g.occupants > 0:
        m.setdefault("People", {})[f"{zone.name} people"] = {
            "zone_or_zonelist_or_space_or_spacelist_name": zone.name,
            "number_of_people_schedule_name": on,
            "number_of_people_calculation_method": "People",
            "number_of_people": round(g.occupants, 3),
            "fraction_radiant": 0.3,
            "activity_level_schedule_name": _schedule(m, g.activity),
        }
    if g.lighting > 0:
        m.setdefault("Lights", {})[f"{zone.name} lights"] = {
            "zone_or_zonelist_or_space_or_spacelist_name": zone.name,
            "schedule_name": on,
            "design_level_calculation_method": "Watts/Area",
            "watts_per_floor_area": g.lighting,
            "fraction_radiant": 0.37,
            "fraction_visible": 0.18,
        }
    if g.equipment > 0:
        m.setdefault("ElectricEquipment", {})[f"{zone.name} equipment"] = {
            "zone_or_zonelist_or_space_or_spacelist_name": zone.name,
            "schedule_name": on,
            "design_level_calculation_method": "Watts/Area",
            "watts_per_floor_area": g.equipment,
            "fraction_radiant": 0.3,
        }


def unconditioned_air(zone: ThermalZone, g: ZoneGains | None) -> tuple[float, str]:
    """Outside air through an unconditioned story [m³/s] and where it comes from: the Table
    8.2.3 exhaust rate per m² of its use (a car park's 3.75 l/s per m²), else its outdoor air
    rate, else 1 air change an hour (SAEngine, from memory: to be checked)."""
    if g is not None:
        row = T.VENTILATION[g.use]
        if row.exhaust is not None and not row.exhaustNote:
            return row.exhaust / 1000.0 * zone.area, f"Table 8.2.3 exhaust {row.exhaust:g} l/s m²"
        flow = g.outdoor_air(zone.area, zone.volume)
        if flow > 0:
            return flow, "Table 8.2.3 outdoor air"
    return zone.volume / 3600.0, "1 air change an hour (SAEngine)"


def _outside_air(m: dict[str, Any], zone: ThermalZone, g: ZoneGains | None, on: str) -> None:
    """An unconditioned story is ventilated with outside air (so that it does not heat up as a
    closed box would)."""
    flow, _ = unconditioned_air(zone, g)
    m.setdefault("ZoneInfiltration:DesignFlowRate", {})[f"{zone.name} outside air"] = {
        "zone_or_zonelist_or_space_or_spacelist_name": zone.name,
        "schedule_name": on,
        "design_flow_rate_calculation_method": "Flow/Zone",
        "design_flow_rate": round(flow, 5),
        "constant_term_coefficient": 1.0,
        "temperature_term_coefficient": 0.0,
        "velocity_term_coefficient": 0.0,
        "velocity_squared_term_coefficient": 0.0,
    }


def _ideal_loads(m: dict[str, Any], zone: ThermalZone, g: ZoneGains) -> str:
    name = f"{zone.name} ideal loads"
    oa = f"{zone.name} outdoor air"
    if g.ach is not None:
        m.setdefault("DesignSpecification:OutdoorAir", {})[oa] = {
            "outdoor_air_method": "Maximum",
            "outdoor_air_flow_per_person": g.perPerson,
            "outdoor_air_flow_air_changes_per_hour": g.ach,
        }
    else:
        m.setdefault("DesignSpecification:OutdoorAir", {})[oa] = {
            "outdoor_air_method": "Sum",
            "outdoor_air_flow_per_person": g.perPerson,
            "outdoor_air_flow_per_zone_floor_area": g.perArea,
        }
    stat = f"{zone.name} setpoints"
    m.setdefault("ThermostatSetpoint:DualSetpoint", {})[stat] = {
        "heating_setpoint_temperature_schedule_name": _schedule(m, -50.0),
        "cooling_setpoint_temperature_schedule_name": _schedule(m, g.indoorDB),
    }
    m.setdefault("ZoneControl:Thermostat", {})[f"{zone.name} thermostat"] = {
        "zone_or_zonelist_name": zone.name,
        "control_type_schedule_name": _schedule(m, 4.0),
        "control_1_object_type": "ThermostatSetpoint:DualSetpoint",
        "control_1_name": stat,
    }
    m.setdefault("ZoneControl:Humidistat", {})[f"{zone.name} humidistat"] = {
        "zone_name": zone.name,
        "humidifying_setpoint_schedule_name": _schedule(m, 0.0),
        "dehumidifying_setpoint_schedule_name": _schedule(m, g.indoorRH),
    }
    m.setdefault("Sizing:Zone", {})[f"{zone.name} sizing"] = {
        "zone_or_zonelist_name": zone.name,
        "zone_cooling_design_supply_air_temperature_input_method": "SupplyAirTemperature",
        "zone_cooling_design_supply_air_temperature": T.SUPPLY_AIR_TEMPERATURE,
        "zone_heating_design_supply_air_temperature_input_method": "SupplyAirTemperature",
        "zone_heating_design_supply_air_temperature": 35.0,
        "zone_cooling_design_supply_air_humidity_ratio": T.SUPPLY_AIR_HUMIDITY,
        "zone_heating_design_supply_air_humidity_ratio": T.SUPPLY_AIR_HUMIDITY,
        "design_specification_outdoor_air_object_name": oa,
        "zone_load_sizing_method": "Sensible And Latent Load",
    }
    inlet, node = f"{zone.name} supply inlet", f"{zone.name} air node"
    m.setdefault("OutdoorAir:Node", {})[f"{zone.name} outdoor air inlet"] = {}
    m.setdefault("ZoneHVAC:IdealLoadsAirSystem", {})[name] = {
        "zone_supply_air_node_name": inlet,
        "minimum_cooling_supply_air_temperature": T.SUPPLY_AIR_TEMPERATURE,
        "minimum_cooling_supply_air_humidity_ratio": T.SUPPLY_AIR_HUMIDITY,
        "heating_limit": "NoLimit",
        "cooling_limit": "NoLimit",
        "dehumidification_control_type": "Humidistat",
        "humidification_control_type": "None",
        "design_specification_outdoor_air_object_name": oa,
        "outdoor_air_inlet_node_name": f"{zone.name} outdoor air inlet",
    }
    m.setdefault("ZoneHVAC:EquipmentList", {})[f"{zone.name} equipment list"] = {
        "load_distribution_scheme": "SequentialLoad",
        "equipment": [
            {
                "zone_equipment_object_type": "ZoneHVAC:IdealLoadsAirSystem",
                "zone_equipment_name": name,
                "zone_equipment_cooling_sequence": 1,
                "zone_equipment_heating_or_no_load_sequence": 1,
            }
        ],
    }
    m.setdefault("ZoneHVAC:EquipmentConnections", {})[f"{zone.name} connections"] = {
        "zone_name": zone.name,
        "zone_conditioning_equipment_list_name": f"{zone.name} equipment list",
        "zone_air_inlet_node_or_nodelist_name": inlet,
        "zone_air_node_name": node,
        "zone_return_air_node_or_nodelist_name": f"{zone.name} return",
    }
    return name


# ──────────────────────────────────────────── run ────────────────────────────────────────────


def errors(folder: Path) -> list[str]:
    """The severe and fatal messages of ``eplusout.err`` (with their continuation lines)."""
    try:
        text = (folder / "eplusout.err").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("** Severe  **", "**  Fatal  **")):
            out.append(re.sub(r"^\*\*\s+\w+\s+\*\*\s*", "", s))
        elif s.startswith("**   ~~~   **") and out:
            out[-1] += " " + s.replace("**   ~~~   **", "").strip()
    return out


def run(
    model: Model,
    exe: Path,
    folder: Path | None = None,
    timeout: float = TIMEOUT,
) -> dict[str, Any]:
    """Run EnergyPlus on the model in ``folder`` (a new temporary folder, deleted afterwards,
    when None) and return :func:`read_results`. Raises :class:`EnergyPlusError`."""
    own = folder is None
    work = Path(tempfile.mkdtemp(prefix="saengine-eplus-")) if own else Path(folder)
    work.mkdir(parents=True, exist_ok=True)
    try:
        path = work / "in.epJSON"
        path.write_text(json.dumps(model.epjson, indent=1), encoding="utf-8")
        start = time.perf_counter()
        done = _run_cancellable(
            [str(exe), "-d", str(work), str(path)], work, timeout
        )  # fmt: skip
        seconds = time.perf_counter() - start
        problems = errors(work)
        if done.returncode != 0 or not (work / "eplusout.sql").is_file():
            detail = "; ".join(problems[:8]) or done.stdout[-600:] or done.stderr[-600:]
            raise EnergyPlusError(f"EnergyPlus failed (exit {done.returncode}): {detail}")
        results = read_results(work / "eplusout.sql", model)
        results["seconds"] = round(seconds, 2)
        results["warnings"] = _warning_count(work)
        results["geometryWarnings"] = geometry_warnings(work)
        return results
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)


class EnergyPlusCancelled(EnergyPlusError):
    """The run was cancelled (:func:`cancel_runs`)."""


_RUNNING: set[subprocess.Popen] = set()
_RUNNING_LOCK = threading.Lock()


def _run_cancellable(args: list[str], work: Path, timeout: float) -> subprocess.CompletedProcess:
    """``subprocess.run`` that :func:`cancel_runs` can stop from another thread."""
    child = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(work),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip
    with _RUNNING_LOCK:
        _RUNNING.add(child)
    try:
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            child.kill()
            child.communicate()
            raise EnergyPlusError(f"EnergyPlus did not finish in {timeout:g} s") from error
    finally:
        with _RUNNING_LOCK:
            cancelled = child not in _RUNNING
            _RUNNING.discard(child)
    if cancelled:
        raise EnergyPlusCancelled("the EnergyPlus run was cancelled")
    return subprocess.CompletedProcess(args, child.returncode, stdout, stderr)


def cancel_runs() -> int:
    """Stops every EnergyPlus run in progress (their :func:`run` raises
    :class:`EnergyPlusCancelled`); the number stopped."""
    with _RUNNING_LOCK:
        children = list(_RUNNING)
        _RUNNING.clear()
    for child in children:
        try:
            child.kill()
        except OSError:
            pass
    return len(children)


#: Warnings of ``eplusout.err`` that mean the zones' geometry is wrong (passed on as problems).
GEOMETRY_WARNINGS = ("not fully enclosed", "upside down", "non-planar", "Surface Area mismatch")


def geometry_warnings(folder: Path) -> list[str]:
    """The warnings of ``eplusout.err`` about the zones' geometry (:data:`GEOMETRY_WARNINGS`),
    with their continuation lines."""
    try:
        text = (folder / "eplusout.err").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("** Warning **"):
            current = s.replace("** Warning **", "").strip()
            if any(w.lower() in current.lower() for w in GEOMETRY_WARNINGS):
                out.append(current)
            else:
                current = None
        elif s.startswith("**   ~~~   **") and current is not None and out:
            out[-1] += " " + s.replace("**   ~~~   **", "").strip()
        else:
            current = None
    return out


def _warning_count(folder: Path) -> int:
    try:
        text = (folder / "eplusout.err").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    found = re.search(r"Completed Successfully--\s*(\d+)\s+Warning", text)
    return int(found.group(1)) if found else 0


# ─────────────────────────────────────────── results ───────────────────────────────────────────

#: Zone Component Load Summary rows -> the report's breakdown.
COMPONENTS = {
    "walls": ("Exterior Wall", "Interzone Wall", "Ground Contact Wall", "Other Wall"),
    "roof": ("Roof", "Other Roof"),
    "floors": (
        "Interzone Ceiling", "Exterior Floor", "Interzone Floor", "Ground Contact Floor",
        "Other Floor",
    ),
    "glazingConduction": ("Fenestration Conduction",),
    "glazingSolar": ("Fenestration Solar",),
    "people": ("People",),
    "lights": ("Lights",),
    "equipment": ("Equipment",),
    "infiltration": ("Infiltration",),
}  # fmt: skip


def _number(text: Any) -> float | None:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def read_results(sql: Path, model: Model) -> dict[str, Any]:
    """Per zone: the coincident peak of its ideal loads system (sensible, latent and total
    cooling with the outdoor air, kW), when and in which design day, the outdoor air's share,
    the design airflow of Sizing:Zone and the Zone Component Load Summary at the zone's sensible
    peak; and the envelope's U-values and SHGC as EnergyPlus works them out."""
    con = sqlite3.connect(str(sql))
    try:
        sizes = {}
        for row in con.execute(
            "select ZoneName, CalcDesLoad, UserDesFlow, DesDayName, PeakHrMin, PeakTemp "
            "from ZoneSizes where LoadType = 'Cooling'"
        ):
            sizes[row[0].upper()] = row
        series = _series(con)
        components = _components(con)
        envelope = _envelope(con)
    finally:
        con.close()
    zones = {}
    for zone, system in model.systems.items():
        z, s = zone.upper(), system.upper()
        total = series.get(("Zone Ideal Loads Supply Air Total Cooling Rate", s), {})
        if not total:
            zones[zone] = {"problem": "no cooling output from EnergyPlus"}
            continue
        when = max(total, key=lambda k: total[k])
        at = {
            name.replace("Zone Ideal Loads ", ""): values.get(when, 0.0)
            for (name, key), values in series.items()
            if key == s
        }
        site = {
            name: values.get(when)
            for (name, key), values in series.items()
            if key.upper() == "ENVIRONMENT"
        }
        size = sizes.get(z)
        environment, month, day, hour, minute = when
        zones[zone] = {
            "sensible": at.get("Supply Air Sensible Cooling Rate", 0.0) / 1000.0,
            "latent": at.get("Supply Air Latent Cooling Rate", 0.0) / 1000.0,
            "total": total[when] / 1000.0,
            "zoneTotal": at.get("Zone Total Cooling Rate", 0.0) / 1000.0,
            "ventilation": {
                "sensible": at.get("Outdoor Air Sensible Cooling Rate", 0.0) / 1000.0,
                "latent": at.get("Outdoor Air Latent Cooling Rate", 0.0) / 1000.0,
                "total": at.get("Outdoor Air Total Cooling Rate", 0.0) / 1000.0,
                "flow": at.get("Outdoor Air Standard Density Volume Flow Rate", 0.0),
            },
            "peak": {
                "designDay": environment,
                "month": month,
                "day": day,
                "time": f"{hour:02d}:{minute:02d}",
                "outdoorDB": site.get("Site Outdoor Air Drybulb Temperature"),
                "outdoorW": site.get("Site Outdoor Air Humidity Ratio"),
                "zoneW": series.get(("Zone Air Humidity Ratio", z), {}).get(when),
                "zoneRH": series.get(("Zone Air Relative Humidity", z), {}).get(when),
            },
            "airflow": float(size[2]) if size else None,
            "sizing": {
                "sensible": float(size[1]) / 1000.0 if size else None,
                "designDay": size[3] if size else None,
                "time": size[4] if size else None,
            },
            "components": components.get(z, {}),
        }
    combined: dict[tuple, float] = {}
    for system in model.systems.values():
        for when, value in series.get(
            ("Zone Ideal Loads Supply Air Total Cooling Rate", system.upper()), {}
        ).items():
            combined[when] = combined.get(when, 0.0) + value
    building = None
    if combined:
        when = max(combined, key=lambda k: combined[k])
        building = {
            "total": combined[when] / 1000.0,
            "designDay": when[0],
            "month": when[1],
            "day": when[2],
            "time": f"{when[3]:02d}:{when[4]:02d}",
        }
    return {"zones": zones, "envelope": envelope, "building": building}


def _series(con: sqlite3.Connection) -> dict[tuple[str, str], dict[tuple, float]]:
    out: dict[tuple[str, str], dict[tuple, float]] = {}
    query = (
        "select d.Name, d.KeyValue, e.EnvironmentName, t.Month, t.Day, t.Hour, t.Minute, r.Value "
        "from ReportData r "
        "join ReportDataDictionary d on r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex "
        "join Time t on r.TimeIndex = t.TimeIndex "
        "left join EnvironmentPeriods e on t.EnvironmentPeriodIndex = e.EnvironmentPeriodIndex "
        "where t.WarmupFlag is null or t.WarmupFlag = 0"
    )
    for name, key, env, month, day, hour, minute, value in con.execute(query):
        out.setdefault((name, str(key).upper()), {})[(env, month, day, hour, minute)] = value
    return out


def _components(con: sqlite3.Connection) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    query = (
        "select ReportForString, RowName, Value from TabularDataWithStrings "
        "where ReportName = 'Zone Component Load Summary' "
        "and TableName = 'Estimated Cooling Peak Load Components' and ColumnName = 'Total'"
    )
    rows: dict[str, dict[str, float]] = {}
    for zone, row, value in con.execute(query):
        number = _number(value)
        if number is not None:
            rows.setdefault(zone.upper(), {})[row.strip()] = number
    for zone, values in rows.items():
        out[zone] = {
            key: sum(values.get(name, 0.0) for name in names) / 1000.0
            for key, names in COMPONENTS.items()
        }
        out[zone]["total"] = values.get("Grand Total", 0.0) / 1000.0
    return out


def _envelope(con: sqlite3.Connection) -> dict[str, Any]:
    """U-values (with films) of the opaque constructions and U / SHGC of the glazing, from the
    Envelope Summary."""
    out: dict[str, Any] = {"opaque": {}, "glazing": {}}
    query = (
        "select TableName, RowName, ColumnName, Value from TabularDataWithStrings "
        "where ReportName = 'EnvelopeSummary' and TableName in "
        "('Opaque Exterior', 'Exterior Fenestration')"
    )
    rows: dict[tuple[str, str], dict[str, str]] = {}
    for table, row, column, value in con.execute(query):
        rows.setdefault((table, row), {})[column.strip()] = str(value).strip()
    for (table, _), cols in rows.items():
        if table == "Opaque Exterior":
            name = cols.get("Construction", "").upper()
            u = _number(cols.get("U-Factor with Film"))
            if name and u is not None:
                out["opaque"][name] = u
        elif table == "Exterior Fenestration":
            name = cols.get("Construction", "").upper()
            u = _number(cols.get("Glass U-Factor"))
            shgc = _number(cols.get("Glass SHGC"))
            if name and u is not None:
                out["glazing"][name] = {"u": u, "shgc": shgc}
    return out

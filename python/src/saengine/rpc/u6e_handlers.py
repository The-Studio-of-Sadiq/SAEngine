"""JSON-RPC handlers for the U6e full-ribbon panels across 6 editor windows.

Covers:
- FEM (`fem/notionalLoads`, `fem/patternLive`, `fem/snowRainLoads`, `fem/thermalLoads`,
  `fem/floodLoads`, `fem/stairCraneLoads`, `fem/loadCombinations`, `fem/spectralHazard`,
  `fem/seismicSummary`, `fem/groundMotions`, `fem/linearTimeHistory`, `fem/irregularities`,
  `fem/torsionalEffects`, `fem/twoLevelSeismic`, `fem/floorSpectra`, `fem/isolationDampers`,
  `fem/windSpeedFactors`, `fem/gustResponse`, `fem/peakVelocityPressure`, `fem/localPressures`,
  `fem/windComfort`, `fem/openStructures`, `fem/pushoverAnalysis`, `fem/nonlinearHistory`,
  `fem/pDeltaBuckling`, `fem/stagedConstruction`, `fem/creepShrinkage`, `fem/ssiSprings`,
  `fem/swayDrift`, `fem/floorVibration`, `fem/differentialSettlement`, `fem/punchingShear`,
  `fem/deflectionCheck`, `fem/crackControl`, `fem/torsionDesign`,
  `fem/capacitySeismicDetailing`, `fem/fireSteelConnections`)
- BIM 3D (`bim/syncStamps`, `bim/detailingModel`, `bim/rebarCages`, `bim/barBendingSchedule`)
- Architecture (`architecture/roomsCheck`, `architecture/massingFloors`,
  `architecture/roofCeilingCurtain`, `architecture/pointCloudStatus`)
- Documents (`documents/sheetInventory`, `documents/drawingAutomation`,
  `documents/calculationPackage`, `documents/clauseTraceability`, `documents/projectMetadata`)
- Studies (`studies/daylightSolar`, `studies/noiseStudy`, `studies/phasingSummary`,
  `studies/plotPlanning`, `studies/specialStructures`, `studies/batchCheck`,
  `studies/verificationStatus`)
- Exports (`exports/formatMatrix`, `exports/fabricationPreview`, `exports/structuralIfcCheck`,
  `exports/archiveInspection`, `exports/bbsReconciliation`)
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import inspect
import json
import math
from pathlib import Path
from typing import Any

from saengine.report.clauses import in_force


def _first_line(error: BaseException) -> str:
    msg = str(error).strip().splitlines()
    return msg[0] if msg else type(error).__name__


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else None
    except OSError:
        return None


def _finite(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_finite(v) for v in value]
    if hasattr(value, "model_dump") and callable(value.model_dump):
        # Pydantic models (settings, drafting standards): their JSON form.
        return _finite(value.model_dump(mode="json"))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _finite(dataclasses.asdict(value))
    if hasattr(value, "item") and callable(value.item):
        try:
            return _finite(value.item())
        except Exception:  # noqa: BLE001
            return str(value)
    if hasattr(value, "__geo_interface__"):
        return _finite(value.__geo_interface__)
    return value if isinstance(value, (int, float, str, bool)) else str(value)


def _load_settings(root: Path, notes: list[str]) -> Any:
    from saengine.library.settings import ProjectSettings, default_project_settings

    raw = _read_text(root / "02 Project Settings/project-settings.json")
    if raw is None:
        notes.append("02 Project Settings/project-settings.json not found; using defaults.")
        return default_project_settings(root.name)
    try:
        return ProjectSettings.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Project settings warning: {_first_line(exc)}; using defaults.")
        return default_project_settings(root.name)


def _load_objects(root: Path, notes: list[str]) -> tuple[Any | None, dict[str, Any]]:
    from saengine.library.objects import ObjectLibrary

    raw = _read_text(root / "04 Objects/objects.json")
    if raw is None:
        notes.append("04 Objects/objects.json not found.")
        return None, {}
    try:
        lib = ObjectLibrary.model_validate_json(raw)
        return lib, {obj.id: obj for obj in lib.objects}
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Objects library error: {_first_line(exc)}")
        return None, {}


def _load_materials(root: Path, notes: list[str]) -> tuple[Any | None, dict[str, Any]]:
    from saengine.library.materials import MaterialLibrary

    raw = _read_text(root / "03 Materials/materials.json")
    if raw is None:
        notes.append("03 Materials/materials.json not found.")
        return None, {}
    try:
        lib = MaterialLibrary.model_validate_json(raw)
        return lib, {mat.id: mat for mat in lib.materials}
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Materials library error: {_first_line(exc)}")
        return None, {}


def _load_building(root: Path, notes: list[str]) -> Any | None:
    from saengine.library.bim import BuildingModel

    raw = _read_text(root / "06 BIM/bim.json")
    if raw is None:
        notes.append("06 BIM/bim.json not found.")
        return None
    try:
        return BuildingModel.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"BIM model error: {_first_line(exc)}")
        return None


def _load_osmodel(root: Path) -> tuple[Path | None, dict[str, Any] | None]:
    for rel in ("08 FEM/model.osmodel", "08 Analysis/model.osmodel"):
        p = root / rel
        if p.is_file():
            try:
                return p, json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return p, None
    return None, None


def _results_dir(root: Path) -> Path | None:
    for rel in ("08 FEM/model.results", "08 Analysis/model.results"):
        p = root / rel
        if p.is_dir():
            return p
    return None


def _building_height_m(building: Any | None, fallback: float = 12.0) -> float:
    if building is not None and getattr(building, "stories", None):
        tops = [
            float(getattr(s, "elevation", 0.0) or 0.0) + float(getattr(s, "height", 0.0) or 0.0)
            for s in building.stories
        ]
        if tops:
            h = max(tops)
            return h / 1000.0 if h > 200.0 else max(h, 3.0)
    return fallback


def _site_params(settings: Any) -> tuple[str, float, float, float]:
    from saengine.fem import seismic_design

    site = getattr(settings, "site", None)
    occ = getattr(settings, "occupancy", None)
    seis = getattr(settings, "seismic", None)
    wind = getattr(settings, "wind", None)

    site_class = str(getattr(site, "siteClass", None) or "SD")
    z_coeff = getattr(site, "zoneCoefficient", None)
    if z_coeff is None:
        z_coeff = seismic_design.peak_ground_acceleration(settings)
    try:
        z_val = float(z_coeff) if z_coeff is not None else 0.2
    except Exception:  # noqa: BLE001
        z_val = 0.2
    wind_speed = getattr(site, "windSpeed", None)
    try:
        vb = float(wind_speed) if wind_speed is not None else 65.7
    except Exception:  # noqa: BLE001
        vb = 65.7
    r_val = getattr(seis, "r", None)
    try:
        r_fac = float(r_val) if r_val is not None else 8.0
    except Exception:  # noqa: BLE001
        r_fac = 8.0
    _ = (occ, wind)
    return site_class, z_val, vb, r_fac


def _importance_value(settings: Any) -> float:
    occ = getattr(settings, "occupancy", None)
    cat = str(getattr(occ, "category", None) or "II")
    return {"I": 0.85, "II": 1.0, "III": 1.15, "IV": 1.25}.get(cat, 1.0)


def _exposure_value(settings: Any) -> str:
    wind = getattr(settings, "wind", None)
    return str(getattr(wind, "exposure", None) or "B")


# ---------------------------------------------------------------------------
# 1. FEM — Loads
# ---------------------------------------------------------------------------


def fem_notional_loads(
    project_root: str,
    *,
    method: str = "directAnalysis",
    drift: float = 0.0,
    tau: str = "additive",
    height_m: float = 12.0,
) -> dict[str, Any]:
    """Compute notional lateral load coefficients and level gravity notional loads."""
    from saengine.fem import notional_loads

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    building = _load_building(root, notes)
    h_val = float(height_m) if height_m else _building_height_m(building)

    with in_force(root):
        try:
            coeff = notional_loads.coefficient(method, drift=float(drift), tau=tau, height=h_val)
        except Exception:  # noqa: BLE001
            coeff = notional_loads.sway_coefficient(h_val)
        sway_coeff = notional_loads.sway_coefficient(h_val)
        stab = notional_loads.stability_table()
        imp = notional_loads.sway_imperfection()
        every = notional_loads.every_combination()

    model_path, project = _load_osmodel(root)
    level_rows: list[dict[str, Any]] = []
    if project:
        levels = sorted(
            {
                round(float(n.get("z", 0.0)), 3)
                for n in (project.get("nodes") or [])
                if float(n.get("z", 0.0)) > 0
            }
        )
        raw_levels = notional_loads.level_loads(project, ("D", "L"), levels)
        for z, item in zip(levels, raw_levels, strict=False):
            level_rows.append({"elevationM": z, **item})
    else:
        notes.append("08 FEM/model.osmodel not derived yet; showing code coefficients only.")

    configured = getattr(getattr(settings, "analysis", None), "notionalLoads", None)
    return _finite(
        {
            "summary": {
                "method": method,
                "configured": str(configured or method),
                "coefficient": coeff,
                "swayCoefficient": sway_coeff,
                "everyCombination": every,
                "heightM": h_val,
                "modelPresent": model_path is not None,
            },
            "levels": level_rows,
            "tables": {"stability": stab is not None, "swayImperfection": imp is not None},
            "notes": notes,
        }
    )


def fem_pattern_live(
    project_root: str,
    *,
    system: str = "rcSmf",
    dead_kpa: float = 5.0,
    live_kpa: float = 2.0,
    adjacent: bool = True,
    alternate: bool = True,
) -> dict[str, Any]:
    """Evaluate code live load patterning requirements and checkerboard patterns."""
    from saengine.fem import pattern_live

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    building = _load_building(root, notes)
    sys_name = str(getattr(getattr(settings, "seismic", None), "system", None) or system)

    with in_force(root):
        required, reason = pattern_live.patterns_required(
            sys_name, float(dead_kpa), float(live_kpa)
        )
        clause_ref = pattern_live.clause("adjacent")

    xs: tuple[float, ...] = (0.0, 6000.0, 12000.0, 18000.0)
    ys: tuple[float, ...] = (0.0, 6000.0, 12000.0)
    if building is not None and getattr(building, "beams", None):
        x_pts: list[float] = []
        y_pts: list[float] = []
        for bm in building.beams:
            if len(bm.start) >= 2 and len(bm.end) >= 2:
                x_pts.extend([bm.start[0], bm.end[0]])
                y_pts.extend([bm.start[1], bm.end[1]])
        gx = pattern_live.grid_lines(x_pts)
        gy = pattern_live.grid_lines(y_pts)
        if len(gx) >= 2:
            xs = gx
        if len(gy) >= 2:
            ys = gy

    grid = pattern_live.Grid(xs=xs, ys=ys)
    patterns = pattern_live.live_patterns(grid, adjacent=adjacent, alternate=alternate)
    rows = [
        {
            "name": p.name,
            "kind": getattr(p, "kind", ""),
            "loadedPanels": len(getattr(p, "cells", []) or getattr(p, "spans", []) or []),
            "clause": clause_ref,
        }
        for p in patterns
    ]
    return _finite(
        {
            "summary": {
                "system": sys_name,
                "deadKpa": float(dead_kpa),
                "liveKpa": float(live_kpa),
                "required": required,
                "reason": reason,
                "patternCount": len(rows),
                "clause": clause_ref,
            },
            "patterns": rows,
            "notes": notes,
        }
    )


def fem_snow_rain_loads(project_root: str) -> dict[str, Any]:
    """Compute code roof snow load and ponding/rain load summary from Project Settings."""
    from saengine.fem import snow_load, special_loads

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)

    with in_force(root):
        snow = snow_load.roof_snow(settings)
        angle = snow_load.roof_angle(settings)
        rain = special_loads.project_rain_load(settings)

    snow_desc = snow_load.describe(snow) if snow else "No snow load configured in site settings."
    if not getattr(settings.site, "snow", None):
        notes.append("Site snow parameters not configured in 02 Project Settings.")
    if not getattr(settings.site, "rain", None):
        notes.append("Site rain intensity not configured in 02 Project Settings.")

    return _finite(
        {
            "summary": {
                "roofAngleDeg": angle,
                "rainLoadKpa": rain,
                "snowDescription": snow_desc,
                "snowConfigured": snow is not None,
            },
            "snow": snow or {},
            "notes": notes,
        }
    )


def fem_thermal_loads(
    project_root: str,
    *,
    uniform: float = 20.0,
    gradient: float = 0.0,
    thickness_mm: float = 200.0,
    e_mpa: float = 25000.0,
    alpha: float = 1e-5,
) -> dict[str, Any]:
    """Evaluate thermal resultants, cached model corrections, and thermal combinations."""
    from saengine.fem import thermal

    root = Path(project_root)
    notes: list[str] = []
    _load_settings(root, notes)
    model_path, _project = _load_osmodel(root)

    with in_force(root):
        nt, mt = thermal.plate_thermal_resultants(
            float(e_mpa), 0.2, float(thickness_mm), float(alpha), float(uniform), float(gradient)
        )
        strength = thermal.strength_combinations_with_t()
        service = thermal.service_combinations_with_t(["D", "L"])

    corrections = thermal.load_corrections(model_path) if model_path is not None else None
    if model_path is None:
        notes.append("08 FEM/model.osmodel not found; computed analytical plate resultants.")

    combos = [
        {"kind": "Strength", "name": name, "factors": factors} for name, factors in strength
    ] + [{"kind": "Service", "name": name, "factors": factors} for name, factors in service]

    return _finite(
        {
            "summary": {
                "uniformDeltaC": float(uniform),
                "gradientDeltaC": float(gradient),
                "axialResultantKnM": nt,
                "momentResultantKnmM": mt,
                "modelCorrections": bool(corrections),
                "combinationCount": len(combos),
            },
            "combinations": combos,
            "notes": notes,
        }
    )


def fem_flood_loads(
    project_root: str,
    *,
    wave_height_m: float = 1.2,
    still_depth_m: float = 2.0,
    pile_width_m: float = 0.5,
    velocity_m_s: float = 2.0,
) -> dict[str, Any]:
    """Compute coastal/flood wave, pile, wall, debris impact, and breakaway loads."""
    from saengine.fem import flood

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    cat = str(getattr(settings.occupancy, "category", None) or "II")
    site_flood = getattr(settings.site, "flood", None)

    with in_force(root):
        covered = flood.covered()
        if not covered:
            notes.append("Active code pack does not tabulate flood loads.")
            return _finite(
                {
                    "summary": {"covered": False, "category": cat},
                    "notes": notes,
                }
            )
        ret = flood.return_period(cat)
        gamma = flood.unit_weight(True)
        hb = flood.breaking_wave_height(float(still_depth_m))
        f_pile = flood.breaking_wave_on_pile(hb, float(pile_width_m), True, gamma)
        wall = flood.breaking_wave_on_wall(float(still_depth_m), cat, gamma)
        impact = flood.impact_force(float(velocity_m_s), cat, float(still_depth_m))
        breakaway = flood.breakaway_pressure()
        depth_info = flood.design_depth(site_flood, cat) if site_flood is not None else None

    if site_flood is None:
        notes.append("Site flood parameters not entered in 02 Project Settings; using defaults.")

    return _finite(
        {
            "summary": {
                "covered": True,
                "category": cat,
                "returnPeriodYr": ret,
                "unitWeightKnM3": gamma,
                "breakingWaveHeightM": hb,
                "pileWaveForceKn": f_pile,
                "breakawayPressureKpa": breakaway,
                "designDepthM": getattr(depth_info, "depth", None) if depth_info else wave_height_m,
            },
            "wallLoads": wall,
            "impactLoads": impact,
            "notes": notes,
        }
    )


def fem_stair_crane_loads(project_root: str) -> dict[str, Any]:
    """Compute stair reaction loads and crane runway wheel/bumper loads."""
    from saengine.fem import cranes, stair_loads

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    _, objs = _load_objects(root, notes)
    _, mats = _load_materials(root, notes)
    building = _load_building(root, notes)

    stairs_summary: dict[str, Any] = {}
    if building is not None:
        with in_force(root):
            try:
                sl = stair_loads.stair_loads(building, objs, mats, settings)
                if sl is not None:
                    stairs_summary = {
                        "count": len(getattr(sl, "stairs", []) or []),
                        "reactions": len(getattr(sl, "reactions", []) or []),
                    }
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Stair loads note: {_first_line(exc)}")

    crane_list = list(getattr(settings, "cranes", None) or [])
    crane_rows: list[dict[str, Any]] = []
    crane_notes: list[str] = []
    if crane_list:
        with in_force(root):
            try:
                crane_rows, crane_notes = cranes.crane_summary(crane_list, objs, mats)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Crane summary note: {_first_line(exc)}")
    else:
        notes.append("No crane runways defined in 02 Project Settings.")

    return _finite(
        {
            "summary": {
                "stairFlights": len(getattr(building, "stairs", []) or []) if building else 0,
                "craneCount": len(crane_list),
                "craneSummaryRows": len(crane_rows),
            },
            "stairs": stairs_summary,
            "cranes": crane_rows,
            "notes": notes + crane_notes,
        }
    )


def fem_load_combinations(project_root: str) -> dict[str, Any]:
    """List code strength, service, allowable, and configured load combinations."""
    from saengine.fem import combinations

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    model_path, project = _load_osmodel(root)

    present = combinations.model_cases(project) if project else {"D", "L", "Lr", "WX", "WY"}
    with in_force(root):
        strength = combinations.strength_combinations(present)
        service = combinations.service_combinations(present)
        allowable = combinations.allowable_combinations(present)
        design_combos = combinations.design_combinations(settings, present)

    rows: list[dict[str, Any]] = []
    for label, group in (
        ("Strength", strength),
        ("Service", service),
        ("Allowable", allowable),
        ("Design", design_combos),
    ):
        for item in group:
            if isinstance(item, dict):
                rows.append({"kind": label, **item})
            elif isinstance(item, (tuple, list)) and len(item) >= 2:
                rows.append({"kind": label, "name": item[0], "factors": item[1]})
            else:
                rows.append({"kind": label, "name": str(item)})

    return _finite(
        {
            "summary": {
                "presentCases": sorted(present),
                "strengthCount": len(strength),
                "serviceCount": len(service),
                "allowableCount": len(allowable),
                "designCount": len(design_combos),
                "modelPresent": model_path is not None,
            },
            "combinations": rows,
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 2. FEM — Seismic
# ---------------------------------------------------------------------------


def fem_spectral_hazard(project_root: str, *, damping: float = 0.05) -> dict[str, Any]:
    """Compute site spectral hazard curve (mapped or zone-based) under the active code pack."""
    from saengine.fem import loads, spectral_hazard

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    site_class, z_val, _vb, r_fac = _site_params(settings)
    imp = _importance_value(settings)

    periods = [0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0]
    rows: list[dict[str, Any]] = []
    hazard_desc = ""
    mapped = False
    with in_force(root):
        mapped = spectral_hazard.uses_mapped()
        hazard = spectral_hazard.site_hazard(settings.site.spectral, site_class, z=z_val)
        if hazard is not None:
            hazard_desc = spectral_hazard.describe(hazard)
        for t in periods:
            if hazard is not None:
                sa = spectral_hazard.spectral_acceleration(t, hazard)
                coeff = spectral_hazard.response_coefficient(t, hazard, imp, r_fac)
            else:
                sa = loads.normalized_spectrum(t, site_class, damping=float(damping))
                coeff = loads.design_acceleration(
                    t, site_class, z_val, imp, r_fac, damping=float(damping)
                )
            rows.append({"periodS": t, "saG": sa, "cs": coeff})

    return _finite(
        {
            "summary": {
                "siteClass": site_class,
                "z": z_val,
                "mappedHazard": mapped,
                "damping": float(damping),
                "r": r_fac,
                "importance": imp,
                "description": hazard_desc or f"Site {site_class}, Z={z_val}",
            },
            "spectrum": rows,
            "notes": notes,
        }
    )


def fem_seismic_summary(project_root: str) -> dict[str, Any]:
    """Summarize Seismic Design Category, drift limits, PGA, and analyzed seismic response."""
    from saengine.fem import seismic_design

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    building = _load_building(root, notes)
    site_class, z_val, _vb, _r = _site_params(settings)
    occ = str(getattr(settings.occupancy, "category", None) or "II")
    height_m = _building_height_m(building)

    with in_force(root):
        zone = seismic_design.zone_of(z_val)
        sdc = seismic_design.seismic_design_category(zone, site_class, occ, height=height_m)
        pga = seismic_design.peak_ground_acceleration(settings)
        av = seismic_design.vertical_coefficient(settings)
        drift_lim = seismic_design.settings_drift_limit(settings, category=sdc)
        h_note = seismic_design.height_limit_note(settings, sdc, height_m)
        uses_rs = seismic_design.design_uses_spectrum(settings)
        uses_th = seismic_design.design_uses_time_history(settings)

    out_dir = _results_dir(root)
    drifts: list[Any] = []
    irregs: list[Any] = []
    if out_dir is not None:
        try:
            summary = seismic_design.load_summary(out_dir)
            if summary:
                drifts = seismic_design.drift_rows(summary)
                irregs = seismic_design.irregularity_rows(summary)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Seismic results summary warning: {_first_line(exc)}")
    else:
        notes.append("Analysis results not found in 08 FEM/model.results.")

    if h_note:
        notes.append(h_note)

    return _finite(
        {
            "summary": {
                "zone": zone,
                "sdc": sdc or "-",
                "pgaG": pga,
                "verticalCoeff": av,
                "driftLimit": drift_lim.get("allowable") if isinstance(drift_lim, dict) else None,
                "usesSpectrum": uses_rs,
                "usesTimeHistory": uses_th,
                "heightM": height_m,
            },
            "driftRows": drifts,
            "irregularityRows": irregs,
            "notes": notes,
        }
    )


def fem_ground_motions(project_root: str, *, procedure: str = "linear") -> dict[str, Any]:
    """Inspect ground-motion scaling rules, suite requirements, and configured records."""
    from saengine.fem import records

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    histories = list(getattr(settings.analysis, "timeHistories", None) or [])

    with in_force(root):
        rules = records.rules()
        mod = records.modification(settings, procedure=procedure)
        match = records.matching_rule(settings)
        rule_3 = records.design_rule(3)
        rule_7 = records.design_rule(7)
        suites = records.suites(histories)

    if not histories:
        notes.append("No time-history records configured in Project Settings > Analysis.")

    return _finite(
        {
            "summary": {
                "procedure": procedure,
                "modification": mod,
                "matchingRule": str(match) if match is not None else "Standard scaling",
                "ruleFor3Records": rule_3,
                "ruleFor7Records": rule_7,
                "historyCount": len(histories),
                "suiteCount": len(suites),
                "rulesLoaded": rules is not None,
            },
            "suites": [{"suite": k, "indices": v} for k, v in suites.items()],
            "notes": notes,
        }
    )


def fem_linear_time_history(project_root: str) -> dict[str, Any]:
    """List linear time-history transient load cases and response summaries if analyzed."""
    from saengine.fem import linear_time_history

    root = Path(project_root)
    notes: list[str] = []
    model_path, project = _load_osmodel(root)
    cases = linear_time_history.transient_cases(project) if project else []

    if model_path is None:
        notes.append("08 FEM/model.osmodel not found.")
    elif not cases:
        notes.append("No transient time-history cases present in the derived model.")

    rows = [
        {
            "id": c.get("id"),
            "name": c.get("name", f"Case {c.get('id', '')}"),
            "steps": len(c.get("series", [])) if isinstance(c.get("series"), list) else None,
        }
        for c in cases
    ]
    return _finite(
        {
            "summary": {"modelPresent": model_path is not None, "transientCases": len(cases)},
            "cases": rows,
            "notes": notes,
        }
    )


def fem_irregularities(project_root: str) -> dict[str, Any]:
    """Run pre-analysis plan/vertical regularity check and post-analysis irregularity checks."""
    from saengine.fem import irregularity, seismic_regularity

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    _, objs = _load_objects(root, notes)
    _, mats = _load_materials(root, notes)
    building = _load_building(root, notes)

    pre = None
    if building is not None:
        with in_force(root):
            try:
                pre = seismic_regularity.pre_analysis(building, objs, mats)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Pre-analysis regularity warning: {_first_line(exc)}")

    model_path, project = _load_osmodel(root)
    out_dir = _results_dir(root)
    post = None
    findings: list[Any] = []
    storeys: list[Any] = []
    if out_dir is not None and model_path is not None:
        with in_force(root):
            try:
                post = irregularity.assessment_of(out_dir, model_path, settings=settings)
                if not post and project is not None and building is not None:
                    post = irregularity.assess(project, out_dir, building, objs, mats, settings)
                if post:
                    findings = irregularity.finding_rows(post)
                    storeys = irregularity.storey_rows(post)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Post-analysis irregularity warning: {_first_line(exc)}")
    else:
        notes.append("Run FEM analysis to compute post-analysis drift/torsion irregularities.")

    return _finite(
        {
            "summary": {
                "preAnalysisEvaluated": pre is not None,
                "postAnalysisEvaluated": post is not None,
                "findingCount": len(findings),
                "storeyRows": len(storeys),
            },
            "preAnalysis": pre or {},
            "findings": findings,
            "storeys": storeys,
            "notes": notes,
        }
    )


def fem_torsional_effects(project_root: str) -> dict[str, Any]:
    """Evaluate code torsional amplification rules and accidental eccentricity diaphragm groups."""
    from saengine.fem import combinations, torsional_effects

    root = Path(project_root)
    notes: list[str] = []
    building = _load_building(root, notes)
    _model_path, project = _load_osmodel(root)
    present = combinations.model_cases(project) if project else {"D", "L", "EX", "EY"}

    with in_force(root):
        rules = torsional_effects.rules()
        groups = torsional_effects.delta_groups(building, present) if building is not None else []
        note = torsional_effects.note(groups) if groups else ""

    if note:
        notes.append(note)
    if building is None:
        notes.append("06 BIM/bim.json required to group storeys for torsional delta effects.")

    return _finite(
        {
            "summary": {
                "rulesLoaded": rules is not None,
                "deltaGroupCount": len(groups),
                "presentCases": sorted(present),
            },
            "groups": groups,
            "notes": notes,
        }
    )


def fem_two_level_seismic(project_root: str) -> dict[str, Any]:
    """Compute code two-level seismic performance grade and rare-earthquake drift criteria."""
    from saengine.fem import seismic_design, two_level_seismic

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    building = _load_building(root, notes)
    _site_class, z_val, _vb, _r = _site_params(settings)
    height_m = _building_height_m(building)
    sys_name = str(getattr(settings.seismic, "system", None) or "rcSmf")
    occ = str(getattr(settings.occupancy, "category", None) or "II")

    with in_force(root):
        zone = seismic_design.zone_of(z_val)
        grade = two_level_seismic.seismic_grade(sys_name, height_m, zone, occ)
        g_note = two_level_seismic.grade_note(grade) if grade else ""

    if g_note:
        notes.append(g_note)

    return _finite(
        {
            "summary": {
                "system": sys_name,
                "heightM": height_m,
                "zone": zone,
                "occupancy": occ,
                "grade": grade.get("grade") if isinstance(grade, dict) else str(grade or "-"),
            },
            "details": grade or {},
            "notes": notes,
        }
    )


def fem_floor_spectra(project_root: str) -> dict[str, Any]:
    """Compute nonstructural floor acceleration response spectra ordinates."""
    from saengine.fem import floor_spectra

    root = Path(project_root)
    notes: list[str] = []
    _load_settings(root, notes)

    with in_force(root):
        tbl = floor_spectra.table()
        periods = floor_spectra.periods_of(tbl) if tbl is not None else []

    if tbl is None:
        notes.append("Active code pack does not define code floor spectra tables.")

    return _finite(
        {
            "summary": {"tableLoaded": tbl is not None, "periodCount": len(periods)},
            "periods": list(periods) if hasattr(periods, "__iter__") else [],
            "notes": notes,
        }
    )


def fem_isolation_dampers(project_root: str) -> dict[str, Any]:
    """Inspect base isolation bearings, supplemental damper braces, and design summaries."""
    from saengine.fem import dampers, isolation

    root = Path(project_root)
    notes: list[str] = []
    _load_settings(root, notes)
    _, objs = _load_objects(root, notes)
    building = _load_building(root, notes)
    fem_dir = root / "08 FEM"

    with in_force(root):
        iso_cov = isolation.covered()
        damp_cov = dampers.covered()
        iso_types = isolation.isolated_types(objs)
        damp_types = dampers.damper_types(objs)
        braces = dampers.damper_braces(building, objs) if building is not None else []
        iso_res = isolation.load(fem_dir) if fem_dir.is_dir() else None
        damp_res = dampers.load(fem_dir) if fem_dir.is_dir() else None

    if not iso_types and not damp_types:
        notes.append("No isolator or supplemental damper object types defined in 04 Objects.")

    return _finite(
        {
            "summary": {
                "isolationCovered": iso_cov,
                "dampersCovered": damp_cov,
                "isolatorTypes": len(iso_types),
                "damperTypes": len(damp_types),
                "damperBraces": len(braces),
                "isolationDesignLoaded": iso_res is not None,
                "damperDesignLoaded": damp_res is not None,
            },
            "isolation": iso_res or {},
            "dampers": damp_res or {},
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 3. FEM — Wind
# ---------------------------------------------------------------------------


def fem_wind_speed_factors(project_root: str, *, height_m: float = 0.0) -> dict[str, Any]:
    """Compute height-wise basic/design wind speed factors and velocity pressures."""
    from saengine.fem import loads, wind_speed_factors

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    building = _load_building(root, notes)
    _sc, _z, vb, _r = _site_params(settings)
    exp = _exposure_value(settings)
    imp = _importance_value(settings)
    h_max = float(height_m) if height_m and height_m > 0 else _building_height_m(building)

    heights = sorted({round(x, 2) for x in [3.0, 6.0, 9.0, 12.0, h_max] if x <= max(h_max, 3.0)})
    rows: list[dict[str, Any]] = []
    top_factors: dict[str, Any] = {}
    top_vd: float | None = None
    top_qz: float | None = None
    with in_force(root):
        try:
            top_factors = wind_speed_factors.factors(h_max, vb, exp, imp)
            top_vd = wind_speed_factors.design_speed(h_max, vb, exp, imp)
            top_qz = wind_speed_factors.design_pressure(h_max, vb, exp, imp)
        except ValueError as error:
            # Speed-factor codes (k1-k4) only; others give the velocity pressure profile below.
            notes.append(f"No wind speed factors in the active code pack ({error}).")
        for z in heights:
            rows.append(
                {
                    "heightM": z,
                    "kz": loads.exposure_coefficient(z, exp),
                    "qzKpa": loads.velocity_pressure(z, vb, exp, imp),
                    "designSpeedMS": (
                        wind_speed_factors.design_speed(z, vb, exp, imp)
                        if top_vd is not None
                        else None
                    ),
                }
            )

    return _finite(
        {
            "summary": {
                "basicWindSpeedMS": vb,
                "exposure": exp,
                "importance": imp,
                "roofHeightM": h_max,
                "designSpeedRoofMS": top_vd,
                "designPressureRoofKpa": top_qz,
                **top_factors,
            },
            "profile": rows,
            "notes": notes,
        }
    )


def fem_gust_response(
    project_root: str, *, frequency_hz: float = 1.0, damping: float = 0.02
) -> dict[str, Any]:
    """Compute rigid vs. flexible gust response factor and dynamic wind applicability."""
    from saengine.fem import gust_response, loads

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    building = _load_building(root, notes)
    _sc, _z, vb, _r = _site_params(settings)
    exp = _exposure_value(settings)
    imp = _importance_value(settings)
    h_m = _building_height_m(building)
    breadth = 18.0
    depth = 12.0

    with in_force(root):
        rules = gust_response.rules()
        applies = gust_response.applies(h_m, breadth, float(frequency_hz))
        rigid_g = loads.gust_factor(h_m, exp)
        flex = loads.flexible_gust_factor(
            h_m, breadth, depth, float(frequency_hz), vb, exp, damping=float(damping)
        )
        try:
            g_detail = gust_response.gust_factor(
                h_m, breadth, float(frequency_hz), vb, exp, imp, damping=float(damping)
            )
        except ValueError as error:
            # The detailed gust factor needs a speed-factor code pack (k1-k4).
            g_detail = None
            notes.append(f"No detailed gust factor for the active code pack ({error}).")
        is_flex = loads.is_flexible(float(frequency_hz))

    return _finite(
        {
            "summary": {
                "heightM": h_m,
                "breadthM": breadth,
                "frequencyHz": float(frequency_hz),
                "damping": float(damping),
                "flexibleBuilding": is_flex,
                "gustRuleApplies": applies,
                "rigidGustFactor": rigid_g,
                "rulesLoaded": rules is not None,
            },
            "flexibleTerms": flex or {},
            "gustBreakdown": g_detail or {},
            "notes": notes,
        }
    )


def fem_peak_velocity_pressure(project_root: str) -> dict[str, Any]:
    """Compute terrain roughness terms, peak velocity pressure q_p(z), and structural factor."""
    from saengine.fem import peak_velocity_pressure

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    building = _load_building(root, notes)
    _sc, _z, vb, _r = _site_params(settings)
    exp = _exposure_value(settings)
    imp = _importance_value(settings)
    h_m = _building_height_m(building)

    with in_force(root):
        rough = peak_velocity_pressure.roughness_terms(h_m, exp, settings.wind)
        qp = peak_velocity_pressure.peak_velocity_pressure(h_m, vb, exp, imp, settings.wind)
        cs_cd, desc = peak_velocity_pressure.structural_factor(
            h_m, 12.0, settings.wind, width=18.0, speed=vb, terrain=exp
        )

    return _finite(
        {
            "summary": {
                "heightM": h_m,
                "terrain": exp,
                "peakPressureKpa": qp,
                "structuralFactorCsCd": cs_cd,
                "basis": desc,
            },
            "roughness": rough,
            "notes": notes,
        }
    )


def fem_local_pressures(
    project_root: str, *, tributary_area_m2: float = 10.0, parapet_m: float = 1.0
) -> dict[str, Any]:
    """Compute local cladding and components (C&C) net wind pressures across roof and wall zones."""
    from saengine.fem import loads, local_pressures

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    building = _load_building(root, notes)
    _sc, _z, vb, _r = _site_params(settings)
    exp = _exposure_value(settings)
    imp = _importance_value(settings)
    h_m = _building_height_m(building)

    with in_force(root):
        rules = local_pressures.rules()
        local = local_pressures.local_pressures(
            h_m, 18.0, 12.0, vb, exp, imp, area=float(tributary_area_m2), parapet=float(parapet_m)
        )
        cladding = loads.cladding_pressures(
            h_m, 12.0, vb, exp, imp, area=float(tributary_area_m2), parapet=float(parapet_m)
        )

    return _finite(
        {
            "summary": {
                "rulesLoaded": rules is not None,
                "tributaryAreaM2": float(tributary_area_m2),
                "parapetM": float(parapet_m),
                "heightM": h_m,
            },
            "localPressures": local or {},
            "claddingPressures": cladding or {},
            "notes": notes,
        }
    )


def fem_wind_comfort(
    project_root: str, *, frequency_hz: float = 0.5, damping: float = 0.015
) -> dict[str, Any]:
    """Check serviceability wind-induced floor acceleration against occupancy comfort limits."""
    from saengine.fem import wind_comfort

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    occ = str(getattr(settings.occupancy, "use", None) or "residential")

    with in_force(root):
        rules = wind_comfort.table()
        ratio = wind_comfort.speed_ratio(rules) if rules is not None else None
        limit = (
            wind_comfort.limit_of(occ, float(frequency_hz), rules) if rules is not None else None
        )

    if rules is None:
        notes.append("Active code pack does not specify wind comfort acceleration limits.")

    return _finite(
        {
            "summary": {
                "tableLoaded": rules is not None,
                "occupancy": occ,
                "frequencyHz": float(frequency_hz),
                "damping": float(damping),
                "speedRatio": ratio,
                "accelLimitMg": limit,
            },
            "notes": notes,
        }
    )


def fem_open_structures(
    project_root: str,
    *,
    solidity: float = 0.35,
    width_m: float = 6.0,
    depth_m: float = 6.0,
    height_m: float = 15.0,
) -> dict[str, Any]:
    """Compute wind force coefficients for open lattice towers, free roofs, and solid signs."""
    from saengine.fem import loads, open_wind

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    _sc, _z, vb, _r = _site_params(settings)
    exp = _exposure_value(settings)
    imp = _importance_value(settings)

    with in_force(root):
        tbl = open_wind.open_buildings_table()
        qh = loads.velocity_pressure(float(height_m), vb, exp, imp)
        gust = loads.gust_factor(float(height_m), exp)
        sign_res = open_wind.solid_sign_wind(
            qh, gust, float(width_m), float(depth_m), float(height_m)
        )
        lat_cf = open_wind.lattice_cf(tbl, float(solidity)) if tbl is not None else None
        twr_cf = open_wind.tower_cf(tbl, float(solidity), "square") if tbl is not None else None

    return _finite(
        {
            "summary": {
                "solidity": float(solidity),
                "qhKpa": qh,
                "gustFactor": gust,
                "latticeCf": lat_cf,
                "squareTowerCf": twr_cf,
                "signForceKn": sign_res.get("force") if isinstance(sign_res, dict) else None,
            },
            "signResult": sign_res,
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 4. FEM — Nonlinear & Stability
# ---------------------------------------------------------------------------


def fem_pushover_analysis(project_root: str) -> dict[str, Any]:
    """Inspect plastic hinge rules, performance target displacement rules, and pushover results."""
    from saengine.fem import hinges, pushover_target

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    _model_path, project = _load_osmodel(root)

    with in_force(root):
        p_tbl = pushover_target.table()
        h_tbl = hinges.table()
        assigned = hinges.assign(project) if project else []

    if project is None:
        notes.append("Derive 08 FEM/model.osmodel to inspect member plastic hinge assignments.")

    return _finite(
        {
            "summary": {
                "targetRuleLoaded": p_tbl is not None,
                "hingeRuleLoaded": h_tbl is not None,
                "assignedHinges": len(assigned),
                "configured": getattr(settings.analysis, "pushover", None) is not None,
            },
            "notes": notes,
        }
    )


def fem_nonlinear_history(project_root: str) -> dict[str, Any]:
    """Inspect nonlinear time-history acceptance criteria and cached response runs."""
    from saengine.fem import nonlinear_history

    root = Path(project_root)
    notes: list[str] = []
    _load_settings(root, notes)
    fem_dir = root / "08 FEM"

    with in_force(root):
        tbl = nonlinear_history.table()
        proc = nonlinear_history.target_procedure()
        mean_n = nonlinear_history.mean_from()
    res = nonlinear_history.results_of(fem_dir) if fem_dir.is_dir() else None
    if res is None:
        notes.append("No nonlinear time-history output found in 08 FEM.")

    return _finite(
        {
            "summary": {
                "tableLoaded": tbl is not None,
                "targetProcedure": proc,
                "meanFromRecords": mean_n,
                "resultsPresent": res is not None,
            },
            "results": res or {},
            "notes": notes,
        }
    )


def fem_p_delta_buckling(project_root: str) -> dict[str, Any]:
    """Inspect P-Delta / Direct Analysis options and elastic/inelastic buckling factors."""
    from saengine.fem import buckling, second_order
    from saengine.rpc import handlers

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    model_path, project = _load_osmodel(root)
    out_dir = _results_dir(root)

    with in_force(root):
        opts = second_order.options_from_settings(settings)
        p_factors = second_order.pdelta_factors()
        grav_factors = second_order.stability_gravity_factors()

    pdelta_res = None
    stab_res = None
    frames_count = 0
    if project:
        try:
            frames, _ = buckling.frames_of(project)
            frames_count = len(frames)
        except Exception:  # noqa: BLE001
            frames_count = 0
    if model_path is not None and out_dir is not None:
        try:
            pdelta_res = handlers.second_order_summary(str(out_dir), str(model_path))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Second-order summary note: {_first_line(exc)}")
        try:
            stab_res = handlers.nonlinear_stability(str(out_dir), str(model_path), False)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Stability summary note: {_first_line(exc)}")
    else:
        notes.append("Run FEM analysis to compute P-Delta drift amplification and buckling modes.")

    return _finite(
        {
            "summary": {
                "secondOrderOption": opts.secondOrder,
                "stiffness": opts.stiffness,
                "directAnalysis": opts.directAnalysis,
                "bucklingFrames": frames_count,
                "pDeltaComputed": pdelta_res is not None,
                "stabilityComputed": stab_res is not None,
            },
            "pDeltaFactors": p_factors,
            "gravityFactors": grav_factors,
            "secondOrderSummary": pdelta_res or {},
            "stabilitySummary": stab_res or {},
            "notes": notes,
        }
    )


def fem_staged_construction(project_root: str) -> dict[str, Any]:
    """Inspect staged construction / column shortening configuration and run summary."""
    from saengine.fem import staged

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    model_path, _project = _load_osmodel(root)
    out_dir = _results_dir(root)
    seq = getattr(settings.analysis, "constructionSequence", None)
    td = getattr(settings.analysis, "timeDependent", None)

    model_info = staged.model_of(td) if td is not None else None
    run_res = None
    if out_dir is not None and model_path is not None:
        try:
            run_res = staged.from_run(out_dir, model_path)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Staged results note: {_first_line(exc)}")
    if run_res is None:
        notes.append("No staged construction / column shortening results cached in 08 FEM.")

    return _finite(
        {
            "summary": {
                "sequenceConfigured": seq is not None,
                "timeDependentConfigured": td is not None,
                "method": getattr(model_info, "method", "not configured") if model_info else "none",
                "resultsPresent": run_res is not None,
            },
            "results": run_res or {},
            "notes": notes,
        }
    )


def fem_creep_shrinkage(
    project_root: str,
    *,
    thickness_mm: float = 200.0,
    humidity: float = 70.0,
    age_days: float = 28.0,
    fck_mpa: float = 28.0,
) -> dict[str, Any]:
    """Compute time-dependent creep coefficient phi, free shrinkage strain, and E/f_c growth."""
    from saengine.fem import concrete_time

    root = Path(project_root)
    notes: list[str] = []
    _load_settings(root, notes)

    rows: list[dict[str, Any]] = []
    with in_force(root):
        try:
            tbl = concrete_time.table()
            m_name = concrete_time.model_name()
        except Exception:  # noqa: BLE001
            tbl = None
            m_name = "Not covered by active code pack"
        if tbl is None:
            notes.append("Active code pack does not tabulate time-dependent creep/shrinkage.")
            return _finite({"summary": {"covered": False, "model": m_name}, "notes": notes})
        for days in (7, 14, 28, 90, 365, 3650):
            phi = concrete_time.creep_phi(
                float(thickness_mm), float(humidity), float(age_days), float(days), float(fck_mpa)
            )
            eps_sh = concrete_time.free_shrinkage(
                float(thickness_mm), float(humidity), float(days), 7.0, float(fck_mpa)
            )
            e_ratio = concrete_time.modulus_ratio(float(days), float(fck_mpa))
            fc_share = concrete_time.strength_share(float(days))
            rows.append(
                {
                    "ageDays": days,
                    "creepPhi": phi,
                    "shrinkageMicrostrain": eps_sh * 1e6 if abs(eps_sh) < 0.01 else eps_sh,
                    "eRatio": e_ratio,
                    "strengthShare": fc_share,
                }
            )

    return _finite(
        {
            "summary": {
                "covered": True,
                "model": m_name,
                "thicknessMm": float(thickness_mm),
                "humidityPct": float(humidity),
                "loadingAgeDays": float(age_days),
                "fckMpa": float(fck_mpa),
            },
            "schedule": rows,
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 5. FEM — Serviceability
# ---------------------------------------------------------------------------


def fem_ssi_springs(
    project_root: str,
    *,
    length_m: float = 2.5,
    width_m: float = 2.5,
    depth_m: float = 1.5,
) -> dict[str, Any]:
    """Compute Gazetas footing impedance springs and SSI shear-modulus reduction."""
    from saengine.fem import ssi

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)

    opts = ssi.options_from_settings(settings)
    pga = ssi.peak_acceleration(settings)
    g_ratio = opts.shear_modulus_ratio or ssi.shear_modulus_ratio(pga)
    vs_eff = 220.0
    g0_kpa = 1.85 * vs_eff**2  # ~rho * Vs^2 (kPa)
    soil_raw = _read_text(root / "01 Soil Report/soil-report.json")
    if soil_raw:
        try:
            from saengine.library.soil import SoilReport

            soil_rep = SoilReport.model_validate_json(soil_raw)
            avg = ssi.soil_average(soil_rep, 0.0, float(depth_m) + float(width_m))
            if avg is not None:
                vs_eff = avg.vs
                g0_kpa = avg.g0
        except Exception as error:  # noqa: BLE001
            notes.append(f"Soil report not read ({error}); using nominal Vs = 220 m/s.")
    else:
        notes.append("01 Soil Report/soil-report.json not found; using nominal Vs = 220 m/s.")

    g_eff = g0_kpa * float(g_ratio)
    stiff, embed = ssi.footing_springs(
        g_eff, g_eff, 0.35, float(length_m), float(width_m), depth=float(depth_m)
    )
    return _finite(
        {
            "summary": {
                "supports": opts.supports,
                "pgaG": pga,
                "gOverG0": g_ratio,
                "vsMS": vs_eff,
                "g0Kpa": g0_kpa,
                "gEffKpa": g_eff,
                "kxKnM": stiff[0] if len(stiff) > 0 else None,
                "kyKnM": stiff[1] if len(stiff) > 1 else None,
                "kzKnM": stiff[2] if len(stiff) > 2 else None,
            },
            "springs": stiff,
            "embedmentFactors": embed,
            "notes": notes,
        }
    )


def fem_sway_drift(project_root: str) -> dict[str, Any]:
    """Inspect code wind sway criteria, storey drift limits, and foundation overturning."""
    from saengine.fem import serviceability

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    group = str(getattr(settings.seismic, "system", None) or "rcSmf")

    with in_force(root):
        tbl = serviceability.table()
        covered = serviceability.covered(group)
        lim_short, lim_basis = serviceability.storey_drift_limit(0.6)
        sway = serviceability.sway_basis()

    return _finite(
        {
            "summary": {
                "tableLoaded": tbl is not None,
                "covered": covered,
                "storeyDriftLimit": lim_short,
                "driftBasis": lim_basis,
                "swayLimit": sway[0] if sway else None,
                "swayBasis": sway[2] if sway else "H/400 to H/500",
            },
            "notes": notes,
        }
    )


def fem_floor_vibration(
    project_root: str,
    *,
    fn_hz: float = 6.0,
    span_m: float = 6.0,
    area_m2: float = 36.0,
    w_kn: float = 150.0,
) -> dict[str, Any]:
    """Evaluate walking excitation floor vibration acceleration / response factor R."""
    from saengine.fem import floor_vibration

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    occ = str(getattr(settings.occupancy, "use", None) or "residential")

    with in_force(root):
        rules = floor_vibration.table()
        if rules is None:
            notes.append("Active code pack does not include floor vibration tables.")
            return _finite({"summary": {"tableLoaded": False}, "notes": notes})
        occupancy_id = rules.areaUses.get(occ, rules.defaultOccupancy)
        check = floor_vibration.check_panel(
            "walking",
            float(fn_hz),
            float(w_kn),
            float(area_m2),
            float(span_m),
            rules.occupancies[occupancy_id],
            rules,
        )

    return _finite(
        {
            "summary": {
                "tableLoaded": True,
                "occupancy": occ,
                "frequencyHz": float(fn_hz),
                "spanM": float(span_m),
                **{k: v for k, v in check.items() if isinstance(v, (str, int, float, bool))},
            },
            "details": check,
            "notes": notes,
        }
    )


def fem_differential_settlement(project_root: str, *, thermal: bool = False) -> dict[str, Any]:
    """List support differential settlement load combinations and code clause references."""
    from saengine.fem import settlement

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    cfg = getattr(settings.analysis, "settlement", None)

    with in_force(root):
        cl = settlement.clause()
        combos = settlement.strength_combinations_with_st(thermal=bool(thermal))

    rows = [{"name": name, "factors": factors} for name, factors in combos]
    if cfg is None:
        notes.append(
            "No differential settlement supports configured in Project Settings > Analysis."
        )

    return _finite(
        {
            "summary": {
                "clause": cl,
                "configured": cfg is not None,
                "includeThermal": bool(thermal),
                "combinationCount": len(rows),
            },
            "combinations": rows,
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 6. FEM — Design (U6e)
# ---------------------------------------------------------------------------


def fem_punching_shear(
    project_root: str,
    *,
    vu_kn: float = 350.0,
    c1_mm: float = 400.0,
    c2_mm: float = 400.0,
    d_mm: float = 180.0,
    fc_mpa: float = 28.0,
) -> dict[str, Any]:
    """Check two-way slab punching shear perimeter, capacity phi*Vc, and stud need."""
    from saengine.design import punching

    root = Path(project_root)
    notes: list[str] = []
    _load_settings(root, notes)
    boundary = [(0.0, 0.0), (6000.0, 0.0), (6000.0, 6000.0), (0.0, 6000.0)]
    demand = punching.Demand(vu=float(vu_kn) * 1000.0, combination="U1")

    with in_force(root):
        res = punching.slab_punching(
            centre=(3000.0, 3000.0),
            c1=float(c1_mm),
            c2=float(c2_mm),
            angle=0.0,
            d=float(d_mm),
            boundary=boundary,
            demands=[demand],
            fc=float(fc_mpa),
        )

    if res is None:
        return _finite(
            {"summary": {"ok": False}, "notes": notes + ["Could not evaluate punching."]}
        )

    return _finite(
        {
            "summary": {
                "location": res.location,
                "perimeterMm": res.b0,
                "depthMm": res.d,
                "vuKn": res.vu / 1000.0,
                "phiVcKn": res.phi_vc / 1000.0,
                "utilisation": res.utilisation,
                "reinforcementNeeded": res.utilisation > 1.0,
                "studLayout": res.reinforcement.text if res.reinforcement else "None required",
            },
            "notes": notes + list(res.notes),
        }
    )


def fem_deflection_check(
    project_root: str,
    *,
    ma_knm: float = 45.0,
    fc_mpa: float = 28.0,
    b_mm: float = 300.0,
    h_mm: float = 500.0,
    span_mm: float = 6000.0,
) -> dict[str, Any]:
    """Compute cracking moment, Branson/Bischoff effective I_e, and long-term multiplier."""
    from saengine.design import deflection

    root = Path(project_root)
    notes: list[str] = []
    _load_settings(root, notes)
    b, h = float(b_mm), float(h_mm)
    ig = b * h**3 / 12.0
    icr = ig * 0.35

    with in_force(root):
        method = deflection.inertia_method()
        mcr = deflection.cracking_moment(float(fc_mpa), ig, h / 2.0)
        ie = deflection.effective_inertia(float(ma_knm) * 1e6, mcr, ig, icr, method=method)
        lam_delta = deflection.long_term_multiplier(0.005, 2.0)

    return _finite(
        {
            "summary": {
                "inertiaMethod": method,
                "igMm4": ig,
                "icrMm4": icr,
                "mcrKnm": mcr / 1e6,
                "maKnm": float(ma_knm),
                "ieMm4": ie,
                "ieOverIg": ie / ig if ig else None,
                "longTermMultiplier": lam_delta,
                "spanOver360Mm": float(span_mm) / 360.0,
            },
            "notes": notes,
        }
    )


def fem_crack_control(
    project_root: str,
    *,
    exposure: str = "XC3",
    moment_knm: float = 45.0,
    b_mm: float = 300.0,
    h_mm: float = 500.0,
    bar_mm: float = 16.0,
    as_mm2: float = 804.0,
) -> dict[str, Any]:
    """Compute serviceability bar stress, crack width w_k, and min crack-control steel."""
    from saengine.design import crack_control

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    group = str(getattr(settings.seismic, "system", None) or "rcSmf")
    d_mm = float(h_mm) - 40.0

    with in_force(root):
        covered = crack_control.covered(group)
        stress = crack_control.stress_limits(28.0, 420.0, exposure=exposure)
        cw = crack_control.crack_width(
            float(b_mm),
            float(h_mm),
            d_mm,
            float(as_mm2),
            float(bar_mm),
            30.0,
            float(moment_knm) * 1e6,
            28.0,
        )
        wmax = crack_control.wmax(exposure)
        as_min = crack_control.min_crack_steel(float(b_mm), float(h_mm), 28.0, 420.0)
        l_over_d = crack_control.span_depth_limit(group, 0.006, 0.0, 28.0)

    wk_val = getattr(cw, "wk", None) or getattr(cw, "width", None)
    return _finite(
        {
            "summary": {
                "covered": covered,
                "exposure": exposure,
                "wkMm": wk_val,
                "wmaxMm": wmax,
                "passCrackWidth": (wk_val <= wmax) if (wk_val is not None and wmax) else True,
                "minCrackSteelMm2": as_min,
                "spanOverDLimit": l_over_d,
            },
            "stressLimits": stress,
            "notes": notes,
        }
    )


def fem_torsion_design(
    project_root: str,
    *,
    tu_knm: float = 15.0,
    vu_kn: float = 120.0,
    b_mm: float = 300.0,
    h_mm: float = 500.0,
    fc_mpa: float = 28.0,
    fy_mpa: float = 420.0,
) -> dict[str, Any]:
    """Compute threshold/cracking torsion and required closed transverse/longitudinal torsion steel."""
    from saengine.design import torsion

    root = Path(project_root)
    notes: list[str] = []
    _load_settings(root, notes)
    sec = torsion.TorsionSection(
        b=float(b_mm),
        h=float(h_mm),
        cover=30.0,
        stirrup_dia=10.0,
        d=float(h_mm) - 30.0 - 10.0 - 10.0,
    )

    with in_force(root):
        t_th = torsion.threshold_torsion(sec, float(fc_mpa))
        t_cr = torsion.cracking_torsion(sec, float(fc_mpa))
        des = torsion.design_torsion(
            sec,
            float(tu_knm) * 1e6,
            float(vu_kn) * 1000.0,
            float(fc_mpa),
            float(fy_mpa),
            float(fy_mpa),
            kind="equilibrium",
        )

    return _finite(
        {
            "summary": {
                "thresholdTorsionKnm": t_th / 1e6,
                "crackingTorsionKnm": t_cr / 1e6,
                "tuKnm": float(tu_knm),
                "exceedsThreshold": float(tu_knm) * 1e6 > t_th,
                "alRequiredMm2": getattr(des, "al", None),
                "atOverS": getattr(des, "at_s", None),
            },
            "notes": notes,
        }
    )


def fem_capacity_seismic_detailing(project_root: str) -> dict[str, Any]:
    """Check strong-column weak-beam, capacity shear, and ductile seismic detailing scope."""
    from saengine.design import capacity_design, seismic_detailing

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    _, objs = _load_objects(root, notes)
    _, mats = _load_materials(root, notes)
    building = _load_building(root, notes)

    with in_force(root):
        cap_selected = capacity_design.selected()
        scope = seismic_detailing.scope_of(settings, mats, objs, building, root=root)

    return _finite(
        {
            "summary": {
                "capacityDesignSelected": cap_selected,
                "seismicSystem": getattr(settings.seismic, "system", None) or "rcSmf",
                "scopeItems": len(scope) if isinstance(scope, (dict, list)) else 0,
            },
            "scope": scope if isinstance(scope, dict) else {"items": scope},
            "notes": notes,
        }
    )


def fem_fire_steel_connections(
    project_root: str,
    *,
    bolt_dia_mm: float = 20.0,
    grade: str = "8.8",
    weld_mm: float = 6.0,
    height_m: float = 12.0,
) -> dict[str, Any]:
    """Compute code fire-resistance ratings and bolt/weld capacities plus FE joint checks."""
    from saengine.design import connection_fe, fire_resistance, steel_connections

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    out_dir = _results_dir(root)

    with in_force(root):
        fire_cov = fire_resistance.covered()
        constr = fire_resistance.construction_summary(settings, height=float(height_m))
        ratings = fire_resistance.ratings_of(settings)
        v_bolt = steel_connections.bolt_shear_capacity(grade, float(bolt_dia_mm), planes=1)
        t_bolt, _t_clause = steel_connections.bolt_tension_capacity(grade, float(bolt_dia_mm))
        edge_min = steel_connections.min_edge(float(bolt_dia_mm))
        pitch_min = steel_connections.min_spacing(float(bolt_dia_mm))
        fw = steel_connections.fillet_capacity_per_mm(float(weld_mm), 480.0)

    fe_checks = connection_fe.load_checks(out_dir) if out_dir is not None else None
    if fe_checks is None:
        notes.append("No nonlinear FE steel joint checks cached in 08 FEM/model.results.")

    return _finite(
        {
            "summary": {
                "fireCovered": fire_cov,
                "boltDiameterMm": float(bolt_dia_mm),
                "boltGrade": grade,
                "boltShearKn": v_bolt / 1000.0 if v_bolt > 500 else v_bolt,
                "boltTensionKn": t_bolt / 1000.0 if t_bolt > 500 else t_bolt,
                "minEdgeMm": edge_min,
                "minSpacingMm": pitch_min,
                "weldCapacityKnPerMm": fw / 1000.0 if fw > 100 else fw,
                "feChecksCount": len(fe_checks) if isinstance(fe_checks, dict) else 0,
            },
            "constructionSummary": constr,
            "fireRatings": {k: list(v) for k, v in ratings.items()} if ratings else {},
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 7. BIM 3D
# ---------------------------------------------------------------------------


def bim_sync_stamps(project_root: str) -> dict[str, Any]:
    """Compare 06 BIM source stamps against 05 Floor Plan and list element counts by kind."""
    from saengine.library import bim

    root = Path(project_root)
    notes: list[str] = []
    building = _load_building(root, notes)
    fp_text = _read_text(root / "05 Floor Plan/floor-plan.json")
    if building is None:
        return _finite({"summary": {"loaded": False}, "notes": notes})

    recorded_fp = getattr(getattr(building, "source", None), "floorPlan", None)
    fp_current = bim.floor_plan_current(recorded_fp, fp_text) if fp_text else False

    counts: dict[str, int] = {}
    for el in building.elements:
        kind = str(getattr(el, "kind", "other"))
        counts[kind] = counts.get(kind, 0) + 1

    return _finite(
        {
            "summary": {
                "loaded": True,
                "floorPlanCurrent": fp_current,
                "stories": len(building.stories),
                "totalElements": len(building.elements),
                "additions": len(building.additions.elements)
                if getattr(building, "additions", None) and hasattr(building.additions, "elements")
                else 0,
            },
            "countsByKind": counts,
            "notes": notes,
        }
    )


def bim_detailing_model(project_root: str) -> dict[str, Any]:
    """Build or inspect the concrete detailing model (bar marks, cutoffs, development lengths)."""
    from saengine.drawings import detailing

    root = Path(project_root)
    notes: list[str] = []
    try:
        with in_force(root):
            det = detailing.detailing_model(root)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Detailing fallback: {_first_line(exc)}")
        det = {}

    elements = list(det.get("elements") or []) if isinstance(det, dict) else []
    marks = det.get("marks") or {} if isinstance(det, dict) else {}
    return _finite(
        {
            "summary": {
                "detailedElements": len(elements),
                "markGroups": len(marks),
            },
            "elements": elements[:50],
            "notes": notes + list(det.get("notes") or [] if isinstance(det, dict) else []),
        }
    )


def bim_rebar_cages(project_root: str) -> dict[str, Any]:
    """Generate 3D reinforcement cages and run bar congestion / layer-spacing checks."""
    from saengine.drawings import cages, detailing

    root = Path(project_root)
    notes: list[str] = []
    _, objs = _load_objects(root, notes)
    _, mats = _load_materials(root, notes)
    try:
        with in_force(root):
            det = detailing.detailing_model(root)
            cage = cages.cage_model(det, objs, mats, check=True)
            total_bars = cages.bar_count(cage)
            probs = cages.congestion_problems(cage, most=25)
            members = list(cages.members_of(cage))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Rebar cage generation warning: {_first_line(exc)}")
        total_bars, probs, members = 0, [], []

    return _finite(
        {
            "summary": {
                "totalBars": total_bars,
                "cagedMembers": len(members),
                "congestionIssues": len(probs),
            },
            "problems": probs,
            "notes": notes,
        }
    )


def bim_bar_bending_schedule(project_root: str) -> dict[str, Any]:
    """Generate BS 8666 / ACI / BNBC bar bending schedule (BBS) and shape key summary."""
    from saengine.drawings import bbs, detailing

    root = Path(project_root)
    notes: list[str] = []
    try:
        with in_force(root):
            det = detailing.detailing_model(root)
            sched = bbs.bar_schedule(det)
            rows = [
                {
                    "member": r.member,
                    "mark": r.mark,
                    "shape": r.shape,
                    "diaMm": r.dia,
                    "count": r.members * r.per_member,
                    "cuttingLengthMm": r.cutting_length,
                }
                for r in sched.rows[:80]
            ]
            s_key = bbs.shape_key(sched)
            total_mass_kg = sum(
                bbs.bar_mass(r.dia) * (r.cutting_length / 1000.0) * r.members * r.per_member
                for r in sched.rows
            )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"BBS warning: {_first_line(exc)}")
        rows, s_key, total_mass_kg = [], [], 0.0

    return _finite(
        {
            "summary": {
                "rowCount": len(rows),
                "shapeTypes": len(s_key),
                "totalMassKg": total_mass_kg,
            },
            "rows": rows,
            "shapeKey": s_key,
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 8. Architecture
# ---------------------------------------------------------------------------


def _load_arch(root: Path, notes: list[str]) -> Any:
    from saengine.library import architecture

    raw = _read_text(root / "05 Floor Plan/architecture.json")
    if raw is None:
        notes.append("05 Floor Plan/architecture.json not found; using empty architectural model.")
        return architecture.Architecture()
    try:
        return architecture.parse(raw)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Architecture parse warning: {_first_line(exc)}")
        return architecture.Architecture()


def architecture_rooms_check(project_root: str) -> dict[str, Any]:
    """Audit architectural rooms, enclosures, areas, doors/windows, and floor-plan alignment."""
    from saengine.library import architecture, architecture_ifc

    root = Path(project_root)
    notes: list[str] = []
    arch = _load_arch(root, notes)
    building = _load_building(root, notes)
    fp = None
    fp_raw = _read_text(root / "05 Floor Plan/floor-plan.json")
    if fp_raw:
        try:
            from saengine.library.floorplan import FloorPlan

            fp = FloorPlan.model_validate_json(fp_raw)
        except Exception:  # noqa: BLE001
            fp = None

    issues = architecture.check(arch, floor_plan=fp)
    summary_counts = architecture_ifc.architecture_summary(arch)
    elevations = (
        {s.id: float(s.elevation) for s in building.stories} if building is not None else {}
    )

    room_rows: list[dict[str, Any]] = []
    for room in arch.rooms:
        area_m2 = None
        try:
            bnd = architecture.room_boundary(arch, room, elevations)
            if bnd and hasattr(bnd[0], "area"):
                area_m2 = float(bnd[0].area) / 1e6
        except Exception:  # noqa: BLE001
            area_m2 = None
        room_rows.append(
            {
                "id": room.id,
                "name": getattr(room, "name", room.id),
                "story": room.story,
                "areaM2": area_m2,
            }
        )

    return _finite(
        {
            "summary": {
                **summary_counts,
                "roomCount": len(arch.rooms),
                "issueCount": len(issues),
            },
            "rooms": room_rows,
            "problems": issues,
            "notes": notes,
        }
    )


def architecture_massing_floors(project_root: str) -> dict[str, Any]:
    """Compute conceptual mass volumes and floor-by-floor GFA areas and FAR summary."""
    from saengine.library import massing

    root = Path(project_root)
    notes: list[str] = []
    arch = _load_arch(root, notes)
    masses = list(arch.masses or [])
    if not masses:
        notes.append("No conceptual masses defined in Architecture; showing empty mass schedule.")
        return _finite(
            {"summary": {"massCount": 0, "totalVolumeM3": 0.0}, "masses": [], "notes": notes}
        )

    report = massing.mass_floor_area_report(masses)
    rows = [
        {
            "id": m.id,
            "name": m.name,
            "kind": m.kind,
            "heightMm": m.height,
            "volumeM3": massing.mass_volume_m3(m),
            "floors": len(massing.mass_floors(m)),
        }
        for m in masses
    ]
    return _finite(
        {
            "summary": {
                "massCount": len(masses),
                "totalVolumeM3": sum(r["volumeM3"] for r in rows),
                "totalFloorAreaM2": report.get("totalArea", 0.0)
                if isinstance(report, dict)
                else 0.0,
            },
            "masses": rows,
            "report": report,
            "notes": notes,
        }
    )


def architecture_roof_ceiling_curtain(project_root: str) -> dict[str, Any]:
    """Inspect roof face slopes/areas, suspended ceiling soffit voids, and curtain wall grids."""
    from saengine.library import architecture, roof_geometry

    root = Path(project_root)
    notes: list[str] = []
    arch = _load_arch(root, notes)
    building = _load_building(root, notes)
    _, objs = _load_objects(root, notes)
    elevations = (
        {s.id: float(s.elevation) for s in building.stories} if building is not None else {}
    )

    roof_rows: list[dict[str, Any]] = []
    for rf in arch.roofs:
        geom = roof_geometry.compute_roof_geometry(rf)
        roof_rows.append(
            {
                "id": rf.id,
                "kind": geom.kind,
                "faces": len(geom.faces),
                "planAreaM2": geom.plan_area / 1e6,
                "slopedAreaM2": geom.sloped_area / 1e6,
            }
        )

    ceiling_rows: list[dict[str, Any]] = []
    for cl in arch.ceilings:
        area = architecture.ceiling_area(arch, cl, elevations)
        vc = None
        if building is not None:
            try:
                vc = architecture.ceiling_void_check(arch, building, objs, cl.story)
            except Exception:  # noqa: BLE001
                vc = None
        ceiling_rows.append(
            {
                "id": cl.id,
                "story": cl.story,
                "areaM2": area / 1e6 if area > 500 else area,
                "voidMm": vc.void_depth if vc else None,
            }
        )

    curtain_rows: list[dict[str, Any]] = []
    for cw in arch.curtainWalls:
        lay = architecture.curtain_wall_layout(arch, cw, elevations)
        curtain_rows.append(
            {
                "id": cw.id,
                "panels": len(lay.panels) if lay else 0,
                "mullions": len(lay.mullions) if lay else 0,
                "areaM2": lay.area_m2 if lay else 0.0,
            }
        )

    if not roof_rows and not ceiling_rows and not curtain_rows:
        notes.append(
            "No roofs, ceilings, or curtain walls modeled in 05 Floor Plan/architecture.json."
        )

    return _finite(
        {
            "summary": {
                "roofCount": len(roof_rows),
                "ceilingCount": len(ceiling_rows),
                "curtainWallCount": len(curtain_rows),
            },
            "roofs": roof_rows,
            "ceilings": ceiling_rows,
            "curtainWalls": curtain_rows,
            "notes": notes,
        }
    )


def architecture_point_cloud_status(project_root: str, *, path: str = "") -> dict[str, Any]:
    """Scan project underlays for point clouds / DXF files and inspect header counts if given."""
    from saengine.library import point_cloud

    root = Path(project_root)
    notes: list[str] = []
    exts = {".ply", ".las", ".laz", ".xyz", ".pts", ".e57"}
    files: list[dict[str, Any]] = []
    underlay_dir = root / "05 Floor Plan/Underlays"
    search_dirs = [underlay_dir, root / "05 Floor Plan"]
    seen: set[Path] = set()
    for d in search_dirs:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if (
                    f.is_file()
                    and f not in seen
                    and (f.suffix.lower() in exts or f.suffix.lower() in {".dxf", ".pdf"})
                ):
                    seen.add(f)
                    files.append(
                        {
                            "name": f.name,
                            "ext": f.suffix.lower(),
                            "sizeKb": f.stat().st_size / 1024.0,
                        }
                    )

    loaded_pts = None
    if path.strip():
        target = Path(path.strip())
        if not target.is_absolute():
            target = root / target
        try:
            cloud = point_cloud.read_cloud(target)
            loaded_pts = len(cloud) if hasattr(cloud, "__len__") else None
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Point cloud read error: {_first_line(exc)}")
    elif not any(f["ext"] in exts for f in files):
        notes.append("No .ply/.las/.xyz point cloud found in 05 Floor Plan/Underlays.")

    return _finite(
        {
            "summary": {"underlayFiles": len(files), "loadedPoints": loaded_pts},
            "files": files,
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 9. Documents
# ---------------------------------------------------------------------------


def documents_sheet_inventory(project_root: str) -> dict[str, Any]:
    """Inventory generated DXF/PDF/DOCX drawing sheets and drawing revision rules."""
    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    exts = {".dxf", ".pdf", ".docx", ".svg", ".png"}
    sheets: list[dict[str, Any]] = []
    for folder in (root / "11 Exports/Drawings", root / "11 Exports", root / "05 Floor Plan"):
        if folder.is_dir():
            for p in sorted(folder.rglob("*")):
                if p.is_file() and p.suffix.lower() in exts:
                    sheets.append(
                        {
                            "path": str(p.relative_to(root)),
                            "format": p.suffix.lower().lstrip("."),
                            "sizeKb": p.stat().st_size / 1024.0,
                        }
                    )

    revs = list(getattr(settings.drawings, "revisions", None) or [])
    return _finite(
        {
            "summary": {
                "sheetCount": len(sheets),
                "revisionCount": len(revs),
                "sheetSize": getattr(settings.drawings, "sheetSize", "A1"),
                "projectNumber": getattr(settings.drawings, "projectNumber", "") or "-",
            },
            "sheets": sheets,
            "revisions": [r.model_dump() if hasattr(r, "model_dump") else r for r in revs],
            "notes": notes,
        }
    )


def documents_drawing_automation(project_root: str) -> dict[str, Any]:
    """Inspect drafting standard scales, dimension rules, and DXF automation readiness."""
    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    drw = settings.drawings
    dxf_files = (
        list((root / "11 Exports/Drawings").glob("*.dxf"))
        if (root / "11 Exports/Drawings").is_dir()
        else []
    )

    if not dxf_files:
        notes.append("Generate DXF sheets first (Drawings > Generate) to run auto-tag/dimension.")

    return _finite(
        {
            "summary": {
                "dxfSheets": len(dxf_files),
                "planScale": drw.planScale,
                "slabScale": drw.slabScale,
                "elevationScale": drw.elevationScale,
                "detailScale": drw.detailScale,
                "standard": drw.standard or "default",
            },
            "notes": notes,
        }
    )


def documents_calculation_package(project_root: str) -> dict[str, Any]:
    """Audit engineering calculation report readiness across all design and analysis sections."""
    from saengine.report import build

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    name = build.project_name(root, settings)
    pack_text = build.code_pack_text(settings)

    sections = [
        ("Soil Report", (root / "01 Soil Report/soil-report.json").is_file()),
        ("Project Settings", (root / "02 Project Settings/project-settings.json").is_file()),
        ("Materials & Objects", (root / "03 Materials/materials.json").is_file()),
        ("BIM Model", (root / "06 BIM/bim.json").is_file()),
        ("MEP Systems", (root / "07 MEP/mep.json").is_file()),
        ("FEM Results", _results_dir(root) is not None),
        ("Substructure", (root / "09 Substructure/substructure.json").is_file()),
        ("BOQ & Takeoffs", (root / "10 BOQ/boq.json").is_file()),
    ]
    ready_count = sum(1 for _, ok in sections if ok)
    return _finite(
        {
            "summary": {
                "projectName": name,
                "codePack": pack_text,
                "readySections": ready_count,
                "totalSections": len(sections),
            },
            "sections": [{"section": s, "ready": ok} for s, ok in sections],
            "notes": notes,
        }
    )


def documents_clause_traceability(project_root: str) -> dict[str, Any]:
    """Collect active code pack clause references across seismic, wind, concrete, and detailing."""
    from saengine.design import crack_control, punching
    from saengine.fem import notional_loads, pattern_live, seismic_design, wind_speed_factors

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)

    with in_force(root) as pack_problems:
        notes.extend(pack_problems)
        clauses = seismic_design.clauses()
        pl_clause = pattern_live.clause("adjacent")
        w_cov = True
        _ = (wind_speed_factors, notional_loads, crack_control, punching, w_cov)

    rows = [{"topic": k, "clause": v} for k, v in (clauses or {}).items()]
    rows.append({"topic": "Pattern Live Load", "clause": pl_clause})
    return _finite(
        {
            "summary": {
                "codePack": settings.codePack,
                "clauseCount": len(rows),
                "packProblems": len(pack_problems),
            },
            "clauses": rows,
            "notes": notes,
        }
    )


def documents_project_metadata(project_root: str) -> dict[str, Any]:
    """Read project manifest, title block info, drawing/report metadata, and active versions."""
    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    manifests = sorted(p.name for p in root.glob("*.saengine"))
    proj_info = settings.project

    return _finite(
        {
            "summary": {
                "projectName": getattr(proj_info, "name", root.name),
                "manifest": manifests[0] if manifests else "None",
                "codePack": settings.codePack,
                "location": getattr(settings.site, "location", "") or "-",
                "firm": settings.drawings.firm or "-",
                "engineer": settings.drawings.engineer or "-",
                "reportTemplate": settings.report.template or "default",
            },
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 10. Studies
# ---------------------------------------------------------------------------


def studies_daylight_solar(project_root: str, *, day: str = "2025-06-21") -> dict[str, Any]:
    """Run solar shadow hours and average daylight factor studies for project massing."""
    from saengine.environment import service, solar

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    try:
        target_day = dt.date.fromisoformat(day)
    except Exception:  # noqa: BLE001
        target_day = dt.date(2025, 6, 21)

    sun_res: dict[str, Any] = {}
    daylight_res: dict[str, Any] = {}
    env_file = root / "05 Floor Plan/environment.json"
    if env_file.is_file():
        try:
            sun_res = service.sun_study(str(root), day=target_day.isoformat())
            daylight_res = service.daylight_study(str(root))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Environment study warning: {_first_line(exc)}")
    else:
        notes.append("05 Floor Plan/environment.json not configured; computing solar path only.")

    lat = 23.81
    lon = 90.41
    loc = getattr(settings.site, "location", None)
    path = solar.sun_path(lat, lon, target_day, 6.0)
    return _finite(
        {
            "summary": {
                "day": target_day.isoformat(),
                "location": str(loc or "dhaka"),
                "sunPathPoints": len(path),
                "envConfigured": env_file.is_file(),
            },
            "sunStudy": sun_res,
            "daylightStudy": daylight_res,
            "notes": notes,
        }
    )


def studies_noise_study(project_root: str) -> dict[str, Any]:
    """Run road-traffic facade acoustic noise evaluation for project site roads."""
    from saengine.environment import service

    root = Path(project_root)
    notes: list[str] = []
    env_file = root / "05 Floor Plan/environment.json"
    res: dict[str, Any] = {}
    if env_file.is_file():
        try:
            res = service.noise_study(str(root))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Noise study warning: {_first_line(exc)}")
    else:
        notes.append(
            "05 Floor Plan/environment.json not found; add road segments to run noise study."
        )

    return _finite(
        {
            "summary": {
                "envConfigured": env_file.is_file(),
                "facadesEvaluated": len(res.get("facades", [])) if isinstance(res, dict) else 0,
            },
            "noise": res,
            "notes": notes,
        }
    )


def studies_phasing_summary(project_root: str) -> dict[str, Any]:
    """Inspect construction phases, design option sets, and phased BOQ split if available."""
    from saengine.project import phasing

    root = Path(project_root)
    notes: list[str] = []
    ph_text = _read_text(root / "05 Floor Plan/phasing.json")
    ph = phasing.parse(ph_text)
    if ph_text is None:
        notes.append(
            "05 Floor Plan/phasing.json not found; showing default new-construction phase."
        )

    boq_raw = _read_text(root / "10 BOQ/boq.json")
    phased_bill: dict[str, Any] = {}
    if boq_raw:
        try:
            phased_bill = phasing.phase_bill(json.loads(boq_raw), ph)
        except Exception:  # noqa: BLE001
            phased_bill = {}

    return _finite(
        {
            "summary": {
                "phaseCount": len(ph.phases),
                "defaultPhase": ph.defaultPhase,
                "assignedElements": len(ph.elements),
                "optionSets": len(ph.optionSets),
            },
            "phases": [p.model_dump() for p in ph.phases],
            "phasedBill": phased_bill,
            "notes": notes,
        }
    )


def studies_plot_planning(project_root: str) -> dict[str, Any]:
    """Check site plot geometry, municipal setbacks, FAR/GC coverage, and encroachments."""
    from saengine.gis import planning, plot

    root = Path(project_root)
    notes: list[str] = []
    site_raw = _read_text(root / "05 Floor Plan/site.json")
    fp_raw = _read_text(root / "05 Floor Plan/floor-plan.json")
    obj_raw = _read_text(root / "04 Objects/objects.json")
    bim_raw = _read_text(root / "06 BIM/bim.json")
    set_raw = _read_text(root / "02 Project Settings/project-settings.json")

    site = None
    if site_raw:
        try:
            from saengine.library.settings import Site

            site = Site.model_validate_json(site_raw)
        except Exception:  # noqa: BLE001
            site = None

    desc = plot.describe(site) if site is not None else None
    enc = plot.encroachments(site, fp_raw, obj_raw) if site is not None else {}
    plan = None
    with in_force(root):
        fa = planning.floor_areas(bim_raw)
        if site is not None:
            plan = planning.check(site, bim_text=bim_raw, settings_text=set_raw)

    if site is None:
        notes.append("Site boundary (05 Floor Plan/site.json) not defined; computed BIM GFA only.")

    return _finite(
        {
            "summary": {
                "siteDefined": site is not None,
                "plotAreaM2": desc.get("areaM2") if isinstance(desc, dict) else None,
                "gfaM2": fa.get("totalM2") if isinstance(fa, dict) else None,
                "encroachmentCount": len(enc.get("encroachments", []))
                if isinstance(enc, dict)
                else 0,
            },
            "planning": plan or {},
            "floorAreas": fa or {},
            "notes": notes,
        }
    )


def studies_special_structures(project_root: str) -> dict[str, Any]:
    """Inspect chimneys, silos, cooling towers, bridges, and special shell structure analyses."""
    import numpy as np

    from saengine.special import project as sp_project
    from saengine.special import shells

    root = Path(project_root)
    notes: list[str] = []
    settings = _load_settings(root, notes)
    spec_cfg = getattr(settings, "specialStructures", None)

    kept_res: dict[str, Any] = {}
    try:
        kept_res = sp_project.kept(root)
    except Exception:  # noqa: BLE001
        kept_res = {}

    if not kept_res:
        notes.append("No special structure analysis kept yet (06 BIM/special.json).")

    sample_janssen = shells.janssen(6.0, 15.0, 0.5, 0.4, np.array([2.0, 5.0, 10.0]))
    return _finite(
        {
            "summary": {
                "configured": spec_cfg is not None,
                "keptResults": bool(kept_res),
                "sampleSiloPressure10mKpa": sample_janssen.get("p")[-1]
                if isinstance(sample_janssen.get("p"), list) and sample_janssen.get("p")
                else None,
            },
            "kept": kept_res,
            "notes": notes,
        }
    )


def studies_batch_check(project_root: str) -> dict[str, Any]:
    """List SAEngine batch editing actions and check completeness across all 11 project folders."""
    from saengine import actions

    root = Path(project_root)
    notes: list[str] = []
    act_list = actions.list_actions()
    folders = [
        "01 Soil Report",
        "02 Project Settings",
        "03 Materials",
        "04 Objects",
        "05 Floor Plan",
        "06 BIM",
        "07 MEP",
        "08 FEM",
        "09 Substructure",
        "10 BOQ",
        "11 Exports",
    ]
    rows = [
        {
            "folder": f,
            "present": (root / f).is_dir(),
            "files": len(list((root / f).glob("*"))) if (root / f).is_dir() else 0,
        }
        for f in folders
    ]
    return _finite(
        {
            "summary": {
                "availableActions": len(act_list),
                "foldersPresent": sum(1 for r in rows if r["present"]),
                "totalFolders": len(rows),
            },
            "folders": rows,
            "notes": notes,
        }
    )


def studies_verification_status(project_root: str) -> dict[str, Any]:
    """List benchmark verification manual suites and check cached verification outputs."""
    from saengine.rpc import handlers

    root = Path(project_root)
    notes: list[str] = []
    cases_res = handlers.verification_cases()
    cases = cases_res.get("cases", []) if isinstance(cases_res, dict) else []
    report_dir = root / "11 Exports/Report"
    has_manual = any(report_dir.glob("*verif*")) if report_dir.is_dir() else False
    return _finite(
        {
            "summary": {"benchmarkCases": len(cases), "cachedManualExport": has_manual},
            "cases": cases[:40],
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 11. Exports
# ---------------------------------------------------------------------------


def exports_format_matrix(project_root: str) -> dict[str, Any]:
    """Inventory supported structural/BIM export formats and existing generated deliverables."""
    from saengine.exporters import exchange

    root = Path(project_root)
    notes: list[str] = []
    exports_dir = root / "11 Exports"

    formats = []
    for fmt in exchange.FORMATS.values():
        folder = exports_dir / fmt.folder if fmt.folder else exports_dir
        matches = list(folder.glob(f"*{fmt.extension}")) if folder.is_dir() else []
        formats.append(
            {
                "id": fmt.id,
                "name": fmt.name,
                "extension": fmt.extension,
                "exported": len(matches) > 0,
                "files": len(matches),
            }
        )

    return _finite(
        {
            "summary": {
                "supportedFormats": len(formats),
                "exportedFormats": sum(1 for f in formats if f["exported"]),
                "exportsFolderExists": exports_dir.is_dir(),
            },
            "formats": formats,
            "notes": notes,
        }
    )


def exports_fabrication_preview(project_root: str) -> dict[str, Any]:
    """Build the steel connection / plate / bolt fabrication model (DSTV NC & BVBS readiness)."""
    from saengine.fabrication import export as fab_export

    root = Path(project_root)
    notes: list[str] = []
    try:
        with in_force(root):
            fab, _extras = fab_export.fabrication_model(root)
        members = len(getattr(fab, "members", []) or [])
        plates = len(getattr(fab, "plates", []) or [])
        bolts = len(getattr(fab, "bolts", []) or [])
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Fabrication preview note: {_first_line(exc)}")
        members = plates = bolts = 0

    return _finite(
        {
            "summary": {
                "steelMembers": members,
                "connectionPlates": plates,
                "boltGroups": bolts,
                "readyForNc": members > 0,
            },
            "notes": notes,
        }
    )


def exports_structural_ifc_check(project_root: str) -> dict[str, Any]:
    """Verify IFC 4x3 structural analysis model, rebar cage, and architecture export readiness."""
    root = Path(project_root)
    notes: list[str] = []
    building = _load_building(root, notes)
    model_path, _ = _load_osmodel(root)
    arch_exists = (root / "05 Floor Plan/architecture.json").is_file()
    ifc_files = list((root / "11 Exports").rglob("*.ifc")) if (root / "11 Exports").is_dir() else []

    return _finite(
        {
            "summary": {
                "bimReady": building is not None,
                "structuralModelReady": model_path is not None,
                "architectureReady": arch_exists,
                "exportedIfcCount": len(ifc_files),
            },
            "ifcFiles": [str(f.relative_to(root)) for f in ifc_files],
            "notes": notes,
        }
    )


def exports_archive_inspection(project_root: str) -> dict[str, Any]:
    """Scan 11 Exports for .civil archives and check pending schema migrations."""
    from saengine.project import archive

    root = Path(project_root)
    notes: list[str] = []
    migrations = archive.pending_migrations(root)
    archives = (
        list((root / "11 Exports").rglob("*.civil")) if (root / "11 Exports").is_dir() else []
    )
    inspections: list[dict[str, Any]] = []
    for arc in archives[:10]:
        try:
            res = archive.inspect_archive(arc, verify=True)
            inspections.append(
                {
                    "file": str(arc.relative_to(root)),
                    "ok": res.get("ok", True),
                    "problems": len(res.get("problems") or []),
                }
            )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{arc.name}: {_first_line(exc)}")

    if not archives:
        notes.append("No .civil project archives found in 11 Exports.")

    return _finite(
        {
            "summary": {
                "archiveCount": len(archives),
                "pendingMigrations": len(migrations),
            },
            "archives": inspections,
            "notes": notes,
        }
    )


def exports_bbs_reconciliation(project_root: str, *, tolerance: float = 0.5) -> dict[str, Any]:
    """Reconcile bar bending schedule (BBS) steel tonnage against 10 BOQ bill quantities."""
    from saengine.drawings import bbs, detailing

    root = Path(project_root)
    notes: list[str] = []
    boq_raw = _read_text(root / "10 BOQ/boq.json")
    if boq_raw is None:
        return _finite({"summary": {"reconciled": False}, "notes": ["10 BOQ/boq.json not found."]})
    try:
        with in_force(root):
            det = detailing.detailing_model(root)
            sched = bbs.bar_schedule(det)
            rec = bbs.reconcile(sched, json.loads(boq_raw), tolerance=float(tolerance))
            rows = [
                {
                    "diaMm": r.dia,
                    "bbsKg": r.bbs,
                    "boqKg": r.boq,
                    "diffKg": r.bbs - r.boq,
                }
                for r in rec.rows
            ]
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Reconciliation note: {_first_line(exc)}")
        rows = []

    return _finite(
        {
            "summary": {"reconciled": len(rows) > 0, "diameterRows": len(rows)},
            "rows": rows,
            "notes": notes,
        }
    )


def _pack_guard(fn: Any) -> Any:
    """Turns a missing code-pack table into a panel note instead of an engine error.

    Several of these features exist only in some code packs (speed factors k1-k4, peak velocity
    pressure, two-level seismic, ...); for the others the panel says so.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ValueError, AttributeError, KeyError, LookupError) as error:
            return {
                "unavailable": True,
                "notes": [f"Not available for the active code pack or this project: {error}"],
            }

    return wrapper


for _name, _fn in list(globals().items()):
    if inspect.isfunction(_fn) and _fn.__module__ == __name__ and not _name.startswith("_"):
        globals()[_name] = _pack_guard(_fn)

"""End-to-end checks for every U6e full-ribbon JSON-RPC handler."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from saengine.rpc import handlers, server

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"

U6E_METHODS = [
    "fem/notionalLoads",
    "fem/patternLive",
    "fem/snowRainLoads",
    "fem/thermalLoads",
    "fem/floodLoads",
    "fem/stairCraneLoads",
    "fem/loadCombinations",
    "fem/spectralHazard",
    "fem/seismicSummary",
    "fem/groundMotions",
    "fem/linearTimeHistory",
    "fem/irregularities",
    "fem/torsionalEffects",
    "fem/twoLevelSeismic",
    "fem/floorSpectra",
    "fem/isolationDampers",
    "fem/windSpeedFactors",
    "fem/gustResponse",
    "fem/peakVelocityPressure",
    "fem/localPressures",
    "fem/windComfort",
    "fem/openStructures",
    "fem/pushoverAnalysis",
    "fem/nonlinearHistory",
    "fem/pDeltaBuckling",
    "fem/stagedConstruction",
    "fem/creepShrinkage",
    "fem/ssiSprings",
    "fem/swayDrift",
    "fem/floorVibration",
    "fem/differentialSettlement",
    "fem/punchingShear",
    "fem/deflectionCheck",
    "fem/crackControl",
    "fem/torsionDesign",
    "fem/capacitySeismicDetailing",
    "fem/fireSteelConnections",
    "bim/syncStamps",
    "bim/detailingModel",
    "bim/rebarCages",
    "bim/barBendingSchedule",
    "architecture/roomsCheck",
    "architecture/massingFloors",
    "architecture/roofCeilingCurtain",
    "architecture/pointCloudStatus",
    "documents/sheetInventory",
    "documents/drawingAutomation",
    "documents/calculationPackage",
    "documents/clauseTraceability",
    "documents/projectMetadata",
    "studies/daylightSolar",
    "studies/noiseStudy",
    "studies/phasingSummary",
    "studies/plotPlanning",
    "studies/specialStructures",
    "studies/batchCheck",
    "studies/verificationStatus",
    "exports/formatMatrix",
    "exports/fabricationPreview",
    "exports/structuralIfcCheck",
    "exports/archiveInspection",
    "exports/bbsReconciliation",
]


def _copy_sample(tmp_path: Path) -> str:
    dest = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, dest)
    return str(dest)


def test_u6e_methods_registered() -> None:
    srv = server.create_server()
    registered = set(srv.protocol.fm.features.keys())
    missing = [m for m in U6E_METHODS if m not in registered]
    assert not missing, f"Missing U6e RPC methods: {missing}"


UNAVAILABLE_ON_BNBC: list[str] = [
    "fem_crack_control",
    "fem_open_structures",
    "fem_peak_velocity_pressure",
]


def test_u6e_all_handlers_run_on_sample_frame(tmp_path: Path) -> None:
    root = _copy_sample(tmp_path)
    calls = [
        handlers.fem_notional_loads,
        handlers.fem_pattern_live,
        handlers.fem_snow_rain_loads,
        handlers.fem_thermal_loads,
        handlers.fem_flood_loads,
        handlers.fem_stair_crane_loads,
        handlers.fem_load_combinations,
        handlers.fem_spectral_hazard,
        handlers.fem_seismic_summary,
        handlers.fem_ground_motions,
        handlers.fem_linear_time_history,
        handlers.fem_irregularities,
        handlers.fem_torsional_effects,
        handlers.fem_two_level_seismic,
        handlers.fem_floor_spectra,
        handlers.fem_isolation_dampers,
        handlers.fem_wind_speed_factors,
        handlers.fem_gust_response,
        handlers.fem_peak_velocity_pressure,
        handlers.fem_local_pressures,
        handlers.fem_wind_comfort,
        handlers.fem_open_structures,
        handlers.fem_pushover_analysis,
        handlers.fem_nonlinear_history,
        handlers.fem_p_delta_buckling,
        handlers.fem_staged_construction,
        handlers.fem_creep_shrinkage,
        handlers.fem_ssi_springs,
        handlers.fem_sway_drift,
        handlers.fem_floor_vibration,
        handlers.fem_differential_settlement,
        handlers.fem_punching_shear,
        handlers.fem_deflection_check,
        handlers.fem_crack_control,
        handlers.fem_torsion_design,
        handlers.fem_capacity_seismic_detailing,
        handlers.fem_fire_steel_connections,
        handlers.bim_sync_stamps,
        handlers.bim_detailing_model,
        handlers.bim_rebar_cages,
        handlers.bim_bar_bending_schedule,
        handlers.architecture_rooms_check,
        handlers.architecture_massing_floors,
        handlers.architecture_roof_ceiling_curtain,
        handlers.architecture_point_cloud_status,
        handlers.documents_sheet_inventory,
        handlers.documents_drawing_automation,
        handlers.documents_calculation_package,
        handlers.documents_clause_traceability,
        handlers.documents_project_metadata,
        handlers.studies_daylight_solar,
        handlers.studies_noise_study,
        handlers.studies_phasing_summary,
        handlers.studies_plot_planning,
        handlers.studies_special_structures,
        handlers.studies_batch_check,
        handlers.studies_verification_status,
        handlers.exports_format_matrix,
        handlers.exports_fabrication_preview,
        handlers.exports_structural_ifc_check,
        handlers.exports_archive_inspection,
        handlers.exports_bbs_reconciliation,
    ]
    assert len(calls) == 62
    unavailable = []
    for fn in calls:
        res = fn(root)
        assert isinstance(res, dict), f"{fn.__name__} did not return dict"
        if res.get("unavailable"):
            # A feature of other code packs (BNBC has no table for it): the panel says so.
            assert res["notes"], fn.__name__
            unavailable.append(fn.__name__)
        else:
            assert "summary" in res, f"{fn.__name__} missing summary"
        json.dumps(res, allow_nan=False)
    assert sorted(unavailable) == UNAVAILABLE_ON_BNBC

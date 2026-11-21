"""Tests for the thin U3 RPC handlers and their registration on the JSON-RPC server."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from saengine.rpc import handlers
from saengine.rpc.server import create_server

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"

U3_METHODS = (
    "mep/electricalCableSize",
    "mep/electricalLighting",
    "mep/hvacLoadsDetailed",
    "mep/hvacDuctPressure",
    "mep/hvacRouteDucts",
    "mep/fireSprinklers",
    "mep/fireAlarm",
    "mep/plumbingHotWater",
    "mep/plumbingGas",
    "drawings/scopeBoxes",
    "drawings/callout",
    "drawings/keynotes",
    "drawings/legend",
    "drawings/scheduleCategories",
    "drawings/schedule",
    "bim/exportIfcFile",
    "bim/diffIfc",
    "project/validateAll",
    "verification/cases",
    "verification/run",
)


@pytest.fixture()
def sample_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, dest)
    # Add sample architecture rooms and extend existing 07 MEP for full end-to-end coverage.
    lines = [
        ([0, 0], [5000, 0]),
        ([5000, 0], [7000, 0]),
        ([7000, 0], [7000, 4000]),
        ([7000, 4000], [5000, 4000]),
        ([5000, 4000], [0, 4000]),
        ([0, 4000], [0, 0]),
        ([5000, 0], [5000, 4000]),
    ]
    arch = {
        "schema": "saengine.architecture/1",
        "separators": [
            {"id": f"S{k}", "story": "BASE", "start": a, "end": b} for k, (a, b) in enumerate(lines)
        ],
        "rooms": [
            {
                "id": "RM-1",
                "name": "Office",
                "story": "BASE",
                "point": [2500, 2000],
                "occupancy": "office",
            },
            {
                "id": "RM-2",
                "name": "Corridor",
                "story": "BASE",
                "point": [6000, 2000],
                "occupancy": "corridorAbove",
            },
        ],
    }
    (dest / "05 Floor Plan/architecture.json").write_text(
        json.dumps(arch, indent=2), encoding="utf-8"
    )
    mep_path = dest / "07 MEP/mep.json"
    mep = json.loads(mep_path.read_text(encoding="utf-8"))
    mep.setdefault("plumbing", {})["hotWater"] = {"enabled": True, "storageTempC": 60.0}
    mep["gas"] = {
        "fuel": "naturalGas",
        "appliances": [{"id": "G-1", "kind": "domesticCooker", "story": "BASE", "count": 1}],
    }
    mep_path.write_text(json.dumps(mep, indent=2), encoding="utf-8")
    return dest


def test_all_u3_rpc_methods_registered_on_server() -> None:
    server = create_server()
    registered = set(server.protocol.fm.features)
    for method in U3_METHODS:
        assert method in registered, f"missing RPC registration: {method}"


def test_electrical_cable_and_lighting(sample_copy: Path) -> None:
    calc = handlers.electrical_cable_size(
        str(sample_copy),
        mode="calculator",
        design_current_a=24.0,
        length_m=25.0,
        phases=1,
        conductor="Cu",
        insulation="PVC",
        installation_method="C",
    )
    assert not calc["problems"]
    assert calc["result"]["size"] >= 2.5
    json.dumps(calc, allow_nan=False)

    proj = handlers.electrical_cable_size(str(sample_copy), mode="project")
    assert not proj["problems"]
    assert isinstance(proj["circuits"], list)
    assert len(proj["boards"]) >= 1
    assert "shortCircuit" in proj
    json.dumps(proj, allow_nan=False)

    light = handlers.electrical_lighting(str(sample_copy), luminaire_type="ledPanel600")
    assert not light["problems"]
    assert len(light["rooms"]) >= 2
    json.dumps(light, allow_nan=False)


def test_hvac_loads_routing_and_pressure(sample_copy: Path) -> None:
    loads = handlers.hvac_loads_detailed(str(sample_copy), zoning="room")
    assert not loads["problems"]
    assert len(loads["zones"]) >= 1
    assert "envelopeCompliance" in loads
    json.dumps(loads, allow_nan=False)

    routed = handlers.hvac_route_ducts(str(sample_copy), story="BASE", apply_to_mep=True)
    assert not routed["problems"]
    assert len(routed["ducts"]) >= 1
    assert routed["applied"] is True
    json.dumps(routed, allow_nan=False)

    pressure = handlers.hvac_duct_pressure(str(sample_copy), friction_rate=1.0)
    assert not pressure["problems"]
    assert len(pressure["ducts"]) >= 1
    assert pressure["pressure"] is not None
    json.dumps(pressure, allow_nan=False)


def test_fire_and_plumbing_u3(sample_copy: Path) -> None:
    spr = handlers.fire_sprinklers(str(sample_copy), hazard="lightI")
    assert not spr["problems"]
    assert spr["headCount"] > 0
    assert len(spr["pipes"]) > 0
    json.dumps(spr, allow_nan=False)

    alarm = handlers.fire_alarm(str(sample_copy), standby_hours=24.0, alarm_minutes=30.0)
    assert not alarm["problems"]
    assert alarm["battery"]["recommendedAh"] > 0
    assert len(alarm["devices"]) > 0
    json.dumps(alarm, allow_nan=False)

    hw = handlers.plumbing_hot_water(str(sample_copy), supply_temp_c=60.0)
    assert not hw["problems"]
    assert hw["hotWater"] is not None
    json.dumps(hw, allow_nan=False)

    gas = handlers.plumbing_gas(str(sample_copy))
    assert not gas["problems"]
    json.dumps(gas, allow_nan=False)


def test_documents_scope_boxes_callouts_keynotes_legend_and_schedule(sample_copy: Path) -> None:
    boxes = handlers.drawings_scope_boxes(str(sample_copy), write_files=True)
    assert not boxes["problems"]
    assert len(boxes["plans"]) >= 2
    assert all(p["dxf"] and Path(p["dxf"]).is_file() for p in boxes["plans"])

    callout = handlers.drawings_callout(
        str(sample_copy), detail_sheet_number="S-501", write_files=True
    )
    assert not callout["problems"]
    assert callout["callout"]["reference"] == "1 / S-501"
    assert Path(callout["callout"]["detailDxf"]).is_file()

    # Copy one written DXF into 11 Exports/Drawings to exercise keynotes & legend scanning.
    drawings_dir = sample_copy / "11 Exports/Drawings"
    drawings_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(boxes["plans"][0]["dxf"], drawings_dir / "S-101 Scope.dxf")

    kn = handlers.drawings_keynotes(str(sample_copy))
    assert not kn["problems"]
    assert kn["totalCatalogue"] > 0

    leg = handlers.drawings_legend(str(sample_copy))
    assert not leg["problems"]
    assert leg["sheetsScanned"] == 1
    assert len(leg["items"]) > 0

    cats = handlers.drawings_schedule_categories(str(sample_copy))
    assert not cats["problems"]
    beams = next(c for c in cats["categories"] if c["id"] == "beams")
    assert beams["count"] > 0

    sched = handlers.drawings_schedule(
        str(sample_copy),
        {
            "name": "Beam Concrete Schedule",
            "category": "beams",
            "fields": [
                {"key": "id", "title": "Mark"},
                {"key": "story", "title": "Story"},
                {"key": "widthMm", "title": "Width (mm)"},
                {"key": "depthMm", "title": "Depth (mm)"},
                {"key": "areaMm2", "title": "Area (mm2)", "expression": "widthMm * depthMm"},
            ],
            "groupBy": ["story"],
            "totals": ["areaMm2"],
        },
        export_xlsx_path=str(sample_copy / "beam-schedule.xlsx"),
    )
    assert not sched["problems"]
    assert sched["rowCount"] > 0
    assert Path(sched["xlsxPath"]).is_file()


def test_ifc_options_diff_validate_and_verification_cases(sample_copy: Path) -> None:
    ifc1 = handlers.bim_export_ifc_file(
        str(sample_copy),
        schema="IFC4",
        structural_analysis=False,
        include_georeferencing=True,
        crs="BTM",
        out_path=str(sample_copy / "rev1.ifc"),
    )
    assert not ifc1["problems"]
    assert Path(ifc1["path"]).is_file()

    ifc2 = handlers.bim_export_ifc_file(
        str(sample_copy),
        schema="IFC4",
        structural_analysis=False,
        include_georeferencing=True,
        crs="BTM",
        out_path=str(sample_copy / "rev2.ifc"),
    )
    diff = handlers.bim_diff_ifc(ifc1["path"], ifc2["path"])
    assert not diff["problems"]
    assert "counts" in diff
    json.dumps(diff, allow_nan=False)

    val = handlers.project_validate_all(str(sample_copy))
    assert isinstance(val["parts"], list) and len(val["parts"]) >= 1
    json.dumps(val, allow_nan=False)

    cases = handlers.verification_cases()
    assert len(cases["cases"]) > 0

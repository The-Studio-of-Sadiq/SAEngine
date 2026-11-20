"""Connector-based MEP systems, connectivity checks, totals, BCF and IFC ports (Revit-parity R8)."""

from __future__ import annotations

import json
from pathlib import Path

import ifcopenshell
import pytest

from saengine.library.bim import BuildingModel
from saengine.library.defaults import default_material_library, default_object_library
from saengine.library.mep import MepModel, parse
from saengine.mep import bcf
from saengine.mep.systems import analyze_systems, issues_to_bcf, mep_systems_report
from saengine.rpc import handlers

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"


def _ahu_supply_model(*, include_third_branch: bool = True) -> MepModel:
    """AHU1 -> trunk duct (0..12 m) -> 3 branches (at 4 m, 8 m, 12 m) -> 3 diffusers (100, 150, 200 l/s)."""
    ducts = [
        {
            "id": "D_TRUNK",
            "system": "supply",
            "shape": "rect",
            "width": 500,
            "height": 300,
            "story": "L1",
            "path": [[0, 0], [12000, 0]],
        },
        {
            "id": "D_B1",
            "system": "supply",
            "shape": "rect",
            "width": 250,
            "height": 200,
            "story": "L1",
            "path": [[4000, 0], [4000, 3000]],
        },
        {
            "id": "D_B2",
            "system": "supply",
            "shape": "rect",
            "width": 250,
            "height": 200,
            "story": "L1",
            "path": [[8000, 0], [8000, 3000]],
        },
    ]
    if include_third_branch:
        ducts.append(
            {
                "id": "D_B3",
                "system": "supply",
                "shape": "rect",
                "width": 500,
                "height": 300,
                "story": "L1",
                "path": [[12000, 0], [12000, 3000]],
            }
        )
    return MepModel.model_validate(
        {
            "schema": "saengine.mep/1",
            "hvac": {
                "system": "chilledWater",
                "plant": [
                    {
                        "id": "AHU1",
                        "kind": "ahu",
                        "story": "L1",
                        "x": 0,
                        "y": 0,
                        "length": 1500,
                        "width": 1000,
                    }
                ],
                "ducts": ducts,
                "terminals": [
                    {
                        "id": "AT1",
                        "kind": "supplyDiffuser",
                        "system": "supply",
                        "story": "L1",
                        "x": 4000,
                        "y": 3000,
                        "width": 250,
                        "height": 200,
                        "flow": 100,
                    },
                    {
                        "id": "AT2",
                        "kind": "supplyDiffuser",
                        "system": "supply",
                        "story": "L1",
                        "x": 8000,
                        "y": 3000,
                        "width": 250,
                        "height": 200,
                        "flow": 150,
                    },
                    {
                        "id": "AT3",
                        "kind": "supplyDiffuser",
                        "system": "supply",
                        "story": "L1",
                        "x": 12000,
                        "y": 3000,
                        "width": 500,
                        "height": 300,
                        "flow": 200,
                    },
                ],
            },
        }
    )


def test_ahu_trunk_branches_diffusers_total_and_critical_path() -> None:
    res = analyze_systems(_ahu_supply_model(include_third_branch=True))
    assert len(res["systems"]) == 1
    sys = res["systems"][0]
    assert sys["classification"] == "supplyAir"
    assert sys["sources"] == ["AHU1"]
    assert sys["airFlowLps"] == pytest.approx(450.0)
    # Critical path: 12.0 m along D_TRUNK + 3.0 m along D_B3 = 15.0 m.
    assert sys["criticalPathLength"] == pytest.approx(15.0)
    assert sys["criticalPath"] == ["AHU1", "D_TRUNK", "D_B3", "AT3"]
    assert res["summary"]["openConnectors"] == 0
    assert res["issues"] == []


def test_disconnecting_branch_updates_total_and_reports_unconnected_diffuser() -> None:
    res = analyze_systems(_ahu_supply_model(include_third_branch=False))
    assert len(res["systems"]) == 1
    sys = res["systems"][0]
    assert sys["airFlowLps"] == pytest.approx(250.0)
    assert "AT3" in res["unassigned"]
    kinds = {(i["kind"], tuple(i["elements"])) for i in res["issues"]}
    assert ("openConnector", ("AT3",)) in kinds
    assert ("unassignedElement", ("AT3",)) in kinds
    assert ("openConnector", ("D_TRUNK",)) in kinds


def test_pipe_size_mismatch_50_to_40_flagged() -> None:
    mep = MepModel.model_validate(
        {
            "schema": "saengine.mep/1",
            "plumbing": {
                "tanks": [
                    {
                        "id": "T1",
                        "kind": "overhead",
                        "story": "L1",
                        "x": 0,
                        "y": 0,
                        "length": 1000,
                        "width": 1000,
                        "waterDepth": 1000,
                    }
                ],
                "pipes": [
                    {
                        "id": "P50",
                        "system": "coldWater",
                        "story": "L1",
                        "path": [[0, 0], [3000, 0]],
                        "diameter": 50,
                        "flow": 2.0,
                    },
                    {
                        "id": "P40",
                        "system": "coldWater",
                        "story": "L1",
                        "path": [[3000, 0], [6000, 0]],
                        "diameter": 40,
                        "flow": 2.0,
                    },
                ],
            },
        }
    )
    res = analyze_systems(mep)
    mismatches = [i for i in res["issues"] if i["kind"] == "sizeMismatch"]
    assert len(mismatches) == 1
    assert mismatches[0]["elements"] == ["P50", "P40"]
    assert "50 mm vs 40 mm" in mismatches[0]["message"]
    assert mismatches[0]["point"][:2] == [3000.0, 0.0]


def test_mixed_classification_and_flow_direction_conflict_flagged() -> None:
    mep = MepModel.model_validate(
        {
            "schema": "saengine.mep/1",
            "hvac": {
                "plant": [
                    {
                        "id": "AHU1",
                        "kind": "ahu",
                        "story": "L1",
                        "x": 0,
                        "y": 0,
                        "length": 1000,
                        "width": 1000,
                    }
                ],
                "ducts": [
                    {
                        "id": "D_SUP",
                        "system": "supply",
                        "shape": "rect",
                        "width": 300,
                        "height": 200,
                        "story": "L1",
                        "path": [[0, 0], [4000, 0]],
                    },
                    {
                        "id": "D_RET",
                        "system": "return",
                        "shape": "rect",
                        "width": 300,
                        "height": 200,
                        "story": "L1",
                        "path": [[4000, 0], [8000, 0]],
                    },
                ],
                "terminals": [
                    {
                        "id": "AT_A",
                        "kind": "supplyDiffuser",
                        "system": "supply",
                        "story": "L1",
                        "x": 10000,
                        "y": 0,
                        "connectors": [
                            {
                                "id": "C1",
                                "domain": "duct",
                                "shape": "rect",
                                "width": 200,
                                "height": 200,
                                "direction": "in",
                                "classification": "supplyAir",
                            }
                        ],
                    },
                    {
                        "id": "AT_B",
                        "kind": "supplyDiffuser",
                        "system": "supply",
                        "story": "L1",
                        "x": 10000,
                        "y": 0,
                        "connectors": [
                            {
                                "id": "C1",
                                "domain": "duct",
                                "shape": "rect",
                                "width": 200,
                                "height": 200,
                                "direction": "in",
                                "classification": "supplyAir",
                            }
                        ],
                    },
                ],
            },
        }
    )
    res = analyze_systems(mep)
    mixed = [i for i in res["issues"] if i["kind"] == "mixedClassification"]
    conflicts = [i for i in res["issues"] if i["kind"] == "flowDirectionConflict"]
    assert len(mixed) == 1
    assert set(mixed[0]["elements"]) == {"D_SUP", "D_RET"}
    assert len(conflicts) == 1
    assert set(conflicts[0]["elements"]) == {"AT_A", "AT_B"}


def test_legacy_mep_json_without_connectors_loads_and_derives() -> None:
    legacy_text = (SAMPLE / "07 MEP" / "mep.json").read_text(encoding="utf-8")
    raw = json.loads(legacy_text)
    assert "connectors" not in legacy_text
    mep = parse(legacy_text)
    assert raw["schema"] == "saengine.mep/1"
    res = analyze_systems(mep)
    assert res["summary"]["elements"] > 0
    assert res["summary"]["connectors"] > 0
    assert all(c["derived"] is True for c in res["connectors"])
    assert res["summary"]["systems"] >= 1


def test_plumbing_fixture_units_electrical_load_and_bcf_export(tmp_path: Path) -> None:
    mep = MepModel.model_validate(
        {
            "schema": "saengine.mep/1",
            "plumbing": {
                "stories": [
                    {"story": "L1", "occupancy": "office", "fixtures": {"wc": 4, "basin": 4}}
                ],
                "tanks": [
                    {
                        "id": "OHT1",
                        "kind": "overhead",
                        "story": "ROOF",
                        "x": 0,
                        "y": 0,
                        "length": 1500,
                        "width": 1500,
                        "waterDepth": 1200,
                    }
                ],
                "risers": [
                    {
                        "id": "CWR1",
                        "system": "coldWater",
                        "x": 0,
                        "y": 0,
                        "fromStory": "L1",
                        "toStory": "ROOF",
                        "diameter": 50,
                    }
                ],
            },
            "electrical": {
                "equipment": [
                    {
                        "id": "DB1",
                        "kind": "distributionBoard",
                        "story": "L1",
                        "x": 5000,
                        "y": 0,
                        "length": 600,
                        "width": 400,
                    }
                ],
                "motors": [
                    {
                        "id": "M1",
                        "kind": "pump",
                        "power": 5.5,
                        "count": 2,
                        "story": "L1",
                        "x": 5000,
                        "y": 0,
                    }
                ],
            },
        }
    )
    building = BuildingModel.model_validate(
        {
            "schema": "saengine.bim/2",
            "stories": [
                {"id": "L1", "name": "Level 1", "elevation": 3000},
                {"id": "ROOF", "name": "Roof", "elevation": 6000},
            ],
            "elements": [],
        }
    )
    res = analyze_systems(mep, building)
    cold = next(s for s in res["systems"] if s["classification"] == "domesticColdWater")
    pwr = next(s for s in res["systems"] if s["classification"] == "power")
    assert cold["fixtureUnits"] > 0
    assert cold["waterFlowLps"] > 0
    assert pwr["electricalLoadKw"] == pytest.approx(11.0)

    # Export connectivity warnings to BCF 3.0 and read back.
    bcf_bytes = issues_to_bcf(res)
    topics = bcf.read_bcf(bcf_bytes)
    assert len(topics) == len(res["issues"])
    assert len(topics) >= 1

    # RPC handler round-trip on project directory.
    (tmp_path / "07 MEP").mkdir()
    (tmp_path / "06 BIM").mkdir()
    (tmp_path / "07 MEP" / "mep.json").write_text(
        mep.model_dump_json(by_alias=True), encoding="utf-8"
    )
    (tmp_path / "06 BIM" / "bim.json").write_text(
        building.model_dump_json(by_alias=True), encoding="utf-8"
    )
    rpc_res = handlers.mep_systems(str(tmp_path))
    assert len(rpc_res["systems"]) == len(res["systems"])
    assert mep_systems_report(tmp_path)["summary"] == res["summary"]


def test_ifc_export_writes_distribution_systems_and_ports(tmp_path: Path) -> None:
    from saengine.library.ifc import export_ifc

    mep = _ahu_supply_model(include_third_branch=True)
    building = BuildingModel.model_validate(
        {
            "schema": "saengine.bim/2",
            "stories": [
                {"id": "L1", "name": "Level 1", "elevation": 3000},
                {"id": "ROOF", "name": "Roof", "elevation": 6000},
            ],
            "elements": [],
        }
    )
    ifc_file, ids, _ = export_ifc(
        building, default_object_library(), default_material_library(), "SystemsTest", mep=mep
    )
    path = tmp_path / "systems.ifc"
    ifc_file.write(str(path))
    reopened = ifcopenshell.open(str(path))

    systems = reopened.by_type("IfcDistributionSystem")
    ports = reopened.by_type("IfcDistributionPort")
    rels = reopened.by_type("IfcRelConnectsPorts")
    assert len(systems) == 1
    assert systems[0].PredefinedType == "AIRCONDITIONING"
    assert len(ports) >= 14  # 7 connections * 2 ports
    assert len(rels) >= 7
    connected_ports = {(r.RelatingPort.Name, r.RelatedPort.Name) for r in rels}
    assert ("AHU1:C1", "D_TRUNK:start") in connected_ports
    assert ("D_B1:end", "AT1:C1") in connected_ports
    assert ("D_B2:end", "AT2:C1") in connected_ports
    assert ("D_B3:end", "AT3:C1") in connected_ports
    assert {"AHU1", "D_TRUNK", "D_B1", "D_B2", "D_B3", "AT1", "AT2", "AT3"} <= set(ids)

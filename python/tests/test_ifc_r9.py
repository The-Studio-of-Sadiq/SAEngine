"""Revit-parity R9 IFC interoperability tests:
1. IFC2x3 export (structure, MEP, architecture, rebar, schema validation).
2. Structural analysis view (IfcStructuralAnalysisModel, members, supports, load groups, physical links).
3. Georeferencing (IfcMapConversion / IfcProjectedCRS in IFC4, ePSet_MapConversion in IFC2X3, BTM & UTM).
4. Steel connections in IFC (IfcPlate, IfcMechanicalFastener/IfcFastener, IfcOpeningElement voids, IfcElementAssembly).
5. IFC model diff (GlobalId matching, self-diff empty, 100 mm moved beam, JSON + colour summary, project/diff.py).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.geolocation as gl
import ifcopenshell.validate
import pytest
from test_exchange_exports import two_bay_frame

from saengine.gis.crs import wgs84_to_btm, wgs84_to_utm
from saengine.library import (
    BuildingModel,
    FloorPlan,
    ObjectLibrary,
    default_floor_plan,
    default_material_library,
)
from saengine.library.architecture import Architecture
from saengine.library.bim import generate
from saengine.library.ifc import export_ifc, global_id
from saengine.library.ifc_diff import diff_ifc
from saengine.library.mep import MepModel
from saengine.library.soil import SoilReport
from saengine.project.diff import diff_file

# ───────────────────────────── shared fixtures ─────────────────────────────


def _validate_clean(ifc_file: ifcopenshell.file) -> None:
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(ifc_file, logger)
    errors = [s for s in logger.statements if s.get("level") == "error"]
    assert errors == [], errors


def _two_bay_objects() -> ObjectLibrary:
    return ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "COL",
                    "name": "Column 300x400",
                    "kind": "column",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 400},
                },
                {
                    "id": "BEAM",
                    "name": "Beam 300x500",
                    "kind": "beam",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
                },
                {
                    "id": "SLAB",
                    "name": "Slab 150",
                    "kind": "slab",
                    "material": "C24.1",
                    "thickness": 150,
                },
            ]
        }
    )


def _two_bay_plan() -> FloorPlan:
    return FloorPlan.model_validate(
        {
            "grids": {
                "x": [
                    {"label": "A", "position": 0},
                    {"label": "B", "position": 6000},
                    {"label": "C", "position": 12000},
                ],
                "y": [
                    {"label": "1", "position": 0},
                    {"label": "2", "position": 5000},
                ],
            },
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3500},
            ],
            "columns": [
                {
                    "id": "C1",
                    "type": "COL",
                    "at": {"x": "A", "y": "1"},
                    "base": "BASE",
                    "top": "L1",
                },
                {
                    "id": "C2",
                    "type": "COL",
                    "at": {"x": "B", "y": "1"},
                    "base": "BASE",
                    "top": "L1",
                },
                {
                    "id": "C3",
                    "type": "COL",
                    "at": {"x": "C", "y": "1"},
                    "base": "BASE",
                    "top": "L1",
                },
            ],
            "beams": [
                {
                    "id": "B1",
                    "type": "BEAM",
                    "story": "L1",
                    "start": {"x": "A", "y": "1"},
                    "end": {"x": "B", "y": "1"},
                },
                {
                    "id": "B2",
                    "type": "BEAM",
                    "story": "L1",
                    "start": {"x": "B", "y": "1"},
                    "end": {"x": "C", "y": "1"},
                },
            ],
            "slabs": [
                {
                    "id": "S1",
                    "type": "SLAB",
                    "story": "L1",
                    "boundary": [
                        {"x": "A", "y": "1"},
                        {"x": "C", "y": "1"},
                        {"x": "C", "y": "2"},
                        {"x": "A", "y": "2"},
                    ],
                }
            ],
        }
    )


# ───────────────────────────── 1. IFC2X3 export ─────────────────────────────


def test_ifc2x3_two_bay_frame_counts_and_validates() -> None:
    building = generate(_two_bay_plan(), "s")
    objects = _two_bay_objects()
    materials = default_material_library()

    ifc_file, ids, skipped = export_ifc(building, objects, materials, "TwoBay", schema="IFC2X3")
    assert skipped == []
    assert ifc_file.schema == "IFC2X3"

    reopened = ifcopenshell.file.from_string(ifc_file.to_string())
    assert reopened.schema == "IFC2X3"
    assert len(reopened.by_type("IfcBeam")) == 2
    assert len(reopened.by_type("IfcColumn")) == 3
    assert len(reopened.by_type("IfcSlab")) == 1
    assert set(ids) == {"C1", "C2", "C3", "B1", "B2", "S1"}
    _validate_clean(reopened)


def test_ifc2x3_stairs_carry_their_shape_type() -> None:
    # IFC2X3's IfcStair.ShapeType is required (PredefinedType came in IFC4); unset, a project
    # with a stair failed the schema (#299).
    from test_ifc import ADDITIONS, PLAN, STAIR_OBJECTS

    from saengine.library.bim import Additions

    building = generate(PLAN, "s").model_copy(
        update={"additions": Additions.model_validate(ADDITIONS)}
    )
    ifc_file, _, _ = export_ifc(building, STAIR_OBJECTS, None, "Stair", schema="IFC2X3")
    (stair,) = ifc_file.by_type("IfcStair")
    assert stair.ShapeType == "STRAIGHT_RUN_STAIR"
    _validate_clean(ifcopenshell.file.from_string(ifc_file.to_string()))


def test_ifc2x3_maps_mep_and_architecture_cleanly() -> None:
    from test_ifc import OBJECTS, PLAN

    building = generate(PLAN, "s")
    mep = MepModel.model_validate(
        {
            "equipment": [
                {
                    "id": "EQ1",
                    "kind": "chiller",
                    "story": "BASE",
                    "x": 1500,
                    "y": 1500,
                    "length": 1200,
                    "width": 800,
                    "height": 900,
                    "operatingWeight": 25.0,
                }
            ],
            "plumbing": {
                "tanks": [
                    {
                        "id": "TK1",
                        "kind": "overhead",
                        "story": "L1",
                        "x": 3000,
                        "y": 2500,
                        "length": 2000,
                        "width": 1500,
                        "waterDepth": 1200,
                    }
                ],
                "risers": [
                    {
                        "id": "PR1",
                        "system": "coldWater",
                        "fromStory": "BASE",
                        "toStory": "L1",
                        "x": 1000,
                        "y": 1000,
                        "diameter": 100,
                    }
                ],
            },
        }
    )
    arch = Architecture.model_validate(
        {
            "wallTypes": [
                {
                    "id": "WT1",
                    "name": "Brick 125",
                    "layers": [{"material": "Brick", "thickness": 125, "unitWeight": 18.85}],
                }
            ],
            "doorTypes": [{"id": "DT1", "name": "Door 900", "width": 900, "height": 2100}],
            "walls": [
                {
                    "id": "AW1",
                    "type": "WT1",
                    "base": "BASE",
                    "top": "L1",
                    "path": [[0, 2000], [4000, 2000]],
                }
            ],
            "doors": [{"id": "AD1", "type": "DT1", "wall": "AW1", "offset": 1500}],
        }
    )
    ifc_file, ids, skipped = export_ifc(
        building, OBJECTS, None, "Full2x3", mep=mep, architecture=arch, schema="IFC2X3"
    )
    assert skipped == []
    assert ifc_file.schema == "IFC2X3"
    assert len(ifc_file.by_type("IfcEnergyConversionDevice")) == 1
    assert len(ifc_file.by_type("IfcFlowStorageDevice")) == 1
    assert len(ifc_file.by_type("IfcFlowSegment")) == 1
    assert len(ifc_file.by_type("IfcDoorStyle")) == 1
    assert {"EQ1", "TK1", "PR1", "arch:AW1", "arch:AD1"} <= set(ids)
    _validate_clean(ifc_file)


def test_ifc_schema_option_in_settings_action_and_cli(tmp_path: Path) -> None:
    from saengine.actions import run_actions
    from saengine.cli.main import main

    # Create a tiny project via actions, configure ifc.schema=IFC2X3 in settings, export via action and CLI.
    root = tmp_path / "Proj"
    res = run_actions(
        root,
        [
            {
                "action": "project.create",
                "params": {
                    "name": "Proj",
                    "building": {"gridsX": [5000], "gridsY": [4000], "storyCount": 2},
                },
            },
            {"action": "run.step", "params": {"step": "derive"}},
        ],
        write=True,
    )
    assert res.ok, res

    out_action = root / "action2x3.ifc"
    res2 = run_actions(
        root,
        [
            {
                "action": "export.ifc",
                "params": {"out": str(out_action), "schema": "IFC2X3", "structuralAnalysis": True},
            }
        ],
        write=True,
    )
    assert res2.ok, res2
    ifc_act = ifcopenshell.open(str(out_action))
    assert ifc_act.schema == "IFC2X3"
    assert len(ifc_act.by_type("IfcStructuralAnalysisModel")) == 1
    _validate_clean(ifc_act)

    # Settings fallback: set ifc.schema = IFC2X3 in project-settings.json and export via CLI without --schema.
    settings_path = root / "02 Project Settings" / "project-settings.json"
    cfg = json.loads(settings_path.read_text(encoding="utf-8"))
    cfg["ifc"] = {"schema": "IFC2X3"}
    settings_path.write_text(json.dumps(cfg, indent="\t"), encoding="utf-8")

    out_cli = root / "cli2x3.ifc"
    code = main(["export", str(root), "--format", "ifc", "--out", str(out_cli)])
    assert code == 0
    assert ifcopenshell.open(str(out_cli)).schema == "IFC2X3"


# ───────────────────────────── 2. Structural analysis view ─────────────────────────────


def _edge_length_mm(curve_member: ifcopenshell.entity_instance) -> float:
    edge = curve_member.Representation.Representations[0].Items[0]
    p1 = edge.EdgeStart.VertexGeometry.Coordinates
    p2 = edge.EdgeEnd.VertexGeometry.Coordinates
    return math.dist(p1, p2)


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_structural_analysis_view_two_bay_frame(schema: str) -> None:
    building = generate(_two_bay_plan(), "s")
    objects = _two_bay_objects()
    materials = default_material_library()
    analytical = two_bay_frame()

    ifc_file, _ids, skipped = export_ifc(
        building,
        objects,
        materials,
        "TwoBayAnalysis",
        schema=schema,
        analytical=analytical,
    )
    assert skipped == []

    models = ifc_file.by_type("IfcStructuralAnalysisModel")
    assert len(models) == 1

    curves = {m.Name: m for m in ifc_file.by_type("IfcStructuralCurveMember")}
    assert set(curves) == {"C1", "C2", "C3", "B1", "B2"}
    # Verify axis lengths by hand: columns 3500 mm, beams 6000 mm.
    for col in ("C1", "C2", "C3"):
        assert _edge_length_mm(curves[col]) == pytest.approx(3500.0, abs=1e-6)
    for bm in ("B1", "B2"):
        assert _edge_length_mm(curves[bm]) == pytest.approx(6000.0, abs=1e-6)

    # Supports at the 3 base nodes (z = 0).
    point_conns = ifc_file.by_type("IfcStructuralPointConnection")
    supported = [c for c in point_conns if c.AppliedCondition is not None]
    assert len(supported) == 3
    for sc in supported:
        z = sc.Representation.Representations[0].Items[0].VertexGeometry.Coordinates[2]
        assert z == pytest.approx(0.0, abs=1e-6)

    # One load group per case (D, L, WX) plus one for combination 1.2D+1.6L.
    groups = ifc_file.by_type("IfcStructuralLoadGroup")
    by_name = {g.Name: g for g in groups}
    assert {"D", "L", "WX", "1.2D+1.6L"} <= set(by_name)
    assert by_name["D"].PredefinedType == "LOAD_CASE"
    assert by_name["1.2D+1.6L"].PredefinedType == "LOAD_COMBINATION"
    assert len(ifc_file.by_type("IfcStructuralLinearAction")) == 4  # D & L on B1, B2
    assert len(ifc_file.by_type("IfcStructuralPointAction")) == 1  # WX on node 4

    # Linked back to physical elements via IfcRelAssignsToProduct.
    rels = ifc_file.by_type("IfcRelAssignsToProduct")
    linked = {
        (r.RelatingProduct.Name, r.RelatedObjects[0].Name)
        for r in rels
        if r.RelatingProduct.is_a("IfcStructuralCurveMember")
    }
    assert linked == {(k, k) for k in ("C1", "C2", "C3", "B1", "B2")}
    _validate_clean(ifc_file)


def test_structural_analysis_surface_member() -> None:
    from saengine.exporters.analytical import Plate, PlateSection

    building = generate(_two_bay_plan(), "s")
    objects = _two_bay_objects()
    analytical = two_bay_frame()
    # Add slab plate S1 across nodes 4, 5, 6 -> plus a corner node at y=5 m.
    from saengine.exporters.analytical import Node

    analytical.nodes[7] = Node(7, (12.0, 5.0, 3.5))
    analytical.nodes[8] = Node(8, (0.0, 5.0, 3.5))
    analytical.plate_sections["SLAB"] = PlateSection("SLAB", "C25", 0.15, "slab")
    analytical.plates.append(Plate("S1", [4, 6, 7, 8], "SLAB", source="S1"))

    ifc_file, _, skipped = export_ifc(
        building, objects, default_material_library(), "PlateTest", analytical=analytical
    )
    assert skipped == []
    surfaces = ifc_file.by_type("IfcStructuralSurfaceMember")
    assert len(surfaces) == 1
    assert surfaces[0].Thickness == pytest.approx(150.0)
    rels = [
        r for r in ifc_file.by_type("IfcRelAssignsToProduct") if r.RelatingProduct == surfaces[0]
    ]
    assert len(rels) == 1 and rels[0].RelatedObjects[0].Name == "S1"
    _validate_clean(ifc_file)


# ───────────────────────────── 3. Georeferencing ─────────────────────────────


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
@pytest.mark.parametrize("crs", ["BTM", "UTM"])
def test_georeferencing_map_conversion_against_crs(schema: str, crs: str) -> None:
    building = generate(_two_bay_plan(), "s")
    objects = _two_bay_objects()
    soil = SoilReport.model_validate(
        {
            "groundLevel": 1500.0,
            "site": {"lat": 23.8069, "lon": 90.3687, "x": 5000.0, "y": 2000.0, "rotation": 15.0},
        }
    )

    ifc_file, _, skipped = export_ifc(
        building, objects, default_material_library(), "GeoTest", schema=schema, soil=soil, crs=crs
    )
    assert skipped == []
    if schema == "IFC4":
        mc = ifc_file.by_type("IfcMapConversion")
        pcrs = ifc_file.by_type("IfcProjectedCRS")
        assert len(mc) == 1 and len(pcrs) == 1
        assert pcrs[0].Name == ("EPSG:9678" if crs == "BTM" else "EPSG:32646")
    else:
        proj = ifc_file.by_type("IfcProject")[0]
        assert ifcopenshell.util.element.get_pset(proj, "ePSet_MapConversion") is not None
        pcrs = ifcopenshell.util.element.get_pset(proj, "ePSet_ProjectedCRS")
        assert pcrs is not None
        assert pcrs["Name"] == ("EPSG:9678" if crs == "BTM" else "EPSG:32646")

    # Hand-check: local site point (5000, 2000, 0) mm converts to exact CRS easting/northing.
    e_ifc, n_ifc, h_ifc = gl.auto_xyz2enh(ifc_file, 5000.0, 2000.0, 0.0)
    if crs == "BTM":
        e_exp, n_exp = wgs84_to_btm(23.8069, 90.3687)
    else:
        e_exp, n_exp, epsg = wgs84_to_utm(23.8069, 90.3687)
        assert epsg == 32646
    assert e_ifc == pytest.approx(e_exp, abs=1e-4)
    assert n_ifc == pytest.approx(n_exp, abs=1e-4)
    assert h_ifc == pytest.approx(1.5, abs=1e-6)
    _validate_clean(ifc_file)


# ───────────────────────────── 4. Steel connections ─────────────────────────────


def _fin_plate_frame(n_bolts: int = 3) -> tuple[BuildingModel, ObjectLibrary]:
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "SCOL",
                    "name": "UC 203x203x46",
                    "kind": "column",
                    "material": "A992",
                    "profile": {
                        "shape": "I",
                        "overallWidth": 203.6,
                        "overallDepth": 203.2,
                        "webThickness": 7.2,
                        "flangeThickness": 11.0,
                        "filletRadius": 10.2,
                    },
                },
                {
                    "id": "SBM",
                    "name": "IPE 300 Fin",
                    "kind": "beam",
                    "material": "A992",
                    "profile": {
                        "shape": "I",
                        "overallWidth": 150.0,
                        "overallDepth": 300.0,
                        "webThickness": 7.1,
                        "flangeThickness": 10.7,
                        "filletRadius": 15.0,
                    },
                    "connection": {
                        "type": "finPlate",
                        "rows": n_bolts,
                        "boltDiameter": 20,
                        "plateThickness": 10,
                    },
                },
            ]
        }
    )
    plan = FloorPlan.model_validate(
        {
            **default_floor_plan().model_dump(mode="json", by_alias=True),
            "columns": [
                {
                    "id": "C1",
                    "type": "SCOL",
                    "at": {"x": "A", "y": "1"},
                    "base": "BASE",
                    "top": "L1",
                }
            ],
            "beams": [
                {
                    "id": "B1",
                    "type": "SBM",
                    "story": "L1",
                    "start": {"x": "A", "y": "1"},
                    "end": {"x": "B", "y": "1"},
                }
            ],
        }
    )
    return generate(plan, "s"), objects


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
@pytest.mark.parametrize("n_bolts", [3, 4])
def test_fin_plate_connection_exports_plate_bolts_and_openings(schema: str, n_bolts: int) -> None:
    building, objects = _fin_plate_frame(n_bolts)
    materials = default_material_library()
    ifc_file, _ids, skipped = export_ifc(building, objects, materials, "SteelConn", schema=schema)
    assert skipped == []

    # Beam B1 has two fin-plate ends (one welded to column C1, one loose at free end):
    # each connection assembly has 1 plate + n bolts with n openings.
    assemblies = ifc_file.by_type("IfcElementAssembly")
    assert len(assemblies) == 2
    for asm in assemblies:
        assert asm.Tag  # assembly mark assigned
        parts = ifcopenshell.util.element.get_parts(asm)
        asm_plates = [p for p in parts if p.is_a("IfcPlate")]
        asm_bolts = [
            p
            for p in parts
            if p.is_a("IfcFastener" if schema == "IFC2X3" else "IfcMechanicalFastener")
        ]
        assert len(asm_plates) == 1
        assert asm_plates[0].Tag  # part mark assigned
        assert len(asm_bolts) == n_bolts
        assert len(asm_plates[0].HasOpenings) == n_bolts
    assert len(ifc_file.by_type("IfcPlate")) == 2
    assert len(ifc_file.by_type("IfcOpeningElement")) == 2 * n_bolts
    _validate_clean(ifc_file)


# ───────────────────────────── 5. IFC model diff ─────────────────────────────


def test_ifc_diff_self_is_empty_and_moved_beam_reported() -> None:
    building_a = generate(_two_bay_plan(), "s")
    objects = _two_bay_objects()
    materials = default_material_library()

    ifc_a, _, _ = export_ifc(building_a, objects, materials, "RevA")
    ifc_a2, _, _ = export_ifc(building_a, objects, materials, "RevA")

    # Diff of a model against itself (even a separate export run) is empty.
    self_report = diff_ifc(ifc_a, ifc_a2)
    assert self_report["added"] == []
    assert self_report["deleted"] == []
    assert self_report["changed"] == []
    assert self_report["counts"]["changed"] == 0
    assert self_report["summary"] == "No changes"

    # Move beam B1 by 100 mm along Y.
    building_b = building_a.model_copy(deep=True)
    for el in building_b.elements:
        if el.id == "B1":
            el.start = [el.start[0], el.start[1] + 100.0]
            el.end = [el.end[0], el.end[1] + 100.0]
    ifc_b, _, _ = export_ifc(building_b, objects, materials, "RevB")

    report = diff_ifc(ifc_a, ifc_b)
    assert report["added"] == []
    assert report["deleted"] == []
    assert len(report["changed"]) == 1
    ch = report["changed"][0]
    assert ch["globalId"] == global_id("B1")
    assert ch["name"] == "B1"
    assert "placement" in ch["fields"]
    assert "100 mm" in ch["what"]
    assert [c["colour"] for c in report["colourSummary"]] == ["green", "red", "amber"]
    assert report["colourSummary"][2]["count"] == 1

    # Also verify integration with project/diff.py's diff_file on .ifc bytes.
    changes = diff_file(
        "exports",
        "11 Exports/IFC/Rev.ifc",
        ifc_a.to_string().encode("utf-8"),
        ifc_b.to_string().encode("utf-8"),
    )
    assert len(changes) == 1
    assert changes[0]["kind"] == "changed"
    assert changes[0]["id"] == global_id("B1")
    assert changes[0]["colour"] == "amber"

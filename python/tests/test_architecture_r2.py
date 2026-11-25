"""Revit-parity R2 tests: components, conceptual massing, in-place elements, and types library."""

from __future__ import annotations

import json
import math

import pytest
from test_architecture import ELEVATIONS, OBJECTS, PLAN
from test_line_loads import OBJECTS as STRUCT_OBJECTS
from test_line_loads import _applied, plan

from saengine.boq.quantities import bill_of_quantities
from saengine.codes import context as code_context
from saengine.fem import architecture_loads as al
from saengine.fem.derive import derive_fem
from saengine.library import default_material_library
from saengine.library.architecture import Architecture, default_architecture
from saengine.library.bim import generate
from saengine.library.components import (
    _G_KN_PER_KG,
    array_component,
    component_schedule,
    detect_host_room,
    mirror_component,
    place_component,
    starter_component_types,
)
from saengine.library.export import library_json
from saengine.library.ifc import export_ifc
from saengine.library.massing import (
    ConceptualMass,
    InPlaceElement,
    create_floors_from_mass,
    mass_floor_area_report,
    mass_floors,
    mass_volume_m3,
    section_area_m2,
)
from saengine.library.settings import default_project_settings
from saengine.library.types_library import (
    TYPES_LIBRARY_SCHEMA_ID,
    delete_type,
    duplicate_type,
    edit_type,
    export_types_library_json,
    import_types_library,
    list_types,
    rename_type,
    type_usages,
)


def _room_arch(room_w: float = 4000, room_d: float = 3500) -> Architecture:
    """Single rectangular room on L1 enclosed by separators of exact size ``room_w × room_d``."""
    data = library_json(default_architecture())
    data.update(
        {
            "separators": [
                {"id": "S1", "story": "L1", "start": [0, 0], "end": [room_w, 0]},
                {"id": "S2", "story": "L1", "start": [room_w, 0], "end": [room_w, room_d]},
                {"id": "S3", "story": "L1", "start": [room_w, room_d], "end": [0, room_d]},
                {"id": "S4", "story": "L1", "start": [0, room_d], "end": [0, 0]},
            ],
            "rooms": [
                {"id": "R1", "story": "L1", "point": [room_w / 2, room_d / 2], "name": "Bedroom"}
            ],
        }
    )
    return Architecture.model_validate(data)


def _two_room_arch() -> Architecture:
    """Two adjacent rooms R1 (0..4000 × 0..5000) and R2 (4000..6000 × 0..5000) on L1."""
    data = library_json(default_architecture())
    data.update(
        {
            "separators": [
                {"id": "S1", "story": "L1", "start": [0, 0], "end": [6000, 0]},
                {"id": "S2", "story": "L1", "start": [6000, 0], "end": [6000, 5000]},
                {"id": "S3", "story": "L1", "start": [6000, 5000], "end": [0, 5000]},
                {"id": "S4", "story": "L1", "start": [0, 5000], "end": [0, 0]},
                {"id": "S5", "story": "L1", "start": [4000, 0], "end": [4000, 5000]},
            ],
            "rooms": [
                {"id": "R1", "story": "L1", "point": [2000, 2500], "name": "Dining"},
                {"id": "R2", "story": "L1", "point": [5000, 2500], "name": "Study"},
            ],
        }
    )
    return Architecture.model_validate(data)


# ───────────────────────────── 1. components ─────────────────────────────


def test_starter_component_library_has_all_required_items() -> None:
    starter = {t.id: t for t in starter_component_types()}
    required = {
        "BED-DBL",
        "BED-SGL",
        "SOFA-3",
        "TABLE-DIN",
        "WARDROBE",
        "CAB-BASE",
        "CAB-WALL",
        "WC",
        "BASIN",
        "SINK",
        "SHOWER",
        "DESK",
        "CHAIR",
        "SHELF",
        "AC-IDU",
        "WH-ELEC",
    }
    assert required <= set(starter)
    assert (starter["BED-DBL"].width, starter["BED-DBL"].depth) == (2000, 1600)
    assert all(len(t.symbol2d) > 0 for t in starter.values())
    assert starter["WH-ELEC"].representation3d == "cylinder"
    assert starter["WC"].resolved_ifc_class() == "IfcSanitaryTerminal"
    assert starter["AC-IDU"].resolved_ifc_class() == "IfcFlowTerminal"


def test_place_bed_in_room_detects_host_and_counts_in_boq() -> None:
    arch = _room_arch(4000, 3500)
    arch, bed = place_component(arch, "BED-DBL", "L1", [2000, 1750], ELEVATIONS)
    assert bed.hostRoom == "R1"
    assert detect_host_room(arch, "L1", [5000, 5000], ELEVATIONS) is None

    bill = bill_of_quantities(
        generate(PLAN, "s"), OBJECTS, default_material_library(), architecture=arch
    )
    furniture = [i for i in bill.items if i.group == "furniture"]
    assert len(furniture) == 1
    assert furniture[0].quantity == 1.0
    assert furniture[0].byStory == {"L1": 1.0}
    assert furniture[0].breakdown[0].detail == "R1 (Bedroom)"
    assert bill.total("furniture", "nr") == 1.0


def test_schedule_three_chairs_and_one_table_across_two_rooms() -> None:
    arch = _two_room_arch()
    arch, _ = place_component(arch, "TABLE-DIN", "L1", [2000, 2500], ELEVATIONS)
    arch, _ = place_component(arch, "CHAIR", "L1", [1500, 2500], ELEVATIONS)
    arch, _ = place_component(arch, "CHAIR", "L1", [2500, 2500], ELEVATIONS)
    arch, _ = place_component(arch, "CHAIR", "L1", [5000, 2500], ELEVATIONS)

    sched = component_schedule(arch, ELEVATIONS)
    assert sched["totalCount"] == 4
    assert sched["byRoom"]["R1"]["counts"] == {"TABLE-DIN": 1, "CHAIR": 2}
    assert sched["byRoom"]["R2"]["counts"] == {"CHAIR": 1}
    assert sched["byStory"]["L1"]["counts"] == {"TABLE-DIN": 1, "CHAIR": 3}
    # 45 + 3 * 7 = 66 kg
    assert sched["totalWeight_kg"] == pytest.approx(66.0)

    bill = bill_of_quantities(
        generate(PLAN, "s"), OBJECTS, default_material_library(), architecture=arch
    )
    chairs = next(i for i in bill.items if i.group == "furniture" and "CHAIR" in i.description)
    tables = next(i for i in bill.items if i.group == "furniture" and "TABLE-DIN" in i.description)
    assert chairs.quantity == 3.0
    assert tables.quantity == 1.0


def test_mirror_and_array_components() -> None:
    arch = _two_room_arch()
    arch, c1 = place_component(arch, "DESK", "L1", [1000, 2500], ELEVATIONS, rotation=30.0)
    # Mirror copy across x = 4000 moves point x = 1000 -> x = 7000 (outside R2) or across x = 3000 -> 5000 (into R2)
    arch, c2 = mirror_component(arch, c1.id, [3000, 0], [3000, 5000], ELEVATIONS, copy=True)
    assert c2.point == pytest.approx([5000, 2500])
    assert c2.mirrored is True
    assert c2.rotation == pytest.approx(150.0)
    assert c2.hostRoom == "R2"

    # Linear array of 3 chairs inside R1 (x = 1000, 2000, 3000)
    arch, ch1 = place_component(arch, "CHAIR", "L1", [1000, 1000], ELEVATIONS)
    arch, copies = array_component(arch, ch1.id, count=3, dx=1000.0, dy=0.0, elevations=ELEVATIONS)
    assert len(copies) == 2
    assert [c.point for c in copies] == [[2000.0, 1000.0], [3000.0, 1000.0]]
    assert all(c.hostRoom == "R1" for c in copies)


def test_component_loads_report_only_vs_explicit_code_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    bay_plan = plan(2)
    building = generate(bay_plan, "s")
    settings = default_project_settings("Bay")
    arch = Architecture.model_validate(library_json(default_architecture()))
    arch, _ = place_component(
        arch, "WARDROBE", "L1", [3000, 2500], {"BASE": 0.0, "L1": 3200.0, "L2": 6400.0}
    )

    # Default pack: explicitFurnishings is False -> report-only, SD unchanged
    loads_default = al.architecture_loads(arch, building, STRUCT_OBJECTS)
    assert len(loads_default.component_rows) == 1
    assert loads_default.component_rows[0]["applied"] is False
    assert loads_default.component_loads == []
    assert any("report-only" in n for n in loads_default.notes)

    base_fem = derive_fem(
        building, STRUCT_OBJECTS, default_material_library(), settings, {"bim": "x"}
    )
    with_comp = derive_fem(
        building,
        STRUCT_OBJECTS,
        default_material_library(),
        settings,
        {"bim": "x"},
        architecture=arch,
    )
    assert -_applied(with_comp.project, "SD") == pytest.approx(-_applied(base_fem.project, "SD"))

    # Custom code pack allowing explicit furnishings: applies 95 kg * g = 0.93163 kN as SD
    pack = code_context.current()
    patched_table = pack.table("areaLoads").model_copy(
        update={
            "partitions": pack.table("areaLoads").partitions.model_copy(
                update={"explicitFurnishings": True}
            )
        }
    )
    custom_pack = pack._copy()
    custom_pack._validated["areaLoads"] = patched_table
    expected_n = 95.0 * _G_KN_PER_KG * 1e3
    monkeypatch.setattr(code_context, "pack_for", lambda *a, **k: custom_pack)
    with code_context.using(custom_pack):
        loads_explicit = al.architecture_loads(arch, building, STRUCT_OBJECTS)
        assert loads_explicit.component_rows[0]["applied"] is True
        assert len(loads_explicit.component_loads) == 1
        assert loads_explicit.component_loads[0].force == pytest.approx(expected_n)

        for slab_mode in ("loadsToBeams", "shells"):
            mode_settings = settings.model_copy(
                update={"analysis": settings.analysis.model_copy(update={"slabs": slab_mode})}
            )
            base_m = derive_fem(
                building, STRUCT_OBJECTS, default_material_library(), mode_settings, {"bim": "x"}
            )
            comp_m = derive_fem(
                building,
                STRUCT_OBJECTS,
                default_material_library(),
                mode_settings,
                {"bim": "x"},
                architecture=arch,
            )
            sd_diff = (-_applied(comp_m.project, "SD")) - (-_applied(base_m.project, "SD"))
            assert sd_diff == pytest.approx(expected_n, rel=1e-4)


# ───────────────────────────── 2. conceptual massing & in-place ─────────────────────────────


def test_mass_extrusion_floors_gfa_far_and_create_floors() -> None:
    mass = ConceptualMass(
        id="M1",
        name="Tower Mass",
        kind="extrusion",
        baseElevation=0.0,
        height=30_000.0,
        outline=[[0, 0], [20_000, 0], [20_000, 15_000], [0, 15_000]],
        floorHeight=3000.0,
        use="residential",
    )
    floors = mass_floors(mass)
    assert len(floors) == 10
    assert [f["elevation"] for f in floors] == [k * 3000.0 for k in range(10)]
    assert all(f["area_m2"] == pytest.approx(300.0) for f in floors)

    report = mass_floor_area_report([mass], plot_area_m2=1000.0, use="A1-A4", road_width_m=12.0)
    assert report["floorCount"] == 10
    assert report["grossFloorArea_m2"] == pytest.approx(3000.0)
    assert report["groundCoverage_m2"] == pytest.approx(300.0)
    assert report["totalVolume_m3"] == pytest.approx(9000.0)
    assert report["far"] == pytest.approx(3.0)
    assert report["groundCoveragePercent"] == pytest.approx(30.0)
    assert any(
        c["label"] == "FAR" and c["provided"] == pytest.approx(3.0) for c in report["checks"]
    )

    generated = create_floors_from_mass(mass)
    assert len(generated["stories"]) == 11  # 10 floors + top roof level at +30 m
    assert generated["stories"][-1]["elevation"] == pytest.approx(30_000.0)
    assert len(generated["floorOutlines"]) == 10
    assert generated["grossFloorArea_m2"] == pytest.approx(3000.0)

    # Mass is excluded from structural loads & BOQ
    arch = Architecture.model_validate({**library_json(default_architecture()), "masses": [mass]})
    assert al.has_loads(arch) is False
    bill = bill_of_quantities(
        generate(PLAN, "s"), OBJECTS, default_material_library(), architecture=arch
    )
    assert not any(i.group == "furniture" for i in bill.items)


def test_loft_volume_by_hand_prismoid_formula() -> None:
    """20×15 m base (300 m²) to 10×10 m top (100 m²) over 30 m:
    mid section is 15×12.5 m -> Am = 187.5 m².
    Prismoid volume V = h/6 * (A1 + 4*Am + A2) = 30/6 * (300 + 4*187.5 + 100) = 5750.0 m³."""
    loft = ConceptualMass(
        id="M-LOFT",
        name="Tapered Tower",
        kind="loft",
        baseElevation=0.0,
        height=30_000.0,
        baseOutline=[[0, 0], [20_000, 0], [20_000, 15_000], [0, 15_000]],
        topOutline=[[5_000, 2_500], [15_000, 2_500], [15_000, 12_500], [5_000, 12_500]],
    )
    assert section_area_m2(loft, 0.0) == pytest.approx(300.0)
    assert section_area_m2(loft, 15_000.0) == pytest.approx(187.5)
    assert section_area_m2(loft, 30_000.0) == pytest.approx(100.0)
    assert mass_volume_m3(loft) == pytest.approx(30.0 / 6.0 * (300.0 + 4.0 * 187.5 + 100.0))
    assert mass_volume_m3(loft) == pytest.approx(5750.0)

    cyl = ConceptualMass(id="M-CYL", kind="cylinder", height=10_000.0, center=[0, 0], radius=5000.0)
    assert mass_volume_m3(cyl) == pytest.approx(math.pi * 25.0 * 10.0)


def test_in_place_element_schedule_and_boq() -> None:
    arch = _room_arch(4000, 3500)
    elem = InPlaceElement(
        id="IP1",
        name="Custom Reception Counter",
        category="casework",
        story="L1",
        geometry="box",
        origin=[2000, 1750],
        width=2400,
        depth=700,
        height=1050,
        weight=120.0,
        material="Corian / timber",
        hostRoom="R1",
        parameters={"adaSection": True},
    )
    arch = Architecture.model_validate({**library_json(arch), "inPlaceElements": [elem]})
    sched = component_schedule(arch, ELEVATIONS)
    assert len(sched["inPlace"]) == 1
    assert sched["inPlace"][0]["room"] == "R1"
    assert sched["totalWeight_kg"] == pytest.approx(120.0)
    bill = bill_of_quantities(
        generate(PLAN, "s"), OBJECTS, default_material_library(), architecture=arch
    )
    ip_items = [i for i in bill.items if i.group == "furniture" and "IP1" in i.description]
    assert len(ip_items) == 1 and ip_items[0].quantity == 1.0


# ───────────────────────────── 3. types library & parametric openings ─────────────────────────────


def test_types_library_crud_rename_delete_refusal_and_round_trip() -> None:
    arch = _room_arch(4000, 3500)
    arch, _ = place_component(arch, "BED-DBL", "L1", [2000, 1750], ELEVATIONS)

    # All categories listed
    all_rows = list_types(arch)
    categories_present = {r["category"] for r in all_rows}
    assert {
        "wall",
        "door",
        "window",
        "finish",
        "roof",
        "railing",
        "curtainWall",
        "component",
    } <= categories_present

    # Used type cannot be deleted
    assert type_usages(arch, "component", "BED-DBL") == ["C1"]
    with pytest.raises(ValueError, match="in use by C1"):
        delete_type(arch, "component", "BED-DBL")

    # Unused type can be deleted
    arch_del = delete_type(arch, "component", "BED-SGL")
    assert not any(t.id == "BED-SGL" for t in arch_del.componentTypes)

    # Duplicate, edit parameters, and rename cascading to instances
    arch, dup = duplicate_type(arch, "door", "D1", new_id="D1-DBL", new_name="Main double door")
    assert dup.id == "D1-DBL"
    arch = edit_type(
        arch,
        "door",
        "D1-DBL",
        {"leafCount": 2, "swing": "both", "frame": 60, "sill": 15, "lintel": 250},
    )
    arch = rename_type(arch, "component", "BED-DBL", new_id="BED-Q", new_name="Queen bed")
    assert arch.components[0].type == "BED-Q"

    # Export -> import JSON round trip preserves every type (including ceiling types)
    lib_text = export_types_library_json(arch, name="Office Standard A")
    lib_obj = json.loads(lib_text)
    assert lib_obj["schema"] == TYPES_LIBRARY_SCHEMA_ID
    lib_obj["ceilingTypes"] = [{"id": "CLG-ACT", "name": "Acoustic grid ceiling", "thickness": 15}]

    blank = Architecture()
    imported, summary = import_types_library(blank, json.dumps(lib_obj), mode="merge")
    assert summary["added"] > 0
    assert {t.id for t in imported.wallTypes} == {t.id for t in arch.wallTypes}
    assert {t.id for t in imported.doorTypes} == {t.id for t in arch.doorTypes}
    assert {t.id for t in imported.windowTypes} == {t.id for t in arch.windowTypes}
    assert {t.id for t in imported.finishTypes} == {t.id for t in arch.finishTypes}
    assert {t.id for t in imported.roofTypes} == {t.id for t in arch.roofTypes}
    assert {t.id for t in imported.railingTypes} == {t.id for t in arch.railingTypes}
    assert {t.id for t in imported.curtainWallTypes} == {t.id for t in arch.curtainWallTypes}
    assert {t.id for t in imported.componentTypes} == {t.id for t in arch.componentTypes}
    d1_dbl = next(t for t in imported.doorTypes if t.id == "D1-DBL")
    assert (d1_dbl.leafCount, d1_dbl.swing, d1_dbl.frame, d1_dbl.sill, d1_dbl.lintel) == (
        2,
        "both",
        60,
        15,
        250,
    )


# ───────────────────────────── 4. IFC export & parametric plan symbols ─────────────────────────────


def test_ifc_export_contains_furniture_terminal_mass_proxy_and_opening_params() -> None:
    arch = _room_arch(4000, 3500)
    arch = Architecture.model_validate(
        {
            **library_json(arch),
            "walls": [{"id": "AW1", "type": "BW250", "base": "L1", "path": [[0, 0], [4000, 0]]}],
            "doorTypes": [
                {
                    "id": "D-R",
                    "name": "Right Swing Door",
                    "style": "single",
                    "width": 1000,
                    "height": 2100,
                    "frame": 65,
                    "leafCount": 1,
                    "swing": "right",
                    "sill": 20,
                    "lintel": 300,
                }
            ],
            "doors": [{"id": "D1", "type": "D-R", "wall": "AW1", "offset": 2000}],
            "masses": [
                {
                    "id": "M1",
                    "name": "Concept Volume",
                    "kind": "extrusion",
                    "baseElevation": 0.0,
                    "height": 30_000.0,
                    "outline": [[0, 0], [20_000, 0], [20_000, 15_000], [0, 15_000]],
                    "floorHeight": 3000.0,
                },
                {
                    "id": "M2",
                    "name": "Concept Loft",
                    "kind": "loft",
                    "baseElevation": 0.0,
                    "height": 30_000.0,
                    "baseOutline": [[0, 0], [20_000, 0], [20_000, 15_000], [0, 15_000]],
                    "topOutline": [
                        [5_000, 2_500],
                        [15_000, 2_500],
                        [15_000, 12_500],
                        [5_000, 12_500],
                    ],
                },
            ],
        }
    )
    arch, _ = place_component(arch, "BED-DBL", "L1", [2000, 1750], ELEVATIONS, rotation=90.0)
    arch, _ = place_component(arch, "WC", "L1", [500, 500], ELEVATIONS)
    arch, _ = place_component(arch, "AC-IDU", "L1", [3500, 500], ELEVATIONS)

    ifc, _, skipped = export_ifc(generate(PLAN, "s"), OBJECTS, None, "Test", architecture=arch)
    assert skipped == []

    import ifcopenshell.util.element

    furniture = ifc.by_type("IfcFurniture")
    assert len(furniture) == 1
    assert furniture[0].Tag == "C1"
    pset_comp = ifcopenshell.util.element.get_pset(furniture[0], "SAEngine_Component")
    assert pset_comp["TypeId"] == "BED-DBL"
    assert pset_comp["Width_mm"] == 2000.0
    assert pset_comp["Depth_mm"] == 1600.0
    assert pset_comp["Weight_kg"] == 65.0
    assert pset_comp["sizeLabel"] == "Queen/Double"

    assert len(ifc.by_type("IfcSanitaryTerminal")) == 1
    terminals = ifc.by_type("IfcFlowTerminal", include_subtypes=False)
    assert len(terminals) == 1
    assert terminals[0].Tag == "C3"

    proxies = ifc.by_type("IfcBuildingElementProxy")
    assert {p.Tag for p in proxies} == {"M1", "M2"}
    m1 = next(p for p in proxies if p.Tag == "M1")
    m2 = next(p for p in proxies if p.Tag == "M2")
    pset_m1 = ifcopenshell.util.element.get_pset(m1, "SAEngine_Mass")
    assert pset_m1["ExcludedFromStructure"] is True
    assert pset_m1["FloorCount"] == 10
    assert pset_m1["GrossFloorArea_m2"] == pytest.approx(3000.0)
    pset_m2 = ifcopenshell.util.element.get_pset(m2, "SAEngine_Mass")
    assert pset_m2["Volume_m3"] == pytest.approx(5750.0)

    door = ifc.by_type("IfcDoor")[0]
    assert door.OperationType == "SINGLE_SWING_RIGHT"
    door_type = ifcopenshell.util.element.get_type(door)
    pset_opening = ifcopenshell.util.element.get_pset(door_type, "SAEngine_OpeningType")
    assert pset_opening["FrameWidth"] == 65.0
    assert pset_opening["Swing"] == "right"
    assert pset_opening["Lintel"] == 300.0

"""Phase D of special structures: parametric shapes, geometry import and model scripts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from test_structure import CANOPY, OBJECTS

from saengine.library import default_material_library
from saengine.library.bim import generate_from_structure, source_stamp
from saengine.library.ifc import export_ifc
from saengine.library.importers import ImportOptions, import_geometry
from saengine.library.script import TEMPLATE, run_script
from saengine.library.shapes import (
    Arch,
    BarrelVault,
    CableNet,
    Dome,
    PlaneTruss,
    PortalFrame,
    SpaceTruss,
    insert,
    shape_geometry,
)
from saengine.library.structure import StructuralModel, plane_of
from saengine.rpc import handlers

KINDS = {"COL": "column", "BM": "beam", "RS": "slab", "WL": "wall"}


def counts(shape: object) -> tuple[int, int, int]:
    g = shape_geometry(shape)  # type: ignore[arg-type]
    return len(g.members), len(g.areas), len(g.supports)


def test_shapes_have_the_members_of_their_pattern() -> None:
    # 8 x 6 bays: top chords 8*7 + 9*6, bottom chords 7*6 + 8*5, four diagonals per bay.
    truss = SpaceTruss(lengthX=24000, lengthY=18000, baysX=8, baysY=6, depth=1500, memberType="BM")
    assert counts(truss) == (110 + 82 + 4 * 48, 0, 2 * (9 + 7) - 4)
    assert counts(truss.model_copy(update={"supportAt": "corners"}))[2] == 4
    # Pratt: chords 8 + 8, verticals 9, diagonals 8; Warren: chords 8 + 7, diagonals 16.
    assert counts(PlaneTruss(span=24000, depth=2000, panels=8, memberType="BM")) == (33, 0, 2)
    warren = PlaneTruss(span=24000, depth=2000, panels=8, memberType="BM", pattern="warren")
    assert counts(warren) == (31, 0, 2)
    # Schwedler dome, 16 ribs and 5 rings: ribs 16 + 4*16, rings 5*16, diagonals 4*16.
    dome = Dome(radius=20000, rise=8000, rings=5, segments=16, memberType="BM", panelType="RS")
    assert counts(dome) == (16 + 64 + 80 + 64, 16 + 2 * 64, 16)
    assert counts(
        BarrelVault(span=20000, rise=6000, length=40000, segments=8, bays=8, memberType="BM")
    ) == (
        9 * 8 + 9 * 8 + 8 * 8,
        0,
        18,
    )
    assert counts(
        CableNet(
            lengthX=30000, lengthY=20000, divisionsX=10, divisionsY=8, rise=3000, memberType="BM"
        )
    ) == (
        10 * 9 + 11 * 8,
        0,
        2 * (11 + 9) - 4,
    )


def test_shapes_are_placed_and_their_geometry_is_right() -> None:
    arch = shape_geometry(
        Arch(
            span=30000,
            rise=8000,
            segments=12,
            memberType="BM",
            origin=(1000, 2000, 500),
            rotation=90,
        )
    )
    ends = [m.end for m in arch.members]
    # Turned to run along y from the origin; the crown is mid-span, 8 m up.
    assert np.allclose(arch.members[0].start, [1000, 2000, 500])
    assert np.allclose(ends[-1], [1000, 32000, 500], atol=1e-6)
    assert np.allclose(ends[5], [1000, 17000, 8500], atol=1e-6)
    parabolic = shape_geometry(
        Arch(span=30000, rise=8000, segments=4, memberType="BM", form="parabolic")
    )
    assert np.allclose([m.end[2] for m in parabolic.members], [6000, 8000, 6000, 0])

    dome = shape_geometry(
        Dome(radius=20000, rise=8000, rings=4, segments=12, memberType="BM", panelType="RS")
    )
    # Every node lies on the sphere through the base circle and the crown.
    sphere = (20000**2 + 8000**2) / (2 * 8000)
    centre = np.array([0, 0, 8000 - sphere])
    nodes = [p for m in dome.members for p in (m.start, m.end)]
    assert max(abs(np.linalg.norm(p - centre) - sphere) for p in nodes) < 1e-6
    assert all(plane_of(a.outline) is not None for a in dome.areas)
    assert all(
        abs(s.at[2]) < 1e-9 and abs(np.hypot(*s.at[:2]) - 20000) < 1e-6 for s in dome.supports
    )

    with pytest.raises(ValidationError, match="half sphere"):
        Dome(radius=10000, rise=12000, rings=4, segments=12, memberType="BM")
    with pytest.raises(ValidationError, match="half circle"):
        Arch(span=10000, rise=6000, segments=4, memberType="BM")


def test_insert_gives_fresh_ids_and_skips_what_is_there() -> None:
    truss = shape_geometry(PlaneTruss(span=12000, depth=1500, panels=4, memberType="BM"))
    model, ids, skipped = insert(CANOPY, truss)
    # 17 members and 2 supports; the support at (0, 0, 0) was already there.
    assert (len(ids), skipped, len(model.supports)) == (18, 1, 5)
    # The canopy's members are C1-C4 and B1-B4: new members start at M1, supports at SP1.
    assert ids[0] == "M1" and ids[-1] == "SP1"
    again, more, skipped = insert(model, truss)
    assert (more, skipped) == ([], 19)
    assert again == model
    StructuralModel.model_validate(model.model_dump(by_alias=True))


def test_dxf_import(tmp_path: Path) -> None:
    import ezdxf

    doc = ezdxf.new(units=6)  # metres
    msp = doc.modelspace()
    msp.add_line((0, 0, 4), (0, 0, 0), dxfattribs={"layer": "Columns"})
    msp.add_line((0, 0, 4), (6, 0, 4), dxfattribs={"layer": "BM"})
    msp.add_lwpolyline([(0, 0), (6, 0), (6, 5), (0, 5)], close=True, dxfattribs={"elevation": 4})
    msp.add_3dface([(0, 5, 0), (6, 5, 0), (6, 5, 4), (0, 5, 4)])
    msp.add_text("note")
    doc.saveas(tmp_path / "frame.dxf")

    options = ImportOptions(columnType="COL", slabType="RS", wallType="WL", supports="fixed")
    g = import_geometry(tmp_path / "frame.dxf", options, KINDS)
    assert [(m.type, list(m.start), list(m.end)) for m in g.members] == [
        ("COL", [0, 0, 0], [0, 0, 4000]),  # columns run upwards
        ("BM", [0, 0, 4000], [6000, 0, 4000]),  # its layer is named like a beam type
    ]
    assert [(a.type, len(a.outline)) for a in g.areas] == [("WL", 4), ("RS", 4)]
    assert sorted(tuple(s.at) for s in g.supports) == [(0, 0, 0), (0, 5000, 0), (6000, 5000, 0)]
    assert g.notes == ["1 TEXT entities skipped."]

    # Without an area type, a closed polyline is members along it.
    g = import_geometry(tmp_path / "frame.dxf", ImportOptions(memberType="BM", units="mm"), KINDS)
    assert len(g.members) == 1 + 4 and np.allclose(g.members[1].end, [6, 0, 4])
    assert g.notes[:2] == [
        "1 members skipped: no type for them (choose one).",
        "1 areas skipped: no type for them (choose one).",
    ]


def test_rhino_import(tmp_path: Path) -> None:
    import rhino3dm as r

    f = r.File3dm()
    f.Settings.ModelUnitSystem = r.UnitSystem.Meters
    layer = r.Layer()
    layer.Name = "Default"
    f.Layers.Add(layer)
    f.Objects.AddLine(r.Point3d(0, 0, 0), r.Point3d(0, 0, 4))
    f.Objects.AddArc(r.Arc(r.Point3d(10, 0, 0), 2, np.pi))
    plane = r.PlaneSurface(
        r.Plane(r.Point3d(0, 0, 4), r.Vector3d(0, 0, 1)), r.Interval(0, 6), r.Interval(0, 5)
    )
    f.Objects.AddBrep(r.Brep.CreateFromSurface(plane))
    f.Objects.AddBrep(
        r.Brep.CreateFromBox(r.Box(r.BoundingBox(r.Point3d(0, 0, 0), r.Point3d(1, 1, 1))))
    )
    mesh = r.Mesh()
    for v in ((0, 0, 8), (6, 0, 8), (6, 5, 8)):
        mesh.Vertices.Add(*v)
    mesh.Faces.AddFace(0, 1, 2)
    f.Objects.AddMesh(mesh)
    f.Write(str(tmp_path / "roof.3dm"), 8)

    g = import_geometry(
        tmp_path / "roof.3dm",
        ImportOptions(memberType="BM", columnType="COL", slabType="RS"),
        KINDS,
    )
    assert (g.members[0].type, list(g.members[0].end)) == ("COL", [0, 0, 4000])
    arc = g.members[1:]
    assert len(arc) >= 8 and np.allclose(arc[-1].end, [8000, 0, 0], atol=1e-6)
    assert [(a.type, len(a.outline)) for a in g.areas] == [("RS", 4), ("RS", 3)]
    assert g.notes == ["1 closed solids (model their mid-surfaces instead) skipped."]


def test_ifc_import_round_trips_the_building_model(tmp_path: Path) -> None:
    model = generate_from_structure(CANOPY, source_stamp("canopy"))
    ifc, _, _ = export_ifc(model, OBJECTS, default_material_library(), "Canopy")
    ifc.write(str(tmp_path / "canopy.ifc"))

    g = import_geometry(
        tmp_path / "canopy.ifc", ImportOptions(supports="pinned"), KINDS | {"RS": "slab"}
    )
    # Types come from the IFC types, named like the object types they were exported from.
    imported = sorted((m.type, tuple(np.round(m.start)), tuple(np.round(m.end))) for m in g.members)
    expected = sorted(
        (m.type, tuple(m.start.array()), tuple(m.end.array())) for m in CANOPY.members
    )
    assert [(t, s, e) for t, s, e in imported if t == "COL"] == [
        x for x in expected if x[0] == "COL"
    ]
    assert len(imported) == 8
    (area,) = g.areas
    assert area.type == "RS" and len(area.outline) == 4 and len(area.openings) == 1
    assert {round(p[2]) for p in area.outline} == {4000}
    assert len(g.supports) == 4 and g.notes == []


def test_script_builds_the_model(tmp_path: Path) -> None:
    script = tmp_path / "frame.py"
    script.write_text(TEMPLATE.format(column="COL", member="BM"), encoding="utf-8")
    text = json.dumps(CANOPY.model_dump(mode="json", by_alias=True))
    result = run_script(text, str(script))
    model = StructuralModel.model_validate_json(result["text"])
    # model.clear(): the canopy is gone; 12 columns and supports, then the vault on top.
    assert result["cleared"] and not any(m.id.startswith(("C", "B")) for m in model.members)
    assert sum(m.type == "COL" for m in model.members) == 12 and len(model.supports) == 12
    vault = BarrelVault(span=30000, rise=7500, length=30000, segments=12, bays=5, memberType="BM")
    assert sum(m.type == "BM" for m in model.members) == counts(vault)[0]
    assert model.grids == CANOPY.grids

    script.write_text(
        'print("hello")\nmodel.member((0, 0, 0), (0, 0, 0), type="BM")\nmodel.nope()\n',
        encoding="utf-8",
    )
    result = run_script(text, str(script))
    assert (
        result["error"] == "AttributeError (line 3): 'ModelBuilder' object has no attribute 'nope'"
    )
    assert result["output"].startswith("hello")


def test_rpc_handlers(tmp_path: Path) -> None:
    shape = {"kind": "arch", "span": 12000, "rise": 3000, "segments": 4, "memberType": "BM"}
    geometry = handlers.shape_geometry(shape)
    assert len(geometry["members"]) == 4 and geometry["supports"][1]["at"] == [12000, 0, 0]
    assert handlers.shape_geometry({**shape, "segments": 1})["problems"] == [
        "segments: Input should be greater than or equal to 2"
    ]
    text = json.dumps(CANOPY.model_dump(mode="json", by_alias=True))
    inserted = handlers.insert_geometry(text, geometry)
    assert inserted["ids"] == ["M1", "M2", "M3", "M4", "SP1"] and inserted["skipped"] == 1
    assert len(StructuralModel.model_validate_json(inserted["text"]).members) == 12
    missing = handlers.import_geometry(str(tmp_path / "x.step"), {}, None)
    assert missing["problems"] == [
        "x.step: x.step: only DXF, DWG, IFC and Rhino (.3dm) files can be imported"
    ]


# ───────────────────────────── portal frames (PEB sheds) ─────────────────────────────


def _peb(**changes: object) -> PortalFrame:
    values: dict[str, object] = {
        "width": 30000,
        "length": 72000,
        "bays": 9,
        "eaveHeight": 9000,
        "endColumns": 3,
        "columnType": "C",
        "rafterType": "R",
        "purlinType": "P",
        "girtType": "G",
        "bracingType": "B",
    }
    return PortalFrame.model_validate({**values, **changes})


def test_portal_frame_gable_geometry():
    shape = _peb()
    g = shape_geometry(shape)
    # 10 frames x 2 columns + 3 end wall columns at each gable end, all supported.
    assert len(g.supports) == 26
    assert all(s.fixity == "pinned" for s in g.supports)
    ridge = 9000 + 15000 * np.tan(np.radians(5.71))
    tops = max(max(m.start[2], m.end[2]) for m in g.members)
    assert tops == pytest.approx(ridge, abs=0.5)
    # Purlins at equal spacing no wider than 1500 mm along the slope.
    lines = shape.purlin_lines()
    steps = np.diff(lines[: len(lines) // 2 + 1])
    assert np.all(steps / np.cos(np.radians(5.71)) <= 1500 + 1e-6)
    # Two braced bays (the end bays): 2 walls x 2 + 2 slopes x 2 panels x 2 diagonals each.
    braces = [m for m in g.members if m.type == "B"]
    assert len(braces) == 2 * (2 * 2 + 2 * 2 * 2)
    # Every purlin and roof brace end lies on a rafter node (rafters are split there).
    rafter_nodes = {
        tuple(np.round(p, 1)) for m in g.members if m.type == "R" for p in (m.start, m.end)
    }
    for m in g.members:
        if m.type in ("P", "B") and min(m.start[2], m.end[2]) > 9000 - 1:
            assert tuple(np.round(m.start, 1)) in rafter_nodes


def test_portal_frame_mono_slope_two_spans_and_checks():
    shape = _peb(roof="monoSlope", slope=5, spans=2, endColumns=0, bracedBays=[5])
    g = shape_geometry(shape)
    high = 9000 + 30000 * np.tan(np.radians(5))
    assert max(max(m.start[2], m.end[2]) for m in g.members) == pytest.approx(high, abs=0.5)
    # Interior column line at mid-width, up to the roof, in every frame.
    interior = [m for m in g.members if m.type == "C" and abs(m.start[0] - 15000) < 1]
    assert len({round(m.start[1]) for m in interior}) == 10
    assert {round(min(m.start[1], m.end[1])) for m in g.members if m.type == "B"} == {32000}
    with pytest.raises(ValidationError):
        _peb(bracedBays=[10])

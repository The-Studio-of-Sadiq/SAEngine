"""Export of SAEngine projects to ETABS text models (.e2k), checked by reading them back.

The golden file (tests/data/export/tiny.e2k) is the export of the synthetic model below; write it
again with ``SAENGINE_UPDATE_GOLDEN=1`` after a deliberate change of the format, and look at the
difference.
"""

from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from saengine.exporters.etabs import (
    Equipment,
    designation,
    export_e2k,
    library_shape,
    write_e2k,
)
from saengine.importers.common import file_combinations
from saengine.importers.etabs import read_e2k
from saengine.importers.project import section_lookup_noted
from saengine.library import BuildingModel, MaterialLibrary, ObjectLibrary, ProjectSettings
from saengine.library.settings import default_project_settings

GOLDEN = Path(__file__).parent / "data" / "export" / "tiny.e2k"
SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)

# ───────────────────────────────────── the synthetic model ─────────────────────────────────────

IPE300 = {
    "shape": "I",
    "overallWidth": 150,
    "overallDepth": 300,
    "webThickness": 7.1,
    "flangeThickness": 10.7,
}
WELDED_I = {
    "shape": "I",
    "overallWidth": 130,
    "overallDepth": 260,
    "webThickness": 6.5,
    "flangeThickness": 9.5,
}


def tiny() -> tuple[BuildingModel, ObjectLibrary, MaterialLibrary, ProjectSettings]:
    """Two stories of one 5 m x 4 m bay: RC columns, beams and slabs, a steel beam pinned at
    both ends, an IPE 300 brace, a brick wall on a beam, a slab opening and a typical floor."""
    materials = MaterialLibrary.model_validate(
        {
            "materials": [
                {
                    "id": "C25",
                    "name": "Concrete 25",
                    "category": "concrete",
                    "mechanical": {"E": 23500, "nu": 0.2, "density": 2400, "alpha": 1e-5},
                    "concrete": {"fc": 25},
                },
                {
                    "id": "B420",
                    "name": "Rebar 420",
                    "category": "rebar",
                    "mechanical": {"E": 200000, "density": 7850},
                    "steel": {"fy": 420, "fu": 525, "grade": "B420DWR"},
                },
                {
                    "id": "S275",
                    "name": "Steel 275",
                    "category": "steel",
                    "mechanical": {"E": 200000, "nu": 0.3, "density": 7850},
                    "steel": {"fy": 275, "fu": 430, "grade": "S275"},
                },
                {
                    "id": "BRICK",
                    "name": "Brick",
                    "category": "masonry",
                    "mechanical": {"density": 1900},
                    "masonry": {"unit": "first-class brick"},
                },
            ]
        }
    )
    bars = {
        "material": "B420",
        "cover": 40,
        "longitudinal": [{"position": "perimeter", "count": 8, "dia": 16}],
        "transverse": {"type": "tie", "dia": 10, "spacing": 150, "legs": 2},
    }
    beam_bars = {
        "material": "B420",
        "cover": 40,
        "longitudinal": [
            {"position": "top", "count": 3, "dia": 16},
            {"position": "bottom", "count": 3, "dia": 20},
        ],
        "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
    }
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "C300x400",
                    "name": "Column",
                    "kind": "column",
                    "material": "C25",
                    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 400},
                    "reinforcement": bars,
                },
                {
                    "id": "B250x450",
                    "name": "Beam",
                    "kind": "beam",
                    "material": "C25",
                    "profile": {"shape": "rectangle", "xDim": 250, "yDim": 450},
                    "reinforcement": beam_bars,
                },
                {
                    "id": "SB260",
                    "name": "Steel beam",
                    "kind": "beam",
                    "material": "S275",
                    "profile": WELDED_I,
                    "connection": {"type": "finPlate"},
                },
                {
                    "id": "BR-IPE300",
                    "name": "Brace",
                    "kind": "brace",
                    "material": "S275",
                    "profile": IPE300,
                },
                {
                    "id": "S125",
                    "name": "Slab",
                    "kind": "slab",
                    "material": "C25",
                    "thickness": 125,
                },
                {
                    "id": "BW125",
                    "name": "Brick wall",
                    "kind": "wall",
                    "material": "BRICK",
                    "thickness": 125,
                    "structural": False,
                },
            ]
        }
    )
    corners = [(0, 0), (5000, 0), (5000, 4000), (0, 4000)]
    elements: list[dict[str, Any]] = []
    stories = [("BASE", 0), ("L1", 3000), ("L2", 6000)]
    for (story, z), (_, below) in zip(stories[1:], stories[:-1], strict=True):
        for k, (x, y) in enumerate(corners, 1):
            elements.append(
                {
                    "kind": "column",
                    "id": f"C{k}-{story}",
                    "type": "C300x400",
                    "position": [x, y],
                    "bottom": below,
                    "top": z,
                    "rotation": 90 if k == 2 else 0,
                }
            )
        for k in range(4):
            steel = story == "L2" and k == 0
            elements.append(
                {
                    "kind": "beam",
                    "id": f"B{k + 1}-{story}",
                    "type": "SB260" if steel else "B250x450",
                    "start": list(corners[k]),
                    "end": list(corners[(k + 1) % 4]),
                    "elevation": z,
                }
            )
        elements.append(
            {
                "kind": "slab",
                "id": f"S-{story}",
                "type": "S125",
                "boundary": [list(c) for c in corners],
                "elevation": z,
            }
        )
    elements.append(
        {
            "kind": "wall",
            "id": "BW1",
            "type": "BW125",
            "start": [0, 4000],
            "end": [5000, 4000],
            "bottom": 3000,
            "top": 6000,
        }
    )
    building = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
                {"id": "L2", "name": "Level 2", "elevation": 6000, "similarTo": "L1"},
            ],
            "elements": elements,
            "additions": {
                "members": [
                    {
                        "id": "BR1",
                        "type": "BR-IPE300",
                        "x1": 0,
                        "y1": 0,
                        "z1": 0,
                        "x2": 5000,
                        "y2": 0,
                        "z2": 3000,
                    }
                ],
                "slabOpenings": [
                    {"id": "O1", "host": "S-L1", "x": 2500, "y": 2000, "xDim": 1000, "yDim": 800}
                ],
            },
        }
    )
    settings = default_project_settings("Tiny")
    settings.analysis.stiffness = "aci"
    settings.analysis.crackedFor = "all"
    return building, objects, materials, settings


def tiny_export(**kwargs: Any) -> Any:
    building, objects, materials, settings = tiny()
    grids = [("X", "A", 0.0), ("X", "B", 5000.0), ("Y", "1", 0.0), ("Y", "2", 4000.0)]
    return write_e2k(building, objects, materials, settings, grids=grids, **kwargs)


# ─────────────────────────────────────── golden text ───────────────────────────────────────


def test_tiny_model_matches_the_golden_file() -> None:
    text = tiny_export().text
    if os.environ.get("SAENGINE_UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    assert text == GOLDEN.read_text(encoding="utf-8")


def test_tiny_model_writes_each_block_as_etabs_reads_it() -> None:
    result = tiny_export()
    text, report = result.text, result.report.to_dict()
    lines = text.splitlines()
    # Stories from the top, the typical floor similar to its master.
    stories = [line.strip() for line in lines if line.strip().startswith("STORY ")]
    assert stories == [
        'STORY "Level 2"  HEIGHT 3 SIMILARTO "Level 1"',
        'STORY "Level 1"  HEIGHT 3 MASTERSTORY "Yes"',
        'STORY "Base"  ELEV 0',
    ]
    # Column depth (local 2) is the profile's x; beams' depth is their y.
    assert 'SHAPE "Concrete Rectangular"  D 0.3 B 0.4' in text
    assert 'SHAPE "Concrete Rectangular"  D 0.45 B 0.25' in text
    # 8 bars round a 300 x 400 column: 3 along the 400 side, 3 along the 300 side.
    assert 'PATTERN "R-3-3"' in text
    # The IPE 300 brace by its library name, the welded I by its plates.
    assert 'FRAMESECTION  "BR-IPE300"  MATERIAL "S275"  SHAPE "IPE300"  FILE "Euro"' in text
    assert 'SHAPE "Steel I/Wide Flange"  D 0.26 B 0.13 TF 0.0095 TW 0.0065' in text
    # The steel beam with a fin plate: released in bending at both ends.
    assert any('"B1-L2"' in x and 'RELEASE "M2I M3I M2J M3J"' in x for x in lines)
    # Cracked sections as modifiers; the column turned 90° by its angle.
    assert any('"C2-L1"' in x and "ANG  90" in x and "PROPMODI33 0.7" in x for x in lines)
    # The brace from the base up to Level 1.
    assert any(x.strip().startswith('LINE  "BR1"  BRACE') and x.endswith("1") for x in lines)
    # Area loads: floor finish and partitions as SD, live as L below the roof, Lr on it.
    floor, roof = settings_loads()
    assert f'LC "SD"  FVAL {floor[0]:g}' in text
    assert f'LC "L"  FVAL {floor[1]:g}' in text
    assert f'LC "Lr"  FVAL {roof[1]:g}' in text
    # The brick wall on beam B3 of Level 1, its weight per metre.
    wall = 1900 * 9.80665 * 0.125 * 3.0 / 1000  # kN/m
    load = next(x for x in lines if x.strip().startswith('LINELOAD  "B3-L1"'))
    assert f"FSTART {round(wall, 9):.10g}" in load and "RDSTART 0  RDEND 1" in load
    # Restraints at the base, a rigid diaphragm above it.
    assert text.count('RESTRAINT "UX UY UZ RX RY RZ"') == 4
    assert 'POINTASSIGN  "1"  "Level 1"  DIAPH "D1"' in text
    # No derivation: the lateral patterns are empty, and the report says so.
    assert any("could not be derived" in w for w in report["warnings"])
    assert report["exported"]["columns"] == 8 and report["exported"]["beams"] == 8


def settings_loads() -> tuple[tuple[float, float], tuple[float, float]]:
    settings = default_project_settings("Tiny")
    loads = {a.id: a for a in settings.areaLoads}
    floor, roof = loads[settings.floorLoad], loads[settings.roofLoad]
    return (floor.finish + floor.partitions, floor.live), (roof.finish + roof.partitions, roof.live)


def test_n_mm_units() -> None:
    text = tiny_export(units=("N", "MM")).text
    assert 'UNITS  "N"  "MM"  "C"' in text
    assert 'SHAPE "Concrete Rectangular"  D 300 B 400' in text
    assert "FC 25" in text  # MPa = N/mm²
    assert 'STORY "Level 1"  HEIGHT 3000' in text


# ─────────────────────────────────────── lateral loads ───────────────────────────────────────


def derivation(forces: dict[str, list[tuple[tuple[float, float, float], float]]]) -> dict:
    nodes, patterns = {}, []
    for case, loads in forces.items():
        nodal = []
        for xyz, value in loads:
            node = nodes.setdefault(xyz, len(nodes) + 1)
            vector = [value, 0, 0] if case.endswith("X") else [0, value, 0]
            nodal.append({"node_id": node, "forces": [*vector, 0, 0, 0]})
        patterns.append({"name": case, "nodal_loads": nodal})
    return {
        "nodes": [{"id": i, "coords": list(xyz)} for xyz, i in nodes.items()],
        "load_patterns": patterns,
    }


def test_story_forces_at_the_centre_of_mass() -> None:
    # Two nodes on Level 1 sharing 30 kN 2:1, one on Level 2 with 20 kN.
    forces = {
        "EX": [((0.0, 0.0, 3.0), 20e3), ((5.0, 0.0, 3.0), 10e3), ((2.0, 3.0, 6.0), 20e3)],
        "EY": [((0.0, 0.0, 3.0), 20e3), ((5.0, 0.0, 3.0), 10e3), ((2.0, 3.0, 6.0), 20e3)],
    }
    result = tiny_export(derivation=derivation(forces))
    text = result.text
    points = {
        line.split('"')[1]: line.split()[2:4]
        for line in text.splitlines()
        if line.strip().startswith("POINT ")
    }
    loads = [line for line in text.splitlines() if line.strip().startswith("POINTLOAD")]
    level1 = next(x for x in loads if '"Level 1"' in x and '"EX"' in x)
    label = level1.split('"')[1]
    assert points[label] == ["1.66667", "0"]  # (2·0 + 1·5) / 3, to 0.01 mm
    assert level1.rstrip().endswith("FX 30")
    assert any('"Level 2"' in x and '"EY"' in x and x.rstrip().endswith("FY 20") for x in loads)
    assert f'POINTASSIGN  "{label}"  "Level 1"  DIAPH "D1"' in text
    assert result.report.carried["EX"] == pytest.approx(50)


def test_user_coefficient() -> None:
    result = tiny_export(lateral="coefficient", summary={"Sa_g": 0.05625, "period_s": 0.3})
    assert (
        'SEISMIC "EX"  "User Coefficient"    DIR "X"    TOPSTORY "Level 2"    BOTTOMSTORY "Base"'
        "    SHEARCOEFF 0.05625  HEIGHTEXPONENT 1"
    ) in result.text


def test_equipment_point_loads_and_fluid_pattern() -> None:
    tank = Equipment("T1", "L2", [(1000.0, 1000.0), (2000.0, 1000.0)], {"SD": 10e3, "F": 20e3})
    pump = Equipment("P1", "BASE", [(0.0, 0.0)], {"SD": 5e3})
    result = tiny_export(equipment=[tank, pump])
    text = result.text
    loads = [x for x in text.splitlines() if x.strip().startswith("POINTLOAD")]
    assert sum('LC "SD"' in x and x.rstrip().endswith("FZ -5") for x in loads) == 2
    assert sum('LC "F"' in x and x.rstrip().endswith("FZ -10") for x in loads) == 2
    assert 'LOADPATTERN "F"  TYPE  "Other"  SELFWEIGHT  0' in text
    assert 'MASSSOURCELOAD  "MsSrc1"  "F"  1' in text
    assert 'COMBO "1.4D"  LOADCASE "F"  SF 1.4' in text
    report = result.report.to_dict()
    assert report["exported"]["equipment"] == 1  # the pump stands on the ground
    assert any(item["examples"] == ["P1"] for item in report["skipped"])


# ─────────────────────────────────────── steel names ───────────────────────────────────────


def test_steel_designations_and_libraries() -> None:
    assert designation(IPE300) == "IPE 300"
    assert library_shape("IPE 300") == ("Euro", "IPE300")
    assert library_shape("HEA 200") == ("Euro", "HE200A")
    assert library_shape("W14x90") == ("AISC16", "W14X90")
    assert library_shape("ISMB300") == ("Indian", "ISMB300")
    assert library_shape("SHS 100x100x5") is None  # by its dimensions
    assert designation(WELDED_I) is None


# ─────────────────────────────────────── round trips ───────────────────────────────────────


def round_trip(e2k_text: str, tmp_path: Path) -> Any:
    path = tmp_path / "model.e2k"
    path.write_text(e2k_text, encoding="utf-8")
    return read_e2k(path, section_lookup=section_lookup_noted)


def profile_dims(profile: Any) -> dict[str, float]:
    data = profile.model_dump() if hasattr(profile, "model_dump") else dict(profile)
    return {
        k: round(float(v), 2)
        for k, v in data.items()
        if isinstance(v, int | float) and not k.endswith("Radius")
    }


def check_round_trip(
    building: BuildingModel,
    objects: ObjectLibrary,
    settings: ProjectSettings,
    imported: Any,
    export_report: Any,
) -> None:
    """Counts, sections, area loads and combinations of the project read back from its e2k."""
    counts = imported.report.imported
    original: dict[str, int] = {}
    for e in building.elements:
        t = next(o for o in objects.objects if o.id == e.type)
        kind = "partition" if getattr(t, "structural", True) is False else e.kind
        original[kind] = original.get(kind, 0) + 1
    assert counts["columns"] == original.get("column", 0)
    assert counts["beams"] == original.get("beam", 0)
    assert counts["slabs"] == original.get("slab", 0)
    assert counts.get("walls", 0) == original.get("wall", 0)
    # The import counts the storeys above the base (N12).
    assert counts["stories"] == len(building.stories) - 1
    assert counts.get("braces", 0) + counts.get("inclinedMembers", 0) == len(
        building.additions.members
    )
    # Sections: each object type comes back with the same profile or thickness.
    for o in objects.objects:
        used = any(e.type == o.id for e in building.elements) or any(
            m.type == o.id for m in building.additions.members
        )
        if not used or getattr(o, "structural", True) is False or o.kind in ("footing",):
            continue
        twin = next(
            (x for x in imported.objects.objects if x.id == o.id or x.name.startswith(f"{o.id} ")),
            None,
        )
        assert twin is not None, o.id
        if hasattr(o, "profile"):
            assert profile_dims(twin.profile) == profile_dims(o.profile), o.id
        else:
            assert twin.thickness == pytest.approx(o.thickness), o.id
    # Loads: the floor and roof loads come back as the area loads of their slabs.
    loads = {a.id: a for a in settings.areaLoads}
    floor = loads[settings.floorLoad]
    imported_loads = {a.id: a for a in imported.settings.areaLoads}
    assert imported_loads["FL"].finish == pytest.approx(floor.finish + floor.partitions)
    assert imported_loads["FL"].live == pytest.approx(floor.live)
    # Every load of the project went into the file.
    assert not any(export_report.not_carried.values())

    # Combinations: the same factors on the same cases.
    def factors(c: Any) -> tuple:
        return tuple(round(getattr(c, k), 6) for k in ("D", "L", "Lr", "WX", "WY", "EX", "EY"))

    imported_combinations = file_combinations(imported.settings.combinations).values()
    assert sorted(factors(c) for c in imported_combinations) == sorted(
        {factors(c) for c in settings.combinations}
    )


def test_tiny_model_round_trip(tmp_path: Path) -> None:
    building, objects, _, settings = tiny()
    result = tiny_export()
    imported = round_trip(result.text, tmp_path)
    check_round_trip(building, objects, settings, imported, result.report)
    # The pinned steel beam comes back with its simple connection.
    steel = next(o for o in imported.objects.objects if o.id.startswith("SB260"))
    assert steel.connection is not None
    # The column bars: 8 bars of 16 mm, ties of 10 mm at 150.
    column = next(o for o in imported.objects.objects if o.id == "C300x400")
    assert column.reinforcement.longitudinal[0].count == 8
    assert column.reinforcement.longitudinal[0].dia == pytest.approx(16, abs=0.05)
    assert column.reinforcement.transverse.spacing == pytest.approx(150)
    # The brick wall's weight on the beam comes back as a member load (N10), not as a lost load.
    wall = 1900 * 9.80665 * 0.125 * 3.0 / 1000 * 5.0  # kN
    assert imported.report.not_carried.get("D", 0.0) == pytest.approx(0.0, abs=1e-9)
    assert imported.report.imported["memberLineLoads"] == 1
    assert imported.report.carried["D"] >= wall * (1 - 1e-6)
    assert imported.report.imported["slabOpenings"] == 1


def test_sample_round_trip(tmp_path: Path) -> None:
    result = export_e2k(SAMPLE, derive=False)
    imported = round_trip(result.text, tmp_path)
    building = BuildingModel.model_validate_json(
        (SAMPLE / "06 BIM" / "bim.json").read_text(encoding="utf-8")
    )
    objects = ObjectLibrary.model_validate_json(
        (SAMPLE / "04 Objects" / "objects.json").read_text(encoding="utf-8")
    )
    settings = ProjectSettings.model_validate_json(
        (SAMPLE / "02 Project Settings" / "project-settings.json").read_text(encoding="utf-8")
    )
    building.elements = [e for e in building.elements if e.kind != "footing"]
    check_round_trip(building, objects, settings, imported, result.report)
    assert imported.problems() == []
    # The rotated column keeps its angle.
    plan = imported.floor_plan
    rotations = sorted(c.rotation for c in plan.columns)
    original = sorted(e.rotation for e in building.elements if e.kind == "column")
    assert rotations == pytest.approx(original)


def test_generated_building_round_trip(tmp_path: Path) -> None:
    from saengine.library.generator import generate_building, write_building

    spec = {
        "name": "Four storeys",
        "gridsX": [6000, 5000],
        "gridsY": [5000, 4500],
        "storyCount": 4,
        "typicalHeight": 3000,
        "groundHeight": 3500,
        "lateralSizing": "gravity",
        "typical": True,
    }
    folder = tmp_path / "Four storeys"
    write_building(generate_building(spec), folder, "Four storeys")
    result = export_e2k(folder, derive=False)
    text = result.text
    assert "SIMILARTO" in text  # typical floors as similar stories
    imported = round_trip(text, tmp_path)
    building = BuildingModel.model_validate_json(
        (folder / "06 BIM" / "bim.json").read_text(encoding="utf-8")
    )
    objects = ObjectLibrary.model_validate_json(
        (folder / "04 Objects" / "objects.json").read_text(encoding="utf-8")
    )
    settings = ProjectSettings.model_validate_json(
        (folder / "02 Project Settings" / "project-settings.json").read_text(encoding="utf-8")
    )
    building.elements = [e for e in building.elements if e.kind != "footing"]
    check_round_trip(building, objects, settings, imported, result.report)
    assert imported.problems() == []


def test_cli_writes_the_e2k_and_its_report(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    from saengine.cli.main import main
    from saengine.exporters import etabs

    project = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, project)
    real = etabs.export_e2k
    monkeypatch.setattr(etabs, "export_e2k", lambda *a, **k: real(*a, **k, derive=False))
    out = tmp_path / "out" / "model.e2k"
    code = main(["export", "--json", "--format", "e2k", str(project), str(out)])
    assert code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["format"] == "e2k" and Path(document["files"][0]) == out
    assert out.read_bytes().startswith(b"$ File Sample Frame.e2k")
    report = json.loads((tmp_path / "out" / "model.export-report.json").read_text("utf-8"))
    assert report["schema"] == "saengine.exportReport/1"
    assert report["exported"]["columns"] == 7
    assert not (project / "08 FEM" / "model.osmodel").exists()  # the project is not touched
    # The live load on the slabs less their openings (as ETABS loads them; residential floors
    # at 2.0 kN/m²), and the overhead tank's water as F.
    assert math.isclose(report["loads"]["exportedKN"]["L"], 107.012, rel_tol=1e-4)
    assert math.isclose(report["loads"]["exportedKN"]["F"], 47.9, rel_tol=1e-4)


def test_app_export_writes_into_the_exports_folder(tmp_path: Path, monkeypatch: Any) -> None:
    """The Exports page's ``export/e2k``: ``11 Exports/ETABS/<project>.e2k`` and its report, or
    the reason it cannot export."""
    from saengine.exporters import etabs

    project = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, project)
    real = etabs.export_e2k
    monkeypatch.setattr(etabs, "export_e2k", lambda *a, **k: real(*a, **k, derive=False))
    answer = etabs.rpc_export_e2k({"projectRoot": str(project)})
    target = project / "11 Exports" / "ETABS" / "Sample Frame.e2k"
    assert Path(answer["path"]) == target and target.exists()
    assert Path(answer["reportPath"]) == target.with_name("Sample Frame.export-report.json")
    assert answer["report"]["exported"]["columns"] == 7
    # N-R4: the report names the file, counts the stories above the base as the import does,
    # and has a version to read beside the JSON.
    assert answer["report"]["target"]["file"] == "Sample Frame.e2k"
    readable = Path(answer["readablePath"])
    assert readable == target.with_name("Sample Frame.export-report.md")
    assert readable.read_text("utf-8").startswith("# ETABS export: Sample Frame")
    assert "## Written" in readable.read_text("utf-8")
    missing = etabs.rpc_export_e2k({"projectRoot": str(tmp_path / "nowhere")})
    assert set(missing) == {"error"} and missing["error"]

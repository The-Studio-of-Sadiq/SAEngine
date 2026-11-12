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
from saengine.importers.etabs import read_e2k
from saengine.importers.project import section_lookup_noted
from saengine.library import BuildingModel, MaterialLibrary, ObjectLibrary, ProjectSettings
from saengine.library.settings import (
    default_project_settings,
    partition_case,
    seismic_weight_rule,
)

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
    # Area loads: floor finish as SD, live as L below the roof, Lr on it; the partition
    # allowance in SD or L as the code pack says (L in the default pack), in a pattern PART of
    # its own as it counts in the seismic weight in full (owner decision 2026-11-03: partitions
    # in full in W, Sec 2.5.7.3), in the mass source x1 and combined as L.
    floor, roof = settings_loads()
    settings = default_project_settings("Tiny")
    partitions = {a.id: a for a in settings.areaLoads}[settings.floorLoad].partitions
    assert f'LC "SD"  FVAL {floor[0]:g}' in text
    assert f'LC "L"  FVAL {floor[1] - partitions:g}' in text
    assert f'LC "PART"  FVAL {partitions:g}' in text
    assert 'MASSSOURCELOAD  "MsSrc1"  "PART"  1' in text
    assert 'MASSSOURCELOAD  "MsSrc1"  "L"  0.25' in text
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
    case = partition_case(settings)
    return (
        (floor.superimposed(case), floor.floor_live(case)),
        (roof.superimposed(case), roof.live),
    )


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


def sample_parts(folder: Path) -> tuple[Any, Any, Any, Any]:
    """The BIM, objects, materials and settings of the project folder ``folder``."""

    def text(part: str) -> str:
        return (folder / part).read_text(encoding="utf-8")

    return (
        BuildingModel.model_validate_json(text("06 BIM/bim.json")),
        ObjectLibrary.model_validate_json(text("04 Objects/objects.json")),
        MaterialLibrary.model_validate_json(text("03 Materials/materials.json")),
        ProjectSettings.model_validate_json(text("02 Project Settings/project-settings.json")),
    )


def seismic_w_v(building: Any, objects: Any, materials: Any, settings: Any) -> tuple[float, float]:
    """The seismic weight W and the static base shear V [kN] of the derived analysis model."""
    from saengine.fem.derive import derive_fem

    d = derive_fem(building, objects, materials, settings, {"bim": "x"})
    return d.summary["seismicWeight"]["total_kN"], d.summary["base_shear_kN"]


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
    case = partition_case(settings)
    rule = seismic_weight_rule(settings).partitions
    if rule.separate:
        # The partition allowance's own pattern (PART) comes back as the area load's
        # partitions (owner decision 2026-11-03), its mass-source share as the setting.
        assert imported_loads["FL"].finish == pytest.approx(floor.finish)
        assert imported_loads["FL"].live == pytest.approx(floor.live)
        assert imported_loads["FL"].partitions == pytest.approx(floor.partitions)
        back = seismic_weight_rule(imported.settings).partitions
        assert (back.mode, back.share(), back.case) == (rule.mode, rule.share(), rule.case)
    else:
        assert imported_loads["FL"].finish == pytest.approx(floor.superimposed(case))
        assert imported_loads["FL"].live == pytest.approx(floor.floor_live(case))
    # Every load of the project went into the file.
    assert not any(export_report.not_carried.values())

    # Combinations: the same factors on the same cases.
    def factors(c: Any) -> tuple:
        return tuple(round(getattr(c, k), 6) for k in ("D", "L", "Lr", "WX", "WY", "EX", "EY"))

    # The file's combinations that are the code pack's are kept once, as the pack's (OI-4):
    # every combination of the project is there, none twice.
    imported_combinations = imported.settings.combinations
    assert {factors(c) for c in imported_combinations} >= {
        factors(c) for c in settings.combinations
    }
    assert len({factors(c) for c in imported_combinations}) == len(imported_combinations)


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
    # Slabs as loads to the beams go out as membrane floors and come back as such.
    assert settings.analysis.slabs == imported.settings.analysis.slabs == "loadsToBeams"


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
    # OI-3/OI-4 (walkthrough 3): what SAEngine wrote comes back. The MEP equipment's point
    # loads on the slab come back as 07 MEP equipment (nothing left out), the mass source the
    # file has (F x 1: SAEngine's W takes the contents in full) is not reported as different,
    # the wall openings come back in their wall, the opening reaching past the slab's corner
    # (O2) in its slab, and the slab live load is that of the net slab, as exported.
    report = imported.report
    assert not any(v for v in report.not_carried.values())
    # The partition pattern PART (in full in SAEngine's W) comes back as the area loads'
    # partition allowance, its mass share as the pack's (in full): the mass source no longer
    # differs (owner decision 2026-11-03: the import restores the partition allowance).
    approximated = report.to_dict()["approximated"]
    assert not [a for a in approximated if "mass source differs" in a["what"]]
    restored = [a for a in approximated if a["what"].startswith("partition patterns restored")]
    assert restored and restored[0]["examples"] == ["PART"]
    assert imported.settings.analysis.massSource.partitions == "pack"
    # W and V of the sample with the area loads and mass source read back are the original's
    # (on the sample's own geometry; the whole project read back: below).
    full, objects_full, materials, own = sample_parts(SAMPLE)
    original = seismic_w_v(full, objects_full, materials, own)
    back = {a.id: a for a in imported.settings.areaLoads}
    own.areaLoads = [back.get(a.id, a) for a in own.areaLoads]
    own.analysis.massSource = imported.settings.analysis.massSource
    own.analysis.partitionAllowanceCase = imported.settings.analysis.partitionAllowanceCase
    assert seismic_w_v(full, objects_full, materials, own) == pytest.approx(original, rel=1e-9)
    assert {o.host for o in imported.bim.additions.wallOpenings} == {"W1-Level-1"}
    assert sorted(o.width for o in imported.bim.additions.wallOpenings) == [900.0, 1000.0]
    assert "O2-Level-1" in {o.id for o in imported.bim.additions.slabOpenings}
    assert report.carried["L"] == pytest.approx(result.report.carried["L"], rel=1e-6)
    assert report.imported["equipment"] >= 4
    assert "07 MEP/mep.json" in imported.texts
    # The stair's reactions are in the file (OI-2): the top of its upper flight on beam B1.
    assert 'LINELOAD  "B1"' in result.text
    assert result.report.carried["D"] > 0


PROJECT_FILES = (
    "06 BIM/bim.json",
    "04 Objects/objects.json",
    "03 Materials/materials.json",
    "02 Project Settings/project-settings.json",
)
SIDE_FILES = (  # what the derivation reads beside the model (soil report: none in the e2k)
    "07 MEP/mep.json",
    "09 Substructure/substructure.json",
    "05 Floor Plan/loads.json",
    "05 Floor Plan/architecture.json",
)


def project_w_v(texts: dict[str, str], root: Path | None = None) -> tuple[float, float, dict]:
    """W, V [kN] and the analysis settings of the whole project of ``texts`` (as Run All
    derives it: MEP, member loads and the rest read beside the model)."""
    from saengine.codes import context as code_context
    from saengine.rpc.handlers import derive_fem

    with code_context.project(root):
        d = derive_fem(
            *(texts[f] for f in PROJECT_FILES), None, None, *(texts.get(f) for f in SIDE_FILES)
        )
    assert "problems" not in d, d.get("problems")
    summary = d["summary"]
    return summary["seismicWeight"]["total_kN"], summary["base_shear_kN"], d


@pytest.fixture(scope="module")
def sample_whole_round_trip(tmp_path_factory: Any) -> dict[str, Any]:
    original = {
        f: (SAMPLE / f).read_text(encoding="utf-8")
        for f in (*PROJECT_FILES, *SIDE_FILES)
        if (SAMPLE / f).exists()
    }
    result = export_e2k(SAMPLE, derive=False)
    imported = round_trip(result.text, tmp_path_factory.mktemp("e2k"))
    return {"original": original, "imported": imported}


def test_sample_whole_project_w_and_v_round_trip(sample_whole_round_trip: Any) -> None:
    """The Sample Frame read back from its e2k has the original's seismic weight W and base
    shear V: its shell slabs come back as shells (MODELINGTYPE ShellThin), their openings out of
    the loaded area. Before, the import made them slabs as loads to the beams, which loaded the
    whole panel through its openings: 54 m² of floor carried on 65 m², W 659 kN for 608 kN."""
    original, imported = sample_whole_round_trip["original"], sample_whole_round_trip["imported"]
    own = ProjectSettings.model_validate_json(original["02 Project Settings/project-settings.json"])
    assert own.analysis.slabs == "shells"
    assert imported.settings.analysis.slabs == "shells"
    w0, v0, d0 = project_w_v(original, SAMPLE)
    # The mesh size comes back from the areas' auto mesh (owner decision 2026-11-04): before,
    # the 500 mm default left W 1.05 kN (0.14 %) low on a plain round trip.
    assert own.analysis.meshSize == 250
    assert imported.settings.analysis.meshSize == own.analysis.meshSize
    w1, v1, d1 = project_w_v(dict(imported.texts))
    assert (w1, v1) == pytest.approx((w0, v0), rel=1e-6)

    # The partition allowance (1.2 kN/m² in full, W's parts kept to 1 N) on the same net floor:
    # 53.35 m² (65 m² of panels less the openings O1, O2 and the shaft SH1).
    def partitions(d: dict) -> float:
        return d["summary"]["seismicWeight"]["levels"][0]["parts_kN"]["partitions"]

    assert partitions(d1) == pytest.approx(partitions(d0), rel=1e-9)
    assert partitions(d1) / 1.2 == pytest.approx(65.0 - 2.6 * 4.14 - 0.5**2 - 0.8**2, abs=1e-3)

    # W's dead and superimposed dead parts come back apart: the stairs' self-weight (written as
    # frame loads of the Dead pattern) stays D. Before, every dead frame load came back SD (D
    # about 13.9 kN lower, SD 12.8 kN higher).
    def parts(d: dict, part: str) -> float:
        return sum(
            level["parts_kN"].get(part, 0.0) for level in d["summary"]["seismicWeight"]["levels"]
        )

    for part in ("D", "SD"):
        assert parts(d1, part) == pytest.approx(parts(d0, part), rel=1e-4, abs=0.05), part


def test_slabs_as_loads_to_beams_leave_the_openings_out() -> None:
    """Slabs as loads to the beams carry the area loads of their net area, as shell slabs do:
    the Sample Frame's W and V are the same either way (O1 and O2 take 36.7 % of S1)."""
    building, objects, materials, settings = sample_parts(SAMPLE)
    shells = seismic_w_v(building, objects, materials, settings)
    settings.analysis.slabs = "loadsToBeams"
    to_beams = seismic_w_v(building, objects, materials, settings)
    assert to_beams == pytest.approx(shells, rel=1e-9)


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
    # The whole project read back has the original's seismic weight W and static base shear V
    # (the partition allowance restored in full, owner decision 2026-11-03; the site and
    # seismic settings, which the e2k does not carry, the original's).
    original = seismic_w_v(*sample_parts(folder))
    again = imported.settings.model_copy(deep=True)
    again.site, again.seismic = settings.site, settings.seismic
    w_v = seismic_w_v(imported.bim, imported.objects, imported.materials, again)
    assert w_v == pytest.approx(original, rel=1e-6)


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
    # at 2.0 kN/m²), and the overhead tank's water as F. Since the owner decision of 2026-11-02
    # (635b7040) the partition allowance is live load too: the sample's floors add 1.2 kN/m²
    # (the code minimum, BNBC 2020 Part 6 Sec 2.3.6) on their 53.346 m², 107.012 + 64.015.
    # Since walkthrough 3 (OI-2) the stair's reactions are exported too: the top of ST1's upper
    # flight on beam B1, its live load 4.8 kN/m² giving 9.943 kN/m over the 1.2 m flight width
    # (11.932 kN; the rest of the stair stands on the ground at the base).
    assert math.isclose(report["loads"]["exportedKN"]["L"], 171.027 + 11.932, rel_tol=1e-4)
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

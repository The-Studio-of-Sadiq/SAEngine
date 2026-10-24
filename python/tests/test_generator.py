"""The building generator (:mod:`saengine.library.generator`): a whole building in one step."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.library import FloorPlan, MaterialLibrary, ObjectLibrary
from saengine.library.bim import generate
from saengine.library.generator import (
    BuildingSpec,
    building_texts,
    flat_divisor,
    generate_building,
    write_building,
)
from saengine.library.settings import LoadCombination, ProjectSettings
from saengine.library.substructure import Substructure

GAMMA = 2400 * 9.80665 / 1000  # kN/m³ of C24.1
SPEC = {
    "name": "Ten storeys",
    "gridsX": [6000, 6000, 6000],
    "gridsY": [5000, 5000],
    "storyCount": 10,
    "groundHeight": 3500,
    "typicalHeight": 3000,
}


@pytest.fixture(scope="module")
def frame() -> dict:
    return generate_building(SPEC)


def parts(result: dict) -> tuple[FloorPlan, ObjectLibrary, MaterialLibrary, ProjectSettings]:
    return (
        FloorPlan.model_validate(result["floorPlan"]),
        ObjectLibrary.model_validate(result["objects"]),
        MaterialLibrary.model_validate(result["materials"]),
        ProjectSettings.model_validate(result["settings"]),
    )


def types(result: dict) -> dict:
    return {o["id"]: o for o in result["objects"]["objects"]}


def test_three_by_two_bays_ten_storeys_validates_and_counts(frame: dict) -> None:
    plan, objects, materials, settings = parts(frame)
    Substructure.model_validate(frame["substructure"])
    assert plan.check_objects(objects) == []
    assert objects.check_materials(materials) == []
    # 4 x 3 grid points, one column per storey: 12 x 10.
    assert len(plan.columns) == 120
    # Per floor 3 Y lines x 3 spans + 4 X lines x 2 spans = 17 beams; 10 floors.
    assert len(plan.beams) == 170
    # One slab per bay (3 x 2) per floor.
    assert len(plan.slabs) == 60
    assert plan.walls == [] and plan.footings == []
    assert len(frame["substructure"]["foundations"]) == 12
    assert [g.label for g in plan.grids.x] == ["A", "B", "C", "D"]
    assert [g.position for g in plan.grids.y] == [0, 5000, 10000]
    assert [s.elevation for s in plan.stories] == [0, 3500] + [
        3500 + 3000 * k for k in range(1, 10)
    ]
    # Columns run from the base to the roof storey by storey.
    a1 = [c for c in plan.columns if (c.at.x, c.at.y) == ("A", "1")]
    assert [(c.base, c.top) for c in a1] == [
        (b.id, t.id) for b, t in zip(plan.stories, plan.stories[1:], strict=False)
    ]
    # Dhaka, site class SD, category II: Seismic Design Category D, special moment frames.
    assert frame["summary"]["sdc"] == "D"
    assert settings.seismic.system == "rcSmf"
    assert frame["settingsPatch"]["seismic"] == {"system": "rcSmf"}


def test_typical_floors_are_similar_within_column_groups(frame: dict) -> None:
    plan, *_ = parts(frame)
    similar = {s.id: s.similarTo for s in plan.stories}
    # Column groups L1-L3, L4-L6, L7-L8, L9-L10; L1 (the first suspended floor) stays its own.
    assert similar == {
        "BASE": None,
        "L1": None,
        "L2": None,
        "L3": "L2",
        "L4": None,
        "L5": "L4",
        "L6": "L4",
        "L7": None,
        "L8": "L7",
        "L9": None,
        "L10": "L9",
    }

    # Every similar story has the master's plan: same places and types (as floorPlanTypical.ts
    # compares them).
    def plan_of(story: str) -> list[tuple]:
        def key(member_id: str) -> str:
            return member_id.rsplit("-", 1)[0]

        return sorted(
            [("c", key(c.id), c.type) for c in plan.columns if c.top == story]
            + [("b", key(b.id), b.type) for b in plan.beams if b.story == story]
            + [("s", key(s.id), s.type) for s in plan.slabs if s.story == story]
        )

    for story, master in similar.items():
        if master:
            assert plan_of(story) == plan_of(master)
    assert plan_of("L2") != plan_of("L4")
    assert not generate_building({**SPEC, "typical": False})["summary"]["families"]


def test_beam_sizes_by_hand(frame: dict) -> None:
    beam = {b.id: b.type for b in parts(frame)[0].beams}
    # 6 m spans: span/15 = 400 governs Table 6.6.1 (l/18.5 = 324, l/21 = 286); b = max(250,
    # 0.3 x 400 = 120) = 250.
    assert beam["B-A1-B1-L1"] == beam["B-B1-C1-L1"] == "B250x400"
    # 5 m spans: 5000/15 = 333 -> 350.
    assert beam["B-A1-A2-L1"] == "B250x350"
    # Deflection minimum only: end span 6000/18.5 = 324.3 -> 325; interior 6000/21 = 285.7 ->
    # the 300 mm floor; 5 m end spans 270 -> 300.
    table = {
        b["id"]: b["type"]
        for b in generate_building({**SPEC, "beamSpanDepth": None})["floorPlan"]["beams"]
    }
    assert table["B-A1-B1-L1"] == "B250x325"
    assert table["B-B1-C1-L1"] == "B250x300"
    assert table["B-A1-A2-L1"] == "B250x300"
    # fy 500: Table 6.6.1 note (b) x (0.4 + 500/700) = 1.114: 6000/18.5 x 1.114 = 361 -> 375.
    b500 = generate_building({**SPEC, "beamSpanDepth": None, "rebar": "B500DWR"})
    assert {b["id"]: b["type"] for b in b500["floorPlan"]["beams"]}["B-A1-B1-L1"] == "B250x375"


def test_slab_thickness_by_hand(frame: dict) -> None:
    slab = {s.id: s.type for s in parts(frame)[0].slabs}
    # Corner panel A1: 6000 x 5000, beams 250 wide: ln = 5750, beta = 5750/4750 = 1.21. At
    # h = 200: alpha_f = Ib / Is with Ib = b h^3/12 and Is over the strip each beam carries:
    # 250x400 on the edge (strip 2500): 1.333e9 / (2500 x 6.667e5) = 0.80; inside (5000): 0.40;
    # 250x350 on the edge (3000): 8.93e8 / (3000 x 6.667e5) = 0.45; inside (6000): 0.22.
    # alpha_fm = 0.47: eq. 6.6.5 h = 5750 (0.8 + 420/1400) / (36 + 5 x 1.21 x 0.27) = 168 mm,
    # x 1.1 for the 0.45 edge beam (6.2.5.3.3(d)) = 185 -> 200.
    ln, beta = 5750, 5750 / 4750
    afm = (0.8 + 0.4 + 8.932e8 / (3000 * 200**3 / 12) + 8.932e8 / (6000 * 200**3 / 12)) / 4
    h = ln * (0.8 + 420 / 1400) / (36 + 5 * beta * (afm - 0.2)) * 1.1
    assert h == pytest.approx(185, abs=1)
    assert slab["S-A1-L1"] == "S200"
    assert types(frame)["S200"]["system"] == "twoWay"
    # The middle panel B1 has beams on both long sides inside the building: 175.
    assert slab["S-B1-L1"] == "S175"


def test_column_size_by_hand(frame: dict) -> None:
    plan, *_ = parts(frame)
    column = {c.id: c.type for c in plan.columns}
    # Interior column B2 at L1: 4 quarter panels of 7.5 m² (two 200 mm, two 175 mm slabs).
    slab = 7.5 * (0.2 + 0.175 + 0.2 + 0.175) * GAMMA
    # Beams below the thinnest slab (175): 2 x 3 m of 250x400 and 2 x 2.5 m of 250x350.
    beams = (2 * 3 * 0.25 * (0.4 - 0.175) + 2 * 2.5 * 0.25 * (0.35 - 0.175)) * GAMMA
    floor = slab + 30 * (1.2 + 1.0 + 2.0) + beams  # finish, partitions, residential live
    roof = slab + 30 * (1.5 + 1.0) + beams
    # Its own weight: 550 (L1-L3), 450 (L4-L6), 350 (L7-L8), 300 (L9-L10).
    own = (0.55**2 * 9.5 + 0.45**2 * 9 + 0.35**2 * 6 + 0.3**2 * 6) * GAMMA
    p = 9 * floor + roof + own
    assert p == pytest.approx(2804, abs=2)
    # Ag = P / (0.4 f'c), interior k = 1.0: sqrt(2804e3 / 9.64) = 539 -> 550.
    side = math.ceil(math.sqrt(p * 1000 / (0.4 * 24.1)) / 50) * 50
    assert side == 550
    assert column["C-B2-L1"] == column["C-C2-L3"] == "C550x550"
    # Corner columns of the top group: the 300 mm least dimension of Sec 8.3.5.1(a).
    assert column["C-A1-L10"] == "C300x300"
    # Never larger above than below.
    sizes = [types(frame)[column[f"C-B2-L{k}"]]["profile"]["xDim"] for k in range(1, 11)]
    assert sizes == sorted(sizes, reverse=True)


def test_isolated_footing_by_hand(frame: dict) -> None:
    footing = {f["id"]: f for f in frame["substructure"]["foundations"]}["F-B2"]
    assert footing["columns"] == ["C-B2-L1"]
    assert footing["center"] == [6000, 5000]
    # Service load 2804 kN (above), qa 100 kPa: sqrt(1.1 x 2804 / 100) = 5.55 m -> 5600;
    # thickness 5600 / 4 = 1400.
    assert (footing["length"], footing["width"], footing["thickness"]) == (5600, 5600, 1400)


def test_flat_slab_variant() -> None:
    result = generate_building({**SPEC, "system": "flatSlab"})
    plan, objects, _, settings = parts(result)
    assert plan.beams == []
    assert len(plan.slabs) == 60
    slab_types = {o.id: o for o in objects.objects if o.kind == "slab"}
    assert list(slab_types) == ["S200-FP"]
    assert slab_types["S200-FP"].system == "flat"
    # Table 6.6.3: exterior panel without edge beams ln/30 at fy 420; ln = 6000 - 300 (the
    # smallest columns) = 5700 -> 190 -> 200 mm.
    assert flat_divisor(420, 0) == 30
    assert flat_divisor(350, 2) == pytest.approx(1 / (0.5 / 36 + 0.5 / 33))
    # Category D: a flat plate frame is no special moment frame, so core walls are added round
    # the middle bay (B2-C3) and the system is a building frame with special walls.
    assert settings.seismic.system == "rcSpecialWallFrame"
    assert len(plan.walls) == 4 * 10
    assert {(w.start.x, w.start.y, w.end.x, w.end.y) for w in plan.walls if w.top == "L1"} == {
        ("B", "2", "C", "2"),
        ("B", "3", "C", "3"),
        ("B", "2", "B", "3"),
        ("C", "2", "C", "3"),
    }
    # In Category C (Rajshahi, zone 1, site class SD) the frame alone is enough (IMF).
    c = generate_building({**SPEC, "system": "flatSlab", "location": "rajshahi"})
    assert (c["summary"]["sdc"], c["settings"]["seismic"]["system"]) == ("C", "rcImf")
    assert c["floorPlan"]["walls"] == []


def test_frame_with_core_walls_and_mat() -> None:
    result = generate_building(
        {
            **SPEC,
            "system": "rcFrameWithWalls",
            "coreBay": {"x": "A", "y": "1"},
            "footing": "mat",
            "occupancy": "office",
        }
    )
    plan = parts(result)[0]
    assert result["settings"]["seismic"]["system"] == "rcDualSpecial"
    # The core's four sides carry walls instead of beams: 17 - 4 = 13 beams a floor.
    assert len(plan.beams) == 130 and len(plan.walls) == 40
    assert not any(b.id.startswith("B-A1-B1-") for b in plan.beams)
    mat = result["substructure"]["foundations"]
    assert len(mat) == 1 and mat[0]["type"] == "raft" and mat[0]["thickness"] == 1000
    assert mat[0]["outline"][0] == [-1000, -1000] and mat[0]["outline"][2] == [19000, 11000]
    # Office: the floor area load takes the office live load (Table 6.2.3, 2.4 kN/m²).
    floor = next(a for a in result["settings"]["areaLoads"] if a["id"] == "FL")
    assert (floor["use"], floor["live"]) == ("office", 2.4)


def test_occupancy_category_default_by_use_and_explicit() -> None:
    small = {"gridsX": [6000] * 3, "gridsY": [5000] * 2, "storyCount": 5, "location": "rajshahi"}
    # Health care without a category: IV assumed (Table 6.1.1), so Rajshahi SD gives
    # Category D: special moment frames and the 300 mm column minimum.
    hospital = generate_building({**small, "occupancy": "healthcare"})
    assert hospital["settings"]["occupancy"] == {"use": "healthcare", "category": "IV"}
    assert (hospital["summary"]["sdc"], hospital["settings"]["seismic"]["system"]) == (
        "D",
        "rcSmf",
    )
    sides = [o["profile"]["xDim"] for o in hospital["objects"]["objects"] if o["kind"] == "column"]
    assert min(sides) >= 300
    assert any("Occupancy category IV assumed" in n for n in hospital["notes"])
    # Given explicitly: used as given, no assumption note.
    given = generate_building({**small, "occupancy": "healthcare", "occupancyCategory": "II"})
    assert given["settings"]["occupancy"]["category"] == "II"
    assert given["summary"]["sdc"] == "C"
    assert not any("assumed for" in n for n in given["notes"])
    # Schools III; residential II, noted as assumed; never below the settings' own category.
    school = generate_building({**small, "occupancy": "educational"})
    assert school["settings"]["occupancy"]["category"] == "III"
    home = generate_building(small)
    assert home["settings"]["occupancy"]["category"] == "II"
    assert any("Occupancy category II assumed" in n for n in home["notes"])
    kept = generate_building(small, settings=hospital["settings"])
    assert kept["settings"]["occupancy"]["category"] == "IV"


def check_references(result: dict) -> None:
    """Every foundation reference resolves against 6 BIM (walls only on strips)."""
    from saengine.library.substructure import check

    bim = generate(parts(result)[0], "s")
    sub = Substructure.model_validate(result["substructure"])
    assert check(sub, bim, MaterialLibrary.model_validate(result["materials"])) == []


def test_core_walls_get_strip_footings() -> None:
    result = generate_building({**SPEC, "storyCount": 4, "system": "rcFrameWithWalls"})
    plan = parts(result)[0]
    found = {f["id"]: f for f in result["substructure"]["foundations"]}
    # Core bay B2-C3: its four columns move from isolated footings onto the core strips.
    assert not {"F-B2", "F-C2", "F-B3", "F-C3"} & set(found)
    assert sum(f["type"] == "isolated" for f in found.values()) == 8
    strips = {k: f for k, f in found.items() if f["type"] == "strip"}
    assert set(strips) == {"F-B2-B3", "F-C2-C3", "F-B2-C2", "F-B3-C3"}
    carried = {c for f in found.values() for c in f["columns"]}
    assert {w.id for w in plan.walls if w.base == "BASE"} <= carried
    assert {"C-B2-L1", "C-B3-L1"} <= set(strips["F-B2-B3"]["columns"])
    check_references(result)
    # Y strip on line B by hand: P = two core columns + the wall (200 x 5000 x 12500 mm);
    # B^2 + 5000 B = 1.1 P / qa, rounded up to 100 mm; the path extends B/2 past the columns.
    wall = 0.2 * 5.0 * 12.5 * GAMMA
    p = float(strips["F-B2-B3"]["note"].split("load ")[1].split(" kN")[0])  # rounded to 1 kN
    assert p > wall

    def width(load: float) -> float:
        area = 1.1 * load / 100 * 1e6
        return math.ceil((-5000 + math.sqrt(5000**2 + 4 * area)) / 2 / 100) * 100

    b = strips["F-B2-B3"]["width"]
    assert b in (width(p - 0.5), width(p + 0.5))
    assert strips["F-B2-B3"]["path"] == [[6000, 5000 - b / 2], [6000, 10000 + b / 2]]
    # X strips lie between the Y strips, not over them; the X wall's weight 200 x 6000 x
    # 12500 mm over the strip's length.
    x_strip = strips["F-B2-C2"]
    x0, x1 = x_strip["path"][0][0], x_strip["path"][1][0]
    assert (x0, x1) == (6000 + b / 2, 12000 - b / 2)
    x_wall = 0.2 * 6.0 * 12.5 * GAMMA
    assert x_strip["width"] == max(600, math.ceil(1.1 * x_wall / 100 * 1e6 / (x1 - x0) / 100) * 100)
    assert any("OVERTURNING" in n for n in result["notes"])


def test_core_walls_get_a_core_raft_when_strips_would_fill_the_core() -> None:
    result = generate_building({**SPEC, "system": "rcFrameWithWalls"})
    found = {f["id"]: f for f in result["substructure"]["foundations"]}
    assert not any(f["type"] == "strip" for f in found.values())
    raft = found["F-CORE"]
    assert raft["type"] == "raft" and raft["thickness"] == 1000
    assert raft["columns"] == ["C-B2-L1", "C-B3-L1", "C-C2-L1", "C-C3-L1"]
    # The outline covers every core wall.
    (x0, y0), _, (x1, y1), _ = raft["outline"]
    assert x0 < 6000 and x1 > 12000 and y0 < 5000 and y1 > 10000
    check_references(result)
    assert any("F-CORE" in n and "OVERTURNING" in n for n in result["notes"])
    # No foundations at all: the notes ask for the core's own foundation; a mat: its note.
    none = generate_building({**SPEC, "system": "rcFrameWithWalls", "footing": "none"})
    assert any("core walls need their own foundation" in n for n in none["notes"])
    mat = generate_building({**SPEC, "system": "rcFrameWithWalls", "footing": "mat"})
    assert any("Core walls stand on the mat" in n for n in mat["notes"])


def test_summary_lists_only_placed_beam_types() -> None:
    one_bay = generate_building(
        {"gridsX": [6000], "gridsY": [6000], "storyCount": 3, "system": "rcFrameWithWalls"}
    )
    assert one_bay["summary"]["counts"]["beams"] == 0
    assert one_bay["summary"]["beamTypes"] == []
    frame = generate_building({**SPEC, "storyCount": 2})
    placed = {b["type"] for b in frame["floorPlan"]["beams"]}
    assert frame["summary"]["beamTypes"] == sorted(placed)


def test_steel_free_by_default_and_template_bars_on_request(frame: dict) -> None:
    assert all("reinforcement" not in o for o in frame["objects"]["objects"])
    barred = generate_building({**SPEC, "storyCount": 2, "reinforcement": True})
    objects = ObjectLibrary.model_validate(barred["objects"])
    assert all(o.reinforcement is not None for o in objects.objects)
    assert {o.reinforcement.material for o in objects.objects} == {"B420DWR"}


def test_spec_errors() -> None:
    with pytest.raises(ValueError, match="storyCount"):
        BuildingSpec.model_validate({"gridsX": [6000], "gridsY": [5000]})
    with pytest.raises(ValueError, match="not a concrete"):
        generate_building({**SPEC, "concrete": "B420DWR"})
    with pytest.raises(ValueError, match="core bay"):
        generate_building({**SPEC, "system": "rcFrameWithWalls", "coreBay": {"x": "D", "y": "1"}})
    named = generate_building(
        {
            "gridsX": [5000],
            "gridsY": [4000],
            "stories": [{"name": "First", "height": 3200}, {"name": "Roof", "height": 2800}],
        }
    )
    assert [s["name"] for s in named["floorPlan"]["stories"]] == ["Base", "First", "Roof"]
    assert named["floorPlan"]["stories"][-1]["elevation"] == 6000


def test_write_building(tmp_path: Path) -> None:
    result = generate_building({**SPEC, "storyCount": 3})
    written = write_building(result, tmp_path)
    names = {p.relative_to(tmp_path).as_posix() for p in written}
    assert "05 Floor Plan/floor-plan.json" in names and "06 BIM/bim.json" in names
    assert "09 Substructure/substructure.json" in names and "Ten storeys.saengine" in names
    bim = json.loads((tmp_path / "06 BIM" / "bim.json").read_text(encoding="utf-8"))
    assert len(bim["elements"]) == 12 * 3 + 17 * 3 + 6 * 3
    assert set(building_texts(result)) <= names


# ───────────────────────────────── analysis of a generated building ─────────────────────────────


def applied(project: dict, name: str) -> np.ndarray:
    """Total applied force of a pattern, element loads turned back to global axes."""
    coords = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
    elements = {e["id"]: e for e in project["elements"]}
    pattern = next(p for p in project["load_patterns"] if p["name"] == name)
    total = sum((np.array(n["forces"][:3]) for n in pattern["nodal_loads"]), np.zeros(3))
    for load in pattern["element_loads"]:
        a, b = (coords[n] for n in elements[load["element_id"]]["nodes"])
        x = (b - a) / np.linalg.norm(b - a)
        vecxz = np.array([1.0, 0, 0]) if abs(x[2]) > abs(x[0]) else np.array([0, 0, 1.0])
        y = np.cross(vecxz, x)
        y /= np.linalg.norm(y)
        total = total + (
            load["wx"] * x + load["wy"] * y + load["wz"] * np.cross(x, y)
        ) * np.linalg.norm(b - a)
    return total


def test_generated_building_analyses_and_reactions_balance_gravity(tmp_path: Path) -> None:
    from saengine.fem.combinations import combination_results
    from saengine.fem.derive import derive_fem

    result = generate_building(
        {"gridsX": [6000, 5000], "gridsY": [5000], "storyCount": 3, "footing": "none"}
    )
    plan, objects, materials, settings = parts(result)
    settings = settings.model_copy(update={"combinations": [LoadCombination(name="D", D=1.0)]})
    d = derive_fem(generate(plan, "s"), objects, materials, settings)
    # Superimposed dead load by hand: 2 floors x 55 m² x (1.2 + 1.0) + the roof 55 m² x 1.5.
    sd = applied(d.project, "SD")[2]
    assert -sd / 1000 == pytest.approx(2 * 55 * 2.2 + 55 * 1.5, rel=1e-6)
    model = tmp_path / "08 FEM" / "model.osmodel"
    model.parent.mkdir()
    model.write_text(json.dumps(d.project), encoding="utf-8")
    out = tmp_path / "08 FEM" / "model.results"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            "1",
            "2",
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    entries = {e["caseName"]: e for e in combination_results(out, d.project, settings)}
    reaction = entries["D"]["tables"][0]["rows"][-1][3]
    gravity = -(applied(d.project, "D")[2] + sd)
    assert reaction == pytest.approx(gravity, rel=0.005)


def test_gravity_only_columns_are_flagged_in_category_c_and_d() -> None:
    """Review: the default Dhaka building is Category D with gravity-only column sizes; the
    notes must say so first."""
    small = {"gridsX": [6000] * 3, "gridsY": [5000] * 2, "storyCount": 6}
    for extra in ({}, {"location": "rajshahi", "occupancy": "healthcare"}):
        result = generate_building({**small, **extra})
        sdc = result["summary"]["sdc"]
        warned = result["notes"][0].startswith(f"WARNING - Seismic Design Category {sdc}")
        assert warned == (sdc in ("C", "D"))
        if sdc == "D":
            assert "GRAVITY ONLY" in result["notes"][0]
    assert generate_building(small)["summary"]["sdc"] == "D"  # the wizard's default case

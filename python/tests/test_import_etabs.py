"""Import of ETABS text models (.e2k) into a SAEngine project.

The model files are synthetic, written by hand for these tests (tests/data/import).
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from saengine.importers.common import Units, bar_diameter
from saengine.importers.etabs import read_e2k
from saengine.library import (
    BuildingModel,
    FloorPlan,
    MaterialLibrary,
    ObjectLibrary,
    ProjectSettings,
)

DATA = Path(__file__).parent / "data" / "import"
FRAME = DATA / "two_story_frame.e2k"

# The synthetic frame: grids A-B-C at 0, 6, 12 m and 1-2 at 0, 5 m; stories at 3.5 and 6.7 m;
# 400x400 columns, 300x500 beams, 150 mm slabs, one 200 mm wall on grid C below Story1, one
# HSS 150x150x8 brace in bay A-B of grid 1.
CONCRETE_WEIGHT = 23.53596  # kN/m³
STEEL_WEIGHT = 76.98220
CONCRETE_VOLUME = (
    6 * 0.4 * 0.4 * (3.5 + 3.2)  # columns
    + 2 * (4 * 6 + 3 * 5) * 0.3 * 0.5  # beams of both floors
    + 2 * 12 * 5 * 0.15  # slabs
    + 5 * 3.5 * 0.2  # wall
)
BRACE = (0.15**2 - 0.134**2) * math.hypot(6, 3.5) * STEEL_WEIGHT
SELF_WEIGHT = CONCRETE_VOLUME * CONCRETE_WEIGHT + BRACE  # kN
SDL, LIVE, ROOF_LIVE = 1.5 * 120, 2.0 * 60, 1.0 * 60  # kN: per m² times the slab areas


def test_units_and_bar_sizes() -> None:
    u = Units.parse("KIP", "IN")
    assert u.to_mm(1) == pytest.approx(25.4)
    assert u.to_mpa(1) == pytest.approx(6.894757, rel=1e-6)  # ksi
    assert Units.parse("KN", "M").to_kpa(2.5) == pytest.approx(2.5)
    assert Units.parse("LB", "FT").to_kpa(100) == pytest.approx(4.788026, rel=1e-6)  # 100 psf
    assert Units.parse("TONF", "M").to_kn_per_m(1) == pytest.approx(9.80665)
    assert Units.parse("KN", "M").to_density(23.53596) == pytest.approx(2400, rel=1e-6)
    assert [bar_diameter(s) for s in ("#9", "20d", "T16", "16mm", "20M", "xx")] == [
        28.65,
        20,
        16,
        16,
        19.5,
        None,
    ]


def test_frame_imports_into_valid_parts(tmp_path: Path) -> None:
    project = read_e2k(FRAME)
    assert project.problems() == []
    written = project.write(tmp_path)
    assert any(p.suffix == ".saengine" for p in written)

    def load(relative: str) -> dict:
        return json.loads((tmp_path / relative).read_text(encoding="utf-8"))

    # Every part validates with SAEngine's own models.
    settings = ProjectSettings.model_validate(load("02 Project Settings/project-settings.json"))
    materials = MaterialLibrary.model_validate(load("03 Materials/materials.json"))
    objects = ObjectLibrary.model_validate(load("04 Objects/objects.json"))
    plan = FloorPlan.model_validate(load("05 Floor Plan/floor-plan.json"))
    bim = BuildingModel.model_validate(load("06 BIM/bim.json"))
    assert objects.check_materials(materials) == []
    assert plan.check_objects(objects) == [] and bim.check_objects(objects) == []

    assert [(s.id, s.elevation) for s in plan.stories] == [
        ("Base", 0),
        ("Story1", 3500),
        ("Story2", 6700),
    ]
    assert [(g.label, g.position) for g in plan.grids.x] == [("A", 0), ("B", 6000), ("C", 12000)]
    assert (len(plan.columns), len(plan.beams), len(plan.slabs), len(plan.walls)) == (12, 14, 4, 1)
    wall = plan.walls[0]
    assert (wall.base, wall.top, wall.start.x, wall.end.x) == ("Base", "Story1", "C", "C")
    brace = bim.additions.members[0]
    # Released in bending at both ends: a steel brace with a simple (gusset) connection.
    assert (brace.type, brace.z1, brace.x2, brace.z2) == ("HSS150x8-pinned", 0, 6000, 3500)

    concrete = materials.get("C25")
    assert concrete.concrete.fc == pytest.approx(25)
    assert concrete.mechanical.E == pytest.approx(23500)
    assert concrete.mechanical.density == pytest.approx(2400, rel=1e-6)
    steel = materials.get("A992Fy50")
    assert (steel.category.value, steel.steel.fy, steel.steel.fu) == ("steel", 345, 450)
    assert materials.get("B420").category.value == "rebar"

    kinds = {o.id: o for o in objects.objects}
    column = kinds["C400"]
    assert column.kind == "column" and column.profile.xDim == 400
    bars = column.reinforcement
    assert (bars.material, bars.cover) == ("B420", 40)
    assert (bars.longitudinal[0].count, bars.longitudinal[0].dia) == (8, 20)
    assert (bars.transverse.dia, bars.transverse.spacing) == (10, 150)
    beam = kinds["B300x500"]
    assert (beam.profile.xDim, beam.profile.yDim, beam.reinforcement) == (300, 500, None)
    tube = kinds["HSS150x8-pinned"]
    assert (tube.kind, tube.profile.shape, tube.profile.wallThickness) == (
        "brace",
        "rectangleHollow",
        8,
    )
    assert tube.connection is not None and tube.connection.type == "gusset"
    assert (kinds["S150"].thickness, kinds["W200"].thickness) == (150, 200)

    loads = {a.id: a for a in settings.areaLoads}
    assert (loads["FL"].finish, loads["FL"].live) == (1.5, 2.0)
    assert (loads["RF"].finish, loads["RF"].live) == (1.5, 1.0)
    combos = {c.name: c for c in settings.combinations}
    assert set(combos) == {"U1", "U2", "U3"}  # U4 repeats U1; ENV is an envelope
    assert (combos["U1"].D, combos["U2"].D, combos["U2"].L, combos["U2"].Lr) == (1.4, 1.2, 1.6, 0.5)
    assert combos["U3"].EX == -1

    report = load("import-report.json")
    assert report["imported"]["braces"] == 1 and report["imported"]["supports"] == 6
    assert report["imported"]["stories"] == 2  # the base is a level, not a story
    skipped = {s["what"]: s for s in report["skipped"]}
    assert "sections named from a steel database that could not be read" in skipped
    assert "envelope, SRSS and absolute combinations" in skipped
    # The frame load (10 kN/m over 6 m) and the point load (20 kN) are member loads now.
    assert report["loads"]["notCarriedKN"] == {}
    assert report["loads"]["carriedKN"] == {"D": SDL + 60, "L": LIVE + 20, "Lr": ROOF_LIVE}
    assert (report["imported"]["memberLineLoads"], report["imported"]["memberPointLoads"]) == (1, 1)
    member_loads = load("05 Floor Plan/loads.json")["loads"]
    assert [(m["member"], m["kind"], m["case"], m["value"]) for m in member_loads] == [
        ("B3-Story1", "line", "SD", 10),
        ("C5-Story2", "point", "L", 20),
    ]
    approximated = {a["what"] for a in report["approximated"]}
    assert any(a.startswith("pinned steel beams and braces as simple") for a in approximated)
    assert "axial, shear and torsion releases not expressed" in approximated  # TI


def test_section_lookup_and_kip_inch_units() -> None:
    text = FRAME.read_text(encoding="utf-8")
    profile = {
        "shape": "I",
        "overallWidth": 368.8,
        "overallDepth": 356.1,
        "webThickness": 11.2,
        "flangeThickness": 18.0,
    }
    project = read_e2k(
        FRAME,
        section_lookup=lambda name: profile if name == "W14X90" else None,
        text=text.replace('"D1"  "Story1"  SECTION "HSS150x8"', '"D1"  "Story1"  SECTION "W14X90"'),
    )
    brace = next(o for o in project.objects.objects if o.kind == "brace")
    assert brace.profile.shape == "I" and brace.profile.overallDepth == 356.1

    # The same frame's first story in kip and inch: 1 m = 39.37 in, 1 kN/m² = 0.0208854 ksf.
    small = """
$ CONTROLS
  UNITS  "KIP"  "IN"  "F"
$ STORIES - IN SEQUENCE FROM TOP
  STORY "L1"  HEIGHT 144
  STORY "Base"  ELEV 0
$ MATERIAL PROPERTIES
  MATERIAL  "4000Psi"  TYPE "Concrete"  WEIGHTPERVOLUME 8.68055555555556E-05
  MATERIAL  "4000Psi"  SYMTYPE "Isotropic"  E 3604.9965  U 0.2  A 0.0000055
  MATERIAL  "4000Psi"  FC 4
$ FRAME SECTIONS
  FRAMESECTION  "C24"  MATERIAL "4000Psi"  SHAPE "Concrete Rectangular"  D 24  B 18
$ SHELL PROPERTIES
  SHELLPROP  "Slab8"  PROPTYPE  "Slab"  MATERIAL "4000Psi"  SLABTHICKNESS 8
$ POINT COORDINATES
  POINT "1"  0  0
  POINT "2"  240  0
  POINT "3"  240  240
  POINT "4"  0  240
$ LINE CONNECTIVITIES
  LINE  "C1"  COLUMN  "1"  "1"  1
  LINE  "B1"  BEAM  "1"  "2"  0
$ AREA CONNECTIVITIES
  AREA "F1"  FLOOR  4  "1"  "2"  "3"  "4"  0  0  0  0
$ LINE ASSIGNS
  LINEASSIGN  "C1"  "L1"  SECTION "C24"  ANG 90
  LINEASSIGN  "B1"  "L1"  SECTION "C24"
$ AREA ASSIGNS
  AREAASSIGN  "F1"  "L1"  SECTION "Slab8"
$ LOAD PATTERNS
  LOADPATTERN "Live"  TYPE  "Live"  SELFWEIGHT  0
$ SHELL OBJECT LOADS
  AREALOAD  "F1"  "L1"  TYPE "UNIFF"  DIR "GRAV"  LC "Live"  FVAL 0.000347222
"""
    project = read_e2k("small.e2k", text=small)
    concrete = project.materials.materials[0]
    assert concrete.concrete.fc == pytest.approx(27.579, rel=1e-4)  # 4 ksi
    assert concrete.mechanical.density == pytest.approx(2402.8, rel=1e-3)  # 150 pcf
    assert project.floor_plan.stories[1].elevation == pytest.approx(3657.6)
    column = next(o for o in project.objects.objects if o.kind == "column")
    beam = next(o for o in project.objects.objects if o.kind == "beam")
    # Depth (D) along the column's local 2 (global X at angle 0); a beam's depth is vertical.
    assert (column.profile.xDim, column.profile.yDim) == (609.6, 457.2)
    assert (beam.profile.xDim, beam.profile.yDim) == (457.2, 609.6)
    assert project.floor_plan.columns[0].rotation == 90
    assert next(o for o in project.objects.objects if o.kind == "slab").thickness == 203.2
    roof = next(a for a in project.settings.areaLoads if a.id == "RF")
    assert roof.live == pytest.approx(2.394, rel=1e-3)  # 50 psf
    assert any("roof live" in a["what"] for a in project.report.approximated)
    assert "supports" not in project.report.imported
    assert project.report.errors[0].startswith("The file has no supports")
    assert project.report.warnings[0].startswith("Error: The file has no supports")


def test_roof_live_in_live_pattern_keeps_its_factor() -> None:
    """A roof live load in the ordinary Live pattern goes to SAEngine's Lr case: the
    combinations give Lr the factor the file gave Live, so the roof load is not lost."""
    text = FRAME.read_text(encoding="utf-8").replace('LC "RLive"', 'LC "Live"')
    text = text.replace('  COMBO "U2"  LOAD "RLive"  SF 0.5\n', "")
    project = read_e2k(FRAME, text=text)
    combos = {c.name: (c.D, c.L, c.Lr) for c in project.settings.combinations}
    assert combos == {"U1": (1.4, 0, 0), "U2": (1.2, 1.6, 1.6), "U3": (1.2, 1.0, 1.0)}
    moved = next(a for a in project.report.approximated if a["what"].startswith("combination fa"))
    assert "U2: Lr 0 → 1.6" in moved["examples"]


def test_etabs_2013_combination_terms_and_response_spectrum() -> None:
    """ETABS 2013+ terms (LOADCASE / LOADCOMBO) and a response-spectrum term mapped to EX/EY."""
    text = FRAME.read_text(encoding="utf-8").replace('LOAD "', 'LOADCASE "')
    text = text.replace('COMBO "U4"  LOADCASE "U1"', 'COMBO "U4"  LOADCOMBO "U1"')
    text = text.replace(
        "$ LOAD COMBINATIONS\n",
        '  LOADCASE "RSX"  TYPE  "Response Spectrum"\n'
        '  LOADCASE "RSX"  ACCEL  "U1"  FUNC "BNBC"  SF 9.81\n'
        '  LOADCASE "RSX"  ACCEL  "U2"  FUNC "BNBC"  SF 2.943\n'
        '  LOADCASE "RSY"  TYPE  "Response Spectrum"\n'
        '  LOADCASE "RSY"  ACCEL  "U2"  FUNC "BNBC"  SF 9.81\n'
        "\n$ LOAD COMBINATIONS\n"
        '  COMBO "S1"  TYPE "Linear Add"\n'
        '  COMBO "S1"  LOADCASE "Dead"  SF 1.2\n'
        '  COMBO "S1"  LOADCASE "SDL"  SF 1.2\n'
        '  COMBO "S1"  LOADCASE "Live"  SF 1\n'
        '  COMBO "S1"  LOADCASE "RSX"  SF 1\n'
        '  COMBO "S2"  TYPE "Linear Add"\n'
        '  COMBO "S2"  LOADCASE "Dead"  SF 0.9\n'
        '  COMBO "S2"  LOADCASE "RSY"  SF -1\n',
    )
    project = read_e2k(FRAME, text=text)
    combos = {c.name: c for c in project.settings.combinations}
    assert set(combos) == {"U1", "U2", "U3", "S1", "S2"}  # U4 repeats U1 (nested LOADCOMBO)
    assert (combos["U2"].D, combos["U2"].L, combos["U2"].Lr) == (1.2, 1.6, 0.5)
    s1, s2 = combos["S1"], combos["S2"]
    assert (s1.D, s1.L, s1.EX, s1.EY) == (1.2, 1.0, 1.0, pytest.approx(0.3))
    assert (s2.D, s2.EX, s2.EY) == (0.9, 0, -1)
    approximated = {a["what"]: a for a in project.report.approximated}
    spectrum = next(v for k, v in approximated.items() if k.startswith("response-spectrum terms"))
    assert set(spectrum["examples"]) == {"RSX", "RSY"}
    assert "combinations with the same factors as another one dropped" in approximated
    assert not any("no SAEngine case" in s["what"] for s in project.report.skipped)


def test_imported_frame_analyses_with_its_loads(tmp_path: Path) -> None:
    """Round trip: import, derive the analysis model, run the gravity cases; the base reactions
    of the imported combination equal the factored loads of the source model."""
    from saengine.fem.combinations import combination_results
    from saengine.fem.derive import derive_fem

    project = read_e2k(FRAME)
    d = derive_fem(project.bim, project.objects, project.materials, project.settings, {"bim": "x"})
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
            "3",
            "4",
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    entries = {e["caseName"]: e for e in combination_results(out, d.project, project.settings)}
    reaction = entries["U2"]["tables"][0]["rows"][-1][3] / 1000  # kN, up
    expected = 1.2 * (SELF_WEIGHT + SDL) + 1.6 * LIVE + 0.5 * ROOF_LIVE
    assert reaction == pytest.approx(expected, rel=0.005)
    dead = entries["U1"]["tables"][0]["rows"][-1][3] / 1000
    assert dead == pytest.approx(1.4 * (SELF_WEIGHT + SDL), rel=0.005)


def test_older_format_without_grids() -> None:
    """Older e2k files: static load cases as the patterns, combinations by CASE; no grids (grid
    lines from the columns), a sloped beam, a pinned base, a floor opening."""
    text = """
$ CONTROLS
  UNITS  "KN"  "MM"  "C"
$ STORIES - IN SEQUENCE FROM TOP
  STORY "ROOF"  HEIGHT 3000
  STORY "BASE"  ELEV 0
$ MATERIAL PROPERTIES
  MATERIAL  "CONC"  M 2.4E-12  W 2.354E-08  TYPE "ISOTROPIC"  E 25  U 0.2  FC 0.025
$ FRAME SECTIONS
  FRAMESECTION  "COL"  MATERIAL "CONC"  SHAPE "Rectangular"  D 300  B 300
$ SHELL PROPERTIES
  SHELLPROP  "SLAB"  PROPTYPE  "Slab"  MATERIAL "CONC"  SLABTHICKNESS 125
$ POINT COORDINATES
  POINT "1"  0  0
  POINT "2"  4000  0
  POINT "3"  4000  3000
  POINT "4"  0  3000
  POINT "5"  1000  1000
  POINT "6"  2000  1000
  POINT "7"  2000  2000
  POINT "8"  1000  2000
$ LINE CONNECTIVITIES
  LINE  "C1"  COLUMN  "1"  "1"  1
  LINE  "C2"  COLUMN  "2"  "2"  1
  LINE  "C3"  COLUMN  "3"  "3"  1
  LINE  "C4"  COLUMN  "4"  "4"  1
  LINE  "B1"  BEAM  "1"  "2"  0
  LINE  "R1"  BRACE  "4"  "3"  1
$ AREA CONNECTIVITIES
  AREA "F1"  FLOOR  4  "1"  "2"  "3"  "4"  0  0  0  0
  AREA "O1"  FLOOR  4  "5"  "6"  "7"  "8"  0  0  0  0
$ POINT ASSIGNS
  POINTASSIGN  "1"  "BASE"  RESTRAINT "UX UY UZ"
$ LINE ASSIGNS
  LINEASSIGN  "C1"  "ROOF"  SECTION "COL"
  LINEASSIGN  "C2"  "ROOF"  SECTION "COL"
  LINEASSIGN  "C3"  "ROOF"  SECTION "COL"
  LINEASSIGN  "C4"  "ROOF"  SECTION "COL"
  LINEASSIGN  "B1"  "ROOF"  SECTION "COL"
  LINEASSIGN  "R1"  "ROOF"  SECTION "COL"
$ AREA ASSIGNS
  AREAASSIGN  "F1"  "ROOF"  SECTION "SLAB"
  AREAASSIGN  "O1"  "ROOF"  SECTION "None"  OPENING "Yes"
$ STATIC LOADS
  LOADCASE "DEAD"  TYPE  "DEAD"  SELFWEIGHT  1
  LOADCASE "LIVE"  TYPE  "LIVE"  SELFWEIGHT  0
$ LOAD COMBINATIONS
  COMBO "COMB1"  TYPE "ADD"
  COMBO "COMB1"  CASE "DEAD"  SF 1.2
  COMBO "COMB1"  CASE "LIVE"  SF 1.6
"""
    project = read_e2k("old.e2k", text=text)
    assert project.problems() == []
    plan = project.floor_plan
    assert [g.position for g in plan.grids.x] == [0, 4000]
    assert [g.position for g in plan.grids.y] == [0, 3000]
    assert project.materials.materials[0].concrete.fc == pytest.approx(25)
    assert project.materials.materials[0].mechanical.density == pytest.approx(2400, rel=2e-3)
    # The brace from the base at point 4 up to the roof at point 3 is an inclined member.
    assert [m.id for m in project.bim.additions.members] == ["R1-ROOF"]
    assert project.bim.additions.slabOpenings[0].xDim == 1000
    assert [(c.name, c.D, c.L) for c in project.settings.combinations] == [("COMB1", 1.2, 1.6)]
    approximated = {a["what"] for a in project.report.approximated}
    # The pinned base of C1 frees its rotations; the other column bases have no restraint in
    # the file, but SAEngine fixes them (reported).
    assert [(b.at, b.fixity) for b in project.bim.supports] == [([0, 0, 0], "pinned")]
    assert any(a.startswith("column bases the file leaves free") for a in approximated)
    assert "grid lines made from the column positions" in approximated

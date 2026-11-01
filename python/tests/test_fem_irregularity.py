"""Building irregularities, the dynamic analysis requirement, the soft storey design and the
diaphragm connection increase (saengine.fem.irregularity), with the values of the bnbc2020 pack:
BNBC 2020 Part 6 Sec 2.5.5.3 (pp. 617-618), Tables 6.1.4-6.1.5 (pp. 490-491), Figures
6.2.27-6.2.28 (pp. 619-621), Sec 2.5.6 (p. 626), Sec 2.5.8.1 (p. 633), Sec 2.5.17 (p. 666),
Sec 1.7.3.8(d) (pp. 505-506), Sec 2.5.5.6.2 (p. 625), Sec 2.5.13.1(b) (p. 645).

Synthetic buildings written here; nothing is written to disk.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.fem import irregularity as ir
from saengine.library.bim import BuildingModel
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import LoadCombination, default_project_settings

# ─────────────────────────────── the pack values ───────────────────────────────


def test_pack_values() -> None:
    s = code_context.table("seismic")
    t = s.irregularities
    # Sec 2.5.5.3.1(ii)-(iii) (pp. 617-618)
    assert t.reentrantProjection == 0.15
    assert t.openingShare == 0.5
    assert t.diaphragmStiffnessChange == 0.5
    # Sec 2.5.5.3.2(i): soft 70 % / 80 %, extreme 60 % / 70 % (p. 618)
    assert (t.soft.storeyAbove, t.soft.threeAbove) == (0.7, 0.8)
    assert (t.extremeSoft.storeyAbove, t.extremeSoft.threeAbove) == (0.6, 0.7)
    # Sec 2.5.5.3.2(v): weak 80 %, extreme 65 % (p. 618)
    assert t.weak.storeyAbove == 0.8 and t.extremeWeak.storeyAbove == 0.65
    # Table 6.1.4 type II 150 % (p. 490), more conservative than the 2.0 of 2.5.5.3.2(ii)
    assert t.mass.adjacent == 1.5 and t.mass.topExempt
    # Table 6.1.4 type III and Figure 6.2.28(c): 130 % (pp. 490, 620)
    assert t.geometry.adjacent == 1.3
    # Sec 2.5.5.3.2(iv): offset greater than the length (p. 618)
    assert t.inPlaneOffset == 1.0
    # Eq. 6.6.49 (p. 922), Sec 6.4.8.4 (p. 936)
    assert (t.strength.concreteFactor, t.strength.depthFactor) == (0.17, 0.8)
    # Sec 2.5.13.1(b): Category C with plan type V takes 100 % + 30 % (p. 645)
    assert t.nonparallelOrthogonal == ["C"]
    # Sec 2.5.8.1 (p. 633)
    d = s.dynamicAnalysis
    assert d.regularHeights == {"1": 90.0, "2": 40.0, "3": 40.0, "4": 40.0}
    assert d.irregularHeights == {"1": 40.0, "2": 12.0, "3": 12.0, "4": 12.0}
    # Sec 2.5.6 (p. 626): T < 4 TC and 2 s, no vertical irregularity
    assert (d.periodTcFactor, d.periodMax, d.verticalIrregularity) == (4.0, 2.0, True)
    # Sec 2.5.17 (p. 666)
    assert (s.softStorey.frameFactor, s.softStorey.wallFactor) == (2.5, 1.5)
    # Sec 1.7.3.8(d)(i), 2.5.5.6.2: +25 % in Category D
    c = s.diaphragmConnections
    assert c.categories == ["D"]
    assert set(c.types) == {
        "torsion",
        "extremeTorsion",
        "reentrantCorner",
        "diaphragmDiscontinuity",
        "outOfPlaneOffset",
        "inPlaneDiscontinuity",
    }
    assert code_context.pack_table("transfer").diaphragm.irregularIncrease == 1.25
    assert "p. 617" in ir.clause("reentrantCorner") and "p. 618" in ir.clause("soft")


# ─────────────────────────────── the threshold rules ───────────────────────────────


@pytest.mark.parametrize(
    ("values", "irregular", "extreme"),
    [
        ([50.0, 100.0, 100.0, 100.0], True, True),  # 50 % < 60 %
        ([78.0, 100.0, 100.0, 100.0], True, False),  # < 80 % of the three above only
        ([65.0, 100.0, 80.0, 80.0], True, False),  # < 70 % of the storey above only
        ([90.0, 100.0, 100.0, 100.0], False, False),
    ],
)
def test_soft_storey(values, irregular, extreme) -> None:
    t = ir.table()
    first = ir.ratio_checks(values, t.soft, t.extremeSoft)[0]
    assert first["irregular"] is irregular
    assert first["extreme"] is extreme
    # The top storey has nothing above to compare with.
    assert ir.ratio_checks(values, t.soft, t.extremeSoft)[-1]["irregular"] is False


@pytest.mark.parametrize(
    ("ratio", "weak", "extreme"),
    [(0.79, True, False), (0.64, True, True), (0.8, False, False)],
)
def test_weak_storey(ratio, weak, extreme) -> None:
    t = ir.table()
    first = ir.ratio_checks([ratio, 1.0], t.weak, t.extremeWeak)[0]
    assert (first["irregular"], first["extreme"]) == (weak, extreme)


def test_mass_irregularity_and_the_roof() -> None:
    t = ir.table()
    assert [c["irregular"] for c in ir.adjacent_checks([100, 160, 100], t.mass)] == [
        False,
        True,
        False,
    ]
    # A roof lighter than the floor below is not compared.
    assert not any(c["irregular"] for c in ir.adjacent_checks([100, 100, 40], t.mass))
    # A heavy roof is.
    assert ir.adjacent_checks([100, 100, 160], t.mass)[2]["irregular"]


def test_vertical_geometry_and_the_penthouse() -> None:
    t = ir.table()
    # One-storey penthouse: not compared.
    assert not any(c["irregular"] for c in ir.adjacent_checks([20, 20, 5], t.geometry))
    assert ir.adjacent_checks([20, 14, 14], t.geometry)[0]["irregular"]  # 1.43 > 1.3
    assert not ir.adjacent_checks([20, 16, 16], t.geometry)[0]["irregular"]  # 1.25


# ─────────────────────────────── plan geometry ───────────────────────────────


def _l_shape(notch: float) -> object:
    from shapely.geometry import Polygon

    a = 20000 - notch
    return Polygon([(0, 0), (20000, 0), (20000, a), (a, a), (a, 20000), (0, 20000)])


def test_reentrant_corners() -> None:
    share = ir.table().reentrantProjection
    corners = ir.reentrant_corners(_l_shape(10000), share)
    assert len(corners) == 1
    assert corners[0]["shareX"] == pytest.approx(0.5) and corners[0]["irregular"]
    small = ir.reentrant_corners(_l_shape(2000), share)  # 10 % < 15 %
    assert not small[0]["irregular"]


def test_openings() -> None:
    from shapely.geometry import Polygon

    floor = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)], [[(1, 1), (9, 1), (9, 9), (1, 9)]]
    )
    open_area, gross = ir.opening_share(floor)
    assert open_area / gross == pytest.approx(0.64)
    assert open_area > ir.table().openingShare * gross


def test_nonparallel() -> None:
    lines = [
        ("B1", (0, 0), (6000, 0)),
        ("B2", (0, 0), (0, 6000)),
        ("B3", (0, 6000), (6000, 6000)),
        ("W1", (0, 0), (5196, 3000)),  # 30°
    ]
    major, off = ir.nonparallel_elements(lines, ir.table().nonparallelTolerance)
    assert major == 0.0
    assert [o["id"] for o in off] == ["W1"]


# ─────────────────────────────── dynamic analysis ───────────────────────────────


@pytest.mark.parametrize(
    ("zone", "height", "irregular", "required", "recommended"),
    [
        (2, 13.0, True, True, False),  # irregular > 12 m, zones 2-4
        (2, 13.0, False, False, False),
        (2, 41.0, False, True, False),  # regular > 40 m
        (1, 85.0, False, False, False),  # regular, zone 1 up to 90 m
        (1, 30.0, True, False, True),  # irregular below 40 m in zone 1: recommended
        (1, 41.0, True, True, False),
    ],
)
def test_dynamic_requirement(zone, height, irregular, required, recommended) -> None:
    found = ir.dynamic_requirement(zone, height, irregular, False, None, None, False)
    assert found["required"] is required
    assert found["recommended"] is recommended
    assert found["ok"] is (not required)


def test_static_method_limits() -> None:
    # Sec 2.5.6: T at least min(4 TC, 2 s) or a vertical irregularity.
    long = ir.dynamic_requirement(2, 10.0, False, False, {"X": 2.1, "Y": 1.0}, 0.8, False)
    assert long["required"]
    short = ir.dynamic_requirement(2, 10.0, False, False, {"X": 1.9, "Y": 1.0}, 0.8, False)
    assert not short["required"]
    assert ir.dynamic_requirement(2, 10.0, True, True, None, None, False)["required"]
    used = ir.dynamic_requirement(2, 50.0, False, False, None, None, True)
    assert used["required"] and used["ok"]


# ─────────────────────────────── soft storey combinations ───────────────────────────────


def test_soft_storey_combinations() -> None:
    combos = [
        LoadCombination(name="1.2D+1.0L+1.0EX", D=1.2, L=1.0, EX=1.0, EY=0.3),
        LoadCombination(name="1.4D", D=1.4),
    ]
    out = ir.soft_storey_combinations(combos, 2.5, ir.frame_prefix(2.5))
    assert len(out) == 1
    assert out[0]["name"].startswith("Soft storey ×2.5: ")
    assert (out[0]["EX"], out[0]["EY"], out[0]["D"]) == (2.5, 0.75, 1.2)
    rs = ir.soft_storey_rs_combinations(
        [{"name": "E", "loads": {"D": 1.2}, "envelope": {"RX": 1.0, "AX": 1.0}}],
        1.5,
        ir.wall_prefix(1.5),
    )
    assert rs[0]["envelope"] == {"RX": 1.5, "AX": 1.5} and rs[0]["loads"] == {"D": 1.2}


# ─────────────────────────────── the assessment of a building ───────────────────────────────


def _materials() -> MaterialLibrary:
    return MaterialLibrary.model_validate(
        {
            "materials": [
                {
                    "id": "C28",
                    "name": "C28",
                    "category": "concrete",
                    "mechanical": {"E": 25000, "density": 2400},
                    "concrete": {"fc": 28},
                },
                {
                    "id": "R420",
                    "name": "R420",
                    "category": "rebar",
                    "mechanical": {"E": 200000},
                    "steel": {"fy": 420, "grade": "R420"},
                },
            ]
        }
    )


def _objects() -> ObjectLibrary:
    return ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "COL",
                    "kind": "column",
                    "name": "Column",
                    "material": "C28",
                    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                },
                {
                    "id": "BIG",
                    "kind": "column",
                    "name": "Big column",
                    "material": "C28",
                    "profile": {"shape": "rectangle", "xDim": 600, "yDim": 600},
                },
                {
                    "id": "BM",
                    "kind": "beam",
                    "name": "Beam",
                    "material": "C28",
                    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
                },
                {"id": "SL", "kind": "slab", "name": "Slab", "material": "C28", "thickness": 150},
                {"id": "W", "kind": "wall", "name": "Wall", "material": "C28", "thickness": 200},
            ]
        }
    )


def _building(storeys: int = 5, l_shape: bool = False, weak_ground: bool = False) -> BuildingModel:
    """A 2 × 2 bay frame (6 m bays), 3 m storeys; ``l_shape``: the floors an L (one bay
    missing); ``weak_ground``: the upper columns 600 mm, the ground ones 400 mm."""
    points = [(x, y) for x in (0, 6000, 12000) for y in (0, 6000, 12000)]
    if l_shape:
        points = [p for p in points if p != (12000, 12000)]
    elements: list[dict] = []
    for k in range(storeys):
        bottom, top = 3000 * k, 3000 * (k + 1)
        for i, (x, y) in enumerate(points):
            elements.append(
                {
                    "id": f"C{k}_{i}",
                    "kind": "column",
                    "type": "COL" if (weak_ground and k == 0) or not weak_ground else "BIG",
                    "position": [x, y],
                    "bottom": bottom,
                    "top": top,
                }
            )
        outline = (
            [[0, 0], [12000, 0], [12000, 6000], [6000, 6000], [6000, 12000], [0, 12000]]
            if l_shape
            else [[0, 0], [12000, 0], [12000, 12000], [0, 12000]]
        )
        elements.append(
            {"id": f"S{k}", "kind": "slab", "type": "SL", "boundary": outline, "elevation": top}
        )
        elements.append(
            {
                "id": f"B{k}",
                "kind": "beam",
                "type": "BM",
                "start": [0, 0],
                "end": [12000, 0],
                "elevation": top,
            }
        )
    stories = [
        {"id": f"L{k}", "name": f"Level {k + 1}", "elevation": 3000 * (k + 1)}
        for k in range(storeys)
    ]
    return BuildingModel.model_validate({"stories": stories, "elements": elements})


def _settings(site: str = "SD", occupancy: str = "II"):
    s = default_project_settings("Test")
    s.site.location = "dhaka"  # zone 2
    s.site.siteClass = site
    s.site.siteClassSource = "entered"
    s.occupancy.category = occupancy
    return s


def test_assess_l_shape_in_category_d() -> None:
    settings = _settings("SD", "III")  # zone 2, SD, occupancy III: Category D
    settings.analysis.seismicDesign = "static"
    found = ir.assess(None, None, _building(l_shape=True), _objects(), _materials(), settings)
    assert found["covered"] and found["plan"]
    assert "reentrantCorner" in found["types"]
    # Irregular, 15 m > 12 m in zone 2: dynamic analysis required (Sec 2.5.8.1), and the
    # design uses the static cases.
    assert found["dynamic"]["required"] and not found["dynamic"]["ok"]
    assert any("dynamic analysis is required" in n for n in found["notes"])
    # Category D with plan type II: connections × 1.25; the wings need their own design.
    assert found["connections"]["applies"] and found["connections"]["factor"] == 1.25
    assert found["connections"]["wings"] and not found["connections"]["wingsExempt"]
    # With the response spectrum on the 3D model, the wings exception holds.
    settings.analysis.seismicDesign = "responseSpectrum"
    found = ir.assess(None, None, _building(l_shape=True), _objects(), _materials(), settings)
    assert found["dynamic"]["ok"] and found["connections"]["wingsExempt"]


def test_regular_building_needs_no_dynamic_analysis() -> None:
    settings = _settings("SC", "II")  # zone 2, SC: Category C
    found = ir.assess(None, None, _building(storeys=4), _objects(), _materials(), settings)
    assert found["types"] == []
    assert not found["dynamic"]["required"]  # 12 m regular
    assert not found["connections"]["applies"]


def test_weak_ground_storey_from_the_column_strength() -> None:
    found = ir.assess(
        None, None, _building(weak_ground=True), _objects(), _materials(), _settings()
    )
    weak = [f for f in found["findings"] if f["type"] in ("weak", "extremeWeak")]
    # 400² against 600² columns: Vn ratio (400·320)/(600·480) = 0.44 < 0.65: extreme.
    assert {f["storey"] for f in weak} == {"Level 1"}
    assert all(f["type"] == "extremeWeak" for f in weak)


def test_declared_soft_storey_members() -> None:
    settings = _settings()
    settings.seismic.softStoreys = ["Level 1"]
    building = _building(storeys=3)
    found = ir.assess(None, None, building, _objects(), _materials(), settings)
    assert found["softStoreys"][0]["type"] == "declared"
    assert found["vertical"]
    members = ir.soft_storey_members(found, building, _objects())
    assert members["frameFactor"] == 2.5 and members["wallFactor"] == 1.5
    # The ground storey's columns and the beam at its ceiling.
    assert {m for m in members["frames"] if m.startswith("C0_")} == {f"C0_{i}" for i in range(9)}
    assert "B0" in members["frames"] and "B1" not in members["frames"]
    settings.seismic.softStoreyDesign = "dynamicInfill"
    found = ir.assess(None, None, building, _objects(), _materials(), settings)
    assert not ir.soft_storey_members(found, building, _objects())["frames"]


def test_wall_offset_in_plane() -> None:
    """A wall continued below on its own line, offset by more than its length: vertical type
    IV (in-plane discontinuity)."""
    building = BuildingModel.model_validate(
        {
            "elements": [
                {"id": "C1", "kind": "column", "type": "COL", "position": [0, 0], "bottom": 0,
                 "top": 3000},
                {"id": "C2", "kind": "column", "type": "COL", "position": [12000, 0],
                 "bottom": 0, "top": 3000},
                {"id": "WL", "kind": "wall", "type": "W", "start": [0, 0], "end": [3000, 0],
                 "bottom": 0, "top": 3000},
                {"id": "WU", "kind": "wall", "type": "W", "start": [8000, 0],
                 "end": [11000, 0], "bottom": 3000, "top": 6000},
            ]
        }
    )
    found = ir.offsets(building, _objects(), _materials())
    assert found == [
        {
            "id": "WU",
            "kind": "wall",
            "elevation": 3.0,
            "type": "inPlaneDiscontinuity",
            "offset": 8000.0,
            "length": 3000.0,
        }
    ]


def test_column_strength() -> None:
    mats = {m.id: m for m in _materials().materials}
    col = _objects().objects[0]
    found = ir.column_strength(col, mats)
    # 0.17 √28 × 400 × 0.8 × 400 (no ties)
    assert found["X"] == pytest.approx(0.17 * 28**0.5 * 400 * 320)


def test_pack_without_irregularities_is_not_covered(monkeypatch) -> None:
    fake = SimpleNamespace(irregularities=None)
    monkeypatch.setattr(ir, "_seismic", lambda: fake)
    found = ir.assess(None, None, _building(), _objects(), _materials(), _settings())
    assert not found["covered"] and "not covered" in found["notes"][0]

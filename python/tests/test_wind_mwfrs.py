"""Wind on the main wind-force resisting system's walls and roofs (B11): the internal pressure
with Ri, the roof pressure coefficients of all heights, domes and arched roofs, the low-rise
(GCpf), the clad special structures and their wind cases. The values are those of the bnbc2020
code pack (BNBC 2020 Part 6 Sec 2.4.10-2.4.11.2, Figures 6.2.5-6.2.8 and 6.2.10, pp. 556-577),
checked by hand."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.fem import loads as fl
from saengine.fem.combinations import wind_case_combinations
from saengine.fem.open_wind import CladPoint, clad_structure_wind
from saengine.library.settings import LoadCombination
from saengine.library.shapes import PortalFrame, shape_geometry


def _wind():
    return code_context.table("wind")


# ── internal pressure (Sec 2.4.10.1, Figure 6.2.5 p. 570, Eq 6.2.18 p. 556) ──


def test_internal_pressure_coefficients_figure_6_2_5() -> None:
    assert fl.internal_pressure_coefficient("enclosed") == (0.18, 1.0)
    assert fl.internal_pressure_coefficient("partiallyEnclosed") == (0.55, 1.0)
    assert fl.internal_pressure_coefficient("open") == (0.0, 1.0)


def test_large_volume_reduction_eq_6_2_18() -> None:
    # Ri = 0.5·(1 + 1/√(1 + Vi/(6951·Aog))): Aog 10 m², Vi 50 000 m³ → 1 + 0.7193 = 1.7193,
    # √ = 1.3112, Ri = 0.5·(1 + 0.7627) = 0.8813.
    gcpi, ri = fl.internal_pressure_coefficient("partiallyEnclosed", 10.0, 50_000.0)
    assert gcpi == 0.55
    assert ri == pytest.approx(0.5 * (1 + 1 / math.sqrt(1 + 50_000 / (6951 * 10))))
    assert ri == pytest.approx(0.8813, abs=1e-4)
    # A small volume: Ri capped at 1.0; enclosed buildings are never reduced.
    assert fl.internal_pressure_coefficient("partiallyEnclosed", 100.0, 10.0)[1] <= 1.0
    assert fl.internal_pressure_coefficient("enclosed", 10.0, 50_000.0) == (0.18, 1.0)


# ── walls and roofs of all heights (Figure 6.2.6, pp. 571-572) ──


def test_wall_coefficients_figure_6_2_6() -> None:
    wind = _wind()
    assert wind.cpWindward == 0.8
    assert fl.leeward_coefficient(1.0) == -0.5
    assert fl.leeward_coefficient(2.0) == -0.3
    assert fl.leeward_coefficient(5.0) == -0.2
    assert wind.mwfrs.sideWall == -0.7
    # Sec 2.4.10.4: windward overhangs, Cp 0.8 on the underside.
    assert wind.mwfrs.overhang == 0.8


@pytest.mark.parametrize(
    ("theta", "ratio", "expected"),
    [
        (10, 0.25, (-0.7, -0.18)),
        (10, 1.0, (-1.3, -0.18)),
        (20, 0.5, (-0.4, 0.0)),
        (30, 0.25, (-0.2, 0.3)),
        (35, 1.0, (-0.2, 0.2)),
        (45, 0.5, (0.0, 0.4)),
        # Linear between angles: 22.5° at h/L 0.25 between (-0.3, 0.2) and (-0.2, 0.3).
        (22.5, 0.25, (-0.25, 0.25)),
        # Linear between h/L: 0.75 between the 0.5 and the 1.0 rows at 15°.
        (15, 0.75, (-0.85, -0.18)),
        # From 60°: 0.01θ; above 80°: 0.8 (the # note).
        (70, 0.5, (0.7, 0.7)),
        (85, 0.5, (0.8, 0.8)),
    ],
)
def test_windward_roof_cp(theta: float, ratio: float, expected: tuple[float, float]) -> None:
    assert fl.roof_windward_cp(theta, ratio) == pytest.approx(expected)


def test_windward_roof_cp_takes_zero_where_no_value_is_printed() -> None:
    # Note 2: h/L ≤ 0.25 at 45° prints only +0.4, so the suction column counts 0.0 there; at
    # 40° it lies between 0.0 (35°) and 0.0 (45°).
    assert fl.roof_windward_cp(40, 0.25)[0] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("theta", "ratio", "expected"),
    [(10, 0.25, -0.3), (10, 0.5, -0.5), (10, 1.0, -0.7), (15, 1.0, -0.6), (30, 0.25, -0.6)],
)
def test_leeward_roof_cp(theta: float, ratio: float, expected: float) -> None:
    assert fl.roof_leeward_cp(theta, ratio) == pytest.approx(expected)


def test_flat_roof_and_parallel_zones() -> None:
    h = 10.0
    # h/L ≤ 0.5: 0-h/2 and h/2-h -0.9, h-2h -0.5, beyond -0.3 (each with -0.18).
    assert fl.roof_parallel_cp(2.0, h, 0.4) == pytest.approx((-0.9, -0.18))
    assert fl.roof_parallel_cp(8.0, h, 0.4) == pytest.approx((-0.9, -0.18))
    assert fl.roof_parallel_cp(15.0, h, 0.4) == pytest.approx((-0.5, -0.18))
    assert fl.roof_parallel_cp(25.0, h, 0.4) == pytest.approx((-0.3, -0.18))
    # h/L ≥ 1.0: 0-h/2 -1.3 (reduced with area: 0.9 at 23.2 m², 0.8 from 92.9 m²), beyond -0.7.
    assert fl.roof_parallel_cp(2.0, h, 1.5) == pytest.approx((-1.3, -0.18))
    assert fl.roof_parallel_cp(2.0, h, 1.5, area=23.2)[0] == pytest.approx(-1.17)
    assert fl.roof_parallel_cp(2.0, h, 1.5, area=200.0)[0] == pytest.approx(-1.04)
    assert fl.roof_parallel_cp(8.0, h, 1.5) == pytest.approx((-0.7, -0.18))
    # h/L 0.75: halfway between the rows.
    assert fl.roof_parallel_cp(8.0, h, 0.75)[0] == pytest.approx(-0.8)


def test_mean_roof_height_uses_the_eave_up_to_10_degrees() -> None:
    assert fl.mean_roof_height(6.0, 7.0, 5.0) == 6.0
    assert fl.mean_roof_height(6.0, 8.0, 15.0) == 7.0


def test_building_mwfrs_pressures_eq_6_2_19() -> None:
    table = fl.building_mwfrs_pressures(12.0, 20.0, 30.0, 65.7, "A", 1.0)
    assert table is not None
    qh, g = table["qh_kPa"], table["G"]
    assert qh == pytest.approx(fl.velocity_pressure(12.0, 65.7, "A", 1.0))
    by = {r["surface"]: r for r in table["surfaces"] if r["surface"] != "roof"}
    # Windward: qh·G·0.8 ± qh·0.18 (enclosed).
    assert by["windward wall"]["pPos_kPa"] == pytest.approx(qh * (g * 0.8 + 0.18))
    assert by["side wall"]["pNeg_kPa"] == pytest.approx(qh * (g * -0.7 - 0.18))
    roofs = [r for r in table["surfaces"] if r["surface"] == "roof"]
    assert [r["from_m"] for r in roofs] == [0.0, 6.0, 12.0]


# ── domes (Figure 6.2.7, p. 573) and arched roofs (Figure 6.2.8, p. 574) ──


def test_dome_coefficients_figure_6_2_7() -> None:
    top = fl.dome_point_cps(0.5, 0.0)
    assert top == pytest.approx({"A": 0.8, "B": -1.2, "C": 0.0})
    tall = fl.dome_point_cps(0.5, 1.0)
    assert tall["A"] == pytest.approx(0.8) and tall["B"] == pytest.approx(-1.5)
    assert tall["C"] == pytest.approx(-0.5)
    assert fl.dome_point_cps(0.1, 1.0)["A"] == pytest.approx(-1.7)
    # Note 8: below f/D 0.05, Figure 6.2.6.
    assert fl.dome_point_cps(0.04, 0.0) is None
    cps = {"A": 0.4, "B": -1.0, "C": -0.5}
    # Case A linear A-B; Case B constant A up to 25°, then linear to B at 90°.
    assert fl.dome_cp(cps, 45, True, "A") == pytest.approx(-0.3)
    assert fl.dome_cp(cps, 20, True, "B") == pytest.approx(0.4)
    assert fl.dome_cp(cps, 57.5, True, "B") == pytest.approx(-0.3)
    assert fl.dome_cp(cps, 45, False, "A") == pytest.approx(-0.75)


def test_arched_roof_coefficients_figure_6_2_8() -> None:
    low = fl.arched_roof_cps(0.1, True)
    assert low == pytest.approx({"windward": [-0.9], "centre": -0.8, "leeward": -0.5})
    mid = fl.arched_roof_cps(0.25, True)
    # 1.5r - 0.3 and the alternate 6r - 2.1 (shall also be used).
    assert mid["windward"] == pytest.approx([0.075, -0.6])
    assert fl.arched_roof_cps(0.4, True)["windward"] == pytest.approx([0.4])
    assert fl.arched_roof_cps(0.4, False)["windward"] == pytest.approx([0.56])
    assert fl.arched_roof_cps(0.7, True) is None


# ── low-rise buildings (Figure 6.2.10, pp. 576-577; Sec 2.1.3, p. 513) ──


def test_low_rise_gcpf_figure_6_2_10() -> None:
    flat = fl.low_rise_gcpf(0)
    assert [flat[k] for k in ("1", "2", "3", "4", "5", "6")] == [
        0.40,
        -0.69,
        -0.37,
        -0.29,
        -0.45,
        -0.45,
    ]
    assert [flat[k] for k in ("1E", "2E", "3E", "4E")] == [0.61, -1.07, -0.53, -0.43]
    assert fl.low_rise_gcpf(20)["1E"] == 0.80
    assert fl.low_rise_gcpf(40)["2"] == 0.21
    assert fl.low_rise_gcpf(90)["2E"] == 0.69
    assert fl.low_rise_gcpf(12.5)["1"] == pytest.approx((0.40 + 0.53) / 2)
    lr = _wind().mwfrs.lowRise
    assert (lr.endZoneFactor, lr.zone2Fraction, lr.zone2EaveFactor) == (2.0, 0.5, 2.5)
    assert lr.torsionalShare == 0.25
    assert fl.is_low_rise(10.0, 20.0) and not fl.is_low_rise(19.0, 40.0)
    assert not fl.is_low_rise(12.0, 10.0)


# ── clad structures ──


def _box(length: float = 20.0, width: float = 10.0, height: float = 5.0) -> list[CladPoint]:
    """A box with a flat roof: one point per face (x along the length)."""
    faces = [
        ("W", np.array([0.0, width / 2, height / 2]), np.array([-1.0, 0, 0]), width * height),
        ("E", np.array([length, width / 2, height / 2]), np.array([1.0, 0, 0]), width * height),
        ("S", np.array([length / 2, 0.0, height / 2]), np.array([0, -1.0, 0]), length * height),
        ("N", np.array([length / 2, width, height / 2]), np.array([0, 1.0, 0]), length * height),
        ("R", np.array([length / 2, width / 2, height]), np.array([0, 0, 1.0]), length * width),
    ]
    return [CladPoint(k, k, c, n, a) for k, c, n, a in faces]


def test_clad_box_pressures_all_heights() -> None:
    q = 1000.0  # Pa, uniform with height
    result = clad_structure_wind(
        _box(),
        eave=5.0,
        top=5.0,
        footprint=(np.zeros(3), np.array([20.0, 10.0, 0.0])),
        qz_of=lambda z: q,
        gust=0.85,
        gcpi=0.18,
    )
    wx = result.pressures["WX"]
    assert wx["W"] == pytest.approx(q * 0.85 * 0.8)
    assert wx["E"] == pytest.approx(q * 0.85 * fl.leeward_coefficient(2.0))
    assert wx["S"] == pytest.approx(q * 0.85 * -0.7)
    # The flat roof by its distance from the windward edge (h/L 0.25): the middle at 10 m = 2h.
    assert wx["R"] == pytest.approx(q * 0.85 * -0.5)
    # Wind from -X: the east wall is windward.
    assert result.pressures["WXN"]["E"] == pytest.approx(q * 0.85 * 0.8)
    assert "WX2" in result.pressures  # the -0.18 roof value
    assert result.internal == pytest.approx(0.18 * q)
    assert result.inside == {"W", "E", "S", "N", "R"}


def test_clad_box_low_rise_end_zones() -> None:
    q = 1000.0
    result = clad_structure_wind(
        _box(),
        eave=5.0,
        top=5.0,
        footprint=(np.zeros(3), np.array([20.0, 10.0, 0.0])),
        qz_of=lambda z: q,
        gust=0.85,
        gcpi=0.18,
        method="lowRise",
    )
    assert result.summary["method"] == "lowRise"
    # One storey, h 5 m ≤ 9.1 m: no torsional patterns, two reference corners per direction.
    assert {"WX", "WX2", "WXN", "WXN2", "WY", "WY2", "WYN", "WYN2"} == set(result.pressures)
    # a = max(min(0.1·10, 0.4·5), 0.04·10, 0.9) = 1.0 m; the end zones 2 m: the faces' centres
    # lie farther, so they take zones 1, 4, 5/6 and 2 (θ = 0, roof centre at L/2: zone 3).
    wx = result.pressures["WX"]
    assert wx["W"] == pytest.approx(q * 0.40)
    assert wx["E"] == pytest.approx(q * -0.29)
    assert wx["S"] == pytest.approx(q * -0.45)


def test_clad_wind_cases_in_the_combinations() -> None:
    present = {"D", "WX", "WY", "WXN", "WYN", "WX2", "WI"}
    combination = LoadCombination(name="0.9D - 1.0WX", D=0.9, WX=-1.0)
    formed = wind_case_combinations([combination], present)
    factors = [
        {**{k: v for k, v in (c.cases or {}).items()}, "WX": c.WX}
        for c in formed
        if "Case 1" in c.name
    ]
    # -WX goes to WXN at +1 (no WXN2 in the model), with ±WI.
    assert {"WXN": 1.0, "WI": 1.0, "WX": 0.0} in factors
    assert {"WXN": 1.0, "WI": -1.0, "WX": 0.0} in factors
    plus = LoadCombination(name="0.9D + 1.0WX", D=0.9, WX=1.0)
    names = [c.name for c in wind_case_combinations([plus], present)]
    assert any(n.endswith("[Case 1 WX2 +WI]") for n in names)


def test_resolve_wind_cases_leaves_buildings_alone() -> None:
    variants = [("Case 1", {"WX": -1.0})]
    assert fl.resolve_wind_cases(variants, {"WX", "WY", "WTX", "WTY"}) == variants


# ── portal frames: end wall panels and overhangs ──


def test_portal_frame_end_walls_and_overhang() -> None:
    shape = PortalFrame(
        width=12000,
        length=18000,
        bays=3,
        eaveHeight=6000,
        slope=15,
        columnType="C",
        rafterType="R",
        purlinType="P",
        purlinSpacing=3000,
        roofPanelType="S",
        wallPanelType="W",
        endWallPanelType="E",
        overhang=1000,
    )
    g = shape_geometry(shape)
    ends = [a for a in g.areas if a.type == "E"]
    # Two gable ends, each split at the ridge.
    assert len(ends) == 4
    assert max(p[2] for a in ends for p in a.outline) == pytest.approx(
        6000 + 6000 * math.tan(math.radians(15)), abs=0.5
    )
    # Overhangs: rafters reach 1 m past each eave, lower than the eave.
    xs = [p[0] for m in g.members if m.type == "R" for p in (m.start, m.end)]
    assert min(xs) == pytest.approx(-1000) and max(xs) == pytest.approx(13000)
    tips = [a for a in g.areas if a.type == "S" and min(p[0] for p in a.outline) < -1]
    assert len(tips) == 3  # one per bay on the -x side


def test_clad_shed_derivation_takes_the_pressures_on_its_panels() -> None:
    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate_from_structure
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import default_project_settings
    from saengine.library.shapes import insert
    from saengine.library.structure import default_structural_model

    def member(id_: str, a: float, b: float) -> dict:
        kind = "column" if id_ == "C" else "beam"
        profile = {"shape": "rectangle", "xDim": a, "yDim": b}
        return {"id": id_, "name": id_, "kind": kind, "material": "C24.1", "profile": profile}

    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                member("C", 300, 300),
                member("R", 200, 400),
                member("P", 100, 150),
                {"id": "S", "name": "s", "kind": "slab", "material": "C24.1", "thickness": 50},
            ]
        }
    )
    shape = PortalFrame(
        width=12000,
        length=18000,
        bays=3,
        eaveHeight=6000,
        slope=15,
        columnType="C",
        rafterType="R",
        purlinType="P",
        purlinSpacing=3000,
        roofPanelType="S",
        wallPanelType="S",
        endWallPanelType="S",
    )
    model, _, _ = insert(default_structural_model(), shape_geometry(shape))
    settings = default_project_settings("Shed")
    settings.wind.openStructure.form = "clad"
    settings.analysis.meshSize = 1500
    building = generate_from_structure(model, "s")
    d = derive_fem(building, objects, default_material_library(), settings)
    names = [p["name"] for p in d.project["load_patterns"]]
    assert {"WX", "WXN", "WY", "WYN", "WI"} <= set(names)
    clad = d.summary["cladWind"]
    assert clad["method"] == "allHeights" and clad["theta_deg"] == pytest.approx(15, abs=0.01)
    # h = (eave + ridge)/2; Vi = 12 × 18 × h.
    assert clad["h_m"] == pytest.approx(6 + 3 * math.tan(math.radians(15)), abs=1e-3)
    assert clad["Vi_m3"] == pytest.approx(12 * 18 * clad["h_m"], rel=1e-3)

    def total(case: str) -> np.ndarray:
        pattern = next(p for p in d.project["load_patterns"] if p["name"] == case)
        return np.sum([n["forces"][:3] for n in pattern["nodal_loads"]], axis=0)

    # The internal pressure pushes the closed envelope out: what is left is the uplift on the
    # plan (the ground takes the rest), qi × 12 × 18.
    assert total("WI") == pytest.approx([0.0, 0.0, clad["qi_Pa"] * 12 * 18], abs=50.0)
    # Wind +X pushes along +X and lifts the roof; -X is its mirror image.
    wx, wxn = total("WX"), total("WXN")
    assert wx[0] > 0 and wx[2] > 0
    assert wxn[0] == pytest.approx(-wx[0], rel=1e-3) and wxn[2] == pytest.approx(wx[2], rel=1e-3)

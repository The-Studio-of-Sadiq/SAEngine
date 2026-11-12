"""Wind on open buildings and pitched-roof components and cladding (B14): the free roofs' net
pressure coefficients CN (MWFRS and C&C), the roof figures of components and cladding by form
and angle, and a canopy's wind cases in the derivation. The values are those of the bnbc2020
code pack (BNBC 2020 Part 6 Sec 2.4.11.4, 2.4.12, Figures 6.2.8 note 4, 6.2.11-6.2.16,
6.2.18-6.2.19, pp. 560-562, 574, 578-595), read off the figures by hand."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.fem import loads as fl
from saengine.fem import open_wind as ow
from saengine.fem.open_wind import CladPoint

# ── free roofs, MWFRS (Figures 6.2.18(a)-(d), pp. 589-592) ──


@pytest.mark.parametrize(
    ("form", "theta", "case", "blockage", "reverse", "expected"),
    [
        ("monoslope", 0, "A", "clear", False, (1.2, 0.3)),  # 6.2.18(a), θ 0°
        ("monoslope", 15, "B", "obstructed", False, (-2.1, -0.6)),
        ("monoslope", 15, "A", "clear", True, (1.3, 1.6)),  # γ = 180°
        ("monoslope", 45, "B", "obstructed", True, (2.1, 0.4)),
        ("pitched", 30, "A", "clear", False, (1.3, 0.3)),  # 6.2.18(b)
        ("pitched", 7.5, "B", "obstructed", False, (-0.9, -1.7)),
        ("troughed", 22.5, "B", "clear", False, (-0.1, 0.8)),  # 6.2.18(c)
        ("troughed", 45, "A", "obstructed", False, (-1.2, -0.3)),
        # Linear between the rows (note 3): pitched A clear, 15° and 22.5°.
        ("pitched", 18.75, "A", "clear", False, (1.1, -0.15)),
        # Below 7.5° every form takes the monoslope's 0° row (note 3).
        ("pitched", 5, "A", "clear", False, (1.2, 0.3)),
        ("troughed", 3, "B", "obstructed", False, (-1.1, -0.6)),
    ],
)
def test_free_roof_cn(form, theta, case, blockage, reverse, expected) -> None:
    cnw, cnl = ow.free_roof_cn(form, theta, case, blockage, reverse)
    assert (cnw, cnl) == pytest.approx(expected)


def test_free_roof_above_45_degrees_is_not_covered() -> None:
    assert ow.free_roof_cn("pitched", 50, "A") is None
    assert ow.free_roof_cladding("pitched", 50, "clear", None, 1.0) is None


def test_free_roof_along_the_ridge_figure_6_2_18d() -> None:
    assert ow.free_roof_along_cn(0.5, "A", "clear") == -0.8
    assert ow.free_roof_along_cn(1.5, "A", "obstructed") == -0.9
    assert ow.free_roof_along_cn(3.0, "B", "clear") == 0.3
    assert ow.free_roof_along_cn(0.5, "B", "obstructed") == 0.5


# ── free roofs, C&C (Figures 6.2.19(a)-(c), pp. 593-595) ──


def _zones(rows):
    return {z["zone"]: (z["CNPos"], z["CNNeg"]) for z in rows}


def test_free_roof_cladding_bands_and_zones() -> None:
    a = 2.0
    # Monoslope 30°, clear: up to a², a² to 4a², above 4a².
    small = _zones(ow.free_roof_cladding("monoslope", 30, "clear", 3.0, a))
    assert small["3"] == pytest.approx((5.2, -5.0))
    assert small["2"] == pytest.approx((3.9, -3.8))
    middle = _zones(ow.free_roof_cladding("monoslope", 30, "clear", 10.0, a))
    assert middle["3"] == pytest.approx((3.9, -3.8))
    large = _zones(ow.free_roof_cladding("monoslope", 30, "clear", 20.0, a))
    assert large["1"] == pytest.approx((2.6, -2.5))
    # No area: the smallest band (the largest values).
    assert _zones(ow.free_roof_cladding("pitched", 7.5, "obstructed", None, a))["3"] == (
        pytest.approx((1.0, -5.1))
    )
    # Troughed 15° obstructed, zone 2 above 4a² (printed '-12', read -1.2).
    assert _zones(ow.free_roof_cladding("troughed", 15, "obstructed", 20.0, a))["2"] == (
        pytest.approx((0.5, -1.2))
    )


def test_free_roof_cladding_conservative_readings() -> None:
    a = 1.0
    # Monoslope 7.5° obstructed zone 2 up to a²: printed +0.5, the +1.2 of larger areas used.
    assert _zones(ow.free_roof_cladding("monoslope", 7.5, "obstructed", 0.5, a))["2"][0] == 1.2
    # Monoslope 15° obstructed zone 1: the printed -2.3 (above 4a²) for every area.
    assert _zones(ow.free_roof_cladding("monoslope", 15, "obstructed", 0.5, a))["1"][1] == -2.3
    # Troughed 30° clear zone 2: the printed +1.9 (above 4a²) for every area.
    assert _zones(ow.free_roof_cladding("troughed", 30, "clear", 0.5, a))["2"][0] == 1.9


def _canopy(form: str, theta: float = 15.0, length: float = 12.0, width: float = 8.0):
    """A free roof: two slopes across x (pitched: ridge at the middle, troughed: valley),
    or one (monoslope, high at x = 0); four points per slope."""
    t = np.tan(np.radians(theta))
    points = []
    k = 0
    for x in np.linspace(0.75, width - 0.75, 4):
        for y in (length / 4, 3 * length / 4):
            if form == "monoslope":
                z, nx = (width - x) * t, 1.0
            elif form == "pitched":
                z, nx = (width / 2 - abs(x - width / 2)) * t, np.sign(x - width / 2)
            else:
                z, nx = abs(x - width / 2) * t, -np.sign(x - width / 2)
            n = np.array([nx * np.sin(np.radians(theta)), 0.0, np.cos(np.radians(theta))])
            points.append(CladPoint(k, "R", np.array([x, y, 4.0 + z]), n, 6.0))
            k += 1
    return points


@pytest.mark.parametrize("form", ["monoslope", "pitched", "troughed"])
def test_free_roof_form_is_read_from_the_panels(form) -> None:
    points = _canopy(form)
    axis = ow.roof_axis(points)
    assert ow.free_roof_form(points, axis, np.array([4.0, 6.0, 0.0])) == form


def test_free_roof_wind_cases() -> None:
    q = 1000.0
    points = _canopy("pitched", theta=15.0)
    top = 4.0 + 4.0 * np.tan(np.radians(15.0))
    result = ow.free_roof_wind(
        points,
        eave=4.0,
        top=top,
        plan=(np.zeros(3), np.array([8.0, 12.0, 0.0])),
        qz_of=lambda z: q,
        gust=0.85,
    )
    s = result.summary
    assert s["roofForm"] == "pitched" and s["theta_deg"] == pytest.approx(15.0)
    # +X is normal to the ridge: Case A clear CNW 1.1 on the windward half, CNL -0.4 leeward.
    wx = result.pressures["WX"]
    assert wx[0] == pytest.approx(q * 0.85 * 1.1)  # x 0.75, windward
    assert wx[7] == pytest.approx(q * 0.85 * -0.4)  # x 7.25, leeward
    assert result.pressures["WX2"][0] == pytest.approx(q * 0.85 * 0.1)  # Case B
    # +Y runs along the ridge (Figure 6.2.18(d)): h = (4 + top)/2, by distance from the edge.
    h = (4.0 + top) / 2
    assert result.pressures["WY"][0] == pytest.approx(q * 0.85 * (-0.8 if 3 <= h else -0.6))
    assert result.pressures["WY2"][1] == pytest.approx(q * 0.85 * 0.5)  # y 9: h to 2h, Case B
    assert result.internal == 0.0
    assert {z["zone"] for z in s["cladding"]["zones"]} == {"1", "2", "3"}


def test_free_monoslope_wind_down_and_up_the_slope() -> None:
    q = 1000.0
    points = _canopy("monoslope", theta=15.0)
    result = ow.free_roof_wind(
        points,
        eave=4.0,
        top=4.0 + 8.0 * np.tan(np.radians(15.0)),
        plan=(np.zeros(3), np.array([8.0, 12.0, 0.0])),
        qz_of=lambda z: q,
        gust=0.85,
        blockage="obstructed",
    )
    # High at x = 0: +X blows down the slope (γ 0°), -X up it (γ 180°).
    assert result.pressures["WX"][0] == pytest.approx(q * 0.85 * -1.1)
    assert result.pressures["WXN"][7] == pytest.approx(q * 0.85 * 0.4)


# ── enclosed buildings, pitched and other roofs (Figures 6.2.11-6.2.16, pp. 578-587) ──


def _cc(**kw):
    out = fl.cladding_pressures(6.0, 20.0, 50.0, "B", 1.0, **kw)
    return {z["zone"]: (z["GCpPos"], z["GCpNeg"]) for z in out["zones"]}, out


def test_gable_roof_7_to_27_degrees_figure_6_2_11c() -> None:
    zones, out = _cc(roof_form="gable", roof_angle=20.0)
    assert zones["1"] == pytest.approx((0.5, -0.9))
    assert zones["2"] == pytest.approx((0.5, -1.7))
    assert zones["3"] == pytest.approx((0.5, -2.6))
    assert zones["3 overhang"] == pytest.approx((None, -3.7))
    assert zones["2 overhang"][1] == pytest.approx(-2.2)
    # Walls not reduced above θ 10° (Figure 6.2.11(a) note 5).
    assert zones["4"] == pytest.approx((1.0, -1.1))
    assert "6.2.11(c)" in out["figure"]
    # 9.3 m² and more: the curves' ends.
    zones, _ = _cc(roof_form="gable", roof_angle=20.0, area=20.0)
    assert zones["3"] == pytest.approx((0.3, -2.0))


def test_hip_roof_zone_3_as_zone_2_up_to_25_degrees() -> None:
    zones, _ = _cc(roof_form="hip", roof_angle=20.0)
    assert zones["3"] == zones["2"]
    zones, _ = _cc(roof_form="hip", roof_angle=26.0)
    assert zones["3"][1] == pytest.approx(-2.6)


def test_gable_roof_27_to_45_degrees_figure_6_2_11d() -> None:
    zones, _ = _cc(roof_form="gable", roof_angle=35.0)
    assert zones["1"] == pytest.approx((0.9, -1.0))
    assert zones["3"] == pytest.approx((0.9, -1.2))
    assert zones["3 overhang"][1] == pytest.approx(-2.0)


def test_flat_roof_overhang_figure_6_2_11b() -> None:
    zones, _ = _cc(area=9.3)
    assert zones["2 overhang"][1] == pytest.approx(-1.6)
    assert zones["3 overhang"][1] == pytest.approx(-0.8)
    steep, _ = _cc(roof_form="gable", roof_angle=20.0, area=9.3)
    assert zones["4"][0] == pytest.approx(0.9 * steep["4"][0])  # walls × 0.9 for θ ≤ 10° only


def test_multispan_and_monoslope_and_sawtooth() -> None:
    zones, _ = _cc(roof_form="multispan", roof_angle=20.0)
    assert zones["3"] == pytest.approx((0.6, -2.7))  # Figure 6.2.13
    zones, _ = _cc(roof_form="multispan", roof_angle=40.0)
    assert zones["1"] == pytest.approx((1.0, -2.0))
    zones, out = _cc(roof_form="multispan", roof_angle=8.0)  # θ ≤ 10°: Figure 6.2.11
    assert "6.2.11(c)" in out["figure"] and any("multispan" in n for n in out["notes"])
    zones, _ = _cc(roof_form="monoslope", roof_angle=20.0)
    assert zones["3"] == pytest.approx((0.4, -2.9))  # Figure 6.2.14(b)
    # 3° < θ ≤ 10°: Figure 6.2.14(a) with Figure 6.2.11 where larger (note 5 misprint).
    zones, _ = _cc(roof_form="monoslope", roof_angle=5.0)
    assert zones["3'"][1] == pytest.approx(-2.8)  # 6.2.11(b) zone 3 -2.8 over -2.6
    assert zones["1"][1] == pytest.approx(-1.1)  # 6.2.14(a) -1.1 over -1.0
    zones, _ = _cc(roof_form="sawtooth", roof_angle=20.0)
    assert zones["3A"] == pytest.approx((1.1, -4.1))  # Figure 6.2.15
    zones, _ = _cc(roof_form="sawtooth", roof_angle=20.0, area=46.5)
    assert zones["3"] == pytest.approx((0.8, -1.9))


def test_stepped_dome_and_arched_roofs() -> None:
    zones, out = _cc(roof_form="stepped", step_height=3.0)
    assert zones["3 step"][1] == zones["2"][1]  # Figure 6.2.12
    assert zones["2 step"][1] == zones["1"][1]
    assert zones["step strip"][0] == pytest.approx(0.9)  # walls' positive (× 0.9)
    assert any("4.50 m" in z["label"] for z in out["zones"])  # b = 1.5 h1
    zones, _ = _cc(roof_form="dome", roof_rise=0.3)
    assert zones["dome 0-60°"] == (0.9, -0.9)  # Figure 6.2.16
    assert zones["dome 60-90°"] == (0.5, -0.9)
    zones, _ = _cc(roof_form="arched", roof_angle=20.0, roof_rise=0.25)
    assert zones["3 perimeter"][1] == pytest.approx(-2.6)
    # Interior: Figure 6.2.8 centre half Cp (-0.7 - r) × 0.87 (note 4).
    assert zones["arch centre half"][1] == pytest.approx(-0.87 * 0.95)


def test_tall_building_pitched_roof_takes_the_low_rise_figure() -> None:
    out = fl.cladding_pressures(30.0, 20.0, 50.0, "B", 1.0, roof_form="gable", roof_angle=20.0)
    zones = {z["zone"]: z for z in out["zones"]}
    assert not out["lowRise"]
    assert zones["3"]["GCpNeg"] == pytest.approx(-2.6)  # Figure 6.2.17 note 6
    assert zones["5"]["GCpNeg"] == pytest.approx(-1.8)  # walls: Figure 6.2.17


def test_parapet_on_a_flat_roof() -> None:
    zones, _ = _cc(parapet=1.0)
    assert zones["3"][1] == zones["2"][1]
    # Note 5 of Figure 6.2.11(b): roof zones 2 and 3 take the walls' positive (GCp).
    assert zones["2"][0] == pytest.approx(0.9)


def test_canopy_derivation_takes_the_free_roof_pressures() -> None:
    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate_from_structure
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import default_project_settings
    from saengine.library.shapes import PortalFrame, insert, shape_geometry
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
    )
    model, _, _ = insert(default_structural_model(), shape_geometry(shape))
    settings = default_project_settings("Canopy")
    settings.wind.openStructure.form = "clad"
    settings.wind.enclosure = "open"
    settings.analysis.meshSize = 1500
    building = generate_from_structure(model, "s")
    d = derive_fem(building, objects, default_material_library(), settings)
    names = [p["name"] for p in d.project["load_patterns"]]
    assert {"WX", "WX2", "WXN", "WY", "WY2", "WYN"} <= set(names)
    assert "WI" not in names
    clad = d.summary["cladWind"]
    assert clad["method"] == "openBuilding" and clad["roofForm"] == "pitched"
    assert clad["theta_deg"] == pytest.approx(15, abs=0.01)
    assert "free pitched roof Case A" in clad["labels"]["WX"]

    def total(case: str) -> np.ndarray:
        pattern = next(p for p in d.project["load_patterns"] if p["name"] == case)
        return np.sum([n["forces"][:3] for n in pattern["nodal_loads"]], axis=0)

    # Case A clear at 15°: CNW 1.1 down on the windward half, CNL -0.4 up on the leeward:
    # the net vertical force is -(1.1 - 0.4)/2 · qh·G · the roof's plan area.
    qhg = clad["qh_Pa"] * clad["G"]
    assert total("WX")[2] == pytest.approx(-(1.1 - 0.4) / 2 * qhg * 12 * 18, rel=0.03)

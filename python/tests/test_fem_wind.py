"""Wind loads per storey, the design wind load cases and the wind/earthquake gating (BNBC 2020
Part 6 Sec 2.4.11.2-2.4.11.3, Figure 6.2.9, pp. 559 and 574-575). Values by hand."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.fem import loads as fl
from saengine.fem.loads import (
    WindDesignCases,
    WindLevel,
    leeward_coefficient,
    velocity_pressure,
    wind_design_variants,
    wind_level_forces,
    wind_levels,
    wind_torsion_exempt,
    wind_torsion_moments,
)

# BNBC 2020 Figure 6.2.9 (p. 574): Case 2 0.75 with e = ±0.15 B, Case 3 0.75, Case 4 0.563;
# Sec 2.4.11.3 Exception (p. 559): one storey with h ≤ 9.1 m.
FIG_6_2_9 = WindDesignCases(
    partial=0.75,
    eccentricity=0.15,
    simultaneous=0.75,
    simultaneousTorsional=0.563,
    exemptHeight=9.1,
)
V, EXPOSURE, I = 65.7, "A", 1.0
G, CPW = 0.85, 0.8  # rigid gust factor, windward Cp (the pack's wind table)


def p_net(z: float, roof: float, depth: float, width: float) -> float:
    """Net pressure windward + leeward [kN/m²] at z, by hand."""
    windward = velocity_pressure(z, V, EXPOSURE, I) * G * CPW
    leeward = velocity_pressure(roof, V, EXPOSURE, I) * G * leeward_coefficient(depth / width)
    return windward - leeward


def test_prismatic_building_unchanged() -> None:
    # The old call (one width and depth for all storeys) gives the same forces as wind_levels
    # with that face at every storey, and the resultant at the face's middle.
    heights = [3.0, 6.0, 9.0]
    forces = wind_level_forces(heights, 12.0, 8.0, V, EXPOSURE, I)
    levels = wind_levels(heights, [(0.0, 12.0)] * 3, [8.0] * 3, V, EXPOSURE, I)
    assert forces == pytest.approx([lv.force for lv in levels])
    assert forces[0] == pytest.approx(p_net(3.0, 9.0, 8.0, 12.0) * 12.0 * 3.0)
    assert forces[2] == pytest.approx(p_net(9.0, 9.0, 8.0, 12.0) * 12.0 * 1.5)
    assert all(lv.centre == pytest.approx(6.0) and lv.width == pytest.approx(12.0) for lv in levels)


def test_setback_storey_widths() -> None:
    # A podium 20 m wide (x 0..20) for storeys 1-2 and a tower 10 m wide (x 10..20, flush with
    # the podium's right side) for storeys 3-4, 3 m storeys, wind along Y (depth 15 m and 8 m).
    heights = [3.0, 6.0, 9.0, 12.0]
    spans = [(0.0, 20.0), (0.0, 20.0), (10.0, 20.0), (10.0, 20.0)]
    depths = [15.0, 15.0, 8.0, 8.0]
    levels = wind_levels(heights, spans, depths, V, EXPOSURE, I)
    # Level 2 (6 m) takes 1.5 m of the podium below it and 1.5 m of the tower above it.
    pod, tow = p_net(6.0, 12.0, 15.0, 20.0), p_net(6.0, 12.0, 8.0, 10.0)
    f2 = pod * 20.0 * 1.5 + tow * 10.0 * 1.5
    assert levels[1].force == pytest.approx(f2)
    assert levels[1].width == pytest.approx((20.0 * 1.5 + 10.0 * 1.5) / 3.0)  # 15 m
    assert levels[1].centre == pytest.approx((pod * 30.0 * 10.0 + tow * 15.0 * 15.0) / f2)
    # Tower levels: the tower's own 10 m face, centred at x = 15 m (not the podium's 10 m).
    assert levels[2].force == pytest.approx(p_net(9.0, 12.0, 8.0, 10.0) * 10.0 * 3.0)
    assert (levels[2].width, levels[2].centre) == pytest.approx((10.0, 15.0))
    assert (levels[3].width, levels[3].centre) == pytest.approx((10.0, 15.0))
    # Podium level 1: the podium's whole face both halves.
    assert levels[0].force == pytest.approx(p_net(3.0, 12.0, 15.0, 20.0) * 20.0 * 3.0)
    # The whole-building width (20 m) at every storey, as before, overloads the tower by 2x.
    old = wind_level_forces(heights, 20.0, 15.0, V, EXPOSURE, I)
    assert old[3] / levels[3].force == pytest.approx(
        p_net(12.0, 12.0, 15.0, 20.0) * 20.0 / (p_net(12.0, 12.0, 8.0, 10.0) * 10.0)
    )


def test_setback_torsion_per_part_face() -> None:
    # Figure 6.2.9 (p. 574): e = 0.15·B on each face, so at the setback level the torsion is
    # 0.15·(F_podium·20 + F_tower·10), not 0.15·F·B_mean (B_mean = 15 m, about 10 % low).
    heights = [3.0, 6.0, 9.0, 12.0]
    spans = [(0.0, 20.0), (0.0, 20.0), (10.0, 20.0), (10.0, 20.0)]
    levels = wind_levels(heights, spans, [15.0, 15.0, 8.0, 8.0], V, EXPOSURE, I)
    f_pod = p_net(6.0, 12.0, 15.0, 20.0) * 20.0 * 1.5
    f_tow = p_net(6.0, 12.0, 8.0, 10.0) * 10.0 * 1.5
    moments = wind_torsion_moments(levels, 0.15)
    assert moments[1] == pytest.approx(0.15 * (f_pod * 20.0 + f_tow * 10.0))
    assert moments[1] > 0.15 * levels[1].force * levels[1].width * 1.05
    # Prismatic levels: the one face's B.
    assert moments[0] == pytest.approx(0.15 * levels[0].force * 20.0)
    assert moments[3] == pytest.approx(0.15 * levels[3].force * 10.0)


def test_torsion_is_force_times_eccentricity() -> None:
    levels = [WindLevel(100.0, 6.0, 12.0), WindLevel(80.0, 6.0, 12.0)]
    # e = 0.15 · 12 = 1.8 m: M = F · e.
    assert wind_torsion_moments(levels, 0.15) == pytest.approx([180.0, 144.0])


def test_exemption() -> None:
    assert wind_torsion_exempt(1, 3.2, True, FIG_6_2_9)
    assert not wind_torsion_exempt(1, 10.0, True, FIG_6_2_9)
    assert wind_torsion_exempt(2, 6.4, False, FIG_6_2_9)
    assert not wind_torsion_exempt(2, 6.4, True, FIG_6_2_9)
    assert not wind_torsion_exempt(3, 9.0, False, FIG_6_2_9)


def test_design_variants() -> None:
    v = dict(wind_design_variants({"WX": -1.6}, FIG_6_2_9))
    assert v["Case 1"] == {"WX": -1.6}
    assert v["Case 2 +e"] == pytest.approx({"WX": -1.2, "WTX": 1.2})
    assert v["Case 2 -e"] == pytest.approx({"WX": -1.2, "WTX": -1.2})
    assert v["Case 3 -WY"] == pytest.approx({"WX": -1.2, "WY": -1.2})
    assert v["Case 4 +WY -eX +eY"] == pytest.approx(
        {"WX": -0.563 * 1.6, "WY": 0.563 * 1.6, "WTX": -0.563 * 1.6, "WTY": 0.563 * 1.6}
    )
    assert len(v) == 1 + 2 + 2 + 8
    exempt = dict(wind_design_variants({"WY": 1.0}, FIG_6_2_9, torsion=False))
    assert sorted(exempt) == ["Case 1", "Case 3 +WX", "Case 3 -WX"]
    # A hand-made combination with both directions, or none, stays as it is.
    assert wind_design_variants({"WX": 1.0, "WY": 1.0}, FIG_6_2_9) == [("", {"WX": 1.0, "WY": 1.0})]
    assert wind_design_variants({"WX": 0.0}, FIG_6_2_9) == [("", {})]


# ───────────────────────── in the derived model ─────────────────────────


@pytest.fixture(scope="module")
def bay():
    from test_fem_derive import OBJECTS, PLAN

    from saengine.library import default_material_library
    from saengine.library.bim import generate

    return generate(PLAN, "s"), OBJECTS, default_material_library()


def _derive(bay, extra_mass: bool = False, **site):
    from saengine.fem.derive import derive_fem
    from saengine.library.settings import ExtraMass, default_project_settings

    settings = default_project_settings("Bay")
    update = {"site": settings.site.model_copy(update=site)}
    if extra_mass:
        # 500 kN at the corner (0, 0): the floor's centre of mass moves off the face centres.
        mass = ExtraMass(story="L1", weight=500.0, x=0.0, y=0.0)
        source = settings.analysis.massSource.model_copy(update={"extraMasses": [mass]})
        update["analysis"] = settings.analysis.model_copy(update={"massSource": source})
    settings = settings.model_copy(update=update, deep=True)
    building, objects, materials = bay
    return derive_fem(building, objects, materials, settings, {"bim": "abc"})


def _total(project: dict, name: str) -> np.ndarray:
    pattern = next(p for p in project["load_patterns"] if p["name"] == name)
    return sum((np.array(n["forces"]) for n in pattern["nodal_loads"]), np.zeros(6))


def test_gating_without_z(bay) -> None:
    # A custom site with a wind speed and no Z: wind stays, earthquake is reported missing.
    d = _derive(bay, location="custom", windSpeed=65.7, zoneCoefficient=None)
    assert d.summary["lateralMissing"] == ["Z"]
    assert any("no earthquake loads" in n for n in d.notes)
    assert _total(d.project, "EX")[0] == 0
    assert _total(d.project, "WX")[0] == pytest.approx(d.summary["wind_X_kN"] * 1e3, rel=1e-6)
    assert d.summary["wind_X_kN"] > 0 and "base_shear_kN" not in d.summary


def test_gating_without_wind_speed(bay) -> None:
    # Z and no wind speed: earthquake stays (it used to vanish with the wind), wind reported.
    d = _derive(bay, location="custom", windSpeed=None, zoneCoefficient=0.2)
    assert d.summary["lateralMissing"] == ["windSpeed"]
    assert any("no wind loads" in n for n in d.notes)
    assert _total(d.project, "WX")[0] == 0
    assert _total(d.project, "EX")[0] == pytest.approx(d.summary["base_shear_kN"] * 1e3, rel=1e-6)
    assert d.summary["base_shear_kN"] > 0 and "wind_X_kN" not in d.summary


def test_both_present(bay) -> None:
    d = _derive(bay)  # Dhaka: Z and V from the location
    assert "lateralMissing" not in d.summary
    assert d.summary["wind_X_kN"] > 0 and d.summary["base_shear_kN"] > 0


def test_wind_resultant_at_the_face_centre(bay, monkeypatch) -> None:
    # Whatever the node weights, the resultant of WX at a level lies on the face's centre line
    # y = c (its moment about (x, c) is zero) and that of WY on x = c.
    monkeypatch.setattr(fl, "wind_design_cases", lambda: FIG_6_2_9)
    d = _derive(bay, extra_mass=True)
    coords = {n["id"]: np.array(n["coords"]) for n in d.project["nodes"]}
    for case, axis in (("WX", 0), ("WY", 1)):
        row = d.summary["wind"]["levels"][case][0]
        pattern = next(p for p in d.project["load_patterns"] if p["name"] == case)
        moment = 0.0
        for load in pattern["nodal_loads"]:
            x, y = coords[load["node_id"]][:2]
            fx, fy, mz = load["forces"][0], load["forces"][1], load["forces"][5]
            if axis == 0:
                moment += -(y - row["centre_m"]) * fx + x * fy + mz
            else:
                moment += (x - row["centre_m"]) * fy - y * fx + mz
        # The centre of mass is off the face centre by metres, so the couple matters.
        assert abs(row["offset_m"]) > 0.5
        assert abs(moment) <= 1e-4 * row["force_kN"] * 1e3
    # One storey at 3.2 m: exempt from the torsional cases (Sec 2.4.11.3, Exception).
    assert d.summary["wind"]["exempt"] and d.summary["wind"]["torsionCases"] == []


def test_wind_torsion_rows(bay, monkeypatch) -> None:
    # Not exempt (a 10 m exemption limit lowered to 1 m for the test): WTX's moment at the level
    # is F·e, e = 0.15·B.
    cases = WindDesignCases(0.75, 0.15, 0.75, 0.563, exemptHeight=1.0)
    monkeypatch.setattr(fl, "wind_design_cases", lambda: cases)
    d = _derive(bay)
    assert d.summary["wind"]["torsionCases"] == ["WTX", "WTY"]
    for case in ("WX", "WY"):
        row = d.summary["wind"]["levels"][case][0]
        assert row["e_m"] == pytest.approx(0.15 * row["B_m"])
        assert row["torsion_kNm"] == pytest.approx(row["force_kN"] * row["e_m"])


def test_flexible_analysis_option_keeps_the_torsional_cases(bay, monkeypatch) -> None:
    # The Exception of Sec 2.4.11.3 (p. 559) is for buildings "designed with flexible
    # diaphragms"; diaphragm = "flexible" only models the RC floors' in-plane stiffness, so a
    # one-storey building above the (lowered) height limit still gets Cases 2 and 4.
    from saengine.fem.derive import derive_fem
    from saengine.library.settings import default_project_settings

    cases = WindDesignCases(0.75, 0.15, 0.75, 0.563, exemptHeight=1.0)
    monkeypatch.setattr(fl, "wind_design_cases", lambda: cases)
    settings = default_project_settings("Bay")
    settings = settings.model_copy(
        update={"analysis": settings.analysis.model_copy(update={"diaphragm": "flexible"})},
        deep=True,
    )
    building, objects, materials = bay
    d = derive_fem(building, objects, materials, settings, {"bim": "abc"})
    assert not d.summary["wind"]["exempt"]
    assert d.summary["wind"]["torsionCases"] == ["WTX", "WTY"]


def test_planar_frame_reports_no_width(monkeypatch) -> None:
    # A one-line frame (A1-B1, 6 m along X): wind in X sees no face across it. It used to fall
    # back silently to 1 m; now WX is empty and a note says why, so 0 kN is not read as a result.
    from test_fem_derive import OBJECTS, PLAN

    from saengine.fem.derive import derive_fem
    from saengine.library import FloorPlan, default_material_library
    from saengine.library.bim import generate
    from saengine.library.settings import default_project_settings

    data = PLAN.model_dump(mode="json", by_alias=True)
    data["columns"] = [c for c in data["columns"] if c["at"]["y"] == "1"]
    data["beams"] = [b for b in data["beams"] if b["start"]["y"] == "1" and b["end"]["y"] == "1"]
    data["slabs"] = []
    plan = FloorPlan.model_validate(data)
    d = derive_fem(
        generate(plan, "s"),
        OBJECTS,
        default_material_library(),
        default_project_settings("Line"),
        {"bim": "abc"},
    )
    assert d.summary["wind_X_kN"] == 0 and d.summary["wind_Y_kN"] > 0
    assert d.summary["wind"]["noWidth"] == {"WX": ["Level 1"]}
    assert any(n.startswith("wind in X: no level has any width") for n in d.notes)
    assert not any(n.startswith("wind in Y:") for n in d.notes)

"""Track B2: seismic tables, site class and the remaining Sec 2.5 checks, pinned through the
bnbc2020 code pack (BNBC 2020 Part 6 Sec 2.5, Tables 6.2.19-6.2.21, Eq. 6.2.36, Sec 2.5.5.5,
2.5.14.2-2.5.14.3)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.fem import loads as fl
from saengine.fem import seismic_design as sd
from saengine.library.settings import (
    AdjacentStructure,
    category_site_class,
    default_project_settings,
    derived,
    design_category,
    site_specific_warning,
    system_values,
)


def table():
    return code_context.table("seismic")


# ─────────────────────────────── Table 6.2.19 (pp. 621-624) ───────────────────────────────


def test_plain_masonry_has_an_18_m_limit_in_category_b():
    # Table 6.2.19 A.4 and B.8 (pp. 621-622): 18 m in B, NP in C and D (was no limit in B).
    for key in ("masonryOrdinaryPlain", "masonryOrdinaryPlainFrame"):
        assert table().systems[key].heightLimits == {"B": 18.0, "C": 0.0, "D": 0.0}


@pytest.mark.parametrize(
    ("key", "r", "omega", "cd", "limits"),
    [
        ("rcSpecialBearingWall", 5.0, 2.5, 5.0, (None, None, 50.0)),  # A.1
        ("steelEbfMoment", 8.0, 2.0, 4.0, (None, None, 50.0)),  # B.1
        ("steelOcbf", 3.25, 2.0, 3.25, (None, None, 11.0)),  # B.4
        ("steelImf", 4.5, 3.0, 4.0, (None, None, 35.0)),  # C.2
        ("rcDualSpecialOrdinaryWalls", 6.0, 2.5, 5.0, (None, None, 0.0)),  # D.4
        ("rcDualIntermediateSpecialWalls", 6.5, 2.5, 5.0, (None, None, 50.0)),  # E.2
        ("masonryDualIntermediateFrame", 3.0, 3.0, 3.0, (None, 50.0, 0.0)),  # E.3
        ("rcDualOrdinary", 4.5, 2.5, 4.0, (None, 0.0, 0.0)),  # F
        ("steelNotDetailed", 3.0, 3.0, 3.0, (None, None, 0.0)),  # G
    ],
)
def test_new_rows_of_table_6_2_19(key, r, omega, cd, limits):
    row = table().systems[key]
    assert (row.R, row.Omega0, row.Cd) == (r, omega, cd)
    assert tuple(row.heightLimits[c] for c in "BCD") == limits


def test_every_row_of_table_6_2_19_is_in_the_pack():
    rows = {s.row.split(" ")[0] for s in table().systems.values()}
    expected = {"A.1", "A.2", "A.3", "A.4", "F", "G"}
    expected |= {f"B.{i}" for i in range(1, 9)}
    expected |= {f"C.{i}" for i in range(1, 7)} | {f"D.{i}" for i in range(1, 5)}
    expected |= {f"E.{i}" for i in range(1, 5)}
    assert rows == expected


def test_dual_and_moment_frame_flags():
    systems = table().systems
    assert {k for k, v in systems.items() if v.momentFrame} == {
        "rcSmf", "rcImf", "rcOmf", "steelSmf", "steelOmf", "steelImf"
    }  # fmt: skip
    assert systems["rcDualSpecial"].dual and not systems["rcSmf"].dual
    assert sd.moment_frame_systems() == frozenset(k for k, v in systems.items() if v.momentFrame)


# ─────────────────────────────── Table 6.2.20 (p. 628) ───────────────────────────────


def test_eccentrically_braced_frame_period():
    coefficient = table().periodCoefficients["eccentricallyBracedSteelFrame"]
    assert (coefficient.Ct, coefficient.m) == (0.0731, 0.75)
    assert fl.approximate_period(20.0, "steelEbf") == pytest.approx(0.0731 * 20.0**0.75)
    # A dual system with EBF keeps the "all other" row (shorter period: conservative).
    assert fl.approximate_period(20.0, "steelDualSmfEbf") == pytest.approx(0.0488 * 20.0**0.75)


# ─────────────────────────────── Table 6.2.21 (p. 648) ───────────────────────────────


@pytest.mark.parametrize(
    ("occupancy", "kwargs", "ratio", "row"),
    [
        ("II", {}, 0.020, "other"),
        ("III", {}, 0.015, "other"),
        ("IV", {}, 0.010, "other"),
        ("II", {"storeys": 4, "tolerant": True}, 0.025, "lowRise"),
        ("III", {"storeys": 3, "tolerant": True}, 0.020, "lowRise"),
        ("IV", {"storeys": 2, "tolerant": True}, 0.015, "lowRise"),
        ("II", {"storeys": 5, "tolerant": True}, 0.020, "other"),
        ("II", {"storeys": 3, "tolerant": False}, 0.020, "other"),
        ("I", {"masonry": True, "cantilever": True}, 0.010, "masonryCantilever"),
        ("IV", {"masonry": True}, 0.007, "masonryOther"),
        # masonry structures never take the 4-storey row
        ("II", {"masonry": True, "storeys": 2, "tolerant": True}, 0.007, "masonryOther"),
    ],
)
def test_drift_table_rows(occupancy, kwargs, ratio, row):
    limit = sd.drift_limit(occupancy, **kwargs)
    assert limit["ratio"] == pytest.approx(ratio)
    assert limit["row"] == row


def test_drift_limit_over_redundancy_for_moment_frames_in_d():
    # Sec 2.5.14.1 (p. 647): Δa/ρ for moment frames only, Category D.
    assert sd.allowable_drift_ratio("IV", "D", "rcImf", 1.3) == pytest.approx(0.010 / 1.3)
    assert sd.allowable_drift_ratio("II", "D", "rcSpecialWallFrame", 1.3) == 0.020
    assert sd.allowable_drift_ratio("II", "C", "rcSmf", 1.3) == 0.020
    assert sd.allowable_drift_ratio("II", "D", "masonryOrdinaryPlain") == 0.007


# ─────────────────────────────── Eq. 6.2.36 (p. 613) ───────────────────────────────


def test_damping_correction():
    assert fl.damping_correction(None) == 1.0
    assert fl.damping_correction(0.05) == 1.0
    assert fl.damping_correction(0.02) == pytest.approx(math.sqrt(10 / 7))
    assert fl.damping_correction(0.10) == pytest.approx(math.sqrt(10 / 15))
    assert fl.damping_correction(0.30) == 0.55  # not below 0.55


def test_spectrum_with_damping():
    plain = fl.normalized_spectrum(0.5, "SD")
    assert fl.normalized_spectrum(0.5, "SD", 0.10) == pytest.approx(plain * math.sqrt(10 / 15))
    sa = fl.design_acceleration(0.5, "SD", 0.2, 1.0, 5.0, 0.02)
    assert sa == pytest.approx(2 / 3 * 0.2 / 5 * 2.5 * 1.35 * math.sqrt(10 / 7))


# ─────────────────────────────── Sec 2.5.5.5 (pp. 624-625) ───────────────────────────────


def test_one_system_keeps_its_values():
    s = default_project_settings()
    values = derived(s)
    assert (values["R"], values["Cd"], values["omega"]) == (8.0, 5.5, 3.0)
    assert values["RX"] == values["RY"] == 8.0


def test_different_systems_in_the_two_directions():
    # 2.5.5.5.1: each direction its own R and Cd.
    s = default_project_settings()
    s.seismic.systemY = "rcSpecialWallFrame"
    values = derived(s)
    assert (values["RX"], values["RY"]) == (8.0, 6.0)
    assert (values["CdX"], values["CdY"]) == (5.5, 5.0)
    # One value for the checks that take one: the least R, the largest Cd and Ω0.
    assert (values["R"], values["Cd"], values["omega"]) == (6.0, 5.5, 3.0)


def test_systems_in_the_same_direction():
    # 2.5.5.5.2: the least R, Cd not below the largest, the more stringent limitation.
    s = default_project_settings()
    s.seismic.system = "rcSpecialWallFrame"
    s.seismic.otherSystems = ["steelOcbf"]
    x = system_values(s)["X"]
    assert x["R"] == 3.25 and x["Cd"] == 5.0 and x["Omega0"] == 2.5
    assert x["heightLimits"]["D"] == 11.0
    assert system_values(s)["Y"]["R"] == 3.25  # without a system in Y, both directions


def test_a_not_permitted_system_in_the_combination_is_reported():
    s = default_project_settings()  # Dhaka, SD, category II: SDC D
    s.seismic.otherSystems = ["rcImf"]
    info = design_category(s)
    assert info["sdc"] == "D"
    assert not info["permitted"] and info["notPermitted"] == ["rcImf"]


def test_height_limit_note():
    s = default_project_settings()
    s.seismic.system = "steelOcbf"
    assert sd.height_limit_note(s, "D", 20.0) is not None
    assert sd.height_limit_note(s, "D", 10.0) is None
    assert sd.height_limit_note(s, "C", 20.0) is None


# ─────────────────────────────── S1 / S2 (Sec 2.5.3.1, 2.5.4.3) ───────────────────────────────


def test_site_specific_classes_warn_and_take_the_assumed_class_for_the_category():
    s = default_project_settings()
    study = table().siteSpecificStudy
    assert study.classes == ["S1", "S2"] and study.assumedClass == "SE"
    warning = site_specific_warning(s, ["S2"], "SD")
    assert warning is not None and study.clause in warning
    assert "SD" in warning and "SE" in warning
    assert site_specific_warning(s, ["SE"]) is None
    assert site_specific_warning(s, []) is None
    assert category_site_class(s, "SC", ["S1"]) == "SE"
    assert category_site_class(s, "SC", []) == "SC"
    assert sd.seismic_design_category(1, "SE", "II") == "D"


# ───────────────────── Sec 2.5.14.2 diaphragm deflection, 2.5.14.3 separation ─────────────────────


def _frame_and_floor():
    """Four columns (0-3 at z = 0, 4-7 at z = 3 m) and a node 8 in the middle of the floor."""
    nodes = []
    corners = [(0.0, 0.0), (6.0, 0.0), (6.0, 6.0), (0.0, 6.0)]
    for i, (x, y) in enumerate(corners):
        nodes.append({"id": i, "coords": [x, y, 0.0]})
        nodes.append({"id": i + 4, "coords": [x, y, 3.0]})
    nodes.append({"id": 8, "coords": [3.0, 3.0, 3.0]})
    elements = [{"id": i, "nodes": [i, i + 4]} for i in range(4)]
    elements.append({"id": 9, "nodes": [4, 5, 6, 7]})
    return {"nodes": nodes, "elements": elements}


def _spectra(top: float, middle: float) -> dict:
    peaks = {i: np.array([top, 0.0, 0.0]) for i in range(4, 8)}
    peaks[8] = np.array([middle, 0.0, 0.0])
    peaks.update({i: np.zeros(3) for i in range(4)})
    mode = {"angular_frequency": 10.0}
    return {"X": {"modes": [mode], "peaks": [peaks], "damping": 0.05, "rule": "SRSS"}}


def test_diaphragm_deflection_relative_to_the_vertical_elements():
    project = _frame_and_floor()
    rows = sd.diaphragm_deflections(project, _spectra(0.010, 0.014), [0.0, 3.0], 5.5, 10.0)
    assert len(rows) == 1
    assert rows[0]["deflection"] == pytest.approx(5.5 * 0.004)
    assert rows[0]["limit"] == pytest.approx(0.010) and rows[0]["ok"] is False
    # A floor moving rigidly with its columns: nothing to report.
    assert sd.diaphragm_deflections(project, _spectra(0.010, 0.010), [0.0, 3.0], 5.5) == []
    no_limit = sd.diaphragm_deflections(project, _spectra(0.010, 0.014), [0.0, 3.0], 5.5)
    assert no_limit[0]["ok"] is None
    assert sd.diaphragm_notes(no_limit, None)  # reported, with a request for the limit


def test_separation_to_the_property_line_and_between_units():
    project = _frame_and_floor()
    s = default_project_settings()
    s.seismic.propertyLineGap = 50.0
    s.seismic.adjacent = [
        AdjacentStructure(name="Block B", gap=60.0, displacement=30.0, sameFloorLevels=True),
        AdjacentStructure(name="Neighbour", gap=40.0, sameProperty=False),
    ]
    result = sd.separation_checks(project, _spectra(0.010, 0.010), [0.0, 3.0], 5.0, s)
    delta = 5.0 * 0.010
    assert result["maxDisplacement"] == pytest.approx(delta)
    checks = {c["name"]: c for c in result["checks"]}
    # (i) the property line: δmax
    assert checks["property line"]["required"] == pytest.approx(delta)
    assert checks["property line"]["ok"]
    # (ii) same property: SRSS of the two, (iii) × 0.7 for the same floor levels
    assert checks["Block B"]["required"] == pytest.approx(0.7 * math.hypot(delta, 0.030))
    assert checks["Block B"]["ok"]
    assert checks["Neighbour"]["required"] == pytest.approx(delta)
    assert not checks["Neighbour"]["ok"]
    assert len(result["notes"]) == 1
    rule = table().separation
    assert (rule.sameProperty, rule.equalFloorLevelsFactor) == ("srss", 0.7)

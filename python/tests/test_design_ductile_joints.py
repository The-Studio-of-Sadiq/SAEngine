"""Capacity design of moment frames for earthquake (BNBC 2020 Part 6 Sec 8.3): probable moments,
strong column / weak beam, joint shear and anchorage, capacity-design shear, foundations and
members outside the seismic system, against hand calculations on synthetic sections."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.design.ductile_joints import (
    FrameJoint,
    JointBeam,
    JointColumn,
    Stirrups,
    beam_capacity_shear,
    beam_limited_column_shear,
    beam_moments,
    column_capacity_shear,
    column_dowel_checks,
    column_moment,
    column_near_footing_edge,
    frame_joints,
    grade_beam_tie_check,
    hooked_anchorage_seismic,
    hooked_development,
    induced_forces,
    joint_beam_mpr,
    joint_checks,
    joint_confinement,
    lowest_column_moment,
    non_sfrs_checks,
    pile_confined_length,
    probable_section,
    seismic_demands,
    strong_column_checks,
)
from saengine.design.rc import DesignError, section_of
from saengine.library.bim import BuildingModel
from saengine.library.objects import Beam, Column, LinearReinforcement, RectangleProfile

FC, FY, ES = 25.0, 420.0, 200_000.0
BAR20 = math.pi * 20**2 / 4
KN, KNM = 1e3, 1e6


def reinforcement(groups: list[dict], transverse: dict | None = None) -> LinearReinforcement:
    return LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": groups,
            "transverse": transverse or {"type": "stirrup", "dia": 10, "spacing": 100, "legs": 2},
        }
    )


def beam_section(top: int = 3, bottom: int = 3, width: float = 300):
    groups = [{"position": "bottom", "count": bottom, "dia": 20}]
    if top:
        groups.append({"position": "top", "count": top, "dia": 20})
    profile = RectangleProfile(xDim=width, yDim=500)
    return section_of(profile, reinforcement(groups), FC, FY, ES)


def column_section(size: float = 400):
    groups = [{"position": "perimeter", "count": 4, "dia": 20}]
    tie = {"type": "tie", "dia": 10, "spacing": 100, "legs": 2}
    return section_of(RectangleProfile(xDim=size, yDim=size), reinforcement(groups, tie), FC, FY)


def rect_mn(b: float, h: float, layers: list[tuple[float, float]], fy: float, p: float = 0.0):
    """Hand strain compatibility of a rectangle: the ACI stress block (0.85 f'c over β1 c,
    εcu = 0.003, β1 = 0.85 at 25 MPa), bars elastic-perfectly plastic at ``fy``, bars inside the
    block displacing its concrete; ``layers`` (depth from the compression face, area). Returns
    the moment about mid-depth [N·mm] at axial force ``p`` (compression positive)."""

    def forces(c: float) -> tuple[float, float]:
        a = 0.85 * c
        n = 0.85 * FC * min(a, h) * b
        m = n * (h / 2 - min(a, h) / 2)
        for y, area in layers:
            fs = max(-fy, min(fy, ES * 0.003 * (c - y) / c))
            if y < a:
                fs -= 0.85 * FC
            n += area * fs
            m += area * fs * (h / 2 - y)
        return n, m

    lo, hi = 1e-3, 10 * h
    for _ in range(200):
        c = (lo + hi) / 2
        if forces(c)[0] > p:
            hi = c
        else:
            lo = c
    return forces((lo + hi) / 2)[1]


# Bars rest on the 10 mm stirrup inside 40 mm cover: centres 60 mm from the faces.
BEAM_LAYERS = [(60.0, 3 * BAR20), (440.0, 3 * BAR20)]
COLUMN_LAYERS = [(60.0, 2 * BAR20), (340.0, 2 * BAR20)]


# ─────────────────────────────────────── strengths ───────────────────────────────────────


def test_probable_moment_of_a_singly_reinforced_beam_by_hand() -> None:
    # 300 x 500, 3T20 bottom only, d = 500 - 40 - 10 - 10 = 440 mm.
    section = beam_section(top=0)
    m = beam_moments(section)
    as_ = 3 * BAR20
    a = as_ * 1.25 * FY / (0.85 * FC * 300)  # 77.6 mm
    mpr = as_ * 1.25 * FY * (440 - a / 2)  # 198.5 kN·m
    a_n = as_ * FY / (0.85 * FC * 300)
    mn = as_ * FY * (440 - a_n / 2)  # 161.9 kN·m
    assert m.mpr_sag == pytest.approx(mpr, rel=2e-3)
    assert mpr / KNM == pytest.approx(198.5, abs=0.1)
    assert m.mn_sag == pytest.approx(mn, rel=2e-3)
    assert m.mpr_hog == 0.0  # no top bars
    assert m.as_bottom == pytest.approx(as_)


def test_probable_moment_doubly_reinforced_matches_strain_compatibility() -> None:
    m = beam_moments(beam_section())
    assert m.mpr_hog == pytest.approx(rect_mn(300, 500, BEAM_LAYERS, 1.25 * FY), rel=3e-3)
    assert m.mn_sag == pytest.approx(rect_mn(300, 500, BEAM_LAYERS, FY), rel=3e-3)


def test_column_moment_at_axial_force_by_hand() -> None:
    section = column_section()
    hand = rect_mn(400, 400, COLUMN_LAYERS, FY, p=500 * KN)
    assert column_moment(section, 500 * KN, 0.0) == pytest.approx(hand, rel=3e-3)
    assert column_moment(section, 500 * KN, math.pi / 2) == pytest.approx(hand, rel=3e-3)
    probable = column_moment(probable_section(section), 500 * KN, 0.0)
    assert probable == pytest.approx(rect_mn(400, 400, COLUMN_LAYERS, 1.25 * FY, 500 * KN), 3e-3)
    # Lowest over a range: at an end (here the tension-side end, P = 0, below the balance).
    low, p = lowest_column_moment(section, 0.0, 500 * KN, 0.0)
    assert p == 0.0
    assert low == pytest.approx(rect_mn(400, 400, COLUMN_LAYERS, FY, 0.0), rel=3e-3)


# ─────────────────────────────────── joints ───────────────────────────────────


def interior_joint(height: float = 3000.0) -> FrameJoint:
    return FrameJoint(
        id="C1@3000",
        position=(0.0, 0.0),
        level=3000.0,
        below="C1",
        above="C1",
        beams=[
            JointBeam("B1", "BM", (-1.0, 0.0), 5000.0),
            JointBeam("B2", "BM", (1.0, 0.0), 5000.0),
        ],
        height_below=height,
        height_above=height,
    )


def joint_column(p: float = 500 * KN) -> JointColumn:
    return JointColumn(column_section(), 0.0, p, p, cover=40.0, tie_dia=10.0)


def test_strong_column_weak_beam_at_an_interior_joint_by_hand() -> None:
    joint = interior_joint()
    beams = {"BM": beam_section()}
    rows, _ = strong_column_checks(
        joint, beams, joint_column(), joint_column(), RectangleProfile(xDim=400, yDim=400)
    )
    assert len(rows) == 1  # beams along x only
    row = rows[0]
    mnc = 2 * rect_mn(400, 400, COLUMN_LAYERS, FY, 500 * KN)
    # One beam hogging, the other sagging: equal bars, so Mn- + Mn+ = 2 Mn.
    mnb = 2 * rect_mn(300, 500, BEAM_LAYERS, FY)
    assert row["capacity"] == pytest.approx(mnc / KNM, rel=5e-3)
    assert row["demand"] == pytest.approx(1.2 * mnb / KNM, rel=5e-3)
    assert row["ok"] == (mnc >= 1.2 * mnb)
    assert not row["flag"]  # 500 kN > 0.1 Ag f'c = 400 kN
    # Light columns: reported only (8.3.5.2(a)).
    light, _ = strong_column_checks(
        joint,
        beams,
        joint_column(300 * KN),
        joint_column(300 * KN),
        RectangleProfile(xDim=400, yDim=400),
    )
    assert light[0]["flag"]


def test_strong_column_uses_the_axes_of_each_column() -> None:
    # 800 x 400 column below at 0°, the same section above turned 90° in plan, beams along x.
    groups = [{"position": "perimeter", "count": 4, "dia": 20}]
    tie = {"type": "tie", "dia": 10, "spacing": 100, "legs": 2}
    profile = RectangleProfile(xDim=800, yDim=400)
    section = section_of(profile, reinforcement(groups, tie), FC, FY)
    p = 1000 * KN
    below = JointColumn(section, 0.0, p, p)
    above = JointColumn(section, 90.0, p, p)
    rows, _ = strong_column_checks(interior_joint(), {"BM": beam_section()}, below, above, profile)
    strong = rect_mn(400, 800, [(60.0, 2 * BAR20), (740.0, 2 * BAR20)], FY, p)
    weak = rect_mn(800, 400, COLUMN_LAYERS, FY, p)
    assert rows[0]["capacity"] == pytest.approx((strong + weak) / KNM, rel=5e-3)
    assert weak < 0.6 * strong  # turning the column above matters


def test_joint_shear_interior_joint_by_hand() -> None:
    joint = interior_joint()
    beams = {"BM": beam_section()}
    rows, _ = joint_checks(
        joint, beams, joint_column(), joint_column(), RectangleProfile(xDim=400, yDim=400)
    )
    shear_row = next(r for r in rows if r["name"].startswith("Joint shear"))
    t = 1.25 * FY * (3 * BAR20 + 3 * BAR20)  # 989.6 kN
    mpr = 2 * rect_mn(300, 500, BEAM_LAYERS, 1.25 * FY)
    vcol = mpr / 3000  # contraflexure at mid-height above and below
    assert shear_row["demand"] == pytest.approx((t - vcol) / KN, rel=5e-3)
    # Two opposite faces covered (300 >= 0.75 x 400): γ = 1.2; Aj = 400 x min(400, 300 + 400).
    assert shear_row["capacity"] == pytest.approx(0.85 * 1.2 * 5 * 400 * 400 / KN, rel=1e-4)
    through = next(r for r in rows if r["name"].startswith("Beam bars through"))
    assert through["demand"] == 400 and through["capacity"] == 400 and through["ok"]


def test_joint_shear_exterior_joint_and_hooked_anchorage_by_hand() -> None:
    joint = interior_joint()
    joint.beams = joint.beams[1:]  # B2 only: the beam bars end in the joint
    joint.above = None
    beams = {"BM": beam_section()}
    rows, notes = joint_checks(
        joint, beams, joint_column(), None, RectangleProfile(xDim=400, yDim=400)
    )
    shear_row = next(r for r in rows if r["name"].startswith("Joint shear"))
    t = 1.25 * FY * 3 * BAR20
    vcol = rect_mn(300, 500, BEAM_LAYERS, 1.25 * FY) / 1500  # the column below only
    assert shear_row["demand"] == pytest.approx((t - vcol) / KN, rel=5e-3)
    assert shear_row["capacity"] == pytest.approx(0.85 * 1.0 * 5 * 400 * 400 / KN, rel=1e-4)
    anchor = next(r for r in rows if r["name"].startswith("Beam bar anchorage"))
    assert anchor["demand"] == pytest.approx(420 * 20 / (5.4 * 5), abs=0.01)  # 311.1 mm
    assert anchor["capacity"] == 400 - 40 - 10
    assert any("ends at this joint" in n for n in notes)


def test_joint_confinement_classes() -> None:
    profile = RectangleProfile(xDim=400, yDim=400)
    beams = {"W": beam_section(width=300), "N": beam_section(width=250)}
    joint = interior_joint()
    joint.beams += [
        JointBeam("B3", "W", (0.0, 1.0), 4000.0),
        JointBeam("B4", "W", (0.0, -1.0), 4000.0),
    ]
    joint.beams[0].type = joint.beams[1].type = "W"
    assert joint_confinement(joint, beams, profile, 0.0) == (1.7, 4, True)
    joint.beams[3].type = "N"  # 250 < 300: that face is not confined
    assert joint_confinement(joint, beams, profile, 0.0)[:2] == (1.2, 3)
    joint.beams = joint.beams[:1] + joint.beams[2:3]  # two adjacent faces
    assert joint_confinement(joint, beams, profile, 0.0)[:2] == (1.0, 2)


def test_hooked_development_lengths_by_hand() -> None:
    assert hooked_anchorage_seismic(20, 420, 25) == pytest.approx(311.11, abs=0.01)
    assert hooked_anchorage_seismic(12, 420, 25) == pytest.approx(186.67, abs=0.01)
    assert hooked_anchorage_seismic(10, 420, 40) == 150.0  # 123 mm and 8 db = 80 mm
    assert hooked_anchorage_seismic(20, 420, 25, lam=0.75) == pytest.approx(388.89, abs=0.01)
    # Sec 8.2.6.2: 0.24 fy db / √f'c.
    assert hooked_development(20, 420, 25) == pytest.approx(403.2)
    rows = column_dowel_checks("C1", 20, 420, 25, 500, 75, 16)
    assert rows[0]["capacity"] == 500 - 75 - 32 and not rows[0]["ok"]  # 403 > 393 mm


# ─────────────────────────────────── capacity-design shear ───────────────────────────────────


def test_beam_capacity_shear_with_gravity_load_and_vc_zero_by_hand() -> None:
    section = beam_section()
    stirrups = Stirrups(10, 2, 100)
    rows = beam_capacity_shear(section, 5000, 60 * KN, 50 * KN, stirrups)
    mpr = rect_mn(300, 500, BEAM_LAYERS, 1.25 * FY)
    v_sway = 2 * mpr / 5000
    ve = v_sway + 60 * KN
    assert rows[0]["demand"] == pytest.approx(ve / KN, rel=5e-3)
    assert v_sway >= 0.5 * ve  # so Vc = 0 (8.3.8.2(a), no axial force)
    vs = 2 * math.pi * 25 * 420 * 440 / 100  # Av fyt d / s
    assert rows[0]["capacity"] == pytest.approx(0.75 * vs / KN, rel=1e-3)
    need = ve / 0.75 / (420 * 440)
    assert rows[1]["demand"] == pytest.approx(need, rel=5e-3)
    assert rows[1]["capacity"] == pytest.approx(2 * math.pi * 25 / 100, rel=1e-3)
    assert "Vc = 0.0 kN (0:" in rows[0]["note"]


def test_beam_capacity_shear_keeps_vc_when_gravity_dominates() -> None:
    section = beam_section()
    rows = beam_capacity_shear(section, 5000, 200 * KN, 0.0, Stirrups(10, 2, 100))
    vc = 0.17 * 5 * 300 * 440  # 112.2 kN, Av >= Av,min
    vs = 2 * math.pi * 25 * 420 * 440 / 100
    assert rows[0]["capacity"] == pytest.approx(0.75 * (vc + vs) / KN, rel=1e-3)
    # Axial compression above 0.05 Ag f'c also keeps Vc, whatever the earthquake share.
    loaded = beam_capacity_shear(section, 5000, 60 * KN, 0.0, Stirrups(10, 2, 100), 200 * KN)
    assert loaded[0]["capacity"] == pytest.approx(0.75 * (vc + vs) / KN, rel=1e-3)


def test_intermediate_frame_beam_takes_the_smaller_shear() -> None:
    section = beam_section()
    mn = rect_mn(300, 500, BEAM_LAYERS, FY)
    from_moments = 2 * mn / 5000 + 60 * KN
    rows = beam_capacity_shear(
        section, 5000, 60 * KN, 0, Stirrups(10, 2, 100), level="intermediate"
    )
    assert rows[0]["demand"] == pytest.approx(from_moments / KN, rel=5e-3)
    rows = beam_capacity_shear(
        section, 5000, 60 * KN, 0, Stirrups(10, 2, 100), level="intermediate", doubled_e_shear=90e3
    )
    assert rows[0]["demand"] == pytest.approx(90.0)


def test_column_capacity_shear_by_hand() -> None:
    section = column_section()
    rows = column_capacity_shear(
        section,
        0.0,
        np.array([1.0, 0.0]),
        2500,
        500 * KN,
        500 * KN,
        20 * KN,
        None,
        Stirrups(10, 2, 100),
    )
    mpr = rect_mn(400, 400, COLUMN_LAYERS, 1.25 * FY, 500 * KN)
    assert rows[0]["demand"] == pytest.approx(2 * mpr / 2500 / KN, rel=5e-3)
    # 500 kN > 0.05 Ag f'c = 200 kN: Vc stays, 0.17 √f'c bw d with d = 340 mm.
    vc = 0.17 * 5 * 400 * 340
    vs = 2 * math.pi * 25 * 420 * 340 / 100
    assert rows[0]["capacity"] == pytest.approx(0.75 * (vc + vs) / KN, rel=1e-3)
    # Limited by the beams: their Mpr shared half and half at both joints.
    limit = beam_limited_column_shear(100 * KNM, 100 * KNM, 2500)
    assert limit == pytest.approx(40 * KN)
    rows = column_capacity_shear(
        section,
        0.0,
        np.array([1.0, 0.0]),
        2500,
        100 * KN,
        100 * KN,
        0.0,
        limit,
        Stirrups(10, 2, 100),
    )
    assert rows[0]["demand"] == pytest.approx(40.0)
    # Light axial force, all earthquake shear: Vc = 0.
    assert rows[0]["capacity"] == pytest.approx(0.75 * vs / KN, rel=1e-3)


def test_joint_beam_mpr_per_direction() -> None:
    mpr = joint_beam_mpr(interior_joint(), {"BM": beam_section()}, 0.0)
    assert set(mpr) == {"x"}
    hog = rect_mn(300, 500, BEAM_LAYERS, 1.25 * FY)
    assert mpr["x"] == pytest.approx(2 * hog, rel=5e-3)


# ─────────────────────────────────── connectivity ───────────────────────────────────


def test_frame_joints_from_the_building_model() -> None:
    building = BuildingModel.model_validate(
        {
            "elements": [
                {
                    "kind": "column",
                    "id": "C1",
                    "type": "COL",
                    "position": [0, 0],
                    "bottom": 0,
                    "top": 6000,
                },
                {
                    "kind": "beam",
                    "id": "B1",
                    "type": "BM",
                    "start": [-5000, 0],
                    "end": [0, 0],
                    "elevation": 3000,
                },
                {
                    "kind": "beam",
                    "id": "B2",
                    "type": "BM",
                    "start": [0, 0],
                    "end": [5000, 0],
                    "elevation": 3000,
                },
                {
                    "kind": "beam",
                    "id": "B3",
                    "type": "BM",
                    "start": [0, -4000],
                    "end": [0, 4000],
                    "elevation": 6000,
                },
            ]
        }
    )
    column = Column.model_validate(
        {
            "id": "COL",
            "name": "C",
            "material": "M25",
            "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
        }
    )
    beam = Beam.model_validate(
        {
            "id": "BM",
            "name": "B",
            "material": "M25",
            "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
        }
    )
    joints = {j.level: j for j in frame_joints(building, {"COL": column, "BM": beam})}
    assert set(joints) == {3000.0, 6000.0}
    first = joints[3000.0]
    assert first.above == "C1" and first.height_below == 3000 and first.height_above == 3000
    assert sorted(b.direction for b in first.beams) == [(-1.0, 0.0), (1.0, 0.0)]
    roof = joints[6000.0]
    assert roof.above is None
    # B3 runs through the column: one beam on each side.
    assert sorted(b.direction for b in roof.beams) == [(0.0, -1.0), (0.0, 1.0)]
    assert all(b.length == 4000 for b in roof.beams)


def frame_types() -> dict:
    column = Column.model_validate(
        {
            "id": "COL",
            "name": "C",
            "material": "M25",
            "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
        }
    )
    beam = Beam.model_validate(
        {
            "id": "BM",
            "name": "B",
            "material": "M25",
            "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
        }
    )
    return {"COL": column, "BM": beam}


def element_column(id_: str, bottom: float, top: float) -> dict:
    return {
        "kind": "column",
        "id": id_,
        "type": "COL",
        "position": [0, 0],
        "bottom": bottom,
        "top": top,
    }


def element_beam(id_: str, start: list, end: list, elevation: float) -> dict:
    return {
        "kind": "beam",
        "id": id_,
        "type": "BM",
        "start": start,
        "end": end,
        "elevation": elevation,
    }


def test_frame_joints_column_above_spanning_storeys() -> None:
    # C1 0-3000, C2 3000-9000 standing on it, beams at 3000, 6000, 9000: the storey above the
    # joint at 3000 is up to the next joint on C2 (6000), not C2's top.
    building = BuildingModel.model_validate(
        {
            "elements": [
                element_column("C1", 0, 3000),
                element_column("C2", 3000, 9000),
                *(element_beam(f"B{z}", [0, 0], [5000, 0], z) for z in (3000, 6000, 9000)),
            ]
        }
    )
    joints = {j.level: j for j in frame_joints(building, frame_types())}
    assert set(joints) == {3000.0, 6000.0, 9000.0}
    first = joints[3000.0]
    assert first.below == "C1" and first.above == "C2"
    assert (first.height_below, first.height_above) == (3000, 3000)
    assert (joints[6000.0].height_below, joints[6000.0].height_above) == (3000, 3000)


def test_frame_joints_ignore_a_stub_beam_inside_the_column() -> None:
    # A 200 mm stub inside a 400 mm column's reach at 3000 frames no side: the joint at 6000
    # measures its storey from the column bottom.
    building = BuildingModel.model_validate(
        {
            "elements": [
                element_column("C1", 0, 9000),
                element_beam("S", [-100, 0], [100, 0], 3000),
                element_beam("B6", [0, 0], [5000, 0], 6000),
                element_beam("B9", [0, 0], [5000, 0], 9000),
            ]
        }
    )
    joints = {j.level: j for j in frame_joints(building, frame_types())}
    assert set(joints) == {6000.0, 9000.0}
    assert joints[6000.0].height_below == 6000 and joints[6000.0].height_above == 3000


def test_capacity_shear_frame_levels() -> None:
    # Sec 8.3.9 (ordinary frames) has no capacity-design shear rule: no rows.
    assert (
        beam_capacity_shear(beam_section(), 5000, 50e3, 0, Stirrups(10, 2, 100), level="ordinary")
        == []
    )
    rows = column_capacity_shear(
        column_section(), 0.0, np.array([1.0, 0.0]), 2500, 500e3, 500e3, level="ordinary"
    )
    assert rows == []
    with pytest.raises(DesignError):
        beam_capacity_shear(beam_section(), 5000, 50e3, level="SMRF")


def test_seismic_demands_from_pieces() -> None:
    forces = np.array([[-500e3, 80e3, 0, 0, 0, 0], [-480e3, 70e3, 0, 0, 0, 0]])
    sway = np.array([[-50e3, 50e3, 0, 0, 0, 0], [-40e3, 40e3, 0, 0, 0, 0]])
    piece = SimpleNamespace(forces=[forces], sway=[sway])

    def profile_forces(_piece, _turned, f):
        return {"P": -f[:, 0], "Vy": f[:, 1]}

    d = seismic_demands([piece], [0], False, profile_forces)
    assert (d.pmin, d.pmax) == (480e3, 500e3)
    assert d.shear == 80e3 and d.gravity_shear == 30e3 and d.doubled_e_shear == 130e3


# ─────────────────────────────────────── foundations ───────────────────────────────────────


def test_tie_beam_force_is_ten_percent_of_the_larger_column_load() -> None:
    from saengine.substructure.shallow import tie_force

    loads = SimpleNamespace(
        bases={"C1": object(), "C2": object()},
        max_axial={"C1": 1500e3, "C2": 2200e3}.get,
    )
    force, governing = tie_force(loads, [("F1", ["C1"]), ("F2", ["C2"])])
    assert force == pytest.approx(220e3) and governing == "C2"


def test_foundation_rules() -> None:
    # 400 mm column 150 mm from the edge of a 600 mm deep footing: within t/2 = 300 mm.
    assert column_near_footing_edge((0, 0), (400, 400), (-350, 0), (1500, 2000), 600)
    assert not column_near_footing_edge((0, 0), (400, 400), (0, 0), (2000, 2000), 600)
    row = grade_beam_tie_check("TB1", 300, 450, 200)
    assert row["capacity"] == 150 and not row["ok"]
    assert grade_beam_tie_check("TB1", 700, 700, 250)["capacity"] == 300
    assert pile_confined_length(500) == 2500
    assert pile_confined_length(300) == 1800
    assert pile_confined_length(300, 2000) == 3800
    # Sec 1.8.5.1 (p 507): Sec 8.3 detailing over 120 % of the flexural length when longer.
    assert pile_confined_length(500, 0, flexural_length=4000) == pytest.approx(4800)
    assert pile_confined_length(500, 0, flexural_length=1500) == 2500


# ─────────────────────────────── members outside the seismic system ───────────────────────────────


def test_non_sfrs_member_paths() -> None:
    assert induced_forces(np.array([10.0, -20.0]), np.array([5.0, 4.0]), 5.5) == pytest.approx(42.0)
    section = beam_section()
    stirrups = Stirrups(10, 2, 250)
    rows, notes = non_sfrs_checks(
        "B9", section, 0.0, 100 * KNM, 50 * KN, 150 * KNM, 200 * KN, "D", stirrups
    )
    assert any("8.3.12.2(a)" in n for n in notes)
    spacing = next(r for r in rows if r["name"].startswith("Stirrup spacing"))
    assert spacing["capacity"] == pytest.approx(220) and not spacing["ok"]  # d / 2
    rows, notes = non_sfrs_checks(
        "B9", section, 0.0, 180 * KNM, 50 * KN, 150 * KNM, 200 * KN, "D", stirrups
    )
    assert any("8.3.12.3" in n for n in notes)
    column = column_section()
    rows, notes = non_sfrs_checks(
        "C9", column, 1000 * KN, 50 * KNM, 20 * KN, 150 * KNM, 200 * KN, "D", Stirrups(10, 2, 150)
    )
    tie = next(r for r in rows if r["name"].startswith("Tie spacing"))
    assert tie["capacity"] == 120  # so = min(6 x 20, 150)
    assert any("8.3.12.2(b)" in n for n in notes)
    _, notes = non_sfrs_checks(
        "C9",
        column,
        0.4 * column.p0,
        50 * KNM,
        20 * KN,
        150 * KNM,
        200 * KN,
        "D",
        Stirrups(10, 2, 100),
    )
    assert any("8.3.12.2(c)" in n for n in notes)
    _, notes = non_sfrs_checks("B9", section, 0.0, 180 * KNM, 0, 150 * KNM, 1, "C")
    assert any("8.3.9.1(a)" in n for n in notes)

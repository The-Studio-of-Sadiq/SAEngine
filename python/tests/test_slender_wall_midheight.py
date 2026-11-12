"""R2-1 of re-walk 2: the alternative design of slender walls works from the midheight
section (the default pack's BNBC 2020 Part 6 Sec 6.6.8.2.1: a simply supported panel, the
largest moment and deflection at midspan; Sec 6.6.8.2.6 and Sec 6.6.8.3: Pu/Ag and Mua "at
midheight"). The bottom and top cuts of a pier carry the end moments of the frame the wall is in
(out-of-plane bending in double curvature); taken as the midheight moment they failed the 6 m x
250 mm shear wall W2 of the re-walk project, so its wall type got no bars at all."""

from __future__ import annotations

import pytest

from saengine.codes import context as code_context
from saengine.design import walls as W
from saengine.design.rc_detailing import concrete_modulus

# W2/L1/P1 of the re-walk project: 6000 x 250 mm, storey 3600 mm, C24.1, B420, Ø10 @ 200
# each way in two layers; its governing out-of-plane forces at the bottom and middle cuts.
GEOMETRY = W.WallGeometry(6000, 250, 13200, 3600)
BARS = W.WallBars(25, 10, 200, 10, 200, 2)
FC, FY, ES = 24.1, 420.0, 200000.0
BOTTOM = W.PierForces("Ω0 E", 754.3e3, 1224e3, 6454e6, 0.0, 423.1e6, where="P1 bottom")
MIDDLE = W.PierForces("Ω0 E", 1782.3e3, 1372e3, 5314e6, 0.0, -192.8e6, where="P1 middle")


def _strength(rows):
    return next(r for r in rows if r["name"].startswith("Slender wall: φMn >= Mu"))


def test_slender_method_takes_the_midheight_cut():
    rows = W.slender_wall_checks(GEOMETRY, BARS, [BOTTOM, MIDDLE], FC, FY, ES, required=True)
    row = _strength(rows)
    assert row["ok"]
    assert "Mua = 192.8 kN·m at midheight (P1 middle)" in row["note"]
    # Mu = Mua / (1 - 5 Pu lc² / (0.75 48 Ec Icr)) (Eq 6.6.94) of the middle cut's forces.
    rules = code_context.current().table("wallMethods").slender
    d = 250 - 25 - 10 - 10 / 2
    as_ = W.bar_area(10) * 6000 / 200
    ec, _ = concrete_modulus(FC)
    section = W.slender_section(6000, 250, d, as_, MIDDLE.P, FC, FY, ES, ec, rules)
    mu, _ = W.second_order_moment(192.8e6, MIDDLE.P, 3600, ec, section.icr, rules)
    assert row["demand"] == pytest.approx(mu / 1e6, abs=0.01)  # 211.8 kN·m
    assert row["capacity"] == pytest.approx(0.9 * section.mn / 1e6, abs=0.01)
    # The axial stress of Sec 6.6.8.2.6 is the midheight one as well.
    assert rows[0]["demand"] == pytest.approx(MIDDLE.P / (6000 * 250), abs=0.01)


def test_forces_without_cuts_are_all_taken():
    # Forces given per combination only (no cut marked): every row, as before. With the bottom
    # cut's end moment as the midheight moment the wall fails, as it did in the re-walk.
    plain = W.PierForces("Ω0 E", 754.3e3, 1224e3, 6454e6, 0.0, 423.1e6)
    row = _strength(W.slender_wall_checks(GEOMETRY, BARS, [plain], FC, FY, ES, required=True))
    assert not row["ok"]
    assert row["demand"] == pytest.approx(445.9, abs=0.5)  # 423.1 kN·m with P-Δ (re-walk)


def test_wall_checks_pass_the_slender_rows_with_the_end_moments():
    design = W.wall_checks(GEOMETRY, BARS, [BOTTOM, MIDDLE], FC, FY, ES)
    slender = [c for c in design.checks if c["name"].startswith("Slender wall")]
    assert slender and all(c["ok"] for c in slender)


def test_the_proposal_gives_the_wall_type_bars():
    # The design proposal of the wall type with W2's forces: bars (end bars for the in-plane
    # moment), checked again on the pier, where it said "section too small ... no bars".
    from saengine.design import wall_design
    from saengine.library.objects import BarMesh, Wall, WallReinforcement

    wall = Wall(
        id="W250",
        name="Wall 250",
        material="C24.1",
        thickness=250,
        reinforcement=WallReinforcement(
            material="B420",
            cover=25,
            vertical=BarMesh(dia=10, spacing=200),
            horizontal=BarMesh(dia=10, spacing=200),
            layers=2,
        ),
    )
    collected = {
        "id": "W2/L1/P1",
        "wall": "W2",
        "type": "W250",
        "object": wall,
        "geometry": GEOMETRY,
        "forces": [BOTTOM, MIDDLE],
        "fc": FC,
        "fy": FY,
        "es": ES,
        "special": False,
        "drift": None,
    }
    original = {"id": "W250", "name": "Wall 250", "kind": "wall", "material": "C24.1"}
    (entry,) = wall_design.proposal_entries([collected], {"W250"}, {"W250": original})
    assert entry["status"] == "ok", entry["tooSmall"]
    assert entry["proposed"]["boundary"]["count"] >= 2
    assert entry["utilisation"]["piers"] <= 1.0

"""Punching shear with shear reinforcement (saengine.design.punching), by hand: interior, edge
and corner columns with moment transfer, an opening, headed studs (vs, the outer section),
stirrups, the limits, and the footing design's punching reproduced (BNBC 2020 Part 6
Sec 6.4.10)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.design.punching import (
    Demand,
    ShearReinforcement,
    column_perimeter,
    footing_punching,
    outer_perimeter,
    slab_punching,
    unit_relief,
)
from saengine.library.settings import Foundation as FoundationSettings
from saengine.substructure.shallow import ColumnBase, FootingSpec, _contact, design_footing

KN = 1e3
SLAB = [(0, 0), (12000, 0), (12000, 12000), (0, 12000)]


def test_interior_column_with_moment_transfer_by_hand() -> None:
    d, c = 150.0, 400.0
    vu, m = 300 * KN, 40e6
    result = slab_punching((6000, 6000), c, c, 0, d, SLAB, [Demand(vu, m, 0.0, "U1")], 30)
    assert result is not None and result.location == "interior"
    b1 = c + d
    b0 = 4 * b1
    jc = d * b1**3 / 6 + b1 * d**3 / 6 + d * b1 * b1**2 / 2  # ACI R8.4.4.2.3
    gamma = 1 - 1 / (1 + 2 / 3)  # Eq. 6.6.77, square section
    expected = vu / (b0 * d) + gamma * m * (b1 / 2) / jc
    assert result.b0 == pytest.approx(b0)
    assert result.vu == pytest.approx(expected, rel=1e-9)
    assert result.gamma_v[0] == pytest.approx(0.4)
    lambda_s = min(1.0, math.sqrt(2 / (1 + 0.004 * d)))
    vc = 0.33 * lambda_s * math.sqrt(30)  # Eq. 6.6.74 governs a square column
    assert result.vc == pytest.approx(vc)
    assert result.utilisation == pytest.approx(expected / (0.75 * vc))
    assert result.combination == "U1"


def test_edge_column_section_centroid_and_jc_by_hand() -> None:
    # A 400 x 400 column flush with the slab edge x = 0: the outer side drops out and the two
    # sides square to the edge run to it (6.4.10.1.2, Figure 6.6.16).
    d, c = 150.0, 400.0
    section, notes = column_perimeter((200, 6000), c, c, 0, d, SLAB)
    assert notes == [] and section.location == "edge" and section.alpha_s == 30
    inner = c / 2 + d / 2  # 275 from the centre
    lengths = {"face": c + d, "side": inner + 200}  # 550 and 475
    assert section.b0 == pytest.approx(lengths["face"] + 2 * lengths["side"])
    uc = (550 * 275 + 2 * 475 * (275 - 200) / 2) / 1500
    assert section.centroid()[0] == pytest.approx(uc)
    jc_face = 550 * d * (275 - uc) ** 2
    mid = (275 - 200) / 2
    jc_side = d * 475**3 / 12 + 475 * d**3 / 12 + 475 * d * (mid - uc) ** 2
    jc, reach = section.polar(True)
    assert jc == pytest.approx(jc_face + 2 * jc_side)
    assert reach == pytest.approx(200 + uc)
    vu, m = 150 * KN, 30e6
    gamma = 1 - 1 / (1 + 2 / 3 * math.sqrt(475 / 550))
    stress, direct, g_u, _ = section.stress(vu, m, 0.0)
    assert g_u == pytest.approx(gamma)
    assert stress == pytest.approx(vu / (1500 * d) + gamma * m * reach / jc)
    assert direct == pytest.approx(vu / (1500 * d))


def test_corner_column_alpha_and_capacity() -> None:
    d, c = 150.0, 400.0
    result = slab_punching((200, 200), c, c, 0, d, SLAB, [Demand(80 * KN, 10e6, 10e6, "U1")], 25)
    assert result is not None and result.location == "corner" and result.alpha_s == 20
    b0 = 2 * 475
    assert result.b0 == pytest.approx(b0)
    lambda_s = min(1.0, math.sqrt(2 / (1 + 0.004 * d)))
    # Eq. 6.6.73 with αs = 20: 0.083 (20 · 150 / 950 + 2) = 0.428 > 0.33: Eq. 6.6.74 governs.
    assert result.expressions[2] == pytest.approx(0.083 * (20 * d / b0 + 2) * lambda_s * 5)
    assert result.vc == pytest.approx(0.33 * lambda_s * 5)


def test_opening_near_column_makes_part_of_the_section_ineffective() -> None:
    # A 600 x 600 opening 300 mm beyond the +x face, centred on the column: the lines from the
    # column centre tangent to it cut the +x side to the opening's angular width.
    d, c = 150.0, 400.0
    hole = [(6500, 5700), (7100, 5700), (7100, 6300), (6500, 6300)]
    section, notes = column_perimeter((6000, 6000), c, c, 0, d, SLAB, [hole], thickness=200)
    # Tangents through (500, ±300) from the centre: v = ±0.6 u; at u = 275, ±165 is lost.
    assert section.ineffective == pytest.approx(2 * 0.6 * 275)
    assert section.b0 == pytest.approx(4 * 550 - 2 * 0.6 * 275)
    assert "6.4.10.6.1" in notes[0]
    # Beyond 10 h it does not count.
    far, _ = column_perimeter((6000, 6000), c, c, 0, d, SLAB, [hole], thickness=20)
    assert far.ineffective == 0 and far.b0 == pytest.approx(2200)


def test_headed_studs_by_hand() -> None:
    d, c, fc = 200.0, 500.0, 30.0
    vu = 1000 * KN
    result = slab_punching(
        (6000, 6000), c, c, 0, d, SLAB, [Demand(vu, 0, 0, "U1")], fc, thickness=250
    )
    assert result is not None and result.needs_reinforcement
    root = math.sqrt(fc)
    b0 = 4 * (c + d)
    v = vu / (b0 * d)
    assert result.vu == pytest.approx(v)
    r = result.reinforcement
    assert r is not None and r.ok and r.kind == "studs"
    # vc with studs: the least of 0.25, 0.17 (1 + 2/β) and 0.083 (2 + αs d/b0) √f'c.
    vc = root * min(0.25, 0.51, 0.083 * (2 + 40 * d / b0))
    assert r.vc == pytest.approx(vc)
    assert r.vs_required == pytest.approx(max(v / 0.75 - vc, 0.17 * root))
    layout = r.layout
    assert layout is not None
    # v <= 0.5 φ √f'c: lines at most 0.75 d = 150 apart; the first within d/2.
    assert (layout.s0, layout.s) == (100, 150)
    # Rails at both ends of each face and 2d apart at most: 3 per 500 mm face.
    assert layout.per_line == 12
    # 12 Ø10 give Av fyt/(b0 s) = 942 · 350 / (2800 · 150) = 0.785 < 1.012: Ø12.
    assert layout.bar == 12
    assert r.vs == pytest.approx(12 * math.pi * 36 * 350 / (b0 * 150))
    assert v <= 0.75 * (r.vc + r.vs)
    # The outer section: 2(c1 + c2) + 4√2 a with a = s0 + (n-1) s + d/2, v <= 0.17 φ √f'c.
    limit = 0.17 * 0.75 * root
    assert r.outer_limit == pytest.approx(limit)
    need = (vu / (limit * d) - 4 * c) / (4 * math.sqrt(2)) - d / 2  # last line from the face
    lines = math.ceil((need - 100) / 150) + 1
    assert layout.lines == lines == 6
    a = 100 + 5 * 150 + d / 2
    assert r.outer_b0 == pytest.approx(4 * c + 4 * math.sqrt(2) * a)
    assert r.outer_stress == pytest.approx(vu / (r.outer_b0 * d))
    assert r.stud_height == pytest.approx(250 - 20 - 20 - 6)
    check = result.check("Punching at C1")
    assert check["ok"] and check["shearReinforcement"]["lines"] == 6


def test_stirrups_by_hand_and_their_limits() -> None:
    d, c, fc = 200.0, 500.0, 30.0
    vu = 900 * KN
    demand = [Demand(vu, 0, 0, "U1")]
    result = slab_punching((6000, 6000), c, c, 0, d, SLAB, demand, fc, kind="stirrups", fyt=500)
    assert result is not None
    r = result.reinforcement
    assert r is not None and r.ok and r.kind == "stirrups"
    root = math.sqrt(fc)
    b0 = 4 * (c + d)
    v = vu / (b0 * d)
    assert r.vc == pytest.approx(0.17 * root)  # 6.4.10.3.1
    assert r.vn_max == pytest.approx(0.5 * root)  # 6.4.10.3.2
    layout = r.layout
    assert layout is not None and layout.fyt == 420  # fyt capped
    assert (layout.s0, layout.s) == (100, 100)  # d/2
    need = (v / 0.75 - 0.17 * root) * b0 * 100 / 420  # Av per line [mm²]
    assert layout.per_line * math.pi * layout.bar**2 / 4 >= need
    assert d >= 16 * layout.bar
    # Stirrups need d >= 150 mm.
    thin = slab_punching((6000, 6000), c, c, 0, 140, SLAB, [Demand(500 * KN)], fc, kind="stirrups")
    assert thin is not None and thin.reinforcement is not None
    assert thin.reinforcement.kind == "thicken" and not thin.ok
    # Beyond φ vn,max: thicken.
    huge = slab_punching((6000, 6000), c, c, 0, d, SLAB, [Demand(3000 * KN)], fc)
    assert huge is not None and huge.reinforcement is not None
    assert huge.reinforcement.kind == "thicken"
    assert "drop panel" in huge.reinforcement.text


def test_provided_studs_are_checked() -> None:
    d, c, fc = 200.0, 500.0, 30.0
    demand = [Demand(1000 * KN, 0, 0, "U1")]
    good = ShearReinforcement("studs", 12, 12, 6, 100, 150, 350)
    result = slab_punching((6000, 6000), c, c, 0, d, SLAB, demand, fc, provided=good)
    assert result is not None and result.ok and result.reinforcement.issues == []
    short = ShearReinforcement("studs", 12, 12, 3, 120, 180, 350)
    bad = slab_punching((6000, 6000), c, c, 0, d, SLAB, demand, fc, provided=short)
    assert bad is not None and not bad.ok
    issues = " ".join(bad.reinforcement.issues)
    assert "exceeds d/2" in issues and "spacing 180" in issues and "more lines" in issues
    # The design check follows: a failing layout never reports a pass.
    assert good_check(result) and not good_check(bad)
    # Only the outer section short (6 lines needed, 1 given): stresses at the face are fine.
    one = ShearReinforcement("studs", 12, 12, 1, 100, 150, 350)
    lone = slab_punching((6000, 6000), c, c, 0, d, SLAB, demand, fc, thickness=250, provided=one)
    assert lone is not None and not lone.ok
    check = lone.check("P")
    assert not check["ok"] and check["utilisation"] > 1
    # Its utilisation is the outer section's v / 0.17 φ √f'c.
    r = lone.reinforcement
    assert check["utilisation"] == pytest.approx(r.outer_stress / r.outer_limit, abs=1e-3)


def good_check(result) -> bool:
    check = result.check("P")
    assert check["ok"] == (check["utilisation"] <= 1)
    return check["ok"]


def test_no_layout_fails_the_check() -> None:
    # Stirrups with d < 150 mm cannot be used: "thicken" while v < φ vn,max.
    result = slab_punching(
        (6000, 6000), 400, 400, 0, 120, SLAB, [Demand(450 * KN, 0, 0, "U1")], 25,
        thickness=150, kind="stirrups",
    )  # fmt: skip
    assert result is not None and result.reinforcement.kind == "thicken" and not result.ok
    check = result.check("P")
    assert not check["ok"] and check["utilisation"] == pytest.approx(result.utilisation, abs=1e-3)
    assert check["capacity"] == pytest.approx(result.phi_vc * result.b0 * result.d / 1e3, abs=0.01)
    assert result.reinforcement.utilisation > 1


def test_outer_section_takes_every_combination() -> None:
    # A (large moment) governs the column face, B (shear only) the outer section: the layout
    # for [A, B] must satisfy B alone.
    d, c, fc = 200.0, 500.0, 30.0
    a, b = Demand(700 * KN, 200e6, 0, "A"), Demand(950 * KN, 0, 0, "B")
    both = slab_punching((6000, 6000), c, c, 0, d, SLAB, [a, b], fc, thickness=250)
    alone = slab_punching((6000, 6000), c, c, 0, d, SLAB, [b], fc, thickness=250)
    assert both is not None and alone is not None and both.combination == "A"
    lines = both.reinforcement.layout.lines
    assert lines >= alone.reinforcement.layout.lines
    again = slab_punching(
        (6000, 6000), c, c, 0, d, SLAB, [b], fc, thickness=250, provided=both.reinforcement.layout
    )
    assert again.ok and again.check("P")["ok"]


def test_outer_section_clipped_at_an_edge() -> None:
    from shapely.geometry import box

    # An edge column flush with x = 0 (local -u face): the octagon loses the -u face and its
    # chords; the ±v faces run to the edge.
    ring = outer_perimeter(400, 400, 150, 300, box(-200, -6000, 11800, 6000))
    a = 300 + 75
    expected = 400 + 2 * math.sqrt(2) * a + 2 * 400  # +u face, its two chords, ±v to the edge
    assert ring.b0 == pytest.approx(expected, rel=1e-6)
    assert ring.location == "edge"


# ───────────────────────────── the footing design reproduced ─────────────────────────────

T16 = {"dia": 16, "spacing": 150}


def _spec(u: float = 0.0) -> FootingSpec:
    from saengine.library.objects import BarMesh

    mesh = BarMesh.model_validate(T16)
    return FootingSpec(
        id="F1",
        type="isolated",
        footing_type="isolated",
        length=1800,
        width=1800,
        thickness=500,
        elevation=-1000,
        cover=75,
        fc=25,
        fy=420,
        columns=[ColumnBase("C1", u, 0, 400, 400, 1500)],
        bottom_x=mesh,
        bottom_y=mesh,
    )


@pytest.mark.parametrize(
    ("u", "load"),
    [(0.0, (1200 * KN, 0.0, 0.0)), (0.0, (900 * KN, 60e6, 90e6)), (520.0, (700 * KN, 0, 50e6))],
)
def test_footing_punching_matches_the_footing_design(u: float, load: tuple) -> None:
    spec = _spec(u)
    loads = [np.array(load)]
    checks, _ = design_footing(spec, {}, {"U1": loads}, FoundationSettings())
    check = next(c for c in checks if c["name"] == "Punching at C1")
    foundation = FoundationSettings()
    own = spec.unit_weight * spec.thickness + foundation.soilUnitWeight * 1e-6 * max(
        0.0, foundation.groundLevel - spec.elevation
    )
    pressure = _contact(spec, loads, own)

    def relief(u0: float, u1: float, v0: float, v1: float) -> float:
        return pressure.over(u0, u1, v0, v1) - own * (u1 - u0) * (v1 - v0)

    result = footing_punching(
        u, 0, 400, 400, 1800, 1800, spec.d, 25, [("U1", *load, relief)], thickness=500
    )
    assert result is not None and result.location == ("edge" if u else "interior")
    # The design check rounds to 3 decimals (utilisation) and 2 (kN).
    assert round(result.utilisation, 3) == check["utilisation"]
    assert round(result.vu * result.b0 * result.d / KN, 2) == check["demand"]
    assert round(result.phi_vc * result.b0 * result.d / KN, 2) == check["capacity"]
    assert result.check("Punching at C1")["utilisation"] == check["utilisation"]


def test_footing_needing_studs() -> None:
    # A thin footing under a heavy column: studs, the outer section's Vu less the relief.
    d = 300.0
    q = 2000 * KN / 2400**2
    result = footing_punching(
        0,
        0,
        400,
        400,
        2400,
        2400,
        d,
        25,
        [("U1", 2000 * KN, 0, 0, unit_relief(q))],
        thickness=400,
    )
    assert result is not None and result.needs_reinforcement
    r = result.reinforcement
    assert r is not None and r.ok and r.layout is not None
    a = r.layout.s0 + (r.layout.lines - 1) * r.layout.s + d / 2
    octagon = (400 + 2 * a) ** 2 - 2 * a * a
    vu_out = 2000 * KN - q * octagon
    assert r.outer_stress == pytest.approx(vu_out / (r.outer_b0 * d), rel=1e-6)
    assert r.outer_stress <= r.outer_limit


def test_footing_outer_section_takes_every_combination() -> None:
    # A: moments govern the column face; B: more axial load, no moment, with its own relief.
    d = 300.0
    args = (0, 0, 400, 400, 2400, 2400, d, 25)
    qa, qb = 1500 * KN / 2400**2, 2000 * KN / 2400**2
    a = ("A", 1500 * KN, 150e6, 150e6, unit_relief(qa))
    b = ("B", 2000 * KN, 0, 0, unit_relief(qb))
    both = footing_punching(*args, [a, b], thickness=400)
    assert both is not None and both.combination == "A" and both.reinforcement.ok
    again = footing_punching(*args, [b], thickness=400, provided=both.reinforcement.layout)
    assert again is not None and again.reinforcement.ok and again.check("P")["ok"]

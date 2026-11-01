"""Post-tensioning sheets (T16): the tendons in plan, the profile, the elongations of the
stressing schedule, the anchorage zone bars (B30) and the sheets."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.design import prestress
from saengine.drawings.sheets import DrawingSettings, build_sheets, pt
from saengine.drawings.sheets.model import Building, DrawingSet, Grid, Level, PlanSlab
from saengine.library.bim import SlabTendon

FPU = 1860.0
EP = 195_000.0


def _tendon(**kw) -> SlabTendon:
    data = {
        "id": "PT1", "host": "S1", "x1": 0, "y1": 2500, "x2": 20000, "y2": 2500, "width": 2000,
        "count": 4, "strands": 1, "longTermLoss": 100, "wobble": 0.0, "friction": 0.0,
        "anchorSet": 0, "profile": [{"at": 0, "height": 100}, {"at": 10000, "height": 100},
                                    {"at": 20000, "height": 100}],
    }  # fmt: skip
    data.update(kw)
    return SlabTendon.model_validate(data)


def _item(tendon: SlabTendon) -> pt.PtTendon:
    return pt.with_forces(pt.PtTendon(tendon, "S1", "L1", 3200, 200, 30))


def test_elongation_without_friction_is_pl_over_ae():
    # Δ = fpj L / Ep: 0.80 x 1860 x 20000 / 195000 = 152.6 mm
    item = _item(_tendon())
    assert item.elongation == pytest.approx((0.80 * FPU * 20000 / EP,), rel=1e-6)
    # both ends live: each end stresses half the length
    both = _item(_tendon(stressedAt="both"))
    assert both.elongation == pytest.approx((0.80 * FPU * 10000 / EP,) * 2, rel=1e-6)


def test_elongation_with_wobble():
    # P(x) = Pj e^(-K x): Δ = fpj / Ep x (1 - e^(-K L)) / K (BNBC Sec 9.6.8, Eq 6.9.2, K per metre)
    k = 0.0033
    item = _item(_tendon(wobble=k))
    expected = 0.80 * FPU / EP * (1 - math.exp(-k * 20.0)) / k * 1000
    assert item.elongation[0] == pytest.approx(expected, rel=1e-3)
    # from the end: the same by symmetry
    assert _item(_tendon(wobble=k, stressedAt="end")).elongation[0] == pytest.approx(
        expected, rel=1e-3
    )


def test_elongations_meet_where_the_forces_do():
    k = 0.0033
    tendon = _tendon(wobble=k, friction=0.07, stressedAt="both",
                     profile=[{"at": 0, "height": 100}, {"at": 8000, "height": 40},
                              {"at": 12000, "height": 160}, {"at": 20000, "height": 100}])  # fmt: skip
    item = _item(tendon)
    one = pt.elongations(item.forces.jacking, item.pieces, item.forces.stations,
                         _tendon(wobble=k, friction=0.07, stressedAt="start",
                                 profile=[p.model_dump() for p in tendon.profile]),
                         item.forces.area)  # fmt: skip
    a, b = item.elongation
    # each end stresses part of it: together less than one end stressing it all
    assert 0 < a < one[0] and 0 < b < one[0] and a + b < one[0]


def test_tendon_lines_banded_and_distributed():
    banded = _item(_tendon())
    lines = pt.tendon_lines(banded)
    ys = sorted(a[1] for a, _ in lines)
    assert np.diff(ys) == pytest.approx([pt.BAND_SPACING] * 3)  # 2000 / 4 = 500 > 300
    distributed = _item(_tendon(layout="distributed"))
    ys = sorted(a[1] for a, _ in pt.tendon_lines(distributed))
    assert np.diff(ys) == pytest.approx([500.0] * 3)
    assert sum(ys) / 4 == pytest.approx(2500)


def test_profile_points_follow_the_design_parabola():
    tendon = _tendon(profile=[{"at": 0, "height": 100}, {"at": 10000, "height": 40},
                              {"at": 20000, "height": 160}])  # fmt: skip
    item = _item(tendon)
    pts = pt.profile_points(item)
    pieces = prestress.segments([(0, 100), (10000, 40), (20000, 160)])
    for x, y in pts:
        piece = next(p for p in pieces if p.x0 <= x <= p.x1)
        assert y == pytest.approx(piece.height(x))
    assert pts[0] == (0, 100) and pts[-1] == pytest.approx((20000, 160))


def test_stressing_schedule_row():
    item = _item(_tendon(stressedAt="both", transferStrength=25))
    row = pt.schedule_row(item, "Level 1")
    # jacking per tendon fpj x Aps = 0.80 x 1860 x 98.7 N
    assert row[10] == f"{0.80 * FPU * 98.7 / 1e3:.0f}"
    assert row[9] == "8 / 0" and row[8] == "Both" and row[13] == "25"


def test_pt_sheets_in_the_set():
    b = Building(
        grids_x=[Grid("A", 0), Grid("B", 20000)],
        grids_y=[Grid("1", 0), Grid("2", 5000)],
        levels=[Level("BASE", "Base", 0), Level("L1", "Level 1", 3200)],
    )
    b.slabs.append(PlanSlab("S1", "S1", [(0, 0), (20000, 0), (20000, 5000), (0, 5000)], 200, 3200))
    data = DrawingSet(building=b)
    data.pt = [_item(_tendon())]
    titles = [s.title for s in build_sheets(data, DrawingSettings.from_dict({"size": "A1"}))]
    assert "Post-tensioning plan - Level 1" in titles
    assert any(t.startswith("Tendon profiles") for t in titles)
    assert "Tendon and stressing schedule" in titles


def test_schedule_lists_the_friction_coefficients_and_the_age_at_stressing():
    """BNBC Sec 9.6.9: K and μ used in design shown on the drawings."""
    item = _item(_tendon(wobble=0.0033, friction=0.07, transferAge=5))
    row = pt.schedule_row(item, "Level 1")
    assert row[-2:] == ["5", "0.0033 / 0.07"]


def test_monostrand_anchorage_zone_bars():
    """BNBC Sec 9.14.2: two 12 mm bars within h/2 ahead of the anchors, 150 mm beyond."""
    item = _item(_tendon())
    assert item.anchorage.edge_bars == (2, 12, 100, 150)
    assert any("Sec 9.14.2" in note for note in pt.plan_notes())
    assert any("Sec 9.5.4 (a)" in note for note in pt.schedule_notes())

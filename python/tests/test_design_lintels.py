"""Lintels and spandrels designed as beams (saengine.design.lintels): loads by the stated 45°
triangle rule, moments, steel and deflection by hand, the spandrel classification of BNBC 2020
Part 6 Sec 8.3.6.7 (p. 1105), and the lintels found in a synthetic building."""

from __future__ import annotations

import math

import pytest

from saengine.design import lintels as L
from saengine.design.rc import bar_area
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import BuildingModel

FC, FY = 25.0, 420.0


def test_arching_lintel_moment_and_steel_by_hand() -> None:
    # 1200 mm door, 150 mm bearings: L = 1350 mm; 250 x 150 lintel; 1000 mm of brick above.
    loads = L.lintel_loads(1200, 250, 150, 1000, masonry_weight=18.85, concrete_weight=24)
    assert loads.span == 1350
    # 45°: the triangle rises L/2 = 675 mm < 1000 mm: the masonry arches.
    assert loads.arching and loads.triangle_height == pytest.approx(675)
    q_t = 18.85e-6 * 250 * 675  # 3.181 N/mm peak
    w = 24e-6 * 250 * 150  # 0.9 N/mm own weight
    assert loads.triangle == pytest.approx(q_t) and loads.dead == pytest.approx(w)
    mu = 1.4 * (q_t * 1350**2 / 12 + w * 1350**2 / 8)  # 0.963 kN·m (1.4D governs, no live)
    vu = 1.4 * (q_t * 1350 / 4 + w * 1350 / 2)
    assert loads.moment(1.4, 0) == pytest.approx(mu)
    assert loads.shear(1.4, 0) == pytest.approx(vu)
    d = L.design_lintel(loads, 250, 150, FC, FY)
    assert d["loads"]["Mu"] == pytest.approx(mu / 1e6, abs=0.01)
    # As: singly, d = 150 - 25 - 8 - 6 = 111: 23 mm²; As,min = 1.4 bw d / fy = 92.5 mm² but
    # 4/3 x 23 = 31 mm² suffices (ACI 9.6.1.3): 2 Ø10 (157 mm²).
    assert d["bars"]["bottom"] == [2, 10.0] and d["bars"]["top"] == [2, 10.0]
    flexure = d["checks"][0]
    dd = 150 - 25 - 8 - 5  # 112 with Ø10
    a = 2 * bar_area(10) * FY / (0.85 * FC * 250)
    phi_mn = 0.9 * 2 * bar_area(10) * FY * (dd - a / 2)
    assert flexure["capacity"] == pytest.approx(phi_mn / 1e6, abs=0.01)
    assert flexure["demand"] == pytest.approx(mu / 1e6, abs=0.01)
    # Deflection: Ma (D + L service) < Mcr = 0.62 √f'c Ig / (h/2): Ie = Ig.
    ig = 250 * 150**3 / 12
    mcr = 0.62 * 5 * ig / 75
    ma = q_t * 1350**2 / 12 + w * 1350**2 / 8
    assert ma < mcr
    ec = 4700 * 5
    delta = 5 * w * 1350**4 / (384 * ec * ig) + q_t * 1350**4 / (120 * ec * ig)
    row = next(c for c in d["checks"] if c["name"].startswith("Deflection"))
    assert row["demand"] == pytest.approx(delta, abs=0.01)
    assert row["capacity"] == pytest.approx(1200 / 600)
    # Shear: 150 mm deep, Vu = 2.35 kN <= φVc = 0.75 x 0.17 x 5 x 250 x 112: no stirrups
    # needed, nominal Ø8 @ 150 links (s <= d/2 = 56 mm could not be met anyway).
    shear = next(c for c in d["checks"] if c["name"].startswith("Shear"))
    assert shear["capacity"] == pytest.approx(0.75 * 0.17 * 5 * 250 * dd / 1e3, abs=0.01)
    assert d["bars"]["stirrups"] == [2, 8.0, 150.0]
    assert d["ok"]


def test_no_arching_takes_all_the_masonry_and_the_floor() -> None:
    # 2400 mm window, L = 2550, triangle 1275 mm; only 600 mm of wall above: no arch.
    loads = L.lintel_loads(
        2400, 250, 200, 600, masonry_weight=19.0, floor_dead=12.0, floor_live=6.0
    )
    assert not loads.arching and loads.triangle == 0
    w_d = 24e-6 * 250 * 200 + 19e-6 * 250 * 600 + 12.0
    assert loads.dead == pytest.approx(w_d) and loads.live == pytest.approx(6.0)
    mu = (1.2 * w_d + 1.6 * 6.0) * 2550**2 / 8
    assert loads.moment(1.2, 1.6) == pytest.approx(mu)
    d = L.design_lintel(loads, 250, 200, FC, FY)
    assert d["loads"]["Mu"] == pytest.approx(max(mu, 1.4 * w_d * 2550**2 / 8) / 1e6, abs=0.01)
    bars = d["bars"]["bottom"]
    assert bars[0] * bar_area(bars[1]) >= 0  # bars were found
    assert d["checks"][0]["ok"]


def test_lintel_depth_and_wind_rows() -> None:
    # Table 6.6.1: L/16 x (0.4 + fy/700), at least 150, rounded up to 25 mm.
    assert L.lintel_depth(1350, 420) == 150
    assert L.lintel_depth(3600, 420) == 225  # 3600/16 = 225
    assert L.lintel_depth(3600, 500) == 275  # 225 x (0.4 + 500/700) = 250.7, up to 275
    loads = L.lintel_loads(3600, 250, 250, 3000)
    d = L.design_lintel(loads, 250, 250, FC, FY, high_wind=True)
    wind = next(c for c in d["checks"] if c["name"].startswith("Lintel span"))
    assert not wind["flag"] and not wind["ok"]  # 3750 mm > 3.5 m in a high wind region
    assert any("600 mm beyond" in n for n in d["notes"])


def test_spandrel_classification() -> None:
    """8.3.6.7: ln/h > 4 flexural; ln/h < 2 with Vu > 0.33 Acw √f'c diagonal; else either.
    Ordinary walls: a beam from ln/h = 4, a deep beam below."""
    root = math.sqrt(FC)
    assert L.spandrel_mode(3600, 600, 100e3, 250, FC, True) == "flexural"
    assert L.spandrel_mode(2400, 600, 100e3, 250, FC, True) == "either"  # exactly 4: not > 4
    high = 0.34 * 250 * 800 * root
    low = 0.32 * 250 * 800 * root
    assert L.spandrel_mode(1000, 800, high, 250, FC, True) == "diagonal"
    assert L.spandrel_mode(1000, 800, low, 250, FC, True) == "either"
    assert L.spandrel_mode(2400, 600, high, 250, FC, False) == "beam"
    assert L.spandrel_mode(1000, 800, high, 250, FC, False) == "deep"


def _spandrel(ln: float, h: float, bw: float, m: float, v: float) -> dict:
    return {
        "spandrel": "W1/L1/S1",
        "length": ln,
        "depth": h,
        "tw": bw,
        "cuts": {
            "left": {"E": {"P": 0, "V2": v, "M3": m}},
            "right": {"E": {"P": 0, "V2": -v, "M3": -m}, "G": {"P": 0, "V2": 30, "M3": 20}},
        },
    }


def test_flexural_coupling_beam_capacity_shear_by_hand() -> None:
    s = _spandrel(3600, 600, 300, 220, 150)
    found = L.spandrel_design(s, FC, FY, special=True, earthquake={"E"})
    assert found["mode"] == "flexural"
    bottom = found["bars"]["bottom"]
    assert found["bars"]["top"] == bottom and bottom[0] <= 3
    area = bottom[0] * bar_area(bottom[1])
    d = 600 - 25 - 8 - bottom[1] / 2
    a = area * 1.25 * FY / (0.85 * FC * 300)
    mpr = area * 1.25 * FY * (d - a / 2)
    ve = 2 * mpr / 3600 + 30e3  # + the gravity shear of G
    row = next(c for c in found["checks"] if c["name"].startswith("Capacity-design shear"))
    assert row["demand"] == pytest.approx(ve / 1e3, abs=0.05)
    # The earthquake part is more than half of Ve and P < Ag f'c / 20: Vc = 0 (8.3.8.2(a)).
    assert "Vc = 0.0 kN" in row["note"]
    flexure = found["checks"][0]
    assert flexure["demand"] == pytest.approx(220.0)
    names = [c["name"] for c in found["checks"]]
    assert "Hoop spacing at the ends (8.3.4.3(b))" in names
    width = next(c for c in found["checks"] if c["name"].startswith("Width ≥ 250"))
    assert not width["flag"] and width["ok"]  # 300 mm: counts, and is met


def test_flexural_coupling_beam_width_rules_count_without_a_stability_analysis() -> None:
    """8.3.6.7(a) waives 8.3.4.1(c), (d) only where analysis shows lateral stability: a 200 mm
    wall's coupling beam fails 'Width ≥ 250' unless the engineer says it was shown."""
    s = _spandrel(3600, 600, 200, 150, 100)
    found = L.spandrel_design(s, FC, FY, special=True, earthquake={"E"})
    assert found["mode"] == "flexural"
    width = next(c for c in found["checks"] if c["name"].startswith("Width ≥ 250"))
    assert not width["flag"] and not width["ok"] and not found["ok"]
    assert "8.3.6.7(a)" in width["note"]
    shown = L.spandrel_design(s, FC, FY, special=True, earthquake={"E"}, lateral_stability=True)
    width = next(c for c in shown["checks"] if c["name"].startswith("Width ≥ 250"))
    assert width["flag"] and "waived" in width["note"]


def test_ordinary_spandrel_uses_the_analysis_shear() -> None:
    found = L.spandrel_design(_spandrel(1000, 800, 250, 60, 300), FC, FY, special=False)
    assert found["mode"] == "deep"
    shear = next(c for c in found["checks"] if c["name"].startswith("Shear"))
    assert shear["demand"] == pytest.approx(300.0)


def test_lintels_found_in_a_building() -> None:
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "BW250",
                    "name": "Brick wall 250",
                    "kind": "wall",
                    "material": "BRICK",
                    "thickness": 250,
                    "structural": False,
                },
                {
                    "id": "B300",
                    "name": "Beam 300x500",
                    "kind": "beam",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
                },
            ]
        }
    ).objects
    types = {o.id: o for o in objects}
    mats = {m.id: m for m in default_material_library().materials}
    building = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
            ],
            "elements": [
                {
                    "id": "W1",
                    "type": "BW250",
                    "kind": "wall",
                    "start": [0, 0],
                    "end": [5000, 0],
                    "bottom": 0,
                    "top": 3000,
                },
                {
                    "id": "B1",
                    "type": "B300",
                    "kind": "beam",
                    "start": [0, 0],
                    "end": [5000, 0],
                    "elevation": 3000,
                },
            ],
            "additions": {
                "wallOpenings": [
                    {
                        "id": "D1",
                        "host": "W1",
                        "offset": 1000,
                        "sill": 0,
                        "width": 1000,
                        "height": 2100,
                    },
                    {
                        "id": "V1",
                        "host": "W1",
                        "offset": 3500,
                        "sill": 2000,
                        "width": 600,
                        "height": 1000,
                    },
                ]
            },
        }
    )
    out = L.lintels_of(building, types, mats)
    (lintel,) = out["elements"]
    assert lintel["id"] == "D1" and lintel["kind"] == "lintel" and lintel["host"] == "W1"
    # Above the door: 3000 - 2100 - 150 (lintel) - 500 (beam) = 250 mm < the triangle's
    # (1150 / 2 = 575 mm): no arching; the beam carries the floor.
    assert not lintel["loads"]["arching"]
    assert lintel["loads"]["heightAbove"] == 250
    assert any("beam 500 mm deep" in n for n in lintel["notes"])
    # The ventilator reaches the wall's top: the beam over it spans it.
    assert [s["id"] for s in out["skipped"]] == ["V1"]

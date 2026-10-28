"""Design mode: the reinforcement required, against hand calculations to ACI 318-19 (adopted
by BNBC 2020 Part 6 Chapter 6). Synthetic members; plain arithmetic for every reference."""

from __future__ import annotations

import math

import pytest

from saengine.design import bars as B
from saengine.design.rc import InteractionSurface, bars_per_row, flexure, section_of
from saengine.design.required import (
    ColumnSearch,
    FoundationDemand,
    Options,
    Peak,
    foundation_layer_need,
    slab_depths,
)
from saengine.library.objects import Column, LinearReinforcement, RectangleProfile

FC, FY = 28.0, 420.0
ROOT = math.sqrt(FC)


def _singly(mu: float, b: float, d: float) -> float:
    """As by hand: Rn = Mu / (φ b d²), ρ = 0.85 f'c / fy (1 - √(1 - 2 Rn / (0.85 f'c)))."""
    rn = mu / (0.9 * b * d**2)
    rho = 0.85 * FC / FY * (1 - math.sqrt(1 - 2 * rn / (0.85 * FC)))
    return rho * b * d


def test_beam_tension_steel_and_minimum_by_hand() -> None:
    # 300 x 500, d = 500 - 40 - 10 - 20/2 = 440, Mu = 150 kN·m.
    need = B.beam_flexure_need(150e6, 300, 440, 60, FC, FY)
    # Rn = 150e6 / (0.9 × 300 × 440²) = 2.8696 MPa; ρ = 0.0073029; As = 964.0 mm².
    assert need.area == pytest.approx(_singly(150e6, 300, 440), rel=1e-9)
    assert need.area == pytest.approx(964.0, abs=0.5)
    assert need.compression == 0 and not need.too_small
    # As,min = max(0.25 √28, 1.4) / 420 × 300 × 440 = 1.4 / 420 × 132000 = 440 mm² (9.6.1.2).
    assert B.beam_min_area(300, 440, FC, FY) == pytest.approx(440.0)
    # 9.6.1.3: where 4/3 of the bars required is less than As,min, it is enough.
    assert B.with_minimum(300.0, 440.0) == pytest.approx(400.0)
    assert B.with_minimum(964.0, 440.0) == pytest.approx(964.0)
    assert B.with_minimum(0.0, 440.0) == 0.0


def test_beam_compression_steel_and_section_too_small_by_hand() -> None:
    # 250 x 400, d = 340, d' = 60, Mu = 250 kN·m: beyond the tension-controlled limit.
    b, d, d2 = 250.0, 340.0, 60.0
    c = 0.003 * d / (0.006 + FY / 200_000)  # εt = εty + 0.003: c = 125.93 mm
    a = 0.85 * c
    as1 = 0.85 * FC * b * a / FY
    mn1 = as1 * FY * (d - a / 2)
    mn2 = 250e6 / 0.9 - mn1
    fs = min(200_000 * 0.003 * (c - d2) / c, FY)  # 314 MPa: below yield
    as2 = mn2 / ((fs - 0.85 * FC) * (d - d2))
    total = as1 + as2 * (fs - 0.85 * FC) / FY
    need = B.beam_flexure_need(250e6, b, d, d2, FC, FY, h=400)
    assert need.compression == pytest.approx(as2, rel=1e-9)
    assert need.area == pytest.approx(total, rel=1e-9)
    assert (as1, as2, total) == pytest.approx((1516, 1174, 2327), abs=2)
    assert not need.too_small and "compression bars" in need.note
    # Twice the moment needs 4689 mm² of tension steel > 0.04 b h = 4000 mm²: too small.
    assert B.beam_flexure_need(500e6, b, d, d2, FC, FY, h=400).too_small


def test_stirrups_by_hand() -> None:
    # 300 x 500, d = 440, Vu = 200 kN.
    need = B.beam_shear_need(200e3, 300, 440, FC, FY)
    vc = 0.17 * ROOT * 300 * 440  # 118.7 kN
    vs = 200e3 / 0.75 - vc  # 147.9 kN
    assert need.vc == pytest.approx(vc)
    assert need.vs == pytest.approx(vs)
    assert need.av_s == pytest.approx(vs / (FY * 440))  # 0.8005 mm²/mm
    assert need.av_s_min == pytest.approx(0.35 * 300 / FY)  # 0.062 √28 = 0.328 < 0.35
    assert need.s_max == pytest.approx(220.0)  # Vs < 0.33 √f'c b d = 230.5 kN: min(d/2, 600)
    # Two-leg Ø8 at 100.5 / 0.8005 = 125.6 -> 125 mm is the lightest (Ø10 at 175: 0.898).
    assert B.choose_stirrups(need, 300) == B.Stirrups(8.0, 2, 125.0)
    # Above 0.33 √f'c b d the spacing halves: min(d/4, 300).
    assert B.beam_shear_need(300e3, 300, 440, FC, FY).s_max == pytest.approx(110.0)
    # Vs above 0.66 √f'c b d (22.5.1.2): the section is too small for shear.
    limit = 0.75 * (vc + 0.66 * ROOT * 300 * 440)
    assert not B.beam_shear_need(limit * 0.99, 300, 440, FC, FY).too_small
    assert B.beam_shear_need(limit * 1.01, 300, 440, FC, FY).too_small


def test_slab_strip_per_metre_and_spacing_rounding() -> None:
    # 150 mm slab, cover 20, Mu = 20 kN·m/m on the outer (X) layer.
    h, cover = 150.0, 20.0
    required = {
        dia: max(_singly(20e6, 1000, h - cover - dia / 2), 0.0018 * h * 1000)
        for dia in B.SLAB_DIAMETERS
    }
    assert required[10] == pytest.approx(436.7, abs=0.3)  # d = 125
    for dia, value in required.items():
        need = B.slab_flexure_need(20e6, h - cover - dia / 2, FC, FY)
        assert max(need.area, 270.0) == pytest.approx(value, rel=1e-6)
    # Ø10: 78.54 × 1000 / 436.7 = 179.8 -> 175 mm (448.8 mm²/m); Ø12: 256.8 -> 250 (452.4).
    mesh = B.mesh_for(0.0, min(2 * h, 450), B.SLAB_DIAMETERS, 100, required)
    assert mesh == B.Mesh(10.0, 175.0)
    assert mesh.area == pytest.approx(448.8, abs=0.1)
    # Depths of the four layers, X outer: Ø10 bottom X, Ø12 bottom Y.
    depths = slab_depths(h, cover, {"bottomX": 10, "bottomY": 12, "topX": 10, "topY": 10})
    assert depths["bottomX"] == 125 and depths["bottomY"] == 150 - 20 - 10 - 6
    # The most a slab may have: c at εt = 0.004 (ACI 7.3.3.1): c = 3/7 d.
    most = 0.85 * FC * 1000 * 0.85 * 3 / 7 * 125 / FY
    assert B.slab_max_area(125, FC, FY) == pytest.approx(most)
    # One-way shear without shear bars: ρ for φ 0.66 λs ρ^(1/3) √f'c b d (Table 22.5.5.1 (c)).
    lam_s = min(1.0, math.sqrt(2 / (1 + 0.004 * 125)))  # 1.15 -> 1 (22.5.5.1.3)
    rho = (40e3 / (0.75 * 0.66 * lam_s * ROOT * 1000 * 125)) ** 3
    assert B.slab_shear_rho(40e3, 125, FC) == pytest.approx(rho)
    assert B.slab_shear_rho(0.75 * 0.42 * ROOT * 1000 * 125 * 1.01, 125, FC) is None


def test_footing_direction_by_hand() -> None:
    # 500 mm footing, cover 75, Mu = 200 kN·m/m about the X bars (Ø16 outer: d = 417).
    peak = Peak(200e6, "1.2D + 1.6L", "Flexure X (bottom)")
    demand = FoundationDemand(
        "F9", "isolated", 500.0, 75.0, FC, FY,
        {"bottomX": peak, "bottomY": Peak(), "topX": Peak(), "topY": Peak()},
        {"X": Peak(), "Y": Peak()}, [], None, "B420DWR",
    )  # fmt: skip
    required, minimum, _, small = foundation_layer_need(demand, "bottomX", 417.0)
    assert required == pytest.approx(_singly(200e6, 1000, 417))  # 1304.8 mm²/m
    assert required == pytest.approx(1304.8, abs=0.5)
    assert minimum == pytest.approx(0.0018 * 500 * 1000) and not small
    # Ø16 at 201.06 × 1000 / 1304.8 = 154 -> 150 mm; Ø12 would need 87 mm (< 100); Ø20 at 225
    # and Ø25 at 350 give more steel.
    required_of = {
        dia: foundation_layer_need(demand, "bottomX", 500 - 75 - dia / 2)[0]
        for dia in (12.0, 16.0, 20.0, 25.0)
    }
    assert B.mesh_for(0.0, 450.0, (12.0, 16.0, 20.0, 25.0), 100, required_of) == B.Mesh(16, 150)
    # A light moment: As,min = 0.0018 Ag governs (ACI 7.6.1.1).
    demand.moments["bottomX"] = Peak(50e6, None, "")
    assert foundation_layer_need(demand, "bottomX", 417.0)[0] == pytest.approx(900.0)


def test_column_layouts_and_ties() -> None:
    layouts = B.column_layouts("rectangle", 400, 400, 50, (16.0, 20.0, 25.0))
    assert all(0.01 * 160000 <= o.area <= 0.08 * 160000 for o in layouts)
    assert [o.area for o in layouts] == sorted(o.area for o in layouts)
    eight = next(o for o in layouts if (o.count, o.dia) == (8, 20.0))
    assert (eight.per_x, eight.per_y) == (1, 1)  # as rc.section_of lays 8 perimeter bars out
    # Ties (25.7.2): Ø10 for Ø20 bars, s <= min(16 × 20, 48 × 10, 400) = 320 -> 300 (25 mm steps).
    ties = B.column_ties(eight, 400, 400, 400, 40)
    assert (ties.dia, ties.spacing) == (10.0, 300.0)
    # 3 bars a face, 125 mm clear: the corners and every other bar held -> 2 + 0 = 2 legs.
    assert ties.legs == 2
    # A circle needs 6 bars at least (10.7.3.1).
    assert min(o.count for o in B.column_layouts("circle", 500, 500, 50)) >= 6


def _column(b: float, h: float) -> Column:
    return Column.model_validate(
        {
            "id": "C",
            "name": "C",
            "material": "C28",
            "profile": {"shape": "rectangle", "xDim": b, "yDim": h},
            "reinforcement": {
                "material": "B420",
                "cover": 40,
                "longitudinal": [{"position": "perimeter", "count": 4, "dia": 20}],
                "transverse": {"type": "tie", "dia": 10, "spacing": 150},
            },
        }
    )


def test_column_axial_required_steel_by_hand() -> None:
    # 400 x 400, Pu = 3000 kN, no moment: φPn,max = 0.80 × 0.65 (0.85 f'c (Ag - As) + fy As).
    pu = 3000e3
    as_hand = (pu / 0.52 - 0.85 * FC * 160000) / (FY - 0.85 * FC)  # 4950 mm², ρ = 0.031
    search = ColumnSearch(_column(400, 400), FC, FY, 200_000, None, Options())
    points = [(pu, 0.0, 0.0, "1.4D", "C at 0.00 L")]
    index = search.smallest(points)
    assert index is not None
    assert search.layouts[index].area >= as_hand
    assert search.layouts[index - 1].area < as_hand
    assert search.required_area(index, points) == pytest.approx(as_hand, rel=0.01)


def test_column_required_from_the_interaction_with_a_hand_point() -> None:
    # The balanced point of 400 x 400 with 8Ø20 (3 bars top and bottom at 140 mm from the
    # centroid, 2 at mid-depth), Ø10 ties, cover 40: d = 340, c = 0.003 / 0.0051 × 340 = 200.
    a_bar = math.pi * 20**2 / 4
    c = 0.003 / (0.003 + FY / 200_000) * 340
    a = 0.85 * c
    cc = 0.85 * FC * 400 * a
    top = 3 * a_bar * (min(200_000 * 0.003 * (c - 60) / c, FY) - 0.85 * FC)
    bottom = 3 * a_bar * FY
    pn = cc + top - bottom
    mn = cc * (200 - a / 2) + top * 140 + bottom * 140
    phi_pn, phi_mn = 0.65 * pn, 0.65 * mn  # εt = εty: compression-controlled
    assert (phi_pn / 1e3, phi_mn / 1e6) == pytest.approx((1037.4, 191.0), abs=0.5)
    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420",
            "cover": 40,
            "longitudinal": [{"position": "perimeter", "count": 8, "dia": 20}],
            "transverse": {"type": "tie", "dia": 10, "spacing": 150},
        }
    )
    section = section_of(RectangleProfile(xDim=400, yDim=400), reinforcement, FC, FY)
    surface = InteractionSurface(section)
    assert surface.moment_capacity(phi_pn, 0.0) == pytest.approx(phi_mn, rel=0.01)

    # A demand at 97 % of that point: the smallest layout carrying it is no heavier than 8Ø20,
    # the one below it does not carry it, and the full surface confirms the pick.
    search = ColumnSearch(_column(400, 400), FC, FY, 200_000, None, Options())
    points = [(phi_pn, 0.97 * phi_mn, 0.0, "1.2D + 1.0E", "C at 0.00 L")]
    index = search.smallest(points)
    assert index is not None
    assert search.layouts[index].area <= 8 * a_bar + 1e-6
    if index > 0:
        assert search.utilisation(index - 1, points) > 1.0
    confirmed = search.confirm(index, points)
    assert confirmed is not None and search.utilisation(confirmed, points, coarse=False) <= 1.0
    required = search.required_area(index, points)
    assert 0.01 * 160000 <= required <= search.layouts[index].area + 1e-6


def test_two_rows_when_one_does_not_fit() -> None:
    # 250 wide, cover 40, Ø10 stirrups: Ø25 bars at 50 mm pitch -> 3 a row (ACI 25.2.1).
    assert bars_per_row(250, 50, 25) == 3
    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420",
            "cover": 40,
            "longitudinal": [
                {"position": "top", "count": 2, "dia": 12},
                {"position": "bottom", "count": 5, "dia": 25},
            ],
            "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
        }
    )
    section = section_of(RectangleProfile(xDim=250, yDim=500), reinforcement, FC, FY)
    rows = sorted({round(b.y, 1) for b in section.bars if b.y < 0})
    # Outer row at 250 - 50 - 12.5 = 187.5 below the centroid, the next 25 + 25 mm higher.
    assert rows == [-187.5, -137.5]
    assert sum(1 for b in section.bars if round(b.y, 1) == -187.5) == 3
    # d to the centroid of the 3 + 2 bars: 250 + (3 × 187.5 + 2 × 137.5) / 5 = 417.5 mm.
    assert section.effective_depth(top=False) == pytest.approx(417.5)
    assert any("2 rows" in n for n in section.notes)
    # With a 20 mm aggregate the least clear spacing is max(25, 25, 26.7) = 26.7 mm: still 3.
    assert bars_per_row(250, 50, 25, 20) == 3
    assert bars_per_row(250, 50, 25, 32) == 2  # 4/3 × 32 = 42.7 mm clear
    assert flexure(section, False).phi_mn > 0


def test_foundation_demands_from_the_substructure_checks() -> None:
    """Pile caps report moments over the cap width and the strut-and-tie force; rafts per
    metre (Wood-Armer); checks bars cannot fix are listed with their remedy."""
    from types import SimpleNamespace

    from saengine.design.required import foundation_demands
    from saengine.library.substructure import Foundation

    cap = Foundation.model_validate(
        {
            "id": "PC1", "type": "pileCap", "columns": ["C1"], "length": 1500, "width": 1500,
            "thickness": 800, "material": "C28", "center": [0, 0], "piles": ["PL1", "PL2"],
            "reinforcement": {"material": "B420", "cover": 75,
                              "bottomX": {"dia": 16, "spacing": 150}},
        }
    )  # fmt: skip
    raft = Foundation.model_validate(
        {
            "id": "R1", "type": "raft", "outline": [[0, 0], [9000, 0], [9000, 6000]],
            "thickness": 600, "material": "C28",
        }
    )  # fmt: skip
    material = SimpleNamespace(concrete=SimpleNamespace(fc=FC), steel=SimpleNamespace(fy=FY))
    context = SimpleNamespace(
        substructure=SimpleNamespace(foundations=[cap, raft]),
        concrete=lambda *_: material,
        rebar=lambda *_: material,
    )

    def check(name: str, demand: float, ok: bool = True, flag: bool = False) -> dict:
        return {"name": name, "demand": demand, "ok": ok, "flag": flag, "utilisation": 1.2,
                "combination": "1.2D + 1.6L", "note": ""}  # fmt: skip

    report = {
        "foundations": [
            {"id": "PC1", "checks": [
                check("Flexure bottom X at the column face (deep cap: strut-and-tie governs)",
                      300.0, flag=True),
                check("Tie (bottom X bars, strut-and-tie)", 900.0),
                check("Punching at C1", 1500.0, ok=False),
            ]},
            {"id": "R1", "checks": [
                check("Flexure top Y (Wood-Armer)", 80.0),
                check("Contact pressure (net)", 180.0, ok=False),
            ]},
        ]
    }  # fmt: skip
    gathered = SimpleNamespace(
        substructure=report,
        context=context,
        objects_text='{"objects": []}',
        materials=SimpleNamespace(materials=[]),
    )
    cap_demand, raft_demand = foundation_demands(gathered)  # type: ignore[arg-type]
    # 300 kN·m over the 1500 mm cap width = 200 kN·m/m; the tie 900 kN / 1.5 m = 600 kN/m.
    assert cap_demand.moments["bottomX"].value == pytest.approx(200e6)
    assert cap_demand.ties["X"].value == pytest.approx(600e3)
    required, _, notes, _ = foundation_layer_need(cap_demand, "bottomX", 717.0)
    # As = T / (φ fy) = 600e3 / (0.75 × 420) = 1904.8 mm²/m (ACI 23.7.2.1) > flexure, As,min.
    assert required == pytest.approx(600e3 / (0.75 * FY))
    assert any("strut-and-tie" in n for n in notes)
    assert cap_demand.failing and "thicker" in cap_demand.failing[0]
    assert raft_demand.moments["topY"].value == pytest.approx(80e6)
    assert raft_demand.failing and "larger foundation" in raft_demand.failing[0]


def test_torsion_row_adds_the_shear_av_s_per_leg() -> None:
    """Required steel's stirrup row asks each outer leg for At/s + Av/(n s), as the torsion
    design check does (Sec 6.4.4.3.8), not At/s alone."""
    from types import SimpleNamespace

    from saengine.design.required import torsion_rows
    from saengine.design.torsion import TorsionDesign

    design = TorsionDesign(
        tu=30e6, tu_design=30e6, kind="equilibrium", phi_tth=8e6, phi_tcr=30e6, required=True,
        reduced=False, at_s=0.40, at_s_min=0.15, al=600.0, al_min=300.0, av_2at_s_min=0.3,
        s_max=250.0, long_dia_min=10.0, stress=2.0, stress_limit=3.0, vc=100e3, fy=420.0,
        fyt=420.0, phi=0.75, flanges=False, av_s=0.50,
    )  # fmt: skip
    transverse = SimpleNamespace(dia=10.0, spacing=150.0, legs=2)
    member = {
        "torsion": design,
        "object": SimpleNamespace(reinforcement=SimpleNamespace(transverse=transverse)),
        "id": "B1",
        "type": "beam",
    }
    row = torsion_rows(member, assumed=False)[0]
    assert row["required"] == pytest.approx((0.40 + 0.50 / 2) * 1000)
    leg = math.pi * 25 / 150 * 1000  # Ø10 at 150: 523.6 mm²/m per leg
    assert row["provided"] == pytest.approx(leg, abs=0.1)
    # 523.6 covers At/s = 400 alone but not At/s + Av/(2s) = 650: the row fails.
    assert row["ok"] is False

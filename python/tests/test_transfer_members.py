"""Deep beams and transfer girders (BNBC 2020 Part 6 Sec 6.4.6), corbels (Sec 6.4.7), the
shared strut-and-tie capacities (Sec 6.2.3.2, ACI 318-19 Chapter 23) and the diaphragm force
(ASCE 7-05 Sec 12.10.1.1, Sec 2.5.5.6.3)."""

from __future__ import annotations

import math

import pytest

from saengine.design import stm
from saengine.design.corbels import CorbelDemand, corbel_checks
from saengine.design.deep_beams import DeepSpan, SpanDemands, deep_span_checks, is_deep, web_steel
from saengine.design.diaphragms import _tributary, diaphragm_forces
from saengine.library.modifiers import Corbel


def _by_name(checks: list[dict]) -> dict[str, dict]:
    return {c["name"]: c for c in checks}


# ── strut-and-tie (ACI 318-19 Chapter 23, φ of BNBC Sec 6.2.3.2) ──


def test_stm_capacities():
    assert stm.phi() == pytest.approx(0.75)
    # Tie: φ As fy (23.7.2.1).
    assert stm.tie_capacity(1000, 420) == pytest.approx(0.75 * 1000 * 420)
    # Nodes: φ 0.85 βn f'c Anz, βn 1.0 / 0.8 / 0.6 (Table 23.9.2).
    assert stm.node_capacity(30, 1e5, "CCC") == pytest.approx(0.75 * 0.85 * 1.0 * 30 * 1e5)
    assert stm.node_capacity(30, 1e5, "CCT") == pytest.approx(0.75 * 0.85 * 0.8 * 30 * 1e5)
    assert stm.node_capacity(30, 1e5, "CTT") == pytest.approx(0.75 * 0.85 * 0.6 * 30 * 1e5)
    # Struts: βs 1.0 prism, 0.75 bottle with web steel, 0.6 without (Table 23.4.3).
    assert stm.strut_capacity(30, 1e5, "prism") == pytest.approx(0.75 * 0.85 * 30 * 1e5)
    assert stm.strut_capacity(30, 1e5, "bottle", True) == pytest.approx(0.75 * 0.85 * 0.75 * 3e6)
    assert stm.strut_capacity(30, 1e5, "bottle", False) == pytest.approx(0.75 * 0.85 * 0.6 * 3e6)
    assert stm.min_angle() == pytest.approx(25.0)  # 23.2.7
    # ws = lb sin θ + wt cos θ (Fig. R23.2.6b).
    theta = math.radians(45)
    assert stm.strut_width(400, 200, theta) == pytest.approx(600 * math.sqrt(0.5))


# ── deep beams (Sec 6.4.6) ──


def _span(**kw) -> DeepSpan:
    values = {
        "clear": 3000.0,
        "depth": 1200.0,
        "width": 400.0,
        "d": 1100.0,
        "fc": 30.0,
        "fy": 420.0,
        "bearings": (500.0, 500.0),
        "tie_area": 4000.0,
        "tie_height": 200.0,
        "vertical": (2 * 113.1, 200.0),
        "horizontal": (2 * 113.1, 200.0),
    }
    values.update(kw)
    return DeepSpan(**values)


def test_deep_by_span_ratio():
    # ln <= 4 h (Sec 6.4.6.1 (a)).
    assert is_deep(_span(clear=4800.0))[0]
    assert not is_deep(_span(clear=4801.0))[0]


def test_deep_by_load_near_support():
    # A concentrated load within 2 h of the face (Sec 6.4.6.1 (b)): h = 600, 2 h = 1200.
    span = _span(clear=6000.0, depth=600.0, d=540.0, loads=[(1400.0, 400.0)])
    assert is_deep(span)[0]  # its face 1200 mm from the support's
    span = _span(clear=6000.0, depth=600.0, d=540.0, loads=[(1500.0, 400.0)])
    assert not is_deep(span)[0]


def test_web_steel_ratios_and_spacing():
    web = web_steel(_span())
    # Av / (bw s) = 226.2 / (400 · 200); least 0.0025 vertical, 0.0015 horizontal (6.4.6.3-4).
    assert web["vertical"]["ratio"] == pytest.approx(226.2 / 80000)
    assert web["vertical"]["required"] == pytest.approx(0.0025)
    assert web["horizontal"]["required"] == pytest.approx(0.0015)
    # s at most d/5 and 300 mm: d = 1100 → 220 mm.
    assert web["vertical"]["allowed"] == pytest.approx(220.0)


def test_deep_span_checks():
    span = _span(loads=[(1500.0, 500.0)])
    demands = SpanDemands(
        reactions=((1.2e6, "c"), (1.2e6, "c")),
        moment=(1.5e9, "c"),
        shear=(1.2e6, "c"),
        loads=[(2.4e6, "c")],
    )
    checks = _by_name(deep_span_checks(span, demands))
    # Vn limit φ 0.83 √f'c bw d (6.4.6.2).
    limit = checks["Deep beam shear limit"]
    assert limit["capacity"] == pytest.approx(0.75 * 0.83 * math.sqrt(30) * 400 * 1100 / 1e3, 0.01)
    # Tie: a = 250 + 1500 = 1750 mm, z = 0.9 d = 990 mm, T = R a / z.
    tie = checks["Tie (bottom bars, strut-and-tie)"]
    assert tie["demand"] == pytest.approx(1.2e6 * 1750 / 990 / 1e3, 0.01)
    assert tie["capacity"] == pytest.approx(0.75 * 4000 * 420 / 1e3, 0.01)
    # θ = atan(990 / 1750) = 29.5° >= 25°.
    angle = checks["Strut angle at the left support"]
    assert angle["capacity"] == pytest.approx(math.degrees(math.atan2(990, 1750)), 0.01)
    assert angle["ok"]
    # C-C-T node at the support: φ 0.85 · 0.8 f'c lb bw.
    node = checks["Node at the left support (C-C-T)"]
    assert node["capacity"] == pytest.approx(0.75 * 0.85 * 0.8 * 30 * 500 * 400 / 1e3, 0.01)
    # C-C-C node under the landing column.
    landing = checks["Node under the landing column at 1500 mm (C-C-C)"]
    assert landing["capacity"] == pytest.approx(0.75 * 0.85 * 30 * 500 * 400 / 1e3, 0.01)


# ── corbels (Sec 6.4.7) ──


def _corbel(**kw) -> Corbel:
    values = {
        "width": 400,
        "depth": 500,
        "edgeDepth": 300,
        "projection": 350,
        "mainBars": {"count": 4, "dia": 20},
        "ties": {"count": 3, "dia": 12},
        "bearing": 150,
    }
    values.update(kw)
    return Corbel(**values)


def test_corbel_steel():
    checks = _by_name(corbel_checks(_corbel(), 30, 420, CorbelDemand(400e3, "c")))
    d = 500 - 40 - 10
    # Vn,max = min(0.2 f'c, 3.3 + 0.08 f'c, 11) bw d = 5.7 bw d at f'c 30 (6.4.7.3.2).
    assert checks["Corbel: shear limit"]["capacity"] == pytest.approx(
        0.75 * 5.7 * 400 * d / 1e3, 0.01
    )
    # As >= (2/3) Avf + An: Avf = Vu / (φ fy 1.4), An = 0.2 Vu / (φ fy) (6.4.7.3.4-5).
    avf = 400e3 / (0.75 * 420 * 1.4)
    an = 0.2 * 400e3 / (0.75 * 420)
    main = checks["Corbel: main bars As"]
    assert main["demand"] >= 2 / 3 * avf + an - 1
    assert main["demand"] >= 0.04 * 30 / 420 * 400 * d - 1  # 6.4.7.5
    # Ah >= 0.5 (As - An) (6.4.7.4).
    ties = checks["Corbel: closed ties Ah"]
    assert ties["demand"] == pytest.approx(0.5 * (4 * math.pi * 100 - an), 0.01)
    # av / d at most 1 (6.4.7.1): av = 175 mm.
    assert checks["Corbel: shear span av / d"]["demand"] == pytest.approx(175 / d, 0.01)


def test_corbel_too_long_fails():
    checks = _by_name(corbel_checks(_corbel(loadOffset=600), 30, 420, CorbelDemand(100e3, None)))
    assert not checks["Corbel: shear span av / d"]["ok"]


# ── diaphragms (ASCE 7-05 Sec 12.10.1.1; Sec 2.5.5.6.3) ──


def test_diaphragm_force_bounds():
    # Two levels; Fpx = Σ F / Σ w · wpx, between 0.2 and 0.4 SDS I wpx.
    rows = diaphragm_forces([3.0, 6.0], [100e3, 200e3], [1000e3, 1000e3], 0.5, 1.0)
    fpx0, low0, high0 = rows[0]
    assert low0 == pytest.approx(0.2 * 0.5 * 1000e3)
    assert high0 == pytest.approx(0.4 * 0.5 * 1000e3)
    assert fpx0 == pytest.approx(150e3)  # 300 / 2000 · 1000 kN
    assert rows[1][0] == pytest.approx(200e3)  # 200 / 1000 · 1000, at the upper bound


def test_tributary_width():
    lines = [0.0, 6000.0, 12000.0]
    assert _tributary(lines, 0.0, 0.0, 12000.0) == pytest.approx(3000.0)
    assert _tributary(lines, 6000.0, 0.0, 12000.0) == pytest.approx(6000.0)


# ── diaphragm chords: the slab's edge bars and the proposal's chord bars (2026-11-02) ──


def test_chord_strip_comes_from_the_pack_and_can_be_overridden():
    from saengine.codes import context as code_context
    from saengine.design.diaphragms import chord_strip

    width, source = chord_strip()
    # The default pack gives the strip and says the code gives no width (SAEngine practice).
    assert width == 1000.0 and "SAEngine practice" in source
    pack = code_context.default_pack().with_overrides({"transfer.diaphragm.chordStrip": 600})
    with code_context.using(pack):
        width, source = chord_strip()
    assert width == 600.0 and source.startswith("project override")


def test_slab_strip_and_chord_bar_areas():
    from saengine.design.diaphragms import chord_bars_area, strip_area

    mesh = {
        "bottomX": {"dia": 10, "spacing": 125},
        "bottomY": {"dia": 10, "spacing": 200},
        "topY": {"dia": 12, "spacing": 250},
        "chordBars": {"count": 2, "dia": 16},
    }
    # Bars along Y within a 1 m strip: Ø10 @ 200 bottom, Ø12 @ 250 top.
    assert strip_area(mesh, "Y", 1000) == pytest.approx(
        math.pi * 10**2 / 4 * 1000 / 200 + math.pi * 12**2 / 4 * 1000 / 250
    )
    assert strip_area(mesh, "X", 1000) == pytest.approx(math.pi * 10**2 / 4 * 1000 / 125)
    assert chord_bars_area(mesh) == pytest.approx(2 * math.pi * 16**2 / 4)
    assert chord_bars_area({"bottomX": mesh["bottomX"]}) == 0.0


def test_chord_bars_count_at_a_free_edge_only():
    from types import SimpleNamespace

    from saengine.design.diaphragms import _weakest_slab
    from saengine.library.objects import PlanarReinforcement

    bars = PlanarReinforcement.model_validate(
        {
            "material": "B420",
            "cover": 20,
            "bottomY": {"dia": 10, "spacing": 200},
            "chordBars": {"count": 2, "dia": 16},
        }
    )
    types = {"S150": SimpleNamespace(reinforcement=bars)}
    mats = {"B420": SimpleNamespace(steel=SimpleNamespace(fy=420.0))}
    slab = [SimpleNamespace(id="S1", type="S150")]
    mesh = math.pi * 10**2 / 4 * 1000 / 200
    chord = 2 * math.pi * 16**2 / 4
    free = _weakest_slab(slab, types, mats, 0.9, "Y", 1000.0, True)
    assert free == (pytest.approx(0.9 * 420 * (mesh + chord)), "S1", "2Ø16")
    beside_beams = _weakest_slab(slab, types, mats, 0.9, "Y", 1000.0, False)
    assert beside_beams == (pytest.approx(0.9 * 420 * mesh), "S1", "")


def test_free_edges_are_the_floor_outline_without_beams_along_it():
    from saengine.design.diaphragms import free_edges
    from saengine.library.bim import BuildingModel

    def slab(id_, x0, x1):
        return {
            "kind": "slab",
            "id": id_,
            "type": "S150",
            "elevation": 3000,
            "boundary": [[x0, 0], [x1, 0], [x1, 5000], [x0, 5000]],
        }

    def beam(id_, start, end):
        return {
            "kind": "beam",
            "id": id_,
            "type": "B",
            "start": start,
            "end": end,
            "elevation": 3000,
        }

    building = BuildingModel.model_validate(
        {
            "elements": [
                slab("S1", 0, 6000),
                slab("S2", 6000, 13000),
                # Edge beams along y = 0 and 5000 (B1 stops 1 m short), one across at x = 6000
                # (an inner line) and one at y = 2500, square to the free edges.
                beam("B1", [0, 0], [12000, 0]),
                beam("B2", [0, 5000], [13000, 5000]),
                beam("B3", [6000, 0], [6000, 5000]),
                beam("B4", [0, 2500], [13000, 2500]),
            ]
        }
    )
    edges = free_edges(building)
    # The x = 0 and x = 13 m edges are free; S2 also keeps the last metre along y = 0.
    assert edges == {"S1": pytest.approx(5000.0), "S2": pytest.approx(6000.0)}


def test_proposal_adds_chord_bars_for_a_free_edge_shortfall():
    from saengine.design.proposal import _with_chord_bars

    chord = {
        "axis": "X",
        "edge": "-X edge",
        "story": "Level 1",
        "force_kN": 400.0,
        "beams_kN": 0.0,
        "free": True,
        "slabs": ["S1"],
        "direction": "Y",
        "strip": 1000.0,
        "phi": 0.9,
    }
    proposed = {
        "material": "B420",
        "cover": 20,
        "bottomY": {"dia": 10, "spacing": 200},
        "text": "bottom Y Ø10 @ 200",
    }
    edges = {"S1": [chord]}
    notes = _with_chord_bars(proposed, ["S1"], edges, 420.0, (12.0, 16.0, 20.0))
    # The mesh gives 0.9 × 392.7 mm² × 420 MPa = 148.4 kN; 251.6 kN short: As 665.6 mm², the
    # fewest of 2 to 4 bars: 4Ø16 (Ø12 would take 6).
    assert proposed["chordBars"] == {"count": 4, "dia": 16.0}
    assert proposed["text"].endswith("chord bars 4Ø16 along the free edges")
    assert "Level 1 -X edge" in notes[0] and "4Ø16" in notes[0]
    # Enough slab bars: no chord bars (earlier ones are dropped).
    edges = {"S1": [{**chord, "force_kN": 100.0}]}
    assert _with_chord_bars(proposed, ["S1"], edges, 420.0, (16.0,)) == []
    assert "chordBars" not in proposed and proposed["text"] == "bottom Y Ø10 @ 200"
    # An edge with beams that falls short is for the beams' bars: a note, no chord bars.
    edges = {"S1": [{**chord, "free": False, "beams_kN": 50.0}]}
    notes = _with_chord_bars(proposed, ["S1"], edges, 420.0, (16.0,))
    assert "chordBars" not in proposed and "give the edge beams more bars" in notes[0]

"""MEP equipment loads on the analysis model and the holes MEP cuts in it (hand calculations)."""

from __future__ import annotations

import math
import time

import numpy as np
import pytest

from saengine.fem.derive import CASES as MODEL_CASES
from saengine.library.bim import BuildingModel
from saengine.library.mep import Equipment, MepModel
from saengine.mep.geometry import bounded_id
from saengine.mep.loads import (
    G,
    analysis_openings,
    bay_of,
    contents_case,
    edge_shares,
    equipment_loads,
    equipment_parts,
    heavy_on_slab,
    impact_percent,
    plinth_weight,
    with_mep_openings,
)

# A 4 x 4 m slab at L1 (+3.0 m) meshed as 2 x 2 four-node shells of 2 m.
BUILDING = BuildingModel.model_validate(
    {
        "stories": [
            {"id": "BASE", "name": "Base", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3000},
            {"id": "L2", "name": "Level 2", "elevation": 6000},
            {"id": "L3", "name": "Level 3", "elevation": 9000},
        ],
        "elements": [
            {
                "id": f"S{k}",
                "type": "SL",
                "kind": "slab",
                "boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                "elevation": z,
            }
            for k, z in ((1, 3000), (2, 6000), (3, 9000))
        ]
        + [
            {
                "id": "W1",
                "type": "WL",
                "kind": "wall",
                "start": [0, 0],
                "end": [0, 4000],
                "bottom": 0,
                "top": 3000,
            }
        ],
        "additions": {
            "slabOpenings": [
                {"id": "O1", "host": "S3", "x": 1000, "y": 1000, "xDim": 800, "yDim": 600}
            ]
        },
    }
)

#: The analysis cases without the fluid case F (a model before F, or one without fluid loads).
CASES = [c for c in MODEL_CASES if c != "F"]


def mesh() -> tuple[dict[int, np.ndarray], list[tuple[str, tuple[int, ...]]]]:
    """Nodes of S1 [m] every 2 m over 0..6 x 0..4 and its shells."""
    nodes, ids = {}, {}
    for i, x in enumerate((0.0, 2.0, 4.0, 6.0)):
        for j, y in enumerate((0.0, 2.0, 4.0)):
            ids[i, j] = len(nodes) + 1
            nodes[ids[i, j]] = np.array([x, y, 3.0])
    shells = [
        ("S1", (ids[i, j], ids[i + 1, j], ids[i + 1, j + 1], ids[i, j + 1]))
        for i in range(3)
        for j in range(2)
    ]
    return nodes, shells


def item(**fields) -> Equipment:
    base = {
        "id": "EQ1",
        "story": "L1",
        "x": 1000,
        "y": 1000,
        "length": 1000,
        "width": 1000,
        "operatingWeight": 120,
    }
    return Equipment.model_validate({**base, **fields})


def test_cases_impact_and_plinth() -> None:
    tank = item(kind="tank", emptyWeight=20)
    dead = {p.what: (p.case, p.total) for p in equipment_parts(tank, "dead")}
    assert dead == {"empty weight": ("SD", 20e3), "contents": ("SD", 100e3)}
    live = {p.what: (p.case, p.total) for p in equipment_parts(tank, "live")}
    assert live == {"empty weight": ("SD", 20e3), "contents": ("L", 100e3)}
    # Fluid (the default): BNBC 2.7.3.1 has F only in 1.4(D + F) and 1.2(D + F + T) + ..., so
    # the contents get their own case F when the model has one, else L; never SD, which the
    # 0.9D combinations would count as resisting uplift.
    with_f = {p.what: p.case for p in equipment_parts(tank, "fluid", cases=[*CASES, "F"])}
    assert with_f == {"empty weight": "SD", "contents": "F"}
    without_f = {p.what: p.case for p in equipment_parts(tank, "fluid", cases=CASES)}
    assert without_f == {"empty weight": "SD", "contents": "L"}
    assert contents_case("fluid") == "F"
    assert MepModel().contentsAs == "fluid"

    # BNBC Table 6.2.6: light machinery 20 %, reciprocating 50 %, lifts 100 % of the operating
    # weight, as live load that adds nothing to the seismic weight.
    assert impact_percent(item(kind="pump", vibrating=True))[0] == 20
    assert impact_percent(item(kind="generator", vibrating=True))[0] == 50
    assert impact_percent(item(kind="lift"))[0] == 100
    assert impact_percent(item(kind="pump"))[0] == 0
    assert impact_percent(item(kind="pump", vibrating=True, impact=35))[0] == 35
    pump = {p.what: p for p in equipment_parts(item(kind="pump", vibrating=True), "dead")}
    assert pump["impact 20 %"].case == "L"
    assert pump["impact 20 %"].total == pytest.approx(24e3)
    assert pump["impact 20 %"].weight_share == 0

    # 1.0 x 1.0 m x 150 mm of 2400 kg/m³ concrete = 0.15 m³ x 23.536 kN/m³ = 3.530 kN.
    plinth = item(plinth={"height": 150, "material": "C25"})
    assert plinth_weight(plinth, {"C25": 2400}) == pytest.approx(0.15 * 2400 * G / 1e3)
    assert plinth_weight(plinth, {}) == pytest.approx(0.15 * 24.0)


def test_area_load_centred_on_a_shell() -> None:
    # 120 kN over 1 x 1 m centred on the first shell (0..2 x 0..2 m): by symmetry its four
    # nodes take a quarter each.
    nodes, shells = mesh()
    loads = equipment_loads(BUILDING, MepModel(equipment=[item()]), nodes, shells)
    by_node: dict[int, float] = {}
    for load in loads.nodal:
        assert load.case == "SD"
        by_node[load.node] = by_node.get(load.node, 0.0) - load.force[2]
    corners = shells[0][1]
    assert set(by_node) == set(corners)
    for node in corners:
        assert by_node[node] == pytest.approx(30e3)
    assert loads.totals() == pytest.approx({"SD": 120.0})
    assert sum(load.weight for load in loads.nodal) == pytest.approx(120e3)
    assert loads.summary[0]["slabs"] == ["S1"]
    assert loads.summary[0]["pressure"] == pytest.approx(120.0)  # kPa


def test_point_load_bilinear_shares() -> None:
    # One support at (0.5, 0.5) m in the shell 0..2 x 0..2: ξ = η = -0.5, so the corners get
    # (1.5 x 1.5, 0.5 x 1.5, 0.5 x 0.5, 1.5 x 0.5) / 4 of it.
    nodes, shells = mesh()
    single = item(x=500, y=500, loadAs="points", supports=[[0, 0]], operatingWeight=100)
    loads = equipment_loads(BUILDING, MepModel(equipment=[single]), nodes, shells)
    got = {load.node: -load.force[2] for load in loads.nodal}
    expected = [0.5625, 0.1875, 0.0625, 0.1875]
    for node, share in zip(shells[0][1], expected, strict=True):
        assert got[node] == pytest.approx(100e3 * share)
    # The resultant stays where the load is.
    x = sum(got[n] * nodes[n][0] for n in got) / sum(got.values())
    assert x == pytest.approx(0.5)


def test_supports_carry_equal_shares() -> None:
    nodes, shells = mesh()
    legs = item(x=2000, y=2000, length=1000, width=600, loadAs="points", operatingWeight=80)
    loads = equipment_loads(BUILDING, MepModel(equipment=[legs]), nodes, shells)
    # Four corners at (1.5|2.5, 1.7|2.3) m: 20 kN each, all of it applied.
    assert loads.totals()["SD"] == pytest.approx(80.0)
    centre_x = sum(-ld.force[2] * nodes[ld.node][0] for ld in loads.nodal) / 80e3
    centre_y = sum(-ld.force[2] * nodes[ld.node][1] for ld in loads.nodal) / 80e3
    assert (centre_x, centre_y) == pytest.approx((2.0, 2.0))


def test_edge_shares_by_hand() -> None:
    # 6 x 4 m two-way rectangle, load at (2, 1) m: s = 1/3 along edge 0, t = 1/4 across it.
    # Crossing strips of equal deflection: the 4 m span takes 6³ / (6³ + 4³) = 0.7714.
    boundary = [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]
    shares = dict(edge_shares(boundary, (2000, 1000)))
    span_4 = 216 / 280
    assert shares[0] == pytest.approx(span_4 * 0.75)
    assert shares[2] == pytest.approx(span_4 * 0.25)
    assert shares[3] == pytest.approx((1 - span_4) * 2 / 3)
    assert shares[1] == pytest.approx((1 - span_4) / 3)
    assert sum(shares.values()) == pytest.approx(1)
    # One way: all across the short span, by the lever rule.
    assert dict(edge_shares(boundary, (2000, 1000), "oneWay")) == pytest.approx({0: 0.75, 2: 0.25})


def test_loads_to_beams() -> None:
    # Without shells, the 120 kN resultant at (1, 1) m goes to the edges as uniform loads.
    tank = item(kind="tank", emptyWeight=20, vibrating=True)
    mep = MepModel(equipment=[tank], contentsAs="dead")
    loads = equipment_loads(BUILDING, mep, {}, [], {"S1": "twoWay"}, cases=CASES)
    assert not loads.nodal
    totals = loads.totals()
    assert totals["SD"] == pytest.approx(120.0)
    assert totals["L"] == pytest.approx(24.0)  # 20 % impact
    shares = dict(edge_shares(BUILDING.elements[0].boundary, (1000, 1000)))
    edge0 = [ln for ln in loads.lines if ln.case == "SD" and ln.start[:2] == (0.0, 0.0)]
    assert sum(ln.load * 6.0 for ln in edge0) == pytest.approx(120e3 * shares[0])
    assert all(ln.weight_share == 0 for ln in loads.lines if ln.case == "L")
    assert any("hands its loads to its beams" in note for note in loads.notes)
    # Contents as dead load are noted: the 0.9D combinations would count them.
    assert any("0.9D" in note and "always there" in note for note in loads.notes)


def test_contents_as_a_fluid_case() -> None:
    # 120 kN operating, 20 kN empty: 100 kN of contents. With an F case they are F (seismic
    # weight in full); without one, L with a note.
    nodes, shells = mesh()
    tank = item(kind="tank", emptyWeight=20)
    mep = MepModel(equipment=[tank])
    with_f = equipment_loads(BUILDING, mep, nodes, shells, cases=[*CASES, "F"])
    assert with_f.totals() == pytest.approx({"SD": 20.0, "F": 100.0})
    assert sum(ld.weight for ld in with_f.nodal) == pytest.approx(120e3)
    assert not any("no fluid load case" in n for n in with_f.notes)
    without = equipment_loads(BUILDING, mep, nodes, shells, cases=CASES)
    assert without.totals() == pytest.approx({"SD": 20.0, "L": 100.0})
    assert sum(ld.weight for ld in without.nodal) == pytest.approx(120e3)
    assert any("no fluid load case F" in n for n in without.notes)


def test_large_mesh_is_fast() -> None:
    # A 4 x 4 m tank (1600 load points) on a 30 x 30 m flat slab of 3600 shells of 0.5 m: the
    # shells are found through their bounding boxes, not by a scan of the whole slab.
    building = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
            ],
            "elements": [
                {
                    "id": "S1",
                    "type": "SL",
                    "kind": "slab",
                    "boundary": [[0, 0], [30000, 0], [30000, 30000], [0, 30000]],
                    "elevation": 3000,
                }
            ],
        }
    )
    n = 60
    ids = {(i, j): i * (n + 1) + j + 1 for i in range(n + 1) for j in range(n + 1)}
    nodes = {k: np.array([i * 0.5, j * 0.5, 3.0]) for (i, j), k in ids.items()}
    shells = [
        ("S1", (ids[i, j], ids[i + 1, j], ids[i + 1, j + 1], ids[i, j + 1]))
        for i in range(n)
        for j in range(n)
    ]
    tank = item(x=24000, y=24000, length=4000, width=4000, operatingWeight=400, emptyWeight=100)
    start = time.perf_counter()
    loads = equipment_loads(building, MepModel(equipment=[tank]), nodes, shells, cases=CASES)
    assert time.perf_counter() - start < 10.0
    assert loads.totals() == pytest.approx({"SD": 100.0, "L": 300.0})
    # Consistent nodal loads keep the resultant at the tank's centre, (24, 24) m.
    total = sum(-ld.force[2] for ld in loads.nodal)
    cx = sum(-ld.force[2] * nodes[ld.node][0] for ld in loads.nodal) / total
    cy = sum(-ld.force[2] * nodes[ld.node][1] for ld in loads.nodal) / total
    assert (cx, cy) == pytest.approx((24.0, 24.0))


def test_on_grade_and_off_slab_are_noted() -> None:
    nodes, shells = mesh()
    mep = MepModel(equipment=[item(id="G1", story="BASE"), item(id="G2", x=20000, y=20000)])
    loads = equipment_loads(BUILDING, mep, nodes, shells)
    assert not loads.nodal and not loads.lines
    assert any(n.startswith("G1: stands on the base level") for n in loads.notes)
    assert any(n.startswith("G2: not on any slab") for n in loads.notes)


def test_shafts_and_openings_cut_the_analysis_model() -> None:
    mep = MepModel.model_validate(
        {
            "shafts": [
                {
                    "id": "SH1",
                    "outline": [[700, 700], [1300, 700], [1300, 1300], [700, 1300]],
                    "fromStory": "L1",
                    "toStory": "L3",
                }
            ],
            "openings": [
                {
                    "id": "OPW",
                    "host": "W1",
                    "kind": "opening",
                    "shape": "rectangle",
                    "width": 1000,
                    "height": 600,
                    "position": {"x": 2000, "y": 1500},
                },
                {
                    "id": "SLV",
                    "host": "S1",
                    "kind": "sleeve",
                    "diameter": 100,
                    "position": {"x": 3000, "y": 3000},
                },
            ],
        }
    )
    slab_openings, wall_openings, _ = analysis_openings(BUILDING, mep)
    # From L1 up to L3: S2 (L2) is cut; S3 already has O1 there; S1 (L1, where it starts)
    # is not; sleeves stay out of the analysis.
    assert [(o.id, o.host, o.x, o.y, o.xDim, o.yDim) for o in slab_openings] == [
        ("SH1.S2", "S2", 1000, 1000, 600, 600)
    ]
    assert [(o.host, o.offset, o.sill, o.width, o.height) for o in wall_openings] == [
        ("W1", 1500, 1200, 1000, 600)
    ]
    cut, notes = with_mep_openings(BUILDING, mep)
    assert len(cut.additions.slabOpenings) == 2 and len(cut.additions.wallOpenings) == 1
    assert len(BUILDING.additions.slabOpenings) == 1  # the building model is left as it is
    assert cut.check_additions() == []
    assert any("cut into the analysis model" in n for n in notes)


def test_shaft_across_two_slabs_cuts_both() -> None:
    # Two slabs meet at x = 6000; the shaft 5600..6800 x 2000..3000 lies 400 mm in SA and
    # 800 mm in SB: each loses its own part (400 x 1000 and 800 x 1000).
    building = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
            ],
            "elements": [
                {
                    "id": sid,
                    "type": "SL",
                    "kind": "slab",
                    "boundary": [[x0, 0], [x1, 0], [x1, 4000], [x0, 4000]],
                    "elevation": 3000,
                }
                for sid, x0, x1 in (("SA", 0, 6000), ("SB", 6000, 12000))
            ],
        }
    )
    mep = MepModel.model_validate(
        {
            "shafts": [
                {
                    "id": "SH1",
                    "outline": [[5600, 2000], [6800, 2000], [6800, 3000], [5600, 3000]],
                    "fromStory": "BASE",
                    "toStory": "L1",
                }
            ]
        }
    )
    slab_openings, _, notes = analysis_openings(building, mep)
    assert [(o.host, o.x, o.y, o.xDim, o.yDim) for o in slab_openings] == [
        ("SA", 5800, 2500, 400, 1000),
        ("SB", 6400, 2500, 800, 1000),
    ]
    assert any("across slabs SA, SB" in n for n in notes)
    cut, _ = with_mep_openings(building, mep)
    assert cut.check_additions() == []


def test_long_ids_stay_valid() -> None:
    # A 60-character shaft id on 60-character slabs: "<shaft>.<slab>" is 121 characters, over
    # the 64 the libraries accept; the analysis opening ids are cut (with a hash, so the two
    # slabs' openings stay distinct) instead of failing the derivation.
    shaft_id, slab_a, slab_b = "SH" + "x" * 58, "SA" + "y" * 58, "SB" + "y" * 58
    building = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
            ],
            "elements": [
                {
                    "id": sid,
                    "type": "SL",
                    "kind": "slab",
                    "boundary": [[x0, 0], [x1, 0], [x1, 4000], [x0, 4000]],
                    "elevation": 3000,
                }
                for sid, x0, x1 in ((slab_a, 0, 6000), (slab_b, 6000, 12000))
            ],
        }
    )
    mep = MepModel.model_validate(
        {
            "shafts": [
                {
                    "id": shaft_id,
                    "outline": [[5600, 2000], [6800, 2000], [6800, 3000], [5600, 3000]],
                    "fromStory": "BASE",
                    "toStory": "L1",
                }
            ]
        }
    )
    slab_openings, _, _ = analysis_openings(building, mep)
    ids = [o.id for o in slab_openings]
    assert len(ids) == 2 and len(set(ids)) == 2
    assert all(len(i) <= 64 for i in ids)
    cut, _ = with_mep_openings(building, mep)
    assert cut.check_additions() == []


def test_bounded_id() -> None:
    assert bounded_id("SH1.S2") == "SH1.S2"
    assert bounded_id("OP-B 1$x", "-2") == "OP-B-1-x-2"
    long = bounded_id("A" * 100, "-12")
    assert len(long) == 64 and long.endswith("-12") and long.startswith("A" * 40)
    assert bounded_id("A" * 100 + "1") != bounded_id("A" * 100 + "2")


def test_footprint_grid_is_exact() -> None:
    nodes, shells = mesh()
    turned = item(x=3000, y=2000, length=1500, width=700, rotation=30, operatingWeight=50)
    loads = equipment_loads(BUILDING, MepModel(equipment=[turned]), nodes, shells)
    total = sum(-ld.force[2] for ld in loads.nodal)
    assert total == pytest.approx(50e3)
    cx = sum(-ld.force[2] * nodes[ld.node][0] for ld in loads.nodal) / total
    cy = sum(-ld.force[2] * nodes[ld.node][1] for ld in loads.nodal) / total
    assert (cx, cy) == pytest.approx((3.0, 2.0))
    assert not math.isnan(cx)


# ─────────────── a heavy tank on a slab panel, or on the beams of its bay (N-E1) ───────────────

#: BUILDING with beams along the four edges of S1: a column-supported bay.
FRAMED = BuildingModel.model_validate(
    {
        **BUILDING.model_dump(mode="json", by_alias=True),
        "elements": [
            *(e.model_dump(mode="json") for e in BUILDING.elements),
            *(
                {
                    "id": f"B{k}",
                    "type": "BM",
                    "kind": "beam",
                    "start": a,
                    "end": b,
                    "elevation": 3000,
                }
                for k, (a, b) in enumerate(
                    (
                        ([0, 0], [6000, 0]),
                        ([6000, 0], [6000, 4000]),
                        ([6000, 4000], [0, 4000]),
                        ([0, 4000], [0, 0]),
                    )
                )
            ),
        ],
    }
)


def _tank(length: float, width: float) -> Equipment:
    return Equipment(
        id="T", kind="tank", story="L1", x=3000, y=2000, length=length, width=width,
        operatingWeight=570, emptyWeight=150,
    )  # fmt: skip


def test_a_small_heavy_tank_mid_panel_is_flagged():
    # 570 kN on 3 x 2 m = 95 kPa over a quarter of the 6 x 4 m panel: not on the beams.
    message = heavy_on_slab(_tank(3000, 2000), FRAMED)
    assert message is not None and "95.0 kPa" in message and "re-run 08 FEM" in message
    assert bay_of(_tank(3000, 2000), FRAMED) is None


def test_a_tank_covering_its_framed_bay_goes_to_the_beams():
    # 5.6 x 3.6 m covers 84 % of the panel, framed by B0-B3: its whole weight goes to the
    # edge beams as line loads (same total), none to the slab's shell nodes.
    tank = _tank(5600, 3600)
    assert bay_of(tank, FRAMED) is not None
    assert heavy_on_slab(tank, FRAMED) is None
    nodes, shells = mesh()
    mep = MepModel(equipment=[tank])
    result = equipment_loads(FRAMED, mep, nodes, shells, cases=CASES)
    assert not result.nodal
    assert sum(result.totals().values()) == pytest.approx(570.0)
    # Without the beams the same tank stays on the slab's shells.
    plain = equipment_loads(BUILDING, mep, nodes, shells, cases=CASES)
    assert plain.nodal and not plain.lines

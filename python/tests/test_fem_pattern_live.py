"""Pattern live loading (saengine.fem.pattern_live): the arrangements of BNBC 2020 Part 6 Sec
6.1.12.2 on a grid, their combinations, and a 3-span continuous beam solved with OpenSees and
checked against moment distribution by hand."""

from __future__ import annotations

import pytest

from saengine.fem.combinations import combination_factors, pattern_live_combinations
from saengine.fem.pattern_live import (
    Grid,
    centroid,
    grid_lines,
    live_patterns,
    patterns_required,
)
from saengine.library.settings import LoadCombination

# The default pack's clauses of the arrangements (concrete.clauses patternAdjacent, patternAlternate),
# as the code had them before they moved into the pack.
CLAUSE_ADJACENT = "BNBC 2020 Part 6 Sec 6.1.12.2 (a)"
CLAUSE_ALTERNATE = "BNBC 2020 Part 6 Sec 6.1.12.2 (b)"

SPAN = 6000.0  # mm
GRID = Grid((0.0, SPAN, 2 * SPAN, 3 * SPAN), (0.0, 5000.0))


def test_grid_lines_cluster_within_300_mm() -> None:
    assert grid_lines([0, 120, 6000, 6000, 5900, 12000]) == pytest.approx(
        (60.0, 5966.67, 12000.0), abs=0.01
    )
    grid = Grid.of([(0, 0), (6000, 10), (12000, 0), (0, 5000), (6000, 4990)])
    assert grid.xs == (0.0, 6000.0, 12000.0) and grid.bays("X") == 2
    assert grid.ys == pytest.approx((3.33, 4995.0), abs=0.01) and grid.bays("Y") == 1
    assert [GRID.bay("X", x) for x in (-500, 0, 3000, 6000, 17000, 18000, 18500)] == [
        -1, 0, 0, 1, 2, 2, 3,
    ]  # fmt: skip


def test_arrangements_of_a_three_by_one_grid() -> None:
    """Three bays along X, one along Y: (b) bays 1 + 3 and bay 2; (a) bays 1 + 2 and 2 + 3;
    nothing along Y (one bay)."""
    patterns = live_patterns(GRID)
    assert [(p.name, sorted(p.bays), p.clause) for p in patterns] == [
        ("LP1", [0, 2], CLAUSE_ALTERNATE),
        ("LP2", [1], CLAUSE_ALTERNATE),
        ("LP3", [0, 1], CLAUSE_ADJACENT),
        ("LP4", [1, 2], CLAUSE_ADJACENT),
    ]
    lp1 = patterns[0]
    assert lp1.loads(GRID, 3000, 2500) and not lp1.loads(GRID, 9000, 2500)
    assert lp1.loads(GRID, 15000, 100)
    # A cantilever beyond the last line continues the alternation (bay 3 is "even" like 1).
    assert not lp1.loads(GRID, 19000, 100) and patterns[1].loads(GRID, 19000, 100)
    assert not patterns[2].loads(GRID, 19000, 100)  # adjacent: never the cantilever
    # A 2 x 2 grid: alternate only (an adjacent pair of two bays is the full live case).
    two = live_patterns(Grid((0, 6000, 12000), (0, 5000, 10000)))
    assert [p.label for p in two] == [
        "Live load on alternate bays along X: 1",
        "Live load on alternate bays along X: 2",
        "Live load on alternate bays along Y: 1",
        "Live load on alternate bays along Y: 2",
    ]
    assert centroid([(0, 0), (6000, 0), (6000, 5000), (0, 5000)]) == pytest.approx((3000, 2500))


def test_combinations_replace_the_live_case_in_gravity_combinations_only() -> None:
    combos = [
        LoadCombination(name="1.2D+1.6L", D=1.2, L=1.6),
        LoadCombination(name="1.4D", D=1.4),
        LoadCombination(name="1.2D+1.0L+1.0EX", D=1.2, L=1.0, EX=1.0),
    ]
    patterns = live_patterns(GRID)
    assert patterns[0].clause == CLAUSE_ALTERNATE and patterns[2].clause == CLAUSE_ADJACENT
    present = {"D", "SD", "L", "EX", *(p.name for p in patterns)}
    out = pattern_live_combinations(combos, present)
    assert out is not None and out[:3] == combos
    assert [c.name for c in out[3:]] == [f"1.2D+1.6L [LP{k}]" for k in range(1, 5)]
    assert combination_factors(out[3], set()) == {"D": 1.2, "SD": 1.2, "LP1": 1.6}


def test_flat_slab_light_live_exemption_only() -> None:
    assert patterns_required("flat", 6.0, 4.0)[0] is False  # 4 <= 0.75 x 6 (Sec 6.5.7.6.2)
    assert patterns_required("flat", 6.0, 5.0)[0] is True
    assert patterns_required("twoWay", 6.0, 2.0)[0] is True  # beams: Sec 6.1.12.2, no exemption


def _three_span_moments(loaded: list[float]) -> tuple[list[float], float]:
    """Support moments M_B, M_C [kN·m] (hogging positive) and the largest sagging moment in
    span 1 [kN·m] of three equal 6 m spans on knife-edge supports, uniform loads ``loaded``
    [kN/m] on the spans, solved with OpenSees (one elastic element per span; eleLoad
    beamUniform gives the exact fixed-end forces)."""
    import openseespy.opensees as ops

    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 3)
    length = SPAN / 1e3
    for k in range(4):
        ops.node(k + 1, k * length, 0.0)
        ops.fix(k + 1, 1 if k == 0 else 0, 1, 0)
    ops.geomTransf("Linear", 1)
    for k in range(3):
        ops.element("elasticBeamColumn", k + 1, k + 1, k + 2, 0.1, 30e6, 1e-3, 1)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    for k, w in enumerate(loaded):
        if w:
            ops.eleLoad("-ele", k + 1, "-type", "-beamUniform", -w)
    ops.system("BandGeneral")
    ops.numberer("RCM")
    ops.constraints("Plain")
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    # localForce of element 1: N_i V_i M_i N_j V_j M_j (counter-clockwise positive).
    force = ops.eleResponse(1, "localForce")
    m_b = -force[5]  # hogging at B: the end moment on span 1 at j is clockwise (negative)
    m_c = -ops.eleResponse(2, "localForce")[5]
    v_a = force[1]  # upward reaction share at A
    w1 = loaded[0]
    span1 = v_a**2 / (2 * w1) if w1 else 0.0  # M_A = 0: the largest moment where V = 0
    ops.wipe()
    return [m_b, m_c], span1


def test_three_span_beam_alternate_and_adjacent_arrangements_by_hand() -> None:
    """Three equal spans L = 6 m, EI constant, end supports pinned; dead 20, live 15 kN/m;
    1.2D + 1.6L: wD = 24, wL = 24 kN/m (w = 48 kN/m).

    Full live (all spans, w = 48): M_B = w L²/10 = 48 x 36 / 10 = 172.8 kN·m; span 1 R_A =
    48 x 6 / 2 - 172.8 / 6 = 115.2 kN, M+ = R_A² / 2w = 138.24 kN·m.

    (b) live on spans 1 and 3 (LP1), by moment distribution: symmetric, so the far end of span
    BC is taken with its symmetric stiffness 2EI/L and the end spans with 3EI/L (pinned at A):
    DF(BA) = 3 / (3 + 2) = 0.6, DF(BC) = 0.4. FEM at B of span 1 (propped, A pinned) = wL L²/8
    = 24 x 36 / 8 = 108; the joint releases -108: BA takes -64.8, so M_B,live = 108 - 64.8 =
    43.2 (= wL L²/20). With the dead load on all spans (24 x 36 / 10 = 86.4): M_B = 129.6;
    R_A = 48 x 6 / 2 - 129.6 / 6 = 122.4 kN, M+ = 122.4² / 96 = 156.06 kN·m: 12.9 % above the
    full live load's 138.24 - the moment the arrangement exists for.

    (a) live on spans 1 and 2 (LP3), three-moment equation: 4 M_B + M_C = (w1 + w2) L²/4,
    M_B + 4 M_C = (w2 + w3) L²/4 with w1 = w2 = 24, w3 = 0: M_B = 7 wL L²/60 = 100.8; with the
    dead load M_B = 187.2 kN·m, above the full live load's 172.8.
    """
    wd, wl = 1.2 * 20.0, 1.6 * 15.0
    patterns = {p.name: p for p in live_patterns(GRID)}
    mids = [SPAN * (k + 0.5) for k in range(3)]

    def live_on(name: str | None) -> list[float]:
        if name is None:
            return [wl, wl, wl]
        return [wl if patterns[name].loads(GRID, x, 2500.0) else 0.0 for x in mids]

    # The factored dead and live loads together (linear: the same as adding the cases, as the
    # combinations do).
    dead_support, _ = _three_span_moments([wd] * 3)
    results = {}
    for name in (None, "LP1", "LP2", "LP3", "LP4"):
        support, span1 = _three_span_moments([wd + w for w in live_on(name)])
        results[name] = (support, span1)
    assert dead_support[0] == pytest.approx(wd * 36 / 10, rel=1e-6)

    full_support, full_span = results[None]
    assert full_support[0] == pytest.approx(172.8, rel=1e-6)
    assert full_span == pytest.approx(138.24, rel=1e-6)

    alternate_support, alternate_span = results["LP1"]
    assert live_on("LP1") == [wl, 0.0, wl]
    assert alternate_support[0] == pytest.approx(129.6, rel=1e-6)
    assert alternate_span == pytest.approx(156.06, abs=0.01)

    adjacent_support, _ = results["LP3"]
    assert live_on("LP3") == [wl, wl, 0.0]
    assert adjacent_support[0] == pytest.approx(86.4 + 7 * 24 * 36 / 60, rel=1e-6)

    # The envelope over the full case and the arrangements governs both moments.
    assert max(r[1] for r in results.values()) == pytest.approx(156.06, abs=0.01)
    assert max(r[0][0] for r in results.values()) == pytest.approx(187.2, rel=1e-6)


#: Five floor levels at 3 m storeys [mm].
LEVELS = tuple(3000.0 * k for k in range(1, 6))
FLOORED = Grid(GRID.xs, GRID.ys, LEVELS)


def test_arrangements_by_floor() -> None:
    """With floor levels: the alternate arrangements are checkerboards over the floors (still
    two), the adjacent ones one per pair and floor ("each": 2 pairs x 5 floors) or per pair
    and floor parity ("alternate")."""
    patterns = live_patterns(FLOORED)
    assert len(patterns) == 2 + 2 * 5
    lp1 = patterns[0]
    assert lp1.checker and "checkerboard" in lp1.label
    # bays 1 + 3 on the 1st, 3rd, 5th floor; bay 2 on the 2nd and 4th
    assert [lp1.loads(FLOORED, 3000, 2500, z) for z in LEVELS] == [True, False] * 2 + [True]
    assert [lp1.loads(FLOORED, 9000, 2500, z) for z in LEVELS] == [False, True] * 2 + [False]
    assert lp1.loads(FLOORED, 19000, 100, 6000.0)  # cantilever on floor 2 follows bay 2
    adjacent = [p for p in patterns if not p.alternate]
    assert {(min(p.bays), next(iter(p.floors))) for p in adjacent} == {
        (k, f) for k in (0, 1) for f in range(5)
    }
    first = adjacent[0]
    assert first.loads(FLOORED, 3000, 2500, 3000.0) and not first.loads(FLOORED, 3000, 2500, 6000)
    assert "6.1.12.1 (a)" in first.clause
    with pytest.raises(ValueError, match="elevation"):
        first.loads(FLOORED, 3000, 2500)
    parity = [p for p in live_patterns(FLOORED, adjacent_floors="alternate") if not p.alternate]
    assert [sorted(p.floors) for p in parity] == [[0, 2, 4], [1, 3]] * 2


def _frame_moments(live: dict[int, set[int]], floor: int) -> tuple[float, float]:
    """A 2D frame, 3 bays of 6 m, 5 storeys of 3 m, fixed bases; beams 300 x 500, columns
    400 x 400, E = 25 GPa; 1.2D on every beam (24 kN/m) and 1.6L (24 kN/m) on the bays
    ``live[storey]`` (0-based bays, storeys 1-5). Returns span 1's largest sagging moment and
    its hogging moment at B [kN·m] on storey ``floor``."""
    import openseespy.opensees as ops

    span, storey, bays, storeys, e = 6.0, 3.0, 3, 5, 25e6
    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 3)

    def tag(i: int, k: int) -> int:
        return 100 * k + i + 1

    for k in range(storeys + 1):
        for i in range(bays + 1):
            ops.node(tag(i, k), i * span, k * storey)
            if k == 0:
                ops.fix(tag(i, k), 1, 1, 1)
    ops.geomTransf("Linear", 1)
    n, beams = 0, {}
    for k in range(1, storeys + 1):
        for i in range(bays + 1):
            n += 1
            ops.element("elasticBeamColumn", n, tag(i, k - 1), tag(i, k), 0.16, e, 0.4**4 / 12, 1)
        for i in range(bays):
            n += 1
            ops.element(
                "elasticBeamColumn", n, tag(i, k), tag(i + 1, k), 0.15, e, 0.3 * 0.5**3 / 12, 1
            )
            beams[(i, k)] = n
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    for (i, k), element in beams.items():
        ops.eleLoad(
            "-ele",
            element,
            "-type",
            "-beamUniform",
            -(24.0 + (24.0 if i in live.get(k, ()) else 0.0)),
        )
    ops.system("UmfPack")
    ops.numberer("RCM")
    ops.constraints("Plain")
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    force = ops.eleResponse(beams[(0, floor)], "localForce")
    q = 24.0 + (24.0 if 0 in live.get(floor, ()) else 0.0)
    x = force[1] / q
    sagging = -force[2] + force[1] * x - q * x * x / 2
    hogging = -force[5]
    ops.wipe()
    return sagging, hogging


def test_frame_floor_arrangements_bound_the_floor_only_case() -> None:
    """BNBC 6.1.12.1 (a) permits the live load on the floor considered only. The same bays on
    every floor at once give LOWER moments (columns in double curvature): on storey 3, span 1
    sags 83.87 kN·m (alternate bays on all floors) against 87.58 (that floor only), and B hogs
    142.74 (adjacent bays on all floors) against 152.22. The arrangements generated here bound
    the floor-only ones: the alternate checkerboard gives 90.75; the adjacent pair is per floor
    (the floor-only case itself)."""
    floor = 3
    patterns = live_patterns(FLOORED)
    mids = [SPAN * (k + 0.5) for k in range(3)]

    def live_of(pattern) -> dict[int, set[int]]:
        return {
            k + 1: {i for i, x in enumerate(mids) if pattern.loads(FLOORED, x, 2500.0, z)}
            for k, z in enumerate(LEVELS)
        }

    results = [_frame_moments(live_of(p), floor) for p in patterns]
    floor_only_sag, _ = _frame_moments({floor: {0, 2}}, floor)
    _, floor_only_hog = _frame_moments({floor: {0, 1}}, floor)
    all_sag, _ = _frame_moments({k: {0, 2} for k in range(1, 6)}, floor)
    _, all_hog = _frame_moments({k: {0, 1} for k in range(1, 6)}, floor)
    assert floor_only_sag == pytest.approx(87.58, abs=0.01)
    assert all_sag == pytest.approx(83.87, abs=0.01)
    assert floor_only_hog == pytest.approx(152.22, abs=0.01)
    assert all_hog == pytest.approx(142.74, abs=0.01)
    assert max(r[0] for r in results) == pytest.approx(90.75, abs=0.01)
    assert max(r[1] for r in results) == pytest.approx(floor_only_hog, rel=1e-9)

"""Column slenderness (saengine.design.slender) against hand calculations to BNBC 2020 Part 6
Sec 6.3.10 (ACI 318's moment magnification): the alignment chart, the nonsway magnifier with
Cm in single and double curvature, the minimum moment, the stability index Q of a sway storey
and δs, the limits, and the magnified moments in the strength check and the design mode.

The frames are synthetic: one column 500 × 500 mm, 6 m between floors, a 600 mm deep beam at
its top, the section forces of each combination written in by hand (no analysis is run).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.design.check import _column_checks, _Piece
from saengine.design.rc import InteractionSurface, section_of
from saengine.design.slender import (
    SlenderContext,
    SlenderOptions,
    cm_factor,
    critical_load,
    delta_ns,
    delta_s_q,
    delta_s_sum,
    effective_ei,
    k_nonsway,
    k_sway,
    minimum_moment,
    nonsway_limit,
    stability_index,
)
from saengine.library.bim import BuildingModel
from saengine.library.objects import Beam, Column, LinearReinforcement, RectangleProfile

FC = 28.0
EC = 4700 * math.sqrt(FC)  # MPa
B = H = 500.0
IG = B * H**3 / 12  # mm⁴
STATIONS = 11
REINFORCEMENT = LinearReinforcement.model_validate(
    {
        "material": "B420DWR",
        "cover": 40,
        "longitudinal": [{"position": "perimeter", "count": 8, "dia": 20}],
        "transverse": {"type": "tie", "dia": 10, "spacing": 150},
    }
)


# ───────────────────────────── the formulas ─────────────────────────────


def _sway_root(psi_a: float, psi_b: float) -> float:
    """k of the sway chart by bisection on its equation, written out independently."""

    def f(k: float) -> float:
        x = math.pi / k
        return (psi_a * psi_b * x * x - 36) / (6 * (psi_a + psi_b)) - x / math.tan(x)

    lo, hi = 1.0 + 1e-9, 50.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def test_k_from_psi_by_the_alignment_chart_equations() -> None:
    # ψA = ψB = 1 (beams as stiff as the columns): the charts of BNBC Figure 6.6.5 read
    # k ≈ 1.32 (sway) and k ≈ 0.77 (nonsway).
    k = k_sway(1.0, 1.0)
    x = math.pi / k
    assert (x * x - 36) / 12 == pytest.approx(x / math.tan(x), abs=1e-9)  # the equation holds
    assert k == pytest.approx(_sway_root(1.0, 1.0), rel=1e-9)
    assert k == pytest.approx(1.32, abs=5e-3)
    kn = k_nonsway(1.0, 1.0)
    x = math.pi / kn
    residual = 1 / 4 * x * x + (1 - x / math.tan(x)) + 2 * math.tan(x / 2) / x - 1
    assert residual == pytest.approx(0.0, abs=1e-8)
    assert kn == pytest.approx(0.7745, abs=5e-4)
    # The ends of the charts: fixed-fixed 0.5 (braced) and 1.0 (sway); pinned-pinned 1.0 braced.
    assert k_nonsway(0.0, 0.0) == pytest.approx(0.5, abs=2e-3)
    assert k_nonsway(math.inf, math.inf) == pytest.approx(1.0, abs=2e-3)
    assert k_sway(0.0, 0.0) == pytest.approx(1.0, abs=2e-3)
    # ψA = 1, ψB = 3: sway k ≈ 1.53 (chart), from the equation by hand.
    assert k_sway(1.0, 3.0) == pytest.approx(_sway_root(1.0, 3.0), rel=1e-9)


def test_nonsway_magnifier_single_and_double_curvature_by_hand() -> None:
    # 400 × 400, f'c 28, k = 1, lu = 6 m, Pu = 1000 kN, βdns = 0.6, M1 = 60, M2 = 100 kN·m.
    ig = 400**4 / 12
    ei = 0.4 * EC * ig / 1.6
    pc = math.pi**2 * ei / 6000**2
    assert effective_ei(EC, ig, 0.6) == pytest.approx(ei)
    assert critical_load(ei, 1.0, 6000) == pytest.approx(pc)
    single = 0.6 + 0.4 * 0.6  # Cm = 0.84 (M1/M2 = +0.6)
    double = 0.6 - 0.4 * 0.6  # Cm = 0.36 (M1/M2 = -0.6)
    assert cm_factor(0.6) == pytest.approx(single)
    assert cm_factor(-0.6) == pytest.approx(double)
    assert cm_factor(-0.6, transverse=True) == 1.0
    expected = single / (1 - 1e6 / (0.75 * pc))
    assert delta_ns(single, 1e6, pc) == pytest.approx(expected)
    assert expected > 1.25
    assert delta_ns(double, 1e6, pc) == 1.0  # 0.36 / 0.63 < 1: at least 1
    assert delta_ns(1.0, 0.8 * pc, pc) == math.inf  # Pu above 0.75 Pc
    # 34 - 12 M1/M2: 26.8 in single curvature, 41.2 capped at 40 in double.
    assert nonsway_limit(0.6) == pytest.approx(26.8)
    assert nonsway_limit(-0.6) == 40.0
    # The bars' form: (0.2 Ec Ig + Es Ise) / (1 + β).
    assert effective_ei(EC, ig, 0.6, 200_000, 1e8) == pytest.approx(
        (0.2 * EC * ig + 200_000 * 1e8) / 1.6
    )
    assert minimum_moment(1e6, 400) == pytest.approx(1e6 * (15 + 12))


def test_stability_index_and_sway_magnifiers_by_hand() -> None:
    q = 2e6 * 0.02 / (1e5 * 6)
    assert stability_index(2e6, 0.02, 1e5, 6) == pytest.approx(q)
    assert delta_s_q(q) == pytest.approx(1 / (1 - q))
    assert delta_s_q(0.0) == 1.0
    assert delta_s_sum(1e6, 1e7) == pytest.approx(1 / (1 - 1e6 / 7.5e6))
    assert delta_s_sum(8e6, 1e7) == math.inf


# ───────────────────────────── a synthetic frame ─────────────────────────────


def _frame(height: float = 6.0, beam_depth: float = 600.0):
    """Column C1 (nodes 1 at the fixed base, 2 at the top) and beam B1 along X (2 to 3),
    as the analysis model and the building model have them. The beam's Iy is twice the
    column's, both 6 m long: ψ at the top = (0.70 Ic / 6) / (0.35 · 2 Ic / 6) = 1."""
    ic = (B * 1e-3) * (H * 1e-3) ** 3 / 12  # m⁴
    project = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [0, 0, height], "restraint": [False] * 6},
            {"id": 3, "coords": [6.0, 0, height], "restraint": [True] * 6},
        ],
        "sections": [
            {"id": 1, "E": EC * 1e6, "A": 0.25, "Iy": ic, "Iz": ic},
            {"id": 2, "E": EC * 1e6, "A": 0.18, "Iy": 2 * ic, "Iz": ic},
        ],
        "elements": [
            {"id": 1, "name": "C1", "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1},
            {"id": 2, "name": "B1", "type": "ElasticBeamColumn", "nodes": [2, 3], "section_id": 2},
        ],
    }
    building = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": height * 1e3},
            ],
            "elements": [
                {
                    "id": "C1",
                    "type": "COL",
                    "kind": "column",
                    "position": [0, 0],
                    "bottom": 0,
                    "top": height * 1e3,
                },
                {
                    "id": "B1",
                    "type": "BM",
                    "kind": "beam",
                    "start": [0, 0],
                    "end": [6000, 0],
                    "elevation": height * 1e3,
                },
            ],
        }
    )
    types = {
        "COL": Column.model_validate(
            {
                "id": "COL",
                "name": "COL",
                "material": "C27.6",
                "profile": {"shape": "rectangle", "xDim": B, "yDim": H},
            }
        ),
        "BM": Beam.model_validate(
            {
                "id": "BM",
                "name": "BM",
                "material": "C27.6",
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": beam_depth},
            }
        ),
    }
    return project, building, types


def _rows(n: float, my_bottom: float, my_top: float, vz: float = 0.0) -> np.ndarray:
    """Section forces at the stations [N, N·m]: axial N (tension +), shear Vz (global X for
    this column, local z = X), My (bending for a deflection along X) linear bottom to top."""
    rows = np.zeros((STATIONS, 6))
    rows[:, 0] = n
    rows[:, 2] = vz
    rows[:, 4] = np.linspace(my_bottom, my_top, STATIONS)
    return rows


def _piece(height: float, total, sway, sustained) -> _Piece:
    axes = np.array([[0, 0, 1.0], [0, -1.0, 0], [1.0, 0, 0]])  # local x up, y = -Y, z = X
    return _Piece(
        "C1",
        1,
        height,
        depth_along_z=False,
        axes=axes,
        forces=total,
        start=np.array([0, 0, 0.0]),
        end=np.array([0, 0, height]),
        sway=sway,
        sustained=sustained,
    )


def _context(piece, combinations, disp, height=6.0, options=None, mats=None):
    project, building, types = _frame(height)
    beam = _Piece(
        "B1",
        2,
        6.0,
        depth_along_z=True,
        axes=np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]),
        forces=[np.zeros((STATIONS, 6)) for _ in combinations],
        start=np.array([0, 0, height]),
        end=np.array([6.0, 0, height]),
        sway=[np.zeros((STATIONS, 6)) for _ in combinations],
        sustained=[np.zeros((STATIONS, 6)) for _ in combinations],
    )
    pieces = {"C1": [piece], "B1": [beam]}
    return SlenderContext(project, building, types, mats or {}, pieces, combinations, disp, options)


SECTION = section_of(RectangleProfile(xDim=B, yDim=H), REINFORCEMENT, FC, 420)


def _about_y(result):
    return next(a for a in result.axes if a.axis == "y")


def test_braced_column_end_moments_magnified_by_hand() -> None:
    # Gravity only (no storey sways): nonsway, k = 1. Pu = 3000 kN, 1500 kN of it sustained
    # (βdns = 0.5), M1 = 60, M2 = 100 kN·m in single curvature.
    total = [_rows(-3e6, 60e3, 100e3)]
    piece = _piece(6.0, total, [np.zeros((STATIONS, 6))], [_rows(-1.5e6, 0, 0)])
    context = _context(piece, ["1.4D"], [{}])
    result = context.column("C1", SECTION, [piece], False, EC)
    axis = _about_y(result)
    s = axis.check["slenderness"]
    lu = 6000 - 600  # the beam along X takes its depth off (BNBC 6.3.10.1.1)
    r = 0.3 * 500
    assert s["lu"] == pytest.approx(lu) and s["r"] == pytest.approx(r) and s["k"] == 1.0
    assert s["sway"] is None and s["klu_r"] == pytest.approx(lu / r, rel=1e-3)  # 36.0
    assert s["limit"] == pytest.approx(34 - 12 * 0.6)  # 26.8 < 36: not neglected
    ei = 0.4 * EC * IG / (1 + 0.5)
    pc = math.pi**2 * ei / lu**2
    cm = 0.6 + 0.4 * 0.6
    dns = cm / (1 - 3e6 / (0.75 * pc))  # 1.28
    assert dns > 1.2
    assert s["Pc"] == pytest.approx(pc / 1e3, rel=1e-3)
    assert s["Cm"] == pytest.approx(cm) and s["deltaNs"] == pytest.approx(dns, rel=1e-3)
    assert s["M2magnified"] == pytest.approx(dns * 100, rel=1e-3)
    assert axis.check["name"] == f"Slenderness about y (nonsway, δns = {dns:.2f})"
    assert not axis.check["flag"] and axis.check["ok"]
    assert axis.mc[0] == pytest.approx(dns * 100e6, rel=1e-6)
    # The strength check takes the magnified moment: (Pu, |Mux|, Mc).
    assert any(
        p[0] == pytest.approx(3e6) and p[2] == pytest.approx(dns * 100e6, rel=1e-6)
        for p in result.points
    )

    # The same column in double curvature (M1/M2 = -0.6): 34 + 7.2 capped at 40 > 36, neglected.
    total = [_rows(-3e6, 60e3, -100e3)]
    piece = _piece(6.0, total, [np.zeros((STATIONS, 6))], total)
    axis = _about_y(_context(piece, ["1.4D"], [{}]).column("C1", SECTION, [piece], False, EC))
    assert axis.check["name"] == "Slenderness about y (nonsway, neglected)"
    assert axis.check["flag"] and axis.check["slenderness"]["limit"] == 40.0
    assert axis.mc[0] == pytest.approx(100e6)


def test_minimum_moment_governs_with_cm_one() -> None:
    # Pu = 1000 kN, end moments 5 kN·m each (single curvature): M2,min = Pu (15 + 0.03 h)
    # = 1e6 × 30 = 30 kN·m governs, with Cm = 1 (BNBC 6.3.10.6.5).
    total = [_rows(-1e6, 5e3, 5e3)]
    piece = _piece(6.0, total, [np.zeros((STATIONS, 6))], total)
    axis = _about_y(_context(piece, ["1.4D"], [{}]).column("C1", SECTION, [piece], False, EC))
    lu = 5400
    pc = math.pi**2 * (0.4 * EC * IG / 2) / lu**2
    dns = 1 / (1 - 1e6 / (0.75 * pc))
    s = axis.check["slenderness"]
    assert s["M2min"] == pytest.approx(30.0)
    assert s["Cm"] == 1.0 and s["deltaNs"] == pytest.approx(dns, rel=1e-3)
    assert s["M2magnified"] == pytest.approx(dns * 30, rel=1e-3)
    assert "M2,min governs" in axis.check["note"]
    # Without the minimum (the point with M2,min about the other axis) it is δns M2, Cm = 1
    # from M1/M2 = +1 as well.
    assert axis.mc_no_min[0] == pytest.approx(dns * 5e6, rel=1e-6)


def _sway_case(delta: float, options=None):
    """1.2D + 1.0EX: Pu = 2000 kN (1200 kN of it dead), Vus = 100 kN along X, the floor
    displaced ``delta`` m along X by EX; end moments Mns = 20 / -10, Ms = 200 / -150 kN·m."""
    sway = [_rows(0.0, 200e3, -150e3, vz=1e5)]
    nonsway = _rows(-2e6, 20e3, -10e3)
    total = [nonsway + sway[0]]
    sustained = [_rows(-1.2e6, 0.0, 0.0)]
    piece = _piece(6.0, total, sway, sustained)
    disp = [{2: np.array([delta, 0, 0, 0, 0, 0]), 3: np.array([delta, 0, 0, 0, 0, 0])}]
    options = options or SlenderOptions(drift_factor=1.0)
    context = _context(piece, ["1.2D + 1.0EX"], disp, options=options)
    return context, piece


def test_sway_storey_q_delta_s_and_magnified_end_moments_by_hand() -> None:
    context, piece = _sway_case(0.02)
    storey = next(s for s in context.storeys if s.direction == "X")
    q = 2e6 * 0.02 / (1e5 * 6.0)  # Q = ΣPu Δo / (Vus lc) = 0.0667 > 0.05: sway
    assert storey.sum_pu[0] == pytest.approx(2e6) and storey.vus[0] == pytest.approx(1e5)
    assert storey.q[0] == pytest.approx(q) and storey.sway is True
    ds = 1 / (1 - q)
    result = context.column("C1", SECTION, [piece], False, EC)
    axis = _about_y(result)
    s = axis.check["slenderness"]
    k = _sway_root(1.0, 1.0)  # ψ = 1 at the fixed base (default) and 1 at the beam
    assert s["psi"] == [pytest.approx(1.0), pytest.approx(1.0, rel=1e-6)]
    assert s["k"] == pytest.approx(k, abs=1e-3) and s["sway"] is True
    assert s["klu_r"] == pytest.approx(k * 5400 / 150, rel=1e-3)  # 47.4 > 22
    assert s["deltaS"] == pytest.approx(ds, rel=1e-3) and s["Q"] == pytest.approx(q, rel=1e-3)
    m_bottom = 20 + ds * 200  # M2 = M2ns + δs M2s = 234.3 kN·m (BNBC Eq. 6.6.26)
    m_top = -10 - ds * 150
    # Along the length: double curvature, Cm = 0.6 + 0.4 (-170.7 / 234.3) < δns floor: 1.
    assert s["Cm"] == pytest.approx(0.6 + 0.4 * (m_top / m_bottom), abs=1e-3)
    assert s["deltaNs"] == 1.0
    assert s["M2magnified"] == pytest.approx(m_bottom, rel=1e-3)
    assert s["M2"] == pytest.approx(220.0)
    assert axis.check["name"] == f"Slenderness about y (sway, δs = {ds:.2f}, δns = 1.00)"
    assert axis.check["ok"] and not axis.check["secondOrderRequired"]
    # The station at the base carries the sway-magnified moment into the strength check.
    bottom = [p for p in result.points if p[4] == "C1 at 0.00 L"]
    assert bottom[0][2] == pytest.approx(m_bottom * 1e6, rel=1e-6)
    # And the column check takes them (the strength check's points are the slender ones).
    surface = InteractionSurface(SECTION, coarse=True)
    checks = _column_checks(SECTION, surface, [piece], ["1.2D + 1.0EX"], False, result)
    assert [c["name"] for c in checks][:2] == [
        "Axial compression",
        "Axial force and biaxial bending",
    ]
    assert sum(c["name"].startswith("Slenderness about") for c in checks) == 2


def test_delta_s_above_1_5_needs_a_second_order_analysis() -> None:
    context, piece = _sway_case(0.2)  # Q = 0.667, δs = 3.0
    axis = _about_y(context.column("C1", SECTION, [piece], False, EC))
    assert axis.check["slenderness"]["deltaS"] == pytest.approx(3.0, rel=1e-3)
    assert not axis.check["ok"] and axis.check["secondOrderRequired"]
    assert "second-order analysis required" in axis.check["note"]
    # With a P-Δ analysis the end moments are the analysis's: no δs, nothing required.
    context, piece = _sway_case(0.2, SlenderOptions(drift_factor=1.0, second_order="pDelta"))
    axis = _about_y(context.column("C1", SECTION, [piece], False, EC))
    assert axis.check["slenderness"]["deltaS"] is None
    assert "P-Δ analysis" in axis.check["name"] and axis.check["ok"]
    assert not axis.check["secondOrderRequired"]
    assert axis.mc[0] == pytest.approx(220e6)  # first order: Mns + Ms


def test_sum_pc_magnifier_by_hand() -> None:
    from saengine.library import default_material_library

    mats = {m.id: m for m in default_material_library().materials}
    from saengine.design.slender import concrete_modulus

    ec = concrete_modulus(mats["C27.6"])
    context, piece = _sway_case(0.2, SlenderOptions(drift_factor=1.0, sway_magnifier="sumPc"))
    context = _context(
        piece,
        ["1.2D + 1.0EX"],
        [{2: np.array([0.2, 0, 0, 0, 0, 0]), 3: np.array([0.2, 0, 0, 0, 0, 0])}],
        options=SlenderOptions(drift_factor=1.0, sway_magnifier="sumPc"),
        mats=mats,
    )
    k = _sway_root(1.0, 1.0)
    # EI of BNBC 6.3.10.6.1 as 6.3.10.7.4 says: 0.4 Ec Ig / (1 + βdns), βdns = 1200 / 2000.
    beta = 1.2e6 / 2e6
    pc = math.pi**2 * 0.4 * ec * IG / (1 + beta) / (k * 5400) ** 2
    ds = 1 / (1 - 2e6 / (0.75 * pc))
    storey = next(s for s in context.storeys if s.direction == "X")
    assert storey.sum_pc == [pytest.approx(pc, rel=1e-3)]
    axis = _about_y(context.column("C1", SECTION, [piece], False, EC))
    assert axis.check["slenderness"]["deltaS"] == pytest.approx(ds, rel=1e-3)
    assert not axis.check["secondOrderRequired"]  # the 1.5 limit is the Q method's


def test_stocky_column_slenderness_neglected() -> None:
    # 2 m storey: lu = 2000 - 600 = 1400 mm, k lu / r = 9.3 < 22: neglected even if it sways.
    total = [_rows(-1e6, 60e3, 100e3)]
    piece = _piece(2.0, total, [np.zeros((STATIONS, 6))], total)
    context = _context(piece, ["1.4D"], [{}], height=2.0)
    result = context.column("C1", SECTION, [piece], False, EC)
    for axis in result.axes:
        assert axis.check["flag"] and axis.check["ok"]
        assert axis.check["name"].endswith("(nonsway, neglected)")
        assert axis.check["demand"] == pytest.approx(1400 / 150, rel=1e-3)
    assert _about_y(result).mc[0] == pytest.approx(100e6)


def test_very_slender_column_fails_above_100() -> None:
    # A 20 m column with no beam: k lu / r = 20000 / 150 = 133 > 100 (ACI 318-19 6.2.6).
    total = [_rows(-1e5, 10e3, 10e3)]
    piece = _piece(20.0, total, [np.zeros((STATIONS, 6))], total)
    context = _context(piece, ["1.4D"], [{}], height=20.0)
    context.model.depth.clear()  # no beam depth to take off
    axis = _about_y(context.column("C1", SECTION, [piece], False, EC))
    assert not axis.check["ok"] and axis.check["secondOrderRequired"]
    assert "6.2.6" in axis.check["note"]


def test_design_mode_requires_steel_for_the_magnified_moments() -> None:
    from saengine.design.required import ColumnSearch, Options, column_points

    total = [_rows(-3e6, 60e3, 100e3)]
    piece = _piece(6.0, total, [np.zeros((STATIONS, 6))], [_rows(-1.5e6, 0, 0)])
    result = _context(piece, ["1.4D"], [{}]).column("C1", SECTION, [piece], False, EC)
    member = {"pieces": [piece], "turned": False, "points": result.points}
    magnified = column_points(member, ["1.4D"])
    first_order = column_points({**member, "points": None}, ["1.4D"])
    assert max(p[2] for p in magnified) > max(p[2] for p in first_order)
    column = Column.model_validate(
        {
            "id": "COL",
            "name": "COL",
            "material": "C27.6",
            "profile": {"shape": "rectangle", "xDim": B, "yDim": H},
            "reinforcement": REINFORCEMENT.model_dump(mode="json"),
        }
    )
    search = ColumnSearch(column, FC, 420, 200_000, None, Options())
    need = search.required_area(search.smallest(magnified), magnified)
    plain = search.required_area(search.smallest(first_order), first_order)
    assert need is not None and plain is not None and need >= plain


def test_neglected_slenderness_adds_no_points_along_the_length() -> None:
    # Slenderness neglected about both axes: the strength check takes the stations alone
    # (no point pairing the largest Pu with both axes' largest moments).
    total = [_rows(-1e6, 60e3, 100e3)]
    piece = _piece(2.0, total, [np.zeros((STATIONS, 6))], total)
    result = _context(piece, ["1.4D"], [{}], height=2.0).column("C1", SECTION, [piece], False, EC)
    assert len(result.points) == STATIONS
    assert not any("along the length" in p[4] for p in result.points)


def test_options_from_the_project_settings() -> None:
    from types import SimpleNamespace

    from saengine.design.slender import options_from_settings

    assert options_from_settings(SimpleNamespace(analysis=SimpleNamespace())) == SlenderOptions()
    settings = SimpleNamespace(
        analysis=SimpleNamespace(
            slenderness={"effectiveLength": "chart", "swayMagnifier": "sumPc", "driftFactor": 1},
            secondOrder="pDelta",
        )
    )
    options = options_from_settings(settings)
    assert options.effective_length == "chart" and options.sway_magnifier == "sumPc"
    assert options.second_order == "pDelta" and options.drift_factor == 1.0
    assert options.stiffness == "0.4EcIg"  # the default kept
    assert options.model_cracked is None  # found from the analysed model
    # The section stiffness settings are not read: they may have changed since the analysis
    # (the cracked drift and sections are read from the model, see test_design_slender_frames).
    for cracked_for in ("lateral", "all"):
        found = options_from_settings(
            SimpleNamespace(analysis=SimpleNamespace(stiffness="aci", crackedFor=cracked_for))
        )
        assert found.drift_factor is None and found.model_cracked is None

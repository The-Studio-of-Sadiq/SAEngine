"""Post-tensioned slabs (saengine.design.prestress): tendon forces, load balancing, hyperstatic
moments and the prestressed concrete checks, pinned through the default pack (BNBC 2020 Part 6
Chapter 9)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.design import prestress
from saengine.library.bim import SlabTendon
from saengine.library.templates import TEMPLATES

#: Two 8 m spans, CGS 125 mm at the ends, 40 mm low, 210 mm over the middle support.
POINTS = [(0.0, 125.0), (3600.0, 40.0), (8000.0, 210.0), (12400.0, 40.0), (16000.0, 125.0)]


def _tendon(**changes) -> SlabTendon:
    return SlabTendon(**{**TEMPLATES["SlabTendon"], **changes})


def test_parabola_has_its_vertex_at_the_low_point():
    piece = prestress.Segment(0, 4000, 200, 50)
    assert piece.height(4000) == 50
    assert piece.slope(4000) == 0
    assert piece.height(0) == 200
    assert piece.curvature == pytest.approx(2 * 150 / 4000**2)


def test_supports_are_the_ends_and_the_interior_high_points():
    assert prestress.supports(POINTS) == [0.0, 8000.0, 16000.0]


def test_balancing_loads_are_in_equilibrium():
    model, pieces = prestress.strip_model(POINTS)
    distributed, nodal, _ = prestress.balancing_loads(pieces, model, 1e6, 250)
    assert distributed @ np.diff(model.stations) + nodal.sum() == pytest.approx(0, abs=1e-6)


def test_continuous_beam_moment_over_the_middle_support():
    """Two equal spans under w: -w l² / 8 over the middle support."""
    model, _ = prestress.strip_model(POINTS)
    moments = model.moments(np.full(len(model.stations) - 1, -10.0))
    middle = int(np.argmin(np.abs(model.stations - 8000)))
    assert moments[middle] == pytest.approx(-10 * 8000**2 / 8, rel=1e-6)


def test_hyperstatic_moment_is_linear_between_supports():
    """M2 = M_bal + P e is zero at the end supports and linear between supports (BNBC Sec
    9.10.3)."""
    model, pieces = prestress.strip_model(POINTS)
    force = 1e6
    total = model.moments(*prestress.balancing_loads(pieces, model, force, 250))
    heights = np.array(
        [next(p for p in pieces if p.x0 <= x <= p.x1).height(x) for x in model.stations]
    )
    m2 = total + force * (125 - heights)
    assert m2[0] == pytest.approx(0, abs=1e-3)
    at = [float(np.interp(x, model.stations, m2)) for x in (0, 4000, 8000)]
    assert at[1] == pytest.approx((at[0] + at[2]) / 2, rel=1e-6)


def test_friction_force():
    """BNBC Sec 9.6.8, Eq 6.9.2: P = Pj e^-(K x + μ α) on a straight tendon (α = 0)."""
    pieces = prestress.segments([(0, 125), (10000, 125)])
    stations = np.array([0.0, 5000.0, 10000.0])
    force = prestress.friction_forces(1e6, pieces, stations, 0.0033, 0.07, "start")
    assert force[-1] == pytest.approx(1e6 * math.exp(-0.0033 * 10), rel=1e-9)


def test_anchor_set_balances_the_draw_in():
    """The area of the force lost to the draw-in is Δ Ep Aps."""
    stations = np.linspace(0, 20000, 401)
    force = 1e6 * (1 - 1e-5 * stations)  # 10 N/mm of friction
    after, length = prestress.anchor_set(force, stations, 6, 195_000, 500, "start")
    lost = np.trapezoid(force - after, stations)
    assert lost == pytest.approx(6 * 195_000 * 500, rel=2e-3)
    # Linear friction p: x_set = √(Δ Ep Aps / p).
    assert length == pytest.approx(math.sqrt(6 * 195_000 * 500 / 10), rel=1e-2)


def test_unbonded_stress_at_strength():
    """BNBC Sec 9.8.2, Eqs 6.9.6-6.9.7: fse + 70 + f'c / (100 ρp) <= fpy, fse + 420; above
    span/depth 35, / (300 ρp) <= fse + 210."""
    fps = prestress.stress_at_strength(1100, 1860, 1674, 35, 0.002, 30, False)
    assert fps == pytest.approx(1100 + 70 + 35 / 0.2)
    slender = prestress.stress_at_strength(1100, 1860, 1674, 35, 0.002, 40, False)
    assert slender == pytest.approx(1100 + 70 + 35 / 0.6)
    capped = prestress.stress_at_strength(1100, 1860, 1674, 35, 0.0002, 30, False)
    assert capped == pytest.approx(1100 + 420)


def test_bonded_stress_at_strength():
    """BNBC Sec 9.8.2, Eq 6.9.5, γp = 0.28 for fpy / fpu >= 0.90: fpu (1 - γp / β1 ρp fpu /
    f'c)."""
    fps = prestress.stress_at_strength(1100, 1860, 1674, 28, 0.003, 30, True)
    assert fps == pytest.approx(1860 * (1 - 0.28 / 0.85 * 0.003 * 1860 / 28))


def test_punching_with_prestress(monkeypatch):
    """The 'precompression' method (a pack's choice): βp √f'c + 0.3 fpc, βp <= 0.29; fpc 0.9-3.5
    MPa. The default pack (BNBC Sec 9.12.2) sends punching to Chapter 6: no prestress term."""
    assert prestress.limits().punchingMethod == "reinforced"
    assert prestress.punching_vc(35, 200, 4000, 40, 1.5) is None
    other = prestress.limits().model_copy(update={"punchingMethod": "precompression"})
    monkeypatch.setattr(prestress, "limits", lambda: other)
    root = min(math.sqrt(35), 5.8)  # √f'c at most 5.8 MPa
    vc = prestress.punching_vc(35, 200, 4000, 40, 1.5)
    assert vc == pytest.approx(0.29 * root + 0.45)
    small = prestress.punching_vc(35, 100, 6000, 40, 1.5)
    assert small == pytest.approx(0.083 * (1.5 + 40 * 100 / 6000) * root + 0.45)
    assert prestress.punching_vc(35, 200, 4000, 40, 0.5) is None


def test_tendon_design_checks_are_named_and_cited():
    design = prestress.tendon_design(
        _tendon(transferStrength=25),
        250,
        35,
        420,
        prestress.StripLoads(0.006, 0.0015, 0.003),
        400,
        600,
        215,
        215,
        True,
    )
    names = {c["name"] for c in design.checks}
    assert {
        "PT PT1: stress at the anchors after transfer",
        "PT PT1: transfer compression",
        "PT PT1: service tension",
        "PT PT1: flexural strength",
        "PT PT1: average precompression",
    } <= names
    assert design.precompression == pytest.approx(
        float(np.mean(design.forces.effective)) / (4000 * 250)
    )


# ─────────────────────────────────── B30: the rest of Chapter 9 ───────────────────────────────────


def _design(tendon: SlabTendon, two_way: bool = True, **kw):
    return prestress.tendon_design(
        tendon,
        250,
        35,
        420,
        prestress.StripLoads(0.006, 0.0015, 0.003),
        kw.pop("bars_bottom", 400),
        kw.pop("bars_top", 600),
        215,
        215,
        two_way,
        **kw,
    )


def test_pack_values_of_chapter_9():
    """BNBC Sec 9.5.1, 9.5.4 (b), 9.4.3, 9.8.2, 9.9.3, 9.9.4, 9.12.6-9.12.7, 9.13-9.14, 9.11
    (part 1 pp. 1139-1159)."""
    lim = prestress.limits()
    assert (lim.transferSteelFpy, lim.transferSteelFpu) == (0.82, 0.74)
    assert (lim.transferCompression, lim.transferCompressionEnds) == (0.60, 0.70)
    assert (lim.transferTension, lim.transferTensionEnds) == (0.25, 0.50)
    assert (lim.tensionClassU, lim.tensionClassT, lim.tensionTwoWay) == (0.62, 1.0, 0.50)
    assert lim.rupture == 0.62 and lim.fpsMinFse == 0.5 and lim.bondedFyMax == 420
    assert (lim.cracking.factor, lim.cracking.waiver) == (1.2, 2.0)
    assert (lim.bondedTop.minBars, lim.bondedTop.maxSpacing, lim.bondedTop.beyondFace) == (
        4,
        300,
        1.5,
    )
    assert lim.relaxation.stressRatios == [0.5, 0.6, 0.7, 0.8]
    assert lim.relaxation.losses == [0, 35, 70, 90]
    assert (lim.integrity.strands, lim.integrity.bottomFactor, lim.integrity.bottomMin) == (
        2,
        1.5,
        2.1,
    )
    a = lim.anchorage
    assert (a.loadFactor, a.phi, a.spalling) == (1.2, 0.85, 0.02)
    assert (a.transferMulti, a.transferSingle) == (28, 17)
    assert (a.edgeBars, a.edgeBarDia, a.edgeBarAhead, a.edgeBarExtension) == (2, 12, 0.5, 150)
    assert (a.groupSpacing, a.groupMin, a.hairpinDia, a.hairpinFrom, a.hairpinTo) == (
        300,
        6,
        10,
        0.375,
        0.5,
    )
    c = lim.compression
    assert (c.threshold, c.tieMinDia, c.tieSpacingDiameters) == (1.6, 10, 48)
    assert (c.spiralCoefficient, c.spiralFytMax) == (0.45, 700)


def test_relaxation_table_6_9_2():
    """BNBC Table 6.9.2: 0, 35, 70, 90 MPa at 0.5, 0.6, 0.7, 0.8 fpu, linear between."""
    assert prestress.relaxation_loss(0.4 * 1860, 1860) == 0
    assert prestress.relaxation_loss(0.6 * 1860, 1860) == pytest.approx(35)
    assert prestress.relaxation_loss(0.65 * 1860, 1860) == pytest.approx(52.5)
    assert prestress.relaxation_loss(0.85 * 1860, 1860) == pytest.approx(90)


def test_creep_coefficient_table_6_9_3_post_tensioned():
    """BNBC Table 6.9.3: 2.2, 1.6, 1.1 at 7, 28 and 365 days; 80 % for post-tensioning
    (Sec 9.6.6 (c))."""
    assert prestress.creep_coefficient(7) == pytest.approx(0.8 * 2.2)
    assert prestress.creep_coefficient(28) == pytest.approx(0.8 * 1.6)
    assert prestress.creep_coefficient(365) == pytest.approx(0.8 * 1.1)
    assert prestress.creep_coefficient(28, post_tensioned=False) == pytest.approx(1.6)
    # Between the printed ages on log(age) (SAEngine practice).
    mid = 2.2 + (1.6 - 2.2) * math.log(14 / 7) / math.log(28 / 7)
    assert prestress.creep_coefficient(14, post_tensioned=False) == pytest.approx(mid)


def test_shrinkage_strain_sec_9_6_7():
    """BNBC Sec 9.6.7 (a): 0.0003 pretensioned; 0.0002 / log10(t + 2) post-tensioned."""
    assert prestress.shrinkage_strain(7, post_tensioned=False) == pytest.approx(0.0003)
    assert prestress.shrinkage_strain(7) == pytest.approx(0.0002 / math.log10(9))
    assert prestress.shrinkage_strain(28) == pytest.approx(0.0002 / math.log10(30))


def test_long_term_losses_lump_sum():
    """Creep Ep φ fcs / Eci (Sec 9.6.6 (e)), shrinkage Ep εsh (9.6.7 (c)), relaxation (9.6.5)."""
    aps, ep, eci = 1000.0, 195_000.0, 25_000.0
    found = prestress.long_term_losses(ep, 1860, aps, 0.7 * 1860 * aps, lambda p: 2.0, eci, 7)
    assert found.creep == pytest.approx(ep * 0.8 * 2.2 * 2.0 / eci)
    assert found.shrinkage == pytest.approx(ep * 0.0002 / math.log10(9))
    assert found.relaxation == pytest.approx(70)
    assert found.total == pytest.approx(found.creep + found.shrinkage + found.relaxation)


def test_long_term_loss_is_worked_out_unless_entered():
    computed = _design(_tendon(longTermLoss=None))
    assert computed.losses is not None
    assert computed.forces.long_term == pytest.approx(computed.losses.total)
    entered = _design(_tendon(longTermLoss=150))
    assert entered.losses is None and entered.forces.long_term == 150


def test_gamma_p_by_fpy_over_fpu():
    """BNBC Sec 9.8.2 (a): γp 0.55 (fpy/fpu >= 0.80), 0.40 (>= 0.85), 0.28 (>= 0.90)."""
    assert prestress.gamma_p(0.90 * 1860, 1860) == 0.28
    assert prestress.gamma_p(0.86 * 1860, 1860) == 0.40
    assert prestress.gamma_p(0.80 * 1860, 1860) == 0.55
    assert prestress.gamma_p(0.70 * 1860, 1860) == 0.55


def test_member_class_sec_9_4_3():
    """Class U up to 0.62 √f'c, T up to 1.0 √f'c, C above."""
    root = math.sqrt(35)
    assert prestress.member_class(0.6 * root, 35) == "U"
    assert prestress.member_class(0.9 * root, 35) == "T"
    assert prestress.member_class(1.1 * root, 35) == "C"


def test_tendon_stress_after_transfer_is_checked():
    """BNBC Sec 9.5.4 (b): 0.82 fpy, at most 0.74 fpu."""
    design = _design(_tendon(transferStrength=25))
    check = next(c for c in design.checks if c["name"].endswith("tendon stress after transfer"))
    assert check["capacity"] == pytest.approx(min(0.82 * 0.9 * 1860, 0.74 * 1860), abs=0.01)


def test_transfer_limits_at_the_ends_of_a_simply_supported_strip():
    """BNBC Sec 9.5.1 (b)-(c): 0.70 f'ci and 0.50 √f'ci at the ends of simply supported
    members."""
    simple = _tendon(
        transferStrength=25,
        x2=8000,
        profile=[{"at": 0, "height": 125}, {"at": 4000, "height": 40}, {"at": 8000, "height": 125}],
    )
    design = _design(simple)
    check = next(c for c in design.checks if c["name"].endswith("transfer compression"))
    assert "0.7 f'ci" in check["note"]


def test_transfer_tension_above_the_limit_needs_bonded_bars():
    """BNBC Sec 9.5.1 (c): bonded bars for the whole tension of the uncracked section."""
    # A deep drape and a light slab: tension at the top at transfer.
    tendon = _tendon(
        transferStrength=20,
        count=16,
        profile=[
            {"at": 0, "height": 125},
            {"at": 3600, "height": 30},
            {"at": 8000, "height": 220},
            {"at": 12400, "height": 30},
            {"at": 16000, "height": 125},
        ],
    )
    design = _design(tendon)
    names = [c["name"] for c in design.checks]
    assert any(n.endswith("bonded bars for the tension at transfer") for n in names) or any(
        n.endswith("transfer tension") for n in names
    )


def test_one_way_strip_reports_its_class_and_class_c_spacing():
    tendon = _tendon(count=2, longTermLoss=200)
    design = _design(tendon, two_way=False, spacing_bottom=300, cover=20)
    assert design.member_class in ("U", "T", "C")
    if design.member_class == "C":
        assert any("Class C" in c["name"] for c in design.checks)


def test_deflection_checks_against_table_6_6_2():
    design = _design(_tendon())
    live = next(c for c in design.checks if c["name"].endswith("live-load deflection"))
    assert "l/360" in live["note"]
    after = next(c for c in design.checks if c["name"].endswith("deflection after attachment"))
    assert "l/480" in after["note"]
    assert not any(
        c["name"].endswith("deflection after attachment")
        for c in _design(_tendon(), deflection="off").checks
    )


def test_strip_deflection_of_a_simple_span():
    """5 w L⁴ / 384 EI mid-span of a simple span (EI = 1)."""
    model, _ = prestress.strip_model([(0.0, 125.0), (4000.0, 40.0), (8000.0, 125.0)])
    deflection = model.deflections(np.full(len(model.stations) - 1, -1.0))
    middle = int(np.argmin(np.abs(model.stations - 4000)))
    assert deflection[middle] == pytest.approx(-5 * 8000**4 / 384, rel=1e-6)


def test_bonded_top_bars_near_the_columns():
    """BNBC Sec 9.9.4.4: at least four bars within 1.5 h of the column faces, <= 300 mm."""
    design = _design(_tendon(), spacing_top=200, column_width=500)
    count = next(c for c in design.checks if c["name"].endswith("bonded top bars near the columns"))
    assert count["capacity"] == int((500 + 2 * 1.5 * 250) // 200) + 1
    spacing = next(c for c in design.checks if c["name"].endswith("spacing of the bonded top bars"))
    assert spacing["capacity"] == 300


def test_anchorage_zone_of_monostrand_slab_tendons():
    """BNBC Sec 9.14.2: two 12 mm bars within h/2 ahead, 150 mm beyond; groups of six or more
    at <= 300 mm: n + 1 No. 10 hairpins 3h/8 to h/2 ahead; Ppu = 1.2 Pj (9.13.2.2)."""
    tendon = _tendon(count=8)
    found = prestress.anchorage_zone(tendon, 250, 420, 1e5)
    assert found.ppu == pytest.approx(1.2e5)
    assert found.edge_bars == (2, 12, 125, 150)
    assert found.hairpins == (9, 10, 93.75, 125)
    few = prestress.anchorage_zone(_tendon(count=4), 250, 420, 1e5)
    assert few.hairpins is None


def test_anchorage_zone_of_multi_strand_tendons():
    """BNBC Sec 9.13.4.7: spalling steel 2 % of Ppu; bursting by the simplified equations of
    the AASHTO reference (Sec 9.15.1): T = 0.25 Ppu (1 - a/h), d = 0.5 (h - 2e)."""
    tendon = _tendon(strands=4, anchorPlate=100)
    found = prestress.anchorage_zone(tendon, 250, 420, 4e5)
    ppu = 1.2 * 4e5
    assert found.spalling == pytest.approx(0.02 * ppu / 420)
    force, where, steel = found.bursting
    assert force == pytest.approx(0.25 * ppu * (1 - 100 / 250))
    assert where == pytest.approx(0.5 * 250)  # anchors at h/2: e = 0
    assert steel == pytest.approx(force / (0.85 * 420))


def test_transfer_strength_for_stressing():
    """BNBC Sec 9.13.5.3: f'ci >= 17 MPa single strand, 28 MPa multi-strand."""
    single = _design(_tendon(transferStrength=20))
    check = next(c for c in single.checks if c["name"].endswith("strength at stressing"))
    assert (check["demand"], check["ok"]) == (17, True)
    multi = _design(_tendon(strands=3, count=3, transferStrength=20))
    check = next(c for c in multi.checks if c["name"].endswith("strength at stressing"))
    assert (check["demand"], check["ok"]) == (28, False)


def test_integrity_tendons_through_the_columns():
    """BNBC Sec 9.12.6-9.12.7: two strands each way through the column, else bottom bars
    As >= 1.5 × 0.25 √f'c bw d / fy and 2.1 bw d / fy."""
    from types import SimpleNamespace

    from saengine.design.slab import Layer

    column = SimpleNamespace(id="C1", centre=(8000.0, 0.0), c1=500.0, c2=500.0, angle=0.0)
    x = _tendon()  # along X through y = 0
    y = _tendon(id="PT2", x1=8000, y1=-8000, x2=8000, y2=8000)
    layers = {"bottomX": Layer("bottomX", 12, 200, 200), "bottomY": Layer("bottomY", 12, 200, 188)}
    checks, _ = prestress.integrity_checks(
        [(x, "X"), (y, "Y")], [column], (1.0, 0.0), 35, 420, layers, True
    )
    assert [c["name"] for c in checks] == ["PT integrity strands, X", "PT integrity strands, Y"]
    assert all(c["ok"] for c in checks)
    off = SimpleNamespace(id="C2", centre=(8000.0, 3000.0), c1=500.0, c2=500.0, angle=0.0)
    checks, _ = prestress.integrity_checks([(x, "X")], [off], (1.0, 0.0), 35, 420, layers, True)
    bars = next(c for c in checks if c["name"] == "PT integrity bottom bars, X")
    needed = max(1.5 * 0.25 * math.sqrt(35) * 500 * 200 / 420, 2.1 * 500 * 200 / 420)
    assert bars["demand"] == pytest.approx(needed, abs=0.01)
    assert bars["capacity"] == pytest.approx(layers["bottomX"].area * 500 / 1000, abs=0.01)


def test_prestressed_compression_members():
    """BNBC Sec 9.11.2-9.11.3: below 1.6 MPa the ordinary minimums; above, ties >= No. 10 at
    <= 48 tie diameters, or ρs >= 0.45 (Ag/Ach - 1) f'c / fyt, fyt <= 700 MPa."""
    checks, notes = prestress.compression_member_checks("P1", 1.0, 400)
    assert not checks and "ordinary" in notes[0]
    checks, _ = prestress.compression_member_checks("P1", 2.0, 400, tie_dia=10, tie_spacing=450)
    spacing = next(c for c in checks if c["name"].endswith("tie spacing"))
    assert spacing["capacity"] == 400 and not spacing["ok"]
    checks, _ = prestress.compression_member_checks(
        "P1", 2.0, 400, spiral=(0.02, 160_000, 120_000, 35, 800)
    )
    assert checks[0]["demand"] == pytest.approx(0.45 * (160_000 / 120_000 - 1) * 35 / 700, abs=1e-2)


def test_results_cite_the_pack_not_aci():
    design = _design(_tendon(transferStrength=25))
    text = " ".join(c["note"] for c in design.checks) + " ".join(design.notes)
    assert "ACI 318" not in text
    assert prestress.clause("relaxation").endswith("Sec 9.6.5, Table 6.9.2")


def test_bonded_fps_with_bonded_bars():
    """BNBC Eq 6.9.5: the bonded bars' d / dp ω inside the bracket."""
    fps = prestress.stress_at_strength(1100, 1860, 1674, 28, 0.003, 30, True, 0.05)
    assert fps == pytest.approx(1860 * (1 - 0.28 / 0.85 * (0.003 * 1860 / 28 + 0.05)))

"""B26: anchoring to concrete (Part 6 Appendix K of the default pack, part 2 pp. 526-564) and
the anchor rod tension of moment bases (Sec 10.10.9). Values pinned through the bnbc2020
pack's ``anchors`` table."""

from __future__ import annotations

import math

import pytest

from saengine.codes.tables import builtin_table
from saengine.design import anchors
from saengine.design import steel_connections as sc
from saengine.design.steel_proposal import SteelMaterial
from saengine.library.objects import AnchorConcrete, ColumnBasePlate
from saengine.library.steel_sections import find

INF = math.inf
T = builtin_table("anchors")


def group(points, spec=None, edges=(INF, INF, INF, INF), d=20.0, fc=25.0, **kw):
    return anchors.Group(
        points=points,
        diameter=d,
        fu=400,
        fy=250,
        concrete=fc,
        spec=spec or AnchorConcrete(**kw),
        edges=edges,
    )


def by_name(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


# ── the pack's values ──


def test_pack_values():
    # Sec K.4.4 (p. 537-538): φ steel 0.75/0.65 ductile, 0.65/0.60 brittle; concrete A/B
    assert (T.phi.steelTensionDuctile, T.phi.steelShearDuctile) == (0.75, 0.65)
    assert (T.phi.steelTensionBrittle, T.phi.steelShearBrittle) == (0.65, 0.6)
    assert (T.phi.concreteShear.A, T.phi.concreteShear.B) == (0.75, 0.7)
    assert (T.phi.concreteTension["castIn"].A, T.phi.concreteTension["castIn"].B) == (0.75, 0.7)
    assert T.phi.concreteTension["category3"].B == 0.45
    # Eq 6.K.7 kc 10 / 7 (p. 542); Sec K.3.5 f'c caps 70 / 55 MPa (p. 533)
    assert T.breakoutTension.kc == {"castIn": 10, "postInstalled": 7}
    assert T.concreteStrengthMax == {"castIn": 70, "postInstalled": 55}
    # Sec K.3.3.3, K.3.3.6 (pp. 532-533): 0.75, 0.4, stud walls 0.5; SDC C and D
    assert (T.seismic.concreteFactor, T.seismic.reducedFactor) == (0.75, 0.4)
    assert T.seismic.studWallFactor == 0.5
    assert T.seismic.categories == ["C", "D"]
    # Eq 6.K.32 (p. 561): 0.2 and 1.2
    assert (T.interaction.threshold, T.interaction.limit) == (0.2, 1.2)


# ── tension ──


def test_steel_tension_effective_area_and_futa_cap():
    # Eq 6.K.3 (p. 539): Nsa = Ase,N futa, futa <= min(1.9 fya, 860); Ase = π/4 (d - 0.9743/nt)²
    g = group([(0, 0)])
    ase = math.pi / 4 * (20 - 0.9743 * 2.5) ** 2
    assert anchors.effective_area(g, T) == pytest.approx(ase)
    g.fu, g.fy = 600, 250  # futa capped at 1.9 × 250 = 475
    r = anchors.check_group(g, [anchors.Demand("C", [10e3])])
    assert by_name(r, "anchor steel in tension (per anchor)")["capacity"] == pytest.approx(
        0.75 * ase * 475 / 1e3, abs=0.01
    )


def test_breakout_single_anchor_far_from_edges():
    # Eqs 6.K.4, 6.K.6, 6.K.7 (pp. 540-541): ANco = 9 hef², Nb = 10 √f'c hef^1.5 (cast-in)
    g = group([(0, 0)], embedment=200)
    ncb, f = anchors.breakout_tension(g, T, [0])
    assert f["ANc"] == pytest.approx(9 * 200**2)
    assert ncb == pytest.approx(10 * math.sqrt(25) * 200**1.5)


def test_breakout_deep_headed_alternative():
    # Eq 6.K.8 (p. 542): 3.9 √f'c hef^(5/3) for cast-in headed with 280 <= hef <= 635 mm
    g = group([(0, 0)], embedment=400)
    _, f = anchors.breakout_tension(g, T, [0])
    assert f["Nb"] == pytest.approx(max(10 * 5 * 400**1.5, 3.9 * 5 * 400 ** (5 / 3)), rel=1e-6)


def test_breakout_edge_factor_and_projected_area():
    # Eqs 6.K.10-6.K.11 (p. 544): ψed,N = 0.7 + 0.3 ca,min / 1.5 hef
    g = group([(0, 0)], edges=(150, INF, INF, INF), embedment=200)
    ncb, f = anchors.breakout_tension(g, T, [0])
    assert f["psiEd"] == pytest.approx(0.7 + 0.3 * 150 / 300)
    assert f["ANc"] == pytest.approx((150 + 300) * 600)
    assert ncb == pytest.approx(450 * 600 / 360000 * f["psiEd"] * 10 * 5 * 200**1.5)


def test_breakout_narrow_member_hef():
    # Sec K.5.2.3 (p. 542): within 1.5 hef of 3+ edges, hef = max(ca,max/1.5, s/3)
    g = group([(0, 0)], edges=(150, 150, 120, INF), embedment=300)
    _, f = anchors.breakout_tension(g, T, [0])
    assert f["hef"] == pytest.approx(150 / 1.5)


def test_breakout_eccentricity_and_cracking():
    # Eq 6.K.9 (p. 543): ψec,N = 1 / (1 + 2e'N / 3hef); Sec K.5.2.6: uncracked 1.25 cast-in
    g = group([(-100, 0), (100, 0)], embedment=200, cracked=False)
    _, f = anchors.breakout_tension(g, T, [0, 1], [10.0, 30.0])
    e = abs((10 * -100 + 30 * 100) / 40 - 0)
    assert f["psiEc"] == pytest.approx(1 / (1 + 2 * e / (3 * 200)))
    assert f["psiC"] == 1.25


def test_pullout_headed_and_hooked():
    # Eqs 6.K.14-6.K.16 (pp. 548-549): Np = 8 Abrg f'c; 0.9 f'c eh da (eh <= 4.5 da);
    # ψc,P = 1.4 uncracked
    g = group([(0, 0)], headBearingArea=1000, cracked=False)
    assert anchors.pullout(g, T) == pytest.approx(1.4 * 8 * 1000 * 25)
    h = group([(0, 0)], kind="hookedBolt", hookExtension=200)  # capped at 4.5 × 20 = 90
    assert anchors.pullout(h, T) == pytest.approx(0.9 * 25 * 90 * 20)
    p = group([(0, 0)], kind="undercut")  # post-installed: only from the product's tests
    assert anchors.pullout(p, T) is None


def test_side_face_blowout():
    # Eqs 6.K.17-6.K.18 (p. 549): hef > 2.5 ca1: Nsb = 13 ca1 √Abrg √f'c, × (1 + ca2/ca1)/4
    g = group([(0, 0)], edges=(60, INF, 100, INF), embedment=300, headBearingArea=900)
    found = anchors.side_face(g, T, [0], [50e3])
    nsb = 13 * 60 * math.sqrt(900) * math.sqrt(25)
    ca1_edge = next(f for f in found if f[2] == pytest.approx(60))
    assert ca1_edge[1] == pytest.approx(nsb * (1 + 100 / 60) / 4)
    row = group([(0, -50), (0, 50)], edges=(60, INF, INF, INF), embedment=300, headBearingArea=900)
    demand, nominal, _ = anchors.side_face(row, T, [0, 1], [20e3, 20e3])[0]
    assert demand == pytest.approx(40e3)
    assert nominal == pytest.approx((1 + 100 / (6 * 60)) * nsb)


# ── shear ──


def test_shear_breakout_basic():
    # Eqs 6.K.21-6.K.24 (pp. 551-553): AVco = 4.5 ca1²; Vb = 0.6 (le/da)^0.2 √da √f'c ca1^1.5
    g = group([(0, 0)], edges=(100, INF, INF, INF), embedment=200)
    vcb, f = anchors.breakout_shear(g, T, 0, [0])
    le = min(200, 8 * 20)
    vb = 0.6 * (le / 20) ** 0.2 * math.sqrt(20) * 5 * 100**1.5
    assert f["AVco"] == pytest.approx(4.5 * 100**2)
    assert f["AVc"] == pytest.approx(f["AVco"])
    assert vcb == pytest.approx(vb)


def test_shear_breakout_thickness_edge_cracking():
    # Eq 6.K.28 ψed,V; Eq 6.K.29 ψh,V = √(1.5 ca1 / ha) >= 1; Sec K.6.2.7 ψc,V 1.2 edge bar
    g = group(
        [(0, 0)],
        edges=(200, INF, 150, INF),
        embedment=200,
        memberThickness=200,
        shearEdgeReinforcement="edgeBar",
    )
    _, f = anchors.breakout_shear(g, T, 0, [0])
    assert f["psiEd"] == pytest.approx(0.7 + 0.3 * 150 / 300)
    assert f["psiH"] == pytest.approx(math.sqrt(300 / 200))
    assert f["psiC"] == 1.2
    assert f["AVc"] == pytest.approx((150 + 300) * 200)


def test_pryout_and_steel_shear_with_grout_pad():
    # Eqs 6.K.30-6.K.31 (p. 560): Vcp = kcp Ncb, kcp = 2 for hef >= 65 mm, φ Condition B 0.70;
    # Eq 6.K.20 0.6 Ase futa × 0.80 on a grout pad (Sec K.6.1.3)
    g = group([(0, 0)], embedment=200)
    r = anchors.check_group(g, [anchors.Demand("C", [0.0], 20e3)])
    ncb = 10 * 5 * 200**1.5
    assert by_name(r, "concrete pryout")["capacity"] == pytest.approx(0.7 * 2 * ncb / 1e3, abs=0.01)
    ase = anchors.effective_area(g, T)
    assert by_name(r, "anchor steel in shear (per anchor)")["capacity"] == pytest.approx(
        0.65 * 0.6 * ase * 400 * 0.8 / 1e3, abs=0.01
    )


def test_interaction_trilinear():
    # Sec K.7 (p. 561): Nua/φNn + Vua/φVn <= 1.2 when both exceed 0.2
    g = group([(0, 0)], edges=(150, INF, INF, INF), embedment=200)
    r = anchors.check_group(g, [anchors.Demand("C", [30e3], 15e3)])
    check = by_name(r, "tension and shear interaction")
    assert check["capacity"] == 1.2
    small = anchors.check_group(g, [anchors.Demand("C", [30e3], 100.0)])
    assert "tension and shear interaction" not in [c["name"] for c in small["checks"]]


# ── seismic and rules ──


def test_seismic_concrete_reduction_and_reduced_strength():
    # Sec K.3.3.3 (p. 532): concrete modes × 0.75 in SDC C/D earthquake combinations;
    # K.3.3.6 (p. 533): × 0.4 more when ductility is not provided
    g = group([(0, 0)], embedment=200)
    plain = anchors.check_group(g, [anchors.Demand("E1", [10e3])])
    quake = anchors.SeismicContext("D", frozenset({"E1"}))
    r = anchors.check_group(g, [anchors.Demand("E1", [10e3])], quake)
    name = "concrete breakout in tension (anchors in tension)"
    assert by_name(r, name)["capacity"] == pytest.approx(
        0.75 * by_name(plain, name)["capacity"], abs=0.02
    )
    assert any(c["name"].startswith("ductile steel governs") for c in r["checks"])
    g.spec = AnchorConcrete(embedment=200, seismicDesign="reducedStrength")
    r = anchors.check_group(g, [anchors.Demand("E1 [x]", [10e3])], quake)
    assert by_name(r, name)["capacity"] == pytest.approx(
        0.3 * by_name(plain, name)["capacity"], abs=0.02
    )
    b = anchors.check_group(
        g, [anchors.Demand("E1", [10e3])], anchors.SeismicContext("B", quake.earthquake)
    )
    assert by_name(b, name)["capacity"] == pytest.approx(by_name(plain, name)["capacity"])


def test_spacing_and_edge_rules():
    # Sec K.8.1-K.8.3 (p. 562): spacing 4 da untorqued cast-in, 6 da torqued; edges: cover,
    # 6 da torqued cast-in, 8 da torque-controlled post-installed
    g = group([(-50, 0), (50, 0)], edges=(150, 150, INF, INF), embedment=200)
    r = anchors.check_group(g, [anchors.Demand("C", [0.0, 0.0])])
    assert by_name(r, "anchor spacing")["demand"] == pytest.approx(80)
    assert by_name(r, "anchor edge distance")["demand"] == pytest.approx(40)
    g.spec = AnchorConcrete(embedment=200, torqued=True)
    r = anchors.check_group(g, [anchors.Demand("C", [0.0, 0.0])])
    assert by_name(r, "anchor spacing")["demand"] == pytest.approx(120)
    assert by_name(r, "anchor edge distance")["demand"] == pytest.approx(120)
    g.spec = AnchorConcrete(embedment=100, kind="torqueControlled", memberThickness=150)
    r = anchors.check_group(g, [anchors.Demand("C", [0.0, 0.0])])
    assert by_name(r, "anchor edge distance")["demand"] == pytest.approx(160)
    # Sec K.8.5 (p. 563): hef <= max(2/3 ha, ha - 100)
    assert by_name(r, "post-installed embedment in the member")["capacity"] == pytest.approx(100)


def test_not_covered_by_a_pack_without_the_table(monkeypatch):
    monkeypatch.setattr(anchors, "anchors_table", lambda: None)
    r = anchors.check_group(group([(0, 0)]), [anchors.Demand("C", [1e3])])
    assert r["covered"] is False and r["checks"] == []


# ── base plates: rod tension from the base moment (Sec 10.10.9) ──


def test_base_plate_moment_rod_tension_bearing_block():
    c = ColumnBasePlate(
        length=400, width=300, anchors=4, anchorDiameter=20, supportLength=600, supportWidth=500
    )
    points = sc.anchor_points(c)
    assert sorted(points) == [(-150, -100), (-150, 100), (150, -100), (150, 100)]
    p, m = 300e3, 150e6
    tension, info = sc.rod_tensions(c, points, p, m)
    fp = sc.bearing_on_concrete(c) / (400 * 300)
    # about the B axis (length 300, width 400, f = 100) governs
    q, f, e = fp * 400, 100.0, 500.0
    lever = f + 150
    y = lever - math.sqrt(lever**2 - 2 * p * (e + f) / q)
    assert info["axis"] == "B"
    assert max(tension) == pytest.approx((q * y - p) / 2)
    # small eccentricity: no rod tension
    assert max(sc.rod_tensions(c, points, 1500e3, 10e6)[0]) == 0.0
    # net uplift: rods alone, -P/n + M x / Σx²
    t, _ = sc.rod_tensions(c, points, -100e3, 0.0)
    assert t == pytest.approx([25e3] * 4)
    # no bearing length balances it (the bare plate's smaller bearing stress): the rods take it
    # about the opposite rod line, T = P (e - f) / 2f
    bare = c.model_copy(update={"supportLength": None, "supportWidth": None})
    t, info = sc.rod_tensions(bare, points, p, m)
    assert info["need"] > info["lever"]
    assert info["axis"] == "B"
    assert max(t) == pytest.approx(p * (e - f) / (2 * f) / 2)


def test_base_plate_reports_anchorage_checks():
    a36 = SteelMaterial(name="A36", fy=250, fu=400)
    c = ColumnBasePlate(anchors=4, anchorDiameter=20, supportLength=600, supportWidth=500)
    r = sc.check_base_plate(c, find("HEB 300"), a36, a36, [("U", -100e3, 60e3, 0.0)])
    names = [k["name"] for k in r["checks"]]
    assert "anchorage: concrete breakout in tension (anchors in tension)" in names
    assert "anchorage: concrete breakout in shear (toward an edge)" in names
    assert by_name(r, "anchor rod tension")["demand"] == pytest.approx(25.0)

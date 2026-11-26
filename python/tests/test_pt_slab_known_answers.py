"""#285 known answers of post-tensioned slab design, worked by hand (closed forms) and compared
with saengine.design.prestress under the default pack (BNBC 2020 Part 6 Chapter 9).

The strip: a single span L = 8 m, one way, b = 1000 mm, h = 200 mm, unbonded; two 12.7 mm
monostrands (Aps = 197.4 mm²), fpu = 1860 MPa, jacked to 0.80 fpu from the start; μ = 0.07,
K = 0.0033 /m, anchor set 6 mm, Ep = 195 000 MPa; f'ci = 25 MPa, f'c = 35 MPa; the long-term loss
entered as 150 MPa. Profile: CGS 100 mm (mid-depth) at the anchors, 30 mm at mid-span: one
parabola with drape a = 70 mm. Loads: self-weight 4.8 kPa, superimposed 1.0 kPa, live 2.0 kPa.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.design import prestress
from saengine.design.rc import beta1
from saengine.fem import prestress_case
from saengine.library.bim import SlabTendon
from saengine.library.templates import TEMPLATES

L, B, H = 8000.0, 1000.0, 200.0
DRAPE = 70.0
APS = 2 * 98.7
FPU, JACK, EP = 1860.0, 0.80, 195_000.0
MU, K, SET = 0.07, 0.0033, 6.0
FCI, FC, FY = 25.0, 35.0, 420.0
LONG_TERM = 150.0
LOADS = prestress.StripLoads(0.0048, 0.0010, 0.0020)  # N/mm² of plan
POINTS = [(0.0, 100.0), (L / 2, 30.0), (L, 100.0)]

# Hand values.
PJ = JACK * FPU * APS
#: The angle change grows evenly along the parabola: α(x) = 8 a x / L², so with the wobble the
#: friction is one exponential P(x) = Pj e^(-λ x).
LAM = K / 1000 + MU * 8 * DRAPE / L**2


def _tendon(**changes) -> SlabTendon:
    base = {
        **TEMPLATES["SlabTendon"],
        "layout": "distributed",
        "x1": 0,
        "y1": 0,
        "x2": L,
        "y2": 0,
        "width": B,
        "count": 2,
        "strands": 1,
        "strandArea": 98.7,
        "fpu": FPU,
        "fpy": None,
        "ep": EP,
        "jacking": JACK,
        "bonded": False,
        "stressedAt": "start",
        "wobble": K,
        "friction": MU,
        "anchorSet": SET,
        "longTermLoss": LONG_TERM,
        "transferStrength": FCI,
        "profile": [{"at": x, "height": y} for x, y in POINTS],
    }
    return SlabTendon(**{**base, **changes})


def _design(**changes) -> prestress.TendonDesign:
    return prestress.tendon_design(
        _tendon(**changes), H, FC, FY, LOADS, 0.0, 0.0, H - 30, H - 30, False
    )


def test_friction_loss_along_a_parabolic_tendon():
    """P(x) = Pj e^-(K x + μ α), α(x) = 8 a x / L² of the parabola: 0.035 rad at mid-span,
    0.070 rad at the far end."""
    pieces = prestress.segments(POINTS)
    assert prestress.angle_change(pieces, L / 2) == pytest.approx(4 * DRAPE / L, rel=1e-12)
    assert prestress.angle_change(pieces, L) == pytest.approx(8 * DRAPE / L, rel=1e-12)
    stations = np.array([0.0, 2000.0, 4000.0, 6000.0, 8000.0])
    found = prestress.friction_forces(PJ, pieces, stations, K, MU, "start")
    expected = PJ * np.exp(-(K * stations / 1000 + MU * 8 * DRAPE * stations / L**2))
    np.testing.assert_allclose(found, expected, rtol=1e-12)
    # The far end by hand: e^-(0.0264 + 0.0049) = e^-0.0313.
    assert found[-1] / PJ == pytest.approx(math.exp(-0.0313), rel=1e-12)
    # Stressed from both ends the force is symmetric, least at mid-span.
    both = prestress.friction_forces(PJ, pieces, stations, K, MU, "both")
    assert both[2] == pytest.approx(PJ * math.exp(-LAM * L / 2), rel=1e-12)
    assert both[0] == pytest.approx(PJ) and both[-1] == pytest.approx(PJ)


def _hand_forces() -> dict[str, float]:
    """Friction, set (it reaches the far end), elastic shortening and the effective force by
    hand: the draw-in work W = Δ Ep Aps; the mirrored diagram over the whole length takes
    2 ∫ (P - P(L)) dx and the rest W - that drops it evenly over L."""
    p_far = PJ * math.exp(-LAM * L)
    work = SET * EP * APS
    mirrored = 2 * PJ * ((1 - math.exp(-LAM * L)) / LAM - L * math.exp(-LAM * L))
    assert mirrored < work  # the set reaches the far end
    drop = (work - mirrored) / L
    mean_friction = PJ * (1 - math.exp(-LAM * L)) / (LAM * L)
    mean_after_set = 2 * p_far - drop - mean_friction
    eci = 4700 * math.sqrt(FCI)  # Ec = 4700 √f'c (MPa)
    elastic = 0.5 * EP / eci * mean_after_set / (B * H)
    p_i = mean_after_set - elastic * APS
    p_e = p_i - LONG_TERM * APS
    return {
        "p_far": p_far,
        "drop": drop,
        "after_set_0": 2 * p_far - PJ - drop,
        "mean_after_set": mean_after_set,
        "eci": eci,
        "elastic": elastic,
        "p_i": p_i,
        "p_e": p_e,
    }


def test_losses_of_the_strip_by_hand():
    hand = _hand_forces()
    design = _design()
    f = design.forces
    assert f.jacking == pytest.approx(PJ, rel=1e-12)
    assert f.friction[-1] == pytest.approx(hand["p_far"], rel=1e-9)
    # Draw-in reaches the far end: set length = L.
    assert f.set_length == pytest.approx(L)
    assert f.after_set[0] == pytest.approx(hand["after_set_0"], rel=5e-3)
    assert float(np.mean(f.after_set)) == pytest.approx(hand["mean_after_set"], rel=5e-3)
    assert f.eci == pytest.approx(hand["eci"], rel=1e-6)
    assert f.elastic == pytest.approx(hand["elastic"], rel=5e-3)
    assert float(np.mean(f.initial)) == pytest.approx(hand["p_i"], rel=5e-3)
    assert float(np.mean(f.effective)) == pytest.approx(hand["p_e"], rel=5e-3)
    assert f.long_term == LONG_TERM


def test_balanced_load_w_8_p_a_over_l_squared():
    design = _design()
    p_e = float(np.mean(design.forces.effective))
    (span,) = design.balance
    assert span.drape == pytest.approx(DRAPE)
    assert span.length == pytest.approx(L)
    assert span.load == pytest.approx(8 * p_e * DRAPE / L**2, rel=1e-12)
    # One symmetric parabola: its own curvature load is the same.
    assert span.mean == pytest.approx(span.load, rel=1e-9)
    # The balanced moment at mid-span is -P a (= -w L² / 8), and a simple span has no M2.
    mid = int(np.argmin(np.abs(design.diagrams["stations"] - L / 2)))
    assert design.diagrams["balanced"][mid] == pytest.approx(-p_e * DRAPE, rel=1e-6)
    assert np.max(np.abs(design.diagrams["hyperstatic"])) < 1e-6 * p_e * DRAPE


def test_transfer_and_service_stresses_at_mid_span():
    """f = P / A ± M / S, M at mid-span = w L² / 8 - P a (compression positive)."""
    hand = _hand_forces()
    design = _design()
    d = design.diagrams
    mid = int(np.argmin(np.abs(d["stations"] - L / 2)))
    area, modulus = B * H, B * H**2 / 6

    def gravity(load: float) -> float:
        return load * B * L**2 / 8

    p_i, p_e = hand["p_i"], hand["p_e"]
    m_transfer = gravity(LOADS.dead) - p_i * DRAPE
    assert d["transferTop"][mid] == pytest.approx(p_i / area + m_transfer / modulus, rel=5e-3)
    assert d["transferBottom"][mid] == pytest.approx(p_i / area - m_transfer / modulus, rel=5e-3)
    m_service = gravity(LOADS.dead + LOADS.superimposed + LOADS.live) - p_e * DRAPE
    top = p_e / area + m_service / modulus
    bottom = p_e / area - m_service / modulus
    assert d["serviceTop"][mid] == pytest.approx(top, rel=5e-3)
    assert d["serviceBottom"][mid] == pytest.approx(bottom, rel=5e-3)
    # One-way: the class from the extreme service tension (mid-span bottom), Class U up to
    # 0.62 √f'c, T up to 1.0 √f'c (BNBC Sec 9.4.3).
    ft = max(-bottom, 0.0)
    expected = "U" if ft <= 0.62 * math.sqrt(FC) else "T" if ft <= math.sqrt(FC) else "C"
    assert design.member_class == expected
    assert any(f"service tension {ft:.2f} MPa" in n for n in design.notes)
    # Average precompression P_e / (b h).
    assert design.precompression == pytest.approx(p_e / area, rel=5e-3)


def test_flexural_strength_with_unbonded_fps():
    """Unbonded, span/depth 8000 / 200 = 40 > 35: fps = fse + 70 + f'c / (300 ρp), at most
    fse + 210 and fpy (BNBC Sec 9.8.2); a = Aps fps / (0.85 f'c b); φ = 0.9 (tension-controlled);
    Mu = the worst gravity combination's w L² / 8 (M2 = 0 on a simple span)."""
    hand = _hand_forces()
    design = _design()
    u = design.ultimate
    assert u["at"] == pytest.approx(L / 2, abs=300)
    fse = hand["p_e"] / APS
    dp = H - 30.0
    rho_p = APS / (B * dp)
    fps = min(fse + 70 + FC / (300 * rho_p), fse + 210, 0.9 * FPU)
    a = APS * fps / (0.85 * FC * B)
    c = a / beta1(FC)
    assert 0.003 * (dp - c) / c > 0.005  # tension-controlled
    phi_mn = 0.9 * APS * fps * (dp - a / 2) / 1e6  # kN·m
    w = {
        "D": LOADS.dead + LOADS.superimposed,
        "L": LOADS.live,
    }
    mu = max(
        (f.factors.get("D", 0.0) * w["D"] + (f.factors.get("L", 0.0) + f.factors.get("Lr", 0.0))
         * w["L"]) * B * L**2 / 8 / 1e6
        for f in code_context.table("combinations").gravity
    )  # fmt: skip
    assert u["fse"] == pytest.approx(fse, rel=5e-3)
    assert u["fps"] == pytest.approx(fps, rel=5e-3)
    assert u["a"] == pytest.approx(a, rel=5e-3)
    assert u["phi"] == pytest.approx(0.9)
    assert u["phiMn"] == pytest.approx(phi_mn, rel=5e-3)
    assert u["mu"] == pytest.approx(mu, rel=1e-3)
    check = next(c for c in design.checks if c["name"].endswith("flexural strength"))
    assert check["utilisation"] == pytest.approx(mu / phi_mn, rel=1e-2)


def test_equivalent_loads_of_the_fe_case_are_in_equilibrium():
    """The PT case's loads of a group sum to zero: the upward curvature load P y'' L = 8 P a / L
    balances the anchors' downward slope components, and the anchor forces cancel."""
    tendon = _tendon()
    force = 250_000.0
    loads = prestress_case.tendon_point_loads(tendon, force, H)
    total = sum(v for _, _, v in loads)
    np.testing.assert_allclose(total[:3], 0.0, atol=1e-6 * force)
    upward = sum(v[2] for _, _, v in loads if v[2] > 0)
    assert upward == pytest.approx(8 * force * DRAPE / L, rel=1e-6)
    # Distributed over the 1 m strip: two lines of points across (500 mm apart).
    assert {round(y) for _, y, _ in loads} == {-250, 250}


def test_fe_case_puts_the_loads_on_the_slab_shells():
    """A one-shell slab: the PT pattern holds the loads at its four nodes, in equilibrium."""
    project = {
        "nodes": [
            {"id": 1, "coords": [0.0, -1.0, 3.0]},
            {"id": 2, "coords": [8.0, -1.0, 3.0]},
            {"id": 3, "coords": [8.0, 1.0, 3.0]},
            {"id": 4, "coords": [0.0, 1.0, 3.0]},
        ],
        "elements": [{"id": 1, "type": "Shell", "name": "S1#1", "nodes": [1, 2, 3, 4]}],
        "load_patterns": [],
        "analyses": [],
        "time_series": [],
    }
    design = _design()
    row = {"slab": "S1", "tendon": _tendon(), "design": design, "h": H}
    analysis, notes = prestress_case.add_prestress_case(project, [row])
    assert analysis is not None
    (pattern,) = project["load_patterns"]
    assert pattern["name"] == "PT"
    forces = np.array([n["forces"] for n in pattern["nodal_loads"]])
    np.testing.assert_allclose(forces[:, :3].sum(axis=0), 0.0, atol=1.0)
    assert project["analyses"][0]["name"] == "PT: Post-tensioning"
    assert any("case PT" in n for n in notes)


def test_pack_without_prestress_says_not_provided(monkeypatch):
    """A pack without prestressed concrete: the limits are not there and the checks say so."""
    monkeypatch.setattr(prestress, "limits", lambda: (_ for _ in ()).throw(ValueError("x")))
    with pytest.raises(ValueError):
        prestress.limits()
    assert "not covered by the code pack" in prestress.not_covered("post-tensioning")

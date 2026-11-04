"""P4: assessment and retrofit of existing buildings (fem/existing_building.py, the packs'
``existing`` table): knowledge factors (ASCE 41-17 Table 6-1 type, EN 1998-3 Table 3.1),
as-built strengths from tests, the model state, the section strength, C1·C2, m-factors, the
shear strengths, and an example column with κ and an FRP jacket (ACI 440.2R-17)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.fem import existing_building as eb
from saengine.library.defaults import default_material_library, default_object_library
from saengine.library.settings import ExistingBuilding, FrpWrap, MaterialTest, MemberCondition

BD, US, EU = "bnbc2020", "aci318-asce7-22", "eurocodes"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def existing(pack_id: str):
    return registry.load(pack_id).table("existing")


# ── the packs ──


def test_default_pack_labels_its_values_saengine_practice() -> None:
    rule = existing(BD)
    assert rule.basis.startswith("SAEngine practice, ASCE 41 basis")
    assert "Part 10 Sec 1.3.2" in rule.sources["requirement"]
    # κ of the brief's ASCE 41 levels; minimum knowledge: the linear procedures only.
    assert [(k.id, k.capacityFactor) for k in rule.knowledge] == [
        ("minimum", 0.75),
        ("usual", 0.9),
        ("comprehensive", 1.0),
    ]
    assert rule.knowledge[0].procedures == ["linear"]
    assert rule.linear.method == "mFactor" and rule.shear.method == "columnDuctility"
    assert rule.frp.method == "aci440"


def test_us_pack_values() -> None:
    rule = existing(US)
    assert rule.basis == "ASCE/SEI 41-17"
    s = rule.strengths
    # ASCE 41-17 Table 10-1: expected / lower bound 1.5 (concrete), 1.25 (bars); mean - 1σ.
    assert (s.expectedFactors["concrete"], s.expectedFactors["rebar"]) == (1.5, 1.25)
    assert s.lowerBoundSigma == 1.0 and s.covLimit == 0.14
    assert (s.deformation.value, s.force.value) == ("expected", "lowerBound")
    lin = rule.linear
    # ASCE 41-17 Eqs 7-1, 7-2: QG = 1.1 (QD + 0.25 QL), 0.9 QD.
    assert (lin.gravityUpper, lin.gravityLower, lin.liveShare) == (1.1, 0.9, 0.25)
    assert [(h.id, h.spectrumScale, h.level) for h in lin.hazards] == [
        ("BSE-1N", 1.0, "LS"),
        ("BSE-2N", 1.5, "CP"),
    ]
    beam = lin.mFactors["rcBeam"].rows[0]  # condition i, conforming, ρ-ρ' = 0, V ≤ 3√f'c
    assert beam.limits == {"IO": 3, "LS": 6, "CP": 7}
    # ACI 440.2R-17: CE carbon interior 0.95, κε = 0.55, ψf 0.95, fl/f'c ≥ 0.08, εccu ≤ 0.01.
    frp = rule.frp
    assert frp.environment["carbon"]["interior"] == 0.95
    c = frp.confinement
    assert (c.strainShare, c.psi, c.strength, c.minRatio, c.strainCap) == (
        0.55,
        0.95,
        3.3,
        0.08,
        0.01,
    )
    assert (frp.shear.strainFull, frp.shear.strainShare) == (0.004, 0.75)
    assert (frp.flexure.psi, frp.flexure.debonding, frp.flexure.debondingShare) == (0.85, 0.41, 0.9)


def test_eurocodes_pack_values() -> None:
    rule = existing(EU)
    # EN 1998-3 Table 3.1: CF 1.35, 1.20, 1.00; KL1 the linear methods only.
    assert [(k.id, k.confidenceFactor) for k in rule.knowledge] == [
        ("KL1", 1.35),
        ("KL2", 1.2),
        ("KL3", 1.0),
    ]
    assert rule.knowledge[0].procedures == ["linear"]
    assert rule.strengths.deformation.divideByConfidence
    assert (rule.strengths.force.concreteDivisor, rule.strengths.force.steelDivisor) == (1.5, 1.15)
    assert rule.linear.method == "chordRotation"
    assert [lv.id for lv in rule.linear.levels] == ["DL", "SD", "NC"]
    assert rule.linear.chordRotation.shares == {"SD": 0.75, "NC": 1.0}  # A.3.2.3, A.3.2.2
    s = rule.shear  # A.3.3.1 Eq A.12
    assert (s.gammaEl, s.axialShare, s.degradation, s.rhoFactor, s.spanFactor) == (
        1.15,
        0.55,
        0.05,
        0.16,
        0.16,
    )
    j = rule.jacketing  # A.4.2.2
    assert (j.strengthFactor, j.yieldFactor, j.ultimateFactor, j.shearFactor) == (1, 1.05, 1, 0.9)


# ── knowledge and strengths ──


def test_knowledge_level_and_overrides() -> None:
    rule = existing(US)
    know = eb.knowledge(ExistingBuilding(knowledgeLevel="usual"), rule)
    assert (know.id, know.kappa, know.cf) == ("usual", 0.9, 1.0)
    own = eb.knowledge(ExistingBuilding(knowledgeLevel="usual", knowledgeFactor=0.8), rule)
    assert own.kappa == 0.8
    unknown = eb.knowledge(ExistingBuilding(knowledgeLevel="KL3"), rule)
    assert unknown.id == "minimum" and "not one of the code pack's" in unknown.note
    assert eb.knowledge(ExistingBuilding(), existing(EU)).cf == 1.35


def test_strengths_from_cores_and_defaults() -> None:
    rule = existing(US)
    tests = [
        MaterialTest(material="C24.1", kind="core", values=[20.0, 22.0, 24.0]),
        MaterialTest(material="C24.1", kind="rebound", values=[40.0]),  # not calibrated
        MaterialTest(material="B420DWR", kind="tensile", values=[450.0, 470.0, 460.0]),
    ]
    found = eb.strengths(ExistingBuilding(tests=tests), rule, default_material_library())
    core = found["C24.1"]
    # Mean 22, σ 2 (sample), lower bound mean - 1σ = 20, expected = the mean.
    assert (core.tests, core.mean, core.std, core.lower, core.expected) == (
        3,
        22.0,
        2.0,
        20.0,
        22.0,
    )
    assert core.cov == pytest.approx(2 / 22)
    assert any("calibration" in n for n in core.notes)
    bars = found["B420DWR"]
    assert (bars.mean, bars.lower) == (460.0, 450.0)
    # Without tests: lower bound = specified, expected = 1.5 × it (ASCE 41-17 Table 10-1).
    untested = next(ms for ms in found.values() if ms.kind == "concrete" and ms.tests == 0)
    assert untested.lower == untested.specified
    assert untested.expected == pytest.approx(1.5 * untested.specified)
    calibrated = MaterialTest(material="C24.1", kind="rebound", values=[40.0], calibration=0.5)
    again = eb.strengths(ExistingBuilding(tests=[calibrated]), rule, default_material_library())
    assert again["C24.1"].mean == 20.0


def test_strength_uses_divide_by_cf_and_partial_factors() -> None:
    rule = existing(EU)
    found = eb.strengths(
        ExistingBuilding(tests=[MaterialTest(material="C24.1", kind="core", values=[27.0])]),
        rule,
        default_material_library(),
    )
    ms = found["C24.1"]
    s = rule.strengths
    assert ms.value(s.analysis, 1.35) == 27.0  # the analysis: the mean
    assert ms.value(s.deformation, 1.35) == pytest.approx(20.0)  # mean / CF
    assert ms.value(s.force, 1.35) == pytest.approx(27.0 / 1.35 / 1.5)  # brittle: / γc too


# ── the model state ──


def _building(elements):
    from saengine.library.bim import BuildingModel

    return BuildingModel.model_validate({"elements": elements})


def _column(cid: str, type_id: str = "C400x400") -> dict:
    return {
        "kind": "column",
        "id": cid,
        "type": type_id,
        "position": [0, 0],
        "bottom": 0,
        "top": 3000,
    }


def test_model_state_as_built_and_retrofitted() -> None:
    with code_context.using(registry.load(US)):
        building = _building([_column("C1"), _column("C2"), _column("C3")])
        objects, materials = default_object_library(), default_material_library()
        measures = [
            {"kind": "rcJacket", "id": "J1", "members": ["C1"], "thickness": 100},
            {"kind": "added", "id": "A1", "members": ["C3"]},
        ]
        conditions = [MemberCondition(members=["C2"], barLoss=0.19)]
        for state in ("asBuilt", "retrofitted"):
            settings = SimpleNamespace(
                analysis=SimpleNamespace(
                    existingBuilding=ExistingBuilding.model_validate(
                        {"state": state, "retrofit": measures, "conditions": conditions}
                    )
                )
            )
            found = eb.model_state(building, objects, materials, settings)
            ids = {e.id: e.type for e in found.building.elements}
            types = {o.id: o for o in found.objects.objects}
            # C2: its bars' area lost to corrosion, diameters × √(1 - 0.19) = 0.9.
            corroded = types[ids["C2"]]
            assert ids["C2"] == "C400x400.eb-c1"
            assert corroded.reinforcement.longitudinal[0].dia == pytest.approx(16 * 0.9)
            if state == "asBuilt":
                assert "C3" not in ids and found.removed == ["C3"]
                assert ids["C1"] == "C400x400"
            else:
                assert "C3" in ids
                jacketed = types[ids["C1"]]
                assert (jacketed.profile.xDim, jacketed.profile.yDim) == (600, 600)
                assert sum(g.count for g in jacketed.reinforcement.longitudinal) == 16
            # The materials at the expected strengths (no tests: 1.5 × f'c, 1.25 × fy).
            mats = {m.id: m for m in found.materials.materials}
            given = {m.id: m for m in materials.materials}
            assert mats["C24.1"].concrete.fc == pytest.approx(1.5 * given["C24.1"].concrete.fc)
            assert mats["B420DWR"].steel.fy == pytest.approx(1.25 * 420)


def test_model_state_without_existing_building_changes_nothing() -> None:
    building = _building([_column("C1")])
    objects, materials = default_object_library(), default_material_library()
    settings = SimpleNamespace(analysis=SimpleNamespace(existingBuilding=None))
    found = eb.model_state(building, objects, materials, settings)
    assert found.building is building and found.objects is objects
    assert found.materials is materials and found.notes == []


def test_state_type_id_stays_an_id() -> None:
    assert eb.state_type_id("C400", ["c1", "J1"]) == "C400.eb-c1-J1"
    long = eb.state_type_id("C" * 60, ["c1", "J1"])
    assert len(long) <= 64 and eb.TAG in long


# ── the section strength ──


def _section(bars, b=300.0, h=500.0, fc=30.0, fy=420.0):
    from saengine.design import rc
    from saengine.library.objects import RectangleProfile

    section = rc.RcSection(
        profile=RectangleProfile(xDim=b, yDim=h),
        bars=tuple(rc.Bar(x, y, rc.bar_area(d), d) for x, y, d in bars),
        fc=fc,
        fy=fy,
        es=200_000.0,
    )
    return eb.Section(section, b, h, False, "C", "B", 78.5, 2, 2, 150, 40, 20)


def test_strength_curve_pins_the_singly_reinforced_moment() -> None:
    # 3 Ø20 at d = 450: a = As fy/(0.85 f'c b) = 51.75 mm, Mn = As fy (d - a/2) = 167.9 kN·m.
    sec = _section([(-100, -200, 20), (0, -200, 20), (100, -200, 20)])
    curve = eb.strength_curve(sec, 0, 1.0, 30.0, 420.0, 200_000.0, (0.85, 0.836, 0.003))
    mn = float(eb.at_axial(curve, 0.0)[0])
    as_ = 3 * math.pi * 20**2 / 4
    a = as_ * 420 / (0.85 * 30 * 300)
    assert mn == pytest.approx(as_ * 420 * (450 - a / 2), rel=0.02)
    assert float(eb.at_axial(curve, 1e9)[0]) == 0.0  # beyond the squash load


def test_c1c2_by_period_and_largest_m() -> None:
    rule = existing(US)  # ASCE 41-17 Table 7-3
    assert eb.c1c2_factor(rule, 0.2, 1.5) == 1.1
    assert eb.c1c2_factor(rule, 0.2, 3.0) == 1.4
    assert eb.c1c2_factor(rule, 0.2, 7.0) == 1.8
    assert eb.c1c2_factor(rule, 0.5, 7.0) == 1.2
    assert eb.c1c2_factor(rule, 1.5, 7.0) == 1.0
    assert eb.c1c2_factor(rule, None, 3.0) == 1.4  # no period: the largest


def test_beam_m_factors_interpolate() -> None:
    rule = existing(US)
    component = rule.linear.mFactors["rcBeam"]
    values = {"control": "flexure", "conforming": "C", "rhoBalance": 0.0, "shearStress": 4.5}
    m = eb._m_factors(component, values, ["IO", "LS", "CP"])
    assert m == pytest.approx({"IO": 2.5, "LS": 4.5, "CP": 5.5})


def test_column_shear_asce41_equation() -> None:
    rule = existing(US).shear
    # 400×400, d 350, f'c 25, 2 legs Ø10 at 150, N 1000 kN, M/Vd = 2.857, k = 1.
    v = eb.shear_strength(
        rule, "column", 400, 400, 350, 25, 420, 2 * 78.54, 150, 1e6, 100e6, 100e3, 1.0
    )
    steel = 2 * 78.54 * 420 * 350 / 150
    concrete = 0.5 * 5 / (100e6 / (100e3 * 350)) * math.sqrt(1 + 1e6 / (0.5 * 5 * 160000))
    assert v == pytest.approx(steel + concrete * 0.8 * 160000, rel=1e-6)
    low = eb.shear_strength(
        rule, "column", 400, 400, 350, 25, 420, 2 * 78.54, 150, 1e6, 100e6, 100e3, 6.0
    )
    assert low == pytest.approx(0.7 * v)  # k = 0.7 at a ductility of 6


def test_cyclic_shear_degrades_with_plastic_ductility() -> None:
    rule = existing(EU).shear  # EN 1998-3 Eq A.12
    args = (rule, "column", 400, 400, 350, 25, 420, 157.08, 150, 0.0, 100e6, 100e3)
    v0 = eb.shear_strength(*args, 0.0, rho_tot=0.0126, x=100, lv=1500)
    v5 = eb.shear_strength(*args, 5.0, rho_tot=0.0126, x=100, lv=1500)
    assert v5 == pytest.approx(0.75 * v0)  # N = 0: the whole strength × (1 - 0.05·5)


# ── an example column with κ and an FRP jacket ──


def test_example_column_with_kappa_and_frp_jacket() -> None:
    """A 400×400 column of f'c 25 MPa with 8 Ø20, usual knowledge (κ = 0.9), wrapped in two
    plies of carbon sheet (tf 0.165 mm, Ef 230 GPa, εfu* 0.0167, interior). ACI 440.2R-17:
    εfu = CE·εfu* = 0.95 × 0.0167, εfe = 0.55 εfu, fl = 2 Ef n tf εfe/√(b² + h²) = 2.342 MPa,
    fl/f'c = 0.094 ≥ 0.08, κa = (Ae/Ac)(b/h)² = 0.4814 (rc = 25 mm), f'cc = f'c + 0.95 × 3.3 ×
    κa × fl = 28.53 MPa; shear: εfe = 0.004, Vf = 0.95 × 2 n tf εfe Ef d = 196.1 kN (d = 340)."""
    rule = existing(US)
    know = eb.knowledge(ExistingBuilding(knowledgeLevel="usual"), rule)
    assert know.kappa == 0.9
    wrap = FrpWrap(
        id="F1",
        members=["C1"],
        purpose="confinement",
        plies=2,
        thickness=0.165,
        modulus=230000,
        ruptureStrain=0.0167,
    )
    rho_g = 8 * math.pi * 20**2 / 4 / 160000
    found = eb.frp_effects(wrap, rule.frp, 400, 400, 340, 25.0, False, rho_g)
    assert found.eps_fu == pytest.approx(0.015865)
    assert found.confined
    assert found.fcc == pytest.approx(28.534, rel=1e-3)
    assert found.vf == pytest.approx(196125.6, rel=1e-3)
    # Its shear strength with κ: κ·(V + Vf) at the column equation's k = 1.
    v = eb.shear_strength(
        rule.shear, "column", 400, 400, 340, 25, 420, 157.08, 150, 1e6, 100e6, 100e3, 1.0,
        vf=found.vf, limit_share=rule.frp.shear.limitShare,
    )  # fmt: skip
    plain = eb.shear_strength(
        rule.shear, "column", 400, 400, 340, 25, 420, 157.08, 150, 1e6, 100e6, 100e3, 1.0
    )
    assert v > plain
    assert know.kappa * v == pytest.approx(0.9 * v)


def test_flexural_laminate_debonding_strain() -> None:
    rule = existing(US)
    laminate = FrpWrap(
        id="F2",
        members=["B1"],
        purpose="flexure",
        plies=1,
        thickness=1.2,
        modulus=165000,
        ruptureStrain=0.017,
        laminateWidth=100,
    )
    found = eb.frp_effects(laminate, rule.frp, 300, 500, 450, 30.0, False, 0.01)
    # ACI 440.2R-17 Eq 10.1.1: εfd = 0.41 √(f'c/(n Ef tf)) ≤ 0.9 εfu.
    eps_fd = min(0.41 * math.sqrt(30 / (165000 * 1.2)), 0.9 * 0.95 * 0.017)
    face, area, ef, strain = found.laminate
    assert (face, area, ef) == (-250, 0.85 * 1.2 * 100, 165000)
    assert strain == pytest.approx(eps_fd)
    sec = _section([(-100, -200, 20), (0, -200, 20), (100, -200, 20)])
    plain = eb.strength_curve(sec, 0, 1.0, 30.0, 420.0, 200_000.0, (0.85, 0.836, 0.003))
    strong = eb.strength_curve(
        sec, 0, 1.0, 30.0, 420.0, 200_000.0, (0.85, 0.836, 0.003), found.laminate
    )
    assert float(eb.at_axial(strong, 0.0)[0]) > float(eb.at_axial(plain, 0.0)[0])


def test_hinge_limits_take_kappa() -> None:
    rule = existing(US)
    know = eb.Knowledge("usual", "Usual", 0.9, 1.0, ("linear", "nonlinear"))
    row = {
        "covered": True,
        "component": "steelBeam",
        "limits": {"IO": 1.0, "LS": 9.0, "CP": 11.0},
        "demand": 8.5,
        "variables": {},
    }
    rules = SimpleNamespace(components={})
    out = eb.adjusted_hinge(row, rule, know, rules, ["IO", "LS", "CP"], "LS")
    assert out["limits"]["LS"] == pytest.approx(8.1)
    assert out["ratio"] == pytest.approx(8.5 / 8.1) and not out["ok"]


def test_hinge_theta_um_with_confidence_factor() -> None:
    rule = existing(EU)
    know = eb.Knowledge("KL1", "KL1", 1.0, 1.35, ("linear",))
    chord = registry.load(EU).table("pushover").hinges.components["rcColumn"].chordRotation
    rules = SimpleNamespace(
        components={"rcColumn": SimpleNamespace(model="chordRotationCapacity", chordRotation=chord)}
    )
    row = {
        "covered": True,
        "component": "rcColumn",
        "limits": {"DL": 0.005, "SD": 0.0225, "NC": 0.03},
        "demand": 0.02,
        "variables": {"nu": 0.2},
    }
    out = eb.adjusted_hinge(row, rule, know, rules, ["DL", "SD", "NC"], "SD")
    # θum with fc and fy over CF: × CF^-0.225 × 0.3^(ν (CF - 1)); θy unchanged.
    factor = 1.35**-0.225 * 0.3 ** (0.2 * 0.35)
    assert out["limits"]["NC"] == pytest.approx(0.03 * factor)
    assert out["limits"]["DL"] == 0.005

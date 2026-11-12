"""The general strut-and-tie model (B28): the pack's Appendix I values and the model engine.

Values pinned through the bnbc2020 pack: BNBC 2020 Part 6 Appendix I (part 2 pp. 481-495) and
Sec 6.2.3.2.6 (p. 898).
"""

from __future__ import annotations

import math

import pytest

from saengine.design import stm
from saengine.design import stm_model as sm
from saengine.library.strut_and_tie import (
    StmLoad,
    StmLoadCase,
    StmMember,
    StmModel,
    StmNode,
    StmWebLayer,
)

# ── the pack's values ──


def test_phi_is_sec_6_2_3_2_6():
    assert stm.phi() == pytest.approx(0.75)  # Sec 6.2.3.2.6
    assert "6.2.3.2.6" in stm.cite("equilibrium") or "I.2" in stm.cite("equilibrium")


def test_strut_betas_appendix_i_3_2():
    assert stm.beta_strut("prism") == pytest.approx(1.0)  # I.3.2.1
    assert stm.beta_strut("bottle", web=True) == pytest.approx(0.75)  # I.3.2.2(a)
    assert stm.beta_strut("bottle", web=False) == pytest.approx(0.60)  # I.3.2.2(b)
    assert stm.beta_strut("bottle", web=False, lam=0.75) == pytest.approx(0.45)  # 0.60 λ
    assert stm.beta_strut("tension") == pytest.approx(0.40)  # I.3.2.3
    assert stm.beta_strut("other", lam=0.85) == pytest.approx(0.51)  # I.3.2.4: 0.60 λ


def test_node_betas_appendix_i_5_2():
    assert stm.beta_node(0) == pytest.approx(1.0)  # I.5.2.1
    assert stm.beta_node(1) == pytest.approx(0.8)  # I.5.2.2
    # I.5.2.3 prints "βn = 0.80, βn = 0.60": the conservative 0.60 for two or more ties.
    assert stm.beta_node(2) == pytest.approx(0.6)
    assert stm.beta_node(3) == pytest.approx(0.6)
    assert "I.5.2.3" in stm.cite("betaCTT")


def test_effective_strength_eqs_6_i_3_and_6_i_8():
    assert stm.effective_strength(30.0, 0.75) == pytest.approx(0.85 * 0.75 * 30.0)
    assert stm.node_capacity(30.0, 1000.0, "CCT") == pytest.approx(0.75 * 0.85 * 0.8 * 30e3)


def test_other_appendix_i_values():
    assert stm.min_angle() == pytest.approx(25.0)  # I.2.5
    assert stm.factor("webRatio") == pytest.approx(0.003)  # Eq 6.I.4
    assert stm.factor("webRatioFcMax") == pytest.approx(40.0)  # I.3.3.1
    assert stm.factor("webAngleMin") == pytest.approx(40.0)  # I.3.3.2
    assert stm.factor("spreadSlope") == pytest.approx(2.0)  # I.3.3
    assert stm.factor("dRegionDepth") == pytest.approx(1.0)  # I.1
    assert stm.covers_general()
    for key in ("betaTension", "betaOther", "minAngle", "webRatio", "betaCCC"):
        assert "Appendix I" in stm.cite(key)


def test_tie_strength_eq_6_i_6():
    assert stm.tie_nominal(1000.0, 420.0) == pytest.approx(420e3)
    # Bonded tendons: Δfp = 420 MPa, capped at fpy.
    assert stm.tie_nominal(0.0, 420.0, 100.0, 1000.0, 1700.0) == pytest.approx(100 * 1420.0)
    assert stm.tie_nominal(0.0, 420.0, 100.0, 1400.0, 1700.0) == pytest.approx(100 * 1700.0)
    # Unbonded: Δfp = 70 MPa.
    assert stm.tie_nominal(0.0, 420.0, 100.0, 1000.0, 1700.0, bonded=False) == pytest.approx(
        100 * 1070.0
    )


def test_strut_with_compression_steel_eq_6_i_5():
    assert stm.strut_nominal(15.0, 1e4, 400.0, 420.0) == pytest.approx(15e4 + 400 * 420)


def test_web_ratio_eq_6_i_4():
    # Ø10 stirrups (2 legs, 157 mm²) at 150 at 90° to a strut at 45°, bs = 300.
    ratio = stm.web_ratio([(157.0, 150.0, 45.0)], 300.0)
    assert ratio == pytest.approx(157 / (300 * 150) * math.sin(math.radians(45)))


# ── the model engine ──


def _deep_beam(**kw) -> StmModel:
    return sm.template("deepBeam", {"span": 3000, "depth": 1500, "load": 1000, **kw})


def test_deep_beam_truss_forces():
    model = _deep_beam()
    solution = sm.solve(model, model.cases[0])
    assert not solution.problems
    z = 1500 - 2 * 75
    # Tie: R a / z = 500 × 1500 / 1350; struts R / sin θ.
    assert solution.forces["T1"] == pytest.approx(500e3 * 1500 / z, rel=1e-6)
    theta = math.atan2(z, 1500)
    assert solution.forces["S2"] == pytest.approx(-500e3 / math.sin(theta), rel=1e-6)
    assert solution.reactions["A"][1] == pytest.approx(500e3)
    assert sm.indeterminacy(model) == 0


def test_deep_beam_checks_and_needed_tie():
    result = sm.check_model(_deep_beam())
    tie = next(m for m in result["members"] if m["id"] == "T1")
    # Ats needed = T / (φ fy) = 555.6e3 / (0.75 × 420).
    assert tie["required"] == pytest.approx(round(555.556e3 / (0.75 * 420)), abs=1)
    assert not result["ok"]  # no bars yet
    model = _deep_beam()
    members = [
        m.model_copy(update={"barArea": 2000.0}) if m.kind == "tie" else m for m in model.members
    ]
    result = sm.check_model(model.model_copy(update={"members": members}))
    assert result["ok"], [c for c in result["checks"] if not c["ok"]]
    nodes = {n["id"]: n for n in result["nodes"]}
    assert nodes["A"]["type"] == "C-C-T" and nodes["A"]["betaN"] == pytest.approx(0.8)
    assert nodes["C"]["type"] == "C-C-C" and nodes["C"]["betaN"] == pytest.approx(1.0)
    strut = next(c for c in result["checks"] if c["name"] == "Strut S2")
    # fce = min(0.85 × 0.60 × 28, 0.85 × 0.80 × 28) (no web steel: βs 0.60), ws 300, bs 300.
    fce = min(0.85 * 0.6 * 28, 0.85 * 0.8 * 28)
    assert strut["capacity"] == pytest.approx(0.75 * fce * 300 * 300 / 1e3, abs=0.01)


def _two_bar(angle: float, kind: str = "tie") -> StmModel:
    """A load hung from two members at ``angle`` to the horizontal."""
    dx = 1000.0
    dy = dx * math.tan(math.radians(angle))
    return StmModel(
        name="hanger",
        thickness=300,
        fc=28,
        fy=420,
        nodes=[
            StmNode(id="A", x=0, y=dy, support="pin"),
            StmNode(id="B", x=2 * dx, y=dy, support="pin"),
            StmNode(id="C", x=dx, y=0),
        ],
        members=[
            StmMember(id="M1", start="A", end="C", kind=kind, width=200, barArea=2000),
            StmMember(id="M2", start="B", end="C", kind="strut", width=200),
        ],
        cases=[StmLoadCase(name="U1", loads=[StmLoad(node="C", fy=-100)])],
    )


def test_strut_in_tension_fails():
    result = sm.check_model(_two_bar(45.0, kind="tie"))
    names = [c["name"] for c in result["checks"] if not c["ok"]]
    assert "Strut M2 in tension" in names


def test_angle_between_strut_and_tie():
    model = StmModel(
        name="angle",
        thickness=300,
        fc=28,
        fy=420,
        nodes=[
            StmNode(id="A", x=0, y=0, support="pin"),
            StmNode(id="B", x=3000, y=0, support="rollerX"),
            StmNode(id="C", x=1500, y=500),
        ],
        members=[
            StmMember(id="T", start="A", end="B", kind="tie", barArea=5000),
            StmMember(id="S1", start="A", end="C", kind="strut", width=400),
            StmMember(id="S2", start="B", end="C", kind="strut", width=400),
        ],
        cases=[StmLoadCase(name="U", loads=[StmLoad(node="C", fy=-200)])],
    )
    result = sm.check_model(model)
    row = next(c for c in result["checks"] if c["name"] == "Angle of strut S1 to tie T at A")
    # atan(500 / 1500) = 18.4° < 25°.
    assert row["capacity"] == pytest.approx(math.degrees(math.atan(1 / 3)), abs=0.01)
    assert not row["ok"]


def test_mechanism_is_a_problem():
    model = _two_bar(45.0).model_copy(
        update={"nodes": [n.model_copy(update={"support": ""}) for n in _two_bar(45.0).nodes]}
    )
    result = sm.check_model(model)
    assert result["problems"] and "mechanism" in result["problems"][0]


def test_indeterminate_warns():
    model = _deep_beam()
    extra = StmMember(id="X", start="A", end="B", kind="tie", barArea=1000)
    result = sm.check_model(model.model_copy(update={"members": [*model.members, extra]}))
    assert any("indeterminate" in w for w in result["warnings"])


def test_bottle_strut_web_steel_sets_beta():
    model = _deep_beam()
    web = [
        StmWebLayer(area=157.0, spacing=150.0, angle=90.0),
        StmWebLayer(area=157.0, spacing=150.0, angle=0.0),
    ]
    result = sm.check_model(model.model_copy(update={"web": web}))
    row = next(c for c in result["checks"] if c["name"] == "Web steel across strut S2")
    assert row["ok"]
    strut = next(c for c in result["checks"] if c["name"] == "Strut S2")
    assert "βs = 0.75" in strut["note"]


def test_web_in_one_direction_below_40_degrees():
    model = _deep_beam(span=1200)  # a steep strut: horizontal bars at a small angle to it
    web = [StmWebLayer(area=157.0, spacing=100.0, angle=90.0)]
    result = sm.check_model(model.model_copy(update={"web": web}))
    row = next(c for c in result["checks"] if c["name"] == "Web steel angle to strut S2")
    assert row["demand"] == pytest.approx(40.0)
    assert not row["ok"]


def test_high_strength_uses_spread_tension():
    model = _deep_beam(fc=50)
    web = [
        StmWebLayer(area=157.0, spacing=150.0, angle=90.0),
        StmWebLayer(area=157.0, spacing=150.0, angle=0.0),
    ]
    result = sm.check_model(model.model_copy(update={"web": web}))
    row = next(c for c in result["checks"] if c["name"] == "Spread tension across strut S2")
    strut = next(m for m in result["members"] if m["id"] == "S2")
    assert row["demand"] == pytest.approx(-strut["force"] / 4, rel=1e-3)  # C / (2 × 2)


def test_hook_anchorage():
    model = _deep_beam()
    nodes = [
        n.model_copy(update={"anchorage": "hook", "anchorLength": 200.0}) if n.id == "A" else n
        for n in model.nodes
    ]
    members = [
        m.model_copy(update={"barArea": 2000.0, "barDiameter": 20.0}) if m.kind == "tie" else m
        for m in model.members
    ]
    result = sm.check_model(model.model_copy(update={"nodes": nodes, "members": members}))
    row = next(c for c in result["checks"] if c["name"] == "Anchorage of tie T1 at A (hooks)")
    assert row["capacity"] == pytest.approx(200.0)
    assert row["demand"] > 200.0


@pytest.mark.parametrize("kind", sorted(sm.TEMPLATES))
def test_templates_solve(kind):
    model = sm.template(kind)
    result = sm.check_model(model)
    assert not result["problems"], result["problems"]
    for member in result["members"]:
        drawn = next(m for m in model.members if m.id == member["id"])
        # The template's kinds follow its forces: ties in tension, struts not.
        assert (member["force"] >= -1e-6) if drawn.kind == "tie" else (member["force"] <= 1e-6)


def test_rpc_handler_round_trip(tmp_path):
    from saengine.rpc import handlers

    made = handlers.strut_and_tie_template("corbel", {"load": 300})
    result = handlers.strut_and_tie(made["model"], None)
    assert result["cases"] and result["checks"]
    assert result["code"]
    bad = handlers.strut_and_tie({"name": "x"}, None)
    assert bad["problems"]
    assert "error" in handlers.strut_and_tie_template("nope", None)


def test_report_section(tmp_path):
    from saengine.library.strut_and_tie import StrutAndTieFile

    file = tmp_path / "strut-and-tie.json"
    assert sm.report_section(file) == {"models": []}
    content = StrutAndTieFile(models=[sm.template("corbel"), _deep_beam()])
    file.write_text(content.model_dump_json(by_alias=True), encoding="utf-8")
    warnings: list[str] = []
    section = sm.report_section(file, warnings)
    assert [m["name"] for m in section["models"]] == ["Corbel", "Deep beam"]
    assert section["models"][1]["members"][0][0] == "T1"
    assert warnings  # the template ties have no bars yet

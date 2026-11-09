"""The rest of the Australian and New Zealand packs (alpha 9 track C18b): AS 3600 torsion (8.3),
punching (9.3) and walls (11.5, 11.6) by their methods' ids, the AS/NZS 1170.2 hill-shape
multiplier Mh (4.4.2) and the dynamic response factor Cdyn (Section 6), the AS 1170.4
earthquake design category by height with the EDC I simple static force, the packs' own clause
references (designClauses) with no inherited clause leaking, and generated buildings under both
packs. The default pack keeps none of these methods.

The values are those of the packs' ``VERIFY.md`` (entries C18b-*).
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

AU, NZ = "australia-as", "newzealand-nzs"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def au():
    loaded = registry.load(AU)
    with code_context.using(loaded):
        yield loaded


@pytest.fixture
def nz():
    loaded = registry.load(NZ)
    with code_context.using(loaded):
        yield loaded


def _beam(fc=32.0, fy=500.0, b=300.0, h=500.0, dia=16.0, cover=35.0):
    from saengine.design.rc import Bar, RcSection, bar_area
    from saengine.library.objects import RectangleProfile

    y = h / 2 - cover - dia / 2
    xs = [-b / 2 + cover + dia / 2, b / 2 - cover - dia / 2]
    bars = [Bar(x, s * y, bar_area(dia), dia) for x in xs for s in (-1, 1)]
    return RcSection(RectangleProfile(xDim=b, yDim=h), tuple(bars), fc, fy)


# ───────────────────────────── methods by id ─────────────────────────────


def test_default_pack_has_none_of_the_methods():
    from saengine.design import moment_punching, simplified_walls, torsion_interaction

    with code_context.using(registry.load("bnbc2020")):
        assert moment_punching.rules() is None
        assert torsion_interaction.rules() is None
        assert simplified_walls.rules() is None


def test_nz_does_not_inherit_the_as3600_methods(nz):
    from saengine.design import moment_punching, simplified_walls, torsion_interaction

    assert moment_punching.rules() is None
    assert torsion_interaction.rules() is None
    assert simplified_walls.rules() is None


def test_as3600_punching_fcv_and_moment_term(au):
    """AS 3600:2018 9.3: fcv = 0.17 (1 + 2/βh) √f'c <= 0.34 √f'c; v = V*/(u d) + M*v/(8 a d²)."""
    from saengine.design import moment_punching

    fcv, shape, cap = moment_punching.strength(32.0, 1.0)
    assert cap == pytest.approx(0.34 * math.sqrt(32.0))
    assert shape == pytest.approx(0.17 * 3 * math.sqrt(32.0))
    assert fcv == pytest.approx(cap)
    fcv4, _, _ = moment_punching.strength(32.0, 4.0)
    assert fcv4 == pytest.approx(0.17 * 1.5 * math.sqrt(32.0))
    v, direct = moment_punching.stress(2400.0, 200.0, (600.0, 600.0), 600e3, 60e6, 0.0)
    assert direct == pytest.approx(600e3 / (2400 * 200))
    assert v == pytest.approx(direct + 60e6 / (8 * 600 * 200 * 200))


def test_as3600_punching_on_a_slab_column(au):
    from saengine.design.punching import Demand, slab_punching

    boundary = [(-4000, -4000), (4000, -4000), (4000, 4000), (-4000, 4000)]
    result = slab_punching(
        (0.0, 0.0), 400.0, 400.0, 0.0, 180.0, boundary, [Demand(400e3, 20e6, 0.0, "U1")], 32.0
    )
    assert result is not None
    fcv = 0.34 * math.sqrt(32.0)
    assert result.vc == pytest.approx(fcv)
    assert result.phi_vc == pytest.approx(0.75 * fcv)
    assert any("fcv" in n for n in result.notes)


def test_as3600_torsion_values(au):
    """AS 3600:2018 8.3: Jt = 0.33 x² y, Tuc = 0.3 Jt √f'c, Tus = fsy.f (Asw/s) 2 At cot θv."""
    from saengine.design import torsion_interaction as ti

    r = ti.rules()
    assert ti.torsion_modulus(300, 500, r) == pytest.approx(0.33 * 300**2 * 500)
    assert ti.cracking_torque(300, 500, 32, r) == pytest.approx(
        0.3 * 0.33 * 300**2 * 500 * math.sqrt(32)
    )
    assert ti.link_torque(0.5, 500, 1e5, r) == pytest.approx(500 * 0.5 * 2 * 1e5 * 1.376)
    assert (r.neglectShare, r.plainInteraction, r.maxCoefficient) == (0.25, 0.5, 0.2)
    assert tuple(r.linkSpacing) == (0.12, 300.0)


def test_as3600_torsion_rows(au):
    from saengine.design import torsion_interaction as ti

    beam = _beam()
    small = ti.torsion_rows(beam, 35.0, (10.0, 2, 150.0), [(1e6, 50e3, 0.0, "U1", "mid")])
    assert len(small) == 1 and small[0]["flag"]  # below 0.25 φTuc: neglected
    big = ti.torsion_rows(beam, 35.0, (10.0, 2, 150.0), [(30e6, 150e3, 0.0, "U1", "end")])
    names = [row["name"] for row in big]
    assert any("web crushing" in n for n in names)
    assert any("closed links" in n for n in names)
    assert any("AS 3600:2018 8.3" in n for n in names)


def test_as3600_simplified_wall_values(au):
    """AS 3600:2018 11.6: Vuc = (0.66 - 0.21 Hw/Lw) √f'c 0.8 Lw tw for Hw/Lw <= 1, else the
    lesser with (0.05 + 0.1/(Hw/Lw - 1)) √f'c, at least 0.17 √f'c."""
    from saengine.design import simplified_walls as sw

    r = sw.rules()
    root = math.sqrt(32.0)
    assert sw.shear_strength(32.0, 3000, 6000, r) == pytest.approx((0.66 - 0.21 * 0.5) * root)
    slender = min((0.66 - 0.21 * 3) * root, (0.05 + 0.1 / 2) * root)
    assert sw.shear_strength(32.0, 9000, 3000, r) == pytest.approx(max(slender, 0.17 * root))
    assert sw.effective_height(3000, 0.8, r) == pytest.approx(2250)
    assert (r.phi, r.strengthShare, r.additionalDivisor, r.slendernessMax) == (
        0.65,
        0.6,
        2500.0,
        30.0,
    )


# ───────────────────────────── loads ─────────────────────────────


def test_hill_shape_multiplier(au):
    """AS/NZS 1170.2:2021 4.4.2: Mh = 1 + H/(3.5 (z + L1)) (1 - |x|/L2), L1 = max(0.36 Lu, 0.4 H),
    L2 = 4 L1; 1 + 0.71 (1 - |x|/L2) from H/(2Lu) = 0.45; 1 below 0.05."""
    from saengine.fem import wind_speed_factors as wsf
    from saengine.fem.loads import _TOPOGRAPHY, Topography

    def mh(h, lu, x, z, feature="hill", downwind=False):
        token = _TOPOGRAPHY.set(Topography(feature, h, lu, x, downwind))
        try:
            return wsf.hill_shape_factor(z)["k3"]
        finally:
            _TOPOGRAPHY.reset(token)

    assert mh(50, 100, 0, 10) == pytest.approx(1 + 50 / (3.5 * (10 + 36)))
    assert mh(50, 100, 72, 10) == pytest.approx(1 + 50 / (3.5 * 46) * (1 - 72 / 144))
    assert mh(50, 50, 0, 10) == pytest.approx(1.71)  # H/(2Lu) = 0.5
    assert mh(5, 100, 0, 10) == pytest.approx(1.0)  # H/(2Lu) = 0.025
    # Downwind of an escarpment L2 = 10 L1.
    assert mh(50, 100, 200, 10, "escarpment", True) == pytest.approx(
        1 + 50 / (3.5 * 46) * (1 - 200 / 360)
    )


def test_dynamic_response_factor_form(au):
    """AS/NZS 1170.2 6.2.2: Cdyn = [1 + 2 Ih √(gv² Bs + Hs gR² S Et/ζ)] / (1 + 2 gv Ih)."""
    from saengine.fem import gust_response as gr

    r = gr.rules()
    assert gr.dynamic_form(r)
    h, b, n, vdes = 120.0, 30.0, 0.4, 50.0
    terms = gr._dynamic_response(r, h, b, n, {"Vz": vdes}, "TC3", 0.02)
    ih = 0.166 + (0.150 - 0.166) * (120 - 100) / 50
    assert terms["Ih"] == pytest.approx(ih)
    vh = vdes / (1 + 3.7 * ih)
    lh = 85 * (h / 10) ** 0.25
    bs = 1 / (1 + math.sqrt(0.26 * h**2 + 0.46 * b**2) / lh)
    s = 1 / ((1 + 3.5 * n * h / vh) * (1 + 4 * n * b / vh))
    nn = n * lh / vh
    et = math.pi * nn / (1 + 70.8 * nn**2) ** 0.8333
    g = math.sqrt(2 * math.log(600 * n))
    expected = (1 + 2 * ih * math.sqrt(3.7**2 * bs + g**2 * s * et / 0.02)) / (1 + 2 * 3.7 * ih)
    assert terms["G"] == pytest.approx(expected)
    assert gr.level_ratio(30.0, terms["G"], "TC3") == pytest.approx(terms["G"])
    assert gr.applies(h, b, 0.4) and not gr.applies(h, b, 1.5)


def test_earthquake_design_category_by_height(au):
    """AS 1170.4 Table 2.1 (slots B/C/D = EDC I/II/III): IL2 to 12 m I, to 50 m II, above III."""
    from saengine.fem.seismic_design import seismic_design_category

    assert seismic_design_category(3, "Ce", "II") == "C"  # no height: the zone rows
    assert seismic_design_category(3, "Ce", "II", height=10.0) == "B"
    assert seismic_design_category(3, "Ce", "II", height=30.0) == "C"
    assert seismic_design_category(3, "Ce", "II", height=60.0) == "D"
    assert seismic_design_category(3, "Ce", "IV", height=10.0) == "C"
    rules = code_context.table("seismic").designCategories
    assert rules.simpleStatic == {"B": 0.1} and rules.dynamicRequired == ["D"]


def test_nz_has_no_category_by_height(nz):
    from saengine.fem.seismic_design import seismic_design_category

    rules = code_context.table("seismic").designCategories
    assert not rules.byHeight and not rules.simpleStatic and not rules.dynamicRequired
    assert seismic_design_category(3, "C", "II", height=10.0) == seismic_design_category(
        3, "C", "II"
    )


# ───────────────────────────── clause references ─────────────────────────────


def test_clauses_from_the_packs_never_inherited():
    from saengine.design.clauses import clause, own_text

    with code_context.using(registry.load(AU)):
        assert clause("check", "torsion") == "AS 3600:2018 8.3"
        assert clause("check", "accidentalTorsion") == "AS 1170.4 6.6"
        assert clause("punching", "punching") == "AS 3600:2018 9.3"
        assert own_text("check", "columnShear") == ""
        assert "BNBC" not in clause("check", "columnShear")
        # C18c gives slender columns in the pack itself (AS 3600 10.3-10.5).
        assert clause("slender", "chapter") == "AS 3600:2018 10.3-10.5"
        # A group the pack does not give is the parent's, named after it.
        assert clause("stairs", "spans").startswith("BNBC")
        assert own_text("stairs", "spans") == ""
    with code_context.using(registry.load(NZ)):
        assert clause("check", "torsion") == "NZS 3101:2006 7.6"
        assert clause("check", "accidentalTorsion") == "NZS 1170.5 5.3.1.2"
        assert clause("punching", "punching") == "NZS 3101:2006 12.7"


# ───────────────────────────── generated buildings ─────────────────────────────


def _derive(pack_id, stories, ground=3500, typical=3200):
    from saengine.fem.derive import derive_fem
    from saengine.library import FloorPlan, MaterialLibrary, ObjectLibrary
    from saengine.library.bim import generate
    from saengine.library.generator import generate_building
    from saengine.library.settings import ProjectSettings

    spec = {
        "name": "Frame",
        "gridsX": [5000, 5000],
        "gridsY": [4000, 4000],
        "storyCount": stories,
        "groundHeight": ground,
        "typicalHeight": typical,
        "codePack": pack_id,
    }
    result = generate_building(spec)
    settings = ProjectSettings.model_validate(result["settings"])
    building = generate(FloorPlan.model_validate(result["floorPlan"]), "s")
    with code_context.using(code_context.pack_for(settings)):
        return derive_fem(
            building,
            ObjectLibrary.model_validate(result["objects"]),
            MaterialLibrary.model_validate(result["materials"]),
            settings,
            {"bim": "abc"},
        )


def test_low_building_under_as1170_4_takes_the_simple_static_force():
    d = _derive(AU, 2)  # hn = 6.7 m, IL2: EDC I
    assert d.summary["designCategoryByHeight"]["category"] == "B"
    assert d.summary["seismic"]["EX"]["Sa_g"] == pytest.approx(0.1)
    assert any("Fi = 0.1 Wi" in n for n in d.notes)


def test_mid_rise_building_under_as1170_4_keeps_the_static_method():
    d = _derive(AU, 5)  # hn = 16.3 m: EDC II
    assert d.summary["designCategoryByHeight"]["category"] == "C"
    assert d.summary["seismic"]["EX"]["Sa_g"] != pytest.approx(0.1)


def test_nz_building_has_no_height_category():
    d = _derive(NZ, 2)
    assert "designCategoryByHeight" not in d.summary
    assert d.summary["seismic"]["EX"]["Sa_g"] > 0


@pytest.mark.parametrize("pack_id", [AU, NZ])
def test_generated_building_designed_with_the_pack_methods(tmp_path, pack_id):
    import json
    from pathlib import Path

    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    spec = {
        "name": "Concrete",
        "gridsX": [5000],
        "gridsY": [4000],
        "storyCount": 1,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": pack_id,
        "lateralSizing": "gravity",
    }
    root = Path(create_building(spec, tmp_path)["root"])
    run_all(root, steps=["derive", "analysis"])
    with code_context.project(root):
        proposal = handlers.design_proposal(
            str(root / "08 FEM/model.results"), str(root / "08 FEM/model.osmodel")
        )
    objects_path, bim_path = root / "04 Objects/objects.json", root / "06 BIM/bim.json"
    applied = handlers.design_apply_proposal(
        objects_path.read_text(encoding="utf-8"), bim_path.read_text(encoding="utf-8"), proposal
    )
    objects_path.write_text(applied["objectsText"], encoding="utf-8")
    bim_path.write_text(applied["bimText"], encoding="utf-8")
    result = run_all(root, steps=["derive", "analysis", "design"])
    assert result.steps[-1].status in ("ok", "warning"), [s.message for s in result.steps]
    report = json.loads(
        (root / "08 FEM/model.results/design-report.json").read_text(encoding="utf-8")
    )["result"]
    # The method's torsion line (the basis line before it may name the torsion clause too).
    torsion_line = next(line for line in report["method"] if line.startswith("Beam torsion"))
    if pack_id == AU:
        assert "Tuc" in torsion_line
    else:
        assert "Tuc" not in torsion_line
    text = json.dumps(report, ensure_ascii=False)
    if pack_id == AU:
        assert "BNBC 2020 Part 6 Sec 6.4.4" not in text  # the torsion clause is the pack's

"""The legacy British Standards pack (``bs8110``, alpha 9 track C10): BS 8110-1:1997 concrete,
BS 6399-1/-2/-3 loads and BS 5950-1:2000 steel values pinned to their clauses, the generic
methods the pack picks, no earthquake (not covered), and a small generated building derived and
designed under it.

The values are those of the pack's ``VERIFY.md``; a test failing here after a value is changed
there says the pack and its verification list disagree.
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

PACK = "bs8110"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def pack():
    loaded = registry.load(PACK)
    with code_context.using(loaded):
        yield loaded


def _beam(fc=30.0, fy=460.0, b=300.0, h=500.0, bottom=3, top=2, dia=16.0, cover=35.0):
    from saengine.design.rc import Bar, RcSection, bar_area
    from saengine.library.objects import RectangleProfile

    y = h / 2 - cover - dia / 2
    xs = lambda n: [
        (-b / 2 + cover + dia / 2) + k * (b - 2 * cover - dia) / (n - 1) for k in range(n)
    ]
    bars = [Bar(x, -y, bar_area(dia), dia) for x in xs(bottom)] + [
        Bar(x, y, bar_area(dia), dia) for x in xs(top)
    ]
    return RcSection(RectangleProfile(xDim=b, yDim=h), tuple(bars), fc, fy)


# ───────────────────────────── the pack ─────────────────────────────


def test_pack_is_built_in_valid_and_picks_the_methods(pack):
    assert PACK in [p.id for p in registry.list_packs()]
    found = registry.validate(registry.BUILTIN_DIR / PACK)
    assert not [p for p in found.problems if p.severity == "error"], found.problems
    from saengine.design import method_selection

    picked = method_selection.summary()
    assert picked["ultimate"] == "partialFactors"
    assert picked["shear"] == "tabulatedStress"
    assert picked["deflection"] == "spanDepthModification"
    assert picked["cracking"] == "strainSpacing"
    # Not covered here: torsion and the seismic detailing (no BS earthquake rules).
    assert picked["torsion"] is None and picked["seismic"] is None


def test_no_earthquake_and_wind_by_the_standard_method(pack):
    # Not covered: Z = 0 everywhere (no earthquake cases).
    assert dict(pack.table("zoneCoefficients").zones) == {0: 0.0}
    towns = pack.table("locations").locations
    assert (towns["london"].zone, towns["london"].windSpeed) == (0, 21.5)
    from saengine.fem import wind_speed_factors as wsf

    # BS 6399-2: Ve = Vb Sa Sd Ss Sp Sb, qs = 0.613 Ve², the overall load × 0.85 (2.1.3.6).
    f = wsf.factors(10.0, 21.5, "country10", 1.0)
    assert f["k2"] == pytest.approx(1.73)
    assert f["Vz"] == pytest.approx(21.5 * 1.73)
    assert f["pz"] == pytest.approx(0.613 * (21.5 * 1.73) ** 2 / 1000)
    assert f["pd"] == pytest.approx(0.85 * f["pz"])
    # Table 4, town 10 km at He 20 m.
    assert wsf.height_factor(20.0, "town10") == pytest.approx(1.81)


def test_imposed_loads_reduction_and_combinations(pack):
    uses = pack.table("areaLoads").uses
    assert (uses["office"].live, uses["office"].concentrated) == (2.5, 2.7)  # BS 6399-1 Table 1
    assert (uses["residential"].live, uses["roof"].live) == (1.5, 0.6)
    rows = pack.table("liveReduction").floorCount.rows
    assert [list(r) for r in rows][:5] == [[1, 0.0], [2, 0.1], [3, 0.2], [4, 0.3], [10, 0.4]]
    combos = {c.name: dict(c.factors) for c in pack.table("combinations").strength}
    assert combos["1.4G + 1.6Q"]["D"] == 1.4 and combos["1.4G + 1.6Q"]["L"] == 1.6
    assert combos["1.2(G + Q + W)"] == {"D": 1.2, "F": 1.2, "L": 1.2, "Lr": 1.2, "W": 1.2}
    assert combos["1.0G + 1.4W"] == {"D": 1.0, "W": 1.4}
    assert not any("E" in f for f in combos.values())  # no earthquake combinations


# ───────────────────────────── concrete ─────────────────────────────


def test_design_strengths_block_and_eccentricity(pack):
    from saengine.design import design_strength as ds
    from saengine.design import limit_state_rows

    u = ds.rules()
    assert (u.gammaC, u.gammaS) == (1.5, 1.05)  # Table 2.2
    # The block 0.45 fcu over 0.9 x (3.4.4.1): η α fcu / γc = 0.45 fcu.
    p = ds.properties(30.0)
    assert p.eta * ds.fcd(30.0) == pytest.approx(0.45 * 30.0, rel=1e-5) and p.lam == 0.9
    # x <= 0.5 d (3.4.4.4, K' = 0.156): 0.405 × 0.5 × (1 - 0.225) = 0.157.
    assert limit_state_rows.neutral_axis_limit(460.0) == pytest.approx(0.5)
    # Ec = 20 + 0.2 fcu kN/mm² (BS 8110-2 7.2).
    assert p.ecm == pytest.approx(26_000.0)
    # emin = 0.05 h at most 20 mm (3.8.2.4).
    assert ds.eccentricity(300.0) == pytest.approx(15.0)
    assert ds.eccentricity(600.0) == pytest.approx(20.0)


def test_shear_vc_with_the_depth_and_grade_factors(pack):
    from saengine.design import tabulated_shear as ts

    # Table 3.8: vc = 0.79 (100 As/bd)^1/3 (400/d)^1/4 / 1.25, × (fcu/25)^1/3.
    def vc(p, d, fcu):
        return 0.79 * p ** (1 / 3) * max(1.0, (400 / d) ** 0.25) * (fcu / 25) ** (1 / 3) / 1.25

    assert ts.tau_c(25.0, 1.0, d=400.0) == pytest.approx(vc(1.0, 400, 25), abs=1e-3)
    assert ts.tau_c(30.0, 0.5, d=200.0) == pytest.approx(vc(0.5, 200, 30), abs=1e-3)
    assert ts.tau_c(40.0, 3.0, d=600.0) == pytest.approx(vc(3.0, 600, 40), abs=1e-3)
    assert ts.depth_factor(125.0) == pytest.approx((400 / 125) ** 0.25)
    assert ts.tau_c_max(30.0) == pytest.approx(4.38)  # 0.8 √fcu <= 5
    s = ts.beam_shear(_beam(), 8.0, 2, 150.0)
    d = 500 - 35 - 8
    pt = 100 * 2 * math.pi * 64 / (300 * d)  # the face with fewer bars
    # Linear between the table's rows (0.25 and 0.5 %): within 1.5 % of the formula.
    assert s.vc == pytest.approx(vc(pt, d, 30) * 300 * d, rel=1.5e-2)
    assert s.vc < vc(pt, d, 30) * 300 * d  # the chord lies below the cube root: safe side


def test_span_depth_cover_bond_and_columns(pack):
    from saengine.design import additional_moment, member_limits, span_depth_factors

    # Table 3.10 with fs = 2/3 fy, M/bd² = pt/100 × 0.95 fy × 0.9 (SAEngine practice).
    fs = 0.667 * 460
    m_bd2 = 1.0 / 100 * 460 / 1.05 * 0.9
    kt = min(2.0, 0.55 + (477 - fs) / (120 * (0.9 + m_bd2)))
    assert span_depth_factors.tension_factor(1.0, 460.0) == pytest.approx(kt)
    assert span_depth_factors.compression_factor(1.0) == pytest.approx(1 + 1 / 4)
    ratio, _ = span_depth_factors.allowed_ratio(6000.0, "simple", 1.0, 0.0, 460.0)
    assert ratio == pytest.approx(20 * kt)
    # Table 3.3: moderate 35 mm, 30 mm at C40 and above.
    assert member_limits.nominal_cover(16.0, "beam", 35.0) == 35.0
    assert member_limits.nominal_cover(16.0, "beam", 40.0) == 30.0
    # 3.12.8.4: l = 0.95 fy φ / (4 × 0.5 √fcu) for type 2 deformed bars in tension.
    ld = member_limits.development_length(20.0, 460.0, 30.0)
    assert ld == pytest.approx(20 * 460 / 1.05 / (4 * 0.5 * math.sqrt(30)), rel=1e-3)
    # 3.8.1.3 braced 15 / unbraced 10; 3.8.3 Madd = N h (le/h)² / 2000 K.
    s = additional_moment.rules().slenderness
    assert (s.limit, s.unbracedLimit, s.divisor) == (15, 10, 2000)
    assert additional_moment.rules().biaxial.method == "surface"


def test_two_way_panel_coefficients(pack):
    t = pack.table("concreteMethods").twoWaySlabs
    interior = t.cases["2,2"]
    assert interior.shortNegative[0] == 0.031 and interior.shortPositive[-1] == 0.048
    assert t.cases["0,0"].shortPositive[0] == 0.055  # Table 3.14 case 9
    assert t.simpleShort[-1] == 0.118 and t.simpleLong[-1] == 0.029  # Table 3.13


def test_the_default_pack_keeps_its_methods():
    from saengine.design import tabulated_shear

    with code_context.using(registry.load("bnbc2020")):
        assert tabulated_shear.rules() is None


# ───────────────────────────── steel ─────────────────────────────


def test_bs5950_strut_curves_ltb_and_py(pack):
    from saengine.design.steel import limit_state as ls
    from saengine.design.steel.members import Steel
    from saengine.design.steel.properties import i_shape

    steel = Steel(275.0, 410.0, 205_000.0)
    # Annex C: pc by Perry-Robertson on curve b (a = 3.5) at λ = 100 (py 275): 170 MPa.
    lam = 100.0
    pe = math.pi**2 * 205_000 / lam**2
    lam0 = 0.2 * math.sqrt(math.pi**2 * 205_000 / 275)
    eta = 0.0035 * (lam - lam0)
    phi = (275 + (eta + 1) * pe) / 2
    pc = pe * 275 / (phi + math.sqrt(phi**2 - pe * 275))
    rel = math.sqrt(275 / pe)
    alpha = ls.imperfection(3.5, True, 205_000.0, 275.0)
    assert ls.chi(rel, alpha, 0.2) * 275 == pytest.approx(pc, rel=1e-9)
    assert pc == pytest.approx(141, abs=1.0)  # Table 24 (b) at λ 100, py 275: about 141
    # Table 9: py by the flange thickness.
    thick = i_shape(400.0, 300.0, 25.0, 15.0)
    assert ls.design_steel(thick, steel).fy == 265.0
    assert ls.design_steel(i_shape(300.0, 150.0, 10.0, 7.0), steel).fy == 275.0
    # 4.2.3: Pv = 0.6 py Av.
    v = ls.shear_capacity(i_shape(300.0, 150.0, 10.0, 7.0), steel, "y")
    assert v.design == pytest.approx(0.6 * 275 * 300 * 7.0, rel=0.05)


# ──────────────────────── settings and a generated building ────────────────────────


def test_settings_derive_no_earthquake():
    from saengine.library.settings import check, default_project_settings, derived

    settings = default_project_settings("United Kingdom", code_pack=PACK)
    assert settings.codePack == PACK
    assert (settings.site.location, settings.wind.exposure) == ("london", "country10")
    names = {c.name for c in settings.combinations}
    assert "1.4G + 1.6Q" in names and any(n.startswith("1.2(G + Q + ") for n in names), names
    assert not [p for p in check(settings) if p.startswith("codePack")]
    with code_context.using(code_context.pack_for(settings)):
        values = derived(settings)
    assert (values["Z"], values["windSpeed"]) == (0.0, 21.5)


def test_generated_building_derives_wind_and_no_earthquake():
    from saengine.fem.derive import derive_fem
    from saengine.library import FloorPlan, MaterialLibrary, ObjectLibrary
    from saengine.library.bim import generate
    from saengine.library.generator import generate_building
    from saengine.library.settings import ProjectSettings

    spec = {
        "name": "BS frame",
        "gridsX": [5000, 5000],
        "gridsY": [4000, 4000],
        "storyCount": 3,
        "groundHeight": 3500,
        "typicalHeight": 3200,
        "codePack": PACK,
    }
    result = generate_building(spec)
    assert result["settings"]["codePack"] == PACK
    settings = ProjectSettings.model_validate(result["settings"])
    building = generate(FloorPlan.model_validate(result["floorPlan"]), "s")
    d = derive_fem(
        building,
        ObjectLibrary.model_validate(result["objects"]),
        MaterialLibrary.model_validate(result["materials"]),
        settings,
        {"bim": "abc"},
    )
    assert d.summary.get("lateralMissing") == ["Z"]  # no earthquake: not covered
    wx = sum(
        n["forces"][0]
        for p in d.project["load_patterns"]
        if p["name"] == "WX"
        for n in p["nodal_loads"]
    )
    assert wx > 0


def test_generated_building_is_designed_under_the_pack(tmp_path):
    import json
    from pathlib import Path

    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

    spec = {
        "name": "BS Concrete",
        "gridsX": [5000],
        "gridsY": [4000],
        "storyCount": 1,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": PACK,
        "lateralSizing": "gravity",
    }
    root = Path(create_building(spec, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    # Design Reinforcement (its verification takes the pack's checks), applied, then the checks.
    from saengine.rpc import handlers

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
    assert any("BS 8110" in line for line in report["method"]), report["method"]
    names = {c["name"] for e in report["elements"] for c in e.get("checks", [])}
    assert any(n.startswith("Deflection: span / effective depth") for n in names), sorted(names)

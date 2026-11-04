"""The Australian and New Zealand packs (``australia-as`` and ``newzealand-nzs``, alpha 9 track
C18): AS/NZS 1170 loads, AS 1170.4 and NZS 1170.5 earthquake actions by the generic method
``shapeFactors``, AS 3600 and NZS 3101 strength design (the pack's stress block, φ by kuo, the
axial cap, vc by ρw), AS 4100 members (αc with αb, αm αs), values pinned to their clauses, and a
small generated building derived and designed under each.

The values are those of the packs' ``VERIFY.md``; a test failing here after a value is changed
there says the pack and its verification list disagree.
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

AU, NZ = "australia-as", "newzealand-nzs"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
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


def _beam(fc=32.0, fy=500.0, b=300.0, h=500.0, bottom=3, top=2, dia=16.0, cover=35.0):
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


# ───────────────────────────── the packs ─────────────────────────────


@pytest.mark.parametrize("pack_id", [AU, NZ])
def test_packs_are_built_in_and_valid(pack_id):
    assert pack_id in [p.id for p in registry.list_packs()]
    found = registry.validate(registry.BUILTIN_DIR / pack_id)
    assert not [p for p in found.problems if p.severity == "error"], found.problems


def test_combinations_and_imposed_actions(au):
    combos = {c.name: dict(c.factors) for c in au.table("combinations").strength}
    assert combos["1.35G"]["D"] == 1.35  # AS/NZS 1170.0 4.2.2(a)
    assert (combos["1.2G + 1.5Q"]["D"], combos["1.2G + 1.5Q"]["L"]) == (1.2, 1.5)
    assert combos["1.2G + ψc Q + Wu"]["L"] == 0.4 and combos["1.2G + ψc Q + Wu"]["Lr"] == 0.0
    assert combos["G + ψE Q + Eu"] == {"D": 1.0, "F": 1.0, "L": 0.3, "E": 1.0}
    uses = au.table("areaLoads").uses
    assert (uses["office"].live, uses["office"].concentrated) == (3.0, 2.7)  # Table 3.1 B
    assert (uses["residential"].live, uses["roof"].live) == (1.5, 0.25)
    from saengine.design import live_reduction

    assert live_reduction is not None
    lr = au.table("liveReduction")
    assert (lr.constant, lr.coefficient, lr.minFloors) == (0.3, 3.0, 0.5)  # 3.4.2


def test_wind_by_region_speed_and_multipliers(au):
    from saengine.fem import wind_speed_factors as wsf

    # Region A, IL2 (1/500): VR = V500 = 45 m/s; TC3 Mz,cat at 10 m 0.83, 30 m 1.00.
    f = wsf.factors(10.0, 45.0, "TC3", 1.0)
    assert (f["k1"], f["k2"]) == (pytest.approx(1.0), pytest.approx(0.83))
    assert f["pz"] == pytest.approx(0.6 * (45 * 0.83) ** 2 / 1000)
    assert wsf.height_factor(30.0, "TC3") == pytest.approx(1.00)
    # IL4 (1/2500) in region C: V2500 / V500 = 74 / 66.
    assert wsf.risk_coefficient(66.0, 1.1) == pytest.approx(74 / 66, abs=1e-4)
    assert wsf.risk_coefficient(45.0, 0.9) == pytest.approx(41 / 45, abs=1e-4)  # IL1, A


def test_as1170_4_spectral_shape_and_design_coefficient(au):
    from saengine.fem import loads as fl

    # Table 6.4, class Ce: 1.25/T <= 3.68 to 1.5 s, 1.874/T² beyond.
    assert fl.normalized_spectrum(0.5, "Ce") == pytest.approx(2.5)
    assert fl.normalized_spectrum(0.2, "Ce") == pytest.approx(3.68)
    assert fl.normalized_spectrum(2.0, "Ce") == pytest.approx(1.874 / 4)
    assert fl.normalized_spectrum(0.05, "De") == pytest.approx(1.1 + 25.8 * 0.05)  # modal ramp
    assert fl.normalized_spectrum(0.05, "De", static=True) == pytest.approx(3.68)  # plateau
    # 6.2.2: V/W = kp Z Ch(T1) Sp/μ; Sydney Z 0.08, IL2, OMRF μ 2, Sp 0.77.
    assert fl.design_acceleration(0.5, "Ce", 0.08, 1.0, 2.0) == pytest.approx(0.08 * 2.5 * 0.77 / 2)
    # kp Z at least 0.08 (Hobart Z 0.03).
    assert fl.design_acceleration(0.5, "Ce", 0.03, 1.0, 3.0) == pytest.approx(0.08 * 2.5 * 0.67 / 3)
    # 6.2.3: T1 = 1.25 kt hn^0.75, kt 0.075 for concrete moment frames.
    assert fl.approximate_period(20.0, "rcOmf") == pytest.approx(1.25 * 0.075 * 20**0.75)
    towns = au.table("locations").locations
    zones = au.table("zoneCoefficients").zones
    assert zones[towns["newcastle"].zone] == 0.11 and towns["brisbane"].windSpeed == 57.0


def test_nzs1170_5_spectrum_ductility_and_least_values(nz):
    from saengine.fem import loads as fl
    from saengine.fem import spectra

    # Table 3.1 class C: 2.0 (0.5/T)^0.75 from 0.3 to 1.5 s; 1.32/T to 3 s.
    assert fl.normalized_spectrum(1.0, "C") == pytest.approx(2.0 * 0.5**0.75)
    assert fl.normalized_spectrum(2.0, "C") == pytest.approx(0.66)
    assert fl.normalized_spectrum(0.0, "C") == pytest.approx(1.33)
    rule = nz.table("seismic").designSpectrum.shapeFactors
    # 4.4.2: Sp = 1.3 - 0.3 μ below μ 2, 0.7 above; 5.2.1.1 kμ.
    assert spectra.performance_factor(1.25, rule) == pytest.approx(0.925)
    assert spectra.performance_factor(4.0, rule) == pytest.approx(0.7)
    assert spectra.ductility_factor(0.35, 3.0, "C", rule) == pytest.approx(2 * 0.4 / 0.7 + 1)
    assert spectra.ductility_factor(1.2, 3.0, "C", rule) == 3.0
    assert spectra.ductility_factor(0.5, 3.0, "E", rule) == pytest.approx(1.5 * 0.5 + 1.5)
    # Wellington Z 0.40, IL2, μ 3 at T1 = 1.0 s: Cd = Ch Z R Sp / kμ.
    cd = fl.design_acceleration(1.0, "C", 0.40, 1.0, 3.0)
    assert cd == pytest.approx(2.0 * 0.5**0.75 * 0.40 * 0.7 / 3.0)
    # The least Cd: (Z/20 + 0.02) Ru, at least 0.03 Ru (μ 6, long period).
    assert fl.design_acceleration(4.0, "C", 0.40, 1.0, 6.0) == pytest.approx(0.40 / 20 + 0.02)
    assert fl.design_acceleration(4.0, "C", 0.13, 1.0, 6.0) == pytest.approx(0.03)
    # Z R at most 0.7 (IL4, R 1.8, Wellington: 0.72 -> 0.7).
    assert spectra.hazard_product(0.40, 1.8, rule) == pytest.approx(0.7)
    # Near fault N(T, D) for D = 2 km at T 3 s.
    near = rule.model_copy(update={"faultDistance": 2.0})
    assert spectra.near_fault_factor(3.0, near) == pytest.approx(1.36)
    assert spectra.near_fault_factor(3.0, rule) == 1.0
    lf = nz.table("seismic").lateralForce
    assert lf.distribution == "linear" and lf.topForce.maxShare == 0.08  # 6.2.1.3


# ───────────────────────────── concrete ─────────────────────────────


def test_as3600_block_phi_and_shear(au):
    from saengine.design import rc

    # 8.1.3: α2 = 0.85 - 0.0015 f'c, γ = 0.97 - 0.0025 f'c (at most 0.85); 10.6.2.2 α1.
    assert rc.alpha1(50.0) == pytest.approx(0.775) and rc.beta1(50.0) == pytest.approx(0.845)
    assert rc.beta1(32.0) == pytest.approx(0.85) and rc.squash_share(50.0) == pytest.approx(0.85)
    assert rc.squash_share(60.0) == pytest.approx(0.82)
    # Table 2.2.2: φ = 1.24 - 13 kuo / 12 within 0.65-0.85.
    eps_t = 0.003 * (1 - 0.45) / 0.45  # kuo = 0.45
    assert rc.phi_strength(eps_t, 500.0) == pytest.approx(1.24 - 13 * 0.45 / 12, rel=1e-6)
    assert rc.phi_strength(0.01, 500.0) == pytest.approx(0.85)
    assert rc.phi_strength(0.001, 500.0) == pytest.approx(0.65)
    # 8.2.4.3: kv = 200 / (1000 + 1.3 dv) <= 0.10 without the least links; φ 0.75.
    s = rc.shear(_beam(), None, 2, None)
    d = s.d
    dv = max(0.9 * d, 0.72 * 500)
    kv = min(200 / (1000 + 1.3 * dv), 0.10)
    assert s.vc == pytest.approx(0.75 * kv * math.sqrt(32) * 300 * dv, rel=1e-3)
    with_links = rc.shear(_beam(), 10.0, 2, 150.0)
    assert with_links.vc == pytest.approx(0.75 * 0.15 * math.sqrt(32) * 300 * dv, rel=1e-3)


def test_nzs3101_phi_cap_and_vc(nz):
    from saengine.design import rc

    # 2.3.2.2: φ 0.85 whatever the strain; 10.3.4.2: N*max = 0.85 φ N0.
    assert rc.phi_strength(0.001, 500.0) == pytest.approx(0.85)
    section = _beam(fc=40.0)
    assert section.phi_pn_max == pytest.approx(0.85 * 0.85 * section.p0)
    # 7.4.2.7: α1 0.85 to 55 MPa, β1 = 0.85 - 0.008 (f'c - 30).
    assert rc.alpha1(65.0) == pytest.approx(0.81) and rc.beta1(40.0) == pytest.approx(0.77)
    # 9.3.9.3.4: vb = (0.07 + 10 ρw) √f'c within 0.08 and 0.2 √f'c.
    s = rc.shear(section, 10.0, 2, 150.0)
    share = min(max(0.07 + 10 * s.rho_w, 0.08), 0.2)
    assert s.vc == pytest.approx(share * math.sqrt(40.0) * 300 * s.d)
    assert s.phi_vn == pytest.approx(0.75 * (s.vc + s.vs))


def test_the_default_pack_keeps_aci_block_and_phi():
    from saengine.design import rc

    with code_context.using(registry.load("bnbc2020")):
        assert rc.alpha1(40.0) == 0.85 and rc.beta1(40.0) == pytest.approx(0.85 - 0.05 * 12 / 7)
        assert rc.squash_share(40.0) == 0.85
        eps_ty = 420 / 200000
        assert rc.phi_strength(eps_ty + 0.0015, 420.0) == pytest.approx(0.65 + 0.25 * 0.5)
        section = _beam(fc=28.0, fy=420.0)
        assert section.phi_pn_max == pytest.approx(0.80 * 0.65 * section.p0)


# ───────────────────────────── steel ─────────────────────────────


def test_as4100_alpha_c_and_lateral_torsional_buckling(au):
    from saengine.design.steel import limit_state as ls
    from saengine.design.steel.members import Steel
    from saengine.design.steel.properties import i_shape

    rule = au.table("steelLimitState").compression.slendernessReduction
    # 6.3.3 at λn = 100 on αb = 0 (hot-rolled UB/UC): about 0.54 (Table 6.3.3(3)).
    lam_n = 100.0
    alpha_a = 2100 * (lam_n - 13.5) / (lam_n**2 - 15.3 * lam_n + 2050)
    lam = lam_n
    eta = 0.00326 * (lam - 13.5)
    xi = ((lam / 90) ** 2 + 1 + eta) / (2 * (lam / 90) ** 2)
    expected = xi * (1 - math.sqrt(1 - (90 / (xi * lam)) ** 2))
    assert alpha_a > 0
    assert ls.alpha_c(100.0, 250.0, 1.0, "0", rule) == pytest.approx(expected)
    assert expected == pytest.approx(0.54, abs=0.01)
    assert (
        ls.alpha_c(100.0, 250.0, 1.0, "-0.5", rule)
        > expected
        > ls.alpha_c(100.0, 250.0, 1.0, "0.5", rule)
    )
    # 5.6.1.1: Mb = αm αs Ms with αs = 0.6 [√((Ms/Mo)² + 3) - Ms/Mo].
    steel = Steel(300.0, 440.0, 200_000.0)
    shape = i_shape(400.0, 180.0, 12.0, 8.0)
    flex = ls.flexure_major(shape, steel, 6000.0, 1.0)
    mo = ls.critical_moment(shape, 200_000.0, 80_000.0, 6000.0, 1.0)
    ms = flex.section * (1 / 0.9)
    alpha_s = 0.6 * (math.sqrt((ms / mo) ** 2 + 3) - ms / mo)
    assert flex.cap.design == pytest.approx(min(alpha_s * ms, ms) * 0.9, rel=1e-6)


# ──────────────────────── settings and generated buildings ────────────────────────


@pytest.mark.parametrize(
    ("pack_id", "town", "site", "exposure"),
    [(AU, "sydney", "Ce", "TC3"), (NZ, "wellington", "C", "TC3")],
)
def test_settings_derive_the_towns_values(pack_id, town, site, exposure):
    from saengine.library.settings import check, default_project_settings, derived

    settings = default_project_settings("Project", code_pack=pack_id)
    assert settings.codePack == pack_id
    assert (settings.site.location, settings.site.siteClass) == (town, site)
    assert settings.wind.exposure == exposure
    assert not [p for p in check(settings) if p.startswith("codePack")]
    with code_context.using(code_context.pack_for(settings)):
        values = derived(settings)
    expected = {AU: (0.08, 45.0), NZ: (0.40, 51.0)}[pack_id]
    assert (float(values["Z"]), values["windSpeed"]) == pytest.approx(expected)


@pytest.mark.parametrize("pack_id", [AU, NZ])
def test_generated_building_derives_wind_and_earthquake(pack_id):
    from saengine.fem.derive import derive_fem
    from saengine.library import FloorPlan, MaterialLibrary, ObjectLibrary
    from saengine.library.bim import generate
    from saengine.library.generator import generate_building
    from saengine.library.settings import ProjectSettings

    spec = {
        "name": "Frame",
        "gridsX": [5000, 5000],
        "gridsY": [4000, 4000],
        "storyCount": 3,
        "groundHeight": 3500,
        "typicalHeight": 3200,
        "codePack": pack_id,
    }
    result = generate_building(spec)
    settings = ProjectSettings.model_validate(result["settings"])
    assert settings.codePack == pack_id
    building = generate(FloorPlan.model_validate(result["floorPlan"]), "s")
    with code_context.using(code_context.pack_for(settings)):
        d = derive_fem(
            building,
            ObjectLibrary.model_validate(result["objects"]),
            MaterialLibrary.model_validate(result["materials"]),
            settings,
            {"bim": "abc"},
        )
    assert not d.summary.get("lateralMissing"), d.summary.get("lateralMissing")
    seismic = d.summary["seismic"]["EX"]
    assert seismic["Sa_g"] > 0 and seismic["base_shear_kN"] > 0
    wx = sum(
        n["forces"][0]
        for p in d.project["load_patterns"]
        if p["name"] == "WX"
        for n in p["nodal_loads"]
    )
    assert wx > 0


@pytest.mark.parametrize("pack_id", [AU, NZ])
def test_generated_building_is_designed_under_the_pack(tmp_path, pack_id):
    import json
    from pathlib import Path

    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

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
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
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
    code = {AU: "AS 3600", NZ: "NZS 3101"}[pack_id]
    assert any(code in line for line in report["method"]), report["method"]
    names = {c["name"] for e in report["elements"] for c in e.get("checks", [])}
    assert names, "no checks in the design report"

"""The Canada (NBCC 2020, CSA A23.3-19, CSA S16-19) and Mexico City (NTC-CDMX) packs of alpha 9
track C17.

Both extend the US pack and set what their codes change; the tests pin those values (with
their clauses, see each pack's VERIFY.md), the generic mechanisms the packs needed (the base
shear from the uniform hazard spectrum's ordinates, the ductility and overstrength reduced
spectrum, the compression field shear, the power column curve and the critical-moment lateral-
torsional buckling, the town's snow, rain and velocity pressure factor, Kz by exposure), that
the other packs keep their methods, and derive and design a small generated building under
each pack.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

PACKS = {
    "canada-nbcc": ["canada-nbcc", "aci318-asce7-22", "bnbc2020"],
    "mexico-ntc": ["mexico-ntc", "aci318-asce7-22", "bnbc2020"],
}


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.mark.parametrize("pack_id", sorted(PACKS))
def test_pack_is_listed_sound_and_extends(pack_id):
    assert pack_id in [p.id for p in registry.list_packs()]
    pack = registry.load(pack_id)
    assert pack.broken == {}
    assert pack.chain == PACKS[pack_id]
    for table in pack.info.covers:
        assert pack.provided_by(table) == pack_id
        pack.table(table)
    assert pack.info.units == "SI"
    assert (Path(pack.path) / "VERIFY.md").is_file()
    assert (Path(pack.path) / "README.md").is_file()


# ───────────────────────────── Canada: NBCC 2020 ─────────────────────────────


def test_nbcc_values():
    pack = registry.load("canada-nbcc")
    categories = pack.table("occupancyCategories").categories
    # Tables 4.1.8.5 and 4.1.7.3: IE and IW (ULS).
    assert [categories[k].seismicImportance for k in ("I", "II", "III", "IV")] == [0.8, 1, 1.3, 1.5]
    assert [categories[k].windImportance for k in ("I", "II", "III", "IV")] == [0.8, 1, 1.15, 1.25]
    strength = {c.id: c.factors for c in pack.table("combinations").strength}
    # Table 4.1.3.2-A: principal and companion loads.
    assert strength["2"] == {"D": 1.25, "F": 1.25, "L": 1.5, "Lr": 1.0, "H": 1.5}
    assert strength["4"]["W"] == 1.4 and strength["4"]["L"] == 0.5
    assert strength["5"] == {"D": 1.0, "F": 1.0, "E": 1.0, "L": 0.5, "Lr": 0.25, "H": 1.0}
    assert pack.table("combinations").exceptions == {}
    systems = pack.table("seismic").systems
    # Table 4.1.8.9: Rd, Ro; R = Rd Ro.
    assert (systems["rcSmf"].Rd, systems["rcSmf"].Ro, systems["rcSmf"].R) == (4.0, 1.7, 6.8)
    assert (systems["steelSmf"].Rd, systems["steelSmf"].Ro) == (5.0, 1.5)
    assert systems["rcSpecialBearingWall"].higherModeGroup == "walls"
    seismic = pack.table("seismic")
    assert seismic.accidentalEccentricity == 0.1  # 4.1.8.11(11)
    assert seismic.periodCoefficients["concreteMomentFrame"].Ct == 0.075  # 4.1.8.11(3)
    assert seismic.allowableDrift["IV"] == 0.01  # 4.1.8.13(3)
    top = seismic.lateralForce.topForce  # 4.1.8.11(7): Ft = 0.07 Ta V <= 0.25 V
    assert (top.periodFrom, top.factor, top.maxShare) == (0.7, 0.07, 0.25)
    vancouver = pack.table("locations").locations["vancouver"]
    assert (vancouver.groundSnow, vancouver.rainLoad) == (1.8, 0.2)
    assert 0.000613 * vancouver.windSpeed**2 == pytest.approx(0.45, abs=1e-3)  # q1/50
    assert pack.table("concrete").barNames["25.2"] == "25M"
    assert pack.provided_by("timber") == "aci318-asce7-22"  # O86 not covered


def test_nbcc_spectrum_and_base_shear():
    from saengine.fem import spectral_hazard as sh

    pack = registry.load("canada-nbcc")
    with code_context.using(pack):
        town = pack.table("locations").locations["vancouver"]
        hazard = sh.site_hazard(sh.with_location(None, town), "SC", pack)
        # 4.1.8.4(7): S(0.2) = max(Sa(0.2), Sa(0.5)); SDS and SD1 stand for S(0.2), S(1.0).
        assert float(hazard) == pytest.approx(0.848) and hazard.sd1 == pytest.approx(0.425)
        assert sh.spectral_acceleration(0.1, hazard) == pytest.approx(0.848)
        assert sh.spectral_acceleration(0.35, hazard) == pytest.approx((0.848 + 0.751) / 2)
        assert sh.band(hazard) == 4  # S(0.2) > 0.75
        # Another site class than the towns' (C): the source says so.
        assert "site class SC" in sh.site_hazard(sh.with_location(None, town), "SD").source
        system = pack.table("seismic").systems["rcSpecialBearingWall"]
        # 4.1.8.11(2): V/W = S(Ta) Mv IE / (Rd Ro), at least S(4.0) for walls, at most
        # max(2/3 S(0.2), S(0.5)) for Rd >= 1.5.
        terms = sh.ordinate_coefficient(1.0, hazard, 1.0, system.R, system)
        assert terms["value"] == pytest.approx(0.425 / 5.6)
        assert terms["least"] == pytest.approx((0.257 + (0.08 - 0.257) * 2 / 3) / 5.6)
        assert terms["cap"] == pytest.approx(0.751 / 5.6)
        assert sh.ordinate_coefficient(0.3, hazard, 1.0, 5.6, system)["value"] == pytest.approx(
            0.751 / 5.6
        )
        assert terms["Mv"] == 1.0 and terms["table"] is False  # Table 4.1.8.11 not entered
        assert sh.response_coefficient(1.0, hazard, 1.0, 5.6, system=system) == terms["value"]


def test_higher_mode_factor_table():
    from saengine.codes.tables import SpectrumOrdinates
    from saengine.fem import spectral_hazard as sh

    pack = registry.load("canada-nbcc")
    with code_context.using(pack):
        hazard = sh.SpectralHazard(0.8, 0.4, spectrum=[(0.2, 0.8), (1.0, 0.4), (5.0, 0.04)])
        rule = sh.rule()
        own = SpectrumOrdinates.model_validate(
            {
                "higherMode": {
                    "walls": {
                        "ratios": [5, 20],
                        "periods": [1.0, 2.0],
                        "values": [[1, 1], [1, 1.5]],
                    }
                }
            }
        )
        saved = rule.ordinates
        try:
            rule.ordinates = own
            # S(0.2)/S(5.0) = 20: Mv 1 at 1 s, 1.5 at 2 s, 1.25 at 1.5 s.
            assert sh.higher_mode_factor(1.5, hazard, "walls") == pytest.approx(1.25)
            assert sh.higher_mode_factor(1.5, hazard, "frames") == 1.0  # no table of the group
        finally:
            rule.ordinates = saved


def test_nbcc_wind_and_snow():
    from saengine.fem import loads, snow_load

    pack = registry.load("canada-nbcc")
    with code_context.using(pack):
        # 4.1.7.3(5): Ce = (h/10)^0.2 >= 0.9 open, 0.7 (h/12)^0.3 >= 0.7 rough.
        assert loads.exposure_coefficient(20.0, "open") == pytest.approx(2**0.2)
        assert loads.exposure_coefficient(3.0, "open") == pytest.approx(0.9, abs=1e-4)
        assert loads.exposure_coefficient(30.0, "rough") == pytest.approx(0.7 * 2.5**0.3, rel=1e-4)
        assert loads.exposure_coefficient(5.0, "rough") == pytest.approx(0.7, abs=1e-4)
        settings = SimpleNamespace(
            site=SimpleNamespace(location="vancouver", snow=SimpleNamespace(groundLoad=None)),
            occupancy=SimpleNamespace(category="IV"),
            wind=SimpleNamespace(claddingRoof=None),
        )
        snow = snow_load.roof_snow(settings)
        # 4.1.6.2: S = Is [Ss (Cb Cw Cs Ca) + Sr] = 1.25 (1.8 × 0.8 + 0.2).
        assert snow["s_kPa"] == pytest.approx(1.25 * (1.8 * 0.8 + 0.2))
        assert "Sr" in snow_load.describe(snow)
    with code_context.using(registry.load("aci318-asce7-22")):  # the parent unchanged
        assert loads.exposure_coefficient(20.0, "C") == pytest.approx(
            2.41 * (20 / 749.8) ** (2 / 9.8)
        )


def _beam(fc: float, fy: float, bottom: int = 3, dia: float = 25.2):
    from saengine.design import rc
    from saengine.library.objects import LinearReinforcement, RectangleProfile

    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [{"position": "bottom", "count": bottom, "dia": dia}],
            "transverse": {"type": "stirrup", "dia": 11.3, "spacing": 200, "legs": 2},
        }
    )
    return rc.section_of(RectangleProfile(xDim=300, yDim=600), reinforcement, fc, fy)


def test_csa_concrete():
    from saengine.design import compression_field_shear as cfs
    from saengine.design import design_strength, rc

    pack = registry.load("canada-nbcc")
    with code_context.using(pack):
        # 8.4.2-8.4.3: φc 0.65, φs 0.85; 10.1.7: α1 = 0.85 - 0.0015 f'c, β1 = 0.97 - 0.0025 f'c.
        p = design_strength.properties(30.0)
        assert (p.eta, p.lam, p.eps_cu3) == (0.805, 0.895, 0.0035)
        assert design_strength.fcd(30.0) == pytest.approx(0.65 * 30)
        assert design_strength.fyd(400.0) == pytest.approx(0.85 * 400)
        assert design_strength.properties(32.0).eta == 0.7975  # the band's top: on the safe side
        assert design_strength.properties(30.0).ecm == pytest.approx(4500 * math.sqrt(30))
        # 11.3.6.3: β 0.18 with Av,min, θ 35°, dv = max(0.9 d, 0.72 h).
        section = _beam(30.0, 400.0)
        result = rc.shear(section, 11.3, 2, 200)
        r = cfs.rules()
        d = section.effective_depth(top=False)
        dv = max(0.9 * d, 0.72 * 600)
        vc = 0.65 * 0.18 * math.sqrt(30) * 300 * dv
        vs = 0.85 * 2 * math.pi * 11.3**2 / 4 * 400 * dv / (math.tan(math.radians(35)) * 200)
        assert result.vc == pytest.approx(vc) and result.vs == pytest.approx(vs)
        assert result.phi_vn == pytest.approx(vc + vs) and result.threshold == pytest.approx(vc)
        assert result.with_min_stirrups  # 0.06 √30 × 300 × 200 / 400 = 49 mm² < 200 mm²
        # Without links: β = 230 / (1000 + dv).
        bare = rc.shear(section, None, 0, None)
        assert bare.vc == pytest.approx(0.65 * 230 / (1000 + dv) * math.sqrt(30) * 300 * dv)
        # 11.3.6.4 general method: β and θ from εx.
        g = cfs.general_terms(200e6, 150e3, 0.0, dv, 1500.0, True, r)
        eps = (200e6 / dv + 150e3) / (2 * 200000 * 1500)
        assert g.eps_x == pytest.approx(eps)
        assert g.beta == pytest.approx(0.4 / (1 + 1500 * eps) * 1300 / 1300)
        assert g.theta_deg == pytest.approx(29 + 7000 * eps)
        assert cfs.max_spacing(dv, 100e3, 30.0, 300.0, r) == pytest.approx(min(0.7 * dv, 600))
        lines = design_strength.method_lines("CSA A23.3-19")
        assert any("compression field" in line for line in lines)
    with code_context.using(registry.load("aci318-asce7-22")):  # the parent unchanged
        assert cfs.rules() is None
        aci = rc.shear(_beam(30.0, 420.0), 11.3, 2, 200)
        assert aci.notes is None and aci.vc == pytest.approx(
            0.17 * math.sqrt(30) * 300 * _beam(30.0, 420.0).effective_depth(top=False)
        )


def test_csa_s16_column_curve_and_ltb():
    from saengine.design.steel import members
    from saengine.design.steel.members import Steel
    from saengine.design.steel.properties import i_shape

    shape = i_shape(400.0, 200.0, 13.0, 8.0)
    steel = Steel(350.0, 450.0, 200_000.0)
    fe = 300.0
    with code_context.using(registry.load("canada-nbcc")):
        # 13.3.1: Cr / (φ A) = Fy (1 + λ^2n)^(-1/n), n = 1.34.
        lam = math.sqrt(350 / fe)
        assert members._fcr(fe, 350.0) == pytest.approx(350 * (1 + lam**2.68) ** (-1 / 1.34))
        # 13.6(a): Mu = ω2 π / L √(E Iy G J + (π E / L)² Iy Cw); Mr on Mp where Mu > 0.67 Mp.
        lb = 6000.0
        cap = members._i_major(shape, steel, lb, 1.0)
        g = members._shear_modulus()
        mu = (
            math.pi
            / lb
            * math.sqrt(
                200_000 * shape.iy * g * shape.j
                + (math.pi * 200_000 / lb) ** 2 * shape.iy * shape.cw
            )
        )
        mp = 350 * shape.zx
        expected = min(1.15 * mp * (1 - 0.28 * mp / mu), mp) if mu > 0.67 * mp else mu
        assert cap.nominal == pytest.approx(min(expected, mp), rel=1e-6)
    with code_context.using(registry.load("mexico-ntc")):
        lam = math.sqrt(350 / fe)
        assert members._fcr(fe, 350.0) == pytest.approx(350 * (1 + lam**2.8) ** (-1 / 1.4))
    with code_context.using(registry.load("aci318-asce7-22")):  # the parent unchanged
        assert members._fcr(fe, 350.0) == pytest.approx(0.658 ** (350 / fe) * 350)


# ───────────────────────────── Mexico: NTC-CDMX ─────────────────────────────


def test_ntc_values():
    pack = registry.load("mexico-ntc")
    strength = {c.id: c.factors for c in pack.table("combinations").strength}
    # NTC-Criterios 3.4: 1.3 / 1.5 gravity (Group B), 1.1 accidental, 0.9 favourable.
    assert strength["1"]["D"] == 1.3 and strength["1"]["L"] == 1.5
    assert strength["2E"]["E"] == 1.1 and strength["3E"]["D"] == 0.9
    seismic = pack.table("seismic")
    assert seismic.systems["rcSmf"].R == 4.0  # Q of marcos dúctiles (Sec 5.1)
    assert seismic.designEccentricity.staticAmplification == 1.5  # Sec 8.5
    assert seismic.allowableDrift["II"] == 0.006
    site = seismic.designSpectrum.ductility.sites["IIIb"]
    assert (site.a0, site.c, site.ta, site.tb, site.r) == (0.11, 0.45, 0.85, 3.0, 2.0)
    assert pack.table("occupancyCategories").categories["IV"].seismicImportance == 1.5
    assert pack.table("concrete").barNames["12.7"] == "#4"
    assert pack.table("factors").phi["bearing"] == 0.7


def test_ntc_spectrum():
    from saengine.fem import ductility_spectrum as ds
    from saengine.fem import loads

    pack = registry.load("mexico-ntc")
    with code_context.using(pack):
        rule = pack.table("seismic").designSpectrum.ductility
        # Zone IIIb: a = a0 + (c - a0) T/Ta below Ta, c to Tb, c (Tb/T)^2 beyond.
        assert ds.elastic_ordinate(0.425, "IIIb", rule) == pytest.approx(0.11 + 0.34 * 0.5)
        assert ds.elastic_ordinate(2.0, "IIIb", rule) == 0.45
        assert ds.elastic_ordinate(4.0, "IIIb", rule) == pytest.approx(0.45 * (3 / 4) ** 2)
        # Q' = 1 + (Q - 1) T/Ta below Ta, Q beyond; R = 1 (zone form).
        assert ds.ductility_factor(0.425, "IIIb", 4.0, rule) == pytest.approx(2.5)
        assert ds.ductility_factor(2.0, "IIIb", 4.0, rule) == 4.0
        assert ds.overstrength_factor(2.0, "IIIb", 4.0, rule) == 1.0
        # The design acceleration a / Q' × I (Group A 1.5).
        assert loads.design_acceleration(2.0, "IIIb", 1.0, 1.5, 4.0) == pytest.approx(
            1.5 * 0.45 / 4
        )
        # The site-specific form (k given): Q' with √(β/k), R = k1 R0 + k2.
        site = rule.sites["IIIb"].model_copy(update={"k": 0.5})
        own = rule.model_copy(update={"sites": {"S": site}})
        assert ds.ductility_factor(2.0, "S", 4.0, own) == pytest.approx(1 + 3 * math.sqrt(2))
        p = 0.5 + 0.5 * (3 / 4) ** 2
        assert ds.elastic_ordinate(4.0, "S", own) == pytest.approx(0.45 * p * (3 / 4) ** 2)
        k2 = 0.5 * (1 - math.sqrt(0.425 / 0.85))
        assert ds.overstrength_factor(0.425, "S", 4.0, own) == pytest.approx(2.0 + k2)
        with pytest.raises(ValueError, match="no spectrum for site class"):
            ds.elastic_ordinate(1.0, "SD", rule)


def test_cfe_wind_and_pressure_factor():
    from saengine.fem import loads
    from saengine.library.settings import default_project_settings, derived

    pack = registry.load("mexico-ntc")
    with code_context.using(pack):
        # CFE Tabla 4.2.3: Kz = Frz² = c² (z/10)^(2α), c below 10 m.
        assert loads.exposure_coefficient(20.0, "cat2") == pytest.approx(2**0.256)
        assert loads.exposure_coefficient(5.0, "cat4") == pytest.approx(0.815**2, rel=1e-3)
    settings = default_project_settings("Mexico", code_pack="mexico-ntc")
    with code_context.using(code_context.pack_for(settings)):
        values = derived(settings)
    assert values["windPressureFactor"] == 0.781
    assert values["windSpeed"] == pytest.approx(32.8 * math.sqrt(0.781))


def test_other_packs_keep_their_methods():
    from saengine.design import compression_field_shear
    from saengine.design.steel import members
    from saengine.fem import spectral_hazard as sh

    for pack_id in ("bnbc2020", "aci318-asce7-22", "eurocodes", "myanmar-mnbc"):
        with code_context.using(registry.load(pack_id)):
            assert compression_field_shear.rules() is None
            assert members._methods().columnCurve == "exponential"
            assert members._methods().lateralTorsional == "lengthLimits"
            rule = sh.rule()
            assert rule is None or rule.ordinates is None


# ───────────────────────────── generated buildings ─────────────────────────────


def _derive(tmp_path, spec):
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import DERIVATION_INPUTS
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    base = {
        "name": "C17 Frame",
        "gridsX": [6000, 6000],
        "gridsY": [5000, 5000],
        "storyCount": 3,
        "typicalHeight": 3200,
        "system": "rcFrame",
        "lateralSizing": "gravity",
        "siteClassSource": "entered",
    }
    root = Path(create_building({**base, **spec}, tmp_path)["root"])
    settings = json.loads(
        (root / "02 Project Settings/project-settings.json").read_text(encoding="utf-8")
    )
    project = open_project(root)
    texts = project.texts(DERIVATION_INPUTS)
    with code_context.project(root):
        out = handlers.derive_fem(
            texts["bim"], texts["objects"], texts["materials"], texts["settings"],
            str(root / "08 FEM"),
        )  # fmt: skip
    return settings, out


def test_canada_building_derives(tmp_path):
    settings, out = _derive(
        tmp_path, {"codePack": "canada-nbcc", "location": "vancouver", "siteClass": "SC"}
    )
    assert settings["seismic"]["system"] == "rcImf"  # Rd 2.5, Ro 1.4
    seismic = out["summary"]["seismic"]["EX"]
    # Ta = 0.075 × 9.6^0.75 = 0.409 s; S(Ta) / 3.5 above the cap S(0.5) / 3.5 = 0.2146.
    assert seismic["period_s"] == pytest.approx(0.075 * 9.6**0.75, rel=1e-3)
    assert seismic["Sa_g"] == pytest.approx(0.751 / 3.5, rel=1e-4)
    assert seismic["ordinates"]["cap"] == pytest.approx(0.751 / 3.5, rel=1e-3)
    assert out["summary"]["wind_X_kN"] > 0
    assert any("Sr = 0.2" in n for n in out["notes"])  # the roof snow with the rain load


def test_mexico_building_derives(tmp_path):
    settings, out = _derive(
        tmp_path, {"codePack": "mexico-ntc", "location": "cdmx", "siteClass": "IIIb"}
    )
    seismic = out["summary"]["seismic"]["EX"]
    t = seismic["period_s"]
    q = 2.0 if settings["seismic"]["system"] == "rcOmf" else None
    assert q is not None
    a = 0.11 + (0.45 - 0.11) * t / 0.85
    assert seismic["Sa_g"] == pytest.approx(a / (1 + (q - 1) * t / 0.85), rel=1e-6)
    assert out["summary"]["wind_X_kN"] > 0


@pytest.mark.parametrize(
    ("pack_id", "extra", "method"),
    [
        ("canada-nbcc", {"location": "toronto", "siteClass": "SC"}, "compression field"),
        ("mexico-ntc", {"location": "cdmx", "siteClass": "II"}, "NTC"),
    ],
)
def test_generated_building_is_designed_under_the_pack(tmp_path, pack_id, extra, method):
    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    spec = {
        "name": "C17 Concrete",
        "gridsX": [5000],
        "gridsY": [4000],
        "storyCount": 1,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": pack_id,
        "lateralSizing": "gravity",
        "siteClassSource": "entered",
        **extra,
    }
    root = Path(create_building(spec, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
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
    text = " ".join(report["method"])
    assert method in text, report["method"]
    names = {c["name"] for e in report["elements"] for c in e.get("checks", [])}
    assert "Shear" in names, sorted(names)

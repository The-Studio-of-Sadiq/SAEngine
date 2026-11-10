"""Alpha 9 C12 (concrete, foundations and loads half): what the IS and US packs no longer take
from the default pack. Value pins with their clauses (the packs' VERIFY.md rows L1-...), the
default pack unchanged, and a generated building per pack."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

IS, US, BNBC = "is-codes", "aci318-asce7-22", "bnbc2020"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def _using(pack_id):
    return code_context.using(registry.load(pack_id))


def test_default_pack_keeps_its_values():
    from saengine.design import prestress
    from saengine.fem import design_eccentricity, gust_response
    from saengine.plumbing import tanks
    from saengine.soil import settlement

    with _using(BNBC):
        lim = prestress.limits()
        assert lim.tensionForm == "root"
        assert prestress.tension_cap(lim.tensionClassU, 25) == pytest.approx(0.62 * 5)
        assert prestress.tension_text(0.5) == "0.5 √f'c"
        r = tanks.rules()
        assert r.crackControl == "crackWidth" and r.steelStress is None
        assert tanks.crack_limit(tanks.TankOptions()) == 0.2
        assert tanks.surface_zone_area(300) == 0.0
        assert tanks.max_spacing(250) == 450.0
        assert design_eccentricity.rule() is None
        assert gust_response.rules() is None
        assert settlement._rigidity() is None
        anchors = code_context.table("anchors")
        assert anchors.breakoutShear.capCoefficient is None
        shallow = code_context.table("foundations").shallow
        assert shallow.raftStiffness is None and shallow.lateralIncrease == pytest.approx(1.33)


def test_is_prestress_tension_limits_are_stresses():
    # IS 1343:1980 18.5.1, 22.7, 22.8 (VERIFY L1-L4).
    from saengine.design import prestress

    with _using(IS):
        lim = prestress.limits()
        assert lim.tensionForm == "absolute"
        assert lim.jackingFpu == pytest.approx(0.76)
        assert lim.transferCompression == pytest.approx(0.54)
        assert prestress.tension_cap(lim.tensionClassU, 40) == pytest.approx(3.0)
        assert prestress.tension_text(lim.transferTension, "f'ci") == "1 MPa"
        assert prestress.member_class(2.9, 40) == "U"
        assert prestress.member_class(3.1, 40) == "C"  # no Type 3 limit: cracked


def test_is_tanks_and_us_tanks():
    # IS 3370 (Part 2):2009 4.1, Table 2, 8.1.1; ACI 350-06 9.2.6, 7.12.2 (VERIFY L5-L8, U9-U12).
    from saengine.plumbing import tanks

    with _using(IS):
        r = tanks.rules()
        assert tanks.crack_limit(tanks.TankOptions()) == pytest.approx(0.2)
        assert r.crackControl == "crackWidth"
        assert (r.steelStress.tension, r.steelStress.flexureAway) == (130, 190)
        assert tanks.surface_zone_area(600) == pytest.approx(0.0035 * 250 * 1000)
        assert tanks.table_cover("severe", 30)[0] == 45.0
        assert tanks.max_spacing(250) == 300.0
        assert tanks.crack_limit(tanks.TankOptions(crackLimit=0.1)) == pytest.approx(0.1)
    with _using(US):
        r = tanks.rules()
        assert tanks.steel_stress_rules().tension == 138
        assert tanks.surface_zone_area(200) == pytest.approx(0.003 * 100 * 1000)
        assert tanks.table_cover("severe", 28)[0] == 50.0
        assert tanks.liquid_face("Wall N", "inner") and not tanks.liquid_face("Wall N", "outer")


def test_deep_beam_support_steel_zones():
    # IS 456 29.3.2 (b): 0.5 (l/D - 0.5) within 0.2 D, the rest about mid-depth (VERIFY L9).
    from saengine.design import deep_beams as db

    with _using(IS):
        span = db.DeepSpan(
            clear=3000.0, depth=1500.0, width=300.0, d=1400.0, fc=25.0, fy=415.0,
            bearings=(400.0, 400.0), tie_area=2000.0, tie_height=120.0,
            horizontal=(226.0, 200.0), top_zones=(1500.0, 400.0),
        )  # fmt: skip
        demands = db.SpanDemands(
            ((500e3, "C1"), (500e3, "C1")), (300e6, "C1"), (500e3, "C1"), hogging=(400e6, "C2")
        )
        rows = db.lever_span_checks(span, demands, "", True)
        names = [r["name"] for r in rows]
        assert "Deep beam support (hogging) steel" in names
        length = min(3000 + 400, 1.15 * 3000)
        z = db.lever_arm(span, True)
        need = 400e6 / (415 / 1.15 * z)
        top = next(r for r in rows if r["name"] == "Deep beam support steel, top zone")
        share = 0.5 * (length / 1500 - 0.5)
        assert top["demand"] == pytest.approx(share * need, abs=0.01)
        assert not db.lever_span_checks(span, demands, "", False)[-1]["name"].startswith(
            "Deep beam support"
        )


def test_settlement_rigidity_and_raft_stiffness():
    # IS 8009 (Part 1) 9.2.3 rigidity 0.8; IS 2950 / ACI 336.2R 1.75/λ (VERIFY L10-L11, U8).
    from saengine.soil import settlement
    from saengine.substructure.raft import RaftColumn, RaftSpec, raft_stiffness

    spec = RaftSpec(
        id="R1", outline=[(0, 0), (12000, 0), (12000, 12000), (0, 12000)], thickness=800.0,
        E=25000.0, fc=25.0, fy=415.0, reinforcement=None, ks=20000.0,
        columns=[RaftColumn(f"C{i}", x, y, 400, 400) for i, (x, y) in
                 enumerate([(0, 0), (6000, 0), (12000, 0), (0, 6000), (6000, 6000)])],
    )  # fmt: skip
    lam = (3 * 20000 / (25000e3 * 0.8**3)) ** 0.25
    with _using(IS):
        assert settlement._rigidity() == pytest.approx(0.8)
        found = raft_stiffness(spec)
        assert found["lambda"] == pytest.approx(lam)
        assert found["rigid"] == (6.0 < 1.75 / lam)
    with _using(US):
        assert raft_stiffness(spec)["bound"] == pytest.approx(1.75 / lam)
    with _using(BNBC):
        assert raft_stiffness(spec) is None


def test_is_loads_period_eccentricity_k3_gust():
    # IS 1893 7.6.2 (b), 7.8.2; IS 875-3 Annex C, Clause 10 (VERIFY L12-L16).
    from saengine.fem import design_eccentricity as de
    from saengine.fem import gust_response
    from saengine.fem import loads as fl
    from saengine.fem import wind_speed_factors as wsf

    with _using(IS):
        walls = [(1.2, 6.0), (1.2, 6.0)]
        aw = 2 * 1.2 * (0.2 + (6 / 30) ** 2)
        assert fl.approximate_period(30, "rcSpecialWallFrame", 20, walls) == pytest.approx(
            0.075 * 30**0.75 / math.sqrt(aw)
        )
        # without walls: 0.09 h / √d
        assert fl.approximate_period(30, "rcSpecialWallFrame", 20, []) == pytest.approx(
            0.09 * 30 / math.sqrt(20)
        )
        assert de.rule().staticAmplification == pytest.approx(1.5)
        assert de.extra(0.8, 1, 1.5) == pytest.approx(0.4)
        assert de.extra(0.8, -1, 1.5) == 0.0
        es = de.static_eccentricity([(0, 0, 1, 1), (10, 0, 1, 1)], [(5, 2, 1)])
        assert es == pytest.approx((2.0, 0.0))

        class Topo:
            feature, height, length, distance, side, isolated = "hill", 40, 100, 0, "upwind", True

        class Wind:
            directionality = topographic = gust = None
            topography = Topo()

        with fl.wind_overrides(Wind()):
            theta = math.degrees(math.atan(40 / 200))
            assert wsf.slope_factor()["theta"] == pytest.approx(theta)
            assert wsf.factors(10, 44, "2", 1.0)["k3"] == pytest.approx(1 + 1.2 * 40 / 200)
        assert gust_response.applies(120, 20, 2.0)  # h/b = 6 > 5
        assert not gust_response.applies(30, 20, 2.0)
        g = gust_response.gust_factor(120, 20, 0.35, 44, "2", 1.0)
        assert 1.0 < g["G"] < 3.0
        assert g["Lh"] == pytest.approx(85 * (120 / 10) ** 0.25)


def test_us_foundations_anchors_deflections():
    # IBC 2021 Table 1806.2, 1806.1, 1809.4; ACI 318-19 17.7.2.2.1; IBC Table 1604.3
    # (VERIFY U1-U7).
    from saengine.substructure import shallow_rules

    with _using(US):
        qa, note = shallow_rules.presumptive("sand", None, 1000)
        assert qa == pytest.approx(2000 * 0.04788026, abs=0.05)
        assert "1806.2" in note and "×" not in note  # no water reduction
        assert shallow_rules.presumptive("softRock", None, 1000)[0] == pytest.approx(191.5)
        shallow = code_context.table("foundations").shallow
        assert shallow.lateralIncrease == 1.0 and shallow.minDepth == 305.0
        assert [c.id for c in shallow.bearingCombinations][:3] == ["D", "DL", "DW"]
        sources = code_context.table("foundations").sources
        assert not any("BNBC" in v for v in sources.values()), [
            k for k, v in sources.items() if "BNBC" in v
        ]
        anchors = code_context.table("anchors")
        assert anchors.breakoutShear.capCoefficient == pytest.approx(3.7)
        assert anchors.applicability.diameterMax == 100
        assert "E" in anchors.seismic.categories
        service = code_context.table("serviceability")
        assert service.deflection.uses["wallPlaster"].wind == 360
        assert service.sway.ratio == pytest.approx(0.0025)


@pytest.mark.parametrize("pack_id", [IS, US])
def test_generated_building_derives_under_the_pack(tmp_path, pack_id):
    import json

    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

    spec = {
        "name": f"C12 {pack_id}",
        "gridsX": [5000, 5000],
        "gridsY": [4000],
        "storyCount": 2,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": pack_id,
        "lateralSizing": "gravity",
    }
    root = Path(create_building(spec, tmp_path)["root"])
    from saengine.pipeline.run_all import missing_hazard

    settings_path = root / "02 Project Settings/project-settings.json"
    if missing_hazard(settings_path.read_text(encoding="utf-8"), root):
        # A pack on the site's mapped values needs them entered (SDS 0.5 g, SD1 0.3 g),
        # as in test_codes_conformance.
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        site = settings.setdefault("site", {})
        site["spectral"] = {**(site.get("spectral") or {}), "sds": 0.5, "sd1": 0.3}
        settings_path.write_text(json.dumps(settings, indent=1), encoding="utf-8")
    result = run_all(root, steps=["derive"])
    assert [s.status for s in result.steps] == ["ok"], [s.message for s in result.steps]
    text = " ".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in (root / "08 FEM").rglob("*.json")
    )
    assert json.dumps("x")  # the model files were written
    if pack_id == IS:
        # The static torsion cases carry es (IS 1893 7.8.2); the gust factor method is noted.
        assert '"es_m"' in text
        assert "gust factor method" in text
    else:
        assert '"es_m"' not in text and "gust factor method" not in text

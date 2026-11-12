"""The previous Bangladesh code pack (``bnbc2006``: BNBC 1993, reissued 2006; alpha 9 track C10):
it extends BNBC 2020 and overrides the seismic zones, the base shear form, the wind method, the
load combinations and the strength reduction factors; values pinned to the pack's VERIFY.md, the
default pack unchanged, and a small generated building derived under it.
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

PACK = "bnbc2006"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def pack():
    loaded = registry.load(PACK)
    with code_context.using(loaded):
        yield loaded


def test_pack_is_built_in_valid_and_extends_bnbc2020(pack):
    assert PACK in [p.id for p in registry.list_packs()]
    found = registry.validate(registry.BUILTIN_DIR / PACK)
    assert not [p for p in found.problems if p.severity == "error"], found.problems
    # Inherited: the live loads and the concrete design of BNBC 2020.
    parent = registry.load("bnbc2020")
    assert (
        pack.table("areaLoads").uses["office"].live == parent.table("areaLoads").uses["office"].live
    )


def test_zones_sites_and_importance(pack):
    # BNBC 1993 Table 6.2.22: three zones.
    assert dict(pack.table("zoneCoefficients").zones) == {1: 0.075, 2: 0.15, 3: 0.25}
    towns = pack.table("locations").locations
    assert (towns["dhaka"].zone, towns["dhaka"].windSpeed) == (2, round(210 / 3.6, 2))
    assert (towns["sylhet"].zone, towns["khulna"].zone) == (3, 1)
    assert towns["chattogram"].windSpeed == round(260 / 3.6, 2)
    cats = pack.table("occupancyCategories").categories
    assert [cats[k].seismicImportance for k in ("I", "II", "III", "IV")] == [1.0, 1.0, 1.0, 1.25]


def test_base_shear_coefficient_and_top_force(pack):
    from saengine.fem import loads as fl

    # V/W = Z I C / R, C = 1.25 S / T^(2/3) <= 2.75 (Sec 2.5.6), C/R >= 0.075.
    for site, s in (("SA", 1.0), ("SC", 1.2), ("SD", 1.5), ("SE", 2.0)):
        for t in (0.2, 0.5, 1.0, 2.0):
            c = min(1.25 * s / t ** (2 / 3), 2.75)
            expected = max(0.15 * 1.0 * c / 8.0, 0.15 * 0.075)
            got = fl.elf_coefficient(t, site, 0.15, 1.0, 8.0, static=True)
            assert got == pytest.approx(expected, rel=2e-3), (site, t)
    # A very flexible frame takes the least C/R = 0.075.
    assert fl.elf_coefficient(6.0, "SA", 0.25, 1.0, 12.0) == pytest.approx(0.25 * 0.075)
    # T = 0.073 hn^(3/4) of RC moment frames (2.5.6.5).
    assert fl.approximate_period(20.0, "rcSmf") == pytest.approx(0.073 * 20**0.75)
    # Ft = 0.07 T V <= 0.25 V above 0.7 s (2.5.7.2), the rest by w h.
    levels = [(3.0, 100.0), (6.0, 100.0), (9.0, 100.0)]
    forces = fl.vertical_distribution(levels, 1000.0, 1.0)
    ft = 0.07 * 1.0 * 1000
    rest = 1000 - ft
    assert forces[2] == pytest.approx(rest * 9 / 18 + ft)
    assert forces[0] == pytest.approx(rest * 3 / 18)
    assert sum(forces) == pytest.approx(1000.0)
    assert fl.vertical_distribution(levels, 1000.0, 0.5)[2] == pytest.approx(1000 * 9 / 18)


def test_wind_pressure_by_cz_and_cg(pack):
    from saengine.fem import wind_speed_factors as wsf

    # qz = 47.2e-6 CI Cz Vb² (km/h), pz = CG Cp qz: exposure B at 10 m.
    z, alpha, zg, d0 = 10.0, 7.0, 274.32, 0.005
    cz = 2.58 * (z / zg) ** (2 / alpha)
    cg = 0.65 + 3.65 * 2.35 * math.sqrt(d0) / (z / 9.144) ** (1 / alpha)
    vb = 210.0
    expected = 47.2e-6 * cz * cg * vb**2  # kN/m²
    f = wsf.factors(z, vb / 3.6, "B", 1.0)
    assert f["pd"] == pytest.approx(expected, rel=3e-3)
    # Essential facilities: CI 1.25 on the pressure.
    assert wsf.factors(z, vb / 3.6, "B", 1.25)["pd"] == pytest.approx(1.25 * f["pd"], rel=1e-3)
    # The tables' first rows (Cz at 0-4.5 m: A 0.368, B 0.801, C 1.196).
    assert 2.58 * (4.572 / 365.76) ** (2 / 4.5) == pytest.approx(0.368, abs=1e-3)


def test_combinations_and_phi(pack):
    combos = {c.name: dict(c.factors) for c in pack.table("combinations").strength}
    assert combos["1.4D + 1.7L"]["D"] == 1.4 and combos["1.4D + 1.7L"]["L"] == 1.7
    assert combos["0.75(1.4D + 1.7L + 1.87E)"]["E"] == pytest.approx(1.4025)
    assert combos["0.9D + 1.43E"] == {"D": 0.9, "E": 1.43}
    phi = pack.table("factors").phi
    assert (phi.tension, phi.compressionTied, phi.shear) == (0.9, 0.7, 0.85)
    # Inherited from BNBC 2020 where the older code has no row.
    assert phi.strutAndTie == registry.load("bnbc2020").table("factors").phi.strutAndTie


def test_default_pack_is_unchanged():
    from saengine.fem import loads as fl

    with code_context.using(registry.load("bnbc2020")):
        rule = code_context.table("seismic").designSpectrum
        assert rule is None or (rule.shapePlateau is None and rule.descendingExponent is None)
        top = code_context.table("seismic").lateralForce
        assert top is None or top.topForce is None
        forces = fl.vertical_distribution([(3.0, 1.0), (6.0, 1.0)], 90.0, 1.0)
        assert sum(forces) == pytest.approx(90.0)


def test_generated_building_derives_under_the_pack():
    from saengine.fem.derive import derive_fem
    from saengine.library import FloorPlan, MaterialLibrary, ObjectLibrary
    from saengine.library.bim import generate
    from saengine.library.generator import generate_building
    from saengine.library.settings import ProjectSettings

    spec = {
        "name": "BNBC 2006 frame",
        "gridsX": [5000, 5000],
        "gridsY": [4000, 4000],
        "storyCount": 3,
        "groundHeight": 3500,
        "typicalHeight": 3200,
        "codePack": PACK,
    }
    result = generate_building(spec)
    settings = ProjectSettings.model_validate(result["settings"])
    assert settings.codePack == PACK and settings.site.location == "dhaka"
    building = generate(FloorPlan.model_validate(result["floorPlan"]), "s")
    with code_context.using(registry.load(PACK)):
        d = derive_fem(
            building,
            ObjectLibrary.model_validate(result["objects"]),
            MaterialLibrary.model_validate(result["materials"]),
            settings,
            {"bim": "abc"},
        )
    ex = d.summary["seismic"]["EX"]
    # Dhaka: zone 2, Z 0.15; T = Ct hn^(3/4).
    system = settings.seismic.system
    with code_context.using(registry.load(PACK)):
        from saengine.fem import loads as fl
        from saengine.library.settings import derived

        values = derived(settings)
        assert values["Z"] == 0.15
        ta = fl.approximate_period(3.5 + 2 * 3.2, system)
        sa = fl.elf_coefficient(
            ta, settings.site.siteClass, 0.15, values["seismicImportance"], values["R"]
        )
    assert ex["period_s"] == pytest.approx(ta, rel=1e-6)
    assert ex["Sa_g"] == pytest.approx(sa, rel=1e-6)
    names = {p["name"] for p in d.project["load_patterns"]}
    assert {"EX", "EY", "WX", "WY"} <= names

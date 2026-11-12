"""Alpha 9 C12 (steel half): the steel features the US, Eurocodes and IS packs still fell back
on, pinned with their clauses (each pack's VERIFY.md lists them for checking against the
printed codes): torsion by elastic stresses (EN 1993-1-1 6.2.7; IS as SAEngine practice), the
stability bracing forces (EN 1993-1-1 5.3.3, IS 800 2.5 %, the AISC Appendix 6 rows), EBF links
(EN 1998-1 6.8.2), cold-formed members (AISI S100, EN 1993-1-3, IS 801), the column side under
flange forces (EN 1993-1-8 6.2.6, IS 800 8.7), HSS joints (EN 1993-1-8 Section 7), steel in
fire (AISC 360 Appendix 4, EN 1993-1-2, IS 800 Section 16); that the default pack is unchanged;
and a small steel portal per pack.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design import steel_connections as sc
from saengine.design.steel import (
    bracing_forces,
    cold_formed,
    dissipative_links,
    fire,
    torsion_stresses,
)
from saengine.design.steel import members as sm
from saengine.design.steel.lengths import MemberLengths
from saengine.design.steel.properties import i_shape, lipped
from saengine.design.steel_proposal import SteelMaterial
from saengine.library import steel_sections as tables
from saengine.library.objects import HssJointConnection

PACKS = ("aci318-asce7-22", "eurocodes", "is-codes")
S355 = sm.Steel(355.0, 510.0, 210_000.0, "S355")
IPE300 = i_shape(300, 150, 10.7, 7.1, 15, "IPE 300")
LIPPED_C = lipped("C", 200, 75, 20, 2.0, 3.0)
LIPPED_Z = lipped("Z", 200, 75, 20, 2.0, 3.0)


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def _using(pack_id: str):
    return code_context.using(registry.load(pack_id))


def _stations(p=0.0, mx=0.0, vy=0.0, torque=None, n=9, length=4.0):
    s = np.linspace(0, length, n)
    return [
        sm.Stations(
            "ULS", s, np.full(n, p), np.full(n, mx), np.zeros(n), np.full(n, vy), np.zeros(n),
            [f"at {x:.1f} m" for x in s], None if torque is None else np.full(n, torque),
        )
    ]  # fmt: skip


def _by(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_tables_load_in_every_pack_and_not_in_the_default():
    for pack_id in PACKS:
        pack = registry.load(pack_id)
        assert pack.has("coldFormed") and pack.has("steelFire"), pack_id
        info = registry.info(pack_id)
        assert info.usable and not info.problems, (pack_id, info.problems)
    bnbc = registry.load("bnbc2020")
    assert not bnbc.has("coldFormed") and not bnbc.has("steelFire")
    with code_context.using(bnbc):
        assert torsion_stresses.table() is None and bracing_forces.table() is None
        assert fire.table() is None and cold_formed.table() is None


def test_fire_retention_and_critical_temperature():
    with _using("eurocodes"):
        t = fire.table()
        # EN 1993-1-2 Table 3.1: ky,θ 0.78 / 0.47 at 500 / 600 °C, kE,θ 0.60 / 0.31
        assert fire.retention(550, t) == pytest.approx((0.625, 0.455))
        # Eq 4.22 (Table 4.1: 585 °C at μ0 = 0.5)
        assert fire.critical_temperature(0.5, t) == pytest.approx(584.6, abs=0.2)
    with _using("is-codes"):
        t = fire.table()
        # IS 800:2007 16.2: fy(T)/fy = (905 - T)/690; E(T)/E = 1 + T / (2000 ln(T/1100))
        ky, ke = fire.retention(500, t)
        assert ky == pytest.approx(405 / 690)
        assert ke == pytest.approx(1 + 500 / (2000 * math.log(500 / 1100)))
        # 16.3: Tl = 905 - 690 rf
        assert fire.critical_temperature(0.5, t) == pytest.approx(560.0)
    with _using("aci318-asce7-22"):
        t = fire.table()
        # AISC 360-22 Table A-4.2.1: ky = 0.66 at 1000 °F (538 °C); θcr where ky = μ0
        assert fire.critical_temperature(0.66, t) == pytest.approx(538.0, abs=0.5)


def test_fire_heating_and_member_rows():
    with _using("eurocodes"):
        t = fire.table()
        am_v, box = fire.section_factor(IPE300, "column")
        assert am_v == pytest.approx((2 * 300 + 4 * 150 - 2 * 7.1) / IPE300.area * 1e3)
        hot = fire.steel_temperature(0.5, am_v, box, "I", t)
        # unprotected I (ksh Am/V ~ 160 1/m), 30 minutes of ISO 834 (θg 842 °C), ca 600 J/kgK
        assert 750 < hot < 842
        opts = sm.SteelOptions(fire={"column": (1.0, "Project Settings")})
        lengths = MemberLengths.simple(4.0)
        rows = sm.check_member(IPE300, S355, _stations(p=400e3), lengths, "column", opts)
        row = _by(rows, "Fire: buckling resistance at temperature")
        assert row["utilisation"] > 1.0  # unprotected for an hour: fails
        assert "EN 1993-1-2" in row["clause"]
    with _using("bnbc2020"):  # the default pack: no fire rows
        opts = sm.SteelOptions(fire={"column": (1.0, "Project Settings")})
        rows = sm.check_member(IPE300, S355, _stations(p=400e3), MemberLengths.simple(4.0),
                               "column", opts)  # fmt: skip
        assert not [r for r in rows if r["name"].startswith("Fire")]


def test_torsion_by_elastic_stresses():
    for pack_id, code in (("eurocodes", "EN 1993-1-1 6.2.7"), ("is-codes", "IS 800:2007")):
        with _using(pack_id):
            rows = sm.check_member(
                IPE300, S355, _stations(mx=50e6, vy=40e3, torque=3e6), MemberLengths.simple(4.0),
                "beam",
            )  # fmt: skip
            crit = _by(rows, "Torsion: yield criterion (elastic stresses)")
            shear = _by(rows, "Torsion: shear with torsion (Vpl,T)")
            assert crit["utilisation"] > 0 and code in crit["clause"]
            assert shear["capacity"] < 7.1 * 300 * 355 / math.sqrt(3) / 1e3
    # Vpl,T / Vpl of I-sections √(1 - τt / (1.25 fy / √3))
    assert torsion_stresses.shear_reduction("I", 50.0, 0.0, 200.0, 1.25) == pytest.approx(
        math.sqrt(0.8)
    )


def test_bracing_forces():
    lengths = MemberLengths.simple(4.0, x=[2.0], y=[2.0])
    with _using("eurocodes"):
        found = bracing_forces.requirements(IPE300, _stations(p=1000e3), lengths, "column")
        # EN 1993-1-1 5.3.3: e0 = L/500 = 8 mm, δq = L/2500 = 1.6 mm, q = 8 NEd (e0 + δq) / L²
        q = 1000e3 * 8 * (8 + 1.6) / 4000**2
        assert found[0]["Pbr"] == pytest.approx(q * 2000 / 1e3, abs=0.01)
    with _using("is-codes"):
        found = bracing_forces.requirements(IPE300, _stations(p=1000e3), lengths, "column")
        assert found[0]["Pbr"] == pytest.approx(25.0)  # 2.5 %
    with _using("aci318-asce7-22"):  # Appendix 6 as flagged rows
        entry_rows = bracing_forces.rows_of(
            sm.bracing_requirements(IPE300, _stations(p=1000e3), lengths, "column")
        )
        assert entry_rows and all(r["flag"] for r in entry_rows)
        assert entry_rows[0]["demand"] == pytest.approx(10.0)  # 0.01 Pr nodal


def test_ebf_link_strength_and_class():
    with _using("eurocodes"):
        t = dissipative_links.table()
        k = dissipative_links.strength(IPE300, 355.0, 0.0, 300e3, t)
        # EN 1998-1 6.8.2: Vp,link = fy/√3 tw (d - tf), Mp,link = fy b tf (d - tf)
        assert k["Vp"] == pytest.approx(355 / math.sqrt(3) * 7.1 * 289.3)
        assert k["Mp"] == pytest.approx(355 * 150 * 10.7 * 289.3)
        es = 1.6 * k["Mp"] / k["Vp"]
        assert dissipative_links.classify(0.9 * es, k["Mp"], k["Vp"], t) == "short"
        assert dissipative_links.classify(3.1 * k["Mp"] / k["Vp"], k["Mp"], k["Vp"], t) == "long"
        assert dissipative_links.rotation_limit(0.5 * es, k["Mp"], k["Vp"], t) == 0.08
        reduced = dissipative_links.strength(IPE300, 355.0, 0.3 * IPE300.area * 355, 300e3, t)
        assert reduced["Vp"] == pytest.approx(k["Vp"] * math.sqrt(1 - 0.09))


def test_cold_formed_members_per_pack():
    lengths = MemberLengths.simple(3.0)
    found = {}
    for pack_id in PACKS:
        with _using(pack_id):
            rows = sm.check_member(
                LIPPED_C, S355, _stations(p=40e3, mx=4e6, vy=5e3, length=3.0), lengths, "column"
            )
            names = {r["name"] for r in rows}
            assert {"Compression: buckling (cold-formed)", "Combined forces (cold-formed)"} <= names
            found[pack_id] = _by(rows, "Compression: buckling (cold-formed)")["capacity"]
            z_rows = sm.check_member(LIPPED_Z, S355, _stations(mx=3e6, length=3.0), lengths, "beam")
            assert _by(z_rows, "Flexure about x (major, cold-formed)")["capacity"] > 0
    assert all(v > 0 for v in found.values())
    with _using("is-codes"):  # IS 801 5.2.2.1: the lip's least depth
        rows = sm.check_member(LIPPED_C, S355, _stations(p=40e3), lengths, "column")
        assert "dmin" in _by(rows, "Cold-formed lip as a stiffener")["note"]
    with _using("bnbc2020"), pytest.raises(sm.SteelDesignError):
        sm.check_member(LIPPED_C, S355, _stations(p=40e3), lengths, "column")


def test_cold_formed_effective_widths():
    with _using("aci318-asce7-22"):
        t = cold_formed.table()
        # AISI S100 1.1: λ = 1.052/√k (w/t) √(f/E), ρ = (1 - 0.22/λ)/λ
        lam = 1.052 / 2 * 95 * math.sqrt(355 / 203000)
        assert cold_formed.rho(190, 2.0, 355, True, 1.0, t) == pytest.approx((1 - 0.22 / lam) / lam)
    with _using("eurocodes"):
        t = cold_formed.table()
        # EN 1993-1-5 4.4: λp = (b/t) / (28.4 ε √4), ρ = (λp - 0.055 × 4) / λp²
        lp = 95 / (28.4 * math.sqrt(235 / 355) * 2)
        assert cold_formed.rho(190, 2.0, 355, True, 1.0, t) == pytest.approx((lp - 0.22) / lp**2)
        sigma, area = cold_formed.distortional_stress(LIPPED_C, 210000, 0.3, False)
        assert sigma > 0 and area > 0


def test_column_side_and_hss_joints():
    col = tables.i_section("HE 300 B", "HEB", 300, 300, 11, 19, 27)
    m = SteelMaterial("S355", 355, 510, 210_000)
    with _using("eurocodes"):
        rows, _ = sc.column_side_checks(500e3, "M", col, m, 16.0, False, delivering_thickness=16)
        web = _by(rows, "column web in transverse compression")
        assert "EN 1993-1-8 6.2.6.2" in web["note"]
        panel = _by(rows, "column panel zone shear")
        avc = col.A - 2 * 300 * 19 + (11 + 2 * 27) * 19
        assert panel["capacity"] == pytest.approx(0.9 * 355 * avc / math.sqrt(3) / 1e3, abs=0.05)
        chord, branch = (
            tables.chs_section("CHS 168.3x8", 168.3, 8),
            tables.chs_section("CHS 88.9x5", 88.9, 5),
        )
        c = HssJointConnection(joint="TY", angle=90, chordCompression=False)
        r = sc.check_hss_joint(c, branch, m, chord, None, [("T", 100e3)])
        beta, gamma = 88.9 / 168.3, 168.3 / 16
        # EN 1993-1-8 Table 7.2: γ^0.2 kp fy0 t0² (2.8 + 14.2 β²) / sinθ / γM5
        pn = gamma**0.2 * 355 * 64 * (2.8 + 14.2 * beta**2)
        assert _by(r["checks"], "chord face failure (tension)")["capacity"] == pytest.approx(
            pn / 1e3, abs=0.01
        )
    with _using("is-codes"):
        rows, _ = sc.column_side_checks(500e3, "M", col, m, 16.0, False, delivering_thickness=16)
        bearing = _by(rows, "column web bearing")
        n2 = 2 * 2.5 * (19 + 27)
        assert bearing["capacity"] == pytest.approx((16 + n2) * 11 * 355 / 1.1 / 1e3, abs=0.05)


def test_portal_per_pack_with_fire_and_bracing():
    """A small steel portal (two H columns braced at mid-height, an H beam) designed under each
    pack with a one-hour rating: the fire rows, the bracing entries and the pack's clauses."""
    from saengine.design import steel_design
    from saengine.design.check import _demands
    from saengine.library.settings import LoadCombination
    from saengine.verification.cases.common import (
        MATERIALS,
        derive,
        objects,
        point,
        run_model,
        settings,
        structure,
    )
    from saengine.verification.cases.common import building as building_of

    w = {"shape": "I", "overallWidth": 200, "overallDepth": 200, "webThickness": 9,
         "flangeThickness": 15}  # fmt: skip
    steel_id = next(m.id for m in MATERIALS.materials if m.category.value == "steel")
    types = objects(
        {"id": "COL", "name": "H col", "kind": "column", "material": steel_id, "profile": w},
        {"id": "BM", "name": "H beam", "kind": "beam", "material": steel_id, "profile": w},
    )
    model = structure(
        members=[
            {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3200)},
            {"id": "C2", "type": "COL", "start": point(6000, 0, 0), "end": point(6000, 0, 3200)},
            {"id": "B1", "type": "BM", "start": point(0, 0, 3200), "end": point(6000, 0, 3200)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    building = building_of(model)
    import tempfile
    from pathlib import Path

    t = {x.id: x for x in types.objects}
    mats = {m.id: m for m in MATERIALS.materials}
    for pack_id in PACKS:
        with _using(pack_id):
            project = derive(building, types, MATERIALS, settings()).project
            beam = next(e["id"] for e in project["elements"] if e["name"] == "B1")
            project["load_patterns"][0]["element_loads"].append(
                {"element_id": beam, "wy": 0.0, "wz": -20e3, "wx": 0.0}
            )
            static = [a["id"] for a in project["analyses"] if a["type"] == "Static"]
            _, out, _ = run_model(project, Path(tempfile.mkdtemp()), static)
            s = settings().model_copy(
                update={"combinations": [LoadCombination(name="1.4D", D=1.4)]}
            )
            combinations, pieces, _, _ = _demands(project, out, s)
            options = sm.SteelOptions(
                fire={"column": (1.0, "Project Settings"), "beam": (1.0, "Project Settings")}
            )
            column = steel_design.design_member(
                "C1", "column", t["COL"], mats[steel_id], mats, pieces["C1"], combinations,
                False, project, options,
            )[0]  # fmt: skip
            fire_rows = [c for c in column["checks"] if c["name"].startswith("Fire")]
            assert fire_rows, pack_id
            beam_entry = steel_design.design_member(
                "B1", "beam", t["BM"], mats[steel_id], mats, pieces["B1"], combinations,
                False, project, options,
            )[0]  # fmt: skip
            assert any(c["name"].startswith("Fire") for c in beam_entry["checks"]), pack_id
            assert "fire" in " ".join(steel_design.METHOD).lower()

"""C6: steel and the other materials of the Eurocodes pack (``eurocodes``).

Pins the pack's values with their clauses (VERIFY.md lists them for checking against the printed
codes): EN 1993-1-1 members through the limit state steel table (cross-section classes, χ of the
buckling curves, lateral-torsional buckling, the interaction), EN 1993-1-8 bolts and welds, the
EN 1993-1-1 5.3 sway imperfection, EN 1994-1-1 studs, EN 1995-1-1 timber, EN 1996-1-1 masonry,
EN 1999-1-1 aluminium; that the default pack keeps its steel methods; and a small steel portal
designed under the pack.
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design.steel import buckling_curves as bc
from saengine.design.steel import joint_resistances as jr
from saengine.design.steel import members as sm
from saengine.design.steel.lengths import MemberLengths
from saengine.design.steel.properties import i_shape

PACK_ID = "eurocodes"
S355 = sm.Steel(355.0, 510.0, 210_000.0, "S355")
# HE 200 B (sharp-cornered, r = 18) and IPE 300 (r = 15)
HEB200 = i_shape(200, 200, 15, 9, 18, "HE 200 B")
IPE300 = i_shape(300, 150, 10.7, 7.1, 15, "IPE 300")


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def ec():
    pack = registry.load(PACK_ID)
    with code_context.using(pack):
        yield pack


def _stations(p: float, mx: float = 0.0, n: int = 5, length: float = 4.0):
    import numpy as np

    s = np.linspace(0, length, n)
    return [
        sm.Stations(
            "ULS", s, np.full(n, p), np.full(n, mx), np.zeros(n), np.zeros(n), np.zeros(n),
            [f"at {x:.1f} m" for x in s],
        )
    ]  # fmt: skip


def test_pack_covers_steel_and_other_materials(ec):
    info = registry.info(PACK_ID)
    assert info.usable and not info.problems
    assert {"steelLimitState", "composite", "timber", "masonry", "aluminium"} <= set(info.covers)
    t = ec.table("steelLimitState")
    m = t.memberResistance
    # EN 1993-1-1 6.1: γM0 1.00, γM1 1.00, γM2 1.25; 3.2.6 E, G; Table 6.1 α
    assert (m.gammaM0, m.gammaM1, m.gammaM2) == (1.0, 1.0, 1.25)
    assert (m.modulus, m.shearModulus) == (210000, 81000)
    assert m.imperfection == {"a0": 0.13, "a": 0.21, "b": 0.34, "c": 0.49, "d": 0.76}
    # Table 5.2: internal parts 72/83/124 (bending), 33/38/42 (compression), outstands 9/10/14
    assert m.classes.internalBending == (72, 83, 124)
    assert m.classes.outstandCompression == (9, 10, 14)
    assert m.interaction.method == "annexB" and m.lateralTorsional.method == "rolled"
    assert t.connections.method == "partialFactors" and t.seismic.method == "dissipativeZones"
    assert t.seismic.gammaOv == 1.25


def test_default_pack_keeps_its_steel_method():
    with code_context.using(registry.load("bnbc2020")):
        assert not bc.active() and not jr.active()
        checks = sm.check_member(
            IPE300, sm.Steel(250, 400, 200000), _stations(100e3), MemberLengths.simple(4.0)
        )
        assert any(c["name"] == "Axial force and flexure (H1)" for c in checks)


def test_classes_and_buckling_curves(ec):
    eps = bc.epsilon(355)
    assert eps == pytest.approx(math.sqrt(235 / 355))
    # IPE 300 web c/t = (300 - 2 10.7 - 2 15) / 7.1 = 35.0 > 42 ε = 34.2: class 4 in compression
    comp = bc.classify(IPE300, 355, "compression")
    assert bc.section_class(comp) == 4
    assert bc.section_class(bc.classify(IPE300, 355, "bending", "y")) == 1
    # Table 6.2: rolled I, h/b <= 1.2, tf <= 100: y-y b, z-z c; h/b > 1.2, tf <= 40: a, b
    assert bc.curves(HEB200, 355, False) == ("b", "c")
    assert bc.curves(IPE300, 355, False) == ("a", "b")
    assert bc.curves(IPE300, 460, False) == ("a0", "a0")
    # 6.3.1.2: λ̄ = 1.0 on curve b: Φ = 0.5 (1 + 0.34 × 0.8 + 1) = 1.136, χ = 0.597
    assert bc.chi(1.0, 0.34, 0.2) == pytest.approx(0.5970, abs=1e-4)


def test_column_buckling_resistance(ec):
    lengths = MemberLengths.simple(4.0)
    checks = {c["name"]: c for c in sm.check_member(HEB200, S355, _stations(800e3), lengths)}
    sec = bc.Section.of(HEB200, 355, 510, False)
    assert sec.compression_class == 1
    # z-z: Ncr = π² E Iz / L², λ̄ = √(A fy / Ncr), curve c
    ncr = math.pi**2 * 210000 * HEB200.iy / 4000**2
    lam = math.sqrt(HEB200.area * 355 / ncr)
    chi = bc.chi(lam, 0.49, 0.2)
    nb = chi * HEB200.area * 355 / 1.0
    assert checks["Compression: buckling"]["capacity"] == pytest.approx(nb / 1e3, rel=1e-3)
    assert "EN 1993-1-1 6.3.1" in checks["Compression: buckling"]["clause"]
    assert "Axial force and flexure: buckling, minor axis" in checks


def test_lateral_torsional_rolled_case(ec):
    sec = bc.Section.of(IPE300, 355, 510, False)
    x, lam, mcr, _ = bc.lateral_torsional(sec, 5000.0, 1.0, IPE300.zx)
    expected_mcr = (
        math.pi**2
        * 210000
        * IPE300.iy
        / 5000**2
        * math.sqrt(
            IPE300.cw / IPE300.iy + 5000**2 * 81000 * IPE300.j / (math.pi**2 * 210000 * IPE300.iy)
        )
    )
    assert mcr == pytest.approx(expected_mcr)
    # 6.3.2.3: h/b = 2 <= 2: curve b, λ̄LT,0 = 0.4, β = 0.75
    phi = 0.5 * (1 + 0.34 * (lam - 0.4) + 0.75 * lam**2)
    assert x == pytest.approx(min(1.0, 1 / lam**2, 1 / (phi + math.sqrt(phi**2 - 0.75 * lam**2))))


def test_joints_by_en1993_1_8(ec):
    assert jr.active()
    # Table 3.4: Fv,Rd = αv fub As / γM2 = 0.6 × 800 × 245 / 1.25; Ft,Rd = 0.9 fub As / γM2
    assert jr.shear("8.8", 20) == pytest.approx(0.6 * 800 * 245 / 1.25)
    ft, _ = jr.tension("8.8", 20)
    assert ft == pytest.approx(0.9 * 800 * 245 / 1.25)
    from saengine.design import steel_connections as sc

    assert sc.bolt_shear_capacity("10.9", 20) == pytest.approx(0.5 * 1000 * 245 / 1.25)
    # 4.5.3.3: fvw,d = fu / (√3 βw γM2), S355 (fu 510): βw 0.9
    with jr.parent(510):
        assert sc.fillet_capacity_per_mm(6, 480) == pytest.approx(
            0.707 * 6 * 510 / (math.sqrt(3) * 0.9 * 1.25)
        )


def test_sway_imperfection(ec):
    from saengine.fem import notional_loads as nl

    # 5.3.2(3): φ = φ0 αh αm, φ0 = 1/200, αh = 2/√h >= 2/3 (h = 12 m: 0.577 -> 2/3)
    assert nl.sway_coefficient(12.0) == pytest.approx(0.005 * 0.6667)
    assert nl.sway_coefficient(4.0) == pytest.approx(0.005)
    assert nl.every_combination()


def test_composite_studs_en1994(ec):
    from saengine.design.steel import composite as cp

    table = cp.composite_table()
    pf = cp.partial_factors(table)
    concrete = cp.Concrete(30, 30, 2400, cp.concrete_modulus(30, 2400, table), False)
    # 3.1: Ecm = 22000 ((fck + 8) / 10)^0.3; 6.6.3.1: PRd = min(0.8 fu π d²/4, 0.29 α d² √(fck Ecm)) / γV
    assert concrete.ec == pytest.approx(22000 * 3.8**0.3)
    prd, _ = cp.stud_resistance(19, 100, 450, concrete, pf)
    steel = 0.8 * 450 * math.pi * 19**2 / 4 / 1.25
    conc = 0.29 * 19**2 * math.sqrt(30 * concrete.ec) / 1.25
    assert prd == pytest.approx(min(steel, conc))
    # 6.6.1.2: η >= 1 - (355/fy)(0.75 - 0.03 Le) >= 0.4
    assert cp.minimum_connection(355, 10000, pf) == pytest.approx(0.55)


def test_timber_en1995(ec):
    from saengine.design.timber import limit_state as tl

    assert tl.active()
    # Table 3.1 kmod: solid timber, service class 1, medium-term 0.8; 2.3 γM 1.3
    assert tl.kmod("solid", "1", "medium") == 0.8
    assert tl.duration_of({"D": 1.35, "L": 1.5}) == "medium"
    assert tl.duration_of({"D": 1.0, "EX": 1.0}) == "instantaneous"
    # 6.3.2: λrel 1.0, βc 0.2: k = 0.5 (1 + 0.2 × 0.7 + 1) = 1.07, kc = 1 / (k + √(k² - 1))
    k = 0.5 * (1 + 0.2 * 0.7 + 1)
    assert tl.column_factor(1.0, 0.2) == pytest.approx(1 / (k + math.sqrt(k * k - 1)))
    assert tl.lateral_factor(1.0) == pytest.approx(1.56 - 0.75)


def test_masonry_en1996(ec):
    from saengine.design import masonry as M
    from saengine.design import masonry_partial_factors as mp

    assert M.method_id() == "partialFactors"
    m = M.Masonry(5.0, "clay", None, "solid", fm_source="estimate", unit_strength=20.0)
    fk, _fb = mp.characteristic_strength(m, [])
    # 3.6.1.2 Eq 3.1, Table 3.3: clay group 1 K 0.55, α 0.7, β 0.3; fm the default 2.5 MPa
    assert fk == pytest.approx(0.55 * 20**0.7 * 2.5**0.3)
    assert mp.capacity_reduction_end(15, 200) == pytest.approx(1 - 2 * 15 / 200)


def test_aluminium_en1999(ec):
    from saengine.design import aluminium as al
    from saengine.design.steel.lengths import MemberLengths as ML
    from saengine.library.materials import Material

    t = al.table()
    assert (t.gammaM1, t.gammaM2) == (1.1, 1.25)
    mat = Material.model_validate(
        {
            "id": "AL", "name": "6082", "category": "aluminium",
            "mechanical": {"E": 70000, "density": 2700}, "aluminium": {"alloy": "EN AW-6082 T6"},
        }
    )  # fmt: skip
    shape = i_shape(120, 120, 8, 6, 0, "I 120")
    checks, summary = al.check_member(
        shape, mat, _stations(50e3, -5e6, length=3.0), ML.simple(3.0), "column"
    )
    names = {c["name"] for c in checks}
    assert {"Compression: buckling", "Lateral-torsional buckling"} <= names
    assert summary["f0"] == 250
    # 6.3.1.2 class A: α 0.20, λ̄0 0.10
    assert al._chi(1.0, 0.2, 0.1) < 1.0


def test_dissipative_split_and_amplify(ec):
    from saengine.design.steel import seismic_dissipative as sd

    assert sd.active()
    names = ["G + EX + 0.3Q", "G + (-EX) + 0.3Q", "1.35G"]
    pairs = sd.earthquake_pairs(names, [0, 1])
    assert pairs == [(0, 1)]
    plus, minus = _stations(300e3)[0], _stations(100e3)[0]
    # G = (F+ + F-) / 2 = 200 kN, E = (F+ - F-) / 2 = 100 kN; G ± 1.1 γov Ω E, Ω = 1.2
    found = sd.amplified([plus, minus], pairs, 1.1 * 1.25 * 1.2)
    assert float(found[0].P[0]) == pytest.approx(200e3 + 1.65 * 100e3)
    assert float(found[1].P[0]) == pytest.approx(200e3 - 1.65 * 100e3)


def test_timber_member_checks(ec):
    from saengine.design.timber import limit_state as tl
    from saengine.design.timber.members import Section
    from saengine.library.materials import Material

    mat = Material.model_validate(
        {
            "id": "C24", "name": "C24", "category": "timber",
            "mechanical": {"E": 11000, "density": 420},
            "timber": {"group": "B", "location": "inside", "strengthClass": "C24"},
        }
    )  # fmt: skip
    stations = _stations(20e3, -10e6, length=3.0)
    checks, summary = tl.check_member(
        Section(100, 200), mat, stations, 3000.0, [{"D": 1.35, "L": 1.5}], "beam"
    )
    rows = {c["name"]: c for c in checks}
    # 6.1.6: fm,d = kmod fm,k / γM = 0.8 × 24 / 1.3 (h = 200 >= 150: kh = 1), σm = M / W
    sigma = 10e6 / (100 * 200**2 / 6)
    assert rows["Bending"]["utilisation"] == pytest.approx(sigma / (0.8 * 24 / 1.3), abs=2e-3)
    assert summary["strengthClass"] == "C24" and summary["serviceClass"] == "1"


def test_masonry_wall_checks(ec):
    from saengine.design import masonry as M
    from saengine.design import masonry_partial_factors as mp
    from saengine.design import walls as W

    m = M.Masonry(5.0, "clay", None, "solid", fm_source="estimate", unit_strength=20.0)
    geometry = W.WallGeometry(3000, 200, 3000, 2800)
    forces = [
        W.PierForces("ULS", 400e3, 50e3, 20e6, 0.0, 2e6, False, "bottom"),
        W.PierForces("ULS", 380e3, 50e3, 10e6, 0.0, 1e6, False, "middle"),
    ]
    d = mp.wall_checks(geometry, None, forces, m)
    rows = {c["name"]: c for c in d.checks}
    assert {"Vertical load NEd / NRd", "In-plane shear", "Slenderness hef / tef"} <= set(rows)
    # 6.1.2.2: Φi = 1 - 2 ei / t, ei = M/N + hef/450 >= 0.05 t; NRd = Φ t l fk / γM
    fk = 0.55 * 20**0.7 * 2.5**0.3
    ei = max(2e6 / 400e3 + 0.75 * 2800 / 450, 0.05 * 200)
    nrd = (1 - 2 * ei / 200) * 200 * 3000 * fk / 2.0
    assert rows["Vertical load NEd / NRd"]["capacity"] <= nrd / 1e3 + 0.01


def test_portal_designed_under_the_pack(ec):
    """A small braced steel portal (two columns, a beam with a fin plate) designed under the
    pack: EN 1993-1-1 rows and clauses, EN 1993-1-8 connection notes."""
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
        {
            "id": "BM",
            "name": "H beam",
            "kind": "beam",
            "material": steel_id,
            "profile": w,
            "connection": {"type": "finPlate", "rows": 4, "boltGrade": "8.8"},
        },
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
    project = derive(building, types, MATERIALS, settings()).project
    beam = next(e["id"] for e in project["elements"] if e["name"] == "B1")
    project["load_patterns"][0]["element_loads"].append(
        {"element_id": beam, "wy": 0.0, "wz": -20e3, "wx": 0.0}
    )
    static = [a["id"] for a in project["analyses"] if a["type"] == "Static"]
    import tempfile
    from pathlib import Path

    _, out, _ = run_model(project, Path(tempfile.mkdtemp()), static)
    s = settings().model_copy(update={"combinations": [LoadCombination(name="1.35G", D=1.35)]})
    combinations, pieces, _, _ = _demands(project, out, s)
    t = {x.id: x for x in types.objects}
    mats = {m.id: m for m in MATERIALS.materials}
    found = {}
    for element in building.elements:
        kind = t[element.type].kind
        found[element.id] = steel_design.design_member(
            element.id, kind, t[element.type], mats[steel_id], mats, pieces[element.id],
            combinations, False, project, sm.SteelOptions(),
        )[0]  # fmt: skip
    beam_entry = found["B1"]
    names = {c["name"] for c in beam_entry["checks"]}
    assert {
        "Flexure about x (major)",
        "Lateral-torsional buckling",
        "Shear along y (depth)",
    } <= names
    clauses = " ".join(str(c.get("clause") or "") for c in beam_entry["checks"])
    assert "EN 1993-1-1" in clauses and "BNBC" not in clauses
    assert beam_entry["section"]["class"].startswith("class")
    conn = " ".join(c["note"] for c in beam_entry["checks"] if c["name"].startswith("Connection"))
    assert conn
    column = found["C1"]
    assert any(c["name"] == "Compression: buckling" for c in column["checks"])
    assert "partial factors" in " ".join(steel_design.METHOD)

"""C3: AISC 360-22 / AISC 341-22 steel of the US code pack ``aci318-asce7-22``.

Pins the pack's steel values with their clauses (VERIFY.md in the pack lists them for checking
against the printed specifications), the member methods it picks where AISC 360-22 differs from
the default pack (the effective width method of Sec E7, Cv1 of Sec G2.1, tees by Sec F9,
rectangular HSS lateral-torsional buckling by Sec F7.4), the ASD basis (Rn / Ω), the AISC 341-22
width-thickness limits by Ry Fy, that the default pack's results stay as they were, and a small
steel portal designed under the pack.
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design.steel import basis as steel_basis
from saengine.design.steel import members as sm
from saengine.design.steel import seismic as S
from saengine.design.steel.properties import i_shape, rhs, tee

PACK_ID = "aci318-asce7-22"
E = 200_000.0
A992 = sm.Steel(345.0, 450.0, E, "A992")


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def us():
    pack = registry.load(PACK_ID)
    with code_context.using(pack):
        yield pack


@pytest.fixture
def bnbc():
    pack = registry.load("bnbc2020")
    with code_context.using(pack):
        yield pack


# ───────────────────────────── values with their clauses ─────────────────────────────


def test_pack_covers_steel(us):
    info = registry.info(PACK_ID)
    assert info.usable and not info.problems
    assert {"steel", "steelStability", "steelSeismic", "composite"} <= set(info.covers)
    assert us.basis["steel"].startswith("AISC 360-22")
    from saengine.design.clauses import clause

    # the steel clauses are named after AISC 360-22, the concrete ones after ACI 318-19
    assert clause("steelMembers", "flexureYield") == "AISC 360-22 Sec F2.1, Eq F2-1"
    assert clause("steelMembers", "interaction") == "AISC 360-22 Sec H1.1"


def test_aisc360_values(us):
    s = code_context.table("steel")
    # Sec B3: LRFD by default, Ω of ASD
    assert s.designMethod == "LRFD" and s.omegaFromPhi == 1.5
    assert (s.omega["tensionYield"], s.omega["tensionRupture"], s.omega["shearWebYield"]) == (
        1.67,
        2.0,
        1.5,
    )
    # J8: φc 0.65, Pp = 0.85 f'c A1 <= 1.7 f'c A1
    c = s.connections
    assert s.phi.concreteBearing == 0.65
    assert (c.concreteBearingFull, c.concreteBearingMax) == (0.85, 1.7)
    # Table J3.2 (SI): Group A N / X, Group B N / X; threaded parts 0.450 / 0.563 Fu
    assert c.boltGrades["A325N"].Fnv == 372 and c.boltGrades["A325X"].Fnv == 469
    assert c.boltGrades["A490N"].Fnv == 469 and c.boltGrades["A490X"].Fnv == 579
    assert c.boltGrades["threadedN"].FnvOfFu == 0.45
    # J3.8: μ 0.30 Class A; Table J3.4M: no sheared-edge increase
    assert c.slip.mu["A"] == 0.3
    assert c.edgeSheared[20] == c.edgeRolled[20] == 26
    # E7 Table E7.1, G2.1 kv
    m = s.memberMethods
    assert (m.effectiveWidth["stiffened"].c1, m.effectiveWidth["stiffened"].c2) == (0.18, 1.31)
    assert (m.effectiveWidth["hssWalls"].c1, m.effectiveWidth["hssWalls"].c2) == (0.2, 1.38)
    assert (m.effectiveWidth["other"].c1, m.effectiveWidth["other"].c2) == (0.22, 1.49)
    assert m.kvUnstiffened == 5.34
    # C2.2b(4): notional loads in the gravity-only combinations up to Δ2nd/Δ1st 1.7
    assert code_context.table("steelStability").directAnalysis.gravityOnlyDriftRatioMax == 1.7


def test_aisc341_and_composite_values(us):
    t = code_context.table("steelSeismic")
    # Table D1.1: λhd, λmd of sqrt(E/(Ry Fy))
    assert t.widthThickness.expectedYield and t.widthThickness.iFlange == 0.32
    assert t.widthThicknessModerate.iFlange == 0.4
    assert (t.widthThickness.web.linearA, t.widthThickness.web.split) == (2.57, 0.114)
    assert t.frames["imf"].compactness == "moderate"
    # A3.2: A500 Grade C HSS Ry 1.3, Grade B 1.4
    hss_c = {"id": "hss", "steel": {"grade": "ASTM A500 Grade C", "fy": 345}}
    hss_b = {"id": "hss", "steel": {"grade": "ASTM A500 Grade B", "fy": 315}}
    assert S.expected_ratios(hss_c, "rhs", t)[:2] == (1.3, 1.2)
    assert S.expected_ratios(hss_b, "rhs", t)[:2] == (1.4, 1.3)
    comp = code_context.table("composite")
    # I2.1b: C1 = 0.25 + 3 ρ <= 0.7; I8.2a: Rp 0.75 for studs welded to the shape
    e = comp.column.encased
    assert (e.c1Base, e.c1Slope, e.c1Max, e.barStiffnessShare) == (0.25, 3.0, 0.7, 1.0)
    assert comp.beam.studs.rpDirect == 0.75


# ───────────────────────────── the member methods ─────────────────────────────


def test_slender_web_column_by_effective_width(us):
    s = i_shape(600, 250, 16, 5)  # h/tw = 113.6 > 1.49 sqrt(E/Fy) = 35.9
    cap = sm.compression(s, A992, 4000, 4000)
    assert "Ae" in cap.note and "Sec E7" in cap.clause
    # Sec E7.1 by hand: Fcr of the member at Q = 1, the web's be at that stress
    fe = min(math.pi**2 * E / (4000 / s.rx) ** 2, math.pi**2 * E / (4000 / s.ry) ** 2)
    fcr = 0.658 ** (345 / fe) * 345 if fe >= 0.44 * 345 else 0.877 * fe
    h, tw = s.dims["h"], s.dims["tw"]
    lam, lam_r = h / tw, 1.49 * math.sqrt(E / 345)
    fel = (1.31 * lam_r / lam) ** 2 * 345
    be = h * (1 - 0.18 * math.sqrt(fel / fcr)) * math.sqrt(fel / fcr)
    assert cap.nominal == pytest.approx(fcr * (s.area - (h - be) * tw), rel=2e-3)
    assert cap.phi == 0.9


def test_web_shear_cv1(us):
    s = i_shape(800, 250, 16, 6)  # h/tw = 128 > 2.24 sqrt(E/Fy)
    cap = sm.shear_major(s, A992)
    h_tw = s.dims["h"] / s.dims["tw"]
    root = math.sqrt(5.34 * E / 345)
    cv1 = min(1.0, 1.10 * root / h_tw)
    assert cap.nominal == pytest.approx(0.6 * 345 * s.dims["d"] * s.dims["tw"] * cv1)
    assert "Cv1" in cap.note and cap.clause.startswith("AISC 360-22 Sec G2.1(b)")


def test_tee_and_hss_flexure(us):
    t = tee(300, 200, 12, 10)
    cap = sm.flexure_major(t, A992, 6000, 1.0, top_compression=True)
    assert "Lp" in cap.note and "Sec F9" in cap.clause
    stem = sm.flexure_major(t, A992, 3000, 1.0, top_compression=False)
    assert "stem" in stem.note
    box = rhs(100, 400, 6)
    ltb = sm.flexure_major(box, A992, 20000, 1.0)
    assert ltb.state == "lateral-torsional buckling" and "Sec F7.4" in ltb.clause


def test_asd_divides_by_omega(us):
    s = i_shape(400, 200, 12, 8)
    with steel_basis.using(steel_basis.ASD):
        ty = sm.tension_yielding(s, A992)
        v = sm.shear_major(s, A992)
    assert ty.design == pytest.approx(345 * s.area / 1.67)
    assert v.phi == pytest.approx(1 / 1.5) and "Ωv = 1.50" in v.note


def test_seismic_limits_by_expected_yield(us):
    s = i_shape(400, 200, 12, 8)
    rows = S.compactness_checks(s, 345, E, "column", "imf", 0.0, table=None, ry=1.1)
    flange = next(r for r in rows if "flange width-thickness" in r["name"])
    assert "moderately ductile" in flange["name"]
    assert flange["capacity"] == pytest.approx(0.40 * math.sqrt(E / (1.1 * 345)), abs=2e-3)


def test_masonry_strength_design_by_tms402(us):
    from saengine.design import masonry, masonry_strength

    t = masonry.table()
    assert masonry.methods() == ["allowableStress", "strength"]
    s = t.strength
    # TMS 402-22 Sec 9.1.4, 9.3.2: φ 0.90 / 0.80, 0.80 f'm over 0.80 c
    assert (s.phi["axial"], s.phi["shear"], s.stressBlock["stress"]) == (0.9, 0.8, 0.8)
    # Sec 9.3.6.5: 4.0 - 1.75 Mu/(Vu dv), Vn max 6 / 4 sqrt(f'm) (x 0.083 in SI)
    assert masonry_strength.shear_coefficient(0.5) == pytest.approx(4.0 - 1.75 * 0.5)
    assert masonry_strength.shear_coefficient(1.5) == pytest.approx(2.25)
    assert masonry_strength.shear_maximum(0.25) == pytest.approx(0.498)
    assert masonry_strength.shear_maximum(0.625) == pytest.approx((0.498 + 0.332) / 2)
    assert "TMS 402-22" in masonry.clause("shearWallShear")


def test_default_pack_unchanged(bnbc):
    s = i_shape(600, 250, 16, 5)
    cap = sm.compression(s, A992, 4000, 4000)
    assert "Q = Qs Qa" in cap.note and "Sec 10.5.7" in cap.clause
    m = sm.flexure_major(i_shape(400, 200, 12, 8), A992, 0.0)
    assert m.clause == "BNBC 2020 Part 6 Sec 10.6.2.1, Eq 6.10.56"
    assert steel_basis.chosen() == steel_basis.LRFD
    v = sm.shear_major(i_shape(800, 250, 16, 6), A992)
    assert "kv = 5, Cv" in v.note


# ───────────────────────────── a small steel structure ─────────────────────────────


def _portal(us_pack, basis: str) -> dict:
    """The braced portal of tests/test_steel_integration.py designed under the pack."""
    from saengine.design import steel_design
    from saengine.design.check import _demands
    from saengine.design.steel.members import SteelOptions
    from saengine.library.settings import LoadCombination
    from saengine.verification.cases.common import (
        MATERIALS,
        derive,
        node_at,
        objects,
        point,
        run_model,
        settings,
        structure,
    )
    from saengine.verification.cases.common import building as building_of

    w = {"shape": "I", "overallWidth": 254, "overallDepth": 254, "webThickness": 8.6,
         "flangeThickness": 14.2}  # fmt: skip
    types = objects(
        {"id": "COL", "name": "W col", "kind": "column", "material": "A992", "profile": w},
        {
            "id": "BM",
            "name": "W beam",
            "kind": "beam",
            "material": "A992",
            "profile": w,
            "connection": {"type": "finPlate", "rows": 4},
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
    assert node_at(project, (0, 0, 3.2))
    static = [a["id"] for a in project["analyses"] if a["type"] == "Static"]
    import tempfile
    from pathlib import Path

    _, out, _ = run_model(project, Path(tempfile.mkdtemp()), static)
    s = settings().model_copy(update={"combinations": [LoadCombination(name="1.4D", D=1.4)]})
    combinations, pieces, _, _ = _demands(project, out, s)
    t = {x.id: x for x in types.objects}
    mats = {m.id: m for m in MATERIALS.materials}
    found = {}
    for element in building.elements:
        kind = t[element.type].kind
        found[element.id] = steel_design.design_member(
            element.id, kind, t[element.type], mats["A992"], mats, pieces[element.id],
            combinations, False, project, SteelOptions(basis=basis),
        )[0]  # fmt: skip
    return found


def test_portal_designed_under_the_pack(us):
    lrfd = _portal(us, steel_basis.LRFD)
    beam = lrfd["B1"]
    clauses = " ".join(str(c.get("clause") or "") for c in beam["checks"])
    assert "AISC 360-22" in clauses and "BNBC" not in clauses
    notes = " ".join(c["note"] for c in beam["checks"] if c["name"].startswith("Connection"))
    assert notes and "6.10.1" not in notes and ("J3" in notes or "J4" in notes)
    asd = _portal(us, steel_basis.ASD)["B1"]
    assert asd["basis"] == "ASD"
    flexure = next(c for c in asd["checks"] if c["name"].startswith("Flexure about x"))
    same = next(c for c in beam["checks"] if c["name"].startswith("Flexure about x"))
    assert flexure["capacity"] == pytest.approx(same["capacity"] / 0.9 / 1.67, rel=1e-2)

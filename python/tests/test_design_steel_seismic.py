"""B35: steel seismic provisions, general requirements and moment frames (the code pack's
``steelSeismic`` table, BNBC 2020 Part 6 Sec 10.20.1-10.20.12, Tables 6.10.17-6.10.18)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from saengine.codes.tables import builtin_table
from saengine.design.steel import seismic as ss
from saengine.library.steel_sections import find

T = builtin_table("steelSeismic")


def _settings(system="steelSmf", r=None, rsa=True, offsets=True, factor=0.5):
    return SimpleNamespace(
        seismic=SimpleNamespace(
            system=system, r=r, systemY=None, otherSystems=[], otherSystemsY=[]
        ),
        analysis=SimpleNamespace(responseSpectrum=rsa, endOffsets=offsets, rigidZoneFactor=factor),
    )


def _steel(grade, fy, fu=450.0, standard=None):
    return {
        "id": grade,
        "name": f"Structural steel {grade}",
        "steel": {"grade": grade, "fy": fy, "fu": fu},
        "source": {"standard": standard},
    }


# ─────────────────────────────── the pack's values (with clauses) ───────────────────────────────


def test_pack_values():
    # Sec 10.1.1.2, 10.20.1: R above 3.
    assert T.trigger.rAbove == 3.0
    # Sec 10.20.4.1: Ω0 2.0 when not given.
    assert T.omegaDefault == 2.0
    # Sec 10.20.6.1: 345 MPa (SMF, IMF, STMF), 380 MPa (OMF).
    assert T.frames["smf"].fyLimit == 345 and T.frames["omf"].fyLimit == 380
    # Table 6.10.17.
    rows = T.expected.rows
    assert (rows["shapesA36"].Ry, rows["shapesA36"].Rt) == (1.5, 1.2)
    assert (rows["shapesA572g42"].Ry, rows["shapesA572g42"].Rt) == (1.3, 1.1)
    assert (rows["shapesA572g50"].Ry, rows["shapesA572g50"].Rt) == (1.1, 1.1)
    assert (rows["hss"].Ry, rows["hss"].Rt) == (1.4, 1.3)
    assert (rows["pipe"].Ry, rows["pipe"].Rt) == (1.6, 1.2)
    # Table 6.10.18.
    w = T.widthThickness
    assert (w.iFlange, w.smfBeamWeb, w.rectHss, w.roundHss) == (0.30, 2.45, 0.64, 0.044)
    # Sec 10.20.9: φv 1.0, Eq 6.10.299 /90, Eq 6.10.300 > 1.0, Lb 0.086 ry E/Fy.
    smf = T.frames["smf"]
    assert (smf.panelZonePhi, smf.panelThicknessDivisor, smf.momentRatio) == (1.0, 90, 1.0)
    assert (smf.beamBracing, smf.braceStrength, smf.driftAngle) == (0.086, 0.06, 0.04)
    # Sec 10.20.10: 0.02 rad, Lb 0.17 ry E/Fy.
    assert (T.frames["imf"].driftAngle, T.frames["imf"].beamBracing) == (0.02, 0.17)
    # Sec 10.20.11.5: 0.54, bf/6.
    assert (T.frames["omf"].continuityCoefficient, T.frames["omf"].continuityWidthRatio) == (
        0.54,
        6,
    )
    # Sec 10.20.8.3, 10.20.8.4.
    assert T.columns.axialRatio == 0.4
    assert (T.splices.distance, T.splices.shortStorey) == (1200, 2400)
    # Sec 10.20.12.
    assert (T.truss.spanMax, T.truss.depthMax, T.truss.vneMoment) == (20000, 1800, 3.75)


# ─────────────────────────────────────── when they apply ───────────────────────────────────────


def test_provisions_by_system_and_r():
    p = ss.provisions(_settings("steelSmf"), T)
    assert p.applies and p.frame == "smf" and p.r == 8.0
    assert ss.provisions(_settings("steelOmf"), T).frame == "omf"  # R 3.5 > 3
    low = ss.provisions(_settings("steelOmf", r=3.0), T)
    assert not low.applies and "not above 3" in low.reason
    assert not ss.provisions(_settings("rcSmf"), T).applies
    assert ss.provisions(_settings("steelDualImfScbf"), T).frame == "imf"


def test_expected_ratios():
    assert ss.expected_ratios(_steel("ASTM A992", 345), "I", T)[:2] == (1.1, 1.1)
    assert ss.expected_ratios(_steel("ASTM A36", 250), "I", T)[:2] == (1.5, 1.2)
    assert ss.expected_ratios(_steel("ASTM A572 Grade 42", 290), "I", T)[:2] == (1.3, 1.1)
    assert ss.expected_ratios(_steel("ASTM A500 Grade B", 315), "rhs", T)[:2] == (1.4, 1.3)
    # A36 tube: no row, the table's largest (SAEngine practice).
    assert ss.expected_ratios(_steel("ASTM A36", 250), "rhs", T)[:2] == (1.6, 1.3)


# ─────────────────────────────────────── width-thickness ───────────────────────────────────────


def test_web_limit_least_of_printed_and_swapped():
    root = math.sqrt(200_000 / 345)
    # Ca = 0: printed 1.12 √(E/Fy) (2.33 - Ca) (62.8), swapped 3.14 √(E/Fy) (75.6): the least.
    assert ss.web_limit(0.0, root, T) == pytest.approx(1.12 * root * 2.33)
    # Ca = 0.5: printed 3.14 √(E/Fy)(1 - 1.54 Ca) is the least.
    assert ss.web_limit(0.5, root, T) == pytest.approx(3.14 * root * (1 - 1.54 * 0.5))


def test_seismically_compact_flange():
    from saengine.design.steel.properties import i_shape

    shape = i_shape(400, 180, 13.5, 8.6, 21)
    checks = ss.compactness_checks(shape, 345, 200_000, "beam", "smf", 0.0, table=T)
    flange = next(c for c in checks if "flange" in c["name"])
    assert flange["capacity"] == pytest.approx(0.30 * math.sqrt(200_000 / 345), abs=1e-3)
    assert flange["demand"] == pytest.approx(90 / 13.5, abs=1e-3)
    assert flange["ok"]
    assert ss.compactness_checks(shape, 345, 200_000, "beam", "omf", 0.0, table=T) == []


# ─────────────────────────────────────────── members ───────────────────────────────────────────


def test_material_limit_and_bracing():
    (fy,) = ss.material_checks("beam", 380, "smf", T)
    assert not fy["ok"] and fy["capacity"] == 345
    from saengine.design.steel.properties import i_shape

    shape = i_shape(400, 180, 13.5, 8.6, 21)
    rows = ss.beam_bracing_checks(shape, 345, 200_000, 1.1, 3000, "smf", T)
    limit = 0.086 * shape.ry * 200_000 / 345
    assert rows[0]["capacity"] == pytest.approx(limit, abs=1e-2)
    assert rows[1]["flag"]


def test_column_strength_amplified():
    rows = ss.column_strength_checks(
        500e3, 1000e3, [("Ω0: a", 1200e3), ("Ω0: b", -100e3)], 2000e3, T
    )
    assert not rows[0]["ok"] and rows[0]["demand"] == pytest.approx(1200)
    assert rows[1]["ok"]
    assert ss.column_strength_checks(300e3, 1000e3, [], 2000e3, T) == []  # 0.3 ≤ 0.4


# ───────────────────────────────────── connections and joints ─────────────────────────────────────


def test_connection_shear_eq_298():
    b = ss.connection_shear(ss.BeamHinge("B1", 1.1, 345, 1e6, 400, 13.5, 6000, 200, 50e3), "smf", T)
    mexp = 1.1 * 1.1 * 345 * 1e6
    assert b.ev == pytest.approx(2 * mexp / 6000)
    assert b.vu == pytest.approx(50e3 + 2 * mexp / 6000)
    assert b.m_face == pytest.approx(mexp + b.vu * 200)


def test_moment_ratio_eq_300():
    b = ss.connection_shear(ss.BeamHinge("B1", 1.1, 345, 1e6, 400, 13.5, 6000, 200, 0.0), "smf", T)
    cols = [ss.JointColumnSide(2e6, 345, 15000, 1000e3)] * 2
    check, ratio = ss.moment_ratio_check(cols, [b], 300, False, "x", T)
    mpc = 2 * 2e6 * (345 - 1000e3 / 15000)
    mpb = b.m_expected + b.vu * (200 + 150)
    assert ratio == pytest.approx(mpc / mpb)
    assert check["ok"] == (ratio > 1.0)
    # A weak column fails.
    weak = [ss.JointColumnSide(0.5e6, 345, 15000, 1000e3)] * 2
    check, ratio = ss.moment_ratio_check(weak, [b, b], 300, False, "x", T)
    assert ratio < 1.0 and not check["ok"]
    # Top storey, light axial: exempt (flag).
    light = [ss.JointColumnSide(0.5e6, 345, 15000, 10e3)]
    check, _ = ss.moment_ratio_check(light, [b, b], 300, True, "x", T)
    assert check["flag"]


def test_panel_zone_thickness_eq_299():
    column = find("HEB 300")
    b = ss.connection_shear(
        ss.BeamHinge("B1", 1.1, 345, 1.3e6, 400, 13.5, 6000, 200, 0.0), "smf", T
    )
    rows = ss.panel_zone_checks(column, 345, [b], 0.2, True, 0.0, T)
    thick = next(r for r in rows if "thickness" in r["name"])
    assert thick["demand"] == pytest.approx(((400 - 27) + (300 - 2 * 19)) / 90, abs=1e-3)
    shear = rows[0]
    assert shear["demand"] == pytest.approx(b.m_face / (400 - 13.5) / 1e3, rel=1e-3)


def test_continuity_plates_omf():
    rows = ss.continuity_plate_checks(10, 200, 15, 345, 345, False, None, T)
    assert not rows[0]["ok"]  # 10 < 0.54 √(200 × 15)
    rows = ss.continuity_plate_checks(10, 200, 15, 345, 345, True, 12.0, T)
    assert rows[0]["demand"] == 15 and not rows[0]["ok"]  # two-sided: tbf


def test_splice_location():
    assert not ss.splice_location_check(1000, 3500, T)["ok"]
    assert ss.splice_location_check(1300, 3500, T)["ok"]
    assert ss.splice_location_check(1100, 2200, T)["ok"]  # short storey: mid height


def test_base_demands():
    v, m = ss.base_demands(1.1, 345, 1e6, 3500, 1e9, 1e12, T)
    assert v == pytest.approx(2 * 1.1 * 345 * 1e6 / 3500)
    assert m == pytest.approx(1.1 * 1.1 * 345 * 1e6)


def test_truss_vne_eq_302():
    s = ss.TrussSegment(
        span=15000,
        depth=1500,
        segment_start=6000,
        segment_length=3000,
        panel_length=1500,
        ry=1.1,
        chord_mnc=100e6,
        chord_ei=2e13,
        chord_fy=345,
        chord_area=4000,
        chord_axial=200e3,
        diagonal_pnt=300e3,
        diagonal_pnc=100e3,
        angle=math.radians(45),
    )
    expected = (
        3.75 * 1.1 * 100e6 / 3000
        + 0.075 * 2e13 * (15000 - 3000) / 3000**3
        + 1.1 * (300e3 + 0.3 * 100e3) * math.sin(math.radians(45))
    )
    assert ss.expected_truss_shear(s, T) == pytest.approx(expected)
    assert all(c["ok"] for c in ss.truss_checks(s, T))


def test_panel_zone_drift_model():
    assert not ss.panel_zone_model_check(_settings(), "smf", T)["ok"]
    assert ss.panel_zone_model_check(_settings(factor=0.0), "smf", T)["ok"]
    assert ss.panel_zone_model_check(_settings(rsa=False), "smf", T) is None


# ─────────────────────────────── integration: a steel moment portal ───────────────────────────────


def test_moment_portal_gets_the_seismic_checks(tmp_path):
    from saengine.design import steel_design
    from saengine.design.check import _demands
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

    w = {
        "shape": "I",
        "overallWidth": 254,
        "overallDepth": 254,
        "webThickness": 8.6,
        "flangeThickness": 14.2,
    }
    types = objects(
        {"id": "COL", "name": "W col", "kind": "column", "material": "A992", "profile": w},
        {"id": "BM", "name": "W beam", "kind": "beam", "material": "A992", "profile": w},
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
    s = settings(system="steelSmf")
    project = derive(building, types, MATERIALS, s).project
    top = node_at(project, (0, 0, 3.2))
    wx = next(p for p in project["load_patterns"] if p["name"] == "WX")
    wx["nodal_loads"] = [{"node_id": top, "forces": [50e3, 0, 0, 0, 0, 0]}]
    static = [a["id"] for a in project["analyses"] if a["type"] == "Static"]
    _, out, _ = run_model(project, tmp_path, static)
    s = s.model_copy(update={"combinations": [LoadCombination(name="1.2D+1.0WX", D=1.2, WX=1.0)]})
    combinations, pieces, _, _ = _demands(project, out, s)
    by_type = {t.id: t for t in types.objects}
    mats = {m.id: m for m in MATERIALS.materials}
    members = []
    for element in building.elements:
        t = by_type[element.type]
        entry, _ = steel_design.design_member(
            element.id,
            t.kind,
            t,
            mats[t.material],
            mats,
            pieces[element.id],
            combinations,
            False,
            project,
        )
        members.append(
            ss.SteelMember(
                element.id, t.kind, element, t, mats[t.material], pieces[element.id], False, entry
            )
        )
    found = ss.apply(project, building, by_type, mats, members, combinations, [], s)
    assert found["applies"] and found["frame"] == "smf"
    assert found["members"]["B1"]["Ry"] == 1.1  # A992, Table 6.10.17
    beam = next(m.entry for m in members if m.id == "B1")
    names = {c["name"] for c in beam["checks"]}
    assert "Seismic: connection shear at the expected moments" in names
    assert any(n.startswith("Seismic: flange width-thickness") for n in names)
    column = next(m.entry for m in members if m.id == "C1")
    assert any(c["name"].startswith("Seismic: ") for c in column["checks"])
    # The default rigid zone factor 0.5 leaves the panel zones out of the drift.
    assert not found["checks"][0]["ok"]

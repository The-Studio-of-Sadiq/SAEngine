"""B32: steel-concrete composite beams, columns and connections under the bnbc2020 pack's
``composite`` table (BNBC 2020 Part 6 Chapter 13, part 2 pp. 370-390; Sec 6.3.13)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes.tables import builtin_table
from saengine.design.steel import composite as cp
from saengine.design.steel.lengths import MemberLengths
from saengine.design.steel.members import Stations
from saengine.design.steel.properties import i_shape, rhs
from saengine.library.materials import Material
from saengine.library.objects import (
    Beam,
    Column,
    CompositeBeam,
    CompositeColumn,
    CompositeDeck,
    IShapeProfile,
    ShearConnectors,
)

T = builtin_table("composite")
STEEL = Material.model_validate(
    {
        "id": "S345",
        "name": "S345",
        "category": "steel",
        "mechanical": {"E": 200000, "density": 7850},
        "steel": {"fy": 345, "fu": 450},
    }
)
C25 = Material.model_validate(
    {
        "id": "C25",
        "name": "C25",
        "category": "concrete",
        "mechanical": {"E": 23500, "density": 2400},
        "concrete": {"fc": 25},
    }
)
C30 = C25.model_copy(update={"id": "C30", "concrete": C25.concrete.model_copy(update={"fc": 30})})
EC25 = 0.043 * 2400**1.5 * math.sqrt(25)
W450 = i_shape(450, 200, 14, 9)


def _beam_stations(span: float = 8.0, mu: float = 800e6, name: str = "1.2D + 1.6L") -> Stations:
    """A simply supported beam's parabolic moment (sagging: Mx negative)."""
    s = np.linspace(0, span, 21)
    m = -4 * mu * s * (span - s) / span**2
    z = np.zeros_like(s)
    return Stations(name, s, z, m, z, z, z, [f"B1 at {x:.2f}" for x in s])


# ──────────────────────────────────────── the pack ────────────────────────────────────────


def test_pack_values_and_clauses():
    # Sec 13.1.2 (p. 370), 13.2.1.2 (p. 373), 13.3.2.1 (p. 381), 13.3.4 (p. 387).
    assert T.method == "plasticStress"
    assert (T.materials.concreteMin, T.materials.concreteMaxNormal) == (21, 70)
    assert T.materials.concreteMaxLight == 42 and T.materials.steelFyMax == 525
    assert T.modulus.steel == 210000 and T.modulus.concreteCoefficient == 0.043
    assert (T.phi.compression, T.phi.tension, T.phi.flexure, T.phi.bearing) == (
        0.75,
        0.9,
        0.9,
        0.65,
    )
    assert T.phi.flexureEncasedComposite == 0.85 and T.omega.flexureEncasedComposite == 1.76
    assert (T.column.buckling.ratio, T.column.buckling.base) == (0.44, 0.658)
    assert T.column.buckling.elastic == 0.877
    assert T.column.encased.c1Max == 0.3 and T.column.filled.c3Max == 0.9
    assert (T.column.filled.c2Rectangular, T.column.filled.c2Circular) == (0.85, 0.95)
    assert T.column.connectorSpacingMax == 405
    assert T.beam.webCompact == 3.76 and T.beam.spanShare == 0.125
    s = T.beam.studs
    assert (s.rgOne, s.rgTwo, s.rgThreeOrMore) == (1.0, 0.85, 0.7)
    assert (s.rpDirect, s.rpStrong, s.rpWeak) == (1.0, 0.75, 0.6)
    assert (T.beam.spacing.longitudinal, T.beam.spacing.max) == (6, 900)
    assert (T.beam.deflection.coefficient, T.beam.deflection.exponent) == (0.85, 0.25)
    assert T.connections.seismicReduction == 0.25
    assert "13.3.2.4.3" in T.sources["stud"] and "p. 384" in T.sources["stud"]


# ─────────────────────────────────────── connectors ───────────────────────────────────────


def test_concrete_modulus_eq_6_13_5():
    assert cp.concrete_modulus(25, 2400, T) == pytest.approx(EC25)
    # wc clamped to 1500-2500 kg/m³
    assert cp.concrete_modulus(25, 2600, T) == pytest.approx(0.043 * 2500**1.5 * 5)


def test_stud_strength_eq_6_13_24():
    concrete = cp.concrete_of(C25, T)
    asc = math.pi * 19**2 / 4
    assert cp.stud_strength(19, 450, concrete, T) == pytest.approx(
        min(0.5 * asc * math.sqrt(25 * EC25), asc * 450)
    )
    # Rg Rp cap: two studs in a perpendicular rib, weak position: 0.85 × 0.60
    rg, rp = cp.stud_factors(CompositeDeck(), 2, None, T)
    assert (rg, rp) == (0.85, 0.6)
    assert cp.stud_strength(19, 450, concrete, T, rg, rp) == pytest.approx(0.85 * 0.6 * asc * 450)
    assert cp.stud_factors(CompositeDeck(), 3, 60, T) == (0.7, 0.75)
    assert cp.stud_factors(None, 2, None, T) == (1.0, 1.0)
    wide = CompositeDeck(orientation="parallel", ribHeight=50, ribWidth=100)
    narrow = CompositeDeck(orientation="parallel", ribHeight=50, ribWidth=60)
    assert cp.stud_factors(wide, 1, None, T) == (1.0, 0.75)
    assert cp.stud_factors(narrow, 1, None, T) == (0.85, 0.75)


def test_channel_strength_eq_6_13_25():
    concrete = cp.concrete_of(C25, T)
    assert cp.channel_strength(8, 5, 100, concrete, T) == pytest.approx(
        0.3 * (8 + 0.5 * 5) * 100 * math.sqrt(25 * EC25)
    )


# ─────────────────────────────────────── composite beams ───────────────────────────────────────


def _solid(**kw) -> CompositeBeam:
    return CompositeBeam(concrete="C25", slabThickness=150, deck=None, **kw)


def test_effective_width_sec_13_3_1_2():
    assert cp.effective_width(8000, _solid(), T)[0] == pytest.approx(2000)  # L/8 each side
    narrow = _solid(spacingLeft=1200, spacingRight=None, edgeRight=300)
    assert cp.effective_width(8000, narrow, T)[0] == pytest.approx(600 + 300)


def test_plastic_positive_full_connection_steel_governs():
    geom = cp.beam_geometry(W450, 345, 200000, _solid(), 8000, T)
    as_ = 2 * 200 * 14 + 422 * 9
    found = cp.plastic_positive(geom, 25, 1e12, T)
    a = as_ * 345 / (0.85 * 25 * 2000)
    assert found["governs"] == "steel"
    assert found["Mn"] == pytest.approx(as_ * 345 * (225 + 150 - a / 2), rel=1e-6)


def test_plastic_positive_partial_connection():
    geom = cp.beam_geometry(W450, 345, 200000, _solid(), 8000, T)
    as_ = 2 * 200 * 14 + 422 * 9
    sum_qn = 2000e3
    found = cp.plastic_positive(geom, 25, sum_qn, T)
    a = sum_qn / (0.85 * 25 * 2000)
    cs = (as_ * 345 - sum_qn) / 2
    depth = cs / 345 / 200  # inside the top flange
    y_cs = 150 + depth / 2
    y_t = (as_ * 375 - cs / 345 * y_cs) / (as_ - cs / 345)
    expected = (as_ * 345 - cs) * y_t - sum_qn * a / 2 - cs * y_cs
    assert found["governs"] == "connectors"
    assert found["Mn"] == pytest.approx(expected, rel=1e-6)
    assert found["ratio"] == pytest.approx(sum_qn / (as_ * 345))


def test_effective_inertia_eq_6_13_18():
    assert cp.effective_inertia(100.0, 300.0, 0.5, T) == pytest.approx(100 + 0.85 * 0.5**0.25 * 200)


def test_beam_checks_design_the_studs_and_flag_the_steel_alone():
    beam = _solid(connectors=ShearConnectors(diameter=19, height=100, fu=450))
    flexure = {"name": "Flexure about x (major)", "capacity": 400.0, "note": "", "flag": False}
    found = cp.beam_checks(W450, STEEL, C25, beam, [_beam_stations()], 8.0, flexure, T)
    names = {c["name"]: c for c in found["checks"]}
    positive = names["Composite: positive flexure"]
    assert positive["demand"] == pytest.approx(800.0)
    assert positive["ok"]
    assert found["summary"]["designedSpacing"]
    assert found["summary"]["spacing"] <= min(8 * 150, 900)
    assert "Composite: construction stage (steel alone)" in names
    assert names["Composite: stud length"]["ok"]
    assert found["deflection"]["Ie"] > found["deflection"]["Is"]


def test_deck_rules_sec_13_3_2_3():
    beam = CompositeBeam(
        concrete="C25",
        slabThickness=120,
        deck=CompositeDeck(ribHeight=80, ribWidth=40),
        connectors=ShearConnectors(diameter=22, height=100, spacing=300),
    )
    found = cp.beam_checks(W450, STEEL, C25, beam, [_beam_stations(mu=300e6)], 8.0, None, T)
    names = {c["name"]: c for c in found["checks"]}
    assert not names["Composite: deck rib height"]["ok"]  # 80 > 75
    assert not names["Composite: deck rib width"]["ok"]  # 40 < 50
    assert not names["Composite: stud diameter"]["ok"]  # 22 > 19
    assert not names["Composite: slab above the deck"]["ok"]  # 40 < 50
    assert not names["Composite: stud above the deck"]["ok"]  # 20 < 38
    assert names["Composite: cover above the studs"]["ok"]  # 20 ≥ 13


def test_deflection_profiles_and_shrinkage_rows():
    entry = {
        "composite": {
            "deflection": {
                "Is": 1.0,
                "Ie": 2.0,
                "stiffening": 0.5,
                "creep": 0.15,
                "shored": False,
                "sustained": 0.4,
                "shrinkage": {"delta": 3.0},
                "clause": "Sec 13.3.1.1",
            }
        }
    }
    one = np.ones((2, 3))
    out = cp.scale_profiles(entry, {"D": one, "L": one, "WX": one})
    assert out["D"][0, 0] == pytest.approx(1.0)  # unshored: the steel carries the dead load
    assert out["L"][0, 0] == pytest.approx(0.5 * (1 + 0.15 * 0.4))
    assert out["WX"][0, 0] == pytest.approx(0.5)
    rows = [
        {
            "name": "Deflection: dead + live load ≤ l/240",
            "demand": 10.0,
            "capacity": 20.0,
            "utilisation": 0.5,
            "ok": True,
            "note": "",
            "clause": "x",
        }
    ]
    rows = cp.adjust_deflection_rows(entry, rows)
    assert rows[0]["demand"] == pytest.approx(13.0)
    assert rows[0]["utilisation"] == pytest.approx(0.65)


# ─────────────────────────────────────── composite columns ───────────────────────────────────────


def _col_stations(p: float, mx: float = 0.0) -> Stations:
    s = np.linspace(0, 4.0, 5)
    z = np.zeros_like(s)
    return Stations("1.2D + 1.6L", s, z + p, z + mx, z, z, z, ["C1"] * 5)


def test_encased_column_eqs_6_13_2_to_6_13_7():
    shape = i_shape(250, 250, 14, 9)
    col = CompositeColumn(concrete="C30", width=450, depth=450, bars=4, barDiameter=20)
    lengths = MemberLengths.simple(4.0)
    found = cp.column_checks(shape, STEEL, C30, col, [_col_stations(3000e3)], lengths, False, T)
    as_ = 2 * 250 * 14 + 222 * 9
    asr = 4 * math.pi * 20**2 / 4
    ac = 450 * 450 - as_ - asr
    po = as_ * 345 + asr * 415 + 0.85 * ac * 30
    c1 = min(0.1 + 2 * as_ / (ac + as_), 0.3)
    off = 40 + 10 + 10
    isr_y = asr * (225 - off) ** 2
    ic_y = 450**4 / 12 - shape.iy - isr_y
    ec = 0.043 * 2400**1.5 * math.sqrt(30)
    ei = 210000 * shape.iy + 0.5 * 210000 * isr_y + c1 * ec * ic_y
    pe = math.pi**2 * ei / 4000**2
    pn = po * 0.658 ** (po / pe) if pe >= 0.44 * po else 0.877 * pe
    assert found["summary"]["Po"] == pytest.approx(po / 1e3, abs=1)
    assert found["summary"]["phiPn"] == pytest.approx(0.75 * pn / 1e3, abs=1)
    names = {c["name"]: c for c in found["checks"]}
    assert names["Composite: compression (flexural buckling)"]["ok"]
    # 4 Ø20 in 450×450: 0.0062 Ag passes 0.004, fails the 0.01 detailing minimum
    assert names["Composite: bar ratio ρsr (scope)"]["ok"]
    assert not names["Composite: bar area / Ag (detailing)"]["ok"]
    assert names["Composite: tie area per tie spacing"]["flag"]


def test_plastic_curve_end_points():
    shape = i_shape(250, 250, 14, 9)
    col = CompositeColumn(concrete="C30", width=450, depth=450, bars=4, barDiameter=20)
    sec = cp.column_section(shape, col, 415, T)
    p, m = cp.plastic_curve(sec, 345, 415, 30, "x")
    po = sec.as_ * 345 + sec.asr * 415 + 0.85 * sec.ac * 30
    assert p[0] == pytest.approx(po, rel=1e-3)
    assert p[-1] == pytest.approx(-(sec.as_ * 345 + sec.asr * 415), rel=1e-3)
    assert m.max() > 0 and m[0] == pytest.approx(0, abs=1e3)


def test_filled_rhs_eqs_6_13_13_to_6_13_15_and_walls():
    shape = rhs(300, 300, 10)
    col = CompositeColumn(form="filled", concrete="C30", bars=0)
    lengths = MemberLengths.simple(4.0)
    found = cp.column_checks(shape, STEEL, C30, col, [_col_stations(2000e3)], lengths, False, T)
    ac = 280 * 280
    po = shape.area * 345 + 0.85 * ac * 30
    assert found["summary"]["Po"] == pytest.approx(po / 1e3, abs=1)
    names = {c["name"]: c for c in found["checks"]}
    b_t = names["Composite: wall b/t"]
    assert b_t["capacity"] == pytest.approx(1350 / math.sqrt(345), abs=0.01)
    # Sec 6.3.13.6.1: t ≥ b √(fy / 3Es)
    assert names["Composite: wall thickness"]["capacity"] == pytest.approx(
        300 * math.sqrt(345 / (3 * 200000)), abs=0.01
    )


def test_transfer_studs_eqs_6_13_9_and_6_13_10():
    shape = i_shape(250, 250, 14, 9)
    lengths = MemberLengths.simple(4.0)
    as_fy = (2 * 250 * 14 + 222 * 9) * 345
    for applied, share in (("steel", lambda r: 1 - r), ("concrete", lambda r: r)):
        col = CompositeColumn(
            concrete="C30", width=450, depth=450, loadApplied=applied, transferForce=1000
        )
        found = cp.column_checks(shape, STEEL, C30, col, [_col_stations(3000e3)], lengths, False, T)
        po = found["summary"]["Po"] * 1e3
        studs = next(c for c in found["checks"] if c["name"] == "Composite: load transfer studs")
        assert studs["demand"] == pytest.approx(1000 * share(as_fy / po), rel=1e-3)


def test_bearing_transfer_seismic_reduction_sec_13_4_2_2():
    shape = i_shape(250, 250, 14, 9)
    col = CompositeColumn(
        concrete="C30", width=450, depth=450, loadApplied="bearing", bearingArea=40000
    )
    lengths = MemberLengths.simple(4.0)
    found = cp.column_checks(shape, STEEL, C30, col, [_col_stations(1000e3)], lengths, True, T)
    bearing = next(c for c in found["checks"] if c["name"] == "Composite: bearing on the concrete")
    assert bearing["capacity"] == pytest.approx(0.65 * 1.7 * 30 * 40000 * 0.75 / 1e3, abs=0.01)


# ────────────────────────────────────── the member entry ──────────────────────────────────────


def test_apply_replaces_the_steel_alone_checks_of_a_column():
    profile = IShapeProfile(overallWidth=250, overallDepth=250, webThickness=9, flangeThickness=14)
    column = Column(
        id="C1",
        name="C1",
        material="S345",
        profile=profile,
        composite=CompositeColumn(concrete="C30", width=450, depth=450, bars=8),
    )
    entry = {
        "checks": [
            {
                "name": "Compression: buckling",
                "utilisation": 1.4,
                "ok": False,
                "flag": False,
                "note": "",
            },
            {
                "name": "Shear along y (depth)",
                "utilisation": 0.2,
                "ok": True,
                "flag": False,
                "note": "",
            },
        ],
        "section": {"notes": []},
    }
    cp.apply(
        entry,
        "column",
        column,
        STEEL,
        {"C30": C30},
        [_col_stations(2000e3, 50e6)],
        MemberLengths.simple(4.0),
        ["1.2D + 1.6L"],
        T,
    )
    bare = entry["checks"][0]
    assert bare["flag"] and "composite" in bare["note"]
    assert any(c["name"].startswith("Composite: axial force and flexure") for c in entry["checks"])
    assert entry["composite"]["form"] == "encased"
    assert entry["utilisation"] == max(c["utilisation"] for c in entry["checks"] if not c["flag"])


def test_apply_notes_when_the_concrete_is_missing():
    beam = Beam(
        id="B1",
        name="B1",
        material="S345",
        profile=IShapeProfile(
            overallWidth=200, overallDepth=450, webThickness=9, flangeThickness=14
        ),
        composite=CompositeBeam(concrete="nope"),
    )
    entry = {"checks": [], "section": {"notes": []}}
    cp.apply(entry, "beam", beam, STEEL, {}, [], MemberLengths.simple(8.0), [], T)
    assert "composite action not checked" in entry["section"]["notes"][0]


def test_seismic_membership():
    assert cp._seismic(SimpleNamespace(seismicRole="auto"), ["1.2D + 1.0E + 1.0L"])
    assert not cp._seismic(SimpleNamespace(seismicRole="gravity"), ["1.2D + 1.0E + 1.0L"])
    assert not cp._seismic(SimpleNamespace(seismicRole="auto"), ["1.2D + 1.6L"])

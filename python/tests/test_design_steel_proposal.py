"""Steel design mode: the lightest passing section of the family."""

from __future__ import annotations

import json

import pytest

from saengine.design import steel_proposal as sp
from saengine.library import steel_sections as tbl

A572 = sp.SteelMaterial("A572-50", 345, 450)
BRACE = {
    "id": "BR-SHS",
    "name": "Brace SHS 150",
    "kind": "brace",
    "material": "A572-50",
    "profile": {"shape": "rectangleHollow", "xDim": 150, "yDim": 150, "wallThickness": 8},
}


def _members(compression: float, tension: float, length: float = 4000.0):
    return [
        sp.SteelMemberDemand(
            "E1",
            sp.MemberLengths(length),
            [sp.StationForces("1.2D+E", N=-compression), sp.StationForces("0.9D-E", N=tension)],
        ),
        sp.SteelMemberDemand(
            "E2",
            sp.MemberLengths(length),
            [sp.StationForces("1.2D+E", N=-0.5 * compression)],
        ),
    ]


def test_proposal_picks_the_lightest_passing_section():
    members = _members(400e3, 300e3)
    checker = sp.stub_member_checks
    proposal = sp.steel_design_proposal(
        [BRACE], {"A572-50": A572}, {"BR-SHS": members}, checker=checker
    )
    entry = proposal["types"][0]
    assert entry["status"] == "ok" and entry["family"] == "SHS"
    picked = tbl.find(entry["proposed"]["section"])
    assert entry["governingMember"] == "E1"

    def passes(s):
        return all(sp.utilisation_of(checker(m.forces, s, A572, m.lengths)) <= 1.0 for m in members)

    assert passes(picked)
    # brute force: no lighter SHS passes
    lighter = [s for s in tbl.family("SHS") if s.mass < picked.mass]
    assert lighter and not any(passes(s) for s in lighter)
    assert max(entry["utilisation"].values()) <= 1.0
    assert entry["current"]["section"] == "SHS 150x150x8"


def test_custom_checker_family_choice_and_apply():
    def area_checker(forces, s, m, lengths):
        return [sp._check("area", 3000.0, s.A, "mm²", None)]

    entry = sp.propose_type(
        "BR-SHS",
        "brace",
        "Brace",
        BRACE["profile"],
        _members(1, 1),
        A572,
        family="CHS",
        checker=area_checker,
    )
    expected = tbl.lightest(tbl.family("CHS"), lambda s: s.A >= 3000.0)
    assert entry["proposed"]["section"] == expected.name
    assert not any(c["shape"] == "rectangleHollow" for c in [entry["proposed"]["profile"]])

    objects_text = json.dumps({"schema": "saengine.objects/1", "objects": [BRACE]}, indent=2)
    out = sp.apply_steel_proposal(objects_text, {"types": [entry]})
    new = json.loads(out["objectsText"])["objects"][0]
    assert new["profile"] == expected.profile()
    assert out["changes"][0]["id"] == "BR-SHS"


def test_unchanged_too_small_and_skipped():
    # the current section is already the lightest passing one
    s150 = tbl.find("SHS 150x150x8")

    def exact(forces, s, m, lengths):
        return [sp._check("mass", s150.mass, s.mass + 1e-9, "kg/m", None)]

    entry = sp.propose_type(
        "BR-SHS",
        "brace",
        "Brace",
        BRACE["profile"],
        _members(1, 1),
        A572,
        family="SHS",
        checker=exact,
    )
    assert entry["status"] == "unchanged"

    def never(forces, s, m, lengths):
        return [sp._check("x", 2.0, 1.0, "-", None)]

    small = sp.propose_type(
        "BR-SHS", "brace", "Brace", BRACE["profile"], _members(1, 1), A572, checker=never
    )
    assert small["status"] == "tooSmall" and small["proposed"] is None
    assert "no SHS section passes" in small["tooSmall"]["reason"]

    concrete_brace = {**BRACE, "material": "C24.1"}
    proposal = sp.steel_design_proposal([concrete_brace], {"A572-50": A572}, {})
    assert proposal["types"] == [] and proposal["skipped"][0]["type"] == "BR-SHS"


def test_stub_checks_format_and_material():
    s = tbl.find("IPE 300")
    checks = sp.stub_member_checks(
        [sp.StationForces("c", N=-200e3, Mx=80e6, Vx=100e3)], s, A572, sp.MemberLengths(3000)
    )
    keys = {
        "name",
        "demand",
        "capacity",
        "unit",
        "utilisation",
        "combination",
        "ok",
        "note",
        "flag",
    }
    assert all(set(c) == keys for c in checks)
    names = {c["name"] for c in checks}
    assert {
        "compression (flexural buckling)",
        "flexure, major axis",
        "combined forces (H1-1)",
    } <= names
    m = sp.SteelMaterial.from_material(
        {"id": "A36", "mechanical": {"E": 200000, "nu": 0.3}, "steel": {"fy": 250, "fu": 400}}
    )
    assert m.fy == 250 and m.fu == 400 and round(m.G) == 76923


A992 = sp.SteelMaterial("A992", 345, 450)


def _beam(moment: float, length: float = 6000.0, lb: float | None = None):
    """A simply supported beam's parabolic moment (N·mm) at five stations."""
    forces = [sp.StationForces("1.2D+1.6L", Mx=f * moment) for f in (0.0, 0.75, 1.0, 0.75, 0.0)]
    return [sp.SteelMemberDemand("B1", sp.MemberLengths(length, Lb=lb), forces, kind="beam")]


def test_default_checker_is_the_bnbc_chapter_10_checks_with_ltb():
    checker, real = sp.default_checker()
    assert real and checker is sp.steel_member_checker
    members = _beam(100e6)
    entry = sp.propose_type("B", "beam", "Beam", tbl.find("IPE 200").profile(), members, A992)
    assert not any("stand-in" in n for n in entry["notes"])
    picked = tbl.find(entry["proposed"]["section"])

    def u(s, m=members):
        return sp.utilisation_of(
            sp.steel_member_checker(m[0].forces, s, A992, m[0].lengths, "beam")
        )

    assert u(picked) <= 1.0
    lighter = [s for s in tbl.family("IPE") if s.mass < picked.mass]
    assert lighter and all(u(s) > 1.0 for s in lighter)
    # unbraced over 6 m, lateral-torsional buckling governs: far above the plastic moment
    # section (IPE 240: Zx 367e3 mm³, φMp = 0.9·345·367e3 = 114 kN·m > 100)
    assert picked.mass > tbl.find("IPE 240").mass
    assert u(tbl.find("IPE 240")) > 2.0
    # braced every 1 m: the plastic moment governs again, IPE 240 passes
    braced = _beam(100e6, lb=1000.0)
    assert u(tbl.find("IPE 240"), braced) <= 1.0


def test_lying_rhs_is_checked_and_proposed_on_its_side():
    lying = {"shape": "rectangleHollow", "xDim": 200, "yDim": 100, "wallThickness": 8}
    forces = [sp.StationForces("c", Mx=60e6), sp.StationForces("c", Mx=60e6)]
    members = [sp.SteelMemberDemand("B2", sp.MemberLengths(3000, Lb=500), forces, kind="beam")]
    for checker in (sp.stub_member_checks, None):
        entry = sp.propose_type(
            "R", "beam", "R", lying, members, A572, family="RHS", checker=checker
        )
        profile = entry["proposed"]["profile"]
        assert profile["xDim"] > profile["yDim"]  # still on its side
        s = tbl.section_of_profile(profile)
        upright = tbl.find(entry["proposed"]["section"])
        assert s.turned and s.Zx == pytest.approx(upright.Zy)
        # by hand: φMn about the horizontal (weak) axis <= 0.9 Fy Zy of the upright box
        assert 60e6 <= 0.9 * 345 * upright.Zy * 1.0001
    # RHS 200x120x5 upright would pass (0.9·345·Zx > 60 kN·m) but lying on its side fails
    r = tbl.find("RHS 200x120x5")
    assert 0.9 * 345 * r.Zx > 60e6 > 0.9 * 345 * r.Zy
    stub = sp.stub_member_checks(forces, tbl.oriented(r, lying), A572, members[0].lengths)
    assert sp.utilisation_of(stub) > 1.0


def test_station_forces_become_chapter_10_stations():
    forces = [
        sp.StationForces("a", N=-100e3, Vx=20e3, Vy=5e3, Mx=30e6, My=1e6, s=4.0),
        sp.StationForces("a", N=-100e3, Vx=-20e3, Mx=-10e6, s=0.0),
        sp.StationForces("b", N=50e3),
    ]
    st = sp.to_stations(forces, 4.0)
    assert [x.combination for x in st] == ["a", "b"]
    a = st[0]
    assert list(a.s) == [0.0, 4.0]  # sorted along the member
    assert list(a.P) == [100e3, 100e3]  # compression positive
    assert list(a.Vy) == [-20e3, 20e3]  # along the depth
    assert list(a.Vx) == [0.0, 5e3] and list(a.Mx) == [-10e6, 30e6]
    assert list(st[1].P) == [-50e3]
    assert sp.to_stations(st, 4.0) == st  # Stations pass through

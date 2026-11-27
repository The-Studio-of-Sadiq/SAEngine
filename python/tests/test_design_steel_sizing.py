"""Size Steel Members (issue #286): lightest catalogue sections, iterated with the analysis."""

from __future__ import annotations

import json

import pytest

from saengine.design import steel_proposal as sp
from saengine.design import steel_sizing as sz
from saengine.library import steel_sections as tbl

FY = 250.0
IPE = [s.name for s in tbl.family("IPE")]
HEB = [s.name for s in tbl.family("HEB")]


class _Steel:
    """A 03 Materials steel as the design checks collect it (``id``, ``model_dump``)."""

    id = "S250"

    def model_dump(self):
        return {
            "id": self.id,
            "mechanical": {"E": 200000, "nu": 0.3},
            "steel": {"fy": FY, "fu": 410},
        }


STEEL = _Steel()


def _type(type_id, kind, section):
    return {
        "id": type_id,
        "name": type_id,
        "kind": kind,
        "material": STEEL.id,
        "profile": tbl.find(section).profile(),
    }


def _z_plates(s):
    """Plastic modulus of an I section's plates (the member checks take no fillets) [mm³]."""
    return s.b * s.tf * (s.h - s.tf) + s.tw * (s.h - 2 * s.tf) ** 2 / 4


def _beam_stations(w, length, end_moment=0.0, axial=0.0, n=13):
    """Beam forces [N, N·mm] under a factored UDL ``w`` [N/mm] over ``length`` [mm], hogging
    ``end_moment`` at both ends."""
    out = []
    for i in range(n):
        x = length * i / (n - 1)
        out.append(
            sp.StationForces(
                "1.2D+1.6L",
                N=-axial,
                Vx=w * (length / 2 - x),
                Mx=w * x * (length - x) / 2 - end_moment,
                s=x / 1e3,
            )
        )
    return out


def _member(member_id, type_id, kind, lengths, stations):
    return {
        "id": member_id,
        "type": type_id,
        "kind": kind,
        "material": STEEL,
        "lengths": lengths,
        "stations": stations,
        "checks": [],
    }


# ─────────────────────────── 1: simply supported beam, by hand ───────────────────────────


def test_simply_supported_beam_takes_the_lightest_ipe_by_hand():
    # 6 m span braced every 0.5 m (no lateral-torsional buckling: Mn = Mp), M = 125 kN·m.
    length, moment = 6000.0, 125e6
    w = 8 * moment / length**2

    def analyse(profiles, member_type):
        lengths = sp.MemberLengths(length, Lb=500.0)
        return [_member("B1", "B", "beam", lengths, _beam_stations(w, length))]

    result = sz.size_steel([_type("B", "beam", "IPE 240")], analyse, {"candidates": IPE})
    # By hand: φMp = 0.9 fy Z (Z of the plates); the lightest IPE with φMp >= 125 kN·m:
    # IPE 270 Z = 460.5e3 mm³, φMp = 103.6 kN·m < 125; IPE 300 Z = 602.1e3, φMp = 135.5.
    by_hand = next(s for s in tbl.family("IPE") if 0.9 * FY * _z_plates(s) >= moment)
    assert by_hand.name == "IPE 300"
    assert 0.9 * FY * _z_plates(tbl.find("IPE 270")) < moment
    row = result["groups"][0]
    assert row["proposedSection"] == "IPE 300"
    assert row["currentSection"] == "IPE 240" and row["currentUtilisation"] > 1.0
    assert row["proposedUtilisation"] == pytest.approx(
        moment / (0.9 * FY * _z_plates(by_hand)), abs=0.002
    )
    assert row["status"] == "ok"
    # Statically determinate: the second analysis gives the same forces and confirms it.
    assert result["converged"] and result["iterations"] == 2
    assert result["history"][0]["changed"] == ["B"] and result["history"][1]["changed"] == []


def test_depth_limit_and_deflection_are_honoured():
    length, moment = 6000.0, 125e6
    w = 8 * moment / length**2

    def analyse(profiles, member_type):
        lengths = sp.MemberLengths(length, Lb=500.0)
        member = _member("B1", "B", "beam", lengths, _beam_stations(w, length))
        # 60 mm live-load deflection under the analysed section, l/360 = 16.7 mm.
        analysed = tbl.section_of_profile(profiles["B"])
        member["checks"] = [
            {
                "name": "Deflection: live load ≤ l/360",
                "demand": 60.0 * tbl.find("IPE 240").Ix / analysed.Ix,
                "capacity": length / 360,
                "utilisation": 60.0 * tbl.find("IPE 240").Ix / analysed.Ix / (length / 360),
                "unit": "mm",
                "ok": False,
                "flag": False,
            }
        ]
        return [member]

    result = sz.size_steel([_type("B", "beam", "IPE 240")], analyse, {"candidates": IPE})
    row = result["groups"][0]
    need = 60.0 * tbl.find("IPE 240").Ix / (length / 360)  # the I that deflects l/360
    expected = next(
        s for s in tbl.family("IPE") if s.Ix >= need and 0.9 * FY * _z_plates(s) >= moment
    )
    assert row["proposedSection"] == expected.name and expected.name != "IPE 300"
    assert row["governingCheck"].startswith("Deflection")
    assert result["converged"]

    capped = sz.size_steel(
        [_type("B", "beam", "IPE 240")], analyse, {"candidates": IPE, "maxDepth": 300}
    )
    assert capped["groups"][0]["status"] == "tooSmall"
    assert capped["types"][0]["proposed"] is None


# ───────────────────── 2: portal frame, moments follow the stiffnesses ─────────────────────


def _portal(w, span, height):
    """A fixed-base portal under a UDL on its beam, by moment distribution (symmetric: the beam
    stiffness 2EI/L at each joint, the column's 4EI/h): ``analyse`` for :func:`size_steel`."""
    calls = []

    def analyse(profiles, member_type):
        ib = tbl.section_of_profile(profiles["B"]).Ix
        ic = tbl.section_of_profile(profiles["C"]).Ix
        kb, kc = 2 * ib / span, 4 * ic / height
        m_end = w * span**2 / 12 * kc / (kc + kb)
        calls.append(m_end)
        shear = 1.5 * m_end / height
        beam = _member(
            "B1",
            "B",
            "beam",
            sp.MemberLengths(span, Lb=1000.0),
            _beam_stations(w, span, m_end, axial=shear),
        )
        columns = []
        for cid in ("C1", "C2"):
            stations = [
                sp.StationForces(
                    "1.2D+1.6L",
                    N=-w * span / 2,
                    Vx=shear,
                    Mx=m_end * (1.5 * x - 0.5),
                    s=x * height / 1e3,
                )
                for x in (0.0, 0.25, 0.5, 0.75, 1.0)
            ]
            columns.append(
                _member(cid, "C", "column", sp.MemberLengths(height, Kx=1.0, Ky=1.0), stations)
            )
        return [beam, *columns]

    return analyse, calls


def test_portal_frame_converges_in_two_iterations():
    span, height, w = 8000.0, 4000.0, 30.0  # 30 kN/m factored
    types = [_type("B", "beam", "IPE 600"), _type("C", "column", "HEB 100")]
    analyse, calls = _portal(w, span, height)
    result = sz.size_steel(types, analyse, {"candidates": {"B": IPE, "C": HEB}})
    assert result["converged"]
    assert result["iterations"] == 2
    assert result["history"][0]["changed"] == ["B", "C"]
    rows = {r["group"]: r for r in result["groups"]}
    assert (rows["B"]["proposedSection"], rows["C"]["proposedSection"]) == ("IPE 400", "HEB 120")
    # The beam's end moment moved with the new stiffnesses between the analyses.
    assert calls[0] != pytest.approx(calls[1], rel=0.01)
    for r in rows.values():
        assert r["proposedUtilisation"] <= 1.0
    # Each proposed section is the lightest of its family under the final forces: confirmed
    # by checking the next lighter one under the same analysis.
    final, _ = _portal(w, span, height)
    profiles = {g: tbl.find(r["proposedSection"]).profile() for g, r in rows.items()}
    members = final(profiles, {})
    for gid, family in (("B", "IPE"), ("C", "HEB")):
        picked = tbl.find(rows[gid]["proposedSection"])
        sections = tbl.family(family)
        lighter = sections[sections.index(picked) - 1]
        demands = [
            sp.SteelMemberDemand(m["id"], m["lengths"], m["stations"], m["kind"])
            for m in members
            if m["type"] == gid
        ]
        material = sp.SteelMaterial("S250", FY, 410)
        worst = max(
            sp.utilisation_of(
                sp.steel_member_checker(d.forces, lighter, material, d.lengths, d.kind)
            )
            for d in demands
        )
        assert worst > 1.0, f"{lighter.name} passes {gid}"

    # The proposal applies as the design mode's does (04 Objects, a new profile per type).
    from saengine.design.proposal import apply_proposal

    objects_text = json.dumps({"schema": "saengine.objects/1", "objects": types}, indent=2)
    bim_text = json.dumps({"schema": "saengine.bim/1", "elements": []})
    out = apply_proposal(objects_text, bim_text, {"types": result["types"]})
    applied = {o["id"]: o["profile"] for o in json.loads(out["objectsText"])["objects"]}
    assert applied["B"] == profiles["B"] and applied["C"] == profiles["C"]


def test_not_converged_is_reported():
    span, height, w = 8000.0, 4000.0, 40.0
    types = [_type("B", "beam", "IPE 600"), _type("C", "column", "HEB 100")]
    analyse, _ = _portal(w, span, height)
    result = sz.size_steel(types, analyse, {"candidates": {"B": IPE, "C": HEB}, "maxIterations": 1})
    assert not result["converged"] and result["iterations"] == 1
    assert any("not converged" in w for w in result["warnings"])


def test_each_member_on_its_own_splits_types():
    length = 6000.0

    def analyse(profiles, member_type):
        lengths = sp.MemberLengths(length, Lb=500.0)
        return [
            _member("B1", "B", "beam", lengths, _beam_stations(8 * 125e6 / length**2, length)),
            _member("B2", "B", "beam", lengths, _beam_stations(8 * 125e6 / length**2, length)),
            _member("B3", "B", "beam", lengths, _beam_stations(8 * 40e6 / length**2, length)),
        ]

    result = sz.size_steel(
        [_type("B", "beam", "IPE 240")], analyse, {"candidates": IPE, "sameSection": False}
    )
    assert result["converged"]
    by_member = {r["group"]: r["proposedSection"] for r in result["groups"]}
    assert by_member["B1"] == by_member["B2"] == "IPE 300"
    assert by_member["B3"] != "IPE 300"
    assert result["types"][0]["proposed"]["section"] == "IPE 300"
    assert [n["members"] for n in result["newTypes"]] == [["B3"]]
    assert result["reassign"] == [
        {"member": "B3", "from": "B", "to": result["newTypes"][0]["type"]}
    ]


def test_options_from_the_panel():
    opts = sz.SizingOptions.from_dict(
        {"maxIterations": "3", "candidates": "IPE 200, IPE 220", "minDepth": 0, "maxDepth": "400"}
    )
    assert opts.max_iterations == 3 and opts.min_depth is None and opts.max_depth == 400
    assert opts.limits_for("X") == {
        "minDepth": None,
        "maxDepth": 400,
        "candidates": ["IPE 200", "IPE 220"],
    }


def test_catalogue_has_the_new_families():
    fams = set(tbl.FAMILIES)
    assert {"HEM", "UPE", "UPN", "LU"} <= fams
    # Nominal masses of EN 10365 / EN 10056-1 (kg/m), from the computed areas.
    for name, mass in (("HEM 300", 238.0), ("UPE 200", 22.8), ("L 100x65x8", 9.94)):
        assert tbl.find(name).mass == pytest.approx(mass, rel=0.005)
    assert tbl.find("L 100x65x8").family == "LU"
    assert "LU" in tbl.families_for(tbl.find("L 50x50x5").profile())

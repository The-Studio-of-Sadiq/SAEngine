"""C3b: the remainder of the US code pack ``aci318-asce7-22``.

Pins the values the pack adds with their clauses (VERIFY.md in the pack lists them for checking
against the printed standards): NDS 2018 timber by reference design values and adjustment
factors (ASD and LRFD, bolts by the yield limit equations), TMS 402-22 Chapter 8 allowable
stress design of masonry, AISC 360-22 built-up members (E6), stability bracing (Appendix 6),
ponding (Appendix 2), tension field stiffeners (G2.3), HSS connections (Chapter K) and fatigue
(Appendix 3), AISC 341-22 moment frames (Cpr, beam bracing by Ry Fy); that the default pack's
results stay as they were; and a generated steel building designed under the pack, LRFD and
ASD.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

PACK_ID = "aci318-asce7-22"
PSI = 0.00689476


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


def _stations(name, s, p, mx, vy):
    from saengine.design.steel.members import Stations

    z = np.zeros_like(s)
    return Stations(name, s, p, mx, z, vy, z, [""] * len(s))


class _Material:
    id = "DF2"

    def __init__(self, **timber):
        from saengine.library.materials import TimberProperties

        self.timber = TimberProperties(**timber)


# ───────────────────────────── the pack ─────────────────────────────


def test_pack_covers_the_remainder(us):
    info = registry.info(PACK_ID)
    assert info.usable and not info.problems
    assert {"timber", "fatigue", "masonry", "steel", "steelSeismic"} <= set(info.covers)
    assert code_context.table("timber").method == "referenceDesign"
    from saengine.design.timber.members import clause

    assert clause("bending") == "NDS 2018 Sec 3.3"  # tableCodes: named after the NDS


# ───────────────────────────── NDS 2018 timber ─────────────────────────────


def test_nds_reference_values_and_factors(us):
    from saengine.design.timber import reference as R
    from saengine.design.timber.members import Section

    ref = R.Reference.of(_Material(species="douglasFirLarch", referenceGrade="No.2"),
                         Section(38, 235), 4000)  # fmt: skip
    # NDS Supplement Table 4A, Douglas Fir-Larch No.2: Fb 900, Ft 575, Fv 180, Fc⊥ 625, Fc 1350,
    # E 1.6e6, Emin 580 000 psi; CF of a 2x10: Fb 1.1, Ft 1.1, Fc 1.0
    assert ref.size == "dimension"
    assert ref.values["Fb"] == pytest.approx(900 * PSI) and ref.values["Fc"] == pytest.approx(
        1350 * PSI
    )
    assert ref.values["Emin"] == pytest.approx(580_000 * PSI)
    assert ref.named["CF"] == {"Fb": 1.1, "Ft": 1.1, "Fc": 1.0}
    # wet service (Sec 4.3.3): Fb 0.85 unless Fb CF <= 1150 psi (990: exempt), Fc⊥ 0.67, Fc 0.8
    wet = R.Reference.of(_Material(species="douglasFirLarch", referenceGrade="No.2",
                                   location="wet"), Section(38, 235), 4000)  # fmt: skip
    assert wet.named["CM"]["Fb"] == 1.0 and wet.named["CM"]["Fcp"] == 0.67
    assert wet.named["CM"]["Fc"] == 0.8
    # Table 2.3.2 CD, Appendix N λ
    assert R.duration_factor({"D": 1.0}) == 0.9
    assert R.duration_factor({"D": 1.0, "L": 1.0}) == 1.0
    assert R.duration_factor({"D": 1.0, "S": 1.0}) == 1.15
    assert R.duration_factor({"D": 1.0, "Lr": 1.0}) == 1.25
    assert R.duration_factor({"D": 0.6, "WX": 0.6}) == 1.6
    assert R.time_effect({"D": 1.4}) == 0.6
    assert R.time_effect({"D": 1.2, "L": 1.6, "Lr": 0.5}) == 0.8
    assert R.time_effect({"D": 1.2, "Lr": 1.6, "L": 1.0}) == 0.8
    assert R.time_effect({"D": 1.2, "EX": 1.0, "L": 0.5}) == 1.0
    lrfd = code_context.table("timber").reference.lrfd
    assert (lrfd.KF["Fb"], lrfd.phi["Fb"], lrfd.KF["Fc"], lrfd.phi["Fc"]) == (2.54, 0.85, 2.4, 0.9)
    assert ref.adjusted("Fb", 0.8, lrfd=True) == pytest.approx(900 * PSI * 1.1 * 0.8 * 2.54 * 0.85)
    # glulam CV (Sec 5.3.6, x = 10)
    glulam = R.Reference.of(_Material(species="glulam", referenceGrade="24F-1.8E"),
                            Section(130, 457), 9000)  # fmt: skip
    expected = (6400 / 9000 * 305 / 457 * 130 / 130) ** 0.1
    assert glulam.cv == pytest.approx(expected) and glulam.values["Fb"] == pytest.approx(2400 * PSI)


def test_nds_beam_column_and_bolts(us):
    from saengine.design.timber import reference as R
    from saengine.design.timber.members import Section
    from saengine.library.objects import TimberBoltedJoint

    mat = _Material(species="Douglas Fir-Larch", referenceGrade="No.2")

    class Beam:
        restraintSpacing = 600.0
        freeEnd = "none"
        bearingLength = 50.0
        repetitive = True

    section = Section(38, 235)
    ref = R.Reference.of(mat, section, 4000, Beam)
    s = np.linspace(0, 4, 9)
    x = s * 1000
    w = 5.0  # N/mm
    st = _stations("D + L", s, np.zeros_like(s), -w * x * (4000 - x) / 2, w * (2000 - x))
    rows = {r["name"].split(" (")[0]: r for r in R.check_member(section, ref, [st], 4000,
                                                                 {"D + L": 1.0}, "beam", Beam)}  # fmt: skip
    bending = rows["Bending fb = M/S about the strong axis"]
    # CL (Sec 3.3.3): le = 2.06 lu (lu/d < 7), RB = √(le d / b²), FbE = 1.20 Emin'/RB²
    le = 2.06 * 600
    rb = math.sqrt(le * 235 / 38**2)
    fb_star = 900 * PSI * 1.1 * 1.15  # CF, Cr
    alpha = 1.2 * 580_000 * PSI / rb**2 / fb_star
    cl = (1 + alpha) / 1.9 - math.sqrt(((1 + alpha) / 1.9) ** 2 - alpha / 0.95)
    assert bending["capacity"] == pytest.approx(fb_star * cl, abs=0.01)
    assert bending["demand"] == pytest.approx(5.0 * 4000**2 / 8 / (38 * 235**2 / 6), abs=0.01)
    shear = rows["Shear fv = 3V/(2bd), loads within d of the supports left out"]
    assert shear["demand"] == pytest.approx(1.5 * 5.0 * (2000 - 235) / (38 * 235), abs=0.01)
    bearing = rows["Bearing perpendicular to the grain at the start support"]
    assert bearing["capacity"] == pytest.approx(625 * PSI * (50 + 9.525) / 50, abs=0.01)
    # a 140 x 140 post (posts and timbers, Table 4D: Fc 700 psi, Emin 470 000 psi): CP, c = 0.8
    post = Section(140, 140)
    col = R.Reference.of(mat, post, 3000)
    assert col.size == "postsTimbers"
    cp = R.column_stability(700 * PSI, 470_000 * PSI, 3000 / 140, "sawn")
    fce = 0.822 * 470_000 * PSI / (3000 / 140) ** 2
    a = fce / (700 * PSI)
    assert cp == pytest.approx((1 + a) / 1.6 - math.sqrt(((1 + a) / 1.6) ** 2 - a / 0.8))
    # four 16 mm bolts in double shear, 40 mm side members, parallel to the grain: mode IIIs
    joint = TimberBoltedJoint(diameter=16, count=4, rows=2, spacing=64, endDistance=112,
                              sideThickness=40)  # fmt: skip
    tension = _stations("D + L", s, np.full_like(s, -20e3), np.zeros_like(s), np.zeros_like(s))
    found, summary = R.check_joint(joint, post, col, [tension], {"D + L": 1.0}, False)
    d, ls = 16 / 25.4, 40 / 25.4
    fe = 11200 * 0.50
    k3 = -1 + math.sqrt(2 * 2 + 2 * 45000 * 3 * d**2 / (3 * fe * ls**2))
    z = 2 * k3 * d * ls * fe / (3 * 3.2) * 4.4482216  # N, Eq 12.3-9 with Rd = 3.2
    assert summary["mode"] == "IIIs"
    cap = found[0]["capacity"]
    assert cap == pytest.approx(4 * z * summary["Cg"] / 1e3, rel=1e-3)


def test_timber_member_designed_by_the_pack(us):
    from saengine.design.timber.members import design_timber_member
    from saengine.library.objects import ObjectLibrary

    lib = ObjectLibrary.model_validate({"objects": [{
        "id": "J", "name": "Joist", "kind": "beam", "material": "DF2",
        "profile": {"shape": "rectangle", "xDim": 38, "yDim": 235},
        "timber": {"restraintSpacing": 600},
    }]})  # fmt: skip
    from saengine.design.timber import reference as R
    from saengine.design.timber.members import Section

    # the entry of one combination by the reference method (no analysis needed)
    s = np.linspace(0, 4, 9)
    x = s * 1000
    st = _stations("1.0D + 1.0L", s, np.zeros_like(s), -1.0 * x * (4000 - x) / 2, 1.0 * (2000 - x))
    entry = R.design_entry("J1", "beam", lib.objects[0], _Material(species="hemFir",
                           referenceGrade="No.1"), Section(38, 235), [st], 4000.0,
                           [{"D": 1.0, "L": 1.0}], ["1.0D + 1.0L"], None, None, [])  # fmt: skip
    assert entry["timber"]["method"] == "referenceDesign" and entry["timber"]["format"] == "ASD"
    assert entry["timber"]["species"] == "Hem-Fir No.1 (dimension)"
    assert entry["ok"] and entry["utilisation"] > 0.1
    assert design_timber_member  # the dispatcher of the pack's method


# ───────────────────────────── TMS 402-22 allowable stress design ─────────────────────────────


def test_tms402_allowable_stresses(us):
    from saengine.design import masonry as M
    from saengine.design import masonry_asd as A

    # Sec 8.2.4.1: Fa = 0.25 f'm [1 - (h/140r)²], r = t/√12; (70r/h)² above h/r 99
    assert A.allowable_axial(10, 3000, 200) == pytest.approx(
        2.5 * (1 - (3000 * math.sqrt(12) / (140 * 200)) ** 2), rel=1e-3
    )
    assert A.allowable_axial(10, 7000, 200) == pytest.approx(
        2.5 * (70 * 200 / (math.sqrt(12) * 7000)) ** 2, rel=1e-3
    )
    # Sec 8.2.4.2, 8.3.4.2.2: Fb 1/3 f'm unreinforced, 0.45 f'm reinforced
    assert A.allowable_flexural_compression(10) == pytest.approx(3.33)
    assert A.allowable_flexural_compression(10, reinforced=True) == pytest.approx(4.5)
    # Sec 8.3.3.1: Fs 32 ksi Grade 60, 20 ksi Grade 40
    assert A.allowable_steel(420) == 220 and A.allowable_steel(280) == 138
    # Sec 8.3.5.1: Fvm = 1/2 (4.0 - 1.75 M/(V dv)) √f'm + 0.25 P/An, Fvs = 0.5 ρ Fs
    fv, fvm, fvs = A.additive_wall_shear(10, 0.5, 0.5, 0.002, 220)
    assert fvm == pytest.approx(0.0415 * (4 - 0.875) * math.sqrt(10) + 0.125)
    assert fvs == pytest.approx(0.22)
    assert fv == pytest.approx((0.249 - (0.249 - 0.166) / 3) * math.sqrt(10))  # the maximum
    # Sec 8.2.6.2: unreinforced Fv = min(1.5 √f'm, 120 psi, 37 psi + 0.45 Nv/An)
    m = M.Masonry(fm=10.0, kind="concrete", grouting="none", mortar="M2")
    assert A.allowable_wall_shear_plain(m, 0.2) == pytest.approx(0.255 + 0.45 * 0.2)
    # Sec 4.2.2: Em 900 f'm concrete masonry, 700 f'm clay; no one-third increase
    assert m.em == 9000 and M.Masonry(fm=10.0).em == 7000
    assert code_context.table("masonry").lateralIncrease.factor == 1.0
    assert "TMS 402-22 Sec 8.3.5.1" in M.clause("wallShearReinforced")


# ───────────────────────────── AISC 360-22 and 341-22 ─────────────────────────────


def test_aisc360_remainder(us):
    from saengine.design.steel import fatigue, ponding
    from saengine.design.steel.built_up import BuiltUp, modified_slenderness
    from saengine.design.steel.members import torsional_bracing

    s = code_context.table("steel")
    # Appendix 6: columns relative 0.005 Pr, beams relative 0.005 Mr Cd / ho, torsional 0.02 Mr
    b = s.bracing
    assert (b.columnRelative.strength, b.beamRelative.strength, b.torsionalMoment) == (
        0.005,
        0.005,
        0.02,
    )
    braced = torsional_bracing(100e6, 8000, 1, 1.0, 1e7, 400, 8)
    assert braced["Mbr"] == pytest.approx(0.02 * 100e6)
    assert braced["betaT"] == pytest.approx(3.6 * 8000 * 100e6**2 / (0.75 * 200_000 * 1e7))
    # Sec E6.1(b): welded connectors, (Lc/r)o up to a/ri = 40, else √((Lc/r)o² + (Ki a/ri)²)
    close = BuiltUp(connectors="welded", spacing=600, ri=20.0)
    assert modified_slenderness(close, 80.0)[0] == 80.0
    far = BuiltUp(connectors="welded", spacing=1200, ri=20.0)
    assert modified_slenderness(far, 80.0)[0] == pytest.approx(math.hypot(80, 0.86 * 60))
    # Appendix 2: the simplified ponding check cites AISC 360-22
    assert "Appendix 2" in ponding.simplified(10, 8, 2, 4e8, 1e8)["checks"][0]["note"]
    # Chapter K: punching of round gapped K joints φ 0.95; the notes cite the K tables
    assert s.phi["hssPunchingRoundK"] == 0.95
    assert s.connections.references["Eq 6.10.211"] == "Sec K3, Table K3.1"
    # Appendix 3: FSR = (Cf 329 / nSR)^0.333 >= FTH (category C at 2 million cycles; A held at
    # its threshold 165 MPa)
    assert fatigue.design_stress_range("C", 2e6) == pytest.approx((4.4e9 * 329 / 2e6) ** 0.333)
    assert fatigue.design_stress_range("A", 2e6) == 165
    assert "AISC 360-22 Table A-3.1" in code_context.table("fatigue").categories["A"].source


def test_aisc341_remainder(us):
    from saengine.design.steel import seismic as S

    t = code_context.table("steelSeismic")
    smf, imf = t.frames["smf"], t.frames["imf"]
    # Sec E3.6d, AISC 358 Sec 2.4.3: Cpr = (Fy + Fu) / (2 Fy) <= 1.2
    assert S.hinge_factor(smf, 345.0, 450.0) == pytest.approx(795 / 690)
    assert S.hinge_factor(smf, 250.0, 400.0) == 1.2
    # Sec D1.2: beams braced at 0.095 / 0.19 ry E / (Ry Fy)
    assert (smf.beamBracing, imf.beamBracing) == (0.095, 0.19) and smf.beamBracingExpected
    assert t.plateWalls.inertiaCoefficient == 0.0031
    assert S.cite(t, "linkShear").startswith("AISC 341-22 Sec F3.5b.2")
    assert not [k for k, v in t.sources.items() if "default pack's rule" in v]


def test_default_pack_unchanged(bnbc):
    from saengine.design import masonry_asd as A
    from saengine.design.steel import ponding
    from saengine.design.steel import seismic as S
    from saengine.design.steel.built_up import BuiltUp, modified_slenderness
    from saengine.design.timber import reference as R
    from saengine.design.timber.members import clause, method

    assert not R.active() and R.combination_set() == "allowable"
    assert clause("bending").startswith("BNBC 2020 Part 6")
    assert method()[0].startswith("Timber members: permissible stress design")
    assert ponding.simplified(10, 8, 2, 4e8, 1e8)["checks"][0]["note"].startswith(
        "Sec 10.16.1 Eq 6.10.272"
    )
    welded = BuiltUp(connectors="welded", spacing=1200, ri=20.0, rib=20.0, separation=100.0)
    alpha = 100 / 40
    expected = math.sqrt(80**2 + 0.82 * alpha**2 / (1 + alpha**2) * 60**2)
    assert modified_slenderness(welded, 80.0)[0] == pytest.approx(expected)
    assert S.hinge_factor(code_context.table("steelSeismic").frames["smf"], 345, 450) == 1.1
    assert A.allowable_steel(420) == 165
    assert A.allowable_flexural_compression(10, True) == pytest.approx(3.3)


# ───────────────────────────── a generated steel building ─────────────────────────────


def _wizard(system: str, stories: int = 2) -> dict:
    return {
        "schema": "saengine.newBuilding/1",
        "name": f"US {system}",
        "spacings": {"x": [6000], "y": [5000]},
        "stories": [{"id": "BASE", "name": "Base", "elevation": 0}]
        + [
            {"id": f"L{k}", "name": f"Level {k}", "elevation": 3500 * k}
            for k in range(1, stories + 1)
        ],
        "storyHeights": [3500] * stories,
        "system": system,
        "footing": "isolated",
        "site": {
            "siteClass": "SD",
            "siteClassSource": "assumed",
            "spectral": {"sds": 1.0, "sd1": 0.6, "s1": 0.65, "tl": 8},
            "windSpeed": 50,
        },
        "occupancy": {"use": "office", "category": "II"},
        "designCode": PACK_ID,
    }


def test_generator_steel_systems():
    from saengine.library.generator import generate_building
    from saengine.project.new_building import spec_from_wizard

    spec, _ = spec_from_wizard(_wizard("steelMomentFrame", 4))
    moment = generate_building(spec)
    assert moment["summary"]["system"] == "steelSmf"  # SDC D: the first permitted (C.1)
    assert {o["material"] for o in moment["objects"]["objects"] if o["kind"] != "slab"} == {"A992"}
    spec, _ = spec_from_wizard(_wizard("steelBracedFrame", 4))
    braced = generate_building(spec)
    assert braced["summary"]["system"] == "steelScbf" and len(braced["bimMembers"]) == 4 * 4 * 2
    # SDC B: steel not specifically detailed (R = 3, row H), the AISC 341-22 provisions off
    low = {**spec, "spectral": {"sds": 0.2, "sd1": 0.08, "s1": 0.05, "tl": 8}}
    assert generate_building(low)["summary"]["system"] == "steelNotDetailed"


def test_generated_steel_building_designed_under_the_pack(tmp_path):
    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

    wizard = _wizard("steelBracedFrame")
    # SDC B (steel not specifically detailed: every member may be checked by ASD)
    wizard["site"]["spectral"] = {"sds": 0.2, "sd1": 0.08, "s1": 0.05, "tl": 8}
    root = Path(create_building(wizard, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis", "design"])
    assert result.steps[-1].status in ("ok", "warning"), [s.message for s in result.steps]
    report_path = root / "08 FEM/model.results/design-report.json"

    def steel_entries() -> list[dict]:
        report = json.loads(report_path.read_text(encoding="utf-8"))["result"]
        return [e for e in report["elements"] if isinstance(e.get("section"), dict)]

    lrfd = steel_entries()
    assert lrfd and {e["kind"] for e in lrfd} >= {"beam", "column", "brace"}
    assert {e.get("basis", "LRFD") for e in lrfd} == {"LRFD"}
    clauses = " ".join(str(c.get("clause") or "") for e in lrfd for c in e["checks"])
    assert "AISC 360-22" in clauses
    # ASD (a project override): Rn / Ω under the ASD combinations of ASCE 7-22 Sec 2.4
    settings_path = root / "02 Project Settings/project-settings.json"
    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    raw["codeOverrides"] = {"steel.designMethod": "ASD"}
    settings_path.write_text(json.dumps(raw, indent="\t"), encoding="utf-8")
    result = run_all(root, steps=["design"])
    assert result.steps[-1].status in ("ok", "warning"), [s.message for s in result.steps]
    asd = steel_entries()
    assert {e.get("basis") for e in asd if e["kind"] in ("beam", "column", "brace")} == {"ASD"}

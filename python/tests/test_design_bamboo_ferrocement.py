"""Bamboo (BNBC 2020 Part 6 Chapter 4) and ferrocement (Chapter 12) members with the bnbc2020
code pack: the values are pinned with their clauses (B39)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes.tables import builtin_table
from saengine.design import bamboo as B
from saengine.design import ferrocement as F
from saengine.design.steel.members import Stations
from saengine.library.materials import Material
from saengine.library.objects import (
    BambooJoint,
    BambooMember,
    Beam,
    CircleHollowProfile,
    FerrocementMember,
    RectangleProfile,
)


def _stations(name: str, p: float = 0.0, m: float = 0.0, v: float = 0.0, n: int = 3):
    z = np.zeros(n)
    return Stations(
        name,
        np.linspace(0, 2, n),
        z + p,
        z + m,
        z.copy(),
        z + v,
        z.copy(),
        ["x"] * n,
    )


def _bamboo(**props) -> Material:
    return Material.model_validate(
        {
            "id": "BAM",
            "name": "bamboo",
            "category": "bamboo",
            "mechanical": {"E": 10300, "density": props.pop("density", 610)},
            "bamboo": props,
        }
    )


# ───────────────────────── bamboo: Tables 6.4.6-6.4.8, Sec 4.5 ─────────────────────────


def test_bamboo_table_values():
    t = builtin_table("bamboo", "bnbc2020")
    # Table 6.4.6 (part 1 pp. 824-825), green condition.
    tulda = t.species["bambusaTulda"]
    assert (tulda.group, tulda.bending, tulda.E, tulda.compression) == ("B", 13.3, 1770.0, 11.6)
    strictus = t.species["dendrocalamusStrictus"]
    assert (strictus.group, strictus.bending, strictus.E, strictus.compression) == (
        "A",
        18.4,
        2660.0,
        10.3,
    )
    nigro = t.species["oxytenantheraNigrociliata"]
    assert (nigro.bending, nigro.E, nigro.compression) == (10.18, 2600.0, 7.2)
    assert len(t.species) == 18
    # Table 6.4.7.
    assert (t.groupLimits["A"].rupture, t.groupLimits["A"].E) == (70.0, 9000.0)
    assert (t.groupLimits["C"].rupture, t.groupLimits["C"].E) == (30.0, 3000.0)
    # Table 6.4.8.
    assert (t.densityFactors["green"].bending, t.densityFactors["green"].shear) == (0.015, None)
    assert t.densityFactors["airDry"].compression == 0.013
    assert t.densityFactors["airDry"].shear == 0.003
    # Sec 4.5.1, 4.5.5, 4.6.7.2-4.6.7.3, 4.6.8.5, 4.4.5.2.
    sf = t.safetyFactors
    assert (sf.bending, sf.E, sf.compression) == (4.0, 4.5, 3.5)
    assert (t.duration.continuous, t.duration.medium, t.duration.short) == (1.0, 1.25, 1.5)
    assert (t.column.maxSlenderness, t.column.inertiaFactor) == (50.0, 0.9)
    assert t.column.initialCurvature == pytest.approx(75 / 6000)
    assert t.trussForceIncrease == 1.1
    assert t.minWallThickness == 8.0
    assert t.joints.fastenings["lashing"].wireDiameter == 1.6
    assert t.joints.fastenings["pinAndWire"].pinDiameter == 12.0


def test_bamboo_stresses_by_species_tests_and_density():
    s = B.Bamboo.of_material(_bamboo(species="Bambusa tulda"))
    assert (s.fb, s.fc, s.e, s.fv, s.group) == (13.3, 11.6, 1770.0, None, "B")
    assert B.Bamboo.of_material(_bamboo(species="B. tulda")).fb == 13.3
    assert B.Bamboo.of_material(_bamboo(species="Bambusa bambos")).fb == 14.6  # synonym
    # Sec 4.5.1: tested values over the factors of safety; Table 6.4.7 group.
    t = B.Bamboo.of_material(_bamboo(tested={"rupture": 80, "E": 12000, "compression": 42}))
    assert (t.fb, t.fc) == (pytest.approx(20.0), pytest.approx(12.0))
    assert t.e == pytest.approx(12000 / 4.5)
    assert t.group == "A"
    # Table 6.4.8 note: green, 600 kg/m³ -> bending 9 MPa.
    d = B.Bamboo.of_material(_bamboo(density=600))
    assert d.fb == pytest.approx(9.0)
    assert d.fc == pytest.approx(6.6)
    dry = B.Bamboo.of_material(_bamboo(density=700, condition="airDry"))
    assert (dry.fb, dry.fc, dry.fv) == (
        pytest.approx(14.0),
        pytest.approx(9.1),
        pytest.approx(2.1),
    )
    with pytest.raises(B.BambooDesignError):
        B.Bamboo.of_material(_bamboo(species="Bambusa imaginaria"))


def test_bamboo_duration_factor_sec_4_5_5():
    assert B.duration_factor({"D": 1.0}) == 1.0
    assert B.duration_factor({"D": 1.0, "L": 1.0}) == 1.25
    assert B.duration_factor({"D": 1.0, "L": 0.75, "WX": 0.75}) == 1.5


def test_culm_section_sec_4_3():
    c = B.Culm.of(CircleHollowProfile(radius=40, wallThickness=8))
    assert c.area == pytest.approx(math.pi / 4 * (80**2 - 64**2))
    # Sec 4.3 prints π/64 (D² - d²): the hollow circle's D⁴ - d⁴ is used.
    assert c.inertia == pytest.approx(math.pi / 64 * (80**4 - 64**4))
    assert c.radius == pytest.approx(math.sqrt(80**2 + 64**2) / 4)


def test_bamboo_column_checks_sec_4_6_7():
    culm = B.Culm.of(CircleHollowProfile(radius=40, wallThickness=8))
    s = B.Bamboo.of_material(_bamboo(species="Bambusa tulda"))
    length = 2000.0
    rows = B.check_member(culm, s, [_stations("D", p=2e3)], length, {"D": 1.0}, "column")
    by = {r["name"].split(" (")[0]: r for r in rows}
    fc = 2e3 / culm.area
    assert by["Compression along the fibres"]["demand"] == pytest.approx(fc, abs=0.01)
    assert by["Compression along the fibres"]["capacity"] == 11.6
    pcr = math.pi**2 * 1770 * 0.9 * culm.inertia / length**2
    assert by["Euler buckling, 0.9 I"]["capacity"] == pytest.approx(pcr / 1e3, abs=0.01)
    e0 = 0.0125 * length
    fb = 2e3 * e0 / (1 - 2e3 / pcr) / culm.modulus
    assert by["Compression and bending with the initial curvature"]["demand"] == pytest.approx(
        fc / 11.6 + fb / 13.3, abs=0.01
    )
    slender = by["Slenderness l/r"]
    assert slender["capacity"] == 50.0
    assert slender["demand"] == pytest.approx(length / culm.radius, abs=0.01)
    # Truss members: the compression increased by 10% (Sec 4.6.8.5).
    truss = B.check_member(
        culm, s, [_stations("D", p=2e3)], length, {}, "brace", BambooMember(truss=True)
    )
    t = next(r for r in truss if r["name"].startswith("Compression along"))
    assert t["demand"] == pytest.approx(1.1 * fc, abs=0.01)


def test_bamboo_beam_bending_with_duration_and_wall_advisory():
    culm = B.Culm.of(CircleHollowProfile(radius=30, wallThickness=6))
    s = B.Bamboo.of_material(_bamboo(species="Bambusa tulda"))
    rows = B.check_member(culm, s, [_stations("D + L", m=0.5e6)], 2000, {"D + L": 1.25})
    fb = next(r for r in rows if r["name"].startswith("Bending"))
    assert fb["capacity"] == pytest.approx(1.25 * 13.3, abs=0.01)
    assert fb["demand"] == pytest.approx(0.5e6 / culm.modulus, abs=0.01)
    wall = next(r for r in rows if r["name"].startswith("Wall thickness"))
    assert wall["flag"] and wall["capacity"] == 8.0
    assert not any(r["name"].startswith("Slenderness") for r in rows)


def test_bamboo_joint_tested_capacity_sec_4_7_1_4():
    st = [_stations("D", p=-5e3)]
    rows, out = B.joint_rows(BambooJoint(kind="lap", fastening="lashing"), st, False)
    assert rows == [] and "full-scale tests" in out["note"]
    assert out["wireDiameter"] == 1.6
    rows, out = B.joint_rows(BambooJoint(testedCapacity=6.0), st, True)
    assert rows[0]["demand"] == pytest.approx(5.5)
    assert rows[0]["capacity"] == 6.0


def test_bamboo_template_material():
    from saengine.library.templates import TEMPLATES

    material = Material.model_validate(TEMPLATES["Material:bamboo"])
    assert B.is_bamboo(material)
    assert B.Bamboo.of_material(material).group == "B"


# ─────────────────── ferrocement: Tables 6.12.2-6.12.3, Sec 12.4, Appendix U ───────────────────


def _ferro(fc: float = 35.0) -> Material:
    return Material.model_validate(
        {
            "id": "FC",
            "name": "mortar",
            "category": "ferrocement",
            "mechanical": {"E": 27800},
            "ferrocement": {"fc": fc},
        }
    )


def _section(**member) -> F.FerroSection:
    data = {"mesh": "wovenSquare", "layers": 4, "wireDiameter": 1.0, "spacing": 13, **member}
    return F.FerroSection.of(
        RectangleProfile(xDim=1000, yDim=25), _ferro(), FerrocementMember(**data)
    )


def test_ferrocement_table_values():
    t = builtin_table("ferrocement", "bnbc2020")
    # Table 6.12.2 (part 2 p. 348).
    woven = t.meshes["wovenSquare"]
    assert (woven.fy, woven.Erl, woven.Ert) == (450.0, 138000.0, 165000.0)
    assert (t.meshes["hexagonal"].fy, t.meshes["hexagonal"].Ert) == (310.0, 69000.0)
    assert (t.bars.fy, t.bars.Erl) == (410.0, 200000.0)
    # Table 6.12.3 (p. 350).
    assert (woven.eta.longitudinal, woven.eta.transverse, woven.eta.diagonal) == (0.5, 0.5, 0.35)
    ex = t.meshes["expanded"].eta
    assert (ex.longitudinal, ex.transverse, ex.diagonal) == (0.65, 0.2, 0.3)
    assert (t.bars.eta.longitudinal, t.bars.eta.transverse, t.bars.eta.diagonal) == (1.0, 0, 0.7)
    # Sec 12.4.2, 12.4.3.2, 12.4.4.1-12.4.4.2, 12.4.5.
    assert (t.strength.fyMax, t.strength.strainLimit, t.strength.efficiencyThickness) == (
        690.0,
        0.003,
        50.0,
    )
    assert (t.service.steelShare, t.service.liquidRetaining) == (0.6, 200.0)
    assert t.crackWidth == {"noncorrosive": 0.1, "corrosive": 0.05, "waterRetaining": 0.05}
    assert t.fatigue == {"oneMillion": 350.0, "twoMillion": 200.0}
    d = t.detailing
    assert (d.waterVolumeFraction, d.waterSpecificSurface, d.skeletalShare) == (0.035, 0.16, 0.5)
    assert (d.minLayers, d.thinSection, d.thinCover, d.coverWireFactor) == (2, 25.0, 2.0, 2.0)


def test_volume_fraction_appendix_u_and_specific_surface():
    s = _section()
    vf_layer = math.pi * 1.0**2 / (4 * 25) * (2 / 13)
    assert s.vf == pytest.approx(4 * vf_layer)
    assert s.sr == pytest.approx(4 * s.vf / 1.0)  # Sec 12.2.1, square mesh
    # Eq 6.12.2: Ari = η Vfi Ac.
    assert s.layers[0].area == pytest.approx(0.5 * vf_layer * 1000 * 25)
    # Expanded metal: Vf = N Wm / (γm h), γm = 77.0 kN/m³ (Table 6.2.1).
    m = FerrocementMember(mesh="expanded", layers=2, wireDiameter=1.0, meshWeight=18)
    assert F.volume_fraction(m, 25) == pytest.approx(18 / (77.0 * 25))


def test_tension_eq_6_12_3_and_strength_curve():
    s = _section()
    nn = sum(layer.area for layer in s.layers) * 450.0
    curve = F.interaction(s)
    assert curve[0][0] == pytest.approx(-0.9 * nn)
    assert F.capacity_ratio(curve, -0.9 * nn, 0.0) == pytest.approx(1.0, abs=1e-6)
    # Sec 12.4.2.3: the mortar alone, 0.85 f'c Ac, times φ = 0.65.
    pmax = 0.65 * 0.85 * 35 * 1000 * 25
    assert curve[-1] == (pytest.approx(pmax), 0.0)
    assert F.capacity_ratio(curve, pmax / 2, 0.0) == pytest.approx(0.5, abs=1e-6)


def test_design_aid_eq_6_12_5():
    s = _section()
    x = s.vf * 450 / 35
    expected = (0.005 + 0.422 * x - 0.0772 * x**2) * 35 * 1000 * 25**2 * 0.5
    assert F.design_aid_moment(s.vf, 450, 35, 1000, 25, 0.5) == pytest.approx(expected)
    # Figure 6.12.3: Y = 0.40 at X = 1.2 (the squared last term).
    assert 0.005 + 0.422 * 1.2 - 0.0772 * 1.2**2 == pytest.approx(0.4, abs=0.001)
    # The strain compatibility moment in pure bending is of the same order as the design aid's.
    mn = 1.0 / F.capacity_ratio(F.interaction(s), 0.0, 1.0) / 0.9
    assert 0.6 < mn / expected < 1.6


def test_service_stresses_sec_12_4_3():
    s = _section()
    rows = F.check_service(s, [_stations("D + L", m=-0.3e6)], "noncorrosive")
    fs = next(r for r in rows if r["name"].startswith("Mesh tension"))
    assert fs["capacity"] == pytest.approx(0.6 * 450)
    x, icr = F.cracked(s)
    n = 138000 / 27800
    deepest = max(layer.y for layer in s.layers)
    assert fs["demand"] == pytest.approx(n * 0.3e6 * (deepest - x) / icr, abs=0.01)
    fc = next(r for r in rows if r["name"].startswith("Mortar compression"))
    assert fc["capacity"] == pytest.approx(0.45 * 35)
    water = F.check_service(s, [_stations("D", m=0.1e6)], "waterRetaining", "twoMillion")
    assert next(r for r in water if r["name"].startswith("Mesh tension"))["capacity"] == 200.0
    assert next(r for r in water if "fatigue" in r["name"])["capacity"] == 200.0


def test_detailing_sec_12_4_5():
    s = _section(exposure="waterRetaining", bars={"diameter": 6, "spacing": 100})
    rows = {r["name"].split(" (")[0]: r for r in F.check_detailing(s, _member(s))}
    assert rows["Cover to the first mesh layer"]["demand"] == 2.0  # 2 × 1 mm wire
    assert rows["Volume fraction, water retaining"]["ok"] is False  # 1.9% < 3.5%
    assert rows["Specific surface, water retaining"]["demand"] == 0.16
    assert rows["Skeletal steel in the thickness"]["capacity"] == pytest.approx(12.5)
    assert rows["Mesh opening"]["ok"]
    thin = F.FerroSection.of(
        RectangleProfile(xDim=1000, yDim=20),
        _ferro(),
        FerrocementMember(layers=2, wireDiameter=1.0, spacing=13),
    )
    assert thin.cover == 2.0  # thinner than 25 mm: about 2 mm


def _member(section: F.FerroSection) -> FerrocementMember:
    return FerrocementMember(
        layers=len([x for x in section.layers if x.fy == 450.0]),
        wireDiameter=1.0,
        spacing=13,
        exposure="waterRetaining",
        bars={"diameter": 6, "spacing": 100},
    )


def test_ferrocement_member_entry():
    beam = Beam(
        id="FB",
        name="Ferrocement plank",
        material="FC",
        profile=RectangleProfile(xDim=1000, yDim=25),
        ferrocement=FerrocementMember(),
    )
    assert F.is_ferrocement(_ferro())
    s = F.FerroSection.of(beam.profile, _ferro(), beam.ferrocement)
    rows = F.check_strength(s, [_stations("1.4D", m=0.2e6)])
    assert rows and 0 < rows[0]["utilisation"] < 1


# ─────────────────────────── the design run's glue (design/check.py) ───────────────────────────


def _piece(forces: list) -> object:
    from saengine.design.check import _Piece

    return _Piece(
        "B1",
        1,
        2.0,
        True,
        np.eye(3),
        forces,
        start=np.array([0, 0, 3.0]),
        end=np.array([2.0, 0, 3.0]),
    )


def test_glue_designs_bamboo_and_ferrocement_members():
    from saengine.design.check import _design_b39

    # Mz [N·m] of a simply supported span: 0 at the ends, peak at mid-span.
    def case(scale: float) -> np.ndarray:
        rows = np.zeros((3, 6))
        rows[1, 5] = 300.0 * scale
        rows[0, 1], rows[2, 1] = 600.0 * scale, -600.0 * scale
        return rows

    service = {"forces": {"D": {1: case(1.0)}, "L": {1: case(0.5)}}}
    bamboo_beam = Beam(
        id="BB",
        name="Bamboo beam",
        material="BAM",
        profile=CircleHollowProfile(radius=40, wallThickness=8),
        bamboo=BambooMember(joint=BambooJoint()),
    )
    ferro_beam = Beam(
        id="FB",
        name="Ferrocement plank",
        material="FC",
        profile=RectangleProfile(xDim=1000, yDim=25),
        ferrocement=FerrocementMember(),
    )
    todo = {
        "bamboo": [("m1", bamboo_beam, _bamboo(species="Bambusa tulda"), [_piece([])], False)],
        "ferrocement": [("m2", ferro_beam, _ferro(), [_piece([1.4 * case(1.0)])], False)],
    }
    checked, skipped, notes = [], [], []
    _design_b39(todo, ["1.4D"], service, checked, skipped, notes)
    assert not skipped, skipped
    by = {e["id"]: e for e in checked}
    assert by["m1"]["bamboo"]["joint"]["note"].endswith("(BNBC 2020 Part 6 Sec 4.7.1.4)")
    bending = next(c for c in by["m1"]["checks"] if c["name"].startswith("Bending"))
    assert bending["capacity"] == pytest.approx(1.25 * 13.3, abs=0.01)  # D + L: medium term
    names = [c["name"] for c in by["m2"]["checks"]]
    assert any(n.startswith("Axial force and bending") for n in names)
    assert any(n.startswith("Mesh tension at service loads") for n in names)
    assert by["m2"]["ferrocement"]["crackWidthLimit"] == 0.1

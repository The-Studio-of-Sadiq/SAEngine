"""Indian Standards pack, steel and the other materials (alpha 9 track C9): IS 800:2007 member,
connection and seismic values and methods pinned with their clauses, IS 1905 masonry, IS 11384
composite studs, the IS 808 section list, the default pack unchanged, and a small steel frame
designed under the pack.

The expected numbers are worked by hand from the values of the pack's VERIFY.md.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

PACK = "is-codes"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def is_pack():
    pack = registry.load(PACK)
    with code_context.using(pack):
        yield pack


def _shape(name: str):
    from pydantic import TypeAdapter

    from saengine.design.steel import limit_state
    from saengine.design.steel.properties import shape_properties
    from saengine.library import steel_sections
    from saengine.library.objects import Profile

    section = steel_sections.find(name)
    assert section is not None, name
    profile = TypeAdapter(Profile).validate_python(steel_sections.profile_of(section))
    return shape_properties(profile, limit_state.erw())


def test_pack_covers_steel_and_keeps_the_default_pack():
    found = registry.validate(registry.BUILTIN_DIR / PACK)
    assert not [p for p in found.problems if p.severity == "error"], found.problems
    pack = registry.load(PACK)
    for table in ("steelLimitState", "steelSections", "masonry", "timber", "composite"):
        assert pack.has(table)
    from saengine.design import steel_connections as sc
    from saengine.design.steel import limit_state
    from saengine.design.steel.lengths import MemberLengths
    from saengine.design.steel.members import Stations, Steel, check_member

    with code_context.using(registry.load("bnbc2020")):
        # BNBC keeps LRFD: no limit state table, φ 0.75 Fnv Ab of an A325N M20 bolt.
        assert limit_state.rules() is None and limit_state.erw() is True
        assert sc.bolt_shear_capacity("A325N", 20) == pytest.approx(0.75 * 330 * math.pi * 100)
        shape = _shape("ISMB 300")
        s = np.array([0.0, 3.0, 6.0])
        st = Stations(
            "c",
            s,
            np.zeros(3),
            np.array([0, 50e6, 0]),
            np.zeros(3),
            np.zeros(3),
            np.zeros(3),
            ["a", "b", "c"],
        )
        names = [
            c["name"]
            for c in check_member(shape, Steel(250, 410), [st], MemberLengths.simple(6.0), "beam")
        ]
        assert "Axial force and flexure (H1)" in names


def test_classification_and_buckling_curves(is_pack):
    """IS 800:2007 Table 2 (ε = √(250/fy)) and Table 10 (curves), Table 7 (α)."""
    from saengine.design.steel import limit_state as ls

    shape = _shape("ISMB 300")
    els = {e.name: e for e in ls.classify(shape, 250.0)}
    assert els["flange"].plastic == pytest.approx(9.4)
    assert els["web"].semi_compact == pytest.approx(126.0)
    assert ls.section_class(els.values()) == ls.PLASTIC
    # fy 410: ε = 0.781, the outstand's compact limit 10.5 ε.
    flange = ls.classify(shape, 410.0)[0]
    assert flange.compact == pytest.approx(10.5 * math.sqrt(250 / 410))
    # The web limits fall with axial compression: plastic 84 ε / (1 + r) at least 42 ε.
    web = ls.classify(shape, 250.0, axial=0.5)[1]
    assert web.plastic == pytest.approx(84 / 1.5) and web.semi_compact == pytest.approx(63.0)
    # Rolled I with h/bf > 1.2 and tf ≤ 40 mm: a (major), b (minor); channels c.
    assert ls.buckling_curves(shape) == ("a", "b")
    assert ls.buckling_curves(_shape("ISMC 200")) == ("c", "c")
    # χ at λ = 1 on curve b: φ = 0.5 (1 + 0.34 × 0.8 + 1) = 1.136.
    assert ls.chi(1.0, 0.34, 0.2) == pytest.approx(1 / (1.136 + math.sqrt(1.136**2 - 1)))
    assert ls.chi(0.15, 0.34, 0.2) == 1.0


def test_member_strengths(is_pack):
    """IS 800 7.1.2 (fcd), 8.2.2 (Mcr, χLT), 8.4.2 (post-critical shear), 6.2-6.3 (tension)."""
    from saengine.design.steel import limit_state as ls
    from saengine.design.steel.members import Steel
    from saengine.design.steel.properties import i_shape

    steel = Steel(250.0, 410.0, 200_000.0)
    shape = _shape("ISMB 300")
    comp = ls.compression(shape, steel, 3000.0, 3000.0, 3000.0, 3000.0)
    lam = math.sqrt(250 / (math.pi**2 * 2e5 / (3000 / shape.ry) ** 2))
    phi = 0.5 * (1 + 0.34 * (lam - 0.2) + lam**2)
    chi = 1 / (phi + math.sqrt(phi**2 - lam**2))
    assert comp.pdy == pytest.approx(shape.area * chi * 250 / 1.1, rel=1e-6)
    assert comp.cap.design == pytest.approx(min(comp.pdx, comp.pdy))
    # Lateral-torsional buckling over 6 m with c1 = 1.
    fl = ls.flexure_major(shape, steel, 6000.0, 1.0)
    mcr = math.sqrt(
        (math.pi**2 * 2e5 * shape.iy / 6000**2)
        * (76900 * shape.j + math.pi**2 * 2e5 * shape.cw / 6000**2)
    )
    lam_lt = math.sqrt(shape.zx * 250 / mcr)
    phi_lt = 0.5 * (1 + 0.21 * (lam_lt - 0.2) + lam_lt**2)
    chi_lt = 1 / (phi_lt + math.sqrt(phi_lt**2 - lam_lt**2))
    assert fl.cap.state == "lateral-torsional buckling"
    assert fl.cap.design == pytest.approx(shape.zx * chi_lt * 250 / 1.1, rel=1e-6)
    # A short span is laterally supported: Zp fy / γm0 (≤ 1.2 Ze fy / γm0).
    short = ls.flexure_major(shape, steel, 500.0, 1.0)
    assert short.cap.design == pytest.approx(min(shape.zx, 1.2 * shape.sx) * 250 / 1.1)
    # A plate girder web d/tw = 960/8 = 120 > 67 ε: τcr,e = 5.35 π² E / (12 (1 - 0.09) 120²).
    girder = i_shape(1000.0, 300.0, 20.0, 8.0)
    v = ls.shear_capacity(girder, steel, "y")
    tau_e = 5.35 * math.pi**2 * 2e5 / (12 * 0.91 * 120**2)
    lam_w = math.sqrt(250 / (math.sqrt(3) * tau_e))
    assert lam_w > 1.2 and v.state == "shear buckling of the web"
    assert v.design == pytest.approx(1000 * 8 * 250 / (math.sqrt(3) * lam_w**2) / 1.1)
    # Tension: 0.9 An fu / γm1; a single angle with 2 bolts α = 0.6.
    tr = ls.tension_rupture(shape, steel)
    assert tr.design == pytest.approx(0.9 * shape.area * 410 / 1.25)
    assert ls.angle_alpha(2) == 0.6 and ls.angle_alpha(9) == 0.8


def test_member_check_rows_and_interaction(is_pack):
    from saengine.design.steel import limit_state as ls
    from saengine.design.steel.lengths import MemberLengths
    from saengine.design.steel.members import Stations, Steel, check_member

    shape = _shape("ISMB 300")
    n = 11
    s = np.linspace(0.0, 6.0, n)
    x = s * 1000
    st = Stations(
        "1.5(D + L)",
        s,
        np.full(n, 200e3),
        20.0 * x * (6000 - x) / 2,
        np.zeros(n),
        20.0 * (3000 - x),
        np.zeros(n),
        [f"{v:.1f} m" for v in s],
    )
    rows = {
        c["name"]: c
        for c in check_member(shape, Steel(250, 410), [st], MemberLengths.simple(6.0), "column")
    }
    assert ls.SECTION_ROW in rows and ls.MEMBER_ROW in rows
    assert "IS 800:2007 9.3.2.2" in rows[ls.MEMBER_ROW]["clause"]
    assert "IS 800:2007 8.2.2" in rows["Flexure about x (major)"]["clause"]
    # KL/r = 6000 / ry > 180 (Table 3).
    assert rows["Slenderness KL/r (compression)"]["capacity"] == 180.0
    assert not rows["Slenderness KL/r (compression)"]["ok"]


def test_connection_strengths(is_pack):
    """IS 800 10.3.3-10.3.6, 10.4.3, 10.5.7, 6.4.1 through the shared connection helpers."""
    from saengine.design import steel_connections as sc

    anb = 0.78 * math.pi * 20**2 / 4
    assert sc.bolt_shear_capacity("8.8", 20) == pytest.approx(800 / (math.sqrt(3) * 1.25) * anb)
    tdb, _ = sc.bolt_tension_capacity("8.8", 20)
    assert tdb == pytest.approx(0.9 * 800 * anb / 1.25)
    # Bearing at an end distance 40 mm, d0 = 22 mm (Table 19): kb = 40 / (3 × 22).
    assert sc.hole_diameter(20) == 22 and sc.hole_diameter(24) == 26
    assert sc.bearing_capacity(20, 10, 410, 40 - 11, "end") == pytest.approx(
        2.5 * (40 / 66) * 20 * 10 * 410 / 1.25
    )
    # A 6 mm fillet with fu 410: 0.7 s fu / (√3 γmw).
    assert sc.fillet_capacity_per_mm(6, 410) == pytest.approx(0.7 * 6 * 410 / (math.sqrt(3) * 1.25))
    assert sc.block_shear(250, 410, 10000, 8000, 1500) == pytest.approx(
        min(
            10000 * 250 / (math.sqrt(3) * 1.1) + 0.9 * 1500 * 410 / 1.25,
            0.9 * 8000 * 410 / (math.sqrt(3) * 1.25) + 1500 * 250 / 1.1,
        )
    )
    # βlj of a 400 mm joint of M20 bolts (> 15 d): 1.075 - 0.005 × 20.
    assert sc.long_joint_factor(400, False, 20) == pytest.approx(0.975)

    class C:
        boltGrade, surfaceClass, holeType, slipCritical = "8.8", "B", "standard", "strength"

    vdsf, note = sc.slip_capacity(C, 20)
    assert vdsf == pytest.approx(0.5 * 0.7 * 800 * anb / 1.25) and "IS 800:2007 10.4.3" in note
    # The parent's clause texts in the notes are rewritten or named after the parent.
    row = sc._check("x", 1, 2, "kN", None, "Eq 6.10.168; Sec 10.10.10.2 rule")
    assert row["note"] == "IS 800:2007 10.3.3; BNBC 2020 Part 6 Sec 10.10.10.2 rule"


def test_sections_deflection_and_seismic_rules(is_pack):
    from saengine.design.steel import limit_state as ls
    from saengine.library import steel_sections
    from saengine.verification.cases.common import settings

    # C9b adds ISLB, ISWB and ISHB.
    assert steel_sections.FAMILIES == (
        "ISLB",
        "ISMB",
        "ISWB",
        "ISHB",
        "ISMC",
        "L",
        "SHS",
        "RHS",
        "CHS",
    )
    assert steel_sections.find("IPE 300") is None and steel_sections.find("ISMB 300") is not None
    limits = is_pack.table("serviceability").deflection
    assert (limits.uses["floor"].live, limits.uses["floorBrittle"].live) == (300, 360)
    assert limits.cantileverSpan == 2.0  # span/150 of a cantilever
    frames = ls.seismic_frames(settings(system="steelSmf"))
    assert list(frames) == ["smf"]
    rules = ls.seismic_rules()
    assert (
        rules.frames["ocbf"].braceSlenderness == 120
        and rules.frames["scbf"].braceSlenderness == 160
    )
    assert rules.frames["smf"].strongColumn == 1.2


def test_masonry_and_composite(is_pack):
    """IS 1905 Tables 8 and 9, 5.4.1.2; IS 11384 Table 1 studs."""
    from saengine.design import masonry as M
    from saengine.design import masonry_basic_stress as B
    from saengine.design import walls as W
    from saengine.design.steel.composite import composite_table, tabulated_stud

    assert M.method_id() == "basicStress"
    grade, sand, row = B.mortar_row(M.Masonry(5.0, mortar="M4"))  # the 1:6 mix: IS M2
    assert (grade, sand) == ("M2", 6.0) and B.basic_stress(10.0, row) == pytest.approx(0.81)
    assert B.stress_reduction(12, 0.0) == pytest.approx(0.84)
    assert B.stress_reduction(13, 1 / 24) == pytest.approx((0.81 + 0.75) / 2, abs=1e-3)
    assert B.stress_reduction(27, 1 / 3) is None
    assert B.area_factor(0.1) == pytest.approx(0.85) and B.area_factor(0.3) == 1.0
    wall = W.WallGeometry(length=3000, thickness=230, height=3000, clear_height=2850)
    m = M.Masonry(5.0, mortar="M4", unit_strength=10.0)
    forces = [W.PierForces("D + L", 300e3, 20e3, 10e6, 0.0, 1e6)]
    d = B.wall_checks(wall, None, forces, m)
    axial = next(c for c in d.checks if c["name"].startswith("Axial stress"))
    sr = 0.75 * 2850 / 230
    e_t = 1e6 / 300e3 / 230
    assert axial["demand"] == pytest.approx(300e3 / (230 * 3000), abs=0.01)
    assert axial["capacity"] == pytest.approx(0.81 * B.stress_reduction(sr, e_t), abs=0.01)
    t = composite_table().beam.limitState
    assert tabulated_stud(20, 100, 25, t) == pytest.approx(66e3)
    assert tabulated_stud(20, 100, 22.5, t) == pytest.approx(64.5e3)
    assert tabulated_stud(19, 100, 25, t) == pytest.approx(46e3)  # the 16 × 75 row


def test_steel_frame_is_designed_under_the_pack(tmp_path):
    """A braced steel portal (ISMB columns and beam with a fin plate, an SHS brace with a
    gusset) analysed and designed under the pack: IS 800 rows and connection strengths."""
    from pydantic import TypeAdapter

    from saengine.design import steel_design
    from saengine.design.check import _demands
    from saengine.library import steel_sections
    from saengine.library.objects import Profile
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

    pack = registry.load(PACK)
    with code_context.using(pack):
        ismb = (
            TypeAdapter(Profile)
            .validate_python(steel_sections.profile_of(steel_sections.find("ISMB 250")))
            .model_dump()
        )
        shs = {"shape": "rectangleHollow", "xDim": 150, "yDim": 150, "wallThickness": 8}
        types = objects(
            {"id": "COL", "name": "col", "kind": "column", "material": "A992", "profile": ismb},
            {
                "id": "BM",
                "name": "beam",
                "kind": "beam",
                "material": "A992",
                "profile": ismb,
                "connection": {"type": "finPlate", "rows": 4, "boltGrade": "8.8"},
            },
            {
                "id": "BR",
                "name": "brace",
                "kind": "brace",
                "material": "A992",
                "profile": shs,
                "connection": {"type": "gusset", "tabThickness": 10, "boltGrade": "8.8"},
            },
        )
        model = structure(
            members=[
                {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3200)},
                {
                    "id": "C2",
                    "type": "COL",
                    "start": point(6000, 0, 0),
                    "end": point(6000, 0, 3200),
                },
                {"id": "B1", "type": "BM", "start": point(0, 0, 3200), "end": point(6000, 0, 3200)},
                {"id": "M1", "type": "BR", "start": point(0, 0, 0), "end": point(6000, 0, 3200)},
            ],
            supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
        )
        building = building_of(model)
        project = derive(building, types, MATERIALS, settings()).project
        top = node_at(project, (0, 0, 3.2))
        wx = next(p for p in project["load_patterns"] if p["name"] == "WX")
        wx["nodal_loads"] = [{"node_id": top, "forces": [100e3, 0, 0, 0, 0, 0]}]
        beam = next(e["id"] for e in project["elements"] if e["name"] == "B1")
        project["load_patterns"][0]["element_loads"].append(
            {"element_id": beam, "wy": 0.0, "wz": -20e3, "wx": 0.0}
        )
        static = [a["id"] for a in project["analyses"] if a["type"] == "Static"]
        _, out, _ = run_model(project, tmp_path, static)
        s = settings().model_copy(
            update={"combinations": [LoadCombination(name="1.2(D + W)", D=1.2, WX=1.2)]}
        )
        combinations, pieces, _, _ = _demands(project, out, s)
        by_type = {t.id: t for t in types.objects}
        mats = {m.id: m for m in MATERIALS.materials}
        entries = {}
        for element in building.elements:
            t = by_type[element.type]
            entries[element.id] = steel_design.design_member(
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
        method = steel_design.METHOD
    beam_entry, _ = entries["B1"]
    names = {c["name"]: c for c in beam_entry["checks"]}
    assert (
        "Flexure about x (major)" in names
        and "IS 800:2007" in names["Flexure about x (major)"]["clause"]
    )
    assert "Axial force and flexure (H1)" not in names
    assert beam_entry["section"]["class"] in ("plastic", "compact", "semi-compact", "slender")
    connection = [c for c in beam_entry["checks"] if c["name"].startswith("Connection:")]
    assert connection and any("IS 800:2007 10.3.3" in c["note"] for c in connection)
    brace_entry, _ = entries["M1"]
    assert any(c["name"] == "Compression: buckling" for c in brace_entry["checks"]) or any(
        c["name"].startswith("Tension") for c in brace_entry["checks"]
    )
    assert any("IS 800:2007" in line for line in method)

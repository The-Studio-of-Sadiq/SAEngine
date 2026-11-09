"""Alpha 9 L7: special members. Steel joists and joist girders (the generic open-web truss by
the pack's steel checks, the SJI rules of the US pack), castellated and cellular beams (AISC
DG31 in the US pack, SCI P355 in the Eurocodes pack), aluminium joints (EN 1999-1-1 Section 8),
structural glass (EN 16612 / ASTM E1300 type), tensile membranes by force density and
concrete-filled composite plate shear walls (AISC 341-22 H7). The bnbc2020 pack covers none of
the new tables (its results unchanged).

Written for the alpha 9 test pass (not run when written, owner 2026-11-05)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.codes.tables import TABLE_MODELS, builtin_manifest
from saengine.design import composite_plate_walls as cpw
from saengine.design import glass as gl
from saengine.design import membranes as mb
from saengine.design import steel_joists as sj
from saengine.design.steel import pack_resistance as pr
from saengine.design.steel import web_openings as wo
from saengine.design.steel.lengths import MemberLengths
from saengine.design.steel.members import Stations
from saengine.design.steel.properties import angle, i_shape
from saengine.fem import form_finding as ff
from saengine.library.materials import Material
from saengine.library.objects import (
    AluminiumJoint,
    Beam,
    BeamWebOpenings,
    FilledPlateWall,
    GlassFin,
    GlassPanel,
    IShapeProfile,
    Membrane,
    ObjectLibrary,
    RectangleProfile,
    SteelJoist,
    Wall,
)

NEW_TABLES = ("steelJoists", "webOpenings", "glass", "membranes", "compositePlateWalls")

STEEL = Material.model_validate(
    {
        "id": "A992",
        "name": "A992",
        "category": "steel",
        "mechanical": {"E": 200000, "density": 7850},
        "steel": {"fy": 345, "fu": 450},
    }
)
GLASS = Material.model_validate(
    {
        "id": "GT",
        "name": "Toughened",
        "category": "glass",
        "mechanical": {"E": 70000, "density": 2500, "nu": 0.22},
        "glass": {"kind": "toughened"},
    }
)
ALU = Material.model_validate(
    {
        "id": "AW6082",
        "name": "6082",
        "category": "aluminium",
        "mechanical": {"E": 70000, "density": 2700},
        "aluminium": {"alloy": "EN AW-6082 T6"},
    }
)
FILL = Material.model_validate(
    {
        "id": "C40",
        "name": "C40",
        "category": "concrete",
        "mechanical": {"E": 30000, "density": 2400},
        "concrete": {"fc": 40},
    }
)


@pytest.fixture(autouse=True)
def _fresh():
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def us():
    pack = registry.load("aci318-asce7-22")
    with code_context.using(pack):
        yield pack


@pytest.fixture
def ec():
    pack = registry.load("eurocodes")
    with code_context.using(pack):
        yield pack


@pytest.fixture
def bnbc():
    pack = registry.load("bnbc2020")
    with code_context.using(pack):
        yield pack


def _stations(span_m: float, mu: float, name: str = "ULS") -> Stations:
    """A simply supported beam under a uniform load: Mx < 0 sagging (Mx > 0 stretches the
    top), the largest moment ``mu`` [N·mm]."""
    s = np.linspace(0, span_m, 41)
    m = -4 * mu * s * (span_m - s) / span_m**2
    w = 8 * mu / (span_m * 1e3) ** 2  # N/mm
    v = w * (span_m * 1e3 / 2 - s * 1e3)
    z = np.zeros_like(s)
    return Stations(name, s, z, m, z, v, z, [f"at {x:.2f}" for x in s])


# ─────────────────────────────────────── packs and models ───────────────────────────────────────


def test_tables_registered_and_only_in_the_us_and_eu_packs():
    for name in NEW_TABLES:
        assert name in TABLE_MODELS
    assert not set(NEW_TABLES) & set(builtin_manifest("bnbc2020")["covers"])
    us_covers = set(builtin_manifest("aci318-asce7-22")["covers"])
    assert set(NEW_TABLES) <= us_covers
    eu_covers = set(builtin_manifest("eurocodes")["covers"])
    assert {"webOpenings", "glass", "membranes"} <= eu_covers
    assert "compositePlateWalls" not in eu_covers and "steelJoists" not in eu_covers


def test_pack_values_with_their_clauses(us, ec):
    t = us.table("steelJoists")
    assert t.slenderness.topChordInterior == 90 and t.slenderness.compressionWeb == 200
    assert t.leastWebShare == 0.25 and t.loadTables == []
    w = us.table("webOpenings")
    assert w.webPost.method == "ward" and len(w.webPost.wardCoefficients) == 9
    assert us.table("glass").method == "loadResistance"
    assert us.table("compositePlateWalls").factors.compression == 0.75
    with code_context.using(ec):
        g = ec.table("glass")
        assert g.method == "partialFactors" and g.partialFactors.annealed == 45
        assert g.partialFactors.prestressed["toughened"] == 120
        assert ec.table("aluminium").joints.gammaMw == 1.25


def test_library_models_and_membrane_kind():
    beam = Beam(
        id="J1",
        name="Joist",
        material="A992",
        profile=IShapeProfile(
            overallDepth=200, overallWidth=100, flangeThickness=6, webThickness=4
        ),
        joist=SteelJoist(),
        webOpenings=None,
    )
    assert beam.joist.topChord.double
    lib = ObjectLibrary.model_validate(
        {"objects": [{"id": "M1", "name": "Sail", "kind": "membrane", "material": "PTFE"}]}
    )
    assert isinstance(lib.objects[0], Membrane) and len(lib.objects[0].corners) == 4
    assert GLASS.glass.kind == "toughened"
    with pytest.raises(ValueError):
        Material.model_validate(
            {"id": "G", "name": "G", "category": "glass", "mechanical": {"E": 70000}}
        )


# ─────────────────────────────────────── steel joists ───────────────────────────────────────


def test_two_angles_act_as_a_tee():
    pair = pr.doubled(angle(50, 50, 5))
    assert pair.family == "tee"
    assert pair.area == pytest.approx(2 * angle(50, 50, 5).area, rel=1e-6)


def test_joist_geometry_and_effective_inertia(us):
    joist = SteelJoist(depth=600, panel=600)
    g = sj.geometry(joist, 9000)
    assert g["panels"] == 15 and g["p"] == pytest.approx(600)
    assert 500 < g["d"] < 600
    i_ch, i_eff = sj.effective_inertia(g, 9000, 200000)
    assert 0 < i_eff < i_ch  # the webs' shear deformation softens the truss


def test_generic_truss_without_the_table(ec):
    joist = SteelJoist(depth=600, panel=600)
    checks, summary = sj.check_joist(joist, STEEL, [_stations(9.0, 60e6)], 9000)
    names = {c["name"] for c in checks}
    assert "Joist top chord: compression" in names and "Joist webs: compression" in names
    assert summary["generic"] is True
    assert not any("slenderness" in n for n in names)  # no specification rules
    top = next(c for c in checks if c["name"] == "Joist top chord: compression")
    assert "generic open-web truss" in top["note"]


def test_us_joist_rules_and_bridging(us):
    joist = SteelJoist(depth=600, panel=600)
    checks, summary = sj.check_joist(joist, STEEL, [_stations(9.0, 60e6)], 9000)
    names = {c["name"] for c in checks}
    assert "Joist webs: slenderness (compression)" in names
    assert summary["bridging"]["rows"] >= 1
    # chord force N = M / d
    top = next(c for c in checks if c["name"] == "Joist top chord: compression")
    assert top["demand"] == pytest.approx(60e6 / sj.geometry(joist, 9000)["d"] / 1e3, rel=0.02)


def test_joist_deflection_scaling():
    entry = {"joist": {"deflection": {"stiffening": 2.0}}}
    moved = sj.scale_profiles(entry, {"D": np.ones((3, 3))})
    assert float(moved["D"][0, 0]) == 2.0
    assert sj.scale_profiles({}, {"D": np.ones(2)})["D"][0] == 1.0


# ─────────────────────────────────── castellated and cellular ───────────────────────────────────


def _cellular_beam(shape: str = "circular") -> Beam:
    return Beam(
        id="CB",
        name="Cellular",
        material="A992",
        profile=IShapeProfile(
            overallDepth=600, overallWidth=200, flangeThickness=15, webThickness=10
        ),
        webOpenings=BeamWebOpenings(shape=shape, depth=400, spacing=600),
    )


def test_opening_geometry():
    beam = _cellular_beam()
    shape = i_shape(600, 200, 15, 10)
    g = wo.geometry(beam.webOpenings, shape, 9000)
    assert g["w0"] == pytest.approx(200)
    assert g["stem"] == pytest.approx(100)
    assert len(g["centres"]) == 15  # (9000 - 400) // 600 + 1
    assert g["centres"][0] + g["centres"][-1] == pytest.approx(9000)


@pytest.mark.parametrize("pack_fixture", ["us", "ec"])
def test_openings_checks_added(pack_fixture, request):
    request.getfixturevalue(pack_fixture)
    beam = _cellular_beam()
    entry = {"checks": [], "utilisation": 0.0, "ok": True}
    wo.apply(entry, beam, STEEL, [_stations(9.0, 300e6)], MemberLengths.simple(9.0))
    names = [c["name"] for c in entry["checks"]]
    assert "Web posts: buckling" in names and "Openings: tee shear" in names
    assert entry["webOpenings"]["covered"]
    assert entry["webOpenings"]["deflection"]["stiffening"] > 1.0


def test_openings_not_covered_by_the_default_pack(bnbc):
    entry = {"checks": [], "utilisation": 0.0, "ok": True}
    wo.apply(entry, _cellular_beam(), STEEL, [_stations(9.0, 100e6)], MemberLengths.simple(9.0))
    assert entry["ok"] is False and entry["webOpenings"]["covered"] is False


# ───────────────────────────────────────── aluminium joints ─────────────────────────────────────────


def test_aluminium_bolted_and_welded_joints(ec):
    from saengine.design import aluminium as al

    st = _stations(4.0, 10e6)
    rows = al.joint_checks(AluminiumJoint(), ALU, [st])
    assert [r["name"] for r in rows] == ["Joint: bolt shear", "Joint: bearing on the aluminium"]
    # Fv,Rd = 0.6 × 800 × 0.78 × π 12² / 4 / 1.25 = 33.9 kN
    assert rows[0]["capacity"] == pytest.approx(0.6 * 800 * 0.78 * math.pi * 36 / 1.25 / 1e3, 0.01)
    welded = al.joint_checks(AluminiumJoint(kind="welded"), ALU, [st])
    assert [r["name"] for r in welded] == [
        "Joint: fillet welds",
        "Joint: heat-affected zone at the weld",
    ]


# ───────────────────────────────────────────── glass ─────────────────────────────────────────────


def test_laminated_effective_thickness_limits():
    mono = gl.effective_thickness([10], 0.76, 0.4, 70000, 1500)
    assert mono["stress"] == 10
    layered = gl.effective_thickness([8, 8], 0.76, 1e-9, 70000, 1500)
    assert layered["omega"] == pytest.approx(0, abs=1e-6)
    assert layered["deflection"] == pytest.approx((2 * 8**3) ** (1 / 3), rel=1e-6)
    full = gl.effective_thickness([8, 8], 0.76, 1e9, 70000, 1500)
    assert full["omega"] == pytest.approx(1, abs=1e-6)
    assert full["deflection"] > 16  # the interlayer adds to the lever arm


def test_plate_coefficients_square_and_long():
    assert gl.plate_coefficients(1.0) == pytest.approx((0.2874, 0.0444))
    assert gl.plate_coefficients(100.0)[0] == pytest.approx(0.75, rel=1e-3)


def test_glass_panel_en16612(ec):
    entry = gl.check_panel("GP", GlassPanel(windPressure=1.5), GLASS, False)
    rows = {c["name"]: c for c in entry["checks"]}
    assert "Glass strength: wind" in rows and "Glass deflection: wind" in rows
    f, _ = gl.strength("toughened", "float", "wind")
    assert f == pytest.approx(0.74 * 45 / 1.8 + (120 - 45) / 1.2, rel=1e-6)


def test_glass_balustrade_uses_the_pack_barrier_load(us):
    panel = GlassPanel(use="balustrade", support="cantilever", height=1100, plies=[10, 10])
    entry = gl.check_panel("BAL", panel, GLASS, False)
    assert any(c["name"] == "Glass strength: barrier" for c in entry["checks"])
    assert "barrier line load" in entry["glass"]["notes"][0]


def test_glass_fin(ec):
    entry = gl.check_fin("FIN", GlassFin(), RectangleProfile(xDim=30, yDim=300), GLASS)
    names = [c["name"] for c in entry["checks"]]
    assert names == [
        "Glass fin: bending stress",
        "Glass fin: lateral-torsional buckling",
        "Glass fin: deflection",
    ]


def test_glass_not_covered_by_the_default_pack(bnbc):
    wall = Wall(
        id="GW", name="Glass", material="GT", thickness=16, glass=GlassPanel(windPressure=1)
    )
    entries, skipped, _ = gl.design_types({"GW": wall}, {"GT": GLASS})
    assert entries == [] and "not covered" in skipped[0]["reason"]


# ──────────────────────────────────────────── membranes ────────────────────────────────────────────


def test_force_density_form_of_a_hypar_is_saddle_shaped():
    corners = np.array([[0, 0, 0], [10000, 0, 3000], [10000, 10000, 0], [0, 10000, 3000]], float)
    net = ff.mesh(corners, 8, 2.0, 2.0, True, 30e3)
    form = ff.find_form(net)
    centre = form.xyz[(9 * 9) // 2]
    assert 0 < centre[2] < 3000  # between the low and high corners
    # equilibrium of a free node at the found form
    k = (9 * 9) // 2
    pull = np.zeros(3)
    for (a, b), t in zip(form.links, form.prestress, strict=True):
        if k in (a, b):
            other = b if a == k else a
            d = form.xyz[other] - form.xyz[k]
            pull += t * d / np.linalg.norm(d)
    assert np.linalg.norm(pull) < 1e-6 * max(form.prestress)


def test_membrane_checks_under_the_pack_cases(us):
    membrane = Membrane(
        id="M1", name="Sail", material="PVC", divisions=8, snow=0.5, windPressure=0.6,
        windSuction=0.8,
    )  # fmt: skip
    entry = mb.check_membrane("M1", membrane)
    names = [c["name"] for c in entry["checks"]]
    assert "Fabric warp stress: Prestress + snow" in names
    assert "Edge cables: Prestress + wind suction" in names
    assert len(entry["membrane"]["reactions"]) == 4
    assert entry["membrane"]["area"] > 100  # m², the 10 m x 10 m sail's surface


def test_membranes_not_covered_by_the_default_pack(bnbc):
    _, skipped, _ = mb.design_types({"M1": Membrane(id="M1", name="S", material="PVC")})
    assert "not covered" in skipped[0]["reason"]


# ─────────────────────────────────── concrete-filled plate walls ───────────────────────────────────


def test_filled_plate_wall_shear_and_flexure(us):
    vn = cpw.shear_strength(12, 3000, 400, 345, 200000, 30000)
    as_fy = 2 * 12 * 3000 * 345
    assert 0 < vn < as_fy  # κ < 1 of the plates' yield
    mn0, c0 = cpw.plastic_moment(0.0, 12, 3000, 400, 345, 40)
    _mn1, c1 = cpw.plastic_moment(5e6, 12, 3000, 400, 345, 40)
    assert c1 > c0 and mn0 > 0


def test_filled_plate_wall_entry(us):
    wall = Wall(
        id="SC",
        name="SpeedCore",
        material="C40",
        thickness=400,
        filledPlate=FilledPlateWall(plateMaterial="A992"),
    )
    element = SimpleNamespace(id="W1", start=[0, 0], end=[3000, 0])
    sections = [
        {"section": "W1/L1", "cuts": {"bottom": {"ULS": {"P": 2000, "V2": 1500, "M3": 4000}}}}
    ]
    entries, skipped, _ = cpw.design_walls(
        [(element, wall, FILL)], {"W1": sections}, {"A992": STEEL}
    )
    assert skipped == []
    names = [c["name"] for c in entries[0]["checks"]]
    assert "Filled plate wall: in-plane shear" in names
    assert "Tie spacing for composite action s / tp" in names
    assert entries[0]["wallType"] == "filledPlate"

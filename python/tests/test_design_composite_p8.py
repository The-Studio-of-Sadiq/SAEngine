"""Alpha 9 P8: composite slabs on steel deck (EN 1994-1-1 Section 9, the eurocodes pack's
``compositeSlab``), the slab's longitudinal shear of composite beams (EN 1994-1-1 6.6.6), the
camber of unshored beams, the composite floor's dynamic stiffness, the design mode's composite
checker and the drawings' composite notes. The bnbc2020 pack covers none of the new groups
(its results unchanged)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.codes.tables import builtin_table
from saengine.design import composite_slab as cs
from saengine.design.steel import composite as cp
from saengine.design.steel.lengths import MemberLengths
from saengine.design.steel.members import Stations
from saengine.design.steel.properties import chs, i_shape
from saengine.library.materials import Material
from saengine.library.objects import (
    Beam,
    CompositeBeam,
    CompositeColumn,
    CompositeSlabDeck,
    IShapeProfile,
    ShearConnectors,
    SlabTransverseBars,
)

STEEL = Material.model_validate(
    {
        "id": "S355",
        "name": "S355",
        "category": "steel",
        "mechanical": {"E": 210000, "density": 7850},
        "steel": {"fy": 355, "fu": 490},
    }
)
C30 = Material.model_validate(
    {
        "id": "C30",
        "name": "C30",
        "category": "concrete",
        "mechanical": {"E": 33000, "density": 2400},
        "concrete": {"fc": 30},
    }
)
W450 = i_shape(450, 200, 14, 9)


@pytest.fixture(autouse=True)
def _fresh():
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def ec():
    pack = registry.load("eurocodes")
    with code_context.using(pack):
        yield pack


def _beam_stations(span: float = 8.0, mu: float = 600e6) -> Stations:
    s = np.linspace(0, span, 21)
    m = -4 * mu * s * (span - s) / span**2
    z = np.zeros_like(s)
    return Stations("ULS", s, z, m, z, z, z, [f"B1 at {x:.2f}" for x in s])


# ─────────────────────────────────────── the packs ───────────────────────────────────────


def test_bnbc_covers_none_of_the_new_groups():
    t = builtin_table("composite")
    assert t.beam.longitudinalShear is None and t.beam.camber is None
    assert not registry.load("bnbc2020").has("compositeSlab")
    assert builtin_table("floorVibration").compositeDynamicModulus is None


def test_eurocodes_composite_slab_values(ec):
    t = cs.table()
    # EN 1994-1-1 2.4.1.2, 9.7.2, 9.7.3, 9.3.2(2), 9.6(2), 9.2.1, 9.8.1(2); EN 1991-1-6 4.11.1
    assert (t.gammaC, t.gammaAp, t.gammaVs) == (1.5, 1.0, 1.25)
    assert (t.gammaG, t.gammaQ) == (1.35, 1.5)
    assert t.concreteShare == 0.85 and t.plasticReduction == 1.25 and t.shearSpanShare == 0.25
    assert t.longitudinalShear == ["mk", "partialConnection"]
    assert (t.ponding.threshold, t.ponding.share) == (0.1, 0.7)
    assert (t.deflection.construction, t.deflection.service) == (180, 250)
    assert (t.thickness.overall, t.thickness.aboveRibs) == (80, 40)
    assert (t.thickness.beamFlangeOverall, t.thickness.beamFlangeAboveRibs) == (90, 50)
    assert tuple(t.antiCrack) == (0.002, 0.004)
    cl = t.constructionLoad
    assert (cl.workingShare, cl.workingMin, cl.workingMax, cl.outside) == (0.1, 0.75, 1.5, 0.75)
    beam = cp.composite_table().beam
    assert beam.longitudinalShear.method == "flangeStrut"
    assert tuple(beam.longitudinalShear.cotTheta) == (1.0, 2.0)
    assert (beam.camber.share, beam.camber.minimum, beam.camber.step) == (0.8, 20, 5)


# ─────────────────────────────────────── the deck ───────────────────────────────────────


def test_deck_section_of_a_symmetric_trapezoid():
    deck = CompositeSlabDeck()  # 60/300, ribs 180 at the top, 120 at the bottom, t 0.9
    sec = cs.deck_section(deck, 350.0)
    web = math.hypot(60, 30)
    per_pitch = 0.9 * (120 + 120 + 2 * web)
    assert sec.ap == pytest.approx(per_pitch * 1000 / 300)
    # Equal flanges: the centroid and the plastic neutral axis at mid-height.
    assert sec.e == pytest.approx(30.0) and sec.ep == pytest.approx(30.0)
    ip = 2 * 0.9 * 120 * 30**2 + 2 * 0.9 * web * 60**2 / 12
    assert sec.ip == pytest.approx(ip * 1000 / 300)
    first = 2 * 0.9 * 120 * 30 + 2 * 0.9 * web / 60 * (30**2 + 30**2) / 2
    assert sec.mpa == pytest.approx(350 * first * 1000 / 300)
    assert sec.b0 == pytest.approx(150) and sec.ribs_share == pytest.approx(0.5)


def test_deck_profile_and_given_values():
    deck = CompositeSlabDeck(profile="generic trapezoidal 80/300", area=1200, inertia=1.1e6)
    sec = cs.deck_section(deck, 350.0)
    assert sec.hp == 80 and sec.ap == 1200 and sec.ip == 1.1e6
    with pytest.raises(cs.CompositeSlabError):
        cs.deck_section(CompositeSlabDeck(profile="nope"), 350.0)


def test_plastic_sagging_resistance_eq_9_5_and_9_6():
    sec = cs.deck_section(CompositeSlabDeck(), 350.0)
    block = 0.85 * 30 / 1.5
    np_ = sec.ap * 350
    # Neutral axis in the slab (Np <= Ncf): MRd = Np (dp - x/2).
    x = np_ / (block * 1000)
    assert cs.moment_resistance(np_, np_, sec, 130, block, 1.25) == pytest.approx(
        np_ * (130 - 30 - x / 2)
    )
    # Neutral axis in the deck: Nc = Ncf < Np, Mpr = 1.25 Mpa (1 - Ncf/Np) <= Mpa.
    ncf = 0.6 * np_
    x = ncf / (block * 1000)
    mpr = min(1.25 * sec.mpa * 0.4, sec.mpa)
    z = 130 - 0.5 * x - sec.ep + (sec.ep - sec.e) * 0.6
    assert cs.moment_resistance(ncf, np_, sec, 130, block, 1.25) == pytest.approx(ncf * z + mpr)


def _inputs(**kw) -> cs.SlabInputs:
    data = {
        "h": 130.0,
        "fck": 30.0,
        "ecm": 33000.0,
        "density": 2400 * 9.80665 / 1e3,
        "span": 3000.0,
        "superimposed": 1.5,
        "live": 3.0,
        "combinations": [("6.10", 1.35, 1.5)],
        "top": (142.0, 142.0),
    }
    data.update(kw)
    return cs.SlabInputs(**data)


def test_construction_stage_simple_span(ec):
    rules = cs.table()
    deck = CompositeSlabDeck(momentResistance=6.0, inertia=2.0e6)  # stiff: no ponding
    sec = cs.deck_section(deck, 350.0)
    inp = _inputs()
    rows, delta, _ = cs.construction_rows(deck, sec, inp, rules, 350.0)
    mean = 130 - 60 * 0.5
    g = (inp.density + 1.0) * mean / 1e3
    assert delta == pytest.approx(5 / 384 * (g + sec.weight) * 3000**4 / (210000 * sec.ip))
    q_in = min(max(0.1 * g, 0.75), 1.5)
    patch = (q_in - 0.75) * 3000 * (2 * 3000 - 3000) / 8
    m_ed = 1.35 * (g + sec.weight) * 3000**2 / 8 + 1.5 * (0.75 * 3000**2 / 8 + patch)
    names = {r["name"]: r for r in rows}
    bending = names["Composite slab: deck bending, construction stage"]
    assert bending["demand"] == pytest.approx(m_ed / 1e6, abs=0.01)
    assert bending["capacity"] == pytest.approx(6.0) and not bending["flag"]
    assert names["Composite slab: deck deflection, construction stage"]["capacity"] == (
        pytest.approx(3000 / 180, abs=0.01)
    )
    # Propped: no construction stage rows.
    assert cs.construction_rows(CompositeSlabDeck(propped=True), sec, inp, rules, 350.0)[0] == []


def test_mk_longitudinal_shear_eq_9_7_and_the_full_check(ec):
    deck = CompositeSlabDeck(m=150.0, k=0.05, momentResistance=6.0)
    found = cs.check(deck, _inputs())
    names = {r["name"]: r for r in found["checks"]}
    sec = cs.deck_section(deck, 350.0)
    dp = 130 - sec.e
    v_l = 1000 * dp / 1.25 * (150 * sec.ap / (1000 * 750) + 0.05)
    row = names["Composite slab: longitudinal shear (m-k)"]
    assert row["capacity"] == pytest.approx(v_l / 1e3, abs=0.01)
    mean = 130 - 60 * 0.5
    own = 2400 * 9.80665 / 1e3 * mean / 1e3 + sec.weight
    w_ed = 1.35 * (own + 1.5) + 1.5 * 3.0
    assert row["demand"] == pytest.approx(w_ed * 3000 / 2 / 1e3, abs=0.01)
    assert names["Composite slab: sagging bending (plastic)"]["demand"] == pytest.approx(
        w_ed * 3000**2 / 8 / 1e6, abs=0.01
    )
    assert "Composite slab: vertical shear" in names  # EN 1992-1-1 6.2.2 by concreteMethods
    anti = names["Composite slab: anti-crack bars above the ribs"]
    assert anti["demand"] == pytest.approx(0.002 * 70 * 1000)
    assert anti["ok"]  # 142 mm²/m each way
    assert names["Composite slab: depth above the ribs"]["ok"]


def test_no_test_values_flag_the_longitudinal_shear(ec):
    found = cs.check(CompositeSlabDeck(), _inputs(top=(None, None)))
    names = {r["name"]: r for r in found["checks"]}
    assert names["Composite slab: longitudinal shear"]["flag"]
    assert not names["Composite slab: anti-crack bars above the ribs"]["ok"]


def test_partial_connection_method(ec):
    deck = CompositeSlabDeck(tauU=0.3, momentResistance=6.0)
    found = cs.check(deck, _inputs())
    row = next(
        r for r in found["checks"] if r["name"].endswith("longitudinal shear (partial connection)")
    )
    assert 0 < row["capacity"] and row["demand"] > 0


def test_apply_keeps_the_concrete_rows_as_advisories(ec):
    entry = {
        "id": "S1",
        "checks": [{"name": "Flexure", "utilisation": 3.0, "ok": False, "flag": False, "note": ""}],
    }
    notes: list[str] = []
    cs.apply(entry, CompositeSlabDeck(m=150.0, k=0.05, momentResistance=6.0), _inputs(), notes)
    assert entry["checks"][0]["flag"]
    assert "compositeSlab" in entry
    assert entry["utilisation"] == max(c["utilisation"] for c in entry["checks"] if not c["flag"])


def test_the_default_pack_does_not_check_composite_slabs():
    with code_context.using(registry.load("bnbc2020")):
        entry = {"id": "S1", "checks": []}
        notes: list[str] = []
        cs.apply(entry, CompositeSlabDeck(), _inputs(), notes)
    assert "compositeSlab" not in entry and "does not cover" in notes[0]


# ─────────────────────────────────────── composite beams ───────────────────────────────────────


def _solid(**kw) -> CompositeBeam:
    return CompositeBeam(concrete="C30", slabThickness=150, deck=None, **kw)


def test_longitudinal_shear_planes_en_1994_6_6_6(ec):
    table = cp.composite_table()
    bars = SlabTransverseBars(top=300, bottom=300, fy=500)
    beam = _solid(connectors=ShearConnectors(diameter=19, height=100), transverseBars=bars)
    geom = cp.beam_geometry(W450, 355, 210000, beam, 8000, table)
    concrete = cp.Concrete(30, 30, 2400, cp.concrete_modulus(30, 2400, table), False)
    conn = cp._connectors(beam, concrete, table)
    notes: list[str] = []
    rows = cp.longitudinal_shear_rows(
        beam, geom, conn, 1500e3, 4000, 8000, concrete, "ULS", table, notes
    )
    names = {r["name"]: r for r in rows}
    fyd = 500 / 1.15
    # a-a: half the force over hf = 150 mm, cot θf = 2 (the struts hold).
    aa = names["Composite: transverse bars, beside the beam (a-a)"]
    v_ed = 750e3 / (150 * 4000)
    assert aa["demand"] == pytest.approx(v_ed * 150 / (fyd * 2) * 1000, abs=0.01)
    assert aa["capacity"] == pytest.approx(600) and aa["ok"]
    struts = names["Composite: longitudinal shear struts, beside the beam (a-a)"]
    nu = 0.6 * (1 - 30 / 250)
    assert struts["capacity"] == pytest.approx(nu * 20 * 2 / 5, abs=0.01)
    # b-b round the studs: all of the force, the bottom bars twice.
    bb = names["Composite: transverse bars, round the studs (b-b)"]
    assert bb["demand"] == pytest.approx(1500e3 / 4000 / (fyd * 2) * 1000, abs=0.01)
    assert bb["capacity"] == pytest.approx(600)


def test_composite_floor_beam_en_1994(ec):
    """A composite floor beam: W450 under a 150 mm solid slab, 8 m, studs designed."""
    table = cp.composite_table()
    beam = _solid(connectors=ShearConnectors(diameter=19, height=100, fu=450))
    flexure = {"name": "Flexure about x (major)", "capacity": 600.0, "note": "", "flag": False}
    found = cp.beam_checks(W450, STEEL, C30, beam, [_beam_stations()], 8.0, flexure, table)
    names = {c["name"]: c for c in found["checks"]}
    assert names["Composite: positive flexure"]["ok"]
    # No transverse bars given: the bars needed are reported (flagged).
    assert names["Composite: transverse bars, beside the beam (a-a)"]["flag"]
    assert "camber" in found["summary"] and found["summary"]["wetDeflection"] > 0


def test_camber_rounding():
    rule = SimpleNamespace(share=0.8, minimum=20, step=5)
    found = cp.camber(40.0, 8000, 210000, 2e8, rule)
    delta = 5 * 40 * 8000**4 / (384 * 210000 * 2e8)
    assert found["wetDeflection"] == pytest.approx(round(delta, 1))
    assert found["camber"] == math.floor(0.8 * delta / 5) * 5
    assert cp.camber(5.0, 8000, 210000, 2e8, rule)["camber"] == 0.0  # below 20 mm


def test_dynamic_stiffening_of_a_composite_beam():
    beam = Beam(
        id="B1",
        name="B1",
        material="S355",
        profile=IShapeProfile(
            overallWidth=200, overallDepth=450, webThickness=9, flangeThickness=14
        ),
        composite=_solid(),
    )
    mats = {"S355": STEEL, "C30": C30}
    table = builtin_table("composite")
    ratio = cp.dynamic_stiffening(beam, mats, 8.0, 1.35, table)
    assert ratio is not None and 0 < ratio < 1
    stiffer = cp.dynamic_stiffening(beam, mats, 8.0, 2.0, table)
    assert stiffer < ratio  # a stiffer concrete: a smaller Is / It
    plain = beam.model_copy(update={"composite": None})
    assert cp.dynamic_stiffening(plain, mats, 8.0, 1.35, table) is None


def test_design_mode_checks_composite_candidates():
    from saengine.design.steel_design import composite_checker
    from saengine.design.steel_proposal import SteelMaterial
    from saengine.library import steel_sections as tbl

    beam = Beam(
        id="B1",
        name="B1",
        material="S355",
        profile=tbl.find("IPE 400").profile(),
        composite=_solid(connectors=ShearConnectors(diameter=19, height=100, fu=450)),
    )
    summaries: dict = {}
    checker = composite_checker(beam, STEEL, {"S355": STEEL, "C30": C30}, ["ULS"], summaries)
    checks = checker(
        [_beam_stations(mu=300e6)],
        tbl.find("IPE 400"),
        SteelMaterial.from_material(STEEL),
        MemberLengths.simple(8.0),
        kind="beam",
    )
    names = {c["name"]: c for c in checks}
    assert "Composite: positive flexure" in names
    assert names["Flexure about x (major)"]["flag"]  # the composite section replaces it
    assert summaries["IPE 400"]["connectors"] > 0


# ─────────────────────────────────────── a CFT column ───────────────────────────────────────


def test_concrete_filled_round_column_example():
    """A CFT column: CHS 406.4 × 10 filled with C30, 4 m, under the default pack (BNBC 2020
    Part 6 Sec 13.2.2: C2 = 0.95 of round filled sections)."""
    t = builtin_table("composite")
    shape = chs(406.4, 10)
    col = CompositeColumn(form="filled", concrete="C30", bars=0)
    s = np.linspace(0, 4.0, 5)
    z = np.zeros_like(s)
    stations = [Stations("1.2D + 1.6L", s, z + 3000e3, z + 100e6, z, z, z, ["C1"] * 5)]
    steel = STEEL.model_copy(update={"steel": STEEL.steel.model_copy(update={"fy": 345})})
    found = cp.column_checks(shape, steel, C30, col, stations, MemberLengths.simple(4.0), False, t)
    ri = 406.4 / 2 - 10
    po = shape.area * 345 + 0.95 * math.pi * ri**2 * 30
    assert found["summary"]["Po"] == pytest.approx(po / 1e3, abs=1)
    names = {c["name"]: c for c in found["checks"]}
    assert names["Composite: compression (flexural buckling)"]["ok"]
    assert "Composite: axial force and flexure (plastic P-M)" in names


# ─────────────────────────────────────── drawings ───────────────────────────────────────


def test_steel_drawings_note_the_studs():
    from saengine.drawings.sheets.steel import composite_notes

    beam = Beam(
        id="CB1",
        name="CB1",
        material="S355",
        profile=IShapeProfile(
            overallWidth=200, overallDepth=450, webThickness=9, flangeThickness=14
        ),
        composite=CompositeBeam(concrete="C30", connectors=ShearConnectors(spacing=300)),
    )
    bim = SimpleNamespace(
        elements=[SimpleNamespace(type="CB1")], additions=SimpleNamespace(members=[])
    )
    notes = composite_notes(bim, SimpleNamespace(objects=[beam]))
    assert len(notes) == 1 and "300 mm centres" in notes[0] and "19 mm × 100 mm" in notes[0]

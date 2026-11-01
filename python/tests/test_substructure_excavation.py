"""Excavations and temporary works (saengine.substructure.excavation): the construction table
of the bnbc2020 pack pinned with its clauses, and the checks that read it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from saengine.codes.tables import builtin_table
from saengine.library.substructure import (
    AdjoiningStructure,
    Excavation,
    ExcavationLoad,
    Formwork,
    Substructure,
)
from saengine.substructure import excavation as ex
from saengine.substructure.earth_pressure import GAMMA_W, Soil

# ─────────────────────────────── the pack's values ───────────────────────────────


def test_excavation_rules_from_the_pack() -> None:
    """BNBC 2020 Part 6 Sec 3.12 (p. 797): 300 mm under a footing, 6 m for a geotechnical
    check; 3.12.2.1 (pp. 798-799): 1.5 m, 1:1, steps 1.5 m, guard rail 1 m (1V:3H exempt);
    3.12.2.2 (p. 799): 1.5 × depth, sheet piles 150 mm above ground; 3.12.1 (p. 797): 10 days;
    3.12.2.3 (p. 799): 48 h notice, 24 h readings; Part 7 Sec 3.3.2 (part 2 p. 658): machinery
    at the depth, at most 6 m; 3.3.10 (part 2 p. 660): escape beyond 1.5 m, 100 lux."""
    r = builtin_table("construction").excavation
    assert (r.underFooting, r.geotechnicalDepth, r.protectionDepth) == (300, 6000, 1500)
    assert (r.slopeHorizontal, r.maxStepHeight) == (1.0, 1500)
    assert (r.guardRailHeight, r.guardRailSlopeExempt) == (1000, 3.0)
    assert (r.surchargeZone, r.sheetPileProjection) == (1.5, 150)
    assert (r.machinerySetback, r.machinerySetbackMax) == (1.0, 6000)
    assert (r.escapeDepth, r.inspectionDepth, r.nightLighting) == (1500, 1500, 100)
    n = r.notices
    assert (n.adjoiningDays, n.operationsHours, n.monitoringHours) == (10, 48, 24)
    assert "3.12" in r.clause


def test_fill_waterproofing_formwork_from_the_pack() -> None:
    """Part 6 Sec 3.15.2-3.15.3 (pp. 801-802): 95% of ASTM D1557, 300 mm lifts, 100 mm
    particles, a test pit per 200 m² to 2 m; Sec 3.17 (pp. 803-806); Part 7 Sec 3.8.2-3.8.5 and
    Table 7.3.1 (part 2 pp. 672-674)."""
    t = builtin_table("construction")
    f = t.fill
    assert (f.compaction, f.maxLift, f.maxParticle, f.testPitArea, f.testPitDepth) == (
        0.95, 300, 100, 200, 2000,
    )  # fmt: skip
    w = t.waterproofing
    assert (w.aboveWaterTable, w.dampAboveGrade, w.membrane, w.lap) == (300, 150, 0.15, 150)
    assert (w.drainBeyond, w.gradingSlope, w.gradingDistance) == (300, 12, 2500)
    fw = t.formwork
    assert (fw.loadFactor, fw.concreteWeight, fw.liveLoad, fw.timberBending) == (
        2.0, 20.0, (1.5, 4.0), 8000,
    )  # fmt: skip
    assert (fw.camber, fw.cantileverCamber, fw.tableSpan, fw.tableHeight) == (250, 50, 5000, 4000)
    assert (fw.posts["bamboo"].minDiameter, fw.posts["bamboo"].maxHeight) == (75, 4000)
    assert (fw.posts["timber"].minDiameter, fw.posts["timber"].topDiameter) == (80, 150)
    assert fw.posts["timber"].maxHeight == 6000
    joist = next(s for s in fw.sizes if s.id == "joist")
    assert (joist.min, joist.max) == ((50, 100), (75, 200))
    assert t.seepage.factorOfSafety is None  # BNBC Sec 3.8.9 gives none


# ─────────────────────────────── excavation checks ───────────────────────────────


def _soil(water: float | None = None) -> Soil:
    return Soil([(0.0, 100.0, 18.0, 20.0, 30.0)], water, source="test")


def _by(checks: list[dict], name: str) -> dict:
    return next(c for c in checks if c["name"].startswith(name))


def test_shallow_excavation_needs_no_protection() -> None:
    """1.2 m deep, vertical, unsupported: below the 1.5 m of Sec 3.12.2.1; a guard rail."""
    e = Excavation(id="E1", bottomLevel=-1200, support="none", guardRail=True)
    checks, _ = ex.excavation_checks(e, 0.0, _soil())
    assert not any(c["name"] == "Unsupported vertical sides" for c in checks)
    assert all(c["ok"] for c in checks if not c["flag"])


def test_deep_vertical_cut_fails_and_slope_rule() -> None:
    """2 m deep: unsupported vertical sides fail; sloped 1 : 0.75 fails, 1 : 1 passes."""
    e = Excavation(id="E1", bottomLevel=-2000, support="none", guardRail=True)
    checks, _ = ex.excavation_checks(e, 0.0, _soil())
    assert not _by(checks, "Unsupported vertical sides")["ok"]
    steep = e.model_copy(update={"support": "sloped", "sideSlope": 0.75})
    assert not _by(ex.excavation_checks(steep, 0.0, _soil())[0], "Side slope")["ok"]
    flat = e.model_copy(update={"support": "sloped", "sideSlope": 1.0})
    assert _by(ex.excavation_checks(flat, 0.0, _soil())[0], "Side slope")["ok"]


def test_stepped_sides_and_guard_rail_exemption() -> None:
    """Steps at most 1.5 m; no guard rail needed at 1V:3H or flatter."""
    e = Excavation(id="E1", bottomLevel=-3000, support="stepped", sideSlope=1.2, stepHeight=1800)
    checks, _ = ex.excavation_checks(e, 0.0, _soil())
    assert not _by(checks, "Step height")["ok"]
    assert not _by(checks, "Guard rail")["ok"]
    flat = e.model_copy(update={"support": "sloped", "sideSlope": 3.0})
    assert _by(ex.excavation_checks(flat, 0.0, _soil())[0], "Guard rail")["ok"]


def test_surcharge_zone_and_machinery_setback() -> None:
    """4 m deep: spoil 5 m away is inside 1.5 × 4 = 6 m (fails beside vertical sides);
    machinery needs 4 m (the depth), capped at 6 m for a 10 m pit."""
    e = Excavation(
        id="E1",
        bottomLevel=-4000,
        support="none",
        guardRail=True,
        loads=[
            ExcavationLoad(kind="spoil", distance=5000),
            ExcavationLoad(kind="machinery", distance=4500),
        ],
    )
    checks, _ = ex.excavation_checks(e, 0.0, _soil())
    spoil = _by(checks, "Surcharge zone: spoil")
    assert spoil["demand"] == pytest.approx(6000) and not spoil["ok"] and not spoil["flag"]
    assert _by(checks, "Machinery setback")["ok"]
    deep = e.model_copy(update={"bottomLevel": -10000})
    setback = _by(ex.excavation_checks(deep, 0.0, _soil())[0], "Machinery setback")
    assert setback["demand"] == pytest.approx(6000) and not setback["ok"]


def test_sheet_piles_above_ground() -> None:
    e = Excavation(
        id="E1", bottomLevel=-3000, support="sheetPiles", sheetPileTop=100, guardRail=True
    )
    assert not _by(ex.excavation_checks(e, 0.0, _soil())[0], "Sheet piles above ground")["ok"]


def test_adjoining_foundation_above_the_bottom_needs_underpinning() -> None:
    """Sec 3.12.1 (i): a foundation at or above the bottom, close by, is underpinned; 300 mm
    under a footing (Sec 3.12); notice of 10 days to another owner."""
    adj = AdjoiningStructure(id="AB1", distance=200, foundingLevel=-1500)
    e = Excavation(id="E1", bottomLevel=-3000, support="sheetPiles", sheetPileTop=200,
                   guardRail=True, adjoining=[adj])  # fmt: skip
    checks, needs = ex.excavation_checks(e, 0.0, _soil())
    assert not _by(checks, "Under the footing of AB1")["ok"]
    assert not _by(checks, "Adjoining AB1 supported")["ok"]
    assert any("10 days" in n for n in needs)
    done = e.model_copy(update={"adjoining": [adj.model_copy(update={"underpinned": True})]})
    checks, _ = ex.excavation_checks(done, 0.0, _soil())
    assert _by(checks, "Adjoining AB1 supported")["ok"]


def test_geotechnical_engineer_beyond_six_metres() -> None:
    e = Excavation(id="E1", bottomLevel=-7000, support="shored", guardRail=True)
    checks, needs = ex.excavation_checks(e, 0.0, _soil())
    flag = _by(checks, "Depth for a geotechnical engineer")
    assert flag["flag"] and flag["capacity"] == pytest.approx(6000)
    assert any("geotechnical engineer" in n for n in needs)


def test_dewatering_below_the_water_table() -> None:
    e = Excavation(id="E1", bottomLevel=-3000, support="shored", guardRail=True)
    checks, needs = ex.excavation_checks(e, 0.0, _soil(water=1.0))
    assert not _by(checks, "Dewatering")["ok"]
    assert any("below the water table" in n for n in needs)
    done = e.model_copy(update={"dewatered": True})
    assert not any(
        c["name"] == "Dewatering" for c in ex.excavation_checks(done, 0.0, _soil(1.0))[0]
    )


def _layered(water: float) -> Soil:
    """Clay to 5 m (γsat 18), sand below: with its report profile."""
    layers = [
        SimpleNamespace(index=0, top=0.0, bottom=5.0, behaviour="cohesive", soil_type="clay",
                        n60=10.0, cu=60.0),
        SimpleNamespace(index=1, top=5.0, bottom=30.0, behaviour="granular", soil_type="sand",
                        n60=20.0, cu=None),
    ]  # fmt: skip
    profile = SimpleNamespace(layers=layers)
    return Soil([(0.0, 5.0, 17.0, 18.0, None, 60.0), (5.0, 30.0, 18.0, 20.0, 32.0, 0.0)],
                water, source="test", profile=profile)  # fmt: skip


def test_base_uplift_of_the_clay_plug() -> None:
    """Clay 4 m to 5 m at the base weighs 18 kPa against γw (5 - 1) = 39.2 kPa: it heaves."""
    found = ex.base_uplift(_layered(1.0), 4.0, 1.0)
    assert found["capacity"] == pytest.approx(18.0, abs=0.01)
    assert found["demand"] == pytest.approx(GAMMA_W * 4.0, abs=0.01)
    assert not found["ok"]
    assert ex.base_uplift(_layered(1.0), 2.0, 1.0)["ok"]  # 3 m of clay: 54 > 39.2


def test_seepage_gradient_round_a_cutoff() -> None:
    """Water at 1 m, base at 4 m, cut-off 3 m below: i = 3 / (3 + 6) = 0.333 against
    icr = (20 - 9.81) / 9.81 = 1.039; reported only."""
    found = ex.seepage_gradient(_soil(1.0), 4.0, 3.0, 1.0)
    assert found["demand"] == pytest.approx(1 / 3, abs=5e-3)  # rounded to 0.01
    assert found["capacity"] == pytest.approx((20 - GAMMA_W) / GAMMA_W, abs=5e-3)
    assert found["flag"]


# ─────────────────────────────── formwork ───────────────────────────────


def test_formwork_loads_and_timber_stress() -> None:
    """Part 7 Sec 3.8.3: w = 2 (20 × 0.15 + 4.0) = 14 kPa; sheeting 25 mm over 500 mm:
    M = 14 × 0.5² / 8 = 0.4375 kN·m/m, σ = 0.4375e6 / (1000 × 25² / 6) = 4.2 MPa < 8 MPa;
    joist 75 × 100 over 900 mm: 7 kN/m, M = 0.709 kN·m, σ = 5.67 MPa."""
    fw = Formwork(joistWidth=75, joistDepth=100, joistSpacing=500, joistSpan=900,
                  postKind="timber", postHeight=3000, postDiameter=100)  # fmt: skip
    checks, _ = ex.formwork_checks(fw, 150)
    assert _by(checks, "Sheeting bending")["demand"] == pytest.approx(4200, rel=1e-3)
    assert _by(checks, "Joist bending")["demand"] == pytest.approx(5670, rel=1e-3)
    assert all(c["ok"] for c in checks)
    heavy = ex.formwork_checks(fw, 150, unit_weight=25.0)[0]
    assert _by(heavy, "Sheeting bending")["demand"] > 4200  # the heavier concrete governs


def test_formwork_posts() -> None:
    """Bamboo posts at most 4 m and 75 mm; timber posts at most 6 m and 80 mm."""
    bamboo = Formwork(postKind="bamboo", postHeight=4500, postDiameter=70)
    checks, _ = ex.formwork_checks(bamboo, 125)
    assert not _by(checks, "Bamboo post height")["ok"]
    assert not _by(checks, "Bamboo post diameter")["ok"]
    timber = Formwork(postKind="timber", postHeight=5000, postDiameter=90)
    checks, needs = ex.formwork_checks(timber, 125)
    assert _by(checks, "Timber post height")["ok"]
    assert any("braced" in n for n in needs)
    assert any("calculation" in n for n in needs)  # 5 m is beyond the table's 4 m


# ─────────────────────────────── model and notes ───────────────────────────────


def test_substructure_round_trip_and_drawing_notes() -> None:
    s = Substructure.model_validate(
        {"excavations": [{"id": "E1", "bottomLevel": -3000, "support": "sheetPiles",
                          "adjoining": [{"id": "AB1", "foundingLevel": -1000}]}],
         "formwork": {"slabThickness": 150}}
    )  # fmt: skip
    assert s.excavations[0].adjoining[0].otherProperty
    notes = ex.construction_notes(s)
    assert any(n.startswith("Excavation:") and "300 mm" in n for n in notes)
    assert any(n.startswith("Formwork:") and "1 in 250" in n for n in notes)
    with pytest.raises(ValueError):
        Substructure.model_validate(
            {"excavations": [{"id": "E1", "bottomLevel": -1}, {"id": "E1", "bottomLevel": -2}]}
        )


def test_in_the_substructure_report() -> None:
    """The excavations and the formwork are designed by the substructure report, without an
    analysis; their requirements reach the notes and the pack's clauses the method."""
    import json

    from test_fem_derive import OBJECTS, PLAN, SETTINGS

    from saengine.library import default_material_library
    from saengine.library.bim import generate
    from saengine.substructure.context import Context
    from saengine.substructure.report import report

    substructure = Substructure.model_validate(
        {"excavations": [{"id": "E1", "bottomLevel": -2500, "support": "none",
                          "adjoining": [{"id": "AB1", "distance": 1000, "foundingLevel": -1200}]}],
         "formwork": {"slabThickness": 150, "postDiameter": 100}}
    )  # fmt: skip
    ctx = Context(
        substructure=substructure,
        building=generate(PLAN, "s"),
        objects=OBJECTS,
        materials=default_material_library(),
        settings=SETTINGS,
    )
    data = report(ctx)
    json.dumps(data)
    (pit,) = data["excavations"]
    assert pit["type"] == "excavation" and not pit["ok"]
    assert pit["sizes"]["depth"] == 2500
    assert data["temporaryWorks"][0]["type"] == "formwork"
    assert any(n.startswith("E1: AB1") for n in data["notes"])
    assert any("3.12" in m for m in data["method"])
    assert data["summary"]["status"] == "fail"

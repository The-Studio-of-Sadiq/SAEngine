"""Alpha 9 P1: staged excavations, embedded wall sections and their supports (value pins and a
two-stage propped cantilever with hand-checkable numbers)."""

from __future__ import annotations

import math
from types import SimpleNamespace as NS
from typing import ClassVar

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.library.materials import Material
from saengine.library.substructure import Excavation
from saengine.substructure import embedded_wall as ew
from saengine.substructure import excavation_support as es
from saengine.substructure.context import Skip
from saengine.substructure.earth_pressure import Soil, kp_coulomb

SAND = Soil([(0.0, 100.0, 18.0, 20.0, 30.0)], None, 0.0)

C30 = Material.model_validate(
    {
        "id": "C30",
        "name": "C30",
        "category": "concrete",
        "mechanical": {"E": 25700, "density": 2400},
        "concrete": {"fc": 30},
    }
)
B420 = Material.model_validate(
    {
        "id": "B420",
        "name": "B420",
        "category": "rebar",
        "mechanical": {"E": 200000, "density": 7850},
        "steel": {"fy": 420, "fu": 550},
    }
)
S355 = Material.model_validate(
    {
        "id": "S355",
        "name": "S355",
        "category": "steel",
        "mechanical": {"E": 200000, "density": 7850},
        "steel": {"fy": 355, "fu": 470},
    }
)


class _Ctx:
    """The parts of :class:`saengine.substructure.context.Context` the design reads."""

    mats: ClassVar[dict[str, Material]] = {"C30": C30, "B420": B420, "S355": S355}

    def concrete(self, material_id: str | None, owner: str) -> Material:
        found = self.mats.get(material_id or "")
        if found is None or found.concrete is None:
            raise Skip("no concrete")
        return found

    def rebar(self, material_id: str) -> Material:
        return self.mats[material_id]


# ─────────────────────────────── the packs ───────────────────────────────


def test_packs_choose_the_methods_by_id() -> None:
    bnbc = registry.load("bnbc2020").table("excavationSupport")
    eu = registry.load("eurocodes").table("excavationSupport")
    us = registry.load("aci318-asce7-22").table("excavationSupport")
    assert bnbc.analysis == "subgradeReaction" and bnbc.subgrade.method == "schmitt"
    assert [a.strengths for a in bnbc.analyses] == ["characteristic"]
    assert bnbc.analyses[0].effectFactor is None  # the pack's 1.6H (Part 6 Sec 2.7.3.1)
    assert [(a.strengths, a.effectFactor) for a in eu.analyses] == [
        ("characteristic", 1.35),
        ("design", 1.0),
    ]
    # BS 8081 (temporary 1.4 / 2.0, permanent 2.0 / 3.0), EN 1997-1 8.5, PTI DC35.1.
    assert (bnbc.anchors.tendonFactor, bnbc.anchors.groundFactor) == (1.4, 2.0)
    assert (bnbc.anchors.permanentTendonFactor, bnbc.anchors.permanentGroundFactor) == (2.0, 3.0)
    assert eu.anchors.groundFactor == pytest.approx(1.35 * 1.1)
    assert us.anchors.tendonFactor == pytest.approx(1 / 0.6, rel=1e-3)
    assert us.anchors.fixedLengthMin == 4.5 and us.anchors.proofFactor == 1.33
    assert (bnbc.heave.pipingFactor, eu.heave.pipingFactor) == (2.0, 1.5)
    assert "SAEngine practice" in bnbc.source


# ─────────────────────────────── pressures and springs ───────────────────────────────


def test_coulomb_passive_with_wall_friction() -> None:
    assert kp_coulomb(30.0, 0.0) == pytest.approx(3.0)
    # cos²30 / (cos 10 (1 - √(sin 40 sin 30 / cos 10))²)
    root = math.sqrt(math.sin(math.radians(40)) * 0.5 / math.cos(math.radians(10)))
    assert kp_coulomb(30.0, 10.0) == pytest.approx(
        0.75 / (math.cos(math.radians(10)) * (1 - root) ** 2)
    )
    assert kp_coulomb(30.0, 10.0) == pytest.approx(4.143, rel=1e-3)


def test_strip_load_boussinesq() -> None:
    # q = 100 kPa from 1 to 3 m from the wall, at the depth 2 m below it: q/π (β - sin β cos 2α).
    t1, t2 = math.atan(1 / 2), math.atan(3 / 2)
    expected = 100 / math.pi * ((t2 - t1) - math.sin(t2 - t1) * math.cos(t1 + t2))
    assert es.strip_pressure(2.0, 100.0, 1.0, 2.0, 0.0) == pytest.approx(expected)
    assert es.strip_pressure(2.0, 100.0, 1.0, 2.0, 0.0) == pytest.approx(14.566, rel=1e-3)
    assert es.strip_pressure(0.5, 100.0, 1.0, 2.0, 1.0) == 0.0  # above the footing


def test_schmitt_subgrade_modulus() -> None:
    rules = registry.load("bnbc2020").table("excavationSupport").subgrade
    soil = Soil([(0.0, 100.0, 18.0, 20.0, 32.0)], None, 0.0)
    # E = 25 MPa at φ' 32°, Eoed = E (1 - ν) / ((1 + ν)(1 - 2ν)), kh = 2.1 Eoed^(4/3) / EI^(1/3).
    oed = 25_000 * 0.7 / (1.3 * 0.4)
    assert es.subgrade(soil, 3.0, 100_000.0, rules) == pytest.approx(
        2.1 * oed ** (4 / 3) / 100_000 ** (1 / 3)
    )


# ─────────────────────────────── the two-stage propped cantilever ───────────────────────────────


def _wall_rules() -> NS:
    return NS(
        method="factoredPassive",
        passiveFactor=1.0,
        materials=None,
        variableFactor=1.0,
        embedmentIncrease=1.0,
        freeEarthIncrease=1.0,
        minimumSurcharge=0.0,
        overdigShare=0.0,
        overdigMax=0.0,
        clauses={},
        source="",
    )


@pytest.fixture
def rankine(monkeypatch: pytest.MonkeyPatch) -> NS:
    """Rankine pressures without wall friction, the least fluid pressure, surcharge or overdig;
    a constant kh of 20 MN/m³; effects × 1."""
    base = registry.load("bnbc2020").table("excavationSupport")
    rules = NS(
        analysis="subgradeReaction",
        analyses=[NS(name="Characteristic", strengths="characteristic", effectFactor=1.0)],
        earthPressure=NS(
            activeMethod="rankine",
            passiveMethod="rankine",
            activeFriction=0.0,
            passiveFriction=0.0,
            minimumFluid=0.0,
            stripLoad="boussinesq",
            stripFactor=1.0,
        ),
        subgrade=base.subgrade.model_copy(
            update={"method": "tabulated", "tabulatedGranular": [(30.0, 20.0)]}
        ),
        struts=base.struts,
        anchors=base.anchors,
        heave=base.heave,
        deflectionShare=0.005,
        clauses={},
        source="",
    )
    monkeypatch.setattr(es, "table", lambda: rules)
    monkeypatch.setattr(ew, "table", _wall_rules)
    return rules


def test_two_stage_propped_cantilever(rankine: NS) -> None:
    """Stage 1 digs 1.5 m as a cantilever; stage 2 places a rigid prop at the top and digs to
    6 m. Sand γ 18 kN/m³, φ' 30° (Ka 1/3, Kp 3), no water; sheet piles to 6 + 1.2 d0."""
    # Free earth support about the prop at the top (hand): Ka L³/3 = Kp ((L³ - H³)/3 -
    # H (L² - H²)/2) with H = 6: (8/9) L³ - 9 L² + 108 = 0, L the wall's length.
    roots = [r.real for r in np.roots([8 / 9, -9, 0, 108]) if abs(r.imag) < 1e-9 and r.real > 6]
    length = min(roots)
    d0 = length - 6.0
    t_free = 18 * (length**2 / 6 - 1.5 * d0**2)  # γ (Ka L²/2 - Kp d²/2)
    z_peak = math.sqrt(2 * t_free / 6.0)  # T = Ka γ z²/2
    m_free = t_free * z_peak - 6.0 * z_peak**3 / 6
    assert (d0, t_free, m_free) == pytest.approx((2.405, 55.75, 160.2), rel=1e-3)
    toe = 6.0 + 1.2 * d0
    ex = Excavation.model_validate(
        {
            "id": "EX1",
            "bottomLevel": -6000,
            "wall": {
                "wallType": "sheetPile",
                "section": "U 600×210×18.0",
                "toeLevel": -toe * 1000,
                "supports": [{"id": "P", "level": 0, "spacing": 1000, "stiffness": 1e7}],
                "stages": [{"digLevel": -1500}, {"digLevel": -6000, "install": ["P"]}],
            },
        }
    )
    found = es.analyse(_Ctx(), ex, 0.0, SAND)
    assert not isinstance(found, str), found
    one, two = found["runs"][0]["stages"]
    z, trib = found["mesh"].z, found["mesh"].trib
    net1 = (one["behind"] - one["front"]) * trib
    net2 = (two["behind"] - two["front"]) * trib
    # Stage 1, a cantilever: the pressures balance (force and moment).
    assert abs(net1.sum()) < 1e-6 and abs((net1 * z).sum()) < 1e-6
    assert one["forces"] == {}
    # Stage 2: the prop takes the net pressure, the moment about it vanishes.
    t = two["forces"]["P"]
    assert t == pytest.approx(net2.sum(), rel=1e-6)
    assert abs((net2 * z).sum()) < 1e-5
    # The prop was placed on the deflected wall: the top stays at stage 1's deflection + T / k.
    assert two["y"][0] == pytest.approx(one["y"][0] + t / 1e7, abs=1e-7)
    # Behind the wall between the prop and the dig the soil is active: Ka γ z.
    i = int(np.argmin(np.abs(z - 3.0)))
    assert two["behind"][i] == pytest.approx(18 * z[i] / 3, rel=1e-6)
    # Within 3 % of free earth support (near the prop the soil stays nearer at rest: more).
    assert t == pytest.approx(t_free, rel=0.03) and t >= t_free * 0.99
    assert -two["M"].min() == pytest.approx(m_free, rel=0.03)
    env = es.envelopes(found)
    assert env["forces"]["P"] == pytest.approx(t)
    assert float(np.max(env["Mpos"])) == pytest.approx(float(np.max(one["M"])))  # stage 1


def test_propped_wall_without_supports_gets_a_rigid_prop(rankine: NS) -> None:
    ex = Excavation.model_validate(
        {
            "id": "EX1",
            "bottomLevel": -6000,
            "wall": {
                "kind": "propped",
                "propLevel": -1000,
                "wallType": "sheetPile",
                "section": "U 600×210×18.0",
                "toeLevel": -10000,
            },
        }
    )
    stages = es.stages_of(ex.wall, 0.0, ex.bottomLevel)
    assert [(s.dig, s.install) for s in stages] == [(1.5, []), (6.0, ["P"])]
    found = es.analyse(_Ctx(), ex, 0.0, SAND)
    assert not isinstance(found, str), found
    assert found["runs"][0]["stages"][-1]["forces"]["P"] > 0


# ─────────────────────────────── the base, anchors, struts ───────────────────────────────


def test_basal_heave_bjerrum_eide() -> None:
    clay = Soil([(0.0, 100.0, 17.0, 17.0, None, 20.0)], None, 0.0)
    ex = Excavation.model_validate(
        {
            "id": "EX1",
            "bottomLevel": -4000,
            "outline": [[0, 0], [20000, 0], [20000, 10000], [0, 10000]],
        }
    )
    found = {"design": 4.0, "length": 9.0, "q": 10.0, "section": NS(water=True)}
    (row,) = es.base_checks(ex, found, clay)
    # Nc = 5 (1 + 0.2 × 4/10)(1 + 0.2 × 10/20) = 5.94; 1.5 (17 × 4 + 10) against Nc cu.
    assert row["capacity"] == pytest.approx(5.94 * 20.0)
    assert row["demand"] == pytest.approx(1.5 * 78.0)


def test_piping_harr_exit_gradient() -> None:
    soil = Soil([(0.0, 100.0, 18.0, 20.0, 30.0)], 2.0, 0.0)
    ex = Excavation.model_validate({"id": "EX1", "bottomLevel": -6000})
    found = {"design": 6.0, "length": 12.0, "q": 10.0, "section": NS(water=True)}
    (row,) = es.base_checks(ex, found, soil)
    # i = Δh / (π d) = 4 / (6 π), × 2.0 against (20 - 9.81) / 9.81.
    assert row["demand"] == pytest.approx(2.0 * 4 / (6 * math.pi), abs=0.005)  # rounded
    assert "0.212" in row["note"]
    assert row["capacity"] == pytest.approx((20 - 9.81) / 9.81, abs=0.005)


def test_anchor_free_length_and_bond() -> None:
    rules = registry.load("bnbc2020").table("excavationSupport")
    theta = math.radians(15)
    # The active wedge from 10 m at 45 - 30/2 = 30° to the anchor at 2 m: x = 8 tan 30 /
    # (1 + tan 15 tan 30) = 4.0 m, + max(0.2 × 10, 1.5) = 2.0 m, along the anchor / cos 15.
    assert es.free_length(2.0, 10.0, theta, SAND, rules) == pytest.approx(6.0 / math.cos(theta))
    assert es.free_length(2.0, 4.0, theta, SAND, rules) == pytest.approx(5.0)  # the least
    # φ' 30°: τ = 150 kPa (between 100 at 28° and 200 at 32°); π D τ L over 5 m, D 150 mm.
    assert es.bond_capacity(SAND, 2.0, theta, 6.0, 5.0, 0.15, rules) == pytest.approx(
        math.pi * 0.15 * 150.0 * 5.0
    )


def test_contiguous_pile_wall_with_strut_and_anchor() -> None:
    soil = Soil([(0.0, 4.0, 18.0, 20.0, 30.0), (4.0, 100.0, 19.0, 20.0, 34.0)], 3.0, 0.0)
    ex = Excavation.model_validate(
        {
            "id": "EX1",
            "bottomLevel": -8000,
            "outline": [[0, 0], [20000, 0], [20000, 12000], [0, 12000]],
            "adjoining": [
                {
                    "id": "AB1",
                    "distance": 2000,
                    "foundingLevel": -1500,
                    "pressure": 150,
                    "width": 2000,
                }
            ],
            "wall": {
                "wallType": "contiguous",
                "material": "C30",
                "pileDiameter": 600,
                "pileSpacing": 700,
                "rebar": "B420",
                "barCount": 10,
                "barDia": 25,
                "linkDia": 10,
                "linkSpacing": 150,
                "toeLevel": -15000,
                "supports": [
                    {
                        "id": "S1",
                        "level": -1500,
                        "spacing": 4000,
                        "section": "CHS 323.9x12.5",
                        "material": "S355",
                        "length": 12000,
                        "waler": "HEB 300",
                    },
                    {
                        "id": "A1",
                        "kind": "anchor",
                        "level": -5000,
                        "spacing": 2500,
                        "inclination": 20,
                        "tendonArea": 600,
                        "tendonStrength": 1860,
                    },
                ],
                "stages": [
                    {"digLevel": -2000},
                    {"digLevel": -5500, "install": ["S1"]},
                    {"digLevel": -8000, "install": ["A1"]},
                ],
            },
        }
    )
    with code_context.using(registry.load("bnbc2020")):
        out = es.support_checks(_Ctx(), ex, 0.0, soil)
    assert out is not None and out["support"] is not None
    names = [c["name"] for c in out["checks"]]
    for name in (
        "Pile wall: bending per pile",
        "Pile wall: shear per pile",
        "S1: design axial force",
        "A1: tendon",
        "A1: fixed length (bond)",
        "Piping at the toe",
        "Wall deflection",
    ):
        assert name in names
    assert any(n.startswith("S1 (CHS 323.9x12.5): Compression") for n in names)
    assert any(n.startswith("S1 waler (HEB 300)") for n in names)
    support = out["support"]
    assert [s["dig"] for s in support["stages"]] == [2.0, 5.5, 8.5]  # + overdig 10 % H, ≤ 0.5 m
    strut = next(s for s in support["supports"] if s["id"] == "S1")
    # α ΔT E A × restraint = 1.2e-5 × 15 × 200 GPa × 12 230 mm² × 0.5 (×1.0).
    from saengine.library.steel_sections import find

    area = find("CHS 323.9x12.5").A
    assert strut["temperature"] == pytest.approx(1.2e-5 * 15 * 200e6 * area * 1e-6 * 0.5, abs=0.1)
    # The design force is 1.6 × the working force per metre × the spacing.
    assert strut["design"] == pytest.approx(1.6 * strut["working"], rel=1e-2)
    # The report's tables: a stage row per stage with a column per support.
    from saengine.report.build import _excavation_support_rows

    (staged,) = _excavation_support_rows([{"id": "EX1", "support": support}])
    assert staged["supportIds"] == ["S1", "A1"]
    assert len(staged["stages"]) == 3 and len(staged["stages"][0]) == 7 + 2
    assert [row[0] for row in staged["supports"]] == ["S1", "A1"]


def test_sheet_pile_wall_in_the_bill() -> None:
    from saengine.boq.quantities import _Bill, _Measure
    from saengine.library.substructure import Substructure

    sub = Substructure.model_validate(
        {
            "excavations": [
                {
                    "id": "EX1",
                    "bottomLevel": -5000,
                    "outline": [[0, 0], [10000, 0], [10000, 10000], [0, 10000]],
                    "wall": {
                        "wallType": "sheetPile",
                        "section": "U 600×210×18.0",
                        "toeLevel": -10000,
                        "supports": [
                            {"id": "A1", "kind": "anchor", "level": -1000, "spacing": 2000,
                             "freeLength": 6000, "fixedLength": 4000},
                        ],
                    },
                }
            ]
        }
    )  # fmt: skip
    measure = _Measure.__new__(_Measure)
    measure.materials, measure.ground_level, measure.notes, measure.bill = {}, 0.0, [], _Bill()
    measure.embedded_wall(sub.excavations[0], None)
    items = {i.description: i.quantity for i in measure.bill.items()}
    # 40 m × 10 m of wall at 176 kg/m²; 20 anchors of 6 + 4 m.
    assert items["Steel sheet piles U 600×210×18.0 (176 kg/m²)"] == pytest.approx(70_400.0)
    assert items["Ground anchors, installed, stressed and tested"] == 20
    assert items["Ground anchors, drilled length (free and fixed)"] == pytest.approx(200.0)


def test_excavation_wall_drawing() -> None:
    from saengine.drawings.sheets.build import DrawingSettings, build_sheets
    from saengine.drawings.sheets.model import DrawingSet
    from saengine.drawings.sheets.project import excavation_wall_detail

    ex = Excavation.model_validate(
        {
            "id": "EX1",
            "bottomLevel": -6000,
            "designWaterTable": 3.0,
            "wall": {
                "wallType": "diaphragm",
                "thickness": 600,
                "toeLevel": -12000,
                "supports": [
                    {"id": "S1", "level": -1000, "section": "CHS 323.9x12.5"},
                    {"id": "A1", "kind": "anchor", "level": -3500, "inclination": 20},
                ],
            },
        }
    )
    detail = excavation_wall_detail(ex, 0.0)
    assert detail is not None and detail.toe == 12000.0
    assert [round(d) for _, d in detail.stages] == [1500, 4000, 6000]
    anchor = detail.supports[1]
    assert (anchor.free, anchor.fixed) == (5000.0, 3000.0)  # the pack's least lengths
    sheets = build_sheets(DrawingSet(excavation_walls=[detail]), DrawingSettings())
    assert len(sheets) == 1

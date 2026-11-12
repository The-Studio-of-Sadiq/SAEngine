"""C2: the ACI 318-19 concrete of the US code pack ``aci318-asce7-22``.

Pins the pack's concrete values with their clauses (VERIFY.md in the pack lists them for checking
against the printed code), the methods it picks where ACI 318-19 differs from the default pack
(Ie of Table 24.2.3.5, the 2019 hooked and headed bar lengths, the grade factor ψg, the special
walls' boundary trigger and design shear, the joint shear of columns that end at the joint), that
the default pack's results stay as they were, and a small generated building designed under the
pack.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design import clauses
from saengine.design import deflection as D
from saengine.design import ductile_joints as dj
from saengine.design import walls as W
from saengine.drawings import detailing as DT

PACK_ID = "aci318-asce7-22"


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


# ───────────────────────────── values with their clauses ─────────────────────────────


def test_pack_covers_concrete(us):
    info = registry.info(PACK_ID)
    assert info.usable and not info.problems
    assert {"concrete", "detailing", "factors", "materials", "designClauses"} <= set(info.covers)
    assert us.basis["concrete"] == "ACI 318-19"


def test_phi_by_table_21_2(us):
    phi = us.table("factors").phi
    assert (phi.tension, phi.compressionTied, phi.compressionSpiral, phi.shear) == (
        0.9, 0.65, 0.75, 0.75
    )  # fmt: skip
    assert (phi.shearSeismic, phi.joint, phi.diagonalCoupling) == (0.6, 0.85, 0.85)


def test_shrinkage_steel_is_0_0018_for_every_grade(us):
    from saengine.design.rc_detailing import shrinkage_ratio

    for fy in (280.0, 420.0, 550.0):
        assert shrinkage_ratio(fy)[0] == pytest.approx(0.0018)  # Table 24.4.3.2


def test_bars_and_detailing_values(us):
    c, d = us.table("concrete"), us.table("detailing")
    assert c.barDiameters["all"][:3] == [10.0, 13.0, 16.0]  # No. 10, 13, 16
    assert c.slabStrainMin == 0.005  # 7.3.3.1: tension-controlled slabs
    assert d.bars.laps.noLapDb == 43.0  # 25.5.1.1: no laps of bars above No. 36
    assert d.bars.bends.steps[1] == (36.0, 8.0)  # Table 25.3.1
    assert d.walls.driftMin == 0.005 and d.walls.driftFactor == 1.5  # 18.10.6.2
    assert d.special.fytConfinementMax == 689.5  # Table 20.2.2.4(a): 100,000 psi (R4AC-4)
    assert us.table("materials").seismicRebarFyMax == 551.6  # 20.2.2.5: Grade 80 (R4AC-4)
    assert us.table("foundations").strutAndTie.betaOther == 0.4  # Table 23.4.3(a)


def test_clauses_name_the_code_they_come_from(us):
    assert clauses.clause("walls", "boundary") == "ACI 318-19 18.10.6"
    assert clauses.clause("check", "omega") == "ASCE 7-22 Sec 12.4.3"
    # Walk 4: the two-way slab coefficients are the ACI 318-63 Method 3 ones (SAEngine practice).
    assert clauses.clause("slab", "twoWayMethod").startswith("ACI 318-63 Method 3")
    assert clauses.short_clause("slab", "oneWaySpans") == "ACI 318 6.5.1(d)"
    assert code_context.cite("concrete", "shrinkage").startswith("ACI 318-19 24.4.3.2")
    assert code_context.cite("citations", "barDevelopmentHooked").startswith("ACI 318-19 25.4.3.1")
    # C3: steel members are AISC 360-22's.
    assert clauses.clause("steelMembers", "flexureYield") == "AISC 360-22 Sec F2.1, Eq F2-1"


# ───────────────────────────── methods ─────────────────────────────


def test_effective_inertia_table_24_2_3_5(us):
    ig, icr, mcr = 2.0e9, 0.6e9, 20e6
    assert D.inertia_method() == "bischoff"
    # Ig up to (2/3) Mcr, then Icr / (1 - ((2/3) Mcr / Ma)² (1 - Icr/Ig)).
    assert D.effective_inertia(13e6, mcr, ig, icr) == ig
    ma = 30e6
    expected = icr / (1 - (2 / 3 * mcr / ma) ** 2 * (1 - icr / ig))
    assert D.effective_inertia(ma, mcr, ig, icr) == pytest.approx(expected)
    assert D.row_clause("limits") == "Table 24.2.2"


def test_hooked_and_headed_bars_25_4_3_and_25_4_4(us):
    # ldh = fy ψe ψr ψo ψc db^1.5 / (23 λ √f'c), ψr 1.6, ψo 1.25, ψc = f'c/105 + 0.6.
    psi_c = 28 / 105 + 0.6
    ldh = 420 * 1.6 * 1.25 * psi_c * 20**1.5 / (23 * math.sqrt(28))
    assert DT.hook_development(20, 420, 28).value == pytest.approx(ldh)
    assert dj.hooked_development(20, 420, 28) == pytest.approx(ldh)  # foundations, proposal
    confined = DT.hook_development(20, 420, 28, cover=True, confined=True).value
    assert confined == pytest.approx(ldh / (1.6 * 1.25))
    ldt = 420 * 1.6 * 1.25 * psi_c * 20**1.5 / (31 * math.sqrt(28))
    assert DT.headed_development(20, 420, 28).value == pytest.approx(ldt)


def test_grade_factor_25_4_2_5(us):
    base = DT.development_tension(20, 420, 28).value
    high = DT.development_tension(20, 550, 28).value
    assert high == pytest.approx(base * 550 / 420 * 1.15)
    assert DT.psi_g(690) == 1.3


def test_special_walls_18_10(us):
    # Boundary trigger c >= lw / (600 × 1.5 × max(δu/hw, 0.005)).
    assert W.displacement_trigger(6000, 0.002) == pytest.approx(6000 / (600 * 1.5 * 0.005))
    g = W.WallGeometry(length=4000, thickness=250, height=30000, clear_height=3000)
    factor, how = W.shear_amplification(g)
    assert factor == pytest.approx(1.5 * min(1.3 + 10 / 30, 1.8))  # Ωv 1.5, ωv for ns = 10
    assert "18.10.3.3" in how
    assert W.two_curtains_by_aspect(g)
    squat = W.WallGeometry(length=6000, thickness=250, height=6000, clear_height=3000)
    assert W.shear_amplification(squat)[0] == 1.0


def test_joint_of_a_column_ending_at_the_roof(us):
    assert dj._gamma(4) == 1.7 and dj._gamma(4, continuous=False) == 1.2
    assert dj._gamma("other", continuous=False) == 0.7


def test_default_pack_is_unchanged(bnbc):
    assert D.inertia_method() == "cubic"
    assert D.effective_inertia(30e6, 20e6, 2e9, 0.6e9) == pytest.approx(
        (2 / 3) ** 3 * 2e9 + (1 - (2 / 3) ** 3) * 0.6e9
    )
    assert DT.hook_development(20, 420, 28).value == pytest.approx(0.24 * 420 * 20 / math.sqrt(28))
    assert "ψg" not in DT.development_tension(20, 420, 28).formula
    assert W.displacement_trigger(6000, 0.002) == pytest.approx(6000 / (600 * 0.007))
    assert W.trigger_text() == "600 max(δu/hw, 0.007)"
    g = W.WallGeometry(length=4000, thickness=250, height=30000, clear_height=3000)
    assert W.shear_amplification(g) == (1.0, "") and not W.two_curtains_by_aspect(g)
    assert dj._gamma(4, continuous=False) == 1.7
    with pytest.raises(DT.NotCovered):
        DT.headed_development(20, 420, 28)


# ───────────────────────────── a small building ─────────────────────────────


def test_generated_building_is_designed_under_the_pack(tmp_path):
    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    wizard = {
        "schema": "saengine.newBuilding/1",
        "name": "US Concrete",
        "spacings": {"x": [5000], "y": [4000]},
        "stories": [
            {"id": "BASE", "name": "Base", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3000},
        ],
        "storyHeights": [3000],
        "system": "rcFrame",
        "footing": "isolated",
        "site": {
            "siteClass": "SD",
            "siteClassSource": "assumed",
            "spectral": {"sds": 0.5, "sd1": 0.3, "s1": 0.3, "tl": 8},
            "windSpeed": 45,
        },
        "occupancy": {"use": "office", "category": "II"},
        "designCode": PACK_ID,
    }
    root = Path(create_building(wizard, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    with code_context.project(root):
        proposal = handlers.design_proposal(
            str(root / "08 FEM/model.results"), str(root / "08 FEM/model.osmodel")
        )
    objects_path, bim_path = root / "04 Objects/objects.json", root / "06 BIM/bim.json"
    applied = handlers.design_apply_proposal(
        objects_path.read_text(encoding="utf-8"), bim_path.read_text(encoding="utf-8"), proposal
    )
    objects_path.write_text(applied["objectsText"], encoding="utf-8")
    bim_path.write_text(applied["bimText"], encoding="utf-8")
    result = run_all(root, steps=["derive", "analysis", "design"])
    assert result.steps[-1].status in ("ok", "warning"), [s.message for s in result.steps]
    texts = " ".join(
        p.read_text(encoding="utf-8") for p in (root / "08 FEM/model.results").glob("design*.json")
    )
    assert "ACI 318-19" in texts
    report = json.loads(
        (root / "08 FEM/model.results/design-report.json").read_text(encoding="utf-8")
    )["result"]
    names = {c["name"] for e in report["elements"] for c in e.get("checks", [])}
    assert names, "no design checks"
    assert not any("Table 6.6.2" in n for n in names)

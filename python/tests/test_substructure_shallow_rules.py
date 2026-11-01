"""The default code pack's rules of shallow foundations (track B5): every value pinned with its
clause of BNBC 2020 Part 6 Chapter 3, read through the pack (``foundations.shallow``,
``foundations.retainingWall``) and the generic engine of
:mod:`saengine.substructure.shallow_rules`."""

from __future__ import annotations

import math

import pytest

from saengine.codes.tables import builtin_table
from saengine.library.soil import SoilReport
from saengine.soil.profile import Profile
from saengine.soil.settlement import permissible, settlement
from saengine.substructure import shallow_rules as R

PACK = builtin_table("foundations")
SHALLOW = PACK.shallow


def by_name(rows):
    return {name: factors for name, factors in rows}


# ─────────────────────────────────────────── pack values ───────────────────────────────────


def test_pack_values_and_clauses():
    # Sec 3.9.3 / 3.9.3.2 (p. 728): 33% with wind or earthquake; FS 2.0-3.0.
    assert SHALLOW.lateralIncrease == 1.33
    assert tuple(SHALLOW.factorOfSafety) == (2.0, 3.0)
    # Sec 3.9.1 (p. 727): B/6; Sec 3.14 (pp. 800-801): 1.5, 1.5, friction 0.5.
    assert SHALLOW.kern == pytest.approx(1 / 6)
    assert (SHALLOW.overturning, SHALLOW.sliding, SHALLOW.friction) == (1.5, 1.5, 0.5)
    # Sec 3.8.2(d), 3.8.6, 3.8.10 (pp. 723-726).
    assert SHALLOW.minDepth == 500
    assert dict(SHALLOW.exteriorDepth) == {"cohesive": 1500, "granular": 2000, "temporary": 400}
    assert dict(SHALLOW.raftDepth) == {"cohesive": 1500, "granular": 2000}
    # Sec 3.8.2 / 3.18: 2B from a slope face; spread angles read on the PDF page (p. 723).
    assert SHALLOW.slopeDistance == 2.0
    assert SHALLOW.spreadAngle["masonry"] == 0.5
    assert SHALLOW.spreadAngle["limeConcrete"] == pytest.approx(2 / 3)
    assert SHALLOW.spreadAngle["cementConcrete"] == 1.0
    assert dict(SHALLOW.stepLap) == {"thickness": 1.0, "stepHeight": 3.0}
    # Sec 3.8.3 (p. 724) and 6.8.7 (p. 978).
    assert dict(SHALLOW.minThickness) == {
        "soil": 150,
        "piles": 300,
        "plainConcrete": 200,
        "masonry": 250,
    }
    # Sec 3.9.4.7(d) (p. 732).
    assert dict(SHALLOW.settlementGuide) == {"sand": 25, "clay": 40, "differential": 20}
    # Sec 6.3.14, 6.2.3.2.5, 6.8.8.2.1, 3.9.6.8(iii).
    base = SHALLOW.columnBase
    assert (base.phi, base.bearing, base.areaRatioMax, base.dowelRatio, base.minBars) == (
        0.65,
        0.85,
        2.0,
        0.005,
        4,
    )
    for key in ("lateralIncrease", "columnBase", "exteriorDepth", "presumptive", "subgrade"):
        assert "BNBC 2020 Part 6" in PACK.sources[f"shallow.{key}"]


def test_table_6_3_7_presumptive_values():
    rows = {r.id: r for r in SHALLOW.presumptive}
    assert [rows[k].qa for k in ("softRock", "gravel", "sand", "fineSand", "silt", "clay")] == [
        440,
        400,
        200,
        100,
        150,
        150,
    ]
    assert rows["softClay"].qa == 100 and rows["verySoftClay"].qa == 50
    assert rows["organic"].qa is None and rows["fill"].qa is None
    # Note **: 50% near water for rows 2-4 only.
    assert [k for k, r in rows.items() if r.waterReduction] == ["gravel", "sand", "fineSand"]
    assert SHALLOW.presumptiveWaterReduction == 0.5


def test_presumptive_bearing_with_the_water_rule():
    assert R.presumptive("sand", 3000, 1500)[0] == 200  # water deeper than B
    assert R.presumptive("sand", 1000, 1500)[0] == 100  # within B
    assert R.presumptive("sand", -200, 1500)[0] == 100  # above the base
    assert R.presumptive("sand", None, 1500)[0] == 100  # not known: the safe side
    assert R.presumptive("clay", -500, 1500)[0] == 150  # no ** on clay
    with pytest.raises(ValueError, match="investigation"):
        R.presumptive("organic", None, 1000)


def test_tables_6_3_9_subgrade_modulus():
    low, high, note = R.subgrade_modulus("granular", 20)
    assert (low, high) == (15000, 47000) and "31000" in note  # medium, interpolated in N
    assert R.subgrade_modulus("granular", 40, submerged=True)[:2] == (29000, 108000)
    assert R.subgrade_modulus("granular", 5)[:2] == (15000, 15000)
    assert R.subgrade_modulus("cohesive", 300)[:2] == (27000, 54000)
    assert R.subgrade_modulus("cohesive", 500)[:2] == (54000, 108000)
    assert R.subgrade_modulus("cohesive", 50) is None  # softer than stiff: not in the table


def test_table_6_3_8_every_row():
    limit, _ = R.settlement_limit("rcc", "raft", "sand")
    assert (limit.total, limit.differential, limit.angular) == (75, 0.0021, pytest.approx(1 / 500))
    limit, _ = R.settlement_limit("framed", "isolated", "plasticClay")
    assert (limit.total, limit.differential) == (75, 0.002)
    limit, _ = R.settlement_limit("steel", "isolated", "sand")
    assert (limit.total, limit.differential, limit.angular) == (50, 0.0033, pytest.approx(1 / 300))
    limit, _ = R.settlement_limit("waterTank", "raft", "plasticClay")
    assert (limit.total, limit.angular) == (125, pytest.approx(1 / 400))
    # Load bearing walls: L/H = 2 and 7, interpolated between (the table's note *).
    limit, _ = R.settlement_limit("loadBearingWalls", "isolated", "sand", 2.0)
    assert limit.differential == pytest.approx(0.0002)
    limit, _ = R.settlement_limit("loadBearingWalls", "isolated", "sand", 4.5)
    assert limit.differential == pytest.approx(0.0003)
    assert limit.angular == pytest.approx((1 / 5000 + 1 / 2500) / 2)
    assert R.settlement_limit("loadBearingWalls", "raft", "sand", 4.5) is None  # not given


def test_permissible_settlement_shown_with_the_soil_report_reads_the_pack():
    assert permissible("isolated", "sand")["value"] == 50
    assert permissible("isolated", "sand")["framedBuilding"] == 60
    assert permissible("raft", "plasticClay")["framedBuilding"] == 125
    assert "Table 6.3.8" in permissible("raft", "sand")["source"]


# ─────────────────────────────────────────── combinations ──────────────────────────────────


def test_sec_3_9_2_combinations():
    cases = {"D", "SD", "L", "Lr", "EX", "EY"}
    combos = R.footing_combinations(cases)
    bearing = by_name(combos.bearing)
    assert bearing["D + L"] == {"D": 1.0, "SD": 1.0, "L": 1.0, "Lr": 1.0}
    # (ii) with the seismic load at 1.0 as printed, ±X and ±Y.
    assert bearing["D + L + EX"]["EX"] == 1.0 and bearing["D + L + -EY"]["EY"] == -1.0
    # (iii) 0.9 D + buoyancy: B applied by the footing's design, not a case.
    assert bearing["0.9D + B"] == {"D": 0.9, "SD": 0.9}
    assert combos.buoyancy == {"0.9D + B": 1.0}
    # Sec 3.14: stability with the dead load only.
    stability = by_name(combos.stability)
    assert stability["D + EX"] == {"D": 1.0, "SD": 1.0, "EX": 1.0}
    # Sec 3.9.2(b): sand D + L, clay D + 0.5 L.
    assert combos.settlement["cohesive"][1] == {"D": 1.0, "SD": 1.0, "L": 0.5, "Lr": 0.5}
    assert combos.settlement["granular"][1]["L"] == 1.0


def test_lateral_increase_only_with_wind_or_earthquake():
    assert R.allowed(150.0, "D + L")[0] == 150.0
    assert R.allowed(150.0, "D + L + EX")[0] == pytest.approx(199.5)
    assert R.allowed(150.0, "D + L + -WY [Case 2]")[0] == pytest.approx(199.5)
    assert R.allowed(150.0, "0.9D + B")[0] == 150.0


# ─────────────────────────────────────────── checks ────────────────────────────────────────


def test_overturning_and_sliding_of_a_footing():
    ok = R.overturning_check("D + EX", 500.0, 0.0, 2000.0, 2000.0)
    assert ok["capacity"] == pytest.approx(2.0) and ok["ok"]  # B / 2e = 2000 / 1000
    bad = R.overturning_check("D + EX", 800.0, 0.0, 2000.0, 2000.0)
    assert bad["capacity"] == pytest.approx(1.25) and not bad["ok"]
    slide = R.sliding_check("D + EX", 100e3, 250e3, False, None)
    assert slide["capacity"] == pytest.approx(1.25) and not slide["ok"]  # 0.5 × 250 / 100
    tied = R.sliding_check("D + EX", 100e3, 250e3, True, None)
    assert tied["flag"]
    kern = R.kern_check("D + L", 400.0, 0.0, 2000.0, 2000.0)
    assert kern["flag"] and not kern["ok"]  # 0.2 > 1/6: reported only


def test_founding_depth_and_thickness():
    rows = {c["name"]: c for c in R.depth_check("F1", 1500.0, True, "cohesive")}
    assert rows["Founding depth"]["ok"] and rows["Exterior footing depth"]["ok"]
    rows = {c["name"]: c for c in R.depth_check("F1", 1500.0, True, "granular")}
    assert not rows["Exterior footing depth"]["ok"]
    assert rows["Exterior footing depth"]["demand"] == 2000
    rows = {c["name"]: c for c in R.depth_check("F1", 450.0, True, None, temporary=True)}
    assert not rows["Founding depth"]["ok"] and rows["Exterior footing depth"]["ok"]
    assert len(R.depth_check("F1", 800.0, False, "granular")) == 1  # interior: 500 mm only
    rows = {c["name"]: c for c in R.depth_check("R1", 1600.0, False, "cohesive", raft=True)}
    assert rows["Raft depth"]["ok"]
    assert R.thickness_check("F1", 150.0)["ok"] and not R.thickness_check("F1", 149.0)["ok"]
    assert not R.thickness_check("PC1", 250.0, on_piles=True)["ok"]
    assert not R.slope_check(1500.0, 2900.0)["ok"] and R.slope_check(1500.0, 3000.0)["ok"]


def test_column_base_bearing_and_dowels_by_hand():
    rows = R.column_base_checks(
        "C1", 3000e3, 400.0, 400.0, 30.0, 25.0, 2000.0**2, None, None, 420.0, "1.2D + 1.6L"
    )
    bearing = rows[0]
    # Column: 0.65 × 0.85 × 30 × 400² = 2652 kN; footing √(A2/A1) at most 2: 4420 kN.
    assert bearing["capacity"] == pytest.approx(2652.0)
    dowels = rows[1]
    excess = (3000e3 - 2652e3) / (0.65 * 420)
    assert dowels["demand"] == pytest.approx(max(0.005 * 400**2, excess), rel=1e-3)
    rows = R.column_base_checks(
        "C1", 1000e3, 400.0, 400.0, 30.0, 25.0, 2000.0**2, 8 * 314.16, 8, 420.0, "c"
    )
    assert rows[1]["demand"] == pytest.approx(800.0) and rows[1]["ok"]
    rows = R.column_base_checks(
        "C1", 1000e3, 400.0, 400.0, 30.0, 25.0, 2000.0**2, 3 * 490.9, 3, 420.0, "c"
    )
    assert not rows[1]["ok"]  # fewer than 4 bars


# ─────────────────────────────────────────── retaining walls ───────────────────────────────


def test_retaining_wall_factors_follow_sec_3_14_and_3_16():
    f = PACK.retainingWall
    assert (f.sliding, f.overturning, f.seismic) == (1.5, 1.5, 1.5)
    assert f.frictionCoefficient == 0.5  # Sec 3.14(iii)
    assert f.passive == 1.0  # counted only where the soil cannot be removed, Sec 3.14(i)
    assert (f.flotation, f.flotationDead) == (1.0, 0.9)  # Sec 3.9.2(a)(iii)
    assert "IBC" not in " ".join(PACK.sources.values())
    assert "3.9.2(a)(iii)" in PACK.sources["retainingWall.flotation"]


# ─────────────────────────────────────────── secondary consolidation ───────────────────────


def _clay(calpha: float | None) -> Profile:
    layer = {"top": 0, "bottom": 20000, "soilType": "clay", "cu": 40, "Cc": 0.3, "e0": 1.0}
    if calpha is not None:
        layer["Calpha"] = calpha
    report = SoilReport.model_validate({"boreholes": [{"id": "BH", "layers": [layer]}]})
    return Profile(report, report.boreholes[0])


def test_secondary_consolidation_sec_3_9_4_5():
    plain = settlement(_clay(None), 2.0, 2.0, 1.0, 100.0)
    assert plain["secondary"] == 0.0
    found = settlement(_clay(0.02), 2.0, 2.0, 1.0, 100.0)
    h = found["depth"] / 1e3
    expected = 0.02 / (1 + 1.0) * h * math.log10(50 / 1) * 1e3
    assert found["secondary"] == pytest.approx(expected, rel=1e-6)
    assert found["total"] == pytest.approx(plain["total"] + expected, rel=1e-6)


# ─────────────────────────────────────────── a footing under the rules ─────────────────────


def test_a_strip_footing_under_the_pack_rules():
    from test_substructure_shallow import wall_strip

    from saengine.substructure.shallow import design_shallow

    ctx = wall_strip(0.0)
    result, _ = design_shallow(ctx, ctx.substructure.foundations[0])
    checks = {c["name"]: c for c in result["checks"]}
    # Sec 3.9.2(a)(i): D + L (the model has D only) against qa (no lateral increase).
    bearing = checks["Bearing (service)"]
    assert bearing["combination"] == "D + L" and bearing["capacity"] == 300
    # Founded 1.5 m below the finished ground at 0: 500 mm passes; a wall's strip is an
    # exterior footing, and without a soil report the cohesionless 2 m governs (Sec 3.8.6).
    assert checks["Founding depth"]["ok"]
    assert checks["Exterior footing depth"]["demand"] == 2000
    assert not checks["Exterior footing depth"]["ok"]
    # Sec 3.8.3: 400 - 75 - 12 - 12 = 301 mm above the bottom bars >= 150.
    assert checks["Depth above the bottom bars"]["capacity"] == pytest.approx(301)
    assert "Base in contact (service, stability)" not in checks

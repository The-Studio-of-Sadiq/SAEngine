"""Gravity live loads and load combinations from the code pack (track B1).

Every value is pinned through the bnbc2020 pack with its clause; the engine reads them from the
pack (``areaLoads``, ``liveReduction``, ``combinations``)."""

from __future__ import annotations

import pytest

from saengine.codes.tables import builtin_table
from saengine.design import live_reduction as lr
from saengine.fem import architecture_loads as al
from saengine.fem import combinations as fc
from saengine.library.settings import LoadCombination, default_project_settings


def test_table_6_2_3_corrected_values():
    uses = builtin_table("areaLoads").uses
    # BNBC 2020 Part 6 Table 6.2.3 (pp. 534, 536): 2.00 kN/m², not 1.9.
    assert uses["classroom"].live == 2.0
    assert uses["hospitalWard"].live == 2.0
    assert uses["parking"].live == 2.0
    # Concentrated column (pp. 533-537) and notes b, k, l.
    assert uses["office"].concentrated == 9.0
    assert uses["classroom"].concentrated == 4.5
    assert uses["parking"].concentrated == 13.35 and uses["parking"].patch == 114
    assert uses["driveway"].live == 12.0 and uses["driveway"].concentrated == 35.6
    assert uses["manufacturingHeavy"].concentrated == 13.4
    assert uses["garmentsStorage"].concentrated == 10.0
    assert uses["stairs"].concentrated == 1.33
    assert uses["awningFabric"].live == 0.24 and not uses["awningFabric"].reducible
    assert uses["libraryStacks"].live == 7.2
    assert builtin_table("areaLoads").concentratedPatch == 300  # Sec 2.3.5


def test_vehicle_partition_barrier_and_impact_loads():
    table = builtin_table("areaLoads")
    # Sec 2.3.5 (p. 533) and Table 6.2.3 note b (p. 537).
    assert table.vehicles.wheel == 9.0 and table.vehicles.jack == 13.35
    assert table.vehicles.vehicleShare == 0.4 and table.vehicles.patch == 750
    assert table.vehicles.spacing == 1.5 and table.vehicles.mechanicalWheel == 10.0
    # Sec 2.3.6 (p. 538): 33 % of the weight per metre run, at least 1.2 kN/m², up to 5.5 kN/m.
    assert (table.partitions.share, table.partitions.minimum, table.partitions.lightMax) == (
        0.33,
        1.2,
        5.5,
    )
    assert al.partition_rule()[:2] == (0.33, 5.5)
    # Table 6.2.5 (pp. 540-541): vehicle barriers 100 / 165 kN.
    rows = {r.id: r for r in table.barriers.rows}
    assert rows["B.a"].load == 100 and rows["B.b"].load == 165
    assert rows["A.b.iv"].load == 3.0 and table.barriers.bumperHeight == 375
    # Table 6.2.6 rows 1-4 (p. 541).
    impact = {r.id: r.vertical for r in table.impact}
    assert impact == {"1": 1.0, "2": 0.2, "3": 0.5, "4": 0.33}
    # Table 6.2.4 (p. 539): 1.0 / 0.8 / 0.6 / 0.5 kN/m², 0.9 kN.
    roof = {r.id: r for r in table.roofLive}
    assert [roof[k].live for k in ("II", "III", "IV", "V")] == [1.0, 0.8, 0.6, 0.5]
    assert all(roof[k].concentrated == 0.9 for k in ("II", "III", "IV", "V"))


def test_floor_live_reduction():
    table = builtin_table("liveReduction")
    # Sec 2.3.13.2 (p. 543): 4.80 kN/m², not 4.79.
    assert table.heavyLive == 4.8
    # Eq 6.2.1 (p. 542): L = L0 (0.25 + 4.57 / √(KLL AT)).
    factor, _ = lr.reduction(4, 100, 3, lr.LiveScope(live=2.0))
    assert factor == pytest.approx(0.25 + 4.57 / 20)
    # Sec 2.3.13.4(b): no reduction for cyclone shelters.
    assert lr.reduction(4, 400, 3, lr.LiveScope(live=2.0, building="cycloneShelter"))[0] == 1.0
    settings = default_project_settings()
    settings.occupancy.cycloneShelter = True
    assert lr.LiveScope.of(settings).building == "cycloneShelter"
    # Sec 2.3.13.4(a): assembly up to 4.80 not reduced; above it the heavy rule.
    settings = default_project_settings()
    settings.areaLoads[0].use = "stageFloor"
    settings.areaLoads[0].live = 7.2
    scope = lr.LiveScope.of(settings)
    assert scope.heavy and not scope.assembly


def test_roof_live_reduction():
    # Sec 2.3.14.1, Eq 6.2.2 (pp. 543-544): R1 = 1.2 − 0.011 AT, R2 = 1.2 − 0.05 F,
    # 0.60 ≤ Lr ≤ 1.00.
    assert lr.roof_reduction(18.0, 1.0)[0] == 1.0
    assert lr.roof_reduction(30.0, 1.0)[0] == pytest.approx(1.2 - 0.011 * 30)
    assert lr.roof_reduction(60.0, 1.0)[0] == pytest.approx(0.6)
    # F = 0.12 × 50 % = 6: R2 = 0.9; with R1 0.6 the 0.54 is raised to 0.60.
    assert lr.roof_reduction(60.0, 1.0, slope=50)[0] == pytest.approx(0.6)
    assert lr.roof_reduction(30.0, 1.0, slope=50)[0] == pytest.approx(0.87 * 0.9)


def test_strength_combinations_carry_f_h_and_their_clauses():
    rows = {r.id: r for r in builtin_table("combinations").strength}
    # Sec 2.7.3.1 (p. 685): 1.4(D + F), 1.2(D + F + T) + 1.6(L + H) + 0.5(Lr or R),
    # 0.9D + 1.6W + 1.6H, 0.9D + 1.0E + 1.6H.
    assert rows["1"].factors == {"D": 1.4, "F": 1.4}
    assert rows["2"].factors["H"] == 1.6 and rows["2"].factors["F"] == 1.2
    assert rows["6"].factors == {"D": 0.9, "W": 1.6, "H": 1.6}
    assert rows["7"].factors == {"D": 0.9, "E": 1.0, "H": 1.6}
    # 1.2F in the other 1.2D combinations is labelled as SAEngine practice.
    assert "SAEngine practice, not BNBC" in rows["4"].note
    assert all(r.source for r in rows.values())


def test_allowable_stress_combinations_sec_2_7_2_1():
    table = builtin_table("combinations")
    rows = {r.id: r.factors for r in table.allowable}
    assert set(rows) == {"1", "2", "3", "4", "5W", "5E", "6W", "6E", "7", "8"}
    assert rows["1"] == {"D": 1.0, "F": 1.0}
    assert rows["2"] == {"D": 1.0, "H": 1.0, "F": 1.0, "L": 1.0, "T": 1.0}
    assert rows["4"] == {"D": 1.0, "H": 1.0, "F": 1.0, "L": 0.75, "T": 0.75, "Lr": 1.0}
    assert rows["6E"]["E"] == 0.525 and rows["6E"]["Lr"] == 0.75  # the Lr term is back
    assert rows["7"] == {"D": 0.6, "W": 1.0, "H": 1.0}
    assert rows["8"] == {"D": 0.6, "E": 0.7, "H": 1.0}
    assert "2.7.2.1" in table.sources["allowable"] and "2.7.3.2" not in table.sources["allowable"]
    formed = dict(fc.allowable_combinations({"D", "SD", "L", "Lr", "T", "H", "WX", "WY"}))
    assert formed["D + L + 1.0T"] == {"D": 1.0, "SD": 1.0, "H": 1.0, "L": 1.0, "T": 1.0}
    assert formed["D + L − 1.0T"]["T"] == -1.0
    # E is not optional: its rows are formed and left to the caller when it has no results.
    assert formed["0.6D + 0.7EX"] == {"D": 0.6, "SD": 0.6, "EX": 0.7, "H": 1.0}
    # Sec 2.5.13.5 (p. 647): 1.2 with Em in combinations 5, 6 and 8 only.
    assert fc.allowable_stress_increase("6E", True) == 1.2
    assert fc.allowable_stress_increase("6E", False) == 1.0
    assert fc.allowable_stress_increase("7", True) == 1.0
    # Sec 1.5.9 (p. 500).
    assert fc.uplift_dead_factor() == 0.85


def test_lr_or_r_alternate():
    combination = LoadCombination(name="1.2D + 1.6L + 0.5Lr", D=1.2, L=1.6, Lr=0.5)
    assert fc.alternate_combinations([combination], {"D", "L", "Lr"}) is None
    formed = fc.alternate_combinations([combination], {"D", "L", "Lr", "R"})
    twin = formed[1]
    assert twin.name == "1.2D + 1.6L + 0.5Lr [Lr → R]"
    assert fc.combination_factors(twin)["R"] == 0.5 and "Lr" not in fc.combination_factors(twin)


def test_exceptions_and_cantilever_uplift():
    table = builtin_table("combinations")
    live = table.exceptions["reducedLive"]
    assert (live.to, live.liveMax, live.rows) == (0.5, 5.0, ["3L", "4", "5"])
    assert fc.exception_applies(live, live_loads=[("residential", 2.0)])[0]
    assert not fc.exception_applies(live, live_loads=[("parking", 2.0)])[0]
    assert not fc.exception_applies(live, live_loads=[("storageLight", 6.0)])[0]
    wind = table.exceptions["concreteWind"]
    # Exception 3: only where W is not reduced by directionality (BNBC's Kd is 0.85).
    assert not fc.exception_applies(wind, directionality=0.85, material="concrete")[0]
    assert fc.exception_applies(wind, directionality=1.0, material="concrete")[0]
    row = next(r for r in table.strength if r.id == "4")
    assert fc.apply_exception(row, wind).name == "1.2D + 1.3W + 1.0L + 0.5Lr"
    # Sec 2.5.13.6 (p. 647): 0.2D upward on cantilevers in SDC D only.
    uplift = fc.cantilever_uplift("D")
    assert uplift is not None and uplift.D == -0.2
    assert uplift.name.startswith(fc.CANTILEVER_PREFIX)
    assert fc.cantilever_uplift("C") is None

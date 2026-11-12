"""Lightning protection and earthing (BNBC 2020 Part 8 Sec 1.3.32-1.3.33)."""

from __future__ import annotations

import pytest
from shapely.geometry import box

from saengine.electrical.lightning import (
    air_terminals,
    choose_down_conductors,
    column_lines,
    down_conductors_needed,
    risk_index,
    roof_conductors,
)
from saengine.library.bim import BuildingModel
from saengine.library.mep import Lightning
from saengine.verification.cases.electrical import eight_storey_bim, results


def test_risk_index_of_table_8_1_27() -> None:
    # Office, RC with nonmetal roof, 28 m, in a town, flat, over 21 thunderstorm days:
    # 7 + 2 + 2 + 2 + 2 + 11 + 21 = 47.
    risk = risk_index(Lightning(), ["office"], 28.0)
    assert risk["total"] == 47 and risk["decision"] == "recommended"
    # BNBC's first example of Table 8.1.28: small house below 10 m in a town: 35, none.
    house = Lightning(construction="masonry")
    assert risk_index(house, ["residenceSingle"], 8.0)["total"] == 2 + 4 + 2 + 2 + 2 + 2 + 21
    assert risk_index(house, ["residenceSingle"], 8.0)["decision"] == "notRequired"
    assert risk_index(Lightning(), ["office"], 60.0)["decision"] == "required"
    few_days = Lightning(thunderstormDays=5)
    assert risk_index(few_days, ["office"], 28.0)["indices"]["G"] == 5


def test_down_conductor_count_for_a_roof_perimeter() -> None:
    # 30 x 20 m: perimeter 100 m -> 4; base area 600 m² -> 1 + ceil(520 / 100) = 7.
    assert down_conductors_needed(600, 100_000, "perimeter", None)[0] == 4
    assert down_conductors_needed(600, 100_000, "area", None)[0] == 7
    assert down_conductors_needed(90, 38_000, "perimeter", None)[0] == 1
    n, spacing, _ = down_conductors_needed(600, 100_000, "perimeter", "I")
    assert (n, spacing) == (10, 10_000)


def test_down_conductors_at_the_corner_columns() -> None:
    lp = results()["lightning"]
    spots = {(c["x"], c["y"]) for c in lp["downConductors"]}
    assert spots == {(0, 0), (30000, 0), (30000, 20000), (0, 20000)}
    first = lp["downConductors"][0]
    assert first["foundation"] == f"F-{first['x']:g}-{first['y']:g}"
    assert len(first["columns"]) == 8  # GF to L7, continuous
    assert any("weld or clamp" in n for n in lp["structuralNotes"])


def test_a_broken_column_line_is_not_a_down_conductor() -> None:
    bim = eight_storey_bim()
    data = bim.model_dump(mode="json", by_alias=True)
    data["elements"] = [e for e in data["elements"] if e["id"] != "C-L3-0-0"]
    lines = column_lines(BuildingModel.model_validate(data), 28000)
    corner = next(line for line in lines if (line["x"], line["y"]) == (0, 0))
    assert not corner["continuous"]
    chosen, gap = choose_down_conductors(lines, box(0, 0, 30000, 20000), 4, 30000)
    assert (0, 0) not in {(c["x"], c["y"]) for c in chosen}
    assert gap <= 30000


def test_air_terminals_and_roof_conductors() -> None:
    roof = box(0, 0, 30000, 20000)
    spikes = air_terminals(roof, 28000)
    assert len(spikes) >= 8 and all(p[2] == 28300 for p in spikes)
    lines, worst = roof_conductors(roof, 9000)
    assert worst == pytest.approx(5000, abs=1)
    assert len(lines) >= 3  # the periphery, one line across each way
    lp = results()["lightning"]
    assert lp["earth"]["limit"] == 10
    assert lp["earth"]["clearance"] == pytest.approx(0.3 * 10 + 28 / (15 * 4))


def test_foundations_from_09_substructure() -> None:
    from saengine.electrical.lightning import foundations_of

    bases = foundations_of(
        eight_storey_bim(), {"foundations": [{"id": "PC1", "columns": ["C-GF-0-0"]}]}
    )
    assert bases["C-GF-0-0"] == "PC1"  # 09 Substructure first
    assert bases["C-GF-30000-0"] == "F-30000-0"  # else the 06 BIM footing below

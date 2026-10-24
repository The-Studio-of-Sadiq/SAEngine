"""The Ω0 combinations and the elements that need them (saengine.design.overstrength): the
factors for the sample's location by hand (BNBC 2020 Part 6 Sec 2.5.13.4, p. 646) and the
supporting elements of discontinuous columns and walls in synthetic models (Sec 2.5.5.6.1,
p. 625)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.design import overstrength as ov
from saengine.library.bim import BuildingModel
from saengine.library.settings import ProjectSettings

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"


def sample_settings() -> ProjectSettings:
    path = SAMPLE / "02 Project Settings" / "project-settings.json"
    return ProjectSettings.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_em_factors_for_the_sample_location_by_hand() -> None:
    settings = sample_settings()
    assert (settings.site.location, settings.site.siteClass) == ("dhaka", "SD")
    factors = ov.em_factors(settings)
    # Dhaka: zone 2, Z = 0.20; SD: S = 1.35 (Table 6.2.16); a_h = (2/3) Z S = 0.18.
    ah = 2 / 3 * 0.20 * 1.35
    assert factors["ah"] == pytest.approx(ah)
    assert factors["ev"] == pytest.approx(0.5 * ah)  # Ev = 0.5 a_h D
    assert factors["omega"] == 3  # RC special moment frame, Table 6.2.19
    assert factors["upper"] == {"D": pytest.approx(1.29), "E": 3}
    assert factors["lower"] == {"D": pytest.approx(0.81), "E": 3}
    combos = {c["name"]: c for c in ov.omega_combinations(settings)}
    upper = combos["Ω0: 1.2D + 1.0EX + 1.0L"]
    assert (upper["D"], upper["L"], upper["EX"], upper["EY"]) == (1.29, 1.0, 3.0, 0.0)
    lower = combos["Ω0: 0.9D + 1.0(-EY)"]
    assert (lower["D"], lower["L"], lower["EX"], lower["EY"]) == (0.81, 0.0, 0.0, -3.0)
    # Only the earthquake combinations get an Ω0 twin (8 of the sample's).
    assert len(combos) == sum(1 for c in settings.combinations if c.EX or c.EY) == 8


def column(cid: str, x: float, y: float, bottom: float, top: float) -> dict:
    return {
        "id": cid,
        "kind": "column",
        "type": "COL",
        "position": [x, y],
        "bottom": bottom,
        "top": top,
    }


def beam(bid: str, start: list, end: list, z: float) -> dict:
    return {"id": bid, "kind": "beam", "type": "BM", "start": start, "end": end, "elevation": z}


def test_column_stopping_on_a_beam_carried_by_a_girder() -> None:
    # Level 3000: a girder G1 between CA and CB; B2 spans from G1's middle to CC; the column CU
    # stops on B2. B2 and CC are found directly, G1 (carrying B2) and CA, CB down the chain.
    model = BuildingModel.model_validate(
        {
            "elements": [
                column("CA", 0, 0, 0, 3000),
                column("CB", 12000, 0, 0, 3000),
                column("CC", 6000, 6000, 0, 3000),
                beam("G1", [0, 0], [12000, 0], 3000),
                beam("B2", [6000, 0], [6000, 6000], 3000),
                beam("B3", [0, 6000], [6000, 6000], 3000),
                column("CU", 6000, 3000, 3000, 6000),
                column("CN", 0, 0, 3000, 6000),  # continues CA: not discontinuous
            ]
        }
    )
    elements = {e["id"]: e for e in ov.supporting_elements(model)}
    assert {i: e["found"] for i, e in elements.items()} == {
        "B2": "direct",
        "CC": "direct",
        "G1": "girder",
        "CA": "girder",
        "CB": "girder",
    }
    assert all(e["discontinuous"] == "CU" for e in elements.values())
    assert elements["G1"]["reason"].startswith("carries beam B2")
    assert "B3" not in elements and "CN" not in elements


def test_planted_column_on_a_slab_and_wall_under_a_transfer_beam() -> None:
    model = BuildingModel.model_validate(
        {
            "elements": [
                column("CA", 0, 0, 0, 3000),
                column("CB", 6000, 0, 0, 3000),
                {
                    "id": "W1",
                    "kind": "wall",
                    "type": "WALL",
                    "start": [6000, 3000],
                    "end": [6000, 9000],
                    "bottom": 0,
                    "top": 3000,
                },
                beam("B1", [0, 6000], [6000, 6000], 3000),
                column("CU", 3000, 6000, 3000, 6000),  # on B1, whose end rests on W1
                {
                    "id": "S1",
                    "kind": "slab",
                    "type": "SLAB",
                    "boundary": [[0, 0], [6000, 0], [6000, 6000], [0, 6000]],
                    "elevation": 3000,
                },
                column("CP", 3000, 3000, 3000, 6000),  # on the slab, no beam under it
            ]
        }
    )
    elements = {e["id"]: e for e in ov.supporting_elements(model)}
    assert elements["B1"]["found"] == "direct"
    assert elements["W1"] == {
        "id": "W1",
        "kind": "wall",
        "reason": "supports beam B1 under discontinuous column CU",
        "discontinuous": "CU",
        "found": "wall",
    }
    assert elements["S1"]["found"] == "slab" and elements["S1"]["discontinuous"] == "CP"
    scope = ov.overstrength_scope(sample_settings(), model)
    assert scope["ids"] == ["B1", "S1", "W1"]
    assert scope["added"] == ["S1", "W1"]
    assert len(scope["combinations"]) == 8
    assert any("transfer slab" in n for n in scope["notes"])


def test_no_discontinuity_no_combinations() -> None:
    model = BuildingModel.model_validate(
        {
            "elements": [
                column("CA", 0, 0, 0, 3000),
                column("CB", 6000, 0, 0, 3000),
                beam("B1", [0, 0], [6000, 0], 3000),
            ]
        }
    )
    scope = ov.overstrength_scope(sample_settings(), model)
    assert scope["elements"] == [] and scope["combinations"] == []

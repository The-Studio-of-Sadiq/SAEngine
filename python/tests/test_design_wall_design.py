"""Integrator glue of the walls and stairs round: walls in the design report
(saengine.design.wall_design), the design mode's wall and stair rows and proposals, the report
tables, the BOQ of end bars and dog-legged stairs, and the new object-type fields.

Synthetic, hand-made data: the pier forces are given (the cuts themselves are stream F's,
tested in test_design_wall_forces.py), so each expectation is the walls module's own result
for the same inputs, or a hand calculation."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from saengine.design import stairs as S
from saengine.design import wall_design
from saengine.design import walls as W
from saengine.design.required import _row, stair_rows
from saengine.fem.combinations import DesignCombination
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import BuildingModel
from saengine.library.objects import Staircase, Wall
from saengine.library.settings import ProjectSettings, derived

EQ = "1.2D + 1.0L + 1.0EX"
GRAVITY = "1.4D"
COMBOS = [
    DesignCombination(EQ, {"D": 1.2, "L": 1.0, "EX": 1.0}),
    DesignCombination(GRAVITY, {"D": 1.4}),
]
SPECIAL = {"applies": {"8.3.6": {"applies": True}}, "omega": {"elements": []}}

WALL_TYPE = {
    "id": "W250",
    "name": "Wall 250",
    "kind": "wall",
    "material": "C24.1",
    "thickness": 250,
    "reinforcement": {
        "material": "B420DWR",
        "cover": 25,
        "vertical": {"dia": 12, "spacing": 200},
        "horizontal": {"dia": 10, "spacing": 200},
        "layers": 2,
    },
}


def _building() -> BuildingModel:
    return BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
            ],
            "elements": [
                {
                    "id": "W1",
                    "type": "W250",
                    "kind": "wall",
                    "start": [0, 0],
                    "end": [5000, 0],
                    "bottom": 0,
                    "top": 3000,
                }
            ],
        }
    )


def _cut(p: float, v: float, m: float) -> dict[str, float]:
    return {"P": p, "V2": v, "V3": 0.0, "T": 0.0, "M2": 0.0, "M3": m}


def _pier(name: str, start: float, end: float, shells: list[int]) -> dict:
    return {
        "pier": name,
        "wall": "W1",
        "type": "W250",
        "storey": "L1",
        "label": "Base to Level 1",
        "bottom": 0.0,
        "top": 3000.0,
        "start": start,
        "end": end,
        "lw": end - start,
        "tw": 250.0,
        "shells": shells,
        "holes": [],
        "spandrels": ["W1/L1/S1"],
        "cuts": {
            "bottom": {EQ: _cut(900, 350, 1100), GRAVITY: _cut(1200, 5, 10)},
            "middle": {EQ: _cut(850, 350, 600), GRAVITY: _cut(1150, 5, 5)},
            "top": {EQ: _cut(800, 350, 100), GRAVITY: _cut(1100, 5, 0)},
        },
    }


FOUND = {
    "piers": [_pier("W1/L1/P1", 0, 2000, [1]), _pier("W1/L1/P2", 3000, 5000, [2])],
    "spandrels": [
        {
            "spandrel": "W1/L1/S1",
            "wall": "W1",
            "type": "W250",
            "storey": "L1",
            "position": "above",
            "opening": "D1",
            "length": 1000.0,
            "depth": 800.0,
            "tw": 250.0,
            "shells": [3],
            "cuts": {"left": {EQ: _cut(0, 280, 50)}, "right": {EQ: _cut(0, -300, 60)}},
        }
    ],
    "sections": [
        {
            "section": "W1/L1",
            "wall": "W1",
            "type": "W250",
            "storey": "L1",
            "bottom": 0.0,
            "top": 3000.0,
            "lw": 5000.0,
            "tw": 250.0,
            "shells": [1, 2, 3],
            "holes": [],
            "segments": {"bottom": [[0, 5000]], "top": [[0, 5000]]},
            "piers": ["W1/L1/P1", "W1/L1/P2"],
            "spandrels": ["W1/L1/S1"],
            "cuts": {"bottom": {EQ: _cut(1800, 700, 4000), GRAVITY: _cut(2400, 10, 20)}},
        }
    ],
    "notes": [],
}

#: The wall's shells and nodes: the top nodes 3, 4 move 6 mm along the wall in EQ.
PROJECT = {
    "nodes": [
        {"id": 1, "coords": [0, 0, 0]},
        {"id": 2, "coords": [5, 0, 0]},
        {"id": 3, "coords": [5, 0, 3]},
        {"id": 4, "coords": [0, 0, 3]},
    ],
    "elements": [{"id": 1, "type": "Shell", "name": "W1", "nodes": [1, 2, 3, 4]}],
}
EXTRA = {
    "factors": [{"D": 1.2, "L": 1.0, "EX": 1.0}, {"D": 1.4}],
    "lateralDisplacements": [
        {3: np.array([0.006, 0, 0, 0, 0, 0]), 4: np.array([0.006, 0, 0, 0, 0, 0])},
        {},
    ],
}


SAMPLE = Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples"


def _settings() -> ProjectSettings:
    """The sample's settings (an RC special moment frame, Cd 5.5, I 1.0)."""
    path = SAMPLE / "Sample Frame" / "02 Project Settings" / "project-settings.json"
    return ProjectSettings.model_validate_json(path.read_text(encoding="utf-8"))


def _run(monkeypatch, scope, collect=None, wall_type=WALL_TYPE, found=None, extra=None, names=None):
    from saengine.design import wall_forces

    monkeypatch.setattr(
        wall_forces, "design_combination_list", lambda *a, **k: (list(COMBOS), None, "corners")
    )
    monkeypatch.setattr(wall_forces, "wall_forces", lambda *a, **k: found or FOUND)
    types = {o.id: o for o in ObjectLibrary.model_validate({"objects": [wall_type]}).objects}
    mats = {m.id: m for m in default_material_library().materials}
    settings = _settings()
    return wall_design.design_walls(
        PROJECT,
        "unused",
        _building(),
        types,
        mats,
        settings,
        settings,
        settings,
        scope,
        extra or EXTRA,
        names or [EQ, GRAVITY],
        collect,
    )


def _expected(pier: dict, special: bool, drift: float | None, cuts=("bottom", "middle", "top")):
    bars = W.wall_bars(WALL_TYPE["reinforcement"])
    geometry = W.geometry_of(pier, wall_height=3000.0, continuous=True)
    forces = [
        W.PierForces(**{**f.__dict__, "earthquake": f.combination == EQ})
        for f in W.pier_rows(pier, None, cuts)
    ]
    return W.wall_checks(
        geometry, bars, forces, 24.1, 420.0, 200_000.0, special=special, drift=drift
    )


def test_ordinary_wall_is_its_piers_checks(monkeypatch) -> None:
    found = _run(monkeypatch, None)
    (wall,) = found["elements"]
    assert wall["kind"] == "wall" and wall["wallType"] == "ordinary"
    # The spandrel over the door (between P1 and P2) is designed as a beam (ln/h = 1.25: deep).
    (beam,) = wall["couplingBeams"]
    assert beam["id"] == "W1/L1/S1" and beam["mode"] == "deep" and beam["ok"] is not None
    assert beam["bars"]["bottom"] == beam["bars"]["top"]
    # The two piers and the continuous section at the base (one solid segment, two piers).
    assert [p["id"] for p in wall["piers"]] == ["W1/L1 (whole wall)", "W1/L1/P1", "W1/L1/P2"]
    p1 = next(p for p in wall["piers"] if p["id"] == "W1/L1/P1")
    expected = _expected(FOUND["piers"][0], False, None)
    assert p1["checks"] == expected.checks and p1["utilisation"] == expected.utilisation
    whole = wall["piers"][0]
    assert whole["whole"] and whole["lw"] == 5000
    section = {**FOUND["sections"][0], "pier": "W1/L1 (whole wall)"}
    assert whole["checks"] == _expected(section, False, None, ("bottom",)).checks
    # The wall's checks are all its piers' and the spandrel's, each note led by its part; the
    # governing forces are those of the governing check's combination at the bottom.
    assert len(wall["checks"]) == sum(len(p["checks"]) for p in wall["piers"]) + len(beam["checks"])
    assert all(
        c["note"].startswith(("W1/L1/P", "W1/L1 (whole", "W1/L1/S1")) for c in wall["checks"]
    )
    assert found["skipped"] == []
    assert wall["utilisation"] == max(
        [p["utilisation"] for p in wall["piers"]] + [beam["utilisation"]]
    )
    assert p1["forces"]["combination"] in (EQ, GRAVITY)
    assert wall["members"] == [1, 2, 3] and wall["curtains"] == 2 and wall["boundary"] is None


def test_special_wall_drift_boundary_and_coupling_beam(monkeypatch) -> None:
    collect: dict = {}
    found = _run(monkeypatch, SPECIAL, collect)
    (wall,) = found["elements"]
    values = derived(_settings())
    drift = values["Cd"] / values["seismicImportance"] * 6.0 / 3000.0  # Cd δe / I / hw
    assert wall["wallType"] == "special" and wall["drift"] == pytest.approx(drift, abs=1e-5)
    p1 = next(p for p in wall["piers"] if p["id"] == "W1/L1/P1")
    expected = _expected(FOUND["piers"][0], True, drift)
    assert p1["checks"] == expected.checks
    need = expected.need.boundary
    assert p1["boundary"]["method"] == "displacement"
    assert p1["boundary"]["required"] == need.required
    assert p1["boundary"]["trigger"] == pytest.approx(2000 / (600 * max(drift, 0.007)), abs=0.1)
    # One curtain: 250 mm is not over 250 (6.6.3.4), and Vu stays below 0.17 Acv √f'c
    # (P1: 350 kN < 0.17 x 2000 x 250 x √24.1 = 417 kN; the whole wall 700 < 1043 kN).
    assert 350e3 < 0.17 * 2000 * 250 * math.sqrt(24.1)
    assert 700e3 < 0.17 * 5000 * 250 * math.sqrt(24.1)
    assert wall["curtainsRequired"] == 1
    (beam,) = wall["couplingBeams"]
    # ln/h = 1000/800 = 1.25 < 2 and Vu 300 kN < 0.33 Acw √f'c = 0.33 x 200 000 x √24.1: either.
    assert 300e3 < 0.33 * 250 * 800 * math.sqrt(24.1)
    assert beam["id"] == "W1/L1/S1" and beam["ln"] == 1000 and beam["h"] == 800
    assert any("8.3.6.7(c)" in n for n in beam["notes"])
    # No diagonal bars entered: designed to the beam rules (8.3.6.7(c)) with the special
    # moment frame beam rules and the capacity-design shear.
    assert beam["mode"] == "either" and beam["ok"] is not None and beam["checks"]
    assert any(c["name"].startswith("Capacity-design shear") for c in beam["checks"])
    assert not any(s["id"] == "W1/L1/S1" for s in found["skipped"])
    # The design mode gets every pier with what it was checked from.
    assert {c["id"] for c in collect["walls"]} == {p["id"] for p in wall["piers"]}
    assert all(c["special"] and c["drift"] == pytest.approx(drift) for c in collect["walls"])


def test_wall_without_bars_is_skipped(monkeypatch) -> None:
    bare = {k: v for k, v in WALL_TYPE.items() if k != "reinforcement"}
    found = _run(monkeypatch, None, wall_type=bare)
    assert found["elements"] == []
    assert found["skipped"] == [
        {"id": "W1", "kind": "wall", "type": "W250", "reason": "no reinforcement"}
    ]


def test_design_mode_rows_and_proposal_for_walls(monkeypatch) -> None:
    collect: dict = {}
    _run(monkeypatch, None, collect)
    rows = [r for c in collect["walls"] for r in wall_design.required_rows(c, False, _row)]
    vertical = next(
        r for r in rows if r["element"] == "W1/L1/P1" and r["location"] == "web, vertical"
    )
    # Entered Ø12 @ 200 per face: 113.1 x 1000 / 200 = 565.5 mm²/m.
    assert vertical["provided"] == pytest.approx(565.5, abs=0.1) and vertical["unit"] == "mm²/m"
    entries = wall_design.proposal_entries(collect["walls"], set(), {"W250": WALL_TYPE})
    (entry,) = entries
    assert entry["kind"] == "wall" and entry["members"] == ["W1"]
    assert entry["status"] in ("ok", "unchanged")
    proposed = {k: v for k, v in entry["proposed"].items() if k != "text"}
    Wall.model_validate({**WALL_TYPE, "reinforcement": proposed})  # a valid 04 Objects type
    # Checked again on every pier with the bars proposed: all pass.
    assert entry["utilisation"]["piers"] <= 1.0
    assert not any("still fails" in n for n in entry["notes"])


def test_proposal_gives_coupling_beams_diagonal_bars_and_hoops(monkeypatch) -> None:
    """Owner 2026-11-03 (sample W250 boundary elements and spandrel hoops): a special wall's
    coupling beam that may take diagonal bars (8.3.6.7(c)) and fails the beam rules gets them
    from Design Reinforcement, with hoops over the whole section ((d)(iv)); applied, it passes."""
    collect: dict = {}
    found = _run(monkeypatch, SPECIAL, collect)
    (beam,) = found["elements"][0]["couplingBeams"]
    assert beam["mode"] == "either" and beam["ok"] is False  # the beam rules: Ve too large
    (spandrel,) = collect["spandrels"]
    assert spandrel["id"] == "W1/L1/S1" and spandrel["asBeam"] and spandrel["ok"] is False
    entries = wall_design.proposal_entries(
        collect["walls"], set(), {"W250": WALL_TYPE}, collect["spandrels"]
    )
    (entry,) = entries
    diagonal = entry["proposed"]["diagonal"]
    assert diagonal["count"] >= 4 and diagonal["hoop"]["spacing"] <= 6 * diagonal["dia"]
    assert "coupling beams" in entry["proposed"]["text"]
    assert any(n.startswith("coupling beams W1/L1/S1:") for n in entry["notes"])
    proposed = {k: v for k, v in entry["proposed"].items() if k != "text"}
    applied = {**WALL_TYPE, "reinforcement": proposed}
    Wall.model_validate(applied)  # a valid 04 Objects type
    again = _run(monkeypatch, SPECIAL, wall_type=applied)
    (beam,) = again["elements"][0]["couplingBeams"]
    assert beam["diagonal"] and beam["ok"] is True
    assert {c["name"] for c in beam["checks"]} >= {
        "Coupling beam hoop spacing (8.3.6.7(d)(iv))",
        "Coupling beam Ash, bc down the depth (8.3.5.4, Eq. 6.8.7, 6.8.8)",
    }
    # Without the spandrels (an ordinary wall, or none needing them): no diagonal bars.
    (plain,) = wall_design.proposal_entries(collect["walls"], set(), {"W250": WALL_TYPE})
    assert "diagonal" not in (plain["proposed"] or {})


def test_stair_rows_and_new_fields() -> None:
    stair = Staircase.model_validate(
        {
            "id": "ST",
            "name": "Stair",
            "material": "C24.1",
            "waistThickness": 150,
            "riser": 165,
            "tread": 250,
            "flightWidth": 1200,
            "reinforcement": {
                "material": "B420DWR",
                "cover": 20,
                "main": {"dia": 12, "spacing": 275},
                "distribution": {"dia": 10, "spacing": 275},
            },
        }
    )
    # Old files stay valid: the new fields' defaults are stream T's.
    assert (stair.arrangement, stair.spanning, stair.supportWidth) == (
        "straight",
        "betweenBeams",
        250,
    )
    assert S.spec_of(stair).spanning == "betweenBeams"
    need = S.StairNeed(main={12.0: 410.1}, distribution=270.0)
    rows = stair_rows({"type": "ST", "object": stair, "need": need, "members": ["ST1"]})
    main = next(r for r in rows if r["location"] == "main bars")
    # Ø12 @ 275: 113.1 x 1000 / 275 = 411.3 mm²/m against 410.1 required.
    assert main["required"] == 410.1 and main["provided"] == pytest.approx(411.3, abs=0.1)
    assert main["ok"] is True
    dist = next(r for r in rows if r["location"] == "distribution bars")
    assert dist["required"] == 270.0 and dist["provided"] == pytest.approx(285.6, abs=0.1)


def test_wall_stacks() -> None:
    building = BuildingModel.model_validate(
        {
            "stories": [{"id": "B", "name": "B", "elevation": 0}, {"id": "L1", "name": "L1", "elevation": 3000}],
            "elements": [
                {"id": "A", "type": "W", "kind": "wall", "start": [0, 0], "end": [4000, 0],
                 "bottom": 0, "top": 3000},
                {"id": "B", "type": "W", "kind": "wall", "start": [4000, 0], "end": [0, 0],
                 "bottom": 3000, "top": 6000},
                {"id": "C", "type": "W", "kind": "wall", "start": [0, 0], "end": [4000, 0],
                 "bottom": 7000, "top": 9000},
            ],
        }
    )  # fmt: skip
    stacks = wall_design.wall_stacks(building)
    assert stacks["A"] == stacks["B"] == (0.0, 6000.0, ["A", "B"])
    assert stacks["C"] == (7000.0, 9000.0, ["C"])


def test_report_tables_and_boq_end_bars() -> None:
    from saengine.report.build import _stairs, _walls

    report = {
        "elements": [
            {
                "id": "W1",
                "kind": "wall",
                "piers": [
                    {
                        "id": "W1/L1/P1",
                        "storey": "Level 1",
                        "lw": 2000,
                        "tw": 250,
                        "forces": {"P": 900, "V2": 350, "M3": 1100},
                        "checks": [
                            {"name": "Shear", "utilisation": 0.5, "flag": False, "ok": True}
                        ],
                        "utilisation": 0.5,
                        "ok": True,
                        "boundary": {"method": "stress", "stress": 3.2, "required": False},
                    }
                ],
                "couplingBeams": [],
            },
            {
                "id": "ST1",
                "kind": "staircase",
                "parts": [{"name": "F1", "kind": "flight", "span": 3000, "h": 150}],
                "checks": [
                    {"name": "F1: flexure (bottom)", "utilisation": 0.99, "ok": True, "flag": False}
                ],
            },
        ]
    }
    walls = _walls(report)
    assert walls["piers"][0][:5] == ["W1", "W1/L1/P1", "Level 1", "2,000", "250"]
    assert walls["boundary"][0][2:5] == ["stress", "σ 3.20 MPa", "not required"]
    stairs = _stairs(report)
    assert stairs["parts"][0][0:3] == ["ST1", "F1", "flight"] and stairs["partsBad"] == [False]


def test_boq_measures_end_bars_and_dog_legged_stairs() -> None:
    from saengine.boq.quantities import bill_of_quantities

    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    **WALL_TYPE,
                    "reinforcement": {
                        **WALL_TYPE["reinforcement"],
                        "boundary": {
                            "length": 400,
                            "count": 4,
                            "dia": 16,
                            "hoop": {"dia": 10, "spacing": 100},
                        },
                    },
                },
                {
                    "id": "ST",
                    "name": "Stair",
                    "kind": "staircase",
                    "material": "C24.1",
                    "waistThickness": 150,
                    "riser": 150,
                    "tread": 250,
                    "flightWidth": 1200,
                    "arrangement": "dogLegged",
                    "landingLength": 1200,
                    "reinforcement": {
                        "material": "B420DWR",
                        "cover": 20,
                        "main": {"dia": 12, "spacing": 150},
                        "distribution": {"dia": 10, "spacing": 200},
                    },
                },
            ]
        }
    )
    building = _building().model_copy(
        update={
            "additions": BuildingModel.model_validate(
                {
                    "additions": {
                        "stairs": [
                            {"id": "S1", "type": "ST", "base": "BASE", "top": "L1", "x": 0, "y": 0}
                        ]
                    }
                }
            ).additions
        }
    )
    boq = bill_of_quantities(building, objects, default_material_library())
    text = boq.model_dump_json()
    assert "end bars" in text and "end hoops" in text and "landing" in text


def _with_pier(found: dict, pier: dict) -> dict:
    return {**found, "piers": [*found["piers"], pier], "sections": []}


def _sliver(lw: float) -> dict:
    """A short pier beside a door (as the sample's 100 mm W1/L1/P2), lightly loaded."""
    pier = _pier("W1/L1/P3", 2000, 2000 + lw, [4])
    pier["cuts"] = {"bottom": {EQ: _cut(50, 5, 2)}, "top": {EQ: _cut(40, 5, 1)}}
    return pier


def _heavy(m: float) -> dict:
    """FOUND with P1's moment at its bottom in EQ set to ``m`` [kN·m]."""
    found = {**FOUND, "piers": [dict(p) for p in FOUND["piers"]]}
    p1 = found["piers"][0]
    p1["cuts"] = {**p1["cuts"], "bottom": {**p1["cuts"]["bottom"], EQ: _cut(900, 350, m)}}
    return found


def test_pier_the_bars_cannot_be_laid_out_in_fails_the_wall(monkeypatch) -> None:
    # End bars 1100 mm long at both ends of 2000 mm piers overlap (2 x 1100 >= 2000): the piers
    # are not checked, so they fail (they are not left out of a passing wall).
    boundary = {"length": 1100, "count": 4, "dia": 16, "hoop": {"dia": 10, "spacing": 100}}
    wall_type = {
        **WALL_TYPE,
        "reinforcement": {**WALL_TYPE["reinforcement"], "boundary": boundary},
    }
    collect: dict = {}
    found = _run(monkeypatch, None, collect, wall_type=wall_type)
    (wall,) = found["elements"]
    assert not wall["ok"] and wall["utilisation"] == pytest.approx(1.1)
    p1 = next(p for p in wall["piers"] if p["id"] == "W1/L1/P1")
    assert p1["ok"] is False and p1["members"] == [1]
    (row,) = p1["checks"]
    assert row["name"].startswith("End bars fit in the pier")
    assert (row["demand"], row["capacity"], row["ok"]) == (2200.0, 2000.0, False)
    assert "overlap" in row["note"]
    # The design mode still sees the pier.
    assert "W1/L1/P1" in {c["id"] for c in collect["walls"]}


def test_proposal_not_offered_when_a_pier_cannot_take_the_end_bars(monkeypatch) -> None:
    # P1 needs end bars and no web alone carries it (M 3000 kN·m): the end bars do not fit in
    # the 150 mm P3, so the type gets no proposal (too small), with P3 named.
    collect: dict = {}
    _run(monkeypatch, None, collect, found=_with_pier(_heavy(3000.0), _sliver(150.0)))
    # As a type without bars of its own (the curtains searched, not kept from the type's).
    (entry,) = wall_design.proposal_entries(collect["walls"], {"W250"}, {"W250": WALL_TYPE})
    assert entry["status"] == "tooSmall" and entry["proposed"] is None
    assert "W1/L1/P3" in entry["tooSmall"]["reason"] and "overlap" in entry["tooSmall"]["reason"]
    assert entry["utilisation"] == {"piers": 0.0}


def test_proposal_falls_back_to_a_heavier_web_without_end_bars(monkeypatch) -> None:
    # M 1800 kN·m: the least web needs end bars, which P3 cannot take; a heavier web alone
    # carries P1, and every pier passes with it.
    collect: dict = {}
    _run(monkeypatch, None, collect, found=_with_pier(_heavy(1800.0), _sliver(150.0)))
    (entry,) = wall_design.proposal_entries(collect["walls"], set(), {"W250": WALL_TYPE})
    assert entry["status"] == "ok"
    proposed = {k: v for k, v in entry["proposed"].items() if k != "text"}
    assert "boundary" not in proposed
    assert any("heavier vertical web" in n for n in entry["notes"])
    bars = W.wall_bars(proposed)
    for c in collect["walls"]:
        d = W.wall_checks(c["geometry"], bars, c["forces"], c["fc"], c["fy"], c["es"])
        assert all(x["ok"] for x in d.checks if not x["flag"]), c["id"]
    # The type's two curtains are kept (X12 of the usability walk: cut to one).
    assert proposed["layers"] == 2
    assert not any("not checked with these bars" in n for n in entry["notes"])


def test_drift_ignores_the_omega_combinations(monkeypatch) -> None:
    # An "Ω0: " combination with EX x 3 moves the top 18 mm; δu = Cd δxe / I (Eq. 6.2.45) is
    # design level, so the drift stays that of the 6 mm, whichever elements are Ω0 ones.
    omega = "Ω0: 1.2D + 1.0L + 3.0EX"
    extra = {
        "factors": [*EXTRA["factors"], {"D": 1.2, "L": 1.0, "EX": 3.0}],
        "lateralDisplacements": [
            *EXTRA["lateralDisplacements"],
            {3: np.array([0.018, 0, 0, 0, 0, 0]), 4: np.array([0.018, 0, 0, 0, 0, 0])},
        ],
    }
    values = derived(_settings())
    drift = values["Cd"] / values["seismicImportance"] * 6.0 / 3000.0
    for elements in ([], ["W1"]):
        scope = {**SPECIAL, "omega": {"elements": elements}}
        found = _run(monkeypatch, scope, extra=extra, names=[EQ, GRAVITY, omega])
        assert found["elements"][0]["drift"] == pytest.approx(drift, abs=1e-5)


def _special_p1():
    pier = FOUND["piers"][0]
    geometry = W.geometry_of(pier, wall_height=3000.0, continuous=True)
    forces = W.pier_rows(pier, None, ("bottom", "middle", "top"))
    values = derived(_settings())
    drift = values["Cd"] / values["seismicImportance"] * 6.0 / 3000.0
    return geometry, forces, drift


def test_end_bars_without_hoops_count_no_hoops() -> None:
    entered = {**WALL_TYPE["reinforcement"], "boundary": {"length": 600, "count": 8, "dia": 20}}
    bars = W.wall_bars(entered)
    assert bars.boundary.hoops is False
    hooped = {**entered["boundary"], "hoop": {"dia": 10, "spacing": 100}}
    assert W.wall_bars({**entered, "boundary": hooped}).boundary.hoops
    # P1 of the special wall needs a boundary element (c 438 mm >= lw/(600 δu/hw) 303 mm):
    # with no hoops entered it fails on "hoops provided", and no Ash row counts assumed hoops.
    geometry, forces, drift = _special_p1()
    d = W.wall_checks(geometry, bars, forces, 24.1, 420.0, special=True, drift=drift)
    names = {c["name"]: c for c in d.checks}
    assert not names["Boundary hoops provided (8.3.6.6(d)(iii), 8.3.5.4)"]["ok"]
    assert not any(n.startswith("Boundary Ash") for n in names)
    assert not any(n.startswith("Boundary hoop spacing") for n in names)


def test_end_ties_not_entered_fail(monkeypatch) -> None:
    # Stress method, no boundary element needed (light forces), ρ at the boundary of 8 Ø20 over 600 x 250 =
    # 2513/150 000 = 1.68 % > 2.8/420 = 0.67 %: ties at <= 200 mm are needed (8.3.6.6(e)(i)),
    # and end bars with no hoops entered have none.
    assert 8 * W.bar_area(20) / (250 * 600) > 2.8 / 420
    entered = {**WALL_TYPE["reinforcement"], "boundary": {"length": 600, "count": 8, "dia": 20}}
    geometry, forces, _ = _special_p1()
    light = [replace(f, M3=f.M3 * 0.02, P=f.P * 0.1, V2=f.V2 * 0.1) for f in forces]
    d = W.wall_checks(geometry, W.wall_bars(entered), light, 24.1, 420.0, special=True)
    assert d.need.boundary is not None and not d.need.boundary.required and d.need.boundary.ties
    (row,) = [c for c in d.checks if c["name"].startswith("End tie")]
    assert row["name"].startswith("End ties where") and not row["ok"]
    assert "no ties entered" in row["note"]
    hooped = {**entered["boundary"], "hoop": {"dia": 10, "spacing": 150}}
    d = W.wall_checks(
        geometry, W.wall_bars({**entered, "boundary": hooped}), light, 24.1, 420.0, special=True
    )
    (row,) = [c for c in d.checks if c["name"].startswith("End tie")]
    assert row["name"].startswith("End tie spacing") and row["ok"]


def test_boq_end_bars_at_every_pier() -> None:
    from saengine.boq.quantities import bill_of_quantities, wall_piers
    from saengine.library.bim import WallOpening

    def opening(offset: float, width: float, sill: float, height: float) -> WallOpening:
        return WallOpening.model_validate(
            {"id": f"O{offset:g}", "host": "W1", "offset": offset, "width": width,
             "sill": sill, "height": height}
        )  # fmt: skip

    assert wall_piers(5000, 3000, []) == 1
    # Two doors 100 mm apart leave three piers; a 300 mm high duct (< 0.25 x 3000) splits none.
    doors = [opening(500, 1000, 0, 2100), opening(1600, 1000, 0, 2100)]
    assert wall_piers(5000, 3000, doors) == 3
    assert wall_piers(5000, 3000, [opening(3000, 400, 2400, 300)]) == 1
    # A door at the wall's end leaves one pier.
    assert wall_piers(5000, 3000, [opening(4000, 1000, 0, 2100)]) == 1

    # The BOQ's end bars of a wall with one door in its middle (two piers) are twice those of
    # the wall without it: 2 piers x 2 ends x 4 bars.
    boundary = {"length": 400, "count": 4, "dia": 16, "hoop": {"dia": 10, "spacing": 100}}
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {**WALL_TYPE, "reinforcement": {**WALL_TYPE["reinforcement"], "boundary": boundary}}
            ]
        }
    )

    def end_bars(openings: list) -> float:
        building = _building()
        if openings:
            additions = building.additions.model_copy(update={"wallOpenings": openings})
            building = building.model_copy(update={"additions": additions})
        boq = bill_of_quantities(building, objects, default_material_library())
        data = boq.model_dump()
        rows = [r for r in _rows(data) if r.get("detail") == "end bars"]
        return sum(float(r["quantity"]) for r in rows)

    plain, split = end_bars([]), end_bars([opening(2000, 1000, 0, 2100)])
    assert plain > 0 and split == pytest.approx(2 * plain, rel=1e-3)


def test_boq_and_schedule_measure_the_coupling_beam_diagonals_and_hoops() -> None:
    """Owner 2026-11-03: the wall type's coupling beam bars (``reinforcement.diagonal``) are
    measured over every opening with a pier on each side and the wall above it: the estimate
    (2 groups x count x the corner-to-corner length + 2 x 1.25 x 40 db) and the bar bending
    schedule's G (diagonals), J (hoops) and Y (crossties) bars."""
    from saengine.boq.quantities import bill_of_quantities, wall_spandrels
    from saengine.drawings.detailing import detailing_model
    from saengine.library.bim import WallOpening

    door = WallOpening.model_validate(
        {"id": "D1", "host": "W1", "offset": 2000, "width": 1000, "sill": 0, "height": 2100}
    )
    end = door.model_copy(update={"id": "D2", "offset": 4000})
    assert wall_spandrels(5000, 3000, [door, end]) == [(1000.0, 900.0)]  # D2 ends the wall
    diagonal = {
        "count": 4,
        "dia": 16,
        "hoop": {"dia": 10, "spacing": 75, "legsAcross": 5, "legsAlong": 2},
    }
    typed = {**WALL_TYPE, "reinforcement": {**WALL_TYPE["reinforcement"], "diagonal": diagonal}}
    objects = ObjectLibrary.model_validate({"objects": [typed]})
    building = _building()
    additions = building.additions.model_copy(update={"wallOpenings": [door]})
    building = building.model_copy(update={"additions": additions})
    data = bill_of_quantities(building, objects, default_material_library()).model_dump()
    rows = {r["detail"]: float(r["quantity"]) for r in _rows(data)}
    run = math.hypot(1000, 900 - 50) + 2 * 1.25 * 40 * 16
    assert rows["diagonals"] == pytest.approx(8 * run / 1000 * W.bar_area(16) * 7.85e-3, rel=0.01)
    assert rows["coupling hoops"] > 0
    texts = {
        "bim": building.model_dump_json(),
        "objects": objects.model_dump_json(),
        "materials": default_material_library().model_dump_json(),
    }
    model = detailing_model(texts=texts)
    (wall,) = [e for e in model["elements"] if e["id"] == "W1"]
    roles = {b["role"] for b in wall["bars"]}
    assert {"diagonal", "hoop", "crosstie"} <= roles
    (g,) = [b for b in wall["bars"] if b["role"] == "diagonal"]
    assert g["count"] == 8 and g["dia"] == 16 and g["mark"].split("-")[1].startswith("G")


def _pier_building() -> BuildingModel:
    """W1 (5000 x 3000) with doors D1 at 1500-2500 (2200 high) and D2 at 3300-4200 (2100): a
    wall pier P2 (800 between the doors) and P3 (800 at the end), as the sample's W1."""
    from saengine.library.bim import WallOpening

    building = _building()
    doors = [
        WallOpening.model_validate(d)
        for d in (
            {"id": "D1", "host": "W1", "offset": 1500, "width": 1000, "sill": 0, "height": 2200},
            {"id": "D2", "host": "W1", "offset": 3300, "width": 900, "sill": 0, "height": 2100},
        )
    ]
    additions = building.additions.model_copy(update={"wallOpenings": doors})
    return building.model_copy(update={"additions": additions})


def test_wall_piers_designed_proposed_and_measured(monkeypatch) -> None:
    """Owner 2026-11-04 (8.3.6.8): a special wall's piers beside its openings that are wall
    piers get the pier rows (P2, P3), the pier that is not (P1, 1500 long) none; Design
    Reinforcement proposes their hoops (pierHoop), and applied every pier row passes; the bill
    and the bar bending schedule measure the hoops (Q) over each wall pier's clear height and
    300 mm above and below."""
    from saengine.boq.quantities import bill_of_quantities, wall_pier_parts
    from saengine.design import wall_forces
    from saengine.drawings.detailing import detailing_model

    found = {
        **FOUND,
        "piers": [
            _pier("W1/L1/P1", 0, 1500, [1]),
            _pier("W1/L1/P2", 2500, 3300, [2]),
            _pier("W1/L1/P3", 4200, 5000, [4]),
        ],
        "spandrels": [],
    }
    for p in found["piers"]:
        p["spandrels"] = []
        for cut in p["cuts"].values():
            cut[EQ] = _cut(300, 60, 40)
    monkeypatch.setattr(
        wall_forces, "design_combination_list", lambda *a, **k: (list(COMBOS), None, "corners")
    )
    monkeypatch.setattr(wall_forces, "wall_forces", lambda *a, **k: found)
    mats = {m.id: m for m in default_material_library().materials}
    settings = _settings()

    def design(wall_type: dict, collect: dict | None = None) -> dict:
        types = {o.id: o for o in ObjectLibrary.model_validate({"objects": [wall_type]}).objects}
        return wall_design.design_walls(
            PROJECT, "unused", _pier_building(), types, mats, settings, settings, settings,
            SPECIAL, EXTRA, [EQ, GRAVITY], collect,
        )  # fmt: skip

    collect: dict = {}
    (wall,) = design(WALL_TYPE, collect)["elements"]
    kinds = {p["id"]: p["wallPier"] for p in wall["piers"] if not p["whole"]}
    assert kinds == {"W1/L1/P1": "wall", "W1/L1/P2": "pier", "W1/L1/P3": "pier"}
    failing = {c["name"] for c in wall["checks"] if not c["ok"] and not c["flag"]}
    assert "Wall pier hoops provided (8.3.6.8(a)(iii))" in failing
    edge = [c for c in wall["checks"] if c["name"].startswith("Edge wall pier")]
    assert [c["note"].split(":")[0] for c in edge] == ["W1/L1/P3"]  # at the wall's end
    (entry,) = wall_design.proposal_entries(collect["walls"], set(), {"W250": WALL_TYPE})
    hoop = entry["proposed"]["pierHoop"]
    assert hoop["spacing"] <= 150 and "wall piers hoops" in entry["proposed"]["text"]
    assert any(n.startswith("wall piers W1/L1/P2, W1/L1/P3:") for n in entry["notes"])
    proposed = {k: v for k, v in entry["proposed"].items() if k != "text"}
    applied = {**WALL_TYPE, "reinforcement": proposed}
    Wall.model_validate(applied)
    (again,) = design(applied)["elements"]
    assert all(c["ok"] for c in again["checks"] if c["name"].startswith(("Wall pier", "Edge")))

    # The bill and the schedule: 2 wall piers x floor((2200 or 2100 + 600) / s) + 1 hoops.
    assert wall_pier_parts(5000, 3000, 250, _pier_building().additions.wallOpenings) == [
        (800.0, 2200.0),
        (800.0, 2100.0),
    ]
    objects = ObjectLibrary.model_validate({"objects": [applied]})
    data = bill_of_quantities(_pier_building(), objects, default_material_library()).model_dump()
    rows = {r["detail"]: float(r["quantity"]) for r in _rows(data)}
    s = float(hoop["spacing"])
    count = sum(math.floor((clear + 600) / s + 1e-9) + 1 for clear in (2200, 2100))
    one = 2 * (250 - 50 + 20 * hoop["dia"]) + 2 * (800 - 50 + 20 * hoop["dia"])
    expected = count * one / 1000 * W.bar_area(hoop["dia"]) * 7.85e-3
    assert rows["pier hoops"] == pytest.approx(expected, rel=0.01)
    texts = {
        "bim": _pier_building().model_dump_json(),
        "objects": objects.model_dump_json(),
        "materials": default_material_library().model_dump_json(),
    }
    (detailed,) = [e for e in detailing_model(texts=texts)["elements"] if e["id"] == "W1"]
    hoops = [b for b in detailed["bars"] if b["mark"].split("-")[1].startswith("Q")]
    assert sum(b["count"] for b in hoops) == count


def test_coupling_proposal_adds_longitudinal_bars_for_the_hoop_legs() -> None:
    """8.3.6.7(d)(iv): the hoops' 7 legs down a 1000 mm spandrel need a longitudinal bar of each
    face at each: the wall's Ø10 @ 200 give 5, so the proposal adds Ø10 @ 150 along each face
    (the sample W250's); the bill measures them."""
    web = W.WallBars(25, 10, 200, 10, 200, 2)
    spandrel = {
        "id": "W1/L1/S1", "wall": "W1", "type": "W250", "ln": 1000.0, "h": 1000.0, "bw": 250.0,
        "vu": 30e3, "combination": EQ, "fc": 24.1, "fy": 420.0, "cover": 25.0, "mode": "either",
        "piers": [1500.0, 800.0], "web": web, "asBeam": True, "ok": False,
    }  # fmt: skip
    current = {"count": 4, "dia": 16, "hoop": {"dia": 10, "spacing": 75, "legsAcross": 7,
                                               "legsAlong": 2}}  # fmt: skip
    proposed, notes = wall_design.coupling_proposal([spandrel], current, web)
    # The type's 7 legs fail with the web's bars: the proposal's own hoops (Ø10 @ 75, 6 legs
    # down 950 mm, 190 mm apart) with a bar of each face at each leg: Ø10 @ 175 (190 rounded
    # down to the 25 mm step), 6 per face.
    assert proposed is not None
    assert proposed["hoop"] == {"dia": 10.0, "spacing": 75.0, "legsAcross": 6, "legsAlong": 2}
    assert proposed["longitudinal"] == {"dia": 10.0, "spacing": 175.0}
    assert W.bars_down(950, 175) >= 6
    assert "along each face" in notes[0] and len(notes) == 1  # nothing left failing
    # With the sample's Ø10 @ 150 along each face, the type's own hoops are kept.
    sample = {**current, "longitudinal": {"dia": 10, "spacing": 150}}
    kept, _ = wall_design.coupling_proposal([spandrel], sample, web)
    assert kept is not None and kept["hoop"]["legsAcross"] == 7
    assert kept["longitudinal"] == {"dia": 10.0, "spacing": 150.0}


def _rows(data):
    if isinstance(data, dict):
        if "detail" in data and "quantity" in data:
            yield data
        for v in data.values():
            yield from _rows(v)
    elif isinstance(data, list):
        for v in data:
            yield from _rows(v)

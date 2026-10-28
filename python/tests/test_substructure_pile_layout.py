"""Part 9 piles placed in plan: the pile grid, piles with their own positions, pile caps formed
over them (eccentric to their columns), the upgrade of the earlier per-cap offsets, the layout
warnings, and the pile layout plan and cap schedule of the drawings. Pile loads by hand."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from saengine.drawings.sheets import DrawingSettings, build_sheets
from saengine.drawings.sheets.model import (
    Building,
    DrawingSet,
    PileGridPlan,
    PlanFooting,
    PlanPile,
)
from saengine.drawings.sheets.plans import pile_layout_plan
from saengine.drawings.sheets.project import pile_cap_schedule
from saengine.library.substructure import (
    Substructure,
    needs_upgrade,
    parse,
    pile_layout_warnings,
    upgrade_pile_caps,
)
from saengine.substructure.pilecap import CapSpec, pile_reactions
from saengine.substructure.shallow import ColumnBase

PILE = {"id": "BP500", "kind": "bored", "diameter": 500, "length": 18000, "material": "C24.1"}


def piled(**extra) -> dict:
    """Four piles on a pile grid of its own (origin 5100, -900; 1500 mm both ways) under a cap
    over them, whose column C2 at (6000, 0) stands 150 mm off the piles' centroid both ways."""
    grid = {
        "origin": [5100, -900],
        "x": [{"label": "a", "position": 0}, {"label": "b", "position": 1500}],
        "y": [{"label": "1", "position": 0}, {"label": "2", "position": 1500}],
    }
    points = [(5100, -900), (6600, -900), (6600, 600), (5100, 600)]
    return {
        "schema": "saengine.substructure/1",
        "foundations": [
            {"id": "PC1", "type": "pileCap", "columns": ["C2"], "center": [5850, -150],
             "length": 2300, "width": 2300, "thickness": 900, "material": "C24.1",
             "piles": ["PL1", "PL2", "PL3", "PL4"]},
        ],
        "pileTypes": [PILE],
        "pileGrid": grid,
        "piles": [
            {"id": f"PL{k + 1}", "type": "BP500", "position": list(p)}
            for k, p in enumerate(points)
        ],
        **extra,
    }  # fmt: skip


def test_eccentric_cap_pile_loads_by_hand() -> None:
    """Rigid cap, P/n ± M x/Σx² both ways: P = 1000 kN on C2, 150 mm off the piles' centroid in
    u and in v. Σu² = Σv² = 4 × 750² = 2.25e6 mm²; M = 1000 kN × 150 mm = 150 kN·m each way, so
    each pile takes 250 ± 150e6 × 750 / 2.25e6 ± the same = 250 ± 50 ± 50 kN: 150, 250, 350, 250
    for the piles at (-,-), (+,-), (+,+), (-,+)."""
    model = Substructure.model_validate(piled())
    cap = model.foundations[0]
    offsets = model.pile_offsets(cap)
    assert offsets == [[-750, -750], [750, -750], [750, 750], [-750, 750]]
    spec = CapSpec(
        id="PC1", length=2300, width=2300, thickness=900, cover=75, fc=24.1, fy=420,
        columns=[ColumnBase("C2", 6000 - 5850, 0 - -150, 400, 400)],
        piles=[tuple(p) for p in offsets], pile_diameter=500,
    )  # fmt: skip
    reactions, notes = pile_reactions(spec, [np.array([1000e3, 0.0, 0.0])])
    assert reactions / 1e3 == pytest.approx([150, 250, 350, 250])
    assert notes == [] and reactions.sum() == pytest.approx(1000e3)
    # A column moment adds to the eccentricity: Cv = 60 kN·m about v (the footing convention,
    # +Cv as +P u) gives ± 60e6 × 750 / 2.25e6 = ± 20 kN along u.
    with_moment, _ = pile_reactions(spec, [np.array([1000e3, 0.0, 60e6])])
    assert with_moment / 1e3 == pytest.approx([130, 270, 370, 230])
    # The same group under a rotated cap: offsets in the cap's axes.
    turned = Substructure.model_validate(
        piled() | {"foundations": [{**piled()["foundations"][0], "rotation": 90}]}
    )
    assert np.allclose(
        turned.pile_offsets(turned.foundations[0]),
        [[-750, 750], [-750, -750], [750, -750], [750, 750]],
    )


def test_earlier_caps_are_read_as_piles_in_plan() -> None:
    old = {
        "schema": "saengine.substructure/1",
        "foundations": [
            {"id": "PC1", "type": "pileCap", "columns": ["C1"], "center": [1000, 2000],
             "rotation": 90, "length": 2400, "width": 1000, "thickness": 800,
             "pileType": "BP500", "piles": [[-750, 0], [750, 0]]},
            {"id": "PC2", "type": "pileCap", "columns": ["C2"], "length": 2400, "width": 1000,
             "thickness": 800, "pileType": "BP500", "piles": [[-750, 0], [750, 0]]},
        ],
        "pileTypes": [PILE],
    }  # fmt: skip
    assert needs_upgrade(old) and not needs_upgrade(piled())
    with pytest.raises(ValueError, match="PC2: a pile cap of an earlier version without a centre"):
        upgrade_pile_caps(old)
    new = upgrade_pile_caps(old, {"C2": [6000, 0]})
    assert old["foundations"][0]["piles"] == [[-750, 0], [750, 0]]  # not changed in place
    # One representation: the caps list their piles, the piles carry the type and position.
    assert [f["piles"] for f in new["foundations"]] == [["PL1", "PL2"], ["PL3", "PL4"]]
    assert all("pileType" not in f for f in new["foundations"])
    assert new["foundations"][1]["center"] == [6000, 0]
    assert [p["position"] for p in new["piles"]] == [
        [1000, 1250], [1000, 2750], [5250, 0], [6750, 0]
    ]  # fmt: skip
    model = Substructure.model_validate(new)
    assert np.allclose(model.pile_offsets(model.foundations[0]), [[-750, 0], [750, 0]])
    # parse() with the building model places a cap without a centre at its columns.
    assert parse(json.dumps(old), _Building({"C2": (6000, 0)})).piles[3].position == [6750, 0]


class _Building:
    """A stand-in for a building model: columns at the given positions."""

    def __init__(self, columns: dict[str, tuple[float, float]]) -> None:
        self.elements = [
            type("Column", (), {"kind": "column", "id": k, "position": [*v, 0]})()
            for k, v in columns.items()
        ]


def test_layout_warnings() -> None:
    data = piled()
    assert pile_layout_warnings(Substructure.model_validate(data)) == []
    data["piles"] += [
        {"id": "PL5", "type": "BP500", "position": [5850, -150]},  # inside PC1, not its pile
        {"id": "PL6", "type": "BP500", "position": [9000, 0]},  # under no cap
        {"id": "PL7", "type": "BP500", "position": [9300, 0]},  # overlapping PL6
        {"id": "PL8", "type": "BP500", "position": [9000, 1000]},  # 1000 < 1250 from PL6
    ]
    data["piles"][1]["position"] = [6900, -900]  # PL2 pokes out of PC1
    warnings = pile_layout_warnings(Substructure.model_validate(data))
    assert "PL2: not wholly within its pile cap PC1" in warnings
    assert "PL5: inside the outline of PC1 but not one of its piles" in warnings
    assert "PL6: under no pile cap" in warnings
    assert any(
        w.startswith("PL6 and PL7 overlap: their centres are 300 mm apart") for w in warnings
    )
    assert any(w.startswith("PL6 and PL8 are 1000 mm apart, less than 1250 mm") for w in warnings)


def test_pile_layout_plan_and_cap_schedule() -> None:
    model = Substructure.model_validate(
        piled(piles=[*piled()["piles"], {"id": "PL5", "type": "BP500", "position": [9000, 0]}])
    )
    schedule = pile_cap_schedule(model)
    assert schedule is not None and schedule.title == "Pile cap schedule"
    assert schedule.rows[0][:5] == [
        "PC1", "2300 x 2300 x 900", "4", "PL1, PL2, PL3, PL4", "BP500: 500 x 18000"
    ]  # fmt: skip
    assert schedule.notes == ["Piles under no cap: PL5."]
    outline = [(4700.0, -1300.0), (7000.0, -1300.0), (7000.0, 1000.0), (4700.0, 1000.0)]
    building = Building(
        footings=[PlanFooting("PC1", "PC1", outline, -600.0, [((5100, -900), 500.0)])],
        piles=[PlanPile(p.id, tuple(p.position), 500.0, "PC1") for p in model.piles],
        pile_grid=PileGridPlan((5100, -900), 0.0),
    )
    assert pile_layout_plan(Building()) is None
    spec = pile_layout_plan(building)
    assert spec is not None and spec.title == "Pile layout plan"
    data = DrawingSet(building=building, pile_caps=schedule)
    sheets = build_sheets(data, DrawingSettings())
    titles = [v.spec.title for s in sheets for v in s.views]
    assert "Pile layout plan" in titles
    assert any(t.startswith("Pile cap schedule") for t in titles)
    # The marks are on the plan.
    plan = next(s for s in sheets if any(v.spec.title == "Pile layout plan" for v in s.views))
    texts = {e.dxf.text for e in plan.doc.modelspace().query("TEXT MTEXT") if e.dxftype() == "TEXT"}
    assert {"PL1", "PL5", "PC1"} <= texts
    assert math.isfinite(spec.scale)

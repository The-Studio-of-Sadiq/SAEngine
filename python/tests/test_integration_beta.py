"""Integrator glue of the "structural office beta" round: the New Building generator behind the
RPC and the command line, punching shear reinforcement wired into the flat slab and footing
designs (checked when given, proposed and applied otherwise), and lintels in the bill of
quantities. Synthetic data only."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from saengine.boq.quantities import bill_of_quantities
from saengine.cli.main import main as cli_main
from saengine.design import slab
from saengine.design.proposal import _with_punching, apply_proposal, punching_layout
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import BuildingModel
from saengine.library.objects import BarMesh, PlanarReinforcement, PunchingReinforcement
from saengine.library.settings import Foundation
from saengine.project.new_building import NewBuildingError, create_building, spec_from_wizard
from saengine.rpc import handlers
from saengine.substructure.shallow import ColumnBase, FootingSpec, design_footing

KN = 1e3

WIZARD = {
    "schema": "saengine.newBuilding/1",
    "name": "Grid Test",
    "grids": {"x": [], "y": []},
    "spacings": {"x": [6000, 6000, 6000], "y": [5000, 5000]},
    "stories": [{"id": "BASE", "name": "Base", "elevation": 0}]
    + [
        {"id": f"L{i}", "name": f"Level {i}", "elevation": 3600 + 3200 * (i - 1)}
        for i in range(1, 7)
    ],
    "storyHeights": [3600, 3200, 3200, 3200, 3200, 3200],
    "system": "rcFrameCore",
    "materials": {"concrete": "C27.6", "rebar": "B500DWR"},
    "footing": "combined",
    "site": {"location": "dhaka"},
    "occupancy": {"use": "office", "category": "II"},
    "designCode": "bnbc",
}


# ─────────────────────────────────────── New Building ───────────────────────────────────────


def test_wizard_spec_maps_to_the_generator() -> None:
    spec, notes = spec_from_wizard(WIZARD)
    assert spec["gridsX"] == [6000, 6000, 6000] and spec["gridsY"] == [5000, 5000]
    assert spec["stories"][0] == {"name": "Level 1", "height": 3600}
    assert len(spec["stories"]) == 6
    assert spec["system"] == "rcFrameWithWalls" and spec["footing"] == "isolated"
    assert (spec["concrete"], spec["rebar"]) == ("C27.6", "B500DWR")
    assert (spec["location"], spec["occupancy"], spec["occupancyCategory"]) == (
        "dhaka",
        "office",
        "II",
    )
    assert any("Combined footings are not generated" in n for n in notes)
    # The generator's own spec passes through.
    assert spec_from_wizard({"name": "X", "gridsX": [5000]}) == (
        {"name": "X", "gridsX": [5000]},
        [],
    )


def test_create_building_writes_a_project_and_refuses_a_full_folder(tmp_path: Path) -> None:
    result = create_building(WIZARD, tmp_path)
    root = Path(result["root"])
    assert root == tmp_path / "Grid Test"
    manifest = json.loads((root / "Grid Test.saengine").read_text(encoding="utf-8"))
    assert manifest["type"] == "building"
    for relative in (
        "02 Project Settings/project-settings.json",
        "04 Objects/objects.json",
        "05 Floor Plan/floor-plan.json",
        "06 BIM/bim.json",
        "09 Substructure/substructure.json",
        "01 Soil Report/soil-report.json",
        "07 MEP/mep.json",
        "10 BOQ/boq.json",
    ):
        assert (root / relative).is_file(), relative
    assert (root / "08 FEM").is_dir() and (root / "11 Exports").is_dir()
    plan = json.loads((root / "05 Floor Plan/floor-plan.json").read_text(encoding="utf-8"))
    assert len(plan["stories"]) == 7 and plan["walls"]  # the core walls
    assert any("Combined footings" in n for n in result["notes"])
    with pytest.raises(NewBuildingError, match="not empty"):
        create_building(WIZARD, tmp_path)
    # The RPC answers an error instead of raising.
    answer = handlers.new_building(WIZARD, str(tmp_path))
    assert "not empty" in answer["error"]
    bad = handlers.new_building(
        {**WIZARD, "name": "Bad", "materials": {"concrete": "B500DWR"}}, str(tmp_path)
    )
    assert "is not a concrete" in bad["error"]


def test_cli_new_building(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {"name": "CLI Frame", "gridsX": [5000, 5000], "gridsY": [4000], "storyCount": 3}
        ),
        encoding="utf-8",
    )
    code = cli_main(["new-building", str(spec), str(tmp_path / "out"), "--json", "-q"])
    document = json.loads(capsys.readouterr().out)
    assert code == 0 and document["newBuilding"]["name"] == "CLI Frame"
    assert (tmp_path / "out" / "CLI Frame" / "CLI Frame.saengine").is_file()
    assert document["newBuilding"]["summary"]["counts"]["columns"] == 6 * 3
    # A relative DEST is taken from the current folder (the app's wizard refuses one, N2).
    monkeypatch.chdir(tmp_path)
    code = cli_main(["new-building", str(spec), "rel", "--name", "Rel", "--json", "-q"])
    capsys.readouterr()
    assert code == 0 and (tmp_path / "rel" / "Rel" / "Rel.saengine").is_file()


# ─────────────────────────────────────── punching ───────────────────────────────────────


def _flat_context(force: float, given: PunchingReinforcement | None = None):
    column = slab.ColumnJoint(
        "C1",
        (0.0, 0.0),
        500.0,
        500.0,
        0.0,
        forces=[np.array([0.0, 0.0, -force])],
        moments=[np.zeros(3)],
    )
    context = slab.SlabContext(
        boundary=[(-4000.0, -4000.0), (4000.0, -4000.0), (4000.0, 4000.0), (-4000.0, 4000.0)],
        columns=[column],
    )
    context.punching = given
    bars = PlanarReinforcement(
        material="B420DWR",
        cover=20,
        bottomX=BarMesh(dia=12, spacing=150),
        bottomY=BarMesh(dia=12, spacing=150),
        topX=BarMesh(dia=16, spacing=150),
        topY=BarMesh(dia=16, spacing=150),
    )
    return slab.layers_of(bars, 250.0), context


def test_flat_slab_punching_proposes_studs_and_checks_given_ones() -> None:
    layers, context = _flat_context(600 * KN)
    (plain,) = slab._punching_checks(layers, 30.0, ["1.2D + 1.6L"], context, h=250.0)
    assert plain["ok"] and "shearReinforcement" not in plain  # concrete alone: unchanged

    layers, context = _flat_context(1500 * KN)
    (row,) = slab._punching_checks(layers, 30.0, ["1.2D + 1.6L"], context, h=250.0)
    studs = row["shearReinforcement"]
    assert row["ok"] and studs["kind"] == "studs" and studs["lines"] >= 1
    layout, thicken, uncovered = punching_layout([row])
    assert thicken == [] and uncovered == [] and layout["perLine"] == studs["perLine"]

    # The proposed layout given on the type passes; one line of small studs does not.
    given = PunchingReinforcement.model_validate(layout)
    layers, context = _flat_context(1500 * KN, given)
    (again,) = slab._punching_checks(layers, 30.0, ["1.2D + 1.6L"], context, h=250.0)
    assert again["ok"]
    weak = PunchingReinforcement(dia=10, perLine=8, lines=1, firstLine=50, spacing=100)
    layers, context = _flat_context(1500 * KN, weak)
    (short,) = slab._punching_checks(layers, 30.0, ["1.2D + 1.6L"], context, h=250.0)
    assert not short["ok"] and short["utilisation"] > 1
    # A failing given layout gets a fresh proposal, not itself back (review: weak.py).
    fresh = short["proposedReinforcement"]
    assert fresh is not None and fresh["lines"] > 1
    entry: dict = {}
    _with_punching(entry, [short])
    assert entry["punching"]["proposed"] != weak.model_dump(exclude_none=True)
    assert any("given studs or stirrups are not enough" in n for n in entry["notes"])
    given = PunchingReinforcement.model_validate(entry["punching"]["proposed"])
    layers, context = _flat_context(1500 * KN, given)
    (fixed,) = slab._punching_checks(layers, 30.0, ["1.2D + 1.6L"], context, h=250.0)
    assert fixed["ok"]


def _two_columns(va: float, vb: float, given: PunchingReinforcement | None = None):
    """The reviewer's combo.py: one flat slab, d = 210, a corner column A and an interior B."""
    columns = [
        slab.ColumnJoint(
            name,
            centre,
            500.0,
            500.0,
            0.0,
            forces=[np.array([0.0, 0.0, -v])],
            moments=[np.zeros(3)],
        )
        for name, centre, v in (("A", (-3750.0, -3750.0), va), ("B", (2000.0, 2000.0), vb))
    ]
    context = slab.SlabContext(
        boundary=[(-4000.0, -4000.0), (8000.0, -4000.0), (8000.0, 8000.0), (-4000.0, 8000.0)],
        columns=columns,
    )
    context.punching = given
    bars = PlanarReinforcement(
        material="B420DWR",
        cover=20,
        bottomX=BarMesh(dia=12, spacing=150),
        bottomY=BarMesh(dia=12, spacing=150),
        topX=BarMesh(dia=20, spacing=150),
        topY=BarMesh(dia=20, spacing=150),
    )
    return slab._punching_checks(
        slab.layers_of(bars, 250.0), 30.0, ["1.2D + 1.6L"], context, h=250.0
    )


@pytest.mark.parametrize(("va", "vb"), [(400, 1250), (450, 1250), (500, 1500)])
def test_one_layout_for_a_slab_type_passes_at_every_column(va: float, vb: float) -> None:
    rows = _two_columns(va * KN, vb * KN)
    own = [r["shearReinforcement"] for r in rows if r.get("shearReinforcement")]
    assert len(own) == 2  # both columns need studs
    layout, thicken, uncovered = punching_layout(rows)
    assert layout is not None and thicken == [] and uncovered == []
    reach = max(r["s0"] + (r["lines"] - 1) * r["s"] for r in own)
    assert layout["firstLine"] + (layout["lines"] - 1) * layout["spacing"] >= reach - 1e-6
    # Given back on the type, the shared layout passes at both columns.
    given = PunchingReinforcement.model_validate(layout)
    assert all(r["ok"] for r in _two_columns(va * KN, vb * KN, given))
    # Without the re-check (plain rows), the merge alone still reaches every column's extent.
    plain = [dict(r) for r in rows]
    alone, _, _ = punching_layout(plain)
    assert alone is not None and alone["lines"] >= 1
    given = PunchingReinforcement.model_validate(alone)
    assert all(r["ok"] for r in _two_columns(va * KN, vb * KN, given))


def _footing(**changes: object) -> FootingSpec:
    values: dict = {
        "id": "F1",
        "type": "F18",
        "footing_type": "isolated",
        "length": 2400,
        "width": 2400,
        "thickness": 500,
        "elevation": -1000,
        "cover": 75,
        "fc": 25,
        "fy": 420,
        "columns": [ColumnBase("C1", 0, 0, 400, 400, 1500)],
        "bottom_x": BarMesh(dia=16, spacing=125),
        "bottom_y": BarMesh(dia=16, spacing=125),
    }
    values.update(changes)
    return FootingSpec(**values)


def test_footing_punching_with_reinforcement() -> None:
    loads = {"1.2D + 1.6L": [np.array([3200 * KN, 0.0, 0.0])]}
    checks = {c["name"]: c for c in design_footing(_footing(), {}, loads, Foundation())[0]}
    row = checks["Punching at C1"]
    assert row["ok"] and row["shearReinforcement"]["lines"] >= 1
    layout, _, _ = punching_layout([row])
    given = PunchingReinforcement.model_validate(layout)
    checks = {
        c["name"]: c
        for c in design_footing(_footing(punching_reinforcement=given), {}, loads, Foundation())[0]
    }
    assert checks["Punching at C1"]["ok"]
    # A failing given layout: re-proposed, and the proposal re-checked at the column.
    weak = PunchingReinforcement(dia=10, perLine=8, lines=1, firstLine=50, spacing=100)
    checks = {
        c["name"]: c
        for c in design_footing(_footing(punching_reinforcement=weak), {}, loads, Foundation())[0]
    }
    short = checks["Punching at C1"]
    assert not short["ok"] and short["proposedReinforcement"] is not None
    layout, thicken, uncovered = punching_layout([short])
    assert layout is not None and thicken == [] and uncovered == []
    assert short.recheck(layout)["ok"]
    light = {"1.2D + 1.6L": [np.array([900 * KN, 0.0, 0.0])]}
    plain = {c["name"]: c for c in design_footing(_footing(), {}, light, Foundation())[0]}
    assert plain["Punching at C1"]["ok"] and "shearReinforcement" not in plain["Punching at C1"]


def test_apply_proposal_writes_the_punching_reinforcement() -> None:
    objects = {
        "objects": [
            {
                "id": "S250",
                "name": "Flat slab 250",
                "kind": "slab",
                "material": "C24.1",
                "thickness": 250,
                "system": "flat",
            }
        ]
    }
    layout = {
        "kind": "studs",
        "dia": 12.0,
        "perLine": 12,
        "lines": 5,
        "firstLine": 80.0,
        "spacing": 150.0,
    }
    proposal = {
        "types": [
            {
                "type": "S250",
                "kind": "slab",
                "proposed": {
                    "material": "B420DWR",
                    "cover": 20,
                    "bottomX": {"dia": 10, "spacing": 150},
                    "text": "Ø10@150",
                },
                "current": None,
                "punching": {"proposed": layout, "text": "studs"},
            }
        ],
        "newTypes": [],
        "reassign": [],
        "foundations": [],
    }
    result = apply_proposal(json.dumps(objects), "{}", proposal)
    target = json.loads(result["objectsText"])["objects"][0]
    assert target["punchingReinforcement"] == layout
    assert any(c["what"] == "punching reinforcement" for c in result["changes"])
    ObjectLibrary.model_validate(json.loads(result["objectsText"]))
    # Old files stay valid: the field is optional.
    assert ObjectLibrary.model_validate(objects).objects[0].punchingReinforcement is None


# ─────────────────────────────────────── lintels in the BOQ ───────────────────────────────────


def test_lintels_and_their_bars_are_measured() -> None:
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "BW250",
                    "name": "Brick wall 250",
                    "kind": "wall",
                    "material": "BRICK-1",
                    "thickness": 250,
                    "structural": False,
                }
            ]
        }
    )
    building = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
            ],
            "elements": [
                {
                    "id": "W1",
                    "type": "BW250",
                    "kind": "wall",
                    "start": [0, 0],
                    "end": [5000, 0],
                    "bottom": 0,
                    "top": 3000,
                }
            ],
            "additions": {
                "wallOpenings": [
                    {
                        "id": "D1",
                        "host": "W1",
                        "offset": 1000,
                        "sill": 0,
                        "width": 1000,
                        "height": 2100,
                    }
                ]
            },
        }
    )
    bill = bill_of_quantities(building, objects, default_material_library())
    concrete = [i for i in bill.items if i.kind == "lintel" and i.unit == "m3"]
    assert len(concrete) == 1
    # 250 wide, 150 deep (L/16 x 1.0 at fy 420, at least 150), over 1000 + 2 x 150 mm.
    assert concrete[0].quantity == pytest.approx(
        0.25 * 0.15 * 1.3, abs=6e-4
    )  # the bill rounds to 3 decimals
    bars = [
        b
        for i in bill.items
        if i.group == "reinforcement"
        for b in i.breakdown
        if b.element == "D1"
    ]
    assert bars and all(math.isfinite(b.quantity) and b.quantity > 0 for b in bars)
    assert any(n.startswith("Lintels: 1 over openings") for n in bill.notes)


def test_no_shared_layout_is_proposed_when_a_column_still_fails() -> None:
    from saengine.design.punching import PunchingRow

    row = PunchingRow(
        name="Punching at C7",
        ok=True,
        shearReinforcement={"kind": "studs", "bar": 12.0, "perLine": 8, "lines": 3, "s0": 80.0,
                            "s": 120.0, "fyt": 350.0},
    )  # fmt: skip
    row.recheck = lambda layout: {"ok": False}
    layout, thicken, uncovered = punching_layout([row])
    assert layout is None and thicken == [] and uncovered == ["C7"]
    entry: dict = {}
    _with_punching(entry, [row])
    assert "punching" not in entry
    assert any("C7" in n and "none is proposed" in n for n in entry["notes"])

"""Part 9 takes the foundations over from Part 8: the hand-over of the footings drawn in the
building model, the design report without footings, and the foundations of 9 Substructure in
the bill of quantities, the IFC, the RPC handlers, the printed report and the shipped sample.
All data is synthetic; the expected quantities are worked by hand in the comments."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import ifcopenshell
import pytest
from test_design_footing import CORNERS, OBJECTS_WITH_FOOTINGS, footing, frame, with_footings
from test_fem_derive import PLAN, SETTINGS

from saengine.boq import compute_boq
from saengine.design.check import DESIGNED_IN_PART_9, design
from saengine.design.footing import footing_checks
from saengine.library import default_material_library
from saengine.library.bim import (
    BuildingModel,
    foundation_solids,
    generate,
    ground_level_stamp,
    source_stamp,
)
from saengine.library.ifc import export_ifc
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import Foundation
from saengine.library.substructure import SUBSTRUCTURE_FILE, Substructure
from saengine.rpc import handlers
from saengine.substructure import substructure_report
from saengine.substructure.handover import (
    authoritative_substructure,
    ensure_migrated,
    needs_migration,
    substructure_text,
)

__all__ = ["frame"]  # the analysed one-bay frame of test_design_footing, used as a fixture

PLACEHOLDER = '{\n\t"schema": 1,\n\t"part": "substructure"\n}\n'
SAMPLE = Path(__file__).parents[2] / "workbench/resources/saengine/samples/Sample Frame"

#: A rectangular tie beam type, 250 x 400 with 3 + 3 T16 and T10 stirrups at 150.
TIE_BEAM = {
    "id": "TB",
    "name": "Tie beam 250x400",
    "kind": "beam",
    "material": "C24.1",
    "profile": {"shape": "rectangle", "xDim": 250, "yDim": 400},
    "reinforcement": {
        "material": "B420DWR",
        "cover": 40,
        "longitudinal": [
            {"position": "bottom", "count": 3, "dia": 16},
            {"position": "top", "count": 3, "dia": 16},
        ],
        "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
    },
}
OBJECTS = ObjectLibrary.model_validate(
    {"objects": [*OBJECTS_WITH_FOOTINGS.model_dump(mode="json")["objects"], TIE_BEAM]}
)
SETTINGS_150 = SETTINGS.model_copy(update={"foundation": Foundation(allowableBearing=150)})
MESH = {"dia": 12, "spacing": 200}


def _project(root: Path, building: BuildingModel, substructure: str = PLACEHOLDER) -> Path:
    files = {
        "02 Project Settings/project-settings.json": SETTINGS_150.model_dump_json(by_alias=True),
        "03 Materials/materials.json": default_material_library().model_dump_json(by_alias=True),
        "04 Objects/objects.json": OBJECTS.model_dump_json(by_alias=True),
        "06 BIM/bim.json": building.model_dump_json(by_alias=True),
        SUBSTRUCTURE_FILE: substructure,
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _analysed(root: Path, frame: tuple[dict, Path]) -> Path:
    project, out = frame
    model = root / "08 FEM" / "model.osmodel"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps(project), encoding="utf-8")
    shutil.copytree(out, root / "08 FEM" / "model.results")
    return root


def _drawn() -> BuildingModel:
    """The one-bay frame with an isolated footing F18 (1.8 x 1.8 x 0.5 m, top at -1.0 m) under
    each column, drawn in the building model as before Part 9."""
    return with_footings(*(footing(f"F{i + 1}", "F18", x, y) for i, (x, y) in enumerate(CORNERS)))


# ─────────────────────────────── the hand-over ───────────────────────────────


def test_only_a_real_substructure_is_the_source_of_the_foundations() -> None:
    assert authoritative_substructure(None) is None
    assert authoritative_substructure("  ") is None
    assert authoritative_substructure(PLACEHOLDER) is None
    empty = authoritative_substructure('{"schema": "saengine.substructure/1"}')
    assert isinstance(empty, Substructure) and empty.foundations == []
    with pytest.raises(ValueError):
        authoritative_substructure('{"schema": "saengine.substructure/1", "foundations": [1]}')


def test_footings_move_into_a_placeholder_substructure_once(tmp_path: Path) -> None:
    root = _project(tmp_path, _drawn())
    assert needs_migration(root)
    first = ensure_migrated(root)
    assert first["migrated"] and first["count"] == 4
    saved = json.loads((root / SUBSTRUCTURE_FILE).read_text(encoding="utf-8"))
    f1 = saved["foundations"][0]
    # The footing's underside: its top at -1000 less its 500 thickness; whole numbers as ints.
    assert (f1["id"], f1["type"], f1["columns"], f1["foundingLevel"]) == (
        "F1",
        "isolated",
        ["C1"],
        -1500,
    )
    assert isinstance(f1["length"], int)
    # Nothing more to do now, and the building model keeps its footings (nothing is lost).
    assert not needs_migration(root)
    assert ensure_migrated(root) == {"migrated": False, "count": 0, "notes": []}
    building = BuildingModel.model_validate_json((root / "06 BIM/bim.json").read_text("utf-8"))
    assert sum(e.kind == "footing" for e in building.elements) == 4


def test_a_project_without_footings_or_with_an_invalid_file_is_left_alone(tmp_path: Path) -> None:
    bare = _project(tmp_path / "bare", generate(PLAN, "s"))
    assert not needs_migration(bare) and not ensure_migrated(bare)["migrated"]
    assert (bare / SUBSTRUCTURE_FILE).read_text(encoding="utf-8") == PLACEHOLDER
    broken = _project(tmp_path / "broken", _drawn(), "{ not json")
    assert not ensure_migrated(broken)["migrated"]
    assert (broken / SUBSTRUCTURE_FILE).read_text(encoding="utf-8") == "{ not json"


def test_part_8_no_longer_designs_footings_and_part_9_designs_them_alike(
    frame: tuple[dict, Path], tmp_path: Path
) -> None:
    project, out = frame
    building = _drawn()
    materials = default_material_library()
    report = design(project, out, building, OBJECTS, materials, SETTINGS_150)
    assert all(e["kind"] != "footing" for e in report["elements"])
    assert DESIGNED_IN_PART_9 in report["notes"]

    # The same footings in Part 9, moved there by the hand-over, check as Part 8 checked them.
    old, _, _ = footing_checks(project, out, building, OBJECTS, materials, SETTINGS_150)
    root = _analysed(_project(tmp_path, building), frame)
    ensure_migrated(root)
    new = {f["id"]: f for f in substructure_report(root)["foundations"]}
    for element in old:
        checks = {c["name"]: c for c in new[element["id"]]["checks"]}
        bearing = next(c for c in element["checks"] if c["name"].startswith("Bearing"))
        assert checks[bearing["name"]]["demand"] == pytest.approx(bearing["demand"], rel=1e-6)
        assert new[element["id"]]["utilisation"] == pytest.approx(element["utilisation"], rel=1e-3)


# ─────────────────────────────── bill of quantities ───────────────────────────────


def _substructure(**extra) -> dict:
    """F1 2.0 x 1.5 x 0.5 m under C1 at (0, 0) founding at -1.5 m; F2 the same at (6000, 0);
    a tie beam TB1 between them."""
    footing = {
        "type": "isolated",
        "length": 2000,
        "width": 1500,
        "thickness": 500,
        "foundingLevel": -1500,
        "material": "C24.1",
        "reinforcement": {"material": "B420DWR", "cover": 75, "bottomX": MESH, "bottomY": MESH},
    }
    return {
        "schema": "saengine.substructure/1",
        "foundations": [
            {"id": "F1", "columns": ["C1"], "center": [0, 0], **footing},
            {"id": "F2", "columns": ["C2"], "center": [6000, 0], **footing},
        ],
        "tieBeams": [{"id": "TB1", "from": "F1", "to": "F2", "type": "TB", "level": -1000}],
        **extra,
    }


def _bill(building: BuildingModel, substructure: dict | str | None, settings=SETTINGS_150) -> dict:
    text = substructure if isinstance(substructure, str | None) else json.dumps(substructure)
    return compute_boq(
        building.model_dump_json(by_alias=True),
        OBJECTS.model_dump_json(by_alias=True),
        default_material_library().model_dump_json(by_alias=True),
        text,
        settings.model_dump_json(by_alias=True) if settings else None,
    )


def _item(bill: dict, kind: str, group: str | None = None) -> dict:
    return next(i for i in bill["items"] if i.get("kind") == kind and group in (None, i["group"]))


def _share(item: dict, element: str, detail: str | None = None) -> float:
    return sum(
        b["quantity"]
        for b in item["breakdown"]
        if b["element"] == element and detail in (None, b.get("detail"))
    )


def test_bill_measures_the_substructure_with_its_earthwork() -> None:
    bill = _bill(_drawn(), _substructure())
    # The footings drawn in the building model are not measured any more.
    assert _share(_item(bill, "footing", "concrete"), "F3") == 0
    assert any(
        n.startswith("Footings drawn in the building model (F1, F2, F3, F4)") for n in bill["notes"]
    )
    footings = _item(bill, "footing", "concrete")
    assert footings["quantity"] == pytest.approx(2 * 2.0 * 1.5 * 0.5)
    assert _item(bill, "footing", "formwork")["quantity"] == pytest.approx(2 * 7.0 * 0.5)
    # T12 at 200 both ways: 3 m² / 0.2 m of bar per layer, 0.889 kg/m (144/162).
    t12 = next(i for i in bill["items"] if i["group"] == "reinforcement" and i["diameter"] == 12)
    assert _share(t12, "F1", "bottom X") == pytest.approx(3.0 / 0.2 * 144 / 162, abs=1e-3)

    # Tie beam: centres 6 m apart, clear between the footings' faces 6 - 2 x 1.0 = 4 m.
    tie = _item(bill, "tieBeam", "concrete")
    assert tie["quantity"] == pytest.approx(0.25 * 0.4 * 4.0)
    assert _item(bill, "tieBeam", "formwork")["quantity"] == pytest.approx(2 * 0.4 * 4.0)
    t16 = next(i for i in bill["items"] if i["group"] == "reinforcement" and i["diameter"] == 16)
    assert _share(t16, "TB1") == pytest.approx(6 * 6.0 * 256 / 162, abs=1e-3)  # centre to centre

    # Blinding 75 mm, 75 mm beyond the edges: 2.15 x 1.65 per footing, 4.15 x 0.40 under the tie.
    blinding = _item(bill, "blinding", "concrete")
    assert _share(blinding, "F1") == pytest.approx(2.15 * 1.65 * 0.075, abs=1e-3)
    assert _share(blinding, "TB1") == pytest.approx(4.15 * 0.40 * 0.075, abs=1e-3)
    assert blinding["material"] is None if "material" in blinding else True

    # Excavation: pits 300 mm beyond the edges, from the ground (0) to the blinding's underside.
    # Footings 2.6 x 2.1 down to -1.575 m; the tie beam's trench x 0.7..5.3 m, 0.85 m wide,
    # down to -1.475 m (its underside -1.4 m less 75), overlapping each footing's pit
    # (x up to 1.3 m) by 0.6 x 0.85 m over the trench's depth.
    pit = 2.6 * 2.1 * 1.575
    trench = 4.6 * 0.85 * 1.475
    overlap = 2 * 0.6 * 0.85 * 1.475
    excavation = _item(bill, "excavation", "earthwork")
    assert excavation["quantity"] == pytest.approx(2 * pit + trench - overlap, abs=2e-3)
    # Backfill: the excavation less the concrete and blinding below the ground.
    solids = 2 * 1.5 + 0.25 * 0.4 * 4.0 + blinding["quantity"]
    backfill = _item(bill, "backfill", "earthwork")
    assert backfill["quantity"] == pytest.approx(excavation["quantity"] - solids, abs=3e-3)
    assert bill["items"][0]["code"] == "E.01"
    # The sources: the substructure always, the settings when foundations were measured.
    assert set(bill["source"]) == {"bim", "objects", "materials", "substructure", "settings"}
    # Of the settings only the ground level is recorded: another qa leaves the stamp alone.
    assert bill["source"]["settings"] == ground_level_stamp(0.0)
    other_qa = SETTINGS_150.model_copy(
        update={"foundation": SETTINGS_150.foundation.model_copy(update={"allowableBearing": 400})}
    )
    assert _bill(_drawn(), _substructure(), other_qa)["source"] == bill["source"]


def test_ground_level_stamp_matches_the_workbench() -> None:
    # The same values as groundLevelStamp in partSources.ts (boqDocument.test.ts pins them).
    assert ground_level_stamp(-150.0) == "eb7f0d0d5faa4ccf9f9d13fbdda0529448065fda"
    assert ground_level_stamp(0.0) == ground_level_stamp(0) == source_stamp("groundLevel=0")
    assert ground_level_stamp(-150.0004) == ground_level_stamp(-150.0)
    assert ground_level_stamp(-150.001) != ground_level_stamp(-150.0)


def test_piles_and_rafts_and_a_deeper_ground() -> None:
    bored = {"id": "P1", "kind": "bored", "diameter": 500, "length": 10000, "material": "C24.1"}
    driven = {
        "id": "P2",
        "kind": "driven",
        "diameter": 400,
        "length": 12000,
        "material": "C24.1",
        "reinforcement": {
            "material": "B420DWR",
            "cover": 50,
            "longitudinal": [{"position": "perimeter", "count": 4, "dia": 20}],
        },
    }
    cap = {"type": "pileCap", "length": 2500, "width": 1000, "thickness": 800, "material": "C24.1"}
    substructure = {
        "schema": "saengine.substructure/1",
        "foundations": [
            {"id": "PC1", "columns": ["C1"], **cap, "pileType": "P1",
             "piles": [[-750, 0], [750, 0]]},
            {"id": "PC2", "columns": ["C2"], **cap, "center": [6000, 0], "pileType": "P2",
             "piles": [[-750, 0], [750, 0]]},
            {"id": "R1", "type": "raft", "columns": ["C3", "C4"], "thickness": 600,
             "material": "C24.1", "foundingLevel": -1000,
             "outline": [[-1000, 4000], [7000, 4000], [7000, 6000], [-1000, 6000]]},
        ],
        "pileTypes": [bored, driven],
    }  # fmt: skip
    ground = SETTINGS_150.model_copy(update={"foundation": Foundation(groundLevel=500)})
    bill = _bill(generate(PLAN, "s"), substructure, ground)
    piles = _item(bill, "pile", "concrete")
    assert _share(piles, "PC1") == pytest.approx(2 * math.pi * 0.25**2 * 10, rel=2e-3)
    assert _share(piles, "PC2") == pytest.approx(2 * 0.4 * 0.4 * 12, abs=1e-3)  # square
    assert _item(bill, "pile", "formwork")["quantity"] == pytest.approx(2 * 3 * 0.4 * 12)
    # 4 T20 per pile, 12 m: one stock length each, no lap.
    t20 = next(i for i in bill["items"] if i["group"] == "reinforcement" and i["diameter"] == 20)
    assert _share(t20, "PC2") == pytest.approx(2 * 4 * 12 * 400 / 162, abs=1e-3)
    assert any(n.startswith("PC1/1: pile type 'P1' has no reinforcement") for n in bill["notes"])
    assert _item(bill, "raft", "concrete")["quantity"] == pytest.approx(8 * 2 * 0.6)
    # Ground at +0.5 m: the caps (no founding level: 1.5 m below it, at -1.0 m) and the raft
    # (at -1.0 m) are dug 1.575 m deep: 3.1 x 1.6 per cap, 8.6 x 2.6 for the raft.
    excavation = _item(bill, "excavation", "earthwork")
    assert _share(excavation, "PC1") == pytest.approx(3.1 * 1.6 * 1.575, abs=2e-3)
    assert _share(excavation, "R1") == pytest.approx(8.6 * 2.6 * 1.575, abs=2e-3)


def test_a_placeholder_substructure_keeps_the_drawn_footings_in_the_bill() -> None:
    bill = _bill(_drawn(), PLACEHOLDER)
    assert _item(bill, "footing", "concrete")["quantity"] == pytest.approx(4 * 1.8 * 1.8 * 0.5)
    assert not any(i["group"] == "earthwork" for i in bill["items"])
    # The placeholder is recorded (its replacement makes the bill out of date), the settings
    # are not (nothing depends on them).
    assert bill["source"]["substructure"] == source_stamp(PLACEHOLDER)
    assert "settings" not in bill["source"]
    legacy = _bill(_drawn(), None, None)
    assert set(legacy["source"]) == {"bim", "objects", "materials"}


def test_boq_handler_reports_an_invalid_substructure() -> None:
    building = _drawn().model_dump_json(by_alias=True)
    objects = OBJECTS.model_dump_json(by_alias=True)
    materials = default_material_library().model_dump_json(by_alias=True)
    bad = json.dumps({"schema": "saengine.substructure/1", "foundations": [{"id": "F1"}]})
    problems = handlers.compute_boq(building, objects, materials, bad)["problems"]
    assert problems and problems[0].startswith("Substructure: ")
    ok = handlers.compute_boq(building, objects, materials, json.dumps(_substructure()))
    assert "E.01" in ok["text"]


# ─────────────────────────────── IFC ───────────────────────────────


def test_ifc_has_the_substructure_foundations_in_place_of_the_drawn_ones() -> None:
    substructure = Substructure.model_validate(
        {
            **_substructure(),
            "foundations": [
                *_substructure()["foundations"],
                {"id": "PC1", "type": "pileCap", "columns": ["C3"], "length": 2500, "width": 1000,
                 "thickness": 800, "material": "C24.1", "pileType": "P1",
                 "piles": [[-750, 0], [750, 0]]},
                {"id": "R1", "type": "raft", "columns": ["C4"], "thickness": 600,
                 "material": "C24.1",
                 "outline": [[-1000, 4000], [1000, 4000], [1000, 6000], [-1000, 6000]]},
            ],
            "pileTypes": [{"id": "P1", "kind": "bored", "diameter": 500, "length": 10000,
                           "material": "C24.1"}],
        }
    )  # fmt: skip
    ifc, ids, skipped = export_ifc(_drawn(), OBJECTS, default_material_library(), "T", substructure)
    assert skipped == []  # the drawn footings are superseded, not missing
    assert not any(e.Name in ("F3", "F4") for e in ifc.by_type("IfcFooting"))

    def entity(key: str) -> ifcopenshell.entity_instance:
        return ifc.by_guid(ids[key])

    # F1 is both a drawn footing (left out) and a foundation: the map keeps the plain id.
    assert entity("F1").is_a("IfcFooting") and entity("F1").PredefinedType == "PAD_FOOTING"
    assert entity("PC1").PredefinedType == "PILE_CAP"
    assert entity("R1").is_a("IfcSlab") and entity("R1").PredefinedType == "BASESLAB"
    assert entity("TB1").PredefinedType == "FOOTING_BEAM"
    piles = [entity(k) for k in ("PC1/1", "PC1/2")]
    assert all(p.is_a("IfcPile") and p.PredefinedType == "BORED" for p in piles)
    # Placements: the footing's underside at its founding level, the piles below the cap
    # (C3's cap founds 1.5 m below the ground: its piles' feet at -11.5 m).
    z = entity("F1").ObjectPlacement.RelativePlacement.Location.Coordinates[2]
    assert z == pytest.approx(-1500)
    foot = piles[0].ObjectPlacement.RelativePlacement.Location.Coordinates
    assert foot[2] == pytest.approx(-1500 - 10000)
    # The handler takes the substructure's and the settings' texts.
    result = handlers.building_ifc(
        _drawn().model_dump_json(by_alias=True),
        OBJECTS.model_dump_json(by_alias=True),
        None,
        "T",
        substructure.model_dump_json(by_alias=True),
        SETTINGS_150.model_dump_json(by_alias=True),
    )
    assert "PC1/2" in result["ids"] and "F4" not in result["ids"]
    placeholder = handlers.building_ifc(
        _drawn().model_dump_json(by_alias=True), OBJECTS.model_dump_json(by_alias=True), None,
        "T", PLACEHOLDER,
    )  # fmt: skip
    assert "F4" in placeholder["ids"]


def test_foundation_solids_place_strips_rafts_and_default_centres() -> None:
    substructure = Substructure.model_validate(
        {
            "schema": "saengine.substructure/1",
            "foundations": [
                {"id": "F1", "type": "combined", "columns": ["C1", "C2"], "length": 8000,
                 "width": 1500, "thickness": 600},
                {"id": "S1", "type": "strip", "columns": [], "width": 1000, "thickness": 400,
                 "path": [[0, 5000], [6000, 5000]], "foundingLevel": -1200},
            ],
        }
    )  # fmt: skip
    solids = foundation_solids(substructure, generate(PLAN, "s"), 0.0)
    combined, strip = solids.foundations
    assert combined.center == pytest.approx((3000, 0)) and combined.bottom == -1500
    assert sorted(combined.outline) == sorted(
        [(-1000, -750), (7000, -750), (7000, 750), (-1000, 750)]
    )
    assert strip.runs == (6000, 1000) and strip.bottom == -1200 and strip.top == -800


# ─────────────────────────────── RPC handlers ───────────────────────────────


def test_substructure_handlers(tmp_path: Path) -> None:
    root = _project(tmp_path, _drawn())
    migrated = handlers.substructure_migrate(str(root))
    assert migrated["count"] == 4 and (root / SUBSTRUCTURE_FILE).read_text("utf-8") == PLACEHOLDER
    assert handlers.substructure_ensure(str(root))["count"] == 4
    # No analysis yet: nothing to size, and the report says why the footings are not designed.
    assert handlers.substructure_size(str(root))["notes"][0].startswith("Nothing sized:")
    report = handlers.substructure_report(str(root))
    assert report["summary"]["analysed"] is False and len(report["skipped"]) == 4
    # The stamps of the files the design read, for the part list ("" for a missing file).
    expected = {
        part: source_stamp((root / relative).read_text("utf-8"))
        if (root / relative).exists()
        else ""
        for part, relative in handlers.SUBSTRUCTURE_SOURCES.items()
    }
    assert report["sources"] == expected and set(expected) == {
        "soil", "settings", "materials", "objects", "bim", "substructure"
    }  # fmt: skip
    assert report["sources"]["soil"] == ""  # this project has no soil report
    (root / SUBSTRUCTURE_FILE).write_text('{"schema": "saengine.substructure/1", "foundations": 1}')
    assert handlers.substructure_report(str(root))["problems"]
    assert handlers.substructure_migrate(str(tmp_path / "missing"))["problems"]


# ─────────────────────────────── the shipped sample ───────────────────────────────


def test_the_sample_has_its_footing_in_9_substructure() -> None:
    def text(relative: str) -> str:
        return (SAMPLE / relative).read_text(encoding="utf-8")

    substructure = authoritative_substructure(text(SUBSTRUCTURE_FILE))
    assert substructure is not None
    f1 = substructure.foundations[0]
    assert (f1.id, f1.type, f1.columns, f1.length, f1.width, f1.thickness) == (
        "F1", "isolated", ["C1"], 2000, 1500, 500
    )  # fmt: skip
    assert text(SUBSTRUCTURE_FILE) == substructure_text(json.loads(text(SUBSTRUCTURE_FILE)))
    building = BuildingModel.model_validate_json(text("06 BIM/bim.json"))
    assert not any(e.kind == "footing" for e in building.elements)
    assert json.loads(text("05 Floor Plan/floor-plan.json"))["footings"] == []
    assert building.source.floorPlan == source_stamp(text("05 Floor Plan/floor-plan.json"))
    # No qa override (PR #33, P24: qa from the soil report), and the shipped bill is the bill of
    # these files (with the tank's plinth and the sleeve of 7 MEP).
    settings = json.loads(text("02 Project Settings/project-settings.json"))
    assert settings["foundation"].get("allowableBearing") is None
    bill = compute_boq(
        text("06 BIM/bim.json"),
        text("04 Objects/objects.json"),
        text("03 Materials/materials.json"),
        text(SUBSTRUCTURE_FILE),
        text("02 Project Settings/project-settings.json"),
        text("07 MEP/mep.json"),
    )
    assert bill == json.loads(text("10 BOQ/boq.json"))


# ─────────────────────────────── the printed report ───────────────────────────────


def test_report_prints_a_foundations_chapter(frame: tuple[dict, Path], tmp_path: Path) -> None:
    from saengine.report import build_report, report_data

    root = _analysed(_project(tmp_path, _drawn()), frame)
    before = report_data(root)
    assert before["foundations"]["available"] is False
    assert "not been moved to 9 Substructure" in before["foundations"]["message"]
    assert any("not been moved to 9 Substructure" in w for w in before["warnings"])

    ensure_migrated(root)
    data = report_data(root)
    chapter = data["foundations"]
    assert chapter["available"] and [r[0] for r in chapter["rows"]] == ["F1", "F2", "F3", "F4"]
    assert all(
        r[1] == "Isolated footing" and r[3] == "1.80 × 1.80 × 0.50 m" for r in chapter["rows"]
    )
    assert [r[2] for r in chapter["pressures"]] == ["150.0"] * 4  # the qa override
    assert len(chapter["details"]) == 4 and chapter["method"]
    assert chapter["limits"][0].startswith("The superstructure is analysed on fixed column bases")
    assert DESIGNED_IN_PART_9 in data["limitations"]["design"]

    result = build_report(root, tmp_path / "report.pdf")
    assert result["pages"] > 3
    from pypdf import PdfReader

    text = "".join(page.extract_text() for page in PdfReader(result["path"]).pages)
    assert "Foundations" in text and "Governing checks" in text

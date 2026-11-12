"""Alpha 9 L10 on a generated steel braced frame (the New Building wizard, ACI 318 / ASCE 7 pack):
the fabrication model, the shop drawings, the NC files and the BVBS file written into
11 Exports, the structural drawing set untouched."""

from __future__ import annotations

import json
import math
from pathlib import Path

import ezdxf
import pytest

from saengine.fabrication import bvbs
from saengine.fabrication.export import (
    BVBS_FOLDER,
    NC_FOLDER,
    SHOP_FOLDER,
    SHOP_RECORD,
    export_bvbs,
    export_nc,
    export_shop_drawings,
    fabrication_model,
    rpc_nc,
)

PACK_ID = "aci318-asce7-22"


def _wizard() -> dict:
    return {
        "schema": "saengine.newBuilding/1",
        "name": "Steel fabrication",
        "spacings": {"x": [6000], "y": [5000]},
        "stories": [
            {"id": "BASE", "name": "Base", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3500},
            {"id": "L2", "name": "Level 2", "elevation": 7000},
        ],
        "storyHeights": [3500, 3500],
        "system": "steelBracedFrame",
        "footing": "isolated",
        "site": {
            "siteClass": "SD",
            "siteClassSource": "assumed",
            "spectral": {"sds": 0.2, "sd1": 0.08, "s1": 0.05, "tl": 8},
            "windSpeed": 50,
        },
        "occupancy": {"use": "office", "category": "II"},
        "designCode": PACK_ID,
    }


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    """The generated building with designed-looking connections on its steel types: fin plates
    at the beams, bolted gussets at the braces, base plates under the columns."""
    from saengine.project.new_building import create_building

    root = Path(create_building(_wizard(), tmp_path_factory.mktemp("fab"))["root"])
    path = root / "04 Objects/objects.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for o in raw["objects"]:
        if o.get("kind") == "beam" and o.get("profile"):
            o["connection"] = {"type": "finPlate"}
        elif o.get("kind") == "brace":
            o["connection"] = {"type": "gusset", "tabThickness": 12}
        elif o.get("kind") == "column" and o.get("profile"):
            o["basePlate"] = {"type": "basePlate"}
    path.write_text(json.dumps(raw, indent="\t"), encoding="utf-8")
    return root


def test_model_marks_and_supports(project: Path) -> None:
    model, opts = fabrication_model(project)
    assert opts.weld_symbols == "aws"  # the pack's (AWS A2.4)
    kinds = {a.kind for a in model.assemblies}
    assert kinds == {"beam", "column", "brace"}
    marks = {a.mark for a in model.assemblies}
    assert {m[:1] for m in marks} >= {"B", "C"}
    # the fin plates are welded to the columns the beams frame into, the base plates to the
    # columns at the base; the beams are cut short of the columns' faces
    columns = [a for a in model.assemblies if a.kind == "column"]
    roles = {x.part.role for a in columns for x in a.parts}
    assert {"fin plate", "base plate", "gusset"} <= roles
    for a in model.assemblies:
        if a.kind == "beam":
            assert a.main.length < math.dist(a.start, a.end)
            assert any(h.face == "v" for h in a.main.holes)
    # identical members share their marks; every member is in one assembly
    assert sum(a.quantity for a in model.marked()) == len(model.assemblies)


def test_nc_files(project: Path) -> None:
    answer = export_nc(project)
    files = [Path(f) for f in answer["files"]]
    assert files and all(f.parent == project / NC_FOLDER for f in files)
    texts = {f.stem: f.read_bytes().decode("ascii") for f in files}
    for mark, text in texts.items():
        lines = text.split("\r\n")
        assert lines[0] == "ST" and lines[5] == f"  {mark}" and "EN" in lines
    plates = [t for t in texts.values() if "\r\n  B\r\n" in t]
    assert plates and all("\r\nAK\r\n" in t for t in plates)
    assert any("\r\nBO\r\n" in t for t in texts.values())
    assert rpc_nc({}) == {"error": "No project."}


def test_shop_drawings(project: Path) -> None:
    drawings = project / "11 Exports/Drawings"
    before = sorted(p.name for p in drawings.glob("*")) if drawings.exists() else []
    answer = export_shop_drawings(project)
    assert answer["sheets"] and answer["pdf"] and Path(answer["pdf"]).exists()
    numbers = [s["number"] for s in answer["sheets"]]
    assert numbers[0] == "SD-101"
    titles = " ".join(s["title"] for s in answer["sheets"])
    assert "Assembly B1" in titles and "Part drawings" in titles and "Marking plans" in titles
    record = json.loads((project / SHOP_FOLDER / SHOP_RECORD).read_text(encoding="utf-8"))
    assert record["weldSymbols"] == "aws"
    assert all(a["sheet"] for a in record["assemblies"])
    for row in answer["sheets"][:4]:
        doc = ezdxf.readfile(row["dxf"])
        assert not doc.audit().has_errors
    # the structural drawing set is not touched
    after = sorted(p.name for p in drawings.glob("*")) if drawings.exists() else []
    assert after == before
    # the NC files name the shop drawing sheets once those exist
    nc = export_nc(project)
    header = Path(nc["files"][0]).read_bytes().decode("ascii").split("\r\n")
    assert header[3].strip().startswith("SD-")


def test_bvbs_file(project: Path) -> None:
    # The generated steel frame has no reinforcement (Run All never writes bars): give the
    # floor slab's type a mesh so the bar schedule has bars to export.
    path = project / "04 Objects/objects.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for o in raw["objects"]:
        if o.get("kind") == "slab":
            o["reinforcement"] = {
                "material": "B420DWR",
                "cover": 20,
                "bottomX": {"dia": 10, "spacing": 150},
                "bottomY": {"dia": 10, "spacing": 200},
            }
    path.write_text(json.dumps(raw, indent="\t"), encoding="utf-8")
    answer = export_bvbs(project)
    (path,) = [Path(f) for f in answer["files"]]
    assert path.parent == project / BVBS_FOLDER and path.suffix == ".abs"
    lines = path.read_bytes().decode("ascii").split("\r\n")
    assert lines[-1] == "" and len(lines) - 1 == answer["marks"] > 0
    for line in lines[:-1]:
        assert line.startswith("BF2D@Hj") and line.endswith("@")
        body, _, tail = line.rpartition("C")
        assert bvbs.checksum(body + "C") == int(tail.rstrip("@"))

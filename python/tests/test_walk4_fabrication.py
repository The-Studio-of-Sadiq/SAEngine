"""Usability walk 4 (W4C-7, W4C-8): the steel shop drawings and the NC files show the special
members as designed, and warn about undesigned connections.

On a generated steel braced frame (the New Building wizard, ACI 318 / ASCE 7 pack): the beams'
type has hexagonal web openings (h0 240 at 420 centres: a castellated beam) and end plates with
no plate material on ASTM A992; one beam is an open-web joist (600 deep). Expected, by hand:

- the castellated beams' main parts carry one opening per 420 mm, centred on the span as the
  design places them, and their NC files one IK block (seven corners, closed) per opening;
- the joist is drawn and billed as "open-web joist 600 mm deep" by the joist supplier, with no
  NC file;
- the end plates are ASTM A572 Grade 50 (the pack's plate grade for A992 members), not A992;
- the braces' ends, with no connection designed, are counted in the exports' problems.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from saengine.fabrication.export import export_nc, export_shop_drawings, fabrication_model
from saengine.fabrication.model import opening_centres

PACK_ID = "aci318-asce7-22"


def _wizard() -> dict:
    return {
        "schema": "saengine.newBuilding/1",
        "name": "Walk 4 fabrication",
        "spacings": {"x": [6000], "y": [5000]},
        "stories": [
            {"id": "BASE", "name": "Base", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3500},
        ],
        "storyHeights": [3500],
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
    from saengine.project.new_building import create_building

    root = Path(create_building(_wizard(), tmp_path_factory.mktemp("walk4fab"))["root"])
    path = root / "04 Objects/objects.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    beam_type = None
    for o in raw["objects"]:
        if o.get("kind") == "beam" and o.get("profile") and beam_type is None:
            beam_type = o
            o["connection"] = {"type": "endPlate"}
            o["webOpenings"] = {"shape": "hexagonal", "depth": 240, "spacing": 420}
    assert beam_type is not None
    joist = json.loads(json.dumps(beam_type))
    joist.update(id="J600", name="Joist 600")
    joist.pop("webOpenings")
    joist.pop("connection")
    joist["joist"] = {"depth": 600}
    raw["objects"].append(joist)
    path.write_text(json.dumps(raw, indent="\t"), encoding="utf-8")
    bim_path = root / "06 BIM/bim.json"
    bim = json.loads(bim_path.read_text(encoding="utf-8"))
    beam = next(
        e for e in bim["elements"] if e.get("kind") == "beam" and e["type"] == beam_type["id"]
    )
    beam["type"] = "J600"
    bim_path.write_text(json.dumps(bim, indent="\t"), encoding="utf-8")
    return root


def test_castellated_beam_has_its_openings(project: Path) -> None:
    model, _ = fabrication_model(project)
    beams = [a for a in model.assemblies if a.kind == "beam" and a.main.openings]
    assert beams
    for a in beams:
        span = math.dist(a.start, a.end)
        centres, width, cut = opening_centres(
            type("O", (), {"shape": "hexagonal", "depth": 240, "spacing": 420, "cut": None,
                           "first": None})(),
            span,
        )  # fmt: skip
        assert cut == pytest.approx(240 / math.sqrt(3))
        assert width == pytest.approx(cut + 240 / math.tan(math.radians(60)))
        assert len(a.main.openings) == len(centres) == int((span - width) // 420) + 1
        steps = [b.x - c.x for c, b in zip(a.main.openings, a.main.openings[1:], strict=False)]
        assert all(s == pytest.approx(420, abs=0.2) for s in steps)
        assert all(o.y == pytest.approx(a.main.h / 2, abs=0.1) for o in a.main.openings)
    # the web less the openings in the part's mass
    a = beams[0]
    assert a.main.mass < a.main.mass_per_m * a.main.length / 1000


def test_joist_is_by_the_supplier(project: Path) -> None:
    model, _ = fabrication_model(project)
    joists = [a for a in model.assemblies if a.main.supplied]
    assert len(joists) == 1
    main = joists[0].main
    assert main.name == "open-web joist 600 mm deep"
    assert main.h == 600 and main.role == "joist" and not main.holes
    assert main.mass > 0


def test_nc_files_skip_the_joist_and_contour_the_openings(project: Path) -> None:
    model, _ = fabrication_model(project)
    joist_mark = next(a.main.mark for a in model.assemblies if a.main.supplied)
    castellated = {a.main.mark: len(a.main.openings) for a in model.assemblies if a.main.openings}
    answer = export_nc(project)
    names = {Path(f).stem for f in answer["files"]}
    assert joist_mark not in names
    for mark_, n in castellated.items():
        text = (Path(answer["folder"]) / f"{mark_}.nc1").read_bytes().decode("ascii")
        lines = text.split("\r\n")
        assert lines.count("IK") == n
        k = lines.index("IK")
        corners = lines[k + 1 : k + 8]
        assert corners[0] == corners[-1]  # closed
    assert any("joist supplier" in n for n in answer["notes"])


def test_plates_take_the_plate_grade_and_undesigned_ends_warn(project: Path) -> None:
    model, _ = fabrication_model(project)
    plates = [p for p, _ in model.parts() if p.role == "end plate"]
    assert plates and all(p.grade == "ASTM A572 Grade 50" for p in plates)
    answer = export_shop_drawings(project)
    braces = [a for a in model.assemblies if a.kind == "brace"]
    warned = [p for p in answer["problems"] if "no connection designed" in p]
    assert len(warned) == 1
    assert warned[0].startswith(f"{len(model.undesigned)} member end(s)")
    assert len(model.undesigned) >= 2 * len(braces)
    record = json.loads(
        (project / "11 Exports/Shop Drawings/shop-drawings.json").read_text(encoding="utf-8")
    )
    names = {p["name"] for p in record["parts"]}
    assert "open-web joist 600 mm deep" in names

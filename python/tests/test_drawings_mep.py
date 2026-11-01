"""MEP sheets and the office drafting standard (T34): the services by story, the schedules, the
standard's layer names (applied and named back) and its sheet prefixes."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from saengine.drawings.sheets import DrawingSettings, build_sheets
from saengine.drawings.sheets import mep as mp
from saengine.drawings.sheets.layout import LAYERS, new_document
from saengine.drawings.sheets.model import Building, DrawingSet, Grid, Level, PlanBeam, PlanSlab
from saengine.drawings.sheets.standards import DEFAULT_PREFIXES, Standard, restore_names
from saengine.library import mep as ml


def _building() -> Building:
    b = Building(
        grids_x=[Grid("A", 0), Grid("B", 6000)],
        grids_y=[Grid("1", 0), Grid("2", 5000)],
        levels=[
            Level("BASE", "Base", 0),
            Level("L1", "Level 1", 3200),
            Level("L2", "Level 2", 6400),
        ],
    )
    b.beams.append(PlanBeam("B1", "B1", (0, 0), (6000, 0), 250, 500, 3200))
    b.slabs.append(PlanSlab("S1", "S1", [(0, 0), (6000, 0), (6000, 5000), (0, 5000)], 150, 3200))
    return b


def _mep() -> ml.MepModel:
    return ml.MepModel.model_validate(
        {
            "schema": "saengine.mep/1",
            "openings": [
                {"id": "OP1", "host": "B1", "kind": "sleeve", "shape": "circle", "diameter": 100,
                 "position": {"distance": 2000, "elevation": 250}, "service": "DN100 drain"},
                {"id": "OP2", "host": "S1", "kind": "opening", "shape": "rectangle", "width": 600,
                 "height": 400, "position": {"x": 3000, "y": 2500}},
            ],
            "shafts": [{"id": "SH1", "outline": [[100, 100], [900, 100], [900, 900], [100, 900]],
                        "fromStory": "BASE", "toStory": "L1", "service": "Plumbing shaft"}],
            "plumbing": {
                "risers": [{"id": "R1", "system": "coldWater", "x": 500, "y": 500,
                            "fromStory": "BASE", "toStory": "L2", "diameter": 50}],
                "tanks": [
                    {"id": "T1", "kind": "overhead", "x": 3000, "y": 2500, "length": 2000,
                     "width": 1500, "waterDepth": 1200},
                    {"id": "SW1", "kind": "soakWell", "x": 9000, "y": 2500, "diameter": 1200,
                     "waterDepth": 2000},
                ],
            },
        }
    )  # fmt: skip


def test_services_by_story():
    b = _building()
    items = mp.items_by_level(mp.MepDrawing(_mep()), b)
    # the riser on every story it rises through, the shaft from Base to Level 1
    assert [i.mark for i in items["L2"] if i.discipline == "plumbing"] == ["R1 CW Ø50"]
    assert any(i.discipline == "shaft" for i in items["L1"])
    assert not any(i.discipline == "shaft" for i in items["L2"])
    # an overhead tank without a story on the top story, a soak well on the lowest
    assert any(i.mark.startswith("T1 ") for i in items["L2"])
    assert any(i.mark.startswith("SW1 ") for i in items["BASE"])
    # the beam's sleeve 2000 along it, on the beam's level; the slab opening at its x, y
    beam_sleeve = next(i for i in items["L1"] if i.mark.startswith("OP1"))
    assert beam_sleeve.points[0] == pytest.approx((2000, 0))
    assert mp.has_plan(items["BASE"], "plumbing") and not mp.has_plan(items["BASE"], "electrical")


def test_tank_volume():
    # inside length x width x water depth; a soak well by its diameter
    tanks = _mep().plumbing.tanks
    assert mp.tank_volume(tanks[0]) == pytest.approx(2.0 * 1.5 * 1.2)
    assert mp.tank_volume(tanks[1]) == pytest.approx(math.pi * 0.6**2 * 2.0)
    assert (
        mp.tank_volume(SimpleNamespace(waterDepth=None, length=1, width=1, diameter=None)) is None
    )


def test_schedules():
    b = _building()
    tables = {t.title: t for t in mp.schedule_tables(mp.MepDrawing(_mep()), b)}
    assert tables["Riser schedule"].rows == [
        ["R1", "Cold water riser", "Base", "Level 2", "Ø50", "-", "-"]
    ]
    assert [r[0] for r in tables["Tank schedule"].rows] == ["T1", "SW1"]
    assert tables["Sleeve and opening schedule"].rows[0][-1] == "Level 1"
    assert "Equipment schedule" not in tables  # no equipment: no table


def test_standard_names_layers_and_back():
    standard = Standard.from_dict(
        {
            "layerPrefix": "X-",
            "layers": [
                {"layer": "s-grid", "name": "GRID", "color": 8, "lineweight": 0.13},
                {"layer": "S-COLS", "name": "S-BEAM"},  # a name of the scheme: kept
                {"layer": "S-WALL", "name": "GRID"},  # taken by S-GRID: kept
                {"layer": "NOPE"},
            ],
            "plumbingPrefix": "PL-",
        }
    )
    assert standard.renames["S-GRID"] == "GRID"
    assert "S-COLS" not in standard.renames and "S-WALL" not in standard.renames
    assert standard.renames["S-TEXT"] == "X-S-TEXT"
    assert len(standard.problems) == 3
    assert standard.prefixes == {**DEFAULT_PREFIXES, "plumbing": "PL-"}
    doc = new_document(100)
    doc.modelspace().add_line((0, 0), (1, 1), dxfattribs={"layer": "S-GRID"})
    standard.apply(doc)
    assert "GRID" in doc.layers and "S-GRID" not in doc.layers
    assert doc.layers.get("GRID").color == 8 and doc.layers.get("GRID").dxf.lineweight == 13
    assert next(iter(doc.modelspace())).dxf.layer == "GRID"
    restore_names(doc, standard.renames)
    assert {name for name, *_ in LAYERS} <= {layer.dxf.name for layer in doc.layers}
    assert next(iter(doc.modelspace())).dxf.layer == "S-GRID"


def test_standard_prefixes_and_font_on_the_sheets():
    data = DrawingSet(building=_building())
    data.mep = mp.MepDrawing(_mep())
    standard = {"font": "Calibri", "arrows": "closed", "plumbingPrefix": "PL-",
                "coordinationPrefix": "CO-"}  # fmt: skip
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": "A1", "standard": standard}))
    numbers = [s.number for s in sheets]
    assert "PL-101" in numbers and "CO-101" in numbers
    assert not any(n.startswith(("P-", "MC-")) for n in numbers)
    style = sheets[0].doc.styles.get("SAE")
    assert style.dxf.font == "calibri.ttf"


def test_shared_prefixes_fall_back():
    standard = Standard.from_dict({"plumbingPrefix": "S-"})
    assert standard.prefixes == DEFAULT_PREFIXES and standard.problems

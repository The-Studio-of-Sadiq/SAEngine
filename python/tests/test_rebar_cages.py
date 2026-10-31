"""3D reinforcement cages and the bar congestion check (saengine.drawings.cages): the cages are
the detailing model's bars on the design's section layout; the spacing limits are BNBC 2020
Part 6 Sec 8.1.6.1-8.1.6.3 (p. 1068) from the code pack; the IFC carries IfcReinforcingBar."""

from __future__ import annotations

import json
import math

import pytest
from test_drawings_detailing import MATERIALS, _frame, _model, _objects

from saengine.drawings import cages
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary


def _cages(objects_text: str | None = None, bim: str | None = None) -> dict:
    objects_text = objects_text or _objects()
    model = _model(objects=objects_text, **({"bim": bim} if bim else {}))
    objects = ObjectLibrary.model_validate_json(objects_text)
    materials = MaterialLibrary.model_validate_json(MATERIALS)
    return cages.cage_model(model, objects, materials)


def test_limits_come_from_the_code_pack() -> None:
    lim = cages.limits()
    assert lim is not None
    # 8.1.6.1: db but not less than 25 mm; 8.1.6.3: 1.5 db but not less than 40 mm
    assert lim.layer(16) == pytest.approx(25.0)
    assert lim.layer(32) == pytest.approx(32.0)
    assert lim.between_layers == pytest.approx(25.0)
    assert lim.column(16) == pytest.approx(40.0)
    assert lim.column(32) == pytest.approx(48.0)


def test_beam_and_column_cages_follow_the_detailing() -> None:
    found = _cages()
    bars = found["bars"]
    beam_top = [b for b in bars if b["element"] == "B1+B2" and b["role"] == "top"]
    # 4 top bars: every one drawn, at the top face of the 450 deep beam (top at 3000)
    assert sum(len(b["lines"]) for b in beam_top) >= 4
    for b in beam_top:
        for line in b["lines"]:
            z = max(p[2] for p in line)
            assert 3000 - 450 / 2 < z < 3000
    stirrups = [b for b in bars if b["element"] == "B1+B2" and b["role"] == "stirrup"]
    assert stirrups and all(len(line) == 5 for line in stirrups[0]["lines"])  # closed rectangle
    columns = [b for b in bars if b["element"] == "C1" and b["role"] == "vertical"]
    assert sum(len(b["lines"]) for b in columns) == 4
    # the column bars at the corners, cover 40 + tie 10 + 8 from the faces of the 300 column
    xs = sorted({round(line[0][0]) for b in columns for line in b["lines"]})
    assert xs == [-92, 92]
    assert "slab" in found["skipped"] and "footing" in found["skipped"]


def test_positions_of_hoop_rows() -> None:
    rows = [
        {"from": 50, "to": 650, "spacing": 100, "count": 7, "mark": "S1"},
        {"from": 650, "to": 1250, "spacing": 150, "count": 4, "mark": "S1"},
    ]
    found = cages._positions(rows, "S1")
    assert found[:2] == [50, 150] and found[6] == 650
    assert found[7:] == [800, 950, 1100, 1250]


def test_congestion_of_a_crowded_beam_and_column() -> None:
    crowded = [
        {
            "id": "C300",
            "name": "Column 300x300",
            "kind": "column",
            "material": json.loads(_objects())["objects"][0]["material"],
            "profile": {"shape": "rectangle", "xDim": 300, "yDim": 300},
            "reinforcement": {
                "material": json.loads(_objects())["objects"][0]["reinforcement"]["material"],
                "cover": 40,
                "longitudinal": [{"position": "perimeter", "count": 16, "dia": 25}],
                "transverse": {"type": "tie", "dia": 10, "spacing": 100, "legs": 2},
            },
        }
    ]
    base = json.loads(_objects())
    base["objects"] = [o for o in base["objects"] if o["id"] != "C300"] + crowded
    found = _cages(json.dumps(base))
    column = [c for c in found["checks"] if c["where"] == "type C300"]
    assert column and not column[0]["ok"]
    assert column[0]["required"] == pytest.approx(max(40.0, 1.5 * 25))
    joints = [c for c in found["checks"] if c["where"].startswith("joint ")]
    assert joints  # the beams' bars against the column's bars at the joints
    lines = cages.congestion_problems(found)
    assert lines and lines[0].startswith("Bar congestion")
    assert "8.1.6" in cages.congestion_csv(found)


def test_beam_layer_spacing_check_passes_for_the_sample_frame() -> None:
    found = _cages()
    layer = [c for c in found["checks"] if c["where"] == "type B250"]
    assert layer and all(c["ok"] for c in layer)
    # 4 Ø16 across 250 - 2 (40 + 10) - 16 = 134 mm between the outer centres: 44.7 - 16 clear
    top = next(c for c in layer if c["name"].startswith("top"))
    assert top["provided"] == pytest.approx(134 / 3 - 16, abs=0.2)


def test_rebar_in_the_ifc() -> None:
    import ifcopenshell

    from saengine.library.bim import BuildingModel
    from saengine.library.ifc import export_ifc

    found = _cages()
    building = BuildingModel.model_validate_json(_frame())
    objects = ObjectLibrary.model_validate_json(_objects())
    ifc, ids, skipped = export_ifc(building, objects, rebar=found)
    bars = ifc.by_type("IfcReinforcingBar")
    assert bars and not [s for s in skipped if s.startswith("rebar:")]
    assert {b.PredefinedType for b in bars} >= {"MAIN", "LIGATURE"}
    assert all(math.isclose(b.CrossSectionArea, math.pi * b.NominalDiameter**2 / 4) for b in bars)
    assert any(key.startswith("rebar:B1/") for key in ids)
    text = ifc.to_string()
    assert "IFCSWEPTDISKSOLID" in text
    assert isinstance(ifcopenshell.file.from_string(text), ifcopenshell.file)

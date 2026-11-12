"""3D reinforcement cages and the bar congestion check (saengine.drawings.cages): the cages are
the detailing model's bars on the design's section layout; the spacing limits are BNBC 2020
Part 6 Sec 8.1.6.1-8.1.6.3 (p. 1068) from the code pack; the IFC carries IfcReinforcingBar."""

from __future__ import annotations

import itertools
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


def test_bars_placed_through_a_joint_keep_clear_of_the_column_bars() -> None:
    lim = cages.limits()
    assert lim is not None
    # a 250 beam flush with the face of a 300 column: its outer bar (67 from the beam's centre
    # line) on the column bars' line (at 67 and at 67 - 184 = -117 across the beam)
    xs = [-67.0, 0.0, 67.0]
    cols = [(67.0, 16.0), (-117.0, 16.0)]
    moved = cages.place_through(xs, 16.0, cols, 67.0, lim)
    assert moved is not None and moved != xs
    assert max(moved) <= 67.0 + 1e-6 and min(moved) >= -67.0 - 1e-6  # never outward
    for x in moved:
        for xc, dc in cols:
            assert abs(x - xc) - (16 + dc) / 2 >= lim.layer(16) - 1e-6
    ordered = sorted(moved)
    assert all(b - a - 16 >= lim.layer(16) - 1e-6 for a, b in itertools.pairwise(ordered))
    # bars already clear do not move
    assert cages.place_through([-30.0, 30.0], 16.0, [(120.0, 16.0)], 67.0, lim) == [-30.0, 30.0]
    # no room for the full spacing: as much of it as fits (the check reports them tight)
    tight = cages.place_through([-67.0, 0.0, 67.0], 16.0, [(0.0, 20.0)], 67.0, lim)
    assert tight is not None
    gaps = [abs(x) - 18 for x in tight]
    assert 0 < min(gaps) < lim.layer(20)


def test_crank_path_and_its_extra_length() -> None:
    crank = {"at": "C1", "from": 1000.0, "to": 1300.0, "offset": -50.0}
    path = cages._path(0.0, 3000.0, 67.0, [crank])
    # 1 in 6: from 700 to 1000 across to 17, along the joint, back by 1600
    assert path == [(0.0, 67.0), (700.0, 67.0), (1000.0, 17.0), (1300.0, 17.0), (1600.0, 67.0),
                    (3000.0, 67.0)]  # fmt: skip
    assert cages.path_extra(0.0, 3000.0, [crank]) == pytest.approx(2 * 50 * (math.sqrt(37) - 6))
    # a bar ending in the joint (hooked into an end column) has one slope only
    assert cages.path_extra(1100.0, 3000.0, [crank]) == pytest.approx(50 * (math.sqrt(37) - 6))


def _flush_frame() -> str:
    """The test frame with its beams flush with the columns' face (y = 25: the 250 beam's face
    on the 300 column's): the beam's outer bars on the column bars' line."""
    bim = json.loads(_frame())
    for e in bim["elements"]:
        if e["kind"] == "beam":
            e["start"][1] = e["end"][1] = 25
    return json.dumps(bim)


def _three_bars() -> str:
    """The test types with three top bars in the beam (four Ø16 do not fit past a flush
    column's bars with the full clear spacing: they would be cranked and reported tight)."""
    objects = json.loads(_objects())
    beam = next(o for o in objects["objects"] if o["id"] == "B250")
    beam["reinforcement"]["longitudinal"][0]["count"] = 3
    return json.dumps(objects)


def _counts(element: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for b in element["bars"]:
        if b["role"] in ("top", "bottom"):
            out[b["role"]] = out.get(b["role"], 0) + b["count"]
    return out


def test_beam_bars_cranked_inside_the_column_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    from saengine.drawings import bbs

    def past_column(found: dict) -> list[dict]:
        return [c for c in found["checks"] if "past the column bars" in c["name"]]

    types, bim = _three_bars(), _flush_frame()
    with monkeypatch.context() as m:  # as before: straight bars clash with the column bars
        m.setattr(cages, "joint_cranks", lambda *a, **k: None)
        straight = _cages(types, bim=bim)
        plain = _model(objects=types, bim=bim)
    assert any(c["severity"] == "error" for c in past_column(straight))
    found = _cages(types, bim=bim)
    checks = past_column(found)
    assert checks and all(c["ok"] for c in checks)
    model = _model(objects=types, bim=bim)
    beam = next(e for e in model["elements"] if e["id"] == "B1+B2")
    cranked = [b for b in beam["bars"] if b["at"].get("cranks")]
    assert cranked and all(b["crank"] > 0 and "cranked" in b["remarks"] for b in cranked)
    assert any("cranked" in n for n in beam["notes"])
    # every bar is still there: the entries are split, not dropped
    plain_beam = next(e for e in plain["elements"] if e["id"] == "B1+B2")
    assert _counts(beam) == _counts(plain_beam)
    # the developed length grows by the cranks
    for bar in cranked:
        base = next(
            b for b in plain_beam["bars"] if b["role"] == bar["role"]
            and b["at"]["from"] == bar["at"]["from"] and b["at"]["to"] == bar["at"]["to"]
        )  # fmt: skip
        extra = cages.path_extra(bar["at"]["from"], bar["at"]["to"], bar["at"]["cranks"][0])
        assert extra > 0
        assert bar["crank"] == math.ceil(extra)  # up to the whole mm
        assert bar["length"] == pytest.approx(base["length"] + bar["crank"], abs=0.1)
        assert bar["shape"] == base["shape"] and bar["dims"] == base["dims"]
    # the BBS schedules them in their shape with the cranks' length added
    schedule = bbs.bar_schedule(model)
    straight_rows = {
        (r.shape, tuple(sorted(r.dims.items()))): r for r in bbs.bar_schedule(plain).rows
    }
    for bar in cranked:
        row = next(r for r in schedule.rows if r.mark == bar["mark"])
        assert "cranked" in row.remarks
        twin = straight_rows[(row.shape, tuple(sorted(row.dims.items())))]
        assert row.cutting_length >= twin.cutting_length
    # the 3D cage draws the crank: the bar moves across the beam (y here) at the joint
    lines = [
        line for b in found["bars"] if b["mark"] == cranked[0]["mark"] and b["element"] == "B1+B2"
        for line in b["lines"]
    ]  # fmt: skip
    assert lines and all(len({round(p[1], 1) for p in line}) > 1 for line in lines)

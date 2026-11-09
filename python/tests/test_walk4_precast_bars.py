"""Usability walk 4, W4C-16: a precast beam piece longer than its bay was accepted, and the bar
bending schedule ran continuous bars over the joints of precast beams (10.7 m on two 5 m bays)
against the precast bar list (one straight bar per piece). The piece is now checked against
the bay, and the schedule (so BVBS) takes the piece's own bars."""

from __future__ import annotations

import json

import pytest

from saengine.design import precast as pc
from saengine.drawings import bbs
from saengine.library import ObjectLibrary
from tests.test_drawings_detailing import _element, _frame, _model, _objects

PRECAST_BEAM = {
    "id": "PB",
    "name": "Precast beam 250x450",
    "kind": "beam",
    "material": "C3500",
    "profile": {"shape": "rectangle", "xDim": 250, "yDim": 450},
    "reinforcement": {
        "material": "B420DWR",
        "cover": 40,
        "longitudinal": [
            {"position": "top", "count": 3, "dia": 16},
            {"position": "bottom", "count": 4, "dia": 12},
        ],
        "transverse": {"type": "stirrup", "dia": 8, "spacing": 200, "legs": 2},
    },
}


def _precast_objects(length: float | None) -> str:
    """The detailing tests' objects with their beam type made a precast beam."""
    data = json.loads(_objects())
    for o in data["objects"]:
        if o["id"] == "B250":
            o["precast"] = {"element": "beam", "mark": "PB1"}
            if length:
                o["precast"]["length"] = length
            o["reinforcement"]["transverse"] = PRECAST_BEAM["reinforcement"]["transverse"]
    return json.dumps(data)


def _pieces(length: float | None):
    from saengine.library.bim import BuildingModel

    building = BuildingModel.model_validate_json(_frame())
    objects = ObjectLibrary.model_validate_json(_precast_objects(length))
    return pc.pieces_of(building, objects), {o.id: o for o in objects.objects}


def test_a_piece_longer_than_its_bay_is_a_problem() -> None:
    pieces, types = _pieces(5600)
    (piece,) = pieces  # four 5 m beams, one mark
    assert sorted(b[1] for b in piece.bays) == [5000] * 4
    # clear span: 5000 less half of each 300 mm column
    assert all(b[2] == pytest.approx(4700) for b in piece.bays)
    rows = pc.fit_checks(types["B250"], piece)
    fits = next(r for r in rows if r["name"] == "Piece length: fits the bay")
    assert fits["ok"] is False and "does not fit" in fits["note"]
    reaches = next(r for r in rows if r["name"] == "Piece length: reaches the supports")
    assert reaches["ok"] is True
    problems = pc.fit_problems(pieces, types)
    assert len(problems) == 1 and "5600 mm piece on a 5000 mm bay" in problems[0]


def test_a_piece_that_fits_and_one_too_short() -> None:
    pieces, types = _pieces(4900)
    assert all(r["ok"] for r in pc.fit_checks(types["B250"], pieces[0]))
    assert pc.fit_problems(pieces, types) == []
    pieces, types = _pieces(4600)
    reaches = next(
        r
        for r in pc.fit_checks(types["B250"], pieces[0])
        if r["name"] == "Piece length: reaches the supports"
    )
    assert reaches["ok"] is False


def test_a_piece_of_the_model_length_is_not_checked() -> None:
    pieces, types = _pieces(None)
    assert pc.fit_checks(types["B250"], pieces[0]) == []


def test_piece_bars_stop_the_cover_short_of_the_ends() -> None:
    obj = ObjectLibrary.model_validate({"objects": [PRECAST_BEAM]}).objects[0]
    bars = pc.piece_bars(obj, 5600)
    top = next(b for b in bars if b["where"] == "top")
    assert top["length"] == pytest.approx(5600 - 2 * 40)
    links = next(b for b in bars if b["where"] == "links")
    assert links["count"] == sum(r["count"] for r in links["rows"])


def test_precast_beams_take_their_bars_from_the_piece() -> None:
    model = _model(objects=_precast_objects(5600))
    ids = {e["id"] for e in model["elements"] if e["kind"] == "beam"}
    assert "B1+B2" not in ids and {"B1", "B2"} <= ids  # no line over the joint
    beam = _element(model, "B1")
    longitudinal = [b for b in beam["bars"] if b["role"] in ("top", "bottom")]
    assert all(b["shape"] == "straight" for b in longitudinal)
    assert all(b["length"] == pytest.approx(5600 - 80) for b in longitudinal)
    assert sum(b["count"] for b in longitudinal if b["role"] == "top") == 4
    assert beam["laps"] == []
    stirrup = next(b for b in beam["bars"] if b["role"] == "stirrup")
    assert stirrup["count"] == sum(r["count"] for r in beam["transverse"])
    # the schedule (and BVBS) as the piece's bar list
    schedule = bbs.bar_schedule(model)
    rows = [r for r in schedule.rows if r.element == "B1" and r.role in ("top", "bottom")]
    assert rows and all(r.cutting_length <= 5600 for r in rows)
    assert not any(
        r.cutting_length > 5600 for r in schedule.rows if r.kind == "beam" and not r.transverse
    )
    # the precast bar list gives the same bars
    from saengine.drawings.sheets.precast import _bars

    objects = ObjectLibrary.model_validate_json(_precast_objects(5600))
    listed = _bars(next(o for o in objects.objects if o.id == "B250"), 5600)
    assert {(b["dia"], b["count"], round(b["length"])) for b in listed if b["where"] == "top"} == {
        (16.0, 4, 5520)
    }


def test_cast_in_place_beams_stay_continuous() -> None:
    model = _model()
    assert _element(model, "B1+B2")["members"] == ["B1", "B2"]

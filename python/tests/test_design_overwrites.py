"""Design overwrites (saengine.design.overwrites): merged member > type > default, and honoured
by the RC column slenderness (saengine.design.slender) and the steel member lengths, with the
source shown in the check's note. Synthetic frames of test_design_slender."""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError
from test_design_slender import EC, IG, SECTION, STATIONS, _frame, _piece, _rows

from saengine.design import overwrites as ow
from saengine.design.check import _Piece
from saengine.design.slender import SlenderContext, SlenderOptions
from saengine.design.steel.lengths import (
    LengthOptions,
    MemberLengths,
    slenderness_note,
)


def test_merge_member_over_type_over_default() -> None:
    object_type = {"designOverwrites": {"k2": 1.5, "k3": 1.1, "framing": "sway"}}
    member = {"designOverwrites": {"k2": 1.2, "momentMagnifiers": {"deltaNs": 1.3}}}
    r = ow.resolve(member, object_type)
    assert r.get("k2") == 1.2 and r.source("k2") == ow.MEMBER and r.text("k2") == " (overwrite)"
    assert r.get("k3") == 1.1 and r.text("k3") == " (type overwrite)"
    assert r.get("framing") == "sway" and r.get("deltaNs") == 1.3
    assert r.get("Lu2") is None and r.source("Lu2") == ow.DEFAULT and r.text("Lu2") == ""
    assert r.k("x") == 1.1 and r.k("y") == 1.2  # x: about the profile's x-axis (local 3)
    assert not ow.resolve(None, None)
    # Attributes (pydantic models) are read as well; the given ones win over them.
    typed = ow.DesignOverwrites(k3=2.0)
    assert ow.resolve(None, None, None, typed).get("k3") == 2.0
    assert "k3 = 2 (type overwrite)" in ow.resolve(None, None, None, typed).notes()
    with pytest.raises(ValidationError):
        ow.DesignOverwrites.model_validate({"framing": "unbraced"})
    with pytest.raises(ValidationError):
        ow.DesignOverwrites.model_validate({"k2": 0})
    found = ow.resolve_all(
        [("C1", None, object_type), ("C2", None, None), ("C3", None, None)],
        by_member={"C3": {"Lu3": 2500}},
    )
    assert set(found) == {"C1", "C3"} and found["C3"].lu("x") == 2500


def _context(piece: _Piece, overwrites: dict, options=None, disp=None):
    project, building, types = _frame(6.0)
    combos = ["1.4D"] if disp is None else ["1.2D + 1.0EX"]
    beam = _Piece(
        "B1",
        2,
        6.0,
        depth_along_z=True,
        axes=np.eye(3),
        forces=[np.zeros((STATIONS, 6))],
        start=np.array([0, 0, 6.0]),
        end=np.array([6.0, 0, 6.0]),
        sway=[np.zeros((STATIONS, 6))],
        sustained=[np.zeros((STATIONS, 6))],
    )
    return SlenderContext(
        project,
        building,
        types,
        {},
        {"C1": [piece], "B1": [beam]},
        combos,
        disp or [{}],
        options,
        overwrites=overwrites,
    )


def _about_y(result):
    return next(a for a in result.axes if a.axis == "y")


def test_k_overwrite_changes_the_slenderness_check_by_hand() -> None:
    # test_design_slender's braced column: lu = 5400 mm, r = 150 mm, k = 1: k lu / r = 36.
    total = [_rows(-3e6, 60e3, 100e3)]
    piece = _piece(6.0, total, [np.zeros((STATIONS, 6))], [_rows(-1.5e6, 0, 0)])
    plain = _about_y(_context(piece, {}).column("C1", SECTION, [piece], False, EC))
    assert plain.check["slenderness"]["klu_r"] == pytest.approx(36.0, rel=1e-3)
    given = {"C1": ow.resolve({"designOverwrites": {"k2": 1.2}}, None)}
    axis = _about_y(_context(piece, given).column("C1", SECTION, [piece], False, EC))
    s = axis.check["slenderness"]
    assert s["k"] == 1.2 and s["kSource"] == "member"
    assert s["klu_r"] == pytest.approx(1.2 * 5400 / 150, rel=1e-3)  # 43.2
    assert "k = 1.20 (overwrite)" in axis.check["note"]
    # Pc with k = 1.2 (a braced column): δns grows.
    pc = math.pi**2 * (0.4 * EC * IG / 1.5) / (1.2 * 5400) ** 2
    cm = 0.6 + 0.4 * 0.6
    assert s["Pc"] == pytest.approx(pc / 1e3, rel=1e-3)
    assert s["deltaNs"] == pytest.approx(cm / (1 - 3e6 / (0.75 * pc)), rel=1e-3)
    assert s["deltaNs"] > plain.check["slenderness"]["deltaNs"]
    # About x nothing was given: the automatic values.
    x = next(a for a in _context(piece, given).column("C1", SECTION, [piece], False, EC).axes)
    assert x.axis == "x" and x.check["slenderness"]["kSource"] == "default"


def test_type_overwrite_of_lu_and_magnifiers() -> None:
    total = [_rows(-3e6, 60e3, 100e3)]
    piece = _piece(6.0, total, [np.zeros((STATIONS, 6))], [_rows(-1.5e6, 0, 0)])
    given = {
        "C1": ow.resolve(
            None, {"designOverwrites": {"Lu2": 3000, "momentMagnifiers": {"deltaNs": 1.25}}}
        )
    }
    # lu = 3000 mm: k lu / r = 20 <= 26.8: neglected, whatever δns says.
    axis = _about_y(_context(piece, given).column("C1", SECTION, [piece], False, EC))
    s = axis.check["slenderness"]
    assert s["lu"] == 3000 and s["luSource"] == "type" and s["neglected"]
    assert "lu = 3000 mm (type overwrite)" in axis.check["note"]
    # A given δns applies where slenderness is designed for.
    given = {"C1": ow.resolve(None, {"designOverwrites": {"momentMagnifiers": {"deltaNs": 1.25}}})}
    axis = _about_y(_context(piece, given).column("C1", SECTION, [piece], False, EC))
    assert axis.check["slenderness"]["deltaNs"] == 1.25
    assert axis.mc[0] == pytest.approx(1.25 * 100e6)
    assert "δns = 1.25 (type overwrite)" in axis.check["note"]


def test_framing_overwrite_braced_and_sway() -> None:
    # test_design_slender's sway storey (Q = 0.0667 > 0.05).
    sway = [_rows(0.0, 200e3, -150e3, vz=1e5)]
    total = [_rows(-2e6, 20e3, -10e3) + sway[0]]
    piece = _piece(6.0, total, sway, [_rows(-1.2e6, 0.0, 0.0)])
    disp = [{2: np.array([0.02, 0, 0, 0, 0, 0]), 3: np.array([0.02, 0, 0, 0, 0, 0])}]
    options = SlenderOptions(drift_factor=1.0)
    auto = _about_y(_context(piece, {}, options, disp).column("C1", SECTION, [piece], False, EC))
    assert auto.check["slenderness"]["sway"] is True
    braced = {"C1": ow.resolve({"designOverwrites": {"framing": "braced"}}, None)}
    axis = _about_y(
        _context(piece, braced, options, disp).column("C1", SECTION, [piece], False, EC)
    )
    s = axis.check["slenderness"]
    assert s["sway"] is False and s["framing"] == "braced" and s["deltaS"] is None
    assert s["k"] == 1.0  # nonsway k (unity)
    assert axis.check["name"].startswith("Slenderness about y (nonsway")
    assert "designed as braced (overwrite)" in axis.check["note"]
    # A gravity-only column forced to sway takes the sway chart's k (ψ = 1, 1: 1.32).
    total = [_rows(-3e6, 60e3, 100e3)]
    gravity = _piece(6.0, total, [np.zeros((STATIONS, 6))], [_rows(-1.5e6, 0, 0)])
    forced = {"C1": ow.resolve(None, {"designOverwrites": {"framing": "sway"}})}
    axis = _about_y(_context(gravity, forced).column("C1", SECTION, [gravity], False, EC))
    assert axis.check["slenderness"]["sway"] is True
    assert axis.check["slenderness"]["k"] == pytest.approx(1.32, abs=5e-3)
    assert "designed as sway (type overwrite)" in axis.check["note"]


def test_steel_length_overwrites() -> None:
    lengths = MemberLengths.simple(6.0)
    assert lengths.ltb_top.longest() == pytest.approx(6.0)
    r = ow.resolve(
        {"designOverwrites": {"Lb": 2000, "k3": 1.5}}, {"designOverwrites": {"Lu2": 3000}}
    )
    options = ow.steel_length_options(r)
    assert options.k["x"] == 1.5 and options.unbraced == {"y": 3.0, "ltb": 2.0}
    found = MemberLengths.simple(6.0, k=options.k).overwritten(options)
    assert found.ltb_top.points == [0.0, 2.0, 4.0, 6.0]
    assert found.ltb_bottom.longest() == pytest.approx(2.0)
    assert found.y.longest() == pytest.approx(3.0) and found.x.longest() == pytest.approx(6.0)
    assert found.effective("x", 1.0) == (1.5, pytest.approx(6000.0), False)
    note = slenderness_note(found)
    assert "about y 3.00 m (type overwrite)" in note
    assert "(bottom) (overwrite)" in note and "K = 1.5 (overwrite) / 1" in note
    # Longer than the member: the member's length, with a note.
    long = MemberLengths.simple(6.0).overwritten(LengthOptions(unbraced={"x": 8.0}))
    assert long.x.points == [0.0, 6.0] and "longer than the member" in long.notes[0]
    # SteelOptions carry them into the member check.
    steel = ow.steel_options(r)
    assert steel.lengths.unbraced["ltb"] == 2.0 and steel.lengths.k["x"] == 1.5
    assert ow.steel_options(None).lengths.unbraced == {}


def _free_top(overwrites: dict, piece: _Piece):
    """test_design_slender's column 4 m tall and nothing at its top (a stub between the
    levels): neither end framed, no alignment chart k."""
    project, building, types = _frame(6.0)
    project["elements"] = project["elements"][:1]
    project["nodes"] = project["nodes"][:2]
    project["nodes"][1]["coords"] = [0, 0, 4.0]
    column = building.elements[0].model_copy(update={"top": 4000})
    building = building.model_copy(update={"elements": [column]})
    return SlenderContext(
        project, building, types, {}, {"C1": [piece]}, ["1.4D"], [{}], overwrites=overwrites
    )


def test_sway_overwrite_of_an_unframed_column_takes_the_cantilever_k() -> None:
    # Overwritten as sway, an unframed column takes k = 2 (the cantilever's, the least for a
    # sway column with a free end), not the nonsway k = 1, and says so.
    total = [_rows(-3e6, 60e3, 100e3)]
    stub = _piece(4.0, total, [np.zeros((STATIONS, 6))], [_rows(-1.5e6, 0, 0)])
    plain = _about_y(_free_top({}, stub).column("C1", SECTION, [stub], False, EC))
    assert plain.check["slenderness"]["k"] == 1.0 and plain.check["slenderness"]["kSway"] is None
    forced = {"C1": ow.resolve(None, {"designOverwrites": {"framing": "sway"}})}
    axis = _about_y(_free_top(forced, stub).column("C1", SECTION, [stub], False, EC))
    s = axis.check["slenderness"]
    assert s["sway"] is True and s["k"] == 2.0
    assert s["klu_r"] == pytest.approx(2.0 * 4000 / 150, rel=1e-3)  # 53.3 > 22: slender
    assert not s["neglected"]
    note = axis.check["note"]
    assert "k = 2.00 (sway, an end not framed: the cantilever's k" in note
    assert "designed as sway (type overwrite)" in note and "give δs" in note
    # A k given wins, without the note; a δs given is used.
    given = {
        "C1": ow.resolve(
            {"designOverwrites": {"k2": 1.6, "momentMagnifiers": {"deltaS": 1.2}}},
            {"designOverwrites": {"framing": "sway"}},
        )
    }
    axis = _about_y(_free_top(given, stub).column("C1", SECTION, [stub], False, EC))
    assert axis.check["slenderness"]["k"] == 1.6
    assert axis.check["slenderness"]["deltaS"] == pytest.approx(1.2)
    assert "cantilever" not in axis.check["note"] and "k = 1.60 (overwrite)" in axis.check["note"]

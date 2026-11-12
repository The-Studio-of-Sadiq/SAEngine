"""3D stratigraphy and fence diagrams from the boreholes (saengine.soil.stratigraphy)."""

from __future__ import annotations

import itertools

import pytest

from saengine.library.soil import SoilReport
from saengine.soil import stratigraphy


def _hole(id_, x, y, layers, water=None, ground=None):
    data = {
        "id": id_,
        "x": x,
        "y": y,
        "layers": [
            {"top": top, "bottom": bottom, "soilType": kind} for top, bottom, kind in layers
        ],
    }
    if water is not None:
        data["waterTable"] = water
    if ground is not None:
        data["groundLevel"] = ground
    return data


def _report(*holes, **extra):
    return SoilReport.model_validate({"boreholes": list(holes), **extra})


def test_correlation_inserts_pinched_out_units():
    master, assigned = stratigraphy.correlate([["fill", "clay", "sand"], ["fill", "sand"]])
    assert master == ["fill", "clay", "sand"]
    assert assigned == [[0, 1, 2], [0, 2]]


def test_correlation_keeps_units_only_one_borehole_has():
    master, _ = stratigraphy.correlate([["clay", "sand"], ["clay", "silt", "sand"]])
    assert master == ["clay", "silt", "sand"]


def test_neighbouring_layers_of_one_type_are_one_stratum():
    report = _report(
        _hole("BH-1", 0, 0, [(0, 1000, "clay"), (1000, 3000, "clay"), (3000, 6000, "sand")])
    )
    merged = stratigraphy.strata(report, report.boreholes[0])
    assert [(s.key, s.top, s.bottom) for s in merged] == [("clay", 0.0, -3.0), ("sand", -3.0, -6.0)]


def test_idw_passes_through_the_boreholes():
    points = [(0.0, 0.0, -2.0), (10.0, 0.0, -4.0)]
    assert stratigraphy.idw(points, 0.0, 0.0) == -2.0
    assert stratigraphy.idw(points, 5.0, 0.0) == pytest.approx(-3.0)


def test_surfaces_and_fence():
    report = _report(
        _hole("BH-1", 0, 0, [(0, 2000, "fill"), (2000, 6000, "clay"), (6000, 12000, "sand")], 1500),
        _hole("BH-2", 20000, 0, [(0, 1000, "fill"), (1000, 12000, "sand")], 2500),
        _hole(
            "BH-3", 10000, 15000, [(0, 1500, "fill"), (1500, 4000, "clay"), (4000, 10000, "sand")]
        ),
        groundLevel=0.0,
    )
    model = stratigraphy.build(report)
    assert [u["key"] for u in model["units"]] == ["fill", "clay", "sand"]
    bh2 = next(b for b in model["boreholes"] if b["id"] == "BH-2")
    # clay pinched out at BH-2: its top and bottom are both the bottom of the fill
    assert bh2["surfaces"] == [0.0, -1.0, -1.0, -12.0]
    grid = model["grid"]
    assert grid is not None and len(grid["surfaces"]) == 4
    for row in zip(*[[v for line in s for v in line] for s in grid["surfaces"]], strict=True):
        assert all(a >= b for a, b in itertools.pairwise(row))  # kept in order
    fence = model["fences"][0]
    assert fence["id"] == "A"
    assert {b["id"] for b in fence["boreholes"]} == {"BH-1", "BH-2", "BH-3"}
    # the fence passes exactly through the logs at the boreholes
    for b in fence["boreholes"]:
        k = next(i for i, s in enumerate(fence["stations"]) if s["distance"] == b["distance"])
        hole = next(h for h in model["boreholes"] if h["id"] == b["id"])
        assert [s[k] for s in fence["surfaces"]] == pytest.approx(hole["surfaces"])
    assert fence["water"] is not None


def test_given_fence_and_coincident_boreholes():
    report = _report(
        _hole("BH-1", 0, 0, [(0, 3000, "clay"), (3000, 9000, "sand")]),
        _hole("BH-2", 0, 0, [(0, 5000, "clay"), (5000, 9000, "sand")]),
        stratigraphy={"fences": [{"id": "F1", "boreholes": ["BH-2", "BH-1"]}]},
    )
    model = stratigraphy.build(report)
    assert model["grid"] is None
    fence = model["fences"][0]
    assert fence["id"] == "F1" and fence["schematic"]
    assert fence["surfaces"][1][0] == pytest.approx(-5.0)
    assert fence["surfaces"][1][-1] == pytest.approx(-3.0)
    assert any("one plan position" in n for n in model["notes"])


def test_unknown_fence_borehole_is_rejected():
    with pytest.raises(ValueError, match="no borehole"):
        _report(
            _hole("BH-1", 0, 0, [(0, 3000, "clay")]),
            stratigraphy={"fences": [{"id": "F1", "boreholes": ["BH-1", "BH-9"]}]},
        )

"""Alpha 9 L1: precast pieces: sections, marks, handling, erection and connection checks by the
code pack's precast table (written 2026-11-05, not run yet: the test pass is next week)."""

from __future__ import annotations

import math
from types import SimpleNamespace as NS

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design import precast as pc
from saengine.library.objects import ObjectLibrary, PrecastConnection


def _library(**precast) -> ObjectLibrary:
    return ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "kind": "slab",
                    "id": "HC200",
                    "name": "Hollow-core 200",
                    "material": "C40",
                    "thickness": 200,
                    "system": "oneWay",
                    "precast": {"element": "hollowCore", "cores": 6, "coreDiameter": 150},
                },
                {
                    "kind": "beam",
                    "id": "PB1",
                    "name": "Precast beam",
                    "material": "C40",
                    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 800},
                    "precast": {
                        "element": "beam",
                        "inserts": [
                            {"position": 1400, "workingLoad": 50},
                            {"position": 8600, "workingLoad": 50},
                        ],
                        **precast,
                    },
                },
            ]
        }
    )


def test_hollow_core_section() -> None:
    obj = _library().objects[0]
    s = pc.piece_section(obj)
    core = math.pi * 150**2 / 4
    assert s.area == pytest.approx(1200 * 200 - 6 * core)
    assert s.inertia == pytest.approx(1200 * 200**3 / 12 - 6 * math.pi * 150**4 / 64)
    assert s.yb == pytest.approx(100)


def test_double_tee_centroid() -> None:
    obj = NS(id="DT", thickness=600)
    piece = NS(
        element="doubleTee", unitWidth=2400, flangeThickness=50, stemWidth=150, stemSpacing=1200
    )
    s = pc.piece_section(obj, piece)
    area = 2400 * 50 + 2 * 150 * 550
    assert s.area == pytest.approx(area)
    assert s.yb == pytest.approx((2400 * 50 * 575 + 2 * 150 * 550 * 275) / area)


def test_stage_moments_balanced_at_0207() -> None:
    sag, hog = pc.stage_moments(10000, 1.0, 2070, 7930)
    assert sag == pytest.approx(hog, rel=0.01)  # the lifting points that balance the moments
    sag, hog = pc.stage_moments(10000, 1.0, 0, 10000)
    assert sag == pytest.approx(10000**2 / 8)
    assert hog == pytest.approx(0)


def test_slab_units_cut_to_fit() -> None:
    objects = _library()
    building = NS(
        elements=[
            NS(
                kind="slab",
                id="S1",
                type="HC200",
                elevation=3000,
                boundary=[(0, 0), (6000, 0), (6000, 3000), (0, 3000)],
            )
        ]
    )
    pieces = pc.pieces_of(building, objects)
    assert [(p.width, p.count) for p in pieces] == [(1200, 2), (600, 1)]
    assert all(p.length == pytest.approx(6000) for p in pieces)
    assert [p.mark for p in pieces] == ["HC200-1", "HC200-2"]


def test_bearing_span_ratio_bnbc() -> None:
    """BNBC 2020 Part 6 Sec 6.10.6.2.2: ln/180, at least 75 mm for beams."""
    section = pc.Section(400 * 800, 800, 400, 400, 1.0, 1.0, "")
    piece = pc.Piece("PB1-1", "PB1", "beam", 9000, 0, 1, span=9000)
    c = PrecastConnection(id="B1", kind="bearing", bearingLength=60)
    rows = pc.bearing_checks(c, piece, section, 40.0, 200e3, 40.0)
    length = rows[0]
    assert length["demand"] == pytest.approx(75)  # 9000/180 = 50 < 75
    assert length["ok"] is False
    stress = rows[1]
    assert stress["capacity"] == pytest.approx(0.65 * 0.85 * 40 * (60 - 13) * 400 / 1e3, rel=1e-3)


def test_net_bearing_eurocodes() -> None:
    """EN 1992-1-1 10.9.5.2: a = a1 + a2 + a3 + √(Δa2² + Δa3²)."""
    with code_context.using(registry.load("eurocodes")):
        section = pc.Section(1200 * 200, 200, 1200, 100, 1.0, 1.0, "")
        piece = pc.Piece("HC-1", "HC", "hollowCore", 7200, 1200, 1, span=7200)
        c = PrecastConnection(id="B1", kind="bearing", bearingLength=100, support="precast")
        row = pc.bearing_checks(c, piece, section, 40.0, 60e3, 25.0)[0]
        # σEd/fcd small: a1 = 25 (Table 10.2), a2 = 5 (C30+), a3 = max(5, cover 25),
        # Δa2 = clamp(7200/1200, 10, 30) = 10, Δa3 = 7200/2500
        assert row["demand"] == pytest.approx(25 + 5 + 25 + math.hypot(10, 7200 / 2500), abs=1)


def test_dowel_action_eccentricity_reduces() -> None:
    with code_context.using(registry.load("eurocodes")):
        near = PrecastConnection(id="D", kind="dowel", dowels=2, dowelDia=20, eccentricity=0)
        far = PrecastConnection(id="D", kind="dowel", dowels=2, dowelDia=20, eccentricity=40)
        a = pc.dowel_checks(near, 40.0, 500.0, 50e3, 0.0, 1e5)[0]["capacity"]
        b = pc.dowel_checks(far, 40.0, 500.0, 50e3, 0.0, 1e5)[0]["capacity"]
        fcd, fyd = 40 / 1.5, 500 / 1.15
        assert a == pytest.approx(2 * 20**2 * math.sqrt(fcd * fyd) / 1.3 / 1e3, rel=1e-3)
        assert b < a


def test_hanging_beam_factor() -> None:
    rule = NS(sweepDivisor=960, insertTolerance=6)
    found = pc.hanging_beam(12000, 7.5, 1000, 30000, 400**3 * 800 / 12, 400, rule)
    assert found["ei"] == pytest.approx(12000 / 960 + 6)
    assert found["fs"] == pytest.approx(400 / (found["zo"] + found["ei"]))


def test_handling_rows_default_pack() -> None:
    obj = _library().objects[1]
    piece = pc.Piece("PB1-1", "PB1", "beam", 10000, 0, 1, span=10000)
    section = pc.piece_section(obj)
    rows = pc.handling_checks(obj, piece, section, 40.0, 2400.0)
    names = [r["name"] for r in rows]
    assert "Handling, stripping: concrete tension" in names
    insert = next(r for r in rows if r["name"] == "Lifting inserts: load per insert")
    weight = 400 * 800 * 1e-9 * 2400 * 9.80665 * 10000 / 1e3  # kN
    assert insert["demand"] == pytest.approx(
        1.3 * weight / 2 / math.sin(math.radians(60)), rel=1e-3
    )


def test_wrong_element_for_kind_refused() -> None:
    with pytest.raises(ValueError, match="cannot be a precast"):
        ObjectLibrary.model_validate(
            {
                "objects": [
                    {
                        "kind": "slab",
                        "id": "S",
                        "name": "S",
                        "material": "C",
                        "thickness": 200,
                        "precast": {"element": "column"},
                    }
                ]
            }
        )

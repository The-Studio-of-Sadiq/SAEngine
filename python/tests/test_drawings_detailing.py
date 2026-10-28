"""Reinforcement detailing (BNBC 2020 Part 6 Chapter 8): development and lap lengths, hooks,
bar cut-off, the detailing model of synthetic projects and the stability of the bar marks,
against hand calculations."""

from __future__ import annotations

import itertools
import json
import math

import pytest

from saengine.drawings.detailing import (
    assign_marks,
    beam_cutoffs,
    bend_diameter,
    column_lap,
    column_splice_region,
    continuous_top_bars,
    detailing_model,
    development_compression,
    development_tension,
    extension_beyond_cutoff,
    hook_development,
    hook_development_seismic,
    inflection_points,
    ktr,
    lap_compression,
    lap_tension,
    negative_extension,
    positive_into_support,
    seismic_hook,
    space,
    splice_class,
    split_run,
    standard_hook,
    stirrup_length,
    uniform_moment,
    up,
)
from saengine.library import default_material_library


def dump(model) -> str:
    return json.dumps(model.model_dump(mode="json", by_alias=True, exclude_none=True))


MATERIALS = dump(default_material_library())

# ─────────────────────────────────────── the rules by hand ───────────────────────────────────────


def test_development_length_of_a_16_mm_bar_in_25_mpa_concrete() -> None:
    # 8.2.3.2, first row, 19 mm and smaller: fy ψt ψe / (2.1 λ √f'c) db = 420 / (2.1 · 5) · 16
    simple = development_tension(16, 420, 25)
    assert simple.value == pytest.approx(640.0)
    assert "8.2.3.2" in simple.clause and "1077" in simple.clause
    # top bar (more than 300 mm of concrete below): ψt = 1.3
    assert development_tension(16, 420, 25, top=True).value == pytest.approx(832.0)
    # other cases: 1.4 (the cell is blank in the gazette)
    other = development_tension(16, 420, 25, spacing_ok=False)
    assert other.value == pytest.approx(420 / (1.4 * 5) * 16)
    assert "blank" in other.clause
    # Eq. 6.8.1: fy ψt ψe ψs / (1.1 λ √f'c (cb + Ktr)/db) db, ψs = 0.8, (cb + Ktr)/db <= 2.5
    general = development_tension(16, 420, 25, method="general", cb=40, k_tr=0)
    assert general.value == pytest.approx(420 * 0.8 / (1.1 * 5 * 2.5) * 16)  # 391.0
    assert general.value == pytest.approx(390.98, abs=0.01)
    tight = development_tension(16, 420, 25, method="general", cb=30)
    assert tight.value == pytest.approx(420 * 0.8 / (1.1 * 5 * 30 / 16) * 16)
    # Ktr = 40 Atr / (s n): two Ø10 legs at 150 mm, 3 bars
    assert ktr(2 * 78.54, 150, 3) == pytest.approx(13.96, abs=0.01)
    capped = development_tension(16, 420, 25, method="general", cb=40, k_tr=50)
    assert capped.value == pytest.approx(general.value)  # the confinement term at most 2.5
    # at least 300 mm (8.2.3.1); √f'c at most 8.3 MPa (8.2.2)
    assert development_tension(10, 280, 70).value == 300.0
    assert development_tension(10, 280, 70, minimum=False).value == pytest.approx(
        280 / (2.1 * 8.3) * 10
    )
    with pytest.raises(ValueError):
        development_tension(16, 420, 25, method="general")


def test_development_in_compression_and_hooks() -> None:
    # 8.2.4.2: max(0.24 fy db / √f'c, 0.043 fy db) = max(322.6, 289.0)
    assert development_compression(16, 420, 25).value == pytest.approx(322.56)
    assert development_compression(16, 420, 25, confined=True).value == pytest.approx(241.92)
    assert development_compression(10, 420, 25).value == pytest.approx(201.6)
    # 8.2.6: ldh = 0.24 ψe fy db / (λ √f'c) = 0.24 · 420 · 16 / 5 = 322.6, × 0.7 with cover
    assert hook_development(16, 420, 25).value == pytest.approx(322.56)
    assert hook_development(16, 420, 25, cover=True).value == pytest.approx(225.79, abs=0.01)
    assert hook_development(10, 420, 60, cover=True).value == 150.0  # at least 150 mm
    # 8.3.7.4(a): max(8 db, 150, fy db / (5.4 √f'c)) = 420 · 16 / 27 = 248.9
    assert hook_development_seismic(16, 420, 25).value == pytest.approx(248.89, abs=0.01)


def test_hook_geometry_and_bend_diameters() -> None:
    assert bend_diameter(16).value == 96  # 6 db (Table 6.8.1)
    assert bend_diameter(32).value == 256  # 8 db
    assert bend_diameter(10, transverse=True).value == 40  # 4 db (8.1.2.2(b))
    assert bend_diameter(20, transverse=True).value == 120  # above 16 mm: Table 6.8.1
    h90 = standard_hook(16)
    assert (h90.angle, h90.tail) == (90, 192)  # 12 db
    assert h90.leg == pytest.approx(192 + 48 + 16)
    h180 = standard_hook(12, 180)
    assert (h180.angle, h180.tail) == (180, 65)  # max(4 db, 65 mm)
    assert standard_hook(20, 180).tail == 80
    assert standard_hook(10, 90, transverse=True).tail == 60  # 6 db
    assert standard_hook(20, 90, transverse=True).tail == 240  # 12 db for 19-25 mm
    assert standard_hook(10, 135, transverse=True).tail == 60
    s = seismic_hook(10)
    assert (s.angle, s.tail) == (135, 75)  # max(6 db, 75 mm)
    assert seismic_hook(16).tail == 96
    # a 220 x 420 Ø10 stirrup: 2 (210 + 410) - 8·25 + 3π·25 + 2·75
    assert stirrup_length(220, 420, 10, s) == pytest.approx(2 * 620 - 200 + 3 * math.pi * 25 + 150)


def test_splices() -> None:
    # class B: 1.3 ld (ld without its 300 mm minimum), at least 300 mm
    assert lap_tension(16, 420, 25).value == pytest.approx(1.3 * 640)  # 832
    assert lap_tension(16, 420, 25, top=True).value == pytest.approx(1.3 * 832)  # 1081.6
    assert lap_tension(16, 420, 25, cls="A").value == pytest.approx(640)
    assert lap_tension(8, 420, 40, cls="A").value == 300.0
    # bars of different sizes: the larger of ld of the larger bar and the lap of the smaller
    mixed = lap_tension(16, 420, 25, other_db=25)
    ld25 = development_tension(25, 420, 25).value
    assert mixed.value == pytest.approx(max(ld25, 1.3 * 640))
    with pytest.raises(ValueError):
        lap_tension(36, 420, 25)
    assert splice_class(2.0, 0.5) == "A"
    assert splice_class(1.9, 0.5) == "B"
    assert splice_class(2.5, 1.0) == "B"
    # compression laps: 0.071 fy db, + 1/3 below 21 MPa, (0.13 fy - 24) db above 420 MPa
    assert lap_compression(16, 420, 25).value == pytest.approx(477.12)
    assert lap_compression(16, 420, 20).value == pytest.approx(477.12 * 4 / 3)
    assert lap_compression(16, 500, 25).value == pytest.approx((65 - 24) * 16)
    assert lap_compression(10, 420, 25).value == 300.0
    assert column_lap(20, 420, 25, stress="compression", factor=0.83).value == pytest.approx(
        0.071 * 420 * 20 * 0.83
    )
    assert column_lap(20, 420, 25, stress="low", spliced_share=0.5).value == pytest.approx(
        420 / (1.7 * 5) * 20
    )
    assert column_lap(20, 420, 25).value == pytest.approx(1.3 * 420 / (1.7 * 5) * 20)


def test_cut_off_of_a_continuous_beam() -> None:
    # interior span ln = 6 m, w = 20 kN/m, wl²/12 at both supports
    ln, w = 6000.0, 20.0
    m = w * ln**2 / 12  # 60 kN·m
    assert uniform_moment(ln / 2, ln, w, m, m) == pytest.approx(w * ln**2 / 24)
    left, right = inflection_points(ln, w, m, m)
    assert left == pytest.approx((6000 - math.sqrt(12e6)) / 2)  # 1267.9
    assert right == pytest.approx(ln - left)
    cut = beam_cutoffs(ln, w, m, m, share=1 / 3, d=440, db=16, ld=832)
    side = cut["left"]
    # the two thirds stop where M = -m/3: x² - 6000 x + 4e6 = 0 -> 763.9; + max(d, 12 db)
    assert side["notNeeded"] == pytest.approx((6000 - math.sqrt(20e6)) / 2)
    assert side["extra"] == pytest.approx(side["notNeeded"] + 440)  # 1203.9 > ld 832
    # the continuing third: beyond the point of inflection by max(d, ln/16, 12 db) = 440
    assert side["continuing"] == pytest.approx(left + 440)
    assert cut["right"]["extra"] == pytest.approx(side["extra"])
    # the practice figure 0.30 ln = 1800 mm covers both
    assert 0.3 * ln > side["continuing"]
    assert extension_beyond_cutoff(300, 25).value == 300
    assert negative_extension(300, 16, 8000).value == 500  # ln/16
    # a simply supported end: no inflection on that side
    simple = beam_cutoffs(ln, w, 0.0, m, share=1 / 3, d=440, db=16, ld=832)
    assert simple["left"] is None and simple["right"] is not None
    assert positive_into_support(4, continuous=True) == 1
    assert positive_into_support(4, continuous=False) == 2
    assert continuous_top_bars(3) == 2
    assert continuous_top_bars(6) == 2
    assert continuous_top_bars(7) == 3
    assert continuous_top_bars(6, required_share=0.6) == 4
    assert column_splice_region(2700) == (675, 2025)


def test_spacing_zones_and_runs() -> None:
    rows = space(0, 3000, 150, [(0, 600, 100, "lo"), (2400, 3000, 100, "lo")], 50)
    assert [r["zone"] for r in rows] == ["lo", "middle", "lo"]
    assert rows[0]["count"] == math.ceil(550 / 100) + 1
    assert rows[1]["count"] == math.ceil(1800 / 150)
    assert sum(r["count"] for r in rows) == 7 + 12 + 6
    pieces, laps, ok = split_run(0, 20_000, 1000, [(8000, 12_000)], 12_000)
    assert ok and laps == [(11_000, 12_000)] and pieces == [(0, 12_000), (11_000, 20_000)]
    _, _, ok = split_run(0, 20_000, 1000, [(13_000, 14_000)], 12_000)
    assert not ok
    assert up(1001) == 1025 and up(1000) == 1000


# ─────────────────────────────────────── synthetic projects ───────────────────────────────────────

REBAR = "B420DWR"
CONCRETE = "C24.1"


def _objects(extra: list[dict] | None = None) -> str:
    objects = [
        {
            "id": "C300",
            "name": "Column 300x300",
            "kind": "column",
            "material": CONCRETE,
            "profile": {"shape": "rectangle", "xDim": 300, "yDim": 300},
            "reinforcement": {
                "material": REBAR,
                "cover": 40,
                "longitudinal": [{"position": "perimeter", "count": 4, "dia": 16}],
                "transverse": {"type": "tie", "dia": 10, "spacing": 150, "legs": 2},
            },
        },
        {
            "id": "B250",
            "name": "Beam 250x450",
            "kind": "beam",
            "material": CONCRETE,
            "profile": {"shape": "rectangle", "xDim": 250, "yDim": 450},
            "reinforcement": {
                "material": REBAR,
                "cover": 40,
                "longitudinal": [
                    {"position": "top", "count": 4, "dia": 16},
                    {"position": "bottom", "count": 3, "dia": 16},
                ],
                "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
            },
        },
        {
            "id": "S125",
            "name": "Slab 125",
            "kind": "slab",
            "material": CONCRETE,
            "thickness": 125,
            "reinforcement": {
                "material": REBAR,
                "cover": 20,
                "bottomX": {"dia": 10, "spacing": 150},
                "bottomY": {"dia": 10, "spacing": 150},
                "topX": {"dia": 10, "spacing": 200},
                "topY": {"dia": 10, "spacing": 200},
            },
        },
        {
            "id": "F1500",
            "name": "Footing 1500",
            "kind": "footing",
            "material": CONCRETE,
            "length": 1500,
            "width": 1500,
            "thickness": 450,
            "reinforcement": {
                "material": REBAR,
                "cover": 75,
                "bottomX": {"dia": 12, "spacing": 150},
                "bottomY": {"dia": 12, "spacing": 150},
            },
        },
    ] + (extra or [])
    return json.dumps({"schema": "saengine.objects/1", "objects": objects})


def _frame(extra_elements: list[dict] | None = None) -> str:
    """Two bays of 5 m along x on three columns, two storeys of 3 m, footings, two slabs."""
    elements: list[dict] = []
    for i, x in enumerate((0, 5000, 10000), start=1):
        elements.append(
            {"id": f"C{i}", "type": "C300", "kind": "column", "position": [x, 0],
             "bottom": 0, "top": 3000}
        )  # fmt: skip
        elements.append(
            {"id": f"C{i}U", "type": "C300", "kind": "column", "position": [x, 0],
             "bottom": 3000, "top": 6000}
        )  # fmt: skip
        elements.append(
            {"id": f"F{i}", "type": "F1500", "kind": "footing", "position": [x, 0],
             "elevation": 0}
        )  # fmt: skip
    for level, tag in ((3000, ""), (6000, "R")):
        elements.append(
            {"id": f"B1{tag}", "type": "B250", "kind": "beam", "start": [0, 0],
             "end": [5000, 0], "elevation": level}
        )  # fmt: skip
        elements.append(
            {"id": f"B2{tag}", "type": "B250", "kind": "beam", "start": [5000, 0],
             "end": [10000, 0], "elevation": level}
        )  # fmt: skip
    for k, (x0, x1) in enumerate(((0, 5000), (5000, 10000)), start=1):
        elements.append(
            {"id": f"S{k}", "type": "S125", "kind": "slab",
             "boundary": [[x0, -4000], [x1, -4000], [x1, 0], [x0, 0]], "elevation": 3000}
        )  # fmt: skip
    elements += extra_elements or []
    return json.dumps(
        {
            "schema": "saengine.bim/2",
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
                {"id": "L2", "name": "Level 2", "elevation": 6000},
            ],
            "elements": elements,
        }
    )


def _model(**kw):
    texts = {"bim": kw.pop("bim", _frame()), "objects": kw.pop("objects", _objects()),
             "materials": MATERIALS}  # fmt: skip
    return detailing_model(texts=texts, **kw)


def _element(model, element_id):
    return next(e for e in model["elements"] if e["id"] == element_id)


def test_continuous_beam_bars_and_cut_offs() -> None:
    model = _model()
    line = _element(model, "B1+B2")
    assert line["members"] == ["B1", "B2"]
    tops = [b for b in line["bars"] if b["role"] == "top"]
    continuous = [b for b in tops if not b.get("curtailed")]
    extra = [b for b in tops if b.get("curtailed")]
    # 4 top bars: 2 continuous (8.3.4.2(a), at least 1/3), hooked into the end columns
    assert sum(b["count"] for b in continuous) == 2
    assert continuous[0]["shape"] == "U"
    assert continuous[0]["at"]["from"] == pytest.approx(-150 + 50)  # far face + cover + tie
    assert continuous[0]["at"]["to"] == pytest.approx(10150 - 50)
    # the extra bars over the interior column: 0.30 ln from each face, ln = 4700
    fc, fy = 24.1, 420.0
    ld_top = up(development_tension(16, fy, fc, top=True).value)
    interior = next(b for b in extra if b["at"]["support"] == "C2")
    extent = up(max(0.3 * 4700, ld_top))
    assert interior["shape"] == "straight"
    assert interior["dims"]["A"] == pytest.approx(2 * extent + 300)
    assert interior["at"]["from"] == pytest.approx(4850 - extent)
    assert interior["count"] == 2
    # at the end columns: an L with the 12 db hook down into the column
    end = next(b for b in extra if b["at"]["support"] == "C1")
    assert end["shape"] == "L"
    assert end["dims"]["B"] == pytest.approx(standard_hook(16).leg)
    assert end["dims"]["A"] == pytest.approx(extent + 300 - 50)
    # bottom bars all run into the supports, hooked at the ends (8.2.8.1, 8.2.8.2)
    bottoms = [b for b in line["bars"] if b["role"] == "bottom"]
    assert sum(b["count"] for b in bottoms) == 3 and bottoms[0]["shape"] == "U"
    # hooked anchorage checked against the column depth less cover and tie
    hooks = [c for c in line["checks"] if c["name"].startswith("Hooked")]
    assert hooks and all(c["provided"] == 250 for c in hooks)
    assert all(
        c["required"] == pytest.approx(hook_development(16, fy, fc).value, abs=0.1) for c in hooks
    )
    # stirrups per clear span, the first 50 mm from the face
    rows = line["transverse"]
    assert rows[0]["from"] == pytest.approx(150 + 50)
    assert (
        sum(r["count"] for r in rows)
        == next(b for b in line["bars"] if b["role"] == "stirrup")["count"]
    )


def test_column_laps_and_starter_bars_into_the_footing() -> None:
    model = _model()
    ground = _element(model, "C1")
    upper = _element(model, "C1U")
    fc, fy = 24.1, 420.0
    lap = up(column_lap(16, fy, fc).value)  # class B tension (default)
    # without seismic settings: ordinary detailing, laps just above each floor
    vertical = next(b for b in ground["bars"] if b["role"] == "vertical")
    assert vertical["at"]["from"] == 0
    assert vertical["at"]["to"] == pytest.approx(3000 + lap)  # laps into the column above
    assert vertical["shape"] == "straight" and vertical["count"] == 4
    lap_rows = [x for x in ground["laps"] if x.get("with") == "C1U"]
    assert lap_rows and lap_rows[0]["from"] == 3000 and lap_rows[0]["length"] == lap
    # starter bars: on the footing's bottom mesh with a 90° hook turned to the centre
    starter = next(b for b in ground["bars"] if b["role"] == "starter")
    bottom = 0 - 450 + 75 + 2 * 12
    assert starter["shape"] == "L"
    assert starter["at"]["from"] == pytest.approx(bottom)
    assert starter["at"]["to"] == pytest.approx(lap)
    assert starter["dims"]["A"] == pytest.approx(lap - bottom)
    assert starter["dims"]["B"] == pytest.approx(standard_hook(16).leg)
    dowel = next(c for c in ground["checks"] if c["name"].startswith("Column bars into"))
    assert dowel["required"] == pytest.approx(hook_development(16, fy, fc).value, abs=0.01)
    assert dowel["provided"] == pytest.approx(450 - 75 - 2 * 12)  # above the two mesh layers
    # the top storey: bars to 40 mm below the top, hooked into the roof beam
    top = next(b for b in upper["bars"] if b["role"] == "vertical")
    assert top["shape"] == "L" and top["at"]["to"] == 6000 - 40
    assert not any(b["role"] == "starter" for b in upper["bars"])
    # ties from half a spacing above the floor
    assert ground["transverse"][0]["from"] == pytest.approx(75)
    # the footing bars of the same column: straight when the length from the face is enough
    footing = _element(model, "F1")
    assert {b["role"] for b in footing["bars"]} == {"bottom"}


def test_special_column_lap_in_the_centre_half() -> None:
    from saengine.drawings import detailing as d

    start, fits = d._lap_start(2700, 1325, True)
    assert start == pytest.approx(1350 - 662.5)
    assert fits
    lo, hi = column_splice_region(2700)
    assert lo <= start and start + 1325 <= hi
    start, fits = d._lap_start(2000, 1325, True)
    assert not fits
    assert d._lap_start(2700, 1325, False) == (0.0, True)


def test_slab_top_bar_extent_over_a_shared_beam() -> None:
    model = _model()
    s1, s2 = _element(model, "S1"), _element(model, "S2")
    # the shared edge x = 5000 has no beam in this frame (beams run along y = 0 only):
    # still continuous, top bars over it to 0.30 ln either side
    over = [b for b in s1["bars"] if b["role"] == "top" and b["at"].get("slabs") == ["S1", "S2"]]
    assert len(over) == 1
    bar = over[0]
    ln = 5000.0  # no support width
    ld = development_tension(10, 420, 24.1).value
    ext = up(max(0.3 * ln, ld))
    assert bar["dims"]["A"] == pytest.approx(2 * ext)
    assert bar["at"]["from"] == pytest.approx(5000 - ext)
    # not repeated on S2
    assert not any(b["at"].get("slabs") == ["S1", "S2"] for b in s2["bars"])
    # the beam edge y = 0 is a discontinuous supported edge: L bars bent down into the beam
    edge = [b for b in s1["bars"] if b["role"] == "top" and b["at"].get("support") == "B1"]
    assert edge and edge[0]["shape"] == "L"
    # the 450 mm edge beam is deep enough for a standard 90° hook (12 db) down into it
    assert edge[0]["dims"]["B"] == pytest.approx(standard_hook(10).leg)
    ln_y = 4000 - 250 / 2
    ext_y = up(max(0.3 * ln_y, ld))
    assert edge[0]["dims"]["A"] == pytest.approx(ext_y + 250 - 20)
    hooked = next(c for c in s1["checks"] if c["name"].startswith("Top Y bars Ø10 hooked"))
    assert hooked["required"] == pytest.approx(hook_development(10, 420, 24.1).value, abs=0.1)
    assert hooked["provided"] == pytest.approx(250 - 20) and hooked["ok"]
    assert "8.2.9.1" in hooked["clause"]
    # bottom bars: to the far face of the edge beam less cover at y = 0, to the slab edge at
    # the free edge y = -4000
    by = next(b for b in s1["bars"] if b["role"] == "bottom" and b["at"]["direction"] == "Y")
    assert by["at"]["from"] == pytest.approx(-4000 + 20)
    assert by["at"]["to"] == pytest.approx(0 + 125 - 20)
    bx = next(b for b in s1["bars"] if b["role"] == "bottom" and b["at"]["direction"] == "X")
    assert bx["at"]["to"] == pytest.approx(5000 + 150)  # 150 mm past the edge (no beam)
    full = _model(options={"slabTop": "full"})
    assert any(b["role"] == "top" and not b.get("curtailed") for b in _element(full, "S1")["bars"])


def test_marks_are_unique_stable_and_grouped() -> None:
    first = _model()
    again = _model()
    assert first["marks"] == again["marks"]
    marks = first["marks"]
    # identical bars of one type share a mark across members: the ties of all six columns
    ties = [m for m in marks.values() if m["role"] == "tie"]
    assert len(ties) == 1 and ties[0]["mark"] == "C1-H1"
    assert len(ties[0]["elements"]) == 6
    assert all("-" in mark for mark in marks)
    for element in first["elements"]:
        for bar in element["bars"]:
            assert bar["mark"] in marks
            assert marks[bar["mark"]]["dia"] == bar["dia"]
    # a new beam type and an extra beam: the earlier marks keep their names
    extra_type = {
        "id": "A100",  # sorts before B250: would take code B1 without the previous marks
        "name": "Beam 200x400",
        "kind": "beam",
        "material": CONCRETE,
        "profile": {"shape": "rectangle", "xDim": 200, "yDim": 400},
        "reinforcement": {
            "material": REBAR,
            "cover": 40,
            "longitudinal": [
                {"position": "top", "count": 2, "dia": 12},
                {"position": "bottom", "count": 2, "dia": 12},
            ],
            "transverse": {"type": "stirrup", "dia": 8, "spacing": 150, "legs": 2},
        },
    }
    extra_beam = {"id": "B9", "type": "A100", "kind": "beam", "start": [0, 0],
                  "end": [0, -4000], "elevation": 3000}  # fmt: skip
    changed = _model(
        bim=_frame([extra_beam]), objects=_objects([extra_type]), previous=first["marks"]
    )
    for mark, row in first["marks"].items():
        assert changed["marks"][mark]["signature"] == row["signature"]
    new = [m for m in changed["marks"].values() if m["type"] == "A100"]
    assert new and all(m["mark"].startswith("B2-") for m in new)
    # without the previous marks the new type would have renumbered the old ones
    fresh = _model(bim=_frame([extra_beam]), objects=_objects([extra_type]))
    assert any(m["mark"].startswith("B1-") and m["type"] == "A100" for m in fresh["marks"].values())


def test_assign_marks_directly() -> None:
    def bar(letter, length):
        return {"role": "top", "dia": 16.0, "shape": "straight", "count": 2,
                "dims": {"A": length}, "length": length, "_letter": letter}  # fmt: skip

    elements = [
        {"id": "X1", "kind": "beam", "type": "T1", "bars": [bar("T", 3000), bar("B", 3000)]},
        {"id": "X2", "kind": "beam", "type": "T1", "bars": [bar("T", 3000)]},
        {"id": "X3", "kind": "beam", "type": "T2", "bars": [bar("T", 3000)]},
    ]
    marks = assign_marks(elements)
    assert elements[0]["bars"][0]["mark"] == elements[1]["bars"][0]["mark"] == "B1-T1"
    assert elements[0]["bars"][1]["mark"] == "B1-B1"
    assert elements[2]["bars"][0]["mark"] == "B2-T1"
    assert marks["B1-T1"]["count"] == 4 and marks["B1-T1"]["elements"] == ["X1", "X2"]


def test_sample_project_is_detailed() -> None:
    from pathlib import Path

    root = Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples"
    model = detailing_model(root / "Sample Frame")
    kinds = {e["kind"] for e in model["elements"]}
    assert {"column", "beam", "slab", "wall", "staircase", "footing"} <= kinds
    assert json.dumps(model)  # JSON-ready
    for element in model["elements"]:
        for bar in element["bars"]:
            assert bar["length"] > 0 and bar["count"] >= 0 and bar["mark"]
            assert bar["shape"] in ("straight", "L", "U", "crank", "stirrup", "helix", "special")
        for row in element["transverse"]:
            assert row["mark"]


def test_design_report_frames_zones_and_failures() -> None:
    objects = json.loads(_objects())
    column = next(o for o in objects["objects"] if o["id"] == "C300")
    column["reinforcement"]["transverse"]["zone"] = {"spacing": 100}
    report = {
        "elements": [
            {"id": "C1", "ok": False, "utilisation": 1.2,
             "detailing": {"frameType": "special", "role": "lateral", "zones": {"lo": 500}}},
        ]
    }  # fmt: skip
    model = _model(objects=json.dumps(objects), design_report=report)
    c1 = _element(model, "C1")
    assert any("fails" in n for n in c1["notes"])
    hc = 3000 - 450  # under the 450 mm beams at the top
    lap = up(column_lap(16, 420, 24.1).value)
    vertical = next(b for b in c1["bars"] if b["role"] == "vertical")
    assert vertical["at"]["from"] == pytest.approx(max(hc / 4, hc / 2 - lap / 2))
    zones = [r["zone"] for r in c1["transverse"]]
    assert zones[0] == "lo" and "joint" in zones and "middle" in zones
    first = c1["transverse"][0]
    assert first["spacing"] == 100 and first["to"] == pytest.approx(500)
    assert first["from"] == pytest.approx(50)  # so/2 from the floor


def test_required_mid_span_steel_keeps_more_top_bars_continuous() -> None:
    required = {
        "elements": [
            {"element": "B1", "location": "middle", "quantity": "top bars (hogging)",
             "required": 500.0},
        ]
    }  # fmt: skip
    model = _model(required=required)
    line = _element(model, "B1+B2")
    continuous = [b for b in line["bars"] if b["role"] == "top" and not b.get("curtailed")]
    # 500 / (4 · 201) = 0.62 of the bars: 3 continuous
    assert sum(b["count"] for b in continuous) == 3
    full = _model(options={"curtail": False})
    tops = [b for b in _element(full, "B1+B2")["bars"] if b["role"] == "top"]
    assert sum(b["count"] for b in tops) == 4 and not any(b.get("curtailed") for b in tops)


# ─────────────────────────────────────── review fixes ───────────────────────────────────────


def _without(bim: str, kinds: tuple[str, ...]) -> dict:
    data = json.loads(bim)
    data["elements"] = [e for e in data["elements"] if e["kind"] not in kinds]
    return data


def _pairs(xs):
    return list(itertools.pairwise(xs))


def test_special_column_without_a_foundation_starts_at_its_base() -> None:
    bim = _without(_frame(), ("footing",))
    report = {"elements": [{"id": "C1", "detailing": {"frameType": "special", "role": "lateral"}}]}
    model = _model(bim=json.dumps(bim), design_report=report)
    c1 = _element(model, "C1")
    vertical = [b for b in c1["bars"] if b["role"] == "vertical"]
    # nothing to lap with below: the bars start at the base, not at the centre-half lap
    assert vertical and all(b["at"]["from"] == 0 for b in vertical)
    assert not any(b["role"] == "starter" for b in c1["bars"])
    assert any("no foundation under C1" in n for n in c1["notes"])
    lap = up(column_lap(16, 420, 24.1).value)
    assert vertical[0]["at"]["to"] == pytest.approx(3000 + lap)


def _beam_line(xs: tuple[float, ...], beam_type: str = "B250") -> dict:
    data = _without(_frame(), ("beam", "slab", "column", "footing"))
    for i, x in enumerate(xs, start=1):
        data["elements"].append(
            {"id": f"C{i}", "type": "C300", "kind": "column", "position": [x, 0],
             "bottom": 0, "top": 3000}
        )  # fmt: skip
    for k, (a, c) in enumerate(_pairs(xs), start=1):
        data["elements"].append(
            {"id": f"B{k}", "type": beam_type, "kind": "beam", "start": [a, 0], "end": [c, 0],
             "elevation": 3000}
        )  # fmt: skip
    return data


def test_extra_top_bars_stay_inside_the_beam_line() -> None:
    # a 700 mm span next to a 5700 mm one: the extent of the bar over C2 (0.30 x 5700) is
    # longer than the short span
    model = _model(bim=json.dumps(_beam_line((0, 1000, 7000))))
    line = _element(model, "B1+B2")
    tops = [b for b in line["bars"] if b["role"] == "top"]
    s_start, s_end = -150 + 50, 7150 - 50
    for bar in tops:
        assert s_start - 1e-6 <= bar["at"]["from"] and bar["at"]["to"] <= s_end + 1e-6
    extra = [b for b in tops if b.get("curtailed")]
    # the extents over C1 and C2 meet in the short span: one bar, hooked into C1
    merged = next(b for b in extra if b["at"]["supports"] == ["C1", "C2"])
    assert merged["at"]["from"] == pytest.approx(s_start)
    assert merged["shape"] == "L" and merged["at"]["hooks"][0] == "down"
    ld = up(development_tension(16, 420, 24.1, top=True).value)
    extent = up(max(0.3 * 5700, ld))
    assert merged["at"]["to"] == pytest.approx(1150 + extent)
    assert len(extra) == 2  # and the one over C3


def test_special_beam_laps_are_clear_of_2h_from_the_joints() -> None:
    deep = {
        "id": "B300", "name": "Beam 300x700", "kind": "beam", "material": CONCRETE,
        "profile": {"shape": "rectangle", "xDim": 300, "yDim": 700},
        "reinforcement": {
            "material": REBAR, "cover": 40,
            "longitudinal": [{"position": "top", "count": 4, "dia": 20},
                             {"position": "bottom", "count": 3, "dia": 20}],
            "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
        },
    }  # fmt: skip
    report = {
        "elements": [
            {"id": f"B{k}", "detailing": {"frameType": "special", "role": "lateral"}}
            for k in (1, 2, 3)
        ]
    }
    for xs in ((0, 8000, 14000, 20000), (0, 8000, 12000, 18000)):
        model = _model(
            bim=json.dumps(_beam_line(xs, "B300")),
            objects=_objects([deep]),
            design_report=report,
        )
        line = _element(model, "B1+B2+B3")
        faces = [(a + 150, c - 150) for a, c in _pairs(xs)]
        for lap in line["laps"]:
            span = next(f for f in faces if f[0] <= lap["from"] and lap["to"] <= f[1])
            assert lap["from"] - span[0] >= 2 * 700 - 1e-6
            assert span[1] - lap["to"] >= 2 * 700 - 1e-6
        if xs[2] == 14000:
            # the top bars: one lap in span 1 and one in the middle third of span 2
            tops = [x for x in line["laps"] if x["face"] == "top"]
            assert len(tops) == 2 and 10050 <= tops[1]["from"] and tops[1]["to"] <= 11950
        else:
            # span 2 is too short for a lap outside 2 h: said so, no lap placed there
            assert not any(8150 < x["from"] < 11850 for x in line["laps"])
            assert any("no lap location" in n for n in line["notes"])


def _gate_beam(bottom_dia: float = 20) -> dict:
    """The beams of the alpha 6 gate: 300 x 600, 4 Ø20 top, 3 Ø20 bottom, stirrups Ø10 at 125
    with end zones at 100 and no splice spacing of their own."""
    return {
        "id": "B300", "name": "Beam 300x600", "kind": "beam", "material": CONCRETE,
        "profile": {"shape": "rectangle", "xDim": 300, "yDim": 600},
        "reinforcement": {
            "material": REBAR, "cover": 40,
            "longitudinal": [{"position": "top", "count": 4, "dia": 20},
                             {"position": "bottom", "count": 3, "dia": bottom_dia}],
            "transverse": {"type": "stirrup", "dia": 10, "spacing": 125, "legs": 2,
                           "zone": {"length": 1200, "spacing": 100}},
        },
    }  # fmt: skip


SPECIAL_LINE = {
    "elements": [
        {"id": f"B{k}", "detailing": {"frameType": "special", "role": "lateral"}} for k in (1, 2, 3)
    ]
}


def test_an_18_m_special_beam_is_spliced_into_stock_bars() -> None:
    """Three spans of 6 m (the gate's grid along X) on 300 x 300 columns: 18.2 m of continuous
    bar is cut into two bars of at most 12 m, lapped class B outside the 2 h zones."""
    from saengine.drawings.bbs import bar_schedule

    model = _model(
        bim=json.dumps(_beam_line((0, 6000, 12000, 18000), "B300")),
        objects=_objects([_gate_beam()]),
        design_report=SPECIAL_LINE,
    )
    line = _element(model, "B1+B2+B3")
    # Faces 150 | 5850, 6150 | 11850, 12150 | 17850 (clear 5700, a third 1900); the bars end 50
    # inside the end columns (s = -100 and 18100), with 90° hooks of leg 12 db + 3 db + db = 320.
    # ld Ø20 (8.2.3.2, 20 mm and larger): 420 / (1.7 √24.1) × 20 = 1006.5; class B laps:
    # bottom 1.3 × 1006.5 = 1308.5 -> 1325, top (ψt 1.3, 530 mm of concrete below) 1701 -> 1725.
    # No laps within 2 h = 1200 of a face (8.3.4.2(b)).
    hook = standard_hook(20, 90).leg
    assert hook == 320
    lap_b = up(lap_tension(20, 420, 24.1).value)
    lap_t = up(lap_tension(20, 420, 24.1, top=True).value)
    assert (lap_b, lap_t) == (1325, 1725)
    tops = [x for x in line["laps"] if x["face"] == "top"]
    bottoms = [x for x in line["laps"] if x["face"] == "bottom"]
    # Top (2 continuous Ø20): middle thirds 2050-3950, 8050-9950, 14050-15950; the first bar
    # reaches -100 + 12000 - 320 = 11580, so the lap ends at 9950 in span 2: 8225-9950. The
    # second bar, 8225 to 18100 + its hook, is 10195 mm.
    assert [(x["from"], x["to"], x["length"], x["class"]) for x in tops] == [
        (8225, 9950, 1725, "B")
    ]
    # Bottom (3 Ø20): near the supports, from 2 h off the face to max(ln/3, 2 h + lap) = 2525
    # from it: in span 2 7350-8675 and 9325-10650; the last one in reach: 9325-10650, 1200
    # from the face of the third column (8.1.12.2(b), 8.3.4.2(b)).
    assert [(x["from"], x["to"], x["length"], x["class"]) for x in bottoms] == [
        (9325, 10650, 1325, "B")
    ]
    assert tops[0]["marks"] and bottoms[0]["marks"]
    for lap in line["laps"]:
        assert lap["from"] - 6150 >= 1200 and 11850 - lap["to"] >= 1200
    pieces = [b for b in line["bars"] if b["role"] in ("top", "bottom") and not b.get("curtailed")]
    assert sorted((b["role"], b["at"]["from"], b["at"]["to"]) for b in pieces) == [
        ("bottom", -100, 10650), ("bottom", 9325, 18100), ("top", -100, 9950),
        ("top", 8225, 18100),
    ]  # fmt: skip
    for bar in pieces:
        assert sum(bar["dims"].values()) <= 12000
        assert bar["lap"] == (lap_t if bar["role"] == "top" else lap_b)
    assert not any("no lap location" in n or "longer than" in n for n in line["notes"])
    # Hoops over the laps (the type has no splice spacing): min(d/4, 100) with d = 600 - 50 -
    # 10 = 540: 100 mm, closer than the 125 elsewhere; one row over both laps.
    splice = [r for r in line["transverse"] if r["zone"] == "splice"]
    assert [(r["from"], r["to"], r["spacing"]) for r in splice] == [(8225, 10650, 100)]
    assert splice[0]["count"] == math.ceil((10650 - 8225) / 100)
    # The schedule shows the laps and no bar longer than stock.
    schedule = bar_schedule(model)
    rows = [r for r in schedule.rows if r.element == "B1+B2+B3" and r.lap]
    assert {r.lap for r in rows} == {1325, 1725} and all("lap" in r.remarks for r in rows)
    assert all(r.cutting_length <= 12000 for r in schedule.rows)
    assert not any("stock bar" in n for n in schedule.notes)


def test_36_mm_beam_bars_are_not_lapped() -> None:
    model = _model(
        bim=json.dumps(_beam_line((0, 6000, 12000, 18000), "B300")),
        objects=_objects([_gate_beam(bottom_dia=36)]),
        design_report=SPECIAL_LINE,
    )
    line = _element(model, "B1+B2+B3")
    assert not [x for x in line["laps"] if x["face"] == "bottom"]
    assert [x["face"] for x in line["laps"]] == ["top"]
    bottom = [b for b in line["bars"] if b["role"] == "bottom"]
    assert len(bottom) == 1 and "lap" not in bottom[0]
    assert any("mechanical couplers" in n and "8.2.12.2(a)" in n for n in line["notes"])


def _isolated(fid: str, column: str, x: float, length: float = 1500) -> dict:
    return {
        "id": fid, "type": "isolated", "columns": [column], "center": [x, 0], "rotation": 0,
        "length": length, "width": 1500, "thickness": 450, "foundingLevel": -450,
        "material": CONCRETE,
        "reinforcement": {"material": REBAR, "cover": 75,
                          "bottomX": {"dia": 12, "spacing": 150},
                          "bottomY": {"dia": 12, "spacing": 150}},
    }  # fmt: skip


def test_footing_marks_follow_their_definitions_and_labels() -> None:
    big = {
        "id": "F2500", "name": "Footing 2500", "kind": "footing", "material": CONCRETE,
        "length": 2500, "width": 2500, "thickness": 500,
        "reinforcement": {"material": REBAR, "cover": 75, "bottomX": {"dia": 16, "spacing": 150},
                          "bottomY": {"dia": 16, "spacing": 150}},
    }  # fmt: skip
    bim = json.loads(_frame())
    next(e for e in bim["elements"] if e["id"] == "F2")["type"] = "F2500"
    model = _model(bim=json.dumps(bim), objects=_objects([big]))
    f1, f2, f3 = (_element(model, f"F{i}") for i in (1, 2, 3))
    # the 04 Objects type is the element type (as for every other kind), the form is apart
    assert (f1["type"], f2["type"], f3["type"]) == ("F1500", "F2500", "F1500")
    assert f1["form"] == "isolated"
    code1 = {b["mark"].split("-")[0] for b in f1["bars"]}
    code2 = {b["mark"].split("-")[0] for b in f2["bars"]}
    assert code1 == {b["mark"].split("-")[0] for b in f3["bars"]} and code1 != code2
    assert {b["mark"] for b in f1["bars"]} == {b["mark"] for b in f3["bars"]}
    # 9 Substructure: no types; identical definitions share a code named after the first
    sub = {
        "schema": "saengine.substructure/1",
        "foundations": [
            _isolated(f"F{i}", f"C{i}", x, 2500 if i == 2 else 1500)
            for i, x in enumerate((0, 5000, 10000), start=1)
        ],
    }
    texts = {"bim": _frame(), "objects": _objects(), "materials": MATERIALS,
             "substructure": json.dumps(sub)}  # fmt: skip
    model = detailing_model(texts=texts)
    f1, f2, f3 = (_element(model, f"F{i}") for i in (1, 2, 3))
    assert (f1["type"], f2["type"], f3["type"]) == ("F1", "F2", "F1")
    assert all(b["mark"].startswith("F1-") for b in f1["bars"] + f3["bars"])
    assert all(b["mark"].startswith("F2-") for b in f2["bars"])


def test_footing_development_uses_the_real_column_position() -> None:
    sub = {"schema": "saengine.substructure/1", "foundations": [_isolated("F1", "C1", 300)]}
    texts = {"bim": _frame(), "objects": _objects(), "materials": MATERIALS,
             "substructure": json.dumps(sub)}  # fmt: skip
    f1 = _element(detailing_model(texts=texts), "F1")
    # C1 at x = 0, 300 mm off the centre: its near edge is 750 - 300 - 150 = 300 mm away
    along_x = next(c for c in f1["checks"] if c["name"].startswith("bottom X"))
    assert along_x["provided"] == pytest.approx(300 - 75)
    along_y = next(c for c in f1["checks"] if c["name"].startswith("bottom Y"))
    assert along_y["provided"] == pytest.approx(750 - 150 - 75)
    # 225 mm is short of ld (at least 300 mm): hooked U bars along x
    bx = next(b for b in f1["bars"] if b["at"]["direction"] == "X")
    assert bx["shape"] == "U"


def test_general_development_form_is_used_when_chosen() -> None:
    simple = _element(_model(), "B1+B2")
    general = _element(_model(options={"method": "general"}), "B1+B2")
    # bottom Ø16 of a 250 wide beam, 3 bars: cb = min(40 + 10 + 8, half the bar spacing)
    cb = min(58.0, (250 - 2 * 50 - 16) / 2 / 2)
    ld = up(development_tension(16, 420, 24.1, method="general", cb=cb).value)
    assert f"Ø16 {ld:g} mm" in general["notes"][-1]
    assert "general form" in general["notes"][-1]
    assert general["notes"][-1] != simple["notes"][-1]
    with pytest.raises(ValueError):
        _model(options={"method": "exact"})


def test_slab_top_bars_at_a_shallow_edge_beam_are_checked() -> None:
    shallow = {
        "id": "B250S", "name": "Beam 250x150", "kind": "beam", "material": CONCRETE,
        "profile": {"shape": "rectangle", "xDim": 250, "yDim": 150},
        "reinforcement": {
            "material": REBAR, "cover": 40,
            "longitudinal": [{"position": "top", "count": 2, "dia": 12},
                             {"position": "bottom", "count": 2, "dia": 12}],
            "transverse": {"type": "stirrup", "dia": 8, "spacing": 150, "legs": 2},
        },
    }  # fmt: skip
    bim = json.loads(_frame())
    for e in bim["elements"]:
        if e["id"] in ("B1", "B2"):
            e["type"] = "B250S"
    model = _model(bim=json.dumps(bim), objects=_objects([shallow]))
    s1 = _element(model, "S1")
    edge = next(b for b in s1["bars"] if b["role"] == "top" and b["at"].get("support") == "B1")
    assert edge["dims"]["B"] == pytest.approx(150 - 2 * 20)  # shorter than a standard hook
    check = next(c for c in s1["checks"] if "straight length in the support" in c["name"])
    assert check["required"] == pytest.approx(development_tension(10, 420, 24.1).value, abs=0.1)
    assert check["provided"] == pytest.approx(250 - 20) and not check["ok"]
    assert "8.2.9.1" in check["clause"]


def test_column_bars_without_a_partner_stop_with_a_hook_and_dowels_start_extra_ones() -> None:
    objects = json.loads(_objects())
    c300 = next(o for o in objects["objects"] if o["id"] == "C300")
    six = json.loads(json.dumps(c300))
    six["id"], six["name"] = "C300X", "Column 300x300, 6 bars"
    six["reinforcement"]["longitudinal"] = [{"position": "perimeter", "count": 6, "dia": 16}]
    objects["objects"].append(six)
    bim = json.loads(_frame())
    next(e for e in bim["elements"] if e["id"] == "C2")["type"] = "C300X"
    next(e for e in bim["elements"] if e["id"] == "C3U")["type"] = "C300X"
    model = _model(bim=json.dumps(bim), objects=json.dumps(objects))
    lap = up(column_lap(16, 420, 24.1).value)
    c2 = _element(model, "C2")
    vertical = [b for b in c2["bars"] if b["role"] == "vertical"]
    straight = [b for b in vertical if b["shape"] == "straight"]
    hooked = [b for b in vertical if b["shape"] == "L"]
    assert sum(b["count"] for b in straight) == 4
    assert straight[0]["at"]["to"] == pytest.approx(3000 + lap)
    assert sum(b["count"] for b in hooked) == 2
    assert hooked[0]["at"]["to"] == pytest.approx(3000 - 40)
    assert hooked[0]["dims"]["B"] == pytest.approx(standard_hook(16).leg)
    assert any(c["name"].startswith("Column bars without a partner") for c in c2["checks"])
    # C3 (4 bars) under C3U (6 bars): 2 dowels, ld below the floor and the lap above
    c3 = _element(model, "C3")
    dowels = [b for b in c3["bars"] if b["role"] == "starter" and b["at"].get("for") == "C3U"]
    assert sum(b["count"] for b in dowels) == 2
    ld = up(development_tension(16, 420, 24.1).value)
    assert dowels[0]["at"]["from"] == pytest.approx(3000 - ld)
    assert dowels[0]["at"]["to"] == pytest.approx(3000 + lap)
    lap_row = next(x for x in c3["laps"] if x.get("with") == "C3U")
    assert dowels[0]["mark"] in lap_row["marks"]

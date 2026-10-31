"""The bill of quantities measured from the building model (Part 10)."""

from __future__ import annotations

import json
import math

import pytest

from saengine.boq import BillOfQuantities, compute_boq, compute_boq_text
from saengine.boq.quantities import BoqSource, bar_length, bar_mass, bill_of_quantities
from saengine.library import FloorPlan, default_floor_plan, default_material_library
from saengine.library.bim import BuildingModel, generate, generate_from_structure, source_stamp
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.structure import StructuralModel, default_structural_model

LINEAR = {"material": "B420DWR", "cover": 40}

OBJECTS = {
    "objects": [
        {
            "id": "COL",
            "name": "Column 400x400",
            "kind": "column",
            "material": "C24.1",
            "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
            "reinforcement": {
                **LINEAR,
                "longitudinal": [{"position": "perimeter", "count": 4, "dia": 16}],
                "transverse": {"type": "tie", "dia": 10, "spacing": 150},
            },
        },
        {
            "id": "BM",
            "name": "Beam 300x500",
            "kind": "beam",
            "material": "C24.1",
            "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            "reinforcement": {
                "material": "B420DWR",
                "cover": 25,
                "longitudinal": [
                    {"position": "bottom", "count": 3, "dia": 20},
                    {"position": "top", "count": 2, "dia": 16},
                ],
                "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
            },
        },
        {
            "id": "SL",
            "name": "Slab 150",
            "kind": "slab",
            "material": "C24.1",
            "thickness": 150,
            "reinforcement": {
                "material": "B420DWR",
                "cover": 20,
                "bottomX": {"dia": 10, "spacing": 150},
                "bottomY": {"dia": 10, "spacing": 200},
            },
        },
    ]
}

# One bay (A-B 6 m, 1-2 5 m), one story at 3.2 m: four columns, four beams, one slab
# (the frame of test_fem_derive.py).
corners = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]
PLAN = FloorPlan.model_validate(
    {
        **default_floor_plan().model_dump(mode="json", by_alias=True),
        "columns": [
            {"id": f"C{i + 1}", "type": "COL", "at": {"x": x, "y": y}, "base": "BASE", "top": "L1"}
            for i, (x, y) in enumerate(corners)
        ],
        "beams": [
            {
                "id": f"B{i + 1}",
                "type": "BM",
                "story": "L1",
                "start": {"x": a[0], "y": a[1]},
                "end": {"x": b[0], "y": b[1]},
            }
            for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1], strict=True))
        ],
        "slabs": [
            {
                "id": "S1",
                "type": "SL",
                "story": "L1",
                "boundary": [{"x": x, "y": y} for x, y in corners],
            }
        ],
    }
)


def dump(model) -> str:
    return json.dumps(model.model_dump(mode="json", by_alias=True, exclude_none=True))


MATERIALS = dump(default_material_library())


def bill(bim: str, objects: dict = OBJECTS) -> BillOfQuantities:
    return BillOfQuantities.model_validate(compute_boq(bim, json.dumps(objects), MATERIALS))


def estimated(bim: str, objects: dict = OBJECTS) -> BillOfQuantities:
    """The bill by the estimating rules alone, as for the elements the drawings do not detail
    (compute_boq takes the detailed bars of the others: see test_the_bill_takes_the_detailed_
    bars)."""
    text = json.dumps(objects)
    return bill_of_quantities(
        BuildingModel.model_validate_json(bim),
        ObjectLibrary.model_validate_json(text),
        MaterialLibrary.model_validate_json(MATERIALS),
        BoqSource(
            bim=source_stamp(bim), objects=source_stamp(text), materials=source_stamp(MATERIALS)
        ),
    )


def item(boq: BillOfQuantities, group: str, **match):
    return next(
        i
        for i in boq.items
        if i.group == group and all(getattr(i, k) == v for k, v in match.items())
    )


def share(entry_item, element: str, detail: str | None = None) -> float:
    return sum(
        e.quantity
        for e in entry_item.breakdown
        if e.element == element and detail in (None, e.detail)
    )


def test_bar_rules() -> None:
    assert bar_mass(16) == pytest.approx(256 / 162)
    # A lap at every joint between 12 m stock bars: none for a bar of one stock length.
    assert bar_length(11_999, 20) == 11_999
    assert bar_length(12_000, 20) == 12_000
    assert bar_length(12_001, 20) == 12_001 + 800
    assert bar_length(24_000, 20) == 24_000 + 800
    assert bar_length(25_000, 16) == 25_000 + 2 * 640


def test_frame_quantities() -> None:
    bim = dump(generate(PLAN, "s"))
    boq = estimated(bim)
    assert boq.source.bim == source_stamp(bim)
    assert boq.source.materials == source_stamp(MATERIALS)

    # Concrete. The slab 6 x 5 x 0.15 runs to the grid lines, i.e. to the beams' and columns'
    # centrelines: it covers the inner half (0.15 m) of each 0.3 m beam and a 0.2 x 0.2 quarter
    # of each column, and that part (0.15 deep) is measured with the slab.
    # Columns: 4 x 0.4 x 0.4 x 3.2, less 4 x 0.04 x 0.15.
    # Beams: between the column faces (6 - 0.4 and 5 - 0.4 m, twice: 20.4 m) x 0.3 x 0.5, less
    # 20.4 x 0.15 x 0.15 under the slab.
    columns = item(boq, "concrete", kind="column")
    beams = item(boq, "concrete", kind="beam")
    slab = item(boq, "concrete", kind="slab")
    assert columns.quantity == pytest.approx(2.048 - 0.024)
    assert columns.byStory == {"L1": pytest.approx(2.024)}
    assert share(beams, "B1") == pytest.approx(5.6 * 0.3 * 0.5 - 5.6 * 0.15 * 0.15, abs=1e-3)
    assert share(beams, "B2") == pytest.approx(4.6 * 0.3 * 0.5 - 4.6 * 0.15 * 0.15, abs=1e-3)
    assert beams.quantity == pytest.approx(3.06 - 0.459)
    assert slab.quantity == pytest.approx(4.5)
    assert boq.total("concrete") == pytest.approx(2.024 + 2.601 + 4.5)
    assert columns.material == "C24.1" and columns.unit == "m3"

    # Column C1: 4 bars of 16 over 3.2 m; ties of 10 at 150 over 3.2 m (21 + 1 of them), each
    # around 400 - 2 x 40 - 10 = 310 mm square plus two hooks of 100 mm.
    d16 = item(boq, "reinforcement", diameter=16)
    d10 = item(boq, "reinforcement", diameter=10)
    d20 = item(boq, "reinforcement", diameter=20)
    assert share(d16, "C1") == pytest.approx(4 * 3.2 * 256 / 162, abs=1e-3)
    assert share(d10, "C1") == pytest.approx(22 * (4 * 0.310 + 0.2) * 100 / 162, abs=1e-3)
    # Beam B1: 3 bars of 20 and 2 of 16 over its 6 m centreline; stirrups of 10 at 150 over its
    # 5.6 m clear span (37 + 1), around 240 x 440 mm plus the hooks.
    assert share(d20, "B1") == pytest.approx(3 * 6 * 400 / 162, abs=1e-3)
    assert share(d16, "B1") == pytest.approx(2 * 6 * 256 / 162, abs=1e-3)
    assert share(d10, "B1") == pytest.approx(38 * (2 * (0.24 + 0.44) + 0.2) * 100 / 162, abs=1e-3)
    # Slab mesh: 30 m² of 10 mm bars at 150 one way and 200 the other.
    assert share(d10, "S1") == pytest.approx((30 / 0.15 + 30 / 0.2) * 100 / 162, abs=1e-3)
    assert {e.detail for e in d10.breakdown if e.element == "S1"} == {"bottom X", "bottom Y"}
    assert d10.material == "B420DWR" and d10.unit == "kg"

    # Formwork. Columns: sides 1.6 x 3.2 each, less the two 0.2 m faces the slab lies against
    # over its 0.15 m depth. Beams: soffit and sides (0.3 + 2 x 0.5) over the 20.4 m of clear
    # span, less the inner side over the slab's depth. Slab: the soffit less the beams and
    # columns under it (20.4 x 0.15 + 4 x 0.04); its edges all lie over beams and columns.
    assert item(boq, "formwork", kind="column").quantity == pytest.approx(20.48 - 4 * 0.4 * 0.15)
    assert item(boq, "formwork", kind="beam").quantity == pytest.approx(20.4 * (1.3 - 0.15))
    slab_form = item(boq, "formwork", kind="slab")
    assert slab_form.quantity == pytest.approx(30 - 3.06 - 0.16)
    assert share(slab_form, "S1", "edges") == 0
    assert boq.total("formwork") == pytest.approx(20.24 + 23.46 + 26.78)
    assert not [i for i in boq.items if i.group == "steel"]
    assert [i.code for i in boq.items if i.group == "concrete"] == ["C.01", "C.02", "C.03"]
    assert any("between the faces of the columns" in n for n in boq.notes)


def test_the_bill_takes_the_detailed_bars() -> None:
    """A quantity lives in one place: the bill's bars of the detailed elements are the bars of
    the bar bending schedule (count x cutting length per mark, with the laps, hooks and stirrup
    zones), so the two agree per bar size to the bill's rounding (0.001 kg per entry)."""
    from saengine.drawings.bbs import bar_schedule
    from saengine.drawings.detailing import detailing_model

    bim = dump(generate(PLAN, "s"))
    boq = bill(bim)
    schedule = bar_schedule(
        detailing_model(texts={"bim": bim, "objects": json.dumps(OBJECTS), "materials": MATERIALS})
    )
    steel = {i.diameter: i.quantity for i in boq.items if i.group == "reinforcement"}
    assert steel.keys() == schedule.by_diameter.keys()
    for dia, mass in schedule.by_diameter.items():
        assert steel[dia] == pytest.approx(mass, abs=0.01)
    # every entry is a bar mark of the schedule; the estimate differs (e.g. the stirrups: zones,
    # seismic hooks and bends against one spacing and two 10 d hooks)
    entries = [e for i in boq.items if i.group == "reinforcement" for e in i.breakdown]
    assert all("(bar bending schedule)" in (e.detail or "") for e in entries)
    assert {e.element for e in entries} == {"C1", "C2", "C3", "C4", "B1", "B2", "B3", "B4", "S1"}
    assert estimated(bim).total("reinforcement") != pytest.approx(boq.total("reinforcement"))
    note = next(n for n in boq.notes if n.startswith("Measured from the detailed bars"))
    assert "4 columns" in note and "1 slab" in note
    assert not any(n.startswith("Measured by the estimating rules") for n in boq.notes)
    assert any(n.startswith("Reinforcement is measured from the detailed bars") for n in boq.notes)


def test_openings_and_missing_types() -> None:
    model = generate(PLAN, "s")
    data = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["additions"]["slabOpenings"] = [
        {"id": "O1", "host": "S1", "x": 3000, "y": 2500, "xDim": 1000, "yDim": 2000}
    ]
    data["elements"].append(
        {"kind": "column", "id": "X1", "type": "NOPE", "position": [0, 0], "bottom": 0, "top": 1}
    )
    objects = json.loads(json.dumps(OBJECTS))
    del objects["objects"][0]["reinforcement"]
    boq = bill(json.dumps(data), objects)
    assert item(boq, "concrete", kind="slab").quantity == pytest.approx((30 - 2) * 0.15)
    # Soffit less the opening and the beams and columns under it; edges: the opening's 6 m.
    assert item(boq, "formwork", kind="slab").quantity == pytest.approx(28 - 3.22 + 6 * 0.15)
    assert any(n.startswith("X1: object type 'NOPE' is not in 04 Objects") for n in boq.notes)
    assert any("'COL'" in n and "no reinforcement" in n and "C1, C2" in n for n in boq.notes)
    assert all(e.element != "X1" for i in boq.items for e in i.breakdown)
    assert not any(
        e.element == "C1" for i in boq.items if i.group == "reinforcement" for e in i.breakdown
    )
    # The bill is incomplete: the columns' bars and X1 are not measured (Q1).
    assert len(boq.problems) == 2
    assert boq.problems[0].startswith("No reinforcement measured for 4 element(s) of 1 object")
    assert "(COL)" in boq.problems[0]
    assert boq.problems[1].startswith("X1: object type 'NOPE' is not in 04 Objects")
    # The breakdown names the type each element was measured with (Q4).
    entry = item(boq, "concrete", kind="slab").breakdown[0]
    assert entry.detail == "type SL"


def test_opening_over_the_slab_edge() -> None:
    # A 1 x 1 m opening centred on the slab's edge over beam B2 (x = 6 m): only its half inside
    # the slab is deducted, and only the slab edges around the notch away from B2 are formed.
    data = generate(PLAN, "s").model_dump(mode="json", by_alias=True, exclude_none=True)
    data["additions"]["slabOpenings"] = [
        {"id": "O1", "host": "S1", "x": 6000, "y": 2500, "xDim": 1000, "yDim": 1000}
    ]
    boq = bill(json.dumps(data))
    assert item(boq, "concrete", kind="slab").quantity == pytest.approx((30 - 0.5) * 0.15)
    # Edges: the notch's 1 m back edge and its two 0.5 m sides less the 0.15 m over B2.
    # Soffit: less the beams and columns under it, except B2's inner strip in the notch.
    slab_form = item(boq, "formwork", kind="slab")
    assert share(slab_form, "S1", "edges") == pytest.approx(1.7 * 0.15)
    assert share(slab_form, "S1", "soffit") == pytest.approx(29.5 - (3.06 - 0.15) - 0.16)
    # B2's inner side is formed to its full depth where the notch leaves it bare.
    beam_form = item(boq, "formwork", kind="beam")
    assert share(beam_form, "B2") == pytest.approx(4.6 * 1.3 - (4.6 - 1) * 0.15)


def test_beams_between_all_column_faces() -> None:
    # Three columns in a row; a grade beam at the columns' bottom from C1 to C2, and one beam
    # along the whole row through C2 at the top. No slab.
    bim = {
        "schema": "saengine.bim/2",
        "stories": [
            {"id": "BASE", "name": "Base", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3200},
        ],
        "elements": [
            *(
                {
                    "kind": "column",
                    "id": f"C{i + 1}",
                    "type": "COL",
                    "position": [x, 0],
                    "bottom": 0,
                    "top": 3200,
                }
                for i, x in enumerate((0, 6000, 12000))
            ),
            {
                "kind": "beam",
                "id": "GB",
                "type": "BM",
                "start": [0, 0],
                "end": [6000, 0],
                "elevation": 0,
            },
            {
                "kind": "beam",
                "id": "LB",
                "type": "BM",
                "start": [0, 0],
                "end": [12000, 0],
                "elevation": 3200,
            },
        ],
    }
    boq = estimated(json.dumps(bim))
    beams = item(boq, "concrete", kind="beam")
    assert share(beams, "GB") == pytest.approx(5.6 * 0.15)
    assert share(beams, "LB") == pytest.approx(11.2 * 0.15)
    assert share(item(boq, "formwork", kind="beam"), "LB") == pytest.approx(11.2 * 1.3)
    # Stirrups over the clear spans: 5.6 m / 0.15 + 1 = 38 for each span of LB.
    d10 = item(boq, "reinforcement", diameter=10)
    stirrup = (2 * (0.24 + 0.44) + 0.2) * 100 / 162
    assert share(d10, "LB") == pytest.approx(2 * 38 * stirrup, abs=1e-3)
    # LB's 12 m bars fit one stock length: no lap.
    assert share(item(boq, "reinforcement", diameter=20), "LB") == pytest.approx(
        3 * 12 * 400 / 162, abs=1e-3
    )


def point(x: float, y: float, z: float) -> dict:
    return {"x": x, "y": y, "z": z}


def test_special_structure() -> None:
    # The canopy of test_structure.py (four 4 m columns, four edge beams, a roof slab with a
    # 1 m square opening), plus a steel brace of a 100 x 100 x 5 box.
    xy = [(0, 0), (6000, 0), (6000, 5000), (0, 5000)]
    h = 4000
    canopy = StructuralModel.model_validate(
        {
            **default_structural_model().model_dump(mode="json", by_alias=True),
            "members": [
                *(
                    {
                        "id": f"C{i + 1}",
                        "type": "COL",
                        "start": point(x, y, 0),
                        "end": point(x, y, h),
                    }
                    for i, (x, y) in enumerate(xy)
                ),
                *(
                    {"id": f"B{i + 1}", "type": "BM", "start": point(*a, h), "end": point(*b, h)}
                    for i, (a, b) in enumerate(zip(xy, xy[1:] + xy[:1], strict=True))
                ),
                {"id": "D1", "type": "BR", "start": point(0, 0, 0), "end": point(6000, 0, h)},
            ],
            "areas": [
                {
                    "id": "R1",
                    "type": "SL",
                    "outline": [point(x, y, h) for x, y in xy],
                    "openings": [
                        {
                            "outline": [
                                point(2000, 2000, h),
                                point(3000, 2000, h),
                                point(3000, 3000, h),
                                point(2000, 3000, h),
                            ]
                        }
                    ],
                }
            ],
        }
    )
    objects = json.loads(json.dumps(OBJECTS))
    objects["objects"].append(
        {
            "id": "BR",
            "name": "Brace box 100x5",
            "kind": "brace",
            "material": "A36",
            "profile": {"shape": "rectangleHollow", "xDim": 100, "yDim": 100, "wallThickness": 5},
        }
    )
    boq = bill(dump(generate_from_structure(canopy, "s")), objects)
    # Members run node to node: columns 4 x 0.16 x 4, beams 22 m x 0.15; the roof less its hole.
    assert item(boq, "concrete", kind="column").quantity == pytest.approx(4 * 0.16 * 4)
    assert item(boq, "concrete", kind="beam").quantity == pytest.approx(22 * 0.15)
    assert item(boq, "concrete", kind="slab").quantity == pytest.approx(29 * 0.15)
    assert item(boq, "concrete", kind="column").byStory == {}
    # Mesh over 29 m², bars running the roof's 7.81 m diagonal (no laps).
    d10 = item(boq, "reinforcement", diameter=10)
    assert share(d10, "R1") == pytest.approx((29 / 0.15 + 29 / 0.2) * 100 / 162, abs=1e-3)
    assert item(boq, "formwork", kind="slab").quantity == pytest.approx(29 + (22 + 4) * 0.15)
    steel = item(boq, "steel", material="A36")
    length = math.hypot(6, 4)
    # The box is the table's SHS 100x100x5 (its rounded corners: SAEngine's section table).
    from saengine.library.steel_sections import find

    area = find("SHS 100x100x5").A
    assert area < 100**2 - 90**2
    assert steel.quantity == pytest.approx(area * 1e-6 * length * 7850, abs=1e-3)
    assert "SHS 100x100x5" in steel.description
    assert steel.kind == "brace" and steel.unit == "kg"


def test_text_for_the_workbench() -> None:
    bim = dump(generate(PLAN, "s"))
    result = compute_boq_text(bim, json.dumps(OBJECTS), MATERIALS)
    document = json.loads(result["text"])
    assert document["schema"] == "saengine.boq/1"
    # materialIds: the materials the bill used, whose entries alone stamp it (N-Q3).
    assert set(document["source"]) == {"bim", "objects", "materials", "materialIds"}
    assert result["notes"] == document["notes"]
    problems = compute_boq_text("{}", '{"objects": [{"id": 1}]}', MATERIALS)["problems"]
    assert problems and all(p.startswith("Object types: ") for p in problems)


def test_walls_footings_piles_and_stairs() -> None:
    stories = [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3000},
    ]
    bim = {
        "schema": "saengine.bim/2",
        "stories": stories,
        "elements": [
            {
                "kind": "wall",
                "id": "W1",
                "type": "WL",
                "start": [0, 0],
                "end": [5000, 0],
                "bottom": 0,
                "top": 3000,
            },
            {"kind": "footing", "id": "F1", "type": "FT", "position": [0, 0], "elevation": 0},
            {"kind": "footing", "id": "P1", "type": "PC", "position": [9000, 0], "elevation": 0},
            {"kind": "footing", "id": "P2", "type": "PC2", "position": [12000, 0], "elevation": 0},
        ],
        "additions": {
            "wallOpenings": [
                {"id": "D1", "host": "W1", "offset": 1000, "width": 1000, "height": 2000},
                # Runs 0.5 m past the wall's end: only 0.5 x 1 m of it is in the wall.
                {
                    "id": "D2",
                    "host": "W1",
                    "offset": 4500,
                    "sill": 1000,
                    "width": 1000,
                    "height": 1000,
                },
            ],
            "stairs": [
                {"id": "ST1", "type": "STR", "base": "BASE", "top": "L1", "x": 0, "y": 3000}
            ],
        },
    }
    rebar = {"material": "B420DWR", "cover": 50}
    objects = {
        "objects": [
            {
                "id": "WL",
                "name": "Wall 200",
                "kind": "wall",
                "material": "C24.1",
                "thickness": 200,
                "reinforcement": {
                    **rebar,
                    "vertical": {"dia": 12, "spacing": 200},
                    "horizontal": {"dia": 10, "spacing": 250},
                },
            },
            {
                "id": "FT",
                "name": "Footing 2x2",
                "kind": "footing",
                "material": "C24.1",
                "length": 2000,
                "width": 2000,
                "thickness": 500,
                "reinforcement": {**rebar, "bottomX": {"dia": 16, "spacing": 200}},
            },
            {
                "id": "PL",
                "name": "Pile 500",
                "kind": "pile",
                "material": "C24.1",
                "pileType": "bored",
                "profile": {"shape": "circle", "radius": 250},
                "length": 15000,
                "reinforcement": {
                    **rebar,
                    "longitudinal": [{"position": "perimeter", "count": 6, "dia": 16}],
                },
            },
            {
                "id": "PC",
                "name": "Pile cap",
                "kind": "pileCap",
                "material": "C24.1",
                "length": 1500,
                "width": 1500,
                "thickness": 800,
                "pile": "PL",
                "pileCount": 2,
            },
            {
                "id": "PC2",
                "name": "Pile cap without a pile type",
                "kind": "pileCap",
                "material": "C24.1",
                "length": 1500,
                "width": 1500,
                "thickness": 800,
                "pileCount": 4,
            },
            {
                "id": "STR",
                "name": "Stair",
                "kind": "staircase",
                "material": "C24.1",
                "waistThickness": 150,
                "riser": 150,
                "tread": 250,
                "flightWidth": 1200,
            },
        ]
    }
    boq = estimated(json.dumps(bim), objects)
    # Wall: 5 x 3 less a 1 x 2 door and the 0.5 x 1 part of D2 in it, 0.2 thick; both faces;
    # two layers of bars.
    assert item(boq, "concrete", kind="wall").quantity == pytest.approx(12.5 * 0.2)
    assert item(boq, "formwork", kind="wall").quantity == pytest.approx(25)
    d12 = item(boq, "reinforcement", diameter=12)
    assert share(d12, "W1") == pytest.approx(2 * 12.5 / 0.2 * 144 / 162, abs=1e-3)
    assert item(boq, "concrete", kind="footing").quantity == pytest.approx(2)
    assert item(boq, "formwork", kind="footing").quantity == pytest.approx(4)
    d16 = item(boq, "reinforcement", diameter=16)
    assert share(d16, "F1") == pytest.approx(4 / 0.2 * 256 / 162, abs=1e-3)
    # Two piles 15 m of 6 bars of 16 with one lap each (40 x 16 mm).
    assert share(d16, "P1") == pytest.approx(2 * 6 * 15.64 * 256 / 162, abs=1e-3)
    piles = item(boq, "concrete", kind="pile")
    assert piles.quantity == pytest.approx(2 * math.pi * 0.25**2 * 15, rel=2e-3)
    assert share(piles, "P2") == 0
    assert item(boq, "concrete", kind="pileCap").quantity == pytest.approx(2 * 1.5 * 1.5 * 0.8)
    assert any(n.startswith("P2: pile cap type 'PC2' has 4 piles but no pile") for n in boq.notes)

    # Stair: 20 risers of 0.15 over 20 goings of 0.25 (5 m), waist 0.15 measured normal to the
    # slope, i.e. a vertical drop of 0.15 x hypot(0.15, 0.25) / 0.25 under the line of nosings.
    # Section: the 20 step triangles, plus the waist strip under the 5 m flight less the
    # triangle cut off below the foot (where the strip's underside meets the floor).
    stairs = item(boq, "concrete", kind="staircase")
    drop = 0.15 * math.hypot(0.15, 0.25) / 0.25
    foot = drop * 0.25 / 0.15
    section = 20 * 0.25 * 0.15 / 2 + 5 * drop - foot * drop / 2
    assert stairs.quantity == pytest.approx(section * 1.2, abs=1e-3)
    assert section * 1.2 == pytest.approx(1.469, abs=1e-3)
    assert stairs.byStory == {"BASE": stairs.quantity}
    # Formwork: the soffit along the 5.831 m slope and the 20 risers, 1.2 m wide.
    stair_form = item(boq, "formwork", kind="staircase")
    assert share(stair_form, "ST1", "soffit") == pytest.approx(math.hypot(5, 3) * 1.2, abs=1e-3)
    assert share(stair_form, "ST1", "risers") == pytest.approx(20 * 0.15 * 1.2, abs=1e-3)
    assert any("'STR'" in n and "no reinforcement" in n for n in boq.notes)

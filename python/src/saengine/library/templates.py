"""Starting values for new entries in the visual library editors.

When the user adds a material or an object type, switches a profile shape or turns on an
optional group (reinforcement, mix, ...), the editor inserts the template for that schema
definition, so the file always stays valid. They are ordinary editable values, chosen to be
typical, not recommendations; ``tests/test_library.py`` validates every template against its
model.

Keys are JSON Schema ``$defs`` names. Material templates are keyed ``Material:<category>``.
References to other entries (``material``, ``pile``) are placeholders that the editor
replaces with an existing id of the right kind.
"""

from __future__ import annotations

from typing import Any

from saengine.library.defaults import default_material_library
from saengine.library.materials import Category

_REBAR = "B420DWR"
_CONCRETE = "C24.1"


def _material_templates() -> dict[str, dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    for material in default_material_library().materials:
        key = f"Material:{material.category.value}"
        if key not in templates:
            templates[key] = material.model_dump(mode="json", by_alias=True, exclude_none=True)
    templates[f"Material:{Category.OTHER.value}"] = {
        "id": "MAT",
        "name": "New material",
        "category": "other",
        "mechanical": {},
    }
    return templates


TEMPLATES: dict[str, dict[str, Any]] = {
    **_material_templates(),
    # materials
    "Mechanical": {},
    "ConcreteProperties": {"fc": 24.1},
    "SteelProperties": {"fy": 420},
    "MasonryProperties": {"unit": "first-class burnt clay brick"},
    "NominalMix": {
        "method": "nominal",
        "ratio": [1, 1.5, 3],
        "waterCement": 0.45,
        "cementType": "OPC",
    },
    "DesignMix": {
        "method": "design",
        "cement": 400,
        "water": 180,
        "fineAggregate": 700,
        "coarseAggregate": 1100,
        "cementType": "OPC",
        "admixtures": [],
    },
    "Admixture": {"name": "Superplasticizer", "amount": 1, "unit": "% of cement"},
    "Source": {},
    # profiles
    "RectangleProfile": {"shape": "rectangle", "xDim": 250, "yDim": 450},
    "CircleProfile": {"shape": "circle", "radius": 250},
    "RectangleHollowProfile": {
        "shape": "rectangleHollow",
        "xDim": 150,
        "yDim": 150,
        "wallThickness": 8,
    },
    "CircleHollowProfile": {"shape": "circleHollow", "radius": 85, "wallThickness": 6},
    "IShapeProfile": {
        "shape": "I",
        "overallWidth": 165,
        "overallDepth": 310,
        "webThickness": 5.8,
        "flangeThickness": 9.7,
        "filletRadius": 8.9,
    },
    "TShapeProfile": {
        "shape": "T",
        "depth": 150,
        "flangeWidth": 150,
        "webThickness": 8,
        "flangeThickness": 10,
    },
    "LShapeProfile": {"shape": "L", "depth": 75, "width": 75, "thickness": 6},
    "UShapeProfile": {
        "shape": "U",
        "depth": 200,
        "flangeWidth": 75,
        "webThickness": 6,
        "flangeThickness": 10,
    },
    # reinforcement
    "BarGroup": {"position": "bottom", "count": 3, "dia": 16},
    "Transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
    "LinearReinforcement": {
        "material": _REBAR,
        "cover": 40,
        "longitudinal": [
            {"position": "top", "count": 2, "dia": 16},
            {"position": "bottom", "count": 3, "dia": 16},
        ],
        "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
    },
    "BarMesh": {"dia": 10, "spacing": 150},
    "PlanarReinforcement": {
        "material": _REBAR,
        "cover": 25,
        "bottomX": {"dia": 10, "spacing": 150},
        "bottomY": {"dia": 10, "spacing": 150},
    },
    "WallReinforcement": {
        "material": _REBAR,
        "cover": 25,
        "layers": 2,
        "vertical": {"dia": 12, "spacing": 200},
        "horizontal": {"dia": 10, "spacing": 200},
    },
    "StairReinforcement": {
        "material": _REBAR,
        "cover": 20,
        "main": {"dia": 12, "spacing": 150},
        "distribution": {"dia": 10, "spacing": 200},
    },
    # object types
    "Beam": {
        "id": "B",
        "name": "New beam",
        "kind": "beam",
        "material": _CONCRETE,
        "profile": {"shape": "rectangle", "xDim": 250, "yDim": 450},
    },
    "Column": {
        "id": "C",
        "name": "New column",
        "kind": "column",
        "material": _CONCRETE,
        "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
    },
    "Brace": {
        "id": "BR",
        "name": "New brace",
        "kind": "brace",
        "material": "A36",
        "profile": {"shape": "L", "depth": 75, "width": 75, "thickness": 6},
    },
    "Slab": {
        "id": "S",
        "name": "New slab",
        "kind": "slab",
        "material": _CONCRETE,
        "thickness": 150,
        "system": "twoWay",
    },
    "Wall": {
        "id": "W",
        "name": "New wall",
        "kind": "wall",
        "material": _CONCRETE,
        "thickness": 200,
        "structural": True,
    },
    "Staircase": {
        "id": "ST",
        "name": "New staircase",
        "kind": "staircase",
        "material": _CONCRETE,
        "waistThickness": 150,
        "riser": 150,
        "tread": 250,
        "flightWidth": 1200,
    },
    "Footing": {
        "id": "F",
        "name": "New footing",
        "kind": "footing",
        "material": _CONCRETE,
        "footingType": "isolated",
        "length": 2000,
        "width": 2000,
        "thickness": 450,
    },
    "PileCap": {
        "id": "PC",
        "name": "New pile cap",
        "kind": "pileCap",
        "material": _CONCRETE,
        "length": 2400,
        "width": 2400,
        "thickness": 900,
    },
    "Pile": {
        "id": "P",
        "name": "New pile",
        "kind": "pile",
        "material": _CONCRETE,
        "pileType": "bored",
        "profile": {"shape": "circle", "radius": 300},
        "length": 18000,
    },
    # building model (the editor computes labels/positions for grid lines and stories)
    "GridLine": {"label": "C", "position": 12000},
    "Story": {"id": "L2", "name": "Level 2", "elevation": 6400},
    "GridPoint": {"x": "A", "y": "1", "dx": 0, "dy": 0},
    "PlacedColumn": {
        "id": "C-A1",
        "type": "C",
        "at": {"x": "A", "y": "1"},
        "base": "BASE",
        "top": "L1",
    },
    "PlacedBeam": {
        "id": "B-A1-B1",
        "type": "B",
        "story": "L1",
        "start": {"x": "A", "y": "1"},
        "end": {"x": "B", "y": "1"},
    },
    "PlacedWall": {
        "id": "W-A1-A2",
        "type": "W",
        "base": "BASE",
        "top": "L1",
        "start": {"x": "A", "y": "1"},
        "end": {"x": "A", "y": "2"},
    },
    "PlacedSlab": {
        "id": "S-A1",
        "type": "S",
        "story": "L1",
        "boundary": [
            {"x": "A", "y": "1"},
            {"x": "B", "y": "1"},
            {"x": "B", "y": "2"},
            {"x": "A", "y": "2"},
        ],
    },
    "PlacedFooting": {"id": "F-A1", "type": "F", "story": "BASE", "at": {"x": "A", "y": "1"}},
    "Underlay": {"story": "L1", "file": "Underlays/architect-L1.dxf"},
    # building model elements
    "ColumnElement": {
        "id": "C1",
        "type": "C",
        "kind": "column",
        "position": [0, 0],
        "bottom": 0,
        "top": 3200,
    },
    "BeamElement": {
        "id": "B1",
        "type": "B",
        "kind": "beam",
        "start": [0, 0],
        "end": [6000, 0],
        "elevation": 3200,
    },
    "WallElement": {
        "id": "W1",
        "type": "W",
        "kind": "wall",
        "start": [0, 0],
        "end": [6000, 0],
        "bottom": 0,
        "top": 3200,
    },
    "SlabElement": {
        "id": "S1",
        "type": "S",
        "kind": "slab",
        "boundary": [[0, 0], [6000, 0], [6000, 5000], [0, 5000]],
        "elevation": 3200,
    },
    "FootingElement": {
        "id": "F1",
        "type": "F",
        "kind": "footing",
        "position": [0, 0],
        "elevation": 0,
    },
}

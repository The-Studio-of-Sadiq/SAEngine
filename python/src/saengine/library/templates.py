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
from saengine.library.settings import Analysis
from saengine.library.shapes import Arch, BarrelVault, CableNet, Dome, PlaneTruss, SpaceTruss

# Parametric shapes start at typical sizes of their kind; "MEMBER" is replaced by a member type.
_SHAPES = [
    SpaceTruss(lengthX=36000, lengthY=24000, baysX=12, baysY=8, depth=2000, memberType="MEMBER"),
    PlaneTruss(span=24000, depth=2400, panels=8, memberType="MEMBER"),
    Arch(span=30000, rise=7500, segments=12, memberType="MEMBER"),
    Dome(radius=20000, rise=8000, rings=6, segments=24, memberType="MEMBER"),
    BarrelVault(span=24000, rise=6000, length=36000, segments=12, bays=6, memberType="MEMBER"),
    CableNet(
        lengthX=36000, lengthY=24000, divisionsX=12, divisionsY=8, rise=3000, memberType="MEMBER"
    ),
]

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
    "TransverseZone": {"spacing": 100},
    "SpliceZone": {"spacing": 100},
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
    "BoundaryHoops": {"dia": 10, "spacing": 100, "legsAcross": 2, "legsAlong": 2},
    "WallBoundary": {
        "length": 400,
        "count": 4,
        "dia": 16,
        "hoop": {"dia": 10, "spacing": 100, "legsAcross": 2, "legsAlong": 2},
    },
    "CouplingDiagonal": {"count": 4, "dia": 20},
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
    # project settings
    "AreaLoad": {
        "id": "AL",
        "name": "Office",
        "use": "office",
        "live": 2.4,
        "finish": 1.2,
        "partitions": 1.0,
    },
    "LoadCombination": {"name": "1.2D + 1.6L", "D": 1.2, "L": 1.6},
    "Analysis": Analysis().model_dump(mode="json"),
    "Pushover": {"directions": ["X", "Y"]},
    "Solid": {"id": "MASS", "name": "Mass concrete", "kind": "solid", "material": _CONCRETE},
    "Block": {
        "id": "K1",
        "type": "MASS",
        "outline": [
            {"x": 0, "y": 0, "z": 0},
            {"x": 4000, "y": 0, "z": 0},
            {"x": 4000, "y": 4000, "z": 0},
            {"x": 0, "y": 4000, "z": 0},
        ],
        "thickness": 1000,
    },
    "TimeHistory": {
        "name": "El Centro X",
        "record": "02 Project Settings/records/ElCentro.AT2",
        "direction": "X",
    },
    # structural model (special structures)
    "CartesianGrid": {"kind": "cartesian", "id": "G2", "x": [], "y": [], "z": []},
    "CylindricalGrid": {"kind": "cylindrical", "id": "G2", "radii": [], "angles": [], "z": []},
    "AngleLine": {"label": "R1", "angle": 0},
    "Point": {"x": 0, "y": 0, "z": 0},
    "Member": {
        "id": "M1",
        "type": "B300x500",
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 6000, "y": 0, "z": 0},
    },
    "Area": {
        "id": "A1",
        "type": "S150",
        "outline": [
            {"x": 0, "y": 0, "z": 0},
            {"x": 6000, "y": 0, "z": 0},
            {"x": 6000, "y": 5000, "z": 0},
            {"x": 0, "y": 5000, "z": 0},
        ],
    },
    "Opening": {
        "outline": [
            {"x": 1000, "y": 1000, "z": 0},
            {"x": 2000, "y": 1000, "z": 0},
            {"x": 2000, "y": 2000, "z": 0},
        ]
    },
    "Support": {"id": "SP1", "at": {"x": 0, "y": 0, "z": 0}, "fixity": "fixed"},
    "ProjectInfo": {"name": "Project"},
    # building model elements
    "SlabOpening": {"id": "O1", "host": "S1", "x": 0, "y": 0, "xDim": 1000, "yDim": 1000},
    "WallOpening": {
        "id": "D1",
        "host": "W1",
        "offset": 500,
        "sill": 0,
        "width": 900,
        "height": 2100,
    },
    "Stair": {
        "id": "ST1",
        "type": "ST",
        "base": "BASE",
        "top": "L1",
        "x": 0,
        "y": 0,
        "direction": 0,
    },
    "InclinedMember": {
        "id": "M1",
        "type": "BR",
        "x1": 0,
        "y1": 0,
        "z1": 0,
        "x2": 6000,
        "y2": 0,
        "z2": 3200,
    },
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
    # parametric shapes (structural model)
    **{type(shape).__name__: shape.model_dump(mode="json", exclude_none=True) for shape in _SHAPES},
}

"""Material and object libraries (Parts 3 and 4)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from saengine.library import (
    BuildingModel,
    FloorPlan,
    MaterialLibrary,
    ObjectLibrary,
    ProjectSettings,
    default_material_library,
    default_object_library,
)
from saengine.library import objects as o
from saengine.library.export import generate_typescript
from saengine.library.sections import section_properties

REPO = Path(__file__).resolve().parents[2]
GENERATED = (
    REPO
    / "workbench/src/vs/workbench/services/saengineProject/common/projectLibraries.generated.ts"
)

EXAMPLE_OBJECTS = {
    "schema": "saengine.objects/1",
    "objects": [
        {
            "id": "B1",
            "name": "Beam 250x450",
            "kind": "beam",
            "material": "C24.1",
            "profile": {"shape": "rectangle", "xDim": 250, "yDim": 450},
            "reinforcement": {
                "material": "B500DWR",
                "cover": 40,
                "longitudinal": [
                    {"position": "top", "count": 2, "dia": 16},
                    {"position": "bottom", "count": 3, "dia": 20},
                ],
                "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
            },
        },
        {
            "id": "SB1",
            "name": "Steel beam",
            "kind": "beam",
            "material": "A992",
            "profile": {
                "shape": "I",
                "overallWidth": 165,
                "overallDepth": 310,
                "webThickness": 5.8,
                "flangeThickness": 9.7,
                "filletRadius": 8.9,
            },
        },
        {"id": "S1", "name": "Slab 150", "kind": "slab", "material": "C24.1", "thickness": 150},
        {
            "id": "W1",
            "name": "Brick wall",
            "kind": "wall",
            "material": "BRICK-1",
            "thickness": 250,
            "structural": False,
        },
        {
            "id": "P1",
            "name": "Bored pile 600",
            "kind": "pile",
            "material": "C24.1",
            "pileType": "bored",
            "profile": {"shape": "circle", "radius": 300},
            "length": 18000,
        },
        {
            "id": "PC1",
            "name": "Pile cap 4P",
            "kind": "pileCap",
            "material": "C24.1",
            "length": 2400,
            "width": 2400,
            "thickness": 900,
            "pile": "P1",
            "pileCount": 4,
        },
        {
            "id": "ST1",
            "name": "Stair flight",
            "kind": "staircase",
            "material": "C20.7",
            "waistThickness": 150,
            "riser": 150,
            "tread": 250,
            "flightWidth": 1200,
        },
        {
            "id": "F1",
            "name": "Isolated footing",
            "kind": "footing",
            "material": "C24.1",
            "length": 2000,
            "width": 2000,
            "thickness": 450,
        },
        {
            "id": "BR1",
            "name": "Angle brace",
            "kind": "brace",
            "material": "A36",
            "profile": {"shape": "L", "depth": 75, "width": 75, "thickness": 6},
        },
    ],
}


def test_generated_typescript_is_up_to_date() -> None:
    assert GENERATED.read_text(encoding="utf-8") == generate_typescript(), (
        "Run: python -m saengine.library.export " + str(GENERATED.relative_to(REPO))
    )


def test_default_materials_follow_code_formulas() -> None:
    library = default_material_library()
    c25 = library.get("C24.1")
    assert c25 is not None and c25.concrete is not None
    assert c25.mechanical.E == pytest.approx(4700 * math.sqrt(24.1), abs=10)
    assert c25.concrete.ft == pytest.approx(0.62 * math.sqrt(24.1), abs=0.01)
    assert [m.id for m in library.materials] == [
        "C20.7",
        "C24.1",
        "C27.6",
        "C31",
        "B420DWR",
        "B500DWR",
        "A36",
        "A572-50",
        "A992",
        "M1-4",
        "M1-6",
        "BRICK-1",
    ]
    # Round trip through the JSON written into a new project.
    dumped = library.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert MaterialLibrary.model_validate(dumped) == library


def test_material_rules() -> None:
    def material(**overrides: object) -> dict:
        return {
            "id": "X",
            "name": "X",
            "category": "concrete",
            "mechanical": {"E": 25000},
            "concrete": {"fc": 25},
            **overrides,
        }

    MaterialLibrary.model_validate({"materials": [material()]})
    for bad, message in [
        (material(concrete=None), "needs 'concrete'"),
        (material(steel={"fy": 400}), "do not apply"),
        (material(mechanical={}), "needs mechanical.E"),
        (material(composition={"method": "nominal", "ratio": [1, 4]}), "3 ratio parts"),
        (
            material(category="rebar", concrete=None, steel={"fy": 500, "fu": 400}),
            "fu must not be lower",
        ),
    ]:
        with pytest.raises(ValidationError, match=message):
            MaterialLibrary.model_validate({"materials": [bad]})
    with pytest.raises(ValidationError, match="duplicate material ids: X"):
        MaterialLibrary.model_validate({"materials": [material(), material()]})


def test_object_library_and_material_references() -> None:
    objects = ObjectLibrary.model_validate(EXAMPLE_OBJECTS)
    assert [type(x).__name__ for x in objects.objects] == [
        "Beam",
        "Beam",
        "Slab",
        "Wall",
        "Pile",
        "PileCap",
        "Staircase",
        "Footing",
        "Brace",
    ]
    assert objects.check_materials(default_material_library()) == []

    broken = ObjectLibrary.model_validate(
        {
            "objects": [
                {**EXAMPLE_OBJECTS["objects"][0], "material": "C99"},
                {
                    **EXAMPLE_OBJECTS["objects"][0],
                    "id": "B2",
                    "reinforcement": {
                        **EXAMPLE_OBJECTS["objects"][0]["reinforcement"],
                        "material": "C24.1",
                    },
                },
            ]
        }
    )
    assert broken.check_materials(default_material_library()) == [
        "B1: unknown material 'C99'",
        "B2: reinforcement material 'C24.1' is not rebar",
    ]

    with pytest.raises(ValidationError, match="unknown pile type 'P9'"):
        ObjectLibrary.model_validate({"objects": [{**EXAMPLE_OBJECTS["objects"][5], "pile": "P9"}]})


@pytest.mark.parametrize(
    ("profile", "area", "ixx"),
    [
        (o.RectangleProfile(xDim=250, yDim=450), 250 * 450, 250 * 450**3 / 12),
        (o.CircleProfile(radius=300), math.pi * 300**2, math.pi * 600**4 / 64),
        (
            o.RectangleHollowProfile(xDim=200, yDim=300, wallThickness=10),
            200 * 300 - 180 * 280,
            (200 * 300**3 - 180 * 280**3) / 12,
        ),
        (
            o.IShapeProfile(
                overallWidth=200, overallDepth=400, webThickness=10, flangeThickness=20
            ),
            2 * 200 * 20 + 360 * 10,
            (200 * 400**3 - 190 * 360**3) / 12,
        ),
    ],
)
def test_section_properties(profile: o.Profile, area: float, ixx: float) -> None:
    props = section_properties(profile)
    # Polygonal circles are slightly smaller than true circles.
    tolerance = 0.004 if isinstance(profile, o.CircleProfile) else 1e-6
    assert props.area == pytest.approx(area, rel=tolerance)
    assert props.ixx == pytest.approx(ixx, rel=tolerance)


def test_rectangle_torsion_constant() -> None:
    # Closed-form J of a 250 x 450 rectangle (Roark): a b³ [1/3 - 0.21 (b/a)(1 - b⁴/12a⁴)].
    a, b = 450, 250
    expected = a * b**3 * (1 / 3 - 0.21 * (b / a) * (1 - b**4 / (12 * a**4)))
    assert section_properties(o.RectangleProfile(xDim=b, yDim=a)).j == pytest.approx(
        expected, rel=0.005
    )


def test_editor_templates_are_valid() -> None:
    from saengine.library import bim as b
    from saengine.library import floorplan as f
    from saengine.library import materials as m
    from saengine.library import settings as st
    from saengine.library import shapes as sh
    from saengine.library import structure as sm
    from saengine.library.templates import TEMPLATES

    schemas = {
        **MaterialLibrary.model_json_schema(by_alias=True)["$defs"],
        **ObjectLibrary.model_json_schema(by_alias=True)["$defs"],
        **FloorPlan.model_json_schema(by_alias=True)["$defs"],
        **ProjectSettings.model_json_schema(by_alias=True)["$defs"],
        **BuildingModel.model_json_schema(by_alias=True)["$defs"],
        **sm.StructuralModel.model_json_schema(by_alias=True)["$defs"],
        **sh.ShapeInput.model_json_schema(by_alias=True)["$defs"],
    }
    for key, value in TEMPLATES.items():
        name = key.split(":")[0]
        assert name in schemas, f"{key} is not a schema definition"
        module = next(x for x in (m, o, st, f, b, sm, sh) if hasattr(x, name))
        model = getattr(module, name)
        model.model_validate(value)
        if key.startswith("Material:"):
            assert value["category"] == key.split(":")[1]
    # Every alternative of every union has a template, so the editor can switch to it.
    for name, schema in schemas.items():
        for prop in schema.get("properties", {}).values():
            for branch in prop.get("oneOf", []) + prop.get("anyOf", []):
                ref = branch.get("$ref", "").rsplit("/", 1)[-1]
                if ref and schemas[ref].get("type") == "object":
                    assert ref in TEMPLATES or ref == "Material", f"{name}: no template for {ref}"


def test_check_reports_problems_per_entry() -> None:
    import json

    from saengine.library.check import check_library

    materials = default_material_library().model_dump(mode="json", by_alias=True, exclude_none=True)
    assert check_library("materials", json.dumps(materials)) == []

    materials["materials"][4]["steel"]["fu"] = 100  # B420DWR, fy 420
    materials["materials"][0]["composition"]["ratio"] = [1, 2]  # concrete needs three parts
    assert check_library("materials", json.dumps(materials)) == [
        {"index": 0, "path": "", "message": "a nominal concrete mix has 3 ratio parts"},
        {"index": 4, "path": "steel", "message": "fu must not be lower than fy"},
    ]

    objects = json.dumps(
        {
            "objects": [
                EXAMPLE_OBJECTS["objects"][0],
                {**EXAMPLE_OBJECTS["objects"][2], "material": "C99"},
            ]
        }
    )
    good = default_material_library().model_dump_json(by_alias=True, exclude_none=True)
    assert check_library("objects", objects, good) == [
        {"index": 1, "path": "material", "message": "unknown material 'C99'"},
    ]
    assert check_library("objects", "{ nope", good)[0]["message"].startswith("Invalid JSON")


def test_new_projects_have_object_types_to_place() -> None:
    objects = default_object_library()
    assert [(o.id, o.kind) for o in objects.objects] == [
        ("C400x400", "column"),
        ("B250x450", "beam"),
        ("S125", "slab"),
        ("W200", "wall"),
        ("W125B", "wall"),
    ]
    assert objects.check_materials(default_material_library()) == []


def test_concrete_e_and_fr_follow_fc_and_far_values_are_flagged() -> None:
    from saengine.library.materials import (
        Material,
        concrete_modulus,
        modulus_of_rupture,
        plausibility,
    )

    assert (concrete_modulus(20.7), modulus_of_rupture(20.7)) == (21380.0, 2.82)
    for material in default_material_library().materials:
        assert plausibility(material) == [], material.id
    concrete = default_material_library().materials[0].model_dump(by_alias=True)
    concrete["concrete"]["fc"] = 20.7
    concrete["concrete"]["ft"] = 34.5  # fr typed in psi-like scale
    concrete["mechanical"]["density"] = 24000
    paths = [path for path, _ in plausibility(Material.model_validate(concrete))]
    assert paths == ["mechanical.density", "concrete.ft"]

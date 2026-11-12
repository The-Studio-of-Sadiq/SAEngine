"""The material set a new project starts with: common Bangladeshi practice under the default pack (BNBC 2020).

Every value is either a specified/nominal value of the named standard, or derived from one
with a code formula stated in the material's ``source``. Values marked "typical" are
starting points for the engineer to replace with test results.
"""

from __future__ import annotations

from saengine.library.bim import BuildingModel
from saengine.library.floorplan import FloorPlan, GridLine, Grids, Story
from saengine.library.materials import (
    Category,
    ConcreteProperties,
    MasonryProperties,
    Material,
    MaterialDefaults,
    MaterialLibrary,
    Mechanical,
    NominalMix,
    Source,
    SteelProperties,
    concrete_modulus,
    modulus_of_rupture,
)
from saengine.library.objects import ObjectLibrary

PSI_TO_MPA = 0.00689476

STEEL_DENSITY = 7850.0
CONCRETE_DENSITY = 2400.0  # reinforced normal-weight concrete, ~23.6 kN/m³ (default pack Part 6)


def _steel_e() -> float:
    """Es of steel [MPa], read when the material set is made: the code pack in force's
    (``materials.steelE``, 200 000 MPa in the default pack) when one is set
    (:func:`saengine.codes.context.using`), else the built-in default pack's. No pack is loaded
    here: the set is also made while packs load (their building templates are checked then)."""
    from saengine.codes import context as code_context
    from saengine.codes.tables import builtin_table

    pack = code_context.in_force()
    if pack is not None and pack.has("materials"):
        return float(pack.table("materials").steelE)
    return float(builtin_table("materials").steelE)


def _concrete(psi: int, mix: NominalMix | None) -> Material:
    fc = round(psi * PSI_TO_MPA, 1)
    return Material(
        id=f"C{fc:g}",
        name=f"Concrete f'c {fc:g} MPa ({psi} psi)",
        category=Category.CONCRETE,
        mechanical=Mechanical(
            E=concrete_modulus(fc),
            nu=0.2,
            density=CONCRETE_DENSITY,
            alpha=1.0e-5,
        ),
        concrete=ConcreteProperties(fc=fc, ft=modulus_of_rupture(fc), maxAggregate=20),
        composition=mix,
        source=Source(
            standard="BNBC 2020 Part 6 / ACI 318-19",
            note="E = 4700√f'c and modulus of rupture 0.62√f'c (normal-weight concrete). "
            + (
                "Nominal mix is typical site practice; confirm strength by trial mix and cylinder tests."
                if mix
                else "Use a design mix for this grade."
            ),
        ),
    )


def _rebar(grade: str, fy: float) -> Material:
    return Material(
        id=grade,
        name=f"Rebar {grade}",
        category=Category.REBAR,
        mechanical=Mechanical(E=_steel_e(), nu=0.3, density=STEEL_DENSITY, alpha=1.2e-5),
        steel=SteelProperties(grade=grade, fy=fy),
        source=Source(
            standard="BDS ISO 6935-2:2016",
            note="Specified characteristic yield strength. Take fu and elongation from the mill certificate.",
        ),
    )


def _structural_steel(
    material_id: str, grade: str, standard: str, fy: float, fu: float
) -> Material:
    return Material(
        id=material_id,
        name=f"Structural steel {grade}",
        category=Category.STEEL,
        mechanical=Mechanical(E=_steel_e(), nu=0.3, density=STEEL_DENSITY, alpha=1.2e-5),
        steel=SteelProperties(grade=grade, fy=fy, fu=fu),
        source=Source(standard=standard, note="Specified minimum yield and tensile strengths."),
    )


def _mortar(ratio: float) -> Material:
    return Material(
        id=f"M1-{ratio:g}",
        name=f"Cement mortar 1:{ratio:g}",
        category=Category.MORTAR,
        mechanical=Mechanical(density=2080),
        composition=NominalMix(ratio=[1, ratio], cementType="OPC"),
        source=Source(note="Typical cement:sand mortar by volume; density ~20.4 kN/m³."),
    )


def _pack_rebars() -> list[Material]:
    """Walk 4 (W4A-6): the reinforcement grades of the code pack in force
    (``materials.rebarGrades``: the US pack's ASTM A615 / A706 grades), first in the set so a
    project under it takes them; none for a pack without (the default pack)."""
    from saengine.codes import context as code_context

    pack = code_context.in_force()
    if pack is None or not pack.has("materials"):
        return []
    out = []
    for grade in getattr(pack.table("materials"), "rebarGrades", None) or []:
        material = _rebar(grade.id, grade.fy)
        material.name = f"Rebar {grade.name}"
        material.steel.grade = grade.name
        if grade.standard:
            material.source.standard = grade.standard
        out.append(material)
    return out


def default_concrete_id(materials: list[Material]) -> str | None:
    """The concrete a new project uses where a type names none: the first of ``materials`` (in
    order of strength) that meets both of the default pack's least f'c, for structural concrete
    and for members resisting earthquake forces (``materials.structuralFcMin`` and
    ``seismicFcMin``: a new project does not know its seismic system yet), else the strongest.
    Read from the pack, so another pack's floor gives another default; no grade is fixed here."""
    concretes = [m for m in materials if m.category == Category.CONCRETE and m.concrete]
    if not concretes:
        return None
    from saengine.codes.tables import builtin_table

    table = builtin_table("materials")
    floors = [
        v for v in (table.structuralFcMin, getattr(table, "seismicFcMin", None)) if v is not None
    ]
    least = max(floors) if floors else None
    for material in sorted(concretes, key=lambda m: m.concrete.fc):
        if least is None or material.concrete.fc >= least:
            return material.id
    return max(concretes, key=lambda m: m.concrete.fc).id


def default_material_library() -> MaterialLibrary:
    library = MaterialLibrary(
        materials=[
            *_pack_rebars(),
            _concrete(3000, NominalMix(ratio=[1, 2, 4], waterCement=0.5, cementType="OPC")),
            _concrete(3500, NominalMix(ratio=[1, 1.5, 3], waterCement=0.45, cementType="OPC")),
            _concrete(4000, None),
            _concrete(4500, None),
            _rebar("B420DWR", 420),
            _rebar("B500DWR", 500),
            _structural_steel("A36", "ASTM A36", "ASTM A36/A36M", 250, 400),
            _structural_steel("A572-50", "ASTM A572 Grade 50", "ASTM A572/A572M", 345, 450),
            _structural_steel("A992", "ASTM A992", "ASTM A992/A992M", 345, 450),
            _mortar(4),
            _mortar(6),
            Material(
                id="BRICK-1",
                name="First-class brick masonry",
                category=Category.MASONRY,
                mechanical=Mechanical(density=1920),
                masonry=MasonryProperties(unit="first-class burnt clay brick", mortar="M1-4"),
                source=Source(
                    note="Typical unit weight ~18.85 kN/m³. Enter unit and prism strengths from tests."
                ),
            ),
        ]
    )
    # The project's concrete is named, so it is not simply the first (weakest) one in the list.
    library.defaults = MaterialDefaults(concrete=default_concrete_id(library.materials))
    return library


def default_object_library() -> ObjectLibrary:
    """The object types a new project starts with, so the floor plan's Fill and draw tools have
    something to place: a 400x400 column, a 250x450 beam, a 125 mm two-way slab, a 200 mm RC
    wall and a 125 mm brick partition, of 3500 psi concrete (C24.1) and B420DWR bars. Typical
    starting sizes for a low-rise frame in Bangladesh, for the engineer to size."""
    rebar = "B420DWR"
    return ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "C400x400",
                    "name": "Column 400x400",
                    "kind": "column",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                    "reinforcement": {
                        "material": rebar,
                        "cover": 40,
                        "longitudinal": [{"position": "perimeter", "count": 8, "dia": 16}],
                        "transverse": {"type": "tie", "dia": 10, "spacing": 150, "legs": 2},
                    },
                },
                {
                    "id": "B250x450",
                    "name": "Beam 250x450",
                    "kind": "beam",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 250, "yDim": 450},
                    "reinforcement": {
                        "material": rebar,
                        "cover": 40,
                        "longitudinal": [
                            {"position": "top", "count": 2, "dia": 16},
                            {"position": "bottom", "count": 3, "dia": 16},
                        ],
                        "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
                    },
                },
                {
                    "id": "S125",
                    "name": "Slab 125",
                    "kind": "slab",
                    "material": "C24.1",
                    "thickness": 125,
                    "system": "twoWay",
                    "reinforcement": {
                        "material": rebar,
                        "cover": 20,
                        "bottomX": {"dia": 10, "spacing": 150},
                        "bottomY": {"dia": 10, "spacing": 150},
                    },
                },
                {
                    "id": "W200",
                    "name": "RC wall 200",
                    "kind": "wall",
                    "material": "C24.1",
                    "thickness": 200,
                    "structural": True,
                    "reinforcement": {
                        "material": rebar,
                        "cover": 25,
                        "layers": 2,
                        "vertical": {"dia": 12, "spacing": 200},
                        "horizontal": {"dia": 10, "spacing": 200},
                    },
                },
                {
                    "id": "W125B",
                    "name": "Brick partition 125",
                    "kind": "wall",
                    "material": "BRICK-1",
                    "thickness": 125,
                    "structural": False,
                },
            ]
        }
    )


def default_floor_plan() -> FloorPlan:
    """A one-bay starting grid and a base plus one level; the engineer edits both."""
    return FloorPlan(
        grids=Grids(
            x=[GridLine(label="A", position=0), GridLine(label="B", position=6000)],
            y=[GridLine(label="1", position=0), GridLine(label="2", position=5000)],
        ),
        stories=[
            Story(id="BASE", name="Base", elevation=0),
            Story(id="L1", name="Level 1", elevation=3200),
        ],
    )


def default_building_model() -> BuildingModel:
    """Empty until it is generated from the floor plan."""
    return BuildingModel()

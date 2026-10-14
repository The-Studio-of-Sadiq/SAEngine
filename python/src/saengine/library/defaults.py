"""The material set a new project starts with: common Bangladeshi practice under BNBC 2020.

Every value is either a specified/nominal value of the named standard, or derived from one
with a code formula stated in the material's ``source``. Values marked "typical" are
starting points for the engineer to replace with test results.
"""

from __future__ import annotations

import math

from saengine.library.materials import (
    Category,
    ConcreteProperties,
    MasonryProperties,
    Material,
    MaterialLibrary,
    Mechanical,
    NominalMix,
    Source,
    SteelProperties,
)
from saengine.library.objects import ObjectLibrary

PSI_TO_MPA = 0.00689476

STEEL_E = 200_000.0  # MPa, ACI 318-19 20.2.2.2 / AISC 360-22
STEEL_DENSITY = 7850.0
CONCRETE_DENSITY = 2400.0  # reinforced normal-weight concrete, ~23.6 kN/m³ (BNBC 2020 Part 6)


def _concrete(psi: int, mix: NominalMix | None) -> Material:
    fc = round(psi * PSI_TO_MPA, 1)
    return Material(
        id=f"C{fc:g}",
        name=f"Concrete f'c {fc:g} MPa ({psi} psi)",
        category=Category.CONCRETE,
        mechanical=Mechanical(
            E=round(4700 * math.sqrt(fc), -1),
            nu=0.2,
            density=CONCRETE_DENSITY,
            alpha=1.0e-5,
        ),
        concrete=ConcreteProperties(fc=fc, ft=round(0.62 * math.sqrt(fc), 2), maxAggregate=20),
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
        mechanical=Mechanical(E=STEEL_E, nu=0.3, density=STEEL_DENSITY, alpha=1.2e-5),
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
        mechanical=Mechanical(E=STEEL_E, nu=0.3, density=STEEL_DENSITY, alpha=1.2e-5),
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


def default_material_library() -> MaterialLibrary:
    return MaterialLibrary(
        materials=[
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


def default_object_library() -> ObjectLibrary:
    return ObjectLibrary()

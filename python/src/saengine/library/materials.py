"""Physical materials of a project (``03 Materials/materials.json``).

Units are fixed SI regardless of how the UI displays them: stresses and moduli in MPa,
lengths in mm, density in kg/m³, thermal expansion in 1/°C.

Categories and property groups follow IFC (``IfcMaterial.Category`` with the
``Pset_MaterialCommon``, ``Pset_MaterialMechanical``, ``Pset_MaterialConcrete`` and
``Pset_MaterialSteel`` property sets) so the library maps directly onto IFC export. The
analysis materials OpenSees needs (Concrete02, Steel02, ...) are derived from these
physical properties when the FEM model is built; they are not stored here.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title

SCHEMA_ID = "saengine.materials/1"

Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]+$", min_length=1, max_length=64)]


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class Category(str, Enum):
    CONCRETE = "concrete"
    REBAR = "rebar"
    STEEL = "steel"
    MASONRY = "masonry"
    MORTAR = "mortar"
    OTHER = "other"


class Mechanical(_Model):
    """Pset_MaterialCommon / Pset_MaterialMechanical."""

    E: float | None = Field(default=None, gt=0, description="Young's modulus [MPa].")
    nu: float | None = Field(default=None, ge=0, lt=0.5, description="Poisson's ratio [-].")
    density: float | None = Field(default=None, gt=0, description="Mass density [kg/m³].")
    alpha: float | None = Field(
        default=None, ge=0, description="Coefficient of thermal expansion [1/°C]."
    )


class ConcreteProperties(_Model):
    """Pset_MaterialConcrete."""

    fc: float = Field(gt=0, description="Specified compressive strength f'c [MPa].")
    ft: float | None = Field(
        default=None, gt=0, description="Tensile strength / modulus of rupture [MPa]."
    )
    maxAggregate: float | None = Field(
        default=None, gt=0, description="Maximum aggregate size [mm]."
    )
    exposure: str | None = Field(
        default=None, description="Exposure class, as named by the design code."
    )


class SteelProperties(_Model):
    """Pset_MaterialSteel; used for reinforcing bars and structural steel."""

    grade: str | None = Field(default=None, description="Grade designation, e.g. B500DWR, A992.")
    fy: float = Field(gt=0, description="Yield strength [MPa].")
    fu: float | None = Field(default=None, gt=0, description="Ultimate tensile strength [MPa].")
    elongation: float | None = Field(default=None, gt=0, description="Elongation at fracture [%].")
    fyActual: float | None = Field(
        default=None,
        gt=0,
        title="Actual fy (mill test)",
        description="Actual yield strength from the mill tests [MPa] (BNBC Sec 8.3.3.4(b)(i)).",
    )
    fuActual: float | None = Field(
        default=None,
        gt=0,
        title="Actual fu (mill test)",
        description="Actual tensile strength from the mill tests [MPa] (BNBC Sec 8.3.3.4(b)(ii)).",
    )

    @model_validator(mode="after")
    def _fu_above_fy(self) -> SteelProperties:
        if self.fu is not None and self.fu < self.fy:
            raise ValueError("fu must not be lower than fy")
        return self


class MasonryProperties(_Model):
    unit: str = Field(description="Masonry unit, e.g. 'first-class brick', 'concrete block'.")
    unitStrength: float | None = Field(
        default=None, gt=0, description="Compressive strength of the unit [MPa]."
    )
    fm: float | None = Field(
        default=None, gt=0, description="Masonry (prism) compressive strength f'm [MPa]."
    )
    mortar: Id | None = Field(default=None, description="Id of the mortar material.")


class NominalMix(_Model):
    """Volumetric site mix, e.g. 1:1.5:3 for concrete or 1:4 for mortar."""

    method: Literal["nominal"] = "nominal"
    ratio: list[Annotated[float, Field(gt=0)]] = Field(
        min_length=2,
        max_length=3,
        description="Volume ratio cement : sand [: coarse aggregate], cement first.",
    )
    waterCement: float | None = Field(
        default=None, gt=0, le=1, description="Water/cement ratio by mass [-]."
    )
    cementType: str | None = Field(default=None, description="Cement type, e.g. OPC, PCC.")


class Admixture(_Model):
    name: str
    amount: float = Field(gt=0)
    unit: Literal["kg/m3", "l/m3", "% of cement"]


class DesignMix(_Model):
    """Mix proportions per cubic metre of concrete, from a mix design."""

    method: Literal["design"] = "design"
    cement: float = Field(gt=0, description="Cement [kg/m³].")
    water: float = Field(gt=0, description="Water [kg/m³].")
    fineAggregate: float = Field(gt=0, description="Fine aggregate (sand) [kg/m³].")
    coarseAggregate: float | None = Field(
        default=None, gt=0, description="Coarse aggregate [kg/m³]; none for mortar."
    )
    cementType: str | None = None
    admixtures: list[Admixture] = Field(default_factory=list)


Composition = Annotated[NominalMix | DesignMix, Field(discriminator="method")]


class Source(_Model):
    """Where the values come from, so engineers can check them."""

    standard: str | None = Field(default=None, description="Standard or code the values follow.")
    note: str | None = None


class Material(_Model):
    id: Id
    name: str = Field(min_length=1)
    category: Category
    description: str | None = None
    mechanical: Mechanical = Field(default_factory=Mechanical)
    concrete: ConcreteProperties | None = None
    steel: SteelProperties | None = None
    masonry: MasonryProperties | None = None
    composition: Composition | None = Field(
        default=None, description="Mix of a concrete or mortar, used for quantities (BOQ)."
    )
    source: Source | None = None

    @model_validator(mode="after")
    def _category_groups(self) -> Material:
        required = {
            Category.CONCRETE: "concrete",
            Category.REBAR: "steel",
            Category.STEEL: "steel",
            Category.MASONRY: "masonry",
        }.get(self.category)
        if required and getattr(self, required) is None:
            raise ValueError(f"a {self.category.value} material needs '{required}' properties")
        for group in ("concrete", "steel", "masonry"):
            if getattr(self, group) is not None and group != required:
                raise ValueError(
                    f"'{group}' properties do not apply to a {self.category.value} material"
                )
        if (
            self.category in (Category.CONCRETE, Category.REBAR, Category.STEEL)
            and self.mechanical.E is None
        ):
            raise ValueError(f"a {self.category.value} material needs mechanical.E")
        if self.composition is not None and self.category not in (
            Category.CONCRETE,
            Category.MORTAR,
        ):
            raise ValueError("composition only applies to concrete and mortar")
        if isinstance(self.composition, NominalMix):
            expected = 3 if self.category == Category.CONCRETE else 2
            if len(self.composition.ratio) != expected:
                raise ValueError(f"a nominal {self.category.value} mix has {expected} ratio parts")
        return self


class MaterialLibrary(_Model):
    schema_: Literal["saengine.materials/1"] = Field(default=SCHEMA_ID, alias="schema")
    materials: list[Material] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self) -> MaterialLibrary:
        ids = [m.id for m in self.materials]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate material ids: {', '.join(duplicates)}")
        mortars = {m.id for m in self.materials if m.category == Category.MORTAR}
        for m in self.materials:
            if m.masonry and m.masonry.mortar and m.masonry.mortar not in mortars:
                raise ValueError(f"material '{m.id}' refers to unknown mortar '{m.masonry.mortar}'")
        return self

    def get(self, material_id: str) -> Material | None:
        return next((m for m in self.materials if m.id == material_id), None)

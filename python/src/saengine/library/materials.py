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

import math
from enum import Enum
from typing import Annotated, Any, Literal

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
    TIMBER = "timber"
    MORTAR = "mortar"
    OTHER = "other"


class Mechanical(_Model):
    """Pset_MaterialCommon / Pset_MaterialMechanical."""

    E: float | None = Field(
        default=None,
        gt=0,
        description="Young's modulus [MPa]. Concrete: follows f'c (Ec = 4700 √f'c, BNBC 2020 "
        "Part 6 Sec 6.1.7.1) until another value is entered.",
    )
    nu: float | None = Field(default=None, ge=0, lt=0.5, description="Poisson's ratio [-].")
    density: float | None = Field(default=None, gt=0, description="Mass density [kg/m³].")
    alpha: float | None = Field(
        default=None, ge=0, description="Coefficient of thermal expansion [1/°C]."
    )


class ConcreteProperties(_Model):
    """Pset_MaterialConcrete."""

    fc: float = Field(gt=0, description="Specified compressive strength f'c [MPa].")
    ft: float | None = Field(
        default=None,
        gt=0,
        title="Modulus of rupture fr",
        description="Tensile strength / modulus of rupture [MPa]. Follows f'c (fr = 0.62 √f'c, "
        "BNBC 2020 Part 6 Eq. 6.6.3) until another value is entered.",
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
    unitKind: Literal["clay", "concrete"] = Field(
        default="clay",
        title="Unit kind",
        description="Burnt clay bricks or concrete blocks: sets the allowable shear and "
        "tension of the masonry design (the code pack's masonry table).",
        json_schema_extra={"enumDescriptions": ["Clay brick", "Concrete block"]},
    )
    mortarType: str | None = Field(
        default=None,
        max_length=16,
        title="Mortar grade",
        description="A mortar grade of the code pack (e.g. M1 to M6); empty: from the mortar "
        "material's cement : sand mix.",
    )
    specialInspection: bool = Field(
        default=False,
        title="Special inspection and prism tests",
        description="The masonry is built under special inspection with prism tests during "
        "construction and f'm is from prism tests: the full allowable stresses. Otherwise the "
        "code pack's reduced share of them (e.g. 50 %).",
    )
    units: Literal["solid", "hollow"] = Field(
        default="solid",
        description="Solid units (bricks) or hollow units (blocks).",
        json_schema_extra={"enumDescriptions": ["Solid", "Hollow"]},
    )
    grouting: Literal["none", "partial", "full"] = Field(
        default="none",
        description="Grout in the cores or cavities: none, at the bars only, or every cell.",
        json_schema_extra={"enumDescriptions": ["Not grouted", "Partly grouted", "Fully grouted"]},
    )
    bond: Literal["running", "stack"] = Field(
        default="running",
        description="Running bond (staggered head joints) or stack bond.",
        json_schema_extra={"enumDescriptions": ["Running bond", "Stack bond"]},
    )


class TimberProperties(_Model):
    """Sawn structural timber (BNBC 2020 Part 6 Chapter 11)."""

    species: str | None = Field(default=None, description="Species, e.g. Sal, Garjan, Teak.")
    group: Literal["A", "B", "C"] = Field(
        default="B",
        title="Strength group",
        description="Strength group by modulus of elasticity: A (E at least 12.6 GPa), B "
        "(9.8-12.6 GPa), C (5.6-9.8 GPa); the code pack gives each group's permissible "
        "stresses.",
        json_schema_extra={"enumDescriptions": ["Group A", "Group B", "Group C"]},
    )
    location: Literal["inside", "outside", "wet"] = Field(
        default="inside",
        title="Location of use",
        description="Inside (dry), outside (exposed to the weather) or wet (always damp).",
        json_schema_extra={"enumDescriptions": ["Inside", "Outside", "Wet"]},
    )


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
    timber: TimberProperties | None = None
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
            Category.TIMBER: "timber",
        }.get(self.category)
        if required and getattr(self, required) is None:
            raise ValueError(f"a {self.category.value} material needs '{required}' properties")
        for group in ("concrete", "steel", "masonry", "timber"):
            if getattr(self, group) is not None and group != required:
                raise ValueError(
                    f"'{group}' properties do not apply to a {self.category.value} material"
                )
        if (
            self.category in (Category.CONCRETE, Category.REBAR, Category.STEEL, Category.TIMBER)
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


class MaterialDefaults(_Model):
    """The project's materials of choice (the New Building wizard's): what an element without
    its own gets, e.g. the bars the design proposes for a type that has none yet."""

    concrete: Id | None = Field(default=None, description="Id of the project's concrete.")
    rebar: Id | None = Field(default=None, description="Id of the project's reinforcing bars.")


class MaterialLibrary(_Model):
    schema_: Literal["saengine.materials/1"] = Field(default=SCHEMA_ID, alias="schema")
    materials: list[Material] = Field(default_factory=list)
    defaults: MaterialDefaults | None = Field(
        default=None,
        description="The project's concrete and reinforcing bars, used wherever a type has none "
        "of its own; else the first of the category.",
    )

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
        if self.defaults is not None:
            for key, category in (("concrete", Category.CONCRETE), ("rebar", Category.REBAR)):
                chosen = getattr(self.defaults, key)
                found = self.get(chosen) if chosen else None
                if chosen and (found is None or found.category != category):
                    raise ValueError(
                        f"defaults.{key} '{chosen}' is not a {category.value} material"
                    )
        return self

    def get(self, material_id: str) -> Material | None:
        return next((m for m in self.materials if m.id == material_id), None)

    def default_concrete(self) -> str | None:
        """The project's concrete (``defaults.concrete``), else the first concrete."""
        return default_of(self, Category.CONCRETE)

    def default_rebar(self) -> str | None:
        """The project's reinforcing bars (``defaults.rebar``), else the first rebar."""
        return default_of(self, Category.REBAR)


def default_of(library: Any, category: Category) -> str | None:
    """The id of the project's material of ``category`` (concrete or rebar): the library's
    ``defaults`` entry, else its first material of that category, else None. ``library`` may be
    a :class:`MaterialLibrary` (or an object with its ``materials`` and ``defaults``) or the
    JSON of ``materials.json`` (read leniently: a stale or malformed entry falls back to the
    first one)."""
    if library is None:
        return None
    if not isinstance(library, dict):
        entries = [
            (m.id, getattr(m.category, "value", m.category))
            for m in getattr(library, "materials", None) or []
        ]
        defaults = getattr(library, "defaults", None)
        chosen = getattr(defaults, category.value, None) if defaults is not None else None
    else:
        entries = [
            (m.get("id"), m.get("category"))
            for m in library.get("materials") or []
            if isinstance(m, dict) and isinstance(m.get("id"), str)
        ]
        defaults = library.get("defaults")
        chosen = defaults.get(category.value) if isinstance(defaults, dict) else None
    ids = [i for i, c in entries if c == category.value]
    if isinstance(chosen, str) and chosen in ids:
        return chosen
    return ids[0] if ids else None


# ───────────────────────── values derived from f'c, and plausibility ─────────────────────────

#: Ec = 4700 √f'c [MPa] for normal-weight concrete (BNBC 2020 Part 6 Sec 6.1.7.1).
EC_COEFFICIENT = 4700.0
#: Modulus of rupture fr = 0.62 λ √f'c [MPa] (BNBC 2020 Part 6 Sec 6.2.5.2.3, Eq. 6.6.3).
FR_COEFFICIENT = 0.62
#: How far an entered E or fr may differ from the code relation before it is flagged.
DEVIATION_LIMIT = 0.10


def concrete_modulus(fc: float) -> float:
    """Ec of normal-weight concrete [MPa], rounded to 10 MPa as the defaults are."""
    return round(EC_COEFFICIENT * math.sqrt(fc), -1)


def modulus_of_rupture(fc: float) -> float:
    """fr of normal-weight concrete (λ = 1) [MPa], rounded to 0.01 MPa."""
    return round(FR_COEFFICIENT * math.sqrt(fc), 2)


#: Plausible ranges of entered values by category: (path, low, high, what).
_RANGES: dict[Category, tuple[tuple[str, float, float, str], ...]] = {
    Category.CONCRETE: (
        ("concrete.fc", 10.0, 100.0, "f'c"),
        ("mechanical.density", 1400.0, 2600.0, "density of concrete"),
        ("mechanical.nu", 0.1, 0.25, "Poisson's ratio of concrete"),
    ),
    Category.REBAR: (
        ("steel.fy", 200.0, 700.0, "fy of reinforcement"),
        ("mechanical.density", 7700.0, 8000.0, "density of steel"),
    ),
    Category.STEEL: (
        ("steel.fy", 200.0, 700.0, "fy of structural steel"),
        ("mechanical.density", 7700.0, 8000.0, "density of steel"),
    ),
    Category.MASONRY: (("mechanical.density", 1000.0, 2400.0, "density of masonry"),),
}


def _value(material: Material, path: str) -> float | None:
    group, _, key = path.partition(".")
    owner = getattr(material, group, None)
    value = getattr(owner, key, None) if owner is not None else None
    return float(value) if isinstance(value, int | float) else None


def plausibility(material: Material) -> list[tuple[str, str]]:
    """Values that pass the schema but are unlikely for the category (a typing slip, a value in
    the wrong unit), as (path, message): E and fr of concrete more than 10 % from the code
    relations of f'c (BNBC 2020 Part 6 Sec 6.1.7.1 and Eq. 6.6.3), and values outside the usual
    range of the category. Test results may justify a value; the message says what to check."""
    out: list[tuple[str, str]] = []
    for path, low, high, what in _RANGES.get(material.category, ()):
        value = _value(material, path)
        if value is not None and not low <= value <= high:
            out.append((path, f"{what} {value:g} is outside the usual {low:g} to {high:g}"))
    if material.category == Category.CONCRETE and material.concrete is not None:
        fc = material.concrete.fc
        for path, own, code, name, clause in (
            (
                "mechanical.E",
                material.mechanical.E,
                concrete_modulus(fc),
                "E",
                "Sec 6.1.7.1: Ec = 4700 √f'c",
            ),
            (
                "concrete.ft",
                material.concrete.ft,
                modulus_of_rupture(fc),
                "fr",
                "Eq. 6.6.3: fr = 0.62 √f'c",
            ),
        ):
            if own is not None and code > 0 and abs(own - code) / code > DEVIATION_LIMIT:
                out.append(
                    (
                        path,
                        (
                            f"{name} = {own:g} MPa differs by {abs(own - code) / code:.0%} from "
                            f"{code:g} MPa for f'c {fc:g} MPa (BNBC 2020 Part 6 {clause}); clear it "
                            "to use the code value, or keep it if it comes from tests"
                        ),
                    )
                )
        if isinstance(material.composition, NominalMix):
            ratio = material.composition.ratio
            usual = nominal_mix_strength(ratio)
            if usual is not None and fc > usual * (1 + NOMINAL_MIX_MARGIN):
                mix = ":".join(f"{r:g}" for r in ratio)
                out.append(
                    (
                        "composition",
                        (
                            f"f'c {fc:g} MPa is unlikely from a nominal {mix} mix, which usually "
                            f"gives about {usual:g} MPa: give a mix design (Composition › Design "
                            "mix) or a richer mix, or lower f'c. Nominal mixes suit ordinary "
                            "grades only (IS 456:2000 Cl. 9.3, up to M20)"
                        ),
                    )
                )
    return out


#: f'c a nominal concrete mix usually reaches in local practice [MPa], by its aggregate parts per
#: part of cement (sand + coarse): 1:1:2 about 4000 psi, 1:1.5:3 about 3500 psi (the default C24.1),
#: 1:2:4 about 3000 psi (the default C20.7), 1:3:6 about 2000 psi, leaner mixes less.
NOMINAL_MIX_STRENGTHS: tuple[tuple[float, float], ...] = (
    (3.0, 27.6),
    (4.5, 24.1),
    (6.0, 20.7),
    (9.0, 13.8),
    (float("inf"), 10.0),
)
#: How far f'c may exceed the usual strength of its nominal mix before it is flagged.
NOMINAL_MIX_MARGIN = 0.20


def nominal_mix_strength(ratio: list[float]) -> float | None:
    """The f'c a nominal concrete mix (cement : sand : coarse) usually reaches, or None for a
    ratio that is not a concrete mix."""
    if len(ratio) != 3 or ratio[0] <= 0:
        return None
    parts = (ratio[1] + ratio[2]) / ratio[0]
    return next(fc for limit, fc in NOMINAL_MIX_STRENGTHS if parts <= limit + 1e-9)

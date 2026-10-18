"""Typical Bangladeshi constructions as EnergyPlus materials and constructions.

The material properties are those of the reference data sets shipped with EnergyPlus version
26.2.0 (``DataSets/ASHRAE_2005_HOF_Materials.idf``, from the ASHRAE Handbook of Fundamentals
2005 Chapter 25; ``WindowGlassMaterials.idf``, ``WindowGasMaterials.idf``,
``WindowBlindMaterials.idf``; the nominal window U and SHGC are the comments of
``WindowConstructs.idf``). Each material keeps the data set's name in ``source``. The layer
thicknesses (12 mm plaster, 250 / 125 mm brick, 100 mm lime terracing, 150 mm slab) are SAEngine's
choice of the usual Bangladeshi practice, not BNBC's (it gives no constructions).

Units: m, W/m·K, kg/m³, J/kg·K; U-values W/m²K.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DATASET = "EnergyPlus version 26.2.0 DataSets"


@dataclass(frozen=True)
class Layer:
    name: str
    thickness: float  # m
    conductivity: float  # W/m·K
    density: float  # kg/m³
    specific_heat: float  # J/kg·K
    source: str
    roughness: str = "MediumRough"

    @property
    def resistance(self) -> float:
        return self.thickness / self.conductivity


def _hof(name: str, thickness: float, k: float, rho: float, c: float, source: str) -> Layer:
    return Layer(name, thickness, k, rho, c, f"{DATASET}/ASHRAE_2005_HOF_Materials.idf: {source}")


PLASTER = "Concrete: Cement/lime - mortar - and stucco - 1920 kg/m3"
BRICK = "Brick - fired clay - 1920 kg/m3"
CONCRETE = "Concrete: Sand and gravel or stone aggregate concretes - 2400 kg/m3"
LIME = "Concrete: Cement/lime - mortar - and stucco - 1600 kg/m3"
EPS = "Insulation: Expanded polystyrene - molded beads - 20kg/m3 density"


def plaster(t: float = 0.012) -> Layer:
    return _hof(f"Plaster {t * 1000:.0f}mm", t, 1.4, 1920, 900, PLASTER)


def brick(t: float) -> Layer:
    return _hof(f"Brick {t * 1000:.0f}mm", t, 0.895, 1920, 790, BRICK)


def concrete(t: float) -> Layer:
    return _hof(f"RC slab {t * 1000:.0f}mm", t, 2.15, 2400, 900, CONCRETE)


def lime_terracing(t: float = 0.100) -> Layer:
    """Lime terracing (lime, surki and brick chips): the data set has no such material; its
    1600 kg/m³ cement/lime mortar is the nearest (SAEngine's proxy)."""
    return _hof(f"Lime terracing {t * 1000:.0f}mm", t, 0.97, 1600, 900, LIME)


def eps(t: float = 0.050) -> Layer:
    return Layer(
        f"EPS insulation {t * 1000:.0f}mm", t, 0.036, 20, 1210,
        f"{DATASET}/ASHRAE_2005_HOF_Materials.idf: {EPS}", "VeryRough",
    )  # fmt: skip


@dataclass(frozen=True)
class Opaque:
    """An opaque construction, outside layer first."""

    key: str
    label: str
    layers: tuple[Layer, ...]
    #: The layer whose conductivity an entered U-value override adjusts (the structure's).
    main: int = 0

    def resistance(self) -> float:
        return sum(layer.resistance for layer in self.layers)


@dataclass(frozen=True)
class Glazing:
    key: str
    label: str
    #: Glass and gas layers, outside first: ("glass", name) / ("gas", name).
    layers: tuple[tuple[str, str], ...]
    u: float  # nominal centre-of-glass U [W/m²K] (WindowConstructs.idf comment)
    shgc: float  # nominal SHGC (WindowConstructs.idf comment)
    source: str


WALLS: dict[str, Opaque] = {
    "brick250": Opaque(
        "brick250", "250 mm brick wall, 12 mm plaster both sides",
        (plaster(), brick(0.250), plaster()), 1,
    ),
    "brick125": Opaque(
        "brick125", "125 mm brick wall, 12 mm plaster both sides",
        (plaster(), brick(0.125), plaster()), 1,
    ),
}  # fmt: skip
ROOFS: dict[str, Opaque] = {
    "rcLimeTerracing": Opaque(
        "rcLimeTerracing", "100 mm lime terracing on 150 mm RC slab, 12 mm plaster ceiling",
        (lime_terracing(), concrete(0.150), plaster()), 1,
    ),
    "rcInsulated": Opaque(
        "rcInsulated",
        "50 mm screed on 50 mm EPS insulation on 150 mm RC slab, 12 mm plaster ceiling",
        (plaster(0.050), eps(), concrete(0.150), plaster()), 1,
    ),
}  # fmt: skip
#: Floors between stories and exposed undersides: a symmetric RC slab (interzone surfaces
#: need the same construction both ways).
FLOOR = Opaque("rcSlab", "150 mm RC slab", (concrete(0.150),), 0)

GLAZINGS: dict[str, Glazing] = {
    "singleClear": Glazing(
        "singleClear", "Single clear glass 6 mm", (("glass", "CLEAR 6MM"),), 5.778, 0.819,
        f"{DATASET}/WindowConstructs.idf: Sgl Clr 6mm",
    ),
    "doubleClear": Glazing(
        "doubleClear", "Double clear glass 6 mm / 13 mm air / 6 mm",
        (("glass", "CLEAR 6MM"), ("gas", "AIR 13MM"), ("glass", "CLEAR 6MM")), 2.67, 0.703,
        f"{DATASET}/WindowConstructs.idf: Dbl Clr 6mm/13mm Air",
    ),
}  # fmt: skip
WALL_KEYS = tuple(WALLS)
ROOF_KEYS = tuple(ROOFS)
GLAZING_KEYS = tuple(GLAZINGS)

#: WindowGlassMaterials.idf, CLEAR 6MM (spectral average).
CLEAR_6MM = {
    "optical_data_type": "SpectralAverage",
    "thickness": 0.006,
    "solar_transmittance_at_normal_incidence": 0.775,
    "front_side_solar_reflectance_at_normal_incidence": 0.071,
    "back_side_solar_reflectance_at_normal_incidence": 0.071,
    "visible_transmittance_at_normal_incidence": 0.881,
    "front_side_visible_reflectance_at_normal_incidence": 0.080,
    "back_side_visible_reflectance_at_normal_incidence": 0.080,
    "infrared_transmittance_at_normal_incidence": 0.0,
    "front_side_infrared_hemispherical_emissivity": 0.84,
    "back_side_infrared_hemispherical_emissivity": 0.84,
    "conductivity": 0.9,
}
#: WindowGasMaterials.idf, AIR 13MM.
AIR_13MM = {"gas_type": "Air", "thickness": 0.0127}
#: WindowBlindMaterials.idf, BLIND WITH MEDIUM REFLECTIVITY SLATS (fixed at 45°).
BLIND = {
    "slat_orientation": "Horizontal",
    "slat_width": 0.025,
    "slat_separation": 0.01875,
    "slat_thickness": 0.001,
    "slat_angle": 45.0,
    "slat_conductivity": 0.9,
    "slat_beam_solar_transmittance": 0.0,
    "front_side_slat_beam_solar_reflectance": 0.5,
    "back_side_slat_beam_solar_reflectance": 0.5,
    "slat_diffuse_solar_transmittance": 0.0,
    "front_side_slat_diffuse_solar_reflectance": 0.5,
    "back_side_slat_diffuse_solar_reflectance": 0.5,
    "slat_beam_visible_transmittance": 0.0,
    "front_side_slat_beam_visible_reflectance": 0.5,
    "back_side_slat_beam_visible_reflectance": 0.5,
    "slat_diffuse_visible_transmittance": 0.0,
    "front_side_slat_diffuse_visible_reflectance": 0.5,
    "back_side_slat_diffuse_visible_reflectance": 0.5,
    "slat_infrared_hemispherical_transmittance": 0.0,
    "front_side_slat_infrared_hemispherical_emissivity": 0.9,
    "back_side_slat_infrared_hemispherical_emissivity": 0.9,
    "blind_to_glass_distance": 0.05,
    "blind_top_opening_multiplier": 0.5,
    "blind_bottom_opening_multiplier": 0.5,
    "blind_left_side_opening_multiplier": 0.5,
    "blind_right_side_opening_multiplier": 0.5,
}

#: Surface film resistances [m²K/W] for the steady-state U-values SAEngine reports and the
#: fallback uses (EnergyPlus computes its own convection): ISO 6946 inside 0.13 (horizontal heat
#: flow), 0.17 (downward, a roof in summer), outside 0.04. From memory, to be checked.
R_INSIDE_WALL = 0.13
R_INSIDE_ROOF = 0.17
R_OUTSIDE = 0.04


def u_value(construction: Opaque, roof: bool = False) -> float:
    """Steady-state air-to-air U-value [W/m²K] with the ISO 6946 film resistances."""
    inside = R_INSIDE_ROOF if roof else R_INSIDE_WALL
    return 1.0 / (inside + construction.resistance() + R_OUTSIDE)


def with_u(construction: Opaque, u: float, roof: bool = False) -> Opaque:
    """The construction with its main layer's conductivity changed so that its U-value (films
    included) is ``u``: its mass stays, its resistance is the entered one."""
    inside = R_INSIDE_ROOF if roof else R_INSIDE_WALL
    target = 1.0 / u - inside - R_OUTSIDE
    others = sum(x.resistance for i, x in enumerate(construction.layers) if i != construction.main)
    main = construction.layers[construction.main]
    r_main = max(target - others, 1e-3)
    layers = list(construction.layers)
    layers[construction.main] = Layer(
        f"{main.name} (U {u:g})", main.thickness, main.thickness / r_main, main.density,
        main.specific_heat, f"{main.source}; conductivity set for the entered U = {u:g} W/m²K",
        main.roughness,
    )  # fmt: skip
    return Opaque(
        f"{construction.key}-u{u:g}", f"{construction.label}, U = {u:g} W/m²K", tuple(layers),
        construction.main,
    )  # fmt: skip


@dataclass
class EnvelopeChoice:
    """The constructions of a building's envelope after its overrides."""

    wall: Opaque
    roof: Opaque
    glazing: Glazing
    uGlazing: float
    shgc: float
    simpleGlazing: bool  # an entered U or SHGC: EnergyPlus's simple glazing model
    shading: str
    notes: list[str] = field(default_factory=list)

    @property
    def uWall(self) -> float:
        return u_value(self.wall)

    @property
    def uRoof(self) -> float:
        return u_value(self.roof, roof=True)


def envelope(entry: Any) -> EnvelopeChoice:
    """The envelope of the 07 MEP ``hvac.envelope`` entry (None: the defaults)."""
    wall = WALLS[getattr(entry, "wall", None) or "brick250"]
    roof = ROOFS[getattr(entry, "roof", None) or "rcLimeTerracing"]
    glazing = GLAZINGS[getattr(entry, "glazing", None) or "singleClear"]
    notes = []
    if entry is not None and entry.uWall:
        wall = with_u(wall, entry.uWall)
        notes.append(f"wall U-value {entry.uWall:g} W/m²K entered")
    if entry is not None and entry.uRoof:
        roof = with_u(roof, entry.uRoof, roof=True)
        notes.append(f"roof U-value {entry.uRoof:g} W/m²K entered")
    u_glazing = (entry.uGlazing if entry is not None and entry.uGlazing else None) or glazing.u
    shgc = (entry.shgc if entry is not None and entry.shgc else None) or glazing.shgc
    simple = bool(entry is not None and (entry.uGlazing or entry.shgc))
    if simple:
        notes.append(
            f"glazing U {u_glazing:g} W/m²K, SHGC {shgc:g} (EnergyPlus simple glazing model)"
        )
    shading = (getattr(entry, "shading", None) or "none") if entry is not None else "none"
    return EnvelopeChoice(wall, roof, glazing, u_glazing, shgc, simple, shading, notes)


def epjson_objects(choice: EnvelopeChoice) -> dict[str, dict[str, Any]]:
    """The Material, WindowMaterial and Construction objects of the envelope (epJSON)."""
    materials: dict[str, Any] = {}
    constructions: dict[str, Any] = {}
    for name, construction in (("Wall", choice.wall), ("Roof", choice.roof), ("Floor", FLOOR)):
        layer_names = []
        for layer in construction.layers:
            materials[layer.name] = {
                "roughness": layer.roughness,
                "thickness": layer.thickness,
                "conductivity": layer.conductivity,
                "density": layer.density,
                "specific_heat": layer.specific_heat,
            }
            layer_names.append(layer.name)
        constructions[name] = _layers(layer_names)
    objects: dict[str, dict[str, Any]] = {"Material": materials, "Construction": constructions}
    if choice.simpleGlazing:
        objects["WindowMaterial:SimpleGlazingSystem"] = {
            "Glazing": {"u_factor": choice.uGlazing, "solar_heat_gain_coefficient": choice.shgc}
        }
        constructions["Window"] = {"outside_layer": "Glazing"}
    else:
        objects["WindowMaterial:Glazing"] = {"CLEAR 6MM": dict(CLEAR_6MM)}
        if any(kind == "gas" for kind, _ in choice.glazing.layers):
            objects["WindowMaterial:Gas"] = {"AIR 13MM": dict(AIR_13MM)}
        constructions["Window"] = _layers([name for _, name in choice.glazing.layers])
    if choice.shading == "blinds":
        objects["WindowMaterial:Blind"] = {"Interior blind": dict(BLIND)}
        glass = ["Glazing"] if choice.simpleGlazing else [n for _, n in choice.glazing.layers]
        constructions["Window with blind"] = _layers([*glass, "Interior blind"])
    return objects


def _layers(names: list[str]) -> dict[str, str]:
    keys = ["outside_layer"] + [f"layer_{i}" for i in range(2, 11)]
    return dict(zip(keys, names, strict=False))

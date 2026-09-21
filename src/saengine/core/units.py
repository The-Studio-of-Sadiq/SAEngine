"""
Unit system management for SAEngine.

Supports multiple unit systems with live conversion. All internal calculations
use a consistent base unit system (SI: N, m, kg, s) and convert for display.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, Tuple


class UnitSystem(enum.Enum):
    """Available unit systems."""
    SI = "SI (kN, m, kg)"
    SI_MM = "SI (N, mm, kg)"
    US = "US (kip, in, slug)"
    US_FT = "US (kip, ft, slug)"
    MKS = "MKS (kgf, m, kg)"
    CGS = "CGS (kgf, cm, kg)"

    @property
    def display_name(self) -> str:
        return self.value



class UnitCategory(enum.Enum):
    """Physical quantity categories."""
    LENGTH = "length"
    FORCE = "force"
    STRESS = "stress"
    MOMENT = "moment"
    AREA = "area"
    INERTIA = "inertia"
    MASS = "mass"
    DENSITY = "density"
    LINEAR_FORCE = "linear_force"
    AREA_FORCE = "area_force"
    ANGLE = "angle"
    TEMPERATURE = "temperature"
    TIME = "time"


# -----------------------------------------------------------------
# Conversion factors TO base SI (kN, m, kg, s)
# Multiply a value in the source unit by the factor to get base SI.
# -----------------------------------------------------------------

_LENGTH_TO_M: Dict[str, float] = {
    "m": 1.0,
    "mm": 1e-3,
    "cm": 1e-2,
    "in": 0.0254,
    "ft": 0.3048,
}

_FORCE_TO_KN: Dict[str, float] = {
    "kN": 1.0,
    "N": 1e-3,
    "kgf": 9.80665e-3,
    "lbf": 4.44822e-3,
    "kip": 4.44822,
    "MN": 1e3,
}

_MASS_TO_KG: Dict[str, float] = {
    "kg": 1.0,
    "g": 1e-3,
    "tonne": 1e3,
    "lb": 0.453592,
    "slug": 14.5939,
    "kip·s²/in": 175.127,
}


@dataclass
class UnitManager:
    """
    Manages the active unit system and provides conversion utilities.

    All internal storage uses base SI (kN, m, kg, s). The UnitManager converts
    values for display and accepts user input in the active unit system.
    """

    active_system: UnitSystem = UnitSystem.SI

    # Maps UnitSystem → (length_unit, force_unit, mass_unit)
    _system_units: Dict[UnitSystem, Tuple[str, str, str]] = field(default_factory=lambda: {
        UnitSystem.SI: ("m", "kN", "kg"),
        UnitSystem.SI_MM: ("mm", "N", "kg"),
        UnitSystem.US: ("in", "kip", "slug"),
        UnitSystem.US_FT: ("ft", "kip", "slug"),
        UnitSystem.MKS: ("m", "kgf", "kg"),
        UnitSystem.CGS: ("cm", "kgf", "kg"),
    })

    @property
    def length_unit(self) -> str:
        return self._system_units[self.active_system][0]

    @property
    def force_unit(self) -> str:
        return self._system_units[self.active_system][1]

    @property
    def mass_unit(self) -> str:
        return self._system_units[self.active_system][2]

    @property
    def stress_unit(self) -> str:
        """Derived: force / length²."""
        f = self.force_unit
        l = self.length_unit
        return f"{f}/{l}²"

    @property
    def moment_unit(self) -> str:
        """Derived: force × length."""
        return f"{self.force_unit}·{self.length_unit}"

    # ---- Conversion methods ----

    def length_to_base(self, value: float) -> float:
        """Convert from display length unit → internal (m)."""
        return value * _LENGTH_TO_M[self.length_unit]

    def length_from_base(self, value_m: float) -> float:
        """Convert from internal (m) → display length unit."""
        return value_m / _LENGTH_TO_M[self.length_unit]

    def force_to_base(self, value: float) -> float:
        """Convert from display force unit → internal (kN)."""
        return value * _FORCE_TO_KN[self.force_unit]

    def force_from_base(self, value_kn: float) -> float:
        """Convert from internal (kN) → display force unit."""
        return value_kn / _FORCE_TO_KN[self.force_unit]

    def stress_to_base(self, value: float) -> float:
        """Convert from display stress → internal (kN/m²)."""
        f_factor = _FORCE_TO_KN[self.force_unit]
        l_factor = _LENGTH_TO_M[self.length_unit]
        return value * f_factor / (l_factor ** 2)

    def stress_from_base(self, value_kpa: float) -> float:
        """Convert from internal (kN/m² = kPa) → display stress."""
        f_factor = _FORCE_TO_KN[self.force_unit]
        l_factor = _LENGTH_TO_M[self.length_unit]
        return value_kpa / f_factor * (l_factor ** 2)

    def moment_to_base(self, value: float) -> float:
        """Convert from display moment → internal (kN·m)."""
        f_factor = _FORCE_TO_KN[self.force_unit]
        l_factor = _LENGTH_TO_M[self.length_unit]
        return value * f_factor * l_factor

    def moment_from_base(self, value_knm: float) -> float:
        """Convert from internal (kN·m) → display moment."""
        f_factor = _FORCE_TO_KN[self.force_unit]
        l_factor = _LENGTH_TO_M[self.length_unit]
        return value_knm / (f_factor * l_factor)

    def set_system(self, system: UnitSystem) -> None:
        """Change the active unit system."""
        self.active_system = system

    def format_length(self, value_m: float, decimals: int = 3) -> str:
        """Format an internal length value for display."""
        display_val = self.length_from_base(value_m)
        return f"{display_val:.{decimals}f} {self.length_unit}"

    def format_force(self, value_kn: float, decimals: int = 2) -> str:
        """Format an internal force value for display."""
        display_val = self.force_from_base(value_kn)
        return f"{display_val:.{decimals}f} {self.force_unit}"

    def to_dict(self) -> dict:
        """Serialize for project save."""
        return {"active_system": self.active_system.value}

    @classmethod
    def from_dict(cls, data: dict) -> UnitManager:
        """Deserialize from project data."""
        system_value = data.get("active_system", UnitSystem.SI.value)
        for sys in UnitSystem:
            if sys.value == system_value:
                return cls(active_system=sys)
        return cls()

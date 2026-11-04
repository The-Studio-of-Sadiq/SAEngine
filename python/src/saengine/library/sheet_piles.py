"""Steel sheet pile sections per metre run of wall (alpha 9 P1).

A nominal set SAEngine designs with: the U sections are the JIS A 5523 / JIS A 5528 hot-rolled
types by their dimensions (width × height × web thickness), the Z sections generic nominal
sizes. They are product data, not code values: every value is nominal and is listed in the
default pack's VERIFY.md; check the section a supplier offers (its own W, I and mass) and
enter it as the wall's moment capacity where it differs.

Per metre of wall: W the elastic section modulus [cm³/m], I the second moment of area
[cm⁴/m], the mass [kg/m²]. Names are shapes and sizes, never makers' names.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SheetPile:
    name: str
    shape: str  # "U" | "Z"
    width: float  # mm, of one pile
    height: float  # mm, of the wall
    W: float  # cm³/m
    I: float  # cm⁴/m
    mass: float  # kg/m²
    nominal: bool = True  # VERIFY with the supplier

    @property
    def modulus(self) -> float:
        """W [mm³/m]."""
        return self.W * 1e3

    @property
    def inertia(self) -> float:
        """I [mm⁴/m]."""
        return self.I * 1e4


SECTIONS: tuple[SheetPile, ...] = (
    # U sections: JIS A 5523 / A 5528 types II-IV and IIw-IVw (nominal values).
    SheetPile("U 400×100×10.5", "U", 400, 100, 874, 8740, 120),
    SheetPile("U 400×125×13.0", "U", 400, 125, 1340, 16800, 150),
    SheetPile("U 400×170×15.5", "U", 400, 170, 2270, 38600, 190),
    SheetPile("U 600×130×10.3", "U", 600, 130, 1000, 13000, 102),
    SheetPile("U 600×180×13.4", "U", 600, 180, 1800, 32400, 136),
    SheetPile("U 600×210×18.0", "U", 600, 210, 2700, 56700, 176),
    # Z sections: generic nominal sizes (I ≈ W h / 2).
    SheetPile("Z 700×300×9.5", "Z", 700, 300, 1100, 16500, 100),
    SheetPile("Z 700×400×10.0", "Z", 700, 400, 1600, 32000, 110),
    SheetPile("Z 700×450×12.0", "Z", 700, 450, 2400, 54000, 135),
    SheetPile("Z 630×450×14.0", "Z", 630, 450, 3000, 67500, 165),
)


def find(name: str | None) -> SheetPile | None:
    """The section named ``name`` (case and spaces ignored, 'x' for '×'), or None."""
    if not name:
        return None
    key = name.replace(" ", "").replace("x", "×").replace("X", "×").lower()
    for section in SECTIONS:
        if section.name.replace(" ", "").lower() == key:
            return section
    return None


def names() -> list[str]:
    return [s.name for s in SECTIONS]

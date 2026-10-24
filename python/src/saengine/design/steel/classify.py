"""Local buckling classification of steel shapes: BNBC 2020 Part 6 Sec 10.2.4 and Table 6.10.1
(pp 3825-3829, the limits of AISC 360-05 Table B4.1).

Each compression element of a shape gets its width-thickness ratio λ and the limits λp
(compact) and λr (noncompact) of the table case that applies, separately for uniform
compression (columns, braces) and for flexure. Widths per Sec 10.2.4.1 and 10.2.4.2: half the
flange of I-shapes and tees, the full flange of channels and full legs of angles; the clear web
height less the fillets of rolled shapes; the flat widths of HSS walls (less the inside corner
radius each side, or 3 t when it is not known). Rolled shapes are assumed (not built-up): the
built-up cases 2 and 4 with kc are not used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from saengine.design.steel.properties import ShapeProperties

COMPACT = "compact"
NONCOMPACT = "noncompact"
SLENDER = "slender"
TABLE = "BNBC 2020 Part 6 Table 6.10.1"


@dataclass(frozen=True)
class Element:
    """One plate element of a shape and its slenderness class."""

    name: str  # "flange", "web", "leg", "stem", "wall"
    ratio: float  # λ
    lambda_p: float | None  # None: no compact limit (uniform compression)
    lambda_r: float
    case: int  # Table 6.10.1 case

    @property
    def cls(self) -> str:
        if self.lambda_p is not None and self.ratio <= self.lambda_p:
            return COMPACT
        if self.ratio <= self.lambda_r:
            return NONCOMPACT if self.lambda_p is not None else COMPACT
        return SLENDER

    @property
    def slender(self) -> bool:
        return self.ratio > self.lambda_r

    def describe(self) -> str:
        limits = (
            f"λp = {self.lambda_p:.1f}, λr = {self.lambda_r:.1f}"
            if self.lambda_p is not None
            else f"λr = {self.lambda_r:.1f}"
        )
        return f"{self.name} λ = {self.ratio:.1f} ({limits}, case {self.case}): {self.cls}"


def _root(e: float, fy: float) -> float:
    return math.sqrt(e / fy)


def compression_elements(shape: ShapeProperties, fy: float, e: float) -> list[Element]:
    """The elements of ``shape`` under uniform compression (Sec 10.2.4 for Sec 10.5)."""
    r = _root(e, fy)
    d = shape.dims
    match shape.family:
        case "I":
            return [
                Element("flange", d["bf"] / 2 / d["tf"], None, 0.56 * r, 3),
                Element("web", d["h"] / d["tw"], None, 1.49 * r, 10),
            ]
        case "channel":
            return [
                Element("flange", d["bf"] / d["tf"], None, 0.56 * r, 3),
                Element("web", d["h"] / d["tw"], None, 1.49 * r, 14),
            ]
        case "tee":
            return [
                Element("flange", d["bf"] / 2 / d["tf"], None, 0.56 * r, 3),
                Element("stem", d["d"] / d["tw"], None, 0.75 * r, 8),
            ]
        case "angle":
            return [Element("leg", max(d["d"], d["b"]) / d["t"], None, 0.45 * r, 5)]
        case "rhs":
            return [
                Element("wall (width)", d["b"] / d["t"], None, 1.40 * r, 12),
                Element("wall (depth)", d["h"] / d["t"], None, 1.40 * r, 12),
            ]
        case "chs":
            return [Element("wall", d["D"] / d["t"], None, 0.11 * e / fy, 15)]
    raise ValueError(f"unknown shape family {shape.family}")


def flexure_elements(shape: ShapeProperties, fy: float, e: float, axis: str) -> list[Element]:
    """The elements of ``shape`` bent about ``axis`` ("x": the horizontal axis, the major one of
    I-shapes and channels; "y": the vertical one) (Sec 10.2.4 for Sec 10.6)."""
    r = _root(e, fy)
    d = shape.dims
    match shape.family:
        case "I" | "channel":
            b = d["bf"] / 2 if shape.family == "I" else d["bf"]
            flange = Element("flange", b / d["tf"], 0.38 * r, 1.0 * r, 1)
            if axis == "y":
                return [flange]
            return [flange, Element("web", d["h"] / d["tw"], 3.76 * r, 5.70 * r, 9)]
        case "tee":
            return [Element("flange", d["bf"] / 2 / d["tf"], 0.38 * r, 1.0 * r, 7)]
        case "angle":
            return [Element("leg", max(d["d"], d["b"]) / d["t"], 0.54 * r, 0.91 * r, 6)]
        case "rhs":
            # The flanges are the walls parallel to the axis of bending.
            flange_b, web_h = (d["b"], d["h"]) if axis == "x" else (d["h"], d["b"])
            return [
                Element("flange", flange_b / d["t"], 1.12 * r, 1.40 * r, 12),
                Element("web", web_h / d["t"], 2.42 * r, 5.70 * r, 13),
            ]
        case "chs":
            return [Element("wall", d["D"] / d["t"], 0.07 * e / fy, 0.31 * e / fy, 15)]
    raise ValueError(f"unknown shape family {shape.family}")


def section_class(elements: list[Element]) -> str:
    """The class of the section: its worst element (Sec 10.2.4)."""
    order = [COMPACT, NONCOMPACT, SLENDER]
    return max((e.cls for e in elements), key=order.index, default=COMPACT)


def by_name(elements: list[Element], name: str) -> Element | None:
    return next((e for e in elements if e.name == name), None)

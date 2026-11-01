"""Corbels and brackets (default pack BNBC 2020 Part 6 Sec 6.4.7, which follows ACI 318-11 Sec 11.8).

A corbel is given on a beam's end in the building model (:class:`saengine.library.modifiers.
Corbel`); the beam's end shear from the analysis is its Vu. The section at the column face is
designed for Vu, the moment Mu = Vu av + Nuc (h - d) and the horizontal tension Nuc, all with
φ = 0.75 (Sec 6.4.7.3.1):

- av / d at most 1 and Nuc at most Vu (6.4.7.1); the depth at the outer edge at least 0.5 d
  (6.4.7.2);
- Vn = Avf fy μ by shear friction (Sec 6.4.5, μ = 1.4 λ for concrete cast monolithically), at
  most min(0.2 f'c, 3.3 + 0.08 f'c, 11) bw d (6.4.7.3.2);
- Af for Mu (the rectangular stress block), An = Nuc / (φ fy), Nuc at least 0.2 Vu
  (6.4.7.3.3-4);
- the main bars As at least Af + An, (2/3) Avf + An (6.4.7.3.5) and 0.04 (f'c / fy) bw d
  (6.4.7.5);
- closed ties Ah at least 0.5 (As - An), placed within (2/3) d next to As (6.4.7.4);
- the bearing Vu at most φ 0.85 f'c A1 with φ = 0.65 (Sec 6.2.3.2, 6.3.13) when a bearing is
  given.

The limits are the pack's ``transfer.corbel``. Units: mm, N, MPa inside; reported in kN, mm².
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.clauses import clause
from saengine.design.rc import bar_area

__all__ = [
    "CLAUSE",  # noqa: F822 - module __getattr__ (read from the code pack)
    "CorbelDemand",
    "corbel_checks",
    "member_checks",
]


def _clause() -> str:
    """The corbel clause of the code pack in force (``CLAUSE``; its subsections follow it)."""
    return clause("corbels", "corbels")


def __getattr__(name: str) -> str:
    if name == "CLAUSE":
        return _clause()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass
class CorbelDemand:
    """The factored shear Vu [N] on a corbel and its combination."""

    shear: float
    combination: str | None


def _phi(name: str, default: float) -> float:
    phi = code_context.table("factors").phi
    return float(phi.get(name) or default)


def corbel_checks(
    corbel: Any, fc: float, fy: float, demand: CorbelDemand, label: str = "Corbel", lam: float = 1.0
) -> list[dict[str, Any]]:
    """The checks of a corbel (:class:`saengine.library.modifiers.Corbel`) under ``demand``,
    in the design report's shape."""
    from saengine.design.check import _check

    table = code_context.pack_table("transfer").corbel
    phi = _phi("shear", 0.75)
    b, h = float(corbel.width), float(corbel.depth)
    main = corbel.mainBars
    d = h - float(corbel.cover) - main.dia / 2
    av = float(corbel.loadOffset or corbel.projection / 2)
    vu, combination = demand.shear, demand.combination
    given = corbel.horizontalForce
    nuc_least = table.tensionShare * vu
    nuc = max(float(given) * 1e3, nuc_least) if given is not None else nuc_least
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            f"{label}: shear span av / d",
            av / d,
            table.spanRatio,
            "",
            None,
            f"av = {av:.0f} mm, d = {d:.0f} mm; at most {table.spanRatio:g} ({_clause()}.1)",
        )
    )
    checks.append(
        _check(
            f"{label}: depth at the outer edge",
            table.edgeDepth * d,
            float(corbel.edgeDepth),
            "mm",
            None,
            f"at least {table.edgeDepth:g} d ({_clause()}.2)",
        )
    )
    if given is not None:
        checks.append(
            _check(
                f"{label}: horizontal force Nuc",
                nuc / 1e3,
                table.tensionMaxShare * vu / 1e3,
                "kN",
                combination,
                f"Nuc at most Vu ({_clause()}.1); at least {table.tensionShare:g} Vu ({_clause()}.3.4)",
            )
        )
    limit = (
        min(
            table.shearCoefficient * fc,
            table.shearIntercept + table.shearSlope * fc,
            table.shearStressMax,
        )
        * b
        * d
    )
    checks.append(
        _check(
            f"{label}: shear limit",
            vu / 1e3,
            phi * limit / 1e3,
            "kN",
            combination,
            f"φ Vn,max = φ min({table.shearCoefficient:g} f'c, {table.shearIntercept:g} + "
            f"{table.shearSlope:g} f'c, {table.shearStressMax:g}) bw d, φ = {phi:g} "
            f"({_clause()}.3.1, .3.2)",
        )
    )
    mu = vu * av + nuc * (h - d)
    mu_n = mu / phi
    # Af fy (d - Af fy / (1.7 f'c b)) = Mu / φ, the smaller root.
    k = fy / (1.7 * fc * b)
    disc = d * d - 4 * k * mu_n / fy
    af = (d - math.sqrt(disc)) / (2 * k) if disc >= 0 else math.inf
    avf = vu / (phi * fy * table.friction * lam)
    an = nuc / (phi * fy)
    least = table.minSteel * fc / fy * b * d
    required = max(af + an, 2 / 3 * avf + an, least)
    provided = main.count * bar_area(main.dia)
    checks.append(
        _check(
            f"{label}: main bars As",
            required,
            provided,
            "mm²",
            combination,
            f"As at least Af + An = {af + an:.0f}, (2/3) Avf + An = {2 / 3 * avf + an:.0f}, "
            f"{table.minSteel:g} (f'c/fy) bw d = {least:.0f} mm²; Mu = Vu av + Nuc (h - d) = "
            f"{mu / 1e6:.1f} kN·m, Avf = Vu / (φ fy μ), μ = {table.friction:g} λ, Nuc = "
            f"{nuc / 1e3:.1f} kN ({_clause()}.3.3-.3.5, .5; Sec 6.4.5); {main.count} Ø{main.dia:g}",
        )
    )
    ties = corbel.ties
    ah = ties.count * 2 * bar_area(ties.dia) if ties else 0.0
    checks.append(
        _check(
            f"{label}: closed ties Ah",
            table.tiesShare * max(provided - an, 0.0),
            ah,
            "mm²",
            combination,
            f"Ah at least {table.tiesShare:g} (As - An), within {table.tiesDepth:.2f} d = "
            f"{table.tiesDepth * d:.0f} mm below As ({_clause()}.4)"
            + (f"; {ties.count} closed Ø{ties.dia:g}" if ties else "; no ties given"),
        )
    )
    if corbel.bearing:
        phi_b = _phi("bearing", 0.65)
        area = float(corbel.bearing) * b
        checks.append(
            _check(
                f"{label}: bearing",
                vu / 1e3,
                phi_b * 0.85 * fc * area / 1e3,
                "kN",
                combination,
                f"φ 0.85 f'c A1, φ = {phi_b:g}, A1 = {corbel.bearing:g} × {b:.0f} mm "
                f"({clause('corbels', 'bearing')})",
            )
        )
    return checks


def member_checks(
    element: Any,
    pieces: list[Any],
    combinations: list[str],
    turned: bool,
    fc: float,
    fy: float,
) -> list[dict[str, Any]]:
    """The checks of the corbels under a beam of the building model (``element.corbels``),
    each with the beam's largest end shear there."""
    corbels = getattr(element, "corbels", None)
    if corbels is None or (corbels.start is None and corbels.end is None) or not pieces:
        return []
    from saengine.design.deep_beams import _stations

    a = np.array(element.start, dtype=float)
    c = np.array(element.end, dtype=float)
    length = float(np.linalg.norm(c - a))
    if length <= 0:
        return []
    rows = _stations(pieces, combinations, turned, a, (c - a) / length)
    if not rows:
        return []
    checks: list[dict[str, Any]] = []
    for corbel, at, label in (
        (corbels.start, 0.0, "Corbel at the start"),
        (corbels.end, length, "Corbel at the end"),
    ):
        if corbel is None:
            continue
        nearest = min(rows, key=lambda r: abs(r[0] - at))
        shear = np.abs(nearest[1])
        k = int(np.argmax(shear))
        demand = CorbelDemand(float(shear[k]), combinations[k] if combinations else None)
        checks += corbel_checks(corbel, fc, fy, demand, label)
    return checks

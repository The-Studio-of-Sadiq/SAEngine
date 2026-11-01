"""Composite concrete flexural members: precast and cast-in-place concrete (or two cast-in-place
placements) built separately and tied to act as one (the code pack's ``compositeConcrete``;
the default pack's BNBC 2020 Part 6 Sec 6.12) (B33).

Not to be confused with steel-concrete composite members (steel beams with a slab, encased
and filled columns), which :mod:`saengine.design.steel.composite` designs.

The vertical shear is designed as for a monolithic member of the same shape (the beam's own
shear check). This module checks the horizontal shear at the contact surface, Vu <= φ Vnh with
d of the whole composite section:

- contact surface clean and intentionally roughened, no ties: Vnh <= ``roughenedLimit`` bv d;
- minimum ties, not intentionally roughened: Vnh <= ``tiedSmoothLimit`` bv d;
- ties and a surface roughened to about ``roughness`` mm: Vnh = (``base`` + ``steelShare`` ρv
  fy) λ bv d <= ``cap`` bv d, ρv = Av / (bv s);
- Vu above φ ``cap`` bv d: shear friction by the general clause (the row fails and says so);
- with tension across the contact surface, shear by contact only with the minimum ties.

The ties: Av >= max(``sqrtShare`` √f'c, ``floor``) bv s / fyt and spacing at most
``tieSpacingFactor`` × the least dimension of the supported element and ``tieSpacingMax``.

Units: mm, N, MPa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context


def rules() -> Any:
    """The pack's ``compositeConcrete`` table, None when the pack does not cover it."""
    pack = code_context.current()
    return pack.table("compositeConcrete") if pack.has("compositeConcrete") else None


def clause(key: str) -> str:
    table = rules()
    text = (getattr(table, "clauses", None) or {}).get(key) if table is not None else None
    if not text:
        return ""
    pack = code_context.current()
    return f"{pack.edition or pack.name} {text}"


@dataclass(frozen=True)
class HorizontalShear:
    """Vnh [N], which limit gave it, whether the ties meet the minimum (area and spacing) and
    the least tie area [mm²] and largest spacing [mm]."""

    vnh: float
    case: str
    ties_ok: bool
    av_min: float
    s_max: float
    friction: bool  # Vu above φ cap bv d: design by shear friction


def horizontal_shear(
    vu: float,
    bv: float,
    d: float,
    fc: float,
    fyt: float,
    av: float,
    s: float | None,
    roughened: bool,
    supported: float,
    phi: float,
    lam: float = 1.0,
    tension: bool = False,
) -> HorizontalShear:
    """Vnh of a contact surface ``bv`` wide (the pack's rules, see the module notes): ``av``
    the area of the ties crossing it [mm²] at ``s`` [mm] (0 / None: no ties), ``supported``
    the least dimension of the supported (cast-in-place) element [mm]."""
    table = rules()
    if table is None:
        raise ValueError(
            f"composite concrete members: not covered by the code pack "
            f"{code_context.current().name}"
        )
    root = math.sqrt(fc)
    s_max = min(float(table.tieSpacingFactor) * supported, float(table.tieSpacingMax))
    av_min = (
        max(float(table.minTies["sqrtShare"]) * root, float(table.minTies["floor"]))
        * bv
        * (s or s_max)
        / fyt
    )
    ties = bool(av > 0 and s)
    ties_ok = ties and av >= av_min - 1e-9 and (s or math.inf) <= s_max + 1e-9
    cap = float(table.roughenedTied.cap) * bv * d
    friction = vu > phi * cap
    if roughened and ties_ok:
        rho = av / (bv * s)  # type: ignore[operator]
        rule = table.roughenedTied
        vnh = min((float(rule.base) + float(rule.steelShare) * rho * fyt) * lam * bv * d, cap)
        case = f"roughened with ties: ({rule.base:g} + {rule.steelShare:g} ρv fy) λ bv d"
    elif roughened and not tension:
        vnh = float(table.roughenedLimit) * bv * d
        case = f"roughened, no minimum ties: {table.roughenedLimit:g} bv d"
    elif ties_ok:
        vnh = float(table.tiedSmoothLimit) * bv * d
        case = f"minimum ties, not roughened: {table.tiedSmoothLimit:g} bv d"
    else:
        vnh = 0.0
        case = (
            "tension across the contact surface without the minimum ties"
            if tension
            else "neither roughened nor tied: no horizontal shear by contact"
        )
    return HorizontalShear(vnh, case, ties_ok, av_min, s_max, friction)


def beam_checks(
    vu: float,
    combination: str | None,
    topping: Any,
    width: float,
    d: float,
    fc: float,
    fyt: float,
    stirrup_dia: float | None,
    legs: int,
    spacing: float | None,
    phi: float,
    lam: float = 1.0,
) -> list[dict[str, Any]]:
    """The rows of a composite concrete beam (``topping``: the beam type's
    ``CompositeTopping``): horizontal shear at the contact surface and its ties."""
    from saengine.design.check import _check

    if topping is None:
        return []
    bv = float(topping.contactWidth or width)
    av = legs * math.pi * stirrup_dia**2 / 4 if (stirrup_dia and topping.ties) else 0.0
    found = horizontal_shear(
        vu,
        bv,
        d,
        fc,
        fyt,
        av,
        spacing if topping.ties else None,
        topping.surface == "roughened",
        float(topping.toppingThickness),
        phi,
        lam,
        bool(topping.tension),
    )
    note = f"{found.case}; bv = {bv:.0f} mm, d = {d:.0f} mm of the composite section"
    if found.friction:
        note += f"; Vu above φ cap bv d: design by shear friction ({clause('shearFriction')})"
    rows = [
        _check(
            f"Horizontal shear, composite member ({clause('horizontal')})",
            vu / 1e3,
            0.0 if found.friction else phi * found.vnh / 1e3,
            "kN",
            combination,
            note,
        )
    ]
    if topping.ties:
        rows.append(
            _check(
                f"Ties for horizontal shear ({clause('ties')})",
                found.av_min,
                av,
                "mm²",
                None,
                f"Av,min at s = {spacing or found.s_max:.0f} mm; s at most {found.s_max:.0f} mm"
                f" (the stirrups extended into the cast-in-place part, anchored "
                f"{clause('anchorage')})",
                utilisation=max(
                    found.av_min / av if av > 0 else math.inf,
                    (spacing or math.inf) / found.s_max,
                ),
            )
        )
    return rows

"""Masonry walls: the masonry of a wall and the design method the code pack chooses.

A structural wall whose 04 Objects type has a masonry material (03 Materials, category
"masonry") is designed as masonry instead of reinforced concrete (:mod:`saengine.design.
wall_design` routes it). A type with vertical and horizontal bars (``reinforcement``) is
reinforced masonry, one without is plain (unreinforced) masonry.

This module holds what every method shares: the masonry of a material (f'm, the unit, the
mortar grade, the grouting, the bond, whether the full allowable stresses may be used), the
mortar grade of a cement : sand mix, the estimate of f'm from the units where the code pack
keeps one, and the dispatch to the method the code pack names in ``masonry.method``:

- ``"allowableStress"``: :mod:`saengine.design.masonry_asd` (working stress design with a linear
  stress-strain distribution, under the code pack's allowable stress combinations).

Every number, limit and clause comes from the code pack's ``masonry`` table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from saengine.codes import context as code_context
from saengine.design.rc import DesignError


def table() -> Any:
    """The code pack's masonry table."""
    return code_context.pack_table("masonry")


def clause(key: str) -> str:
    """The code pack's clause reference of check ``key`` (the chapter when it names none)."""
    clauses = table().clauses
    return str(clauses.get(key) or clauses.get("chapter") or "")


# ─────────────────────────────────────── the masonry ───────────────────────────────────────


@dataclass(frozen=True)
class Masonry:
    """The masonry of a wall: f'm [MPa] and what its checks depend on."""

    fm: float
    kind: str = "clay"  # "clay" or "concrete"
    mortar: str | None = None  # a mortar grade of the code pack; None: not known
    units: str = "solid"  # "solid" or "hollow"
    grouting: str = "none"  # "none", "partial" or "full"
    bond: str = "running"  # "running" or "stack"
    fm_source: str = "entered"  # "entered" (prism tests) or "estimate" (from the units)
    inspected: bool = False  # special inspection and prism tests during construction
    notes: tuple[str, ...] = field(default=(), compare=False)

    @property
    def em(self) -> float:
        """Em = ratio · f'm, at most the cap [MPa] (code pack ``elastic``)."""
        e = table().elastic
        return min(float(e.emRatio) * self.fm, float(e.emCap))

    @property
    def g(self) -> float:
        """Shear modulus G = ratio · Em [MPa]."""
        return float(table().elastic.shearRatio) * self.em

    @property
    def grouted(self) -> bool:
        return self.grouting == "full"

    @property
    def full_stresses(self) -> bool:
        """The full allowable stresses may be used: special inspection with prism tests during
        construction, and f'm from prism tests (not estimated)."""
        return self.inspected and self.fm_source == "entered"


def allowable_share(m: Masonry) -> float:
    """The share of the allowable masonry stresses: 1, or the code pack's reduced share
    without special inspection and prism tests (``quality.reducedShare``)."""
    return 1.0 if m.full_stresses else float(table().quality.reducedShare)


def mortar_grades() -> list[str]:
    """The code pack's mortar grades, richest first (by sand parts per cement part)."""
    mortars = table().mortars
    return sorted(mortars, key=lambda g: float(mortars[g].sand) / float(mortars[g].cement))


def mortar_grade_of_mix(sand_parts: float, cement_parts: float = 1.0) -> str | None:
    """The mortar grade of a cement : sand mix: the richest grade whose sand parts per cement
    part are at least the mix's (``mortarFromMix: "grades"``); None for a mix leaner than every
    grade."""
    mortars = table().mortars
    ratio = sand_parts / cement_parts
    for grade in mortar_grades():
        if float(mortars[grade].sand) / float(mortars[grade].cement) >= ratio - 1e-9:
            return grade
    return None


def mortar_rank(grade: str | None) -> int:
    """Position of ``grade`` from the richest (0); a large number when unknown."""
    grades = mortar_grades()
    return grades.index(grade) if grade in grades else len(grades) + 1


def prism_estimate(
    unit_strength: float, kind: str = "clay", grade: str | None = None
) -> float | None:
    """f'm [MPa] estimated from the units' strength [MPa] by the code pack's ``prismEstimate``
    (linear between its rows, its top f'm above them); None where the pack has no estimate, the
    mortar grade is not one it may be used with, or the units are below its first row."""
    estimate = table().prismEstimate
    if estimate is None or (grade is not None and grade not in estimate.grades):
        return None
    rows = getattr(estimate, kind)
    units, fms = rows.units, rows.fm
    if unit_strength < units[0]:
        return None
    if unit_strength >= units[-1]:
        return float(fms[-1])
    for k in range(1, len(units)):
        if unit_strength <= units[k]:
            share = (unit_strength - units[k - 1]) / (units[k] - units[k - 1])
            return float(fms[k - 1] + share * (fms[k] - fms[k - 1]))
    return float(fms[-1])  # pragma: no cover - the loop returns


def masonry_of(material: Any, mats: dict[str, Any] | None = None) -> Masonry:
    """The :class:`Masonry` of a masonry material (``library.materials.Material``); its mortar
    material (``mats``) gives the mortar grade when the material names none of the code pack's.
    Raises :class:`DesignError` when there is no f'm and none can be estimated."""
    props = getattr(material, "masonry", None)
    if props is None:
        raise DesignError(f"'{getattr(material, 'id', '?')}' is not a masonry material")
    notes: list[str] = []
    grade = props.mortarType
    if grade is not None and grade not in table().mortars:
        notes.append(
            f"mortar '{grade}' is not a grade of the code pack ({', '.join(mortar_grades())}): "
            "the grade is taken from the mortar's mix"
        )
        grade = None
    if grade is None:
        mix = getattr((mats or {}).get(props.mortar or ""), "composition", None)
        ratio = getattr(mix, "ratio", None)
        if ratio and len(ratio) == 2 and ratio[0] > 0:
            grade = mortar_grade_of_mix(ratio[1], ratio[0])
            if grade is None:
                notes.append(
                    f"the mortar mix 1:{ratio[1] / ratio[0]:g} is leaner than every grade of "
                    "the code pack: no flexural tension or plain shear is allowed"
                )
    kind = props.unitKind
    fm = props.fm
    source = "entered"
    if fm is None and props.unitStrength is not None:
        fm = prism_estimate(props.unitStrength, kind, grade)
        source = "estimate"
        if fm is None:
            raise DesignError(
                f"f'm cannot be estimated from the unit strength {props.unitStrength:g} MPa "
                f"with mortar {grade or 'of unknown grade'}: enter f'm from prism tests on the "
                "masonry material (03 Materials)"
            )
        estimate = table().prismEstimate
        notes.append(
            f"f'm = {fm:.1f} MPa estimated from the unit strength {props.unitStrength:g} MPa "
            f"({estimate.label if estimate else ''}); prism tests ({clause('prisms')}) give it"
        )
    if fm is None:
        raise DesignError(
            "no masonry strength: enter f'm (prism strength) or the unit strength on the "
            "masonry material (03 Materials)"
        )
    return Masonry(
        float(fm),
        kind,
        grade,
        props.units,
        props.grouting,
        props.bond,
        fm_source=source,
        inspected=bool(getattr(props, "specialInspection", False)),
        notes=tuple(notes),
    )


# ─────────────────────────────────────── the method ───────────────────────────────────────


@dataclass
class MasonryDesign:
    checks: list[dict[str, Any]]
    notes: list[str]
    utilisation: float


def method_module() -> ModuleType:
    """The module of the code pack's masonry method (``masonry.method``)."""
    method = table().method
    if method == "allowableStress":
        from saengine.design import masonry_asd

        return masonry_asd
    raise DesignError(f"the code pack's masonry method '{method}' is not available")


def method_text() -> list[str]:
    """The report's method paragraphs of the code pack's masonry method."""
    return list(method_module().method_text())


def combinations_kind() -> str:
    """Which combinations the method checks: "allowable" (the code pack's allowable stress
    combinations) or "strength" (the design combinations)."""
    return str(method_module().COMBINATIONS)


def masonry_wall_checks(
    geometry: Any,
    bars: Any,
    forces: list[Any],
    m: Masonry,
    fy: float = 420.0,
    lateral: frozenset[str] | set[str] = frozenset(),
    storeys: int | None = None,
) -> MasonryDesign:
    """The checks of a masonry wall pier by the code pack's method: plain masonry without
    ``bars``, reinforced masonry with them. ``forces``: the pier's forces under the method's
    combinations (compression positive, N and N·mm); ``lateral``: the names of the combinations
    with wind or earthquake; ``storeys``: the building's storeys (minimum thickness)."""
    return method_module().wall_checks(geometry, bars, forces, m, fy, lateral, storeys)


def describe(m: Masonry, reinforced: bool) -> str:
    """'Reinforced clay masonry, f'm 8.0 MPa (estimate), Em 6000 MPa, mortar M2, 50 % of the
    allowable stresses' for the report."""
    share = allowable_share(m)
    estimate = " (estimate)" if m.fm_source == "estimate" else ""
    stresses = "full allowable stresses" if share >= 1 else f"{share:.0%} of the allowable stresses"
    return (
        f"{'Reinforced' if reinforced else 'Plain'} {m.kind} masonry, f'm {m.fm:.1f} MPa"
        f"{estimate}, Em {m.em:.0f} MPa, mortar {m.mortar or 'of unknown grade'}, {stresses}"
    )


__all__ = [
    "Masonry",
    "MasonryDesign",
    "allowable_share",
    "clause",
    "combinations_kind",
    "describe",
    "masonry_of",
    "masonry_wall_checks",
    "method_module",
    "method_text",
    "mortar_grade_of_mix",
    "mortar_grades",
    "mortar_rank",
    "prism_estimate",
    "table",
]

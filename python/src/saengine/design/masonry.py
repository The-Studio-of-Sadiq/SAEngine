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
  stress-strain distribution, under the code pack's allowable stress combinations);
- ``"strength"``: :mod:`saengine.design.masonry_strength` (strength design of reinforced slender
  walls and shear walls, under the design combinations).

A wall type may choose one of the pack's ``alternatives`` instead (``masonryMethod``). After the
method's checks every wall gets the pack's seismic detailing and high wind rules
(:mod:`saengine.design.masonry_seismic`); confined walls are checked by
:mod:`saengine.design.confined_masonry`, anchor bolts by :mod:`saengine.design.masonry_anchors`.

Every number, limit and clause comes from the code pack's ``masonry`` table.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    unit_strength: float | None = None  # the units' compressive strength [MPa], when entered

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
        unit_strength=props.unitStrength,
    )


# ─────────────────────────────────────── the method ───────────────────────────────────────


@dataclass
class MasonryDesign:
    checks: list[dict[str, Any]]
    notes: list[str]
    utilisation: float


def methods() -> list[str]:
    """The methods the code pack permits: its ``method`` first, then its ``alternatives``."""
    t = table()
    return list(dict.fromkeys([t.method, *getattr(t, "alternatives", [])]))


def method_id(chosen: str | None = None) -> str:
    """The method of a wall: ``chosen`` (a wall type's ``masonryMethod``) when the pack permits
    it, else the pack's ``method``."""
    if chosen and chosen in methods():
        return chosen
    return str(table().method)


def method_module(method: str | None = None) -> ModuleType:
    """The module of a masonry method (default: the code pack's ``masonry.method``)."""
    method = method or table().method
    if method == "allowableStress":
        from saengine.design import masonry_asd

        return masonry_asd
    if method == "strength":
        from saengine.design import masonry_strength

        return masonry_strength
    raise DesignError(f"the code pack's masonry method '{method}' is not available")


def method_text(used: list[str] | None = None) -> list[str]:
    """The report's method paragraphs of the code pack's masonry method (and of the other
    methods in ``used``)."""
    out: list[str] = []
    for method in dict.fromkeys([table().method, *(used or [])]):
        if method == "confinedPanels":
            from saengine.design import confined_masonry

            out += confined_masonry.method_text()
        else:
            out += list(method_module(method).method_text())
    return out


def combinations_kind(method: str | None = None) -> str:
    """Which combinations the method checks: "allowable" (the code pack's allowable stress
    combinations) or "strength" (the design combinations)."""
    return str(method_module(method).COMBINATIONS)


def site_zone(settings: Any) -> int | None:
    """The seismic zone of the project's site: its location's, or the zone whose coefficient is
    nearest the entered Z; None when neither is known."""
    if settings is None:
        return None
    try:
        from saengine.library.settings import derived

        d = derived(settings)
    except Exception:  # noqa: BLE001 - a project without the site tables
        return None
    if d.get("zone") is not None:
        return int(d["zone"])
    z = d.get("Z")
    if z is None:
        return None
    try:
        zones = code_context.pack_table("zoneCoefficients").zones
    except Exception:  # noqa: BLE001
        return None
    return int(min(zones, key=lambda k: abs(float(zones[k]) - float(z))))


def site_wind_kmh(settings: Any) -> float | None:
    """The basic wind speed of the project's site [km/h]."""
    if settings is None:
        return None
    try:
        from saengine.library.settings import derived

        v = derived(settings).get("windSpeed")
    except Exception:  # noqa: BLE001
        return None
    return None if v is None else float(v) * 3.6


def seismic_shear(forces: list[Any], zone: int | None) -> list[Any]:
    """The forces with the in-plane shear of the earthquake combinations × the pack's factor in
    the highest seismic zone (``seismic.zone4.shearForceFactor``)."""
    zones = table().seismic.zones
    if zone is None or not zones or zone != max(zones):
        return forces
    factor = float(table().seismic.zone4.get("shearForceFactor", 1.0))
    if factor == 1.0:
        return forces
    return [replace(f, V2=f.V2 * factor) if f.earthquake else f for f in forces]


def masonry_wall_checks(
    geometry: Any,
    bars: Any,
    forces: list[Any],
    m: Masonry,
    fy: float = 420.0,
    lateral: frozenset[str] | set[str] = frozenset(),
    storeys: int | None = None,
    *,
    method: str | None = None,
    service: list[Any] | None = None,
    zone: int | None = None,
    wind_kmh: float | None = None,
    storey_from_top: int | None = None,
    opening_share: float | None = None,
    confined: bool = False,
) -> MasonryDesign:
    """The checks of a masonry wall pier by the code pack's method (or ``method``, one the pack
    permits): plain masonry without ``bars``, reinforced masonry with them. ``forces``: the
    pier's forces under the method's combinations (compression positive, N and N·mm);
    ``lateral``: the names of the combinations with wind or earthquake; ``storeys``: the
    building's storeys (minimum thickness); ``service``: the service forces (the strength
    method's deflection). With ``zone`` and ``wind_kmh`` the pack's seismic detailing and high
    wind rules are added (:mod:`saengine.design.masonry_seismic`); ``storey_from_top`` (0: the
    top storey) and ``opening_share`` (the openings' share of the wall's length) feed them;
    ``confined``: the wall is confined (its tie columns and beams stand for the bands and
    corner bars)."""
    chosen = method_id(method)
    module = method_module(chosen)
    shear_forces = seismic_shear(forces, zone)
    if chosen == "strength":
        d = module.wall_checks(geometry, bars, shear_forces, m, fy, lateral, storeys, service)
    else:
        d = module.wall_checks(geometry, bars, shear_forces, m, fy, lateral, storeys)
    if shear_forces is not forces:
        d.notes.append(
            "in-plane shear of the earthquake combinations × "
            f"{float(table().seismic.zone4['shearForceFactor']):g} ({clause('zone4Shear')})"
        )
    if method and method != chosen:
        d.notes.append(f"method '{method}' is not permitted by the code pack: '{chosen}' is used")
    from saengine.design import masonry_seismic as S

    rows, notes = S.detailing(
        geometry,
        bars,
        m,
        zone=zone,
        wind_kmh=wind_kmh,
        storeys=storeys,
        storey_from_top=storey_from_top,
        opening_share=opening_share,
        bearing=any(f.P > 0 for f in forces),
        confined=confined,
    )
    d.checks += rows
    d.notes += notes
    strength = [c for c in d.checks if not c["flag"]]
    d.utilisation = max((c["utilisation"] for c in strength), default=0.0)
    return d


def fire_row(m: Masonry) -> dict[str, Any]:
    """The wall's fire rating inputs (:mod:`saengine.design.fire_resistance`): the row of the
    code pack's ``fireResistance.masonryThickness`` its units use ("clayUnfilled",
    "clayFilled", "concreteUnfilled", ...; hollow units fully grouted are "filled") and whether
    the wall's thickness is its equivalent thickness (solid units, or hollow units fully
    grouted; otherwise the units' net volume is needed)."""
    hollow = m.units == "hollow"
    filled = hollow and m.grouting == "full"
    return {
        "row": f"{m.kind}{'Filled' if filled else 'Unfilled'}",
        "equivalent": not hollow or filled,
    }


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
    "fire_row",
    "masonry_of",
    "masonry_wall_checks",
    "method_id",
    "method_module",
    "method_text",
    "methods",
    "mortar_grade_of_mix",
    "mortar_grades",
    "mortar_rank",
    "prism_estimate",
    "seismic_shear",
    "site_wind_kmh",
    "site_zone",
    "table",
]

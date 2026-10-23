"""Which earthquake-resistant detailing provisions apply, and the general requirements, to
BNBC 2020 Part 6 Chapter 8 Sec 8.3 (pp. 1088-1123 of the code PDF) with the system rules of
Part 6 Chapter 2 Sec 2.5 (pp. 617-625, 646).

What this module decides, from the project settings, materials, object types and building:

* the Seismic Design Category (Sec 2.5.5.2, Table 6.2.18, p. 617), with
  :func:`saengine.fem.seismic_design.seismic_design_category`;
* the seismic force-resisting system, its R, Ω0, Cd and whether Table 6.2.19 (pp. 621-624)
  permits it in that category and at the building's height;
* the detailing level the category requires (Sec 8.3.2(b)-(e), pp. 1088-1089: D special,
  C intermediate, B ordinary; a lower category may use a higher level) and so which sections of
  8.3 apply (8.3.3-8.3.12; 8.3.6, special structural walls, designed by saengine.design.walls);
* the material requirements of Sec 8.3.3.3-8.3.3.5 (pp. 1089-1090) as checks;
* per member its role (part of the seismic force-resisting system or not, Sec 8.3.3.1(d),
  8.3.12) and whether it needs the combinations with the overstrength factor Ω0 (Sec 2.5.5.6,
  2.5.13.4, pp. 625, 646), with the combinations themselves as data.

Pure functions: nothing is read from disk. Checks follow :mod:`saengine.design.check`:
``{name, demand, capacity, unit, utilisation, combination, ok, note, flag}``; ``flag`` checks
are reported without failing (values the model does not hold, such as mill-test results).
"""

from __future__ import annotations

import math
from typing import Any, Literal, NamedTuple

from saengine.library import bnbc

FrameType = Literal["special", "intermediate", "ordinary"]

#: Detailing levels in increasing order of stringency.
LEVELS: tuple[FrameType, ...] = ("ordinary", "intermediate", "special")

CLAUSES = {
    "scope": "BNBC 2020 Part 6 Sec 8.3.1 (p. 1088)",
    "provisions": "BNBC 2020 Part 6 Sec 8.3.2 (pp. 1088-1089)",
    "sdc": "BNBC 2020 Part 6 Sec 2.5.5.2, Table 6.2.18 (p. 617)",
    "systems": "BNBC 2020 Part 6 Sec 2.5.5.4, Table 6.2.19 (pp. 619-624)",
    "analysis": "BNBC 2020 Part 6 Sec 8.3.3.1 (p. 1089)",
    "phi": "BNBC 2020 Part 6 Sec 8.3.3.2 (p. 1089)",
    "concrete": "BNBC 2020 Part 6 Sec 8.3.3.3 (p. 1089)",
    "reinforcement": "BNBC 2020 Part 6 Sec 8.3.3.4 (pp. 1089-1090)",
    "welding": "BNBC 2020 Part 6 Sec 8.3.3.5 (p. 1090)",
    "splices": "BNBC 2020 Part 6 Sec 8.3.4.2(b), 8.3.5.3(b) (pp. 1091, 1096)",
    "lightweight": "BNBC 2020 Part 6 Sec 6.1 definitions (p. 868), Sec 6.1.8 (p. 893)",
    "shearFy": "BNBC 2020 Part 6 Sec 6.4.3.2 (p. 924)",
    "discontinuous": "BNBC 2020 Part 6 Sec 2.5.5.6.1 (p. 625)",
    "irregularForces": "BNBC 2020 Part 6 Sec 2.5.5.6.2 (p. 625)",
    "collectors": "BNBC 2020 Part 6 Sec 2.5.5.6.3 (p. 625)",
    "omega": "BNBC 2020 Part 6 Sec 2.5.13.4 (p. 646)",
    "vertical": "BNBC 2020 Part 6 Sec 2.5.13.2, eq. 6.2.56 (pp. 645-646)",
}

#: Sections of 8.3 with their page and title.
SECTIONS: dict[str, tuple[int, str]] = {
    "8.3.3": (1089, "General requirements"),
    "8.3.4": (1090, "Flexural members of special moment frames"),
    "8.3.5": (1095, "Special moment frame members subjected to bending and axial load"),
    "8.3.6": (1100, "Special structural walls and coupling beams"),
    "8.3.7": (1108, "Joints of special moment frames"),
    "8.3.8": (1111, "Shear strength requirements"),
    "8.3.9": (1113, "Ordinary moment frame members (members not proportioned for earthquake)"),
    "8.3.10": (1114, "Intermediate moment frames"),
    "8.3.11": (1120, "Foundations"),
    "8.3.12": (1122, "Members not designated as part of the seismic-force-resisting system"),
}


class SystemRow(NamedTuple):
    """A row of Table 6.2.19 (pp. 621-624)."""

    row: str
    r: float
    omega: float
    cd: float
    #: Height limit [m] in categories B, C, D: None no limit (NL), 0 not permitted (NP).
    limits: tuple[float | None, float | None, float | None]
    #: Detailing level of the system's RC moment frames, or None when its frames are not part
    #: of the seismic force-resisting system (building frame systems) or it is not RC.
    frame: FrameType | None
    #: Whether the system's walls are special structural walls (8.3.6).
    specialWalls: bool = False
    concrete: bool = True


NL = None
NP = 0.0

#: Table 6.2.19 rows of the systems a project can choose (``bnbc.STRUCTURAL_SYSTEMS``).
TABLE_6_2_19: dict[str, SystemRow] = {
    "rcSmf": SystemRow("C.4 (p. 623)", 8.0, 3.0, 5.5, (NL, NL, NL), "special"),
    "rcImf": SystemRow("C.5 (p. 623)", 5.0, 3.0, 4.5, (NL, NL, NP), "intermediate"),
    "rcOmf": SystemRow("C.5 [sic, the 6th row] (p. 623)", 3.0, 3.0, 2.5, (NL, NP, NP), "ordinary"),
    "rcSpecialWallFrame": SystemRow(
        "B.5 (p. 622)", 6.0, 2.5, 5.0, (NL, NL, 50.0), None, specialWalls=True
    ),
    "rcOrdinaryWallFrame": SystemRow("B.6 (p. 622)", 5.0, 2.5, 4.25, (NL, NL, NP), None),
    "rcDualSpecial": SystemRow(
        "D.3 (p. 623)", 7.0, 2.5, 5.5, (NL, NL, NL), "special", specialWalls=True
    ),
    "steelSmf": SystemRow("C.1 (p. 622)", 8.0, 3.0, 5.5, (NL, NL, NL), None, concrete=False),
    "steelOmf": SystemRow("C.3 (p. 622)", 3.5, 3.0, 3.0, (NL, NL, NP), None, concrete=False),
    "steelScbf": SystemRow("B.3 (p. 622)", 6.0, 2.0, 5.0, (NL, NL, 50.0), None, concrete=False),
}

#: The detailing level each category requires (Sec 8.3.2(b)-(d)).
REQUIRED_LEVEL: dict[str, FrameType] = {"D": "special", "C": "intermediate", "B": "ordinary"}

#: Sec 8.3.3.3: f'c of special moment frames and special walls at least 21 MPa; lightweight
#: concrete at most 35 MPa unless shown by tests.
FC_MIN = 21.0
FC_MAX_LIGHTWEIGHT = 35.0
#: Lightweight concrete: equilibrium density 1450-1850 kg/m³ (Sec 6.1 definitions, p. 868).
LIGHTWEIGHT_DENSITY = 1850.0
#: Sec 8.3.3.4(b): permitted grades, as their specified yield strength [MPa]: ASTM A706 Grade
#: 420; BDS ISO 6935-2 Grades 300, 350, 400, 420; ASTM A615 Grades 275 and 420.
PERMITTED_FY = (275.0, 300.0, 350.0, 400.0, 420.0)
FY_MAX = 420.0
#: A specified fy within this fraction of a permitted grade is taken as that grade, with a
#: warning (Grade 420 / 60 ksi = 413.7 MPa is often entered as 415 MPa): an SAEngine choice.
GRADE_TOLERANCE = 0.02
#: Sec 8.3.3.4(b)(i): actual (mill-test) fy at most the specified fy + 125 MPa (retests +20).
FY_ACTUAL_MARGIN = 125.0
FY_RETEST_MARGIN = 20.0
#: Sec 8.3.3.4(b)(ii): actual tensile / actual yield at least 1.25.
FU_FY_MIN = 1.25
#: Sec 8.3.3.4(c): fyt of the confinement reinforcement at most 700 MPa.
FYT_CONFINEMENT_MAX = 700.0
#: Sec 6.4.3.2 via 8.3.3.4(d): fy, fyt of shear reinforcement at most 420 MPa.
FYT_SHEAR_MAX = 420.0

#: Position tolerance of the discontinuity search [mm].
TOLERANCE = 50.0

ROLE_FIELD = "seismicRole"  # "auto" | "lateral" | "gravity"
OMEGA_FIELD = "omegaCombinations"  # "auto" | "transfer" | "collector" | "none"


# ─────────────────────────────────────── checks ───────────────────────────────────────


def _check(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    note: str = "",
    flag: bool = False,
    utilisation: float | None = None,
) -> dict[str, Any]:
    """A check in :func:`saengine.design.check._check`'s format (no combination)."""
    if utilisation is None:
        utilisation = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    utilisation = round(float(utilisation), 3) if math.isfinite(utilisation) else 99.0
    return {
        "name": name,
        "demand": round(float(demand), 2),
        "capacity": round(float(capacity), 2),
        "unit": unit,
        "utilisation": utilisation,
        "combination": None,
        "ok": bool(utilisation <= 1.0),
        "note": note,
        "flag": flag,
    }


# ─────────────────────────────────────── the system ───────────────────────────────────────


def seismic_design_category(settings: Any) -> tuple[str | None, int | None]:
    """(category "B"/"C"/"D" or None without a zone, zone 1-4) of Table 6.2.18 (p. 617) from the
    settings' zone (the location's, or the zone nearest the entered Z), site class and occupancy
    category. The settings should carry the site class the analysis uses
    (:func:`saengine.library.settings.resolve_site_class`)."""
    from saengine.fem.seismic_design import seismic_design_category as table
    from saengine.fem.seismic_design import zone_of
    from saengine.library.settings import derived

    values = derived(settings)
    zone = values["zone"] if settings.site.zoneCoefficient is None else None
    if zone is None:
        zone = zone_of(values["Z"])
    return table(zone, settings.site.siteClass, settings.occupancy.category), zone


def building_height(building: Any) -> float | None:
    """Height of the structure [m]: the highest column or wall top or beam level over the lowest
    column or wall bottom (BNBC's height above the base, taken from the elements); None without
    columns or walls."""
    if building is None:
        return None
    bottoms, tops = [], []
    for e in getattr(building, "elements", []):
        kind = getattr(e, "kind", "")
        if kind in ("column", "wall"):
            bottoms.append(float(e.bottom))
            tops.append(float(e.top))
        elif kind == "beam":
            tops.append(float(e.elevation))
    if not bottoms or not tops:
        return None
    return (max(tops) - min(bottoms)) / 1000.0


def _level_at_least(level: FrameType, required: FrameType) -> bool:
    return LEVELS.index(level) >= LEVELS.index(required)


def system_checks(
    system: str, row: SystemRow | None, sdc: str | None, height: float | None
) -> list[dict[str, Any]]:
    """Table 6.2.19 (pp. 621-624): the system permitted (not NP) in the category, and within the
    height limit; Sec 8.3.2: the system's frame detailing at least what the category needs."""
    if row is None or sdc is None:
        return []
    limit = row.limits["BCD".index(sdc)]
    name = bnbc.STRUCTURAL_SYSTEMS[system].name if system in bnbc.STRUCTURAL_SYSTEMS else system
    checks = []
    if limit == NP:
        checks.append(
            _check(
                f"System permitted in Seismic Design Category {sdc} (Table 6.2.19 row {row.row})",
                1.0,
                0.0,
                "-",
                f"Table 6.2.19 row {row.row}: {name} is NP (not permitted) in Category {sdc}"
                + (
                    f"; Sec 8.3.2 requires {REQUIRED_LEVEL[sdc]} seismic detailing in Category "
                    f"{sdc}: choose a system with it (and its R, Ω0, Cd)"
                    if row.frame and not _level_at_least(row.frame, REQUIRED_LEVEL[sdc])
                    else ""
                ),
                utilisation=99.0,
            )
        )
    elif limit is not None:
        if height is None:
            checks.append(
                _check(
                    f"Height limit of the system in Category {sdc} (Table 6.2.19)",
                    0.0,
                    limit,
                    "m",
                    f"Table 6.2.19 row {row.row}: at most {limit:g} m; the building has no "
                    "columns or walls to take its height from",
                    flag=True,
                )
            )
        else:
            checks.append(
                _check(
                    f"Height limit of the system in Category {sdc} (Table 6.2.19)",
                    height,
                    limit,
                    "m",
                    f"Table 6.2.19 row {row.row}: {name} at most {limit:g} m high in Category "
                    f"{sdc}",
                )
            )
    return checks


def _used_materials(
    objects: Any, kinds: tuple[str, ...], frame_types: set[str] | None = None
) -> tuple[dict[str, list], dict[str, list]]:
    """Concrete and rebar material ids used by object types of ``kinds``: concrete {id: [type
    ids]}, rebar {id: [types]}. ``frame_types`` limits the beam and column types to those ids
    (the types of the special moment frame members)."""
    concrete: dict[str, list] = {}
    rebar: dict[str, list] = {}
    for o in getattr(objects, "objects", []):
        if o.kind not in kinds:
            continue
        if frame_types is not None and o.kind in ("beam", "column") and o.id not in frame_types:
            continue
        concrete.setdefault(o.material, []).append(o.id)
        reinforcement = getattr(o, "reinforcement", None)
        if reinforcement is not None and hasattr(reinforcement, "material"):
            rebar.setdefault(reinforcement.material, []).append(o)
    return concrete, rebar


def _bar_dias(object_type: Any) -> list[float]:
    """Longitudinal bar diameters of a beam or column type, vertical and horizontal ones of a
    wall type."""
    r = object_type.reinforcement
    dias = [float(g.dia) for g in getattr(r, "longitudinal", []) or []]
    for mesh in ("vertical", "horizontal"):
        layer = getattr(r, mesh, None)
        if layer is not None:
            dias.append(float(layer.dia))
    return dias


def required_elongation(dia: float) -> float:
    """Sec 8.3.3.4(b)(iii): minimum elongation in 200 mm [%] by bar diameter: 14 for 10-20 mm,
    12 for 22-36 mm, 10 for 40-60 mm (bars under 10 mm: the 14 % of the smallest range, an
    SAEngine reading; between the ranges: the next larger range's)."""
    if dia <= 20:
        return 14.0
    if dia <= 36:
        return 12.0
    return 10.0


def material_checks(
    materials: Any,
    objects: Any,
    frame_type: FrameType | None,
    special_walls: bool,
    frame_types: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Sec 8.3.3.3 and 8.3.3.4 (pp. 1089-1090) for the materials of the beam and column types
    of the special moment frames (``frame_type`` "special"; ``frame_types``, when given, the
    type ids of its members, so gravity frames are left out) and of the wall types with special
    walls. They apply to special moment frames and special structural walls only (titles of
    8.3.3.3, 8.3.3.4 and 8.3.3.4(a)); otherwise the result is empty with a note."""
    if frame_types is not None and not frame_types and frame_type == "special":
        frame_type = None
    notes: list[str] = []
    if frame_type != "special" and not special_walls:
        return [], [
            (
                f"the material requirements of {CLAUSES['concrete']} and {CLAUSES['reinforcement']} "
                "apply to special moment frames and special structural walls only"
            )
        ]
    kinds = (("beam", "column") if frame_type == "special" else ()) + (
        ("wall",) if special_walls else ()
    )
    concrete_used, rebar_used = _used_materials(objects, kinds, frame_types)
    by_id = {m.id: m for m in getattr(materials, "materials", [])}
    checks: list[dict[str, Any]] = []
    for mid, types in sorted(concrete_used.items()):
        m = by_id.get(mid)
        if m is None or m.concrete is None:
            continue
        fc = float(m.concrete.fc)
        used = ", ".join(types)
        checks.append(
            _check(
                f"f'c ≥ 21 MPa (Sec 8.3.3.3, p. 1089): {mid}",
                FC_MIN,
                fc,
                "MPa",
                f"concrete of {used}",
            )
        )
        density = m.mechanical.density
        if density is not None and density <= LIGHTWEIGHT_DENSITY:
            checks.append(
                _check(
                    f"Lightweight f'c ≤ 35 MPa (Sec 8.3.3.3, p. 1089): {mid}",
                    fc,
                    FC_MAX_LIGHTWEIGHT,
                    "MPa",
                    f"density {density:g} kg/m³ is lightweight concrete ({CLAUSES['lightweight']});"
                    " higher strengths need experimental evidence; λ per Sec 6.1.8",
                )
            )
    for mid, types in sorted(rebar_used.items()):
        m = by_id.get(mid)
        if m is None or m.steel is None:
            continue
        steel = m.steel
        fy = float(steel.fy)
        used = ", ".join(t.id for t in types)
        grade = steel.grade or mid
        nearest = min(PERMITTED_FY, key=lambda g: abs(fy - g))
        exact = abs(fy - nearest) < 1e-6
        near = not exact and abs(fy - nearest) <= GRADE_TOLERANCE * nearest
        if exact:
            remark = ""
        elif near:
            remark = (
                f"; fy {fy:g} MPa taken as Grade {nearest:g} (within {GRADE_TOLERANCE:.0%}: "
                "60 ksi = 413.7 MPa is often entered as 415): confirm the grade"
            )
        else:
            remark = f"; fy {fy:g} MPa is not one of these grades"
        checks.append(
            _check(
                f"Reinforcement grade (Sec 8.3.3.4(b), p. 1090): {mid}",
                fy,
                FY_MAX,
                "MPa",
                f"{grade}, fy {fy:g} MPa, in {used}: only ASTM A706 Grade 420, BDS ISO 6935-2 "
                "Grades 300, 350, 400, 420 or ASTM A615 Grades 275, 420 may resist earthquake-"
                "induced flexure and axial force" + remark,
                flag=near,
                utilisation=None if exact or near or fy > FY_MAX else 99.0,
            )
        )
        actual_fy = getattr(steel, "fyActual", None)
        actual_fu = getattr(steel, "fuActual", None)
        if actual_fy is not None:
            checks.append(
                _check(
                    f"Actual fy ≤ fy + 125 MPa (Sec 8.3.3.4(b)(i), p. 1090): {mid}",
                    float(actual_fy),
                    fy + FY_ACTUAL_MARGIN,
                    "MPa",
                    "mill-test yield strength; retests at most a further 20 MPa",
                )
            )
        else:
            checks.append(
                _check(
                    f"Actual fy ≤ fy + 125 MPa (Sec 8.3.3.4(b)(i), p. 1090): {mid}",
                    fy,
                    fy + FY_ACTUAL_MARGIN,
                    "MPa",
                    "the material has no mill-test yield strength: check the mill certificate "
                    f"(actual fy at most {fy + FY_ACTUAL_MARGIN:g} MPa)",
                    flag=True,
                )
            )
        fu = actual_fu if actual_fu is not None else steel.fu
        ratio_fy = float(actual_fy) if actual_fy is not None and actual_fu is not None else fy
        if fu is not None:
            ratio = float(fu) / ratio_fy
            actual = actual_fu is not None and actual_fy is not None
            checks.append(
                _check(
                    f"fu/fy ≥ 1.25 (Sec 8.3.3.4(b)(ii), p. 1090): {mid}",
                    FU_FY_MIN,
                    ratio,
                    "-",
                    f"fu {float(fu):g} / fy {ratio_fy:g} MPa"
                    + (
                        ""
                        if actual
                        else " (the material's values; the clause asks for the actual mill-test "
                        "values)"
                    ),
                )
            )
        else:
            checks.append(
                _check(
                    f"fu/fy ≥ 1.25 (Sec 8.3.3.4(b)(ii), p. 1090): {mid}",
                    FU_FY_MIN,
                    0.0,
                    "-",
                    "the material has no fu: enter it from the mill certificate (actual tensile / "
                    "actual yield strength at least 1.25)",
                    flag=True,
                    utilisation=0.0,
                )
            )
        dias = [d for t in types for d in _bar_dias(t)]
        need = max((required_elongation(d) for d in dias), default=14.0)
        largest = max(dias, default=0.0)
        if steel.elongation is not None:
            checks.append(
                _check(
                    f"Elongation in 200 mm (Sec 8.3.3.4(b)(iii), p. 1090): {mid}",
                    need,
                    float(steel.elongation),
                    "%",
                    f"bars up to {largest:g} mm: at least 14 % for 10-20 mm, 12 % for 22-36 mm, "
                    "10 % for 40-60 mm",
                )
            )
        else:
            checks.append(
                _check(
                    f"Elongation in 200 mm (Sec 8.3.3.4(b)(iii), p. 1090): {mid}",
                    need,
                    0.0,
                    "%",
                    f"the material has no elongation: at least {need:g} % from the mill "
                    "certificate (14 % for 10-20 mm, 12 % for 22-36 mm, 10 % for 40-60 mm bars)",
                    flag=True,
                    utilisation=0.0,
                )
            )
        has_ties = any(getattr(t.reinforcement, "transverse", None) for t in types)
        if has_ties:
            checks.append(
                _check(
                    f"fyt of confinement ≤ 700 MPa (Sec 8.3.3.4(c), p. 1090): {mid}",
                    fy,
                    FYT_CONFINEMENT_MAX,
                    "MPa",
                    "the transverse bars use the member's reinforcement material",
                )
            )
    notes.append(
        f"BNBC 2020 Part 6 Sec 8.3.3.4(d) (p. 1090) and {CLAUSES['shearFy']}: fy, fyt of shear reinforcement "
        "at most 420 MPa; the shear design (saengine.design.rc.shear) already caps fyt at 420 MPa"
    )
    notes.append(
        f"{CLAUSES['welding']}: reinforcement required by the earthquake combinations is not to "
        "be welded except as 8.3.4.2(d) and 8.3.5.3(b) allow, and stirrups, ties and inserts "
        "are not to be welded to the longitudinal bars (a drawing note; the model holds no "
        "welds)"
    )
    notes.append(
        f"{CLAUSES['splices']}: welded splices and mechanical connections to Sec 8.2.12.3(a)-(d) "
        "only at alternate bars of a layer, 600 mm apart along the member; welded splices and "
        "Type 1 mechanical connections not within twice the member depth of a joint face or "
        "where yielding is likely. BNBC 8.3 does not define Type 1/Type 2 itself (ACI 318 "
        "18.2.7 does); the model holds no splice positions, so this is a drawing note"
    )
    return checks, notes


# ─────────────────────────────────────── members ───────────────────────────────────────


def _near(a: Any, b: Any, tol: float = TOLERANCE) -> bool:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])) <= tol


def _on_segment(p: Any, a: Any, b: Any, tol: float = TOLERANCE) -> bool:
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    px, py = float(p[0]), float(p[1])
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 0:
        return _near(p, a, tol)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) <= tol


def _overlap(a1: Any, a2: Any, b1: Any, b2: Any, tol: float = TOLERANCE) -> bool:
    """Segment b lies along segment a for more than the tolerance."""
    inside = [p for p in (b1, b2) if _on_segment(p, a1, a2, tol)]
    inside += [p for p in (a1, a2) if _on_segment(p, b1, b2, tol)]
    if len(inside) < 2:
        return False
    return max(math.dist(p, q) for p in inside for q in inside) > tol


def _half_size(object_type: Any) -> float:
    """Half the smaller plan dimension of a column type's profile [mm] (0 when unknown): an
    upper column whose axis lies within it sits on the column below (an eccentricity, not a
    discontinuity)."""
    profile = getattr(object_type, "profile", None)
    if profile is None:
        return 0.0
    if getattr(profile, "shape", "") == "circle":
        return float(profile.radius)
    dims = [float(getattr(profile, k)) for k in ("xDim", "yDim") if hasattr(profile, k)]
    return min(dims) / 2 if dims else 0.0


def _structural_wall(wall: Any, types: dict[str, Any], materials: dict[str, Any]) -> bool:
    """A wall element of the seismic force-resisting system: its type is ``structural`` (not a
    partition or infill, ``objects.Wall.structural``) and, when its material is known, not
    masonry or another non-concrete material. Infill and partitions are not the "discontinuous
    walls" of Sec 2.5.5.6.1 (vertical irregularity Type IV concerns the elements resisting the
    lateral forces) and carry no column."""
    t = types.get(getattr(wall, "type", None))
    if t is not None and not getattr(t, "structural", True):
        return False
    m = materials.get(getattr(t, "material", None)) if t is not None else None
    category = getattr(getattr(m, "category", None), "value", getattr(m, "category", None))
    return m is None or category in (None, "concrete")


def discontinuities(
    building: Any, objects: Any = None, materials: Any = None
) -> list[dict[str, Any]]:
    """Columns and walls that stop above the base on something other than a column, wall or
    footing below (Sec 2.5.5.6.1: vertical irregularity Type IV, in-plane discontinuity, or
    horizontal Type IV, out-of-plane offset, p. 618), with the beams that carry them and the
    columns under those beams' ends: ``[{"id", "kind", "elevation", "supportedBy": [beam
    ids], "supportColumns": [column ids]}]``. An automatic finding for the engineer to confirm:
    slabs carrying a planted column without a beam are not found (the column is listed with no
    supporting beam). Only structural walls count (:func:`_structural_wall`): a brick partition
    on a beam is not a discontinuous wall, and a column on one is not supported."""
    if building is None:
        return []
    types = {o.id: o for o in getattr(objects, "objects", [])} if objects is not None else {}
    by_material = {m.id: m for m in getattr(materials, "materials", [])} if materials else {}
    elements = list(getattr(building, "elements", []))
    columns = [e for e in elements if getattr(e, "kind", "") == "column"]
    walls = [
        e
        for e in elements
        if getattr(e, "kind", "") == "wall" and _structural_wall(e, types, by_material)
    ]
    beams = [e for e in elements if getattr(e, "kind", "") == "beam"]
    footings = [e for e in elements if getattr(e, "kind", "") == "footing"]
    if not columns and not walls:
        return []
    base = min(float(e.bottom) for e in columns + walls)
    found = []

    def reach(column: Any) -> float:
        return max(TOLERANCE, _half_size(types.get(column.type)))

    def beam_ends_columns(beam: Any, z: float) -> list[str]:
        return sorted(
            c.id
            for c in columns
            if abs(float(c.top) - z) <= TOLERANCE
            and (_near(c.position, beam.start) or _near(c.position, beam.end))
        )

    for c in columns:
        z = float(c.bottom)
        if z <= base + TOLERANCE:
            continue
        below = any(
            o is not c
            and abs(float(o.top) - z) <= TOLERANCE
            and _near(o.position, c.position, reach(o))
            for o in columns
        ) or any(
            abs(float(w.top) - z) <= TOLERANCE and _on_segment(c.position, w.start, w.end)
            for w in walls
        )
        footed = any(
            abs(float(f.elevation) - z) <= TOLERANCE and _near(f.position, c.position)
            for f in footings
        )
        if below or footed:
            continue
        carrying = [
            b
            for b in beams
            if abs(float(b.elevation) - z) <= TOLERANCE and _on_segment(c.position, b.start, b.end)
        ]
        supports = sorted({cid for b in carrying for cid in beam_ends_columns(b, z)})
        found.append(
            {
                "id": c.id,
                "kind": "column",
                "elevation": z,
                "supportedBy": sorted(b.id for b in carrying),
                "supportColumns": supports,
            }
        )
    for w in walls:
        z = float(w.bottom)
        if z <= base + TOLERANCE:
            continue
        below = any(
            o is not w
            and abs(float(o.top) - z) <= TOLERANCE
            and _overlap(o.start, o.end, w.start, w.end)
            for o in walls
        )
        if below:
            continue
        carrying = [
            b
            for b in beams
            if abs(float(b.elevation) - z) <= TOLERANCE and _overlap(b.start, b.end, w.start, w.end)
        ]
        supports = sorted({cid for b in carrying for cid in beam_ends_columns(b, z)})
        found.append(
            {
                "id": w.id,
                "kind": "wall",
                "elevation": z,
                "supportedBy": sorted(b.id for b in carrying),
                "supportColumns": supports,
            }
        )
    return found


def member_roles(
    objects: Any,
    building: Any,
    row: SystemRow | None,
    sdc: str | None,
    overrides: dict[str, dict[str, str]] | None = None,
    materials: Any = None,
) -> dict[str, dict[str, Any]]:
    """Per beam and column element (and inclined member of a beam or column type) ``{"kind",
    "role": "lateral"|"gravity", "roleSource", "omega": None|"transfer"|"collector",
    "omegaSource", "provisions": [sections], "note"}``.

    The role: the element's ``seismicRole`` ("lateral"/"gravity"; "auto" or absent: its object
    type's, then the system's), ``overrides[id]["role"]`` first. By the system: moment frames
    and dual systems' frames are part of the seismic force-resisting system; the beams and
    columns of building frame systems (shear walls) are not (Table 6.2.19 B: the walls resist
    the earthquake). The Ω0 need: the element's or type's ``omegaCombinations`` ("transfer",
    "collector", "none"; "auto": found by :func:`discontinuities`), ``overrides[id]["omega"]``
    first. Collectors need Ω0 in Category C and D only (2.5.5.6.3); SAEngine cannot find
    collectors (it has no diaphragm-chord model): the engineer marks them."""
    overrides = overrides or {}
    types = {o.id: o for o in getattr(objects, "objects", [])}
    default_role = "lateral" if row is None or row.frame is not None else "gravity"
    transfer: dict[str, str] = {}
    for d in discontinuities(building, objects, materials):
        for bid in d["supportedBy"]:
            transfer.setdefault(bid, f"carries discontinuous {d['kind']} {d['id']}")
        for cid in d["supportColumns"]:
            transfer.setdefault(
                cid, f"supports the beam(s) under discontinuous {d['kind']} {d['id']}"
            )
    members = []
    if building is not None:
        members = [
            e
            for e in getattr(building, "elements", [])
            if getattr(e, "kind", "") in ("beam", "column")
        ]
        members += list(getattr(getattr(building, "additions", None), "members", []) or [])
    result: dict[str, dict[str, Any]] = {}
    for e in members:
        t = types.get(e.type)
        kind = t.kind if t is not None else getattr(e, "kind", "member")
        if kind not in ("beam", "column"):
            continue
        given = overrides.get(e.id, {})
        role, source = given.get("role"), "override"
        if role in (None, "auto"):
            role, source = getattr(e, ROLE_FIELD, None), "element"
        if role in (None, "auto"):
            role, source = getattr(t, ROLE_FIELD, None), "type"
        if role in (None, "auto"):
            role, source = default_role, "system"
        omega, omega_source = given.get("omega"), "override"
        if omega in (None, "auto"):
            omega, omega_source = getattr(e, OMEGA_FIELD, None), "element"
        if omega in (None, "auto"):
            omega, omega_source = getattr(t, OMEGA_FIELD, None), "type"
        note = ""
        if omega in (None, "auto"):
            omega, omega_source = ("transfer", "auto") if e.id in transfer else (None, "auto")
            if omega:
                note = (
                    f"{transfer[e.id]}: {CLAUSES['discontinuous']}, an automatic finding to confirm"
                )
        if omega == "none":
            omega = None
        if omega == "collector" and sdc not in ("C", "D"):
            note = f"collectors need Ω0 in Category C and D only ({CLAUSES['collectors']})"
            omega = None
        provisions = _member_provisions(kind, role, row, sdc)
        result[e.id] = {
            "kind": kind,
            "role": role,
            "roleSource": source,
            "omega": omega,
            "omegaSource": omega_source,
            "provisions": provisions,
            "note": note,
        }
    return result


def detailing_level(row: SystemRow | None, sdc: str | None) -> FrameType | None:
    """The detailing level of the structure's RC members of the seismic force-resisting system:
    the stricter of the system's frames' and the one the category requires (Sec 8.3.2(b)-(e));
    for a building frame system (no moment frame) the category's. None for a system that is
    not RC."""
    if row is None or not row.concrete:
        return None
    required = REQUIRED_LEVEL.get(sdc or "", "ordinary")
    own = row.frame or required
    return own if _level_at_least(own, required) else required


def frame_type_of(row: SystemRow | None, sdc: str | None) -> FrameType | None:
    """The detailing level the system's moment frames are checked to (:func:`detailing_level`);
    None for a system without RC moment frames in its seismic force-resisting system (building
    frame systems, whose beams and columns are gravity members, and steel systems)."""
    if row is None or row.frame is None:
        return None
    return detailing_level(row, sdc)


def _member_provisions(kind: str, role: str, row: SystemRow | None, sdc: str | None) -> list[str]:
    """Sections of 8.3 a beam or column follows.

    Members not part of the seismic force-resisting system: in Category D, 8.3.2(b) puts
    8.3.3 in force, and 8.3.3.1(d) (p. 1089) sends them to 8.3.9; 8.3.12.1(a) (p. 1122) adds
    8.3.12 in D. In B, 8.3.2(d) makes 8.3.9 apply to all RC structures. In C, 8.3.2(c) asks for
    8.3.10 only, and 8.3.10.1 covers the frames proportioned to resist earthquake: BNBC sets no
    8.3 provision for gravity members there (Chapter 6 only)."""
    level = detailing_level(row, sdc)
    if level is None:
        return []
    if role == "gravity":
        return {"D": ["8.3.9", "8.3.12"], "B": ["8.3.9"]}.get(sdc or "B", [])
    if level == "special":
        return (["8.3.4"] if kind == "beam" else ["8.3.5", "8.3.7"]) + ["8.3.8"]
    if level == "intermediate":
        return ["8.3.10"]
    return ["8.3.9"]


# ─────────────────────────────────────── Ω0 combinations ───────────────────────────────────


def _vertical_coefficient(settings: Any) -> float:
    from saengine.fem.seismic_design import vertical_coefficient

    return float(vertical_coefficient(settings))


def omega_combinations(settings: Any, omega: float | None = None) -> list[dict[str, Any]]:
    """The project's earthquake combinations (those with EX or EY) with the overstrength factor
    (Sec 2.5.13.4, p. 646): E = Em = Ω0·Eh + Ev in combination 5 (1.2D + 1.0E + L) and
    Ω0·Eh − Ev in combination 7 (0.9D + 1.0E), Ev = 0.5·a_h·D (eq. 6.2.56): the EX, EY factors
    times Ω0, D (and F with it) plus 0.5·a_h where D > 1, minus it otherwise. Each is a
    :class:`saengine.library.settings.LoadCombination` dict, named ``"Ω0: <name>"``, with a
    ``"clause"``. The 100 % + 30 % directions of the project's combinations carry over (2.5.13.4
    applies 2.5.13.1(b) to Emh too). Emh need not exceed the forces a plastic mechanism or a
    nonlinear analysis gives (not computed here)."""
    from saengine.library.settings import derived

    omega = float(omega if omega is not None else derived(settings)["omega"])
    ev = _vertical_coefficient(settings)
    result = []
    for c in settings.combinations:
        if not (c.EX or c.EY):
            continue
        data = c.model_dump()
        upper = c.D > 1.0
        shift = ev if upper else -ev
        data.update(
            name=f"Ω0: {c.name}",
            D=round(c.D + shift, 4),
            EX=round(c.EX * omega, 4),
            EY=round(c.EY * omega, 4),
        )
        if data.get("F"):
            data["F"] = round(float(data["F"]) + shift, 4)
        data["clause"] = (
            f"{CLAUSES['omega']} {'1' if upper else '2'}: E = Ω0·Eh {'+' if upper else '−'} Ev, "
            f"Ω0 = {omega:g}, Ev = {ev:.4f}D"
        )
        result.append(data)
    return result


def omega_rs_combinations(
    rs_combinations: list[dict[str, Any]], settings: Any, omega: float | None = None
) -> list[dict[str, Any]]:
    """The response spectrum design combinations (:func:`saengine.fem.seismic_design.
    seismic_design`'s ``combinations``: ``{"name", "loads", "envelope", "clause"}``) with
    Em of Sec 2.5.13.4: the envelope factors times Ω0 and D = 1.2 + 0.5·a_h or 0.9 − 0.5·a_h
    (Ev always: 2.5.13.4 has it in Em whatever the response spectrum option is)."""
    from saengine.library.settings import derived

    omega = float(omega if omega is not None else derived(settings)["omega"])
    ev = _vertical_coefficient(settings)
    result = []
    for c in rs_combinations:
        loads = dict(c.get("loads", {}))
        upper = float(loads.get("D", 0.0)) > 1.0
        loads["D"] = round(1.2 + ev if upper else 0.9 - ev, 4)
        result.append(
            {
                "name": f"Ω0: {c['name']}",
                "loads": loads,
                "envelope": {
                    k: round(float(v) * omega, 4) for k, v in c.get("envelope", {}).items()
                },
                "clause": f"{CLAUSES['omega']}: E = Ω0·Eh {'+' if upper else '−'} Ev, Ω0 = "
                f"{omega:g}",
            }
        )
    return result


# ─────────────────────────────────────── the scope ───────────────────────────────────────


def _flat_slabs(objects: Any, building: Any) -> list[str]:
    """Slab types with ``system`` "flat" used by the building (or defined, without one)."""
    flat = {o.id for o in getattr(objects, "objects", []) if getattr(o, "system", None) == "flat"}
    if building is None:
        return sorted(flat)
    used = {getattr(e, "type", None) for e in getattr(building, "elements", [])}
    return sorted(flat & used)


def seismic_detailing_scope(
    settings: Any,
    materials: Any,
    objects: Any,
    building: Any = None,
    overrides: dict[str, dict[str, str]] | None = None,
    height: float | None = None,
) -> dict[str, Any]:
    """Which provisions of BNBC 2020 Part 6 Sec 8.3 apply to the project, and its general
    requirements: ``{"system", "systemName", "sdc", "zone", "R", "Cd", "Omega0", "frameType"
    (the level of the system's RC moment frames; None for building frame and steel systems),
    "detailingLevel" (the level members marked lateral are detailed to), "requiredFrameType", "systemFrameType", "height", "applies": {section: {"applies", "page",
    "title", "members", "reason"}}, "checks": [...], "members": {id: member_roles row},
    "discontinuities": [...], "omega": {"required", "elements", "combinations"}, "notes",
    "clauses"}``.

    ``settings`` should carry the analysis's site class
    (:func:`saengine.library.settings.resolve_site_class`); ``overrides`` per element id
    ``{"role", "omega"}`` (see :func:`member_roles`); ``height`` [m] replaces the one taken from
    the building."""
    from saengine.library.settings import derived

    values = derived(settings)
    system = settings.seismic.system
    row = TABLE_6_2_19.get(system)
    sdc, zone = seismic_design_category(settings)
    if height is None:
        height = building_height(building)
    frame_type = frame_type_of(row, sdc)
    level = detailing_level(row, sdc)
    required = REQUIRED_LEVEL.get(sdc) if sdc else None
    notes: list[str] = []
    checks: list[dict[str, Any]] = []

    if sdc is None:
        notes.append(
            "no seismic zone (a custom location without Z): the Seismic Design Category and the "
            "detailing level cannot be found; the ordinary level is assumed"
        )
    checks += system_checks(system, row, sdc, height)
    if row is not None:
        table = {"R": row.r, "Omega0": row.omega, "Cd": row.cd}
        library = bnbc.STRUCTURAL_SYSTEMS.get(system)
        for key, own in (("R", "r"), ("Omega0", "omega"), ("Cd", "cd")):
            if library is not None and abs(getattr(library, own) - table[key]) > 1e-9:
                notes.append(
                    f"{key} of {library.name}: the project's default is "
                    f"{getattr(library, own):g}, Table 6.2.19 row {row.row} gives {table[key]:g}"
                )
        if row.frame and required and not _level_at_least(row.frame, required):
            notes.append(
                f"the system's frames are {row.frame}; Category {sdc} requires {required} seismic "
                f"detailing ({CLAUSES['provisions']}): the members are checked to the {required} "
                "provisions, but R, Ω0 and Cd stay the system's until it is changed"
            )
        if row.frame and required and LEVELS.index(row.frame) > LEVELS.index(required):
            notes.append(
                f"{row.frame} detailing in Category {sdc} is permitted to use its lower design "
                f"forces (Sec 8.3.2(e), p. 1089)"
            )
        if not row.concrete:
            notes.append(
                "a steel system: the RC detailing of Sec 8.3 does not apply to its members "
                "(Part 6 Chapter 10)"
            )
    flat = _flat_slabs(objects, building)
    if flat and frame_type == "special" and row is not None and row.frame == "special":
        checks.append(
            _check(
                "Slabs without beams in a special moment frame (Sec 8.3.2(b), p. 1088)",
                1.0,
                0.0,
                "-",
                f"flat slab types {', '.join(flat)}: a slab without beams is not permitted as "
                "part of the seismic force-resisting system of a special moment frame; design "
                "them as gravity members (Sec 8.3.12.4)",
                flag=True,
                utilisation=99.0,
            )
        )
    members = member_roles(objects, building, row, sdc, overrides, materials)
    gravity = sorted(i for i, m in members.items() if m["role"] == "gravity")
    lateral = sorted(i for i, m in members.items() if m["role"] == "lateral")
    # Special moment frame members: the lateral beams and columns at the special level (with a
    # building, those of the elements; without one, the system's frames).
    if building is not None:
        smf = level == "special" and bool(lateral)
        element_types = {
            getattr(e, "id", None): getattr(e, "type", None)
            for e in list(getattr(building, "elements", []))
            + list(getattr(getattr(building, "additions", None), "members", []) or [])
        }
        smf_types: set[str] | None = {element_types[i] for i in lateral if element_types.get(i)}
    else:
        smf = frame_type == "special"
        smf_types = None
    m_checks, m_notes = material_checks(
        materials,
        objects,
        "special" if smf else frame_type,
        bool(row and row.specialWalls and sdc == "D"),
        smf_types,
    )
    checks += m_checks
    notes += m_notes
    if level and frame_type is None and row is not None and row.concrete:
        notes.append(
            f"{bnbc.STRUCTURAL_SYSTEMS[system].name if system in bnbc.STRUCTURAL_SYSTEMS else system}"
            " has no moment frame in its seismic force-resisting system (Table 6.2.19 group B): "
            "its beams and columns are gravity members unless marked lateral, so the special or "
            "intermediate moment frame sections apply only to members marked lateral"
        )

    def entry(section: str, applies: bool, members_: str, reason: str) -> dict[str, Any]:
        page, title = SECTIONS[section]
        return {
            "applies": bool(applies),
            "page": page,
            "title": title,
            "members": members_,
            "reason": reason,
        }

    special = smf
    walls_special = bool(row and row.specialWalls)
    applies = {
        "8.3.3": entry(
            "8.3.3",
            level == "special" or (walls_special and sdc == "D"),
            "all",
            "8.3.2(b): Category D needs 8.3.3-8.3.8 for all RC structures (8.3.3.1(d): members "
            "not part of the seismic force-resisting system conform to 8.3.9); 8.3.3.3-8.3.3.5 "
            "apply to special moment frames and special walls only",
        ),
        "8.3.4": entry(
            "8.3.4", special, "lateral beams", "special moment frame flexural members (8.3.4.1)"
        ),
        "8.3.5": entry(
            "8.3.5",
            special,
            "lateral columns",
            "special moment frame members with Pu > 0.1·Ag·f'c (8.3.5.1)",
        ),
        "8.3.6": entry(
            "8.3.6",
            walls_special and sdc == "D",
            "walls",
            "special structural walls (designed by saengine.design.walls)",
        ),
        "8.3.7": entry("8.3.7", special, "joints", "beam-column joints of special moment frames"),
        "8.3.8": entry("8.3.8", special, "lateral beams and columns", "capacity-design shear"),
        "8.3.9": entry(
            "8.3.9",
            (level == "ordinary" and bool(lateral or building is None))
            or (bool(gravity) and sdc in ("B", "D", None)),
            ", ".join(
                (["lateral members"] if level == "ordinary" and lateral else [])
                + (["gravity members"] if gravity and sdc in ("B", "D", None) else [])
            )
            or "lateral members",
            "8.3.2(d): in Category B all RC structures follow the ordinary detailing of 8.3.9; "
            "in Category D 8.3.3.1(d) (in force by 8.3.2(b)): members not part of the seismic "
            "force-resisting system conform to 8.3.9; in Category C (8.3.2(c): 8.3.10 only) "
            "BNBC sets no 8.3 provision for gravity members",
        ),
        "8.3.10": entry(
            "8.3.10",
            level == "intermediate" and bool(lateral or (building is None and frame_type)),
            "lateral beams and columns",
            "8.3.2(c), 8.3.10.1: Category C needs intermediate moment frame detailing"
            + ("; 8.3.10.6 for the flat slabs" if flat and level == "intermediate" else ""),
        ),
        "8.3.11": entry(
            "8.3.11",
            sdc == "D",
            "footings, pile caps, grade beams, piles",
            "8.3.11.1: foundations transferring earthquake forces in Category D",
        ),
        "8.3.12": entry(
            "8.3.12",
            sdc == "D" and bool(gravity),
            "gravity members",
            "8.3.12.1: members not part of the seismic force-resisting system in Category D",
        ),
    }
    if level is None:
        for value in applies.values():
            value["applies"] = False

    omega_elements = sorted(i for i, m in members.items() if m["omega"])
    combinations = omega_combinations(settings, values["omega"]) if omega_elements else []
    if sdc == "D":
        notes.append(
            f"{CLAUSES['irregularForces']}: in Category D with plan irregularity Type I.a, I.b, "
            "II, III or IV or vertical Type IV, the forces of diaphragm-to-vertical-element and "
            "collector connections go up 25 % (unless the collectors take the Ω0 combinations); "
            "SAEngine designs no diaphragm connections"
        )
    if sdc in ("C", "D"):
        notes.append(
            f"{CLAUSES['collectors']}: collectors, their splices and connections take the Ω0 "
            "combinations; SAEngine cannot find collectors: mark them (omegaCombinations "
            "'collector')"
        )
    notes.append(
        f"{CLAUSES['phi']}: strength reduction factors of Sec 6.2.3.2-6.2.3.4, as the design "
        "uses already"
    )
    notes.append(
        f"{CLAUSES['analysis']}(c): members below the base that carry earthquake forces to the "
        "foundation follow Sec 8.3 too"
    )
    return {
        "system": system,
        "systemName": bnbc.STRUCTURAL_SYSTEMS[system].name
        if system in bnbc.STRUCTURAL_SYSTEMS
        else system,
        "systemRow": row.row if row else None,
        "sdc": sdc,
        "zone": zone,
        "R": values["R"],
        "Cd": values["Cd"],
        "Omega0": values["omega"],
        "frameType": frame_type,
        "detailingLevel": level,
        "systemFrameType": row.frame if row else None,
        "requiredFrameType": required,
        "height": None if height is None else round(height, 3),
        "applies": applies,
        "checks": checks,
        "members": members,
        "discontinuities": discontinuities(building, objects, materials),
        "omega": {
            "elements": omega_elements,
            "combinations": combinations,
        },
        "notes": notes,
        "clauses": dict(CLAUSES),
    }

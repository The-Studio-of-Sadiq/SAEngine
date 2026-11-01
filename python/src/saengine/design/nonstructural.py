"""Seismic design of nonstructural components and the anchorage of walls: the one home of the
component forces.

Everything code-dependent comes from the active code pack's ``nonstructural`` table (its
clauses in the table's ``source`` / ``sources``); this module only computes. The bnbc2020 pack
reads BNBC 2020 Part 6 Sec 2.5.15 and Sec 1.7.3.2(b), 1.7.3.6.

**Force** (method ``amplifiedHeight``, the only one so far)::

    a  = groundFactor · Z · S                         (Z, S: the seismic table's)
    F  = αc · a · Wc · Ic / Rc · (1 + heightFactor · z/h),   z ≥ 0, z/h ≤ zOverHMax
    minFactor · a · Wc · Ic ≤ F ≤ maxFactor · a · Wc · Ic
    Fv = ± verticalFactor · a · Wc (concurrent)

applied at the component's centre of gravity, in two orthogonal horizontal directions. αc and
Rc are the component's row; Ic the pack's ``importance`` (essential or default). A component on
vibration isolators whose bumper clearance exceeds ``isolation.clearance`` is designed for
``isolation.factor`` × F. The pack's exemptions (by group, Seismic Design Category, Ic, flexible
connections, mounting height and weight) say which components need no design.

**Relative displacements** (method ``allowableDrift``): Dc = δx − δy on one structure, limited to
(hx − hy)·Δa/hsx; between two structures Dc = |δxA| + |δyB| ≤ hx·ΔaA/hsx + hy·ΔaB/hsx, with
Δa/hsx the allowable storey drift ratio of the seismic table.

**Exterior panels**: connection bodies for ``connections.bodyFactor`` × F, fasteners for
``fastenerFactor`` × F, joints that allow max(``jointDriftFactor`` × storey drift,
``jointMinimum``).

**Wall anchorage**: concrete and masonry structural walls are anchored to each floor and the roof
for the larger of their out-of-plane force and ``anchorage.minimum`` per metre of wall, and are
designed for bending between anchors farther apart than ``anchorage.maxSpacing``.

Users: 07 MEP (:mod:`saengine.mep.loads`, :mod:`saengine.mep.report`) for the equipment and
tanks, the architecture walls and curtain walls (:func:`architecture_components`), and the
structural walls of the building model (:func:`structural_wall_anchorage`).
:func:`report_section` gives the calculation report's rows.

Units: weights and forces in kN, lengths in mm unless named ``*_m``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.codes import context as code_context

__all__ = [
    "Component",
    "Ground",
    "allowable_drift_ratio",
    "anchorage",
    "architecture_components",
    "component_force",
    "component_row",
    "connection_forces",
    "covered",
    "equipment_component",
    "equipment_force",
    "exemption",
    "forces_of",
    "ground_motion",
    "importance",
    "interaction_check",
    "joint_movement",
    "project_components",
    "relative_displacement",
    "relative_displacement_between",
    "report_section",
    "structural_wall_anchorage",
]

TABLE = "nonstructural"
MM = 1e-3


def _table(pack: Any = None) -> Any:
    if pack is not None:
        return pack.table(TABLE)
    return code_context.pack_table(TABLE)


def covered(pack: Any = None) -> bool:
    """Whether the active pack (or ``pack``) has the nonstructural table."""
    try:
        target = pack if pack is not None else code_context.current()
        return bool(target.has(TABLE))
    except Exception:  # noqa: BLE001 - no pack in force: the built-in default has it
        return True


# ───────────────────────────────────────── inputs ─────────────────────────────────────────


@dataclass
class Ground:
    """The site's ground motion for the components: ``a`` [g] = groundFactor·Z·S, the Seismic
    Design Category, the roof height ``h`` above the base [mm] and the base level [mm]."""

    a: float
    Z: float
    S: float
    sdc: str | None
    h: float
    base: float = 0.0
    occupancy: str = "II"
    drift_ratio: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Component:
    """One component to design. ``weight`` Wc [kN] (for a wall or distribution run, the whole
    item; ``length`` [mm] gives it per metre too); ``z`` the height of its attachment above the
    base [mm]; ``mount`` its height above its floor [mm] (exemptions)."""

    id: str
    name: str
    row: str
    weight: float
    z: float
    essential: bool = False
    length: float | None = None
    area: float | None = None
    flexible: bool = False
    mount: float = 0.0
    isolator_clearance: float | None = None
    on_structural_wall: bool = False
    source: str = ""
    story: str = ""
    basis: str = ""


def ground_motion(settings: Any, building: Any = None, pack: Any = None) -> Ground:
    """The :class:`Ground` of a project: a = groundFactor·Z·S (Z of the location or entered, S of
    the settings' site class, which should be the one the analysis uses:
    :func:`saengine.library.settings.resolve_site_class`), the Seismic Design Category, and the
    roof height from the building model's stories (0 without one)."""
    from saengine.design.seismic_rules import seismic_design_category
    from saengine.library.settings import code_pack, derived

    pack = pack or code_pack(settings)
    table = pack.table(TABLE)
    seismic = pack.table("seismic")
    z = float(derived(settings)["Z"] or 0.0)
    site = seismic.siteClasses.get(settings.site.siteClass)
    s = float(site.S) if site is not None else 1.0
    notes: list[str] = []
    if site is None:
        notes.append(f"site class {settings.site.siteClass} has no soil factor: S = 1.0 taken")
    try:
        sdc, _ = seismic_design_category(settings)
    except Exception:  # noqa: BLE001 - a missing zone: no category, nothing exempt
        sdc = None
    levels = [float(s.elevation) for s in getattr(building, "stories", []) or []]
    base = min(levels) if levels else 0.0
    h = (max(levels) - base) if levels else 0.0
    occupancy = settings.occupancy.category
    return Ground(
        a=table.force.groundFactor * z * s,
        Z=z,
        S=s,
        sdc=sdc,
        h=h,
        base=base,
        occupancy=occupancy,
        drift_ratio=allowable_drift_ratio(occupancy, sdc),
        notes=notes,
    )


def allowable_drift_ratio(occupancy: str, sdc: str | None = None, **conditions: Any) -> float:
    """Δa/hsx of the seismic table for the occupancy (its drift table's first matching row)."""
    from saengine.fem.seismic_design import drift_limit

    return float(drift_limit(occupancy, sdc, **conditions)["ratio"])


# ───────────────────────────────────────── the force ─────────────────────────────────────────


def component_row(row: str, pack: Any = None) -> Any:
    """The pack's row ``row`` (raises KeyError naming the known rows)."""
    rows = _table(pack).components
    if row not in rows:
        raise KeyError(f"no nonstructural component '{row}' in the code pack")
    return rows[row]


def importance(essential: bool, pack: Any = None) -> float:
    """Ic: the pack's essential value for an essential component, else its default."""
    rule = _table(pack).importance
    return float(rule.essential if essential else rule.default)


def _condition_holds(cond: Any, item: Component, row: Any) -> bool:
    if cond.flexibleConnections is not None and cond.flexibleConnections != item.flexible:
        return False
    if cond.distribution is not None and cond.distribution != row.distribution:
        return False
    if cond.maxMountHeight is not None and item.mount > cond.maxMountHeight:
        return False
    weight_n = item.weight * 1e3
    if cond.maxWeight is not None and weight_n > cond.maxWeight:
        return False
    if cond.maxWeightPerLength is not None:
        if not item.length:
            return False
        if weight_n / (item.length * MM) > cond.maxWeightPerLength:
            return False
    return True


def exemption(item: Component, sdc: str | None, pack: Any = None) -> Any | None:
    """The pack's exemption that applies to ``item`` in category ``sdc``, or None (also None
    without a category: nothing is exempted on an unknown site)."""
    if sdc is None:
        return None
    table = _table(pack)
    row = table.components[item.row]
    ic = importance(item.essential, pack)
    for rule in table.exemptions:
        if row.group not in rule.groups or sdc not in rule.categories:
            continue
        if rule.importance is not None and abs(ic - rule.importance) > 1e-9:
            continue
        if rule.exceptParapetsOnStructuralWalls and row.parapet and item.on_structural_wall:
            continue
        if not _condition_holds(rule, item, row):
            continue
        if rule.alternatives and not any(_condition_holds(c, item, row) for c in rule.alternatives):
            continue
        return rule
    return None


def component_force(item: Component, ground: Ground, pack: Any = None) -> dict[str, Any]:
    """The design force of one component: ``{"id", "name", "row", "label", "group", "alpha",
    "R", "Ic", "Wc", "z", "h", "zOverH", "raw", "lower", "upper", "Fc", "factor" (isolators),
    "design" (factor × Fc), "Fv", "perMetre" (design kN/m when the length is known),
    "pressure" (kPa over ``area``), "exempt" (the exemption's id) and "exemptLabel", "clause",
    "note", "basis", "story", "source"}``."""
    table = _table(pack)
    rule = table.force
    row = component_row(item.row, pack)
    ic = importance(item.essential, pack)
    wc = float(item.weight)
    a = ground.a
    z = max(0.0, float(item.z))
    ratio = min(z / ground.h, rule.zOverHMax) if ground.h > 0 else rule.zOverHMax
    raw = row.alpha * a * wc * ic / row.R * (1.0 + rule.heightFactor * ratio)
    lower = rule.minFactor * a * wc * ic
    upper = rule.maxFactor * a * wc * ic
    fc = min(max(raw, lower), upper)
    factor = 1.0
    notes: list[str] = []
    if row.isolated and table.isolation is not None:
        gap = item.isolator_clearance
        if gap is None or gap > table.isolation.clearance:
            factor = table.isolation.factor
            notes.append(
                f"on isolators, clearance {'not given' if gap is None else f'{gap:g} mm'} > "
                f"{table.isolation.clearance:g} mm: {factor:g} × {rule.symbols.get('force', 'F')}"
            )
    design = factor * fc
    found = exemption(item, ground.sdc, pack)
    out: dict[str, Any] = {
        "id": item.id,
        "name": item.name,
        "row": item.row,
        "label": row.label,
        "heading": row.heading,
        "group": row.group,
        "alpha": row.alpha,
        "R": row.R,
        "Ic": ic,
        "a": round(a, 4),
        "Wc": round(wc, 3),
        "z": round(z, 1),
        "h": round(ground.h, 1),
        "zOverH": round(ratio, 3),
        "raw": round(raw, 3),
        "lower": round(lower, 3),
        "upper": round(upper, 3),
        "Fc": round(fc, 3),
        "factor": factor,
        "design": round(design, 3),
        "Fv": round(rule.verticalFactor * a * wc, 3),
        "perMetre": round(design / (item.length * MM), 3) if item.length else None,
        "pressure": round(design / (item.area * MM * MM), 3) if item.area else None,
        "exempt": found.id if found is not None else None,
        "exemptLabel": found.label if found is not None else "",
        "clause": rule.source,
        "note": "; ".join(notes),
        "basis": item.basis,
        "story": item.story,
        "source": item.source,
    }
    return out


# ─────────────────────────────── relative displacements, joints ───────────────────────────────


def relative_displacement(
    delta_x: float, delta_y: float, hx: float, hy: float, drift_ratio: float
) -> dict[str, float | bool]:
    """Two points on one structure (upper at hx, lower at hy [mm], deflections [mm]):
    ``{"Dc", "max", "ok"}`` with Dc = δx − δy (its size) and max = (hx − hy)·Δa/hsx."""
    dc = abs(float(delta_x) - float(delta_y))
    limit = abs(float(hx) - float(hy)) * float(drift_ratio)
    return {"Dc": round(dc, 3), "max": round(limit, 3), "ok": dc <= limit + 1e-9}


def relative_displacement_between(
    delta_xa: float,
    delta_yb: float,
    hx: float,
    hy: float,
    drift_ratio_a: float,
    drift_ratio_b: float,
) -> dict[str, float | bool]:
    """Two points on separate structures A (at hx) and B (at hy): Dc = |δxA| + |δyB| ≤
    hx·ΔaA/hsx + hy·ΔaB/hsx."""
    dc = abs(float(delta_xa)) + abs(float(delta_yb))
    limit = float(hx) * float(drift_ratio_a) + float(hy) * float(drift_ratio_b)
    return {"Dc": round(dc, 3), "max": round(limit, 3), "ok": dc <= limit + 1e-9}


def joint_movement(storey_drift: float, pack: Any = None) -> float:
    """The relative movement exterior panel joints and connections allow [mm]: the larger of
    jointDriftFactor × the storey drift [mm] and jointMinimum."""
    rule = _table(pack).connections
    if rule is None:
        return float(storey_drift)
    return max(rule.jointDriftFactor * abs(float(storey_drift)), rule.jointMinimum)


def connection_forces(force: float, pack: Any = None) -> dict[str, float]:
    """Exterior panel connections: ``{"body", "fasteners"}`` [kN] for a component force."""
    rule = _table(pack).connections
    if rule is None:
        return {"body": float(force), "fasteners": float(force)}
    return {"body": rule.bodyFactor * force, "fasteners": rule.fastenerFactor * force}


def interaction_check(
    component_weights: Iterable[float], seismic_weight: float, pack: Any = None
) -> dict[str, Any] | None:
    """Whether the supported components (flexible ones: period over the pack's) weigh more than
    the pack's share of the total seismic weight W: ``{"share", "limit", "interaction"}``."""
    rule = _table(pack).interaction
    if rule is None or seismic_weight <= 0:
        return None
    share = sum(component_weights) / seismic_weight
    return {"share": round(share, 4), "limit": rule.share, "interaction": share > rule.share}


# ─────────────────────────────────────── wall anchorage ───────────────────────────────────────


def anchorage(
    force_per_metre: float, spacing: float | None = None, pack: Any = None
) -> dict[str, Any]:
    """Anchorage of a concrete or masonry structural wall at a floor or roof: ``{"demand"
    (kN/m), "minimum", "design" (the larger), "governs" ("force" | "minimum"), "bending"
    (anchors farther apart than the limit: the wall spans between them)}``."""
    rule = _table(pack).anchorage
    minimum = rule.minimum if rule is not None else 0.0
    design = max(float(force_per_metre), minimum)
    bending = bool(rule is not None and spacing is not None and spacing > rule.maxSpacing)
    return {
        "demand": round(float(force_per_metre), 3),
        "minimum": minimum,
        "design": round(design, 3),
        "governs": "force" if force_per_metre >= minimum else "minimum",
        "bending": bending,
        "maxSpacing": rule.maxSpacing if rule is not None else None,
    }


# ───────────────────────────────────── items of a project ─────────────────────────────────────


def equipment_component(item: Any, pack: Any = None) -> str:
    """The row of a piece of equipment: its own ``component`` when the pack has it, else its
    kind's default."""
    table = _table(pack)
    own = getattr(item, "component", None)
    if own and own in table.components:
        return own
    d = table.defaults
    return d.equipmentKinds.get(getattr(item, "kind", "other"), d.equipment)


def equipment_force(
    item: Any, ground: Ground, elevations: Mapping[str, float], pack: Any = None
) -> dict[str, Any]:
    """The design force of a piece of 07 MEP equipment (:class:`saengine.library.mep.Equipment`,
    its operating weight, at its story's level, a plinth's height as its mounting height)."""
    level = elevations.get(item.story)
    z = (level - ground.base) if level is not None else ground.h
    plinth = getattr(item, "plinth", None)
    mount = float(plinth.height) if plinth is not None else 0.0
    row = equipment_component(item, pack)
    own = getattr(item, "component", None)
    notes = []
    if own and own != row:
        notes.append(f"component '{own}' is not in the code pack: by its kind")
    result = component_force(
        Component(
            id=item.id,
            name=item.name or item.id,
            row=row,
            weight=float(item.operatingWeight),
            z=z,
            essential=bool(getattr(item, "essential", False)),
            flexible=bool(getattr(item, "flexibleConnections", False)),
            mount=mount,
            isolator_clearance=getattr(item, "isolatorClearance", None),
            story=item.story,
            source="equipment",
            basis="operating weight at its floor",
        ),
        ground,
        pack,
    )
    if level is None:
        notes.append("its story is not in the building model: at the roof")
    if notes:
        result["note"] = "; ".join(n for n in [result["note"], *notes] if n)
    return result


def _top_story(elevations: Mapping[str, float]) -> str | None:
    return max(elevations, key=lambda k: elevations[k]) if elevations else None


def architecture_components(
    arch: Any, ground: Ground, elevations: Mapping[str, float], pack: Any = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """The design forces of the architecture's walls and curtain walls, and notes.

    A wall's Wc is its type's weight per m² × its height × its length (openings not deducted:
    conservative); its attachment height z is its top for a wall between floors (the upper
    of its two attachments, the larger force) and its bottom for a wall with no story above,
    which is a parapet by default (attached at its base). ``perMetre`` is the force per metre
    of wall; its anchorage to each floor carries half of it (a wall spanning between floors),
    a parapet's base all of it."""
    from saengine.library import architecture as arch_lib

    table = _table(pack)
    d = table.defaults
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    top_story = _top_story(elevations)
    wall_types = {t.id: t for t in arch.wallTypes}
    curtain_types = {t.id: t for t in arch.curtainWallTypes}
    items = [(w, wall_types.get(w.type), False) for w in arch.walls]
    items += [(w, curtain_types.get(w.type), True) for w in arch.curtainWalls]
    for wall, wall_type, curtain in items:
        if wall_type is None:
            notes.append(f"{wall.id}: its type {wall.type} is not defined")
            continue
        levels = arch_lib.wall_levels(wall, dict(elevations))
        if levels is None:
            notes.append(
                f"{wall.id}: its height is not known (a wall with no story above needs a height)"
            )
            continue
        bottom, top = levels
        length = sum(math.dist(a, b) for a, b in zip(wall.path, wall.path[1:], strict=False))
        height = top - bottom
        if length <= 0 or height <= 0:
            continue
        rises_to_level = any(abs(top - z) < 1.0 for z in elevations.values())
        cantilever = wall.base == top_story or not rises_to_level
        default = d.curtainWall if curtain else d.parapet if cantilever else d.interiorWall
        row = wall.component if wall.component in table.components else default
        if wall.component and wall.component != row:
            notes.append(f"{wall.id}: component '{wall.component}' is not in the code pack")
        parapet = table.components[row].parapet or (cantilever and not curtain)
        z = (bottom if parapet else top) - ground.base
        weight = wall_type.weight * height * MM * length * MM
        result = component_force(
            Component(
                id=wall.id,
                name=f"{'Curtain wall' if curtain else 'Wall'} {wall.id} ({wall_type.id})",
                row=row,
                weight=weight,
                z=z,
                essential=wall.essential,
                length=length,
                area=length * height,
                on_structural_wall=wall.structuralRef is not None,
                story=wall.base,
                source="curtainWall" if curtain else "wall",
                basis=(
                    f"{wall_type.weight:.2f} kN/m² × {height * MM:.2f} m × {length * MM:.2f} m, "
                    f"attached at {'its base' if parapet else 'its top'}"
                ),
            ),
            ground,
            pack,
        )
        share = 1.0 if parapet else 0.5
        result["height"] = round(height, 1)
        result["anchorage"] = (
            round(share * result["perMetre"], 3) if result["perMetre"] is not None else None
        )
        result["anchorageShare"] = share
        if curtain or table.components[row].exterior:
            result["connections"] = {
                k: round(v, 3) for k, v in connection_forces(result["design"], pack).items()
            }
            if ground.drift_ratio is not None:
                drift = ground.drift_ratio * height
                result["joint"] = round(joint_movement(drift, pack), 1)
                result["jointBasis"] = (
                    f"at the allowable storey drift {ground.drift_ratio:g} hsx "
                    f"= {drift:.1f} mm (the analysed drift may be used instead)"
                )
        out.append(result)
    return out, notes


def structural_wall_anchorage(
    building: Any,
    objects: Any,
    materials: Any,
    ground: Ground,
    pack: Any = None,
    anchor_spacing: float | None = None,
) -> list[dict[str, Any]]:
    """The anchorage of each concrete or masonry structural wall of the building model to the
    floor or roof at its top: its out-of-plane force (the pack's ``defaults.structuralWall``
    row, Wc its thickness × density × height × length, attached at its top), half of it per
    metre at the top, against the pack's least anchorage force; ``anchor_spacing`` [mm] flags
    bending between anchors."""
    table = _table(pack)
    row = table.defaults.structuralWall
    types = {o.id: o for o in getattr(objects, "objects", [])}
    mats = {m.id: m for m in getattr(materials, "materials", [])}
    out: list[dict[str, Any]] = []
    for element in getattr(building, "elements", []):
        if getattr(element, "kind", "") != "wall":
            continue
        wall_type = types.get(element.type)
        if wall_type is None or not getattr(wall_type, "structural", True):
            continue
        material = mats.get(getattr(wall_type, "material", None))
        raw = getattr(material, "category", "") if material is not None else ""
        category = str(getattr(raw, "value", raw))
        if material is not None and category not in ("concrete", "masonry"):
            continue
        density = getattr(getattr(material, "mechanical", None), "density", None) or 2400.0
        length = math.dist(element.start, element.end)
        height = float(element.top) - float(element.bottom)
        if length <= 0 or height <= 0:
            continue
        weight = wall_type.thickness * MM * density * 9.80665e-3 * height * MM * length * MM
        result = component_force(
            Component(
                id=element.id,
                name=f"Wall {element.id} ({element.type})",
                row=row,
                weight=weight,
                z=float(element.top) - ground.base,
                length=length,
                area=length * height,
                source="structuralWall",
                basis=(
                    f"{wall_type.thickness:g} mm × {density:g} kg/m³ × {height * MM:.2f} m × "
                    f"{length * MM:.2f} m, at its top"
                ),
            ),
            ground,
            pack,
        )
        result["exempt"] = None  # Sec 1.7.3.6 has no exemption: the minimum always applies
        result["exemptLabel"] = ""
        demand = 0.5 * (result["perMetre"] or 0.0)
        result["anchorage"] = anchorage(demand, anchor_spacing, pack)
        result["height"] = round(height, 1)
        out.append(result)
    return out


# ──────────────────────────────────── the project and report ────────────────────────────────────


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def project_components(root: str | Path, pack: Any = None) -> dict[str, Any]:
    """The components of a project: ``{"covered", "ground" (a, Z, S, sdc, h, driftRatio),
    "equipment", "walls", "structuralWalls", "notes", "clause", "pack"}``. Reads the settings
    (site class resolved as the analysis does), the building model, the architecture, 07 MEP
    (its equipment and its disciplines' tanks and plant) and the materials and objects."""
    from saengine.library.bim import BuildingModel
    from saengine.library.settings import (
        ProjectSettings,
        code_pack,
        read_soil_text,
        resolve_site_class,
    )

    root = Path(root)
    notes: list[str] = []
    text = _read(root, "02 Project Settings/project-settings.json")
    if text is None:
        return {"covered": False, "notes": ["no project settings"]}
    entered = ProjectSettings.model_validate_json(text)
    settings, _ = resolve_site_class(entered, read_soil_text(root))
    pack = pack or code_pack(settings)
    if not pack.has(TABLE):
        return {
            "covered": False,
            "pack": pack.edition or pack.name,
            "notes": ["the code pack has no nonstructural component table"],
        }
    bim_text = _read(root, "06 BIM/bim.json")
    building = BuildingModel.model_validate_json(bim_text) if bim_text else None
    ground = ground_motion(settings, building, pack)
    notes += ground.notes
    elevations = {s.id: float(s.elevation) for s in getattr(building, "stories", []) or []}
    equipment: list[dict[str, Any]] = []
    walls: list[dict[str, Any]] = []
    structural: list[dict[str, Any]] = []
    materials = objects = None
    try:
        from saengine.library.materials import MaterialLibrary
        from saengine.library.objects import ObjectLibrary

        mtext = _read(root, "03 Materials/materials.json")
        otext = _read(root, "04 Objects/objects.json")
        materials = MaterialLibrary.model_validate_json(mtext) if mtext else None
        objects = ObjectLibrary.model_validate_json(otext) if otext else None
    except ValueError as error:
        notes.append(f"materials or objects not read: {str(error).splitlines()[0]}")
    mep_text = _read(root, "07 MEP/mep.json")
    if mep_text:
        try:
            from saengine.library.mep import parse as parse_mep
            from saengine.mep.loads import seismic_components

            mep = parse_mep(mep_text)
            equipment, more = seismic_components(mep, ground, elevations, materials, pack)
            notes += more
        except ValueError as error:
            notes.append(f"07 MEP not read: {str(error).splitlines()[0]}")
    arch_text = _read(root, "05 Floor Plan/architecture.json")
    if arch_text:
        try:
            from saengine.library.architecture import parse as parse_arch

            walls, more = architecture_components(parse_arch(arch_text), ground, elevations, pack)
            notes += more
        except ValueError as error:
            notes.append(f"architecture not read: {str(error).splitlines()[0]}")
    if building is not None and objects is not None:
        structural = structural_wall_anchorage(building, objects, materials, ground, pack)
    table = pack.table(TABLE)
    return {
        "covered": True,
        "pack": pack.edition or pack.name,
        "clause": table.source,
        "ground": {
            "a": round(ground.a, 4),
            "Z": ground.Z,
            "S": ground.S,
            "sdc": ground.sdc,
            "h": round(ground.h, 1),
            "driftRatio": ground.drift_ratio,
            "groundFactor": table.force.groundFactor,
        },
        "equipment": equipment,
        "walls": walls,
        "structuralWalls": structural,
        "notes": notes,
    }


def _f(value: Any, digits: int = 2) -> str:
    if value is None:
        return "–"
    return f"{float(value):.{digits}f}"


def _force_row(r: Mapping[str, Any]) -> list[str]:
    status = f"exempt ({r['exempt']})" if r.get("exempt") else _f(r["design"])
    return [
        str(r["name"]),
        str(r.get("story", "")),
        str(r["label"]),
        f"{_f(r['alpha'], 2)} / {_f(r['R'], 1)} / {_f(r['Ic'], 1)}",
        _f(r["Wc"]),
        _f(r["zOverH"], 2),
        _f(r["Fc"]),
        status,
        _f(r["Fv"]),
    ]


def report_section(root: str | Path, pack: Any = None) -> dict[str, Any] | None:
    """The calculation report's section on nonstructural components (for
    :mod:`saengine.report.build` to place): ``{"title", "intro", "headers", "rows" (equipment,
    walls, curtain walls), "anchorageHeaders", "anchorage" (structural walls), "notes",
    "clauses"}``; None when the project has no components at all. A pack without the table
    gives a section that says so."""
    found = project_components(root, pack)
    if not found.get("covered"):
        if not found.get("pack"):
            return None
        return {
            "title": "Nonstructural components",
            "intro": f"Not covered by the code pack {found['pack']}.",
            "headers": [],
            "rows": [],
            "anchorageHeaders": [],
            "anchorage": [],
            "notes": found.get("notes", []),
            "clauses": [],
        }
    items = [*found["equipment"], *found["walls"]]
    if not items and not found["structuralWalls"]:
        return None
    g = found["ground"]
    table = (pack or _pack_of(root)).table(TABLE)
    sym = table.force.symbols
    intro = (
        f"{table.force.source}. Site: {sym.get('ground', 'a')} = {g['groundFactor']:g} × Z × S = "
        f"{g['groundFactor']:g} × {g['Z']:g} × {g['S']:g} = {g['a']:.3f} g; Seismic Design "
        f"Category {g['sdc'] or '–'}; roof height h = {g['h'] * MM:.2f} m. {table.force.note}"
    )
    headers = [
        "Component",
        "Story",
        "Row",
        " / ".join(sym.get(k, k) for k in ("amplification", "reduction", "importance")),
        f"{sym.get('weight', 'W')} (kN)",
        "z/h",
        f"{sym.get('force', 'F')} (kN)",
        "Design (kN)",
        "Vertical ± (kN)",
    ]
    rows = [_force_row(r) for r in items]
    anchorage_rows = []
    for r in found["structuralWalls"]:
        a = r["anchorage"]
        anchorage_rows.append(
            [
                str(r["name"]),
                _f(r["perMetre"]),
                _f(a["demand"]),
                _f(a["minimum"]),
                _f(a["design"]),
                "minimum" if a["governs"] == "minimum" else "force",
            ]
        )
    notes = list(found["notes"])
    for r in found["walls"]:
        if r.get("anchorage") is not None:
            notes.append(
                f"{r['name']}: {_f(r['perMetre'])} kN/m out of plane, "
                f"{_f(r['anchorage'])} kN/m to each support ({r['basis']})"
            )
        if r.get("connections"):
            c = r["connections"]
            joint = f", joints {r['joint']:g} mm {r['jointBasis']}" if r.get("joint") else ""
            notes.append(
                f"{r['name']}: connection bodies {_f(c['body'])} kN, fasteners "
                f"{_f(c['fasteners'])} kN{joint}"
            )
    for r in items:
        if r.get("note"):
            notes.append(f"{r['name']}: {r['note']}")
    notes.append(table.defaults.note)
    clauses = [table.source, *table.sources.values()]
    for part in (table.importance, table.anchorage, table.connections, table.isolation):
        if part is not None and part.source:
            clauses.append(part.source)
    return {
        "title": "Nonstructural components",
        "intro": intro,
        "headers": headers,
        "rows": rows,
        "anchorageHeaders": [
            "Structural wall",
            "Out of plane (kN/m)",
            "At the top (kN/m)",
            "Least (kN/m)",
            "Anchorage (kN/m)",
            "Governs",
        ],
        "anchorage": anchorage_rows,
        "notes": notes,
        "clauses": clauses,
    }


def _pack_of(root: str | Path) -> Any:
    from saengine.library.settings import ProjectSettings, code_pack

    text = _read(Path(root), "02 Project Settings/project-settings.json")
    settings = ProjectSettings.model_validate_json(text) if text else ProjectSettings()
    return code_pack(settings)


def forces_of(results: Sequence[Mapping[str, Any]]) -> float:
    """Sum of the design forces of ``results`` that are not exempt [kN]."""
    return sum(float(r["design"]) for r in results if not r.get("exempt"))

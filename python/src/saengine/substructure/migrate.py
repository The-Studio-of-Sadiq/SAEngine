"""Move the footings drawn in the building model into the substructure (a one-time migration).

Before Part 9, footings were drawn in the floor plan (Footing tool) as building-model
``FootingElement``s of ``Footing`` (or ``PileCap``) object types, and Part 8 designed them. Each
becomes a foundation of ``09 Substructure/substructure.json`` with the sizes and reinforcement
of its object type, its founding level at the underside of the drawn footing and the columns
whose base lies inside its plan outline (each column on the first footing that holds it, as
Part 8 took them). The building model and the object types are left as they are.

:func:`upgrade_project` brings a ``substructure.json`` of an earlier version up to date: its pile
caps' pile offsets become piles placed in plan.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from saengine.library.bim import BuildingModel, ColumnElement, FootingElement, WallElement
from saengine.library.objects import CircleProfile, Footing, ObjectLibrary, Pile, PileCap
from saengine.library.substructure import (
    SUBSTRUCTURE_FILE,
    Substructure,
    parse,
    pile_layout_problem,
)

#: Clear distance from a migrated pile to the edge of its cap [mm].
EDGE = 150.0


def _bases(building: BuildingModel) -> list[Any]:
    """The lowest column at each plan position, and every wall at its lowest level: the
    elements that stand on foundations. Columns starting above the lowest column bottom stand on
    the floor below (a column on a transfer beam), not on a footing."""
    lowest: dict[tuple[int, int], ColumnElement] = {}
    columns = [e for e in building.elements if isinstance(e, ColumnElement)]
    base = min((c.bottom for c in columns), default=0.0)
    for e in columns:
        if e.bottom <= base + 1:
            key = (round(e.position[0]), round(e.position[1]))
            if key not in lowest or e.bottom < lowest[key].bottom:
                lowest[key] = e
    walls = [e for e in building.elements if isinstance(e, WallElement)]
    if walls:
        bottom = min(w.bottom for w in walls)
        walls = [w for w in walls if abs(w.bottom - bottom) < 1]
    return [*lowest.values(), *walls]


def pile_layout(count: int, length: float, width: float, diameter: float) -> list[list[float]]:
    """``count`` pile positions on a regular grid inside a cap ``length`` x ``width`` [mm], the
    piles' faces :data:`EDGE` from the cap's edges (rows along the longer side)."""
    if count <= 1:
        return [[0.0, 0.0]]
    long_side = max(length, width)
    short_side = min(length, width)
    across = max(1, round(math.sqrt(count * short_side / long_side)))
    along = math.ceil(count / across)
    reach_l = max(long_side / 2 - diameter / 2 - EDGE, 0.0)
    reach_s = max(short_side / 2 - diameter / 2 - EDGE, 0.0)
    points: list[list[float]] = []
    for row in range(across):
        in_row = min(along, count - row * along)
        y = 0.0 if across == 1 else -reach_s + 2 * reach_s * row / (across - 1)
        for k in range(in_row):
            x = 0.0 if in_row == 1 else -reach_l + 2 * reach_l * k / (in_row - 1)
            points.append(
                [round(x, 1), round(y, 1)] if length >= width else [round(y, 1), round(x, 1)]
            )
    return points


def migrate(
    building: BuildingModel, objects: ObjectLibrary, existing: Substructure | None = None
) -> tuple[Substructure, list[str]]:
    """The substructure with the building model's footings added as foundations (to
    ``existing``, whose foundations stay as they are), and notes on what was done."""
    types = {o.id: o for o in objects.objects}
    data = (existing or Substructure()).model_dump(mode="json", by_alias=True, exclude_none=True)
    taken = {f["id"] for f in data["foundations"]}
    carried = {c for f in data["foundations"] for c in f.get("columns", [])}
    pile_ids = {p["id"] for p in data["pileTypes"]}
    notes: list[str] = []
    bases = _bases(building)
    for footing in (e for e in building.elements if isinstance(e, FootingElement)):
        object_type = types.get(footing.type)
        if footing.id in taken:
            notes.append(f"{footing.id}: already in 9 Substructure; left as it is there")
            continue
        if not isinstance(object_type, Footing | PileCap):
            notes.append(f"{footing.id}: object type '{footing.type}' is not a footing; left out")
            continue
        theta = math.radians(footing.rotation)
        cos, sin = math.cos(theta), math.sin(theta)
        half_l, half_w = object_type.length / 2, object_type.width / 2
        columns: list[str] = []
        for element in bases:
            if isinstance(element, ColumnElement):
                point = element.position
            else:
                point = [(a + b) / 2 for a, b in zip(element.start, element.end, strict=True)]
            dx, dy = point[0] - footing.position[0], point[1] - footing.position[1]
            u, v = dx * cos + dy * sin, -dx * sin + dy * cos
            if abs(u) > half_l + 1 or abs(v) > half_w + 1:
                continue
            if isinstance(element, WallElement) and not (
                isinstance(object_type, Footing) and object_type.footingType == "strip"
            ):
                continue
            if element.id in carried:
                notes.append(f"{element.id}: stands on more than one footing; kept on the first")
                continue
            columns.append(element.id)
        foundation: dict[str, Any] = {
            "id": footing.id,
            "columns": columns,
            "thickness": object_type.thickness,
            "foundingLevel": footing.elevation - object_type.thickness,
            "material": object_type.material,
            "note": f"From the footing {footing.id} ({object_type.name}) of 6 BIM.",
        }
        if object_type.reinforcement is not None:
            foundation["reinforcement"] = object_type.reinforcement.model_dump(
                mode="json", exclude_none=True
            )
        if isinstance(object_type, Footing) and object_type.footingType == "strip":
            foundation.update(
                type="strip",
                path=[
                    [footing.position[0] - half_l * cos, footing.position[1] - half_l * sin],
                    [footing.position[0] + half_l * cos, footing.position[1] + half_l * sin],
                ],
                width=object_type.width,
            )
        else:
            foundation.update(
                type="pileCap" if isinstance(object_type, PileCap) else object_type.footingType,
                center=list(footing.position[:2]),
                rotation=footing.rotation,
                length=object_type.length,
                width=object_type.width,
            )
        if isinstance(object_type, PileCap):
            pile = types.get(object_type.pile or "")
            if not isinstance(pile, Pile):
                notes.append(f"{footing.id}: its pile cap type names no pile type; left out")
                continue
            profile = pile.profile
            diameter = (
                2 * profile.radius
                if isinstance(profile, CircleProfile)
                else getattr(profile, "xDim", 0.0)
            )
            if not diameter:
                notes.append(f"{footing.id}: pile '{pile.id}' is neither round nor square")
                continue
            layout = pile_layout(
                object_type.pileCount or 1, object_type.length, object_type.width, diameter
            )
            problem = pile_layout_problem(layout, diameter, object_type.length, object_type.width)
            if problem:
                notes.append(
                    f"{footing.id}: its {len(layout)} piles do not fit in the cap ({problem}); "
                    "left out"
                )
                continue
            if pile.id not in pile_ids:
                pile_type: dict[str, Any] = {
                    "id": pile.id,
                    "kind": "bored" if pile.pileType == "bored" else "driven",
                    "diameter": diameter,
                    "length": pile.length,
                    "material": pile.material,
                }
                if pile.reinforcement is not None:
                    pile_type["reinforcement"] = pile.reinforcement.model_dump(
                        mode="json", exclude_none=True
                    )
                data["pileTypes"].append(pile_type)
                pile_ids.add(pile.id)
            foundation["pileType"] = pile.id
            foundation["piles"] = layout
            notes.append(
                f"{footing.id}: {len(foundation['piles'])} piles laid out on a regular grid; "
                "check their positions"
            )
        # Only now do its columns count as carried: a footing left out above carries none.
        carried.update(columns)
        data["foundations"].append(foundation)
        taken.add(footing.id)
        notes.append(
            f"{footing.id}: {foundation['type']} under {', '.join(columns) or 'no column'}"
        )
    return Substructure.model_validate(data), notes


def upgrade_project(project_root: str | Path) -> dict[str, Any]:
    """Rewrites the project's ``substructure.json`` when its pile caps are of the earlier format
    (a pile type and pile offsets from the cap's centre): each pile becomes a pile placed in plan
    (PL1, PL2, ...) and its cap lists them by id
    (:func:`saengine.library.substructure.upgrade_pile_caps`; a cap without a centre is placed at
    its columns' centroid, read from 6 BIM). Returns ``{"upgraded": bool, "piles": count}``;
    ``"problems"`` when it cannot be done. An invalid file is left as it is."""
    from saengine.library.substructure import column_positions, needs_upgrade, upgrade_pile_caps
    from saengine.substructure.handover import substructure_text

    root = Path(project_root)
    path = root / SUBSTRUCTURE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"upgraded": False, "piles": 0}
    if not needs_upgrade(data):
        return {"upgraded": False, "piles": 0}
    try:
        building = BuildingModel.model_validate_json(
            (root / "06 BIM" / "bim.json").read_text(encoding="utf-8")
        )
        positions = column_positions(building)
    except (OSError, ValueError):
        positions = {}
    try:
        upgraded = upgrade_pile_caps(data, positions)
        Substructure.model_validate(upgraded)
    except ValueError as error:
        return {"upgraded": False, "piles": 0, "problems": [str(error)]}
    path.write_text(substructure_text(upgraded), encoding="utf-8", newline="\n")
    return {"upgraded": True, "piles": len(upgraded["piles"]) - len(data.get("piles") or [])}


def migrate_project(project_root: str | Path) -> dict[str, Any]:
    """:func:`migrate` for the project at ``project_root``: ``{"substructure": the file's new
    content (JSON-ready), "notes", "count": foundations added}``. Nothing is written."""
    root = Path(project_root)
    building = BuildingModel.model_validate_json(
        (root / "06 BIM" / "bim.json").read_text(encoding="utf-8")
    )
    objects = ObjectLibrary.model_validate_json(
        (root / "04 Objects" / "objects.json").read_text(encoding="utf-8")
    )
    try:
        text = (root / SUBSTRUCTURE_FILE).read_text(encoding="utf-8")
    except OSError:
        text = None
    existing = parse(text)
    substructure, notes = migrate(building, objects, existing)
    added = len(substructure.foundations) - len(existing.foundations)
    return {
        "substructure": json.loads(substructure.model_dump_json(by_alias=True, exclude_none=True)),
        "notes": notes,
        "count": added,
    }

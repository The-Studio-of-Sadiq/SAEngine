"""Unified architectural types browser and office-standards library import/export.

Provides one consistent model over every architectural type category in
``05 Floor Plan/architecture.json`` (wall, door, window, finish, roof, railing, ceiling,
curtain wall, component types): duplicate, rename (cascading id changes to instances), edit
parameters, delete only when unused, and export/import a standalone ``saengine.typesLibrary/1``
JSON for office standards.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.architecture import (
    Architecture,
    CeilingType,
    CurtainMullionType,
    CurtainPanelType,
    CurtainWallType,
    DoorType,
    FinishType,
    RailingType,
    RoofType,
    WallType,
    WindowType,
)
from saengine.library.components import ComponentType
from saengine.library.labels import field_title

TYPES_LIBRARY_SCHEMA_ID = "saengine.typesLibrary/1"

TypeCategory = Literal[
    "wall",
    "door",
    "window",
    "finish",
    "roof",
    "railing",
    "ceiling",
    "curtainWall",
    "component",
]

TYPE_CATEGORIES: tuple[TypeCategory, ...] = (
    "wall",
    "door",
    "window",
    "finish",
    "roof",
    "railing",
    "ceiling",
    "curtainWall",
    "component",
)

_ARCH_FIELD: dict[TypeCategory, str] = {
    "wall": "wallTypes",
    "door": "doorTypes",
    "window": "windowTypes",
    "finish": "finishTypes",
    "roof": "roofTypes",
    "railing": "railingTypes",
    "ceiling": "ceilingTypes",
    "curtainWall": "curtainWallTypes",
    "component": "componentTypes",
}


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


_TYPE_MODELS: dict[TypeCategory, type[BaseModel]] = {
    "wall": WallType,
    "door": DoorType,
    "window": WindowType,
    "finish": FinishType,
    "roof": RoofType,
    "railing": RailingType,
    "ceiling": CeilingType,
    "curtainWall": CurtainWallType,
    "component": ComponentType,
}


class TypesLibrary(_Model):
    """Office-standards library JSON holding architectural types across all categories."""

    schema_: Literal["saengine.typesLibrary/1"] = Field(
        default=TYPES_LIBRARY_SCHEMA_ID, alias="schema"
    )
    name: str = Field(default="Office Standards", min_length=1)
    wallTypes: list[WallType] = Field(default_factory=list)
    doorTypes: list[DoorType] = Field(default_factory=list)
    windowTypes: list[WindowType] = Field(default_factory=list)
    finishTypes: list[FinishType] = Field(default_factory=list)
    roofTypes: list[RoofType] = Field(default_factory=list)
    railingTypes: list[RailingType] = Field(default_factory=list)
    ceilingTypes: list[CeilingType] = Field(default_factory=list)
    curtainWallTypes: list[CurtainWallType] = Field(default_factory=list)
    curtainPanelTypes: list[CurtainPanelType] = Field(default_factory=list)
    curtainMullionTypes: list[CurtainMullionType] = Field(default_factory=list)
    componentTypes: list[ComponentType] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids_per_category(self) -> TypesLibrary:
        for cat in TYPE_CATEGORIES:
            items = getattr(self, _ARCH_FIELD[cat])
            ids = [t.id for t in items]
            dups = sorted({i for i in ids if ids.count(i) > 1})
            if dups:
                raise ValueError(f"duplicate {cat} type ids: {', '.join(dups)}")
        for label, items in (
            ("curtain panel", self.curtainPanelTypes),
            ("curtain mullion", self.curtainMullionTypes),
        ):
            ids = [t.id for t in items]
            dups = sorted({i for i in ids if ids.count(i) > 1})
            if dups:
                raise ValueError(f"duplicate {label} type ids: {', '.join(dups)}")
        return self


def _get_list(arch: Architecture, category: TypeCategory) -> list[Any]:
    field = _ARCH_FIELD[category]
    return list(getattr(arch, field, ()))


def _set_list(arch: Architecture, category: TypeCategory, items: list[Any]) -> Architecture:
    field = _ARCH_FIELD[category]
    if not hasattr(arch, field):
        if not items:
            return arch
        raise ValueError(f"architecture does not yet store '{field}' directly")
    data = arch.model_dump(mode="json", by_alias=True, exclude_none=True)
    data[field] = [
        item.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(item, BaseModel)
        else item
        for item in items
    ]
    return Architecture.model_validate(data)


def type_usages(arch: Architecture, category: TypeCategory, type_id: str) -> list[str]:
    """Ids of every instance in ``arch`` referencing ``type_id`` in ``category``."""
    if category == "wall":
        return [w.id for w in arch.walls if w.type == type_id]
    if category == "door":
        return [d.id for d in arch.doors if d.type == type_id]
    if category == "window":
        return [w.id for w in arch.windows if w.type == type_id]
    if category == "finish":
        used = [
            r.id
            for r in arch.rooms
            if type_id in (r.floorFinish, r.wallFinish, r.ceilingFinish)
        ]
        used.extend(rp.id for rp in arch.ramps if rp.finish == type_id)
        return used
    if category == "roof":
        return [r.id for r in arch.roofs if r.type == type_id]
    if category == "railing":
        return [r.id for r in arch.railings if r.type == type_id]
    if category == "ceiling":
        return [c.id for c in arch.ceilings if c.type == type_id]
    if category == "curtainWall":
        return [c.id for c in arch.curtainWalls if c.type == type_id]
    if category == "component":
        return [c.id for c in arch.components if c.type == type_id]
    return []


def list_types(
    arch: Architecture, category: TypeCategory | None = None
) -> list[dict[str, Any]]:
    """Unified list of architectural types across ``category`` (or all categories)."""
    cats = (category,) if category is not None else TYPE_CATEGORIES
    rows: list[dict[str, Any]] = []
    for cat in cats:
        for item in _get_list(arch, cat):
            used = type_usages(arch, cat, item.id)
            rows.append(
                {
                    "category": cat,
                    "id": item.id,
                    "name": item.name,
                    "usageCount": len(used),
                    "usedBy": used,
                    "data": item.model_dump(mode="json", by_alias=True, exclude_none=True),
                }
            )
    return rows


def duplicate_type(
    arch: Architecture,
    category: TypeCategory,
    type_id: str,
    *,
    new_id: str | None = None,
    new_name: str | None = None,
) -> tuple[Architecture, Any]:
    """Duplicate ``type_id`` in ``category`` with a unique id and return ``(arch, new_type)``."""
    items = _get_list(arch, category)
    source = next((t for t in items if t.id == type_id), None)
    if source is None:
        raise ValueError(f"no {category} type '{type_id}'")
    existing_ids = {t.id for t in items}
    candidate = new_id
    if not candidate:
        n = 2
        while f"{type_id}-{n}" in existing_ids:
            n += 1
        candidate = f"{type_id}-{n}"
    if candidate in existing_ids:
        raise ValueError(f"{category} type '{candidate}' already exists")
    data = source.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["id"] = candidate
    data["name"] = new_name or f"{source.name} (copy)"
    model_cls = _TYPE_MODELS[category]
    created = model_cls.model_validate(data)
    return _set_list(arch, category, [*items, created]), created


def rename_type(
    arch: Architecture,
    category: TypeCategory,
    old_id: str,
    *,
    new_id: str | None = None,
    new_name: str | None = None,
) -> Architecture:
    """Rename a type's display name and/or id, cascading ``new_id`` to all referencing instances."""
    items = _get_list(arch, category)
    source = next((t for t in items if t.id == old_id), None)
    if source is None:
        raise ValueError(f"no {category} type '{old_id}'")
    target_id = new_id or old_id
    if target_id != old_id and any(t.id == target_id for t in items):
        raise ValueError(f"{category} type '{target_id}' already exists")

    data = arch.model_dump(mode="json", by_alias=True, exclude_none=True)
    field = _ARCH_FIELD[category]
    for entry in data.get(field, []):
        if entry["id"] == old_id:
            entry["id"] = target_id
            if new_name:
                entry["name"] = new_name

    if target_id != old_id:
        if category == "wall":
            for w in data.get("walls", []):
                if w["type"] == old_id:
                    w["type"] = target_id
        elif category == "door":
            for d in data.get("doors", []):
                if d["type"] == old_id:
                    d["type"] = target_id
        elif category == "window":
            for w in data.get("windows", []):
                if w["type"] == old_id:
                    w["type"] = target_id
        elif category == "finish":
            for r in data.get("rooms", []):
                for rf in ("floorFinish", "wallFinish", "ceilingFinish"):
                    if r.get(rf) == old_id:
                        r[rf] = target_id
            for rp in data.get("ramps", []):
                if rp.get("finish") == old_id:
                    rp["finish"] = target_id
        elif category == "roof":
            for r in data.get("roofs", []):
                if r["type"] == old_id:
                    r["type"] = target_id
        elif category == "railing":
            for r in data.get("railings", []):
                if r["type"] == old_id:
                    r["type"] = target_id
        elif category == "ceiling":
            for c in data.get("ceilings", []):
                if c.get("type") == old_id:
                    c["type"] = target_id
        elif category == "curtainWall":
            for c in data.get("curtainWalls", []):
                if c["type"] == old_id:
                    c["type"] = target_id
        elif category == "component":
            for c in data.get("components", []):
                if c["type"] == old_id:
                    c["type"] = target_id

    return Architecture.model_validate(data)


def edit_type(
    arch: Architecture,
    category: TypeCategory,
    type_id: str,
    updates: dict[str, Any],
) -> Architecture:
    """Update fields/parameters of ``type_id`` in ``category`` (re-validating the architecture)."""
    if "id" in updates and updates["id"] != type_id:
        raise ValueError("use rename_type to change a type id")
    items = _get_list(arch, category)
    idx = next((i for i, t in enumerate(items) if t.id == type_id), None)
    if idx is None:
        raise ValueError(f"no {category} type '{type_id}'")
    merged = items[idx].model_dump(mode="json", by_alias=True, exclude_none=True)
    for k, v in updates.items():
        if v is None:
            merged.pop(k, None)
        else:
            merged[k] = v
    model_cls = _TYPE_MODELS[category]
    items[idx] = model_cls.model_validate(merged)
    return _set_list(arch, category, items)


def delete_type(arch: Architecture, category: TypeCategory, type_id: str) -> Architecture:
    """Delete ``type_id`` in ``category`` only if unused; raises ``ValueError`` if referenced."""
    items = _get_list(arch, category)
    if not any(t.id == type_id for t in items):
        raise ValueError(f"no {category} type '{type_id}'")
    used = type_usages(arch, category, type_id)
    if used:
        raise ValueError(
            f"cannot delete {category} type '{type_id}': in use by {', '.join(used)}"
        )
    return _set_list(arch, category, [t for t in items if t.id != type_id])


def export_types_library(
    arch: Architecture,
    name: str = "Office Standards",
    categories: Sequence[TypeCategory] | None = None,
) -> TypesLibrary:
    """Export architectural types from ``arch`` as a :class:`TypesLibrary`."""
    chosen = set(categories or TYPE_CATEGORIES)
    payload: dict[str, Any] = {"name": name}
    for cat in TYPE_CATEGORIES:
        field = _ARCH_FIELD[cat]
        if cat in chosen:
            payload[field] = [
                t.model_dump(mode="json", by_alias=True, exclude_none=True)
                for t in _get_list(arch, cat)
            ]
    if "curtainWall" in chosen:
        for sub_field in ("curtainPanelTypes", "curtainMullionTypes"):
            payload[sub_field] = [
                t.model_dump(mode="json", by_alias=True, exclude_none=True)
                for t in getattr(arch, sub_field, ())
            ]
    return TypesLibrary.model_validate(payload)


def export_types_library_json(
    arch: Architecture,
    name: str = "Office Standards",
    categories: Sequence[TypeCategory] | None = None,
) -> str:
    """Export architectural types as formatted office-standards JSON."""
    lib = export_types_library(arch, name=name, categories=categories)
    return lib.model_dump_json(indent=2, by_alias=True, exclude_none=True)


def import_types_library(
    arch: Architecture,
    source: TypesLibrary | dict[str, Any] | str,
    *,
    mode: Literal["merge", "overwrite", "replace"] = "merge",
) -> tuple[Architecture, dict[str, int]]:
    """Import a :class:`TypesLibrary` (JSON string, dict, or model) into ``arch``.

    Modes:
    - ``merge``: add types whose ids are not yet present in ``arch``; keep existing ones.
    - ``overwrite``: add new types and update existing types with matching ids.
    - ``replace``: replace each non-empty category in ``source`` with ``source``'s list
      (refuses to drop any type currently in use by instances in ``arch``).
    """
    if isinstance(source, str):
        lib = TypesLibrary.model_validate_json(source)
    elif isinstance(source, TypesLibrary):
        lib = source
    else:
        lib = TypesLibrary.model_validate(source)

    data = arch.model_dump(mode="json", by_alias=True, exclude_none=True)
    added = 0
    updated = 0
    skipped = 0

    for sub_field in ("curtainPanelTypes", "curtainMullionTypes"):
        incoming_sub = getattr(lib, sub_field)
        if not incoming_sub:
            continue
        current_list = list(data.get(sub_field, []))
        by_id = {entry["id"]: i for i, entry in enumerate(current_list)}
        incoming_dicts = [
            item.model_dump(mode="json", by_alias=True, exclude_none=True)
            for item in incoming_sub
        ]
        for d in incoming_dicts:
            if d["id"] in by_id:
                if mode in ("overwrite", "replace"):
                    current_list[by_id[d["id"]]] = d
            else:
                current_list.append(d)
                by_id[d["id"]] = len(current_list) - 1
        data[sub_field] = current_list

    for cat in TYPE_CATEGORIES:
        field = _ARCH_FIELD[cat]
        incoming = getattr(lib, field)
        if not incoming:
            continue
        if not hasattr(arch, field):
            skipped += len(incoming)
            continue
        current_list = list(data.get(field, []))
        by_id = {entry["id"]: i for i, entry in enumerate(current_list)}
        incoming_dicts = [
            item.model_dump(mode="json", by_alias=True, exclude_none=True)
            for item in incoming
        ]
        if mode == "replace":
            incoming_ids = {d["id"] for d in incoming_dicts}
            for entry in current_list:
                if entry["id"] not in incoming_ids:
                    used = type_usages(arch, cat, entry["id"])
                    if used:
                        raise ValueError(
                            f"cannot replace {cat} types: '{entry['id']}' is in use by {', '.join(used)}"
                        )
            data[field] = incoming_dicts
            added += sum(1 for d in incoming_dicts if d["id"] not in by_id)
            updated += sum(1 for d in incoming_dicts if d["id"] in by_id)
        else:
            for d in incoming_dicts:
                if d["id"] in by_id:
                    if mode == "overwrite":
                        current_list[by_id[d["id"]]] = d
                        updated += 1
                    else:
                        skipped += 1
                else:
                    current_list.append(d)
                    by_id[d["id"]] = len(current_list) - 1
                    added += 1
            data[field] = current_list

    return Architecture.model_validate(data), {
        "added": added,
        "updated": updated,
        "skipped": skipped,
    }

"""Semantic differences between two versions of a project part, in an engineer's words.

A git diff of ``floor-plan.json`` shows changed braces and commas; an engineer wants "Beam B5:
section B300x500 → B300x600" or "Column C3 added". This module compares the two JSON texts of
a part file and reports each difference against the things the part is made of (members,
materials, load combinations, boreholes, tanks, …), identified by their ids.

How it works, without a hand-written rule for every field:

* Lists of objects are matched by their identifying key (``id``, a grid line's ``label``, a
  load combination's ``name``, an SPT record's ``depth``, …), so a reordered or inserted item
  is not reported as every later item changing.
* Field names and units come from the part's Pydantic model (``saengine.library``): the JSON
  Schema ``title`` ("Compressive strength f'c") and the unit written in the field description
  ("[MPa]"), walked alongside the data. A field the model does not describe falls back to a
  readable form of its name, with a few unit fallbacks (soil depths are mm).
* Anything else, or a file that is not valid JSON, falls back to a generic JSON or text diff.

Output of :func:`diff_part`::

    {"part": "floorPlan", "title": "Floor Plan", "changes": [
        {"kind": "changed", "id": "B5", "what": "Beam B5: section B300x500 → B300x600",
         "before": "B300x500", "after": "B300x600", "path": "beams[B5].type", "file": ...},
    ], "summary": "1 change: Beam B5 changed"}

``kind`` is ``added``, ``removed`` or ``changed``. Ordering is stable: the order of the part's
own document (the newer side first, then what was removed), so the same two texts always give
the same list.
"""

from __future__ import annotations

import difflib
import importlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cache
from typing import Any

__all__ = [
    "PARTS",
    "Part",
    "diff_file",
    "diff_part",
    "diff_values",
    "part_for_path",
]


@dataclass(frozen=True)
class Part:
    """One part of a project: its id, folder and main file (mirrors the workbench's table)."""

    id: str
    folder: str
    main_file: str | None
    title: str


# Keep in step with PROJECT_PARTS / STRUCTURE_PART in
# workbench/src/vs/workbench/services/saengineProject/common/saengineProject.ts.
PARTS: tuple[Part, ...] = (
    Part("soil", "01 Soil Report", "soil-report.json", "Soil Report"),
    Part("settings", "02 Project Settings", "project-settings.json", "Project Settings"),
    Part("materials", "03 Materials", "materials.json", "Materials"),
    Part("objects", "04 Objects", "objects.json", "Objects"),
    Part("floorPlan", "05 Floor Plan", "floor-plan.json", "Floor Plan"),
    Part("structure", "05 Structural Model", "structure.json", "Structural Model"),
    Part("bim", "06 BIM", "bim.json", "BIM"),
    Part("mep", "07 MEP", "mep.json", "MEP"),
    Part("fem", "08 FEM", "model.osmodel", "FEM"),
    Part("substructure", "09 Substructure", "substructure.json", "Substructure"),
    Part("boq", "10 BOQ", "boq.json", "BOQ"),
    Part("exports", "11 Exports", None, "Exports"),
)
PROJECT = Part("project", "", None, "Project")
"""Files at the project root: the ``<name>.saengine`` manifest, ``.gitignore``."""

_BY_FOLDER = {p.folder: p for p in PARTS}
_BY_ID = {p.id: p for p in PARTS} | {PROJECT.id: PROJECT}
PART_ORDER = {p.id: i for i, p in enumerate((*PARTS, PROJECT))}


def part_for_path(path: str) -> Part:
    """The part a project-relative path (``"05 Floor Plan/floor-plan.json"``) belongs to."""
    head, sep, _ = path.replace("\\", "/").partition("/")
    if not sep:
        return PROJECT
    part = _BY_FOLDER.get(head)
    return part if part else Part(head, head, None, head)


def part_by_id(part_id: str) -> Part:
    return _BY_ID.get(part_id) or Part(part_id, part_id, None, part_id)


# --- What things are called --------------------------------------------------------------------

# Collections (dotted path of the list inside the part, without indices) → the noun for one item.
# A callable gets the item and returns the noun (a member's kind, a material's category).
Noun = str | Callable[[dict[str, Any]], str]


def _field_noun(field: str, fallback: str, suffix: str = "") -> Callable[[dict[str, Any]], str]:
    def noun(item: dict[str, Any]) -> str:
        value = item.get(field)
        base = _humanize(value).capitalize() if isinstance(value, str) and value else fallback
        return f"{base}{suffix}"

    return noun


_NOUNS: dict[str, dict[str, Noun]] = {
    "soil": {
        "boreholes": "",
        "boreholes.layers": "layer",
        "boreholes.spt": "SPT",
        "boreholes.samples": "sample",
    },
    "settings": {"areaLoads": "Area load", "combinations": "Load combination"},
    "materials": {"materials": _field_noun("category", "Material")},
    "objects": {"objects": _field_noun("kind", "Object", " type")},
    "floorPlan": {
        "grids.x": "Grid line",
        "grids.y": "Grid line",
        "stories": "Story",
        "columns": "Column",
        "beams": "Beam",
        "walls": "Wall",
        "slabs": "Slab",
        "footings": "Footing",
        "underlays": "Underlay",
    },
    "structure": {
        "grids": "Grid",
        "grids.x": "grid line",
        "grids.y": "grid line",
        "grids.z": "grid line",
        "grids.r": "grid line",
        "grids.theta": "grid line",
        "members": _field_noun("kind", "Member"),
        "areas": _field_noun("kind", "Area"),
        "blocks": "Block",
        "supports": "Support",
    },
    "bim": {
        "stories": "Story",
        "elements": _field_noun("kind", "Element"),
        "additions.slabOpenings": "Slab opening",
        "additions.wallOpenings": "Wall opening",
        "additions.stairs": "Stair",
        "additions.members": "Member",
        "supports": "Support",
    },
    "mep": {
        "equipment": "Equipment",
        "openings": "Opening",
        "shafts": "Shaft",
        "ifcModels": "IFC model",
        "plumbing.stories": "Plumbing, story",
        "plumbing.risers": "Plumbing riser",
        "plumbing.tanks": "Tank",
        "hvac.stories": "HVAC, story",
        "hvac.plant": "HVAC plant",
        "hvac.ducts": "Duct",
        "electrical.stories": "Electrical, story",
        "electrical.equipment": "Electrical equipment",
        "electrical.risers": "Electrical riser",
        "electrical.trays": "Cable tray",
    },
    "substructure": {"foundations": "Foundation", "pileTypes": "Pile type", "tieBeams": "Tie beam"},
    "boq": {"items": "BOQ item"},
}

# The identifying key of the items of a collection, where it is not id / label / name / code.
_KEYS: dict[str, dict[str, str]] = {
    "soil": {"boreholes.layers": "top", "boreholes.spt": "depth", "boreholes.samples": "depth"},
    "floorPlan": {"underlays": "file"},
    "mep": {
        "plumbing.stories": "story",
        "hvac.stories": "story",
        "electrical.stories": "story",
        "ifcModels": "file",
    },
}
_GENERIC_KEYS = ("id", "label", "name", "code", "story", "file", "position")

# Keys shown as a depth ("SPT at 6 m"), in mm in the file.
_DEPTH_KEYS = {
    ("soil", "boreholes.layers"),
    ("soil", "boreholes.spt"),
    ("soil", "boreholes.samples"),
}

# Bookkeeping the engineer did not change: revisions of the parts a derived part came from.
_IGNORED: dict[str, tuple[str, ...]] = {"bim": ("source",), "boq": ("source",)}

# Labels where the model's title is missing or would read worse.
_LABELS: dict[str, str] = {
    "id": "ID",
    "mechanical": "",
    "hvac": "HVAC",
    "mep": "MEP",
    "nu": "Poisson's ratio ν",
    "fc": "f'c",
    "fy": "fy",
    "fu": "fu",
    "N": "N",
    "cu": "undrained shear strength cu",
    "phi": "friction angle φ",
    "uscs": "USCS class",
    "OCR": "OCR",
    "Cc": "Cc",
    "Cr": "Cr",
    "e0": "e0",
    "D": "D",
    "L": "L",
    "Lr": "Lr",
    "WX": "WX",
    "WY": "WY",
    "EX": "EX",
    "EY": "EY",
    "dx": "dx",
    "dy": "dy",
    "xDim": "width",
    "yDim": "depth",
    "schema": "file format",
}
# Members whose "type" is the cross-section they are made of.
_SECTION_NOUNS = {"beam", "column", "brace", "member"}

# Units for fields the model does not annotate (only used for numbers).
_FALLBACK_UNITS: dict[str, str] = {
    "depth": "mm",
    "top": "mm",
    "bottom": "mm",
    "waterTable": "mm",
    "groundLevel": "mm",
    "elevation": "mm",
    "position": "mm",
    "x": "mm",
    "y": "mm",
    "z": "mm",
    "length": "mm",
    "width": "mm",
    "height": "mm",
    "thickness": "mm",
    "unitWeight": "kN/m³",
    "saturatedUnitWeight": "kN/m³",
    "cu": "kPa",
    "phi": "°",
    "rotation": "°",
    "finesContent": "%",
    "plasticityIndex": "%",
    "liquidLimit": "%",
    "plasticLimit": "%",
    "moistureContent": "%",
    "live": "kN/m²",
    "finish": "kN/m²",
    "partitions": "kN/m²",
    "allowableBearing": "kN/m²",
    "density": "kg/m³",
}


def _humanize(name: Any) -> str:
    """``"siteClass"`` → ``"site class"``; leaves acronyms ("IFC", "SPT") alone."""
    text = str(name)
    if text.isupper() or not re.search(r"[a-z]", text):
        return text
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text).replace("_", " ")
    return " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in text.split())


# --- Field titles and units from the library models --------------------------------------------


_MODELS = {
    "soil": ("saengine.library.soil", "SoilReport"),
    "settings": ("saengine.library.settings", "ProjectSettings"),
    "materials": ("saengine.library.materials", "MaterialLibrary"),
    "objects": ("saengine.library.objects", "ObjectLibrary"),
    "floorPlan": ("saengine.library.floorplan", "FloorPlan"),
    "structure": ("saengine.library.structure", "StructuralModel"),
    "bim": ("saengine.library.bim", "BuildingModel"),
    "mep": ("saengine.library.mep", "MepModel"),
    "substructure": ("saengine.library.substructure", "Substructure"),
}
"""The Pydantic model of each part, imported on first use."""


@cache
def _schema(part: str) -> dict[str, Any] | None:
    """The JSON Schema of ``part``'s model; None without one (labels are a nicety)."""
    if part not in _MODELS:
        return None
    module, name = _MODELS[part]
    try:
        model = getattr(importlib.import_module(module), name)
        return model.model_json_schema(by_alias=True)
    except Exception:  # noqa: BLE001 - the diff works without the model
        return None


class _Schema:
    """Walks a JSON Schema alongside the data to find the title and unit of each field."""

    def __init__(self, root: dict[str, Any] | None):
        self.root = root
        self.defs = (root or {}).get("$defs", {})

    def resolve(self, node: dict[str, Any] | None) -> dict[str, Any] | None:
        for _ in range(16):
            if not node or "$ref" not in node:
                return node
            name = node["$ref"].rsplit("/", 1)[-1]
            # A definition's title is its class name ("ConcreteProperties"), not a label.
            target = {k: v for k, v in self.defs.get(name, {}).items() if k != "title"}
            node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        return node

    def _branches(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for key in ("anyOf", "oneOf", "allOf"):
            for branch in node.get(key, ()):
                branch = self.resolve(branch)
                if branch:
                    out.extend(self._branches(branch) if self._is_union(branch) else [branch])
        return out

    @staticmethod
    def _is_union(node: dict[str, Any]) -> bool:
        return any(k in node for k in ("anyOf", "oneOf", "allOf")) and "properties" not in node

    def for_object(self, node: dict[str, Any] | None, value: Any) -> dict[str, Any] | None:
        """The branch of ``node`` (maybe a union) describing the object ``value``."""
        node = self.resolve(node)
        if not node or not self._is_union(node):
            return node
        best, score = None, -1
        for branch in self._branches(node):
            props = branch.get("properties", {})
            if not isinstance(value, dict):
                if "properties" not in branch:
                    return branch
                continue
            # A discriminator ("kind": "beam") must match; otherwise count shared keys.
            mismatch = any(
                "const" in (p := self.resolve(spec) or {}) and value.get(k) != p["const"]
                for k, spec in props.items()
                if k in value
            )
            if mismatch:
                continue
            shared = sum(1 for k in value if k in props)
            if shared > score:
                best, score = branch, shared
        return best

    def child(self, node: dict[str, Any] | None, value: Any, key: str) -> dict[str, Any] | None:
        node = self.for_object(node, value)
        if not node:
            return None
        props = node.get("properties")
        if props and key in props:
            return self.resolve(props[key])
        extra = node.get("additionalProperties")
        return self.resolve(extra) if isinstance(extra, dict) else None

    def items(self, node: dict[str, Any] | None) -> dict[str, Any] | None:
        node = self.resolve(node)
        if not node:
            return None
        if self._is_union(node):
            for branch in self._branches(node):
                if branch.get("type") == "array":
                    return self.resolve(branch.get("items"))
            return None
        return self.resolve(node.get("items"))

    def describe(self, node: dict[str, Any] | None, key: str) -> tuple[str, str]:
        """(label, unit) of the field ``key`` whose schema is ``node``."""
        label = _LABELS.get(key)
        unit = ""
        texts: list[dict[str, Any]] = []
        node = self.resolve(node)
        if node:
            texts.append(node)
            texts.extend(self._branches(node))
            items = node.get("items")
            if isinstance(items, dict):
                texts.append(self.resolve(items) or {})
        for spec in texts:
            title = spec.get("title")
            if label is None and title and title.replace(" ", "").lower() != key.lower():
                label = title[0].lower() + title[1:] if not title[:2].isupper() else title
            match = re.search(r"\[([^\]]{1,12})\]", spec.get("description") or "")
            if not unit and match:
                unit = match.group(1)
        return label or _humanize(key), unit or _FALLBACK_UNITS.get(key, "")


# --- Formatting --------------------------------------------------------------------------------


def _number(value: float) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return str(int(value))
    return f"{value:.6g}"


def _is_point(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and set(value) <= {"x", "y", "z", "dx", "dy", "dz"}
        and all(
            isinstance(v, str | int | float) and not isinstance(v, bool) for v in value.values()
        )
    )


def _format(value: Any, unit: str = "") -> str:
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return f"{_number(value)} {unit}".rstrip() if unit else _number(value)
    if isinstance(value, str):
        return value if value else '""'
    if _is_point(value):
        grid = "/".join(str(value[k]) for k in ("x", "y", "z") if k in value)
        offsets = " ".join(f"{k} {_format(value[k])}" for k in ("dx", "dy", "dz") if value.get(k))
        return f"{grid} ({offsets})" if offsets else grid
    if isinstance(value, list):
        if all(isinstance(v, int | float) and not isinstance(v, bool) for v in value):
            text = "(" + ", ".join(_number(v) for v in value) + ")"
            return f"{text} {unit}" if unit else text
        if all(isinstance(v, str) for v in value):
            return ", ".join(value) if value else "(none)"
        if all(_is_point(v) for v in value):
            return " – ".join(_format(v) for v in value)
        return f"{len(value)} item{'s' if len(value) != 1 else ''}"
    if isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return text if len(text) <= 80 else text[:77] + "…"
    return str(value)


def _equal(a: Any, b: Any) -> bool:
    if type(a) is bool or type(b) is bool:
        return type(a) is type(b) and a == b
    if isinstance(a, float | int) and isinstance(b, float | int):
        return a == b or math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
    return a == b


# --- The diff ----------------------------------------------------------------------------------


@dataclass
class _Context:
    """Where in the document a difference is: the items it is inside and the fields below."""

    display: str  # "Beam B5", "BH-2 SPT at 6 m"; empty at the document level
    ids: tuple[str, ...]  # ("BH-2", "6000")
    nouns: tuple[str, ...]  # lower-case nouns of the items, to drop from labels
    path: str  # "boreholes[BH-2].spt[6000]"
    collection: str  # "boreholes.spt", for the noun and key tables
    fields: tuple[str, ...] = ()  # labels of the dict fields below the item
    item: dict[str, Any] | None = None


class _Differ:
    def __init__(self, part: str, file: str | None):
        self.part = part
        self.file = file
        self.schema = _Schema(_schema(part))
        self.changes: list[dict[str, Any]] = []
        self.ignored = _IGNORED.get(part, ())

    # Items ---------------------------------------------------------------------------------

    def _noun(self, collection: str, item: dict[str, Any]) -> str:
        noun = _NOUNS.get(self.part, {}).get(collection)
        if noun is None:
            last = collection.rsplit(".", 1)[-1]
            singular = last[:-3] + "y" if last.endswith("ies") else last.rstrip("s") or last
            noun = _humanize(singular).capitalize()
        return noun(item) if callable(noun) else noun

    def _key_of(self, collection: str, before: list[Any], after: list[Any]) -> str | None:
        items = [*before, *after]
        if not items or not all(isinstance(i, dict) for i in items):
            return None
        preferred = _KEYS.get(self.part, {}).get(collection)
        for key in (preferred, *_GENERIC_KEYS) if preferred else _GENERIC_KEYS:
            if key is None:
                continue
            ok = True
            for side in (before, after):
                values = [i.get(key) for i in side]
                if any(not isinstance(v, str | int | float) or isinstance(v, bool) for v in values):
                    ok = False
                    break
                if len(set(values)) != len(values):
                    ok = False
                    break
            if ok:
                return key
        return None

    def _key_text(self, collection: str, key: str, value: Any) -> str:
        if (self.part, collection) in _DEPTH_KEYS and isinstance(value, int | float):
            return f"at {_number(value / 1000)} m"
        return str(value) if not isinstance(value, float) else _number(value)

    def _enter(
        self,
        ctx: _Context,
        collection: str,
        key: str | None,
        item: dict[str, Any],
        index: int,
        noun: str | None = None,
    ) -> _Context:
        noun = self._noun(collection, item) if noun is None else noun
        key_value = item.get(key) if key else None
        key_text = self._key_text(collection, key, key_value) if key else str(index + 1)
        own = f"{noun} {key_text}".strip()
        display = f"{ctx.display} {own}".strip() if ctx.display else own
        ident = str(key_value) if key else str(index + 1)
        return _Context(
            display=display,
            ids=(*ctx.ids, ident),
            nouns=(*ctx.nouns, noun.lower()),
            path=f"{ctx.path}[{ident}]",
            collection=collection,
            item=item,
        )

    # Recording -----------------------------------------------------------------------------

    def _add(self, kind: str, ctx: _Context, what: str, before: Any, after: Any, path: str):
        ident = "/".join(ctx.ids) if ctx.ids else path
        change = {
            "kind": kind,
            "id": ident,
            "what": what,
            "before": before,
            "after": after,
            "path": path,
        }
        if self.file:
            change["file"] = self.file
        self.changes.append(change)

    def _item_event(self, kind: str, ctx: _Context, item: Any, path: str):
        detail = ""
        if isinstance(item, dict):
            kind_of = item.get("type")
            if isinstance(kind_of, str) and kind_of:
                detail = f" ({kind_of})"
        what = f"{ctx.display} {'added' if kind == 'added' else 'removed'}{detail}"
        self._add(
            kind,
            ctx,
            what,
            None if kind == "added" else item,
            item if kind == "added" else None,
            path,
        )

    def _label(self, ctx: _Context, labels: tuple[str, ...]) -> str:
        words: list[str] = []
        for label in labels:
            if not label or label.lower() in ctx.nouns:
                continue  # "Concrete C20.7: concrete f'c" → "Concrete C20.7: f'c"
            words.append(label)
        text = " ".join(words)
        # "Site site class" → "Site class"
        parts = text.split(" ")
        deduped = [w for i, w in enumerate(parts) if i == 0 or w.lower() != parts[i - 1].lower()]
        return " ".join(deduped)

    def _field_change(
        self,
        ctx: _Context,
        labels: tuple[str, ...],
        unit: str,
        key: str,
        before: Any,
        after: Any,
        path: str,
    ):
        if not labels:
            labels = (_humanize(key),)
        item_noun = ctx.nouns[-1] if ctx.nouns else ""
        if key == "type" and len(labels) == 1 and item_noun in _SECTION_NOUNS:
            labels = ("section",)
        if key == "quantity" and ctx.item and isinstance(ctx.item.get("unit"), str):
            unit = ctx.item["unit"]
        label = self._label(ctx, labels)
        if ctx.display:
            what = f"{ctx.display}: {label}"
        else:
            head, *rest = label.split(" ", 1)
            what = (head[:1].upper() + head[1:] + (" " + rest[0] if rest else "")) if label else ""
        if (
            isinstance(before, list)
            and isinstance(after, list)
            and all(isinstance(v, str) for v in [*before, *after])
        ):
            added = [v for v in after if v not in before]
            removed = [v for v in before if v not in after]
            bits = []
            if added:
                bits.append(f"{', '.join(added)} added")
            if removed:
                bits.append(f"{', '.join(removed)} removed")
            if bits:
                what = f"{what}: {'; '.join(bits)}"
                self._add("changed", ctx, what, before, after, path)
                return
        if before is None:
            what = f"{what} set to {_format(after, unit)}"
            kind = "added"
        elif after is None:
            what = f"{what} cleared (was {_format(before, unit)})"
            kind = "removed"
        else:
            b, a = _format(before, unit), _format(after, unit)
            if unit and b.endswith(" " + unit) and a.endswith(" " + unit):
                b = b[: -len(unit) - 1]
            what = f"{what} {b} → {a}"
            kind = "changed"
        what += self._note(ctx, key, before, after)
        self._add(kind, ctx, what, before, after, path)

    def _note(self, ctx: _Context, key: str, before: Any, after: Any) -> str:
        """What a coded value means, where SAEngine knows (the seismic zone of a district)."""
        if self.part == "settings" and key == "location" and not ctx.ids:
            try:
                from saengine.library.bnbc import LOCATIONS

                zb = LOCATIONS[before].zone if before in LOCATIONS else None
                za = LOCATIONS[after].zone if after in LOCATIONS else None
            except Exception:  # noqa: BLE001
                return ""
            if zb != za and (zb or za):
                return f" (seismic zone {zb or '?'} → {za or '?'})"
        return ""

    # Walking -------------------------------------------------------------------------------

    def walk(
        self,
        before: Any,
        after: Any,
        schema: dict[str, Any] | None,
        ctx: _Context,
        labels: tuple[str, ...],
        key: str,
        path: str,
        unit: str,
    ):
        if _equal(before, after):
            return
        if (
            isinstance(before, dict)
            and isinstance(after, dict)
            and not (_is_point(before) and _is_point(after))
        ):
            self.walk_dict(before, after, schema, ctx, labels, path)
            return
        if (
            isinstance(before, list)
            and isinstance(after, list)
            and self.walk_list(before, after, schema, ctx, labels, key, path)
        ):
            return
        self._field_change(ctx, labels, unit, key, before, after, path)

    def walk_dict(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
        schema: dict[str, Any] | None,
        ctx: _Context,
        labels: tuple[str, ...],
        path: str,
    ):
        top = not ctx.ids and not labels
        keys = list(after) + [k for k in before if k not in after]
        for k in keys:
            if top and k in self.ignored:
                continue
            b, a = before.get(k), after.get(k)
            if _equal(b, a):
                continue
            child = self.schema.child(schema, after if k in after else before, k)
            label, unit = self.schema.describe(child, k)
            sub = f"{path}.{k}" if path else k
            if isinstance(a if a is not None else b, list) and not ctx.ids and not labels:
                collection = k
            elif isinstance(a if a is not None else b, list):
                collection = f"{ctx.collection}.{k}" if ctx.collection else k
            else:
                collection = ctx.collection
            sub_ctx = (
                ctx
                if collection == ctx.collection
                else _Context(
                    ctx.display, ctx.ids, ctx.nouns, ctx.path, collection, ctx.fields, ctx.item
                )
            )
            if not ctx.ids and not labels and isinstance(a if a is not None else b, dict):
                # A top-level section ("seismic", "plumbing"): nested collections are named
                # by their dotted path, "plumbing.tanks".
                sub_ctx = _Context("", (), (), "", k)
            self.walk(b, a, child, sub_ctx, (*labels, label), k, sub, unit)

    def walk_list(
        self,
        before: list[Any],
        after: list[Any],
        schema: dict[str, Any] | None,
        ctx: _Context,
        labels: tuple[str, ...],
        key: str,
        path: str,
    ) -> bool:
        """Diff two lists of objects item by item; False to report the list as one value."""
        if not all(isinstance(v, dict) for v in [*before, *after]) or not (before or after):
            return False
        if all(_is_point(v) for v in [*before, *after]):
            return False  # a boundary or a path: one value
        collection = (
            ctx.collection
            if ctx.collection.endswith(key)
            else (f"{ctx.collection}.{key}" if ctx.collection else key)
        )
        item_schema = self.schema.items(schema)
        base = _Context(ctx.display, ctx.ids, ctx.nouns, ctx.path, collection)
        # A list inside an item ("reinforcement.longitudinal") without its own noun: name its
        # items by the labels leading there.
        noun = None
        if labels and ctx.display and collection not in _NOUNS.get(self.part, {}):
            noun = self._label(ctx, labels)
        id_key = self._key_of(collection, before, after)
        if id_key is None:
            if len(before) != len(after):
                return False
            for i, (b, a) in enumerate(zip(before, after, strict=True)):
                if _equal(b, a):
                    continue
                item_ctx = self._enter(base, collection, None, a, i, noun)
                self.walk_dict(
                    b, a, self.schema.for_object(item_schema, a), item_ctx, (), f"{path}[{i + 1}]"
                )
            return True
        old = {i[id_key]: i for i in before}
        new_keys = {i[id_key] for i in after}
        for index, item in enumerate(after):
            k = item[id_key]
            item_ctx = self._enter(base, collection, id_key, item, index, noun)
            sub = f"{path}[{k}]"
            if k not in old:
                self._item_event("added", item_ctx, item, sub)
            elif not _equal(old[k], item):
                self.walk_dict(
                    old[k], item, self.schema.for_object(item_schema, item), item_ctx, (), sub
                )
        for index, item in enumerate(before):
            k = item[id_key]
            if k not in new_keys:
                item_ctx = self._enter(base, collection, id_key, item, index, noun)
                self._item_event("removed", item_ctx, item, f"{path}[{k}]")
        return True


def diff_values(part: str, before: Any, after: Any, file: str | None = None) -> list[dict]:
    """The semantic differences between two parsed JSON documents of ``part``."""
    differ = _Differ(part, file)
    root = differ.schema.root
    ctx = _Context("", (), (), "", "")
    if isinstance(before, dict) and isinstance(after, dict):
        differ.walk_dict(before, after, root, ctx, (), "")
    elif (
        isinstance(before, list)
        and isinstance(after, list)
        and differ.walk_list(before, after, root, ctx, (), "items", "")
    ):
        pass
    elif not _equal(before, after):
        differ._add(
            "changed", ctx, f"Content {_format(before)} → {_format(after)}", before, after, ""
        )
    return differ.changes


# --- Files and parts ---------------------------------------------------------------------------

_JSON_SUFFIXES = (".json", ".osmodel", ".saengine")
_KINDS = {
    ".dxf": "Drawing",
    ".dwg": "Drawing",
    ".pdf": "PDF",
    ".ifc": "IFC model",
    ".csv": "Table",
    ".xlsx": "Spreadsheet",
    ".png": "Image",
    ".jpg": "Image",
    ".typ": "Report source",
}
_TEXT_LIMIT = 2_000_000


def _decode(data: bytes | str | None) -> str | None:
    if data is None or isinstance(data, str):
        return data
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


#: Above this many differing lines (after the common start and end are taken off), lines are
#: compared as multisets instead of in order: :class:`difflib.SequenceMatcher` is quadratic on
#: repetitive text (DXF group codes, CSV), and its ``autojunk`` heuristic, which would make it
#: fast, throws away exactly those repeated lines and reports nearly every line as changed.
_ORDERED_LINES = 600


def _text_summary(before: str, after: str, limit: int = 20) -> tuple[str, list[str]]:
    a, b = before.splitlines(), after.splitlines()
    start = 0
    while start < len(a) and start < len(b) and a[start] == b[start]:
        start += 1
    end = 0
    while end < len(a) - start and end < len(b) - start and a[-1 - end] == b[-1 - end]:
        end += 1
    a, b = a[start : len(a) - end], b[start : len(b) - end]
    added = removed = 0
    lines: list[str] = []
    approximate = len(a) + len(b) > _ORDERED_LINES
    if not approximate:
        matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            removed += i2 - i1
            added += j2 - j1
            for line in a[i1:i2]:
                if len(lines) < limit:
                    lines.append(f"- {line[:200]}")
            for line in b[j1:j2]:
                if len(lines) < limit:
                    lines.append(f"+ {line[:200]}")
    else:
        # Linear: a line counts as removed (added) as many times as it occurs more often before
        # (after); the order of lines is not considered, so moved lines are not counted.
        left = Counter(b)
        for line in a:
            if left[line] > 0:
                left[line] -= 1
            else:
                removed += 1
                if len(lines) < limit:
                    lines.append(f"- {line[:200]}")
        left = Counter(a)
        shown = len(lines)
        for line in b:
            if left[line] > 0:
                left[line] -= 1
            else:
                added += 1
                if shown < limit:
                    lines.append(f"+ {line[:200]}")
                    shown += 1
    about = "about " if approximate else ""
    return f"{about}{added} line{'s' if added != 1 else ''} added, {removed} removed", lines


def diff_file(
    part: str, file: str, before: bytes | str | None, after: bytes | str | None
) -> list[dict]:
    """Differences of one file of ``part`` (project-relative ``file``), semantic for JSON."""
    name = file.rsplit("/", 1)[-1]
    lower = name.lower()
    ctx_none: dict[str, Any] = {"id": file, "path": "", "file": file}
    if before is None and after is None:
        return []
    if before is None or after is None:
        kind = "added" if before is None else "removed"
        noun = _KINDS.get(lower[lower.rfind(".") :], "File") if "." in lower else "File"
        return [
            {
                **ctx_none,
                "kind": kind,
                "what": f"{noun} {name} {kind}",
                "before": None,
                "after": None,
            }
        ]
    if before == after:
        return []
    is_json = lower.endswith(_JSON_SUFFIXES)
    tb, ta = _decode(before), _decode(after)
    if is_json and tb is not None and ta is not None:
        # A corrupt or hostile file nested thousands of levels deep makes the parser (or the
        # walk below) recurse too far: it gets the same text summary as invalid JSON.
        try:
            changes: list[dict[str, Any]] | None = diff_values(
                part, json.loads(tb), json.loads(ta), file
            )
        except (ValueError, RecursionError):
            changes = None
        if changes is not None:
            if not changes:
                return [
                    {
                        **ctx_none,
                        "kind": "changed",
                        "what": f"{name}: formatting only",
                        "before": None,
                        "after": None,
                    }
                ]
            return changes
        if len(tb) + len(ta) <= _TEXT_LIMIT:
            text, lines = _text_summary(tb, ta)
            return [
                {
                    **ctx_none,
                    "kind": "changed",
                    "lines": lines,
                    "before": None,
                    "after": None,
                    "what": f"{name} is not valid JSON; text: {text}",
                }
            ]
    if (
        tb is not None
        and ta is not None
        and not lower.endswith((".pdf", ".png", ".jpg"))
        and (len(tb) + len(ta) <= _TEXT_LIMIT)
    ):
        text, lines = _text_summary(tb, ta)
        noun = _KINDS.get(lower[lower.rfind(".") :], "File") if "." in lower else "File"
        return [
            {
                **ctx_none,
                "kind": "changed",
                "lines": lines,
                "before": None,
                "after": None,
                "what": f"{noun} {name} modified ({text})",
            }
        ]
    noun = _KINDS.get(lower[lower.rfind(".") :], "File") if "." in lower else "File"
    return [
        {
            **ctx_none,
            "kind": "changed",
            "what": f"{noun} {name} modified",
            "before": None,
            "after": None,
        }
    ]


def _summary(changes: list[dict]) -> str:
    if not changes:
        return "No changes"
    counts = {"added": 0, "removed": 0, "changed": 0}
    things: list[str] = []
    seen: set[str] = set()
    for change in changes:
        counts[change["kind"]] = counts.get(change["kind"], 0) + 1
        subject = change["what"].split(":", 1)[0] if ":" in change["what"] else change["what"]
        if change["kind"] == "changed" and ":" in change["what"]:
            subject = f"{subject} changed"
        if subject not in seen:
            seen.add(subject)
            things.append(subject)
    n = len(changes)
    head = f"{n} change{'s' if n != 1 else ''}"
    shown = "; ".join(things[:3])
    more = f"; and {len(things) - 3} more" if len(things) > 3 else ""
    return f"{head}: {shown}{more}"


def diff_part(
    part: str, files: Iterable[tuple[str, bytes | str | None, bytes | str | None]]
) -> dict[str, Any]:
    """Differences of one part over its changed files ``(relative path, before, after)``.

    The part's main file comes first, then its other files by name.
    """
    info = part_by_id(part)
    main = f"{info.folder}/{info.main_file}" if info.main_file else None
    ordered = sorted(files, key=lambda f: (f[0] != main, f[0]))
    changes: list[dict] = []
    for file, before, after in ordered:
        changes.extend(diff_file(part, file, before, after))
    return {"part": part, "title": info.title, "changes": changes, "summary": _summary(changes)}

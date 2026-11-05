"""Project overrides of code pack values.

A project may replace any value of its code pack (Project Settings > Code values, the setting
``codeOverrides``): a map from a value's path to the project's value::

    "codeOverrides": {
      "factors.phi.shear": 0.7,
      "seismic.systems.rcSmf.R": 7,
      "combinations.pDeltaPreload": {"D": 1.4, "L": 0.5},
      "combinations.strength[1.2D + 1.6L + 0.5Lr].factors.L": 1.7
    }

A path is the table's name, then the keys inside it, separated by dots. A key with dots or
brackets in it is written in brackets (``zones[2]`` or ``strength[1.2D + 1.6L]``); an item of a
list is named by its index or by its ``name`` / ``id`` (or the list's merge key).

The overrides are merged over the pack in force where the pack is resolved for a project
(:func:`saengine.codes.context.pack_for`, :meth:`saengine.codes.registry.Registry.active`), with
the inheritance merge of :mod:`saengine.codes.merge` (a value or a group replaces the pack's):
every reader of the pack sees them, with no change at the call. Each override is checked against
the table's model: an override of a value the pack does not have, of another JSON type, or that
the model refuses (a φ above 1, say) is not applied, and is reported with its path
(:attr:`CodePack.override_problems`, the settings' problems), never raised. Without an override
the pack's value applies; the overrides hold for whichever pack the project uses, so after
switching packs an override of a value the new pack lacks is reported, not applied.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import RootModel, ValidationError

from saengine.codes.merge import merge

#: The settings key of the overrides.
SETTING = "codeOverrides"

_TOKEN = re.compile(r"\[([^\]]*)\]|([^.\[\]]+)")


class OverrideError(ValueError):
    """An override that cannot be applied (its path and why)."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.reason = message


@dataclass(frozen=True)
class Override:
    """An override applied: the pack's value it replaced and the project's value."""

    path: str
    table: str
    #: The path within the table ("phi.shear").
    key: str
    packValue: Any
    value: Any

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "packValue": self.packValue, "value": self.value}


def of(settings: Any) -> dict[str, Any]:
    """The overrides a project's settings give (``codeOverrides``; a dict or a ProjectSettings);
    {} without any. Not a map: none."""
    if settings is None:
        return {}
    value = (
        settings.get(SETTING) if isinstance(settings, dict) else getattr(settings, SETTING, None)
    )
    return dict(value) if isinstance(value, dict) else {}


def with_town(pack: Any, settings: Any) -> dict[str, Any]:
    """The project's overrides (:func:`of`) after the values its town gives (alpha 9 C20: a
    town of the pack's ``locations`` with a ``spectrumType``, GB 50011's design earthquake
    group, sets ``seismic.spectrumType``; a project's own override of it wins). Just
    :func:`of` for a town without one (every pack before C20)."""
    given = of(settings)
    if settings is None or "seismic.spectrumType" in given:
        return given
    site = settings.get("site") if isinstance(settings, dict) else getattr(settings, "site", None)
    location = site.get("location") if isinstance(site, dict) else getattr(site, "location", None)
    if not location:
        return given
    try:
        if not pack.has("locations") or not pack.has("seismic"):
            return given
        town = pack.table("locations").locations.get(location)
    except Exception:  # noqa: BLE001 - a pack that cannot give its towns keeps the overrides
        return given
    kind = getattr(town, "spectrumType", None) if town is not None else None
    if not kind:
        return given
    return {"seismic.spectrumType": kind, **given}


def table_of(path: str) -> str | None:
    """The table an override's path names ("factors.phi.shear" -> "factors"); None when it is
    not a path."""
    try:
        return split(path)[0]
    except OverrideError:
        return None


def restricted(overrides: dict[str, Any], tables: Any) -> dict[str, Any]:
    """The overrides of the tables ``tables`` (in their order); one whose path is not a path is
    kept (it counts wherever it may apply)."""
    return {
        path: value
        for path, value in overrides.items()
        if (table := table_of(path)) is None or table in tables
    }


def digest(overrides: dict[str, Any]) -> str:
    """A hash of the overrides (keyed caches)."""
    text = json.dumps(overrides, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def split(path: str) -> list[str]:
    """The keys of ``path`` ("a.b[c.d].0" -> ["a", "b", "c.d", "0"]); OverrideError when it is
    not a path."""
    if not isinstance(path, str) or not path.strip():
        raise OverrideError(str(path), "not a path")
    keys: list[str] = []
    at = 0
    text = path.strip()
    while at < len(text):
        if keys and text[at] == ".":
            at += 1
        m = _TOKEN.match(text, at)
        if m is None or m.end() == at:
            raise OverrideError(path, "not a path (table.key.key, a key with dots in [brackets])")
        keys.append(m.group(1) if m.group(1) is not None else m.group(2))
        at = m.end()
    if any(not k for k in keys):
        raise OverrideError(path, "an empty key")
    return keys


def join(keys: list[str]) -> str:
    """The path of ``keys`` (inverse of :func:`split`)."""
    out = ""
    for key in keys:
        if re.fullmatch(r"[^.\[\]]+", key) and key.strip() == key:
            out += f".{key}" if out else key
        else:
            out += f"[{key}]"
    return out


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true or false"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "a group of values"
    return type(value).__name__


def _item(items: list[Any], key: str, merge_key: str | None) -> int:
    """The index of list item ``key``: its index, else the item whose merge key (``name``,
    ``id``) is ``key``; -1 when none."""
    for field in (merge_key, "name", "id"):
        if not field:
            continue
        for i, item in enumerate(items):
            if isinstance(item, dict) and str(item.get(field)) == key:
                return i
    if re.fullmatch(r"-?\d+", key):
        i = int(key)
        if -len(items) <= i < len(items):
            return i % len(items)
    return -1


def _nest(
    base: Any, keys: list[str], value: Any, merge_keys: dict[str, str], path: str, at: str = ""
) -> tuple[Any, Any]:
    """(the override document to merge over ``base``, the pack's value at ``keys``). A list on
    the way is given whole with the item changed (merge then replaces it, or merges it item by
    item by its merge key); a group's value replaces the pack's group."""
    if not keys:
        doc = {"$replace": True, **value} if isinstance(value, dict) else copy.deepcopy(value)
        return doc, copy.deepcopy(base)
    key, rest = keys[0], keys[1:]
    if isinstance(base, dict):
        if key not in base:
            raise OverrideError(path, f"the code pack has no value '{key}' here")
        doc, old = _nest(base[key], rest, value, merge_keys, path, f"{at}.{key}" if at else key)
        return {key: doc}, old
    if isinstance(base, list):
        i = _item(base, key, merge_keys.get(at))
        if i < 0:
            raise OverrideError(path, f"the code pack's list has no item '{key}'")
        doc, old = _nest(base[i], rest, value, merge_keys, path, f"{at}[]")
        items = copy.deepcopy(base)
        items[i] = merge(items[i], doc, merge_keys, f"{at}[]")
        return items, old
    raise OverrideError(path, f"the code pack's value here is {_json_type(base)}, not a group")


def _same_type(old: Any, new: Any) -> bool:
    if old is None:
        return True
    return _json_type(old) == _json_type(new)


#: Pydantic's range errors: (its context key, how the page says it).
_RANGES = {
    "less_than_equal": ("le", "at most {}"),
    "less_than": ("lt", "less than {}"),
    "greater_than_equal": ("ge", "at least {}"),
    "greater_than": ("gt", "more than {}"),
}


def _message(error: ValidationError, table: str, value: Any = None) -> str:
    """Why the model refused an override: the value and its allowed range when that is why
    (SL-3: "1.2 is out of range: it must be at most 1"), else the model's words."""
    err = error.errors()[0]
    loc = ".".join(str(x) for x in err["loc"])
    kind = _RANGES.get(str(err.get("type")))
    limit = (err.get("ctx") or {}).get(kind[0]) if kind else None
    if kind and limit is not None:
        shown = err.get("input", value)
        bound = f"{limit:g}" if isinstance(limit, (int, float)) else str(limit)
        return f"{shown!r} is out of range: it must be {kind[1].format(bound)}"
    msg = str(err["msg"]).removeprefix("Value error, ")
    return f"{msg} ({table}.{loc})" if loc else msg


def apply(pack: Any, overrides: dict[str, Any]) -> Any:
    """``pack`` (a :class:`saengine.codes.registry.CodePack`) with ``overrides`` merged over its
    tables: a copy with :attr:`overrides` (applied) and :attr:`override_problems` (refused, with
    their path); the refused ones are also among its warnings."""
    from saengine.codes.manifest import Problem
    from saengine.codes.registry import DEFAULT_MERGE_KEYS, _validators

    out = pack._copy()
    out._requested = dict(overrides)
    validators = _validators()
    applied: list[Override] = []
    refused: list[tuple[str, str]] = []
    for path in sorted(overrides):
        value = overrides[path]
        try:
            keys = split(path)
            table, inner = keys[0], keys[1:]
            if not inner:
                raise OverrideError(path, "name a value inside the table, not the whole table")
            if table not in out._tables:
                raise OverrideError(
                    path, f"the code pack {pack.edition or pack.name} has no table '{table}'"
                )
            v = validators.get(table)
            merge_keys = (v.merge_keys if v else DEFAULT_MERGE_KEYS.get(table)) or {}
            base = out._tables[table]
            doc, old = _nest(base, inner, value, merge_keys, path)
            if not _same_type(old, value):
                raise OverrideError(
                    path, f"must be {_json_type(old)} like the code pack's value {old!r}"
                )
            data = merge(base, doc, merge_keys)
            validated = None
            if v is not None:
                try:
                    validated = v.adapter.validate_python(data)
                except ValidationError as e:
                    raise OverrideError(path, _message(e, table, value)) from e
                if isinstance(validated, RootModel):
                    validated = validated.root
        except OverrideError as e:
            refused.append((e.path, e.reason))
            continue
        out._tables[table] = data
        if validated is not None:
            out._validated[table] = validated
        applied.append(Override(join(keys), table, join(inner), old, copy.deepcopy(value)))
    out._overrides = applied
    out._override_problems = refused
    out._warnings = [
        *out._warnings,
        *(
            Problem(severity="warning", message=f"code value override {p}: {m}: not applied")
            for p, m in refused
        ),
    ]
    return out


#: Keys that hold clause references, not values (not listed for overriding).
_NOT_VALUES = frozenset({"source", "sources", "clauses"})
#: Keys whose text is a label of an entry, not a value.
_LABELS = frozenset({"name", "description", "label", "note", "title", "row", "text"})
#: Keys of prose (lists of notes): not code values.
_PROSE = frozenset({"notes", "remarks", "comments"})

#: The page's sections and their tables, structural first (SL-1); tables not named here come
#: last ("Other"), in the pack's order.
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Concrete and steel design",
        (
            "factors",
            "concrete",
            "detailing",
            "designLimits",
            "serviceability",
            "floorVibration",
            "windComfort",
            "slabCoefficients",
            "slabMethods",
            "wallMethods",
            "stairMethods",
            "concreteMethods",
            "geotechnicalMethods",
            "allowableStress",
            "transfer",
            "anchors",
            "concreteTime",
            "steel",
            "steelLimitState",
            "steelSeismic",
            "steelStability",
            "steelSections",
            "coldFormed",
            "composite",
            "compositeConcrete",
            "precast",
            "masonry",
            "timber",
            "bamboo",
            "ferrocement",
            "fatigue",
            "designClauses",
        ),
    ),
    (
        "Loads, combinations and analysis",
        (
            "combinations",
            "areaLoads",
            "deadLoads",
            "liveReduction",
            "snow",
            "seismic",
            "zoneCoefficients",
            "locations",
            "wind",
            "flood",
            "cranes",
            "isolation",
            "pushover",
            "horizontalCapacity",
            "nonlinearHistory",
            "existing",
            "nonstructural",
            "nonBuilding",
            "occupancyCategories",
        ),
    ),
    (
        "Foundations and site",
        (
            "foundations",
            "siteInvestigation",
            "hazardLookup",
            "construction",
            "embeddedWalls",
            "excavationSupport",
            "materials",
        ),
    ),
    (
        "Fire, services and planning",
        (
            "fire",
            "fireResistance",
            "steelFire",
            "plumbing",
            "hvac",
            "electrical",
            "mepOpenings",
            "planning",
            "accessibility",
        ),
    ),
)
OTHER_SECTION = "Other"


def ordered_tables(tables: list[str]) -> list[tuple[str, str]]:
    """(table, section) of ``tables`` in the page's order: by :data:`SECTIONS`, the rest last."""
    rank = {t: (i, j) for i, (_, names) in enumerate(SECTIONS) for j, t in enumerate(names)}
    section = {t: name for name, names in SECTIONS for t in names}
    known = sorted((t for t in tables if t in rank), key=lambda t: rank[t])
    return [(t, section[t]) for t in known] + [(t, OTHER_SECTION) for t in tables if t not in rank]


def humanize(key: str) -> str:
    """A key as words: "compressionTied" -> "Compression tied", "R" stays "R"."""
    if not key or not re.search(r"[a-z]", key):
        return key
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key.replace("_", " ")).split()
    if not words:
        return key
    out = [words[0][:1].upper() + words[0][1:]]
    out += [w if (len(w) > 1 and w.isupper()) else w.lower() for w in words[1:]]
    return " ".join(out)


_UNIT = re.compile(r"\[([^\]]{1,24})\]")


def _schema_node(schema: dict[str, Any], node: Any, key: str) -> Any:
    """The schema of ``key`` inside ``node`` (``$ref``, ``anyOf`` and list items followed)."""
    defs = schema.get("$defs", {})

    def resolve(n: Any) -> Any:
        for _ in range(8):
            if not isinstance(n, dict):
                return None
            if "$ref" in n:
                n = defs.get(str(n["$ref"]).rsplit("/", 1)[-1])
                continue
            options = [o for o in n.get("anyOf", []) if o.get("type") != "null"]
            if options and "properties" not in n:
                n = options[0]
                continue
            return n
        return n

    node = resolve(node)
    if not isinstance(node, dict):
        return None
    if node.get("type") == "array" and "items" in node:
        return resolve(node["items"])  # a named item of a list

    def described(raw: Any) -> Any:
        # An optional field ("float | None") keeps its description on the anyOf node, not on
        # the option it resolves to (R1-18 of re-walk 1: no unit on "Concentrated", "Max").
        found = resolve(raw)
        if (
            isinstance(raw, dict)
            and raw.get("description")
            and isinstance(found, dict)
            and not found.get("description")
        ):
            found = {**found, "description": raw["description"]}
        return found

    props = node.get("properties", {})
    if key in props:
        return described(props[key])
    extra = node.get("additionalProperties")
    if not isinstance(extra, dict):
        return None
    found = described(extra)
    # A value of a mapping of plain values ("byLanes": {1: 3600}): the mapping's words.
    if isinstance(found, dict) and not found.get("description") and "properties" not in found:
        found = {**found, "description": node.get("description") or ""}
    return found


@functools.cache
def _table_schema(table: str) -> dict[str, Any]:
    """The JSON Schema of a table's model ({} for a table without one)."""
    from saengine.codes.tables import TABLE_MODELS, table_schema

    if table not in TABLE_MODELS:
        return {}
    try:
        return table_schema(table)
    except Exception:  # noqa: BLE001 - a model whose schema cannot be generated: no words
        return {}


def describe(table: str, keys: list[str], data: Any) -> dict[str, str]:
    """What the page shows of a value (SL-1): ``label`` (the field's words), ``description``
    (the table model's), ``unit`` (from the description's "[mm]"), ``clause`` (the pack's
    reference of the value or its group, else the table's source)."""
    description = ""
    schema = _table_schema(table)
    if schema:
        node: Any = schema
        for key in keys:
            node = _schema_node(schema, node, key)
            if node is None:
                break
        if isinstance(node, dict):
            description = str(node.get("description") or "")
    unit_match = _UNIT.search(description)
    clause = ""
    if isinstance(data, dict):
        sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
        for k in (join(keys), *reversed(keys)):
            if isinstance(sources.get(k), str):
                clause = sources[k]
                break
        clause = clause or str(data.get("source") or "")
    label = humanize(keys[-1]) if keys else table
    return {
        "label": label,
        "description": description,
        "unit": unit_match.group(1) if unit_match else "",
        "clause": clause,
    }


def words_of(pack: Any, path: str) -> dict[str, str]:
    """What the page and the report show of an override's ``path`` (R1-16 of re-walk 1: they
    listed raw keys such as ``factors.phi.shear``): :func:`describe` of its value, with
    ``title``, its table, groups and name in words ("Factors › Phi › Shear"). Empty words for a
    path that is not one."""
    try:
        keys = split(path)
    except OverrideError:
        return {"title": str(path), "label": "", "description": "", "unit": "", "clause": ""}
    table, rest = keys[0], keys[1:]
    tables = getattr(pack, "_tables", {}) or {}
    found = describe(table, rest, tables.get(table))
    title = " › ".join([humanize(table), *(humanize(k) for k in rest)])
    return {"title": title, **found}


def browse(pack: Any, tables: list[str] | None = None) -> list[dict[str, Any]]:
    """The values of the pack's tables (``tables``; default all) as the Code values page lists
    them: ``{path, table, value, packValue, type, overridden, generic, note}`` for each value
    (a number, text, true or false, or a list), in table order. Groups are walked; lists of
    groups (named items) by their names; clause references and labels are left out."""
    rows: list[dict[str, Any]] = []
    base = pack.base

    def walk(table: str, data: Any, keys: list[str], pack_data: Any) -> None:
        if isinstance(data, dict):
            for k, v in data.items():
                if k in _NOT_VALUES or (k in _LABELS and isinstance(v, str)):
                    continue  # clause references and labels: not code values
                if k in _PROSE and isinstance(v, list):
                    continue  # notes: prose, not values (SL-1)
                other = pack_data.get(k) if isinstance(pack_data, dict) else None
                walk(table, v, [*keys, str(k)], other)
            return
        if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
            for i, item in enumerate(data):
                name = item.get("name", item.get("id", i))
                other = pack_data[i] if isinstance(pack_data, list) and i < len(pack_data) else None
                walk(table, item, [*keys, str(name)], other)
            return
        key = join(keys)
        fb = pack.fallback(table, key)
        ov = pack.override(table, key)
        rows.append(
            {
                "path": join([table, *keys]),
                "table": table,
                "value": data,
                "packValue": pack_data,
                "type": _json_type(data),
                "overridden": ov is not None,
                "generic": fb is not None,
                "note": fb.note if fb is not None else "",
                **describe(table, keys, pack._tables.get(table)),
                "group": humanize(keys[0]) if len(keys) > 1 else "",
            }
        )

    for table in pack.tables():
        if table in pack.broken or (tables is not None and table not in tables):
            continue
        walk(table, pack._tables.get(table), [], base._tables.get(table))
    return rows


def pack_value(pack: Any, path: str) -> Any:
    """The pack's value at ``path`` (overrides that were refused are not in it); None when the
    pack has none there."""
    try:
        keys = split(path)
    except OverrideError:
        return None
    node: Any = pack._tables.get(keys[0])
    for key in keys[1:]:
        if isinstance(node, dict):
            node = node.get(key)
        elif isinstance(node, list):
            i = _item(node, key, None)
            node = node[i] if i >= 0 else None
        else:
            return None
    return copy.deepcopy(node)

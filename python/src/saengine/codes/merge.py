"""Inheritance of table data: a pack that extends another overrides only what it provides.

Rules (applied per table, child over parent):

* objects are deep-merged key by key;
* lists are replaced, unless the table declares a merge key for that list: then items are matched
  by that key, matched items are deep-merged, new items appended (in order), and an item with
  ``"$remove": true`` removes the parent's item with the same key;
* ``{"$replace": true, ...}`` at any object level replaces that whole object (and below);
* ``"$remove": ["key", ...]`` in an object removes those keys of the parent's object;
* keys starting with ``$`` are directives and never reach the resolved data.

A table file (``data/<table>.json``) is either the table itself (an object) or a wrapper
``{"$data": <object or list>, ...directives}``. Root-level directives:

* ``"$sources": ["BNBC 2020 Part 6 2.7.3", ...]``: clause references of the table;
* ``"$mergeKeys": {"": "id", "strength": "name"}``: merge keys by path ("" is the table itself,
  ``a.b`` a nested object's list, ``a[].b`` a list inside the items of list ``a``);
* ``"$replace": true``: replace the parent's table as a whole.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

DIRECTIVE = "$"


@dataclass
class TableFile:
    """A table as one pack provides it: the raw data (directives still inside) and the
    root-level directives."""

    data: Any
    sources: list[Any] = field(default_factory=list)
    merge_keys: dict[str, str] = field(default_factory=dict)
    replace: bool = False


def parse_table_file(raw: Any) -> TableFile:
    """Split a ``data/<table>.json`` document into data and root directives."""
    if not isinstance(raw, dict):
        return TableFile(data=raw)
    sources = raw.get("$sources") or []
    if not isinstance(sources, list):
        raise TypeError("'$sources' must be a list")
    merge_keys = raw.get("$mergeKeys") or {}
    if not isinstance(merge_keys, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in merge_keys.items()
    ):
        raise TypeError("'$mergeKeys' must map paths to key names")
    replace = bool(raw.get("$replace", False))
    if "$data" in raw:
        data = raw["$data"]
    else:
        data = {k: v for k, v in raw.items() if k not in ("$sources", "$mergeKeys", "$replace")}
    return TableFile(data=data, sources=list(sources), merge_keys=dict(merge_keys), replace=replace)


def strip(value: Any) -> Any:
    """``value`` without directives (``$`` keys, list items marked ``$remove``)."""
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if not k.startswith(DIRECTIVE)}
    if isinstance(value, list):
        return [strip(v) for v in value if not (isinstance(v, dict) and v.get("$remove") is True)]
    return copy.deepcopy(value)


def _is_key(value: Any) -> bool:
    """Whether ``value`` can identify a list item or name an object key (a JSON scalar)."""
    return isinstance(value, (str, int, float, bool))


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def merge(
    base: Any, override: Any, merge_keys: dict[str, str] | None = None, path: str = ""
) -> Any:
    """``override`` applied over ``base`` (neither is modified); see the module rules."""
    keys = merge_keys or {}
    if isinstance(override, dict):
        if override.get("$replace") is True or not isinstance(base, dict):
            return strip(override)
        result = copy.deepcopy(base)
        removed = override.get("$remove")
        if isinstance(removed, list):
            for key in removed:
                if isinstance(key, str):  # anything else names no key: ignored
                    result.pop(key, None)
        for key, value in override.items():
            if key.startswith(DIRECTIVE):
                continue
            if key in result:
                result[key] = merge(result[key], value, keys, _join(path, key))
            else:
                result[key] = strip(value)
        return result
    if isinstance(override, list):
        key = keys.get(path)
        if key is None or not isinstance(base, list):
            return strip(override)
        result = copy.deepcopy(base)
        index = {
            item[key]: i
            for i, item in enumerate(result)
            if isinstance(item, dict) and _is_key(item.get(key))
        }
        dropped: set[int] = set()
        for item in override:
            remove = isinstance(item, dict) and item.get("$remove") is True
            keyed = isinstance(item, dict) and _is_key(item.get(key))
            if keyed and item[key] in index:
                i = index[item[key]]
                if remove:
                    dropped.add(i)
                else:
                    result[i] = merge(result[i], item, keys, f"{path}[]")
            elif remove:
                continue
            else:
                result.append(strip(item))
                if keyed:
                    index[item[key]] = len(result) - 1
        return [item for i, item in enumerate(result) if i not in dropped]
    return copy.deepcopy(override)


def resolve_table(files: list[TableFile], merge_keys: dict[str, str] | None = None) -> Any:
    """The resolved table from its files, root ancestor first. Merge keys: the registered ones,
    then those the files declare (a later file wins)."""
    keys = dict(merge_keys or {})
    for f in files:
        keys.update(f.merge_keys)
    result: Any = None
    for i, f in enumerate(files):
        if i == 0 or f.replace:
            result = strip(f.data)
        else:
            result = merge(result, f.data, keys)
    return result

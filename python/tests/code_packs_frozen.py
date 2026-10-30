"""Frozen values of the code tables that moved from Python modules into the code pack.

``python tests/code_packs_frozen.py <module> [...]`` writes what each module's public data names
returned before the move to ``tests/data/code_packs_3/<module>.txt`` (a Python literal: run once,
on the old module). The tests compare the module, now reading the pack, with that file: values
*and* types (an int that became a float would print differently in a report).
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import math
import sys
import types
from pathlib import Path
from typing import Any

FROZEN_DIR = Path(__file__).parent / "data" / "code_packs_3"


def plain(value: Any) -> Any:
    """``value`` as Python literals: a dataclass a dict with its class name, inf a marker."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "__class__": type(value).__name__,
            **{f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)},
        }
    if isinstance(value, float) and math.isinf(value):
        return {"__float__": "inf" if value > 0 else "-inf"}
    if isinstance(value, dict):
        return {plain_key(k): plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(plain(v) for v in value)
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, (frozenset, set)):
        return {"__set__": sorted(plain(v) for v in value)}
    return value


def plain_key(key: Any) -> Any:
    return plain(key) if isinstance(key, tuple) else key


def public_data(module: types.ModuleType, names: list[str] | None = None) -> dict[str, Any]:
    """The module's public names that hold data (not functions, classes or modules)."""
    out = {}
    for name in names if names is not None else sorted(vars(module)):
        if name.startswith("_") and names is None:
            continue
        value = getattr(module, name)
        if callable(value) or isinstance(value, types.ModuleType) or name == "annotations":
            continue
        out[name] = plain(value)
    return out


def frozen(stem: str) -> dict[str, Any]:
    return ast.literal_eval((FROZEN_DIR / f"{stem}.txt").read_text(encoding="utf-8"))


def same(a: Any, b: Any, path: str = "") -> list[str]:
    """Where ``a`` and ``b`` differ in value or type (empty: identical)."""
    if type(a) is not type(b):
        return [f"{path}: {type(a).__name__} {a!r} != {type(b).__name__} {b!r}"]
    if isinstance(a, dict):
        if list(a) != list(b):
            return [f"{path}: keys {list(a)} != {list(b)}"]
        return [d for k in a for d in same(a[k], b[k], f"{path}[{k!r}]")]
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in same(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def write(stem: str, data: dict[str, Any]) -> Path:
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    path = FROZEN_DIR / f"{stem}.txt"
    lines = ["{"] + [f"    {k!r}: {v!r}," for k, v in data.items()] + ["}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    for spec in sys.argv[1:]:
        module = importlib.import_module(spec)
        data = public_data(module)
        if spec == "saengine.library.steel_sections":
            data["section_table()"] = plain(list(module.section_table()))
            data["table_json()"] = plain(module.table_json())
        print(
            write(
                spec.rsplit(".", 2)[-2] if spec.endswith(".tables") else spec.rsplit(".", 1)[-1],
                data,
            )
        )

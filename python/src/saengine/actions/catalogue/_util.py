"""Small helpers of the catalogue: the parameters' base model, merging a patch into a part."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, ConfigDict


class Params(BaseModel):
    """Parameters of an action: unknown names are refused (a misspelt field is not ignored)."""

    model_config = ConfigDict(extra="forbid")


def given(p: BaseModel, *names: str) -> dict[str, Any]:
    """The fields of ``p`` the caller gave (an explicit null included), of ``names`` (or all)."""
    fields = names or tuple(type(p).model_fields)
    return {n: getattr(p, n) for n in fields if n in p.model_fields_set}


def merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """``patch`` merged into a copy of ``base`` (objects merged key by key; a None removes)."""
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def plain(value: Any) -> Any:
    """Pydantic models in ``value`` as JSON data."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def fmt(value: float) -> str:
    return f"{value:g}"

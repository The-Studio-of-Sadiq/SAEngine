"""Shared IO, code-pack, parsing, and export helpers for Project Settings features."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from pathlib import Path
from typing import Any

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.features import FeatureContext, FeatureInputError
from saengine.library.settings import (
    ProjectSettings,
    derived,
    pack_choices,
    read_soil_text,
    resolve_site_class,
)
from saengine.report.clauses import in_force


def require_root(ctx: FeatureContext, purpose: str = "this feature") -> Path:
    """Return the open project root Path or raise FeatureInputError."""
    if ctx.root is None or not ctx.root.exists():
        raise FeatureInputError(f"Open a project folder before {purpose}.")
    return ctx.root


def load_settings_raw(ctx: FeatureContext) -> dict[str, Any]:
    """Return raw 02 Project Settings/project-settings.json dict, or {}."""
    raw = ctx.raw("settings")
    return raw if isinstance(raw, dict) else {}


def load_settings(ctx: FeatureContext) -> ProjectSettings:
    """Return validated ProjectSettings (or defaults when no file exists)."""
    return ctx.settings()


def active_pack(ctx: FeatureContext, settings: ProjectSettings | None = None) -> Any:
    """Return the resolved CodePack for the project settings."""
    st = settings or load_settings(ctx)
    return code_context.pack_for(st, ctx.root)


def safe_table(pack: Any, name: str) -> Any | None:
    """Return pack table ``name`` when present and valid, else None."""
    if pack is None or not pack.has(name):
        return None
    try:
        return pack.table(name)
    except Exception:  # noqa: BLE001 - broken table handled gracefully
        return None


def project_derived(ctx: FeatureContext, settings: ProjectSettings | None = None) -> dict[str, Any]:
    """Compute derived seismic/wind/importance code values within in_force(ctx.root)."""
    st = settings or load_settings(ctx)
    with in_force(ctx.root, st):
        return derived(st)


def effective_site_class(
    ctx: FeatureContext, settings: ProjectSettings | None = None
) -> tuple[ProjectSettings, dict[str, Any]]:
    """Resolve effective site class from soil report or entered settings."""
    st = settings or load_settings(ctx)
    soil_text = read_soil_text(ctx.root) if ctx.root else None
    with in_force(ctx.root, st):
        return resolve_site_class(st, soil_text)


def available_pack_ids(ctx: FeatureContext) -> list[str]:
    """Return usable design code pack ids visible to this project."""
    return [
        p.id
        for p in registry.default_registry().list_packs(ctx.root, "designCode")
        if p.effective and p.usable
    ]


def export_file(ctx: FeatureContext, filename: str, content: str | bytes) -> Path:
    """Write an export artifact under ``02 Project Settings/exports/<filename>``."""
    require_root(ctx, "exporting settings files")
    target = ctx.path(f"02 Project Settings/exports/{filename}")
    if target is None:
        raise FeatureInputError("Open a project folder before exporting settings files.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target


def parse_numbers(raw: str, label: str = "Values") -> list[float]:
    """Parse comma, semicolon, or whitespace separated numbers."""
    tokens = [t for t in re.split(r"[\s,;]+", raw.strip()) if t]
    if not tokens:
        raise FeatureInputError(f"Enter at least one numeric value for {label}.")
    out: list[float] = []
    for tok in tokens:
        try:
            val = float(tok)
        except ValueError as exc:
            raise FeatureInputError(f"{label}: {tok!r} is not a valid number.") from exc
        if not math.isfinite(val):
            raise FeatureInputError(f"{label}: values must be finite.")
        out.append(val)
    return out


def parse_pairs(raw: str, label: str = "Pairs") -> list[tuple[float, float]]:
    """Parse ``x, y`` numeric pairs from lines or semicolon-separated text."""
    pairs: list[tuple[float, float]] = []
    for line in re.split(r"[\r\n;]+", raw.strip()):
        s = line.strip()
        if not s:
            continue
        parts = [p for p in re.split(r"[\s,]+", s) if p]
        if len(parts) < 2:
            raise FeatureInputError(f"{label}: each line needs two numbers, got {s!r}.")
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise FeatureInputError(f"{label}: invalid number in {s!r}.") from exc
        if not (math.isfinite(x) and math.isfinite(y)):
            raise FeatureInputError(f"{label}: values must be finite.")
        pairs.append((x, y))
    if not pairs:
        raise FeatureInputError(f"Enter at least one pair for {label}.")
    return pairs


def parse_csv_rows(raw: str, label: str = "CSV data") -> list[dict[str, str]]:
    """Parse CSV text with a header row into stripped dict rows."""
    cleaned = "\n".join(line.strip() for line in raw.strip().splitlines() if line.strip())
    if not cleaned:
        raise FeatureInputError(f"Provide {label} with a header row and at least one data row.")
    reader = csv.DictReader(io.StringIO(cleaned))
    rows = [
        {str(k).strip(): str(v).strip() for k, v in row.items() if k is not None} for row in reader
    ]
    if not rows:
        raise FeatureInputError(f"{label} must contain at least one data row.")
    return rows


def list_bim_elements(ctx: FeatureContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (elements, stories) from 06 BIM/bim.json."""
    raw = ctx.raw("bim")
    if not isinstance(raw, dict):
        return [], []
    els = raw.get("elements")
    sts = raw.get("stories")
    return (
        [e for e in els if isinstance(e, dict)] if isinstance(els, list) else [],
        [s for s in sts if isinstance(s, dict)] if isinstance(sts, list) else [],
    )


def list_objects(ctx: FeatureContext) -> list[dict[str, Any]]:
    """Return object definitions from 04 Objects/objects.json."""
    raw = ctx.raw("objects")
    if not isinstance(raw, dict):
        return []
    objs = raw.get("objects")
    return [o for o in objs if isinstance(o, dict)] if isinstance(objs, list) else []


def list_materials(ctx: FeatureContext) -> list[dict[str, Any]]:
    """Return materials list from 03 Materials/materials.json."""
    raw = ctx.raw("materials")
    if not isinstance(raw, dict):
        return []
    mats = raw.get("materials")
    return [m for m in mats if isinstance(m, dict)] if isinstance(mats, list) else []


def pack_summary_choices(pack: Any) -> dict[str, list[dict[str, str]]]:
    """Return pack_choices(pack) safely."""
    try:
        return pack_choices(pack)
    except Exception:  # noqa: BLE001
        return {}


def json_dumps_clean(data: Any) -> str:
    """Format JSON cleanly with UTF-8 indentation."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

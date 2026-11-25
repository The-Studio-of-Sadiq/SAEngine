"""Shared helpers for Materials library features (``03 Materials``)."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from pathlib import Path
from typing import Any

from saengine.features import FeatureContext, FeatureInputError
from saengine.library.defaults import default_material_library
from saengine.library.materials import Material, MaterialLibrary


def load_materials(ctx: FeatureContext) -> MaterialLibrary | None:
    """Return the validated project MaterialLibrary, or None if no project/file."""
    raw = ctx.raw("materials")
    if raw is None:
        return None
    try:
        return MaterialLibrary.model_validate(raw)
    except Exception as exc:
        raise FeatureInputError(f"03 Materials/materials.json is invalid: {exc}") from exc


def require_materials(ctx: FeatureContext) -> MaterialLibrary:
    """Return the project MaterialLibrary or raise FeatureInputError."""
    lib = load_materials(ctx)
    if lib is None:
        raise FeatureInputError("Open a project with 03 Materials/materials.json first.")
    return lib


def materials_or_default(ctx: FeatureContext) -> tuple[MaterialLibrary, bool]:
    """Return (MaterialLibrary, is_project) falling back to the built-in default set."""
    lib = load_materials(ctx)
    if lib is not None:
        return lib, True
    return default_material_library(), False


def require_project_root(ctx: FeatureContext) -> Path:
    """Return the project root Path or raise FeatureInputError."""
    if ctx.root is None:
        raise FeatureInputError("Open a project folder first.")
    return ctx.root


def save_export(ctx: FeatureContext, filename: str, content: str | bytes) -> Path:
    """Write an export file under ``03 Materials/exports/<filename>``."""
    require_project_root(ctx)
    target = ctx.path(f"03 Materials/exports/{filename}")
    if target is None:
        raise FeatureInputError("Open a project folder first.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target


def parse_numbers(raw: str, label: str = "Values") -> list[float]:
    """Parse comma, whitespace, or newline separated numbers."""
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
            raise FeatureInputError(f"{label}: values must be finite numbers.")
        out.append(val)
    return out


def parse_pairs(raw: str, label: str = "Data pairs") -> list[tuple[float, float]]:
    """Parse ``x, y`` numeric pairs from lines or semicolon-separated text."""
    pairs: list[tuple[float, float]] = []
    for line in re.split(r"[\r\n;]+", raw.strip()):
        s = line.strip()
        if not s:
            continue
        parts = [p for p in re.split(r"[\s,]+", s) if p]
        if len(parts) < 2:
            raise FeatureInputError(f"{label}: each line needs two numbers (x, y), got {s!r}.")
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


def parse_csv_rows(raw: str) -> list[dict[str, str]]:
    """Parse CSV text with a header row into stripped dict rows."""
    text_clean = raw.strip()
    if not text_clean:
        raise FeatureInputError("Provide CSV input with a header row.")
    reader = csv.DictReader(io.StringIO(text_clean))
    if not reader.fieldnames:
        raise FeatureInputError("CSV input needs a header row.")
    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}
        if any(cleaned.values()):
            rows.append(cleaned)
    if not rows:
        raise FeatureInputError("CSV input contains no data rows.")
    return rows


def find_material(lib: MaterialLibrary, identifier: str) -> Material | None:
    """Find a material by exact ID, case-insensitive ID, or name substring."""
    ident = identifier.strip()
    if not ident:
        return lib.materials[0] if lib.materials else None
    exact = lib.get(ident)
    if exact is not None:
        return exact
    low = ident.lower()
    for mat in lib.materials:
        if mat.id.lower() == low or mat.name.lower() == low:
            return mat
    for mat in lib.materials:
        if low in mat.id.lower() or low in mat.name.lower():
            return mat
    return None


def material_strength_mpa(mat: Material) -> float | None:
    """Return primary characteristic strength [MPa] of a material if present."""
    if mat.concrete is not None:
        return float(mat.concrete.fc)
    if mat.steel is not None:
        return float(mat.steel.fy)
    if mat.masonry is not None:
        return mat.masonry.fm or mat.masonry.unitStrength
    if mat.ferrocement is not None:
        return float(mat.ferrocement.fc)
    return None


def project_material_usage(ctx: FeatureContext) -> dict[str, int]:
    """Count how many object types / BOQ items reference each material ID."""
    counts: dict[str, int] = {}
    objects = ctx.raw("objects") or {}
    for obj in objects.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        for key in ("material",):
            mid = obj.get(key)
            if isinstance(mid, str) and mid:
                counts[mid] = counts.get(mid, 0) + 1
        reinf = obj.get("reinforcement")
        if isinstance(reinf, dict):
            rmid = reinf.get("material")
            if isinstance(rmid, str) and rmid:
                counts[rmid] = counts.get(rmid, 0) + 1
    boq = ctx.raw("boq") or {}
    for mid in (boq.get("source") or {}).get("materialIds") or []:
        if isinstance(mid, str) and mid:
            counts[mid] = counts.get(mid, 0) + 1
    return counts


def safe_json(data: Any) -> str:
    """Serialize data deterministically to indented JSON."""
    return json.dumps(data, indent=2, sort_keys=False) + "\n"

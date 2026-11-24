"""Shared IO, parsing, and geometry/library helpers for Objects & Section Designer features."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from pathlib import Path
from typing import Any

from saengine.features import FeatureContext, FeatureInputError
from saengine.library import objects as o
from saengine.library.defaults import default_material_library, default_object_library
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.section_designer import DesignedSection, Region, list_sections, load_section


def require_root(ctx: FeatureContext, purpose: str = "this feature") -> Path:
    """Return the project root path or raise a clear FeatureInputError."""
    if ctx.root is None or not ctx.root.exists():
        raise FeatureInputError(f"Open a project folder before running {purpose}.")
    return ctx.root


def load_objects(ctx: FeatureContext) -> ObjectLibrary | None:
    """Return the validated project ObjectLibrary, or None when no project/file exists."""
    raw = ctx.raw("objects")
    if raw is None:
        return None
    try:
        return ObjectLibrary.model_validate(raw)
    except Exception as exc:
        raise FeatureInputError(f"04 Objects/objects.json is invalid: {exc}") from exc


def require_objects(ctx: FeatureContext) -> ObjectLibrary:
    """Return the project ObjectLibrary or raise FeatureInputError."""
    lib = load_objects(ctx)
    if lib is None:
        raise FeatureInputError("Open a project with 04 Objects/objects.json first.")
    return lib


def objects_or_default(ctx: FeatureContext) -> tuple[ObjectLibrary, bool]:
    """Return (ObjectLibrary, is_project) falling back to the built-in default library."""
    lib = load_objects(ctx)
    if lib is not None:
        return lib, True
    return default_object_library(), False


def load_materials(ctx: FeatureContext) -> MaterialLibrary | None:
    """Return the validated project MaterialLibrary, or None if missing."""
    raw = ctx.raw("materials")
    if raw is None:
        return None
    try:
        return MaterialLibrary.model_validate(raw)
    except Exception as exc:
        raise FeatureInputError(f"03 Materials/materials.json is invalid: {exc}") from exc


def materials_or_default(ctx: FeatureContext) -> tuple[MaterialLibrary, bool]:
    """Return (MaterialLibrary, is_project) falling back to the built-in default materials."""
    lib = load_materials(ctx)
    if lib is not None:
        return lib, True
    return default_material_library(), False


def save_export(ctx: FeatureContext, filename: str, content: str | bytes) -> Path:
    """Write an export file under ``04 Objects/exports/<filename>``."""
    require_root(ctx, "exporting")
    target = ctx.path(f"04 Objects/exports/{filename}")
    if target is None:
        raise FeatureInputError("Open a project folder first.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target


def parse_points(raw: str, label: str = "Polygon points") -> list[tuple[float, float]]:
    """Parse ``x, y`` coordinate pairs (mm) from newline or semicolon-separated text."""
    pts: list[tuple[float, float]] = []
    for line in re.split(r"[\r\n;]+", raw.strip()):
        s = line.strip()
        if not s:
            continue
        parts = [p for p in re.split(r"[\s,]+", s) if p]
        if len(parts) < 2:
            raise FeatureInputError(f"{label}: expected x, y coordinates on line {s!r}.")
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise FeatureInputError(f"{label}: invalid number on line {s!r}.") from exc
        if not (math.isfinite(x) and math.isfinite(y)):
            raise FeatureInputError(f"{label}: coordinates must be finite numbers.")
        pts.append((x, y))
    if len(pts) < 3:
        raise FeatureInputError(f"{label}: provide at least 3 points.")
    return pts


def parse_bars_spec(raw: str, default_dia: float = 20.0) -> list[tuple[float, float, float]]:
    """Parse ``x, y[, dia]`` bar definitions from lines or semicolon-separated text."""
    bars: list[tuple[float, float, float]] = []
    for line in re.split(r"[\r\n;]+", raw.strip()):
        s = line.strip()
        if not s:
            continue
        parts = [p for p in re.split(r"[\s,]+", s) if p]
        if len(parts) < 2:
            raise FeatureInputError(f"Bar coordinates: expected x, y[, dia] on line {s!r}.")
        try:
            x, y = float(parts[0]), float(parts[1])
            dia = float(parts[2]) if len(parts) >= 3 else default_dia
        except ValueError as exc:
            raise FeatureInputError(f"Bar coordinates: invalid number on line {s!r}.") from exc
        if dia <= 0 or not (math.isfinite(x) and math.isfinite(y) and math.isfinite(dia)):
            raise FeatureInputError(
                f"Bar coordinates: invalid bar diameter or coordinate in {s!r}."
            )
        bars.append((x, y, dia))
    return bars


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


def parse_numbers(raw: str, label: str = "Values") -> list[float]:
    """Parse comma, whitespace, or semicolon separated numbers."""
    tokens = [t for t in re.split(r"[\s,;]+", raw.strip()) if t]
    if not tokens:
        raise FeatureInputError(f"Enter at least one number for {label}.")
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


def rect_outline(
    width: float, depth: float, cx: float = 0.0, cy: float = 0.0
) -> list[tuple[float, float]]:
    """Return counter-clockwise rectangle corners centred at (cx, cy) [mm]."""
    hx, hy = width / 2.0, depth / 2.0
    return [(cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy), (cx - hx, cy + hy)]


def perimeter_bars_rect(
    width: float, depth: float, cover: float, dia: float, nx: int, ny: int
) -> list[tuple[float, float, float]]:
    """Generate perimeter longitudinal bar coordinates inside a rectangle centred at (0, 0)."""
    inset = cover + 10.0 + dia / 2.0
    x_lim = width / 2.0 - inset
    y_lim = depth / 2.0 - inset
    if x_lim <= 0 or y_lim <= 0:
        raise FeatureInputError("Cover and bar diameter exceed section half-dimensions.")
    pts: dict[tuple[float, float], float] = {}
    for i in range(max(2, nx)):
        x = -x_lim + 2.0 * x_lim * i / (max(2, nx) - 1)
        pts[(round(x, 3), round(y_lim, 3))] = dia
        pts[(round(x, 3), round(-y_lim, 3))] = dia
    for j in range(1, max(2, ny) - 1):
        y = -y_lim + 2.0 * y_lim * j / (max(2, ny) - 1)
        pts[(round(-x_lim, 3), round(y, 3))] = dia
        pts[(round(x_lim, 3), round(y, 3))] = dia
    return [(x, y, d) for (x, y), d in pts.items()]


def resolve_or_build_section(
    ctx: FeatureContext,
    section_id: str,
    width_mm: float = 400.0,
    depth_mm: float = 600.0,
    cover_mm: float = 40.0,
    bar_dia_mm: float = 20.0,
    n_top: int = 4,
    n_bottom: int = 4,
    concrete_id: str = "",
    rebar_id: str = "",
) -> tuple[DesignedSection, MaterialLibrary, str]:
    """Load a designed section from ``04 Objects/sections`` or build an RC rectangle from inputs."""
    mats, _ = materials_or_default(ctx)
    conc = concrete_id.strip() or next(
        (m.id for m in mats.materials if m.category.value == "concrete"), "C24.1"
    )
    reb = rebar_id.strip() or next(
        (m.id for m in mats.materials if m.category.value == "rebar"), "B420DWR"
    )
    sid = section_id.strip()
    if sid and ctx.root is not None:
        avail = list_sections(ctx.root)
        if sid in avail:
            return load_section(ctx.root, sid), mats, f"Project section {sid}"
        obj_lib = load_objects(ctx)
        if obj_lib is not None:
            obj = next((x for x in obj_lib.objects if x.id.lower() == sid.lower()), None)
            if obj is not None and getattr(obj, "profile", None) is not None:
                prof = obj.profile
                if isinstance(prof, o.DesignedProfile):
                    return load_section(ctx.root, prof.section), mats, f"Object {obj.id} section"
                if isinstance(prof, o.RectangleProfile):
                    width_mm, depth_mm = prof.xDim, prof.yDim
                    conc = obj.material
    bars_xy = []
    inset = cover_mm + 10.0 + bar_dia_mm / 2.0
    x_lim = max(10.0, width_mm / 2.0 - inset)
    y_lim = max(10.0, depth_mm / 2.0 - inset)
    for count, y_pos in ((max(2, n_top), y_lim), (max(2, n_bottom), -y_lim)):
        for i in range(count):
            x_pos = -x_lim + 2.0 * x_lim * i / (count - 1)
            bars_xy.append({"x": round(x_pos, 2), "y": round(y_pos, 2), "dia": bar_dia_mm})
    sec = DesignedSection(
        id=sid or "RECT-DESIGNED",
        name=f"Rectangular {width_mm:g}x{depth_mm:g}",
        regions=[Region(outline=rect_outline(width_mm, depth_mm), material=conc, label="Core")],
        bars=bars_xy,
        rebar=reb,
        cover=cover_mm,
    )
    return sec, mats, "Parametric rectangular RC section"


def find_object(lib: ObjectLibrary, object_id: str) -> Any:
    """Find an object type by exact or case-insensitive id."""
    ident = object_id.strip()
    if not ident:
        if not lib.objects:
            raise FeatureInputError("No object types found in 04 Objects/objects.json.")
        return lib.objects[0]
    for obj in lib.objects:
        if obj.id.lower() == ident.lower():
            return obj
    avail = ", ".join(obj.id for obj in lib.objects[:10])
    raise FeatureInputError(f"Object type '{ident}' not found (available: {avail}).")


def used_type_ids(ctx: FeatureContext) -> dict[str, int]:
    """Count placements of each object type ID across BIM and Floor Plan."""
    counts: dict[str, int] = {}
    bim = ctx.raw("bim") or {}
    for el in bim.get("elements") or []:
        if isinstance(el, dict):
            tid = el.get("type")
            if isinstance(tid, str) and tid:
                counts[tid] = counts.get(tid, 0) + 1
    fp = ctx.raw("floorPlan") or {}
    for group in ("columns", "beams", "walls", "slabs", "footings"):
        for el in fp.get(group) or []:
            if isinstance(el, dict):
                tid = el.get("type")
                if isinstance(tid, str) and tid:
                    counts[tid] = counts.get(tid, 0) + 1
    return counts


def safe_json(data: Any) -> str:
    """Serialize data deterministically to indented JSON."""
    return json.dumps(data, indent=2, sort_keys=False) + "\n"

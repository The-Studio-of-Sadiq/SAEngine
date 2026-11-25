"""Shared project-file, serialization and safe output helpers for export tools."""

from __future__ import annotations

import csv
import ctypes
import io
import json
import re
from pathlib import Path
from typing import Any

from saengine.features import FeatureContext, FeatureInputError


def output_path(ctx: FeatureContext, name: str, folder: str = "") -> Path:
    """Resolve an output filename under ``11 Exports`` and reject path traversal."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to write this export.")
    clean = re.sub(r"[^A-Za-z0-9._ -]", "-", name).strip(" .") or "export"
    relative = Path("11 Exports") / folder / clean
    root = ctx.root.resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise FeatureInputError("The output path must stay inside the project folder.")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def write_export_text(ctx: FeatureContext, name: str, data: str, folder: str = "") -> str:
    """Write a UTF-8 project deliverable and return its project-relative path."""
    target = output_path(ctx, name, folder)
    target.write_text(data, encoding="utf-8", newline="\n")
    return target.relative_to(ctx.root).as_posix()


def write_export_bytes(ctx: FeatureContext, name: str, data: bytes, folder: str = "") -> str:
    """Write binary project deliverable bytes and return the relative path."""
    target = output_path(ctx, name, folder)
    target.write_bytes(data)
    return target.relative_to(ctx.root).as_posix()


def write_export_json(ctx: FeatureContext, name: str, data: Any, folder: str = "") -> str:
    """Write readable UTF-8 JSON into the project's exports folder."""
    return write_export_text(
        ctx, name, json.dumps(data, indent=2, ensure_ascii=False) + "\n", folder
    )


def csv_document(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    """Serialize record rows as readable UTF-8 CSV."""
    fields = columns or list(dict.fromkeys(key for row in rows for key in row))
    if not fields:
        raise FeatureInputError("There are no data columns to export.")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def project_file_rows(ctx: FeatureContext, limit: int = 20000) -> list[dict[str, Any]]:
    """Inventory non-hidden project files without traversing the version-control folder."""
    if ctx.root is None or not ctx.root.is_dir():
        raise FeatureInputError("Open a project folder to inventory its files.")
    result = []
    for path in sorted(ctx.root.rglob("*")):
        relative = path.relative_to(ctx.root)
        if ".git" in relative.parts or any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_file():
            try:
                stat = path.stat()
            except OSError:
                continue
            result.append(
                {
                    "path": relative.as_posix(),
                    "sizeBytes": stat.st_size,
                    "modifiedNs": stat.st_mtime_ns,
                }
            )
            if len(result) >= limit:
                break
    return result


def model_elements(ctx: FeatureContext) -> list[dict[str, Any]]:
    """Read the project's BIM element records or explain what is missing."""
    data = ctx.raw("bim")
    rows = data.get("elements") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise FeatureInputError("Add building elements to 06 BIM before exporting a model.")
    return [row for row in rows if isinstance(row, dict)]


def coordinate_rows(ctx: FeatureContext) -> list[dict[str, Any]]:
    """Flatten BIM element centerlines and planar boundaries into source-linked coordinate records."""
    rows = model_elements(ctx)
    coordinates = []
    for element in rows:
        kind = str(element.get("kind", element.get("type", "element")))
        identifier = str(element.get("id", f"E{len(coordinates) + 1}"))
        for point_key in ("start", "end", "position", "outline", "boundary"):
            value = element.get(point_key)
            if isinstance(value, dict) and "x" in value and "y" in value:
                coordinates.append(
                    {
                        "element": identifier,
                        "kind": kind,
                        "role": point_key,
                        "xMm": float(value["x"]),
                        "yMm": float(value["y"]),
                        "zMm": float(element.get("elevation", element.get("top", 0))),
                    }
                )
            elif isinstance(value, list):
                for index, point in enumerate(value):
                    if isinstance(point, dict) and "x" in point and "y" in point:
                        coordinates.append(
                            {
                                "element": identifier,
                                "kind": kind,
                                "role": f"{point_key}{index + 1}",
                                "xMm": float(point["x"]),
                                "yMm": float(point["y"]),
                                "zMm": float(point.get("z", element.get("elevation", 0))),
                            }
                        )
    if not coordinates:
        raise FeatureInputError("The BIM elements have no usable coordinates to export.")
    return coordinates


def require_source(ctx: FeatureContext, relative: str) -> Path:
    """Resolve an existing relative project file for an export operation."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to read this source file.")
    root = ctx.root.resolve()
    source = (root / relative).resolve()
    if root not in source.parents or not source.is_file():
        raise FeatureInputError(f"Source file does not exist inside the project: {relative}")
    return source


def protect_for_current_windows_user(data: bytes) -> bytes:
    """Protect bytes with Windows DPAPI, scoped to the current user's profile."""
    if not hasattr(ctypes, "windll"):
        raise FeatureInputError(
            "Windows DPAPI is required for this local-user encryption operation."
        )

    class DataBlob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    protected = DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "SAEngine export", None, None, None, 1, ctypes.byref(protected)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(protected.data, protected.size)
    finally:
        kernel32.LocalFree(protected.data)

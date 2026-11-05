"""Point-cloud references (alpha 9 L2): a laser scan as an underlay of a story's plan and of the
building model view, with snap and trace tools for as-built input.

**Formats.** LAS 1.2-1.4, uncompressed, point data formats 0-10 (:func:`read_las`, numpy only:
the header, the scaled X, Y, Z of every record, the intensity and the classification) and text
scans: XYZ / TXT / CSV (``x y z ...`` per line) and PTS (a count line first) (:func:`read_text`).
LAZ (compressed LAS) and E57 need a library that is not bundled (``lazrs`` or ``laszip`` for
LAZ, ``pye57`` for E57): they are refused with a message saying so, until the owner adds the
dependency.

**Decimation** (:func:`decimate`): one point per cube of ``voxel`` (the first one met: the scan
order, no averaging), then at most ``limit`` points by an even stride.

**Underlay of a plan** (:func:`convert`): the points between ``cut - thickness/2`` and ``cut +
thickness/2`` (in the cloud's units; the cut is the story's level plus the cut height, as the
floor plan asks for it), decimated in plan, written as a DXF (each point a short dash on layer
``CLOUD``, as a CAD program draws a point cloud slice) with the lines traced through them on
layer ``TRACED`` (:func:`trace_lines`): walls and edges as straight segments found by RANSAC
(repeatedly: the line through two random points with the most points within ``tolerance``, its
extent along the line split where the points are further apart than ``gap``, kept when at
least ``min_points`` and ``min_length``). The traced segments are the floor plan's object snaps
(as a PDF underlay's lines), so walls, columns and grids can be drawn over the scan.

**Snap** (:func:`snap`): the nearest slice point to a picked point within a radius
(scipy's KD tree).

The DXF and the traced segments are cached in ``.cloud-cache`` beside the scan (left out of
archives) and read again while the scan and the slice settings are unchanged.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "CACHE_FOLDER",
    "Cloud",
    "PointCloudError",
    "convert",
    "decimate",
    "read_cloud",
    "read_las",
    "read_text",
    "slice_plan",
    "snap",
    "to_dxf",
    "trace_lines",
    "view_points",
]

CACHE_FOLDER = ".cloud-cache"
#: Bumped when the output changes, so older cached copies convert again.
VERSION = 1
#: Text and LAS scans this module reads; the others need a library.
READABLE = (".las", ".xyz", ".txt", ".csv", ".pts")
NEEDS_LIBRARY = {".laz": "lazrs or laszip", ".e57": "pye57"}
#: At most this many points go into a plan slice's DXF and into the 3D view.
MAX_SLICE_POINTS = 40000
MAX_VIEW_POINTS = 200000
#: At most this many traced segments are sent to the floor plan for object snaps.
MAX_SNAP_SEGMENTS = 2000


class PointCloudError(ValueError):
    """A scan that cannot be read (with the reason)."""


@dataclass
class Cloud:
    """Points (n, 3) in the file's units, with intensity and classification when it has them."""

    points: np.ndarray
    intensity: np.ndarray | None = None
    classification: np.ndarray | None = None
    units: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def bounds(self) -> list[float]:
        if not len(self.points):
            return [0.0] * 6
        lo, hi = self.points.min(axis=0), self.points.max(axis=0)
        return [float(v) for v in (*lo, *hi)]


# ─────────────────────────────────────── LAS ───────────────────────────────────────

_HEADER = struct.Struct("<4sHH16sBB32s32sHHHIIBHI5I3d3d6d")


def read_las(path: str | Path, limit: int | None = None) -> Cloud:
    """The points of an uncompressed LAS 1.2-1.4 file (formats 0-10); ``limit``: read at most
    this many records (an even stride over the file). Raises :class:`PointCloudError`."""
    path = Path(path)
    with path.open("rb") as f:
        head = f.read(375)
    if len(head) < _HEADER.size or head[:4] != b"LASF":
        raise PointCloudError(f"{path.name} is not a LAS file")
    fields = _HEADER.unpack_from(head)
    major, minor = fields[4], fields[5]
    header_size, offset, _vlrs, fmt_byte, length, legacy = fields[10:16]
    scale = np.array(fields[21:24])
    origin = np.array(fields[24:27])
    if major != 1 or minor not in (0, 1, 2, 3, 4):
        raise PointCloudError(f"{path.name}: LAS {major}.{minor} is not supported (1.0-1.4)")
    if fmt_byte & 0xC0:
        raise PointCloudError(
            f"{path.name} is compressed (LAZ): it needs {NEEDS_LIBRARY['.laz']}, which SAEngine "
            "does not bundle; ask the owner before adding it, or save the scan as LAS"
        )
    fmt = fmt_byte & 0x3F
    if fmt > 10:
        raise PointCloudError(f"{path.name}: point data format {fmt} is not supported (0-10)")
    count = int(legacy)
    if minor >= 4 and header_size >= 255 and len(head) >= 255:
        (count14,) = struct.unpack_from("<Q", head, 247)
        count = int(count14) or count
    size = path.stat().st_size
    count = min(count, (size - offset) // length) if length else 0
    if count <= 0:
        return Cloud(np.zeros((0, 3)), notes=[f"{path.name} has no points"])
    class_at = 16 if fmt >= 6 else 15
    dtype = np.dtype(
        {
            "names": ["x", "y", "z", "intensity", "classification"],
            "formats": ["<i4", "<i4", "<i4", "<u2", "u1"],
            "offsets": [0, 4, 8, 12, class_at],
            "itemsize": length,
        }
    )
    records = np.memmap(path, dtype=dtype, mode="r", offset=offset, shape=(count,))
    if limit is not None and count > limit:
        records = records[:: math.ceil(count / limit)]
    xyz = np.column_stack([records["x"], records["y"], records["z"]]).astype(float)
    points = xyz * scale + origin
    classification = np.asarray(records["classification"])
    if fmt < 6:
        classification = classification & 0x1F
    out = Cloud(points, np.asarray(records["intensity"], dtype=float), classification)
    del records
    return out


# ─────────────────────────────────────── text scans ───────────────────────────────────────


def read_text(path: str | Path, limit: int | None = None) -> Cloud:
    """The points of an XYZ / TXT / CSV / PTS scan: x y z as the first three numbers of each
    line (commas, semicolons or spaces between them), a PTS file's count line skipped; a
    fourth number is taken as the intensity. Lines that are not numbers are skipped."""
    path = Path(path)
    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.replace(",", " ").replace(";", " ").split()
            if len(parts) < 3:
                continue
            try:
                values = [float(v) for v in parts[:4]]
            except ValueError:
                continue
            rows.append(values if len(values) == 4 else [*values, math.nan])
    if not rows:
        return Cloud(np.zeros((0, 3)), notes=[f"{path.name} has no points"])
    data = np.asarray(rows, dtype=float)
    if limit is not None and len(data) > limit:
        data = data[:: math.ceil(len(data) / limit)]
    intensity = data[:, 3] if not np.all(np.isnan(data[:, 3])) else None
    return Cloud(data[:, :3], intensity)


def read_cloud(path: str | Path, limit: int | None = None) -> Cloud:
    """A scan of any format this module reads (see the module notes)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in NEEDS_LIBRARY:
        raise PointCloudError(
            f"{path.name}: {suffix[1:].upper()} scans need {NEEDS_LIBRARY[suffix]}, which "
            "SAEngine does not bundle; ask the owner before adding it, or save the scan as LAS "
            "or XYZ"
        )
    if not path.is_file():
        raise PointCloudError(f"{path.name} does not exist")
    if suffix == ".las":
        return read_las(path, limit)
    if suffix in READABLE:
        return read_text(path, limit)
    raise PointCloudError(
        f"{path.name}: not a point cloud this program reads ({', '.join(READABLE)})"
    )


# ─────────────────────────────────────── processing ───────────────────────────────────────


def decimate(points: np.ndarray, voxel: float, limit: int | None = None) -> np.ndarray:
    """The indices of the points kept: one per cube of side ``voxel`` (the first in the
    file's order; ``voxel`` 0: all), then at most ``limit`` by an even stride."""
    n = len(points)
    if n == 0:
        return np.zeros(0, dtype=int)
    if voxel > 0:
        keys = np.floor((points - points.min(axis=0)) / voxel).astype(np.int64)
        _, first = np.unique(keys, axis=0, return_index=True)
        kept = np.sort(first)
    else:
        kept = np.arange(n)
    if limit is not None and len(kept) > limit:
        kept = kept[:: math.ceil(len(kept) / limit)]
    return kept


def slice_plan(points: np.ndarray, cut: float, thickness: float) -> np.ndarray:
    """The plan (x, y) of the points within ``thickness / 2`` of the level ``cut``."""
    if not len(points):
        return np.zeros((0, 2))
    inside = np.abs(points[:, 2] - cut) <= thickness / 2
    return points[inside, :2]


def trace_lines(
    plan: np.ndarray,
    tolerance: float,
    min_points: int = 30,
    min_length: float | None = None,
    gap: float | None = None,
    tries: int = 300,
    max_lines: int = 200,
    seed: int = 1,
) -> list[list[float]]:
    """Straight segments ``[x1, y1, x2, y2]`` through the plan points (see the module notes);
    deterministic for one ``seed``. ``min_length`` default 20 × tolerance, ``gap`` 10 ×."""
    rng = np.random.default_rng(seed)
    min_length = 20 * tolerance if min_length is None else min_length
    gap = 10 * tolerance if gap is None else gap
    left = np.asarray(plan, dtype=float)
    out: list[list[float]] = []
    misses = 0
    while len(left) >= min_points and len(out) < max_lines and misses < 5:
        best: np.ndarray | None = None
        best_dir = None
        for _ in range(tries):
            i, j = rng.choice(len(left), 2, replace=False)
            d = left[j] - left[i]
            norm = math.hypot(*d)
            if norm < tolerance:
                continue
            u = d / norm
            normal = np.array([-u[1], u[0]])
            near = np.abs((left - left[i]) @ normal) <= tolerance
            if best is None or near.sum() > best.sum():
                best, best_dir = near, (left[i], u)
        if best is None or best.sum() < min_points:
            break
        origin, u = best_dir
        members = left[best]
        t = (members - origin) @ u
        order = np.argsort(t)
        t = t[order]
        found = False
        start = 0
        for k in range(1, len(t) + 1):
            if k == len(t) or t[k] - t[k - 1] > gap:
                run = k - start
                if run >= min_points and t[k - 1] - t[start] >= min_length:
                    # a least-squares fit of the run for the segment's direction
                    pts = members[order[start:k]]
                    centre = pts.mean(axis=0)
                    _, _, axes = np.linalg.svd(pts - centre, full_matrices=False)
                    v = axes[0]
                    s = (pts - centre) @ v
                    a, b = centre + v * s.min(), centre + v * s.max()
                    out.append([float(a[0]), float(a[1]), float(b[0]), float(b[1])])
                    found = True
                start = k
        left = left[~best]
        misses = 0 if found else misses + 1
    return out


def snap(plan: np.ndarray, x: float, y: float, radius: float) -> list[float] | None:
    """The nearest plan point to (x, y) within ``radius``, or None."""
    if not len(plan):
        return None
    from scipy.spatial import cKDTree

    distance, index = cKDTree(plan).query([x, y], distance_upper_bound=radius)
    if not math.isfinite(distance):
        return None
    return [float(plan[index][0]), float(plan[index][1])]


# ─────────────────────────────────────── outputs ───────────────────────────────────────


def to_dxf(plan: np.ndarray, segments: list[list[float]], dash: float) -> str:
    """The slice as DXF text: a dash of ``dash`` per point on ``CLOUD``, the traced segments on
    ``TRACED``."""
    import io

    import ezdxf

    doc = ezdxf.new("R2010")
    doc.layers.add("CLOUD", color=8)
    doc.layers.add("TRACED", color=1)
    msp = doc.modelspace()
    h = dash / 2
    for x, y in plan:
        msp.add_line((x - h, y), (x + h, y), dxfattribs={"layer": "CLOUD"})
    for x1, y1, x2, y2 in segments:
        msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": "TRACED"})
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue()


@dataclass
class Conversion:
    dxf: Path
    points: int
    total: int
    segments: list[list[float]]
    bounds: list[float]
    warnings: list[str]
    cached: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "dxf": str(self.dxf),
            "points": self.points,
            "total": self.total,
            "segments": self.segments,
            "bounds": self.bounds,
            "warnings": self.warnings,
            "cached": self.cached,
        }


def _stamp(path: Path, settings: dict[str, Any]) -> str:
    stat = path.stat()
    text = json.dumps([VERSION, stat.st_size, stat.st_mtime_ns, settings], sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()


def convert(
    path: str | Path,
    cut: float,
    thickness: float,
    voxel: float = 0.0,
    tolerance: float | None = None,
    trace: bool = True,
    cache: str | Path | None = None,
) -> Conversion:
    """A plan slice of the scan at level ``cut`` as DXF (see the module notes), in the cloud's
    units: ``thickness`` of the slice, ``voxel`` its decimation (0: by the point limit only),
    ``tolerance`` of the traced lines (default the voxel, else thickness / 10). Raises
    :class:`PointCloudError`."""
    path = Path(path)
    if thickness <= 0:
        raise PointCloudError("the slice thickness must be positive")
    tolerance = float(tolerance or voxel or thickness / 10)
    settings = {
        "cut": cut,
        "thickness": thickness,
        "voxel": voxel,
        "tolerance": tolerance,
        "trace": trace,
    }
    folder = Path(cache) if cache else path.parent / CACHE_FOLDER
    key = hashlib.sha1(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:10]
    dxf = folder / f"{path.name}.{key}.dxf"
    meta = folder / f"{path.name}.{key}.json"
    stamp = _stamp(path, settings) if path.is_file() else ""
    with contextlib.suppress(OSError, ValueError, TypeError, KeyError):
        known = json.loads(meta.read_text(encoding="utf-8"))
        if known.get("source") == stamp and dxf.is_file():
            return Conversion(
                dxf,
                int(known["points"]),
                int(known["total"]),
                list(known["segments"]),
                list(known["bounds"]),
                list(known.get("warnings", [])),
                cached=True,
            )
    cloud = read_cloud(path)
    warnings = list(cloud.notes)
    plan = slice_plan(cloud.points, cut, thickness)
    if not len(plan):
        warnings.append(
            f"no points within {thickness / 2:g} of the level {cut:g} (the scan's heights run "
            f"from {cloud.bounds[2]:g} to {cloud.bounds[5]:g}): check the cut height and the "
            "scan's units"
        )
    kept = decimate(np.column_stack([plan, np.zeros(len(plan))]), voxel, MAX_SLICE_POINTS)
    plan = plan[kept]
    segments = trace_lines(plan, tolerance) if trace and len(plan) else []
    if len(segments) > MAX_SNAP_SEGMENTS:
        warnings.append(f"more than {MAX_SNAP_SEGMENTS} traced lines: the snaps use the first")
        segments = segments[:MAX_SNAP_SEGMENTS]
    folder.mkdir(parents=True, exist_ok=True)
    dxf.write_text(to_dxf(plan, segments, max(tolerance, thickness / 20)), encoding="utf-8")
    result = Conversion(dxf, len(plan), len(cloud.points), segments, cloud.bounds, warnings)
    with contextlib.suppress(OSError):
        meta.write_text(
            json.dumps(
                {
                    "source": stamp,
                    **{k: v for k, v in result.to_json().items() if k not in ("dxf", "cached")},
                }
            ),
            encoding="utf-8",
        )
    return result


def view_points(
    path: str | Path, voxel: float = 0.0, limit: int = MAX_VIEW_POINTS
) -> dict[str, Any]:
    """The scan decimated for the 3D view: ``{"positions": [x, y, z, ...] (flat), "colors":
    [r, g, b, ...] in 0-1 by intensity (grey) or None, "count", "total", "bounds"}`` in the
    cloud's units."""
    cloud = read_cloud(path)
    kept = decimate(cloud.points, voxel, limit)
    points = cloud.points[kept]
    colors = None
    if cloud.intensity is not None and len(kept):
        values = cloud.intensity[kept]
        lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
        grey = (values - lo) / (hi - lo) if hi > lo else np.full(len(values), 0.6)
        grey = np.nan_to_num(0.25 + 0.7 * grey, nan=0.6)
        colors = np.repeat(grey[:, None], 3, axis=1).ravel().round(3).tolist()
    return {
        "positions": points.ravel().round(4).tolist(),
        "colors": colors,
        "count": len(points),
        "total": len(cloud.points),
        "bounds": cloud.bounds,
        "notes": cloud.notes,
    }

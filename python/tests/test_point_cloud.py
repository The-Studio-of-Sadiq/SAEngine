"""Alpha 9 L2: point-cloud references (LAS / XYZ readers, decimation, plan slices, traced lines,
snaps, the DXF underlay) (written 2026-11-05, not run yet: the test pass is next week)."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from saengine.library import point_cloud as pcl


def _write_las(path: Path, points: np.ndarray, fmt: int = 0, minor: int = 2) -> None:
    """A minimal uncompressed LAS 1.2 / 1.4 file of ``points`` (scale 1 mm, offset 0)."""
    length = {0: 20, 1: 28, 6: 30}[fmt]
    header_size = 375 if minor == 4 else 227
    scale, offset = (0.001, 0.001, 0.001), (0.0, 0.0, 0.0)
    lo, hi = points.min(axis=0), points.max(axis=0)
    head = struct.pack(
        "<4sHH16sBB32s32sHHHIIBHI5I3d3d6d",
        b"LASF",
        0,
        0,
        b"\0" * 16,
        1,
        minor,
        b"test",
        b"test",
        1,
        2026,
        header_size,
        header_size,
        0,
        fmt,
        length,
        len(points) if minor < 4 else 0,
        *([0] * 5),
        *scale,
        *offset,
        hi[0],
        lo[0],
        hi[1],
        lo[1],
        hi[2],
        lo[2],
    )
    if minor == 4:
        head += b"\0" * (247 - len(head)) + struct.pack("<Q", len(points))
        head += b"\0" * (header_size - len(head))
    records = bytearray()
    for k, (x, y, z) in enumerate(points):
        rec = struct.pack("<iiiH", round(x / 0.001), round(y / 0.001), round(z / 0.001), 100 + k)
        rec += b"\0" * (length - len(rec))
        records += rec
    path.write_bytes(head + bytes(records))


def _room(n: int = 400) -> np.ndarray:
    """Points on the four walls of a 4 m x 3 m room, 0 to 3 m high (metres)."""
    rng = np.random.default_rng(3)
    t = rng.random(n)
    z = rng.random(n) * 3
    side = np.arange(n) % 4
    x = np.where(side == 0, t * 4, np.where(side == 1, 4.0, np.where(side == 2, t * 4, 0.0)))
    y = np.where(side == 0, 0.0, np.where(side == 1, t * 3, np.where(side == 2, 3.0, t * 3)))
    return np.column_stack([x, y, z])


@pytest.mark.parametrize(("fmt", "minor"), [(0, 2), (1, 2), (6, 4)])
def test_las_round_trip(tmp_path: Path, fmt: int, minor: int) -> None:
    pts = _room(50)
    path = tmp_path / "scan.las"
    _write_las(path, pts, fmt, minor)
    cloud = pcl.read_las(path)
    assert cloud.points.shape == (50, 3)
    assert np.allclose(cloud.points, pts, atol=1e-3)
    assert cloud.intensity is not None and cloud.intensity[0] == 100


def test_laz_and_e57_are_read_and_bad_files_say_so(tmp_path: Path) -> None:
    # Owner 2026-11-09: LAZ (lazrs) and E57 (pye57) are dependencies; a damaged file is refused
    # with the reason, never with a crash.
    assert {".laz", ".e57"} <= set(pcl.READABLE)
    for name in ("scan.laz", "scan.e57"):
        (tmp_path / name).write_bytes(b"x")
        with pytest.raises(pcl.PointCloudError):
            pcl.read_cloud(tmp_path / name)


def test_xyz_and_pts(tmp_path: Path) -> None:
    (tmp_path / "a.xyz").write_text("1 2 3\n4,5,6,7\nnot a point\n", encoding="utf-8")
    cloud = pcl.read_cloud(tmp_path / "a.xyz")
    assert cloud.points.tolist() == [[1, 2, 3], [4, 5, 6]]
    (tmp_path / "b.pts").write_text("2\n1 1 1 10 0 0 0\n2 2 2 20 0 0 0\n", encoding="utf-8")
    assert len(pcl.read_cloud(tmp_path / "b.pts").points) == 2  # the count line skipped


def test_decimate_one_per_voxel() -> None:
    pts = np.array([[0, 0, 0], [0.01, 0.01, 0], [1, 1, 1], [1.02, 1, 1]], dtype=float)
    assert pcl.decimate(pts, 0.1).tolist() == [0, 2]
    assert len(pcl.decimate(pts, 0.0, limit=2)) == 2


def test_slice_and_trace_the_room() -> None:
    # Dense enough that no random hole along a wall exceeds the default gap (10 x 0.02 m): at
    # 4000 points a wall had about 56 points in the slice and holes of 0.35 m, so it broke up.
    plan = pcl.slice_plan(_room(8000), 1.2, 0.2)
    assert len(plan) > 100
    lines = pcl.trace_lines(plan, 0.02, min_points=20, min_length=1.0)
    assert len(lines) >= 4
    lengths = sorted(np.hypot(x2 - x1, y2 - y1) for x1, y1, x2, y2 in lines)[-4:]
    assert lengths[-1] == pytest.approx(4.0, abs=0.3)


def test_snap_nearest_within_radius() -> None:
    plan = np.array([[0.0, 0.0], [1.0, 1.0]])
    assert pcl.snap(plan, 0.9, 1.05, 0.2) == [1.0, 1.0]
    assert pcl.snap(plan, 5, 5, 0.2) is None


def test_convert_writes_and_caches(tmp_path: Path) -> None:
    path = tmp_path / "scan.las"
    _write_las(path, _room(800))
    first = pcl.convert(path, 1.2, 0.3, voxel=0.01)
    assert first.dxf.is_file() and not first.cached
    text = first.dxf.read_text(encoding="utf-8")
    assert "CLOUD" in text and "TRACED" in text
    again = pcl.convert(path, 1.2, 0.3, voxel=0.01)
    assert again.cached and again.segments == first.segments
    empty = pcl.convert(path, 50.0, 0.3)
    assert empty.points == 0 and "no points" in empty.warnings[-1]

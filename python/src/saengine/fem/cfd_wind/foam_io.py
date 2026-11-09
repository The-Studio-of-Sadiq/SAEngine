"""Reading an OpenFOAM case's ASCII mesh and fields back (alpha 9 L3), without OpenFOAM.

The cases are written with ``writeFormat ascii`` and no compression (:mod:`.case`); a ``.gz``
file is read too, a binary one is refused. Read:

- ``constant/polyMesh/points`` (``vectorField``), ``faces`` (``faceList`` ``n(a b c)``, or the
  ``faceCompactList`` of offsets and indices), ``owner`` (``labelList``) and ``boundary``
  (each patch's type, ``nFaces`` and ``startFace``);
- a scalar field's ``internalField`` (``uniform v`` or ``nonuniform List<scalar> N (...)``; a
  list written ``N{v}`` too). The building's pressure is zero-gradient there, so its face values
  are its cells' (``owner``).
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

import numpy as np

_HEADER = re.compile(rb"FoamFile\s*\{(.*?)\}", re.DOTALL)
_ENTRY = re.compile(rb"(\w+)\s+([^;]*);")
_COUNT = re.compile(rb"(\d+)\s*([({])")
_FACE = re.compile(rb"(\d+)\s*\(([^)]*)\)")
_PATCH = re.compile(rb'("?[^\s{}";()]+"?)\s*\{([^{}]*)\}')
_TIME = re.compile(r"^\d+(\.\d+)?([eE][-+]?\d+)?$")


class FoamFormatError(ValueError):
    """A file this reader cannot read (binary, or not the expected kind)."""


def read_bytes(path: Path) -> bytes:
    """The file's bytes (``path`` or ``path.gz``)."""
    if path.is_file():
        return path.read_bytes()
    zipped = path.with_name(path.name + ".gz")
    if zipped.is_file():
        return gzip.decompress(zipped.read_bytes())
    raise FileNotFoundError(str(path))


def header(data: bytes) -> dict[str, str]:
    """The ``FoamFile`` header's entries."""
    m = _HEADER.search(data)
    if not m:
        return {}
    return {k.decode(): v.decode().strip().strip('"') for k, v in _ENTRY.findall(m.group(1))}


def _body_start(data: bytes) -> int:
    m = _HEADER.search(data)
    return m.end() if m else 0


def _check_ascii(data: bytes, what: str) -> None:
    if header(data).get("format", "ascii") != "ascii":
        raise FoamFormatError(f"{what} is binary: SAEngine reads ASCII cases (writeFormat ascii)")


def _list_at(data: bytes, start: int) -> tuple[int, bytes, bytes | None, int]:
    """The list starting at ``start`` (``N (`` or ``N{``): (N, its body, the uniform value of
    ``N{v}`` or None, the index after it)."""
    m = _COUNT.search(data, start)
    if not m:
        raise FoamFormatError("no list found")
    n = int(m.group(1))
    if m.group(2) == b"{":
        close = data.index(b"}", m.end())
        return n, b"", data[m.end() : close], close + 1
    open_ = m.end()
    if n > 10:
        # Long lists: one item a line, ")" alone on the closing line.
        close = data.find(b"\n)", open_)
        if close < 0:
            raise FoamFormatError("unterminated list")
        return n, data[open_:close], None, close + 2
    depth, i = 1, open_
    while depth:
        c = data[i : i + 1]
        if not c:
            raise FoamFormatError("unterminated list")
        if c == b"(":
            depth += 1
        elif c == b")":
            depth -= 1
        i += 1
    return n, data[open_ : i - 1], None, i


def _numbers(body: bytes, dtype: type = float) -> np.ndarray:
    text = body.replace(b"(", b" ").replace(b")", b" ").decode("ascii", errors="replace")
    if not text.strip():
        return np.zeros(0, dtype=dtype)
    return np.array(text.split(), dtype=dtype)


def read_points(path: Path) -> np.ndarray:
    """The mesh's points, (n, 3) [m]."""
    data = read_bytes(path)
    _check_ascii(data, "points")
    n, body, uniform, _ = _list_at(data, _body_start(data))
    if uniform is not None:
        return np.tile(_numbers(uniform), (n, 1)).reshape(n, 3)
    values = _numbers(body)
    if values.size != 3 * n:
        raise FoamFormatError(f"points: {values.size} numbers for {n} points")
    return values.reshape(n, 3)


def read_labels(path: Path) -> np.ndarray:
    """A ``labelList`` (``owner``)."""
    data = read_bytes(path)
    _check_ascii(data, path.name)
    n, body, uniform, _ = _list_at(data, _body_start(data))
    if uniform is not None:
        return np.full(n, int(uniform.strip()), dtype=np.int64)
    values = _numbers(body, np.int64)
    if values.size != n:
        raise FoamFormatError(f"{path.name}: {values.size} labels for {n}")
    return values


def read_faces(path: Path, first: int = 0, count: int | None = None) -> list[np.ndarray]:
    """The faces ``first`` .. ``first + count`` (all by default) as point index arrays."""
    data = read_bytes(path)
    _check_ascii(data, "faces")
    start = _body_start(data)
    if header(data).get("class") == "faceCompactList":
        n, body, _, end = _list_at(data, start)
        offsets = _numbers(body, np.int64)
        _, body2, _, _ = _list_at(data, end)
        flat = _numbers(body2, np.int64)
        last = n - 1 if count is None else first + count
        return [flat[offsets[i] : offsets[i + 1]] for i in range(first, min(last, n - 1))]
    n, body, _, _ = _list_at(data, start)
    stop = n if count is None else min(n, first + count)
    out: list[np.ndarray] = []
    for i, m in enumerate(_FACE.finditer(body)):
        if i < first:
            continue
        if i >= stop:
            break
        out.append(np.array(m.group(2).split(), dtype=np.int64))
    return out


def read_boundary(path: Path) -> dict[str, dict[str, str | int]]:
    """Each patch: ``type``, ``nFaces``, ``startFace``."""
    data = read_bytes(path)
    out: dict[str, dict[str, str | int]] = {}
    for name, body in _PATCH.findall(data[_body_start(data) :]):
        entries = {k.decode(): v.decode().strip() for k, v in _ENTRY.findall(body)}
        if "nFaces" not in entries or "startFace" not in entries:
            continue
        out[name.decode().strip('"')] = {
            "type": entries.get("type", ""),
            "nFaces": int(entries["nFaces"]),
            "startFace": int(entries["startFace"]),
        }
    return out


def read_internal(path: Path) -> np.ndarray | float:
    """A scalar field's ``internalField``: a value per cell, or one uniform value."""
    data = read_bytes(path)
    _check_ascii(data, path.name)
    at = data.find(b"internalField")
    if at < 0:
        raise FoamFormatError(f"{path.name}: no internalField")
    rest = data[at + len(b"internalField") :].lstrip()
    if rest.startswith(b"uniform"):
        return float(rest[len(b"uniform") :].split(b";", 1)[0])
    if not rest.startswith(b"nonuniform"):
        raise FoamFormatError(f"{path.name}: unknown internalField")
    start = at + len(b"internalField")
    n, body, uniform, _ = _list_at(data, start)
    if uniform is not None:
        return np.full(n, float(uniform.strip()))
    values = _numbers(body)
    if values.size != n:
        raise FoamFormatError(f"{path.name}: {values.size} values for {n} cells")
    return values


def latest_time(case: Path, field: str = "p") -> Path | None:
    """The latest time folder (above 0) with ``field``."""
    times = []
    for child in case.iterdir() if case.is_dir() else []:
        if (
            child.is_dir()
            and _TIME.match(child.name)
            and float(child.name) > 0
            and ((child / field).is_file() or (child / f"{field}.gz").is_file())
        ):
            times.append((float(child.name), child))
    return max(times)[1] if times else None


def face_geometry(points: np.ndarray, faces: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """(centres (n, 3), area vectors (n, 3)) of polygon faces: the area-weighted centre of the
    triangles fanned from the points' mean, and ½ Σ (vi × vi+1), the right-hand normal (out of
    the cell that owns a boundary face, i.e. out of the domain)."""
    centres = np.zeros((len(faces), 3))
    vectors = np.zeros((len(faces), 3))
    for i, face in enumerate(faces):
        v = points[face]
        mid = v.mean(axis=0)
        nxt = np.roll(v, -1, axis=0)
        tri = np.cross(v - mid, nxt - mid) / 2
        area = tri.sum(axis=0)
        weights = np.linalg.norm(tri, axis=1)
        tc = (v + nxt + mid) / 3
        total = weights.sum()
        centres[i] = (tc * weights[:, None]).sum(axis=0) / total if total > 0 else mid
        vectors[i] = area
    return centres, vectors

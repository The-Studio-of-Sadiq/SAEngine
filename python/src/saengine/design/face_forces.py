"""Design forces at the faces of the supports (beams at the column faces, columns at the beam
soffit and the top of the slab), from the analysis's support face offsets.

BNBC 2020 Part 6 (part 1 of the code, p 892) Sec 6.1.6.2 takes the span centre to centre of
the supports for the analysis of frames, and Sec 6.1.6.3 permits "design on the basis of
moments at faces of support" for beams built integrally with their supports. Sec 6.4.1.3
(p 922) lets sections closer than d to the face of a support be designed for the shear at d
(6.4.1.3.1) when (a) the support reaction introduces compression into the end region, (b) the
loads act at or near the top of the member and (c) no concentrated load acts between the face
and the section at d. Sec 6.1.6.3 covers beams only: designing columns for the forces at the
beam soffit and the top of the slab is SAEngine's practice (the project's decision, as a
commercial analysis program does), not that clause (:data:`COLUMN_PRACTICE`).

What this module does:

- The analysis (:mod:`saengine.fem.end_zones`) records per analysis frame element its face
  offsets ``{"i": mm, "j": mm}``: the distance from its i node to the face of the support at
  i, and from its j node back to the face at j; 0 (or absent) where nothing supports that end
  (a span split by the slab mesh, a beam framing into a girder). They come from the results'
  ``face-forces.json`` (:func:`read_face_forces`, ``face_offsets`` of :func:`at_faces`) or an
  element's own ``"faceOffsets"`` key, with the forces at the faces per load case, which are
  exact and preferred (:func:`face_rows_of`, ``face_rows``). The offset is the member's: where
  it is longer than the element it is recorded on (the first short element of a meshed beam),
  the face lies on a later element of the member, and every element before it lies inside the
  support.
- **Rigid end zones.** The analysis makes the end of an element rigid over ``rigidZoneFactor``
  of its offset (OpenSees ``geomTransf -jntOffset``, the element's ``joint_offsets``): its
  ``localForce`` then acts at the ends of the flexible part, and the check's stations
  (``saengine.fem.display.element_section_forces``) run from the flexible end i over the node to
  node length. :func:`at_faces` reads every force at its true place: the distance ``x`` from
  the node is ``x - ri`` along the stations (the convention of
  :func:`saengine.fem.end_zones.section_at`), and the pieces it returns are re-stationed from the
  node (each station at its distance from the node, the rigid zones taking the forces at the
  flexible ends; those inside a support then take the face's).
- :func:`at_faces` gives a member's pieces (``saengine.design.check._Piece``) with the stations
  inside a support replaced by the forces at its face: the axial force, torsion and moments of
  every station between the joint and the face become those at the face, and with
  ``shear_depth`` the shears of every station between the joint and d beyond the face become
  those at d (6.4.1.3.1). The positive moments in the span and every station outside the
  supports are unchanged. The forces at the face are interpolated from the three nearest
  stations by a parabola, exact for the uniform loads of the analysis (between point loads).
  The combination's forces, its lateral part (``sway``) and its sustained part
  (``sustained``) are treated alike, so they stay consistent (the model is linear).
- When the analysis has no face offsets (a model analysed before they existed) the joint
  forces are kept, with :data:`JOINT_NOTE`.
- When the analysis writes the forces at the faces themselves (``"faceForces"`` of an element
  per load case, ``{"i": {N, Vy, Vz, T, My, Mz}, "j": {...}}``, section forces as
  ``element_section_forces`` gives them, N and N·m), :func:`combined_face_rows` combines them
  as the check combines the stations and :func:`at_faces` takes them (``face_rows``) instead of
  the interpolated ones.

The conditions (a) to (c) of 6.4.1.3 are taken as met where a support face exists (a column or
wall, whose reaction compresses the end of the beam; the analysis loads act on the beam's
axis). Condition (c) is the engineer's to confirm where a point load sits within d of a face:
``shear_depth=None`` designs the shear at the face instead.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Columns of a station row (N, Vy, Vz, T, My, Mz): taken at the face, and the shears, taken at
#: d from the face when allowed.
_AT_FACE = (0, 3, 4, 5)
_SHEARS = (1, 2)
_TOL = 1e-9

JOINT_NOTE = (
    "forces at the joints: the analysis model has no support face offsets (run the analysis "
    "again to design at the faces of the supports, BNBC 2020 Part 6 Sec 6.1.6.3)"
)
FACE_CLAUSE = "BNBC 2020 Part 6 Sec 6.1.6.3"
SHEAR_CLAUSE = "BNBC 2020 Part 6 Sec 6.4.1.3.1"
#: Columns at the beam soffit: SAEngine's practice, not a BNBC clause (6.1.6.3 covers beams).
COLUMN_PRACTICE = (
    "SAEngine's practice for columns; BNBC 2020 Part 6 Sec 6.1.6.3 permits face design for "
    "beams only"
)

METHOD = [
    (
        "Design at the faces of the supports (BNBC 2020 Part 6 Sec 6.1.6.3): the analysis "
        "spans centre to centre of the supports (6.1.6.2); beams are designed for the moments "
        "at the column and wall faces (the positive moments in the span unchanged) and for the "
        "shear at d from the face (6.4.1.3.1: the support compresses the end of the beam, the "
        "loads act at its top; with a point load within d of a face the shear at the face "
        "should be taken)."
    ),
    (
        "Columns are designed for the forces at the beam soffit and the top of the slab: "
        "SAEngine's practice, as a commercial analysis program designs them (6.1.6.3 covers "
        "beams only); their slenderness end moments M1 and M2 stay the joints'."
    ),
]


@dataclass
class Faced:
    """A member's pieces with the forces inside its supports taken at the faces."""

    pieces: list[Any]
    #: "analysis" (the analysis's face offsets), "joints" (none: the joint forces kept).
    source: str
    #: Per piece id the offsets (i, j) from its node to the support faces [m] (the member's: a
    #: face may lie on a later piece).
    offsets: dict[int, tuple[float, float]] = field(default_factory=dict)
    shear_depth: float | None = None  # m
    notes: list[str] = field(default_factory=list)

    @property
    def at_faces(self) -> bool:
        return self.source == "analysis"

    def _distance(self) -> str:
        ends = [v for pair in self.offsets.values() for v in pair if v > 0]
        if not ends:
            return ""
        low, high = min(ends), max(ends)
        span = f"{low:.2f}" if math.isclose(low, high, abs_tol=5e-3) else f"{low:.2f} to {high:.2f}"
        return f", {span} m from the joints"

    def describe(self, column: bool = False) -> str:
        """The note the checks carry: where their forces were taken (``column``: a column's,
        at the beam soffit and the top of the slab)."""
        if not self.at_faces:
            return JOINT_NOTE
        if column:
            return (
                f"forces at the beam soffit and the top of the slab ({COLUMN_PRACTICE}"
                f"{self._distance()})"
            )
        return f"forces at the support faces ({FACE_CLAUSE}{self._distance()})"

    def shear_note(self) -> str:
        if not self.at_faces:
            return JOINT_NOTE
        if self.shear_depth is None:
            return f"shear at the support faces ({FACE_CLAUSE})"
        return f"shear at d = {self.shear_depth:.3f} m from the support faces ({SHEAR_CLAUSE})"


# ─────────────────────────────────── offsets ───────────────────────────────────


def _mm(value: Any, key: str = "offset") -> float:
    """A length in mm of the face offsets: a number, or the faces file's ``{"offset": mm,
    "rigid": mm, "at": ...}`` (its ``key``)."""
    if isinstance(value, dict):
        value = value.get(key)
    return float(value or 0.0)


def element_offsets(element: dict[str, Any] | None) -> tuple[float, float] | None:
    """The face offsets (i, j) [m] an analysis element carries (``"faceOffsets"`` in mm), or
    None when it has none."""
    if not element:
        return None
    raw = element.get("faceOffsets")
    if not isinstance(raw, dict):
        return None
    try:
        i = _mm(raw.get("i"))
        j = _mm(raw.get("j"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(i) and math.isfinite(j)):
        return None
    return max(i, 0.0) * 1e-3, max(j, 0.0) * 1e-3


def offsets_of(
    project: dict[str, Any],
    pieces: list[Any],
    by_element: dict[Any, dict[str, Any]] | None = None,
) -> dict[int, tuple[float, float]] | None:
    """Each piece's face offsets [m] from the analysis model ``project`` (or a piece's own
    ``face_offsets`` attribute, (i, j) in m, or ``by_element``: per element id, int or str,
    ``{"i": mm, "j": mm}`` as the analysis's face-forces file gives them, see
    :func:`read_face_forces`); None when no piece has any: the analysis was run without
    them."""
    by_id = {e.get("id"): e for e in project.get("elements", []) or []}
    found: dict[int, tuple[float, float]] = {}
    seen = False
    for p in pieces:
        own = getattr(p, "face_offsets", None)
        if own is not None:
            found[p.id] = (max(float(own[0]), 0.0), max(float(own[1]), 0.0))
            seen = True
            continue
        given = None
        if by_element:
            given = by_element.get(p.id, by_element.get(str(p.id)))
        offsets = (
            element_offsets({"faceOffsets": given})
            if given is not None
            else element_offsets(by_id.get(p.id))
        )
        if offsets is not None:
            seen = True
            found[p.id] = offsets
        else:
            found[p.id] = (0.0, 0.0)
    return found if seen else None


def rigid_of(project: dict[str, Any], pieces: list[Any]) -> dict[int, tuple[float, float]]:
    """Each piece's rigid end zones (i, j) [m]: its own ``rigid_offsets`` attribute, else the
    length of its element's ``joint_offsets`` in the analysis model ``project`` (as
    :func:`saengine.fem.end_zones.element_offsets` reads them); (0, 0) without."""
    by_id = {e.get("id"): e for e in project.get("elements", []) or []}
    found: dict[int, tuple[float, float]] = {}
    for p in pieces:
        own = getattr(p, "rigid_offsets", None)
        if own is not None:
            found[p.id] = (max(float(own[0]), 0.0), max(float(own[1]), 0.0))
            continue
        raw = (by_id.get(p.id) or {}).get("joint_offsets")
        if raw and len(raw) >= 6:
            vec = np.asarray(raw[:6], dtype=float)
            found[p.id] = (float(np.linalg.norm(vec[0:3])), float(np.linalg.norm(vec[3:6])))
        else:
            found[p.id] = (0.0, 0.0)
    return found


def shear_depth(section: Any) -> float | None:
    """d for the shear at d from the face [m]: the smaller effective depth of the section's
    two faces (hogging at a support takes the top bars'), None when it has no bars."""
    from saengine.design.rc import DesignError

    depths = []
    for top in (True, False):
        try:
            depths.append(float(section.effective_depth(top=top)))
        except (DesignError, AttributeError, ZeroDivisionError):
            continue
    return min(depths) * 1e-3 if depths else None


# ─────────────────────────────────── combining ───────────────────────────────────


def _row(values: dict[str, Any]) -> np.ndarray:
    return np.array([float(values.get(k) or 0.0) for k in ("N", "Vy", "Vz", "T", "My", "Mz")])


def read_face_forces(out_dir: Any) -> dict[str, Any] | None:
    """The analysis's face forces file in the results folder ``out_dir`` (``face-forces.json``
    of :mod:`saengine.fem.end_zones`: ``{"faceOffsets": {element id: {"i"|"j": mm}},
    "cases": {case code: {element id: {"i"|"j": {N, Vy, Vz, T, My, Mz}}}}}``), or None."""
    import json
    from pathlib import Path

    try:
        data = json.loads((Path(out_dir) / "face-forces.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("faceOffsets"):
        return None
    return data


def face_rows_of(
    data: dict[str, Any] | None, factors_of: list[dict[str, float]], pieces: list[Any]
) -> dict[int, list[np.ndarray]]:
    """Per piece id its forces at the faces per combination (:func:`combined_face_rows`) from
    the face forces file ``data`` (:func:`read_face_forces`); pieces it lacks are left out."""
    if not data:
        return {}
    found = {}
    for p in pieces:
        rows = combined_face_rows(data.get("cases", {}), factors_of, p.id)
        if rows is not None:
            found[p.id] = rows
    return found


def combined_face_rows(
    face_by_case: dict[str, dict[int, dict[str, dict[str, Any]]]],
    factors_of: list[dict[str, float]],
    element_id: int,
) -> list[np.ndarray] | None:
    """The forces at the faces of one analysis element per combination (rows i, j of N .. Mz),
    from the analysis's per-case ``faceForces`` (``{case: {element: {"i": {...}, "j":
    {...}}}}``) and the combinations' factors (``extra["factors"]`` of the check); None when
    a case of a combination has none for the element."""
    rows = []
    for factors in factors_of:
        total = np.zeros((2, 6))
        for case, f in factors.items():
            of_case = face_by_case.get(case, {})
            own = of_case.get(element_id, of_case.get(str(element_id)))  # type: ignore[call-overload]
            if own is None:
                return None
            total += f * np.vstack([_row(own.get("i", {})), _row(own.get("j", {}))])
        rows.append(total)
    return rows


# ─────────────────────────────────── at the faces ───────────────────────────────────


def _interpolate(rows: np.ndarray, length: float, x: float) -> np.ndarray:
    """The row at ``x`` [m] of station ``rows`` evenly spread over ``length``: a parabola through
    the three nearest stations (exact for a uniform load), linear with two stations."""
    n = len(rows)
    if n == 1 or length <= 0:
        return rows[0].copy()
    x = min(max(x, 0.0), length)
    step = length / (n - 1)
    if n == 2:
        t = x / length
        return (1 - t) * rows[0] + t * rows[1]
    first = int(min(max(round(x / step) - 1, 0), n - 3))
    x0 = step * first
    x1, x2 = x0 + step, x0 + 2 * step
    w0 = (x - x1) * (x - x2) / (2 * step * step)
    w1 = -(x - x0) * (x - x2) / (step * step)
    w2 = (x - x0) * (x - x1) / (2 * step * step)
    return w0 * rows[first] + w1 * rows[first + 1] + w2 * rows[first + 2]


def _interpolate_many(rows: np.ndarray, length: float, xs: np.ndarray) -> np.ndarray:
    """:func:`_interpolate` at each of ``xs`` [m] at once (one row per x): a member's stations
    are re-stationed thousands of times in a design, so not one x at a time."""
    rows = np.asarray(rows, dtype=float)
    n = len(rows)
    if n == 1 or length <= 0:
        return np.repeat(rows[:1], len(xs), axis=0)
    xs = np.clip(xs, 0.0, length)
    shape = (-1,) + (1,) * (rows.ndim - 1)
    step = length / (n - 1)
    if n == 2:
        t = (xs / length).reshape(shape)
        return (1 - t) * rows[0] + t * rows[1]
    first = np.clip(np.round(xs / step) - 1, 0, n - 3).astype(int)
    x0 = step * first
    x1, x2 = x0 + step, x0 + 2 * step
    # Lagrange weights of the three stations x0, x1, x2 (a step apart).
    w0 = (xs - x1) * (xs - x2) / (2 * step * step)
    w1 = -(xs - x0) * (xs - x2) / (step * step)
    w2 = (xs - x0) * (xs - x1) / (2 * step * step)
    return (
        w0.reshape(shape) * rows[first]
        + w1.reshape(shape) * rows[first + 1]
        + w2.reshape(shape) * rows[first + 2]
    )


@dataclass
class _Curve:
    """One combination's station rows of an analysis element, read at distances from its node
    i: the stations run from the flexible end i (``ri`` from the node) over ``length``."""

    rows: np.ndarray
    length: float
    ri: float = 0.0
    rj: float = 0.0

    def at(self, x: float) -> np.ndarray:
        """The forces at ``x`` [m] from the node i; inside a rigid zone, those at its flexible
        end."""
        flexible = max(self.length - self.ri - self.rj, 0.0)
        return _interpolate(self.rows, self.length, min(max(x - self.ri, 0.0), flexible))

    def from_node(self) -> np.ndarray:
        """The rows re-stationed from the node (as many, evenly over the node to node length)."""
        if self.ri <= 0 and self.rj <= 0:
            return np.array(self.rows, dtype=float, copy=True)
        flexible = max(self.length - self.ri - self.rj, 0.0)
        xs = np.clip(np.linspace(0.0, self.length, len(self.rows)) - self.ri, 0.0, flexible)
        return _interpolate_many(self.rows, self.length, xs)


@dataclass
class _Face:
    """A support face of the member: recorded on piece ``owner`` (its id) at end ``side``,
    ``offset`` [m] from that piece's node; it lies on chain piece ``land`` at ``x`` [m] from
    that piece's node i, beyond the chain pieces ``inside`` (wholly inside the support)."""

    owner: int
    side: str
    offset: float
    land: int
    x: float
    shear_x: float
    inside: list[int]
    #: The analysis's forces at this face per combination (rows N .. Mz), or None.
    given: list[np.ndarray] | None


def _chain(pieces: list[Any]) -> list[int]:
    """The pieces' order along the member (each starting where the one before ends), from their
    end coordinates; their own order when that cannot be told."""
    n = len(pieces)
    if n < 2 or any(
        getattr(p, "start", None) is None or getattr(p, "end", None) is None for p in pieces
    ):
        return list(range(n))

    def same(a: Any, b: Any) -> bool:
        return float(np.linalg.norm(np.asarray(a, float) - np.asarray(b, float))) < 1e-6

    heads = [
        k
        for k, p in enumerate(pieces)
        if not any(same(q.end, p.start) for m, q in enumerate(pieces) if m != k)
    ]
    if len(heads) != 1:
        return list(range(n))
    order = [heads[0]]
    while len(order) < n:
        last = pieces[order[-1]]
        following = [k for k, q in enumerate(pieces) if k not in order and same(q.start, last.end)]
        if len(following) != 1:
            return list(range(n))
        order.append(following[0])
    return order


def _faces(
    chain: list[Any],
    offsets: dict[int, tuple[float, float]],
    face_rows: dict[int, list[np.ndarray]] | None,
    depth: float,
    notes: list[str],
) -> list[_Face]:
    """The member's support faces, each located on the chain (a face beyond a short piece lies
    on a later one), the sections at d placed (``depth``, 0 for the shear at the face)."""
    lengths = [float(p.length) for p in chain]
    found: list[_Face] = []
    for idx, piece in enumerate(chain):
        for side, offset in zip(("i", "j"), offsets.get(piece.id, (0.0, 0.0)), strict=True):
            if offset <= 0:
                continue
            step = 1 if side == "i" else -1
            k, rest, inside = idx, offset, []
            while 0 <= k < len(chain) and rest >= lengths[k] - _TOL:
                inside.append(k)
                rest -= lengths[k]
                k += step
            if not 0 <= k < len(chain):
                notes.append(f"{piece.name}: the support covers the member, its forces kept")
                continue
            x = rest if side == "i" else lengths[k] - rest
            given = None
            if face_rows and piece.id in face_rows:
                given = [np.asarray(r)[0 if side == "i" else 1] for r in face_rows[piece.id]]
            found.append(_Face(piece.id, side, offset, k, x, x, inside, given))
    # Faces past one another (the supports overlap the clear span): their forces kept.
    starts = np.concatenate([[0.0], np.cumsum(lengths)])
    pos = {id(f): starts[f.land] + f.x for f in found}
    overlap: set[int] = set()
    for f in found:
        for g in found:
            if f.side == "i" and g.side == "j" and pos[id(f)] >= pos[id(g)] - _TOL:
                overlap.update((id(f), id(g)))
    if overlap:
        names = sorted({chain[f.land].name for f in found if id(f) in overlap})
        notes.append(f"{', '.join(names)}: the supports cover the element, its forces kept")
        found = [f for f in found if id(f) not in overlap]
    # The sections at d, on the piece the face lies on (no further than its ends); where those
    # of the two faces of one piece meet, both at mid clear span.
    for f in found:
        f.shear_x = f.x + depth if f.side == "i" else f.x - depth
        f.shear_x = min(max(f.shear_x, 0.0), lengths[f.land])
    for f in found:
        for g in found:
            if f.side == "i" and g.side == "j" and f.land == g.land and f.shear_x > g.shear_x:
                middle = (f.x + g.x) / 2
                f.shear_x = g.shear_x = middle
    return found


class _Combined:
    """A kind's curves of every piece (:func:`at_faces`), re-stationed and read at the faces for
    all combinations at once: they share the piece's stations (per combination, a 10-storey
    design made millions of small calls). A piece whose curves differ falls back to them."""

    def __init__(self, of_kind: list[list[_Curve | None] | None]) -> None:
        self.of_kind = of_kind
        self._together: dict[int, _Curve | None] = {}
        self._from_node: dict[int, np.ndarray | None] = {}
        self._readings: dict[tuple[int, float], np.ndarray | None] = {}

    def _stacked(self, k: int) -> _Curve | None:
        """One curve of piece ``k`` with the combinations along a second axis, or None."""
        if k not in self._together:
            parts = self.of_kind[k]
            together = None
            if parts and all(c is not None for c in parts):
                first = parts[0]
                if all(
                    c.rows.shape == first.rows.shape  # type: ignore[union-attr]
                    and (c.length, c.ri, c.rj) == (first.length, first.ri, first.rj)  # type: ignore[union-attr]
                    for c in parts
                ):
                    together = _Curve(
                        np.stack([c.rows for c in parts], axis=1),  # type: ignore[union-attr]
                        first.length,  # type: ignore[union-attr]
                        first.ri,  # type: ignore[union-attr]
                        first.rj,  # type: ignore[union-attr]
                    )
            self._together[k] = together
        return self._together[k]

    def from_node(self, k: int) -> np.ndarray | None:
        """:meth:`_Curve.from_node` of each combination of piece ``k`` (combination first)."""
        if k not in self._from_node:
            together = self._stacked(k)
            self._from_node[k] = (
                None if together is None else np.moveaxis(together.from_node(), 1, 0)
            )
        return self._from_node[k]

    def read(self, k: int, x: float, c: int) -> np.ndarray:
        """:meth:`_Curve.at` ``x`` of combination ``c`` of piece ``k``."""
        if (k, x) not in self._readings:
            together = self._stacked(k)
            self._readings[(k, x)] = None if together is None else together.at(x)
        found = self._readings[(k, x)]
        return found[c] if found is not None else self.of_kind[k][c].at(x)  # type: ignore[index,union-attr]

    def read_all(self, k: int, x: float) -> np.ndarray | None:
        """:meth:`read` of every combination (combination first), or None when piece ``k``'s
        curves differ."""
        if self._stacked(k) is None:
            return None
        self.read(k, x, 0)
        return self._readings[(k, x)]


def _moved_together(
    rows: np.ndarray,
    length: float,
    faces: list[_Face],
    combined: _Combined,
    kind: str,
    k: int,
    cols: list[int],
    shears: list[int],
    moved: set[int],
    sheared: set[int],
) -> np.ndarray:
    """:func:`at_faces`' moves of the stations of piece ``k`` for every combination at once
    (``rows``: combination, station, force), the same values as one combination at a time."""
    count = rows.shape[0]
    xs = np.linspace(0.0, length, rows.shape[1])
    for f in faces:
        read_x = combined.read_all(f.land, f.x)
        assert read_x is not None
        at = read_x.copy()
        given = np.zeros(count, dtype=bool)
        if kind == "forces" and f.given:
            for c in range(min(len(f.given), count)):
                if f.given[c] is not None:
                    at[c] = f.given[c]
                    given[c] = True
        shear = at
        if not math.isclose(f.shear_x, f.x, abs_tol=_TOL):
            read_d = combined.read_all(f.land, f.shear_x)
            assert read_d is not None
            shear = read_d.copy()
            # The analysis's face row, moved to d by the stations' change.
            shear[given] = at[given] + read_d[given] - read_x[given]
        if k in f.inside:
            rows[:, :, cols] = at[:, None, cols]
            rows[:, :, shears] = shear[:, None, shears]
            moved.update(range(rows.shape[1]))
            continue
        sign = 1.0 if f.side == "i" else -1.0
        for s, x in enumerate(xs):
            if sign * (f.x - x) > _TOL:
                rows[:, s, cols] = at[:, cols]
                moved.add(s)
            if sign * (f.shear_x - x) > _TOL:
                rows[:, s, shears] = shear[:, shears]
                sheared.add(s)
    return rows


def at_faces(
    pieces: list[Any],
    project: dict[str, Any],
    shear_depth: float | None = None,
    face_rows: dict[int, list[np.ndarray]] | None = None,
    face_offsets: dict[Any, dict[str, Any]] | None = None,
) -> Faced:
    """The member's ``pieces`` with the forces inside its supports taken at their faces (see the
    module notes): copies, the originals untouched. ``shear_depth`` [m]: the shear is taken at
    d from each face (BNBC 6.4.1.3.1), else at the face. ``face_rows``: per piece id the
    analysis's forces at its faces per combination (:func:`combined_face_rows`), else they are
    interpolated from the stations. ``face_offsets``: per element id (int or str) ``{"i": mm,
    "j": mm}`` (the face forces file's ``faceOffsets``), else read from ``project``. The rigid
    end zones come from ``project`` (its elements' ``joint_offsets``, :func:`rigid_of`).

    Each copy gets ``face_labels`` ({station: where}) for the stations moved, which
    ``saengine.design.check._where`` reports."""
    offsets = offsets_of(project, pieces, face_offsets)
    if offsets is None or not any(i > 0 or j > 0 for i, j in offsets.values()):
        return Faced(list(pieces), "joints", notes=[JOINT_NOTE])
    notes: list[str] = []
    order = _chain(pieces)
    chain = [pieces[k] for k in order]
    rigid = rigid_of(project, pieces)
    depth = shear_depth if shear_depth and shear_depth > 0 else 0.0
    faces = _faces(chain, offsets, face_rows, depth, notes)

    def curves(kind: str) -> list[list[_Curve | None] | None]:
        found: list[list[_Curve | None] | None] = []
        for p in chain:
            parts = getattr(p, kind, None)
            if parts is None:
                found.append(None)
                continue
            ri, rj = rigid.get(p.id, (0.0, 0.0))
            found.append(
                [
                    _Curve(np.asarray(rows, dtype=float), float(p.length), ri, rj)
                    if rows is not None and len(rows)
                    else None
                    for rows in parts
                ]
            )
        return found

    touched = {f.land for f in faces} | {k for f in faces for k in f.inside}
    touched |= {k for k, p in enumerate(chain) if any(rigid.get(p.id, (0.0, 0.0)))}
    moved_of: dict[int, set[int]] = {k: set() for k in touched}
    shear_of: dict[int, set[int]] = {k: set() for k in touched}
    new_parts: dict[tuple[int, str], list[Any]] = {}
    cols, shears = list(_AT_FACE), list(_SHEARS)
    for kind in ("forces", "sway", "sustained"):
        of_kind = curves(kind)
        combined = _Combined(of_kind)
        for k in touched:
            parts = of_kind[k]
            if parts is None:
                continue
            all_rows = combined.from_node(k)
            mine = [f for f in faces if k == f.land or k in f.inside]
            if all_rows is not None and all(
                combined.read_all(f.land, f.x) is not None for f in mine
            ):
                new_parts[(k, kind)] = list(
                    _moved_together(
                        all_rows.copy(),
                        parts[0].length,
                        mine,
                        combined,
                        kind,
                        k,
                        cols,
                        shears,
                        moved_of[k],
                        shear_of[k],
                    )
                )
                continue
            done: list[Any] = []
            for c, curve in enumerate(parts):
                if curve is None:
                    done.append(getattr(chain[k], kind)[c])
                    continue
                rows = all_rows[c].copy() if all_rows is not None else curve.from_node()
                xs = np.linspace(0.0, curve.length, len(rows))
                for f in faces:
                    if k != f.land and k not in f.inside:
                        continue
                    land_parts = of_kind[f.land]
                    land = land_parts[c] if land_parts is not None else None
                    if land is None:
                        continue
                    given = (
                        f.given[c] if kind == "forces" and f.given and c < len(f.given) else None
                    )
                    at = given if given is not None else combined.read(f.land, f.x, c)
                    shear = at
                    if not math.isclose(f.shear_x, f.x, abs_tol=_TOL):
                        shear = combined.read(f.land, f.shear_x, c)
                        if given is not None:
                            # The analysis's face row, moved to d by the stations' change.
                            shear = given + shear - combined.read(f.land, f.x, c)
                    if k in f.inside:
                        rows[:, cols] = at[cols]
                        rows[:, shears] = shear[shears]
                        moved_of[k].update(range(len(rows)))
                        continue
                    sign = 1.0 if f.side == "i" else -1.0
                    for s, x in enumerate(xs):
                        if sign * (f.x - x) > _TOL:
                            rows[s, cols] = at[cols]
                            moved_of[k].add(s)
                        if sign * (f.shear_x - x) > _TOL:
                            rows[s, shears] = shear[shears]
                            shear_of[k].add(s)
                done.append(rows)
            new_parts[(k, kind)] = done

    face_of: dict[int, list[_Face]] = {}
    for f in faces:
        for k in [f.land, *f.inside]:
            face_of.setdefault(k, []).append(f)
    with_d = depth > 0
    replaced: dict[int, Any] = {}
    for k in touched:
        piece = chain[k]
        copied = copy.copy(piece)
        for kind in ("forces", "sway", "sustained"):
            if (k, kind) in new_parts:
                setattr(copied, kind, new_parts[(k, kind)])
        count = len(piece.forces[0]) if piece.forces else 0
        length = float(piece.length)
        labels: dict[int, str] = {}
        for s in sorted(moved_of[k]):
            x = length * s / max(count - 1, 1)
            near = [f for f in face_of.get(k, []) if (f.side == "i") == (x < length / 2)]
            near = near or face_of.get(k, [])
            off = near[0].offset if near else 0.0
            text = f"{piece.name} at the support face, {off:.2f} m from the joint"
            if with_d:
                text += ", shear at d from the face"
            labels[s] = text
        for s in sorted(shear_of[k] - moved_of[k]):
            labels[s] = (
                f"{piece.name} at {s / max(count - 1, 1):.2f} L (shear taken at d from the face)"
            )
        copied.face_labels = labels
        replaced[id(piece)] = copied
    kept = {f.owner for f in faces}
    return Faced(
        [replaced.get(id(p), p) for p in pieces],
        "analysis",
        offsets={k: v for k, v in offsets.items() if k in kept and (v[0] > 0 or v[1] > 0)},
        shear_depth=shear_depth if shear_depth and shear_depth > 0 else None,
        notes=notes,
    )


def annotate(checks: list[dict[str, Any]], faced: Faced) -> list[dict[str, Any]]:
    """Adds where the forces were taken to the beam or column ``checks`` (flexure and, for
    columns, axial force with bending: the faces; shear: the faces or d from them), in place;
    returns them."""
    for check in checks:
        name = check.get("name", "")
        if name.startswith("Flexure"):
            extra = faced.describe()
        elif name.startswith("Axial force and"):
            extra = faced.describe(column=True)
        elif name == "Shear" or name.startswith("Minimum stirrups"):
            extra = faced.shear_note()
        else:
            continue
        note = check.get("note") or ""
        check["note"] = f"{note}; {extra}" if note else extra
    return checks


__all__ = [
    "COLUMN_PRACTICE",
    "FACE_CLAUSE",
    "JOINT_NOTE",
    "METHOD",
    "SHEAR_CLAUSE",
    "Faced",
    "annotate",
    "at_faces",
    "combined_face_rows",
    "element_offsets",
    "face_rows_of",
    "offsets_of",
    "read_face_forces",
    "rigid_of",
    "shear_depth",
]

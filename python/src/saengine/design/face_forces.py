"""Design forces at the faces of the supports (beams at the column faces, columns at the beam
soffit and the top of the slab), from the analysis's support face offsets.

BNBC 2020 Part 6 (part 1 of the code, p 892) Sec 6.1.6.2 takes the span centre to centre of
the supports for the analysis of frames, and Sec 6.1.6.3 permits "design on the basis of
moments at faces of support" for beams built integrally with their supports. Sec 6.4.1.3
(p 922) lets sections closer than d to the face of a support be designed for the shear at d
(6.4.1.3.1) when (a) the support reaction introduces compression into the end region, (b) the
loads act at or near the top of the member and (c) no concentrated load acts between the face
and the section at d.

What this module does:

- The analysis (:mod:`saengine.fem.end_zones`) records per analysis frame element its face
  offsets ``{"i": mm, "j": mm}``: the distance from its i node to the face of the support at
  i, and from its j node back to the face at j; 0 (or absent) where nothing supports that end
  (a span split by the slab mesh, a beam framing into a girder). They come from the results'
  ``face-forces.json`` (:func:`read_face_forces`, ``face_offsets`` of :func:`at_faces`) or an
  element's own ``"faceOffsets"`` key, with the forces at the faces per load case, which are
  exact and preferred (:func:`face_rows_of`, ``face_rows``).
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

JOINT_NOTE = (
    "forces at the joints: the analysis model has no support face offsets (run the analysis "
    "again to design at the faces of the supports, BNBC 2020 Part 6 Sec 6.1.6.3)"
)
FACE_CLAUSE = "BNBC 2020 Part 6 Sec 6.1.6.3"
SHEAR_CLAUSE = "BNBC 2020 Part 6 Sec 6.4.1.3.1"

METHOD = [
    (
        "Design at the faces of the supports (BNBC 2020 Part 6 Sec 6.1.6.3): the analysis "
        "spans centre to centre of the supports (6.1.6.2); beams are designed for the moments "
        "at the column and wall faces (the positive moments in the span unchanged) and for the "
        "shear at d from the face (6.4.1.3.1: the support compresses the end of the beam, the "
        "loads act at its top; with a point load within d of a face the shear at the face "
        "should be taken), columns for the forces at the beam soffit and the top of the slab."
    )
]


@dataclass
class Faced:
    """A member's pieces with the forces inside its supports taken at the faces."""

    pieces: list[Any]
    #: "analysis" (the analysis's face offsets), "joints" (none: the joint forces kept).
    source: str
    #: Per piece id the offsets (i, j) from its station origin to the support faces [m].
    offsets: dict[int, tuple[float, float]] = field(default_factory=dict)
    shear_depth: float | None = None  # m
    notes: list[str] = field(default_factory=list)

    @property
    def at_faces(self) -> bool:
        return self.source == "analysis"

    def describe(self) -> str:
        """The note the checks carry: where their forces were taken."""
        if not self.at_faces:
            return JOINT_NOTE
        ends = [v for pair in self.offsets.values() for v in pair if v > 0]
        if not ends:
            return f"forces at the support faces ({FACE_CLAUSE})"
        low, high = min(ends), max(ends)
        span = f"{low:.2f}" if math.isclose(low, high, abs_tol=5e-3) else f"{low:.2f} to {high:.2f}"
        return f"forces at the support faces ({FACE_CLAUSE}, {span} m from the joints)"

    def shear_note(self) -> str:
        if not self.at_faces:
            return JOINT_NOTE
        if self.shear_depth is None:
            return f"shear at the support faces ({FACE_CLAUSE})"
        return f"shear at d = {self.shear_depth:.3f} m from the support faces ({SHEAR_CLAUSE})"


# ─────────────────────────────────── offsets ───────────────────────────────────


def element_offsets(element: dict[str, Any] | None) -> tuple[float, float] | None:
    """The face offsets (i, j) [m] an analysis element carries (``"faceOffsets"`` in mm), or
    None when it has none."""
    if not element:
        return None
    raw = element.get("faceOffsets")
    if not isinstance(raw, dict):
        return None
    try:
        i = float(raw.get("i") or 0.0)
        j = float(raw.get("j") or 0.0)
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
    xs = [step * (first + k) for k in range(3)]
    out = np.zeros_like(rows[0], dtype=float)
    for a in range(3):
        weight = 1.0
        for b in range(3):
            if a != b:
                weight *= (x - xs[b]) / (xs[a] - xs[b])
        out = out + weight * rows[first + a]
    return out


def _clamp(
    rows: np.ndarray,
    length: float,
    i_face: float,
    j_face: float,
    i_shear: float,
    j_shear: float,
    face_rows: np.ndarray | None,
) -> tuple[np.ndarray, set[int], set[int]]:
    """``rows`` with the stations inside the faces taken at the faces (and the shears inside the
    sections at d taken there): the new rows, the stations moved to a face, and those whose
    shear only moved."""
    n = len(rows)
    xs = np.linspace(0.0, length, n)
    out = np.array(rows, dtype=float, copy=True)
    moved: set[int] = set()
    shear_only: set[int] = set()
    cols = list(_AT_FACE)
    shears = list(_SHEARS)
    at_i = face_rows[0] if face_rows is not None else _interpolate(rows, length, i_face)
    at_j = face_rows[1] if face_rows is not None else _interpolate(rows, length, length - j_face)
    v_i = _interpolate(rows, length, i_shear) if i_shear > i_face else at_i
    v_j = _interpolate(rows, length, length - j_shear) if j_shear > j_face else at_j
    if face_rows is not None:
        # The analysis's own face rows: the shear at d moves from them by the stations' slope.
        if i_shear > i_face:
            v_i = at_i + _interpolate(rows, length, i_shear) - _interpolate(rows, length, i_face)
        if j_shear > j_face:
            v_j = (
                at_j
                + _interpolate(rows, length, length - j_shear)
                - _interpolate(rows, length, length - j_face)
            )
    tol = 1e-9
    for k, x in enumerate(xs):
        if i_face > 0 and x < i_face - tol:
            out[k, cols] = at_i[cols]
            moved.add(k)
        elif j_face > 0 and x > length - j_face + tol:
            out[k, cols] = at_j[cols]
            moved.add(k)
        if i_face > 0 and x < i_shear - tol:
            out[k, shears] = v_i[shears]
            if k not in moved:
                shear_only.add(k)
        elif j_face > 0 and x > length - j_shear + tol:
            out[k, shears] = v_j[shears]
            if k not in moved:
                shear_only.add(k)
    return out, moved, shear_only


def _clamp_list(
    parts: list[np.ndarray] | None,
    bounds: tuple[float, float, float, float, float],
    rows_of: list[np.ndarray] | None,
    moved_all: set[int],
    shear_all: set[int],
) -> list[np.ndarray] | None:
    """:func:`_clamp` of each combination's rows of ``parts`` (``bounds``: length, the faces
    and the sections at d), the stations moved added to ``moved_all`` and ``shear_all``."""
    if parts is None:
        return None
    done = []
    for c, rows in enumerate(parts):
        if rows is None or not len(rows):
            done.append(rows)
            continue
        given = rows_of[c] if rows_of and c < len(rows_of) else None
        new, moved, shear_only = _clamp(np.asarray(rows, dtype=float), *bounds, given)
        moved_all.update(moved)
        shear_all.update(shear_only)
        done.append(new)
    return done


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
    "j": mm}`` (the face forces file's ``faceOffsets``), else read from ``project``.

    Each copy gets ``face_labels`` ({station: where}) for the stations moved, which
    ``saengine.design.check._where`` reports."""
    offsets = offsets_of(project, pieces, face_offsets)
    if offsets is None or not any(i > 0 or j > 0 for i, j in offsets.values()):
        return Faced(list(pieces), "joints", notes=[JOINT_NOTE])
    out: list[Any] = []
    notes: list[str] = []
    for piece in pieces:
        i_face, j_face = offsets.get(piece.id, (0.0, 0.0))
        length = float(piece.length)
        if i_face <= 0 and j_face <= 0:
            out.append(piece)
            continue
        if i_face + j_face >= length:
            # The supports overlap the whole piece (a stub between two faces): keep it whole.
            notes.append(f"{piece.name}: the supports cover the element, its forces kept")
            out.append(piece)
            continue
        d = shear_depth or 0.0
        i_shear = i_face + d if i_face > 0 else 0.0
        j_shear = j_face + d if j_face > 0 else 0.0
        clear = length - i_face - j_face
        if i_shear - i_face + j_shear - j_face > clear:
            # The sections at d meet: both at mid-clear-span.
            i_shear = i_face + clear / 2 if i_face > 0 else 0.0
            j_shear = j_face + clear / 2 if j_face > 0 else 0.0
        bounds = (length, i_face, j_face, i_shear, j_shear)
        moved_all: set[int] = set()
        shear_all: set[int] = set()
        copied = copy.copy(piece)
        copied.forces = _clamp_list(
            piece.forces, bounds, (face_rows or {}).get(piece.id), moved_all, shear_all
        )
        # The lateral and sustained parts have no face rows of their own: interpolated.
        copied.sway = _clamp_list(getattr(piece, "sway", None), bounds, None, moved_all, shear_all)
        copied.sustained = _clamp_list(
            getattr(piece, "sustained", None), bounds, None, moved_all, shear_all
        )
        count = len(piece.forces[0]) if piece.forces else 0
        labels: dict[int, str] = {}
        with_d = shear_depth is not None and shear_depth > 0
        for k in sorted(moved_all):
            x = length * k / max(count - 1, 1)
            near_i = x < length / 2
            off = i_face if near_i else j_face
            text = f"{piece.name} at the support face, {off:.2f} m from the joint"
            if with_d:
                text += ", shear at d from the face"
            labels[k] = text
        for k in sorted(shear_all - moved_all):
            labels[k] = (
                f"{piece.name} at {k / max(count - 1, 1):.2f} L (shear taken at d from the face)"
            )
        copied.face_labels = labels
        out.append(copied)
    return Faced(
        out,
        "analysis",
        offsets={k: v for k, v in offsets.items() if v[0] > 0 or v[1] > 0},
        shear_depth=shear_depth if shear_depth and shear_depth > 0 else None,
        notes=notes,
    )


def annotate(checks: list[dict[str, Any]], faced: Faced) -> list[dict[str, Any]]:
    """Adds where the forces were taken to the beam or column ``checks`` (flexure and axial
    with bending: the faces; shear: the faces or d from them), in place; returns them."""
    for check in checks:
        name = check.get("name", "")
        if name.startswith(("Flexure", "Axial force and")):
            extra = faced.describe()
        elif name == "Shear" or name.startswith("Minimum stirrups"):
            extra = faced.shear_note()
        else:
            continue
        note = check.get("note") or ""
        check["note"] = f"{note}; {extra}" if note else extra
    return checks


__all__ = [
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
    "shear_depth",
]

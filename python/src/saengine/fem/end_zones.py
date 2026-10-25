"""Rigid end zones of beams and columns, and their forces at the support faces.

Where a beam frames into a column its clear span starts at the column's face; where a column
meets the beams of a floor its clear height ends at their soffit. Like a commercial analysis
program (and normal BNBC 2020 Part 6 Chapter 6 / ACI 318 practice), the analysis model
(:mod:`saengine.fem.derive`) gives such member ends an end offset:

- the **end offset** ``a`` is the distance from the joint (the analysis node, on the column
  axis or at the top of the floor) to the support face: for a beam, half the column's
  dimension along the beam (:func:`support_reach`, the column's rotation taken into account);
  for a column below a floor, the depth of the deepest beam framing into its top (or of the
  slab where no beam does), so its top face is the beam soffit; a column's bottom is the top of
  the floor below, the node itself (no offset);
- the **rigid zone** is ``rigidZoneFactor · a`` (0.5 by default, a setting): the element is
  rigid over it (OpenSees ``geomTransf ... -jntOffset``, OpenSees Studio's ``joint_offsets``)
  and deforms over the rest. The uniform loads on the rigid zones go straight to the joints
  (the element carries its load over its flexible length only);
- the **face forces** are the section forces at distance ``a`` from the joint
  (:func:`face_forces`): for a beam its moments at the column faces, for a column its moments
  at the beam soffit. The design checks them (``design.face_forces``).

The derivation records, per analysis element, the offsets of its ends (``08 FEM/faces.json``,
:data:`FACES_FILE`): ``{"schema", "rigidZoneFactor", "elements": {id: {"i"|"j": {"offset":
a mm, "rigid": rigid zone mm, "at": [element id, distance from that element's node i in m]}}}}``
— ``at`` is where the face is: on the element itself, or further along the member when the
face lies beyond a short element of a meshed member.

Units: the model's (m, N, N·m); offsets in the faces file in mm.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

#: The derivation's record of the member end offsets, beside the analysis model.
FACES_FILE = "faces.json"
FACES_SCHEMA = "saengine.faces/1"
#: The face forces of every static case, in the analysis results folder.
FACE_FORCES_FILE = "face-forces.json"
FACE_FORCES_SCHEMA = "saengine.faceForces/1"
#: The rigid zone of one end is at most this share of its element's length (a short element
#: of a meshed member): the element must keep a flexible part.
RIGID_SHARE_LIMIT = 0.45
COMPONENTS = ("N", "Vy", "Vz", "T", "My", "Mz")


def profile_extent(profile: Any) -> tuple[float, float] | None:
    """A profile's overall dimensions along its x and y axes [mm] (its bounding rectangle;
    a circle's diameter both ways), or None for an unknown profile."""
    shape = getattr(profile, "shape", None)
    if shape in ("rectangle", "rectangleHollow"):
        return float(profile.xDim), float(profile.yDim)
    if shape in ("circle", "circleHollow"):
        return 2 * float(profile.radius), 2 * float(profile.radius)
    if shape == "I":
        return float(profile.overallWidth), float(profile.overallDepth)
    if shape in ("T", "U"):
        return float(profile.flangeWidth), float(profile.depth)
    if shape == "L":
        return float(profile.width), float(profile.depth)
    return None


def profile_depth(profile: Any) -> float | None:
    """A beam profile's depth [mm] (along its y axis)."""
    extent = profile_extent(profile)
    return extent[1] if extent else None


def support_reach(profile: Any, rotation: float, direction: tuple[float, float]) -> float:
    """Distance [mm] from a column's axis to its face along the plan ``direction`` (any length),
    the column's profile turned by ``rotation`` degrees: half its width along that direction for
    a rectangle (where the ray leaves the rotated rectangle), the radius for a circle. 0 for an
    unknown profile or a zero direction."""
    extent = profile_extent(profile)
    length = math.hypot(*direction)
    if extent is None or length < 1e-12:
        return 0.0
    if getattr(profile, "shape", None) in ("circle", "circleHollow"):
        return extent[0] / 2
    angle = math.radians(rotation)
    ux, uy = direction[0] / length, direction[1] / length
    # The direction in the profile's own axes.
    lx = ux * math.cos(angle) + uy * math.sin(angle)
    ly = -ux * math.sin(angle) + uy * math.cos(angle)
    reach = math.inf
    if abs(lx) > 1e-12:
        reach = min(reach, extent[0] / 2 / abs(lx))
    if abs(ly) > 1e-12:
        reach = min(reach, extent[1] / 2 / abs(ly))
    return float(reach)


def section_at(end_forces: np.ndarray, load: np.ndarray, x: float) -> np.ndarray:
    """Section forces N, Vy, Vz, T, My, Mz at distance ``x`` [m] from an element's (rigid) end
    i, from its OpenSees ``localForce`` (12 values) and uniform local load (wx, wy, wz): the
    convention of :func:`saengine.fem.display.element_section_forces` (tension positive; at the
    far end the end forces at j)."""
    f, m = np.asarray(end_forces[0:3], dtype=float), np.asarray(end_forces[3:6], dtype=float)
    w = np.asarray(load, dtype=float)
    forces = -(f + x * w)
    moments = -(
        m
        + np.array([0.0, x * f[2], -x * f[1]])
        + np.array([0.0, w[2] * x**2 / 2, -w[1] * x**2 / 2])
    )
    return np.concatenate([forces, moments])


def element_offsets(element: dict[str, Any]) -> tuple[float, float]:
    """The rigid zone lengths (i, j) [m] of an analysis element (its ``joint_offsets``)."""
    offsets = element.get("joint_offsets")
    if not offsets:
        return 0.0, 0.0
    return float(np.linalg.norm(offsets[0:3])), float(np.linalg.norm(offsets[3:6]))


def face_section_forces(
    elements: dict[int, dict[str, Any]],
    end_forces: dict[int, np.ndarray],
    loads: dict[int, np.ndarray],
    faces: dict[str, Any],
) -> dict[int, dict[str, dict[str, float]]]:
    """Per element of ``faces["elements"]`` its face forces ``{"i"|"j": {N, Vy, Vz, T, My, Mz}}``
    (N, N·m) from the elements' end forces (OpenSees ``localForce``) and uniform local loads of
    one case. A face beyond its element is read on the element named by its ``at``; the forces
    are in that element's axes (the elements of one member share theirs)."""
    out: dict[int, dict[str, dict[str, float]]] = {}
    for key, ends in (faces.get("elements") or {}).items():
        record: dict[str, dict[str, float]] = {}
        for end, face in ends.items():
            at_id, distance = int(face["at"][0]), float(face["at"][1])
            element = elements.get(at_id)
            forces = end_forces.get(at_id)
            if element is None or forces is None:
                continue
            ri, _ = element_offsets(element)
            values = section_at(forces, loads.get(at_id, np.zeros(3)), distance - ri)
            record[end] = {c: round(float(v), 3) for c, v in zip(COMPONENTS, values, strict=True)}
        if record:
            out[int(key)] = record
    return out


def read_faces(model_path: str | Path) -> dict[str, Any] | None:
    """The faces file beside an analysis model, or None."""
    path = Path(model_path).parent / FACES_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("elements") else None


def face_forces(model_path: str | Path, out_dir: str | Path | None = None) -> dict[str, Any]:
    """The face forces of every static case of an analysed model: ``{"schema",
    "rigidZoneFactor", "faceOffsets": {element id: {"i"|"j": a mm}}, "cases": {case code:
    {element id: {"i"|"j": {N, Vy, Vz, T, My, Mz}}}}}`` (N, N·m, the elements' local axes, the
    convention of :func:`section_at`). Empty ``cases`` without a faces file or results."""
    from opensees_studio.services.result_store import load_manifest, load_results
    from opensees_studio.services.results import StaticResults

    model_path = Path(model_path)
    faces = read_faces(model_path) or {"elements": {}}
    result: dict[str, Any] = {
        "schema": FACE_FORCES_SCHEMA,
        "rigidZoneFactor": faces.get("rigidZoneFactor"),
        "faceOffsets": {
            str(k): {end: face["offset"] for end, face in ends.items()}
            for k, ends in faces["elements"].items()
        },
        "cases": {},
    }
    if not faces["elements"]:
        return result
    project = json.loads(model_path.read_text(encoding="utf-8"))
    if out_dir is None:
        name = model_path.name
        stem = name[: -len(".osmodel")] if name.lower().endswith(".osmodel") else name
        out_dir = model_path.parent / f"{stem}.results"
    try:
        manifest = load_manifest(out_dir)
    except (OSError, ValueError):
        return result
    # The temperature case's fixed-end forces, added back as the design's stations do
    # (saengine.fem.thermal; design.check._demands).
    from saengine.fem.thermal import end_force_corrections, load_corrections

    thermal = load_corrections(model_path)
    elements = {int(e["id"]): e for e in project.get("elements", [])}
    patterns = {p["id"]: p for p in project.get("load_patterns", [])}
    analyses = {a["id"]: a for a in project.get("analyses", [])}
    for entry in manifest.get("cases", []):
        results = load_results(entry, out_dir)
        if not isinstance(results, StaticResults):
            continue
        analysis = analyses.get(int(entry["case_id"]), {})
        pattern_ids = list(analysis.get("pattern_ids", [])) or [
            pid for stage in analysis.get("stages", []) for pid in stage.get("pattern_ids", [])
        ]
        loads: dict[int, np.ndarray] = {}
        for pid in pattern_ids:
            for load in patterns.get(pid, {}).get("element_loads", []):
                total = loads.setdefault(int(load["element_id"]), np.zeros(3))
                total += [load.get("wx", 0.0), load.get("wy", 0.0), load.get("wz", 0.0)]
        reached = float(results.load_factors[-1]) if len(results.load_factors) else 1.0
        end_forces = {
            int(e): np.asarray(rows[-1], dtype=float)[:12]
            for e, rows in results.element_forces.items()
            if rows is not None and len(rows)
        }
        code = str(entry["case_name"]).split(":")[0].strip()
        for e, add in end_force_corrections(thermal, code).items():
            if e in end_forces:
                end_forces[e] = end_forces[e] + reached * add[:12]
        forces = face_section_forces(
            elements, end_forces, {k: v * reached for k, v in loads.items()}, faces
        )
        result["cases"][code] = {str(k): v for k, v in forces.items()}
    return result


def write_face_forces(model_path: str | Path, out_dir: str | Path | None = None) -> Path | None:
    """Write :func:`face_forces` into the results folder (:data:`FACE_FORCES_FILE`); None (and
    nothing written) when the model has no faces file."""
    if read_faces(model_path) is None:
        return None
    model_path = Path(model_path)
    if out_dir is None:
        name = model_path.name
        stem = name[: -len(".osmodel")] if name.lower().endswith(".osmodel") else name
        out_dir = model_path.parent / f"{stem}.results"
    data = face_forces(model_path, out_dir)
    path = Path(out_dir) / FACE_FORCES_FILE
    path.write_text(json.dumps(data), encoding="utf-8")
    return path

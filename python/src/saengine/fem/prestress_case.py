"""The post-tensioning load case PT (#285): the tendons' equivalent loads on the slab shells.

Each tendon group (``bim.SlabTendon``) puts on the concrete, at its effective force P (after the
immediate and the long-term losses, the mean along the group, as the PT checks find it:
:func:`saengine.design.check.tendon_designs`), the loads of load balancing
(:func:`saengine.design.prestress.balancing_loads`):

- an upward load P y'' along each parabolic segment of the profile,
- a point load P Δs where two segments meet (downward at a high point),
- at each anchor the force P along the tendon (into the slab), its vertical component and the
  couple P e of its eccentricity from the mid-depth.

These are in equilibrium on their own. They go into the analysis model's load pattern ``PT``
as nodal forces and moments on the shell nodes of the tendons' slab: along the tendon line for
a banded group, spread evenly across the strip width for a distributed one (to the shell
triangle each point falls in, by its barycentric weights). The shells then carry the balanced
load and the precompression with the restraint of the columns and walls the strip design
leaves out, and the PT case gives the hyperstatic actions in the columns.

The case is analysed on its own (``PT: Post-tensioning``) and, like T and ST, is in no
generated combination: the PT checks of the slabs add the hyperstatic moment themselves, and
the slab's own flexure along the tendons is reported only. Units: the analysis model's m and N.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = ["CASE", "CASE_TITLE", "add_prestress_case", "tendon_point_loads"]

CASE = "PT"
CASE_TITLE = "Post-tensioning"

#: Spacing of the points across a distributed group's width and along the tendon [mm].
_ACROSS = 500.0
_ALONG = 250.0
#: How far [m] a point off the shells may be from a shell node of its slab to go to that node.
_SNAP = 0.1


def tendon_point_loads(
    tendon: Any, force: float, h: float
) -> list[tuple[float, float, np.ndarray]]:
    """The equivalent loads of a tendon group at its force ``force`` [N] in a slab ``h`` thick
    [mm]: (plan x, plan y [mm], [Fx, Fy, Fz, Mx, My, Mz] in N and N·mm). Their sum is zero."""
    from saengine.design import prestress

    points = [(float(p.at), float(p.height)) for p in tendon.profile]
    model, pieces = prestress.strip_model(points)
    distributed, nodal, couples = prestress.balancing_loads(pieces, model, force, h)
    stations = model.stations
    start = np.array([float(tendon.x1), float(tendon.y1)])
    run = np.array([float(tendon.x2), float(tendon.y2)]) - start
    plan = float(np.linalg.norm(run))
    u = run / plan
    across = np.array([-u[1], u[0]])
    # The profile's distances are along the tendon; its plan length scales them onto the line.
    scale = plan / float(stations[-1])
    width = float(tendon.width)
    count = (
        max(1, round(width / _ACROSS))
        if getattr(tendon, "layout", "banded") == "distributed"
        else 1
    )
    offsets = [(k + 0.5) / count * width - width / 2 for k in range(count)] if count > 1 else [0.0]
    # The anchor couple's vector: about the plan axis across the tendon (u x Z, the strip's
    # counter-clockwise couples with x along u and y up).
    couple_axis = np.array([u[1], -u[0], 0.0])
    out: list[tuple[float, float, np.ndarray]] = []

    def put(at: float, vector: np.ndarray) -> None:
        share = vector / len(offsets)
        base = start + u * at * scale
        for offset in offsets:
            x, y = base + across * offset
            out.append((float(x), float(y), share))

    # The distributed upward load, lumped at points about _ALONG apart within each element.
    for e in range(len(stations) - 1):
        q = float(distributed[e])
        if q == 0.0:
            continue
        x0, x1 = float(stations[e]), float(stations[e + 1])
        parts = max(1, math.ceil((x1 - x0) / _ALONG))
        piece = (x1 - x0) / parts
        for k in range(parts):
            put(x0 + (k + 0.5) * piece, np.array([0.0, 0.0, q * piece, 0.0, 0.0, 0.0]))
    for i, (fz, couple) in enumerate(zip(nodal, couples, strict=True)):
        if fz or couple:
            vector = np.zeros(6)
            vector[2] = float(fz)
            vector[3:] = couple_axis * float(couple)
            put(float(stations[i]), vector)
    # The anchors: the force into the slab along the tendon (in plan; the slope's vertical part
    # is in the nodal loads above).
    horizontal = np.array([u[0], u[1], 0.0]) * force
    put(0.0, np.concatenate([horizontal, np.zeros(3)]))
    put(float(stations[-1]), np.concatenate([-horizontal, np.zeros(3)]))
    return out


def _triangles(project: dict[str, Any], slab_id: str) -> list[tuple[int, int, int]]:
    found = []
    for e in project.get("elements", []):
        if e.get("type") != "Shell":
            continue
        if (e.get("name") or str(e["id"])).split("#")[0] != slab_id:
            continue
        corners = list(e["nodes"])
        for k in range(1, len(corners) - 1):
            found.append((corners[0], corners[k], corners[k + 1]))
    return found


def add_prestress_case(
    project: dict[str, Any], designs: list[dict[str, Any]]
) -> tuple[int | None, list[str]]:
    """Add the case PT to an OpenSees Studio ``project`` (in place) from the tendon designs of
    :func:`saengine.design.check.tendon_designs`. Returns (the analysis id, or None when no
    load reached the shells, notes)."""
    from saengine.fem.derive import _barycentric

    notes: list[str] = []
    coords = {int(n["id"]): np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    loads: dict[int, np.ndarray] = {}
    groups = 0
    for row in designs:
        tendon, design = row["tendon"], row["design"]
        triangles = _triangles(project, row["slab"])
        if not triangles:
            notes.append(
                f"PT: {row['slab']} is not analysed as shells; tendon {tendon.id} is left out of "
                "the case PT (its strip is designed by the PT checks)"
            )
            continue
        force = float(np.mean(design.forces.effective))
        slab_nodes = sorted({n for nodes in triangles for n in nodes})
        lost = 0.0
        for x, y, vector in tendon_point_loads(tendon, force, row["h"]):
            point = np.array([x / 1e3, y / 1e3])
            for nodes in triangles:
                weights = _barycentric(point, [coords[n] for n in nodes])
                if weights is None:
                    continue
                for node_id, weight in zip(nodes, weights, strict=True):
                    if weight:
                        # N·mm -> N·m for the moments.
                        scaled = vector * weight
                        scaled[3:] /= 1e3
                        loads[node_id] = loads.get(node_id, np.zeros(6)) + scaled
                break
            else:
                # On the slab's edge (an anchor) a round-off can miss every triangle: the
                # nearest shell node within _SNAP takes the load.
                distance, nearest = min(
                    (float(np.linalg.norm(coords[n][:2] - point)), n) for n in slab_nodes
                )
                if distance <= _SNAP:
                    scaled = vector.copy()
                    scaled[3:] /= 1e3
                    loads[nearest] = loads.get(nearest, np.zeros(6)) + scaled
                else:
                    lost += float(np.linalg.norm(vector[:3]))
        groups += 1
        if lost > 1.0:
            notes.append(
                f"PT: {lost / 1e3:.1f} kN of the loads of tendon {tendon.id} fall off the shells "
                f"of {row['slab']} (an opening or outside the slab); not applied, so the case is "
                "not in equilibrium there: keep the tendons on the slab"
            )
    if not loads:
        return None, notes
    series = next(
        (s["id"] for s in project.get("time_series", []) if s.get("type") == "Linear"), None
    )
    if series is None:
        series = 1 + max((s["id"] for s in project.get("time_series", [])), default=0)
        project.setdefault("time_series", []).append(
            {"id": series, "name": "", "type": "Linear", "factor": 1.0}
        )
    pattern = {
        "id": 1 + max((p["id"] for p in project.get("load_patterns", [])), default=0),
        "name": CASE,
        "type": "Plain",
        "time_series_id": series,
        "nodal_loads": [
            {"node_id": n, "forces": [round(float(f), 3) for f in v]}
            for n, v in sorted(loads.items())
        ],
        "element_loads": [],
    }
    project.setdefault("load_patterns", []).append(pattern)
    analysis = {
        "id": 1 + max((a["id"] for a in project.get("analyses", [])), default=0),
        "name": f"{CASE}: {CASE_TITLE}",
        "type": "Static",
        "pattern_ids": [pattern["id"]],
        "n_steps": 1,
        "load_factor_increment": 1.0,
        "system": "BandGeneral",
        "constraints": "Transformation",
        "integrator": "LoadControl",
        "algorithm": "Linear",
        "test": "NormDispIncr",
        "tolerance": 1e-8,
        "max_iter": 25,
    }
    project.setdefault("analyses", []).append(analysis)
    notes.append(
        f"PT: the equivalent loads of {groups} tendon group(s) at their effective force are the "
        "case PT (analysed on its own, in no generated combination: the PT checks add the "
        "hyperstatic moments themselves)"
    )
    return int(analysis["id"]), notes

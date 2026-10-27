"""Raft foundations: a plate on Winkler springs (Part 9, mat foundations).

The model (:func:`raft_model`), in SI units (m, N), built with SAEngine's own machinery and run
with OpenSees Studio's runner, as the building's analysis is:

- the raft's plan outline meshed by Gmsh (:func:`saengine.fem.mesh.mesh`) into four-node
  shells (triangles where quadrilaterals do not fit) no larger than ``design.raftMeshSize``,
  ASDShellQ4 / ASDShellT3 with an elastic plate section of the raft's thickness and its
  concrete's E and ν (``ElasticMembranePlateSection``);
- a vertical spring under every node (a ``ZeroLength`` element in the vertical direction to a
  fixed node at the same place) of stiffness ``k = ks A``, A the node's share of the plan
  area under a uniform pressure (the consistent shares of the shells,
  :func:`saengine.fem.mesh.shell_node_shares`), so a uniform pressure q settles exactly q/ks;
- compression-only springs by default: an elastic material with a tension modulus of 10⁻⁶ of
  the compression one, solved with Newton iterations, so where the raft lifts off the soil
  carries nothing (``compression_only=False``: linear springs, which may pull);
- the raft's horizontal translations and its drilling rotation are restrained (the model
  carries vertical loads; horizontal forces are not analysed here);
- the column loads as nodal loads, each spread to the corners of the shell under the column's
  centre by its shape functions (the force and the two moments), in every service and strength
  combination (:data:`saengine.substructure.shallow.Loads`, here in global X and Y: ``[P, Cx, Cy]``
  the downward force [N] and the moments [N·mm] the column puts on the raft); the raft's own
  weight and any ``surcharge`` [kPa] on it as nodal loads by the same shares, times the
  combination's dead-load factor. Each combination is one analysis case (the springs make the
  model nonlinear: combinations are not superposed).

From the results (:func:`raft_design`):

- contact pressure ``p = ks max(-w, 0)`` at each node (``-ks w`` with linear springs), the
  gross pressure; less the overburden at the founding level it is the net pressure, checked
  against the net allowable pressure qa of the soil report for the raft (service
  combinations);
- settlement ``-w - overburden/ks`` (gravity service combinations, the sustained loads): the
  springs carry the gross load, the soil settles under the net pressure (ks is the soil's
  secant net pressure / settlement), so the uniform rebound of the overburden the excavation
  removed is taken off (exact for linear springs in contact; it does not change the
  differential settlements); the largest, and for every pair of neighbouring columns the
  differential settlement and the angular distortion δ/L, against BNBC 2020 Part 6 Table
  6.3.8 for rafts of RCC structures: 75 mm, 0.0021 L and 1/500 on sand and hard clay, 100 mm,
  0.002 L and 1/500 on plastic clay ("a guide", Table 6.3.8's note; L the centre-to-centre
  distance of the columns). Neighbours: the columns within 1.5 times a column's distance to
  its nearest one;
- flexure and one-way shear of the raft by :func:`saengine.design.slab.slab_checks` (Wood-Armer
  moments at every integration point averaged over design strips on the column lines, ACI
  318-19), with the raft's shells, its columns and its reinforcement (strength combinations);
- punching at each column (ACI 22.6): the critical section at d/2 from the column's faces cut
  by the raft's edges (:func:`saengine.design.slab.critical_section`), d the mean of the bottom
  layers, ``Vu = P + the raft's factored weight and surcharge inside the section - the soil
  reaction inside it`` (the springs' forces and the nodal shares of the nodes inside it) plus
  ``γv M c / Jc`` for the column's moments (:func:`saengine.design.slab.punching_stress`), vc
  of 22.6.5.2 (:func:`saengine.design.slab.punching_capacity`).

ks (kN/m³): ``design.springsFrom`` a value, or from the soil report: :func:`raft_ks` gives the
secant ``q_net / s`` of the whole raft's settlement at its founding level under its average
net service pressure (gross less the overburden) (:func:`saengine.soil.settlement.settlement`
with the raft's plan size), which Part 1 recommends over the small-plate ks for a raft.

Results for the editor (``raft`` in the report; every list in the order of ``nodes`` or
``elements``):

- ``nodes``: [[x, y]] mm (plan); ``elements``: [[node index, ...]] (0-based, 3 or 4 each);
- ``pressure``: gross contact pressure per node [kPa], the largest over the service
  combinations; ``settlement``: per node [mm], the largest net settlement
  ``-w - overburden/ks`` over the gravity service combinations (0 where the raft lifts off);
- ``moments``: per element [kN·m/m], the envelope over the strength combinations of the
  element's mean Wood-Armer design moments ``bottomX``, ``bottomY``, ``topX``, ``topY`` and of
  the signed ``mxMax``, ``mxMin``, ``myMax``, ``myMin`` (sagging positive, raft axes = global);
- ``columns``: [{id, x, y, settlement, pressure}] (largest per column);
- ``summary``: the largest pressure, settlement, differential settlement and angular
  distortion, and ``rebound`` [mm] (overburden / ks, taken off the spring displacements);
  ``ks``, ``meshSize``, ``compressionOnly``, ``uplift`` (nodes off the soil in the worst
  service combination).

Units: mm, N, N·mm inside the loads; kPa, mm, kN·m/m reported.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.design import punching
from saengine.design.punching import Demand
from saengine.design.rc import PHI_SHEAR, STEEL_E
from saengine.design.slab import (
    ColumnJoint,
    ShellPoint,
    SlabContext,
    critical_section,
    integration_areas,
    integration_points,
    layers_of,
    plan_axes,
    punching_capacity,
    punching_stress,
    shell_axes,
    slab_checks,
    slab_forces,
    wood_armer,
)
from saengine.library.objects import PlanarReinforcement

#: Tension stiffness of a compression-only spring, as a share of its compression stiffness.
TENSION_SHARE = 1e-6
#: Gmsh keeps global state: one raft mesh at a time.
MESH_LOCK = threading.Lock()
#: BNBC 2020 Part 6 Table 6.3.8, raft foundations of RCC structures: soil column ->
#: (maximum settlement [mm], differential settlement / L, angular distortion).
RAFT_LIMITS = {
    "sand": (75.0, 0.0021, 1 / 500),
    "plasticClay": (100.0, 0.002, 1 / 500),
}
SOIL_NAMES = {"sand": "sand and hard clay", "plasticClay": "plastic clay"}
#: A column's neighbours lie within this multiple of its distance to the nearest one.
NEIGHBOURS = 1.5


@dataclass(frozen=True)
class RaftColumn:
    """A column standing on the raft: plan position [mm], section c1 (along its u axis, at
    ``angle`` degrees from global X) × c2 [mm]."""

    id: str
    x: float
    y: float
    c1: float
    c2: float
    angle: float = 0.0


@dataclass
class RaftSpec:
    """A raft to analyse and design."""

    id: str
    outline: list[tuple[float, float]]  # plan, mm
    thickness: float  # mm
    E: float  # MPa
    fc: float  # MPa
    fy: float  # MPa
    reinforcement: PlanarReinforcement | None
    columns: list[RaftColumn]
    ks: float  # kN/m³
    nu: float = 0.2
    es: float = STEEL_E
    mesh_size: float = 500.0  # mm
    unit_weight: float = 24.0  # kN/m³
    surcharge: float = 0.0  # kPa, dead load on the raft besides its weight
    compression_only: bool = True
    notes: list[str] = field(default_factory=list)
    #: The raft's punching studs or stirrups (``objects.PunchingReinforcement``) or None: checked
    #: where given, else proposed where the concrete alone is not enough
    #: (:mod:`saengine.design.punching`).
    punching_reinforcement: Any = None


@dataclass
class RaftMesh:
    """The raft's mesh: node coordinates [m] (plan, index = node id - 1), shells (0-based
    node indices) and each node's share of the plan area [m²]."""

    nodes: np.ndarray
    shells: list[tuple[int, ...]]
    shares: np.ndarray


@dataclass
class RaftResults:
    """Per combination: the nodes' vertical displacement [m] and the shells' forces (rows of
    N11 N22 N12 M11 M22 M12 Q13 Q23 per integration point)."""

    mesh: RaftMesh
    combinations: list[str]
    w: dict[str, np.ndarray]
    shells: dict[str, list[np.ndarray]]
    notes: list[str] = field(default_factory=list)


# ─────────────────────────────────────── mesh ───────────────────────────────────────


def raft_mesh(outline: list[tuple[float, float]], size: float) -> RaftMesh:
    """Gmsh mesh of the outline [mm] with elements no larger than ``size`` [mm]."""
    from saengine.fem.mesh import Surface, mesh, shell_node_shares

    if len(outline) < 3:
        raise ValueError("the raft's outline needs at least three points")
    points = [(float(x), float(y), 0.0) for x, y in outline]
    with MESH_LOCK:
        found = mesh([], [Surface("raft", points, normal=(0.0, 0.0, 1.0))], size)
    elements = found.surfaces.get("raft", [])
    used = sorted({n for e in elements for n in e})
    index = {tag: k for k, tag in enumerate(used)}
    nodes = np.array([found.nodes[tag][:2] / 1e3 for tag in used])
    shells = [tuple(index[n] for n in e) for e in elements]
    shares = np.zeros(len(nodes))
    for shell in shells:
        corners = [np.array([*nodes[n], 0.0]) for n in shell]
        for n, share in zip(shell, shell_node_shares(corners), strict=True):
            shares[n] += share
    return RaftMesh(nodes, shells, shares)


def _shape(points: np.ndarray, p: np.ndarray) -> np.ndarray | None:
    """The shape function values at plan point ``p`` [m] of a 3- or 4-node shell (plan
    corners), or None when the point is outside it."""
    if len(points) == 3:
        a, b, c = points
        matrix = np.column_stack([b - a, c - a])
        if abs(np.linalg.det(matrix)) < 1e-14:
            return None
        s, t = np.linalg.solve(matrix, p - a)
        values = np.array([1 - s - t, s, t])
        return values if values.min() >= -1e-9 else None
    xi = eta = 0.0
    for _ in range(25):
        n = (
            np.array(
                [
                    (1 - xi) * (1 - eta),
                    (1 + xi) * (1 - eta),
                    (1 + xi) * (1 + eta),
                    (1 - xi) * (1 + eta),
                ]
            )
            / 4
        )
        d_xi = np.array([-(1 - eta), 1 - eta, 1 + eta, -(1 + eta)]) / 4
        d_eta = np.array([-(1 - xi), -(1 + xi), 1 + xi, 1 - xi]) / 4
        residual = n @ points - p
        jacobian = np.column_stack([d_xi @ points, d_eta @ points])
        if abs(np.linalg.det(jacobian)) < 1e-14:
            return None
        step = np.linalg.solve(jacobian, residual)
        xi, eta = xi - step[0], eta - step[1]
        if np.linalg.norm(step) < 1e-12:
            break
    if abs(xi) > 1 + 1e-6 or abs(eta) > 1 + 1e-6:
        return None
    return (
        np.array(
            [(1 - xi) * (1 - eta), (1 + xi) * (1 - eta), (1 + xi) * (1 + eta), (1 - xi) * (1 + eta)]
        )
        / 4
    )


def locate(mesh: RaftMesh, x_mm: float, y_mm: float) -> tuple[tuple[int, ...], np.ndarray] | None:
    """The shell under a plan point [mm] and its shape function values there."""
    p = np.array([x_mm, y_mm]) / 1e3
    for shell in mesh.shells:
        corners = mesh.nodes[list(shell)]
        lo, hi = corners.min(axis=0), corners.max(axis=0)
        if np.any(p < lo - 1e-9) or np.any(p > hi + 1e-9):
            continue
        values = _shape(corners, p)
        if values is not None:
            return shell, values
    return None


# ─────────────────────────────────────── model ───────────────────────────────────────


def raft_model(
    spec: RaftSpec,
    mesh: RaftMesh,
    combinations: dict[str, tuple[list[np.ndarray], float]],
) -> tuple[dict[str, Any], list[str]]:
    """The OpenSees Studio project of the raft: per combination name, (column loads, dead-load
    factor). Returns the project and notes."""
    notes: list[str] = []
    count = len(mesh.nodes)
    k_values = spec.ks * 1e3 * mesh.shares  # N/m
    nodes = []
    for i, (x, y) in enumerate(mesh.nodes):
        coords = [round(float(x), 6), round(float(y), 6), 0.0]
        nodes.append(
            {
                "id": i + 1,
                "name": "",
                "coords": coords,
                "restraint": [True, True, False, False, False, True],
            }
        )
    for i, (x, y) in enumerate(mesh.nodes):
        nodes.append(
            {
                "id": count + i + 1,
                "name": "",
                "coords": [round(float(x), 6), round(float(y), 6), 0.0],
                "restraint": [True] * 6,
            }
        )
    materials = []
    for i, k in enumerate(k_values):
        material: dict[str, Any] = {"id": i + 1, "name": "", "type": "Elastic", "E": float(k)}
        if spec.compression_only:
            # Spring strain = ground - raft displacement: positive when the raft goes down.
            material["Eneg"] = float(k) * TENSION_SHARE
        materials.append(material)
    elements: list[dict[str, Any]] = []
    for shell in mesh.shells:
        elements.append(
            {
                "id": len(elements) + 1,
                "name": f"{spec.id}",
                "type": "Shell",
                "formulation": "ASDShellQ4" if len(shell) == 4 else "ASDShellT3",
                "nodes": [n + 1 for n in shell],
                "section_id": 1,
            }
        )
    for i in range(count):
        elements.append(
            {
                "id": len(elements) + 1,
                "name": f"spring {i + 1}",
                "type": "ZeroLength",
                "nodes": [i + 1, count + i + 1],
                "material_ids": [i + 1],
                "dofs": [3],
            }
        )
    placed: dict[str, tuple[tuple[int, ...], np.ndarray]] = {}
    for column in spec.columns:
        found = locate(mesh, column.x, column.y)
        if found is None:
            notes.append(f"{column.id} is outside the raft {spec.id}: its load is left out")
        else:
            placed[column.id] = found
    weight = (spec.unit_weight * spec.thickness / 1e3 + spec.surcharge) * 1e3  # N/m²
    patterns, analyses = [], []
    for number, (name, (loads, dead)) in enumerate(combinations.items(), start=1):
        forces = np.zeros((count, 6))
        forces[:, 2] -= dead * weight * mesh.shares
        for column, load in zip(spec.columns, loads, strict=True):
            if column.id not in placed:
                continue
            shell, values = placed[column.id]
            for n, share in zip(shell, values, strict=True):
                forces[n, 2] -= share * float(load[0])
                forces[n, 3] += share * float(load[1]) / 1e3
                forces[n, 4] += share * float(load[2]) / 1e3
        patterns.append(
            {
                "id": number,
                "name": name,
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [
                    {"node_id": i + 1, "forces": [round(float(f), 4) for f in row]}
                    for i, row in enumerate(forces)
                    if np.any(row)
                ],
                "element_loads": [],
            }
        )
        analyses.append(
            {
                "id": number,
                "name": name,
                "type": "Static",
                "pattern_ids": [number],
                "n_steps": 1,
                "load_factor_increment": 1.0,
                "system": "BandGeneral",
                "constraints": "Plain",
                "integrator": "LoadControl",
                "algorithm": "Newton" if spec.compression_only else "Linear",
                "test": "NormDispIncr",
                "tolerance": 1e-10,
                "max_iter": 100,
            }
        )
    project = {
        "meta": {"name": f"Raft {spec.id}"},
        "ndm": 3,
        "ndf": 6,
        "nodes": nodes,
        "materials": materials,
        "sections": [
            {
                "id": 1,
                "name": f"{spec.id} {spec.thickness:g} mm",
                "type": "ElasticMembranePlateSection",
                "E": spec.E * 1e6,
                "nu": spec.nu,
                "h": spec.thickness / 1e3,
                "rho": 0.0,
            }
        ],
        "elements": elements,
        "time_series": [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}],
        "load_patterns": patterns,
        "analyses": analyses,
    }
    return project, notes


def run_raft(
    spec: RaftSpec,
    combinations: dict[str, tuple[list[np.ndarray], float]],
    folder: str | Path,
    mesh: RaftMesh | None = None,
) -> RaftResults:
    """Mesh the raft, build its model, run every combination with OpenSees Studio's runner (in
    ``folder``: ``raft-<id>.osmodel`` and its results) and read the results back."""
    from opensees_studio.services.result_store import load_manifest, load_results

    mesh = mesh or raft_mesh(spec.outline, spec.mesh_size)
    project, notes = raft_model(spec, mesh, combinations)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"raft-{_safe(spec.id)}"
    model = folder / f"{stem}.osmodel"
    out = folder / f"{stem}.results"
    if out.exists():
        shutil.rmtree(out)
    model.write_text(json.dumps(project), encoding="utf-8")
    cases = [str(a["id"]) for a in project["analyses"]]
    done = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model), "--cases", *cases,
         "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )  # fmt: skip
    if done.returncode != 0:
        message = _error(done.stdout) or done.stderr[-1500:]
        raise RuntimeError(f"the raft analysis of {spec.id} failed: {message}")
    names = list(combinations)
    w: dict[str, np.ndarray] = {}
    shells: dict[str, list[np.ndarray]] = {}
    count = len(mesh.nodes)
    for entry in load_manifest(str(out))["cases"]:
        results = load_results(entry, str(out))
        name = names[int(entry["case_id"]) - 1]
        w[name] = np.array([results.node_disp[i + 1][-1, 2] for i in range(count)])
        shells[name] = [
            np.asarray(results.shell_forces[k + 1][-1], dtype=float).reshape(-1, 8)
            for k in range(len(mesh.shells))
        ]
    return RaftResults(mesh, names, w, shells, notes)


def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text) or "raft"


def _error(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("type") == "error":
            return str(data.get("message"))
    return None


# ─────────────────────────────────────── ks ───────────────────────────────────────


def raft_ks(profile: Any, b: float, l_: float, df: float, q: float) -> dict[str, Any]:
    """Secant ks [kN/m³] of a whole raft B × L [m] founded Df [m] below the borehole's ground
    under a net pressure q [kPa]: q / s, s by :func:`saengine.soil.settlement.settlement`."""
    from saengine.soil.settlement import rounded, settlement

    result = rounded(settlement(profile, b, l_, df, q, foundation="raft"))
    total = result["total"]
    if q <= 0 or total <= 0:
        return {"value": None, "settlement": result, "note": "no settlement computed"}
    return {
        "value": round(q / (total / 1e3)),
        "settlement": result,
        "method": (
            f"ks = q/s of the whole raft {b:.1f} × {l_:.1f} m at Df = {df:.2f} m under its "
            f"average net pressure {q:.0f} kPa (s = {total:.1f} mm)"
        ),
    }


# ─────────────────────────────────────── design ───────────────────────────────────────


def _gravity(name: str) -> bool:
    return not any(word in name for word in ("W", "E"))


def _pressure(spec: RaftSpec, w: np.ndarray) -> np.ndarray:
    """Contact pressure [kPa] from the vertical displacements [m]."""
    if spec.compression_only:
        return spec.ks * np.maximum(-w, 0.0) + spec.ks * TENSION_SHARE * np.minimum(-w, 0.0)
    return -spec.ks * w


def _at(mesh: RaftMesh, column: RaftColumn, values: np.ndarray) -> float | None:
    found = locate(mesh, column.x, column.y)
    if found is None:
        return None
    shell, shape = found
    return float(shape @ values[list(shell)])


def neighbour_pairs(columns: list[RaftColumn]) -> list[tuple[int, int]]:
    """Pairs of neighbouring columns: each column with those within :data:`NEIGHBOURS` times
    its distance to the nearest one."""
    pairs: set[tuple[int, int]] = set()
    for i, a in enumerate(columns):
        distances = [(math.hypot(b.x - a.x, b.y - a.y), j) for j, b in enumerate(columns) if j != i]
        if not distances:
            continue
        nearest = min(d for d, _ in distances)
        for d, j in distances:
            if d <= NEIGHBOURS * nearest + 1e-6:
                pairs.add((min(i, j), max(i, j)))
    return sorted(pairs)


def raft_design(
    spec: RaftSpec,
    service: dict[str, list[np.ndarray]],
    strength: dict[str, list[np.ndarray]],
    folder: str | Path,
    qa: float | None = None,
    overburden: float = 0.0,
    soil: str = "sand",
    dead_factor: dict[str, float] | None = None,
    strength_dead_factor: dict[str, float] | None = None,
    gravity: list[str] | None = None,
) -> dict[str, Any]:
    """Analyse the raft under every combination and check it (see the module notes).

    ``service`` / ``strength``: per combination the column loads (one ``[P, Cx, Cy]`` per
    column of ``spec.columns``); ``qa`` the net allowable pressure [kPa] (None: not checked),
    ``overburden`` [kPa] the soil pressure at the founding level the excavation removed;
    ``soil``: Table 6.3.8's column, "sand" or "plasticClay"; ``dead_factor`` /
    ``strength_dead_factor``: the dead-load factor per combination (default 1.0 / 1.2);
    ``gravity``: the service combinations for the settlement (default: those without W or E).

    Returns ``{"checks", "raft", "notes"}`` (``raft``: see the module notes)."""
    from saengine.design.check import _check

    combinations: dict[str, tuple[list[np.ndarray], float]] = {}
    for name, loads in service.items():
        combinations[f"S: {name}"] = (loads, (dead_factor or {}).get(name, 1.0))
    for name, loads in strength.items():
        combinations[f"U: {name}"] = (loads, (strength_dead_factor or {}).get(name, 1.2))
    results = run_raft(spec, combinations, folder)
    mesh = results.mesh
    notes = list(spec.notes) + results.notes
    checks: list[dict[str, Any]] = []
    gravity = [n for n in service if (gravity is None and _gravity(n)) or n in (gravity or [])]
    if not gravity:
        gravity = list(service)
    # The springs carry the gross load; the soil settles under the net one (the overburden the
    # excavation removed comes back first): a uniform rebound overburden / ks [mm] is taken off.
    rebound = overburden / spec.ks * 1e3 if spec.ks > 0 else 0.0

    def net_settlement(w: np.ndarray) -> np.ndarray:
        return -w * 1e3 - rebound

    # ── service: pressure and settlement ──
    pressure_env = np.zeros(len(mesh.nodes))
    settlement_env = np.zeros(len(mesh.nodes))
    worst_p = (0.0, None)
    uplift = (0, None)
    for name in service:
        w = results.w[f"S: {name}"]
        pressure = _pressure(spec, w)
        pressure_env = np.maximum(pressure_env, pressure)
        if pressure.max() > worst_p[0]:
            worst_p = (float(pressure.max()), name)
        lifted = int(np.sum(w > 0))
        if lifted > uplift[0]:
            uplift = (lifted, name)
        if name in gravity:
            settlement_env = np.maximum(settlement_env, net_settlement(w))
    if worst_p[1] is not None:
        net = worst_p[0] - overburden
        if qa is not None:
            checks.append(
                _check(
                    "Contact pressure (net)",
                    net,
                    qa,
                    "kPa",
                    worst_p[1],
                    f"gross {worst_p[0]:.0f} kPa (Winkler springs, ks = {spec.ks:.0f} kN/m³) "
                    f"less the overburden {overburden:.0f} kPa, against the net allowable "
                    "pressure qa of the soil report",
                )
            )
        else:
            notes.append(
                f"contact pressure: largest {worst_p[0]:.0f} kPa gross ({worst_p[1]}); no qa "
                "to check it against"
            )
    if uplift[0]:
        notes.append(
            f"{uplift[0]} nodes lift off the soil under {uplift[1]}"
            + (" (compression-only springs)" if spec.compression_only else " (springs pull)")
        )
    limit, ratio, angular = RAFT_LIMITS[soil]
    soil_name = SOIL_NAMES[soil]
    max_settlement = float(settlement_env.max()) if len(settlement_env) else 0.0
    checks.append(
        _check(
            "Settlement (max)",
            max_settlement,
            limit,
            "mm",
            None,
            f"Winkler settlement under the net pressure, (p - overburden {overburden:.0f} "
            f"kPa)/ks, gravity service combinations; BNBC 2020 Table 6.3.8, raft of RCC "
            f"structures on {soil_name}: {limit:g} mm (a guide)",
        )
    )
    column_settlement: dict[str, float] = {}
    column_pressure: dict[str, float] = {}
    for column in spec.columns:
        s = _at(mesh, column, settlement_env)
        p = _at(mesh, column, pressure_env)
        if s is not None:
            column_settlement[column.id] = s
        if p is not None:
            column_pressure[column.id] = p
    worst_diff: tuple[float, float, float, str] = (-1.0, 0.0, 0.0, "")
    worst_angle: tuple[float, float, str, str | None] = (-1.0, 0.0, "", None)
    for i, j in neighbour_pairs(spec.columns):
        a, b = spec.columns[i], spec.columns[j]
        span = math.hypot(b.x - a.x, b.y - a.y)
        for name in gravity:
            w = results.w[f"S: {name}"]
            sa, sb = _at(mesh, a, net_settlement(w)), _at(mesh, b, net_settlement(w))
            if sa is None or sb is None or span <= 0:
                continue
            delta = abs(sa - sb)
            use = delta / (ratio * span)
            if use > worst_diff[0]:
                worst_diff = (use, delta, ratio * span, f"{a.id}-{b.id}, L = {span:.0f} mm, {name}")
            distortion = delta / span
            if distortion / angular > worst_angle[0]:
                worst_angle = (distortion / angular, distortion, f"{a.id}-{b.id}", name)
    if worst_diff[0] >= 0:
        _, delta, allowed, where = worst_diff
        checks.append(
            _check(
                "Differential settlement",
                delta,
                allowed,
                "mm",
                None,
                f"between neighbouring columns, BNBC Table 6.3.8: {ratio:g} L on {soil_name}; "
                f"{where}",
            )
        )
        _, distortion, pair, name = worst_angle
        checks.append(
            _check(
                "Angular distortion",
                distortion * 1e3,
                angular * 1e3,
                "‰",
                name,
                f"δ/L between {pair}, BNBC Table 6.3.8: 1/{1 / angular:.0f} on {soil_name}",
            )
        )

    # ── strength: flexure and shear (slab design), punching ──
    shells: list[ShellPoint] = []
    element_moments = {
        key: np.full(len(mesh.shells), -np.inf if key.endswith("Max") else np.inf)
        for key in ("mxMax", "mxMin", "myMax", "myMin")
    }
    design_env = {key: np.zeros(len(mesh.shells)) for key in ("bottomX", "bottomY", "topX", "topY")}
    names = [f"U: {n}" for n in strength]
    axes = plan_axes()
    for k, shell in enumerate(mesh.shells):
        corners = [np.array([*mesh.nodes[n], 0.0]) for n in shell]
        local = shell_axes(corners)
        forces = []
        count = None
        for name in names:
            rows = results.shells[name][k]
            count = len(rows)
            f = slab_forces(rows, local, axes)
            forces.append(f)
            areas_k = np.array(integration_areas(corners, count))
            mean = (areas_k @ f) / areas_k.sum()
            element_moments["mxMax"][k] = max(element_moments["mxMax"][k], mean[0])
            element_moments["mxMin"][k] = min(element_moments["mxMin"][k], mean[0])
            element_moments["myMax"][k] = max(element_moments["myMax"][k], mean[1])
            element_moments["myMin"][k] = min(element_moments["myMin"][k], mean[1])
            design = np.array([wood_armer(*row[:3]) for row in f])
            design_mean = (areas_k @ design) / areas_k.sum()
            for key, value in zip(design_env, design_mean, strict=True):
                design_env[key][k] = max(design_env[key][k], value)
        if count is None:
            continue
        shells.append(
            ShellPoint(
                id=k + 1,
                name=f"{spec.id}#{k + 1}",
                points=integration_points(corners, count),
                forces=forces,
                areas=integration_areas(corners, count),
            )
        )
    joints = [ColumnJoint(c.id, (c.x, c.y), c.c1, c.c2, c.angle) for c in spec.columns]
    if spec.reinforcement is not None and strength and shells:
        context = SlabContext(boundary=list(spec.outline), columns=joints, axes=axes)
        checks += slab_checks(
            "twoWay",
            spec.thickness,
            spec.reinforcement,
            spec.fc,
            spec.fy,
            spec.es,
            shells,
            list(strength),
            context,
        )
        notes += [f"raft: {n}" for n in context.notes]
        _needed_bars(spec, checks)
        checks += _punching(spec, results, strength, strength_dead_factor)
    elif spec.reinforcement is None:
        notes.append(f"{spec.id} has no reinforcement: flexure and punching are not checked")

    summary = {
        "maxPressure": round(worst_p[0], 1),
        "maxPressureCombination": worst_p[1],
        "maxSettlement": round(max_settlement, 2),
        "rebound": round(rebound, 2),
        "maxDifferential": round(worst_diff[1], 2) if worst_diff[0] >= 0 else None,
        "maxAngularDistortion": round(worst_angle[1], 6) if worst_angle[0] >= 0 else None,
    }
    raft = {
        "nodes": [[round(float(x) * 1e3, 1), round(float(y) * 1e3, 1)] for x, y in mesh.nodes],
        "elements": [list(shell) for shell in mesh.shells],
        "pressure": [round(float(v), 2) for v in pressure_env],
        "settlement": [round(float(v), 3) for v in settlement_env],
        "moments": {
            **{k: [round(float(v) / 1e3, 2) for v in values] for k, values in design_env.items()},
            **{
                k: [round(float(v) / 1e3, 2) if math.isfinite(v) else 0.0 for v in values]
                for k, values in element_moments.items()
            },
        },
        "columns": [
            {
                "id": c.id,
                "x": c.x,
                "y": c.y,
                "settlement": _round(column_settlement.get(c.id), 2),
                "pressure": _round(column_pressure.get(c.id), 1),
            }
            for c in spec.columns
        ],
        "summary": summary,
        "ks": spec.ks,
        "meshSize": spec.mesh_size,
        "compressionOnly": spec.compression_only,
        "uplift": uplift[0],
        "soil": soil,
    }
    return {"checks": checks, "raft": raft, "notes": notes}


def _needed_bars(spec: RaftSpec, checks: list[dict[str, Any]]) -> None:
    """A flexure check of a layer the raft has no bars in (capacity 0, utilisation 99) says
    instead how much steel it needs: As from Mu = 0.9 As fy 0.9 d (d with 16 mm bars), at least
    As,min, and the lightest mesh that gives it (as a new foundation's,
    :func:`saengine.substructure.run.minimum_mesh`)."""
    from saengine.substructure.run import BAR_DIAS
    from saengine.substructure.shallow import min_steel_ratio

    cover = spec.reinforcement.cover if spec.reinforcement is not None else 75.0
    d = spec.thickness - cover - 1.5 * 16.0
    for check in checks:
        if not check["name"].startswith("Flexure") or check["capacity"] not in (0, 0.0):
            continue
        moment = float(check["demand"]) * 1e6  # N·mm per metre
        need = moment / (0.9 * spec.fy * 0.9 * d) if d > 0 else math.inf
        need = max(need, min_steel_ratio(spec.fy) * spec.thickness * 1000.0)
        limit = min(3.0 * spec.thickness, 450.0)
        mesh = next(
            (
                f"{dia:g}@{spacing:g}"
                for dia in BAR_DIAS
                for spacing in [min(math.floor(math.pi * dia**2 / 4 * 1e3 / need / 25) * 25, limit)]
                if spacing >= 125
            ),
            None,
        )
        face = "top" if "top" in check["name"] else "bottom"
        check["note"] = (
            f"Needs {face} bars: As ≈ {need:.0f} mm²/m"
            + (f" (e.g. {mesh})" if mesh else "")
            + f" for {check['demand']:.1f} kN·m/m. "
            + check["note"]
        )


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _punching(
    spec: RaftSpec,
    results: RaftResults,
    strength: dict[str, list[np.ndarray]],
    dead_factor: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    from saengine.design.check import _check

    assert spec.reinforcement is not None
    layers = layers_of(spec.reinforcement, spec.thickness)
    bottom = [layers[n] for n in ("bottomX", "bottomY") if layers[n] is not None]
    if not bottom:
        bottom = [layers[n] for n in ("topX", "topY") if layers[n] is not None]
    if not bottom:
        return []
    d = sum(layer.d for layer in bottom) / len(bottom)  # type: ignore[union-attr]
    mesh = results.mesh
    springs = spec.ks * 1e3 * mesh.shares  # N/m per node
    weight = (spec.unit_weight * spec.thickness / 1e3 + spec.surcharge) * 1e3  # N/m²
    checks = []
    for k, column in enumerate(spec.columns):
        section = critical_section(
            (column.x, column.y), column.c1, column.c2, column.angle, d, spec.outline
        )
        if not section.sides:
            continue
        t = math.radians(column.angle)
        u = np.array([math.cos(t), math.sin(t)])
        v = np.array([-math.sin(t), math.cos(t)])
        rel = mesh.nodes * 1e3 - np.array([column.x, column.y])
        lo_u, hi_u, lo_v, hi_v = section.extents
        pu, pv = rel @ u, rel @ v
        inside = (pu >= -lo_u) & (pu <= hi_u) & (pv >= -lo_v) & (pv <= hi_v)
        beta = max(column.c1, column.c2) / min(column.c1, column.c2)
        capacity = punching_capacity(spec.fc, d, section.b0, beta, section.alpha_s)
        phi_vc = PHI_SHEAR * capacity.vc
        worst = None
        demands = []
        for name, loads in strength.items():
            w = results.w[f"U: {name}"]
            if spec.compression_only:
                reaction = springs * np.maximum(-w, 0.0)
            else:
                reaction = -springs * w
            # Free body inside the section: the column load and the raft's factored weight and
            # surcharge there, less the soil reaction under it.
            own = (dead_factor or {}).get(name, 1.2) * weight * float(mesh.shares[inside].sum())
            soil = float(reaction[inside].sum())
            vu = max(float(loads[k][0]) + own - soil, 0.0)
            moment = np.array([float(loads[k][1]), float(loads[k][2])])
            m_u, m_v = float(moment @ v), float(moment @ u)
            stress = punching_stress(section, vu, m_u, m_v)
            demands.append(Demand(vu, m_u, m_v, name))
            if worst is None or stress.vu > worst[0]:
                worst = (stress.vu, stress, vu, name, soil, own)
        if worst is None:
            continue
        vu_max, stress, vu, name, soil, own = worst
        area = section.b0 * d
        plain = _check(
            f"Punching at {column.id}",
            vu_max * area / 1e3,
            phi_vc * area / 1e3,
            "kN",
            name,
            f"{section.location} column, b0 = {section.b0:.0f} mm, d = {d:.0f} mm (bottom), "
            f"Vu = P + weight inside - soil inside = {vu / 1e3:.0f} kN (weight and "
            f"surcharge {own / 1e3:.0f} kN, soil {soil / 1e3:.0f} kN), "
            f"vu = {vu_max:.3f} MPa (direct {stress.direct:.3f}, γv "
            f"{stress.gamma_v[0]:.2f}/{stress.gamma_v[1]:.2f}), vc = {capacity.vc:.3f} MPa "
            f"(ACI 22.6.5.2, λs = {capacity.lambda_s:.2f}); shown as v b0 d",
            utilisation=vu_max / phi_vc,
        )
        if vu_max > phi_vc or spec.punching_reinforcement is not None:
            free_body = (
                f"Vu = P + weight inside - soil inside = {vu / 1e3:.0f} kN ({name}; weight and "
                f"surcharge {own / 1e3:.0f} kN, soil {soil / 1e3:.0f} kN)"
            )
            plain = _punching_with_reinforcement(spec, column, d, demands, bottom, plain, free_body)
        checks.append(plain)
    return checks


def _punching_with_reinforcement(
    spec: RaftSpec,
    column: RaftColumn,
    d: float,
    demands: list[Demand],
    bottom: list[Any],
    plain: dict[str, Any],
    free_body: str,
) -> dict[str, Any]:
    """The punching check of a column on the raft redone with shear reinforcement
    (:func:`saengine.design.punching.slab_punching`, as a flat slab's or a footing's): the
    raft's given studs or stirrups checked, else a layout proposed, over every strength
    combination. ``demands``: each combination's net Vu (the column load and the raft's
    factored weight inside the critical section less the soil reaction there) and the
    column's moments. The outer sections beyond the last line take the same Vu (no further
    soil relief: on the safe side)."""
    given = spec.punching_reinforcement
    kind = given.kind if given is not None else "studs"
    fyt = (given.fyt if given is not None else None) or (
        punching.STUD_FY if kind == "studs" else min(spec.fy, punching.STIRRUP_FY_MAX)
    )
    provided = None
    if given is not None:
        provided = punching.ShearReinforcement(
            kind, float(given.dia), int(given.perLine), int(given.lines),
            float(given.firstLine), float(given.spacing), float(fyt),
        )  # fmt: skip
    cover = spec.reinforcement.cover if spec.reinforcement is not None else 75.0
    flexural = max((layer.dia for layer in bottom), default=16.0)

    def run(layout: Any) -> Any:
        return punching.slab_punching(
            (column.x, column.y),
            column.c1,
            column.c2,
            column.angle,
            d,
            spec.outline,
            demands,
            spec.fc,
            thickness=spec.thickness,
            kind=layout.kind if layout is not None else kind,
            fyt=layout.fyt if layout is not None else fyt,
            covers=(cover, cover),
            flexural_bar=flexural,
            provided=layout,
        )

    name = plain["name"]
    try:
        result = run(provided)
    except (ValueError, ArithmeticError) as error:
        plain["note"] += f"; shear reinforcement not designed: {error}"
        return plain
    if result is None:
        return plain
    row = punching.recheckable(result.check(name), name, run, spec.fy, provided)
    # The free body of the governing combination, as without reinforcement.
    row["note"] = f"{free_body}; {row['note']}"
    return row


# ─────────────────────────────────────── in the report ───────────────────────────────────────

RAFT_METHOD = [
    (
        "Rafts: a plate on Winkler springs analysed with OpenSees (Gmsh shells no larger than "
        "the raft mesh size, ASDShellQ4/T3 with an elastic plate section; a vertical spring "
        "k = ks A at every node, A its consistent share of the area, compression-only; the "
        "horizontal translations and drilling rotations restrained), one analysis per "
        "combination with the columns' support reactions, reversed, as nodal loads spread by "
        "the shape functions of the shell under each column, and the raft's weight and the "
        "soil on it. ks from the soil report: the secant q/s of the whole raft at its founding "
        "level under its average net gravity pressure (soil settlement module), or the value of "
        "9 Substructure → Design."
    ),
    (
        "Raft checks: net contact pressure p = ks (-w) less the overburden against qa (service "
        "combinations); the largest net settlement (-w less the overburden's rebound "
        "overburden/ks, as ks is the soil's net pressure over its settlement), the differential "
        "settlement and angular distortion between neighbouring columns (gravity service "
        "combinations) against BNBC 2020 Part 6 Table 6.3.8 for rafts of RCC structures (75 "
        "mm, 0.0021 L, 1/500 on sand and hard clay; 100 mm, 0.002 L, 1/500 on plastic clay; a "
        "guide); flexure and one-way shear by the slab design (Wood-Armer moments averaged "
        "over column and middle strips, ACI 318-19); punching at d/2 round each column with "
        "Vu = P plus the raft's factored weight and surcharge inside the section less the soil "
        "reaction there, plus γv M c / Jc (ACI 22.6, 8.4.4.2)."
    ),
]


def _inside_outline(x: float, y: float, outline: list[list[float]]) -> bool:
    inside = False
    count = len(outline)
    for k in range(count):
        (x0, y0), (x1, y1) = outline[k], outline[(k + 1) % count]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def design_raft(ctx: Any, foundation: Any) -> tuple[dict[str, Any], list[str]]:
    """The analysis and checks of a raft of the substructure (``ctx``: a
    :class:`saengine.substructure.context.Context`): ``(result, notes)`` in the report's
    format, with ``raft`` (see the module notes) and ``pressure``. Raises
    :class:`~saengine.substructure.context.Skip` when it cannot be designed."""
    import tempfile

    from saengine.library.bim import ColumnElement
    from saengine.library.substructure import polygon_area
    from saengine.soil.settlement import soil_column
    from saengine.substructure.context import Skip, polygon_centroid
    from saengine.substructure.loads import column_action, combine
    from saengine.substructure.piles import nearest_profile, profiles_of
    from saengine.substructure.shallow import summary

    loads = ctx.require_loads()
    outline = [[float(p[0]), float(p[1])] for p in foundation.outline or []]
    thickness = float(foundation.thickness)
    founding = ctx.founding_level(foundation)
    notes: list[str] = []
    ids = list(foundation.columns)
    if not ids:
        ids = [
            base_id
            for base_id, base in loads.bases.items()
            if isinstance(base.element, ColumnElement)
            and _inside_outline(
                float(base.element.position[0]), float(base.element.position[1]), outline
            )
        ]
    if not ids:
        raise Skip("no column stands on it")
    columns: list[RaftColumn] = []
    nodes: list[int] = []
    arms: list[float] = []
    for element_id in ids:
        element = ctx.elements.get(element_id)
        if not isinstance(element, ColumnElement):
            raise Skip(f"'{element_id}' is not a column of 6 BIM (walls on rafts: not yet)")
        base = loads.bases.get(element_id)
        if base is None:
            raise Skip(f"{element_id} stands on no support of the analysis model")
        c1, c2, note = ctx.column_sides(element, 0.0)
        if note:
            notes.append(f"{foundation.id}: {note}")
        x, y = float(element.position[0]), float(element.position[1])
        columns.append(RaftColumn(element_id, x, y, c1, c2))
        nodes.append(base.nodes[0][0])
        arms.append(max(float(element.bottom) - founding - thickness / 2, 0.0))
    concrete = ctx.concrete(foundation.material, foundation.id)
    reinforcement = foundation.reinforcement
    fy, es = 420.0, STEEL_E
    if reinforcement is not None:
        bars = ctx.rebar(reinforcement.material)
        fy, es = bars.steel.fy, bars.mechanical.E or STEEL_E
    fc = concrete.concrete.fc
    young = concrete.mechanical.E or 4700 * math.sqrt(fc)
    nu = concrete.mechanical.nu if concrete.mechanical.nu is not None else 0.2
    density = concrete.mechanical.density or 2400.0
    x_axis, y_axis = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    zero = np.zeros(6)
    per_case = {
        case: [
            column_action(reactions.get(node, zero), arm, x_axis, y_axis)
            for node, arm in zip(nodes, arms, strict=True)
        ]
        for case, reactions in loads.cases.items()
    }
    service = {name: combine(per_case, f) for name, f in loads.service}
    strength = {name: combine(per_case, f) for name, f in loads.strength}
    service_dead = {name: f.get("D", f.get("SD", 1.0)) for name, f in loads.service}

    # Soil: qa, the overburden, ks and Table 6.3.8's column.
    settings = ctx.settings.foundation
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    b, l_ = sorted((max(xs) - min(xs), max(ys) - min(ys)))
    area = abs(polygon_area(outline)) / 1e6  # m²
    centre = polygon_centroid(outline)
    bearing = ctx.soil.at(
        float(centre[0]), float(centre[1]), founding, b, l_, foundation.allowableBearing,
        foundation.id,
    )  # fmt: skip
    cover = max(0.0, settings.groundLevel - (founding + thickness))
    surcharge = settings.soilUnitWeight * cover / 1e3  # kPa
    overburden = settings.soilUnitWeight * max(0.0, settings.groundLevel - founding) / 1e3
    if bearing.overburden is not None:
        overburden = min(overburden, bearing.overburden)
    profiles, report, _ = profiles_of(ctx.soil_text)
    profile = None
    df = 0.0
    if profiles:
        profile, _ = nearest_profile(profiles, float(centre[0]), float(centre[1]))
        df = max((report.ground_level(profile.borehole) - founding) / 1e3, 0.0)
    gravity = [n for n in service if _gravity(n)] or list(service)
    weight = (density * 9.80665e-3 * thickness / 1e3 + surcharge) * area  # kN
    total = max((sum(float(f[0]) for f in service[n]) / 1e3 for n in gravity), default=0.0)
    q_net = (total + weight) / area - overburden
    springs = ctx.substructure.design.springsFrom
    if springs != "soilReport":
        ks = float(springs)
        ks_note = f"ks = {ks:.0f} kN/m³ (9 Substructure → Design)"
    else:
        if profile is None:
            raise Skip("ks needs the soil report's boreholes, or a value in 9 Substructure")
        found = raft_ks(profile, b / 1e3, l_ / 1e3, df, max(q_net, 1.0))
        if found["value"] is None:
            raise Skip(f"no ks from the soil report at {profile.id}: {found['note']}")
        ks = float(found["value"])
        ks_note = f"ks = {ks:.0f} kN/m³ at {profile.id}: {found['method']}"
    soil = soil_column(profile, df, b / 1e3) if profile is not None else "sand"
    spec = RaftSpec(
        id=foundation.id,
        outline=[(p[0], p[1]) for p in outline],
        thickness=thickness,
        E=young,
        fc=fc,
        fy=fy,
        reinforcement=reinforcement,
        columns=columns,
        ks=ks,
        nu=nu,
        es=es,
        mesh_size=ctx.substructure.design.raftMeshSize,
        unit_weight=density * 9.80665e-3,
        surcharge=surcharge,
        punching_reinforcement=getattr(foundation, "punchingReinforcement", None),
    )
    with tempfile.TemporaryDirectory(prefix="saengine-raft-") as folder:
        try:
            out = raft_design(
                spec, service, strength, folder, bearing.qa, overburden, soil, service_dead,
                loads.dead, gravity,
            )  # fmt: skip
        except RuntimeError as error:
            raise Skip(str(error)) from error
    raft = out["raft"]
    raft["ksNote"] = ks_note
    pressure_check = next((c for c in out["checks"] if c["name"] == "Contact pressure (net)"), None)
    pressure = None
    if pressure_check is not None:
        pressure = {
            "net": pressure_check["demand"],
            "qa": pressure_check["capacity"],
            "combination": pressure_check["combination"],
            "source": bearing.source,
        }
    sizes = {
        "thickness": thickness,
        "foundingLevel": founding,
        "area": round(area, 2),
        "outline": outline,
    }
    result = summary(
        foundation, out["checks"], [c.id for c in columns], sizes=sizes, pressure=pressure,
        raft=raft,
    )  # fmt: skip
    notes += [ks_note] + [f"{foundation.id}: {n}" for n in out["notes"]]
    if bearing.note:
        notes.append(f"{foundation.id}: {bearing.note}")
    return result, notes

"""SAEngine's derived analysis model (``08 FEM/model.osmodel``) as a solver-neutral description:
the input both independent solvers (PyNite, CalculiX) are built from.

    python ir.py --model "<project>/08 FEM/model.osmodel" --out ir.json

Runs with SAEngine's Python (it uses :func:`saengine.fem.derive.local_axes` for the element
axes and :mod:`saengine.fem.end_zones` for the rigid end zones). The description is plain JSON,
so the solver scripts need neither SAEngine nor OpenSees. Units: the model's (m, N, kg, s, Pa).

What it keeps, element by element (no remeshing, no lumping, no change of the mesh):

- nodes with their restraints and lumped masses (``mass`` [mx, my, mz, Ix, Iy, Iz]);
- frames (OpenSees ``elasticBeamColumn``) with their local axes, their rigid joint offsets
  (``-jntOffset``: the flexible length between the faces of the rigid zones) and the section of
  every analysis group (the cracked modifiers of the lateral cases and the modal case);
- pinned ends: SAEngine's ``ZeroLength`` twin nodes, tied to their main node in the listed
  global DOFs (the others released);
- shells (``ASDShellQ4``/``ASDShellT3``) with their section per group: a section whose
  bending modifier (``Ep_mod``) differs from its membrane one becomes two coincident layers that
  reproduce both stiffnesses (see :func:`layers`);
- rigid diaphragms (``rigidDiaphragm``: in-plane translations and the rotation about the
  normal follow the retained node);
- the load patterns of every static analysis (nodal loads; uniform frame loads as global
  vectors over the flexible length) and the modal analysis.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "saengine.crosscheck.ir/1"
#: The element types the solvers rebuild; anything else is listed in the notes.
FRAME, SHELL, TWIN = "ElasticBeamColumn", "Shell", "ZeroLength"


def case_code(name: str) -> str:
    """``"EX: Earthquake in X"`` -> ``"EX"`` (the analysis names Run All writes)."""
    return name.split(":")[0].strip()


def layers(e: float, h: float, membrane: float, bending: float) -> list[list[float]]:
    """Coincident shell layers ``[[E, h], ...]`` whose summed membrane stiffness is
    ``membrane · E·h`` and summed bending stiffness ``bending · E·h³`` (an isotropic shell
    element has one E for both, so a cracked section with a bending modifier other than its
    membrane one needs two). One layer when the modifiers are equal; else a full-depth layer
    E2 and a thin layer E1 (t1 = h/20) solving E1·t1 + E2·h = M, E1·t1³ + E2·h³ = B."""
    if abs(membrane - bending) <= 1e-9 * max(membrane, bending, 1.0):
        return [[e * membrane, h]]
    m, b = membrane * e * h, bending * e * h**3
    t1 = h / 20
    if b < m * t1 * t1:
        raise ValueError(f"bending modifier {bending:g} too small to layer (membrane {membrane:g})")
    e2 = (b - m * t1 * t1) / (h**3 - h * t1 * t1)
    e1 = (m - e2 * h) / t1
    if e1 < 0:
        raise ValueError(f"bending modifier {bending:g} above the membrane one {membrane:g}")
    return [[e2, h], [e1, t1]]


def _frame_section(s: dict[str, Any]) -> dict[str, float]:
    return {k: float(s[k]) for k in ("E", "G", "A", "Iy", "Iz", "J")}


def _shell_section(base: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    e0, h0 = float(base["E"]), float(base["h"])
    e, h = float(s.get("E", e0)), float(s.get("h", h0))
    membrane = e * h / (e0 * h0)
    bending = e * h**3 * float(s.get("Ep_mod", 1.0)) / (e0 * h0**3)
    return {
        "E": e0,
        "nu": float(base.get("nu", 0.2)),
        "h": h0,
        "membrane": membrane,
        "bending": bending,
        "layers": layers(e0, h0, membrane, bending),
    }


def build_ir(project: dict[str, Any], faces: dict[str, Any] | None = None) -> dict[str, Any]:
    """The solver-neutral description of an OpenSees Studio project derived by SAEngine."""
    from saengine.fem.derive import local_axes
    from saengine.fem.end_zones import element_offsets

    notes: list[str] = []
    nodes = {n["id"]: n for n in project["nodes"]}
    sections = {s["id"]: s for s in project["sections"]}
    materials = {m["id"]: m for m in project.get("materials", [])}
    used: set[int] = set()

    frames, shells, twins = [], [], []
    for e in project["elements"]:
        kind = e["type"]
        if kind == FRAME:
            i, j = e["nodes"]
            pi, pj = (np.asarray(nodes[n]["coords"], dtype=float) for n in (i, j))
            x, y, z = local_axes(pi, pj, e.get("vecxz"))
            offsets = e.get("joint_offsets")
            ri, rj = element_offsets(e)
            if e.get("rho"):
                notes.append(f"{e['name']}: element mass rho = {e['rho']:g} kg/m is not rebuilt")
            if e.get("geom_transf", "Linear") != "Linear":
                notes.append(f"{e['name']}: geomTransf {e['geom_transf']} analysed as Linear")
            frames.append(
                {
                    "id": e["id"],
                    "name": e["name"],
                    "i": i,
                    "j": j,
                    "section": e["section_id"],
                    "axes": {"x": x.tolist(), "y": y.tolist(), "z": z.tolist()},
                    "offsets": [float(v) for v in offsets] if offsets else None,
                    "rigid": [ri, rj],
                    "length": float(np.linalg.norm(pj - pi)),
                }
            )
            used.update((i, j))
        elif kind == SHELL:
            shells.append(
                {
                    "id": e["id"],
                    "name": e["name"],
                    "nodes": list(e["nodes"]),
                    "section": e["section_id"],
                    "formulation": e.get("formulation", "ASDShellQ4"),
                }
            )
            used.update(e["nodes"])
        elif kind == TWIN:
            stiff = [float(materials.get(m, {}).get("E", 0.0)) for m in e["material_ids"]]
            twins.append(
                {
                    "main": e["nodes"][0],
                    "twin": e["nodes"][1],
                    "dofs": list(e["dofs"]),
                    "penalty": min(stiff) if stiff else None,
                }
            )
            used.update(e["nodes"])
        else:
            notes.append(f"{e.get('name', e['id'])}: element type {kind} is not rebuilt")

    diaphragms = []
    for c in project.get("mp_constraints", []):
        if c.get("type") != "RigidDiaphragm":
            notes.append(f"constraint {c.get('type')} is not rebuilt")
            continue
        diaphragms.append(
            {
                "retained": c["retained_node"],
                "nodes": list(c["constrained_nodes"]),
                "perp": int(c.get("perp_dir", 3)),
            }
        )
        used.add(c["retained_node"])
        used.update(c["constrained_nodes"])

    loaded = {
        x["node_id"] for p in project["load_patterns"] for x in p.get("nodal_loads", []) or []
    }
    out_nodes = [
        {
            "id": n["id"],
            "xyz": [float(v) for v in n["coords"]],
            "restraint": [bool(r) for r in n["restraint"]],
            "mass": [float(v) for v in (n.get("mass") or [0.0] * 6)],
        }
        for n in project["nodes"]
        if n["id"] in used or n["id"] in loaded or any(n.get("mass") or [])
    ]

    # Analysis groups: the analyses that share their section overrides form one solver model.
    patterns = {p["id"]: p for p in project["load_patterns"]}
    frame_of = {f["id"]: f for f in frames}
    groups: dict[str, dict[str, Any]] = {}
    analyses = []
    cases: dict[str, dict[str, Any]] = {}
    for a in project["analyses"]:
        if a["type"] not in ("Static", "Modal"):
            if a["type"] not in ("ResponseSpectrum",):
                notes.append(f"{a['name']}: analysis type {a['type']} is not rebuilt")
            continue
        overrides = {o["id"]: o for o in a.get("section_overrides") or []}
        key = json.dumps(sorted(overrides), sort_keys=True) + json.dumps(
            [overrides[k] for k in sorted(overrides)], sort_keys=True
        )
        group = groups.get(key)
        if group is None:
            group = {
                "name": f"G{len(groups) + 1}",
                "frameSections": {},
                "shellSections": {},
            }
            for sid, s in sections.items():
                eff = {**s, **overrides.get(sid, {})}
                if s["type"] == "ElasticSection":
                    group["frameSections"][str(sid)] = _frame_section(eff)
                elif s["type"] == "ElasticMembranePlateSection":
                    group["shellSections"][str(sid)] = _shell_section(s, eff)
            groups[key] = group
        code = case_code(a["name"])
        if a["type"] == "Modal":
            analyses.append(
                {
                    "code": code,
                    "id": a["id"],
                    "type": "Modal",
                    "group": group["name"],
                    "modes": int(a.get("n_modes", 12)),
                }
            )
            continue
        pids = list(a.get("pattern_ids", []))
        nodal: dict[int, np.ndarray] = {}
        element: dict[int, np.ndarray] = {}
        for pid in pids:
            p = patterns[pid]
            if p.get("type") != "Plain":
                notes.append(f"{a['name']}: pattern {p['name']} ({p.get('type')}) is not rebuilt")
                continue
            for x in p.get("nodal_loads", []) or []:
                nodal.setdefault(x["node_id"], np.zeros(6))
                nodal[x["node_id"]] += np.asarray(x["forces"], dtype=float)
            for x in p.get("element_loads", []) or []:
                f = frame_of.get(x["element_id"])
                if f is None:
                    notes.append(f"{a['name']}: load on element {x['element_id']} not rebuilt")
                    continue
                ax = f["axes"]
                g = (
                    x.get("wx", 0.0) * np.asarray(ax["x"])
                    + x.get("wy", 0.0) * np.asarray(ax["y"])
                    + x.get("wz", 0.0) * np.asarray(ax["z"])
                )
                element.setdefault(x["element_id"], np.zeros(3))
                element[x["element_id"]] += g
        if not nodal and not element:
            continue  # an empty case (no roof live load on a model without a roof...)
        cases[code] = {
            "nodal": [[n, v.tolist()] for n, v in sorted(nodal.items())],
            "element": [[k, v.tolist()] for k, v in sorted(element.items())],
        }
        analyses.append({"code": code, "id": a["id"], "type": "Static", "group": group["name"]})

    return {
        "schema": SCHEMA,
        "name": project.get("meta", {}).get("name", ""),
        "units": "SI (m, N, kg, s, Pa)",
        "nodes": out_nodes,
        "frames": frames,
        "shells": shells,
        "twins": twins,
        "diaphragms": diaphragms,
        "groups": list(groups.values()),
        "analyses": analyses,
        "cases": cases,
        "faces": (faces or {}).get("elements") or {},
        "probes": default_probes(out_nodes, frames, shells, diaphragms, faces),
        "notes": notes,
    }


def default_probes(
    nodes: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    shells: list[dict[str, Any]],
    diaphragms: list[dict[str, Any]],
    faces: dict[str, Any] | None,
    count: int = 6,
) -> dict[str, Any]:
    """Where the solvers report: every diaphragm's retained node (storey drifts), the highest
    free node, a few frames (the ones with faces first, then the most loaded storey's columns
    and beams by position) and a few shells (spread over the model)."""
    masters = [d["retained"] for d in diaphragms]
    free = [n for n in nodes if not all(n["restraint"])]
    held = [np.asarray(n["xyz"]) for n in nodes if all(n["restraint"][:3])]
    base = np.mean(held, axis=0) if held else np.zeros(3)
    # the highest free node, the farthest from the supports among equals (a cantilever's tip)
    top = (
        max(
            free,
            key=lambda n: (
                round(n["xyz"][2], 6),
                float(np.linalg.norm(np.asarray(n["xyz"]) - base)),
            ),
        )["id"]
        if free
        else None
    )
    # and the free node nearest the middle of the free nodes (a plate's centre)
    centre = np.mean([n["xyz"] for n in free], axis=0) if free else None
    middle = (
        min(free, key=lambda n: float(np.linalg.norm(np.asarray(n["xyz"]) - centre)))["id"]
        if free and not diaphragms
        else None
    )
    with_faces = [int(k) for k in (faces or {}).get("elements", {})]
    vertical = [f for f in frames if abs(f["axes"]["x"][2]) > 0.9]
    horizontal = [f for f in frames if abs(f["axes"]["x"][2]) <= 0.1]
    lowest = sorted(vertical, key=lambda f: (min(_z(nodes, f)), f["id"]))
    beams = sorted(horizontal, key=lambda f: (_z(nodes, f)[0], f["id"]))
    picks: list[int] = []
    for group in (with_faces, [f["id"] for f in lowest], [f["id"] for f in beams]):
        for fid in group[: count // 2]:
            if fid not in picks:
                picks.append(fid)
    step = max(1, len(shells) // count)
    return {
        "nodes": sorted({*masters, *([top] if top else []), *([middle] if middle else [])}),
        "frames": picks[: 2 * count],
        "shells": [s["id"] for s in shells[::step][:count]],
    }


def _z(nodes: list[dict[str, Any]], f: dict[str, Any]) -> list[float]:
    at = {n["id"]: n["xyz"] for n in nodes}
    return [at[f["i"]][2], at[f["j"]][2]]


def load_model(model_path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from saengine.fem.end_zones import read_faces

    project = json.loads(model_path.read_text(encoding="utf-8"))
    return project, read_faces(model_path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    project, faces = load_model(args.model)
    ir = build_ir(project, faces)
    args.out.write_text(json.dumps(ir), encoding="utf-8")
    print(f"{len(ir['nodes'])} nodes, {len(ir['frames'])} frames, {len(ir['shells'])} shells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

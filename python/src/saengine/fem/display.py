"""Analysis results prepared for display in 3D: deflected shapes and force diagrams.

The workbench shows one result at a time: a static case, a load combination of the project
settings, or a mode of a modal case. For it this module computes, at stations along every
frame element:

- the displacement (global axes), interpolated with the beam's exact elastic shape: cubic
  Hermite functions of the end displacements and rotations, plus the deflection of a fixed-end
  beam under the element's uniform load (``w x² (L - x)² / 24EI``); axial displacement varies
  linearly;
- the section forces (local axes, tension positive) from the end forces at ``i`` and the
  element's uniform load, by equilibrium of the segment ``[0, x]``.

Element axes follow OpenSees Studio's runner (``vecxz`` chosen from the element axis), so the
local y and z directions sent with each element are the ones the forces refer to.
Units follow the model (SAEngine models: m, N, N·m).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem.derive import local_axes

STATIONS = 11
"""Points along each element (ends included)."""

_FRAME_TYPES = {"ElasticBeamColumn", "ForceBeamColumn", "DispBeamColumn", "BeamWithHinges"}


@dataclass
class _Element:
    id: int
    name: str
    i: int
    j: int
    length: float
    axes: np.ndarray  # rows x, y, z
    ei_y: float | None  # bending stiffness for deflection in local y (E·Iz)
    ei_z: float | None  # for deflection in local z (E·Iy)


def _elements(project: dict[str, Any]) -> list[_Element]:
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    sections = {s["id"]: s for s in project.get("sections", [])}
    result = []
    for e in project.get("elements", []):
        nodes = e.get("nodes", [])
        if e.get("type") not in _FRAME_TYPES or len(nodes) != 2:
            continue
        a, b = coords.get(nodes[0]), coords.get(nodes[1])
        if a is None or b is None or len(a) < 3 or np.linalg.norm(b - a) < 1e-12:
            continue
        section = sections.get(e.get("section_id"), {})
        modulus = section.get("E")
        result.append(
            _Element(
                id=e["id"],
                name=e.get("name") or str(e["id"]),
                i=nodes[0],
                j=nodes[1],
                length=float(np.linalg.norm(b - a)),
                axes=np.array(local_axes(a, b)),
                ei_y=modulus * section["Iz"] if modulus and section.get("Iz") else None,
                ei_z=modulus * section["Iy"] if modulus and section.get("Iy") else None,
            )
        )
    return result


def _hermite(xi: np.ndarray, length: float) -> np.ndarray:
    """Cubic shape functions (value i, slope i, value j, slope j), shape (4, n)."""
    return np.array(
        [
            1 - 3 * xi**2 + 2 * xi**3,
            length * (xi - 2 * xi**2 + xi**3),
            3 * xi**2 - 2 * xi**3,
            length * (-(xi**2) + xi**3),
        ]
    )


def element_displacements(
    element: _Element, u_i: np.ndarray, u_j: np.ndarray, load: np.ndarray
) -> np.ndarray:
    """Global displacement at each station, shape (STATIONS, 3).

    ``u_i``, ``u_j``: the end nodes' six global DOFs; ``load``: uniform local load (wx, wy, wz).
    """
    r = element.axes
    di, dj = r @ u_i[:3], r @ u_j[:3]
    ri, rj = r @ u_i[3:6], r @ u_j[3:6]
    xi = np.linspace(0.0, 1.0, STATIONS)
    x = xi * element.length
    shape = _hermite(xi, element.length)
    axial = di[0] + (dj[0] - di[0]) * xi
    # Deflection in local y turns about local z (dv/dx = θz); in local z about -y (dw/dx = -θy).
    v = shape.T @ np.array([di[1], ri[2], dj[1], rj[2]])
    w = shape.T @ np.array([di[2], -ri[1], dj[2], -rj[1]])
    fixed_end = x**2 * (element.length - x) ** 2 / 24.0
    if element.ei_y:
        v = v + load[1] * fixed_end / element.ei_y
    if element.ei_z:
        w = w + load[2] * fixed_end / element.ei_z
    return np.column_stack([axial, v, w]) @ r


def element_section_forces(
    element: _Element, end_forces: np.ndarray, load: np.ndarray
) -> np.ndarray:
    """Section forces N, Vy, Vz, T, My, Mz at each station, shape (STATIONS, 6).

    ``end_forces``: OpenSees ``localForce`` (12 values, forces of the nodes on the element);
    the forces are those of the part beyond the cut on the part ``[0, x]`` (tension positive).
    At ``x = L`` they equal the end forces at ``j``.
    """
    f, m = end_forces[0:3], end_forces[3:6]
    x = np.linspace(0.0, element.length, STATIONS)
    forces = -(f[None, :] + np.outer(x, load))
    moments = -(
        m[None, :]
        + np.column_stack([np.zeros_like(x), x * f[2], -x * f[1]])
        + np.column_stack([np.zeros_like(x), load[2] * x**2 / 2, -load[1] * x**2 / 2])
    )
    return np.column_stack([forces, moments])


def _case_loads(project: dict[str, Any], analysis_id: int) -> dict[int, np.ndarray]:
    """Uniform local loads (wx, wy, wz) per element of a static analysis's patterns."""
    analysis = next((a for a in project.get("analyses", []) if a.get("id") == analysis_id), None)
    patterns = {p["id"]: p for p in project.get("load_patterns", [])}
    loads: dict[int, np.ndarray] = {}
    for pattern_id in (analysis or {}).get("pattern_ids", []):
        for load in patterns.get(pattern_id, {}).get("element_loads", []):
            total = loads.setdefault(load["element_id"], np.zeros(3))
            total += [load.get("wx", 0.0), load.get("wy", 0.0), load.get("wz", 0.0)]
    return loads


def _last(group: dict[int, Any], key: int, width: int) -> np.ndarray:
    rows = group.get(key)
    if rows is None or not len(rows):
        return np.zeros(width)
    value = np.zeros(width)
    row = np.asarray(rows[-1], dtype=float)[:width]
    value[: len(row)] = row
    return value


def _manifest(out_dir: str | Path) -> dict[str, Any] | None:
    from opensees_studio.services.result_store import load_manifest

    try:
        return load_manifest(out_dir)
    except (OSError, ValueError):
        return None


def _load(project_path: str | Path) -> dict[str, Any]:
    import json

    return json.loads(Path(project_path).read_text(encoding="utf-8"))


#: Most time frames a time-history result offers to show or play.
MAX_FRAMES = 200


def _frames(results: Any) -> np.ndarray:
    """Recorded steps of a time history or a pushover shown as its frames (at most MAX_FRAMES;
    a pushover's first step is its state under the gravity loads)."""
    count = len(results.control_disp) if hasattr(results, "control_disp") else int(results.n_steps)
    if count <= 0:
        return np.zeros(0, dtype=int)
    return np.unique(np.round(np.linspace(0, count - 1, min(MAX_FRAMES, count))).astype(int))


def _peak_frame(results: Any, node_ids: list[int], frames: np.ndarray) -> int:
    """The frame (1-based) where the largest node translation is reached."""
    largest = np.zeros(len(frames))
    for node in node_ids:
        try:
            history = np.asarray(results.node_disp_history(node), dtype=float)
        except (KeyError, ValueError):
            continue
        if history.ndim == 2 and len(history):
            moved = np.linalg.norm(history[frames, :3] - history[0, :3], axis=1)
            largest = np.maximum(largest, moved)
    return int(np.argmax(largest)) + 1 if len(largest) else 1


def _code(case_name: str) -> str:
    return case_name.split(":")[0].strip()


def result_list(out_dir: str | Path, project_path: str | Path) -> dict[str, Any]:
    """The results that can be shown: ``{"results": [...], "stale": bool}``.

    Each result has a ``key`` (``case:<id>``, ``combination:<n>``), a ``label`` and a ``kind``
    (``static``, ``combination``, ``modal``, ``spectrum``, ``history``, ``pushover``); modal
    results list their ``modes`` with periods, time histories their ``frames`` (number, time)
    and the ``peak`` frame, where the structure moves most, and pushovers their ``frames``
    (number, control ``displacement``, base ``shear``: the capacity curve) and the ``peak``
    frame, at the largest base shear.
    ``stale`` is true when the model was changed after the run.
    """
    from opensees_studio.services.result_store import load_results
    from opensees_studio.services.results import (
        ModalResults,
        PushoverResults,
        ResponseSpectrumResults,
        StaticResults,
        TransientResults,
    )

    manifest = _manifest(out_dir)
    if manifest is None:
        return {"results": [], "stale": False}
    node_ids = [n["id"] for n in _load(project_path).get("nodes", [])]
    results: list[dict[str, Any]] = []
    static_codes = set()
    for entry in manifest["cases"]:
        loaded = load_results(entry, out_dir)
        key = f"case:{entry['case_id']}"
        if isinstance(loaded, StaticResults):
            static_codes.add(_code(entry["case_name"]))
            results.append({"key": key, "label": entry["case_name"], "kind": "static"})
        elif isinstance(loaded, ModalResults):
            modes = [
                {"number": n + 1, "period": float(p) if np.isfinite(p) else None}
                for n, p in enumerate(loaded.periods)
            ]
            results.append(
                {"key": key, "label": entry["case_name"], "kind": "modal", "modes": modes}
            )
        elif isinstance(loaded, ResponseSpectrumResults):
            results.append({"key": key, "label": entry["case_name"], "kind": "spectrum"})
        elif isinstance(loaded, PushoverResults):
            frames = _frames(loaded)
            disp, shear = np.asarray(loaded.control_disp), np.asarray(loaded.base_shear)
            results.append(
                {
                    "key": key,
                    "label": entry["case_name"],
                    "kind": "pushover",
                    "frames": [
                        {
                            "number": i + 1,
                            "displacement": round(float(disp[step]), 6),
                            "shear": round(float(shear[step]), 1),
                        }
                        for i, step in enumerate(frames)
                    ],
                    "peak": int(np.argmax(np.abs(shear[frames]))) + 1,
                }
            )
        elif isinstance(loaded, TransientResults):
            frames = _frames(loaded)
            if not len(frames):
                continue
            times = np.asarray(loaded.time(), dtype=float)
            results.append(
                {
                    "key": key,
                    "label": entry["case_name"],
                    "kind": "history",
                    "frames": [
                        {"number": i + 1, "time": round(float(times[step]), 4)}
                        for i, step in enumerate(frames)
                    ],
                    "peak": _peak_frame(loaded, node_ids, frames),
                }
            )
    project = _load(project_path)
    if project.get("meta", {}).get("author") == "SAEngine":
        from saengine.fem.combinations import combination_factors, settings_beside

        settings = settings_beside(project_path)
        for number, combination in enumerate(settings.combinations if settings else [], 1):
            if set(combination_factors(combination)) <= static_codes:
                results.append(
                    {
                        "key": f"combination:{number}",
                        "label": combination.name,
                        "kind": "combination",
                    }
                )
    manifest_file = Path(out_dir) / "manifest.json"
    stale = Path(project_path).stat().st_mtime > manifest_file.stat().st_mtime
    return {"results": results, "stale": stale}


def result_view(
    out_dir: str | Path, project_path: str | Path, key: str, mode: int = 1
) -> dict[str, Any]:
    """One result ready to draw.

    Returns ``{"label", "kind", "nodes", "reactions", "elements", "shells"}``: node
    displacements ``[id, ux, uy, uz, rx, ry, rz]``, support reactions
    ``[id, fx, fy, fz, mx, my, mz]``, per frame element ``{"id", "name", "y", "z",
    "displacements", "forces"}`` with the local axes and the station values, and per shell
    ``{"id", "name", "nodes", "forces"}`` with its section forces per unit length
    (N11, N22, N12, M11, M22, M12, Q13, Q23, local axes) averaged over its integration points.
    Mode shapes are scaled so their largest translation is 1 and have no forces or reactions.
    Response spectrum results are peak displacements (no signs, forces or reactions); a time
    history is shown at its frame ``mode`` (see :func:`result_list`), with forces but no
    reactions, and a pushover at its frame ``mode`` with forces and reactions.
    """
    from opensees_studio.services.result_store import load_results
    from opensees_studio.services.results import (
        ModalResults,
        PushoverResults,
        ResponseSpectrumResults,
        StaticResults,
        TransientResults,
    )

    manifest = _manifest(out_dir)
    if manifest is None:
        raise ValueError("there are no results; run the analysis first")
    project = _load(project_path)
    elements = _elements(project)
    # Supports: restrained nodes, but not the diaphragms' own nodes (held out of plane only).
    diaphragm_nodes = {c.get("retained_node") for c in project.get("mp_constraints", [])}
    restrained = {
        n["id"]
        for n in project.get("nodes", [])
        if any(n.get("restraint") or []) and n["id"] not in diaphragm_nodes
    }
    shells = [e for e in project.get("elements", []) if e.get("type") == "Shell"]
    entries = {f"case:{e['case_id']}": e for e in manifest["cases"]}

    # Each result is a factored sum of static cases: (factor, results, analysis id).
    parts: list[tuple[float, Any, int]] = []
    modal: dict[int, np.ndarray] | None = None
    spectrum: dict[int, np.ndarray] | None = None
    history: tuple[Any, int, int] | None = None  # results, recorded step, analysis id
    push: tuple[Any, int, int] | None = None  # pushover results, step, analysis id
    kind = "static" if key in entries else "combination"
    label = ""
    if key in entries:
        entry = entries[key]
        loaded = load_results(entry, out_dir)
        label = entry["case_name"]
        if isinstance(loaded, StaticResults):
            parts.append((1.0, loaded, int(entry["case_id"])))
        elif isinstance(loaded, ModalResults):
            shape = loaded.mode_shapes.get(mode)
            if shape is None:
                raise ValueError(f"{label} has no mode {mode}")
            modal = {nid: np.asarray(v, dtype=float) for nid, v in shape.items()}
            period = loaded.periods[mode - 1]
            label = f"{label}, mode {mode} (T = {period:.3f} s)"
            kind = "modal"
        elif isinstance(loaded, ResponseSpectrumResults):
            spectrum = {nid: np.asarray(v, dtype=float) for nid, v in loaded.combined_disp.items()}
            label = f"{label} (peak values)"
            kind = "spectrum"
        elif isinstance(loaded, TransientResults):
            frames = _frames(loaded)
            if not 1 <= mode <= len(frames):
                raise ValueError(f"{label} has no frame {mode}")
            step = int(frames[mode - 1])
            history = (loaded, step, int(entry["case_id"]))
            label = f"{label}, t = {float(loaded.time()[step]):.2f} s"
            kind = "history"
        elif isinstance(loaded, PushoverResults):
            frames = _frames(loaded)
            if not 1 <= mode <= len(frames):
                raise ValueError(f"{label} has no step {mode}")
            step = int(frames[mode - 1])
            push = (loaded, step, int(entry["case_id"]))
            label = f"{label}, step {step} of {len(loaded.control_disp) - 1}"
            kind = "pushover"
        else:
            raise ValueError(f"{label} cannot be shown in 3D")
    elif key.startswith("combination:"):
        from saengine.fem.combinations import combination_factors, settings_beside

        settings = settings_beside(project_path)
        number = int(key.split(":")[1])
        if settings is None or not 1 <= number <= len(settings.combinations):
            raise ValueError(f"unknown combination {number}")
        combination = settings.combinations[number - 1]
        label = combination.name
        by_code = {_code(e["case_name"]): e for e in manifest["cases"]}
        for code, factor in combination_factors(combination).items():
            entry = by_code.get(code)
            if entry is None:
                raise ValueError(f"{label}: case {code} has no results")
            parts.append((factor, load_results(entry, out_dir), int(entry["case_id"])))
    else:
        raise ValueError(f"unknown result {key}")

    node_ids = [n["id"] for n in project.get("nodes", [])]
    if modal is not None:
        peak = max((float(np.max(np.abs(v[:3]))) for v in modal.values()), default=0.0)
        scale = 1.0 / peak if peak > 0 else 1.0
        disp = {n: _pad(modal.get(n), 6) * scale for n in node_ids}
        loads: dict[int, np.ndarray] = {}
        forces: dict[int, np.ndarray] = {}
        reactions: dict[int, np.ndarray] = {}
        plate_forces: dict[int, np.ndarray] = {}
    elif spectrum is not None:
        disp = {n: _pad(spectrum.get(n), 6) for n in node_ids}
        loads, forces, reactions, plate_forces = {}, {}, {}, {}
    elif push is not None:
        results, step, analysis_id = push
        disp = {n: _row(results.node_disp, n, step, 6) for n in node_ids}
        forces = {e.id: _row(results.element_forces, e.id, step, 12) for e in elements}
        reactions = {n: _row(results.node_reaction, n, step, 6) for n in sorted(restrained)}
        plate_forces = {}
        # The gravity loads stay on the members while they are pushed.
        loads = {}
        analysis = next(a for a in project["analyses"] if a["id"] == analysis_id)
        for preload in analysis.get("preload_case_ids", []):
            for element_id, w in _case_loads(project, preload).items():
                loads[element_id] = loads.get(element_id, np.zeros(3)) + w
    elif history is not None:
        results, step, analysis_id = history
        disp = {n: _at(results.node_disp_history, n, step, 6) for n in node_ids}
        forces = {e.id: _at(results.element_force_history, e.id, step, 12) for e in elements}
        reactions, plate_forces = {}, {}
        # The dead loads applied before the shaking stay on the members.
        loads = {}
        analysis = next(a for a in project["analyses"] if a["id"] == analysis_id)
        for preload in analysis.get("preload_case_ids", []):
            for element_id, w in _case_loads(project, preload).items():
                loads[element_id] = loads.get(element_id, np.zeros(3)) + w
    else:
        disp = {n: sum(f * _last(r.node_disp, n, 6) for f, r, _ in parts) for n in node_ids}
        reactions = {
            n: sum(f * _last(r.node_reaction, n, 6) for f, r, _ in parts)
            for n in sorted(restrained)
        }
        forces = {
            e.id: sum(f * _last(r.element_forces, e.id, 12) for f, r, _ in parts) for e in elements
        }
        # Shells: the mean over the integration points (the value at the element's centre).
        plate_forces = {
            e["id"]: sum(f * _centre(r.shell_forces.get(e["id"])) for f, r, _ in parts)
            for e in shells
        }
        loads = {}
        for factor, results, analysis_id in parts:
            # A static case may apply its patterns in steps; scale by the factor reached.
            reached = float(results.load_factors[-1]) if len(results.load_factors) else 1.0
            for element_id, w in _case_loads(project, analysis_id).items():
                loads[element_id] = loads.get(element_id, np.zeros(3)) + factor * reached * w

    view_elements = []
    for e in elements:
        load = loads.get(e.id, np.zeros(3))
        item: dict[str, Any] = {
            "id": e.id,
            "name": e.name,
            "y": _round(e.axes[1], 6),
            "z": _round(e.axes[2], 6),
            "displacements": _round(element_displacements(e, disp[e.i], disp[e.j], load), 9),
        }
        if e.id in forces:
            item["forces"] = _round(element_section_forces(e, forces[e.id], load), 3)
        view_elements.append(item)
    return {
        "label": label,
        "kind": kind,
        "nodes": [[n, *_round(v, 9)] for n, v in disp.items()],
        "reactions": [[n, *_round(v, 3)] for n, v in reactions.items()],
        "elements": view_elements,
        "shells": [
            {
                "id": e["id"],
                "name": e.get("name") or str(e["id"]),
                "nodes": list(e["nodes"]),
                **({"forces": _round(plate_forces[e["id"]], 3)} if e["id"] in plate_forces else {}),
            }
            for e in shells
        ],
    }


def _row(group: dict[int, Any], item: int, step: int, width: int) -> np.ndarray:
    """One step of a node's or an element's recorded rows, padded to ``width``."""
    rows = group.get(item)
    if rows is None or step >= len(rows):
        return np.zeros(width)
    return _pad(np.asarray(rows[step], dtype=float), width)


def _at(history: Any, item: int, step: int, width: int) -> np.ndarray:
    """One recorded step of a node's or an element's history, padded to ``width``."""
    try:
        rows = np.asarray(history(item), dtype=float)
    except (KeyError, ValueError):
        return np.zeros(width)
    if rows.ndim != 2 or step >= len(rows):
        return np.zeros(width)
    return _pad(rows[step], width)


def _centre(rows: np.ndarray | None) -> np.ndarray:
    """Section forces of a shell (8 per integration point, last step) averaged over its points."""
    if rows is None or not len(rows):
        return np.zeros(8)
    values = np.asarray(rows[-1], dtype=float)
    return values.reshape(-1, 8).mean(axis=0)


def _pad(values: np.ndarray | None, width: int) -> np.ndarray:
    out = np.zeros(width)
    if values is not None:
        out[: min(width, len(values))] = values[:width]
    return out


def _round(values: np.ndarray, digits: int) -> Any:
    return np.round(np.asarray(values, dtype=float), digits).tolist()

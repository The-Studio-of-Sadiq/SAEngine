"""Storey response, modal participation and the other charts of an analysis run.

What an engineer reads off ETABS's "story response plots" and "modal" tables, computed from a
finished run (``<model>.results``) for every static case, load combination of the project
settings and response spectrum case:

- per level the largest displacement in X and Y (the value with the largest magnitude, and the
  mean over the level's nodes);
- per storey the largest inter-storey drift ratio in X and Y over the plan positions with a node
  on both its levels (:func:`saengine.fem.second_order.storey_drifts`);
- the storey forces, storey shears and overturning moments in X and Y: of a static case or a
  combination from its lateral nodal loads (SAEngine applies lateral loads at the storey levels
  only), each load given to the nearest level and scaled by the load factor the case reached; of
  a response spectrum case from the modal inertia forces ``m ω² u`` of every mode, combined over
  the modes with the case's own rule (SRSS or CQC) storey by storey, and scaled like the
  spectrum design (0.85·V/V_rs, BNBC 2020 Part 6 Sec 2.5.9.4) when it has been worked out;
  its drifts are the spectrum design's (the modal drifts combined, unscaled);
- the base reactions (sum over the supports) of the static cases and combinations.

Also the modal periods with the mass participation in X and Y (of the response spectrum cases,
else worked out from the masses), the design response spectrum with the modal periods on it, the
pushover capacity curves and the roof displacement of the time histories.

Values in the model's units (SAEngine: m, N, N·m); levels in m. Elastic drift ratios: BNBC 2020
Part 6 Sec 2.5.14.1 limits the design drift Cd·δ/I, which ``driftLimit`` gives with Cd and I.
"""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Iterator, Mapping
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

#: Level tolerance [m]: a node within it of a level is on the level.
LEVEL_TOLERANCE = 1e-3

_cache_lock = threading.Lock()
#: The results read of the last run: (results folder, manifest mtime) -> case id -> results.
_cache: dict[tuple[str, float], dict[int, Any]] = {}


def load_cached(entry: dict[str, Any], out_dir: str | Path) -> Any:
    """``load_results`` of a case, kept while the run (its manifest) stays the same: the charts,
    the tables and the member windows read the same cases one after the other."""
    from opensees_studio.services.result_store import load_results

    folder = Path(out_dir).resolve()
    try:
        stamp = (str(folder), (folder / "manifest.json").stat().st_mtime)
    except OSError:
        return load_results(entry, out_dir)
    with _cache_lock:
        cases = _cache.get(stamp)
        if cases is None:
            _cache.clear()  # one run at a time: the results are large
            cases = _cache[stamp] = {}
        found = cases.get(int(entry["case_id"]))
    if found is None:
        found = load_results(entry, out_dir)
        with _cache_lock:
            if stamp in _cache:
                _cache[stamp][int(entry["case_id"])] = found
    return found


def _code(case_name: str) -> str:
    return case_name.split(":")[0].strip()


def storey_levels(project: dict[str, Any], project_path: str | Path) -> list[dict[str, Any]]:
    """The levels ``[{"z", "name"}]`` bottom up: the base (lowest support) and the building's
    storeys (``06 BIM/bim.json``) above it, else the levels the analysis model shows
    (:func:`saengine.fem.second_order._levels`: diaphragm floors, base, roof)."""
    from saengine.fem import second_order

    coords = [n["coords"] for n in project.get("nodes", []) if len(n.get("coords", [])) >= 3]
    supports = [
        float(n["coords"][2]) for n in project.get("nodes", []) if any(n.get("restraint") or [])
    ]
    base = round(min(supports), 3) if supports else None
    named: list[dict[str, Any]] = []
    root = Path(project_path).resolve().parent.parent
    try:
        building = json.loads((root / "06 BIM/bim.json").read_text(encoding="utf-8"))
        if not (building.get("source") or {}).get("structure"):
            for story in building.get("stories", []):
                named.append(
                    {"z": round(float(story["elevation"]) / 1e3, 3), "name": story["name"]}
                )
    except (OSError, ValueError, KeyError, TypeError):
        named = []
    top = max((float(c[2]) for c in coords), default=None)
    if named and base is not None:
        # Storeys of the building at or above the base, below the top of the model.
        levels = [s for s in named if s["z"] > base + LEVEL_TOLERANCE]
        if top is not None:
            levels = [s for s in levels if s["z"] <= top + LEVEL_TOLERANCE]
        at_base = next((s["name"] for s in named if abs(s["z"] - base) <= LEVEL_TOLERANCE), None)
        return [{"z": base, "name": at_base or "Base"}, *sorted(levels, key=lambda s: s["z"])]
    zs = second_order._levels(project)
    return [{"z": z, "name": "Base" if k == 0 else f"Level {k}"} for k, z in enumerate(zs)]


def _nearest(levels: list[float], z: float) -> int:
    return int(np.argmin([abs(z - level) for level in levels]))


def _level_nodes(project: dict[str, Any], levels: list[float]) -> list[list[int]]:
    """The nodes on each level."""
    out: list[list[int]] = [[] for _ in levels]
    for node in project.get("nodes", []):
        c = node.get("coords", [])
        if len(c) < 3:
            continue
        for k, z in enumerate(levels):
            if abs(float(c[2]) - z) <= LEVEL_TOLERANCE:
                out[k].append(node["id"])
                break
    return out


def _pattern_loads(project: dict[str, Any], analysis: dict[str, Any] | None) -> list[tuple]:
    """``(z, fx, fy)`` of every nodal load of a static analysis's patterns."""
    from saengine.fem.display import case_pattern_ids

    coords = {n["id"]: n["coords"] for n in project.get("nodes", [])}
    patterns = {p["id"]: p for p in project.get("load_patterns", [])}
    loads = []
    for pid in case_pattern_ids(analysis):
        for load in patterns.get(pid, {}).get("nodal_loads", []):
            c = coords.get(load.get("node_id"))
            forces = load.get("forces") or []
            if c is None or len(c) < 3 or len(forces) < 2:
                continue
            if forces[0] or forces[1]:
                loads.append((float(c[2]), float(forces[0]), float(forces[1])))
    return loads


def _storey_loads(
    loads: list[tuple[float, float, float]], levels: list[float]
) -> tuple[np.ndarray, np.ndarray]:
    """Forces at each level in X and Y (each load at the nearest level)."""
    fx, fy = np.zeros(len(levels)), np.zeros(len(levels))
    if not loads or not levels:
        return fx, fy
    values = np.asarray(loads, dtype=float).reshape(-1, 3)
    # The nearest level of each load (the first of two as near, as argmin gives).
    k = np.abs(values[:, :1] - np.asarray(levels, dtype=float)[None, :]).argmin(axis=1)
    np.add.at(fx, k, values[:, 1])
    np.add.at(fy, k, values[:, 2])
    return fx, fy


def _shears(forces: np.ndarray) -> np.ndarray:
    """Storey shear of each storey (above level k-1, below k) from the level forces: the sum of
    the forces at and above its top level. Index k-1 for storey k."""
    return np.cumsum(forces[::-1])[::-1][1:]


def _overturning(forces: np.ndarray, levels: list[float]) -> np.ndarray:
    """Overturning moment at each level from the level forces above it."""
    z = np.asarray(levels)
    return np.array([float(np.sum(forces[k + 1 :] * (z[k + 1 :] - z[k]))) for k in range(len(z))])


class _Rows(Mapping[int, np.ndarray]):
    """Node id -> displacement row, over one array of every node's rows (a combination is a sum
    of the cases' arrays, not of a dictionary per node)."""

    def __init__(self, index: dict[int, int], values: np.ndarray) -> None:
        self.index, self.values = index, values

    def __getitem__(self, node: int) -> np.ndarray:
        return self.values[self.index[node]]

    def __contains__(self, node: object) -> bool:
        return node in self.index

    def __iter__(self) -> Iterator[int]:
        return iter(self.index)

    def __len__(self) -> int:
        return len(self.index)


def _displacements(
    disp: dict[int, np.ndarray], level_nodes: list[list[int]]
) -> list[dict[str, float | None]]:
    """Per level the largest (by magnitude, signed) and mean displacement in X and Y."""
    out = []
    for nodes in level_nodes:
        rows = np.array([disp[n][:2] for n in nodes if n in disp], dtype=float)
        if not len(rows):
            out.append({"maxX": None, "maxY": None, "avgX": None, "avgY": None})
            continue
        ix, iy = int(np.argmax(np.abs(rows[:, 0]))), int(np.argmax(np.abs(rows[:, 1])))
        out.append(
            {
                "maxX": float(rows[ix, 0]),
                "maxY": float(rows[iy, 1]),
                "avgX": float(rows[:, 0].mean()),
                "avgY": float(rows[:, 1].mean()),
            }
        )
    return out


def _drifts(
    project: dict[str, Any], disp: dict[int, np.ndarray], levels: list[float]
) -> tuple[list[float | None], list[float | None]]:
    """The largest drift ratio of each storey in X and Y (None where no plan position has a
    node on both its levels)."""
    from saengine.fem.second_order import storey_drifts

    out = []
    for axis in (0, 1):
        rows = {
            (round(r["from"], 3), round(r["to"], 3)): r["drift"]
            for r in storey_drifts(project, disp, axis, levels)
        }
        out.append([rows.get((round(a, 3), round(b, 3))) for a, b in pairwise(levels)])
    return out[0], out[1]


def _spectrum_drifts(
    project: dict[str, Any], entry: dict[str, Any], results: Any, levels: list[float]
) -> tuple[list[float | None], list[float | None]] | None:
    """The drift ratios of a response spectrum case in X and Y as the spectrum design works
    them out (:func:`saengine.fem.seismic_design.storey_drifts`): per storey the modal
    combination of the modal drifts, unscaled (BNBC 2020 Part 6 Sec 2.5.9.4, p. 635), the
    largest over the plan positions. None when the manifest has no modes (older runs)."""
    from saengine.fem.seismic_design import storey_drifts

    try:
        data = {
            "modes": [dict(m) for m in entry["modes"]],
            "peaks": [m.modal_peak_disp for m in results.modes],
            "damping": entry.get("damping_ratio"),
            "rule": str(entry.get("combination", "CQC")),
        }
    except (KeyError, TypeError, AttributeError):
        return None
    # The case's modes along both axes: the same data under each direction's key.
    rows = storey_drifts(project, {"X": data, "Y": data}, levels, 1.0, math.inf)
    ratio = {(r["direction"], r["bottom"], r["top"]): r["ratio"] for r in rows}
    out = [
        [ratio.get((axis, round(a, 3), round(b, 3))) for a, b in pairwise(levels)]
        for axis in ("X", "Y")
    ]
    return out[0], out[1]


def _spectrum_scale(out_dir: str | Path, project_path: str | Path) -> dict[str, Any] | None:
    """The spectrum design of these results (``seismic-design.json``), when it is of this run:
    ``{"scale": {"X", "Y"}, "drift": [rows], "clause"}``; None without one."""
    from saengine.fem import seismic_design as rs

    summary = rs.load_summary(out_dir)
    if not summary or not summary.get("available") or "run" not in summary:
        return None
    try:
        current = {rs._stamp(Path(out_dir), Path(project_path), t) for t in (False, True)}
    except OSError:
        return None
    if summary["run"].get("stamp") not in current:
        return None
    return {
        "scale": {"X": float(summary["scale"]["x"]), "Y": float(summary["scale"]["y"])},
        "drift": [
            {k: d.get(k) for k in ("direction", "bottom", "top", "ratio", "allowableRatio", "ok")}
            for d in summary.get("drift", [])
        ],
        "clause": summary["scale"].get("clause", rs.CLAUSES["scale"]),
    }


def _storeys(
    names: list[str],
    levels: list[float],
    displacements: list[dict[str, float | None]],
    drift_x: list[float | None],
    drift_y: list[float | None],
    fx: np.ndarray | None,
    fy: np.ndarray | None,
    shear_x: np.ndarray | None,
    shear_y: np.ndarray | None,
) -> list[dict[str, Any]]:
    """Rows by level, bottom up; the storey values (drift, shear) on the storey's top level."""
    over_x = _overturning(fx, levels) if fx is not None else None
    over_y = _overturning(fy, levels) if fy is not None else None

    def at(values: Any, k: int) -> float | None:
        return None if values is None or values[k] is None else float(values[k])

    rows = []
    for k, z in enumerate(levels):
        storey = k - 1  # the storey below this level
        rows.append(
            {
                "name": names[k],
                "z": z,
                "height": z - levels[k - 1] if k else None,
                **{f"disp{a}": displacements[k][f"max{a}"] for a in ("X", "Y")},
                **{f"avgDisp{a}": displacements[k][f"avg{a}"] for a in ("X", "Y")},
                "driftX": at(drift_x, storey) if k else None,
                "driftY": at(drift_y, storey) if k else None,
                "forceX": at(fx, k) if k else None,
                "forceY": at(fy, k) if k else None,
                "shearX": at(shear_x, storey) if k else None,
                "shearY": at(shear_y, storey) if k else None,
                "overturningX": at(over_x, k),
                "overturningY": at(over_y, k),
            }
        )
    return rows


def _spectrum_forces(
    results: Any,
    project: dict[str, Any],
    levels: list[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Storey forces and shears of a response spectrum case in X and Y: per mode the inertia
    forces ``m ω² u`` (u: the mode's peak displacement), gathered to the levels, then each
    level's force and each storey's shear combined over the modes with the case's rule."""
    from saengine.fem.seismic_design import combine

    mass = {
        n["id"]: np.asarray((n.get("mass") or [0, 0, 0])[:2], dtype=float) for n in project["nodes"]
    }
    coords = {n["id"]: n["coords"] for n in project["nodes"]}
    modes = [m for m in results.modes if m.angular_frequency > 0]
    if not modes:
        zero = np.zeros(len(levels))
        return zero, zero, zero[1:], zero[1:]
    level_forces = np.zeros((len(modes), 2, len(levels)))
    level_of = {
        nid: _nearest(levels, float(coords[nid][2]))
        for nid, m in mass.items()
        if m.any() and nid in coords
    }
    for i, mode in enumerate(modes):
        omega2 = mode.angular_frequency**2
        for nid, u in mode.modal_peak_disp.items():
            m = mass.get(nid)
            if m is None or not m.any() or nid not in coords:
                continue
            level_forces[i, :, level_of[nid]] += m * omega2 * np.asarray(u, dtype=float)[:2]
    shears = np.array([[_shears(level_forces[i, a]) for a in (0, 1)] for i in range(len(modes))])
    omegas = [m.angular_frequency for m in modes]
    rule, damping = results.combination, results.damping_ratio
    f = [combine(level_forces[:, a, :], omegas, damping, rule) for a in (0, 1)]
    v = [combine(shears[:, a, :], omegas, damping, rule) for a in (0, 1)]
    return f[0], f[1], v[0], v[1]


def _modal(
    project_path: str | Path, loaded: list[tuple[dict[str, Any], Any]], notes: list[str]
) -> dict[str, Any] | None:
    """The modal periods with the mass participation in X and Y (UX, UY, their running sums)."""
    from opensees_studio.services.results import ModalResults, ResponseSpectrumResults

    modal = next(((e, r) for e, r in loaded if isinstance(r, ModalResults)), None)
    if modal is None:
        return None
    entry, results = modal
    ratios: dict[int, dict[int, float]] = {}
    for _, r in loaded:
        if isinstance(r, ResponseSpectrumResults) and r.direction in (1, 2):
            ratios.setdefault(r.direction, {m.mode_number: m.mass_ratio for m in r.modes})
    missing = [d for d in (1, 2) if d not in ratios]
    if missing:
        try:
            from opensees_studio.services.persistence import load_project
            from opensees_studio.services.spectrum import mass_participation

            project = load_project(str(project_path))
            for d in missing:
                ratios[d] = {
                    m.mode_number: m.mass_ratio for m in mass_participation(project, results, d)
                }
        except Exception as error:  # noqa: BLE001 - participation is extra; the periods show
            notes.append(f"the mass participation could not be worked out: {error}")
    rows, sums = [], {1: 0.0, 2: 0.0}
    for index, period in enumerate(np.asarray(results.periods, dtype=float)):
        number = index + 1
        row: dict[str, Any] = {
            "number": number,
            "period": float(period) if np.isfinite(period) else None,
            "frequency": float(1 / period) if np.isfinite(period) and period > 0 else None,
        }
        for d, axis in ((1, "X"), (2, "Y")):
            share = ratios.get(d, {}).get(number)
            if share is not None:
                sums[d] += share
            row[f"u{axis}"] = share
            row[f"sumU{axis}"] = sums[d] if d in ratios else None
        rows.append(row)
    return {"case": entry["case_name"], "modes": rows, "required": 0.9}


def _spectrum_curve(project: dict[str, Any]) -> dict[str, Any] | None:
    """The design response spectrum the spectrum cases use (periods [s], Sa [model units])."""
    used = {a.get("spectrum_id") for a in project.get("analyses", []) if a.get("spectrum_id")}
    spectrum = next((s for s in project.get("spectra", []) if s.get("id") in used), None)
    if spectrum is None:
        return None
    return {
        "name": spectrum.get("name", ""),
        "periods": [float(p) for p in spectrum.get("periods", [])],
        "accelerations": [float(a) for a in spectrum.get("accelerations", [])],
        "damping": spectrum.get("damping_ratio"),
    }


def _drift_limit(project_path: str | Path) -> dict[str, Any] | None:
    """The allowable design drift ratio with Cd and I (the pack's drift table: the row of the
    project's systems; its clause from the pack)."""
    from saengine.fem.combinations import settings_beside
    from saengine.fem.seismic_design import CLAUSES, settings_drift_limit
    from saengine.library.settings import derived

    settings = settings_beside(project_path)
    if settings is None:
        return None
    try:
        values = derived(settings)
        limit = settings_drift_limit(settings)
    except (KeyError, AttributeError, ValueError):
        return None
    return {
        "ratio": limit["ratio"],
        "row": limit["label"],
        "cd": values.get("Cd"),
        "importance": values.get("seismicImportance"),
        "clause": CLAUSES["drift"],
    }


def _base_reactions(parts: list[tuple[float, Any]], restrained: set[int]) -> list[float]:
    from saengine.fem.display import _last

    total = np.zeros(6)
    for factor, results in parts:
        for node in restrained:
            total += factor * _last(results.node_reaction, node, 6)
    return [float(v) for v in total]


_responses: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
_responses_lock = threading.Lock()


def _response_stamp(out_dir: str | Path, project_path: str | Path) -> tuple[Any, ...]:
    """What the storey response is worked out from: the run, the model, the settings, the
    building (its storey names) and the response spectrum design of the run."""
    from saengine.fem.seismic_design import RS_FOLDER, SUMMARY_FILE

    model = Path(project_path).resolve()
    root = model.parent.parent
    files = (
        Path(out_dir) / "manifest.json",
        model,
        root / "02 Project Settings" / "project-settings.json",
        root / "06 BIM" / "bim.json",
        Path(out_dir) / RS_FOLDER / SUMMARY_FILE,
    )
    return tuple(f.stat().st_mtime_ns if f.exists() else None for f in files)


def story_response(out_dir: str | Path, project_path: str | Path) -> dict[str, Any]:
    """:func:`work_out_story_response`, kept while the run and what it is worked out from stay
    the same: the charts are opened again and again (a tall building's takes a minute)."""
    key = f"{Path(out_dir).resolve()}|{Path(project_path).resolve()}"
    try:
        stamp = _response_stamp(out_dir, project_path)
    except OSError:
        return work_out_story_response(out_dir, project_path)
    with _responses_lock:
        found = _responses.get(key)
    if found is not None and found[0] == stamp:
        return found[1]
    response = work_out_story_response(out_dir, project_path)
    with _responses_lock:
        _responses.clear()  # one run at a time
        _responses[key] = (stamp, response)
    return response


def work_out_story_response(out_dir: str | Path, project_path: str | Path) -> dict[str, Any]:
    """The storey response of every result of a run, and its modal and other curves:
    ``{"levels": [{"z", "name"}], "results": [{"key", "label", "kind", "storeys": [rows],
    "baseReaction": [Fx, Fy, Fz, Mx, My, Mz] | None, "forceScale"?}], "modal", "spectrum",
    "driftLimit", "spectrumDesign" (:func:`_spectrum_scale`), "pushover": [{"key", "label",
    "displacement", "shear"}], "histories": [{"key", "label", "node", "time", "displacement":
    [[ux, uy]]}], "serviceability" (:func:`_serviceability`), "notes"}``. Result keys are those of
    :func:`saengine.fem.display.result_list`."""
    from opensees_studio.services.results import (
        PushoverResults,
        ResponseSpectrumResults,
        StaticResults,
        TransientResults,
    )

    from saengine.fem.display import _last, _manifest

    manifest = _manifest(out_dir)
    if manifest is None:
        raise ValueError("there are no results; run the analysis first")
    project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    level_rows = storey_levels(project, project_path)
    levels = [lv["z"] for lv in level_rows]
    names = [lv["name"] for lv in level_rows]
    level_nodes = _level_nodes(project, levels)
    node_ids = [n["id"] for n in project.get("nodes", [])]
    analyses = {a["id"]: a for a in project.get("analyses", [])}
    diaphragm_nodes = {c.get("retained_node") for c in project.get("mp_constraints", [])}
    restrained = {
        n["id"]
        for n in project.get("nodes", [])
        if any(n.get("restraint") or []) and n["id"] not in diaphragm_nodes
    }
    notes: list[str] = []

    loaded: list[tuple[dict[str, Any], Any]] = []
    for entry in manifest["cases"]:
        try:
            loaded.append((entry, load_cached(entry, out_dir)))
        except Exception as error:  # noqa: BLE001 - one unreadable case must not hide the rest
            notes.append(f"{entry.get('case_name')}: the results could not be read ({error})")

    results: list[dict[str, Any]] = []
    # The response spectrum design of this run (read once, when there is a spectrum case).
    design: dict[str, Any] | None = None
    # Static cases: displacements, lateral loads (scaled by the load factor reached).
    static: dict[str, tuple[dict[str, Any], Any, list[tuple]]] = {}
    # Every node's last displacement row per static case, in the order of node_ids.
    arrays: dict[str, np.ndarray] = {}
    node_index = {n: k for k, n in enumerate(node_ids)}
    pushover, histories = [], []
    for entry, r in loaded:
        key = f"case:{entry['case_id']}"
        if isinstance(r, StaticResults):
            reached = float(r.load_factors[-1]) if len(r.load_factors) else 1.0
            loads = [
                (z, reached * x, reached * y)
                for z, x, y in _pattern_loads(project, analyses.get(int(entry["case_id"])))
            ]
            static[_code(entry["case_name"])] = (entry, r, loads)
            arrays[_code(entry["case_name"])] = np.array(
                [_last(r.node_disp, n, 6) for n in node_ids], dtype=float
            ).reshape(-1, 6)
            disp = _Rows(node_index, arrays[_code(entry["case_name"])])
            fx, fy = _storey_loads(loads, levels)
            dx, dy = _drifts(project, disp, levels)
            storeys = _storeys(
                names,
                levels,
                _displacements(disp, level_nodes),
                dx,
                dy,
                fx,
                fy,
                _shears(fx),
                _shears(fy),
            )
            results.append(
                {
                    "key": key,
                    "label": entry["case_name"],
                    "kind": "static",
                    "storeys": storeys,
                    "baseReaction": _base_reactions([(1.0, r)], restrained),
                }
            )
        elif isinstance(r, ResponseSpectrumResults):
            disp = {
                n: np.concatenate([np.asarray(v, dtype=float)[:3], np.zeros(3)])
                for n, v in r.combined_disp.items()
            }
            fx, fy, vx, vy = _spectrum_forces(r, project, levels)
            dx, dy = _spectrum_drifts(project, entry, r, levels) or _drifts(project, disp, levels)
            # The forces at the design level: times the spectrum design's scale of the case's
            # direction (Sec 2.5.9.4); the displacements and drifts stay unscaled.
            axis = {1: "X", 2: "Y"}.get(int(getattr(r, "direction", 0) or 0))
            if design is None:
                design = _spectrum_scale(out_dir, project_path) or {}
            factor = (design.get("scale") or {}).get(axis) if axis else None
            if factor is not None:
                fx, fy, vx, vy = (factor * v for v in (fx, fy, vx, vy))
            results.append(
                {
                    "key": key,
                    "label": entry["case_name"],
                    "kind": "spectrum",
                    "storeys": _storeys(
                        names, levels, _displacements(disp, level_nodes), dx, dy, fx, fy, vx, vy
                    ),
                    "baseReaction": None,
                    "forceScale": factor,
                }
            )
        elif isinstance(r, PushoverResults):
            pushover.append(
                {
                    "key": key,
                    "label": entry["case_name"],
                    "displacement": [float(v) for v in np.asarray(r.control_disp)],
                    "shear": [float(v) for v in np.asarray(r.base_shear)],
                }
            )
        elif isinstance(r, TransientResults):
            history = _roof_history(r, level_nodes[-1] if level_nodes else [])
            if history is not None:
                histories.append({"key": key, "label": entry["case_name"], **history})
    if any(r["kind"] == "spectrum" for r in results):
        scaled = any(r.get("forceScale") is not None for r in results)
        notes.append(
            "Response spectrum drifts combine the modal drifts storey by storey, as the "
            "spectrum design does; displacements and drifts are unscaled (BNBC 2020 Part 6 "
            "Sec 2.5.9.4, p. 635). "
            + (
                "Storey forces, shears and overturning are scaled to 0.85·V like the design."
                if scaled
                else "Storey forces, shears and overturning are unscaled: the response "
                "spectrum design has not been worked out for this run."
            )
        )

    # The load combinations of the project settings, factored sums of the static cases.
    if project.get("meta", {}).get("author") == "SAEngine":
        from saengine.fem.combinations import (
            combination_factors,
            combination_label,
            settings_beside,
        )

        settings = settings_beside(project_path)
        for number, combination in enumerate(settings.combinations if settings else [], 1):
            factors = combination_factors(combination, set(static))
            if not factors or not set(factors) <= set(static):
                continue
            # The factored sum, in the factors' order (the same sums as node by node).
            disp = _Rows(node_index, sum(f * arrays[c] for c, f in factors.items()))
            loads = [(z, f * x, f * y) for c, f in factors.items() for z, x, y in static[c][2]]
            fx, fy = _storey_loads(loads, levels)
            dx, dy = _drifts(project, disp, levels)
            results.append(
                {
                    "key": f"combination:{number}",
                    "label": combination_label(combination, set(static)),
                    "kind": "combination",
                    "storeys": _storeys(
                        names,
                        levels,
                        _displacements(disp, level_nodes),
                        dx,
                        dy,
                        fx,
                        fy,
                        _shears(fx),
                        _shears(fy),
                    ),
                    "baseReaction": _base_reactions(
                        [(f, static[c][1]) for c, f in factors.items()], restrained
                    ),
                }
            )
    # B9: the code pack's service wind combinations, the wind drift and sway limits and the
    # overturning stability of the whole building (saengine.fem.serviceability).
    serviceability = None
    try:
        serviceability = _serviceability(
            project, project_path, arrays, node_index, levels, names, level_nodes, static, results
        )
    except Exception as error:  # noqa: BLE001 - the charts show without the checks
        notes.append(f"the serviceability checks could not be worked out: {error}")
    return _finite(
        {
            "levels": level_rows,
            "results": results,
            "serviceability": serviceability,
            "modal": _modal(project_path, loaded, notes),
            "spectrum": _spectrum_curve(project),
            "driftLimit": _drift_limit(project_path),
            "spectrumDesign": design or None,
            "pushover": pushover,
            "histories": histories,
            "notes": notes,
        }
    )


def _serviceability(
    project: dict[str, Any],
    project_path: str | Path,
    arrays: dict[str, np.ndarray],
    node_index: dict[int, int],
    levels: list[float],
    names: list[str],
    level_nodes: list[list[int]],
    static: dict[str, tuple[dict[str, Any], Any, list[tuple]]],
    results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """B9: the serviceability checks of the code pack (:mod:`saengine.fem.serviceability`) on
    this run, and the pack's service wind combinations added to ``results`` (kind "service",
    with the drift and sway limits of their direction). None when the pack has no
    serviceability table."""
    from saengine.fem import serviceability as sv
    from saengine.fem.combinations import service_combinations, settings_beside
    from saengine.fem.display import _last

    found = sv.table()
    if found is None:
        return None
    settings = settings_beside(project_path)
    periods = sv.base_shear_periods(_derivation_summary(project, project_path))
    plain = sv.unreinforced_axes(settings) if settings and found.storeyDrift else {}
    wind = sv.wind_checks(project, arrays, node_index, levels, periods, plain, _Rows)
    # The service wind combinations as results (the charts draw their limits).
    wanted = {g.combination for g in (found.storeyDrift, found.sway) if g is not None}
    for row_id in sorted(wanted):
        for name, factors, _row in service_combinations(set(arrays), row_id):
            winds = [c for c in factors if c in sv.WIND_AXES]
            if len(winds) != 1 or any(c not in arrays for c in winds):
                continue
            used = {c: f for c, f in factors.items() if c in arrays}
            disp = _Rows(node_index, sum(f * arrays[c] for c, f in used.items()))
            loads = [(z, f * x, f * y) for c, f in used.items() for z, x, y in static[c][2]]
            fx, fy = _storey_loads(loads, levels)
            dx, dy = _drifts(project, disp, levels)
            direction = "XY"[sv.WIND_AXES[winds[0]]]
            drift_limit = (
                sv.storey_drift_limit(periods.get(direction), bool(plain.get(direction)))[0]
                if found.storeyDrift
                else None
            )
            results.append(
                {
                    "key": f"service:{name}",
                    "label": name,
                    "kind": "service",
                    "storeys": _storeys(
                        names,
                        levels,
                        _displacements(disp, level_nodes),
                        dx,
                        dy,
                        fx,
                        fy,
                        _shears(fx),
                        _shears(fy),
                    ),
                    "baseReaction": None,
                    "direction": direction,
                    "windDriftLimit": drift_limit,
                    "swayLimit": float(found.sway.ratio) if found.sway else None,
                }
            )
    # Overturning: each lateral case's level forces along its axis, the dead load's supports.
    level_forces = {}
    for case, axis in sv.LATERAL_CASES.items():
        if case in static:
            fx, fy = _storey_loads(static[case][2], levels)
            level_forces[case] = fx if axis == 0 else fy
    reactions = {
        case: (lambda node, r=static[case][1]: _last(r.node_reaction, node, 6))
        for case in ("D", "SD")
        if case in static
    }
    supports = sv.dead_supports(project, reactions) if reactions else []
    overturning = sv.overturning_checks(level_forces, levels, supports)
    return {"wind": wind, "overturning": overturning, "periods": periods}


def _derivation_summary(project: dict[str, Any], project_path: str | Path) -> dict[str, Any]:
    """The kept derivation's code values of this model (the periods the base shear used)."""
    try:
        from saengine.report.build import kept_derivation

        kept = kept_derivation(Path(project_path).resolve().parent.parent, project)
    except Exception:  # noqa: BLE001 - no periods: the stricter drift limit
        return {}
    return dict(kept.summary) if kept is not None else {}


def _roof_history(results: Any, roof: list[int]) -> dict[str, Any] | None:
    """The time history of the roof node that moves most: ``{"node", "time", "displacement"}``."""
    best: tuple[float, int, np.ndarray] | None = None
    for node in roof:
        try:
            history = np.asarray(results.node_disp_history(node), dtype=float)
        except (KeyError, ValueError):
            continue
        if history.ndim != 2 or not len(history):
            continue
        moved = history[:, :2] - history[0, :2]
        peak = float(np.max(np.hypot(moved[:, 0], moved[:, 1])))
        if best is None or peak > best[0]:
            best = (peak, node, moved)
    if best is None:
        return None
    times = np.asarray(results.time(), dtype=float)
    step = max(1, len(times) // 2000)  # at most about 2000 points
    return {
        "node": best[1],
        "time": [float(t) for t in times[::step]],
        "displacement": [[float(a), float(b)] for a, b in best[2][::step]],
    }


def _finite(value: Any) -> Any:
    """JSON has no inf or nan: they become None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    if isinstance(value, np.generic):
        return _finite(value.item())
    return value

"""On-disk transport for analysis results.

The analysis CLI (``python -m opensees_studio.run``) runs in a child
process and cannot hand result objects back to the GUI directly, so every
result kind is written to the output directory and rebuilt from it:

- ``StaticResults``, ``PushoverResults``, ``ModalResults`` and
  ``ResponseSpectrumResults`` go to ``case_<id>.results.h5`` (float64
  datasets, so the round trip is exact) plus scalar metadata in the
  manifest entry. Each ``{id: array}`` dict (node displacements, element
  forces, ...) is one group of four packed datasets (``ids``, ``offsets``,
  ``shapes``, ``values``), read in four reads however many nodes or
  elements the model has; files of the earlier layout, one dataset per id,
  are still read.
- ``TransientResults`` already keeps its history in ``case_<id>.h5``
  written by the runner; the manifest entry only records the scalars.

``manifest.json`` lists one entry per case with the result type, the
files, the completed steps, the early-stop flag and warnings.

Qt-free: safe to import from the CLI and from tests without a display.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import weakref
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)
from opensees_studio.services.spectrum import ModeContribution

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = 1

AnyResults = (
    StaticResults | PushoverResults | ModalResults | ResponseSpectrumResults | TransientResults
)


def temporary_results_dir() -> Path:
    """A fresh output folder in the system temp directory, for a run given none.

    Whoever creates it owns it and hands it to :func:`release_results_dir`
    once the results are loaded (or the run failed).
    """
    return Path(tempfile.mkdtemp(prefix="osstudio_"))


def release_results_dir(out_dir: Path, results: Any = None) -> None:
    """Remove a temporary output folder once nothing reads from it any more.

    ``TransientResults`` read their HDF5 file lazily, so the folder stays
    until that object is garbage collected (or the interpreter exits).
    Every other result kind is fully in memory, and without results (a
    failed or cancelled run) there is nothing to keep: the folder goes now.
    """
    if isinstance(results, TransientResults):
        weakref.finalize(results, shutil.rmtree, out_dir, ignore_errors=True)
    else:
        shutil.rmtree(out_dir, ignore_errors=True)


def results_file_name(case_id: int) -> str:
    """Name of the array file of a non-transient case."""
    return f"case_{case_id}.results.h5"


# ─────────────────────── helpers ───────────────────────
#: Most dimensions of a packed array (node and element results are 1 to 3 dimensional).
_PACKED_NDIM = 3


def _write_int_dict(group: Any, name: str, data: dict[int, np.ndarray]) -> None:
    """``data`` packed into ``group[name]``: the ids, each array's offset into ``values`` and its
    shape (``ndim`` then the dimensions), and all the values flattened in id order. One dataset
    per id made reading a 10-storey model's results take minutes (an HDF5 lookup per array)."""
    sub = group.create_group(name)
    sub.attrs["packed"] = 1
    ids = sorted(int(k) for k in data)
    arrays = [np.asarray(data[k], dtype=float) for k in ids]
    if any(a.ndim > _PACKED_NDIM for a in arrays):
        raise ValueError(f"{name}: arrays of more than {_PACKED_NDIM} dimensions cannot be packed")
    shapes = np.zeros((len(arrays), _PACKED_NDIM + 1), dtype=np.int64)
    for i, a in enumerate(arrays):
        shapes[i, 0] = a.ndim
        shapes[i, 1 : 1 + a.ndim] = a.shape
    sizes = np.array([a.size for a in arrays], dtype=np.int64)
    offsets = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int64)
    values = np.concatenate([a.ravel() for a in arrays]) if arrays else np.empty(0)
    sub.create_dataset("ids", data=np.asarray(ids, dtype=np.int64))
    sub.create_dataset("offsets", data=offsets)
    sub.create_dataset("shapes", data=shapes)
    sub.create_dataset("values", data=values)


def _read_int_dict(group: Any, name: str, keys: Any = None) -> dict[int, np.ndarray]:
    """The arrays of ``group[name]`` by id, in id order; only those of ``keys`` when given."""
    if name not in group:
        return {}
    sub = group[name]
    wanted = None if keys is None else {int(k) for k in keys}
    if not sub.attrs.get("packed"):
        # The earlier layout: one dataset per id.
        if wanted is not None:
            return {k: sub[str(k)][()] for k in sorted(wanted) if str(k) in sub}
        return {int(k): sub[k][()] for k in sorted(sub.keys(), key=int)}
    ids = sub["ids"][()]
    offsets = sub["offsets"][()]
    shapes = sub["shapes"][()]
    values = sub["values"][()]
    out: dict[int, np.ndarray] = {}
    # Plain ints taken once (hundreds of thousands of ids on tall buildings).
    bounds = offsets.tolist()
    for i, (key, row) in enumerate(zip(ids.tolist(), shapes.tolist(), strict=True)):
        if wanted is not None and key not in wanted:
            continue
        out[key] = values[bounds[i] : bounds[i + 1]].reshape(row[1 : 1 + row[0]])
    return out


def _mode_scalars(mode: ModeContribution) -> dict[str, Any]:
    scalars = asdict(mode)
    scalars.pop("modal_peak_disp", None)
    return {k: (float(v) if isinstance(v, float | np.floating) else v) for k, v in scalars.items()}


# ─────────────────────── write ───────────────────────
def write_results(results: AnyResults, out_dir: str | Path) -> dict[str, Any]:
    """Write ``results`` under ``out_dir`` and return its manifest entry.

    The entry carries everything ``load_results`` needs; file paths are
    relative to ``out_dir``.
    """
    import h5py

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "case_id": results.case_id,
        "case_name": results.case_name,
        "result_type": type(results).__name__,
        "files": [],
        "completed_steps": None,
        "early_stop": False,
        "warnings": [],
    }

    if isinstance(results, TransientResults):
        h5 = Path(results.h5_path)
        try:
            rel = h5.relative_to(out)
        except ValueError:
            rel = h5.resolve()
        entry["files"] = [rel.as_posix()]
        entry["completed_steps"] = results.n_steps
        entry["early_stop"] = results.early_stop
        entry["dt"] = results.dt
        entry["n_steps_requested"] = results.n_steps_requested
        if results.early_stop:
            entry["warnings"].append(f"Transient run stopped early: {results.steps_summary()}.")
        return entry

    name = results_file_name(results.case_id)
    entry["files"] = [name]
    with h5py.File(out / name, "w") as f:
        if isinstance(results, StaticResults):
            f.create_dataset("load_factors", data=results.load_factors)
            entry["completed_steps"] = results.n_steps
            _write_int_dict(f, "node_disp", results.node_disp)
            _write_int_dict(f, "node_reaction", results.node_reaction)
            _write_int_dict(f, "element_forces", results.element_forces)
            if results.shell_forces:
                _write_int_dict(f, "shell_forces", results.shell_forces)
            if results.stage_names:
                entry["stages"] = list(results.stage_names)

        elif isinstance(results, PushoverResults):
            entry["completed_steps"] = results.n_steps
            entry["n_steps_requested"] = results.n_steps_requested
            entry["early_stop"] = results.early_stop
            if results.early_stop:
                entry["warnings"].append(
                    f"Pushover stopped at step {results.n_steps} of "
                    f"{results.n_steps_requested} (control displacement "
                    f"{float(results.control_disp[-1]):.6g}): the analysis did not converge "
                    "further."
                )
            entry["control_node"] = results.control_node
            entry["control_dof"] = results.control_dof
            f.create_dataset("control_disp", data=np.asarray(results.control_disp, dtype=float))
            f.create_dataset("base_shear", data=np.asarray(results.base_shear, dtype=float))
            _write_int_dict(f, "node_disp", results.node_disp)
            _write_int_dict(f, "node_reaction", results.node_reaction)
            _write_int_dict(f, "element_end_fibers", results.element_end_fibers)
            _write_int_dict(f, "element_forces", results.element_forces)
        elif isinstance(results, ModalResults):
            entry["completed_steps"] = len(results.eigenvalues)
            entry["solver"] = results.solver
            entry["n_free_dof"] = int(results.n_free_dof)
            f.create_dataset("eigenvalues", data=np.asarray(results.eigenvalues, dtype=float))
            shapes = f.create_group("mode_shapes")
            for mode, vectors in results.mode_shapes.items():
                _write_int_dict(shapes, str(mode), vectors)
        elif isinstance(results, ResponseSpectrumResults):
            entry["completed_steps"] = len(results.modes)
            entry["direction"] = results.direction
            entry["combination"] = results.combination
            entry["solver"] = results.solver
            entry["damping_ratio"] = results.damping_ratio
            entry["warnings"] = list(results.warnings)
            entry["modes"] = [_mode_scalars(m) for m in results.modes]
            _write_int_dict(f, "combined_disp", results.combined_disp)
            modes = f.create_group("modes")
            for i, mode in enumerate(results.modes):
                _write_int_dict(modes, str(i), mode.modal_peak_disp)
        else:  # pragma: no cover - guarded by the AnyResults union
            raise TypeError(f"Unsupported result type: {type(results).__name__}")
    return entry


def write_manifest(
    out_dir: str | Path,
    entries: list[dict[str, Any]],
    project: str,
    name: str = MANIFEST_NAME,
) -> Path:
    """Write ``manifest.json`` (or ``name``) under ``out_dir``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": MANIFEST_SCHEMA, "project": project, "cases": entries}
    target = out / name
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


# ─────────────────────── read ───────────────────────
def load_manifest(out_dir: str | Path) -> dict[str, Any]:
    """Read ``manifest.json`` from ``out_dir``."""
    return json.loads((Path(out_dir) / MANIFEST_NAME).read_text(encoding="utf-8"))


def load_node_reactions(
    entry: dict[str, Any], out_dir: str | Path, nodes: Any = None
) -> dict[int, np.ndarray] | None:
    """The node reactions of the static case of a manifest ``entry`` (only those of ``nodes``
    when given), without reading its other results; None for any other kind of case."""
    import h5py

    if entry["result_type"] != "StaticResults":
        return None
    with h5py.File(Path(out_dir) / entry["files"][0], "r") as f:
        return _read_int_dict(f, "node_reaction", nodes)


def load_results(entry: dict[str, Any], out_dir: str | Path) -> AnyResults:
    """Rebuild the result object described by a manifest ``entry``."""
    import h5py

    out = Path(out_dir)
    kind = entry["result_type"]
    case_id = int(entry["case_id"])
    case_name = str(entry["case_name"])
    path = out / entry["files"][0]

    if kind == "TransientResults":
        return TransientResults(
            case_id=case_id,
            case_name=case_name,
            h5_path=path,
            n_steps=int(entry["completed_steps"]),
            dt=float(entry["dt"]),
            n_steps_requested=int(entry["n_steps_requested"]),
        )

    with h5py.File(path, "r") as f:
        if kind == "StaticResults":
            return StaticResults(
                case_id=case_id,
                case_name=case_name,
                n_steps=int(entry["completed_steps"]),
                load_factors=f["load_factors"][()] if "load_factors" in f else np.empty(0),
                node_disp=_read_int_dict(f, "node_disp"),
                node_reaction=_read_int_dict(f, "node_reaction"),
                element_forces=_read_int_dict(f, "element_forces"),
                shell_forces=_read_int_dict(f, "shell_forces"),
                stage_names=[str(name) for name in entry.get("stages", [])],
            )
        if kind == "PushoverResults":
            return PushoverResults(
                case_id=case_id,
                case_name=case_name,
                n_steps=int(entry["completed_steps"]),
                control_node=int(entry["control_node"]),
                control_dof=int(entry["control_dof"]),
                control_disp=f["control_disp"][()],
                base_shear=f["base_shear"][()],
                node_disp=_read_int_dict(f, "node_disp"),
                node_reaction=_read_int_dict(f, "node_reaction"),
                element_end_fibers=_read_int_dict(f, "element_end_fibers"),
                element_forces=_read_int_dict(f, "element_forces"),
                n_steps_requested=int(entry.get("n_steps_requested", 0)),
            )
        if kind == "ModalResults":
            shapes = f["mode_shapes"]
            return ModalResults(
                case_id=case_id,
                case_name=case_name,
                eigenvalues=f["eigenvalues"][()],
                mode_shapes={
                    int(m): _read_int_dict(shapes, m) for m in sorted(shapes.keys(), key=int)
                },
                solver=str(entry.get("solver", "")),
                n_free_dof=int(entry.get("n_free_dof", 0)),
            )
        if kind == "ResponseSpectrumResults":
            mode_groups = f["modes"]
            modes = [
                ModeContribution(
                    **scalars,
                    modal_peak_disp=_read_int_dict(mode_groups, str(i)),
                )
                for i, scalars in enumerate(entry["modes"])
            ]
            return ResponseSpectrumResults(
                case_id=case_id,
                case_name=case_name,
                direction=int(entry["direction"]),
                combination=str(entry["combination"]),
                combined_disp=_read_int_dict(f, "combined_disp"),
                modes=modes,
                solver=str(entry.get("solver", "")),
                damping_ratio=(
                    None if entry.get("damping_ratio") is None else float(entry["damping_ratio"])
                ),
                warnings=[str(w) for w in entry.get("warnings", [])],
            )
    raise ValueError(f"Unknown result type in manifest: {kind}")

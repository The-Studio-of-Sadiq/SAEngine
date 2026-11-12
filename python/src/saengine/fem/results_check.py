"""The plausibility check of an analysis run (W4B-1): Run All must not say "done" over results
no structure can have.

After the solver finishes, each static case (plain or staged) and each response spectrum case
is read back: a displacement that is not a number, or larger than :data:`HEIGHT_MULTIPLE` times
the building's height (a model with a free mechanism, a support left out of a staged model),
fails the analysis step with the case and the node named, so that the foundations, the design
checks and the report are not made from it.

Values in the model's units (m).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

#: A translation larger than this many times the building's height is not a result.
HEIGHT_MULTIPLE = 10.0
#: The least height [m] the bound is taken from (a one-level model).
MIN_HEIGHT = 1.0
#: The result kinds read (their translations: the first three columns).
_KINDS = {"StaticResults": "node_disp", "ResponseSpectrumResults": "combined_disp"}


def _node_names(model: dict[str, Any]) -> dict[int, str]:
    """Each node's name, else its position, for the message."""
    out = {}
    for n in model.get("nodes", []):
        xyz = ", ".join(f"{float(c):.2f}" for c in n.get("coords", [])[:3])
        out[int(n["id"])] = str(n.get("name") or "") or f"at {xyz} m"
    return out


def building_height(model: dict[str, Any]) -> float:
    """The height [m] of the analysis model: its highest node above its lowest."""
    z = [float(n["coords"][2]) for n in model.get("nodes", []) if len(n.get("coords", [])) > 2]
    return max(z) - min(z) if z else 0.0


def _worst(values: dict[int, np.ndarray]) -> tuple[float, int | None]:
    """The largest translation [m] of ``values`` (node -> array, translations first) and its
    node; ``inf`` at the first node with a value that is not a number."""
    worst, where = 0.0, None
    for node, rows in values.items():
        a = np.asarray(rows, dtype=float)
        if a.size == 0 or a.ndim == 0:
            continue
        t = a.reshape(-1, a.shape[-1])[:, :3]
        if not np.all(np.isfinite(t)):
            return math.inf, node
        m = float(np.abs(t).max()) if t.size else 0.0
        if m > worst:
            worst, where = m, node
    return worst, where


def implausible(model_path: str | Path, out_dir: str | Path | None = None) -> str | None:
    """The message naming the first case of the run of ``model_path`` (its results in
    ``out_dir``, by default ``<model>.results`` beside it) whose displacements are not numbers
    or exceed :data:`HEIGHT_MULTIPLE` × the building height; None when every case is plausible
    or there is nothing to read."""
    import h5py
    from opensees_studio.services.result_store import _read_int_dict, load_manifest

    model_path = Path(model_path)
    out = Path(out_dir) if out_dir is not None else model_path.with_suffix(".results")
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        manifest = load_manifest(out)
    except (OSError, ValueError):
        return None
    height = building_height(model)
    bound = HEIGHT_MULTIPLE * max(height, MIN_HEIGHT)
    names: dict[int, str] | None = None
    for entry in manifest.get("cases", []):
        key = _KINDS.get(str(entry.get("result_type")))
        files = entry.get("files") or []
        if key is None or not files:
            continue
        try:
            with h5py.File(out / files[0], "r") as f:
                values = _read_int_dict(f, key)
        except (OSError, KeyError, ValueError):
            continue
        worst, node = _worst(values)
        if worst <= bound:
            continue
        names = names if names is not None else _node_names(model)
        label = f"node {node}" + (
            f" ({names[node]})" if node is not None and names.get(node) else ""
        )
        size = "not a number" if not math.isfinite(worst) else f"{worst * 1e3:.3g} mm"
        return (
            f"The results are not plausible: case {entry.get('case_name')}, {label} moves "
            f"{size}, more than {HEIGHT_MULTIPLE:g} × the building height ({height:.2f} m). The "
            "model is not stable in this case (a part without supports or a free mechanism, in "
            "a staged case the supports built in no stage); the foundations, design checks and "
            "report are not made from it."
        )
    return None

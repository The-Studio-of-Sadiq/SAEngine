"""Fixed base against soil springs: the same analysis model with fixed column bases, run beside
the soil-spring model, and the two compared.

With Project Settings -> Analysis -> Column supports "Soil springs" the analysis model
(``08 FEM/model.osmodel``) stands on the springs of :mod:`saengine.fem.ssi`. :func:`compare`
derives the same model with fixed bases (``08 FEM/model-fixed.osmodel``), runs its static and
modal cases (``08 FEM/model-fixed.results``, in its own Python process, as the workbench runs
analyses) and compares the two runs: the modal periods (and their ratio T̃/T), the base shear of
the lateral static cases, and the storey drifts (:func:`saengine.fem.ssi.compare_responses`).
The result is also written to ``08 FEM/ssi-compare.json`` for the FEM editor.

The foundations of 9 Substructure are designed from the fixed-base run while the model is on
soil springs: the springs move the supports below the column bases, where the foundation design
does not read its loads (:func:`fixed_run`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FEM_FOLDER = "08 FEM"
MODEL = "model.osmodel"
FIXED_MODEL = "model-fixed.osmodel"
SSI_FILE = "ssi.json"
COMPARE_FILE = "ssi-compare.json"
#: Analysis types the fixed-base run needs: the static cases (the foundations' loads, drifts,
#: base shear) and the modes (periods).
_RUN_TYPES = ("Static", "Staged", "Modal")
_TIMEOUT = 1800  # s


def _folder(project_root: str | Path) -> Path:
    return Path(project_root) / FEM_FOLDER


def on_springs(project_root: str | Path) -> bool:
    """Whether the project's analysis model was derived on soil springs (it has ``ssi.json``)."""
    return (_folder(project_root) / SSI_FILE).is_file()


def fixed_run(project_root: str | Path) -> tuple[Path, Path] | str:
    """The fixed-base model and its results folder the foundation design reads while the model is
    on soil springs, or why there is none (not run yet, or older than the model)."""
    folder = _folder(project_root)
    model, fixed = folder / MODEL, folder / FIXED_MODEL
    results = fixed.with_suffix(".results")
    manifest = results / "manifest.json"
    if not fixed.is_file() or not manifest.is_file():
        return (
            "the analysis model is on soil springs: the foundations are designed from its "
            "fixed-base run, which has not run yet (8 FEM: Compare Fixed Base and Soil Springs; "
            "Run All runs it)"
        )
    if model.is_file() and model.stat().st_mtime > manifest.stat().st_mtime:
        return (
            "the fixed-base run is older than the analysis model: run Compare Fixed Base and "
            "Soil Springs again (Run All runs it)"
        )
    return fixed, results


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"{path.parent.name}/{path.name} could not be read: {error}") from error


def derive_fixed(project_root: str | Path) -> dict[str, Any]:
    """The fixed-base analysis model of the project (the derivation's result, see
    :func:`saengine.rpc.handlers.derive_fem`): the same inputs with the supports fixed."""
    from saengine.rpc.handlers import derive_fem

    root = Path(project_root)
    settings = json.loads(_read(root / "02 Project Settings/project-settings.json"))
    settings.setdefault("analysis", {})["supports"] = "fixed"
    return derive_fem(
        _read(root / "06 BIM/bim.json"),
        _read(root / "04 Objects/objects.json"),
        _read(root / "03 Materials/materials.json"),
        json.dumps(settings),
        str(_folder(root)),
    )


def run_cases(model: Path, out: Path, types: tuple[str, ...] = _RUN_TYPES) -> None:
    """Runs the analyses of ``model`` of the given types into ``out`` (OpenSees Studio's CLI, in
    its own process). Raises ``ValueError`` when the run fails."""
    # Absolute paths: the run's working folder is the model's own, where a relative path would
    # no longer point at the model.
    model, out = Path(model).resolve(), Path(out).resolve()
    project = json.loads(model.read_text(encoding="utf-8"))
    ids = [str(a["id"]) for a in project.get("analyses", []) if a.get("type") in types]
    if not ids:
        raise ValueError(f"{model.name} has no static or modal analyses")
    run = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model)]
        + ["--cases", *ids, "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        cwd=str(model.parent),
    )
    if run.returncode != 0:
        lines = [line for line in (run.stderr or run.stdout).splitlines() if line.strip()]
        raise ValueError(f"the fixed-base run failed: {lines[-1] if lines else run.returncode}")


def compare(project_root: str | Path) -> dict[str, Any]:
    """Derives and runs the fixed-base model and compares it with the soil-spring run of
    ``08 FEM/model.results``: ``{"periods", "baseShear", "drift", "storeyDrift", "springs",
    "shearModulusRatio", "fixedColumns", "notes", "computed"}`` (see
    :func:`saengine.fem.ssi.compare_responses`; base shear in kN, drift ratios, levels in m).
    Raises ``ValueError`` when the model is not on soil springs or has not run."""
    from saengine.fem import ssi
    from saengine.library.bim import BuildingModel

    root = Path(project_root)
    folder = _folder(root)
    if not on_springs(root):
        raise ValueError(
            "the analysis model is not on soil springs (Project Settings, Analysis model, "
            "Column supports); derive it again after choosing Soil springs"
        )
    results = folder / "model.results"
    if not (results / "manifest.json").is_file():
        raise ValueError("the soil-spring model has not run yet: run the analysis first")
    springs = json.loads(_read(folder / SSI_FILE))
    derived = derive_fixed(root)
    if "text" not in derived:
        raise ValueError("; ".join(derived.get("problems", [])) or "the fixed model failed")
    fixed = folder / FIXED_MODEL
    fixed.write_text(derived["text"], encoding="utf-8")
    fixed_out = fixed.with_suffix(".results")
    run_cases(fixed, fixed_out)

    building = BuildingModel.model_validate_json(_read(root / "06 BIM/bim.json"))
    levels = ssi.storey_levels(building)
    ssi_project = json.loads(_read(folder / MODEL))
    comparison = ssi.compare_responses(
        ssi.response_summary(json.loads(derived["text"]), fixed_out, levels),
        ssi.response_summary(ssi_project, results, levels),
    )
    result = {
        **comparison,
        "springs": springs.get("springs", []),
        "shearModulusRatio": springs.get("shearModulusRatio"),
        "fixedColumns": springs.get("fixedColumns", []),
        "notes": springs.get("notes", []),
        "computed": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (folder / COMPARE_FILE).write_text(
        json.dumps(result, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def comparison_stale(project_root: str | Path) -> bool:
    """Whether the comparison beside the model is out of date: older than the soil-spring model
    or its run (derived or run again since, outside Run All), or the model is no longer on soil
    springs. The FEM editor applies the same test (``femSsi.ts``)."""
    folder = _folder(project_root)
    try:
        computed = (folder / COMPARE_FILE).stat().st_mtime
    except OSError:
        return True
    if not on_springs(project_root):
        return True
    for source in (folder / MODEL, folder / "model.results" / "manifest.json"):
        try:
            if source.stat().st_mtime > computed:
                return True
        except OSError:
            return True
    return False


def read_comparison(project_root: str | Path) -> dict[str, Any] | None:
    """The last comparison written beside the model, if any, with ``stale`` set when it is out
    of date (:func:`comparison_stale`)."""
    try:
        data = json.loads((_folder(project_root) / COMPARE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {**data, "stale": comparison_stale(project_root)}

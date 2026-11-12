"""Design studies: parametric variants of a project, analysed and designed, compared (gap API-7).

A study (``12 Automation/studies/<id>/study.json``, schema ``saengine.study/1``) names parameters
and their values::

    {"schema": "saengine.study/1", "id": "grid-and-grade", "name": "Grid and concrete grade",
     "parameters": [{"kind": "gridSpacing", "axis": "both", "values": [0.9, 1.0, 1.1]},
                    {"kind": "concreteGrade", "values": ["C24.1", "C30"]}],
     "combine": "all", "steps": ["bim", "derive", "analysis", "design", "boq"]}

Parameter kinds (:func:`apply_parameter`; each edits the part files of a variant's copy):

- ``gridSpacing`` (factor): every grid spacing of the floor plan (``axis`` x, y or both) times the
  factor, measured from the first grid line; members follow their grid points;
- ``storeyHeight`` (mm): the height of every storey above the first suspended floor (with
  ``includeFirst`` the first storey's too); levels above move with it;
- ``concreteGrade`` (a material id of 03 Materials): the material of every object type whose
  material is concrete;
- ``sectionScale`` (factor): the dimensions of the rectangular and circular object types of
  ``kinds`` (default column and beam) times the factor, to the nearest 5 mm; other shapes are
  listed as unchanged;
- ``sectionFamily`` (an object type id per value, with ``kinds`` or ``types``): the members of
  those object types placed with the value's type instead;
- ``setValue`` (any JSON): one value of a part file (``file``, ``path``).

``combine``: ``all`` (every combination, at most :data:`MAX_VARIANTS`) or ``oneAtATime`` (each
parameter's values with the others at their first value). Each variant is a copy of the project
(``variants/<variant>/``, without results, versions and exports; a computed cache, never in the
project's versions or archives) on which Run All's ``steps`` run headlessly, one variant after
the other in a background thread (:func:`start`); the comparison (cost, steel, carbon, the
design's largest utilisation and failures, the largest storey drift) goes to ``results.json``
beside the study, for the table and chart of the Studies editor.

Versions: before the variants run, the project's current state is saved as a version
("Study <name>: base", when the project keeps versions), so the study is reproducible; applying a
variant (:func:`apply_variant`) copies its changed part files into the project and saves that as a
version ("Study <name>: variant <id>") so it can be compared with, or restored to, the base in
Versions like any other version.
"""

from __future__ import annotations

import itertools
import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from saengine.automation import FOLDER

SCHEMA = "saengine.study/1"
STUDIES_FOLDER = "studies"
RESULTS_FILE = "results.json"
MAX_VARIANTS = 32
DEFAULT_STEPS = ("bim", "derive", "analysis", "design", "boq")
#: The part files a variant may change (what :func:`apply_variant` copies back).
PART_FILES = (
    "02 Project Settings/project-settings.json",
    "03 Materials/materials.json",
    "04 Objects/objects.json",
    "05 Floor Plan/floor-plan.json",
    "05 Structural Model/structure.json",
)
#: Folders a variant's copy leaves out (results, versions, exports, the automation itself).
_SKIP = {".git", "11 Exports", FOLDER}


class StudyError(ValueError):
    """The study cannot be run or applied; the message says why."""


# ─────────────────────────────────────────── parameters ───────────────────────────────────────────


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise StudyError(f"{path.name} could not be read: {error}") from error


def _save(path: Path, value: Any) -> None:
    from saengine.pipeline.project import write_text

    write_text(path, json.dumps(value, indent="\t", ensure_ascii=False) + "\n")


def _round5(value: float) -> float:
    return max(5.0, round(value / 5.0) * 5.0)


def apply_parameter(root: Path, parameter: dict[str, Any], value: Any) -> list[str]:
    """Edits the project at ``root`` for ``parameter`` at ``value``; notes on what it did."""
    kind = parameter.get("kind")
    notes: list[str] = []
    plan_path = root / "05 Floor Plan" / "floor-plan.json"
    objects_path = root / "04 Objects" / "objects.json"
    if kind == "gridSpacing":
        factor = float(value)
        if not (0.2 <= factor <= 5):
            raise StudyError(f"gridSpacing: a factor from 0.2 to 5, not {value}")
        plan = _load(plan_path)
        axes = ("x", "y") if parameter.get("axis", "both") == "both" else (str(parameter["axis"]),)
        for axis in axes:
            lines = (plan.get("grids") or {}).get(axis) or []
            if lines:
                first = min(float(g["position"]) for g in lines)
                for g in lines:
                    g["position"] = round(first + (float(g["position"]) - first) * factor, 3)
        _save(plan_path, plan)
        notes.append(f"grid spacings ({'/'.join(axes)}) x {factor:g}")
    elif kind == "storeyHeight":
        height = float(value)
        if not (1000 <= height <= 20000):
            raise StudyError(f"storeyHeight: 1000 to 20000 mm, not {value}")
        plan = _load(plan_path)
        stories = sorted(plan.get("stories") or [], key=lambda s: float(s["elevation"]))
        first = 1 if parameter.get("includeFirst") else 2
        for k in range(first, len(stories)):
            stories[k]["elevation"] = round(float(stories[k - 1]["elevation"]) + height, 3)
        _save(plan_path, plan)
        notes.append(f"storey heights {height:g} mm from storey {first + 1}")
    elif kind == "concreteGrade":
        materials = _load(root / "03 Materials" / "materials.json")
        by_id = {m.get("id"): m for m in materials.get("materials") or []}
        if value not in by_id:
            raise StudyError(f"concreteGrade: no material {value!r} in 03 Materials")
        if by_id[value].get("category") != "concrete":
            raise StudyError(f"concreteGrade: {value!r} is not a concrete")
        objects = _load(objects_path)
        changed = 0
        for o in objects.get("objects") or []:
            if by_id.get(o.get("material"), {}).get("category") == "concrete":
                o["material"] = value
                changed += 1
        _save(objects_path, objects)
        notes.append(f"{changed} object type(s) in {value}")
    elif kind == "sectionScale":
        factor = float(value)
        if not (0.3 <= factor <= 3):
            raise StudyError(f"sectionScale: a factor from 0.3 to 3, not {value}")
        kinds = set(parameter.get("kinds") or ("column", "beam"))
        objects = _load(objects_path)
        for o in objects.get("objects") or []:
            if o.get("kind") not in kinds or not isinstance(o.get("profile"), dict):
                continue
            p = o["profile"]
            if p.get("shape") == "rectangle":
                p["xDim"], p["yDim"] = (
                    _round5(float(p["xDim"]) * factor),
                    _round5(float(p["yDim"]) * factor),
                )
            elif p.get("shape") == "circle":
                p["radius"] = _round5(float(p["radius"]) * 2 * factor) / 2
            else:
                notes.append(f"{o.get('id')}: {p.get('shape')} profiles are not scaled")
        _save(objects_path, objects)
        notes.append(f"sections of {', '.join(sorted(kinds))} x {factor:g}")
    elif kind == "sectionFamily":
        objects = _load(objects_path)
        ids = {o.get("id"): o for o in objects.get("objects") or []}
        if value not in ids:
            raise StudyError(f"sectionFamily: no object type {value!r} in 04 Objects")
        target_kind = ids[value].get("kind")
        types = set(
            parameter.get("types") or [o for o, d in ids.items() if d.get("kind") == target_kind]
        )
        plan = _load(plan_path)
        changed = 0
        for group in ("columns", "beams", "walls", "slabs"):
            for member in plan.get(group) or []:
                if member.get("type") in types and member.get("type") != value:
                    member["type"] = value
                    changed += 1
        _save(plan_path, plan)
        notes.append(f"{changed} member(s) of {', '.join(sorted(types))} as {value}")
    elif kind == "setValue":
        from saengine.automation.graph import project_file, set_path

        path = project_file(root, str(parameter.get("file")))
        document = _load(path)
        set_path(document, parameter.get("path"), value)
        _save(path, document)
        notes.append(f"{parameter.get('file')}: {parameter.get('path')} = {value!r}")
    else:
        raise StudyError(f"unknown parameter kind {kind!r}")
    return notes


def variants(study: dict[str, Any]) -> list[dict[str, Any]]:
    """The variants of a study: ``[{"id", "values": [one value per parameter]}]``."""
    parameters = study.get("parameters") or []
    if not parameters:
        raise StudyError("the study has no parameters")
    lists = []
    for p in parameters:
        values = p.get("values")
        if not isinstance(values, list) or not values:
            raise StudyError(f"parameter {p.get('kind')}: give its values")
        lists.append(values)
    if study.get("combine", "all") == "oneAtATime":
        combos = [tuple(v[0] for v in lists)]
        for k, values in enumerate(lists):
            for value in values[1:]:
                combo = [v[0] for v in lists]
                combo[k] = value
                combos.append(tuple(combo))
    else:
        combos = list(itertools.product(*lists))
    if len(combos) > MAX_VARIANTS:
        raise StudyError(
            f"{len(combos)} variants: at most {MAX_VARIANTS} (fewer values, or oneAtATime)"
        )
    return [{"id": f"V{k:02d}", "values": list(combo)} for k, combo in enumerate(combos, start=1)]


def _label(study: dict[str, Any], values: list[Any]) -> str:
    parts = []
    for p, v in zip(study.get("parameters") or [], values, strict=False):
        parts.append(f"{p.get('kind')}={v}")
    return ", ".join(parts)


# ─────────────────────────────────────────── metrics ───────────────────────────────────────────


def design_metrics(root: Path) -> dict[str, Any]:
    try:
        summary = json.loads(
            (root / "08 FEM" / "model.results" / "design-summary.json").read_text("utf-8")
        )
    except (OSError, ValueError):
        return {}
    return {
        k: summary.get(k) for k in ("checked", "passed", "failed", "maxUtilisation", "governing")
    }


def drift_metric(root: Path) -> float | None:
    results = root / "08 FEM" / "model.results"
    model = root / "08 FEM" / "model.osmodel"
    if not (results / "manifest.json").is_file() or not model.is_file():
        return None
    try:
        from saengine.exporters.web_viewer import max_drift
        from saengine.rpc.handlers import story_response

        return max_drift(story_response(str(results), str(model)))
    except Exception:  # noqa: BLE001 - a missing metric, never a failed study
        return None


def boq_metrics(root: Path) -> dict[str, Any]:
    from saengine.pipeline.project import read_text

    boq = read_text(root / "10 BOQ" / "boq.json")
    if not boq:
        return {}
    from saengine.boq.costing import cost_texts

    answer = cost_texts(
        boq,
        read_text(root / "10 BOQ" / "rates.json"),
        read_text(root / "10 BOQ" / "carbon-factors.json"),
    )
    costing = answer.get("costing")
    if not isinstance(costing, dict):
        return {"problems": answer.get("problems")}
    steel = concrete = 0.0
    for line in costing.get("carbon") or []:
        name = f"{line.get('id', '')} {line.get('material', '')}".lower()
        mass = float(line.get("mass") or 0.0)
        if "steel" in name or "rebar" in name or "reinforc" in name:
            steel += mass
        elif "concrete" in name or "cement" in name:
            concrete += mass
    return {
        "cost": costing.get("total"),
        "currency": costing.get("currency"),
        "carbonKg": costing.get("carbonTotal"),
        "steelKg": round(steel, 1),
        "concreteKg": round(concrete, 1),
        "sampleRates": answer.get("sampleRates"),
    }


# ─────────────────────────────────────────── running ───────────────────────────────────────────


def studies_folder(root: Path) -> Path:
    return root / FOLDER / STUDIES_FOLDER


def study_folder(root: Path, study_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,60}", study_id or ""):
        raise StudyError("a study id of letters, digits, '.', '_' and '-'")
    return studies_folder(root) / study_id


def _copy_project(root: Path, target: Path) -> None:
    from saengine.project.archive import is_computed

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for path in root.iterdir():
        if path.name in _SKIP:
            continue
        dest = target / path.name
        if path.is_dir():
            shutil.copytree(
                path,
                dest,
                ignore=lambda folder, names, base=root: [
                    n
                    for n in names
                    if is_computed(
                        (Path(folder) / n).relative_to(base).as_posix(), (Path(folder) / n).is_dir()
                    )
                ],
            )
        elif path.is_file():
            shutil.copy2(path, dest)


_RUNS: dict[str, dict[str, Any]] = {}
_RUNS_LOCK = threading.Lock()


def _key(root: Path, study_id: str) -> str:
    return f"{root.resolve()}|{study_id}"


def run_study(
    root: Path, study: dict[str, Any], progress: Any = None, cancelled: Any = None
) -> dict[str, Any]:
    """Runs every variant of ``study`` (see the module notes); the comparison (also written to
    ``results.json``)."""
    from saengine.pipeline.run_all import normalise_steps, run_all

    root = Path(root)
    folder = study_folder(root, str(study.get("id")))
    steps = normalise_steps(study.get("steps") or DEFAULT_STEPS)
    rows: list[dict[str, Any]] = []
    base_version, rows_note = save_version(
        root, f"Study {study.get('name') or study.get('id')}: base"
    )
    all_variants = variants(study)
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "study": study.get("id"),
        "name": study.get("name"),
        "baseVersion": base_version,
        "steps": steps,
        "started": time.time(),
        "rows": rows,
        "notes": [rows_note] if rows_note else [],
    }
    for k, variant in enumerate(all_variants, start=1):
        if cancelled is not None and cancelled():
            result["notes"].append("cancelled")
            break
        if progress is not None:
            progress(k, len(all_variants), variant["id"])
        row: dict[str, Any] = {
            "id": variant["id"],
            "label": _label(study, variant["values"]),
            "values": variant["values"],
        }
        target = folder / "variants" / variant["id"]
        try:
            _copy_project(root, target)
            notes: list[str] = []
            for parameter, value in zip(study["parameters"], variant["values"], strict=True):
                notes += apply_parameter(target, parameter, value)
            row["notes"] = notes
            run = run_all(target, steps=steps)
            row["ok"] = run.ok
            row["summary"] = run.summary
            row["failedSteps"] = [s.id for s in run.failed]
            row["design"] = design_metrics(target)
            row["drift"] = drift_metric(target)
            row["boq"] = boq_metrics(target)
        except (StudyError, OSError, ValueError) as error:
            row["ok"] = False
            row["error"] = str(error)
        rows.append(row)
        _save(folder / RESULTS_FILE, result)
    result["finished"] = time.time()
    _save(folder / RESULTS_FILE, result)
    return result


def start(root: str | Path, study: dict[str, Any]) -> dict[str, Any]:
    """Saves the study and runs it in a background thread: ``{"started", "variants"}``."""
    root = Path(root)
    problems = check_study(study)
    if problems:
        raise StudyError("; ".join(problems))
    folder = study_folder(root, str(study["id"]))
    folder.mkdir(parents=True, exist_ok=True)
    _save(folder / "study.json", study)
    key = _key(root, str(study["id"]))
    with _RUNS_LOCK:
        if _RUNS.get(key, {}).get("state") == "running":
            raise StudyError("the study is running already")
        state: dict[str, Any] = {
            "state": "running",
            "index": 0,
            "count": len(variants(study)),
            "variant": None,
            "cancel": False,
        }
        _RUNS[key] = state

    def progress(index: int, count: int, variant: str) -> None:
        state.update(index=index, count=count, variant=variant)

    def work() -> None:
        try:
            run_study(root, study, progress, lambda: state["cancel"])
            state["state"] = "cancelled" if state["cancel"] else "done"
        except Exception as error:  # noqa: BLE001 - reported to the editor
            state["state"], state["error"] = "failed", str(error)

    threading.Thread(target=work, name=f"study-{study['id']}", daemon=True).start()
    return {"started": True, "variants": state["count"]}


def status(root: str | Path, study_id: str) -> dict[str, Any]:
    root = Path(root)
    with _RUNS_LOCK:
        state = dict(_RUNS.get(_key(root, study_id)) or {"state": "idle"})
    state.pop("cancel", None)
    try:
        state["results"] = json.loads(
            (study_folder(root, study_id) / RESULTS_FILE).read_text("utf-8")
        )
    except (OSError, ValueError):
        state["results"] = None
    return state


def cancel(root: str | Path, study_id: str) -> dict[str, Any]:
    with _RUNS_LOCK:
        state = _RUNS.get(_key(Path(root), study_id))
        if state is not None:
            state["cancel"] = True
    return status(root, study_id)


def check_study(study: dict[str, Any]) -> list[str]:
    problems = []
    if study.get("schema") != SCHEMA:
        problems.append(f"schema: {SCHEMA} expected")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,60}", str(study.get("id") or "")):
        problems.append("id: letters, digits, '.', '_' and '-'")
    kinds = {
        "gridSpacing",
        "storeyHeight",
        "concreteGrade",
        "sectionScale",
        "sectionFamily",
        "setValue",
    }
    for p in study.get("parameters") or []:
        if p.get("kind") not in kinds:
            problems.append(f"unknown parameter kind {p.get('kind')!r}")
    if not problems:
        try:
            variants(study)
        except StudyError as error:
            problems.append(str(error))
    return problems


def list_studies(root: str | Path) -> dict[str, Any]:
    folder = studies_folder(Path(root))
    studies = []
    for path in sorted(folder.glob("*/study.json")) if folder.is_dir() else []:
        try:
            study = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        studies.append(
            {
                "id": study.get("id"),
                "name": study.get("name"),
                "path": str(path),
                "hasResults": (path.parent / RESULTS_FILE).is_file(),
            }
        )
    return {"studies": studies}


def apply_variant(
    root: str | Path, study_id: str, variant_id: str, author: str | None = None
) -> dict[str, Any]:
    """Copies a variant's changed part files into the project and saves a version of it."""
    root = Path(root)
    source = study_folder(root, study_id) / "variants" / variant_id
    if not re.fullmatch(r"V\d{2}", variant_id) or not source.is_dir():
        raise StudyError(f"no variant {variant_id} of study {study_id} (run the study first)")
    copied = []
    for rel in PART_FILES:
        src, dst = source / rel, root / rel
        if src.is_file() and (not dst.is_file() or src.read_bytes() != dst.read_bytes()):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            copied.append(rel)
    version, note = save_version(root, f"Study {study_id}: variant {variant_id}", author)
    return {"copied": copied, "version": version, "note": note}


def save_version(
    root: Path, message: str, author: str | None = None
) -> tuple[str | None, str | None]:
    """Saves a version when the project keeps versions already (a study never starts a history
    the engineer did not ask for): (the version id, or the last one when nothing changed; a note
    when none was saved)."""
    from saengine.project import versions

    try:
        state = versions.status(root)
        if not state.get("initialized"):
            return None, "The project keeps no versions: no version saved."
        saved = versions.save(root, message, author=author)
        return (saved.get("version") or {}).get("id"), None
    except versions.VersionsError as error:
        if error.code == "nothingToSave":
            head = versions.status(root).get("head") or {}
            return head.get("id"), None
        return None, f"No version saved: {error}"


__all__ = [
    "MAX_VARIANTS",
    "SCHEMA",
    "StudyError",
    "apply_parameter",
    "apply_variant",
    "boq_metrics",
    "cancel",
    "check_study",
    "design_metrics",
    "drift_metric",
    "list_studies",
    "run_study",
    "start",
    "status",
    "variants",
]

"""IDS (Information Delivery Specification, buildingSMART) checks of the coordination's models.

Each IDS file of the coordination is checked with IfcTester (IfcOpenShell's IDS checker,
LGPL-3.0) against SAEngine's own model (the structure and the architecture as exported to IFC),
the MEP IFC models and the other coordination models. Every specification that fails on a model
becomes one issue (source ``ids``, keyed ``ids:<file>:<specification>:<model>``) listing the
failing elements, so the issue workflow of :mod:`saengine.mep.coordination` resolves it once
the model passes.

IfcTester is optional: without it the check says it is not installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from saengine.library.mep import MEP_FILE, MepModel, parse
from saengine.mep import clash
from saengine.mep.coordination import coordination_of, merge_found

#: Failing elements listed per specification and model (the rest are counted).
MAX_FAILURES = 200


def _ifctester() -> Any:
    try:
        import ifctester.ids  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError(
            "IDS checks need IfcTester, which is not installed (pip install ifctester)"
        ) from error
    return ifctester.ids


def available() -> bool:
    try:
        _ifctester()
    except RuntimeError:
        return False
    return True


def check_model(ids_path: Path, model: Any) -> list[dict[str, Any]]:
    """The specifications of the IDS at ``ids_path`` checked on the IFC ``model``:
    ``[{"name", "description", "status" (bool), "applicable", "failed", "failures":
    [{"globalId", "name", "class", "reason"}]}]``."""
    ids_module = _ifctester()
    specs = ids_module.open(str(ids_path))
    specs.validate(model)
    results = []
    for spec in specs.specifications:
        failures: dict[str, dict[str, Any]] = {}
        for requirement in getattr(spec, "requirements", []) or []:
            for failure in getattr(requirement, "failures", []) or []:
                element = failure.get("element") if isinstance(failure, dict) else None
                guid = getattr(element, "GlobalId", None)
                if not guid or guid in failures:
                    continue
                failures[guid] = {
                    "globalId": guid,
                    "name": getattr(element, "Name", None) or "",
                    "class": element.is_a() if element is not None else "",
                    "reason": str(failure.get("reason") or "")[:300],
                }
        applicable = getattr(spec, "applicable_entities", None) or []
        results.append(
            {
                "name": spec.name or "",
                "description": getattr(spec, "description", None) or "",
                "status": bool(getattr(spec, "status", not failures)),
                "applicable": len(applicable),
                "failed": len(failures),
                "failures": list(failures.values()),
            }
        )
    return results


def _models(project_root: Path, mep: MepModel) -> tuple[list[tuple[str, Any]], list[str]]:
    import ifcopenshell

    notes: list[str] = []
    models: list[tuple[str, Any]] = []
    try:
        own, *_ = clash.structural_ifc(project_root, architecture=True)
        models.append(("SAEngine model", own))
    except ValueError as error:
        notes.append(f"the building model could not be exported: {error}")
    opened, more = clash.open_models(project_root, mep)
    notes += more
    models += [(path, model) for path, _, model in opened]
    for entry in coordination_of(mep).models:
        full = Path(entry.path) if Path(entry.path).is_absolute() else project_root / entry.path
        try:
            models.append((entry.path, ifcopenshell.open(str(full))))
        except Exception as error:  # noqa: BLE001 - IfcOpenShell raises several kinds
            notes.append(f"{entry.path}: could not be read ({error})")
    return models, notes


def check_ids(project_root: str | Path, mep_text: str | None = None) -> dict[str, Any]:
    """Checks every model of the project against the coordination's IDS files and merges the
    failures into its issues: ``{"coordination", "results": [{"ids", "model",
    "specifications"}], "counts", "notes"}``. Raises ``RuntimeError`` without IfcTester and
    ``ValueError`` for an invalid MEP file."""
    _ifctester()
    root = Path(project_root)
    if mep_text is None:
        try:
            mep_text = (root / MEP_FILE).read_text(encoding="utf-8")
        except OSError:
            mep_text = None
    mep = parse(mep_text)
    coordination = coordination_of(mep)
    if not coordination.idsFiles:
        return {
            "coordination": coordination.model_dump(mode="json", by_alias=True, exclude_none=True),
            "results": [],
            "counts": {"new": 0, "reopened": 0, "resolved": 0, "open": 0},
            "notes": ["the coordination lists no IDS files"],
        }
    models, notes = _models(root, mep)
    results: list[dict[str, Any]] = []
    found: list[dict[str, Any]] = []
    scope: set[str] = set()
    for ids_file in coordination.idsFiles:
        path = Path(ids_file) if Path(ids_file).is_absolute() else root / ids_file
        scope.add(ids_file)
        for label, model in models:
            try:
                specifications = check_model(path, model)
            except Exception as error:  # noqa: BLE001 - IfcTester raises several kinds
                notes.append(f"{ids_file} on {label}: could not be checked ({error})")
                continue
            results.append({"ids": ids_file, "model": label, "specifications": specifications})
            for spec in specifications:
                if not spec["failed"]:
                    continue
                listed = spec["failures"][:MAX_FAILURES]
                more = spec["failed"] - len(listed)
                reasons = "; ".join(dict.fromkeys(f["reason"] for f in listed if f["reason"]))
                found.append(
                    {
                        "key": f"ids:{ids_file}:{spec['name']}:{label}",
                        "test": ids_file,
                        "title": f"IDS: {spec['name']} ({label})",
                        "elements": [f["globalId"] for f in listed],
                        "description": (
                            f"{spec['failed']} of {spec['applicable']} elements fail"
                            + (f" ({more} not listed)" if more > 0 else "")
                            + (f": {reasons[:600]}" if reasons else "")
                        ),
                    }
                )
    merged, counts = merge_found(coordination, found, scope, source="ids")
    return {
        "coordination": merged.model_dump(mode="json", by_alias=True, exclude_none=True),
        "results": results,
        "counts": counts,
        "notes": notes,
    }

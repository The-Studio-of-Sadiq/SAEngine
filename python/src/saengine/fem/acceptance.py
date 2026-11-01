"""Acceptance of the members of a pushover at its target displacement, by the method the code
pack names.

The code pack's ``pushover.acceptance`` (:class:`saengine.codes.tables.PushoverAcceptance`)
limits a member's deformation at the target displacement to ``deformationShare`` × the
deformation at which it fails: for a member that carries gravity loads, the smaller of the
deformation at which it can no longer carry them and the one at which its strength has
dropped below ``residualStrengthShare`` × its peak; for any other member, the latter.

One method is implemented, ``fibreStrain``, for the fibre elements of the pushover model
(:mod:`saengine.fem.nonlinear`): a member's deformation is measured by the strains of the
fibres of its end sections, each against the strains at which its own material curve fails:

- concrete (``Concrete02``, compression): the strength falls below the residual share of the
  peak on the descending branch from (εc0, f'c) to (εu, fpcu) at
  ε = εc0 + (1 - share)/(1 - fpcu/f'c)·(εu - εc0); it can no longer carry gravity load at εu
  (crushed). Cover concrete is left out: it may spall without the member losing strength;
- reinforcing bars and steel shapes (``Steel02``, which does not lose strength): the pack's
  fracture (or buckling) strain for both.

Results per member: the largest ratio of demand to limit over its elements and ends, with the
fibre that governs.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def table() -> Any | None:
    from saengine.fem.pushover_target import table as pushover_table

    found = pushover_table()
    return found.acceptance if found is not None else None


# ───────────────────────────────────── fibre limits ─────────────────────────────────────


def concrete_failure_strains(material: dict[str, Any], residual: float) -> tuple[float, float]:
    """Compressive strains (positive) at which a ``Concrete02`` material has dropped below
    ``residual`` × its peak strength, and at which it has crushed (εu)."""
    fpc, eps0 = abs(float(material["fpc"])), abs(float(material["epsc0"]))
    fpcu, epsu = abs(float(material.get("fpcu", 0.0))), abs(float(material["epsU"]))
    drop = 1 - fpcu / fpc if fpc > 0 else 1.0
    if drop <= 1 - residual or epsu <= eps0:
        return epsu, epsu  # the residual strength stays above the share: crushing governs
    return eps0 + (1 - residual) / drop * (epsu - eps0), epsu


def _fibre_kinds(
    section: dict[str, Any], materials: dict[int, dict[str, Any]]
) -> list[tuple[str, int]]:
    """The kind ("concrete", "cover", "bar", "steel", "other") and material id of each fibre
    of a FiberSection, in the order OpenSees creates them: patches, layers, point fibres."""
    kinds: list[tuple[str, int]] = []

    def kind(material_id: int, point: bool) -> str:
        m = materials.get(material_id, {})
        if m.get("type") == "Concrete02":
            return "cover" if str(m.get("name", "")).endswith(" cover") else "concrete"
        if m.get("type") == "Steel02":
            return "bar" if point else "steel"
        return "other"

    for patch in section.get("patches", []):
        if patch["kind"] == "rect":
            n = int(patch["n_fib_y"]) * int(patch["n_fib_z"])
        else:
            n = int(patch["n_fib_circ"]) * int(patch["n_fib_rad"])
        kinds += [(kind(patch["material_id"], False), patch["material_id"])] * n
    for layer in section.get("layers", []):
        kinds += [(kind(layer["material_id"], True), layer["material_id"])] * int(layer["n_bars"])
    for fibre in section.get("fibres", []):
        kinds.append((kind(fibre["material_id"], True), fibre["material_id"]))
    return kinds


#: What each kind of fibre is called in the results.
FIBRE_LABELS = {
    "concrete": "concrete",
    "bar": "reinforcing bar",
    "steel": "steel",
}


def _limits(
    kinds: list[tuple[str, int]],
    materials: dict[int, dict[str, Any]],
    rule: Any,
    gravity: bool,
) -> list[tuple[str, float, int] | None]:
    """Per fibre: (kind, strain limit, sign of the strain that counts: -1 compression,
    0 either) or None when it is not checked."""
    share = rule.deformationShare
    result: list[tuple[str, float, int] | None] = []
    for kind, material_id in kinds:
        if kind == "concrete":
            strength, crushed = concrete_failure_strains(
                materials[material_id], rule.residualStrengthShare
            )
            capacity = min(strength, crushed) if gravity else strength
            result.append(("concrete", share * capacity, -1))
        elif kind == "bar":
            result.append(("bar", share * rule.reinforcementFractureStrain, 0))
        elif kind == "steel":
            result.append(("steel", share * rule.steelFractureStrain, 0))
        else:
            result.append(None)
    return result


def _worst(
    fibres: np.ndarray, limits: list[tuple[str, float, int] | None]
) -> tuple[float, str, float, float] | None:
    """The largest demand/limit of the fibres at one step (rows y, z, area, stress, strain):
    (ratio, kind, strain, limit)."""
    if len(fibres) != len(limits):
        return None
    best: tuple[float, str, float, float] | None = None
    for row, limit in zip(fibres, limits, strict=True):
        if limit is None:
            continue
        kind, allowed, sign = limit
        strain = float(row[4])
        demand = -strain if sign < 0 else abs(strain)
        if demand <= 0 or allowed <= 0:
            continue
        ratio = demand / allowed
        if best is None or ratio > best[0]:
            best = (ratio, kind, demand, allowed)
    return best


# ───────────────────────────────────── the check ─────────────────────────────────────


def fibre_strain(
    project: dict[str, Any], results: Any, step: int, rule: Any
) -> list[dict[str, Any]]:
    """Method ``fibreStrain``: per member (element name before any ``#``) its governing fibre
    at ``step`` of the pushover ``results`` of the model ``project``."""
    materials = {int(m["id"]): m for m in project.get("materials", [])}
    sections = {int(s["id"]): s for s in project.get("sections", [])}
    coords = {int(n["id"]): n["coords"] for n in project.get("nodes", [])}
    members: dict[str, dict[str, Any]] = {}
    for element in project.get("elements", []):
        if element.get("type") not in ("ForceBeamColumn", "DispBeamColumn"):
            continue
        section = sections.get(int(element["section_id"]))
        while section is not None and section.get("type") == "SectionAggregator":
            section = sections.get(int(section.get("section_id") or 0))
        if section is None or section.get("type") != "FiberSection":
            continue
        i, j = (np.asarray(coords[n], dtype=float) for n in element["nodes"])
        axis = j - i
        length = float(np.linalg.norm(axis))
        slope = abs(axis[2]) / length if length else 1.0
        # Columns, walls and beams carry gravity loads; inclined members (braces) do not.
        gravity = slope > 0.999 or slope < 0.05
        limits = _limits(_fibre_kinds(section, materials), materials, rule, gravity)
        member = str(element.get("name") or element["id"]).split("#")[0]
        for end, store in (("i", results.element_start_fibers), ("j", results.element_end_fibers)):
            history = store.get(int(element["id"]))
            if history is None or step >= len(history):
                continue
            found = _worst(np.asarray(history[step]), limits)
            if found is None:
                continue
            ratio, kind, demand, allowed = found
            row = members.get(member)
            if row is None or ratio > row["ratio"]:
                members[member] = {
                    "member": member,
                    "element": int(element["id"]),
                    "end": end,
                    "fibre": kind,
                    "strain": demand,
                    "limit": allowed,
                    "ratio": ratio,
                    "gravity": bool(gravity),
                    "ok": bool(ratio <= 1.0),
                }
    return sorted(members.values(), key=lambda r: -r["ratio"])


#: Acceptance methods by the id a code pack gives (``acceptance.method``).
METHODS = {"fibreStrain": fibre_strain}


def evaluate(project: dict[str, Any], results: Any, target: dict[str, Any]) -> dict[str, Any]:
    """The acceptance of the members of a pushover run at the step its target displacement
    (``target``, :func:`saengine.fem.pushover_target.evaluate`) is reached, by the method of
    the code pack in force."""
    from saengine.fem.pushover_target import clause

    rule = table()
    if rule is None:
        return {"available": False, "reason": "the code pack does not cover pushover acceptance"}
    method = METHODS.get(rule.method)
    if method is None:
        return {"available": False, "reason": f"acceptance method '{rule.method}' unknown"}
    if not target.get("available"):
        return {"available": False, "reason": "no target displacement"}
    step = target.get("targetStep")
    if step is None:
        return {
            "available": False,
            "reason": "the pushover stopped before the target displacement",
        }
    if not getattr(results, "element_start_fibers", None) and not results.element_end_fibers:
        return {"available": False, "reason": "the run kept no fibre strains; run it again"}
    rows = method(project, results, int(step), rule)
    notes = []
    if not results.element_start_fibers:
        notes.append(
            "The run kept the fibre strains of one end of each element only (an older run): "
            "run the pushover again for both ends."
        )
    failed = sum(1 for r in rows if not r["ok"])
    return {
        "available": True,
        "method": rule.method,
        "step": int(step),
        "displacement": float(target["target"]),
        "rows": rows,
        "failed": failed,
        "worst": rows[0]["ratio"] if rows else None,
        "ok": failed == 0,
        "share": rule.deformationShare,
        "residual": rule.residualStrengthShare,
        "clause": clause("acceptance"),
        "note": rule.note,
        "notes": notes,
    }


def pushover_results(out_dir: Any, project_path: Any) -> list[dict[str, Any]]:
    """The target displacement (:mod:`saengine.fem.pushover_target`) and the member acceptance
    of every pushover of a run (``out_dir``) of the model at ``project_path``:
    ``[{"key", "label", "target", "acceptance"}]``."""
    import json
    from pathlib import Path

    from opensees_studio.services.results import PushoverResults

    from saengine.fem.display import _manifest
    from saengine.fem.story_response import load_cached

    manifest = _manifest(out_dir)
    if manifest is None:
        return []
    project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    analyses = {a["id"]: a for a in project.get("analyses", [])}
    settings = analysis_settings(project_path)
    found = []
    for entry in manifest["cases"]:
        analysis = analyses.get(int(entry["case_id"]))
        if analysis is None or analysis.get("type") != "Pushover":
            continue
        try:
            results = load_cached(entry, out_dir)
        except Exception:  # noqa: BLE001, S112 - an unreadable case is left out
            continue
        if not isinstance(results, PushoverResults):
            continue
        found.append(
            {
                "key": f"case:{entry['case_id']}",
                "label": entry["case_name"],
                **evaluate_run(project, analysis, results, settings),
            }
        )
    return found


def analysis_settings(project_path: Any) -> Any:
    """The project settings of the model at ``project_path`` with the site class the analysis
    uses (from the soil report when the settings say so); None outside a project."""
    from pathlib import Path

    from saengine.fem.combinations import settings_beside
    from saengine.library.settings import read_soil_text, resolve_site_class

    settings = settings_beside(project_path)
    if settings is None:
        return None
    root = Path(project_path).resolve().parent.parent
    return resolve_site_class(settings, read_soil_text(root))[0]


def evaluate_run(
    project: dict[str, Any], analysis: dict[str, Any], results: Any, settings: Any
) -> dict[str, Any]:
    """``{"target", "acceptance"}`` of one pushover run."""
    from saengine.fem import pushover_target

    target = pushover_target.evaluate(project, analysis, results, settings)
    return {"target": target, "acceptance": evaluate(project, results, target)}

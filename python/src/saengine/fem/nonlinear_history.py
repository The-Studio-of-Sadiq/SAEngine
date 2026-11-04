"""The nonlinear time history analysis (B36): what the runs of ``08 FEM/nonlinear-history.osmodel``
mean for the design, by the rules of the code pack in force.

The model (:func:`saengine.fem.nonlinear.history_model`) runs each time history of the project
settings through the frames and walls as fibre elements, after the gravity loads, its records
scaled to the pack's nonlinear target (:mod:`saengine.fem.records`, ``seismic.timeHistory``
``targets``; the default pack's Part 6 Sec 2.5.11.2: the real design spectrum, R = 1 and I = 1). This
module reads the runs with the pack's ``nonlinearHistory`` table
(:class:`saengine.codes.tables.NonlinearHistoryTable`):

- **Suites** per direction ("X", "Y") and of pairs ("XY"), as the linear procedure forms them
  (:func:`saengine.fem.linear_time_history.transient_cases`). A suite needs the pack's least
  number of records, every run to its end (a run that stops early did not converge: the
  structure may have lost its stability) and its mean spectrum to meet the criterion with the
  fundamental period of the model's modal case (or the settings' period). The nonlinear
  responses cannot be scaled up afterwards: a suite that falls short must be scaled again.
- **Design value** of each response: the largest of the records' peaks below the procedure's
  ``meanFrom`` records (or pairs), their mean from it; with no scaling to the static base shear
  unless the pack asks for it (Sec 2.5.11.3: the results are used as they come).
- **Storey drift**: the peak drift of each storey (the largest over the plan positions), its
  design value against ``drift.limitFactor`` × the allowable storey drift of the linear
  procedures (the pack's drift table with its redundancy rule; Sec 2.5.14.1: 1.25 ×), not
  multiplied by Cd/I unless ``drift.amplify``.
- **Members**: each fibre's peak strain over the record at the members' end sections against
  the pack's acceptance (:func:`saengine.fem.acceptance.fibre_strain_peaks`; Sec 2.5.11.4: two
  thirds of the smaller of the deformation at gravity loss and at 67 % of the peak strength);
  the design ratio of a member over the suite by the same max / mean rule.
- **Design review** (Sec 2.5.11.5) is stated, never done by the program.

Alpha 9 P5, by the pack in force (no code named in the engine):

- the procedure's own least number of records, period range (from the shorter to the longer
  period, ``periodBasis`` "bounds"), ratios and target factor (:func:`saengine.fem.records.
  value`); pairs by the SRSS, the maximum-direction spectrum or each component; suites
  spectrally matched in place of scaled, checked against the matched ratio;
- ``procedure.unacceptableResponses``: how many records of a suite may stop early, by
  occupancy category; ``procedure.damping``: the damping model (Rayleigh, first mode);
- acceptance ``hingeRotation``: P3's hinges (:mod:`saengine.fem.hinges`, the pack's
  ``pushover.hinges``) read from each record (the runs keep the end sections' deformations),
  their peak against the pack's performance level, the design value over the suite;
- ``forceControlled``: column compression and member shear, γ·[I]·(Fu − Fg) + Fg against the
  member design's design strength (the kept design checks of ``model.osmodel``);
- each record's metadata (Mw, R, Vs30, source), its applied PGA and its matching.

Units: m, N (summaries in kN, m).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem import linear_time_history as lth
from saengine.fem import records as rec

#: The nonlinear time history model and its results folder beside ``model.osmodel``.
HISTORY_FILE = "nonlinear-history.osmodel"
RESULTS_FOLDER = "nonlinear-history.results"
#: The part of each suite in the results.
SUITES = ("X", "Y", "XY")


def table() -> Any | None:
    """The code pack's ``nonlinearHistory`` table; None when the pack in force has none."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    return pack.table("nonlinearHistory") if pack.has("nonlinearHistory") else None


def clause(key: str) -> str:
    """The pack's clause of ``key`` (its ``sources``), for the results and the report."""
    found = table()
    if found is None:
        return ""
    return found.sources.get(key) or found.source


def target_procedure() -> str:
    """The ``seismic.timeHistory.targets`` entry the records are scaled to."""
    found = table()
    return found.procedure.target if found is not None else "nonlinear"


def mean_from() -> int | None:
    """From how many records (or pairs) the mean governs, by the procedure's own clause."""
    found = table()
    return found.procedure.meanFrom if found is not None else None


def is_history_model(project_path: str | Path) -> bool:
    """Whether ``project_path`` is the nonlinear time history model of a project."""
    return Path(project_path).name == HISTORY_FILE


# ─────────────────────────────────────── the pieces ───────────────────────────────────────


def fundamental_periods(
    nodes: list[dict[str, Any]], periods: Any, shapes: dict[int, dict[int, Any]]
) -> dict[str, float]:
    """The period [s] of the mode with the largest effective mass in X and in Y (``periods``
    of the modes 1..n, ``shapes``: mode -> node -> vector, 1-indexed)."""
    mass = {int(n["id"]): list(n.get("mass") or [0.0] * 6) for n in nodes}
    out: dict[str, float] = {}
    for d, axis in enumerate(("X", "Y")):
        best, best_mass = None, 0.0
        for mode in sorted(shapes):
            gamma = norm = 0.0
            for node, vector in shapes[mode].items():
                m = mass.get(int(node))
                if not m:
                    continue
                v = [float(x) for x in vector]
                gamma += m[d] * v[d]
                norm += sum(m[k] * v[k] ** 2 for k in range(min(len(v), len(m), 3)))
            effective = gamma**2 / norm if norm > 0 else 0.0
            if effective > best_mass * (1 + 1e-9):
                best, best_mass = mode, effective
        if best is not None and best - 1 < len(periods):
            period = float(periods[best - 1])
            if np.isfinite(period) and period > 0:
                out[axis] = period
    return out


def read_fibre_peaks(h5_path: str | Path) -> dict[int, dict[str, np.ndarray]]:
    """The fibre strain peaks of a run (``TransientCase.record_fibre_peaks``): element id ->
    ``{"start", "end"}`` -> rows y, z, area, least strain, largest strain."""
    import h5py

    out: dict[int, dict[str, np.ndarray]] = {}
    with h5py.File(h5_path, "r") as f:
        elements = f.get("elements")
        if elements is None:
            return out
        for key, group in elements.items():
            peaks = group.get("fibrePeaks") if hasattr(group, "get") else None
            if peaks is None:
                continue
            out[int(key)] = {end: np.asarray(peaks[end][:]) for end in peaks}
    return out


def design_ratios(per_record: list[list[dict[str, Any]]], rule: str) -> list[dict[str, Any]]:
    """The design ratio of each member over the records' acceptance rows: its largest, or its
    mean (a record without the member counts 0), by ``rule``; with the governing record's row
    (``record``: its index)."""
    members: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for k, rows in enumerate(per_record):
        for row in rows:
            members.setdefault(row["member"], []).append((k, row))
    out = []
    count = max(len(per_record), 1)
    for found in members.values():
        k, worst = max(found, key=lambda item: item[1]["ratio"])
        ratio = (
            sum(r["ratio"] for _, r in found) / count if rule == "mean" else float(worst["ratio"])
        )
        out.append({**worst, "record": k, "ratio": ratio, "ok": bool(ratio <= 1.0)})
    return sorted(out, key=lambda r: -r["ratio"])


def drift_rows(
    key: str,
    drift: np.ndarray,
    levels: list[float],
    limit: float,
    amplification: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """The design drift of a suite (rows of ``levels[1:]``, columns X, Y [m]) against
    ``limit`` (a drift ratio), storey by storey, in the suite's directions."""
    axes = ["X", "Y"] if key == "XY" else [key]
    rows = []
    for k in range(1, len(levels)):
        height = levels[k] - levels[k - 1]
        if height <= 0 or k - 1 >= len(drift):
            continue
        for a, axis in enumerate("XY"):
            if axis not in axes:
                continue
            value = float(drift[k - 1][a]) * (amplification or {}).get(axis, 1.0)
            ratio = value / height
            rows.append(
                {
                    "suite": key,
                    "direction": axis,
                    "bottom": round(levels[k - 1], 3),
                    "top": round(levels[k], 3),
                    "height": round(height, 3),
                    "drift": value,
                    "ratio": ratio,
                    "limitRatio": limit,
                    "ok": bool(ratio <= limit + 1e-12),
                }
            )
    return rows


def _allowable(settings: Any, levels: list[float]) -> dict[str, Any]:
    """The allowable storey drift of the linear procedures (the pack's drift table, the
    project's Seismic Design Category and redundancy)."""
    from saengine.fem.seismic_design import (
        options_from_settings,
        seismic_design_category,
        settings_drift_limit,
        zone_of,
    )
    from saengine.library.settings import category_site_class, derived, soil_flags

    values = derived(settings)
    category = seismic_design_category(
        zone_of(values["Z"]),
        category_site_class(settings, settings.site.siteClass, soil_flags(settings)),
        settings.occupancy.category,
    )
    return settings_drift_limit(
        settings, category, max(len(levels) - 1, 0), options_from_settings(settings).redundancy
    )


def _without_ground_nodes(project: dict[str, Any]) -> dict[str, Any]:
    """``project`` without the fully fixed nodes of zero-length elements (the ground side of
    isolators or soil springs): they have no mass and share the plan position of the node
    above them, which the storey drifts must read."""
    nodes = {int(n["id"]): n for n in project.get("nodes", [])}
    ground = {
        int(k)
        for e in project.get("elements", [])
        if e.get("type") == "ZeroLength"
        for k in e.get("nodes", [])
        if all(nodes.get(int(k), {}).get("restraint") or [False])
    }
    if not ground:
        return project
    return {**project, "nodes": [n for n in project["nodes"] if int(n["id"]) not in ground]}


def _isolation_criteria(model_dir: Path) -> dict[str, Any] | None:
    """B37's time-history criteria of a seismically isolated building
    (:func:`saengine.fem.isolation.history_criteria`), when the model folder holds its
    isolation design; None for a building without isolators."""
    from saengine.fem import isolation

    try:
        if not isolation.covered():
            return None
        design = isolation.load(model_dir)
        if not design:
            return None
        return {"design": design, "criteria": isolation.history_criteria(design)}
    except (KeyError, TypeError, AttributeError, ValueError):
        return None


def _isolation_suite_check(
    isolated: dict[str, Any],
    project: dict[str, Any],
    model_dir: Path,
    ran: list[dict[str, Any]],
    settings: Any,
    key: str,
) -> dict[str, Any]:
    """A suite of an isolated building against B37's criteria (Sec 2.5.16.3.2): pairs, their
    number, and the average SRSS spectrum over the isolation period range
    (:func:`saengine.fem.isolation.check_history_suite`)."""
    from saengine.fem import isolation
    from saengine.library.settings import derived

    criteria = isolated["criteria"]
    clause_text = criteria.get("clause", "")
    if key != "XY":
        return {
            "ok": False,
            "notes": [
                (
                    "an isolated building needs pairs of records applied together "
                    f"({clause_text}): this suite is not usable"
                )
            ],
        }
    notes = []
    ok = True
    if len(ran) < int(criteria["minRecords"]):
        ok = False
        notes.append(f"{len(ran)} pairs, the isolation clause asks for {criteria['minRecords']}")
    low, high = criteria["periodRange"]
    try:
        records, pairs = lth._suite_records(project, model_dir, ran)
        periods = np.geomspace(max(low, 0.01), max(high, low * 1.01, 0.02), rec.CHECK_POINTS)
        members = rec._members(records, pairs, periods, float(criteria["recordDamping"]))
        average = np.mean(members, axis=0)
        z = float(derived(settings)["Z"] or 0.0)
        found = isolation.check_history_suite(
            [float(t) for t in periods],
            [float(v) for v in average],
            isolated["design"],
            settings.site.siteClass,
            z,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"ok": None, "notes": [f"the isolation spectrum check failed ({error})"]}
    if not found["ok"]:
        ok = False
        worst = found.get("worst") or {}
        notes.append(
            f"the average SRSS spectrum reaches {worst.get('ratio', 0):.3f} of "
            f"{criteria['spectrumFactor']:g} × the design spectrum at {worst.get('period', 0):.2f} s "
            f"(at least {found['required']:g} over {low:.2f} to {high:.2f} s, {clause_text})"
        )
    return {**found, "ok": ok and bool(found["ok"]), "periodRange": [low, high], "notes": notes}


# ─────────────────────── P5: records, hinges and force-controlled actions ───────────────────────


def _record_spans(cases: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Where each case's components lie in :func:`saengine.fem.linear_time_history.
    _suite_records`: ``(start, count)``."""
    out, start = [], 0
    for case in cases:
        count = len(case["excitations"])
        out.append((start, count))
        start += count
    return out


def _record_metadata(
    settings: Any, model_dir: Path, procedure: str, project: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """By run name ("NTH: <time history>"): the record's metadata of the project settings
    (Mw, R, Vs30, source) and the summaries of its spectral matching (the matched records the
    model runs, :func:`saengine.fem.records.suite_factors`)."""
    out: dict[str, dict[str, Any]] = {}
    analysis = getattr(settings, "analysis", None)
    used = {Path(str(r.get("source_path", ""))).name for r in project.get("ground_motions", [])}
    folder = Path(model_dir) / rec.MATCHED_FOLDER
    summaries: dict[str, list[dict[str, Any]]] = {}
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            try:
                found = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if found.get("procedure") == procedure and found.get("file") in used:
                summaries.setdefault(str(found.get("timeHistory")), []).append(
                    {
                        k: found.get(k)
                        for k in ("component", "method", "misfit", "iterations", "converged")
                    }
                )
    for history in getattr(analysis, "timeHistories", None) or []:
        entry: dict[str, Any] = {
            k: getattr(history, k)
            for k in ("magnitude", "distance", "vs30")
            if getattr(history, k, None) is not None
        }
        if getattr(history, "source", ""):
            entry["source"] = history.source
        if history.name in summaries:
            entry["matching"] = sorted(summaries[history.name], key=lambda s: s["component"])
        if entry:
            out[f"NTH: {history.name}"] = entry
    return out


def _frame_kinds(project: dict[str, Any]) -> dict[int, tuple[str, str]]:
    """The fibre frame elements of the model (fibre walls left out): element id -> (member,
    "column" or "beam"); braces (neither vertical nor horizontal) are left out."""
    sections = {int(s["id"]): s for s in project.get("sections", [])}
    coords = {int(n["id"]): np.asarray(n["coords"], dtype=float) for n in project["nodes"]}
    out: dict[int, tuple[str, str]] = {}
    for element in project.get("elements", []):
        if element.get("type") not in ("ForceBeamColumn", "DispBeamColumn"):
            continue
        section = sections.get(int(element.get("section_id") or 0)) or {}
        if str(section.get("name", "")).endswith((" wall fibers and shear", " wall fibers")):
            continue
        a, b = (coords[int(n)] for n in element["nodes"][:2])
        d = b - a
        length = float(np.linalg.norm(d))
        if length <= 0:
            continue
        rise = abs(float(d[2])) / length
        kind = "column" if rise > 0.99 else "beam" if rise < 0.01 else ""
        if kind:
            member = str(element.get("name") or element["id"]).split("#")[0]
            out[int(element["id"])] = (member, kind)
    return out


def _record_members(
    project: dict[str, Any],
    out_dir: str | Path,
    entries: dict[int, dict[str, Any]],
    ran: list[dict[str, Any]],
    rule: Any,
    library: dict[str, Any] | None,
    notes: list[str],
    hinge_check: bool,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, dict[str, Any]]]]:
    """Per record of a suite: the worst hinge row of each member (P3's hinges over the run,
    :func:`saengine.fem.hinges.history_rows`) and the force-controlled actions of each frame
    member ``{member: {"kind", "shear": (peak, gravity), "columnAxial": (peak, gravity)}}`` [N]
    (gravity: at the first step, after the gravity loads)."""
    from saengine.fem import hinges
    from saengine.fem.story_response import load_cached

    kinds = _frame_kinds(project) if rule.forceControlled is not None else {}
    per_hinges: list[list[dict[str, Any]]] = []
    per_forces: list[dict[str, dict[str, Any]]] = []
    for c in ran:
        try:
            results = load_cached(entries[c["id"]], out_dir)
        except Exception:  # noqa: BLE001 - a run that cannot be read counts as none
            notes.append(f"{c['name']}: its results could not be read")
            per_hinges.append([])
            per_forces.append({})
            continue
        rows: list[dict[str, Any]] = []
        if hinge_check:
            fibre = next(iter(kinds), None) or next(
                (
                    int(e["id"])
                    for e in project.get("elements", [])
                    if e.get("type") in ("ForceBeamColumn", "DispBeamColumn")
                ),
                None,
            )
            kept = fibre is not None and bool(results.element_section_deformations(fibre))
            if not kept:
                notes.append(
                    f"{c['name']}: the run kept no section deformations, so its hinges are "
                    "not read; derive the model again and run it"
                )
            else:
                found, more = hinges.history_rows(
                    project,
                    hinges.transient_results(results),
                    rule.acceptance.performanceLevel,
                    library,
                )
                for text in more:
                    if text not in notes:
                        notes.append(text)
                worst: dict[str, dict[str, Any]] = {}
                for row in found:
                    if not row.get("covered") or row.get("ratio") is None:
                        continue
                    if row["member"] not in worst or row["ratio"] > worst[row["member"]]["ratio"]:
                        worst[row["member"]] = row
                rows = list(worst.values())
        per_hinges.append(rows)
        members: dict[str, dict[str, Any]] = {}
        for element, (member, kind) in kinds.items():
            try:
                f = np.asarray(results.element_force_history(element), dtype=float)
            except (KeyError, OSError, ValueError):
                continue
            if f.ndim != 2 or f.shape[1] < 12 or not len(f):
                continue
            shear = np.max(np.abs(f[:, [1, 2, 7, 8]]), axis=1)
            axial = 0.5 * (f[:, 0] - f[:, 6])  # compression +
            found = members.setdefault(
                member, {"kind": kind, "shear": (0.0, 0.0), "columnAxial": (0.0, 0.0)}
            )
            found["shear"] = (
                max(found["shear"][0], float(shear.max())),
                max(found["shear"][1], float(shear[0])),
            )
            if kind == "column":
                found["columnAxial"] = (
                    max(found["columnAxial"][0], float(axial.max())),
                    max(found["columnAxial"][1], float(axial[0])),
                )
        per_forces.append(members)
    return per_hinges, per_forces


def _force_design(
    per_record: list[dict[str, dict[str, Any]]], rule: str, ran: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The design value over the records (largest or mean, :func:`saengine.fem.records.
    design_value`) of each member's force-controlled actions, with its gravity part (the
    largest of the records') and the record of the largest peak."""
    members = sorted({m for found in per_record for m in found})
    out = []
    for member in members:
        kind = next(found[member]["kind"] for found in per_record if member in found)
        for action in ("shear", "columnAxial"):
            if action == "columnAxial" and kind != "column":
                continue
            values = [found.get(member, {}).get(action, (0.0, 0.0)) for found in per_record]
            peaks = [v[0] for v in values]
            k = int(np.argmax(peaks))
            out.append(
                {
                    "member": member,
                    "kind": kind,
                    "action": action,
                    "Fu": float(rec.design_value(np.asarray(peaks)[:, None], rule)[0]),
                    "Fg": max(v[1] for v in values),
                    "record": ran[k]["name"] if k < len(ran) else "",
                }
            )
    return out


def _design_strengths(project_path: str | Path) -> dict[str, dict[str, float]] | None:
    """The design strengths [N] of the members from the kept design checks of the analysis
    model beside the nonlinear one (``model.osmodel``): ``{member: {"shear": the least of its
    shear checks' capacities, "columnAxial": its axial compression capacity}}``; None when no
    current design checks are kept."""
    from saengine.pipeline.design_mode import kept_report
    from saengine.pipeline.run_all import results_folder

    model = Path(project_path).parent / "model.osmodel"
    if not model.is_file():
        return None
    try:
        report = kept_report(results_folder(model), model)
    except Exception:  # noqa: BLE001 - no kept checks
        return None
    if not report:
        return None
    out: dict[str, dict[str, float]] = {}
    for element in report.get("elements", []):
        found: dict[str, float] = {}
        for check in element.get("checks", []):
            name, capacity = str(check.get("name", "")), check.get("capacity")
            if not capacity or capacity <= 0:
                continue
            if name.startswith("Shear"):
                found["shear"] = min(found.get("shear", math.inf), 1e3 * float(capacity))
            elif name == "Axial compression":
                found["columnAxial"] = 1e3 * float(capacity)
        if found:
            out[str(element.get("id"))] = found
    return out


def _force_checks(
    forces: dict[str, list[dict[str, Any]]],
    rule: Any,
    settings: Any,
    project_path: str | Path,
    notes: list[str],
) -> list[dict[str, Any]]:
    """The force-controlled actions of the pack (``rule.forceControlled``): demand γ·[I]·(Fu −
    Fg) + Fg (Fu the design value over the suite, Fg the gravity part) against the member
    design's design strength (the safe side of an expected strength); one row per member and
    action, its worst suite. Forces in kN."""
    spec = rule.forceControlled
    factors = {a.action: a for a in spec.actions}
    importance = 1.0
    if spec.importance:
        from saengine.library.settings import derived

        importance = float(derived(settings).get("seismicImportance") or 1.0)
    strengths = _design_strengths(project_path)
    if strengths is None:
        notes.append(
            "force-controlled actions: no current design checks of the analysis model are kept, "
            "so the demands are shown without the members' strengths (run the design checks)"
        )
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in forces.items():
        for row in rows:
            action = factors.get(row["action"])
            if action is None:
                continue
            demand = action.factor * importance * (row["Fu"] - row["Fg"]) + row["Fg"]
            capacity = (strengths or {}).get(row["member"], {}).get(row["action"])
            ratio = demand / capacity if capacity else None
            out = {
                "member": row["member"],
                "kind": row["kind"],
                "action": row["action"],
                "category": action.category,
                "factor": action.factor,
                "suite": key,
                "record": row["record"],
                "Fu": row["Fu"] / 1e3,
                "Fg": row["Fg"] / 1e3,
                "demand": demand / 1e3,
                "capacity": capacity / 1e3 if capacity else None,
                "ratio": ratio,
                "ok": None if ratio is None else bool(ratio <= 1.0 + 1e-9),
            }
            slot = (row["member"], row["action"])
            if slot not in best or (out["ratio"] or 0.0, out["demand"]) > (
                best[slot]["ratio"] or 0.0,
                best[slot]["demand"],
            ):
                best[slot] = out
    return sorted(best.values(), key=lambda r: (-(r["ratio"] or 0.0), -r["demand"]))


# ─────────────────────────────────────── the evaluation ───────────────────────────────────────


def evaluate(out_dir: str | Path, project_path: str | Path) -> dict[str, Any] | None:
    """The nonlinear time history design of a run (``out_dir``) of the model at
    ``project_path`` (see the module doc), or None when it has no time history case:
    ``{"available", "reason", "suites", "drift", "limit", "acceptance", "notes", "clauses",
    "review", "ok"}``."""
    from opensees_studio.services.result_store import load_manifest
    from opensees_studio.services.results import ModalResults

    from saengine.fem.acceptance import PEAK_METHODS, analysis_settings
    from saengine.fem.seismic_design import _levels
    from saengine.fem.story_response import load_cached

    project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    cases = lth.transient_cases(project)
    if not cases:
        return None
    rule = table()
    if rule is None:
        return {
            "available": False,
            "reason": "the code pack in force does not cover nonlinear time history analysis",
        }
    th_rules = rec.rules()
    if th_rules is None:
        return {
            "available": False,
            "reason": "the code pack in force has no rules for time-history records",
        }
    settings = analysis_settings(project_path)
    if settings is None:
        return {"available": False, "reason": "the project settings could not be read"}
    try:
        manifest = load_manifest(out_dir)["cases"]
    except (OSError, ValueError, KeyError):
        return {"available": False, "reason": "the model has not been run"}
    entries = {int(e["case_id"]): e for e in manifest}
    model_dir = Path(project_path).parent
    levels = _levels(project, None)
    notes: list[str] = []

    # ── the fundamental periods: the settings' T, else the model's modal case ──
    given = getattr(getattr(settings, "analysis", None), "timeHistoryPeriod", None)
    periods: dict[str, float] = {}
    for entry in manifest:
        if entry.get("result_type") != "ModalResults":
            continue
        try:
            modal = load_cached(entry, out_dir)
        except Exception:  # noqa: BLE001, S112 - the check goes on without the modal case
            continue
        if isinstance(modal, ModalResults):
            periods = fundamental_periods(
                project.get("nodes", []), modal.periods, modal.mode_shapes
            )
    # ── the drift limit (Sec 2.5.14.1) ──
    try:
        allowable = _allowable(settings, levels)
    except (KeyError, AttributeError, ValueError) as error:
        return {"available": False, "reason": f"no allowable storey drift ({error})"}
    limit_factor = rule.drift.limitFactor
    limit_ratio = limit_factor * float(allowable["ratio"])
    amplification = None
    if rule.drift.amplify:
        from saengine.library.settings import derived

        values = derived(settings)
        importance = values.get("seismicImportance") or 1.0
        amplification = {
            a: float(values.get(f"Cd{a}", values.get("Cd")) or 1.0) / importance for a in "XY"
        }
    # ── B37 hook: a seismically isolated building takes the isolation clauses' criteria ──
    isolated = _isolation_criteria(model_dir)
    # The peaks read the superstructure: the fixed ground nodes under zero-length isolators share
    # the plan position of the isolated column bases and would take their place in the drifts.
    peaks_project = _without_ground_nodes(project)
    if isolated is not None:
        criteria = isolated["criteria"]
        limit_factor = 1.0
        limit_ratio = float(criteria["driftLimit"])
        allowable = {"ratio": limit_ratio, "label": "isolated structure"}
        factor = criteria.get("driftFactor") or {}
        cd = float(factor.get("Cd") or 1.0) / float(factor.get("importance") or 1.0)
        amplification = {"X": cd, "Y": cd}
        notes.append(
            f"seismically isolated building: the storey drift above the isolation system at most "
            f"{100 * limit_ratio:.1f} % of the storey height, Cd = RI = {cd:g} and I = 1 "
            f"(Sec 2.5.7.7 as the isolation clause asks; {criteria.get('clause', '')}); the "
            "suites need pairs, checked against the isolation spectrum criteria"
        )
    hinge_check = rule.acceptance.method == "hingeRotation"  # P5: P3's hinges over the records
    method = PEAK_METHODS.get(rule.acceptance.method)
    if method is None and not hinge_check:
        notes.append(f"acceptance method '{rule.acceptance.method}' unknown: no member check")
    procedure = target_procedure()
    least = int(rec.value("minimumRecords", procedure) or th_rules.minimumRecords)
    matched = rec.modification(settings, procedure) == "matching"
    allowed = int(
        rule.procedure.unacceptableResponses.get(str(settings.occupancy.category), 0)
        if rule.procedure.unacceptableResponses
        else 0
    )
    target_label = rec._spectrum_label(procedure)
    spectrum_text = (
        "real design spectrum" if target_label.startswith("real design") else target_label
    )
    meta = _record_metadata(settings, model_dir, procedure, project)
    library = None
    if hinge_check:
        from saengine.fem import hinges

        library = hinges.library_beside(project_path)
        if library is None:
            notes.append(
                "The object types could not be read: the ties of the concrete members are taken "
                "as not conforming and the steel profiles as noncompact (the safe side)."
            )
    forces: dict[str, list[dict[str, Any]]] = {}

    by_suite: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_suite.setdefault(case["suite"], []).append(case)
    suites: list[dict[str, Any]] = []
    drift: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for key in SUITES:
        members = by_suite.get(key)
        if not members:
            continue
        label = "pairs" if key == "XY" else "records"
        ran = [c for c in members if c["id"] in entries]
        stopped = [c for c in ran if entries[c["id"]].get("early_stop")]
        # P5: the pack may accept a suite with a few unacceptable responses (by category).
        complete = len(ran) == len(members) and len(stopped) <= allowed
        count = len(members)
        design_rule = rec.design_rule(count, rule.procedure.meanFrom)
        enough = count >= least
        suite: dict[str, Any] = {
            "key": key,
            "count": count,
            "rule": design_rule,
            "enough": enough,
            "complete": complete,
            "cases": [],
            "check": None,
            "period": None,
            "used": False,
        }
        suites.append(suite)
        if not enough:
            notes.append(
                f"nonlinear suite {key}: {count} {label}, the code pack asks for at least "
                f"{least} ({clause('groundMotion')})"
            )
        if stopped and len(stopped) <= allowed:
            notes.append(
                f"nonlinear suite {key}: {len(stopped)} unacceptable response"
                f"{'s' if len(stopped) != 1 else ''} (runs stopped early), as many as the code "
                f"pack accepts for occupancy category {settings.occupancy.category} "
                f"({clause('response')})"
            )
        for c in stopped:
            entry = entries[c["id"]]
            notes.append(
                f"{c['name']}: the run stopped early ({entry.get('completed_steps', '?')} of "
                f"{entry.get('n_steps_requested', '?')} steps): it did not converge, and the "
                "structure may have lost its stability under the record; the suite cannot be "
                "accepted until it runs to its end"
            )
        if len(ran) < len(members):
            notes.append(f"nonlinear suite {key}: not every record has run; run the model")
        if not ran:
            continue
        peaks = [
            lth.cached_peaks(out_dir, peaks_project, model_dir, entries[c["id"]], c, levels)
            for c in ran
        ]
        # ── the spectrum check with the fundamental period (no scaling afterwards) ──
        low, high, period = rec.period_range(key, periods, given, procedure)
        suite["period"] = period or None
        suite["modification"] = "matching" if matched else "scaling"
        check_ok = None
        if period:
            try:
                records, pairs = lth._suite_records(project, model_dir, ran)
                target = rec.target_spectrum(settings, key, procedure)
                check = rec.check_suite(
                    records,
                    target,
                    period,
                    pairs or None,
                    procedure=procedure,
                    bounds=(low, high),
                    matched=matched,
                )
                suite["check"] = check.as_dict()
                check_ok = check.ok
                if not check.ok:
                    notes.append(
                        f"nonlinear suite {key}: with T = {period:.3f} s its mean spectrum "
                        f"reaches {check.least:.3f} of {check.ratio:g} × the {spectrum_text} "
                        f"at {check.governing:.3f} s ({clause('groundMotion')}); the "
                        "nonlinear responses cannot be scaled up afterwards: set the period T "
                        "in the project settings (Analysis, Time histories) and derive again"
                    )
                # P5: the applied records' peak ground acceleration [g].
                for c, (start, count_of) in zip(ran, _record_spans(ran), strict=True):
                    pga = [
                        float(np.max(np.abs(acc))) for _, acc in records[start : start + count_of]
                    ]
                    meta.setdefault(c["name"], {})["pga"] = pga
            except (OSError, ValueError, KeyError) as error:
                notes.append(f"nonlinear suite {key}: the spectrum check failed ({error})")
        if isolated is not None:
            found_iso = _isolation_suite_check(isolated, project, model_dir, ran, settings, key)
            suite["isolation"] = found_iso
            if found_iso.get("ok") is False:
                check_ok = False
            for text in found_iso.get("notes", []):
                notes.append(f"nonlinear suite {key}: {text}")
        if not period:
            notes.append(
                f"nonlinear suite {key}: no fundamental period (run the modal case, or set "
                "the period T in the project settings): the records' scaling is not checked"
            )
        base = rec.design_value([p["base"] for p in peaks], design_rule)
        suite["cases"] = [
            {
                "id": c["id"],
                "name": c["name"],
                "complete": not entries[c["id"]].get("early_stop"),
                "baseShear": {"x": float(p["base"][0]) / 1e3, "y": float(p["base"][1]) / 1e3},
                **meta.get(c["name"], {}),  # P5: the record's metadata and matching
            }
            for c, p in zip(ran, peaks, strict=True)
        ]
        suite["baseShear"] = {"x": float(base[0]) / 1e3, "y": float(base[1]) / 1e3}
        # ── storey drift (Sec 2.5.14.1) ──
        design_drift = rec.design_value([p["drift"] for p in peaks], design_rule)
        drift += drift_rows(key, design_drift, levels, limit_ratio, amplification)
        # ── P5: the hinges and the force-controlled actions over the records ──
        if hinge_check or rule.forceControlled is not None:
            per_hinges, per_forces = _record_members(
                project, out_dir, entries, ran, rule, library, notes, hinge_check
            )
            if hinge_check:
                for row in design_ratios(per_hinges, design_rule):
                    row["suite"] = key
                    row["record"] = ran[row["record"]]["name"]
                    accepted.append(row)
            if rule.forceControlled is not None:
                forces[key] = _force_design(per_forces, design_rule, ran)
        # ── members (Sec 2.5.11.4) ──
        if method is not None:
            per_record = []
            for c in ran:
                try:
                    found = read_fibre_peaks(Path(out_dir) / entries[c["id"]]["files"][0])
                except (OSError, KeyError, ValueError):
                    found = {}
                if not found:
                    notes.append(
                        f"{c['name']}: the run kept no fibre strain peaks; derive the model "
                        "again and run it"
                    )
                per_record.append(method(project, found.get, rule.acceptance))
            for row in design_ratios(per_record, design_rule):
                row["suite"] = key
                row["record"] = ran[row["record"]]["name"]
                accepted.append(row)
        suite["used"] = bool(enough and complete and check_ok is not False)
    failing = [r for r in drift if not r["ok"]]
    if failing:
        worst = max(failing, key=lambda r: r["ratio"])
        notes.append(
            f"nonlinear storey drift {100 * worst['ratio']:.2f} % in {worst['direction']} "
            f"between {worst['bottom']:g} and {worst['top']:g} m exceeds "
            f"the limit {100 * limit_ratio:.2f} % "
            f"({clause('drift')})"
        )
    # One row per member: its worst suite.
    by_member: dict[str, dict[str, Any]] = {}
    for row in accepted:
        if row["member"] not in by_member or row["ratio"] > by_member[row["member"]]["ratio"]:
            by_member[row["member"]] = row
    member_rows = sorted(by_member.values(), key=lambda r: -r["ratio"])
    failed = sum(1 for r in member_rows if not r["ok"])
    if failed:
        notes.append(
            f"{failed} member{'s' if failed != 1 else ''} exceed the deformation limit of "
            f"the nonlinear time histories ({clause('acceptance')})"
        )
    force_rows: list[dict[str, Any]] = []
    if rule.forceControlled is not None:
        force_rows = _force_checks(forces, rule, settings, project_path, notes)
    force_failed = sum(1 for r in force_rows if r.get("ok") is False)
    if force_failed:
        notes.append(
            f"{force_failed} force-controlled action{'s' if force_failed != 1 else ''} exceed "
            f"the member design strength ({clause('forceControlled')})"
        )
    review = clause("review") if rule.procedure.designReview else ""
    if review:
        notes.append(
            "The design by nonlinear time history analysis needs an independent design review "
            f"of the records, the acceptance criteria and the structural design ({review}); "
            "SAEngine does not do it."
        )
    for text in (
        rule.procedure.note,
        rule.drift.note,
        rule.acceptance.note,
        rule.forceControlled.note if rule.forceControlled is not None else "",
    ):
        if text:
            notes.append(text)
    usable = [s for s in suites if s["used"]]
    return {
        "available": True,
        "suites": suites,
        "drift": drift,
        "limit": {
            "allowable": float(allowable["ratio"]),
            "factor": limit_factor,
            "ratio": limit_ratio,
            "row": allowable.get("label", ""),
            "amplified": bool(rule.drift.amplify),
        },
        "acceptance": {
            "method": rule.acceptance.method,
            "rows": member_rows,
            "failed": failed,
            "share": rule.acceptance.deformationShare,
            "residual": rule.acceptance.residualStrengthShare,
            "clause": clause("acceptance"),
            **(
                {"level": rule.acceptance.performanceLevel}
                if hinge_check and rule.acceptance.performanceLevel
                else {}
            ),
        },
        **(
            {
                "forceControlled": {
                    "rows": force_rows,
                    "failed": force_failed,
                    "clause": clause("forceControlled"),
                }
            }
            if rule.forceControlled is not None
            else {}
        ),
        "periods": periods,
        "notes": notes,
        "clauses": {
            k: clause(k)
            for k in ("modelling", "groundMotion", "response", "acceptance", "review", "drift")
        },
        "review": review,
        "ok": bool(usable) and not failing and not failed and not force_failed,
    }


def results_of(model_folder: str | Path) -> dict[str, Any] | None:
    """:func:`evaluate` of the project's nonlinear time history run (``08 FEM``), when the model
    has been derived and run; None otherwise."""
    folder = Path(model_folder)
    model, run = folder / HISTORY_FILE, folder / RESULTS_FOLDER
    if not model.is_file() or not (run / "manifest.json").is_file():
        return None
    return evaluate(run, model)

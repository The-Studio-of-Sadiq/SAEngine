"""The nonlinear time history analysis (B36): what the runs of ``08 FEM/nonlinear-history.osmodel``
mean for the design, by the rules of the code pack in force.

The model (:func:`saengine.fem.nonlinear.history_model`) runs each time history of the project
settings through the frames and walls as fibre elements, after the gravity loads, its records
scaled to the pack's nonlinear target (:mod:`saengine.fem.records`, ``seismic.timeHistory``
``targets``; BNBC 2020 Part 6 Sec 2.5.11.2: the real design spectrum, R = 1 and I = 1). This
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

Units: m, N (summaries in kN, m).
"""

from __future__ import annotations

import json
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
    method = PEAK_METHODS.get(rule.acceptance.method)
    if method is None:
        notes.append(f"acceptance method '{rule.acceptance.method}' unknown: no member check")

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
        complete = len(ran) == len(members) and not stopped
        count = len(members)
        design_rule = rec.design_rule(count, rule.procedure.meanFrom)
        enough = count >= th_rules.minimumRecords
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
                f"{th_rules.minimumRecords} ({clause('groundMotion')})"
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
        period = given or (
            max(periods.get("X") or 0.0, periods.get("Y") or 0.0)
            if key == "XY"
            else periods.get(key) or 0.0
        )
        suite["period"] = period or None
        check_ok = None
        if period:
            try:
                records, pairs = lth._suite_records(project, model_dir, ran)
                target = rec.target_spectrum(settings, key, target_procedure())
                check = rec.check_suite(records, target, period, pairs or None)
                suite["check"] = check.as_dict()
                check_ok = check.ok
                if not check.ok:
                    notes.append(
                        f"nonlinear suite {key}: with T = {period:.3f} s its mean spectrum "
                        f"reaches {check.least:.3f} of {check.ratio:g} × the real design "
                        f"spectrum at {check.governing:.3f} s ({clause('groundMotion')}); the "
                        "nonlinear responses cannot be scaled up afterwards: set the period T "
                        "in the project settings (Analysis, Time histories) and derive again"
                    )
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
            }
            for c, p in zip(ran, peaks, strict=True)
        ]
        suite["baseShear"] = {"x": float(base[0]) / 1e3, "y": float(base[1]) / 1e3}
        # ── storey drift (Sec 2.5.14.1) ──
        design_drift = rec.design_value([p["drift"] for p in peaks], design_rule)
        drift += drift_rows(key, design_drift, levels, limit_ratio, amplification)
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
    review = clause("review") if rule.procedure.designReview else ""
    if review:
        notes.append(
            "The design by nonlinear time history analysis needs an independent design review "
            f"of the records, the acceptance criteria and the structural design ({review}); "
            "SAEngine does not do it."
        )
    for text in (rule.procedure.note, rule.drift.note, rule.acceptance.note):
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
        },
        "periods": periods,
        "notes": notes,
        "clauses": {
            k: clause(k)
            for k in ("modelling", "groundMotion", "response", "acceptance", "review", "drift")
        },
        "review": review,
        "ok": bool(usable) and not failing and not failed,
    }


def results_of(model_folder: str | Path) -> dict[str, Any] | None:
    """:func:`evaluate` of the project's nonlinear time history run (``08 FEM``), when the model
    has been derived and run; None otherwise."""
    folder = Path(model_folder)
    model, run = folder / HISTORY_FILE, folder / RESULTS_FOLDER
    if not model.is_file() or not (run / "manifest.json").is_file():
        return None
    return evaluate(run, model)

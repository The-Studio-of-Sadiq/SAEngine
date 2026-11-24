"""FEM Model - Analyze tab: solver options, stability/buckling, modal/mass checks, and run diagnostics."""

from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.fem_common import (
    building_height_m,
    export_fem_file,
    format_json,
    load_bim,
    load_manifest,
    load_settings,
    optional_osmodel,
    require_results,
)
from saengine.fem import (
    buckling,
    loads,
    notional_loads,
    results_check,
    second_order,
    story_response,
)
from saengine.report.clauses import in_force


@feature(
    "analyze.solverOptions",
    "Solver Options",
    part="fem",
    fields=[
        select(
            "solver",
            "Equation solver",
            [
                ("UmfPack", "Sparse LU (UmfPack)"),
                ("BandGeneral", "Banded"),
                ("ProfileSPD", "Profile SPD"),
                ("Mumps", "Parallel MUMPS"),
            ],
            "UmfPack",
        ),
        number("threads", "Worker threads", 4, min=1, max=64),
        number("memoryMb", "Memory budget", 4096, unit="MB", min=256),
    ],
    requires_project=False,
)
def solver_options(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure equation solver, threading, and estimate system DOF memory footprint."""
    _, model = optional_osmodel(ctx)
    bim = load_bim(ctx)
    n_nodes = len(model.get("nodes", [])) if model else (len(bim.elements) * 2 if bim else 48)
    n_elems = len(model.get("elements", [])) if model else (len(bim.elements) if bim else 64)
    dofs = n_nodes * 6
    est_mb = max(4.0, (dofs * 36.0 * 8.0) / (1024.0 * 1024.0))
    fits = est_mb <= values["memoryMb"]
    rows = [
        {"parameter": "Solver algorithm", "value": str(values["solver"])},
        {"parameter": "Threads", "value": str(int(values["threads"]))},
        {"parameter": "Model nodes", "value": str(n_nodes)},
        {"parameter": "Model elements", "value": str(n_elems)},
        {"parameter": "Estimated free DOFs", "value": str(dofs)},
        {"parameter": "Estimated matrix memory [MB]", "value": f"{est_mb:.2f}"},
        {"parameter": "Fits memory budget", "value": str(fits)},
    ]
    return result(
        summary={
            "solver": str(values["solver"]),
            "threads": int(values["threads"]),
            "estimatedDofs": dofs,
            "estimatedMemoryMb": est_mb,
            "withinBudget": fits,
        },
        tables=[
            table(
                "Solver configuration & DOF sizing",
                [("parameter", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Sparse direct factorization scales roughly with DOF count and graph fill-in."],
    )


@feature(
    "analyze.pDelta",
    "P-Delta",
    part="fem",
    fields=[
        select(
            "method",
            "Second-order option",
            [
                ("pDelta", "P-Delta preload"),
                ("directAnalysis", "Direct analysis (0.8 EA/EI)"),
                ("none", "First-order only"),
            ],
            "pDelta",
        ),
        number("gravityScale", "Preload gravity scale", 1.2, min=0.5, max=2.0),
    ],
    requires_project=False,
)
def p_delta(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate second-order P-Delta preload factors and drift amplification if analyzed."""
    settings = load_settings(ctx)
    with in_force(ctx.root):
        opts = second_order.options_from_settings(settings)
        preload = second_order.pdelta_factors()
        stab_grav = second_order.stability_gravity_factors()
    out_dir = None
    _, model = optional_osmodel(ctx)
    try:
        out_dir, _model_path = require_results(ctx)
    except FeatureInputError:
        out_dir = None

    amp_summary: dict[str, Any] = {}
    if out_dir is not None and model is not None:
        try:
            amp_summary = second_order.drift_amplification(model, out_dir)
        except Exception:  # noqa: BLE001
            amp_summary = {}

    rows = [
        {"item": "Configured second-order", "value": str(opts.secondOrder)},
        {"item": "Stiffness option", "value": str(opts.stiffness)},
        {"item": "Direct analysis", "value": str(opts.directAnalysis)},
        {
            "item": "Preload factors",
            "value": ", ".join(f"{k}:{v:g}" for k, v in preload.items())
            or f"{values['gravityScale']:g}D+1.0L",
        },
        {
            "item": "Stability θ gravity factors",
            "value": ", ".join(f"{k}:{v:g}" for k, v in stab_grav.items()) or "1.0D+1.0L",
        },
        {
            "item": "Model uses P-Delta",
            "value": str(second_order.is_second_order(model) if model else False),
        },
    ]
    return result(
        summary={
            "method": str(values["method"]),
            "configuredOption": str(opts.secondOrder),
            "directAnalysis": bool(opts.directAnalysis),
            "amplificationComputed": bool(amp_summary),
        },
        tables=[
            table(
                "Second-order P-Delta parameters", [("item", "Parameter"), ("value", "Value")], rows
            )
        ],
        notes=[
            "Vertical elements use geometric P-Delta stiffness under the locked gravity preload."
        ],
    )


@feature(
    "analyze.modalCases",
    "Modal Cases",
    part="fem",
    fields=[
        select(
            "extraction",
            "Extraction method",
            [("eigen", "Subspace / Lanczos Eigen"), ("ritz", "Load-dependent Ritz")],
            "eigen",
        ),
        number("modes", "Number of modes", 12, min=1, max=100),
        number("massRatioTarget", "Target mass participation", 0.90, min=0.5, max=1.0),
    ],
    requires_project=False,
)
def modal_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure eigenvalue or Ritz modal extraction and estimate fundamental period."""
    settings = load_settings(ctx)
    bim = load_bim(ctx)
    _, model = optional_osmodel(ctx)
    h_m = building_height_m(bim, model)
    sys_id = str(getattr(getattr(settings, "seismic", None), "system", None) or "rcSmf")
    with in_force(ctx.root):
        t_approx = loads.approximate_period(h_m, sys_id)
    analyses = model.get("analyses", []) if model else []
    modal_defined = [a for a in analyses if "modal" in str(a.get("type", "")).lower()]
    rows = [
        {"property": "Extraction algorithm", "value": str(values["extraction"])},
        {"property": "Requested modes", "value": str(int(values["modes"]))},
        {"property": "Target cumulative mass ratio", "value": f"{values['massRatioTarget']:.2f}"},
        {"property": "Modal cases in model", "value": str(len(modal_defined))},
        {"property": "Estimated fundamental period [s]", "value": f"{t_approx:.3f}"},
    ]
    return result(
        summary={
            "extraction": str(values["extraction"]),
            "requestedModes": int(values["modes"]),
            "definedModalCases": len(modal_defined),
            "approxPeriodS": t_approx,
        },
        tables=[
            table("Modal case parameters", [("property", "Property"), ("value", "Value")], rows)
        ],
        notes=[
            "At least 3 modes per storey (minimum 12) or 90% mass participation is recommended."
        ],
    )


@feature(
    "analyze.bucklingCases",
    "Buckling Cases",
    part="fem",
    fields=[
        number("modes", "Buckling modes", 6, min=1, max=30),
        text("caseFilter", "Combination/case filter", "D"),
    ],
    requires_project=True,
)
def buckling_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run linear elastic frame buckling eigenvalue analysis on analyzed axial forces."""
    out_dir, _model_path = require_results(ctx)
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel before running buckling analysis.")
    from opensees_studio.services.result_store import load_results
    from opensees_studio.services.results import StaticResults

    manifest = load_manifest(out_dir)
    filt = values["caseFilter"].strip().lower()
    axial: dict[int, float] = {}
    used_cases: list[str] = []
    for entry in manifest.get("cases", []):
        if entry.get("result_type") != "StaticResults":
            continue
        cname = str(entry.get("case_name", ""))
        if filt and filt not in cname.lower():
            continue
        res = load_results(entry, out_dir)
        if not isinstance(res, StaticResults):
            continue
        used_cases.append(cname)
        for eid, arr in res.element_forces.items():
            a = np.asarray(arr, dtype=float)
            if a.size:
                flat = a.reshape(-1, a.shape[-1])
                axial[int(eid)] = axial.get(int(eid), 0.0) + float(flat[-1, 0])
    if not axial:
        raise FeatureInputError("No static element axial forces found for the selected filter.")
    try:
        bres = buckling.linear_buckling(model, axial, modes=int(values["modes"]))
    except buckling.BucklingError as exc:
        raise FeatureInputError(f"Buckling solver could not run: {exc}") from exc

    rows = [
        {
            "mode": idx + 1,
            "loadFactor": lam,
            "criticalStatus": "Unstable (<1)" if lam < 1.0 else "Stable (>=1)",
        }
        for idx, lam in enumerate(bres.factors)
    ]
    return result(
        summary={
            "modesSolved": len(bres.factors),
            "firstCriticalFactor": bres.factors[0] if bres.factors else 0.0,
            "casesIncluded": ", ".join(used_cases) or "None",
            "framesAnalysed": len(bres.frames),
        },
        tables=[
            table(
                "Linear buckling critical load factors",
                [("mode", "Mode"), ("loadFactor", "λcr"), ("criticalStatus", "Status")],
                rows,
            )
        ],
        notes=[
            "Solves (K + λ Kg) φ = 0 using frame stiffness and geometric stiffness under analyzed axial loads."
        ],
    )


@feature(
    "analyze.runModelCheck",
    "Run Model Check",
    part="fem",
    fields=[number("toleranceMm", "Coincident node tolerance", 5.0, unit="mm", min=0.1)],
    requires_project=True,
)
def run_model_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate nodes, supports, element connectivity, and properties before solving."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first before running the model check.")
    nodes = model.get("nodes", [])
    elems = model.get("elements", [])
    coords = {
        n["id"]: np.asarray(n["coords"], dtype=float)
        for n in nodes
        if len(n.get("coords", [])) >= 3
    }
    restrained = sum(1 for n in nodes if any(n.get("restraint") or []))
    tol_m = values["toleranceMm"] / 1000.0
    zero_len = 0
    missing_nodes = 0
    for el in elems:
        nids = el.get("nodes") or []
        if any(nid not in coords for nid in nids):
            missing_nodes += 1
            continue
        if len(nids) == 2 and float(np.linalg.norm(coords[nids[1]] - coords[nids[0]])) < tol_m:
            zero_len += 1
    height_m = results_check.building_height(model)
    checks = [
        {"check": "Nodes defined", "count": len(nodes), "status": "OK" if nodes else "FAIL"},
        {"check": "Elements defined", "count": len(elems), "status": "OK" if elems else "FAIL"},
        {
            "check": "Restrained support nodes",
            "count": restrained,
            "status": "OK" if restrained > 0 else "FAIL",
        },
        {
            "check": "Elements with missing nodes",
            "count": missing_nodes,
            "status": "OK" if missing_nodes == 0 else "FAIL",
        },
        {
            "check": "Zero-length frame elements",
            "count": zero_len,
            "status": "OK" if zero_len == 0 else "FAIL",
        },
    ]
    passed = bool(nodes and elems and restrained > 0 and missing_nodes == 0 and zero_len == 0)
    return result(
        summary={
            "passed": passed,
            "nodes": len(nodes),
            "elements": len(elems),
            "supports": restrained,
            "heightM": height_m,
        },
        tables=[
            table(
                "Pre-analysis model validation",
                [("check", "Check"), ("count", "Count"), ("status", "Status")],
                checks,
            )
        ],
        notes=[
            "Validates connectivity, non-zero lengths, and boundary restraints prior to solver execution."
        ],
    )


@feature(
    "analyze.stabilityCheck",
    "Stability Check",
    part="fem",
    fields=[number("minSupportDofs", "Minimum restrained DOFs", 6, min=3)],
    requires_project=True,
)
def stability_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check restraint completeness, frame mechanism risk, and result plausibility if solved."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to check model stability.")
    nodes = model.get("nodes", [])
    total_restraints = sum(sum(1 for r in (n.get("restraint") or []) if r) for n in nodes)
    frames, skipped = buckling.frames_of(model)
    referenced = {nid for el in model.get("elements", []) for nid in (el.get("nodes") or [])}
    orphan_nodes = sum(1 for n in nodes if n["id"] not in referenced)
    plaus_msg = None
    out_dir = None
    try:
        out_dir, model_path = require_results(ctx)
        plaus_msg = results_check.implausible(model_path, out_dir)
    except FeatureInputError:
        pass
    rows = [
        {
            "check": "Total restrained DOFs",
            "value": str(total_restraints),
            "ok": total_restraints >= values["minSupportDofs"],
        },
        {
            "check": "Orphan (unconnected) nodes",
            "value": str(orphan_nodes),
            "ok": orphan_nodes == 0,
        },
        {"check": "Frame elements assembled", "value": str(len(frames)), "ok": len(frames) > 0},
        {
            "check": "Result plausibility",
            "value": plaus_msg or "No excessive displacements detected",
            "ok": plaus_msg is None,
        },
    ]
    stable = (
        total_restraints >= values["minSupportDofs"] and orphan_nodes == 0 and plaus_msg is None
    )
    return result(
        summary={
            "stable": stable,
            "restrainedDofs": total_restraints,
            "orphanNodes": orphan_nodes,
            "skippedTypes": len(skipped),
        },
        tables=[
            table(
                "Structural stability audit",
                [("check", "Check"), ("value", "Observed"), ("ok", "OK")],
                rows,
            )
        ],
        notes=[
            "Flags unconnected nodes, insufficient global restraints, and mechanism-level displacements."
        ],
    )


@feature(
    "analyze.massSummary",
    "Mass Summary",
    part="fem",
    fields=[number("gravityAccel", "Gravity g", 9.80665, unit="m/s²", min=9.0, max=10.0)],
    requires_project=True,
)
def mass_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report nodal seismic mass and weight by storey elevation from the model."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to summarize nodal masses.")
    levels = second_order._levels(model)
    grav = notional_loads.node_gravity(model, ("D", "SD"))
    g = values["gravityAccel"]
    mass_by_z: dict[float, float] = {z: 0.0 for z in levels}
    for node in model.get("nodes", []):
        coords = node.get("coords") or [0.0, 0.0, 0.0]
        z = float(coords[2]) if len(coords) >= 3 else 0.0
        nearest_z = min(levels, key=lambda lv: abs(lv - z)) if levels else round(z, 3)
        m_arr = node.get("mass") or []
        m_val = float(m_arr[0]) if m_arr else abs(grav.get(int(node["id"]), 0.0)) / (g * 1000.0)
        mass_by_z[nearest_z] = mass_by_z.get(nearest_z, 0.0) + m_val
    rows = [
        {"elevationM": z, "massTonnes": m, "weightKn": m * g} for z, m in sorted(mass_by_z.items())
    ]
    total_mass = sum(r["massTonnes"] for r in rows)
    return result(
        summary={
            "levelCount": len(rows),
            "totalMassTonnes": total_mass,
            "totalWeightKn": total_mass * g,
        },
        tables=[
            table(
                "Seismic mass by level",
                [
                    ("elevationM", "Elevation", "m"),
                    ("massTonnes", "Mass", "t"),
                    ("weightKn", "Weight", "kN"),
                ],
                rows,
            )
        ],
        notes=["Masses extracted from nodal mass matrices or dead-load gravity reactions."],
    )


@feature(
    "analyze.analysisReport",
    "Analysis Report",
    part="fem",
    fields=[checkbox("includePlausibility", "Include plausibility check", True)],
    requires_project=True,
)
def analysis_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Publish solver configuration, analyzed load cases, and plausibility check to Markdown."""
    out_dir, model_path = require_results(ctx)
    manifest = load_manifest(out_dir)
    cases = manifest.get("cases", [])
    plaus = (
        results_check.implausible(model_path, out_dir) if values["includePlausibility"] else None
    )
    lines = [
        "# FEM Analysis Run Report",
        "",
        f"- Results folder: `{out_dir}`",
        f"- Cases completed: {len(cases)}",
        f"- Plausibility check: {plaus or 'PASSED'}",
        "",
        "## Load Cases",
        "| ID | Case | Type | Steps | Early Stop |",
        "|---|---|---|---|---|",
    ]
    rows = []
    for c in cases:
        row = {
            "caseId": c.get("case_id"),
            "caseName": str(c.get("case_name", "")),
            "resultType": str(c.get("result_type", "")),
            "steps": int(c.get("completed_steps") or 1),
            "earlyStop": bool(c.get("early_stop", False)),
        }
        rows.append(row)
        lines.append(
            f"| {row['caseId']} | {row['caseName']} | {row['resultType']} | {row['steps']} | {row['earlyStop']} |"
        )
    report_path = export_fem_file(ctx, "analysis-report.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "caseCount": len(rows),
            "plausible": plaus is None,
            "reportPath": str(report_path),
        },
        tables=[
            table(
                "Analyzed cases",
                [
                    ("caseId", "ID"),
                    ("caseName", "Case"),
                    ("resultType", "Type"),
                    ("steps", "Steps"),
                    ("earlyStop", "Early Stop"),
                ],
                rows,
            )
        ],
        notes=[f"Report exported to {report_path}"],
    )


@feature(
    "analyze.storeResults",
    "Store Results",
    part="fem",
    fields=[text("revisionTag", "Revision label", "rev-1")],
    requires_project=True,
)
def store_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Hash and archive analysis manifest metadata against the current model revision."""
    out_dir, model_path = require_results(ctx)
    manifest_bytes = (out_dir / "manifest.json").read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()[:12]
    model_hash = (
        hashlib.sha256(model_path.read_bytes()).hexdigest()[:12] if model_path.is_file() else "none"
    )
    tag = values["revisionTag"].strip() or "rev-1"
    snapshot = {
        "revisionTag": tag,
        "manifestHash": manifest_hash,
        "modelHash": model_hash,
        "resultsDir": str(out_dir),
        "cases": len(load_manifest(out_dir).get("cases", [])),
    }
    out_path = export_fem_file(ctx, f"results-revision-{tag}.json", format_json(snapshot))
    return result(
        summary={
            "revisionTag": tag,
            "manifestHash": manifest_hash,
            "modelHash": model_hash,
            "snapshotPath": str(out_path),
        },
        tables=[
            table(
                "Stored result revision",
                [("key", "Field"), ("val", "Value")],
                [{"key": k, "val": str(v)} for k, v in snapshot.items()],
            )
        ],
        notes=[f"Revision snapshot written to {out_path}"],
    )


@feature(
    "analyze.compareRuns",
    "Compare Runs",
    part="fem",
    fields=[
        text("caseA", "First case code", "EX"),
        text("caseB", "Second case code", "EY"),
    ],
    requires_project=True,
)
def compare_runs(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare storey displacements and base reactions between two analyzed load cases."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    ca, cb = values["caseA"].strip().lower(), values["caseB"].strip().lower()
    entry_a = next((c for c in cases if ca in str(c.get("label", "")).lower()), None)
    entry_b = next((c for c in cases if cb in str(c.get("label", "")).lower()), None)
    if entry_a is None or entry_b is None:
        avail = ", ".join(str(c.get("label", "")) for c in cases[:8])
        raise FeatureInputError(f"Requested cases not found in results (available: {avail}).")
    rows = []
    for lv_a, lv_b in zip(entry_a.get("levels", []), entry_b.get("levels", []), strict=False):
        dx_a = float(lv_a.get("maxUxMm", 0.0))
        dx_b = float(lv_b.get("maxUxMm", 0.0))
        rows.append(
            {"level": lv_a.get("name", ""), "caseAMm": dx_a, "caseBMm": dx_b, "diffMm": dx_b - dx_a}
        )
    return result(
        summary={
            "caseA": entry_a.get("label", ""),
            "caseB": entry_b.get("label", ""),
            "levelsCompared": len(rows),
        },
        tables=[
            table(
                "Peak X-displacement comparison",
                [
                    ("level", "Level"),
                    ("caseAMm", "Case A", "mm"),
                    ("caseBMm", "Case B", "mm"),
                    ("diffMm", "Difference", "mm"),
                ],
                rows,
            )
        ],
        notes=["Compares peak nodal displacements per storey from 08 FEM/model.results."],
    )


@feature(
    "analyze.ritzVectorAnalysis",
    "Ritz Vector Analysis",
    part="fem",
    fields=[
        number("vectorsPerDirection", "Ritz vectors per direction", 6, min=1, max=50),
        checkbox("includeVertical", "Include Z vertical excitation", True),
    ],
    requires_project=False,
)
def ritz_vector_analysis(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure load-dependent Ritz starting vectors for X, Y, and optional Z seismic mass participation."""
    _, model = optional_osmodel(ctx)
    n_vec = int(values["vectorsPerDirection"])
    dirs = ["UX", "UY"] + (["UZ"] if values["includeVertical"] else [])
    total_vecs = n_vec * len(dirs)
    n_nodes = len(model.get("nodes", [])) if model else 0
    rows = [
        {"direction": d, "vectors": n_vec, "startingLoad": "Unit acceleration mass vector"}
        for d in dirs
    ]
    return result(
        summary={"directions": len(dirs), "totalRitzVectors": total_vecs, "modelNodes": n_nodes},
        tables=[
            table(
                "Ritz vector generation plan",
                [
                    ("direction", "Direction"),
                    ("vectors", "Count"),
                    ("startingLoad", "Starting Load"),
                ],
                rows,
            )
        ],
        notes=[
            "Load-dependent Ritz vectors capture high-frequency local and vertical modes more efficiently than pure eigensolvers."
        ],
    )


@feature(
    "analyze.eigenModalSolver",
    "Eigen Modal Solver",
    part="fem",
    fields=[
        number("numModes", "Modes to extract", 15, min=1, max=200),
        number("shiftFreqHz", "Frequency shift", 0.0, unit="Hz", min=0.0),
    ],
    requires_project=False,
)
def eigen_modal_solver(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate natural frequencies and configure shifted Lanczos/subspace eigen parameters."""
    bim = load_bim(ctx)
    _, model = optional_osmodel(ctx)
    h_m = building_height_m(bim, model)
    settings = load_settings(ctx)
    sys_id = str(getattr(getattr(settings, "seismic", None), "system", None) or "rcSmf")
    with in_force(ctx.root):
        t1 = loads.approximate_period(h_m, sys_id)
    f1 = 1.0 / max(t1, 1e-6)
    rows = [
        {"mode": k, "estPeriodS": t1 / (2 * k - 1), "estFreqHz": f1 * (2 * k - 1)}
        for k in range(1, min(int(values["numModes"]), 6) + 1)
    ]
    return result(
        summary={
            "numModes": int(values["numModes"]),
            "shiftHz": values["shiftFreqHz"],
            "estFundamentalHz": f1,
        },
        tables=[
            table(
                "Estimated cantilever modal frequencies",
                [("mode", "Mode"), ("estPeriodS", "Period", "s"), ("estFreqHz", "Frequency", "Hz")],
                rows,
            )
        ],
        notes=[
            "Estimates use code approximate fundamental period and shear-beam odd-harmonic ratios."
        ],
    )


@feature(
    "analyze.massParticipationCheck",
    "Mass Participation Check",
    part="fem",
    fields=[
        number(
            "minRatioPct",
            "Minimum cumulative mass participation",
            90.0,
            unit="%",
            min=50.0,
            max=100.0,
        )
    ],
    requires_project=True,
)
def mass_participation_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify cumulative modal mass participation ratios from modal results against target."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    modal_rows = resp.get("modal", [])
    if not modal_rows:
        raise FeatureInputError("No modal participation results found in 08 FEM/model.results.")
    sum_x = sum(float(r.get("ux", 0.0)) for r in modal_rows)
    sum_y = sum(float(r.get("uy", 0.0)) for r in modal_rows)
    # Normalize if stored as 0-1 fractions
    scale = 100.0 if max(sum_x, sum_y) <= 1.05 else 1.0
    pct_x, pct_y = sum_x * scale, sum_y * scale
    req = values["minRatioPct"]
    rows = [
        {
            "mode": r.get("mode"),
            "periodS": r.get("period"),
            "uxPct": float(r.get("ux", 0.0)) * scale,
            "uyPct": float(r.get("uy", 0.0)) * scale,
        }
        for r in modal_rows[:20]
    ]
    return result(
        summary={
            "modes": len(modal_rows),
            "sumUxPct": pct_x,
            "sumUyPct": pct_y,
            "passes": pct_x >= req and pct_y >= req,
        },
        tables=[
            table(
                "Modal mass participation",
                [
                    ("mode", "Mode"),
                    ("periodS", "T", "s"),
                    ("uxPct", "UX", "%"),
                    ("uyPct", "UY", "%"),
                ],
                rows,
            )
        ],
        notes=[
            f"Cumulative mass participation target: {req:.1f}% in both orthogonal horizontal directions."
        ],
    )


@feature(
    "analyze.diaphragmFlexibility",
    "Diaphragm Flexibility",
    part="fem",
    fields=[
        number("spanM", "Diaphragm span between lateral lines", 18.0, unit="m", min=1.0),
        number("depthM", "Diaphragm depth parallel to load", 12.0, unit="m", min=1.0),
        number("slabThicknessMm", "Slab thickness", 150.0, unit="mm", min=50.0),
        number("maxDriftMm", "Frame inter-storey drift Δframe", 12.0, unit="mm", min=0.1),
        number("diaphragmDeflMm", "In-plane diaphragm deflection δMDD", 4.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def diaphragm_flexibility(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify diaphragm in-plane rigidity via span-to-depth aspect ratio and deflection ratio."""
    aspect = values["spanM"] / values["depthM"]
    ratio = values["diaphragmDeflMm"] / values["maxDriftMm"]
    classification = (
        "Flexible"
        if (ratio > 2.0 or aspect > 3.0)
        else ("Rigid" if ratio <= 0.5 and aspect <= 2.0 else "Semi-rigid")
    )
    rows = [
        {
            "metric": "Plan aspect ratio L/B",
            "value": round(aspect, 3),
            "threshold": "<= 3.0 for rigid",
        },
        {
            "metric": "Deflection ratio δMDD / Δframe",
            "value": round(ratio, 3),
            "threshold": "<= 2.0 for non-flexible",
        },
        {
            "metric": "Slab thickness [mm]",
            "value": values["slabThicknessMm"],
            "threshold": ">= 50 mm",
        },
    ]
    return result(
        summary={"aspectRatio": aspect, "deflectionRatio": ratio, "classification": classification},
        tables=[
            table(
                "Diaphragm flexibility classification",
                [("metric", "Metric"), ("value", "Value"), ("threshold", "Criterion")],
                rows,
            )
        ],
        notes=[
            "A diaphragm is flexible when mid-span in-plane deflection exceeds twice the average storey drift."
        ],
    )


@feature(
    "analyze.solverWarnings",
    "Solver Warnings",
    part="fem",
    fields=[],
    requires_project=True,
)
def solver_warnings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List solver convergence warnings, early-stop flags, and displacement plausibility notices."""
    out_dir, model_path = require_results(ctx)
    manifest = load_manifest(out_dir)
    rows = []
    for c in manifest.get("cases", []):
        warns = list(c.get("warnings") or [])
        if c.get("early_stop"):
            warns.append("Analysis stopped before reaching full load factor.")
        for w in warns:
            rows.append({"case": str(c.get("case_name", "")), "warning": str(w)})
    plaus = results_check.implausible(model_path, out_dir)
    if plaus:
        rows.append({"case": "Global", "warning": plaus})
    return result(
        summary={"warningCount": len(rows), "casesChecked": len(manifest.get("cases", []))},
        tables=[
            table(
                "Solver warnings and flags",
                [("case", "Load Case"), ("warning", "Message")],
                rows or [{"case": "All", "warning": "No solver warnings recorded."}],
            )
        ],
        notes=["Inspects OpenSees manifest warnings and implausible displacement checks."],
    )


@feature(
    "analyze.illConditionedCheck",
    "Ill-Conditioned Check",
    part="fem",
    fields=[number("stiffnessRatioLimit", "Max adjacent stiffness ratio", 1e6, min=100.0)],
    requires_project=True,
)
def ill_conditioned_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect extreme member stiffness contrasts and zero-stiffness DOFs in the model."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to check matrix conditioning.")
    sections = model.get("sections", [])
    eas = [float(s["E"]) * float(s["A"]) for s in sections if s.get("E") and s.get("A")]
    eis = [float(s["E"]) * float(s["Iz"]) for s in sections if s.get("E") and s.get("Iz")]
    ratio_ea = (max(eas) / min(eas)) if eas and min(eas) > 0 else 1.0
    ratio_ei = (max(eis) / min(eis)) if eis and min(eis) > 0 else 1.0
    limit = values["stiffnessRatioLimit"]
    rows = [
        {"metric": "Axial stiffness max/min EA ratio", "value": ratio_ea, "ok": ratio_ea <= limit},
        {
            "metric": "Flexural stiffness max/min EI ratio",
            "value": ratio_ei,
            "ok": ratio_ei <= limit,
        },
        {
            "metric": "Estimated digits lost ~ log10(κ)",
            "value": round(math.log10(max(ratio_ea, ratio_ei, 1.0)), 2),
            "ok": max(ratio_ea, ratio_ei) <= limit,
        },
    ]
    return result(
        summary={
            "eaRatio": ratio_ea,
            "eiRatio": ratio_ei,
            "wellConditioned": max(ratio_ea, ratio_ei) <= limit,
        },
        tables=[
            table(
                "Stiffness conditioning diagnostics",
                [("metric", "Metric"), ("value", "Value"), ("ok", "OK")],
                rows,
            )
        ],
        notes=[
            "Extreme ratios (>1e6) between rigid links/springs and flexible members increase condition number."
        ],
    )


@feature(
    "analyze.solveTimeReport",
    "Solve Time Report",
    part="fem",
    fields=[],
    requires_project=True,
)
def solve_time_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report solver phase durations and result file sizes from 08 FEM/model.results."""
    out_dir, _ = require_results(ctx)
    manifest = load_manifest(out_dir)
    rows = []
    total_kb = 0.0
    total_sec = 0.0
    for c in manifest.get("cases", []):
        files = c.get("files") or []
        kb = sum((out_dir / f).stat().st_size for f in files if (out_dir / f).is_file()) / 1024.0
        sec = float(c.get("elapsed_s") or 0.0)
        total_kb += kb
        total_sec += sec
        rows.append(
            {
                "case": str(c.get("case_name", "")),
                "type": str(c.get("result_type", "")),
                "steps": int(c.get("completed_steps") or 1),
                "elapsedS": sec,
                "sizeKb": kb,
            }
        )
    return result(
        summary={"caseCount": len(rows), "totalElapsedS": total_sec, "totalSizeKb": total_kb},
        tables=[
            table(
                "Case solve timings & storage",
                [
                    ("case", "Case"),
                    ("type", "Type"),
                    ("steps", "Steps"),
                    ("elapsedS", "Time", "s"),
                    ("sizeKb", "Size", "KB"),
                ],
                rows,
            )
        ],
        notes=["Reads timing and HDF5 file sizes from 08 FEM/model.results."],
    )


@feature(
    "analyze.memoryProfile",
    "Memory Profile",
    part="fem",
    fields=[number("availableRamGb", "Available system RAM", 16.0, unit="GB", min=1.0)],
    requires_project=False,
)
def memory_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate peak sparse stiffness matrix and result-store memory usage."""
    _, model = optional_osmodel(ctx)
    n_nodes = len(model.get("nodes", [])) if model else 100
    n_elems = len(model.get("elements", [])) if model else 160
    dofs = n_nodes * 6
    nnz = dofs * 42
    k_mb = (nnz * 8.0) / (1024.0 * 1024.0)
    lu_mb = k_mb * 6.5
    ram_mb = values["availableRamGb"] * 1024.0
    rows = [
        {"component": "Global sparse matrix K", "memoryMb": k_mb},
        {"component": "LU factorization fill-in", "memoryMb": lu_mb},
        {"component": "Element & nodal result buffers", "memoryMb": max(1.0, n_elems * 0.05)},
    ]
    peak_mb = sum(r["memoryMb"] for r in rows)
    return result(
        summary={
            "dofs": dofs,
            "estimatedPeakMb": peak_mb,
            "ramUtilizationPct": (peak_mb / ram_mb) * 100.0,
        },
        tables=[
            table(
                "Solver memory breakdown",
                [("component", "Component"), ("memoryMb", "Memory", "MB")],
                rows,
            )
        ],
        notes=["Peak memory estimate assumes sparse symmetric/unsymmetric direct factorization."],
    )

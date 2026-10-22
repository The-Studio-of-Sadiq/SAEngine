"""Elastic second-order (P-Delta) analysis and cracked-section stiffness
(:mod:`saengine.fem.second_order`), checked against hand calculations."""

from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from saengine.fem.second_order import (
    ACI_FACTORS,
    SecondOrderOptions,
    apply_second_order,
    drift_amplification,
    is_second_order,
    level_displacement,
    loads_above,
    match_modal_stiffness,
    options_from_settings,
    storey_drifts,
)

E = 25e9  # Pa
B = 0.4  # m, square column
I = B**4 / 12
A = B * B
L = 3.0  # m
H = 10e3  # N


def _section(sid: int, name: str, inertia: float = I) -> dict[str, Any]:
    return {
        "id": sid,
        "name": name,
        "type": "ElasticSection",
        "E": E,
        "A": A,
        "Iz": inertia,
        "Iy": inertia,
        "G": E / 2.4,
        "J": 0.141 * B**4,
    }


def _static(cid: int, name: str, pattern: int) -> dict[str, Any]:
    return {
        "id": cid,
        "name": name,
        "type": "Static",
        "pattern_ids": [pattern],
        "n_steps": 1,
        "load_factor_increment": 1.0,
        "system": "BandGeneral",
        "constraints": "Plain",
        "integrator": "LoadControl",
        "algorithm": "Linear",
        "test": "NormDispIncr",
        "tolerance": 1e-8,
        "max_iter": 25,
    }


def _project(nodes, elements, sections, patterns, analyses) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "meta": {"name": "t", "description": "", "author": "", "units": "SI (m, N, kg, s, Pa)"},
        "ndm": 3,
        "ndf": 6,
        "nodes": nodes,
        "materials": [],
        "sections": sections,
        "elements": elements,
        "mp_constraints": [],
        "time_series": [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}],
        "load_patterns": patterns,
        "analyses": analyses,
        "spectra": [],
        "ground_motions": [],
    }


def _node(nid: int, xyz, fixed: bool = False, mass: float = 0.0) -> dict[str, Any]:
    return {
        "id": nid,
        "name": "",
        "coords": list(xyz),
        "mass": [mass, mass, 0.0, 0.0, 0.0, 0.0],
        "restraint": [fixed] * 6,
    }


def _frame(eid: int, name: str, i: int, j: int, section: int) -> dict[str, Any]:
    return {
        "id": eid,
        "name": name,
        "type": "ElasticBeamColumn",
        "nodes": [i, j],
        "section_id": section,
        "geom_transf": "Linear",
        "rho": 0.0,
        "consistent_mass": False,
    }


def _pattern(pid: int, name: str, nodal: dict[int, list[float]]) -> dict[str, Any]:
    return {
        "id": pid,
        "name": name,
        "type": "Plain",
        "time_series_id": 1,
        "nodal_loads": [{"node_id": n, "forces": f} for n, f in nodal.items()],
        "element_loads": [],
    }


def cantilever(p: float, parts: int) -> dict[str, Any]:
    """A cantilever column of ``parts`` elements: axial P (case D) and tip H in X (EX)."""
    top = parts + 1
    nodes = [_node(k + 1, (0.0, 0.0, L * k / parts), fixed=k == 0) for k in range(parts + 1)]
    elements = [_frame(k + 1, f"C1#{k + 1}", k + 1, k + 2, 1) for k in range(parts)]
    patterns = [
        _pattern(1, "D", {top: [0, 0, -p, 0, 0, 0]}),
        _pattern(2, "EX", {top: [H, 0, 0, 0, 0, 0]}),
    ]
    analyses = [_static(1, "D: Dead", 1), _static(2, "EX: Earthquake in X", 2)]
    return _project(nodes, elements, [_section(1, "COL column")], patterns, analyses)


def run_in_process(project: dict[str, Any], case_id: int) -> Any:
    from opensees_studio.core.project import Project
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    model = Project.model_validate(project)
    case = next(c for c in model.analyses if c.id == case_id)
    return OpenSeesRunner(model).run(case)


def tip(results: Any, node: int, dof: int = 0) -> float:
    return float(np.asarray(results.node_disp[node][-1])[dof])


P_DELTA = SecondOrderOptions(secondOrder="pDelta", pDeltaFactors={"D": 1.0})


# ─────────────────────────── the model changes ───────────────────────────


def test_none_and_gross_leave_the_model_unchanged() -> None:
    project = cantilever(1e6, 2)
    before = copy.deepcopy(project)
    result = apply_second_order(project, SecondOrderOptions())
    assert result.project == before and result.notes == []
    assert not is_second_order(result.project)
    # The input is never changed, whatever the options.
    apply_second_order(project, SecondOrderOptions(secondOrder="pDelta", stiffness="aci"))
    assert project == before


def test_p_delta_marks_columns_and_preloads_every_static_case() -> None:
    project = cantilever(1e6, 2)
    project["nodes"].append(_node(9, (4.0, 0.0, L)))
    project["elements"].append(_frame(9, "B1", 3, 9, 1))  # a beam stays Linear
    out = apply_second_order(project, P_DELTA).project
    transf = {e["name"]: e["geom_transf"] for e in out["elements"]}
    assert transf == {"C1#1": "PDelta", "C1#2": "PDelta", "B1": "Linear"}
    by_code = {a["name"].split(":")[0]: a for a in out["analyses"]}
    preload = by_code["PDelta"]
    assert preload["algorithm"] == "Newton" and "preload_case_ids" not in preload
    assert by_code["D"]["preload_case_ids"] == [preload["id"]]
    assert by_code["EX"]["preload_case_ids"] == [preload["id"]]
    assert "preload_case_ids" not in by_code["EX-1"]  # the first-order reference
    (pattern,) = (q for q in out["load_patterns"] if q["id"] == preload["pattern_ids"][0])
    assert pattern["nodal_loads"] == [{"node_id": 3, "forces": [0.0, 0.0, -1e6, 0.0, 0.0, 0.0]}]
    assert is_second_order(out)


def test_preload_is_the_factored_sum_of_the_gravity_patterns() -> None:
    project = cantilever(1e5, 1)
    project["load_patterns"].append(_pattern(3, "L", {2: [0, 0, -4e4, 0, 0, 0]}))
    project["load_patterns"].append(_pattern(4, "SD", {2: [0, 0, -1e4, 0, 0, 0]}))
    out = apply_second_order(project, SecondOrderOptions(secondOrder="pDelta"))
    pattern = out.project["load_patterns"][-1]
    # 1.2 (100 + 10) + 1.0 (40) kN = 172 kN
    assert pattern["nodal_loads"][0]["forces"][2] == pytest.approx(-172e3)
    assert out.summary["preloadFactors"] == {"D": 1.2, "SD": 1.2, "L": 1.0}


def test_aci_factors_per_member_kind() -> None:
    project = cantilever(1e5, 1)
    project["nodes"] += [_node(5, (4.0, 0.0, L)), _node(6, (4.0, 4.0, L)), _node(7, (0.0, 4.0, L))]
    project["nodes"] += [_node(8, (4.0, 0.0, 0.0), fixed=True)]
    project["elements"].append(_frame(2, "B1", 2, 5, 1))  # same section as the column
    plate = {"type": "ElasticMembranePlateSection", "E": E, "nu": 0.2, "h": 0.15, "rho": 0.0}
    project["sections"] += [
        {"id": 2, "name": "SL slab", **plate},
        {"id": 3, "name": "W wall", **plate},
    ]
    project["elements"].append(
        {"id": 3, "name": "S1", "type": "Shell", "formulation": "ASDShellQ4",
         "nodes": [2, 5, 6, 7], "section_id": 2}
    )  # fmt: skip
    project["elements"].append(
        {"id": 4, "name": "W1", "type": "Shell", "formulation": "ASDShellQ4",
         "nodes": [1, 8, 5, 2], "section_id": 3}
    )  # fmt: skip
    project["sections"].append(dict(_section(4, "STEEL column"), E=200e9))
    project["nodes"].append(_node(10, (8.0, 0.0, 0.0), fixed=True))
    project["nodes"].append(_node(11, (8.0, 0.0, L)))
    project["elements"].append(_frame(5, "SC1", 10, 11, 4))
    out = apply_second_order(project, SecondOrderOptions(stiffness="aci")).project
    sections = {s["id"]: s for s in out["sections"]}
    elements = {e["name"]: e for e in out["elements"]}
    column = sections[elements["C1#1"]["section_id"]]
    beam = sections[elements["B1"]["section_id"]]
    assert elements["C1#1"]["section_id"] != elements["B1"]["section_id"]  # split
    assert column["Iz"] == pytest.approx(0.70 * I) and column["Iy"] == pytest.approx(0.70 * I)
    assert beam["Iz"] == pytest.approx(0.35 * I) and beam["Iy"] == pytest.approx(0.35 * I)
    assert column["A"] == A and beam["A"] == A and column["J"] == _section(1, "")["J"]
    assert sections[2]["Ep_mod"] == 0.25 and sections[2]["E"] == E  # slab: bending only
    assert sections[3]["E"] == pytest.approx(0.70 * E) and "Ep_mod" not in sections[3]
    assert sections[4]["Iz"] == I  # steel is not cracked
    assert all(e["geom_transf"] == "Linear" for e in out["elements"] if "geom_transf" in e)
    walls = apply_second_order(project, SecondOrderOptions(stiffness="aci", wallsCracked=True))
    assert {s["id"]: s for s in walls.project["sections"]}[3]["E"] == pytest.approx(0.35 * E)
    # The engine reads the slab's bending factor.
    from opensees_studio.core.project import Project

    model = Project.model_validate(out)
    assert next(s for s in model.sections if s.id == 2).Ep_mod == 0.25


def test_cracked_for_lateral_keeps_the_gross_model_for_gravity() -> None:
    project = cantilever(1e5, 1)
    out = apply_second_order(project, SecondOrderOptions(stiffness="aci", crackedFor="lateral"))
    model = out.project
    assert model["sections"][0]["Iz"] == I
    by_code = {a["name"].split(":")[0]: a for a in model["analyses"]}
    assert "section_overrides" not in by_code["D"]
    (override,) = by_code["EX"]["section_overrides"]
    assert override["id"] == 1 and override["Iz"] == pytest.approx(0.70 * I)
    gravity = run_in_process(model, by_code["D"]["id"])
    lateral = run_in_process(model, by_code["EX"]["id"])
    gross = H * L**3 / (3 * E * I)
    assert tip(lateral, 2) == pytest.approx(gross / 0.70, rel=1e-6)
    assert tip(gravity, 2, 2) == pytest.approx(-1e5 * L / (E * A), rel=1e-6)


@pytest.mark.parametrize("pdelta", [False, True])
def test_cracked_for_all_keeps_the_temperature_case_gross(pdelta: bool) -> None:
    # The T case's equivalent loads come from the gross E I (fem/thermal.py): with every case
    # cracked it must still run on the gross sections, or a tip moment M would rotate the
    # cantilever M L / (0.70 E I) instead of M L / (E I).
    project = cantilever(1e5, 1)
    moment = 5e3
    project["load_patterns"].append(_pattern(3, "T", {2: [0, 0, 0, 0, moment, 0]}))
    project["analyses"].append(dict(_static(3, "T: Temperature", 3), release_diaphragms=True))
    options = SecondOrderOptions(
        stiffness="aci", crackedFor="all", secondOrder="pDelta" if pdelta else "none"
    )
    out = apply_second_order(project, options)
    model = out.project
    assert model["sections"][0]["Iz"] == pytest.approx(0.70 * I)
    by_code = {a["name"].split(":")[0]: a for a in model["analyses"]}
    (override,) = by_code["T"]["section_overrides"]
    assert override["id"] == 1 and override["Iz"] == I
    assert "section_overrides" not in by_code["EX"] and "section_overrides" not in by_code["D"]
    assert any("temperature case T keeps the gross" in n for n in out.notes)
    thermal = run_in_process(model, by_code["T"]["id"])
    assert abs(tip(thermal, 2, 4)) == pytest.approx(moment * L / (E * I), rel=1e-6)
    lateral = run_in_process(model, by_code["EX"]["id"])
    if not pdelta:
        assert tip(lateral, 2) == pytest.approx(H * L**3 / (3 * E * 0.70 * I), rel=1e-6)


def test_cracked_for_lateral_with_a_time_history_validates_and_runs(tmp_path: Path) -> None:
    """A time history (with its own preload) takes the cracked sections as overrides too."""
    from opensees_studio.core.project import Project

    project = cantilever(1e5, 2)
    project["nodes"][-1]["mass"] = [1000.0, 1000.0, 0, 0, 0, 0]
    project["load_patterns"].append(
        {"id": 3, "name": "GM", "type": "UniformExcitation", "direction": 1, "accel_series_id": 1}
    )
    project["analyses"].append(
        {"id": 3, "name": "TH: record", "type": "Transient", "pattern_ids": [3], "dt": 0.01,
         "n_steps": 10, "system": "BandGeneral", "algorithm": "Newton", "preload_case_ids": [1]}
    )  # fmt: skip
    Project.model_validate(project)
    for options in (
        SecondOrderOptions(stiffness="aci", crackedFor="lateral"),
        SecondOrderOptions(secondOrder="pDelta", stiffness="aci", crackedFor="lateral"),
    ):
        out = apply_second_order(project, options).project
        th = next(a for a in out["analyses"] if a["type"] == "Transient")
        assert th["section_overrides"][0]["Iz"] == pytest.approx(0.70 * I)
        model = Project.model_validate(out)
        case = next(c for c in model.analyses if c.type == "Transient")
        from opensees_studio.services.opensees_runner import OpenSeesRunner

        result = OpenSeesRunner(model).run(case, tmp_path / options.secondOrder)
        assert result.n_steps == 10


def _modal_cantilever(options: SecondOrderOptions) -> tuple[dict[str, Any], float, np.ndarray]:
    """A one-element cantilever, tip mass 1 t, P = 0.3 Pcr, its modal case run: (the project
    after ``options``, ω, the mode shape at the tip)."""
    q = cantilever(0.3 * math.pi**2 * E * I / (4 * L**2), 1)
    q["nodes"][1]["mass"] = [1000.0, 1000.0, 0, 0, 0, 0]
    q["analyses"].append({"id": 3, "name": "Modal", "type": "Modal", "n_modes": 1})
    o = apply_second_order(q, options).project
    modal = next(a for a in o["analyses"] if a["type"] == "Modal")
    r = run_in_process(o, modal["id"])
    return o, math.sqrt(float(np.asarray(r.eigenvalues)[0])), np.asarray(r.mode_shapes[1][2])


@pytest.mark.parametrize(
    "options",
    [
        P_DELTA,
        SecondOrderOptions(stiffness="aci", crackedFor="lateral"),
        SecondOrderOptions(secondOrder="pDelta", stiffness="aci", crackedFor="lateral"),
        SecondOrderOptions(stiffness="aci"),
    ],
    ids=["pDelta", "aci-lateral", "pDelta-aci-lateral", "aci-all"],
)
def test_modal_forces_are_solved_on_the_modal_stiffness(options: SecondOrderOptions) -> None:
    """A static case loaded with ω²·M·φ of a mode must return φ: on the preloaded, cracked
    stiffness the mode was found on (the response spectrum's member forces)."""
    from saengine.fem.seismic_design import modal_force_model

    o, omega, phi = _modal_cantilever(options)
    spectra = {
        "X": {"modes": [{"angular_frequency": omega, "mode_number": 1}], "peaks": [{2: phi}]}
    }
    model, cases = modal_force_model(o, spectra, torsion=False)
    matched = match_modal_stiffness(o, model)
    u = tip(run_in_process(matched, cases[0]["id"]), 2)
    assert u / phi[0] == pytest.approx(1.0, rel=1e-4)
    assert model == modal_force_model(o, spectra, torsion=False)[0]  # input unchanged
    if options.secondOrder == "pDelta":
        # Without it the static run is first order and gross: u = (c - P L² / 3EI) φ, c the
        # cracked factor of the modes, P the preload (its factor on D).
        p = options.pDeltaFactors["D"] * 0.3 * math.pi**2 * E * I / (4 * L**2)
        plain = tip(run_in_process(model, cases[0]["id"]), 2) / phi[0]
        cracked = 0.70 if options.crackedFor == "lateral" else 1.0
        assert plain == pytest.approx(cracked * (1 - p * L**2 / (3 * E * cracked * I)), rel=1e-3)


def test_match_modal_stiffness_without_second_order_changes_nothing() -> None:
    from saengine.fem.seismic_design import modal_force_model

    o, omega, phi = _modal_cantilever(SecondOrderOptions(stiffness="aci"))
    spectra = {
        "X": {"modes": [{"angular_frequency": omega, "mode_number": 1}], "peaks": [{2: phi}]}
    }
    model, _ = modal_force_model(o, spectra, torsion=False)
    assert match_modal_stiffness(o, model) is model


# ─────────────────────────── the analysis, by hand ───────────────────────────


def test_cantilever_amplification_against_the_buckling_load() -> None:
    """Tip deflection under P and H: P-Delta of a column cut into 8 elements against
    Δ1 / (1 - P / Pcr), Pcr = π² EI / (4 L²), and the exact beam-column solution."""
    pcr = math.pi**2 * E * I / (4 * L**2)
    p = 0.3 * pcr
    out = apply_second_order(cantilever(p, 8), P_DELTA).project
    ex = next(a for a in out["analyses"] if a["name"].startswith("EX:"))
    reference = next(a for a in out["analyses"] if a["name"].startswith("EX-1:"))
    second = tip(run_in_process(out, ex["id"]), 9)
    first = tip(run_in_process(out, reference["id"]), 9)
    delta1 = H * L**3 / (3 * E * I)
    assert first == pytest.approx(delta1, rel=1e-6)
    assert second == pytest.approx(delta1 / (1 - p / pcr), rel=0.03)
    k = math.sqrt(p / (E * I))
    exact = H / (p * k) * (math.tan(k * L) - k * L)
    assert second == pytest.approx(exact, rel=0.03)
    # The increment only: the preload's shortening is not in the EX result.
    assert abs(tip(run_in_process(out, ex["id"]), 9, 2)) < 1e-3 * abs(first)


def test_one_element_column_has_chord_p_delta_only() -> None:
    """One element per column: the PDelta transformation is a chord rotation, the lateral
    stiffness 3EI/L³ less P/L, no P-small-delta: Δ = Δ1 / (1 - P L² / (3 EI))."""
    p = 0.3 * math.pi**2 * E * I / (4 * L**2)
    out = apply_second_order(cantilever(p, 1), P_DELTA).project
    ex = next(a for a in out["analyses"] if a["name"].startswith("EX:"))
    delta1 = H * L**3 / (3 * E * I)
    expected = delta1 / (1 - p * L**2 / (3 * E * I))
    assert tip(run_in_process(out, ex["id"]), 2) == pytest.approx(expected, rel=1e-4)


def test_results_superpose_with_a_common_preload() -> None:
    """Every case runs on the same preloaded stiffness: 2 H gives twice H's response."""
    p = 0.2 * math.pi**2 * E * I / (4 * L**2)
    project = cantilever(p, 4)
    project["load_patterns"].append(_pattern(3, "WX", {5: [2 * H, 0, 0, 0, 0, 0]}))
    project["analyses"].append(_static(3, "WX: Wind in X", 3))
    out = apply_second_order(project, P_DELTA).project
    ids = {a["name"].split(":")[0]: a["id"] for a in out["analyses"]}
    ex, wx = run_in_process(out, ids["EX"]), run_in_process(out, ids["WX"])
    assert tip(wx, 5) == pytest.approx(2 * tip(ex, 5), rel=1e-9)
    assert np.asarray(wx.element_forces[1][-1])[4] == pytest.approx(
        2 * np.asarray(ex.element_forces[1][-1])[4], rel=1e-6
    )
    # The base moment includes the P-Delta moment P Δ: H L + P Δtip.
    base = abs(float(np.asarray(ex.node_reaction[1][-1])[4]))
    assert base == pytest.approx(H * L + p * tip(ex, 5), rel=1e-3)


def portal(storeys: int = 2) -> dict[str, Any]:
    """A two-column frame, one bay of 6 m, storeys of 3 m, a gravity load at each joint."""
    nodes, elements, k = [], [], 0
    for s in range(storeys + 1):
        nodes += [
            _node(10 * s + 1, (0.0, 0, 3.0 * s), s == 0),
            _node(10 * s + 2, (6.0, 0, 3.0 * s), s == 0),
        ]
    for s in range(storeys):
        for c in (1, 2):
            k += 1
            elements.append(_frame(k, f"C{c}L{s + 1}", 10 * s + c, 10 * (s + 1) + c, 1))
        k += 1
        elements.append(_frame(k, f"B1L{s + 1}", 10 * (s + 1) + 1, 10 * (s + 1) + 2, 2))
    top = [10 * s + c for s in range(1, storeys + 1) for c in (1, 2)]
    patterns = [
        _pattern(1, "D", {n: [0, 0, -400e3, 0, 0, 0] for n in top}),
        _pattern(2, "EX", {n: [H / 2, 0, 0, 0, 0, 0] for n in top}),
    ]
    analyses = [_static(1, "D: Dead", 1), _static(2, "EX: Earthquake in X", 2)]
    sections = [_section(1, "COL column"), _section(2, "BM beam", inertia=0.3 * 0.5**3 / 12)]
    return _project(nodes, elements, sections, patterns, analyses)


def test_stiffness_modifiers_change_a_frames_drift_by_the_expected_ratio() -> None:
    """Fixed-base portal, sway stiffness K = 24 E Ic / h³ (6k + 1) / (6k + 4) with
    k = (Ib / Lb) / (Ic / h) (axial shortening suppressed by a large area). Columns 0.70 Ic,
    beams 0.35 Ib: k halves, so Δcracked / Δgross = (1 / 0.70) f(k) / f(k / 2)."""
    project = portal(1)
    for section in project["sections"]:
        section["A"] *= 1e4
    ic, ib, h, span = I, project["sections"][1]["Iz"], 3.0, 6.0
    k = (ib / span) / (ic / h)

    def stiffness(ic: float, k: float) -> float:
        return 24 * E * ic / h**3 * (6 * k + 1) / (6 * k + 4)

    gross = tip(run_in_process(project, 2), 11)
    assert gross == pytest.approx(H / stiffness(ic, k), rel=1e-3)
    out = apply_second_order(project, SecondOrderOptions(stiffness="aci")).project
    cracked = tip(run_in_process(out, 2), 11)
    ratio = stiffness(ic, k) / stiffness(0.70 * ic, k * 0.35 / 0.70)
    assert cracked / gross == pytest.approx(ratio, rel=1e-3)
    assert ratio > 1 / 0.70


def test_storey_drifts_and_their_amplification(tmp_path: Path) -> None:
    project = apply_second_order(portal(2), P_DELTA).project
    model = tmp_path / "model.osmodel"
    model.write_text(json.dumps(project), encoding="utf-8")
    out = tmp_path / "model.results"
    ids = [str(a["id"]) for a in project["analyses"]]
    result = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model), "--cases", *ids,
         "--out", str(out)],
        check=False, capture_output=True, text=True, timeout=600,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    amplification = drift_amplification(project, out, importance=1.5, cd=5.5)
    (ex,) = amplification["cases"]
    assert ex["case"] == "EX" and [s["from"] for s in ex["storeys"]] == [0.0, 3.0]
    for s in ex["storeys"]:
        assert s["secondOrder"] > s["firstOrder"] > 0
        # With the preload 1.0 D, the measured amplification is 1/(1 - P δ / (V h)).
        storey = int(s["to"] / 3.0)
        gravity = 400e3 * 2 * (2 - storey + 1)  # Px by hand: 1600 kN, 800 kN
        shear = H * (2 - storey + 1)  # Vx by hand: 2H, H
        implied = gravity * s["firstOrder"] / shear
        assert s["ratio"] == pytest.approx(1 / (1 - implied), rel=0.05)
        assert s["impliedTheta"] == pytest.approx(implied, rel=0.05)
        # BNBC Eq 6.2.48 with Δ = Cd δxe / I: θ = Px δxe / (I Vx h), at the centres of mass
        # (no mass here: the mean of the two columns' drifts), unfactored Px.
        assert s["Px"] == pytest.approx(gravity) and s["Vx"] == pytest.approx(shear)
        assert s["theta"] == pytest.approx(gravity * s["centreOfMassDrift"] / (1.5 * shear))
        assert s["theta"] == pytest.approx(s["impliedTheta"] / 1.5, rel=0.02)
        assert s["thetaMax"] == pytest.approx(0.5 / 5.5)
    assert 1.0 < ex["maxRatio"] < 1.2
    assert ex["maxTheta"] == max(s["theta"] for s in ex["storeys"])
    # Without the importance factor θ is left out (said so in the notes).
    plain = drift_amplification(project, out)
    assert all(s["theta"] is None for s in plain["cases"][0]["storeys"])
    assert any("importance" in n for n in plain["notes"])


def test_loads_above_turns_frame_loads_global() -> None:
    """Px and Vx by hand: joint loads and beam loads above a level; a column's local load
    turned global exactly as the engine applies it (the reactions balance it)."""
    project = portal(2)
    beams = [e["id"] for e in project["elements"] if e["name"].startswith("B")]
    project["load_patterns"][0]["element_loads"] = [
        {"element_id": b, "wx": 0.0, "wy": 0.0, "wz": -10e3} for b in beams
    ]
    column = next(e["id"] for e in project["elements"] if e["name"] == "C1L2")
    project["load_patterns"][1]["element_loads"] = [
        {"element_id": column, "wx": 0.0, "wy": 0.0, "wz": 1e3}
    ]
    assert loads_above(project, {"D": 1.0}, 0.0)[2] == pytest.approx(-(1600e3 + 2 * 60e3))
    assert loads_above(project, {"D": 1.0}, 3.0)[2] == pytest.approx(-(800e3 + 60e3))
    assert loads_above(project, {"D": 1.2}, 3.0)[2] == pytest.approx(-1.2 * 860e3)
    ex = loads_above(project, {"EX": 1.0}, 3.0)
    assert ex[0] == pytest.approx(H + 3e3) and abs(ex[1]) < 1e-9
    assert loads_above(project, {"EX": 1.0}, 0.0)[0] == pytest.approx(2 * H + 3e3)
    result = run_in_process(project, 2)
    reactions = sum(np.asarray(result.node_reaction[n][-1])[0] for n in (1, 2))
    assert -reactions == pytest.approx(2 * H + 3e3, rel=1e-9)


def test_level_displacement_is_the_centre_of_mass() -> None:
    project = portal(1)
    project["nodes"][2]["mass"] = [3.0, 3.0, 0, 0, 0, 0]  # node 11 at x = 0
    project["nodes"][3]["mass"] = [1.0, 1.0, 0, 0, 0, 0]  # node 12 at x = 6
    disp = {n["id"]: np.zeros(6) for n in project["nodes"]}
    disp[11][1], disp[12][1] = 0.004, 0.012  # a plan rotation: Y grows with x
    # The centre of mass is at x = 1.5: 0.004 + 1.5 / 6 * 0.008 = 0.006.
    assert level_displacement(project, disp, 3.0, 1) == pytest.approx(0.006)
    assert level_displacement(project, disp, 0.0, 1) == 0.0
    assert level_displacement(project, disp, 9.0, 1) is None


def test_storey_drifts_of_a_displacement_field() -> None:
    project = portal(2)
    disp = {n["id"]: np.zeros(6) for n in project["nodes"]}
    for n in project["nodes"]:
        disp[n["id"]][0] = 0.01 * n["coords"][2] / 3.0  # 10 mm per storey
    rows = storey_drifts(project, disp, 0)
    assert [r["drift"] for r in rows] == pytest.approx([0.01 / 3.0] * 2)


def test_options_from_settings_defaults() -> None:
    from saengine.library.settings import default_project_settings

    options = options_from_settings(default_project_settings("x"))
    # The project settings default to cracked sections for the lateral cases (BNBC 2020 Part 6
    # Sec 2.5.9.1 (a), p. 634: "shall consider the effects of cracked sections") and no P-Delta.
    assert options == SecondOrderOptions(stiffness="aci", crackedFor="lateral")
    gross = SecondOrderOptions(stiffness="gross", crackedFor="lateral")
    assert apply_second_order(cantilever(1e5, 1), gross).notes == []
    assert options_from_settings(object()) == SecondOrderOptions()
    assert ACI_FACTORS["column"] == 0.70 and ACI_FACTORS["slab"] == 0.25


# ─────────────────────────── the sample building ───────────────────────────


def test_derived_building_with_p_delta_and_cracked_sections(tmp_path: Path) -> None:
    """The two-bay, three-storey frame of the staged tests (shell slabs off), derived, then
    P-Delta and cracked: every case runs; the drift amplification is small for a low frame."""
    from saengine.fem.combinations import combination_results
    from tests.test_fem_staged import derivation, settings

    d = derivation(sequence=True, stiffness="gross")  # a gross first-order derivation
    project = apply_second_order(
        d.project, SecondOrderOptions(secondOrder="pDelta", stiffness="aci")
    ).project
    staged = next(a for a in project["analyses"] if a["type"] == "Staged")
    assert staged["linear_geometry"] is True
    model = tmp_path / "model.osmodel"
    model.write_text(json.dumps(project), encoding="utf-8")
    out = tmp_path / "model.results"
    ids = [str(a["id"]) for a in project["analyses"]]
    result = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model), "--cases", *ids,
         "--out", str(out)],
        check=False, capture_output=True, text=True, timeout=900,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    amplification = drift_amplification(project, out)
    cases = {c["case"]: c for c in amplification["cases"]}
    assert set(cases) >= {"EX", "EY"}
    for case in cases.values():
        assert 1.0 < case["maxRatio"] < 1.05, case
    # The combinations are formed from the P-Delta cases as before.
    entries = combination_results(out, project, settings())
    assert entries and not any(
        w.startswith("not formed") for e in entries for w in e.get("warnings", [])
    )

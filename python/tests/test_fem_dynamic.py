"""Dynamic analyses of the derived model: BNBC response spectrum and earthquake time histories."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_fem_derive import OBJECTS, PLAN, SETTINGS

from saengine.fem import loads as fl
from saengine.fem.derive import G, derive_fem
from saengine.library import default_material_library
from saengine.library.bim import generate
from saengine.library.settings import TimeHistory, derived

DT = 0.01
FREQUENCY = 2.0  # Hz
AMPLITUDE = 0.2  # g


def write_record(path: Path) -> np.ndarray:
    """Two seconds of a 2 Hz, 0.2 g sine as a two-column (time, acceleration) file."""
    t = np.arange(0, 2 + DT / 2, DT)
    a = AMPLITUDE * np.sin(2 * math.pi * FREQUENCY * t)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{ti:.4f} {ai:.6f}" for ti, ai in zip(t, a, strict=True)) + "\n")
    return a


def newmark_peak(omega: float, zeta: float, ground: np.ndarray, dt: float) -> float:
    """Peak |u| of a damped one-degree-of-freedom oscillator under ground acceleration (m/s²)."""
    gamma, beta = 0.5, 0.25
    k, c = omega**2, 2 * zeta * omega
    u = v = 0.0
    a = -ground[0] - c * v - k * u
    peak = 0.0
    keff = k + gamma / (beta * dt) * c + 1 / (beta * dt**2)
    for p in -ground[1:]:
        rhs = (
            p
            + (u / (beta * dt**2) + v / (beta * dt) + (1 / (2 * beta) - 1) * a)
            + c
            * (gamma / (beta * dt) * u + (gamma / beta - 1) * v + dt * (gamma / (2 * beta) - 1) * a)
        )
        un = rhs / keff
        vn = (
            gamma / (beta * dt) * (un - u)
            + (1 - gamma / beta) * v
            + dt * (1 - gamma / (2 * beta)) * a
        )
        an = (un - u) / (beta * dt**2) - v / (beta * dt) - (1 / (2 * beta) - 1) * a
        u, v, a = un, vn, an
        peak = max(peak, abs(u))
    return peak


def test_response_spectrum_and_time_history_of_a_one_story_bay(tmp_path: Path) -> None:
    from opensees_studio.services.result_store import load_manifest, load_results

    record = tmp_path / "02 Project Settings" / "records" / "sine.txt"
    ground = write_record(record) * G
    history = TimeHistory(
        name="Sine X", record="02 Project Settings/records/sine.txt", direction="X"
    )
    settings = SETTINGS.model_copy(
        update={"analysis": SETTINGS.analysis.model_copy(update={"timeHistories": [history]})}
    )
    model_dir = tmp_path / "08 FEM"
    model_dir.mkdir()
    d = derive_fem(
        generate(PLAN, "s"), OBJECTS, default_material_library(), settings, None, model_dir
    )
    cases = {a["name"]: a for a in d.project["analyses"]}
    assert list(cases)[-4:] == [
        "Modal",
        "RX: Response spectrum X",
        "RY: Response spectrum Y",
        "TH: Sine X",
    ]
    assert (
        d.project["ground_motions"][0]["source_path"] == "../02 Project Settings/records/sine.txt"
    )
    transient = cases["TH: Sine X"]
    assert (transient["n_steps"], transient["dt"], transient["preload_case_ids"]) == (
        201,
        DT,
        [1, 2],
    )

    model = model_dir / "model.osmodel"
    model.write_text(json.dumps(d.project), encoding="utf-8")
    out = model_dir / "model.results"
    ids = [str(cases[n]["id"]) for n in ("Modal", "RX: Response spectrum X", "TH: Sine X")]
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *ids,
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    results = {e["case_name"]: load_results(e, str(out)) for e in load_manifest(str(out))["cases"]}

    # The bay sways in X as one mass on four columns (rigid floor): one mode governs.
    modal = results["Modal"]
    period = float(modal.periods[0])
    omega = 2 * math.pi / period
    top = max(
        results["RX: Response spectrum X"].combined_disp,
        key=lambda n: d.project["nodes"][n - 1]["coords"][2],
    )

    # Response spectrum: u = Γφ·Sa/ω² with Γφ = 1 for the floor of a single mass.
    values = derived(SETTINGS)
    sa = G * fl.design_acceleration(
        period, SETTINGS.site.siteClass, values["Z"], values["seismicImportance"], values["R"]
    )
    rs = results["RX: Response spectrum X"].combined_disp[top]
    assert rs[0] == pytest.approx(sa / omega**2, rel=0.03)

    # Time history: the same one-mass oscillator integrated here, with 5 % damping in mode 1.
    th = results["TH: Sine X"]
    assert not th.early_stop and th.n_steps == 201
    ux = th.node_disp_history(top)[:, 0]
    gravity_shift = ux[0]  # after the dead loads, before the shaking
    assert abs(np.max(np.abs(ux - gravity_shift))) == pytest.approx(
        newmark_peak(omega, 0.05, ground, DT), rel=0.03
    )

    # The 3D display: the spectrum's peak shape, and the time history frame by frame.
    from saengine.fem.display import result_list, result_view

    listing = {r["label"]: r for r in result_list(out, model)["results"]}
    assert (listing["RX: Response spectrum X"]["kind"], listing["TH: Sine X"]["kind"]) == (
        "spectrum",
        "history",
    )
    frames = listing["TH: Sine X"]["frames"]
    assert len(frames) == 200 and frames[0]["time"] == pytest.approx(DT)
    assert frames[-1]["time"] == pytest.approx(201 * DT)
    spectrum = result_view(out, model, listing["RX: Response spectrum X"]["key"])
    assert spectrum["label"].endswith("(peak values)") and spectrum["reactions"] == []
    assert {n[0]: n[1] for n in spectrum["nodes"]}[top] == pytest.approx(rs[0], rel=1e-6)
    peak = listing["TH: Sine X"]["peak"]
    view = result_view(out, model, listing["TH: Sine X"]["key"], peak)
    assert view["kind"] == "history" and view["label"].startswith("TH: Sine X, t = ")
    moved = {n[0]: n[1] for n in view["nodes"]}[top] - gravity_shift
    assert abs(moved) == pytest.approx(np.max(np.abs(ux - gravity_shift)), rel=0.05)
    # Every frame element has its section forces at that moment.
    assert all("forces" in e for e in view["elements"])

    # The results tables: each node's peak during the shaking.
    from saengine.rpc.handlers import results_tables

    cases_out = {c["caseName"]: c for c in results_tables(str(out), str(model))["cases"]}
    (peaks,) = cases_out["TH: Sine X"]["tables"]
    row = next(r for r in peaks["rows"] if r[0] == top)
    assert row[1] == pytest.approx(np.max(np.abs(ux - gravity_shift)), rel=1e-6)


def test_missing_record_is_left_out_with_a_note(tmp_path: Path) -> None:
    history = TimeHistory(name="Lost", record="02 Project Settings/records/none.AT2")
    settings = SETTINGS.model_copy(
        update={
            "analysis": SETTINGS.analysis.model_copy(
                update={"timeHistories": [history], "responseSpectrum": False}
            )
        }
    )
    (tmp_path / "08 FEM").mkdir()
    d = derive_fem(
        generate(PLAN, "s"),
        OBJECTS,
        default_material_library(),
        settings,
        None,
        tmp_path / "08 FEM",
    )
    assert [a["type"] for a in d.project["analyses"]][-1] == "Modal"
    assert any("time history 'Lost' left out" in n for n in d.notes)

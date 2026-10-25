"""Tests of the cross-check's translation (scripts/crosscheck).

    python -m pytest -q scripts/crosscheck/tests

CI-safe: the translation of a small hand-written analysis model (no OpenSees run). The solver
runs are skipped unless PyNite and CalculiX are set up locally:
``CROSSCHECK_PYNITE_PYTHON`` (the Python of PyNite's environment) and ``CROSSCHECK_CCX`` (the
``ccx`` program); see docs/verification/cross-check.md.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import run_ccx
from ir import layers

E, G = 25e9, 10e9
B, H = 0.3, 0.5
A, IY, IZ, J = B * H, B * H**3 / 12, H * B**3 / 12, 0.0028
L, P, W = 4.0, 20e3, 5e3


def cantilever() -> dict:
    """A cantilever along X (two elements, the first with a rigid zone at its fixed end) with a
    pinned twin at the middle joint tying every DOF, a tip load and a uniform load; plus a
    modal case on a lumped tip mass."""
    return {
        "meta": {"name": "test"},
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6, "mass": [0] * 6},
            {"id": 2, "coords": [2, 0, 0], "restraint": [False] * 6, "mass": [0] * 6},
            {"id": 3, "coords": [2, 0, 0], "restraint": [False] * 6, "mass": [0] * 6},
            {
                "id": 4,
                "coords": [L, 0, 0],
                "restraint": [False] * 6,
                "mass": [500, 500, 0, 0, 0, 0],
            },
        ],
        "materials": [{"id": 1, "type": "Elastic", "E": 1e13}],
        "sections": [
            {"id": 1, "type": "ElasticSection", "E": E, "A": A, "Iy": IY, "Iz": IZ, "G": G, "J": J}
        ],
        "elements": [
            {
                "id": 1,
                "name": "M1",
                "type": "ElasticBeamColumn",
                "nodes": [1, 2],
                "section_id": 1,
                "joint_offsets": [0.2, 0, 0, 0, 0, 0],
            },
            {
                "id": 2,
                "name": "M1#2",
                "type": "ElasticBeamColumn",
                "nodes": [3, 4],
                "section_id": 1,
            },
            {
                "id": 3,
                "name": "M1/pin",
                "type": "ZeroLength",
                "nodes": [2, 3],
                "material_ids": [1] * 6,
                "dofs": [1, 2, 3, 4, 5, 6],
            },
        ],
        "mp_constraints": [],
        "load_patterns": [
            {
                "id": 1,
                "name": "D",
                "type": "Plain",
                "nodal_loads": [{"node_id": 4, "forces": [0, 0, -P, 0, 0, 0]}],
                "element_loads": [{"element_id": 2, "wx": 0, "wy": 0, "wz": -W}],
            },
        ],
        "analyses": [
            {"id": 1, "name": "D: Dead", "type": "Static", "pattern_ids": [1]},
            {
                "id": 2,
                "name": "Modal",
                "type": "Modal",
                "n_modes": 1,
                "section_overrides": [{"id": 1, "Iy": IY * 0.5}],
            },
        ],
    }


@pytest.fixture(scope="module")
def ir() -> dict:
    pytest.importorskip("saengine")
    from ir import build_ir

    return build_ir(cantilever())


def test_layers_reproduce_membrane_and_bending() -> None:
    e, h = 25e9, 0.15
    for membrane, bending in ((1.0, 1.0), (1.0, 0.25), (0.7, 0.35), (1.0, 0.05)):
        lay = layers(e, h, membrane, bending)
        assert sum(x * t for x, t in lay) == pytest.approx(membrane * e * h)
        assert sum(x * t**3 for x, t in lay) == pytest.approx(bending * e * h**3)
        assert all(x > 0 and t > 0 for x, t in lay)


def test_ties_resolve_chains() -> None:
    ties = run_ccx.Ties()
    ties.add((2, 1), [((1, 1), 1.0), ((1, 6), -0.5)])
    ties.add((3, 1), [((2, 1), 1.0), ((2, 6), 2.0)])
    ties.add((2, 6), [((1, 6), 1.0)])
    resolved = ties.resolve()
    assert resolved[(3, 1)] == pytest.approx({(1, 1): 1.0, (1, 6): 1.5})
    with pytest.raises(ValueError):
        ties.add((2, 1), [((1, 1), 1.0)])


def test_fixed_end_resultants() -> None:
    w = np.array([0.0, 0.0, -W])
    x = np.array([1.0, 0.0, 0.0])
    force, moment = run_ccx.fixed_end(w, x, L, at_j=False)
    assert force == pytest.approx([0, 0, -W * L / 2])
    assert moment == pytest.approx([0, W * L**2 / 12, 0])  # hogging at the support


def test_parse_dat() -> None:
    text = """
                        S T E P       1

 displacements (vx,vy,vz,rx,ry,rz) for set PROBES and time  0.1000000E+01

         4  0.000000E+00  0.000000E+00 -1.000000E-03  0.000000E+00  2.000000E-04  0.000000E+00

                        S T E P       2

     E I G E N V A L U E   O U T P U T

 MODE NO    EIGENVALUE                       FREQUENCY
                           (RAD/TIME)      (CYCLES/TIME     (RAD/TIME)

      1   0.1689697E+04   0.4110593E+02   0.6542212E+01   0.0000000E+00
"""
    steps = run_ccx.parse_dat(text)
    assert run_ccx._block_set(steps[0], "displacements", "PROBES")[0][3] == -1e-3
    modal = run_ccx.modal_results(steps[1], [500.0, 500.0, 0.0])
    assert modal["periods"] == pytest.approx([2 * np.pi / 41.10593])


def test_translation(ir: dict, tmp_path: Path) -> None:
    assert [f["rigid"] for f in ir["frames"]] == [[0.2, 0.0], [0.0, 0.0]]
    assert ir["twins"] == [{"main": 2, "twin": 3, "dofs": [1, 2, 3, 4, 5, 6], "penalty": 1e13}]
    assert ir["cases"]["D"]["element"] == [[2, pytest.approx([0.0, 0.0, -W])]]
    groups = {a["code"]: a["group"] for a in ir["analyses"]}
    assert groups["D"] != groups["Modal"]  # the modal case has its own (cracked) sections
    modal = next(g for g in ir["groups"] if g["name"] == groups["Modal"])
    assert modal["frameSections"]["1"]["Iy"] == pytest.approx(IY * 0.5)
    group = next(g for g in ir["groups"] if g["name"] == groups["D"])
    deck = run_ccx.Deck(ir, group)
    inp = tmp_path / "t.inp"
    deck.write(inp, [("D", ir["cases"]["D"])], 0)
    text = inp.read_text()
    assert text.count("TYPE=U1, ELSET") == 1 and "*EQUATION" in text
    # the rigid zone's follower and the twin (6 + 6 tied DOFs), the tip mass in X and Y (2)
    assert len(deck.resolved) == 14
    # local direction 1 is SAEngine's local y; I11 = Iz, I22 = Iy
    assert f"{A:.9g},{IZ:.9g},0.,{IY:.9g}" in text


def _tip_deflection() -> float:
    """Euler-Bernoulli: a cantilever of length l = L - 0.2 fixed at the face of the rigid zone,
    the tip load and the uniform load from c = 1.8 m to the tip: P l³/(3EI) +
    w (3 l⁴ - 4 c³ l + c⁴)/(24 EI)."""
    ei, ell, c = E * IY, L - 0.2, 1.8
    return P * ell**3 / (3 * ei) + W * (3 * ell**4 - 4 * c**3 * ell + c**4) / (24 * ei)


@pytest.mark.skipif(not os.environ.get("CROSSCHECK_CCX"), reason="CalculiX not set up")
def test_ccx_cantilever(ir: dict, tmp_path: Path) -> None:
    (tmp_path / "ir.json").write_text(json.dumps(ir))
    res = run_ccx.run(ir, Path(os.environ["CROSSCHECK_CCX"]), tmp_path / "ccx", threads=1)
    tip = res["cases"]["D"]["disp"].get("4") or [0, 0, 0]
    assert -tip[2] == pytest.approx(_tip_deflection(), rel=1e-3)
    assert res["cases"]["D"]["reactions"][2] == pytest.approx(P + W * 2.0, rel=1e-5)


@pytest.mark.skipif(not os.environ.get("CROSSCHECK_PYNITE_PYTHON"), reason="PyNite not set up")
def test_pynite_cantilever(ir: dict, tmp_path: Path) -> None:
    (tmp_path / "ir.json").write_text(json.dumps(ir))
    out = tmp_path / "pynite.json"
    subprocess.run(
        [
            os.environ["CROSSCHECK_PYNITE_PYTHON"],
            "-I",
            str(HERE / "run_pynite.py"),
            "--ir",
            str(tmp_path / "ir.json"),
            "--out",
            str(out),
        ],
        check=True,
    )
    res = json.loads(out.read_text())
    tip = res["cases"]["D"]["disp"]["4"]
    assert -tip[2] == pytest.approx(_tip_deflection(), rel=1e-3)
    assert res["cases"]["D"]["reactions"][2] == pytest.approx(P + W * 2.0, rel=1e-5)
    # the tip mass moves in X and Y only: the first mode bends about local z (Iz, which the
    # modal case's override leaves as it is)
    period = 2 * np.pi * np.sqrt(500 * (L - 0.2) ** 3 / (3 * E * IZ))
    assert res["modal"]["periods"][0] == pytest.approx(period, rel=1e-3)

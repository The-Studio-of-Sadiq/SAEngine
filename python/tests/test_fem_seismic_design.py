"""Seismic design from the response spectrum (saengine.fem.seismic_design), checked by hand."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.fem import seismic_design as sd
from saengine.fem.combinations import (
    DesignCombination,
    combination_factors,
    design_combinations,
    evaluate,
    sign_patterns,
    variants,
)
from saengine.library.settings import LoadCombination, default_project_settings

# ─────────────────────────────── code values ───────────────────────────────


def test_scale_factor_is_85_percent_of_the_static_base_shear() -> None:
    # BNBC 2020 Part 6 Sec 2.5.9.4: V_rs < 0.85 V -> forces x 0.85 V / V_rs.
    assert sd.scale_factor(1000.0, 700.0) == pytest.approx(0.85 * 1000 / 700)  # 1.2143
    assert sd.scale_factor(1000.0, 850.0) == 1.0
    assert sd.scale_factor(1000.0, 900.0) == 1.0  # never scaled down
    assert sd.scale_factor(0.0, 900.0) == 1.0  # no static base shear: no scaling
    assert sd.scale_factor(1000.0, 0.0) == 1.0


def test_modal_base_shear_combines_the_modal_shears() -> None:
    # V_k = M_eff,k * Sa_k: 100 kg x 2 = 200 N and 50 kg x 4 = 200 N.
    modes = [
        {"angular_frequency": 10.0, "effective_mass": 100.0, "sa_at_period": 2.0},
        {"angular_frequency": 100.0, "effective_mass": 50.0, "sa_at_period": 4.0},
    ]
    assert sd.modal_base_shear(modes, None, "SRSS") == pytest.approx(math.hypot(200, 200))
    # Well separated modes: CQC is SRSS (rho_12 is about 1e-4 at 5 %).
    assert sd.modal_base_shear(modes, 0.05, "CQC") == pytest.approx(math.hypot(200, 200), 1e-3)
    # Equal frequencies: rho = 1, CQC adds them.
    same = [dict(m, angular_frequency=10.0) for m in modes]
    assert sd.modal_base_shear(same, 0.05, "CQC") == pytest.approx(400.0)


def test_seismic_design_category_table_6_2_18() -> None:
    assert sd.zone_of(0.20) == 2 and sd.zone_of(0.36) == 4 and sd.zone_of(None) is None
    assert sd.seismic_design_category(2, "SD", "II") == "D"  # Dhaka on soft soil
    assert sd.seismic_design_category(1, "SA", "II") == "B"
    assert sd.seismic_design_category(1, "SC", "IV") == "C"
    assert sd.seismic_design_category(2, "SA", "III") == "C"
    assert sd.orthogonal_required("D") and not sd.orthogonal_required("C")
    assert sd.orthogonal_required("B", "always") and not sd.orthogonal_required("D", "never")


def test_vertical_component_and_drift_limit() -> None:
    settings = default_project_settings("T")  # Dhaka: Z = 0.20, site class SD: S = 1.35
    # a_h = (2/3) Z S = 0.18 g; Ev = 0.5 a_h D = 0.09 D (Sec 2.5.13.2).
    assert sd.peak_ground_acceleration(settings) == pytest.approx(0.18)
    assert sd.vertical_coefficient(settings) == pytest.approx(0.09)
    # Table 6.2.21, all other structures; Δa/ρ for moment frames in Category D.
    assert sd.allowable_drift_ratio("II") == 0.020
    assert sd.allowable_drift_ratio("III") == 0.015
    assert sd.allowable_drift_ratio("IV", "D", "rcImf", 1.3) == pytest.approx(0.010 / 1.3)
    assert sd.allowable_drift_ratio("II", "D", "rcSpecialWallFrame", 1.3) == 0.020


def test_combinations_with_the_response_spectrum() -> None:
    settings = default_project_settings("T")
    options = sd.SeismicOptions()
    combos = sd.seismic_combinations(settings, options, orthogonal=True, torsion=True)
    assert [c["name"] for c in combos] == [
        "1.29D + 1.0L ± 1.0E(RS EX + 0.3EY)",
        "1.29D + 1.0L ± 1.0E(RS 0.3EX + EY)",
        "1.29D + 1.0L ± 1.0E(RS EX + 0.3EY, torsion of EY)",
        "1.29D + 1.0L ± 1.0E(RS 0.3EX + EY, torsion of EX)",
        "0.81D ± 1.0E(RS EX + 0.3EY)",
        "0.81D ± 1.0E(RS 0.3EX + EY)",
        "0.81D ± 1.0E(RS EX + 0.3EY, torsion of EY)",
        "0.81D ± 1.0E(RS 0.3EX + EY, torsion of EX)",
    ]
    # The 5 % shift in one direction at a time, either one (Sec 2.5.7.6.3): across X with
    # the full X forces (AX), or along X, which moves the 30 % Y forces only (0.3 AY).
    assert combos[0]["envelope"] == {"RX": 1.0, "RY": 0.3, "AX": 1.0}
    assert combos[1]["envelope"] == {"RX": 0.3, "RY": 1.0, "AY": 1.0}
    assert combos[2]["envelope"] == {"RX": 1.0, "RY": 0.3, "AY": 0.3}
    assert combos[3]["envelope"] == {"RX": 0.3, "RY": 1.0, "AX": 0.3}
    # Ax on the torsion case of its direction (eq. 6.2.44).
    amplified = sd.seismic_combinations(settings, options, True, True, {"X": 1.5, "Y": 1.0})
    assert amplified[0]["envelope"]["AX"] == 1.5 and amplified[3]["envelope"]["AX"] == 0.45
    assert amplified[1]["envelope"]["AY"] == 1.0
    no_torsion = sd.seismic_combinations(settings, options, True, False)
    assert [c["envelope"] for c in no_torsion[:2]] == [
        {"RX": 1.0, "RY": 0.3},
        {"RX": 0.3, "RY": 1.0},
    ]
    one_at_a_time = sd.seismic_combinations(
        settings, sd.SeismicOptions(verticalComponent=False, liveFactor=0.5), False, False
    )
    assert [c["name"] for c in one_at_a_time] == [
        "1.2D + 0.5L ± 1.0E(RS EX)",
        "1.2D + 0.5L ± 1.0E(RS EY)",
        "0.9D ± 1.0E(RS EX)",
        "0.9D ± 1.0E(RS EY)",
    ]
    assert one_at_a_time[1]["envelope"] == {"RY": 1.0}
    # The design combination: D on D and SD; F follows D above 1.0 (LoadCombination).
    c = DesignCombination.from_json(combos[0])
    assert c.factors == {"D": 1.29, "SD": 1.29, "L": 1.0, "F": 1.29}
    assert DesignCombination.from_json(combos[4], {"D", "SD"}).factors == {"D": 0.81, "SD": 0.81}


# ─────────────────────────────── the combination evaluator ───────────────────────────────


def test_static_combinations_evaluate_as_before() -> None:
    combination = LoadCombination(name="1.2D + 1.6L", D=1.2, L=1.6)
    design = DesignCombination.of(combination, {"D", "SD", "L"})  # no F results
    assert design.factors == combination_factors(combination, {"D", "SD", "L"})
    assert not design.has_envelope
    static = {"D": np.array([1.0, 2.0]), "SD": np.array([0.5, 0.0]), "L": np.array([1.0, -1.0])}
    (name, value), *more = variants(design, static)
    assert name == "1.2D + 1.6L" and not more
    np.testing.assert_allclose(value, [1.2 * 1.5 + 1.6, 1.2 * 2 - 1.6])


def test_orthogonal_envelope_term_at_a_section() -> None:
    # Section forces N, Vy, Vz, T, My, Mz [N, N·m] of one station.
    static = {
        "D": np.array([-100e3, 2e3, 0.0, 0.0, 10e3, -5e3]),
        "SD": np.zeros(6),
        "L": np.array([-40e3, 1e3, 0.0, 0.0, 4e3, -2e3]),
    }
    envelope = {
        "RX": np.array([20e3, 1e3, 8e3, 0.5e3, 30e3, 2e3]),
        "RY": np.array([10e3, 6e3, 1e3, 0.5e3, 3e3, 25e3]),
    }
    combination = DesignCombination(
        "1.2D + 1.0L ± (EX + 0.3EY)", {"D": 1.2, "SD": 1.2, "L": 1.0}, {"RX": 1.0, "RY": 0.3}
    )
    s, e = evaluate(combination, static, envelope)
    # S = 1.2 D + L; E = RX + 0.3 RY (peaks add).
    np.testing.assert_allclose(s, [-160e3, 3.4e3, 0, 0, 16e3, -8e3])
    np.testing.assert_allclose(e, [23e3, 2.8e3, 8.3e3, 0.65e3, 30.9e3, 9.5e3])
    named = dict(variants(combination, static, envelope))
    assert len(named) == 8
    # +N +My -Mz: N = -160 + 23, Vz with My (+), Vy with Mz (-), T with N.
    corner = named["1.2D + 1.0L ± (EX + 0.3EY) [+N +My −Mz]"]
    np.testing.assert_allclose(
        corner, [-137e3, 3.4e3 - 2.8e3, 8.3e3, 0.65e3, 16e3 + 30.9e3, -8e3 - 9.5e3]
    )
    # The two plus-minus patterns are S + E and S - E.
    pm = variants(combination, static, envelope, signs="plusMinus")
    np.testing.assert_allclose(pm[0][1], s + e)
    np.testing.assert_allclose(pm[1][1], s - e)
    # Envelope values are peaks: a negative entry counts by its size.
    flipped = {k: -v for k, v in envelope.items()}
    np.testing.assert_allclose(evaluate(combination, static, flipped)[1], e)
    with pytest.raises(KeyError):
        evaluate(combination, static, {"RX": envelope["RX"]})


def test_sign_patterns_follow_their_groups() -> None:
    labels = [label for label, _ in sign_patterns("frame")]
    assert len(set(labels)) == 8 and labels[0] == "+N +My +Mz"
    _, reaction = sign_patterns("reaction")[1]  # +Fz +Mx -My
    np.testing.assert_allclose(reaction, [-1, 1, 1, 1, -1, 1])
    _, ends = sign_patterns("ends")[3]  # +N -My -Mz at both ends
    np.testing.assert_allclose(ends, [1, -1, -1, 1, -1, -1] * 2)
    assert len(sign_patterns("shell")) == 8


def test_design_combinations_replace_the_static_earthquake_ones() -> None:
    settings = default_project_settings("T")
    assert [c.name for c in design_combinations(settings)] == [
        c.name for c in settings.combinations
    ]
    summary = {
        "available": True,
        "combinations": sd.seismic_combinations(settings, sd.SeismicOptions(), True, True),
    }
    chosen = design_combinations(settings, None, summary)
    static = [c.name for c in settings.combinations if not (c.EX or c.EY)]
    assert [c.name for c in chosen[: len(static)]] == static
    assert [c.name for c in chosen[len(static) :]] == [c["name"] for c in summary["combinations"]]
    assert not any(c.has_envelope for c in chosen[: len(static)])
    # Not available: the project's combinations, unchanged.
    assert len(design_combinations(settings, None, {"available": False})) == len(
        settings.combinations
    )


def test_design_demands_expand_the_rs_combinations_into_sign_patterns(monkeypatch) -> None:
    """:func:`sd.design_demands` with a stand-in for ``check._demands``: the EX combination is
    replaced, the RS one gets 8 patterns of S ± E (E = RX + 0.3RY), sway = ±E."""
    from types import SimpleNamespace

    settings = default_project_settings("T").model_copy(
        update={
            "combinations": [
                LoadCombination(name="1.4D", D=1.4),
                LoadCombination(name="1.2D + 1.0E", D=1.2, L=1.0, EX=1.0),
            ]
        }
    )
    rs_name = "1.2D + 1.0L ± 1.0E(RS EX + 0.3EY)"
    summary = {
        "schema": sd.SUMMARY_SCHEMA,
        "available": True,
        "signs": "corners",
        "scale": {"x": 2.0, "y": 1.5},
        "combinations": [
            {"name": rs_name, "loads": {"D": 1.2, "L": 1.0}, "envelope": {"RX": 1.0, "RY": 0.3}}
        ],
    }
    seen = {}
    gravity = np.array([[-100e3, 1e3, 0, 0, 5e3, -2e3]])

    def base(project, out_dir, trial, extra=None):
        seen["names"] = [c.name for c in trial.combinations]
        piece = SimpleNamespace(
            id=7,
            forces=[1.4 * gravity, 1.2 * gravity],
            sway=[np.zeros((1, 6)), np.zeros((1, 6))],
            sustained=[1.4 * gravity, 1.2 * gravity],
        )
        if extra is not None:
            extra["factors"] = [{"D": 1.4}, {"D": 1.2, "L": 1.0}]
            extra["lateralDisplacements"] = [{}, {}]
        return [c.name for c in trial.combinations], {"C1": [piece]}, [], {}

    env = {
        "RX": np.array([[10e3, 2e3, 4e3, 0, 20e3, 1e3]]),
        "RY": np.array([[5e3, 3e3, 1e3, 0, 2e3, 10e3]]),
    }
    fake = SimpleNamespace(
        parts=["RX", "RY"],
        frame=lambda element: env,
        shell=lambda i: {},
        displacement=lambda n: {"RX": np.array([0.01, 0, 0, 0, 0, 0])},
    )
    monkeypatch.setattr(sd, "load_seismic_forces", lambda out: fake)
    monkeypatch.setattr("saengine.fem.display._elements", lambda project: [SimpleNamespace(id=7)])
    project = {"nodes": [{"id": 3, "coords": [0, 0, 3]}]}
    extra: dict = {}
    names, pieces, notes, _ = sd.design_demands(project, "out", settings, extra, summary, base)
    # The static EX combination is dropped; the RS one stands in with its static loads only.
    assert seen["names"] == ["1.4D", rs_name]
    assert names[0] == "1.4D" and len(names) == 1 + 8
    assert names[1] == f"{rs_name} [+N +My +Mz]"
    piece = pieces["C1"][0]
    e = env["RX"] + 0.3 * env["RY"]  # [11.5e3, 2.9e3, 4.3e3, 0, 20.6e3, 4e3]
    np.testing.assert_allclose(piece.forces[0], 1.4 * gravity)
    np.testing.assert_allclose(piece.forces[1], 1.2 * gravity + e)
    # Pattern 8: -N -My -Mz.
    np.testing.assert_allclose(piece.forces[8], 1.2 * gravity - e)
    np.testing.assert_allclose(piece.sway[8], -e)
    np.testing.assert_allclose(piece.sustained[8], 1.2 * gravity)
    assert len(extra["factors"]) == 9 and extra["lateralDisplacements"][0] == {}
    np.testing.assert_allclose(extra["lateralDisplacements"][3][3], [0.01, 0, 0, 0, 0, 0])
    assert "scaled by 2.000 (X) and 1.500 (Y)" in notes[-1]
    # Without a summary: exactly the base.
    monkeypatch.setattr(sd, "load_summary", lambda out: None)
    names2, *_ = sd.design_demands(project, "out", settings, None, None, base)
    assert names2 == ["1.4D", "1.2D + 1.0E"]


# ─────────────────────────────── torsion and drift ───────────────────────────────


def _square_level(force: float = 40e3) -> dict:
    """Four nodes of a 6 m x 4 m floor at 3 m, each with a quarter of the storey force EX, and
    a base node below each."""
    corners = [(0, 0), (6, 0), (6, 4), (0, 4)]
    nodes = [
        {"id": i + 1, "coords": [x, y, 0.0], "mass": [0.0] * 6} for i, (x, y) in enumerate(corners)
    ] + [
        {"id": i + 5, "coords": [x, y, 3.0], "mass": [1e4, 1e4, 0, 0, 0, 0]}
        for i, (x, y) in enumerate(corners)
    ]
    ex = [{"node_id": i, "forces": [force / 4, 0, 0, 0, 0, 0]} for i in range(5, 9)]
    ey = [{"node_id": i, "forces": [0, force / 4, 0, 0, 0, 0]} for i in range(5, 9)]
    return {
        "nodes": nodes,
        "load_patterns": [
            {"id": 7, "name": "EX", "nodal_loads": ex},
            {"id": 8, "name": "EY", "nodal_loads": ey},
        ],
    }


def test_accidental_torsion_is_5_percent_of_the_floor_across_the_force() -> None:
    project = _square_level()
    assert sd.static_storey_forces(project, "EX")[0]["force"] == pytest.approx(40e3)
    nodal, levels = sd.torsion_loads(project, "EX")
    # M_ta = 0.05 x L x F, L = 4 m across X: 0.05 x 4 x 40 kN = 8 kN·m.
    assert levels == [{"z": 3.0, "force": 40e3, "L": 4.0, "moment": pytest.approx(8e3)}]
    coords = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
    forces = np.array([load["forces"][:2] for load in nodal])
    assert np.allclose(forces.sum(axis=0), 0, atol=1e-9)  # no net force
    moment = sum(
        (coords[load["node_id"]][0] - 3) * load["forces"][1]
        - (coords[load["node_id"]][1] - 2) * load["forces"][0]
        for load in nodal
    )
    assert moment == pytest.approx(8e3)
    # Across Y the floor is 6 m: 12 kN·m.
    assert sd.torsion_loads(project, "EY")[1][0]["moment"] == pytest.approx(12e3)


def test_design_drift_is_cd_over_i_times_the_modal_drift() -> None:
    project = _square_level()
    # Two modes in X: signed peak displacements of the floor (the bases do not move).
    floor = {n: np.array([0.010, 0.0, 0.0]) for n in range(5, 9)}
    second = {n: np.array([-0.002, 0.0, 0.0]) for n in range(5, 9)}
    base = {n: np.zeros(3) for n in range(1, 5)}
    spectra = {
        "X": {
            "rule": "SRSS",
            "damping": None,
            "modes": [{"angular_frequency": 10.0}, {"angular_frequency": 40.0}],
            "peaks": [floor | base, second | base],
        }
    }
    rows = sd.storey_drifts(project, spectra, [0.0, 3.0], 4.5 / 1.25, 0.015)
    (row,) = rows
    elastic = math.hypot(0.010, 0.002)  # SRSS of the modal drifts: 10.198 mm
    assert row["elasticDrift"] == pytest.approx(elastic)
    assert row["designDrift"] == pytest.approx(4.5 / 1.25 * elastic)  # Cd/I = 3.6: 36.71 mm
    assert row["ratio"] == pytest.approx(4.5 / 1.25 * elastic / 3.0)  # 1.224 %
    assert row["ok"] and row["allowableRatio"] == 0.015
    assert sd.drift_rows({"drift": rows})[0][4] == "36.71"


class _Twist:
    """A stand-in for the static results of a torsion case: signed node displacements."""

    def __init__(self, ux: dict[int, float]) -> None:
        self.node_disp = {n: [[u, 0, 0, 0, 0, 0]] for n, u in ux.items()}


def _one_mode_x(drift: float) -> dict:
    floor = {n: np.array([drift, 0.0, 0.0]) for n in range(5, 9)}
    base = {n: np.zeros(3) for n in range(1, 5)}
    return {
        "X": {
            "rule": "SRSS",
            "damping": None,
            "modes": [
                {
                    "angular_frequency": 10.0,
                    "mode_number": 1,
                    "effective_mass": 4e4,
                    "sa_at_period": 1.0,
                    "mass_ratio": 1.0,
                }
            ],
            "peaks": [floor | base],
        }
    }


def test_torsional_irregularity_and_ax_by_hand() -> None:
    project = _square_level()
    # RS: the floor moves 10 mm in X everywhere; the torsion case of EX twists it +3 mm at the
    # y = 4 m edge (nodes 7, 8) and -3 mm at the y = 0 edge (nodes 5, 6).
    twist = _Twist({5: -0.003, 6: -0.003, 7: 0.003, 8: 0.003})
    (row,) = sd.torsional_irregularity(
        project, _one_mode_x(0.010), [0.0, 3.0], {"X": 1.0}, {"AX": twist}
    )
    # Ends 7 and 13 mm: Δmax / Δavg = 13 / 10 = 1.3 > 1.2, irregular, not extreme (Sec
    # 2.5.5.3.1(i)); Ax = (13 / (1.2 x 10))² = 1.1736 (eq. 6.2.44).
    assert row["driftMax"] == pytest.approx(0.013) and row["driftAvg"] == pytest.approx(0.010)
    assert row["ratio"] == pytest.approx(1.3) and row["irregular"] and not row["extreme"]
    assert row["amplification"] == pytest.approx((13 / 12) ** 2)
    rows = [row]
    assert sd.torsion_amplification(rows, "D")["X"] == pytest.approx(1.17361, rel=1e-5)
    assert sd.torsion_amplification(rows, "D")["Y"] == 1.0
    assert sd.torsion_amplification(rows, "B") == {"X": 1.0, "Y": 1.0}
    assert sd.torsion_amplification(rows, "D", torsion=False)["X"] == 1.0
    # Scaled to the design force level (x 2): ends 17 and 23 mm, 23 / 20 = 1.15, regular.
    (scaled,) = sd.torsional_irregularity(
        project, _one_mode_x(0.010), [0.0, 3.0], {"X": 2.0}, {"AX": twist}
    )
    assert scaled["ratio"] == pytest.approx(1.15) and not scaled["irregular"]
    assert sd.torsion_amplification([scaled], "D")["X"] == 1.0
    # Extreme: torsion 5 mm, 15 / 10 = 1.5; Ax = (15 / 12)² = 1.5625.
    big = _Twist({5: -0.005, 6: -0.005, 7: 0.005, 8: 0.005})
    (extreme,) = sd.torsional_irregularity(
        project, _one_mode_x(0.010), [0.0, 3.0], None, {"AX": big}
    )
    assert extreme["extreme"] and extreme["amplification"] == pytest.approx(1.5625)
    # The design drift takes Ax on the torsion drift: Cd/I x (10 + 1.1736 x 3) mm.
    (drift,) = sd.storey_drifts(
        project, _one_mode_x(0.010), [0.0, 3.0], 3.6, 0.02, {"AX": twist}, {"X": (13 / 12) ** 2}
    )
    assert drift["designDrift"] == pytest.approx(3.6 * (0.010 + (13 / 12) ** 2 * 0.003))


def test_a_stale_rs_design_folder_is_removed_before_a_failing_rerun(tmp_path, monkeypatch) -> None:
    out = tmp_path / "results"
    folder = out / sd.RS_FOLDER
    folder.mkdir(parents=True)
    (folder / sd.SUMMARY_FILE).write_text(
        json.dumps({"schema": sd.SUMMARY_SCHEMA, "available": True, "run": {"stamp": "old"}}),
        encoding="utf-8",
    )
    (out / "manifest.json").write_text("{}", encoding="utf-8")
    project = _square_level()
    path = tmp_path / "model.osmodel"
    path.write_text(json.dumps(project), encoding="utf-8")
    monkeypatch.setattr(sd, "_spectra", lambda out_dir: _one_mode_x(0.01))

    def fail(*args, **kwargs):
        raise ValueError("the response spectrum force run failed")

    monkeypatch.setattr(sd, "_run", fail)
    with pytest.raises(ValueError):
        sd.seismic_design(out, path, default_project_settings("T"))
    assert sd.load_summary(out) is None and sd.load_seismic_forces(out) is None


def _rs_model(tmp_path: Path) -> tuple[Path, Path]:
    """A results folder with an old rs-design summary and a model with RS cases in X and Y."""
    out = tmp_path / "results"
    folder = out / sd.RS_FOLDER
    folder.mkdir(parents=True)
    (folder / sd.SUMMARY_FILE).write_text(
        json.dumps({"schema": sd.SUMMARY_SCHEMA, "available": True, "run": {"stamp": "old"}}),
        encoding="utf-8",
    )
    (out / "manifest.json").write_text('{"cases": []}', encoding="utf-8")
    project = _square_level()
    project["analyses"] = [
        {"id": 1, "name": "M", "type": "Modal"},
        {"id": 2, "name": "RX", "type": "ResponseSpectrum", "direction": 1},
        {"id": 3, "name": "RY", "type": "ResponseSpectrum", "direction": 2},
    ]
    path = tmp_path / "model.osmodel"
    path.write_text(json.dumps(project), encoding="utf-8")
    return out, path


def test_unfinished_results_make_no_rs_run(tmp_path, monkeypatch) -> None:
    """The app calls seismic_design while the analysis runs: a manifest with RX but not yet RY
    (the model has both) gives no run and no summary, and the old summary goes, so the design
    uses the static EX, EY rather than an RS design without EY."""
    out, path = _rs_model(tmp_path)
    monkeypatch.setattr(sd, "_spectra", lambda out_dir: _one_mode_x(0.01))
    ran = []
    monkeypatch.setattr(sd, "_run", lambda *a, **k: ran.append(1))
    summary = sd.seismic_design(out, path, default_project_settings("T"))
    assert not summary["available"] and "in Y has no results" in summary["notes"][0]
    assert not ran and sd.load_summary(out) is None
    assert sd.expected_axes(path) == {"X", "Y"}


def test_results_changing_while_read_make_no_rs_run(tmp_path, monkeypatch) -> None:
    """The stamp is taken before the spectra are read: a manifest rewritten meanwhile (the
    runner adding a case) is not stamped as the one the spectra came from."""
    out, path = _rs_model(tmp_path)
    both = {**_one_mode_x(0.01), "Y": _one_mode_x(0.01)["X"]}

    def spectra(out_dir):
        (out / "manifest.json").write_text('{"cases": [1]}', encoding="utf-8")
        return both

    monkeypatch.setattr(sd, "_spectra", spectra)
    ran = []
    monkeypatch.setattr(sd, "_run", lambda *a, **k: ran.append(1))
    summary = sd.seismic_design(out, path, default_project_settings("T"))
    assert not summary["available"] and "changed while they were read" in summary["notes"][0]
    assert not ran and sd.load_summary(out) is None


def test_design_demands_never_drop_a_spectrum_part_silently(monkeypatch) -> None:
    """A modal-force run without RY (or none at all) for a summary whose combinations need it:
    the design is the static one, with a note saying why."""
    from types import SimpleNamespace

    settings = default_project_settings("T")
    summary = {
        "schema": sd.SUMMARY_SCHEMA,
        "available": True,
        "signs": "corners",
        "scale": {"x": 2.0, "y": 1.5},
        "combinations": [{"name": "E", "loads": {"D": 1.2}, "envelope": {"RX": 0.3, "RY": 1.0}}],
    }

    def base(project, out_dir, trial, extra=None):
        return ["static"], {}, [], {}

    monkeypatch.setattr(sd, "load_seismic_forces", lambda out: SimpleNamespace(parts=["RX"]))
    names, _, notes, _ = sd.design_demands({}, "out", settings, {}, summary, base)
    assert names == ["static"] and "has no RY" in notes[-1]
    monkeypatch.setattr(sd, "load_seismic_forces", lambda out: None)
    names, _, notes, _ = sd.design_demands({}, "out", settings, {}, summary, base)
    assert names == ["static"] and "response spectrum design is not used" in notes[-1]


def test_storey_shear_combines_the_modal_storey_shears() -> None:
    """SeismicForces.storey_shear: per mode the loads above the cut, SRSS over two modes,
    times the scale: modes of 30 and 40 kN above the cut give 50 kN, x 2 = 100 kN."""
    forces = sd.SeismicForces(
        scale={"X": 2.0, "Y": 1.0},
        rules={"RX": ("SRSS", None, [10.0, 30.0])},
        modal={"RX": [None, None]},
        torsion={},
        loads={
            "RX": [
                {5: np.array([20e3, 0, 0]), 6: np.array([10e3, 0, 0]), 1: np.array([9e9, 0, 0])},
                {5: np.array([-40e3, 0, 0])},
            ]
        },
        heights={1: 0.0, 5: 3.0, 6: 3.0},
    )
    np.testing.assert_allclose(forces.storey_shear(1.5)["RX"], [100e3, 0, 0])
    np.testing.assert_allclose(forces.storey_shear(3.5)["RX"], [0, 0, 0])


# ─────────────────────────────── a derived bay, run ───────────────────────────────


def _run_bay(root: Path, settings=None, transform=None):
    from test_fem_derive import OBJECTS, PLAN, SETTINGS

    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate

    settings = settings or SETTINGS
    folder = root / "08 FEM"
    folder.mkdir(parents=True)
    d = derive_fem(generate(PLAN, "s"), OBJECTS, default_material_library(), settings, None, folder)
    if transform is not None:
        transform(d.project)
    model = folder / "model.osmodel"
    model.write_text(json.dumps(d.project), encoding="utf-8")
    out = folder / "model.results"
    ids = [str(a["id"]) for a in d.project["analyses"]]
    run = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model)]
        + ["--cases", *ids, "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    return d, model, out, settings


@pytest.fixture(scope="module")
def bay(tmp_path_factory: pytest.TempPathFactory):
    d, model, out, settings = _run_bay(tmp_path_factory.mktemp("rs-bay"))
    summary = sd.seismic_design(out, model, settings)
    return d, model, out, settings, summary


def test_bay_scale_and_modal_forces_balance_the_base_shear(bay) -> None:
    from opensees_studio.services.result_store import load_manifest, load_results

    d, _, out, _, summary = bay
    assert summary["available"] and summary["category"] == "D" and summary["orthogonal"]
    scale = summary["scale"]
    assert scale["fraction"] == 0.85
    for axis in ("x", "y"):
        expected = sd.scale_factor(scale["vStatic"][axis], scale["vDynamic"][axis])
        assert scale[axis] == pytest.approx(expected)
    # The equivalent static base shear is the derivation's.
    assert scale["vStatic"]["x"] == pytest.approx(d.summary["base_shear_kN"], rel=1e-6)

    # The modal-force cases: each mode's base reaction is its M_eff·Sa, and the column shears
    # combined over the modes add up to V_rs (one storey of four equal columns).
    forces = sd.load_seismic_forces(out)
    assert forces is not None and set(forces.parts) == {"RX", "RY", "AX", "AY"}
    folder = out / sd.RS_FOLDER / "results"
    run = summary["run"]["parts"]["RX"]
    manifest = {int(e["case_id"]): e for e in load_manifest(folder)["cases"]}
    rs = sd._spectra(out)["X"]
    modes = [m for m in rs["modes"] if m["angular_frequency"] > 0]
    for case_id, omega in zip(run["cases"], run["omegas"], strict=True):
        mode = next(m for m in modes if m["angular_frequency"] == omega)
        result = load_results(manifest[case_id], folder)
        shear = -sum(float(np.asarray(r[-1])[0]) for r in result.node_reaction.values())
        assert abs(shear) == pytest.approx(mode["effective_mass"] * mode["sa_at_period"], rel=1e-4)
    supports = [n["id"] for n in d.project["nodes"] if all(n["restraint"])]
    total = sum(forces.reaction(n)["RX"][0] for n in supports)
    v_rs = scale["vDynamic"]["x"] * 1e3 * scale["x"]
    # Peaks of each support's shear: their sum is the base shear when the columns move alike.
    assert total == pytest.approx(v_rs, rel=1e-2)
    # The storey shear just above the base, the modal shears combined: the scaled V_rs.
    assert forces.storey_shear(0.01)["RX"][0] == pytest.approx(v_rs, rel=1e-3)

    # The design combinations of the bay: ±(EX + 0.3EY) with the vertical component.
    names = [c["name"] for c in summary["combinations"]]
    assert names[0] == "1.29D + 1.0L ± 1.0E(RS EX + 0.3EY)"
    assert all(d_["ok"] for d_ in summary["drift"])
    assert (out / sd.RS_FOLDER / sd.SUMMARY_FILE).is_file()


def test_bay_column_envelope_and_combination_results(bay) -> None:
    from saengine.fem.combinations import combination_results
    from saengine.fem.display import _elements

    d, model, out, settings, summary = bay
    forces = sd.load_seismic_forces(out)
    column = next(e for e in _elements(d.project) if e.name.startswith("C"))
    envelope = forces.frame(column)
    assert envelope["RX"].shape == (11, 6) and np.all(envelope["RX"] >= 0)
    # The column base moment of the scaled RS: about its shear times the height to the point
    # of contraflexure, and the X earthquake moves it in one plane only.
    vx = max(envelope["RX"][0, 1], envelope["RX"][0, 2])
    v_rs = summary["scale"]["vDynamic"]["x"] * 1e3 * summary["scale"]["x"]
    assert vx == pytest.approx(v_rs / 4, rel=1e-2)
    entries = combination_results(out, d.project, settings, seismic=summary)
    rs_entries = [e for e in entries if e["caseId"] > 3000]
    assert [e["caseName"] for e in rs_entries] == names_of(summary)
    rows = rs_entries[0]["tables"][0]["rows"]
    assert all(row[3] <= row[4] for row in rows)
    # Without the summary the entries are those of before.
    assert all(e["caseId"] < 3000 for e in combination_results(out, d.project, settings))
    # A second call reuses the run (same stamp).
    again = sd.seismic_design(out, model, settings)
    assert again["run"]["stamp"] == summary["run"]["stamp"]


def names_of(summary: dict) -> list[str]:
    return [c["name"] for c in summary["combinations"]]


def test_without_response_spectrum_nothing_is_available(tmp_path: Path) -> None:
    from test_fem_derive import SETTINGS

    settings = SETTINGS.model_copy(
        update={"analysis": SETTINGS.analysis.model_copy(update={"responseSpectrum": False})}
    )
    _, model, out, settings = _run_bay(tmp_path, settings)
    summary = sd.seismic_design(out, model, settings)
    assert not summary["available"] and "Response spectrum" in summary["notes"][0]
    assert sd.load_seismic_forces(out) is None


# ── the modal-force cases are solved on the RS case's own stiffness ──


def _crack_lateral(project: dict) -> None:
    """Stream B's crackedFor="lateral": E x 0.35 on the modal and RS cases only."""
    cracked = [{**s, "E": s["E"] * 0.35} for s in project["sections"] if "E" in s]
    for a in project["analyses"]:
        if a["type"] in ("Modal", "ResponseSpectrum"):
            a["section_overrides"] = json.loads(json.dumps(cracked))


def _preload_pdelta(project: dict) -> None:
    """Stream B's secondOrder="pDelta": PDelta columns, the modal case preloaded by gravity."""
    gravity = next(
        a for a in project["analyses"] if a["type"] == "Static" and a["name"].startswith("D")
    )
    preload = {
        **gravity,
        "id": max(a["id"] for a in project["analyses"]) + 1,
        "name": "PD: gravity preload",
        "algorithm": "Newton",
    }
    preload.pop("preload_case_ids", None)
    project["analyses"].append(preload)
    for a in project["analyses"]:
        if a["type"] == "Modal":
            a["preload_case_ids"] = [preload["id"]]
    for e in project["elements"]:
        if e.get("geom_transf") == "Linear":
            e["geom_transf"] = "PDelta"


def test_modal_force_model_copies_the_overrides_and_the_preload() -> None:
    """Synthetic: the generated cases carry the RS case's overrides and its modal case's
    preload; the preload case, its pattern and time series keep their ids; nothing collides."""
    override = {"id": 1, "type": "Elastic", "E": 1.0}
    project = {
        "nodes": [{"id": 1, "coords": [0, 0, 3], "mass": [2.0, 2.0, 0, 0, 0, 0]}],
        "sections": [{"id": 1, "type": "Elastic", "E": 3.0}],
        "time_series": [{"id": 7, "type": "Constant"}, {"id": 8, "type": "Linear"}],
        "load_patterns": [
            {"id": 4, "name": "D", "time_series_id": 7},
            {"id": 9, "name": "L", "time_series_id": 8},
        ],
        "analyses": [
            {"id": 3, "type": "Static", "name": "PD", "pattern_ids": [4]},
            {"id": 5, "type": "Modal", "name": "M", "preload_case_ids": [3]},
            {
                "id": 6,
                "type": "ResponseSpectrum",
                "name": "RX",
                "modal_case_id": 5,
                "section_overrides": [override],
            },
        ],
    }
    spectra = {
        "X": {
            "case_id": 6,
            "modes": [{"angular_frequency": 2.0, "mode_number": 1}],
            "peaks": [{1: [0.5, 0, 0, 0, 0, 0]}],
        }
    }
    model, cases = sd.modal_force_model(project, spectra, torsion=False)
    assert [c["part"] for c in cases] == ["RX"]
    generated = next(a for a in model["analyses"] if a["id"] == cases[0]["id"])
    assert generated["section_overrides"] == [override]
    assert generated["preload_case_ids"] == [3]
    assert cases[0]["id"] not in (3,)
    assert {a["id"] for a in model["analyses"]} == {3, cases[0]["id"]}
    assert {p["id"] for p in model["load_patterns"]} == {4, generated["pattern_ids"][0]}
    assert generated["pattern_ids"][0] != 4
    series = {s["id"]: s for s in model["time_series"]}
    # The preload's series kept; the L pattern's is not, the generated Linear one follows.
    assert series[7] == {"id": 7, "type": "Constant"} and len(series) == 2
    pattern = next(p for p in model["load_patterns"] if p["id"] == generated["pattern_ids"][0])
    assert series[pattern["time_series_id"]]["type"] == "Linear"
    # ω²·m·u = 4 x 2 x 0.5 = 4 N
    assert pattern["nodal_loads"][0]["forces"][:3] == [4.0, 0.0, 0.0]
    # Without overrides or preload, the cases are plain (as before).
    plain = json.loads(json.dumps(project))
    plain["analyses"][1].pop("preload_case_ids")
    plain["analyses"][2].pop("section_overrides")
    model, cases = sd.modal_force_model(plain, spectra, torsion=False)
    (only,) = model["analyses"]
    assert "section_overrides" not in only and "preload_case_ids" not in only


def _roof_ratio(out: Path, project: dict, summary: dict) -> float:
    """The modal-force run's roof Ux peak over the RS case's own peak (both scaled)."""
    forces = sd.load_seismic_forces(out)
    top = max(project["nodes"], key=lambda n: (n["coords"][2], n["id"]))["id"]
    rs_peak = float(np.asarray(sd._spectra(out)["X"]["combined"][top])[0]) * summary["scale"]["x"]
    return forces.displacement(top)["RX"][0] / rs_peak


@pytest.mark.parametrize("transform", [_crack_lateral, _preload_pdelta], ids=["cracked", "pDelta"])
def test_bay_modal_forces_use_the_spectrum_stiffness(tmp_path: Path, transform) -> None:
    """With cracked lateral sections (0.35 E) or a P-Delta preload of the modal case, the
    modal-force run reproduces the RS case's own peak displacement (it ran on gross,
    first-order sections before: ratio 0.35 with the cracked sections)."""
    d, model, out, settings = _run_bay(tmp_path, transform=transform)
    summary = sd.seismic_design(out, model, settings)
    # Without the fix: 0.350 (cracked), 0.99878 (P-Delta of this low bay): hence the tight 1e-5.
    assert _roof_ratio(out, d.project, summary) == pytest.approx(1.0, rel=1e-5)
    # The base shear still balances.
    forces = sd.load_seismic_forces(out)
    supports = [n["id"] for n in d.project["nodes"] if all(n["restraint"])]
    total = sum(forces.reaction(n)["RX"][0] for n in supports)
    v_rs = summary["scale"]["vDynamic"]["x"] * 1e3 * summary["scale"]["x"]
    assert total == pytest.approx(v_rs, rel=1e-2)

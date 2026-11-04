"""Alpha 9 P5: nonlinear time history in design, record scaling and spectral matching.

Values pinned with their clauses (the packs' VERIFY.md lists them for checking):

- ASCE 7-22 Ch 16 (aci318-asce7-22): MCER target 1.5 x the design spectrum with R = 1, I = 1;
  at least 11 records (Sec 16.2.2); 0.2 Tmin to 2.0 Tmax (Sec 16.2.1); the mean
  maximum-direction spectrum at least 90 % (scaled, Sec 16.2.3.2) or 110 % (matched, Sec
  16.2.3.3); the mean response (Sec 16.4.1); drift 1.5 x the allowable (Sec 16.4.1.2).
- EN 1998-1 (eurocodes): at least 3 accelerograms, 90 % of the elastic spectrum over 0.2T1 to
  2T1 (Sec 3.2.3.1.2); the mean from 7 analyses (Sec 4.3.3.4.3(3)).
"""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from opensees_studio.core.target_spectrum import TargetSpectrum

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.fem import records as rec
from saengine.fem import spectral_matching as sm

US, EU = "aci318-asce7-22", "eurocodes"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def _synthetic(seed: int, seconds: float = 12.0, dt: float = 0.01) -> tuple[float, np.ndarray]:
    """A synthetic record [g]: white noise under a smooth envelope."""
    rng = np.random.default_rng(seed)
    t = np.arange(0.0, seconds, dt)
    envelope = (t / 2.0) ** 2 * np.exp(-t / 2.0) / np.exp(-1.0)
    return dt, 0.15 * envelope * rng.normal(size=t.size)


def _target() -> TargetSpectrum:
    periods = np.geomspace(0.01, 10.0, 120)
    sa = np.where(periods < 0.5, 0.8, 0.4 / periods)
    return TargetSpectrum(id=1, kind="user", periods=list(periods), sa=list(sa), damping_ratio=0.05)


# ─────────────────────────────── the packs ───────────────────────────────


def test_us_and_eu_pack_values() -> None:
    us = registry.load(US)
    th = us.table("seismic").timeHistory
    target = th.targets["nonlinear"]
    assert (target.R, target.I, target.factor) == (1.0, 1.0, 1.5)  # MCER, Sec 16.2.1
    assert target.minimumRecords == 11  # Sec 16.2.2
    assert (th.periodLower, th.periodUpper, th.periodBasis) == (0.2, 2.0, "bounds")
    assert (target.pairRatio, target.matchedRatio) == (0.9, 1.1)  # Sec 16.2.3.2, 16.2.3.3
    assert th.pairCombination == "maxDirection"
    nh = us.table("nonlinearHistory")
    assert nh.procedure.meanFrom == 1 and nh.drift.limitFactor == 1.5  # Sec 16.4.1, 16.4.1.2
    assert nh.acceptance.method == "hingeRotation" and nh.acceptance.performanceLevel == "CP"
    assert [a.factor for a in nh.forceControlled.actions] == [2.0, 1.5]
    eu = registry.load(EU)
    th = eu.table("seismic").timeHistory
    assert (th.minimumRecords, th.periodLower, th.periodUpper) == (3, 0.2, 2.0)
    assert (th.singleRatio, th.pairRatio, th.meanFrom) == (0.9, 0.9, 7)
    assert th.targets["nonlinear"].spectrum == "elastic"
    assert eu.table("nonlinearHistory").acceptance.performanceLevel == "SD"


def test_bnbc_keeps_its_rules() -> None:
    th = registry.load("bnbc2020").table("seismic").timeHistory
    assert th.pairCombination == "srss" and th.periodBasis == "governing"
    assert th.matching is None
    assert th.targets["nonlinear"].factor == 1.0
    nh = registry.load("bnbc2020").table("nonlinearHistory")
    assert nh.acceptance.method == "fibreStrain" and nh.forceControlled is None
    assert nh.procedure.damping is None and nh.procedure.unacceptableResponses == {}


# ─────────────────────────────── spectra and scaling ───────────────────────────────


def test_filter_spectrum_equals_the_recurrence() -> None:
    from opensees_studio.core.response_spectrum import response_spectrum

    dt, a = _synthetic(1)
    periods = np.geomspace(0.05, 4.0, 25)
    ours = sm.spectrum(dt, a, periods, 0.05)
    theirs = response_spectrum(dt, a, 0.05, periods=periods).sa
    assert np.allclose(ours, theirs, rtol=1e-9)


def test_max_direction_spectrum_between_components_and_srss() -> None:
    first, second = _synthetic(2), _synthetic(3)
    periods = np.geomspace(0.1, 3.0, 20)
    rotd = sm.pair_spectrum(first, second, periods, 0.05, "maxDirection")
    s1 = sm.spectrum(*first, periods, 0.05)
    s2 = sm.spectrum(*second, periods, 0.05)
    assert np.all(rotd >= np.maximum(s1, s2) * (1 - 1e-9))
    assert np.all(rotd <= np.sqrt(s1**2 + s2**2) * (1 + 1e-9))


def test_scaling_factors_meet_the_us_criterion() -> None:
    """Eleven synthetic pairs scaled to 90 % of the target (maximum direction, 0.2 to 2.0 T)."""
    records = [_synthetic(10 + k) for k in range(22)]
    pairs = [(2 * k, 2 * k + 1) for k in range(11)]
    target = _target()
    with code_context.using(registry.load(US)):
        low, high, period = rec.period_range("XY", {"X": 0.6, "Y": 0.9}, None, "nonlinear")
        assert (low, high, period) == pytest.approx((0.12, 1.8, 0.9))
        factors = rec.scale_suite(records, target, period, pairs, True, "nonlinear", (low, high))
        assert all(factors[a] == factors[b] > 0 for a, b in pairs)  # one factor per pair
        scaled = [(dt, f * acc) for f, (dt, acc) in zip(factors, records, strict=True)]
        check = rec.check_suite(
            scaled, target, period, pairs, procedure="nonlinear", bounds=(low, high)
        )
    assert check.ratio == 0.9 and check.count == 11 and not check.notes
    assert check.least == pytest.approx(1.0, abs=1e-6)  # just meets 90 % at the governing T


def test_bnbc_scaling_unchanged() -> None:
    """The default pack goes through OpenSees Studio's period-range scaling as before."""
    from opensees_studio.core.scaling import period_range_scale_factors

    records = [_synthetic(30 + k) for k in range(3)]
    target = _target()
    with code_context.using(registry.load("bnbc2020")):
        ours = rec.scale_suite(records, target, 0.8, None, True, "nonlinear")
    theirs = period_range_scale_factors(
        dict(enumerate(records)), target, 0.8, a=0.2, b=1.5, alpha=1.0, individual=True,
        n_periods=rec.CHECK_POINTS,
    )  # fmt: skip
    assert ours == [theirs.factors[k] for k in range(3)]


# ─────────────────────────────── spectral matching ───────────────────────────────


def test_frequency_domain_matching_converges() -> None:
    dt, a = _synthetic(4, seconds=20.0)
    rule = SimpleNamespace(
        method="frequencyDomain", lowerShare=0.8, upperShare=1.25, tolerance=0.1,
        iterations=30, points=40, baselineOrder=3,
    )  # fmt: skip

    def goal(p):
        return _target().sa_at(p)

    found = sm.match(dt, a, goal, 0.1, 3.0, rule, 0.05)
    assert found.converged and found.misfit <= 0.1
    assert found.history[0] > found.misfit  # the misfit falls
    assert found.accel.size == a.size
    # The baseline correction: no drift left in velocity and displacement.
    velocity = np.cumsum(found.accel) * dt
    assert abs(velocity[-1]) < 0.05 * np.abs(velocity).max()


# ─────────────────────────────── a small frame, three records ───────────────────────────────


def _record(path, seed: int) -> None:
    dt, a = _synthetic(seed, seconds=3.0, dt=0.01)
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(a.size) * dt
    path.write_text(
        "time,accel\n" + "\n".join(f"{ti:.4f},{ai:.6f}" for ti, ai in zip(t, a, strict=True))
    )  # a CSV with a header line


@pytest.fixture(scope="module")
def frame(tmp_path_factory):
    from test_fem_derive import PLAN, SETTINGS
    from test_fem_pushover import MATERIALS, OBJECTS

    from saengine.fem.derive import derive_fem
    from saengine.library.bim import generate
    from saengine.library.settings import NonlinearHistory, TimeHistory

    root = tmp_path_factory.mktemp("p5-frame")
    histories = []
    for k in range(3):
        _record(root / "02 Project Settings" / "records" / f"r{k}.csv", 50 + k)
        histories.append(
            TimeHistory(
                name=f"R{k}",
                record=f"02 Project Settings/records/r{k}.csv",
                direction="X",
                magnitude=6.5,
                distance=20.0,
                vs30=300.0,
                source="synthetic",
            )
        )
    settings = SETTINGS.model_copy(
        update={
            "analysis": SETTINGS.analysis.model_copy(
                update={
                    "timeHistories": histories,
                    "nonlinearHistory": NonlinearHistory(),
                    "timeHistoryModification": "matching",
                    "timeHistoryMatching": "frequencyDomain",
                }
            )
        }
    )
    folder = root / "08 FEM"
    folder.mkdir(parents=True)
    d = derive_fem(generate(PLAN, "s"), OBJECTS, MATERIALS, settings, None, folder)
    return d, folder, settings, {o.id: o for o in OBJECTS.objects}


def test_frame_with_three_matched_records(frame, monkeypatch: pytest.MonkeyPatch) -> None:
    from saengine.fem import acceptance, hinges
    from saengine.fem import nonlinear_history as nh

    d, folder, settings, types = frame
    model = d.history
    assert model is not None
    # The matched records replace the originals in the nonlinear model (the same ids).
    sources = [r["source_path"] for r in model["ground_motions"]]
    assert all(s.startswith(rec.MATCHED_FOLDER) for s in sources), sources
    assert any("spectrally matched" in n for n in d.notes), d.notes
    runs = [a for a in model["analyses"] if a["type"] == "Transient"]
    assert len(runs) == 3
    for run in runs:  # the hinges of the US pack read the section deformations
        run["record_section_deformations"] = True
    path = folder / nh.HISTORY_FILE
    path.write_text(json.dumps(model), encoding="utf-8")
    out = folder / nh.RESULTS_FOLDER
    ids = [str(a["id"]) for a in model["analyses"]][1:]
    done = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(path)]
        + ["--cases", *ids, "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    monkeypatch.setattr(acceptance, "analysis_settings", lambda _path: settings)
    found = nh.evaluate(out, path)  # the default pack: fibre strains, matched suite
    assert found is not None and found["available"], found
    (suite,) = found["suites"]
    assert suite["modification"] == "matching" and suite["count"] == 3
    assert all(c.get("matching") and c.get("magnitude") == 6.5 for c in suite["cases"])
    assert all(c.get("pga") for c in suite["cases"])
    assert found["acceptance"]["rows"]
    # P3's hinges over the records (the US pack's ASCE 41 tables).
    from opensees_studio.services.result_store import load_manifest

    from saengine.fem.story_response import load_cached

    entry = next(e for e in load_manifest(out)["cases"] if e["result_type"] == "TransientResults")
    results = load_cached(entry, out)
    # The fibres rebuilt from the section deformations give the strain peaks the run kept.
    element = next(e["id"] for e in model["elements"] if e["type"] == "ForceBeamColumn")
    rebuilt = hinges._fibres_from_sections(results, element, "start")
    peaks = results.element_fibre_peaks(element)["start"]
    assert rebuilt is not None and rebuilt.shape[1] == len(peaks)
    scale = np.abs(peaks[:, 3:]).max()
    assert np.abs(rebuilt[:, :, 4].max(axis=0) - peaks[:, 4]).max() < 0.05 * scale
    with code_context.using(registry.load(US)):
        rows, _ = hinges.history_rows(model, hinges.transient_results(results), "CP", types)
    assert rows and {r["component"] for r in rows} <= {"rcColumn", "rcBeam"}
    assert all(r["level"] == "CP" and r["demand"] >= 0 for r in rows)
    assert all(r["covered"] for r in rows)

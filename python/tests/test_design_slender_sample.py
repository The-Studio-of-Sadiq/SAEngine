"""Column slenderness of the shipped sample (a copy), after its analysis.

Before slenderness was designed for, the check only flagged k lu / r > 22 (k = 1, lu = the
element length): bending about the sample columns' 400 mm faces (r = 120 mm) was flagged
at 3200 / 120 = 26.7. Now
every storey is nonsway (Q well below 0.05) and the limit is 34 - 12 M1/M2 <= 40, so most
storey columns' slenderness may be neglected; those governed by a response spectrum
combination (single curvature taken) and the raking members are designed (δns ~ 1).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from saengine.design.check import design_report
from saengine.pipeline.run_all import run_all

pytestmark = pytest.mark.slow

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("slender-sample") / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    result = run_all(root, ["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    return root


@pytest.fixture(scope="module")
def report(analysed: Path):
    return design_report(
        analysed / "08 FEM" / "model.results", analysed / "08 FEM" / "model.osmodel"
    )


def test_sample_walls_count_in_the_response_spectrum_design(analysed: Path, monkeypatch) -> None:
    # The sample's earthquake is designed from the response spectrum (the default): every
    # shell reaches the stability index with its lateral part for every combination (the RS
    # sign patterns included), so the wall's shear counts in Vus as in the static design.
    from saengine.design import slender

    seen: dict = {}
    original = slender.SlenderContext.__init__

    def spy(self, *args, **kwargs):
        original(self, *args, **kwargs)
        seen["context"] = self

    monkeypatch.setattr(slender.SlenderContext, "__init__", spy)
    names: list[str] = []
    shells: dict = {}
    real = slender.storeys

    def storeys(project, building, pieces, combinations, lateral, drift, found, model, *rest):
        names.extend(combinations)
        shells.update(found or {})
        return real(project, building, pieces, combinations, lateral, drift, found, model, *rest)

    monkeypatch.setattr(slender, "storeys", storeys)
    design_report(analysed / "08 FEM" / "model.results", analysed / "08 FEM" / "model.osmodel")
    context = seen["context"]
    spectral = [n for n, s in zip(names, context.spectrum, strict=True) if s]
    assert spectral and any(n.endswith("]") for n in spectral)
    assert shells and all(len(sway) == len(names) for _, sway in shells.values())
    # An RS sign pattern's wall forces carry ± E in their lateral part.
    c = names.index(spectral[0])
    assert any(abs(sway[c]).max() > 0 for _, sway in shells.values())
    # The modal-force run covers both directions (none is left out silently), and an RS
    # combination's Vus is the spectrum's own storey shear: with 100 % EY at least the scaled
    # base shear in Y, 0.85 V (the sum of the members' signed envelopes was far below it).
    from saengine.fem import seismic_design as sd

    out = analysed / "08 FEM" / "model.results"
    summary = sd.load_summary(out)
    assert summary["run"]["directions"] == ["X", "Y"]
    assert {"RX", "RY"} <= set(sd.load_seismic_forces(out).parts)
    v_y = 0.85 * summary["scale"]["vStatic"]["y"] * 1e3
    ground_y = next(s for s in context.storeys if s.direction == "Y" and s.name.startswith("Base"))
    full_y = [i for i, n in enumerate(names) if "(RS 0.3EX + EY)" in n]
    assert full_y and all(ground_y.vus[i] >= 0.99 * v_y for i in full_y)
    # The drift factor follows what the analysed model ran (not the settings now): 1.0 when
    # its lateral cases carry cracked sections, else each storey's cracked-over-gross ratio.
    if context.model.lateral_cracked:
        assert all(f == 1.0 for s in context.storeys for f in s.factor)
    else:
        assert all(f > 1.0 for s in context.storeys for f in s.factor)


def test_sample_storeys_are_nonsway(report) -> None:
    stability = report["stability"]
    assert {(s["storey"], s["direction"]) for s in stability} == {
        ("Base to Level 1", "X"),
        ("Base to Level 1", "Y"),
        ("Level 1 to Level 2", "X"),
        ("Level 1 to Level 2", "Y"),
    }
    for s in stability:
        assert s["sway"] is False and 0 < s["Q"] < 0.05, s
        # Q = ΣPu Δo / (Vus lc), Δo the cracked drift of 6.3.10.4.1: the analysis's own when
        # it ran the lateral cases cracked (factor 1.0), else times the storey's ratio.
        assert s["driftFactor"] >= 1.0
        q = s["sumPu"] * s["deltaO"] * 1e-3 / (s["Vus"] * s["lc"])
        assert q == pytest.approx(s["Q"], rel=0.02, abs=2e-4)


def test_sample_columns_slenderness(report) -> None:
    columns = [e for e in report["elements"] if e["kind"] == "column"]
    assert columns
    designed = []
    for element in columns:
        slender = [c for c in element["checks"] if c["name"].startswith("Slenderness about")]
        assert len(slender) == 2, element["id"]
        for check in slender:
            s = check["slenderness"]
            assert check["ok"] and not check["secondOrderRequired"]
            assert s["klu_r"] <= 100
            if s["neglected"]:
                # Formerly flagged at k lu / r > 22; now within 34 - 12 M1/M2 (<= 40).
                assert check["flag"] and s["klu_r"] <= s["limit"] <= 40
                assert check["name"].endswith("(nonsway, neglected)")
            else:
                designed.append((element["id"], s))
                assert not check["flag"] and s["deltaNs"] >= 1.0
                assert s["M2magnified"] >= s["M2"] * 0.999
    # The storey columns' slenderness is neglected, except about the 400 mm faces (k lu / r =
    # 22.5) of the columns whose governing combination is a response spectrum one: taken in
    # single curvature with nearly equal end moments (limit 34 - 12 |M1/M2| ~ 22), they are
    # designed with Cm = 1.0 and δns ~ 1.01. The long raking members are designed too.
    # C7 stands on level 1 with nothing framing into its top: lu is its full 3200 mm (k lu / r
    # = 26.7 about the 400 mm faces) and, without first-order moments under gravity (round-off
    # only, M1/M2 = 1: limit 22), it is designed for M2,min.
    for member, s in designed:
        assert s["deltaNs"] < 1.1, member
        if member == "C7":
            assert s["lu"] == pytest.approx(3200) and s["klu_r"] == pytest.approx(26.67, abs=0.1)
            assert s["limit"] == pytest.approx(22.0) and s["M2"] == 0.0 and s["Cm"] == 1.0
        elif member.startswith("C"):
            assert s["lu"] == pytest.approx(2700) and s["klu_r"] == pytest.approx(22.5, abs=0.1)
            assert s["Cm"] == 1.0
    assert any(not member.startswith("C") for member, _ in designed)
    assert any(member.startswith("C") for member, _ in designed)

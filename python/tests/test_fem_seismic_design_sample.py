"""The response spectrum design of the shipped sample (a copy), after its analysis."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from saengine.fem import seismic_design as sd
from saengine.library.settings import ProjectSettings
from saengine.pipeline.run_all import run_all

pytestmark = pytest.mark.slow

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


@pytest.fixture(scope="module")
def sample(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("rs-sample") / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    result = run_all(root, ["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    settings = ProjectSettings.model_validate_json(
        (root / "02 Project Settings" / "project-settings.json").read_text(encoding="utf-8")
    )
    out, model = root / "08 FEM" / "model.results", root / "08 FEM" / "model.osmodel"
    return root, out, model, settings, sd.seismic_design(out, model, settings)


def test_sample_runs_the_response_spectrum_and_its_forces_are_scaled_up(sample) -> None:
    _, out, _, settings, summary = sample
    # The sample keeps the default Response spectrum on: RX and RY ran with the analysis.
    assert settings.analysis.responseSpectrum and summary["available"]
    # Dhaka (zone 2), site class SD, occupancy II: still Category D (Table 6.2.18), 100 % + 30 %.
    assert summary["category"] == "D" and summary["orthogonal"]
    scale = summary["scale"]
    # The sample is stiff (modes of 0.06-0.15 s, on the rising branch of the spectrum below
    # TB = 0.2 s), while the static base shear takes the approximate period on the plateau:
    # V_rs is 41 % (X) and 42 % (Y) of V on the cracked lateral sections, so the forces are
    # scaled by 0.85 / 0.41 = 2.08 and 0.85 / 0.42 = 2.01 (when written).
    # Special moment frame R = 8 in zone 2: 103.9 kN of the earlier rcImf (R 5) in zone 3
    # x (0.20 / 0.28) x (5 / 8) = 46.4 kN, then x 779.7 / 824.8 for the seismic weight the
    # dog-legged stair's larger well (2.6 x 4.14 m) leaves: 43.86 kN; the brace M2 in steel
    # (A572-50, SHS 150x150x8: 0.33 kN/m instead of the concrete box's 0.11 kN/m over 6.8 m)
    # adds 1.5 kN to the 780 kN: 43.95 kN. Since version 0.0.44 the mass is lumped at the story
    # levels (the lower half of the first storey, 99.8 kN with the supports' own share, goes
    # to the base, BNBC 2020 Part 6 Sec 2.5.7.3 counts what participates) and live loads above
    # 3 kN/m² count with 50 %: W = 718.2 kN, V = 0.05625 x 718.2 = 40.40 kN. Since 0.0.45 the
    # sample's floors are residential (live 2.0 kN/m² instead of the office's 2.4; x 0.25 in W:
    # 26.7 kN instead of 32.0): W = 713.2 kN, V = 0.05625 x 713.2 = 40.12 kN.
    assert scale["vStatic"]["x"] == pytest.approx(40.12, rel=1e-3)
    for axis in ("x", "y"):
        assert scale[axis] == pytest.approx(0.85 * scale["vStatic"][axis] / scale["vDynamic"][axis])
        assert 1.6 < scale[axis] < 2.4
        assert summary["massParticipation"][axis] >= 0.90
    # Ev = 0.5 (2/3) Z S D = 0.5 x (2/3) x 0.20 x 1.35 = 0.09 D.
    assert summary["verticalCoefficient"] == pytest.approx(0.09)
    assert [c["name"] for c in summary["combinations"]][:2] == [
        "1.29D + 1.0L ± 1.0E(RS EX + 0.3EY)",
        "1.29D + 1.0L ± 1.0E(RS 0.3EX + EY)",
    ]
    # Torsional irregularity (Sec 2.5.5.3.1(i)): the ground storey's wall line at x = 13 m
    # holds one end while the frame end at x = 0 drifts, so in Y the storey is extremely
    # irregular (Δmax / Δavg ≈ 2.0 when written) and in X irregular (≈ 1.3); the roof level
    # has a single node, so only the ground storey is checked. Category D: the torsion cases
    # take Ax (eq. 6.2.44, ≈ 1.16 in X and 2.67 in Y when written), 1 < Ax ≤ 3.
    rows = {r["direction"]: r for r in summary["torsionalIrregularity"]}
    assert set(rows) == {"X", "Y"} and rows["Y"]["extreme"] and rows["X"]["irregular"]
    ax = summary["torsionAmplification"]
    assert 1.0 < ax["X"] < ax["Y"] <= 3.0
    assert summary["combinations"][1]["envelope"]["AY"] == pytest.approx(round(ax["Y"], 4))
    # 0.3 times Ax as the combinations take it (to 4 decimals), rounded again: with Ax = 2.6935
    # here, 0.3 x 2.6935 = 0.80805 rounds to 0.808, not 0.3 x Ax unrounded (0.8081).
    share_y = round(0.3 * round(ax["Y"], 4), 4)
    assert summary["combinations"][2]["envelope"]["AY"] == pytest.approx(share_y)
    assert any("extreme torsional irregularity" in n for n in summary["notes"])
    # Two storeys in each direction, within 2 % of the storey height.
    assert len(summary["drift"]) == 4 and all(d["ok"] for d in summary["drift"])
    forces = sd.load_seismic_forces(out)
    assert forces is not None and forces.scale == {"X": scale["x"], "Y": scale["y"]}


def test_sample_design_with_the_response_spectrum(sample) -> None:
    """The design check of the sample with the static EX, EY combinations
    (``analysis.seismicDesign = "static"``) and with the scaled response spectrum ones (the
    default; :func:`saengine.design.check.design` calls
    :func:`saengine.fem.seismic_design.design_demands`): the earthquake combinations are
    replaced and the demands grow."""
    from saengine.design import check

    root, out, model, _, _ = sample
    path = root / "02 Project Settings" / "project-settings.json"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    data.setdefault("analysis", {})["seismicDesign"] = "static"
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
        static = check.design_report(out, model)
    finally:
        path.write_text(text, encoding="utf-8")
    assert not any("RS" in n for n in static["combinations"])
    spectrum = check.design_report(out, model)
    names = spectrum["combinations"]
    assert not any("EX" in n and "RS" not in n for n in names)
    # 2 directions x 2 torsion shifts x 2 (1.2D, 0.9D) = 8 combinations x 8 sign patterns
    assert sum("RS" in n for n in names) == 8 * 8
    assert any("+N +My +Mz" in n for n in names) and any("−N −My −Mz" in n for n in names)

    # The strength checks only: since the seismic detailing (Sec 8.3), an element's overall
    # utilisation is often its hoop spacing or Ash, which the response spectrum does not change.
    strength = ("Flexure", "Shear", "Axial", "One-way shear", "Punching")

    def worst(report):
        out = {}
        for e in report["elements"]:
            checks = [c for c in e["checks"] if c["name"].startswith(strength)]
            if checks:
                out[e["id"]] = (
                    max(c["utilisation"] for c in checks),
                    all(c["ok"] for c in checks),
                )
        return out

    before, after = worst(static), worst(spectrum)
    assert before.keys() == after.keys()
    # The response spectrum (scaled by ~1.8-1.9, plus 30 % orthogonal, torsion and Ev) governs:
    # no element's utilisation drops by more than rounding, and some rise.
    assert all(after[k][0] >= before[k][0] - 1e-6 for k in before)
    assert any(after[k][0] > before[k][0] + 1e-3 for k in before)
    # The sample's verdicts do not change: gravity governs its failing beams and slabs; the
    # columns C3 and C5, beam B2, wall M1 and slab S2 rise (0.453 -> 0.470, 0.598 -> 0.653,
    # 1.331 -> 1.367, 0.753 -> 0.755, 1.536 -> 1.595 when written, with Ax on the torsion).
    assert all(before[k][1] == after[k][1] for k in before)

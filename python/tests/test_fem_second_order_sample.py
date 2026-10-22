"""The shipped sample (a copy) derived, then analysed with P-Delta and cracked sections."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from saengine.fem.second_order import (
    SecondOrderOptions,
    apply_second_order,
    drift_amplification,
    is_second_order,
)
from saengine.pipeline.run_all import run_all

pytestmark = pytest.mark.slow

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


def test_sample_with_p_delta_has_a_small_drift_amplification(tmp_path: Path) -> None:
    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    # Integrated: the settings ask for P-Delta with cracked sections for every case, and the
    # derivation (saengine.fem.derive) applies it.
    settings_file = root / "02 Project Settings" / "project-settings.json"
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    data.setdefault("analysis", {}).update(
        {"secondOrder": "pDelta", "stiffness": "aci", "crackedFor": "all"}
    )
    settings_file.write_text(json.dumps(data, indent="\t"), encoding="utf-8")
    result = run_all(root, ["derive"])
    assert [s.status for s in result.steps] == ["ok"], [s.message for s in result.steps]
    model = root / "08 FEM" / "model.osmodel"
    derived = json.loads(model.read_text(encoding="utf-8"))
    assert is_second_order(derived)
    # Applying it again to a gross first-order copy gives the same model.
    gross = dict(data, analysis={**data["analysis"], "secondOrder": "none", "stiffness": "gross"})
    settings_file.write_text(json.dumps(gross, indent="\t"), encoding="utf-8")
    assert run_all(root, ["derive"]).steps[0].status == "ok"
    first = json.loads(model.read_text(encoding="utf-8"))
    second = apply_second_order(
        first, SecondOrderOptions(secondOrder="pDelta", stiffness="aci", crackedFor="all")
    )
    same = {k: v for k, v in derived.items() if k != "meta"}  # meta records the settings' stamp
    assert {k: v for k, v in second.project.items() if k != "meta"} == same
    assert second.summary["pDeltaColumns"] > 0
    settings_file.write_text(json.dumps(data, indent="\t"), encoding="utf-8")
    model.write_text(json.dumps(derived), encoding="utf-8")
    result = run_all(root, ["analysis"])
    assert [s.status for s in result.steps] == ["ok"], [s.message for s in result.steps]
    amplification = drift_amplification(second.project, root / "08 FEM" / "model.results")
    cases = {c["case"]: c for c in amplification["cases"]}
    assert set(cases) == {"WX", "WY", "EX", "EY"}, amplification["notes"]
    # The default levels: the diaphragm floor at 3.2 m, the base and the roof column's top.
    assert [(s["from"], s["to"]) for s in cases["EX"]["storeys"]] == [(0.0, 3.2), (3.2, 6.4)]
    # The building's stories (Floor Plan elevations / 1000) give the same storeys.
    given = drift_amplification(
        second.project, root / "08 FEM" / "model.results", levels=[0.0, 3.2, 6.4]
    )
    assert given["cases"] == amplification["cases"]
    # A two-storey frame: P-Delta adds a little, ratio = 1 / (1 - θ) with θ well below 0.10.
    for case in cases.values():
        assert case["storeys"]
        assert 1.0 < case["maxRatio"] < 1.05, case
        # The roof storey (one light column) is barely amplified: ratio 1.000.
        assert all(-1e-6 < s["impliedTheta"] < 0.05 for s in case["storeys"]), case
    # BNBC Eq 6.2.48 θ (I = 1.0, Cd = 5.5 assumed here): far below 0.10 and θmax.
    bnbc = drift_amplification(
        second.project, root / "08 FEM" / "model.results", importance=1.0, cd=5.5
    )
    for case in bnbc["cases"]:
        if case["case"].startswith("W"):
            assert case["maxTheta"] is None
            continue
        ground = case["storeys"][0]
        assert ground["Px"] > 0 and ground["Vx"] > 0, case
        assert 0 < case["maxTheta"] < 0.05, case
        assert ground["thetaMax"] == pytest.approx(0.5 / 5.5)

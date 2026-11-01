"""Column shortening with creep and shrinkage (B25, saengine.fem.staged): worked out from a run
of the three-storey frame of test_fem_staged, through the storey response."""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.fem import staged
from saengine.fem.story_response import work_out_story_response
from tests.test_fem_staged import derivation, settings


def test_section_perimeter_of_rectangles_and_circles() -> None:
    rect = {"A": 0.3 * 0.5, "Iy": 0.3 * 0.5**3 / 12, "Iz": 0.5 * 0.3**3 / 12}
    assert staged.section_perimeter(rect) == pytest.approx(1.6)
    d = 0.6
    area = np.pi * d**2 / 4
    circle = {"A": area, "Iy": np.pi * d**4 / 64, "Iz": np.pi * d**4 / 64}
    assert staged.section_perimeter(circle) == pytest.approx(np.pi * d)
    odd = {"A": 0.16, "Iy": 1.0, "Iz": 1.0}
    assert staged.section_perimeter(odd) == pytest.approx(1.6)  # a square of the same area


def _options(**kw):
    s = settings().analysis.timeDependent.model_copy(update={"enabled": True, **kw})
    return s


def _run(root: Path, sequence: bool) -> tuple[Path, Path]:
    d = derivation(sequence)
    model = root / "08 FEM" / "model.osmodel"
    model.parent.mkdir(parents=True)
    model.write_text(json.dumps(d.project), encoding="utf-8")
    s = settings(sequence)
    s.analysis.timeDependent.enabled = True
    (root / "02 Project Settings").mkdir()
    (root / "02 Project Settings" / "project-settings.json").write_text(
        s.model_dump_json(by_alias=True), encoding="utf-8"
    )
    out = root / "08 FEM" / "model.results"
    keep = [a["id"] for a in d.project["analyses"] if a["name"].split(":")[0] in ("D", "SD", "L")]
    result = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model), "--cases"]
        + [str(i) for i in keep]
        + ["--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return model, out


@pytest.fixture(scope="module")
def response(tmp_path_factory: pytest.TempPathFactory) -> dict:
    model, out = _run(tmp_path_factory.mktemp("shortening"), True)
    return work_out_story_response(out, model)


def test_shortening_of_every_column_line(response) -> None:
    found = response["columnShortening"]
    assert found and found["available"], found
    assert found["inputs"]["staged"] is True
    assert found["inputs"]["humidity"] == 45  # indoor, from the pack
    assert len(found["lines"]) == 6  # 3 × 2 grid
    for line in found["lines"]:
        rows = line["rows"]
        assert [r["level"] for r in rows] == ["Level 1", "Level 2", "Level 3"]
        totals = [r["total"] for r in rows]
        assert all(b > a > 0 for a, b in itertools.pairwise(totals))
        for k, r in enumerate(rows):
            assert r["elastic"] > 0 and r["creep"] > 0 and r["shrinkage"] > 0
            # What happens after a floor is cast is less than the total below it (level 1:
            # nothing loads or dries its columns before its floor is cast).
            assert 0 < r["afterCasting"] <= r["total"] * (1 + 1e-9)
            if k:
                assert r["afterCasting"] < r["total"]
            assert r["total"] == pytest.approx(r["elastic"] + r["creep"] + r["shrinkage"])
        # 400 × 400 columns: effective thickness 2A/u = 200 mm.
        assert line["storeys"][0]["thickness"] == pytest.approx(200.0)
    # Creep under sustained load is a multiple of the elastic shortening (cc of 2 to 4).
    top = found["lines"][0]["rows"][-1]
    assert 1.0 < top["creep"] / top["elastic"] < 4.0
    # Millimetres, not metres or microns, for a 9.6 m frame.
    assert 1e-4 < top["total"] < 2e-2
    assert found["times"]["complete"] == pytest.approx(21.0)  # 3 floors on a 7 day cycle
    assert found["clauses"]["creep"] and found["clauses"]["reinforced"]


def test_history_grows_and_differential_rows(response) -> None:
    found = response["columnShortening"]
    for line in found["history"]["lines"]:
        values = line["values"]
        assert len(values) == len(found["history"]["days"])
        assert values[-1] == max(values)
    # Corner and edge columns carry different loads: the beams see a differential.
    assert found["differential"]
    row = found["differential"][0]
    assert row["difference"] >= 0 and row["moment"] >= 0 and row["length"] > 0


def test_without_the_construction_sequence(tmp_path: Path) -> None:
    model, out = _run(tmp_path, False)
    found = work_out_story_response(out, model)["columnShortening"]
    assert found["available"] and found["inputs"]["staged"] is False
    assert any("construction sequence" in n for n in found["notes"])


def test_uncovered_pack_reports_unavailable(monkeypatch) -> None:
    from saengine.fem import concrete_time

    monkeypatch.setattr(concrete_time, "table", lambda: None)
    found = staged.column_shortening({}, {}, [], SimpleNamespace(exposure="indoor"))
    assert found["available"] is False and "does not cover" in found["reason"]


def test_settings_default_off() -> None:
    options = settings().analysis.timeDependent
    assert options.enabled is False
    assert (options.cycleDays, options.serviceLifeYears, options.sustainedLive) == (7, 30, 0.25)

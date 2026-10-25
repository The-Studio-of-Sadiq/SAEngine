"""Storey response, member detail and table export of the FEM results (saengine.fem.story_response,
saengine.fem.member_detail, saengine.fem.table_export)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_fem_derive import OBJECTS, PLAN, SETTINGS

from saengine.fem import member_detail
from saengine.fem.derive import derive_fem
from saengine.fem.story_response import (
    _overturning,
    _shears,
    _storey_loads,
    storey_levels,
    story_response,
)
from saengine.fem.table_export import sheet_name, write_xlsx
from saengine.library import default_material_library
from saengine.library.bim import generate

# ─────────────────────────────── pure helpers ───────────────────────────────


def test_storey_forces_shears_and_overturning_by_hand() -> None:
    levels = [0.0, 3.0, 6.0, 9.0]
    # Loads near the levels go to the nearest one; a load at the base carries no storey.
    loads = [(3.0, 10.0, 0.0), (5.99, 20.0, -5.0), (9.0, 30.0, 0.0), (0.0, 7.0, 0.0)]
    fx, fy = _storey_loads(loads, levels)
    assert fx.tolist() == [7.0, 10.0, 20.0, 30.0]
    assert fy.tolist() == [0.0, 0.0, -5.0, 0.0]
    # Storey shears: the forces at and above each storey's top level.
    assert _shears(fx).tolist() == [60.0, 50.0, 30.0]
    # Overturning at each level from the forces above it.
    assert _overturning(fx, levels).tolist() == pytest.approx(
        [10 * 3 + 20 * 6 + 30 * 9, 20 * 3 + 30 * 6, 30 * 3, 0.0]
    )


def test_chain_orders_a_member_from_one_end() -> None:
    class E:
        def __init__(self, i: int, j: int) -> None:
            self.i, self.j = i, j

    a, b, c = E(2, 3), E(4, 3), E(1, 2)  # 1-2, 2-3, 3-4 given out of order, one reversed
    order = member_detail._chain([a, b, c])
    # Walked from one free end to the other (member_forces then turns it to run upwards).
    walk = [(e.j, e.i) if back else (e.i, e.j) for e, back in order]
    assert all(walk[k][1] == walk[k + 1][0] for k in range(len(walk) - 1))
    assert {walk[0][0], walk[-1][1]} == {1, 4}
    assert member_detail.member_of("C3#2") == "C3" and member_detail.member_of("B1") == "B1"


def test_demand_points_keep_what_matters_per_combination() -> None:
    points = [
        (100e3, 10e6, 1e6, "1.4D", "C1 at 0.00 L"),
        (90e3, 30e6, 2e6, "1.4D", "C1 at 1.00 L"),
        (95e3, 5e6, 40e6, "1.4D", "C1 at 0.50 L"),
        (50e3, 1e6, 1e6, "0.9D + EX", "C1 at 0.00 L"),
    ]
    out = member_detail._demand_points(points)
    by = {(p["combination"], p["where"]) for p in out}
    assert by == {
        ("1.4D", "C1 at 0.00 L"),
        ("1.4D", "C1 at 1.00 L"),
        ("1.4D", "C1 at 0.50 L"),
        ("0.9D + EX", "C1 at 0.00 L"),
    }
    first = next(p for p in out if p["where"] == "C1 at 1.00 L")
    assert (first["P"], first["Mx"], first["My"]) == pytest.approx((90.0, 30.0, 2.0))


def test_column_interaction_is_worked_out_once_per_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from saengine.design import rc, required

    out = tmp_path / "08 FEM" / "model.results"
    out.mkdir(parents=True)
    (out / "manifest.json").write_text("{}", encoding="utf-8")
    model = tmp_path / "08 FEM" / "model.osmodel"
    model.write_text("{}", encoding="utf-8")

    class Section:
        phi_pn_max, phi_tension = 2000e3, 500e3

    class Surface:
        def __init__(self, section: object) -> None:
            pass

        def moment_capacity(self, pu: float, angle: float) -> float:
            return 100e6 * (1 - abs(pu - 750e3) / 1250e3)

        def check(self, pu: float, mux: float, muy: float) -> rc.ColumnCheck:
            return rc.ColumnCheck(mux / 100e6, 100e6, mux, "")

        def contour(self, pu: float) -> np.ndarray:
            return np.array([[100e6, 0], [0, 100e6], [-100e6, 0], [0, -100e6]])

    calls = []

    def gather(out_dir: object, project_path: object, substructure: bool = True) -> object:
        calls.append(1)
        member = {
            "id": "C1",
            "kind": "column",
            "type": "C400",
            "section": Section(),
            "points": [(300e3, 60e6, 5e6, "1.4D", "C1 at 0.00 L")],
        }

        class Gathered:
            def __init__(self) -> None:
                self.collect = {"members": [member, {"id": "B1", "kind": "beam", "points": None}]}
                self.assumed = {"C400"}

        return Gathered()

    monkeypatch.setattr(required, "gather", gather)
    monkeypatch.setattr(rc, "InteractionSurface", Surface)
    first = member_detail.column_interaction(out, model, "C1")
    column = first["columns"]["C1"]
    assert column["assumedBars"] and column["phiPnMax"] == pytest.approx(2000.0)
    assert column["governing"]["utilisation"] == pytest.approx(0.6)
    assert len(column["curves"]["x"]) == member_detail.CURVE_POINTS
    assert column["contour"][0] == pytest.approx([100.0, 0.0])
    # Read again from the file beside the results, until the run changes.
    assert member_detail.column_interaction(out, model)["columns"].keys() == {"C1"}
    assert len(calls) == 1
    (out / "manifest.json").write_text('{"again": 1}', encoding="utf-8")
    assert member_detail.column_interaction(out, model, "B1")["columns"] == {}
    assert len(calls) == 2


def test_tables_to_excel(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    taken: set[str] = set()
    assert (
        sheet_name("Storey drifts: 1.2D + 1.6L [X/Y]", taken) == "Storey drifts  1.2D + 1.6L  X Y"
    )
    assert sheet_name("Storey drifts: 1.2D + 1.6L [X/Y]", taken).endswith(" (2)")
    path = tmp_path / "out" / "results.xlsx"
    written = write_xlsx(
        path,
        [
            {"name": "Joint displacements", "columns": ["Node", "ux [mm]"], "rows": [[1, 2.5]]},
            {
                "name": "Reactions",
                "columns": ["Node", "Fz [kN]"],
                "rows": [[1, -10]],
                "notes": ["n"],
            },
        ],
    )
    assert written["sheets"] == 2
    book = load_workbook(path)
    assert book.sheetnames == ["Joint displacements", "Reactions"]
    assert [c.value for c in book["Joint displacements"][2]] == [1, 2.5]
    assert book["Reactions"]["A4"].value == "n"
    with pytest.raises(ValueError):
        write_xlsx(tmp_path / "results.csv", [])


# ─────────────────────────────── a solved bay ───────────────────────────────


@pytest.fixture(scope="module")
def solved(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, dict]:
    root = tmp_path_factory.mktemp("bay")
    model_dir = root / "08 FEM"
    model_dir.mkdir()
    building = generate(PLAN, "s")
    (root / "06 BIM").mkdir()
    (root / "06 BIM" / "bim.json").write_text(building.model_dump_json(), encoding="utf-8")
    (root / "02 Project Settings").mkdir()
    (root / "02 Project Settings" / "project-settings.json").write_text(
        SETTINGS.model_dump_json(), encoding="utf-8"
    )
    d = derive_fem(building, OBJECTS, default_material_library(), SETTINGS, None, model_dir)
    model = model_dir / "model.osmodel"
    model.write_text(json.dumps(d.project), encoding="utf-8")
    out = model_dir / "model.results"
    cases = {a["name"]: a["id"] for a in d.project["analyses"]}
    wanted = [n for n in cases if n.split(":")[0] in ("D", "EX", "Modal", "RX")]
    run = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model)]
        + ["--cases", *(str(cases[n]) for n in wanted), "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    return out, model, d.project


def test_storey_response_of_a_one_storey_bay(solved: tuple[Path, Path, dict]) -> None:
    out, model, project = solved
    response = story_response(out, model)
    levels = response["levels"]
    assert len(levels) == 2 and levels[0]["z"] == pytest.approx(0.0)
    assert levels == storey_levels(project, model)
    height = levels[1]["z"] - levels[0]["z"]
    by_label = {r["label"].split(":")[0]: r for r in response["results"]}

    # EX: the storey shear is the sum of the pattern's loads, and the supports take it back.
    pattern = next(p for p in project["load_patterns"] if p["name"] == "EX")
    total = sum(load["forces"][0] for load in pattern["nodal_loads"])
    ex = by_label["EX"]
    top = ex["storeys"][1]
    assert top["shearX"] == pytest.approx(total, rel=1e-9)
    assert top["forceX"] == pytest.approx(total, rel=1e-9)
    assert ex["baseReaction"][0] == pytest.approx(-total, rel=1e-3)
    assert ex["storeys"][0]["overturningX"] == pytest.approx(total * height, rel=1e-9)
    # One storey on fixed supports: the drift ratio is the floor's displacement over its height.
    assert top["driftX"] == pytest.approx(abs(top["dispX"]) / height, rel=1e-6)
    assert top["shearY"] == pytest.approx(0.0, abs=1e-6)

    # Dead load: no lateral force, the supports carry the weight.
    dead = by_label["D"]
    assert dead["storeys"][1]["shearX"] == pytest.approx(0.0, abs=1e-9)
    assert dead["baseReaction"][2] > 0

    # The bay sways as one mass: mode 1 carries (nearly) all the mass in X or Y.
    modal = response["modal"]
    assert modal["required"] == 0.9 and modal["modes"][0]["period"] > 0
    assert max(modal["modes"][-1]["sumUX"], modal["modes"][-1]["sumUY"]) == pytest.approx(
        1.0, abs=0.05
    )
    # The response spectrum's storey shear: of one mass, about M_eff·Sa of the governing mode.
    rx = by_label["RX"]
    assert rx["kind"] == "spectrum" and rx["storeys"][1]["shearX"] > 0
    assert response["spectrum"]["periods"] and response["driftLimit"]["ratio"] == 0.02


def test_member_forces_of_a_column(solved: tuple[Path, Path, dict]) -> None:
    out, model, project = solved
    column = next(e["name"] for e in project["elements"] if e.get("name", "").startswith("C"))
    detail = member_detail.member_forces(out, model, member_detail.member_of(column))
    assert detail["kind"] == "column" and detail["stations"][0] == 0.0
    assert detail["stations"][-1] == pytest.approx(detail["length"])
    dead = next(r for r in detail["results"] if r["label"].startswith("D"))
    n = [f[0] for f in dead["forces"]]
    assert max(n) < 0  # the dead load compresses the column
    # The deflection is measured from the chord: zero at both ends.
    assert dead["deflection"][0] == pytest.approx([0, 0, 0], abs=1e-12)
    assert dead["deflection"][-1] == pytest.approx([0, 0, 0], abs=1e-12)
    with pytest.raises(ValueError):
        member_detail.member_forces(out, model, "nope")

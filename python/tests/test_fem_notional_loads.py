"""Notional loads of the steel stability design (BNBC 2020 Part 6 Sec 10.3.2.2)."""

from __future__ import annotations

import pytest

from saengine.fem import notional_loads as nl
from saengine.fem.combinations import combination_factors
from saengine.library.settings import LoadCombination


def _project():
    """Two columns (base z = 0, top z = 3 m) joined by a beam carrying 10 kN/m of D, 50 kN of D
    at each top node and 20 kN of L at node 3."""
    return {
        "nodes": [
            {"id": 1, "coords": [0.0, 0.0, 0.0]},
            {"id": 2, "coords": [6.0, 0.0, 0.0]},
            {"id": 3, "coords": [0.0, 0.0, 3.0]},
            {"id": 4, "coords": [6.0, 0.0, 3.0]},
        ],
        "elements": [
            {"id": 1, "type": "ElasticBeamColumn", "nodes": [3, 4]},
        ],
        "time_series": [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}],
        "load_patterns": [
            {
                "id": 1,
                "name": "D",
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [
                    {"node_id": 3, "forces": [0, 0, -50e3, 0, 0, 0]},
                    {"node_id": 4, "forces": [0, 0, -50e3, 0, 0, 0]},
                ],
                # local z of a beam along X is global Z (vecxz default (0, 0, 1))
                "element_loads": [{"element_id": 1, "wx": 0.0, "wy": 0.0, "wz": -10e3}],
            },
            {
                "id": 2,
                "name": "L",
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [{"node_id": 3, "forces": [0, 0, -20e3, 0, 0, 0]}],
                "element_loads": [],
            },
        ],
        "analyses": [{"id": 1, "name": "D: Dead", "type": "Static", "pattern_ids": [1]}],
    }


def test_coefficients():
    assert nl.coefficient("secondOrder") == pytest.approx(0.002)  # Sec 10.3.2.2.1
    assert nl.coefficient("firstOrder", 0.001) == pytest.approx(0.0042)  # minimum
    assert nl.coefficient("firstOrder", 0.003) == pytest.approx(2.1 * 0.003)  # Sec 10.3.2.2.2
    assert nl.coefficient("none") == 0.0


def test_level_gravity_and_cases():
    p = _project()
    gravity = nl.node_gravity(p, ("D", "SD"))
    assert gravity == {3: pytest.approx(80e3), 4: pytest.approx(80e3)}  # 50 + 10 × 6 / 2
    rows = nl.level_loads(p, ("D", "SD"), [0.0, 3.0])
    assert rows[1]["Y"] == pytest.approx(160e3)
    notes = nl.add_notional_cases(p, "secondOrder")
    names = [pat["name"] for pat in p["load_patterns"]]
    assert {"NXD", "NYD", "NXL", "NYL"} <= set(names)
    assert "NXLr" not in names  # no Lr case
    nxd = next(pat for pat in p["load_patterns"] if pat["name"] == "NXD")
    total = sum(load["forces"][0] for load in nxd["nodal_loads"])
    assert total == pytest.approx(0.002 * 160e3)  # Ni = 0.002 Yi
    nyl = next(pat for pat in p["load_patterns"] if pat["name"] == "NYL")
    assert nyl["nodal_loads"] == [{"node_id": 3, "forces": [0, 0.002 * 20e3, 0, 0, 0, 0]}]
    assert any(a["name"].startswith("NXD:") for a in p["analyses"])
    assert notes and "Sec 10.3.2.2.1" in notes[0]


def test_combinations_scale_by_their_factors():
    gravity = LoadCombination(name="1.2D + 1.6L", D=1.2, L=1.6)
    lateral = LoadCombination(name="1.2D + 1.0EX + 1.0L", D=1.2, EX=-1.0, L=1.0)
    present = {"D", "SD", "L", "EX", "NXD", "NYD", "NXL", "NYL"}
    out = nl.notional_combinations([gravity, lateral], present, every=False)
    assert [c.name for c in out] == [
        "1.2D + 1.6L",
        "1.2D + 1.6L [+NX]",
        "1.2D + 1.6L [-NX]",
        "1.2D + 1.6L [+NY]",
        "1.2D + 1.6L [-NY]",
        "1.2D + 1.0EX + 1.0L",
    ]
    minus_x = combination_factors(out[2], present)
    assert minus_x["NXD"] == pytest.approx(-1.2)
    assert minus_x["NXL"] == pytest.approx(-1.6)
    assert "NYD" not in minus_x
    first = nl.notional_combinations([lateral], present, every=True)
    assert len(first) == 1 and first[0].name.endswith("[+N]")
    f = combination_factors(first[0], present)
    assert f["NXD"] == pytest.approx(-1.2)  # with the earthquake's direction (-X)
    assert "NYD" not in f


def test_no_notional_cases_no_change():
    assert nl.notional_combinations([LoadCombination(name="1.4D", D=1.4)], {"D"}, False) is None

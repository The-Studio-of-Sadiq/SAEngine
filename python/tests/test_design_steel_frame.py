"""Steel member design end to end: a braced steel portal (W-shape columns and beam, an SHS
diagonal) is derived and analysed through SAEngine's pipeline, its section forces combined as
:mod:`saengine.design.check` combines them, and every member designed by
:func:`saengine.design.steel.design_steel_member`, the brace in tension or compression by the
sign of the sway, with the bracing read from the model.
"""

from __future__ import annotations

import math

import pytest

from saengine.design.check import _demands
from saengine.design.steel import design_steel_member
from saengine.library.settings import LoadCombination
from saengine.verification.cases.common import (
    MATERIALS,
    derive,
    node_at,
    objects,
    point,
    run_model,
    settings,
    structure,
)
from saengine.verification.cases.common import building as building_of

W = {
    "shape": "I",
    "overallWidth": 254,
    "overallDepth": 254,
    "webThickness": 8.6,
    "flangeThickness": 14.2,
}
TYPES = objects(
    {"id": "COL", "name": "W col", "kind": "column", "material": "A992", "profile": W},
    {"id": "BM", "name": "W beam", "kind": "beam", "material": "A992", "profile": W},
    {
        "id": "BR",
        "name": "SHS 150x8",
        "kind": "brace",
        "material": "A992",
        "profile": {"shape": "rectangleHollow", "xDim": 150, "yDim": 150, "wallThickness": 8},
    },
)


@pytest.fixture(scope="module")
def frame(tmp_path_factory):
    model = structure(
        members=[
            {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3200)},
            {"id": "C2", "type": "COL", "start": point(6000, 0, 0), "end": point(6000, 0, 3200)},
            {"id": "B1", "type": "BM", "start": point(0, 0, 3200), "end": point(6000, 0, 3200)},
            {"id": "M1", "type": "BR", "start": point(0, 0, 0), "end": point(6000, 0, 3200)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    building = building_of(model)
    d = derive(building, TYPES, MATERIALS, settings())
    project = d.project
    top = node_at(project, (0, 0, 3.2))
    wx = next(p for p in project["load_patterns"] if p["name"] == "WX")
    wx["nodal_loads"] = [{"node_id": top, "forces": [100e3, 0, 0, 0, 0, 0]}]
    beam = next(e["id"] for e in project["elements"] if e["name"] == "B1")
    project["load_patterns"][0]["element_loads"].append(
        {"element_id": beam, "wy": 0.0, "wz": -20e3, "wx": 0.0}
    )
    static = [a["id"] for a in project["analyses"] if a["type"] == "Static"]
    _, out, _ = run_model(project, tmp_path_factory.mktemp("steel"), static)
    s = settings().model_copy(
        update={
            "combinations": [
                LoadCombination(name="1.2D+1.0WX", D=1.2, WX=1.0),
                LoadCombination(name="0.9D-1.0WX", D=0.9, WX=-1.0),
            ]
        }
    )
    combinations, pieces, _, _ = _demands(project, out, s)
    return project, building, combinations, pieces


def test_braced_portal_members(frame):
    project, building, combinations, pieces = frame
    assert combinations == ["1.2D+1.0WX", "0.9D-1.0WX"]
    types = {t.id: t for t in TYPES.objects}
    mats = {m.id: m for m in MATERIALS.materials}
    entries = {}
    for element in building.elements:
        t = types[element.type]
        entries[element.id] = design_steel_member(
            element.id,
            t.kind,
            t.id,
            t,
            mats[t.material],
            pieces[element.id],
            combinations,
            project=project,
        )
    brace = {c["name"]: c for c in entries["M1"]["checks"]}
    # The diagonal runs from the base of C1 up to the top of C2: +WX at the top of C1 stretches
    # it, -WX shortens it, by roughly the horizontal load over cos θ.
    cos = 6000 / math.hypot(6000, 3200)
    assert brace["Compression: buckling"]["combination"] == "0.9D-1.0WX"
    assert brace["Tension: yielding (gross section)"]["combination"] == "1.2D+1.0WX"
    assert 40 < brace["Compression: buckling"]["demand"] < 100 / cos * 1.1
    assert brace["Compression: buckling"]["ok"]
    beam = {c["name"]: c for c in entries["B1"]["checks"]}
    assert beam["Flexure about x (major)"]["demand"] > 50  # 20 kN/m on 6 m: wL²/8 = 90 kN·m
    assert "10.6.2" in beam["Flexure about x (major)"]["clause"]
    column = {c["name"]: c for c in entries["C1"]["checks"]}
    assert column["K = 1 by first-order analysis (αPr ≤ 0.5 Py)"]["flag"]
    for entry in entries.values():
        assert entry["utilisation"] < 1.0, entry
        assert all(c["clause"].startswith("BNBC 2020 Part 6") for c in entry["checks"])

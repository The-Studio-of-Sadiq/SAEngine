"""Usability walk 4, W4-C fixes (W4C-12 to W4C-15): the point cloud slice, the bridge results
view and its clause labels, and the precast templates of each kind."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.library.defaults import default_material_library
from saengine.library.objects import PRECAST_ELEMENTS, PrecastPiece
from saengine.library.special_structures import Bridge
from saengine.library.templates import TEMPLATES
from saengine.special import bridges as br
from saengine.special import moving_loads as ml
from saengine.special.project import view_section


def _bridge(**changes) -> Bridge:
    data = {
        "id": "BR1",
        "spans": [20.0],
        "carriageway": 7.5,
        "girders": 4,
        "girderSpacing": 2.5,
        "analysis": "lineGirder",
        "girder": {
            "depth": 1500,
            "webWidth": 400,
            "concrete": "C24.1",
            "rebar": "B420DWR",
            "bottomBars": 10,
            "bottomDiameter": 32,
        },
    }
    data.update(changes)
    return Bridge.model_validate(data)


# ───────────────────────────── W4C-12: point cloud slice ─────────────────────────────


def test_w4c12_scan_sliced_at_the_story_floor_cut(tmp_path):
    """A 0-3.6 m scan cut at Level 1's floor (0) + 1.2 m has points; at 4.8 m it has none."""
    from saengine.library.point_cloud import PointCloudError, convert

    rng = np.random.default_rng(1)
    rows = [(x, y, z) for x, y, z in rng.uniform([0, 0, 0], [10, 8, 3.6], size=(4000, 3))]
    # Two walls, full height.
    rows += [(x, 0.0, z) for x in np.linspace(0, 10, 60) for z in np.linspace(0, 3.6, 20)]
    scan = tmp_path / "scan.xyz"
    scan.write_text("\n".join(f"{x:.3f} {y:.3f} {z:.3f}" for x, y, z in rows), encoding="utf-8")
    found = convert(str(scan), 1.2, 0.1, 0.02, None, True, str(tmp_path / "cache"))
    assert found.to_json()["points"] > 0
    try:
        above = convert(str(scan), 4.8, 0.1, 0.02, None, True, str(tmp_path / "cache")).to_json()
    except PointCloudError:
        return
    assert above["points"] == 0 and above["warnings"]


# ───────────────────────────── W4C-14: bridge results ─────────────────────────────


def test_w4c14_bridge_clauses_cite_the_bridge_document():
    with code_context.using(registry.load("aci318-asce7-22")):
        design = ml.basis("bridgeDesign")
        traffic = ml.basis("movingLoads")
        assert design.cite("strength").startswith("AASHTO LRFD Table 3.4.1-1")
        assert traffic.cite("lanes") == "AASHTO LRFD Art. 3.6.1.1.1"
        assert "ASCE" not in design.cite("strength")
        found = br.check_bridge(_bridge(), default_material_library())
    assert not any("ASCE 7-22 Table" in r["note"] for r in found["rows"])
    assert not any("ASCE 7-22 Art." in n for n in found["notes"])


def test_w4c14_simple_span_has_no_hogging_check():
    with code_context.using(registry.load("aci318-asce7-22")):
        found = br.check_bridge(_bridge(), default_material_library())
    assert not any("hogging" in r["name"] for r in found["rows"])
    assert any("hogging: not applicable" in n for n in found["notes"])


def test_w4c14_continuous_spans_keep_the_hogging_check():
    bridge = _bridge(spans=[20.0, 20.0], continuity="continuous")
    with code_context.using(registry.load("aci318-asce7-22")):
        found = br.check_bridge(bridge, default_material_library())
    assert any("hogging" in r["name"] for r in found["rows"])


def test_w4c14_influence_lines():
    simple = br.influence_chart([20.0])
    assert len(simple["lines"]) == 2  # midspan moment and the end reaction
    peak = max(simple["lines"][0]["values"])
    assert peak == pytest.approx(20.0 / 4, rel=1e-3)  # L/4 under the load at midspan
    assert simple["lines"][1]["values"][0] == pytest.approx(1.0)
    continuous = br.influence_chart([20.0, 20.0])
    assert len(continuous["lines"]) == 3
    assert min(continuous["lines"][1]["values"]) < 0  # hogging over the middle support


def test_w4c14_results_view_has_envelopes_and_influence_lines():
    with code_context.using(registry.load("aci318-asce7-22")):
        found = br.check_bridge(_bridge(), default_material_library())
    section = view_section({"kind": "bridges", "id": "BR1", "name": "", **found})
    titles = [c["title"] for c in section["charts"]]
    assert any(t.startswith("Moments along girder") for t in titles)
    assert any(t.startswith("Shears along girder") for t in titles)
    assert any(t.startswith("Influence lines") for t in titles)


# ───────────────────────────── W4C-15: precast templates ─────────────────────────────


@pytest.mark.parametrize("kind", ["slab", "beam", "column", "wall"])
def test_w4c15_precast_template_of_each_kind_is_its_element(kind):
    template = TEMPLATES.get(f"PrecastPiece:{kind}", TEMPLATES["PrecastPiece"])
    piece = PrecastPiece.model_validate(template)
    assert piece.element in PRECAST_ELEMENTS[kind]
    if kind == "slab":
        assert piece.element == "hollowCore"

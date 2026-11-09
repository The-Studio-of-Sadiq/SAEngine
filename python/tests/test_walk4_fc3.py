"""Usability walk 4, W-C fixes (round fc3): what the code pack does not cover is its own status
(W4C-6), steel edge beams carry the diaphragm chords (W4C-9), the slab braces the top flange of
the steel beams it rests on and the wizard's sizes (W4C-10), membrane cases without their load
(W4C-11), a missing mapped hazard fails the derive step (W4C-17), joists with frame action
(W4C-25)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design import diaphragms, membranes, steel_joists
from saengine.design.check import (
    _Piece,
    design_counts,
    is_not_covered,
    not_covered_items,
    not_covered_note,
    slab_carried_beams,
)
from saengine.design.steel.lengths import SLAB_BRACE_SPACING, LengthOptions, member_lengths
from saengine.design.steel.members import Stations
from saengine.library import default_project_settings
from saengine.library.bim import BuildingModel
from saengine.library.check import check_library
from saengine.library.materials import Material
from saengine.library.objects import Beam, Membrane

STEEL = Material.model_validate(
    {
        "id": "A992",
        "name": "A992",
        "category": "steel",
        "mechanical": {"E": 200000, "density": 7850},
        "steel": {"fy": 345, "fu": 450},
    }
)
IPE300 = {
    "shape": "I",
    "overallWidth": 150,
    "overallDepth": 300,
    "webThickness": 7.1,
    "flangeThickness": 10.7,
    "filletRadius": 15,
}


@pytest.fixture(autouse=True)
def _fresh():
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def bnbc():
    with code_context.using(registry.load("bnbc2020")) as pack:
        yield pack


@pytest.fixture
def us():
    with code_context.using(registry.load("aci318-asce7-22")) as pack:
        yield pack


# ─────────────────────────────── W4C-6: not covered by the pack ───────────────────────────────


def test_not_covered_is_counted_apart_from_no_bars_and_failures(bnbc):
    skipped = [
        {"id": "GW1", "kind": "wall", "type": "GW1", "reason": "x", "status": "notCovered"},
        {"id": "MEM1", "kind": "membrane", "type": "MEM1", "reason": "tensile membranes are "
         "not covered by the code pack"},
        {"id": "C1", "kind": "column", "type": "C350", "reason": "no reinforcement"},
    ]  # fmt: skip
    checked = [
        {"id": "B1", "kind": "beam", "type": "SB", "ok": True, "utilisation": 0.4,
         "notCovered": ["web openings are not covered by BNBC 2020"]},
    ]  # fmt: skip
    counts = design_counts(checked, skipped, [], [])
    assert counts["notChecked"] == {"noBars": 1, "notCovered": 2, "other": 0}
    assert all(is_not_covered(s) for s in skipped[:2]) and not is_not_covered(skipped[2])
    items = not_covered_items(checked, skipped)
    assert [i["id"] for i in items] == ["GW1", "MEM1", "B1"]
    note = not_covered_note(items)
    assert "BNBC 2020" in note and "web openings (B1)" in note and "tensile membranes" in note
    assert "no reinforcement" not in note


def test_membranes_and_glass_not_covered_carry_the_status(bnbc):
    _, skipped, _ = membranes.design_types({"M1": Membrane(id="M1", name="S", material="PVC")})
    assert skipped[0]["status"] == "notCovered"


def test_objects_warn_of_types_the_pack_does_not_cover(bnbc):
    materials = {"materials": [STEEL.model_dump(mode="json", by_alias=True, exclude_none=True)]}
    objects = {
        "objects": [
            {"id": "CB", "name": "Cellular", "kind": "beam", "material": "A992",
             "profile": IPE300, "webOpenings": {"shape": "circular", "depth": 200,
                                                "spacing": 400}},
            {"id": "J1", "name": "Joist", "kind": "beam", "material": "A992", "profile": IPE300,
             "joist": {"topChord": {"profile": {"shape": "L", "depth": 50, "width": 50,
                                                "thickness": 5}},
                       "bottomChord": {"profile": {"shape": "L", "depth": 50, "width": 50,
                                                   "thickness": 5}},
                       "webs": {"profile": {"shape": "L", "depth": 50, "width": 50,
                                            "thickness": 5}}}},
            {"id": "J2", "name": "Pinned joist", "kind": "beam", "material": "A992",
             "profile": IPE300, "connection": {"type": "finPlate"},
             "joist": {"topChord": {"profile": {"shape": "L", "depth": 50, "width": 50,
                                                "thickness": 5}},
                       "bottomChord": {"profile": {"shape": "L", "depth": 50, "width": 50,
                                                   "thickness": 5}},
                       "webs": {"profile": {"shape": "L", "depth": 50, "width": 50,
                                            "thickness": 5}}}},
        ]
    }  # fmt: skip
    found = check_library("objects", json.dumps(objects), json.dumps(materials))
    warnings = [p for p in found if p.get("severity") == "warning"]
    assert any(p["index"] == 0 and "web openings" in p["message"] for p in warnings)
    assert any(p["index"] == 1 and "rigid ends" in p["message"] for p in warnings)
    assert not any(p["index"] == 2 for p in warnings)  # simple ends: no frame action
    assert all(p.get("severity") == "warning" for p in found if "covered" in p["message"])


# ─────────────────────────────── W4C-9: steel edge beams as chords ───────────────────────────────


def test_steel_edge_beams_carry_the_chord(bnbc):
    beam = Beam.model_validate(
        {"id": "SB", "name": "IPE 300", "material": "A992", "kind": "beam", "profile": IPE300}
    )
    element = SimpleNamespace(id="B1", type="SB")
    capacity, weakest = diaphragms._weakest(
        [(element, None, None)], {"SB": beam}, {"A992": STEEL}, 0.9
    )
    # φ Ag Fy of an IPE 300 (Ag about 5380 mm² with its fillets; φ 0.9 of tension yielding)
    assert weakest == "B1" and capacity == pytest.approx(0.9 * 345 * 5380, rel=0.05)
    text = diaphragms._beams_text(
        [(element, None, None)], {"SB": beam}, {"A992": STEEL}, "B1", "edge"
    )
    assert "axial strength" in text and "bars" not in text


# ─────────────────────────────── W4C-10: slab bracing of steel beams ───────────────────────────────


def _beam_on_columns():
    """A 6 m beam B1 along X in two elements on two columns; no shells (the slab is carried as
    loads, not analysed)."""
    nodes = [
        {"id": 1, "coords": [0.0, 0.0, 3.0], "restraint": [False] * 6},
        {"id": 2, "coords": [3.0, 0.0, 3.0], "restraint": [False] * 6},
        {"id": 3, "coords": [6.0, 0.0, 3.0], "restraint": [False] * 6},
        {"id": 10, "coords": [0.0, 0.0, 0.0], "restraint": [True] * 6},
        {"id": 11, "coords": [6.0, 0.0, 0.0], "restraint": [True] * 6},
    ]
    elements = [
        {"id": 1, "name": "B1", "type": "ElasticBeamColumn", "nodes": [1, 2]},
        {"id": 2, "name": "B1#2", "type": "ElasticBeamColumn", "nodes": [2, 3]},
        {"id": 5, "name": "C1", "type": "ElasticBeamColumn", "nodes": [10, 1]},
        {"id": 6, "name": "C2", "type": "ElasticBeamColumn", "nodes": [11, 3]},
    ]
    axes = np.eye(3)
    pieces = [
        _Piece(n, k + 1, 3.0, True, axes, [np.zeros((11, 6))],
               start=np.array([3.0 * k, 0, 3.0]), end=np.array([3.0 * (k + 1), 0, 3.0]))
        for k, n in enumerate(["B1", "B1#2"])
    ]  # fmt: skip
    return {"nodes": nodes, "elements": elements}, pieces


def test_slab_braces_the_top_flange_of_the_beam_it_rests_on():
    project, pieces = _beam_on_columns()
    plain = member_lengths(project, pieces)
    assert plain.ltb_top.longest() == pytest.approx(6.0)  # before: Lb = 6000 mm
    braced = member_lengths(project, pieces, options=LengthOptions(slab_on_top=True))
    assert braced.ltb_top.longest() <= SLAB_BRACE_SPACING + 1e-9
    # Hogging near the supports: the bottom flange keeps the frame's brace points.
    assert braced.ltb_bottom.points == pytest.approx([0.0, 6.0])
    assert any("slab" in n for n in braced.notes)
    # The project's option to take no slab bracing still wins.
    off = LengthOptions(slab_on_top=True, slab_braces_top_flange=False)
    assert member_lengths(project, pieces, options=off).ltb_top.longest() == pytest.approx(6.0)


def test_beams_under_a_slab_are_found_in_the_building_model():
    building = BuildingModel.model_validate(
        {
            "stories": [{"id": "L1", "name": "L1", "elevation": 3000}],
            "elements": [
                {"kind": "slab", "id": "S1", "type": "S150", "elevation": 3000,
                 "boundary": [[0, 0], [6000, 0], [6000, 5000], [0, 5000]]},
                {"kind": "beam", "id": "B-edge", "type": "SB", "elevation": 3000,
                 "start": [0, 0], "end": [6000, 0]},
                {"kind": "beam", "id": "B-roof", "type": "SB", "elevation": 6000,
                 "start": [0, 0], "end": [6000, 0]},
                {"kind": "beam", "id": "B-out", "type": "SB", "elevation": 3000,
                 "start": [0, 8000], "end": [6000, 8000]},
            ],
        }
    )  # fmt: skip
    assert slab_carried_beams(building, {}) == {"B-edge"}


def test_wizard_summary_has_column_and_footing_rows_for_a_steel_frame():
    from saengine.library.generator import footing_sizes, generate_building

    assert footing_sizes(
        [{"type": "isolated", "length": 1200, "width": 1200, "thickness": 450}] * 2
    ) == ["2 isolated 1.2 × 1.2 × 0.45 m"]
    result = generate_building(
        {"gridsX": [6000, 6000], "gridsY": [5000, 5000], "storyCount": 2,
         "system": "steelMomentFrame"}
    )  # fmt: skip
    summary = result["summary"]
    assert summary["columnTypes"] and all(
        v.startswith("SC-") for v in summary["columnTypes"].values()
    )
    assert set(summary["columnReasons"]) == set(summary["columnTypes"])
    assert summary["footingTypes"]


# ─────────────────────────────── W4C-11: membrane loads ───────────────────────────────


def test_membrane_cases_without_their_load_are_not_passed_silently(us):
    bare = membranes.check_membrane("M", Membrane(id="M", name="Sail", material="PVC", divisions=8))
    skipped = [c for c in bare["checks"] if c.get("status") == "noLoad"]
    assert {c["combination"] for c in skipped} == {
        "Prestress + snow", "Prestress + wind pressure", "Prestress + wind suction"
    }  # fmt: skip
    assert all(c["flag"] and c["ok"] for c in skipped)
    assert len(bare["membrane"]["missingLoads"]) == 3
    _, _, notes = membranes.design_types(
        {"M": Membrane(id="M", name="S", material="PVC", divisions=8)}
    )
    assert notes and "no snow load given" in notes[0]
    loaded = membranes.check_membrane(
        "M", Membrane(id="M", name="Sail", material="PVC", divisions=8, snow=1.0,
                      windPressure=1.0, windSuction=1.5)
    )  # fmt: skip
    cable = {
        c["combination"]: c["demand"] for c in loaded["checks"] if c["name"].startswith("Edge")
    }
    # Each case carries its own load: the four results differ.
    assert len(set(cable.values())) == 4 and not loaded["membrane"]["missingLoads"]


# ─────────────────────────────── W4C-17: missing mapped hazard ───────────────────────────────


def test_missing_sds_sd1_fails_the_derive_step():
    from saengine.pipeline.run_all import missing_hazard

    settings = default_project_settings("T").model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert missing_hazard(json.dumps(settings)) is None  # BNBC: Z from the location
    aci = {**settings, "codePack": "aci318-asce7-22"}
    aci["site"] = {**aci["site"], "location": "custom", "zoneCoefficient": 0.2, "windSpeed": 50}
    aci["wind"] = {**aci["wind"], "exposure": "C"}
    message = missing_hazard(json.dumps(aci))
    assert message and "SDS" in message
    # No earthquake in any combination: nothing is missing.
    quiet = {**aci, "combinations": [c | {"EX": 0, "EY": 0} for c in aci["combinations"]]}
    assert missing_hazard(json.dumps(quiet)) is None


# ─────────────────────────────── W4C-25: joists with frame action ───────────────────────────────


def _joist_stations(end_moment: float) -> list[Stations]:
    s = np.linspace(0, 6.0, 21)
    m = -100e6 * 4 * s * (6.0 - s) / 36.0 + end_moment
    z = np.zeros_like(s)
    return [Stations("ULS", s, z, m, z, z, z, [f"at {x:.1f}" for x in s])]


def test_joist_with_end_moments_is_flagged():
    assert steel_joists.frame_action(_joist_stations(0.0)) is None
    row = steel_joists.frame_action(_joist_stations(60e6))
    assert row is not None and row["flag"] and row["ok"] and "simple connection" in row["note"]

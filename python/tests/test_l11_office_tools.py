"""Alpha 9 L11: the office tools (written with the track, run in the alpha 9 test pass).

4D programme durations and dates, cut and fill of a sloped TIN, a takeoff calibration, phasing,
MEP fabrication detailing, the sun and the daylight / road noise formulas, the mepFabrication
pack table.
"""

from __future__ import annotations

import itertools
import json
import math
import xml.etree.ElementTree as ET
from datetime import date

import numpy as np
import pytest

from saengine.boq.construction_schedule import (
    ConstructionSchedule,
    element_dates,
    generate,
    parse_productivity,
    schedule,
    to_csv,
    to_mspdi,
)
from saengine.boq.quantities import GROUPS
from saengine.boq.takeoff import Takeoff, bill_items, calibrate, measure, scale_of
from saengine.gis.terrain import cut_fill, elevation_at, read_xyz, triangulate
from saengine.library.bim import BuildingModel


def _building() -> BuildingModel:
    return BuildingModel.model_validate(
        {
            "stories": [
                {"id": "L0", "name": "Ground", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
                {"id": "L2", "name": "Level 2", "elevation": 6000},
            ],
            "elements": [
                {"id": "C1", "kind": "column", "type": "C", "position": [0, 0], "bottom": 0,
                 "top": 3000},
                {"id": "C2", "kind": "column", "type": "C", "position": [0, 0], "bottom": 3000,
                 "top": 6000},
                {"id": "S1", "kind": "slab", "type": "S",
                 "boundary": [[0, 0], [5000, 0], [5000, 5000]], "elevation": 3000},
                {"id": "S2", "kind": "slab", "type": "S",
                 "boundary": [[0, 0], [5000, 0], [5000, 5000]], "elevation": 6000},
            ],
        }
    )  # fmt: skip


BILL = {
    "items": [
        {"group": "concrete", "kind": "column", "unit": "m3", "description": "Columns",
         "quantity": 30, "breakdown": [{"element": "C1", "story": "L1", "quantity": 15},
                                       {"element": "C2", "story": "L2", "quantity": 15}]},
        {"group": "concrete", "kind": "slab", "unit": "m3", "description": "Slabs",
         "quantity": 160, "breakdown": [{"element": "S1", "story": "L1", "quantity": 80},
                                        {"element": "S2", "story": "L2", "quantity": 80}]},
        {"group": "masonry", "kind": "wall", "unit": "m3", "description": "Brick",
         "quantity": 32, "breakdown": [{"element": "W1", "story": "L1", "quantity": 16},
                                       {"element": "W2", "story": "L2", "quantity": 16}]},
        {"group": "earthwork", "kind": "excavation", "unit": "m3", "description": "Excavation",
         "quantity": 240, "breakdown": [{"element": "F1", "quantity": 240}]},
    ]
}  # fmt: skip


# ─────────────────────────────── 4D scheduling ───────────────────────────────


def test_schedule_durations_from_quantities_and_productivity() -> None:
    """Duration = Σ quantity / (perDay x crews), rounded up: the sample's rates (excavation 120
    m³/day, column concrete 15 m³/day, other concrete 40 m³/day, brick work 8 m³/day x 2)."""
    p = parse_productivity(None)
    s = generate(_building(), BILL, p, date(2026, 11, 7), 7.0)
    acts = {a.id: a for a in s.activities}
    assert acts["excavation"].days == 2  # 240 / 120
    assert acts["vertical:L1"].days == 1  # 15 / 15
    assert acts["floor:L1"].days == 2  # 80 / 40
    assert acts["masonry:L1"].days == 1  # 16 / (8 x 2)
    assert acts["floor:L1"].elements == ["S1"]
    assert [lk.source for lk in acts["vertical:L1"].links] == ["excavation"]


def test_schedule_floor_cycle_and_cast_day() -> None:
    """Level 2's floor starts no earlier than level 1's plus the cycle (SS), and finishes on its
    casting day (alpha 9 P2) when that is later; the calendar skips Fridays (sample work days)."""
    p = parse_productivity(None)
    start = date(2026, 11, 7)  # a Saturday
    s = generate(_building(), BILL, p, start, 7.0, {"Level 2": 20})
    acts = {a.id: a for a in s.activities}
    floor2 = acts["floor:L2"]
    assert ("floor:L1", "SS", 6.0) in [(lk.source, lk.type, lk.lag) for lk in floor2.links]
    # Day 20 is Friday 27 November (not worked): cast on Saturday 28, started 2 working days on.
    assert floor2.earlyFinish == date(2026, 11, 28)
    assert floor2.earlyStart == date(2026, 11, 26)
    assert floor2.critical
    assert all(a.earlyStart.weekday() != 4 for a in s.activities)  # no Friday starts
    assert s.finish == max(a.earlyFinish for a in s.activities)


def test_schedule_keeps_edits_and_exports() -> None:
    p = parse_productivity(None)
    s = generate(_building(), BILL, p, date(2026, 11, 7))
    s.activities[0].duration = 5
    again = generate(_building(), BILL, p, date(2026, 11, 7), previous=s)
    assert {a.id: a for a in again.activities}["excavation"].working_days == 5
    xml = to_mspdi(again)
    root = ET.fromstring(xml.split("\n", 1)[1])
    ns = {"p": "http://schemas.microsoft.com/project"}
    tasks = root.findall("p:Tasks/p:Task", ns)
    assert len(tasks) == len(again.activities)
    assert tasks[0].find("p:Duration", ns).text == "PT40H0M0S"  # 5 days of 8 h
    assert to_csv(again).splitlines()[0].startswith("ID,Name,Level")
    assert element_dates(again)["S1"]["activity"] == "floor:L1"


def test_schedule_loop_is_reported() -> None:
    text = json.dumps(
        {
            "start": "2026-11-07",
            "activities": [
                {"id": "a", "name": "A", "category": "floor", "links": [{"from": "b"}]},
                {"id": "b", "name": "B", "category": "floor", "links": [{"from": "a"}]},
            ],
        }
    )
    with pytest.raises(ValueError, match="loop"):
        schedule(ConstructionSchedule.model_validate_json(text))


# ─────────────────────────────── terrain cut and fill ───────────────────────────────


def test_cut_fill_of_a_sloped_tin_is_exact() -> None:
    """z = 0.1 x over a 10 m square, the platform 2-8 m square at 500 mm: the cut is
    ∫(0.1x - 500) over 5000 < x < 8000 times 6 m = 2.7 m³, the fill the same by symmetry."""
    pts = np.array(
        [[x, y, 0.1 * x] for x in range(0, 10001, 2000) for y in range(0, 10001, 2000)], float
    )
    tri = triangulate(pts)
    found = cut_fill(pts, tri, [(2000, 2000), (8000, 2000), (8000, 8000), (2000, 8000)], 500.0)
    assert found["cut"] == pytest.approx(2.7, rel=1e-9)
    assert found["fill"] == pytest.approx(2.7, rel=1e-9)
    assert found["area"] == pytest.approx(36.0)
    assert found["uncovered"] == pytest.approx(0.0, abs=1e-9)
    assert elevation_at(pts, tri, 3000, 3000) == pytest.approx(300.0)


def test_cut_fill_of_a_platform_partly_off_the_survey() -> None:
    pts = np.array([[0, 0, 1000], [10000, 0, 1000], [0, 10000, 1000], [10000, 10000, 1000]], float)
    tri = triangulate(pts)
    found = cut_fill(pts, tri, [(5000, 0), (15000, 0), (15000, 10000), (5000, 10000)], 0.0)
    assert found["cut"] == pytest.approx(5 * 10 * 1.0)  # 50 m² at 1 m
    assert found["fill"] == pytest.approx(0.0)
    assert found["uncovered"] == pytest.approx(50.0)


def test_xyz_reader_skips_headers() -> None:
    assert read_xyz("x,y,z\n1,2,3\n4 5 6\n# note\n").tolist() == [[1, 2, 3], [4, 5, 6]]


# ─────────────────────────────── PDF takeoff ───────────────────────────────


def test_takeoff_calibration_and_measures() -> None:
    """100 paper mm between the two points is 10 m: 1:100; a 50 mm line times 2 m high is
    10 m², a 10 mm square times 100 mm deep is 0.1 m³, two marks are 2 nr."""
    cal = calibrate([0, 0], [100, 0], 10000)
    assert cal["scale"] == pytest.approx(100.0)
    t = Takeoff.model_validate(
        {
            "sheets": [{"id": "A", "file": "site.pdf", "calibration": cal["calibration"]}],
            "items": [
                {"id": "T1", "sheet": "A", "kind": "length", "points": [[0, 0], [50, 0]],
                 "description": "Fence", "height": 2000},
                {"id": "T2", "sheet": "A", "kind": "area",
                 "points": [[0, 0], [10, 0], [10, 10], [0, 10]], "description": "Paving",
                 "group": "concrete", "depth": 100},
                {"id": "T3", "sheet": "A", "kind": "count", "points": [[0, 0], [1, 1]],
                 "description": "Lamp posts", "group": "mep"},
                {"id": "T4", "sheet": "A", "kind": "length", "points": [[0, 0], [10, 0]],
                 "description": "Fence", "height": 2000, "deduct": True},
            ],
        }
    )  # fmt: skip
    sheet = t.sheets[0]
    assert scale_of(sheet) == pytest.approx(100.0)
    assert measure(t.items[0], sheet) == (pytest.approx(10.0), "m2")
    assert measure(t.items[1], sheet) == (pytest.approx(0.1), "m3")
    assert measure(t.items[2], sheet) == (2.0, "nr")
    items, notes = bill_items(t, GROUPS)
    fence = next(i for i in items if i["description"].startswith("Fence"))
    assert fence["quantity"] == pytest.approx(8.0)  # 10 m² less the 2 m² deducted
    assert fence["origin"] == "drawing" and fence["code"] == "A.D01"
    assert {i["code"] for i in items} == {"C.D01", "A.D01", "P.D01"}
    assert notes


def test_takeoff_uses_the_drawing_scale_without_calibration() -> None:
    t = Takeoff.model_validate(
        {"sheets": [{"id": "A", "file": "a.pdf", "scale": 50}],
         "items": [{"id": "T", "sheet": "A", "kind": "length", "points": [[0, 0], [0, 20]],
                    "description": "Kerb", "group": "concrete"}]}
    )  # fmt: skip
    assert measure(t.items[0], t.sheets[0]) == (pytest.approx(1.0), "m")


# ─────────────────────────────── phasing ───────────────────────────────


def test_phase_status_and_bill() -> None:
    from saengine.project.phasing import Phasing, phase_bill, status_in, visible_in

    ph = Phasing.model_validate(
        {"elements": {"C1": {"created": "existing", "demolished": "new"},
                      "C2": {"created": "existing"}}}
    )  # fmt: skip
    assert status_in(ph, "C1", "new") == "demolished"
    assert status_in(ph, "C2", "new") == "existing"
    assert status_in(ph, "C3", "new") == "new"
    assert status_in(ph, "C3", "existing") == "future"
    # Built in the phase shown: new in it (status_in).
    assert visible_in(ph, ["C1", "C2", "C3"], "existing") == {"C1": "new", "C2": "new"}
    bill = {"items": [{"code": "C.01", "group": "concrete", "description": "x", "unit": "m3",
                       "quantity": 3, "breakdown": [{"element": e, "quantity": 1}
                                                    for e in ("C1", "C2", "C3")]}]}  # fmt: skip
    split = phase_bill(bill, ph)
    new = split["phases"][1]
    assert new["new"][0]["quantity"] == 1.0
    assert new["demolished"][0]["quantity"] == 1.0
    assert split["existing"][0]["quantity"] == 1.0


def test_phasing_rejects_demolition_before_creation() -> None:
    from saengine.project.phasing import Phasing

    with pytest.raises(ValueError, match="demolished before"):
        Phasing.model_validate({"elements": {"C1": {"created": "new", "demolished": "existing"}}})


# ─────────────────────────────── MEP fabrication ───────────────────────────────


def test_fabrication_pieces_fittings_hangers() -> None:
    """A 100 mm fire main with a 90° bend and a branch: long-radius elbow (1.5 D, take-out
    150 mm), 6 m stock, hangers at no more than the pack's 5 m (BNBC 2020 Part 4 Sec 4.2.3.14),
    each designed for five times the water-filled weight plus 110 kg."""
    from saengine.mep.fabrication import FabricationOptions, fabrication

    bim = {
        "stories": [
            {"id": "L0", "name": "G", "elevation": 0},
            {"id": "L1", "name": "1", "elevation": 3000},
        ],
        "elements": [],
    }
    mep = {"schema": "saengine.mep/1",
           "fire": {"mains": [{"id": "FM1", "story": "L0",
                               "path": [[0, 0], [10000, 0], [10000, 8000]], "diameter": 100},
                              {"id": "FM2", "story": "L0", "path": [[5000, 0], [5000, -4000]],
                               "diameter": 65}]}}  # fmt: skip
    found = fabrication(json.dumps(mep), json.dumps(bim), None, FabricationOptions())
    run = next(r for r in found["runs"] if r["id"] == "FM1")
    assert [p["length"] for p in run["pieces"]] == [6000, 3850, 6000, 1850]
    assert [f["type"] for f in run["fittings"]] == ["elbow 90°", "tee"]
    stations = [h["station"] for h in run["hangers"]]
    assert all(b - a <= 5000 + 1e-6 for a, b in itertools.pairwise(stations))
    assert run["hangers"][0]["station"] == pytest.approx(600)
    assert all(h["load"] > 110 for h in run["hangers"])
    assert "4.2.3.14" in run["supportRule"]


def test_pack_table_mep_fabrication_values() -> None:
    """BNBC 2020 Part 8 Table 8.5.14 (p1063), Part 8 Sec 2.11.4.8(b) (p911), Part 4 Sec 4.2.3.14
    (part 1 p330)."""
    from saengine.codes import registry

    t = registry.load("bnbc2020").table("mepFabrication")
    gi = next(r for r in t.pipeSupports if r.material == "GI")
    assert (gi.horizontal, gi.vertical) == (3500, 4500)
    pvc = next(r for r in t.pipeSupports if r.material == "uPVC")
    assert (pvc.horizontal, pvc.vertical) == (1000, 1000)
    assert [r.spacing for r in t.ductSupports] == [3700, 6000]
    assert (t.fireMains.spacing, t.fireMains.loadFactor, t.fireMains.extraMass) == (5000, 5, 110)


# ─────────────────────────────── sun, daylight, noise ───────────────────────────────


def test_sun_at_equinox_noon() -> None:
    """At the March equinox the sun at solar noon stands at 90° less the latitude, due south."""
    from saengine.environment.solar import local_time, sun_position

    az, el = sun_position(51.5, 0.0, local_time(date(2026, 3, 20), 12.1, 0))
    assert el == pytest.approx(90 - 51.5, abs=0.6)
    assert az == pytest.approx(180, abs=3)


def test_massing_blocks_rays_and_casts_shadows() -> None:
    from shapely.geometry import box

    from saengine.environment.solar import Massing, Prism, shadow_polygons, to_grid

    m = Massing([Prism(box(0, 0, 10000, 10000), 0, 30000)])
    east = to_grid(90, 45)
    pts = np.array([[-5000, 5000, 1.0], [20000, 5000, 1.0]])
    assert m.blocked(pts, east).tolist() == [True, False]
    shadow = shadow_polygons(m.prisms, east, 0.0)
    assert shadow.area / 1e6 == pytest.approx(400.0)  # 30 m tall at 45°: 30 m long, 10 m wide
    x = np.array([[-5000, 5000, 1000.0]])
    assert not m.blocked(x, np.array([1.0, 0, 0]), reach=4000)[0]
    assert m.blocked(x, np.array([1.0, 0, 0]), reach=6000)[0]


def test_daylight_factor_formula() -> None:
    """DF = T Aw θ M / (A (1 - R²)): 0.68 x 4 x 80 x 0.9 / (100 x 0.75) = 2.61 %."""
    from saengine.environment.daylight import average_daylight_factor

    assert average_daylight_factor(4.0, 80, 100, 0.68, 0.9, 0.5) == pytest.approx(2.6112)


def test_road_noise_crtn_form() -> None:
    """10 000 vehicles in 18 h at 50 km/h, 10 % heavy, 10 m from the kerb at 1.5 m: 29.1 + 40
    + (66 + 3.01 - 68.8) - 10 log10(13.54 / 13.5) + 2.5 = 71.8 dB(A)."""
    from saengine.environment.road_noise import road_level
    from saengine.environment.service import defaults

    k = defaults()["roadNoise"]
    expected = 29.1 + 40 + 33 * math.log10(100) + 10 * math.log10(2) - 68.8
    expected -= 10 * math.log10(math.hypot(13.5, 1.0) / 13.5)
    assert road_level(10000, 50, 10, 0, 10, 1.5, k) == pytest.approx(expected + 2.5)


# ─────────────────────────────── cost optimisation ───────────────────────────────


def test_pricer_and_bar_mass() -> None:
    """Unit prices come from the schedule of rates as the costing finds them (a rate per cft
    prices m³ x 35.3147); bars weigh π d²/4 x 7850 kg/m³ along the member."""
    from saengine.boq.costing import RateSchedule
    from saengine.design.cost_optimisation import Pricer, bar_kg

    schedule = RateSchedule.model_validate(
        {"items": [{"code": "1", "description": "Concrete", "unit": "cft", "rate": 10,
                    "match": {"group": "concrete"}}]}
    )  # fmt: skip
    pricer = Pricer(schedule)
    assert pricer.price("concrete", "beam", "m3", "C25") == pytest.approx(353.147)
    assert pricer.price("formwork", "beam", "m2") is None
    assert pricer.missing == {"formwork beam (m2)"}
    bars = {"longitudinal": [{"position": "bottom", "count": 2, "dia": 20}]}
    assert bar_kg(bars, 1000.0, 300, 500) == pytest.approx(2 * math.pi * 100 * 7850e-6)


def test_apply_optimisation_changes_only_cheaper_accepted_groups() -> None:
    from saengine.design.cost_optimisation import apply_optimisation

    objects = {"objects": [
        {"id": "B1", "kind": "beam", "material": "C25",
         "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500}},
        {"id": "B2", "kind": "beam", "material": "C25",
         "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500}},
    ]}  # fmt: skip
    result = {"groups": [
        {"type": "B1", "status": "cheaper", "best": {"b": 300, "h": 550, "material": "C30",
                                                     "label": "300 x 550 mm, C30"}},
        {"type": "B2", "status": "unchanged", "best": {"b": 300, "h": 500, "material": "C25"}},
    ]}  # fmt: skip
    out = apply_optimisation(json.dumps(objects), result)
    data = json.loads(out["objectsText"])
    assert data["objects"][0]["profile"]["yDim"] == 550
    assert data["objects"][0]["material"] == "C30"
    assert data["objects"][1]["profile"]["yDim"] == 500
    assert [c["type"] for c in out["changes"]] == ["B1"]

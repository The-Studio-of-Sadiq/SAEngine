"""Openings the HVAC ducts need through beams and slabs (stream H2), worked out by hand.

The synthetic project of :func:`test_hvac_air.hvac_project`: beam B1 400 x 900 under L1 (top at
3800, bottom at 2900) along y = 5000 from x = 0 to 8000; 150 mm slabs S1 (L1) and S2 (L2).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from test_hvac_air import hvac_project

from saengine.hvac.openings import beam_opening_for, hvac_duct_openings

USE = [{"story": "GF", "use": "officeSpace"}]


def test_a_duct_through_the_beam_web(tmp_path: Path) -> None:
    # Exhaust duct (no insulation) 300 x 150, underside 3275 above GF: its centre at 3350,
    # 450 above the beam's bottom (2900). It crosses B1 square at x = 4000: an opening of
    # 300 + 2 x 50 = 400 along the beam, 150 + 2 x 50 = 250 high (h/3 = 300), 4000 from B1's
    # start.
    hvac = {"system": "vrf", "stories": USE, "ducts": [
        {"id": "D1", "system": "exhaust", "width": 300, "height": 150, "story": "GF",
         "bottom": 3275, "path": [[4000, 1000], [4000, 9000]]}]}  # fmt: skip
    result = hvac_duct_openings(hvac_project(tmp_path / "p", hvac))
    (opening,) = result["openings"]
    assert opening["host"] == "B1"
    assert opening["shape"] == "rectangle"
    assert (opening["width"], opening["height"]) == (400, 250)
    assert opening["position"] == {"distance": 4000.0, "elevation": 450.0}
    assert result["conflicts"] == []
    (crossing,) = result["crossings"]
    assert all(c["ok"] for c in crossing["checks"] if not c["flag"])


def test_an_oblique_crossing_is_longer_along_the_beam() -> None:
    # At 45° through a 400 mm web: the duct's section in the beam face is 300 / sin 45° =
    # 424.3 long and it shifts 400 x cot 45° = 400 along the beam through the web: 824.3,
    # + 2 x 50 = 924.3, up to 950.
    axis = ((0, 5000), (8000, 5000))
    opening = beam_opening_for(axis, 2900, (4000, 5000), (1, 1), 300, 150, False, 3350, 50, 400)
    assert opening["width"] == 950 and opening["height"] == 250
    assert opening["need"][0] == pytest.approx(300 / math.sqrt(0.5) + 400)
    assert opening["sine"] == pytest.approx(math.sqrt(0.5))
    # A round duct crossing square takes a circle of D + 100.
    circle = beam_opening_for(axis, 2900, (4000, 5000), (0, 1), 250, 250, True, 3350, 50, 400)
    assert circle["shape"] == "circle" and circle["diameter"] == 350
    # At 75°: 250 / sin 75° + 400 cot 75° = 258.8 + 107.2 = 366.0 along the beam, 116 over D:
    # a rectangle of 366.0 + 100 -> 500 by 250 + 100 = 350.
    d75 = (math.cos(math.radians(75)), math.sin(math.radians(75)))
    oblique = beam_opening_for(axis, 2900, (4000, 5000), d75, 250, 250, True, 3350, 50, 400)
    assert oblique["need"][0] == pytest.approx(366.0, abs=0.1)
    assert oblique["shape"] == "rectangle"
    assert (oblique["width"], oblique["height"]) == (500, 350)


def test_an_oblique_duct_through_the_project_beam(tmp_path: Path) -> None:
    # Exhaust 300 x 150 from (2000, 1000) to (6000, 9000) crosses B1 (y = 5000) at x = 4000;
    # direction (1, 2)/sqrt 5: sin = 2/sqrt 5 = 0.894, cot = 0.5. Along the beam 300/0.894 +
    # 400 x 0.5 = 335.4 + 200 = 535.4, + 100 = 635.4 -> 650; 250 high. It passes h/3 = 300.
    hvac = {"system": "vrf", "stories": USE, "ducts": [
        {"id": "D1", "system": "exhaust", "width": 300, "height": 150, "story": "GF",
         "bottom": 3275, "path": [[2000, 1000], [6000, 9000]]}]}  # fmt: skip
    result = hvac_duct_openings(hvac_project(tmp_path / "p", hvac))
    (opening,) = result["openings"]
    assert (opening["width"], opening["height"]) == (650, 250)
    assert opening["position"]["distance"] == pytest.approx(4000.0)


def test_a_moved_duct_gets_its_opening_again(tmp_path: Path) -> None:
    # HD-D1-B1-1 was accepted at x = 4000; the duct now runs at x = 6500: the opening is
    # proposed again at distance 6500 under the same id (it replaces the saved one).
    saved = {"id": "HD-D1-B1-1", "host": "B1", "kind": "opening", "shape": "rectangle",
             "width": 400, "height": 250, "position": {"distance": 4000, "elevation": 450}}  # fmt: skip
    duct = {"id": "D1", "system": "exhaust", "width": 300, "height": 150, "story": "GF",
            "bottom": 3275, "path": [[6500, 1000], [6500, 9000]]}  # fmt: skip
    root = hvac_project(tmp_path / "a", {"stories": USE, "ducts": [duct]}, openings=[saved])
    result = hvac_duct_openings(root)
    (opening,) = result["openings"]
    assert opening["id"] == "HD-D1-B1-1"
    assert opening["position"] == {"distance": 6500.0, "elevation": 450.0}
    assert result["crossings"][0]["replaces"] == "HD-D1-B1-1"
    assert result["stale"] == []
    # The duct no longer crosses B1 at all: the saved opening is stale.
    short = {**duct, "path": [[6500, 1000], [6500, 4000]]}
    root = hvac_duct_openings(
        hvac_project(tmp_path / "b", {"stories": USE, "ducts": [short]}, openings=[saved])
    )
    assert root["openings"] == [] and root["stale"] == ["HD-D1-B1-1"]


def test_a_riser_slab_opening_that_fails_is_a_conflict(tmp_path: Path) -> None:
    # A 7900 x 4000 riser at (4000, 2500) in the 8 x 10 m slabs: its 8000 x 4100 opening runs
    # out of the slab: not proposed, a conflict with the option of a shaft.
    riser = {"id": "R1", "system": "supply", "width": 7900, "height": 4000, "story": "GF",
             "path": [[4000, 2500]], "riser": {"fromStory": "GF", "toStory": "L2"}}  # fmt: skip
    result = hvac_duct_openings(hvac_project(tmp_path / "p", {"ducts": [riser]}))
    assert result["openings"] == []
    assert sorted(c["slab"] for c in result["conflicts"]) == ["S1", "S2"]
    for conflict in result["conflicts"]:
        assert not all(c["ok"] for c in conflict["checks"] if not c.get("flag"))
        assert conflict["options"][0]["kind"] == "inShaft"


def test_split_without_a_flow_keeps_the_free_area(tmp_path: Path) -> None:
    # 1200 x 500 supply duct with no flow: h/3 = 300 leaves 300 - 100 - 50 = 150 mm. Free area
    # 0.6 m² in ducts 150 deep at most 4:1 (600 wide): 6 ducts of 600000 / 6 / 150 = 666.7 ->
    # 700 wide, still over 4:1, so not ok, but not "no room".
    hvac = {"system": "vrf", "stories": USE, "ducts": [
        {"id": "D2", "system": "supply", "width": 1200, "height": 500, "story": "GF",
         "path": [[6000, 1000], [6000, 9000]]}]}  # fmt: skip
    result = hvac_duct_openings(hvac_project(tmp_path / "p", hvac))
    (conflict,) = result["conflicts"]
    split = next(o for o in conflict["options"] if o["kind"] == "split")
    assert (split["ducts"], split["width"], split["height"]) == (6, 700, 150)
    assert not split["ok"] and "no room" not in split["note"]
    # A 600 x 300 duct (0.18 m²): 2 ducts of 180000 / 2 / 150 = 600 wide, 4:1: ok.
    hvac["ducts"][0].update(width=600, height=300)
    hvac["ducts"][0]["path"] = [[6000, 1000], [6000, 9000]]
    result = hvac_duct_openings(hvac_project(tmp_path / "q", hvac))
    (conflict,) = result["conflicts"]
    split = next(o for o in conflict["options"] if o["kind"] == "split")
    assert (split["ducts"], split["width"], split["height"]) == (2, 600, 150) and split["ok"]


def test_a_duct_too_deep_for_the_beam_routes_below(tmp_path: Path) -> None:
    # Supply duct 1200 x 500 with 25 mm insulation: 1250 x 550 outside, its top 25 mm below the
    # soffit (3800 - 150 = 3650) by default: 3075 to 3625, through B1 (bottom 2900). The
    # opening would be 650 high > h/3 = 300: no web opening.
    # Route below: top at 2900 - 50 = 2850, outside bottom 2300, 2250 clear above a 50 mm
    # finish < 2440 (BNBC Part 3 Sec 1.14.2.1(b)): raise the floor by 190 to 3990.
    hvac = {"system": "vrf", "stories": USE, "ducts": [
        {"id": "D2", "system": "supply", "width": 1200, "height": 500, "story": "GF",
         "flow": 1.0, "path": [[6000, 1000], [6000, 9000]]}]}  # fmt: skip
    result = hvac_duct_openings(hvac_project(tmp_path / "p", hvac))
    assert result["openings"] == []
    (conflict,) = result["conflicts"]
    assert conflict["beam"] == "B1"
    assert conflict["ductTop"] == pytest.approx(3625)
    assert conflict["opening"]["height"] == 650
    depth = next(c for c in conflict["checks"] if "h/3" in c["name"])
    assert depth["demand"] == 650 and depth["capacity"] == pytest.approx(300) and not depth["ok"]
    options = {o["kind"]: o for o in conflict["options"]}
    below = options["routeBelow"]
    assert below["clearHeight"] == pytest.approx(2250)
    assert below["required"] == 2440
    assert below["bottom"] == pytest.approx(2325)  # the duct's own underside above GF
    assert not below["ok"]
    raise_ = options["increaseFloorHeight"]
    assert raise_["by"] == pytest.approx(190)
    assert raise_["floorToFloor"] == pytest.approx(3990)
    # Split: at most 300 - 100 - 50 = 150 mm deep ducts.
    split = options["split"]
    assert split["ok"] and split["height"] <= 150 and split["ducts"] >= 2
    assert not options["lowerToMidDepth"]["ok"]
    assert options["throughSlab"]["slabOpening"] == {"width": 1350, "height": 650}


def test_a_duct_below_the_beam_needs_no_opening(tmp_path: Path) -> None:
    hvac = {"system": "vrf", "stories": USE, "ducts": [
        {"id": "D3", "system": "exhaust", "width": 300, "height": 150, "story": "GF",
         "bottom": 2700, "path": [[4000, 1000], [4000, 9000]]}]}  # fmt: skip
    result = hvac_duct_openings(hvac_project(tmp_path / "p", hvac))
    assert result["openings"] == [] and result["crossings"] == []


def test_riser_slab_openings_unless_in_a_shaft(tmp_path: Path) -> None:
    # A 300 x 200 exhaust riser from GF to L2 at (2000, 2000) cuts S1 (L1) and S2 (L2): two
    # rectangles of 400 x 300.
    riser = {"id": "R1", "system": "exhaust", "width": 300, "height": 200, "story": "GF",
             "path": [[2000, 2000]], "riser": {"fromStory": "GF", "toStory": "L2"}}  # fmt: skip
    result = hvac_duct_openings(hvac_project(tmp_path / "a", {"ducts": [riser]}))
    hosts = sorted((o["host"], o["width"], o["height"]) for o in result["openings"])
    assert hosts == [("S1", 400, 300), ("S2", 400, 300)]
    assert all(o["position"] == {"x": 2000.0, "y": 2000.0} for o in result["openings"])
    shaft = {"id": "SH1", "outline": [[1500, 1500], [2500, 1500], [2500, 2500], [1500, 2500]],
             "fromStory": "GF", "toStory": "L2"}  # fmt: skip
    inside = hvac_duct_openings(hvac_project(tmp_path / "b", {"ducts": [riser]}, shafts=[shaft]))
    assert inside["openings"] == []


def test_an_existing_opening_is_not_proposed_again(tmp_path: Path) -> None:
    hvac = {"ducts": [
        {"id": "D1", "system": "exhaust", "width": 300, "height": 150, "story": "GF",
         "bottom": 3275, "path": [[4000, 1000], [4000, 9000]]}]}  # fmt: skip
    given = {"id": "OP1", "host": "B1", "kind": "opening", "shape": "rectangle", "width": 400,
             "height": 250, "position": {"distance": 4000, "elevation": 450}}  # fmt: skip
    result = hvac_duct_openings(hvac_project(tmp_path / "p", hvac, openings=[given]))
    assert result["openings"] == []
    assert result["crossings"][0]["existing"] == "OP1"

"""Flanged walls (saengine.design.wall_flanges): junctions and groups, effective flange widths
(BNBC 2020 Part 6 Sec 8.3.6.5(b), p. 1102), the composite section's strain compatibility by
hand, the summed forces, the boundary length in flanged sections (8.3.6.6(d)(ii), p. 1103) and
the wiring into wall_design.design_walls. Synthetic data only."""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from saengine.design import wall_design
from saengine.design import wall_flanges as F
from saengine.design import walls as W
from saengine.design.rc import Bar, bar_area
from saengine.fem.combinations import DesignCombination
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import BuildingModel

BARS = W.WallBars(25, 12, 200, 10, 200, 2)


def _t(height: float = 30_000.0):
    web = F.Leg("W1", (0, 0), (0, 3000), 250, BARS, "W250", 0, 3000)
    flange = F.Leg("W2", (-1500, 3000), (1500, 3000), 250, BARS, "W250", 0, 3000)
    (group,) = F.groups_of([web, flange])
    return group


def test_junctions_and_groups() -> None:
    a = F.Leg("A", (0, 0), (4000, 0), 200)
    b = F.Leg("B", (4000, 0), (4000, 3000), 200)  # L at A's end
    c = F.Leg("C", (2000, 0), (2000, -2000), 200)  # T on A's middle
    d = F.Leg("D", (1000, 1000), (1000, -1000), 200)  # X through A
    far = F.Leg("E", (9000, 0), (9000, 3000), 200)  # alone
    face = F.Leg("G", (4100, 1500), (6000, 1500), 200)  # drawn to B's face, not its line
    junctions = {(j.a, j.b): j for j in F.find_junctions([a, b, c, d, far, face])}
    assert junctions[("A", "B")].kind == "L"
    assert junctions[("A", "C")].kind == "T" and junctions[("A", "C")].sa == pytest.approx(2000)
    assert junctions[("A", "D")].kind == "X"
    assert junctions[("B", "G")].kind == "T"  # within half B's thickness of its centre line
    assert not any("E" in k for k in junctions)
    groups = F.groups_of([a, b, c, d, far, face])
    assert [g.id for g in groups] == ["A+B+C+D+G"]
    # Walls in different storeys do not meet.
    upper = F.Leg("U", (4000, 0), (4000, 3000), 200, top=6000, bottom=3000)
    lower = F.Leg("A", (0, 0), (4000, 0), 200, top=3000, bottom=0)
    assert F.groups_of([lower, upper]) == []


def test_effective_flange_width_by_hand() -> None:
    """8.3.6.5(b): from the web face, the smaller of half the distance to the adjacent web
    and 25 % of the total wall height."""
    group = _t()
    # hw = 30 m: 0.25 hw = 7.5 m, more than the flange: all of it (1375 mm each side of the
    # 250 mm web).
    (info,) = F.effective_section(group, (0, 1), 30_000, 25, 420).flanges
    assert info["overhang"] == [1375.0, 1375.0]
    # hw = 4 m: 0.25 hw = 1000 mm each side of the web: 250 + 2 x 1000 = 2250 mm effective.
    s = F.effective_section(group, (0, 1), 4000, 25, 420)
    (info,) = s.flanges
    assert info["overhang"] == [1000.0, 1000.0]
    assert (info["from"], info["to"]) == (375.0, 2625.0)
    # Area: web 250 x 3000 (to the flange's centre line) + flange 2250 x 250, less the 250 x
    # 125 overlap of the web with the flange's half thickness.
    assert s.gross_area == pytest.approx(250 * 3000 + 2250 * 250 - 250 * 125)
    # A C: two webs 2000 mm apart on one flange; half the clear distance between them
    # (2000 - 250) / 2 = 875 governs between them, 0.25 hw = 1000 outside.
    w1 = F.Leg("W1", (0, 0), (0, 3000), 250, BARS)
    w3 = F.Leg("W3", (2000, 0), (2000, 3000), 250, BARS)
    fl = F.Leg("W2", (-1500, 3000), (3500, 3000), 250, BARS)
    (c_group,) = F.groups_of([w1, w3, fl])
    s = F.effective_section(c_group, (0, 1), 4000, 25, 420)
    by_web = {i["web"]: i for i in s.flanges}
    assert by_web["W1"]["overhang"] == [1000.0, 875.0]
    assert by_web["W3"]["overhang"] == [875.0, 1000.0]
    assert "half the distance" in by_web["W1"]["rule"][1]


def _t_section() -> F.FlangedSection:
    """A T by hand: flange 1000 x 200 (y 800-1000), web 200 x 800 (y 0-800); 4 Ø16 at y = 950
    (x = ±150, ±450), 2 Ø20 at y = 50 (x = ±50); about the gross centroid."""
    poly = unary_union([box(-500, 800, 500, 1000), box(-100, 0, 100, 800)])
    yc = (200_000 * 900 + 160_000 * 400) / 360_000
    bars = [Bar(x, 950 - yc, bar_area(16), 16) for x in (-450, -150, 150, 450)]
    bars += [Bar(x, 50 - yc, bar_area(20), 20) for x in (-50, 50)]
    from shapely import affinity

    return F.FlangedSection(
        affinity.translate(poly, 0, -yc),
        tuple(bars),
        25.0,
        420.0,
        200_000.0,
        (0.0, yc),
        (0.0, 1.0),
        ["web"],
    )


def test_t_section_strain_compatibility_by_hand() -> None:
    s = _t_section()
    yc = 2440 / 3.6  # 677.78 mm
    assert s.origin[1] == pytest.approx(yc)
    surface = F.FlangedInteraction(s)
    # Compression at the flange (θ = 0), c = 150 mm: a = 0.85 x 150 = 127.5 mm in the flange.
    pn, sx, sy, eps_t = surface.actions(0.0, 150.0)
    cc = 0.85 * 25 * 1000 * 127.5  # 2 709 375 N at y = 1000 - 63.75
    top_strain = 0.003 * (150 - 50) / 150  # 0.002: 400 MPa, inside the block
    ft = (200_000 * top_strain - 0.85 * 25) * 4 * bar_area(16)
    fb = -420 * 2 * bar_area(20)  # 0.003 (150 - 950) / 150 = -0.016: yielded
    assert pn == pytest.approx(cc + ft + fb, rel=1e-9)
    hand = cc * (1000 - 63.75 - yc) + ft * (950 - yc) + fb * (50 - yc)
    assert sy == pytest.approx(hand, rel=1e-9) and sx == pytest.approx(0.0, abs=1.0)
    assert eps_t == pytest.approx(0.003 * (950 - 150) / 150)
    # c = 400 mm: a = 340 mm, the block is the flange and 140 mm of web.
    pn, _, sy, _ = surface.actions(0.0, 400.0)
    cf, cw = 0.85 * 25 * 200_000, 0.85 * 25 * 200 * 140
    # 0.003 (400 - 50) / 400 = 0.002625 > εy = 0.0021: the top bars yield.
    top = (420 - 0.85 * 25) * 4 * bar_area(16)
    bot = -420 * 2 * bar_area(20)  # 0.003 (400 - 950) / 400 = -0.0041
    assert pn == pytest.approx(cf + cw + top + bot, rel=1e-9)
    hand = cf * (900 - yc) + cw * (730 - yc) + top * (950 - yc) + bot * (50 - yc)
    assert sy == pytest.approx(hand, rel=1e-9)
    # Compression at the web's tip (θ = π): S points to -y; the senses differ (unsymmetric).
    pn2, _, sy2, _ = surface.actions(math.pi, 150.0)
    assert sy2 < 0 and pn2 < pn
    up = surface.capacity(0.0, (0, 1))
    down = surface.capacity(0.0, (0, -1))
    assert up > 0 and down > 0 and up != pytest.approx(down, rel=0.05)
    # The capacity at Pu = 0 matches the hand φMn of the flange-in-compression sense: pure
    # bending puts the neutral axis where Pn = 0 (found by bisection here as a check).
    mn, c = surface.nominal(0.0, (0, 1))
    pn0, _, _, eps0 = surface.actions(0.0, c)
    assert pn0 == pytest.approx(0.0, abs=50.0)
    assert up == pytest.approx(0.9 * mn, rel=0.02) and eps0 > 0.005


def test_rectangle_matches_the_pier_interaction() -> None:
    """A rectangle through the polygon code gives the walls module's own P-M diagram."""
    g = W.WallGeometry(3000, 250, 9000, 3000)
    section = W.pier_section(g, BARS, 25, 420)
    pier = W.PierInteraction(section)
    flanged = F.FlangedSection(
        Polygon(box(-125, -1500, 125, 1500)), section.bars, 25, 420, 200_000, (0, 0), (0, 1), ["W"]
    )
    surface = F.FlangedInteraction(flanged)
    for pu in (-500e3, 0.0, 2e6, 6e6):
        assert surface.capacity(pu, (0, 1)) == pytest.approx(pier.capacity(pu, "M3", 1), rel=0.01)
        assert surface.capacity(pu, (0, -1)) == pytest.approx(pier.capacity(pu, "M3", -1), rel=0.01)
    mn, c = surface.nominal(1e6, (0, 1))
    mn_r, c_r = pier.nominal(1e6, "M3", 1)
    assert mn == pytest.approx(mn_r, rel=1e-4) and c == pytest.approx(c_r, rel=1e-4)


def _cut(p: float, v2: float, m3: float, m2: float = 0.0, v3: float = 0.0) -> dict:
    return {"P": p, "V2": v2, "V3": v3, "T": 0.0, "M2": m2, "M3": m3}


def test_group_forces_sum_by_hand() -> None:
    group = _t()
    piers = {
        "W1": {
            "pier": "W1/L1/P1",
            "start": 0,
            "end": 3000,
            "cuts": {"bottom": {"E": _cut(1000, 200, 500)}},
        },
        "W2": {
            "pier": "W2/L1/P1",
            "start": 0,
            "end": 3000,
            "cuts": {"bottom": {"E": _cut(600, 50, 100, 20)}},
        },
    }
    (f,) = F.group_forces(group, piers, about=(0.0, 0.0))
    # W1 runs +y: M3 = 500 kN·m compresses its end (+y): S = (0, 500) kN·m; P 1000 kN at its
    # middle (0, 1500): S += (0, 1500) kN·m. W2 runs +x at y = 3000: M3 = 100 compresses +x,
    # M2 = 20 compresses its -e3 face: e3 = (0, 1) → -y: S = (100, -20); P 600 at (0, 3000).
    assert f.P == pytest.approx(1.6e6)
    assert f.Sx == pytest.approx(100e6)
    assert f.Sy == pytest.approx((500 + 1500 - 20 + 1800) * 1e6)
    assert (f.Vx, f.Vy) == pytest.approx((50e3, 200e3))
    # About another point: S' = S - P (point - about).
    assert f.moved((0, 1000)) == pytest.approx((100e6, f.Sy - 1.6e6 * 1000))


def test_boundary_length_in_flanged_sections() -> None:
    flange = F.Leg("W2", (0, 0), (1, 0), 250)
    # max(c - 0.1 lw, c/2) = max(600 - 300, 300) = 300; the flange: 250 + 300 mm into the web.
    assert F.boundary_length(600, 3000) == 300
    assert F.boundary_length(600, 3000, flange) == 550
    assert F.boundary_length(1200, 3000, flange) == 900


def test_flanged_checks_of_a_t_wall() -> None:
    group = _t()
    eq = "1.2D + 1.0L + 1.0EY"
    piers = {
        "W1": {
            "pier": "W1/L1/P1",
            "start": 0,
            "end": 3000,
            "cuts": {"bottom": {eq: _cut(1200, 600, 4000)}},
        },
        "W2": {
            "pier": "W2/L1/P1",
            "start": 0,
            "end": 3000,
            "cuts": {"bottom": {eq: _cut(900, 20, 50)}},
        },
    }
    forces = F.group_forces(group, piers, {eq})
    d = F.flanged_checks(group, forces, 25, 420, height=12_000, special=True, drift=0.01)
    names = [c["name"] for c in d.checks]
    assert names[0].startswith("Axial force and bending, flanged section")
    assert any(n.startswith("Shear along W1") for n in names)
    assert any(n.startswith("Boundary element at") for n in names)
    pm = d.checks[0]
    assert 0 < pm["utilisation"] < 99 and pm["combination"] == eq
    # Both directions have a section: web W1 (along y) and web W2 (along x).
    assert sorted(tuple(s.webs) for s in d.sections) == [("W1",), ("W2",)]
    assert {b["edge"] for b in d.boundary} == {"web", "flange"}
    assert all(b["method"] == "displacement" for b in d.boundary)


# ─────────────────────────────────────── design_walls wiring ───────────────────────────────────────

EQ = "1.2D + 1.0L + 1.0EX"
WALL_TYPE = {
    "id": "W250",
    "name": "Wall 250",
    "kind": "wall",
    "material": "C24.1",
    "thickness": 250,
    "reinforcement": {
        "material": "B420DWR",
        "cover": 25,
        "vertical": {"dia": 12, "spacing": 200},
        "horizontal": {"dia": 10, "spacing": 200},
        "layers": 2,
    },
}


def _pier(wall: str, lw: float, cut: dict) -> dict:
    return {
        "pier": f"{wall}/L1/P1",
        "wall": wall,
        "type": "W250",
        "storey": "L1",
        "label": "Base to Level 1",
        "bottom": 0.0,
        "top": 3000.0,
        "start": 0.0,
        "end": lw,
        "lw": lw,
        "tw": 250.0,
        "shells": [1 if wall == "W1" else 2],
        "holes": [],
        "spandrels": [],
        "cuts": {"bottom": {EQ: cut}, "top": {EQ: {**cut, "M3": cut["M3"] / 4}}},
    }


@pytest.mark.parametrize("brick", [False, True])
def test_design_walls_checks_the_t_as_flanged(monkeypatch, brick: bool) -> None:
    """With ``brick``: a brick wall (its type left structural, as the template makes it) built
    against W2's end neither joins the group nor drops it; a note says it is not a flange."""
    from saengine.design import wall_forces

    found = {
        "piers": [_pier("W1", 3000, _cut(1500, 400, 3000)), _pier("W2", 3000, _cut(800, 10, 20))],
        "spandrels": [],
        "sections": [],
        "notes": [],
    }
    monkeypatch.setattr(
        wall_forces,
        "design_combination_list",
        lambda *a, **k: ([DesignCombination(EQ, {"D": 1.2, "L": 1.0, "EX": 1.0})], None, "corners"),
    )
    monkeypatch.setattr(wall_forces, "wall_forces", lambda *a, **k: found)
    building = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
            ],
            "elements": [
                {
                    "id": "W1",
                    "type": "W250",
                    "kind": "wall",
                    "start": [0, 0],
                    "end": [0, 3000],
                    "bottom": 0,
                    "top": 3000,
                },
                {
                    "id": "W2",
                    "type": "W250",
                    "kind": "wall",
                    "start": [-1500, 3000],
                    "end": [1500, 3000],
                    "bottom": 0,
                    "top": 3000,
                },
            ],
        }
    )
    mats = {m.id: m for m in default_material_library().materials}
    objects = [WALL_TYPE]
    if brick:
        building.elements.append(
            BuildingModel.model_validate(
                {
                    "elements": [
                        {
                            "id": "B1",
                            "type": "BR250",
                            "kind": "wall",
                            "start": [1500, 3000],
                            "end": [1500, 6000],
                            "bottom": 0,
                            "top": 3000,
                        }
                    ]
                }
            ).elements[0]
        )
        masonry = next(m.id for m in mats.values() if m.masonry is not None)
        objects = objects + [
            {
                "id": "BR250",
                "name": "Brick 250",
                "kind": "wall",
                "material": masonry,
                "thickness": 250,
                "structural": True,
            }
        ]
    types = {o.id: o for o in ObjectLibrary.model_validate({"objects": objects}).objects}
    from pathlib import Path

    from saengine.library.settings import ProjectSettings

    sample = Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples"
    path = sample / "Sample Frame" / "02 Project Settings" / "project-settings.json"
    settings = ProjectSettings.model_validate_json(path.read_text(encoding="utf-8"))
    out = wall_design.design_walls(
        {"nodes": [], "elements": []},
        "unused",
        building,
        types,
        mats,
        settings,
        settings,
        settings,
        None,
        {},
        [EQ],
        None,
    )
    by_id = {e["id"]: e for e in out["elements"]}
    for wid in ("W1", "W2"):
        (entry,) = by_id[wid]["flanged"]
        assert entry["id"] == "W1+W2/L1" and entry["walls"] == ["W1", "W2"]
        assert entry["junctions"][0]["kind"] == "T"
        (pier,) = by_id[wid]["piers"]
        pm = next(c for c in pier["checks"] if c["name"].startswith("Axial force and bending"))
        assert pm["flag"] and "superseded by the flanged section W1+W2/L1" in pm["note"]
        assert any(c["note"].startswith("W1+W2/L1 (flanged)") for c in by_id[wid]["checks"])
    own = [c for c in by_id["W1"]["checks"] if not c["flag"]]
    assert by_id["W1"]["utilisation"] == max(c["utilisation"] for c in own)
    assert any("flanged sections" in n for n in out["notes"])
    flange_notes = [n for n in out["notes"] if "not taken as a flange" in n]
    if brick:
        expected = (
            "walls: B1 meets W1, W2 but is not a designed RC wall: not taken as a flange "
            "(left out of the flanged section)"
        )
        assert flange_notes == [expected]
    else:
        assert not flange_notes
    # Off: the rectangular piers only.
    off = wall_design.design_walls(
        {"nodes": [], "elements": []},
        "unused",
        building,
        types,
        mats,
        settings,
        settings,
        settings,
        None,
        {},
        [EQ],
        None,
        flanged=False,
    )
    assert not any(e.get("flanged") for e in off["elements"])
    assert np.isfinite(by_id["W1"]["utilisation"])

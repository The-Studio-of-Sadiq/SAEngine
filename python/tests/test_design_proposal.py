"""Design mode: the proposed bars (by hand where the pick is fixed by the documented ranking),
the pure edit that applies them, and the shipped sample designed end to end."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from saengine.design.proposal import (
    BeamDesigner,
    BeamLoads,
    MemberPick,
    Pick,
    SlabDesigner,
    SlabLoads,
    _groups,
    _split,
    apply_proposal,
)
from saengine.design.rc import bars_per_row, flexure, section_of, shear
from saengine.design.required import Options
from saengine.library.bim import source_stamp
from saengine.library.objects import Beam, LinearReinforcement, Slab

FC, FY = 28.0, 420.0


def _beam(b: float, h: float) -> Beam:
    return Beam.model_validate(
        {
            "id": "B",
            "name": "B",
            "material": "C28",
            "profile": {"shape": "rectangle", "xDim": b, "yDim": h},
            "reinforcement": {
                "material": "B420",
                "cover": 40,
                "longitudinal": [
                    {"position": "top", "count": 2, "dia": 16},
                    {"position": "bottom", "count": 2, "dia": 16},
                ],
                "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
            },
        }
    )


def _confirm(beam: Beam, reinforcement: dict, loads: BeamLoads) -> None:
    """The checks' own functions accept the pick."""
    section = section_of(beam.profile, LinearReinforcement.model_validate(reinforcement), FC, FY)
    sag, hog = flexure(section, False), flexure(section, True)
    assert sag.phi_mn >= loads.sag and sag.eps_t >= 0.004
    assert loads.hog <= 0 or (hog.phi_mn >= loads.hog and hog.eps_t >= 0.004)
    t = reinforcement["transverse"]
    resistance = shear(section, t["dia"], t["legs"], t["spacing"])
    assert resistance.phi_vn >= loads.shear and resistance.with_min_stirrups


def test_simply_supported_beam_bars() -> None:
    # 300 x 500, Mu = 150 kN·m, Vu = 100 kN. Stirrups first: Vs = 100/0.75 - 118.7 = 14.6 kN,
    # so Av,min governs: 0.35 × 300 / 420 = 0.25 mm²/mm; Ø8 two legs at 402 mm, held to
    # d/2 = 221 -> 200 mm. With Ø8 stirrups d = 500 - 40 - 8 - 10 = 442 and As = 958.6 mm².
    # Bottom choices (score = As × 1.15^(rows - 1) + 25 per bar): 2Ø25 982 + 50 = 1032 beats
    # 5Ø16 (1005 + 125) and 4Ø20 (1257 + 100); top: no hogging, 2Ø12 hanger bars.
    beam = _beam(300, 500)
    loads = BeamLoads(150e6, 0.0, 100e3)
    pick = BeamDesigner(beam, FC, FY, 200_000, None, Options()).propose(loads)
    assert pick.reinforcement is not None, pick.too_small
    groups = {g["position"]: (g["count"], g["dia"]) for g in pick.reinforcement["longitudinal"]}
    assert groups == {"top": (2, 12.0), "bottom": (2, 25.0)}
    t = pick.reinforcement["transverse"]
    assert (t["dia"], t["legs"], t["spacing"]) == (8.0, 2, 200.0)
    assert pick.label == "top 2Ø12, bottom 2Ø25, stirrups Ø8 2 legs @ 200"
    _confirm(beam, pick.reinforcement, loads)
    # By hand: d = 500 - 40 - 8 - 12.5 = 439.5, a = 982 × 420 / (0.85 × 28 × 300) = 57.8,
    # φMn = 0.9 × 982 × 420 × (439.5 - 28.9) = 152.4 kN·m (the top bars add a little).
    as_ = 2 * math.pi * 25**2 / 4
    a = as_ * FY / (0.85 * FC * 300)
    assert pick.utilisation["sagging"] == pytest.approx(
        150e6 / (0.9 * as_ * FY * (439.5 - a / 2)), rel=0.01
    )


def test_beam_needing_two_rows() -> None:
    # 250 x 500, Mu = 250 kN·m: about 1750 mm²; three Ø20 or Ø25 fit a row of 250 mm.
    beam = _beam(250, 500)
    loads = BeamLoads(250e6, 60e6, 150e3)
    pick = BeamDesigner(beam, FC, FY, 200_000, None, Options()).propose(loads)
    assert pick.reinforcement is not None, pick.too_small
    bottom = next(g for g in pick.reinforcement["longitudinal"] if g["position"] == "bottom")
    inset = 40 + pick.reinforcement["transverse"]["dia"]
    assert bottom["count"] > bars_per_row(250, inset, bottom["dia"])  # two rows
    assert "2 rows" in " ".join(pick.notes)
    _confirm(beam, pick.reinforcement, loads)


def test_beam_too_small_suggests_a_deeper_section() -> None:
    # 250 x 400, Mu = 500 kN·m: 4689 mm² of tension steel > 0.04 b h (see
    # test_design_required); at 450 mm deep 4015 mm² < 0.04 × 250 × 450 = 4500 mm².
    beam = _beam(250, 400)
    pick = BeamDesigner(beam, FC, FY, 200_000, None, Options()).propose(
        BeamLoads(500e6, 0.0, 100e3)
    )
    assert pick.reinforcement is None
    assert "too small" in pick.too_small
    assert pick.suggestion.startswith("try 250 x 450 mm (depth +50 mm)")
    # Shear beyond 0.66 √f'c b d: too small for shear.
    shear_pick = BeamDesigner(beam, FC, FY, 200_000, None, Options()).propose(
        BeamLoads(50e6, 0.0, 600e3)
    )
    assert shear_pick.reinforcement is None and "shear" in shear_pick.too_small


def test_compression_bars_in_the_proposal() -> None:
    # 250 x 400, Mu = 250 kN·m needs compression bars (As' = 1174 mm², see
    # test_design_required): the top face gets at least that.
    beam = _beam(250, 400)
    loads = BeamLoads(250e6, 0.0, 120e3)
    pick = BeamDesigner(beam, FC, FY, 200_000, None, Options()).propose(loads)
    assert pick.reinforcement is not None, pick.too_small
    top = next(g for g in pick.reinforcement["longitudinal"] if g["position"] == "top")
    assert top["count"] * math.pi * top["dia"] ** 2 / 4 >= 1100
    _confirm(beam, pick.reinforcement, loads)


def test_slab_mesh_per_layer() -> None:
    slab = Slab.model_validate(
        {
            "id": "S",
            "name": "S",
            "material": "C28",
            "thickness": 150,
            "system": "twoWay",
            "reinforcement": {
                "material": "B420",
                "cover": 20,
                **{n: {"dia": 10, "spacing": 200} for n in ("bottomX", "bottomY", "topX", "topY")},
            },
        }
    )
    loads = SlabLoads({"bottomX": 20e6, "bottomY": 10e6, "topX": 0.0, "topY": 0.0}, {"topX": 60e3})
    pick = SlabDesigner(slab, FC, FY, 200_000, Options()).propose(loads)
    assert pick.reinforcement is not None, pick.too_small
    meshes = {
        n: (m["dia"], m["spacing"]) for n, m in pick.reinforcement.items() if isinstance(m, dict)
    }
    # bottom X: 436.7 mm²/m -> Ø10 @ 175 (test_design_required); bottom Y (d = 115): 234 mm²/m
    # < As,min 270 -> Ø10 @ 290.9 -> 275; top Y: no demand, the largest spacing min(2h, 450).
    assert meshes["bottomX"] == (10.0, 175.0)
    assert meshes["bottomY"] == (10.0, 275.0)
    assert meshes["topY"] == (10.0, 300.0)
    # top X carries the one-way shear 60 kN/m: ρ = (60e3 / (0.75 × 0.66 × √28 × 1000 × 125))³
    # = 0.00615, As = 769 mm²/m -> Ø10 @ 102 -> 100.
    assert meshes["topX"] == (10.0, 100.0)
    assert pick.utilisation["shear topX"] <= 1.0
    # A demand no bars can carry: too thin, with a thicker slab suggested.
    heavy = SlabDesigner(slab, FC, FY, 200_000, Options()).propose(
        SlabLoads({"bottomX": 100e6}, {})
    )
    assert heavy.reinforcement is None and heavy.suggestion.startswith("try ")


def test_split_groups_the_over_designed_members() -> None:
    def member(name: str, area: float, signature: int) -> MemberPick:
        return MemberPick(name, None, Pick({"s": signature}, f"#{signature}", area))

    type_pick = Pick({"s": 0}, "#0", 1000.0)
    members = [
        member("B1", 1000.0, 0),
        member("B2", 700.0, 1),
        member("B3", 700.0, 1),
        member("B4", 500.0, 2),
        member("B5", 950.0, 3),  # 5 % over-designed: stays
    ]
    groups = _groups(type_pick, members, 0.25, 1)
    # One group allowed: the most populous (B2, B3); B4 joins it (700 >= 500).
    assert [[m.id for m in g] for g in groups] == [["B2", "B3", "B4"]]
    groups = _groups(type_pick, members, 0.25, 3)
    assert [[m.id for m in g] for g in groups] == [["B2", "B3"], ["B4"]]


class _Ids:
    """Loads that are the set of members enveloped (to see what a pick was designed for)."""

    def __init__(self, *ids: str) -> None:
        self.ids = frozenset(ids)

    def envelope(self, other: _Ids) -> _Ids:
        return _Ids(*self.ids, *other.ids)


def test_a_split_group_without_bars_stays_in_the_type_envelope() -> None:
    def member(name: str, area: float, signature: int) -> MemberPick:
        return MemberPick(name, _Ids(name), Pick({"s": signature}, f"#{signature}", area))

    members = [
        member("B1", 1000.0, 0),
        member("B2", 700.0, 1),
        member("B3", 700.0, 1),
        member("B4", 500.0, 2),
        member("B5", 950.0, 3),
    ]

    def propose_for(loads: _Ids) -> Pick:
        # The group (B2, B3) together finds no bars, although each alone does.
        if loads.ids == {"B2", "B3"}:
            return Pick(None, "", 0.0, too_small="no bars")
        return Pick({"for": sorted(loads.ids)}, ",".join(sorted(loads.ids)), 1000.0)

    accepted, remaining = _split(
        Pick({"s": 0}, "#0", 1000.0), members, Options(max_new_types=3), propose_for
    )
    assert [[m.id for m in g] for g, _ in accepted] == [["B4"]]
    # B2 and B3 stay, and the type's bars are designed for them too.
    assert remaining.reinforcement == {"for": ["B1", "B2", "B3", "B5"]}
    # No group finds bars: nothing leaves, the type's own pick stands.
    nothing, same = _split(
        Pick({"s": 0}, "#0", 1000.0),
        members,
        Options(max_new_types=3),
        lambda loads: Pick(None, "", 0.0) if loads.ids <= {"B2", "B3", "B4"} else Pick({}, "", 1),
    )
    assert nothing == [] and same.label == "#0"


def test_square_column_layouts_are_the_same_on_every_face() -> None:
    from saengine.design.bars import column_layouts

    for size in (380, 400, 440):  # within 10 % of 400: square
        layouts = column_layouts("rectangle", 400, size, 50)
        assert layouts
        assert all(o.per_x == o.per_y and o.count % 4 == 0 for o in layouts), size
    # A rectangle shares its bars by the faces' lengths: 6 bars on 300 x 600 put the extra pair
    # on the long faces.
    six = [o for o in column_layouts("rectangle", 300, 600, 50) if o.count == 6]
    assert six and all((o.per_x, o.per_y) == (0, 1) for o in six)


OBJECTS = {
    "schema": "saengine.objects/1",
    "objects": [
        {
            "id": "B1",
            "name": "Beam",
            "kind": "beam",
            "material": "C28",
            "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            "reinforcement": {
                "material": "B420",
                "cover": 40,
                "longitudinal": [{"position": "bottom", "count": 3, "dia": 16}],
            },
        },
        {
            "id": "C1",
            "name": "Column",
            "kind": "column",
            "material": "C28",
            "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
        },
    ],
}
NEW_BARS = {
    "material": "B420",
    "cover": 40,
    "longitudinal": [
        {"position": "top", "count": 2, "dia": 12},
        {"position": "bottom", "count": 2, "dia": 25},
    ],
    "transverse": {"type": "stirrup", "dia": 8, "spacing": 200, "legs": 2},
}


def test_apply_proposal_is_a_pure_edit() -> None:
    objects_text = json.dumps(OBJECTS, indent="\t") + "\n"
    plan = {"schema": "saengine.floorPlan/1", "beams": [{"id": "P1", "type": "B1"}]}
    plan_text = json.dumps(plan)
    bim = {
        "schema": "saengine.bim/2",
        "source": {"floorPlan": source_stamp(plan_text)},
        "elements": [
            {"id": "BM1", "kind": "beam", "type": "B1", "source": "P1"},
            {"id": "BM2", "kind": "beam", "type": "B1"},
        ],
        "additions": {"members": []},
    }
    sub = {"foundations": [{"id": "F1", "type": "isolated", "reinforcement": None}]}
    column_bars = {
        "material": "B420",
        "cover": 40,
        "longitudinal": [{"position": "perimeter", "count": 8, "dia": 20}],
        "transverse": {"type": "tie", "dia": 10, "spacing": 300, "legs": 2},
    }
    footing_bars = {"material": "B420", "cover": 75, "bottomX": {"dia": 16, "spacing": 150}}
    proposal = {
        "types": [
            {
                "type": "B1",
                "current": {"text": "bottom 3Ø16"},
                "proposed": {**NEW_BARS, "text": "new"},
            },
            {
                "type": "C1",
                "proposed": {**column_bars, "text": "8Ø20"},
                "apply": False,
            },
        ],
        "newTypes": [
            {
                "type": "B1-2",
                "from": "B1",
                "name": "Beam (2)",
                "proposed": {**NEW_BARS, "text": "light"},
                "members": ["BM1"],
            }
        ],
        "reassign": [{"member": "BM1", "from": "B1", "to": "B1-2", "source": "P1"}],
        "foundations": [{"id": "F1", "proposed": {**footing_bars, "text": "f"}}],
    }
    bim_text, sub_text = json.dumps(bim), json.dumps(sub, indent=2)
    result = apply_proposal(objects_text, bim_text, proposal, plan_text, sub_text)
    assert objects_text == json.dumps(OBJECTS, indent="\t") + "\n"  # the inputs are untouched
    objects = json.loads(result["objectsText"])
    assert [o["id"] for o in objects["objects"]] == ["B1", "B1-2", "C1"]
    assert objects["objects"][0]["reinforcement"] == NEW_BARS
    assert objects["objects"][1]["name"] == "Beam (2)"
    assert "reinforcement" not in objects["objects"][2]  # apply: false
    assert result["objectsText"].startswith('{\n\t"schema"') and result["objectsText"].endswith(
        "\n"
    )
    assert [e["type"] for e in json.loads(result["bimText"])["elements"]] == ["B1-2", "B1"]
    assert json.loads(result["floorPlanText"])["beams"][0]["type"] == "B1-2"
    # The BIM model stays current with the floor plan it was built from.
    stamp = json.loads(result["bimText"])["source"]["floorPlan"]
    assert stamp == source_stamp(result["floorPlanText"])
    # Foundations are designed in 9 Substructure: an older caller's foundations and
    # substructure text are ignored (X12, no duplication).
    assert "substructureText" not in result
    assert sub_text == json.dumps(sub, indent=2)
    files = [c["file"] for c in result["changes"]]
    assert files == [
        "04 Objects/objects.json",
        "04 Objects/objects.json",
        "06 BIM/bim.json",
        "05 Floor Plan/floor-plan.json",
    ]
    # A type that is not there is an error, not a silent no-op.
    assert result["changes"][0]["message"] == "B1: bottom 3Ø16 → new"
    bad = {"types": [{"type": "X9", "proposed": {**NEW_BARS, "text": ""}}]}
    with pytest.raises(ValueError, match="X9"):
        apply_proposal(objects_text, bim_text, bad)


def test_unticked_split_keeps_the_type_on_bars_for_all_its_members() -> None:
    objects_text = json.dumps(OBJECTS, indent=2)
    bim_text = json.dumps(
        {
            "schema": "saengine.bim/2",
            "elements": [
                {"id": "BM1", "kind": "beam", "type": "B1"},
                {"id": "BM2", "kind": "beam", "type": "B1"},
            ],
        }
    )
    light = {**NEW_BARS, "longitudinal": [{"position": "bottom", "count": 2, "dia": 16}]}
    heavy = {**NEW_BARS, "longitudinal": [{"position": "bottom", "count": 3, "dia": 25}]}

    def proposal(new_apply: bool = True, move_apply: bool = True, by_type: bool = True) -> dict:
        # BM2 is heavier: the split gives the remaining B1 BM2's own bars (2Ø25), BM1 its own
        # type B1-2 (2Ø16); by type, B1 takes 3Ø25 for both.
        entry = {"type": "B1", "current": {"text": "bottom 3Ø16"}, "proposed": NEW_BARS}
        if by_type:
            entry["byType"] = {**heavy, "text": "by type"}
        return {
            "types": [{**entry, "proposed": {**NEW_BARS, "text": "split"}}],
            "newTypes": [
                {"type": "B1-2", "from": "B1", "proposed": {**light, "text": "light"}}
                | ({} if new_apply else {"apply": False})
            ],
            "reassign": [
                {"member": "BM1", "from": "B1", "to": "B1-2"}
                | ({} if move_apply else {"apply": False})
            ],
        }

    def bars(result: dict) -> dict:
        return {
            o["id"]: o.get("reinforcement") for o in json.loads(result["objectsText"])["objects"]
        }

    whole = apply_proposal(objects_text, bim_text, proposal())
    assert bars(whole)["B1"] == NEW_BARS and bars(whole)["B1-2"] == light
    for unticked in (proposal(new_apply=False), proposal(move_apply=False)):
        result = apply_proposal(objects_text, bim_text, unticked)
        # BM1 stays in B1, so B1 takes the bars designed for all its members, and no empty new
        # type is added.
        assert bars(result)["B1"] == heavy and "B1-2" not in bars(result)
        assert [e["type"] for e in json.loads(result["bimText"])["elements"]] == ["B1", "B1"]
        assert result["changes"][0]["message"] == (
            "B1: bottom 3Ø16 → by type (the bars for all its members: BM1 stay in the type)"
        )
    # Without the by-type bars to fall back on, the edit is refused.
    with pytest.raises(ValueError, match="BM1"):
        apply_proposal(objects_text, bim_text, proposal(new_apply=False, by_type=False))


# ─────────────────────────────── seismic column ties ───────────────────────────────


def _column_ties(count: int, dia: float):
    from saengine.design.proposal import seismic_transverse
    from saengine.library.objects import Column

    column = Column.model_validate(
        {
            "id": "C550",
            "name": "Column",
            "material": "C28",
            "profile": {"shape": "rectangle", "xDim": 550, "yDim": 550},
        }
    )
    context = {"level": "special", "lateral": True, "cover": 40.0, "axial": (3000e3,)}
    reinforcement = {
        "material": "B420",
        "cover": 40.0,
        "longitudinal": [{"position": "perimeter", "count": count, "dia": dia}],
        "transverse": {"type": "tie", "dia": 10.0, "spacing": 150.0, "legs": 2},
    }
    return seismic_transverse(
        "column",
        column,
        reinforcement,
        [{"seismicContext": {**context, "clearHeight": 2500.0}}],
        FC,
        FY,
        200_000.0,
        None,
        Options.of({}),
    )


def test_seismic_ties_never_have_more_legs_than_bars_on_a_face() -> None:
    # N-X3 of usability walk 2: 4Ø32 in a 550 mm column got 4-leg ties. Its corner bars are
    # 550 - 2 × 40 - 2 × 10 - 32 = 418 mm apart, above hx = 350 mm (Sec 8.3.5.4(c)), and a cross
    # tie needs a bar to hold (8.3.5.4(a)(iii)): no ties can be made, so the layout is refused
    # ("detailable": False) and the proposal moves to one with more bars on its faces.
    _, info = _column_ties(4, 32.0)
    assert info is not None and info["detailable"] is False
    # 8Ø25: 3 bars a face, 3 legs; 12Ø20: 4 bars a face, at most 4 legs.
    found, info = _column_ties(8, 25.0)
    assert info.get("detailable", True) and found["transverse"]["legs"] == 3
    assert found["transverse"].get("legsX", 3) <= 3
    found, _ = _column_ties(12, 20.0)
    assert found["transverse"]["legs"] <= 4 and found["transverse"].get("legsX", 4) <= 4


def test_column_pick_prefers_fewer_larger_bars() -> None:
    # N-X3: the lightest layout of a 1050 mm column was 56Ø16 (11 259 mm²); 24Ø25 (11 781 mm²,
    # 4.6 % more) is within FEWER_BARS_MARGIN and is taken instead.
    from saengine.design.proposal import FEWER_BARS_MARGIN, _column_pick
    from saengine.design.required import ColumnSearch
    from saengine.library.objects import Column

    column = Column.model_validate(
        {
            "id": "C1050",
            "name": "Column",
            "material": "C28",
            "profile": {"shape": "rectangle", "xDim": 1050, "yDim": 1050},
        }
    )
    search = ColumnSearch(column, FC, FY, 200_000.0, None, Options.of({}))
    points = [(2000e3, 50e6, 50e6, "U1", "bottom")]
    index = search.smallest(points)
    lightest = search.layouts[index]
    pick = _column_pick(search, index, points)
    chosen = search.layouts[pick.index]
    assert chosen.area <= lightest.area * (1 + FEWER_BARS_MARGIN) + 1e-6
    assert chosen.count <= lightest.count
    assert (lightest.count, lightest.dia) == (56, 16.0)
    assert (chosen.count, chosen.dia) == (24, 25.0)


# ─────────────────────────────── joint shear ───────────────────────────────


def _joint_frame(
    tmp_path: Path,
    monkeypatch,
    sag: float,
    hog: float,
    options: dict | None = None,
    b2: tuple[float, float] | None = None,
):
    """An interior joint of a special moment frame, f'c 25, fy 420: the 400 x 400 column C1
    (storey 0-3 m) with C2 above it, 300 x 500 beams B1 and B2 of one type framing into two
    opposite faces (x) at 3 m. The checks' own joint shear: γ = 1.2 (two opposite faces
    confined, 300 ≥ 0.75 × 400), Aj = 400 × min(400, 300 + 400) = 160 000 mm², φ Vn = 0.85 ×
    1.2 × √25 × 160 000 = 816 kN. The beam demands (sagging, hogging [kN·m], shear 150 kN) are
    given directly; the joint is found in the building model as the checks found it (their row
    named "Detailing: Joint shear, ..."), and the proposal is made for them. ``b2``: other
    demands (sagging, hogging) of B2."""
    from types import SimpleNamespace

    from saengine.design import proposal as P
    from saengine.library.bim import BuildingModel
    from saengine.library.objects import Column, RectangleProfile

    fc = 25.0
    beam = Beam.model_validate(
        {
            "id": "B300x500",
            "name": "Beam",
            "material": "C25",
            "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            "reinforcement": {
                "material": "B420",
                "cover": 40,
                "longitudinal": [],
                "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
            },
        }
    )
    column = Column.model_validate(
        {
            "id": "C400",
            "name": "Column",
            "material": "C25",
            "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
        }
    )
    building = BuildingModel.model_validate(
        {
            "elements": [
                {"kind": "column", "id": "C1", "type": "C400", "position": [0, 0], "bottom": 0,
                 "top": 3000},
                {"kind": "column", "id": "C2", "type": "C400", "position": [0, 0],
                 "bottom": 3000, "top": 6000},
                {"kind": "beam", "id": "B1", "type": "B300x500", "start": [-6000, 0],
                 "end": [0, 0], "elevation": 3000},
                {"kind": "beam", "id": "B2", "type": "B300x500", "start": [0, 0],
                 "end": [6000, 0], "elevation": 3000},
            ]
        }
    )  # fmt: skip
    column_section = section_of(
        RectangleProfile(xDim=400, yDim=400),
        LinearReinforcement.model_validate(
            {
                "material": "B420",
                "cover": 40,
                "longitudinal": [{"position": "perimeter", "count": 8, "dia": 20}],
                "transverse": {"type": "tie", "dia": 10, "spacing": 100},
            }
        ),
        fc,
        FY,
    )
    common = {"fc": fc, "fy": FY, "es": 200_000.0, "aggregate": None}
    loads = BeamLoads(sag * 1e6, hog * 1e6, 150e3)
    light = BeamLoads(b2[0] * 1e6, b2[1] * 1e6, 150e3) if b2 else loads
    beams = [
        {"id": b, "kind": "beam", "type": "B300x500", "object": beam, "loads": own, **common}
        for b, own in (("B1", loads), ("B2", light))
    ]
    columns = [
        {
            "id": c,
            "kind": "column",
            "type": "C400",
            "object": column,
            "section": column_section,
            "points": [(1500e3, 60e6, 20e6, "U1", "bottom")],
            **common,
        }
        for c in ("C1", "C2")
    ]
    joints = [{"id": "C1@3000", "checks": [{"name": "Detailing: Joint shear, C1@3000 x"}]}]
    gathered = SimpleNamespace(
        root=tmp_path,
        collect={"combinations": ["U1"], "members": beams + columns, "joints": joints},
        objects_text=json.dumps({"objects": []}),
        objects=SimpleNamespace(objects=[beam, column]),
        assumed=set(),
        building=building,
        notes=[],
    )
    monkeypatch.setattr(P, "_beam_loads", lambda member, combinations: member["loads"])
    return P.design_proposal(tmp_path, tmp_path / "model.osmodel", options, gathered=gathered)


def test_lighter_beam_bars_make_the_joint_pass(tmp_path: Path, monkeypatch) -> None:
    # Mu- 160, Mu+ 80 kN·m. The best ranked bars, top 4Ø20 (1256.6 mm²), bottom 3Ø16 (603.2):
    # T = 1.25 × 420 × (1256.6 + 603.2) = 976.4 kN, Vcol = ΣMpr / 3000 mm = 131.7 kN, Vj = 844.7
    # kN > 816 kN. The lightest that pass, top 10Ø12 (1131.0, two rows), bottom 5Ø12 (565.5):
    # T = 525 × 1696.5 = 890.7 kN, Vcol 120.6 kN, Vj = 770.1 kN ≤ 816 kN.
    proposal = _joint_frame(tmp_path, monkeypatch, sag=80, hog=160)
    by_type = {t["type"]: t for t in proposal["types"]}
    beam, column = by_type["B300x500"], by_type["C400"]
    groups = {g["position"]: (g["count"], g["dia"]) for g in beam["proposed"]["longitudinal"]}
    assert groups == {"top": (10, 12.0), "bottom": (5, 12.0)}
    assert any("joint shear at C1@3000" in n for n in beam["notes"])
    assert column["status"] == "ok" and column["tooSmall"] is None


def test_joint_shear_reports_the_column_too_small(tmp_path: Path, monkeypatch) -> None:
    # Mu- 280, Mu+ 196 kN·m: top 4Ø25 (1963.5 mm²), bottom 3Ø25 (1472.6): T = 525 × 3436.1 =
    # 1803.9 kN, Vcol = 233.8 kN, Vj = 1570.1 kN, far above 816 kN; the lightest bars that pass
    # (top 4Ø25, bottom 12Ø12: Vj 1521.5 kN) do not help, so the beam keeps its bars and the
    # column is too small. Larger columns, both sides +50 mm: from 450 the 300 mm beams cover
    # less than 0.75 of a face, γ = 1.0, Aj = h², φ Vn = 0.85 × 1.0 × 5 × h²: 600 gives 1530 kN
    # (fails), 650 gives 1795.6 kN ≥ 1570.1 kN.
    proposal = _joint_frame(tmp_path, monkeypatch, sag=196, hog=280)
    by_type = {t["type"]: t for t in proposal["types"]}
    beam, column = by_type["B300x500"], by_type["C400"]
    groups = {g["position"]: (g["count"], g["dia"]) for g in beam["proposed"]["longitudinal"]}
    assert groups == {"top": (4, 25.0), "bottom": (3, 25.0)}
    assert column["status"] == "tooSmall" and column["proposed"] is None
    assert column["tooSmall"]["reason"] == "joint shear at C1@3000"
    assert column["tooSmall"]["suggestion"].startswith("try 650 x 650 mm (+250 mm)")
    assert any(n.startswith("bars for its axial forces and moments:") for n in column["notes"])
    assert "C400: section too small — joint shear at C1@3000" in proposal["warnings"]


def test_joint_shear_verdict_is_the_same_in_both_modes(tmp_path: Path, monkeypatch) -> None:
    # N-X5 of usability walk 2: the split moves the lightly loaded B2 to a lighter new type, and
    # the joint was judged on those lighter bars: the C400 failed joint shear when keeping
    # shared types and passed when splitting. Both modes now judge the joints on the beam
    # type's shared bars (top 4Ø25, bottom 3Ø25 here), so both report the column too small.
    verdicts = {}
    for mode in ("byType", "splitTypes"):
        proposal = _joint_frame(
            tmp_path / mode, monkeypatch, sag=196, hog=280, options={"mode": mode}, b2=(40, 80)
        )
        column = next(t for t in proposal["types"] if t["type"] == "C400")
        verdicts[mode] = (column["status"], column["tooSmall"]["reason"])
        if mode == "splitTypes":
            assert [n["members"] for n in proposal["newTypes"]] == [["B2"]]
        # The bars its strength needs stay on offer ("apply strength bars anyway").
        assert column["strengthBars"]["text"].startswith("8Ø16")
    assert verdicts["byType"] == verdicts["splitTypes"] == ("tooSmall", "joint shear at C1@3000")


def test_strength_bars_applied_anyway_on_request(tmp_path: Path, monkeypatch) -> None:
    proposal = _joint_frame(tmp_path, monkeypatch, sag=196, hog=280)
    column = next(t for t in proposal["types"] if t["type"] == "C400")
    # The fixture's column type has no bars, so no rebar grade to carry over (a real type
    # without bars is checked with assumed ones, which have it).
    column = {**column, "strengthBars": {**column["strengthBars"], "material": "B420"}}
    objects = {
        "objects": [
            {
                "id": "C400",
                "kind": "column",
                "name": "Column",
                "material": "C25",
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
            }
        ]
    }
    request = {**proposal, "types": [{**column, "apply": True}]}
    untouched = apply_proposal(json.dumps(objects), "{}", request)
    assert "reinforcement" not in json.loads(untouched["objectsText"])["objects"][0]
    request = {**proposal, "types": [{**column, "apply": True, "applyStrengthBars": True}]}
    applied = apply_proposal(json.dumps(objects), "{}", request)
    bars = json.loads(applied["objectsText"])["objects"][0]["reinforcement"]
    assert bars["longitudinal"] == [{"position": "perimeter", "count": 8, "dia": 16.0}]


# ─────────────────────────────── the shipped sample ───────────────────────────────


@pytest.mark.slow
def test_sample_byType_proposal_makes_the_design_pass(tmp_path: Path) -> None:
    from test_integration_e56 import _derive, _project, _run

    from saengine.design import design_report
    from saengine.design.proposal import design_proposal
    from saengine.design.required import design_required, gather

    root = _project(tmp_path)
    model, out = _run(root, _derive(root))
    before = design_report(out, model)
    assert before["summary"]["failed"] > 0  # the sample's bars are short (beams, slabs)
    # The steel brace M2's gusset is a simple connection: both its ends are pinned in the
    # analysis (zero-length links, torsion kept at its foot), and it passes, governed by the
    # gusset's bolt gauge; its kg/m is the section table's, as in the BOQ (33.9).
    links = [
        (e["name"], e["dofs"])
        for e in json.loads(Path(model).read_text(encoding="utf-8"))["elements"]
        if e["type"] == "ZeroLength"
    ]
    assert links == [("M2/pin", [1, 2, 3, 4]), ("M2/pin#2", [1, 2, 3])]
    brace = next(e for e in before["elements"] if e["id"] == "M2")
    assert brace["ok"] and brace["utilisation"] == pytest.approx(0.889, abs=0.005)
    assert f"{brace['section']['massPerMetre']:.1f}" == "33.9"
    assert not any("end moment" in c["name"] for c in brace["checks"])

    gathered = gather(out, model)
    required = design_required(out, model, gathered=gathered)
    rows = required["elements"]
    assert {r["kind"] for r in rows} >= {"beam", "column", "slab", "isolated"}
    short = {r["element"] for r in rows if r["ok"] is False}
    failed = {e["id"] for e in before["elements"] if not e["ok"]}
    assert failed <= short  # every failing element shows a shortfall
    # No section is too small for bars; the footing F1 fails a plan-size check (bearing or the
    # resultant within its base: a larger footing, not bars, is the remedy).
    small = [r for r in rows if r["tooSmall"]]
    assert {r["element"] for r in small} <= {"F1"}
    assert all(r["quantity"] == "other check" and "larger" in r["notes"] for r in small)

    proposal = design_proposal(out, model, {"mode": "byType"}, gathered=gathered)
    by_type = {t["type"]: t for t in proposal["types"]}
    # The steel brace BR-SHS (A572-50) gets a lighter SHS of its family; it is left out here so
    # the bars are checked on the analysed sections (a new section would need a new analysis).
    assert set(by_type) == {"B300x500", "C400x600", "S150", "W200", "ST1200", "BR-SHS"}
    assert all(t["status"] in ("ok", "unchanged") for t in by_type.values())  # none too small
    assert by_type["B300x500"]["governingMember"] in {"B2", "B4", "B5"}
    assert by_type["BR-SHS"]["family"] == "SHS" and by_type["BR-SHS"]["governingMember"] == "M2"
    by_type["BR-SHS"]["apply"] = False

    def read(relative: str) -> str:
        return (root / relative).read_text(encoding="utf-8")

    result = apply_proposal(
        read("04 Objects/objects.json"),
        read("06 BIM/bim.json"),
        proposal,
        read("05 Floor Plan/floor-plan.json"),
        read("09 Substructure/substructure.json"),
    )
    (root / "04 Objects/objects.json").write_text(result["objectsText"], encoding="utf-8")
    (root / "06 BIM/bim.json").write_text(result["bimText"], encoding="utf-8")
    after = design_report(out, model)
    failures = [
        (e["id"], c["name"])
        for e in after["elements"]
        for c in e["checks"]
        if not c["ok"] and not c["flag"]
    ]
    # Everything passes with the bars proposed: the wall W1 and the dog-legged stair ST1 (riser
    # 160, tread 327: 2R + T = 647 mm, BNBC Part 3 Sec 1.14.5.2, and Part 4 Table 4.3.5's 327 mm).
    assert failures == []
    # The totals count the 18 members (5 beams, 8 columns with the steel M1, the brace M2, 2
    # slabs, the stair and the wall), the 6 beam-column joints and the building's 3 seismic
    # checks (f'c, bar grade, fyt of the ties): 27 (X4 of the usability walk).
    summary = after["summary"]
    assert summary["failed"] == 0 and summary["checked"] == 27
    assert summary["elements"]["checked"] == 18
    assert summary["joints"]["checked"] == 6 and summary["seismicChecks"] == 3

    # Splitting: the lighter beams get their own types, and the design still passes.
    split = design_proposal(out, model, {"mode": "splitTypes"}, gathered=gathered)
    assert split["newTypes"], "the sample's beams differ enough to split"
    for entry in split["types"]:
        if entry.get("family"):  # steel types: kept, as above
            entry["apply"] = False
    assert {m["to"] for m in split["reassign"]} == {t["type"] for t in split["newTypes"]}
    result = apply_proposal(
        read("04 Objects/objects.json"), read("06 BIM/bim.json"), split,
        read("05 Floor Plan/floor-plan.json"),
    )  # fmt: skip
    (root / "04 Objects/objects.json").write_text(result["objectsText"], encoding="utf-8")
    (root / "06 BIM/bim.json").write_text(result["bimText"], encoding="utf-8")
    (root / "05 Floor Plan/floor-plan.json").write_text(result["floorPlanText"], encoding="utf-8")
    again = design_report(out, model)
    assert {e["id"] for e in again["elements"] if not e["ok"]} == set()
    moved = {m["member"]: m["to"] for m in split["reassign"]}
    assert {e["id"]: e["type"] for e in again["elements"] if e["id"] in moved} == moved

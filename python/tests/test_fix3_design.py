"""Walkthrough 3 fixes of the RC design checks and the Design Reinforcement proposal."""

from __future__ import annotations

import math

import pytest

from saengine.design import wall_forces as WF
from saengine.library.settings import LoadCombination

# ── B10-23: base reactions about the base centroid ──


def test_base_reaction_moments_are_about_the_supports_centroid() -> None:
    """B10-23: Mx, My, Mz of the base reactions were the sums of the support moments only (a
    fixed-base frame under EX showed My = -5070 kN·m against an overturning of about 45 MN·m).
    Now about the supports' centroid at the base: two supports 6 m apart in x, each pushing
    back 100 kN in -x with 50 kN up and down (a couple), give the overturning about y."""
    from types import SimpleNamespace

    import numpy as np

    from saengine.fem.story_response import _base_reactions, base_centre

    project = {
        "nodes": [{"id": 1, "coords": [0.0, 0.0, 0.0]}, {"id": 2, "coords": [6.0, 0.0, 0.0]}]
    }
    results = SimpleNamespace(
        node_reaction={
            1: [[-100e3, 0.0, 50e3, 0.0, 10e3, 0.0]],
            2: [[-100e3, 0.0, -50e3, 0.0, 10e3, 0.0]],
        }
    )
    centre = base_centre(project, {1, 2})
    assert list(centre) == [3.0, 0.0, 0.0]
    coords = {n["id"]: np.asarray(n["coords"]) for n in project["nodes"]}
    fx, _fy, fz, _mx, my, _mz = _base_reactions([(1.0, results)], {1, 2}, coords, centre)
    assert (fx, fz) == (-200e3, 0.0)
    # (r x F)y = z Fx - (x - 3) Fz: 3 x 50 + 3 x 50 = 300 kN·m, plus the supports' 2 x 10.
    assert my == pytest.approx(300e3 + 20e3)
    # Without the points: the support moments alone, as before.
    assert _base_reactions([(1.0, results)], {1, 2})[4] == pytest.approx(20e3)


# ── FD-9 / B10-24: reversed combinations named with SD ──


def test_reversed_combination_names_show_sd() -> None:
    """FD-9: "1.2D + 1.0(-EX) + 1.0L" (as fem.combinations.expand_rows names it) is a name of
    factors too: shown with SD, which its D factor applies to, as the +EX combination is."""
    from saengine.fem.combinations import combination_label

    present = {"D", "SD", "L", "EX", "WX"}
    label = combination_label(
        LoadCombination(name="1.2D + 1.0(-EX) + 1.0L", D=1.2, EX=-1.0, L=1.0), present
    )
    assert label == "1.2D + 1.2SD + 1.0L + 1.0(-EX)"
    label = combination_label(LoadCombination(name="0.9D + 1.6(-WX)", D=0.9, WX=-1.6), present)
    assert label == "0.9D + 0.9SD + 1.6(-WX)"


# ── FD-3: walls in a model without the optional cases H and F ──


def test_wall_combinations_leave_out_optional_cases_the_model_lacks() -> None:
    """FD-3: a combination naming H (earth pressure) in a model without basement walls gave no
    wall forces at all ("no forces at its cuts; not checked"); with the model's cases the
    optional case is left out, as for the frames (fem.combinations.OPTIONAL_CASES)."""
    import tests.test_design_wall_design as T

    settings = T._settings().model_copy(
        update={"combinations": [LoadCombination(name="1.2D + 1.6L + 1.6H", D=1.2, L=1.6, H=1.6)]}
    )
    combos, _, _ = WF.design_combination_list(settings, "unused", {"D", "SD", "L"})
    assert combos[0].factors == {"D": 1.2, "SD": 1.2, "L": 1.6}
    # Without the cases the optional one stays (what the walls were given before).
    combos, _, _ = WF.design_combination_list(settings, "unused")
    assert "H" in combos[0].factors


def test_design_walls_asks_for_the_combinations_with_the_model_cases(monkeypatch) -> None:
    """FD-3: design_walls passes the analysis model's cases to the combination list."""
    import tests.test_design_wall_design as T
    from saengine.design import wall_design
    from saengine.library import ObjectLibrary, default_material_library

    seen: dict = {}

    def probe(settings, out_dir, present=None):
        seen["present"] = present
        return list(T.COMBOS), None, "corners"

    monkeypatch.setattr(WF, "design_combination_list", probe)
    monkeypatch.setattr(WF, "wall_forces", lambda *a, **k: T.FOUND)
    project = {**T.PROJECT, "analyses": [{"name": "D: dead"}, {"name": "L: live"}]}
    types = {o.id: o for o in ObjectLibrary.model_validate({"objects": [T.WALL_TYPE]}).objects}
    mats = {m.id: m for m in default_material_library().materials}
    settings = T._settings()
    found = wall_design.design_walls(
        project,
        "unused",
        T._building(),
        types,
        mats,
        settings,
        settings,
        settings,
        None,
        T.EXTRA,
        [T.EQ, T.GRAVITY],
    )
    assert seen["present"] == {"D", "L"}
    assert found["elements"], "the wall is designed"


# ── FD-6 doubt: a transfer beam's spans ──


def _transfer_building():
    from saengine.library.bim import BuildingModel

    def column(cid, x, bottom, top):
        return {
            "id": cid,
            "type": "C400",
            "kind": "column",
            "position": [x, 0.0],
            "bottom": bottom,
            "top": top,
        }

    return BuildingModel.model_validate(
        {
            "stories": [
                {"id": "L1", "name": "L1", "elevation": 3600.0},
                {"id": "L2", "name": "L2", "elevation": 6800.0},
            ],
            "elements": [
                column("C1", 0.0, 0.0, 3600.0),
                column("C2", 12000.0, 0.0, 3600.0),
                column("C3", 6000.0, 3600.0, 6800.0),  # stands on the transfer beam
                column("C1a", 0.0, 3600.0, 6800.0),
                {
                    "id": "B1",
                    "type": "B500",
                    "kind": "beam",
                    "start": [0.0, 0.0],
                    "end": [12000.0, 0.0],
                    "elevation": 3600.0,
                },
                {
                    "id": "T1",
                    "type": "B500",
                    "kind": "beam",
                    "start": [0.0, 0.0],
                    "end": [12000.0, 0.0],
                    "elevation": 0.0,
                },
            ],
        }
    )


def test_a_column_standing_on_a_beam_is_not_its_support() -> None:
    """FD (doubt): the 12 m transfer beam B23 was split into two 6 m spans at the column C16
    that stands on it (its deflection checked against 6000/480). A column starting at the
    beam's level is a load on it; the spans run between the columns below (12 m). At the base
    a tie beam is still held by the columns standing on their footings."""
    from saengine.design.check import _BeamFraming, _longest_span
    from saengine.library.objects import ObjectLibrary

    building = _transfer_building()
    types = {o.id: o for o in ObjectLibrary.model_validate({"objects": []}).objects}
    framing = _BeamFraming(building, types)
    beam = next(e for e in building.elements if e.id == "B1")
    assert framing.support_stations(beam) == [0.0, 1.0]
    assert _longest_span(beam, framing) == 12000.0
    tie = next(e for e in building.elements if e.id == "T1")
    assert framing.support_stations(tie) == [0.0, 1.0]


# ── FD-10: no punching where beams frame in ──


def test_slab_on_beams_has_no_punching_at_the_columns() -> None:
    """FD-10: S125 "punching fails at C10, C14, C15" on a slab designed by frames although
    beams ran along every grid line. Where beams run along the spans either side of a column
    in both directions they carry the slab's shear to it; no punching row. The same slab
    without beams (a flat plate) still has its 16."""
    from saengine.design import slab, slab_frames
    from saengine.library.objects import BarMesh, PlanarReinforcement
    from tests.test_design_b33_methods import OUTLINE, _grid

    mesh = BarMesh(dia=12, spacing=150)
    reinforcement = PlanarReinforcement(
        material="r", cover=20, bottomX=mesh, bottomY=mesh, topX=mesh, topY=mesh
    )
    beams = []
    for k in range(4):
        at = k * 6000.0
        beams += [
            slab_frames.FrameBeam(
                f"BX{k}{i}", (i * 6000.0, at), ((i + 1) * 6000.0, at), 300, 500, 25000
            )
            for i in range(3)
        ]
        beams += [
            slab_frames.FrameBeam(
                f"BY{k}{i}", (at, i * 6000.0), (at, (i + 1) * 6000.0), 300, 500, 25000
            )
            for i in range(3)
        ]

    def design(with_beams):
        context = slab.SlabContext(boundary=OUTLINE, axes=slab.plan_axes(), supports=[])
        found = slab_frames.design_slab(
            "twoWay",
            150,
            reinforcement,
            25,
            420,
            200000,
            6.0,
            3.0,
            [slab.GravityCombination("U", 1.2, 1.6)],
            context,
            _grid(),
            beams if with_beams else [],
            25000,
        )
        return found, context

    found, context = design(True)
    assert not [c for c in found.checks if c["name"].startswith("Punching at")]
    assert any("beams frame into it in both directions" in n for n in context.notes)
    found, _ = design(False)
    assert sum(c["name"].startswith("Punching at") for c in found.checks) == 16


# ── OI-1: the proposal respects the bars' anchorage ──


def test_proposal_keeps_bars_that_hook_into_the_column() -> None:
    """OI-1: the proposal gave a 300 x 500 beam 2Ø25 bottom bars that cannot hook into its
    400 mm end column. With f'c = 28 MPa, fy = 420 MPa a special frame's hooked bar needs
    ldh = max(8 db, 150, fy db / (5.4 √f'c)) (Sec 8.3.7.4(a), Eq. 6.8.12): Ø25 367 mm, Ø20
    294 mm, against 400 - 40 - 12 = 348 mm. Bars passing through a joint need a column depth
    of 20 db (Sec 8.3.7.1(d)): 400 mm takes Ø20 at most."""
    from saengine.design.proposal import BarRoom, BeamDesigner, BeamLoads
    from saengine.design.required import Options
    from tests.test_design_proposal import FC, FY, _beam

    designer = BeamDesigner(_beam(300, 500), FC, FY, 200_000, None, Options())
    loads = BeamLoads(150e6, 0.0, 100e3)
    free = designer.propose(loads)
    assert any(g["dia"] == 25 for g in free.reinforcement["longitudinal"])  # as before
    assert designer.hooked_need(25, True) == pytest.approx(420 * 25 / (5.4 * math.sqrt(28)))
    designer.anchorage = BarRoom(348.0, True, "column C1 (at B1)")
    pick = designer.propose(loads)
    assert pick.reinforcement is not None
    assert max(g["dia"] for g in pick.reinforcement["longitudinal"]) <= 20
    assert any("hooks fit the 348 mm in column C1" in n for n in pick.notes)
    # Only passing through a 400 mm column: Ø20 at most too.
    designer = BeamDesigner(_beam(300, 500), FC, FY, 200_000, None, Options())
    designer.anchorage = BarRoom(math.inf, True, "", 400.0, "column C2 (at B1)")
    pick = designer.propose(loads)
    assert max(g["dia"] for g in pick.reinforcement["longitudinal"]) <= 20
    assert any("20 db" in n for n in pick.notes)


def test_anchorage_rooms_from_the_frame() -> None:
    """OI-1: where a beam ends in a column the room is the column's depth along it less its
    cover and tie; where beams meet from both sides the bars pass through."""
    from types import SimpleNamespace

    from saengine.design.proposal import _anchorage_rooms, _type_anchorage
    from saengine.library.bim import BuildingModel
    from saengine.library.objects import ObjectLibrary

    def column(cid, x):
        return {
            "id": cid,
            "type": "C400",
            "kind": "column",
            "position": [x, 0.0],
            "bottom": 0.0,
            "top": 3000.0,
        }

    building = BuildingModel.model_validate(
        {
            "stories": [{"id": "L1", "name": "L1", "elevation": 3000.0}],
            "elements": [
                column("C1", 0.0),
                column("C2", 6000.0),
                column("C3", 12000.0),
                {
                    "id": "B1",
                    "type": "B",
                    "kind": "beam",
                    "start": [0.0, 0.0],
                    "end": [6000.0, 0.0],
                    "elevation": 3000.0,
                },
                {
                    "id": "B2",
                    "type": "B",
                    "kind": "beam",
                    "start": [6000.0, 0.0],
                    "end": [12000.0, 0.0],
                    "elevation": 3000.0,
                },
            ],
        }
    )
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "C400",
                    "name": "C400",
                    "kind": "column",
                    "material": "C28",
                    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                    "reinforcement": {
                        "material": "B420",
                        "cover": 40,
                        "longitudinal": [{"position": "perimeter", "count": 8, "dia": 16}],
                        "transverse": {"type": "tie", "dia": 12, "spacing": 100},
                    },
                },
            ]
        }
    )
    rooms = _anchorage_rooms(SimpleNamespace(building=building, objects=objects))
    assert rooms["B1"] == (348.0, "C1") and rooms["B2"] == (348.0, "C3")
    assert rooms["through:B1"] == (400.0, "C2")
    members = [{"id": "B1", "seismicContext": {"level": "special", "lateral": True}}]
    room = _type_anchorage(members, rooms)
    assert (room.end, room.through, room.special) == (348.0, 400.0, True)


# ── B10-14: the grid wizard sizes columns for the joint shear too ──


def test_wizard_columns_are_sized_for_the_joint_shear() -> None:
    """B10-14: the wizard's 10-storey frame (4 x 6 m by 3 x 6 m, Dhaka, Category D, special
    moment frame) failed joint shear at once at the interior C600 columns (Vj about 1.5 MN
    against φ γ √f'c Aj = 0.85 x 1.0 x √f'c x 600² with 300 mm beams covering less than
    three quarters of a face, Sec 8.3.7.3). The sizing now checks the joint shear with the
    beams' estimated bars (T = 1.25 fy As, Vcol = 1.25 ΣMnb over the storey height) and the
    interior columns of L1-L3 grow to 650 mm, of L4-L6 to 600 mm. W4C-10 of usability walk 4:
    the bars the design then proposes ran about 30 % above the estimate (the walk's edge C350
    failed), so the sizing keeps the joint at most 80 % used (JOINT_SHEAR_RESERVE): 700 mm."""
    from saengine.library.generator import generate_building

    result = generate_building(
        {"gridsX": [6000] * 4, "gridsY": [6000] * 3, "storyCount": 10, "location": "dhaka"}
    )
    reasons = result["summary"]["columnReasons"]
    # The governing joint moved from L1 to L2 with the larger W (owner decision 2026-11-03:
    # partitions in full in W, Sec 2.5.7.3): the storey forces and so the beams' bars grew.
    assert reasons["L1-L3 interior"] == "joint shear at B2 L1"
    assert reasons["L4-L6 interior"] == "joint shear at B2 L4"
    by_id = {c["id"]: c["type"] for c in result["floorPlan"]["columns"]}
    assert by_id["C-B2-L1"] == "C700x700"
    assert by_id["C-B2-L4"] == "C700x700"
    method = next(n for n in result["notes"] if "PRELIMINARY P-M sizing" in n)
    assert "the joint shear with those bars (Sec 8.3.7.3" in method


# ── Detailing doubts of walk 3, checked against the default pack's text ──


def _rect_section(b, h, top, bottom, kind="beam"):
    from saengine.design.rc import section_of
    from saengine.library.objects import LinearReinforcement, RectangleProfile

    if kind == "beam":
        longitudinal = [
            {"position": "top", "count": top[0], "dia": top[1]},
            {"position": "bottom", "count": bottom[0], "dia": bottom[1]},
        ]
        transverse = {"type": "stirrup", "dia": 8, "spacing": 150}
    else:
        longitudinal = [{"position": "perimeter", "count": top[0], "dia": top[1]}]
        transverse = {"type": "tie", "dia": 10, "spacing": 100}
    reinforcement = LinearReinforcement.model_validate(
        {"material": "B420", "cover": 40, "longitudinal": longitudinal, "transverse": transverse}
    )
    return section_of(RectangleProfile(xDim=b, yDim=h), reinforcement, 24.1, 420.0)


def test_smf_beam_hoops_follow_8_db_of_the_default_pack() -> None:
    """B10 doubt "6 db = 96 mm": the default pack's BNBC 2020 Part 6 Sec 8.3.4.3(b) limits the
    hoops in the 2h end zones to min(d/4, 8 db of the smallest longitudinal bar, 24 dh,
    300 mm) (ACI 318-19's 6 db and 150 mm are not the pack's). A 300 x 600 beam with 7Ø16
    top, 2Ø20 bottom and Ø8 hoops: 8 x 16 = 128 mm against d/4 = (600 - 40 - 8 - 10) / 4 =
    135.5 mm, so 8 db governs at 128 mm; the proposal's "ends @ 125" is within it."""
    from saengine.design.ductile_members import beam_need

    need = beam_need(_rect_section(300, 600, (7, 16), (2, 20)), "special", 8.0)
    assert need.zone_spacing == pytest.approx(128.0)
    assert "8 db governs" in need.zone_rule
    assert need.zone_length == 1200.0  # 2h


def test_smf_column_zone_length_by_its_axial_force_and_clear_height() -> None:
    """B10 / FD doubts on lo: Sec 8.3.5.4(d) lo = max(h, ln/6, 450 mm) for a column above
    0.1 Ag f'c; at or below it the column is a flexural member (8.3.5.1, 8.3.4.1(a)) and
    SAEngine adds the 2h hoop zone of 8.3.4.3(a): why the lightly loaded upper C450/C550
    showed lo = 2h and the heavily loaded C600 h. C9 (400 mm) under the 1500 mm transfer beam
    B23 has ln = 3600 - 1500 = 2100 mm: lo = max(400, 350, 450) = 450 mm, not 525."""
    from saengine.design.ductile_members import Zones, column_need

    section = _rect_section(400, 400, (8, 16), None, kind="column")
    zones = Zones("tie", 10.0, 100.0, 3)
    heavy = column_need(section, "special", 40.0, zones, clear_height=2100.0, axial=1.0e6)
    assert heavy.zone_length == 450.0
    light = column_need(section, "special", 40.0, zones, clear_height=2100.0, axial=1.0e5)
    assert light.zone_length == 800.0  # 2h for Pu <= 0.1 Ag f'c = 385.6 kN


# ── FD-7: skin bars of a deep beam ──


def test_deep_beam_proposal_gives_the_skin_bars_its_check_asks_for() -> None:
    """FD-7: the 500 x 1500 transfer beam failed the skin check (h > 900 mm, the default pack's
    detailing.skin) and the proposal gave no side bars; side bars came only with torsion. Now
    a beam deeper than the limit gets side bars on each face between the top and bottom rows
    at most the crack-control spacing apart: fs = 2/3 fy = 280 MPa, cc = 40 + 10 = 50 mm,
    s = min(380 (280 / fs) - 2.5 cc, 300 (280 / fs)) = 255 mm; the gap between the rows
    1500 - 2 x 50 - (25 + 25) / 2 = 1375 mm needs ceil(1375 / 255) - 1 = 5 bars a face."""
    from saengine.design import bars as B
    from saengine.design import rc_detailing as RD
    from saengine.design.proposal import BeamDesigner, BeamLoads
    from saengine.design.rc import section_of
    from saengine.design.required import Options
    from saengine.library.objects import LinearReinforcement
    from tests.test_design_proposal import FC, FY, _beam

    beam = _beam(500, 1500)
    designer = BeamDesigner(beam, FC, FY, 200_000, None, Options())
    face = B.FaceBars(4, 25.0, 1)
    r = designer.reinforcement(face, face, B.Stirrups(10, 2, 200))
    sides = [g for g in r["longitudinal"] if g["position"] == "sides"]
    assert sides and sides[0]["count"] == 10
    section = section_of(beam.profile, LinearReinforcement.model_validate(r), FC, FY)
    row = RD.skin_check(section, {"top": True, "bottom": True})
    assert row is not None and row["ok"], row
    # A full proposal for the beam carries them too.
    pick = designer.propose(BeamLoads(1500e6, 1500e6, 600e3))
    assert pick.reinforcement is not None, pick.too_small
    assert any(g["position"] == "sides" for g in pick.reinforcement["longitudinal"])
    # A 450-deep beam without torsion gets none.
    shallow = BeamDesigner(_beam(250, 450), FC, FY, 200_000, None, Options())
    face = B.FaceBars(3, 16.0, 1)
    r = shallow.reinforcement(face, face, B.Stirrups(10, 2, 150))
    assert not [g for g in r["longitudinal"] if g["position"] == "sides"]


# ── B10-18: the pack's clauses in the slab and proposal notes ──


def test_slab_spacing_cites_the_code_pack() -> None:
    """B10-18: "ACI 8.7.2.2: min(2h, 450 mm)" in a BNBC project; the default pack gives the
    same limits in Part 6 Sec 6.5.3.2 (two-way: 2h) and 6.3.5.4 (one-way: 3h, 450 mm)."""
    from saengine.design.required import slab_layer_rules
    from saengine.design.slab import spacing_clause

    assert spacing_clause("twoWay") == "min(2h, 450 mm) (BNBC 2020 Part 6 Sec 6.5.3.2)"
    assert spacing_clause("oneWay") == "min(3h, 450 mm) (BNBC 2020 Part 6 Sec 6.3.5.4)"
    assert slab_layer_rules("twoWay", 150, None)["topX"] == (
        300.0,
        "min(2h, 450 mm) (BNBC 2020 Part 6 Sec 6.5.3.2)",
    )

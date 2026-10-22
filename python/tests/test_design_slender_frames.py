"""Column slenderness (saengine.design.slender) in frames beyond one column and one beam,
against hand calculations to BNBC 2020 Part 6 Sec 6.3.10: ψ with the lengths between the
joints (Figure 6.6.5's lc and l) and flat plates at 0.25 Ig (6.3.10.4.1), a column cut by a
tie beam between the floors swaying with its storey (6.3.10.7), the walls in a storey's ΣPu
and Vus (6.3.10.5.2), a combination loading the other direction, and the cracked storey drift
for Q.

The frames are synthetic, their section forces written in by hand (no analysis is run).
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from test_design_slender import EC, SECTION, STATIONS, _about_y, _frame, _rows, _sway_case

from saengine.design.check import _Piece
from saengine.design.slender import (
    CRACKED_BEAM,
    CRACKED_COLUMN,
    Model,
    SlenderContext,
    SlenderOptions,
    k_sway,
    storeys,
)
from saengine.library.bim import BuildingModel

E = 25e9  # N/m²
IC = 0.5 * 0.5**3 / 12  # m⁴, a 500 × 500 mm column
X = np.array([1.0, 0, 0])
EMPTY = BuildingModel.model_validate({"stories": [], "elements": []})
COLUMN_AXES = np.array([[0, 0, 1.0], [0, -1.0, 0], [1.0, 0, 0]])  # local x up, z = X


def _two_storeys(one_element: bool, beam_pieces: int = 1) -> dict:
    """A column 0 to 3 to 6 m with beams along X at both floors, 6 m to fixed far ends; the
    column one member (C1, C1#2) or two (C1, C2); beam B1 in ``beam_pieces`` elements."""
    nodes = [
        {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
        {"id": 2, "coords": [0, 0, 3.0], "restraint": [False] * 6},
        {"id": 4, "coords": [0, 0, 6.0], "restraint": [False] * 6},
        {"id": 3, "coords": [6.0, 0, 3.0], "restraint": [True] * 6},
        {"id": 5, "coords": [6.0, 0, 6.0], "restraint": [True] * 6},
    ]
    elements = [
        {"id": 1, "name": "C1", "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1},
        {
            "id": 2,
            "name": "C1#2" if one_element else "C2",
            "type": "ElasticBeamColumn",
            "nodes": [2, 4],
            "section_id": 1,
        },
        {"id": 4, "name": "B2", "type": "ElasticBeamColumn", "nodes": [4, 5], "section_id": 2},
    ]
    chain = [2] + [10 + k for k in range(beam_pieces - 1)] + [3]
    for k in range(beam_pieces - 1):
        x = 6.0 * (k + 1) / beam_pieces
        nodes.append({"id": 10 + k, "coords": [x, 0, 3.0], "restraint": [False] * 6})
    for k, (a, b) in enumerate(itertools.pairwise(chain)):
        elements.append(
            {
                "id": 20 + k,
                "name": "B1" if k == 0 else f"B1#{k + 1}",
                "type": "ElasticBeamColumn",
                "nodes": [a, b],
                "section_id": 2,
            }
        )
    sections = [{"id": 1, "E": E, "Iy": IC, "Iz": IC}, {"id": 2, "E": E, "Iy": 2 * IC, "Iz": IC}]
    return {"nodes": nodes, "elements": elements, "sections": sections}


def test_psi_takes_the_lengths_between_the_joints() -> None:
    # ψ at level 1 = Σ 0.70 E Ic / lc (3 m below, 3 m above) / (0.35 E 2Ic / 6 m) = 4.0, the
    # column modelled as two members or one member of two pieces; the beam in 1 or 3 pieces.
    hand = (2 * CRACKED_COLUMN * IC / 3) / (CRACKED_BEAM * 2 * IC / 6)
    assert hand == pytest.approx(4.0)
    for one in (False, True):
        for pieces in (1, 3):
            model = Model(_two_storeys(one, pieces), EMPTY, {})
            psi, note = model.psi(2, X, 1.0)
            assert psi == pytest.approx(hand), (one, pieces)
            assert note == ""
    # The chain of a member between its joints: 3 m each, not the member's whole 6 m.
    model = Model(_two_storeys(True), EMPTY, {})
    column = model.frames[1]
    assert model.joint_length(2, column) == pytest.approx(3.0)
    assert k_sway(1.0, 4.0) == pytest.approx(1.63, abs=0.01)  # not k_sway(1, 2) = 1.45


def test_psi_of_a_model_already_cracked_for_every_case() -> None:
    # Section stiffness ACI for every case: the model holds 0.70 Ic and 0.35 Ib; ψ is still
    # Σ 0.70 E Ic / lc / Σ 0.35 E Ib / l = 4.0 (the factors applied once, not twice).
    project = _two_storeys(True)
    project["sections"] = [
        {"id": 1, "E": E, "Iy": CRACKED_COLUMN * IC, "Iz": CRACKED_COLUMN * IC},
        {"id": 2, "E": E, "Iy": CRACKED_BEAM * 2 * IC, "Iz": CRACKED_BEAM * IC},
    ]
    psi, _ = Model(project, EMPTY, {}, cracked=True).psi(2, X, 1.0)
    assert psi == pytest.approx(4.0)
    psi_twice, _ = Model(project, EMPTY, {}).psi(2, X, 1.0)
    assert psi_twice == pytest.approx(4.0 * CRACKED_COLUMN / CRACKED_BEAM)  # 8.0, the error
    # A steel member (E above 50 GPa) is not concrete and is left as it is.
    steel = _two_storeys(True)
    steel["sections"] = [{"id": 1, "E": E, "Iy": IC, "Iz": IC}]
    steel["sections"].append({"id": 2, "E": 200e9, "Iy": 2 * IC, "Iz": IC})
    plain, _ = Model(steel, EMPTY, {}).psi(2, X, 1.0)
    cracked, _ = Model(steel, EMPTY, {}, cracked=True).psi(2, X, 1.0)
    assert cracked == pytest.approx(plain / CRACKED_COLUMN)  # only the column taken back


def _flat_plate() -> dict:
    """Two 500 mm columns 6 m apart along X, 6 m high from fixed bases, with a 200 mm slab
    (two shells, y -3 to 3 m) at their tops and no beam."""
    nodes = [
        {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
        {"id": 2, "coords": [0, 0, 6.0], "restraint": [False] * 6},
        {"id": 3, "coords": [6.0, 0, 0], "restraint": [True] * 6},
        {"id": 4, "coords": [6.0, 0, 6.0], "restraint": [False] * 6},
        {"id": 5, "coords": [0, -3.0, 6.0], "restraint": [False] * 6},
        {"id": 6, "coords": [6.0, -3.0, 6.0], "restraint": [False] * 6},
        {"id": 7, "coords": [6.0, 3.0, 6.0], "restraint": [False] * 6},
        {"id": 8, "coords": [0, 3.0, 6.0], "restraint": [False] * 6},
    ]
    elements = [
        {"id": 1, "name": "C1", "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1},
        {"id": 2, "name": "C2", "type": "ElasticBeamColumn", "nodes": [3, 4], "section_id": 1},
        {"id": 3, "name": "S1", "type": "Shell", "nodes": [5, 6, 4, 2], "section_id": 3},
        {"id": 4, "name": "S1#2", "type": "Shell", "nodes": [2, 4, 7, 8], "section_id": 3},
    ]
    sections = [
        {"id": 1, "E": E, "Iy": IC, "Iz": IC},
        {"id": 3, "type": "ElasticMembranePlateSection", "E": E, "nu": 0.2, "h": 0.2},
    ]
    return {"nodes": nodes, "elements": elements, "sections": sections}


def test_flat_plate_counts_in_psi_at_0_25_ig() -> None:
    # The slab-beam: l1 = 6 m to the other column, no columns across, so b = l1 = 6 m;
    # Ig = 6 × 0.2³ / 12 = 0.004 m⁴. ψ = 0.70 Ic / 6 / (0.25 × 0.004 / 6) = 3.646 (not ∞).
    model = Model(_flat_plate(), EMPTY, {})
    psi, note = model.psi(2, X, 1.0)
    hand = (CRACKED_COLUMN * IC / 6) / (0.25 * (6 * 0.2**3 / 12) / 6)
    assert psi == pytest.approx(hand, rel=1e-9) and hand == pytest.approx(3.646, abs=1e-3)
    assert note == "flat plate"
    assert k_sway(1.0, psi) < k_sway(1.0, 1000.0)  # 1.75 instead of 2.32
    # Across (Y) there is no column within reach: the slab gives no restraint, ψ = ∞.
    psi_y, note_y = model.psi(2, np.array([0, 1.0, 0]), 1.0)
    assert psi_y == 1000.0 and note_y == "no beams"


def _tie_beam_case(z_tie: float):
    """The sway case of test_design_slender (Pu = 2000 kN, Vus = 100 kN, 6 m storey) with a
    tie beam along X at ``z_tie`` cutting the column; the floor displaced 60 mm along X by EX:
    Q = 2000 × 0.060 / (100 × 6) = 0.20."""
    project, building, types = _frame(6.0)
    project["nodes"] += [
        {"id": 6, "coords": [0, 0, z_tie], "restraint": [False] * 6},
        {"id": 7, "coords": [6.0, 0, z_tie], "restraint": [True] * 6},
    ]
    project["elements"] = [
        {"id": 1, "name": "C1", "type": "ElasticBeamColumn", "nodes": [1, 6], "section_id": 1},
        {"id": 3, "name": "C1#2", "type": "ElasticBeamColumn", "nodes": [6, 2], "section_id": 1},
        {"id": 2, "name": "B1", "type": "ElasticBeamColumn", "nodes": [2, 3], "section_id": 2},
        {"id": 4, "name": "TB", "type": "ElasticBeamColumn", "nodes": [6, 7], "section_id": 2},
    ]

    def piece(pid, name, z0, z1, mb, mt, msb, mst):
        sway = [_rows(0.0, msb, mst, vz=1e5)]
        return _Piece(
            name,
            pid,
            z1 - z0,
            depth_along_z=False,
            axes=COLUMN_AXES,
            forces=[_rows(-2e6, mb, mt) + sway[0]],
            start=np.array([0, 0, z0]),
            end=np.array([0, 0, z1]),
            sway=sway,
            sustained=[_rows(-1.2e6, 0, 0)],
        )

    lower = piece(1, "C1", 0, z_tie, 20e3, 5e3, 200e3, 25e3)
    upper = piece(3, "C1#2", z_tie, 6, 5e3, -10e3, 25e3, -150e3)
    zero = [np.zeros((STATIONS, 6))]

    def beam(pid, name, z):
        return _Piece(
            name,
            pid,
            6.0,
            depth_along_z=True,
            axes=np.eye(3),
            forces=zero,
            start=np.array([0, 0, z]),
            end=np.array([6.0, 0, z]),
            sway=zero,
            sustained=zero,
        )

    disp = [{2: np.array([0.06, 0, 0, 0, 0, 0]), 3: np.array([0.06, 0, 0, 0, 0, 0])}]
    pieces = {"C1": [lower, upper], "B1": [beam(2, "B1", 6.0)], "TB": [beam(4, "TB", z_tie)]}
    options = SlenderOptions(drift_factor=1.0)
    context = SlenderContext(project, building, types, {}, pieces, ["1.2D + 1.0EX"], disp, options)
    return context, [lower, upper]


@pytest.mark.parametrize("z_tie", [2.5, 3.0])
def test_column_cut_by_a_tie_beam_sways_with_its_storey(z_tie: float) -> None:
    context, own = _tie_beam_case(z_tie)
    storey = next(s for s in context.storeys if s.direction == "X")
    # A node exactly at mid-height (3.0 m) still counts the column once (the piece above).
    assert storey.sum_pu[0] == pytest.approx(2e6) and storey.vus[0] == pytest.approx(1e5)
    assert storey.q[0] == pytest.approx(0.2) and storey.sway is True
    axis = _about_y(context.column("C1", SECTION, own, False, EC))
    s = axis.check["slenderness"]
    assert s["sway"] is True and s["deltaS"] == pytest.approx(1.25)  # 1 / (1 - 0.2)
    assert axis.check["name"].startswith("Slenderness about y (sway, δs = 1.25")
    assert axis.delta_s == [pytest.approx(1.25)]
    assert s["limit"] == 22.0 and s["k"] >= 1.0
    # The lower segment's bottom moment: 20 + 1.25 × 200 = 270 kN·m in the strength check.
    bottom = [
        p for p in context.column("C1", SECTION, own, False, EC).points if p[4].endswith("0.00 L")
    ]
    assert max(p[2] for p in bottom) == pytest.approx(270e6, rel=1e-6)


def _wall_storey(n22: float, n12: float):
    """The test column (6 m, Pu 2000 kN, Vus 100 kN along X) beside a 1 m wide wall shell in
    the X-Z plane with a vertical membrane force N22 and an in-plane shear N12 [N/m] (all of
    the shear from the lateral case); the floor displaced 20 mm along X."""
    project, building, _ = _frame(6.0)
    project["nodes"] += [
        {"id": 10, "coords": [1.0, 0, 0], "restraint": [True] * 6},
        {"id": 11, "coords": [2.0, 0, 0], "restraint": [True] * 6},
        {"id": 12, "coords": [2.0, 0, 6.0], "restraint": [False] * 6},
        {"id": 13, "coords": [1.0, 0, 6.0], "restraint": [False] * 6},
    ]
    project["elements"].append(
        {"id": 9, "name": "W1", "type": "Shell", "nodes": [10, 11, 12, 13], "section_id": 3}
    )
    sway = [_rows(0.0, 200e3, -150e3, vz=1e5)]
    column = _Piece(
        "C1",
        1,
        6.0,
        depth_along_z=False,
        axes=COLUMN_AXES,
        forces=[_rows(-2e6, 20e3, -10e3) + sway[0]],
        start=np.array([0, 0, 0.0]),
        end=np.array([0, 0, 6.0]),
        sway=sway,
        sustained=[_rows(-1.2e6, 0, 0)],
    )
    total = np.zeros((4, 8))
    total[:, 1], total[:, 2] = n22, n12  # axes e1 = X, e2 = Z (up), e3 = -Y
    lateral = np.zeros((4, 8))
    lateral[:, 2] = n12
    disp = {n: np.array([0.02, 0, 0, 0, 0, 0]) for n in (2, 3, 12, 13)}
    return storeys(
        project,
        building,
        {"C1": [column]},
        ["1.2D + 1.0EX"],
        [disp],
        1.0,
        {9: ([total], [lateral])},
    )


def test_walls_count_in_the_storey_load_and_shear() -> None:
    # The wall carries 1000 kN down (N22 = -1000 kN/m over 1 m) and 50 kN of shear: ΣPu =
    # 3000 kN, Vus = 150 kN; Q = 3000 × 0.020 / (150 × 6) = 0.0667.
    found = _wall_storey(-1e6, 5e4)
    x = next(s for s in found if s.direction == "X")
    assert x.sum_pu[0] == pytest.approx(3e6) and x.vus[0] == pytest.approx(1.5e5)
    assert x.q[0] == pytest.approx(3e6 * 0.02 / (1.5e5 * 6))
    # A wall taking most of the shear: Vus = 100 + 400 kN, Q = 3000 × 0.020 / (500 × 6) =
    # 0.020, nonsway (the frame alone would have given 0.0667: a false sway storey).
    x = next(s for s in _wall_storey(-1e6, 4e5) if s.direction == "X")
    assert x.vus[0] == pytest.approx(5e5)
    assert x.q[0] == pytest.approx(3e6 * 0.02 / (5e5 * 6)) and x.sway is False


def test_combination_loading_the_other_direction_defines_no_q() -> None:
    # EX loads X (Vus,X = 100 kN, Δ 20 mm); WY loads Y (200 kN) with a 10 kN by-product along X
    # and the same 20 mm drift along X from torsion: its Q along X would be 2000 × 0.020 /
    # (10 × 6) = 0.67. It is not taken (10 < 0.25 × 200); Q along X is EX's 0.0667.
    project, building, _types = _frame(6.0)
    sway = [_rows(0.0, 200e3, -150e3, vz=1e5), _rows(0.0, 20e3, -15e3, vz=1e4)]
    sway[1][:, 1] = 2e5  # Vy along local y = -Y
    column = _Piece(
        "C1",
        1,
        6.0,
        depth_along_z=False,
        axes=COLUMN_AXES,
        forces=[_rows(-2e6, 0, 0) + s for s in sway],
        start=np.array([0, 0, 0.0]),
        end=np.array([0, 0, 6.0]),
        sway=sway,
        sustained=[_rows(-1.2e6, 0, 0)] * 2,
    )
    disp = [{n: np.array([0.02, 0, 0, 0, 0, 0]) for n in (2, 3)}] * 2
    found = storeys(project, building, {"C1": [column]}, ["1.0EX", "1.0WY"], disp, 1.0)
    x = next(s for s in found if s.direction == "X")
    assert x.vus == [pytest.approx(1e5), pytest.approx(1e4)]
    assert x.q[0] == pytest.approx(0.0667, abs=1e-4) and x.q[1] is None
    assert x.q_max == (pytest.approx(0.0667, abs=1e-4), 0)


def test_response_spectrum_storey_shear_is_the_spectrum_s_own() -> None:
    # A response spectrum sign pattern: the column's sway rows are a uniform-sign envelope
    # whose global sum here is only 20 kN along X, but the spectrum's storey shear at the cut
    # (its modal storey shears combined) is 100 kN: Vus = 100 kN, Q = 2000 × 0.020 / (100 × 6).
    project, building, _types = _frame(6.0)
    sway = [_rows(0.0, 0.0, 0.0, vz=2e4)]
    column = _Piece(
        "C1",
        1,
        6.0,
        depth_along_z=False,
        axes=COLUMN_AXES,
        forces=[_rows(-2e6, 0, 0) + sway[0]],
        start=np.array([0, 0, 0.0]),
        end=np.array([0, 0, 6.0]),
        sway=sway,
        sustained=[_rows(-1.2e6, 0, 0)],
    )
    disp = [{n: np.array([0.02, 0, 0, 0, 0, 0]) for n in (2, 3)}]
    cuts: list[float] = []

    def shear(cut: float) -> np.ndarray:
        cuts.append(cut)
        return np.array([1e5, 5e3, 0.0])

    plain = storeys(project, building, {"C1": [column]}, ["RS"], disp, 1.0)
    assert next(s for s in plain if s.direction == "X").vus[0] == pytest.approx(2e4)
    found = storeys(project, building, {"C1": [column]}, ["RS"], disp, 1.0, storey_shear=[shear])
    x = next(s for s in found if s.direction == "X")
    assert cuts and cuts[0] == pytest.approx(3.0)  # the storey's mid-height
    assert x.vus[0] == pytest.approx(1e5)
    assert x.q[0] == pytest.approx(2e6 * 0.02 / (1e5 * 6))
    # The 5 kN across is a by-product (< 0.25 × 100 kN): no Q along Y from it.
    y = next(s for s in found if s.direction == "Y")
    assert y.vus[0] == pytest.approx(5e3) and y.q[0] is None


def test_cracked_storey_drift_factor_by_hand() -> None:
    # The test frame: column Kc = E Ic / 6, beam Kb = E 2Ic / 6 = 2 Kc at the top, a fixed
    # base (its term 0). Δ ∝ 1/Kc + (0 + 1/Kb)/2: gross 1 + 0.25 = 1.25 (per 1/Kc); cracked
    # 1/0.70 + (0 + 1/(0.35 × 2))/2 = 1.4286 + 0.7143 = 2.1429; factor 2.1429/1.25 = 1.714.
    project, building, types = _frame(6.0)
    model = Model(project, building, types)
    hand = (1 / 0.7 + 0.5 / (0.35 * 2)) / (1 + 0.5 / 2)
    assert model.drift_factor(0.0, 6.0, X, [1]) == pytest.approx(hand, rel=1e-9)
    assert hand == pytest.approx(1.714, abs=1e-3)
    # By default Q takes it: the sway case's Q = 0.0667 × 1.714 = 0.114.
    context, _ = _sway_case(0.02, SlenderOptions())
    storey = next(s for s in context.storeys if s.direction == "X")
    assert storey.factor == [pytest.approx(hand)]
    assert storey.q[0] == pytest.approx(2e6 * 0.02 * hand / (1e5 * 6))
    # A flat plate's storey: 0.25 Ig plates make the cracked drift larger still.
    plate = Model(_flat_plate(), EMPTY, {})
    kc = 2 * E * IC / 6
    kb = (E * 6 * 0.2**3 / 12 / 6) / 2 * 2  # the panel once, seen from its two columns
    plate_hand = (1 / (0.7 * kc) + 0.5 / (0.25 * kb)) / (1 / kc + 0.5 / kb)
    assert plate.drift_factor(0.0, 6.0, X, [1, 2]) == pytest.approx(plate_hand, rel=1e-9)
    assert math.isclose(min(max(plate_hand, 1 / 0.7), 4.0), plate_hand)


# ───────────── the cracked model read from the analysis model itself ─────────────


def _gross_frame() -> tuple[dict, object, dict]:
    """The test frame with sections that are the building profiles' gross ones: column
    500 × 500 (A 0.25 m²), beam 300 × 600 (A 0.18 m²)."""
    project, building, types = _frame(6.0)
    ic = 0.5**4 / 12
    project["sections"] = [
        {"id": 1, "type": "ElasticSection", "E": EC * 1e6, "A": 0.25, "Iy": ic, "Iz": ic},
        {
            "id": 2,
            "type": "ElasticSection",
            "E": EC * 1e6,
            "A": 0.18,
            "Iy": 0.3 * 0.6**3 / 12,
            "Iz": 0.6 * 0.3**3 / 12,
        },
    ]
    return project, building, types


def _cracked(project: dict) -> dict:
    """``project`` as saengine.fem.second_order leaves it with crackedFor "all"."""
    out = {**project, "sections": [dict(s) for s in project["sections"]]}
    for section, factor in zip(out["sections"], (CRACKED_COLUMN, CRACKED_BEAM), strict=True):
        section["Iy"] *= factor
        section["Iz"] *= factor
    return out


def _mats(category=None) -> dict:
    from saengine.library import default_material_library

    mats = {m.id: m for m in default_material_library().materials}
    if category is not None:
        mats["C27.6"] = mats["C27.6"].model_copy(update={"category": category})
    return mats


def test_cracked_sections_found_from_the_model_not_the_settings() -> None:
    # ψ at the top = (0.70 Ic / 6) / (0.35 Ib / 6), Ib the beam's gross 0.3 × 0.6³ / 12.
    gross, building, types = _gross_frame()
    hand = (CRACKED_COLUMN * 0.5**4 / 12) / (CRACKED_BEAM * 0.3 * 0.6**3 / 12)
    plain = Model(gross, building, types, mats=_mats())
    assert plain.psi(2, X, 1.0)[0] == pytest.approx(hand)
    assert plain.cracked_frames == 0 and not plain.lateral_cracked
    # The model's sections are the cracked ones (crackedFor "all"): found per section (the
    # gross area, I at 0.70 / 0.35 of the profile's) and taken back once: the same ψ.
    cracked = Model(_cracked(gross), building, types, mats=_mats())
    assert cracked.cracked_frames == 2 and cracked.lateral_cracked
    assert cracked.psi(2, X, 1.0)[0] == pytest.approx(hand)
    # A section neither gross nor at a cracked factor is left alone (I edited by hand, say).
    odd = _cracked(gross)
    odd["sections"][0]["Iy"] *= 0.9
    assert Model(odd, building, types, mats=_mats()).cracked_frames == 1  # the beam alone


def test_cracked_sections_only_for_concrete_frames() -> None:
    from saengine.library.materials import Category

    gross, building, types = _gross_frame()
    # A material that is not concrete or masonry (timber, "other", E <= 50 GPa) was never
    # cracked by saengine.fem.second_order: not taken back, found or forced.
    timber = _mats(Category.OTHER)
    assert Model(_cracked(gross), building, types, mats=timber).cracked_frames == 0
    assert Model(_cracked(gross), building, types, True, timber).cracked_frames == 0
    # Only ElasticBeamColumn elements on ElasticSection sections.
    other = _cracked(gross)
    other["elements"] = [dict(e, type="ForceBeamColumn") for e in other["elements"]]
    assert Model(other, building, types, mats=_mats()).cracked_frames == 0
    assert Model(other, building, types, True, _mats()).cracked_frames == 0
    fiber = _cracked(gross)
    fiber["sections"] = [dict(s, type="FiberSection") for s in fiber["sections"]]
    assert Model(fiber, building, types, True, _mats()).cracked_frames == 0


def test_lateral_cases_on_cracked_sections_give_drift_factor_one() -> None:
    # crackedFor "lateral": the model keeps the gross sections, the lateral static cases carry
    # the cracked ones as section overrides: Δo is the cracked drift, the factor 1.0 (and ψ
    # from the gross sections as they are).
    gross, building, types = _gross_frame()
    gross["analyses"] = [
        {"id": 1, "name": "D: dead", "type": "Static"},
        {
            "id": 2,
            "name": "EX: earthquake X",
            "type": "Static",
            "section_overrides": _cracked(gross)["sections"],
        },
    ]
    model = Model(gross, building, types, mats=_mats())
    assert model.lateral_cracked and model.cracked_frames == 0
    # The temperature case's gross copies (crackedFor "all") are not a lateral case's.
    thermal = {**gross, "analyses": [dict(gross["analyses"][1], name="T: temperature")]}
    assert not Model(thermal, building, types, mats=_mats()).lateral_cracked
    # In the context the default drift factor follows the model: 1.0 here, the storey's
    # cracked-over-gross ratio without the overrides.
    context, _ = _sway_case(0.02, SlenderOptions())
    assert context.storeys[0].factor[0] > 1.0
    from test_design_slender import _piece

    piece = _piece(6.0, [_rows(-2e6, 20e3, -10e3)], [_rows(0, 200e3, -150e3, vz=1e5)], None)
    disp = [{2: np.array([0.02, 0, 0, 0, 0, 0])}]
    found = SlenderContext(gross, building, types, _mats(), {"C1": [piece]}, ["1.2D + 1.0EX"], disp)
    assert all(f == 1.0 for s in found.storeys for f in s.factor)


def test_sum_pc_with_the_bars_and_beta_dns_by_hand() -> None:
    # Eq. 6.6.28 with EI of 6.3.10.6.1 (BNBC 6.3.10.7.4): the "bars" option, Eq. 6.6.21
    # (0.2 Ec Ig + Es Ise) / (1 + βdns), βdns = 1200 / 2000 = 0.6, k from the sway chart.
    from test_design_slender import REINFORCEMENT, _piece, _sway_root

    from saengine.design.rc import section_of
    from saengine.design.slender import concrete_modulus
    from saengine.library.objects import RectangleProfile

    project, building, types = _frame(6.0)
    types["COL"] = types["COL"].model_copy(update={"reinforcement": REINFORCEMENT})
    mats = _mats()
    ec = concrete_modulus(mats["C27.6"])
    section = section_of(RectangleProfile(xDim=500, yDim=500), REINFORCEMENT, 27.6, 420)
    ise = sum(bar.area * bar.x**2 for bar in section.bars)
    ig = 500**4 / 12
    ei = (0.2 * ec * ig + 200_000 * ise) / 1.6
    k = _sway_root(1.0, 1.0)
    pc = math.pi**2 * ei / (k * 5400) ** 2
    sway = [_rows(0.0, 200e3, -150e3, vz=1e5)]
    piece = _piece(6.0, [_rows(-2e6, 20e3, -10e3) + sway[0]], sway, [_rows(-1.2e6, 0, 0)])
    beam = _Piece(
        "B1",
        2,
        6.0,
        depth_along_z=True,
        axes=np.eye(3),
        forces=[np.zeros((STATIONS, 6))],
        start=np.array([0, 0, 6.0]),
        end=np.array([6.0, 0, 6.0]),
        sway=[np.zeros((STATIONS, 6))],
        sustained=[np.zeros((STATIONS, 6))],
    )
    disp = [{2: np.array([0.2, 0, 0, 0, 0, 0]), 3: np.array([0.2, 0, 0, 0, 0, 0])}]
    options = SlenderOptions(drift_factor=1.0, sway_magnifier="sumPc", stiffness="bars")
    context = SlenderContext(
        project,
        building,
        types,
        mats,
        {"C1": [piece], "B1": [beam]},
        ["1.2D + 1.0EX"],
        disp,
        options,
    )
    storey = next(s for s in context.storeys if s.direction == "X")
    assert storey.sum_pc == [pytest.approx(pc, rel=1e-3)]
    assert storey.delta_s(0, "sumPc") == pytest.approx(1 / (1 - 2e6 / (0.75 * pc)), rel=1e-3)


def test_response_spectrum_combination_single_curvature_and_cm_one() -> None:
    # Braced column, Pu = 3000 kN, ends 60 and -100 kN·m (double curvature, M1/M2 = -0.6):
    # k lu / r = 5400 / 150 = 36 <= 34 + 7.2 -> 40: neglected. The same moments in a response
    # spectrum combination (± E, no sign) are taken in single curvature: limit 34 - 7.2 =
    # 26.8 < 36, designed with Cm = 1.0.
    from test_design_slender import _piece

    total = [_rows(-3e6, 60e3, -100e3)]
    zero = [np.zeros((STATIONS, 6))]
    project, building, types = _frame(6.0)

    def run(spectrum):
        piece = _piece(6.0, total, zero, [_rows(-1.5e6, 0, 0)])
        beam = _Piece(
            "B1",
            2,
            6.0,
            depth_along_z=True,
            axes=np.eye(3),
            forces=zero,
            start=np.array([0, 0, 6.0]),
            end=np.array([6.0, 0, 6.0]),
            sway=zero,
            sustained=zero,
        )
        context = SlenderContext(
            project,
            building,
            types,
            {},
            {"C1": [piece], "B1": [beam]},
            ["c"],
            [{}],
            None,
            None,
            spectrum,
        )
        return _about_y(context.column("C1", SECTION, [piece], False, EC)).check

    static = run(None)
    assert static["slenderness"]["neglected"] and static["slenderness"]["limit"] == 40.0
    spectral = run([True])
    s = spectral["slenderness"]
    assert not s["neglected"] and s["limit"] == pytest.approx(34 - 12 * 0.6)
    assert s["Cm"] == 1.0
    assert "response spectrum combination" in spectral["note"]


def test_response_spectrum_shell_sway_carried_through() -> None:
    # The walls' lateral parts for the RS design's combinations: a kept combination keeps its
    # own, a sign pattern adds the ± E it added to the forces (check._spectrum_shell_sway).
    from saengine.design.check import _spectrum_shell_sway

    r_a, r_b = np.full((4, 8), 1.0), np.full((4, 8), 2.0)
    s_a, s_b = np.full((4, 8), 0.1), np.full((4, 8), 0.2)
    e = np.full((4, 8), 5.0)
    static = {
        "names": ["A", "B"],
        "shells": {9: [r_a, r_b]},
        "inner": {"shellSway": {9: [s_a, s_b]}},
    }
    names = ["A", "B [+N]", "B [-N]"]
    found = _spectrum_shell_sway(static, names, {9: [r_a, r_b + e, r_b - e]})
    assert [f.tolist() for f in found[9]] == [s_a.tolist(), (s_b + e).tolist(), (s_b - e).tolist()]

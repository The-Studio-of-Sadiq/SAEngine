"""Design at the faces of the supports (saengine.design.face_forces), checked by hand.

A 6 m beam with both ends fixed under w = 20 kN/m (synthetic): the moment at the joints is
w L² / 12 = 60 kN·m (hogging), at mid-span w L² / 24 = 30 kN·m (sagging). Columns 600 mm wide
put the support faces 0.30 m from the joints, where the moment is
60 - w a (L - a) / 2 = 60 - 17.1 = 42.9 kN·m: 28.5 % less than at the joint, the order of the
differences the comparison with a commercial analysis program showed between its face moments
and SAEngine's joint moments (7 % to 39 % for the sample's beams).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.design import face_forces
from saengine.design.check import _beam_checks, _Piece
from saengine.design.rc import flexure, section_of, shear
from saengine.design.required import BeamGeometry, beam_need
from saengine.library.objects import Beam, LinearReinforcement, RectangleProfile

STATIONS = 11
W = 20e3  # N/m
L = 6.0  # m
A = 0.30  # m, joint to face
FC, FY = 28.0, 420.0

REINFORCEMENT = LinearReinforcement.model_validate(
    {
        "material": "B420DWR",
        "cover": 40,
        "longitudinal": [
            {"position": "top", "count": 3, "dia": 20},
            {"position": "bottom", "count": 3, "dia": 20},
        ],
        "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
    }
)
BEAM = Beam.model_validate(
    {
        "id": "BM",
        "name": "BM",
        "material": "C27.6",
        "profile": {"shape": "rectangle", "xDim": 300, "yDim": 600},
        "reinforcement": REINFORCEMENT.model_dump(),
    }
)
SECTION = section_of(RectangleProfile(xDim=300, yDim=600), REINFORCEMENT, FC, FY)


def moment(x: float) -> float:
    """My [N·m], positive hogging (the top in tension, as the analysis gives a floor beam)."""
    return W * L**2 / 12 - W * x * (L - x) / 2


def shear_at(x: float) -> float:
    return W * (L / 2 - x)


def _rows() -> np.ndarray:
    rows = np.zeros((STATIONS, 6))
    xs = np.linspace(0.0, L, STATIONS)
    rows[:, 2] = [shear_at(x) for x in xs]  # Vz: shear along the depth (local z up)
    rows[:, 4] = [moment(x) for x in xs]
    return rows


def _beam(rows: list[np.ndarray]) -> _Piece:
    return _Piece(
        "B1",
        7,
        L,
        depth_along_z=True,
        axes=np.eye(3),
        forces=rows,
        start=np.array([0.0, 0.0, 3.0]),
        end=np.array([L, 0.0, 3.0]),
        sway=[np.zeros((STATIONS, 6)) for _ in rows],
        sustained=[r * 0.5 for r in rows],
    )


def _project(i: float | None = A * 1e3, j: float | None = A * 1e3) -> dict:
    element = {"id": 7, "name": "B1", "type": "ElasticBeamColumn", "nodes": [1, 2]}
    if i is not None or j is not None:
        element["faceOffsets"] = {"i": i, "j": j}
    return {"nodes": [], "elements": [element]}


def test_face_moment_and_shear_at_d_by_hand() -> None:
    piece = _beam([_rows()])
    d = face_forces.shear_depth(SECTION)
    # d = 600 - 40 - 10 - 10 = 540 mm (one row of Ø20, Ø10 stirrups), on either face.
    assert d == pytest.approx(0.540, abs=1e-6)
    faced = face_forces.at_faces([piece], _project(), shear_depth=d)
    assert faced.source == "analysis" and faced.at_faces
    rows = faced.pieces[0].forces[0]
    hand = moment(A)  # 42.9 kN·m
    assert hand == pytest.approx(42.9e3)
    assert rows[0, 4] == pytest.approx(hand, rel=1e-9)  # the parabola is exact here
    assert rows[-1, 4] == pytest.approx(hand, rel=1e-9)
    assert 1 - hand / moment(0.0) == pytest.approx(0.285, abs=1e-3)  # 28.5 % below the joint
    # Mid-span (sagging) unchanged; every station outside the supports unchanged.
    assert rows[5, 4] == pytest.approx(moment(L / 2))
    np.testing.assert_allclose(rows[1:-1, 4], _rows()[1:-1, 4])
    # Shear at d from the face, BNBC 6.4.1.3.1: w (L/2 - a - d) = 20 (3 - 0.84) = 43.2 kN,
    # at every station between the joint and the section at d (x = 0 and 0.6 m).
    assert rows[0, 2] == pytest.approx(shear_at(A + d), rel=1e-9)
    assert rows[1, 2] == pytest.approx(shear_at(A + d), rel=1e-9)
    assert rows[2, 2] == pytest.approx(shear_at(1.2))  # beyond d: unchanged
    assert rows[-1, 2] == pytest.approx(shear_at(L - A - d), rel=1e-9)
    # The lateral and sustained parts move alike (linear), the original stays as it was.
    assert faced.pieces[0].sustained[0][0, 4] == pytest.approx(0.5 * hand)
    assert piece.forces[0][0, 4] == pytest.approx(moment(0.0))
    labels = faced.pieces[0].face_labels
    assert labels[0] == "B1 at the support face, 0.30 m from the joint, shear at d from the face"
    assert labels[1] == "B1 at 0.10 L (shear taken at d from the face)"
    assert set(labels) == {0, 1, 9, 10}
    assert "0.30 m from the joints" in faced.describe()
    assert "d = 0.540 m" in faced.shear_note()


def test_beam_designed_with_the_face_moment_needs_less_top_steel() -> None:
    piece = _beam([_rows()])
    capacities = {hog: flexure(SECTION, hog) for hog in (False, True)}
    joint = _beam_checks(SECTION, capacities, BEAM, [piece], ["1.4D"])
    faced = face_forces.at_faces([piece], _project(), face_forces.shear_depth(SECTION))
    face = face_forces.annotate(
        _beam_checks(SECTION, capacities, BEAM, faced.pieces, ["1.4D"]), faced
    )
    by = {c["name"]: c for c in face}
    by_joint = {c["name"]: c for c in joint}
    hog = "Flexure, hogging (top bars)"
    sag = "Flexure, sagging (bottom bars)"
    assert by_joint[hog]["demand"] == pytest.approx(60.0)
    assert by[hog]["demand"] == pytest.approx(42.9)
    assert by[sag]["demand"] == pytest.approx(by_joint[sag]["demand"]) == pytest.approx(30.0)
    assert by["Shear"]["demand"] == pytest.approx(43.2, abs=0.01)
    assert by_joint["Shear"]["demand"] == pytest.approx(60.0)
    assert "BNBC 2020 Part 6 Sec 6.1.6.3" in by[hog]["note"]
    assert "BNBC 2020 Part 6 Sec 6.4.1.3.1" in by["Shear"]["note"]
    # The design mode's top steel for the two moments (BNBC/ACI strength design): less at the
    # face, in proportion to the moment near enough (the lever arm barely changes).
    g = BeamGeometry(300, 600, 540, 540, FC, FY, 200_000, FY)
    vu = shear(SECTION, 10, 2, 150).phi_vn * 0.5
    at_joint = beam_need(g, 30e6, 60e6, vu)[0]
    at_face = beam_need(g, 30e6, 42.9e6, vu)[0]
    assert at_face.top < at_joint.top
    assert at_face.top / at_joint.top == pytest.approx(42.9 / 60, rel=0.05)
    assert at_face.bottom == pytest.approx(at_joint.bottom)


def test_no_face_offsets_keeps_the_joint_forces_with_a_note() -> None:
    piece = _beam([_rows()])
    faced = face_forces.at_faces([piece], _project(None, None), 0.54)
    assert faced.source == "joints" and faced.pieces[0] is piece
    assert faced.notes == [face_forces.JOINT_NOTE]
    checks = face_forces.annotate([{"name": "Shear", "note": "Vc = 1"}], faced)
    assert checks[0]["note"] == f"Vc = 1; {face_forces.JOINT_NOTE}"
    # Zero offsets on every element: the same.
    assert face_forces.at_faces([piece], _project(0, 0)).source == "joints"


def test_one_supported_end_and_the_shear_at_the_face() -> None:
    # A beam framing into a girder at j (no face) and a column at i; shear at the face.
    piece = _beam([_rows()])
    faced = face_forces.at_faces([piece], _project(A * 1e3, 0))
    rows = faced.pieces[0].forces[0]
    assert rows[0, 4] == pytest.approx(moment(A)) and rows[0, 2] == pytest.approx(shear_at(A))
    assert rows[-1, 4] == pytest.approx(moment(L)) and rows[-1, 2] == pytest.approx(shear_at(L))
    assert faced.shear_depth is None and "shear at the support faces" in faced.shear_note()


def test_analysis_face_forces_combined_and_taken_over_the_interpolation() -> None:
    piece = _beam([_rows(), 2 * _rows()])
    by_case = {
        "D": {7: {"i": {"My": 40e3, "Vz": 50e3}, "j": {"My": 41e3, "Vz": -50e3}}},
        "L": {7: {"i": {"My": 10e3}, "j": {"My": 10e3}}},
    }
    rows = face_forces.combined_face_rows(by_case, [{"D": 1.4}, {"D": 1.2, "L": 1.6}], 7)
    assert rows is not None and rows[0][0, 4] == pytest.approx(56e3)
    assert rows[1][1, 4] == pytest.approx(1.2 * 41e3 + 16e3)
    assert face_forces.combined_face_rows(by_case, [{"W": 1.0}], 7) is None
    faced = face_forces.at_faces([piece], _project(), None, {7: rows})
    assert faced.pieces[0].forces[0][0, 4] == pytest.approx(56e3)
    assert faced.pieces[0].forces[1][-1, 4] == pytest.approx(1.2 * 41e3 + 16e3)


def test_the_analysis_face_forces_file(tmp_path) -> None:
    # The shape saengine.fem.end_zones writes (face-forces.json): string element ids.
    import json

    data = {
        "schema": "saengine.faceForces/1",
        "rigidZoneFactor": 0.5,
        "faceOffsets": {"7": {"i": 300.0, "j": 300.0}},
        "cases": {"D": {"7": {"i": {"My": moment(A), "Vz": shear_at(A)}, "j": {"My": moment(A)}}}},
    }
    (tmp_path / "face-forces.json").write_text(json.dumps(data), encoding="utf-8")
    read = face_forces.read_face_forces(tmp_path)
    assert read is not None and face_forces.read_face_forces(tmp_path / "none") is None
    piece = _beam([1.4 * _rows()])
    rows = face_forces.face_rows_of(read, [{"D": 1.4}], [piece])
    assert rows[7][0][0, 4] == pytest.approx(1.4 * moment(A))
    # Offsets from the file (the element itself has none in the model).
    faced = face_forces.at_faces([piece], _project(None, None), 0.54, rows, read["faceOffsets"])
    assert faced.at_faces and faced.offsets == {7: (0.3, 0.3)}
    assert faced.pieces[0].forces[0][0, 4] == pytest.approx(1.4 * moment(A))
    # Shear at d: the file's face shear plus the stations' change from the face to d.
    assert faced.pieces[0].forces[0][0, 2] == pytest.approx(1.4 * shear_at(A + 0.54))


def test_column_strength_points_at_the_beam_soffit() -> None:
    # A 3 m column, the beam 500 mm deep at its top: My linear 10 -> 70 kN·m from the base to
    # the joint; at the soffit (2.5 m) 60 kN·m. The strength points take it, the slenderness
    # end moments stay the joints'.
    from test_design_slender import SECTION as COLUMN
    from test_design_slender import _context, _piece

    rows = np.zeros((STATIONS, 6))
    rows[:, 0] = -1e6
    rows[:, 4] = np.linspace(10e3, 70e3, STATIONS)
    piece = _piece(3.0, [rows], [np.zeros((STATIONS, 6))], [rows])
    project = {"elements": [{"id": 1, "faceOffsets": {"i": 0, "j": 500}}]}
    faced = face_forces.at_faces([piece], project)
    top = faced.pieces[0].forces[0][-1]
    assert top[4] == pytest.approx(60e3) and top[0] == pytest.approx(-1e6)
    context = _context(piece, ["1.4D"], [{}], height=3.0)
    result = context.column("C1", COLUMN, [piece], False, 25_000.0, faced.pieces)
    at_top = [p for p in result.points if p[4].startswith("C1 at 1.00")]
    assert at_top and at_top[0][2] == pytest.approx(60e6)
    axis = next(a for a in result.axes if a.axis == "y")
    assert axis.check["slenderness"]["M2"] == pytest.approx(70.0)


def test_interpolation_is_exact_for_a_parabola() -> None:
    rows = np.array([[x * x - 3 * x + 2] for x in np.linspace(0, 4, 9)])
    for x in (0.0, 0.13, 1.7, 3.99, 4.0):
        assert face_forces._interpolate(rows, 4.0, x)[0] == pytest.approx(x * x - 3 * x + 2)
    # Two stations: a straight line between them (2 at 0, 0.75 at the other end).
    assert math.isclose(face_forces._interpolate(rows[:2], 4.0, 2.0)[0], (2 + 0.75) / 2)

"""Member end releases and point springs (#303): known answers by hand.

- a propped cantilever whose fixed end releases its moments is a simply supported beam;
- a cantilever propped on a point spring shares a point load with the spring by compatibility;
- releases that leave a mechanism are a clear error, not a failed analysis.
"""

from __future__ import annotations

import pytest

from saengine.fem.derive import MechanismError
from saengine.library.bim import BuildingModel, EndRelease, PointSpring
from saengine.verification.cases.analysis import BEAM, E_C, I_BM
from saengine.verification.cases.common import (
    MATERIALS,
    building,
    derive,
    node_at,
    objects,
    only_pattern,
    point,
    run_model,
    settings,
    structure,
)

L = 6.0  # m
P = 50e3  # N at mid-span


def _beam(*supports: dict) -> BuildingModel:
    """A 6 m beam along X in two members (a node at mid-span) on ``supports``."""
    return building(
        structure(
            members=[
                {"id": "M1", "type": "BM", "start": point(0, 0, 0), "end": point(3000, 0, 0)},
                {"id": "M2", "type": "BM", "start": point(3000, 0, 0), "end": point(6000, 0, 0)},
            ],
            supports=list(supports),
        )
    )


def _with(model: BuildingModel, **additions: list) -> BuildingModel:
    model.additions = model.additions.model_copy(update=additions)
    return model


def _run(model: BuildingModel, tmp_path):
    derivation = derive(model, objects(BEAM), MATERIALS, settings())
    project = derivation.project
    mid = node_at(project, (L / 2, 0, 0))
    only_pattern(project, nodal=[{"node_id": mid, "forces": [0, 0, -P, 0, 0, 0]}])
    _, _, results = run_model(project, tmp_path, [1])
    return derivation, project, results[1], mid


def test_released_fixed_end_makes_a_simple_beam(tmp_path):
    """Fixed at x = 0, pinned at x = L; M1 releases its moments (M2, M3) at its start: the
    beam is simply supported, so R_A = P/2 (not the propped cantilever's 11P/16), no moment
    at the fixed support, and δ_mid = PL³/(48EI)."""
    model = _with(
        _beam(
            {"id": "S1", "at": point(0, 0, 0), "fixity": "fixed"},
            {"id": "S2", "at": point(6000, 0, 0), "fixity": "pinned"},
        ),
        endReleases=[EndRelease(id="ER1", member="M1", start={"M2": 0, "M3": 0})],
    )
    derivation, project, result, mid = _run(model, tmp_path)
    links = [e for e in project["elements"] if e["type"] == "ZeroLength"]
    # One link at M1's start: translations and torsion (about X) fixed, Y and Z rotations free.
    assert [(e["name"], e["dofs"]) for e in links] == [("M1/pin", [1, 2, 3, 4])]
    assert any("end releases: 1 member end(s)" in n for n in derivation.notes)

    support = node_at(project, (0, 0, 0))
    reaction = result.node_reaction[support][-1]
    assert reaction[2] == pytest.approx(P / 2, rel=1e-3)
    assert abs(reaction[4]) < 1e-3 * P * L  # no fixed-end moment about Y
    deflection = -result.node_disp[mid][-1][2]
    assert deflection == pytest.approx(P * L**3 / (48 * E_C * I_BM), rel=1e-3)


def test_without_the_release_it_is_a_propped_cantilever(tmp_path):
    """The same beam without the release: R_A = 11P/16 and M_A = 3PL/16 (the reference the
    release test differs from)."""
    model = _beam(
        {"id": "S1", "at": point(0, 0, 0), "fixity": "fixed"},
        {"id": "S2", "at": point(6000, 0, 0), "fixity": "pinned"},
    )
    _, project, result, _ = _run(model, tmp_path)
    reaction = result.node_reaction[node_at(project, (0, 0, 0))][-1]
    assert reaction[2] == pytest.approx(11 * P / 16, rel=1e-3)
    assert abs(reaction[4]) == pytest.approx(3 * P * L / 16, rel=1e-3)


def test_cantilever_on_a_point_spring(tmp_path):
    """Fixed at x = 0, a vertical spring k at x = L. With the load P at a = L/2, the free
    cantilever's tip would sag δ_P = P a² (3L − a) / (6EI); the spring force R makes the tip
    sag R/k = δ_P − R L³/(3EI), so R = δ_P / (L³/(3EI) + 1/k)."""
    k = 5000.0  # kN/m
    model = _with(
        _beam({"id": "S1", "at": point(0, 0, 0), "fixity": "fixed"}),
        pointSprings=[PointSpring(id="PS1", at=[6000, 0, 0], UZ=k)],
    )
    derivation, project, result, _ = _run(model, tmp_path)
    ei = E_C * I_BM
    a = L / 2
    delta_p = P * a**2 * (3 * L - a) / (6 * ei)
    spring = k * 1e3  # N/m
    r = delta_p / (L**3 / (3 * ei) + 1 / spring)

    (link,) = [e for e in project["elements"] if e["type"] == "ZeroLength"]
    assert link["name"] == "PS1/spring" and link["dofs"] == [3]
    joint, ground = link["nodes"]
    assert -result.node_disp[joint][-1][2] == pytest.approx(r / spring, rel=1e-3)
    assert result.node_reaction[ground][-1][2] == pytest.approx(r, rel=1e-3)
    fixed = result.node_reaction[node_at(project, (0, 0, 0))][-1]
    assert fixed[2] == pytest.approx(P - r, rel=1e-3)
    assert any("point springs: 1 joint(s)" in n for n in derivation.notes)


def test_point_spring_with_a_support():
    """A point spring's support holds its directions; a spring in a held direction is left
    out."""
    model = _with(
        _beam({"id": "S1", "at": point(0, 0, 0), "fixity": "fixed"}),
        pointSprings=[PointSpring(id="PS1", at=[6000, 0, 0], UZ=100, RY=50, support="pinned")],
    )
    project = derive(model, objects(BEAM), MATERIALS, settings()).project
    end = next(n for n in project["nodes"] if n["id"] == node_at(project, (L, 0, 0)))
    assert end["restraint"] == [True, True, True, False, False, False]
    (link,) = [e for e in project["elements"] if e["type"] == "ZeroLength"]
    assert link["dofs"] == [5]  # about Y only: Z is supported


def test_partial_fixity_is_a_spring_in_the_link():
    model = _with(
        _beam(
            {"id": "S1", "at": point(0, 0, 0), "fixity": "fixed"},
            {"id": "S2", "at": point(6000, 0, 0), "fixity": "pinned"},
        ),
        endReleases=[EndRelease(id="ER1", member="M1", start={"M3": 2000})],
    )
    project = derive(model, objects(BEAM), MATERIALS, settings()).project
    (link,) = [e for e in project["elements"] if e["type"] == "ZeroLength"]
    assert link["dofs"] == [1, 2, 3, 4, 5, 6]
    materials = {m["id"]: m for m in project["materials"]}
    # M3 of a beam along X is about global Y (its member axis 3 is horizontal).
    assert materials[link["material_ids"][4]]["E"] == pytest.approx(2000e3)


def test_member_released_both_ends_is_a_mechanism():
    model = _with(
        _beam({"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}),
        endReleases=[EndRelease(id="ER1", member="M1", start={"T": 0}, end={"T": 0})],
    )
    assert any("T is released at both ends of M1" in p for p in model.check_additions())
    with pytest.raises(MechanismError, match="spin about its axis"):
        derive(model, objects(BEAM), MATERIALS, settings())


def test_joint_every_end_releases_is_a_mechanism():
    """Both members release their axial force at the mid-span joint: nothing holds it in X."""
    model = _with(
        _beam({"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}),
        endReleases=[
            EndRelease(id="ER1", member="M1", end={"P": 0}),
            EndRelease(id="ER2", member="M2", start={"P": 0}),
        ],
    )
    with pytest.raises(MechanismError, match=r"\(3000, 0, 0\) mm is free to move in X"):
        derive(model, objects(BEAM), MATERIALS, settings())


def test_hinge_where_both_ends_release_the_moment():
    """Both members release M3 at the mid-span joint (a hinge): the joint's own rotation about
    Y is held (nothing passes it) and the model derives."""
    model = _with(
        _beam({"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}),
        endReleases=[
            EndRelease(id="ER1", member="M1", end={"M3": 0}),
            EndRelease(id="ER2", member="M2", start={"M3": 0}),
        ],
    )
    derivation = derive(model, objects(BEAM), MATERIALS, settings())
    mid = next(n for n in derivation.project["nodes"] if n["coords"] == [3.0, 0.0, 0.0])
    assert mid["restraint"] == [False, False, False, False, True, False]
    assert any("held in that rotation" in n for n in derivation.notes)


def test_old_building_models_load_unchanged():
    old = _beam({"id": "S1", "at": point(0, 0, 0)}).model_dump(mode="json", by_alias=True)
    for key in ("endReleases", "pointSprings"):
        old["additions"].pop(key)
    model = BuildingModel.model_validate(old)
    assert model.additions.endReleases == [] and model.additions.pointSprings == []


def test_release_of_an_unknown_member_is_reported():
    model = _with(
        _beam({"id": "S1", "at": point(0, 0, 0)}),
        endReleases=[EndRelease(id="ER1", member="B9", start={"M3": 0})],
    )
    assert "ER1: there is no beam, column or member 'B9'" in model.check_additions()

"""The temperature load case T (saengine.fem.thermal): equivalent fixed-end actions, run through
OpenSees Studio's runner, against hand calculations.

Synthetic members: concrete E = 25 GPa, α = 10e-6 /°C; a 300 × 500 beam and 400 × 400 columns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from saengine.fem.derive import UNITS
from saengine.fem.display import _elements, element_section_forces
from saengine.fem.thermal import (
    CASE,
    DEFAULT_ALPHA,
    ThermalOptions,
    ThermalSection,
    add_thermal_case,
    default_alpha,
    end_force_corrections,
    frame_fixed_end_forces,
    load_corrections,
    plate_thermal_resultants,
    service_combinations_with_t,
    shell_equivalent_loads,
    shell_force_corrections,
    strength_combinations_with_t,
    thermal_sections,
    write_corrections,
)
from saengine.library import default_material_library
from saengine.library.objects import ObjectLibrary
from saengine.verification.cases.common import run_model

E, ALPHA = 25e9, 10e-6  # Pa, 1/°C
B, H = 0.3, 0.5  # beam, m
A_B, I_B = B * H, B * H**3 / 12
A_C, I_C = 0.16, 0.4**4 / 12  # column 400 × 400


def _project(
    nodes: dict[int, tuple[float, float, float]],
    fixed: dict[int, list[bool]],
    sections: list[dict[str, Any]],
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "meta": {"name": "thermal", "description": "", "author": "", "units": UNITS},
        "ndm": 3,
        "ndf": 6,
        "nodes": [
            {
                "id": n,
                "name": "",
                "coords": list(xyz),
                "mass": [0.0] * 6,
                "restraint": fixed.get(n, [False] * 6),
            }
            for n, xyz in nodes.items()
        ],
        "materials": [],
        "sections": sections,
        "elements": elements,
        "mp_constraints": [],
        "time_series": [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}],
        "load_patterns": [],
        "analyses": [],
        "spectra": [],
        "ground_motions": [],
    }


def _frame_section(sid: int, a: float, i: float) -> dict[str, Any]:
    return {
        "id": sid,
        "name": f"S{sid}",
        "type": "ElasticSection",
        "E": E,
        "A": a,
        "Iz": i,
        "Iy": i,
        "G": E / 2.4,
        "J": 2 * i,
    }


def _frame(eid: int, i: int, j: int, sid: int, name: str = "") -> dict[str, Any]:
    return {
        "id": eid,
        "name": name or f"E{eid}",
        "type": "ElasticBeamColumn",
        "nodes": [i, j],
        "section_id": sid,
        "geom_transf": "Linear",
        "rho": 0.0,
        "consistent_mass": False,
    }


FIXED = [True] * 6


def _run(project: dict[str, Any], case: Any, folder: Path) -> tuple[Any, dict[int, np.ndarray]]:
    """The case's results and each frame's true section forces (analysis + fixed-end)."""
    _, _, results = run_model(project, folder, [case.analysis_id])
    result = results[case.analysis_id]
    fixed_end = end_force_corrections(case.corrections, CASE)
    forces = {}
    for e in _elements(project):
        end = np.asarray(result.element_forces[e.id][-1], dtype=float)[:12]
        forces[e.id] = element_section_forces(e, end + fixed_end.get(e.id, 0.0), np.zeros(3))
    return result, forces


# ───────────────────────────────── formulas ─────────────────────────────────


def test_frame_fixed_end_forces() -> None:
    # Iy != Iz, so a mix-up of the two inertias shows.
    iy, iz = I_B, 0.36 * I_B
    f = frame_fixed_end_forces(E, A_B, iy, iz, ALPHA, 20.0, gradient_z=10.0, depth_z=H)
    n0, m0 = E * A_B * ALPHA * 20, E * iy * ALPHA * 10 / H
    assert f[[0, 6]] == pytest.approx([n0, -n0])  # the held member pushes on its nodes
    assert f[[4, 10]] == pytest.approx([m0, -m0])
    assert np.count_nonzero(f) == 4
    # A gradient along local y bends about local z the other way round (Mz = -∫σy).
    g = frame_fixed_end_forces(E, A_B, iy, iz, ALPHA, 0.0, gradient_y=10.0, depth_y=B)
    assert g[[5, 11]] == pytest.approx([-E * iz * ALPHA * 10 / B, E * iz * ALPHA * 10 / B])


def test_plate_thermal_resultants() -> None:
    e, nu, t = 30e9, 0.2, 0.2
    n_t, m_t = plate_thermal_resultants(e, nu, t, ALPHA, 20.0, 10.0)
    assert n_t == pytest.approx(30e9 * 0.2 * 1e-5 * 20 / 0.8)  # 1.5 MN/m
    # MT = D (1 + ν) κT with D = E t³ / 12 (1 - ν²), κT = α ΔTg / t.
    d = e * t**3 / (12 * (1 - nu**2))
    assert m_t == pytest.approx(d * (1 + nu) * ALPHA * 10 / t)


def test_shell_equivalent_loads_balance() -> None:
    corners = [np.array(p, dtype=float) for p in [(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)]]
    loads = shell_equivalent_loads(corners, 1000.0, 50.0, np.array([0, 0, 1.0]))
    total = sum(loads, np.zeros(6))
    assert total == pytest.approx(np.zeros(6), abs=1e-9)  # self-equilibrating
    # Corner (0, 0): half of the two edges meeting there, pushed outward.
    assert loads[0][:3] == pytest.approx([-1000 * 1 / 2, -1000 * 2 / 2, 0])
    # Moments bend the edges down (top hotter): about +x on the edge y = 0 (rotation x̂ × -ŷ).
    assert loads[0][3:] == pytest.approx([50 * 2 / 2, -50 * 1 / 2, 0])


def test_default_alpha_and_sections() -> None:
    materials = default_material_library()
    mats = {m.id: m for m in materials.materials}
    concrete = next(m for m in materials.materials if m.category.value == "concrete")
    assert default_alpha(concrete) == pytest.approx(concrete.mechanical.alpha or 10e-6)
    bare = concrete.model_copy(
        update={"mechanical": concrete.mechanical.model_copy(update={"alpha": None})}
    )
    assert default_alpha(bare) == DEFAULT_ALPHA["concrete"]
    types = {
        o.id: o
        for o in ObjectLibrary.model_validate(
            {
                "objects": [
                    {
                        "id": "BM",
                        "name": "Beam",
                        "kind": "beam",
                        "material": concrete.id,
                        "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
                    },
                    {
                        "id": "SL",
                        "name": "Slab",
                        "kind": "slab",
                        "material": concrete.id,
                        "thickness": 150,
                    },
                ]
            }
        ).objects
    }
    sections = thermal_sections(
        {1: ("BM", 0, False), 2: ("BM", 1, False), 3: ("BM", 0, True), 4: ("plate", "SL")},
        types,
        mats,
    )
    assert sections[1].depth == pytest.approx(0.5)
    assert sections[2].depth == pytest.approx(0.3)  # turned on its side
    assert sections[3].depth is None  # vertical: no gradient
    assert sections[4].depth is None and sections[4].alpha == default_alpha(concrete)


def test_combinations_with_t() -> None:
    """BNBC 2020 Part 6 2.7.3.1 (2) and 2.7.2.1 (2), (4), for a rise and a fall."""
    assert strength_combinations_with_t() == [
        ("1.2D + 1.2T + 1.6L + 0.5Lr", {"D": 1.2, "T": 1.2, "L": 1.6, "Lr": 0.5}),
        ("1.2D - 1.2T + 1.6L + 0.5Lr", {"D": 1.2, "T": -1.2, "L": 1.6, "Lr": 0.5}),
    ]
    service = dict(service_combinations_with_t({"D", "SD", "L", "Lr", "T", "WX"}))
    assert service == {
        "D + L + T": {"D": 1.0, "SD": 1.0, "L": 1.0, "T": 1.0},
        "D + 0.75(L + T) + Lr": {"D": 1.0, "SD": 1.0, "L": 0.75, "Lr": 1.0, "T": 0.75},
        "D + L - T": {"D": 1.0, "SD": 1.0, "L": 1.0, "T": -1.0},
        "D + 0.75(L - T) + Lr": {"D": 1.0, "SD": 1.0, "L": 0.75, "Lr": 1.0, "T": -0.75},
    }
    assert service_combinations_with_t({"D", "L"}) == []  # no temperature case
    assert [n for n, _ in service_combinations_with_t({"D", "T"})] == [
        "D + T",
        "D + 0.75T",
        "D - T",
        "D + 0.75(-T)",
    ]


def test_corrections_round_trip(tmp_path: Path) -> None:
    model = tmp_path / "model.osmodel"
    data = {"schema": 1, "case": "T", "frames": {"3": [1.0] * 12}, "shells": {"7": [2.0] * 8}}
    write_corrections(model, data)
    loaded = load_corrections(model)
    assert end_force_corrections(loaded, "T")[3] == pytest.approx([1.0] * 12)
    assert shell_force_corrections(loaded, "T")[7] == pytest.approx([2.0] * 8)
    assert end_force_corrections(loaded, "D") == {}  # only the temperature case
    write_corrections(model, None)
    assert load_corrections(model) is None


# ───────────────────────────────── frames ─────────────────────────────────


def test_fixed_beam_heated_uniformly(tmp_path: Path) -> None:
    """Both ends fixed, ΔTu = +20 °C: no deflection, N = -E A α ΔT, reactions push inward."""
    length = 6.0
    project = _project(
        {1: (0, 0, 0), 2: (3, 0, 0), 3: (length, 0, 0)},
        {1: FIXED, 3: FIXED},
        [_frame_section(1, A_B, I_B)],
        [_frame(1, 1, 2, 1), _frame(2, 2, 3, 1)],
    )
    case = add_thermal_case(project, {1: ThermalSection(ALPHA, H)}, ThermalOptions(uniform=20))
    result, forces = _run(project, case, tmp_path)
    n0 = E * A_B * ALPHA * 20
    assert np.asarray(result.node_disp[2][-1]) == pytest.approx(np.zeros(6), abs=1e-12)
    for f in forces.values():
        assert f[:, 0] == pytest.approx(np.full(len(f), -n0))  # compression throughout
        assert f[:, 4] == pytest.approx(np.zeros(len(f)), abs=1e-6)
    # The reactions include the loads applied at the supports: the true support forces.
    assert result.node_reaction[1][-1][0] == pytest.approx(n0)
    assert result.node_reaction[3][-1][0] == pytest.approx(-n0)


def test_face_forces_include_the_fixed_end_forces(tmp_path: Path) -> None:
    """The face forces file (saengine.fem.end_zones) of the temperature case carries the
    fixed-end forces, as the design's stations do: a fixed beam heated uniformly is in
    compression N = -E A α ΔT at its faces too (the raw localForce alone is zero)."""
    from saengine.fem.end_zones import FACES_FILE, face_forces

    length = 6.0
    project = _project(
        {1: (0, 0, 0), 2: (length / 2, 0, 0), 3: (length, 0, 0)},
        {1: FIXED, 3: FIXED},
        [_frame_section(1, A_B, I_B)],
        [_frame(1, 1, 2, 1), _frame(2, 2, 3, 1)],
    )
    case = add_thermal_case(project, {1: ThermalSection(ALPHA, H)}, ThermalOptions(uniform=20))
    model, out, _ = run_model(project, tmp_path, [case.analysis_id])
    write_corrections(model, case.corrections)
    faces = {
        "schema": "saengine.faces/1",
        "rigidZoneFactor": 0.0,
        "elements": {"1": {"i": {"offset": 200.0, "rigid": 0.0, "at": [1, 0.2]}}},
    }
    (model.parent / FACES_FILE).write_text(json.dumps(faces), encoding="utf-8")
    face = face_forces(model, out)["cases"][CASE]["1"]["i"]
    assert face["N"] == pytest.approx(-E * A_B * ALPHA * 20, rel=1e-6)
    assert face["Mz"] == pytest.approx(0.0, abs=1e-3)


def test_free_beam_expands_without_force(tmp_path: Path) -> None:
    """A cantilever is free to expand and curl: u = α ΔTu L, w = -κ L² / 2, no forces."""
    length = 4.0
    project = _project(
        {1: (0, 0, 0), 2: (2, 0, 0), 3: (length, 0, 0)},
        {1: FIXED},
        [_frame_section(1, A_B, I_B)],
        [_frame(1, 1, 2, 1), _frame(2, 2, 3, 1)],
    )
    options = ThermalOptions(uniform=20, gradient=10)
    case = add_thermal_case(project, {1: ThermalSection(ALPHA, H)}, options)
    result, forces = _run(project, case, tmp_path)
    kappa = ALPHA * 10 / H
    tip = np.asarray(result.node_disp[3][-1])
    assert tip[0] == pytest.approx(ALPHA * 20 * length)
    assert tip[2] == pytest.approx(-kappa * length**2 / 2)  # top hotter: the tip curls down
    for f in forces.values():
        assert f == pytest.approx(np.zeros_like(f), abs=1e-4)


def test_propped_beam_with_gradient(tmp_path: Path) -> None:
    """Fixed at x = 0, propped at x = L, top 10 °C hotter: the prop holds the curling tip with
    R = 3 E I κ / (2 L), so M(0) = -3 E I κ / 2 (top in compression), M(L) = 0."""
    length = 6.0
    pin = [True, True, True, True, False, False]  # held in translation and twist
    project = _project(
        {1: (0, 0, 0), 2: (3, 0, 0), 3: (length, 0, 0)},
        {1: FIXED, 3: pin},
        [_frame_section(1, A_B, I_B)],
        [_frame(1, 1, 2, 1), _frame(2, 2, 3, 1)],
    )
    case = add_thermal_case(project, {1: ThermalSection(ALPHA, H)}, ThermalOptions(gradient=10))
    result, forces = _run(project, case, tmp_path)
    ei_kappa = E * I_B * ALPHA * 10 / H
    assert forces[1][0, 4] == pytest.approx(-1.5 * ei_kappa)
    assert forces[1][-1, 4] == pytest.approx(-0.75 * ei_kappa)  # linear to zero at the prop
    assert forces[2][-1, 4] == pytest.approx(0.0, abs=1e-6 * ei_kappa)
    assert result.node_reaction[3][-1][2] == pytest.approx(1.5 * ei_kappa / length)  # pushes up


def _portal_reference(
    span: float, height: float, delta_t: float
) -> tuple[float, float, float, float]:
    """Slope-deflection of the symmetric fixed-base portal whose beam expands (beam axially
    flexible, columns without axial force by symmetry): (sway of each column top, column shear
    = beam compression, moment at the column top, moment at the base)."""
    kc, kb = E * I_C / height, E * I_B / span
    # Joint rotation θ per chord rotation ψ = Δ/H: 2kc(2θ - 3ψ) + 2kb θ = 0.
    theta_per_psi = 3 * kc / (2 * kc + kb)
    shear_per_sway = 6 * kc / height**2 * (2 - theta_per_psi)  # V = 6kc/H (2ψ - θ)
    # Compatibility: the beam lengthens by α ΔT L less its shortening under V.
    sway = ALPHA * delta_t * span / (2 + shear_per_sway * span / (E * A_B))
    psi = sway / height
    theta = theta_per_psi * psi
    return (
        sway,
        shear_per_sway * sway,
        2 * kc * abs(2 * theta - 3 * psi),
        2 * kc * abs(theta - 3 * psi),
    )


def _stiffness_2d(span: float, height: float, delta_t: float) -> np.ndarray:
    """Independent 2D direct-stiffness solution (x, z, rotation) of the same portal: the
    displacements of the two column tops."""

    def element(xa: np.ndarray, xb: np.ndarray, a: float, i: float) -> tuple[np.ndarray, Any]:
        d = xb - xa
        length = float(np.hypot(*d))
        c, s = d / length
        ea, ei = E * a / length, E * i
        k = np.zeros((6, 6))
        k[np.ix_([0, 3], [0, 3])] = ea * np.array([[1, -1], [-1, 1]])
        k[np.ix_([1, 2, 4, 5], [1, 2, 4, 5])] = (ei / length**3) * np.array(
            [
                [12, 6 * length, -12, 6 * length],
                [6 * length, 4 * length**2, -6 * length, 2 * length**2],
                [-12, -6 * length, 12, -6 * length],
                [6 * length, 2 * length**2, -6 * length, 4 * length**2],
            ]
        )
        t = np.zeros((6, 6))
        t[:2, :2] = t[3:5, 3:5] = [[c, s], [-s, c]]
        t[2, 2] = t[5, 5] = 1
        return t.T @ k @ t, t

    xy = [np.array(p, dtype=float) for p in [(0, 0), (0, height), (span, height), (span, 0)]]
    members = [(0, 1, A_C, I_C, 0.0), (1, 2, A_B, I_B, delta_t), (3, 2, A_C, I_C, 0.0)]
    k_global, load = np.zeros((12, 12)), np.zeros(12)
    for a, b, area, inertia, dt in members:
        k, t = element(xy[a], xy[b], area, inertia)
        dofs = [3 * a, 3 * a + 1, 3 * a + 2, 3 * b, 3 * b + 1, 3 * b + 2]
        k_global[np.ix_(dofs, dofs)] += k
        n0 = E * area * ALPHA * dt
        load[dofs] -= t.T @ np.array([n0, 0, 0, -n0, 0, 0])  # -f0
    free = [3, 4, 5, 6, 7, 8]
    u = np.zeros(12)
    u[free] = np.linalg.solve(k_global[np.ix_(free, free)], load[free])
    return u[3:9]


def test_portal_frame_beam_expansion(tmp_path: Path) -> None:
    """Fixed-base portal (6 m × 3.5 m) whose roof beam warms by 20 °C: the columns bend."""
    span, height, delta_t = 6.0, 3.5, 20.0
    project = _project(
        {1: (0, 0, 0), 2: (0, 0, height), 3: (span, 0, height), 4: (span, 0, 0)},
        {1: FIXED, 4: FIXED},
        [_frame_section(1, A_B, I_B), _frame_section(2, A_C, I_C)],
        [_frame(1, 1, 2, 2, "C1"), _frame(2, 2, 3, 1, "B1"), _frame(3, 4, 3, 2, "C2")],
    )
    sections = {1: ThermalSection(ALPHA, H), 2: ThermalSection(ALPHA)}
    case = add_thermal_case(project, sections, ThermalOptions(uniform=delta_t, scope="roof"))
    assert set(case.corrections["frames"]) == {"2"}  # only the roof beam is heated
    result, forces = _run(project, case, tmp_path)
    sway, shear, top, base = _portal_reference(span, height, delta_t)

    left, right = np.asarray(result.node_disp[2][-1]), np.asarray(result.node_disp[3][-1])
    assert left[0] == pytest.approx(-sway, rel=1e-6)
    assert right[0] == pytest.approx(sway, rel=1e-6)
    independent = _stiffness_2d(span, height, delta_t)
    assert [left[0], left[2], right[0], right[2]] == pytest.approx(
        independent[[0, 1, 3, 4]], rel=1e-6, abs=1e-12
    )
    # 2D rotation (x toward z) is the 3D rotation about -Y.
    assert left[4] == pytest.approx(-independent[2], rel=1e-6)
    assert forces[2][:, 0] == pytest.approx(np.full(len(forces[2]), -shear), rel=1e-6)
    assert abs(forces[1][0, 4]) == pytest.approx(base, rel=1e-6)
    assert abs(forces[1][-1, 4]) == pytest.approx(top, rel=1e-6)
    assert result.node_reaction[1][-1][0] == pytest.approx(shear, rel=1e-6)  # pulls inward


def test_roof_scope_and_gradient_only_on_roof(tmp_path: Path) -> None:
    """Scope 'roof': a lower beam is left alone; the gradient only bends roof members."""
    project = _project(
        {1: (0, 0, 0), 2: (4, 0, 0), 3: (0, 0, 3), 4: (4, 0, 3)},
        {n: FIXED for n in (1, 2, 3, 4)},
        [_frame_section(1, A_B, I_B)],
        [_frame(1, 1, 2, 1), _frame(2, 3, 4, 1)],
    )
    case = add_thermal_case(
        project, {1: ThermalSection(ALPHA, H)}, ThermalOptions(uniform=20, gradient=10)
    )
    assert set(case.corrections["frames"]) == {"2"}
    case_all = add_thermal_case(
        project, {1: ThermalSection(ALPHA, H)}, ThermalOptions(uniform=20, gradient=10, scope="all")
    )
    lower = case_all.corrections["frames"]["1"]
    assert lower[0] == pytest.approx(E * A_B * ALPHA * 20) and lower[4] == 0.0
    # The case is filled once: one pattern T and one analysis.
    assert [p["name"] for p in project["load_patterns"]] == ["T"]
    assert [a["name"] for a in project["analyses"]] == ["T: Temperature"]


def _nodal_loads(project: dict[str, Any]) -> dict[int, list[float]]:
    (pattern,) = (p for p in project["load_patterns"] if p["name"] == CASE)
    return {load["node_id"]: load["forces"] for load in pattern["nodal_loads"]}


def test_refilling_the_case_replaces_its_loads(tmp_path: Path) -> None:
    """A second call (or a T pattern already there) gives the same loads as the first, so the
    loads always match the fixed-end forces added back."""
    project = _project(
        {1: (0, 0, 0), 2: (4, 0, 0), 3: (0, 0, 3), 4: (4, 0, 3), 5: (2, 0, 0), 6: (2, 0, 3)},
        {n: FIXED for n in (1, 2, 3, 4)},
        [_frame_section(1, A_B, I_B)],
        [_frame(1, 1, 5, 1), _frame(2, 5, 2, 1), _frame(3, 3, 6, 1), _frame(4, 6, 4, 1)],
    )
    sections, options = {1: ThermalSection(ALPHA, H)}, ThermalOptions(uniform=20, gradient=10)
    first = add_thermal_case(project, sections, options)
    loads = _nodal_loads(project)
    n0 = E * A_B * ALPHA * 20
    assert loads[3][0] == pytest.approx(-n0) and loads[4][0] == pytest.approx(n0)
    second = add_thermal_case(project, sections, options)
    assert _nodal_loads(project) == loads
    assert second.corrections == first.corrections
    assert (second.pattern_id, second.analysis_id) == (first.pattern_id, first.analysis_id)
    # Other options replace the loads in full (the lower beam heated too, a fall of 10 °C).
    add_thermal_case(project, sections, ThermalOptions(uniform=-10, scope="all"))
    assert _nodal_loads(project)[1][0] == pytest.approx(n0 / 2)
    assert _nodal_loads(project)[3][0] == pytest.approx(n0 / 2)
    # Run: the held beam carries exactly the fixed-end force, whatever was filled before.
    case = add_thermal_case(project, sections, options)
    _, forces = _run(project, case, tmp_path)
    for upper in (3, 4):
        assert forces[upper][:, 0] == pytest.approx(np.full(len(forces[upper]), -n0))
    for lower in (1, 2):
        assert forces[lower] == pytest.approx(np.zeros_like(forces[lower]), abs=1e-6)


@pytest.mark.parametrize("along", ["x", "y"])
def test_gradient_bends_about_the_strong_axis(tmp_path: Path, along: str) -> None:
    """A 300 × 500 beam (Iy = b h³/12 about its strong axis, Iz = h b³/12 = 0.36 Iy): the
    propped beam's end moment is -1.5 E Iy κ, κ = α ΔTg / h (Iz would give 0.36 of it).
    Beams along global X and Y (both have local z up)."""
    length, iy, iz = 6.0, B * H**3 / 12, H * B**3 / 12
    section = {**_frame_section(1, A_B, iy), "Iz": iz}
    end = (length, 0.0, 0.0) if along == "x" else (0.0, length, 0.0)
    mid = (end[0] / 2, end[1] / 2, 0.0)
    # The prop holds the translations and the twist, and frees the bending rotation.
    twist = [True, False] if along == "x" else [False, True]
    pin = [True, True, True, *twist, False]
    project = _project(
        {1: (0, 0, 0), 2: mid, 3: end},
        {1: FIXED, 3: pin},
        [section],
        [_frame(1, 1, 2, 1), _frame(2, 2, 3, 1)],
    )
    case = add_thermal_case(project, {1: ThermalSection(ALPHA, H)}, ThermalOptions(gradient=10))
    ei_kappa = E * iy * ALPHA * 10 / H
    fixed_end = case.corrections["frames"]["1"]
    assert fixed_end[4] == pytest.approx(ei_kappa) and fixed_end[5] == 0.0
    result, forces = _run(project, case, tmp_path)
    assert forces[1][0, 4] == pytest.approx(-1.5 * ei_kappa)
    assert forces[2][-1, 4] == pytest.approx(0.0, abs=1e-6 * ei_kappa)
    assert np.abs(forces[1][:, 5]).max() == pytest.approx(0.0, abs=1e-6 * ei_kappa)
    assert result.node_reaction[3][-1][2] == pytest.approx(1.5 * ei_kappa / length)


def test_missing_alpha_note_and_no_release_without_diaphragms() -> None:
    project = _project(
        {1: (0, 0, 3), 2: (4, 0, 3), 3: (8, 0, 3)},
        {},
        [_frame_section(1, A_B, I_B), _frame_section(2, A_B, I_B)],
        [_frame(1, 1, 2, 1, "B1"), _frame(2, 2, 3, 2, "B2")],
    )
    case = add_thermal_case(project, {1: ThermalSection(ALPHA, H)}, ThermalOptions(uniform=20))
    assert set(case.corrections["frames"]) == {"1"}
    assert any("B2" in note for note in case.notes)  # no α for its section
    assert "release_diaphragms" not in project["analyses"][-1]  # no diaphragm to release


@pytest.fixture(scope="module")
def derived() -> dict[str, Any]:
    """The one-bay, one-storey frame of tests/test_fem_derive.py as derive builds it: four
    400 × 400 columns, four 300 × 500 beams, and the default rigid floor diaphragm."""
    from saengine.fem.derive import derive_fem
    from saengine.library.bim import generate
    from saengine.library.settings import default_project_settings
    from tests.test_fem_derive import OBJECTS, PLAN

    settings = default_project_settings("Frame")
    settings.analysis.responseSpectrum = False
    assert settings.analysis.diaphragm == "rigid"
    project = derive_fem(
        generate(PLAN, "s"), OBJECTS, default_material_library(), settings, {"bim": "x"}
    ).project
    assert any(c["type"] == "RigidDiaphragm" for c in project["mp_constraints"])
    return project


def _derived_sections(project: dict[str, Any]) -> dict[int, ThermalSection]:
    from tests.test_fem_derive import OBJECTS

    keys = {"COL column": ("COL", 0, True), "BM beam": ("BM", 0, False)}
    section_keys = {s["id"]: keys[s["name"]] for s in project["sections"]}
    mats = {m.id: m for m in default_material_library().materials}
    return thermal_sections(section_keys, {o.id: o for o in OBJECTS.objects}, mats)


def test_derived_beam_depth_goes_with_iy(derived: dict[str, Any]) -> None:
    """derive's horizontal beam has its strong-axis inertia in Iy (local z up), and
    thermal_sections' depth is along that same axis: Iy = b h³ / 12 with h = the depth."""
    sections = _derived_sections(derived)
    beam = next(s for s in derived["sections"] if s["name"] == "BM beam")
    depth = sections[beam["id"]].depth
    assert depth == pytest.approx(0.5)
    assert beam["Iy"] == pytest.approx(0.3 * depth**3 / 12)
    assert beam["Iz"] == pytest.approx(depth * 0.3**3 / 12)


def test_rigid_diaphragm_released_for_the_case(tmp_path: Path, derived: dict[str, Any]) -> None:
    """With derive's default rigid diaphragm the case runs without it: the heated roof beams
    expand (their force far below the held E A α ΔTu) and bend the columns, exactly as the
    same model without the diaphragm."""
    project = json.loads(json.dumps(derived))
    sections = _derived_sections(project)
    case = add_thermal_case(project, sections, ThermalOptions(uniform=20))
    assert any("without the rigid floor diaphragms" in note for note in case.notes)
    analysis = next(a for a in project["analyses"] if a["id"] == case.analysis_id)
    assert analysis["release_diaphragms"] is True
    result, forces = _run(project, case, tmp_path / "released")

    bare = json.loads(json.dumps(project))
    bare["mp_constraints"] = []
    used = {n for e in bare["elements"] for n in e["nodes"]}
    bare["nodes"] = [n for n in bare["nodes"] if n["id"] in used]
    # The loads lumped at the diaphragms' own nodes (story masses, static earthquake) go too.
    for p in bare["load_patterns"]:
        p["nodal_loads"] = [load for load in p["nodal_loads"] if load["node_id"] in used]
    for a in bare["analyses"]:
        a.pop("release_diaphragms", None)
    bare_result, bare_forces = _run(bare, case, tmp_path / "bare")

    beam = next(s for s in project["sections"] if s["name"] == "BM beam")
    held = beam["E"] * beam["A"] * sections[beam["id"]].alpha * 20  # 750 kN for C24-type
    names = {e["id"]: e["name"] for e in project["elements"]}
    for eid, f in forces.items():
        np.testing.assert_allclose(f, bare_forces[eid], rtol=1e-6, atol=1e-3)
        if names[eid].startswith("B"):
            assert 0 < -f[0, 0] < 0.1 * held  # compressed by the columns only, not held
        else:
            assert np.abs(f[:, 4:6]).max() > 1e3  # the columns bend [N·m]
    for node in used:
        np.testing.assert_allclose(
            result.node_disp[node][-1], bare_result.node_disp[node][-1], atol=1e-12
        )
    # Self-equilibrating: the base reactions sum to zero.
    base = [n["id"] for n in project["nodes"] if all(n["restraint"])]
    total = sum(np.asarray(result.node_reaction[n][-1][:3], dtype=float) for n in base)
    assert total == pytest.approx(np.zeros(3), abs=1e-3)


# ───────────────────────────────── shells ─────────────────────────────────


def _plate(n: int, size: float, fixed_all: bool, flip: bool = False) -> dict[str, Any]:
    ids: dict[tuple[int, int], int] = {}
    nodes = {}
    for j in range(n + 1):
        for i in range(n + 1):
            ids[(i, j)] = len(ids) + 1
            nodes[ids[(i, j)]] = (i * size / n, j * size / n, 0.0)
    edge = {k for (i, j), k in ids.items() if min(i, j) == 0 or max(i, j) == n}
    fixed = {k: FIXED for k in edge} if fixed_all else {1: FIXED}
    elements = []
    for j in range(n):
        for i in range(n):
            quad = [ids[(i, j)], ids[(i + 1, j)], ids[(i + 1, j + 1)], ids[(i, j + 1)]]
            elements.append(
                {
                    "id": len(elements) + 1,
                    "name": "SL",
                    "type": "Shell",
                    "formulation": "ASDShellQ4",
                    "nodes": quad[::-1] if flip else quad,
                    "section_id": 1,
                }
            )
    section = {
        "id": 1,
        "name": "slab",
        "type": "ElasticMembranePlateSection",
        "E": 30e9,
        "nu": 0.2,
        "h": 0.2,
        "rho": 0.0,
    }
    return _project(nodes, fixed, [section], elements)


def _shell_forces(result: Any, case: Any, element_id: int) -> np.ndarray:
    rows = np.asarray(result.shell_forces[element_id][-1], dtype=float).reshape(-1, 8)
    return rows.mean(axis=0) + shell_force_corrections(case.corrections, CASE)[element_id]


def test_fully_restrained_plate(tmp_path: Path) -> None:
    """Every edge node held (the centre node free): no movement, N = -E t α ΔTu / (1 - ν),
    M = -E t² α ΔTg / 12 (1 - ν)."""
    project = _plate(2, 2.0, fixed_all=True)
    options = ThermalOptions(uniform=20, gradient=10)
    case = add_thermal_case(project, {1: ThermalSection(ALPHA)}, options)
    _, _, results = run_model(project, tmp_path, [case.analysis_id])
    result = results[case.analysis_id]
    assert np.asarray(result.node_disp[5][-1]) == pytest.approx(np.zeros(6), abs=1e-12)
    n_t, m_t = 30e9 * 0.2 * ALPHA * 20 / 0.8, 30e9 * 0.04 * ALPHA * 10 / (12 * 0.8)
    for e in project["elements"]:
        forces = _shell_forces(result, case, e["id"])
        assert forces == pytest.approx([-n_t, -n_t, 0, -m_t, -m_t, 0, 0, 0], abs=1e-3)
    # The supports take the held expansion: the corner reaction is the corner's edge forces.
    assert result.node_reaction[1][-1][0] == pytest.approx(n_t * 0.5)


@pytest.mark.parametrize("flip", [False, True])
def test_free_plate_expands_and_curls_without_force(tmp_path: Path, flip: bool) -> None:
    """Held at one corner only: u = α ΔTu x, w = -κ (x² + y²) / 2 with κ = α ΔTg / t, and no
    section forces, whichever way the shells' normals point."""
    size = 2.0
    project = _plate(4, size, fixed_all=False, flip=flip)
    options = ThermalOptions(uniform=20, gradient=10)
    case = add_thermal_case(project, {1: ThermalSection(ALPHA)}, options)
    _, _, results = run_model(project, tmp_path, [case.analysis_id])
    result = results[case.analysis_id]
    corner = np.asarray(result.node_disp[25][-1])
    kappa = ALPHA * 10 / 0.2
    assert corner[:3] == pytest.approx(
        [ALPHA * 20 * size, ALPHA * 20 * size, -kappa * (2 * size**2) / 2]
    )
    for e in project["elements"]:
        assert _shell_forces(result, case, e["id"]) == pytest.approx(np.zeros(8), abs=1e-3)

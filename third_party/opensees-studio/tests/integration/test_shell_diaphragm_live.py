"""Shell elements and rigid diaphragms in real OpenSeesPy runs.

- A cantilever plate meshed with shells against beam theory: tip deflection
  ``P L^3 / 3EI`` and the bending moment per unit width ``P (L - x) / b``.
- A one-storey frame with a rigid floor: equal in-plane movement of the tied nodes, the
  storey stiffness of four cantilever columns, and the period ``2 pi sqrt(m / k)``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

ops = pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    RigidDiaphragmConstraint,
    ShellElement,
    StaticCase,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402
from opensees_studio.services.result_store import load_results, write_results  # noqa: E402

FIXED = (True,) * 6
E, H = 30e9, 0.2  # Pa, m


def _run(project: Project, case_id: int = 1):  # type: ignore[no-untyped-def]
    case = next(c for c in project.analyses if c.id == case_id)
    return OpenSeesRunner(project).run(case)


def _plate(formulation: str, length: float = 4.0, width: float = 1.0, nx: int = 8) -> Project:
    """A plate along X clamped at x = 0, loaded by P = 1 kN spread over its free edge."""
    ny = 2
    nodes, elements = [], []

    def nid(i: int, j: int) -> int:
        return 1 + i * (ny + 1) + j

    for i in range(nx + 1):
        for j in range(ny + 1):
            nodes.append(
                Node(
                    id=nid(i, j),
                    coords=(length * i / nx, width * j / ny, 0.0),
                    restraint=FIXED if i == 0 else (False,) * 6,
                )
            )
    triangles = formulation in ("ASDShellT3", "ShellDKGT")
    for i in range(nx):
        for j in range(ny):
            a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
            if triangles:
                elements.append(
                    ShellElement(
                        id=len(elements) + 1, formulation=formulation, nodes=(a, b, c), section_id=1
                    )
                )
                elements.append(
                    ShellElement(
                        id=len(elements) + 1, formulation=formulation, nodes=(a, c, d), section_id=1
                    )
                )
            else:
                elements.append(
                    ShellElement(
                        id=len(elements) + 1,
                        formulation=formulation,
                        nodes=(a, b, c, d),
                        section_id=1,
                    )
                )
    # Edge load, lumped consistently (ends take half a share).
    shares = [0.25, 0.5, 0.25]
    loads = [
        NodalLoad(node_id=nid(nx, j), forces=(0, 0, -1000.0 * s, 0, 0, 0))
        for j, s in enumerate(shares)
    ]
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, E=E, nu=0.0, h=H)],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, nodal_loads=loads)],
        analyses=[StaticCase(id=1, pattern_ids=[1])],
    )


@pytest.mark.parametrize(
    "formulation", ["ASDShellQ4", "ShellMITC4", "ShellDKGQ", "ASDShellT3", "ShellDKGT"]
)
def test_cantilever_plate_matches_beam_theory(formulation: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = _plate(formulation)
    results = _run(project)
    inertia = 1.0 * H**3 / 12
    expected = 1000.0 * 4.0**3 / (3 * E * inertia)
    tip = [results.node_disp[n.id][-1, 2] for n in project.nodes if n.coords[0] == 4.0]
    reaction = sum(results.node_reaction[n.id][-1, 2] for n in project.nodes if n.coords[0] == 0.0)
    print(formulation, np.mean(tip), -expected)
    assert np.mean(tip) == pytest.approx(-expected, rel=0.03)
    assert reaction == pytest.approx(1000.0, rel=1e-9)

    # Section forces: one row of 8 values per integration point, kept by the result store.
    stored = load_results(write_results(results, tmp_path), tmp_path)
    assert set(stored.shell_forces) == {e.id for e in project.elements}
    if formulation in ("ASDShellQ4", "ShellMITC4", "ShellDKGQ"):
        first = stored.shell_forces[1][-1].reshape(-1, 8)
        # Element 1 spans x = 0 … 0.5: its mean M11 is the moment at x = 0.25.
        assert abs(first[:, 3].mean()) == pytest.approx(1000.0 * (4.0 - 0.25) / 1.0, rel=0.03)


def _storey(diaphragm: bool) -> Project:
    """Four 3 m columns on a 6 x 5 m plan, floor mass 10 t at the centre."""
    h, mass = 3.0, 10_000.0
    corners = [(0, 0), (6, 0), (6, 5), (0, 5)]
    nodes = [
        Node(id=i + 1, coords=(x, y, 0.0), restraint=FIXED) for i, (x, y) in enumerate(corners)
    ]
    nodes += [Node(id=i + 11, coords=(x, y, h)) for i, (x, y) in enumerate(corners)]
    nodes.append(
        Node(
            id=100,
            coords=(3.0, 2.5, h),
            restraint=(False, False, True, True, True, False),
            mass=(mass, mass, 0, 0, 0, mass * (6**2 + 5**2) / 12),
        )
    )
    elements = [ElasticBeamColumn(id=i + 1, nodes=(i + 1, i + 11), section_id=1) for i in range(4)]
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[
            ElasticSection(id=1, E=E, A=0.16, Iz=0.4**4 / 12, Iy=0.4**4 / 12, G=E / 2.4, J=0.0036)
        ],
        elements=elements,
        mp_constraints=[
            RigidDiaphragmConstraint(retained_node=100, constrained_nodes=[11, 12, 13, 14])
        ]
        if diaphragm
        else [],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=100, forces=(100_000.0, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[StaticCase(id=1, pattern_ids=[1]), ModalCase(id=2, n_modes=3)],
    )


def test_rigid_diaphragm_ties_the_floor_and_gives_the_storey_period() -> None:
    project = _storey(diaphragm=True)
    stiffness = 4 * 3 * E * (0.4**4 / 12) / 3.0**3  # cantilever columns, tops free to rotate
    static = _run(project, 1)
    ux = [static.node_disp[n][-1, 0] for n in (11, 12, 13, 14, 100)]
    assert ux == pytest.approx([100_000.0 / stiffness] * 5, rel=1e-6)
    base = sum(static.node_reaction[n][-1, 0] for n in (1, 2, 3, 4))
    assert base == pytest.approx(-100_000.0, rel=1e-9)

    modal = _run(project, 2)
    period = 2 * math.pi * math.sqrt(10_000.0 / stiffness)
    assert modal.periods[0] == pytest.approx(period, rel=1e-6)
    # The tied nodes move with the floor in the mode shape too.
    shape = modal.mode_shapes[1]
    assert abs(shape[11][0]) == pytest.approx(abs(shape[100][0]), rel=1e-6) or abs(
        shape[11][1]
    ) == pytest.approx(abs(shape[100][1]), rel=1e-6)

"""Second order from a preload ("P-Delta load combination"), per-case section overrides, the
plate bending factor ``Ep_mod`` and first-order staged cases in a P-Delta model."""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.core.analysis import ConstructionStage, StagedCase
from opensees_studio.services.opensees_runner import OpenSeesRunner

E, A, IZ, L, H = 2e8, 0.01, 1e-4, 3.0, 10.0
PCR = math.pi**2 * E * IZ / (4 * L**2)
P = 0.25 * PCR
PARTS = 8


def _column(transf: str = "PDelta", mass: float = 0.0) -> Project:
    """A cantilever of PARTS elements: pattern 1 the axial load P, pattern 2 the tip load H."""
    nodes = [
        Node(
            id=k + 1,
            coords=(0.0, 0.0, L * k / PARTS),
            restraint=(True,) * 6 if k == 0 else (False,) * 6,
            mass=(mass, mass, 0, 0, 0, 0) if k == PARTS else (0,) * 6,
        )
        for k in range(PARTS + 1)
    ]
    elements = [
        ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 2), section_id=1, geom_transf=transf)
        for k in range(PARTS)
    ]
    top = PARTS + 1
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=E, A=A, Iz=IZ, Iy=IZ, G=8e7, J=2e-4)],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=top, forces=(0, 0, -P, 0, 0, 0))],
            ),
            PlainLoadPattern(
                id=2,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=top, forces=(H, 0, 0, 0, 0, 0))],
            ),
        ],
        analyses=[
            StaticCase(id=1, name="preload", pattern_ids=[1], algorithm="Newton", max_iter=50),
            StaticCase(id=2, name="lateral", pattern_ids=[2], preload_case_ids=[1]),
            StaticCase(id=3, name="first order", pattern_ids=[2]),
        ],
    )


def _case(project: Project, cid: int):
    return next(c for c in project.analyses if c.id == cid)


def test_preloaded_case_reports_the_amplified_increment() -> None:
    project = _column()
    second = OpenSeesRunner(project).run(_case(project, 2))
    first = OpenSeesRunner(project).run(_case(project, 3))
    top = PARTS + 1
    delta1 = H * L**3 / (3 * E * IZ)
    assert first.disp(top, 1) == pytest.approx(delta1, rel=1e-9)
    assert second.disp(top, 1) == pytest.approx(delta1 / (1 - P / PCR), rel=0.03)
    # The preload's own shortening and reaction are subtracted.
    assert abs(second.disp(top, 3)) < 1e-6 * delta1
    reaction = np.asarray(second.node_reaction[1][-1])
    assert reaction[2] == pytest.approx(0.0, abs=1e-6 * P)
    assert reaction[0] == pytest.approx(-H, rel=1e-9)


def test_preload_round_trips_and_is_left_out_when_empty() -> None:
    project = _column()
    data = project.model_dump(mode="json")
    assert data["analyses"][1]["preload_case_ids"] == [1]
    assert "preload_case_ids" not in data["analyses"][0]
    assert "section_overrides" not in data["analyses"][0]
    assert Project.model_validate(data).analyses[1].preload_case_ids == [1]


def test_release_diaphragms_and_preload_do_not_mix() -> None:
    with pytest.raises(ValueError, match="release_diaphragms"):
        StaticCase(id=9, pattern_ids=[2], preload_case_ids=[1], release_diaphragms=True)


def test_modal_case_on_the_preloaded_stiffness() -> None:
    """The first period lengthens by about 1/sqrt(1 - P/Pcr) under the axial preload."""
    project = _column(mass=10.0)
    project.analyses += [
        ModalCase(id=4, name="plain", n_modes=1),
        ModalCase(id=5, name="preloaded", n_modes=1, preload_case_ids=[1]),
    ]
    plain = OpenSeesRunner(project).run(_case(project, 4)).eigenvalues[0]
    loaded = OpenSeesRunner(project).run(_case(project, 5)).eigenvalues[0]
    ratio = math.sqrt(plain / loaded)  # T_loaded / T_plain
    assert ratio == pytest.approx(1 / math.sqrt(1 - P / PCR), rel=0.03)


def test_section_overrides_apply_to_their_case_only() -> None:
    project = _column(transf="Linear")
    cracked = ElasticSection(id=1, E=E, A=A, Iz=0.7 * IZ, Iy=0.7 * IZ, G=8e7, J=2e-4)
    project.analyses.append(StaticCase(id=4, pattern_ids=[2], section_overrides=[cracked]))
    top = PARTS + 1
    gross = OpenSeesRunner(project).run(_case(project, 3)).disp(top, 1)
    reduced = OpenSeesRunner(project).run(_case(project, 4)).disp(top, 1)
    assert reduced == pytest.approx(gross / 0.7, rel=1e-9)
    assert project.sections[0].Iz == IZ
    bad = StaticCase(
        id=5,
        pattern_ids=[2],
        section_overrides=[cracked.model_copy(update={"id": 7})],
    )
    with pytest.raises(ValueError, match="replaces nothing"):
        OpenSeesRunner(project).run(bad)


def test_transient_case_takes_section_overrides(tmp_path) -> None:
    """A time history with cracked overrides (its preload too) equals the same time history
    on a model whose sections are the cracked ones; the field is left out while empty."""
    from opensees_studio.core import TransientCase

    cracked = ElasticSection(id=1, E=E, A=A, Iz=0.7 * IZ, Iy=0.7 * IZ, G=8e7, J=2e-4)

    def history(project: Project, overrides: list) -> np.ndarray:
        case = TransientCase(
            id=8,
            name="th",
            pattern_ids=[2],
            dt=0.01,
            n_steps=30,
            preload_case_ids=[1],
            section_overrides=overrides,
        )
        project.analyses.append(case)
        out = tmp_path / f"th{len(list(tmp_path.iterdir()))}"
        result = OpenSeesRunner(project).run(case, out)
        return np.asarray(result.node_disp_history(PARTS + 1))[:, 0]

    with_overrides = history(_column(transf="Linear", mass=10.0), [cracked])
    reduced = _column(transf="Linear", mass=10.0)
    reduced.sections = [cracked]
    on_cracked_model = history(reduced, [])
    gross = history(_column(transf="Linear", mass=10.0), [])
    assert np.max(np.abs(on_cracked_model)) > 0
    assert with_overrides == pytest.approx(on_cracked_model, rel=1e-9, abs=1e-15)
    assert not np.allclose(with_overrides, gross)
    data = TransientCase(id=8, dt=0.01, n_steps=3).model_dump(mode="json")
    assert "section_overrides" not in data
    dumped = TransientCase(id=8, dt=0.01, n_steps=3, section_overrides=[cracked]).model_dump(
        mode="json"
    )
    assert TransientCase.model_validate(dumped).section_overrides[0].Iz == pytest.approx(0.7 * IZ)


def test_staged_case_with_linear_geometry_runs_in_a_p_delta_model() -> None:
    project = _column()
    stages = [ConstructionStage(name="all", element_ids=list(range(1, PARTS + 1)), pattern_ids=[2])]
    refused = StagedCase(id=6, name="staged", stages=stages)
    with pytest.raises(ValueError, match="linear elastic model"):
        OpenSeesRunner(project).run(refused)
    first = StagedCase(id=7, name="staged", stages=stages, linear_geometry=True)
    result = OpenSeesRunner(project).run(first)
    assert result.disp(PARTS + 1, 1) == pytest.approx(H * L**3 / (3 * E * IZ), rel=1e-9)
    assert "linear_geometry" not in refused.model_dump(mode="json")


def test_plate_bending_factor_scales_bending_only() -> None:
    from opensees_studio.core import ElasticMembranePlateSection, ShellElement

    def plate(ep_mod: float) -> tuple[float, float]:
        nodes = [
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(1, 0, 0)),
            Node(id=3, coords=(1, 1, 0)),
            Node(id=4, coords=(0, 1, 0), restraint=(True,) * 6),
        ]
        project = Project(
            ndm=3,
            ndf=6,
            nodes=nodes,
            sections=[ElasticMembranePlateSection(id=1, E=3e10, nu=0.2, h=0.2, Ep_mod=ep_mod)],
            elements=[ShellElement(id=1, nodes=(1, 2, 3, 4), section_id=1)],
            time_series=[LinearTimeSeries(id=1)],
            load_patterns=[
                PlainLoadPattern(
                    id=1,
                    time_series_id=1,
                    nodal_loads=[
                        NodalLoad(node_id=2, forces=(1e3, 0, -1e3, 0, 0, 0)),
                        NodalLoad(node_id=3, forces=(0, 0, -1e3, 0, 0, 0)),
                    ],
                )
            ],
            analyses=[StaticCase(id=1, pattern_ids=[1])],
        )
        r = OpenSeesRunner(project).run(project.analyses[0])
        return r.disp(2, 3), r.disp(2, 1)

    (w1, u1), (w4, u4) = plate(1.0), plate(0.25)
    assert w4 == pytest.approx(4 * w1, rel=1e-6)  # bending stiffness x 0.25
    assert u4 == pytest.approx(u1, rel=1e-9)  # membrane unchanged
    section = ElasticMembranePlateSection(id=1, E=3e10, nu=0.2, h=0.2)
    assert "Ep_mod" not in section.model_dump(mode="json")

"""B33: slab (direct design, equivalent frame, corners, openings), wall (slender, grade beam),
stair (built-in, open well, stringers, Appendix M) and composite concrete methods, with the
values pinned through the bnbc2020 pack."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.design import composite_concrete as CC
from saengine.design import direct_design, equivalent_frame, slab, slab_frames, stairs
from saengine.design import special_stairs as S
from saengine.design import walls as W
from saengine.design.slab_frames import ColumnStiffness, FrameColumn, Loads
from saengine.library.objects import (
    BarMesh,
    CompositeTopping,
    GradeBeamWall,
    PlanarReinforcement,
    Staircase,
)


def table(name: str):
    return code_context.current().table(name)


# ───────────────────────────────────── pack values ─────────────────────────────────────


def test_slab_method_values_pinned():
    t = table("slabMethods")
    assert t.twoWayMethods == ["directDesign", "equivalentFrame"]  # Sec 6.5.5.1.1
    dd = t.directDesign
    assert dd.minSpans == 3 and dd.maxPanelRatio == 2.0  # Sec 6.5.6.1.1-6.5.6.1.2
    assert dd.maxLiveToDead == 2.0  # 6.5.6.1.5
    assert tuple(dd.stiffnessRatioRange) == (0.2, 5.0)  # Eq 6.6.82
    assert dd.staticDivisor == 8 and dd.minClearSpanShare == 0.65  # Eq 6.6.84, 6.5.6.2.5
    assert (dd.interiorNegative, dd.interiorPositive) == (0.65, 0.35)  # 6.5.6.3.2
    # Table 6.6.4
    assert list(dd.endSpan.interiorNegative) == [0.75, 0.70, 0.70, 0.70, 0.65]
    assert list(dd.endSpan.positive) == [0.63, 0.57, 0.52, 0.50, 0.35]
    assert list(dd.endSpan.exteriorNegative) == [0.0, 0.16, 0.26, 0.30, 0.65]
    # Tables 6.6.5-6.6.7
    assert list(dd.interiorStrip.alphaFull) == [90, 75, 45]
    assert list(dd.exteriorStrip.alphaZeroBetaFull) == [75, 75, 75]
    assert list(dd.positiveStrip.alphaZero) == [60, 60, 60]
    assert dd.beamShare == 0.85 and dd.edgeTransferShare == 0.3  # 6.5.6.5.1, 6.5.6.3.6
    assert dd.columnMomentFactor == 0.07  # Eq 6.6.87
    ef = t.equivalentFrame
    assert ef.torsionFactor == 9 and ef.faceLimit == 0.175  # Eq 6.6.88, 6.5.7.7.1
    assert ef.uniformLiveMax == 0.75 and ef.patternLiveShare == 0.75  # 6.5.7.6.2-6.5.7.6.3
    assert t.corner.extentShare == 0.2 and t.corner.alphaMin == 1.0  # 6.5.3.6
    assert (t.openings.columnColumnShare, t.openings.columnMiddleShare) == (0.125, 0.25)


def test_wall_stair_composite_values_pinned():
    w = table("wallMethods").slender
    assert w.maxAxialShare == 0.06 and w.deflectionDivisor == 150  # 6.6.8.2.6, 6.6.8.4
    assert w.deflectionFactor == 0.75 and w.minModularRatio == 6  # Eqs 6.6.93-6.6.95
    s = table("stairMethods")
    assert (s.builtIn.embedmentMin, s.builtIn.deductedStrip, s.builtIn.addedBreadth) == (
        110,
        150,
        75,
    )  # 6.7.1.3.1
    assert s.openWellShare == 0.5
    assert s.freeStanding.referenceLive == 5.0 and s.freeStanding.unitWeight == 23.56
    c = table("compositeConcrete")
    assert c.roughenedLimit == 0.55 and c.tiedSmoothLimit == 0.55  # 6.12.5.3.1-2
    assert (c.roughenedTied.base, c.roughenedTied.steelShare, c.roughenedTied.cap) == (
        1.8,
        0.6,
        3.5,
    )  # 6.12.5.3.3
    assert c.tieSpacingFactor == 4 and c.tieSpacingMax == 600  # 6.12.6.1


# ───────────────────────────────────── slabs ─────────────────────────────────────


def _grid(n: int = 4, span: float = 6000.0) -> list[FrameColumn]:
    return [
        FrameColumn(
            f"C{i}{j}",
            (i * span, j * span),
            400,
            400,
            0,
            below=ColumnStiffness(3000, 25000),
            above=ColumnStiffness(3000, 25000),
        )
        for i in range(n)
        for j in range(n)
    ]


OUTLINE = [(-200, -200), (18200, -200), (18200, 18200), (-200, 18200)]


def test_frames_of_a_flat_plate():
    frames, problems = slab_frames.build_frames(
        "Y", OUTLINE, slab.plan_axes(), _grid(), [], [], 200, 25000
    )
    assert not problems and len(frames) == 4
    assert [f.spans for f in frames] == [[6000.0] * 3] * 4
    assert frames[1].l2 == pytest.approx(6000) and frames[0].l2 == pytest.approx(3200)
    assert frames[0].edge and not frames[1].edge
    # column strip 0.25 min(l1, l2) each side (Sec 6.5.2.1)
    assert frames[1].column_strip(1) == (pytest.approx(3000), pytest.approx(3000))


def test_direct_design_interior_span_shares():
    frames, _ = slab_frames.build_frames(
        "X", OUTLINE, slab.plan_axes(), _grid(), [], [], 200, 25000
    )
    loads = Loads(6e-3, 3e-3, (("U", 1.2, 1.6),))
    rules = table("slabMethods").directDesign
    assert direct_design.limitations(frames, loads, rules) == []
    result = direct_design.design_frame(frames[1], loads, rules)
    qu = 1.2 * 6e-3 + 1.6 * 3e-3
    mo = qu * 6000 * 5600**2 / 8  # Eq 6.6.84
    positive = [m for m in result.moments if m.span == 1 and m.where == "positive"]
    assert sum(m.moment for m in positive) == pytest.approx(0.35 * mo)
    column = next(m for m in positive if m.strip == "column")
    assert column.moment == pytest.approx(0.60 * 0.35 * mo)  # Table 6.6.7, αf = 0
    neg = [m for m in result.moments if m.span == 1 and m.where == "negative at support 1"]
    assert next(m for m in neg if m.strip == "column").moment == pytest.approx(0.75 * 0.65 * mo)
    # End span without edge beams: 0.26 / 0.52 / 0.70 (Table 6.6.4); edge column 0.3 Mo.
    end = [m for m in result.moments if m.span == 0]
    assert sum(m.moment for m in end if m.where == "negative at support 0") == pytest.approx(
        0.26 * mo
    )
    assert result.column_moments[0][0] == pytest.approx(0.3 * mo)


def test_direct_design_limits_reject_two_spans():
    columns = _grid(3)
    outline = [(-200, -200), (12200, -200), (12200, 12200), (-200, 12200)]
    frames, _ = slab_frames.build_frames(
        "X", outline, slab.plan_axes(), columns, [], [], 200, 25000
    )
    problems = direct_design.limitations(
        frames, Loads(6e-3, 3e-3, (("U", 1.2, 1.6),)), table("slabMethods").directDesign
    )
    assert problems and "fewer than 3" in problems[0]


def test_column_stiffness_prismatic_is_4EI_over_L():
    assert equivalent_frame.column_stiffness(3000, 1e12, 0.0) == pytest.approx(4e12 / 3000)
    # rigid over the slab depth makes the column stiffer
    assert equivalent_frame.column_stiffness(3000, 1e12, 400) > 4e12 / 3000


def test_equivalent_frame_fixed_ends_give_fixed_end_moments():
    # One span between walls fixing the slab-beam: face moments of a fixed-ended beam.
    support = [
        slab_frames.FrameSupport(0.0, 1.0, 6000.0, "wall", wall_length=6000.0),
        slab_frames.FrameSupport(6000.0, 1.0, 6000.0, "wall", wall_length=6000.0),
    ]
    frame = slab_frames.SlabFrame("X", 0.0, support, 3000, 3000, 200, 25000, [0], alpha=[0.0])
    loads = Loads(5e-3, 0.0, (("D", 1.0, 0.0),))
    result = equivalent_frame.design_frame(frame, loads, table("slabMethods").equivalentFrame, None)
    w = 5e-3 * 6000
    negative = max(m.moment for m in result.moments if m.where.startswith("negative"))
    assert negative == pytest.approx(w * 6000**2 / 12, rel=0.01)


def test_flat_plate_design_selects_direct_design_and_checks_punching():
    reinforcement = PlanarReinforcement(
        material="r",
        cover=20,
        bottomX=BarMesh(dia=12, spacing=150),
        bottomY=BarMesh(dia=12, spacing=150),
        topX=BarMesh(dia=12, spacing=125),
        topY=BarMesh(dia=12, spacing=125),
    )
    context = slab.SlabContext(boundary=OUTLINE, axes=slab.plan_axes(), supports=[])
    opening = slab_frames.Opening("O1", ((2500, 2500), (3500, 2500), (3500, 3500), (2500, 3500)))
    design = slab_frames.design_slab(
        "flat",
        200,
        reinforcement,
        25,
        420,
        200000,
        6.0,
        3.0,
        [slab.GravityCombination("U", 1.2, 1.6)],
        context,
        _grid(),
        [],
        25000,
        (),
        [opening],
    )
    assert design.method == "directDesign"
    names = [c["name"] for c in design.checks]
    assert sum(n.startswith("Punching at") for n in names) == 16
    row = next(c for c in design.checks if c["name"].startswith("Opening O1"))
    assert row["ok"]  # within the middle strips: any size (Sec 6.5.4.2.1)


def test_corner_rows_need_the_positive_moment_in_both_faces():
    layers = slab.layers_of(
        PlanarReinforcement(
            material="r",
            cover=20,
            bottomX=BarMesh(dia=12, spacing=150),
            bottomY=BarMesh(dia=12, spacing=150),
            topX=BarMesh(dia=10, spacing=300),
        ),
        150,
    )
    envelope = {
        "bottomX": (12000.0, "U", ""),
        "bottomY": (9000.0, "U", ""),
        "topX": (0.0, None, ""),
        "topY": (0.0, None, ""),
    }
    rows = slab_frames.corner_rows(envelope, layers, 25, 420, 200000, 150, 5000)
    top = next(r for r in rows if ", top" in r["name"])
    assert not top["ok"]  # no topY bars
    assert "1000 mm" in top["note"]  # 1/5 of the longer span


# ───────────────────────────────────── walls ─────────────────────────────────────


def test_second_order_moment_eq_6_6_94():
    rules = table("wallMethods").slender
    mu, delta = W.second_order_moment(30e6, 300e3, 6000, 25000, 3.6e8, rules)
    k = 5 * 6000**2 / (0.75 * 48 * 25000 * 3.6e8)
    assert mu == pytest.approx(30e6 / (1 - 300e3 * k))
    assert delta == pytest.approx(mu * k)


def test_slender_wall_and_grade_beam_rows():
    g = W.WallGeometry(3000, 200, 6000, 6000)
    bars = W.WallBars(25, 12, 200, 10, 200, 2)
    forces = [W.PierForces("U", 300e3, 10e3, 5e6, 20e3, 30e6)]
    rows = W.slender_wall_checks(g, bars, forces, 28, 420, 200000, required=True)
    axial = rows[0]
    assert axial["capacity"] == pytest.approx(0.06 * 28)  # Sec 6.6.8.2.6
    assert axial["demand"] == pytest.approx(300e3 / (3000 * 200))
    grade = GradeBeamWall(span=5000, bottomBars=3, bottomDia=20)
    rows = W.grade_beam_checks(
        W.WallGeometry(5000, 250, 3000, 3000), grade, bars, forces, 28, 420, 200000
    )
    flexure = rows[0]
    w = 300e3 / 5000
    assert flexure["demand"] == pytest.approx(w * 5000**2 / 8 / 1e6, rel=1e-3)


# ───────────────────────────────────── stairs ─────────────────────────────────────


def test_built_in_and_open_well_rules():
    spec = stairs.StairSpec(150, 170, 250, 1200, "dogLegged", "landingEdges", 1200, well=150)
    factor, _ = stairs.built_in_factor(replace(spec, built_in=True))
    assert factor == pytest.approx((1200 - 150) / (1200 + 75))
    assert stairs.open_well_share(replace(spec, open_well=True)) == 0.5
    assert stairs.open_well_share(spec) == 1.0


def test_free_standing_expression_at_reference():
    method = table("stairMethods").freeStanding
    ms = next(e for e in method.expressions if e.id == "MS")
    values = {"A": 0.05, "B": 0.86, "C": 0.864, "L": 2.03, "H": 2.44, "T": 0.09, "fc": 20}
    # every factor reduces to its base: 4.712 × 1.555 × 1.06 × 1.2 × 1 × 1 × 0.39
    assert S.empirical_value(ms, values) == pytest.approx(4.712 * 1.555 * 1.06 * 1.2 * 0.39)


def test_sawtooth_and_helicoidal_charts():
    saw = table("stairMethods").sawtooth
    assert S.sawtooth_coefficient(3, 0.0, saw) == pytest.approx(0.0877)  # Figure 6.M.4
    assert S.sawtooth_coefficient(2, 5.0, saw) is None  # off the chart
    k1, k2, k3 = S.helicoidal_coefficients(1.05, 5, 20, 360)  # Figure 6.M.6
    assert (k1, k2, k3) == pytest.approx((-0.555, 2.32, -1.53))
    with pytest.raises(ValueError):
        S.helicoidal_coefficients(1.05, 5, 20, 400)


def test_helix_forces_at_midspan():
    f = S.helix_forces(2.0, 5.0, 10.0, 1.5, 1.4, math.radians(25), np.array([0.0]))
    assert f["My"][0] == pytest.approx(2.0) and f["Vh"][0] == pytest.approx(5.0)
    assert f["N"][0] == pytest.approx(0.0) and f["T"][0] == pytest.approx(0.0)


def test_staircase_model_fields():
    t = Staircase(
        id="S",
        name="S",
        material="c",
        waistThickness=150,
        riser=170,
        tread=250,
        flightWidth=1200,
        special="helicoidal",
        innerRadius=800,
        outerRadius=2000,
        planAngle=270,
    )
    spec = stairs.spec_of(t)
    assert spec.special == "helicoidal" and spec.plan_angle == 270


# ───────────────────────────────────── composite concrete ─────────────────────────────────────


def test_horizontal_shear_cases():
    phi = 0.75
    rough = CC.horizontal_shear(1e5, 300, 500, 28, 420, 0.0, None, True, 100, phi)
    assert rough.vnh == pytest.approx(0.55 * 300 * 500)
    av = 2 * math.pi * 10**2 / 4
    tied = CC.horizontal_shear(1e5, 300, 500, 28, 420, av, 200, True, 100, phi)
    rho = av / (300 * 200)
    assert tied.vnh == pytest.approx((1.8 + 0.6 * rho * 420) * 300 * 500)
    smooth = CC.horizontal_shear(1e5, 300, 500, 28, 420, 0.0, None, False, 100, phi)
    assert smooth.vnh == 0.0
    assert CC.horizontal_shear(1e7, 300, 500, 28, 420, av, 200, True, 100, phi).friction
    rows = CC.beam_checks(
        2e5, "U", CompositeTopping(toppingThickness=100), 300, 500, 28, 420, 10, 2, 200, phi
    )
    assert rows[0]["ok"] and rows[1]["capacity"] == pytest.approx(av, rel=1e-3)


def test_wall_joint_under_storey_shear():
    g = W.WallGeometry(3000, 200, 3000, 3000)
    bars = W.WallBars(25, 12, 200, 10, 200, 2)
    forces = [W.PierForces("U", 300e3, 400e3, 5e6, where="bottom")]
    rows = W._joint_rows(g, bars, forces, 28, 420)
    assert rows and rows[0]["demand"] == pytest.approx(400.0)

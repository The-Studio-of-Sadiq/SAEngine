"""Reinforced-concrete design checks: section capacities against hand calculations, and the
checks of an analysed one-bay frame."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from concreteproperties.results import UltimateBendingResults
from test_fem_derive import OBJECTS, PLAN, SETTINGS

from saengine.design import design, design_report
from saengine.design.rc import (
    InteractionSurface,
    beta1,
    flexure,
    phi_axial_flexure,
    section_of,
    shear,
)
from saengine.fem.derive import derive_fem
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import generate
from saengine.library.objects import LinearReinforcement, RectangleProfile
from saengine.library.settings import LoadCombination

BAR20 = math.pi * 20**2 / 4


def beam_reinforcement(top: int = 0) -> LinearReinforcement:
    groups = [{"position": "bottom", "count": 3, "dia": 20}]
    if top:
        groups.append({"position": "top", "count": top, "dia": 16})
    return LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": groups,
            "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
        }
    )


COLUMN_REINFORCEMENT = LinearReinforcement.model_validate(
    {
        "material": "B420DWR",
        "cover": 40,
        "longitudinal": [{"position": "perimeter", "count": 8, "dia": 20}],
        "transverse": {"type": "tie", "dia": 10, "spacing": 150},
    }
)


def test_code_factors() -> None:
    assert beta1(25) == 0.85
    assert beta1(35) == pytest.approx(0.80)
    assert beta1(60) == 0.65
    assert phi_axial_flexure(0.0021, 420) == 0.65
    assert phi_axial_flexure(0.0051, 420) == pytest.approx(0.90)
    assert phi_axial_flexure(0.0036, 420) == pytest.approx(0.775)
    assert phi_axial_flexure(0.001, 420, spiral=True) == 0.75


def test_rectangular_beam_flexure_and_shear_by_hand() -> None:
    # 300 x 500, 3T20 bottom, T10 stirrups at 150, cover 40: d = 500 - 40 - 10 - 10 = 440.
    section = section_of(RectangleProfile(xDim=300, yDim=500), beam_reinforcement(), 25, 420)
    a_s = 3 * BAR20
    a = a_s * 420 / (0.85 * 25 * 300)
    mn = a_s * 420 * (440 - a / 2)
    sagging = flexure(section, hogging=False)
    assert sagging.mn == pytest.approx(mn, rel=0.01)
    assert sagging.phi == 0.90  # εt = 0.003 (d - c) / c, well above 0.005
    assert sagging.eps_t == pytest.approx(0.003 * (440 - a / 0.85) / (a / 0.85), rel=0.01)
    assert sagging.phi_mn == pytest.approx(0.9 * mn, rel=0.01)
    assert flexure(section, hogging=True).phi_mn == 0  # no top bars

    vc = 0.17 * math.sqrt(25) * 300 * 440
    vs = 2 * math.pi * 10**2 / 4 * 420 * 440 / 150
    resistance = shear(section, 10, 2, 150)
    assert (resistance.vc, resistance.vs) == pytest.approx((vc, vs), rel=0.01)
    assert resistance.phi_vn == pytest.approx(0.75 * (vc + vs), rel=0.01)
    # Closely spaced stirrups: Vs is limited to 0.66 √f'c b d.
    dense = shear(section, 10, 4, 50)
    assert dense.vs_limited and dense.vs == pytest.approx(0.66 * 5 * 300 * 440, rel=1e-6)


def test_bar_groups_sharing_a_position_are_all_laid_out() -> None:
    # 3T20 + 2T16 bottom: one row of 5 bars, T20 at the ends and the middle.
    bars = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [
                {"position": "bottom", "count": 3, "dia": 20},
                {"position": "bottom", "count": 2, "dia": 16},
            ],
            "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
        }
    )
    section = section_of(RectangleProfile(xDim=300, yDim=500), bars, 25, 420)
    bar16 = math.pi * 16**2 / 4
    assert len(section.bars) == 5
    assert section.steel_area == pytest.approx(3 * BAR20 + 2 * bar16)
    assert [b.dia for b in sorted(section.bars, key=lambda b: b.x)] == [20, 16, 20, 16, 20]
    # Each bar rests on the stirrup: d to the centroid of the row.
    a_s = section.steel_area
    d = 500 - (3 * BAR20 * 60 + 2 * bar16 * 58) / a_s
    assert section.effective_depth(top=False) == pytest.approx(d)
    a = a_s * 420 / (0.85 * 25 * 300)
    assert flexure(section, hogging=False).mn == pytest.approx(a_s * 420 * (d - a / 2), rel=0.01)

    # Perimeter bars with extra top bars: the corners are not counted twice.
    mixed = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [
                {"position": "perimeter", "count": 4, "dia": 20},
                {"position": "top", "count": 2, "dia": 16},
            ],
            "transverse": {"type": "tie", "dia": 10, "spacing": 150},
        }
    )
    section = section_of(RectangleProfile(xDim=400, yDim=400), mixed, 28, 420)
    assert len(section.bars) == 6
    assert section.steel_area == pytest.approx(4 * BAR20 + 2 * bar16)
    assert sorted(b.dia for b in section.bars if b.y > 0) == [16, 16, 20, 20]
    assert any("between the perimeter corner bars" in n for n in section.notes)


def test_beam_shear_without_minimum_stirrups_by_hand() -> None:
    # No stirrups: d = 500 - 40 - 10 = 450, Vc by ACI 318-19 Table 22.5.5.1 (c).
    reinforcement = beam_reinforcement().model_copy(update={"transverse": None})
    section = section_of(RectangleProfile(xDim=300, yDim=500), reinforcement, 25, 420)
    resistance = shear(section, None, 0, None)
    rho_w = 3 * BAR20 / (300 * 450)
    lambda_s = math.sqrt(2 / (1 + 0.004 * 450))
    vc = 0.66 * lambda_s * rho_w ** (1 / 3) * 5 * 300 * 450
    assert not resistance.with_min_stirrups
    assert resistance.vc == pytest.approx(vc, rel=1e-6)  # about 72 kN, not 115 kN
    assert resistance.phi_vn == pytest.approx(0.75 * vc, rel=1e-6)
    # Too few stirrups (T6 at 600: Av = 57 < Av,min = 0.35 b s / fyt = 150 mm²): same Vc.
    sparse = shear(section, 6, 2, 600)
    assert sparse.av_min == pytest.approx(0.35 * 300 * 600 / 420)
    assert not sparse.with_min_stirrups
    assert sparse.vc == pytest.approx(vc, rel=1e-6)
    # √f'c is capped at 8.3 MPa in Vc.
    strong = section_of(RectangleProfile(xDim=300, yDim=500), beam_reinforcement(), 100, 420)
    assert shear(strong, 10, 2, 150).vc == pytest.approx(0.17 * 8.3 * 300 * 440, rel=1e-6)


def test_check_pass_and_fail_follow_the_reported_utilisation() -> None:
    from saengine.design.check import _check

    # 1.0004 is reported as 1.000: it passes, as the viewer's colour band (amber) says.
    assert _check("x", 1.0004, 1.0, "kN", None) == _check("x", 1.0, 1.0, "kN", None)
    assert _check("x", 1.0004, 1.0, "kN", None)["ok"]
    failing = _check("x", 1.0006, 1.0, "kN", None)
    assert failing["utilisation"] == 1.001 and not failing["ok"]


def test_sloped_beams_along_y_find_their_top_whichever_way_they_are_drawn() -> None:
    # A rafter along Y rising 0.3 m over 6 m: the analysis treats it as "vertical" (|dz| >
    # |dx|), so its depth lies along local y, which points up or down with the drawing direction.
    import numpy as np

    from saengine.design.check import _Piece, _profile_forces
    from saengine.fem.derive import local_axes

    def piece(a: tuple[float, ...], b: tuple[float, ...]) -> _Piece:
        axes = np.array(local_axes(np.array(a, dtype=float), np.array(b, dtype=float)))
        return _Piece("R1", 1, 6.0, depth_along_z=False, axes=axes, forces=[])

    def mz(value: float) -> np.ndarray:
        return np.array([[0, 0, 0, 0, 0, value]], dtype=float)

    up = piece((0, 0, 0), (0, 6, 0.3))  # local y points up
    down = piece((0, 6, 0.3), (0, 0, 0))  # local y points down
    assert up.axes[1][2] > 0 > down.axes[1][2]
    # Positive Mz stretches the -y fibres: the bottom of `up`, so sagging (negative Mx).
    assert _profile_forces(up, False, mz(10.0))["Mx"][0] == pytest.approx(-10e3)
    # The same physical state seen from the member drawn the other way: x and y reverse, and
    # the moment about the unchanged z axis changes sign. It must be the same sagging moment.
    assert _profile_forces(down, False, mz(-10.0))["Mx"][0] == pytest.approx(-10e3)
    # A floor beam (depth along local z, always up) is unaffected.
    floor = piece((0, 0, 0), (0, 6, 0))
    floor.depth_along_z = True
    my = np.array([[0, 0, 0, 0, 10.0, 0]])
    assert _profile_forces(floor, False, my)["Mx"][0] == pytest.approx(10e3)


def test_tied_column_axial_and_interaction_point_by_hand() -> None:
    # 400 x 400, 8T20 (3 per face): bar centres 140 mm from the axes; f'c 28, fy 420.
    section = section_of(RectangleProfile(xDim=400, yDim=400), COLUMN_REINFORCEMENT, 28, 420)
    assert len(section.bars) == 8 and section.symmetric
    ast = 8 * BAR20
    p0 = 0.85 * 28 * (400 * 400 - ast) + 420 * ast
    assert section.phi_pn_max == pytest.approx(0.80 * 0.65 * p0, rel=1e-6)
    surface = InteractionSurface(section)
    assert surface.check(0.5 * section.phi_pn_max, 0, 0).utilisation == pytest.approx(0.5)
    assert surface.check(1.1 * section.phi_pn_max, 0, 0).utilisation > 1

    # Neutral axis at c = 200 (bending about x, top face in compression): a = 0.85 c = 170.
    # Top bars (d = 60) at εs = 0.0021 = fy/Es, middle bars at zero, bottom bars at yield in
    # tension; εt = εty, so compression-controlled, φ = 0.65.
    cc = 0.85 * 28 * (400 * 170 - 3 * BAR20)
    fs = 3 * BAR20 * 420
    pn = cc + fs - fs
    mn = cc * (200 - 85) + fs * 140 + fs * 140
    phi = 0.65
    capacity = surface.moment_capacity(phi * pn, 0.0)
    assert capacity == pytest.approx(phi * mn, rel=0.03)
    # On the curve the utilisation is 1; biaxially (45°) the capacity is lower.
    point = surface.check(phi * pn, phi * mn, 0.0)
    assert point.utilisation == pytest.approx(1.0, rel=0.03)
    diagonal = surface.check(phi * pn, phi * mn / math.sqrt(2), phi * mn / math.sqrt(2))
    assert diagonal.utilisation > point.utilisation


@pytest.mark.parametrize(
    ("width", "depth", "count", "dia", "fc", "fy"),
    [(400, 400, 8, 20, 28, 420), (300, 600, 10, 25, 35, 500), (500, 350, 12, 16, 25, 420)],
)
def test_interaction_surface_is_never_outside_the_exact_curve(
    width: float, depth: float, count: int, dia: float, fc: float, fy: float
) -> None:
    # The φ-factored diagram bends inwards where φ leaves 0.65 (εt = εty) and reaches 0.90
    # (εt = εty + 0.003): chords across those corners would pass outside the true curve. At
    # every exact point of the strong- and weak-axis meridians (concreteproperties at that
    # neutral axis, φ from its εt), the interpolated capacity is at most 0.2 % larger.
    from concreteproperties.utils import calculate_extreme_fibre

    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [{"position": "perimeter", "count": count, "dia": dia}],
            "transverse": {"type": "tie", "dia": 10, "spacing": 150},
        }
    )
    section = section_of(RectangleProfile(xDim=width, yDim=depth), reinforcement, fc, fy)
    surface = InteractionSurface(section)
    points = section.analysis.compound_geometry.points
    eps_ty = fy / 200_000
    in_transition = 0
    for theta, along in ((0.0, 0), (math.pi / 2, 1)):
        _, d_t = calculate_extreme_fibre(points=points, theta=theta)
        for d_n in np.linspace(0.05, 1.3, 120) * d_t:
            result = section.analysis.calculate_ultimate_section_actions(
                d_n=float(d_n),
                ultimate_results=UltimateBendingResults(
                    default_units=section.analysis.default_units, theta=theta
                ),
            )
            eps_t = 0.003 * (1 / result.k_u - 1)
            phi = phi_axial_flexure(eps_t, fy)
            pu = phi * result.n
            exact = phi * abs((result.m_x, result.m_y)[along])
            if not -section.phi_tension < pu < section.phi_pn_max or exact < 1e6:
                continue
            in_transition += eps_ty < eps_t < eps_ty + 0.003
            capacity = surface.moment_capacity(pu, along * math.pi / 2)
            assert capacity <= exact * 1.002, (theta, d_n, pu / 1e3)
    assert in_transition > 20


def _column(width: float, depth: float, groups: list[dict]) -> InteractionSurface:
    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": groups,
            "transverse": {"type": "tie", "dia": 10, "spacing": 150},
        }
    )
    profile = RectangleProfile(xDim=width, yDim=depth)
    return InteractionSurface(section_of(profile, reinforcement, 28, 420))


def _exact(surface: InteractionSurface, degrees: float, d_n: float) -> tuple[float, float, float]:
    """φPn, φMnx, φMny [N, N·mm] of the section at that neutral axis, φ from its εt."""
    cp = surface.section.analysis
    result = cp.calculate_ultimate_section_actions(
        d_n=d_n,
        ultimate_results=UltimateBendingResults(
            default_units=cp.default_units, theta=math.radians(degrees)
        ),
    )
    phi = phi_axial_flexure(0.003 * (1 / result.k_u - 1), surface.section.fy)
    return phi * result.n, phi * result.m_x, phi * result.m_y


@pytest.mark.parametrize(
    ("width", "depth", "groups", "angles"),
    [
        # Doubly symmetric: one quadrant of neutral-axis angles, all between computed meridians.
        (600, 300, [{"position": "perimeter", "count": 4, "dia": 32}], np.arange(1.25, 90, 5)),
        # Unsymmetric (different top and bottom bars, side bars): the full turn.
        (
            350,
            700,
            [
                {"position": "top", "count": 3, "dia": 20},
                {"position": "bottom", "count": 5, "dia": 28},
                {"position": "sides", "count": 2, "dia": 16},
            ],
            np.arange(2.5, 360, 10),
        ),
    ],
)
def test_interaction_surface_between_meridians_is_never_outside_the_exact_surface(
    width: float, depth: float, groups: list[dict], angles: np.ndarray
) -> None:
    # Biaxial demands: exact points at neutral-axis angles off the computed meridians. Where φ
    # changes along the contour at a given Pu, chords between meridians 15° apart overstated the
    # capacity by up to 1.4 % (600 x 300, 4 Ø32, neutral axis at 100°). The bound is 0.4 %: the
    # largest found over nine sections was 0.35 %, where the contour runs almost along the
    # demand ray and a tiny shift of the moment's direction changes the radial capacity most.
    from concreteproperties.utils import calculate_extreme_fibre

    surface = _column(width, depth, groups)
    s = surface.section
    points = s.analysis.compound_geometry.points
    probes = [(100.0, 305.0)]  # the reviewer's worst point (1.37 % before)
    for degrees in angles:
        _, d_t = calculate_extreme_fibre(points=points, theta=math.radians(degrees))
        probes += [(float(degrees), float(d_n)) for d_n in np.geomspace(0.1, 1.3, 14) * d_t]
    checked = 0
    for degrees, d_n in probes:
        pu, mx, my = _exact(surface, degrees, d_n)
        m = math.hypot(mx, my)
        if not -s.phi_tension < pu < s.phi_pn_max or m < 0.05 * 1e6 * width * depth / 1e4:
            continue
        capacity = surface.moment_capacity(pu, math.atan2(abs(my), abs(mx)))
        assert capacity <= m * 1.004, (degrees, d_n, pu / 1e3, capacity / m)
        checked += 1
    assert checked > 0.6 * len(probes)


def test_unsymmetric_column_in_tension_reads_signed_moments() -> None:
    # 2 Ø16 top, 4 Ø25 bottom. Under tension the bars' resultant lies below the centroid, so
    # the contour at Pu is off the origin: on the hogging meridian the moment changes sign. The
    # absolute moments used to fold it back, overstating the hogging capacity 2.2 times.
    surface = _column(
        300,
        500,
        [{"position": "top", "count": 2, "dia": 16}, {"position": "bottom", "count": 4, "dia": 25}],
    )
    assert not surface.section.symmetric
    pu, mx, _ = _exact(surface, 180.0, 50.0)
    assert pu == pytest.approx(-144e3, rel=0.01) and mx == pytest.approx(-41.96e6, rel=0.01)
    assert surface.moment_capacity(pu, 0.0) <= abs(mx) * 1.004
    # Factored tension at zero moment about the centroid: at most both rows yielding with the
    # resultant at the centroid, 0.9 (Ftop + Fbottom) with Ftop · 194 = Fbottom · 187.5, top
    # 402 mm² at 420 MPa: 0.9 × (169 + 175) = 310 kN (less with concrete in compression).
    assert surface.check(-250e3, 0.0, 0.0).utilisation < 1
    assert surface.check(-400e3, 0.0, 0.0).utilisation == math.inf
    assert surface.check(-400e3, 1e6, 0.0).utilisation == math.inf
    # Old behaviour: φ fy Ast = 894 kN, so the axial utilisation alone looked like 0.45.
    assert surface.section.phi_tension == pytest.approx(894e3, rel=1e-3)


# ─────────────────────────────── the analysed one-bay frame ───────────────────────────────

GRAVITY = LoadCombination(name="1.2D + 1.6L + 0.5Lr", D=1.2, L=1.6, Lr=0.5)


def reinforced(columns: bool = True) -> ObjectLibrary:
    data = OBJECTS.model_dump(mode="json", by_alias=True)
    for o in data["objects"]:
        if o["id"] == "BM":
            o["reinforcement"] = beam_reinforcement(top=3).model_dump(mode="json")
        if o["id"] == "COL" and columns:
            o["reinforcement"] = COLUMN_REINFORCEMENT.model_dump(mode="json")
    return ObjectLibrary.model_validate(data)


@pytest.fixture(scope="module")
def frame(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The one-bay frame as a project folder, analysed."""
    root = tmp_path_factory.mktemp("bay")
    settings = SETTINGS.model_copy(update={"combinations": [GRAVITY]})
    building = generate(PLAN, "s")
    materials = default_material_library()
    d = derive_fem(building, OBJECTS, materials, settings, {"bim": "abc"})
    files = {
        "02 Project Settings/project-settings.json": settings.model_dump_json(by_alias=True),
        "03 Materials/materials.json": materials.model_dump_json(by_alias=True),
        "04 Objects/objects.json": reinforced().model_dump_json(by_alias=True),
        "06 BIM/bim.json": building.model_dump_json(by_alias=True),
        "08 FEM/model.osmodel": json.dumps(d.project),
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    static = [a["id"] for a in d.project["analyses"] if a.get("type", "Static") == "Static"]
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(root / "08 FEM" / "model.osmodel"),
            "--cases",
            *map(str, static or range(1, 9)),
            "--out",
            str(root / "08 FEM" / "model.results"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    return root


def _station(model: dict, note: str) -> float:
    """The position along its whole beam (0 to 1) of a check's station "B1#3 at 0.40 L"."""
    import re

    name, at = re.search(r"(\S+) at ([\d.]+) L$", note).groups()
    coords = {n["id"]: np.array(n["coords"]) for n in model["nodes"]}
    chain = [e for e in model["elements"] if e["name"].split("#")[0] == name.split("#")[0]]
    ends = [(coords[e["nodes"][0]], coords[e["nodes"][1]], e["name"]) for e in chain]
    start = min((a for a, _, _ in ends), key=lambda p: (p[0], p[1]))
    finish = max((b for _, b, _ in ends), key=lambda p: (p[0], p[1]))
    a, b, _ = next(x for x in ends if x[2] == name)
    point = a + float(at) * (b - a)
    return float(np.linalg.norm(point - start) / np.linalg.norm(finish - start))


def test_frame_beams_sag_at_midspan_and_hog_at_the_supports(frame: Path) -> None:
    report = design_report(frame / "08 FEM" / "model.results", frame / "08 FEM" / "model.osmodel")
    model = json.loads((frame / "08 FEM" / "model.osmodel").read_text(encoding="utf-8"))
    json.dumps(report)  # JSON-ready
    assert report["code"] == "BNBC 2020 Part 6 Chapter 6"
    assert report["combinations"] == [GRAVITY.name]
    elements = {e["id"]: e for e in report["elements"]}
    assert sorted(elements) == ["B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4"]
    for beam in ("B1", "B2", "B3", "B4"):
        checks = {c["name"]: c for c in elements[beam]["checks"]}
        sagging = checks["Flexure, sagging (bottom bars)"]
        hogging = checks["Flexure, hogging (top bars)"]
        assert sagging["demand"] > 0 and hogging["demand"] > 0
        assert sagging["combination"] == GRAVITY.name
        # Gravity load on a frame beam: largest sagging at midspan, hogging at an end. The beam
        # is a chain of members (cut for the slab's load shapes, 0.0.45): the sagging station
        # lies within a member length of the middle of the beam.
        assert abs(_station(model, sagging["note"]) - 0.5) < 0.1, sagging["note"]
        assert hogging["note"].endswith(("at 0.00 L", "at 1.00 L")), hogging["note"]
        assert checks["Shear"]["note"].endswith(("at 0.00 L", "at 1.00 L"))
        # Both capacities come from the bar layout: 3T20 bottom, 3T16 top.
        assert sagging["capacity"] > hogging["capacity"] > 0
        assert elements[beam]["utilisation"] == max(
            c["utilisation"] for c in elements[beam]["checks"] if not c["flag"]
        )
    column = {c["name"]: c for c in elements["C1"]["checks"]}
    assert column["Axial compression"]["demand"] > 0
    assert column["Axial force and biaxial bending"]["utilisation"] < 1
    # Slenderness per bending axis (saengine.design.slender; tests in test_design_slender.py):
    # gravity only, so no storey is known to sway: nonsway, k = 1, lu below the beams.
    slender = [c for name, c in column.items() if name.startswith("Slenderness about")]
    assert len(slender) == 2
    for check in slender:
        s = check["slenderness"]
        assert s["sway"] is None and s["k"] == 1.0
        assert s["lu"] < 3200 and check["demand"] == pytest.approx(s["lu"] / s["r"], rel=1e-3)
    summary = report["summary"]
    assert summary["checked"] == 8 and summary["passed"] + summary["failed"] == 8
    assert summary["maxUtilisation"] == max(e["utilisation"] for e in report["elements"])


def test_frame_members_without_reinforcement_are_skipped(frame: Path) -> None:
    from saengine.library import BuildingModel, MaterialLibrary, ProjectSettings

    def read(relative: str) -> str:
        return (frame / relative).read_text(encoding="utf-8")

    report = design(
        json.loads(read("08 FEM/model.osmodel")),
        frame / "08 FEM" / "model.results",
        BuildingModel.model_validate_json(read("06 BIM/bim.json")),
        reinforced(columns=False),
        MaterialLibrary.model_validate_json(read("03 Materials/materials.json")),
        ProjectSettings.model_validate_json(read("02 Project Settings/project-settings.json")),
    )
    assert sorted(e["id"] for e in report["elements"]) == ["B1", "B2", "B3", "B4"]
    skipped = {s["id"]: s["reason"] for s in report["skipped"]}
    assert skipped == {c: "no reinforcement" for c in ("C1", "C2", "C3", "C4")}
    assert report["summary"]["skipped"] == 4


def test_circular_and_unsymmetric_columns() -> None:
    from saengine.library.objects import CircleProfile

    def ring(count: int) -> LinearReinforcement:
        return LinearReinforcement.model_validate(
            {
                "material": "B420DWR",
                "cover": 40,
                "longitudinal": [{"position": "perimeter", "count": count, "dia": 20}],
                "transverse": {"type": "spiral", "dia": 10, "spacing": 50},
            }
        )

    circle = section_of(CircleProfile(radius=250), ring(8), 28, 420)
    assert circle.spiral and circle.symmetric
    ast = 8 * BAR20
    p0 = 0.85 * 28 * (math.pi * 250**2 - ast) + 420 * ast
    assert circle.phi_pn_max == pytest.approx(0.85 * 0.75 * p0, rel=1e-6)
    surface = InteractionSurface(circle)
    # Nearly the same capacity in every direction.
    along, diagonal = (surface.moment_capacity(1e6, a) for a in (0.0, math.pi / 4))
    assert diagonal == pytest.approx(along, rel=0.05)

    # Five bars on a rectangle: the extra bar makes the layout unsymmetric, so every quadrant
    # is computed and the weakest governs; it lies between four and six bars.
    profile = RectangleProfile(xDim=400, yDim=400)
    capacities = []
    for count in (4, 5, 6):
        section = section_of(profile, ring(count), 28, 420)
        assert section.symmetric == (count != 5)
        capacities.append(InteractionSurface(section).moment_capacity(5e5, 0.0))
    assert capacities[0] <= capacities[1] <= capacities[2]

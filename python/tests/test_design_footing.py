"""Isolated and combined footing design: soil pressure, shear and flexure by hand, and the
footings of an analysed one-bay frame."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_fem_derive import OBJECTS, PLAN, SETTINGS

from saengine.design.footing import (
    ColumnBase,
    FootingSpec,
    design_footing,
    footing_checks,
    one_way_shear_capacity,
    punching_stress,
    service_combinations,
    soil_pressure,
)
from saengine.fem.derive import derive_fem
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import BuildingModel, FootingElement, generate
from saengine.library.objects import BarMesh
from saengine.library.settings import Foundation, ProjectSettings

KN = 1e3


# ─────────────────────────────────────── soil pressure ───────────────────────────────────────


def test_bearing_pressure_inside_the_kern_by_hand() -> None:
    # 1000 kN on 2.0 x 1.5 m, 200 mm off centre along the length: q = P/A (1 ± 6e/L).
    p = soil_pressure(1000 * KN, 200, 0, 2000, 1500)
    mean = 1000 * KN / (2000 * 1500)
    assert p.state == "kern" and p.contact == 1
    assert p.qmax == pytest.approx(mean * 1.6) and p.qmin == pytest.approx(mean * 0.4)
    assert p.at(1000, 0) == pytest.approx(mean * 1.6)
    assert p.over(-1000, 1000, -750, 750) == pytest.approx(1000 * KN)
    # Biaxial inside the kern: the corners carry P/A (1 ± 6eu/L ± 6ev/B).
    q = soil_pressure(1000 * KN, 100, 75, 2000, 1500)
    assert q.qmax == pytest.approx(mean * (1 + 0.3 + 0.3))
    assert q.at(1000, 750) == pytest.approx(q.qmax)


def test_bearing_pressure_in_partial_contact_by_hand() -> None:
    # e = 500 mm > L/6 = 333 mm: triangular pressure over 3 (L/2 - e) = 1500 mm.
    p = soil_pressure(1000 * KN, 500, 0, 2000, 1500)
    qmax = 2 * 1000 * KN / (3 * 1500 * (1000 - 500))
    assert p.state == "partial"
    assert p.qmax == pytest.approx(qmax) and p.contact == pytest.approx(0.75)
    assert p.at(1000, 0) == pytest.approx(qmax) and p.at(-500, 0) == pytest.approx(0, abs=1e-9)
    assert p.at(-900, 0) == 0
    # The pressure still carries the load at its eccentricity.
    assert p.over(-1000, 1000, -750, 750) == pytest.approx(1000 * KN)
    force, first_u, first_v = p.integrals(-1000, 1000, -750, 750)
    assert first_u / force == pytest.approx(500) and first_v == pytest.approx(0, abs=1e-3)
    # The same in the other direction, and outside the base.
    assert soil_pressure(1000 * KN, 0, -500, 1500, 2000).qmax == pytest.approx(qmax)
    assert soil_pressure(1000 * KN, 1000, 0, 2000, 1500).state == "unstable"
    assert soil_pressure(-1.0, 0, 0, 2000, 1500).state == "uplift"


def grid_resultant(p, length: float, width: float, n: int = 400) -> tuple[float, float, float]:
    """Force and eccentricities of ``max(0, q)`` by the midpoint rule, independent of the
    polygon integrals."""
    u = (np.arange(n) + 0.5) / n * length - length / 2
    v = (np.arange(n) + 0.5) / n * width - width / 2
    uu, vv = np.meshgrid(u, v, indexing="ij")
    q = np.maximum(p.a + p.gu * uu + p.gv * vv, 0.0) * (length / n) * (width / n)
    total = float(q.sum())
    return total, float((q * uu).sum()) / total, float((q * vv).sum()) / total


@pytest.mark.parametrize(
    ("eu", "ev", "length", "width"),
    [
        (300, 200, 2000, 1500),
        (400, 60, 2000, 2000),
        (-227, -107, 1800, 1800),
        (600, 400, 2000, 1500),
    ],
)
def test_biaxial_partial_contact_is_in_equilibrium(
    eu: float, ev: float, length: float, width: float
) -> None:
    p = soil_pressure(1000 * KN, eu, ev, length, width)
    assert p.state == "partial" and p.clip and 0 < p.contact < 1
    total, e_u, e_v = grid_resultant(p, length, width)
    assert total == pytest.approx(1000 * KN, rel=2e-3)
    assert (e_u, e_v) == pytest.approx((eu, ev), abs=0.002 * length)
    corners = [p.at(su * length / 2, sv * width / 2) for su in (-1, 1) for sv in (-1, 1)]
    assert max(corners) == pytest.approx(p.qmax) and min(corners) == 0


def test_biaxial_out_of_the_rhombic_kern_but_inside_both_middle_thirds() -> None:
    # The reviewer's corner footing: eu/L = 0.126 and ev/B = 0.059 are both inside the middle
    # third but leave the rhombic kern; an exact solution (361 x 361 grid) gave 99.4 % contact.
    p = soil_pressure(500 * KN, -227, -107, 1800, 1800)
    assert p.contact == pytest.approx(0.994, abs=0.003)
    linear = 500 * KN / 1800**2 * (1 + 6 * 227 / 1800 + 6 * 107 / 1800)
    assert p.qmax == pytest.approx(linear, rel=0.02)  # barely more than the linear corner


# ─────────────────────────────── one footing, loads by hand ───────────────────────────────

T16 = BarMesh(dia=16, spacing=150)


def square_footing(**changes: object) -> FootingSpec:
    """1.8 x 1.8 x 0.5 m, cover 75, T16 at 150 both ways, f'c 25, fy 420, a 400 x 400 column."""
    values: dict = {
        "id": "F1",
        "type": "F18",
        "footing_type": "isolated",
        "length": 1800,
        "width": 1800,
        "thickness": 500,
        "elevation": -1000,
        "cover": 75,
        "fc": 25,
        "fy": 420,
        "columns": [ColumnBase("C1", 0, 0, 400, 400, 1500)],
        "bottom_x": T16,
        "bottom_y": T16,
    }
    values.update(changes)
    return FootingSpec(**values)


def by_name(checks: list[dict]) -> dict[str, dict]:
    return {c["name"]: c for c in checks}


def test_effective_depths_of_the_two_layers() -> None:
    t20 = BarMesh(dia=20, spacing=150)
    spec = square_footing(bottom_x=t20, top_x=T16, top_y=t20)
    # X outer: 500 - 75 - 10; Y on the X bars: 500 - 75 - 20 - 8; punching the mean.
    assert spec.depths() == {"u": 415, "v": 397} and spec.d == 406
    assert spec.depths("top") == {"u": 417, "v": 399}
    # One direction without bars: the other layer lies against the cover, and is used for both.
    assert square_footing(bottom_y=None).depths() == {"u": 417, "v": 417}
    assert square_footing(bottom_x=None).depths() == {"u": 417, "v": 417}
    assert square_footing(bottom_x=None, bottom_y=None).d == 425


def test_punching_one_way_shear_and_flexure_by_hand() -> None:
    spec = square_footing()
    pu = 1200 * KN
    checks, notes = design_footing(
        spec, {}, {"1.2D + 1.6L": [np.array([pu, 0.0, 0.0])]}, Foundation()
    )
    checks = by_name(checks)
    # X bars the outer layer, Y bars on them (as in slabs); punching takes the mean depth.
    d_x, d_y = 500 - 75 - 16 / 2, 500 - 75 - 16 - 16 / 2
    assert spec.depths() == {"u": d_x, "v": d_y}
    d = (d_x + d_y) / 2
    assert spec.d == d == 500 - 75 - 16
    q = pu / 1800**2
    lambda_s = math.sqrt(2 / (1 + 0.004 * d))

    # Punching at d/2: Vu = Pu - q (c + d)², vc = 0.33 λs √f'c governs (β = 1, αs d / b0 large).
    b0 = 4 * (400 + d)
    vu = pu - q * (400 + d) ** 2
    phi_vc = 0.75 * 0.33 * lambda_s * 5
    assert punching_stress(400, 400, d, b0, 40, 25) == pytest.approx(0.33 * lambda_s * 5)
    punching = checks["Punching at C1"]
    assert punching["demand"] == pytest.approx(vu / KN, rel=0.01)
    assert punching["capacity"] == pytest.approx(phi_vc * b0 * d / KN, rel=0.01)
    assert punching["utilisation"] == pytest.approx(vu / (b0 * d) / phi_vc, rel=0.01)

    # One-way shear at d from the face, each direction with its own layer's d: the
    # 900 - 200 - d strip beyond it.
    a_s = math.pi * 16**2 / 4 * 1000 / 150
    for label, d_layer in (("X", d_x), ("Y", d_y)):
        rho = a_s / (1000 * d_layer)
        lam = math.sqrt(2 / (1 + 0.004 * d_layer))
        vu1 = q * (900 - 200 - d_layer) * 1800
        phi_vc1 = 0.75 * 0.66 * lam * rho ** (1 / 3) * 5 * 1800 * d_layer
        assert one_way_shear_capacity(1800, d_layer, rho, 25) == pytest.approx(phi_vc1)
        one_way = checks[f"One-way shear {label}"]
        assert one_way["demand"] == pytest.approx(vu1 / KN, rel=0.005)
        assert one_way["capacity"] == pytest.approx(phi_vc1 / KN, rel=0.005)
        assert f"d = {d_layer:.0f} mm" in one_way["note"]

    # Flexure at the column face: q B l² / 2 per metre width, l = 700 mm.
    mu = q * 1800 * 700**2 / 2 / 1.8
    a = a_s * 420 / (0.85 * 25 * 1000)
    for label, d_layer in (("X", d_x), ("Y", d_y)):
        phi_mn = 0.9 * a_s * 420 * (d_layer - a / 2)
        flexure = checks[f"Flexure {label} (bottom)"]
        assert flexure["demand"] == pytest.approx(mu / 1e6, rel=0.01)
        assert flexure["capacity"] == pytest.approx(phi_mn / 1e6, rel=0.005)
        assert flexure["unit"] == "kN·m/m"

    # Minimum steel: 0.0018 x 500 x 1000 = 900 mm²/m against 1340 provided.
    minimum = checks["Min. reinforcement X (bottom)"]
    assert (minimum["demand"], minimum["capacity"]) == pytest.approx((900, a_s), rel=1e-3)
    assert "Flexure X (top)" not in checks and "Bearing (service)" not in checks
    assert notes == ["F1: no service combination could be formed for the bearing check"]


def test_bearing_net_of_overburden_with_footing_weight_and_soil() -> None:
    spec = square_footing()
    foundation = Foundation(allowableBearing=300, soilUnitWeight=18, groundLevel=0)
    service = {"D + L": [np.array([800 * KN, 0.0, 0.0])], "D": [np.array([600 * KN, 0.0, 0.0])]}
    checks, _ = design_footing(spec, service, {}, foundation)
    bearing = by_name(checks)["Bearing (service)"]
    area = 1.8 * 1.8
    weight = 2400 * 9.80665 / 1e3 * area * 0.5 + 18 * area * 1.0  # kN: concrete + 1 m of soil
    gross = (800 + weight) / area
    net = gross - 18 * 1.5  # Df = 1.5 m to the underside
    assert bearing["combination"] == "D + L"
    assert bearing["demand"] == pytest.approx(net, rel=1e-3)
    assert bearing["capacity"] == 300 and bearing["unit"] == "kPa"

    # A column moment takes the resultant beyond the kern: partial contact, by hand.
    moment = 800 * KN * 450  # about v: e = 450 mm along u (kern 300 mm)
    checks, _ = design_footing(
        spec, {"D + 0.6WX": [np.array([800 * KN, 0.0, moment])]}, {}, foundation
    )
    bearing = by_name(checks)["Bearing (service)"]
    total = 800 + weight
    e = 450 * 800 / total
    qmax = 2 * total / (3 * 1.8 * (0.9 - e / 1000))
    assert bearing["demand"] == pytest.approx(qmax - 27, rel=1e-3)
    assert "partial contact" in bearing["note"]

    # Beyond the kern both ways: the exact biaxial contact pressure.
    checks, _ = design_footing(
        spec,
        {"D + 0.7EX": [np.array([800 * KN, -moment, moment])]},
        {},
        foundation,
    )
    bearing = by_name(checks)["Bearing (service)"]
    exact = soil_pressure(total * KN, e, e, 1800, 1800)
    assert bearing["demand"] == pytest.approx(exact.qmax * 1e3 - 27, rel=1e-3)
    assert "partial contact" in bearing["note"]

    # The resultant outside the base: its own check, e against the half side (not a sentinel).
    checks, _ = design_footing(
        spec,
        {
            "D": [np.array([800 * KN, 0.0, 0.0])],
            "0.6D + W": [np.array([400 * KN, 0.0, moment * 3])],
        },
        {},
        foundation,
    )
    checks = by_name(checks)
    outside = checks["Resultant within the base (service)"]
    e = 800 * 1350 / (400 + weight)  # 3 x 800 kN x 450 mm on 400 kN + the weight
    assert outside["demand"] == pytest.approx(e, rel=1e-3) and outside["capacity"] == 900
    assert outside["utilisation"] == pytest.approx(e / 900, rel=1e-2) and not outside["ok"]
    assert checks["Bearing (service)"]["combination"] == "D" and checks["Bearing (service)"]["ok"]

    # Without qa the bearing is not checked, and a note says what to enter.
    checks, notes = design_footing(spec, service, {}, Foundation())
    assert "Bearing (service)" not in by_name(checks)
    assert any("enter the net allowable bearing pressure" in n for n in notes)


def test_combined_footing_resultant_and_hogging_between_columns_by_hand() -> None:
    # Two 400 x 400 columns 6 m apart on a 7.8 x 1.8 x 0.6 m footing with T16 at 150 on top.
    columns = [ColumnBase("C1", -3000, 0, 400, 400), ColumnBase("C2", 3000, 0, 400, 400)]
    spec = square_footing(
        footing_type="combined",
        length=7800,
        thickness=600,
        columns=columns,
        top_x=T16,
        top_y=T16,
    )
    pu = 900 * KN
    checks, _ = design_footing(
        spec, {}, {"1.4D": [np.array([pu, 0, 0]), np.array([pu, 0, 0])]}, Foundation()
    )
    checks = by_name(checks)
    # Symmetric: uniform pressure, the largest hogging at midspan, P (L/4 - 3000) per footing.
    hogging = pu * (3000 - 7800 / 4) / 1.8
    top = checks["Flexure between columns (top)"]
    assert top["demand"] == pytest.approx(hogging / 1e6, rel=0.01)
    assert top["capacity"] > 0 and "Punching at C1" in checks and "Punching at C2" in checks
    # Across the footing: a strip c + d wide under each column carries its load, Pu / B
    # uniform across: M = Pu / B (900 - 200)² / 2 at the face, V at dY from it (the strip is
    # c + d wide with the mean d; the Y bars are the inner layer).
    d = 600 - 75 - 16
    d_y = 600 - 75 - 16 - 16 / 2
    strip = 400 + d
    transverse = checks["Flexure Y (bottom)"]
    assert transverse["demand"] == pytest.approx(pu / 1800 * 700**2 / 2 / strip / 1e3, rel=0.01)
    assert "transverse strip under C" in transverse["note"]
    a_s = math.pi * 64 / 0.150
    a = a_s * 420 / (0.85 * 25 * 1000)
    assert transverse["capacity"] == pytest.approx(0.9 * a_s * 420 * (d_y - a / 2) / 1e6, rel=5e-3)
    shear = checks["One-way shear Y"]
    assert shear["demand"] == pytest.approx(pu / 1800 * (700 - d_y) / KN, rel=0.005)
    assert shear["capacity"] == pytest.approx(
        one_way_shear_capacity(strip, d_y, a_s / (1000 * d_y), 25) / KN, rel=0.005
    )
    # Top flexure between the columns: the top X bars are the outer top layer.
    d_top_x = 600 - 75 - 16 / 2
    a_top = 0.9 * a_s * 420 * (d_top_x - a / 2) / 1e6
    assert spec.depths("top") == {"u": d_top_x, "v": d_y}
    assert top["capacity"] == pytest.approx(a_top, rel=5e-3)

    # Unequal loads: the resultant of both columns about the centroid, by hand.
    service = {"D": [np.array([1000 * KN, 0, 0]), np.array([500 * KN, 0, 0])]}
    foundation = Foundation(allowableBearing=500, groundLevel=-1000)  # no soil above
    checks, _ = design_footing(spec, service, {}, foundation)
    bearing = by_name(checks)["Bearing (service)"]
    weight = 2400 * 9.80665 / 1e3 * 7.8 * 1.8 * 0.6
    total = 1500 + weight
    e = 3000 * (1000 - 500) / total  # towards C1 (-u)
    gross = total / (7.8 * 1.8) * (1 + 6 * e / 7800)
    assert bearing["demand"] == pytest.approx(gross - 18 * 0.6, rel=1e-3)
    assert f"eu = -{e:.0f} mm" in bearing["note"]

    # Without top bars the hogging moment fails with a note.
    bare = square_footing(footing_type="combined", length=7800, thickness=600, columns=columns)
    checks, _ = design_footing(
        bare, {}, {"1.4D": [np.array([pu, 0, 0]), np.array([pu, 0, 0])]}, Foundation()
    )
    top = by_name(checks)["Flexure between columns (top)"]
    assert not top["ok"] and "top reinforcement is needed" in top["note"]


def test_service_combinations_follow_bnbc_2_7_2_for_nominal_wind() -> None:
    names = [name for name, _ in service_combinations(["D", "SD", "L", "Lr", "WX", "EY"])]
    assert names[:2] == ["D", "D + L + Lr"]
    assert "D + WX" in names and "D - WX" in names
    assert "D + 0.75L + 0.75Lr + 0.75WX" in names and "0.6D - WX" in names
    assert "D + 0.7EY" in names and "D + 0.75L + 0.75Lr - 0.525EY" in names
    assert "0.6D - 0.7EY" in names
    factors = dict(service_combinations(["D", "SD", "WX"]))["0.6D + WX"]
    assert factors == {"D": 0.6, "SD": 0.6, "WX": 1.0}
    # Strength-level wind (ASCE 7-16): 0.6W and 0.45W.
    strength_level = dict(service_combinations(["D", "L", "WY"], strength_level_wind=True))
    assert strength_level["D + 0.75L + 0.45WY"] == {"D": 1.0, "L": 0.75, "WY": 0.45}
    assert strength_level["0.6D - 0.6WY"] == {"D": 0.6, "WY": -0.6}


def test_uplifted_part_hogs_under_its_own_weight() -> None:
    # 100 kN with 100 kN·m on the 1.8 m footing under 1 m of soil, 0.9D: partial contact from
    # u = -195 mm; the overhang beyond the column face at -200 mm hangs from the rest.
    spec = square_footing()
    loads = {"0.9D + 1.0EX": [np.array([100 * KN, 0.0, 100 * KN * 1000])]}
    checks, notes = design_footing(
        spec, {}, loads, Foundation(groundLevel=0), dead={"0.9D + 1.0EX": 0.9}
    )
    top = by_name(checks)["Flexure X (top)"]
    w = 0.9 * (2400 * 9.80665 / 1e3 * 0.5 + 18 * 1.0)  # kPa, factored footing and soil
    assert top["demand"] == pytest.approx(w * 0.7**2 / 2, rel=0.01)
    # No top bars: plain concrete, 0.60 x 0.42 √f'c (h - 50)² / 6 per metre.
    assert top["capacity"] == pytest.approx(0.6 * 0.42 * 5 * 450**2 / 6 / 1e3, rel=1e-3)
    assert top["ok"] and "plain concrete" in top["note"]
    assert any("partial contact" in n for n in notes)
    # In full contact the weight balances its own pressure: the net factored pressure.
    gravity = {"1.2D": [np.array([1200 * KN, 0.0, 0.0])]}
    with_weight, _ = design_footing(spec, {}, gravity, Foundation(), dead={"1.2D": 1.2})
    without, _ = design_footing(spec, {}, gravity, Foundation())
    assert by_name(with_weight)["Flexure X (bottom)"]["demand"] == pytest.approx(
        by_name(without)["Flexure X (bottom)"]["demand"]
    )


# ─────────────────────────────── the analysed one-bay frame ───────────────────────────────

FOOTING_TYPES = [
    {
        "id": "F18",
        "name": "Footing 1800x1800x500",
        "kind": "footing",
        "material": "C24.1",
        "footingType": "isolated",
        "length": 1800,
        "width": 1800,
        "thickness": 500,
        "reinforcement": {
            "material": "B420DWR",
            "cover": 75,
            "bottomX": {"dia": 16, "spacing": 150},
            "bottomY": {"dia": 16, "spacing": 150},
        },
    },
    {
        "id": "CF",
        "name": "Combined footing 7800x1800x600",
        "kind": "footing",
        "material": "C24.1",
        "footingType": "combined",
        "length": 7800,
        "width": 1800,
        "thickness": 600,
        "reinforcement": {
            "material": "B420DWR",
            "cover": 75,
            "bottomX": {"dia": 16, "spacing": 150},
            "bottomY": {"dia": 16, "spacing": 150},
            "topX": {"dia": 16, "spacing": 150},
        },
    },
    {
        "id": "SF",
        "name": "Strip footing",
        "kind": "footing",
        "material": "C24.1",
        "footingType": "strip",
        "length": 6000,
        "width": 1000,
        "thickness": 400,
    },
]
OBJECTS_WITH_FOOTINGS = ObjectLibrary.model_validate(
    {
        "objects": [
            *OBJECTS.model_dump(mode="json", by_alias=True)["objects"],
            *FOOTING_TYPES,
        ]
    }
)
CORNERS = [(0, 0), (6000, 0), (6000, 5000), (0, 5000)]


def with_footings(*footings: FootingElement) -> BuildingModel:
    building = generate(PLAN, "s")
    return building.model_copy(update={"elements": [*building.elements, *footings]})


def footing(id: str, type: str, x: float, y: float, rotation: float = 0) -> FootingElement:
    return FootingElement(id=id, type=type, position=[x, y], elevation=-1000, rotation=rotation)


@pytest.fixture(scope="module")
def frame(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, Path]:
    """The one-bay frame analysed for all its static cases: (analysis model, results)."""
    root = tmp_path_factory.mktemp("footings")
    d = derive_fem(
        generate(PLAN, "s"), OBJECTS, default_material_library(), SETTINGS, {"bim": "abc"}
    )
    model = root / "08 FEM" / "model.osmodel"
    model.parent.mkdir(parents=True)
    model.write_text(json.dumps(d.project), encoding="utf-8")
    static = [a["id"] for a in d.project["analyses"] if a.get("type", "Static") == "Static"]
    out = root / "08 FEM" / "model.results"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *map(str, static or range(1, 9)),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    return d.project, out


def run_checks(
    frame: tuple[dict, Path], building: BuildingModel, settings: ProjectSettings | None = None
):
    project, out = frame
    return footing_checks(
        project,
        out,
        building,
        OBJECTS_WITH_FOOTINGS,
        default_material_library(),
        settings or SETTINGS.model_copy(update={"foundation": Foundation(allowableBearing=150)}),
    )


def test_isolated_footings_under_every_column(frame: tuple[dict, Path]) -> None:
    building = with_footings(
        *(footing(f"F{i + 1}", "F18", x, y) for i, (x, y) in enumerate(CORNERS))
    )
    elements, skipped, notes = run_checks(frame, building)
    json.dumps(elements)
    assert not skipped
    assert [e["id"] for e in elements] == ["F1", "F2", "F3", "F4"]
    for i, element in enumerate(elements):
        assert element["kind"] == "footing" and element["type"] == "F18"
        assert element["members"] == [f"C{i + 1}"]
        names = [c["name"] for c in element["checks"]]
        # The light corner columns carry large base moments: the weight of the footing and
        # the soil hogs the light side, which plain concrete carries (no top bars).
        # (Under gravity they may lift a part of the base: reported only, "Full contact under
        # gravity", which the sizing assistant avoids.)
        assert [
            n for n in names if not n.endswith("(top)") and not n.startswith("Full contact")
        ] == [
            "Bearing (service)",
            f"Punching at C{i + 1}",
            "One-way shear X",
            "One-way shear Y",
            "Flexure X (bottom)",
            "Flexure Y (bottom)",
            "Min. reinforcement X (bottom)",
            "Min. reinforcement Y (bottom)",
        ]
        checks = by_name(element["checks"])
        # Nearly full contact under the governing service combination: well within qa.
        bearing = checks["Bearing (service)"]
        assert bearing["ok"] and bearing["utilisation"] < 0.8
        assert element["ok"], [c for c in element["checks"] if not c["ok"]]
        for name in names:
            if name.endswith("(top)"):
                assert "plain concrete" in checks[name]["note"]
        assert checks["Bearing (service)"]["demand"] > 0
        assert checks["Bearing (service)"]["capacity"] == 150
        # A project combination, or one of its design wind load cases (BNBC Figure 6.2.9,
        # "<name> [Case 3 -WY]": the same combinations as 9 Substructure since 0.0.45).
        governing = checks[f"Punching at C{i + 1}"]["combination"]
        assert governing.split(" [Case ")[0] in [c.name for c in SETTINGS.combinations]
        assert all(c["demand"] >= 0 for c in element["checks"])
        assert element["utilisation"] == max(c["utilisation"] for c in element["checks"])
        assert element["ok"] == all(c["ok"] for c in element["checks"])
    assert not any("no footing under it" in n for n in notes)


def test_combined_footing_takes_the_resultant_of_its_columns(frame: tuple[dict, Path]) -> None:
    building = with_footings(
        footing("CF1", "CF", 3000, 0),
        footing("F3", "F18", 6000, 5000),
        footing("S1", "SF", 3000, 5000),
        footing("F9", "F18", 3000, 2500),  # under no column
    )
    elements, skipped, notes = run_checks(frame, building)
    by_id = {e["id"]: e for e in elements}
    assert sorted(by_id) == ["CF1", "F3"]
    combined = by_id["CF1"]
    assert combined["members"] == ["C1", "C2"]
    checks = by_name(combined["checks"])
    for name in (
        "Bearing (service)",
        "Punching at C1",
        "Punching at C2",
        "Flexure between columns (top)",
        "One-way shear X",
    ):
        assert name in checks, name
    # Columns 6 m apart on a 7.8 m footing: it hogs between them.
    assert checks["Flexure between columns (top)"]["demand"] > 0

    reasons = {s["id"]: s["reason"] for s in skipped}
    assert reasons == {
        "S1": "strip footings are not designed yet",
        "F9": "no column base lies within its plan outline",
    }
    # The strip S1 spans C3 and C4; C3 already stands on F3, the footing listed first.
    assert "C3: stands on more than one footing; taken by the first" in notes
    assert not any("no footing under it" in n for n in notes)


def test_column_without_footing_and_bearing_without_qa(frame: tuple[dict, Path]) -> None:
    building = with_footings(footing("F1", "F18", 0, 0))
    elements, _, notes = run_checks(frame, building, SETTINGS)
    assert [e["id"] for e in elements] == ["F1"]
    names = [c["name"] for c in elements[0]["checks"]]
    assert "Bearing (service)" not in names and "Punching at C1" in names
    assert any(n.startswith("F1: bearing not checked: enter the net allowable") for n in notes)
    assert {"C2: no footing under it", "C3: no footing under it", "C4: no footing under it"} <= set(
        notes
    )
    # A building without footings gives nothing to report.
    assert run_checks(frame, generate(PLAN, "s")) == ([], [], [])


# ─────────────────────────── qa from the soil report (Part 1) ───────────────────────────


def soil_text(layers: list[dict], x: float = 500, spt_from: int = 1500) -> str:
    """A soil report with one borehole BH-1 at (x, 0), ground at the datum, dry to 20 m, SPT
    N = 15 every 1.5 m from ``spt_from``."""
    return json.dumps(
        {
            "schema": "saengine.soilReport/1",
            "boreholes": [
                {
                    "id": "BH-1",
                    "x": x,
                    "y": 0,
                    "waterTable": 20000,
                    "depth": 20000,
                    "layers": layers,
                    "spt": [{"depth": d, "N": 15} for d in range(spt_from, 20001, 1500)],
                }
            ],
        }
    )


STIFF_CLAY = [
    {
        "top": 0,
        "bottom": 20000,
        "description": "Stiff clay",
        "soilType": "clay",
        "unitWeight": 19,
        "cu": 100,
        "E": 60,
    }
]


def run_with_soil(frame, building, soil: str, settings: ProjectSettings = SETTINGS):
    project, out = frame
    return footing_checks(
        project, out, building, OBJECTS_WITH_FOOTINGS, default_material_library(), settings, soil
    )


def test_qa_per_footing_from_the_soil_report(frame: tuple[dict, Path]) -> None:
    # F18 (1.8 x 1.8 x 0.5 m, top at -1.0 m) founded at -1.5 m: Df = 1.5 m below BH-1's ground,
    # on clay with cu = 100 kPa, undrained: qu - q = cu Nc sc dc with Nc = 5.14,
    # sc = 1 + (B/L)(Nq/Nc) = 1 + 1/5.14, dc = 1 + 0.4 Df/B = 1 + 0.4 x 1.5/1.8, FS = 3:
    hand = 100 * 5.14 * (1 + 1 / 5.14) * (1 + 0.4 * 1.5 / 1.8) / 3  # 272.9 kPa
    building = with_footings(footing("F1", "F18", 0, 0))
    elements, _, notes = run_with_soil(frame, building, soil_text(STIFF_CLAY))
    bearing = by_name(elements[0]["checks"])["Bearing (service)"]
    assert bearing["capacity"] == pytest.approx(hand, abs=0.05)
    assert "qa = 272.9 kPa from 1 Soil Report: BH-1, 0.5 m away, Df = 1.50 m" in bearing["note"]
    assert "shear governs" in bearing["note"]
    assert any(
        n.startswith("Allowable bearing pressures from 1 Soil Report: qa = min(") for n in notes
    )

    # The override of Project Settings wins, and the note gives the soil report's value.
    override = SETTINGS.model_copy(update={"foundation": Foundation(allowableBearing=150)})
    elements, _, notes = run_with_soil(frame, building, soil_text(STIFF_CLAY), override)
    bearing = by_name(elements[0]["checks"])["Bearing (service)"]
    assert bearing["capacity"] == 150
    assert "the override in Project Settings → Foundation" in bearing["note"]
    assert "1 Soil Report gives 273 kPa here (BH-1" in bearing["note"]
    assert not any(n.startswith("Allowable bearing pressures") for n in notes)


def test_net_pressure_takes_off_the_overburden_qa_is_net_of(frame: tuple[dict, Path]) -> None:
    # F18 founded at -1.5 m, BH-1's ground at the datum: qa is net of the clay's overburden
    # 19 x 1.5 = 28.5 kPa. With the finished ground at the datum too, the net pressure takes off
    # gamma Df = 18 x 1.5 = 27 kPa (the smaller). With the finished ground 1.0 m higher (site
    # fill), the gross pressure gains 18 x 1.0 = 18 kPa of soil above the footing, but only the
    # 28.5 kPa the soil qa allowed for comes off (not 18 x 2.5 = 45): net + 18 - 1.5 = +16.5 kPa.
    building = with_footings(footing("F1", "F18", 0, 0))
    same, _, _ = run_with_soil(frame, building, soil_text(STIFF_CLAY))
    filled = SETTINGS.model_copy(update={"foundation": Foundation(groundLevel=1000)})
    raised, _, notes = run_with_soil(frame, building, soil_text(STIFF_CLAY), filled)
    low = by_name(same[0]["checks"])["Bearing (service)"]
    high = by_name(raised[0]["checks"])["Bearing (service)"]
    assert high["capacity"] == low["capacity"]  # the same soil qa: Df below BH-1's ground
    # (The governing combination is in partial contact at the lower ground, so the 18 kPa
    # does not add in full to qmax there: the uniform pressure widens the contact, so qmax
    # rises by at most 16.5 kPa. Since bearing is checked under every wind case of BNBC Figure
    # 6.2.9 it is D + 0.75L + 0.75Lr - 0.5625WX - 0.5625WY [Case 3 -WY] at 14.2 kPa; taking
    # off 45 kPa instead would have lowered it.)
    assert "Case 3" in low["combination"]
    assert 12.0 <= high["demand"] - low["demand"] <= 18 - 1.5 + 0.1
    assert "net = gross - 27.0 kPa, the overburden γ Df below the finished ground" in low["note"]
    assert (
        "net = gross - 28.5 kPa, the overburden at the founding level below BH-1's"
        in (high["note"])
    )
    assert any(
        n.startswith("F1: the finished ground (Project Settings → Foundation, +1.00 m) is 1.00 m")
        and "fill above the borehole's ground is taken as a load" in n
        for n in notes
    )


def test_soil_report_without_qa_and_old_projects(frame: tuple[dict, Path]) -> None:
    building = with_footings(footing("F1", "F18", 0, 0))
    # Fill without any strength (no SPT in it either) right under the base: no qa.
    fill = [
        {"top": 0, "bottom": 3000, "description": "Fill", "soilType": "fill", "unitWeight": 17},
        {**STIFF_CLAY[0], "top": 3000},
    ]
    elements, _, notes = run_with_soil(frame, building, soil_text(fill, spt_from=4500))
    assert "Bearing (service)" not in by_name(elements[0]["checks"])
    note = next(n for n in notes if n.startswith("F1: bearing not checked"))
    assert "1 Soil Report gives no qa here (BH-1 gives none: layer 1 (fill): no strength" in note
    # ... and the override, when given, is used instead.
    override = SETTINGS.model_copy(update={"foundation": Foundation(allowableBearing=120)})
    elements, _, _ = run_with_soil(frame, building, soil_text(fill, spt_from=4500), override)
    assert by_name(elements[0]["checks"])["Bearing (service)"]["capacity"] == 120

    # The placeholder of an old project (or no soil report): qa from the settings as before.
    for text in ('{"schema": 1, "part": "soil"}', None):
        elements, _, notes = run_with_soil(frame, building, text, override)
        bearing = by_name(elements[0]["checks"])["Bearing (service)"]
        assert bearing["capacity"] == 120
        assert bearing["note"].endswith("qa = 120 kPa from Project Settings → Foundation")
        assert not any("Soil Report" in n for n in notes)


def test_soil_note_names_the_practice_of_the_soil_report() -> None:
    """The footing note says how qa was worked out with the soil report's own practice."""
    from saengine.design.footing import SoilBearing
    from saengine.library.settings import Foundation

    clay = [{"top": 0, "bottom": 20000, "description": "Stiff clay", "soilType": "clay", "cu": 80}]
    text = json.loads(soil_text(clay))
    textbook = SoilBearing(json.dumps(text), Foundation()).notes()
    text["design"] = {"practice": "bdConsultant"}
    consultant = SoilBearing(json.dumps(text), Foundation()).notes()
    assert "Bangladesh consultant practice" not in textbook[0]
    assert "Bangladesh consultant practice" in consultant[0]

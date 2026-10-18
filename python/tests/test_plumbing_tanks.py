"""RC water-retaining tanks (saengine.plumbing.tanks): loads, the shell model, design, stability.

Synthetic, hand-calculated data only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from saengine.plumbing.tanks import (
    GAMMA_W,
    Cracked,
    Soil,
    TankContext,
    TankOptions,
    combinations,
    crack_width,
    cracked_section,
    design_tank,
    face_cover,
    fctm,
    fctm_at,
    flotation,
    load_patterns,
    min_area,
    model_of,
    soil_of,
    support_loads,
    table_cover,
    tank_spec,
    tension_flexure,
    volumes,
    water_volume,
)
from saengine.plumbing.tanks_model import (
    M11,
    M22,
    Q23,
    combine,
    factors_key,
    run_tank,
    wall_panel,
)

GAMMA = 9810.0  # N/m³

UGT = {
    "id": "UGT",
    "kind": "underground",
    "story": None,
    "x": 0,
    "y": 0,
    "length": 4000,
    "width": 3000,
    "waterDepth": 2500,
    "freeboard": 300,
    "compartments": 1,  # one: the hand calculations have no partition
    "walls": 200,
    "base": 250,
    "roof": 150,
    "topLevel": 300,
    "construction": "rc",
}
OHT = {
    "id": "OHT",
    "kind": "overhead",
    "story": "Roof",
    "x": 0,
    "y": 0,
    "length": 3000,
    "width": 2500,
    "waterDepth": 1500,
    "freeboard": 300,
    "compartments": 1,  # one: the hand calculations have no partition
    "walls": 150,
    "base": 175,
    "roof": 125,
    "construction": "rc",
}


def soil_text(water_table: float = 2000) -> str:
    """One borehole of medium dense sand, γ 18 / γsat 20 kN/m³, φ' 32°, water at 2 m."""
    return json.dumps(
        {
            "schema": "saengine.soilReport/1",
            "boreholes": [
                {
                    "id": "BH-1",
                    "x": 0,
                    "y": 0,
                    "waterTable": water_table,
                    "depth": 20000,
                    "layers": [
                        {
                            "top": 0,
                            "bottom": 20000,
                            "description": "Medium dense sand",
                            "soilType": "sand",
                            "unitWeight": 18,
                            "saturatedUnitWeight": 20,
                            "phi": 32,
                        }
                    ],
                    "spt": [{"depth": d, "N": 20} for d in range(1500, 20001, 1500)],
                }
            ],
        }
    )


def context(tmp_path: Path, soil: str | None = None, **options) -> TankContext:
    return TankContext.build(None, soil, options, tmp_path)


# ───────────────────────────── the shell model against plates ─────────────────────────────


def test_cantilever_wall_strip_base_moment_and_shear(tmp_path: Path) -> None:
    # A wall 3 m high fixed at its base, free at the top, under water to its top: per metre,
    # M = γ h³ / 6 = 9.81 × 27 / 6 = 44.145 kN·m/m and V = γ h² / 2 = 44.145 kN/m at the base.
    # A long wall (12 m) bends cylindrically at its middle: the beam values there; a 1 m strip
    # with free sides gives them as the average over its width (statics).
    m_hand = GAMMA * 3**3 / 6
    v_hand = GAMMA * 3**2 / 2
    long = wall_panel(12.0, 3.0, 0.25, {"bottom": "fixed"}, GAMMA, tmp_path / "long")
    base = sorted((x, long.forces[n]) for n, (x, z) in long.coords.items() if z == 0)
    middle = min(base, key=lambda r: abs(r[0] - 6.0))[1]
    assert middle[M22] == pytest.approx(m_hand, rel=0.02)
    assert -middle[Q23] == pytest.approx(v_hand, rel=0.01)
    strip = wall_panel(1.0, 3.0, 0.25, {"bottom": "fixed"}, GAMMA, tmp_path / "strip")
    row = sorted((x, strip.forces[n]) for n, (x, z) in strip.coords.items() if z == 0)
    xs = np.array([x for x, _ in row])
    mean = np.trapezoid([f[M22] for _, f in row], xs) / 1.0
    assert mean == pytest.approx(m_hand, rel=0.02)
    # The reactions carry the whole pressure and its moment exactly.
    reactions = [strip.reactions[n] for n, (_, z) in strip.coords.items() if z == 0]
    assert -sum(r[1] for r in reactions) == pytest.approx(v_hand, rel=1e-6)
    assert sum(r[3] for r in reactions) == pytest.approx(m_hand, rel=1e-6)


def test_cantilever_moment_halfway_up(tmp_path: Path) -> None:
    # At z = 1.5 m the cantilever carries M = γ (h - z)³ / 6 = 9.81 × 1.5³ / 6 = 5.518 kN·m/m.
    long = wall_panel(12.0, 3.0, 0.25, {"bottom": "fixed"}, GAMMA, tmp_path, mesh=3 / 16)
    row = [
        (abs(x - 6.0), long.forces[n]) for n, (x, z) in long.coords.items() if abs(z - 1.5) < 1e-9
    ]
    middle = min(row, key=lambda r: r[0])[1]
    assert middle[M22] == pytest.approx(GAMMA * 1.5**3 / 6, rel=0.04)


def test_fixed_wall_panel_converges(tmp_path: Path) -> None:
    # A 4 × 3 m panel fixed on all four edges under water to its top: the base, top, side and
    # mid-height moments at 8 and 12 elements over the height are within 4 % and 2 % of those
    # at 16, and the
    # reactions add up to the pressure's resultant γ h² b / 2 = 9.81 × 9 × 4 / 2 = 176.58 kN.
    edges = dict.fromkeys(("bottom", "top", "left", "right"), "fixed")
    found = []
    for count in (8, 12, 16):
        r = wall_panel(4.0, 3.0, 0.25, edges, GAMMA, tmp_path / str(count), mesh=3.0 / count)

        def at(x: float, z: float, column: int, r=r) -> float:
            node = min(
                r.coords, key=lambda n: (r.coords[n][0] - x) ** 2 + (r.coords[n][1] - z) ** 2
            )
            return float(r.forces[node][column])

        found.append([at(2, 0, M22), at(2, 3, M22), at(0, 1.5, M11), at(2, 1.5, M22)])
        assert -sum(v[1] for v in r.reactions.values()) == pytest.approx(GAMMA * 9 * 4 / 2)
    fine = np.array(found[-1])
    assert np.allclose(found[0], fine, rtol=0.04)
    assert np.allclose(found[1], fine, rtol=0.02)
    # Hogging at the fixed edges (water face in tension), sagging at mid-height.
    assert fine[0] > 0 and fine[1] > 0 and fine[2] > 0 and fine[3] < 0


# ─────────────────────────────────────── loads ───────────────────────────────────────


def test_earth_pressure_at_rest_with_water_table() -> None:
    # Sand γ 18 / γsat 20 kN/m³, φ' 30°, water at 1 m, surcharge 10 kPa; at 3 m:
    # σ'v = 18 × 1 + (20 - 9.81) × 2 = 38.38 kPa, K0 = 1 - sin 30° = 0.5, u = 9.81 × 2 = 19.62,
    # σh = 0.5 (38.38 + 10) + 19.62 = 43.81 kPa.
    soil = Soil([(0.0, 10.0, 18.0, 20.0, 30.0)], 1.0, 10.0, 0.6, "test")
    assert soil.sigma_v_eff(3.0) == pytest.approx(38.38)
    assert soil.k0(3.0) == pytest.approx(0.5)
    assert soil.u(3.0) == pytest.approx(19.62)
    assert soil.lateral(3.0) == pytest.approx(0.5 * (38.38 + 10) + 19.62)
    assert soil.lateral(-0.2) == 0.0


def test_bnbc_combinations_with_the_fluid_and_earth() -> None:
    patterns = {"D": {}, "F": {}, "F1": {}, "F2": {}, "H": {}, "Lr": {}}
    combos = {c["name"]: c for c in combinations(None, patterns)}  # type: ignore[arg-type]
    assert combos["1.4D + 1.4F"]["factors"] == {"D": 1.4, "F": 1.4}
    assert combos["1.4D + 1.4F1"]["kind"] == "strength"
    assert combos["1.2D + 1.2F + 1.6H + 0.5Lr"]["bnbc"] == "2.7.3.1 (2)"
    assert combos["1.2D + 1.2F + 0.5Lr"]["bnbc"] == "2.7.3.1 (2), H = 0"
    assert combos["1.2D + 1.6H + 0.5Lr"]["bnbc"] == "2.7.3.1 (2), F = 0"
    assert combos["0.9D + 1.6H"]["factors"] == {"D": 0.9, "H": 1.6}
    assert combos["1.2D + 1.6Lr"]["bnbc"] == "2.7.3.1 (3)"
    assert combos["D + F"]["kind"] == "service"
    assert combos["D + H"]["kind"] == "service"
    # BNBC Sec 2.7.2.1 (7) 0.6D + W + H with W = 0: the reduced dead load against the uplift.
    assert combos["0.6D + H"]["factors"] == {"D": 0.6, "H": 1.0}
    assert combos["0.6D + H"]["kind"] == "service"


# ─────────────────────────────────────── design ───────────────────────────────────────


def test_tension_flexure_small_eccentricity_by_the_lever_rule() -> None:
    # h 200, both layers at d = 150 (ds = dc = 50 mm); N = 100 kN/m, M = 2 kN·m/m: e = 20 mm
    # lies between the bars: As = N (dc ± e) / (φ fy (ds + dc)) = 1e5 × 70 / (0.9 × 420 × 100)
    # = 185.2 and 1e5 × 30 / 37 800 = 79.4 mm²/m.
    found = tension_flexure(2e6, 1e5, 200, 150, 150, 27.6, 420)
    assert found.case == "small eccentricity"
    assert found.this == pytest.approx(1e5 * 70 / (0.9 * 420 * 100))
    assert found.other == pytest.approx(1e5 * 30 / (0.9 * 420 * 100))
    # Pure tension: half each.
    both = tension_flexure(0.0, 1e5, 200, 150, 150, 27.6, 420)
    assert both.this == pytest.approx(both.other) == pytest.approx(1e5 / (2 * 0.9 * 420))


def test_tension_flexure_large_eccentricity_by_hand() -> None:
    # M = 30 kN·m/m, N = 50 kN/m, d = 150, h = 200: Ms = M - N ds = 30e6 - 50e3 × 50 = 27.5e6;
    # a = d - √(d² - 2 Ms / (φ 0.85 f'c b)); As = 0.85 f'c b a / fy + N / (φ fy).
    ms = 30e6 - 50e3 * 50
    a = 150 - math.sqrt(150**2 - 2 * ms / (0.9 * 0.85 * 27.6 * 1000))
    hand = 0.85 * 27.6 * 1000 * a / 420 + 50e3 / (0.9 * 420)
    found = tension_flexure(30e6, 50e3, 200, 150, 150, 27.6, 420)
    assert found.case == "large eccentricity" and found.phi == 0.9
    assert found.this == pytest.approx(hand)


def test_cracked_section_in_bending_matches_the_transformed_section() -> None:
    # One layer (no compression bars): x = (-n As + √((n As)² + 2 b n As d)) / b,
    # σs = M / (As (d - x/3)), n = Es / Ec.
    es, ec, area, d, m = 200_000.0, 24_700.0, 754.0, 150.0, 15e6
    n = es / ec
    x = (-n * area + math.sqrt((n * area) ** 2 + 2 * 1000 * n * area * d)) / 1000
    found = cracked_section(m, 0.0, 200, d, area, 50, 0.0, es, ec)
    assert found is not None
    assert found.x == pytest.approx(x)
    assert found.sigma_s == pytest.approx(m / (area * (d - x / 3)))
    # Under pure tension the bars share it by the lever rule: σ = N / (A1 + A2) here.
    tension = cracked_section(0.0, 1e5, 200, 150, 754, 50, 754, es, ec)
    assert tension is not None and tension.x == -math.inf
    assert tension.sigma_s == pytest.approx(1e5 / (2 * 754))
    assert cracked_section(-5e6, 0.0, 200, 150, 754, 50, 754, es, ec) is None


def test_crack_width_by_hand() -> None:
    # EN 1992-1-1 7.3.4: h 200, d 150, c 44, Ø12 @ 150 (As 754), σs 200 MPa, x 40 mm,
    # fct,eff = 0.30 × 27.6^(2/3), Ec = 24 700, kt 0.4.
    fct = 0.30 * 27.6 ** (2 / 3)
    area = math.pi * 36 * 1000 / 150
    hc = min(2.5 * 50, (200 - 40) / 3, 100)  # 53.3 mm
    rho = area / (1000 * hc)
    alpha = 200_000 / 24_700
    strain = max((200 - 0.4 * fct / rho * (1 + alpha * rho)) / 200_000, 0.6 * 200 / 200_000)
    sr = 3.4 * 44 + 0.8 * 0.5 * 0.425 * 12 / rho  # 150 <= 5 (44 + 6): the formula applies
    found = crack_width(
        Cracked(200.0, 40.0, 0.0, 0.0), 200, 150, 44, 12, 150, area, fct, 200_000, 24_700
    )
    assert found["hc_ef"] == pytest.approx(hc)
    assert found["rho_eff"] == pytest.approx(rho)
    assert found["sr_max"] == pytest.approx(sr)
    assert found["wk"] == pytest.approx(sr * strain)
    assert 0.1 < found["wk"] < 0.25
    # Bars further apart than 5 (c + φ/2) = 250 mm: sr,max = 1.3 (h - x).
    wide = crack_width(
        Cracked(200.0, 40.0, 0.0, 0.0), 200, 150, 44, 12, 300, area / 2, fct, 200_000, 24_700
    )
    assert wide["sr_max"] == pytest.approx(1.3 * 160)


def test_minimum_reinforcement_and_tensile_strength() -> None:
    # fctm = 0.30 fck^(2/3); at 3 days βcc = exp(0.25 (1 - √(28/3))) = 0.598;
    # As,min = kc k fct,eff Act / fy = 1.0 × 1.0 × 0.598 fctm × 1000 × 100 / 420 per face.
    assert fctm(27.6) == pytest.approx(0.30 * 27.6 ** (2 / 3))
    beta = math.exp(0.25 * (1 - math.sqrt(28 / 3)))
    assert fctm_at(27.6, 3) == pytest.approx(beta * fctm(27.6))
    assert min_area(200, 27.6, 420, 3) == pytest.approx(beta * fctm(27.6) * 1e5 / 420)
    # k = 0.65 at 800 mm and over, linear from 1.0 at 300 mm.
    assert min_area(550, 27.6, 420, 28) == pytest.approx(0.825 * fctm(27.6) * 275e3 / 420)


def test_cover_by_bnbc_table_6_8_3(tmp_path: Path) -> None:
    # Severe exposure: 45 mm at 25 N/mm² (27.6 reads the 25 column), 40 at 30, 30 at 35;
    # below 25 N/mm² the table gives none for severe exposure.
    assert table_cover("severe", 27.6) == (45.0, None)
    assert table_cover("severe", 30.0)[0] == 40.0
    assert table_cover("moderate", 20.7)[0] == 40.0
    cover, note = table_cover("severe", 20.7)
    assert cover == 45.0 and note and "below" in note
    spec = tank_spec(UGT, context(tmp_path))
    options = TankOptions()
    assert face_cover(spec, "South", "inner", 12, options) == 45.0
    assert face_cover(spec, "Base", "bottom", 12, options) == 75.0  # cast against earth
    assert face_cover(spec, "South", "outer", 20, options) == 50.0  # Sec 8.1.7.2 (b)
    assert face_cover(spec, "South", "outer", 12, options) == 40.0


# ─────────────────────────────── stability and weights ───────────────────────────────


def test_flotation_of_an_empty_underground_tank_by_hand(tmp_path: Path) -> None:
    # 4 × 3 m inside, 2.8 m high, walls 200, base 250, roof 150, top 300 mm above the ground,
    # water table at the ground: the base's underside is 2.8 + 0.25 + 0.15 - 0.3 = 2.9 m deep.
    # U = 9.81 × 2.9 × 4.4 × 3.4 = 425.6 kN; concrete: walls 14.8 × 0.2 × 2.8 = 8.288, base
    # 4.4 × 3.4 × 0.25 = 3.74, roof 4.4 × 3.4 × 0.15 = 2.244 m³, × 24 = 342.5 kN; FS = 0.805.
    ctx = context(tmp_path)
    spec = tank_spec(UGT, ctx)
    soil = Soil([(0.0, 100.0, 18.0, 20.0, 30.0)], 0.0, 10.0, 0.6, "test")
    found = flotation(spec, soil, ctx.options)
    assert found["uplift"] == pytest.approx(9.81 * 2.9 * 4.4 * 3.4, abs=0.1)
    assert found["concrete"] == pytest.approx((8.288 + 3.74 + 2.244) * 24, abs=0.1)
    assert found["FS"] == pytest.approx(342.5 / 425.6, abs=0.002)
    assert not found["ok"]
    # A 500 mm toe all round carries the saturated soil over it (2.65 m × 20 kN/m³ = 53 kPa on
    # 5.4 × 4.4 - 4.4 × 3.4 = 8.8 m²) and the uplift acts on 5.4 × 4.4 m.
    toe = tank_spec({**UGT, "toe": 500}, ctx)
    found = flotation(toe, soil, ctx.options)
    concrete = (8.288 + 5.4 * 4.4 * 0.25 + 2.244) * 24
    assert found["soilOnToe"] == pytest.approx(53.0 * 8.8, abs=0.5)
    assert found["FS"] == pytest.approx(
        (concrete + 53.0 * 8.8) / (9.81 * 2.9 * 5.4 * 4.4), abs=0.002
    )
    assert found["ok"]


def test_overhead_tank_weights_by_hand(tmp_path: Path) -> None:
    # 3 × 2.5 m inside, water 1.5 m, freeboard 300, walls 150, base 175, roof 125:
    # walls (2 × 3.15 + 2 × 2.65) × 0.15 × 1.8 = 3.132, base 3.3 × 2.8 × 0.175 = 1.617, roof
    # 3.3 × 2.8 × 0.125 = 1.155 m³ -> 5.904 m³ × 24 = 141.70 kN + roof finish 1 kPa × 9.24 m²
    # = 150.9 kN empty; water 3 × 2.5 × 1.5 × 9.81 = 110.36 kN; full 261.3 kN.
    ctx = context(tmp_path)
    spec = tank_spec(OHT, ctx)
    assert volumes(spec)["concrete"] == pytest.approx(5.904)
    assert water_volume(spec) == pytest.approx(11.25)
    loads = support_loads(spec, ctx.options)
    assert loads["empty"] == pytest.approx(141.70 + 9.24, abs=0.1)
    assert loads["water"] == pytest.approx(11.25 * GAMMA_W, abs=0.1)
    assert loads["full"] == pytest.approx(150.94 + 110.36, abs=0.1)
    assert loads["roofLive"] == pytest.approx(9.24, abs=0.05)


# ─────────────────────────────────────── the API ───────────────────────────────────────


def test_design_overhead_tank(tmp_path: Path) -> None:
    result = design_tank({**OHT, "compartments": 2}, context(tmp_path))
    json.dumps(result)  # plain numbers for the RPC
    support = result["supportLoads"]
    lines = support["lines"]
    # The base's reactions on the supporting lines carry the water exactly and the concrete
    # within the model's centre-line idealisation (walls to the mid-planes).
    assert sum(row["F"] for row in lines) == pytest.approx(support["water"], rel=0.005)
    assert sum(row["D"] for row in lines) == pytest.approx(support["empty"], rel=0.03)
    assert {row["line"] for row in lines} == {"South", "North", "West", "East", "Partition 1"}
    names = {c["name"] for c in result["cases"]}
    assert {"1.4D + 1.4F", "1.4D + 1.4F1", "1.4D + 1.4F2", "D + F"} <= names
    # Every wall, face and direction designed, with bars and a crack width.
    walls = {(e["name"], e["direction"], e["face"]) for e in result["walls"]}
    assert ("Partition 1", "vertical", "east") in walls
    assert ("South", "horizontal", "inner") in walls
    for e in result["walls"] + result["base"] + result["roof"]:
        assert e["As_provided"] >= max(e["As_required"], e["As_min"]) - 1
        assert e["crackWidth"] <= e["crackLimit"]
    assert result["quantities"]["concrete"] == pytest.approx(5.904 + 2.5 * 0.15 * 1.8, abs=0.01)
    assert result["uplift"] is None and result["bearing"] is None


def test_design_underground_tank_with_the_soil_report(tmp_path: Path) -> None:
    result = design_tank(UGT, context(tmp_path, soil_text(2000), designWaterTable=None, ks=20000))
    json.dumps(result)
    # H at the base's mid-plane, 2.9 - 0.125 = 2.775 m below the ground, water at 2 m:
    # σ'v = 18 × 2 + 10.19 × 0.775 = 43.90 kPa, K0 = 1 - sin 32°, u = 9.81 × 0.775.
    k0 = 1 - math.sin(math.radians(32))
    hand = k0 * (18 * 2 + (20 - 9.81) * 0.775 + 10) + 9.81 * 0.775
    earth = next(load for load in result["loads"] if load["case"] == "H")
    assert earth["value"] == pytest.approx(hand, abs=0.05)
    uplift = next(load for load in result["loads"] if load["name"] == "Uplift on the base")
    assert uplift["value"] == pytest.approx(9.81 * 0.9, abs=0.01)
    assert result["uplift"]["head"] == pytest.approx(0.9)
    assert result["uplift"]["ok"]
    checks = {c["name"]: c for c in result["checks"]}
    assert "Flotation (empty, design water table)" in checks
    assert "Bearing pressure (net, full)" in checks
    assert "South: one-way shear (vertical span)" in checks
    # The empty tank backfilled bends the walls' outer face at the base; full, the inner one.
    outer = next(
        e
        for e in result["walls"]
        if e["name"] == "South" and e["direction"] == "vertical" and e["face"] == "outer"
    )
    inner = next(
        e
        for e in result["walls"]
        if e["name"] == "South" and e["direction"] == "vertical" and e["face"] == "inner"
    )
    assert "H" in outer["combination"]
    assert outer["Mu"] > 0 and inner["Mu"] > 0
    assert any("ks = 20000" in n for n in result["notes"])
    assert result["settlement"]["limit"] == 100.0  # sand: BNBC Table 6.3.8


def test_reinforcement_from_the_tank(tmp_path: Path) -> None:
    bars = {"dia": 16, "spacing": 125}
    tank = {
        **OHT,
        "reinforcement": {
            "walls": {f: {"vertical": bars, "horizontal": bars} for f in ("inner", "outer")},
            "base": {f: {"X": bars, "Y": bars} for f in ("top", "bottom")},
            "roof": {f: {"X": bars, "Y": bars} for f in ("top", "bottom")},
        },
    }
    result = design_tank(tank, context(tmp_path))
    for e in result["walls"] + result["base"] + result["roof"]:
        assert e["bars"] == "Ø16 @ 125" and e["barsFrom"] == "tank"


def test_soak_well_ring(tmp_path: Path) -> None:
    # Ø1.5 m inside, 100 mm ring, 3 m deep, top at the ground; sand φ' 30°, dry, q = 10 kPa:
    # p = 0.5 (18 × 3 + 10) = 32 kPa at the bottom, N = p r = 32 × 0.85 = 27.2 kN/m.
    well = {
        "id": "SW1", "kind": "soakWell", "diameter": 1500, "waterDepth": 2700,
        "freeboard": 300, "walls": 100, "topLevel": 0,
    }  # fmt: skip
    result = design_tank(well, context(tmp_path, designWaterTable=None))
    check = result["checks"][0]
    assert check["demand"] == pytest.approx(1.6 * 32 * 0.85, abs=0.05)
    assert check["capacity"] == pytest.approx(0.65 * 0.85 * 27.6 * 100, abs=0.1)


def test_equipment_entry_of_an_overhead_tank(tmp_path: Path) -> None:
    from saengine.library.mep import Equipment
    from saengine.plumbing.tanks import tank_equipment

    entry = tank_equipment(OHT, context(tmp_path))
    assert entry["operatingWeight"] == pytest.approx(261.3, abs=0.1)
    assert entry["emptyWeight"] == pytest.approx(150.9, abs=0.1)
    assert (entry["length"], entry["width"]) == (3300, 2800)
    Equipment.model_validate(entry)  # the existing equipment model takes it as it is


def test_open_tank_has_no_roof(tmp_path: Path) -> None:
    spec = tank_spec({**OHT, "roof": 0}, context(tmp_path))
    assert spec.roof is None
    assert volumes(spec)["roof"] == 0.0
    assert tank_spec({**OHT, "roof": None}, context(tmp_path)).roof == pytest.approx(0.125)


# ─────────────────────────────── uplift and the base's shear ───────────────────────────────


def _uplift_run(tmp_path: Path, ks: float, **tank):
    ctx = context(tmp_path, soil_text(2000), designWaterTable=0.0, ks=ks / 1e3)
    spec = tank_spec({**UGT, **tank}, ctx)
    model = model_of(spec, ks / 1e3, ctx.options)
    patterns, _ = load_patterns(spec, model, soil_of(spec, ctx), ctx.options)
    combos = {c["name"]: c["factors"] for c in combinations(spec, patterns)}
    return model, patterns, run_tank(model.box, model.grid, patterns, tmp_path / "run", combos)


def _centre(model, values: dict) -> np.ndarray:
    grid = model.grid
    cx, cy = grid.xs[-1] / 2, grid.ys[-1] / 2
    node = min(
        values, key=lambda n: (grid.coords[n - 1][0] - cx) ** 2 + (grid.coords[n - 1][1] - cy) ** 2
    )
    return values[node]


def test_base_under_net_uplift_spans_between_the_walls(tmp_path: Path) -> None:
    # The UGT tank empty, water at the ground: uplift u = 9.81 × 2.9 = 28.45 kPa on the base
    # against its weight 0.25 × 24 = 6 kPa; 0.9D + 1.6H gives a net upward 1.6 × 28.45 -
    # 0.9 × 6 = 40.1 kPa and the tank floats (W 342.5 < U 425.6 kN). Linear springs pulling
    # would hold the base where it is and leave it almost unbent (about 1 kN·m/m at the centre).
    # Held along the walls' lines instead, the base spans 3.2 m (centre lines) by 4.2 m: at the
    # centre, between a clamped plate (≈ 0.033 q a² = 13.5 kN·m/m for b/a = 1.31) and a simply
    # supported one (≈ 0.069 q a² = 28.5): the walls' joints are partly fixed (Timoshenko's plate
    # coefficients, from memory: the test asserts the bounds 0.02 q a² and q a² / 8).
    model, patterns, results = _uplift_run(tmp_path, 20000e3)
    assert "0.9D + 1.6H" in results.floating
    q, a = 1.6 * 9.81 * 2.9 - 0.9 * 6.0, 3.2
    base = combine(results, {"D": 0.9, "H": 1.6})["Base"]
    m_short = abs(_centre(model, base)[M22]) / 1e3
    assert 0.02 * q * a**2 < m_short < q * a**2 / 8
    assert max(abs(v[M22]) for v in base.values()) / 1e3 < q * a**2 / 8
    # The rerun carries its load: the supports' reactions balance the net upward load.
    own = results.direct[factors_key({"D": 0.9, "H": 1.6})]
    net = sum(f[2] * 0.9 for f in patterns["D"].values()) + sum(
        f[2] * 1.6 for f in patterns["H"].values()
    )
    assert -sum(r[2] for r in results.reactions[own].values()) == pytest.approx(net, rel=1e-6)


def test_compression_only_springs_where_the_base_lifts_off(tmp_path: Path) -> None:
    # On stiff ground (ks 200 MN/m³) with an 800 mm toe holding the tank down, the superposed
    # 1.2D + 1.6H + 0.5Lr lifts the base's middle off (the walls press its edges down): rerun
    # with compression-only springs, the springs pull nowhere, the reactions still balance the
    # load, and the base bends more at its centre than on linear springs.
    model, patterns, results = _uplift_run(tmp_path, 200000e3, toe=800)
    name = "1.2D + 1.6H + 0.5Lr"
    assert name in results.lifted
    factors = {"D": 1.2, "H": 1.6, "Lr": 0.5}
    own = results.direct.pop(factors_key(factors))  # the linear superposition below
    count = len(model.grid.coords)
    springs = [r[2] for n, r in results.reactions[own].items() if n > count]
    assert min(springs) > -1.0  # N: the ground nodes' reactions, + under compression
    net = sum(f[2] * v for k, v in factors.items() for f in patterns[k].values())
    assert -sum(r[2] for r in results.reactions[own].values()) == pytest.approx(net, rel=1e-6)
    linear = _centre(model, combine(results, factors)["Base"])[M22]
    nonlinear = _centre(model, results.panels[own]["Base"])[M22]
    assert abs(nonlinear) > abs(linear) * 1.1


def test_base_shear_reads_the_interior_lines_mesh_independently(tmp_path: Path) -> None:
    # The base's shear on its edge lines (on the walls' joints) is the shells' joint shear, not
    # the slab's one-way shear, and grew from 35 to 59 kN/m on refining the mesh; on the
    # interior lines it settles (about 24-26 kN/m at d from the walls' faces).
    found = []
    for mesh in (None, 0.2):
        opts = {"designWaterTable": None, "ks": 20000} | ({"mesh": mesh} if mesh else {})
        result = design_tank(UGT, context(tmp_path / str(mesh), soil_text(2000), **opts))
        checks = {c["name"]: c for c in result["checks"]}
        found.append([checks[f"Base: one-way shear ({d} span)"]["demand"] for d in "XY"])
    assert np.allclose(found[0], found[1], rtol=0.05)
    assert all(v < 40 for v in found[0])

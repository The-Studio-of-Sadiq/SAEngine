"""Stair design (saengine.design.stairs) checked by hand: a 3.0 m flight, the BNBC geometry
rules, a dog-legged half landing carrying two flights, the design mode's bars and the report
over 06 BIM stairs. Synthetic data only."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from saengine.design import stairs as S
from saengine.library.materials import Material
from saengine.library.objects import Staircase
from saengine.library.settings import default_project_settings

GAMMA = 2400 * 9.80665 / 1000  # kN/m³
FC, FY = 25.0, 420.0
MATERIAL = S.StairMaterial(FC, FY, steel="RB420")
LOADS = S.StairLoads(1.2, 4.8, S.gravity_combinations())


def hand_area(mu: float, d: float) -> float:
    """As [mm²/m] for mu [kN·m/m], φ = 0.90, b = 1000 mm (textbook closed form)."""
    rn = mu * 1e6 / (0.9 * 1000 * d**2)
    rho = 0.85 * FC / FY * (1 - math.sqrt(1 - 2 * rn / (0.85 * FC)))
    return rho * 1000 * d


def flight_spec(**kw) -> S.StairSpec:
    base = {
        "waist": 150.0,
        "riser": 165.0,
        "tread": 250.0,
        "width": 1200.0,
        "spanning": "betweenBeams",
        "support_width": 250.0,
    }
    base.update(kw)
    return S.StairSpec(**base)


# ─────────────────────────── a 3.0 m flight: waist 150, R 165, T 250 ───────────────────────────


def test_flight_by_hand():
    # 12 risers of 165 mm: going 11 x 250 = 2750 mm, span c/c beams 2750 + 250 = 3000 mm
    spec = flight_spec()
    geometry = S.stair_geometry(spec, 12 * 165.0)
    (flight,) = geometry.flights
    assert flight.risers == 12 and flight.going == 2750 and flight.span == 3000
    cos = 250 / math.sqrt(165**2 + 250**2)  # 0.83461
    assert flight.cos == pytest.approx(cos)
    mean = 150 / cos + 165 / 2  # 179.72 + 82.5 = 262.22 mm
    assert flight.mean_thickness(150) == pytest.approx(mean)
    assert mean == pytest.approx(262.22, abs=0.01)

    dead = GAMMA * mean / 1000 + 1.2  # 6.172 + 1.2 = 7.372 kN/m²
    wu = 1.2 * dead + 1.6 * 4.8  # 16.53 kN/m² (1.4D = 10.32 does not govern)
    assert wu == pytest.approx(16.526, abs=1e-3)
    demand = S.flight_demand(flight, spec, MATERIAL, LOADS)
    assert demand.wu == pytest.approx(wu)
    assert demand.mu == pytest.approx(wu * 3.0**2 / 8)  # 18.59 kN·m/m
    assert demand.mu == pytest.approx(18.592, abs=1e-3)
    assert demand.vu == pytest.approx(wu * 3.0 / 2)  # 24.79 kN/m
    assert demand.mu_top == 0
    assert demand.combination == "1.2D + 1.6L"
    assert demand.reactions["L"]["bottom"] == pytest.approx(4.8 * 1.5)

    # Ø12: d = 150 - 20 - 6 = 124 mm; As = 410 mm²/m > As,min 0.0018 x 150 000 = 270
    need = S.need_of([demand], 20.0, MATERIAL)
    hand = hand_area(demand.mu, 124.0)
    assert hand == pytest.approx(410.1, abs=0.5)
    assert need.main[12.0] == pytest.approx(hand, rel=1e-4)
    assert need.distribution == pytest.approx(270.0)
    pick = S.propose(need, "RB420", 20.0, diameters=(10.0, 12.0))
    # 113.1 x 1000 / 410.1 = 275.8 -> 275 mm (25 mm steps); distribution Ø10: 78.5/270 -> 275
    assert pick.reinforcement["main"] == {"dia": 12.0, "spacing": 275.0}
    assert pick.reinforcement["distribution"] == {"dia": 10.0, "spacing": 275.0}
    assert "top" not in pick.reinforcement and "landing" not in pick.reinforcement


def test_flight_checks_of_entered_bars():
    bars = S.StairBars("RB420", 20.0, S.Mesh(12, 275), S.Mesh(10, 275))
    spec = flight_spec(bars=bars)
    (flight,) = S.stair_geometry(spec, 1980.0).flights
    demand = S.flight_demand(flight, spec, MATERIAL, LOADS)
    checks = {c["name"]: c for c in S.part_checks(demand, bars, MATERIAL)}
    flexure = checks["F1: flexure (bottom)"]
    as_ = math.pi * 36 * 1000 / 275  # 411.3 mm²/m
    a = as_ * FY / (0.85 * FC * 1000)
    phi_mn = 0.9 * as_ * FY * (124 - a / 2) / 1e6
    assert flexure["capacity"] == pytest.approx(phi_mn, abs=0.01)
    assert flexure["ok"] and flexure["utilisation"] == pytest.approx(18.592 / phi_mn, abs=2e-3)
    shear = checks["F1: one-way shear"]
    assert shear["capacity"] == pytest.approx(0.75 * 0.17 * 5 * 124, abs=0.01)  # 79.05 kN/m
    assert shear["ok"]
    assert checks["F1: max. spacing (main)"]["capacity"] == 450  # min(3 x 150, 450)
    assert checks["F1: min. reinforcement"]["ok"]
    # Table 6.6.1: 3000 / 20 = 150 mm; going 2750 ≥ 60% of 3000 -> / 1.15 = 130.4 mm
    thickness = checks["F1: min. thickness (Table 6.6.1)"]
    assert thickness["demand"] == pytest.approx(3000 / 20 / 1.15, abs=0.01)
    assert thickness["flag"] and thickness["ok"]

    thin = S.StairBars("RB420", 20.0, S.Mesh(10, 300), S.Mesh(8, 400))
    checks = {c["name"]: c for c in S.part_checks(demand, thin, MATERIAL)}
    assert not checks["F1: flexure (bottom)"]["ok"]
    assert not checks["F1: distribution steel"]["ok"]  # 125.7 < 270 mm²/m


def test_continuous_ends_need_top_bars():
    spec = flight_spec(bottom_end="continuous", top_end="continuous")
    (flight,) = S.stair_geometry(spec, 1980.0).flights
    demand = S.flight_demand(flight, spec, MATERIAL, LOADS)
    assert demand.mu_top == pytest.approx(demand.wu * 9 / 10)
    assert demand.continuous_ends == 2
    bars = S.StairBars("RB420", 20.0, S.Mesh(12, 250), S.Mesh(10, 250))
    checks = {c["name"]: c for c in S.part_checks(demand, bars, MATERIAL)}
    assert not checks["F1: flexure (top, supports)"]["ok"]
    with_top = S.StairBars("RB420", 20.0, S.Mesh(12, 250), S.Mesh(10, 250), S.Mesh(12, 250))
    checks = {c["name"]: c for c in S.part_checks(demand, with_top, MATERIAL)}
    assert checks["F1: flexure (top, supports)"]["ok"]
    # Table 6.6.1 both ends continuous: l/28
    assert checks["F1: min. thickness (Table 6.6.1)"]["demand"] == pytest.approx(
        3000 / 28 / 1.15, abs=0.01
    )


def test_spans_by_bnbc_6_7_1_1():
    rise = 12 * 165.0
    edges = S.stair_geometry(flight_spec(spanning="landingEdges", landing_length=1500), rise)
    assert edges.flights[0].span == 2750 + 2 * 750  # landing/2 < 1.0 m
    wide = S.stair_geometry(flight_spec(spanning="landingEdges", landing_length=2400), rise)
    assert wide.flights[0].span == 2750 + 2 * 1000  # capped at 1.0 m
    along = S.stair_geometry(flight_spec(spanning="withLandings", landing_length=1200), rise)
    assert along.flights[0].span == 1200 + 2750 + 1200 + 250
    three = S.stair_geometry(flight_spec(spanning="landingsThreeSides"), rise)
    assert three.flights[0].span == 2750
    with pytest.raises(ValueError):
        S.stair_geometry(flight_spec(spanning="cantilever"), rise)


def test_flight_with_landings_patches():
    # (c): landing 1200 + going 2750 + landing 1200, supports 250: span 5400 mm with the lighter
    # landing load on 1.325 m at each end, the flight load between
    spec = flight_spec(spanning="withLandings", landing_length=1200)
    (flight,) = S.stair_geometry(spec, 1980.0).flights
    demand = S.flight_demand(flight, spec, MATERIAL, LOADS)
    wf = 1.2 * (GAMMA * flight.mean_thickness(150) / 1000 + 1.2) + 1.6 * 4.8
    wl = 1.2 * (GAMMA * 0.150 + 1.2) + 1.6 * 4.8
    # symmetric: R = wl 1.325 + wf 2.75 / 2, M at mid = R 2.7 - wl 1.325 (2.7 - 0.6625)
    # - wf 1.375² / 2
    r = wl * 1.325 + wf * 2.75 / 2
    m = r * 2.7 - wl * 1.325 * (2.7 - 0.6625) - wf * 1.375**2 / 2
    assert demand.vu == pytest.approx(r)
    assert demand.mu == pytest.approx(m)


# ─────────────────────────── a dog-legged half landing carrying two flights ───────────────────────────


def test_dog_legged_landing_carries_two_flights():
    # rise 3200 = 20 risers of 160, two flights of 10; tread 300: going 2700 = the span (d)
    spec = S.StairSpec(
        waist=150,
        riser=160,
        tread=300,
        width=1200,
        arrangement="dogLegged",
        spanning="landingsThreeSides",
        landing_length=1200,
        support_width=250,
        well=100,
    )
    geometry = S.stair_geometry(spec, 3200.0)
    assert [f.risers for f in geometry.flights] == [10, 10]
    f1 = geometry.flights[0]
    assert f1.going == 2700 and f1.span == 2700
    assert f1.cos == pytest.approx(300 / 340)
    assert f1.mean_thickness(150) == pytest.approx(250.0)  # 170 + 80
    (landing,) = geometry.landings
    assert landing.span == 2 * 1200 + 100 + 250  # 2750 mm
    assert landing.flights == (("F1", 125, 1325), ("F2", 1425, 2625))

    flights = {f.name: S.flight_demand(f, spec, MATERIAL, LOADS) for f in geometry.flights}
    wf = 1.2 * (GAMMA * 0.250 + 1.2) + 1.6 * 4.8  # 16.18 kN/m²
    assert flights["F1"].wu == pytest.approx(wf)
    assert flights["F1"].mu == pytest.approx(wf * 2.7**2 / 8)
    assert flights["F1"].mu_top == pytest.approx(wf * 2.7**2 / 8)  # (d): ± wl²/8
    reaction = wf * 2.7 / 2  # 21.84 kN per m of flight width
    assert reaction == pytest.approx(21.844, abs=1e-3)

    demand = S.landing_demand(landing, flights, spec, MATERIAL, LOADS)
    own = 1.2 * (GAMMA * 0.150 + 1.2) + 1.6 * 4.8  # 13.36 kN/m²
    q = reaction / 1.2  # spread over the landing depth: 18.20 kN/m per metre strip
    left = (own * 2.75 + 2 * q * 1.2) / 2
    mid = left * 1.375 - own * 1.375**2 / 2 - q * 1.2 * (1.375 - 0.725)
    assert mid == pytest.approx(28.463, abs=1e-3)
    assert demand.mu == pytest.approx(mid)
    assert demand.vu == pytest.approx(left)
    assert demand.kind == "landing" and demand.h == 150

    need = S.need_of([*flights.values(), demand], 20.0, MATERIAL, (10.0, 12.0))
    assert need.landing[12.0] == pytest.approx(hand_area(mid, 124.0), rel=1e-4)
    assert need.top  # support moments of (d)
    pick = S.propose(need, "RB420", 20.0, (10.0, 12.0))
    assert set(pick.reinforcement) >= {"main", "distribution", "top", "landing"}
    landing_mesh = pick.reinforcement["landing"]
    assert math.pi * landing_mesh["dia"] ** 2 / 4 * 1000 / landing_mesh["spacing"] >= min(
        need.landing[landing_mesh["dia"]], 1e9
    )


def test_landing_edges_landing_not_counted_twice():
    # (b): straight flight of 12 risers, landing 1200 deep: 600 mm of it inside the flight's
    # span (min(1200/2, 1000)); landing L0 spans 1200 + 250 = 1450 mm, the flight on 125-1325
    one = S.StairLoads(1.2, 4.8, (("1.2D + 1.6L", 1.2, 1.6),))
    spec = flight_spec(spanning="landingEdges", landing_length=1200)
    geometry = S.stair_geometry(spec, 12 * 165.0)
    (flight,) = geometry.flights
    assert flight.span == 2750 + 2 * 600
    flights = {"F1": S.flight_demand(flight, spec, MATERIAL, one)}
    l0 = geometry.landings[0]
    assert l0.span == 1450 and l0.flights == (("F1", 125, 1325),)
    demand = S.landing_demand(l0, flights, spec, MATERIAL, one)
    ends = flights["F1"].reactions
    r = 1.2 * ends["D"]["bottom"] + 1.6 * ends["L"]["bottom"]  # kN per m of flight width
    own = 1.2 * (GAMMA * 0.150 + 1.2) + 1.6 * 4.8  # 13.36 kN/m²
    # under the flight: its reaction over the 1.2 m depth plus the landing's own load on the
    # 600 mm not already in the flight's span: r / 1.2 + own (1 - 0.5)
    q = r / 1.2 - own * 0.5
    left = (own * 1.45 + q * 1.2) / 2
    mid = left * 0.725 - own * 0.725**2 / 2 - q * 0.6 * 0.3
    assert demand.vu == pytest.approx(left)
    assert demand.mu == pytest.approx(mid)
    assert any("not counted twice" in n for n in demand.notes)


def test_flight_without_going_is_skipped():
    # dog-legged, rise 320 = 2 risers of 160: two flights of one riser, going 0 (case (d) span 0)
    spec = S.StairSpec(
        waist=150,
        riser=160,
        tread=300,
        width=1200,
        arrangement="dogLegged",
        spanning="landingsThreeSides",
        landing_length=1200,
    )
    with pytest.raises(ValueError, match="no going"):
        S.stair_geometry(spec, 320.0)
    with pytest.raises(ValueError):
        S.simple_beam(0.0, [(0, 1, 1.0)])
    stair = SimpleNamespace(
        id="ST",
        kind="staircase",
        material="C25",
        waistThickness=150,
        riser=160,
        tread=300,
        flightWidth=1200,
        reinforcement=None,
        arrangement="dogLegged",
        spanning="landingsThreeSides",
        landingLength=1200,
    )
    building = _building()
    building.stories[1].elevation = 320.0
    building.additions.stairs = building.additions.stairs[:1]
    report = S.stair_report(building, {"ST": stair}, MATERIALS, None)
    assert report["elements"] == []
    assert "no going" in report["skipped"][0]["reason"]


def test_dog_legged_between_beams_landing_note():
    spec = S.StairSpec(
        waist=150, riser=160, tread=300, width=1200, arrangement="dogLegged", landing_length=1200
    )
    checks, notes = _checks(spec, 3200.0)
    assert "Landing depth" in checks
    assert any("half landing" in n and "not designed" in n for n in notes)
    _, notes = _checks(S.StairSpec(**{**spec.__dict__, "spanning": "landingsThreeSides"}), 3200.0)
    assert not any("half landing" in n for n in notes)


def test_simple_beam_patch_exact():
    beam = S.simple_beam(4.0, [(0, 4, 10.0)])
    assert beam.left == pytest.approx(20) and beam.moment == pytest.approx(20.0)
    # a patch over the left half: R_A = 15, zero shear at 1.5 m, M = 11.25
    beam = S.simple_beam(4.0, [(0, 2, 10.0)])
    assert beam.left == pytest.approx(15) and beam.at == pytest.approx(1.5)
    assert beam.moment == pytest.approx(11.25)


# ─────────────────────────── geometry checks ───────────────────────────


def _checks(spec, rise, use="residential"):
    checks, notes = S.geometry_checks(spec, S.stair_geometry(spec, rise), use)
    return {c["name"].split(" (")[0]: c for c in checks}, notes


def test_geometry_failing():
    # 2 x 165 + 250 = 580 < 610; a 1000 mm flight below 1120; a straight flight of 3960 mm
    spec = flight_spec(width=1000, spanning="withLandings", landing_length=900)
    checks, notes = _checks(spec, 24 * 165.0)
    assert not checks["2R + T"]["ok"]
    assert checks["2R + T"]["utilisation"] == pytest.approx(610 / 580, abs=1e-3)
    assert not checks["Stair width"]["ok"]
    assert not checks["Flight rise"]["ok"] and checks["Flight rise"]["demand"] == 3960
    assert not checks["Landing depth"]["ok"]  # 900 < 1000
    assert checks["Tread for the riser"]["flag"]  # table: 165 -> 311 mm, reported
    assert not checks["Tread for the riser"]["ok"]
    assert any("headroom not entered" in n for n in notes)
    # risers as built: 3200 / 20 = 160 exactly; 3200 / round(3200 / 175) = 3200 / 18 = 177.8
    built = "Riser as built against the type's riser"
    checks, _ = _checks(flight_spec(riser=160, tread=300), 3200.0)
    assert checks[built]["ok"] and checks[built]["demand"] == 0
    checks, _ = _checks(flight_spec(riser=175, tread=280), 3200.0)
    assert checks[built]["demand"] == pytest.approx(2.78, abs=0.01)
    checks, _ = _checks(flight_spec(riser=150, tread=300), 3500.0)  # 23 risers: 152.2
    assert checks[built]["ok"]
    # 1500 / round(1500 / 175) = 1500 / 9 = 166.7: 8.3 mm off the type's riser, but all risers
    # are equal (Part 4 Sec 3.10.6 met): a flag, not a failure
    checks, _ = _checks(flight_spec(riser=175, tread=280), 1500.0)
    assert checks[built]["demand"] == pytest.approx(8.33, abs=0.01)
    assert checks[built]["flag"] and not checks[built]["ok"]
    assert "3.10.6" not in built
    checks, _ = _checks(flight_spec(riser=240, tread=300), 3360.0)  # 14 risers of 240
    assert not checks["Riser height"]["ok"]


def test_geometry_passing():
    # dog-legged, 20 risers of 160, tread 300: 2R + T = 620; flights of 1600 mm; width 1200;
    # half landing 1200; headroom 2200
    spec = S.StairSpec(
        waist=150,
        riser=160,
        tread=300,
        width=1200,
        arrangement="dogLegged",
        spanning="landingsThreeSides",
        landing_length=1200,
        headroom=2200,
    )
    checks, notes = _checks(spec, 3200.0)
    strength = [c for c in checks.values() if not c["flag"]]
    assert all(c["ok"] for c in strength), [c["name"] for c in strength if not c["ok"]]
    assert checks["2R + T"]["demand"] == 620
    assert checks["Headroom"]["ok"]
    assert not notes
    # assembly: flights at most 2440 mm; a 2.10 m headroom is the reduced 2.03 m (flagged)
    low = S.StairSpec(**{**spec.__dict__, "headroom": 2100.0})
    checks, _ = _checks(low, 3200.0, "assembly")
    assert checks["Headroom"]["flag"] and checks["Headroom"]["ok"]
    assert checks["Flight rise"]["capacity"] == 2440
    _, notes = _checks(spec, 3200.0, "office")
    assert any("Table 4.3.6 gives no width" in n for n in notes)


def test_minimum_width_and_table():
    assert S.minimum_width("healthcare")[0] == 2235
    assert S.minimum_width("educational", 200)[0] == 2235
    assert S.minimum_width("educational")[0] == 1120
    assert S.table_tread(165) == 311 and S.table_tread(229) == 203
    assert S.table_tread(162) == pytest.approx(330 + (311 - 330) * 3 / 6)


# ─────────────────────────── loads and the report over 06 BIM ───────────────────────────


def test_loads_from_settings():
    settings = default_project_settings()
    loads = S.loads_from_settings(settings)
    assert loads.live == 4.8 and loads.finish == 1.2
    names = [c[0] for c in loads.combinations]
    assert "1.4D" in names and "1.2D + 1.6L + 0.5Lr" in names
    assert all(not any(k in n for k in ("W", "E")) for n in names)
    bare = S.loads_from_settings(None)
    assert bare.live == S.LIVE_STAIRS and bare.combinations == S.gravity_combinations()
    # an apartment building with the stairs at 2.0 kN/m² is warned: Table 6.2.3's 2.00 row is
    # for one- and two-family residences only
    stairs = next(a for a in settings.areaLoads if a.use == "stairs")
    low = settings.model_copy(
        update={
            "areaLoads": [
                a.model_copy(update={"live": 2.0}) if a is stairs else a for a in settings.areaLoads
            ],
            "occupancy": settings.occupancy.model_copy(update={"use": "residential"}),
        }
    )
    source = S.loads_from_settings(low).source
    assert "below BNBC Table 6.2.3" in source and "one- and two-family" in source


MATERIALS = {
    "C25": Material(
        id="C25",
        name="Concrete 25",
        category="concrete",
        mechanical={"E": 23500, "nu": 0.2, "density": 2400},
        concrete={"fc": 25},
    ),
    "RB420": Material(
        id="RB420", name="Bars 420", category="rebar", mechanical={"E": 200000}, steel={"fy": 420}
    ),
}


def _building(stair_type: str = "ST"):
    return SimpleNamespace(
        stories=[
            SimpleNamespace(id="B", elevation=0.0),
            SimpleNamespace(id="L1", elevation=3200.0),
        ],
        additions=SimpleNamespace(
            stairs=[
                SimpleNamespace(id="S1", type=stair_type, base="B", top="L1"),
                SimpleNamespace(id="S2", type=stair_type, base="L1", top="B"),
            ]
        ),
    )


def test_report_and_proposal():
    bars = {
        "material": "RB420",
        "cover": 20,
        "main": {"dia": 12, "spacing": 150},
        "distribution": {"dia": 10, "spacing": 200},
    }
    stair = Staircase(
        id="ST",
        name="Stair",
        material="C25",
        waistThickness=150,
        riser=160,
        tread=300,
        flightWidth=1200,
        reinforcement=bars,
    )
    collect: dict = {}
    report = S.stair_report(
        _building(), {"ST": stair}, MATERIALS, default_project_settings(), collect
    )
    (entry,) = report["elements"]
    assert entry["id"] == "S1" and entry["kind"] == "staircase" and entry["members"] == []
    # defaults: one straight flight between floor beams (a): 19 x 300 + 250 = 5950 mm
    assert entry["flights"][0]["span"] == 19 * 300 + 250
    failed = {c["name"].split(" (")[0] for c in entry["checks"] if not c["ok"]}
    assert "F1: flexure" in failed and not entry["ok"]
    assert [s["id"] for s in report["skipped"]] == ["S2"]  # top below base
    (proposal,) = S.proposal_entries(collect["stairs"])
    assert proposal["kind"] == "staircase" and proposal["members"] == ["S1"]
    assert proposal["status"] == "ok" and proposal["proposed"]["main"]["dia"] == 16

    # dog-legged with landings on three sides: two 2.7 m flights and a 2.75 m half landing
    dog = stair.model_copy(
        update={
            "arrangement": "dogLegged",
            "spanning": "landingsThreeSides",
            "landingLength": 1200,
            "wellWidth": 100,
        }
    )
    collect = {}
    report = S.stair_report(
        _building(), {"ST": dog}, MATERIALS, default_project_settings(), collect
    )
    (entry,) = report["elements"]
    assert [p["name"] for p in entry["parts"]] == ["F1", "F2", "L1"]
    failed = {c["name"] for c in entry["checks"] if not c["ok"] and not c["flag"]}
    assert failed == {"F1: flexure (top, supports)", "F2: flexure (top, supports)"}  # no top
    (proposal,) = S.proposal_entries(collect["stairs"])
    assert set(proposal["proposed"]) >= {"main", "distribution", "top", "landing"}
    assert proposal["proposed"]["main"] == {"dia": 12.0, "spacing": 350.0}  # As ≈ 320 mm²/m


def test_report_without_bars_is_skipped_with_a_proposal():
    stair = Staircase(
        id="ST",
        name="Stair",
        material="C25",
        waistThickness=150,
        riser=165,
        tread=250,
        flightWidth=1200,
    )
    building = _building()
    building.additions.stairs = building.additions.stairs[:1]
    collect: dict = {}
    report = S.stair_report(building, {"ST": stair}, MATERIALS, None, collect)
    assert report["elements"] == []
    assert report["skipped"][0]["reason"] == "no reinforcement"
    assert any("geometry fails" in n and "2R + T" in n for n in report["notes"])
    (entry,) = S.proposal_entries(collect["stairs"])
    assert entry["current"] is None
    assert entry["proposed"]["material"] == "RB420"  # the bar material of 03 Materials


def test_too_small_suggests_a_waist():
    stair = Staircase(
        id="ST",
        name="S",
        material="C25",
        waistThickness=100,
        riser=160,
        tread=300,
        flightWidth=1200,
    )
    building = _building()
    building.additions.stairs = building.additions.stairs[:1]
    collect: dict = {}
    S.stair_report(building, {"ST": stair}, MATERIALS, None, collect)
    (entry,) = S.proposal_entries(collect["stairs"])
    assert entry["status"] == "tooSmall"
    assert entry["tooSmall"]["suggestion"].startswith("try a ")
    assert "mm waist" in entry["tooSmall"]["suggestion"]


def test_spec_of_reads_proposed_fields():
    stair = Staircase(
        id="ST",
        name="S",
        material="C25",
        waistThickness=150,
        riser=160,
        tread=300,
        flightWidth=1200,
    )
    spec = S.spec_of(stair)
    assert spec.spanning == "betweenBeams" and spec.arrangement == "straight"
    assert spec.landing == 1200 and spec.landing_h == 150 and spec.bars is None
    extended = stair.model_copy(
        update={"arrangement": "dogLegged", "spanning": "landingEdges", "wellWidth": 150}
    )
    spec = S.spec_of(extended)
    assert spec.arrangement == "dogLegged" and spec.well == 150

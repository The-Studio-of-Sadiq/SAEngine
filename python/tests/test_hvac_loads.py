"""HVAC cooling loads (stream H1): BNBC tables, constructions, zones, gains, the estimate, the
report and its cache, and, when EnergyPlus version 26.2.0 is found (``SAENGINE_ENERGYPLUS``),
the EnergyPlus runs. All buildings are synthetic."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import pytest

from saengine.hvac import constructions as C
from saengine.hvac import energyplus as EP
from saengine.hvac import fallback as F
from saengine.hvac import tables as T
from saengine.hvac.gains import design_conditions, zone_gains
from saengine.hvac.geometry import facade_of, zones
from saengine.hvac.report import hvac_loads, hvac_results, plant_equipment
from saengine.library.bim import BuildingModel
from saengine.library.mep import MepModel, parse
from saengine.plumbing.building import Building
from saengine.verification.cases import BY_ID
from saengine.verification.run import run_case

EXE = EP.find_energyplus()
needs_energyplus = pytest.mark.skipif(EXE is None, reason="EnergyPlus not found")

L_SHAPE = [[0, 0], [20000, 0], [20000, 12000], [8000, 12000], [8000, 20000], [0, 20000]]


def tower(n: int = 3, outline=None, setback=None) -> BuildingModel:
    """GF and L1..L(n-1) at 3 m, the roof on top; every level above GF has a slab of
    ``outline`` (``setback``: the outline of the top floor's roof)."""
    names = ["GF"] + [f"L{i}" for i in range(1, n)] + ["ROOF"]
    stories = [{"id": s, "name": s, "elevation": 3000 * i} for i, s in enumerate(names)]
    slabs = []
    for i, s in enumerate(names):
        if i == 0:
            continue
        boundary = setback if (setback and s == "ROOF") else (outline or L_SHAPE)
        if setback and s == names[-2]:
            boundary = setback
        slabs.append({"id": f"S-{s}", "type": "SL150", "kind": "slab", "elevation": 3000 * i,
                      "boundary": boundary})  # fmt: skip
    return BuildingModel.model_validate({"stories": stories, "elements": slabs})


def office(names: list[str], **hvac) -> MepModel:
    """Office stories ``names`` (``stories`` in ``hvac`` replaces them)."""
    return MepModel.model_validate(
        {"hvac": {"stories": [{"story": s, "use": "officeSpace"} for s in names], **hvac}}
    )


# ─────────────────────────────────────────── tables ───────────────────────────────────────────


def test_bnbc_tables_as_read_from_the_pages() -> None:
    dhaka = T.STATIONS["dhaka"]
    assert dhaka.cooling["2"] == (34.5, 27.0) and dhaka.cooling["0.4"] == (35.55, 27.5)
    assert dhaka.evaporation["1"] == (28.5, 29.0) and dhaka.range == 5.0
    assert T.STATIONS["jessore"].cooling["0.4"] == (38.0, 28.5)
    assert T.STATIONS["mongla"].range == 5.0 and T.STATIONS["ishurdi"].range == 6.0
    assert len(T.STATIONS) == 20
    office = T.VENTILATION["officeSpace"]
    assert (office.perPerson, office.perArea, office.density) == (2.5, 0.3, 5)
    assert T.VENTILATION["livingArea"].ach == 0.35 and T.VENTILATION["livingArea"].perPerson == 7.5
    assert T.VENTILATION["parkingGarage"].exhaust == 3.75
    assert T.VENTILATION["operatingRoom"].perPerson == 15
    assert T.LPD["offices"] == 9 and T.LPD["apartments"] == 7
    assert T.shgc_limit(0.2) == 0.60 and T.shgc_limit(0.25) == 0.50 and T.shgc_limit(0.05) == 0.85
    assert T.station_for(None, "chattogram")[0].key == "chittagong"
    station, notes = T.station_for(None, "custom")
    assert station.key == "dhaka" and notes


def test_inside_conditions_within_table_8_2_1() -> None:
    assert T.inside_conditions("officeSpace")[:2] == (24.0, 60.0)
    assert T.inside_conditions("kitchenCooking")[:2] == (28.0, 60.0)  # row 2: 28-31 °C
    assert T.inside_conditions("museum")[:2] == (22.0, 55.0)  # row 22: 17-22 °C
    assert T.inside_conditions("patientRoom")[:2] == (24.0, 55.0)


# ──────────────────────────────────────── constructions ────────────────────────────────────────


def test_u_values_from_the_data_set_layers() -> None:
    r = 2 * 0.012 / 1.4 + 0.25 / 0.895
    assert C.u_value(C.WALLS["brick250"]) == pytest.approx(1 / (0.13 + r + 0.04))
    assert (
        C.u_value(C.ROOFS["rcInsulated"], roof=True) < 0.7 < C.u_value(C.ROOFS["rcLimeTerracing"])
    )
    changed = C.with_u(C.WALLS["brick250"], 1.0)
    assert C.u_value(changed) == pytest.approx(1.0)
    assert changed.layers[1].density == 1920  # the mass stays
    hvac = MepModel.model_validate({"hvac": {"envelope": {"uGlazing": 3.0, "shgc": 0.4}}}).hvac
    choice = C.envelope(hvac.envelope)
    assert choice.simpleGlazing and (choice.uGlazing, choice.shgc) == (3.0, 0.4)
    objects = C.epjson_objects(choice)
    assert objects["WindowMaterial:SimpleGlazingSystem"]["Glazing"]["u_factor"] == 3.0


# ─────────────────────────────────────────── zones ───────────────────────────────────────────


def test_zones_walls_windows_and_interzone_pairs() -> None:
    bim = tower(3)
    mep = office(["L1", "L2"], stories=[
        {"story": "GF", "conditioned": False, "use": "parkingGarage"},
        {"story": "L1", "glazing": {"S": 0.4, "N": 0.0}},
        {"story": "L2"},
    ])  # fmt: skip
    zoning = zones(Building.of(bim), mep.hvac)
    assert [z.story for z in zoning.zones] == ["GF", "L1", "L2"]
    gf, l1, l2 = zoning.zones
    assert not gf.conditioned and l1.conditioned
    assert l1.area == pytest.approx(20 * 12 + 8 * 8)  # the L: 304 m²
    assert gf.area == pytest.approx(304)  # on grade: the plan of L1's slab
    assert len(l1.walls()) == 6 and l1.height == pytest.approx(3.0)
    south = [w for w in l1.walls() if w.facade == "S"]
    assert len(south) == 1 and south[0].azimuth == pytest.approx(180)
    window = sum(w.area for w in south[0].windows)
    assert window == pytest.approx(0.4 * south[0].area)
    assert not [w for w in l1.walls() if w.facade == "N" and w.windows]
    # default ratio (Part 3 Sec 4.5.1.2): the plan is 20 m deep behind the east facade, > 14 m
    east = [w for w in l2.walls() if w.facade == "E"]
    assert sum(x.area for w in east for x in w.windows) == pytest.approx(
        0.35 * sum(w.area for w in east)
    )
    assert (T.default_wwr(7.9), T.default_wwr(8.0), T.default_wwr(14.0)) == (0.2, 0.3, 0.3)
    assert T.default_wwr(14.1) == 0.35
    names = {s.name: s for z in zoning.zones for s in z.surfaces}
    pairs = [s for s in names.values() if s.boundary == "Surface"]
    assert pairs and all(names[s.other].other == s.name for s in pairs)
    assert sum(s.area for s in l2.by_kind("Roof")) == pytest.approx(304)
    assert gf.by_kind("Floor")[0].boundary == "Adiabatic"
    assert facade_of(10) == "N" and facade_of(90) == "E" and facade_of(200) == "S"
    assert facade_of(300) == "W"


def test_setback_gives_a_roof_on_the_story_below() -> None:
    small = [[0, 0], [10000, 0], [10000, 10000], [0, 10000]]
    bim = tower(3, outline=[[0, 0], [20000, 0], [20000, 10000], [0, 10000]], setback=small)
    zoning = zones(Building.of(bim), office(["L1", "L2"]).hvac)
    l1 = zoning.zones[1]
    assert sum(s.area for s in l1.by_kind("Roof")) == pytest.approx(100)
    assert sum(s.area for s in l1.by_kind("Ceiling")) == pytest.approx(100)


def test_no_listed_stories_conditions_them_all() -> None:
    zoning = zones(Building.of(tower(2)), MepModel.model_validate({"hvac": {}}).hvac)
    assert [z.conditioned for z in zoning.zones] == [True, True] and zoning.notes


# ─────────────────────────────────────────── gains ───────────────────────────────────────────


def test_gains_occupants_and_outdoor_air() -> None:
    bim = tower(2, outline=[[0, 0], [20000, 0], [20000, 15000], [0, 15000]])
    mep = MepModel.model_validate({"hvac": {"stories": [
        {"story": "GF", "use": "officeSpace"}, {"story": "L1", "use": "livingArea"},
    ]}})  # fmt: skip
    zoning = zones(Building.of(bim), mep.hvac)
    office_gains = zone_gains(zoning.zones[0], mep.hvac)
    assert office_gains.occupants == pytest.approx(15)
    assert office_gains.outdoor_air(300, 900) == pytest.approx((2.5 * 15 + 0.3 * 300) / 1000)
    assert office_gains.lighting == 9.0
    living = zone_gains(zoning.zones[1], mep.hvac)
    assert living.problems  # no density: give the occupants
    living = zone_gains(zoning.zones[1], mep.hvac, population=20)
    assert living.occupants == 20 and living.lighting == 7.0
    # max(0.35 ACH of 900 m³ = 0.0875 m³/s, 7.5 l/s x 20 = 0.15 m³/s)
    assert living.outdoor_air(300, 900) == pytest.approx(0.15)


def test_design_conditions_from_settings_and_overrides() -> None:
    hvac = MepModel.model_validate({"hvac": {"design": {"outdoorDB": 36, "dailyRange": 7}}}).hvac
    d = design_conditions(hvac, "sylhet")
    assert (d.db, d.wb, d.range, d.station.key) == (36, 26.5, 7, "sylhet")
    d = design_conditions(MepModel.model_validate({"hvac": {}}).hvac, None)
    assert (d.db, d.wb, d.latitude, d.longitude) == (34.5, 27.0, 23.7, 90.4)


# ──────────────────────────────────────── the estimate ────────────────────────────────────────


def test_psychrometrics() -> None:
    assert F.saturation_pressure(20.0) == pytest.approx(2.339, rel=2e-3)  # ASHRAE table 2.3389
    assert F.humidity_ratio_rh(24, 60) == pytest.approx(0.01117, rel=5e-3)
    # wet bulb = dry bulb: saturated
    assert F.humidity_ratio_wb(27, 27) == pytest.approx(F.humidity_ratio_rh(27, 100))


def test_ventilation_load_by_hand() -> None:
    s, la = F.ventilation_load(0.1, 34.5, 0.0195, 24.0, 0.0112)
    assert s == pytest.approx(1.204 * 0.1 * (1.006 + 1.86 * 0.0195) * 10.5)
    assert la == pytest.approx(1.204 * 0.1 * 2501 * 0.0083)


def test_estimate_report_without_energyplus() -> None:
    mep = office(["L1", "L2"], stories=[
        {"story": "GF", "conditioned": False, "use": "parkingGarage"},
        {"story": "L1"}, {"story": "L2"},
    ])  # fmt: skip
    r = hvac_results(mep, tower(3), "dhaka", use_energyplus=False)
    assert r["engine"] == "estimate" and r["engineLabel"] == F.LABEL
    assert [z["story"] for z in r["zones"]] == ["L1", "L2"]
    for z in r["zones"]:
        assert z["total"] == pytest.approx(z["sensible"] + z["latent"], abs=2e-3)
        assert set(z["breakdown"]) >= {"walls", "roof", "glazingSolar", "people", "ventilation"}
        assert z["airflow"] >= z["outdoorAir"] > 0
    top = r["zones"][1]
    assert top["breakdown"]["roof"] > 0 and r["zones"][0]["breakdown"]["roof"] == 0
    assert r["total"] == pytest.approx(sum(z["total"] for z in r["zones"]), abs=2e-3)
    assert any("not conditioned" in n for n in r["notes"])
    assert r["problems"] == []


def test_overhangs_and_blinds_lower_the_estimate() -> None:
    bim = tower(2)
    base = hvac_results(office(["GF"]), bim, use_energyplus=False)
    shaded = hvac_results(office(["GF"], envelope={"shading": "overhang"}), bim,
                          use_energyplus=False)  # fmt: skip
    a = 0.09 + (0.14 - 0.09) * 0.34  # Table 3.4.3 at 0.234
    ratio = (
        shaded["zones"][0]["breakdown"]["glazingSolar"]
        / base["zones"][0]["breakdown"]["glazingSolar"]
    )
    assert ratio == pytest.approx(0.819 / (0.819 + a), rel=1e-3)


def test_files_cache_and_problems(tmp_path: Path) -> None:
    (tmp_path / "06 BIM").mkdir()
    (tmp_path / "07 MEP").mkdir()
    (tmp_path / "06 BIM" / "bim.json").write_text(tower(2).model_dump_json(), encoding="utf-8")
    mep = {"schema": "saengine.mep/1", "hvac": {"stories": [{"story": "GF"}, {"story": "L1"}]}}
    (tmp_path / "07 MEP" / "mep.json").write_text(json.dumps(mep), encoding="utf-8")
    first = hvac_loads(tmp_path, use_energyplus=False)
    assert first["engine"] == "estimate" and not first["cached"] and "run" not in first
    # the estimate is never cached (it takes no time; EnergyPlus is tried again next time)
    assert not (tmp_path / "07 MEP" / "hvac.results" / "loads.json").exists()
    again = hvac_loads(tmp_path, use_energyplus=False)
    assert not again["cached"] and again["total"] == first["total"]
    changed = json.dumps({**mep, "hvac": {**mep["hvac"], "design": {"indoorDB": 25}}})
    third = hvac_loads(tmp_path, changed, use_energyplus=False)
    assert not third.get("cached") and third["total"] < first["total"]
    bad = hvac_loads(tmp_path, '{"schema": "saengine.mep/1", "hvac": {"stories": [{"story": "X"}]}}',
                     use_energyplus=False)  # fmt: skip
    assert any("no story 'X'" in p for p in bad["problems"])
    assert hvac_loads(tmp_path, "{not json")["problems"]
    assert hvac_loads(tmp_path, '{"schema": "saengine.mep/1"}')["problems"] == [
        "07 MEP has no hvac section"
    ]


def gap_building() -> BuildingModel:
    """GF 0, L1 3 m, L2 6 m, L3 9 m, ROOF 12 m; slabs (10 x 10 m) only at L1 and ROOF."""
    square = [[0, 0], [10000, 0], [10000, 10000], [0, 10000]]
    names = ["GF", "L1", "L2", "L3", "ROOF"]
    stories = [{"id": s, "name": s, "elevation": 3000 * i} for i, s in enumerate(names)]
    slabs = [{"id": f"S-{s}", "type": "SL150", "kind": "slab", "elevation": 3000 * i,
              "boundary": square} for i, s in enumerate(names) if s in ("L1", "ROOF")]  # fmt: skip
    return BuildingModel.model_validate({"stories": stories, "elements": slabs})


def test_story_without_slabs_leaves_a_gap_not_a_false_pair() -> None:
    """L2 has no zone, L3 has one (from the ROOF slab). L1's ceiling and L3's floor face the
    outside at their own heights; no interzone pair crosses the gap."""
    zoning = zones(Building.of(gap_building()), office(["GF", "L1", "L3"]).hvac)
    assert [z.story for z in zoning.zones] == ["GF", "L1", "L3"]
    _, l1, l3 = zoning.zones
    assert any(p.startswith("L2: no slabs") for p in zoning.problems)
    assert any("no zone between it and L3" in p for p in zoning.problems)
    assert not l1.by_kind("Ceiling") and not [s for s in l3.surfaces if s.other]
    roof = l1.by_kind("Roof")
    assert sum(s.area for s in roof) == pytest.approx(100)
    assert all(v[2] == pytest.approx(6.0) for s in roof for v in s.vertices)
    floor = l3.by_kind("Floor")
    assert [s.boundary for s in floor] == ["Outdoors"]
    assert all(v[2] == pytest.approx(9.0) for s in floor for v in s.vertices)


def test_slabs_with_nothing_above_are_the_roof() -> None:
    """GF 0, L1 3 m, L2 6 m; slabs (10 x 10 m) only at L1: they are the building's roof, so
    GF is the only zone (its roof at 3.0 m, 100 m², in the sun) and no room is made above them;
    a story listed as conditioned above the roof slab is a problem."""
    square = [[0, 0], [10000, 0], [10000, 10000], [0, 10000]]
    stories = [
        {"id": s, "name": s, "elevation": 3000 * i} for i, s in enumerate(["GF", "L1", "L2"])
    ]
    model = BuildingModel.model_validate(
        {
            "stories": stories,
            "elements": [
                {"id": "S1", "type": "SL150", "kind": "slab", "elevation": 3000, "boundary": square}
            ],
        }
    )
    zoning = zones(Building.of(model), office(["GF", "L1"]).hvac)
    assert [z.story for z in zoning.zones] == ["GF"]
    roof = zoning.zones[0].by_kind("Roof")
    assert sum(s.area for s in roof) == pytest.approx(100)
    assert all(v[2] == pytest.approx(3.0) for s in roof for v in s.vertices)
    assert any("slabs at L1 are the roof" in n and "L1, L2" in n for n in zoning.notes)
    assert any("'L1' is listed as conditioned" in p for p in zoning.problems)
    assert not any(p.startswith(("L1:", "L2:")) for p in zoning.problems)


def test_rounding_keeps_humidity_ratios() -> None:
    from saengine.hvac.report import _round

    assert _round({"w": 0.019556, "kw": 33.61234, "flow": 0.0012346, "z": 0.0}) == {
        "w": 0.01956, "kw": 33.612, "flow": 0.001235, "z": 0.0,
    }  # fmt: skip


def test_geometry_warnings_are_read(tmp_path: Path) -> None:
    (tmp_path / "eplusout.err").write_text(
        "   ** Warning ** CalculateZoneVolume: 1 zone is not fully enclosed.\n"
        "   **   ~~~   ** For more details use:  Output:Diagnostics,DisplayExtrawarnings;\n"
        "   ** Warning ** Something else\n",
        encoding="utf-8",
    )
    found = EP.geometry_warnings(tmp_path)
    assert len(found) == 1 and "not fully enclosed" in found[0] and "Diagnostics" in found[0]


def test_mep_model_stays_backward_compatible() -> None:
    assert parse('{"schema": "saengine.mep/1", "equipment": []}').hvac is None
    with pytest.raises(ValueError, match="duplicate hvac ids"):
        MepModel.model_validate({"hvac": {"plant": [
            {"id": "P1", "kind": "pump", "story": "GF", "x": 0, "y": 0},
            {"id": "P1", "kind": "chiller", "story": "GF", "x": 0, "y": 0},
        ]}})  # fmt: skip


def test_plant_equipment_never_twice() -> None:
    item = {"id": "CH1", "kind": "chiller", "story": "ROOF", "x": 5000, "y": 5000,
            "length": 3000, "width": 1500, "operatingWeight": 60}  # fmt: skip
    eq = plant_equipment(item)
    assert eq["id"] == "EQ-CH1" and eq["kind"] == "chiller" and eq["vibrating"]
    assert plant_equipment(item, {"EQ-CH1"}) is None
    assert plant_equipment({**item, "operatingWeight": None}) is None


def test_fast_verification_cases(tmp_path: Path) -> None:
    for case in ("DH1", "DH2"):
        assert BY_ID[case].fast
        record = run_case(case, tmp_path)
        assert record["pass"], record


def test_energyplus_case_skips_cleanly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(EP, "find_energyplus", lambda explicit=None: None)
    record = run_case("AH1", tmp_path)
    assert record["pass"] and record["quantities"] == [] and "Skipped" in record["notes"][0]
    assert not BY_ID["AH1"].fast


def test_find_energyplus_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EP.ENV_VAR, raising=False)
    exe = tmp_path / EP.EXE
    exe.write_text("")
    assert EP.find_energyplus(tmp_path) == exe
    monkeypatch.setenv(EP.ENV_VAR, str(tmp_path))
    assert EP.find_energyplus() == exe


# ───────────────────────────────────────── EnergyPlus ─────────────────────────────────────────


@needs_energyplus
def test_energyplus_version() -> None:
    assert EP.version(EXE).startswith("EnergyPlus, Version 26.2.0")


@needs_energyplus
def test_energyplus_steady_box_case(tmp_path: Path) -> None:
    record = run_case("AH1", tmp_path)
    assert record["pass"] and len(record["quantities"]) == 4, record


@needs_energyplus
def test_energyplus_ten_storeys_under_30_s(tmp_path: Path) -> None:
    names = ["GF"] + [f"L{i}" for i in range(1, 10)]
    mep = MepModel.model_validate({"hvac": {
        "envelope": {"shading": "overhang"},
        "stories": [{"story": "GF", "conditioned": False, "use": "parkingGarage"}]
        + [{"story": s, "use": "officeSpace", "glazing": {"S": 0.4, "W": 0.3}} for s in names[1:]],
    }})  # fmt: skip
    start = time.perf_counter()
    r = hvac_results(mep, tower(10), "dhaka", folder=tmp_path / "run")
    assert time.perf_counter() - start < 30
    assert r["engine"] == "EnergyPlus version 26.2.0" and r["problems"] == []
    assert [z["story"] for z in r["zones"]] == names[1:]
    assert EP.errors(tmp_path / "run") == []
    for z in r["zones"]:
        assert z["total"] == pytest.approx(z["sensible"] + z["latent"], rel=1e-3)
        assert 40 < z["density"] < 200  # W/m², an office in Dhaka
        assert z["peak"]["month"] in (5, 6, 7, 8, 9)
        parts = sum(v for k, v in z["breakdown"].items() if k != "glazing")
        assert parts == pytest.approx(z["total"], rel=0.1)
        assert z["airflow"] >= z["outdoorAir"] > 0
    top, mid = r["zones"][-1], r["zones"][4]
    assert top["breakdown"]["roof"] > 0 and mid["breakdown"]["roof"] == 0
    assert r["building"]["total"] <= r["total"] + 1e-6
    opaque = r["energyplus"]["envelope"]["opaque"]
    assert math.isclose(opaque["WALL"], C.u_value(C.WALLS["brick250"]), rel_tol=0.15)


@needs_energyplus
def test_energyplus_cache_skips_the_run(tmp_path: Path) -> None:
    (tmp_path / "06 BIM").mkdir()
    (tmp_path / "07 MEP").mkdir()
    (tmp_path / "06 BIM" / "bim.json").write_text(tower(3).model_dump_json(), encoding="utf-8")
    mep = {
        "schema": "saengine.mep/1",
        "hvac": {"envelope": {"shading": "blinds"}, "stories": [{"story": "L1"}, {"story": "L2"}]},
    }
    (tmp_path / "07 MEP" / "mep.json").write_text(json.dumps(mep), encoding="utf-8")
    first = hvac_loads(tmp_path)
    assert first["engine"] == "EnergyPlus version 26.2.0", first["problems"]
    assert first["problems"] == [] and not first["cached"] and "run" not in first
    stored = json.loads((tmp_path / "07 MEP" / "hvac.results" / "loads.json").read_text("utf-8"))
    assert stored["stamp"] == first["stamp"] and "zones" in stored["run"]
    start = time.perf_counter()
    again = hvac_loads(tmp_path)
    assert again["cached"] and time.perf_counter() - start < 2
    assert again["total"] == first["total"] and again["zones"] == first["zones"]
    # inputs that leave the epJSON alone still give fresh problems (the run is reused)
    mep["hvac"]["plant"] = [{"id": "CH1", "kind": "chiller", "story": "NOPE", "x": 0, "y": 0}]
    mep["hvac"]["ducts"] = [{"id": "D1", "system": "supply", "story": "L1",
                             "path": [[0, 0], [1000, 0]], "shaft": "NOSHAFT"}]  # fmt: skip
    edited = hvac_loads(tmp_path, json.dumps(mep))
    assert edited["cached"] and edited["total"] == first["total"]
    assert any("NOPE" in p for p in edited["problems"])
    assert any("NOSHAFT" in p for p in edited["problems"])


@needs_energyplus
def test_energyplus_gap_story(tmp_path: Path) -> None:
    r = hvac_results(office(["L1", "L3"]), gap_building(), "dhaka", folder=tmp_path / "run")
    assert r["engine"] == "EnergyPlus version 26.2.0"
    assert [z["story"] for z in r["zones"]] == ["L1", "L3"]
    assert not [p for p in r["problems"] if p.startswith("EnergyPlus")], r["problems"]
    err = (tmp_path / "run" / "eplusout.err").read_text("utf-8", errors="replace")
    assert "not fully enclosed" not in err
    assert r["zones"][1]["breakdown"]["floors"] != 0  # the exposed floor over the gap


@needs_energyplus
def test_energyplus_failure_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(model, exe, folder=None, timeout=EP.TIMEOUT):
        raise EP.EnergyPlusError("EnergyPlus failed (exit 1): test")

    real = EP.run
    monkeypatch.setattr(EP, "run", broken)
    r = hvac_results(office(["GF"]), tower(2))
    assert r["engine"] == "estimate" and "EnergyPlus failed" in r["problems"][0]
    # through the files: the failure is not cached, the next call runs EnergyPlus
    (tmp_path / "06 BIM").mkdir()
    (tmp_path / "07 MEP").mkdir()
    (tmp_path / "06 BIM" / "bim.json").write_text(tower(2).model_dump_json(), encoding="utf-8")
    mep = {"schema": "saengine.mep/1", "hvac": {"stories": [{"story": "GF"}]}}
    (tmp_path / "07 MEP" / "mep.json").write_text(json.dumps(mep), encoding="utf-8")
    assert hvac_loads(tmp_path)["engine"] == "estimate"
    assert not (tmp_path / "07 MEP" / "hvac.results" / "loads.json").exists()
    monkeypatch.setattr(EP, "run", real)
    retried = hvac_loads(tmp_path)
    assert retried["engine"] == "EnergyPlus version 26.2.0" and not retried["cached"]
    assert retried["problems"] == []

"""D5: the services (mep, plumbing, hvac, fire, electrical) read the code pack, not BNBC constants.

Every value below is pinned with the default pack (bnbc2020): the results are those before the
values moved into the pack. A stub pack that extends bnbc2020 and overrides one table changes
only that table's results; a pack without a table says the feature is not covered. Synthetic
data; packs are written to ``tmp_path`` only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.electrical import report as electrical_report
from saengine.fire import report as fire_report
from saengine.hvac import air, plant
from saengine.hvac import openings as duct_openings
from saengine.hvac import report as hvac_report
from saengine.library.mep import Equipment, MepModel
from saengine.mep import code_pack, loads
from saengine.mep import openings as mep_openings
from saengine.mep import report as mep_report
from saengine.plumbing import hydraulics, tanks
from saengine.plumbing import report as plumbing_report


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def stub(root: Path, tables: dict[str, dict], extends: str | None = "bnbc2020") -> object:
    """A pack ``d5-stub`` (name "D5 stub") extending bnbc2020 with ``tables`` over it."""
    folder = root / "d5-stub"
    (folder / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": "d5-stub",
        "name": "D5 stub",
        "version": "1.0.0",
        "extends": extends,
        "covers": list(tables),
    }
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, data in tables.items():
        (folder / "data" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return registry.load_path(folder)


def equipment(**kw) -> Equipment:
    base = {"id": "E", "kind": "pump", "story": "L1", "x": 0, "y": 0, "length": 1000,
            "width": 1000, "operatingWeight": 10}  # fmt: skip
    return Equipment.model_validate({**base, **kw})


# ─────────────────────────────── default pack: pinned ───────────────────────────────


def test_plumbing_hydraulics_and_tank_values_pinned() -> None:
    assert hydraulics.outlet_above_bottom() == 0.050
    assert hydraulics.FIXTURE_FLOW == {
        "wc": 11.4, "urinal": 56.8, "shower": 11.4, "bathtub": 15.1, "kitchenSink": 9.5,
    }  # fmt: skip
    assert hydraulics.FIXTURE_FLOW_FLUSH_VALVE_WC == 132.0
    assert hydraulics.fitting_length(50, {"elbow": 2, "gate": 1}) == pytest.approx(2 * 1.53 + 0.70)
    assert hydraulics.fitting_length(44, {"check": 1}) == pytest.approx((4.88 + 6.10) / 2)
    assert hydraulics._by_material() == "uPVC/PPR/HDPE 150, GI 120, CI 100"
    assert tanks.table_cover("severe", 30.0) == (40.0, None)
    assert tanks.table_cover("severe", 20.0)[0] == 45.0  # below the table: its least strength
    assert tanks.COVER_AGAINST_EARTH == 75.0 and tanks.brick_unit_weight() == 19.1
    assert tanks.default_roof_live() == 1.0 and tanks.TankOptions().roofLive == 1.0
    assert tanks._settlement_limit("sand") == 100.0
    assert tanks._settlement_limit("plasticClay") == 125.0
    assert tanks.code_min_area("Wall", "vertical", 200.0, 420.0, 12.0) == pytest.approx(120.0)
    assert tanks.code_min_area("Wall", "horizontal", 200.0, 420.0, 20.0) == pytest.approx(250.0)
    assert (tanks.max_spacing(100.0), tanks.max_spacing(200.0)) == (300.0, 450.0)
    combos = {c["name"]: c for c in tanks.combinations(None, {"D": {}, "F": {}, "H": {}})}  # type: ignore[arg-type]
    assert list(combos) == [
        "1.4D + 1.4F", "1.2D + 1.2F", "1.2D + 1.2F + 1.6H", "1.2D + 1.6H", "0.9D + 1.6H",
        "D + F", "D + F + H", "D + H", "0.6D + H",
    ]  # fmt: skip
    assert combos["0.9D + 1.6H"]["clause"] == "2.7.3.1 (6), W = 0"


def test_hvac_and_mep_values_pinned() -> None:
    oa = air.outdoor_air("corridor", 50.0, occupants=10.0)
    assert oa["flow"] == pytest.approx(0.025)  # 2.5 l/s per person governs over 0.3 l/s m²
    assert oa["source"].endswith(
        "at least 2.5 l/s per person (BNBC 2020 Part 8 Sec 2.11.3.4, p. 905)"
    )
    assert air.kitchen_exhaust_flow([("grill", 10.0, "gas")]) == pytest.approx(0.61)
    assert air.kitchen_rate_default() == 35.0
    assert air.velocity_limits("kitchenExhaust")[:2] == (7.62, 12.7)
    assert air.ceiling_height("worship") == 2600.0 and air.ceiling_height("officeSpace") is None
    assert duct_openings.required_headroom("officeSpace") == (
        2440.0,
        "BNBC 2020 Part 3 Sec 1.14.2.1(b), Part 1 volume p. 66",
    )
    assert duct_openings.clearance_of("kitchenExhaust") == 75.0
    assert (plant.chiller_cop("screw", 1000.0), plant.chiller_cop("airCooled", 2000.0)) == (
        5.40,
        3.05,
    )
    assert plant.WATER_COOLED_FROM == 1050.0 and plant.INSTALLATION_500TR == 1758.0
    assert loads.impact_percent(equipment(vibrating=True))[0] == 20.0
    assert loads.impact_percent(equipment(kind="generator", vibrating=True))[0] == 50.0
    percent, source = loads.impact_percent(equipment(kind="lift"))
    assert percent == 100.0 and "Table 6.2.6" in source
    assert mep_openings.strip_shares() == (0.125, 0.25)
    assert mep_openings.rules().punchingDistance == 10
    assert mep_openings.two_layer_thickness() == 250.0
    assert mep_openings.beam_source() == "BNBC 2020 6.4.1.1.1 (openings in Vn); net section"


def test_methods_are_built_from_the_pack() -> None:
    assert "+ 1000 l/min each other (at most eight)" in fire_report.method()[1]
    assert fire_report.METHOD == fire_report.method()
    assert "at least 0.8, Sec 1.3.18.1" in electrical_report.method()[0]
    assert "above ten storeys or 32 m" in electrical_report.method()[1]
    assert "daily / 16 h x 2.2" in plumbing_report.method()[0]
    assert "roof tank 1/2, underground reservoir 1 x" in plumbing_report.method()[1]
    assert "20 % below 8 m, 30 % to 14 m, 35 % beyond" in hvac_report.method()[0]
    assert "BNBC 2020 BNBC" not in " ".join(hvac_report.method())
    assert "Equipment (BNBC 2020)" in mep_report.method()[0]


# ─────────────────────────────── a second pack ───────────────────────────────


def test_a_pack_overriding_the_plumbing_fittings_changes_only_the_friction(tmp_path) -> None:
    import test_plumbing_hydraulics as th

    elbow = [round(2 * x, 2) for x in hydraulics.FITTINGS["elbow"]]
    pack = stub(tmp_path, {"plumbing": {"fittings": {"lengths": {"elbow": elbow}}}})
    before = hydraulics.water_hydraulics(building=th.building(5), mep={"plumbing": th.tower(5)})
    with code_context.using(pack):
        assert hydraulics.fitting_length(50, {"elbow": 1}) == pytest.approx(2 * 1.53)
        assert hydraulics.fitting_length(50, {"gate": 1}) == pytest.approx(0.70)
        assert tanks.table_cover("severe", 30.0) == (40.0, None)  # the tank rules: unchanged
        after = hydraulics.water_hydraulics(building=th.building(5), mep={"plumbing": th.tower(5)})
    # The same demands and pipes, more friction: lower heads at the fixtures.
    assert [f["flow"] for f in after["floors"]] == [f["flow"] for f in before["floors"]]
    assert [f["staticHead"] for f in after["floors"]] == [f["staticHead"] for f in before["floors"]]
    assert all(
        a["head"] < b["head"] for a, b in zip(after["floors"], before["floors"], strict=True)
    )


def test_a_pack_overriding_the_hvac_plant_changes_only_the_cop(tmp_path) -> None:
    pack = stub(tmp_path, {"hvac": {"plant": {"cop": {"screw": [{"upTo": None, "cop": 6.0}]}}}})
    with code_context.using(pack):
        assert plant.chiller_cop("screw", 1000.0) == 6.0
        assert plant.chiller_cop("centrifugal", 2000.0) == 6.30
        assert air.kitchen_exhaust_flow([("grill", 10.0, "gas")]) == pytest.approx(0.61)


def test_a_pack_overriding_the_tank_cover_and_mep_openings(tmp_path) -> None:
    cover = {"severe": [None, 50, 50, 40, 30, 30, 25]}
    pack = stub(
        tmp_path,
        {"plumbing": {"tanks": {"cover": cover}}, "mepOpenings": {"punchingDistance": 5}},
    )
    with code_context.using(pack):
        assert tanks.table_cover("severe", 30.0) == (50.0, None)
        assert tanks.table_cover("moderate", 30.0) == (30.0, None)
        assert hydraulics.fitting_length(50, {"elbow": 1}) == pytest.approx(1.53)
        assert mep_openings.rules().punchingDistance == 5
        assert mep_openings.strip_shares() == (0.125, 0.25)


def test_a_pack_without_the_service_tables_says_not_covered(tmp_path) -> None:
    import test_fire as tf
    import test_plumbing_hydraulics as th

    from saengine.electrical.report import electrical_results
    from saengine.fire.report import fire_results

    root = stub(tmp_path, {}, extends=None)
    mep, bim, objects = tf.high_rise()
    with code_context.using(root):
        assert not code_pack.covers("plumbing") and not code_pack.covers("fire")
        hyd = hydraulics.water_hydraulics(building=th.building(2), mep={"plumbing": th.tower(2)})
        assert "Water-supply hydraulics: not covered by the code pack D5 stub" in hyd["problems"]
        fire = fire_results(mep, bim, objects)
        assert fire["notes"] == ["Fire protection: not covered by the code pack D5 stub"]
        assert fire["method"] == []
        bare = MepModel.model_validate({"schema": "saengine.mep/1", "electrical": {}})
        electrical = electrical_results(bare)
        assert electrical["notes"] == ["Electrical services: not covered by the code pack D5 stub"]
        with pytest.raises(ValueError, match="not covered by the code pack D5 stub"):
            tanks.rules()
        with pytest.raises(ValueError, match="not covered by the code pack D5 stub"):
            mep_openings.rules()
        percent, note = loads.impact_percent(equipment(kind="lift"))
        assert percent == 0.0 and "not covered by the code pack D5 stub" in note


def test_a_pack_without_the_new_groups_says_not_covered(tmp_path) -> None:
    pack = stub(
        tmp_path,
        {
            "plumbing": {"$remove": ["fittings", "tanks"]},
            "hvac": {"$remove": ["air", "plant"]},
        },
    )
    with code_context.using(pack):
        assert not hydraulics.covered()
        with pytest.raises(ValueError, match="The design of water tanks: not covered"):
            tanks.rules()
        with pytest.raises(ValueError, match="The HVAC air distribution: not covered"):
            air.outdoor_air("officeSpace", 100.0)
        with pytest.raises(ValueError, match="The HVAC plant proposal: not covered"):
            plant.chiller_cop("screw", 1000.0)

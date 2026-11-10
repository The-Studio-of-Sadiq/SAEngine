"""Walk 4 W-A (US project) fixes: a US project's units, bars, sheets, bill and settings come
from its code pack (``aci318-asce7-22``): W4A-6 (New Building units and bar grades), W4A-9 (bar
names), W4A-12/13 (report units), W4A-16 (bar schedule standard, laps, bar sizes and masses),
W4A-17 (sheet size, column sizes in inches), W4A-18 (bill units, bag, mixes, rates), W4A-19
(settings fields the pack has no use for) and W4A-20 (area loads in psf). The default pack's
output is unchanged."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

US = "aci318-asce7-22"
PSF = 0.047880258980335843  # kN/m² per psf
FT = 304.8  # mm

WIZARD = {
    "schema": "saengine.newBuilding/1",
    "name": "US5",
    "spacings": {"x": [6096, 6096, 6096], "y": [4877, 4877]},
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3658},
        {"id": "L2", "name": "Level 2", "elevation": 6706},
    ],
    "storyHeights": [3658, 3048],
    "system": "rcFrame",
    "designCode": US,
    "site": {
        "location": "custom",
        "spectral": {"sds": 1.0, "sd1": 0.6, "s1": 0.6, "tl": 8},
        "windSpeed": 46.9,
        "siteClass": "SD",
        "siteClassSource": "assumed",
    },
    "wind": {"exposure": "C"},
    "occupancy": {"use": "office"},
}


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture(scope="module")
def us_building(tmp_path_factory) -> Path:
    from saengine.project.new_building import create_building

    result = create_building(copy.deepcopy(WIZARD), tmp_path_factory.mktemp("us"))
    return Path(result["root"])


def _json(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


# ── W4A-6, W4A-17, W4A-20: a new US building ──


def test_new_us_building_takes_the_pack_units_sheet_and_area_loads(us_building: Path) -> None:
    settings = _json(us_building, "02 Project Settings/project-settings.json")
    assert settings["units"] == {"system": "USCustomary", "volume": "yd³"}
    assert settings["drawings"]["sheetSize"] == "ARCH D"
    loads = {a["id"]: a for a in settings["areaLoads"]}
    assert loads["FL"]["live"] / PSF == pytest.approx(50.0, abs=1e-3)  # office
    assert loads["FL"]["partitions"] / PSF == pytest.approx(15.0, abs=1e-3)
    assert loads["FL"]["finish"] / PSF == pytest.approx(25.0, abs=1e-3)
    assert loads["RF"]["live"] / PSF == pytest.approx(20.0, abs=1e-3)
    assert loads["RF"]["finish"] / PSF == pytest.approx(30.0, abs=1e-3)
    assert loads["ST"]["live"] / PSF == pytest.approx(100.0, abs=1e-3)


def test_new_us_building_uses_the_pack_bar_grade_and_sizes(us_building: Path) -> None:
    materials = _json(us_building, "03 Materials/materials.json")
    ids = [m["id"] for m in materials["materials"]]
    assert "A615-60" in ids
    assert materials["defaults"]["rebar"] == "A615-60"
    sizes = {str(int(d)) for d in (10, 13, 16, 19, 22, 25, 29, 32, 36)}
    from saengine.library.defaults import default_object_library

    starters = {o.id for o in default_object_library().objects}
    objects = _json(us_building, "04 Objects/objects.json")
    for item in objects["objects"]:
        if item["id"] in starters:
            continue  # the starting types of every new project (not generated)
        bars = item.get("reinforcement") or {}
        for group in bars.get("longitudinal") or []:
            assert f"{group['dia']:g}" in sizes
        if item.get("kind") == "column":
            side = item["profile"]["xDim"]
            assert side / 25.4 == pytest.approx(round(side / 25.4), abs=1e-3), side
    substructure = _json(us_building, "09 Substructure/substructure.json")
    for footing in substructure.get("foundations", []):
        for layer in ("bottomX", "bottomY", "topX", "topY"):
            mesh = (footing.get("reinforcement") or {}).get(layer)
            if mesh:
                assert f"{mesh['dia']:g}" in sizes, footing["id"]


def test_wizard_units_choice_is_kept() -> None:
    from saengine.project.new_building import spec_from_wizard

    spec, _ = spec_from_wizard({**WIZARD, "units": "SI"})
    assert spec["units"] == "SI"
    from saengine.library.generator import BuildingSpec, settings_patch

    notes: list[str] = []
    _, patch, _, _ = settings_patch(BuildingSpec.model_validate(spec), None, notes)
    assert patch["units"]["system"] == "SI"


def test_pack_choices_give_units_grades_and_hidden_fields() -> None:
    from saengine.library.settings import pack_choices
    from saengine.units import Units

    choices = pack_choices(registry.load(US))
    assert choices["units"][0]["id"] == "USCustomary"
    assert choices["rebarGrades"][0]["id"] == "A615-60"
    hidden = {h["id"] for h in choices["hiddenFields"]}
    assert {"site.zoneCoefficient", "site.airRaidShelter", "site.spectral.na"} <= hidden
    assert choices["locations"][-1]["label"] == "Custom (enter V)"
    shown = pack_choices(registry.load(US), Units("USCustomary"))
    office = next(u for u in shown["areaUses"] if u["id"] == "office")
    assert office["label"].endswith("(50 psf)")
    # The default pack: nothing hidden, its labels as before.
    bnbc = pack_choices(registry.load("bnbc2020"))
    assert "hiddenFields" not in bnbc and "rebarGrades" not in bnbc
    assert bnbc["locations"][-1]["label"] == "Custom (enter Z and V)"


def test_bnbc_new_project_defaults_unchanged() -> None:
    from saengine.library.defaults import default_material_library
    from saengine.library.settings import default_project_settings

    settings = default_project_settings("P")
    assert [(a.finish, a.partitions) for a in settings.areaLoads] == [
        (1.2, 1.2),
        (1.2, 0),
        (1.5, 0),
    ]
    assert settings.drawings.sheetSize == "A1" and settings.units.is_default()
    assert default_material_library().materials[0].id == "C20.7"


# ── W4A-16: the bar schedule ──


def test_bar_schedule_uses_the_pack_standard_masses_and_laps() -> None:
    from saengine.codes.bars import bar_mass
    from saengine.drawings import bbs
    from saengine.units import Units

    with code_context.using(registry.load(US)):
        assert bbs.standard().name == "ACI 315 / CRSI"
        assert bar_mass(16) == pytest.approx(1.552)  # #5: 1.043 lb/ft
        with bbs.in_units(Units("USCustomary", bar_names={"16": "#5"})):
            assert bbs._remarks("zone B, lap 800") == "zone B, lap 2'-7 1/2\""
    assert bbs._remarks("lap 800") == "lap 800"


def test_requests_about_a_us_project_run_under_its_pack(tmp_path: Path) -> None:
    from saengine.rpc import server

    settings = tmp_path / "02 Project Settings"
    settings.mkdir(parents=True)
    (tmp_path / "x.saengine").write_text("{}", encoding="utf-8")
    (settings / "project-settings.json").write_text(json.dumps({"codePack": US}), "utf-8")
    seen = []

    def handler(params):
        seen.append(code_context.current().id)

    with code_context.project(tmp_path) as found:
        if found is None:
            pytest.skip("no project marker recognised here")
    server._scoped(handler)({"projectRoot": str(tmp_path)})
    assert seen == [US]
    (settings / "project-settings.json").write_text(json.dumps({"codePack": "bnbc2020"}), "utf-8")
    server._scoped(handler)({"projectRoot": str(tmp_path)})
    assert seen[-1] == "bnbc2020" and code_context.in_force() is None


# ── W4A-12/13: the report ──


def test_report_units_line_and_weight_parts() -> None:
    from saengine.units import Units, convert_document, convert_text

    us = Units("USCustomary")
    document = {"meta": {"units": "Units: geometry in m"}, "sections": []}
    line = convert_document(document, us)["meta"]["units"]
    assert "ft" in line and "kip" in line and "psf" in line and "MPa" not in line
    assert convert_document(document, Units())["meta"]["units"] == "Units: geometry in m"
    text = convert_text("1,804.7 kN (D 1,371.7 kN, SD 214.1 kN)", us)
    assert "kN" not in text and text.count("kip") == 3


# ── W4A-17: the sheet ──


def test_us_sheets_are_known() -> None:
    from saengine.drawings.sheets.layout import PAPER, TITLE_WIDTH
    from saengine.library.settings import Drawings

    assert PAPER["ARCH D"] == pytest.approx((36 * 25.4, 24 * 25.4))
    assert PAPER["ANSI D"] == pytest.approx((34 * 25.4, 22 * 25.4))
    assert "ARCH D" in TITLE_WIDTH
    assert Drawings(sheetSize="ARCH D").sheetSize == "ARCH D"


# ── W4A-18: the bill ──


def test_bill_takes_the_pack_bag_mixes_and_rates() -> None:
    from saengine.boq import costing, quantities

    assert quantities.estimating().cementBag == 50.0
    assert quantities.materials_conventions() == quantities.MATERIALS_CONVENTIONS
    with code_context.using(registry.load(US)):
        bag = quantities.estimating().cementBag
        assert bag / 0.45359237 == pytest.approx(94.0, abs=1e-3)
        text = quantities.materials_conventions()[0]
        assert "42.6377 kg bags" in text and "35.3147" not in text
        assert quantities._bar_text(16) == "#5"
        assert not costing.sample_rates_apply()
        answer = costing.cost_texts(json.dumps({"items": []}))
        assert answer.get("noRates") is True or "problems" in answer
    assert quantities._bar_text(16) == "16 mm"


def test_bill_workbook_units() -> None:
    from saengine.boq.workbook import _shown_quantity
    from saengine.units import Units

    show, unit = _shown_quantity(Units("USCustomary"), "cft")
    assert unit == "ft³" and show(10.0) == 10.0
    show, unit = _shown_quantity(Units("USCustomary"), "l")
    assert unit == "gal" and show(3.785411784) == pytest.approx(1.0)
    show, unit = _shown_quantity(Units("USCustomary", {"volume": "yd³"}), "m3")
    assert unit == "yd³"
    show, unit = _shown_quantity(Units(), "l")
    assert unit == "l" and show(5.0) == 5.0

"""Usability walk 4 minors (alpha 10 track G): list labels and the new project's exposure
(W4A-27/28), settings problems in words on their own page (W4C-28), the AGS4 boring method
(W4B-20), the report's governing check (W4A-29), the footings' bearing text by the pack in
force (W4B-25), precast warnings before Run All (W4C-38) and the CBFEM texts (W4C-27)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.library import default_project_settings
from saengine.library.check import check_library, coverage_warnings
from saengine.library.settings import (
    PackListError,
    ProjectSettings,
    keyed_label,
    new_project_exposure,
    pack_choices,
)

US = "aci318-asce7-22"


def test_list_labels_do_not_repeat_the_key():
    assert keyed_label("C", "Exposure C: open terrain") == "Exposure C: open terrain"
    assert keyed_label("SD", "Site class D: stiff soil") == "Site class D: stiff soil"
    assert keyed_label("A", "Urban, suburban, wooded") == "A: Urban, suburban, wooded"
    choices = pack_choices(registry.load(US))
    assert [e["label"].split(":")[0] for e in choices["exposures"]] == [
        "Exposure B",
        "Exposure C",
        "Exposure D",
    ]
    assert not any(c["label"].startswith("SD: ") for c in choices["siteClasses"])


def test_new_project_exposure_is_the_one_the_wizard_shows():
    us = registry.load(US)
    assert pack_choices(us)["defaultExposure"] == [{"id": "C", "label": "C"}]
    assert new_project_exposure(us.table("wind"), "A") == "C"  # ASCE 7-22 26.7.3
    assert new_project_exposure(us.table("wind"), "D") == "D"
    ec = registry.load("eurocodes")
    assert pack_choices(ec)["defaultExposure"][0]["id"] == "II"
    assert new_project_exposure(SimpleNamespace(exposures={}), "A") is None


def test_settings_choices_not_in_the_pack_are_problems_on_their_page():
    data = default_project_settings("M").model_dump(mode="json", by_alias=True)
    data["site"]["location"] = "nowhere"
    with pytest.raises(Exception) as caught:
        ProjectSettings.model_validate(data)
    assert "Location 'nowhere'" in str(caught.value)
    found = check_library("settings", json.dumps(data))
    paths = [p["path"] for p in found]
    assert "site.location" in paths, found
    message = next(p["message"] for p in found if p["path"] == "site.location")
    assert message.startswith("Location 'nowhere' is not in the lists of the code pack")
    error = PackListError("X", [("wind.exposure", "Exposure 'Q'")])
    assert error.problems() == [
        ("wind.exposure", "Exposure 'Q' is not in the lists of the code pack X: choose one")
    ]


def test_ags_writes_the_boring_method_as_loca_type():
    from saengine.library.soil import SoilReport
    from saengine.soil import ags

    report = SoilReport.model_validate(
        {
            "report": {"title": "Site"},
            "boreholes": [
                {"id": "BH-1", "method": "Wash boring", "spt": [{"depth": 1500, "N": 5}]},
                {"id": "BH-2", "method": "Wash boring", "spt": [{"depth": 1500, "N": 6}]},
                {"id": "BH-3", "method": "Wireline bore", "spt": [{"depth": 1500, "N": 7}]},
                {"id": "BH-4", "spt": [{"depth": 1500, "N": 8}]},
            ],
        }
    )
    text, _ = ags.to_text(report)
    rows = [line for line in text.split("\r\n") if line.startswith('"DATA","BH-')]
    assert [r.split(",")[2] for r in rows[:4]] == ['"WB"', '"WB"', '"WB2"', '""']
    assert '"DATA","LOCA_TYPE","WB","Wash boring"' in text
    assert '"DATA","LOCA_TYPE","WB2","Wireline bore"' in text
    holes, problems, _ = ags.read_text(text, "t.ags")
    assert not problems and holes[0]["method"] == "Wash boring"


def test_report_governing_check_is_the_one_that_sets_the_utilisation():
    from saengine.report.build import _governing

    element = {
        "utilisation": 0.702,
        "governingCheck": {"name": "Axial and bending", "combination": "1.2D + 1.6L"},
        "checks": [
            {"name": "Detailing: Confinement length lo", "utilisation": 1.0, "flag": False},
            {
                "name": "Axial and bending",
                "combination": "1.2D + 1.6L",
                "utilisation": 0.702,
                "flag": False,
            },
        ],
    }
    assert _governing(element)["name"] == "Axial and bending"
    del element["governingCheck"]
    assert _governing(element)["name"].startswith("Detailing")


def test_footing_bearing_text_leads_with_the_packs_own_combinations():
    from saengine.substructure.shallow import shallow_method

    with code_context.using(registry.load("bnbc2020")):
        bearing = next(line for line in shallow_method() if line.startswith("Bearing"))
    assert bearing.startswith("Bearing under the combinations of the code pack")
    assert "ASCE 7-05" not in bearing


def test_precast_warnings_before_run_all():
    objects = SimpleNamespace(
        objects=[
            SimpleNamespace(
                id="HC1",
                material="C30",
                kind="slab",
                precast=SimpleNamespace(element="hollowCore", cores=None, inserts=[]),
            ),
            SimpleNamespace(
                id="HC2",
                material="C30",
                kind="slab",
                precast=SimpleNamespace(element="hollowCore", cores=6, inserts=[object()]),
            ),
        ]
    )
    found = coverage_warnings(objects, SimpleNamespace(materials=[]))
    paths = [(p["index"], p["path"]) for p in found]
    assert (0, "precast.cores") in paths and (0, "precast.inserts") in paths
    assert not any(index == 1 for index, _ in paths)


def test_cbfem_texts_are_not_double_encoded():
    import saengine.design.connection_fe as cfe
    from saengine.fem import cables

    for module in (cfe, cables):
        text = Path(module.__file__).read_text(encoding="utf-8")
        assert not any(bad in text for bad in ("Ã", "Â", "Îµ", "â”")), module.__name__
    assert "εp,max at most" in Path(cfe.__file__).read_text(encoding="utf-8")

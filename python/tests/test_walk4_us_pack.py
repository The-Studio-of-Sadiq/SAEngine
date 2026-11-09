"""Walk 4 (W4-A) on the US pack (``aci318-asce7-22``, which extends ``bnbc2020``): a US project
shows ACI 318-19 / ASCE 7-22 text, never the default pack's (BNBC 2020) clauses.

- the pack declares the parent's tables that do not apply under its code (``notApplicable``):
  they are not inherited, the features that read them are not covered, the report lists them;
- the tables it keeps give its own sources (no table left inherited);
- the New Building notes, the report's front matter, seismic detailing chapter, tie beam method
  line and the drawings' general notes cite the active pack only;
- the default pack's text is unchanged.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

US = "aci318-asce7-22"
#: Text of the default pack a US output must not show.
BNBC_TEXT = re.compile(
    r"BNBC|Part 6|Sec 8\.3|Table 6\.[12]\.\d|Table 6\.6\.\d+(?![.\d])|Figure 6\.\d|eq\. 6\.|Eq\. 6\.|zone 4"
)

WIZARD = {
    "schema": "saengine.newBuilding/1",
    "name": "US4",
    "spacings": {"x": [6000, 6000, 6000], "y": [5000, 5000]},
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3500},
        {"id": "L2", "name": "Level 2", "elevation": 6500},
        {"id": "L3", "name": "Level 3", "elevation": 9500},
        {"id": "L4", "name": "Level 4", "elevation": 12500},
    ],
    "storyHeights": [3500, 3000, 3000, 3000],
    "system": "rcFrame",
    "designCode": US,
    "site": {
        "location": "custom",
        "spectral": {"sds": 1.0, "sd1": 0.6, "s1": 0.6, "tl": 8},
        "windSpeed": 43,
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


def _us():
    return registry.load(US)


def test_the_us_pack_inherits_no_table_and_declares_the_rest_not_applicable() -> None:
    pack = _us()
    assert not pack.broken
    inherited = [name for name in pack.tables() if pack.inherited_from(name)]
    assert inherited == []
    for name in ("zoneCoefficients", "planning", "bamboo", "hvac", "fireResistance"):
        assert name in pack.not_applicable
        assert not pack.has(name)
    # The tables it keeps say so in its own words.
    assert "Sec 4.9" in pack.table("cranes").source
    assert pack.table("cranes").impact["pendantOperated"] == pytest.approx(0.1)
    assert pack.table("mepOpenings").punchingDistance == pytest.approx(4)
    assert pack.table("foundations").shallow.exteriorDepth is None
    assert pack.table("siteInvestigation").siteClassification.byN[0].siteClass == "SC"
    # The default pack keeps every table.
    default = registry.load("bnbc2020")
    assert default.not_applicable == [] and default.has("zoneCoefficients")


def test_a_grandchild_inherits_the_declaration(tmp_path: Path) -> None:
    """A pack extending the US pack does not get its parent's not-applicable tables back."""
    import json

    root = tmp_path / "user" / "code-packs" / "us-local"
    root.mkdir(parents=True)
    (root / "pack.json").write_text(
        json.dumps(
            {"schema": "saengine.codePack/1", "id": "us-local", "name": "US local", "extends": US}
        ),
        encoding="utf-8",
    )
    registry.clear_cache()
    pack = registry.load("us-local")
    assert not pack.has("zoneCoefficients")
    assert "zoneCoefficients" in pack.not_applicable


def test_new_building_notes_cite_the_us_codes(tmp_path: Path) -> None:
    from saengine.project.new_building import create_building

    result = create_building(WIZARD, tmp_path)
    notes = "\n".join(result["notes"])
    found = BNBC_TEXT.findall(notes)
    assert not found, found
    assert "ASCE 7-22 Table 1.5-1" in notes
    assert "ACI 318-19 Table 9.3.1.1" in notes
    assert "Cs = 0.1250 g" in notes and "Sa = " not in notes
    assert "Special reinforced concrete moment frame" in notes


def test_report_front_matter_and_seismic_chapter_cite_the_us_codes() -> None:
    from saengine.library.settings import default_project_settings
    from saengine.report.build import _seismic_detailing, code_pack_text
    from saengine.report.document import _seismic

    settings = default_project_settings("US4").model_copy(update={"codePack": US})
    text = code_pack_text(settings)
    assert text.startswith("ACI 318-19 + ASCE 7-22 (aci318-asce7-22)")
    scope = {
        "sdc": "D",
        "zone": 4,
        "systemName": "Special reinforced concrete moment frame",
        "detailingLevel": "special",
        "requiredFrameType": "special",
        "systemFrameType": "special",
        "checks": [],
        "applies": {
            "8.3.3": {
                "applies": True,
                "title": "General requirements",
                "page": 1089,
                "members": "all",
            },
            "8.3.11": {
                "applies": True,
                "title": "Foundations",
                "page": 1120,
                "members": "footings",
            },
        },
    }
    with code_context.using(_us()):
        chapter = _seismic_detailing({"seismic": scope, "elements": []})
        blocks = _seismic(
            {"design": {"available": True, "seismic": {**chapter, "available": True}}}, None
        )
    flat = repr(chapter) + repr(blocks)
    assert not BNBC_TEXT.findall(flat), BNBC_TEXT.findall(flat)
    assert ["18.2", "General requirements", "–", "yes", "all"] in chapter["applies"]
    assert not any(row[0] == "Zone" for row in chapter["lines"])


def test_bnbc_seismic_chapter_unchanged() -> None:
    from saengine.report.build import _seismic_detailing

    scope = {
        "sdc": "D",
        "zone": 4,
        "systemName": "RC special moment frame",
        "detailingLevel": "special",
        "requiredFrameType": "special",
        "systemFrameType": "special",
        "checks": [],
        "applies": {
            "8.3.3": {
                "applies": True,
                "title": "General requirements",
                "page": 1089,
                "members": "all",
            }
        },
    }
    with code_context.using(registry.load("bnbc2020")):
        chapter = _seismic_detailing({"seismic": scope, "elements": []})
    assert ["8.3.3", "General requirements", "p. 1089", "yes", "all"] in chapter["applies"]
    assert ["Zone", "4"] in chapter["lines"]
    assert any("(Sec 8.3.2; the category" in row[1] for row in chapter["lines"])


def test_tie_beams_and_drawing_notes_cite_the_us_codes() -> None:
    from saengine.drawings.sheets.project import general_notes
    from saengine.substructure.shallow import shallow_method

    with code_context.using(_us()):
        lines = shallow_method()
        notes = general_notes(None, None, {})
    text = "\n".join([*lines, *notes])
    assert not BNBC_TEXT.findall(text), BNBC_TEXT.findall(text)
    assert "seismic zones" not in text
    assert any("ACI 318-19" in n for n in notes)


def test_fire_resistance_not_covered_under_the_us_pack() -> None:
    from saengine.design.fire_resistance import covered

    with code_context.using(_us()):
        assert not covered()
    with code_context.using(registry.load("bnbc2020")):
        assert covered()

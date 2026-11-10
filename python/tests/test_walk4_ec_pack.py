"""Walk 4 (W4-A) on the Eurocodes pack (``eurocodes``, which extends ``bnbc2020``) and the UK
National Annex pack (``eurocodes-uk``): a Eurocode project shows EN text, never the default
pack's (BNBC 2020) clauses.

- the pack declares the parent's tables that do not apply under the Eurocodes
  (``notApplicable``); every other table it used to inherit is its own (EN sources, EN values,
  or SAEngine practice where the Eurocodes give none);
- the New Building notes, the seismic detailing chapter, the face and shear-at-d clauses, the
  tie beam method line, the foundation text and the drawings' notes cite the active pack only;
- the site messages name the pack's hazard inputs (agR, vb,0), not Z of Table 6.2.14;
- a pack switch offers the new pack's live loads (W4A-22) and the Wind page's meaning (W4A-23);
- the default pack's text is unchanged.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

EC = "eurocodes"
UK = "eurocodes-uk"
#: Text of the default pack a Eurocode output must not show.
BNBC_TEXT = re.compile(
    r"BNBC|Part 6|Sec 8\.3|Table 6\.[12]\.\d|Table 6\.6\.\d+(?![.\d])|Figure 6\.\d|eq\. 6\.|"
    r"Eq\. 6\.|BDS|6\.1\.6\.3|6\.4\.1\.3\.1"
)

WIZARD = {
    "schema": "saengine.newBuilding/1",
    "name": "UK4",
    "spacings": {"x": [6000, 6000, 6000], "y": [5000, 5000]},
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3500},
        {"id": "L2", "name": "Level 2", "elevation": 6500},
    ],
    "storyHeights": [3500, 3000],
    "system": "rcFrame",
    "designCode": UK,
    "site": {"location": "london", "siteClass": "C"},
    "wind": {"exposure": "III"},
    "occupancy": {"use": "office"},
}


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.mark.parametrize("pack_id", [EC, UK])
def test_no_table_from_the_default_pack(pack_id: str) -> None:
    pack = registry.load(pack_id)
    assert not pack.broken
    from_default = [name for name in pack.tables() if pack.inherited_from(name) == "BNBC 2020"]
    assert from_default == []
    for name in ("planning", "hvac", "fireResistance", "anchors", "plumbing"):
        assert name in pack.not_applicable
        assert not pack.has(name)
    # No string of any table it has names the default pack (its own sources, or practice).
    for name in pack.tables():
        found = re.search(r"BNBC|Part 6|Bangladesh|BDS", repr(pack.table(name).model_dump()))
        assert found is None, name


def test_own_values() -> None:
    pack = registry.load(EC)
    shallow = pack.table("foundations").shallow
    assert shallow.exteriorDepth is None and shallow.raftDepth is None
    assert shallow.columnBase.areaRatioMax == pytest.approx(3.0)
    assert "EN 1992-1-1 6.7" in pack.table("foundations").sources["shallow.columnBase"]
    assert "γC = 1.5" in pack.table("factors").source
    assert pack.table("materials").seismicRebarFyMax == pytest.approx(500.0)
    # The default pack keeps its own.
    default = registry.load("bnbc2020")
    assert default.table("foundations").shallow.exteriorDepth is not None


def test_new_building_notes_cite_the_eurocodes(tmp_path: Path) -> None:
    from saengine.project.new_building import create_building

    result = create_building(WIZARD, tmp_path)
    notes = "\n".join(result["notes"])
    found = BNBC_TEXT.findall(notes)
    assert not found, found


def test_design_clauses_of_face_forces_and_seismic_chapter() -> None:
    from saengine.design import face_forces
    from saengine.report.build import _seismic_detailing

    scope = {
        "sdc": "D",
        "zone": 3,
        "systemName": "Frame system DCM",
        "detailingLevel": "special",
        "requiredFrameType": "special",
        "systemFrameType": "special",
        "checks": [],
        "applies": {
            "8.3.3": {"applies": True, "title": "General requirements", "members": "all"},
            "8.3.11": {"applies": True, "title": "Foundations", "members": "footings"},
        },
    }
    with code_context.using(registry.load(UK)):
        texts = [face_forces.FACE_CLAUSE, face_forces.SHEAR_CLAUSE, face_forces.COLUMN_PRACTICE]
        chapter = _seismic_detailing({"seismic": scope, "elements": []})
    flat = repr(texts) + repr(chapter)
    assert not BNBC_TEXT.findall(flat), BNBC_TEXT.findall(flat)
    assert "EN 1992-1-1 5.3.2.2(3)" in texts[0]
    assert "EN 1992-1-1 6.2.1(8)" in texts[1]
    # The UK NA adopts the Eurocodes' clauses (own_text: only the default pack's are hidden).
    assert ["EN 1998-1 5.2", "General requirements", "–", "yes", "all"] in chapter["applies"]


class _Empty(dict):
    """A foundations result without designs: every list it is asked for is empty."""

    def __missing__(self, key: str) -> list:
        return []


def test_tie_beams_foundation_text_and_drawing_notes() -> None:
    from saengine.drawings.sheets.project import general_notes
    from saengine.report.document import _foundations
    from saengine.substructure.shallow import shallow_method

    with code_context.using(registry.load(UK)):
        lines = shallow_method()
        notes = general_notes(None, None, {})
        blocks = _foundations({"foundations": _Empty(available=True)}, None)
    text = "\n".join([*lines, *notes]) + repr(blocks)
    assert not BNBC_TEXT.findall(text), BNBC_TEXT.findall(text)
    assert "EN 1992-1-1 6.4 for punching" in repr(blocks)


def test_site_messages_name_the_packs_inputs() -> None:
    from saengine.library.settings import site_input_text

    uk = registry.load(UK)
    assert "agR" in site_input_text(uk, "zone") and "6.2.14" not in site_input_text(uk, "zone")
    assert "vb,0" in site_input_text(uk, "wind")
    default = registry.load("bnbc2020")
    assert site_input_text(default, "zone") == "seismic zone coefficient Z (Table 6.2.14)"
    assert site_input_text(default, "wind", False) == "basic wind speed V"


def test_pack_switch_offers_the_new_packs_live_loads() -> None:
    from saengine.library.settings import area_loads_from_pack, default_project_settings

    with code_context.using(registry.load(EC)):
        settings = default_project_settings("EC4").model_copy(update={"codePack": EC})
    office = settings.areaLoads[0].model_copy(update={"use": "office", "live": 3.0})
    settings = settings.model_copy(update={"areaLoads": [office, *settings.areaLoads[1:]]})
    uk = registry.load(UK)
    rows, changed = area_loads_from_pack(settings, uk)
    uses = uk.table("areaLoads").uses
    assert rows[0].live == pytest.approx(uses["office"].live)
    if uses["office"].live != 3.0:
        assert office.id in changed
    assert rows[0].finish == office.finish
    again, none = area_loads_from_pack(settings.model_copy(update={"areaLoads": rows}), uk)
    assert none == [] and again == rows


def test_wind_page_words_of_the_pack() -> None:
    from saengine.library.settings import pack_choices

    fields = {r["id"]: r["label"] for r in pack_choices(registry.load(EC))["windFields"]}
    assert "cdir" in fields["wind.directionality"]
    assert "co" in fields["wind.topographic"]
    assert "windFields" not in pack_choices(registry.load("bnbc2020"))


def test_bnbc_face_clauses_unchanged() -> None:
    from saengine.design import face_forces

    with code_context.using(registry.load("bnbc2020")):
        assert face_forces.FACE_CLAUSE == "BNBC 2020 Part 6 Sec 6.1.6.3"
        assert face_forces.SHEAR_CLAUSE == "BNBC 2020 Part 6 Sec 6.4.1.3.1"

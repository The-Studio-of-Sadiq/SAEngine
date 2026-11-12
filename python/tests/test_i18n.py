"""The reports' and drawings' language (saengine.i18n)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from saengine import i18n
from saengine.library.settings import ProjectInfo

CATALOGUE = Path(i18n.__file__).with_name("bn.json")


def test_english_is_unchanged():
    assert i18n.translate("Settlement [mm]", "en") == "Settlement [mm]"
    assert i18n.translate("12.5 kN", "en") == "12.5 kN"
    doc = i18n.localize_document({"sections": []}, "en")
    assert doc["lang"] == "en" and doc["labels"]["fail"] == "FAIL"


def test_bangla_labels_and_digits():
    assert i18n.translate("Check", "bn") == "চেক"
    assert i18n.translate("12.5 kN", "bn") == "১২.৫ kN"
    assert i18n.translate("250 x 500", "bn") == "২৫০ x ৫০০"
    assert i18n.translate("SCALE 1:100   LEVEL +3.000", "bn") == "স্কেল ১:১০০   লেভেল +৩.০০০"


def test_units_clauses_and_identifiers_stay():
    for text in ("C1", "S-101", "B1-T2", "1.2D + 1.6L", "BNBC 2020 Part 6 Sec 6.3.10.6"):
        assert i18n.translate(text, "bn") == text
    assert i18n.localize_digits("Sec 8.3.5.2 and 8.3.6.6: 12") == "Sec 8.3.5.2 and 8.3.6.6: ১২"
    assert i18n.localize_digits("Table 8.5.1") == "Table 8.5.1"


def test_english_text_keeps_its_digits():
    # a sentence the catalogue does not know stays English, digits included
    assert i18n.translate("Story 3 fails", "bn") == "Story 3 fails"


def test_project_language():
    assert ProjectInfo(name="P").language == "en"
    assert i18n.project_language({"project": {"name": "P", "language": "bn"}}) == "bn"
    assert i18n.project_language({"project": {"language": "xx"}}) == "en"
    assert i18n.project_language(None) == "en"


def test_document_fail_label_matches_cells():
    doc = {
        "sections": [
            {
                "title": "Member design",
                "blocks": [{"t": "table", "head": ["Result"], "rows": [["FAIL"]]}],
            }
        ]
    }
    out = i18n.localize_document(doc, "bn")
    assert out["sections"][0]["blocks"][0]["rows"][0][0] == out["labels"]["fail"]
    assert out["sections"][0]["title"] == "মেম্বার ডিজাইন"


def test_catalogue_keeps_placeholders_and_line_breaks():
    messages = json.loads(CATALOGUE.read_text(encoding="utf-8"))["messages"]
    for english, bangla in messages.items():
        assert sorted(re.findall(r"\{\d+\}", english)) == sorted(re.findall(r"\{\d+\}", bangla))
        assert english.count("\n") == bangla.count("\n"), english


def test_registered_pack_messages_win():
    i18n.register_messages("bn", {"Check": "যাচাই"})
    try:
        assert i18n.translate("Check", "bn") == "যাচাই"
    finally:
        i18n._extra.clear()
        i18n.clear_cache()


def test_language_pack_files_are_checked(tmp_path):
    from saengine.codes.contents import check_language_pack

    (tmp_path / "messages").mkdir()
    (tmp_path / "messages" / "bn.json").write_text(
        json.dumps({"language": "bn", "messages": {"Check {0}": "চেক", "Date": "তারিখ"}}),
        encoding="utf-8",
    )
    problems = check_language_pack(tmp_path, ["messages/bn.json"], "bn")
    assert [p.message for p in problems] == ["'Check {0}': the placeholders differ"]
    assert check_language_pack(tmp_path, [], None)  # no language, no files

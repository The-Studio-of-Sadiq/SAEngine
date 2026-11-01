"""The AI assistant's retrieval over the code pack (saengine.ai.knowledge, round T49).

The assistant may cite only what this search returns, so the tests pin that the BNBC 2020
values come back with their clauses and that an unrelated question finds nothing.
"""

from __future__ import annotations

from saengine.ai import knowledge
from saengine.rpc import handlers


def test_tokenize_keeps_clause_numbers_and_their_sections() -> None:
    tokens = knowledge.tokenize("What does Table 6.2.14 give?")
    assert "6.2.14" in tokens
    assert "6.2" in tokens
    assert "what" not in tokens


def test_clause_numbers_skip_decimals_below_one() -> None:
    assert knowledge.clause_numbers("Table 6.2.14 and a ratio of 0.20") == ["6.2.14"]


def test_pack_passages_carry_entry_and_table_citations() -> None:
    data = {
        "$sources": ["T 1.1"],
        "systems": {
            "a": {"name": "Frame A", "R": 8.0, "row": "C.4 (p. 623)", "pad": "x" * 800},
            "b": {"name": "Frame B", "R": 5.0, "row": "C.5 (p. 623)"},
        },
    }
    passages = {p.title: p for p in knowledge.pack_passages("seismic", data, ["T 1.1"])}
    assert passages["seismic.systems.a"].citations[0] == "C.4 (p. 623)"
    assert "T 1.1" in passages["seismic.systems.a"].citations


def test_bnbc_zone_coefficients_are_found_with_table_6_2_14() -> None:
    # BNBC 2020 Part 6 Table 6.2.14 (p. 615): the seismic zone coefficients.
    result = knowledge.search_code("seismic zone coefficient Table 6.2.14", include_docs=False)
    assert result["found"]
    assert result["pack"]["id"] == "bnbc2020"
    top = result["passages"][0]
    assert any("6.2.14" in c for c in top["citations"])


def test_bnbc_special_moment_frame_r_is_8() -> None:
    # BNBC 2020 Part 6 Table 6.2.19 row C.4 (p. 623): RC special moment frame, R = 8.
    result = knowledge.search_code(
        "RC special moment frame response reduction R", include_docs=False
    )
    texts = [p["text"] for p in result["passages"]]
    assert any('"name": "RC special moment frame", "R": 8.0' in t for t in texts)


def test_unrelated_question_finds_nothing() -> None:
    result = knowledge.search_code("quantum chromodynamics gluon", include_docs=False)
    assert result["found"] is False
    assert result["passages"] == []


def test_handler_refuses_an_empty_query() -> None:
    assert handlers.ai_search_code("  ")["ok"] is False

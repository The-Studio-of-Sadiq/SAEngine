"""Independent known-answer tests for standalone calculators in the Exports window."""

from __future__ import annotations

from saengine import features


def test_exports_fabrication_rebar_tagging() -> None:
    # 5 marks packed at max 2 per bundle -> ceil(5 / 2) = 3 bundles:
    # M1, M2 -> BND-001 (pos 1, 2); M3, M4 -> BND-002 (pos 1, 2); M5 -> BND-003 (pos 1).
    res = features.run(
        "exportsFabrication.rebarTagging",
        None,
        {"marks": "M1,M2,M3,M4,M5", "maximumPerBundle": 2, "prefix": "BND"},
    )
    assert res["problems"] == []
    assert res["summary"]["barMarkCount"] == 5
    assert res["summary"]["bundleCount"] == 3
    rows = res["tables"][0]["rows"]
    assert rows[0] == {"mark": "M1", "bundle": "BND-001", "positionInBundle": 1}
    assert rows[2] == {"mark": "M3", "bundle": "BND-002", "positionInBundle": 1}
    assert rows[4] == {"mark": "M5", "bundle": "BND-003", "positionInBundle": 1}

"""Walk 4 (W4-A) on the Eurocodes UK National Annex pack (``eurocodes-uk``):

- W4A-1: the New Building wizard under a pack with no period cap (Cu) — EN 1998-1 has none —
  sizes the building (the period is used as computed, with a note) instead of failing;
- W4A-2: Project Settings > Load Combinations generates the ACTIVE pack's combinations
  (``codes/combinations``), and tells whether the project's are those already;
- W4A-3: the report's load combination text describes the rows of its table: the pack's basis
  only when the project's combinations are the ones the pack generates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import registry

WIZARD = {
    "schema": "saengine.newBuilding/1",
    "name": "UK2",
    "spacings": {"x": [6000, 6000], "y": [5000]},
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3500},
        {"id": "L2", "name": "Level 2", "elevation": 7000},
    ],
    "storyHeights": [3500, 3500],
    "system": "rcFrame",
    "designCode": "eurocodes-uk",
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


def test_period_ratio_without_a_cap_is_not_checked() -> None:
    from saengine.library.generator import PERIOD_TARGET, period_ratio

    assert period_ratio(1.2, None) == 0.0
    assert period_ratio(1.5, 1.0) == pytest.approx((1.5 / PERIOD_TARGET) ** 2)


def test_uk_wizard_creates_the_building_with_the_uk_combinations(tmp_path: Path) -> None:
    from saengine.project.new_building import create_building

    result = create_building(WIZARD, tmp_path)
    root = Path(result["root"])
    assert root.is_dir()
    notes = " ".join(result["notes"])
    # W4A-1: no Cu in EN 1998-1: the period is used as computed, and the note says so.
    assert "gives no upper limit on the period (no Cu)" in notes
    settings = json.loads(
        (root / "02 Project Settings" / "project-settings.json").read_text(encoding="utf-8")
    )
    assert settings["codePack"] == "eurocodes-uk"
    names = [c["name"] for c in settings["combinations"]]
    # UK NA Table NA.A1.2(B): Eqs 6.10a/b with ξ 0.925 (1.25G) and ψ0 of the wind 0.5 (0.75W).
    assert "1.35G + 1.05Q + 0.75S + 0.75WX" in names
    assert "1.25G + 1.5Q + 0.75S" in names
    assert not any("0.9W" in n for n in names)


def test_the_generated_stiffness_summary_has_no_period_limit() -> None:
    from saengine.library.generator import generate_building
    from saengine.project.new_building import spec_from_wizard

    spec, _ = spec_from_wizard(WIZARD)
    stiffness = generate_building(spec)["summary"]["stiffness"]
    # The lateral sizing ran (the wind sway), with no cap to report.
    assert stiffness["periodLimit"] is None and stiffness["periodTarget"] is None
    assert stiffness["ta"] > 0


def _uk_settings(kept_from: str | None = None):
    from saengine.library.settings import default_project_settings

    if kept_from is None:
        return default_project_settings("UK", code_pack="eurocodes-uk")
    # The project switched to the UK pack in Project Settings, its combinations kept.
    settings = default_project_settings("UK", code_pack=kept_from)
    return settings.model_copy(update={"codePack": "eurocodes-uk"})


def test_codes_combinations_generates_the_active_pack() -> None:
    from saengine.rpc.handlers import codes_combinations

    kept = _uk_settings("eurocodes")
    answer = codes_combinations(json.dumps(kept.model_dump(mode="json", by_alias=True)))
    assert answer["id"] == "eurocodes-uk"
    assert answer["fromPack"] is False  # still the recommended values (0.9W)
    names = [c["name"] for c in answer["combinations"]]
    assert "1.25G + 1.5Q + 0.75S + 0.75WX" in names
    assert not any("1.2D" in n or "0.9W" in n for n in names)  # not BNBC, not EN recommended
    fresh = _uk_settings()
    again = codes_combinations(json.dumps(fresh.model_dump(mode="json", by_alias=True)))
    assert again["fromPack"] is True


def test_codes_combinations_refuses_an_unknown_pack() -> None:
    from saengine.library.settings import default_project_settings
    from saengine.rpc.handlers import codes_combinations

    data = default_project_settings("X").model_dump(mode="json", by_alias=True)
    data["codePack"] = "no-such-pack"
    assert codes_combinations(json.dumps(data))["ok"] is False


def test_report_text_matches_the_combinations_table() -> None:
    from saengine.report.build import _basis, _Parts

    uk = registry.load("eurocodes-uk").table("combinations")
    fresh = _basis(_uk_settings(), _Parts(Path("."), []), {}, {})["combinations"]
    assert fresh["fromPack"] is True and fresh["source"] == uk.source
    assert "ξ 0.925" in fresh["source"]
    rows = [r[0] for r in fresh["rows"]]
    assert "1.25G + 1.5Q + 0.75S + 0.75WX" in rows
    # Kept from the recommended values: the UK basis is not claimed for 0.9W rows.
    kept = _basis(_uk_settings("eurocodes"), _Parts(Path("."), []), {}, {})["combinations"]
    assert kept["fromPack"] is False
    assert "NA.A1.2" not in kept["source"] and "NOT the combinations" in kept["source"]
    assert any("0.9WX" in r[0] for r in kept["rows"])


def test_the_default_pack_report_text_is_unchanged() -> None:
    from saengine.library.settings import default_project_settings
    from saengine.report.build import _basis, _Parts

    basis = _basis(default_project_settings("B"), _Parts(Path("."), []), {}, {})
    combos = basis["combinations"]
    assert combos["fromPack"] is True
    assert combos["source"] == registry.load("bnbc2020").table("combinations").source

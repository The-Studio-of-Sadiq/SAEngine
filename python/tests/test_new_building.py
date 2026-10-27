"""The New Building glue (:mod:`saengine.project.new_building`): the wizard's site class and
the project folder it may write into."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from saengine.library.generator import generate_building
from saengine.project.new_building import (
    NewBuildingError,
    create_building,
    project_parent,
    spec_from_wizard,
)

WIZARD = {
    "schema": "saengine.newBuilding/1",
    "name": "Site Test",
    "spacings": {"x": [5000], "y": [4000]},
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3200},
    ],
    "storyHeights": [3200],
    "system": "rcFrame",
    "site": {"location": "dhaka", "siteClass": "SD", "siteClassSource": "assumed"},
}


def test_wizard_site_class_is_mapped_as_assumed() -> None:
    spec, _ = spec_from_wizard(WIZARD)
    assert (spec["location"], spec["siteClass"], spec["siteClassSource"]) == (
        "dhaka",
        "SD",
        "assumed",
    )
    # No source given: the wizard's class is an assumption.
    spec, _ = spec_from_wizard({**WIZARD, "site": {"location": "dhaka", "siteClass": "SC"}})
    assert (spec["siteClass"], spec["siteClassSource"]) == ("SC", "assumed")
    with pytest.raises(NewBuildingError, match="site class 'S1'"):
        spec_from_wizard({**WIZARD, "site": {"siteClass": "S1"}})
    with pytest.raises(NewBuildingError, match="site class source"):
        spec_from_wizard({**WIZARD, "site": {"siteClass": "SD", "siteClassSource": "guess"}})


def test_assumed_site_class_is_patched_and_noted() -> None:
    spec, _ = spec_from_wizard({**WIZARD, "site": {**WIZARD["site"], "siteClass": "SE"}})
    result = generate_building({**spec, "lateralSizing": "gravity"})
    # The settings have no "assumed" source: "soilReport" keeps the class until 1 Soil
    # Report's boreholes give one.
    assert result["settingsPatch"]["site"] == {
        "location": "dhaka",
        "siteClass": "SE",
        "siteClassSource": "soilReport",
    }
    assert result["settings"]["site"]["siteClass"] == "SE"
    assert any(n.startswith("Site class SE ASSUMED (no soil report yet)") for n in result["notes"])
    assert any("site class SE assumed," in n for n in result["notes"])
    # Entered (the generator's own spec): kept as entered, no assumption note.
    entered = generate_building({**spec, "siteClassSource": "entered", "lateralSizing": "gravity"})
    assert entered["settingsPatch"]["site"]["siteClassSource"] == "entered"
    assert not any("ASSUMED" in n for n in entered["notes"])


@pytest.mark.parametrize("bad", ["C:Users", "c:Users\\me", "\\Users", "\\Users\\me", "relative"])
def test_refuses_a_folder_that_is_not_absolute(
    bad: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Never resolved against the current folder: nothing is written there.
    monkeypatch.chdir(tmp_path)
    with pytest.raises(NewBuildingError, match="not a full folder path"):
        create_building(WIZARD, bad)
    assert list(tmp_path.iterdir()) == []


def test_refuses_a_folder_that_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere"
    with pytest.raises(NewBuildingError, match="does not exist"):
        create_building(WIZARD, missing)
    assert not missing.exists()
    a_file = tmp_path / "file.txt"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(NewBuildingError, match="does not exist"):
        project_parent(a_file)
    with pytest.raises(NewBuildingError, match="give the folder"):
        project_parent("  ")


def test_accepts_absolute_folders(tmp_path: Path) -> None:
    assert project_parent(tmp_path) == tmp_path
    assert project_parent(str(tmp_path)) == tmp_path
    if os.name == "nt":
        # Forward slashes with a drive are absolute too.
        assert project_parent(str(tmp_path).replace("\\", "/")) == tmp_path
    result = create_building({**WIZARD, "site": {"location": "dhaka"}}, tmp_path)
    assert Path(result["root"]) == tmp_path / "Site Test"

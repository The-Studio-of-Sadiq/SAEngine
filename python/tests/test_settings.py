"""Project settings (02 Project Settings/project-settings.json) and the BNBC 2020 tables."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from saengine.library import ProjectSettings, default_project_settings
from saengine.library.check import check_library
from saengine.library.settings import derived, strength_combinations


def settings(**changes: object) -> dict:
    return {
        **default_project_settings("Tower").model_dump(
            mode="json", by_alias=True, exclude_none=True
        ),
        **changes,
    }


def test_defaults_follow_bnbc_2020() -> None:
    default = default_project_settings("Tower")
    assert ProjectSettings.model_validate(default.model_dump(mode="json", by_alias=True)) == default
    assert derived(default) == {
        "zone": 2,
        "Z": 0.2,
        "windSpeed": 65.7,
        "seismicImportance": 1.0,
        "windImportance": 1.0,
        "R": 5.0,
        "omega": 3.0,
        "Cd": 4.5,
    }
    assert [(a.id, a.live) for a in default.areaLoads] == [("FL", 2.0), ("ST", 4.8), ("RF", 1.0)]


def test_derived_values_follow_location_category_system_and_overrides() -> None:
    chattogram = ProjectSettings.model_validate(
        settings(
            site={"location": "chattogram", "siteClass": "SC"},
            occupancy={"use": "healthcare", "category": "IV"},
            seismic={"system": "rcSmf", "r": 7.0},
        )
    )
    assert derived(chattogram) == {
        "zone": 3,
        "Z": 0.28,
        "windSpeed": 80.0,
        "seismicImportance": 1.5,
        "windImportance": 1.15,
        "R": 7.0,
        "omega": 3.0,
        "Cd": 5.5,
    }


def test_strength_combinations() -> None:
    combinations = {c.name: c for c in strength_combinations()}
    assert len(combinations) == 23
    assert combinations["1.2D + 1.6L + 0.5Lr"].model_dump() == {
        "name": "1.2D + 1.6L + 0.5Lr",
        "D": 1.2,
        "L": 1.6,
        "Lr": 0.5,
        "WX": 0,
        "WY": 0,
        "EX": 0,
        "EY": 0,
    }
    assert combinations["0.9D + 1.0(-EY)"].EY == -1.0
    assert combinations["1.2D + 1.6WX + 1.0L + 0.5Lr"].WX == 1.6


def test_check_reports_code_minimums_and_references() -> None:
    data = settings(
        areaLoads=[{"id": "FL", "name": "Office", "use": "office", "live": 2.0}],
        roofLoad="RF",
        site={"location": "custom"},
    )
    assert [p["message"] for p in check_library("settings", json.dumps(data))] == [
        "roofLoad: there is no area load 'RF'",
        "FL: live load 2.0 kN/m² is below the BNBC 2020 minimum of 2.4 kN/m² for office",
        "site: a custom location needs the seismic zone coefficient Z",
        "site: a custom location needs the basic wind speed",
    ]
    with pytest.raises(ValidationError):
        ProjectSettings.model_validate(settings(site={"location": "atlantis"}))

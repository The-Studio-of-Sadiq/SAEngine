"""Project settings (02 Project Settings/project-settings.json) and the BNBC 2020 tables."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from saengine.library import ProjectSettings, default_project_settings
from saengine.library.check import check_library
from saengine.library.settings import LoadCombination, derived, problems, strength_combinations


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
        "R": 8.0,
        "omega": 3.0,
        "Cd": 5.5,
        # B2: by direction (Sec 2.5.5.5.1), the same with one system
        "RX": 8.0,
        "RY": 8.0,
        "CdX": 5.5,
        "CdY": 5.5,
        "omegaX": 3.0,
        "omegaY": 3.0,
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
        # B2: the override applies in both directions
        "RX": 7.0,
        "RY": 7.0,
        "CdX": 5.5,
        "CdY": 5.5,
        "omegaX": 3.0,
        "omegaY": 3.0,
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
        "T": 0,
        "ST": 0,
        "F": 1.2,
        "H": 1.6,
    }
    assert combinations["0.9D + 1.0(-EY)"].EY == -1.0
    assert combinations["1.2D + 1.6WX + 1.0L + 0.5Lr"].WX == 1.6


def test_fluid_factor_follows_the_dead_load() -> None:
    # BNBC 2020 2.7.3.1: F with D in 1.4(D + F) and 1.2(D + F + T) + ...; none with 0.9D.
    combinations = {c.name: c for c in strength_combinations()}
    assert combinations["1.4D"].F == 1.4
    assert combinations["1.2D + 1.0EX + 1.0L"].F == 1.2
    assert combinations["0.9D + 1.6WX"].F == 0.0
    # A saved file's own factor stays; an old file without F gets it from D.
    assert LoadCombination(name="c", D=1.2, F=0.0).F == 0.0
    assert LoadCombination.model_validate({"name": "old", "D": 1.4}).F == 1.4


def test_temperature_combinations() -> None:
    # BNBC 2020 Part 6 Sec 2.7.3.1 combination 2 with ±T, right after the one without T; T is
    # not combined with wind or earthquake.
    names = [c.name for c in strength_combinations(thermal=True)]
    assert len(names) == 25
    at = names.index("1.2D + 1.6L + 0.5Lr")
    assert names[at + 1 : at + 3] == ["1.2D + 1.2T + 1.6L + 0.5Lr", "1.2D - 1.2T + 1.6L + 0.5Lr"]
    falling = {c.name: c for c in strength_combinations(thermal=True)}["1.2D - 1.2T + 1.6L + 0.5Lr"]
    assert (falling.D, falling.T, falling.L, falling.Lr, falling.F) == (1.2, -1.2, 1.6, 0.5, 1.2)
    assert all(not c.T for c in strength_combinations(thermal=True) if c.WX or c.WY or c.EX or c.EY)


def test_check_reports_code_minimums_and_references() -> None:
    data = settings(
        areaLoads=[{"id": "FL", "name": "Office", "use": "office", "live": 2.0}],
        roofLoad="RF",
        site={"location": "custom"},
    )
    assert [p["message"] for p in check_library("settings", json.dumps(data))] == [
        "there is no area load 'RF'",
        (
            "FL: live load 2 kN/m² is below the BNBC 2020 minimum of 2.4 kN/m² for office "
            "(BNBC 2020 Part 6 Table 6.2.3, Office buildings, offices (p. 535))"
        ),
        "a custom location needs the seismic zone coefficient Z (Table 6.2.14)",
        "a custom location needs the basic wind speed V (Table 6.2.8)",
    ]
    assert [p["path"] for p in check_library("settings", json.dumps(data))] == [
        "roofLoad",
        "areaLoads.0.live",
        "site.zoneCoefficient",
        "site.windSpeed",
    ]
    with pytest.raises(ValidationError):
        ProjectSettings.model_validate(settings(site={"location": "atlantis"}))


def test_system_is_checked_against_the_seismic_design_category() -> None:
    """BNBC 2020 Part 6 Table 6.2.18 (p. 617): Dhaka (zone 2) on SD, occupancy II is Category
    D, where an RC intermediate or ordinary moment frame is NP (Table 6.2.19 rows C.5, p. 623)."""
    from saengine.library.settings import design_category

    for system in ("rcImf", "rcOmf"):
        data = settings(seismic={"system": system})
        problems = check_library("settings", json.dumps(data))
        assert [p["path"] for p in problems] == ["seismic.system"]
        assert "not permitted in Seismic Design Category D" in problems[0]["message"]
    assert check_library("settings", json.dumps(settings())) == []
    info = design_category(ProjectSettings.model_validate(settings()))
    assert (info["sdc"], info["detailing"], info["required"]) == ("D", "special", "special")
    # Rajshahi (zone 1) on SC, occupancy II: Category B, where an IMF is permitted.
    rajshahi = settings(
        site={"location": "rajshahi", "siteClass": "SC", "siteClassSource": "entered"},
        seismic={"system": "rcImf"},
    )
    assert check_library("settings", json.dumps(rajshahi)) == []


def test_override_values_out_of_the_code_range_are_reported() -> None:
    data = settings(site={"location": "dhaka", "zoneCoefficient": 0.6, "windSpeed": 250})
    assert [p["path"] for p in check_library("settings", json.dumps(data))] == [
        "site.zoneCoefficient",
        "site.windSpeed",
    ]


def test_code_basis_comes_from_the_pack() -> None:
    from saengine.library.settings import code_basis

    basis = code_basis(default_project_settings("Tower"))
    assert basis.rows() == [
        ["Loads and general", "BNBC 2020"],
        ["Concrete", "BNBC 2020 Part 6 Chapter 6"],
        ["Steel", "BNBC 2020 Part 6 Chapter 10"],
        ["Design method", "Strength design (LRFD)"],
    ]


def test_old_codes_are_read_but_not_written_back() -> None:
    from saengine.pipeline.status import holds_defaults

    old = settings(
        codes={
            "general": "BNBC 2020",
            "concrete": "ACI 318-19",
            "steel": "AISC 360-22",
            "method": "strength",
        }
    )
    model = ProjectSettings.model_validate(old)
    assert model.codes is not None and model.codes.concrete == "ACI 318-19"
    assert "codes" not in model.model_dump(mode="json", by_alias=True)
    assert holds_defaults(old, "settings")
    assert ProjectSettings.model_json_schema()["properties"]["codes"]["deprecated"] is True


def test_reduced_live_factor_follows_the_pack_exception() -> None:
    # BNBC 2020 Part 6 Sec 2.7.3.1 exception 1 (p. 685): 0.5L in combinations 3, 4 and 5 where
    # every live load is at most 5.0 kN/m², not for garages or assembly.
    default = default_project_settings("Tower")
    default.analysis.reducedLiveFactor = True
    names = [c.name for c in strength_combinations(settings=default)]
    assert "1.2D + 1.6Lr + 0.5L" in names and "1.2D + 1.0EX + 0.5L" in names
    assert "1.2D + 1.6L + 0.5Lr" in names  # combination 2 keeps 1.6L
    default.areaLoads[0].use = "parking"
    names = [c.name for c in strength_combinations(settings=default)]
    assert "1.2D + 1.6Lr + 1.0L" in names
    assert any(p[0] == "analysis.reducedLiveFactor" for p in problems(default))


def test_partition_allowance_minimum() -> None:
    # BNBC 2020 Part 6 Sec 2.3.6 (p. 538): at least 1.2 kN/m².
    default = default_project_settings("Tower")
    assert default.areaLoads[0].partitions == 1.2
    default.areaLoads[0].partitions = 1.0
    assert any(p[0] == "areaLoads.0.partitions" for p in problems(default))

"""The report on a freshly generated project: the analysis model it derives is current (the
settings stamp the derivation records is the one the report checks), and the detailing table
lists what fails, joints included (alpha 6 release gate)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from saengine.library.generator import generate_building, write_building
from saengine.report.build import (
    MODEL_FILE,
    SETTINGS_FILE,
    _failed_text,
    _model_summary,
    _Parts,
    _seismic_detailing,
)
from saengine.rpc.handlers import derive_fem

STALE = "derived from earlier versions"


def _derive(root: Path) -> dict[str, Any]:
    def text(relative: str) -> str:
        return (root / relative).read_text(encoding="utf-8")

    result = derive_fem(
        text("06 BIM/bim.json"),
        text("04 Objects/objects.json"),
        text("03 Materials/materials.json"),
        text(SETTINGS_FILE),
        str(root / "08 FEM"),
    )
    assert "problems" not in result, result
    (root / MODEL_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / MODEL_FILE).write_text(result["text"], encoding="utf-8")
    return json.loads(result["text"])


def _warnings(root: Path, model: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    parts = _Parts(root, warnings)
    _model_summary(root, model, {}, parts, warnings)
    return [w for w in warnings if STALE in w]


@pytest.fixture
def generated(tmp_path: Path) -> Path:
    root = tmp_path / "Gate Residence"
    spec = {
        "name": "Gate Residence",
        "gridsX": [5000, 5000, 5000],
        "gridsY": [4500, 4500],
        "storyCount": 2,
        "typicalHeight": 3200,
        "groundHeight": 3600,
    }
    write_building(generate_building(spec), root, "Gate Residence")
    return root


def test_a_freshly_derived_model_of_a_generated_project_is_current(generated: Path) -> None:
    model = _derive(generated)
    # The derivation stamps the settings without the project's details and title block.
    assert "settings=" in model["meta"]["description"]
    assert _warnings(generated, model) == []

    settings_path = generated / SETTINGS_FILE
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    # Windows line endings and the project's details leave the model current.
    settings["project"]["name"] = "Gate Residence, revised"
    settings_path.write_bytes(json.dumps(settings, indent=2).replace("\n", "\r\n").encode())
    assert _warnings(generated, model) == []

    # What the model takes from the settings makes it out of date.
    settings["foundation"]["groundLevel"] = settings["foundation"].get("groundLevel", 0) - 300
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    assert _warnings(generated, model) and SETTINGS_FILE in _warnings(generated, model)[0]


def test_the_other_sources_of_a_fresh_model_are_current_until_they_change(
    generated: Path,
) -> None:
    model = _derive(generated)
    for relative in (
        "06 BIM/bim.json",
        "04 Objects/objects.json",
        "03 Materials/materials.json",
    ):
        path = generated / relative
        original = path.read_text(encoding="utf-8")
        path.write_bytes(original.replace("\n", "\r\n").encode())  # line endings only
        assert _warnings(generated, model) == [], relative
        path.write_text(original + " ", encoding="utf-8")
        assert _warnings(generated, model), relative
        path.write_text(original, encoding="utf-8")
    assert _warnings(generated, model) == []


# ───────────────────────────── the detailing checks that fail ─────────────────────────────


def _check(name: str, utilisation: float, ok: bool, demand: float = 100.0) -> dict[str, Any]:
    return {
        "name": name,
        "demand": demand,
        "capacity": demand / utilisation,
        "unit": "mm",
        "utilisation": utilisation,
        "combination": None,
        "ok": ok,
        "flag": False,
    }


def _design_report(member_fails: bool, joint_fails: bool) -> dict[str, Any]:
    hoops = "Detailing: Hoops over lap splices (8.3.4.2(b))"
    elements = [
        {
            "id": f"B{i}",
            "kind": "beam",
            "type": "B275x600",
            "checks": [
                _check(
                    hoops, 1.2 if member_fails and i == 2 else 1.0, not (member_fails and i == 2)
                )
            ],
        }
        for i in (1, 2)
    ] + [
        {
            "id": "C1",
            "kind": "column",
            "type": "C450x450",
            "checks": [_check("Detailing: First tie from the face (Figure 6.8.8)", 1.0, True)],
        }
    ]
    joint = {
        "id": "C-A2-L4@13200",
        "type": "exterior",
        "beams": ["B1", "B2"],
        "shear": {"Vj": 944.65, "phiVn": 904.27, "utilisation": 1.045},
        "utilisation": 1.045,
        "ok": not joint_fails,
        "checks": [
            _check("Detailing: Strong column / weak beam, C-A2-L4@13200 y", 0.959, True),
            {
                **_check("Detailing: Joint shear, C-A2-L4@13200 y", 1.045, not joint_fails),
                "demand": 944.65,
                "capacity": 904.27,
                "unit": "kN",
            },
        ],
    }
    return {
        "seismic": {"detailingLevel": "special", "checks": [], "applies": {}},
        "elements": elements,
        "joints": [joint],
    }


def test_only_failing_joints_are_listed_as_failing() -> None:
    chapter = _seismic_detailing(_design_report(member_fails=False, joint_fails=True))
    assert chapter["membersFail"]
    assert chapter["members"] == [
        [
            "exterior",
            "joint",
            "Joint shear, C-A2-L4@13200 y",
            "944.6",
            "904.3",
            "kN",
            "1.045",
            "C-A2-L4@13200",
        ]
    ]
    assert chapter["membersBad"] == [True]


def test_failing_members_and_joints_are_listed_and_nothing_that_passes() -> None:
    chapter = _seismic_detailing(_design_report(member_fails=True, joint_fails=True))
    assert chapter["membersFail"]
    rows = [(r[0], r[1], r[6], r[7]) for r in chapter["members"]]
    assert rows == [
        ("B275x600", "beam", "1.200", "B2"),
        ("exterior", "joint", "1.045", "C-A2-L4@13200"),
    ]
    assert all(chapter["membersBad"])


def test_without_failures_the_governing_check_of_each_type() -> None:
    chapter = _seismic_detailing(_design_report(member_fails=False, joint_fails=False))
    assert not chapter["membersFail"]
    assert [(r[0], r[6], r[7]) for r in chapter["members"]] == [
        ("B275x600", "1.000", "–"),
        ("C450x450", "1.000", "–"),
    ]
    assert chapter["membersBad"] == [False, False]


def test_what_fails_is_named() -> None:
    summary = {
        "failed": 8,
        "elements": {"checked": 174, "passed": 174, "failed": 0},
        "joints": {"checked": 72, "failed": 8},
        "seismicChecksFailed": 0,
    }
    assert _failed_text(summary) == "8 beam-column joint(s)"
    summary["elements"]["failed"] = 2
    assert _failed_text(summary) == "2 element(s) and 8 beam-column joint(s)"
    assert _failed_text({"failed": 3}) == "3 element(s)"

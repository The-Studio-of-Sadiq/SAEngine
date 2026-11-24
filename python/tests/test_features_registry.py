"""The ribbon buttons' features (saengine.features): every catalog button has one, and every
feature runs with its default inputs, without a project and on the sample project, returning
a result or a clear problem (never an exception)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from saengine import features

REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "scripts" / "ribbon" / "ribbon_catalog.json"
EXPORT = REPO / "scripts" / "ribbon" / "features.json"
SAMPLE = REPO / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"


def _slug(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)
    return words[0].lower() + "".join(w[:1].upper() + w[1:].lower() for w in words[1:])


def _catalog_ids() -> set[str]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    return {
        f"{group['tab']}.{_slug(button['label'])}"
        for group in catalog["groups"]
        for button in group["buttons"]
        if not button.get("command")
    }


def test_every_catalog_button_has_a_feature_and_the_export_is_current() -> None:
    described = features.describe()
    ids = {f["id"] for f in described}
    assert _catalog_ids() - ids == set()
    assert ids - _catalog_ids() == set()
    # The workbench's copy (scripts/ribbon/features.json) must match the registry.
    exported = json.loads(EXPORT.read_text(encoding="utf-8"))
    assert exported == described


def test_features_have_well_formed_fields() -> None:
    for item in features.describe():
        keys = [f["key"] for f in item["fields"]]
        assert len(keys) == len(set(keys)), item["id"]
        for field in item["fields"]:
            assert field["type"] in {"number", "text", "select", "checkbox"}, item["id"]
            if field["type"] == "select":
                values = [o["value"] for o in field["options"]]
                assert field["default"] in values, (item["id"], field["key"])


@pytest.fixture(scope="module")
def sample_copy(tmp_path_factory: pytest.TempPathFactory) -> str:
    target = tmp_path_factory.mktemp("features") / "Sample Frame"
    shutil.copytree(SAMPLE, target)
    return str(target)


@pytest.mark.parametrize("root_kind", ["none", "sample"])
def test_every_feature_runs_with_its_defaults(root_kind: str, sample_copy: str) -> None:
    root = None if root_kind == "none" else sample_copy
    failures = []
    for item in features.describe():
        try:
            out = features.run(item["id"], root, {})
        except Exception as error:  # noqa: BLE001 - every failure is reported together
            failures.append((item["id"], repr(error)[:160]))
            continue
        assert isinstance(out, dict), item["id"]
        json.dumps(out, allow_nan=False)
    assert failures == []


def test_unknown_feature_and_bad_number_are_problems() -> None:
    assert features.run("nope.nothing", None, {})["problems"]
    out = features.run("soilEarth.activePressure", None, {"height": "tall"})
    assert out["problems"] and "number" in out["problems"][0]

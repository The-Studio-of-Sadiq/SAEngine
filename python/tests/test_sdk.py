"""The public SDK (docs/sdk): the versioned Python API, the generated reference and the example
package with a coded template."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from saengine import api

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "sdk" / "examples"


def test_api_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", api.API_VERSION)


def test_every_public_name_resolves():
    for name in api.__all__:
        assert getattr(api, name) is not None, name
    assert set(api.__all__) == {"API_VERSION", *api.exports()}
    with pytest.raises(AttributeError):
        api.not_a_public_name  # noqa: B018


def test_reference_is_up_to_date():
    spec = importlib.util.spec_from_file_location(
        "gen_sdk_reference", ROOT / "scripts" / "docs" / "gen_sdk_reference.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    current = (ROOT / "docs" / "sdk" / "reference.md").read_text(encoding="utf-8")
    assert module.generate() == current, "run python -I scripts/docs/gen_sdk_reference.py"
    methods = {m["name"] for m in module.rpc_methods(module.SRC / "saengine/rpc/server.py",
                                                     module.SRC / "saengine/rpc/handlers.py")}  # fmt: skip
    assert {"codes/list", "codes/remove", "codes/templates", "codes/codedGeometry"} <= methods


def test_example_package_makes_its_portal_frame(tmp_path):
    from saengine.codes import Registry
    from saengine.codes.trust import TrustStore

    reg = Registry(tmp_path / "builtin", tmp_path / "user" / "code-packs",
                   TrustStore(tmp_path / "trust.json"))  # fmt: skip
    (tmp_path / "builtin").mkdir()
    info = reg.install(EXAMPLES / "portal-frames", "user")
    assert info.usable, info.problems
    reg.set_trusted("portal-frames", True, kind="structureTemplate")
    geometry = api.coded_geometry(
        "portal-frames", "templates/portal.json", {"span": 20000}, registry=reg, member_type="B1"
    )
    assert [m["type"] for m in geometry["members"]] == ["B1"] * 4
    assert geometry["members"][1]["end"] == [10000.0, 0.0, 7500.0]  # apex: span / 2, eaves + rise
